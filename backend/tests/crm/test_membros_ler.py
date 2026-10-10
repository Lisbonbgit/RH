"""`GET /api/crm/membros` e `GET /api/crm/membros/candidatos` — só admin do CRM
(plano T1.6; desenho §3.1; dossiê §4 e §6).

- `/membros`: o admin master primeiro (sem linha em `crm_membros`, `id: null`),
  depois os membros por nome sem acentos nem maiúsculas, com o nome, o email
  e o tipo de conta lidos da conta do portal; um membro cuja conta foi
  apagada fica no fim com `conta_existe: false`.
- `/membros/candidatos`: as contas do portal que ainda não são membros nem
  são o admin master, por nome. A projeção de `users` é exatamente a mínima:
  o registo do duplo prova que a `password` nunca é pedida à base.

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
from crm.auth import SO_ADMIN, membro_crm_atual
from faturacao.auth import utilizador_atual

from .duplos import BaseFalsa, ColeccaoFalsa

MEMBROS_URL = "/api/crm/membros"
CANDIDATOS_URL = "/api/crm/membros/candidatos"
ROTAS = [MEMBROS_URL, CANDIDATOS_URL]
ADMIN_LOCAL = "admin.local@example.com"

PROJECAO_CONTAS = {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1}
CHAVES_MEMBRO = {
    "id", "user_id", "nome", "email", "tipo_conta", "perfil", "admin_master", "conta_existe", "criado_em",
}
CHAVES_CANDIDATO = {"id", "nome", "email", "tipo_conta"}

# Nomes escolhidos para a ordem por caracteres (A < Z < á) ser diferente da
# ordem sem acentos nem maiúsculas (álvaro < Ana < Zé; Beatriz < carla < Élio).
USERS = [
    {"id": "u-admin", "email": ADMIN_LOCAL, "name": "Administrador Principal", "role": "admin",
     "password": "$2b$12$hash-do-admin"},
    {"id": "u-ze", "email": "ze@example.com", "name": "Zé Silva", "role": "colaborador",
     "password": "$2b$12$hash-do-ze"},
    {"id": "u-alv", "email": "alvaro@example.com", "name": "álvaro Costa", "role": "gerente",
     "password": "$2b$12$hash-do-alvaro"},
    {"id": "u-ana", "email": "ana@example.com", "name": "Ana Reis", "role": "contabilista",
     "password": "$2b$12$hash-da-ana"},
    {"id": "u-eli", "email": "elio@example.com", "name": "Élio Matos", "role": "gerente",
     "password": "$2b$12$hash-do-elio"},
    {"id": "u-car", "email": "carla@example.com", "name": "carla Dias", "role": "colaborador",
     "password": "$2b$12$hash-da-carla"},
    {"id": "u-bea", "email": "bea@example.com", "name": "Beatriz Lopes", "role": "colaborador",
     "password": "$2b$12$hash-da-bea"},
]
MEMBROS = [
    {"id": "m-ze", "user_id": "u-ze", "perfil": "utilizador",
     "criado_em": "2026-10-01T09:00:00Z", "criado_por": "u-admin"},
    {"id": "m-alv", "user_id": "u-alv", "perfil": "motorista",
     "criado_em": "2026-10-02T09:00:00Z", "criado_por": "u-admin"},
    {"id": "m-ana", "user_id": "u-ana", "perfil": "admin",
     "criado_em": "2026-10-03T09:00:00Z", "criado_por": "u-admin"},
    {"id": "m-apagada", "user_id": "u-apagada", "perfil": "utilizador",
     "criado_em": "2026-09-30T09:00:00Z", "criado_por": "u-admin"},
]

LINHA_ADMIN_MASTER = {
    "id": None, "user_id": "u-admin", "nome": "Administrador Principal", "email": ADMIN_LOCAL,
    "tipo_conta": "gestor", "perfil": "admin", "admin_master": True, "conta_existe": True, "criado_em": None,
}

ADMIN_MASTER = {"user_id": "u-admin", "email": ADMIN_LOCAL, "role": "admin"}
ANA_ADMIN_DO_CRM = {"user_id": "u-ana", "email": "ana@example.com", "role": "contabilista"}
ZE_UTILIZADOR = {"user_id": "u-ze", "email": "ze@example.com", "role": "colaborador"}
ALVARO_MOTORISTA = {"user_id": "u-alv", "email": "alvaro@example.com", "role": "gerente"}
BEA_NAO_MEMBRO = {"user_id": "u-bea", "email": "bea@example.com", "role": "colaborador"}


def _base(membros=MEMBROS, users=USERS):
    return BaseFalsa({"crm_membros": list(membros), "users": list(users)})


def _rota(caminho):
    achadas = [r for r in crm.router.routes if getattr(r, "path", None) == caminho]
    assert achadas, f"{caminho} não está no router do CRM"
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
    `sessao(utilizador, base)` devolve o cliente (com `cliente.base`)."""
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


# --- As rotas: onde estão e quem as guarda -------------------------------------


@pytest.mark.parametrize("caminho", ROTAS)
def test_as_rotas_existem_so_com_get_e_vivem_em_crm_membros(caminho):
    rota = _rota(caminho)
    assert rota.methods == {"GET"}
    assert rota.endpoint.__module__ == "crm.membros"


@pytest.mark.parametrize("caminho", ROTAS)
def test_as_rotas_sao_so_do_admin_do_crm(caminho):
    """Exatamente uma guarda de perfil, a SO_ADMIN, sobre `membro_crm_atual`."""
    dependencias = _dependencias(_rota(caminho))
    assert membro_crm_atual in dependencias
    guardas = [d for d in dependencias if hasattr(d, "perfis_crm")]
    assert guardas == [SO_ADMIN]
    assert SO_ADMIN.perfis_crm == frozenset({"admin"})


def test_candidatos_e_declarada_antes_de_qualquer_rota_de_um_membro():
    """`/membros/candidatos` tem de vir antes de `/membros/{membro_id}` (T1.7):
    senão "candidatos" podia ser lido como o id de um membro."""
    caminhos = [r.path for r in crm.router.routes]
    candidatos = caminhos.index(CANDIDATOS_URL)
    de_um_membro = [i for i, c in enumerate(caminhos) if c.startswith(MEMBROS_URL + "/{")]
    assert all(candidatos < i for i in de_um_membro)


# --- Quem entra ----------------------------------------------------------------


@pytest.mark.parametrize("caminho", ROTAS)
def test_um_membro_utilizador_recebe_403_sem_permissao_sem_ler_as_contas(sessao, caminho):
    cliente = sessao(ZE_UTILIZADOR)
    r = cliente.get(caminho)
    assert r.status_code == 403
    assert r.json() == {"detail": {"codigo": "sem_permissao", "mensagem": "Sem permissão para esta ação."}}
    assert cliente.base.users.registo == []
    assert cliente.base.crm_membros.chamadas("find") == []


@pytest.mark.parametrize("caminho", ROTAS)
def test_um_membro_motorista_recebe_403_sem_permissao(sessao, caminho):
    r = sessao(ALVARO_MOTORISTA).get(caminho)
    assert r.status_code == 403
    assert r.json()["detail"]["codigo"] == "sem_permissao"


@pytest.mark.parametrize("caminho", ROTAS)
def test_quem_nao_e_membro_recebe_403_sem_acesso(sessao, caminho):
    cliente = sessao(BEA_NAO_MEMBRO)
    r = cliente.get(caminho)
    assert r.status_code == 403
    assert r.json() == {"detail": {"codigo": "sem_acesso_crm", "mensagem": "Sem acesso ao CRM."}}
    assert cliente.base.users.registo == []


@pytest.mark.parametrize("caminho", ROTAS)
@pytest.mark.parametrize("utilizador", [ADMIN_MASTER, ANA_ADMIN_DO_CRM], ids=["admin-master", "membro-admin"])
def test_o_admin_master_e_os_membros_admin_entram(sessao, caminho, utilizador):
    r = sessao(utilizador).get(caminho)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# --- GET /membros ----------------------------------------------------------------


def test_membros_admin_master_primeiro_depois_por_nome_e_as_contas_apagadas_no_fim(sessao):
    r = sessao(ADMIN_MASTER).get(MEMBROS_URL)
    assert r.status_code == 200
    assert r.json() == [
        LINHA_ADMIN_MASTER,
        {"id": "m-alv", "user_id": "u-alv", "nome": "álvaro Costa", "email": "alvaro@example.com",
         "tipo_conta": "gestor", "perfil": "motorista", "admin_master": False, "conta_existe": True,
         "criado_em": "2026-10-02T09:00:00Z"},
        {"id": "m-ana", "user_id": "u-ana", "nome": "Ana Reis", "email": "ana@example.com",
         "tipo_conta": "gestor", "perfil": "admin", "admin_master": False, "conta_existe": True,
         "criado_em": "2026-10-03T09:00:00Z"},
        {"id": "m-ze", "user_id": "u-ze", "nome": "Zé Silva", "email": "ze@example.com",
         "tipo_conta": "colaborador", "perfil": "utilizador", "admin_master": False, "conta_existe": True,
         "criado_em": "2026-10-01T09:00:00Z"},
        {"id": "m-apagada", "user_id": "u-apagada", "nome": None, "email": None,
         "tipo_conta": None, "perfil": "utilizador", "admin_master": False, "conta_existe": False,
         "criado_em": "2026-09-30T09:00:00Z"},
    ]


def test_membros_cada_linha_tem_exatamente_as_chaves_da_api_sem_password_nem_id_do_mongo(sessao):
    linhas = sessao(ADMIN_MASTER).get(MEMBROS_URL).json()
    assert linhas
    for linha in linhas:
        assert set(linha) == CHAVES_MEMBRO


def test_membros_projecoes_minimas_a_password_nunca_e_pedida(sessao):
    cliente = sessao(ADMIN_MASTER)
    assert cliente.get(MEMBROS_URL).status_code == 200
    assert cliente.base.crm_membros.chamadas("find") == [
        ("find", {}, {"_id": 0, "id": 1, "user_id": 1, "perfil": 1, "criado_em": 1})
    ]
    contas = cliente.base.users.chamadas("find")
    assert len(contas) == 1
    _, filtro, projecao = contas[0]
    assert set(filtro) == {"id"}
    assert sorted(filtro["id"]["$in"]) == ["u-alv", "u-ana", "u-apagada", "u-ze"]
    assert projecao == PROJECAO_CONTAS
    assert cliente.base.users.chamadas("find_one") == [("find_one", {"email": ADMIN_LOCAL}, PROJECAO_CONTAS)]
    for chamada in cliente.base.users.registo:
        assert "password" not in chamada[2]


def test_membros_nomes_iguais_desempatam_pelo_id(sessao):
    """`m-z` está primeiro na base: uma ordenação estável só pelo nome
    deixava-o à frente de `m-a`."""
    users = USERS + [
        {"id": "u-ana2", "email": "ana2@example.com", "name": "ANA REIS", "role": "colaborador"},
    ]
    membros = [
        {"id": "m-z", "user_id": "u-ana", "perfil": "admin", "criado_em": "2026-10-03T09:00:00Z"},
        {"id": "m-a", "user_id": "u-ana2", "perfil": "utilizador", "criado_em": "2026-10-04T09:00:00Z"},
    ]
    linhas = sessao(ADMIN_MASTER, _base(membros, users)).get(MEMBROS_URL).json()
    assert [linha["id"] for linha in linhas] == [None, "m-a", "m-z"]


def test_membros_sem_membros_so_o_admin_master(sessao):
    cliente = sessao(ADMIN_MASTER, _base(membros=[]))
    assert cliente.get(MEMBROS_URL).json() == [LINHA_ADMIN_MASTER]


def test_membros_a_linha_do_admin_master_aparece_mesmo_sem_a_conta_dele(sessao):
    """Quem pede é um membro admin; a conta do admin master não existe (ex.:
    ainda não foi criada no arranque). A linha fica, como conta inexistente."""
    users = [u for u in USERS if u["id"] != "u-admin"]
    linhas = sessao(ANA_ADMIN_DO_CRM, _base(users=users)).get(MEMBROS_URL).json()
    assert linhas[0] == {
        "id": None, "user_id": None, "nome": None, "email": None, "tipo_conta": None,
        "perfil": "admin", "admin_master": True, "conta_existe": False, "criado_em": None,
    }
    assert [linha["id"] for linha in linhas[1:]] == ["m-alv", "m-ana", "m-ze", "m-apagada"]


def test_membros_uma_linha_antiga_do_admin_master_nao_o_repete(sessao):
    """O admin master é admin do CRM sem linha. Se ficou uma linha dele (de
    antes de o ADMIN_EMAIL ser este), aparece só a linha do admin master."""
    membros = MEMBROS + [
        {"id": "m-admin", "user_id": "u-admin", "perfil": "utilizador", "criado_em": "2026-09-01T09:00:00Z"},
    ]
    linhas = sessao(ADMIN_MASTER, _base(membros=membros)).get(MEMBROS_URL).json()
    assert linhas[0] == LINHA_ADMIN_MASTER
    assert [linha["user_id"] for linha in linhas].count("u-admin") == 1


def test_membros_o_admin_master_segue_o_admin_email_do_ambiente(sessao, monkeypatch):
    """Lido a cada pedido: com outro ADMIN_EMAIL, o admin master é outra conta
    (e a linha da Ana deixa de aparecer como membro)."""
    cliente = sessao(ANA_ADMIN_DO_CRM)
    monkeypatch.setenv("ADMIN_EMAIL", "ana@example.com")
    linhas = cliente.get(MEMBROS_URL).json()
    assert linhas[0]["user_id"] == "u-ana"
    assert linhas[0]["admin_master"] is True
    assert [linha["user_id"] for linha in linhas] == ["u-ana", "u-alv", "u-ze", "u-apagada"]


def test_membros_um_perfil_desconhecido_sai_como_null_e_a_linha_continua_na_lista(sessao):
    """Fechado por omissão, como no /eu: a linha não dá acesso, mas o admin
    vê-a para lhe corrigir o perfil ou a retirar."""
    membros = [{"id": "m-ze", "user_id": "u-ze", "perfil": "gestor", "criado_em": "2026-10-01T09:00:00Z"}]
    linhas = sessao(ADMIN_MASTER, _base(membros=membros)).get(MEMBROS_URL).json()
    assert linhas[1]["id"] == "m-ze"
    assert linhas[1]["perfil"] is None


def test_membros_com_admin_email_vazio_nao_procura_contas_sem_email(sessao, monkeypatch):
    """Um email vazio nunca é o admin master (crm.auth): não se pergunta à base
    por `{"email": ""}`, que apanhava contas sem email."""
    cliente = sessao(ANA_ADMIN_DO_CRM)
    monkeypatch.setenv("ADMIN_EMAIL", "")
    linhas = cliente.get(MEMBROS_URL).json()
    assert cliente.base.users.chamadas("find_one") == []
    assert linhas[0]["admin_master"] is True
    assert linhas[0]["conta_existe"] is False


def test_membros_uma_falha_da_base_e_um_erro(sessao):
    base = BaseFalsa({
        "crm_membros": ColeccaoFalsa(MEMBROS, unicos=("id", "user_id")),
        "users": ColeccaoFalsa(USERS, falhar={"find": RuntimeError("base em baixo")}),
    })
    r = sessao(ADMIN_MASTER, base, levantar=False).get(MEMBROS_URL)
    assert r.status_code == 500


# --- GET /membros/candidatos -------------------------------------------------------


def test_candidatos_sao_as_contas_que_nao_sao_membros_nem_o_admin_master_por_nome(sessao):
    r = sessao(ADMIN_MASTER).get(CANDIDATOS_URL)
    assert r.status_code == 200
    assert r.json() == [
        {"id": "u-bea", "nome": "Beatriz Lopes", "email": "bea@example.com", "tipo_conta": "colaborador"},
        {"id": "u-car", "nome": "carla Dias", "email": "carla@example.com", "tipo_conta": "colaborador"},
        {"id": "u-eli", "nome": "Élio Matos", "email": "elio@example.com", "tipo_conta": "gestor"},
    ]


def test_candidatos_projecao_exata_sem_password(sessao):
    cliente = sessao(ADMIN_MASTER)
    linhas = cliente.get(CANDIDATOS_URL).json()
    contas = cliente.base.users.chamadas("find")
    assert len(contas) == 1
    assert contas[0][2] == PROJECAO_CONTAS
    for chamada in cliente.base.users.registo:
        assert "password" not in chamada[2]
    for linha in linhas:
        assert set(linha) == CHAVES_CANDIDATO
    assert cliente.base.crm_membros.chamadas("find") == [("find", {}, {"_id": 0, "user_id": 1})]


def test_candidatos_uma_linha_com_perfil_desconhecido_continua_a_excluir_a_conta(sessao):
    """A linha existe (o índice único de `user_id` recusava outra), por isso
    a conta não é candidata: corrige-se o perfil em vez de a voltar a juntar."""
    membros = [{"id": "m-bea", "user_id": "u-bea", "perfil": "gestor"}]
    ids = [c["id"] for c in sessao(ADMIN_MASTER, _base(membros=membros)).get(CANDIDATOS_URL).json()]
    assert "u-bea" not in ids
    assert ids == ["u-alv", "u-ana", "u-car", "u-eli", "u-ze"]


def test_candidatos_contas_sem_id_de_texto_ficam_de_fora(sessao):
    """Sem `id` não se pode juntar (o POST precisa do `user_id`)."""
    users = USERS + [
        {"email": "sem.id@example.com", "name": "Sem Id", "role": "colaborador"},
        {"id": "", "email": "id.vazio@example.com", "name": "Id Vazio", "role": "colaborador"},
        {"id": 7, "email": "id.numero@example.com", "name": "Id Número", "role": "colaborador"},
    ]
    ids = [c["id"] for c in sessao(ADMIN_MASTER, _base(users=users)).get(CANDIDATOS_URL).json()]
    assert ids == ["u-bea", "u-car", "u-eli"]


def test_candidatos_nomes_iguais_desempatam_pelo_id(sessao):
    """A conta nova entra na base DEPOIS e tem o id menor: uma ordenação
    estável só pelo nome deixava-a em segundo."""
    users = USERS + [
        {"id": "u-ba", "email": "bea0@example.com", "name": "BEATRIZ LOPES", "role": "gerente"},
    ]
    ids = [c["id"] for c in sessao(ADMIN_MASTER, _base(users=users)).get(CANDIDATOS_URL).json()]
    assert ids == ["u-ba", "u-bea", "u-car", "u-eli"]


def test_candidatos_o_admin_master_fica_de_fora_mesmo_quando_quem_pede_e_outro_admin(sessao):
    ids = [c["id"] for c in sessao(ANA_ADMIN_DO_CRM).get(CANDIDATOS_URL).json()]
    assert "u-admin" not in ids


def test_candidatos_com_admin_email_vazio_ninguem_fica_de_fora_por_ser_o_admin_master(sessao, monkeypatch):
    users = USERS + [{"id": "u-sem-email", "email": "", "name": "Sem Email", "role": "colaborador"}]
    cliente = sessao(ANA_ADMIN_DO_CRM, _base(users=users))
    monkeypatch.setenv("ADMIN_EMAIL", "")
    ids = [c["id"] for c in cliente.get(CANDIDATOS_URL).json()]
    assert ids == ["u-admin", "u-bea", "u-car", "u-eli", "u-sem-email"]


def test_candidatos_quando_todos_sao_membros_a_lista_e_vazia(sessao):
    membros = [{"id": f"m-{u['id']}", "user_id": u["id"], "perfil": "utilizador"} for u in USERS[1:]]
    assert sessao(ADMIN_MASTER, _base(membros=membros)).get(CANDIDATOS_URL).json() == []


# --- De ponta a ponta: a sessão verdadeira do portal --------------------------------

SEGREDO = "segredo-de-teste-crm-membros"
AGORA = int(time.time())


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
    base = _base()
    monkeypatch.setattr(faturacao.auth, "obter_db", lambda: base)
    monkeypatch.setattr(crm.db, "obter_db", lambda: base)
    app = FastAPI()
    app.include_router(crm.router)
    cliente = TestClient(app)
    cliente.base = base
    return cliente


@pytest.mark.parametrize("caminho", ROTAS)
def test_sem_cabecalho_da_o_403_herdado(portal, caminho):
    r = portal.get(caminho)
    assert r.status_code == 403
    assert r.json() == {"detail": "Not authenticated"}


@pytest.mark.parametrize("caminho", ROTAS)
def test_conta_apagada_da_401_sessao_terminada(portal, caminho):
    r = portal.get(caminho, headers=_cabecalho(_token("u-apagada")))
    assert r.status_code == 401
    assert r.json() == {"detail": "Sessão terminada"}
    assert portal.base.crm_membros.registo == []


def test_o_admin_master_de_ponta_a_ponta(portal):
    r = portal.get(MEMBROS_URL, headers=_cabecalho(_token("u-admin", email=ADMIN_LOCAL, role="admin")))
    assert r.status_code == 200
    assert r.json()[0] == LINHA_ADMIN_MASTER
    r = portal.get(CANDIDATOS_URL, headers=_cabecalho(_token("u-admin", email=ADMIN_LOCAL, role="admin")))
    assert r.status_code == 200
    assert [c["id"] for c in r.json()] == ["u-bea", "u-car", "u-eli"]


def test_um_colaborador_membro_utilizador_recebe_403_sem_permissao(portal):
    r = portal.get(MEMBROS_URL, headers=_cabecalho(_token("u-ze")))
    assert r.status_code == 403
    assert r.json()["detail"]["codigo"] == "sem_permissao"


def test_um_gestor_do_portal_que_nao_e_membro_recebe_403_sem_acesso(portal):
    r = portal.get(CANDIDATOS_URL, headers=_cabecalho(_token("u-eli", role="gerente")))
    assert r.status_code == 403
    assert r.json()["detail"]["codigo"] == "sem_acesso_crm"


def test_um_token_com_o_email_do_admin_master_nao_chega(portal):
    """O admin master vem do email da conta na base, não do token."""
    r = portal.get(MEMBROS_URL, headers=_cabecalho(_token("u-bea", email=ADMIN_LOCAL, role="admin")))
    assert r.status_code == 403
    assert r.json()["detail"]["codigo"] == "sem_acesso_crm"
