"""Entrar com o email escrito com outras maiúsculas.

O caso que o pediu (registos de produção): o gestor corrigiu o email do Carlos
e gravou-o «Carlos.Silva@…». O Carlos fez seis vezes «Esqueci a palavra-passe»
→ código certo → palavra-passe nova e, logo a seguir, o login dava 401. O
«Esqueci» procurava a conta sem diferenciar maiúsculas e o login tal e qual; o
EmailStr só põe o domínio em minúsculas, e o telemóvel escreve «carlos.silva@…».

A regra agora é uma só (`server._conta_pelo_email`), no login, no «Esqueci» e
na equipa do Financeiro: tal e qual primeiro; senão a conta da mesma caixa com
outras maiúsculas, mas só se for UMA. Duas contas que só diferem nas
maiúsculas (de antes desta correção) entram cada uma com o seu email tal e
qual, e uma terceira grafia não escolhe nenhuma ao acaso. E já não se cria (nem
se edita para) um email que só difere nas maiúsculas de uma conta existente.

Contra um mongod REAL (molde: tests/test_editar_email_colaborador.py).
"""
import asyncio
import os
import shutil
import socket
import subprocess
import tempfile
import time

import pytest
from fastapi import HTTPException
from starlette.requests import Request

os.environ.setdefault("POS_JWT_SECRET", "segredo-de-teste-pos")
os.environ.setdefault("JWT_SECRET", "segredo-de-teste")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

import limite  # noqa: E402
import server  # noqa: E402

BASE_DE_TESTE = "teste_login_maiusculas"
MESTRE = "mestre@example.com"
CARLOS = "Carlos.Silva@example.com"  # gravado como o gestor o escreveu
SENHA = "Certa#2026x"
ERRADA = "Errada#2026x"
NOVA = "Nova#2026xyz"
# Duas contas que só diferem nas maiúsculas, deixadas pelo código antigo.
RUI_A, SENHA_A = "Rui@example.com", "DoRuiA#2026"
RUI_B, SENHA_B = "rui@example.com", "DoRuiB#2026"
MASTER = {"user_id": "u-mestre", "role": "admin", "email": MESTRE, "employee_id": None}


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module")
def mongod_porta():
    mongod = shutil.which("mongod") or "/opt/homebrew/bin/mongod"
    if not os.path.exists(mongod):
        pytest.skip("sem mongod nesta máquina: o login sem maiúsculas NÃO foi testado contra uma base")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    pasta = tempfile.mkdtemp(prefix="mongod-login-")
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


def _conta(uid, email, role="colaborador", senha=SENHA, nome="Conta", **extra):
    return {"id": uid, "email": email, "name": nome, "role": role, "employee_id": None,
            "password": server.hash_password(senha), "must_change_password": False,
            "created_at": "2026-01-01T00:00:00+00:00", **extra}


@pytest.fixture
def base(mongod_porta, monkeypatch):
    """Uma base limpa com: o admin master, o Carlos (gravado com maiúsculas e
    ainda com a temporária), a Ana (gravada em minúsculas) e um gestor. Os
    códigos enviados ficam em `base.enviados`."""
    cliente = AsyncIOMotorClient(f"mongodb://127.0.0.1:{mongod_porta}")
    _corre(cliente.drop_database(BASE_DE_TESTE))
    db = cliente[BASE_DE_TESTE]
    monkeypatch.setattr(server, "db", db)
    monkeypatch.setattr(server, "JWT_SECRET", os.environ["JWT_SECRET"])
    monkeypatch.setattr(server, "MASTER_ADMIN_EMAIL", MESTRE)
    monkeypatch.setenv("ADMIN_EMAIL", MESTRE)
    enviados = []

    async def envia(email, user_name, reset_code):
        enviados.append((email, reset_code))
        return True

    async def da_as_boas_vindas(email, employee_name, company_name, temp_password):
        return True

    monkeypatch.setattr(server, "send_password_reset_email", envia)
    monkeypatch.setattr(server, "send_welcome_email", da_as_boas_vindas)
    _corre(db.companies.insert_one({"id": "emp-1", "name": "Empresa Teste"}))
    _corre(db.users.insert_many([
        _conta("u-mestre", MESTRE, role="admin", nome="Mestre"),
        _conta("u-carlos", CARLOS, nome="Carlos", must_change_password=True),
        _conta("u-ana", "ana@example.com", nome="Ana"),
        _conta("u-gestor", "Gestor@example.com", role="gerente", nome="Gestor"),
    ]))
    limite._falhas.clear()
    db.enviados = enviados
    yield db
    limite._falhas.clear()
    cliente.close()


def _duas_parecidas(db):
    _corre(db.users.insert_many([
        _conta("u-rui-a", RUI_A, senha=SENHA_A, nome="Rui A"),
        _conta("u-rui-b", RUI_B, senha=SENHA_B, nome="Rui B"),
    ]))


def _pedido():
    return Request({"type": "http", "headers": [], "client": ("10.0.0.8", 1)})


def _login(email, senha=SENHA):
    return server.login(server.UserLogin(email=email, password=senha), _pedido())


def _esqueci(email):
    return server.forgot_password(server.ForgotPasswordRequest(email=email))


def _falha(coro):
    """(estado, detalhe) do HTTPException; 200 se passou."""
    try:
        _corre(coro)
        return 200
    except HTTPException as e:
        return e.status_code, e.detail


def _conta_de(db, uid):
    return _corre(db.users.find_one({"id": uid}, {"_id": 0}))


def _retrato(db):
    return (
        _corre(db.users.find({}, {"_id": 0}).sort("id", 1).to_list(100)),
        _corre(db.employees.find({}, {"_id": 0}).sort("id", 1).to_list(100)),
    )


INVALIDAS = (401, "Credenciais inválidas")


# ---------- entrar com outras maiúsculas ----------

def test_conta_gravada_com_maiusculas_entra_a_escrever_em_minusculas(base):
    r = _corre(_login("carlos.silva@example.com"))
    assert r["user"]["id"] == "u-carlos"
    assert r["user"]["email"] == CARLOS  # a sessão leva o email gravado
    assert r["user"]["must_change_password"] is True


def test_conta_gravada_em_minusculas_entra_a_escrever_com_maiuscula(base):
    # O teclado do telemóvel põe a primeira letra em maiúscula.
    assert _corre(_login("Ana@example.com"))["user"]["id"] == "u-ana"
    assert _corre(_login("ANA@EXAMPLE.COM"))["user"]["id"] == "u-ana"


@pytest.mark.parametrize("email", ["  carlos.silva@example.com ", "\tCarlos.Silva@example.com\n"])
def test_espacos_nas_pontas_nao_contam(base, email):
    assert _corre(_login(email))["user"]["id"] == "u-carlos"


def test_palavra_passe_errada_continua_401(base):
    for email in (CARLOS, "carlos.silva@example.com", "ninguem@example.com"):
        assert _falha(_login(email, ERRADA)) == INVALIDAS, email


def test_o_admin_master_entra_com_outras_maiusculas_e_continua_master(base):
    r = _corre(_login("Mestre@Example.com"))
    assert r["user"]["id"] == "u-mestre" and r["user"]["is_master_admin"] is True


# ---------- duas contas que só diferem nas maiúsculas ----------

def test_duas_parecidas_cada_uma_entra_com_o_seu_email_tal_e_qual(base):
    _duas_parecidas(base)
    assert _corre(_login(RUI_A, SENHA_A))["user"]["id"] == "u-rui-a"
    assert _corre(_login(RUI_B, SENHA_B))["user"]["id"] == "u-rui-b"
    # A palavra-passe de uma não abre a outra.
    assert _falha(_login(RUI_A, SENHA_B)) == INVALIDAS
    assert _falha(_login(RUI_B, SENHA_A)) == INVALIDAS
    # Noutra grafia não se escolhe nenhuma, nem com a palavra-passe certa.
    for senha in (SENHA_A, SENHA_B):
        assert _falha(_login("RUI@example.com", senha)) == INVALIDAS


# ---------- o limite de tentativas ----------

def test_o_limite_apanha_as_varias_grafias_do_mesmo_email(base):
    grafias = ["carlos.silva@example.com", CARLOS, " CARLOS.SILVA@example.com ", "carlos.silva@EXAMPLE.COM"]
    for i in range(server.LOGIN_FALHAS_POR_CONTA):
        assert _falha(_login(grafias[i % len(grafias)], ERRADA)) == INVALIDAS
    # Esgotado: em nenhuma grafia, nem com a palavra-passe certa.
    for email in grafias:
        assert _falha(_login(email))[0] == 429, email


# ---------- o «Esqueci a palavra-passe» ----------

def test_o_caso_do_carlos_repoe_a_palavra_passe_e_entra(base):
    _corre(_esqueci("carlos.silva@example.com"))
    (para, codigo), = base.enviados
    assert para == CARLOS
    assert _corre(server.verify_reset_code(server.VerifyResetCodeRequest(
        email="carlos.silva@example.com", code=codigo)))["valid"] is True
    _corre(server.reset_password(server.ResetPasswordCodeRequest(
        email="carlos.silva@example.com", code=codigo, new_password=NOVA)))
    for email in ("carlos.silva@example.com", "Carlos.silva@example.com", CARLOS):
        r = _corre(_login(email, NOVA))
        assert r["user"]["id"] == "u-carlos" and r["user"]["must_change_password"] is False


def test_esqueci_com_duas_parecidas_nao_manda_codigo_a_nenhuma_ao_acaso(base):
    _duas_parecidas(base)
    _corre(_esqueci("RUI@example.com"))
    assert base.enviados == []
    for uid in ("u-rui-a", "u-rui-b"):
        assert "reset_password_token" not in _conta_de(base, uid)
    # Com o email de uma, tal e qual, o código vai para essa e só para essa
    # (a B, que não é a primeira que a base encontra sem diferenciar maiúsculas).
    _corre(_esqueci(RUI_B))
    (para, codigo), = base.enviados
    assert para == RUI_B
    assert "reset_password_token" not in _conta_de(base, "u-rui-a")
    # Noutra grafia o código não serve: não se sabe de que conta é.
    assert _falha(server.verify_reset_code(server.VerifyResetCodeRequest(
        email="RUI@example.com", code=codigo))) == (400, "Código inválido")
    # Com o dela, repõe a palavra-passe da conta com que depois se entra.
    _corre(server.reset_password(server.ResetPasswordCodeRequest(
        email=RUI_B, code=codigo, new_password=NOVA)))
    assert _corre(_login(RUI_B, NOVA))["user"]["id"] == "u-rui-b"
    assert server.verify_password(SENHA_A, _conta_de(base, "u-rui-a")["password"])


# ---------- não se cria outra conta na mesma caixa ----------

def _cria_colaborador(email):
    return server.create_employee(server.EmployeeCreate(
        name="Carlos Costa", email=email, password=SENHA, company_id="emp-1",
        position="Motorista", contract_type="efetivo", start_date="2026-01-01"), dict(MASTER))


def _cria_admin(email):
    return server.create_admin(server.AdminCreate(
        email=email, password=SENHA, name="Gestor Novo", role="gerente"), dict(MASTER))


def _edita_admin(admin_id, email):
    return server.update_admin(admin_id, server.AdminUpdate(email=email), dict(MASTER))


@pytest.mark.parametrize("email", ["carlos.silva@example.com", "CARLOS.SILVA@example.com", "Ana@example.com"])
def test_criar_colaborador_com_email_que_so_difere_nas_maiusculas_e_recusado(base, email):
    antes = _retrato(base)
    assert _falha(_cria_colaborador(email)) == (400, "Email já registado")
    assert _retrato(base) == antes


def test_criar_colaborador_com_email_novo_continua_a_funcionar(base):
    r = _corre(_cria_colaborador("Carlos.Costa@example.com"))
    assert r.email == "Carlos.Costa@example.com"
    assert _corre(_login("carlos.costa@example.com"))["user"]["email"] == "Carlos.Costa@example.com"


@pytest.mark.parametrize("email", ["carlos.silva@example.com", "ANA@example.com", "Mestre@example.com"])
def test_criar_admin_com_email_que_so_difere_nas_maiusculas_e_recusado(base, email):
    antes = _retrato(base)
    assert _falha(_cria_admin(email)) == (400, "Email já registado")
    assert _retrato(base) == antes


def test_criar_admin_com_email_novo_continua_a_funcionar(base):
    assert _corre(_cria_admin("gestor.novo@example.com")).email == "gestor.novo@example.com"


def test_editar_admin_para_o_email_de_outra_conta_so_com_outras_maiusculas_e_recusado(base):
    antes = _retrato(base)
    for email in ("carlos.silva@example.com", "MESTRE@example.com"):
        assert _falha(_edita_admin("u-gestor", email)) == (400, "Email já registado"), email
    assert _retrato(base) == antes
    # Corrigir só as maiúsculas do próprio email não é «já registado».
    assert _corre(_edita_admin("u-gestor", "gestor@example.com")).email == "gestor@example.com"


# ---------- a equipa do Financeiro (adicionar por email) ----------

def _junta_a_equipa(email):
    return server.fin_add_team_member(server.FinTeamAdd(email=email), dict(MASTER))


def test_equipa_do_financeiro_encontra_a_conta_gravada_com_maiusculas(base):
    r = _corre(_junta_a_equipa(" carlos.silva@example.com"))
    assert (r.member_id, r.email) == ("u-carlos", CARLOS)


def test_equipa_do_financeiro_com_duas_parecidas_nao_escolhe_ao_acaso(base):
    _duas_parecidas(base)
    assert _falha(_junta_a_equipa("RUI@example.com"))[0] == 404
    assert _corre(_junta_a_equipa(RUI_B)).member_id == "u-rui-b"
