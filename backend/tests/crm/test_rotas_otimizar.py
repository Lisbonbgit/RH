"""`POST /api/crm/rotas/{data}/otimizar` — a melhor ordem pelo VROOM do
openrouteservice e, logo a seguir, as horas pelo Directions (plano F3 §1
"Melhor ordem", "Pedido VROOM", "Não cabem" e §4; T3.22).

As regras estão provadas em baixo: o pedido ao VROOM e a leitura da resposta
(`dominio.vroom`, T3.6), o Directions (`dominio.directions`, T3.7), as horas
(`dominio.horarios`, T3.8), o cliente (`servicos.ors`, T3.11), a forma da
resposta (`formatar_rota`, T3.16) e a escrita condicional (`rotas_bd`,
T3.17). Aqui prova-se a rota HTTP: quem entra, a ordem das verificações, os
dois pedidos que saem (só coordenadas e números), o que lê e o que escreve
(o filtro e a atualização exatos no registo do duplo), as falhas (tudo ou
nada) e a resposta.

- **Ao VROOM** vão todas as paragens ativas com loja, incluindo as que têm
  `nao_cabe: true` de um cálculo anterior; ficam de fora só as fechadas nesse
  dia sem "Manter" e as `sem_loja` (correções "T3.22" e "T3.22 / §1"). As
  impossíveis (nenhuma janela leva o serviço) não se enviam. Um *job* por
  paragem (`id` 1..n, `[lng, lat]`, serviço em segundos, prioridade 100 na
  entrega e 1 nas outras, janelas `[a, b − s]`); nunca nomes, telefones,
  moradas, notas nem uuids (§0, regra 12). Sem nenhum *job* não se chama o
  openrouteservice.
- **Depois, o Directions** pela ordem devolvida, só com as atribuídas; sem
  nenhuma atribuída (`routes: []`, ou nenhum *job*) não se chama e o
  `calculo` fica `None` (correção "T3.6 / T3.22").
- **A escrita:** uma só `find_one_and_update` com `$set` + `$inc` da versão
  (`rotas_bd.alterar`): a `ordem` (a do VROOM, as não atribuídas, as
  impossíveis, as fechadas, as `sem_loja`), os sinais `nao_cabe` de todas as
  enviadas, as horas nas atribuídas (nenhumas nas outras) e o `calculo`; só o
  que muda, e sem nada a mudar 200 sem escrever.
- **Falhas (nada muda):** o VROOM falha → 503 sem Directions; o VROOM
  responde bem e o Directions falha → 503, atómico; uma resposta do VROOM sem
  a forma esperada → 503. Um 2010 do Directions aponta para o `numero` ATUAL
  da paragem na rota gravada (a ordem nova ainda não está gravada; correção
  "T3.22"), ou para a mensagem geral se ela não tiver número.
- Recusas pela ordem do plano §4 (como no recalcular); o relógio lê-se uma
  vez; só o escritório; a guarda antes do corpo.

As respostas são construídas no próprio teste (`_otimizacao`, `_direcoes`,
`polilinha.codificar` e o simulador local para o formato); as fixtures
gravadas (`otimizacao-todas.json`, `otimizacao-uma-nao-cabe.json`) só provam
o formato real (decisão da T3.12). O cenário da prioridade (1 entrega + 11
visitas) é o risco R3, a confirmar com a gravação do dono.

Molde do test_rotas_recalcular.py (T3.21).
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
from crm.dominio.horas import segundos
from crm.dominio.vroom import paragem_calculo, pedido_otimizacao
from crm.formatar_rota import PROJECAO_LOJA_ROTA, rota_api
from crm.pedidos import corpo_json
from crm.servicos import ors
from faturacao.auth import utilizador_atual

from .duplos import BaseFalsa
from .formatos import escritas_no_terreno, instantes_fora_do_formato

ROTAS_URL = "/api/crm/rotas"
CAMINHO = ROTAS_URL + "/{data}/otimizar"
ADMIN_LOCAL = "admin.local@example.com"
JSON = {"Content-Type": "application/json"}
FIXTURES = Path(__file__).parent / "fixtures" / "ors"

UTC = timezone.utc
# 23:30Z de 12 de outubro de 2026: em Lisboa (WEST, UTC+1) já é dia 13.
AGORA = datetime(2026, 10, 12, 23, 30, 15, 987654, tzinfo=UTC)
AGORA_INSTANTE = "2026-10-12T23:30:15Z"
AGORA_CARIMBO = "2026-10-12T23:30:15.987654Z"
HOJE = "2026-10-13"  # uma terça-feira
ONTEM = "2026-10-12"
AMANHA = "2026-10-14"  # uma quarta-feira

MEMBRO = "membro-1"
ZE = "u-ze"
LOJA_A = "00000000-0000-4000-8000-00000000000a"
LOJA_B = "00000000-0000-4000-8000-00000000000b"
LOJA_C = "00000000-0000-4000-8000-00000000000c"
LOJA_D = "00000000-0000-4000-8000-00000000000d"
LOJA_E = "00000000-0000-4000-8000-00000000000e"  # apagada: não está na base

PARAGEM_A = "10000000-0000-4000-8000-00000000000a"
PARAGEM_B = "10000000-0000-4000-8000-00000000000b"
PARAGEM_C = "10000000-0000-4000-8000-00000000000c"
PARAGEM_D = "10000000-0000-4000-8000-00000000000d"  # retirada
PARAGEM_E = "10000000-0000-4000-8000-00000000000e"  # sem loja
# O índice de cada paragem na lista gravada (`_tres_paragens`).
INDICE = {PARAGEM_A: 0, PARAGEM_B: 1, PARAGEM_D: 2, PARAGEM_C: 3}

COMERCIO = (38.7075, -9.1364)
MARQUES = (38.7253, -9.15)
BELEM = (38.6979, -9.2065)
FABRICA_PADRAO = (38.7223, -9.1393)
OUTRA_FABRICA = (38.75, -9.2)
OUTRO_PONTO = {"lat": 38.6, "lng": -9.1}

# O openrouteservice falso: a chave canária e o URL de teste.
CHAVE = "ors-CANARIA-chave-do-otimizar-5b3ce3597851110001cf6248"
BASE = "https://ors.teste"
URL_VROOM = BASE + "/optimization"
URL_DIRECOES = BASE + "/v2/directions/driving-car/json"
CAMINHO_VROOM = "/optimization"
CAMINHO_DIRECOES = "/v2/directions/driving-car/json"

# A rota por omissão: B (Marquês, ordem 0) e C (Belém, ordem 1, recebe das
# 09:00 às 12:00) vão ao VROOM (jobs 1 e 2); a A (Comércio) está fechada à
# quarta. O VROOM falso responde C → B (`_otimizacao([2, 1])`) e o Directions
# `[fábrica, C, B, fábrica]`.
PONTOS = [FABRICA_PADRAO, BELEM, MARQUES, FABRICA_PADRAO]
DURACOES = [1200, 900, 600]
DISTANCIAS = [3000.0, 2000.25, 1000.5]  # soma 6000,75 → 6001
# Saída 08:00 → C às 08:20, espera até às 09:00 (serviço 15) → B às 09:30
# (serviço 15) → regresso às 09:55.
ORDEM_PADRAO = {"paragens.3.ordem": 0, "paragens.1.ordem": 1}
HORAS_PADRAO = {"paragens.3.chegada_prevista": "08:20", "paragens.3.espera_min": 40,
                "paragens.1.chegada_prevista": "09:30", "paragens.1.espera_min": 0}
PEDIDO_VROOM_PADRAO = {
    "jobs": [
        {"id": 1, "location": [-9.15, 38.7253], "service": 900, "priority": 1},
        {"id": 2, "location": [-9.2065, 38.6979], "service": 900, "priority": 1, "time_windows": [[32400, 42300]]},
    ],
    "vehicles": [{
        "id": 1, "profile": "driving-car", "start": [-9.1393, 38.7223], "end": [-9.1393, 38.7223],
        "time_window": [28800, 68400],
    }],
}
COORDENADAS_CANARIAS = ("38.7253", "9.15", "38.6979", "9.2065", "38.7223", "9.1393")
CANARIOS = ("Pastelaria", "Mercearia", "Café", "+351", "Rua Secreta", "não sai", "Sr. Silva",
            LOJA_A, LOJA_B, LOJA_C, PARAGEM_A, PARAGEM_B, PARAGEM_C, "r-1", AMANHA, "cliente", "potencial",
            "contactada", "angariacao", "amostra", MEMBRO, ZE)

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
HORAS_VELHAS = {"chegada_prevista": "10:00", "espera_min": 5, "fora_de_horario": True}

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
    "calculo": None,
    "estado": {"$in": ["rascunho", "planeada"]},
    "paragens.estado": {"$nin": ["feita", "nao_feita"]},
}
AUTORIA = {"atualizado_em": AGORA_CARIMBO, "atualizado_por": ZE}

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
    return f"{ROTAS_URL}/{data}/otimizar"


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


def _janela(inicio, fim):
    return {"inicio": inicio, "fim": fim}


def _lojas(ponto_d=(38.71, -9.14), janelas_b=(), janelas_c=(_janela("09:00", "12:00"),)):
    # A A fecha à quarta (o dia de AMANHA); as outras abrem todos os dias.
    return [
        _loja(LOJA_A, "Café A", "contactada", COMERCIO, dias_fechada=["qua"]),
        _loja(LOJA_B, "Pastelaria B", "potencial", MARQUES, janelas=list(janelas_b)),
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


def _id_loja(n):
    return f"00000000-0000-4000-8000-{n:012d}"


def _id_paragem(n):
    return f"10000000-0000-4000-8000-{n:012d}"


def _muitas(visitas=11):
    """O cenário da prioridade: uma entrega (paragem 0, 10 min) e `visitas`
    visitas (15 min), em lojas diferentes e sem janelas. `(paragens, lojas)`."""
    paragens, lojas = [], []
    for n in range(1, visitas + 2):
        ponto = (38.70 + 0.002 * n, -9.14 - 0.002 * n)
        lojas.append(_loja(_id_loja(n), f"Loja {n}", "cliente", ponto))
        entrega = n == 1
        paragens.append(_paragem(
            _id_paragem(n), _id_loja(n), n - 1, motivo="entrega" if entrega else "angariacao",
            tempo_servico_min=10 if entrega else 15,
        ))
    return paragens, lojas


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


def _guarda_do_calculo(calculo):
    """O cálculo lido no filtro de guarda (correção "F3-INT-1"): `calculo:
    None`, ou a assinatura e o `calculado_em` dele."""
    if calculo is None:
        return {"calculo": None}
    return {"calculo.assinatura": calculo["assinatura"], "calculo.calculado_em": calculo["calculado_em"]}


def _escrita(set_, versao=3, rota_id="r-1", autoria=AUTORIA, calculo=None):
    """A única `find_one_and_update` esperada: o filtro de guarda (com o
    `calculo` lido), o `$set` do que muda mais a autoria, e o `$inc` da versão
    (o otimizar muda o plano)."""
    filtro = {campo: valor for campo, valor in FILTRO_DE_ESCRITA.items() if campo != "calculo"}
    return (
        "find_one_and_update",
        {**filtro, "id": rota_id, "versao": versao, **_guarda_do_calculo(calculo)},
        {"$set": {**set_, **autoria}, "$inc": {"versao": 1}},
        SEM_ID,
        False,
        ReturnDocument.AFTER,
    )


def _autoria(n=0):
    """A autoria da n-ésima escrita seguida no mesmo instante: o
    `relogio.proximo_carimbo` soma 1 µs a cada uma."""
    return {"atualizado_em": AGORA_CARIMBO[:-3] + f"{54 + n}Z", "atualizado_por": ZE}


def _calculo(rota, lojas, pontos, distancia_m, duracao_s, regresso, depois=False, geometria=None):
    """O `calculo` que fica gravado: a assinatura da entrada de agora (a rota
    como ficou, só com a secção "rota" pela ordem nova e os extremos
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


def _pedido_vroom(ids, paragens=None, lojas=None, inicio=FABRICA_PADRAO, fim=FABRICA_PADRAO, saida="08:00", limite="19:00"):
    """O corpo que o `vroom.pedido_otimizacao` monta para as paragens `ids`
    (pela ordem dada) desta rota: a referência do pedido capturado."""
    por_paragem = {p["id"]: p for p in (paragens if paragens is not None else _tres_paragens())}
    por_loja = {loja["id"]: _projetada(loja) for loja in (lojas if lojas is not None else _lojas())}
    calculos = [paragem_calculo(por_paragem[id_], por_loja[por_paragem[id_]["loja_id"]]) for id_ in ids]
    return pedido_otimizacao(calculos, inicio, fim, segundos(saida), segundos(limite)).corpo


def _passo_vroom(tipo, local, chegada, **extra):
    return {"type": tipo, "location": list(local), "setup": 0, "service": 0, "waiting_time": 0,
            "arrival": chegada, "duration": 0, "violations": [], **extra}


def _otimizacao(ordem, nao_atribuidos=()):
    """Uma resposta do VROOM escrita aqui, no formato do ORS: `code 0`, uma
    rota do veículo 1 com os passos `start`, um `job` por número de `ordem`
    (com `id` e `job`, como as respostas reais) e `end`; os não atribuídos
    `{id, type, location}`; sem nenhum atribuído, `routes: []`."""
    fabrica = [FABRICA_PADRAO[1], FABRICA_PADRAO[0]]
    rotas_ = []
    if ordem:
        passos = [_passo_vroom("start", fabrica, 28800)]
        for numero in ordem:
            passos.append(_passo_vroom("job", [-9.1, 38.7], 30000, id=numero, job=numero, service=900))
        passos.append(_passo_vroom("end", fabrica, 36000, duration=1000))
        rotas_.append({"vehicle": 1, "cost": 1000, "setup": 0, "service": 900 * len(ordem), "duration": 1000,
                       "waiting_time": 0, "priority": len(ordem), "steps": passos, "violations": []})
    return {
        "code": 0,
        "summary": {"cost": 1000, "routes": len(rotas_), "unassigned": len(nao_atribuidos), "setup": 0,
                    "service": 900 * len(ordem), "duration": 1000, "waiting_time": 0, "priority": len(ordem),
                    "violations": [], "computing_times": {"loading": 1, "solving": 1, "routing": 0}},
        "unassigned": [{"id": numero, "type": "job", "location": [-9.1, 38.7]} for numero in nao_atribuidos],
        "routes": rotas_,
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
    guarda os pedidos recebidos (aos dois serviços, pela ordem) e responde o
    que `vroom(...)` e `direcoes(...)` fixaram — por omissão, a ordem C → B
    de `_otimizacao([2, 1])` e os troços de `_direcoes()`."""

    def __init__(self):
        self.pedidos = []
        self.respostas = []
        self.vroom()
        self.direcoes()

    def __call__(self, pedido):
        self.pedidos.append(pedido)
        if pedido.url.path == CAMINHO_VROOM:
            return self._vroom(pedido)
        if pedido.url.path == CAMINHO_DIRECOES:
            return self._direcoes(pedido)
        return httpx.Response(404, json={"error": "caminho desconhecido no falso"})

    @staticmethod
    def _fixa(omissao, dados, estado, conteudo, excecao):
        def _responder(pedido):
            if excecao is not None:
                raise excecao(pedido)
            corpo = conteudo if conteudo is not None else json.dumps(omissao() if dados is None else dados).encode("utf-8")
            return httpx.Response(estado, content=corpo)

        return _responder

    def vroom(self, dados=None, estado=200, conteudo=None, excecao=None):
        self._vroom = self._fixa(lambda: _otimizacao([2, 1]), dados, estado, conteudo, excecao)

    def direcoes(self, dados=None, estado=200, conteudo=None, excecao=None):
        self._direcoes = self._fixa(_direcoes, dados, estado, conteudo, excecao)

    def pelo_simulador(self):
        """Os dois serviços respondem como o simulador local (T3.13)."""

        def _vroom(pedido):
            resposta = ors_simulado_local.otimizar(json.loads(pedido.content))
            self.respostas.append(resposta)
            return httpx.Response(200, json=resposta)

        def _direcoes_(pedido):
            resposta = ors_simulado_local.direcoes(json.loads(pedido.content))
            self.respostas.append(resposta)
            return httpx.Response(200, json=resposta)

        self._vroom, self._direcoes = _vroom, _direcoes_

    def corpos(self):
        return [json.loads(pedido.content) for pedido in self.pedidos]

    def caminhos(self):
        return [pedido.url.path for pedido in self.pedidos]


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


def _otimizar(cliente, data=AMANHA, versao=3, **corpo):
    return cliente.post(_url(data), json={"versao": versao, **corpo})


def _ok(cliente, **corpo):
    """Um otimizar que tem de dar 200; devolve `(resposta, rota gravada)`."""
    r = _otimizar(cliente, **corpo)
    assert r.status_code == 200, r.text
    return r, _gravadas(cliente.base)[0]


def _nada_muda(cliente, antes):
    """Nada do escritório ficou escrito: nenhuma escrita no registo e a rota
    tal como estava."""
    assert _escritas(cliente.base) == []
    assert _gravadas(cliente.base) == antes


def _resumo(resposta):
    """`(id, numero, seccao, nao_cabe, chegada_prevista)` de cada paragem da resposta."""
    return [(p["id"], p["numero"], p["seccao"], p["nao_cabe"], p["chegada_prevista"]) for p in resposta.json()["paragens"]]


# --- A rota: onde está, quem a guarda e a ordem das dependências ----------------------------------


def test_a_rota_existe_e_vive_em_crm_rotas():
    rota = _rota_http()
    assert rota.methods == {"POST"}
    assert rota.endpoint.__module__ == rotas_http.__name__ == "crm.rotas"
    assert rota.status_code in (None, 200)


def test_so_o_escritorio_otimiza_e_o_corpo_le_se_depois_da_guarda():
    """Exatamente uma guarda de perfil, a do escritório, sobre
    `membro_crm_atual`; o `corpo_json` depois dela (regra T1.3/T2.15)."""
    dependencias = _dependencias(_rota_http())
    assert membro_crm_atual in dependencias
    assert [d for d in dependencias if hasattr(d, "perfis_crm")] == [ESCRITORIO]
    assert corpo_json in dependencias
    assert dependencias.index(ESCRITORIO) < dependencias.index(corpo_json)


# --- O pedido ao VROOM e, depois, o Directions pela ordem devolvida -------------------------------


def test_primeiro_o_vroom_depois_o_directions_pela_ordem_devolvida_com_a_chave_so_no_cabecalho(sessao, ors_falso):
    """Dois POST, pela ordem: `/optimization` com os jobs 1 = B e 2 = C (a
    ordem gravada; a A fechada à quarta fica de fora) e
    `/v2/directions/driving-car/json` com `[fábrica, C, B, fábrica]` (a ordem
    do VROOM, não a gravada). A chave só no `Authorization`."""
    cliente = sessao()
    _ok(cliente)
    assert [(p.method, str(p.url)) for p in ors_falso.pedidos] == [("POST", URL_VROOM), ("POST", URL_DIRECOES)]
    for pedido in ors_falso.pedidos:
        assert pedido.headers["Authorization"] == CHAVE
        assert CHAVE not in str(pedido.url) and CHAVE.encode() not in pedido.content
    assert ors_falso.corpos() == [_pedido_vroom([PARAGEM_B, PARAGEM_C]), pedido_direcoes(PONTOS, False)]
    assert ors_falso.corpos()[0] == PEDIDO_VROOM_PADRAO
    assert ors_falso.corpos()[1]["coordinates"] == [[-9.1393, 38.7223], [-9.2065, 38.6979], [-9.15, 38.7253], [-9.1393, 38.7223]]


def test_o_pedido_ao_vroom_so_leva_numeros_e_driving_car(sessao, ors_falso):
    """§0, regra 12: nem nomes, telefones, moradas, notas, fases, motivos nem
    uuids; as chaves são exatamente as do `pedido_otimizacao`; as prioridades
    100/1 e as janelas `[a, b − s]` (09:00–12:00 com 15 min → [32400, 42300])."""
    cliente = sessao()
    _ok(cliente)
    texto = ors_falso.pedidos[0].content.decode("utf-8")
    for canario in CANARIOS:
        assert canario not in texto
    corpo = ors_falso.corpos()[0]
    assert set(corpo) == {"jobs", "vehicles"}
    for job in corpo["jobs"]:
        assert set(job) <= {"id", "location", "service", "priority", "time_windows"}
        assert {"id", "location", "service", "priority"} <= set(job)
    assert [job["priority"] for job in corpo["jobs"]] == [1, 1]
    assert ("time_windows" in corpo["jobs"][0], corpo["jobs"][1]["time_windows"]) == (False, [[32400, 42300]])
    assert [job["id"] for job in corpo["jobs"]] == [1, 2]
    assert corpo["vehicles"][0]["profile"] == "driving-car"
    textos = [v for v in _folhas(corpo) if isinstance(v, str)]
    assert textos == ["driving-car"]
    assert all(type(v) in (int, float) for v in _folhas(corpo) if not isinstance(v, str))


def _folhas(valor):
    if isinstance(valor, dict):
        return [f for v in valor.values() for f in _folhas(v)]
    if isinstance(valor, list):
        return [f for v in valor for f in _folhas(v)]
    return [valor]


def test_a_entrega_vai_com_prioridade_100_e_as_outras_com_1(sessao, ors_falso):
    paragens, lojas = _muitas(2)
    cliente = sessao(ZE_UTILIZADOR, _base(rotas=[_rota(AMANHA, paragens)], lojas=lojas))
    ors_falso.vroom(_otimizacao([1, 2, 3]))
    ors_falso.direcoes(_direcoes([600] * 4, [1000.0] * 4, [FABRICA_PADRAO] * 5))
    _ok(cliente)
    assert [(job["id"], job["priority"], job["service"]) for job in ors_falso.corpos()[0]["jobs"]] == [(1, 100, 600), (2, 1, 900), (3, 1, 900)]


def test_uma_paragem_que_nao_cabia_volta_a_ir_ao_vroom_e_se_couber_volta_a_rota(sessao, ors_falso):
    """Correção "T3.22 / §1": a C gravada com `nao_cabe: true` (e horas
    velhas) vai no pedido ao VROOM e, atribuída, volta à secção "rota" com
    `nao_cabe: false`, uma hora e um número."""
    velhas = {"nao_cabe": True, **HORAS_VELHAS}
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(por_paragem={PARAGEM_C: velhas}, calculo=deepcopy(CALCULO_VELHO)))
    r, rota = _ok(cliente)
    assert ors_falso.corpos()[0] == PEDIDO_VROOM_PADRAO
    assert _escritas(cliente.base) == [_escrita({
        **ORDEM_PADRAO, **HORAS_PADRAO, "paragens.3.nao_cabe": False, "paragens.3.fora_de_horario": False,
        "calculo": _calculo(rota, _lojas(), PONTOS, 6001, 2700, "09:55"),
    }, calculo=CALCULO_VELHO)]
    assert _resumo(r) == [(PARAGEM_C, 1, "rota", False, "08:20"), (PARAGEM_B, 2, "rota", False, "09:30"), (PARAGEM_A, None, "fechada", False, None)]
    assert r.json()["calculo"]["atual"] is True


def test_a_fechada_sem_manter_nao_vai_ao_vroom_e_com_manter_vai(sessao, ors_falso):
    """Com "Manter", a A (ordem 2) é o job 3; o VROOM responde A → B → C e o
    Directions leva os 5 pontos."""
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(por_paragem={PARAGEM_A: {"manter_fechada": True}}))
    pontos = [FABRICA_PADRAO, COMERCIO, MARQUES, BELEM, FABRICA_PADRAO]
    ors_falso.vroom(_otimizacao([3, 1, 2]))
    ors_falso.direcoes(_direcoes([600, 600, 900, 1200], [1000.0, 1000.0, 2000.0, 3000.0], pontos))
    r, rota = _ok(cliente)
    paragens = _tres_paragens(**{PARAGEM_A: {"manter_fechada": True}})
    assert ors_falso.corpos() == [_pedido_vroom([PARAGEM_B, PARAGEM_C, PARAGEM_A], paragens), pedido_direcoes(pontos, False)]
    assert len(ors_falso.corpos()[0]["jobs"]) == 3
    # A 08:10 → B 08:35 → C 09:05 (já aberta) → regresso 09:40.
    assert _escritas(cliente.base) == [_escrita({
        "paragens.0.ordem": 0, "paragens.1.ordem": 1, "paragens.3.ordem": 2,
        "paragens.0.chegada_prevista": "08:10", "paragens.0.espera_min": 0,
        "paragens.1.chegada_prevista": "08:35", "paragens.1.espera_min": 0,
        "paragens.3.chegada_prevista": "09:05", "paragens.3.espera_min": 0,
        "calculo": _calculo(rota, _lojas(), pontos, 7000, 3300, "09:40"),
    })]
    assert _resumo(r) == [(PARAGEM_A, 1, "rota", False, "08:10"), (PARAGEM_B, 2, "rota", False, "08:35"), (PARAGEM_C, 3, "rota", False, "09:05")]


def test_uma_paragem_sem_loja_nao_vai_ao_vroom_e_fica_no_fim(sessao, ors_falso):
    paragens = [*_tres_paragens(), _paragem(PARAGEM_E, LOJA_E, 3, **HORAS_VELHAS)]
    cliente = sessao(ZE_UTILIZADOR, _base(rotas=[_rota(AMANHA, paragens)], lojas=_lojas()))
    r, rota = _ok(cliente)
    assert ors_falso.corpos()[0] == PEDIDO_VROOM_PADRAO
    assert _escritas(cliente.base) == [_escrita({
        **ORDEM_PADRAO, **HORAS_PADRAO,
        "paragens.4.chegada_prevista": None, "paragens.4.espera_min": None, "paragens.4.fora_de_horario": False,
        "calculo": _calculo(rota, _lojas(), PONTOS, 6001, 2700, "09:55"),
    })]
    assert _resumo(r)[-2:] == [(PARAGEM_A, None, "fechada", False, None), (PARAGEM_E, None, "sem_loja", False, None)]


def test_com_evitar_portagens_so_o_directions_leva_avoid_features(sessao, ors_falso):
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(evitar_portagens=True))
    r, rota = _ok(cliente)
    assert ors_falso.corpos() == [PEDIDO_VROOM_PADRAO, pedido_direcoes(PONTOS, True)]
    assert ors_falso.corpos()[1]["options"] == {"avoid_features": ["tollways"]}
    assert rota["calculo"] == _calculo(rota, _lojas(), PONTOS, 6001, 2700, "09:55")
    assert r.json()["calculo"]["atual"] is True


def test_o_inicio_proprio_da_rota_e_a_fabrica_das_definicoes_em_vigor_como_fim(sessao, ors_falso):
    """`inicio` é o ponto da rota; `fim: null` é a fábrica guardada nas
    definições (não a dos padrões), nos dois pedidos. As horas do dia vão na
    `time_window` do veículo."""
    definicoes = [_guardada("fabrica_lat", str(OUTRA_FABRICA[0])), _guardada("fabrica_lng", str(OUTRA_FABRICA[1]))]
    rota_ = _rota(AMANHA, _tres_paragens(), inicio=OUTRO_PONTO, hora_saida="07:30", hora_regresso_limite="18:00")
    cliente = sessao(ZE_UTILIZADOR, _base(rotas=[rota_], lojas=_lojas(), definicoes=definicoes))
    inicio = (OUTRO_PONTO["lat"], OUTRO_PONTO["lng"])
    pontos = [inicio, BELEM, MARQUES, OUTRA_FABRICA]
    ors_falso.direcoes(_direcoes(pontos=pontos))
    r, rota = _ok(cliente)
    esperado = _pedido_vroom([PARAGEM_B, PARAGEM_C], inicio=inicio, fim=OUTRA_FABRICA, saida="07:30", limite="18:00")
    assert ors_falso.corpos() == [esperado, pedido_direcoes(pontos, False)]
    assert esperado["vehicles"][0] == {"id": 1, "profile": "driving-car", "start": [-9.1, 38.6], "end": [-9.2, 38.75], "time_window": [27000, 64800]}
    # 07:30 → C 07:50, espera até às 09:00 → B 09:30 → regresso 09:55.
    assert rota["calculo"] == _calculo(rota, _lojas(), pontos, 6001, 2700, "09:55")
    em_vigor = {**DEFINICOES_PADRAO, "fabrica_lat": OUTRA_FABRICA[0], "fabrica_lng": OUTRA_FABRICA[1]}
    assert r.json() == _api(rota, _lojas(), definicoes=em_vigor)
    assert (r.json()["calculo"]["atual"], r.json()["fim"]) == (True, {"lat": OUTRA_FABRICA[0], "lng": OUTRA_FABRICA[1], "fabrica": True})


# --- A escrita -----------------------------------------------------------------------------------


def test_grava_a_ordem_do_vroom_as_horas_e_o_calculo_numa_so_escrita_e_sobe_a_versao(sessao, ors_falso):
    """Uma só `find_one_and_update` com o filtro de guarda, o `$set` do que
    muda (a ordem nova pelos caminhos por índice, as horas das atribuídas e o
    `calculo` inteiro) mais a autoria, e o `$inc` da versão. A resposta é a
    rota gravada, com `calculo.atual: true` e a versão 4."""
    cliente = sessao()
    antes = _gravadas(cliente.base)[0]
    r, rota = _ok(cliente)
    calculo = _calculo(rota, _lojas(), PONTOS, 6001, 2700, "09:55")
    assert _escritas(cliente.base) == [_escrita({**ORDEM_PADRAO, **HORAS_PADRAO, "calculo": calculo})]
    assert (rota["versao"], rota["atualizado_em"], rota["atualizado_por"]) == (4, AGORA_CARIMBO, ZE)
    assert [(p["id"], p["ordem"], p["nao_cabe"]) for p in rota["paragens"]] == [
        (PARAGEM_A, 2, False), (PARAGEM_B, 1, False), (PARAGEM_D, None, False), (PARAGEM_C, 0, False),
    ]
    assert rota["calculo"] == calculo
    assert rota == {**antes, "paragens": rota["paragens"], "calculo": calculo, "versao": 4, **AUTORIA}
    assert r.json() == _api(rota, _lojas())
    assert (r.json()["versao"], r.json()["calculo"]["atual"], r.json()["calculo_disponivel"]) == (4, True, True)
    assert "assinatura" not in r.json()["calculo"]
    assert [(p["numero"], p["chegada_prevista"], p["espera_min"], p["fora_de_horario"], p["aviso"]) for p in r.json()["paragens"]] == [
        (1, "08:20", 40, False, "nenhum"), (2, "09:30", 0, False, "nenhum"), (None, None, None, False, "fechada_neste_dia"),
    ]
    assert r.json()["calculo"] == {
        "atual": True, "distancia_m": 6001, "duracao_s": 2700, "regresso_previsto": "09:55",
        "depois_do_limite": False, "geometria": polilinha.codificar(PONTOS), "calculado_em": AGORA_INSTANTE,
    }


def test_so_escreve_o_que_muda_e_o_calculo_escreve_se_sempre(sessao, ors_falso):
    """Com a ordem (C, B) e as horas já gravadas iguais às calculadas, e o
    VROOM a devolver essa mesma ordem (os jobs vão pela ordem gravada: 1 = C,
    2 = B), o `$set` leva só o `calculo` (que fica sempre, com o
    `calculado_em` de agora) — e a versão sobe na mesma."""
    iguais = {
        PARAGEM_B: {"ordem": 1, "chegada_prevista": "09:30", "espera_min": 0},
        PARAGEM_C: {"ordem": 0, "chegada_prevista": "08:20", "espera_min": 40},
    }
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(por_paragem=iguais, calculo=deepcopy(CALCULO_VELHO)))
    ors_falso.vroom(_otimizacao([1, 2]))
    r, rota = _ok(cliente)
    assert ors_falso.corpos()[0] == _pedido_vroom([PARAGEM_C, PARAGEM_B])
    assert _escritas(cliente.base) == [
        _escrita({"calculo": _calculo(rota, _lojas(), PONTOS, 6001, 2700, "09:55")}, calculo=CALCULO_VELHO)
    ]
    assert (rota["versao"], r.json()["calculo"]["atual"]) == (4, True)


def test_duas_vezes_seguidas_a_segunda_sobe_outra_vez_a_versao(sessao, ors_falso):
    """À segunda, os jobs vão pela ordem já gravada (1 = C, 2 = B); com o
    VROOM a devolvê-la tal e qual, só o `calculo` se reescreve, mas a versão
    sobe outra vez e o carimbo avança 1 µs."""
    cliente = sessao()
    _ok(cliente)
    ors_falso.vroom(_otimizacao([1, 2]))
    r, rota = _ok(cliente, versao=4)
    assert ors_falso.caminhos() == [CAMINHO_VROOM, CAMINHO_DIRECOES] * 2
    assert ors_falso.corpos()[2] == _pedido_vroom([PARAGEM_C, PARAGEM_B])
    calculo = _calculo(rota, _lojas(), PONTOS, 6001, 2700, "09:55")
    # A 2.ª leu o cálculo gravado pela 1.ª, e leva-o no filtro (correção "F3-INT-1").
    assert _escritas(cliente.base)[1] == _escrita({"calculo": calculo}, versao=4, autoria=_autoria(1), calculo=calculo)
    assert (rota["versao"], r.json()["versao"]) == (5, 5)


def test_as_nao_atribuidas_ficam_nao_cabe_sem_hora_depois_das_atribuidas_e_antes_das_fechadas(sessao, ors_falso):
    """A A fechada gravada em primeiro (ordem 0), a B (1) e a C (2); o VROOM
    atribui só a B: a ordem fica B, C (`nao_cabe`), A (fechada) — as fechadas
    vão para depois das `nao_cabe`, não para onde estavam."""
    por_paragem = {PARAGEM_A: {"ordem": 0}, PARAGEM_B: {"ordem": 1}, PARAGEM_C: {"ordem": 2, **HORAS_VELHAS}}
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(por_paragem=por_paragem))
    pontos = [FABRICA_PADRAO, MARQUES, FABRICA_PADRAO]
    ors_falso.vroom(_otimizacao([1], [2]))
    ors_falso.direcoes(_direcoes([600, 600], [1000.0, 1000.0], pontos))
    r, rota = _ok(cliente)
    assert ors_falso.corpos() == [PEDIDO_VROOM_PADRAO, pedido_direcoes(pontos, False)]
    assert _escritas(cliente.base) == [_escrita({
        "paragens.0.ordem": 2, "paragens.1.ordem": 0, "paragens.3.ordem": 1,
        "paragens.3.nao_cabe": True,
        "paragens.1.chegada_prevista": "08:10", "paragens.1.espera_min": 0,
        "paragens.3.chegada_prevista": None, "paragens.3.espera_min": None, "paragens.3.fora_de_horario": False,
        "calculo": _calculo(rota, _lojas(), pontos, 2000, 1200, "08:35"),
    })]
    assert _resumo(r) == [(PARAGEM_B, 1, "rota", False, "08:10"), (PARAGEM_C, None, "nao_cabe", True, None), (PARAGEM_A, None, "fechada", False, None)]
    assert [p["aviso"] for p in r.json()["paragens"]] == ["nenhum", "nao_cabe", "fechada_neste_dia"]


def test_as_impossiveis_nao_vao_ao_vroom_e_ficam_nao_cabe_depois_das_nao_atribuidas(sessao, ors_falso):
    """A B só recebe das 10:00 às 10:05 (15 min não cabem: impossível, não se
    envia); a A mantida e a C são os jobs 1 = C e 2 = A; o VROOM atribui só a
    A: a ordem fica A, C (não atribuída), B (impossível)."""
    lojas = _lojas(janelas_b=(_janela("10:00", "10:05"),))
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(lojas=lojas, por_paragem={PARAGEM_A: {"manter_fechada": True}}))
    pontos = [FABRICA_PADRAO, COMERCIO, FABRICA_PADRAO]
    ors_falso.vroom(_otimizacao([2], [1]))
    ors_falso.direcoes(_direcoes([600, 600], [1000.0, 1000.0], pontos))
    r, rota = _ok(cliente)
    paragens = _tres_paragens(**{PARAGEM_A: {"manter_fechada": True}})
    assert ors_falso.corpos() == [_pedido_vroom([PARAGEM_C, PARAGEM_A], paragens, lojas), pedido_direcoes(pontos, False)]
    assert [job["id"] for job in ors_falso.corpos()[0]["jobs"]] == [1, 2]
    assert _escritas(cliente.base) == [_escrita({
        "paragens.0.ordem": 0, "paragens.1.ordem": 2,
        "paragens.1.nao_cabe": True, "paragens.3.nao_cabe": True,
        "paragens.0.chegada_prevista": "08:10", "paragens.0.espera_min": 0,
        "calculo": _calculo(rota, lojas, pontos, 2000, 1200, "08:35"),
    })]
    assert _resumo(r) == [(PARAGEM_A, 1, "rota", False, "08:10"), (PARAGEM_C, None, "nao_cabe", True, None), (PARAGEM_B, None, "nao_cabe", True, None)]


def test_o_cenario_da_prioridade_uma_entrega_e_onze_visitas(sessao, ors_falso):
    """Só a entrega é atribuída (a resposta escrita aqui; o VROOM verdadeiro é
    o risco R3): fica na rota com hora e número, as 11 visitas em `nao_cabe`,
    pela ordem do pedido, sem hora."""
    paragens, lojas = _muitas(11)
    cliente = sessao(ZE_UTILIZADOR, _base(rotas=[_rota(AMANHA, paragens)], lojas=lojas))
    pontos = [FABRICA_PADRAO, (lojas[0]["lat"], lojas[0]["lng"]), FABRICA_PADRAO]
    ors_falso.vroom(_otimizacao([1], range(2, 13)))
    ors_falso.direcoes(_direcoes([600, 600], [1000.0, 1000.0], pontos))
    r, rota = _ok(cliente)
    assert len(ors_falso.corpos()[0]["jobs"]) == 12
    assert [job["priority"] for job in ors_falso.corpos()[0]["jobs"]] == [100] + [1] * 11
    assert ors_falso.corpos()[1] == pedido_direcoes(pontos, False)
    assert _escritas(cliente.base) == [_escrita({
        **{f"paragens.{i}.nao_cabe": True for i in range(1, 12)},
        "paragens.0.chegada_prevista": "08:10", "paragens.0.espera_min": 0,
        "calculo": _calculo(rota, lojas, pontos, 2000, 1200, "08:30"),
    })]
    assert _resumo(r)[0] == (_id_paragem(1), 1, "rota", False, "08:10")
    assert _resumo(r)[1:] == [(_id_paragem(n), None, "nao_cabe", True, None) for n in range(2, 13)]
    assert [p["ordem"] for p in rota["paragens"]] == list(range(12))
    assert (r.json()["versao"], r.json()["calculo"]["atual"]) == (4, True)


def test_fora_de_horario_e_depois_do_limite_vem_do_dominio(sessao, ors_falso):
    """O VROOM atribuiu a C (recebe das 09:00 às 09:30: a janela do início do
    serviço é [09:00, 09:15]), mas pelo Directions ela só chega às 09:20:
    serve-se à chegada, sem espera, com `fora_de_horario` e o aviso; o limite
    às 09:00 → regresso depois do limite."""
    lojas = _lojas(janelas_c=(_janela("09:00", "09:30"),))
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(lojas=lojas, hora_regresso_limite="09:00"))
    ors_falso.direcoes(_direcoes([4800, 900, 600]))
    r, rota = _ok(cliente)
    assert ors_falso.corpos()[0]["jobs"][1]["time_windows"] == [[32400, 33300]]
    # C 09:20 sem espera (+15) → B 09:50 (+15) → regresso 10:15, depois do limite.
    assert _escritas(cliente.base) == [_escrita({
        **ORDEM_PADRAO,
        "paragens.3.chegada_prevista": "09:20", "paragens.3.espera_min": 0, "paragens.3.fora_de_horario": True,
        "paragens.1.chegada_prevista": "09:50", "paragens.1.espera_min": 0,
        "calculo": _calculo(rota, lojas, PONTOS, 6001, 6300, "10:15", depois=True),
    })]
    assert [(p["fora_de_horario"], p["aviso"]) for p in r.json()["paragens"]][:2] == [(True, "fora_de_horario"), (False, "nenhum")]
    assert r.json()["calculo"]["depois_do_limite"] is True


# --- Sem nenhuma atribuída: sem Directions e o calculo a None ---------------------------------------


def test_sem_nenhuma_atribuida_todas_ficam_nao_cabe_sem_directions_e_a_versao_sobe(sessao, ors_falso):
    """Correção "T3.6 / T3.22": `routes: []` com todos em `unassigned` → 200,
    as enviadas `nao_cabe: true` (as horas velhas apagadas), sem Directions,
    `calculo: None` e a versão + 1."""
    por_paragem = {PARAGEM_B: HORAS_VELHAS, PARAGEM_C: {"espera_min": 3}}
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(por_paragem=por_paragem, calculo=deepcopy(CALCULO_VELHO)))
    ors_falso.vroom(_otimizacao([], [1, 2]))
    r, rota = _ok(cliente)
    assert ors_falso.caminhos() == [CAMINHO_VROOM]
    assert _escritas(cliente.base) == [_escrita({
        "paragens.1.nao_cabe": True, "paragens.3.nao_cabe": True,
        "paragens.1.chegada_prevista": None, "paragens.1.espera_min": None, "paragens.1.fora_de_horario": False,
        "paragens.3.espera_min": None,
        "calculo": None,
    }, calculo=CALCULO_VELHO)]
    assert (rota["versao"], rota["calculo"]) == (4, None)
    assert r.json() == _api(rota, _lojas())
    assert _resumo(r) == [(PARAGEM_B, None, "nao_cabe", True, None), (PARAGEM_C, None, "nao_cabe", True, None), (PARAGEM_A, None, "fechada", False, None)]
    assert r.json()["calculo"] is None


def test_sem_nenhuma_atribuida_e_sem_calculo_gravado_escreve_so_os_sinais(sessao, ors_falso):
    cliente = sessao()
    ors_falso.vroom(_otimizacao([], [1, 2]))
    r, rota = _ok(cliente)
    assert _escritas(cliente.base) == [_escrita({"paragens.1.nao_cabe": True, "paragens.3.nao_cabe": True})]
    assert (rota["versao"], rota["calculo"], r.json()["versao"]) == (4, None, 4)


def test_com_todas_impossiveis_nao_se_chama_o_ors_e_ficam_nao_cabe_com_a_versao_a_subir(sessao, ors_falso):
    """Correção "T3.6 / T3.22 (zero jobs)": há paragens a enviar mas nenhum
    *job* cabe numa janela (`corpo is None`): nenhum pedido, `nao_cabe: true`
    nas duas, o `calculo` que havia a `None`, `$inc` da versão."""
    lojas = _lojas(janelas_b=(_janela("10:00", "10:05"),), janelas_c=(_janela("09:00", "09:10"),))
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(lojas=lojas, calculo=deepcopy(CALCULO_VELHO)))
    r, rota = _ok(cliente)
    assert ors_falso.pedidos == []
    assert _escritas(cliente.base) == [
        _escrita({"paragens.1.nao_cabe": True, "paragens.3.nao_cabe": True, "calculo": None}, calculo=CALCULO_VELHO)
    ]
    assert (rota["versao"], rota["calculo"]) == (4, None)
    assert _resumo(r) == [(PARAGEM_B, None, "nao_cabe", True, None), (PARAGEM_C, None, "nao_cabe", True, None), (PARAGEM_A, None, "fechada", False, None)]


def test_com_todas_impossiveis_tambem_sem_chave_da_200(sessao):
    """O 503 `sem_chave` é só de quem precisa do openrouteservice."""
    lojas = _lojas(janelas_b=(_janela("10:00", "10:05"),), janelas_c=(_janela("09:00", "09:10"),))
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(lojas=lojas))
    r, rota = _ok(cliente)
    assert _escritas(cliente.base) == [_escrita({"paragens.1.nao_cabe": True, "paragens.3.nao_cabe": True})]
    assert r.json() == _api(rota, lojas, calculo_disponivel=False)


@pytest.mark.parametrize(
    "paragens",
    [
        [_paragem(PARAGEM_A, LOJA_A, 0)],
        [_paragem(PARAGEM_A, LOJA_A, 0), _paragem(PARAGEM_E, LOJA_E, 1)],
        [_retirada(PARAGEM_B, LOJA_B), _retirada(PARAGEM_C, LOJA_C)],
        [],
    ],
    ids=["só a fechada", "sem loja e fechada", "todas retiradas", "sem paragens"],
)
def test_sem_nada_para_o_vroom_limpa_o_calculo_que_havia_sem_chamar_o_ors(sessao, paragens):
    """Zero *jobs*: nenhum pedido (a guarda do conftest falharia), uma só
    escrita com `calculo: None` (a versão sobe, como em toda a escrita do
    otimizar)."""
    base = _base(rotas=[_rota(AMANHA, paragens, calculo=deepcopy(CALCULO_VELHO))], lojas=_lojas())
    cliente = sessao(ZE_UTILIZADOR, base)
    r, rota = _ok(cliente)
    assert _escritas(base) == [_escrita({"calculo": None}, calculo=CALCULO_VELHO)]
    assert (rota["versao"], rota["calculo"]) == (4, None)
    assert r.json() == _api(rota, _lojas(), calculo_disponivel=False)
    assert r.json()["calculo"] is None


def test_sem_nada_para_o_vroom_e_sem_calculo_nao_escreve(sessao):
    base = _base(rotas=[_rota(AMANHA, [_paragem(PARAGEM_A, LOJA_A, 0)])], lojas=_lojas())
    cliente = sessao(ZE_UTILIZADOR, base)
    antes = _gravadas(base)
    r = _otimizar(cliente)
    assert r.status_code == 200, r.text
    _nada_muda(cliente, antes)
    assert r.json() == _api(antes[0], _lojas(), calculo_disponivel=False)
    assert r.json()["versao"] == 3


def test_com_tudo_ja_nao_cabe_e_sem_calculo_nao_escreve(sessao, ors_falso):
    """As duas já `nao_cabe` e o VROOM volta a não atribuir nenhuma: nada muda,
    200 sem escrever e sem subir a versão."""
    por_paragem = {PARAGEM_B: {"nao_cabe": True}, PARAGEM_C: {"nao_cabe": True}}
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(por_paragem=por_paragem))
    antes = _gravadas(cliente.base)
    ors_falso.vroom(_otimizacao([], [1, 2]))
    r = _otimizar(cliente)
    assert r.status_code == 200, r.text
    assert ors_falso.caminhos() == [CAMINHO_VROOM]
    _nada_muda(cliente, antes)
    assert r.json()["versao"] == 3


# --- O simulador local e as fixtures gravadas: o formato real -------------------------------------


def test_de_ponta_a_ponta_pelo_simulador_local(sessao, ors_falso):
    """Os dois serviços pelo simulador (T3.13): a resposta do VROOM lê-se
    (atribuídos ∪ não atribuídos = enviados), o Directions vai pela ordem
    escolhida (B primeiro: mais perto da fábrica) e as horas ficam gravadas."""
    cliente = sessao()
    ors_falso.pelo_simulador()
    r, rota = _ok(cliente)
    vroom, direcoes = ors_falso.respostas
    assert (vroom["metadata"]["simulador"], direcoes["metadata"]["simulador"]) == (True, True)
    atribuidos = [p["id"] for p in vroom["routes"][0]["steps"] if p["type"] == "job"]
    assert sorted(atribuidos + [u["id"] for u in vroom["unassigned"]]) == [1, 2]
    assert atribuidos == [1, 2]  # B (Marquês) fica mais perto da fábrica do que C (Belém)
    assert ors_falso.corpos()[1]["coordinates"] == pedido_direcoes([FABRICA_PADRAO, MARQUES, BELEM, FABRICA_PADRAO], False)["coordinates"]
    assert _resumo(r)[:2] == [(PARAGEM_B, 1, "rota", False, r.json()["paragens"][0]["chegada_prevista"]), (PARAGEM_C, 2, "rota", False, r.json()["paragens"][1]["chegada_prevista"])]
    assert all(p["chegada_prevista"] is not None for p in r.json()["paragens"][:2])
    assert (r.json()["versao"], r.json()["calculo"]["atual"]) == (4, True)
    assert rota["calculo"]["geometria"] == direcoes["routes"][0]["geometry"]
    resumo = direcoes["routes"][0]["summary"]
    assert (rota["calculo"]["distancia_m"], rota["calculo"]["duracao_s"]) == (int(resumo["distance"] + 0.5), int(resumo["duration"] + 0.5))


def _cenario_das_fixtures():
    """A rota do `cenarios.json`: Comércio (entrega, 10 min, 09:00–12:00),
    Marquês (amostra, 10) e Belém (acompanhamento, 15), por esta ordem."""
    lojas = [
        _loja(LOJA_A, "Comércio", "cliente", COMERCIO, janelas=[_janela("09:00", "12:00")]),
        _loja(LOJA_B, "Marquês", "contactada", MARQUES),
        _loja(LOJA_C, "Belém", "amostra", (38.6916, -9.216)),
    ]
    paragens = [
        _paragem(PARAGEM_A, LOJA_A, 0, motivo="entrega", tempo_servico_min=10),
        _paragem(PARAGEM_B, LOJA_B, 1, motivo="amostra", tempo_servico_min=10),
        _paragem(PARAGEM_C, LOJA_C, 2, motivo="acompanhamento", tempo_servico_min=15),
    ]
    return paragens, lojas


def test_a_fixture_otimizacao_todas_le_se_de_ponta_a_ponta(sessao, ors_falso):
    """`otimizacao-todas.json` (jobs 2, 1, 3) serve a rota do cenário: as 3
    ficam na rota, numeradas pela ordem do VROOM; só prova o formato."""
    paragens, lojas = _cenario_das_fixtures()
    cliente = sessao(ZE_UTILIZADOR, _base(rotas=[_rota(AMANHA, paragens)], lojas=lojas))
    gravada = _fixture("otimizacao-todas.json")
    ors_falso.vroom(gravada)
    ors_falso.direcoes(_direcoes([600] * 4, [1000.0] * 4, [FABRICA_PADRAO, MARQUES, COMERCIO, (38.6916, -9.216), FABRICA_PADRAO]))
    r, rota = _ok(cliente)
    assert ors_falso.corpos()[0]["jobs"][0]["priority"] == 100
    atribuidos = [p["id"] for p in gravada["routes"][0]["steps"] if p["type"] == "job"]
    assert sorted(atribuidos) == [1, 2, 3] and gravada["unassigned"] == []
    assert [(p["id"], p["numero"], p["nao_cabe"]) for p in r.json()["paragens"]] == [(PARAGEM_B, 1, False), (PARAGEM_A, 2, False), (PARAGEM_C, 3, False)]
    assert all(p["chegada_prevista"] is not None for p in r.json()["paragens"])
    assert (r.json()["versao"], r.json()["calculo"]["atual"]) == (4, True)


def test_a_fixture_otimizacao_uma_nao_cabe_le_se_de_ponta_a_ponta(sessao, ors_falso):
    paragens, lojas = _cenario_das_fixtures()
    cliente = sessao(ZE_UTILIZADOR, _base(rotas=[_rota(AMANHA, paragens)], lojas=lojas))
    gravada = _fixture("otimizacao-uma-nao-cabe.json")
    ors_falso.vroom(gravada)
    ors_falso.direcoes(_direcoes([600] * 3, [1000.0] * 3, [FABRICA_PADRAO, MARQUES, COMERCIO, FABRICA_PADRAO]))
    r, rota = _ok(cliente)
    assert [u["id"] for u in gravada["unassigned"]] == [3]
    assert [(p["id"], p["numero"], p["seccao"], p["nao_cabe"]) for p in r.json()["paragens"]] == [
        (PARAGEM_B, 1, "rota", False), (PARAGEM_A, 2, "rota", False), (PARAGEM_C, None, "nao_cabe", True),
    ]
    assert len(ors_falso.corpos()[1]["coordinates"]) == 4


# --- As falhas do openrouteservice: 503 e nada muda (tudo ou nada) ---------------------------------


def test_sem_chave_da_503_sem_pedido_nenhum(sessao, ors_falso, monkeypatch):
    monkeypatch.delenv(ors.VARIAVEL_CHAVE)
    cliente = sessao()
    antes = _gravadas(cliente.base)
    r = _otimizar(cliente)
    assert (r.status_code, r.json()) == (503, _indisponivel("sem_chave"))
    assert ors_falso.pedidos == []
    _nada_muda(cliente, antes)


def test_o_vroom_a_falhar_com_429_da_o_limite_sem_directions(sessao, ors_falso):
    cliente = sessao()
    antes = _gravadas(cliente.base)
    ors_falso.vroom(_fixture("erro-429.json"), estado=429)
    r = _otimizar(cliente)
    assert (r.status_code, r.json()) == (503, _indisponivel("limite", LIMITE))
    assert ors_falso.caminhos() == [CAMINHO_VROOM]
    _nada_muda(cliente, antes)


@pytest.mark.parametrize(
    "estado, dados",
    [
        (500, {"error": "x"}),
        (401, {"error": {"code": 2001, "message": "Authorization field missing"}}),
        (403, {"error": "Quota exceeded"}),
        (400, {"code": 3, "error": "Unfound route(s) from location [-9.2,38.6]"}),
        (404, {"error": {"code": 2010, "message": "Could not find routable point ... coordinate 1: -9.15 38.7253."}}),
        (200, []),
        (200, {}),
        (200, {"code": 1, "error": "Internal error"}),
        (200, {**_otimizacao([2, 1]), "routes": _otimizacao([2, 1])["routes"] * 2}),
        (200, _otimizacao([3, 1])),
        (200, _otimizacao([1, 1])),
        (200, _otimizacao([1])),
        (200, _otimizacao([1], [2, 2])),
        (200, {**_otimizacao([2, 1]), "unassigned": None}),
        (200, {**_otimizacao([2, 1]), "routes": [{**_otimizacao([2, 1])["routes"][0], "vehicle": 2}]}),
        (200, {**_otimizacao([1]), "routes": [{**_otimizacao([1])["routes"][0], "steps": [*_otimizacao([1])["routes"][0]["steps"], {"type": "break", "id": 2}]}]}),
    ],
    ids=["500", "401", "403", "erro do VROOM", "2010 na otimização", "lista", "vazio", "code 1", "duas rotas",
         "job desconhecido", "job repetido", "job em falta", "não atribuído repetido", "sem unassigned", "veículo 2", "passo break"],
)
def test_uma_resposta_do_vroom_que_nao_serve_e_indisponivel_sem_directions(sessao, ors_falso, estado, dados):
    cliente = sessao()
    antes = _gravadas(cliente.base)
    ors_falso.vroom(dados, estado=estado)
    r = _otimizar(cliente)
    assert (r.status_code, r.json()) == (503, _indisponivel("indisponivel"))
    assert ors_falso.caminhos() == [CAMINHO_VROOM]
    _nada_muda(cliente, antes)


def test_o_vroom_com_um_corpo_que_nao_e_json_e_indisponivel(sessao, ors_falso):
    cliente = sessao()
    ors_falso.vroom(conteudo=b"<html>erro</html>")
    r = _otimizar(cliente)
    assert (r.status_code, r.json()) == (503, _indisponivel("indisponivel"))
    assert ors_falso.caminhos() == [CAMINHO_VROOM]


def test_a_rede_a_falhar_no_vroom_e_indisponivel(sessao, ors_falso):
    cliente = sessao()
    antes = _gravadas(cliente.base)
    ors_falso.vroom(excecao=lambda pedido: httpx.ConnectError(f"ligação recusada {CHAVE}", request=pedido))
    r = _otimizar(cliente)
    assert (r.status_code, r.json()) == (503, _indisponivel("indisponivel"))
    assert ors_falso.caminhos() == [CAMINHO_VROOM]
    _nada_muda(cliente, antes)


def test_o_vroom_responde_bem_e_o_directions_falha_nada_muda(sessao, ors_falso):
    """Atómico: os dois pedidos saíram, o segundo falhou (500) e nem a ordem
    nova nem os sinais ficam gravados."""
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(por_paragem={PARAGEM_C: {"nao_cabe": True}}, calculo=deepcopy(CALCULO_VELHO)))
    antes = _gravadas(cliente.base)
    ors_falso.direcoes({"error": "x"}, estado=500)
    r = _otimizar(cliente)
    assert (r.status_code, r.json()) == (503, _indisponivel("indisponivel"))
    assert ors_falso.caminhos() == [CAMINHO_VROOM, CAMINHO_DIRECOES]
    _nada_muda(cliente, antes)
    assert _gravadas(cliente.base)[0]["paragens"][3]["nao_cabe"] is True
    assert _gravadas(cliente.base)[0]["calculo"] == CALCULO_VELHO


@pytest.mark.parametrize(
    "estado, dados, tipo, mensagem",
    [
        (429, _fixture("erro-429.json"), "limite", LIMITE),
        (200, {"routes": []}, "indisponivel", GERAL),
        (200, _direcoes([600, 900], [1.0, 2.0], PONTOS[:3]), "indisponivel", GERAL),  # um troço a menos
        (200, {"routes": [{"segments": [{}, {}, {}], "geometry": "???"}]}, "indisponivel", GERAL),
        (500, {"error": "x"}, "indisponivel", GERAL),
    ],
    ids=["429", "sem rota", "troço a menos", "linha estragada", "500"],
)
def test_o_directions_a_falhar_de_varias_formas_nada_muda(sessao, ors_falso, estado, dados, tipo, mensagem):
    cliente = sessao()
    antes = _gravadas(cliente.base)
    ors_falso.direcoes(dados, estado=estado)
    r = _otimizar(cliente)
    assert (r.status_code, r.json()) == (503, _indisponivel(tipo, mensagem))
    assert ors_falso.caminhos() == [CAMINHO_VROOM, CAMINHO_DIRECOES]
    _nada_muda(cliente, antes)


def test_a_rede_a_falhar_no_directions_nada_muda(sessao, ors_falso):
    cliente = sessao()
    antes = _gravadas(cliente.base)
    ors_falso.direcoes(excecao=lambda pedido: httpx.ReadTimeout("lento", request=pedido))
    r = _otimizar(cliente)
    assert (r.status_code, r.json()) == (503, _indisponivel("indisponivel"))
    assert ors_falso.caminhos() == [CAMINHO_VROOM, CAMINHO_DIRECOES]
    _nada_muda(cliente, antes)


@pytest.mark.parametrize(
    "indice, mensagem",
    [(0, INICIO_SEM_ESTRADA), (1, _paragem_sem_estrada(2)), (2, _paragem_sem_estrada(1)), (3, FIM_SEM_ESTRADA)],
    ids=["início", "1.ª enviada = C (número 2)", "2.ª enviada = B (número 1)", "fim"],
)
def test_o_2010_do_directions_aponta_para_o_numero_atual_da_paragem_na_rota_gravada(sessao, ors_falso, indice, mensagem):
    """Correção "T3.22": o Directions vai pela ordem do VROOM (C, B), que
    ainda não está gravada; a coordenada 1 é a C, que no ecrã é a paragem 2,
    e a coordenada 2 é a B, a paragem 1."""
    cliente = sessao()
    antes = _gravadas(cliente.base)
    ors_falso.direcoes(*reversed(_erro_2010(indice)))
    r = _otimizar(cliente)
    assert (r.status_code, r.json()) == (503, _indisponivel("ponto_sem_estrada", mensagem))
    assert ors_falso.caminhos() == [CAMINHO_VROOM, CAMINHO_DIRECOES]
    _nada_muda(cliente, antes)


def test_o_2010_numa_paragem_sem_numero_atual_da_a_mensagem_geral(sessao, ors_falso):
    """A C estava `nao_cabe` (sem número no ecrã) e o VROOM pô-la em primeiro:
    a coordenada 1 não tem número que se possa dizer."""
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(por_paragem={PARAGEM_C: {"nao_cabe": True}}))
    ors_falso.direcoes(*reversed(_erro_2010(1)))
    r = _otimizar(cliente)
    assert (r.status_code, r.json()) == (503, _indisponivel("ponto_sem_estrada", GERAL))
    ors_falso.direcoes(*reversed(_erro_2010(2)))
    assert _otimizar(cliente).json() == _indisponivel("ponto_sem_estrada", _paragem_sem_estrada(1))


def test_o_2010_com_a_fechada_mantida_e_a_fixture_gravada(sessao, ors_falso):
    """Com a A mantida (número 3 na rota gravada) e o VROOM a pô-la em
    primeiro ([3, 1, 2]): a coordenada 1 é a paragem 3; a fixture
    `direcoes-erro-2010.json` (coordenada 2) é a B, a paragem 1."""
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(por_paragem={PARAGEM_A: {"manter_fechada": True}}))
    ors_falso.vroom(_otimizacao([3, 1, 2]))
    ors_falso.direcoes(*reversed(_erro_2010(1)))
    assert _otimizar(cliente).json() == _indisponivel("ponto_sem_estrada", _paragem_sem_estrada(3))
    ors_falso.direcoes(_fixture("direcoes-erro-2010.json"), estado=404)
    assert _otimizar(cliente).json() == _indisponivel("ponto_sem_estrada", _paragem_sem_estrada(1))
    ors_falso.direcoes(*reversed(_erro_2010(4)))
    assert _otimizar(cliente).json() == _indisponivel("ponto_sem_estrada", FIM_SEM_ESTRADA)


def test_um_2010_com_um_indice_fora_dos_pontos_e_indisponivel(sessao, ors_falso):
    cliente = sessao()
    ors_falso.direcoes(*reversed(_erro_2010(9)))
    r = _otimizar(cliente)
    assert (r.status_code, r.json()) == (503, _indisponivel("indisponivel"))


@pytest.mark.parametrize(
    "preparar, motivo",
    [
        (lambda falso: falso.vroom(_fixture("erro-429.json"), estado=429), "estado HTTP 429"),
        (lambda falso: falso.vroom(_otimizacao([3, 1])), "a otimização falou de um job que não foi enviado"),
        (lambda falso: falso.vroom({"code": 3, "error": "Unfound route(s) from location [-9.15,38.7253]"}, estado=400), "estado HTTP 400"),
        (lambda falso: falso.vroom(excecao=lambda p: httpx.ReadTimeout("lento", request=p)), "sem resposta (ReadTimeout)"),
        (lambda falso: falso.direcoes({"error": "x"}, estado=500), "estado HTTP 500"),
        (lambda falso: falso.direcoes(*reversed(_erro_2010(1))), "estado HTTP 404 (código 2010)"),
        (lambda falso: falso.direcoes({"routes": []}), "o Directions não trouxe a rota"),
    ],
    ids=["VROOM 429", "VROOM job desconhecido", "VROOM erro 3", "VROOM rede", "Directions 500", "Directions 2010", "Directions forma errada"],
)
def test_a_falha_fica_no_registo_sem_coordenadas_nem_a_chave(sessao, ors_falso, caplog, preparar, motivo):
    cliente = sessao()
    preparar(ors_falso)
    with caplog.at_level(logging.DEBUG), caplog.at_level(logging.DEBUG, logger="httpx"), caplog.at_level(
        logging.DEBUG, logger="httpcore"
    ):
        assert _otimizar(cliente).status_code == 503
    avisos = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert [(r.name, r.getMessage()) for r in avisos] == [
        ("crm.rotas", f"[crm] rota {AMANHA}: o openrouteservice falhou (otimizar) — {motivo}"),
    ]
    for segredo in (CHAVE, "Pastelaria", LOJA_B, PARAGEM_B, *COORDENADAS_CANARIAS):
        assert segredo not in caplog.text
        for registo in caplog.records:
            assert segredo not in str(registo.args)


def test_sem_chave_tambem_fica_no_registo(sessao, ors_falso, monkeypatch, caplog):
    monkeypatch.delenv(ors.VARIAVEL_CHAVE)
    cliente = sessao()
    with caplog.at_level(logging.DEBUG):
        assert _otimizar(cliente).status_code == 503
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == [
        f"[crm] rota {AMANHA}: o openrouteservice falhou (otimizar) — sem chave",
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
        ({"versao": "3"}, {"versao": VERSAO_OBRIGATORIA}),
        ({"versao": 3.0}, {"versao": VERSAO_OBRIGATORIA}),
        ({"versao": True}, {"versao": VERSAO_OBRIGATORIA}),
        ({"versao": [3]}, {"versao": VERSAO_OBRIGATORIA}),
    ],
    ids=["sem versão", "null", "0", "texto", "decimal", "bool", "lista"],
)
def test_um_corpo_sem_a_versao_da_422_sem_tocar_na_base(sessao, ors_falso, corpo, campos):
    cliente = sessao()
    r = cliente.post(_url(), json=corpo)
    assert (r.status_code, r.json()) == (422, _validacao(campos))
    assert cliente.base.crm_rotas.registo == [] and cliente.base.crm_lojas.registo == []
    assert ors_falso.pedidos == []


def test_as_outras_chaves_do_corpo_ignoram_se(sessao, ors_falso):
    r = _otimizar(sessao(), ordem="x", hora_saida=5, paragens=[])
    assert r.status_code == 200, r.text


@pytest.mark.parametrize(
    "data, mensagem",
    [("abc", DATA), ("2026-1-1", DATA), ("2026-13-01", DATA), ("2028-01-01", HORIZONTE), ("2027-10-14", HORIZONTE)],
    ids=["abc", "sem zeros", "mês 13", "2028", "hoje + 366"],
)
def test_uma_data_errada_da_422_sem_tocar_na_base(sessao, ors_falso, data, mensagem):
    cliente = sessao()
    r = _otimizar(cliente, data=data)
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
    r = _otimizar(cliente, data=data, versao=1)
    assert (r.status_code, r.json()) == (404, SEM_ROTA)
    assert cliente.base.crm_rotas.registo == [("find_one", {"data": data}, SEM_ID)]
    assert cliente.base.crm_lojas.registo == [] and cliente.base.crm_definicoes.registo == []
    assert ors_falso.pedidos == []


def test_ontem_com_rota_da_rota_fechada_sem_escrever(sessao, ors_falso):
    base = _base(rotas=[_rota(ONTEM, _tres_paragens())], lojas=_lojas())
    cliente = sessao(ZE_UTILIZADOR, base)
    antes = _gravadas(base)
    r = _otimizar(cliente, data=ONTEM)
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
    r = _otimizar(cliente)
    assert (r.status_code, r.json()) == (409, ROTA_EM_CURSO)
    _nada_muda(cliente, antes)
    assert ors_falso.pedidos == []


def test_rota_em_curso_ganha_ao_conflito(sessao):
    base = _base(rotas=[_rota(AMANHA, [_feita(PARAGEM_B, LOJA_B, 0)])], lojas=_lojas())
    r = _otimizar(sessao(ZE_UTILIZADOR, base), versao=99)
    assert (r.status_code, r.json()) == (409, ROTA_EM_CURSO)


@pytest.mark.parametrize("versao", [1, 2, 4, 99], ids=["1", "2", "4", "99"])
def test_uma_versao_diferente_da_conflito_sem_ler_mais_nada(sessao, ors_falso, versao):
    cliente = sessao()
    antes = _gravadas(cliente.base)
    r = _otimizar(cliente, versao=versao)
    assert (r.status_code, r.json()) == (409, CONFLITO)
    assert [c[0] for c in cliente.base.crm_rotas.registo] == ["find_one"]
    assert cliente.base.crm_lojas.registo == [] and cliente.base.crm_definicoes.registo == []
    assert ors_falso.pedidos == []
    _nada_muda(cliente, antes)


# --- A escrita que não casa: `porque_falhou`, sem tentar outra vez ----------------------------------


def test_outra_pessoa_a_gravar_entre_a_leitura_e_a_escrita_da_conflito(sessao, ors_falso):
    """Os dois pedidos saíram, mas a versão subiu entretanto: 409 `conflito`,
    uma só tentativa, nada do escritório fica escrito."""
    base = _base_com_tres()

    def outra_pessoa(docs):
        docs[0]["versao"] += 1

    base.crm_rotas.antes_de("find_one_and_update", outra_pessoa)
    cliente = sessao(ZE_UTILIZADOR, base)
    r = _otimizar(cliente)
    assert (r.status_code, r.json()) == (409, CONFLITO)
    assert [c[0] for c in base.crm_rotas.registo] == ["find_one", "find_one_and_update", "find_one"]
    assert base.crm_rotas.registo[2][1:] == ({"id": "r-1"}, SEM_CALCULO)  # o porque_falhou
    assert ors_falso.caminhos() == [CAMINHO_VROOM, CAMINHO_DIRECOES]
    assert _gravadas(base) == [_rota(AMANHA, _tres_paragens(), versao=4)]


def test_um_recalculo_entre_a_leitura_e_a_escrita_da_conflito(sessao, ors_falso):
    """Correção "F3-INT-1": outra pessoa recalcula enquanto o VROOM e o
    Directions respondem (as horas da C fora de horário e um `calculo`, a
    versão igual). O `$set` do otimizar foi montado por diferença contra a
    rota lida e já não casa: 409 `conflito`, e fica o recálculo tal e qual —
    nunca as horas dele debaixo do cálculo do otimizar."""
    base = _base_com_tres()

    def outra_pessoa_recalcula(docs):
        docs[0]["paragens"][3].update(HORAS_VELHAS)
        docs[0]["calculo"] = deepcopy(CALCULO_VELHO)

    base.crm_rotas.antes_de("find_one_and_update", outra_pessoa_recalcula)
    r = _otimizar(sessao(ZE_UTILIZADOR, base))
    assert (r.status_code, r.json()) == (409, CONFLITO)
    assert [c[0] for c in base.crm_rotas.registo] == ["find_one", "find_one_and_update", "find_one"]
    assert base.crm_rotas.registo[1][1] == FILTRO_DE_ESCRITA
    assert ors_falso.caminhos() == [CAMINHO_VROOM, CAMINHO_DIRECOES]
    assert _gravadas(base) == [
        _rota(AMANHA, _tres_paragens(**{PARAGEM_C: HORAS_VELHAS}), calculo=CALCULO_VELHO),
    ]


def test_o_motorista_a_registar_entre_a_leitura_e_a_escrita_da_rota_em_curso(sessao, ors_falso):
    base = _base_com_tres()

    def motorista(docs):
        docs[0]["paragens"][1]["estado"] = "feita"

    base.crm_rotas.antes_de("find_one_and_update", motorista)
    cliente = sessao(ZE_UTILIZADOR, base)
    r = _otimizar(cliente)
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
    r = _otimizar(cliente)
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
    """Um só instante por pedido: o "hoje" da validação, o `calculado_em`, o
    `atualizado_em` e o `hoje` da resposta são do mesmo `relogio.agora()`."""
    cliente = sessao()
    leituras = []

    def _agora():
        leituras.append(1)
        return AGORA

    monkeypatch.setattr(relogio, "agora", _agora)
    r, rota = _ok(cliente)
    assert len(leituras) == 1
    assert (rota["calculo"]["calculado_em"], rota["atualizado_em"], r.json()["hoje"]) == (AGORA_INSTANTE, AGORA_CARIMBO, HOJE)


def test_todas_as_escritas_passam_no_terreno_e_nos_instantes(sessao, ors_falso):
    """Uma sequência real (otimizar, retirar a C pelo PATCH, otimizar outra
    vez só com a B): cada `find_one_and_update` passa em `escritas_no_terreno`
    e em `instantes_fora_do_formato`; as do otimizar têm só `$set` e `$inc`
    (nunca `$push`, `$pull` nem `$unset`) e os caminhos são só dos campos do
    escritório, por índice."""
    cliente = sessao()
    _ok(cliente)
    assert cliente.patch(ROTAS_URL + f"/{AMANHA}", json={"versao": 4, "retirar": [PARAGEM_C]}).status_code == 200
    pontos = [FABRICA_PADRAO, MARQUES, FABRICA_PADRAO]
    ors_falso.vroom(_otimizacao([1]))
    ors_falso.direcoes(_direcoes([600, 600], [1000.0, 1000.0], pontos))
    r, rota = _ok(cliente, versao=5)
    escritas = _escritas(cliente.base)
    assert [e[0] for e in escritas] == ["find_one_and_update"] * 3
    for escrita in escritas:
        assert escritas_no_terreno(escrita[2]) == []
        assert instantes_fora_do_formato(escrita[2]) == []
    for escrita in (escritas[0], escritas[2]):
        assert set(escrita[2]) == {"$set", "$inc"}
        assert escrita[2]["$inc"] == {"versao": 1}
        caminhos = [caminho for caminho in escrita[2]["$set"] if caminho.startswith("paragens.")]
        assert all(caminho.split(".")[2] in dominio_rotas.CAMPOS_DO_ESCRITORIO for caminho in caminhos)
        assert all(len(caminho.split(".")) == 3 and caminho.split(".")[1].isdigit() for caminho in caminhos)
    # Depois do PATCH a B já está em 0: só as horas (iguais) e o calculo; a C retirada não se toca.
    assert ors_falso.corpos()[2] == _pedido_vroom([PARAGEM_B])
    assert escritas[2] == _escrita(
        {"calculo": _calculo(rota, _lojas(), pontos, 2000, 1200, "08:35"), "paragens.1.chegada_prevista": "08:10"},
        versao=5, autoria=_autoria(2), calculo=escritas[0][2]["$set"]["calculo"],
    )
    assert instantes_fora_do_formato(_gravadas(cliente.base)) == []
    assert (rota["versao"], r.json()["calculo"]["atual"], [p["numero"] for p in r.json()["paragens"]]) == (6, True, [1, None])
    assert all((p["estado"], p["resultado"], p["concluida_em"]) == ("pendente", None, None) for p in rota["paragens"])
    assert rota["paragens"][3]["removida_em"] is not None and rota["paragens"][3]["chegada_prevista"] == "08:20"


def test_a_resposta_nao_leva_dados_pessoais_nem_a_assinatura(sessao, ors_falso):
    r, _ = _ok(sessao())
    for pessoal in ("Rua Secreta", "não sai na rota", "Sr. Silva", "assinatura", '"_id"'):
        assert pessoal not in r.text


def test_depois_do_otimizar_um_patch_torna_as_horas_velhas_e_o_recalcular_repoe_as(sessao, ors_falso):
    """`calculo.atual` segue a assinatura: mudar a saída pelo PATCH deixa as
    horas com `atual: false`; o recalcular (sem subir a versão) refaz as horas
    pela ordem que o otimizar gravou."""
    cliente = sessao()
    _ok(cliente)
    r = cliente.patch(ROTAS_URL + f"/{AMANHA}", json={"versao": 4, "hora_saida": "07:00"})
    assert (r.status_code, r.json()["versao"], r.json()["calculo"]["atual"]) == (200, 5, False)
    r = cliente.post(ROTAS_URL + f"/{AMANHA}/recalcular", json={"versao": 5})
    assert (r.status_code, r.json()["versao"], r.json()["calculo"]["atual"]) == (200, 5, True)
    assert ors_falso.caminhos() == [CAMINHO_VROOM, CAMINHO_DIRECOES, CAMINHO_DIRECOES]
    assert ors_falso.corpos()[2] == pedido_direcoes(PONTOS, False)  # a ordem C, B gravada pelo otimizar
    assert [(p["id"], p["chegada_prevista"]) for p in r.json()["paragens"]][:2] == [(PARAGEM_C, "07:20"), (PARAGEM_B, "09:30")]


# --- Quem entra -----------------------------------------------------------------------------------


def test_o_escritorio_otimiza(sessao, ors_falso):
    for pessoa, autor in ((ADMIN_MASTER, "u-admin"), (ANA_ADMIN_DO_CRM, "u-ana"), (ZE_UTILIZADOR, ZE)):
        cliente = sessao(pessoa)
        r, rota = _ok(cliente)
        assert (r.json()["calculo"]["atual"], rota["atualizado_por"], rota["versao"]) == (True, autor, 4)


def test_o_motorista_recebe_403_sem_permissao(sessao, ors_falso):
    cliente = sessao(ALVARO_MOTORISTA)
    r = _otimizar(cliente)
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)
    assert cliente.base.crm_rotas.registo == [] and ors_falso.pedidos == []


def test_quem_nao_e_membro_recebe_403_sem_acesso_crm(sessao, ors_falso):
    cliente = sessao(BEA_NAO_MEMBRO)
    r = _otimizar(cliente)
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

SEGREDO = "segredo-de-teste-crm-rotas-otimizar"
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


def test_de_ponta_a_ponta_o_escritorio_otimiza_e_o_dia_mostra_a_ordem_nova(portal, ors_falso):
    ze = _cabecalho(ZE, email="ze@example.com")
    admin = _cabecalho("u-admin", email=ADMIN_LOCAL, role="admin")

    r = portal.post(_url(), json={"versao": 3}, headers=_cabecalho("u-alv", email="alvaro@example.com"))
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)
    r = portal.post(_url(), json={"versao": 3}, headers=_cabecalho("u-bea", email="bea@example.com"))
    assert (r.status_code, r.json()) == (403, SEM_ACESSO)
    assert portal.base.crm_rotas.registo == [] and ors_falso.pedidos == []

    r = portal.post(_url(), json={"versao": 3}, headers=ze)
    assert r.status_code == 200, r.text
    assert (r.json()["versao"], r.json()["calculo"]["atual"], r.json()["calculo"]["regresso_previsto"]) == (4, True, "09:55")
    assert [(p["id"], p["chegada_prevista"]) for p in r.json()["paragens"]] == [(PARAGEM_C, "08:20"), (PARAGEM_B, "09:30"), (PARAGEM_A, None)]
    assert portal.get(ROTAS_URL + f"/{AMANHA}", headers=admin).json() == r.json()

    # A versão subiu: um pedido com a 3 já não casa; com a 4 "Guardar rota" segue.
    r = portal.post(_url(), json={"versao": 3}, headers=admin)
    assert (r.status_code, r.json()) == (409, CONFLITO)
    r = portal.patch(ROTAS_URL + f"/{AMANHA}", json={"versao": 4, "estado": "planeada"}, headers=admin)
    assert (r.status_code, r.json()["versao"], r.json()["calculo"]["atual"]) == (200, 5, True)
    r = portal.post(_url(ONTEM), json={"versao": 1}, headers=admin)
    assert (r.status_code, r.json()) == (404, SEM_ROTA)
    assert ors_falso.caminhos() == [CAMINHO_VROOM, CAMINHO_DIRECOES]
    assert all(escritas_no_terreno(e[2]) == [] for e in _escritas(portal.base))
