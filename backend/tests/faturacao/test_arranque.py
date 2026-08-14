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

import faturacao as faturacao_mod
from faturacao import arrancar


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


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
