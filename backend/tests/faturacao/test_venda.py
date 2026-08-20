"""A conta do balcão (Plano 2B, Task 2) — fat_vendas.

Mesmo padrão de duplo de base de dados que test_caixa_endpoints.py:
find()/find_one() filtram de facto pelos campos do filtro, e as leituras
devolvem cópias como o Motor (ver `ColeccaoFalsa` — foi um aliasing aqui que
pôs um teste do cancelamento a defender um defeito). Nenhum teste liga a uma
base de dados nem à rede.

A regra central deste ficheiro (repetida em vários testes, de propósito): os
totais NUNCA são inventados aqui — são sempre a soma do que
`precos.linha_de_venda` (a MESMA função que constrói as linhas da fatura)
devolveria para cada linha. Se o endpoint alguma vez calculasse um total por
fora dessa função, o que a operadora vê no ecrã e o que sai no papel podiam
divergir ao cêntimo — e é exactamente isso que os testes de "totais
conferidos" vão apanhar.

Três testes montam o router REAL numa app FastAPI e falam com ela pelo
TestClient (mesmo padrão de test_saude.py): é a única forma honesta de provar
resolução de rotas — o conflito de caminhos, a existir, é entre venda.py e
fiscal.py, e essas duas só se encontram no router de faturacao/__init__.py.
Continua tudo dentro do processo: nenhuma ligação sai daqui.
"""
import asyncio
from copy import deepcopy
from datetime import datetime

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from faturacao import router as router_do_modulo
from faturacao import venda as venda_mod
from faturacao.db import COLECOES
# A MESMA função que a rota usa para escolher os campos do documento — o
# teste compara com ela, e não com um dicionário escrito à mão aqui: uma
# cópia local ficava verde no dia em que as duas divergissem, que é
# precisamente o defeito que se quer impedir.
from faturacao.fiscal import _resposta_documento
from faturacao.pos_auth import operador_atual
from faturacao.precos import linha_de_venda
from faturacao.venda import (
    PedidoDescontoGlobal,
    PedidoEditarLinha,
    PedidoJuntarLinha,
    PedidoNovaVenda,
    abrir_venda,
    aplicar_desconto_global,
    cancelar_venda,
    editar_linha,
    juntar_linha,
    obter_venda,
    remover_linha,
    venda_aberta,
)


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- Duplo de base de dados (mesmo padrão de test_caixa_endpoints.py) --------


def _corresponde(item, filtro):
    """Réplica minimalista do casamento de filtro do Mongo: igualdade exacta
    em cada campo — com suporte extra a `{"$in": [...]}` (mesmo padrão de
    test_pos_auth.py), que é como `juntar_linha` (Task 3) vai buscar os
    grupos de personalização das opções da linha."""
    if not filtro:
        return True
    for chave, valor in filtro.items():
        if isinstance(valor, dict) and "$in" in valor:
            if item.get(chave) not in valor["$in"]:
                return False
        elif item.get(chave) != valor:
            return False
    return True


class CursorFalso:
    """Cursor de mentira que ORDENA e LIMITA a sério.

    Ao contrário do cursor de test_caixa_endpoints.py, cujo `sort()` só se
    devolve a si próprio: aqui isso não servia. O teste da "conta mais
    recente" passaria na mesma se `venda_aberta` se esquecesse do
    `.sort("criada_em", -1)`, porque a ordem certa vinha por acaso da ordem
    de inserção — um teste que continua verde com o código de produção
    partido não defende nada (já aconteceu 3× neste módulo)."""

    def __init__(self, itens):
        self._itens = list(itens)

    def sort(self, campo, direccao=1):
        self._itens.sort(key=lambda d: d.get(campo), reverse=(direccao == -1))
        return self

    async def to_list(self, n=None):
        return self._itens if n is None else self._itens[:n]


class ResultadoUpdateFalso:
    """Réplica minimalista do UpdateResult do pymongo/motor (mesmo duplo de
    test_caixa_endpoints.py) — só o `matched_count`, que é o que decide se a
    escrita CONDICIONAL do cancelamento encontrou mesmo a venda ainda
    aberta, em vez de aplicar o $set às cegas."""

    def __init__(self, matched_count):
        self.matched_count = matched_count
        self.modified_count = matched_count


class ColeccaoFalsa:
    """Duplo de uma colecção Mongo. As leituras devolvem CÓPIAS, como o
    Motor.

    Devolver o próprio documento guardado (era o que este duplo fazia) cria
    um aliasing que o Motor real não tem: ler com `find_one` e escrever com
    `update_one` passavam a mexer no MESMO objecto, e o dicionário que o
    código de produção tinha em mãos actualizava-se sozinho. Um teste que
    lesse a resposta da rota ficava verde mesmo com a linha que a constrói
    apagada — provado: sem o `venda.update(...)` de `cancelar_venda`, a
    suite inteira continuava verde. Em produção, `find_one` devolve um
    dicionário NOVO, descodificado do BSON, e essa resposta saía com
    `estado: "aberta"` para uma conta acabada de cancelar.

    Cópia PROFUNDA, não `dict(d)`: as linhas da venda vivem numa lista
    aninhada, e uma cópia rasa deixava essa lista partilhada — o mesmo
    aliasing, só que um nível mais abaixo. O `insert_one` guarda pela mesma
    razão uma cópia: em produção o que fica gravado é BSON, e nada do que o
    código de produção faça ao dicionário que inseriu volta a tocar-lhe."""

    def __init__(self, registo, documentos=None):
        self.registo = registo
        self._documentos = documentos if documentos is not None else []

    def find(self, filtro=None, projecao=None):
        self.registo.append(("find", filtro))
        return CursorFalso(
            [deepcopy(d) for d in self._documentos if _corresponde(d, filtro)]
        )

    async def find_one(self, filtro, projecao=None):
        self.registo.append(("find_one", filtro))
        encontrados = [d for d in self._documentos if _corresponde(d, filtro)]
        return deepcopy(encontrados[0]) if encontrados else None

    async def insert_one(self, doc):
        self.registo.append(("insert_one", dict(doc)))
        self._documentos.append(deepcopy(doc))
        return None

    async def update_one(self, filtro, atualizacao):
        self.registo.append(("update_one", filtro, atualizacao))
        alvos = [d for d in self._documentos if _corresponde(d, filtro)]
        if alvos:
            alvos[0].update(atualizacao.get("$set", {}))
        return ResultadoUpdateFalso(matched_count=len(alvos))


class DbFalsa:
    def __init__(self, coleccoes):
        self._coleccoes = coleccoes

    def __getitem__(self, nome):
        return self._coleccoes.setdefault(nome, ColeccaoFalsa([]))


def _db(registo, caixas=None, sessoes=None, vendas=None, produtos=None, refs=None,
        documentos=None, grupos=None):
    return DbFalsa({
        COLECOES["caixas"]: ColeccaoFalsa(registo, caixas),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa(registo, sessoes),
        COLECOES["vendas"]: ColeccaoFalsa(registo, vendas),
        COLECOES["produtos"]: ColeccaoFalsa(registo, produtos),
        # A reserva de emissão do fiscal.py — o cancelamento pergunta por
        # ela antes de deitar uma conta fora.
        COLECOES["refs_fiscais"]: ColeccaoFalsa(registo, refs),
        # O documento fiscal gravado por `fiscal.py::_gravar_documento`: é o
        # que `GET /pos/venda/{venda_id}` devolve a quem perdeu a resposta do
        # EMITIR e ficou sem número nem ATCUD no ecrã.
        COLECOES["documentos"]: ColeccaoFalsa(registo, documentos),
        # Os grupos de personalização (Task 1/3): `juntar_linha` consulta-os
        # pelo `grupo_id` das opções para carimbar o retrato do
        # `sai_na_fatura` em cada opção da linha. Vazio por omissão, como as
        # outras colecções — a maioria dos testes deste ficheiro não junta
        # opções com grupo nenhum.
        COLECOES["grupos_personalizacao"]: ColeccaoFalsa(registo, grupos),
    })


def _operador(**over):
    o = {"operador_id": "op-1", "nome": "Rafaela", "perfil": "operador_caixa", "loja_id": "loja-1"}
    o.update(over)
    return o


def _caixa(**over):
    c = {"id": "caixa-1", "loja_id": "loja-1", "nome": "Balcão"}
    c.update(over)
    return c


def _sessao(**over):
    s = {
        "id": "sessao-1", "caixa_id": "caixa-1", "loja_id": "loja-1",
        "aberta_por": {"id": "op-1", "nome": "Rafaela"}, "aberta_em": "2026-08-15T09:00:00+00:00",
        "fundo": 50.0, "estado": "aberta", "fechada_por": None, "fechada_em": None,
        "contado": None, "esperado": None, "diferenca": None,
    }
    s.update(over)
    return s


def _produto(**over):
    p = {
        "id": "prod-1", "nome": "Açaí Regular", "preco": 8.99, "tax_id": "INT",
        "categoria_id": "cat-1", "foto_url": None, "grupos_personalizacao": [], "ativo": True,
        "vendus_ref": None,
    }
    p.update(over)
    return p


def _venda(**over):
    v = {
        "id": "venda-1", "loja_id": "loja-1", "caixa_id": "caixa-1", "sessao_id": "sessao-1",
        "operador_id": "op-1", "linhas": [], "desconto_global_pct": None,
        "desconto_global_eur": None, "estado": "aberta", "criada_em": "2026-08-15T09:05:00+00:00",
    }
    v.update(over)
    return v


def _reserva(**over):
    """Uma reserva de emissão como `fiscal.py::_reservar` a insere.

    A `ext_ref` está aqui só porque o documento real a tem: o que este
    módulo lê é o `venda_id`, e é de propósito — a fórmula da ext_ref é a
    chave da idempotência e não pode ter uma segunda fonte (nem no código,
    nem num teste que a copiasse e a deixasse divergir em silêncio)."""
    r = {
        "id": "ref-1", "ext_ref": "pos-loja-1-sessao-1-venda-1",
        "venda_id": "venda-1", "criado_em": "2026-08-15T09:06:00+00:00",
    }
    r.update(over)
    return r


def _documento(**over):
    """Um documento fiscal como `fiscal.py::_gravar_documento` o grava —
    incluindo os campos que NÃO são para sair na resposta (`ext_ref`,
    `loja_id`, `emitido_em`), para que a comparação com
    `_resposta_documento` tenha alguma coisa que possa apanhar."""
    d = {
        "id": "doc-1", "vendus_document_id": 8801, "atcud": "JFT7-1",
        "numero": "FS 2026PDV/1", "total": 8.99, "modo": "normal",
        "ext_ref": "pos-loja-1-sessao-1-venda-1", "venda_id": "venda-1",
        "loja_id": "loja-1", "emitido_em": "2026-08-15T09:07:00+00:00",
    }
    d.update(over)
    return d


def _linha(**over):
    li = {
        "id": "linha-1", "produto_id": "prod-1", "produto_nome": "Açaí Regular",
        "produto_preco": 8.99, "produto_tax_id": "INT", "quantidade": 1, "opcoes": [],
        "preco_override": None, "tax_override": None, "desconto_pct": None, "desconto_eur": None,
    }
    li.update(over)
    return li


# --- Abrir venda ---------------------------------------------------------------


def test_abrir_venda_com_sucesso(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(abrir_venda(PedidoNovaVenda(caixa_id="caixa-1"), operador=_operador()))
    assert resultado["estado"] == "aberta"
    assert resultado["caixa_id"] == "caixa-1"
    assert resultado["sessao_id"] == "sessao-1"
    assert resultado["operador_id"] == "op-1"
    assert resultado["loja_id"] == "loja-1"
    assert resultado["linhas"] == []
    assert resultado["totais"] == {
        "subtotal": 0.0, "desconto_linhas": 0.0, "desconto_global": 0.0, "total": 0.0,
    }


def test_abrir_venda_sem_sessao_aberta_e_recusado_409(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(abrir_venda(PedidoNovaVenda(caixa_id="caixa-1"), operador=_operador()))
    assert excinfo.value.status_code == 409


def test_abrir_venda_em_caixa_de_outra_loja_e_recusado_404(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa(loja_id="loja-2")], sessoes=[])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(abrir_venda(PedidoNovaVenda(caixa_id="caixa-1"), operador=_operador()))
    assert excinfo.value.status_code == 404


def test_abrir_venda_usa_o_operador_e_a_sessao_do_token_nunca_do_corpo():
    """PedidoNovaVenda nem sequer declara sessao_id/operador_id — mesmo que
    apareçam no JSON, o pydantic ignora-os. A sessão e o operador vêm sempre
    de `operador_atual` (o token) e da sessão aberta resolvida no servidor."""
    dados = PedidoNovaVenda.model_validate(
        {"caixa_id": "caixa-1", "sessao_id": "sessao-estranha", "operador_id": "op-estranho"}
    )
    assert not hasattr(dados, "sessao_id")
    assert not hasattr(dados, "operador_id")


# --- Juntar linha ----------------------------------------------------------


def test_juntar_linha_com_sucesso(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], vendas=[_venda()], produtos=[_produto()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(juntar_linha(
        "venda-1", PedidoJuntarLinha(produto_id="prod-1", quantidade=2), operador=_operador()
    ))
    assert len(resultado["linhas"]) == 1
    linha = resultado["linhas"][0]
    assert linha["produto_id"] == "prod-1"
    assert linha["produto_nome"] == "Açaí Regular"
    assert linha["produto_preco"] == 8.99
    assert linha["produto_tax_id"] == "INT"
    assert linha["quantidade"] == 2
    assert resultado["totais"]["subtotal"] == 17.98
    assert resultado["totais"]["total"] == 17.98


def test_juntar_duas_linhas_acumula(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], vendas=[_venda()],
              produtos=[_produto(), _produto(id="prod-2", nome="Sumo", preco=2.5, tax_id="NOR")])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    _corre(juntar_linha("venda-1", PedidoJuntarLinha(produto_id="prod-1", quantidade=1), operador=_operador()))
    resultado = _corre(juntar_linha(
        "venda-1", PedidoJuntarLinha(produto_id="prod-2", quantidade=1), operador=_operador()
    ))
    assert len(resultado["linhas"]) == 2
    assert resultado["totais"]["subtotal"] == round(8.99 + 2.5, 2)


def test_juntar_linha_com_personalizacoes_soma_ao_preco(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], vendas=[_venda()], produtos=[_produto()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    opcoes = [{"nome": "Nutella", "preco": 0.95}]
    resultado = _corre(juntar_linha(
        "venda-1", PedidoJuntarLinha(produto_id="prod-1", quantidade=1, opcoes=opcoes),
        operador=_operador(),
    ))
    assert resultado["totais"]["subtotal"] == 9.94


def test_juntar_linha_venda_inexistente_e_recusado_404(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], vendas=[], produtos=[_produto()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(juntar_linha(
            "venda-x", PedidoJuntarLinha(produto_id="prod-1"), operador=_operador()
        ))
    assert excinfo.value.status_code == 404


def test_juntar_linha_venda_de_outra_loja_e_recusado_404(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda(loja_id="loja-2")], produtos=[_produto()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(juntar_linha(
            "venda-1", PedidoJuntarLinha(produto_id="prod-1"), operador=_operador()
        ))
    assert excinfo.value.status_code == 404


def test_juntar_linha_produto_inexistente_e_recusado_404(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda()], produtos=[])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(juntar_linha(
            "venda-1", PedidoJuntarLinha(produto_id="prod-nao-existe"), operador=_operador()
        ))
    assert excinfo.value.status_code == 404


def test_juntar_produto_sem_iva_nao_entra_na_conta(monkeypatch):
    """A regra central da Task 2: um produto sem IVA definido não entra na
    conta, com um erro claro — nunca um valor assumido (13% por omissão,
    como a app antiga fazia)."""
    registo = []
    produto_sem_iva = _produto(tax_id=None)
    db = _db(registo, vendas=[_venda()], produtos=[produto_sem_iva])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(juntar_linha(
            "venda-1", PedidoJuntarLinha(produto_id="prod-1"), operador=_operador()
        ))
    assert excinfo.value.status_code == 422
    assert "IVA" in excinfo.value.detail
    # Não gravou nada.
    assert db._coleccoes[COLECOES["vendas"]]._documentos[0]["linhas"] == []


def test_juntar_produto_sem_iva_no_catalogo_e_recusado_mesmo_com_tax_override(monkeypatch):
    """A distinção que justifica verificar `erros_do_produto` no PRÓPRIO
    produto, e não confiar só na validação de `linha_de_venda`: um
    `tax_override` faria `linha_de_venda` aceitar a linha na mesma (o
    override substitui o tax_id em falta) — mas um produto mal configurado
    no catálogo não pode ser "salvo" ad-hoc no balcão. Corrige-se no
    catálogo, não com um override a tapar o buraco."""
    registo = []
    produto_sem_iva = _produto(tax_id=None)
    db = _db(registo, vendas=[_venda()], produtos=[produto_sem_iva])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(juntar_linha(
            "venda-1", PedidoJuntarLinha(produto_id="prod-1", tax_override="NOR"),
            operador=_operador(),
        ))
    assert excinfo.value.status_code == 422
    assert "IVA" in excinfo.value.detail


def test_juntar_produto_sem_preco_nao_entra_na_conta(monkeypatch):
    registo = []
    produto_sem_preco = _produto(preco=None)
    db = _db(registo, vendas=[_venda()], produtos=[produto_sem_preco])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(juntar_linha(
            "venda-1", PedidoJuntarLinha(produto_id="prod-1"), operador=_operador()
        ))
    assert excinfo.value.status_code == 422
    assert "preço" in excinfo.value.detail.lower()


def test_juntar_linha_com_tax_override_invalido_e_recusado_422(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda()], produtos=[_produto()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(juntar_linha(
            "venda-1", PedidoJuntarLinha(produto_id="prod-1", tax_override="XPTO"),
            operador=_operador(),
        ))
    assert excinfo.value.status_code == 422


def test_juntar_linha_em_venda_emitida_e_recusado_409(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda(estado="emitida")], produtos=[_produto()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(juntar_linha(
            "venda-1", PedidoJuntarLinha(produto_id="prod-1"), operador=_operador()
        ))
    assert excinfo.value.status_code == 409
    assert not any(chamada[0] == "update_one" for chamada in registo)


def test_juntar_linha_com_quantidade_zero_e_recusado():
    with pytest.raises(ValidationError):
        PedidoJuntarLinha(produto_id="prod-1", quantidade=0)


def test_juntar_linha_guarda_as_respostas_de_texto(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda()], produtos=[_produto()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(juntar_linha(
        "venda-1", PedidoJuntarLinha(
            produto_id="prod-1", quantidade=1,
            respostas_texto=[{"grupo_id": "g-nome", "nome_grupo": "Nome", "texto": "Maria"}],
        ), operador=_operador()
    ))
    assert resultado["linhas"][0]["respostas_texto"] == [
        {"grupo_id": "g-nome", "nome_grupo": "Nome", "texto": "Maria"}
    ]


def test_juntar_linha_carimba_o_sai_na_fatura_de_cada_opcao(monkeypatch):
    """Retrato, pela mesma razão que o preço: o gestor pode desligar o
    interruptor amanhã, e o que saiu no papel não muda."""
    registo = []
    grupo = {
        "id": "g1", "nome": "Consumir na loja", "sai_na_fatura": False,
        "opcoes": [{"id": "o1", "nome": "Levar", "preco": 0}],
    }
    db = _db(registo, vendas=[_venda()], produtos=[_produto()], grupos=[grupo])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(juntar_linha(
        "venda-1", PedidoJuntarLinha(
            produto_id="prod-1", quantidade=1,
            opcoes=[{"id": "o1", "grupo_id": "g1", "nome": "Levar", "preco": 0}],
        ), operador=_operador()
    ))
    assert resultado["linhas"][0]["opcoes"][0]["sai_na_fatura"] is False


# --- Alterar quantidade / editar linha --------------------------------------


def test_alterar_quantidade_com_sucesso(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[_linha(quantidade=1)])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(editar_linha(
        "venda-1", "linha-1", PedidoEditarLinha(quantidade=3), operador=_operador()
    ))
    assert resultado["linhas"][0]["quantidade"] == 3
    assert resultado["totais"]["subtotal"] == round(8.99 * 3, 2)


def test_editar_linha_aplica_desconto_por_linha_em_percentagem(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[_linha(quantidade=2)])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(editar_linha(
        "venda-1", "linha-1", PedidoEditarLinha(desconto_pct=10), operador=_operador()
    ))
    bruto = round(8.99 * 2, 2)
    assert resultado["totais"]["subtotal"] == bruto
    assert resultado["totais"]["desconto_linhas"] == round(bruto * 0.10, 2)
    assert resultado["totais"]["total"] == round(bruto - bruto * 0.10, 2)


def test_editar_linha_aplica_desconto_por_linha_em_euros(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[_linha(quantidade=2)])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(editar_linha(
        "venda-1", "linha-1", PedidoEditarLinha(desconto_eur=3.0), operador=_operador()
    ))
    bruto = round(8.99 * 2, 2)
    assert resultado["totais"]["desconto_linhas"] == 3.0
    assert resultado["totais"]["total"] == round(bruto - 3.0, 2)


def test_editar_linha_com_preco_override(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[_linha(quantidade=1)])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(editar_linha(
        "venda-1", "linha-1", PedidoEditarLinha(preco_override=5.0), operador=_operador()
    ))
    assert resultado["totais"]["subtotal"] == 5.0


def test_editar_linha_inexistente_e_recusado_404(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[_linha()])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(editar_linha(
            "venda-1", "linha-x", PedidoEditarLinha(quantidade=2), operador=_operador()
        ))
    assert excinfo.value.status_code == 404


def test_editar_linha_em_venda_emitida_e_recusado_409(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda(estado="emitida", linhas=[_linha()])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(editar_linha(
            "venda-1", "linha-1", PedidoEditarLinha(quantidade=2), operador=_operador()
        ))
    assert excinfo.value.status_code == 409


def test_editar_linha_com_override_invalido_nao_grava_nada(monkeypatch):
    """Uma edição recusada não pode deixar a linha meio-alterada: a validação
    corre ANTES de qualquer escrita."""
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[_linha(quantidade=1)])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException):
        _corre(editar_linha(
            "venda-1", "linha-1", PedidoEditarLinha(preco_override=8.995), operador=_operador()
        ))
    linha_intacta = db._coleccoes[COLECOES["vendas"]]._documentos[0]["linhas"][0]
    assert linha_intacta["quantidade"] == 1
    assert linha_intacta["preco_override"] is None


def test_editar_linha_reenviando_opcoes_mantem_o_carimbo_do_sai_na_fatura(monkeypatch):
    """Achado da revisão da Task 3: `PosDialogoProduto.js` reenvia SEMPRE as
    opções inteiras por `editarLinha` (nunca só o delta de uma opção), e
    `PosPersonalizacoes.js` constrói cada opção escolhida de raiz — sem
    `sai_na_fatura`. Uma linha que já tinha o carimbo (posto por
    `juntar_linha`) não pode perdê-lo só por a operadora ter voltado a abrir
    o diálogo e picado mais um topping: sem isto, o 'Levar' de um grupo
    escondido (`sai_na_fatura=False`) reaparecia no título e ia para a
    Fatura Simplificada real, que é o que o interruptor existe para impedir."""
    registo = []
    grupo_servico = {
        "id": "g-serv", "nome": "Consumir na loja", "sai_na_fatura": False,
        "opcoes": [{"id": "o1", "nome": "Levar", "preco": 0}],
    }
    linha_ja_carimbada = _linha(opcoes=[
        {"id": "o1", "grupo_id": "g-serv", "nome": "Levar", "preco": 0, "sai_na_fatura": False},
    ])
    db = _db(registo, vendas=[_venda(linhas=[linha_ja_carimbada])], grupos=[grupo_servico])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    # A app reenvia a opção "Levar" tal como o PosPersonalizacoes.js a
    # constrói de raiz — SEM `sai_na_fatura` — mais uma Nutella escolhida
    # agora.
    resultado = _corre(editar_linha(
        "venda-1", "linha-1", PedidoEditarLinha(opcoes=[
            {"id": "o1", "grupo_id": "g-serv", "nome": "Levar", "preco": 0},
            {"id": "o2", "grupo_id": "g-top", "nome": "Nutella", "preco": 0.5},
        ]), operador=_operador()
    ))
    opcoes = resultado["linhas"][0]["opcoes"]
    assert next(o for o in opcoes if o["id"] == "o1")["sai_na_fatura"] is False
    # A opção do grupo que não está em `grupos_da_linha` (sem entrada em
    # fat_grupos_personalizacao) fica com o valor por omissão — visível,
    # como manda o brief da Task 1.
    assert next(o for o in opcoes if o["id"] == "o2")["sai_na_fatura"] is True


# --- Remover linha -----------------------------------------------------------


def test_remover_linha_com_sucesso(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[
        _linha(id="linha-1"), _linha(id="linha-2", produto_id="prod-2", produto_nome="Sumo",
                                      produto_preco=2.5, produto_tax_id="NOR"),
    ])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(remover_linha("venda-1", "linha-1", operador=_operador()))
    assert [li["id"] for li in resultado["linhas"]] == ["linha-2"]
    assert resultado["totais"]["subtotal"] == 2.5


def test_remover_ultima_linha_deixa_totais_a_zero(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[_linha()])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(remover_linha("venda-1", "linha-1", operador=_operador()))
    assert resultado["linhas"] == []
    assert resultado["totais"]["total"] == 0.0


def test_remover_linha_inexistente_e_recusado_404(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[_linha()])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(remover_linha("venda-1", "linha-x", operador=_operador()))
    assert excinfo.value.status_code == 404


def test_remover_linha_em_venda_emitida_e_recusado_409(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda(estado="emitida", linhas=[_linha()])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(remover_linha("venda-1", "linha-1", operador=_operador()))
    assert excinfo.value.status_code == 409


# --- Desconto global -----------------------------------------------------------


def test_desconto_global_em_percentagem(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[_linha(quantidade=2)])])  # 17.98
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(aplicar_desconto_global(
        "venda-1", PedidoDescontoGlobal(desconto_pct=10), operador=_operador()
    ))
    assert resultado["totais"]["subtotal"] == 17.98
    assert resultado["totais"]["desconto_global"] == round(17.98 * 0.10, 2)
    assert resultado["totais"]["total"] == round(17.98 - 17.98 * 0.10, 2)


def test_desconto_global_em_euros_tem_precedencia_sobre_percentagem(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[_linha(quantidade=2)])])  # 17.98
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(aplicar_desconto_global(
        "venda-1", PedidoDescontoGlobal(desconto_pct=10, desconto_eur=2.0), operador=_operador()
    ))
    assert resultado["totais"]["desconto_global"] == 2.0
    assert resultado["totais"]["total"] == round(17.98 - 2.0, 2)


def test_desconto_global_aplica_se_depois_do_desconto_por_linha(monkeypatch):
    """O desconto global incide sobre o que falta depois dos descontos por
    linha, não sobre o subtotal bruto — 'desconto na conta toda' é o
    último passo, não em paralelo com os descontos já dados linha a linha."""
    registo = []
    db = _db(registo, vendas=[_venda(
        linhas=[_linha(quantidade=2, desconto_eur=1.0)],  # 17.98 - 1.0 = 16.98
        desconto_global_pct=10,
    )])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(aplicar_desconto_global(
        "venda-1", PedidoDescontoGlobal(desconto_pct=10), operador=_operador()
    ))
    liquido_linhas = round(17.98 - 1.0, 2)
    assert resultado["totais"]["desconto_linhas"] == 1.0
    assert resultado["totais"]["desconto_global"] == round(liquido_linhas * 0.10, 2)
    assert resultado["totais"]["total"] == round(liquido_linhas - liquido_linhas * 0.10, 2)


def test_desconto_global_em_venda_emitida_e_recusado_409(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda(estado="emitida")])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(aplicar_desconto_global(
            "venda-1", PedidoDescontoGlobal(desconto_pct=10), operador=_operador()
        ))
    assert excinfo.value.status_code == 409


def test_desconto_global_eur_negativo_e_recusado():
    with pytest.raises(ValidationError):
        PedidoDescontoGlobal(desconto_eur=-1.0)


def test_desconto_global_pct_acima_de_100_e_recusado():
    with pytest.raises(ValidationError):
        PedidoDescontoGlobal(desconto_pct=150)


def test_desconto_global_eur_com_3_casas_e_recusado():
    with pytest.raises(ValidationError):
        PedidoDescontoGlobal(desconto_eur=2.005)


# --- Totais conferidos ao cêntimo contra o linha_de_venda --------------------


def test_totais_conferidos_ao_centimo_contra_linha_de_venda(monkeypatch):
    """A prova directa da regra de ouro da Task 2: para cada linha guardada,
    o total que o endpoint devolve tem de bater, ao cêntimo, com o que
    `linha_de_venda` (a mesma função que vai construir as linhas da fatura)
    calcularia para essas mesmas linhas — nunca uma soma inventada à parte."""
    registo = []
    linhas_brutas = [
        _linha(id="l1", produto_id="prod-1", produto_nome="Açaí Regular",
               produto_preco=8.99, produto_tax_id="INT", quantidade=2, desconto_pct=10),
        _linha(id="l2", produto_id="prod-2", produto_nome="Sumo", produto_preco=2.5,
               produto_tax_id="NOR", quantidade=3, desconto_eur=1.0),
    ]
    db = _db(registo, vendas=[_venda(linhas=linhas_brutas, desconto_global_eur=1.5)])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    # Lê os totais através de uma edição no-op (sem alterar nada) para obter
    # a venda com totais calculados, sem depender de nenhum endpoint GET.
    resultado = _corre(editar_linha(
        "venda-1", "l1", PedidoEditarLinha(quantidade=2), operador=_operador()
    ))

    li1_vendus = linha_de_venda(
        {"nome": "Açaí Regular", "preco": 8.99, "tax_id": "INT"}, 2, desconto_pct=10,
    )
    li2_vendus = linha_de_venda(
        {"nome": "Sumo", "preco": 2.5, "tax_id": "NOR"}, 3, desconto_eur=1.0,
    )
    bruto_esperado = round(li1_vendus["qty"] * li1_vendus["gross_price"]
                            + li2_vendus["qty"] * li2_vendus["gross_price"], 2)
    desconto_l1 = round(li1_vendus["qty"] * li1_vendus["gross_price"] * li1_vendus["discount_percentage"] / 100, 2)
    desconto_l2 = round(li2_vendus["discount_amount"], 2)
    desconto_linhas_esperado = round(desconto_l1 + desconto_l2, 2)
    liquido_esperado = round(bruto_esperado - desconto_linhas_esperado, 2)
    total_esperado = round(liquido_esperado - 1.5, 2)

    assert resultado["totais"]["subtotal"] == bruto_esperado
    assert resultado["totais"]["desconto_linhas"] == desconto_linhas_esperado
    assert resultado["totais"]["desconto_global"] == 1.5
    assert resultado["totais"]["total"] == total_esperado


# --- Recuperar a conta em curso (GET /pos/venda/aberta) ----------------------
#
# Porque é que esta rota existe: sem ela, `POST /pos/venda` era a única
# entrada e criava SEMPRE uma conta nova. A tela de descanso ao fim de 5
# minutos, um F5 no PC da loja ou um browser que vai abaixo faziam a operadora
# perder o que já tinha picado — com o cliente à frente — e deixavam uma venda
# `aberta` órfã em fat_vendas por cada recarregamento, para sempre.


def test_venda_aberta_devolve_a_conta_em_curso_da_sessao(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()],
             vendas=[_venda(linhas=[_linha(quantidade=2)])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(venda_aberta(caixa_id="caixa-1", operador=_operador()))
    assert resultado["id"] == "venda-1"
    assert resultado["estado"] == "aberta"
    assert [li["id"] for li in resultado["linhas"]] == ["linha-1"]

    # Mesmo formato das outras rotas, totais incluídos (senão o ecrã tinha
    # dois formatos da mesma conta) — e conferidos contra o `linha_de_venda`,
    # nunca contra um número escrito à mão aqui.
    li_vendus = linha_de_venda({"nome": "Açaí Regular", "preco": 8.99, "tax_id": "INT"}, 2)
    assert resultado["totais"]["subtotal"] == round(li_vendus["qty"] * li_vendus["gross_price"], 2)
    assert resultado["totais"]["total"] == resultado["totais"]["subtotal"]


def test_venda_aberta_sem_nenhuma_conta_devolve_null_e_nao_404(monkeypatch):
    """O estado normal do início do dia: caixa aberta, nada picado ainda. Um
    404 aqui obrigava o ecrã a tratar "ainda não há conta" como um erro."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()], vendas=[])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    assert _corre(venda_aberta(caixa_id="caixa-1", operador=_operador())) is None


def test_venda_aberta_ignora_as_vendas_de_outra_sessao_caixa_ou_loja(monkeypatch):
    """Só a sessão ABERTA desta caixa conta. A conta da sessão de ontem na
    mesma caixa, a da caixa do lado e a da loja ao lado vivem todas na mesma
    colecção ao mesmo tempo — devolver qualquer uma delas punha a operadora a
    facturar a conta de outra pessoa."""
    registo = []
    db = _db(
        registo,
        caixas=[_caixa()],
        sessoes=[_sessao()],
        vendas=[
            _venda(id="v-sessao-de-ontem", sessao_id="sessao-0"),
            _venda(id="v-outra-caixa", caixa_id="caixa-2", sessao_id="sessao-2"),
            _venda(id="v-outra-loja", loja_id="loja-2", caixa_id="caixa-9",
                   sessao_id="sessao-9"),
        ],
    )
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    assert _corre(venda_aberta(caixa_id="caixa-1", operador=_operador())) is None


def test_venda_aberta_ignora_as_ja_emitidas_e_as_canceladas(monkeypatch):
    """Uma conta já facturada (ou deitada fora) não é uma conta em curso —
    devolvê-la punha a operadora a acrescentar artigos a uma venda que já
    tem Fatura Simplificada na AT."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()], vendas=[
        _venda(id="v-emitida", estado="emitida"),
        _venda(id="v-cancelada", estado="cancelada"),
    ])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    assert _corre(venda_aberta(caixa_id="caixa-1", operador=_operador())) is None


def test_venda_aberta_com_varias_devolve_a_mais_recente(monkeypatch):
    """Ordem de inserção deliberadamente baralhada (nem a primeira nem a
    última da lista é a certa): se a rota deixar cair o
    `.sort("criada_em", -1)`, ou o ordenar ao contrário, sai a conta errada e
    a operadora continua a picar por cima de uma conta antiga."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()], vendas=[
        _venda(id="v-meio", criada_em="2026-08-15T10:00:00+00:00"),
        _venda(id="v-antiga", criada_em="2026-08-15T09:00:00+00:00"),
        _venda(id="v-recente", criada_em="2026-08-15T11:00:00+00:00"),
    ])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(venda_aberta(caixa_id="caixa-1", operador=_operador()))
    assert resultado["id"] == "v-recente"


def test_venda_aberta_nao_se_limita_ao_operador_que_a_abriu(monkeypatch):
    """A decisão que está escrita na docstring da rota: ao balcão a conta é
    da CAIXA, não da pessoa. A Rafaela picou três artigos, a tela de descanso
    caiu e a Ana entrou com o PIN dela — a conta tem de continuar lá, é o
    cliente que está à espera. Quem picou continua registado em
    `operador_id`."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()],
             vendas=[_venda(operador_id="op-1", linhas=[_linha()])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    ana = _operador(operador_id="op-2", nome="Ana")
    resultado = _corre(venda_aberta(caixa_id="caixa-1", operador=ana))
    assert resultado is not None, "a conta da Rafaela perdeu-se ao entrar a Ana"
    assert resultado["id"] == "venda-1"
    assert resultado["operador_id"] == "op-1"


def test_venda_aberta_sem_sessao_aberta_e_recusado_409(monkeypatch):
    """Sem caixa aberta não há conta nenhuma para recuperar — o 409 de
    `_sessao_aberta` é a resposta certa, e não um `null` que faria o ecrã
    parecer pronto a vender com a caixa fechada."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[], vendas=[_venda()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(venda_aberta(caixa_id="caixa-1", operador=_operador()))
    assert excinfo.value.status_code == 409


def test_venda_aberta_em_caixa_de_outra_loja_e_recusado_404(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa(loja_id="loja-2")], sessoes=[_sessao()],
             vendas=[_venda()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(venda_aberta(caixa_id="caixa-1", operador=_operador()))
    assert excinfo.value.status_code == 404


# --- O caminho /pos/venda/aberta contra as rotas de {venda_id} ----------------


def _app_do_modulo():
    """App mínima com o router REAL do módulo (mesmo padrão de
    test_saude.py). Sem base de dados e sem rede: o TestClient corre a app
    dentro do próprio processo."""
    app = FastAPI()
    app.include_router(router_do_modulo)
    return app


def test_get_pos_venda_aberta_chega_mesmo_a_esta_funcao(monkeypatch):
    """`/pos/venda/aberta` não pode ser engolida pela rota de `{venda_id}`: o
    FastAPI serve a PRIMEIRA rota que casa com o caminho. O dia hipotético
    chegou — `GET /pos/venda/{venda_id}` existe (venda.py::obter_venda), casa
    com "aberta" tão bem como com um uuid, e só a ORDEM de declaração as
    separa. Trocá-las fazia o "aberta" ser lido como um id de venda: 404 à
    operadora, com o cliente à frente. Este teste percorre o caminho todo
    (URL → router montado → esta função) e é ele que fica vermelho nesse
    dia."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()], vendas=[_venda()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    app = _app_do_modulo()
    app.dependency_overrides[operador_atual] = lambda: _operador()
    resposta = TestClient(app).get(
        "/api/faturacao/pos/venda/aberta", params={"caixa_id": "caixa-1"}
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    # A prova de que foi ESTA função a responder — e não um 404/405 de outra
    # rota, nem uma de {venda_id} a tratar "aberta" como um id de venda.
    assert corpo["id"] == "venda-1"
    assert corpo["estado"] == "aberta"
    assert "totais" in corpo
    # E que foi a função CERTA das duas: `obter_venda` põe sempre uma chave
    # `documento` na resposta (mesmo a `None`) e a `venda_aberta` nunca a põe
    # — é o que distingue as duas com o mesmo 200 e a mesma venda.
    assert "documento" not in corpo


def test_as_duas_rotas_novas_recusam_sem_token_de_operador():
    """Ambas dependem de `operador_atual`: 401 ANTES de tocar na base de
    dados — repare-se que `obter_db` nem sequer está trocado neste teste, por
    isso se alguma delas chegasse a ler, isto rebentava com 500 em vez de
    401. (test_protecao_rotas.py garante o mesmo para todas as rotas do POS,
    sem lista para actualizar; isto prova-o pelo HTTP, de fora.)"""
    cliente = TestClient(_app_do_modulo())

    sem_token = cliente.get(
        "/api/faturacao/pos/venda/aberta", params={"caixa_id": "caixa-1"}
    )
    assert sem_token.status_code == 401

    cancelar = cliente.post("/api/faturacao/pos/venda/venda-1/cancelar")
    assert cancelar.status_code == 401


# --- Cancelar a conta (POST /pos/venda/{venda_id}/cancelar) -------------------


class ColeccaoComCorrida(ColeccaoFalsa):
    """Deixa outro pedido mexer no documento ENTRE a leitura e a escrita —
    é o único sítio onde a escrita condicional do cancelamento se prova. O
    gancho corre uma única vez, no primeiro update_one."""

    def __init__(self, registo, documentos=None, ao_escrever=None):
        super().__init__(registo, documentos)
        self._ao_escrever = ao_escrever

    async def update_one(self, filtro, atualizacao):
        if self._ao_escrever is not None:
            gancho, self._ao_escrever = self._ao_escrever, None
            gancho(self._documentos)
        return await super().update_one(filtro, atualizacao)


def test_cancelar_venda_aberta_grava_o_estado_e_o_momento(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[_linha()])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(cancelar_venda("venda-1", operador=_operador()))
    assert resultado["estado"] == "cancelada"

    gravada = db._coleccoes[COLECOES["vendas"]]._documentos[0]
    assert gravada["estado"] == "cancelada"
    # ISO em UTC, como o `_agora()` do módulo — nunca um datetime cru (que o
    # JSON não leva) nem uma hora local sem fuso (que ninguém consegue
    # comparar com o resto dos carimbos do módulo).
    assert gravada["cancelada_em"].endswith("+00:00")
    assert datetime.fromisoformat(gravada["cancelada_em"]).tzinfo is not None


def test_cancelar_venda_emitida_e_recusado_409_sem_escrever_nada(monkeypatch):
    """Uma venda emitida tem uma Fatura Simplificada REAL na AT: passá-la a
    cancelada apagava do nosso lado um documento que continua a existir lá
    fora. Corrige-se com uma nota de crédito, nunca com um estado mudado à
    socapa — e a recusa é ANTES de qualquer escrita: nem um update_one sai
    daqui."""
    registo = []
    db = _db(registo, vendas=[_venda(estado="emitida")])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(cancelar_venda("venda-1", operador=_operador()))
    assert excinfo.value.status_code == 409
    assert not any(chamada[0] == "update_one" for chamada in registo)
    assert db._coleccoes[COLECOES["vendas"]]._documentos[0]["estado"] == "emitida"


def test_cancelar_venda_ja_cancelada_e_recusado_409(monkeypatch):
    """Idempotência não é o objectivo: é melhor a operadora ouvir que aquela
    conta já estava cancelada do que carregar no botão e ficar sem saber se
    fez alguma coisa. E o carimbo original não se perde."""
    registo = []
    db = _db(registo, vendas=[
        _venda(estado="cancelada", cancelada_em="2026-08-15T09:30:00+00:00"),
    ])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(cancelar_venda("venda-1", operador=_operador()))
    assert excinfo.value.status_code == 409
    gravada = db._coleccoes[COLECOES["vendas"]]._documentos[0]
    assert gravada["cancelada_em"] == "2026-08-15T09:30:00+00:00"


def test_cancelar_venda_de_outra_loja_e_recusado_404(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda(loja_id="loja-2")])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(cancelar_venda("venda-1", operador=_operador()))
    assert excinfo.value.status_code == 404
    assert db._coleccoes[COLECOES["vendas"]]._documentos[0]["estado"] == "aberta"


def test_cancelar_venda_emitida_entre_a_leitura_e_a_escrita_e_recusado_409(monkeypatch):
    """A corrida a sério: o `finalizar` (fiscal.py) emitiu esta mesma venda
    DEPOIS do `_garante_aberta` e ANTES do $set. Sem a condição
    {"estado": "aberta"} na escrita, o cancelamento carimbava-se por cima de
    uma venda com Fatura Simplificada real e ela desaparecia do fecho de
    caixa (`caixa_math.soma_vendas_dinheiro` só soma as emitidas) — o
    dinheiro ficava na gaveta sem nada que o explicasse."""
    registo = []
    venda = _venda()

    def emite_entretanto(documentos):
        documentos[0]["estado"] = "emitida"
        documentos[0]["documento_id"] = "doc-1"

    db = DbFalsa({
        COLECOES["vendas"]: ColeccaoComCorrida(registo, [venda], emite_entretanto),
    })
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(cancelar_venda("venda-1", operador=_operador()))
    assert excinfo.value.status_code == 409
    assert venda["estado"] == "emitida"
    assert "cancelada_em" not in venda


def test_venda_cancelada_deixa_de_aceitar_alteracoes(monkeypatch):
    """`cancelada` não é só um rótulo para o ecrã: as rotas que escrevem
    recusam-na pelo mesmo caminho das emitidas (`_garante_aberta`)."""
    registo = []
    db = _db(registo, vendas=[_venda(estado="cancelada", linhas=[_linha()])],
             produtos=[_produto()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(juntar_linha(
            "venda-1", PedidoJuntarLinha(produto_id="prod-1"), operador=_operador()
        ))
    assert excinfo.value.status_code == 409


def test_depois_de_cancelar_a_conta_deixa_de_ser_a_conta_em_curso(monkeypatch):
    """As duas rotas juntas, que é como o ecrã as usa: a operadora deita a
    conta fora e o cliente seguinte encontra a caixa limpa — não a conta do
    anterior à espera de ser facturada."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()],
             vendas=[_venda(linhas=[_linha()])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    antes = _corre(venda_aberta(caixa_id="caixa-1", operador=_operador()))
    assert antes["id"] == "venda-1"

    _corre(cancelar_venda("venda-1", operador=_operador()))

    assert _corre(venda_aberta(caixa_id="caixa-1", operador=_operador())) is None


# --- A conta é de UM PC, não da caixa toda -----------------------------------
#
# Uma loja com UMA caixa e dois PCs emparelhados (o `nome` do PedidoCodigo —
# "PC Balcão", "PC Drive-Thru" — existe exactamente para isso, e
# `caixa.estado_caixa` resolve automaticamente essa única caixa para os dois)
# tinha `GET /pos/venda/aberta` com âmbito só na SESSÃO: os dois PCs
# recuperavam a MESMA conta e um cliente pagava o açaí do outro. Não é uma
# corrida de milissegundos — é o estado estável dessa configuração, o dia
# inteiro. O `dispositivo_id` vem do token do operador (pos_auth.py::entrar),
# nunca do corpo nem da query.


def test_abrir_venda_carimba_o_dispositivo_que_vem_no_token(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    _corre(abrir_venda(
        PedidoNovaVenda(caixa_id="caixa-1"),
        operador=_operador(dispositivo_id="pc-balcao"),
    ))
    gravada = db._coleccoes[COLECOES["vendas"]]._documentos[0]
    assert gravada["dispositivo_id"] == "pc-balcao"


def test_abrir_venda_ignora_um_dispositivo_vindo_do_corpo():
    """Mesmo raciocínio do operador e da sessão: `PedidoNovaVenda` não
    declara `dispositivo_id`, por isso um PC que o mandasse no JSON não
    conseguia carimbar a conta com o id de OUTRO posto — e ficar depois com
    as contas dele."""
    dados = PedidoNovaVenda.model_validate(
        {"caixa_id": "caixa-1", "dispositivo_id": "pc-do-lado"}
    )
    assert not hasattr(dados, "dispositivo_id")


def test_venda_aberta_nao_devolve_a_conta_do_outro_pc_da_mesma_caixa(monkeypatch):
    """O defeito, exactamente como acontece na loja: mesma caixa, mesma
    sessão, dois postos. A conta do PC do lado é deliberadamente a MAIS
    RECENTE — sem o filtro por dispositivo é ela que o `.sort("criada_em",
    -1)` traz primeiro, e o teste ficaria verde por acaso se fosse a mais
    antiga."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()], vendas=[
        _venda(id="v-balcao", dispositivo_id="pc-balcao",
               criada_em="2026-08-15T09:00:00+00:00", linhas=[_linha()]),
        _venda(id="v-drive", dispositivo_id="pc-drive",
               criada_em="2026-08-15T11:00:00+00:00", linhas=[_linha()]),
    ])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    no_balcao = _corre(venda_aberta(
        caixa_id="caixa-1", operador=_operador(dispositivo_id="pc-balcao")
    ))
    assert no_balcao["id"] == "v-balcao", "o balcão apanhou a conta do drive-thru"

    no_drive = _corre(venda_aberta(
        caixa_id="caixa-1", operador=_operador(dispositivo_id="pc-drive")
    ))
    assert no_drive["id"] == "v-drive"


def test_venda_aberta_num_pc_sem_conta_nenhuma_devolve_null(monkeypatch):
    """O outro lado do mesmo filtro: o drive-thru ainda não picou nada, e o
    que vê é uma caixa limpa — não a conta que o balcão tem a meio."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()],
             vendas=[_venda(id="v-balcao", dispositivo_id="pc-balcao", linhas=[_linha()])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    assert _corre(venda_aberta(
        caixa_id="caixa-1", operador=_operador(dispositivo_id="pc-drive")
    )) is None


def test_venda_aberta_segue_o_mesmo_pc_quando_a_operadora_muda(monkeypatch):
    """O caso legítimo que a docstring da rota defende desde sempre, e que o
    âmbito por dispositivo NÃO pode partir: a Rafaela picou três artigos, a
    tela de descanso caiu, e a Ana entrou com o PIN dela NO MESMO PC. A conta
    tem de continuar lá — é o cliente que está à espera."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()], vendas=[
        _venda(operador_id="op-1", dispositivo_id="pc-balcao", linhas=[_linha()]),
    ])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    ana = _operador(operador_id="op-2", nome="Ana", dispositivo_id="pc-balcao")
    resultado = _corre(venda_aberta(caixa_id="caixa-1", operador=ana))
    assert resultado is not None, "a conta da Rafaela perdeu-se ao entrar a Ana no mesmo PC"
    assert resultado["id"] == "venda-1"
    assert resultado["operador_id"] == "op-1"


def test_token_antigo_e_conta_antiga_encontram_se_e_nunca_cruzam_com_os_novos(monkeypatch):
    """Os tokens emitidos ANTES desta alteração não trazem `dispositivo_id`,
    e as contas abertas com eles não têm o campo. Filtrar por `None` casa, no
    Mongo, com o campo AUSENTE e com o campo a `null` (é a semântica da
    igualdade a null) — é isso que dispensa qualquer migração. Este teste
    percorre os quatro cruzamentos em vez de o assumir; o duplo replica essa
    semântica (`item.get(chave) == valor`, ver `_corresponde`).

    O que estaria em jogo se fosse ao contrário: um token antigo a apanhar a
    conta de um PC identificado seria o mesmo defeito de origem — e um token
    novo a apanhar a conta órfã de antes do deploy punha a operadora a
    facturar uma conta de outro posto, no dia da actualização."""
    registo = []
    # Uma conta SEM o campo (como as que ficaram abertas antes do deploy) e
    # uma conta do PC identificado, na mesma sessão.
    db_ausente = _db(registo, caixas=[_caixa()], sessoes=[_sessao()], vendas=[
        _venda(id="v-antiga", linhas=[_linha()]),
        _venda(id="v-nova", dispositivo_id="pc-balcao", linhas=[_linha()]),
    ])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db_ausente)

    # Token antigo → conta antiga (o campo AUSENTE casa com o filtro a None).
    antigo = _corre(venda_aberta(caixa_id="caixa-1", operador=_operador()))
    assert antigo is not None, "o token antigo deixou de encontrar a conta que já tinha"
    assert antigo["id"] == "v-antiga"

    # Token novo → só a conta do SEU PC, nunca a órfã de antes do deploy.
    novo = _corre(venda_aberta(
        caixa_id="caixa-1", operador=_operador(dispositivo_id="pc-balcao")
    ))
    assert novo["id"] == "v-nova"

    # E um PC identificado que ainda não picou nada não herda as antigas.
    outro = _corre(venda_aberta(
        caixa_id="caixa-1", operador=_operador(dispositivo_id="pc-drive")
    ))
    assert outro is None

    # A outra metade do "ausente OU nulo": o campo lá, a `null` — é o que
    # fica gravado quando quem abre a conta traz um token sem dispositivo.
    db_nulo = _db([], caixas=[_caixa()], sessoes=[_sessao()],
                  vendas=[_venda(id="v-nula", dispositivo_id=None, linhas=[_linha()])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db_nulo)

    nula = _corre(venda_aberta(caixa_id="caixa-1", operador=_operador()))
    assert nula is not None, "o campo a null não casou com o filtro a None"
    assert nula["id"] == "v-nula"
    assert _corre(venda_aberta(
        caixa_id="caixa-1", operador=_operador(dispositivo_id="pc-balcao")
    )) is None


# --- Cancelar com uma emissão pelo meio (fat_refs_fiscais) --------------------
#
# O `estado` da venda não chega para decidir um cancelamento: `fiscal.py`
# reserva em `fat_refs_fiscais` ANTES de falar com o Vendus e só marca
# `emitida` no fim. Entre as duas coisas — segundos à espera do Vendus, ou
# horas se a reserva ficar `incerta` — a venda diz `aberta` e pode ter uma
# Fatura Simplificada real a nascer do outro lado. Cancelá-la ali dizia à
# operadora que a conta tinha sido deitada fora enquanto saía uma FS com
# ATCUD (e ela voltava a picar tudo: duas faturas ao mesmo cliente), ou —
# no caso da reserva incerta — apagava a única venda que ainda ligava o
# dinheiro da gaveta a essa FS.


class ColeccaoComCorridaDepoisDaEscrita(ColeccaoFalsa):
    """A outra metade da corrida: o gancho corre DEPOIS do primeiro
    `update_one` — é a única janela que a verificação feita ANTES da escrita
    não fecha, e a razão de o cancelamento voltar a perguntar pela reserva
    depois de escrever."""

    def __init__(self, registo, documentos=None, depois_de_escrever=None):
        super().__init__(registo, documentos)
        self._depois_de_escrever = depois_de_escrever

    async def update_one(self, filtro, atualizacao):
        resultado = await super().update_one(filtro, atualizacao)
        if self._depois_de_escrever is not None:
            gancho, self._depois_de_escrever = self._depois_de_escrever, None
            gancho(self._documentos)
        return resultado


def test_cancelar_venda_com_emissao_em_curso_e_recusado_409(monkeypatch):
    """Cenário A: a operadora carregou em FINALIZAR, a emissão está à espera
    da resposta do Vendus (a reserva já existe, a venda ainda diz `aberta`) e
    ela carrega em Cancelar. Recusa — e nem uma escrita sai daqui."""
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[_linha()])], refs=[_reserva()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(cancelar_venda("venda-1", operador=_operador()))
    assert excinfo.value.status_code == 409
    # A mensagem tem de dizer o que fazer. Um "tente novamente" aqui era o
    # pior conselho possível: mandava a operadora carregar outra vez no botão
    # que não pode funcionar, com o cliente à frente.
    assert "gestor" in excinfo.value.detail
    assert "novamente" not in excinfo.value.detail
    assert not any(chamada[0] == "update_one" for chamada in registo)
    assert db._coleccoes[COLECOES["vendas"]]._documentos[0]["estado"] == "aberta"


def test_cancelar_venda_com_reserva_incerta_e_recusado_409(monkeypatch):
    """Cenário B, o pior: o Vendus deu timeout E a verificação também falhou
    — a reserva ficou `incerta` e a venda ficou `aberta` (é o desenho, ver
    VerificacaoFiscalIncerta em fiscal.py). É essa conta que
    `GET /pos/venda/aberta` devolve como conta em curso.

    Se a FS chegou mesmo a sair, cancelá-la deixava de existir do nosso lado
    qualquer venda `emitida` a explicar o dinheiro: o Z fechava curto
    (`caixa_math.soma_vendas_dinheiro` só soma as emitidas) e a reserva
    incerta ficava presa para sempre, sem nada por onde a gestão a resolver
    (a listagem de `/fiscal/reservas-incertas` liga-se às vendas pelo mesmo
    `venda_id`)."""
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[_linha()])],
             refs=[_reserva(incerta=True)])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(cancelar_venda("venda-1", operador=_operador()))
    assert excinfo.value.status_code == 409
    # Recusado ANTES de escrever, e não desfeito à posteriori pela
    # compensação: a compensação é uma rede para a corrida, não o caminho
    # normal — e no desfecho em que a venda já ficou `emitida` ela não pode
    # (nem deve) tocar-lhe.
    assert not any(chamada[0] == "update_one" for chamada in registo)
    assert db._coleccoes[COLECOES["vendas"]]._documentos[0]["estado"] == "aberta"


def test_cancelar_venda_ignora_a_reserva_de_outra_venda(monkeypatch):
    """A pergunta é pelo `venda_id` desta conta — não "há alguma reserva".
    Basta uma venda a ser emitida na caixa do lado para, com a pergunta
    errada, nenhuma conta do dia se conseguir cancelar."""
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[_linha()])],
             refs=[_reserva(id="ref-2", venda_id="venda-2",
                            ext_ref="pos-loja-1-sessao-1-venda-2")])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(cancelar_venda("venda-1", operador=_operador()))
    assert resultado["estado"] == "cancelada"


def test_reserva_que_aparece_depois_da_escrita_desfaz_o_cancelamento(monkeypatch):
    """A janela que a verificação de cima não fecha: entre ela e o `$set`, o
    `finalizar` reservou. O cancelamento pergunta OUTRA VEZ depois de
    escrever e compensa — a conta volta a `aberta`, sem carimbos de
    cancelamento, e a operadora ouve o mesmo 409 em vez de um "cancelada"
    que era mentira."""
    registo = []
    venda = _venda(linhas=[_linha()])
    refs = []

    def reserva_entretanto(_documentos):
        refs.append(_reserva())

    db = DbFalsa({
        COLECOES["vendas"]: ColeccaoComCorridaDepoisDaEscrita(
            registo, [venda], reserva_entretanto
        ),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(registo, refs),
    })
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(cancelar_venda("venda-1", operador=_operador()))
    assert excinfo.value.status_code == 409
    assert "gestor" in excinfo.value.detail
    assert venda["estado"] == "aberta", "a conta ficou cancelada com uma emissão a decorrer"
    assert venda["cancelada_em"] is None
    assert venda["cancelada_por"] is None


def test_a_compensacao_nunca_toca_numa_venda_ja_emitida(monkeypatch):
    """A mesma corrida, no desfecho mais perigoso: entre o nosso `$set` e a
    segunda pergunta, o `fiscal.py::_gravar_documento` gravou a FS e pôs a
    venda `emitida` — e o $set DELE não tem condição de estado nenhuma, por
    isso cai por cima do nosso "cancelada".

    A compensação é condicionada a {"estado": "cancelada"}: aqui não casa, e
    não lhe toca. Incondicional, ressuscitava como `aberta` uma venda com
    Fatura Simplificada real e ATCUD — que desaparecia do Z
    (`soma_vendas_dinheiro` só soma as emitidas) e ficava a convidar a
    operadora a facturá-la outra vez."""
    registo = []
    venda = _venda(linhas=[_linha()])
    refs = []

    def emite_e_reserva(documentos):
        documentos[0]["estado"] = "emitida"
        documentos[0]["documento_id"] = "doc-1"
        refs.append(_reserva())

    db = DbFalsa({
        COLECOES["vendas"]: ColeccaoComCorridaDepoisDaEscrita(
            registo, [venda], emite_e_reserva
        ),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(registo, refs),
    })
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(cancelar_venda("venda-1", operador=_operador()))
    assert excinfo.value.status_code == 409
    assert venda["estado"] == "emitida", "a compensação ressuscitou uma venda com FS real"
    assert venda["documento_id"] == "doc-1"


# --- Quem cancelou -------------------------------------------------------------


def test_cancelar_grava_quem_cancelou_e_nao_quem_abriu(monkeypatch):
    """O único nome na venda era o `operador_id` de quem a ABRIU: a Rafaela
    abre e pica 24 €, a Ana entra com o PIN dela e cancela, e ficava lá o
    nome da Rafaela. A atribuição não estava só ausente — estava ERRADA, e no
    vector de fraude mais banal que há ao balcão (picar, receber o dinheiro,
    cancelar a conta), num módulo cujo pos_auth.py existe precisamente para
    nenhuma venda entrar na caixa sem dono.

    O carimbo é o mesmo `_quem` do resto do módulo (caixa.py: `aberta_por`,
    `fechada_por`, o `por` dos movimentos), reutilizado e não reescrito."""
    registo = []
    db = _db(registo, vendas=[_venda(operador_id="op-1", linhas=[_linha()])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    ana = _operador(operador_id="op-2", nome="Ana")
    resultado = _corre(cancelar_venda("venda-1", operador=ana))

    gravada = db._coleccoes[COLECOES["vendas"]]._documentos[0]
    assert gravada["cancelada_por"] == {"id": "op-2", "nome": "Ana"}
    assert gravada["operador_id"] == "op-1", "quem picou a conta não se perde"
    # E chega mesmo ao ecrã: um `cancelada_em` escrito e nunca lido por
    # ninguém é um dado cego — é a primeira coisa que se pergunta quando
    # falta dinheiro na gaveta ao fim do dia.
    assert resultado["cancelada_por"] == {"id": "op-2", "nome": "Ana"}
    assert resultado["cancelada_em"] == gravada["cancelada_em"]


def test_conta_por_cancelar_mostra_os_dois_campos_a_none(monkeypatch):
    """Os campos existem SEMPRE na resposta, mesmo na esmagadora maioria das
    contas que nunca foram canceladas — o ecrã não tem de adivinhar se a
    ausência da chave quer dizer "não cancelada" ou "versão antiga da API"."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()],
             vendas=[_venda(linhas=[_linha()])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(venda_aberta(caixa_id="caixa-1", operador=_operador()))
    assert resultado["cancelada_em"] is None
    assert resultado["cancelada_por"] is None


# --- Uma venda com reserva fiscal fica CONGELADA -------------------------------
#
# Não era só o cancelamento a decidir por `_garante_aberta`: `juntar_linha`,
# `editar_linha`, `remover_linha` e `aplicar_desconto_global` decidiam TODAS
# só por ele — o critério que a docstring de `_tem_reserva_fiscal` declara
# insuficiente. O estrago, reproduzido em processo antes desta correcção: o
# Vendus dá timeout, a verificação também falha, a reserva fica `incerta` e a
# venda fica `aberta` (é o desenho); a FS de 8,99 € até pode ter saído. A
# conta continua no ecrã, aceita um segundo açaí (201) e um desconto de 10 %
# (200), e mais tarde a retoma encontra o documento original e liga-lhe a
# venda: fica no sistema uma venda emitida de 16,18 € contra um documento
# fiscal de 8,99 €. O Z não apanha (soma os `pagamentos`, não os `_totais`) e
# a divergência não aparece em lado nenhum.


def _db_congelada(registo, **over):
    """Uma conta com uma linha e uma reserva de emissão a pairar sobre ela."""
    argumentos = {
        "caixas": [_caixa()], "sessoes": [_sessao()], "produtos": [_produto()],
        "vendas": [_venda(linhas=[_linha()])], "refs": [_reserva()],
    }
    argumentos.update(over)
    return _db(registo, **argumentos)


def _escritas(registo):
    return [chamada for chamada in registo if chamada[0] == "update_one"]


def test_juntar_linha_com_reserva_fiscal_e_recusado_409(monkeypatch):
    registo = []
    db = _db_congelada(registo)
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(juntar_linha("venda-1", PedidoJuntarLinha(produto_id="prod-1"), operador=_operador()))
    assert excinfo.value.status_code == 409
    assert "gestor" in excinfo.value.detail
    assert _escritas(registo) == []
    assert len(db._coleccoes[COLECOES["vendas"]]._documentos[0]["linhas"]) == 1


def test_editar_linha_com_reserva_fiscal_e_recusado_409(monkeypatch):
    registo = []
    db = _db_congelada(registo)
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(editar_linha(
            "venda-1", "linha-1", PedidoEditarLinha(quantidade=5), operador=_operador()
        ))
    assert excinfo.value.status_code == 409
    assert "gestor" in excinfo.value.detail
    assert _escritas(registo) == []
    assert db._coleccoes[COLECOES["vendas"]]._documentos[0]["linhas"][0]["quantidade"] == 1


def test_remover_linha_com_reserva_fiscal_e_recusado_409(monkeypatch):
    registo = []
    db = _db_congelada(registo)
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(remover_linha("venda-1", "linha-1", operador=_operador()))
    assert excinfo.value.status_code == 409
    assert "gestor" in excinfo.value.detail
    assert _escritas(registo) == []
    assert len(db._coleccoes[COLECOES["vendas"]]._documentos[0]["linhas"]) == 1


def test_aplicar_desconto_global_com_reserva_fiscal_e_recusado_409(monkeypatch):
    """O caso exacto do guião de reprodução: 10 % de desconto sobre uma conta
    cuja fatura pode já ter saído."""
    registo = []
    db = _db_congelada(registo)
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(aplicar_desconto_global(
            "venda-1", PedidoDescontoGlobal(desconto_pct=10), operador=_operador()
        ))
    assert excinfo.value.status_code == 409
    assert "gestor" in excinfo.value.detail
    assert _escritas(registo) == []
    assert db._coleccoes[COLECOES["vendas"]]._documentos[0]["desconto_global_pct"] is None


def test_reserva_incerta_congela_as_rotas_de_escrita_tal_como_a_reserva_normal(monkeypatch):
    """O pior caso (o do guião): a reserva ficou `incerta` — a FS pode ter
    saído mesmo — e a conta continua `aberta` a ser servida no ecrã."""
    registo = []
    db = _db_congelada(registo, refs=[_reserva(incerta=True)])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(juntar_linha("venda-1", PedidoJuntarLinha(produto_id="prod-1"), operador=_operador()))
    assert excinfo.value.status_code == 409


def test_a_reserva_de_outra_venda_nao_congela_esta_conta(monkeypatch):
    """A pergunta é pelo `venda_id` desta conta — não "há alguma reserva".
    Com a pergunta errada, bastava uma venda a ser emitida na caixa do lado
    para nenhuma conta da loja aceitar mais nada: o balcão inteiro parava de
    cada vez que alguém finalizasse."""
    registo = []
    db = _db_congelada(registo, refs=[
        _reserva(id="ref-2", venda_id="venda-2", ext_ref="pos-loja-1-sessao-1-venda-2")
    ])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)
    op = _operador()

    assert len(_corre(juntar_linha(
        "venda-1", PedidoJuntarLinha(produto_id="prod-1"), operador=op
    ))["linhas"]) == 2
    assert _corre(editar_linha(
        "venda-1", "linha-1", PedidoEditarLinha(quantidade=3), operador=op
    ))["linhas"][0]["quantidade"] == 3
    assert _corre(aplicar_desconto_global(
        "venda-1", PedidoDescontoGlobal(desconto_pct=10), operador=op
    ))["desconto_global_pct"] == 10
    assert _corre(remover_linha("venda-1", "linha-1", operador=op))["linhas"] != []


# --- O travão, visto pelo ecrã: `emissao_por_confirmar` ------------------------
#
# Até aqui o POS só sabia da emissão por confirmar pelo 503 que tinha acabado
# de receber, e essa memória vivia no browser: um F5, a tela de descanso ou o
# browser a ir abaixo apagavam-na e a conta voltava a parecer normal. Agora o
# estado vem do SERVIDOR, em todas as respostas de venda.


def test_conta_recuperada_avisa_que_a_emissao_esta_por_confirmar(monkeypatch):
    """`GET /pos/venda/aberta` é por onde o ecrã recupera a conta depois da
    tela de descanso — é a resposta que TEM de trazer o travão."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()],
             vendas=[_venda(linhas=[_linha()])], refs=[_reserva(incerta=True)])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(venda_aberta(caixa_id="caixa-1", operador=_operador()))
    assert resultado["emissao_por_confirmar"] is True


def test_conta_recuperada_sem_reserva_nenhuma_nao_mostra_travao(monkeypatch):
    """A esmagadora maioria das contas. Um travão que aparecesse sempre era
    igualmente inútil — e pior, ensinava a operadora a ignorá-lo."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()],
             vendas=[_venda(linhas=[_linha()])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(venda_aberta(caixa_id="caixa-1", operador=_operador()))
    assert resultado["emissao_por_confirmar"] is False


def test_travao_ignora_a_reserva_de_outra_venda(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()],
             vendas=[_venda(linhas=[_linha()])],
             refs=[_reserva(id="ref-2", venda_id="venda-2",
                            ext_ref="pos-loja-1-sessao-1-venda-2")])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    assert _corre(venda_aberta(caixa_id="caixa-1", operador=_operador()))[
        "emissao_por_confirmar"] is False


def test_venda_emitida_nao_conta_como_emissao_por_confirmar(monkeypatch):
    """A reserva de uma venda emitida NÃO desaparece — é ela que sustenta a
    idempotência. Sem esta condição, toda a conta que correu bem ficava para
    sempre marcada como "por confirmar"."""
    registo = []
    db = _db(registo, vendas=[_venda(estado="emitida", linhas=[_linha()])], refs=[_reserva()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    emitida = db._coleccoes[COLECOES["vendas"]]._documentos[0]
    assert _corre(venda_mod._emissao_por_confirmar(db, emitida)) is False


def test_o_campo_vem_sempre_na_resposta_das_rotas_de_venda(monkeypatch):
    """Presente SEMPRE, mesmo a `False` (mesma regra de `cancelada_em`): o
    ecrã não pode ter de adivinhar se a ausência da chave quer dizer "não há
    emissão pendente" ou "versão antiga da API"."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()],
             vendas=[_venda(linhas=[_linha()])], produtos=[_produto()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)
    op = _operador()

    respostas = [
        _corre(abrir_venda(PedidoNovaVenda(caixa_id="caixa-1"), operador=op)),
        _corre(juntar_linha("venda-1", PedidoJuntarLinha(produto_id="prod-1"), operador=op)),
        _corre(editar_linha("venda-1", "linha-1", PedidoEditarLinha(quantidade=2), operador=op)),
        _corre(aplicar_desconto_global(
            "venda-1", PedidoDescontoGlobal(desconto_eur=1.0), operador=op)),
        _corre(remover_linha("venda-1", "linha-1", operador=op)),
        _corre(cancelar_venda("venda-1", operador=op)),
    ]
    for resposta in respostas:
        assert resposta["emissao_por_confirmar"] is False, resposta["id"]


# --- A ESCRITA das quatro rotas também é condicional --------------------------
#
# As cinco rotas de escrita tinham todas a PERGUNTA (`_garante_sem_emissao`);
# só o `cancelar_venda` tinha também a escrita CONDICIONADA a
# {"estado": "aberta"} + matched_count — "é o matched_count, não a leitura de
# cima, que decide esta corrida", diz o comentário do próprio ficheiro. As
# outras quatro escreviam `update_one({"id": venda_id}, ...)` sem condição
# nenhuma, e entre a pergunta e a escrita ainda há `await`s (o `find_one` do
# produto, o I/O da própria escrita). Reproduzido em processo, com a emissão
# a correr INTEIRA nessa janela: `FINALIZAR -> 200 documento FS 2026/1 total
# 8.99 €` e a seguir `JUNTAR LINHA (a chegar atrasado) -> 201, sem erro
# nenhum` — ficava no Mongo uma venda `emitida` com 2 linhas e 17,98 € contra
# um documento fiscal REAL de 8,99 €.


class ColeccaoComEmissaoAntesDaEscrita(ColeccaoFalsa):
    """A emissão cabe entre a pergunta e a escrita: este duplo é a colecção
    das RESERVAS, e corre o gancho logo depois de responder à pergunta de
    `_garante_sem_emissao` — que é o último `await` antes da escrita nas
    quatro rotas."""

    def __init__(self, registo, documentos=None, depois_de_responder=None):
        super().__init__(registo, documentos)
        self._depois_de_responder = depois_de_responder

    async def find_one(self, filtro, projecao=None):
        resposta = await super().find_one(filtro, projecao)
        if self._depois_de_responder is not None:
            gancho, self._depois_de_responder = self._depois_de_responder, None
            gancho()
        return resposta


def _db_com_emissao_a_meio(registo, venda):
    """A conta ainda `aberta` quando a rota a lê; `emitida`, com uma FS real
    de 8,99 €, quando a rota vai escrever."""

    def emite_entretanto():
        venda["estado"] = "emitida"
        venda["documento_id"] = "doc-1"

    return DbFalsa({
        COLECOES["caixas"]: ColeccaoFalsa(registo, [_caixa()]),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa(registo, [_sessao()]),
        COLECOES["vendas"]: ColeccaoFalsa(registo, [venda]),
        COLECOES["produtos"]: ColeccaoFalsa(registo, [_produto()]),
        COLECOES["refs_fiscais"]: ColeccaoComEmissaoAntesDaEscrita(
            registo, [], emite_entretanto
        ),
    })


def test_juntar_linha_que_chega_atrasado_a_uma_venda_ja_emitida_e_recusado(monkeypatch):
    registo = []
    venda = _venda(linhas=[_linha()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: _db_com_emissao_a_meio(registo, venda))

    with pytest.raises(HTTPException) as excinfo:
        _corre(juntar_linha("venda-1", PedidoJuntarLinha(produto_id="prod-1"),
                            operador=_operador()))

    assert excinfo.value.status_code == 409
    assert len(venda["linhas"]) == 1, (
        "venda emitida ficou com 2 linhas contra um documento fiscal de 1"
    )
    assert venda["estado"] == "emitida"


def test_editar_linha_que_chega_atrasado_a_uma_venda_ja_emitida_e_recusado(monkeypatch):
    registo = []
    venda = _venda(linhas=[_linha()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: _db_com_emissao_a_meio(registo, venda))

    with pytest.raises(HTTPException) as excinfo:
        _corre(editar_linha("venda-1", "linha-1", PedidoEditarLinha(quantidade=5),
                            operador=_operador()))

    assert excinfo.value.status_code == 409
    assert venda["linhas"][0]["quantidade"] == 1, (
        "a quantidade da linha mudou por baixo de uma Fatura Simplificada real"
    )


def test_remover_linha_que_chega_atrasado_a_uma_venda_ja_emitida_e_recusado(monkeypatch):
    registo = []
    venda = _venda(linhas=[_linha()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: _db_com_emissao_a_meio(registo, venda))

    with pytest.raises(HTTPException) as excinfo:
        _corre(remover_linha("venda-1", "linha-1", operador=_operador()))

    assert excinfo.value.status_code == 409
    assert len(venda["linhas"]) == 1, "a linha faturada desapareceu da venda emitida"


def test_desconto_global_que_chega_atrasado_a_uma_venda_ja_emitida_e_recusado(monkeypatch):
    registo = []
    venda = _venda(linhas=[_linha()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: _db_com_emissao_a_meio(registo, venda))

    with pytest.raises(HTTPException) as excinfo:
        _corre(aplicar_desconto_global("venda-1", PedidoDescontoGlobal(desconto_pct=10),
                                       operador=_operador()))

    assert excinfo.value.status_code == 409
    assert venda["desconto_global_pct"] is None, (
        "entrou um desconto numa venda com Fatura Simplificada real já emitida"
    )


def test_as_quatro_rotas_continuam_a_escrever_quando_a_venda_esta_mesmo_aberta(monkeypatch):
    """O contrapeso da condição: sem ele, uma condição errada (ou um
    matched_count mal lido) trancava o balcão inteiro em silêncio."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()], produtos=[_produto()],
             vendas=[_venda(linhas=[_linha()])], refs=[])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)
    guardada = db._coleccoes[COLECOES["vendas"]]._documentos[0]

    _corre(juntar_linha("venda-1", PedidoJuntarLinha(produto_id="prod-1"),
                        operador=_operador()))
    assert len(guardada["linhas"]) == 2

    _corre(editar_linha("venda-1", "linha-1", PedidoEditarLinha(quantidade=3),
                        operador=_operador()))
    assert guardada["linhas"][0]["quantidade"] == 3

    _corre(aplicar_desconto_global("venda-1", PedidoDescontoGlobal(desconto_pct=10),
                                   operador=_operador()))
    assert guardada["desconto_global_pct"] == 10

    _corre(remover_linha("venda-1", "linha-1", operador=_operador()))
    assert len(guardada["linhas"]) == 1


# --- O 409 do cancelamento descreve o estado do MOMENTO -----------------------
#
# A3: o cancelar escreve `cancelada`, a releitura do `finalizar` vê-a, liberta
# a reserva e aborta sem emitir, e a compensação repõe `aberta`. A conta acaba
# `aberta`, sem reserva e sem emissão nenhuma — e a operadora ouvia "esta conta
# tem uma emissão de fatura em curso... Chame o gestor". Bastava voltar a
# carregar em Cancelar.


class RefsQueDesaparecemDepoisDaPergunta(ColeccaoFalsa):
    """A reserva existe quando o cancelamento pergunta por ela (depois de
    escrever) e já não existe quando a mensagem é composta — que é
    exactamente o que acontece quando a emissão aborta e a liberta."""

    def __init__(self, registo, documentos=None):
        super().__init__(registo, documentos)
        self.perguntas = 0

    async def find_one(self, filtro, projecao=None):
        resposta = await super().find_one(filtro, projecao)
        self.perguntas += 1
        if self.perguntas == 2:  # a segunda pergunta: a de DEPOIS da escrita
            del self._documentos[:]
        return resposta


def test_cancelamento_abortado_sem_emissao_nao_manda_chamar_o_gestor(monkeypatch):
    """A conta ficou `aberta`, sem reserva e sem fatura nenhuma: mandar
    chamar o gestor a uma loja cheia por causa disto é o mesmo erro que dizer
    "tente novamente" onde não se pode tentar — só que ao contrário."""
    registo = []
    venda = _venda(linhas=[_linha()])
    db = DbFalsa({
        COLECOES["vendas"]: ColeccaoComCorridaDepoisDaEscrita(
            registo, [venda], lambda _docs: refs._documentos.append(_reserva())
        ),
        COLECOES["refs_fiscais"]: RefsQueDesaparecemDepoisDaPergunta(registo, []),
    })
    refs = db._coleccoes[COLECOES["refs_fiscais"]]
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(cancelar_venda("venda-1", operador=_operador()))

    assert excinfo.value.status_code == 409
    assert "gestor" not in excinfo.value.detail
    assert "NÃO saiu nenhuma Fatura" in excinfo.value.detail
    assert "Carregue em Cancelar outra vez" in excinfo.value.detail
    # E a conta está mesmo como a mensagem diz: aberta, sem carimbos.
    assert venda["estado"] == "aberta"
    assert venda["cancelada_em"] is None


def test_cancelamento_que_perdeu_para_uma_emissao_diz_que_a_fatura_saiu(monkeypatch):
    """O desfecho oposto, e a mensagem também: a venda ficou `emitida` com
    uma FS real. "Chame o gestor" não descreve isto — o que a operadora
    precisa de saber é que a fatura SAIU e que se corrige com nota de
    crédito."""
    registo = []
    venda = _venda(linhas=[_linha()])
    refs = []

    def emite_e_reserva(documentos):
        documentos[0]["estado"] = "emitida"
        documentos[0]["documento_id"] = "doc-1"
        refs.append(_reserva())

    db = DbFalsa({
        COLECOES["vendas"]: ColeccaoComCorridaDepoisDaEscrita(
            registo, [venda], emite_e_reserva
        ),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(registo, refs),
    })
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(cancelar_venda("venda-1", operador=_operador()))

    assert excinfo.value.status_code == 409
    assert "nota de crédito" in excinfo.value.detail
    assert venda["estado"] == "emitida"


def test_cancelamento_com_a_emissao_ainda_viva_continua_a_mandar_chamar_o_gestor(monkeypatch):
    """O caso em que o gestor faz mesmo falta — a reserva continua lá, não se
    sabe se a FS saiu — tem de continuar a dizer o que sempre disse."""
    registo = []
    venda = _venda(linhas=[_linha()])
    refs = []

    def reserva_entretanto(_documentos):
        refs.append(_reserva())

    db = DbFalsa({
        COLECOES["vendas"]: ColeccaoComCorridaDepoisDaEscrita(
            registo, [venda], reserva_entretanto
        ),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(registo, refs),
    })
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(cancelar_venda("venda-1", operador=_operador()))

    assert excinfo.value.status_code == 409
    assert "gestor" in excinfo.value.detail
    assert venda["estado"] == "aberta"


# --- Reler uma venda pelo id (GET /pos/venda/{venda_id}) ----------------------
#
# O pior defeito do ecrã do POS, e a metade que lhe faltava: a operadora
# carrega em EMITIR, a Fatura Simplificada SAI mesmo, e a resposta perde-se (o
# Wi-Fi do balcão pisca, ou o proxy corta aos 30 s porque o Vendus demorou).
# Ela carrega outra vez → 409 "esta venda já foi emitida" → o ecrã esvazia a
# conta com um aviso que passa e NUNCA lhe mostra o número nem o ATCUD. Sem
# talão (o agente de impressão ainda não existe), sem documento no ecrã e com
# a conta vazia, o gesto natural é picar tudo outra vez — e sai uma SEGUNDA
# Fatura Simplificada real, que a idempotência do servidor não apanha, porque
# é uma venda nova com uma referência nova.
#
# `GET /pos/venda/aberta` não servia: filtra `estado: "aberta"` e devolve
# `null` assim que a venda passa a `emitida`, que é exactamente o caso.


def test_obter_venda_aberta_devolve_a_conta_e_documento_a_none(monkeypatch):
    """Sem documento não é erro — é o estado normal de uma conta por
    facturar. Um 404 (ou um 500) aqui obrigava o ecrã a tratar "ainda não há
    fatura" como uma avaria."""
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[_linha(quantidade=2)])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(obter_venda("venda-1", operador=_operador()))
    assert resultado["id"] == "venda-1"
    assert resultado["estado"] == "aberta"
    assert resultado["documento"] is None
    assert [li["id"] for li in resultado["linhas"]] == ["linha-1"]

    # Mesmo formato das outras rotas, totais incluídos — e conferidos contra o
    # `linha_de_venda`, nunca contra um número escrito à mão aqui.
    li_vendus = linha_de_venda({"nome": "Açaí Regular", "preco": 8.99, "tax_id": "INT"}, 2)
    assert resultado["totais"]["subtotal"] == round(
        li_vendus["qty"] * li_vendus["gross_price"], 2)
    assert resultado["totais"]["total"] == resultado["totais"]["subtotal"]


def test_obter_venda_emitida_devolve_o_numero_e_o_atcud(monkeypatch):
    """O caso que justifica a rota inteira: a venda já não é "aberta" (por
    isso `GET /pos/venda/aberta` responderia `null`) e o que a operadora
    precisa de ver é o documento que saiu."""
    registo = []
    db = _db(registo, vendas=[_venda(estado="emitida", linhas=[_linha()])],
             documentos=[_documento()], refs=[_reserva()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(obter_venda("venda-1", operador=_operador()))
    assert resultado["estado"] == "emitida"
    documento = resultado["documento"]
    assert documento["numero"] == "FS 2026PDV/1"
    assert documento["atcud"] == "JFT7-1"
    assert documento["total"] == 8.99
    assert documento["modo"] == "normal"

    # A MESMA selecção de campos do `finalizar` — comparada com a função de
    # verdade e não com uma lista escrita aqui: se alguém escrever uma segunda
    # selecção neste módulo, as duas divergem no dia em que uma delas mudar, e
    # o ecrã passa a mostrar coisas diferentes conforme o caminho por onde
    # chegou ao documento.
    assert documento == _resposta_documento(_documento())


def test_obter_venda_emitida_em_modo_tests_diz_o_modo(monkeypatch):
    """Um documento emitido em `tests` NÃO tem valor fiscal — o ecrã avisa-o
    em destaque, e só o consegue se o `modo` vier na resposta. Perder este
    campo pelo caminho deixava a loja convencida de que tinha facturado."""
    registo = []
    db = _db(registo, vendas=[_venda(estado="emitida")],
             documentos=[_documento(modo="tests")])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    assert _corre(obter_venda("venda-1", operador=_operador()))["documento"]["modo"] == "tests"


def test_obter_venda_cancelada_devolve_a_conta_e_quem_a_cancelou(monkeypatch):
    """A outra pergunta da operadora quando a resposta se perde: "a conta foi
    mesmo deitada fora?". Uma conta cancelada não tem documento nenhum."""
    registo = []
    db = _db(registo, vendas=[_venda(
        estado="cancelada", cancelada_em="2026-08-15T09:30:00+00:00",
        cancelada_por={"id": "op-2", "nome": "Ana"},
    )])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(obter_venda("venda-1", operador=_operador()))
    assert resultado["estado"] == "cancelada"
    assert resultado["cancelada_por"] == {"id": "op-2", "nome": "Ana"}
    assert resultado["documento"] is None


def test_obter_venda_nao_devolve_o_documento_de_outra_venda(monkeypatch):
    """A colecção de documentos tem TODAS as faturas de TODAS as lojas. Uma
    leitura sem filtro (ou filtrada pela chave errada) devolvia o número e o
    ATCUD de outra venda qualquer — a operadora lia à cliente o documento de
    outra pessoa, e ficava convencida de que esta conta já estava facturada
    quando não está."""
    registo = []
    db = _db(registo, vendas=[_venda()],
             documentos=[_documento(id="doc-9", venda_id="venda-9",
                                    numero="FS 2026PDV/9", atcud="JFT7-9",
                                    vendus_document_id=8809)])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    assert _corre(obter_venda("venda-1", operador=_operador()))["documento"] is None


def test_obter_venda_traz_o_travao_da_emissao_por_confirmar(monkeypatch):
    """O mesmo travão de `GET /pos/venda/aberta`: esta rota é o outro caminho
    por onde o ecrã recupera uma conta, e uma conta congelada tem de o dizer
    aqui também — senão bastava recuperá-la por este lado para o travão
    desaparecer."""
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[_linha()])], refs=[_reserva(incerta=True)])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(obter_venda("venda-1", operador=_operador()))
    assert resultado["emissao_por_confirmar"] is True
    assert resultado["documento"] is None


def test_obter_venda_emitida_nao_marca_travao_nenhum(monkeypatch):
    """A reserva de uma venda emitida NÃO desaparece (é ela que sustenta a
    idempotência) — sem a condição do `_emissao_por_confirmar`, toda a conta
    que correu bem aparecia aqui marcada como "por confirmar", ao lado do
    documento que prova que correu bem."""
    registo = []
    db = _db(registo, vendas=[_venda(estado="emitida")],
             documentos=[_documento()], refs=[_reserva()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(obter_venda("venda-1", operador=_operador()))
    assert resultado["emissao_por_confirmar"] is False
    assert resultado["documento"]["numero"] == "FS 2026PDV/1"


def test_obter_venda_de_outra_loja_e_recusado_404(monkeypatch):
    """O âmbito é o de sempre (`_obter_venda_da_loja`): o id vem do browser, e
    reler não é uma permissão mais fraca do que escrever — o número e o ATCUD
    de uma loja não se lêem com o token de outra."""
    registo = []
    db = _db(registo, vendas=[_venda(loja_id="loja-2", estado="emitida")],
             documentos=[_documento(loja_id="loja-2")])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(obter_venda("venda-1", operador=_operador()))
    assert excinfo.value.status_code == 404


def test_obter_venda_inexistente_e_recusado_404(monkeypatch):
    registo = []
    db = _db(registo, vendas=[])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(obter_venda("venda-que-nao-existe", operador=_operador()))
    assert excinfo.value.status_code == 404


def test_obter_venda_sem_token_de_operador_e_recusado_401():
    """401 ANTES de tocar na base de dados — `obter_db` nem sequer está
    trocado neste teste, por isso se a rota chegasse a ler rebentava com 500
    em vez de 401."""
    resposta = TestClient(_app_do_modulo()).get("/api/faturacao/pos/venda/venda-1")
    assert resposta.status_code == 401


def test_a_rota_nova_nao_engole_o_caminho_da_conta_em_curso(monkeypatch):
    """A armadilha, montada de propósito: uma venda cujo id é LITERALMENTE
    "aberta", e numa sessão que já não é a de hoje — portanto não é a conta em
    curso deste PC.

    - servida por `venda_aberta` (o que tem de acontecer): 200 com `null`,
      porque este PC não tem conta nenhuma em curso;
    - servida por `obter_venda` (a rota de `{venda_id}` a engolir o caminho):
      200 com essa venda lá dentro.

    Duas respostas 200 distinguíveis — um teste que só olhasse para o código
    de estado não separava as duas funções, e é essa a separação que aqui
    interessa."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()],
             vendas=[_venda(id="aberta", sessao_id="sessao-de-ontem")])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    app = _app_do_modulo()
    app.dependency_overrides[operador_atual] = lambda: _operador()
    resposta = TestClient(app).get(
        "/api/faturacao/pos/venda/aberta", params={"caixa_id": "caixa-1"}
    )

    assert resposta.status_code == 200
    assert resposta.json() is None, (
        "`GET /pos/venda/aberta` foi servida pela rota de {venda_id} — o "
        "'aberta' foi lido como um id de venda, e a operadora perdia a conta "
        "em curso."
    )


def test_a_rota_nova_responde_mesmo_pelo_router_montado(monkeypatch):
    """O outro lado da armadilha acima: com um id a sério, é `obter_venda` que
    responde — se a rota estivesse mal declarada (ou não estivesse declarada
    de todo), isto era um 404/405 do FastAPI e não uma venda."""
    registo = []
    db = _db(registo, vendas=[_venda(estado="emitida")], documentos=[_documento()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    app = _app_do_modulo()
    app.dependency_overrides[operador_atual] = lambda: _operador()
    resposta = TestClient(app).get("/api/faturacao/pos/venda/venda-1")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["id"] == "venda-1"
    assert corpo["estado"] == "emitida"
    assert corpo["documento"]["atcud"] == "JFT7-1"


# --- Duas alterações à MESMA conta: nenhuma apaga a outra ----------------------
#
# As três rotas de linha liam o array `linhas` inteiro, mexiam-lhe em memória
# e gravavam-no INTEIRO por cima. `_escrever_se_ainda_aberta` prendia a
# identidade e o ESTADO da venda, e nada prendia a VERSÃO do que foi lido:
# duas escritas sobrepostas e a última apagava a primeira, com as duas
# respostas HTTP a dizer sucesso.
#
# Medido, sobre as rotas reais: A junta a água (lê [açaí], pára), B remove o
# açaí, A grava o que leu → «o que ficou MESMO no Mongo -> ['Açaí Regular',
# 'Água 33cl']»: o açaí que a operadora removeu volta à conta e vai numa
# Fatura Simplificada REAL de 9,99 € em vez de 1,00 €. Pela ordem inversa é a
# água que desaparece do Mongo depois de o ecrã a mostrar na conta, e o
# cliente leva-a sem a pagar.
#
# A defesa existia — uma fila em `PosVenda.js` — mas vive toda no cliente e é
# POR INSTÂNCIA: um F5 a meio de um pedido lento, ou dois separadores do POS
# no mesmo PC (partilham o `dispositivo_id`, logo recuperam a MESMA conta),
# passam-lhe ao lado.


class VendasQueMudamAntesDeGravar(ColeccaoFalsa):
    """Deixa correr uma alteração INTEIRA de outro sítio no instante exacto
    em que a rota vai gravar as linhas que leu — a janela do defeito.

    `repetir=True` fá-lo em TODAS as tentativas (a conta martelada dos dois
    lados); por omissão só na primeira, que é o cenário medido. O `_dentro`
    existe para a alteração do outro sítio não se disparar a si própria."""

    def __init__(self, registo, documentos=None):
        super().__init__(registo, documentos)
        self.o_outro_sitio = None
        self.repetir = False
        self._dentro = False

    async def update_one(self, filtro, atualizacao):
        outro = self.o_outro_sitio
        if (outro is not None and not self._dentro
                and "linhas" in (atualizacao.get("$set") or {})):
            if not self.repetir:
                self.o_outro_sitio = None
            self._dentro = True
            try:
                await outro()
            finally:
                self._dentro = False
        return await super().update_one(filtro, atualizacao)


def _db_de_duas_maos(registo, linhas, produtos=None):
    vendas = VendasQueMudamAntesDeGravar(registo, [_venda(linhas=linhas)])
    db = DbFalsa({
        COLECOES["caixas"]: ColeccaoFalsa(registo, [_caixa()]),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa(registo, [_sessao()]),
        COLECOES["vendas"]: vendas,
        COLECOES["produtos"]: ColeccaoFalsa(
            registo, produtos if produtos is not None else [_produto()]),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(registo, []),
        COLECOES["documentos"]: ColeccaoFalsa(registo, []),
    })
    return db, vendas


def _linhas_guardadas(db):
    return [li["produto_nome"] for li in db._coleccoes[COLECOES["vendas"]]._documentos[0]["linhas"]]


def test_juntar_linha_nao_ressuscita_a_linha_que_o_outro_sitio_removeu(monkeypatch):
    """A variante que custa dinheiro ao CLIENTE: o juntar leu a conta com o
    açaí, o outro sítio removeu-o, e o juntar gravava o que tinha lido — o
    açaí voltava à conta e ia faturado. Agora a versão não casa, a conta
    relê-se, e a água junta-se à conta como ela está."""
    registo = []
    db, vendas = _db_de_duas_maos(
        registo, [_linha()],
        produtos=[_produto(), _produto(id="prod-agua", nome="Água 33cl", preco=1.0)])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    async def o_outro_sitio_remove_o_acai():
        await remover_linha("venda-1", "linha-1", operador=_operador())

    vendas.o_outro_sitio = o_outro_sitio_remove_o_acai
    resposta = _corre(juntar_linha(
        "venda-1", PedidoJuntarLinha(produto_id="prod-agua"), operador=_operador()))

    assert _linhas_guardadas(db) == ["Água 33cl"]
    assert [li["produto_nome"] for li in resposta["linhas"]] == ["Água 33cl"], (
        "a resposta tem de descrever a conta que ficou gravada, nunca outra"
    )
    assert resposta["totais"]["total"] == 1.0


def test_remover_linha_nao_apaga_a_linha_que_o_outro_sitio_juntou(monkeypatch):
    """A variante que custa dinheiro à LOJA: a remoção leu a conta antes de a
    água existir e gravava a lista lida — a água desaparecia do Mongo depois
    de o ecrã a mostrar na conta, e o cliente levava-a sem a pagar."""
    registo = []
    db, vendas = _db_de_duas_maos(
        registo, [_linha()],
        produtos=[_produto(), _produto(id="prod-agua", nome="Água 33cl", preco=1.0)])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    async def o_outro_sitio_junta_a_agua():
        await juntar_linha(
            "venda-1", PedidoJuntarLinha(produto_id="prod-agua"), operador=_operador())

    vendas.o_outro_sitio = o_outro_sitio_junta_a_agua
    resposta = _corre(remover_linha("venda-1", "linha-1", operador=_operador()))

    assert _linhas_guardadas(db) == ["Água 33cl"]
    assert [li["produto_nome"] for li in resposta["linhas"]] == ["Água 33cl"]


def test_editar_linha_aplica_se_a_conta_como_ela_esta_e_nao_a_que_leu(monkeypatch):
    """A edição é um DELTA ("põe quantidade 2 nesta linha") e tem de cair na
    conta como ela está: gravar a lista lida desfazia a linha que o outro
    sítio juntou pelo meio."""
    registo = []
    db, vendas = _db_de_duas_maos(
        registo, [_linha()],
        produtos=[_produto(), _produto(id="prod-agua", nome="Água 33cl", preco=1.0)])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    async def o_outro_sitio_junta_a_agua():
        await juntar_linha(
            "venda-1", PedidoJuntarLinha(produto_id="prod-agua"), operador=_operador())

    vendas.o_outro_sitio = o_outro_sitio_junta_a_agua
    resposta = _corre(editar_linha(
        "venda-1", "linha-1", PedidoEditarLinha(quantidade=2), operador=_operador()))

    guardadas = db._coleccoes[COLECOES["vendas"]]._documentos[0]["linhas"]
    assert [li["produto_nome"] for li in guardadas] == ["Açaí Regular", "Água 33cl"]
    assert guardadas[0]["quantidade"] == 2
    assert resposta["totais"]["total"] == round(8.99 * 2 + 1.0, 2)


def test_editar_uma_linha_que_o_outro_sitio_removeu_e_404(monkeypatch):
    """O que NÃO se repete às cegas: se a linha a editar desapareceu, ninguém
    a ressuscita — 404, e a conta fica como o outro sítio a deixou."""
    registo = []
    db, vendas = _db_de_duas_maos(registo, [_linha()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    async def o_outro_sitio_remove_o_acai():
        await remover_linha("venda-1", "linha-1", operador=_operador())

    vendas.o_outro_sitio = o_outro_sitio_remove_o_acai
    with pytest.raises(HTTPException) as excinfo:
        _corre(editar_linha(
            "venda-1", "linha-1", PedidoEditarLinha(quantidade=2), operador=_operador()))

    assert excinfo.value.status_code == 404
    assert _linhas_guardadas(db) == []


def test_conta_martelada_de_dois_sitios_acaba_em_409_e_nunca_num_200_falso(monkeypatch):
    """Esgotadas as tentativas, o que a operadora ouve é a verdade — nunca um
    200 sobre uma escrita que não aconteceu."""
    registo = []
    db, vendas = _db_de_duas_maos(
        registo, [_linha()],
        produtos=[_produto(), _produto(id="prod-agua", nome="Água 33cl", preco=1.0)])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    async def o_outro_sitio_nunca_para():
        await juntar_linha(
            "venda-1", PedidoJuntarLinha(produto_id="prod-agua"), operador=_operador())

    vendas.repetir = True
    vendas.o_outro_sitio = o_outro_sitio_nunca_para
    with pytest.raises(HTTPException) as excinfo:
        _corre(remover_linha("venda-1", "linha-1", operador=_operador()))

    assert excinfo.value.status_code == 409
    assert "ao mesmo tempo" in excinfo.value.detail
    assert "Açaí Regular" in _linhas_guardadas(db), (
        "a remoção que respondeu 409 não pode ter apagado nada"
    )


def test_venda_emitida_a_meio_de_uma_alteracao_e_409_e_nao_uma_repeticao(monkeypatch):
    """A outra razão para o filtro não casar: a conta deixou de estar
    `aberta`. Aí não há nada a repetir — a mensagem é a de sempre."""
    registo = []
    db, vendas = _db_de_duas_maos(registo, [_linha()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    async def a_conta_e_emitida():
        db._coleccoes[COLECOES["vendas"]]._documentos[0]["estado"] = "emitida"

    vendas.o_outro_sitio = a_conta_e_emitida
    with pytest.raises(HTTPException) as excinfo:
        _corre(remover_linha("venda-1", "linha-1", operador=_operador()))

    assert excinfo.value.status_code == 409
    assert "já foi emitida" in excinfo.value.detail


def test_dois_toques_no_mesmo_produto_ficam_as_duas_linhas(monkeypatch):
    """O que a operadora pediu foram DOIS açaís, e é isso que tem de ficar na
    conta. Antes desta correcção, dois toques que se cruzassem gravavam cada
    um a sua lista de uma linha e ficava UMA — o cliente levava dois e pagava
    um."""
    registo = []
    db, vendas = _db_de_duas_maos(registo, [])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    async def o_outro_toque():
        await juntar_linha(
            "venda-1", PedidoJuntarLinha(produto_id="prod-1"), operador=_operador())

    vendas.o_outro_sitio = o_outro_toque
    _corre(juntar_linha("venda-1", PedidoJuntarLinha(produto_id="prod-1"),
                        operador=_operador()))

    assert _linhas_guardadas(db) == ["Açaí Regular", "Açaí Regular"]


# --- A guarda que a REPETIÇÃO refaz, e o tecto das tentativas ------------------
#
# O ciclo de `_aplicar_as_linhas` é o único caminho deste módulo que escreve na
# conta DEPOIS de uma releitura. A licença dessa escrita é a guarda que ele
# refaz no topo (`_garante_sem_emissao`): entre a primeira tentativa e a
# segunda pode ter nascido uma reserva fiscal, e uma conta com emissão em curso
# está CONGELADA. Sem essa linha, a repetição escreve numa conta que está a
# virar uma Fatura Simplificada real — pela única porta que o resto do módulo
# não cobre, porque só existe desde que o ciclo existe.


def test_reserva_nascida_entre_duas_tentativas_congela_a_conta(monkeypatch):
    """A ordem exacta: a operadora toca na água; nesse instante, no outro PC, a
    colega carrega em FINALIZAR — a conta muda de versão E nasce a reserva
    fiscal (o Vendus já está a ser contactado). A escrita da água não casa, o
    ciclo relê... e é aqui que se decide.

    Com a guarda refeita: 409 e nada se escreve. Sem ela, a água entrava numa
    conta cuja emissão em voo já a validou como ['Açaí Regular'] (8,99 €) e a
    vai gravar assim — ficava no Mongo uma venda de 9,99 € contra uma Fatura
    Simplificada REAL de 8,99 €, que é exactamente o estrago que a docstring de
    `_garante_sem_emissao` descreve."""
    registo = []
    db, vendas = _db_de_duas_maos(
        registo, [_linha()],
        produtos=[_produto(), _produto(id="prod-agua", nome="Água 33cl", preco=1.0)])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    async def a_colega_carrega_em_finalizar():
        # As duas coisas ao mesmo tempo, e é isso que faz o cenário: a versão
        # muda (a escrita da água não vai casar e o ciclo vai repetir) E nasce
        # a reserva (a conta passa a estar congelada). Uma sem a outra não
        # prova nada — a versão sozinha só faz o ciclo repetir, e a reserva
        # sozinha já é apanhada pela guarda de ENTRADA da rota.
        db._coleccoes[COLECOES["vendas"]]._documentos[0]["linhas_versao"] = 7
        await db[COLECOES["refs_fiscais"]].insert_one(_reserva())

    vendas.o_outro_sitio = a_colega_carrega_em_finalizar
    with pytest.raises(HTTPException) as excinfo:
        _corre(juntar_linha("venda-1", PedidoJuntarLinha(produto_id="prod-agua"),
                            operador=_operador()))

    assert excinfo.value.status_code == 409
    assert "emissão de fatura em curso" in excinfo.value.detail, (
        "a repetição tem de recusar pela EMISSÃO (a conta está congelada), e "
        "não pelo 409 genérico de conta alterada"
    )
    assert _linhas_guardadas(db) == ["Açaí Regular"], (
        "a repetição não pode escrever numa conta que está a virar uma Fatura "
        "Simplificada real"
    )


def test_o_desconto_global_nao_apaga_a_linha_que_o_outro_sitio_juntou(monkeypatch):
    """A QUINTA rota de escrita — a única que ficou em
    `_escrever_se_ainda_aberta` — e a razão por que pode lá ficar: escreve dois
    campos escalares e mais nada.

    Duas escritas de desconto sobrepostas dão o valor de uma delas, nunca um
    valor que ninguém pediu, e não apagam linha nenhuma. É essa promessa que
    este teste prende: basta acrescentar o array `linhas` lido no princípio do
    pedido ao `$set` do desconto — o gesto mais natural de quem queira que a
    resposta traga a conta toda — para a água que a operadora acabou de juntar
    desaparecer do Mongo (e é o Mongo que a Fatura Simplificada lê, não a
    resposta do ecrã)."""

    class VendasQueDeixamOutroPedidoPassarNoDesconto(ColeccaoFalsa):
        """Deixa correr uma alteração INTEIRA de outro sítio no instante exacto
        em que a rota do DESCONTO vai gravar. Precisa de ser um duplo à parte,
        e não o `VendasQueMudamAntesDeGravar`: esse dispara-se por ver
        `linhas` no `$set`, que é precisamente o que o desconto NÃO escreve —
        e um gatilho que só arma com a mutação aplicada não mede nada."""

        def __init__(self, registo, documentos=None):
            super().__init__(registo, documentos)
            self.o_outro_sitio = None

        async def update_one(self, filtro, atualizacao):
            outro = self.o_outro_sitio
            if outro is not None and "desconto_global_pct" in (atualizacao.get("$set") or {}):
                self.o_outro_sitio = None  # só na primeira, como no outro duplo
                await outro()
            return await super().update_one(filtro, atualizacao)

    registo = []
    vendas = VendasQueDeixamOutroPedidoPassarNoDesconto(registo, [_venda(linhas=[_linha()])])
    db = DbFalsa({
        COLECOES["caixas"]: ColeccaoFalsa(registo, [_caixa()]),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa(registo, [_sessao()]),
        COLECOES["vendas"]: vendas,
        COLECOES["produtos"]: ColeccaoFalsa(
            registo, [_produto(), _produto(id="prod-agua", nome="Água 33cl", preco=1.0)]),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(registo, []),
        COLECOES["documentos"]: ColeccaoFalsa(registo, []),
    })
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    async def o_outro_sitio_junta_a_agua():
        await juntar_linha(
            "venda-1", PedidoJuntarLinha(produto_id="prod-agua"), operador=_operador())

    vendas.o_outro_sitio = o_outro_sitio_junta_a_agua
    _corre(aplicar_desconto_global(
        "venda-1", PedidoDescontoGlobal(desconto_pct=10.0), operador=_operador()))

    assert _linhas_guardadas(db) == ["Açaí Regular", "Água 33cl"], (
        "o desconto global não pode gravar o array `linhas` que leu à entrada"
    )
    # E o desconto ficou mesmo escrito: o teste não passa por a rota não ter
    # feito nada.
    assert vendas._documentos[0]["desconto_global_pct"] == 10.0


# --- O TECTO das tentativas, medido -------------------------------------------
#
# `_TENTATIVAS_DE_ESCRITA_DAS_LINHAS` não é folga: é o número de escritores
# simultâneos que a MESMA conta aguenta. Sob contenção em lock-step cada ronda
# deixa passar exactamente um, por isso N escritores precisam de N rondas — com
# quatro tentativas, o 5.º toque simultâneo esgota-as e leva o 409.
#
# Os testes de cima (as "duas mãos") forçam a ordem à mão e provam a CORRECÇÃO.
# Estes provam o TECTO, e para isso precisam de concorrência a sério: o duplo
# normal não tem um único `await` real lá dentro, e um `asyncio.gather` sobre
# ele corre as rotas uma a seguir à outra — cada uma acertava à primeira
# tentativa e o ciclo nunca era exercitado.


class ColeccaoQueCede(ColeccaoFalsa):
    """A mesma colecção, mas cede o controlo ao event loop em CADA operação.

    É o que torna um `gather` uma corrida e não uma fila disfarçada: cada
    leitura e cada escrita passa a ser um ponto de paragem, e as rotas
    entrelaçam-se como se entrelaçam contra o Mongo a sério."""

    async def find_one(self, filtro, projecao=None):
        await asyncio.sleep(0)
        return await super().find_one(filtro, projecao)

    async def update_one(self, filtro, atualizacao):
        await asyncio.sleep(0)
        return await super().update_one(filtro, atualizacao)


def _db_que_cede(registo):
    return DbFalsa({
        COLECOES["caixas"]: ColeccaoQueCede(registo, [_caixa()]),
        COLECOES["sessoes_caixa"]: ColeccaoQueCede(registo, [_sessao()]),
        COLECOES["vendas"]: ColeccaoQueCede(registo, [_venda(linhas=[])]),
        COLECOES["produtos"]: ColeccaoQueCede(registo, [_produto()]),
        COLECOES["refs_fiscais"]: ColeccaoQueCede(registo, []),
        COLECOES["documentos"]: ColeccaoQueCede(registo, []),
    })


def _toques_ao_mesmo_tempo(db, quantos):
    return _corre(asyncio.gather(*[
        juntar_linha("venda-1", PedidoJuntarLinha(produto_id="prod-1"),
                     operador=_operador())
        for _ in range(quantos)
    ], return_exceptions=True))


def test_quatro_toques_ao_mesmo_tempo_entram_todos_na_conta(monkeypatch):
    """Quatro tentativas dão para quatro escritores simultâneos: cada ronda
    deixa passar um, e o último acerta à quarta. Os quatro açaís que a
    operadora picou ficam os quatro na conta — e vão os quatro na Fatura
    Simplificada."""
    registo = []
    db = _db_que_cede(registo)
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    saidas = _toques_ao_mesmo_tempo(db, 4)

    assert [s for s in saidas if isinstance(s, Exception)] == []
    guardadas = db._coleccoes[COLECOES["vendas"]]._documentos[0]
    assert len(guardadas["linhas"]) == 4
    assert guardadas["linhas_versao"] == 4, "quatro escritas, quatro versões"
    assert len({li["id"] for li in guardadas["linhas"]}) == 4, "nenhuma linha a dobrar"


def test_o_quinto_toque_ao_mesmo_tempo_leva_409_e_nunca_se_perde_em_silencio(monkeypatch):
    """O tecto, dito à letra: ao 5.º escritor simultâneo as tentativas
    esgotam-se. O que interessa não é o número — é o que acontece quando ele
    chega ao fim: quatro toques gravados, UM recusado com 409, e a operadora
    informada. Nunca um 200 sobre uma escrita que não aconteceu, nem uma linha
    a desaparecer em silêncio.

    Para lá chegar são precisos cinco separadores do POS a picar a MESMA conta
    ao mesmo tempo — a fila do `PosVenda.js` mantém uma escrita em voo por
    instância, por isso cada separador só contribui com uma."""
    registo = []
    db = _db_que_cede(registo)
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    saidas = _toques_ao_mesmo_tempo(db, 5)

    recusados = [s for s in saidas if isinstance(s, HTTPException)]
    assert [s for s in saidas if isinstance(s, Exception) and s not in recusados] == []
    assert len(recusados) == 1
    assert recusados[0].status_code == 409
    assert "ao mesmo tempo" in recusados[0].detail
    guardadas = db._coleccoes[COLECOES["vendas"]]._documentos[0]
    assert len(guardadas["linhas"]) == 4, (
        "os quatro que passaram ficam gravados; o que foi recusado não escreveu nada"
    )
    assert len(saidas) - len(recusados) == 4, "os outros quatro receberam 201"


# --- O `vendus_ref` no retrato da linha ------------------------------------
#
# O produto do catálogo tem `vendus_ref` (o id dele no Vendus, vindo da
# importação). Sem ele na linha que sai para o Vendus, o Vendus não casa a
# linha por nome e CRIA um produto novo a cada venda — na conta real já eram
# 95 produtos e 13 órfãos só do "Açaí Mini".
#
# O degrau: `_linha_vendus` não passa o produto do CATÁLOGO a
# `linha_de_venda`, passa o RETRATO gravado na própria linha (deliberado — o
# catálogo pode ter mudado ou o artigo ter sido apagado depois de a conta ser
# aberta). Por isso o `vendus_ref` tem de ser gravado na linha quando ela
# nasce, como o nome, o preço e o IVA já eram.

def test_juntar_linha_grava_o_vendus_ref_no_retrato(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], vendas=[_venda()],
             produtos=[_produto(vendus_ref="171258472")])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(juntar_linha(
        "venda-1", PedidoJuntarLinha(produto_id="prod-1", quantidade=1), operador=_operador()
    ))
    assert resultado["linhas"][0]["produto_vendus_ref"] == "171258472"
    # E ficou mesmo GRAVADO, não só na resposta: é da conta gravada que a
    # emissão vai ler o retrato, dias depois de a linha nascer.
    guardada = db._coleccoes[COLECOES["vendas"]]._documentos[0]
    assert guardada["linhas"][0]["produto_vendus_ref"] == "171258472"


def test_juntar_linha_de_produto_sem_vendus_ref_grava_none_e_vende_na_mesma(monkeypatch):
    """Um artigo criado à mão no backoffice não tem `vendus_ref`. A venda
    TEM de passar à mesma — recusá-la deixava a operadora com o cliente à
    frente sem poder cobrar."""
    registo = []
    db = _db(registo, caixas=[_caixa()], vendas=[_venda()], produtos=[_produto()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    resultado = _corre(juntar_linha(
        "venda-1", PedidoJuntarLinha(produto_id="prod-1", quantidade=1), operador=_operador()
    ))
    assert resultado["linhas"][0]["produto_vendus_ref"] is None
    assert resultado["totais"]["total"] == 8.99


def test_o_retrato_da_linha_alimenta_o_id_da_linha_do_vendus(monkeypatch):
    """O caminho todo, ponta a ponta dentro deste módulo: o que `juntar_linha`
    grava é o que `_produto_snapshot` devolve, e é o que faz `linha_de_venda`
    pôr o `id` na linha."""
    registo = []
    db = _db(registo, caixas=[_caixa()], vendas=[_venda()],
             produtos=[_produto(vendus_ref="171258472")])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    _corre(juntar_linha(
        "venda-1", PedidoJuntarLinha(produto_id="prod-1", quantidade=1), operador=_operador()
    ))
    guardada = db._coleccoes[COLECOES["vendas"]]._documentos[0]["linhas"][0]
    assert venda_mod._produto_snapshot(guardada)["vendus_ref"] == "171258472"
    assert venda_mod._linha_vendus(guardada)["id"] == 171258472


def test_uma_linha_gravada_ANTES_desta_alteracao_nao_rebenta():
    """As contas já abertas têm linhas sem o campo novo. Não podem rebentar:
    saem sem `id`, exactamente como saíam — e o dinheiro é o mesmo."""
    antiga = {
        "id": "linha-velha", "produto_id": "prod-1", "produto_nome": "Açaí Regular",
        "produto_preco": 8.99, "produto_tax_id": "INT", "quantidade": 2, "opcoes": [],
        "preco_override": None, "tax_override": None, "desconto_pct": None,
        "desconto_eur": None,
    }  # sem "produto_vendus_ref" — de propósito
    assert venda_mod._produto_snapshot(antiga)["vendus_ref"] is None
    li = venda_mod._linha_vendus(antiga)
    assert "id" not in li
    assert li == {"title": "Açaí Regular", "qty": 2, "gross_price": 8.99, "tax_id": "INT"}
    assert venda_mod._totais(_venda(linhas=[antiga]))["total"] == 17.98


def test_o_id_na_linha_nao_mexe_nos_totais_da_conta():
    """O mesmo total com e sem `vendus_ref` — se algum destes números mudar,
    é sinal de que se mexeu em mais do que devia."""
    def _linha(**over):
        li = {
            "id": "linha-1", "produto_id": "prod-1", "produto_nome": "Açaí Regular",
            "produto_preco": 8.99, "produto_tax_id": "INT", "quantidade": 3, "opcoes": [],
            "preco_override": None, "tax_override": None, "desconto_pct": 10,
            "desconto_eur": None,
        }
        li.update(over)
        return li

    sem = venda_mod._totais(_venda(linhas=[_linha()], desconto_global_eur=1.5))
    com = venda_mod._totais(
        _venda(linhas=[_linha(produto_vendus_ref="171258472")], desconto_global_eur=1.5)
    )
    assert com == sem
