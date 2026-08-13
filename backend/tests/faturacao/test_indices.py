"""Os índices são declarados como dados e aplicados por criar_indices.

Testa-se com um duplo que regista as chamadas, para não ser preciso um Mongo.
"""
import asyncio

from faturacao.db import INDICES, criar_indices


class ColeccaoFalsa:
    def __init__(self, nome, registo):
        self.nome = nome
        self.registo = registo

    async def create_index(self, chaves, **opcoes):
        self.registo.append((self.nome, chaves, opcoes))
        return "ok"


class DbFalsa:
    def __init__(self):
        self.registo = []

    def __getitem__(self, nome):
        return ColeccaoFalsa(nome, self.registo)


def test_declara_indice_unico_de_pin_por_loja():
    chaves = [(c, k) for (c, k, o) in INDICES if c == "fat_utilizadores" and o.get("unique")]
    assert ("fat_utilizadores", [("loja_id", 1), ("pin_hash", 1)]) in chaves


def test_criar_indices_aplica_todos():
    db = DbFalsa()
    asyncio.get_event_loop().run_until_complete(criar_indices(db))
    assert len(db.registo) == len(INDICES)


def test_criar_indices_nao_rebenta_se_um_falhar():
    """Um índice que falhe (ex.: dados antigos duplicados) não pode impedir o arranque."""

    class ColeccaoRebentada(ColeccaoFalsa):
        async def create_index(self, chaves, **opcoes):
            raise RuntimeError("índice duplicado")

    class DbRebentada(DbFalsa):
        def __getitem__(self, nome):
            return ColeccaoRebentada(nome, self.registo)

    asyncio.get_event_loop().run_until_complete(criar_indices(DbRebentada()))
