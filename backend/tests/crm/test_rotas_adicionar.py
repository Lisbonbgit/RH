"""`POST /api/crm/rotas/{data}/paragens` — adicionar uma loja à rota de um
dia (plano F3 §1 e §4; T3.19).

As regras estão provadas em baixo: o corpo (`validador_rota.adicao`, T3.4),
o motivo pela fase e o tempo das definições (`dominio.rotas`, T3.3), a forma
da rota e da paragem novas (`formatar_rota.documento_rota`/
`documento_paragem`, T3.16) e as escritas condicionais (`rotas_bd.criar`/
`acrescentar_paragem`/`alterar`/`porque_falhou`, T3.17). Aqui prova-se a
rota HTTP: quem entra, a ordem das verificações do plano §4, o que lê e o que
escreve (o filtro e a atualização exatos no registo do duplo), as tentativas
sem versão, as corridas e a resposta.

- Sem rota nesse dia, cria-a em `rascunho` (versão 1) já com a primeira
  paragem, numa só `insert_one`; com rota, `$push` da paragem no fim
  (`ordem = n`) com a versão + 1; uma loja retirada antes é **reativada** na
  mesma paragem (o mesmo `id`, pelos caminhos `paragens.<índice>.<campo>`,
  sem `$push`), com o motivo, o tempo e os sinais repostos e as horas a
  `None`. Responde sempre **201** com a rota completa (`rota_api`).
- O motivo vem do corpo ou, em falta, da fase da loja (`motivo_por_fase`); o
  tempo de serviço é sempre o padrão do motivo nas definições em vigor.
- Recusas, pela ordem do plano §4: 400 → 422 (`data`, corpo) → 404 "Loja não
  encontrada." → 409 `rota_fechada` (ontem) → 409 `rota_em_curso` (algum
  registo do motorista, mesmo numa paragem retirada) → 409 `conflito` (só com
  `versao` no corpo) → 409 `ja_na_rota` → 409 `rota_cheia` (48 ativas) → a
  escrita condicional: sem versão tenta até 3 vezes (relê de cada vez) e só
  depois dá 409 `conflito`; se entretanto o motorista registou algo, 409
  `rota_em_curso` sem tentar outra vez (`porque_falhou`, T3.17).
- Duas pessoas a criar a rota do mesmo dia: a segunda `insert_one` falha
  pelo índice único de `data`, volta-se a ler e acrescenta-se (versão 2).
- O relógio lê-se uma vez por pedido (`relogio.agora`): o "hoje" da
  validação, os instantes gravados e o `hoje` da resposta são do mesmo
  instante.
- Só o escritório; a guarda antes do corpo (um `[` sem sessão dá 403, nunca
  400). Nenhum pedido ao openrouteservice (a guarda do conftest).

Molde do test_rotas_ler.py: `TestClient` com `dependency_overrides` e
`monkeypatch.setattr(crm.db, "obter_db", …)` sobre o duplo (`duplos.py`), o
relógio parado e, no fim, a sessão verdadeira do portal.
"""
import asyncio
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
from crm import rotas_bd
from crm.auth import ESCRITORIO, membro_crm_atual
from crm.dominio import rotas as dominio_rotas
from crm.dominio.horarios import assinatura, entrada_calculo
from crm.dominio.ids import e_uuid4
from crm.formatar_rota import PROJECAO_LOJA_ROTA, rota_api
from crm.pedidos import corpo_json
from crm.servicos import ors
from faturacao.auth import utilizador_atual

from .duplos import BaseFalsa, correr
from .formatos import escritas_no_terreno, instantes_fora_do_formato

ROTAS_URL = "/api/crm/rotas"
CAMINHO = ROTAS_URL + "/{data}/paragens"
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
INEXISTENTE = "00000000-0000-4000-8000-0000000000ff"

COMERCIO = (38.7075, -9.1364)
MARQUES = (38.7253, -9.15)
BELEM = (38.6979, -9.2065)
FABRICA_PADRAO = (38.7223, -9.1393)

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

CHAVES_ROTA_API = (
    "id", "data", "existe", "estado", "estado_efetivo", "editavel", "versao", "hoje",
    "hora_saida", "hora_regresso_limite", "evitar_portagens", "inicio", "fim",
    "limite_paragens", "calculo_disponivel", "calculo", "paragens", "blocos_google",
)
CHAVES_ROTA_BASE = (
    "id", "data", "estado", "versao", "hora_saida", "hora_regresso_limite", "inicio", "fim", "evitar_portagens",
    "paragens", "calculo", "criado_em", "criado_por", "atualizado_em", "atualizado_por",
)
CHAVES_PARAGEM_BASE = (
    "id", "loja_id", "ordem", "motivo", "tempo_servico_min", "manter_fechada", "nao_cabe", "chegada_prevista",
    "espera_min", "fora_de_horario", "adicionada_em", "adicionada_por", "removida_em", "estado", "resultado",
    "concluida_em",
)

DATA = "Indique o dia no formato AAAA-MM-DD."
HORIZONTE = "Escolha um dia até um ano a partir de hoje."
LOJA = "Escolha uma loja."
MOTIVO = "Escolha um motivo: entrega, amostra, acompanhamento ou angariação."
VERSAO_INVALIDA = "A versão da rota não é válida."

SEM_PERMISSAO = {"detail": {"codigo": "sem_permissao", "mensagem": "Sem permissão para esta ação."}}
SEM_ACESSO = {"detail": {"codigo": "sem_acesso_crm", "mensagem": "Sem acesso ao CRM."}}
JSON_INVALIDO = {"detail": {"codigo": "json_invalido", "mensagem": "O pedido não é JSON válido."}}
LOJA_NAO_ENCONTRADA = {"detail": {"codigo": "nao_encontrado", "mensagem": "Loja não encontrada."}}
CONFLITO = {"detail": {"codigo": "conflito", "mensagem": "Alterado por outra pessoa — recarregar"}}
JA_NA_ROTA = {"detail": {"codigo": "ja_na_rota", "mensagem": "Esta loja já está na rota deste dia."}}
ROTA_CHEIA = {"detail": {"codigo": "rota_cheia", "mensagem": "Uma rota tem no máximo 48 paragens."}}
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
    return f"{ROTAS_URL}/{data}/paragens"


def _validacao(campos):
    return {"detail": {"codigo": "validacao", "mensagem": "Verifique os campos assinalados.", "campos": campos}}


def _guardada(chave, valor, quando="2026-10-01T08:00:00.000000Z", por="u-ana"):
    return {"chave": chave, "valor": valor, "atualizado_em": quando, "atualizado_por": por}


def _paragem(nome, loja_id, ordem, **campos):
    return {
        "id": f"p-{nome}", "loja_id": loja_id, "ordem": ordem, "motivo": "angariacao", "tempo_servico_min": 15,
        "manter_fechada": False, "nao_cabe": False, "chegada_prevista": None, "espera_min": None,
        "fora_de_horario": False, "adicionada_em": "2026-10-10T09:00:00Z", "adicionada_por": MEMBRO,
        "removida_em": None, "estado": "pendente", "resultado": None, "concluida_em": None, **campos,
    }


def _retirada(nome, loja_id, **campos):
    return _paragem(nome, loja_id, None, removida_em="2026-10-10T10:00:00Z", **campos)


def _feita(nome, loja_id, ordem, **campos):
    return _paragem(
        nome, loja_id, ordem, estado="feita", resultado="interessado", concluida_em="2026-10-13T10:00:00Z", **campos
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
        _loja(LOJA_E, "Padaria E", "amostra", (38.715, -9.145)),
        _loja(LOJA_F, "Talho F", "perdida", (38.712, -9.142)),
    ]


def _loja_em_serie(i):
    """A i-ésima de uma série de lojas, para encher uma rota (ids uuid4 que
    não colidem com os de cima)."""
    return _loja(f"00000000-0000-4000-9000-{i:012x}", f"Loja {i}", "potencial", (38.70 + i * 0.001, -9.14))


def _rota_com_n_ativas(n):
    """Uma rota com `n` paragens ativas (as lojas da série, por ordem) e as lojas dela."""
    lojas = [_loja_em_serie(i) for i in range(n)]
    paragens = [_paragem(f"s{i}", loja["id"], i) for i, loja in enumerate(lojas)]
    return _rota(AMANHA, paragens), lojas


def _tres_paragens():
    # Pela ordem: B (0), C (1) e A (2, fechada à quarta); a D retirada (índice 2 da lista).
    return [_paragem("a", LOJA_A, 2), _paragem("b", LOJA_B, 0), _retirada("d", LOJA_D), _paragem("c", LOJA_C, 1)]


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
    (com `cliente.base`)."""
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    monkeypatch.setattr(relogio, "agora", lambda: AGORA)

    def _montar(utilizador=ZE_UTILIZADOR, base=None, levantar=True):
        base = base if base is not None else _base(lojas=_lojas())
        monkeypatch.setattr(crm.db, "obter_db", lambda: base)
        app = FastAPI()
        app.include_router(crm.router)
        app.dependency_overrides[utilizador_atual] = lambda: dict(utilizador)
        cliente = TestClient(app, raise_server_exceptions=levantar)
        cliente.base = base
        return cliente

    return _montar


def _adicionar(cliente, loja_id=LOJA_A, data=AMANHA, **corpo):
    return cliente.post(_url(data), json={"loja_id": loja_id, **corpo})


# --- A rota: onde está, quem a guarda e a ordem das dependências ----------------------------------


def test_a_rota_existe_e_vive_em_crm_rotas():
    rota = _rota_http()
    assert rota.methods == {"POST"}
    assert rota.endpoint.__module__ == rotas_http.__name__ == "crm.rotas"


def test_o_sucesso_e_201():
    assert _rota_http().status_code == 201


def test_so_o_escritorio_adiciona_e_o_corpo_le_se_depois_da_guarda():
    """Exatamente uma guarda de perfil, a do escritório, sobre
    `membro_crm_atual`; o `corpo_json` depois dela (regra T1.3/T2.15)."""
    dependencias = _dependencias(_rota_http())
    assert membro_crm_atual in dependencias
    assert [d for d in dependencias if hasattr(d, "perfis_crm")] == [ESCRITORIO]
    assert corpo_json in dependencias
    assert dependencias.index(ESCRITORIO) < dependencias.index(corpo_json)


# --- Criar e adicionar ---------------------------------------------------------------------------


def test_sem_rota_cria_a_rota_em_rascunho_com_uma_paragem(sessao):
    """Uma só `insert_one` da rota nova (versão 1, as horas das definições, a
    fábrica como início e fim) já com a paragem: o motivo pela fase
    (contactada → amostra), o tempo das definições (10), `ordem 0`, os
    instantes do relógio parado e o terreno inicial. A resposta é o
    `rota_api` da rota gravada, 201."""
    cliente = sessao()
    r = _adicionar(cliente, LOJA_A)
    assert r.status_code == 201, r.text
    gravadas = _gravadas(cliente.base)
    assert len(gravadas) == 1
    rota = gravadas[0]
    assert tuple(rota) == CHAVES_ROTA_BASE
    assert len(rota["paragens"]) == 1
    paragem = rota["paragens"][0]
    assert tuple(paragem) == CHAVES_PARAGEM_BASE
    assert rota == {
        "id": rota["id"], "data": AMANHA, "estado": "rascunho", "versao": 1, "hora_saida": "08:00",
        "hora_regresso_limite": "19:00", "inicio": None, "fim": None, "evitar_portagens": False,
        "paragens": [paragem], "calculo": None, "criado_em": AGORA_INSTANTE, "criado_por": ZE,
        "atualizado_em": AGORA_CARIMBO, "atualizado_por": ZE,
    }
    assert paragem == {
        "id": paragem["id"], "loja_id": LOJA_A, "ordem": 0, "motivo": "amostra", "tempo_servico_min": 10,
        "manter_fechada": False, "nao_cabe": False, "chegada_prevista": None, "espera_min": None,
        "fora_de_horario": False, "adicionada_em": AGORA_INSTANTE, "adicionada_por": ZE, "removida_em": None,
        "estado": "pendente", "resultado": None, "concluida_em": None,
    }
    assert dominio_rotas.ESTADOS_EDITAVEIS[0] == rota["estado"]
    assert _escritas(cliente.base) == [("insert_one", rota)]
    assert tuple(r.json()) == CHAVES_ROTA_API
    assert r.json() == _api(rota, _lojas())
    assert (r.json()["id"], r.json()["existe"], r.json()["estado"], r.json()["versao"], r.json()["hoje"]) == (
        rota["id"], True, "rascunho", 1, HOJE,
    )


def test_a_rota_nova_leva_as_horas_das_definicoes_guardadas(sessao):
    base = _base(lojas=_lojas(), definicoes=[
        _guardada("rota_hora_saida", "07:30"), _guardada("rota_hora_regresso", "18:00"),
    ])
    r = _adicionar(sessao(ZE_UTILIZADOR, base), LOJA_B)
    assert r.status_code == 201
    rota = _gravadas(base)[0]
    assert (rota["hora_saida"], rota["hora_regresso_limite"]) == ("07:30", "18:00")
    assert (r.json()["hora_saida"], r.json()["hora_regresso_limite"]) == ("07:30", "18:00")


def test_o_id_da_rota_e_o_da_paragem_sao_uuid4_novos(sessao):
    cliente = sessao()
    assert _adicionar(cliente, LOJA_A).status_code == 201
    assert _adicionar(cliente, LOJA_B).status_code == 201
    rota = _gravadas(cliente.base)[0]
    ids = [rota["id"]] + [p["id"] for p in rota["paragens"]]
    assert len(set(ids)) == 3
    assert all(e_uuid4(id_) for id_ in ids)


@pytest.mark.parametrize(
    "loja_id, motivo, minutos",
    [
        (LOJA_B, "angariacao", 15),
        (LOJA_A, "amostra", 10),
        (LOJA_E, "acompanhamento", 15),
        (LOJA_C, "acompanhamento", 15),
        (LOJA_F, "angariacao", 15),
    ],
    ids=["potencial", "contactada", "amostra", "cliente", "perdida"],
)
def test_o_motivo_por_omissao_vem_da_fase_e_o_tempo_do_motivo_nas_definicoes(sessao, loja_id, motivo, minutos):
    cliente = sessao()
    r = _adicionar(cliente, loja_id)
    assert r.status_code == 201
    paragem = _gravadas(cliente.base)[0]["paragens"][0]
    assert (paragem["motivo"], paragem["tempo_servico_min"]) == (motivo, minutos)
    assert (r.json()["paragens"][0]["motivo"], r.json()["paragens"][0]["tempo_servico_min"]) == (motivo, minutos)


def test_motivo_nulo_no_corpo_vale_o_da_fase(sessao):
    cliente = sessao()
    assert _adicionar(cliente, LOJA_A, motivo=None).status_code == 201
    assert _gravadas(cliente.base)[0]["paragens"][0]["motivo"] == "amostra"


@pytest.mark.parametrize(
    "motivo, minutos",
    [("entrega", 10), ("amostra", 10), ("acompanhamento", 15), ("angariacao", 15)],
    ids=["entrega", "amostra", "acompanhamento", "angariacao"],
)
def test_o_motivo_enviado_ganha_a_fase_e_o_tempo_segue_o_motivo(sessao, motivo, minutos):
    cliente = sessao()
    r = _adicionar(cliente, LOJA_B, motivo=motivo)
    assert r.status_code == 201
    paragem = _gravadas(cliente.base)[0]["paragens"][0]
    assert (paragem["motivo"], paragem["tempo_servico_min"]) == (motivo, minutos)


def test_o_tempo_de_servico_vem_das_definicoes_em_vigor_e_nao_dos_padroes(sessao):
    base = _base(lojas=_lojas(), definicoes=[
        _guardada("servico_amostra_min", "20"), _guardada("servico_entrega_min", "5"),
    ])
    cliente = sessao(ZE_UTILIZADOR, base)
    assert _adicionar(cliente, LOJA_A).status_code == 201  # contactada → amostra
    assert _adicionar(cliente, LOJA_B, motivo="entrega").status_code == 201
    assert [(p["motivo"], p["tempo_servico_min"]) for p in _gravadas(base)[0]["paragens"]] == [
        ("amostra", 20), ("entrega", 5),
    ]


def test_com_rota_faz_push_no_fim_com_a_versao_mais_um(sessao):
    """Uma só `find_one_and_update` com o filtro de guarda (a versão lida, um
    estado editável, nenhum registo do motorista), o `$push` da paragem com
    `ordem = n` (as ativas: 3), o `$set` só de topo e o `$inc` da versão; a
    resposta é a rota como ficou, com a versão 4."""
    base = _base(rotas=[_rota(AMANHA, _tres_paragens())], lojas=_lojas())
    cliente = sessao(ZE_UTILIZADOR, base)
    r = _adicionar(cliente, LOJA_E)
    assert r.status_code == 201, r.text
    rota = _gravadas(base)[0]
    nova = rota["paragens"][4]
    assert (nova["loja_id"], nova["ordem"], nova["motivo"], nova["tempo_servico_min"]) == (
        LOJA_E, 3, "acompanhamento", 15,
    )
    assert (nova["adicionada_em"], nova["adicionada_por"], nova["removida_em"]) == (AGORA_INSTANTE, ZE, None)
    assert (nova["estado"], nova["resultado"], nova["concluida_em"]) == ("pendente", None, None)
    assert (rota["versao"], rota["atualizado_em"], rota["atualizado_por"]) == (4, AGORA_CARIMBO, ZE)
    assert rota["paragens"][:4] == _tres_paragens()
    assert _escritas(base) == [(
        "find_one_and_update",
        FILTRO_DE_ESCRITA,
        {"$push": {"paragens": nova}, "$set": AUTORIA, "$inc": {"versao": 1}},
        SEM_ID,
        False,
        ReturnDocument.AFTER,
    )]
    assert r.json() == _api(rota, _lojas())
    assert (r.json()["versao"], r.json()["existe"]) == (4, True)
    assert [(p["id"], p["numero"], p["seccao"]) for p in r.json()["paragens"]] == [
        ("p-b", 1, "rota"), ("p-c", 2, "rota"), ("p-a", None, "fechada"), (nova["id"], 3, "rota"),
    ]


def test_le_a_loja_pela_projecao_da_rota_depois_a_rota_pelo_dia_e_no_fim_as_lojas_de_todas(sessao):
    """A loja lê-se primeiro (o 404 vem antes de tudo), pela projeção da rota
    (nunca a morada nem as notas); a rota pelo texto do dia e sem `_id`; as
    definições uma vez; no fim, as lojas das paragens ativas para a resposta."""
    base = _base(rotas=[_rota(AMANHA, _tres_paragens())], lojas=_lojas())
    cliente = sessao(ZE_UTILIZADOR, base)
    assert _adicionar(cliente, LOJA_E).status_code == 201
    assert base.crm_lojas.registo == [
        ("find_one", {"id": LOJA_E}, PROJECAO_LOJA_ROTA),
        ("find", {"id": {"$in": [LOJA_B, LOJA_C, LOJA_A, LOJA_E]}}, PROJECAO_LOJA_ROTA),
    ]
    assert base.crm_definicoes.registo == [("find", {}, PROJECAO_DEFINICOES)]
    assert [c[:3] for c in base.crm_rotas.registo if c[0] == "find_one"] == [("find_one", {"data": AMANHA}, SEM_ID)]
    assert len(base.crm_rotas.registo) == 2


def test_uma_loja_retirada_antes_e_reativada_na_mesma_paragem(sessao):
    """A D foi retirada (índice 2 da lista): voltar a adicioná-la escreve pelos
    caminhos `paragens.2.<campo do escritório>` (sem `$push`): `removida_em`
    nulo, a `ordem` no fim (3), o motivo e o tempo de agora, os sinais
    repostos, as horas a `None` e quem a voltou a pôr; o `id`, o `loja_id`
    e o terreno não se tocam. A versão sobe 1."""
    base = _base(rotas=[_rota(AMANHA, _tres_paragens())], lojas=_lojas())
    retirada = _retirada(
        "d", LOJA_D, motivo="entrega", tempo_servico_min=30, manter_fechada=True, nao_cabe=True,
        chegada_prevista="10:00", espera_min=5, fora_de_horario=True,
    )
    base.crm_rotas.docs[0]["paragens"][2] = retirada
    cliente = sessao(ZE_UTILIZADOR, base)
    r = _adicionar(cliente, LOJA_D)
    assert r.status_code == 201, r.text
    rota = _gravadas(base)[0]
    assert len(rota["paragens"]) == 4
    assert rota["paragens"][2] == _paragem("d", LOJA_D, 3, adicionada_em=AGORA_INSTANTE, adicionada_por=ZE)
    assert rota["versao"] == 4
    caminhos = {
        "paragens.2.ordem": 3, "paragens.2.motivo": "angariacao", "paragens.2.tempo_servico_min": 15,
        "paragens.2.manter_fechada": False, "paragens.2.nao_cabe": False, "paragens.2.chegada_prevista": None,
        "paragens.2.espera_min": None, "paragens.2.fora_de_horario": False, "paragens.2.removida_em": None,
        "paragens.2.adicionada_em": AGORA_INSTANTE, "paragens.2.adicionada_por": ZE,
    }
    assert _escritas(base) == [(
        "find_one_and_update",
        FILTRO_DE_ESCRITA,
        {"$set": {**caminhos, **AUTORIA}, "$inc": {"versao": 1}},
        SEM_ID,
        False,
        ReturnDocument.AFTER,
    )]
    assert r.json() == _api(rota, _lojas())
    assert [(p["id"], p["numero"]) for p in r.json()["paragens"]] == [("p-b", 1), ("p-c", 2), ("p-a", None), ("p-d", 3)]
    assert r.json()["paragens"][3]["chegada_prevista"] is None


def _calculo_de(paragens, calculado_em="2026-10-12T20:00:00Z"):
    """Um `calculo` gravado cuja assinatura é a da rota com estas `paragens`
    (só a secção "rota", pela ordem, e a fábrica como início e fim): o
    `rota_api` dá-o como `atual` enquanto a rota tiver essas paragens assim."""
    rota = _rota(AMANHA, paragens)
    lojas = {loja["id"]: _projetada(loja) for loja in _lojas()}
    seccoes = dominio_rotas.seccoes(rota["paragens"], lojas, _dia(AMANHA))
    incluidas = [(paragem, loja) for paragem, loja, seccao, _ in seccoes if seccao == "rota"]
    return {
        "assinatura": assinatura(entrada_calculo(rota, incluidas, FABRICA_PADRAO, FABRICA_PADRAO)),
        "distancia_m": 9000, "duracao_s": 3000, "regresso_previsto": "09:50", "depois_do_limite": False,
        "geometria": "_p~iF~ps|U_ulLnnqC_mqNvxq`@", "calculado_em": calculado_em,
    }


def _filtro_com(calculo):
    """O filtro de guarda de uma rota lida com este `calculo` (correção "F3-INT-1")."""
    filtro = {campo: valor for campo, valor in FILTRO_DE_ESCRITA.items() if campo != "calculo"}
    return {**filtro, "calculo.assinatura": calculo["assinatura"], "calculo.calculado_em": calculo["calculado_em"]}


def test_reativar_na_seccao_rota_limpa_o_calculo_que_a_daria_como_atual(sessao):
    """Correção "F3-MAT-1": B, C e D foram calculadas (a D no fim, fora de
    horário) e a D foi retirada sem novo cálculo. Voltar a pô-la deixa a
    entrada igual à do cálculo gravado, mas a D volta sem horas: o `calculo`
    limpa-se na mesma escrita, e a API nunca diz `atual: true` com uma
    paragem da secção "rota" sem hora (o planeador volta a pedir as horas)."""
    horas = {
        "p-b": {"chegada_prevista": "08:10", "espera_min": 0},
        "p-c": {"chegada_prevista": "08:40", "espera_min": 20},
    }
    reativada = _paragem("d", LOJA_D, 3, adicionada_em=AGORA_INSTANTE, adicionada_por=ZE)
    depois = [
        _paragem("a", LOJA_A, 2), _paragem("b", LOJA_B, 0, **horas["p-b"]), reativada,
        _paragem("c", LOJA_C, 1, **horas["p-c"]),
    ]
    calculo = _calculo_de(depois)
    antes = deepcopy(depois)
    antes[2] = _retirada("d", LOJA_D, chegada_prevista="09:10", espera_min=0, fora_de_horario=True)
    base = _base(rotas=[_rota(AMANHA, antes, calculo=calculo)], lojas=_lojas())
    r = _adicionar(sessao(ZE_UTILIZADOR, base), LOJA_D)
    assert r.status_code == 201, r.text
    rota = _gravadas(base)[0]
    assert (rota["paragens"], rota["calculo"], rota["versao"]) == (depois, None, 4)
    assert r.json()["calculo"] is None
    assert [(p["id"], p["numero"], p["chegada_prevista"], p["aviso"]) for p in r.json()["paragens"]] == [
        ("p-b", 1, "08:10", "nenhum"), ("p-c", 2, "08:40", "nenhum"), ("p-a", None, None, "fechada_neste_dia"),
        ("p-d", 3, None, "nenhum"),
    ]
    caminhos = {
        "paragens.2.ordem": 3, "paragens.2.motivo": "angariacao", "paragens.2.tempo_servico_min": 15,
        "paragens.2.manter_fechada": False, "paragens.2.nao_cabe": False, "paragens.2.chegada_prevista": None,
        "paragens.2.espera_min": None, "paragens.2.fora_de_horario": False, "paragens.2.removida_em": None,
        "paragens.2.adicionada_em": AGORA_INSTANTE, "paragens.2.adicionada_por": ZE,
    }
    assert _escritas(base) == [(
        "find_one_and_update",
        _filtro_com(calculo),
        {"$set": {**caminhos, "calculo": None, **AUTORIA}, "$inc": {"versao": 1}},
        SEM_ID,
        False,
        ReturnDocument.AFTER,
    )]
    assert r.json() == _api(rota, _lojas())


def test_reativar_na_seccao_fechada_nao_toca_no_calculo(sessao):
    """A A fecha à quarta: reativada (sem "Manter"; o motivo da fase
    "contactada" é a amostra) fica na secção "fechada", fora do Directions.
    O cálculo de B e C continua a valer e não se escreve."""
    depois = [
        _paragem("a", LOJA_A, 2, motivo="amostra", tempo_servico_min=10, adicionada_em=AGORA_INSTANTE, adicionada_por=ZE),
        _paragem("b", LOJA_B, 0, chegada_prevista="08:10", espera_min=0),
        _paragem("c", LOJA_C, 1, chegada_prevista="08:40", espera_min=20),
    ]
    calculo = _calculo_de(depois)
    antes = deepcopy(depois)
    antes[0] = _retirada("a", LOJA_A, manter_fechada=True, chegada_prevista="09:30", espera_min=0)
    base = _base(rotas=[_rota(AMANHA, antes, calculo=calculo)], lojas=_lojas())
    r = _adicionar(sessao(ZE_UTILIZADOR, base), LOJA_A)
    assert r.status_code == 201, r.text
    rota = _gravadas(base)[0]
    assert (rota["paragens"], rota["calculo"]) == (depois, calculo)
    assert "calculo" not in _escritas(base)[0][2]["$set"]
    assert r.json()["calculo"]["atual"] is True
    assert [(p["id"], p["seccao"], p["chegada_prevista"]) for p in r.json()["paragens"]] == [
        ("p-b", "rota", "08:10"), ("p-c", "rota", "08:40"), ("p-a", "fechada", None),
    ]


def test_a_reativacao_tambem_leva_o_motivo_enviado(sessao):
    base = _base(rotas=[_rota(AMANHA, _tres_paragens())], lojas=_lojas())
    r = _adicionar(sessao(ZE_UTILIZADOR, base), LOJA_D, motivo="entrega")
    assert r.status_code == 201
    paragem = _gravadas(base)[0]["paragens"][2]
    assert (paragem["id"], paragem["motivo"], paragem["tempo_servico_min"], paragem["removida_em"]) == (
        "p-d", "entrega", 10, None,
    )


def test_uma_loja_fechada_nesse_dia_entra_na_seccao_fechada_com_o_aviso(sessao):
    """A A fecha à quarta (AMANHA): entra na mesma, sem número e com o aviso."""
    r = _adicionar(sessao(), LOJA_A)
    assert r.status_code == 201
    paragem = r.json()["paragens"][0]
    assert (paragem["numero"], paragem["seccao"], paragem["aviso"], paragem["loja"]["nome"]) == (
        None, "fechada", "fechada_neste_dia", "Café A",
    )
    assert r.json()["blocos_google"] == []


def test_a_resposta_nao_leva_dados_pessoais_nem_a_assinatura(sessao):
    r = _adicionar(sessao(), LOJA_B)
    assert r.status_code == 201
    for pessoal in ("Rua Secreta", "não sai na rota", "Sr. Silva", "assinatura", '"_id"'):
        assert pessoal not in r.text  # ("_id" entre aspas: o "loja_id" contém o texto)


def test_calculo_disponivel_segue_a_chave_do_openrouteservice(sessao, monkeypatch):
    """Com a chave é `true`; sem ela, `false`. Adicionar nunca chama o
    openrouteservice (a guarda do conftest falharia)."""
    cliente = sessao()
    monkeypatch.setenv(ors.VARIAVEL_CHAVE, "chave-de-teste")
    r = _adicionar(cliente, LOJA_B)
    assert (r.status_code, r.json()["calculo_disponivel"]) == (201, True)
    assert r.json() == _api(_gravadas(cliente.base)[0], _lojas(), calculo_disponivel=True)
    monkeypatch.delenv(ors.VARIAVEL_CHAVE)
    r = _adicionar(cliente, LOJA_C)
    assert (r.status_code, r.json()["calculo_disponivel"]) == (201, False)


def test_hoje_e_o_ultimo_dia_do_horizonte_tambem_recebem_paragens(sessao):
    cliente = sessao()
    assert _adicionar(cliente, LOJA_B, data=HOJE).status_code == 201
    assert _adicionar(cliente, LOJA_B, data=ULTIMO_DIA).status_code == 201
    assert [rota["data"] for rota in _gravadas(cliente.base)] == [HOJE, ULTIMO_DIA]


def test_o_relogio_le_se_uma_vez_por_pedido(sessao, monkeypatch):
    """Um só instante por pedido: o "hoje" da validação, os instantes gravados
    e o `hoje` da resposta são do mesmo `relogio.agora()`."""
    cliente = sessao(ZE_UTILIZADOR, _base(rotas=[_rota(AMANHA, _tres_paragens())], lojas=_lojas()))
    leituras = []

    def _agora():
        leituras.append(1)
        return AGORA

    monkeypatch.setattr(relogio, "agora", _agora)
    assert _adicionar(cliente, LOJA_E).status_code == 201
    assert len(leituras) == 1
    leituras.clear()
    assert _adicionar(cliente, LOJA_F, data=HOJE).status_code == 201
    assert len(leituras) == 1


# --- Recusas, pela ordem do plano ----------------------------------------------------------------


@pytest.mark.parametrize(
    "corpo, campos",
    [
        ({}, {"loja_id": LOJA}),
        ({"loja_id": None}, {"loja_id": LOJA}),
        ({"loja_id": "abc"}, {"loja_id": LOJA}),
        ({"loja_id": LOJA_A.upper()}, {"loja_id": LOJA}),
        ({"loja_id": LOJA_A, "motivo": "visita"}, {"motivo": MOTIVO}),
        ({"loja_id": LOJA_A, "motivo": ""}, {"motivo": MOTIVO}),
        ({"loja_id": LOJA_A, "versao": "3"}, {"versao": VERSAO_INVALIDA}),
        ({"loja_id": LOJA_A, "versao": 0}, {"versao": VERSAO_INVALIDA}),
        ({"loja_id": LOJA_A, "versao": True}, {"versao": VERSAO_INVALIDA}),
        ({"loja_id": LOJA_A, "versao": 1.0}, {"versao": VERSAO_INVALIDA}),
        ({"loja_id": 7, "motivo": 3, "versao": -1}, {"loja_id": LOJA, "motivo": MOTIVO, "versao": VERSAO_INVALIDA}),
    ],
    ids=[
        "vazio", "loja nula", "loja que não é uuid", "uuid em maiúsculas", "motivo desconhecido", "motivo vazio",
        "versão em texto", "versão 0", "versão booleana", "versão 1.0", "os três errados",
    ],
)
def test_um_corpo_errado_da_422_sem_tocar_na_base(sessao, corpo, campos):
    cliente = sessao()
    r = cliente.post(_url(), json=corpo)
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
    r = _adicionar(cliente, LOJA_A, data=data)
    assert (r.status_code, r.json()) == (422, _validacao({"data": mensagem}))
    assert _operacoes(cliente.base) == set()


def test_os_erros_da_data_e_do_corpo_vem_juntos_com_a_data_primeiro(sessao):
    r = sessao().post(_url("abc"), json={"motivo": "x"})
    assert (r.status_code, r.json()) == (422, _validacao({"data": DATA, "loja_id": LOJA, "motivo": MOTIVO}))
    assert list(r.json()["detail"]["campos"]) == ["data", "loja_id", "motivo"]


@pytest.mark.parametrize("corpo", [b"[", b"[1]", b"null", b'"x"', b'{"loja_id": NaN}'], ids=["[", "lista", "null", "texto", "NaN"])
def test_um_corpo_que_nao_e_um_objeto_json_da_400(sessao, corpo):
    cliente = sessao()
    r = cliente.post(_url(), content=corpo, headers=JSON)
    assert (r.status_code, r.json()) == (400, JSON_INVALIDO)
    assert _operacoes(cliente.base) == set()


def test_uma_loja_inexistente_da_404_antes_de_ler_a_rota(sessao):
    cliente = sessao(ZE_UTILIZADOR, _base(rotas=[_rota(AMANHA, _tres_paragens())], lojas=_lojas()))
    r = _adicionar(cliente, INEXISTENTE)
    assert (r.status_code, r.json()) == (404, LOJA_NAO_ENCONTRADA)
    assert cliente.base.crm_lojas.registo == [("find_one", {"id": INEXISTENTE}, PROJECAO_LOJA_ROTA)]
    assert cliente.base.crm_rotas.registo == []
    assert cliente.base.crm_definicoes.registo == []


def test_a_loja_ve_se_antes_do_dia_fechado(sessao):
    r = _adicionar(sessao(), INEXISTENTE, data=ONTEM)
    assert (r.status_code, r.json()) == (404, LOJA_NAO_ENCONTRADA)


@pytest.mark.parametrize("com_rota", [False, True], ids=["sem rota", "com rota"])
def test_ontem_da_rota_fechada_sem_escrever(sessao, com_rota):
    rotas = [_rota(ONTEM, [_paragem("b", LOJA_B, 0)])] if com_rota else []
    cliente = sessao(ZE_UTILIZADOR, _base(rotas=rotas, lojas=_lojas()))
    antes = _gravadas(cliente.base)
    r = _adicionar(cliente, LOJA_A, data=ONTEM)
    assert (r.status_code, r.json()) == (409, ROTA_FECHADA)
    assert _escritas(cliente.base) == []
    assert _gravadas(cliente.base) == antes


@pytest.mark.parametrize(
    "paragens, estado",
    [
        ([_paragem("b", LOJA_B, 0), _feita("c", LOJA_C, 1)], "rascunho"),
        ([_paragem("b", LOJA_B, 0, estado="nao_feita")], "planeada"),
        ([_paragem("b", LOJA_B, 0), _retirada("c", LOJA_C, estado="feita")], "rascunho"),
        ([_paragem("b", LOJA_B, 0)], "em_curso"),
        ([_paragem("b", LOJA_B, 0)], "concluida"),
    ],
    ids=["uma feita", "uma não feita", "uma retirada e feita", "estado em_curso", "estado concluida"],
)
def test_uma_rota_com_registo_do_motorista_da_rota_em_curso_sem_escrever(sessao, paragens, estado):
    base = _base(rotas=[_rota(AMANHA, paragens, estado=estado)], lojas=_lojas())
    cliente = sessao(ZE_UTILIZADOR, base)
    antes = _gravadas(base)
    r = _adicionar(cliente, LOJA_A)
    assert (r.status_code, r.json()) == (409, ROTA_EM_CURSO)
    assert _escritas(base) == []
    assert _gravadas(base) == antes


def test_rota_em_curso_ganha_ao_conflito_e_ao_ja_na_rota(sessao):
    base = _base(rotas=[_rota(AMANHA, [_paragem("b", LOJA_B, 0), _feita("c", LOJA_C, 1)])], lojas=_lojas())
    r = _adicionar(sessao(ZE_UTILIZADOR, base), LOJA_B, versao=1)
    assert (r.status_code, r.json()) == (409, ROTA_EM_CURSO)


def test_ja_na_rota_quando_a_loja_esta_numa_paragem_ativa(sessao):
    base = _base(rotas=[_rota(AMANHA, _tres_paragens())], lojas=_lojas())
    cliente = sessao(ZE_UTILIZADOR, base)
    for loja_id in (LOJA_A, LOJA_B, LOJA_C):
        r = _adicionar(cliente, loja_id)
        assert (r.status_code, r.json()) == (409, JA_NA_ROTA)
    assert _escritas(base) == []
    assert _gravadas(base) == [_rota(AMANHA, _tres_paragens())]


def test_rota_cheia_com_48_ativas(sessao):
    rota, lojas = _rota_com_n_ativas(48)
    base = _base(rotas=[rota], lojas=lojas + _lojas())
    cliente = sessao(ZE_UTILIZADOR, base)
    r = _adicionar(cliente, LOJA_B)
    assert (r.status_code, r.json()) == (409, ROTA_CHEIA)
    assert _escritas(base) == []
    assert _gravadas(base) == [rota]
    assert r.json()["detail"]["mensagem"] == f"Uma rota tem no máximo {dominio_rotas.LIMITE_PARAGENS} paragens."


def test_com_47_ativas_e_uma_retirada_a_48_entra(sessao):
    """As retiradas não contam para o limite; a nova fica com a ordem 47."""
    rota, lojas = _rota_com_n_ativas(47)
    rota["paragens"].append(_retirada("x", LOJA_D))
    base = _base(rotas=[rota], lojas=lojas + _lojas())
    r = _adicionar(sessao(ZE_UTILIZADOR, base), LOJA_B)
    assert r.status_code == 201, r.text
    nova = _gravadas(base)[0]["paragens"][-1]
    assert (nova["loja_id"], nova["ordem"]) == (LOJA_B, 47)
    assert len(r.json()["paragens"]) == 48


def test_reativar_uma_retirada_tambem_conta_para_o_limite(sessao):
    rota, lojas = _rota_com_n_ativas(48)
    rota["paragens"].insert(0, _retirada("x", LOJA_D))
    base = _base(rotas=[rota], lojas=lojas + _lojas())
    r = _adicionar(sessao(ZE_UTILIZADOR, base), LOJA_D)
    assert (r.status_code, r.json()) == (409, ROTA_CHEIA)
    assert _escritas(base) == []


def test_ja_na_rota_ganha_a_rota_cheia(sessao):
    rota, lojas = _rota_com_n_ativas(48)
    base = _base(rotas=[rota], lojas=lojas)
    r = _adicionar(sessao(ZE_UTILIZADOR, base), lojas[5]["id"])
    assert (r.status_code, r.json()) == (409, JA_NA_ROTA)


# --- Versão ---------------------------------------------------------------------------------------


def test_com_a_versao_certa_grava(sessao):
    base = _base(rotas=[_rota(AMANHA, _tres_paragens())], lojas=_lojas())
    r = _adicionar(sessao(ZE_UTILIZADOR, base), LOJA_E, versao=3)
    assert r.status_code == 201
    assert (r.json()["versao"], _gravadas(base)[0]["versao"]) == (4, 4)


@pytest.mark.parametrize("versao", [1, 2, 4, 99], ids=["1", "2", "4", "99"])
def test_com_uma_versao_diferente_da_conflito_sem_escrever(sessao, versao):
    base = _base(rotas=[_rota(AMANHA, _tres_paragens())], lojas=_lojas())
    cliente = sessao(ZE_UTILIZADOR, base)
    r = _adicionar(cliente, LOJA_E, versao=versao)
    assert (r.status_code, r.json()) == (409, CONFLITO)
    assert _escritas(base) == []
    assert _gravadas(base) == [_rota(AMANHA, _tres_paragens())]
    assert [c[0] for c in base.crm_rotas.registo] == ["find_one"]


def test_versao_nula_quer_dizer_que_julgo_que_nao_ha_rota(sessao):
    """Sem rota, cria; com rota, 409 `conflito` (outra pessoa criou-a)."""
    cliente = sessao()
    r = _adicionar(cliente, LOJA_A, versao=None)
    assert r.status_code == 201
    assert _gravadas(cliente.base)[0]["versao"] == 1
    r = _adicionar(cliente, LOJA_B, versao=None)
    assert (r.status_code, r.json()) == (409, CONFLITO)
    assert len(_gravadas(cliente.base)[0]["paragens"]) == 1


def test_uma_versao_para_um_dia_sem_rota_e_conflito(sessao):
    cliente = sessao()
    r = _adicionar(cliente, LOJA_A, versao=3)
    assert (r.status_code, r.json()) == (409, CONFLITO)
    assert _gravadas(cliente.base) == []


def test_o_conflito_ganha_ao_ja_na_rota_e_a_rota_cheia(sessao):
    rota, lojas = _rota_com_n_ativas(48)
    base = _base(rotas=[rota], lojas=lojas)
    r = _adicionar(sessao(ZE_UTILIZADOR, base), lojas[0]["id"], versao=2)
    assert (r.status_code, r.json()) == (409, CONFLITO)


def test_sem_versao_tenta_de_novo_quando_a_escrita_falha(sessao):
    """O cartão do mapa não conhece a versão: outra pessoa sobe a versão entre
    a leitura e a escrita (o gancho, só na 1.ª tentativa) → a 2.ª tentativa
    relê e grava (201), com a versão 5 (3, +1 da outra pessoa, +1 nossa)."""
    base = _base(rotas=[_rota(AMANHA, _tres_paragens())], lojas=_lojas())
    vezes = []

    def outra_pessoa(docs):
        if not vezes:
            vezes.append(1)
            docs[0]["versao"] += 1

    base.crm_rotas.antes_de("find_one_and_update", outra_pessoa)
    cliente = sessao(ZE_UTILIZADOR, base)
    r = _adicionar(cliente, LOJA_E)
    assert r.status_code == 201, r.text
    rota = _gravadas(base)[0]
    assert (rota["versao"], len(rota["paragens"]), rota["paragens"][4]["loja_id"]) == (5, 5, LOJA_E)
    assert r.json() == _api(rota, _lojas())
    operacoes = [c[0] for c in base.crm_rotas.registo]
    assert operacoes == ["find_one", "find_one_and_update", "find_one", "find_one", "find_one_and_update"]
    filtros = [c[1]["versao"] for c in base.crm_rotas.registo if c[0] == "find_one_and_update"]
    assert filtros == [3, 4]
    # porque_falhou relê sem o calculo; as tentativas releem pelo dia.
    assert base.crm_rotas.registo[2][1:] == ({"id": "r-1"}, SEM_CALCULO)
    assert base.crm_rotas.registo[3][1:] == ({"data": AMANHA}, SEM_ID)


def test_sem_versao_desiste_a_terceira_falha_com_conflito(sessao):
    base = _base(rotas=[_rota(AMANHA, _tres_paragens())], lojas=_lojas())

    def outra_pessoa(docs):
        docs[0]["versao"] += 1

    base.crm_rotas.antes_de("find_one_and_update", outra_pessoa)
    cliente = sessao(ZE_UTILIZADOR, base)
    r = _adicionar(cliente, LOJA_E)
    assert (r.status_code, r.json()) == (409, CONFLITO)
    assert [c[0] for c in base.crm_rotas.registo].count("find_one_and_update") == 3
    rota = _gravadas(base)[0]
    assert (rota["versao"], rota["paragens"]) == (6, _tres_paragens())  # só a outra pessoa escreveu


def test_com_versao_nao_tenta_de_novo(sessao):
    base = _base(rotas=[_rota(AMANHA, _tres_paragens())], lojas=_lojas())

    def outra_pessoa(docs):
        docs[0]["versao"] += 1

    base.crm_rotas.antes_de("find_one_and_update", outra_pessoa)
    r = _adicionar(sessao(ZE_UTILIZADOR, base), LOJA_E, versao=3)
    assert (r.status_code, r.json()) == (409, CONFLITO)
    assert [c[0] for c in base.crm_rotas.registo].count("find_one_and_update") == 1
    assert _gravadas(base)[0]["paragens"] == _tres_paragens()


@pytest.mark.parametrize("corpo", [{}, {"versao": 3}], ids=["sem versão", "com versão"])
def test_o_motorista_a_registar_entre_a_leitura_e_a_escrita_da_rota_em_curso(sessao, corpo):
    """A escrita condicional não casa e `porque_falhou` diz `em_curso`: 409
    `rota_em_curso` logo, sem tentar outra vez; nada do escritório fica."""
    base = _base(rotas=[_rota(AMANHA, _tres_paragens())], lojas=_lojas())

    def motorista(docs):
        docs[0]["paragens"][1]["estado"] = "feita"

    base.crm_rotas.antes_de("find_one_and_update", motorista)
    cliente = sessao(ZE_UTILIZADOR, base)
    r = cliente.post(_url(), json={"loja_id": LOJA_E, **corpo})
    assert (r.status_code, r.json()) == (409, ROTA_EM_CURSO)
    assert [c[0] for c in base.crm_rotas.registo] == ["find_one", "find_one_and_update", "find_one"]
    assert base.crm_rotas.registo[2][1:] == ({"id": "r-1"}, SEM_CALCULO)  # o porque_falhou, não uma nova tentativa
    esperada = _rota(AMANHA, _tres_paragens())
    esperada["paragens"][1]["estado"] = "feita"
    assert _gravadas(base) == [esperada]


def _recalculo_de_outra_pessoa(base, so_uma_vez):
    """O gancho de um recálculo de outra pessoa entre a leitura e a escrita:
    as horas da B e um `calculo` novo, com a versão igual (correção "F3-INT-1")."""
    def recalcula(docs):
        docs[0]["paragens"][1].update({"chegada_prevista": "08:10", "espera_min": 0})
        docs[0]["calculo"] = _calculo_de(docs[0]["paragens"], calculado_em="2026-10-12T23:30:00Z")
        if so_uma_vez:
            base.crm_rotas.antes_de("find_one_and_update", None)

    base.crm_rotas.antes_de("find_one_and_update", recalcula)


def test_sem_versao_um_recalculo_entre_a_leitura_e_a_escrita_rele_e_grava(sessao):
    """O recálculo não sobe a versão, mas muda o cálculo lido: a 1.ª escrita
    já não casa, a 2.ª tentativa relê (com o cálculo novo no filtro) e grava."""
    base = _base(rotas=[_rota(AMANHA, _tres_paragens())], lojas=_lojas())
    _recalculo_de_outra_pessoa(base, so_uma_vez=True)
    r = _adicionar(sessao(ZE_UTILIZADOR, base), LOJA_E)
    assert r.status_code == 201, r.text
    assert [c[0] for c in base.crm_rotas.registo] == [
        "find_one", "find_one_and_update", "find_one", "find_one", "find_one_and_update",
    ]
    escritas = [c for c in base.crm_rotas.registo if c[0] == "find_one_and_update"]
    rota = _gravadas(base)[0]
    assert (escritas[0][1], escritas[1][1]) == (FILTRO_DE_ESCRITA, _filtro_com(rota["calculo"]))
    assert (rota["versao"], rota["paragens"][4]["loja_id"], rota["paragens"][1]["chegada_prevista"]) == (4, LOJA_E, "08:10")


def test_com_versao_um_recalculo_entre_a_leitura_e_a_escrita_da_conflito(sessao):
    base = _base(rotas=[_rota(AMANHA, _tres_paragens())], lojas=_lojas())
    _recalculo_de_outra_pessoa(base, so_uma_vez=False)
    r = _adicionar(sessao(ZE_UTILIZADOR, base), LOJA_E, versao=3)
    assert (r.status_code, r.json()) == (409, CONFLITO)
    assert [c[0] for c in base.crm_rotas.registo] == ["find_one", "find_one_and_update", "find_one"]
    rota = _gravadas(base)[0]
    assert (rota["versao"], len(rota["paragens"]), rota["paragens"][1]["chegada_prevista"]) == (3, 4, "08:10")


def test_a_rota_apagada_entre_a_leitura_e_a_escrita_cria_se_de_novo_sem_versao(sessao):
    base = _base(rotas=[_rota(AMANHA, _tres_paragens())], lojas=_lojas())

    def apagada(docs):
        docs.clear()

    base.crm_rotas.antes_de("find_one_and_update", apagada)
    cliente = sessao(ZE_UTILIZADOR, base)
    r = _adicionar(cliente, LOJA_E)
    assert r.status_code == 201, r.text
    rota = _gravadas(base)[0]
    assert (rota["versao"], [p["loja_id"] for p in rota["paragens"]]) == (1, [LOJA_E])
    assert [c[0] for c in base.crm_rotas.registo] == ["find_one", "find_one_and_update", "find_one", "find_one", "insert_one"]


# --- Corridas -------------------------------------------------------------------------------------


def test_duas_pessoas_a_criar_a_rota_do_mesmo_dia_ficam_as_duas(monkeypatch):
    """Duas corrotinas (o duplo cede ao ciclo antes de cada operação): as duas
    leem "sem rota" e inserem; a segunda `insert_one` falha pelo índice único
    de `data` (`criar` → False), volta a ler e acrescenta. Fica uma rota com
    as duas paragens e a versão 2."""
    base = _base(lojas=_lojas())
    monkeypatch.setattr(relogio, "agora", lambda: AGORA)
    monkeypatch.setattr(crm.db, "obter_db", lambda: base)

    async def _duas():
        return await asyncio.gather(
            rotas_http.adicionar_paragem(AMANHA, membro={**ZE_UTILIZADOR, "crm_perfil": "utilizador"}, corpo={"loja_id": LOJA_A}),
            rotas_http.adicionar_paragem(AMANHA, membro={**ANA_ADMIN_DO_CRM, "crm_perfil": "admin"}, corpo={"loja_id": LOJA_B}),
        )

    primeira, segunda = correr(_duas())
    gravadas = _gravadas(base)
    assert len(gravadas) == 1
    rota = gravadas[0]
    assert rota["versao"] == 2
    assert [(p["loja_id"], p["ordem"], p["adicionada_por"]) for p in rota["paragens"]] == [
        (LOJA_A, 0, ZE), (LOJA_B, 1, "u-ana"),
    ]
    assert [c[0] for c in base.crm_rotas.registo].count("insert_one") == 2
    assert [c[0] for c in base.crm_rotas.registo].count("find_one_and_update") == 1
    assert (primeira["versao"], [p["loja_id"] for p in primeira["paragens"]]) == (1, [LOJA_A])
    assert segunda == _api(rota, _lojas())


def test_com_versao_nula_a_corrida_na_criacao_e_conflito(sessao):
    """O planeador diz "julgo que ainda não há rota" e outra pessoa cria-a
    entre a leitura e a `insert_one`: 409 `conflito`, sem tentar acrescentar."""
    base = _base(lojas=_lojas())
    outra = _rota(AMANHA, [_paragem("b", LOJA_B, 0)], id_="r-outra")

    def outra_pessoa(docs):
        if not docs:
            docs.append({**deepcopy(outra), "_id": "outra"})

    base.crm_rotas.antes_de("insert_one", outra_pessoa)
    r = _adicionar(sessao(ZE_UTILIZADOR, base), LOJA_A, versao=None)
    assert (r.status_code, r.json()) == (409, CONFLITO)
    assert _gravadas(base) == [outra]
    assert [c[0] for c in base.crm_rotas.registo] == ["find_one", "insert_one"]


def test_sem_versao_a_corrida_na_criacao_acrescenta(sessao):
    base = _base(lojas=_lojas())
    outra = _rota(AMANHA, [_paragem("b", LOJA_B, 0)], id_="r-outra", versao=1)

    def outra_pessoa(docs):
        if not docs:
            docs.append({**deepcopy(outra), "_id": "outra"})

    base.crm_rotas.antes_de("insert_one", outra_pessoa)
    r = _adicionar(sessao(ZE_UTILIZADOR, base), LOJA_A)
    assert r.status_code == 201, r.text
    rota = _gravadas(base)[0]
    assert (rota["id"], rota["versao"], [p["loja_id"] for p in rota["paragens"]]) == ("r-outra", 2, [LOJA_B, LOJA_A])
    assert [c[0] for c in base.crm_rotas.registo] == ["find_one", "insert_one", "find_one", "find_one_and_update"]


# --- As escritas passam nos verificadores --------------------------------------------------------


def test_todas_as_escritas_passam_no_terreno_e_nos_instantes(sessao):
    """Criar, acrescentar e reativar: cada escrita registada (a `insert_one` e
    as `find_one_and_update`) passa em `escritas_no_terreno` e em
    `instantes_fora_do_formato`, e os documentos gravados também."""
    cliente = sessao()
    assert _adicionar(cliente, LOJA_A).status_code == 201
    assert _adicionar(cliente, LOJA_B).status_code == 201
    cliente.base.crm_rotas.docs[0]["paragens"][0]["removida_em"] = "2026-10-12T20:00:00Z"
    cliente.base.crm_rotas.docs[0]["paragens"][0]["ordem"] = None
    cliente.base.crm_rotas.docs[0]["paragens"][1]["ordem"] = 0
    assert _adicionar(cliente, LOJA_A).status_code == 201
    escritas = _escritas(cliente.base)
    assert [e[0] for e in escritas] == ["insert_one", "find_one_and_update", "find_one_and_update"]
    for escrita in escritas:
        atualizacao = escrita[1] if escrita[0] == "insert_one" else escrita[2]
        assert escritas_no_terreno(atualizacao) == []
        assert instantes_fora_do_formato(atualizacao) == []
    assert instantes_fora_do_formato(_gravadas(cliente.base)) == []
    rota = _gravadas(cliente.base)[0]
    assert (rota["versao"], [(p["loja_id"], p["ordem"], p["removida_em"]) for p in rota["paragens"]]) == (
        3, [(LOJA_A, 1, None), (LOJA_B, 0, None)],
    )


def test_o_escritorio_nunca_escreve_os_campos_do_terreno_por_caminho(sessao):
    base = _base(rotas=[_rota(AMANHA, _tres_paragens())], lojas=_lojas())
    assert _adicionar(sessao(ZE_UTILIZADOR, base), LOJA_D).status_code == 201
    atualizacao = _escritas(base)[0][2]
    assert "$push" not in atualizacao
    for caminho in atualizacao["$set"]:
        if caminho.startswith("paragens."):
            assert caminho.split(".")[2] in dominio_rotas.CAMPOS_DO_ESCRITORIO


# --- Quem entra -----------------------------------------------------------------------------------


def test_o_escritorio_adiciona(sessao):
    for pessoa, loja_id in ((ADMIN_MASTER, LOJA_A), (ANA_ADMIN_DO_CRM, LOJA_B), (ZE_UTILIZADOR, LOJA_C)):
        cliente = sessao(pessoa)
        r = _adicionar(cliente, loja_id)
        assert r.status_code == 201, r.text
        assert _gravadas(cliente.base)[0]["paragens"][0]["adicionada_por"] == pessoa["user_id"]


def test_o_motorista_recebe_403_sem_permissao(sessao):
    cliente = sessao(ALVARO_MOTORISTA)
    r = _adicionar(cliente, LOJA_A)
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)
    assert _operacoes(cliente.base) == set()


def test_quem_nao_e_membro_recebe_403_sem_acesso_crm(sessao):
    cliente = sessao(BEA_NAO_MEMBRO)
    r = _adicionar(cliente, LOJA_A)
    assert (r.status_code, r.json()) == (403, SEM_ACESSO)
    assert _operacoes(cliente.base) == set()


@pytest.mark.parametrize(
    "utilizador, esperado", [(ALVARO_MOTORISTA, SEM_PERMISSAO), (BEA_NAO_MEMBRO, SEM_ACESSO)],
    ids=["motorista", "não membro"],
)
def test_sem_perfil_e_com_json_partido_da_403_e_nunca_400(sessao, utilizador, esperado):
    r = sessao(utilizador).post(_url(), content=b"[", headers=JSON)
    assert (r.status_code, r.json()) == (403, esperado)


# --- De ponta a ponta: a sessão verdadeira do portal ---------------------------------------------

SEGREDO = "segredo-de-teste-crm-rotas-adicionar"
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
    base = _base(rotas=[_rota(AMANHA, _tres_paragens())], lojas=_lojas())
    monkeypatch.setattr(faturacao.auth, "obter_db", lambda: base)
    monkeypatch.setattr(crm.db, "obter_db", lambda: base)
    app = FastAPI()
    app.include_router(crm.router)
    cliente = TestClient(app)
    cliente.base = base
    return cliente


def test_sem_sessao_da_o_403_herdado(portal):
    r = portal.post(_url(), json={"loja_id": LOJA_E})
    assert (r.status_code, r.json()) == (403, {"detail": "Not authenticated"})
    assert portal.base.crm_rotas.registo == []


def test_sem_cabecalho_e_com_json_partido_da_o_403_herdado_e_nunca_400(portal):
    r = portal.post(_url(), content=b"[", headers=JSON)
    assert (r.status_code, r.json()) == (403, {"detail": "Not authenticated"})
    assert portal.base.users.registo == []
    assert portal.base.crm_rotas.registo == []


def test_uma_conta_apagada_da_401_sessao_terminada(portal):
    r = portal.post(_url(), json={"loja_id": LOJA_E}, headers=_cabecalho("u-apagada"))
    assert (r.status_code, r.json()) == (401, {"detail": "Sessão terminada"})
    assert portal.base.crm_rotas.registo == []


def test_de_ponta_a_ponta_o_escritorio_adiciona_e_o_dia_mostra_a_paragem(portal):
    ze = _cabecalho(ZE, email="ze@example.com")
    admin = _cabecalho("u-admin", email=ADMIN_LOCAL, role="admin")

    r = portal.post(_url(), json={"loja_id": LOJA_E}, headers=_cabecalho("u-alv", email="alvaro@example.com"))
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)
    r = portal.post(_url(), json={"loja_id": LOJA_E}, headers=_cabecalho("u-bea", email="bea@example.com"))
    assert (r.status_code, r.json()) == (403, SEM_ACESSO)
    assert portal.base.crm_rotas.registo == []

    r = portal.post(_url(), json={"loja_id": LOJA_E}, headers=ze)
    assert r.status_code == 201, r.text
    assert (r.json()["versao"], len(r.json()["paragens"])) == (4, 4)
    assert portal.get(f"{ROTAS_URL}/{AMANHA}", headers=admin).json() == r.json()

    r = portal.post(_url(), json={"loja_id": LOJA_E, "versao": 4}, headers=admin)
    assert (r.status_code, r.json()) == (409, JA_NA_ROTA)
    r = portal.post(_url(), json={"loja_id": LOJA_F, "versao": 3}, headers=admin)
    assert (r.status_code, r.json()) == (409, CONFLITO)
    r = portal.post(_url(), json={"loja_id": LOJA_F, "versao": 4}, headers=admin)
    assert r.status_code == 201, r.text
    assert [p["loja"]["nome"] for p in r.json()["paragens"]] == [
        "Pastelaria B", "Mercearia C", "Café A", "Padaria E", "Talho F",
    ]
    assert portal.get(ROTAS_URL, headers=ze).json()["rotas"] == [
        {"id": "r-1", "data": AMANHA, "estado": "rascunho", "estado_efetivo": "rascunho", "paragens": 5},
    ]
    r = portal.post(_url(ONTEM), json={"loja_id": LOJA_F}, headers=admin)
    assert (r.status_code, r.json()) == (409, ROTA_FECHADA)
    assert all(escritas_no_terreno(e[1] if e[0] == "insert_one" else e[2]) == [] for e in _escritas(portal.base))
