"""**Um PUT à empresa não pode apagar as categorias dela.**

O `fin_update_company` faz um `$set` explícito com `name` e `nif`. Acrescentar
`categorias` ao modelo e escrevê-lo sempre significa que qualquer ecrã que
guarde o nome da empresa — e o de Configurações guarda — apaga a lista de
categorias que a diretora financeira montou, sem ninguém dar por isso.

Por isso o campo só se escreve quando vem MESMO no pedido (`exclude_unset`),
e a lista de omissão serve quem nunca a personalizou.
"""
import asyncio
import os

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class EmpresasFalsas:
    def __init__(self, guardadas):
        self.guardadas = [dict(d) for d in guardadas]
        self.updates = []

    async def find_one(self, filtro, proj=None):
        for doc in self.guardadas:
            if doc.get("id") == filtro.get("id"):
                return dict(doc)
        return None

    async def update_one(self, filtro, update):
        self.updates.append(update)
        for doc in self.guardadas:
            if doc.get("id") == filtro.get("id"):
                doc.update(update.get("$set", {}))


class BaseFalsa:
    def __init__(self, empresas):
        self.fin_companies = empresas


@pytest.fixture
def sem_permissoes(monkeypatch):
    async def passa(*a, **kw):
        return None
    monkeypatch.setattr(server, "fin_require_owner", passa)


def test_guardar_so_o_nome_nao_apaga_as_categorias(monkeypatch, sem_permissoes):
    empresas = EmpresasFalsas([
        {"id": "e1", "name": "Fordaimon", "nif": "500000000",
         "categorias": [{"id": "gelo", "label": "Gelo"}]},
    ])
    monkeypatch.setattr(server, "db", BaseFalsa(empresas))

    payload = server.FinCompanyCreate(name="Fordaimon Foods", nif="500000000")
    _corre(server.fin_update_company("e1", payload, {"user_id": "u1"}))

    assert "categorias" not in empresas.updates[0]["$set"], (
        "o PUT escreveu categorias sem ninguém as ter enviado — isto apaga a "
        "lista da empresa de cada vez que se muda o nome"
    )
    assert empresas.guardadas[0]["categorias"] == [{"id": "gelo", "label": "Gelo"}]


def test_enviar_categorias_guarda_as_categorias(monkeypatch, sem_permissoes):
    empresas = EmpresasFalsas([{"id": "e1", "name": "Fordaimon", "nif": None}])
    monkeypatch.setattr(server, "db", BaseFalsa(empresas))

    payload = server.FinCompanyCreate(
        name="Fordaimon", categorias=[{"id": "gelo", "label": "Gelo"}]
    )
    _corre(server.fin_update_company("e1", payload, {"user_id": "u1"}))

    assert empresas.guardadas[0]["categorias"] == [{"id": "gelo", "label": "Gelo"}]


def test_uma_empresa_sem_lista_usa_a_de_omissao(monkeypatch):
    empresas = EmpresasFalsas([{"id": "e1", "name": "Fordaimon"}])
    monkeypatch.setattr(server, "db", BaseFalsa(empresas))

    cats = _corre(server._fin_categorias_da_empresa("e1"))

    assert cats is server.FIN_CATEGORIAS_PADRAO
    ids = [c["id"] for c in cats]
    assert "entradas" in ids and "fornecedor" in ids and "rendas" in ids


def test_uma_lista_vazia_nao_deixa_a_empresa_sem_categorias(monkeypatch):
    empresas = EmpresasFalsas([{"id": "e1", "name": "Fordaimon", "categorias": []}])
    monkeypatch.setattr(server, "db", BaseFalsa(empresas))

    assert _corre(server._fin_categorias_da_empresa("e1")) is server.FIN_CATEGORIAS_PADRAO
