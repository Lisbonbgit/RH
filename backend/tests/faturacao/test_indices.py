"""Os índices são declarados como dados e aplicados por criar_indices.

Testa-se com um duplo que regista as chamadas, para não ser preciso um Mongo.
"""
import asyncio

from faturacao.db import (
    INDICES,
    criar_indices,
    indice_idempotencia_confirmado,
    indice_idempotencia_presente,
    marcar_indice_idempotencia,
)


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


def test_existe_indice_unico_de_ext_ref_em_fat_refs_fiscais():
    """A GARANTIA da Task 3 (spec §6.1 passo 2): a reserva atómica só
    funciona se este índice existir — sem ele, duas tentativas concorrentes
    da mesma venda podiam inserir as duas com sucesso e emitir duas
    faturas."""
    unicos = [
        chaves
        for (coleccao, chaves, opcoes) in INDICES
        if coleccao == "fat_refs_fiscais" and opcoes.get("unique")
    ]
    assert unicos == [[("ext_ref", 1)]]


def test_existe_indice_unico_de_vendus_document_id_e_de_atcud_em_fat_documentos():
    """Terceira e quarta defesa da Task 3: mesmo que a reserva falhasse por
    alguma razão, o Vendus nunca atribui o mesmo `vendus_document_id` nem o
    mesmo ATCUD a dois documentos — um índice único sobre cada um recusa uma
    segunda gravação."""
    unicos_documentos = [
        chaves
        for (coleccao, chaves, opcoes) in INDICES
        if coleccao == "fat_documentos" and opcoes.get("unique")
    ]
    assert [("vendus_document_id", 1)] in unicos_documentos
    assert [("atcud", 1)] in unicos_documentos


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


# --- I3: o índice de idempotência é VERIFICADO, nunca assumido ------------------
#
# criar_indices (acima) engole a falha de CADA índice individualmente, e o
# arranque (faturacao/__init__.py) corta a criação toda aos
# LIMITE_INDICES_SEGUNDOS — com um Mongo Atlas lento, o índice único de
# fat_refs_fiscais.ext_ref (o último dos 22, o mais provável de ficar por
# criar) podia nunca chegar a existir, em silêncio, e o POS continuava a
# servir sem defesa nenhuma contra o duplo-toque. `indice_idempotencia_
# presente` confirma esse índice concreto, a sério — nunca "criar_indices
# não rebentou, logo deve estar lá".


class ColeccaoComIndices:
    def __init__(self, indices):
        self._indices = indices

    async def index_information(self):
        return self._indices


class DbComIndices:
    def __init__(self, indices_por_coleccao):
        self._indices_por_coleccao = indices_por_coleccao

    def __getitem__(self, nome):
        return ColeccaoComIndices(self._indices_por_coleccao.get(nome, {}))


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_indice_idempotencia_presente_quando_o_indice_unico_existe():
    db = DbComIndices({
        "fat_refs_fiscais": {
            "_id_": {"key": [("_id", 1)]},
            "ext_ref_1": {"key": [("ext_ref", 1)], "unique": True},
        }
    })
    assert _corre(indice_idempotencia_presente(db)) is True


def test_indice_idempotencia_ausente_quando_o_indice_nao_existe():
    """O caso concreto do defeito: criar_indices "correu" (não levantou
    nada), mas o índice único nunca ficou criado (Atlas lento + timeout
    global) — só sobra o _id_ automático."""
    db = DbComIndices({"fat_refs_fiscais": {"_id_": {"key": [("_id", 1)]}}})
    assert _corre(indice_idempotencia_presente(db)) is False


def test_indice_idempotencia_ausente_quando_existe_mas_nao_e_unico():
    """Um índice em ext_ref que exista mas NÃO seja único não dá nenhuma
    garantia contra o duplo-toque — não conta como presente."""
    db = DbComIndices({
        "fat_refs_fiscais": {"ext_ref_1": {"key": [("ext_ref", 1)]}},  # sem unique
    })
    assert _corre(indice_idempotencia_presente(db)) is False


def test_indice_idempotencia_ausente_se_a_verificacao_rebentar():
    class ColeccaoRebentada:
        async def index_information(self):
            raise RuntimeError("Atlas indisponível")

    class DbRebentada:
        def __getitem__(self, nome):
            return ColeccaoRebentada()

    assert _corre(indice_idempotencia_presente(DbRebentada())) is False


def test_marcar_e_ler_o_estado_confirmado():
    marcar_indice_idempotencia(True)
    assert indice_idempotencia_confirmado() is True
    marcar_indice_idempotencia(False)
    assert indice_idempotencia_confirmado() is False
    # None (nunca confirmado, ex.: arrancar() nunca correu) conta como "não
    # confirmado" — nunca um "assumido OK" por omissão.
    marcar_indice_idempotencia(None)
    assert indice_idempotencia_confirmado() is False
