"""**Um campo que não vem no pedido não pode ser apagado.**

A tabela da Conciliação guarda campo a campo: mudar a categoria manda só a
categoria. Se o endpoint escrevesse sempre os três campos, escolher uma
categoria apagava a anotação que a diretora financeira acabou de escrever ao
lado — e ninguém ligaria as duas coisas.

E a categoria tem de ser da lista DA EMPRESA: aceitar texto livre é como não
ter lista nenhuma, e os cartões de resumo passam a somar categorias que não
existem em sítio nenhum.
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
        self.updates = []

    async def find_one(self, filtro, proj=None, sort=None):
        for doc in self.guardados:
            if all(doc.get(k) == v for k, v in filtro.items()):
                return dict(doc)
        return None

    async def update_one(self, filtro, update):
        self.updates.append(update)
        for doc in self.guardados:
            if doc.get("id") == filtro.get("id"):
                doc.update(update.get("$set", {}))


class BaseFalsa:
    def __init__(self, movimentos, empresas):
        self.fin_movements = movimentos
        self.fin_companies = empresas


@pytest.fixture
def sem_permissoes(monkeypatch):
    async def passa(*a, **kw):
        return None
    monkeypatch.setattr(server, "fin_require_editor", passa)


def _base(monkeypatch, mv_extra=None):
    mv = {"id": "m1", "company_id": "e1", "amount": -10.0,
          "title": "MAKRO", "note": "combinado com a Rafaela", "category": None}
    mv.update(mv_extra or {})
    movimentos = ColeccaoFalsa([mv])
    empresas = ColeccaoFalsa([{"id": "e1", "categorias": [{"id": "supermercado", "label": "Supermercado"}]}])
    monkeypatch.setattr(server, "db", BaseFalsa(movimentos, empresas))
    return movimentos


def test_mudar_so_a_categoria_nao_apaga_a_anotacao(monkeypatch, sem_permissoes):
    movimentos = _base(monkeypatch)

    payload = server.FinMovementFields(category="supermercado")
    _corre(server.fin_update_movement("m1", payload, {"user_id": "u1"}))

    escrito = movimentos.updates[0]["$set"]
    assert escrito == {"category": "supermercado"}, (
        "o endpoint escreveu campos que ninguém enviou — isto apaga a anotação "
        "de quem só mudou a categoria"
    )
    assert movimentos.guardados[0]["note"] == "combinado com a Rafaela"


def test_uma_anotacao_vazia_limpa_a_anotacao(monkeypatch, sem_permissoes):
    movimentos = _base(monkeypatch)

    payload = server.FinMovementFields(note="")
    _corre(server.fin_update_movement("m1", payload, {"user_id": "u1"}))

    assert movimentos.guardados[0]["note"] is None


def test_uma_categoria_fora_da_lista_da_empresa_e_recusada(monkeypatch, sem_permissoes):
    _base(monkeypatch)

    payload = server.FinMovementFields(category="criptomoedas")
    with pytest.raises(HTTPException) as erro:
        _corre(server.fin_update_movement("m1", payload, {"user_id": "u1"}))
    assert erro.value.status_code == 400


def test_limpar_a_categoria_e_sempre_permitido(monkeypatch, sem_permissoes):
    movimentos = _base(monkeypatch, {"category": "supermercado"})

    payload = server.FinMovementFields(category=None)
    _corre(server.fin_update_movement("m1", payload, {"user_id": "u1"}))

    assert movimentos.guardados[0]["category"] is None
