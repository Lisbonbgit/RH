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


def test_nao_existe_indice_unico_sobre_pin_hash():
    """Um índice único que inclua pin_hash NUNCA pode detectar PINs repetidos:
    o bcrypt usa sal aleatório, por isso o mesmo PIN "1234" gera um pin_hash
    diferente de cada vez (ver test_hash_muda_de_cada_vez em test_pins.py).
    Um índice (loja_id, pin_hash) nunca rejeitaria a duplicação real — por
    isso NÃO deve existir. A unicidade do PIN é garantida no servidor: ao
    criar/mudar um PIN, compara-se com bcrypt.checkpw contra os utilizadores
    activos da mesma loja. Não voltes a acrescentar este índice."""
    indices_unicos_com_pin_hash = [
        (coleccao, chaves)
        for (coleccao, chaves, opcoes) in INDICES
        if opcoes.get("unique") and any(chave == "pin_hash" for chave, _direccao in chaves)
    ]
    assert indices_unicos_com_pin_hash == []


def test_existe_indice_unico_parcial_para_sessao_aberta_por_caixa():
    """A garantia central da Task 3 (spec §7.2): impossível haver duas
    sessões abertas na mesma caixa, mesmo com dois PCs a tentar ao mesmo
    tempo. Tem de ser PARCIAL (só estado='aberta') — senão duas sessões
    FECHADAS da mesma caixa (o histórico normal de dois dias diferentes)
    colidiam entre si."""
    unicos = [
        (chaves, opcoes)
        for (coleccao, chaves, opcoes) in INDICES
        if coleccao == "fat_sessoes_caixa" and opcoes.get("unique")
    ]
    assert len(unicos) == 1
    chaves, opcoes = unicos[0]
    assert chaves == [("caixa_id", 1)]
    assert opcoes.get("partialFilterExpression") == {"estado": "aberta"}


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
