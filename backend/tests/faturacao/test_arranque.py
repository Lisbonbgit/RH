"""O arranque do módulo (arrancar, em faturacao/__init__.py) não pode derrubar o
RH, o Financeiro nem o Marketing — correm no mesmo server.py e estão em produção
(ver a docstring do módulo). Testa-se com duplos, sem Mongo real.

Achado 1 da revisão final: o try/except só estava dentro de criar_indices, à
volta de cada create_index — mas obter_db() era chamado FORA dele, em
arrancar(), e é aí que o cliente Motor é construído. Com um URI mongodb+srv://
(o que a produção usa, é Atlas), o PyMongo resolve o DNS de forma síncrona na
construção do cliente e levanta ConfigurationError se falhar; essa excepção
saía de arrancar() sem ninguém a apanhar, rebentava o evento de arranque do
FastAPI e abortava o worker do uvicorn — caía tudo. Além disso, os índices
eram criados em série e o arranque esperava por todos: com o Mongo lento, cada
create_index podia esperar até ao tempo limite de selecção de servidor (30s
por omissão) — com 9 índices, minutos com a aplicação a não servir nada, e o
HEALTHCHECK do Dockerfile marca unhealthy aos 110s.
"""
import asyncio

import pytest

import faturacao as faturacao_mod
from faturacao import arrancar
from faturacao import db as db_mod
from faturacao.db import COLECOES


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _reset_indice_idempotencia():
    """`db_mod._indice_idempotencia_ok` é global — sem isto, o resultado de
    um teste "vazava" para o seguinte."""
    db_mod.marcar_indice_idempotencia(None)
    yield
    db_mod.marcar_indice_idempotencia(None)


class _ColeccaoFalsa:
    def __init__(self, indices=None):
        self._indices = indices if indices is not None else {}

    async def create_index(self, chaves, **opcoes):
        return "ok"

    async def index_information(self):
        return self._indices


class _DbFalsa:
    """`refs_fiscais` tem os índices que lhe passarmos; qualquer outra
    colecção aceita create_index sem fazer nada (não é o que este ficheiro
    testa)."""

    def __init__(self, indices_refs_fiscais=None):
        self._indices_refs_fiscais = indices_refs_fiscais

    def __getitem__(self, nome):
        if nome == COLECOES["refs_fiscais"]:
            return _ColeccaoFalsa(self._indices_refs_fiscais)
        return _ColeccaoFalsa()


_INDICE_EXT_REF_PRESENTE = {"ext_ref_1": {"key": [("ext_ref", 1)], "unique": True}}


def test_arrancar_confirma_o_indice_de_idempotencia_quando_presente(monkeypatch):
    monkeypatch.setattr(faturacao_mod, "obter_db", lambda: _DbFalsa(_INDICE_EXT_REF_PRESENTE))
    _corre(arrancar())
    assert db_mod.indice_idempotencia_confirmado() is True


def test_arrancar_nao_confirma_o_indice_de_idempotencia_quando_ausente(monkeypatch):
    """I3, reproduzido: criar_indices "correu" sem levantar nada (o duplo
    aceita create_index sempre — exactamente o que acontece em produção
    quando o índice simplesmente ainda não chegou a ser criado, sem
    nenhuma excepção no meio), mas o índice de `ext_ref` nunca ficou
    mesmo lá. Sem a verificação dedicada, isto passava em silêncio."""
    monkeypatch.setattr(faturacao_mod, "obter_db", lambda: _DbFalsa({}))
    _corre(arrancar())
    assert db_mod.indice_idempotencia_confirmado() is False


def test_arrancar_confirma_o_indice_mesmo_se_criar_indices_demorar_demais(monkeypatch):
    """A verificação dedicada é INDEPENDENTE de criar_indices ter
    conseguido correr — um índice criado num deploy anterior continua lá
    mesmo que ESTA chamada a criar_indices() nunca resolva a tempo."""

    async def _criar_indices_que_nunca_acaba(db):
        await asyncio.sleep(2)

    monkeypatch.setattr(faturacao_mod, "obter_db", lambda: _DbFalsa(_INDICE_EXT_REF_PRESENTE))
    monkeypatch.setattr(faturacao_mod, "criar_indices", _criar_indices_que_nunca_acaba)
    monkeypatch.setattr(faturacao_mod, "LIMITE_INDICES_SEGUNDOS", 0.05)

    _corre(arrancar())
    assert db_mod.indice_idempotencia_confirmado() is True


def test_arrancar_nao_confirma_o_indice_quando_criar_indices_demora_e_o_indice_nao_existe(monkeypatch):
    """O cenário concreto do defeito: Atlas lento, criar_indices corta aos
    LIMITE_INDICES_SEGUNDOS antes de chegar ao índice de ext_ref (o
    último dos 22) — a verificação dedicada apanha isto e recusa
    confirmar."""

    async def _criar_indices_que_nunca_acaba(db):
        await asyncio.sleep(2)

    monkeypatch.setattr(faturacao_mod, "obter_db", lambda: _DbFalsa({}))
    monkeypatch.setattr(faturacao_mod, "criar_indices", _criar_indices_que_nunca_acaba)
    monkeypatch.setattr(faturacao_mod, "LIMITE_INDICES_SEGUNDOS", 0.05)

    _corre(arrancar())
    assert db_mod.indice_idempotencia_confirmado() is False


def test_arrancar_nao_confirma_o_indice_se_obter_db_rebentar(monkeypatch):
    def _obter_db_rebentada():
        raise RuntimeError("falha de configuração simulada (DNS do Atlas)")

    monkeypatch.setattr(faturacao_mod, "obter_db", _obter_db_rebentada)
    _corre(arrancar())
    assert db_mod.indice_idempotencia_confirmado() is False


def test_arrancar_nao_propaga_se_obter_db_rebentar(monkeypatch):
    """Simula o ConfigurationError síncrono do PyMongo ao resolver um URI
    mongodb+srv:// na construção do cliente Motor (produção usa Atlas)."""

    def _obter_db_rebentada():
        raise RuntimeError("falha de configuração simulada (DNS do Atlas)")

    monkeypatch.setattr(faturacao_mod, "obter_db", _obter_db_rebentada)

    _corre(arrancar())  # não pode levantar


def test_arrancar_nao_propaga_se_criar_indices_demorar_demais(monkeypatch):
    """Simula um Mongo lento: criar_indices nunca resolve dentro do limite
    total. arrancar() tem de cortar a espera e devolver o controlo — o
    módulo funciona sem índices, só mais devagar; o portal não pode ficar
    em baixo por causa disso."""

    async def _criar_indices_que_nunca_acaba(db):
        await asyncio.sleep(2)

    monkeypatch.setattr(faturacao_mod, "obter_db", lambda: object())
    monkeypatch.setattr(faturacao_mod, "criar_indices", _criar_indices_que_nunca_acaba)
    # Limite curto só para o teste não demorar — ver LIMITE_INDICES_SEGUNDOS.
    monkeypatch.setattr(faturacao_mod, "LIMITE_INDICES_SEGUNDOS", 0.05)

    _corre(arrancar())  # não pode levantar nem esperar os 2s todos
