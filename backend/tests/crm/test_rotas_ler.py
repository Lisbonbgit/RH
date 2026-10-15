"""`GET /api/crm/rotas` e `GET /api/crm/rotas/{data}` — ler as rotas por dia
(plano F3 §4; T3.18).

As regras já estão provadas no domínio e nos módulos de baixo: os parâmetros
(`validador_rota.data_do_caminho`/`intervalo`, T3.4), a forma da resposta
(`formatar_rota.rota_api`/`resumo_rota_api`, T3.16) e as leituras
(`rotas_bd.ler`/`rotas_entre`/`lojas_da_rota`, T3.17). Aqui prova-se a rota
HTTP: quem entra, o que lê (com o filtro e a projeção exatos, e nunca uma
escrita), por que ordem, o que responde e com que "hoje".

- `GET /rotas?de=&ate=` → `{hoje, de, ate, rotas: [{id, data, estado,
  estado_efetivo, paragens}]}`, por `data`, com o intervalo por omissão hoje
  − 14 / hoje + 60 (cada extremo por si) e sem o `calculo` (correção "T3.17 /
  T3.18"). 422 em `de`/`ate` sem tocar na base.
- `GET /rotas/{data}` → a rota completa, com as lojas juntadas pela
  `PROJECAO_LOJA_ROTA`, ou a rota **virtual** de um dia sem rota (`existe:
  false`, com as horas e a fábrica das definições em vigor). Um dia passado
  lê-se `concluida` e só de leitura, com ou sem rota. `calculo_disponivel`
  diz se há `CRM_ORS_CHAVE` (nunca se chama o openrouteservice ao ler: a
  guarda do conftest prova-o). 422 em `data` (formato, ou mais de um ano).
- O "hoje" é o dia em Lisboa do relógio do CRM (`relogio.hoje()`), lido uma
  vez por pedido: às 23:30Z de 12 de outubro (WEST) já é dia 13.
- Só o escritório (admin e utilizador do CRM): o motorista recebe 403
  `sem_permissao`, quem não é membro 403 `sem_acesso_crm` e, sem sessão, os
  403/401 herdados do portal (de ponta a ponta, com a sessão verdadeira: o
  molde do test_lojas_editar.py).

Rotas por `TestClient` com `dependency_overrides[utilizador_atual]` e
`monkeypatch.setattr(crm.db, "obter_db", …)` (plano §10) sobre o duplo da base
(`tests/crm/duplos.py`); o relógio parado com `monkeypatch`.
"""
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
from crm.formatar_rota import PROJECAO_LOJA_ROTA, rota_api
from crm.pedidos import corpo_json
from crm.servicos import ors
from faturacao.auth import utilizador_atual

from .duplos import BaseFalsa

ROTAS_URL = "/api/crm/rotas"
ADMIN_LOCAL = "admin.local@example.com"

UTC = timezone.utc
# 23:30Z de 12 de outubro de 2026: em Lisboa (WEST, UTC+1) já é dia 13 — o
# "hoje" vem do relógio parado, em hora de Lisboa, e não do dia em UTC.
AGORA = datetime(2026, 10, 12, 23, 30, 15, 987654, tzinfo=UTC)
HOJE = "2026-10-13"  # uma terça-feira
ONTEM = "2026-10-12"
AMANHA = "2026-10-14"  # uma quarta-feira
DE_OMISSAO = "2026-09-29"  # hoje − 14
ATE_OMISSAO = "2026-12-12"  # hoje + 60
ULTIMO_DIA = "2027-10-13"  # hoje + 365, o último que se lê
DEPOIS_DO_ULTIMO = "2027-10-14"
# No inverno (WET, UTC+0) o dia em Lisboa é o de UTC.
AGORA_NO_INVERNO = datetime(2026, 12, 1, 23, 30, 0, tzinfo=UTC)

MEMBRO = "membro-1"
LOJA_A = "00000000-0000-4000-8000-00000000000a"
LOJA_B = "00000000-0000-4000-8000-00000000000b"
LOJA_C = "00000000-0000-4000-8000-00000000000c"
LOJA_D = "00000000-0000-4000-8000-00000000000d"
APAGADA = "00000000-0000-4000-8000-0000000000ff"

COMERCIO = (38.7075, -9.1364)
MARQUES = (38.7253, -9.15)
BELEM = (38.6979, -9.2065)
FABRICA_PADRAO = (38.7223, -9.1393)

# As definições em vigor sem nada guardado (`dominio.definicoes.PADROES`, já
# combinadas: as coordenadas e os minutos como números).
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

# A rota da API, pela ordem do plano F3 §4 (a mesma do test_formatar_rota.py).
CHAVES_ROTA_API = (
    "id", "data", "existe", "estado", "estado_efetivo", "editavel", "versao", "hoje",
    "hora_saida", "hora_regresso_limite", "evitar_portagens", "inicio", "fim",
    "limite_paragens", "calculo_disponivel", "calculo", "paragens", "blocos_google",
)
CHAVES_RESUMO_API = ("id", "data", "estado", "estado_efetivo", "paragens")
CHAVES_CALCULO_API = (
    "atual", "distancia_m", "duracao_s", "regresso_previsto", "depois_do_limite", "geometria", "calculado_em",
)

DATA = "Indique o dia no formato AAAA-MM-DD."
HORIZONTE = "Escolha um dia até um ano a partir de hoje."
FIM_ANTES_DO_INICIO = "O fim do intervalo tem de ser depois do início."
INTERVALO_LONGO = "O intervalo tem no máximo 120 dias."

SEM_PERMISSAO = {"detail": {"codigo": "sem_permissao", "mensagem": "Sem permissão para esta ação."}}
SEM_ACESSO = {"detail": {"codigo": "sem_acesso_crm", "mensagem": "Sem acesso ao CRM."}}

SEM_ID = {"_id": 0}
SEM_CALCULO = {"_id": 0, "calculo": 0}
PROJECAO_DEFINICOES = {"_id": 0, "chave": 1, "valor": 1}

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

# As duas rotas desta tarefa, para os testes de quem entra.
URLS = [ROTAS_URL, f"{ROTAS_URL}/{AMANHA}"]
IDS_URLS = ["lista", "dia"]
CAMINHOS = [(ROTAS_URL, "GET"), (ROTAS_URL + "/{data}", "GET")]


# --- montagem ------------------------------------------------------------------------------------


def _validacao(campos):
    return {"detail": {"codigo": "validacao", "mensagem": "Verifique os campos assinalados.", "campos": campos}}


def _guardada(chave, valor, quando="2026-10-01T08:00:00.000000Z", por="u-ana"):
    """Uma definição como fica gravada (o valor em texto)."""
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


def _calculo(**campos):
    return {
        "assinatura": "sha256:" + "0" * 64, "distancia_m": 12345, "duracao_s": 2345, "regresso_previsto": "12:30",
        "depois_do_limite": False, "geometria": "_p~iF~ps|U_ulLnnqC_mqNvxq`@", "calculado_em": "2026-10-10T09:05:00Z",
        **campos,
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


def _projetada(loja):
    return {campo: loja[campo] for campo in PROJECAO_LOJA_ROTA if campo != "_id"}


def _tres_paragens():
    # Pela ordem: B (0), C (1) e A (2, fechada à quarta); a D retirada.
    return [_paragem("a", LOJA_A, 2), _paragem("b", LOJA_B, 0), _retirada("d", LOJA_D), _paragem("c", LOJA_C, 1)]


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
    """O que o `rota_api` dá para esta rota: a referência da resposta."""
    return rota_api(
        rota,
        data=_dia(AMANHA if rota is None else rota["data"]),
        hoje=_dia(hoje),
        lojas=[_projetada(loja) for loja in lojas],
        definicoes=DEFINICOES_PADRAO if definicoes is None else definicoes,
        calculo_disponivel=calculo_disponivel,
    )


def _rota_http(caminho, metodo):
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


# --- As rotas: onde estão, quem as guarda e o que não leem --------------------------------


@pytest.mark.parametrize("caminho, metodo", CAMINHOS, ids=IDS_URLS)
def test_as_rotas_existem_e_vivem_em_crm_rotas(caminho, metodo):
    rota = _rota_http(caminho, metodo)
    assert rota.methods == {metodo}
    assert rota.endpoint.__module__ == rotas_http.__name__ == "crm.rotas"


@pytest.mark.parametrize("caminho, metodo", CAMINHOS, ids=IDS_URLS)
def test_so_o_escritorio_le_as_rotas(caminho, metodo):
    """Exatamente uma guarda de perfil, a do escritório, sobre `membro_crm_atual`."""
    dependencias = _dependencias(_rota_http(caminho, metodo))
    assert membro_crm_atual in dependencias
    assert [d for d in dependencias if hasattr(d, "perfis_crm")] == [ESCRITORIO]


@pytest.mark.parametrize("caminho, metodo", CAMINHOS, ids=IDS_URLS)
def test_ler_nao_le_o_corpo(caminho, metodo):
    assert corpo_json not in _dependencias(_rota_http(caminho, metodo))


# --- GET /rotas ----------------------------------------------------------------------------------


def test_sem_rotas_a_lista_vem_vazia_com_o_intervalo_por_omissao(sessao):
    """`hoje` é o dia em Lisboa do relógio parado (23:30Z de dia 12 → dia 13)
    e o intervalo por omissão é hoje − 14 / hoje + 60, pela ordem das chaves
    do plano."""
    r = sessao().get(ROTAS_URL)
    assert r.status_code == 200
    assert list(r.json()) == ["hoje", "de", "ate", "rotas"]
    assert r.json() == {"hoje": HOJE, "de": DE_OMISSAO, "ate": ATE_OMISSAO, "rotas": []}


def test_no_inverno_o_hoje_e_o_dia_de_utc(sessao, monkeypatch):
    monkeypatch.setattr(relogio, "agora", lambda: AGORA_NO_INVERNO)
    r = sessao().get(ROTAS_URL)
    assert r.status_code == 200
    assert (r.json()["hoje"], r.json()["de"], r.json()["ate"]) == ("2026-12-01", "2026-11-17", "2027-01-30")


def test_le_as_rotas_do_intervalo_com_o_filtro_e_a_projecao_exatos(sessao):
    """Uma leitura só, pelo texto dos dias (o índice único de `data`) e sem o
    `calculo` (correção "T3.17 / T3.18"); as lojas e as definições não se
    leem na lista."""
    cliente = sessao()
    assert cliente.get(ROTAS_URL).status_code == 200
    assert cliente.base.crm_rotas.registo == [
        ("find", {"data": {"$gte": DE_OMISSAO, "$lte": ATE_OMISSAO}}, SEM_CALCULO),
    ]
    assert cliente.base.crm_lojas.registo == []
    assert cliente.base.crm_definicoes.registo == []


def test_a_lista_vem_por_data_com_o_resumo_de_cada_rota(sessao):
    """Gravadas fora de ordem; cada linha com as 5 chaves do plano, pela
    ordem, com `paragens` a contar só as ativas e o `estado_efetivo` do
    fecho simples: a de ontem é `concluida`."""
    base = _base(rotas=[
        _rota("2026-10-20", _tres_paragens(), id_="r-20", estado="planeada"),
        _rota(ONTEM, [_paragem("a", LOJA_A, 0)], id_="r-12", calculo=_calculo()),
        _rota(HOJE, [], id_="r-13"),
    ])
    r = sessao(ADMIN_MASTER, base).get(ROTAS_URL)
    assert r.status_code == 200
    assert r.json()["rotas"] == [
        {"id": "r-12", "data": ONTEM, "estado": "rascunho", "estado_efetivo": "concluida", "paragens": 1},
        {"id": "r-13", "data": HOJE, "estado": "rascunho", "estado_efetivo": "rascunho", "paragens": 0},
        {"id": "r-20", "data": "2026-10-20", "estado": "planeada", "estado_efetivo": "planeada", "paragens": 3},
    ]
    assert [tuple(linha) for linha in r.json()["rotas"]] == [CHAVES_RESUMO_API] * 3


def test_a_lista_nao_leva_o_calculo_nem_as_paragens(sessao):
    """A geometria tem dezenas de KB por rota: na lista não vai, nem a lista
    das paragens (só a contagem)."""
    base = _base(rotas=[_rota(AMANHA, _tres_paragens(), calculo=_calculo(geometria="geometria-enorme"))])
    r = sessao(ZE_UTILIZADOR, base).get(ROTAS_URL)
    assert r.status_code == 200
    assert "geometria-enorme" not in r.text
    assert "p-a" not in r.text
    assert LOJA_A not in r.text


def test_os_extremos_do_intervalo_entram_e_os_dias_de_fora_nao(sessao):
    base = _base(rotas=[
        _rota("2026-09-28", id_="r-fora-1"),
        _rota(DE_OMISSAO, id_="r-de"),
        _rota(ATE_OMISSAO, id_="r-ate"),
        _rota("2026-12-13", id_="r-fora-2"),
    ])
    r = sessao(ZE_UTILIZADOR, base).get(ROTAS_URL)
    assert [linha["id"] for linha in r.json()["rotas"]] == ["r-de", "r-ate"]


def test_de_e_ate_explicitos_devolvem_se_e_filtram(sessao):
    base = _base(rotas=[
        _rota("2026-11-02", id_="r-fora"),
        _rota("2026-10-20", id_="r-20"),
        _rota("2026-10-05", id_="r-05"),
    ])
    cliente = sessao(ZE_UTILIZADOR, base)
    r = cliente.get(ROTAS_URL, params={"de": "2026-10-01", "ate": "2026-10-31"})
    assert r.status_code == 200
    assert (r.json()["hoje"], r.json()["de"], r.json()["ate"]) == (HOJE, "2026-10-01", "2026-10-31")
    assert [linha["id"] for linha in r.json()["rotas"]] == ["r-05", "r-20"]
    assert cliente.base.crm_rotas.registo == [
        ("find", {"data": {"$gte": "2026-10-01", "$lte": "2026-10-31"}}, SEM_CALCULO),
    ]


def test_cada_extremo_e_por_si_o_da_omissao(sessao):
    cliente = sessao()
    so_de = cliente.get(ROTAS_URL, params={"de": "2026-10-10"}).json()
    assert (so_de["de"], so_de["ate"]) == ("2026-10-10", ATE_OMISSAO)
    so_ate = cliente.get(ROTAS_URL, params={"ate": "2026-10-20"}).json()
    assert (so_ate["de"], so_ate["ate"]) == (DE_OMISSAO, "2026-10-20")


def test_o_mesmo_dia_e_um_intervalo_de_um_dia(sessao):
    base = _base(rotas=[_rota(HOJE, id_="r-13"), _rota(AMANHA, id_="r-14"), _rota(ONTEM, id_="r-12")])
    r = sessao(ZE_UTILIZADOR, base).get(ROTAS_URL, params={"de": HOJE, "ate": HOJE})
    assert r.status_code == 200
    assert [linha["id"] for linha in r.json()["rotas"]] == ["r-13"]


def test_o_intervalo_de_120_dias_passa_e_o_de_121_nao(sessao):
    """Contam-se os dois extremos (T3.4): de 1 de outubro a 28 de janeiro são
    120 dias; até 29 de janeiro são 121."""
    cliente = sessao()
    r = cliente.get(ROTAS_URL, params={"de": "2026-10-01", "ate": "2027-01-28"})
    assert (r.status_code, r.json()["de"], r.json()["ate"]) == (200, "2026-10-01", "2027-01-28")
    r = cliente.get(ROTAS_URL, params={"de": "2026-10-01", "ate": "2027-01-29"})
    assert (r.status_code, r.json()) == (422, _validacao({"ate": INTERVALO_LONGO}))


@pytest.mark.parametrize(
    "parametros, campos",
    [
        ({"de": "2026-1-1"}, {"de": DATA}),
        ({"de": ""}, {"de": DATA}),
        ({"ate": "13/10/2026"}, {"ate": DATA}),
        ({"de": "2026-10-02", "ate": "2026-10-01"}, {"ate": FIM_ANTES_DO_INICIO}),
        ({"de": "abc", "ate": "xyz"}, {"de": DATA, "ate": DATA}),
        ({"de": "2026-02-30", "ate": "2026-10-01"}, {"de": DATA}),
    ],
    ids=["de-curto", "de-vazio", "ate-barras", "ate-antes-de-de", "os-dois", "de-30-de-fevereiro"],
)
def test_os_parametros_errados_dao_422_sem_tocar_na_base(sessao, parametros, campos):
    """Um parâmetro presente, mesmo vazio (`?de=`), tem de ser um dia; com um
    mal escrito não se comparam os dois. Os erros em `de` e depois `ate`."""
    cliente = sessao()
    r = cliente.get(ROTAS_URL, params=parametros)
    assert (r.status_code, r.json()) == (422, _validacao(campos))
    assert list(r.json()["detail"]["campos"]) == list(campos)
    assert cliente.base.crm_rotas.registo == []


def test_uma_data_estragada_na_base_e_um_erro_e_nunca_outra_forma(sessao):
    """Uma `data` que não é um dia `AAAA-MM-DD` (escrita à mão) dentro do
    intervalo é um 500 (ValueError do `resumo_rota_api`), não uma linha
    com outra forma."""
    base = _base(rotas=[_rota("2026-10-5", id_="r-estragada")])
    with pytest.raises(ValueError):
        sessao(ZE_UTILIZADOR, base).get(ROTAS_URL)


# --- GET /rotas/{data} ---------------------------------------------------------------------------


def test_um_dia_sem_rota_e_a_rota_virtual_com_as_definicoes_em_vigor(sessao):
    """`existe: false`, com as horas e a fábrica das definições guardadas (e
    não dos padrões), `editavel` porque a primeira paragem a cria, sem
    cálculo nem paragens, pela ordem das chaves do plano F3 §4."""
    base = _base(definicoes=[
        _guardada("rota_hora_saida", "07:30"),
        _guardada("rota_hora_regresso", "18:00"),
        _guardada("fabrica_lat", "41.149600"),
        _guardada("fabrica_lng", "-8.611000"),
    ])
    r = sessao(ZE_UTILIZADOR, base).get(f"{ROTAS_URL}/{AMANHA}")
    assert r.status_code == 200
    assert tuple(r.json()) == CHAVES_ROTA_API
    assert r.json() == {
        "id": None, "data": AMANHA, "existe": False, "estado": None, "estado_efetivo": None, "editavel": True,
        "versao": None, "hoje": HOJE, "hora_saida": "07:30", "hora_regresso_limite": "18:00",
        "evitar_portagens": False,
        "inicio": {"lat": 41.1496, "lng": -8.611, "fabrica": True},
        "fim": {"lat": 41.1496, "lng": -8.611, "fabrica": True},
        "limite_paragens": 48, "calculo_disponivel": False, "calculo": None, "paragens": [], "blocos_google": [],
    }


def test_sem_nada_guardado_a_rota_virtual_leva_os_padroes(sessao):
    r = sessao().get(f"{ROTAS_URL}/{AMANHA}")
    assert r.status_code == 200
    assert r.json() == _api(None, [])
    assert (r.json()["hora_saida"], r.json()["hora_regresso_limite"]) == ("08:00", "19:00")
    assert r.json()["inicio"] == {"lat": FABRICA_PADRAO[0], "lng": FABRICA_PADRAO[1], "fabrica": True}


def test_a_rota_virtual_le_a_rota_e_as_definicoes_e_nunca_as_lojas(sessao):
    """A rota pelo texto do dia e sem o `_id`; as definições uma vez; as lojas
    não (não há paragens)."""
    cliente = sessao()
    assert cliente.get(f"{ROTAS_URL}/{AMANHA}").status_code == 200
    assert cliente.base.crm_rotas.registo == [("find_one", {"data": AMANHA}, SEM_ID)]
    assert cliente.base.crm_definicoes.registo == [("find", {}, PROJECAO_DEFINICOES)]
    assert cliente.base.crm_lojas.registo == []


def test_um_dia_passado_sem_rota_le_se_concluido_e_so_de_leitura(sessao):
    r = sessao().get(f"{ROTAS_URL}/{ONTEM}")
    assert r.status_code == 200
    assert (r.json()["existe"], r.json()["estado"], r.json()["estado_efetivo"], r.json()["editavel"]) == (
        False, None, "concluida", False,
    )
    assert r.json()["data"] == ONTEM


def test_hoje_sem_rota_e_editavel(sessao):
    r = sessao().get(f"{ROTAS_URL}/{HOJE}")
    assert (r.json()["data"], r.json()["hoje"], r.json()["estado_efetivo"], r.json()["editavel"]) == (
        HOJE, HOJE, None, True,
    )


def test_com_rota_vem_completa_com_as_lojas_juntadas(sessao):
    """A rota do dia com as paragens ativas por ordem, numeradas na secção
    "rota", cada uma com a sua loja pela projeção (nunca a morada, as notas
    nem a pessoa de contacto), os links e os blocos do Google — tal e qual o
    `rota_api` (T3.16) sobre a rota lida e as lojas projetadas."""
    rota = _rota(AMANHA, _tres_paragens(), estado="planeada")
    base = _base(rotas=[rota], lojas=_lojas())
    cliente = sessao(ADMIN_MASTER, base)
    r = cliente.get(f"{ROTAS_URL}/{AMANHA}")
    assert r.status_code == 200
    resposta = r.json()
    assert tuple(resposta) == CHAVES_ROTA_API
    assert resposta == _api(rota, _lojas()[:3])
    assert (resposta["id"], resposta["existe"], resposta["estado"], resposta["versao"], resposta["editavel"]) == (
        "r-1", True, "planeada", 3, True,
    )
    assert [(p["id"], p["numero"], p["seccao"], p["loja"]["nome"]) for p in resposta["paragens"]] == [
        ("p-b", 1, "rota", "Pastelaria B"), ("p-c", 2, "rota", "Mercearia C"), ("p-a", None, "fechada", "Café A"),
    ]
    assert resposta["paragens"][1]["loja"] == {
        "nome": "Mercearia C", "fase": "cliente", "lat": BELEM[0], "lng": BELEM[1], "telefone": "+351911111111",
        "janela1_inicio": "09:00", "janela1_fim": "12:00", "janela2_inicio": None, "janela2_fim": None,
        "dias_fechada": [],
    }
    assert set(resposta["paragens"][0]["links"]) == {"google", "waze"}
    assert [(b["de"], b["ate"], b["quantas"]) for b in resposta["blocos_google"]] == [(1, 2, 2)]
    for pessoal in ("Rua Secreta", "não sai na rota", "Sr. Silva", "p-d", LOJA_D):
        assert pessoal not in r.text


def test_as_lojas_leem_se_pela_projecao_da_rota_e_pela_ordem_das_paragens_ativas(sessao):
    base = _base(rotas=[_rota(AMANHA, _tres_paragens())], lojas=_lojas())
    cliente = sessao(ZE_UTILIZADOR, base)
    assert cliente.get(f"{ROTAS_URL}/{AMANHA}").status_code == 200
    assert cliente.base.crm_rotas.registo == [("find_one", {"data": AMANHA}, SEM_ID)]
    assert cliente.base.crm_lojas.registo == [("find", {"id": {"$in": [LOJA_B, LOJA_C, LOJA_A]}}, PROJECAO_LOJA_ROTA)]
    assert cliente.base.crm_definicoes.registo == [("find", {}, PROJECAO_DEFINICOES)]


def test_uma_loja_apagada_entretanto_fica_sem_loja(sessao):
    base = _base(rotas=[_rota(AMANHA, [_paragem("b", LOJA_B, 0), _paragem("x", APAGADA, 1)])], lojas=_lojas())
    r = sessao(ZE_UTILIZADOR, base).get(f"{ROTAS_URL}/{AMANHA}")
    assert r.status_code == 200
    assert [(p["id"], p["numero"], p["seccao"], p["loja"] is None, p["links"]) for p in r.json()["paragens"]] == [
        ("p-b", 1, "rota", False, {"google": r.json()["paragens"][0]["links"]["google"],
                                   "waze": r.json()["paragens"][0]["links"]["waze"]}),
        ("p-x", None, "sem_loja", True, None),
    ]
    assert r.json()["paragens"][0]["loja"]["nome"] == "Pastelaria B"
    assert r.json() == _api(base.crm_rotas.sem_id()[0], _lojas())


def test_uma_rota_passada_le_se_concluida_e_so_de_leitura(sessao):
    rota = _rota(ONTEM, [_paragem("b", LOJA_B, 0)], estado="planeada")
    r = sessao(ZE_UTILIZADOR, _base(rotas=[rota], lojas=_lojas())).get(f"{ROTAS_URL}/{ONTEM}")
    assert r.status_code == 200
    assert (r.json()["existe"], r.json()["estado"], r.json()["estado_efetivo"], r.json()["editavel"]) == (
        True, "planeada", "concluida", False,
    )
    assert r.json() == _api(rota, _lojas())


def test_uma_rota_com_registo_do_motorista_e_so_de_leitura(sessao):
    rota = _rota(AMANHA, [_paragem("b", LOJA_B, 0), _feita("c", LOJA_C, 1)])
    r = sessao(ZE_UTILIZADOR, _base(rotas=[rota], lojas=_lojas())).get(f"{ROTAS_URL}/{AMANHA}")
    assert r.status_code == 200
    assert (r.json()["estado_efetivo"], r.json()["editavel"]) == ("rascunho", False)
    assert r.json()["paragens"][1]["estado"] == "feita"


def test_a_rota_do_dia_traz_o_calculo_com_a_geometria_e_sem_a_assinatura(sessao):
    """Ao contrário da lista, a rota do dia lê-se inteira: o `calculo` vem com
    a geometria e com `atual` (aqui falso: a assinatura gravada não é a de
    agora), nunca com a assinatura."""
    rota = _rota(AMANHA, _tres_paragens(), calculo=_calculo())
    r = sessao(ZE_UTILIZADOR, _base(rotas=[rota], lojas=_lojas())).get(f"{ROTAS_URL}/{AMANHA}")
    assert r.status_code == 200
    calculo = r.json()["calculo"]
    assert tuple(calculo) == CHAVES_CALCULO_API
    assert (calculo["atual"], calculo["geometria"], calculo["distancia_m"]) == (False, _calculo()["geometria"], 12345)
    assert "assinatura" not in r.text
    assert r.json() == _api(rota, _lojas())


def test_calculo_disponivel_segue_a_chave_do_openrouteservice(sessao, monkeypatch):
    """Com `CRM_ORS_CHAVE` no ambiente é `true`; sem ela, ou vazia, `false`.
    Ler nunca chama o openrouteservice (a guarda do conftest falharia)."""
    cliente = sessao()
    monkeypatch.setenv(ors.VARIAVEL_CHAVE, "chave-de-teste")
    assert cliente.get(f"{ROTAS_URL}/{AMANHA}").json()["calculo_disponivel"] is True
    monkeypatch.setenv(ors.VARIAVEL_CHAVE, "")
    assert cliente.get(f"{ROTAS_URL}/{AMANHA}").json()["calculo_disponivel"] is False
    monkeypatch.delenv(ors.VARIAVEL_CHAVE)
    assert cliente.get(f"{ROTAS_URL}/{AMANHA}").json()["calculo_disponivel"] is False


def test_calculo_disponivel_com_chave_tambem_na_rota_que_existe(sessao, monkeypatch):
    rota = _rota(AMANHA, [_paragem("b", LOJA_B, 0)])
    cliente = sessao(ZE_UTILIZADOR, _base(rotas=[rota], lojas=_lojas()))
    monkeypatch.setenv(ors.VARIAVEL_CHAVE, "chave-de-teste")
    r = cliente.get(f"{ROTAS_URL}/{AMANHA}")
    assert r.json()["calculo_disponivel"] is True
    assert r.json() == _api(rota, _lojas(), calculo_disponivel=True)


@pytest.mark.parametrize(
    "data, mensagem",
    [
        ("abc", DATA),
        ("2026-1-1", DATA),
        ("2026-02-30", DATA),
        ("20261014", DATA),
        ("2028-01-01", HORIZONTE),
        (DEPOIS_DO_ULTIMO, HORIZONTE),
    ],
    ids=["abc", "curta", "30-de-fevereiro", "sem-tracos", "2028", "hoje-mais-366"],
)
def test_uma_data_errada_da_422_sem_tocar_na_base(sessao, data, mensagem):
    cliente = sessao()
    r = cliente.get(f"{ROTAS_URL}/{data}")
    assert (r.status_code, r.json()) == (422, _validacao({"data": mensagem}))
    assert cliente.base.crm_rotas.registo == []
    assert cliente.base.crm_definicoes.registo == []


def test_o_ultimo_dia_que_se_le_e_hoje_mais_365(sessao):
    r = sessao().get(f"{ROTAS_URL}/{ULTIMO_DIA}")
    assert r.status_code == 200
    assert (r.json()["data"], r.json()["existe"], r.json()["editavel"]) == (ULTIMO_DIA, False, True)


@pytest.mark.parametrize("url", URLS, ids=IDS_URLS)
def test_o_relogio_le_se_uma_vez_por_pedido(sessao, monkeypatch, url):
    """Um só "hoje" por pedido: o da validação é o da resposta (à meia-noite
    não se valida com um dia e responde com outro)."""
    cliente = sessao()
    leituras = []

    def _agora():
        leituras.append(1)
        return AGORA

    monkeypatch.setattr(relogio, "agora", _agora)
    assert cliente.get(url).status_code == 200
    assert len(leituras) == 1


@pytest.mark.parametrize("url", URLS, ids=IDS_URLS)
def test_ler_nunca_escreve(sessao, url):
    base = _base(rotas=[_rota(AMANHA, _tres_paragens(), calculo=_calculo())], lojas=_lojas())
    cliente = sessao(ZE_UTILIZADOR, base)
    antes = (base.crm_rotas.sem_id(), base.crm_lojas.sem_id())
    assert cliente.get(url).status_code == 200
    assert _operacoes(base) <= {"find", "find_one"}
    assert (base.crm_rotas.sem_id(), base.crm_lojas.sem_id()) == antes


# --- Quem entra ----------------------------------------------------------------------------------


@pytest.mark.parametrize("url", URLS, ids=IDS_URLS)
def test_o_escritorio_le_as_rotas(sessao, url):
    base = _base(rotas=[_rota(AMANHA, [_paragem("b", LOJA_B, 0)])], lojas=_lojas())
    for pessoa in (ADMIN_MASTER, ANA_ADMIN_DO_CRM, ZE_UTILIZADOR):
        assert sessao(pessoa, base).get(url).status_code == 200


@pytest.mark.parametrize("url", URLS, ids=IDS_URLS)
def test_o_motorista_recebe_403_sem_permissao(sessao, url):
    cliente = sessao(ALVARO_MOTORISTA)
    r = cliente.get(url)
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)
    assert cliente.base.crm_rotas.registo == []


@pytest.mark.parametrize("url", URLS, ids=IDS_URLS)
def test_quem_nao_e_membro_recebe_403_sem_acesso_crm(sessao, url):
    cliente = sessao(BEA_NAO_MEMBRO)
    r = cliente.get(url)
    assert (r.status_code, r.json()) == (403, SEM_ACESSO)
    assert cliente.base.crm_rotas.registo == []


# --- De ponta a ponta: a sessão verdadeira do portal ---------------------------------------------

SEGREDO = "segredo-de-teste-crm-rotas-ler"
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
    base = _base(rotas=[_rota(AMANHA, _tres_paragens(), estado="planeada")], lojas=_lojas())
    monkeypatch.setattr(faturacao.auth, "obter_db", lambda: base)
    monkeypatch.setattr(crm.db, "obter_db", lambda: base)
    app = FastAPI()
    app.include_router(crm.router)
    cliente = TestClient(app)
    cliente.base = base
    return cliente


@pytest.mark.parametrize("url", URLS, ids=IDS_URLS)
def test_sem_sessao_da_o_403_herdado(portal, url):
    """No portal, sem cabeçalho é o 403 do HTTPBearer (o frontend trata-o
    como sessão em falta)."""
    r = portal.get(url)
    assert (r.status_code, r.json()) == (403, {"detail": "Not authenticated"})
    assert portal.base.crm_rotas.registo == []


@pytest.mark.parametrize("url", URLS, ids=IDS_URLS)
def test_uma_conta_apagada_da_401_sessao_terminada(portal, url):
    r = portal.get(url, headers=_cabecalho("u-apagada"))
    assert (r.status_code, r.json()) == (401, {"detail": "Sessão terminada"})
    assert portal.base.crm_rotas.registo == []


def test_de_ponta_a_ponta_o_escritorio_le_a_lista_e_o_dia(portal):
    ze = _cabecalho("u-ze", email="ze@example.com")
    admin = _cabecalho("u-admin", email=ADMIN_LOCAL, role="admin")

    r = portal.get(ROTAS_URL, headers=_cabecalho("u-alv", email="alvaro@example.com"))
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)
    r = portal.get(f"{ROTAS_URL}/{AMANHA}", headers=_cabecalho("u-bea", email="bea@example.com"))
    assert (r.status_code, r.json()) == (403, SEM_ACESSO)

    r = portal.get(ROTAS_URL, headers=ze)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "hoje": HOJE, "de": DE_OMISSAO, "ate": ATE_OMISSAO,
        "rotas": [{"id": "r-1", "data": AMANHA, "estado": "planeada", "estado_efetivo": "planeada", "paragens": 3}],
    }

    r = portal.get(f"{ROTAS_URL}/{AMANHA}", headers=ze)
    assert r.status_code == 200, r.text
    rota = r.json()
    assert (rota["existe"], rota["estado"], rota["editavel"], rota["calculo_disponivel"]) == (
        True, "planeada", True, False,
    )
    assert [p["numero"] for p in rota["paragens"]] == [1, 2, None]
    assert portal.get(f"{ROTAS_URL}/{AMANHA}", headers=admin).json() == rota

    r = portal.get(f"{ROTAS_URL}/{ONTEM}", headers=admin)
    assert (r.json()["existe"], r.json()["estado_efetivo"], r.json()["editavel"]) == (False, "concluida", False)
    assert _operacoes(portal.base) <= {"find", "find_one"}
