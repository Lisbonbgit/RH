"""`/api/crm/definicoes` — as definições da fábrica e (F3, T3.5) das rotas, só
para o admin do CRM (plano T2.13; dossiê §5.9 e §6).

Porta de tests/Integration/Api/DefinicoesTest.php do CRM autónomo (etiqueta
`referencia-standalone`): todos os casos, com os nomes de lá. As regras do
corpo (morada aparada até 255 caracteres, lat e lng juntas, 6 casas, Portugal
continental, "Esta definição não existe.") já estão provadas no domínio
(test_dominio_definicoes.py, T2.7); aqui prova-se a rota: quem entra, o que
lê, o que grava, por que ordem, e o que responde. Adaptações ao portal:

- Só o admin do CRM (o admin master e os membros admin); o utilizador e o
  motorista recebem 403 `sem_permissao`, quem não é membro 403
  `sem_acesso_crm`. Sem sessão, os 403/401 herdados do portal, em vez do 401
  `nao_autenticado` do autónomo.
- `crm_definicoes` guarda `{chave, valor (texto), atualizado_em,
  atualizado_por}` com upsert por `chave` (plano §3); o `atualizado_em` é um
  carimbo de 6 casas em UTC (plano §1; o autónomo usava `DATETIME` sem casas).
- Sem transações (o autónomo gravava tudo numa): cada chave grava-se pela
  ordem dos `PADROES`; uma falha a meio responde 500 e deixa gravadas as
  anteriores, e repetir o pedido acerta (os upserts são idempotentes).
- O `Cache-Control: no-store, private` do autónomo não se porta (a mesma
  diferença assumida da T2.9, dossiê §5.8).

Rotas por `TestClient` com `dependency_overrides[utilizador_atual]` e
`monkeypatch.setattr(crm.db, "obter_db", …)` (plano §10); a corrida com duas
corrotinas no duplo (`correr`, nunca `asyncio.run`); no fim, de ponta a ponta
com a sessão verdadeira do portal (JWT + conta lida da base).
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import crm
import crm.db
import faturacao.auth
from crm import definicoes as rotas_definicoes
from crm import relogio
from crm.auth import SO_ADMIN, membro_crm_atual
from crm.pedidos import corpo_json
from faturacao.auth import utilizador_atual

from .duplos import BaseFalsa, ColeccaoFalsa, correr, unicos_declarados
from .formatos import instantes_fora_do_formato

DEFINICOES_URL = "/api/crm/definicoes"
ADMIN_LOCAL = "admin.local@example.com"
JSON = {"Content-Type": "application/json"}

UTC = timezone.utc
AGORA = datetime(2026, 10, 10, 9, 30, 15, 987654, tzinfo=UTC)
AGORA_CARIMBO = "2026-10-10T09:30:15.987654Z"
AGORA_DO_RELOGIO = relogio.agora  # o verdadeiro, antes de qualquer monkeypatch

# O corpo exato do `semNadaAlteradoOAdminVeOsPadroes` (lá dentro de "dados"),
# com as 6 chaves das rotas da F3 (plano F3, T3.5: os minutos como inteiros).
PADROES_TEXTO = (
    '{"fabrica_morada":"","fabrica_lat":38.7223,"fabrica_lng":-9.1393,'
    '"rota_hora_saida":"08:00","rota_hora_regresso":"19:00",'
    '"servico_entrega_min":10,"servico_amostra_min":10,"servico_acompanhamento_min":15,"servico_angariacao_min":15}'
)
PADROES_ROTAS = {
    "rota_hora_saida": "08:00", "rota_hora_regresso": "19:00", "servico_entrega_min": 10, "servico_amostra_min": 10,
    "servico_acompanhamento_min": 15, "servico_angariacao_min": 15,
}
PADROES = {"fabrica_morada": "", "fabrica_lat": 38.7223, "fabrica_lng": -9.1393, **PADROES_ROTAS}
CHAVES = list(PADROES)
TEMPO = "O tempo de serviço é um número inteiro de minutos, de 1 a 240."
HORA = "Indique a hora no formato HH:MM."
FORA = "Fora de Portugal"

PROJECAO_GUARDADA = {"_id": 0, "chave": 1, "valor": 1}

SEM_PERMISSAO = {"detail": {"codigo": "sem_permissao", "mensagem": "Sem permissão para esta ação."}}
SEM_ACESSO = {"detail": {"codigo": "sem_acesso_crm", "mensagem": "Sem acesso ao CRM."}}
JSON_INVALIDO = {"detail": {"codigo": "json_invalido", "mensagem": "O pedido não é JSON válido."}}


def _validacao(campos):
    return {"detail": {"codigo": "validacao", "mensagem": "Verifique os campos assinalados.", "campos": campos}}


def _guardada(chave, valor, quando="2026-10-01T08:00:00.000000Z", por="u-ana"):
    """Uma definição como fica gravada (escrita à mão, de propósito)."""
    return {"chave": chave, "valor": valor, "atualizado_em": quando, "atualizado_por": por}


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

# O `pedidos` do autónomo: as duas rotas, com um corpo válido para o PATCH.
PEDIDOS = [("GET", None), ("PATCH", {"fabrica_morada": "Rua A"})]
IDS_PEDIDOS = ["GET", "PATCH"]


def _base(guardadas=(), membros=MEMBROS, users=USERS):
    return BaseFalsa({
        "crm_membros": list(membros),
        "users": list(users),
        "crm_definicoes": list(guardadas),
    })


def _definicoes_falsas(classe=ColeccaoFalsa, guardadas=(), **kw):
    """Uma `crm_definicoes` feita à mão, com o `chave` único dos índices."""
    return classe(list(guardadas), unicos=unicos_declarados("crm_definicoes"), nome="crm_definicoes", **kw)


def _guardadas(base):
    """`{chave: valor}` do que está em crm_definicoes, por chave (o `guardadas()` do autónomo)."""
    return {d["chave"]: d["valor"] for d in sorted(base.crm_definicoes.docs, key=lambda d: d["chave"])}


def _escritas(base):
    return [c for c in base.crm_definicoes.registo if c[0] in ("insert_one", "update_one", "delete_one", "delete_many")]


def _pedir(cliente, metodo, url, corpo, headers=None):
    if corpo is None:
        return cliente.request(metodo, url, headers=headers)
    return cliente.request(metodo, url, json=corpo, headers=headers)


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
    (com `cliente.base`); para outra pessoa na mesma base,
    `sessao(outra, cliente.base)`."""
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


@pytest.mark.parametrize("metodo", ["GET", "PATCH"])
def test_as_rotas_existem_e_vivem_em_crm_definicoes(metodo):
    rota = _rota(DEFINICOES_URL, metodo)
    assert rota.methods == {metodo}
    assert rota.endpoint.__module__ == "crm.definicoes"


@pytest.mark.parametrize("metodo", ["GET", "PATCH"])
def test_so_o_admin_do_crm_ve_e_muda_as_definicoes(metodo):
    """Exatamente uma guarda de perfil, sobre `membro_crm_atual`."""
    dependencias = _dependencias(_rota(DEFINICOES_URL, metodo))
    assert membro_crm_atual in dependencias
    assert [d for d in dependencias if hasattr(d, "perfis_crm")] == [SO_ADMIN]


def test_a_guarda_de_perfil_vem_antes_do_corpo():
    """Correções do plano, linha "T1.3 / T2.15"."""
    diretas = [d.call for d in _rota(DEFINICOES_URL, "PATCH").dependant.dependencies]
    assert diretas == [SO_ADMIN, corpo_json]


def test_ver_nao_le_o_corpo():
    assert corpo_json not in _dependencias(_rota(DEFINICOES_URL, "GET"))


# --- GET /definicoes --------------------------------------------------------------------------


def test_sem_nada_alterado_o_admin_ve_os_padroes(sessao):
    """`semNadaAlteradoOAdminVeOsPadroes`: o corpo exato, com as coordenadas
    como números e pela ordem morada, lat, lng."""
    r = sessao(ADMIN_MASTER).get(DEFINICOES_URL)
    assert r.status_code == 200
    assert r.text == PADROES_TEXTO


def test_ver_mostra_o_que_esta_guardado_por_cima_dos_padroes(sessao):
    base = _base([
        _guardada("fabrica_lng", "-8.611000"),
        _guardada("fabrica_morada", "Rua das Flores 1, Porto"),
        _guardada("fabrica_lat", "41.149600"),
    ])
    r = sessao(ANA_ADMIN_DO_CRM, base).get(DEFINICOES_URL)
    assert r.status_code == 200
    assert list(r.json().items()) == [
        ("fabrica_morada", "Rua das Flores 1, Porto"), ("fabrica_lat", 41.1496), ("fabrica_lng", -8.611),
        *PADROES_ROTAS.items(),
    ]
    assert [type(v) for v in r.json().values()] == [str, float, float, str, str, int, int, int, int]


def test_so_a_morada_guardada_e_o_ponto_fica_o_padrao(sessao):
    base = _base([_guardada("fabrica_morada", "Rua A")])
    assert sessao(ADMIN_MASTER, base).get(DEFINICOES_URL).json() == {**PADROES, "fabrica_morada": "Rua A"}


def test_ver_pede_so_a_chave_e_o_valor(sessao):
    """Uma leitura só, de tudo o que está guardado (o `SELECT chave, valor
    FROM definicoes` do autónomo), sem o `_id`, a hora nem quem alterou."""
    cliente = sessao(ADMIN_MASTER, _base([_guardada("fabrica_morada", "Rua A")]))
    assert cliente.get(DEFINICOES_URL).status_code == 200
    assert cliente.base.crm_definicoes.registo == [("find", {}, PROJECAO_GUARDADA)]


def test_ver_ignora_as_chaves_que_esta_versao_nao_conhece(sessao):
    """Gravadas por uma versão mais nova (ex.: uma chave de uma fase futura): não saem."""
    base = _base([_guardada("hora_saida", "08:00"), _guardada("fabrica_morada", "Rua A")])
    r = sessao(ADMIN_MASTER, base).get(DEFINICOES_URL)
    assert list(r.json()) == CHAVES
    assert r.json()["fabrica_morada"] == "Rua A"


def test_um_numero_escrito_a_mao_na_base_le_se_como_numero(sessao):
    base = _base([_guardada("fabrica_lat", 41), _guardada("fabrica_lng", -8.5)])
    r = sessao(ADMIN_MASTER, base).get(DEFINICOES_URL)
    assert (r.status_code, r.json()["fabrica_lat"], r.json()["fabrica_lng"]) == (200, 41.0, -8.5)


@pytest.mark.parametrize(
    "estragada",
    [
        {"chave": "fabrica_lat", "valor": None},
        {"chave": "fabrica_lat", "valor": True},
        {"chave": "fabrica_lat", "valor": ["41.1"]},
        {"chave": "fabrica_lat", "valor": {"$numberDouble": "41.1"}},
        {"chave": "fabrica_lat"},
        {"valor": "41.1"},
        {"chave": None, "valor": "41.1"},
        {"chave": ["fabrica_lat"], "valor": "41.1"},
    ],
    ids=["valor null", "valor bool", "valor lista", "valor objeto", "sem valor", "sem chave",
         "chave null", "chave lista"],
)
def test_uma_definicao_estragada_na_base_ignora_se_e_fica_o_padrao(sessao, caplog, estragada):
    """O CRM só grava `{chave de texto, valor de texto}`. Uma linha estragada à
    mão não pode dar 500: o `/config` lê as mesmas definições e todo o
    escritório ficava sem mapa. Ignora-se, com uma linha `[crm]` no registo
    só com a contagem (nada do que lá está)."""
    base = _base([estragada, _guardada("fabrica_morada", "Rua A")])
    with caplog.at_level(logging.DEBUG, logger="crm"):
        r = sessao(ADMIN_MASTER, base).get(DEFINICOES_URL)
    assert (r.status_code, r.json()) == (200, {**PADROES, "fabrica_morada": "Rua A"})
    registos = [registo for registo in caplog.records if registo.name.startswith("crm")]
    assert [(registo.levelname, registo.getMessage()) for registo in registos] == [
        ("WARNING", "[crm] definições guardadas ignoradas por estarem estragadas: 1"),
    ]
    assert "41.1" not in caplog.text


def test_sem_definicoes_estragadas_nao_ha_nada_no_registo(sessao, caplog):
    with caplog.at_level(logging.DEBUG, logger="crm"):
        sessao(ADMIN_MASTER, _base([_guardada("fabrica_morada", "Rua A")])).get(DEFINICOES_URL)
    assert [registo for registo in caplog.records if registo.name.startswith("crm")] == []


@pytest.mark.parametrize("utilizador", [ADMIN_MASTER, ANA_ADMIN_DO_CRM], ids=["admin master", "membro admin"])
def test_o_admin_master_e_os_membros_admin_veem_e_mudam(sessao, utilizador):
    cliente = sessao(utilizador)
    assert cliente.get(DEFINICOES_URL).status_code == 200
    assert cliente.patch(DEFINICOES_URL, json={"fabrica_morada": "Rua A"}).status_code == 200


def test_ver_quando_a_base_falha_e_um_erro(sessao):
    base = BaseFalsa({
        "crm_membros": list(MEMBROS),
        "crm_definicoes": _definicoes_falsas(falhar={"find": RuntimeError("base em baixo")}),
    })
    assert sessao(ADMIN_MASTER, base, levantar=False).get(DEFINICOES_URL).status_code == 500


# --- Quem pode ver e mudar ------------------------------------------------------------------------


@pytest.mark.parametrize("metodo, corpo", PEDIDOS, ids=IDS_PEDIDOS)
@pytest.mark.parametrize("utilizador", [ZE_UTILIZADOR, ALVARO_MOTORISTA], ids=["utilizador", "motorista"])
def test_um_utilizador_recebe_403_e_nada_muda(sessao, metodo, corpo, utilizador):
    """`umUtilizadorRecebe403ENadaMuda`: e nem se leu a coleção."""
    cliente = sessao(utilizador, _base([_guardada("fabrica_morada", "Rua A")]))
    antes = cliente.base.crm_definicoes.sem_id()
    r = _pedir(cliente, metodo, DEFINICOES_URL, corpo)
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)
    assert cliente.base.crm_definicoes.sem_id() == antes
    assert cliente.base.crm_definicoes.registo == []


@pytest.mark.parametrize("metodo, corpo", PEDIDOS, ids=IDS_PEDIDOS)
def test_quem_nao_e_membro_recebe_403_sem_acesso_e_nada_muda(sessao, metodo, corpo):
    cliente = sessao(BEA_NAO_MEMBRO)
    r = _pedir(cliente, metodo, DEFINICOES_URL, corpo)
    assert (r.status_code, r.json()) == (403, SEM_ACESSO)
    assert cliente.base.crm_definicoes.registo == []


@pytest.mark.parametrize(
    "utilizador, esperado",
    [(ZE_UTILIZADOR, SEM_PERMISSAO), (BEA_NAO_MEMBRO, SEM_ACESSO)],
    ids=["sem perfil", "não membro"],
)
def test_sem_perfil_e_com_json_partido_da_403_e_nunca_400(sessao, utilizador, esperado):
    r = sessao(utilizador).patch(DEFINICOES_URL, content=b"[", headers=JSON)
    assert (r.status_code, r.json()) == (403, esperado)


# --- PATCH /definicoes --------------------------------------------------------------------------


def test_o_admin_guarda_a_morada_e_o_ponto_da_fabrica(sessao):
    """`oAdminGuardaAMoradaEOPontoDaFabrica`: a morada aparada, as
    coordenadas em texto com 6 casas, e o GET a seguir igual à resposta."""
    esperado = {**PADROES, "fabrica_morada": "Rua das Flores 1, Porto", "fabrica_lat": 41.1496, "fabrica_lng": -8.611}
    cliente = sessao(ADMIN_MASTER)
    r = cliente.patch(DEFINICOES_URL, json={
        "fabrica_morada": "  Rua das Flores 1, Porto ",
        "fabrica_lat": 41.1496,
        "fabrica_lng": -8.611,
    })
    assert (r.status_code, r.json()) == (200, esperado)
    assert list(r.json()) == CHAVES
    assert _guardadas(cliente.base) == {
        "fabrica_lat": "41.149600",
        "fabrica_lng": "-8.611000",
        "fabrica_morada": "Rua das Flores 1, Porto",
    }
    assert cliente.get(DEFINICOES_URL).json() == esperado


def test_a_hora_da_alteracao_guarda_se_em_utc(sessao, monkeypatch):
    """`aHoraDaAlteracaoGuardaSeEmUtc`: com o relógio em Lisboa (UTC+1 em
    outubro), o carimbo é o de UTC, com as 6 casas (plano §1)."""
    lisboa = datetime(2026, 10, 10, 10, 30, 15, 987654, tzinfo=ZoneInfo("Europe/Lisbon"))
    cliente = sessao(ADMIN_MASTER)
    monkeypatch.setattr(relogio, "agora", lambda: lisboa)
    assert cliente.patch(DEFINICOES_URL, json={"fabrica_morada": "Rua A"}).status_code == 200
    (guardada,) = cliente.base.crm_definicoes.sem_id()
    assert guardada["atualizado_em"] == "2026-10-10T09:30:15.987654Z"
    assert instantes_fora_do_formato(guardada) == []


def test_com_o_relogio_verdadeiro_a_hora_e_a_do_pedido(sessao, monkeypatch):
    cliente = sessao(ADMIN_MASTER)
    monkeypatch.setattr(relogio, "agora", AGORA_DO_RELOGIO)
    antes = relogio.carimbo(AGORA_DO_RELOGIO())
    assert cliente.patch(DEFINICOES_URL, json={"fabrica_lat": 41.1496, "fabrica_lng": -8.611}).status_code == 200
    depois = relogio.carimbo(AGORA_DO_RELOGIO())
    for guardada in cliente.base.crm_definicoes.sem_id():
        assert antes <= guardada["atualizado_em"] <= depois
        assert instantes_fora_do_formato(guardada) == []


def test_cada_definicao_guarda_a_chave_o_valor_a_hora_e_quem_alterou(sessao):
    """O documento de `crm_definicoes` (plano §3): só estes quatro campos (e o
    `_id` do Mongo); `atualizado_por` é o id da conta do portal."""
    cliente = sessao(ANA_ADMIN_DO_CRM)
    cliente.patch(DEFINICOES_URL, json={"fabrica_morada": "Rua A", "fabrica_lat": 41.1496, "fabrica_lng": -8.611})
    assert cliente.base.crm_definicoes.sem_id() == [
        {"chave": "fabrica_morada", "valor": "Rua A", "atualizado_em": AGORA_CARIMBO, "atualizado_por": "u-ana"},
        {"chave": "fabrica_lat", "valor": "41.149600", "atualizado_em": AGORA_CARIMBO, "atualizado_por": "u-ana"},
        {"chave": "fabrica_lng", "valor": "-8.611000", "atualizado_em": AGORA_CARIMBO, "atualizado_por": "u-ana"},
    ]
    assert [instantes_fora_do_formato(d) for d in cliente.base.crm_definicoes.docs] == [[], [], []]


def test_grava_pela_ordem_dos_padroes_com_upsert_por_chave_e_depois_rele(sessao):
    """Uma escrita por chave, pela ordem morada, lat, lng (mesmo com o corpo
    ao contrário), cada uma um upsert pela `chave`; depois relê tudo para
    responder com as definições em vigor (dossiê §5.9)."""
    cliente = sessao(ADMIN_MASTER)
    r = cliente.patch(DEFINICOES_URL, json={"fabrica_lng": -8.611, "fabrica_lat": 41.1496, "fabrica_morada": "Rua A"})
    assert r.status_code == 200

    def _escrita(chave, valor):
        return (
            "update_one",
            {"chave": chave},
            {"$set": {"valor": valor, "atualizado_em": AGORA_CARIMBO, "atualizado_por": "u-admin"}},
            True,
        )

    assert cliente.base.crm_definicoes.registo == [
        _escrita("fabrica_morada", "Rua A"),
        _escrita("fabrica_lat", "41.149600"),
        _escrita("fabrica_lng", "-8.611000"),
        ("find", {}, PROJECAO_GUARDADA),
    ]


def test_um_so_agora_por_pedido_mesmo_com_o_relogio_a_andar(sessao, monkeypatch):
    """As três chaves da mesma alteração ficam com a mesma hora (o `$quando`
    do `DefinicoesRepositorio::gravar`)."""
    leituras = []

    def _relogio_a_andar():
        leituras.append(1)
        return AGORA if len(leituras) == 1 else datetime(2026, 10, 10, 9, 30, 20, 0, tzinfo=UTC)

    cliente = sessao(ADMIN_MASTER)
    monkeypatch.setattr(relogio, "agora", _relogio_a_andar)
    cliente.patch(DEFINICOES_URL, json={"fabrica_morada": "Rua A", "fabrica_lat": 41.1496, "fabrica_lng": -8.611})
    assert len(leituras) == 1
    assert [d["atualizado_em"] for d in cliente.base.crm_definicoes.docs] == [AGORA_CARIMBO] * 3


def test_so_muda_o_que_vem_no_pedido_e_uma_segunda_alteracao_substitui_a_primeira(sessao):
    """`soMudaOQueVemNoPedidoEUmaSegundaAlteracaoSubstituiAPrimeira`."""
    cliente = sessao(ADMIN_MASTER)
    cliente.patch(DEFINICOES_URL, json={"fabrica_lat": 41.1496, "fabrica_lng": -8.611})
    cliente.patch(DEFINICOES_URL, json={"fabrica_morada": "Rua A"})

    r = cliente.patch(DEFINICOES_URL, json={"fabrica_morada": "Rua B"})

    assert (r.status_code, r.json()) == (
        200, {**PADROES, "fabrica_morada": "Rua B", "fabrica_lat": 41.1496, "fabrica_lng": -8.611},
    )
    assert _guardadas(cliente.base) == {
        "fabrica_lat": "41.149600", "fabrica_lng": "-8.611000", "fabrica_morada": "Rua B",
    }
    # Uma linha por chave: o upsert substitui, não acrescenta.
    assert len(cliente.base.crm_definicoes.docs) == 3


def test_a_segunda_alteracao_muda_a_hora_e_quem_alterou_so_da_chave_que_veio(sessao, monkeypatch):
    base = _base([
        _guardada("fabrica_morada", "Rua A", por="u-ana"),
        _guardada("fabrica_lat", "41.149600", por="u-ana"),
        _guardada("fabrica_lng", "-8.611000", por="u-ana"),
    ])
    cliente = sessao(ADMIN_MASTER, base)
    r = cliente.patch(DEFINICOES_URL, json={"fabrica_morada": "Rua B"})
    assert r.status_code == 200
    assert cliente.base.crm_definicoes.sem_id() == [
        _guardada("fabrica_morada", "Rua B", quando=AGORA_CARIMBO, por="u-admin"),
        _guardada("fabrica_lat", "41.149600", por="u-ana"),
        _guardada("fabrica_lng", "-8.611000", por="u-ana"),
    ]


def test_responde_com_as_definicoes_em_vigor_tambem_as_que_nao_vieram(sessao):
    """O ponto muda e a morada guardada antes vem na resposta, tal como está
    na base (a resposta é o que se releu, não o pedido)."""
    cliente = sessao(ADMIN_MASTER, _base([_guardada("fabrica_morada", "Rua das Flores 1, Porto")]))
    r = cliente.patch(DEFINICOES_URL, json={"fabrica_lat": 41.1496, "fabrica_lng": -8.611})
    assert r.json() == {
        **PADROES, "fabrica_morada": "Rua das Flores 1, Porto", "fabrica_lat": 41.1496, "fabrica_lng": -8.611,
    }


class _OutroAdminMudaAMoradaDepoisDaEscrita(ColeccaoFalsa):
    """Entre as escritas deste pedido e a releitura, outro admin muda a morada."""

    async def update_one(self, filtro, atualizacao, upsert=False):
        resultado = await super().update_one(filtro, atualizacao, upsert)
        if filtro == {"chave": "fabrica_lng"}:
            await super().update_one(
                {"chave": "fabrica_morada"},
                {"$set": {"valor": "Rua do Outro", "atualizado_em": AGORA_CARIMBO, "atualizado_por": "u-ana"}},
                True,
            )
        return resultado


def test_a_resposta_e_o_que_se_releu_da_base_e_nao_o_pedido(sessao):
    base = BaseFalsa({
        "crm_membros": list(MEMBROS),
        "crm_definicoes": _definicoes_falsas(_OutroAdminMudaAMoradaDepoisDaEscrita),
    })
    r = sessao(ADMIN_MASTER, base).patch(
        DEFINICOES_URL, json={"fabrica_morada": "Rua A", "fabrica_lat": 41.1496, "fabrica_lng": -8.611}
    )
    assert r.json() == {**PADROES, "fabrica_morada": "Rua do Outro", "fabrica_lat": 41.1496, "fabrica_lng": -8.611}


def test_gravar_o_mesmo_valor_outra_vez_da_200_e_muda_a_hora(sessao):
    cliente = sessao(ADMIN_MASTER, _base([_guardada("fabrica_morada", "Rua A")]))
    r = cliente.patch(DEFINICOES_URL, json={"fabrica_morada": "Rua A"})
    assert (r.status_code, r.json()["fabrica_morada"]) == (200, "Rua A")
    assert cliente.base.crm_definicoes.sem_id() == [
        _guardada("fabrica_morada", "Rua A", quando=AGORA_CARIMBO, por="u-admin"),
    ]


@pytest.mark.parametrize(
    "corpo, guardadas",
    [
        ({"fabrica_lat": 38.7223445, "fabrica_lng": -9.1393}, {"fabrica_lat": "38.722345", "fabrica_lng": "-9.139300"}),
        ({"fabrica_lat": 39, "fabrica_lng": -9}, {"fabrica_lat": "39.000000", "fabrica_lng": "-9.000000"}),
        ({"fabrica_morada": None}, {"fabrica_morada": ""}),
        ({"fabrica_morada": "   "}, {"fabrica_morada": ""}),
    ],
    ids=["6 casas meio para longe do zero", "inteiros", "morada null fica vazia", "morada só com espaços"],
)
def test_os_valores_guardam_se_em_texto_como_o_dominio_os_deixa(sessao, corpo, guardadas):
    cliente = sessao(ADMIN_MASTER)
    assert cliente.patch(DEFINICOES_URL, json=corpo).status_code == 200
    assert _guardadas(cliente.base) == guardadas
    assert all(type(valor) is str for valor in _guardadas(cliente.base).values())


@pytest.mark.parametrize("corpo", [{}, None], ids=["objeto vazio", "sem corpo"])
def test_um_patch_vazio_nao_grava_nada_e_devolve_as_definicoes(sessao, monkeypatch, corpo):
    """`umPatchVazioNaoGravaNadaEDevolveAsDefinicoes`: nem lê o relógio."""
    leituras = []
    cliente = sessao(ADMIN_MASTER)
    monkeypatch.setattr(relogio, "agora", lambda: leituras.append(1) or AGORA)
    r = _pedir(cliente, "PATCH", DEFINICOES_URL, corpo)
    assert (r.status_code, r.text) == (200, PADROES_TEXTO)
    assert _guardadas(cliente.base) == {}
    assert cliente.base.crm_definicoes.registo == [("find", {}, PROJECAO_GUARDADA)]
    assert leituras == []


def test_um_patch_vazio_devolve_o_que_esta_guardado(sessao):
    cliente = sessao(ADMIN_MASTER, _base([_guardada("fabrica_morada", "Rua A")]))
    r = cliente.patch(DEFINICOES_URL, json={})
    assert r.json() == {**PADROES, "fabrica_morada": "Rua A"}
    assert _escritas(cliente.base) == []


def test_uma_chave_desconhecida_da_422_e_nada_se_grava(sessao):
    """`umaChaveDesconhecidaDa422ENadaSeGrava`: nem a morada, que era válida."""
    cliente = sessao(ADMIN_MASTER)
    r = cliente.patch(DEFINICOES_URL, json={"fabrica_morada": "Rua A", "hora_saida": "08:00"})
    assert (r.status_code, r.json()) == (422, _validacao({"hora_saida": "Esta definição não existe."}))
    assert _guardadas(cliente.base) == {}


def test_um_ponto_fora_de_portugal_da_422_e_nada_se_grava(sessao):
    """`umPontoForaDePortugalDa422ENadaSeGrava`: o Funchal."""
    cliente = sessao(ADMIN_MASTER)
    r = cliente.patch(DEFINICOES_URL, json={"fabrica_morada": "Funchal", "fabrica_lat": 32.65, "fabrica_lng": -16.9})
    assert r.status_code == 422
    assert r.json()["detail"]["campos"] == {"fabrica_lat": FORA, "fabrica_lng": FORA}
    assert _guardadas(cliente.base) == {}


@pytest.mark.parametrize(
    "corpo, campos",
    [
        ({"fabrica_lat": 41.1496}, {"fabrica_lng": "Indique também a longitude."}),
        ({"fabrica_lng": -8.611}, {"fabrica_lat": "Indique também a latitude."}),
        ({"fabrica_lat": "41.1496", "fabrica_lng": -8.611}, {"fabrica_lat": "A latitude tem de ser um número."}),
        ({"fabrica_lat": 41.1496, "fabrica_lng": True}, {"fabrica_lng": "A longitude tem de ser um número."}),
        ({"fabrica_morada": 12}, {"fabrica_morada": "Tem de ser texto."}),
        ({"fabrica_morada": "x" * 256}, {"fabrica_morada": "A morada tem no máximo 255 caracteres."}),
        (
            {"Fabrica_lat": 41.1496, "fabrica_lng": -8.611, "fabrica_morada": 1},
            {
                "fabrica_morada": "Tem de ser texto.",
                "fabrica_lat": "Indique também a latitude.",
                "Fabrica_lat": "Esta definição não existe.",
            },
        ),
    ],
    ids=["lat sem lng", "lng sem lat", "lat em texto", "lng bool", "morada número", "morada com 256",
         "vários erros pela ordem"],
)
def test_um_patch_invalido_da_422_com_os_erros_do_dominio_e_nem_toca_na_base(sessao, corpo, campos):
    cliente = sessao(ADMIN_MASTER, _base([_guardada("fabrica_morada", "Rua A")]))
    r = cliente.patch(DEFINICOES_URL, json=corpo)
    assert (r.status_code, r.json()) == (422, _validacao(campos))
    assert list(r.json()["detail"]["campos"]) == list(campos)
    assert cliente.base.crm_definicoes.registo == []


@pytest.mark.parametrize(
    "bruto", [b"[", b"[]", b"null", b'"fabrica_morada"', b"1", b'{"fabrica_morada": NaN}'],
    ids=["partido", "lista", "null", "texto", "número", "NaN"],
)
def test_um_corpo_que_nao_e_um_objeto_json_da_400(sessao, bruto):
    cliente = sessao(ADMIN_MASTER)
    r = cliente.patch(DEFINICOES_URL, content=bruto, headers=JSON)
    assert (r.status_code, r.json()) == (400, JSON_INVALIDO)
    assert cliente.base.crm_definicoes.registo == []


def test_gravar_quando_a_base_falha_e_um_erro_e_nada_se_grava(sessao):
    base = BaseFalsa({
        "crm_membros": list(MEMBROS),
        "crm_definicoes": _definicoes_falsas(falhar={"update_one": RuntimeError("base em baixo")}),
    })
    cliente = sessao(ADMIN_MASTER, base, levantar=False)
    assert cliente.patch(DEFINICOES_URL, json={"fabrica_morada": "Rua A"}).status_code == 500
    assert _guardadas(cliente.base) == {}


class _FalhaNaSegundaEscrita(ColeccaoFalsa):
    """A segunda escrita do primeiro pedido perde a ligação; as seguintes passam."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.escritas = 0

    async def update_one(self, filtro, atualizacao, upsert=False):
        self.escritas += 1
        if self.escritas == 2:
            self._registar("update_one", filtro, atualizacao, upsert)
            raise RuntimeError("ligação perdida")
        return await super().update_one(filtro, atualizacao, upsert)


def test_uma_falha_a_meio_responde_500_deixa_as_anteriores_e_repetir_acerta(sessao):
    """Sem transações (o autónomo gravava tudo numa): a ordem é a dos
    `PADROES`, por isso a morada já ficou e a latitude e a longitude não. O
    ponto nunca fica com uma coordenada nova e a outra velha, a não ser que a
    falha seja entre as duas — e cada uma, sozinha, está em Portugal. Repetir
    o mesmo pedido grava o resto (os upserts são idempotentes)."""
    base = BaseFalsa({"crm_membros": list(MEMBROS), "crm_definicoes": _definicoes_falsas(_FalhaNaSegundaEscrita)})
    cliente = sessao(ADMIN_MASTER, base, levantar=False)
    corpo = {"fabrica_morada": "Rua A", "fabrica_lat": 41.1496, "fabrica_lng": -8.611}

    assert cliente.patch(DEFINICOES_URL, json=corpo).status_code == 500
    assert _guardadas(cliente.base) == {"fabrica_morada": "Rua A"}

    r = cliente.patch(DEFINICOES_URL, json=corpo)
    assert (r.status_code, r.json()) == (
        200, {**PADROES, "fabrica_morada": "Rua A", "fabrica_lat": 41.1496, "fabrica_lng": -8.611},
    )
    assert _guardadas(cliente.base) == {
        "fabrica_lat": "41.149600", "fabrica_lng": "-8.611000", "fabrica_morada": "Rua A",
    }


def test_reler_quando_a_base_falha_e_um_erro_mas_o_que_se_gravou_fica(sessao):
    base = BaseFalsa({
        "crm_membros": list(MEMBROS),
        "crm_definicoes": _definicoes_falsas(falhar={"find": RuntimeError("base em baixo")}),
    })
    cliente = sessao(ADMIN_MASTER, base, levantar=False)
    assert cliente.patch(DEFINICOES_URL, json={"fabrica_morada": "Rua A"}).status_code == 500
    assert _guardadas(cliente.base) == {"fabrica_morada": "Rua A"}


def test_dois_admins_a_mudar_o_ponto_ao_mesmo_tempo(monkeypatch):
    """A corrida (sem a transação do autónomo): os dois recebem 200, cada
    chave fica com uma só linha (upsert pela `chave`, índice único) e cada
    coordenada fica com o valor de um dos dois pedidos — o ponto pode ficar
    misturado, mas sempre dentro de Portugal continental (cada coordenada
    foi vista contra Portugal). Diferença assumida no dossiê §5.9."""
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    base = _base()
    monkeypatch.setattr(crm.db, "obter_db", lambda: base)
    admin = {**ADMIN_MASTER, "crm_perfil": "admin", "crm_admin_master": True}
    ana = {**ANA_ADMIN_DO_CRM, "crm_perfil": "admin", "crm_admin_master": False}
    porto = {"fabrica_lat": 41.1496, "fabrica_lng": -8.611}
    faro = {"fabrica_lat": 37.0194, "fabrica_lng": -7.9304}

    async def _os_dois():
        return await asyncio.gather(
            rotas_definicoes.alterar_definicoes(admin=admin, corpo=dict(porto)),
            rotas_definicoes.alterar_definicoes(admin=ana, corpo=dict(faro)),
        )

    respostas = correr(_os_dois())
    assert len(respostas) == 2
    guardadas = _guardadas(base)
    assert sorted(guardadas) == ["fabrica_lat", "fabrica_lng"]
    assert len(base.crm_definicoes.docs) == 2
    assert guardadas["fabrica_lat"] in ("41.149600", "37.019400")
    assert guardadas["fabrica_lng"] in ("-8.611000", "-7.930400")


# --- F3 (T3.5): as definições das rotas ----------------------------------------------------------
#
# O domínio (crm/dominio/definicoes.py) passou a ter as 6 chaves das rotas, e
# a rota usa-o tal e qual: o GET devolve as 9 chaves e o PATCH aceita as
# novas. A coerência da saída com o regresso no PATCH é da T3.15.


def test_o_get_devolve_as_nove_chaves_com_os_minutos_como_inteiros(sessao):
    r = sessao(ANA_ADMIN_DO_CRM).get(DEFINICOES_URL)
    assert r.status_code == 200
    assert list(r.json().items()) == list(PADROES.items())
    assert [type(v) for v in r.json().values()] == [str, float, float, str, str, int, int, int, int]


def test_o_get_mostra_as_rotas_guardadas_por_cima_dos_padroes(sessao):
    base = _base([
        _guardada("servico_angariacao_min", "30"),
        _guardada("rota_hora_saida", "07:30"),
        _guardada("servico_entrega_min", "1"),
    ])
    r = sessao(ADMIN_MASTER, base).get(DEFINICOES_URL)
    assert list(r.json().items()) == list({
        **PADROES, "rota_hora_saida": "07:30", "servico_entrega_min": 1, "servico_angariacao_min": 30,
    }.items())


@pytest.mark.parametrize(
    "chave, guardado",
    [
        ("rota_hora_saida", "8:00"),
        ("rota_hora_regresso", ""),
        ("servico_entrega_min", "0"),
        ("servico_amostra_min", "241"),
        ("servico_acompanhamento_min", " 10"),
        ("servico_angariacao_min", "10.5"),
        ("servico_entrega_min", 20),
    ],
    ids=["hora sem o zero", "hora vazia", "zero minutos", "241 minutos", "espaço antes", "decimal",
         "número escrito à mão"],
)
def test_uma_definicao_das_rotas_estragada_na_base_fica_o_padrao_e_nao_da_500(sessao, chave, guardado):
    base = _base([_guardada(chave, guardado)])
    r = sessao(ADMIN_MASTER, base).get(DEFINICOES_URL)
    assert (r.status_code, r.json()) == (200, PADROES)


def test_o_admin_muda_a_hora_de_saida(sessao):
    """O primeiro caso do PATCH da T3.15 (`{"rota_hora_saida": "07:30"}`
    grava e devolve), já verde aqui."""
    cliente = sessao(ANA_ADMIN_DO_CRM)
    r = cliente.patch(DEFINICOES_URL, json={"rota_hora_saida": "07:30"})
    assert (r.status_code, r.json()) == (200, {**PADROES, "rota_hora_saida": "07:30"})
    assert cliente.base.crm_definicoes.sem_id() == [
        {"chave": "rota_hora_saida", "valor": "07:30", "atualizado_em": AGORA_CARIMBO, "atualizado_por": "u-ana"},
    ]
    assert instantes_fora_do_formato(cliente.base.crm_definicoes.docs) == []
    assert cliente.get(DEFINICOES_URL).json() == {**PADROES, "rota_hora_saida": "07:30"}


def test_os_minutos_gravam_se_em_texto_e_voltam_como_inteiros(sessao):
    cliente = sessao(ADMIN_MASTER)
    r = cliente.patch(DEFINICOES_URL, json={"servico_entrega_min": 20, "servico_angariacao_min": 240})
    assert (r.status_code, r.json()) == (200, {**PADROES, "servico_entrega_min": 20, "servico_angariacao_min": 240})
    assert _guardadas(cliente.base) == {"servico_angariacao_min": "240", "servico_entrega_min": "20"}


def test_as_nove_chaves_gravam_se_pela_ordem_dos_padroes(sessao):
    cliente = sessao(ADMIN_MASTER)
    corpo = {
        "servico_angariacao_min": 16, "servico_acompanhamento_min": 14, "servico_amostra_min": 11,
        "servico_entrega_min": 9, "rota_hora_regresso": "18:00", "rota_hora_saida": "07:00",
        "fabrica_lng": -8.611, "fabrica_lat": 41.1496, "fabrica_morada": "Rua A",
    }
    r = cliente.patch(DEFINICOES_URL, json=corpo)
    assert r.status_code == 200
    assert [(c[1]["chave"], c[2]["$set"]["valor"]) for c in _escritas(cliente.base)] == [
        ("fabrica_morada", "Rua A"), ("fabrica_lat", "41.149600"), ("fabrica_lng", "-8.611000"),
        ("rota_hora_saida", "07:00"), ("rota_hora_regresso", "18:00"), ("servico_entrega_min", "9"),
        ("servico_amostra_min", "11"), ("servico_acompanhamento_min", "14"), ("servico_angariacao_min", "16"),
    ]
    assert list(r.json().items()) == [
        ("fabrica_morada", "Rua A"), ("fabrica_lat", 41.1496), ("fabrica_lng", -8.611),
        ("rota_hora_saida", "07:00"), ("rota_hora_regresso", "18:00"), ("servico_entrega_min", 9),
        ("servico_amostra_min", 11), ("servico_acompanhamento_min", 14), ("servico_angariacao_min", 16),
    ]
    assert instantes_fora_do_formato(cliente.base.crm_definicoes.docs) == []


@pytest.mark.parametrize(
    "corpo, campos",
    [
        ({"servico_entrega_min": 0}, {"servico_entrega_min": TEMPO}),
        ({"servico_amostra_min": 241}, {"servico_amostra_min": TEMPO}),
        ({"servico_acompanhamento_min": "15"}, {"servico_acompanhamento_min": TEMPO}),
        ({"servico_angariacao_min": 15.0}, {"servico_angariacao_min": TEMPO}),
        ({"servico_entrega_min": True}, {"servico_entrega_min": TEMPO}),
        ({"rota_hora_saida": "7:30"}, {"rota_hora_saida": HORA}),
        ({"rota_hora_regresso": ""}, {"rota_hora_regresso": HORA}),
        ({"rota_hora_regresso": None}, {"rota_hora_regresso": HORA}),
        (
            {"servico_entrega_min": 0, "fabrica_morada": "Rua A", "rota_hora_saida": "24:00", "hora_saida": "08:00"},
            {"rota_hora_saida": HORA, "servico_entrega_min": TEMPO, "hora_saida": "Esta definição não existe."},
        ),
    ],
    ids=["zero minutos", "241 minutos", "minutos em texto", "minutos decimais", "minutos bool", "hora sem o zero",
         "hora vazia", "hora nula", "vários erros pela ordem (e a morada válida também não se grava)"],
)
def test_uma_definicao_das_rotas_invalida_da_422_e_nada_se_grava(sessao, corpo, campos):
    cliente = sessao(ADMIN_MASTER, _base([_guardada("servico_entrega_min", "12")]))
    r = cliente.patch(DEFINICOES_URL, json=corpo)
    assert (r.status_code, r.json()) == (422, _validacao(campos))
    assert list(r.json()["detail"]["campos"]) == list(campos)
    assert cliente.base.crm_definicoes.registo == []


# --- F3 (T3.15): a coerência da saída com o regresso no PATCH ------------------------------------
#
# A `alteracao` não compara as horas entre si (T3.5): é a rota que, só quando
# o pedido traz `rota_hora_saida` ou `rota_hora_regresso`, junta as definições
# em vigor com as horas do pedido e chama `dominio.definicoes.coerencia`, antes
# da primeira escrita (correção "T3.5 / T3.15" do plano F3). Como as janelas
# da loja (`semMexerNasJanelasNaoSeVerificamAsGuardadas`): um PATCH só da
# fábrica ou dos minutos nunca recebe 422 por causa das horas guardadas.

COERENCIA = "A hora de regresso tem de ser depois da hora de saída."


def _com_guardadas(guardadas):
    return _base([_guardada(chave, valor) for chave, valor in guardadas])


def test_o_regresso_antes_da_saida_guardada_da_422_de_coerencia_e_nada_se_grava(sessao):
    """O vermelho da T3.15: `{"rota_hora_regresso": "07:00"}` com a saída
    guardada às 08:00 gravava, em vez de dar 422."""
    cliente = sessao(ANA_ADMIN_DO_CRM, _com_guardadas([("rota_hora_saida", "08:00")]))
    r = cliente.patch(DEFINICOES_URL, json={"rota_hora_regresso": "07:00"})
    assert (r.status_code, r.json()) == (422, _validacao({"rota_hora_regresso": COERENCIA}))
    assert _escritas(cliente.base) == []
    assert _guardadas(cliente.base) == {"rota_hora_saida": "08:00"}
    assert cliente.get(DEFINICOES_URL).json() == PADROES


@pytest.mark.parametrize(
    "guardadas, corpo",
    [
        ([], {"rota_hora_regresso": "07:00"}),
        ([("rota_hora_saida", "08:00")], {"rota_hora_regresso": "08:00"}),
        ([("rota_hora_saida", "08:00")], {"rota_hora_regresso": "00:00"}),
        ([("rota_hora_regresso", "17:00")], {"rota_hora_saida": "17:00"}),
        ([("rota_hora_regresso", "17:00")], {"rota_hora_saida": "17:01"}),
        ([], {"rota_hora_saida": "19:00"}),
        ([], {"rota_hora_saida": "23:59"}),
        ([("rota_hora_saida", "06:00"), ("rota_hora_regresso", "22:00")],
         {"rota_hora_saida": "12:00", "rota_hora_regresso": "11:59"}),
        ([("rota_hora_saida", "06:00"), ("rota_hora_regresso", "22:00")],
         {"rota_hora_regresso": "06:00", "rota_hora_saida": "06:00"}),
        ([("rota_hora_saida", "8:00")], {"rota_hora_regresso": "07:59"}),
        ([("rota_hora_regresso", "")], {"rota_hora_saida": "19:00"}),
        ([], {"fabrica_morada": "Rua A", "rota_hora_regresso": "07:00", "servico_entrega_min": 20}),
        ([("fabrica_morada", "Rua B")], {"fabrica_lat": 41.1496, "fabrica_lng": -8.611, "rota_hora_saida": "19:30"}),
    ],
    ids=["regresso antes da saída por omissão", "a mesma hora da saída guardada", "regresso à meia-noite",
         "saída igual ao regresso guardado", "saída depois do regresso guardado", "saída igual ao regresso por omissão",
         "saída às 23:59", "as duas no pedido, trocadas (as guardadas eram coerentes)",
         "as duas no pedido, iguais (por outra ordem)", "saída guardada estragada conta como o padrão",
         "regresso guardado estragado conta como o padrão", "com a morada e os minutos válidos, nada se grava",
         "com o ponto válido, nada se grava"],
)
def test_a_saida_e_o_regresso_incoerentes_dao_422_so_no_regresso_e_nada_se_grava(sessao, guardadas, corpo):
    base = _com_guardadas(guardadas)
    antes = _guardadas(base)
    cliente = sessao(ADMIN_MASTER, base)
    r = cliente.patch(DEFINICOES_URL, json=corpo)
    assert (r.status_code, r.json()) == (422, _validacao({"rota_hora_regresso": COERENCIA}))
    assert list(r.json()["detail"]["campos"]) == ["rota_hora_regresso"]
    assert _escritas(cliente.base) == []
    assert _guardadas(cliente.base) == antes


def test_a_coerencia_le_as_definicoes_em_vigor_uma_vez_antes_da_primeira_escrita_e_sem_ler_o_relogio(
    sessao, monkeypatch,
):
    """`em_vigor` + as horas do pedido, antes de qualquer escrita; o relógio
    nem se lê (como os 422 da `alteracao`)."""
    leituras = []
    cliente = sessao(ADMIN_MASTER)
    monkeypatch.setattr(relogio, "agora", lambda: leituras.append(1) or AGORA)
    r = cliente.patch(DEFINICOES_URL, json={"rota_hora_regresso": "07:00"})
    assert r.status_code == 422
    assert cliente.base.crm_definicoes.registo == [("find", {}, PROJECAO_GUARDADA)]
    assert leituras == []


def test_a_coerencia_ignora_as_linhas_estragadas_como_o_em_vigor(sessao, caplog):
    """Uma linha sem valor legível ignora-se (fica o padrão 08:00): 422 de
    coerência, nunca 500."""
    base = _base([{"chave": "rota_hora_saida", "valor": None}, _guardada("rota_hora_regresso", "18:00")])
    cliente = sessao(ADMIN_MASTER, base)
    with caplog.at_level(logging.WARNING, logger="crm.definicoes"):
        r = cliente.patch(DEFINICOES_URL, json={"rota_hora_regresso": "07:00"})
    assert (r.status_code, r.json()) == (422, _validacao({"rota_hora_regresso": COERENCIA}))
    assert _escritas(cliente.base) == []


@pytest.mark.parametrize(
    "guardadas, corpo, resposta",
    [
        ([], {"rota_hora_regresso": "08:01"}, {"rota_hora_regresso": "08:01"}),
        ([("rota_hora_saida", "09:00")], {"rota_hora_regresso": "09:01"},
         {"rota_hora_saida": "09:00", "rota_hora_regresso": "09:01"}),
        ([("rota_hora_regresso", "21:00")], {"rota_hora_saida": "20:59"},
         {"rota_hora_saida": "20:59", "rota_hora_regresso": "21:00"}),
        ([], {"rota_hora_saida": "18:59"}, {"rota_hora_saida": "18:59"}),
        ([("rota_hora_saida", "20:00"), ("rota_hora_regresso", "19:00")],
         {"rota_hora_saida": "06:00", "rota_hora_regresso": "06:01"},
         {"rota_hora_saida": "06:00", "rota_hora_regresso": "06:01"}),
        ([("rota_hora_saida", "8:00")], {"rota_hora_regresso": "08:01"}, {"rota_hora_regresso": "08:01"}),
        ([], {"rota_hora_saida": "00:00", "rota_hora_regresso": "23:59"},
         {"rota_hora_saida": "00:00", "rota_hora_regresso": "23:59"}),
        ([], {"fabrica_morada": "Rua A", "rota_hora_saida": "07:30", "servico_amostra_min": 5},
         {"fabrica_morada": "Rua A", "rota_hora_saida": "07:30", "servico_amostra_min": 5}),
    ],
    ids=["regresso um minuto depois da saída por omissão", "regresso depois da saída guardada",
         "saída antes do regresso guardado", "saída antes do regresso por omissão",
         "o pedido corrige as guardadas incoerentes", "saída guardada estragada conta como o padrão",
         "o dia inteiro", "com a morada e os minutos"],
)
def test_com_o_regresso_depois_da_saida_grava_e_devolve(sessao, guardadas, corpo, resposta):
    cliente = sessao(ANA_ADMIN_DO_CRM, _com_guardadas(guardadas))
    r = cliente.patch(DEFINICOES_URL, json=corpo)
    assert (r.status_code, r.json()) == (200, {**PADROES, **resposta})
    assert _guardadas(cliente.base) == {
        **dict(guardadas), **{chave: str(valor) if isinstance(valor, int) else valor for chave, valor in corpo.items()},
    }
    assert [c[0] for c in cliente.base.crm_definicoes.registo] == ["find"] + ["update_one"] * len(corpo) + ["find"]
    assert instantes_fora_do_formato(cliente.base.crm_definicoes.docs) == []
    assert cliente.get(DEFINICOES_URL).json() == {**PADROES, **resposta}


@pytest.mark.parametrize(
    "corpo, resposta",
    [
        ({"fabrica_morada": "Rua A"}, {"fabrica_morada": "Rua A"}),
        ({"fabrica_lat": 41.1496, "fabrica_lng": -8.611}, {"fabrica_lat": 41.1496, "fabrica_lng": -8.611}),
        ({"servico_entrega_min": 20, "servico_angariacao_min": 240},
         {"servico_entrega_min": 20, "servico_angariacao_min": 240}),
        ({}, {}),
    ],
    ids=["só a morada", "só o ponto", "só os minutos", "vazio"],
)
def test_sem_mexer_nas_horas_nao_se_verificam_as_guardadas(sessao, corpo, resposta):
    """Como as janelas da loja (`semMexerNasJanelasNaoSeVerificamAsGuardadas`):
    horas guardadas incoerentes (escritas à mão) não travam um PATCH da
    fábrica nem dos minutos, e a base nem se lê antes de gravar."""
    guardadas = [("rota_hora_saida", "20:00"), ("rota_hora_regresso", "19:00")]
    cliente = sessao(ADMIN_MASTER, _com_guardadas(guardadas))
    r = cliente.patch(DEFINICOES_URL, json=corpo)
    assert (r.status_code, r.json()) == (200, {**PADROES, **dict(guardadas), **resposta})
    assert [c[0] for c in cliente.base.crm_definicoes.registo] == ["update_one"] * len(corpo) + ["find"]


@pytest.mark.parametrize(
    "corpo, campos",
    [
        ({"rota_hora_regresso": "7:00"}, {"rota_hora_regresso": HORA}),
        ({"rota_hora_saida": "", "rota_hora_regresso": "07:00"}, {"rota_hora_saida": HORA}),
        ({"rota_hora_saida": "09:00", "rota_hora_regresso": None}, {"rota_hora_regresso": HORA}),
        ({"rota_hora_regresso": "07:00", "servico_entrega_min": 0}, {"servico_entrega_min": TEMPO}),
        ({"rota_hora_regresso": "07:00", "fabrica_lat": 41.1496}, {"fabrica_lng": "Indique também a longitude."}),
        ({"rota_hora_regresso": "07:00", "hora_regresso": "07:00"}, {"hora_regresso": "Esta definição não existe."}),
    ],
    ids=["hora sem o zero", "saída vazia e regresso incoerente", "saída válida e regresso nulo",
         "minutos a zero", "latitude sem a longitude", "chave desconhecida"],
)
def test_os_erros_dos_campos_vem_antes_da_coerencia_e_sem_ler_a_base(sessao, corpo, campos):
    """Com um campo errado, o 422 é o da `alteracao` (só os seus erros) e a
    coerência nem corre: a base não se lê."""
    cliente = sessao(ADMIN_MASTER, _com_guardadas([("rota_hora_saida", "08:00")]))
    r = cliente.patch(DEFINICOES_URL, json=corpo)
    assert (r.status_code, r.json()) == (422, _validacao(campos))
    assert cliente.base.crm_definicoes.registo == []


def test_a_coerencia_e_a_do_dominio(sessao, monkeypatch):
    """A rota chama `dominio.definicoes.coerencia` com as definições em vigor
    juntas com as horas do pedido (as do pedido por cima), e devolve o que ela
    disser."""
    chamadas = []

    def _coerencia(valores):
        chamadas.append(dict(valores))
        return {"rota_hora_regresso": "mensagem do domínio"}

    monkeypatch.setattr(rotas_definicoes.regras, "coerencia", _coerencia)
    cliente = sessao(ADMIN_MASTER, _com_guardadas([("rota_hora_regresso", "21:00"), ("servico_entrega_min", "30")]))
    r = cliente.patch(DEFINICOES_URL, json={"rota_hora_saida": "09:00", "servico_entrega_min": 5})
    assert (r.status_code, r.json()) == (422, _validacao({"rota_hora_regresso": "mensagem do domínio"}))
    assert len(chamadas) == 1
    assert chamadas[0]["rota_hora_saida"] == "09:00"
    assert chamadas[0]["rota_hora_regresso"] == "21:00"
    assert _escritas(cliente.base) == []


# --- De ponta a ponta: a sessão verdadeira do portal ---------------------------------------------

SEGREDO = "segredo-de-teste-crm-definicoes"
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
    base = _base()
    monkeypatch.setattr(faturacao.auth, "obter_db", lambda: base)
    monkeypatch.setattr(crm.db, "obter_db", lambda: base)
    app = FastAPI()
    app.include_router(crm.router)
    cliente = TestClient(app)
    cliente.base = base
    return cliente


@pytest.mark.parametrize("metodo, corpo", PEDIDOS, ids=IDS_PEDIDOS)
def test_sem_sessao_da_o_403_herdado(portal, metodo, corpo):
    """`semSessaoDa401`: no portal, sem cabeçalho é o 403 do HTTPBearer (o
    frontend trata-o como sessão em falta)."""
    r = _pedir(portal, metodo, DEFINICOES_URL, corpo)
    assert (r.status_code, r.json()) == (403, {"detail": "Not authenticated"})
    assert portal.base.crm_definicoes.registo == []


def test_sem_cabecalho_e_com_json_partido_da_o_403_herdado_e_nunca_400(portal):
    """Correções do plano, linha "T1.3 / T2.15"."""
    r = portal.patch(DEFINICOES_URL, content=b"[", headers=JSON)
    assert (r.status_code, r.json()) == (403, {"detail": "Not authenticated"})
    assert portal.base.users.registo == []
    assert portal.base.crm_definicoes.registo == []


@pytest.mark.parametrize("metodo, corpo", PEDIDOS, ids=IDS_PEDIDOS)
def test_uma_conta_apagada_da_401_sessao_terminada(portal, metodo, corpo):
    r = _pedir(portal, metodo, DEFINICOES_URL, corpo, headers=_cabecalho("u-apagada"))
    assert (r.status_code, r.json()) == (401, {"detail": "Sessão terminada"})
    assert portal.base.crm_definicoes.registo == []


def test_de_ponta_a_ponta_o_admin_muda_a_fabrica_e_o_utilizador_nao(portal):
    admin = _cabecalho("u-admin", email=ADMIN_LOCAL, role="admin")
    ze = _cabecalho("u-ze")

    assert portal.get(DEFINICOES_URL, headers=admin).json() == PADROES
    r = portal.patch(DEFINICOES_URL, json={"fabrica_morada": "Rua B"}, headers=ze)
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)

    r = portal.patch(
        DEFINICOES_URL,
        json={"fabrica_morada": " Rua das Flores 1, Porto", "fabrica_lat": 41.1496, "fabrica_lng": -8.611},
        headers=admin,
    )
    esperado = {**PADROES, "fabrica_morada": "Rua das Flores 1, Porto", "fabrica_lat": 41.1496, "fabrica_lng": -8.611}
    assert (r.status_code, r.json()) == (200, esperado)
    assert portal.get(DEFINICOES_URL, headers=admin).json() == esperado
    assert {d["atualizado_por"] for d in portal.base.crm_definicoes.docs} == {"u-admin"}
    assert [instantes_fora_do_formato(d) for d in portal.base.crm_definicoes.docs] == [[], [], []]
