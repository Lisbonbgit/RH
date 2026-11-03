"""Corrigir o email de um colaborador em RH → Colaboradores → Editar.

O caso que o pediu: o email do motorista ficou mal escrito na ficha e o
«Esqueci a palavra-passe» mandava o código para uma caixa que não é dele. O
gestor corrige o email e, a partir daí, o colaborador entra com o novo e o
código de recuperação vai para o novo.

Contra um mongod REAL (molde: `mongo_real` em tests/test_seguranca_login.py):
o que se prova aqui é o que fica GRAVADO em `users` e em `employees` — e, nos
casos recusados, que não fica NADA, nem o nome que vinha no mesmo pedido.

O 422 (email inválido) e o 403 (quem não é gestor) passam pelo FastAPI a sério
(`TestClient`): são o validador do corpo e a guarda da rota, que uma chamada
directa à função não exercita.

O que foi mandado para a caixa errada antes da correção — o código do «Esqueci»,
a palavra-passe temporária do email de boas-vindas, uma sessão aberta com eles —
deixa de servir; e um «Esqueci» que se cruze com a correção (há 2 workers) não
deixa um código válido para trás.
"""
import asyncio
import logging
import os
import shutil
import socket
import subprocess
import tempfile
import time

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from starlette.requests import Request

os.environ.setdefault("POS_JWT_SECRET", "segredo-de-teste-pos")
os.environ.setdefault("JWT_SECRET", "segredo-de-teste")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

import limite  # noqa: E402
import server  # noqa: E402

BASE_DE_TESTE = "teste_editar_email"
ADMIN = {"user_id": "u-admin", "role": "admin", "email": "admin@example.com", "employee_id": None}
MESTRE = "mestre@example.com"
ERRADO = "ze.errado@example.com"
CERTO = "ze@example.com"
SENHA = "Certa#2026x"
CAMPOS_DO_RESET = (
    "reset_password_token", "reset_password_expires", "reset_pedido_em",
    "reset_tentativas", "reset_tentativas_desde",
)
# Uma conta gravada com maiúsculas na parte local (a criação guarda-a como foi escrita).
RUI = "Rui.Costa@example.com"
# O envio a sério das boas-vindas (a fixture troca-o por um que só apanha o que se mandou).
_BOAS_VINDAS_A_SERIO = server.send_welcome_email


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module")
def mongod_porta():
    mongod = shutil.which("mongod") or "/opt/homebrew/bin/mongod"
    if not os.path.exists(mongod):
        pytest.skip("sem mongod nesta máquina: a correção do email NÃO foi testada contra uma base")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    pasta = tempfile.mkdtemp(prefix="mongod-email-")
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


def _conta(uid, email, role="colaborador", employee_id=None, nome="Conta"):
    return {"id": uid, "email": email, "name": nome, "role": role, "employee_id": employee_id,
            "password": server.hash_password(SENHA), "must_change_password": False,
            "created_at": "2026-01-01T00:00:00+00:00"}


def _ficha(eid, uid, email, nome):
    return {"id": eid, "user_id": uid, "name": nome, "email": email, "company_id": "emp-1",
            "location_id": "loc-1", "position": "Motorista", "contract_type": "efetivo",
            "start_date": "2026-01-01", "vacation_days": 22, "created_at": "2026-01-01T00:00:00+00:00"}


@pytest.fixture
def base(mongod_porta, monkeypatch):
    """Uma base limpa com: o Zé (o email errado), a Ana e o Rui (outros
    colaboradores; o Rui gravado com maiúsculas), o admin master (com ficha, para
    o caso de alguém lhe tentar mudar o email) e o gestor que faz o pedido. Os
    códigos enviados ficam em `base.enviados`; as boas-vindas em `base.boas_vindas`."""
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

    monkeypatch.setattr(server, "send_password_reset_email", envia)
    boas_vindas = []

    async def da_as_boas_vindas(email, employee_name, company_name, temp_password):
        boas_vindas.append((email, temp_password))
        return True

    monkeypatch.setattr(server, "send_welcome_email", da_as_boas_vindas)
    _corre(db.companies.insert_one({"id": "emp-1", "name": "Empresa Teste"}))
    _corre(db.locations.insert_one({"id": "loc-1", "name": "Loja Teste", "company_id": "emp-1"}))
    _corre(db.users.insert_many([
        _conta("u-admin", "admin@example.com", role="admin", nome="Gestor"),
        _conta("u-ze", ERRADO, employee_id="e-ze", nome="Zé"),
        _conta("u-ana", "ana@example.com", employee_id="e-ana", nome="Ana"),
        _conta("u-rui", RUI, employee_id="e-rui", nome="Rui"),
        _conta("u-mestre", MESTRE, role="admin", employee_id="e-mestre", nome="Mestre"),
    ]))
    _corre(db.employees.insert_many([
        _ficha("e-ze", "u-ze", ERRADO, "Zé"),
        _ficha("e-ana", "u-ana", "ana@example.com", "Ana"),
        _ficha("e-rui", "u-rui", RUI, "Rui"),
        _ficha("e-mestre", "u-mestre", MESTRE, "Mestre"),
    ]))
    limite._falhas.clear()
    db.enviados = enviados
    db.boas_vindas = boas_vindas
    yield db
    limite._falhas.clear()
    cliente.close()


def _put(employee_id, **campos):
    return server.update_employee(employee_id, server.EmployeeUpdate(**campos), dict(ADMIN))


def _estado(coro):
    try:
        _corre(coro)
        return 200
    except HTTPException as e:
        return e.status_code


def _retrato(db):
    """Tudo o que está nas contas e nas fichas, para comparar antes/depois."""
    return (
        _corre(db.users.find({}, {"_id": 0}).sort("id", 1).to_list(100)),
        _corre(db.employees.find({}, {"_id": 0}).sort("id", 1).to_list(100)),
    )


def _conta_de(db, uid):
    return _corre(db.users.find_one({"id": uid}, {"_id": 0}))


def _ficha_de(db, eid):
    return _corre(db.employees.find_one({"id": eid}, {"_id": 0}))


def _pedido():
    return Request({"type": "http", "headers": [], "client": ("10.0.0.7", 1)})


def _login(email):
    return server.login(server.UserLogin(email=email, password=SENHA), _pedido())


def _esqueci(email):
    return server.forgot_password(server.ForgotPasswordRequest(email=email))


def _token_de_antes(monkeypatch, uid, email):
    """Um token emitido uns segundos antes (o `iat` tem resolução de segundos)."""
    agora = server._agora_s()
    with monkeypatch.context() as m:
        m.setattr(server, "_agora_s", lambda: agora - 5)
        token = server.create_token(uid, email, "colaborador", "e-" + uid[2:])
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _sessao(cred):
    """200 se o token ainda vale; senão (estado, detalhe)."""
    try:
        _corre(server.get_current_user(cred))
        return 200
    except HTTPException as e:
        return e.status_code, e.detail


# ---------- a correção ----------

def test_corrigir_o_email_grava_na_conta_e_na_ficha(base):
    antes = _conta_de(base, "u-ze")
    r = _corre(_put("e-ze", email=CERTO))
    assert r.email == CERTO
    depois = _conta_de(base, "u-ze")
    assert depois["email"] == CERTO
    assert _ficha_de(base, "e-ze")["email"] == CERTO
    # O resto da conta fica como estava (a palavra-passe, o papel, o nome); só
    # se marca o momento, para as sessões abertas antes terminarem.
    assert {k: v for k, v in depois.items() if k not in ("email", "password_mudada_em")} == \
        {k: v for k, v in antes.items() if k != "email"}
    assert "password_mudada_em" not in antes and depois["password_mudada_em"]
    # As outras contas não mexem.
    assert _conta_de(base, "u-ana")["email"] == "ana@example.com"


def test_depois_da_correcao_entra_com_o_email_novo_e_ja_nao_com_o_antigo(base):
    _corre(_put("e-ze", email=CERTO))
    assert _corre(_login(CERTO))["user"]["email"] == CERTO
    assert _estado(_login(ERRADO)) == 401
    # Já tinha trocado a temporária: a palavra-passe é dele e fica; não há boas-vindas.
    assert base.boas_vindas == []


def test_o_codigo_de_recuperacao_vai_para_o_email_novo(base):
    _corre(_put("e-ze", email=CERTO))
    _corre(_esqueci(ERRADO))
    assert base.enviados == []  # o email errado já não é de conta nenhuma
    assert _corre(server._utilizador_por_email(ERRADO)) is None
    _corre(_esqueci(CERTO))
    assert [e for e, _ in base.enviados] == [CERTO]
    assert _corre(server._utilizador_por_email(CERTO))["id"] == "u-ze"


def test_o_codigo_mandado_para_o_email_errado_deixa_de_servir(base):
    # Antes da correção, alguém pede o código: vai para a caixa errada (de um estranho).
    _corre(_esqueci(ERRADO))
    (_, codigo_errado), = base.enviados
    _corre(base.users.update_one({"id": "u-ze"}, {"$set": {"reset_tentativas": 3}}))
    _corre(_put("e-ze", email=CERTO))
    conta = _conta_de(base, "u-ze")
    for campo in CAMPOS_DO_RESET:
        assert campo not in conta, campo
    with pytest.raises(HTTPException) as e:
        _corre(server.verify_reset_code(server.VerifyResetCodeRequest(email=CERTO, code=codigo_errado)))
    assert e.value.status_code == 400
    # E o colaborador pede logo um código novo, sem esperar o minuto do pedido anterior.
    _corre(_esqueci(CERTO))
    assert [e for e, _ in base.enviados] == [ERRADO, CERTO]


def test_corrigir_o_email_termina_as_sessoes_abertas(base, monkeypatch):
    # Quem entrou pela caixa errada (com um código do «Esqueci», ou com a
    # temporária das boas-vindas) não fica lá dentro depois da correção.
    antes = _token_de_antes(monkeypatch, "u-ze", ERRADO)
    assert _sessao(antes) == 200
    _corre(_put("e-ze", email=CERTO))
    assert _sessao(antes) == (401, "Sessão terminada")
    # Quem entra depois, com o email novo, fica.
    novo = _corre(_login(CERTO))["token"]
    assert _sessao(HTTPAuthorizationCredentials(scheme="Bearer", credentials=novo)) == 200


def test_a_temporaria_mandada_para_o_email_errado_deixa_de_servir(base):
    # O Zé nunca entrou: a palavra-passe ainda é a temporária, e o email de
    # boas-vindas (com ela lá escrita) foi para a caixa errada.
    _corre(base.users.update_one({"id": "u-ze"}, {"$set": {"must_change_password": True}}))
    _corre(_put("e-ze", email=CERTO))
    assert _estado(_login(CERTO)) == 401  # a temporária que foi para a caixa errada
    # Uma temporária NOVA vai para o email certo, e com ela entra (e tem de a trocar).
    (para, nova), = base.boas_vindas
    assert para == CERTO and nova != SENHA and len(nova) >= server.MIN_PASSWORD_LENGTH
    r = _corre(server.login(server.UserLogin(email=CERTO, password=nova), _pedido()))
    assert r["user"]["email"] == CERTO and r["user"]["must_change_password"] is True
    assert _conta_de(base, "u-ze")["must_change_password"] is True


def test_um_codigo_pedido_durante_a_correcao_nao_fica_valido_nem_vai_para_o_errado(base, monkeypatch):
    # O «Esqueci» lê a conta pelo email errado e, antes de gravar o código, o
    # gestor corrige o email noutro worker: os dois pedidos cruzam-se.
    le_a_conta = server._utilizador_por_email

    async def le_e_o_gestor_corrige(email):
        conta = await le_a_conta(email)
        await _put("e-ze", email=CERTO)
        return conta

    monkeypatch.setattr(server, "_utilizador_por_email", le_e_o_gestor_corrige)
    _corre(_esqueci(ERRADO))
    assert base.enviados == []
    conta = _conta_de(base, "u-ze")
    assert conta["email"] == CERTO
    for campo in CAMPOS_DO_RESET:
        assert campo not in conta, campo
    # E o Zé pede logo o seu, sem esperar o minuto de um pedido que não foi dele.
    monkeypatch.setattr(server, "_utilizador_por_email", le_a_conta)
    _corre(_esqueci(CERTO))
    assert [e for e, _ in base.enviados] == [CERTO]


def test_um_codigo_usado_durante_a_correcao_nao_muda_a_palavra_passe(base, monkeypatch):
    # Quem tem o código da caixa errada usa-o no instante em que o gestor corrige o email.
    _corre(_esqueci(ERRADO))
    (_, codigo), = base.enviados
    expirou = server._codigo_expirou

    async def confere_e_o_gestor_corrige(user):
        await _put("e-ze", email=CERTO)
        return await expirou(user)

    monkeypatch.setattr(server, "_codigo_expirou", confere_e_o_gestor_corrige)
    assert _estado(server.reset_password(server.ResetPasswordCodeRequest(
        email=ERRADO, code=codigo, new_password="Estranho#2026"))) == 400
    conta = _conta_de(base, "u-ze")
    assert conta["email"] == CERTO
    assert server.verify_password(SENHA, conta["password"])  # a palavra-passe é a do Zé


# ---------- o que é recusado (e não deixa nada meio escrito) ----------

@pytest.mark.parametrize("email", ["ana@example.com", "ANA@Example.com", "  Ana@EXAMPLE.com "])
def test_email_de_outra_conta_e_recusado_e_nada_muda(base, email):
    antes = _retrato(base)
    with pytest.raises(HTTPException) as e:
        _corre(_put("e-ze", name="Zé Novo", email=email))
    assert (e.value.status_code, e.value.detail) == (400, "Email já registado")
    assert _retrato(base) == antes


def test_email_de_conta_gravada_com_maiusculas_tambem_e_recusado(base):
    # A conta do Rui está gravada «Rui.Costa@…»; o «Esqueci» não diferencia
    # maiúsculas, por isso «rui.costa@…» noutra conta confundia as duas.
    antes = _retrato(base)
    with pytest.raises(HTTPException) as e:
        _corre(_put("e-ze", name="Zé Novo", email=RUI.lower()))
    assert (e.value.status_code, e.value.detail) == (400, "Email já registado")
    assert _retrato(base) == antes


@pytest.mark.parametrize("email", [MESTRE, "MESTRE@Example.com"])
def test_ninguem_fica_com_o_email_do_admin_master(base, email):
    # Sem a conta dele na base, para provar a guarda própria e não a dos repetidos.
    _corre(base.users.delete_one({"id": "u-mestre"}))
    antes = _retrato(base)
    with pytest.raises(HTTPException) as e:
        _corre(_put("e-ze", name="Zé Novo", email=email))
    assert e.value.status_code == 400
    assert _retrato(base) == antes


def test_a_conta_do_admin_master_nao_muda_de_email_pela_ficha(base):
    antes = _retrato(base)
    with pytest.raises(HTTPException) as e:
        _corre(_put("e-mestre", name="Mestre Novo", email="outro@example.com"))
    assert e.value.status_code == 400
    assert _retrato(base) == antes


def test_colaborador_que_nao_existe_da_404_e_nada_se_escreve(base):
    antes = _retrato(base)
    for campos in ({"name": "Fantasma", "email": "novo@example.com"}, {"name": "Fantasma"}):
        with pytest.raises(HTTPException) as e:
            _corre(_put("nao-existe", **campos))
        assert e.value.status_code == 404
    assert _retrato(base) == antes


# ---------- o mesmo email, e o pedido de sempre ----------

def test_o_mesmo_email_com_espacos_nao_e_mudanca(base):
    _corre(base.users.update_one({"id": "u-ze"}, {"$set": {"reset_password_token": "pendente"}}))
    antes = _retrato(base)
    _corre(_put("e-ze", email="  ze.errado@Example.com "))
    assert _retrato(base) == antes
    r = _corre(_put("e-ze", email=" ze.errado@example.com", position="Motorista-chefe"))
    assert r.email == ERRADO and r.position == "Motorista-chefe"
    conta = _conta_de(base, "u-ze")
    assert conta["email"] == ERRADO
    assert conta["reset_password_token"] == "pendente"  # não houve mudança: o código fica
    assert _ficha_de(base, "e-ze")["email"] == ERRADO


def test_corrigir_so_as_maiusculas_grava_porque_o_login_compara_tal_e_qual(base, monkeypatch):
    # Gravado «Ze.Errado@…» (a criação guarda a parte local como foi escrita); o
    # telemóvel escreve tudo em minúsculas e o login dá 401.
    misto = "Ze.Errado@example.com"
    _corre(base.users.update_one({"id": "u-ze"}, {"$set": {
        "email": misto, "reset_password_token": "pendente", "must_change_password": True}}))
    _corre(base.employees.update_one({"id": "e-ze"}, {"$set": {"email": misto}}))
    assert _estado(_login(ERRADO)) == 401
    sessao = _token_de_antes(monkeypatch, "u-ze", misto)
    r = _corre(_put("e-ze", email=ERRADO))
    assert r.email == ERRADO
    assert _ficha_de(base, "e-ze")["email"] == ERRADO
    assert _corre(_login(ERRADO))["user"]["email"] == ERRADO
    # É a MESMA caixa de correio: o que lá foi parar é do Zé e continua a servir.
    conta = _conta_de(base, "u-ze")
    assert conta["reset_password_token"] == "pendente"
    assert server.verify_password(SENHA, conta["password"]) and base.boas_vindas == []
    assert _sessao(sessao) == 200


def test_a_ficha_que_ficou_para_tras_alinha_com_a_conta(base, monkeypatch):
    # O email mudou só na conta (o PUT /admins mexe só em `users`): a ficha
    # mostra o antigo, e é para ela que vai o email da decisão das férias.
    _corre(base.users.update_one({"id": "u-ze"}, {"$set": {
        "email": CERTO, "reset_password_token": "pendente"}}))
    conta_antes = _conta_de(base, "u-ze")
    sessao = _token_de_antes(monkeypatch, "u-ze", CERTO)
    r = _corre(_put("e-ze", email=CERTO))
    assert r.email == CERTO
    assert _ficha_de(base, "e-ze")["email"] == CERTO
    # A conta já estava certa: não se lhe mexe (nem no código, nem nas sessões).
    assert _conta_de(base, "u-ze") == conta_antes
    assert _sessao(sessao) == 200


class _ColecaoQueFalha:
    def __init__(self, colecao):
        self._colecao = colecao

    def __getattr__(self, nome):
        return getattr(self._colecao, nome)

    async def update_one(self, *args, **kwargs):
        raise RuntimeError("o Mongo foi abaixo a meio")


class _BaseQueFalhaEm:
    """A base, mas a escrita numa colecção rebenta (timeout, worker reiniciado)."""

    def __init__(self, db, colecao):
        self._db, self._colecao = db, colecao

    def __getattr__(self, nome):
        colecao = getattr(self._db, nome)
        return _ColecaoQueFalha(colecao) if nome == self._colecao else colecao


def test_uma_escrita_que_para_a_meio_nao_deixa_a_ficha_a_mostrar_o_email_novo(base, monkeypatch):
    # Se a conta (o login) não foi gravada, a ficha NÃO pode mostrar já o email
    # novo: o ecrã só reenvia o email quando difere da ficha, e o gestor ficava
    # com «sucesso» à vista e a conta presa no email errado.
    monkeypatch.setattr(server, "db", _BaseQueFalhaEm(base, "users"))
    with pytest.raises(RuntimeError):
        _corre(_put("e-ze", email=CERTO))
    assert _ficha_de(base, "e-ze")["email"] == ERRADO
    # E se for a ficha a falhar depois da conta, o gestor volta a mandar o email
    # (a ficha ainda mostra o antigo) e o mesmo pedido completa a correção.
    monkeypatch.setattr(server, "db", _BaseQueFalhaEm(base, "employees"))
    with pytest.raises(RuntimeError):
        _corre(_put("e-ze", email=CERTO))
    assert (_conta_de(base, "u-ze")["email"], _ficha_de(base, "e-ze")["email"]) == (CERTO, ERRADO)
    monkeypatch.setattr(server, "db", base)
    _corre(_put("e-ze", email=CERTO))
    assert (_conta_de(base, "u-ze")["email"], _ficha_de(base, "e-ze")["email"]) == (CERTO, CERTO)


def test_um_put_sem_email_continua_como_antes(base, monkeypatch):
    _corre(base.users.update_one({"id": "u-ze"}, {"$set": {"reset_password_token": "pendente"}}))
    sessao = _token_de_antes(monkeypatch, "u-ze", ERRADO)
    r = _corre(_put("e-ze", name="Zé Silva", phone="910000000"))
    assert _sessao(sessao) == 200  # mudar o nome não deita ninguém fora
    assert (r.name, r.email, r.phone) == ("Zé Silva", ERRADO, "910000000")
    conta = _conta_de(base, "u-ze")
    assert (conta["name"], conta["email"], conta["reset_password_token"]) == ("Zé Silva", ERRADO, "pendente")
    ficha = _ficha_de(base, "e-ze")
    assert (ficha["name"], ficha["email"], ficha["phone"]) == ("Zé Silva", ERRADO, "910000000")
    with pytest.raises(HTTPException) as e:
        _corre(_put("e-ze"))
    assert e.value.status_code == 400  # «Nenhum dado para atualizar», como sempre


class _ResendFalso:
    """O `resend` do servidor, sem rede: só guarda para quem se mandou."""

    def __init__(self):
        self.para = []
        self.Emails = self

    def send(self, params):
        self.para.extend(params["to"])
        return {"id": "teste"}


def test_o_email_nao_fica_nos_logs(base, caplog, monkeypatch):
    # Com o envio das boas-vindas a sério (o Zé ainda tem a temporária), só sem rede.
    resend = _ResendFalso()
    monkeypatch.setattr(server, "send_welcome_email", _BOAS_VINDAS_A_SERIO)
    monkeypatch.setattr(server, "RESEND_AVAILABLE", True)
    monkeypatch.setattr(server, "RESEND_API_KEY", "re_teste")
    monkeypatch.setattr(server, "resend", resend, raising=False)
    _corre(base.users.update_one({"id": "u-ze"}, {"$set": {"must_change_password": True}}))
    caplog.set_level(logging.DEBUG)
    _corre(_put("e-ze", email=CERTO))
    assert resend.para == [CERTO]
    assert _estado(_put("e-ze", email="ana@example.com")) == 400
    assert _estado(_put("e-ze", email=MESTRE)) == 400
    for email in (ERRADO, CERTO, "ana@example.com", MESTRE):
        assert email not in caplog.text.lower()


# ---------- pelo FastAPI a sério: o corpo e a guarda ----------

def _cliente(**substitutos):
    app = FastAPI()
    app.include_router(server.api_router)
    for dependencia, valor in substitutos.items():
        app.dependency_overrides[getattr(server, dependencia)] = lambda valor=valor: dict(valor)
    return TestClient(app)


def test_email_invalido_da_422_e_nada_muda(base):
    antes = _retrato(base)
    cliente = _cliente(admin_required=ADMIN)
    for email in ("nao-e-um-email", "ze@", ""):
        r = cliente.put("/api/employees/e-ze", json={"name": "Zé Novo", "email": email})
        assert r.status_code == 422, email
    assert _retrato(base) == antes


def test_quem_nao_e_gestor_leva_403_e_nada_muda(base):
    antes = _retrato(base)
    colaborador = {"user_id": "u-ana", "role": "colaborador", "email": "ana@example.com", "employee_id": "e-ana"}
    r = _cliente(get_current_user=colaborador).put("/api/employees/e-ze", json={"email": "ana2@example.com"})
    assert r.status_code == 403
    assert _retrato(base) == antes
    rota, = [r for r in server.api_router.routes
             if r.path == "/api/employees/{employee_id}" and "PUT" in r.methods]
    assert server.admin_required in [d.call for d in rota.dependant.dependencies]
