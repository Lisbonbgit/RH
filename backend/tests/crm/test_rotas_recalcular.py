"""`POST /api/crm/rotas/{data}/recalcular` — as horas da rota pelo Directions
do openrouteservice (plano F3 §1 "Horas", "Recálculo" e §4; T3.21).

As regras estão provadas em baixo: o pedido e a leitura dos troços
(`dominio.directions`, T3.7), as chegadas, as esperas e a assinatura
(`dominio.horarios`, T3.8), o cliente do openrouteservice (`servicos.ors`,
T3.11), a forma da resposta (`formatar_rota.rota_api`, T3.16) e a escrita
condicional (`rotas_bd.alterar`/`porque_falhou`, T3.17). Aqui prova-se a rota
HTTP: quem entra, a ordem das verificações do plano §4, o pedido que sai (só
coordenadas e constantes), o que lê e o que escreve (o filtro e a atualização
exatos no registo do duplo), as falhas do openrouteservice (nada muda) e a
resposta.

- **O pedido:** as coordenadas `[início] + incluídas (secção "rota", pela
  ordem) + [fim]`, sem as fechadas sem "Manter", as `nao_cabe` nem as
  `sem_loja`; `avoid_features: ["tollways"]` com `evitar_portagens`; o início
  e o fim próprios da rota ou a fábrica das definições em vigor. Nunca nomes,
  telefones, moradas, notas nem uuids (§0, regra 12).
- **A escrita:** uma só `find_one_and_update` com o filtro de guarda e um
  `$set` SEM `$inc` nem autoria (`rotas_bd.alterar(..., subir_versao=False)`:
  as horas são dados derivados e **a versão não muda**): por paragem ativa,
  `paragens.N.chegada_prevista|espera_min|fora_de_horario` só do que muda (as
  excluídas ficam a `None`/`None`/`False`), e o `calculo` inteiro com a
  assinatura da entrada (`calculo.atual: true` na resposta), os totais, o
  regresso, a geometria e `calculado_em` de agora.
- **Sem paragens incluídas:** não chama o openrouteservice e põe `calculo:
  None` (só se havia um; senão 200 sem escrever).
- **Falhas do openrouteservice** (503 `calculo_indisponivel`, com `tipo`;
  **nada é escrito**): sem chave → `sem_chave` sem pedido; 429 → `limite`;
  um 2010 → `ponto_sem_estrada` com a mensagem da paragem N (o índice da
  coordenada é o número da paragem na secção "rota"), do início (0) ou do
  fim (o último); o resto (401/500, uma resposta que não é JSON ou sem a
  forma esperada, a rede) → `indisponivel`. Fica um registo
  `"[crm] rota AAAA-MM-DD: o openrouteservice falhou (recalcular) — <motivo>"`,
  sem coordenadas e sem a chave.
- **Recusas, pela ordem do plano §4:** 400 → 422 (`data`, `versao`) → 404
  "Ainda não há rota para este dia." → 409 `rota_fechada` → 409
  `rota_em_curso` → 409 `conflito` → 503 → a escrita → a falha: 404 / 409
  `conflito` / 409 `rota_em_curso` (`porque_falhou`), sem tentar outra vez.
- O relógio lê-se uma vez por pedido; só o escritório; a guarda antes do
  corpo.

Os testes das rotas usam respostas construídas no próprio teste para os
valores exatos (durações e distâncias escolhidas, a linha pelo
`polilinha.codificar`, e o simulador local `ors_simulado_local.direcoes` para
o formato do ORS, troço de comprimento zero incluído), e as gravadas
(`fixtures/ors/direcoes-tres-paragens.json`) só provam o formato real
(decisão da T3.12). Correção "T3.7 (+ T3.13, T3.21)": duas paragens nas
mesmas coordenadas → 200, com chegadas seguidas e espera 0.

Molde do test_rotas_alterar.py (T3.20).
"""
import json
import logging
import math
import time
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo import ReturnDocument

import crm
import crm.db
import faturacao.auth
import ors_simulado_local
from crm import relogio
from crm import rotas as rotas_http
from crm.auth import ESCRITORIO, membro_crm_atual
from crm.dominio import polilinha
from crm.dominio import rotas as dominio_rotas
from crm.dominio.directions import pedido_direcoes
from crm.dominio.horarios import assinatura, entrada_calculo
from crm.formatar_rota import PROJECAO_LOJA_ROTA, rota_api
from crm.pedidos import corpo_json
from crm.servicos import ors
from faturacao.auth import utilizador_atual

from .duplos import BaseFalsa
from .formatos import escritas_no_terreno, instantes_fora_do_formato

ROTAS_URL = "/api/crm/rotas"
CAMINHO = ROTAS_URL + "/{data}/recalcular"
ADMIN_LOCAL = "admin.local@example.com"
JSON = {"Content-Type": "application/json"}
FIXTURES = Path(__file__).parent / "fixtures" / "ors"

UTC = timezone.utc
# 23:30Z de 12 de outubro de 2026: em Lisboa (WEST, UTC+1) já é dia 13.
AGORA = datetime(2026, 10, 12, 23, 30, 15, 987654, tzinfo=UTC)
AGORA_INSTANTE = "2026-10-12T23:30:15Z"
HOJE = "2026-10-13"  # uma terça-feira
ONTEM = "2026-10-12"
AMANHA = "2026-10-14"  # uma quarta-feira

MEMBRO = "membro-1"
ZE = "u-ze"
LOJA_A = "00000000-0000-4000-8000-00000000000a"
LOJA_B = "00000000-0000-4000-8000-00000000000b"
LOJA_C = "00000000-0000-4000-8000-00000000000c"
LOJA_D = "00000000-0000-4000-8000-00000000000d"

PARAGEM_A = "10000000-0000-4000-8000-00000000000a"
PARAGEM_B = "10000000-0000-4000-8000-00000000000b"
PARAGEM_C = "10000000-0000-4000-8000-00000000000c"
PARAGEM_D = "10000000-0000-4000-8000-00000000000d"  # retirada
# O índice de cada paragem na lista gravada (`_tres_paragens`).
INDICE = {PARAGEM_A: 0, PARAGEM_B: 1, PARAGEM_D: 2, PARAGEM_C: 3}

COMERCIO = (38.7075, -9.1364)
MARQUES = (38.7253, -9.15)
BELEM = (38.6979, -9.2065)
FABRICA_PADRAO = (38.7223, -9.1393)
OUTRA_FABRICA = (38.75, -9.2)
OUTRO_PONTO = {"lat": 38.6, "lng": -9.1}

# O openrouteservice falso: a chave canária e o URL de teste.
CHAVE = "ors-CANARIA-chave-do-recalcular-5b3ce3597851110001cf6248"
BASE = "https://ors.teste"
URL_DIRECOES = BASE + "/v2/directions/driving-car/json"

# A rota por omissão: B (Marquês) e C (Belém) incluídas, A fechada à quarta.
PONTOS = [FABRICA_PADRAO, MARQUES, BELEM, FABRICA_PADRAO]
DURACOES = [600, 900, 1200]
DISTANCIAS = [1000.5, 2000.25, 3000.0]  # soma 6000,75 → 6001
# Saída 08:00 → B às 08:10 (serviço 15) → C às 08:40, espera até às 09:00
# (serviço 15) → regresso às 09:35.
HORAS_PADRAO = {"paragens.1.chegada_prevista": "08:10", "paragens.1.espera_min": 0,
                "paragens.3.chegada_prevista": "08:40", "paragens.3.espera_min": 20}
COORDENADAS_CANARIAS = ("38.7253", "9.15", "38.6979", "9.2065", "38.7223", "9.1393")

DEFINICOES_PADRAO = {
    "fabrica_morada": "",
    "fabrica_lat": FABRICA_PADRAO[0],
    "fabrica_lng": FABRICA_PADRAO[1],
    "rota_hora_saida": "08:00",
    "rota_hora_regresso": "19:00",
    "servico_entrega_min": 10,
    "servico_amostra_min": 10,
    "servico_acompanhamento_min": 15,
    "servico_angariacao_min": 15,
}

CALCULO_VELHO = {
    "assinatura": "sha256:" + "0" * 64,
    "distancia_m": 12345,
    "duracao_s": 3600,
    "regresso_previsto": "12:00",
    "depois_do_limite": False,
    "geometria": "_p~iF~ps|U_ulLnnqC_mqNvxq`@",
    "calculado_em": "2026-10-10T09:30:00Z",
}

DATA = "Indique o dia no formato AAAA-MM-DD."
HORIZONTE = "Escolha um dia até um ano a partir de hoje."
VERSAO_OBRIGATORIA = "Indique a versão da rota que recebeu."

GERAL = "Cálculo automático indisponível — ordene à mão"
LIMITE = "Cálculo automático indisponível por agora (limite de pedidos) — espere um minuto ou ordene à mão"
INICIO_SEM_ESTRADA = "O ponto de início não fica perto de uma estrada — escolha outro ponto"
FIM_SEM_ESTRADA = "O ponto de fim não fica perto de uma estrada — escolha outro ponto"


def _paragem_sem_estrada(numero):
    return f"A paragem {numero} não fica perto de uma estrada — corrija a localização da loja"


def _indisponivel(tipo, mensagem=GERAL):
    return {"detail": {"codigo": "calculo_indisponivel", "mensagem": mensagem, "tipo": tipo}}


SEM_PERMISSAO = {"detail": {"codigo": "sem_permissao", "mensagem": "Sem permissão para esta ação."}}
SEM_ACESSO = {"detail": {"codigo": "sem_acesso_crm", "mensagem": "Sem acesso ao CRM."}}
JSON_INVALIDO = {"detail": {"codigo": "json_invalido", "mensagem": "O pedido não é JSON válido."}}
SEM_ROTA = {"detail": {"codigo": "nao_encontrado", "mensagem": "Ainda não há rota para este dia."}}
CONFLITO = {"detail": {"codigo": "conflito", "mensagem": "Alterado por outra pessoa — recarregar"}}
ROTA_FECHADA = {"detail": {"codigo": "rota_fechada", "mensagem": "Este dia já passou — a rota só se pode ver."}}
ROTA_EM_CURSO = {
    "detail": {
        "codigo": "rota_em_curso",
        "mensagem": "A rota já tem registos do motorista — no escritório só se pode ver.",
    }
}

SEM_ID = {"_id": 0}
SEM_CALCULO = {"_id": 0, "calculo": 0}
PROJECAO_DEFINICOES = {"_id": 0, "chave": 1, "valor": 1}
FILTRO_DE_ESCRITA = {
    "id": "r-1",
    "versao": 3,
    "estado": {"$in": ["rascunho", "planeada"]},
    "paragens.estado": {"$nin": ["feita", "nao_feita"]},
}

USERS = [
    {"id": "u-admin", "email": ADMIN_LOCAL, "name": "Administrador Principal", "role": "admin",
     "password": "$2b$12$hash-do-admin"},
    {"id": "u-ana", "email": "ana@example.com", "name": "Ana Reis", "role": "contabilista",
     "password": "$2b$12$hash-da-ana"},
    {"id": ZE, "email": "ze@example.com", "name": "Zé Silva", "role": "colaborador",
     "password": "$2b$12$hash-do-ze"},
    {"id": "u-alv", "email": "alvaro@example.com", "name": "Álvaro Costa", "role": "gerente",
     "password": "$2b$12$hash-do-alvaro"},
    {"id": "u-bea", "email": "bea@example.com", "name": "Beatriz Lopes", "role": "colaborador",
     "password": "$2b$12$hash-da-bea"},
]
MEMBROS = [
    {"id": "m-ana", "user_id": "u-ana", "perfil": "admin", "criado_em": "2026-10-03T09:00:00Z"},
    {"id": "m-ze", "user_id": ZE, "perfil": "utilizador", "criado_em": "2026-10-01T09:00:00Z"},
    {"id": "m-alv", "user_id": "u-alv", "perfil": "motorista", "criado_em": "2026-10-02T09:00:00Z"},
    {"id": "m-apagada", "user_id": "u-apagada", "perfil": "utilizador", "criado_em": "2026-09-30T09:00:00Z"},
]

ADMIN_MASTER = {"user_id": "u-admin", "email": ADMIN_LOCAL, "role": "admin"}
ANA_ADMIN_DO_CRM = {"user_id": "u-ana", "email": "ana@example.com", "role": "contabilista"}
ZE_UTILIZADOR = {"user_id": ZE, "email": "ze@example.com", "role": "colaborador"}
ALVARO_MOTORISTA = {"user_id": "u-alv", "email": "alvaro@example.com", "role": "gerente"}
BEA_NAO_MEMBRO = {"user_id": "u-bea", "email": "bea@example.com", "role": "colaborador"}


# --- montagem ------------------------------------------------------------------------------------


def _url(data=AMANHA):
    return f"{ROTAS_URL}/{data}/recalcular"


def _validacao(campos):
    return {"detail": {"codigo": "validacao", "mensagem": "Verifique os campos assinalados.", "campos": campos}}


def _guardada(chave, valor, quando="2026-10-01T08:00:00.000000Z", por="u-ana"):
    return {"chave": chave, "valor": valor, "atualizado_em": quando, "atualizado_por": por}


def _paragem(id_, loja_id, ordem, **campos):
    return {
        "id": id_, "loja_id": loja_id, "ordem": ordem, "motivo": "angariacao", "tempo_servico_min": 15,
        "manter_fechada": False, "nao_cabe": False, "chegada_prevista": None, "espera_min": None,
        "fora_de_horario": False, "adicionada_em": "2026-10-10T09:00:00Z", "adicionada_por": MEMBRO,
        "removida_em": None, "estado": "pendente", "resultado": None, "concluida_em": None, **campos,
    }


def _retirada(id_, loja_id, **campos):
    return _paragem(id_, loja_id, None, removida_em="2026-10-10T10:00:00Z", **campos)


def _feita(id_, loja_id, ordem, **campos):
    return _paragem(
        id_, loja_id, ordem, estado="feita", resultado="interessado", concluida_em="2026-10-13T10:00:00Z", **campos
    )


def _rota(data=AMANHA, paragens=(), id_="r-1", **campos):
    return {
        "id": id_, "data": data, "estado": "rascunho", "versao": 3, "hora_saida": "08:00",
        "hora_regresso_limite": "19:00", "inicio": None, "fim": None, "evitar_portagens": False,
        "paragens": [dict(p) for p in paragens], "calculo": None, "criado_em": "2026-10-10T09:00:00Z",
        "criado_por": MEMBRO, "atualizado_em": "2026-10-10T09:00:00.000000Z", "atualizado_por": MEMBRO, **campos,
    }


def _loja(id_, nome, fase, ponto, **extra):
    """Uma loja da base, com mais campos do que a projeção da rota traz."""
    return {
        "id": id_, "nome": nome, "fase": fase, "lat": ponto[0], "lng": ponto[1], "telefone": "+351911111111",
        "janelas": [], "dias_fechada": [], "morada": "Rua Secreta 1", "notas": "não sai na rota",
        "regiao_id": None, "pessoa_contacto": "Sr. Silva", **extra,
    }


def _lojas(ponto_d=(38.71, -9.14), janelas_c=({"inicio": "09:00", "fim": "12:00"},)):
    # A A fecha à quarta (o dia de AMANHA); as outras abrem todos os dias.
    return [
        _loja(LOJA_A, "Café A", "contactada", COMERCIO, dias_fechada=["qua"]),
        _loja(LOJA_B, "Pastelaria B", "potencial", MARQUES),
        _loja(LOJA_C, "Mercearia C", "cliente", BELEM, janelas=list(janelas_c)),
        _loja(LOJA_D, "Quiosque D", "potencial", ponto_d),
    ]


def _tres_paragens(**por_paragem):
    """Pela ordem: B (0), C (1) e A (2, fechada à quarta); a D retirada (índice
    2 da lista). `por_paragem={PARAGEM_C: {...}}` altera uma delas."""
    paragens = [
        _paragem(PARAGEM_A, LOJA_A, 2), _paragem(PARAGEM_B, LOJA_B, 0), _retirada(PARAGEM_D, LOJA_D),
        _paragem(PARAGEM_C, LOJA_C, 1),
    ]
    for paragem in paragens:
        paragem.update(por_paragem.get(paragem["id"], {}))
    return paragens


def _projetada(loja):
    return {campo: loja[campo] for campo in PROJECAO_LOJA_ROTA if campo != "_id"}


def _base(rotas=(), lojas=(), definicoes=(), membros=MEMBROS, users=USERS):
    return BaseFalsa({
        "crm_rotas": list(rotas),
        "crm_lojas": list(lojas),
        "crm_definicoes": list(definicoes),
        "crm_membros": list(membros),
        "users": list(users),
    })


def _base_com_tres(lojas=None, por_paragem=None, **campos_da_rota):
    return _base(rotas=[_rota(AMANHA, _tres_paragens(**(por_paragem or {})), **campos_da_rota)],
                 lojas=_lojas() if lojas is None else lojas)


def _dia(texto):
    return date(*(int(parte) for parte in texto.split("-")))


def _api(rota, lojas, hoje=HOJE, definicoes=None, calculo_disponivel=True):
    """O que o `rota_api` dá para esta rota gravada: a referência da resposta."""
    return rota_api(
        rota,
        data=_dia(rota["data"]),
        hoje=_dia(hoje),
        lojas=[_projetada(loja) for loja in lojas],
        definicoes=DEFINICOES_PADRAO if definicoes is None else definicoes,
        calculo_disponivel=calculo_disponivel,
    )


def _gravadas(base):
    return base.crm_rotas.sem_id()


def _escritas(base):
    """As operações de escrita registadas em `crm_rotas`."""
    return [c for c in base.crm_rotas.registo if c[0] in ("insert_one", "update_one", "find_one_and_update")]


def _escrita(set_, versao=3, rota_id="r-1"):
    """A única `find_one_and_update` esperada: o filtro de guarda e só o
    `$set` (sem `$inc` e sem autoria: a versão não muda)."""
    return (
        "find_one_and_update",
        {**FILTRO_DE_ESCRITA, "id": rota_id, "versao": versao},
        {"$set": set_},
        SEM_ID,
        False,
        ReturnDocument.AFTER,
    )


def _calculo(rota, lojas, pontos, distancia_m, duracao_s, regresso, depois=False, geometria=None):
    """O `calculo` que fica gravado: a assinatura da entrada de agora (a rota
    tal como está, só com a secção "rota" pela ordem e os extremos
    resolvidos), os totais, o regresso, a linha e o instante."""
    lojas_por_id = {loja["id"]: loja for loja in lojas}
    seccoes = dominio_rotas.seccoes(rota["paragens"], lojas_por_id, _dia(rota["data"]))
    incluidas = [(paragem, loja) for paragem, loja, seccao, _ in seccoes if seccao == "rota"]
    return {
        "assinatura": assinatura(entrada_calculo(rota, incluidas, pontos[0], pontos[-1])),
        "distancia_m": distancia_m,
        "duracao_s": duracao_s,
        "regresso_previsto": regresso,
        "depois_do_limite": depois,
        "geometria": polilinha.codificar(pontos) if geometria is None else geometria,
        "calculado_em": AGORA_INSTANTE,
    }


def _direcoes(duracoes=DURACOES, distancias=DISTANCIAS, pontos=PONTOS, resumo=True):
    """Uma resposta do Directions escrita aqui, no formato do ORS: um troço por
    par de pontos seguidos (uma medida `None` fica de fora, como o ORS faz
    com um troço de comprimento zero), o resumo pela soma e a linha
    codificada (precisão 5)."""
    segmentos = []
    for indice, (duracao, distancia) in enumerate(zip(duracoes, distancias)):
        segmento = {}
        if distancia is not None:
            segmento["distance"] = distancia
        if duracao is not None:
            segmento["duration"] = duracao
        segmento["steps"] = [
            {**segmento, "type": 11, "instruction": "Head", "name": "-", "way_points": [indice, indice + 1]},
            {"type": 10, "instruction": "Arrive", "name": "-", "way_points": [indice + 1, indice + 1]},
        ]
        segmentos.append(segmento)
    rota = {"segments": segmentos, "geometry": polilinha.codificar(pontos), "way_points": list(range(len(pontos)))}
    if resumo:
        rota = {
            "summary": {
                "distance": math.fsum(d for d in distancias if d is not None),
                "duration": math.fsum(d for d in duracoes if d is not None),
            },
            **rota,
        }
    return {"routes": [rota], "metadata": {"attribution": "openrouteservice.org | OpenStreetMap contributors"}}


def _erro_2010(indice, estado=404):
    mensagem = (
        f"Could not find routable point within a radius of 350.0 meters of specified coordinate {indice}: "
        "-9.0350000 38.7200000."
    )
    return estado, {"error": {"code": 2010, "message": mensagem}}


def _fixture(nome):
    return json.loads((FIXTURES / nome).read_text(encoding="utf-8"))


class OrsFalso:
    """O openrouteservice falso, como handler de um `httpx.MockTransport`:
    guarda os pedidos recebidos e responde o que `responde(...)` fixou (por
    omissão, a resposta padrão de `_direcoes()`)."""

    def __init__(self):
        self.pedidos = []
        self.respostas = []
        self.responde()

    def __call__(self, pedido):
        self.pedidos.append(pedido)
        return self._responder(pedido)

    def responde(self, dados=None, estado=200, conteudo=None):
        def _responder(pedido):
            corpo = conteudo if conteudo is not None else json.dumps(_direcoes() if dados is None else dados).encode("utf-8")
            return httpx.Response(estado, content=corpo)

        self._responder = _responder

    def pelo_simulador(self):
        """Responde como o simulador local (T3.13) ao corpo recebido."""

        def _responder(pedido):
            resposta = ors_simulado_local.direcoes(json.loads(pedido.content))
            self.respostas.append(resposta)
            return httpx.Response(200, json=resposta)

        self._responder = _responder

    def falha(self, excecao):
        def _responder(pedido):
            raise excecao(pedido)

        self._responder = _responder

    def corpos(self):
        return [json.loads(pedido.content) for pedido in self.pedidos]


@pytest.fixture
def ors_falso(monkeypatch):
    """A chave canária e o URL de teste no ambiente; o transporte do cliente
    trocado pelo `OrsFalso` (a guarda do conftest fica sem pedidos)."""
    monkeypatch.setenv(ors.VARIAVEL_CHAVE, CHAVE)
    monkeypatch.setenv(ors.VARIAVEL_URL, BASE)
    falso = OrsFalso()
    monkeypatch.setattr(ors, "_transporte", httpx.MockTransport(falso))
    return falso


def _rota_http(caminho=CAMINHO, metodo="POST"):
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
    (com `cliente.base`); por omissão, a rota de AMANHA com três paragens."""
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    monkeypatch.setattr(relogio, "agora", lambda: AGORA)

    def _montar(utilizador=ZE_UTILIZADOR, base=None, levantar=True):
        base = base if base is not None else _base_com_tres()
        monkeypatch.setattr(crm.db, "obter_db", lambda: base)
        app = FastAPI()
        app.include_router(crm.router)
        app.dependency_overrides[utilizador_atual] = lambda: dict(utilizador)
        cliente = TestClient(app, raise_server_exceptions=levantar)
        cliente.base = base
        return cliente

    return _montar


def _recalcular(cliente, data=AMANHA, versao=3, **corpo):
    return cliente.post(_url(data), json={"versao": versao, **corpo})


def _ok(cliente, **corpo):
    """Um recalcular que tem de dar 200; devolve `(resposta, rota gravada)`."""
    r = _recalcular(cliente, **corpo)
    assert r.status_code == 200, r.text
    return r, _gravadas(cliente.base)[0]


def _nada_muda(cliente, antes):
    """Nada do escritório ficou escrito: nenhuma escrita no registo e a rota
    tal como estava."""
    assert _escritas(cliente.base) == []
    assert _gravadas(cliente.base) == antes


# --- A rota: onde está, quem a guarda e a ordem das dependências ----------------------------------


def test_a_rota_existe_e_vive_em_crm_rotas():
    rota = _rota_http()
    assert rota.methods == {"POST"}
    assert rota.endpoint.__module__ == rotas_http.__name__ == "crm.rotas"
    assert rota.status_code in (None, 200)


def test_so_o_escritorio_recalcula_e_o_corpo_le_se_depois_da_guarda():
    """Exatamente uma guarda de perfil, a do escritório, sobre
    `membro_crm_atual`; o `corpo_json` depois dela (regra T1.3/T2.15)."""
    dependencias = _dependencias(_rota_http())
    assert membro_crm_atual in dependencias
    assert [d for d in dependencias if hasattr(d, "perfis_crm")] == [ESCRITORIO]
    assert corpo_json in dependencias
    assert dependencias.index(ESCRITORIO) < dependencias.index(corpo_json)


# --- O pedido ao Directions ----------------------------------------------------------------------


def test_o_pedido_leva_o_inicio_as_incluidas_pela_ordem_e_o_fim_com_a_chave_so_no_cabecalho(sessao, ors_falso):
    """Um só POST ao Directions com `[fábrica, B, C, fábrica]` (a ordem das
    paragens, não a da lista gravada; a A fechada à quarta fica de fora), o
    corpo exato do `pedido_direcoes` e a chave só no `Authorization`."""
    cliente = sessao()
    _ok(cliente)
    assert len(ors_falso.pedidos) == 1
    pedido = ors_falso.pedidos[0]
    assert (pedido.method, str(pedido.url)) == ("POST", URL_DIRECOES)
    assert pedido.headers["Authorization"] == CHAVE
    assert CHAVE not in str(pedido.url) and CHAVE.encode() not in pedido.content
    assert ors_falso.corpos() == [pedido_direcoes(PONTOS, False)]
    assert ors_falso.corpos()[0]["coordinates"] == [[-9.1393, 38.7223], [-9.15, 38.7253], [-9.2065, 38.6979], [-9.1393, 38.7223]]


def test_o_pedido_nao_leva_nomes_telefones_moradas_notas_nem_uuids(sessao, ors_falso):
    """§0, regra 12: só coordenadas e constantes. As chaves do corpo são
    exatamente as do `pedido_direcoes`."""
    cliente = sessao()
    _ok(cliente)
    texto = ors_falso.pedidos[0].content.decode("utf-8")
    for canario in ("Pastelaria", "Mercearia", "Café", "+351", "Rua Secreta", "não sai", "Sr. Silva",
                    LOJA_B, LOJA_C, PARAGEM_B, PARAGEM_C, "r-1", AMANHA, "cliente", "potencial"):
        assert canario not in texto
    assert set(ors_falso.corpos()[0]) == {"coordinates", "instructions", "geometry", "elevation", "units"}


def test_uma_paragem_nao_cabe_fica_de_fora_e_as_suas_horas_velhas_apagam_se(sessao, ors_falso):
    """A C com `nao_cabe` não vai ao Directions (`[fábrica, B, fábrica]`) e
    as horas que tinha de um cálculo anterior ficam a `None`/`None`/`False`."""
    velhas = {"nao_cabe": True, "chegada_prevista": "10:00", "espera_min": 5, "fora_de_horario": True}
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(por_paragem={PARAGEM_C: velhas}))
    pontos = [FABRICA_PADRAO, MARQUES, FABRICA_PADRAO]
    ors_falso.responde(_direcoes([600, 1200], [1000.0, 2000.0], pontos))
    r, rota = _ok(cliente)
    assert ors_falso.corpos() == [pedido_direcoes(pontos, False)]
    assert _escritas(cliente.base) == [_escrita({
        "paragens.1.chegada_prevista": "08:10", "paragens.1.espera_min": 0,
        "paragens.3.chegada_prevista": None, "paragens.3.espera_min": None, "paragens.3.fora_de_horario": False,
        "calculo": _calculo(rota, _lojas(), pontos, 3000, 1800, "08:45"),
    })]
    assert r.json() == _api(rota, _lojas())
    assert [(p["numero"], p["seccao"], p["chegada_prevista"]) for p in r.json()["paragens"]] == [
        (1, "rota", "08:10"), (None, "nao_cabe", None), (None, "fechada", None),
    ]


def test_com_manter_fechada_a_paragem_fechada_entra_no_fim(sessao, ors_falso):
    """A A (ordem 2, fechada à quarta) com "Manter" vai ao Directions:
    `[fábrica, B, C, A, fábrica]`, 5 pontos e 4 troços."""
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(por_paragem={PARAGEM_A: {"manter_fechada": True}}))
    pontos = [FABRICA_PADRAO, MARQUES, BELEM, COMERCIO, FABRICA_PADRAO]
    ors_falso.responde(_direcoes([600, 900, 600, 300], [1000.0, 2000.0, 3000.0, 500.0], pontos))
    r, rota = _ok(cliente)
    assert ors_falso.corpos() == [pedido_direcoes(pontos, False)]
    # B 08:10 → C 08:40 (espera até 09:00) → A 09:25 → regresso 09:45.
    assert _escritas(cliente.base) == [_escrita({
        **HORAS_PADRAO, "paragens.0.chegada_prevista": "09:25", "paragens.0.espera_min": 0,
        "calculo": _calculo(rota, _lojas(), pontos, 6500, 2400, "09:45"),
    })]
    assert [(p["numero"], p["chegada_prevista"]) for p in r.json()["paragens"]] == [(1, "08:10"), (2, "08:40"), (3, "09:25")]


def test_com_evitar_portagens_o_pedido_leva_avoid_features(sessao, ors_falso):
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(evitar_portagens=True))
    r, rota = _ok(cliente)
    assert ors_falso.corpos() == [pedido_direcoes(PONTOS, True)]
    assert ors_falso.corpos()[0]["options"] == {"avoid_features": ["tollways"]}
    assert rota["calculo"] == _calculo(rota, _lojas(), PONTOS, 6001, 2700, "09:35")
    assert r.json()["calculo"]["atual"] is True


def test_o_inicio_proprio_da_rota_e_a_fabrica_das_definicoes_em_vigor_como_fim(sessao, ors_falso):
    """`inicio` é o ponto da rota; `fim: null` é a fábrica guardada nas
    definições (não a dos padrões). A assinatura leva os extremos resolvidos."""
    definicoes = [_guardada("fabrica_lat", str(OUTRA_FABRICA[0])), _guardada("fabrica_lng", str(OUTRA_FABRICA[1]))]
    base = _base(rotas=[_rota(AMANHA, _tres_paragens(), inicio=OUTRO_PONTO)], lojas=_lojas(), definicoes=definicoes)
    cliente = sessao(ZE_UTILIZADOR, base)
    pontos = [(OUTRO_PONTO["lat"], OUTRO_PONTO["lng"]), MARQUES, BELEM, OUTRA_FABRICA]
    ors_falso.responde(_direcoes(pontos=pontos))
    r, rota = _ok(cliente)
    assert ors_falso.corpos() == [pedido_direcoes(pontos, False)]
    assert rota["calculo"] == _calculo(rota, _lojas(), pontos, 6001, 2700, "09:35")
    em_vigor = {**DEFINICOES_PADRAO, "fabrica_lat": OUTRA_FABRICA[0], "fabrica_lng": OUTRA_FABRICA[1]}
    assert r.json() == _api(rota, _lojas(), definicoes=em_vigor)
    assert (r.json()["calculo"]["atual"], r.json()["fim"]) == (True, {"lat": OUTRA_FABRICA[0], "lng": OUTRA_FABRICA[1], "fabrica": True})


# --- A escrita -----------------------------------------------------------------------------------


def test_grava_as_horas_e_o_calculo_numa_so_escrita_sem_subir_a_versao(sessao, ors_falso):
    """Uma só `find_one_and_update` com o filtro de guarda e um `$set` sem
    `$inc` nem autoria: as horas das incluídas pelos caminhos por índice (só
    o que muda) e o `calculo` inteiro. A versão, o `atualizado_em` e o
    `atualizado_por` ficam iguais; a resposta é a rota gravada, com
    `calculo.atual: true`."""
    cliente = sessao()
    antes = _gravadas(cliente.base)[0]
    r, rota = _ok(cliente)
    calculo = _calculo(rota, _lojas(), PONTOS, 6001, 2700, "09:35")
    assert _escritas(cliente.base) == [_escrita({**HORAS_PADRAO, "calculo": calculo})]
    assert (rota["versao"], rota["atualizado_em"], rota["atualizado_por"]) == (3, antes["atualizado_em"], MEMBRO)
    assert rota["calculo"] == calculo
    assert rota == {**antes, "paragens": rota["paragens"], "calculo": calculo}
    assert r.json() == _api(rota, _lojas())
    assert (r.json()["versao"], r.json()["calculo"]["atual"], r.json()["calculo_disponivel"]) == (3, True, True)
    assert "assinatura" not in r.json()["calculo"]
    assert [(p["numero"], p["chegada_prevista"], p["espera_min"], p["fora_de_horario"], p["aviso"]) for p in r.json()["paragens"]] == [
        (1, "08:10", 0, False, "nenhum"), (2, "08:40", 20, False, "nenhum"), (None, None, None, False, "fechada_neste_dia"),
    ]
    assert r.json()["calculo"] == {
        "atual": True, "distancia_m": 6001, "duracao_s": 2700, "regresso_previsto": "09:35",
        "depois_do_limite": False, "geometria": polilinha.codificar(PONTOS), "calculado_em": AGORA_INSTANTE,
    }


def test_so_escreve_as_horas_que_mudam_e_o_calculo_escreve_se_sempre(sessao, ors_falso):
    """Com as horas já gravadas iguais às calculadas, o `$set` leva só o
    `calculo` (que fica sempre, com o `calculado_em` de agora)."""
    iguais = {PARAGEM_B: {"chegada_prevista": "08:10", "espera_min": 0}, PARAGEM_C: {"chegada_prevista": "08:40", "espera_min": 20}}
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(por_paragem=iguais, calculo=deepcopy(CALCULO_VELHO)))
    r, rota = _ok(cliente)
    assert _escritas(cliente.base) == [_escrita({"calculo": _calculo(rota, _lojas(), PONTOS, 6001, 2700, "09:35")})]
    assert r.json()["calculo"]["atual"] is True


def test_duas_vezes_seguidas_a_segunda_so_reescreve_o_calculo(sessao, ors_falso):
    cliente = sessao()
    _ok(cliente)
    r, rota = _ok(cliente)
    assert len(ors_falso.pedidos) == 2
    assert _escritas(cliente.base)[1] == _escrita({"calculo": _calculo(rota, _lojas(), PONTOS, 6001, 2700, "09:35")})
    assert (rota["versao"], r.json()["versao"]) == (3, 3)


def test_fora_de_horario_quando_nenhuma_janela_leva_o_servico(sessao, ors_falso):
    """A C recebe das 09:00 às 09:10 e o serviço leva 15 min: serve-se à
    chegada, sem espera, com `fora_de_horario` e o aviso."""
    lojas = _lojas(janelas_c=({"inicio": "09:00", "fim": "09:10"},))
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(lojas=lojas))
    r, rota = _ok(cliente)
    # B 08:10 (+15) → C 08:40, sem espera (+15) → regresso 09:15.
    assert _escritas(cliente.base) == [_escrita({
        "paragens.1.chegada_prevista": "08:10", "paragens.1.espera_min": 0,
        "paragens.3.chegada_prevista": "08:40", "paragens.3.espera_min": 0, "paragens.3.fora_de_horario": True,
        "calculo": _calculo(rota, lojas, PONTOS, 6001, 2700, "09:15"),
    })]
    assert [(p["fora_de_horario"], p["aviso"]) for p in r.json()["paragens"]][:2] == [(False, "nenhum"), (True, "fora_de_horario")]


def test_o_regresso_depois_do_limite(sessao, ors_falso):
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(hora_regresso_limite="09:00"))
    r, rota = _ok(cliente)
    assert rota["calculo"] == _calculo(rota, _lojas(), PONTOS, 6001, 2700, "09:35", depois=True)
    assert r.json()["calculo"]["depois_do_limite"] is True


def test_uma_hora_a_partir_das_24h_fica_nula_com_os_avisos(sessao, ors_falso):
    """Saída às 23:00 e 2 h até à B: a chegada é `None` com `fora_de_horario`,
    e o regresso `None` com `depois_do_limite`."""
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(hora_saida="23:00", hora_regresso_limite="23:30"))
    ors_falso.responde(_direcoes([7200, 600, 600], [1000.0, 1000.0, 1000.0]))
    r, rota = _ok(cliente)
    assert _escritas(cliente.base) == [_escrita({
        "paragens.1.espera_min": 0, "paragens.1.fora_de_horario": True,
        "paragens.3.espera_min": 0, "paragens.3.fora_de_horario": True,
        "calculo": _calculo(rota, _lojas(), PONTOS, 3000, 8400, None, depois=True),
    })]
    assert r.json()["calculo"]["regresso_previsto"] is None
    assert [p["chegada_prevista"] for p in r.json()["paragens"]] == [None, None, None]


def test_duas_paragens_nas_mesmas_coordenadas_dao_chegadas_seguidas_e_espera_zero(sessao, ors_falso):
    """Correção "T3.7 (+ T3.13, T3.21)": a B e a D na mesma morada; o ORS
    deixa o troço do meio sem `distance`/`duration` → 200, a D chega quando a
    B acaba (08:25), as duas com espera 0."""
    lojas = _lojas(ponto_d=MARQUES)
    paragens = [_paragem(PARAGEM_B, LOJA_B, 0), _paragem(PARAGEM_D, LOJA_D, 1)]
    cliente = sessao(ZE_UTILIZADOR, _base(rotas=[_rota(AMANHA, paragens)], lojas=lojas))
    pontos = [FABRICA_PADRAO, MARQUES, MARQUES, FABRICA_PADRAO]
    ors_falso.responde(_direcoes([600, None, 600], [1000.0, None, 1000.0], pontos))
    r, rota = _ok(cliente)
    assert "duration" not in ors_falso.corpos()[0]  # (só para garantir que o corpo é o pedido, não a resposta)
    assert _escritas(cliente.base) == [_escrita({
        "paragens.0.chegada_prevista": "08:10", "paragens.0.espera_min": 0,
        "paragens.1.chegada_prevista": "08:25", "paragens.1.espera_min": 0,
        "calculo": _calculo(rota, lojas, pontos, 2000, 1200, "08:50"),
    })]
    assert [(p["numero"], p["chegada_prevista"], p["espera_min"]) for p in r.json()["paragens"]] == [(1, "08:10", 0), (2, "08:25", 0)]


def test_o_mesmo_caso_pelo_simulador_local(sessao, ors_falso):
    """O simulador (T3.13) omite as medidas do troço de comprimento zero, como
    o ORS: 200, a D chega 15 min depois da B, sem espera, e a linha passa
    pelos 4 pontos."""
    lojas = _lojas(ponto_d=MARQUES)
    paragens = [_paragem(PARAGEM_B, LOJA_B, 0), _paragem(PARAGEM_D, LOJA_D, 1)]
    cliente = sessao(ZE_UTILIZADOR, _base(rotas=[_rota(AMANHA, paragens)], lojas=lojas))
    ors_falso.pelo_simulador()
    r, rota = _ok(cliente)
    troco = ors_falso.respostas[0]["routes"][0]["segments"][1]
    assert "distance" not in troco and "duration" not in troco
    b, d = rota["paragens"]
    assert (b["espera_min"], d["espera_min"], b["fora_de_horario"], d["fora_de_horario"]) == (0, 0, False, False)
    assert _minutos(d["chegada_prevista"]) == _minutos(b["chegada_prevista"]) + 15
    assert r.json()["calculo"]["atual"] is True
    linha = polilinha.descodificar(rota["calculo"]["geometria"])
    assert len(linha) == 4
    assert all(abs(a - b) < 1e-5 for ponto, esperado in zip(linha, [FABRICA_PADRAO, MARQUES, MARQUES, FABRICA_PADRAO]) for a, b in zip(ponto, esperado))


def test_a_resposta_do_simulador_local_le_se_de_ponta_a_ponta(sessao, ors_falso):
    """O formato do simulador (troços a 1 casa, resumo, `bbox`, `metadata`)
    passa pelo parser estrito; os totais são os do resumo, arredondados."""
    cliente = sessao()
    ors_falso.pelo_simulador()
    r, rota = _ok(cliente)
    resumo = ors_falso.respostas[0]["routes"][0]["summary"]
    assert rota["calculo"]["distancia_m"] == int(resumo["distance"] + 0.5)
    assert rota["calculo"]["duracao_s"] == int(resumo["duration"] + 0.5)
    assert rota["calculo"]["geometria"] == ors_falso.respostas[0]["routes"][0]["geometry"]
    assert r.json() == _api(rota, _lojas())
    assert r.json()["calculo"]["atual"] is True
    assert all(p["chegada_prevista"] is not None for p in r.json()["paragens"] if p["seccao"] == "rota")


def test_a_fixture_gravada_tem_o_formato_real_do_directions(sessao, ors_falso):
    """`direcoes-tres-paragens.json` (5 pontos, 4 troços) serve uma rota com 3
    incluídas (a A com "Manter"): só prova o formato; os valores exatos vêm
    das respostas escritas nos testes (decisão da T3.12)."""
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(por_paragem={PARAGEM_A: {"manter_fechada": True}}))
    gravada = _fixture("direcoes-tres-paragens.json")
    ors_falso.responde(gravada)
    r, rota = _ok(cliente)
    assert (rota["calculo"]["distancia_m"], rota["calculo"]["duracao_s"]) == (20866, 2455)
    assert rota["calculo"]["geometria"] == gravada["routes"][0]["geometry"]
    assert rota["calculo"]["calculado_em"] == AGORA_INSTANTE
    assert r.json() == _api(rota, _lojas())
    assert r.json()["calculo"]["atual"] is True
    assert [p["numero"] for p in r.json()["paragens"]] == [1, 2, 3]
    assert all(p["chegada_prevista"] is not None for p in r.json()["paragens"])


# --- Sem paragens incluídas: não se chama o openrouteservice ---------------------------------------


@pytest.mark.parametrize(
    "paragens",
    [
        [_paragem(PARAGEM_A, LOJA_A, 0)],
        [_paragem(PARAGEM_B, LOJA_B, 0, nao_cabe=True), _paragem(PARAGEM_A, LOJA_A, 1)],
        [_retirada(PARAGEM_B, LOJA_B), _retirada(PARAGEM_C, LOJA_C)],
        [],
    ],
    ids=["só a fechada", "nao_cabe e fechada", "todas retiradas", "sem paragens"],
)
def test_sem_incluidas_limpa_o_calculo_que_havia_sem_chamar_o_ors(sessao, paragens):
    """Nenhuma paragem na secção "rota": sem pedido (a guarda do conftest
    falharia), uma só escrita com `calculo: None`, a versão igual."""
    base = _base(rotas=[_rota(AMANHA, paragens, calculo=deepcopy(CALCULO_VELHO))], lojas=_lojas())
    cliente = sessao(ZE_UTILIZADOR, base)
    r, rota = _ok(cliente)
    assert _escritas(base) == [_escrita({"calculo": None})]
    assert (rota["versao"], rota["calculo"]) == (3, None)
    assert r.json() == _api(rota, _lojas(), calculo_disponivel=False)
    assert r.json()["calculo"] is None


def test_sem_incluidas_e_sem_calculo_nao_escreve(sessao):
    base = _base(rotas=[_rota(AMANHA, [_paragem(PARAGEM_A, LOJA_A, 0)])], lojas=_lojas())
    cliente = sessao(ZE_UTILIZADOR, base)
    antes = _gravadas(base)
    r = _recalcular(cliente)
    assert r.status_code == 200, r.text
    _nada_muda(cliente, antes)
    assert r.json() == _api(antes[0], _lojas(), calculo_disponivel=False)


def test_sem_incluidas_tambem_sem_chave_da_200(sessao):
    """O 503 `sem_chave` é só de quem precisa do Directions."""
    base = _base(rotas=[_rota(AMANHA, [_paragem(PARAGEM_A, LOJA_A, 0)], calculo=deepcopy(CALCULO_VELHO))], lojas=_lojas())
    cliente = sessao(ZE_UTILIZADOR, base)
    assert _recalcular(cliente).status_code == 200
    assert _gravadas(base)[0]["calculo"] is None


# --- As falhas do openrouteservice: 503 e nada muda ------------------------------------------------


def test_sem_chave_da_503_sem_pedido_nenhum(sessao, ors_falso, monkeypatch):
    monkeypatch.delenv(ors.VARIAVEL_CHAVE)
    cliente = sessao()
    antes = _gravadas(cliente.base)
    r = _recalcular(cliente)
    assert (r.status_code, r.json()) == (503, _indisponivel("sem_chave"))
    assert ors_falso.pedidos == []
    _nada_muda(cliente, antes)


def test_o_429_e_o_limite(sessao, ors_falso):
    cliente = sessao()
    antes = _gravadas(cliente.base)
    ors_falso.responde(_fixture("erro-429.json"), estado=429)
    r = _recalcular(cliente)
    assert (r.status_code, r.json()) == (503, _indisponivel("limite", LIMITE))
    assert len(ors_falso.pedidos) == 1
    _nada_muda(cliente, antes)


@pytest.mark.parametrize(
    "indice, mensagem",
    [(0, INICIO_SEM_ESTRADA), (1, _paragem_sem_estrada(1)), (2, _paragem_sem_estrada(2)), (3, FIM_SEM_ESTRADA)],
    ids=["início", "paragem 1", "paragem 2", "fim"],
)
def test_o_2010_diz_que_ponto_nao_tem_estrada(sessao, ors_falso, indice, mensagem):
    """O ORS conta as coordenadas a partir de 0: 0 é o início, o último é o
    fim e os do meio são o número da paragem na secção "rota"."""
    cliente = sessao()
    antes = _gravadas(cliente.base)
    ors_falso.responde(*reversed(_erro_2010(indice)))
    r = _recalcular(cliente)
    assert (r.status_code, r.json()) == (503, _indisponivel("ponto_sem_estrada", mensagem))
    _nada_muda(cliente, antes)


def test_a_fixture_do_2010_aponta_para_a_paragem_2(sessao, ors_falso):
    cliente = sessao()
    ors_falso.responde(_fixture("direcoes-erro-2010.json"), estado=404)
    r = _recalcular(cliente)
    assert (r.status_code, r.json()) == (503, _indisponivel("ponto_sem_estrada", _paragem_sem_estrada(2)))


def test_o_2010_com_a_paragem_fechada_mantida_conta_pela_seccao_rota(sessao, ors_falso):
    """Com a A mantida (ordem 2) há 5 pontos: o índice 3 é a paragem 3 (a A)
    e o 4 é o fim."""
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(por_paragem={PARAGEM_A: {"manter_fechada": True}}))
    ors_falso.responde(*reversed(_erro_2010(3)))
    assert _recalcular(cliente).json() == _indisponivel("ponto_sem_estrada", _paragem_sem_estrada(3))
    ors_falso.responde(*reversed(_erro_2010(4)))
    assert _recalcular(cliente).json() == _indisponivel("ponto_sem_estrada", FIM_SEM_ESTRADA)


def test_um_2010_com_um_indice_fora_dos_pontos_e_indisponivel(sessao, ors_falso):
    cliente = sessao()
    ors_falso.responde(*reversed(_erro_2010(9)))
    r = _recalcular(cliente)
    assert (r.status_code, r.json()) == (503, _indisponivel("indisponivel"))


@pytest.mark.parametrize(
    "estado, dados",
    [
        (500, {"error": "x"}),
        (401, {"error": {"code": 2001, "message": "Authorization field missing"}}),
        (403, {"error": "Quota exceeded"}),
        (200, []),
        (200, {}),
        (200, {"routes": []}),
        (200, {"routes": [{"summary": {"distance": 1.0, "duration": 2.0}}]}),
        (200, _direcoes([600, 900], [1.0, 2.0], PONTOS[:3])),  # um troço a menos
        (200, {"routes": [{"segments": [{}, {}, {}], "geometry": "???"}]}),
        (200, {"routes": [{"segments": [{"duration": -1}, {}, {}], "geometry": polilinha.codificar(PONTOS)}]}),
    ],
    ids=["500", "401", "403", "lista", "vazio", "sem rota", "sem troços", "troço a menos", "linha estragada", "duração negativa"],
)
def test_uma_resposta_que_nao_serve_e_indisponivel(sessao, ors_falso, estado, dados):
    cliente = sessao()
    antes = _gravadas(cliente.base)
    ors_falso.responde(dados, estado=estado)
    r = _recalcular(cliente)
    assert (r.status_code, r.json()) == (503, _indisponivel("indisponivel"))
    assert len(ors_falso.pedidos) == 1
    _nada_muda(cliente, antes)


def test_um_corpo_que_nao_e_json_e_indisponivel(sessao, ors_falso):
    cliente = sessao()
    ors_falso.responde(conteudo=b"<html>erro</html>")
    r = _recalcular(cliente)
    assert (r.status_code, r.json()) == (503, _indisponivel("indisponivel"))


def test_a_rede_a_falhar_e_indisponivel(sessao, ors_falso):
    cliente = sessao()
    antes = _gravadas(cliente.base)
    ors_falso.falha(lambda pedido: httpx.ConnectError(f"ligação recusada {CHAVE}", request=pedido))
    r = _recalcular(cliente)
    assert (r.status_code, r.json()) == (503, _indisponivel("indisponivel"))
    _nada_muda(cliente, antes)


@pytest.mark.parametrize(
    "preparar, motivo",
    [
        (lambda falso: falso.responde(_fixture("erro-429.json"), estado=429), "estado HTTP 429"),
        (lambda falso: falso.responde(*reversed(_erro_2010(2))), "estado HTTP 404 (código 2010)"),
        (lambda falso: falso.responde({"error": "x"}, estado=500), "estado HTTP 500"),
        (lambda falso: falso.responde({"routes": []}), "o Directions não trouxe a rota"),
        (lambda falso: falso.falha(lambda p: httpx.ReadTimeout("lento", request=p)), "sem resposta (ReadTimeout)"),
    ],
    ids=["429", "2010", "500", "forma errada", "rede"],
)
def test_a_falha_fica_no_registo_sem_coordenadas_nem_a_chave(sessao, ors_falso, caplog, preparar, motivo):
    cliente = sessao()
    preparar(ors_falso)
    with caplog.at_level(logging.DEBUG), caplog.at_level(logging.DEBUG, logger="httpx"), caplog.at_level(
        logging.DEBUG, logger="httpcore"
    ):
        assert _recalcular(cliente).status_code == 503
    avisos = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert [(r.name, r.getMessage()) for r in avisos] == [
        ("crm.rotas", f"[crm] rota {AMANHA}: o openrouteservice falhou (recalcular) — {motivo}"),
    ]
    for segredo in (CHAVE, "Pastelaria", LOJA_B, *COORDENADAS_CANARIAS):
        assert segredo not in caplog.text
        for registo in caplog.records:
            assert segredo not in str(registo.args)


def test_sem_chave_tambem_fica_no_registo(sessao, ors_falso, monkeypatch, caplog):
    monkeypatch.delenv(ors.VARIAVEL_CHAVE)
    cliente = sessao()
    with caplog.at_level(logging.DEBUG):
        assert _recalcular(cliente).status_code == 503
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == [
        f"[crm] rota {AMANHA}: o openrouteservice falhou (recalcular) — sem chave",
    ]


def test_um_sucesso_nao_deixa_avisos_nem_segredos_no_registo(sessao, ors_falso, caplog):
    cliente = sessao()
    with caplog.at_level(logging.DEBUG), caplog.at_level(logging.DEBUG, logger="httpx"), caplog.at_level(
        logging.DEBUG, logger="httpcore"
    ):
        _ok(cliente)
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    for segredo in (CHAVE, *COORDENADAS_CANARIAS):
        assert segredo not in caplog.text


# --- Recusas, pela ordem do plano ----------------------------------------------------------------


@pytest.mark.parametrize(
    "corpo, campos",
    [
        ({}, {"versao": VERSAO_OBRIGATORIA}),
        ({"versao": None}, {"versao": VERSAO_OBRIGATORIA}),
        ({"versao": 0}, {"versao": VERSAO_OBRIGATORIA}),
        ({"versao": -1}, {"versao": VERSAO_OBRIGATORIA}),
        ({"versao": "3"}, {"versao": VERSAO_OBRIGATORIA}),
        ({"versao": 3.0}, {"versao": VERSAO_OBRIGATORIA}),
        ({"versao": True}, {"versao": VERSAO_OBRIGATORIA}),
        ({"versao": [3]}, {"versao": VERSAO_OBRIGATORIA}),
    ],
    ids=["sem versão", "null", "0", "-1", "texto", "decimal", "bool", "lista"],
)
def test_um_corpo_sem_a_versao_da_422_sem_tocar_na_base(sessao, ors_falso, corpo, campos):
    cliente = sessao()
    r = cliente.post(_url(), json=corpo)
    assert (r.status_code, r.json()) == (422, _validacao(campos))
    assert cliente.base.crm_rotas.registo == [] and cliente.base.crm_lojas.registo == []
    assert ors_falso.pedidos == []


def test_as_outras_chaves_do_corpo_ignoram_se(sessao, ors_falso):
    r = _recalcular(sessao(), ordem="x", hora_saida=5, paragens=[])
    assert r.status_code == 200, r.text


@pytest.mark.parametrize(
    "data, mensagem",
    [("abc", DATA), ("2026-1-1", DATA), ("2026-13-01", DATA), ("2028-01-01", HORIZONTE), ("2027-10-14", HORIZONTE)],
    ids=["abc", "sem zeros", "mês 13", "2028", "hoje + 366"],
)
def test_uma_data_errada_da_422_sem_tocar_na_base(sessao, ors_falso, data, mensagem):
    cliente = sessao()
    r = _recalcular(cliente, data=data)
    assert (r.status_code, r.json()) == (422, _validacao({"data": mensagem}))
    assert cliente.base.crm_rotas.registo == []
    assert ors_falso.pedidos == []


def test_os_erros_da_data_e_do_corpo_vem_juntos_com_a_data_primeiro(sessao):
    r = sessao().post(_url("abc"), json={})
    assert (r.status_code, r.json()) == (422, _validacao({"data": DATA, "versao": VERSAO_OBRIGATORIA}))
    assert list(r.json()["detail"]["campos"]) == ["data", "versao"]


@pytest.mark.parametrize("corpo", [b"[", b"[1]", b"null", b'"x"', b'{"versao": NaN}'], ids=["[", "lista", "null", "texto", "NaN"])
def test_um_corpo_que_nao_e_um_objeto_json_da_400(sessao, corpo):
    cliente = sessao()
    r = cliente.post(_url(), content=corpo, headers=JSON)
    assert (r.status_code, r.json()) == (400, JSON_INVALIDO)
    assert cliente.base.crm_rotas.registo == []


@pytest.mark.parametrize("data", [AMANHA, HOJE, ONTEM], ids=["amanhã", "hoje", "ontem (antes do rota_fechada)"])
def test_um_dia_sem_rota_da_404_sem_ler_mais_nada(sessao, ors_falso, data):
    cliente = sessao(ZE_UTILIZADOR, _base(lojas=_lojas()))
    r = _recalcular(cliente, data=data, versao=1)
    assert (r.status_code, r.json()) == (404, SEM_ROTA)
    assert cliente.base.crm_rotas.registo == [("find_one", {"data": data}, SEM_ID)]
    assert cliente.base.crm_lojas.registo == [] and cliente.base.crm_definicoes.registo == []
    assert ors_falso.pedidos == []


def test_ontem_com_rota_da_rota_fechada_sem_escrever(sessao, ors_falso):
    base = _base(rotas=[_rota(ONTEM, _tres_paragens())], lojas=_lojas())
    cliente = sessao(ZE_UTILIZADOR, base)
    antes = _gravadas(base)
    r = _recalcular(cliente, data=ONTEM)
    assert (r.status_code, r.json()) == (409, ROTA_FECHADA)
    _nada_muda(cliente, antes)
    assert ors_falso.pedidos == []


@pytest.mark.parametrize(
    "paragens, estado",
    [
        ([_paragem(PARAGEM_B, LOJA_B, 0), _feita(PARAGEM_C, LOJA_C, 1)], "rascunho"),
        ([_retirada(PARAGEM_B, LOJA_B, estado="nao_feita", resultado="fechada")], "planeada"),
        ([_paragem(PARAGEM_B, LOJA_B, 0)], "em_curso"),
        ([_paragem(PARAGEM_B, LOJA_B, 0)], "concluida"),
    ],
    ids=["uma feita", "uma retirada nao_feita", "em_curso", "concluida"],
)
def test_uma_rota_com_registo_do_motorista_da_rota_em_curso_sem_escrever(sessao, ors_falso, paragens, estado):
    base = _base(rotas=[_rota(AMANHA, paragens, estado=estado)], lojas=_lojas())
    cliente = sessao(ZE_UTILIZADOR, base)
    antes = _gravadas(base)
    r = _recalcular(cliente)
    assert (r.status_code, r.json()) == (409, ROTA_EM_CURSO)
    _nada_muda(cliente, antes)
    assert ors_falso.pedidos == []


def test_rota_em_curso_ganha_ao_conflito(sessao):
    base = _base(rotas=[_rota(AMANHA, [_feita(PARAGEM_B, LOJA_B, 0)])], lojas=_lojas())
    r = _recalcular(sessao(ZE_UTILIZADOR, base), versao=99)
    assert (r.status_code, r.json()) == (409, ROTA_EM_CURSO)


@pytest.mark.parametrize("versao", [1, 2, 4, 99], ids=["1", "2", "4", "99"])
def test_uma_versao_diferente_da_conflito_sem_ler_mais_nada(sessao, ors_falso, versao):
    cliente = sessao()
    antes = _gravadas(cliente.base)
    r = _recalcular(cliente, versao=versao)
    assert (r.status_code, r.json()) == (409, CONFLITO)
    assert [c[0] for c in cliente.base.crm_rotas.registo] == ["find_one"]
    assert cliente.base.crm_lojas.registo == [] and cliente.base.crm_definicoes.registo == []
    assert ors_falso.pedidos == []
    _nada_muda(cliente, antes)


# --- A escrita que não casa: `porque_falhou`, sem tentar outra vez ----------------------------------


def test_outra_pessoa_a_gravar_entre_a_leitura_e_a_escrita_da_conflito(sessao, ors_falso):
    """O Directions respondeu, mas a versão subiu entretanto: 409 `conflito`,
    um só pedido ao ORS, uma só tentativa, nada do escritório fica escrito."""
    base = _base_com_tres()

    def outra_pessoa(docs):
        docs[0]["versao"] += 1

    base.crm_rotas.antes_de("find_one_and_update", outra_pessoa)
    cliente = sessao(ZE_UTILIZADOR, base)
    r = _recalcular(cliente)
    assert (r.status_code, r.json()) == (409, CONFLITO)
    assert [c[0] for c in base.crm_rotas.registo] == ["find_one", "find_one_and_update", "find_one"]
    assert base.crm_rotas.registo[2][1:] == ({"id": "r-1"}, SEM_CALCULO)  # o porque_falhou
    assert len(ors_falso.pedidos) == 1
    assert _gravadas(base) == [_rota(AMANHA, _tres_paragens(), versao=4)]


def test_o_motorista_a_registar_entre_a_leitura_e_a_escrita_da_rota_em_curso(sessao, ors_falso):
    base = _base_com_tres()

    def motorista(docs):
        docs[0]["paragens"][1]["estado"] = "feita"

    base.crm_rotas.antes_de("find_one_and_update", motorista)
    cliente = sessao(ZE_UTILIZADOR, base)
    r = _recalcular(cliente)
    assert (r.status_code, r.json()) == (409, ROTA_EM_CURSO)
    assert [c[0] for c in base.crm_rotas.registo] == ["find_one", "find_one_and_update", "find_one"]
    esperada = _rota(AMANHA, _tres_paragens())
    esperada["paragens"][1]["estado"] = "feita"
    assert _gravadas(base) == [esperada]


def test_a_rota_apagada_entre_a_leitura_e_a_escrita_da_404(sessao, ors_falso):
    base = _base_com_tres()

    def apagada(docs):
        docs.clear()

    base.crm_rotas.antes_de("find_one_and_update", apagada)
    cliente = sessao(ZE_UTILIZADOR, base)
    r = _recalcular(cliente)
    assert (r.status_code, r.json()) == (404, SEM_ROTA)
    assert [c[0] for c in base.crm_rotas.registo] == ["find_one", "find_one_and_update", "find_one"]
    assert _gravadas(base) == []


# --- O que se lê, o relógio e os verificadores ---------------------------------------------------


def test_le_a_rota_pelo_dia_depois_as_lojas_das_ativas_e_as_definicoes_e_escreve_uma_vez(sessao, ors_falso):
    cliente = sessao()
    _ok(cliente)
    assert [c[0] for c in cliente.base.crm_rotas.registo] == ["find_one", "find_one_and_update"]
    assert cliente.base.crm_rotas.registo[0][1:] == ({"data": AMANHA}, SEM_ID)
    assert cliente.base.crm_lojas.registo == [("find", {"id": {"$in": [LOJA_B, LOJA_C, LOJA_A]}}, PROJECAO_LOJA_ROTA)]
    assert cliente.base.crm_definicoes.registo == [("find", {}, PROJECAO_DEFINICOES)]


def test_o_relogio_le_se_uma_vez_por_pedido(sessao, ors_falso, monkeypatch):
    """Um só instante por pedido: o "hoje" da validação, o `calculado_em` e o
    `hoje` da resposta são do mesmo `relogio.agora()`."""
    cliente = sessao()
    leituras = []

    def _agora():
        leituras.append(1)
        return AGORA

    monkeypatch.setattr(relogio, "agora", _agora)
    r, rota = _ok(cliente)
    assert len(leituras) == 1
    assert (rota["calculo"]["calculado_em"], r.json()["hoje"]) == (AGORA_INSTANTE, HOJE)


def test_todas_as_escritas_passam_no_terreno_e_nos_instantes(sessao, ors_falso):
    """Uma sequência real (recalcular, retirar a C pelo PATCH, recalcular
    outra vez só com a B): cada `find_one_and_update` passa em
    `escritas_no_terreno` e em `instantes_fora_do_formato`; as do recalcular
    só têm `$set` (nunca `$inc`, `$push` nem `$unset`) e os caminhos são só
    dos campos do escritório."""
    cliente = sessao()
    _ok(cliente)
    assert cliente.patch(ROTAS_URL + f"/{AMANHA}", json={"versao": 3, "retirar": [PARAGEM_C]}).status_code == 200
    pontos = [FABRICA_PADRAO, MARQUES, FABRICA_PADRAO]
    ors_falso.responde(_direcoes([600, 1200], [1000.0, 2000.0], pontos))
    r, rota = _ok(cliente, versao=4)
    escritas = _escritas(cliente.base)
    assert [e[0] for e in escritas] == ["find_one_and_update"] * 3
    for escrita in escritas:
        assert escritas_no_terreno(escrita[2]) == []
        assert instantes_fora_do_formato(escrita[2]) == []
    for escrita in (escritas[0], escritas[2]):
        assert set(escrita[2]) == {"$set"}
        caminhos = [caminho for caminho in escrita[2]["$set"] if caminho.startswith("paragens.")]
        assert all(caminho.split(".")[2] in dominio_rotas.CAMPOS_DO_ESCRITORIO for caminho in caminhos)
        assert all(len(caminho.split(".")) == 3 and caminho.split(".")[1].isdigit() for caminho in caminhos)
    assert escritas[0] == _escrita({**HORAS_PADRAO, "calculo": _calculo(_rota(AMANHA, _tres_paragens()), _lojas(), PONTOS, 6001, 2700, "09:35")})
    # A B chega à mesma hora: só o `calculo` muda; a C retirada não se toca.
    assert escritas[2] == _escrita({"calculo": _calculo(rota, _lojas(), pontos, 3000, 1800, "08:45")}, versao=4)
    assert instantes_fora_do_formato(_gravadas(cliente.base)) == []
    assert (rota["versao"], r.json()["calculo"]["atual"], [p["numero"] for p in r.json()["paragens"]]) == (4, True, [1, None])
    assert all((p["estado"], p["resultado"], p["concluida_em"]) == ("pendente", None, None) for p in rota["paragens"])


def test_a_resposta_nao_leva_dados_pessoais_nem_a_assinatura(sessao, ors_falso):
    r, _ = _ok(sessao())
    for pessoal in ("Rua Secreta", "não sai na rota", "Sr. Silva", "assinatura", '"_id"'):
        assert pessoal not in r.text


def test_depois_do_recalcular_um_patch_torna_as_horas_velhas(sessao, ors_falso):
    """`calculo.atual` segue a assinatura: mudar a saída pelo PATCH deixa as
    horas gravadas com `atual: false` (e a versão sobe por ele, não pelo
    recalcular)."""
    cliente = sessao()
    _ok(cliente)
    r = cliente.patch(ROTAS_URL + f"/{AMANHA}", json={"versao": 3, "hora_saida": "07:00"})
    assert (r.status_code, r.json()["versao"], r.json()["calculo"]["atual"]) == (200, 4, False)
    r, rota = _ok(cliente, versao=4)
    assert (r.json()["versao"], r.json()["calculo"]["atual"], rota["paragens"][1]["chegada_prevista"]) == (4, True, "07:10")


# --- Quem entra -----------------------------------------------------------------------------------


def test_o_escritorio_recalcula(sessao, ors_falso):
    for pessoa in (ADMIN_MASTER, ANA_ADMIN_DO_CRM, ZE_UTILIZADOR):
        cliente = sessao(pessoa)
        r, rota = _ok(cliente)
        assert (r.json()["calculo"]["atual"], rota["atualizado_por"]) == (True, MEMBRO)


def test_o_motorista_recebe_403_sem_permissao(sessao, ors_falso):
    cliente = sessao(ALVARO_MOTORISTA)
    r = _recalcular(cliente)
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)
    assert cliente.base.crm_rotas.registo == [] and ors_falso.pedidos == []


def test_quem_nao_e_membro_recebe_403_sem_acesso_crm(sessao, ors_falso):
    cliente = sessao(BEA_NAO_MEMBRO)
    r = _recalcular(cliente)
    assert (r.status_code, r.json()) == (403, SEM_ACESSO)
    assert cliente.base.crm_rotas.registo == [] and ors_falso.pedidos == []


@pytest.mark.parametrize(
    "utilizador, esperado", [(ALVARO_MOTORISTA, SEM_PERMISSAO), (BEA_NAO_MEMBRO, SEM_ACESSO)], ids=["motorista", "não membro"]
)
def test_sem_perfil_e_com_json_partido_da_403_e_nunca_400(sessao, utilizador, esperado):
    cliente = sessao(utilizador)
    r = cliente.post(_url(), content=b"[", headers=JSON)
    assert (r.status_code, r.json()) == (403, esperado)
    assert cliente.base.crm_rotas.registo == []


# --- De ponta a ponta com a sessão verdadeira do portal --------------------------------------------

SEGREDO = "segredo-de-teste-crm-rotas-recalcular"
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
    base = _base_com_tres()
    monkeypatch.setattr(faturacao.auth, "obter_db", lambda: base)
    monkeypatch.setattr(crm.db, "obter_db", lambda: base)
    app = FastAPI()
    app.include_router(crm.router)
    cliente = TestClient(app)
    cliente.base = base
    return cliente


def test_sem_sessao_da_o_403_herdado(portal):
    r = portal.post(_url(), json={"versao": 3})
    assert (r.status_code, r.json()) == (403, {"detail": "Not authenticated"})
    assert portal.base.crm_rotas.registo == []


def test_sem_cabecalho_e_com_json_partido_da_o_403_herdado_e_nunca_400(portal):
    r = portal.post(_url(), content=b"[", headers=JSON)
    assert (r.status_code, r.json()) == (403, {"detail": "Not authenticated"})
    assert portal.base.users.registo == []
    assert portal.base.crm_rotas.registo == []


def test_uma_conta_apagada_da_401_sessao_terminada(portal):
    r = portal.post(_url(), json={"versao": 3}, headers=_cabecalho("u-apagada"))
    assert (r.status_code, r.json()) == (401, {"detail": "Sessão terminada"})
    assert portal.base.crm_rotas.registo == []


def test_de_ponta_a_ponta_o_escritorio_recalcula_e_o_dia_mostra_as_horas(portal, ors_falso):
    ze = _cabecalho(ZE, email="ze@example.com")
    admin = _cabecalho("u-admin", email=ADMIN_LOCAL, role="admin")

    r = portal.post(_url(), json={"versao": 3}, headers=_cabecalho("u-alv", email="alvaro@example.com"))
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)
    r = portal.post(_url(), json={"versao": 3}, headers=_cabecalho("u-bea", email="bea@example.com"))
    assert (r.status_code, r.json()) == (403, SEM_ACESSO)
    assert portal.base.crm_rotas.registo == [] and ors_falso.pedidos == []

    r = portal.post(_url(), json={"versao": 3}, headers=ze)
    assert r.status_code == 200, r.text
    assert (r.json()["versao"], r.json()["calculo"]["atual"], r.json()["calculo"]["regresso_previsto"]) == (3, True, "09:35")
    assert [p["chegada_prevista"] for p in r.json()["paragens"]] == ["08:10", "08:40", None]
    assert portal.get(ROTAS_URL + f"/{AMANHA}", headers=admin).json() == r.json()

    # A versão não mudou: um PATCH com a versão 3 ainda casa, e sobe-a.
    r = portal.patch(ROTAS_URL + f"/{AMANHA}", json={"versao": 3, "estado": "planeada"}, headers=admin)
    assert (r.status_code, r.json()["versao"], r.json()["calculo"]["atual"]) == (200, 4, True)
    r = portal.post(_url(), json={"versao": 3}, headers=admin)
    assert (r.status_code, r.json()) == (409, CONFLITO)
    r = portal.post(_url(ONTEM), json={"versao": 1}, headers=admin)
    assert (r.status_code, r.json()) == (404, SEM_ROTA)
    assert len(ors_falso.pedidos) == 1
    assert all(escritas_no_terreno(e[2]) == [] for e in _escritas(portal.base))


def _minutos(texto):
    horas, minutos = texto.split(":")
    return int(horas) * 60 + int(minutos)
