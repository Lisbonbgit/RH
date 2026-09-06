"""**Uma linha escrita à mão não pode fingir que passou no banco.**

O saldo de cada conta é o `balance` do último movimento. Se uma linha manual
gravasse `balance`, o cartão "Valor Contas" passava a mostrar um saldo que o
banco nunca disse — e é esse número que a diretora financeira usa para decidir
o que pode pagar.

E não pode ter `dedup_key`: o dedup do importador procura por essa chave, e uma
linha manual a partilhá-la faria o extrato a sério ser descartado como repetido.
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
        self.inseridos = []

    async def find_one(self, filtro, proj=None, sort=None):
        for doc in self.guardados:
            if all(doc.get(k) == v for k, v in filtro.items()):
                return dict(doc)
        return None

    async def insert_one(self, doc):
        self.inseridos.append(doc)
        self.guardados.append(dict(doc))


class BaseFalsa:
    def __init__(self, movimentos, empresas):
        self.fin_movements = movimentos
        self.fin_companies = empresas


@pytest.fixture
def sem_permissoes(monkeypatch):
    async def passa(*a, **kw):
        return None
    monkeypatch.setattr(server, "fin_require_editor", passa)


def _base(monkeypatch):
    movimentos = ColeccaoFalsa()
    empresas = ColeccaoFalsa([{"id": "e1", "categorias": [{"id": "entradas", "label": "Entradas"}]}])
    monkeypatch.setattr(server, "db", BaseFalsa(movimentos, empresas))
    return movimentos


def test_a_linha_manual_nao_grava_saldo(monkeypatch, sem_permissoes):
    movimentos = _base(monkeypatch)

    payload = server.FinMovementCreate(
        company_id="e1", date_lancamento="2026-09-01",
        description="Dinheiro Restante Mês Anterior", amount=1104.97, category="entradas",
    )
    _corre(server.fin_create_movement(payload, {"user_id": "u1"}))

    doc = movimentos.inseridos[0]
    assert doc.get("balance") is None
    assert "dedup_key" not in doc
    assert doc["manual"] is True
    assert doc["source"] == "manual"
    assert doc["account_id"] is None


def test_a_linha_manual_aceita_montante_negativo(monkeypatch, sem_permissoes):
    movimentos = _base(monkeypatch)

    payload = server.FinMovementCreate(
        company_id="e1", date_lancamento="2026-09-01", description="Ajuste", amount=-50.0,
    )
    _corre(server.fin_create_movement(payload, {"user_id": "u1"}))

    assert movimentos.inseridos[0]["amount"] == -50.0
