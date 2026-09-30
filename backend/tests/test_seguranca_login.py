"""Os três buracos da auditoria de 2026-09-30, cada um preso por um teste.

1. Força bruta no login (o código de recuperação tem o contador na BASE e é
   provado ponta-a-ponta contra um mongod real — um duplo não mede atomicidade).
2. Um colaborador criava empresas no Financeiro e mexia nas regras globais.
3. O token valia 24 h depois de a pessoa ser apagada ou despromovida.
"""
import asyncio
import os

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")
os.environ.setdefault("JWT_SECRET", "segredo-de-teste")

import limite  # noqa: E402
import server  # noqa: E402
from faturacao import auth as fat_auth  # noqa: E402


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _pedido(xff=None, host="10.0.0.9"):
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "headers": headers, "client": (host, 1)})


# ---------- 1. login ----------

def test_ip_e_o_penultimo_do_forwarded_for():
    # "cliente, caddy" — o nginx junta o do Caddy no fim
    assert limite.ip_do_cliente(_pedido("1.2.3.4, 172.18.0.5")) == "1.2.3.4"


def test_ip_inventado_pelo_cliente_nao_passa_a_frente():
    assert limite.ip_do_cliente(_pedido("6.6.6.6, 1.2.3.4, 172.18.0.5")) == "1.2.3.4"


def test_sem_forwarded_for_usa_a_ligacao():
    assert limite.ip_do_cliente(_pedido()) == "10.0.0.9"


def test_bloqueia_a_partir_do_limite_e_solta_quando_a_janela_passa():
    chave = ("teste", "janela")
    for i in range(3):
        assert not limite.bloqueado(chave, 3, 60, agora=100 + i)
        limite.falhou(chave, 60, agora=100 + i)
    assert limite.bloqueado(chave, 3, 60, agora=103)
    assert not limite.bloqueado(chave, 3, 60, agora=161)


class _UsersFalsos:
    def __init__(self, docs):
        self.docs = docs

    async def find_one(self, filtro, proj=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in filtro.items() if not isinstance(v, dict)):
                return dict(d)
        return None


class _DbFalsa:
    def __init__(self, users):
        self.users = _UsersFalsos(users)


def test_login_da_429_depois_de_falhas_seguidas(monkeypatch):
    monkeypatch.setattr(server, "db", _DbFalsa([]))
    limite._falhas.clear()
    cred = server.UserLogin(email="alvo@example.com", password="errada")
    req = _pedido("9.9.9.9, 172.18.0.5")
    for _ in range(server.LOGIN_FALHAS_POR_CONTA):
        with pytest.raises(HTTPException) as e:
            _corre(server.login(cred, req))
        assert e.value.status_code == 401
    with pytest.raises(HTTPException) as e:
        _corre(server.login(cred, req))
    assert e.value.status_code == 429
    limite._falhas.clear()


# ---------- 2. Financeiro ----------

def test_colaborador_nao_cria_empresa_no_financeiro():
    with pytest.raises(HTTPException) as e:
        _corre(server.fin_create_company(
            server.FinCompanyCreate(name="Minha", nif="500000000"),
            {"user_id": "u1", "role": "colaborador"},
        ))
    assert e.value.status_code == 403


def test_colaborador_dono_de_empresa_nao_e_editor_global():
    # Mesmo com uma empresa em seu nome (criada antes da correção), não passa.
    assert _corre(server._fin_user_is_editor_somewhere({"user_id": "u1", "role": "colaborador"})) is False


def test_nif_repetido_e_recusado(monkeypatch):
    class _Empresas:
        async def find_one(self, filtro, proj=None):
            assert filtro["nif"] == "500000000"
            return {"id": "a-real"} if filtro["id"]["$ne"] != "a-real" else None

    class _Db:
        fin_companies = _Empresas()

    monkeypatch.setattr(server, "db", _Db())
    with pytest.raises(HTTPException) as e:
        _corre(server._fin_nif_livre("500 000 000"))
    assert e.value.status_code == 409
    _corre(server._fin_nif_livre("500000000", "a-real"))  # a própria empresa pode manter o NIF


# ---------- 3. token de quem já não existe ----------

def _cred(**payload):
    import jwt
    base = {"user_id": "u1", "email": "a@example.com", "role": "admin", "employee_id": None}
    base.update(payload)
    return HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=jwt.encode(base, os.environ["JWT_SECRET"], algorithm="HS256"))


def test_token_de_utilizador_apagado_e_recusado(monkeypatch):
    monkeypatch.setattr(server, "JWT_SECRET", os.environ["JWT_SECRET"])
    monkeypatch.setattr(server, "db", _DbFalsa([]))
    with pytest.raises(HTTPException) as e:
        _corre(server.get_current_user(_cred()))
    assert e.value.status_code == 401


def test_papel_vem_da_base_e_nao_do_token(monkeypatch):
    monkeypatch.setattr(server, "JWT_SECRET", os.environ["JWT_SECRET"])
    monkeypatch.setattr(server, "db", _DbFalsa([{"id": "u1", "role": "colaborador", "email": "a@example.com"}]))
    assert _corre(server.get_current_user(_cred(role="admin")))["role"] == "colaborador"


def test_pos_tambem_le_o_papel_da_base(monkeypatch):
    monkeypatch.setattr(fat_auth, "obter_db", lambda: _DbFalsa([{"id": "u1", "role": "colaborador"}]))
    utilizador = _corre(fat_auth.utilizador_atual(_cred(role="admin")))
    with pytest.raises(HTTPException) as e:
        fat_auth.exigir_gestao(utilizador)
    assert e.value.status_code == 403


def test_pos_recusa_utilizador_apagado(monkeypatch):
    monkeypatch.setattr(fat_auth, "obter_db", lambda: _DbFalsa([]))
    with pytest.raises(HTTPException) as e:
        _corre(fat_auth.utilizador_atual(_cred()))
    assert e.value.status_code == 401
