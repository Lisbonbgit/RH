"""O terreno ganha: as escritas do escritório nunca tocam no que o motorista
registou (plano F3 §1 "O terreno ganha" e "Estados", §3 contrato com a F4;
T3.24; desenho §4.3).

As regras estão provadas uma a uma a montante: o `bloqueio_de_escrita` e os
`caminhos_paragem` (`dominio.rotas`, T3.3), o filtro de guarda e o
`porque_falhou` (`rotas_bd`, T3.17), o verificador `escritas_no_terreno`
(T3.14) e cada rota de escrita (T3.19–T3.22). Aqui prova-se o conjunto, de
ponta a ponta pelas rotas HTTP e com o duplo do Motor:

- **Uma rota com registo do motorista** (uma paragem `feita`, com `resultado`
  "interessado", `concluida_em` e um `client_uuid` da fila da F4): o `POST`
  de paragens, cada forma do `PATCH`, o `recalcular` e o `otimizar` dão 409
  `rota_em_curso` sem escrever nem chamar o openrouteservice, e a paragem
  fica **igual ao byte** (`sem_id()` antes e depois). A rota lê-se na mesma
  (`editavel: false`), também com a paragem reposta pelo motorista só com
  `removida_em: null` e `ordem: null` (correção "T3.3 (ativas com ordem
  nula)").
- **A corrida:** o gancho `antes_de("find_one_and_update", …)` do duplo grava
  `paragens.0.estado = "feita"` entre a leitura e a escrita de cada rota de
  escrita → a escrita condicional não casa (o filtro `"paragens.estado":
  {"$nin": ["feita", "nao_feita"]}`), `porque_falhou` diz `em_curso` → 409
  `rota_em_curso`, e nada do escritório fica escrito.
- **O varrimento:** uma sequência real (adicionar 3, reordenar, mudar o
  motivo, manter, retirar, recalcular, otimizar e guardar), com o
  openrouteservice respondido pelo simulador local (T3.13) → todas as
  atualizações registadas no duplo passam em `escritas_no_terreno == []` e
  os documentos em `instantes_fora_do_formato == []`; o terreno de todas as
  paragens continua `pendente`/null/null. E o primeiro registo do motorista
  a seguir fecha a rota ao escritório.

Molde do test_rotas_recalcular.py / test_rotas_otimizar.py (montagem,
`_base_com_tres`, o ORS falso num `httpx.MockTransport` com a chave canária).
Nenhum pedido sai para o openrouteservice verdadeiro.
"""
import json
from copy import deepcopy
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo import ReturnDocument

import crm
import crm.db
import ors_simulado_local
from crm import relogio
from crm.servicos import ors
from faturacao.auth import utilizador_atual

from .duplos import BaseFalsa
from .formatos import escritas_no_terreno, instantes_fora_do_formato

ROTAS_URL = "/api/crm/rotas"
ADMIN_LOCAL = "admin.local@example.com"

UTC = timezone.utc
# 23:30Z de 12 de outubro de 2026: em Lisboa (WEST, UTC+1) já é dia 13.
AGORA = datetime(2026, 10, 12, 23, 30, 15, 987654, tzinfo=UTC)
HOJE = "2026-10-13"  # uma terça-feira
AMANHA = "2026-10-14"  # uma quarta-feira

MEMBRO = "membro-1"
ZE = "u-ze"
LOJA_A = "00000000-0000-4000-8000-00000000000a"
LOJA_B = "00000000-0000-4000-8000-00000000000b"
LOJA_C = "00000000-0000-4000-8000-00000000000c"
LOJA_D = "00000000-0000-4000-8000-00000000000d"
LOJA_E = "00000000-0000-4000-8000-00000000000e"

PARAGEM_A = "10000000-0000-4000-8000-00000000000a"
PARAGEM_B = "10000000-0000-4000-8000-00000000000b"
PARAGEM_C = "10000000-0000-4000-8000-00000000000c"
PARAGEM_D = "10000000-0000-4000-8000-00000000000d"  # retirada
# O índice de cada paragem na lista gravada (`_tres_paragens`).
INDICE = {PARAGEM_A: 0, PARAGEM_B: 1, PARAGEM_D: 2, PARAGEM_C: 3}

COMERCIO = (38.7075, -9.1364)
MARQUES = (38.7253, -9.15)
BELEM = (38.6979, -9.2065)
QUIOSQUE = (38.71, -9.14)
OUTRA = (38.74, -9.16)
OUTRO_PONTO = {"lat": 38.6, "lng": -9.1}

# O openrouteservice falso: a chave canária e o URL de teste.
CHAVE = "ors-CANARIA-chave-do-terreno-5b3ce3597851110001cf6248"
BASE = "https://ors.teste"
CAMINHO_VROOM = "/optimization"
CAMINHO_DIRECOES = "/v2/directions/driving-car/json"

# O registo do motorista numa paragem (F4): o terreno, mais o `client_uuid`
# da fila sem rede, um campo que a F3 não conhece e nunca pode apagar.
REGISTO_FEITA = {
    "estado": "feita",
    "resultado": "interessado",
    "concluida_em": "2026-10-13T10:00:00Z",
    "client_uuid": "c0ffee00-0000-4000-8000-0000000000f4",
}

ROTA_EM_CURSO = {
    "detail": {
        "codigo": "rota_em_curso",
        "mensagem": "A rota já tem registos do motorista — no escritório só se pode ver.",
    }
}

SEM_ID = {"_id": 0}
SEM_CALCULO = {"_id": 0, "calculo": 0}
GUARDA_DO_TERRENO = {"paragens.estado": {"$nin": ["feita", "nao_feita"]}}

USERS = [
    {"id": "u-admin", "email": ADMIN_LOCAL, "name": "Administrador Principal", "role": "admin",
     "password": "$2b$12$hash-do-admin"},
    {"id": ZE, "email": "ze@example.com", "name": "Zé Silva", "role": "colaborador",
     "password": "$2b$12$hash-do-ze"},
]
MEMBROS = [
    {"id": "m-ze", "user_id": ZE, "perfil": "utilizador", "criado_em": "2026-10-01T09:00:00Z"},
]
ZE_UTILIZADOR = {"user_id": ZE, "email": "ze@example.com", "role": "colaborador"}


# --- montagem ------------------------------------------------------------------------------------


def _url(sufixo="", data=AMANHA):
    return f"{ROTAS_URL}/{data}{sufixo}"


def _paragem(id_, loja_id, ordem, **campos):
    return {
        "id": id_, "loja_id": loja_id, "ordem": ordem, "motivo": "angariacao", "tempo_servico_min": 15,
        "manter_fechada": False, "nao_cabe": False, "chegada_prevista": None, "espera_min": None,
        "fora_de_horario": False, "adicionada_em": "2026-10-10T09:00:00Z", "adicionada_por": MEMBRO,
        "removida_em": None, "estado": "pendente", "resultado": None, "concluida_em": None, **campos,
    }


def _retirada(id_, loja_id, **campos):
    return _paragem(id_, loja_id, None, removida_em="2026-10-10T10:00:00Z", **campos)


def _rota(data=AMANHA, paragens=(), id_="r-1", **campos):
    return {
        "id": id_, "data": data, "estado": "rascunho", "versao": 3, "hora_saida": "08:00",
        "hora_regresso_limite": "19:00", "inicio": None, "fim": None, "evitar_portagens": False,
        "paragens": [deepcopy(p) for p in paragens], "calculo": None, "criado_em": "2026-10-10T09:00:00Z",
        "criado_por": MEMBRO, "atualizado_em": "2026-10-10T09:00:00.000000Z", "atualizado_por": MEMBRO, **campos,
    }


def _loja(id_, nome, fase, ponto, **extra):
    return {
        "id": id_, "nome": nome, "fase": fase, "lat": ponto[0], "lng": ponto[1], "telefone": "+351911111111",
        "janelas": [], "dias_fechada": [], "morada": "Rua Secreta 1", "notas": "não sai na rota",
        "regiao_id": None, "pessoa_contacto": "Sr. Silva", **extra,
    }


def _lojas():
    # A A fecha à quarta (o dia de AMANHA); as outras abrem todos os dias.
    return [
        _loja(LOJA_A, "Café A", "contactada", COMERCIO, dias_fechada=["qua"]),
        _loja(LOJA_B, "Pastelaria B", "potencial", MARQUES),
        _loja(LOJA_C, "Mercearia C", "cliente", BELEM, janelas=[{"inicio": "09:00", "fim": "12:00"}]),
        _loja(LOJA_D, "Quiosque D", "potencial", QUIOSQUE),
        _loja(LOJA_E, "Tasca E", "potencial", OUTRA),
    ]


def _tres_paragens(**por_paragem):
    """Pela ordem: B (0), C (1) e A (2, fechada à quarta); a D retirada (índice
    2 da lista). `por_paragem={PARAGEM_B: {...}}` altera uma delas."""
    paragens = [
        _paragem(PARAGEM_A, LOJA_A, 2), _paragem(PARAGEM_B, LOJA_B, 0), _retirada(PARAGEM_D, LOJA_D),
        _paragem(PARAGEM_C, LOJA_C, 1),
    ]
    for paragem in paragens:
        paragem.update(por_paragem.get(paragem["id"], {}))
    return paragens


def _base(rotas=(), lojas=None, definicoes=()):
    return BaseFalsa({
        "crm_rotas": list(rotas),
        "crm_lojas": _lojas() if lojas is None else list(lojas),
        "crm_definicoes": list(definicoes),
        "crm_membros": list(MEMBROS),
        "users": list(USERS),
    })


def _base_com_tres(por_paragem=None, **campos_da_rota):
    return _base(rotas=[_rota(AMANHA, _tres_paragens(**(por_paragem or {})), **campos_da_rota)])


def _base_com_registo(**registo):
    """A rota de AMANHA com a B já visitada pelo motorista (o registo da F4)."""
    return _base_com_tres(por_paragem={PARAGEM_B: registo or REGISTO_FEITA})


def _gravadas(base):
    return base.crm_rotas.sem_id()


def _operacoes(base):
    return [c[0] for c in base.crm_rotas.registo]


def _escritas(base):
    """As escritas registadas em `crm_rotas`: `(operação, documento ou atualização)`."""
    return [
        (c[0], c[1] if c[0] == "insert_one" else c[2])
        for c in base.crm_rotas.registo
        if c[0] in ("insert_one", "update_one", "find_one_and_update")
    ]


class OrsSimulado:
    """O openrouteservice falso, como handler de um `httpx.MockTransport`:
    guarda os pedidos e responde aos dois serviços como o simulador local
    (T3.13) — tudo é atribuído e as horas vêm pelos troços simulados."""

    def __init__(self):
        self.pedidos = []

    def __call__(self, pedido):
        self.pedidos.append(pedido)
        corpo = json.loads(pedido.content)
        if pedido.url.path == CAMINHO_VROOM:
            return httpx.Response(200, json=ors_simulado_local.otimizar(corpo))
        if pedido.url.path == CAMINHO_DIRECOES:
            return httpx.Response(200, json=ors_simulado_local.direcoes(corpo))
        return httpx.Response(404, json={"error": "caminho desconhecido no falso"})

    def caminhos(self):
        return [pedido.url.path for pedido in self.pedidos]


@pytest.fixture
def ors_falso(monkeypatch):
    """A chave canária e o URL de teste no ambiente; o transporte do cliente
    trocado pelo simulador (a guarda do conftest fica sem pedidos)."""
    monkeypatch.setenv(ors.VARIAVEL_CHAVE, CHAVE)
    monkeypatch.setenv(ors.VARIAVEL_URL, BASE)
    falso = OrsSimulado()
    monkeypatch.setattr(ors, "_transporte", httpx.MockTransport(falso))
    return falso


@pytest.fixture
def sessao(monkeypatch):
    """Uma app só com o router do CRM, a sessão do portal trocada por
    `dependency_overrides`, a base do CRM trocada pelo único ponto e o
    relógio parado em AGORA. `sessao(base)` devolve o cliente (com
    `cliente.base`); por omissão, a rota de AMANHA com três paragens."""
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    monkeypatch.setattr(relogio, "agora", lambda: AGORA)

    def _montar(base=None, utilizador=ZE_UTILIZADOR):
        base = base if base is not None else _base_com_tres()
        monkeypatch.setattr(crm.db, "obter_db", lambda: base)
        app = FastAPI()
        app.include_router(crm.router)
        app.dependency_overrides[utilizador_atual] = lambda: dict(utilizador)
        cliente = TestClient(app)
        cliente.base = base
        return cliente

    return _montar


# --- As escritas do escritório, uma a uma ---------------------------------------------------------


def _post(loja_id=LOJA_E, **corpo):
    return lambda cliente, versao=3: cliente.post(_url("/paragens"), json={"loja_id": loja_id, **corpo})


def _post_com_versao(loja_id=LOJA_E):
    return lambda cliente, versao=3: cliente.post(_url("/paragens"), json={"loja_id": loja_id, "versao": versao})


def _patch(**corpo):
    return lambda cliente, versao=3: cliente.patch(_url(), json={"versao": versao, **corpo})


def _recalcular():
    return lambda cliente, versao=3: cliente.post(_url("/recalcular"), json={"versao": versao})


def _otimizar():
    return lambda cliente, versao=3: cliente.post(_url("/otimizar"), json={"versao": versao})


# `(nome, pedido, caminhos que o openrouteservice receberia numa rota livre)`.
# Cada forma do PATCH do plano §4 está aqui, mais o PATCH só com a versão.
ESCRITAS = [
    ("POST paragens sem versão", _post(), []),
    ("POST paragens com versão", _post_com_versao(), []),
    ("POST paragens (reativar a D)", _post(LOJA_D), []),
    ("PATCH hora_saida", _patch(hora_saida="07:00"), []),
    ("PATCH hora_regresso_limite", _patch(hora_regresso_limite="20:00"), []),
    ("PATCH inicio", _patch(inicio=OUTRO_PONTO), []),
    ("PATCH fim", _patch(fim=OUTRO_PONTO), []),
    ("PATCH evitar_portagens", _patch(evitar_portagens=True), []),
    ("PATCH ordem", _patch(ordem=[PARAGEM_C, PARAGEM_B]), []),
    ("PATCH motivo", _patch(paragens={PARAGEM_C: {"motivo": "entrega"}}), []),
    ("PATCH tempo_servico_min", _patch(paragens={PARAGEM_C: {"tempo_servico_min": 30}}), []),
    ("PATCH manter_fechada", _patch(paragens={PARAGEM_A: {"manter_fechada": True}}), []),
    ("PATCH nao_cabe false", _patch(paragens={PARAGEM_C: {"nao_cabe": False}}), []),
    ("PATCH a propria paragem feita", _patch(paragens={PARAGEM_B: {"motivo": "entrega"}}), []),
    ("PATCH retirar", _patch(retirar=[PARAGEM_C]), []),
    ("PATCH retirar a feita", _patch(retirar=[PARAGEM_B]), []),
    ("PATCH estado planeada", _patch(estado="planeada"), []),
    ("PATCH so com a versao", _patch(), []),
    ("POST recalcular", _recalcular(), [CAMINHO_DIRECOES]),
    ("POST otimizar", _otimizar(), [CAMINHO_VROOM, CAMINHO_DIRECOES]),
]
NOMES = [nome for nome, _, _ in ESCRITAS]
PEDIDOS = [pedido for _, pedido, _ in ESCRITAS]
CAMINHOS_ORS = [caminhos for _, _, caminhos in ESCRITAS]


# --- Uma rota com registo do motorista é só de leitura no escritório -------------------------------


@pytest.mark.parametrize("nome, pedido", [(n, p) for n, p, _ in ESCRITAS], ids=NOMES)
def test_cada_escrita_do_escritorio_da_rota_em_curso_e_a_paragem_feita_fica_igual_ao_byte(sessao, ors_falso, nome, pedido):
    """A B já foi visitada (`feita`, "interessado", `concluida_em` e o
    `client_uuid` da fila): 409 `rota_em_curso` em todas as escritas, só com
    a leitura da rota no registo, nenhum pedido ao openrouteservice, e a rota
    inteira — a paragem feita incluída — exatamente como estava."""
    cliente = sessao(_base_com_registo())
    antes = _gravadas(cliente.base)

    r = pedido(cliente)

    assert (r.status_code, r.json()) == (409, ROTA_EM_CURSO)
    assert _gravadas(cliente.base) == antes
    assert _gravadas(cliente.base)[0]["paragens"][INDICE[PARAGEM_B]] == _paragem(PARAGEM_B, LOJA_B, 0, **REGISTO_FEITA)
    assert _operacoes(cliente.base) == ["find_one"], "só a leitura da rota: nem escrita, nem porque_falhou"
    assert _escritas(cliente.base) == []
    assert ors_falso.pedidos == []
    assert cliente.base.crm_lojas.chamadas("find") == [], "as lojas da rota nem se leem"
    if not nome.startswith("POST paragens"):
        # O POST lê a loja e as definições antes da rota (T3.19); os outros
        # só depois do bloqueio.
        assert cliente.base.crm_definicoes.registo == [], "o bloqueio vem antes das definições"


@pytest.mark.parametrize("registo", ["feita", "nao_feita"])
@pytest.mark.parametrize("pedido", [PEDIDOS[0], PEDIDOS[8], PEDIDOS[18], PEDIDOS[19]], ids=[NOMES[0], NOMES[8], NOMES[18], NOMES[19]])
def test_qualquer_registo_do_motorista_bloqueia_tambem_sem_resultado(sessao, ors_falso, pedido, registo):
    """Basta o `estado` (`feita` ou `nao_feita`), mesmo sem resultado nem
    `concluida_em`: a F3 não interpreta o registo, só o respeita."""
    cliente = sessao(_base_com_registo(estado=registo))
    antes = _gravadas(cliente.base)
    r = pedido(cliente)
    assert (r.status_code, r.json()) == (409, ROTA_EM_CURSO)
    assert _gravadas(cliente.base) == antes
    assert ors_falso.pedidos == []


@pytest.mark.parametrize("pedido", [PEDIDOS[0], PEDIDOS[2], PEDIDOS[8], PEDIDOS[16], PEDIDOS[18], PEDIDOS[19]],
                         ids=[NOMES[0], NOMES[2], NOMES[8], NOMES[16], NOMES[18], NOMES[19]])
def test_um_registo_numa_paragem_retirada_tambem_bloqueia(sessao, ors_falso, pedido):
    """O motorista fez a visita e o escritório retirou a paragem entretanto
    (ou ao contrário): a rota tem um registo, e é só de leitura (§1
    "Estados": mesmo retirada). Reativar a D também não."""
    cliente = sessao(_base_com_tres(por_paragem={PARAGEM_D: REGISTO_FEITA}))
    antes = _gravadas(cliente.base)
    r = pedido(cliente)
    assert (r.status_code, r.json()) == (409, ROTA_EM_CURSO)
    assert _gravadas(cliente.base) == antes
    assert _gravadas(cliente.base)[0]["paragens"][INDICE[PARAGEM_D]] == _retirada(PARAGEM_D, LOJA_D, **REGISTO_FEITA)
    assert ors_falso.pedidos == []


def test_a_rota_com_registo_le_se_na_mesma_e_so_de_leitura(sessao):
    """O escritório vê a rota (200), com `editavel: false`, o estado gravado
    (o fecho é da F5) e o que o motorista registou na paragem."""
    cliente = sessao(_base_com_registo())
    r = cliente.get(_url())
    assert r.status_code == 200, r.text
    rota = r.json()
    assert (rota["existe"], rota["editavel"], rota["estado"], rota["estado_efetivo"]) == (True, False, "rascunho", "rascunho")
    feita = next(p for p in rota["paragens"] if p["id"] == PARAGEM_B)
    assert (feita["estado"], feita["resultado"], feita["numero"]) == ("feita", "interessado", 1)
    assert _operacoes(cliente.base) == ["find_one"]


def test_uma_paragem_reposta_pelo_motorista_com_ordem_nula_le_se_e_fecha_a_rota(sessao, ors_falso):
    """Correção "T3.3 (ativas com ordem nula)": a F4 repõe uma retirada só
    com `removida_em: null`, e a `ordem` fica `null`. A rota lê-se sem erro
    (a paragem vai para o fim, com o número a seguir) e é só de leitura."""
    reposta = {"ordem": None, "removida_em": None, **REGISTO_FEITA}
    cliente = sessao(_base_com_tres(por_paragem={PARAGEM_D: reposta}))
    antes = _gravadas(cliente.base)

    r = cliente.get(_url())

    assert r.status_code == 200, r.text
    rota = r.json()
    assert rota["editavel"] is False
    assert [(p["id"], p["numero"], p["ordem"]) for p in rota["paragens"]] == [
        (PARAGEM_B, 1, 0), (PARAGEM_C, 2, 1), (PARAGEM_A, None, 2), (PARAGEM_D, 3, None),
    ]
    assert rota["paragens"][3]["estado"] == "feita"
    for pedido in PEDIDOS:
        r = pedido(cliente)
        assert (r.status_code, r.json()) == (409, ROTA_EM_CURSO)
    assert _gravadas(cliente.base) == antes
    assert ors_falso.pedidos == []


def test_uma_rota_fora_dos_estados_editaveis_tambem_e_so_de_leitura(sessao, ors_falso):
    """A F4 grava `em_curso` ao arrancar o dia (e a F5 `concluida`): sem
    nenhum registo numa paragem, o estado chega para fechar o escritório."""
    cliente = sessao(_base_com_tres(estado="em_curso"))
    antes = _gravadas(cliente.base)
    for pedido in PEDIDOS:
        r = pedido(cliente)
        assert (r.status_code, r.json()) == (409, ROTA_EM_CURSO)
    assert _gravadas(cliente.base) == antes
    assert ors_falso.pedidos == []
    assert cliente.get(_url()).json()["editavel"] is False


# --- A corrida: o motorista grava entre a leitura e a escrita ---------------------------------------


def _motorista(docs):
    """O registo da F4 na 1.ª paragem da lista (a A), feito entre a leitura e
    a escrita do escritório: só o campo do terreno, nada mais."""
    docs[0]["paragens"][0]["estado"] = "feita"


def _com_a_a_feita(rota):
    esperada = deepcopy(rota)
    esperada["paragens"][0]["estado"] = "feita"
    return esperada


# As escritas que passam o bloqueio numa rota livre e chegam à escrita
# condicional (sem o "PATCH só com a versão", que responde sem escrever, e
# sem o "nao_cabe false" numa paragem que já cabe).
CORRIDAS = [
    (nome, pedido, caminhos)
    for nome, pedido, caminhos in ESCRITAS
    if nome not in ("PATCH so com a versao", "PATCH nao_cabe false", "PATCH a propria paragem feita", "PATCH retirar a feita")
]


@pytest.mark.parametrize("pedido, caminhos", [(p, c) for _, p, c in CORRIDAS], ids=[n for n, _, _ in CORRIDAS])
def test_o_motorista_a_registar_entre_a_leitura_e_a_escrita_da_rota_em_curso_e_nada_do_escritorio_fica(
    sessao, ors_falso, pedido, caminhos
):
    """O gancho corre antes da `find_one_and_update`: o filtro de guarda
    (`"paragens.estado": {"$nin": ["feita", "nao_feita"]}`) já não casa,
    `porque_falhou` relê e diz `em_curso` → 409, sem nova tentativa (também
    no POST sem versão). Na base fica só o `feita` do motorista."""
    base = _base_com_tres()
    base.crm_rotas.antes_de("find_one_and_update", _motorista)
    cliente = sessao(base)

    r = pedido(cliente)

    assert (r.status_code, r.json()) == (409, ROTA_EM_CURSO)
    assert _gravadas(base) == [_com_a_a_feita(_rota(AMANHA, _tres_paragens()))]
    assert _operacoes(base) == ["find_one", "find_one_and_update", "find_one"]
    escrita = base.crm_rotas.registo[1]
    assert escrita[1] == {
        "id": "r-1", "versao": 3, "calculo": None, "estado": {"$in": ["rascunho", "planeada"]}, **GUARDA_DO_TERRENO,
    }
    assert escrita[3:] == (SEM_ID, False, ReturnDocument.AFTER)
    assert base.crm_rotas.registo[2][1:] == ({"id": "r-1"}, SEM_CALCULO), "o porque_falhou, não uma nova tentativa"
    assert ors_falso.caminhos() == caminhos, "o openrouteservice já tinha respondido; a rota não muda na mesma"


def test_a_corrida_com_o_nao_feita_e_igual(sessao):
    base = _base_com_tres()

    def motorista(docs):
        docs[0]["paragens"][3]["estado"] = "nao_feita"

    base.crm_rotas.antes_de("find_one_and_update", motorista)
    cliente = sessao(base)
    r = cliente.patch(_url(), json={"versao": 3, "ordem": [PARAGEM_C, PARAGEM_B]})
    assert (r.status_code, r.json()) == (409, ROTA_EM_CURSO)
    esperada = _rota(AMANHA, _tres_paragens())
    esperada["paragens"][3]["estado"] = "nao_feita"
    assert _gravadas(base) == [esperada]


def test_na_corrida_o_em_curso_ganha_ao_conflito(sessao):
    """O motorista registou E outra pessoa gravou (a versão subiu): o
    planeador tem de passar a só leitura, não recarregar e tentar outra vez
    (correção "T3.17 (porque_falhou: precedência)")."""
    base = _base_com_tres()

    def os_dois(docs):
        docs[0]["paragens"][0]["estado"] = "feita"
        docs[0]["versao"] += 1

    base.crm_rotas.antes_de("find_one_and_update", os_dois)
    cliente = sessao(base)
    r = cliente.patch(_url(), json={"versao": 3, "hora_saida": "07:00"})
    assert (r.status_code, r.json()) == (409, ROTA_EM_CURSO)
    assert _gravadas(base) == [_com_a_a_feita(_rota(AMANHA, _tres_paragens(), versao=4))]


# --- O varrimento: uma sequência real ------------------------------------------------------------


def _ok(resposta):
    assert resposta.status_code in (200, 201), resposta.text
    return resposta.json()


def _sequencia(cliente):
    """Adicionar 3 (B, C e A, que fecha à quarta), reordenar, mudar o motivo,
    manter a A, retirar a C, recalcular, otimizar e guardar — cada passo com
    a versão em vigor, como o planeador faz. Devolve as respostas."""
    respostas = []

    def passo(resposta):
        respostas.append(_ok(resposta))
        return respostas[-1]

    passo(cliente.post(_url("/paragens"), json={"loja_id": LOJA_B}))
    passo(cliente.post(_url("/paragens"), json={"loja_id": LOJA_C}))
    rota = passo(cliente.post(_url("/paragens"), json={"loja_id": LOJA_A}))
    por_loja = {p["loja_id"]: p["id"] for p in rota["paragens"]}
    b, c, a = por_loja[LOJA_B], por_loja[LOJA_C], por_loja[LOJA_A]
    rota = passo(cliente.patch(_url(), json={"versao": rota["versao"], "ordem": [c, b]}))
    rota = passo(cliente.patch(_url(), json={"versao": rota["versao"], "paragens": {b: {"motivo": "entrega"}}}))
    rota = passo(cliente.patch(_url(), json={"versao": rota["versao"], "paragens": {a: {"manter_fechada": True}}}))
    rota = passo(cliente.patch(_url(), json={"versao": rota["versao"], "retirar": [c]}))
    rota = passo(cliente.post(_url("/recalcular"), json={"versao": rota["versao"]}))
    rota = passo(cliente.post(_url("/otimizar"), json={"versao": rota["versao"]}))
    passo(cliente.patch(_url(), json={"versao": rota["versao"], "estado": "planeada"}))
    return respostas


def test_uma_sequencia_real_nunca_escreve_no_terreno(sessao, ors_falso):
    """Todas as atualizações registadas no duplo passam no verificador do
    contrato com a F4 e os documentos no dos instantes; o terreno de todas as
    paragens fica `pendente`/null/null do princípio ao fim."""
    cliente = sessao(_base())

    respostas = _sequencia(cliente)

    escritas = _escritas(cliente.base)
    assert [operacao for operacao, _ in escritas] == ["insert_one"] + ["find_one_and_update"] * 9
    for operacao, atualizacao in escritas:
        assert escritas_no_terreno(atualizacao) == [], (operacao, atualizacao)
        assert instantes_fora_do_formato(atualizacao) == [], (operacao, atualizacao)
    for operacao, atualizacao in escritas[1:]:
        assert set(atualizacao) <= {"$set", "$inc", "$push"}, atualizacao
        assert not any(caminho.startswith("paragens.$") for operador in atualizacao.values() for caminho in operador)
    assert ors_falso.caminhos() == [CAMINHO_DIRECOES, CAMINHO_VROOM, CAMINHO_DIRECOES]

    gravada = _gravadas(cliente.base)[0]
    assert instantes_fora_do_formato(gravada) == []
    assert (gravada["estado"], gravada["versao"]) == ("planeada", 9)
    assert [(p["loja_id"], p["ordem"], p["removida_em"] is None) for p in gravada["paragens"]] == [
        (LOJA_B, 0, True), (LOJA_C, None, False), (LOJA_A, 1, True),
    ]
    assert gravada["calculo"] is not None
    for paragem in gravada["paragens"]:
        assert {c: paragem[c] for c in ("estado", "resultado", "concluida_em")} == {
            "estado": "pendente", "resultado": None, "concluida_em": None,
        }
    assert respostas[-1]["editavel"] is True
    assert [p["estado"] for p in respostas[-1]["paragens"]] == ["pendente", "pendente"]


def test_depois_da_sequencia_o_primeiro_registo_do_motorista_fecha_a_rota(sessao, ors_falso):
    """O dia chega e o motorista regista a primeira paragem: a partir daí
    nenhuma escrita do escritório passa, e o que ele gravou fica intacto."""
    cliente = sessao(_base())
    rota = _sequencia(cliente)[-1]
    docs = cliente.base.crm_rotas.docs
    docs[0]["paragens"][0].update(REGISTO_FEITA)
    antes = _gravadas(cliente.base)
    ors_falso.pedidos.clear()

    for pedido in PEDIDOS:
        r = pedido(cliente, versao=rota["versao"])
        assert (r.status_code, r.json()) == (409, ROTA_EM_CURSO)

    assert _gravadas(cliente.base) == antes
    assert ors_falso.pedidos == []
    lida = cliente.get(_url()).json()
    assert lida["editavel"] is False
    assert (lida["paragens"][0]["estado"], lida["paragens"][0]["resultado"]) == ("feita", "interessado")
