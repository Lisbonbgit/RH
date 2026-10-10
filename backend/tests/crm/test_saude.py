"""O router do CRM existe, monta em /api/crm e responde sem base de dados.

Molde: tests/faturacao/test_saude.py. Este teste NÃO importa o server.py de
propósito: o pacote crm tem de conseguir ser importado e testado sozinho (a
montagem no server.py é a T1.9, com o seu próprio teste).
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from crm import router


def _cliente():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_saude_responde_ok():
    r = _cliente().get("/api/crm/saude")
    assert r.status_code == 200
    assert r.json() == {"estado": "ok", "modulo": "crm"}


def test_saude_e_publica_sem_cabecalho_de_sessao():
    # Nenhum Authorization: a rota é da família "pública" (T1.8).
    r = _cliente().get("/api/crm/saude", headers={})
    assert r.status_code == 200


def test_prefixo_do_router():
    assert router.prefix == "/api/crm"


def test_etiqueta_do_router():
    assert router.tags == ["crm"]
