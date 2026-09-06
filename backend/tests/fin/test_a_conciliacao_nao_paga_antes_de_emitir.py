"""**Um pagamento não pode conciliar com uma fatura ainda por emitir.**

O motor pontua pares fatura↔movimento e o montante igual vale 50 pontos
sozinho, num limiar de 65 — o nome do fornecedor na descrição chega para o
passar. Sem a guarda da data, uma renda de 1.200 € paga em Agosto casa com a
fatura de 1.200 € emitida em Setembro: o sistema dá a de Setembro por paga e a
de Agosto fica por pagar para sempre.

A guarda vive no `fin_reconcile_suggestions` (`mvd < issue`), NÃO no
`_fin_reconcile_score` — que só olha para a distância absoluta em dias e não
sabe distinguir 15 dias antes de 15 dias depois. Testar a pontuação não
defenderia nada.

Este é o primeiro teste deste motor. Ele está em produção desde que a
conciliação existe.
"""
import asyncio
import os

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class ColeccaoFalsa:
    def __init__(self, guardados=None):
        self.guardados = [dict(d) for d in (guardados or [])]

    def find(self, filtro=None, proj=None):
        docs = [dict(d) for d in self.guardados]

        class Cursor:
            async def to_list(self, n):
                return docs
        return Cursor()


class BaseFalsa:
    def __init__(self, faturas, movimentos):
        self.fin_invoices = faturas
        self.fin_movements = movimentos
        self.fin_supplier_rules = ColeccaoFalsa()
        self.fin_reconcile_dismissed = ColeccaoFalsa()


def _fatura(emissao):
    return {
        "id": "f1", "company_id": "e1", "supplier": "EDP Comercial",
        "invoice_number": "FT 2026/812", "amount": 1200.0,
        "issue_date": emissao, "due_date": emissao,
    }


def _movimento(data):
    return {
        "id": "m1", "company_id": "e1", "date_lancamento": data,
        "amount": -1200.0, "description": "PAGAMENTO SERVICOS EDP COMERCIAL",
    }


@pytest.fixture
def sem_permissoes(monkeypatch):
    async def passa(*a, **kw):
        return None

    async def sem_carimbos():
        return {}
    monkeypatch.setattr(server, "fin_require_member", passa)
    monkeypatch.setattr(server, "_fin_carimbos_by_supplier", sem_carimbos)


def _sugestoes(monkeypatch, emissao, data_pagamento):
    base = BaseFalsa(ColeccaoFalsa([_fatura(emissao)]), ColeccaoFalsa([_movimento(data_pagamento)]))
    monkeypatch.setattr(server, "db", base)
    return _corre(server.fin_reconcile_suggestions("e1", {"user_id": "u1"}))


def test_pagar_antes_de_a_fatura_existir_nao_e_sugerido(monkeypatch, sem_permissoes):
    out = _sugestoes(monkeypatch, emissao="2026-09-01", data_pagamento="2026-08-15")

    assert out == [], (
        "um pagamento de Agosto foi casado com uma fatura emitida em Setembro — "
        "a de Setembro fica dada por paga e a de Agosto por pagar para sempre"
    )


def test_o_mesmo_par_com_as_datas_pela_ordem_certa_e_sugerido(monkeypatch, sem_permissoes):
    out = _sugestoes(monkeypatch, emissao="2026-08-01", data_pagamento="2026-08-15")

    assert len(out) == 1, "o par legítimo deixou de ser sugerido"
    assert out[0]["invoice"]["id"] == "f1"
    assert out[0]["movement"]["id"] == "m1"
    assert out[0]["score"] >= 65
