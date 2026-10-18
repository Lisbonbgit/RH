"""`PATCH /api/crm/rotas/{data}` — as definições do dia, a ordem, as paragens,
retirar e "Guardar rota" (plano F3 §1 e §4; T3.20).

As regras estão provadas em baixo: o corpo (`validador_rota.alteracao`, T3.4),
a nova ordem, as secções e os caminhos de escrita (`dominio.rotas`, T3.3), a
forma da resposta (`formatar_rota.rota_api`, T3.16) e a escrita condicional
(`rotas_bd.alterar`/`porque_falhou`, T3.17). Aqui prova-se a rota HTTP: quem
entra, a ordem das verificações do plano §4, o que lê e o que escreve (o
filtro e a atualização exatos no registo do duplo), as corridas e a resposta.

- **Uma só `find_one_and_update`** com o filtro de guarda (a versão recebida,
  um estado editável, nenhum registo do motorista), o `$set` dos campos que
  mudam e o `$inc` da versão. O que já está gravado com o mesmo valor não se
  escreve; sem nada a mudar (também um PATCH só com a `versao`), 200 sem
  escrever e sem subir a versão.
- **Cada campo:** as horas (a coerência vê-se sobre os valores juntos com os
  guardados, só quando o pedido traz uma hora); `inicio`/`fim` como ponto ou
  `null` (a fábrica); `evitar_portagens`; a `ordem` leniente (as ativas em
  falta vão para o fim, pela ordem delas); `paragens.<id>.motivo` sem tempo
  → o padrão do motivo novo nas definições em vigor, com tempo → o tempo
  enviado; `manter_fechada`; `nao_cabe: false`; `retirar` → `removida_em` e
  `ordem` nula, com as outras renumeradas 0..k−1 (os ids de `retirar` saem da
  `ordem`: correção "T3.4 / T3.20"); `estado: "planeada"`.
- **Correção "T3.20 / T3.27":** uma escrita que deixe a rota sem paragens
  incluídas (nenhuma na secção "rota") limpa o `calculo` (campo de topo) na
  mesma escrita, se havia um.
- **Recusas, pela ordem do plano §4:** 400 → 422 (`data`, corpo) → 404 "Ainda
  não há rota para este dia." → 409 `rota_fechada` → 409 `rota_em_curso` →
  409 `conflito` → 422 contra a rota (um id que não é de uma paragem ativa,
  em `ordem`, `paragens.<id>` ou `retirar`; a coerência das horas) → a
  escrita → a falha: 404 (a rota apagada) / 409 `conflito` / 409
  `rota_em_curso` (`porque_falhou`, T3.17), sem tentar outra vez.
- O relógio lê-se uma vez por pedido; só o escritório; a guarda antes do
  corpo. Nenhum pedido ao openrouteservice (a guarda do conftest).

Molde do test_rotas_adicionar.py (T3.19).
"""
import time
from copy import deepcopy
from datetime import date, datetime, timezone

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo import ReturnDocument

import crm
import crm.db
import faturacao.auth
from crm import relogio
from crm import rotas as rotas_http
from crm.auth import ESCRITORIO, membro_crm_atual
from crm.dominio import rotas as dominio_rotas
from crm.formatar_rota import PROJECAO_LOJA_ROTA, rota_api
from crm.pedidos import corpo_json
from crm.servicos import ors
from faturacao.auth import utilizador_atual

from .duplos import BaseFalsa
from .formatos import escritas_no_terreno, instantes_fora_do_formato

ROTAS_URL = "/api/crm/rotas"
CAMINHO = ROTAS_URL + "/{data}"
ADMIN_LOCAL = "admin.local@example.com"
JSON = {"Content-Type": "application/json"}

UTC = timezone.utc
# 23:30Z de 12 de outubro de 2026: em Lisboa (WEST, UTC+1) já é dia 13.
AGORA = datetime(2026, 10, 12, 23, 30, 15, 987654, tzinfo=UTC)
AGORA_INSTANTE = "2026-10-12T23:30:15Z"
AGORA_CARIMBO = "2026-10-12T23:30:15.987654Z"
HOJE = "2026-10-13"  # uma terça-feira
ONTEM = "2026-10-12"
AMANHA = "2026-10-14"  # uma quarta-feira
DEPOIS_DO_ULTIMO = "2027-10-14"  # hoje + 366

MEMBRO = "membro-1"
ZE = "u-ze"
LOJA_A = "00000000-0000-4000-8000-00000000000a"
LOJA_B = "00000000-0000-4000-8000-00000000000b"
LOJA_C = "00000000-0000-4000-8000-00000000000c"
LOJA_D = "00000000-0000-4000-8000-00000000000d"

# As paragens têm ids uuid4: o PATCH recebe-os em `ordem`, `paragens` e `retirar`.
PARAGEM_A = "10000000-0000-4000-8000-00000000000a"
PARAGEM_B = "10000000-0000-4000-8000-00000000000b"
PARAGEM_C = "10000000-0000-4000-8000-00000000000c"
PARAGEM_D = "10000000-0000-4000-8000-00000000000d"  # retirada
DESCONHECIDA = "10000000-0000-4000-8000-0000000000ff"
OUTRA_DESCONHECIDA = "10000000-0000-4000-8000-0000000000fe"
# O índice de cada paragem na lista gravada (`_tres_paragens`).
INDICE = {PARAGEM_A: 0, PARAGEM_B: 1, PARAGEM_D: 2, PARAGEM_C: 3}

COMERCIO = (38.7075, -9.1364)
MARQUES = (38.7253, -9.15)
BELEM = (38.6979, -9.2065)
FABRICA_PADRAO = (38.7223, -9.1393)
OUTRO_PONTO = {"lat": 38.6, "lng": -9.1}

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

CALCULO = {
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
ORDEM = "A ordem tem de ser uma lista de paragens, sem repetidas."
ESTADO = "Só se pode marcar a rota como planeada."
NAO_CABE = "Só se pode pôr de volta na rota."
VAI_SER_RETIRADA = "Esta paragem vai ser retirada."
NAO_ESTA_NA_ROTA = "Esta paragem não está na rota."
COERENCIA = "A hora limite de regresso tem de ser depois da hora de saída."

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
    return f"{ROTAS_URL}/{data}"


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


def _lojas():
    # A A fecha à quarta (o dia de AMANHA); as outras abrem todos os dias.
    return [
        _loja(LOJA_A, "Café A", "contactada", COMERCIO, dias_fechada=["qua"]),
        _loja(LOJA_B, "Pastelaria B", "potencial", MARQUES),
        _loja(LOJA_C, "Mercearia C", "cliente", BELEM, janelas=[{"inicio": "09:00", "fim": "12:00"}]),
        _loja(LOJA_D, "Quiosque D", "potencial", (38.71, -9.14)),
    ]


def _tres_paragens():
    # Pela ordem: B (0), C (1) e A (2, fechada à quarta); a D retirada (índice 2 da lista).
    return [
        _paragem(PARAGEM_A, LOJA_A, 2), _paragem(PARAGEM_B, LOJA_B, 0), _retirada(PARAGEM_D, LOJA_D),
        _paragem(PARAGEM_C, LOJA_C, 1),
    ]


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


def _base_com_tres(**campos_da_rota):
    return _base(rotas=[_rota(AMANHA, _tres_paragens(), **campos_da_rota)], lojas=_lojas())


def _dia(texto):
    return date(*(int(parte) for parte in texto.split("-")))


def _api(rota, lojas, hoje=HOJE, definicoes=None, calculo_disponivel=False):
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


def _operacoes(base):
    return {chamada[0] for nome in ("crm_rotas", "crm_lojas", "crm_definicoes") for chamada in base[nome].registo}


def _caminho(id_, campo):
    return f"paragens.{INDICE[id_]}.{campo}"


def _escrita(set_, versao=3, rota_id="r-1"):
    """A única `find_one_and_update` esperada: o filtro de guarda, o `$set`
    dos campos que mudam mais a autoria, e o `$inc` da versão."""
    return (
        "find_one_and_update",
        {**FILTRO_DE_ESCRITA, "id": rota_id, "versao": versao},
        {"$set": {**set_, **AUTORIA}, "$inc": {"versao": 1}},
        SEM_ID,
        False,
        ReturnDocument.AFTER,
    )


def _rota_http(caminho=CAMINHO, metodo="PATCH"):
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


def _alterar(cliente, data=AMANHA, versao=3, **corpo):
    return cliente.patch(_url(data), json={"versao": versao, **corpo})


def _ok(cliente, **corpo):
    """Um PATCH que tem de dar 200; devolve `(resposta, rota gravada)`."""
    r = _alterar(cliente, **corpo)
    assert r.status_code == 200, r.text
    return r, _gravadas(cliente.base)[0]


def _sem_escrever(cliente, **corpo):
    """Um PATCH que dá 200 sem escrever: a rota fica como estava (versão 3)
    e a resposta é a rota lida."""
    antes = _gravadas(cliente.base)
    r = _alterar(cliente, **corpo)
    assert r.status_code == 200, r.text
    assert _escritas(cliente.base) == []
    assert _gravadas(cliente.base) == antes
    assert r.json() == _api(antes[0], _lojas())
    assert r.json()["versao"] == 3
    return r


# --- A rota: onde está, quem a guarda e a ordem das dependências ----------------------------------


def test_a_rota_existe_e_vive_em_crm_rotas():
    rota = _rota_http()
    assert rota.methods == {"PATCH"}
    assert rota.endpoint.__module__ == rotas_http.__name__ == "crm.rotas"
    assert rota.status_code in (None, 200)


def test_so_o_escritorio_altera_e_o_corpo_le_se_depois_da_guarda():
    """Exatamente uma guarda de perfil, a do escritório, sobre
    `membro_crm_atual`; o `corpo_json` depois dela (regra T1.3/T2.15)."""
    dependencias = _dependencias(_rota_http())
    assert membro_crm_atual in dependencias
    assert [d for d in dependencias if hasattr(d, "perfis_crm")] == [ESCRITORIO]
    assert corpo_json in dependencias
    assert dependencias.index(ESCRITORIO) < dependencias.index(corpo_json)


# --- As definições do dia ------------------------------------------------------------------------


def test_a_hora_de_saida_grava_numa_so_escrita_com_a_versao_mais_um(sessao):
    """Uma só `find_one_and_update` com o filtro de guarda, o `$set` do campo
    e da autoria e o `$inc` da versão; a resposta é a rota como ficou."""
    cliente = sessao()
    r, rota = _ok(cliente, hora_saida="07:00")
    assert (rota["hora_saida"], rota["versao"], rota["atualizado_em"], rota["atualizado_por"]) == (
        "07:00", 4, AGORA_CARIMBO, ZE,
    )
    assert rota["paragens"] == _tres_paragens()
    assert _escritas(cliente.base) == [_escrita({"hora_saida": "07:00"})]
    assert r.json() == _api(rota, _lojas())
    assert (r.json()["hora_saida"], r.json()["versao"], r.json()["existe"], r.json()["hoje"]) == ("07:00", 4, True, HOJE)


def test_as_duas_horas_juntas(sessao):
    cliente = sessao()
    r, rota = _ok(cliente, hora_saida="09:30", hora_regresso_limite="20:00")
    assert (rota["hora_saida"], rota["hora_regresso_limite"]) == ("09:30", "20:00")
    assert _escritas(cliente.base) == [_escrita({"hora_saida": "09:30", "hora_regresso_limite": "20:00"})]
    assert (r.json()["hora_saida"], r.json()["hora_regresso_limite"]) == ("09:30", "20:00")


@pytest.mark.parametrize(
    "corpo",
    [
        {"hora_regresso_limite": "08:00"},
        {"hora_regresso_limite": "07:59"},
        {"hora_saida": "19:00"},
        {"hora_saida": "19:30"},
        {"hora_saida": "12:00", "hora_regresso_limite": "12:00"},
        {"hora_saida": "13:00", "hora_regresso_limite": "12:59"},
    ],
    ids=["limite igual à saída guardada", "limite antes da saída guardada", "saída igual ao limite guardado",
         "saída depois do limite guardado", "as duas iguais", "as duas trocadas"],
)
def test_a_coerencia_das_horas_ve_se_com_os_valores_guardados(sessao, corpo):
    """Mudar só uma das horas compara-se com a outra guardada (08:00/19:00):
    422 em `hora_regresso_limite`, sem escrever e sem ler mais nada."""
    cliente = sessao()
    r = _alterar(cliente, **corpo)
    assert (r.status_code, r.json()) == (422, _validacao({"hora_regresso_limite": COERENCIA}))
    assert _escritas(cliente.base) == []
    assert [c[0] for c in cliente.base.crm_rotas.registo] == ["find_one"]
    assert cliente.base.crm_lojas.registo == [] and cliente.base.crm_definicoes.registo == []


@pytest.mark.parametrize(
    "corpo",
    [{"hora_saida": "18:59"}, {"hora_regresso_limite": "08:01"}, {"hora_saida": "20:00", "hora_regresso_limite": "22:00"}],
    ids=["saída um minuto antes do limite", "limite um minuto depois da saída", "as duas, depois do limite guardado"],
)
def test_as_horas_coerentes_entre_si_gravam(sessao, corpo):
    cliente = sessao()
    r, rota = _ok(cliente, **corpo)
    assert {campo: rota[campo] for campo in corpo} == corpo
    assert _escritas(cliente.base) == [_escrita(corpo)]


def test_sem_horas_no_pedido_as_guardadas_nao_se_verificam(sessao):
    """Uma rota com as horas guardadas trocadas (não acontece pela API) ainda
    aceita um PATCH que não toca nas horas."""
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(hora_saida="20:00", hora_regresso_limite="19:00"))
    r, rota = _ok(cliente, evitar_portagens=True)
    assert rota["evitar_portagens"] is True


@pytest.mark.parametrize("campo", ["inicio", "fim"])
def test_o_inicio_e_o_fim_gravam_um_ponto_arredondado_as_6_casas(sessao, campo):
    cliente = sessao()
    r, rota = _ok(cliente, **{campo: {"lat": 38.7223445, "lng": -9.1393005, "nome": "ignorado"}})
    assert rota[campo] == {"lat": 38.722345, "lng": -9.139301}
    assert _escritas(cliente.base) == [_escrita({campo: {"lat": 38.722345, "lng": -9.139301}})]
    assert r.json()[campo] == {"lat": 38.722345, "lng": -9.139301, "fabrica": False}
    outro = "fim" if campo == "inicio" else "inicio"
    assert r.json()[outro] == {"lat": FABRICA_PADRAO[0], "lng": FABRICA_PADRAO[1], "fabrica": True}


@pytest.mark.parametrize("campo", ["inicio", "fim"])
def test_null_no_inicio_ou_no_fim_volta_a_fabrica(sessao, campo):
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(**{campo: OUTRO_PONTO}))
    r, rota = _ok(cliente, **{campo: None})
    assert rota[campo] is None
    assert _escritas(cliente.base) == [_escrita({campo: None})]
    assert r.json()[campo] == {"lat": FABRICA_PADRAO[0], "lng": FABRICA_PADRAO[1], "fabrica": True}


def test_evitar_portagens(sessao):
    cliente = sessao()
    r, rota = _ok(cliente, evitar_portagens=True)
    assert rota["evitar_portagens"] is True
    assert _escritas(cliente.base) == [_escrita({"evitar_portagens": True})]
    assert r.json()["evitar_portagens"] is True
    assert r.json() == _api(rota, _lojas())
    assert all("tolls" in paragem["links"]["google"] for paragem in r.json()["paragens"])


@pytest.mark.parametrize(
    "corpo",
    [
        {"hora_saida": "08:00"},
        {"hora_regresso_limite": "19:00"},
        {"hora_saida": "08:00", "hora_regresso_limite": "19:00"},
        {"inicio": None},
        {"fim": None},
        {"evitar_portagens": False},
    ],
    ids=["saída", "limite", "as duas", "início", "fim", "portagens"],
)
def test_uma_definicao_igual_a_guardada_nao_escreve(sessao, corpo):
    _sem_escrever(sessao(), **corpo)


def test_um_ponto_igual_ao_guardado_nao_escreve(sessao):
    _sem_escrever(sessao(ZE_UTILIZADOR, _base_com_tres(inicio=dict(OUTRO_PONTO))), inicio={"lat": 38.6, "lng": -9.1})


# --- A ordem --------------------------------------------------------------------------------------


def test_a_ordem_completa_reescreve_so_as_posicoes_que_mudam(sessao):
    """[C, A, B]: C 1→0, A 2→1, B 0→2, pelos caminhos `paragens.<índice>.ordem`
    da lista gravada (A é o índice 0, B o 1, C o 3). A resposta numera só a
    secção "rota" (A está fechada à quarta)."""
    cliente = sessao()
    r, rota = _ok(cliente, ordem=[PARAGEM_C, PARAGEM_A, PARAGEM_B])
    assert [(p["id"], p["ordem"]) for p in rota["paragens"]] == [
        (PARAGEM_A, 1), (PARAGEM_B, 2), (PARAGEM_D, None), (PARAGEM_C, 0),
    ]
    assert _escritas(cliente.base) == [_escrita({
        _caminho(PARAGEM_C, "ordem"): 0, _caminho(PARAGEM_A, "ordem"): 1, _caminho(PARAGEM_B, "ordem"): 2,
    })]
    assert r.json() == _api(rota, _lojas())
    assert [(p["id"], p["ordem"], p["numero"], p["seccao"]) for p in r.json()["paragens"]] == [
        (PARAGEM_C, 0, 1, "rota"), (PARAGEM_A, 1, None, "fechada"), (PARAGEM_B, 2, 2, "rota"),
    ]
    assert r.json()["versao"] == 4


def test_a_ordem_parcial_e_leniente_as_ativas_em_falta_vao_para_o_fim_pela_ordem_delas(sessao):
    cliente = sessao()
    r, rota = _ok(cliente, ordem=[PARAGEM_A])
    assert [(p["id"], p["ordem"]) for p in rota["paragens"]] == [
        (PARAGEM_A, 0), (PARAGEM_B, 1), (PARAGEM_D, None), (PARAGEM_C, 2),
    ]
    assert _escritas(cliente.base) == [_escrita({
        _caminho(PARAGEM_A, "ordem"): 0, _caminho(PARAGEM_B, "ordem"): 1, _caminho(PARAGEM_C, "ordem"): 2,
    })]
    assert [p["id"] for p in r.json()["paragens"]] == [PARAGEM_A, PARAGEM_B, PARAGEM_C]


def test_a_ordem_parcial_deixa_quietas_as_posicoes_que_nao_mudam(sessao):
    """[C]: C 1→0 e B 0→1; A fica no 2, por isso não se escreve."""
    cliente = sessao()
    r, rota = _ok(cliente, ordem=[PARAGEM_C])
    assert _escritas(cliente.base) == [_escrita({_caminho(PARAGEM_C, "ordem"): 0, _caminho(PARAGEM_B, "ordem"): 1})]
    assert [p["id"] for p in r.json()["paragens"]] == [PARAGEM_C, PARAGEM_B, PARAGEM_A]


@pytest.mark.parametrize("ordem", [[PARAGEM_B, PARAGEM_C, PARAGEM_A], [PARAGEM_B], [PARAGEM_B, PARAGEM_C], []],
                         ids=["a ordem atual", "só a primeira", "as duas primeiras", "vazia"])
def test_uma_ordem_que_nao_muda_nada_nao_escreve(sessao, ordem):
    _sem_escrever(sessao(), ordem=ordem)


# --- As paragens ----------------------------------------------------------------------------------


def test_mudar_o_motivo_sem_tempo_poe_o_tempo_padrao_do_motivo_novo(sessao):
    """B passa de angariação (15) a entrega: o tempo é o `servico_entrega_min`
    em vigor (10)."""
    cliente = sessao()
    r, rota = _ok(cliente, paragens={PARAGEM_B: {"motivo": "entrega"}})
    paragem = rota["paragens"][INDICE[PARAGEM_B]]
    assert (paragem["motivo"], paragem["tempo_servico_min"]) == ("entrega", 10)
    assert _escritas(cliente.base) == [_escrita({
        _caminho(PARAGEM_B, "motivo"): "entrega", _caminho(PARAGEM_B, "tempo_servico_min"): 10,
    })]
    assert r.json() == _api(rota, _lojas())
    assert (r.json()["paragens"][0]["motivo"], r.json()["paragens"][0]["tempo_servico_min"]) == ("entrega", 10)


def test_o_tempo_padrao_vem_das_definicoes_em_vigor_e_nao_dos_padroes(sessao):
    base = _base(rotas=[_rota(AMANHA, _tres_paragens())], lojas=_lojas(), definicoes=[
        _guardada("servico_entrega_min", "5"), _guardada("servico_acompanhamento_min", "40"),
    ])
    cliente = sessao(ZE_UTILIZADOR, base)
    r, rota = _ok(cliente, paragens={PARAGEM_B: {"motivo": "entrega"}, PARAGEM_C: {"motivo": "acompanhamento"}})
    assert [(p["motivo"], p["tempo_servico_min"]) for p in rota["paragens"]] == [
        ("angariacao", 15), ("entrega", 5), ("angariacao", 15), ("acompanhamento", 40),
    ]
    assert r.json()["paragens"][0]["tempo_servico_min"] == 5


def test_o_tempo_enviado_ganha_ao_padrao_do_motivo_novo(sessao):
    cliente = sessao()
    r, rota = _ok(cliente, paragens={PARAGEM_B: {"motivo": "entrega", "tempo_servico_min": 45}})
    paragem = rota["paragens"][INDICE[PARAGEM_B]]
    assert (paragem["motivo"], paragem["tempo_servico_min"]) == ("entrega", 45)
    assert _escritas(cliente.base) == [_escrita({
        _caminho(PARAGEM_B, "motivo"): "entrega", _caminho(PARAGEM_B, "tempo_servico_min"): 45,
    })]


def test_so_o_tempo(sessao):
    cliente = sessao()
    r, rota = _ok(cliente, paragens={PARAGEM_C: {"tempo_servico_min": 30}})
    assert (rota["paragens"][INDICE[PARAGEM_C]]["motivo"], rota["paragens"][INDICE[PARAGEM_C]]["tempo_servico_min"]) == (
        "angariacao", 30,
    )
    assert _escritas(cliente.base) == [_escrita({_caminho(PARAGEM_C, "tempo_servico_min"): 30})]


def test_o_mesmo_motivo_sem_tempo_nao_mexe_no_tempo_ajustado_a_mao(sessao):
    """B já é angariação com 30 min (ajustado à mão): voltar a enviar o mesmo
    motivo não repõe o padrão (15) nem escreve nada."""
    base = _base_com_tres()
    base.crm_rotas.docs[0]["paragens"][INDICE[PARAGEM_B]]["tempo_servico_min"] = 30
    cliente = sessao(ZE_UTILIZADOR, base)
    _sem_escrever(cliente, paragens={PARAGEM_B: {"motivo": "angariacao"}})
    assert _gravadas(base)[0]["paragens"][INDICE[PARAGEM_B]]["tempo_servico_min"] == 30


def test_um_motivo_novo_cujo_padrao_e_o_tempo_guardado_so_escreve_o_motivo(sessao):
    """B passa de angariação a acompanhamento: o padrão (15) é o que já lá
    está, por isso só o motivo vai no `$set`."""
    cliente = sessao()
    r, rota = _ok(cliente, paragens={PARAGEM_B: {"motivo": "acompanhamento"}})
    assert _escritas(cliente.base) == [_escrita({_caminho(PARAGEM_B, "motivo"): "acompanhamento"})]
    assert rota["paragens"][INDICE[PARAGEM_B]]["tempo_servico_min"] == 15


def test_manter_fechada_poe_a_paragem_fechada_na_rota(sessao):
    """A fecha à quarta: com "Manter" passa à secção "rota", com o número 3."""
    cliente = sessao()
    r, rota = _ok(cliente, paragens={PARAGEM_A: {"manter_fechada": True}})
    assert rota["paragens"][INDICE[PARAGEM_A]]["manter_fechada"] is True
    assert _escritas(cliente.base) == [_escrita({_caminho(PARAGEM_A, "manter_fechada"): True})]
    assert [(p["id"], p["numero"], p["seccao"], p["aviso"]) for p in r.json()["paragens"]] == [
        (PARAGEM_B, 1, "rota", "nenhum"), (PARAGEM_C, 2, "rota", "nenhum"), (PARAGEM_A, 3, "rota", "nenhum"),
    ]
    assert len(r.json()["blocos_google"]) == 1


def test_nao_cabe_falso_poe_a_paragem_de_volta_na_rota(sessao):
    base = _base_com_tres()
    base.crm_rotas.docs[0]["paragens"][INDICE[PARAGEM_C]]["nao_cabe"] = True
    cliente = sessao(ZE_UTILIZADOR, base)
    r, rota = _ok(cliente, paragens={PARAGEM_C: {"nao_cabe": False}})
    assert rota["paragens"][INDICE[PARAGEM_C]]["nao_cabe"] is False
    assert _escritas(base) == [_escrita({_caminho(PARAGEM_C, "nao_cabe"): False})]
    assert [(p["id"], p["seccao"]) for p in r.json()["paragens"]][1] == (PARAGEM_C, "rota")


@pytest.mark.parametrize(
    "alteracoes",
    [{"manter_fechada": False}, {"nao_cabe": False}, {"tempo_servico_min": 15}, {"motivo": "angariacao"}, {}],
    ids=["manter já desligado", "nao_cabe já falso", "o mesmo tempo", "o mesmo motivo", "nada"],
)
def test_uma_alteracao_igual_a_guardada_nao_escreve(sessao, alteracoes):
    _sem_escrever(sessao(), paragens={PARAGEM_A: alteracoes})


def test_varias_paragens_num_so_pedido(sessao):
    cliente = sessao()
    r, rota = _ok(cliente, paragens={
        PARAGEM_A: {"manter_fechada": True, "tempo_servico_min": 20},
        PARAGEM_B: {"motivo": "amostra"},
        PARAGEM_C: {"motivo": "entrega", "tempo_servico_min": 5},
    })
    assert _escritas(cliente.base) == [_escrita({
        _caminho(PARAGEM_A, "manter_fechada"): True, _caminho(PARAGEM_A, "tempo_servico_min"): 20,
        _caminho(PARAGEM_B, "motivo"): "amostra", _caminho(PARAGEM_B, "tempo_servico_min"): 10,
        _caminho(PARAGEM_C, "motivo"): "entrega", _caminho(PARAGEM_C, "tempo_servico_min"): 5,
    })]
    assert r.json() == _api(rota, _lojas())


# --- Retirar --------------------------------------------------------------------------------------


def test_retirar_poe_removida_em_e_ordem_nula_e_renumera_as_outras(sessao):
    """Retirar B (a primeira): `removida_em` de agora e `ordem` nula; C 1→0 e
    A 2→1. A lista não encolhe (nunca há `$pull`); a resposta já não a traz."""
    cliente = sessao()
    r, rota = _ok(cliente, retirar=[PARAGEM_B])
    assert len(rota["paragens"]) == 4
    assert rota["paragens"][INDICE[PARAGEM_B]] == _paragem(PARAGEM_B, LOJA_B, None, removida_em=AGORA_INSTANTE)
    assert [(p["id"], p["ordem"]) for p in rota["paragens"]] == [
        (PARAGEM_A, 1), (PARAGEM_B, None), (PARAGEM_D, None), (PARAGEM_C, 0),
    ]
    assert _escritas(cliente.base) == [_escrita({
        _caminho(PARAGEM_B, "removida_em"): AGORA_INSTANTE, _caminho(PARAGEM_B, "ordem"): None,
        _caminho(PARAGEM_C, "ordem"): 0, _caminho(PARAGEM_A, "ordem"): 1,
    })]
    assert r.json() == _api(rota, _lojas())
    assert [(p["id"], p["numero"]) for p in r.json()["paragens"]] == [(PARAGEM_C, 1), (PARAGEM_A, None)]
    assert r.json()["versao"] == 4


def test_retirar_a_ultima_nao_renumera_nada(sessao):
    cliente = sessao()
    r, rota = _ok(cliente, retirar=[PARAGEM_A])
    assert _escritas(cliente.base) == [_escrita({
        _caminho(PARAGEM_A, "removida_em"): AGORA_INSTANTE, _caminho(PARAGEM_A, "ordem"): None,
    })]
    assert [p["id"] for p in r.json()["paragens"]] == [PARAGEM_B, PARAGEM_C]


def test_retirar_todas(sessao):
    cliente = sessao()
    r, rota = _ok(cliente, retirar=[PARAGEM_A, PARAGEM_B, PARAGEM_C])
    assert all(p["removida_em"] is not None and p["ordem"] is None for p in rota["paragens"])
    assert _escritas(cliente.base) == [_escrita({
        _caminho(PARAGEM_A, "removida_em"): AGORA_INSTANTE, _caminho(PARAGEM_A, "ordem"): None,
        _caminho(PARAGEM_B, "removida_em"): AGORA_INSTANTE, _caminho(PARAGEM_B, "ordem"): None,
        _caminho(PARAGEM_C, "removida_em"): AGORA_INSTANTE, _caminho(PARAGEM_C, "ordem"): None,
    })]
    assert (r.json()["paragens"], r.json()["blocos_google"], r.json()["existe"]) == ([], [], True)


def test_um_id_em_retirar_e_em_ordem_e_retirado_e_a_ordem_segue_sem_ele(sessao):
    """Correção "T3.4 / T3.20": `{ordem: [a, b, c], retirar: [b]}` deixa B com
    `ordem` nula e `removida_em`, e A e C com 0 e 1 (o retirar ganha). Só A
    muda de posição (2→0); C já estava no 1, por isso não se reescreve."""
    cliente = sessao()
    r, rota = _ok(cliente, ordem=[PARAGEM_A, PARAGEM_B, PARAGEM_C], retirar=[PARAGEM_B])
    assert [(p["id"], p["ordem"], p["removida_em"]) for p in rota["paragens"]] == [
        (PARAGEM_A, 0, None), (PARAGEM_B, None, AGORA_INSTANTE), (PARAGEM_D, None, "2026-10-10T10:00:00Z"),
        (PARAGEM_C, 1, None),
    ]
    assert _escritas(cliente.base) == [_escrita({
        _caminho(PARAGEM_B, "removida_em"): AGORA_INSTANTE, _caminho(PARAGEM_B, "ordem"): None,
        _caminho(PARAGEM_A, "ordem"): 0,
    })]
    assert [p["id"] for p in r.json()["paragens"]] == [PARAGEM_A, PARAGEM_C]


def test_retirar_e_ordenar_as_que_ficam(sessao):
    cliente = sessao()
    r, rota = _ok(cliente, ordem=[PARAGEM_C], retirar=[PARAGEM_A])
    assert _escritas(cliente.base) == [_escrita({
        _caminho(PARAGEM_A, "removida_em"): AGORA_INSTANTE, _caminho(PARAGEM_A, "ordem"): None,
        _caminho(PARAGEM_C, "ordem"): 0, _caminho(PARAGEM_B, "ordem"): 1,
    })]
    assert [(p["id"], p["numero"]) for p in r.json()["paragens"]] == [(PARAGEM_C, 1), (PARAGEM_B, 2)]


def test_retirar_vazio_nao_escreve(sessao):
    _sem_escrever(sessao(), retirar=[])


# --- Guardar rota ---------------------------------------------------------------------------------


def test_estado_planeada_grava_e_a_rota_continua_editavel(sessao):
    cliente = sessao()
    r, rota = _ok(cliente, estado="planeada")
    assert rota["estado"] == "planeada"
    assert _escritas(cliente.base) == [_escrita({"estado": "planeada"})]
    assert (r.json()["estado"], r.json()["estado_efetivo"], r.json()["editavel"], r.json()["versao"]) == (
        "planeada", "planeada", True, 4,
    )


def test_uma_rota_ja_planeada_aceita_alteracoes_e_nao_reescreve_o_estado(sessao):
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(estado="planeada"))
    _sem_escrever(cliente, estado="planeada")
    r, rota = _ok(cliente, estado="planeada", hora_saida="07:00")
    assert _escritas(cliente.base) == [_escrita({"hora_saida": "07:00"})]
    assert rota["estado"] == "planeada"


# --- Tudo junto -----------------------------------------------------------------------------------


def test_tudo_num_so_pedido_e_numa_so_escrita(sessao):
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(fim=dict(OUTRO_PONTO)))
    r, rota = _ok(
        cliente,
        hora_saida="07:30", hora_regresso_limite="20:00", inicio={"lat": 38.7, "lng": -9.2}, fim=None,
        evitar_portagens=True, ordem=[PARAGEM_C], paragens={PARAGEM_B: {"motivo": "entrega"}, PARAGEM_C: {"tempo_servico_min": 20}},
        retirar=[PARAGEM_A], estado="planeada",
    )
    assert _escritas(cliente.base) == [_escrita({
        "hora_saida": "07:30", "hora_regresso_limite": "20:00", "inicio": {"lat": 38.7, "lng": -9.2}, "fim": None,
        "evitar_portagens": True, "estado": "planeada",
        _caminho(PARAGEM_B, "motivo"): "entrega", _caminho(PARAGEM_B, "tempo_servico_min"): 10,
        _caminho(PARAGEM_C, "tempo_servico_min"): 20,
        _caminho(PARAGEM_A, "removida_em"): AGORA_INSTANTE, _caminho(PARAGEM_A, "ordem"): None,
        _caminho(PARAGEM_C, "ordem"): 0, _caminho(PARAGEM_B, "ordem"): 1,
    })]
    assert (rota["versao"], rota["estado"], rota["hora_saida"], rota["hora_regresso_limite"]) == (4, "planeada", "07:30", "20:00")
    assert (rota["inicio"], rota["fim"], rota["evitar_portagens"]) == ({"lat": 38.7, "lng": -9.2}, None, True)
    assert r.json() == _api(rota, _lojas())
    assert [(p["id"], p["numero"], p["motivo"], p["tempo_servico_min"]) for p in r.json()["paragens"]] == [
        (PARAGEM_C, 1, "angariacao", 20), (PARAGEM_B, 2, "entrega", 10),
    ]


# --- Correção "T3.20 / T3.27": sem paragens incluídas, o cálculo limpa-se -------------------------


def test_retirar_as_incluidas_limpa_o_calculo_na_mesma_escrita(sessao):
    """Ficam só A (fechada à quarta, sem "Manter"): nenhuma paragem na secção
    "rota", por isso `calculo: None` vai no mesmo `$set` (campo de topo)."""
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(calculo=deepcopy(CALCULO)))
    r, rota = _ok(cliente, retirar=[PARAGEM_B, PARAGEM_C])
    assert rota["calculo"] is None
    assert _escritas(cliente.base) == [_escrita({
        _caminho(PARAGEM_B, "removida_em"): AGORA_INSTANTE, _caminho(PARAGEM_B, "ordem"): None,
        _caminho(PARAGEM_C, "removida_em"): AGORA_INSTANTE, _caminho(PARAGEM_C, "ordem"): None,
        _caminho(PARAGEM_A, "ordem"): 0, "calculo": None,
    })]
    assert r.json()["calculo"] is None
    assert [(p["id"], p["seccao"]) for p in r.json()["paragens"]] == [(PARAGEM_A, "fechada")]


def test_retirar_todas_limpa_o_calculo(sessao):
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(calculo=deepcopy(CALCULO)))
    r, rota = _ok(cliente, retirar=[PARAGEM_A, PARAGEM_B, PARAGEM_C])
    assert rota["calculo"] is None
    assert _escritas(cliente.base)[0][2]["$set"]["calculo"] is None


def test_retirar_uma_e_ficar_uma_incluida_nao_toca_no_calculo(sessao):
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(calculo=deepcopy(CALCULO)))
    r, rota = _ok(cliente, retirar=[PARAGEM_B])
    assert rota["calculo"] == CALCULO
    assert "calculo" not in _escritas(cliente.base)[0][2]["$set"]
    assert r.json()["calculo"] == {"atual": False, **{c: CALCULO[c] for c in CALCULO if c != "assinatura"}}


def test_sem_calculo_gravado_nao_ha_nada_a_limpar(sessao):
    cliente = sessao()
    r, rota = _ok(cliente, retirar=[PARAGEM_A, PARAGEM_B, PARAGEM_C])
    assert "calculo" not in _escritas(cliente.base)[0][2]["$set"]
    assert rota["calculo"] is None


def test_tirar_o_manter_a_unica_incluida_limpa_o_calculo(sessao):
    base = _base(
        rotas=[_rota(AMANHA, [_paragem(PARAGEM_A, LOJA_A, 0, manter_fechada=True)], calculo=deepcopy(CALCULO))],
        lojas=_lojas(),
    )
    cliente = sessao(ZE_UTILIZADOR, base)
    r, rota = _ok(cliente, paragens={PARAGEM_A: {"manter_fechada": False}})
    assert _escritas(base) == [_escrita({_caminho(PARAGEM_A, "manter_fechada"): False, "calculo": None})]
    assert rota["calculo"] is None


def test_qualquer_escrita_numa_rota_sem_incluidas_limpa_um_calculo_que_tenha_ficado(sessao):
    """Só A, fechada e sem "Manter", com um cálculo antigo gravado: mudar as
    portagens limpa-o; um PATCH só com a versão continua a não escrever."""
    base = _base(rotas=[_rota(AMANHA, [_paragem(PARAGEM_A, LOJA_A, 0)], calculo=deepcopy(CALCULO))], lojas=_lojas())
    cliente = sessao(ZE_UTILIZADOR, base)
    r = _alterar(cliente)
    assert (r.status_code, _escritas(base)) == (200, [])
    r, rota = _ok(cliente, evitar_portagens=True)
    assert _escritas(base) == [_escrita({"evitar_portagens": True, "calculo": None})]
    assert rota["calculo"] is None


# --- Sem nada a mudar -----------------------------------------------------------------------------


def test_um_patch_so_com_a_versao_da_200_sem_escrever_e_sem_subir_a_versao(sessao):
    """Lê a rota, as lojas das paragens ativas e as definições (para a
    resposta) e não escreve nada; a resposta é a rota tal como está."""
    cliente = sessao()
    r = _sem_escrever(cliente)
    assert [c[:3] for c in cliente.base.crm_rotas.registo] == [("find_one", {"data": AMANHA}, SEM_ID)]
    assert cliente.base.crm_lojas.registo == [("find", {"id": {"$in": [LOJA_B, LOJA_C, LOJA_A]}}, PROJECAO_LOJA_ROTA)]
    assert cliente.base.crm_definicoes.registo == [("find", {}, PROJECAO_DEFINICOES)]
    assert r.json() == _api(_rota(AMANHA, _tres_paragens()), _lojas())


def test_listas_e_objetos_vazios_tambem_nao_escrevem(sessao):
    _sem_escrever(sessao(), ordem=[], paragens={}, retirar=[])


def test_a_resposta_nao_leva_dados_pessoais_nem_a_assinatura(sessao):
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(calculo=deepcopy(CALCULO)))
    r, _ = _ok(cliente, hora_saida="07:00")
    for pessoal in ("Rua Secreta", "não sai na rota", "Sr. Silva", "assinatura", '"_id"'):
        assert pessoal not in r.text  # ("_id" entre aspas: o "loja_id" contém o texto)


def test_calculo_disponivel_segue_a_chave_do_openrouteservice(sessao, monkeypatch):
    """Com a chave é `true`; sem ela, `false`. Alterar nunca chama o
    openrouteservice (a guarda do conftest falharia)."""
    cliente = sessao()
    monkeypatch.setenv(ors.VARIAVEL_CHAVE, "chave-de-teste")
    r, rota = _ok(cliente, hora_saida="07:00")
    assert r.json()["calculo_disponivel"] is True
    assert r.json() == _api(rota, _lojas(), calculo_disponivel=True)
    monkeypatch.delenv(ors.VARIAVEL_CHAVE)
    r = _alterar(cliente, versao=4)
    assert (r.status_code, r.json()["calculo_disponivel"]) == (200, False)


def test_o_relogio_le_se_uma_vez_por_pedido(sessao, monkeypatch):
    """Um só instante por pedido: o "hoje" da validação, o `removida_em` e o
    `hoje` da resposta são do mesmo `relogio.agora()`."""
    cliente = sessao()
    leituras = []

    def _agora():
        leituras.append(1)
        return AGORA

    monkeypatch.setattr(relogio, "agora", _agora)
    assert _alterar(cliente, retirar=[PARAGEM_B]).status_code == 200
    assert len(leituras) == 1
    leituras.clear()
    assert _alterar(cliente, versao=4).status_code == 200
    assert len(leituras) == 1


def test_le_a_rota_pelo_dia_depois_as_lojas_das_ativas_e_as_definicoes_e_escreve_uma_vez(sessao):
    """A rota pelo texto do dia e sem `_id`; as lojas das paragens ativas pela
    projeção da rota (nunca a morada nem as notas), uma vez; as definições
    uma vez; uma só escrita. A resposta é a rota gravada."""
    cliente = sessao()
    r, rota = _ok(cliente, retirar=[PARAGEM_B], hora_saida="07:00")
    assert [c[0] for c in cliente.base.crm_rotas.registo] == ["find_one", "find_one_and_update"]
    assert cliente.base.crm_rotas.registo[0][1:] == ({"data": AMANHA}, SEM_ID)
    assert cliente.base.crm_lojas.registo == [("find", {"id": {"$in": [LOJA_B, LOJA_C, LOJA_A]}}, PROJECAO_LOJA_ROTA)]
    assert cliente.base.crm_definicoes.registo == [("find", {}, PROJECAO_DEFINICOES)]
    assert r.json() == _api(rota, _lojas())
    assert [p["loja"]["nome"] for p in r.json()["paragens"]] == ["Mercearia C", "Café A"]


# --- Recusas, pela ordem do plano ----------------------------------------------------------------


@pytest.mark.parametrize(
    "corpo, campos",
    [
        ({}, {"versao": VERSAO_OBRIGATORIA}),
        ({"versao": None}, {"versao": VERSAO_OBRIGATORIA}),
        ({"versao": "3"}, {"versao": VERSAO_OBRIGATORIA}),
        ({"versao": 0}, {"versao": VERSAO_OBRIGATORIA}),
        ({"versao": True}, {"versao": VERSAO_OBRIGATORIA}),
        ({"versao": 3, "ordem": "x"}, {"ordem": ORDEM}),
        ({"versao": 3, "ordem": [PARAGEM_A, PARAGEM_A]}, {"ordem": ORDEM}),
        ({"versao": 3, "estado": "rascunho"}, {"estado": ESTADO}),
        ({"versao": 3, "paragens": {PARAGEM_B: {"nao_cabe": True}}}, {f"paragens.{PARAGEM_B}.nao_cabe": NAO_CABE}),
        ({"versao": 3, "paragens": {PARAGEM_B: {}}, "retirar": [PARAGEM_B]}, {f"paragens.{PARAGEM_B}": VAI_SER_RETIRADA}),
        ({"hora_saida": "", "estado": "x"}, {"versao": VERSAO_OBRIGATORIA, "hora_saida": "Indique a hora.", "estado": ESTADO}),
    ],
    ids=[
        "vazio", "versão nula", "versão em texto", "versão 0", "versão booleana", "ordem em texto", "ordem repetida",
        "estado rascunho", "nao_cabe verdadeiro", "alterar e retirar a mesma", "três errados",
    ],
)
def test_um_corpo_errado_da_422_sem_tocar_na_base(sessao, corpo, campos):
    cliente = sessao()
    r = cliente.patch(_url(), json=corpo)
    assert (r.status_code, r.json()) == (422, _validacao(campos))
    assert list(r.json()["detail"]["campos"]) == list(campos)
    assert _operacoes(cliente.base) == set()


@pytest.mark.parametrize(
    "data, mensagem",
    [("abc", DATA), ("2026-1-1", DATA), ("2026-02-30", DATA), ("2028-01-01", HORIZONTE), (DEPOIS_DO_ULTIMO, HORIZONTE)],
    ids=["abc", "curta", "30-de-fevereiro", "2028", "hoje-mais-366"],
)
def test_uma_data_errada_da_422_sem_tocar_na_base(sessao, data, mensagem):
    cliente = sessao()
    r = _alterar(cliente, data=data)
    assert (r.status_code, r.json()) == (422, _validacao({"data": mensagem}))
    assert _operacoes(cliente.base) == set()


def test_os_erros_da_data_e_do_corpo_vem_juntos_com_a_data_primeiro(sessao):
    r = sessao().patch(_url("abc"), json={"estado": "x"})
    assert (r.status_code, r.json()) == (422, _validacao({"data": DATA, "versao": VERSAO_OBRIGATORIA, "estado": ESTADO}))
    assert list(r.json()["detail"]["campos"]) == ["data", "versao", "estado"]


@pytest.mark.parametrize("corpo", [b"[", b"[1]", b"null", b'"x"', b'{"versao": NaN}'], ids=["[", "lista", "null", "texto", "NaN"])
def test_um_corpo_que_nao_e_um_objeto_json_da_400(sessao, corpo):
    cliente = sessao()
    r = cliente.patch(_url(), content=corpo, headers=JSON)
    assert (r.status_code, r.json()) == (400, JSON_INVALIDO)
    assert _operacoes(cliente.base) == set()


@pytest.mark.parametrize("data", [AMANHA, HOJE, ONTEM], ids=["amanhã", "hoje", "ontem (antes do rota_fechada)"])
def test_um_dia_sem_rota_da_404_sem_ler_mais_nada(sessao, data):
    """Uma rota só nasce com a primeira paragem (`POST .../paragens`): o PATCH
    de um dia sem rota é 404, mesmo num dia já passado (o 404 vem antes do
    `rota_fechada` na ordem do plano)."""
    cliente = sessao(ZE_UTILIZADOR, _base(lojas=_lojas()))
    r = _alterar(cliente, data=data, hora_saida="07:00")
    assert (r.status_code, r.json()) == (404, SEM_ROTA)
    assert [c[:3] for c in cliente.base.crm_rotas.registo] == [("find_one", {"data": data}, SEM_ID)]
    assert cliente.base.crm_lojas.registo == [] and cliente.base.crm_definicoes.registo == []


def test_ontem_com_rota_da_rota_fechada_sem_escrever(sessao):
    base = _base(rotas=[_rota(ONTEM, _tres_paragens())], lojas=_lojas())
    cliente = sessao(ZE_UTILIZADOR, base)
    antes = _gravadas(base)
    r = _alterar(cliente, data=ONTEM, hora_saida="07:00")
    assert (r.status_code, r.json()) == (409, ROTA_FECHADA)
    assert _escritas(base) == []
    assert _gravadas(base) == antes


@pytest.mark.parametrize(
    "paragens, estado",
    [
        ([_paragem(PARAGEM_B, LOJA_B, 0), _feita(PARAGEM_C, LOJA_C, 1)], "rascunho"),
        ([_paragem(PARAGEM_B, LOJA_B, 0, estado="nao_feita")], "planeada"),
        ([_paragem(PARAGEM_B, LOJA_B, 0), _retirada(PARAGEM_C, LOJA_C, estado="feita")], "rascunho"),
        ([_paragem(PARAGEM_B, LOJA_B, 0)], "em_curso"),
        ([_paragem(PARAGEM_B, LOJA_B, 0)], "concluida"),
    ],
    ids=["uma feita", "uma não feita", "uma retirada e feita", "estado em_curso", "estado concluida"],
)
def test_uma_rota_com_registo_do_motorista_da_rota_em_curso_sem_escrever(sessao, paragens, estado):
    base = _base(rotas=[_rota(AMANHA, paragens, estado=estado)], lojas=_lojas())
    cliente = sessao(ZE_UTILIZADOR, base)
    antes = _gravadas(base)
    r = _alterar(cliente, hora_saida="07:00", retirar=[PARAGEM_B])
    assert (r.status_code, r.json()) == (409, ROTA_EM_CURSO)
    assert _escritas(base) == []
    assert _gravadas(base) == antes


def test_rota_em_curso_ganha_ao_conflito(sessao):
    base = _base(rotas=[_rota(AMANHA, [_paragem(PARAGEM_B, LOJA_B, 0), _feita(PARAGEM_C, LOJA_C, 1)])], lojas=_lojas())
    r = _alterar(sessao(ZE_UTILIZADOR, base), versao=1, hora_saida="07:00")
    assert (r.status_code, r.json()) == (409, ROTA_EM_CURSO)


@pytest.mark.parametrize("versao", [1, 2, 4, 99], ids=["1", "2", "4", "99"])
def test_uma_versao_diferente_da_conflito_sem_escrever_nem_ler_mais_nada(sessao, versao):
    cliente = sessao()
    r = _alterar(cliente, versao=versao, hora_saida="07:00")
    assert (r.status_code, r.json()) == (409, CONFLITO)
    assert [c[0] for c in cliente.base.crm_rotas.registo] == ["find_one"]
    assert cliente.base.crm_lojas.registo == [] and cliente.base.crm_definicoes.registo == []
    assert _gravadas(cliente.base) == [_rota(AMANHA, _tres_paragens())]


def test_o_conflito_ganha_ao_422_contra_a_rota(sessao):
    r = _alterar(sessao(), versao=2, ordem=[DESCONHECIDA], hora_regresso_limite="07:00")
    assert (r.status_code, r.json()) == (409, CONFLITO)


@pytest.mark.parametrize(
    "corpo, campos",
    [
        ({"ordem": [DESCONHECIDA]}, {"ordem": NAO_ESTA_NA_ROTA}),
        ({"ordem": [PARAGEM_B, PARAGEM_D]}, {"ordem": NAO_ESTA_NA_ROTA}),
        ({"paragens": {DESCONHECIDA: {}}}, {f"paragens.{DESCONHECIDA}": NAO_ESTA_NA_ROTA}),
        ({"paragens": {PARAGEM_D: {"motivo": "entrega"}}}, {f"paragens.{PARAGEM_D}": NAO_ESTA_NA_ROTA}),
        ({"paragens": {PARAGEM_B: {"motivo": "entrega"}, PARAGEM_D: {}}}, {f"paragens.{PARAGEM_D}": NAO_ESTA_NA_ROTA}),
        ({"retirar": [DESCONHECIDA]}, {"retirar": NAO_ESTA_NA_ROTA}),
        ({"retirar": [PARAGEM_D]}, {"retirar": NAO_ESTA_NA_ROTA}),
        ({"retirar": [PARAGEM_A, PARAGEM_D]}, {"retirar": NAO_ESTA_NA_ROTA}),
        (
            {"hora_regresso_limite": "07:00", "ordem": [DESCONHECIDA], "paragens": {DESCONHECIDA: {}, PARAGEM_D: {}},
             "retirar": [OUTRA_DESCONHECIDA]},
            {"hora_regresso_limite": COERENCIA, "ordem": NAO_ESTA_NA_ROTA, f"paragens.{DESCONHECIDA}": NAO_ESTA_NA_ROTA,
             f"paragens.{PARAGEM_D}": NAO_ESTA_NA_ROTA, "retirar": NAO_ESTA_NA_ROTA},
        ),
    ],
    ids=[
        "ordem com uma desconhecida", "ordem com a retirada", "paragens desconhecida", "paragens retirada",
        "paragens: uma certa e a retirada", "retirar desconhecida", "retirar a já retirada", "retirar uma certa e a retirada",
        "tudo, pela ordem das chaves",
    ],
)
def test_um_id_que_nao_e_de_uma_paragem_ativa_da_422_contra_a_rota(sessao, corpo, campos):
    """"Na rota" quer dizer numa paragem ativa: as retiradas e as desconhecidas
    dão 422 em `ordem`, `paragens.<id>` ou `retirar`, depois de ler a rota
    e sem escrever nem ler mais nada."""
    cliente = sessao()
    r = _alterar(cliente, **corpo)
    assert (r.status_code, r.json()) == (422, _validacao(campos))
    assert list(r.json()["detail"]["campos"]) == list(campos)
    assert [c[0] for c in cliente.base.crm_rotas.registo] == ["find_one"]
    assert cliente.base.crm_lojas.registo == [] and cliente.base.crm_definicoes.registo == []
    assert _gravadas(cliente.base) == [_rota(AMANHA, _tres_paragens())]


# --- A escrita falha ------------------------------------------------------------------------------


def test_outra_pessoa_a_gravar_entre_a_leitura_e_a_escrita_da_conflito_sem_tentar_de_novo(sessao):
    """A escrita condicional não casa (a versão subiu) e `porque_falhou` diz
    `conflito`: 409, uma só tentativa, nada do escritório fica escrito."""
    base = _base_com_tres()

    def outra_pessoa(docs):
        docs[0]["versao"] += 1

    base.crm_rotas.antes_de("find_one_and_update", outra_pessoa)
    cliente = sessao(ZE_UTILIZADOR, base)
    r = _alterar(cliente, hora_saida="07:00", retirar=[PARAGEM_B])
    assert (r.status_code, r.json()) == (409, CONFLITO)
    assert [c[0] for c in base.crm_rotas.registo] == ["find_one", "find_one_and_update", "find_one"]
    assert base.crm_rotas.registo[2][1:] == ({"id": "r-1"}, SEM_CALCULO)  # o porque_falhou
    assert _gravadas(base) == [_rota(AMANHA, _tres_paragens(), versao=4)]


def test_o_motorista_a_registar_entre_a_leitura_e_a_escrita_da_rota_em_curso(sessao):
    base = _base_com_tres()

    def motorista(docs):
        docs[0]["paragens"][1]["estado"] = "feita"

    base.crm_rotas.antes_de("find_one_and_update", motorista)
    cliente = sessao(ZE_UTILIZADOR, base)
    r = _alterar(cliente, ordem=[PARAGEM_C])
    assert (r.status_code, r.json()) == (409, ROTA_EM_CURSO)
    assert [c[0] for c in base.crm_rotas.registo] == ["find_one", "find_one_and_update", "find_one"]
    esperada = _rota(AMANHA, _tres_paragens())
    esperada["paragens"][1]["estado"] = "feita"
    assert _gravadas(base) == [esperada]


def test_a_rota_apagada_entre_a_leitura_e_a_escrita_da_404(sessao):
    base = _base_com_tres()

    def apagada(docs):
        docs.clear()

    base.crm_rotas.antes_de("find_one_and_update", apagada)
    cliente = sessao(ZE_UTILIZADOR, base)
    r = _alterar(cliente, estado="planeada")
    assert (r.status_code, r.json()) == (404, SEM_ROTA)
    assert [c[0] for c in base.crm_rotas.registo] == ["find_one", "find_one_and_update", "find_one"]
    assert _gravadas(base) == []


# --- As escritas passam nos verificadores --------------------------------------------------------


def test_todas_as_escritas_passam_no_terreno_e_nos_instantes(sessao):
    """Uma sequência real (horas, ordem, motivo, manter, retirar, guardar):
    cada `find_one_and_update` registada passa em `escritas_no_terreno` e em
    `instantes_fora_do_formato`, e o documento gravado também."""
    cliente = sessao(ZE_UTILIZADOR, _base_com_tres(calculo=deepcopy(CALCULO)))
    passos = [
        dict(hora_saida="07:00", inicio={"lat": 38.7, "lng": -9.2}),
        dict(ordem=[PARAGEM_C, PARAGEM_B]),
        dict(paragens={PARAGEM_B: {"motivo": "entrega"}, PARAGEM_A: {"manter_fechada": True}}),
        dict(retirar=[PARAGEM_C]),
        dict(retirar=[PARAGEM_B, PARAGEM_A]),
        dict(estado="planeada"),
    ]
    for versao, passo in enumerate(passos, start=3):
        r = _alterar(cliente, versao=versao, **passo)
        assert r.status_code == 200, (passo, r.text)
    escritas = _escritas(cliente.base)
    assert [e[0] for e in escritas] == ["find_one_and_update"] * len(passos)
    for escrita in escritas:
        assert escritas_no_terreno(escrita[2]) == []
        assert instantes_fora_do_formato(escrita[2]) == []
        assert "$push" not in escrita[2] and "$pull" not in escrita[2] and "$unset" not in escrita[2]
    assert instantes_fora_do_formato(_gravadas(cliente.base)) == []
    rota = _gravadas(cliente.base)[0]
    assert (rota["versao"], rota["estado"], rota["calculo"], len(rota["paragens"])) == (9, "planeada", None, 4)
    assert all(p["removida_em"] is not None and p["ordem"] is None for p in rota["paragens"])
    assert all((p["estado"], p["resultado"], p["concluida_em"]) == ("pendente", None, None) for p in rota["paragens"])


def test_o_escritorio_nunca_escreve_os_campos_do_terreno_nem_os_imutaveis_por_caminho(sessao):
    cliente = sessao()
    _ok(cliente, retirar=[PARAGEM_B], paragens={PARAGEM_A: {"motivo": "entrega", "manter_fechada": True}}, ordem=[PARAGEM_A])
    atualizacao = _escritas(cliente.base)[0][2]
    assert set(atualizacao) == {"$set", "$inc"}
    caminhos = [caminho for caminho in atualizacao["$set"] if caminho.startswith("paragens.")]
    assert caminhos
    assert all(caminho.split(".")[2] in dominio_rotas.CAMPOS_DO_ESCRITORIO for caminho in caminhos)
    assert all(len(caminho.split(".")) == 3 and caminho.split(".")[1].isdigit() for caminho in caminhos)


# --- Quem entra -----------------------------------------------------------------------------------


def test_o_escritorio_altera(sessao):
    for pessoa, hora in ((ADMIN_MASTER, "07:00"), (ANA_ADMIN_DO_CRM, "07:15"), (ZE_UTILIZADOR, "07:30")):
        cliente = sessao(pessoa)
        r, rota = _ok(cliente, hora_saida=hora)
        assert (rota["hora_saida"], rota["atualizado_por"]) == (hora, pessoa["user_id"])


def test_o_motorista_recebe_403_sem_permissao(sessao):
    cliente = sessao(ALVARO_MOTORISTA)
    r = _alterar(cliente, hora_saida="07:00")
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)
    assert _operacoes(cliente.base) == set()


def test_quem_nao_e_membro_recebe_403_sem_acesso_crm(sessao):
    cliente = sessao(BEA_NAO_MEMBRO)
    r = _alterar(cliente, hora_saida="07:00")
    assert (r.status_code, r.json()) == (403, SEM_ACESSO)
    assert _operacoes(cliente.base) == set()


@pytest.mark.parametrize(
    "utilizador, esperado", [(ALVARO_MOTORISTA, SEM_PERMISSAO), (BEA_NAO_MEMBRO, SEM_ACESSO)],
    ids=["motorista", "não membro"],
)
def test_sem_perfil_e_com_json_partido_da_403_e_nunca_400(sessao, utilizador, esperado):
    r = sessao(utilizador).patch(_url(), content=b"[", headers=JSON)
    assert (r.status_code, r.json()) == (403, esperado)


# --- De ponta a ponta: a sessão verdadeira do portal ---------------------------------------------

SEGREDO = "segredo-de-teste-crm-rotas-alterar"
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
    r = portal.patch(_url(), json={"versao": 3, "hora_saida": "07:00"})
    assert (r.status_code, r.json()) == (403, {"detail": "Not authenticated"})
    assert portal.base.crm_rotas.registo == []


def test_sem_cabecalho_e_com_json_partido_da_o_403_herdado_e_nunca_400(portal):
    r = portal.patch(_url(), content=b"[", headers=JSON)
    assert (r.status_code, r.json()) == (403, {"detail": "Not authenticated"})
    assert portal.base.users.registo == []
    assert portal.base.crm_rotas.registo == []


def test_uma_conta_apagada_da_401_sessao_terminada(portal):
    r = portal.patch(_url(), json={"versao": 3, "hora_saida": "07:00"}, headers=_cabecalho("u-apagada"))
    assert (r.status_code, r.json()) == (401, {"detail": "Sessão terminada"})
    assert portal.base.crm_rotas.registo == []


def test_de_ponta_a_ponta_o_escritorio_altera_e_o_dia_mostra_a_rota_como_ficou(portal):
    ze = _cabecalho(ZE, email="ze@example.com")
    admin = _cabecalho("u-admin", email=ADMIN_LOCAL, role="admin")

    r = portal.patch(_url(), json={"versao": 3, "ordem": [PARAGEM_C]}, headers=_cabecalho("u-alv", email="alvaro@example.com"))
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)
    r = portal.patch(_url(), json={"versao": 3, "ordem": [PARAGEM_C]}, headers=_cabecalho("u-bea", email="bea@example.com"))
    assert (r.status_code, r.json()) == (403, SEM_ACESSO)
    assert portal.base.crm_rotas.registo == []

    r = portal.patch(_url(), json={"versao": 3, "ordem": [PARAGEM_C]}, headers=ze)
    assert r.status_code == 200, r.text
    assert (r.json()["versao"], [p["loja"]["nome"] for p in r.json()["paragens"]]) == (
        4, ["Mercearia C", "Pastelaria B", "Café A"],
    )
    assert portal.get(_url(), headers=admin).json() == r.json()

    r = portal.patch(_url(), json={"versao": 3, "estado": "planeada"}, headers=admin)
    assert (r.status_code, r.json()) == (409, CONFLITO)
    r = portal.patch(_url(), json={"versao": 4, "retirar": [PARAGEM_B], "estado": "planeada"}, headers=admin)
    assert r.status_code == 200, r.text
    assert (r.json()["versao"], r.json()["estado"], [p["numero"] for p in r.json()["paragens"]]) == (5, "planeada", [1, None])
    assert portal.get(ROTAS_URL, headers=ze).json()["rotas"] == [
        {"id": "r-1", "data": AMANHA, "estado": "planeada", "estado_efetivo": "planeada", "paragens": 2},
    ]
    r = portal.patch(_url(ONTEM), json={"versao": 1, "hora_saida": "07:00"}, headers=admin)
    assert (r.status_code, r.json()) == (404, SEM_ROTA)
    assert all(escritas_no_terreno(e[2]) == [] for e in _escritas(portal.base))
