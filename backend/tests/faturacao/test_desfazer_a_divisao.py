"""**A seta de voltar desfaz a divisão** — e a conta fica inteira outra vez.

O dono, ao usar o POS: dividiu a conta, carregou na seta ao lado do Finalizar,
e ficou preso — a grelha apagada, sem poder acrescentar o artigo de que o
cliente se lembrou. Sem esta rota, a única saída era cancelar as partes uma a
uma e **repicar a conta toda**: cancelar uma parte não devolve os artigos dela
a lado nenhum.

A regra, nas palavras dele: «se eu estiver na página da divisão e clicar na
seta, automaticamente é cancelada a divisão; se eu quiser pôr mais produtos,
ponho; se quiser dividir outra vez, clico em Finalizar e divido de novo.»

O que este ficheiro guarda é o limite: **isto só se faz enquanto nada
aconteceu**. Uma parte emitida é uma Fatura Simplificada real e não se desfaz
com um toque na seta.
"""
import pytest
from fastapi import HTTPException

from faturacao import venda as venda_mod
from faturacao.db import COLECOES
from faturacao.venda import PedidoDividir, desfazer_divisao, dividir_conta

from .test_venda import _corre, _db, _linha, _operador, _reserva, _venda


def _conta_dividida(monkeypatch, n=2, linhas=None):
    """Uma conta mesmo dividida, pela rota a sério — e não um retrato à mão
    de como ela ficaria."""
    linhas = linhas or [_linha(id="l1", produto_preco=3.80),
                        _linha(id="l2", produto_preco=8.99)]
    db = _db([], vendas=[_venda(linhas=linhas)])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)
    r = _corre(dividir_conta("venda-1", PedidoDividir(partes=n), operador=_operador()))
    return db, r


def _vendas(db):
    return db._coleccoes[COLECOES["vendas"]]._documentos


def test_a_conta_volta_inteira_e_com_os_artigos_todos(monkeypatch):
    db, _ = _conta_dividida(monkeypatch)

    conta = _corre(desfazer_divisao("venda-1", operador=_operador()))

    assert conta["estado"] == "aberta"
    assert [li["id"] for li in conta["linhas"]] == ["l1", "l2"]
    assert conta["totais"]["total"] == 12.79
    assert [d["id"] for d in _vendas(db)] == ["venda-1"], (
        "as partes têm de desaparecer: uma divisão desfeita antes de existir "
        "não é uma venda cancelada, é uma que nunca chegou a acontecer"
    )


def test_e_divide_se_outra_vez_a_seguir(monkeypatch):
    """O caminho que o dono descreveu: desfaz-se, acrescenta-se (ou não), e
    divide-se de novo pelo Finalizar."""
    db, _ = _conta_dividida(monkeypatch)
    _corre(desfazer_divisao("venda-1", operador=_operador()))

    r = _corre(dividir_conta("venda-1", PedidoDividir(partes=3), operador=_operador()))
    assert [p["totais"]["total"] for p in r["partes"]] == [4.27, 4.26, 4.26]


def test_uma_parte_JA_EMITIDA_impede_desfazer(monkeypatch):
    """A Fatura Simplificada é real e não se desfaz com um toque na seta."""
    db, r = _conta_dividida(monkeypatch)
    for doc in _vendas(db):
        if doc.get("conta_mae_id"):
            doc["estado"] = "emitida"
            doc["documento_id"] = "doc-1"
            break

    with pytest.raises(HTTPException) as e:
        _corre(desfazer_divisao("venda-1", operador=_operador()))
    assert e.value.status_code == 409
    assert "nota de crédito" in e.value.detail
    assert len([d for d in _vendas(db) if d.get("conta_mae_id")]) == 2, (
        "nenhuma parte pode ter sido apagada"
    )


def test_uma_parte_CANCELADA_tambem_impede(monkeypatch):
    """Cancelar uma parte é uma decisão de alguém — os artigos dela saíram sem
    fatura e sem dinheiro. Desfazer a divisão por cima disso era apagar essa
    decisão sem ninguém a ver."""
    db, _ = _conta_dividida(monkeypatch)
    for doc in _vendas(db):
        if doc.get("conta_mae_id"):
            doc["estado"] = "cancelada"
            break

    with pytest.raises(HTTPException) as e:
        _corre(desfazer_divisao("venda-1", operador=_operador()))
    assert e.value.status_code == 409


def test_uma_parte_com_emissao_em_curso_impede(monkeypatch):
    """A reserva fiscal viva quer dizer que pode estar a nascer uma FS neste
    instante — o estado da parte ainda diz `aberta` e não conta a história."""
    linhas = [_linha(id="l1", produto_preco=3.80), _linha(id="l2", produto_preco=8.99)]
    db = _db([], vendas=[_venda(linhas=linhas)])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)
    r = _corre(dividir_conta("venda-1", PedidoDividir(partes=2), operador=_operador()))
    parte_id = r["partes"][0]["id"]
    db._coleccoes[COLECOES["refs_fiscais"]]._documentos.append(_reserva(venda_id=parte_id))

    with pytest.raises(HTTPException) as e:
        _corre(desfazer_divisao("venda-1", operador=_operador()))
    assert e.value.status_code == 409
    assert len([d for d in _vendas(db) if d.get("conta_mae_id")]) == 2


def test_uma_conta_que_nao_esta_dividida_diz_isso(monkeypatch):
    db = _db([], vendas=[_venda(linhas=[_linha()])])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)
    with pytest.raises(HTTPException) as e:
        _corre(desfazer_divisao("venda-1", operador=_operador()))
    assert e.value.status_code == 409
    assert e.value.detail == venda_mod._MSG_NAO_ESTA_DIVIDIDA


def test_a_emissao_da_MAE_em_curso_tambem_impede(monkeypatch):
    """A guarda de sempre das rotas de escrita: com uma reserva na mãe, não se
    lhe toca."""
    linhas = [_linha(id="l1", produto_preco=3.80), _linha(id="l2", produto_preco=8.99)]
    db = _db([], vendas=[_venda(linhas=linhas)])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)
    _corre(dividir_conta("venda-1", PedidoDividir(partes=2), operador=_operador()))
    db._coleccoes[COLECOES["refs_fiscais"]]._documentos.append(_reserva(venda_id="venda-1"))

    with pytest.raises(HTTPException) as e:
        _corre(desfazer_divisao("venda-1", operador=_operador()))
    assert e.value.status_code == 409
