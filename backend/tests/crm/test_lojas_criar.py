"""`/api/crm/lojas` — criar, listar e ler lojas (plano T2.10; dossiê §5.2, §5.5 e §6).

Porta de tests/Integration/Api/LojasCriarTest.php do CRM autónomo (etiqueta
`referencia-standalone`): todos os casos, com os nomes de lá, e os dados dos
`DataProvider` com os mesmos nomes. Adaptações ao portal:

- só o escritório (admin e utilizador do CRM; o motorista ganha o POST na
  F4) — lá "qualquer pessoa com sessão". Sem sessão, os 403/401 herdados do
  portal em vez do 401 `nao_autenticado` do autónomo;
- ids uuid4 em texto (lá inteiros), também o `regiao_id` e o `criado_por`
  (o `user_id` do portal);
- as lojas "inseridas por SQL" (`lojaPorSql`, `LojasTeste::criar`) são
  documentos escritos à mão no duplo, com a forma da base (plano §3: `loc`
  GeoJSON, janelas em lista), criados a 2026-10-03 09:00 UTC com a versão
  `2026-10-03T09:00:00.250000Z`;
- sem transações: a região verifica-se com `find_one` antes dos duplicados e
  da escrita (corrida residual aceite, dossiê §3); os duplicados pelo
  pré-filtro `$geoWithin` (T2.3) — no duplo devolve todas as lojas com `loc`,
  e a regra exata dos 50 m é a do domínio;
- o `Cache-Control: no-store, private` do `aListaEOResumo…` não se porta
  (diferença assumida na T2.9, dossiê §5.8).

Rotas por `TestClient` com `dependency_overrides[utilizador_atual]` e
`monkeypatch.setattr(crm.db, "obter_db", …)` (plano §10), com o relógio parado
(`relogio.agora`); as corridas com `correr` (nunca `asyncio.run`); no fim, de
ponta a ponta com a sessão verdadeira do portal (JWT + conta lida da base).
"""
import asyncio
import re
import time
from datetime import datetime, timezone

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import crm
import crm.db
import faturacao.auth
from crm import lojas as rotas_lojas
from crm import relogio
from crm.auth import ESCRITORIO, membro_crm_atual
from crm.dominio.geo import filtro_candidatos
from crm.pedidos import corpo_json
from faturacao.auth import utilizador_atual

from .duplos import BaseFalsa, ColeccaoFalsa, correr
from .formatos import instantes_fora_do_formato

LOJAS_URL = "/api/crm/lojas"
UMA_LOJA_URL = "/api/crm/lojas/{loja_id}"
ADMIN_LOCAL = "admin.local@example.com"
JSON = {"Content-Type": "application/json"}

UTC = timezone.utc
AGORA = datetime(2026, 10, 10, 9, 30, 15, 987654, tzinfo=UTC)
AGORA_INSTANTE = "2026-10-10T09:30:15Z"
AGORA_CARIMBO = "2026-10-10T09:30:15.987654Z"
AGORA_DO_RELOGIO = relogio.agora  # o verdadeiro, antes de qualquer monkeypatch

# Rua Augusta, em Lisboa. Os outros pontos medem-se a partir daqui, para norte (1 m ≈ 0,000009°).
LAT = 38.710800
LNG = -9.136900
# Um place ID como a Google os dá (o do exemplo da documentação); vai tal e qual.
PLACE = "ChIJN1t_tDeuEmsRUsoyG83frY4"

# A forma das lojas "inseridas por SQL" (LojasTeste).
CRIADA_EM = "2026-10-03T09:00:00Z"
VERSAO = "2026-10-03T09:00:00.250000Z"

INSTANTE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
INSTANTE_MICRO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z")
UUID4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")

VALIDACAO = "Verifique os campos assinalados."
NAO_ENCONTRADA = {"detail": {"codigo": "nao_encontrado", "mensagem": "Loja não encontrada."}}
JSON_INVALIDO = {"detail": {"codigo": "json_invalido", "mensagem": "O pedido não é JSON válido."}}
SEM_PERMISSAO = {"detail": {"codigo": "sem_permissao", "mensagem": "Sem permissão para esta ação."}}
SEM_ACESSO = {"detail": {"codigo": "sem_acesso_crm", "mensagem": "Sem acesso ao CRM."}}

PROJECAO_RESUMO = {
    "_id": 0, "id": 1, "nome": 1, "fase": 1, "regiao_id": 1, "lat": 1, "lng": 1, "telefone": 1, "pessoa_contacto": 1,
}
PROJECAO_CANDIDATO = {"_id": 0, "id": 1, "nome": 1, "lat": 1, "lng": 1}
PROJECAO_ID = {"_id": 0, "id": 1}


def _id(n):
    """Um uuid4 em texto, fixo para os testes serem legíveis."""
    return f"00000000-0000-4000-8000-{n:012d}"


LISBOA, PORTO = _id(901), _id(902)
NAO_EXISTE = _id(999)


def _validacao(campos):
    return {"detail": {"codigo": "validacao", "mensagem": VALIDACAO, "campos": campos}}


def _regiao(regiao_id, nome):
    return {"id": regiao_id, "nome": nome, "nome_chave": nome.lower(), "ordem": 0}


def _loja(numero, nome, lat, lng=LNG, **outros):
    """Uma loja escrita à mão na base (o `lojaPorSql`/`LojasTeste::criar`), na
    longitude de referência, criada a 2026-10-03 09:00 UTC."""
    return {
        "id": _id(numero),
        "nome": nome,
        "fase": "potencial",
        "fase_desde": CRIADA_EM,
        "regiao_id": None,
        "morada": None,
        "codigo_postal": None,
        "localidade": None,
        "lat": lat,
        "lng": lng,
        "loc": {"type": "Point", "coordinates": [lng, lat]},
        "origem_coords": "pin_manual",
        "precisao_m": None,
        "google_place_id": None,
        "telefone": None,
        "pessoa_contacto": None,
        "instagram": None,
        "site": None,
        "notas": None,
        "janelas": [],
        "dias_fechada": [],
        "visita_pendente_motivo": None,
        "visita_pendente_desde": None,
        "ultima_interacao_em": None,
        "ultima_visita_ou_entrega_em": None,
        "criado_por": None,
        "criado_em": CRIADA_EM,
        "atualizado_em": VERSAO,
        **outros,
    }


def _minima(**outros):
    """Só os obrigatórios, no ponto de referência."""
    return {
        "nome": "Café Central", "fase": "potencial", "lat": LAT, "lng": LNG, "origem_coords": "pin_manual", **outros,
    }


USERS = [
    {"id": "u-admin", "email": ADMIN_LOCAL, "name": "Administrador Principal", "role": "admin",
     "password": "$2b$12$hash-do-admin"},
    {"id": "u-rui", "email": "rui@example.com", "name": "Rui Costa", "role": "colaborador",
     "password": "$2b$12$hash-do-rui"},
    {"id": "u-ana", "email": "ana@example.com", "name": "Ana Reis", "role": "contabilista",
     "password": "$2b$12$hash-da-ana"},
    {"id": "u-alv", "email": "alvaro@example.com", "name": "Álvaro Costa", "role": "gerente",
     "password": "$2b$12$hash-do-alvaro"},
    {"id": "u-bea", "email": "bea@example.com", "name": "Beatriz Lopes", "role": "colaborador",
     "password": "$2b$12$hash-da-bea"},
]
MEMBROS = [
    {"id": "m-rui", "user_id": "u-rui", "perfil": "utilizador", "criado_em": "2026-10-01T09:00:00Z"},
    {"id": "m-ana", "user_id": "u-ana", "perfil": "admin", "criado_em": "2026-10-01T09:00:00Z"},
    {"id": "m-alv", "user_id": "u-alv", "perfil": "motorista", "criado_em": "2026-10-02T09:00:00Z"},
    {"id": "m-apagada", "user_id": "u-apagada", "perfil": "utilizador", "criado_em": "2026-09-30T09:00:00Z"},
]

ADMIN_MASTER = {"user_id": "u-admin", "email": ADMIN_LOCAL, "role": "admin"}
RUI_UTILIZADOR = {"user_id": "u-rui", "email": "rui@example.com", "role": "colaborador"}
ANA_ADMIN_DO_CRM = {"user_id": "u-ana", "email": "ana@example.com", "role": "contabilista"}
ALVARO_MOTORISTA = {"user_id": "u-alv", "email": "alvaro@example.com", "role": "gerente"}
BEA_NAO_MEMBRO = {"user_id": "u-bea", "email": "bea@example.com", "role": "colaborador"}


def _base(lojas=(), regioes=()):
    return BaseFalsa({
        "crm_membros": list(MEMBROS),
        "users": list(USERS),
        "crm_regioes": list(regioes),
        "crm_lojas": list(lojas),
    })


def _escritas(base):
    """As escritas em `crm_lojas` e `crm_regioes`, pela ordem."""
    return [
        c
        for coleccao in (base.crm_lojas, base.crm_regioes)
        for c in coleccao.registo
        if c[0] in ("insert_one", "update_one", "delete_one", "delete_many")
    ]


def _rota(caminho, metodo):
    achadas = [
        r for r in crm.router.routes
        if getattr(r, "path", None) == caminho and metodo in getattr(r, "methods", ())
    ]
    assert achadas, f"{metodo} {caminho} não está no router do CRM"
    assert len(achadas) == 1
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
    """Uma app só com o router do CRM, a sessão do portal trocada por
    `dependency_overrides`, a base do CRM trocada pelo único ponto e o
    relógio parado em AGORA. `sessao(utilizador, base)` devolve o cliente
    (com `cliente.base`)."""
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    monkeypatch.setattr(relogio, "agora", lambda: AGORA)

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


# --- As rotas: onde estão, quem as guarda e por que ordem -------------------------------


ROTAS = [("GET", LOJAS_URL), ("POST", LOJAS_URL), ("GET", UMA_LOJA_URL)]
IDS_ROTAS = ["listar", "criar", "ler"]


@pytest.mark.parametrize("metodo, caminho", ROTAS, ids=IDS_ROTAS)
def test_as_rotas_existem_vivem_em_crm_lojas_e_sao_do_escritorio(metodo, caminho):
    rota = _rota(caminho, metodo)
    assert rota.methods == {metodo}
    assert rota.endpoint.__module__ == "crm.lojas"
    dependencias = _dependencias(rota)
    assert membro_crm_atual in dependencias
    assert [d for d in dependencias if hasattr(d, "perfis_crm")] == [ESCRITORIO]


def test_criar_responde_201():
    assert _rota(LOJAS_URL, "POST").status_code == 201


def test_criar_tem_a_guarda_de_perfil_antes_do_corpo():
    """Correções do plano, linha "T1.3 / T2.15"."""
    assert [d.call for d in _rota(LOJAS_URL, "POST").dependant.dependencies] == [ESCRITORIO, corpo_json]


@pytest.mark.parametrize("metodo, caminho", [("GET", LOJAS_URL), ("GET", UMA_LOJA_URL)], ids=["listar", "ler"])
def test_listar_e_ler_nao_leem_o_corpo(metodo, caminho):
    assert corpo_json not in _dependencias(_rota(caminho, metodo))


# --- POST /lojas -------------------------------------------------------------------------------


def test_criar_devolve_201_com_a_loja_completa(sessao):
    """`criarDevolve201ComALojaCompleta`."""
    cliente = sessao(RUI_UTILIZADOR, _base(regioes=[_regiao(LISBOA, "Lisboa")]))
    r = cliente.post(LOJAS_URL, json={
        "nome": "  Café Central ",
        "fase": "amostra",
        "regiao_id": LISBOA,
        "morada": "Rua Augusta 10",
        "codigo_postal": "1100-053",
        "localidade": "Lisboa",
        "lat": 38.7108004,
        "lng": -9.1369,
        "origem_coords": "gps",
        "precisao_m": 12.4,
        "google_place_id": PLACE,
        "telefone": "+351  912 345 678",
        "pessoa_contacto": "Rita",
        "instagram": "@cafe.central",
        "site": "cafecentral.pt",
        "notas": "Fecha em agosto.",
        "janela1_inicio": "10:00",
        "janela1_fim": "13:00",
        "janela2_inicio": "15:00",
        "janela2_fim": "19:00",
        "dias_fechada": ["dom", "sab"],
    })

    assert r.status_code == 201, r.text
    loja = r.json()
    assert UUID4.fullmatch(loja["id"])
    esperado = {
        "id": loja["id"],
        "nome": "Café Central",
        "fase": "amostra",
        "fase_desde": loja["criado_em"],
        "regiao_id": LISBOA,
        "morada": "Rua Augusta 10",
        "codigo_postal": "1100-053",
        "localidade": "Lisboa",
        "lat": 38.7108,
        "lng": -9.1369,
        "origem_coords": "gps",
        "precisao_m": 12,
        "google_place_id": PLACE,
        "telefone": "+351 912 345 678",
        "pessoa_contacto": "Rita",
        "instagram": "https://www.instagram.com/cafe.central/",
        "site": "https://cafecentral.pt",
        "notas": "Fecha em agosto.",
        "janela1_inicio": "10:00",
        "janela1_fim": "13:00",
        "janela2_inicio": "15:00",
        "janela2_fim": "19:00",
        "dias_fechada": ["sab", "dom"],
        "visita_pendente_motivo": None,
        "visita_pendente_desde": None,
        "ultima_interacao_em": None,
        "ultima_visita_ou_entrega_em": None,
        "criado_por": "u-rui",
        "criado_em": loja["criado_em"],
        "atualizado_em": loja["atualizado_em"],
    }
    assert list(loja.items()) == list(esperado.items())
    assert type(loja["precisao_m"]) is int
    assert INSTANTE.fullmatch(loja["criado_em"])
    assert INSTANTE_MICRO.fullmatch(loja["atualizado_em"])
    # Com o relógio parado: o mesmo instante, sem e com os microssegundos.
    assert (loja["criado_em"], loja["atualizado_em"]) == (AGORA_INSTANTE, AGORA_CARIMBO)
    assert '"lat":38.7108,"lng":-9.1369,' in r.text, "lat e lng vão como números."
    assert '"precisao_m":12,"google_place_id":"ChIJN1t_tDeuEmsRUsoyG83frY4",' in r.text


def test_criar_com_o_relogio_verdadeiro_da_o_instante_do_pedido(sessao, monkeypatch):
    """O `assertEntre` do autónomo: os instantes ficam entre o antes e o
    depois (com 1 s de folga: os instantes sem fração vêm cortados)."""
    cliente = sessao(RUI_UTILIZADOR)
    monkeypatch.setattr(relogio, "agora", AGORA_DO_RELOGIO)
    antes = relogio.agora().timestamp()
    r = cliente.post(LOJAS_URL, json=_minima())
    depois = relogio.agora().timestamp()

    assert r.status_code == 201, r.text
    loja = r.json()
    criado = datetime.strptime(loja["criado_em"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
    versao = datetime.strptime(loja["atualizado_em"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC).timestamp()
    assert antes - 1 <= criado <= depois + 1
    assert antes - 1 <= versao <= depois + 1
    assert loja["fase_desde"] == loja["criado_em"]


def test_a_loja_fica_gravada_como_a_api_a_devolve(sessao):
    """`aLojaFicaGravadaComoAApiADevolve`: o documento do Mongo (plano §3) e o
    GET /lojas/{id} igual ao 201."""
    cliente = sessao(RUI_UTILIZADOR)
    r = cliente.post(
        LOJAS_URL, json=_minima(dias_fechada=["seg", "dom"], janela1_inicio="09:30", janela1_fim="12:00")
    )
    assert r.status_code == 201, r.text
    criada = r.json()

    [gravada] = cliente.base.crm_lojas.sem_id()
    assert list(gravada.items()) == list({
        "id": criada["id"],
        "nome": "Café Central",
        "fase": "potencial",
        "fase_desde": AGORA_INSTANTE,
        "regiao_id": None,
        "morada": None,
        "codigo_postal": None,
        "localidade": None,
        "lat": 38.7108,
        "lng": -9.1369,
        "loc": {"type": "Point", "coordinates": [-9.1369, 38.7108]},
        "origem_coords": "pin_manual",
        "precisao_m": None,
        "google_place_id": None,
        "telefone": None,
        "pessoa_contacto": None,
        "instagram": None,
        "site": None,
        "notas": None,
        "janelas": [{"inicio": "09:30", "fim": "12:00"}],
        "dias_fechada": ["seg", "dom"],
        "visita_pendente_motivo": None,
        "visita_pendente_desde": None,
        "ultima_interacao_em": None,
        "ultima_visita_ou_entrega_em": None,
        "criado_por": "u-rui",
        "criado_em": AGORA_INSTANTE,
        "atualizado_em": AGORA_CARIMBO,
    }.items())
    # Correções do plano, linha "§1 Decisões (Tempo) / T2.8": o que se grava.
    assert instantes_fora_do_formato(gravada) == []

    lida = cliente.get(f"{LOJAS_URL}/{criada['id']}")
    assert lida.status_code == 200
    assert lida.json() == criada, "GET /lojas/{id} devolve o mesmo que o POST."
    assert list(lida.json()) == list(criada)


def test_so_com_os_obrigatorios_o_resto_fica_vazio(sessao):
    """`soComOsObrigatoriosORestoFicaVazio`."""
    r = sessao(RUI_UTILIZADOR).post(LOJAS_URL, json=_minima())
    assert r.status_code == 201, r.text
    loja = r.json()
    assert (loja["nome"], loja["fase"], loja["origem_coords"], loja["dias_fechada"]) == (
        "Café Central", "potencial", "pin_manual", [],
    )
    for campo in ("regiao_id", "morada", "codigo_postal", "localidade", "precisao_m", "google_place_id", "telefone",
                  "pessoa_contacto", "instagram", "site", "notas",
                  "janela1_inicio", "janela1_fim", "janela2_inicio", "janela2_fim"):
        assert loja[campo] is None, campo


def test_criar_com_o_identificador_do_lugar_grava_o_e_devolve_o(sessao):
    """Plano do mapa Google (G3): o `google_place_id` vai no bloco da
    localização com qualquer origem válida (aqui o pino arrastado, `pin_manual`),
    grava-se tal e qual a seguir à precisão e sai no 201 e no GET da loja."""
    cliente = sessao(RUI_UTILIZADOR)
    r = cliente.post(LOJAS_URL, json=_minima(google_place_id=PLACE))

    assert r.status_code == 201, r.text
    assert (r.json()["origem_coords"], r.json()["google_place_id"]) == ("pin_manual", PLACE)
    assert '"precisao_m":null,"google_place_id":"ChIJN1t_tDeuEmsRUsoyG83frY4",' in r.text
    [gravada] = cliente.base.crm_lojas.sem_id()
    assert gravada["google_place_id"] == PLACE
    assert list(gravada).index("google_place_id") == list(gravada).index("precisao_m") + 1
    lida = cliente.get(f"{LOJAS_URL}/{r.json()['id']}")
    assert (lida.status_code, lida.json()["google_place_id"]) == (200, PLACE)


def test_a_lista_nao_traz_o_identificador_do_lugar(sessao):
    """O resumo do mapa (`CAMPOS_RESUMO`) não muda: o `google_place_id` só vem na loja completa."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_loja(1, "Bar", 38.72, google_place_id=PLACE)]))
    r = cliente.get(LOJAS_URL)

    assert r.status_code == 200
    assert "google_place_id" not in r.json()[0]
    assert "google_place_id" not in PROJECAO_RESUMO
    assert cliente.base.crm_lojas.registo == [("find", {}, PROJECAO_RESUMO)]


def test_o_duplicado_a_menos_de_50_metros_aplica_se_mesmo_com_o_identificador_do_lugar(sessao):
    """A regra dos 50 m é sobre o pino posto pela pessoa (adenda §2.1): um
    negócio da Google ao lado de uma loja gravada dá 409 na mesma, nada se
    grava, e com `confirmar_duplicado` grava-se com o identificador."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_loja(1, "Bar a 10 m", 38.710710)]))

    r = cliente.post(LOJAS_URL, json=_minima(google_place_id=PLACE))
    assert r.status_code == 409
    assert r.json()["detail"]["codigo"] == "duplicado"
    assert len(cliente.base.crm_lojas.docs) == 1 and _escritas(cliente.base) == []

    r = cliente.post(LOJAS_URL, json=_minima(google_place_id=PLACE, confirmar_duplicado=True))
    assert r.status_code == 201, r.text
    assert r.json()["google_place_id"] == PLACE


def test_os_campos_que_o_servidor_decide_ignoram_se(sessao):
    """`osCamposQueOServidorDecideIgnoramSe`, mais os do modelo do portal
    (`_id`, `loc`, `janelas` em lista, `nome_chave`): nada disto vem do corpo."""
    cliente = sessao(RUI_UTILIZADOR)
    r = cliente.post(LOJAS_URL, json=_minima(
        id="999",
        _id="forjado",
        criado_por="u-bea",
        criado_em="2020-01-01T00:00:00Z",
        fase_desde="2020-01-01T00:00:00Z",
        atualizado_em="2020-01-01T00:00:00.000000Z",
        visita_pendente_motivo="amostra",
        visita_pendente_desde="2020-01-01T00:00:00Z",
        ultima_interacao_em="2020-01-01T00:00:00Z",
        ultima_visita_ou_entrega_em="2020-01-01T00:00:00Z",
        loc={"type": "Point", "coordinates": [0, 0]},
        janelas=[{"inicio": "01:00", "fim": "02:00"}],
    ))

    assert r.status_code == 201, r.text
    loja = r.json()
    assert UUID4.fullmatch(loja["id"]) and loja["id"] != "999"
    assert loja["criado_por"] == "u-rui"
    assert not loja["criado_em"].startswith("2020")
    assert loja["fase_desde"] == loja["criado_em"]
    assert not loja["atualizado_em"].startswith("2020")
    assert loja["visita_pendente_motivo"] is None
    assert loja["visita_pendente_desde"] is None
    assert loja["ultima_interacao_em"] is None
    assert loja["ultima_visita_ou_entrega_em"] is None
    assert loja["janela1_inicio"] is None

    [gravada] = cliente.base.crm_lojas.docs
    assert gravada["_id"] != "forjado"
    assert gravada["loc"] == {"type": "Point", "coordinates": [LNG, LAT]}
    assert gravada["janelas"] == []
    assert "confirmar_duplicado" not in gravada


INVALIDAS = [
    ("corpo vazio", {}, {
        "nome": "Indique o nome.",
        "fase": "Indique a fase.",
        "lat": "Coloque o pino no mapa.",
        "lng": "Coloque o pino no mapa.",
        "origem_coords": "Indique a origem das coordenadas.",
    }),
    ("fora de Portugal (Madeira)", _minima(lat=32.65, lng=-16.9), {
        "lat": "Fora de Portugal", "lng": "Fora de Portugal",
    }),
    ("GPS impreciso", _minima(origem_coords="gps", precisao_m=80), {
        "precisao_m": "Localização imprecisa — ajuste o pino",
    }),
    ("fase e telefone", _minima(fase="vip", telefone="12"), {
        "fase": "A fase não é válida.",
        "telefone": "O telefone tem de ter 9 a 15 algarismos (aceita + e espaços).",
    }),
    ("região que não é um id", _minima(regiao_id="2"), {"regiao_id": "A região não é válida."}),
    ("janela sem fim", _minima(janela1_inicio="10:00"), {"janela1_fim": "Indique também o fim."}),
    ("instagram e site (2026-10-13)", _minima(instagram="purple house", site="exemplo"), {
        "instagram": "O Instagram tem de ser um perfil válido (ex.: @purplehouse).",
        "site": "O site tem de ser um endereço válido (ex.: https://exemplo.pt).",
    }),
    ("origem google (só estado do seletor; nunca chega à base)",
     _minima(origem_coords="google", google_place_id=PLACE),
     {"origem_coords": "A origem das coordenadas não é válida."}),
    ("identificador do lugar na Google inválido", _minima(google_place_id="<b>x</b>"), {
        "google_place_id": "O identificador do lugar na Google não é válido.",
    }),
]


@pytest.mark.parametrize("corpo, campos", [c[1:] for c in INVALIDAS], ids=[c[0] for c in INVALIDAS])
def test_dados_invalidos_dao_422_com_os_campos(sessao, corpo, campos):
    """`dadosInvalidosDao422ComOsCampos`: e sem ler a base (nem a região, nem
    os duplicados)."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_loja(1, "Bar a 10 m", 38.710710)]))
    r = cliente.post(LOJAS_URL, json=corpo)

    assert (r.status_code, r.json()) == (422, _validacao(campos))
    assert list(r.json()["detail"]["campos"]) == list(campos)
    assert len(cliente.base.crm_lojas.docs) == 1
    assert cliente.base.crm_lojas.registo == []
    assert cliente.base.crm_regioes.registo == []


def test_uma_regiao_que_nao_existe_da_422_na_regiao(sessao):
    """`umaRegiaoQueNaoExisteDa422NaRegiao`."""
    cliente = sessao(RUI_UTILIZADOR, _base(regioes=[_regiao(LISBOA, "Lisboa")]))
    r = cliente.post(LOJAS_URL, json=_minima(regiao_id=NAO_EXISTE))

    assert (r.status_code, r.json()) == (422, _validacao({"regiao_id": "A região não existe."}))
    assert cliente.base.crm_lojas.docs == []
    assert _escritas(cliente.base) == []
    assert cliente.base.crm_regioes.registo == [("find_one", {"id": NAO_EXISTE}, PROJECAO_ID)]


def test_uma_regiao_que_existe_grava_se_com_a_loja(sessao):
    cliente = sessao(RUI_UTILIZADOR, _base(regioes=[_regiao(LISBOA, "Lisboa"), _regiao(PORTO, "Porto")]))
    r = cliente.post(LOJAS_URL, json=_minima(regiao_id=PORTO))

    assert r.status_code == 201, r.text
    assert r.json()["regiao_id"] == PORTO
    assert cliente.base.crm_lojas.docs[0]["regiao_id"] == PORTO


def test_sem_regiao_nao_se_procura_a_regiao(sessao):
    cliente = sessao(RUI_UTILIZADOR)
    assert cliente.post(LOJAS_URL, json=_minima(regiao_id=None)).status_code == 201
    assert cliente.base.crm_regioes.registo == []


def test_uma_loja_a_menos_de_50_metros_da_409_duplicado_e_nada_se_grava(sessao):
    """`umaLojaAMenosDe50MetrosDa409DuplicadoENadaSeGrava`."""
    a30 = _loja(1, "Mercearia a 30 m", 38.711070)
    a10 = _loja(2, "Bar a 10 m", 38.710710)
    a60 = _loja(3, "Talho a 60 m", 38.711340)
    a51 = _loja(4, "Padaria a 51 m", 38.711259)
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[a30, a10, a60, a51]))

    r = cliente.post(LOJAS_URL, json=_minima())

    assert r.status_code == 409
    assert r.json() == {"detail": {
        "codigo": "duplicado",
        "mensagem": "Já existe Bar a 10 m aqui — é a mesma?",
        "lojas": [
            {"id": a10["id"], "nome": "Bar a 10 m", "distancia_m": 10},
            {"id": a30["id"], "nome": "Mercearia a 30 m", "distancia_m": 30},
        ],
    }}
    assert list(r.json()["detail"]) == ["codigo", "mensagem", "lojas"]
    assert len(cliente.base.crm_lojas.docs) == 4
    assert _escritas(cliente.base) == []


def test_os_duplicados_procuram_se_pelo_pre_filtro_do_indice(sessao):
    """O `find` é o círculo de 60 m da T2.3, com só os campos que a regra dos
    50 m usa."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_loja(2, "Bar a 10 m", 38.710710)]))
    assert cliente.post(LOJAS_URL, json=_minima()).status_code == 409
    assert cliente.base.crm_lojas.registo == [("find", filtro_candidatos(LAT, LNG), PROJECAO_CANDIDATO)]


def test_a_49_metros_ainda_e_duplicado(sessao):
    """`a49MetrosAindaEDuplicado`."""
    a49 = _loja(1, "Quiosque", 38.711241)
    r = sessao(RUI_UTILIZADOR, _base(lojas=[a49])).post(LOJAS_URL, json=_minima())

    assert r.status_code == 409
    assert r.json()["detail"]["lojas"] == [{"id": a49["id"], "nome": "Quiosque", "distancia_m": 49}]


def test_a_49_virgula_7_metros_tambem_e_duplicado_e_nada_se_grava(sessao):
    """`a49Virgula7MetrosTambemEDuplicadoENadaSeGrava`: 0,000447° de latitude
    ≈ 49,70 m — menos de 50 m, mesmo que arredondado dê 50."""
    quiosque = _loja(1, "Quiosque", 38.711247)
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[quiosque]))
    r = cliente.post(LOJAS_URL, json=_minima())

    assert r.status_code == 409, r.text
    assert r.json()["detail"]["lojas"] == [{"id": quiosque["id"], "nome": "Quiosque", "distancia_m": 49}]
    assert len(cliente.base.crm_lojas.docs) == 1


def test_a_50_metros_ou_mais_nao_e_duplicado(sessao):
    """O raio do pré-filtro (60 m) apanha a loja a 51 m, mas a regra exata não."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_loja(1, "Padaria a 51 m", 38.711259)]))
    assert cliente.post(LOJAS_URL, json=_minima()).status_code == 201
    assert len(cliente.base.crm_lojas.docs) == 2


def test_com_confirmar_duplicado_grava_na_mesma(sessao):
    """`comConfirmarDuplicadoGravaNaMesma`: e nem se procuram os duplicados."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_loja(1, "Bar a 10 m", 38.710710)]))
    r = cliente.post(LOJAS_URL, json=_minima(confirmar_duplicado=True))

    assert r.status_code == 201, r.text
    assert r.json()["nome"] == "Café Central"
    assert len(cliente.base.crm_lojas.docs) == 2
    assert cliente.base.crm_lojas.chamadas("find") == []
    assert "confirmar_duplicado" not in cliente.base.crm_lojas.docs[1]


NAO_CONFIRMAM = [
    ("false", False),
    ('texto "true"', "true"),
    ("o número 1", 1),
    ("null", None),
    ("o número 1.0", 1.0),
    ("uma lista com true", [True]),
    ("um objeto", {"confirmar": True}),
]


@pytest.mark.parametrize("confirmar", [c[1] for c in NAO_CONFIRMAM], ids=[c[0] for c in NAO_CONFIRMAM])
def test_so_o_true_confirma_o_duplicado(sessao, confirmar):
    """`soOTrueConfirmaODuplicado` (em Python, `1 == True`: compara-se com `is True`)."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_loja(1, "Bar a 10 m", 38.710710)]))
    r = cliente.post(LOJAS_URL, json=_minima(confirmar_duplicado=confirmar))

    assert r.status_code == 409
    assert len(cliente.base.crm_lojas.docs) == 1


def test_a_regiao_verifica_se_antes_dos_duplicados(sessao):
    """`aRegiaoVerificaSeAntesDosDuplicados`."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_loja(1, "Bar a 10 m", 38.710710)]))
    r = cliente.post(LOJAS_URL, json=_minima(regiao_id=_id(5)))

    assert r.status_code == 422
    assert r.json()["detail"]["campos"] == {"regiao_id": "A região não existe."}
    assert cliente.base.crm_lojas.registo == []


def test_a_regiao_verifica_se_mesmo_com_o_duplicado_confirmado(sessao):
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_loja(1, "Bar a 10 m", 38.710710)]))
    r = cliente.post(LOJAS_URL, json=_minima(regiao_id=_id(5), confirmar_duplicado=True))
    assert (r.status_code, r.json()) == (422, _validacao({"regiao_id": "A região não existe."}))
    assert len(cliente.base.crm_lojas.docs) == 1


def test_os_numeros_inteiros_gravam_se_em_float_e_a_precisao_em_inteiro(sessao):
    """O `json.loads` dá `int` a um 39; a base e a API ficam com 39.0 (o
    `(float)` do PHP), e a precisão do GPS sempre em metros inteiros."""
    cliente = sessao(RUI_UTILIZADOR)
    r = cliente.post(LOJAS_URL, json=_minima(lat=39, lng=-8, origem_coords="gps", precisao_m=12.5))

    assert r.status_code == 201, r.text
    assert '"lat":39.0,"lng":-8.0,' in r.text
    assert '"precisao_m":13,' in r.text
    [gravada] = cliente.base.crm_lojas.docs
    assert [type(gravada["lat"]), type(gravada["lng"]), type(gravada["precisao_m"])] == [float, float, int]
    assert gravada["loc"] == {"type": "Point", "coordinates": [-8.0, 39.0]}


def test_a_resposta_do_criar_nunca_traz_o_id_do_mongo_o_loc_nem_as_janelas_em_lista(sessao):
    r = sessao(RUI_UTILIZADOR).post(LOJAS_URL, json=_minima())
    assert r.status_code == 201
    assert {"_id", "loc", "janelas", "confirmar_duplicado"}.isdisjoint(r.json())


@pytest.mark.parametrize(
    "bruto", [b"[]", b"null", b'"loja"', b"{partido", b'{"nome": "Caf\\ud800"}'],
    ids=["lista", "null", "texto", "partido", "surrogate sozinho"],
)
def test_criar_com_um_corpo_que_nao_e_um_objeto_json_da_400(sessao, bruto):
    cliente = sessao(RUI_UTILIZADOR)
    r = cliente.post(LOJAS_URL, content=bruto, headers=JSON)
    assert (r.status_code, r.json()) == (400, JSON_INVALIDO)
    assert cliente.base.crm_lojas.registo == []


def test_criar_quando_a_base_falha_e_um_erro(sessao):
    base = BaseFalsa({
        "crm_membros": list(MEMBROS),
        "crm_lojas": ColeccaoFalsa(falhar={"insert_one": RuntimeError("base em baixo")}),
    })
    assert sessao(RUI_UTILIZADOR, base, levantar=False).post(LOJAS_URL, json=_minima()).status_code == 500


def test_duas_lojas_no_mesmo_sitio_ao_mesmo_tempo_gravam_se_as_duas(monkeypatch):
    """Dois pedidos no mesmo instante e no mesmo sítio podem gravar-se os dois:
    o duplicado é um aviso, não uma regra da base (docstring do
    `LojasControlador`). Fica provado e documentado, não escondido."""
    base = _base()
    monkeypatch.setattr(crm.db, "obter_db", lambda: base)
    monkeypatch.setattr(relogio, "agora", lambda: AGORA)
    membro = {**RUI_UTILIZADOR, "crm_perfil": "utilizador", "crm_admin_master": False}

    async def _as_duas():
        return await asyncio.gather(
            rotas_lojas.criar_loja(membro, _minima(nome="Café A")),
            rotas_lojas.criar_loja(membro, _minima(nome="Café B")),
        )

    a, b = correr(_as_duas())
    assert {a["nome"], b["nome"]} == {"Café A", "Café B"}
    assert len(base.crm_lojas.docs) == 2


# --- Quem pode -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "utilizador", [ADMIN_MASTER, ANA_ADMIN_DO_CRM, RUI_UTILIZADOR], ids=["admin master", "admin", "utilizador"]
)
def test_o_escritorio_cria_lista_e_le(sessao, utilizador):
    cliente = sessao(utilizador)
    r = cliente.post(LOJAS_URL, json=_minima())
    assert r.status_code == 201, r.text
    assert r.json()["criado_por"] == utilizador["user_id"]
    assert [loja["id"] for loja in cliente.get(LOJAS_URL).json()] == [r.json()["id"]]
    assert cliente.get(f"{LOJAS_URL}/{r.json()['id']}").json() == r.json()


TODAS = [("GET", LOJAS_URL, None), ("POST", LOJAS_URL, _minima()), ("GET", f"{LOJAS_URL}/{_id(1)}", None)]


def _pedir(cliente, metodo, url, corpo, headers=None):
    if corpo is None:
        return cliente.request(metodo, url, headers=headers)
    return cliente.request(metodo, url, json=corpo, headers=headers)


@pytest.mark.parametrize("metodo, url, corpo", TODAS, ids=IDS_ROTAS)
def test_o_motorista_nao_mexe_nas_lojas_na_f2(sessao, metodo, url, corpo):
    """As permissões do terreno chegam na F4 (plano §1, "Perfis por rota")."""
    cliente = sessao(ALVARO_MOTORISTA, _base(lojas=[_loja(1, "Bar", 38.72)]))
    r = _pedir(cliente, metodo, url, corpo)
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)
    assert cliente.base.crm_lojas.registo == []


@pytest.mark.parametrize("metodo, url, corpo", TODAS, ids=IDS_ROTAS)
def test_quem_nao_e_membro_recebe_403_sem_acesso(sessao, metodo, url, corpo):
    cliente = sessao(BEA_NAO_MEMBRO, _base(lojas=[_loja(1, "Bar", 38.72)]))
    r = _pedir(cliente, metodo, url, corpo)
    assert (r.status_code, r.json()) == (403, SEM_ACESSO)
    assert cliente.base.crm_lojas.registo == []


@pytest.mark.parametrize(
    "utilizador, esperado", [(ALVARO_MOTORISTA, SEM_PERMISSAO), (BEA_NAO_MEMBRO, SEM_ACESSO)],
    ids=["motorista", "não membro"],
)
def test_sem_perfil_e_com_json_partido_da_403_e_nunca_400(sessao, utilizador, esperado):
    r = sessao(utilizador).post(LOJAS_URL, content=b"[", headers=JSON)
    assert (r.status_code, r.json()) == (403, esperado)


# --- GET /lojas e GET /lojas/{id} ------------------------------------------------------------------


def test_a_lista_e_o_resumo_de_todas_as_lojas_por_nome(sessao):
    """`aListaEOResumoDeTodasAsLojasPorNome` (sem maiúsculas nem acentos, como
    a collation do MariaDB)."""
    cafe = _loja(1, "Café Central", 38.720000, fase="cliente", regiao_id=LISBOA,
                 telefone="+351 912 345 678", pessoa_contacto="D. Amélia", notas="Não aparece no resumo.",
                 instagram="https://www.instagram.com/cafecentral/", site="https://cafecentral.pt")
    acai = _loja(2, "Açaí da Esquina", 38.730000, fase="perdida", pessoa_contacto="Sr. Rui")
    bar = _loja(3, "bar do Rui", 38.740000)
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[cafe, acai, bar], regioes=[_regiao(LISBOA, "Lisboa")]))

    r = cliente.get(LOJAS_URL)

    assert r.status_code == 200
    assert r.json() == [
        {"id": acai["id"], "nome": "Açaí da Esquina", "fase": "perdida", "regiao_id": None, "lat": 38.73,
         "lng": -9.1369, "telefone": None, "pessoa_contacto": "Sr. Rui"},
        {"id": bar["id"], "nome": "bar do Rui", "fase": "potencial", "regiao_id": None, "lat": 38.74,
         "lng": -9.1369, "telefone": None, "pessoa_contacto": None},
        {"id": cafe["id"], "nome": "Café Central", "fase": "cliente", "regiao_id": LISBOA, "lat": 38.72,
         "lng": -9.1369, "telefone": "+351 912 345 678", "pessoa_contacto": "D. Amélia"},
    ]
    assert [list(loja) for loja in r.json()] == [
        ["id", "nome", "fase", "regiao_id", "lat", "lng", "telefone", "pessoa_contacto"],
    ] * 3


def test_a_lista_pede_so_os_campos_do_resumo(sessao):
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_loja(1, "Bar", 38.72)]))
    assert cliente.get(LOJAS_URL).status_code == 200
    assert cliente.base.crm_lojas.registo == [("find", {}, PROJECAO_RESUMO)]


def test_a_lista_desempata_pelo_id_quando_o_nome_e_igual(sessao):
    lojas = [_loja(3, "Bar", 38.72), _loja(1, "BAR", 38.73), _loja(2, "bár", 38.74)]
    r = sessao(RUI_UTILIZADOR, _base(lojas=lojas)).get(LOJAS_URL)
    assert [loja["id"] for loja in r.json()] == [_id(1), _id(2), _id(3)]


def test_sem_lojas_a_lista_vem_vazia(sessao):
    """`semLojasAListaVemVazia`."""
    r = sessao(RUI_UTILIZADOR).get(LOJAS_URL)
    assert (r.status_code, r.text) == (200, "[]")


def test_ler_uma_loja_gravada_na_base_devolve_os_valores_da_api(sessao):
    """`lerUmaLojaGravadaPorSqlDevolveOsValoresDaApi`: uma loja escrita à mão na
    base (os dias fora da ordem da semana) lê-se com os valores da API."""
    loja = _loja(
        1, "Café Central", 38.720000,
        janelas=[{"inicio": "10:00", "fim": "13:00"}],
        dias_fechada=["dom", "seg"],
        precisao_m=7,
        origem_coords="gps",
    )
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[loja]))

    r = cliente.get(f"{LOJAS_URL}/{_id(1)}")

    assert r.status_code == 200
    lida = r.json()
    assert lida["fase_desde"] == "2026-10-03T09:00:00Z"
    assert lida["criado_em"] == "2026-10-03T09:00:00Z"
    assert lida["atualizado_em"] == "2026-10-03T09:00:00.250000Z"
    assert lida["janela1_inicio"] == "10:00"
    assert lida["janela1_fim"] == "13:00"
    assert lida["janela2_inicio"] is None
    assert lida["dias_fechada"] == ["seg", "dom"], "Pela ordem da semana."
    assert lida["precisao_m"] == 7
    assert lida["lat"] == 38.72
    assert lida["criado_por"] is None
    assert cliente.base.crm_lojas.registo == [("find_one", {"id": _id(1)}, {"_id": 0})]


@pytest.mark.parametrize("loja_id", ["999", NAO_EXISTE], ids=["número", "uuid"])
def test_uma_loja_que_nao_existe_da_404(sessao, loja_id):
    """`umaLojaQueNaoExisteDa404`."""
    r = sessao(RUI_UTILIZADOR, _base(lojas=[_loja(1, "Bar", 38.72)])).get(f"{LOJAS_URL}/{loja_id}")
    assert (r.status_code, r.json()) == (404, NAO_ENCONTRADA)


def test_ler_e_listar_quando_a_base_falha_e_um_erro(sessao):
    base = BaseFalsa({
        "crm_membros": list(MEMBROS),
        "crm_lojas": ColeccaoFalsa([_loja(1, "Bar", 38.72)], falhar={"find_one": RuntimeError("x"),
                                                                      "find": RuntimeError("x")}),
    })
    cliente = sessao(RUI_UTILIZADOR, base, levantar=False)
    assert cliente.get(LOJAS_URL).status_code == 500
    assert cliente.get(f"{LOJAS_URL}/{_id(1)}").status_code == 500


# --- De ponta a ponta: a sessão verdadeira do portal ---------------------------------------------

SEGREDO = "segredo-de-teste-crm-lojas"
AGORA_TOKEN = int(time.time())


def _token(user_id, email="qualquer@example.com", role="colaborador"):
    dados = {"user_id": user_id, "email": email, "role": role, "iat": AGORA_TOKEN, "exp": AGORA_TOKEN + 3600}
    return jwt.encode(dados, SEGREDO, algorithm="HS256")


def _cabecalho(user_id, **kw):
    return {"Authorization": f"Bearer {_token(user_id, **kw)}"}


@pytest.fixture
def portal(monkeypatch):
    """O router do CRM com a sessão verdadeira (faturacao.auth) e a mesma base
    falsa para o portal e para o CRM."""
    monkeypatch.setenv("JWT_SECRET", SEGREDO)
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    monkeypatch.setattr(relogio, "agora", lambda: AGORA)
    base = _base(lojas=[_loja(1, "Bar a 10 m", 38.710710)], regioes=[_regiao(LISBOA, "Lisboa")])
    monkeypatch.setattr(faturacao.auth, "obter_db", lambda: base)
    monkeypatch.setattr(crm.db, "obter_db", lambda: base)
    app = FastAPI()
    app.include_router(crm.router)
    cliente = TestClient(app)
    cliente.base = base
    return cliente


@pytest.mark.parametrize("metodo, url, corpo", TODAS, ids=IDS_ROTAS)
def test_sem_sessao_da_o_403_herdado_e_nada_se_grava(portal, metodo, url, corpo):
    """`semSessaoDa401ENadaSeGrava`: no portal, sem cabeçalho é o 403 do
    HTTPBearer (o frontend trata-o como sessão em falta)."""
    r = _pedir(portal, metodo, url, corpo)
    assert (r.status_code, r.json()) == (403, {"detail": "Not authenticated"})
    assert portal.base.crm_lojas.registo == []
    assert len(portal.base.crm_lojas.docs) == 1


def test_sem_cabecalho_e_com_json_partido_da_o_403_herdado_e_nunca_400(portal):
    r = portal.post(LOJAS_URL, content=b"[", headers=JSON)
    assert (r.status_code, r.json()) == (403, {"detail": "Not authenticated"})
    assert portal.base.users.registo == []


@pytest.mark.parametrize("metodo, url, corpo", TODAS, ids=IDS_ROTAS)
def test_uma_conta_apagada_da_401_sessao_terminada(portal, metodo, url, corpo):
    r = _pedir(portal, metodo, url, corpo, headers=_cabecalho("u-apagada"))
    assert (r.status_code, r.json()) == (401, {"detail": "Sessão terminada"})
    assert portal.base.crm_lojas.registo == []


def test_de_ponta_a_ponta_criar_avisar_do_duplicado_confirmar_listar_e_ler(portal):
    rui = _cabecalho("u-rui")
    alvaro = _cabecalho("u-alv")

    r = portal.post(LOJAS_URL, json=_minima(regiao_id=NAO_EXISTE), headers=rui)
    assert (r.status_code, r.json()) == (422, _validacao({"regiao_id": "A região não existe."}))

    r = portal.post(LOJAS_URL, json=_minima(regiao_id=LISBOA), headers=rui)
    assert r.status_code == 409
    assert r.json()["detail"]["lojas"] == [{"id": _id(1), "nome": "Bar a 10 m", "distancia_m": 10}]

    r = portal.post(LOJAS_URL, json=_minima(regiao_id=LISBOA, confirmar_duplicado=True), headers=alvaro)
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)

    r = portal.post(LOJAS_URL, json=_minima(regiao_id=LISBOA, confirmar_duplicado=True), headers=rui)
    assert r.status_code == 201, r.text
    criada = r.json()
    assert (criada["regiao_id"], criada["criado_por"], criada["criado_em"]) == (LISBOA, "u-rui", AGORA_INSTANTE)

    admin = _cabecalho("u-admin", email=ADMIN_LOCAL, role="admin")
    assert [loja["nome"] for loja in portal.get(LOJAS_URL, headers=admin).json()] == ["Bar a 10 m", "Café Central"]
    assert portal.get(f"{LOJAS_URL}/{criada['id']}", headers=admin).json() == criada
    assert portal.get(f"{LOJAS_URL}/{NAO_EXISTE}", headers=rui).json() == NAO_ENCONTRADA
    assert [instantes_fora_do_formato(d) for d in portal.base.crm_lojas.sem_id()] == [[], []]
