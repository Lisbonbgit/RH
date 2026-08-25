"""**Uma pessoa leva estes artigos; o resto continua a ser a conta.**

A terceira forma de repartir (`POST /pos/venda/{id}/separar-parte`), pedida
pelo dono depois de usar o POS do Vendus: nada de decidir a mesa inteira antes
de a primeira fatura sair — leva-se uma pessoa, cobra-se, e a conta segue com
o que sobrou, quantas vezes forem precisas.

O que se guarda aqui é o que muda em relação ao `separar_conta`, e cada um
destes é dinheiro:

1. a soma fecha ao cêntimo entre a PARTE e o que FICA na conta (não entre N
   partes de uma mãe travada);
2. a conta continua `aberta` e sem `conta_mae_id` — é isso que a deixa ser
   separada outra vez, e é o modelo inteiro;
3. o desconto global reparte-se por peso e a percentagem passa a euros nos
   DOIS lados, porque dois caminhos diferentes de arredondar divergem no
   cêntimo que faz a soma das faturas não bater com a gaveta;
4. as duas recusas novas (levar tudo, e deixar uma sobra sem valor), que
   existem para não ficar uma venda `aberta` para sempre;
5. as duas corridas: a conta mudou por baixo, e a emissão reservou depois da
   pergunta. Nas duas a parte tem de MORRER — uma FS a mais não se desfaz.

A matemática de repartir linhas e descontos não se re-testa aqui: é a mesma
do `separar_conta` (`_partes_da_separacao`), guardada em test_venda.py, e é
partilhada de propósito.
"""
import pytest
from fastapi import HTTPException

from faturacao import venda as venda_mod
from faturacao.db import COLECOES
from faturacao.venda import PedidoSepararUmaParte, separar_uma_parte

from .test_venda import (
    ColeccaoComEmissaoAntesDaEscrita, ColeccaoFalsa, DbFalsa,
    _caixa, _corre, _db, _linha, _operador, _reserva, _sessao, _venda,
)

# 19,99 € em três linhas — a conta do print que o dono mandou.
_COOKIE = dict(id="l1", produto_nome="Cookie Tradicional", produto_preco=3.80)
_SMALL = dict(id="l2", produto_nome="Açaí Small", produto_preco=7.20)
_REGULAR = dict(id="l3", produto_nome="Açaí Regular", produto_preco=8.99)


def _conta_de_tres(**over):
    return _venda(linhas=[_linha(**_COOKIE), _linha(**_SMALL), _linha(**_REGULAR)], **over)


def _leva(*ids):
    return PedidoSepararUmaParte(
        linhas=[{"linha_id": i, "quantidade": 1} for i in ids])


def _vendas(db):
    return db._coleccoes[COLECOES["vendas"]]._documentos


# --- O caminho normal ---------------------------------------------------------


def test_a_pessoa_leva_o_que_lhe_deram_e_a_conta_fica_com_o_resto(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_conta_de_tres()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    r = _corre(separar_uma_parte("venda-1", _leva("l1"), operador=_operador()))

    assert r["parte"]["totais"]["total"] == 3.80
    assert r["conta"]["totais"]["total"] == 16.19
    assert round(r["parte"]["totais"]["total"] + r["conta"]["totais"]["total"], 2) == 19.99
    assert [li["produto_nome"] for li in r["parte"]["linhas"]] == ["Cookie Tradicional"]
    assert [li["produto_nome"] for li in r["conta"]["linhas"]] == ["Açaí Small", "Açaí Regular"]


def test_a_conta_continua_aberta_e_a_parte_e_que_e_filha(monkeypatch):
    """O modelo inteiro está nesta asserção: a mãe NÃO fica `separada`. É por
    isso que ela continua a ser a conta em curso do posto (a `GET
    /pos/venda/aberta` devolve a mais recente das abertas, que passa a ser a
    parte, e volta a ser esta assim que aquela for cobrada) e é por isso que
    se pode separar outra vez."""
    registo = []
    db = _db(registo, vendas=[_conta_de_tres()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    r = _corre(separar_uma_parte("venda-1", _leva("l1"), operador=_operador()))

    assert r["conta"]["estado"] == "aberta"
    assert r["conta"]["conta_mae_id"] is None
    assert r["parte"]["estado"] == "aberta"
    assert r["parte"]["conta_mae_id"] == "venda-1"
    assert r["parte"]["caixa_id"] == r["conta"]["caixa_id"]
    assert r["parte"]["sessao_id"] == r["conta"]["sessao_id"]


def test_a_mesma_conta_separa_se_outra_vez_e_outra(monkeypatch):
    """Três pessoas, três chamadas — e ninguém teve de dizer que eram três.
    É o que o `separar_conta` não consegue fazer (exige a conta toda de uma
    vez) e a razão desta rota existir."""
    registo = []
    db = _db(registo, vendas=[_conta_de_tres()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    primeira = _corre(separar_uma_parte("venda-1", _leva("l1"), operador=_operador()))
    segunda = _corre(separar_uma_parte("venda-1", _leva("l2"), operador=_operador()))

    assert primeira["parte"]["totais"]["total"] == 3.80
    assert segunda["parte"]["totais"]["total"] == 7.20
    assert segunda["conta"]["totais"]["total"] == 8.99
    # A terceira pessoa não se separa: ela É a conta, e paga-a como está.
    with pytest.raises(HTTPException) as e:
        _corre(separar_uma_parte("venda-1", _leva("l3"), operador=_operador()))
    assert e.value.status_code == 422
    assert e.value.detail == venda_mod._MSG_PARTE_LEVA_A_CONTA_TODA
    assert round(3.80 + 7.20 + 8.99, 2) == 19.99


def test_uma_linha_de_duas_unidades_separa_se_uma_de_cada_vez(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[
        _linha(id="l1", produto_preco=8.99, quantidade=2)])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    r = _corre(separar_uma_parte("venda-1", _leva("l1"), operador=_operador()))

    assert r["parte"]["totais"]["total"] == 8.99
    assert r["conta"]["totais"]["total"] == 8.99
    assert r["conta"]["linhas"][0]["quantidade"] == 1


# --- O desconto global --------------------------------------------------------


def test_a_percentagem_global_passa_a_euros_nos_dois_lados(monkeypatch):
    """10% sobre 19,99 € são 2,00 €. Se a conta guardasse os 10% e a parte
    levasse a fatia em euros, os dois números vinham por caminhos diferentes
    de arredondar — e é o cêntimo dessa divergência que faz a soma das
    faturas não bater com o que entrou na gaveta."""
    registo = []
    db = _db(registo, vendas=[_conta_de_tres(desconto_global_pct=10)])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    r = _corre(separar_uma_parte("venda-1", _leva("l1"), operador=_operador()))

    assert r["parte"]["desconto_global_pct"] is None
    assert r["conta"]["desconto_global_pct"] is None
    assert round(r["parte"]["totais"]["total"] + r["conta"]["totais"]["total"], 2) == 17.99
    assert round(
        r["parte"]["totais"]["desconto_global"] + r["conta"]["totais"]["desconto_global"], 2
    ) == 2.00


def test_o_desconto_global_em_euros_reparte_se_por_peso(monkeypatch):
    """3,00 € de desconto numa conta de 19,99 €: quem leva o cookie de 3,80 €
    não pode levar o desconto todo."""
    registo = []
    db = _db(registo, vendas=[_conta_de_tres(desconto_global_eur=3.00)])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    r = _corre(separar_uma_parte("venda-1", _leva("l1"), operador=_operador()))

    assert r["parte"]["totais"]["desconto_global"] < 1.00
    assert round(
        r["parte"]["totais"]["desconto_global"] + r["conta"]["totais"]["desconto_global"], 2
    ) == 3.00
    assert round(r["parte"]["totais"]["total"] + r["conta"]["totais"]["total"], 2) == 16.99


# --- As recusas ---------------------------------------------------------------


def test_levar_a_conta_toda_e_recusado(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[_linha(id="l1")])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as e:
        _corre(separar_uma_parte("venda-1", _leva("l1"), operador=_operador()))
    assert e.value.status_code == 422
    assert e.value.detail == venda_mod._MSG_PARTE_LEVA_A_CONTA_TODA
    assert len(_vendas(db)) == 1, "não pode ter nascido parte nenhuma"


def test_uma_sobra_sem_valor_e_recusada(monkeypatch):
    """A oferta que ficasse sozinha na conta: 0,00 € não se factura
    (`fiscal.finalizar` recusa), e a conta ficava aberta para sempre — sem
    nada visível de errado no ecrã da operadora."""
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[
        _linha(id="l1", produto_preco=8.99),
        _linha(id="l2", produto_nome="Oferta", produto_preco=0.0)])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as e:
        _corre(separar_uma_parte("venda-1", _leva("l1"), operador=_operador()))
    assert e.value.status_code == 422
    assert e.value.detail == venda_mod._MSG_RESTO_SEM_VALOR
    assert len(_vendas(db)) == 1


def test_a_parte_sem_valor_e_recusada(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_venda(linhas=[
        _linha(id="l1", produto_preco=8.99),
        _linha(id="l2", produto_nome="Oferta", produto_preco=0.0)])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as e:
        _corre(separar_uma_parte("venda-1", _leva("l2"), operador=_operador()))
    assert e.value.status_code == 422
    assert e.value.detail == venda_mod._MSG_PARTE_SEM_VALOR


def test_uma_parte_nao_se_volta_a_separar(monkeypatch):
    """A guarda de sempre: quem não paga a sua parte não a subdivide."""
    registo = []
    db = _db(registo, vendas=[_conta_de_tres(conta_mae_id="outra")])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as e:
        _corre(separar_uma_parte("venda-1", _leva("l1"), operador=_operador()))
    assert e.value.status_code == 409


def test_a_linha_que_nao_existe_da_404(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_conta_de_tres()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as e:
        _corre(separar_uma_parte("venda-1", _leva("nao-existe"), operador=_operador()))
    assert e.value.status_code == 404


def test_pedir_mais_unidades_do_que_a_conta_tem_e_recusado(monkeypatch):
    registo = []
    db = _db(registo, vendas=[_conta_de_tres()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as e:
        _corre(separar_uma_parte("venda-1", PedidoSepararUmaParte(
            linhas=[{"linha_id": "l1", "quantidade": 2}]), operador=_operador()))
    assert e.value.status_code == 422
    assert "mais gente do que artigos" in e.value.detail
    assert len(_vendas(db)) == 1


# --- As duas corridas ---------------------------------------------------------


class ColeccaoQueMudaAContaAoInserir(ColeccaoFalsa):
    """A outra operadora juntou uma água entre a leitura da conta e a escrita
    que lhe tira as linhas — a janela que o `_a_mae_como_foi_lida` fecha."""

    async def insert_one(self, documento):
        resultado = await super().insert_one(documento)
        for doc in self._documentos:
            if doc["id"] == "venda-1":
                doc["linhas_versao"] = (doc.get("linhas_versao") or 0) + 1
        return resultado


def test_a_conta_que_muda_por_baixo_mata_a_parte_recem_nascida(monkeypatch):
    registo = []
    conta = _conta_de_tres(linhas_versao=3)
    db = DbFalsa({
        COLECOES["caixas"]: ColeccaoFalsa(registo, [_caixa()]),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa(registo, [_sessao()]),
        COLECOES["vendas"]: ColeccaoQueMudaAContaAoInserir(registo, [conta]),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(registo, []),
    })
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as e:
        _corre(separar_uma_parte("venda-1", _leva("l1"), operador=_operador()))

    assert e.value.status_code == 409
    assert [d["id"] for d in db._coleccoes[COLECOES["vendas"]]._documentos] == ["venda-1"], (
        "a parte tem de ser apagada: era uma conta órfã pronta a emitir uma "
        "Fatura Simplificada REAL de artigos que ficaram na conta"
    )
    assert len(conta["linhas"]) == 3, "e a conta não pode ter perdido nada"


def test_a_emissao_que_reserva_depois_da_pergunta_desfaz_a_separacao(monkeypatch):
    """A janela que o `_garante_sem_emissao` não fecha: entre a pergunta e a
    escrita cabe o `finalizar` inteiro. A conta pode estar a virar uma FS
    REAL de 19,99 € enquanto lhe tiramos o cookie — e a parte emitiria os
    mesmos 3,80 € outra vez."""
    registo = []
    conta = _conta_de_tres()
    reservas = []
    db = DbFalsa({
        COLECOES["caixas"]: ColeccaoFalsa(registo, [_caixa()]),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa(registo, [_sessao()]),
        COLECOES["vendas"]: ColeccaoFalsa(registo, [conta]),
        COLECOES["refs_fiscais"]: ColeccaoComEmissaoAntesDaEscrita(
            registo, reservas, lambda: reservas.append(_reserva())),
    })
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as e:
        _corre(separar_uma_parte("venda-1", _leva("l1"), operador=_operador()))

    assert e.value.status_code == 409
    assert [d["id"] for d in db._coleccoes[COLECOES["vendas"]]._documentos] == ["venda-1"]
    assert [li["id"] for li in conta["linhas"]] == ["l1", "l2", "l3"], (
        "as linhas têm de voltar à conta: sem isso o cookie desaparecia de uma "
        "conta que pode estar mesmo a ser emitida"
    )
    assert conta["desconto_global_pct"] is None
