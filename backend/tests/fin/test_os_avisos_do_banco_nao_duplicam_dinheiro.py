"""**O mesmo movimento não pode entrar duas vezes por dois documentos.**

O banco manda duas coisas diferentes para a caixa:

* o EXTRATO, com o período todo e a coluna de saldo;
* o AVISO de lançamento, com UM movimento e SEM saldo (medido: 80 em 30 dias
  do Millennium).

O aviso entra marcado `provisorio`, para o dinheiro aparecer no dia em que
acontece. O perigo é o extrato chegar depois com os MESMOS movimentos: a
descrição e o saldo diferem entre os dois documentos, por isso nem a dedup_key
nem a comparação por saldo os reconhecem — e a transferência ficava contada
duas vezes no fecho do mês.

A regra é: quando chega o extrato de um período, ele MANDA e apaga os avisos
que cobre. Menos os que já têm fatura ligada — esses foram ligados por uma
pessoa, e apagá-los desfazia o trabalho dela e deixava a fatura dada por paga
sem movimento nenhum por trás.
"""
import asyncio
import os

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _casa(doc, filtro):
    for campo, esperado in filtro.items():
        valor = doc.get(campo)
        if isinstance(esperado, dict):
            if "$gte" in esperado and not (valor is not None and valor >= esperado["$gte"]):
                return False
            if "$lte" in esperado and not (valor is not None and valor <= esperado["$lte"]):
                return False
            if "$in" in esperado and valor not in esperado["$in"]:
                return False
        elif valor != esperado:
            return False
    return True


class MovimentosFalsos:
    def __init__(self, guardados=None):
        self.guardados = [dict(d) for d in (guardados or [])]
        self.inseridos = []

    async def find_one(self, filtro, proj=None, sort=None):
        for doc in self.guardados:
            if _casa(doc, filtro):
                return dict(doc)
        return None

    def find(self, filtro, proj=None):
        docs = [dict(d) for d in self.guardados if _casa(d, filtro)]

        class Cursor:
            async def to_list(self, n):
                return docs
        return Cursor()

    async def insert_one(self, doc):
        self.inseridos.append(doc)
        self.guardados.append(dict(doc))

    async def delete_many(self, filtro):
        antes = len(self.guardados)
        self.guardados = [d for d in self.guardados if not _casa(d, filtro)]

        class Res:
            deleted_count = antes - len(self.guardados)
        return Res()


class BaseFalsa:
    def __init__(self, movimentos):
        self.fin_movements = movimentos


CONTA = {"id": "c1", "company_id": "e1", "account_number": "0000045740375997", "currency": "EUR"}
AVISO = [{"date_lancamento": "2026-09-04", "date_valor": "2026-09-04",
          "description": "TRANSFERÊNCIA A CRÉDITO - TRF. P/O Fordaimon Foods Lda",
          "amount": 665.02, "balance": None}]


def test_um_aviso_sem_saldo_entra_marcado_como_provisorio(monkeypatch):
    movs = MovimentosFalsos()
    monkeypatch.setattr(server, "db", BaseFalsa(movs))

    ins, salt = _corre(server._fin_guardar_movimentos_do_banco(
        CONTA, AVISO, "bank_email", provisorio=True))

    assert (ins, salt) == (1, 0)
    doc = movs.inseridos[0]
    assert doc["provisorio"] is True
    assert doc["balance"] is None
    assert doc["amount"] == 665.02
    assert doc["source"] == "bank_email"


def test_ler_o_mesmo_aviso_outra_vez_nao_duplica(monkeypatch):
    movs = MovimentosFalsos()
    monkeypatch.setattr(server, "db", BaseFalsa(movs))

    _corre(server._fin_guardar_movimentos_do_banco(CONTA, AVISO, "bank_email", provisorio=True))
    ins, salt = _corre(server._fin_guardar_movimentos_do_banco(CONTA, AVISO, "bank_email", provisorio=True))

    assert (ins, salt) == (0, 1), "a mesma nota de lançamento entrou duas vezes"
    assert len(movs.guardados) == 1


def test_um_movimento_ja_la_estar_pelo_extrato_trava_o_aviso(monkeypatch):
    # O extrato entrou primeiro (com saldo); o aviso do mesmo movimento chega
    # depois. Mesma conta, mesmo dia, mesmo valor, mesma descrição.
    movs = MovimentosFalsos([{
        "id": "m0", "account_id": "c1", "date_lancamento": "2026-09-04",
        "amount": 665.02, "balance": 3192.91,
        "description": "TRANSFERÊNCIA A CRÉDITO - TRF. P/O Fordaimon Foods Lda",
        "dedup_key": "outra", "provisorio": False,
    }])
    monkeypatch.setattr(server, "db", BaseFalsa(movs))

    ins, salt = _corre(server._fin_guardar_movimentos_do_banco(
        CONTA, AVISO, "bank_email", provisorio=True))

    assert (ins, salt) == (0, 1), "o dinheiro ficou contado a dobrar"


def test_dois_pagamentos_iguais_no_mesmo_dia_sao_dois(monkeypatch):
    # Duas transferências de 100 € no mesmo dia com descrições diferentes são
    # dois movimentos. Uma trava só por data+valor comia um deles.
    movs = MovimentosFalsos()
    monkeypatch.setattr(server, "db", BaseFalsa(movs))
    dois = [
        {"date_lancamento": "2026-09-04", "description": "TRF FORNECEDOR A", "amount": -100.0, "balance": None},
        {"date_lancamento": "2026-09-04", "description": "TRF FORNECEDOR B", "amount": -100.0, "balance": None},
    ]

    ins, salt = _corre(server._fin_guardar_movimentos_do_banco(CONTA, dois, "bank_email", provisorio=True))

    assert (ins, salt) == (2, 0), "duas saídas distintas foram tomadas por uma"


def test_o_extrato_apaga_os_avisos_do_periodo_que_cobre(monkeypatch):
    movs = MovimentosFalsos([
        {"id": "p1", "account_id": "c1", "date_lancamento": "2026-09-02",
         "provisorio": True, "invoice_id": None},
        {"id": "p2", "account_id": "c1", "date_lancamento": "2026-09-20",
         "provisorio": True, "invoice_id": None},
        {"id": "real", "account_id": "c1", "date_lancamento": "2026-09-03",
         "provisorio": False, "invoice_id": None},
    ])
    monkeypatch.setattr(server, "db", BaseFalsa(movs))

    apagados = _corre(server._fin_substituir_provisorios("c1", "2026-09-01", "2026-09-10"))

    assert apagados == 1
    ids = sorted(d["id"] for d in movs.guardados)
    assert ids == ["p2", "real"], "apagou fora do período, ou apagou o que veio do extrato"


def test_um_aviso_com_fatura_ligada_nao_se_apaga(monkeypatch):
    # Alguém ligou aquilo à mão. Apagar desfazia trabalho humano e deixava a
    # fatura dada por paga sem movimento nenhum por trás.
    movs = MovimentosFalsos([
        {"id": "p1", "account_id": "c1", "date_lancamento": "2026-09-02",
         "provisorio": True, "invoice_id": "f1"},
    ])
    monkeypatch.setattr(server, "db", BaseFalsa(movs))

    apagados = _corre(server._fin_substituir_provisorios("c1", "2026-09-01", "2026-09-10"))

    assert apagados == 0
    assert len(movs.guardados) == 1
