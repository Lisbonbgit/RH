"""**O saldo de uma conta é o do ÚLTIMO movimento, e "último" tem regra.**

Num dia com vários movimentos na mesma conta, a data não chega para desempatar.
O painel já resolve isto com `sort=[("date_lancamento", -1), ("_id", -1)]` — a
ordem de inserção do extrato. É por isso que este cálculo não pode ser feito no
browser: o `_id` vem excluído de todas as projeções e o frontend não consegue
reproduzir o desempate; mostraria um saldo arbitrário do dia.

E uma linha escrita à mão não tem saldo nenhum — não pode ser escolhida como o
último movimento, senão o cartão passa a mostrar `None` como se fosse 0.
"""
import asyncio
import os

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class ContasFalsas:
    def __init__(self, guardadas):
        self.guardadas = [dict(d) for d in guardadas]

    def find(self, filtro, proj=None):
        docs = [dict(d) for d in self.guardadas
                if d.get("company_id") == filtro.get("company_id")]

        class Cursor:
            async def to_list(self, n):
                return docs
        return Cursor()


class MovimentosFalsos:
    """Guarda a ordenação pedida e responde-lhe a sério (ordem de inserção como
    substituto honesto do _id)."""

    def __init__(self, guardados):
        self.guardados = [dict(d, _ordem=i) for i, d in enumerate(guardados)]
        self.sorts = []

    async def find_one(self, filtro, proj=None, sort=None):
        self.sorts.append(sort)
        candidatos = []
        for doc in self.guardados:
            ok = True
            for campo, esperado in filtro.items():
                valor = doc.get(campo)
                if isinstance(esperado, dict) and "$ne" in esperado:
                    if valor == esperado["$ne"]:
                        ok = False
                elif valor != esperado:
                    ok = False
            if ok:
                candidatos.append(doc)
        if not candidatos:
            return None
        for campo, direccao in reversed(sort or []):
            chave = "_ordem" if campo == "_id" else campo
            candidatos.sort(key=lambda d: (d.get(chave) is None, d.get(chave)),
                            reverse=(direccao == -1))
        return dict(candidatos[0])


class BaseFalsa:
    def __init__(self, contas, movimentos):
        self.fin_bank_accounts = contas
        self.fin_movements = movimentos


@pytest.fixture
def sem_permissoes(monkeypatch):
    async def scope(company_id, current_user):
        return company_id
    monkeypatch.setattr(server, "_fin_report_scope", scope)


def test_no_mesmo_dia_ganha_o_ultimo_inserido(monkeypatch, sem_permissoes):
    contas = ContasFalsas([{"id": "c1", "company_id": "e1", "bank": "Millennium", "name": "Millennium"}])
    movimentos = MovimentosFalsos([
        {"id": "m1", "account_id": "c1", "date_lancamento": "2026-09-30", "balance": 100.0},
        {"id": "m2", "account_id": "c1", "date_lancamento": "2026-09-30", "balance": 3192.91},
    ])
    monkeypatch.setattr(server, "db", BaseFalsa(contas, movimentos))

    res = _corre(server.fin_bank_account_balances("e1", {"user_id": "u1"}))

    assert movimentos.sorts[0] == [("date_lancamento", -1), ("_id", -1)], (
        "sem o desempate por _id o saldo do dia sai arbitrário"
    )
    assert res["contas"][0]["balance"] == 3192.91


def test_uma_linha_a_mao_nunca_e_o_saldo(monkeypatch, sem_permissoes):
    contas = ContasFalsas([{"id": "c1", "company_id": "e1", "bank": "Millennium", "name": "Millennium"}])
    movimentos = MovimentosFalsos([
        {"id": "m1", "account_id": "c1", "date_lancamento": "2026-09-01", "balance": 3192.91},
        {"id": "m2", "account_id": "c1", "date_lancamento": "2026-09-30", "balance": None, "manual": True},
    ])
    monkeypatch.setattr(server, "db", BaseFalsa(contas, movimentos))

    res = _corre(server.fin_bank_account_balances("e1", {"user_id": "u1"}))

    assert res["contas"][0]["balance"] == 3192.91


def test_uma_conta_sem_movimentos_diz_nao_sei_e_nao_zero(monkeypatch, sem_permissoes):
    contas = ContasFalsas([
        {"id": "c1", "company_id": "e1", "bank": "Millennium", "name": "Millennium"},
        {"id": "c2", "company_id": "e1", "bank": "Revolut", "name": "Revolut"},
    ])
    movimentos = MovimentosFalsos([
        {"id": "m1", "account_id": "c1", "date_lancamento": "2026-09-01", "balance": 3192.91},
    ])
    monkeypatch.setattr(server, "db", BaseFalsa(contas, movimentos))

    res = _corre(server.fin_bank_account_balances("e1", {"user_id": "u1"}))

    por_nome = {c["name"]: c for c in res["contas"]}
    assert por_nome["Revolut"]["balance"] is None, "desconhecido não é zero"
    assert res["total"] == 3192.91
