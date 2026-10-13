"""O arranque do CRM (crm.arrancar, chamado pelo server.py a partir da T1.9)
nunca derruba o portal: o RH, o Financeiro e a Faturação correm no mesmo
processo e estão em produção.

Molde: tests/faturacao/test_arranque.py — mas com `correr` (tests/crm/duplos.py)
e nunca com o asyncio.run, que deixava a thread principal sem ciclo de eventos
para os testes da Faturação (correções do plano, §10).
"""
import asyncio
import logging
import time

import crm
import crm.db

from .duplos import BaseFalsa, correr


def test_limite_de_tempo_dos_indices_e_de_10_segundos():
    assert crm.LIMITE_INDICES_SEGUNDOS == 10


def test_arrancar_cria_os_indices_na_base_do_crm(monkeypatch):
    base = BaseFalsa()
    monkeypatch.setattr(crm.db, "obter_db", lambda: base)
    correr(crm.arrancar())
    assert len(base.crm_membros.chamadas("create_index")) == len(
        [1 for (c, _k, _o) in crm.db.INDICES if c == "crm_membros"]
    )


def test_arrancar_nao_propaga_se_obter_db_rebentar(monkeypatch, caplog):
    """Simula o ConfigurationError síncrono do PyMongo ao resolver um URI
    mongodb+srv:// na construção do cliente (a produção usa o Atlas)."""

    def _obter_db_rebentada():
        raise RuntimeError("falha de configuração simulada (DNS do Atlas)")

    monkeypatch.setattr(crm.db, "obter_db", _obter_db_rebentada)
    with caplog.at_level(logging.ERROR, logger="crm"):
        correr(crm.arrancar())  # não pode levantar
    assert any(r.getMessage().startswith("[crm]") for r in caplog.records)


def test_arrancar_nao_propaga_se_criar_indices_rebentar(monkeypatch):
    async def _criar_indices_rebentado(db):
        raise RuntimeError("rebentou")

    monkeypatch.setattr(crm.db, "obter_db", lambda: BaseFalsa())
    monkeypatch.setattr(crm.db, "criar_indices", _criar_indices_rebentado)
    correr(crm.arrancar())  # não pode levantar


def test_arrancar_corta_a_espera_se_criar_indices_ficar_pendurado(monkeypatch, caplog):
    """Mongo lento: criar_indices nunca acaba dentro do limite. O arranque
    volta em ~LIMITE_INDICES_SEGUNDOS e o módulo funciona sem índices (mais
    lento, não indisponível)."""

    async def _criar_indices_pendurado(db):
        await asyncio.sleep(3)

    monkeypatch.setattr(crm.db, "obter_db", lambda: BaseFalsa())
    monkeypatch.setattr(crm.db, "criar_indices", _criar_indices_pendurado)
    monkeypatch.setattr(crm, "LIMITE_INDICES_SEGUNDOS", 0.05)

    inicio = time.monotonic()
    with caplog.at_level(logging.ERROR, logger="crm"):
        correr(crm.arrancar())
    assert time.monotonic() - inicio < 1.0
    assert any(
        r.getMessage().startswith("[crm]") and "0.05" in r.getMessage() for r in caplog.records
    )
