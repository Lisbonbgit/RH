"""`PATCH /api/crm/lojas/{loja_id}` — editar uma loja com bloqueio otimista e
histórico de fase (plano T2.11; dossiê §5.2, §5.10, §5.11 e §6).

Porta dos casos de edição de tests/Integration/Api/LojasEditarTest.php do CRM
autónomo (etiqueta `referencia-standalone`; os de apagar são da T2.12) e dos
de `atualizar` de tests/Integration/Repositorios/LojasRepositorioTest.php, com
os nomes de lá e os dados dos `DataProvider` com os mesmos nomes. Adaptações
ao portal:

- só o escritório (admin e utilizador do CRM; as correções do terreno chegam
  na F4). Sem sessão, os 403/401 herdados do portal em vez do 401
  `nao_autenticado` do autónomo;
- ids uuid4 em texto (lá inteiros), também o `regiao_id` e o `utilizador_id`
  (o `user_id` do portal);
- as lojas "inseridas por SQL" (`LojasTeste::criar`) são documentos escritos à
  mão no duplo, com a forma da base (plano §3), criados a 2026-10-03 09:00 UTC
  com a versão `2026-10-03T09:00:00.250000Z`;
- sem transações (o autónomo bloqueava a linha com `SELECT … FOR UPDATE`):
  a versão lida compara-se logo a seguir à leitura, e o `update_one`
  condicionado a `{"id", "atualizado_em": versao}` é a rede para as corridas
  (`matched_count 0` → relê: 404 ou 409). A interação `mudanca_fase` grava-se
  DEPOIS da loja; se falhar, fica uma linha `[crm]` no registo e a loja não
  se desfaz (plano §1, "Sem transações").
- Ordem das verificações (correções do plano, linha "T2.11"): 422 dos campos
  junto com o do `atualizado_em` → ler a loja (404) → versão diferente (409
  conflito) → janelas contra as horas guardadas, só se o pedido mexer numa
  hora → a região existe → duplicados só se as coordenadas mudarem nas 6
  casas → atualização condicional.
- o `Cache-Control: no-store, private` não se porta (diferença assumida na
  T2.9, dossiê §5.8).

Rotas por `TestClient` com `dependency_overrides[utilizador_atual]` e
`monkeypatch.setattr(crm.db, "obter_db", …)` (plano §10), com o relógio parado
(`relogio.agora`); as corridas com `correr` (nunca `asyncio.run`); no fim, de
ponta a ponta com a sessão verdadeira do portal (JWT + conta lida da base).
"""
import asyncio
import logging
import re
import time
from datetime import datetime, timezone

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError

import crm
import crm.db
import faturacao.auth
from crm import lojas as rotas_lojas
from crm import relogio
from crm.auth import ESCRITORIO, membro_crm_atual
from crm.dominio.geo import filtro_candidatos
from crm.dominio.validador_loja import campos_de_janelas
from crm.lojas import MENSAGEM_CONFLITO, MENSAGEM_SEM_VERSAO, alterar_loja
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
# Longe de tudo (1 km para norte).
LAT_LONGE = 38.719800

# A forma das lojas "inseridas por SQL" (LojasTeste).
CRIADA_EM = "2026-10-03T09:00:00Z"
VERSAO = "2026-10-03T09:00:00.250000Z"
# A versão que outra pessoa gravou entretanto.
VERSAO_DE_OUTRA_PESSOA = "2026-10-03T09:30:00.000000Z"

INSTANTE_MICRO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z")
UUID4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")

SEM_VERSAO = "Indique o atualizado_em que recebeu com a loja."
VALIDACAO = "Verifique os campos assinalados."
INCOMPLETA = "A localização tem de vir completa (lat, lng e origem_coords)."
CONFLITO = {"detail": {"codigo": "conflito", "mensagem": "Alterado por outra pessoa — recarregar"}}
NAO_ENCONTRADA = {"detail": {"codigo": "nao_encontrado", "mensagem": "Loja não encontrada."}}
JSON_INVALIDO = {"detail": {"codigo": "json_invalido", "mensagem": "O pedido não é JSON válido."}}
SEM_PERMISSAO = {"detail": {"codigo": "sem_permissao", "mensagem": "Sem permissão para esta ação."}}
SEM_ACESSO = {"detail": {"codigo": "sem_acesso_crm", "mensagem": "Sem acesso ao CRM."}}

PROJECAO_LOJA = {"_id": 0}
PROJECAO_ID = {"_id": 0, "id": 1}
PROJECAO_CANDIDATO = {"_id": 0, "id": 1, "nome": 1, "lat": 1, "lng": 1}


def _id(n):
    """Um uuid4 em texto, fixo para os testes serem legíveis."""
    return f"00000000-0000-4000-8000-{n:012d}"


CAFE = _id(1)
LISBOA, PORTO = _id(901), _id(902)
NAO_EXISTE = _id(999)


def _validacao(campos):
    return {"detail": {"codigo": "validacao", "mensagem": VALIDACAO, "campos": campos}}


def _regiao(regiao_id, nome):
    return {"id": regiao_id, "nome": nome, "nome_chave": nome.lower(), "ordem": 0}


def _loja(numero, nome, lat, lng=LNG, **outros):
    """Uma loja escrita à mão na base (o `LojasTeste::criar`), na longitude de
    referência, criada a 2026-10-03 09:00 UTC com a versão VERSAO."""
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


def _cafe(**outros):
    """O Café Central (a loja que se edita), no ponto de referência."""
    return _loja(1, "Café Central", LAT, **outros)


def _pino(lat):
    """O pino posto à mão nessa latitude, na longitude de referência."""
    return {"lat": lat, "lng": LNG, "origem_coords": "pin_manual"}


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

# Os membros como a guarda os devolve (para chamar a função da rota diretamente).
RUI_MEMBRO = {**RUI_UTILIZADOR, "crm_perfil": "utilizador", "crm_admin_master": False}
ANA_MEMBRO = {**ANA_ADMIN_DO_CRM, "crm_perfil": "admin", "crm_admin_master": False}


def _base(lojas=(), regioes=(), lojas_coleccao=None, interacoes=None):
    colecoes = {
        "crm_membros": list(MEMBROS),
        "users": list(USERS),
        "crm_regioes": list(regioes),
        "crm_lojas": lojas_coleccao if lojas_coleccao is not None else list(lojas),
    }
    if interacoes is not None:
        colecoes["crm_interacoes"] = interacoes
    return BaseFalsa(colecoes)


def _escritas(base):
    """As escritas em `crm_lojas`, `crm_regioes` e `crm_interacoes`, pela ordem de cada coleção."""
    return [
        c
        for coleccao in (base.crm_lojas, base.crm_regioes, base.crm_interacoes)
        for c in coleccao.registo
        if c[0] in ("insert_one", "update_one", "delete_one", "delete_many")
    ]


def _guardada(base, numero=1):
    """A loja `numero` como está gravada no duplo (sem o `_id`)."""
    [loja] = [d for d in base.crm_lojas.sem_id() if d["id"] == _id(numero)]
    return loja


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
    (com `cliente.base` e `cliente.alterar(loja_id, alteracoes, versao=VERSAO)`,
    o `alterar` do LojasEditarTest)."""
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    monkeypatch.setattr(relogio, "agora", lambda: AGORA)

    def _montar(utilizador, base=None, levantar=True):
        base = base if base is not None else _base(lojas=[_cafe()])
        monkeypatch.setattr(crm.db, "obter_db", lambda: base)
        app = FastAPI()
        app.include_router(crm.router)
        app.dependency_overrides[utilizador_atual] = lambda: dict(utilizador)
        cliente = TestClient(app, raise_server_exceptions=levantar)
        cliente.base = base

        def _alterar(loja_id, alteracoes, versao=VERSAO):
            return cliente.patch(f"{LOJAS_URL}/{loja_id}", json={**alteracoes, "atualizado_em": versao})

        cliente.alterar = _alterar
        return cliente

    return _montar


@pytest.fixture
def direto(monkeypatch):
    """Para chamar a função da rota diretamente (as corridas): a base trocada
    e o relógio parado."""
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    monkeypatch.setattr(relogio, "agora", lambda: AGORA)

    def _montar(base):
        monkeypatch.setattr(crm.db, "obter_db", lambda: base)
        return base

    return _montar


def _relogio_em(monkeypatch, texto):
    """Para o relógio no instante UTC `texto` ("AAAA-MM-DD HH:MM:SS[.ffffff]")."""
    formato = "%Y-%m-%d %H:%M:%S.%f" if "." in texto else "%Y-%m-%d %H:%M:%S"
    momento = datetime.strptime(texto, formato).replace(tzinfo=UTC)
    monkeypatch.setattr(relogio, "agora", lambda: momento)


# --- A rota: onde está, quem a guarda e por que ordem ---------------------------------------------


def test_a_rota_existe_vive_em_crm_lojas_e_e_do_escritorio():
    rota = _rota(UMA_LOJA_URL, "PATCH")
    assert rota.methods == {"PATCH"}
    assert rota.endpoint is alterar_loja
    assert rota.endpoint.__module__ == "crm.lojas"
    dependencias = _dependencias(rota)
    assert membro_crm_atual in dependencias
    assert [d for d in dependencias if hasattr(d, "perfis_crm")] == [ESCRITORIO]


def test_alterar_tem_a_guarda_de_perfil_antes_do_corpo():
    """Correções do plano, linha "T1.3 / T2.15"."""
    assert [d.call for d in _rota(UMA_LOJA_URL, "PATCH").dependant.dependencies] == [ESCRITORIO, corpo_json]


def test_as_mensagens_sao_as_do_autonomo():
    assert MENSAGEM_SEM_VERSAO == SEM_VERSAO
    assert MENSAGEM_CONFLITO == CONFLITO["detail"]["mensagem"]


# --- O caminho feliz e a versão nova ----------------------------------------------------------------


def test_mudar_o_telefone_devolve_a_loja_com_novo_atualizado_em(sessao):
    """`mudarOTelefoneDevolveALojaComNovoAtualizadoEm`."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe(telefone="912 345 678")]))
    antes = cliente.get(f"{LOJAS_URL}/{CAFE}").json()

    r = cliente.alterar(CAFE, {"telefone": " 213  456 789 "})

    assert r.status_code == 200, r.text
    loja = r.json()
    assert loja["telefone"] == "213 456 789"
    assert INSTANTE_MICRO.fullmatch(loja["atualizado_em"])
    assert loja["atualizado_em"] > VERSAO
    assert loja["atualizado_em"] == AGORA_CARIMBO
    sem = ("telefone", "atualizado_em")
    assert {c: v for c, v in loja.items() if c not in sem} == {c: v for c, v in antes.items() if c not in sem}, (
        "O resto da loja fica igual."
    )
    assert list(loja) == list(antes), "A mesma forma (e ordem) da loja completa."

    lida = cliente.get(f"{LOJAS_URL}/{CAFE}")
    assert lida.json() == loja, "GET /lojas/{id} devolve o mesmo que o PATCH."
    assert list(lida.json()) == list(loja)
    assert _guardada(cliente.base)["telefone"] == "213 456 789"


def test_com_o_relogio_verdadeiro_a_versao_e_a_do_pedido(sessao, monkeypatch):
    """O `assertGreaterThanOrEqual(inicio − 1, …)` do autónomo, com o relógio verdadeiro."""
    cliente = sessao(RUI_UTILIZADOR)
    monkeypatch.setattr(relogio, "agora", AGORA_DO_RELOGIO)
    antes = relogio.agora().timestamp()
    r = cliente.alterar(CAFE, {"telefone": "912 345 678"})
    depois = relogio.agora().timestamp()

    assert r.status_code == 200, r.text
    versao = datetime.strptime(r.json()["atualizado_em"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC).timestamp()
    assert antes - 1 <= versao <= depois + 1


def test_o_update_one_e_condicional_a_versao_lida(sessao):
    """O bloqueio otimista (plano §1): ler a loja, e gravar SÓ se ainda tiver a
    versão que o cliente recebeu — `{"id", "atualizado_em": versao}`, sem upsert."""
    cliente = sessao(RUI_UTILIZADOR)
    assert cliente.alterar(CAFE, {"telefone": "912 345 678"}).status_code == 200

    assert cliente.base.crm_lojas.registo == [
        ("find_one", {"id": CAFE}, PROJECAO_LOJA),
        ("update_one", {"id": CAFE, "atualizado_em": VERSAO},
         {"$set": {"telefone": "912 345 678", "atualizado_em": AGORA_CARIMBO}}, False),
    ]


def test_so_com_o_atualizado_em_so_a_versao_muda(sessao):
    """Um PATCH sem campos grava só a versão nova (o UPDATE do autónomo também
    a avançava): nunca um `$set` vazio."""
    cliente = sessao(RUI_UTILIZADOR)
    r = cliente.alterar(CAFE, {})

    assert r.status_code == 200, r.text
    assert r.json()["atualizado_em"] == AGORA_CARIMBO
    [(_, _, atualizacao, _)] = cliente.base.crm_lojas.chamadas("update_one")
    assert atualizacao == {"$set": {"atualizado_em": AGORA_CARIMBO}}


def test_o_set_grava_os_campos_com_os_tipos_da_base_e_a_versao_nova(sessao, monkeypatch):
    """`atualizarGravaOsCamposComOsTiposDaBdEAVersaoNova` (LojasRepositorioTest):
    lat/lng em float e SEMPRE com o `loc`, janelas em lista, dias pela ordem da
    semana, precisão inteira; a fase não mudou, o `fase_desde` fica."""
    _relogio_em(monkeypatch, "2026-10-04 08:00:00.123456")
    cliente = sessao(RUI_UTILIZADOR)

    r = cliente.alterar(CAFE, {
        "telefone": "912 345 678",
        "lat": 38.7109,
        "lng": -9.1368,
        "origem_coords": "gps",
        "precisao_m": 8,
        "dias_fechada": ["dom", "seg"],
        "janela1_inicio": "10:00",
        "janela1_fim": "13:00",
    })

    assert r.status_code == 200, r.text
    novos = {
        "lat": 38.7109,
        "lng": -9.1368,
        "loc": {"type": "Point", "coordinates": [-9.1368, 38.7109]},
        "origem_coords": "gps",
        "precisao_m": 8,
        "telefone": "912 345 678",
        "janelas": [{"inicio": "10:00", "fim": "13:00"}],
        "dias_fechada": ["seg", "dom"],
        "atualizado_em": "2026-10-04T08:00:00.123456Z",
    }
    [(_, filtro, atualizacao, upsert)] = cliente.base.crm_lojas.chamadas("update_one")
    assert (filtro, atualizacao, upsert) == ({"id": CAFE, "atualizado_em": VERSAO}, {"$set": novos}, False)
    # Correções do plano, linha "§1 Decisões (Tempo) / T2.8": o que se grava.
    assert instantes_fora_do_formato(atualizacao["$set"]) == []

    guardada = _guardada(cliente.base)
    assert guardada == {**_cafe(), **novos}
    assert list(guardada) == list(_cafe()), "As chaves ficam no sítio (o $set só muda valores)."
    assert [type(guardada["lat"]), type(guardada["lng"]), type(guardada["precisao_m"])] == [float, float, int]
    assert guardada["fase_desde"] == CRIADA_EM
    assert instantes_fora_do_formato(guardada) == []
    assert cliente.base.crm_interacoes.registo == []


def test_com_o_relogio_atrasado_a_versao_avanca_na_mesma(sessao, monkeypatch):
    """`comORelogioAtrasadoAVersaoAvancaNaMesma` (LojasRepositorioTest): cada
    alteração dá uma versão nova, mesmo com o relógio atrasado ou repetido."""
    cliente = sessao(RUI_UTILIZADOR)
    versao = VERSAO

    for agora in ("2026-10-01 00:00:00", "2026-10-03 09:00:00.250000"):
        _relogio_em(monkeypatch, agora)
        r = cliente.alterar(CAFE, {"notas": agora}, versao)
        assert r.status_code == 200, r.text
        versao = r.json()["atualizado_em"]

    assert versao == "2026-10-03T09:00:00.250002Z"
    assert _guardada(cliente.base)["atualizado_em"] == "2026-10-03T09:00:00.250002Z"


def test_os_campos_que_o_servidor_decide_ignoram_se(sessao):
    """`osCamposQueOServidorDecideIgnoramSe`, mais os do modelo do portal
    (`_id`, `loc`, `janelas` em lista, os temporizadores): nada disto vem do corpo."""
    cliente = sessao(RUI_UTILIZADOR)

    r = cliente.alterar(CAFE, {
        "id": "999",
        "_id": "forjado",
        "notas": "Fecha em agosto.",
        "criado_por": "u-bea",
        "criado_em": "2020-01-01T00:00:00Z",
        "fase_desde": "2020-01-01T00:00:00Z",
        "visita_pendente_motivo": "amostra",
        "visita_pendente_desde": "2020-01-01T00:00:00Z",
        "ultima_interacao_em": "2020-01-01T00:00:00Z",
        "ultima_visita_ou_entrega_em": "2020-01-01T00:00:00Z",
        "loc": {"type": "Point", "coordinates": [0, 0]},
        "janelas": [{"inicio": "01:00", "fim": "02:00"}],
    })

    assert r.status_code == 200, r.text
    loja = r.json()
    assert loja["id"] == CAFE
    assert loja["notas"] == "Fecha em agosto."
    assert loja["criado_por"] is None
    assert loja["criado_em"] == CRIADA_EM
    assert loja["fase_desde"] == CRIADA_EM
    assert loja["visita_pendente_motivo"] is None
    assert loja["visita_pendente_desde"] is None
    assert loja["ultima_interacao_em"] is None
    assert loja["ultima_visita_ou_entrega_em"] is None
    assert loja["janela1_inicio"] is None
    [(_, _, atualizacao, _)] = cliente.base.crm_lojas.chamadas("update_one")
    assert atualizacao == {"$set": {"notas": "Fecha em agosto.", "atualizado_em": AGORA_CARIMBO}}
    guardada = cliente.base.crm_lojas.docs[0]
    assert guardada["_id"] != "forjado"
    assert guardada["loc"] == {"type": "Point", "coordinates": [LNG, LAT]}
    assert guardada["janelas"] == []


def test_limpar_os_opcionais_grava_null_e_os_dias_vazios(sessao):
    """Limpar um opcional (`null` ou `""`) grava null; os dias, `[]`; tirar
    todas as horas, `janelas: []`."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe(
        telefone="912 345 678", morada="Rua Augusta 10", notas="Fecha em agosto.", dias_fechada=["dom"],
        janelas=[{"inicio": "10:00", "fim": "13:00"}],
    )]))

    r = cliente.alterar(CAFE, {
        "telefone": None, "morada": "", "notas": "   ", "dias_fechada": None,
        "janela1_inicio": None, "janela1_fim": "",
    })

    assert r.status_code == 200, r.text
    guardada = _guardada(cliente.base)
    assert (guardada["telefone"], guardada["morada"], guardada["notas"]) == (None, None, None)
    assert (guardada["dias_fechada"], guardada["janelas"]) == ([], [])
    assert (r.json()["janela1_inicio"], r.json()["janela1_fim"], r.json()["dias_fechada"]) == (None, None, [])


def test_mudar_o_instagram_e_o_site_grava_os_normalizados(sessao):
    """2026-10-13: os dois campos novos passam pelo `alteracao` como os outros
    opcionais — o handle vira o endereço do perfil e o domínio ganha https://;
    limpar grava null."""
    cliente = sessao(RUI_UTILIZADOR)

    r = cliente.alterar(CAFE, {"instagram": "@cafe.central", "site": "cafecentral.pt"})

    assert r.status_code == 200, r.text
    assert (r.json()["instagram"], r.json()["site"]) == (
        "https://www.instagram.com/cafe.central/", "https://cafecentral.pt",
    )
    [(_, _filtro, atualizacao, _upsert)] = cliente.base.crm_lojas.chamadas("update_one")
    assert atualizacao["$set"] == {
        "instagram": "https://www.instagram.com/cafe.central/",
        "site": "https://cafecentral.pt",
        "atualizado_em": AGORA_CARIMBO,
    }
    guardada = _guardada(cliente.base)
    assert (guardada["instagram"], guardada["site"]) == (
        "https://www.instagram.com/cafe.central/", "https://cafecentral.pt",
    )
    assert list(guardada) == list(_cafe()), "As chaves ficam no sítio."

    r = cliente.alterar(CAFE, {"instagram": "", "site": None}, versao=r.json()["atualizado_em"])
    assert r.status_code == 200, r.text
    assert (r.json()["instagram"], r.json()["site"]) == (None, None)
    guardada = _guardada(cliente.base)
    assert (guardada["instagram"], guardada["site"]) == (None, None)


def test_um_instagram_ou_um_site_invalido_da_422_sem_ler_a_base(sessao):
    cliente = sessao(RUI_UTILIZADOR)
    r = cliente.alterar(CAFE, {"instagram": "purple house", "site": "exemplo"})

    assert (r.status_code, r.json()) == (422, _validacao({
        "instagram": "O Instagram tem de ser um perfil válido (ex.: @purplehouse).",
        "site": "O site tem de ser um endereço válido (ex.: https://exemplo.pt).",
    }))
    assert cliente.base.crm_lojas.registo == []


def test_uma_loja_gravada_antes_do_instagram_e_do_site_edita_se_e_le_se(sessao):
    """Um documento de antes de 2026-10-13 não tem os dois campos: lê-se com
    eles a null, e um PATCH noutro campo não os inventa no `$set`."""
    antiga = _cafe()
    del antiga["instagram"]
    del antiga["site"]
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[antiga]))

    lida = cliente.get(f"{LOJAS_URL}/{CAFE}")
    assert lida.status_code == 200
    assert (lida.json()["instagram"], lida.json()["site"]) == (None, None)

    r = cliente.alterar(CAFE, {"telefone": "912 345 678"})
    assert r.status_code == 200, r.text
    assert (r.json()["instagram"], r.json()["site"]) == (None, None)
    [(_, _filtro, atualizacao, _upsert)] = cliente.base.crm_lojas.chamadas("update_one")
    assert set(atualizacao["$set"]) == {"telefone", "atualizado_em"}


def test_a_resposta_nunca_traz_o_id_do_mongo_o_loc_nem_as_janelas_em_lista(sessao):
    r = sessao(RUI_UTILIZADOR).alterar(CAFE, {**_pino(38.7109), "confirmar_duplicado": True})
    assert r.status_code == 200
    assert {"_id", "loc", "janelas", "confirmar_duplicado"}.isdisjoint(r.json())


def test_os_numeros_inteiros_gravam_se_em_float_e_a_precisao_em_inteiro(sessao):
    cliente = sessao(RUI_UTILIZADOR)
    r = cliente.alterar(CAFE, {"lat": 39, "lng": -8, "origem_coords": "gps", "precisao_m": 12.5})

    assert r.status_code == 200, r.text
    assert '"lat":39.0,"lng":-8.0,' in r.text
    assert '"precisao_m":13,' in r.text
    guardada = cliente.base.crm_lojas.docs[0]
    assert [type(guardada["lat"]), type(guardada["lng"]), type(guardada["precisao_m"])] == [float, float, int]
    assert guardada["loc"] == {"type": "Point", "coordinates": [-8.0, 39.0]}


# --- A versão: 422, 409 e 404 -----------------------------------------------------------------------


def test_um_atualizado_em_antigo_da_409_conflito_e_nada_muda(sessao):
    """`umAtualizadoEmAntigoDa409ConflitoENadaMuda`: a Eva (aqui a Ana) grava
    primeiro; o Rui, com a versão que tinha, recebe 409 e nada muda; com a
    versão nova já consegue."""
    base = _base(lojas=[_cafe()])
    ana = sessao(ANA_ADMIN_DO_CRM, base)
    rui = sessao(RUI_UTILIZADOR, base)

    primeiro = ana.alterar(CAFE, {"telefone": "912 345 678"})
    assert primeiro.status_code == 200

    r = rui.alterar(CAFE, {"telefone": "213 456 789"})

    assert (r.status_code, r.json()) == (409, CONFLITO)
    assert list(r.json()["detail"]) == ["codigo", "mensagem"]
    assert _guardada(base)["telefone"] == "912 345 678"

    segundo = rui.alterar(CAFE, {"telefone": "213 456 789"}, primeiro.json()["atualizado_em"])
    assert segundo.status_code == 200, "Com o atualizado_em novo já se consegue: " + segundo.text
    assert segundo.json()["telefone"] == "213 456 789"


@pytest.mark.parametrize(
    "versao", ["2026-10-03T09:00:00.249999Z", "2026-10-03T09:00:00.250001Z"], ids=["1 µs antes", "1 µs depois"]
)
def test_um_atualizado_em_que_nao_e_o_guardado_da_409(sessao, versao):
    """`umAtualizadoEmQueNaoEOGuardadoDa409`: e decide-se logo a seguir a ler a
    loja, sem tentar gravar."""
    cliente = sessao(RUI_UTILIZADOR)
    r = cliente.alterar(CAFE, {"telefone": "912 345 678"}, versao)

    assert (r.status_code, r.json()) == (409, CONFLITO)
    assert _guardada(cliente.base) == _cafe()
    assert cliente.base.crm_lojas.registo == [("find_one", {"id": CAFE}, PROJECAO_LOJA)]


def test_com_uma_versao_antiga_nada_se_grava_nem_a_mudanca_de_fase(sessao):
    """`comUmaVersaoAntigaNadaSeGrava` (LojasRepositorioTest): nem a loja, nem a interação."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe(atualizado_em=VERSAO_DE_OUTRA_PESSOA)]))
    r = cliente.alterar(CAFE, {"telefone": "912 345 678", "fase": "cliente"})

    assert (r.status_code, r.json()) == (409, CONFLITO)
    guardada = _guardada(cliente.base)
    assert (guardada["telefone"], guardada["fase"], guardada["atualizado_em"]) == (
        None, "potencial", VERSAO_DE_OUTRA_PESSOA,
    )
    assert _escritas(cliente.base) == []


SEM_VERSAO_VALIDA = [
    ("sem a chave", {}),
    ("null", {"atualizado_em": None}),
    ("no formato da BD", {"atualizado_em": "2026-10-03 09:00:00.250000"}),
    ("sem microssegundos", {"atualizado_em": "2026-10-03T09:00:00Z"}),
    ("um número", {"atualizado_em": 1759482000}),
    # Armadilhas do portal: nada disto chega ao filtro do update_one.
    ("um operador do Mongo", {"atualizado_em": {"$gt": ""}}),
    ("uma lista", {"atualizado_em": [VERSAO]}),
    ("verdadeiro", {"atualizado_em": True}),
    ("com 7 casas", {"atualizado_em": "2026-10-03T09:00:00.2500000Z"}),
    ("sem o Z", {"atualizado_em": "2026-10-03T09:00:00.250000"}),
    ("com espaço no fim", {"atualizado_em": VERSAO + " "}),
    ("com fuso", {"atualizado_em": "2026-10-03T09:00:00.250000+00:00"}),
    ("um dia que não existe", {"atualizado_em": "2026-02-30T09:00:00.250000Z"}),
]


@pytest.mark.parametrize("versao", [c[1] for c in SEM_VERSAO_VALIDA], ids=[c[0] for c in SEM_VERSAO_VALIDA])
def test_sem_atualizado_em_valido_da_422(sessao, versao):
    """`semAtualizadoEmValidoDa422`: e sem ler a base."""
    cliente = sessao(RUI_UTILIZADOR)
    r = cliente.patch(f"{LOJAS_URL}/{CAFE}", json={"telefone": "912 345 678", **versao})

    assert (r.status_code, r.json()) == (422, _validacao({"atualizado_em": SEM_VERSAO}))
    assert _guardada(cliente.base)["telefone"] is None
    assert cliente.base.crm_lojas.registo == []


def test_os_erros_dos_campos_vem_juntos_com_o_do_atualizado_em(sessao):
    """`osErrosDosCamposVemJuntosComODoAtualizadoEm`: os dos campos pela ordem
    de `CAMPOS` e o da versão no fim."""
    cliente = sessao(RUI_UTILIZADOR)
    r = cliente.patch(f"{LOJAS_URL}/{CAFE}", json={"telefone": "12", "nome": " "})

    assert r.status_code == 422
    assert list(r.json()["detail"]["campos"].items()) == [
        ("nome", "Indique o nome."),
        ("telefone", "O telefone tem de ter 9 a 15 algarismos (aceita + e espaços)."),
        ("atualizado_em", SEM_VERSAO),
    ]
    assert _guardada(cliente.base)["nome"] == "Café Central"
    assert cliente.base.crm_lojas.registo == []


def test_os_erros_dos_campos_dao_422_sem_ler_a_base(sessao):
    """O 422 vem antes de ler a loja: um id que não existe com campos errados é 422, não 404."""
    cliente = sessao(RUI_UTILIZADOR)
    r = cliente.alterar(NAO_EXISTE, {"fase": "vip"})

    assert (r.status_code, r.json()) == (422, _validacao({"fase": "A fase não é válida."}))
    assert cliente.base.crm_lojas.registo == []
    assert cliente.base.crm_regioes.registo == []


@pytest.mark.parametrize("loja_id", ["999", NAO_EXISTE], ids=["número", "uuid"])
def test_editar_uma_loja_que_nao_existe_da_404(sessao, loja_id):
    """`editarUmaLojaQueNaoExisteDa404`: com qualquer versão (o 404 vem antes do 409)."""
    cliente = sessao(RUI_UTILIZADOR)
    r = cliente.alterar(loja_id, {"telefone": "912 345 678"}, VERSAO_DE_OUTRA_PESSOA)

    assert (r.status_code, r.json()) == (404, NAO_ENCONTRADA)
    assert cliente.base.crm_lojas.registo == [("find_one", {"id": loja_id}, PROJECAO_LOJA)]
    assert _escritas(cliente.base) == []


# --- As corridas: a atualização condicional é a rede --------------------------------------------------


class LojasQueMudamEntretanto(ColeccaoFalsa):
    """Outra pessoa grava a loja entre a leitura e o `update_one` deste pedido."""

    async def update_one(self, filtro, atualizacao, upsert=False):
        for doc in self.docs:
            if doc["id"] == filtro["id"]:
                doc["atualizado_em"] = VERSAO_DE_OUTRA_PESSOA
                doc["telefone"] = "966 000 000"
        return await super().update_one(filtro, atualizacao, upsert)


class LojasQueSomemEntretanto(ColeccaoFalsa):
    """Outra pessoa apaga a loja entre a leitura e o `update_one` deste pedido."""

    async def update_one(self, filtro, atualizacao, upsert=False):
        self.docs[:] = [doc for doc in self.docs if doc["id"] != filtro["id"]]
        return await super().update_one(filtro, atualizacao, upsert)


def test_na_corrida_uma_loja_alterada_entretanto_da_409_e_nada_se_grava(sessao):
    """O `update_one` não apanha nada (`matched_count 0`) e a loja ainda lá
    está: 409, a gravação da outra pessoa fica, e não há interação."""
    lojas = LojasQueMudamEntretanto([_cafe()], nome="crm_lojas")
    cliente = sessao(RUI_UTILIZADOR, _base(lojas_coleccao=lojas))

    r = cliente.alterar(CAFE, {"telefone": "912 345 678", "fase": "cliente"})

    assert (r.status_code, r.json()) == (409, CONFLITO)
    guardada = _guardada(cliente.base)
    assert (guardada["telefone"], guardada["fase"], guardada["atualizado_em"]) == (
        "966 000 000", "potencial", VERSAO_DE_OUTRA_PESSOA,
    )
    assert [c[0] for c in lojas.registo] == ["find_one", "update_one", "find_one"]
    assert lojas.registo[-1] == ("find_one", {"id": CAFE}, PROJECAO_ID)
    assert cliente.base.crm_interacoes.registo == []


def test_na_corrida_uma_loja_apagada_entretanto_da_404_e_nao_ressuscita(sessao):
    """O `update_one` não apanha nada e a loja já não existe: 404 (sem upsert,
    a loja não volta), e não há interação."""
    lojas = LojasQueSomemEntretanto([_cafe()], nome="crm_lojas")
    cliente = sessao(RUI_UTILIZADOR, _base(lojas_coleccao=lojas))

    r = cliente.alterar(CAFE, {"telefone": "912 345 678", "fase": "cliente"})

    assert (r.status_code, r.json()) == (404, NAO_ENCONTRADA)
    assert lojas.docs == []
    assert [c[0] for c in lojas.registo] == ["find_one", "update_one", "find_one"]
    assert lojas.chamadas("update_one")[0][3] is False, "Nunca upsert."
    assert cliente.base.crm_interacoes.registo == []


def test_duas_alteracoes_com_a_mesma_versao_ao_mesmo_tempo_so_uma_grava(direto):
    """A corrida a sério no duplo: as duas leem a mesma versão e passam a
    comparação antecipada; o `update_one` condicional deixa gravar só a
    primeira, e só ela fica no histórico."""
    base = direto(_base(lojas=[_cafe()]))

    async def _ao_mesmo_tempo():
        return await asyncio.gather(
            alterar_loja(CAFE, RUI_MEMBRO, {"fase": "cliente", "atualizado_em": VERSAO}),
            alterar_loja(CAFE, ANA_MEMBRO, {"fase": "perdida", "atualizado_em": VERSAO}),
            return_exceptions=True,
        )

    primeira, segunda = correr(_ao_mesmo_tempo())

    assert primeira["fase"] == "cliente"
    assert isinstance(segunda, HTTPException)
    assert (segunda.status_code, segunda.detail) == (409, CONFLITO["detail"])
    assert [c[0] for c in base.crm_lojas.registo] == ["find_one", "find_one", "update_one", "update_one", "find_one"]
    guardada = _guardada(base)
    assert (guardada["fase"], guardada["atualizado_em"]) == ("cliente", AGORA_CARIMBO)
    assert [i["resultado"] for i in base.crm_interacoes.sem_id()] == ["potencial→cliente"]


def test_quando_a_base_falha_ao_gravar_e_um_erro(sessao):
    lojas = ColeccaoFalsa([_cafe()], falhar={"update_one": RuntimeError("base em baixo")}, nome="crm_lojas")
    cliente = sessao(RUI_UTILIZADOR, _base(lojas_coleccao=lojas), levantar=False)
    assert cliente.alterar(CAFE, {"telefone": "912 345 678"}).status_code == 500


# --- A fase e o histórico ---------------------------------------------------------------------------


def test_mudar_a_fase_atualiza_fase_desde_e_grava_uma_interacao(sessao):
    """`mudarAFaseAtualizaFaseDesdeEGravaUmaInteracao`: o `fase_desde` é o
    instante do pedido, e a interação `mudanca_fase` "potencial→cliente" fica
    com quem a mudou, no mesmo instante. As mudanças de fase não contam para os
    alertas (`ultima_interacao_em` fica null)."""
    cliente = sessao(RUI_UTILIZADOR)

    r = cliente.alterar(CAFE, {"fase": "cliente"})

    assert r.status_code == 200, r.text
    loja = r.json()
    assert (loja["fase"], loja["fase_desde"]) == ("cliente", AGORA_INSTANTE)
    assert loja["ultima_interacao_em"] is None

    [interacao] = cliente.base.crm_interacoes.sem_id()
    assert UUID4.fullmatch(interacao["id"])
    assert list(interacao.items()) == list({
        "id": interacao["id"],
        "loja_id": CAFE,
        "tipo": "mudanca_fase",
        "resultado": "potencial→cliente",
        "notas": None,
        "paragem_id": None,
        "utilizador_id": "u-rui",
        "ocorrida_em": _guardada(cliente.base)["fase_desde"],
    }.items())
    assert "client_uuid" not in interacao, "Na F2 as interações não têm client_uuid (índice parcial)."
    # Correções do plano, linha "§1 Decisões (Tempo) / T2.8".
    assert instantes_fora_do_formato(interacao) == []
    [(_, _, atualizacao, _)] = cliente.base.crm_lojas.chamadas("update_one")
    assert atualizacao == {"$set": {"fase": "cliente", "fase_desde": AGORA_INSTANTE, "atualizado_em": AGORA_CARIMBO}}
    assert instantes_fora_do_formato(atualizacao["$set"]) == []


def test_mudar_a_fase_grava_fase_desde_e_a_interacao_no_mesmo_instante(sessao, monkeypatch):
    """`mudarAFaseGravaFaseDesdeEAInteracaoNoMesmoInstante` (LojasRepositorioTest):
    o segundo do pedido (sem fração) no `fase_desde` e na `ocorrida_em`, e a
    versão com os microssegundos."""
    _relogio_em(monkeypatch, "2026-10-04 08:00:00.654321")
    cliente = sessao(ANA_ADMIN_DO_CRM, _base(lojas=[_cafe(fase="amostra")]))

    assert cliente.alterar(CAFE, {"fase": "cliente"}).status_code == 200

    guardada = _guardada(cliente.base)
    assert (guardada["fase"], guardada["fase_desde"], guardada["atualizado_em"]) == (
        "cliente", "2026-10-04T08:00:00Z", "2026-10-04T08:00:00.654321Z",
    )
    [interacao] = cliente.base.crm_interacoes.sem_id()
    assert {c: interacao[c] for c in ("loja_id", "tipo", "resultado", "utilizador_id", "ocorrida_em")} == {
        "loja_id": CAFE,
        "tipo": "mudanca_fase",
        "resultado": "amostra→cliente",
        "utilizador_id": "u-ana",
        "ocorrida_em": "2026-10-04T08:00:00Z",
    }


def test_um_so_agora_por_pedido_mesmo_com_o_relogio_a_andar(sessao, monkeypatch):
    """O relógio lê-se UMA vez por pedido: o `fase_desde`, a `ocorrida_em` e a
    versão nova são do mesmo instante, mesmo que o relógio ande entre a
    leitura e as escritas (aqui, 5 s a cada leitura)."""
    leituras = []

    def _relogio_a_andar():
        leituras.append(None)
        return AGORA if len(leituras) == 1 else datetime(2026, 10, 10, 9, 30, 20, 0, tzinfo=UTC)

    cliente = sessao(RUI_UTILIZADOR)
    monkeypatch.setattr(relogio, "agora", _relogio_a_andar)

    r = cliente.alterar(CAFE, {"fase": "cliente"})

    assert r.status_code == 200, r.text
    assert len(leituras) == 1
    guardada = _guardada(cliente.base)
    [interacao] = cliente.base.crm_interacoes.sem_id()
    assert (guardada["fase_desde"], interacao["ocorrida_em"], guardada["atualizado_em"]) == (
        AGORA_INSTANTE, AGORA_INSTANTE, AGORA_CARIMBO,
    )


def test_cada_mudanca_de_fase_fica_no_historico(sessao):
    """`cadaMudancaDeFaseFicaNoHistorico`."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe(fase="contactada")]))

    primeira = cliente.alterar(CAFE, {"fase": "amostra"})
    assert cliente.alterar(CAFE, {"fase": "perdida"}, primeira.json()["atualizado_em"]).status_code == 200

    assert [i["resultado"] for i in cliente.base.crm_interacoes.sem_id()] == ["contactada→amostra", "amostra→perdida"]
    assert _guardada(cliente.base)["fase"] == "perdida"


SEM_MUDAR_DE_FASE = [
    ("sem a fase", {"telefone": "912 345 678"}),
    ("com a mesma fase", {"fase": "amostra", "telefone": "912 345 678"}),
]


@pytest.mark.parametrize("alteracoes", [c[1] for c in SEM_MUDAR_DE_FASE], ids=[c[0] for c in SEM_MUDAR_DE_FASE])
def test_nao_mudar_a_fase_deixa_fase_desde_igual_e_sem_interacoes(sessao, alteracoes):
    """`naoMudarAFaseDeixaFaseDesdeIgualESemInteracoes`."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe(fase="amostra")]))

    r = cliente.alterar(CAFE, alteracoes)

    assert r.status_code == 200, r.text
    assert (r.json()["fase"], r.json()["fase_desde"]) == ("amostra", CRIADA_EM)
    assert cliente.base.crm_interacoes.registo == []
    [(_, _, atualizacao, _)] = cliente.base.crm_lojas.chamadas("update_one")
    assert "fase_desde" not in atualizacao["$set"]


def test_a_loja_grava_se_antes_da_interacao(sessao):
    """A ordem das escritas sem transações (plano §1): primeiro a loja (com a
    versão), depois a interação."""
    ordem = []

    class Registada(ColeccaoFalsa):
        async def update_one(self, *args, **kwargs):
            ordem.append((self.nome, "update_one"))
            return await super().update_one(*args, **kwargs)

        async def insert_one(self, doc):
            ordem.append((self.nome, "insert_one"))
            return await super().insert_one(doc)

    base = _base(
        lojas_coleccao=Registada([_cafe()], nome="crm_lojas"),
        interacoes=Registada([], nome="crm_interacoes"),
    )
    assert sessao(RUI_UTILIZADOR, base).alterar(CAFE, {"fase": "cliente"}).status_code == 200
    assert ordem == [("crm_lojas", "update_one"), ("crm_interacoes", "insert_one")]


PESSOAL = "Café Central 912 345 678 u-rui rui@example.com Rui Costa"
FALHAS_DA_INTERACAO = [
    ("RuntimeError", RuntimeError(PESSOAL)),
    ("DuplicateKeyError", DuplicateKeyError(f"E11000 duplicate key error dup key: {PESSOAL}", 11000)),
    ("ServerSelectionTimeoutError", ServerSelectionTimeoutError(PESSOAL)),
]


@pytest.mark.parametrize("falha", [c[1] for c in FALHAS_DA_INTERACAO], ids=[c[0] for c in FALHAS_DA_INTERACAO])
def test_uma_falha_ao_gravar_a_interacao_nao_desfaz_a_loja(sessao, caplog, falha):
    """Sem transações: a loja já mudou e responde-se 200; a falha fica numa
    linha `[crm]` no registo, sem dados pessoais (nem quem, nem a loja pelo
    nome, nem a mensagem da exceção, que pode trazer o documento)."""
    interacoes = ColeccaoFalsa([], falhar={"insert_one": falha}, nome="crm_interacoes")
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe(telefone="912 345 678")], interacoes=interacoes))

    with caplog.at_level(logging.DEBUG, logger="crm"):
        r = cliente.alterar(CAFE, {"fase": "cliente"})

    assert r.status_code == 200, r.text
    assert (r.json()["fase"], r.json()["fase_desde"]) == ("cliente", AGORA_INSTANTE)
    assert _guardada(cliente.base)["fase"] == "cliente"
    assert len(interacoes.chamadas("insert_one")) == 1
    registos = [registo for registo in caplog.records if registo.name.startswith("crm")]
    assert [(registo.name, registo.levelno) for registo in registos] == [("crm.lojas", logging.ERROR)]
    mensagem = registos[0].getMessage()
    assert mensagem.startswith("[crm] ")
    assert CAFE in mensagem and "potencial→cliente" in mensagem and type(falha).__name__ in mensagem
    for dado in ("Café", "912", "u-rui", "rui@example.com", "Rui Costa"):
        assert dado not in caplog.text, dado
    assert registos[0].exc_info is None, "Sem o traceback, que traz a mensagem da exceção."


# --- As janelas: com as horas que a loja já tem --------------------------------------------------------


COM_JANELA_1 = [{"inicio": "10:00", "fim": "13:00"}]

JANELAS_INCOERENTES = [
    ("janela 2 antes do fim da 1", {"janela2_inicio": "12:00", "janela2_fim": "14:00"},
     {"janela2_inicio": "A janela 2 tem de começar depois do fim da janela 1."}),
    ("tirar só o fim", {"janela1_fim": None}, {"janela1_fim": "Indique também o fim."}),
    ("início depois do fim guardado", {"janela1_inicio": "14:00"}, {"janela1_fim": "O fim tem de ser depois do início."}),
    # A ordem dos erros é a do `Janelas::erros` (o autónomo não os reordenava aqui).
    ("tirar a janela 1 e deixar a 2 só com o início",
     {"janela1_inicio": None, "janela1_fim": None, "janela2_inicio": "15:00"},
     {"janela2_fim": "Indique também o fim.", "janela2_inicio": "Preencha primeiro a janela 1."}),
]


@pytest.mark.parametrize(
    "alteracoes, campos", [c[1:] for c in JANELAS_INCOERENTES], ids=[c[0] for c in JANELAS_INCOERENTES]
)
def test_as_janelas_verificam_se_com_as_horas_que_a_loja_ja_tem(sessao, alteracoes, campos):
    """`asJanelasVerificamSeComAsHorasQueALojaJaTem`: e nada se grava."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe(janelas=COM_JANELA_1)]))

    r = cliente.alterar(CAFE, alteracoes)

    assert (r.status_code, r.json()) == (422, _validacao(campos))
    assert list(r.json()["detail"]["campos"]) == list(campos)
    assert _guardada(cliente.base)["atualizado_em"] == VERSAO
    assert _escritas(cliente.base) == []


def test_as_janelas_coerentes_gravam_se(sessao):
    """`asJanelasCoerentesGravamSe`: a janela 1 guardada mais a 2 do pedido."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe(janelas=COM_JANELA_1)]))

    r = cliente.alterar(CAFE, {"janela2_inicio": "15:00", "janela2_fim": "19:00"})

    assert r.status_code == 200, r.text
    loja = r.json()
    assert [loja["janela1_inicio"], loja["janela1_fim"], loja["janela2_inicio"], loja["janela2_fim"]] == [
        "10:00", "13:00", "15:00", "19:00",
    ]
    assert _guardada(cliente.base)["janelas"] == [{"inicio": "10:00", "fim": "13:00"}, {"inicio": "15:00", "fim": "19:00"}]
    [(_, _, atualizacao, _)] = cliente.base.crm_lojas.chamadas("update_one")
    assert set(atualizacao["$set"]) == {"janelas", "atualizado_em"}, "As horas planas nunca se gravam."


def test_sem_mexer_nas_janelas_nao_se_verificam_as_guardadas(sessao, monkeypatch):
    """`semMexerNasJanelasNaoSeVerificamAsGuardadas` (correções do plano, linha
    "T2.11"). No autónomo, uma janela incompleta gravada antes por SQL não
    impedia outras alterações. No portal, uma janela a meio nem chega à base
    (`janelas_para_lista` recusa-a, e o `loja_api` dava 500 ao lê-la); o que
    se prova é que, sem horas no pedido, as guardadas nem se leem para a
    verificação — e que, com uma hora, se leem (o espião não é vazio)."""
    lidas = []

    def _espiao(lista):
        lidas.append(lista)
        return campos_de_janelas(lista)

    monkeypatch.setattr(rotas_lojas, "campos_de_janelas", _espiao)
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe(janelas=COM_JANELA_1)]))

    r = cliente.alterar(CAFE, {"telefone": "912 345 678", "nome": "Café Central 2"})
    assert r.status_code == 200, r.text
    assert lidas == []
    [(_, _, atualizacao, _)] = cliente.base.crm_lojas.chamadas("update_one")
    assert "janelas" not in atualizacao["$set"]

    r = cliente.alterar(CAFE, {"janela2_inicio": "15:00", "janela2_fim": "19:00"}, r.json()["atualizado_em"])
    assert r.status_code == 200, r.text
    assert lidas == [COM_JANELA_1]


# --- A região ------------------------------------------------------------------------------------------


def test_a_regiao_muda_se_existir(sessao):
    """`aRegiaoMudaSeExistir`: inexistente → 422; existente → 200; null = sem região."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe()], regioes=[_regiao(LISBOA, "Lisboa")]))

    r = cliente.alterar(CAFE, {"regiao_id": NAO_EXISTE})
    assert (r.status_code, r.json()) == (422, _validacao({"regiao_id": "A região não existe."}))
    assert cliente.base.crm_regioes.registo == [("find_one", {"id": NAO_EXISTE}, PROJECAO_ID)]
    assert _escritas(cliente.base) == []

    r = cliente.alterar(CAFE, {"regiao_id": LISBOA})
    assert r.status_code == 200, r.text
    assert r.json()["regiao_id"] == LISBOA

    r = cliente.alterar(CAFE, {"regiao_id": None}, r.json()["atualizado_em"])
    assert r.status_code == 200, r.text
    assert r.json()["regiao_id"] is None, "null = sem região."
    assert len(cliente.base.crm_regioes.registo) == 2, "Sem região não se procura a região."
    assert _guardada(cliente.base)["regiao_id"] is None


def test_sem_a_regiao_no_pedido_nao_se_procura_a_regiao(sessao):
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe(regiao_id=PORTO)]))
    assert cliente.alterar(CAFE, {"telefone": "912 345 678"}).status_code == 200
    assert cliente.base.crm_regioes.registo == []
    assert _guardada(cliente.base)["regiao_id"] == PORTO


def test_as_janelas_verificam_se_antes_da_regiao(sessao):
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe(janelas=COM_JANELA_1)]))
    r = cliente.alterar(CAFE, {"regiao_id": NAO_EXISTE, "janela1_inicio": "14:00"})

    assert (r.status_code, r.json()) == (422, _validacao({"janela1_fim": "O fim tem de ser depois do início."}))
    assert cliente.base.crm_regioes.registo == []


def test_a_regiao_verifica_se_antes_dos_duplicados(sessao):
    """Como no POST: a região que não existe dá 422 antes de procurar as vizinhas."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_loja(2, "Bar da Esquina", LAT), _loja(1, "Café", LAT_LONGE)]))
    r = cliente.alterar(CAFE, {**_pino(38.710890), "regiao_id": NAO_EXISTE})

    assert (r.status_code, r.json()) == (422, _validacao({"regiao_id": "A região não existe."}))
    assert cliente.base.crm_lojas.chamadas("find") == []


def test_a_regiao_verifica_se_mesmo_com_o_duplicado_confirmado(sessao):
    cliente = sessao(RUI_UTILIZADOR)
    r = cliente.alterar(CAFE, {**_pino(38.7109), "regiao_id": NAO_EXISTE, "confirmar_duplicado": True})
    assert (r.status_code, r.json()) == (422, _validacao({"regiao_id": "A região não existe."}))


# --- Os duplicados: só quando a loja muda de sítio ---------------------------------------------------


def test_mudar_as_coordenadas_para_junto_de_outra_loja_da_409_duplicado(sessao):
    """`mudarAsCoordenadasParaJuntoDeOutraLojaDa409Duplicado`: e nada muda."""
    vizinha = _loja(2, "Bar da Esquina", LAT)
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[vizinha, _loja(1, "Café Central", LAT_LONGE)]))

    r = cliente.alterar(CAFE, _pino(38.710890))

    assert r.status_code == 409
    assert r.json() == {"detail": {
        "codigo": "duplicado",
        "mensagem": "Já existe Bar da Esquina aqui — é a mesma?",
        "lojas": [{"id": vizinha["id"], "nome": "Bar da Esquina", "distancia_m": 10}],
    }}
    assert list(r.json()["detail"]) == ["codigo", "mensagem", "lojas"]
    guardada = _guardada(cliente.base)
    assert (guardada["lat"], guardada["atualizado_em"]) == (LAT_LONGE, VERSAO)
    assert _escritas(cliente.base) == []


def test_os_duplicados_procuram_se_pelo_pre_filtro_sem_a_propria_loja(sessao):
    """O `find` é o círculo de 60 m da T2.3 sem a própria loja (`excluir_id`),
    com só os campos que a regra dos 50 m usa."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_loja(2, "Bar da Esquina", LAT), _loja(1, "Café", LAT_LONGE)]))
    assert cliente.alterar(CAFE, _pino(38.710890)).status_code == 409
    assert cliente.base.crm_lojas.chamadas("find") == [
        ("find", filtro_candidatos(38.71089, LNG, excluir_id=CAFE), PROJECAO_CANDIDATO),
    ]


def test_com_confirmar_duplicado_as_coordenadas_mudam_na_mesma(sessao):
    """`comConfirmarDuplicadoAsCoordenadasMudamNaMesma`: e nem se procuram os duplicados."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_loja(2, "Bar da Esquina", LAT), _loja(1, "Café", LAT_LONGE)]))

    r = cliente.alterar(CAFE, {**_pino(38.710890), "confirmar_duplicado": True})

    assert r.status_code == 200, r.text
    assert r.json()["lat"] == 38.71089
    guardada = _guardada(cliente.base)
    assert (guardada["lat"], guardada["loc"]) == (38.71089, {"type": "Point", "coordinates": [LNG, 38.71089]})
    assert cliente.base.crm_lojas.chamadas("find") == []


NAO_CONFIRMAM = [
    ("false", False),
    ('texto "true"', "true"),
    ("o número 1", 1),
    ("null", None),
    ("o número 1.0", 1.0),
    ("uma lista com true", [True]),
]


@pytest.mark.parametrize("confirmar", [c[1] for c in NAO_CONFIRMAM], ids=[c[0] for c in NAO_CONFIRMAM])
def test_so_o_true_confirma_o_duplicado(sessao, confirmar):
    """Em Python, `1 == True`: compara-se com `is True`."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_loja(2, "Bar da Esquina", LAT), _loja(1, "Café", LAT_LONGE)]))
    r = cliente.alterar(CAFE, {**_pino(38.710890), "confirmar_duplicado": confirmar})

    assert r.status_code == 409
    assert _guardada(cliente.base)["lat"] == LAT_LONGE


def test_a_propria_loja_nao_conta_como_duplicado(sessao):
    """`aPropriaLojaNaoContaComoDuplicado`: mover o pino 10 m não é um duplicado de si mesma."""
    cliente = sessao(RUI_UTILIZADOR)

    r = cliente.alterar(CAFE, _pino(38.710890))

    assert r.status_code == 200, r.text
    assert r.json()["lat"] == 38.71089


SEM_MUDAR_AS_COORDENADAS = [
    ("outro campo", {"telefone": "912 345 678"}),
    ("as mesmas coordenadas, agora por GPS", {"lat": LAT, "lng": LNG, "origem_coords": "gps", "precisao_m": 8}),
    # As 6 casas que a base guarda: 38,7108004 arredonda a 38,7108.
    ("as mesmas às 6 casas", {"lat": 38.7108004, "lng": -9.1368996, "origem_coords": "pin_manual"}),
    ("as mesmas, agora pela morada", {"lat": LAT, "lng": LNG, "origem_coords": "geocoder"}),
]


@pytest.mark.parametrize(
    "alteracoes", [c[1] for c in SEM_MUDAR_AS_COORDENADAS], ids=[c[0] for c in SEM_MUDAR_AS_COORDENADAS]
)
def test_sem_mudar_as_coordenadas_nao_se_procuram_duplicados(sessao, alteracoes):
    """`semMudarAsCoordenadasNaoSeProcuramDuplicados`: o duplicado a 10 m já foi
    confirmado quando a loja se gravou."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_loja(2, "Bar da Esquina", 38.710710), _cafe()]))

    r = cliente.alterar(CAFE, alteracoes)

    assert r.status_code == 200, r.text
    assert cliente.base.crm_lojas.chamadas("find") == []


def test_mudar_so_a_longitude_tambem_e_mudar_de_sitio(sessao):
    """O `mudouDeSitio` compara a latitude OU a longitude."""
    vizinha = _loja(2, "Bar da Esquina", LAT, -9.136800)
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[vizinha, _loja(1, "Café", LAT, -9.137800)]))

    r = cliente.alterar(CAFE, {"lat": LAT, "lng": -9.136900, "origem_coords": "pin_manual"})

    assert r.status_code == 409
    assert r.json()["detail"]["lojas"] == [{"id": vizinha["id"], "nome": "Bar da Esquina", "distancia_m": 9}]


def test_mudar_so_na_sexta_casa_tambem_e_mudar_de_sitio(sessao):
    """0,000001° (≈ 0,1 m) já é outro sítio para a base, que guarda 6 casas."""
    bar = _loja(2, "Bar da Esquina", 38.710710)
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[bar, _cafe()]))

    r = cliente.alterar(CAFE, _pino(38.710801))

    assert r.status_code == 409
    assert r.json()["detail"]["lojas"] == [{"id": bar["id"], "nome": "Bar da Esquina", "distancia_m": 10}]


def test_uma_loja_gravada_com_coordenadas_inteiras_nao_muda_de_sitio_com_as_mesmas(sessao):
    """Um 39 gravado à mão (int) e o 39.0 do pedido são o mesmo sítio às 6 casas."""
    inteira = _loja(1, "Café", 39, -8)
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[inteira, _loja(2, "Bar", 39.00001, -8.0)]))
    assert cliente.alterar(CAFE, {"lat": 39.0, "lng": -8.0, "origem_coords": "gps", "precisao_m": 3}).status_code == 200
    assert cliente.base.crm_lojas.chamadas("find") == []


def test_uma_loja_escrita_a_mao_com_mais_casas_compara_se_nas_6_casas(sessao):
    """O `mudouDeSitio` compara as 6 casas que a base guarda (o `sprintf('%.6F')`
    do autónomo): uma loja escrita à mão no mongosh com 38,7108001 está no
    mesmo sítio que o 38,7108 do pedido, e não se procuram duplicados."""
    escrita_a_mao = _loja(1, "Café", 38.7108001, -9.1369001)
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[escrita_a_mao, _loja(2, "Bar da Esquina", 38.710710)]))

    assert cliente.alterar(CAFE, {"lat": LAT, "lng": LNG, "origem_coords": "gps", "precisao_m": 5}).status_code == 200
    assert cliente.base.crm_lojas.chamadas("find") == []


LOCALIZACOES_INVALIDAS = [
    ("GPS com precisão de 80 m", {"lat": 38.710890, "lng": LNG, "origem_coords": "gps", "precisao_m": 80},
     {"precisao_m": "Localização imprecisa — ajuste o pino"}),
    ("só a latitude", {"lat": 38.710890}, {"lng": INCOMPLETA, "origem_coords": INCOMPLETA}),
    ("fora de Portugal", {"lat": 40.4168, "lng": -3.7038, "origem_coords": "pin_manual"},
     {"lng": "Fora de Portugal"}),
]


@pytest.mark.parametrize(
    "alteracoes, campos", [c[1:] for c in LOCALIZACOES_INVALIDAS], ids=[c[0] for c in LOCALIZACOES_INVALIDAS]
)
def test_uma_localizacao_invalida_da_422(sessao, alteracoes, campos):
    """`umaLocalizacaoInvalidaDa422`: e sem ler a base."""
    cliente = sessao(RUI_UTILIZADOR)

    r = cliente.alterar(CAFE, alteracoes)

    assert (r.status_code, r.json()) == (422, _validacao(campos))
    assert _guardada(cliente.base)["lat"] == LAT
    assert cliente.base.crm_lojas.registo == []


# --- A ordem das verificações (correções do plano, linha "T2.11") -------------------------------------


def test_uma_versao_velha_com_coordenadas_junto_de_outra_loja_da_409_conflito_sem_procurar_duplicados(sessao):
    """O 409 conflito ganha ao duplicado: os duplicados seriam calculados sobre
    a loja de outra versão."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[
        _loja(2, "Bar da Esquina", LAT), _loja(1, "Café", LAT_LONGE, atualizado_em=VERSAO_DE_OUTRA_PESSOA),
    ]))

    r = cliente.alterar(CAFE, _pino(38.710890))

    assert (r.status_code, r.json()) == (409, CONFLITO)
    assert cliente.base.crm_lojas.registo == [("find_one", {"id": CAFE}, PROJECAO_LOJA)]


def test_uma_versao_velha_com_janelas_incoerentes_da_409_conflito(sessao):
    """O 409 conflito ganha ao 422 das janelas, que seria calculado sobre as
    horas de outra versão."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe(janelas=COM_JANELA_1, atualizado_em=VERSAO_DE_OUTRA_PESSOA)]))
    r = cliente.alterar(CAFE, {"janela1_inicio": "14:00"})
    assert (r.status_code, r.json()) == (409, CONFLITO)


def test_uma_versao_velha_com_uma_regiao_que_nao_existe_da_409_conflito_sem_procurar_a_regiao(sessao):
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe(atualizado_em=VERSAO_DE_OUTRA_PESSOA)]))
    r = cliente.alterar(CAFE, {"regiao_id": NAO_EXISTE})
    assert (r.status_code, r.json()) == (409, CONFLITO)
    assert cliente.base.crm_regioes.registo == []


def test_as_janelas_verificam_se_antes_dos_duplicados(sessao):
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[
        _loja(2, "Bar da Esquina", LAT), _loja(1, "Café", LAT_LONGE, janelas=COM_JANELA_1),
    ]))
    r = cliente.alterar(CAFE, {**_pino(38.710890), "janela1_fim": None})

    assert (r.status_code, r.json()) == (422, _validacao({"janela1_fim": "Indique também o fim."}))
    assert cliente.base.crm_lojas.chamadas("find") == []


# --- Quem pode -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "utilizador", [ADMIN_MASTER, ANA_ADMIN_DO_CRM, RUI_UTILIZADOR], ids=["admin master", "admin", "utilizador"]
)
def test_o_escritorio_edita(sessao, utilizador):
    cliente = sessao(utilizador)
    r = cliente.alterar(CAFE, {"fase": "contactada"})
    assert r.status_code == 200, r.text
    [interacao] = cliente.base.crm_interacoes.docs
    assert interacao["utilizador_id"] == utilizador["user_id"]


def test_o_motorista_nao_edita_lojas_na_f2(sessao):
    """As correções do terreno chegam na F4 (plano §1, "Perfis por rota")."""
    cliente = sessao(ALVARO_MOTORISTA)
    r = cliente.alterar(CAFE, {"telefone": "912 345 678"})
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)
    assert cliente.base.crm_lojas.registo == []


def test_quem_nao_e_membro_recebe_403_sem_acesso(sessao):
    cliente = sessao(BEA_NAO_MEMBRO)
    r = cliente.alterar(CAFE, {"telefone": "912 345 678"})
    assert (r.status_code, r.json()) == (403, SEM_ACESSO)
    assert cliente.base.crm_lojas.registo == []


@pytest.mark.parametrize(
    "utilizador, esperado", [(ALVARO_MOTORISTA, SEM_PERMISSAO), (BEA_NAO_MEMBRO, SEM_ACESSO)],
    ids=["motorista", "não membro"],
)
def test_sem_perfil_e_com_json_partido_da_403_e_nunca_400(sessao, utilizador, esperado):
    r = sessao(utilizador).patch(f"{LOJAS_URL}/{CAFE}", content=b"[", headers=JSON)
    assert (r.status_code, r.json()) == (403, esperado)


@pytest.mark.parametrize(
    "bruto", [b"[]", b"null", b'"loja"', b"{partido", b'{"notas": "x\\udc00", "atualizado_em": "' + VERSAO.encode() + b'"}'],
    ids=["lista", "null", "texto", "partido", "surrogate sozinho"],
)
def test_alterar_com_um_corpo_que_nao_e_um_objeto_json_da_400(sessao, bruto):
    cliente = sessao(RUI_UTILIZADOR)
    r = cliente.patch(f"{LOJAS_URL}/{CAFE}", content=bruto, headers=JSON)
    assert (r.status_code, r.json()) == (400, JSON_INVALIDO)
    assert cliente.base.crm_lojas.registo == []


# --- De ponta a ponta: a sessão verdadeira do portal ---------------------------------------------

SEGREDO = "segredo-de-teste-crm-lojas-editar"
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
    base = _base(lojas=[_loja(2, "Bar da Esquina", LAT), _loja(1, "Café Central", LAT_LONGE)],
                 regioes=[_regiao(LISBOA, "Lisboa")])
    monkeypatch.setattr(faturacao.auth, "obter_db", lambda: base)
    monkeypatch.setattr(crm.db, "obter_db", lambda: base)
    app = FastAPI()
    app.include_router(crm.router)
    cliente = TestClient(app)
    cliente.base = base
    return cliente


def test_sem_sessao_da_o_403_herdado_e_nada_muda(portal):
    """`semSessaoDa401ENadaMuda`: no portal, sem cabeçalho é o 403 do
    HTTPBearer (também com JSON partido, nunca 400)."""
    for pedido in (
        portal.patch(f"{LOJAS_URL}/{CAFE}", json={"telefone": "912 345 678", "atualizado_em": VERSAO}),
        portal.patch(f"{LOJAS_URL}/{CAFE}", content=b"[", headers=JSON),
    ):
        assert (pedido.status_code, pedido.json()) == (403, {"detail": "Not authenticated"})
    assert portal.base.crm_lojas.registo == []
    assert _guardada(portal.base)["telefone"] is None


def test_uma_conta_apagada_da_401_sessao_terminada(portal):
    r = portal.patch(
        f"{LOJAS_URL}/{CAFE}", json={"telefone": "912 345 678", "atualizado_em": VERSAO},
        headers=_cabecalho("u-apagada"),
    )
    assert (r.status_code, r.json()) == (401, {"detail": "Sessão terminada"})
    assert portal.base.crm_lojas.registo == []


def test_de_ponta_a_ponta_editar_mudar_a_fase_e_receber_o_conflito(portal):
    rui = _cabecalho("u-rui")
    ana = _cabecalho("u-ana", email="ana@example.com")
    url = f"{LOJAS_URL}/{CAFE}"

    r = portal.patch(url, json={"telefone": "912 345 678", "atualizado_em": VERSAO}, headers=_cabecalho("u-alv"))
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)

    r = portal.patch(url, json={**_pino(38.710890), "atualizado_em": VERSAO}, headers=rui)
    assert r.status_code == 409
    assert r.json()["detail"]["lojas"] == [{"id": _id(2), "nome": "Bar da Esquina", "distancia_m": 10}]

    r = portal.patch(url, json={"fase": "cliente", "regiao_id": LISBOA, "atualizado_em": VERSAO}, headers=rui)
    assert r.status_code == 200, r.text
    alterada = r.json()
    assert (alterada["fase"], alterada["fase_desde"], alterada["regiao_id"], alterada["atualizado_em"]) == (
        "cliente", AGORA_INSTANTE, LISBOA, AGORA_CARIMBO,
    )

    r = portal.patch(url, json={"telefone": "213 456 789", "atualizado_em": VERSAO}, headers=ana)
    assert (r.status_code, r.json()) == (409, CONFLITO)

    admin = _cabecalho("u-admin", email=ADMIN_LOCAL, role="admin")
    assert portal.get(url, headers=admin).json() == alterada
    assert [i["resultado"] for i in portal.base.crm_interacoes.sem_id()] == ["potencial→cliente"]
    assert portal.base.crm_interacoes.sem_id()[0]["utilizador_id"] == "u-rui"
    assert [instantes_fora_do_formato(d) for d in portal.base.crm_lojas.sem_id()] == [[], []]
    assert [instantes_fora_do_formato(d) for d in portal.base.crm_interacoes.sem_id()] == [[]]
