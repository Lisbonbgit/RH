"""Autenticação dos membros do CRM (crm/auth.py), sobre a sessão do portal.

O CRM não tem sessões próprias: assenta em `faturacao.auth.utilizador_atual`
(papel e email lidos da BASE a cada pedido, conta apagada → 401, sessão
anterior à troca de palavra-passe → 401) e só acrescenta a pergunta "é membro
do CRM, e com que perfil?" (desenho §4.2; dossiê §4; plano T1.4).

- Admin master = a conta cujo email (o da base) é igual a `ADMIN_EMAIL`, com o
  mesmo valor por omissão do server.py. É sempre `admin` do CRM, sem linha em
  `crm_membros` — nem se chega a ler essa coleção.
- Os outros são membros por uma linha `{user_id, perfil}`; uma linha com um
  perfil que não é dos três conta como não-membro (fechado por omissão).

As corrotinas correm com `correr` (tests/crm/duplos.py), nunca com o
asyncio.run (correções do plano, linha do §10).
"""
import inspect
import re
import time
from pathlib import Path

import jwt
import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

import crm.db
import faturacao.auth
from crm import auth
from crm.auth import (
    ESCRITORIO,
    SO_ADMIN,
    email_admin_master,
    estado_crm,
    exigir_perfil,
    membro_crm_atual,
)

from .duplos import BaseFalsa, correr

ADMIN_LOCAL = "admin.local@example.com"
NAO_MEMBRO = {"membro": False, "perfil": None, "admin_master": False}
SEM_ACESSO = {"codigo": "sem_acesso_crm", "mensagem": "Sem acesso ao CRM."}
SEM_PERMISSAO = {"codigo": "sem_permissao", "mensagem": "Sem permissão para esta ação."}
SERVER_PY = Path(__file__).resolve().parents[2] / "server.py"


def _base(membros=(), users=()):
    return BaseFalsa({"crm_membros": list(membros), "users": list(users)})


@pytest.fixture
def com_base(monkeypatch):
    """Troca a base do CRM (pelo único ponto, crm.db.obter_db) e devolve-a."""

    def _trocar(base):
        monkeypatch.setattr(crm.db, "obter_db", lambda: base)
        return base

    return _trocar


# --- Admin master: o email do ADMIN_EMAIL, como no server.py -------------------


def test_sem_admin_email_no_ambiente_o_admin_master_e_o_do_server(monkeypatch):
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    assert auth.ADMIN_EMAIL_POR_OMISSAO == "geral@olacai.com"
    assert email_admin_master() == "geral@olacai.com"


def test_o_valor_por_omissao_e_o_mesmo_do_server_py():
    """Trava a paridade lendo o server.py como texto (importá-lo abria a base):
    se o Matheus mudar o valor por omissão lá, este teste avisa."""
    texto = SERVER_PY.read_text(encoding="utf-8")
    achado = re.findall(r"""os\.environ\.get\(\s*['"]ADMIN_EMAIL['"]\s*,\s*['"]([^'"]+)['"]\s*\)""", texto)
    assert achado == [auth.ADMIN_EMAIL_POR_OMISSAO]


def test_o_admin_email_le_se_do_ambiente_a_cada_chamada(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    assert email_admin_master() == ADMIN_LOCAL
    monkeypatch.setenv("ADMIN_EMAIL", "outro@example.com")
    assert email_admin_master() == "outro@example.com"


# --- estado_crm -----------------------------------------------------------------


def test_o_admin_master_e_admin_do_crm_sem_ler_os_membros(monkeypatch, com_base):
    """Mesmo com uma linha dele (aqui com outro perfil), a linha não conta: o
    admin master é admin pelo email e a coleção nem é lida."""
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    base = com_base(_base([{"id": "m1", "user_id": "u1", "perfil": "motorista"}]))
    estado = correr(estado_crm({"user_id": "u1", "email": ADMIN_LOCAL}))
    assert estado == {"membro": True, "perfil": "admin", "admin_master": True}
    assert base.crm_membros.registo == []


def test_sem_admin_email_no_ambiente_o_admin_master_e_geral(monkeypatch, com_base):
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    base = com_base(_base())
    estado = correr(estado_crm({"user_id": "u1", "email": "geral@olacai.com"}))
    assert estado == {"membro": True, "perfil": "admin", "admin_master": True}
    assert base.crm_membros.registo == []


@pytest.mark.parametrize(
    "email",
    ["ADMIN.LOCAL@example.com", " admin.local@example.com", "admin.local@example.com ", "admin.local@example"],
    ids=["maiusculas", "espaco antes", "espaco depois", "outro email"],
)
def test_o_email_do_admin_master_compara_se_tal_e_qual(monkeypatch, com_base, email):
    """Paridade com o server.py (`user["email"] == MASTER_ADMIN_EMAIL`): o
    portal compara tal e qual, e o CRM não pode dar admin a quem o portal não
    reconhece como admin master."""
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    com_base(_base())
    assert correr(estado_crm({"user_id": "u9", "email": email})) == NAO_MEMBRO


@pytest.mark.parametrize("email", ["", None], ids=["vazio", "sem email"])
def test_admin_email_vazio_nao_faz_de_ninguem_admin_master(monkeypatch, com_base, email):
    """Um ADMIN_EMAIL vazio por engano não pode transformar em admin uma conta
    sem email."""
    monkeypatch.setenv("ADMIN_EMAIL", "")
    com_base(_base())
    utilizador = {"user_id": "u9"} if email is None else {"user_id": "u9", "email": email}
    assert correr(estado_crm(utilizador)) == NAO_MEMBRO


@pytest.mark.parametrize("perfil", ["admin", "utilizador", "motorista"])
def test_um_membro_tem_o_perfil_da_sua_linha(monkeypatch, com_base, perfil):
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    com_base(_base([{"id": "m2", "user_id": "u2", "perfil": perfil}]))
    estado = correr(estado_crm({"user_id": "u2", "email": "u2@example.com"}))
    assert estado == {"membro": True, "perfil": perfil, "admin_master": False}


def test_le_so_o_perfil_da_linha_do_proprio(monkeypatch, com_base):
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    base = com_base(
        _base(
            [
                {"id": "m1", "user_id": "u1", "perfil": "admin"},
                {"id": "m2", "user_id": "u2", "perfil": "utilizador"},
            ]
        )
    )
    assert correr(estado_crm({"user_id": "u2", "email": "u2@example.com"})) == {
        "membro": True,
        "perfil": "utilizador",
        "admin_master": False,
    }
    assert base.crm_membros.registo == [("find_one", {"user_id": "u2"}, {"_id": 0, "perfil": 1})]


def test_sem_linha_nao_e_membro(monkeypatch, com_base):
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    com_base(_base([{"id": "m1", "user_id": "u1", "perfil": "admin"}]))
    assert correr(estado_crm({"user_id": "u3", "email": "u3@example.com"})) == NAO_MEMBRO


@pytest.mark.parametrize(
    "linha",
    [
        {"perfil": "Admin"},
        {"perfil": "gestor"},
        {"perfil": ""},
        {"perfil": None},
        {"perfil": 1},
        {"perfil": ["admin"]},
        {},
    ],
    ids=["maiuscula", "papel do portal", "vazio", "null", "numero", "lista", "sem perfil"],
)
def test_uma_linha_com_perfil_desconhecido_conta_como_nao_membro(monkeypatch, com_base, linha):
    """Fechado por omissão: um perfil estragado na base nunca dá acesso."""
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    com_base(_base([{"id": "m4", "user_id": "u4", **linha}]))
    assert correr(estado_crm({"user_id": "u4", "email": "u4@example.com"})) == NAO_MEMBRO


@pytest.mark.parametrize(
    "utilizador",
    [{"email": "x@example.com"}, {"user_id": None}, {"user_id": ""}, {"user_id": 7}],
    ids=["sem user_id", "user_id null", "user_id vazio", "user_id numero"],
)
def test_sem_user_id_de_texto_nao_e_membro_nem_se_procura(monkeypatch, com_base, utilizador):
    """`{"user_id": None}` no Mongo apanhava linhas SEM user_id: nem se pergunta."""
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    base = com_base(_base([{"id": "m5", "perfil": "admin"}]))
    assert correr(estado_crm(utilizador)) == NAO_MEMBRO
    assert base.crm_membros.registo == []


def test_cada_estado_e_um_dicionario_novo(monkeypatch, com_base):
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    com_base(_base())
    primeiro = correr(estado_crm({"user_id": "u3", "email": "u3@example.com"}))
    primeiro["membro"] = True
    assert correr(estado_crm({"user_id": "u3", "email": "u3@example.com"})) == NAO_MEMBRO


# --- membro_crm_atual -----------------------------------------------------------


def test_membro_crm_atual_depende_da_sessao_do_portal():
    parametros = list(inspect.signature(membro_crm_atual).parameters.values())
    assert len(parametros) == 1
    assert parametros[0].default.dependency is faturacao.auth.utilizador_atual


def test_um_nao_membro_recebe_403_sem_acesso_crm(monkeypatch, com_base):
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    com_base(_base())
    with pytest.raises(HTTPException) as e:
        correr(membro_crm_atual({"user_id": "u3", "email": "u3@example.com", "role": "gerente"}))
    assert e.value.status_code == 403
    assert e.value.detail == SEM_ACESSO


def test_um_membro_recebe_o_utilizador_com_o_perfil_do_crm(monkeypatch, com_base):
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    com_base(_base([{"id": "m2", "user_id": "u2", "perfil": "utilizador"}]))
    utilizador = {"user_id": "u2", "email": "u2@example.com", "role": "colaborador"}
    membro = correr(membro_crm_atual(utilizador))
    assert membro == {**utilizador, "crm_perfil": "utilizador", "crm_admin_master": False}
    assert "crm_perfil" not in utilizador  # o dicionário da sessão não é mexido


def test_o_admin_master_recebe_perfil_admin(monkeypatch, com_base):
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    com_base(_base())
    membro = correr(membro_crm_atual({"user_id": "u1", "email": ADMIN_LOCAL, "role": "admin"}))
    assert membro["crm_perfil"] == "admin"
    assert membro["crm_admin_master"] is True


# --- exigir_perfil, SO_ADMIN e ESCRITORIO --------------------------------------


def _membro(perfil, admin_master=False):
    return {"user_id": "u", "email": "u@example.com", "crm_perfil": perfil, "crm_admin_master": admin_master}


def test_os_perfis_de_rota_da_f1_e_f2():
    assert SO_ADMIN.perfis_crm == frozenset({"admin"})
    assert ESCRITORIO.perfis_crm == frozenset({"admin", "utilizador"})


def test_exigir_perfil_depende_de_membro_crm_atual():
    for guarda in (SO_ADMIN, ESCRITORIO, exigir_perfil("motorista")):
        parametros = list(inspect.signature(guarda).parameters.values())
        assert len(parametros) == 1
        assert parametros[0].default.dependency is membro_crm_atual
        assert inspect.iscoroutinefunction(guarda)


def test_so_admin_recusa_o_perfil_utilizador():
    with pytest.raises(HTTPException) as e:
        correr(SO_ADMIN(_membro("utilizador")))
    assert e.value.status_code == 403
    assert e.value.detail == SEM_PERMISSAO


def test_so_admin_deixa_passar_o_admin_e_devolve_o_membro():
    membro = _membro("admin")
    assert correr(SO_ADMIN(membro)) == membro


@pytest.mark.parametrize("perfil", ["admin", "utilizador"])
def test_escritorio_deixa_passar_admin_e_utilizador(perfil):
    assert correr(ESCRITORIO(_membro(perfil)))["crm_perfil"] == perfil


def test_o_motorista_nao_entra_no_escritorio_na_f1_f2():
    with pytest.raises(HTTPException) as e:
        correr(ESCRITORIO(_membro("motorista")))
    assert e.value.status_code == 403
    assert e.value.detail == SEM_PERMISSAO


def test_os_perfis_repetidos_contam_uma_vez():
    assert exigir_perfil("admin", "admin").perfis_crm == frozenset({"admin"})


@pytest.mark.parametrize(
    "perfis",
    [(), ("Admin",), ("gestor",), ("admin", "colaborador"), (None,)],
    ids=["nenhum", "maiuscula", "papel do portal", "um bom e um mau", "null"],
)
def test_exigir_perfil_recusa_perfis_que_nao_existem(perfis):
    """Erro de programação, apanhado ao importar o módulo das rotas — nunca
    uma rota que, por um erro de escrita, não deixasse entrar ninguém."""
    with pytest.raises(ValueError):
        exigir_perfil(*perfis)


# --- De ponta a ponta: sessão do portal → membro → perfil ---------------------

SEGREDO = "segredo-de-teste-crm-auth"
AGORA = int(time.time())

USERS = [
    {"id": "u-admin", "email": ADMIN_LOCAL, "role": "admin"},
    {"id": "u-esc", "email": "escritorio@example.com", "role": "gerente"},
    {"id": "u-ger", "email": "gestor@example.com", "role": "gerente"},
    {"id": "u-col", "email": "colaborador@example.com", "role": "colaborador"},
    {"id": "u-mot", "email": "motorista@example.com", "role": "colaborador"},
    {"id": "u-pw", "email": "trocou@example.com", "role": "colaborador", "password_mudada_em": AGORA - 60},
]
MEMBROS = [
    {"id": "m-esc", "user_id": "u-esc", "perfil": "utilizador"},
    {"id": "m-col", "user_id": "u-col", "perfil": "utilizador"},
    {"id": "m-mot", "user_id": "u-mot", "perfil": "motorista"},
    {"id": "m-pw", "user_id": "u-pw", "perfil": "admin"},
]


def _token(user_id, email="qualquer@example.com", role="colaborador", iat=AGORA):
    dados = {"user_id": user_id, "email": email, "role": role, "iat": iat, "exp": AGORA + 3600}
    return jwt.encode(dados, SEGREDO, algorithm="HS256")


def _cabecalho(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def portal(monkeypatch):
    """Uma app com duas rotas de teste (ESCRITORIO e SO_ADMIN), a sessão do
    portal real (faturacao.auth) e a mesma base falsa para o portal e o CRM."""
    monkeypatch.setenv("JWT_SECRET", SEGREDO)
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    base = _base(MEMBROS, USERS)
    monkeypatch.setattr(faturacao.auth, "obter_db", lambda: base)
    monkeypatch.setattr(crm.db, "obter_db", lambda: base)

    app = FastAPI()

    @app.get("/escritorio")
    async def escritorio(membro: dict = Depends(ESCRITORIO)):
        return {"perfil": membro["crm_perfil"], "admin_master": membro["crm_admin_master"]}

    @app.get("/admin")
    async def so_admin(membro: dict = Depends(SO_ADMIN)):
        return {"perfil": membro["crm_perfil"], "admin_master": membro["crm_admin_master"]}

    cliente = TestClient(app)
    cliente.base = base
    return cliente


def test_sem_cabecalho_da_o_403_herdado(portal):
    r = portal.get("/escritorio")
    assert r.status_code == 403
    assert r.json() == {"detail": "Not authenticated"}


def test_token_invalido_da_o_401_herdado(portal):
    r = portal.get("/escritorio", headers=_cabecalho("isto-nao-e-um-token"))
    assert r.status_code == 401
    assert r.json() == {"detail": "Sessão inválida ou expirada"}


def test_conta_apagada_da_401_sessao_terminada(portal):
    r = portal.get("/escritorio", headers=_cabecalho(_token("u-apagada")))
    assert r.status_code == 401
    assert r.json() == {"detail": "Sessão terminada"}
    assert portal.base.crm_membros.registo == []


def test_sessao_anterior_a_troca_de_palavra_passe_da_401(portal):
    r = portal.get("/admin", headers=_cabecalho(_token("u-pw", iat=AGORA - 3600)))
    assert r.status_code == 401
    assert r.json() == {"detail": "Sessão terminada"}


def test_colaborador_membro_utilizador_entra_o_papel_do_portal_nao_interessa(portal):
    r = portal.get("/escritorio", headers=_cabecalho(_token("u-col", role="colaborador")))
    assert r.status_code == 200
    assert r.json() == {"perfil": "utilizador", "admin_master": False}


def test_gestor_do_portal_sem_linha_nao_entra(portal):
    r = portal.get("/escritorio", headers=_cabecalho(_token("u-ger", role="gerente")))
    assert r.status_code == 403
    assert r.json() == {"detail": SEM_ACESSO}


def test_o_motorista_recebe_sem_permissao_no_escritorio(portal):
    r = portal.get("/escritorio", headers=_cabecalho(_token("u-mot")))
    assert r.status_code == 403
    assert r.json() == {"detail": SEM_PERMISSAO}


def test_o_utilizador_recebe_sem_permissao_nas_rotas_de_admin(portal):
    r = portal.get("/admin", headers=_cabecalho(_token("u-esc", role="gerente")))
    assert r.status_code == 403
    assert r.json() == {"detail": SEM_PERMISSAO}


def test_o_admin_master_entra_nas_rotas_de_admin_sem_linha(portal):
    r = portal.get("/admin", headers=_cabecalho(_token("u-admin", email=ADMIN_LOCAL, role="admin")))
    assert r.status_code == 200
    assert r.json() == {"perfil": "admin", "admin_master": True}
    assert portal.base.crm_membros.registo == []


def test_o_admin_master_vem_do_email_da_base_e_nao_do_token(portal):
    """Um token com o email do admin master não chega: conta o email da conta
    na base (faturacao.auth.utilizador_atual substitui-o)."""
    r = portal.get("/admin", headers=_cabecalho(_token("u-ger", email=ADMIN_LOCAL, role="admin")))
    assert r.status_code == 403
    assert r.json() == {"detail": SEM_ACESSO}


def test_retirar_o_membro_corta_o_acesso_no_pedido_seguinte(portal):
    cabecalho = _cabecalho(_token("u-col"))
    assert portal.get("/escritorio", headers=cabecalho).status_code == 200
    portal.base.crm_membros.docs[:] = [d for d in portal.base.crm_membros.docs if d["user_id"] != "u-col"]
    r = portal.get("/escritorio", headers=cabecalho)
    assert r.status_code == 403
    assert r.json() == {"detail": SEM_ACESSO}
