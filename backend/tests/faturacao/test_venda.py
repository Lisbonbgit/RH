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
"""
import asyncio

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from faturacao import venda as venda_mod
from faturacao.db import COLECOES
from faturacao.precos import linha_de_venda
from faturacao.venda import (
    PedidoDescontoGlobal,
    PedidoEditarLinha,
    PedidoJuntarLinha,
    PedidoNovaVenda,
    abrir_venda,
    aplicar_desconto_global,
    editar_linha,
    juntar_linha,
    remover_linha,
)


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- Duplo de base de dados (mesmo padrão de test_caixa_endpoints.py) --------


def _corresponde(item, filtro):
    if not filtro:
        return True
    return all(item.get(chave) == valor for chave, valor in filtro.items())


class ColeccaoFalsa:
    def __init__(self, registo, documentos=None):
        self.registo = registo
        self._documentos = documentos if documentos is not None else []

    def find(self, filtro=None):
        self.registo.append(("find", filtro))
        return [d for d in self._documentos if _corresponde(d, filtro)]

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
        return None


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
