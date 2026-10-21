"""`GET /api/crm/config` — a configuração do mapa: a chave do navegador e o
Map ID da Google, e o centro (plano do mapa Google, G2; dossiê §6 e §8).

Reescrita, na G2, da porta de tests/Unit/Http/ConfigMapaTest.php e de
tests/Integration/Api/SessaoMapaTest.php do CRM autónomo (etiqueta
`referencia-standalone`), que até à F2 entregava os mosaicos da Geoapify e a
alternativa do OpenStreetMap ao mapa antigo (saiu na G19). Com o mapa da Google:

- A rota continua própria e do escritório (admin e utilizador do CRM). O
  motorista só entra na F4; quem não é membro recebe 403 `sem_acesso_crm`;
  sem sessão, os 403/401 herdados; uma conta apagada, 401.
- A chave do navegador (`CRM_GOOGLE_CHAVE_NAVEGADOR`) e o Map ID
  (`CRM_GOOGLE_MAP_ID`) leem-se a cada pedido (não à importação): mudá-los no
  `.env` não pede outro código. As duas são obrigatórias: falta uma, ou está
  vazia → `google: null` (o frontend mostra "Mapa não configurado"). Não há
  mapa alternativo.
- A chave vai tal e qual, no JSON (não num URL): saíram o `_codificar` e os
  casos do `rawurlencode`. É pública por natureza (restrita por referrer e por
  API na consola Google), mas só a membros do escritório e nunca nos registos.
"""
import inspect
import logging
import time

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import crm
import crm.db
import faturacao.auth
from crm import config_mapa as modulo
from crm.auth import ESCRITORIO, membro_crm_atual
from crm.config_mapa import VARIAVEL_CHAVE, VARIAVEL_MAP_ID, config_mapa
from crm.pedidos import corpo_json
from faturacao.auth import utilizador_atual

from .duplos import BaseFalsa, ColeccaoFalsa, unicos_declarados

CONFIG_URL = "/api/crm/config"
DEFINICOES_URL = "/api/crm/definicoes"
ADMIN_LOCAL = "admin.local@example.com"

# Escritos à mão (não copiados do código).
CHAVE = "chave-teste-navegador"
MAP_ID = "map-id-teste"
DEFINICOES = {"fabrica_morada": "", "fabrica_lat": 38.7223, "fabrica_lng": -9.1393}
CENTRO_PADRAO = {"lat": 38.7223, "lng": -9.1393}

PROJECAO_GUARDADA = {"_id": 0, "chave": 1, "valor": 1}

SEM_PERMISSAO = {"detail": {"codigo": "sem_permissao", "mensagem": "Sem permissão para esta ação."}}
SEM_ACESSO = {"detail": {"codigo": "sem_acesso_crm", "mensagem": "Sem acesso ao CRM."}}


# --- A função pura -------------------------------------------------------------------------


def test_os_nomes_das_variaveis_sao_os_do_plano():
    """Plano §1 "Chave e Map ID" e adenda §6.2; a dos mosaicos saiu."""
    assert VARIAVEL_CHAVE == "CRM_GOOGLE_CHAVE_NAVEGADOR"
    assert VARIAVEL_MAP_ID == "CRM_GOOGLE_MAP_ID"


def test_a_funcao_pura_recebe_a_chave_o_map_id_e_as_definicoes_por_esta_ordem():
    assert list(inspect.signature(config_mapa).parameters) == ["chave", "map_id", "definicoes"]


def test_com_a_chave_e_o_map_id_vem_o_bloco_google_e_o_centro():
    assert config_mapa(CHAVE, MAP_ID, DEFINICOES) == {
        "google": {"chave": CHAVE, "map_id": MAP_ID},
        "centro": CENTRO_PADRAO,
    }


def test_a_chave_e_o_map_id_nao_se_trocam():
    google = config_mapa("primeiro-argumento", "segundo-argumento", DEFINICOES)["google"]
    assert google["chave"] == "primeiro-argumento"
    assert google["map_id"] == "segundo-argumento"


@pytest.mark.parametrize(
    "chave, map_id",
    [("", MAP_ID), (CHAVE, ""), ("", "")],
    ids=["sem chave", "sem Map ID", "sem nenhum dos dois"],
)
def test_sem_a_chave_ou_sem_o_map_id_o_google_e_nulo(chave, map_id):
    """As duas são obrigatórias (plano §1): sem uma delas o frontend mostra
    `MENSAGEM_MAPA_NAO_CONFIGURADO`; o centro vem na mesma."""
    assert config_mapa(chave, map_id, DEFINICOES) == {"google": None, "centro": CENTRO_PADRAO}


@pytest.mark.parametrize(
    "valor",
    ["AZaz09-_.~", "a b&c=d", "a/b+c", "?#%:@!*'()", "ção €", " "],
    ids=["não reservados", "espaço, e comercial e igual", "barra e mais", "reservados", "UTF-8",
         "só um espaço conta como valor"],
)
def test_a_chave_e_o_map_id_vao_tal_e_qual_sem_codificacao(valor):
    """Vão no JSON, não num URL: nada se codifica (saiu o `rawurlencode` da
    F2). Como lá, só o texto vazio conta como "sem valor"."""
    assert config_mapa(valor, MAP_ID, DEFINICOES)["google"] == {"chave": valor, "map_id": MAP_ID}
    assert config_mapa(CHAVE, valor, DEFINICOES)["google"] == {"chave": CHAVE, "map_id": valor}


def test_o_centro_vem_das_definicoes():
    """`oCentroVemDasDefinicoes`."""
    definicoes = {"fabrica_morada": "Rua A, Porto", "fabrica_lat": 41.1496, "fabrica_lng": -8.611}
    assert config_mapa(CHAVE, MAP_ID, definicoes)["centro"] == {"lat": 41.1496, "lng": -8.611}
    assert config_mapa("", "", definicoes)["centro"] == {"lat": 41.1496, "lng": -8.611}


def test_as_chaves_saem_por_esta_ordem():
    for chave, map_id in ((CHAVE, MAP_ID), ("", MAP_ID), (CHAVE, ""), ("", "")):
        resultado = config_mapa(chave, map_id, DEFINICOES)
        assert list(resultado) == ["google", "centro"]
        assert list(resultado["centro"]) == ["lat", "lng"]
    assert list(config_mapa(CHAVE, MAP_ID, DEFINICOES)["google"]) == ["chave", "map_id"]


def test_os_mosaicos_a_alternativa_e_a_codificacao_sairam_do_modulo():
    """Não há mapa alternativo nem URL com a chave: o módulo deixa de ter as
    peças da F2 e de nomear a variável dos mosaicos."""
    for nome in ("MODELO_MOSAICOS", "ALTERNATIVA", "_codificar", "chave_mosaicos"):
        assert not hasattr(modulo, nome), nome
    fonte = inspect.getsource(modulo)
    assert "CRM_GEOAPIFY" not in fonte
    assert "urllib" not in fonte


# --- A rota GET /config ---------------------------------------------------------------------

USERS = [
    {"id": "u-admin", "email": ADMIN_LOCAL, "name": "Administrador Principal", "role": "admin",
     "password": "$2b$12$hash-do-admin"},
    {"id": "u-ana", "email": "ana@example.com", "name": "Ana Reis", "role": "contabilista",
     "password": "$2b$12$hash-da-ana"},
    {"id": "u-ze", "email": "ze@example.com", "name": "Zé Silva", "role": "colaborador",
     "password": "$2b$12$hash-do-ze"},
    {"id": "u-alv", "email": "alvaro@example.com", "name": "Álvaro Costa", "role": "gerente",
     "password": "$2b$12$hash-do-alvaro"},
    {"id": "u-bea", "email": "bea@example.com", "name": "Beatriz Lopes", "role": "colaborador",
     "password": "$2b$12$hash-da-bea"},
]
MEMBROS = [
    {"id": "m-ana", "user_id": "u-ana", "perfil": "admin", "criado_em": "2026-10-03T09:00:00Z"},
    {"id": "m-ze", "user_id": "u-ze", "perfil": "utilizador", "criado_em": "2026-10-01T09:00:00Z"},
    {"id": "m-alv", "user_id": "u-alv", "perfil": "motorista", "criado_em": "2026-10-02T09:00:00Z"},
    {"id": "m-apagada", "user_id": "u-apagada", "perfil": "utilizador", "criado_em": "2026-09-30T09:00:00Z"},
]

ADMIN_MASTER = {"user_id": "u-admin", "email": ADMIN_LOCAL, "role": "admin"}
ANA_ADMIN_DO_CRM = {"user_id": "u-ana", "email": "ana@example.com", "role": "contabilista"}
ZE_UTILIZADOR = {"user_id": "u-ze", "email": "ze@example.com", "role": "colaborador"}
ALVARO_MOTORISTA = {"user_id": "u-alv", "email": "alvaro@example.com", "role": "gerente"}
BEA_NAO_MEMBRO = {"user_id": "u-bea", "email": "bea@example.com", "role": "colaborador"}

CONFIG_COM_GOOGLE = {"google": {"chave": CHAVE, "map_id": MAP_ID}, "centro": CENTRO_PADRAO}
CONFIG_SEM_GOOGLE = {"google": None, "centro": CENTRO_PADRAO}


def _guardada(chave, valor):
    return {"chave": chave, "valor": valor, "atualizado_em": "2026-10-01T08:00:00.000000Z", "atualizado_por": "u-ana"}


def _base(guardadas=(), membros=MEMBROS, users=USERS):
    return BaseFalsa({"crm_membros": list(membros), "users": list(users), "crm_definicoes": list(guardadas)})


def _rota():
    achadas = [
        r for r in crm.router.routes
        if getattr(r, "path", None) == CONFIG_URL and "GET" in getattr(r, "methods", ())
    ]
    assert len(achadas) == 1, f"GET {CONFIG_URL} não está (uma só vez) no router do CRM"
    return achadas[0]


def _dependencias(rota):
    encontrados = []

    def _procura(dependente):
        for d in dependente.dependencies:
            encontrados.append(d.call)
            _procura(d)

    _procura(rota.dependant)
    return encontrados


@pytest.fixture
def sessao(monkeypatch):
    """Como em test_definicoes.py; a chave e o Map ID começam SEMPRE fora do
    ambiente (o Mac do dono pode tê-los no shell ou no `.env.local`)."""
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    monkeypatch.delenv(VARIAVEL_CHAVE, raising=False)
    monkeypatch.delenv(VARIAVEL_MAP_ID, raising=False)

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


def _com_google(monkeypatch, chave=CHAVE, map_id=MAP_ID):
    monkeypatch.setenv(VARIAVEL_CHAVE, chave)
    monkeypatch.setenv(VARIAVEL_MAP_ID, map_id)


def test_a_rota_existe_e_vive_em_crm_config_mapa():
    rota = _rota()
    assert rota.methods == {"GET"}
    assert rota.endpoint.__module__ == "crm.config_mapa"


def test_e_do_escritorio_com_uma_so_guarda_e_sem_corpo():
    dependencias = _dependencias(_rota())
    assert membro_crm_atual in dependencias
    assert [d for d in dependencias if hasattr(d, "perfis_crm")] == [ESCRITORIO]
    assert corpo_json not in dependencias


def test_com_a_sessao_iniciada_vem_a_chave_o_map_id_e_o_centro_padrao(sessao, monkeypatch):
    """`comASessaoIniciadaVemOMapa…`, agora com a Google: o Zé (utilizador) —
    o mapa não é só para o admin."""
    _com_google(monkeypatch)
    r = sessao(ZE_UTILIZADOR).get(CONFIG_URL)
    assert (r.status_code, r.json()) == (200, CONFIG_COM_GOOGLE)


def test_sem_as_variaveis_vem_google_nulo(sessao):
    """O normal em local sem a Demo Key (adenda §3.1): o resto do CRM
    funciona e o ecrã diz "Mapa não configurado"."""
    r = sessao(ZE_UTILIZADOR).get(CONFIG_URL)
    assert (r.status_code, r.json()) == (200, CONFIG_SEM_GOOGLE)


@pytest.mark.parametrize(
    "ambiente",
    [
        {VARIAVEL_CHAVE: "", VARIAVEL_MAP_ID: MAP_ID},
        {VARIAVEL_CHAVE: CHAVE, VARIAVEL_MAP_ID: ""},
        {VARIAVEL_CHAVE: CHAVE},
        {VARIAVEL_MAP_ID: MAP_ID},
        {VARIAVEL_CHAVE: "", VARIAVEL_MAP_ID: ""},
    ],
    ids=["chave vazia", "Map ID vazio", "só a chave", "só o Map ID", "as duas vazias"],
)
def test_com_uma_das_variaveis_em_falta_ou_vazia_vem_google_nulo(sessao, monkeypatch, ambiente):
    for nome, valor in ambiente.items():
        monkeypatch.setenv(nome, valor)
    r = sessao(ZE_UTILIZADOR).get(CONFIG_URL)
    assert (r.status_code, r.json()) == (200, CONFIG_SEM_GOOGLE)
    assert CHAVE not in r.text and MAP_ID not in r.text


def test_a_chave_vai_tal_e_qual_no_json(sessao, monkeypatch):
    _com_google(monkeypatch, chave="a b&c=d/é", map_id="x y&z")
    assert sessao(ZE_UTILIZADOR).get(CONFIG_URL).json()["google"] == {"chave": "a b&c=d/é", "map_id": "x y&z"}


def test_as_variaveis_leem_se_a_cada_pedido_e_nao_a_importacao(sessao, monkeypatch):
    cliente = sessao(ZE_UTILIZADOR)
    assert cliente.get(CONFIG_URL).json() == CONFIG_SEM_GOOGLE
    _com_google(monkeypatch, "primeira", "mapa-um")
    assert cliente.get(CONFIG_URL).json()["google"] == {"chave": "primeira", "map_id": "mapa-um"}
    monkeypatch.setenv(VARIAVEL_CHAVE, "segunda")
    assert cliente.get(CONFIG_URL).json()["google"] == {"chave": "segunda", "map_id": "mapa-um"}
    monkeypatch.setenv(VARIAVEL_MAP_ID, "mapa-dois")
    assert cliente.get(CONFIG_URL).json()["google"] == {"chave": "segunda", "map_id": "mapa-dois"}
    monkeypatch.delenv(VARIAVEL_MAP_ID)
    assert cliente.get(CONFIG_URL).json() == CONFIG_SEM_GOOGLE
    monkeypatch.setenv(VARIAVEL_MAP_ID, "mapa-dois")
    monkeypatch.delenv(VARIAVEL_CHAVE)
    assert cliente.get(CONFIG_URL).json() == CONFIG_SEM_GOOGLE


def test_o_centro_vem_das_definicoes_guardadas(sessao):
    base = _base([_guardada("fabrica_lat", "41.149600"), _guardada("fabrica_lng", "-8.611000")])
    r = sessao(ZE_UTILIZADOR, base).get(CONFIG_URL)
    assert r.json()["centro"] == {"lat": 41.1496, "lng": -8.611}
    assert [type(v) for v in r.json()["centro"].values()] == [float, float]


def test_a_config_le_as_definicoes_uma_vez_e_so_a_chave_e_o_valor(sessao):
    cliente = sessao(ZE_UTILIZADOR, _base([_guardada("fabrica_lat", "41.149600")]))
    assert cliente.get(CONFIG_URL).status_code == 200
    assert cliente.base.crm_definicoes.registo == [("find", {}, PROJECAO_GUARDADA)]


def test_uma_definicao_estragada_nao_parte_o_mapa(sessao, monkeypatch):
    """Todo o escritório abre o mapa: uma linha estragada à mão em
    crm_definicoes fica de fora e o centro volta ao padrão."""
    _com_google(monkeypatch)
    base = _base([{"chave": "fabrica_lat", "valor": None}, _guardada("fabrica_lng", "-8.611000")])
    r = sessao(ZE_UTILIZADOR, base).get(CONFIG_URL)
    assert (r.status_code, r.json()) == (200, {
        "google": {"chave": CHAVE, "map_id": MAP_ID}, "centro": {"lat": 38.7223, "lng": -8.611},
    })


@pytest.mark.parametrize(
    "utilizador", [ADMIN_MASTER, ANA_ADMIN_DO_CRM, ZE_UTILIZADOR], ids=["admin master", "admin", "utilizador"]
)
def test_o_escritorio_ve_a_config(sessao, monkeypatch, utilizador):
    _com_google(monkeypatch)
    r = sessao(utilizador).get(CONFIG_URL)
    assert (r.status_code, r.json()) == (200, CONFIG_COM_GOOGLE)


def test_o_motorista_nao_ve_a_config(sessao, monkeypatch):
    """As permissões do terreno chegam na F4 (plano F2 §1, "Perfis por
    rota"); a chave do navegador e o Map ID só vão para quem pode abrir o
    mapa."""
    _com_google(monkeypatch)
    cliente = sessao(ALVARO_MOTORISTA)
    r = cliente.get(CONFIG_URL)
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)
    assert CHAVE not in r.text and MAP_ID not in r.text
    assert cliente.base.crm_definicoes.registo == []


def test_quem_nao_e_membro_nao_ve_a_config(sessao, monkeypatch):
    _com_google(monkeypatch)
    cliente = sessao(BEA_NAO_MEMBRO)
    r = cliente.get(CONFIG_URL)
    assert (r.status_code, r.json()) == (403, SEM_ACESSO)
    assert CHAVE not in r.text and MAP_ID not in r.text
    assert cliente.base.crm_definicoes.registo == []


def test_nem_a_chave_nem_o_map_id_vao_para_os_registos(sessao, monkeypatch, caplog):
    """Plano §0, regra 8: os dois canários chegam ao browser e a nenhum
    registo, mesmo em DEBUG."""
    canaria_chave = "canaria-chave-navegador-0123456789"
    canaria_map_id = "canaria-map-id-9876543210"
    _com_google(monkeypatch, canaria_chave, canaria_map_id)
    with caplog.at_level(logging.DEBUG):
        r = sessao(ZE_UTILIZADOR).get(CONFIG_URL)
    assert canaria_chave in r.text and canaria_map_id in r.text
    assert canaria_chave not in caplog.text
    assert canaria_map_id not in caplog.text


def test_a_config_quando_a_base_falha_e_um_erro(sessao):
    definicoes = ColeccaoFalsa(
        [], unicos=unicos_declarados("crm_definicoes"), nome="crm_definicoes",
        falhar={"find": RuntimeError("base em baixo")},
    )
    base = BaseFalsa({"crm_membros": list(MEMBROS), "crm_definicoes": definicoes})
    assert sessao(ZE_UTILIZADOR, base, levantar=False).get(CONFIG_URL).status_code == 500


def test_a_rota_le_as_variaveis_pelo_modulo(monkeypatch):
    """A chave e o Map ID leem-se por `chave_navegador()` e `map_id_google()`,
    a cada chamada ("" sem a variável)."""
    _com_google(monkeypatch, "x", "y")
    assert (modulo.chave_navegador(), modulo.map_id_google()) == ("x", "y")
    monkeypatch.delenv(VARIAVEL_CHAVE)
    monkeypatch.delenv(VARIAVEL_MAP_ID)
    assert (modulo.chave_navegador(), modulo.map_id_google()) == ("", "")


# --- De ponta a ponta: a sessão verdadeira do portal (SessaoMapaTest.php) ---------------------

SEGREDO = "segredo-de-teste-crm-config"
AGORA_TOKEN = int(time.time())


def _token(user_id, email="qualquer@example.com", role="colaborador"):
    dados = {"user_id": user_id, "email": email, "role": role, "iat": AGORA_TOKEN, "exp": AGORA_TOKEN + 3600}
    return jwt.encode(dados, SEGREDO, algorithm="HS256")


def _cabecalho(user_id, **kw):
    return {"Authorization": f"Bearer {_token(user_id, **kw)}"}


@pytest.fixture
def portal(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SEGREDO)
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    _com_google(monkeypatch)
    base = _base()
    monkeypatch.setattr(faturacao.auth, "obter_db", lambda: base)
    monkeypatch.setattr(crm.db, "obter_db", lambda: base)
    app = FastAPI()
    app.include_router(crm.router)
    cliente = TestClient(app)
    cliente.base = base
    return cliente


def test_sem_sessao_nao_vem_o_mapa(portal):
    """`semSessaoNaoVemOMapa`: o 403 herdado, sem a chave nem o Map ID."""
    r = portal.get(CONFIG_URL)
    assert (r.status_code, r.json()) == (403, {"detail": "Not authenticated"})
    assert CHAVE not in r.text and MAP_ID not in r.text
    assert portal.base.crm_definicoes.registo == []


def test_uma_conta_apagada_da_401_sessao_terminada(portal):
    r = portal.get(CONFIG_URL, headers=_cabecalho("u-apagada"))
    assert (r.status_code, r.json()) == (401, {"detail": "Sessão terminada"})
    assert CHAVE not in r.text and MAP_ID not in r.text


def test_o_centro_vem_das_definicoes_guardadas_pelo_admin(portal):
    """`oCentroVemDasDefinicoesGuardadas`: o admin muda o ponto da fábrica e
    o mapa do Zé (utilizador) passa a centrar-se lá."""
    admin = _cabecalho("u-admin", email=ADMIN_LOCAL, role="admin")
    ze = _cabecalho("u-ze")
    assert portal.get(CONFIG_URL, headers=ze).json() == CONFIG_COM_GOOGLE

    r = portal.patch(DEFINICOES_URL, json={"fabrica_lat": 41.1496, "fabrica_lng": -8.611}, headers=admin)
    assert r.status_code == 200

    mapa = portal.get(CONFIG_URL, headers=ze).json()
    assert mapa["centro"] == {"lat": 41.1496, "lng": -8.611}
    assert mapa["google"] == {"chave": CHAVE, "map_id": MAP_ID}
