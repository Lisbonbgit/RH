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


# ---------- revisão pré-deploy (2026-10-01) ----------

class _UsersLentos(_UsersFalsos):
    """Como o Atlas: o find_one cede o event loop antes de responder."""

    async def find_one(self, filtro, proj=None):
        await asyncio.sleep(0.01)
        return await super().find_one(filtro, proj)


def test_login_em_rajada_paralela_nao_fura_o_limite(monkeypatch):
    db = _DbFalsa([])
    db.users = _UsersLentos([])
    monkeypatch.setattr(server, "db", db)
    limite._falhas.clear()
    cred = server.UserLogin(email="alvo@example.com", password="errada")
    req = _pedido("9.9.9.9, 172.18.0.5")

    async def um():
        try:
            await server.login(cred, req)
        except HTTPException as e:
            return e.status_code

    async def rajada():
        return await asyncio.gather(*[um() for _ in range(60)])

    rs = _corre(rajada())
    assert rs.count(401) == server.LOGIN_FALHAS_POR_CONTA
    assert rs.count(429) == 60 - server.LOGIN_FALHAS_POR_CONTA
    limite._falhas.clear()


def test_login_certo_nao_gasta_vaga(monkeypatch):
    monkeypatch.setattr(server, "JWT_SECRET", os.environ["JWT_SECRET"])
    monkeypatch.setattr(server, "db", _DbFalsa([{
        "id": "u1", "email": "ok@example.com", "name": "Ok", "role": "colaborador",
        "password": server.hash_password("Certa#2026x")}]))
    limite._falhas.clear()
    req = _pedido("5.5.5.5, 172.18.0.5")
    for _ in range(server.LOGIN_FALHAS_POR_IP + 5):
        assert _corre(server.login(server.UserLogin(email="ok@example.com", password="Certa#2026x"), req))["token"]
    limite._falhas.clear()


# ---------- contra um mongod REAL (um duplo não mede atomicidade) ----------

import shutil  # noqa: E402
import socket  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


@pytest.fixture(scope="module")
def mongo_real():
    if not shutil.which("mongod"):
        pytest.skip("sem mongod nesta máquina: o contador do código de recuperação NÃO foi testado")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    pasta = tempfile.mkdtemp(prefix="mongod-teste-")
    proc = subprocess.Popen(
        ["mongod", "--dbpath", pasta, "--port", str(porta), "--bind_ip", "127.0.0.1", "--quiet"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", porta), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    db = AsyncIOMotorClient(f"mongodb://127.0.0.1:{porta}")["teste_seguranca"]
    yield db
    proc.terminate()
    proc.wait(10)
    shutil.rmtree(pasta, ignore_errors=True)


@pytest.fixture
def base(mongo_real, monkeypatch):
    _corre(mongo_real.client.drop_database("teste_seguranca"))
    monkeypatch.setattr(server, "db", mongo_real)
    monkeypatch.setattr(fat_auth, "obter_db", lambda: mongo_real)
    monkeypatch.setattr(server, "JWT_SECRET", os.environ["JWT_SECRET"])
    codigos = []

    async def envia(email, user_name, reset_code):
        codigos.append(reset_code)
        return True

    monkeypatch.setattr(server, "send_password_reset_email", envia)
    _corre(mongo_real.users.insert_one({
        "id": "u1", "email": "ana@example.com", "name": "Ana", "role": "gerente",
        "password": server.hash_password("Certa#2026x")}))
    return mongo_real, codigos


def _estado(coro):
    try:
        _corre(coro)
        return 200
    except HTTPException as e:
        return e.status_code


def _verify(code):
    return server.verify_reset_code(server.VerifyResetCodeRequest(email="ana@example.com", code=code))


def test_codigos_em_paralelo_so_gastam_o_teto(base):
    db, codigos = base
    _corre(server.forgot_password(server.ForgotPasswordRequest(email="ana@example.com")))
    certo = codigos[-1]
    errados = [f"{i:06d}" for i in range(60) if f"{i:06d}" != certo][:50]

    async def tenta(c):
        try:
            await _verify(c)
        except HTTPException as e:
            return e.status_code

    async def todos():
        return await asyncio.gather(*[tenta(c) for c in errados])

    rs = _corre(todos())
    assert rs.count(400) == server.RESET_MAX_TENTATIVAS
    assert rs.count(429) == 50 - server.RESET_MAX_TENTATIVAS
    assert _corre(db.users.find_one({"id": "u1"}))["reset_tentativas"] == server.RESET_MAX_TENTATIVAS
    assert _estado(_verify(certo)) == 429  # esgotado vale mesmo com o código certo


def test_fluxo_normal_redefine_e_limpa_os_contadores(base):
    db, codigos = base
    _corre(server.forgot_password(server.ForgotPasswordRequest(email="ana@example.com")))
    c = codigos[-1]
    assert _estado(_verify("999999" if c != "999999" else "888888")) == 400
    assert _estado(_verify(c)) == 200
    assert _estado(server.reset_password(server.ResetPasswordCodeRequest(
        email="ana@example.com", code=c, new_password="Nova#2026xy"))) == 200
    doc = _corre(db.users.find_one({"id": "u1"}))
    assert "reset_tentativas" not in doc and "reset_password_token" not in doc
    assert server.verify_password("Nova#2026xy", doc["password"])


def test_segundo_pedido_no_mesmo_minuto_nao_gera_codigo(base):
    _, codigos = base
    for _ in range(3):
        _corre(server.forgot_password(server.ForgotPasswordRequest(email="ana@example.com")))
    assert len(codigos) == 1


def test_com_tentativas_esgotadas_nao_se_envia_codigo_novo(base):
    db, codigos = base
    _corre(db.users.update_one({"id": "u1"}, {"$set": {
        "reset_tentativas": server.RESET_MAX_TENTATIVAS,
        "reset_tentativas_desde": server.datetime.now(server.timezone.utc).isoformat()}}))
    _corre(server.forgot_password(server.ForgotPasswordRequest(email="ana@example.com")))
    assert codigos == []


def test_trocar_a_password_termina_as_sessoes_anteriores(base):
    db, codigos = base
    antigo = server.create_token("u1", "ana@example.com", "gerente")
    cred = HTTPAuthorizationCredentials(scheme="Bearer", credentials=antigo)
    assert _corre(server.get_current_user(cred))["role"] == "gerente"
    time.sleep(1.1)  # o iat tem resolução de segundos
    _corre(server.forgot_password(server.ForgotPasswordRequest(email="ana@example.com")))
    _corre(server.reset_password(server.ResetPasswordCodeRequest(
        email="ana@example.com", code=codigos[-1], new_password="Nova#2026xy")))
    assert _estado(server.get_current_user(cred)) == 401
    assert _estado(fat_auth.utilizador_atual(cred)) == 401
    novo = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=server.create_token("u1", "ana@example.com", "gerente"))
    assert _corre(server.get_current_user(novo))["role"] == "gerente"


def test_mudar_password_devolve_token_que_funciona(base):
    cred = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=server.create_token("u1", "ana@example.com", "gerente"))
    eu = _corre(server.get_current_user(cred))
    r = _corre(server.change_password(server.ChangePasswordRequest(
        current_password="Certa#2026x", new_password="Nova#2026xy"), eu))
    novo = HTTPAuthorizationCredentials(scheme="Bearer", credentials=r["token"])
    assert _corre(server.get_current_user(novo))["user_id"] == "u1"


def test_empresa_com_nif_ja_repetido_continua_editavel(base, monkeypatch):
    db, _ = base

    async def dono(company_id, current_user):
        return None

    monkeypatch.setattr(server, "fin_require_owner", dono)
    _corre(db.fin_companies.insert_many([
        {"id": "real", "name": "Real", "nif": "500000000"},
        {"id": "falsa", "name": "Falsa", "nif": "500000000"},  # deixada pelo código antigo
    ]))
    eu = {"user_id": "u1", "role": "gerente"}
    r = _corre(server.fin_update_company("real", server.FinCompanyCreate(name="Real SA", nif="500000000"), eu))
    assert r.name == "Real SA"
    _corre(db.fin_companies.insert_one({"id": "outra", "name": "Outra", "nif": "999999990"}))
    assert _estado(server.fin_update_company(
        "outra", server.FinCompanyCreate(name="Outra", nif="500000000"), eu)) == 409
