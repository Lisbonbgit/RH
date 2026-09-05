"""**O DELETE não pode apagar um movimento do banco.**

A tabela da Conciliação tem um caixote do lixo por linha. Se ele apagasse
movimentos importados do extrato, um clique enganado tirava dinheiro real do
sistema — e o importador não o traz de volta, porque o dedup vê o `dedup_key`
antigo... que já não existe. O extrato é para reimportar, não para apagar.
"""
import asyncio
import os

import pytest
from fastapi import HTTPException

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class ColeccaoFalsa:
    def __init__(self, guardados):
        self.guardados = [dict(d) for d in guardados]
        self.apagados = []

    async def find_one(self, filtro, proj=None, sort=None):
        for doc in self.guardados:
            if all(doc.get(k) == v for k, v in filtro.items()):
                return dict(doc)
        return None

    async def delete_one(self, filtro):
        self.apagados.append(filtro)


class BaseFalsa:
    def __init__(self, movimentos):
        self.fin_movements = movimentos


@pytest.fixture
def sem_permissoes(monkeypatch):
    async def passa(*a, **kw):
        return None
    monkeypatch.setattr(server, "fin_require_editor", passa)


def test_apagar_um_movimento_do_banco_e_recusado(monkeypatch, sem_permissoes):
    movimentos = ColeccaoFalsa([
        {"id": "m1", "company_id": "e1", "source": "bank_import", "manual": False},
    ])
    monkeypatch.setattr(server, "db", BaseFalsa(movimentos))

    with pytest.raises(HTTPException) as erro:
        _corre(server.fin_delete_movement("m1", {"user_id": "u1"}))

    assert erro.value.status_code == 400
    assert movimentos.apagados == []


def test_apagar_uma_linha_manual_e_permitido(monkeypatch, sem_permissoes):
    movimentos = ColeccaoFalsa([
        {"id": "m2", "company_id": "e1", "source": "manual", "manual": True},
    ])
    monkeypatch.setattr(server, "db", BaseFalsa(movimentos))

    _corre(server.fin_delete_movement("m2", {"user_id": "u1"}))

    assert movimentos.apagados == [{"id": "m2"}]


def test_um_movimento_antigo_sem_o_campo_manual_nao_se_apaga(monkeypatch, sem_permissoes):
    # Todos os movimentos importados antes desta obra não têm o campo. A
    # ausência tem de valer "não é manual", nunca o contrário.
    movimentos = ColeccaoFalsa([{"id": "m3", "company_id": "e1", "source": "bank_pdf"}])
    monkeypatch.setattr(server, "db", BaseFalsa(movimentos))

    with pytest.raises(HTTPException):
        _corre(server.fin_delete_movement("m3", {"user_id": "u1"}))
