"""Testes do calendário das lojas.

1. As variáveis de ambiente têm de existir ANTES de qualquer `import server`: o pytest
   colecciona `tests/calendario` antes de `tests/crm` e `tests/faturacao`, cujos
   conftest as definem (ler o docstring de tests/crm/conftest.py). Os valores são
   exactamente os mesmos, e `setdefault` nunca sobrepõe um valor que já lá esteja.
2. `mongod_porta` arranca UM mongod para a sessão inteira, numa porta livre e numa
   pasta temporária (molde: `mongo_real` em tests/test_seguranca_login.py). Aqui
   mede-se o que fica GRAVADO — o que um `$set` apaga não se vê num duplo.
"""
import os
import shutil
import socket
import subprocess
import tempfile
import time

import pytest

os.environ.setdefault("POS_JWT_SECRET", "segredo-de-teste-pos")
os.environ.setdefault("JWT_SECRET", "segredo-de-teste")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

import server  # noqa: E402

from .apoio import corre  # noqa: E402

BASE_DE_TESTE = "teste_calendario"


@pytest.fixture(scope="session")
def mongod_porta():
    mongod = shutil.which("mongod") or "/opt/homebrew/bin/mongod"
    if not os.path.exists(mongod):
        pytest.skip("sem mongod nesta máquina: os Locais, as Escalas e o arranque NÃO foram testados contra uma base")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    pasta = tempfile.mkdtemp(prefix="mongod-calendario-")
    proc = subprocess.Popen(
        [mongod, "--dbpath", pasta, "--port", str(porta), "--bind_ip", "127.0.0.1", "--quiet"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", porta), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        proc.terminate()
        pytest.fail("o mongod dos testes não arrancou em 10 s")
    yield porta
    proc.terminate()
    proc.wait(10)
    shutil.rmtree(pasta, ignore_errors=True)


@pytest.fixture
def base(mongod_porta, monkeypatch):
    """Uma base limpa no mongod da sessão, posta no lugar do `server.db`."""
    cliente = AsyncIOMotorClient(f"mongodb://127.0.0.1:{mongod_porta}")
    corre(cliente.drop_database(BASE_DE_TESTE))
    db = cliente[BASE_DE_TESTE]
    monkeypatch.setattr(server, "db", db)
    yield db
    cliente.close()
