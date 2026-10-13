"""`GET /api/crm/eu` — a cada sessão do portal, "sou membro do CRM, e com que
perfil?" (plano T1.5; desenho §4.2; dossiê §4).

É a única rota da família "qualquer sessão válida": depende de
`faturacao.auth.utilizador_atual` e NUNCA de `membro_crm_atual`. Quem não é
membro recebe 200 `{"membro": false, "perfil": null, "admin_master": false}`
e nunca 403 — o frontend pergunta isto a todas as sessões (uma vez por token)
para decidir se mostra o CRM, e um 403 ali era um erro no ecrã de quem nem
sabe que o CRM existe. Os 401/403 da própria sessão são os herdados.

Rotas por `TestClient` com `dependency_overrides[utilizador_atual]` e
`monkeypatch.setattr(crm.db, "obter_db", …)` (plano §10); no fim, de ponta a
ponta com a sessão verdadeira do portal (JWT + conta lida da base).
"""
import time

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import crm
import crm.db
import faturacao.auth
from crm.auth import membro_crm_atual
from faturacao.auth import utilizador_atual

from .duplos import BaseFalsa, ColeccaoFalsa

CAMINHO = "/api/crm/eu"
ADMIN_LOCAL = "admin.local@example.com"
NAO_MEMBRO = {"membro": False, "perfil": None, "admin_master": False}


def _base(membros=(), users=()):
    return BaseFalsa({"crm_membros": list(membros), "users": list(users)})


def _rota_eu():
    achadas = [r for r in crm.router.routes if getattr(r, "path", None) == CAMINHO]
    assert achadas, f"{CAMINHO} não está no router do CRM"
    assert len(achadas) == 1
    return achadas[0]


def _dependencias(rota):
    """Todos os `call` das dependências da rota, recursivamente (molde de
    tests/faturacao/test_protecao_rotas.py)."""
    encontrados = []

    def _procura(dependente):
        for d in dependente.dependencies:
            encontrados.append(d.call)
            _procura(d)

    _procura(rota.dependant)
    return encontrados


@pytest.fixture
def sessao(monkeypatch):
    """Uma app só com o router do CRM, a sessão do portal trocada por
    `dependency_overrides` e a base do CRM trocada pelo único ponto.

    `sessao(utilizador, base)` devolve o cliente; `utilizador` é o dicionário
    que o `utilizador_atual` devolveria (com o email JÁ lido da base)."""
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)

    def _montar(utilizador, base=None, levantar=True):
        base = base if base is not None else _base()
        monkeypatch.setattr(crm.db, "obter_db", lambda: base)
        app = FastAPI()
        app.include_router(crm.router)
        app.dependency_overrides[utilizador_atual] = lambda: dict(utilizador)
        cliente = TestClient(app, raise_server_exceptions=levantar)
        cliente.base = base
        return cliente

    return _montar


# --- A rota: onde está e de que depende ---------------------------------------


def test_a_rota_existe_so_com_get_no_router_do_crm():
    rota = _rota_eu()
    assert rota.methods == {"GET"}


def test_a_rota_vive_em_crm_eu():
    assert _rota_eu().endpoint.__module__ == "crm.eu"


def test_depende_da_sessao_do_portal_e_nao_de_ser_membro():
    """Família "qualquer sessão válida" (T1.8): `utilizador_atual`, sem
    `membro_crm_atual` nem nenhuma guarda de perfil — senão um não-membro
    recebia 403 em vez de `membro: false`."""
    dependencias = _dependencias(_rota_eu())
    assert utilizador_atual in dependencias
    assert membro_crm_atual not in dependencias
    assert not [d for d in dependencias if hasattr(d, "perfis_crm")]


# --- O que responde (sessão por dependency_overrides) --------------------------


def test_um_nao_membro_recebe_200_com_membro_falso_e_nunca_403(sessao):
    cliente = sessao({"user_id": "u-ger", "email": "gestor@example.com", "role": "gerente"})
    r = cliente.get(CAMINHO)
    assert r.status_code == 200
    assert r.json() == NAO_MEMBRO
    assert cliente.base.crm_membros.chamadas("find_one") == [
        ("find_one", {"user_id": "u-ger"}, {"_id": 0, "perfil": 1})
    ]


def test_um_membro_motorista_recebe_o_seu_perfil(sessao):
    """O motorista não entra no /crm na F1–F2, mas o /eu diz-lhe a verdade:
    é o frontend (acesso.js) que decide o que lhe mostra."""
    cliente = sessao(
        {"user_id": "u-mot", "email": "motorista@example.com", "role": "colaborador"},
        _base([{"id": "m-mot", "user_id": "u-mot", "perfil": "motorista"}]),
    )
    r = cliente.get(CAMINHO)
    assert r.status_code == 200
    assert r.json() == {"membro": True, "perfil": "motorista", "admin_master": False}


@pytest.mark.parametrize("perfil", ["admin", "utilizador", "motorista"])
def test_cada_membro_recebe_o_perfil_da_sua_linha(sessao, perfil):
    cliente = sessao(
        {"user_id": "u2", "email": "u2@example.com", "role": "colaborador"},
        _base([{"id": "m2", "user_id": "u2", "perfil": perfil}]),
    )
    assert cliente.get(CAMINHO).json() == {"membro": True, "perfil": perfil, "admin_master": False}


def test_o_admin_master_e_admin_do_crm_sem_ler_os_membros(sessao):
    cliente = sessao({"user_id": "u-admin", "email": ADMIN_LOCAL, "role": "admin"})
    r = cliente.get(CAMINHO)
    assert r.status_code == 200
    assert r.json() == {"membro": True, "perfil": "admin", "admin_master": True}
    assert cliente.base.crm_membros.registo == []


def test_o_papel_do_portal_nao_faz_de_ninguem_membro(sessao):
    """Um admin do portal que não é o admin master, sem linha, não é membro."""
    cliente = sessao({"user_id": "u-outro-admin", "email": "outro.admin@example.com", "role": "admin"})
    assert cliente.get(CAMINHO).json() == NAO_MEMBRO


def test_uma_linha_com_perfil_desconhecido_responde_como_nao_membro(sessao):
    cliente = sessao(
        {"user_id": "u4", "email": "u4@example.com", "role": "colaborador"},
        _base([{"id": "m4", "user_id": "u4", "perfil": "gestor"}]),
    )
    r = cliente.get(CAMINHO)
    assert r.status_code == 200
    assert r.json() == NAO_MEMBRO


def test_le_se_a_cada_pedido_retirar_o_membro_muda_a_resposta_seguinte(sessao):
    cliente = sessao(
        {"user_id": "u-col", "email": "colaborador@example.com", "role": "colaborador"},
        _base([{"id": "m-col", "user_id": "u-col", "perfil": "utilizador"}]),
    )
    assert cliente.get(CAMINHO).json()["membro"] is True
    cliente.base.crm_membros.docs.clear()
    assert cliente.get(CAMINHO).json() == NAO_MEMBRO


def test_uma_falha_da_base_e_um_erro_e_nao_um_nao_membro(sessao):
    """Com a base em baixo, responder `membro: false` seria mentir — e o
    frontend guardava essa resposta para o token inteiro (24 h sem CRM). Um
    500 é uma falha: o CRM fica escondido e o pedido seguinte volta a tentar
    (T1.11, `criarCacheEu`)."""
    base = BaseFalsa({"crm_membros": ColeccaoFalsa(falhar={"find_one": RuntimeError("base em baixo")})})
    cliente = sessao({"user_id": "u2", "email": "u2@example.com", "role": "colaborador"}, base, levantar=False)
    r = cliente.get(CAMINHO)
    assert r.status_code == 500


# --- De ponta a ponta: a sessão verdadeira do portal ---------------------------

SEGREDO = "segredo-de-teste-crm-eu"
AGORA = int(time.time())

USERS = [
    {"id": "u-admin", "email": ADMIN_LOCAL, "role": "admin"},
    {"id": "u-ger", "email": "gestor@example.com", "role": "gerente"},
    {"id": "u-col", "email": "colaborador@example.com", "role": "colaborador"},
    {"id": "u-pw", "email": "trocou@example.com", "role": "colaborador", "password_mudada_em": AGORA - 60},
]
MEMBROS = [
    {"id": "m-col", "user_id": "u-col", "perfil": "utilizador"},
    {"id": "m-pw", "user_id": "u-pw", "perfil": "admin"},
]


def _token(user_id, email="qualquer@example.com", role="colaborador", iat=AGORA):
    dados = {"user_id": user_id, "email": email, "role": role, "iat": iat, "exp": AGORA + 3600}
    return jwt.encode(dados, SEGREDO, algorithm="HS256")


def _cabecalho(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def portal(monkeypatch):
    """O router do CRM com a sessão verdadeira (faturacao.auth) e a mesma base
    falsa para o portal e para o CRM."""
    monkeypatch.setenv("JWT_SECRET", SEGREDO)
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    base = _base(MEMBROS, USERS)
    monkeypatch.setattr(faturacao.auth, "obter_db", lambda: base)
    monkeypatch.setattr(crm.db, "obter_db", lambda: base)
    app = FastAPI()
    app.include_router(crm.router)
    cliente = TestClient(app)
    cliente.base = base
    return cliente


def test_sem_cabecalho_da_o_403_herdado(portal):
    r = portal.get(CAMINHO)
    assert r.status_code == 403
    assert r.json() == {"detail": "Not authenticated"}


def test_token_invalido_da_o_401_herdado(portal):
    r = portal.get(CAMINHO, headers=_cabecalho("isto-nao-e-um-token"))
    assert r.status_code == 401
    assert r.json() == {"detail": "Sessão inválida ou expirada"}


def test_conta_apagada_da_401_sessao_terminada_sem_ler_os_membros(portal):
    r = portal.get(CAMINHO, headers=_cabecalho(_token("u-apagada")))
    assert r.status_code == 401
    assert r.json() == {"detail": "Sessão terminada"}
    assert portal.base.crm_membros.registo == []


def test_sessao_anterior_a_troca_de_palavra_passe_da_401(portal):
    r = portal.get(CAMINHO, headers=_cabecalho(_token("u-pw", iat=AGORA - 3600)))
    assert r.status_code == 401
    assert r.json() == {"detail": "Sessão terminada"}


def test_um_colaborador_membro_recebe_o_seu_estado(portal):
    r = portal.get(CAMINHO, headers=_cabecalho(_token("u-col")))
    assert r.status_code == 200
    assert r.json() == {"membro": True, "perfil": "utilizador", "admin_master": False}


def test_um_gestor_do_portal_que_nao_e_membro_recebe_200_e_nao_403(portal):
    r = portal.get(CAMINHO, headers=_cabecalho(_token("u-ger", role="gerente")))
    assert r.status_code == 200
    assert r.json() == NAO_MEMBRO


def test_o_admin_master_de_ponta_a_ponta(portal):
    r = portal.get(CAMINHO, headers=_cabecalho(_token("u-admin", email=ADMIN_LOCAL, role="admin")))
    assert r.status_code == 200
    assert r.json() == {"membro": True, "perfil": "admin", "admin_master": True}
    assert portal.base.crm_membros.registo == []


def test_o_admin_master_vem_do_email_da_base_e_nao_do_token(portal):
    """Um token com o email do admin master não chega: conta o email da conta
    na base (faturacao.auth.utilizador_atual substitui-o)."""
    r = portal.get(CAMINHO, headers=_cabecalho(_token("u-ger", email=ADMIN_LOCAL, role="admin")))
    assert r.status_code == 200
    assert r.json() == NAO_MEMBRO
