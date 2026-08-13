"""O router do módulo existe, monta em /api/faturacao e responde sem base de dados.

Este teste NÃO importa o server.py de propósito: o server.py lê os.environ["DB_NAME"]
ao ser importado e rebentaria fora do servidor. O pacote faturacao tem de conseguir
ser importado e testado sozinho.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from faturacao import router


def _cliente():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_saude_responde_ok():
    r = _cliente().get("/api/faturacao/saude")
    assert r.status_code == 200
    assert r.json() == {"estado": "ok", "modulo": "faturacao"}


def test_prefixo_do_router():
    assert router.prefix == "/api/faturacao"
