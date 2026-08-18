"""A conta do balcão (Plano 2B, Task 2) — fat_vendas.

Mesmo padrão de duplo de base de dados que test_caixa_endpoints.py:
find()/find_one() filtram de facto pelos campos do filtro. Nenhum teste liga
a uma base de dados nem à rede.

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
from datetime import datetime

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from faturacao import router as router_do_modulo
from faturacao import venda as venda_mod
from faturacao.db import COLECOES
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
    remover_linha,
    venda_aberta,
)


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- Duplo de base de dados (mesmo padrão de test_caixa_endpoints.py) --------


def _corresponde(item, filtro):
    if not filtro:
        return True
    return all(item.get(chave) == valor for chave, valor in filtro.items())


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
    def __init__(self, registo, documentos=None):
        self.registo = registo
        self._documentos = documentos if documentos is not None else []

    def find(self, filtro=None, projecao=None):
        self.registo.append(("find", filtro))
        return CursorFalso([d for d in self._documentos if _corresponde(d, filtro)])

    async def find_one(self, filtro, projecao=None):
        self.registo.append(("find_one", filtro))
        encontrados = [d for d in self._documentos if _corresponde(d, filtro)]
        return encontrados[0] if encontrados else None

    async def insert_one(self, doc):
        self.registo.append(("insert_one", dict(doc)))
        self._documentos.append(doc)
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


def _db(registo, caixas=None, sessoes=None, vendas=None, produtos=None):
    return DbFalsa({
        COLECOES["caixas"]: ColeccaoFalsa(registo, caixas),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa(registo, sessoes),
        COLECOES["vendas"]: ColeccaoFalsa(registo, vendas),
        COLECOES["produtos"]: ColeccaoFalsa(registo, produtos),
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
    """`/pos/venda/aberta` não pode ser engolida por nenhuma rota de
    `{venda_id}`: o FastAPI serve a PRIMEIRA rota que casa com o caminho, e
    no dia em que alguém declarar um `GET /pos/venda/{venda_id}` por cima
    desta, o "aberta" passava a ser lido como um id de venda — 404 à
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
