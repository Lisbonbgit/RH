"""`GET /api/crm/rotas/{data}/sugestoes` — as lojas para aproveitar a viagem
(plano F3 §1 "Sugestões" e §4; T3.23).

As regras das sugestões estão provadas no domínio (`dominio.sugestoes`, T3.9:
o raio de 5 km, o corredor de 3 km, as fases, os dias fechados, a ordem e o
limite de 30). Aqui prova-se a rota HTTP: quem entra, o 422 da `data`, o que
lê (o filtro e a projeção exatos no registo do duplo: as lojas de todas as
sugestões **nunca** trazem o telefone), o que passa ao domínio (as lojas das
paragens ativas, os ids das paragens ativas, o dia da rota) e quando a linha
da rota conta.

- **Sem rota, ou sem paragens ativas com loja** → `{"sem_paragens": true,
  "no_caminho": false, "grupos": []}`, sem ler as lojas nem as definições.
- **Com paragens:** `rotas_bd.lojas_da_rota` (a `PROJECAO_LOJA_ROTA`, para a
  distância e para a assinatura do cálculo) e depois todas as lojas pela
  projeção exata `{"_id": 0, "id", "nome", "fase", "lat", "lng",
  "dias_fechada"}`; os ids das paragens ativas (também as fechadas, as
  `nao_cabe` e as sem loja) nunca se sugerem; uma paragem retirada já não
  conta e a loja dela volta a ser sugerida.
- **Corredor:** só com `calculo.atual` — a mesma conta do `rota_api`
  (a assinatura gravada é a de `entrada_calculo(rota, secção "rota" pela
  ordem, início e fim resolvidos pelas definições em vigor)` — a geometria
  descodificada vai ao domínio e `no_caminho` é verdadeiro; com um cálculo
  velho, ou sem cálculo, não (e sem cálculo nem se leem as definições).
- **Só leitura:** uma rota passada e uma rota com registo do motorista
  respondem na mesma; nunca se escreve e o relógio lê-se uma vez.
- Só o escritório; um GET sem corpo.

Molde do test_rotas_ler.py (T3.18) e do test_rotas_recalcular.py (T3.21).
"""
import math
import time
from datetime import date, datetime, timezone

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import crm
import crm.db
import faturacao.auth
from crm import relogio
from crm import rotas as rotas_http
from crm.auth import ESCRITORIO, membro_crm_atual
from crm.dominio import polilinha
from crm.dominio import rotas as dominio_rotas
from crm.dominio import sugestoes as dominio_sugestoes
from crm.dominio.geo import METROS_POR_GRAU, distancia_metros
from crm.dominio.horarios import assinatura, entrada_calculo
from crm.formatar_rota import PROJECAO_LOJA_ROTA, rota_api
from crm.pedidos import corpo_json
from faturacao.auth import utilizador_atual

from .duplos import BaseFalsa

ROTAS_URL = "/api/crm/rotas"
CAMINHO = ROTAS_URL + "/{data}/sugestoes"
ADMIN_LOCAL = "admin.local@example.com"

UTC = timezone.utc
# 23:30Z de 12 de outubro de 2026: em Lisboa (WEST, UTC+1) já é dia 13.
AGORA = datetime(2026, 10, 12, 23, 30, 15, 987654, tzinfo=UTC)
AGORA_INSTANTE = "2026-10-12T23:30:15Z"
HOJE = "2026-10-13"  # uma terça-feira
ONTEM = "2026-10-12"  # uma segunda-feira
AMANHA = "2026-10-14"  # uma quarta-feira
ULTIMO_DIA = "2027-10-13"  # hoje + 365
DEPOIS_DO_ULTIMO = "2027-10-14"

MEMBRO = "membro-1"
ZE = "u-ze"
LOJA_A = "00000000-0000-4000-8000-00000000000a"
LOJA_B = "00000000-0000-4000-8000-00000000000b"
LOJA_C = "00000000-0000-4000-8000-00000000000c"
LOJA_D = "00000000-0000-4000-8000-00000000000d"
LOJA_E = "00000000-0000-4000-8000-00000000000e"
LOJA_F = "00000000-0000-4000-8000-00000000000f"
LOJA_AGUA = "00000000-0000-4000-8000-000000000010"
LOJA_G = "00000000-0000-4000-8000-000000000011"
LOJA_G2 = "00000000-0000-4000-8000-000000000012"
LOJA_H = "00000000-0000-4000-8000-000000000013"
LOJA_I = "00000000-0000-4000-8000-000000000014"
LOJA_J = "00000000-0000-4000-8000-000000000015"
LOJA_K = "00000000-0000-4000-8000-000000000016"
LOJA_L = "00000000-0000-4000-8000-000000000017"
LOJA_M = "00000000-0000-4000-8000-000000000018"
LOJA_N = "00000000-0000-4000-8000-000000000019"

PARAGEM_A = "10000000-0000-4000-8000-00000000000a"
PARAGEM_B = "10000000-0000-4000-8000-00000000000b"
PARAGEM_C = "10000000-0000-4000-8000-00000000000c"
PARAGEM_D = "10000000-0000-4000-8000-00000000000d"  # retirada

COMERCIO = (38.7075, -9.1364)
MARQUES = (38.7253, -9.15)
BELEM = (38.6979, -9.2065)
FABRICA_PADRAO = (38.7223, -9.1393)
OUTRA_FABRICA = (38.75, -9.2)
PORTO = (41.1579, -8.6291)
OUTRO_PONTO = {"lat": 38.6, "lng": -9.1}


def _deslocar(ponto, norte_m=0.0, este_m=0.0):
    """O ponto `norte_m` metros para norte e `este_m` para este (negativos: sul e oeste)."""
    lat, lng = ponto
    return (lat + norte_m / METROS_POR_GRAU, lng + este_m / (METROS_POR_GRAU * math.cos(math.radians(lat))))


PERTO_DE_A = _deslocar(COMERCIO, norte_m=400)
# A linha da rota com um desvio a 10 km a oeste de Belém; a N fica 2 km a sul
# desse vértice: a 2000 m da linha e a mais de 10 km de qualquer paragem.
VERTICE = _deslocar(BELEM, este_m=-10000)
LINHA = [FABRICA_PADRAO, MARQUES, VERTICE, BELEM, FABRICA_PADRAO]
NO_CAMINHO = _deslocar(VERTICE, norte_m=-2000)

# A projeção exata das lojas das sugestões (plano, T3.23): nunca o telefone.
PROJECAO_SUGESTAO = {"_id": 0, "id": 1, "nome": 1, "fase": 1, "lat": 1, "lng": 1, "dias_fechada": 1}
CHAVES_DA_SUGESTAO = ["id", "nome", "fase", "lat", "lng", "distancia_m", "no_caminho"]
CHAVES_DA_RESPOSTA = ["sem_paragens", "no_caminho", "grupos"]
SEM_PARAGENS = {"sem_paragens": True, "no_caminho": False, "grupos": []}

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

DATA = "Indique o dia no formato AAAA-MM-DD."
HORIZONTE = "Escolha um dia até um ano a partir de hoje."

SEM_PERMISSAO = {"detail": {"codigo": "sem_permissao", "mensagem": "Sem permissão para esta ação."}}
SEM_ACESSO = {"detail": {"codigo": "sem_acesso_crm", "mensagem": "Sem acesso ao CRM."}}

SEM_ID = {"_id": 0}
PROJECAO_DEFINICOES = {"_id": 0, "chave": 1, "valor": 1}

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
    return f"{ROTAS_URL}/{data}/sugestoes"


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
    """Uma loja da base, com mais campos do que as projeções trazem (o
    telefone, a morada, as notas e a pessoa de contacto nunca saem)."""
    lat, lng = ponto if ponto is not None else (None, None)
    return {
        "id": id_, "nome": nome, "fase": fase, "lat": lat, "lng": lng, "telefone": "+351911111111",
        "janelas": [], "dias_fechada": [], "morada": "Rua Secreta 1", "notas": "não sai nas sugestões",
        "regiao_id": None, "pessoa_contacto": "Sr. Silva", **extra,
    }


def _lojas():
    """As lojas das paragens: a A fecha à quarta (o dia de AMANHA); a D é a da
    paragem retirada, a 400 m da A."""
    return [
        _loja(LOJA_A, "Café A", "contactada", COMERCIO, dias_fechada=["qua"]),
        _loja(LOJA_B, "Pastelaria B", "potencial", MARQUES),
        _loja(LOJA_C, "Mercearia C", "cliente", BELEM, janelas=[{"inicio": "09:00", "fim": "12:00"}]),
        _loja(LOJA_D, "Quiosque D", "potencial", PERTO_DE_A),
    ]


def _vizinhas():
    """As candidatas: cada uma prova uma regra do domínio pela API."""
    return [
        _loja(LOJA_E, "Tabacaria E", "contactada", _deslocar(MARQUES, norte_m=1000)),
        # As duas no mesmo prédio, a 2 km da B: a ordem decide-se pelo nome sem acentos.
        _loja(LOJA_F, "Frutaria F", "potencial", _deslocar(MARQUES, norte_m=2000)),
        _loja(LOJA_AGUA, "Água F", "potencial", _deslocar(MARQUES, norte_m=2000)),
        _loja(LOJA_G, "Garrafeira G", "potencial", _deslocar(BELEM, norte_m=-5000)),  # 5000 m entra
        _loja(LOJA_G2, "Garagem G2", "potencial", _deslocar(BELEM, norte_m=-5001)),  # 5001 m não
        _loja(LOJA_H, "Hortaliça H", "perdida", _deslocar(MARQUES, norte_m=300)),
        _loja(LOJA_I, "Ilha I", "amostra", _deslocar(MARQUES, norte_m=300)),
        _loja(LOJA_J, "Jardim J", "cliente", _deslocar(MARQUES, norte_m=300)),
        _loja(LOJA_K, "Kiosque K", "contactada", _deslocar(COMERCIO, norte_m=500), dias_fechada=["qua"]),
        _loja(LOJA_L, "Loja L", "potencial", None),
        _loja(LOJA_M, "Mercado M", "potencial", PORTO),
        _loja(LOJA_N, "Nova N", "contactada", NO_CAMINHO),
    ]


def _todas():
    return _lojas() + _vizinhas()


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


def _projetada(loja, projecao=PROJECAO_LOJA_ROTA):
    return {campo: loja[campo] for campo in projecao if campo != "_id"}


def _base(rotas=(), lojas=(), definicoes=(), membros=MEMBROS, users=USERS):
    return BaseFalsa({
        "crm_rotas": list(rotas),
        "crm_lojas": list(lojas),
        "crm_definicoes": list(definicoes),
        "crm_membros": list(membros),
        "users": list(users),
    })


def _base_com_tres(lojas=None, por_paragem=None, definicoes=(), **campos_da_rota):
    return _base(
        rotas=[_rota(AMANHA, _tres_paragens(**(por_paragem or {})), **campos_da_rota)],
        lojas=_todas() if lojas is None else lojas,
        definicoes=definicoes,
    )


def _dia(texto):
    return date(*(int(parte) for parte in texto.split("-")))


def _api(rota, lojas, hoje=HOJE, definicoes=None):
    """O `rota_api` desta rota gravada: a referência do `calculo.atual`."""
    return rota_api(
        rota,
        data=_dia(rota["data"]),
        hoje=_dia(hoje),
        lojas=[_projetada(loja) for loja in lojas],
        definicoes=DEFINICOES_PADRAO if definicoes is None else definicoes,
        calculo_disponivel=False,
    )


def _calculo(rota, lojas, pontos=LINHA, inicio=None, fim=None):
    """Um `calculo` gravado cuja assinatura é a da entrada de agora (a rota
    tal como está, só com a secção "rota" pela ordem e os extremos
    resolvidos), com a linha `pontos` codificada."""
    lojas_por_id = {loja["id"]: loja for loja in lojas}
    seccoes = dominio_rotas.seccoes(rota["paragens"], lojas_por_id, _dia(rota["data"]))
    incluidas = [(paragem, loja) for paragem, loja, seccao, _ in seccoes if seccao == "rota"]
    return {
        "assinatura": assinatura(entrada_calculo(rota, incluidas, inicio or pontos[0], fim or pontos[-1])),
        "distancia_m": 23456,
        "duracao_s": 4321,
        "regresso_previsto": "10:30",
        "depois_do_limite": False,
        "geometria": polilinha.codificar(pontos),
        "calculado_em": AGORA_INSTANTE,
    }


def _calculo_velho(pontos=LINHA):
    return {**_calculo(_rota(AMANHA, _tres_paragens()), _lojas(), pontos), "assinatura": "sha256:" + "0" * 64}


def _sugestao(loja, distancia_m, no_caminho=False):
    return {
        "id": loja["id"], "nome": loja["nome"], "fase": loja["fase"], "lat": loja["lat"], "lng": loja["lng"],
        "distancia_m": distancia_m, "no_caminho": no_caminho,
    }


def _por_id(lojas):
    return {loja["id"]: loja for loja in lojas}


def _grupos(resposta):
    """`{fase: [ids]}` e `{fase: mais}` da resposta."""
    return {g["fase"]: [l["id"] for l in g["lojas"]] for g in resposta["grupos"]}


def _rota_http(caminho=CAMINHO, metodo="GET"):
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


def _operacoes(base):
    """As operações feitas em todas as coleções do CRM, sem repetir."""
    return {chamada[0] for nome in ("crm_rotas", "crm_lojas", "crm_definicoes") for chamada in base[nome].registo}


@pytest.fixture
def sessao(monkeypatch):
    """Uma app só com o router do CRM, a sessão do portal trocada por
    `dependency_overrides`, a base do CRM trocada pelo único ponto e o
    relógio parado em AGORA. `sessao(utilizador, base)` devolve o cliente
    (com `cliente.base`)."""
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    monkeypatch.setattr(relogio, "agora", lambda: AGORA)

    def _montar(utilizador=ZE_UTILIZADOR, base=None, levantar=True):
        base = base if base is not None else _base()
        monkeypatch.setattr(crm.db, "obter_db", lambda: base)
        app = FastAPI()
        app.include_router(crm.router)
        app.dependency_overrides[utilizador_atual] = lambda: dict(utilizador)
        cliente = TestClient(app, raise_server_exceptions=levantar)
        cliente.base = base
        return cliente

    return _montar


# --- A rota: onde está, quem a guarda e o que não lê ---------------------------------------------


def test_a_rota_existe_e_vive_em_crm_rotas():
    rota = _rota_http()
    assert rota.methods == {"GET"}
    assert rota.endpoint.__module__ == rotas_http.__name__ == "crm.rotas"


def test_so_o_escritorio_pede_sugestoes():
    """Exatamente uma guarda de perfil, a do escritório, sobre `membro_crm_atual`."""
    dependencias = _dependencias(_rota_http())
    assert membro_crm_atual in dependencias
    assert [d for d in dependencias if hasattr(d, "perfis_crm")] == [ESCRITORIO]


def test_as_sugestoes_nao_leem_o_corpo():
    assert corpo_json not in _dependencias(_rota_http())


# --- A data ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "data, mensagem",
    [
        ("2026-1-5", DATA),
        ("14-10-2026", DATA),
        ("2026-10-14T00:00", DATA),
        ("amanha", DATA),
        ("2026-02-30", DATA),
        (DEPOIS_DO_ULTIMO, HORIZONTE),
        ("2030-01-01", HORIZONTE),
    ],
)
def test_uma_data_errada_da_422_sem_tocar_na_base(sessao, data, mensagem):
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres())
    r = cliente.get(_url(data))
    assert (r.status_code, r.json()) == (422, _validacao({"data": mensagem}))
    assert _operacoes(cliente.base) == set()


def test_o_ultimo_dia_que_se_le_e_hoje_mais_365(sessao):
    r = sessao().get(_url(ULTIMO_DIA))
    assert (r.status_code, r.json()) == (200, SEM_PARAGENS)


def test_o_hoje_e_o_dia_em_lisboa_do_relogio(sessao, monkeypatch):
    """Às 23:30Z de 12/10 (WEST) o horizonte conta-se a partir do dia 13:
    2027-10-13 ainda se lê; no inverno (UTC) o mesmo instante é o dia 12."""
    assert sessao().get(_url(ULTIMO_DIA)).status_code == 200
    monkeypatch.setattr(relogio, "agora", lambda: datetime(2026, 12, 12, 23, 30, tzinfo=UTC))
    r = sessao().get(_url("2027-12-13"))
    assert (r.status_code, r.json()) == (422, _validacao({"data": HORIZONTE}))
    assert sessao().get(_url("2027-12-12")).status_code == 200


# --- Sem paragens ----------------------------------------------------------------------------------


def test_um_dia_sem_rota_nao_tem_paragens_e_so_le_a_rota(sessao):
    cliente = sessao(ZE_UTILIZADOR, _base(lojas=_todas()))
    r = cliente.get(_url(AMANHA))
    assert (r.status_code, r.json()) == (200, SEM_PARAGENS)
    assert list(r.json()) == CHAVES_DA_RESPOSTA
    assert cliente.base.crm_rotas.registo == [("find_one", {"data": AMANHA}, SEM_ID)]
    assert cliente.base.crm_lojas.registo == []
    assert cliente.base.crm_definicoes.registo == []


def test_um_dia_passado_sem_rota_tambem_responde_sem_paragens(sessao):
    r = sessao(ZE_UTILIZADOR, _base(lojas=_todas())).get(_url(ONTEM))
    assert (r.status_code, r.json()) == (200, SEM_PARAGENS)


def test_uma_rota_so_com_paragens_retiradas_nao_tem_paragens_e_nao_le_as_lojas(sessao):
    rota = _rota(AMANHA, [_retirada(PARAGEM_B, LOJA_B), _retirada(PARAGEM_D, LOJA_D)])
    cliente = sessao(ZE_UTILIZADOR, _base(rotas=[rota], lojas=_todas()))
    r = cliente.get(_url(AMANHA))
    assert (r.status_code, r.json()) == (200, SEM_PARAGENS)
    assert cliente.base.crm_lojas.registo == []
    assert cliente.base.crm_definicoes.registo == []


def test_uma_rota_sem_nenhuma_paragem_nao_tem_paragens(sessao):
    cliente = sessao(ZE_UTILIZADOR, _base(rotas=[_rota(AMANHA, [])], lojas=_todas()))
    assert cliente.get(_url(AMANHA)).json() == SEM_PARAGENS
    assert cliente.base.crm_lojas.registo == []


def test_com_as_lojas_das_paragens_apagadas_nao_ha_paragens_e_as_outras_lojas_nem_se_leem(sessao):
    """As paragens ficam `sem_loja`: lê-se a lista das lojas da rota (vazia)
    e mais nada."""
    sem_as_da_rota = [loja for loja in _todas() if loja["id"] not in (LOJA_A, LOJA_B, LOJA_C)]
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(lojas=sem_as_da_rota))
    r = cliente.get(_url(AMANHA))
    assert (r.status_code, r.json()) == (200, SEM_PARAGENS)
    assert cliente.base.crm_lojas.registo == [
        ("find", {"id": {"$in": [LOJA_B, LOJA_C, LOJA_A]}}, PROJECAO_LOJA_ROTA),
    ]
    assert cliente.base.crm_definicoes.registo == []


def test_com_as_lojas_das_paragens_sem_coordenadas_nao_ha_paragens(sessao):
    """Uma paragem cuja loja não tem coordenadas não serve para medir: é o
    domínio que o decide (a lista das lojas da rota não vem vazia)."""
    lojas = [_loja(LOJA_B, "Pastelaria B", "potencial", None)] + _vizinhas()
    rota = _rota(AMANHA, [_paragem(PARAGEM_B, LOJA_B, 0)])
    r = sessao(ZE_UTILIZADOR, _base(rotas=[rota], lojas=lojas)).get(_url(AMANHA))
    assert (r.status_code, r.json()) == (200, SEM_PARAGENS)


# --- Com paragens: o que se lê e o que se passa ao domínio ----------------------------------------


def test_le_a_rota_as_lojas_da_rota_e_todas_as_lojas_pela_projecao_exata(sessao):
    """Três leituras, por esta ordem: a rota do dia, as lojas das paragens
    ativas (pela ordem das ativas, com a `PROJECAO_LOJA_ROTA`) e todas as
    lojas pela projeção das sugestões; sem cálculo, as definições nem se
    leem."""
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres())
    assert cliente.get(_url(AMANHA)).status_code == 200
    assert cliente.base.crm_rotas.registo == [("find_one", {"data": AMANHA}, SEM_ID)]
    assert cliente.base.crm_lojas.registo == [
        ("find", {"id": {"$in": [LOJA_B, LOJA_C, LOJA_A]}}, PROJECAO_LOJA_ROTA),
        ("find", {}, PROJECAO_SUGESTAO),
    ]
    assert cliente.base.crm_definicoes.registo == []


def test_a_projecao_das_sugestoes_e_exatamente_a_do_plano():
    """`{"_id": 0, "id", "nome", "fase", "lat", "lng", "dias_fechada"}`: nunca o telefone."""
    assert PROJECAO_SUGESTAO == {"_id": 0, "id": 1, "nome": 1, "fase": 1, "lat": 1, "lng": 1, "dias_fechada": 1}
    assert "telefone" not in PROJECAO_SUGESTAO


def test_os_grupos_com_as_regras_do_dominio_pela_api(sessao):
    """A contactada primeiro e depois a potencial; só as fases das duas; a
    fechada à quarta (a K) fica de fora; as da rota (A, B, C) nunca se
    sugerem, a da paragem retirada (D) sim; 5000 m entra e 5001 não; sem
    coordenadas e no Porto ficam de fora; no empate manda o nome sem
    acentos. Sem cálculo não há corredor: a N não entra."""
    lojas = _por_id(_todas())
    r = sessao(ZE_UTILIZADOR, _base_com_tres()).get(_url(AMANHA))
    assert r.status_code == 200, r.text
    assert r.json() == {
        "sem_paragens": False,
        "no_caminho": False,
        "grupos": [
            {"fase": "contactada", "lojas": [_sugestao(lojas[LOJA_E], 1000)], "mais": 0},
            {
                "fase": "potencial",
                "lojas": [
                    _sugestao(lojas[LOJA_D], 400),
                    _sugestao(lojas[LOJA_AGUA], 2000),
                    _sugestao(lojas[LOJA_F], 2000),
                    _sugestao(lojas[LOJA_G], 5000),
                ],
                "mais": 0,
            },
        ],
    }
    assert all(list(sugestao) == CHAVES_DA_SUGESTAO for grupo in r.json()["grupos"] for sugestao in grupo["lojas"])


def test_nunca_saem_o_telefone_a_morada_as_notas_nem_a_pessoa_de_contacto(sessao):
    r = sessao(ZE_UTILIZADOR, _base_com_tres()).get(_url(AMANHA))
    assert r.status_code == 200
    for segredo in ("+351911111111", "telefone", "Rua Secreta", "morada", "notas", "Sr. Silva", "pessoa_contacto"):
        assert segredo not in r.text


def test_a_distancia_e_a_minima_a_qualquer_paragem_ativa_tambem_a_fechada(sessao):
    """A D está a 400 m da A, que é uma paragem fechada neste dia: conta na
    mesma como paragem (as lojas da rota são as de todas as ativas)."""
    r = sessao(ZE_UTILIZADOR, _base_com_tres()).get(_url(AMANHA))
    potencial = {l["id"]: l["distancia_m"] for l in r.json()["grupos"][1]["lojas"]}
    assert potencial[LOJA_D] == 400
    a_b = int(round(distancia_metros(*PERTO_DE_A, *MARQUES)))
    assert a_b > 400


def test_uma_paragem_nao_cabe_conta_como_paragem_e_nao_se_sugere(sessao):
    """A B com `nao_cabe: true` continua ativa: a E a 1 km dela entra com
    1000 m e a B nunca aparece."""
    r = sessao(ZE_UTILIZADOR, _base_com_tres(por_paragem={PARAGEM_B: {"nao_cabe": True}})).get(_url(AMANHA))
    assert r.status_code == 200
    assert _grupos(r.json()) == {"contactada": [LOJA_E], "potencial": [LOJA_D, LOJA_AGUA, LOJA_F, LOJA_G]}
    assert r.json()["grupos"][0]["lojas"][0]["distancia_m"] == 1000


def test_uma_fechada_com_manter_conta_como_paragem_e_nao_se_sugere(sessao):
    r = sessao(ZE_UTILIZADOR, _base_com_tres(por_paragem={PARAGEM_A: {"manter_fechada": True}})).get(_url(AMANHA))
    assert _grupos(r.json()) == {"contactada": [LOJA_E], "potencial": [LOJA_D, LOJA_AGUA, LOJA_F, LOJA_G]}


def test_a_loja_de_uma_paragem_retirada_volta_a_ser_sugerida_e_ja_nao_mede(sessao):
    """Com a B retirada, só a C e a A medem: a E (a 1 km da B) fica a mais de
    2 km da A e a B volta a ser sugerida (a 1,8 km da A, dentro do raio)."""
    r = sessao(ZE_UTILIZADOR, _base_com_tres(por_paragem={PARAGEM_B: {"removida_em": "2026-10-11T10:00:00Z", "ordem": None}})).get(_url(AMANHA))
    assert r.status_code == 200
    grupos = _grupos(r.json())
    assert LOJA_B in grupos["potencial"]
    e = next(l for l in r.json()["grupos"][0]["lojas"] if l["id"] == LOJA_E)
    assert e["distancia_m"] == int(round(min(
        distancia_metros(*_deslocar(MARQUES, norte_m=1000), *COMERCIO),
        distancia_metros(*_deslocar(MARQUES, norte_m=1000), *BELEM),
    )))
    assert e["distancia_m"] > 1000


def test_uma_paragem_com_a_loja_apagada_nao_mede_e_as_outras_sim(sessao):
    """A C apagada: a paragem é `sem_loja`; mede-se à A e à B e a G (a 5 km
    da C) já não entra."""
    sem_c = [loja for loja in _todas() if loja["id"] != LOJA_C]
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(lojas=sem_c))
    r = cliente.get(_url(AMANHA))
    assert r.status_code == 200
    assert _grupos(r.json()) == {"contactada": [LOJA_E], "potencial": [LOJA_D, LOJA_AGUA, LOJA_F]}
    assert cliente.base.crm_lojas.registo[0] == ("find", {"id": {"$in": [LOJA_B, LOJA_C, LOJA_A]}}, PROJECAO_LOJA_ROTA)


def test_a_fechada_e_pelo_dia_da_rota_e_nao_pelo_de_hoje(sessao):
    """A K fecha à quarta: fora da rota de AMANHA (quarta), dentro da rota de
    HOJE (terça), a 500 m da A."""
    rota_de_hoje = _rota(HOJE, _tres_paragens())
    r = sessao(ZE_UTILIZADOR, _base(rotas=[rota_de_hoje], lojas=_todas())).get(_url(HOJE))
    assert r.status_code == 200
    contactada = r.json()["grupos"][0]["lojas"]
    assert [(l["id"], l["distancia_m"]) for l in contactada] == [(LOJA_K, 500), (LOJA_E, 1000)]
    # E a A, que fecha à quarta, é à terça uma paragem normal: continua a não se sugerir.
    assert LOJA_A not in _grupos(r.json())["contactada"]


def test_uma_rota_passada_tambem_da_sugestoes(sessao):
    """Ler não é escrever: a rota de ONTEM (segunda, só de leitura) responde
    com as suas sugestões, pelo dia dela (a K, fechada à quarta, entra)."""
    rota = _rota(ONTEM, _tres_paragens(), estado="planeada")
    r = sessao(ZE_UTILIZADOR, _base(rotas=[rota], lojas=_todas())).get(_url(ONTEM))
    assert r.status_code == 200, r.text
    assert _grupos(r.json()) == {"contactada": [LOJA_K, LOJA_E], "potencial": [LOJA_D, LOJA_AGUA, LOJA_F, LOJA_G]}


def test_uma_rota_com_registo_do_motorista_tambem_da_sugestoes(sessao):
    r = sessao(ZE_UTILIZADOR, _base_com_tres(por_paragem={PARAGEM_B: _feita(PARAGEM_B, LOJA_B, 0)})).get(_url(AMANHA))
    assert r.status_code == 200
    assert _grupos(r.json())["contactada"] == [LOJA_E]


def test_uma_paragem_reposta_pelo_terreno_com_ordem_nula_le_se(sessao):
    """Contrato da F4 (correção "T3.3 / T3.16"): uma paragem com `ordem`
    nula e `removida_em` nula é ativa e conta."""
    r = sessao(ZE_UTILIZADOR, _base_com_tres(por_paragem={PARAGEM_B: {"ordem": None, "estado": "feita"}})).get(_url(AMANHA))
    assert r.status_code == 200
    assert _grupos(r.json())["contactada"] == [LOJA_E]


def test_o_limite_e_30_por_grupo_com_o_mais(sessao):
    """35 potenciais a 100, 200, … 3500 m da B: as 30 mais perto, pela
    distância, e `mais: 5`; a contactada vazia com `mais: 0`."""
    muitas = [
        _loja(f"00000000-0000-4000-8000-0000000001{n:02d}", f"Loja {n:02d}", "potencial", _deslocar(MARQUES, norte_m=100 * n))
        for n in range(1, 36)
    ]
    rota = _rota(AMANHA, [_paragem(PARAGEM_B, LOJA_B, 0)])
    r = sessao(ZE_UTILIZADOR, _base(rotas=[rota], lojas=_lojas()[1:2] + muitas)).get(_url(AMANHA))
    assert r.status_code == 200
    contactada, potencial = r.json()["grupos"]
    assert contactada == {"fase": "contactada", "lojas": [], "mais": 0}
    assert [l["distancia_m"] for l in potencial["lojas"]] == [100 * n for n in range(1, 31)]
    assert (len(potencial["lojas"]), potencial["mais"]) == (30, 5)


def test_a_resposta_e_a_do_dominio_com_as_lojas_projetadas(sessao):
    """A ligação, de ponta a ponta: as lojas de todas pela projeção das
    sugestões, as da rota pela `PROJECAO_LOJA_ROTA`, os ids das ativas, o
    dia da rota e nenhuma linha."""
    r = sessao(ZE_UTILIZADOR, _base_com_tres()).get(_url(AMANHA))
    assert r.json() == dominio_sugestoes.sugerir(
        [_projetada(loja, PROJECAO_SUGESTAO) for loja in _todas()],
        [_projetada(loja) for loja in _lojas()[:3]],
        [LOJA_B, LOJA_C, LOJA_A],
        _dia(AMANHA),
        None,
    )


def test_as_coordenadas_saem_como_estao_na_base(sessao):
    lojas = _lojas() + [_loja(LOJA_E, "Tabacaria E", "contactada", (38, -9)), ]
    lojas[-1]["lat"], lojas[-1]["lng"] = 38.7343, -9.15  # ~1 km a norte da B, em float
    r = sessao(ZE_UTILIZADOR, _base_com_tres(lojas=lojas)).get(_url(AMANHA))
    e = r.json()["grupos"][0]["lojas"][0]
    assert (e["lat"], e["lng"]) == (38.7343, -9.15)


# --- O corredor: só com calculo.atual ------------------------------------------------------------


def test_com_o_calculo_atual_a_linha_conta_e_a_n_entra_no_caminho(sessao):
    """A N está a 2 km do vértice da linha e a mais de 10 km de qualquer
    paragem: entra pelo corredor, com a distância à linha. A E, perto pelos
    dois lados, fica com a distância à B e `no_caminho: false`. Lê-se também
    as definições, para resolver a fábrica da assinatura."""
    rota = _rota(AMANHA, _tres_paragens())
    rota["calculo"] = _calculo(rota, _lojas())
    cliente = sessao(ZE_UTILIZADOR, _base(rotas=[rota], lojas=_todas()))
    r = cliente.get(_url(AMANHA))
    assert r.status_code == 200, r.text
    assert _api(rota, _lojas())["calculo"]["atual"] is True
    lojas = _por_id(_todas())
    assert r.json()["no_caminho"] is True
    assert r.json()["grupos"][0] == {
        "fase": "contactada",
        "lojas": [_sugestao(lojas[LOJA_E], 1000), _sugestao(lojas[LOJA_N], 2000, no_caminho=True)],
        "mais": 0,
    }
    assert _grupos(r.json())["potencial"] == [LOJA_D, LOJA_AGUA, LOJA_F, LOJA_G]
    assert cliente.base.crm_definicoes.registo == [("find", {}, PROJECAO_DEFINICOES)]
    assert cliente.base.crm_lojas.registo == [
        ("find", {"id": {"$in": [LOJA_B, LOJA_C, LOJA_A]}}, PROJECAO_LOJA_ROTA),
        ("find", {}, PROJECAO_SUGESTAO),
    ]


def test_com_o_calculo_velho_a_linha_nao_conta(sessao):
    """A assinatura gravada não é a de agora: a N fica de fora e
    `no_caminho` é falso, embora as definições se leiam para o saber."""
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(calculo=_calculo_velho()))
    r = cliente.get(_url(AMANHA))
    assert r.status_code == 200
    assert r.json()["no_caminho"] is False
    assert _grupos(r.json()) == {"contactada": [LOJA_E], "potencial": [LOJA_D, LOJA_AGUA, LOJA_F, LOJA_G]}
    assert cliente.base.crm_definicoes.registo == [("find", {}, PROJECAO_DEFINICOES)]


def test_com_o_calculo_atual_e_ninguem_no_caminho_no_caminho_e_verdadeiro(sessao):
    rota = _rota(AMANHA, _tres_paragens())
    rota["calculo"] = _calculo(rota, _lojas())
    sem_n = [loja for loja in _todas() if loja["id"] != LOJA_N]
    r = sessao(ZE_UTILIZADOR, _base(rotas=[rota], lojas=sem_n)).get(_url(AMANHA))
    assert r.json()["no_caminho"] is True
    assert _grupos(r.json()) == {"contactada": [LOJA_E], "potencial": [LOJA_D, LOJA_AGUA, LOJA_F, LOJA_G]}


def test_a_linha_e_a_geometria_gravada_descodificada(sessao):
    """É a geometria lida que decide: sem o desvio a oeste, a N já não está no
    caminho; com um desvio a 10 km a norte do Marquês, uma loja 2,5 km a
    este desse vértice entra pelo corredor com 2500 m."""
    rota = _rota(AMANHA, _tres_paragens())
    rota["calculo"] = _calculo(rota, _lojas(), pontos=[FABRICA_PADRAO, MARQUES, BELEM, FABRICA_PADRAO])
    r = sessao(ZE_UTILIZADOR, _base(rotas=[rota], lojas=_todas())).get(_url(AMANHA))
    assert r.json()["no_caminho"] is True
    assert LOJA_N not in _grupos(r.json())["contactada"]

    vertice_norte = _deslocar(MARQUES, norte_m=10000)
    rota["calculo"] = _calculo(rota, _lojas(), pontos=[FABRICA_PADRAO, MARQUES, vertice_norte, BELEM, FABRICA_PADRAO])
    perto_da_linha = _loja(LOJA_N, "Nova N", "contactada", _deslocar(vertice_norte, este_m=2500))
    lojas = [loja for loja in _todas() if loja["id"] != LOJA_N] + [perto_da_linha]
    r = sessao(ZE_UTILIZADOR, _base(rotas=[rota], lojas=lojas)).get(_url(AMANHA))
    n = next(l for l in r.json()["grupos"][0]["lojas"] if l["id"] == LOJA_N)
    assert (n["no_caminho"], n["distancia_m"]) == (True, 2500)


def _rota_com_calculo(definicoes=None, inicio=None, fim=None, por_paragem=None, lojas=None, **campos):
    """Uma rota com um `calculo` atual para a rota e as definições dadas; o
    que se muda a seguir (`campos`) torna-o velho ou não."""
    rota = _rota(AMANHA, _tres_paragens(**(por_paragem or {})), inicio=inicio, fim=fim)
    definicoes = definicoes or DEFINICOES_PADRAO
    pontos_inicio = (inicio["lat"], inicio["lng"]) if inicio else (definicoes["fabrica_lat"], definicoes["fabrica_lng"])
    pontos_fim = (fim["lat"], fim["lng"]) if fim else (definicoes["fabrica_lat"], definicoes["fabrica_lng"])
    rota["calculo"] = _calculo(rota, lojas or _lojas(), inicio=pontos_inicio, fim=pontos_fim)
    rota.update(campos)
    return rota


OUTRAS_DEFINICOES = [
    _guardada("fabrica_lat", str(OUTRA_FABRICA[0])),
    _guardada("fabrica_lng", str(OUTRA_FABRICA[1])),
]
DEFINICOES_COM_OUTRA_FABRICA = {**DEFINICOES_PADRAO, "fabrica_lat": OUTRA_FABRICA[0], "fabrica_lng": OUTRA_FABRICA[1]}


def test_a_atualidade_do_calculo_e_a_mesma_conta_do_rota_api(sessao):
    """Mudar a hora de saída, as portagens, o tempo de serviço, "manter" a
    fechada ou pôr uma `nao_cabe` torna o cálculo velho (sem corredor); o
    nome, o telefone, a fase, o motivo, a versão ou o estado não."""
    casos = [
        ({}, True),
        ({"hora_saida": "09:00"}, False),
        ({"hora_regresso_limite": "18:00"}, False),
        ({"evitar_portagens": True}, False),
        ({"versao": 9, "estado": "planeada"}, True),
    ]
    for campos, esperado in casos:
        rota = _rota_com_calculo(**campos)
        r = sessao(ZE_UTILIZADOR, _base(rotas=[rota], lojas=_todas())).get(_url(AMANHA))
        assert r.status_code == 200, (campos, r.text)
        assert _api(rota, _lojas())["calculo"]["atual"] is esperado, campos
        assert r.json()["no_caminho"] is esperado, campos
        assert (LOJA_N in _grupos(r.json())["contactada"]) is esperado, campos


@pytest.mark.parametrize(
    "por_paragem, esperado",
    [
        ({PARAGEM_C: {"tempo_servico_min": 30}}, False),
        ({PARAGEM_A: {"manter_fechada": True}}, False),
        ({PARAGEM_C: {"nao_cabe": True}}, False),
        ({PARAGEM_B: {"ordem": 1}, PARAGEM_C: {"ordem": 0}}, False),
        ({PARAGEM_B: {"motivo": "entrega"}}, True),
        ({PARAGEM_B: {"estado": "feita"}}, True),
    ],
    ids=["tempo", "manter", "nao_cabe", "ordem", "motivo", "feita"],
)
def test_o_que_muda_nas_paragens_depois_do_calculo_decide_o_corredor(sessao, por_paragem, esperado):
    rota = _rota_com_calculo()
    for paragem in rota["paragens"]:
        paragem.update(por_paragem.get(paragem["id"], {}))
    r = sessao(ZE_UTILIZADOR, _base(rotas=[rota], lojas=_todas())).get(_url(AMANHA))
    assert r.status_code == 200
    assert _api(rota, _lojas())["calculo"]["atual"] is esperado
    assert r.json()["no_caminho"] is esperado
    assert (LOJA_N in _grupos(r.json())["contactada"]) is esperado


def test_uma_loja_que_mudou_de_sitio_ou_de_janela_torna_o_calculo_velho(sessao):
    rota = _rota_com_calculo()
    for mudanca in ({"lat": 38.7254}, {"janelas": [{"inicio": "10:00", "fim": "12:00"}]}):
        lojas = _todas()
        _por_id(lojas)[LOJA_B].update(mudanca)
        r = sessao(ZE_UTILIZADOR, _base(rotas=[rota], lojas=lojas)).get(_url(AMANHA))
        assert r.json()["no_caminho"] is False, mudanca
    # O nome, a fase e o telefone não entram na assinatura.
    lojas = _todas()
    _por_id(lojas)[LOJA_B].update({"nome": "Outra B", "fase": "cliente", "telefone": "+351999999999"})
    r = sessao(ZE_UTILIZADOR, _base(rotas=[rota], lojas=lojas)).get(_url(AMANHA))
    assert r.json()["no_caminho"] is True


def test_a_fabrica_das_definicoes_em_vigor_resolve_o_inicio_e_o_fim(sessao):
    """O cálculo feito com a fábrica padrão: com outra fábrica guardada (e
    `inicio`/`fim` nulos) fica velho; feito já com a outra fábrica, é atual.
    As definições são as em vigor, nunca os padrões."""
    rota = _rota_com_calculo()
    r = sessao(ZE_UTILIZADOR, _base(rotas=[rota], lojas=_todas(), definicoes=OUTRAS_DEFINICOES)).get(_url(AMANHA))
    assert r.json()["no_caminho"] is False
    rota = _rota_com_calculo(definicoes=DEFINICOES_COM_OUTRA_FABRICA)
    assert _api(rota, _lojas(), definicoes=DEFINICOES_COM_OUTRA_FABRICA)["calculo"]["atual"] is True
    r = sessao(ZE_UTILIZADOR, _base(rotas=[rota], lojas=_todas(), definicoes=OUTRAS_DEFINICOES)).get(_url(AMANHA))
    assert r.json()["no_caminho"] is True
    r = sessao(ZE_UTILIZADOR, _base(rotas=[rota], lojas=_todas())).get(_url(AMANHA))
    assert r.json()["no_caminho"] is False


def test_com_pontos_proprios_a_fabrica_nao_interessa(sessao):
    rota = _rota_com_calculo(inicio=OUTRO_PONTO, fim={"lat": 38.65, "lng": -9.2})
    r = sessao(ZE_UTILIZADOR, _base(rotas=[rota], lojas=_todas(), definicoes=OUTRAS_DEFINICOES)).get(_url(AMANHA))
    assert r.json()["no_caminho"] is True
    rota["fim"] = None
    r = sessao(ZE_UTILIZADOR, _base(rotas=[rota], lojas=_todas(), definicoes=OUTRAS_DEFINICOES)).get(_url(AMANHA))
    assert r.json()["no_caminho"] is False


def test_sem_calculo_as_definicoes_nem_se_leem(sessao):
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(definicoes=OUTRAS_DEFINICOES))
    assert cliente.get(_url(AMANHA)).json()["no_caminho"] is False
    assert cliente.base.crm_definicoes.registo == []


def test_a_resposta_com_a_linha_e_a_do_dominio(sessao):
    rota = _rota_com_calculo()
    r = sessao(ZE_UTILIZADOR, _base(rotas=[rota], lojas=_todas())).get(_url(AMANHA))
    assert r.json() == dominio_sugestoes.sugerir(
        [_projetada(loja, PROJECAO_SUGESTAO) for loja in _todas()],
        [_projetada(loja) for loja in _lojas()[:3]],
        [LOJA_B, LOJA_C, LOJA_A],
        _dia(AMANHA),
        polilinha.descodificar(rota["calculo"]["geometria"]),
    )


# --- Só leitura ----------------------------------------------------------------------------------


def test_o_relogio_le_se_uma_vez_por_pedido(sessao, monkeypatch):
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(calculo=_calculo_velho()))
    leituras = []

    def _agora():
        leituras.append(1)
        return AGORA

    monkeypatch.setattr(relogio, "agora", _agora)
    assert cliente.get(_url(AMANHA)).status_code == 200
    assert len(leituras) == 1


def test_pedir_sugestoes_nunca_escreve(sessao):
    rota = _rota_com_calculo()
    base = _base(rotas=[rota], lojas=_todas(), definicoes=OUTRAS_DEFINICOES)
    cliente = sessao(ZE_UTILIZADOR, base)
    antes = (base.crm_rotas.sem_id(), base.crm_lojas.sem_id(), base.crm_definicoes.sem_id())
    assert cliente.get(_url(AMANHA)).status_code == 200
    assert _operacoes(base) <= {"find", "find_one"}
    assert (base.crm_rotas.sem_id(), base.crm_lojas.sem_id(), base.crm_definicoes.sem_id()) == antes


# --- Quem entra ----------------------------------------------------------------------------------


def test_o_escritorio_pede_sugestoes(sessao):
    base = _base_com_tres()
    for pessoa in (ADMIN_MASTER, ANA_ADMIN_DO_CRM, ZE_UTILIZADOR):
        r = sessao(pessoa, base).get(_url(AMANHA))
        assert r.status_code == 200
        assert _grupos(r.json())["contactada"] == [LOJA_E]


def test_o_motorista_recebe_403_sem_permissao(sessao):
    cliente = sessao(ALVARO_MOTORISTA, _base_com_tres())
    r = cliente.get(_url(AMANHA))
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)
    assert _operacoes(cliente.base) == set()


def test_quem_nao_e_membro_recebe_403_sem_acesso_crm(sessao):
    cliente = sessao(BEA_NAO_MEMBRO, _base_com_tres())
    r = cliente.get(_url(AMANHA))
    assert (r.status_code, r.json()) == (403, SEM_ACESSO)
    assert _operacoes(cliente.base) == set()


def test_a_guarda_vem_antes_da_data(sessao):
    r = sessao(ALVARO_MOTORISTA, _base_com_tres()).get(_url("amanha"))
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)


# --- De ponta a ponta: a sessão verdadeira do portal ---------------------------------------------

SEGREDO = "segredo-de-teste-crm-rotas-sugestoes"
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
    rota = _rota_com_calculo(estado="planeada")
    base = _base(rotas=[rota], lojas=_todas())
    monkeypatch.setattr(faturacao.auth, "obter_db", lambda: base)
    monkeypatch.setattr(crm.db, "obter_db", lambda: base)
    app = FastAPI()
    app.include_router(crm.router)
    cliente = TestClient(app)
    cliente.base = base
    return cliente


def test_sem_sessao_da_o_403_herdado(portal):
    r = portal.get(_url(AMANHA))
    assert (r.status_code, r.json()) == (403, {"detail": "Not authenticated"})
    assert portal.base.crm_rotas.registo == []


def test_uma_conta_apagada_da_401_sessao_terminada(portal):
    r = portal.get(_url(AMANHA), headers=_cabecalho("u-apagada"))
    assert (r.status_code, r.json()) == (401, {"detail": "Sessão terminada"})
    assert portal.base.crm_rotas.registo == []


def test_de_ponta_a_ponta_o_escritorio_pede_as_sugestoes(portal):
    ze = _cabecalho("u-ze", email="ze@example.com")
    admin = _cabecalho("u-admin", email=ADMIN_LOCAL, role="admin")

    r = portal.get(_url(AMANHA), headers=_cabecalho("u-alv", email="alvaro@example.com"))
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)
    r = portal.get(_url(AMANHA), headers=_cabecalho("u-bea", email="bea@example.com"))
    assert (r.status_code, r.json()) == (403, SEM_ACESSO)

    r = portal.get(_url(AMANHA), headers=ze)
    assert r.status_code == 200, r.text
    resposta = r.json()
    assert (resposta["sem_paragens"], resposta["no_caminho"]) == (False, True)
    assert _grupos(resposta) == {"contactada": [LOJA_E, LOJA_N], "potencial": [LOJA_D, LOJA_AGUA, LOJA_F, LOJA_G]}
    assert portal.get(_url(AMANHA), headers=admin).json() == resposta
    assert "telefone" not in r.text

    r = portal.get(_url(ONTEM), headers=admin)
    assert (r.status_code, r.json()) == (200, SEM_PARAGENS)
    assert _operacoes(portal.base) <= {"find", "find_one"}
