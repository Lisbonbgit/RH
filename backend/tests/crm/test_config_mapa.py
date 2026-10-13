"""`GET /api/crm/config` — a configuração do mapa: os mosaicos, a alternativa
e o centro (plano T2.13; dossiê §6 e §8).

Porta de tests/Unit/Http/ConfigMapaTest.php (todos os casos, com os nomes de
lá, sobre a função pura `config_mapa`) e de
tests/Integration/Api/SessaoMapaTest.php do CRM autónomo (etiqueta
`referencia-standalone`). Adaptações ao portal:

- Lá o "mapa" vinha dentro do `GET /api/sessao`; aqui é uma rota própria, para
  o escritório (admin e utilizador do CRM). O motorista só entra na F4; quem
  não é membro recebe 403 `sem_acesso_crm`; sem sessão, os 403/401 herdados.
- A chave dos mosaicos vem da variável `CRM_GEOAPIFY_CHAVE_MOSAICOS`, lida a
  cada pedido (não à importação): mudá-la no `.env` não pede outro código.
  Sem ela, ou vazia (o normal em local), os mosaicos são os do OSM.
- O modelo da Geoapify e a alternativa do OSM são constantes (lá vinham do
  ficheiro de configuração); a função pura continua a aceitá-los, para se
  portar o caso do modelo que já tem parâmetros.
"""
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
from crm.config_mapa import ALTERNATIVA, MODELO_MOSAICOS, VARIAVEL_CHAVE, config_mapa
from crm.pedidos import corpo_json
from faturacao.auth import utilizador_atual

from .duplos import BaseFalsa, ColeccaoFalsa, unicos_declarados

CONFIG_URL = "/api/crm/config"
DEFINICOES_URL = "/api/crm/definicoes"
ADMIN_LOCAL = "admin.local@example.com"

# Os do ConfigMapaTest.php, escritos à mão (não copiados do código).
MODELO = "https://maps.geoapify.com/v1/tile/osm-bright/{z}/{x}/{y}.png"
ALTERNATIVA_OSM = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
DEFINICOES = {"fabrica_morada": "", "fabrica_lat": 38.7223, "fabrica_lng": -9.1393}

PROJECAO_GUARDADA = {"_id": 0, "chave": 1, "valor": 1}

SEM_PERMISSAO = {"detail": {"codigo": "sem_permissao", "mensagem": "Sem permissão para esta ação."}}
SEM_ACESSO = {"detail": {"codigo": "sem_acesso_crm", "mensagem": "Sem acesso ao CRM."}}


# --- ConfigMapaTest.php: a função pura ---------------------------------------------------


def test_o_modelo_e_a_alternativa_sao_os_do_plano():
    assert MODELO_MOSAICOS == MODELO
    assert ALTERNATIVA == ALTERNATIVA_OSM
    assert VARIAVEL_CHAVE == "CRM_GEOAPIFY_CHAVE_MOSAICOS"


def test_com_chave_usa_os_mosaicos_geoapify_com_a_chave_na_url():
    """`comChaveUsaOsMosaicosGeoapifyComAChaveNaUrl`."""
    assert config_mapa("chave-teste-mosaicos", DEFINICOES) == {
        "mosaicos": {"url": MODELO + "?apiKey=chave-teste-mosaicos", "atribuicao": "geoapify"},
        "alternativa": {"url": ALTERNATIVA_OSM},
        "centro": {"lat": 38.7223, "lng": -9.1393},
    }


def test_sem_chave_a_url_principal_passa_a_ser_a_alternativa_com_atribuicao_osm():
    """`semChaveAUrlPrincipalPassaASerAAlternativaComAtribuicaoOsm`."""
    assert config_mapa("", DEFINICOES) == {
        "mosaicos": {"url": ALTERNATIVA_OSM, "atribuicao": "osm"},
        "alternativa": {"url": ALTERNATIVA_OSM},
        "centro": {"lat": 38.7223, "lng": -9.1393},
    }


def test_o_centro_vem_das_definicoes():
    """`oCentroVemDasDefinicoes`."""
    definicoes = {"fabrica_morada": "Rua A, Porto", "fabrica_lat": 41.1496, "fabrica_lng": -8.611}
    assert config_mapa("chave-teste-mosaicos", definicoes)["centro"] == {"lat": 41.1496, "lng": -8.611}


def test_um_modelo_que_ja_tem_parametros_recebe_a_chave_com_e():
    """`umModeloQueJaTemParametrosRecebeAChaveComE`."""
    resultado = config_mapa("chave-teste-mosaicos", DEFINICOES, modelo=MODELO + "?lang=pt")
    assert resultado["mosaicos"]["url"] == MODELO + "?lang=pt&apiKey=chave-teste-mosaicos"


def test_a_chave_vai_codificada_na_url():
    """`aChaveVaiCodificadaNaUrl`."""
    assert config_mapa("a b&c=d", DEFINICOES)["mosaicos"]["url"] == MODELO + "?apiKey=a%20b%26c%3Dd"


@pytest.mark.parametrize(
    "chave, codificada",
    [
        ("AZaz09-_.~", "AZaz09-_.~"),
        ("a/b+c", "a%2Fb%2Bc"),
        ("?#%:@!*'()", "%3F%23%25%3A%40%21%2A%27%28%29"),
        ("ção €", "%C3%A7%C3%A3o%20%E2%82%AC"),
        ("\udcff\udc80", "%FF%80"),
        (" ", "%20"),
    ],
    ids=["não reservados ficam", "barra e mais", "reservados", "UTF-8", "bytes que não são UTF-8 no ambiente",
         "só um espaço conta como chave"],
)
def test_a_chave_codifica_se_como_o_rawurlencode_do_php(chave, codificada):
    """O `rawurlencode` (RFC 3986): só `A-Za-z0-9-_.~` ficam; a barra também
    se codifica (o `quote` do Python, por omissão, deixava-a). Uma variável
    de ambiente com bytes que não são UTF-8 chega ao Python com surrogates
    (surrogateescape) e codifica-se byte a byte, como o PHP, sem rebentar."""
    assert config_mapa(chave, DEFINICOES)["mosaicos"] == {
        "url": MODELO + "?apiKey=" + codificada, "atribuicao": "geoapify",
    }


def test_as_chaves_saem_por_esta_ordem():
    for chave in ("k", ""):
        resultado = config_mapa(chave, DEFINICOES)
        assert list(resultado) == ["mosaicos", "alternativa", "centro"]
        assert list(resultado["mosaicos"]) == ["url", "atribuicao"]
        assert list(resultado["centro"]) == ["lat", "lng"]


def test_a_alternativa_vem_sempre_mesmo_com_um_modelo_proprio():
    """A alternativa vem sempre: o mapa muda para ela sozinho se os mosaicos
    falharem (mosaicos.js)."""
    resultado = config_mapa("k", DEFINICOES, modelo="http://outro/{z}/{x}/{y}.png", alternativa="http://alt/{z}.png")
    assert resultado["alternativa"] == {"url": "http://alt/{z}.png"}
    assert config_mapa("", DEFINICOES, alternativa="http://alt/{z}.png")["mosaicos"]["url"] == "http://alt/{z}.png"


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

CONFIG_SEM_CHAVE = {
    "mosaicos": {"url": ALTERNATIVA_OSM, "atribuicao": "osm"},
    "alternativa": {"url": ALTERNATIVA_OSM},
    "centro": {"lat": 38.7223, "lng": -9.1393},
}


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
    """Como em test_definicoes.py; a chave dos mosaicos começa SEMPRE fora do
    ambiente (o Mac do dono pode tê-la no shell)."""
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    monkeypatch.delenv(VARIAVEL_CHAVE, raising=False)

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


def test_a_rota_existe_e_vive_em_crm_config_mapa():
    rota = _rota()
    assert rota.methods == {"GET"}
    assert rota.endpoint.__module__ == "crm.config_mapa"


def test_e_do_escritorio_com_uma_so_guarda_e_sem_corpo():
    dependencias = _dependencias(_rota())
    assert membro_crm_atual in dependencias
    assert [d for d in dependencias if hasattr(d, "perfis_crm")] == [ESCRITORIO]
    assert corpo_json not in dependencias


def test_com_a_sessao_iniciada_vem_o_mapa_com_os_mosaicos_geoapify_e_o_centro_padrao(sessao, monkeypatch):
    """`comASessaoIniciadaVemOMapaComOsMosaicosGeoapifyEOCentroPadrao`: o Zé
    (utilizador) — o mapa não é só para o admin."""
    monkeypatch.setenv(VARIAVEL_CHAVE, "chave-teste-mosaicos")
    r = sessao(ZE_UTILIZADOR).get(CONFIG_URL)
    assert (r.status_code, r.json()) == (200, {
        "mosaicos": {"url": MODELO + "?apiKey=chave-teste-mosaicos", "atribuicao": "geoapify"},
        "alternativa": {"url": ALTERNATIVA_OSM},
        "centro": {"lat": 38.7223, "lng": -9.1393},
    })
    assert r.json()["mosaicos"]["url"].endswith("?apiKey=chave-teste-mosaicos")


def test_sem_a_variavel_vem_os_mosaicos_do_osm(sessao):
    """O normal em local (dossiê §8)."""
    r = sessao(ZE_UTILIZADOR).get(CONFIG_URL)
    assert (r.status_code, r.json()) == (200, CONFIG_SEM_CHAVE)


def test_com_a_variavel_vazia_vem_os_mosaicos_do_osm(sessao, monkeypatch):
    monkeypatch.setenv(VARIAVEL_CHAVE, "")
    assert sessao(ZE_UTILIZADOR).get(CONFIG_URL).json() == CONFIG_SEM_CHAVE


def test_a_chave_le_se_a_cada_pedido_e_nao_a_importacao(sessao, monkeypatch):
    cliente = sessao(ZE_UTILIZADOR)
    assert cliente.get(CONFIG_URL).json()["mosaicos"]["atribuicao"] == "osm"
    monkeypatch.setenv(VARIAVEL_CHAVE, "primeira")
    assert cliente.get(CONFIG_URL).json()["mosaicos"]["url"] == MODELO + "?apiKey=primeira"
    monkeypatch.setenv(VARIAVEL_CHAVE, "segunda")
    assert cliente.get(CONFIG_URL).json()["mosaicos"]["url"] == MODELO + "?apiKey=segunda"
    monkeypatch.delenv(VARIAVEL_CHAVE)
    assert cliente.get(CONFIG_URL).json() == CONFIG_SEM_CHAVE


def test_o_centro_vem_das_definicoes_guardadas(sessao):
    base = _base([_guardada("fabrica_lat", "41.149600"), _guardada("fabrica_lng", "-8.611000")])
    r = sessao(ZE_UTILIZADOR, base).get(CONFIG_URL)
    assert r.json()["centro"] == {"lat": 41.1496, "lng": -8.611}
    assert [type(v) for v in r.json()["centro"].values()] == [float, float]


def test_a_config_le_as_definicoes_uma_vez_e_so_a_chave_e_o_valor(sessao):
    cliente = sessao(ZE_UTILIZADOR, _base([_guardada("fabrica_lat", "41.149600")]))
    assert cliente.get(CONFIG_URL).status_code == 200
    assert cliente.base.crm_definicoes.registo == [("find", {}, PROJECAO_GUARDADA)]


def test_uma_definicao_estragada_nao_parte_o_mapa(sessao):
    """Todo o escritório abre o mapa: uma linha estragada à mão em
    crm_definicoes fica de fora e o centro volta ao padrão."""
    base = _base([{"chave": "fabrica_lat", "valor": None}, _guardada("fabrica_lng", "-8.611000")])
    r = sessao(ZE_UTILIZADOR, base).get(CONFIG_URL)
    assert (r.status_code, r.json()["centro"]) == (200, {"lat": 38.7223, "lng": -8.611})


@pytest.mark.parametrize(
    "utilizador", [ADMIN_MASTER, ANA_ADMIN_DO_CRM, ZE_UTILIZADOR], ids=["admin master", "admin", "utilizador"]
)
def test_o_escritorio_ve_a_config(sessao, utilizador):
    assert sessao(utilizador).get(CONFIG_URL).status_code == 200


def test_o_motorista_nao_ve_a_config_na_f2(sessao, monkeypatch):
    """As permissões do terreno chegam na F4 (plano §1, "Perfis por rota");
    e a chave dos mosaicos só vai para quem pode abrir o mapa."""
    monkeypatch.setenv(VARIAVEL_CHAVE, "chave-teste-mosaicos")
    cliente = sessao(ALVARO_MOTORISTA)
    r = cliente.get(CONFIG_URL)
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)
    assert "chave-teste-mosaicos" not in r.text
    assert cliente.base.crm_definicoes.registo == []


def test_quem_nao_e_membro_nao_ve_a_config(sessao, monkeypatch):
    monkeypatch.setenv(VARIAVEL_CHAVE, "chave-teste-mosaicos")
    cliente = sessao(BEA_NAO_MEMBRO)
    r = cliente.get(CONFIG_URL)
    assert (r.status_code, r.json()) == (403, SEM_ACESSO)
    assert "chave-teste-mosaicos" not in r.text
    assert cliente.base.crm_definicoes.registo == []


def test_a_chave_dos_mosaicos_nao_vai_para_os_registos(sessao, monkeypatch, caplog):
    canaria = "canaria-mosaicos-0123456789"
    monkeypatch.setenv(VARIAVEL_CHAVE, canaria)
    with caplog.at_level(logging.DEBUG):
        r = sessao(ZE_UTILIZADOR).get(CONFIG_URL)
    assert canaria in r.text
    assert canaria not in caplog.text


def test_a_config_quando_a_base_falha_e_um_erro(sessao):
    definicoes = ColeccaoFalsa(
        [], unicos=unicos_declarados("crm_definicoes"), nome="crm_definicoes",
        falhar={"find": RuntimeError("base em baixo")},
    )
    base = BaseFalsa({"crm_membros": list(MEMBROS), "crm_definicoes": definicoes})
    assert sessao(ZE_UTILIZADOR, base, levantar=False).get(CONFIG_URL).status_code == 500


def test_a_rota_le_a_chave_pelo_modulo(monkeypatch):
    """A chave lê-se por `chave_mosaicos()`, a cada chamada."""
    monkeypatch.setenv(VARIAVEL_CHAVE, "x")
    assert modulo.chave_mosaicos() == "x"
    monkeypatch.delenv(VARIAVEL_CHAVE)
    assert modulo.chave_mosaicos() == ""


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
    monkeypatch.setenv(VARIAVEL_CHAVE, "chave-teste-mosaicos")
    base = _base()
    monkeypatch.setattr(faturacao.auth, "obter_db", lambda: base)
    monkeypatch.setattr(crm.db, "obter_db", lambda: base)
    app = FastAPI()
    app.include_router(crm.router)
    cliente = TestClient(app)
    cliente.base = base
    return cliente


def test_sem_sessao_nao_vem_o_mapa(portal):
    """`semSessaoNaoVemOMapa`: o 403 herdado, sem a chave."""
    r = portal.get(CONFIG_URL)
    assert (r.status_code, r.json()) == (403, {"detail": "Not authenticated"})
    assert portal.base.crm_definicoes.registo == []


def test_uma_conta_apagada_da_401_sessao_terminada(portal):
    r = portal.get(CONFIG_URL, headers=_cabecalho("u-apagada"))
    assert (r.status_code, r.json()) == (401, {"detail": "Sessão terminada"})
    assert "chave-teste-mosaicos" not in r.text


def test_o_centro_vem_das_definicoes_guardadas_pelo_admin(portal):
    """`oCentroVemDasDefinicoesGuardadas`: o admin muda o ponto da fábrica e
    o mapa do Zé (utilizador) passa a centrar-se lá."""
    admin = _cabecalho("u-admin", email=ADMIN_LOCAL, role="admin")
    ze = _cabecalho("u-ze")
    assert portal.get(CONFIG_URL, headers=ze).json()["centro"] == {"lat": 38.7223, "lng": -9.1393}

    r = portal.patch(DEFINICOES_URL, json={"fabrica_lat": 41.1496, "fabrica_lng": -8.611}, headers=admin)
    assert r.status_code == 200

    mapa = portal.get(CONFIG_URL, headers=ze).json()
    assert mapa["centro"] == {"lat": 41.1496, "lng": -8.611}
    assert mapa["mosaicos"] == {"url": MODELO + "?apiKey=chave-teste-mosaicos", "atribuicao": "geoapify"}
