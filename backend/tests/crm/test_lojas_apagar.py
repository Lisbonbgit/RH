"""`DELETE /api/crm/lojas/{loja_id}` — apagar uma loja, só quando é um engano
(plano T2.12; dossiê §5.12 e §6).

Porta dos casos de apagar de tests/Integration/Api/LojasEditarTest.php do CRM
autónomo (etiqueta `referencia-standalone`): `apagarDa200EDepois404`,
`asMudancasDeFaseNaoImpedemApagarEVaoComALoja`, `umaLojaComHistoricoNaoSeApaga`
(com os tipos do `DataProvider` `historico`) e a metade DELETE do
`semSessaoDa401ENadaMuda`; e do `LojasControlador::apagar` com o
`LojasRepositorio::podeApagar`/`apagar`. Adaptações ao portal:

- só o escritório (admin e utilizador do CRM). Sem sessão, os 403/401 herdados
  do portal em vez do 401 `nao_autenticado` do autónomo;
- ids uuid4 em texto (lá inteiros);
- as lojas e as interações "inseridas por SQL" (`LojasTeste::criar` e
  `LojasTeste::interacao`) são documentos escritos à mão no duplo, com a forma
  da base (plano §3);
- sem transações nem `ON DELETE CASCADE` (o autónomo bloqueava a linha com
  `SELECT … FOR UPDATE` e as interações iam com a loja pela chave estrangeira).
  Ordem: ler a loja (404) → há histórico? (409) → `delete_one` da loja
  (`deleted_count 0` → 404) → `delete_many` SÓ das `mudanca_fase` dela. Nunca
  se apaga outro tipo de interação, nem numa corrida; uma falha no
  `delete_many` não desfaz nada (a loja já foi) e fica numa linha `[crm]` no
  registo (plano §1, "Sem transações");
- o `Cache-Control: no-store, private` não se porta (diferença assumida na
  T2.9, dossiê §5.8);
- **F3 (T3.24): uma loja numa rota não se apaga** (plano F3 §1 "Apagar uma
  loja" e §4). Depois do histórico, leem-se as rotas em que a loja está
  (`rotas_bd.rotas_com_loja`: o índice `paragens.loja_id`, sem o `calculo`)
  e a regra pura `dominio.rotas.loja_presa_em_rota(rotas, loja_id, hoje)`
  decide: uma paragem ativa, ou com registo do motorista mesmo retirada,
  prende; uma retirada e ainda `pendente` não. 409 `loja_em_rota`, com
  "está numa rota — retire-a da rota ou mude a fase para perdida" numa
  rota de hoje ou do futuro e "esteve numa rota — mude a fase para
  perdida" quando só há rotas passadas (correção "T3.24": essa rota é só
  de leitura, retirar é impossível). Ordem: 404 → `loja_com_historico` →
  `loja_em_rota` → `delete_one`. O "hoje" é o do relógio do CRM, em
  Lisboa.

Rotas por `TestClient` com `dependency_overrides[utilizador_atual]` e
`monkeypatch.setattr(crm.db, "obter_db", …)` (plano §10); as corridas com
`correr` (nunca `asyncio.run`); no fim, de ponta a ponta com a sessão
verdadeira do portal (JWT + conta lida da base).
"""
import asyncio
import inspect
import logging
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
from crm.lojas import MENSAGEM_COM_HISTORICO, MENSAGEM_LOJA_EM_ROTA, MENSAGEM_LOJA_ESTEVE_EM_ROTA, apagar_loja
from crm.pedidos import corpo_json
from faturacao.auth import utilizador_atual

from .duplos import BaseFalsa, ColeccaoFalsa, correr

LOJAS_URL = "/api/crm/lojas"
UMA_LOJA_URL = "/api/crm/lojas/{loja_id}"
ADMIN_LOCAL = "admin.local@example.com"
JSON = {"Content-Type": "application/json"}

UTC = timezone.utc
AGORA = datetime(2026, 10, 10, 9, 30, 15, 987654, tzinfo=UTC)

# Rua Augusta, em Lisboa; e longe de tudo (1 km para norte).
LAT = 38.710800
LNG = -9.136900
LAT_LONGE = 38.719800

# A forma das lojas "inseridas por SQL" (LojasTeste).
CRIADA_EM = "2026-10-03T09:00:00Z"
VERSAO = "2026-10-03T09:00:00.250000Z"

NAO_ENCONTRADA = {"detail": {"codigo": "nao_encontrado", "mensagem": "Loja não encontrada."}}
COM_HISTORICO = {
    "detail": {
        "codigo": "loja_com_historico",
        "mensagem": "Esta loja tem histórico — mude a fase para perdida em vez de a apagar.",
    }
}
APAGADA = {"apagada": True}
EM_ROTA = {
    "detail": {
        "codigo": "loja_em_rota",
        "mensagem": "Esta loja está numa rota — retire-a da rota ou mude a fase para perdida.",
    }
}
ESTEVE_EM_ROTA = {
    "detail": {"codigo": "loja_em_rota", "mensagem": "Esta loja esteve numa rota — mude a fase para perdida."}
}
SEM_PERMISSAO = {"detail": {"codigo": "sem_permissao", "mensagem": "Sem permissão para esta ação."}}
SEM_ACESSO = {"detail": {"codigo": "sem_acesso_crm", "mensagem": "Sem acesso ao CRM."}}

PROJECAO_ID = {"_id": 0, "id": 1}
# O `podeApagar` do autónomo: `SELECT 1 FROM interacoes WHERE loja_id = ? AND tipo <> 'mudanca_fase' LIMIT 1`.
FILTRO_HISTORICO = {"tipo": {"$ne": "mudanca_fase"}}
FILTRO_MUDANCAS_DE_FASE = {"tipo": "mudanca_fase"}
# As rotas em que a loja está (`rotas_bd.rotas_com_loja`): pelo índice
# `paragens.loja_id`, sem a geometria.
SEM_CALCULO = {"_id": 0, "calculo": 0}

# AGORA é 09:30Z de 2026-10-10: em Lisboa (WEST) ainda é dia 10.
ONTEM, HOJE, AMANHA = "2026-10-09", "2026-10-10", "2026-10-11"


def _id(n):
    """Um uuid4 em texto, fixo para os testes serem legíveis."""
    return f"00000000-0000-4000-8000-{n:012d}"


CAFE, BAR = _id(1), _id(2)
NAO_EXISTE = _id(999)
FILTRO_ROTAS = {"paragens.loja_id": CAFE}


def _loja(numero, nome, lat, lng=LNG, **outros):
    """Uma loja escrita à mão na base (o `LojasTeste::criar`)."""
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
    """O Café Central (a loja que se apaga), no ponto de referência."""
    return _loja(1, "Café Central", LAT, **outros)


def _bar(**outros):
    """O Bar da Esquina, outra loja, longe do Café."""
    return _loja(2, "Bar da Esquina", LAT_LONGE, **outros)


def _interacao(numero, loja_id, tipo, resultado=None):
    """Uma interação escrita à mão (o `LojasTeste::interacao`: às 10:00 de 2026-10-03)."""
    return {
        "id": _id(500 + numero),
        "loja_id": loja_id,
        "tipo": tipo,
        "resultado": resultado,
        "notas": None,
        "paragem_id": None,
        "utilizador_id": None,
        "ocorrida_em": "2026-10-03T10:00:00Z",
    }


def _mudanca(numero, loja_id, resultado="potencial→contactada"):
    return _interacao(numero, loja_id, "mudanca_fase", resultado)


def _paragem(loja_id, ordem, **campos):
    """Uma paragem como está na base (plano F3 §3)."""
    return {
        "id": _id(700 + ordem if ordem is not None else 799), "loja_id": loja_id, "ordem": ordem,
        "motivo": "angariacao", "tempo_servico_min": 15, "manter_fechada": False, "nao_cabe": False,
        "chegada_prevista": None, "espera_min": None, "fora_de_horario": False,
        "adicionada_em": "2026-10-08T09:00:00Z", "adicionada_por": "u-rui", "removida_em": None,
        "estado": "pendente", "resultado": None, "concluida_em": None, **campos,
    }


def _retirada(loja_id, **campos):
    return _paragem(loja_id, None, removida_em="2026-10-08T10:00:00Z", **campos)


def _rota_do_dia(data, *paragens):
    """Uma rota escrita à mão na base (plano F3 §3), com um `calculo` para
    provar que a leitura o deixa de fora."""
    return {
        "id": f"r-{data}", "data": data, "estado": "planeada", "versao": 2, "hora_saida": "08:00",
        "hora_regresso_limite": "19:00", "inicio": None, "fim": None, "evitar_portagens": False,
        "paragens": list(paragens),
        "calculo": {"assinatura": "sha256:" + "0" * 64, "distancia_m": 1, "duracao_s": 1, "regresso_previsto": "09:00",
                    "depois_do_limite": False, "geometria": "_p~iF~ps|U", "calculado_em": "2026-10-08T09:30:00Z"},
        "criado_em": "2026-10-08T09:00:00Z", "criado_por": "u-rui", "atualizado_em": "2026-10-08T09:00:00.000000Z",
        "atualizado_por": "u-rui",
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

# Os membros como a guarda os devolve (para chamar a função da rota diretamente).
RUI_MEMBRO = {**RUI_UTILIZADOR, "crm_perfil": "utilizador", "crm_admin_master": False}
ANA_MEMBRO = {**ANA_ADMIN_DO_CRM, "crm_perfil": "admin", "crm_admin_master": False}


def _base(lojas=(), interacoes=(), rotas=(), lojas_coleccao=None, interacoes_coleccao=None, rotas_coleccao=None):
    return BaseFalsa({
        "crm_membros": list(MEMBROS),
        "users": list(USERS),
        "crm_regioes": [],
        "crm_lojas": lojas_coleccao if lojas_coleccao is not None else list(lojas),
        "crm_interacoes": interacoes_coleccao if interacoes_coleccao is not None else list(interacoes),
        "crm_rotas": rotas_coleccao if rotas_coleccao is not None else list(rotas),
    })


def _escritas(base):
    """As escritas em `crm_lojas`, `crm_interacoes` e `crm_rotas`, pela ordem de cada coleção."""
    return [
        c
        for coleccao in (base.crm_lojas, base.crm_interacoes, base.crm_rotas)
        for c in coleccao.registo
        if c[0] in ("insert_one", "update_one", "delete_one", "delete_many")
    ]


def _ids(coleccao):
    return [doc["id"] for doc in coleccao.sem_id()]


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
    `dependency_overrides`, a base do CRM trocada pelo único ponto e o relógio
    parado em AGORA. `sessao(utilizador, base)` devolve o cliente (com
    `cliente.base` e `cliente.apagar(loja_id)`, o `apagar` do LojasEditarTest)."""
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
        cliente.apagar = lambda loja_id: cliente.delete(f"{LOJAS_URL}/{loja_id}")
        return cliente

    return _montar


@pytest.fixture
def direto(monkeypatch):
    """Para chamar a função da rota diretamente (as corridas): a base trocada."""
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    monkeypatch.setattr(relogio, "agora", lambda: AGORA)

    def _montar(base):
        monkeypatch.setattr(crm.db, "obter_db", lambda: base)
        return base

    return _montar


# --- A rota: onde está, quem a guarda e o que lê -----------------------------------------------------


def test_a_rota_existe_vive_em_crm_lojas_e_e_do_escritorio():
    rota = _rota(UMA_LOJA_URL, "DELETE")
    assert rota.methods == {"DELETE"}
    assert rota.endpoint is apagar_loja
    assert rota.endpoint.__module__ == "crm.lojas"
    dependencias = _dependencias(rota)
    assert membro_crm_atual in dependencias
    assert [d for d in dependencias if hasattr(d, "perfis_crm")] == [ESCRITORIO]


def test_apagar_nao_le_o_corpo():
    """Como no autónomo (o DELETE não tem corpo): a única dependência direta é a guarda."""
    rota = _rota(UMA_LOJA_URL, "DELETE")
    assert [d.call for d in rota.dependant.dependencies] == [ESCRITORIO]
    assert corpo_json not in _dependencias(rota)


def test_a_mensagem_e_a_do_autonomo():
    assert MENSAGEM_COM_HISTORICO == COM_HISTORICO["detail"]["mensagem"]


def test_as_mensagens_da_loja_numa_rota_sao_as_do_plano():
    assert MENSAGEM_LOJA_EM_ROTA == EM_ROTA["detail"]["mensagem"]
    assert MENSAGEM_LOJA_ESTEVE_EM_ROTA == ESTEVE_EM_ROTA["detail"]["mensagem"]


def test_o_gancho_da_f5_esta_no_unico_sitio_que_decide_se_se_pode_apagar():
    """Plano §7, "Ganchos": na F5 as encomendas também impedem de apagar (o
    `podeApagar` do autónomo: "Etapa 2: recusar também…"). As paragens já
    contam desde a T3.24 (`_presa_em_rota`)."""
    assert "F5: bloquear se houver encomendas" in inspect.getsource(rotas_lojas._pode_apagar)
    assert "paragens" not in inspect.getsource(rotas_lojas._pode_apagar).split("F5:")[1].split("\n")[0]


# --- Apagar um engano -----------------------------------------------------------------------------------


def test_apagar_da_200_e_depois_404(sessao):
    """`apagarDa200EDepois404`: a loja sai da base, da lista e da ficha; e um
    segundo DELETE já dá 404."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe(), _bar()]))

    r = cliente.apagar(CAFE)

    assert (r.status_code, r.json()) == (200, APAGADA)
    assert r.json()["apagada"] is True, "um booleano JSON, não 1 (em Python, 1 == True)"
    assert _ids(cliente.base.crm_lojas) == [BAR]
    assert [loja["id"] for loja in cliente.get(LOJAS_URL).json()] == [BAR]
    for r in (cliente.get(f"{LOJAS_URL}/{CAFE}"), cliente.apagar(CAFE)):
        assert (r.status_code, r.json()) == (404, NAO_ENCONTRADA)


def test_apagar_le_a_loja_procura_o_historico_e_apaga_por_esta_ordem(sessao):
    """Sem transações: primeiro ler (404), depois o histórico (409), depois a
    loja e só no fim as mudanças de fase dela. Assim, se a loja não se apagar,
    o histórico dela fica inteiro."""
    ordem = []

    class Registada(ColeccaoFalsa):
        def _registar(self, *chamada):
            super()._registar(*chamada)
            ordem.append((self.nome, *chamada))

    base = _base(
        lojas_coleccao=Registada([_cafe()], nome="crm_lojas"),
        interacoes_coleccao=Registada([_mudanca(1, CAFE)], nome="crm_interacoes"),
        rotas_coleccao=Registada([_rota_do_dia(ONTEM, _retirada(CAFE))], nome="crm_rotas"),
    )

    assert sessao(RUI_UTILIZADOR, base).apagar(CAFE).status_code == 200
    assert ordem == [
        ("crm_lojas", "find_one", {"id": CAFE}, PROJECAO_ID),
        ("crm_interacoes", "find_one", {"loja_id": CAFE, **FILTRO_HISTORICO}, PROJECAO_ID),
        ("crm_rotas", "find", FILTRO_ROTAS, SEM_CALCULO),
        ("crm_lojas", "delete_one", {"id": CAFE}),
        ("crm_interacoes", "delete_many", {"loja_id": CAFE, **FILTRO_MUDANCAS_DE_FASE}),
    ]


def test_as_mudancas_de_fase_nao_impedem_apagar_e_vao_com_a_loja(sessao):
    """`asMudancasDeFaseNaoImpedemApagarEVaoComALoja`: um engano apaga-se,
    mesmo depois de lhe mudar a fase (pelo PATCH verdadeiro)."""
    cliente = sessao(RUI_UTILIZADOR)
    r = cliente.patch(f"{LOJAS_URL}/{CAFE}", json={"fase": "contactada", "atualizado_em": VERSAO})
    assert r.status_code == 200, r.text
    assert [i["resultado"] for i in cliente.base.crm_interacoes.sem_id()] == ["potencial→contactada"]

    r = cliente.apagar(CAFE)

    assert (r.status_code, r.json()) == (200, APAGADA), "Um engano apaga-se, mesmo depois de lhe mudar a fase."
    assert cliente.base.crm_lojas.docs == []
    assert cliente.base.crm_interacoes.docs == []


def test_so_as_mudancas_de_fase_da_propria_loja_vao_com_ela(sessao):
    """As interações das outras lojas ficam todas, também as mudanças de fase."""
    interacoes = [
        _mudanca(1, CAFE), _mudanca(2, BAR), _mudanca(3, CAFE, "contactada→amostra"),
        _interacao(4, BAR, "visita", "interessado"),
    ]
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe(), _bar()], interacoes=interacoes))

    assert cliente.apagar(CAFE).json() == APAGADA

    assert _ids(cliente.base.crm_lojas) == [BAR]
    assert cliente.base.crm_interacoes.sem_id() == [interacoes[1], interacoes[3]]


def test_o_historico_de_outras_lojas_nao_impede_de_apagar(sessao):
    interacoes = [_interacao(1, BAR, "visita"), _interacao(2, BAR, "nota")]
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe(), _bar()], interacoes=interacoes))
    assert cliente.apagar(CAFE).json() == APAGADA
    assert cliente.base.crm_interacoes.sem_id() == interacoes


def test_sem_interacoes_nenhumas_tambem_se_apaga(sessao):
    """A loja acabada de criar por engano: nada no histórico, e o `delete_many`
    corre na mesma (não apaga nada)."""
    cliente = sessao(RUI_UTILIZADOR)
    assert cliente.apagar(CAFE).json() == APAGADA
    assert cliente.base.crm_lojas.docs == []
    assert cliente.base.crm_interacoes.chamadas("delete_many") == [
        ("delete_many", {"loja_id": CAFE, **FILTRO_MUDANCAS_DE_FASE}),
    ]


# --- Com histórico não se apaga -----------------------------------------------------------------------


HISTORICO = ["visita", "chamada", "amostra", "entrega", "nota"]


@pytest.mark.parametrize("tipo", HISTORICO, ids=HISTORICO)
def test_uma_loja_com_historico_nao_se_apaga(sessao, tipo):
    """`umaLojaComHistoricoNaoSeApaga`: os tipos de interação que não são
    mudanças de fase (spec §5). 409 com só `codigo` e `mensagem`, a loja e as
    duas interações ficam, e nada se escreve."""
    interacoes = [_mudanca(1, CAFE), _interacao(2, CAFE, tipo)]
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe()], interacoes=interacoes))
    antes = cliente.base.crm_lojas.sem_id()

    r = cliente.apagar(CAFE)

    assert (r.status_code, r.json()) == (409, COM_HISTORICO)
    assert cliente.base.crm_lojas.sem_id() == antes
    assert cliente.base.crm_interacoes.sem_id() == interacoes
    assert _escritas(cliente.base) == []
    assert cliente.get(f"{LOJAS_URL}/{CAFE}").status_code == 200


def test_uma_so_interacao_que_nao_e_mudanca_de_fase_chega(sessao):
    """Sem mudanças de fase, só uma visita: 409 na mesma."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe()], interacoes=[_interacao(1, CAFE, "visita")]))
    assert (cliente.apagar(CAFE).status_code, len(cliente.base.crm_lojas.docs)) == (409, 1)


SEM_TIPO = {k: v for k, v in _interacao(1, CAFE, None).items() if k != "tipo"}
TIPOS_DUVIDOSOS = [
    ("sem o campo tipo", SEM_TIPO),
    ("tipo null", _interacao(1, CAFE, None)),
    ("tipo desconhecido", _interacao(1, CAFE, "reuniao")),
    ("mudanca_fase com espaço", _interacao(1, CAFE, "mudanca_fase ")),
]


@pytest.mark.parametrize("interacao", [c[1] for c in TIPOS_DUVIDOSOS], ids=[c[0] for c in TIPOS_DUVIDOSOS])
def test_na_duvida_uma_interacao_que_nao_e_exatamente_mudanca_de_fase_conta_como_historico(sessao, interacao):
    """O `tipo <> 'mudanca_fase'` com o `$ne` do Mongo: qualquer interação que
    não seja exatamente `mudanca_fase` impede de apagar, também uma sem tipo
    (no autónomo o tipo era NOT NULL). Na dúvida, não se apaga histórico."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe()], interacoes=[interacao]))
    assert (cliente.apagar(CAFE).status_code, len(cliente.base.crm_lojas.docs)) == (409, 1)
    assert cliente.base.crm_interacoes.sem_id() == [interacao]


# --- Uma loja numa rota não se apaga (F3, T3.24) ------------------------------------------------------


def _rotas_lidas(base):
    return base.crm_rotas.registo


@pytest.mark.parametrize("data", [HOJE, AMANHA], ids=["hoje", "amanhã"])
def test_numa_paragem_ativa_de_uma_rota_de_hoje_ou_do_futuro_da_409_loja_em_rota(sessao, data):
    """Plano F3 §1 "Apagar uma loja": 409 só com `codigo` e `mensagem`, a loja
    e as mudanças de fase ficam, nada se escreve, e as rotas leram-se pelo
    índice `paragens.loja_id`, sem o `calculo`."""
    rotas = [_rota_do_dia(data, _paragem(BAR, 0), _paragem(CAFE, 1))]
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe(), _bar()], interacoes=[_mudanca(1, CAFE)], rotas=rotas))
    antes = cliente.base.crm_rotas.sem_id()

    r = cliente.apagar(CAFE)

    assert (r.status_code, r.json()) == (409, EM_ROTA)
    assert _ids(cliente.base.crm_lojas) == [CAFE, BAR]
    assert len(cliente.base.crm_interacoes.docs) == 1
    assert cliente.base.crm_rotas.sem_id() == antes
    assert _escritas(cliente.base) == []
    assert _rotas_lidas(cliente.base) == [("find", FILTRO_ROTAS, SEM_CALCULO)]
    assert cliente.get(f"{LOJAS_URL}/{CAFE}").status_code == 200


def test_so_numa_rota_passada_da_409_com_a_mensagem_de_esteve_em_rota(sessao):
    """Correção "T3.24": a rota de ontem é só de leitura (`rota_fechada`), por
    isso "retire-a da rota" é impossível — o mesmo código, outra mensagem."""
    rotas = [_rota_do_dia(ONTEM, _paragem(CAFE, 0)), _rota_do_dia("2026-09-01", _paragem(CAFE, 0))]
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe()], rotas=rotas))
    r = cliente.apagar(CAFE)
    assert (r.status_code, r.json()) == (409, ESTEVE_EM_ROTA)
    assert _ids(cliente.base.crm_lojas) == [CAFE]
    assert _escritas(cliente.base) == []


def test_numa_rota_passada_e_noutra_de_hoje_ou_do_futuro_ganha_a_mensagem_da_atual(sessao):
    rotas = [_rota_do_dia(ONTEM, _paragem(CAFE, 0)), _rota_do_dia(AMANHA, _paragem(CAFE, 0))]
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe()], rotas=rotas))
    assert cliente.apagar(CAFE).json() == EM_ROTA


def test_so_numa_paragem_retirada_e_pendente_apaga_e_as_rotas_ficam_como_estavam(sessao):
    """Uma paragem retirada e ainda `pendente` não prende (§1): a loja
    apaga-se, as mudanças de fase vão com ela e as rotas não se tocam (a
    paragem fica, órfã — a rota é só de acrescentar)."""
    rotas = [_rota_do_dia(ONTEM, _retirada(CAFE)), _rota_do_dia(HOJE, _retirada(CAFE), _paragem(BAR, 0)), _rota_do_dia(AMANHA, _retirada(CAFE))]
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe(), _bar()], interacoes=[_mudanca(1, CAFE)], rotas=rotas))
    antes = cliente.base.crm_rotas.sem_id()

    r = cliente.apagar(CAFE)

    assert (r.status_code, r.json()) == (200, APAGADA)
    assert _ids(cliente.base.crm_lojas) == [BAR]
    assert cliente.base.crm_interacoes.docs == []
    assert cliente.base.crm_rotas.sem_id() == antes
    assert _rotas_lidas(cliente.base) == [("find", FILTRO_ROTAS, SEM_CALCULO)], "só a leitura: nunca uma escrita nas rotas"


@pytest.mark.parametrize("registo", ["feita", "nao_feita"])
@pytest.mark.parametrize("data, esperado", [(AMANHA, EM_ROTA), (ONTEM, ESTEVE_EM_ROTA)], ids=["amanhã", "ontem"])
def test_numa_paragem_retirada_com_registo_do_motorista_da_409(sessao, registo, data, esperado):
    """O motorista fez a visita e a paragem foi retirada: há um registo do
    terreno, e a loja não se apaga (§1: "ou numa paragem com registo")."""
    rotas = [_rota_do_dia(data, _retirada(CAFE, estado=registo, resultado="interessado", concluida_em="2026-10-09T10:00:00Z"))]
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe()], rotas=rotas))
    r = cliente.apagar(CAFE)
    assert (r.status_code, r.json()) == (409, esperado)
    assert _ids(cliente.base.crm_lojas) == [CAFE]
    assert _escritas(cliente.base) == []


def test_as_rotas_de_outras_lojas_nao_prendem(sessao):
    rotas = [_rota_do_dia(AMANHA, _paragem(BAR, 0)), _rota_do_dia(ONTEM, _paragem(BAR, 0, estado="feita"))]
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe(), _bar()], rotas=rotas))
    assert cliente.apagar(CAFE).json() == APAGADA
    assert _ids(cliente.base.crm_lojas) == [BAR]
    assert _rotas_lidas(cliente.base) == [("find", FILTRO_ROTAS, SEM_CALCULO)]


def test_com_historico_e_numa_rota_ganha_o_historico_e_as_rotas_nem_se_leem(sessao):
    """A ordem do plano §4: 404 → `loja_com_historico` → `loja_em_rota`."""
    rotas = [_rota_do_dia(AMANHA, _paragem(CAFE, 0))]
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe()], interacoes=[_interacao(1, CAFE, "visita")], rotas=rotas))
    r = cliente.apagar(CAFE)
    assert (r.status_code, r.json()) == (409, COM_HISTORICO)
    assert _rotas_lidas(cliente.base) == []
    assert _escritas(cliente.base) == []


def test_o_hoje_das_rotas_e_o_do_relogio_do_crm_em_lisboa(sessao, monkeypatch):
    """Às 23:30Z de 10 de outubro (WEST) já é dia 11 em Lisboa: a rota de dia
    10 passou a ser passada, e a de dia 11 é a de hoje."""
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe(), _bar()], rotas=[_rota_do_dia(HOJE, _paragem(CAFE, 0)), _rota_do_dia(AMANHA, _paragem(BAR, 0))]))
    monkeypatch.setattr(relogio, "agora", lambda: datetime(2026, 10, 10, 23, 30, tzinfo=UTC))
    assert cliente.apagar(CAFE).json() == ESTEVE_EM_ROTA

    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe()], rotas=[_rota_do_dia(AMANHA, _paragem(CAFE, 0))]))
    monkeypatch.setattr(relogio, "agora", lambda: datetime(2026, 10, 10, 23, 30, tzinfo=UTC))
    assert cliente.apagar(CAFE).json() == EM_ROTA


def test_quando_a_base_falha_a_ler_as_rotas_e_um_erro_e_nada_se_apaga(sessao):
    rotas = ColeccaoFalsa([], falhar={"find": RuntimeError("base em baixo")}, nome="crm_rotas")
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe()], interacoes=[_mudanca(1, CAFE)], rotas_coleccao=rotas), levantar=False)
    assert cliente.apagar(CAFE).status_code == 500
    assert len(cliente.base.crm_lojas.docs) == 1
    assert len(cliente.base.crm_interacoes.docs) == 1
    assert _escritas(cliente.base) == []


# --- Lojas que não existem ------------------------------------------------------------------------


def test_apagar_uma_loja_que_nao_existe_da_404_sem_olhar_para_o_historico(sessao):
    """Primeiro a loja (como o `bloquear` do autónomo), depois o histórico:
    interações órfãs de um id que não existe não dão 409, nem se apagam."""
    orfas = [_interacao(1, NAO_EXISTE, "visita"), _mudanca(2, NAO_EXISTE)]
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe()], interacoes=orfas))

    r = cliente.apagar(NAO_EXISTE)

    assert (r.status_code, r.json()) == (404, NAO_ENCONTRADA)
    assert cliente.base.crm_lojas.registo == [("find_one", {"id": NAO_EXISTE}, PROJECAO_ID)]
    assert cliente.base.crm_interacoes.registo == []
    assert cliente.base.crm_rotas.registo == []
    assert cliente.base.crm_interacoes.sem_id() == orfas


@pytest.mark.parametrize("loja_id", ['{"$ne": null}', "$where", "1"], ids=["operador", "dólar", "número"])
def test_o_id_do_caminho_e_so_texto(sessao, loja_id):
    """O `loja_id` chega sempre em texto: nunca um operador do Mongo."""
    cliente = sessao(RUI_UTILIZADOR)
    r = cliente.apagar(loja_id)
    assert (r.status_code, r.json()) == (404, NAO_ENCONTRADA)
    assert cliente.base.crm_lojas.registo == [("find_one", {"id": loja_id}, PROJECAO_ID)]
    assert len(cliente.base.crm_lojas.docs) == 1


# --- As corridas: sem transações --------------------------------------------------------------------


class LojasQueSomemEntretanto(ColeccaoFalsa):
    """Outra pessoa apaga a loja entre a leitura e o `delete_one` deste pedido."""

    async def delete_one(self, filtro):
        self.docs[:] = [doc for doc in self.docs if doc["id"] != filtro["id"]]
        return await super().delete_one(filtro)


def test_na_corrida_uma_loja_apagada_entretanto_da_404_e_nao_mexe_no_historico(sessao):
    """`deleted_count 0`: 404 (quem a apagou é que limpa as mudanças de fase)."""
    lojas = LojasQueSomemEntretanto([_cafe()], nome="crm_lojas")
    cliente = sessao(RUI_UTILIZADOR, _base(lojas_coleccao=lojas, interacoes=[_mudanca(1, CAFE)]))

    r = cliente.apagar(CAFE)

    assert (r.status_code, r.json()) == (404, NAO_ENCONTRADA)
    assert [c[0] for c in lojas.registo] == ["find_one", "delete_one"]
    assert cliente.base.crm_interacoes.chamadas("delete_many") == []
    assert len(cliente.base.crm_interacoes.docs) == 1


def test_dois_pedidos_ao_mesmo_tempo_so_um_apaga(direto):
    """A corrida a sério no duplo: os dois leem a loja e passam o histórico; o
    `delete_one` só apaga uma vez, o outro dá 404, e as mudanças de fase
    apagam-se uma só vez."""
    base = direto(_base(lojas=[_cafe(), _bar()], interacoes=[_mudanca(1, CAFE), _mudanca(2, BAR)]))

    async def _ao_mesmo_tempo():
        return await asyncio.gather(
            apagar_loja(CAFE, RUI_MEMBRO), apagar_loja(CAFE, ANA_MEMBRO), return_exceptions=True,
        )

    primeiro, segundo = correr(_ao_mesmo_tempo())

    assert primeiro == APAGADA
    assert isinstance(segundo, HTTPException)
    assert (segundo.status_code, segundo.detail) == (404, NAO_ENCONTRADA["detail"])
    assert [c[0] for c in base.crm_lojas.registo] == ["find_one", "find_one", "delete_one", "delete_one"]
    assert base.crm_interacoes.chamadas("delete_many") == [
        ("delete_many", {"loja_id": CAFE, **FILTRO_MUDANCAS_DE_FASE}),
    ]
    assert _ids(base.crm_lojas) == [BAR]
    assert _ids(base.crm_interacoes) == [_id(502)]


class LojasComUmaVisitaEntretanto(ColeccaoFalsa):
    """Uma visita (F4) regista-se entre a procura do histórico e o `delete_one`."""

    interacoes = None

    async def delete_one(self, filtro):
        self.interacoes.docs.append(_interacao(9, filtro["id"], "visita", "interessado"))
        return await super().delete_one(filtro)


def test_uma_interacao_que_chega_entretanto_nunca_se_apaga(sessao):
    """Corrida residual aceite (dossiê §5.12): a loja apaga-se, mas o
    `delete_many` só leva as `mudanca_fase` — a visita fica (órfã), e nunca se
    perde histórico verdadeiro."""
    interacoes = ColeccaoFalsa([_mudanca(1, CAFE)], nome="crm_interacoes")
    lojas = LojasComUmaVisitaEntretanto([_cafe()], nome="crm_lojas")
    lojas.interacoes = interacoes
    cliente = sessao(RUI_UTILIZADOR, _base(lojas_coleccao=lojas, interacoes_coleccao=interacoes))

    assert cliente.apagar(CAFE).json() == APAGADA

    assert lojas.docs == []
    assert [(i["tipo"], i["resultado"]) for i in interacoes.sem_id()] == [("visita", "interessado")]


# --- Quando a base falha ------------------------------------------------------------------------------


def test_quando_a_base_falha_ao_procurar_o_historico_e_um_erro_e_nada_se_apaga(sessao):
    interacoes = ColeccaoFalsa([_mudanca(1, CAFE)], falhar={"find_one": RuntimeError("base em baixo")})
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe()], interacoes_coleccao=interacoes), levantar=False)
    assert cliente.apagar(CAFE).status_code == 500
    assert len(cliente.base.crm_lojas.docs) == 1
    assert _escritas(cliente.base) == []


def test_quando_a_base_falha_ao_apagar_a_loja_e_um_erro_e_o_historico_fica(sessao):
    lojas = ColeccaoFalsa([_cafe()], falhar={"delete_one": RuntimeError("base em baixo")}, nome="crm_lojas")
    cliente = sessao(RUI_UTILIZADOR, _base(lojas_coleccao=lojas, interacoes=[_mudanca(1, CAFE)]), levantar=False)
    assert cliente.apagar(CAFE).status_code == 500
    assert len(lojas.docs) == 1
    assert [c[0] for c in cliente.base.crm_interacoes.registo] == ["find_one"], "Sem delete_many."
    assert len(cliente.base.crm_interacoes.docs) == 1


PESSOAL = "Café Central 912 345 678 u-rui rui@example.com Rui Costa"
FALHAS_DO_HISTORICO = [
    ("RuntimeError", RuntimeError(PESSOAL)),
    ("DuplicateKeyError", DuplicateKeyError(f"E11000 duplicate key error dup key: {PESSOAL}", 11000)),
    ("ServerSelectionTimeoutError", ServerSelectionTimeoutError(PESSOAL)),
]


@pytest.mark.parametrize("falha", [c[1] for c in FALHAS_DO_HISTORICO], ids=[c[0] for c in FALHAS_DO_HISTORICO])
def test_uma_falha_ao_apagar_as_mudancas_de_fase_nao_desfaz_nada_e_fica_no_registo(sessao, caplog, falha):
    """Sem transações: a loja já foi, e responde-se 200 (um 500 levava a
    pessoa a tentar de novo e a receber 404). As mudanças de fase ficam órfãs
    (ninguém as vê: a linha do tempo é por loja) e a falha fica numa linha
    `[crm]` no registo, sem dados pessoais (nem quem, nem a loja pelo nome,
    nem a mensagem da exceção) nem traceback."""
    interacoes = ColeccaoFalsa([_mudanca(1, CAFE)], falhar={"delete_many": falha}, nome="crm_interacoes")
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe(telefone="912 345 678")], interacoes_coleccao=interacoes))

    with caplog.at_level(logging.DEBUG, logger="crm"):
        r = cliente.apagar(CAFE)

    assert (r.status_code, r.json()) == (200, APAGADA)
    assert cliente.base.crm_lojas.docs == []
    assert len(interacoes.docs) == 1
    registos = [registo for registo in caplog.records if registo.name.startswith("crm")]
    assert [(registo.name, registo.levelno) for registo in registos] == [("crm.lojas", logging.ERROR)]
    mensagem = registos[0].getMessage()
    assert mensagem.startswith("[crm] ")
    assert CAFE in mensagem and type(falha).__name__ in mensagem
    for dado in ("Café", "912", "u-rui", "rui@example.com", "Rui Costa"):
        assert dado not in caplog.text, dado
    assert registos[0].exc_info is None, "Sem o traceback, que traz a mensagem da exceção."


def test_apagar_sem_falhas_nao_regista_nada(sessao, caplog):
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_cafe()], interacoes=[_mudanca(1, CAFE)]))
    with caplog.at_level(logging.DEBUG, logger="crm"):
        assert cliente.apagar(CAFE).status_code == 200
    assert [registo for registo in caplog.records if registo.name.startswith("crm")] == []


# --- Quem pode ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "utilizador", [ADMIN_MASTER, ANA_ADMIN_DO_CRM, RUI_UTILIZADOR], ids=["admin master", "admin", "utilizador"]
)
def test_o_escritorio_apaga(sessao, utilizador):
    cliente = sessao(utilizador)
    assert (cliente.apagar(CAFE).status_code, cliente.base.crm_lojas.docs) == (200, [])


def test_o_motorista_nao_apaga_lojas_na_f2(sessao):
    """As permissões do terreno chegam na F4 (plano §1, "Perfis por rota")."""
    cliente = sessao(ALVARO_MOTORISTA)
    r = cliente.apagar(CAFE)
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)
    assert cliente.base.crm_lojas.registo == []
    assert cliente.base.crm_interacoes.registo == []


def test_quem_nao_e_membro_recebe_403_sem_acesso(sessao):
    cliente = sessao(BEA_NAO_MEMBRO)
    r = cliente.apagar(CAFE)
    assert (r.status_code, r.json()) == (403, SEM_ACESSO)
    assert cliente.base.crm_lojas.registo == []


@pytest.mark.parametrize("bruto", [b"[", b"null", b'{"confirmar": true}'], ids=["partido", "null", "objeto"])
def test_um_corpo_no_delete_ignora_se(sessao, bruto):
    """O DELETE não lê o corpo (o autónomo mandava null): nem um JSON partido dá 400."""
    cliente = sessao(RUI_UTILIZADOR)
    r = cliente.request("DELETE", f"{LOJAS_URL}/{CAFE}", content=bruto, headers=JSON)
    assert (r.status_code, r.json()) == (200, APAGADA)


# --- De ponta a ponta: a sessão verdadeira do portal ---------------------------------------------

SEGREDO = "segredo-de-teste-crm-lojas-apagar"
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
    base = _base(lojas=[_cafe(), _bar()], interacoes=[_mudanca(1, BAR), _interacao(2, BAR, "visita")])
    monkeypatch.setattr(faturacao.auth, "obter_db", lambda: base)
    monkeypatch.setattr(crm.db, "obter_db", lambda: base)
    app = FastAPI()
    app.include_router(crm.router)
    cliente = TestClient(app)
    cliente.base = base
    return cliente


def test_sem_sessao_da_o_403_herdado_e_nada_muda(portal):
    """`semSessaoDa401ENadaMuda` (a metade do DELETE): no portal, sem
    cabeçalho é o 403 do HTTPBearer."""
    r = portal.delete(f"{LOJAS_URL}/{CAFE}")
    assert (r.status_code, r.json()) == (403, {"detail": "Not authenticated"})
    assert portal.base.crm_lojas.registo == []
    assert len(portal.base.crm_lojas.docs) == 2


def test_uma_conta_apagada_da_401_sessao_terminada(portal):
    r = portal.delete(f"{LOJAS_URL}/{CAFE}", headers=_cabecalho("u-apagada"))
    assert (r.status_code, r.json()) == (401, {"detail": "Sessão terminada"})
    assert portal.base.crm_lojas.registo == []


def test_de_ponta_a_ponta_criar_por_engano_mudar_a_fase_e_apagar(portal):
    rui = _cabecalho("u-rui")
    admin = _cabecalho("u-admin", email=ADMIN_LOCAL, role="admin")

    nova = {"nome": "Quiosque por engano", "fase": "potencial", "lat": 38.73, "lng": LNG, "origem_coords": "pin_manual"}
    r = portal.post(LOJAS_URL, json=nova, headers=rui)
    assert r.status_code == 201, r.text
    criada = r.json()
    r = portal.patch(
        f"{LOJAS_URL}/{criada['id']}", json={"fase": "contactada", "atualizado_em": criada["atualizado_em"]},
        headers=rui,
    )
    assert r.status_code == 200, r.text

    r = portal.delete(f"{LOJAS_URL}/{criada['id']}", headers=_cabecalho("u-alv"))
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)

    r = portal.delete(f"{LOJAS_URL}/{criada['id']}", headers=rui)
    assert (r.status_code, r.json()) == (200, APAGADA)
    assert portal.get(f"{LOJAS_URL}/{criada['id']}", headers=admin).json() == NAO_ENCONTRADA

    r = portal.delete(f"{LOJAS_URL}/{BAR}", headers=admin)
    assert (r.status_code, r.json()) == (409, COM_HISTORICO)

    assert portal.delete(f"{LOJAS_URL}/{CAFE}", headers=admin).json() == APAGADA
    assert [loja["nome"] for loja in portal.get(LOJAS_URL, headers=rui).json()] == ["Bar da Esquina"]
    assert [(i["loja_id"], i["tipo"]) for i in portal.base.crm_interacoes.sem_id()] == [
        (BAR, "mudanca_fase"), (BAR, "visita"),
    ]
