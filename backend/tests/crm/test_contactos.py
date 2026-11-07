"""`/api/crm/lojas/{loja_id}/contactos` — os contactos de uma loja (desenho dos
contactos §3, "API", "Regras" e "Último contacto"; dossiê §5.11).

As regras puras estão em test_dominio_contactos.py; aqui prova-se a rota: quem
entra, a ordem das recusas, o que fica gravado em `crm_interacoes` e na loja, e
as falhas entre uma escrita e a outra.

Rotas por `TestClient` com `dependency_overrides[utilizador_atual]` e
`monkeypatch.setattr(crm.db, "obter_db", …)`, com o relógio parado; no fim, de
ponta a ponta com a sessão verdadeira do portal. O `except Exception` da escrita
da loja esconderia uma falha no duplo: por isso os testes do POST verificam a
loja gravada e que não ficou nenhuma linha `[crm]` no registo. O `$max` e o
repetido provam-se também no Mongo verdadeiro, em test_mongo_local.py.
"""
import logging
import time
from datetime import datetime, timezone

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError

import crm
import crm.db
import faturacao.auth
from crm import contactos as rotas_contactos
from crm import relogio
from crm.auth import ESCRITORIO, membro_crm_atual
from crm.dominio.contactos import MENSAGEM_CLIENT_UUID, MENSAGEM_DATA, MENSAGEM_DATA_FORA, MENSAGEM_RESUMO, MENSAGEM_TIPO
from crm.pedidos import corpo_json
from faturacao.auth import utilizador_atual

from .duplos import BaseFalsa, ColeccaoFalsa
from .formatos import instantes_fora_do_formato

ADMIN_LOCAL = "admin.local@example.com"
JSON = {"Content-Type": "application/json"}

UTC = timezone.utc
# Um sábado de inverno (WET): o dia de Lisboa é o de UTC.
AGORA = datetime(2026, 11, 7, 10, 30, 15, 987654, tzinfo=UTC)
AGORA_INSTANTE = "2026-11-07T10:30:15Z"
HOJE = "2026-11-07"

CRIADA_EM = "2026-10-03T09:00:00Z"
VERSAO = "2026-10-03T09:00:00.250000Z"

VALIDACAO = "Verifique os campos assinalados."
LOJA_NAO_ENCONTRADA = {"detail": {"codigo": "nao_encontrado", "mensagem": "Loja não encontrada."}}
CONTACTO_NAO_ENCONTRADO = {"detail": {"codigo": "nao_encontrado", "mensagem": "Contacto não encontrado."}}
JSON_INVALIDO = {"detail": {"codigo": "json_invalido", "mensagem": "O pedido não é JSON válido."}}
SEM_PERMISSAO = {"detail": {"codigo": "sem_permissao", "mensagem": "Sem permissão para esta ação."}}
SEM_ACESSO = {"detail": {"codigo": "sem_acesso_crm", "mensagem": "Sem acesso ao CRM."}}

PROJECAO_AUTOR = {"_id": 0, "id": 1, "name": 1}

CAMPOS_CONTACTO = ["id", "numero", "tipo", "data", "resumo", "autor", "pode_alterar", "corrigido"]


def _id(n):
    """Um uuid4 em texto, fixo para os testes serem legíveis."""
    return f"00000000-0000-4000-8000-{n:012d}"


CAFE, BAR = _id(1), _id(2)
NAO_EXISTE = _id(999)
UUID_DO_BLOCO = _id(500)

CONTACTOS_URL = f"/api/crm/lojas/{CAFE}/contactos"
LOJA_URL = f"/api/crm/lojas/{CAFE}"


def _um_contacto_url(contacto_id, loja_id=CAFE):
    return f"/api/crm/lojas/{loja_id}/contactos/{contacto_id}"


def _validacao(campos):
    return {"detail": {"codigo": "validacao", "mensagem": VALIDACAO, "campos": campos}}


def _loja(numero=1, **outros):
    return {
        "id": _id(numero),
        "nome": "Café Central",
        "fase": "potencial",
        "fase_desde": CRIADA_EM,
        "regiao_id": None,
        "morada": None,
        "codigo_postal": None,
        "localidade": None,
        "lat": 38.7108,
        "lng": -9.1369,
        "loc": {"type": "Point", "coordinates": [-9.1369, 38.7108]},
        "origem_coords": "pin_manual",
        "precisao_m": None,
        "google_place_id": None,
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


def _linha(numero=1, ocorrida_em="2026-11-05T12:00:00Z", tipo="visita", **outros):
    """Um contacto gravado, do Rui, no Café Central."""
    return {
        "id": _id(100 + numero),
        "loja_id": CAFE,
        "tipo": tipo,
        "resultado": None,
        "notas": f"Resumo {numero}.",
        "paragem_id": None,
        "utilizador_id": "u-rui",
        "ocorrida_em": ocorrida_em,
        "criado_em": ocorrida_em,
        "editado_em": None,
        "client_uuid": None,
        **outros,
    }


def _corpo(**outros):
    return {"tipo": "visita", "data": HOJE, "resumo": "  Falou-se do verão.  ", **outros}


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
    {"id": "u-gil", "email": "gil@example.com", "name": "Gil Matos", "role": "admin",
     "password": "$2b$12$hash-do-gil"},
    {"id": "u-tia", "email": "tia@example.com", "name": "Tia Ramos", "role": "colaborador",
     "password": "$2b$12$hash-da-tia"},
]
MEMBROS = [
    {"id": "m-rui", "user_id": "u-rui", "perfil": "utilizador", "criado_em": "2026-10-01T09:00:00Z"},
    {"id": "m-ana", "user_id": "u-ana", "perfil": "admin", "criado_em": "2026-10-01T09:00:00Z"},
    {"id": "m-alv", "user_id": "u-alv", "perfil": "motorista", "criado_em": "2026-10-02T09:00:00Z"},
    # Admin no portal, mas só utilizador no CRM: o `role` não conta.
    {"id": "m-gil", "user_id": "u-gil", "perfil": "utilizador", "criado_em": "2026-10-02T09:00:00Z"},
    {"id": "m-tia", "user_id": "u-tia", "perfil": "utilizador", "criado_em": "2026-10-02T09:00:00Z"},
]

ADMIN_MASTER = {"user_id": "u-admin", "email": ADMIN_LOCAL, "role": "admin"}
RUI_UTILIZADOR = {"user_id": "u-rui", "email": "rui@example.com", "role": "colaborador"}
ANA_ADMIN_DO_CRM = {"user_id": "u-ana", "email": "ana@example.com", "role": "contabilista"}
ALVARO_MOTORISTA = {"user_id": "u-alv", "email": "alvaro@example.com", "role": "gerente"}
BEA_NAO_MEMBRO = {"user_id": "u-bea", "email": "bea@example.com", "role": "colaborador"}
GIL_ADMIN_DO_PORTAL = {"user_id": "u-gil", "email": "gil@example.com", "role": "admin"}
TIA_UTILIZADORA = {"user_id": "u-tia", "email": "tia@example.com", "role": "colaborador"}


def _base(lojas=None, interacoes=(), interacoes_coleccao=None, lojas_coleccao=None, users=None):
    return BaseFalsa({
        "crm_membros": list(MEMBROS),
        "users": list(USERS) if users is None else users,
        "crm_lojas": lojas_coleccao if lojas_coleccao is not None else list([_loja()] if lojas is None else lojas),
        "crm_interacoes": interacoes_coleccao if interacoes_coleccao is not None else list(interacoes),
    })


def _escritas(base):
    return [
        c
        for coleccao in (base.crm_lojas, base.crm_interacoes)
        for c in coleccao.registo
        if c[0] in ("insert_one", "update_one", "delete_one", "delete_many")
    ]


def _leituras_e_escritas(base):
    return base.crm_lojas.registo + base.crm_interacoes.registo


def _guardada(base, numero=1):
    [loja] = [d for d in base.crm_lojas.sem_id() if d["id"] == _id(numero)]
    return loja


def _ultimos(base, numero=1):
    loja = _guardada(base, numero)
    return loja["ultima_interacao_em"], loja["ultima_visita_ou_entrega_em"]


def _linhas_crm(caplog):
    return [registo for registo in caplog.records if registo.name.startswith("crm")]


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
    """Uma app só com o router do CRM, a sessão do portal trocada, a base do
    CRM trocada pelo único ponto e o relógio parado em AGORA."""
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


def _relogio_em(monkeypatch, *partes):
    momento = datetime(*partes, tzinfo=UTC)
    monkeypatch.setattr(relogio, "agora", lambda: momento)


# --- As rotas: onde estão e quem as guarda -----------------------------------------------------------

ROTAS = [
    ("GET", "/api/crm/lojas/{loja_id}/contactos", rotas_contactos.listar_contactos),
    ("POST", "/api/crm/lojas/{loja_id}/contactos", rotas_contactos.criar_contacto),
    ("PATCH", "/api/crm/lojas/{loja_id}/contactos/{contacto_id}", rotas_contactos.alterar_contacto),
    ("DELETE", "/api/crm/lojas/{loja_id}/contactos/{contacto_id}", rotas_contactos.apagar_contacto),
]


@pytest.mark.parametrize("metodo, caminho, funcao", ROTAS, ids=["listar", "criar", "alterar", "apagar"])
def test_as_rotas_vivem_em_crm_contactos_e_sao_do_escritorio(metodo, caminho, funcao):
    rota = _rota(caminho, metodo)
    assert rota.endpoint is funcao
    assert rota.endpoint.__module__ == "crm.contactos"
    dependencias = _dependencias(rota)
    assert membro_crm_atual in dependencias
    assert [d for d in dependencias if hasattr(d, "perfis_crm")] == [ESCRITORIO]


def test_criar_responde_201():
    assert _rota(ROTAS[1][1], "POST").status_code == 201


@pytest.mark.parametrize("metodo, caminho", [(m, c) for m, c, _ in ROTAS[1:3]], ids=["criar", "alterar"])
def test_a_guarda_de_perfil_vem_antes_do_corpo(metodo, caminho):
    """Correções do plano, linha "T1.3 / T2.15"."""
    assert [d.call for d in _rota(caminho, metodo).dependant.dependencies] == [ESCRITORIO, corpo_json]


@pytest.mark.parametrize("metodo, caminho", [(ROTAS[0][0], ROTAS[0][1]), (ROTAS[3][0], ROTAS[3][1])], ids=["listar", "apagar"])
def test_listar_e_apagar_nao_leem_o_corpo(metodo, caminho):
    assert [d.call for d in _rota(caminho, metodo).dependant.dependencies] == [ESCRITORIO]


TODAS = [
    ("GET", CONTACTOS_URL, None),
    ("POST", CONTACTOS_URL, _corpo()),
    ("PATCH", _um_contacto_url(_id(101)), {"resumo": "Outro."}),
    ("DELETE", _um_contacto_url(_id(101)), None),
]
IDS_TODAS = ["listar", "criar", "alterar", "apagar"]


def _pedir(cliente, metodo, url, corpo, **opcoes):
    if corpo is None:
        return cliente.request(metodo, url, **opcoes)
    return cliente.request(metodo, url, json=corpo, **opcoes)


@pytest.mark.parametrize("metodo, url, corpo", TODAS, ids=IDS_TODAS)
def test_o_motorista_nao_entra_e_nada_se_le(sessao, metodo, url, corpo):
    cliente = sessao(ALVARO_MOTORISTA, _base(interacoes=[_linha()]))
    r = _pedir(cliente, metodo, url, corpo)
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)
    assert _leituras_e_escritas(cliente.base) == []


@pytest.mark.parametrize("metodo, url, corpo", TODAS, ids=IDS_TODAS)
def test_quem_nao_e_membro_nao_entra_e_nada_se_le(sessao, metodo, url, corpo):
    cliente = sessao(BEA_NAO_MEMBRO, _base(interacoes=[_linha()]))
    r = _pedir(cliente, metodo, url, corpo)
    assert (r.status_code, r.json()) == (403, SEM_ACESSO)
    assert _leituras_e_escritas(cliente.base) == []


@pytest.mark.parametrize("metodo, url", [("POST", CONTACTOS_URL), ("PATCH", _um_contacto_url(_id(101)))], ids=["criar", "alterar"])
def test_json_partido_da_400(sessao, metodo, url):
    cliente = sessao(RUI_UTILIZADOR)
    r = cliente.request(metodo, url, content=b"[", headers=JSON)
    assert (r.status_code, r.json()) == (400, JSON_INVALIDO)
    assert _leituras_e_escritas(cliente.base) == []


# --- GET -----------------------------------------------------------------------------------------------


def test_sem_contactos_a_lista_vem_vazia_com_o_hoje(sessao):
    r = sessao(RUI_UTILIZADOR).get(CONTACTOS_URL)
    assert (r.status_code, r.json()) == (200, {"hoje": HOJE, "contactos": []})
    assert list(r.json()) == ["hoje", "contactos"]


def test_uma_loja_que_nao_existe_da_404(sessao):
    cliente = sessao(RUI_UTILIZADOR)
    r = cliente.get(f"/api/crm/lojas/{NAO_EXISTE}/contactos")
    assert (r.status_code, r.json()) == (404, LOJA_NAO_ENCONTRADA)
    assert cliente.base.crm_interacoes.registo == []


def test_a_lista_vem_do_mais_recente_para_o_mais_antigo_com_a_forma_da_api(sessao):
    interacoes = [
        _linha(1, "2026-11-01T12:00:00Z", "chamada"),
        _linha(2, "2026-11-05T12:00:00Z", "visita", utilizador_id="u-ana"),
        _linha(3, "2026-11-03T12:00:00Z", "mensagem", editado_em="2026-11-04T09:00:00Z"),
    ]
    r = sessao(RUI_UTILIZADOR, _base(interacoes=interacoes)).get(CONTACTOS_URL)

    assert r.status_code == 200
    assert r.json() == {"hoje": HOJE, "contactos": [
        {"id": _id(102), "numero": 3, "tipo": "visita", "data": "2026-11-05", "resumo": "Resumo 2.",
         "autor": "Ana Reis", "pode_alterar": False, "corrigido": False},
        {"id": _id(103), "numero": 2, "tipo": "mensagem", "data": "2026-11-03", "resumo": "Resumo 3.",
         "autor": "Rui Costa", "pode_alterar": True, "corrigido": True},
        {"id": _id(101), "numero": 1, "tipo": "chamada", "data": "2026-11-01", "resumo": "Resumo 1.",
         "autor": "Rui Costa", "pode_alterar": True, "corrigido": False},
    ]}
    assert [list(contacto) for contacto in r.json()["contactos"]] == [CAMPOS_CONTACTO] * 3


def test_a_lista_so_traz_visitas_chamadas_e_mensagens_desta_loja(sessao):
    interacoes = [
        _linha(1, tipo="visita"),
        _linha(2, tipo="mudanca_fase", resultado="potencial→contactada"),
        _linha(3, tipo="amostra"),
        _linha(4, tipo="entrega"),
        _linha(5, tipo="nota"),
        _linha(6, tipo="chamada", loja_id=BAR),
    ]
    r = sessao(RUI_UTILIZADOR, _base(lojas=[_loja(), _loja(2)], interacoes=interacoes)).get(CONTACTOS_URL)
    assert [c["id"] for c in r.json()["contactos"]] == [_id(101)]
    assert r.json()["contactos"][0]["numero"] == 1


def test_a_data_e_o_dia_de_lisboa_e_nunca_o_corte_do_texto(sessao):
    """Às 23:30Z do verão já é o dia seguinte em Lisboa."""
    r = sessao(RUI_UTILIZADOR, _base(interacoes=[_linha(1, "2026-07-15T23:30:00Z")])).get(CONTACTOS_URL)
    assert r.json()["contactos"][0]["data"] == "2026-07-16"


def test_o_hoje_do_get_e_o_dia_de_lisboa_do_relogio(sessao, monkeypatch):
    cliente = sessao(RUI_UTILIZADOR)
    _relogio_em(monkeypatch, 2026, 7, 15, 23, 30)
    assert cliente.get(CONTACTOS_URL).json()["hoje"] == "2026-07-16"


def test_os_autores_leem_se_de_uma_vez_sem_o_email(sessao):
    interacoes = [_linha(1), _linha(2, utilizador_id="u-ana"), _linha(3), _linha(4, utilizador_id="u-admin")]
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes=interacoes))

    r = cliente.get(CONTACTOS_URL)

    assert cliente.base.users.chamadas("find") == [
        ("find", {"id": {"$in": ["u-admin", "u-ana", "u-rui"]}}, PROJECAO_AUTOR),
    ]
    assert "example.com" not in r.text
    assert sorted({c["autor"] for c in r.json()["contactos"]}) == ["Administrador Principal", "Ana Reis", "Rui Costa"]


def test_um_autor_cuja_conta_ja_nao_existe_e_a_conta_removida(sessao):
    r = sessao(RUI_UTILIZADOR, _base(interacoes=[_linha(1, utilizador_id="u-que-saiu")])).get(CONTACTOS_URL)
    assert r.json()["contactos"][0]["autor"] == "Conta removida"


def test_sem_contactos_nao_se_perguntam_as_contas(sessao):
    cliente = sessao(RUI_UTILIZADOR)
    cliente.get(CONTACTOS_URL)
    assert cliente.base.users.chamadas("find") == []


@pytest.mark.parametrize("utilizador, pode", [
    (RUI_UTILIZADOR, True),
    (TIA_UTILIZADORA, False),
    (ANA_ADMIN_DO_CRM, True),
    (ADMIN_MASTER, True),
    (GIL_ADMIN_DO_PORTAL, False),
], ids=["quem escreveu", "outro utilizador", "admin do CRM", "admin master", "admin do portal só utilizador no CRM"])
def test_pode_alterar_segue_o_perfil_do_crm_e_o_autor(sessao, utilizador, pode):
    r = sessao(utilizador, _base(interacoes=[_linha()])).get(CONTACTOS_URL)
    assert r.json()["contactos"][0]["pode_alterar"] is pode


@pytest.mark.parametrize("utilizador", [RUI_UTILIZADOR, ANA_ADMIN_DO_CRM, ADMIN_MASTER], ids=["autor", "admin", "master"])
def test_uma_linha_de_uma_paragem_sai_sem_pode_alterar_para_ninguem(sessao, utilizador):
    r = sessao(utilizador, _base(interacoes=[_linha(paragem_id=_id(300))])).get(CONTACTOS_URL)
    assert r.json()["contactos"][0]["pode_alterar"] is False


def test_o_get_nao_escreve_nada(sessao):
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes=[_linha()]))
    cliente.get(CONTACTOS_URL)
    assert _escritas(cliente.base) == []


# --- POST ----------------------------------------------------------------------------------------------


def test_guardar_um_contacto_de_hoje_grava_a_linha_e_responde_201_com_a_lista(sessao, caplog):
    cliente = sessao(RUI_UTILIZADOR)

    with caplog.at_level(logging.DEBUG, logger="crm"):
        r = cliente.post(CONTACTOS_URL, json=_corpo(client_uuid=UUID_DO_BLOCO))

    assert r.status_code == 201, r.text
    [gravada] = cliente.base.crm_interacoes.sem_id()
    assert list(gravada.items()) == list({
        "id": gravada["id"],
        "loja_id": CAFE,
        "tipo": "visita",
        "resultado": None,
        "notas": "Falou-se do verão.",
        "paragem_id": None,
        "utilizador_id": "u-rui",
        "ocorrida_em": AGORA_INSTANTE,
        "criado_em": AGORA_INSTANTE,
        "editado_em": None,
        "client_uuid": UUID_DO_BLOCO,
    }.items())
    assert instantes_fora_do_formato(gravada) == []
    assert r.json() == {"hoje": HOJE, "contactos": [{
        "id": gravada["id"], "numero": 1, "tipo": "visita", "data": HOJE, "resumo": "Falou-se do verão.",
        "autor": "Rui Costa", "pode_alterar": True, "corrigido": False,
    }]}
    assert _ultimos(cliente.base) == (AGORA_INSTANTE, AGORA_INSTANTE)
    assert _linhas_crm(caplog) == []


def test_uma_data_passada_fica_as_12_de_lisboa_desse_dia(sessao):
    cliente = sessao(RUI_UTILIZADOR)

    assert cliente.post(CONTACTOS_URL, json=_corpo(data="2026-07-15")).status_code == 201
    assert cliente.post(CONTACTOS_URL, json=_corpo(data="2026-01-15")).status_code == 201

    assert [linha["ocorrida_em"] for linha in cliente.base.crm_interacoes.docs] == [
        "2026-07-15T11:00:00Z", "2026-01-15T12:00:00Z",
    ]
    assert [c["data"] for c in cliente.get(CONTACTOS_URL).json()["contactos"]] == ["2026-07-15", "2026-01-15"]


def test_o_hoje_da_validacao_e_o_dia_de_lisboa_do_mesmo_instante(sessao, monkeypatch):
    """Às 23:30Z do verão, em Lisboa já é dia 16: dia 16 é hoje, e a linha
    grava o instante do pedido."""
    cliente = sessao(RUI_UTILIZADOR)
    _relogio_em(monkeypatch, 2026, 7, 15, 23, 30)

    r = cliente.post(CONTACTOS_URL, json=_corpo(data="2026-07-16"))

    assert r.status_code == 201, r.text
    assert r.json()["hoje"] == "2026-07-16"
    assert cliente.base.crm_interacoes.docs[0]["ocorrida_em"] == "2026-07-15T23:30:00Z"
    assert r.json()["contactos"][0]["data"] == "2026-07-16"


def test_o_relogio_le_se_uma_so_vez_em_cada_escrita(sessao, monkeypatch):
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes=[_linha()]))
    leituras = []

    def _contar():
        leituras.append(1)
        return AGORA

    monkeypatch.setattr(relogio, "agora", _contar)
    pedidos = [
        ("POST", CONTACTOS_URL, _corpo()),
        ("PATCH", _um_contacto_url(_id(101)), {"resumo": "Outro."}),
        ("DELETE", _um_contacto_url(_id(101)), None),
    ]
    for metodo, url, corpo in pedidos:
        leituras.clear()
        assert _pedir(cliente, metodo, url, corpo).status_code < 300
        assert len(leituras) == 1, metodo


@pytest.mark.parametrize("corpo, campos", [
    ({}, {"tipo": MENSAGEM_TIPO, "data": MENSAGEM_DATA, "resumo": MENSAGEM_RESUMO}),
    (_corpo(tipo="nota"), {"tipo": MENSAGEM_TIPO}),
    (_corpo(data="2026-11-08"), {"data": MENSAGEM_DATA_FORA}),
    (_corpo(data="1999-12-31"), {"data": MENSAGEM_DATA_FORA}),
    (_corpo(data="ontem"), {"data": MENSAGEM_DATA}),
    (_corpo(resumo="   "), {"resumo": MENSAGEM_RESUMO}),
    (_corpo(resumo="r" * 5001), {"resumo": "O resumo tem no máximo 5000 caracteres."}),
    (_corpo(client_uuid="x"), {"client_uuid": MENSAGEM_CLIENT_UUID}),
    (_corpo(client_uuid={"$ne": None}), {"client_uuid": MENSAGEM_CLIENT_UUID}),
], ids=["vazio", "tipo", "data futura", "antes de 2000", "data inválida", "resumo vazio", "resumo comprido",
        "client_uuid", "operador do Mongo"])
def test_um_corpo_invalido_da_422_por_campo_sem_ler_a_base(sessao, corpo, campos):
    cliente = sessao(RUI_UTILIZADOR)
    r = cliente.post(CONTACTOS_URL, json=corpo)
    assert (r.status_code, r.json()) == (422, _validacao(campos))
    assert _leituras_e_escritas(cliente.base) == []


def test_o_corpo_vem_antes_da_loja(sessao):
    cliente = sessao(RUI_UTILIZADOR)
    r = cliente.post(f"/api/crm/lojas/{NAO_EXISTE}/contactos", json={})
    assert r.status_code == 422


def test_guardar_numa_loja_que_nao_existe_da_404_e_nada_se_grava(sessao):
    cliente = sessao(RUI_UTILIZADOR)
    r = cliente.post(f"/api/crm/lojas/{NAO_EXISTE}/contactos", json=_corpo())
    assert (r.status_code, r.json()) == (404, LOJA_NAO_ENCONTRADA)
    assert _escritas(cliente.base) == []


def test_as_chaves_que_o_servidor_decide_ignoram_se(sessao):
    cliente = sessao(RUI_UTILIZADOR)
    r = cliente.post(CONTACTOS_URL, json=_corpo(
        id=_id(7), loja_id=BAR, utilizador_id="u-ana", paragem_id=_id(8), resultado="x", ocorrida_em="y", editado_em="z",
    ))
    assert r.status_code == 201, r.text
    [gravada] = cliente.base.crm_interacoes.sem_id()
    assert gravada["id"] != _id(7)
    assert (gravada["loja_id"], gravada["utilizador_id"], gravada["paragem_id"]) == (CAFE, "u-rui", None)
    assert (gravada["resultado"], gravada["ocorrida_em"], gravada["editado_em"]) == (None, AGORA_INSTANTE, None)


@pytest.mark.parametrize("corpo", [_corpo(), _corpo(client_uuid=None)], ids=["ausente", "null"])
def test_sem_client_uuid_grava_null_e_nao_procura_repetidos(sessao, corpo):
    cliente = sessao(RUI_UTILIZADOR)

    assert cliente.post(CONTACTOS_URL, json=corpo).status_code == 201
    assert cliente.post(CONTACTOS_URL, json=corpo).status_code == 201

    assert [linha["client_uuid"] for linha in cliente.base.crm_interacoes.docs] == [None, None]
    assert cliente.base.crm_interacoes.chamadas("find_one") == []


def test_um_contacto_com_data_antiga_renumera_os_outros(sessao):
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes=[_linha(1, "2026-11-05T12:00:00Z")]))

    r = cliente.post(CONTACTOS_URL, json=_corpo(data="2026-10-01"))

    assert [(c["numero"], c["data"]) for c in r.json()["contactos"]] == [(2, "2026-11-05"), (1, "2026-10-01")]


def test_guardar_um_contacto_nao_muda_a_fase_nem_o_atualizado_em_da_loja(sessao):
    cliente = sessao(RUI_UTILIZADOR)
    antes = _guardada(cliente.base)

    assert cliente.post(CONTACTOS_URL, json=_corpo()).status_code == 201

    depois = _guardada(cliente.base)
    assert {c: v for c, v in depois.items() if not c.startswith("ultima_")} == {
        c: v for c, v in antes.items() if not c.startswith("ultima_")
    }
    assert (depois["fase"], depois["fase_desde"], depois["atualizado_em"]) == ("potencial", CRIADA_EM, VERSAO)
    [atualizacao] = cliente.base.crm_lojas.chamadas("update_one")
    assert list(atualizacao[2]) == ["$max"]


# --- POST: o último contacto ----------------------------------------------------------------------------


@pytest.mark.parametrize("tipo, visita", [("visita", AGORA_INSTANTE), ("chamada", None), ("mensagem", None)])
def test_so_a_visita_sobe_a_ultima_visita(sessao, caplog, tipo, visita):
    cliente = sessao(RUI_UTILIZADOR)

    with caplog.at_level(logging.DEBUG, logger="crm"):
        assert cliente.post(CONTACTOS_URL, json=_corpo(tipo=tipo)).status_code == 201

    assert _ultimos(cliente.base) == (AGORA_INSTANTE, visita)
    assert _linhas_crm(caplog) == []


def test_um_contacto_antigo_nao_faz_recuar_o_ultimo_contacto(sessao, caplog):
    loja = _loja(ultima_interacao_em="2026-11-01T12:00:00Z", ultima_visita_ou_entrega_em="2026-10-20T11:00:00Z")
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[loja]))

    with caplog.at_level(logging.DEBUG, logger="crm"):
        assert cliente.post(CONTACTOS_URL, json=_corpo(data="2026-10-26")).status_code == 201

    assert _ultimos(cliente.base) == ("2026-11-01T12:00:00Z", "2026-10-26T12:00:00Z")
    assert _linhas_crm(caplog) == []


def test_uma_loja_de_antes_sem_os_campos_ganha_os_na_mesma(sessao, caplog):
    loja = _loja()
    del loja["ultima_interacao_em"]
    del loja["ultima_visita_ou_entrega_em"]
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[loja]))

    with caplog.at_level(logging.DEBUG, logger="crm"):
        assert cliente.post(CONTACTOS_URL, json=_corpo()).status_code == 201

    assert _ultimos(cliente.base) == (AGORA_INSTANTE, AGORA_INSTANTE)
    assert _linhas_crm(caplog) == []


FALHAS = [
    pytest.param(RuntimeError("loja Café Central da D. Amélia"), id="erro qualquer"),
    pytest.param(ServerSelectionTimeoutError("mongodb://utilizador:segredo@host"), id="sem ligação"),
]


@pytest.mark.parametrize("falha", FALHAS)
def test_uma_falha_ao_subir_a_loja_nao_desfaz_o_contacto(sessao, caplog, falha):
    lojas = ColeccaoFalsa([_loja()], falhar={"update_one": falha}, nome="crm_lojas")
    cliente = sessao(RUI_UTILIZADOR, _base(lojas_coleccao=lojas))

    with caplog.at_level(logging.DEBUG, logger="crm"):
        r = cliente.post(CONTACTOS_URL, json=_corpo(resumo="Dados pessoais do resumo", client_uuid=UUID_DO_BLOCO))

    assert r.status_code == 201
    assert len(r.json()["contactos"]) == 1
    assert len(cliente.base.crm_interacoes.docs) == 1
    [registo] = _linhas_crm(caplog)
    assert registo.levelno == logging.ERROR
    assert registo.getMessage() == (
        f"[crm] loja {CAFE}: o contacto mudou, mas o último contacto da loja não se atualizou "
        f"({type(falha).__name__})"
    )
    for dado in ("Dados pessoais", "Amélia", "segredo", "rui@example.com", "u-rui", UUID_DO_BLOCO):
        assert dado not in caplog.text, dado


def test_depois_da_falha_entre_a_linha_e_a_loja_o_reenvio_acerta_a_loja_sem_outra_linha(sessao, caplog):
    """A falha entre o `insert_one` e o `$max`, seguida de um reenvio com o
    mesmo `client_uuid`: a linha fica uma só e a loja sobe com o `tipo` e o
    `ocorrida_em` da linha gravada."""
    lojas = ColeccaoFalsa([_loja()], falhar={"update_one": RuntimeError("x")}, nome="crm_lojas")
    cliente = sessao(RUI_UTILIZADOR, _base(lojas_coleccao=lojas))
    corpo = _corpo(client_uuid=UUID_DO_BLOCO, data="2026-11-01")

    assert cliente.post(CONTACTOS_URL, json=corpo).status_code == 201
    assert _ultimos(cliente.base) == (None, None)

    lojas.falhar.clear()
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="crm"):
        r = cliente.post(CONTACTOS_URL, json={**corpo, "tipo": "chamada", "data": HOJE, "resumo": "Outro texto."})

    assert r.status_code == 201
    assert len(cliente.base.crm_interacoes.docs) == 1
    assert [(c["tipo"], c["data"], c["resumo"]) for c in r.json()["contactos"]] == [
        ("visita", "2026-11-01", "Falou-se do verão."),
    ]
    assert _ultimos(cliente.base) == ("2026-11-01T12:00:00Z", "2026-11-01T12:00:00Z")
    assert _linhas_crm(caplog) == []


def test_uma_falha_a_gravar_a_linha_e_um_erro_e_a_loja_nao_sobe(sessao):
    interacoes = ColeccaoFalsa(falhar={"insert_one": RuntimeError("x")}, nome="crm_interacoes")
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes_coleccao=interacoes), levantar=False)

    assert cliente.post(CONTACTOS_URL, json=_corpo()).status_code == 500
    assert _ultimos(cliente.base) == (None, None)


# --- POST: o client_uuid repetido -----------------------------------------------------------------------


def test_um_repetido_ja_gravado_nao_cria_outra_linha_e_responde_com_a_lista(sessao, caplog):
    linha = _linha(1, "2026-11-05T12:00:00Z", "visita", client_uuid=UUID_DO_BLOCO)
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes=[linha]))

    with caplog.at_level(logging.DEBUG, logger="crm"):
        r = cliente.post(CONTACTOS_URL, json=_corpo(client_uuid=UUID_DO_BLOCO))

    assert r.status_code == 201
    assert cliente.base.crm_interacoes.chamadas("insert_one") == []
    assert [c["id"] for c in r.json()["contactos"]] == [_id(101)]
    assert _ultimos(cliente.base) == ("2026-11-05T12:00:00Z", "2026-11-05T12:00:00Z")
    assert _linhas_crm(caplog) == []


def test_um_repetido_sobe_a_loja_com_o_tipo_da_linha_gravada_e_nao_com_o_do_pedido(sessao):
    linha = _linha(1, "2026-11-05T12:00:00Z", "chamada", client_uuid=UUID_DO_BLOCO)
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes=[linha]))

    assert cliente.post(CONTACTOS_URL, json=_corpo(tipo="visita", client_uuid=UUID_DO_BLOCO)).status_code == 201

    assert _ultimos(cliente.base) == ("2026-11-05T12:00:00Z", None)


def test_um_repetido_de_outra_loja_da_422_em_client_uuid_e_nada_se_grava(sessao):
    linha = _linha(1, loja_id=BAR, client_uuid=UUID_DO_BLOCO)
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_loja(), _loja(2)], interacoes=[linha]))

    r = cliente.post(CONTACTOS_URL, json=_corpo(client_uuid=UUID_DO_BLOCO))

    assert (r.status_code, r.json()) == (422, _validacao({"client_uuid": "Este identificador já foi usado noutra loja."}))
    assert _escritas(cliente.base) == []


def _corrida(linha):
    """A coleção das interações em que outro pedido grava `linha` entre o
    `find_one` e o `insert_one`, que então dá `DuplicateKeyError`."""
    interacoes = ColeccaoFalsa(
        falhar={"insert_one": DuplicateKeyError("E11000 duplicate key error", 11000)}, nome="crm_interacoes",
    )
    interacoes.antes_de("insert_one", lambda docs: docs.append({"_id": "gravada-pelo-outro", **linha}))
    return interacoes


def test_na_corrida_o_segundo_pedido_responde_como_um_repetido(sessao, caplog):
    linha = _linha(1, "2026-11-05T12:00:00Z", "visita", client_uuid=UUID_DO_BLOCO)
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes_coleccao=_corrida(linha)))

    with caplog.at_level(logging.DEBUG, logger="crm"):
        r = cliente.post(CONTACTOS_URL, json=_corpo(client_uuid=UUID_DO_BLOCO))

    assert r.status_code == 201
    assert [c["id"] for c in r.json()["contactos"]] == [_id(101)]
    assert len(cliente.base.crm_interacoes.docs) == 1
    assert _ultimos(cliente.base) == ("2026-11-05T12:00:00Z", "2026-11-05T12:00:00Z")
    assert _linhas_crm(caplog) == []


def test_na_corrida_com_outra_loja_da_422_em_client_uuid(sessao):
    linha = _linha(1, loja_id=BAR, client_uuid=UUID_DO_BLOCO)
    base = _base(lojas=[_loja(), _loja(2)], interacoes_coleccao=_corrida(linha))
    cliente = sessao(RUI_UTILIZADOR, base)

    r = cliente.post(CONTACTOS_URL, json=_corpo(client_uuid=UUID_DO_BLOCO))

    assert (r.status_code, r.json()) == (422, _validacao({"client_uuid": "Este identificador já foi usado noutra loja."}))
    assert cliente.base.crm_lojas.chamadas("update_one") == []


def test_uma_chave_repetida_sem_linha_com_o_client_uuid_e_um_erro_a_serio(sessao):
    interacoes = ColeccaoFalsa(
        falhar={"insert_one": DuplicateKeyError("E11000 duplicate key error", 11000)}, nome="crm_interacoes",
    )
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes_coleccao=interacoes), levantar=False)

    assert cliente.post(CONTACTOS_URL, json=_corpo(client_uuid=UUID_DO_BLOCO)).status_code == 500
    assert cliente.post(CONTACTOS_URL, json=_corpo()).status_code == 500


# --- PATCH: a ordem das recusas -------------------------------------------------------------------------


def test_um_corpo_invalido_da_422_antes_de_ler_a_base(sessao):
    cliente = sessao(TIA_UTILIZADORA, _base(interacoes=[_linha()]))
    r = cliente.patch(_um_contacto_url(NAO_EXISTE, NAO_EXISTE), json={"resumo": ""})
    assert (r.status_code, r.json()) == (422, _validacao({"resumo": MENSAGEM_RESUMO}))
    assert _leituras_e_escritas(cliente.base) == []


@pytest.mark.parametrize("corpo, campos", [
    ({"tipo": None}, {"tipo": MENSAGEM_TIPO}),
    ({"tipo": ""}, {"tipo": MENSAGEM_TIPO}),
    ({"data": None}, {"data": MENSAGEM_DATA}),
    ({"data": ""}, {"data": MENSAGEM_DATA}),
    ({"data": "2026-11-08"}, {"data": MENSAGEM_DATA_FORA}),
    ({"resumo": None}, {"resumo": MENSAGEM_RESUMO}),
    ({"resumo": "  "}, {"resumo": MENSAGEM_RESUMO}),
    ({"tipo": None, "resumo": None}, {"tipo": MENSAGEM_TIPO, "resumo": MENSAGEM_RESUMO}),
], ids=["tipo null", "tipo vazio", "data null", "data vazia", "data futura", "resumo null", "resumo vazio", "dois"])
def test_uma_chave_presente_com_null_ou_vazio_e_erro_do_campo(sessao, corpo, campos):
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes=[_linha()]))
    r = cliente.patch(_um_contacto_url(_id(101)), json=corpo)
    assert (r.status_code, r.json()) == (422, _validacao(campos))
    assert _escritas(cliente.base) == []


@pytest.mark.parametrize("metodo, corpo", [("PATCH", {"resumo": "Outro."}), ("DELETE", None)], ids=["alterar", "apagar"])
def test_a_loja_vem_antes_do_contacto_e_da_permissao(sessao, metodo, corpo):
    cliente = sessao(TIA_UTILIZADORA, _base(interacoes=[_linha()]))
    r = _pedir(cliente, metodo, _um_contacto_url(_id(101), NAO_EXISTE), corpo)
    assert (r.status_code, r.json()) == (404, LOJA_NAO_ENCONTRADA)
    assert cliente.base.crm_interacoes.registo == []


@pytest.mark.parametrize("metodo, corpo", [("PATCH", {"resumo": "Outro."}), ("DELETE", None)], ids=["alterar", "apagar"])
@pytest.mark.parametrize("linha", [
    _linha(9, loja_id=BAR),
    _linha(1, tipo="mudanca_fase"),
    _linha(1, tipo="amostra"),
    _linha(1, tipo="entrega"),
    _linha(1, tipo="nota"),
], ids=["de outra loja", "mudança de fase", "amostra", "entrega", "nota"])
def test_um_contacto_que_nao_e_desta_lista_da_404(sessao, metodo, corpo, linha):
    cliente = sessao(ANA_ADMIN_DO_CRM, _base(lojas=[_loja(), _loja(2)], interacoes=[linha]))
    r = _pedir(cliente, metodo, _um_contacto_url(linha["id"]), corpo)
    assert (r.status_code, r.json()) == (404, CONTACTO_NAO_ENCONTRADO)
    assert _escritas(cliente.base) == []


@pytest.mark.parametrize("metodo, corpo", [("PATCH", {"resumo": "Outro."}), ("DELETE", None)], ids=["alterar", "apagar"])
def test_um_contacto_que_nao_existe_da_404_antes_da_permissao(sessao, metodo, corpo):
    cliente = sessao(TIA_UTILIZADORA, _base(interacoes=[_linha()]))
    r = _pedir(cliente, metodo, _um_contacto_url(NAO_EXISTE), corpo)
    assert (r.status_code, r.json()) == (404, CONTACTO_NAO_ENCONTRADO)


@pytest.mark.parametrize("metodo, corpo", [("PATCH", {"resumo": "Outro."}), ("DELETE", None)], ids=["alterar", "apagar"])
@pytest.mark.parametrize("utilizador", [TIA_UTILIZADORA, GIL_ADMIN_DO_PORTAL], ids=["outro utilizador", "admin do portal"])
def test_quem_nao_escreveu_nem_e_admin_do_crm_da_403_e_nada_muda(sessao, metodo, corpo, utilizador):
    cliente = sessao(utilizador, _base(interacoes=[_linha()]))
    r = _pedir(cliente, metodo, _um_contacto_url(_id(101)), corpo)
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)
    assert _escritas(cliente.base) == []


@pytest.mark.parametrize("metodo, corpo", [("PATCH", {"resumo": "Outro."}), ("DELETE", None)], ids=["alterar", "apagar"])
@pytest.mark.parametrize("utilizador", [RUI_UTILIZADOR, ANA_ADMIN_DO_CRM, ADMIN_MASTER], ids=["autor", "admin", "master"])
def test_uma_linha_de_uma_paragem_da_403_a_todos(sessao, metodo, corpo, utilizador):
    cliente = sessao(utilizador, _base(interacoes=[_linha(paragem_id=_id(300))]))
    r = _pedir(cliente, metodo, _um_contacto_url(_id(101)), corpo)
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)
    assert _escritas(cliente.base) == []


def test_sem_permissao_um_patch_sem_mudancas_tambem_da_403(sessao):
    """A permissão vem antes da escrita, e também antes de ver que não há nada."""
    cliente = sessao(TIA_UTILIZADORA, _base(interacoes=[_linha()]))
    r = cliente.patch(_um_contacto_url(_id(101)), json={})
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)


# --- PATCH: sem nada a mudar ----------------------------------------------------------------------------


@pytest.mark.parametrize("corpo", [
    {},
    {"tipo": "visita"},
    {"data": "2026-11-05"},
    {"resumo": "Resumo 1."},
    {"resumo": "  Resumo 1.  "},
    {"tipo": "visita", "data": "2026-11-05", "resumo": "Resumo 1."},
], ids=["vazio", "o mesmo tipo", "o mesmo dia", "o mesmo resumo", "o mesmo resumo com espaços", "tudo igual"])
def test_sem_nada_a_mudar_responde_200_com_a_lista_sem_escrever(sessao, corpo):
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes=[_linha(1, "2026-11-05T12:00:00Z")]))

    r = cliente.patch(_um_contacto_url(_id(101)), json=corpo)

    assert r.status_code == 200, r.text
    assert r.json()["contactos"][0]["corrigido"] is False
    assert _escritas(cliente.base) == []
    assert cliente.base.crm_interacoes.docs[0]["editado_em"] is None


# --- PATCH: o que muda ----------------------------------------------------------------------------------


def test_corrigir_o_resumo_grava_o_aparado_e_marca_corrigido(sessao, caplog):
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes=[_linha(1, "2026-11-05T08:15:00Z")]))

    with caplog.at_level(logging.DEBUG, logger="crm"):
        r = cliente.patch(_um_contacto_url(_id(101)), json={"resumo": "  Outro texto. "})

    assert r.status_code == 200, r.text
    [gravada] = cliente.base.crm_interacoes.sem_id()
    assert gravada == {**_linha(1, "2026-11-05T08:15:00Z"), "notas": "Outro texto.", "editado_em": AGORA_INSTANTE}
    assert instantes_fora_do_formato(gravada) == []
    assert r.json()["hoje"] == HOJE
    assert r.json()["contactos"] == [{
        "id": _id(101), "numero": 1, "tipo": "visita", "data": "2026-11-05", "resumo": "Outro texto.",
        "autor": "Rui Costa", "pode_alterar": True, "corrigido": True,
    }]
    assert _linhas_crm(caplog) == []


def test_o_set_leva_so_o_que_muda(sessao):
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes=[_linha(1, "2026-11-05T12:00:00Z")]))

    cliente.patch(_um_contacto_url(_id(101)), json={"tipo": "chamada", "data": "2026-11-05", "resumo": "Resumo 1."})

    [atualizacao] = cliente.base.crm_interacoes.chamadas("update_one")
    assert atualizacao[1:3] == (
        {"id": _id(101), "loja_id": CAFE},
        {"$set": {"editado_em": AGORA_INSTANTE, "tipo": "chamada"}},
    )


def test_o_administrador_do_crm_corrige_o_de_outro_e_o_autor_nao_muda(sessao):
    cliente = sessao(ANA_ADMIN_DO_CRM, _base(interacoes=[_linha()]))

    r = cliente.patch(_um_contacto_url(_id(101)), json={"resumo": "Corrigido pela Ana."})

    assert r.status_code == 200, r.text
    assert r.json()["contactos"][0]["autor"] == "Rui Costa"
    assert cliente.base.crm_interacoes.docs[0]["utilizador_id"] == "u-rui"


def test_mudar_para_outro_dia_passado_fica_as_12_de_lisboa(sessao):
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes=[_linha(1, "2026-11-05T08:15:00Z")]))

    r = cliente.patch(_um_contacto_url(_id(101)), json={"data": "2026-07-15"})

    assert r.status_code == 200, r.text
    assert cliente.base.crm_interacoes.docs[0]["ocorrida_em"] == "2026-07-15T11:00:00Z"
    assert r.json()["contactos"][0]["data"] == "2026-07-15"


def test_mudar_para_hoje_fica_o_instante_do_pedido(sessao):
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes=[_linha(1, "2026-11-05T08:15:00Z")]))

    cliente.patch(_um_contacto_url(_id(101)), json={"data": HOJE})

    assert cliente.base.crm_interacoes.docs[0]["ocorrida_em"] == AGORA_INSTANTE


def test_um_patch_que_nao_muda_a_data_deixa_o_ocorrida_em_como_estava(sessao):
    """A comparação é pelo dia de Lisboa: às 23:30Z do verão o dia é o 16."""
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes=[_linha(1, "2026-07-15T23:30:00Z")]))

    r = cliente.patch(_um_contacto_url(_id(101)), json={"data": "2026-07-16", "resumo": "Outro."})

    assert r.status_code == 200, r.text
    gravada = cliente.base.crm_interacoes.docs[0]
    assert (gravada["ocorrida_em"], gravada["notas"]) == ("2026-07-15T23:30:00Z", "Outro.")


def test_mudar_a_data_renumera_os_outros(sessao):
    interacoes = [_linha(1, "2026-11-01T12:00:00Z"), _linha(2, "2026-11-03T12:00:00Z")]
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes=interacoes))

    r = cliente.patch(_um_contacto_url(_id(102)), json={"data": "2026-10-20"})

    assert [(c["id"], c["numero"]) for c in r.json()["contactos"]] == [(_id(101), 2), (_id(102), 1)]


def test_corrigir_nao_muda_a_fase_nem_o_atualizado_em_da_loja(sessao):
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes=[_linha()]))

    cliente.patch(_um_contacto_url(_id(101)), json={"data": "2026-11-02"})

    guardada = _guardada(cliente.base)
    assert (guardada["fase"], guardada["fase_desde"], guardada["atualizado_em"]) == ("potencial", CRIADA_EM, VERSAO)


def test_um_contacto_apagado_entre_a_leitura_e_a_escrita_da_404(sessao):
    interacoes = ColeccaoFalsa([_linha()], nome="crm_interacoes")
    interacoes.antes_de("update_one", lambda docs: docs.clear())
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes_coleccao=interacoes))

    r = cliente.patch(_um_contacto_url(_id(101)), json={"resumo": "Outro."})

    assert (r.status_code, r.json()) == (404, CONTACTO_NAO_ENCONTRADO)
    assert cliente.base.crm_lojas.chamadas("update_one") == []


# --- PATCH e DELETE: o recálculo do último contacto -----------------------------------------------------


def _loja_com_ultimos(interacao, visita):
    return _loja(ultima_interacao_em=interacao, ultima_visita_ou_entrega_em=visita)


def test_recuar_a_data_faz_recuar_o_ultimo_contacto(sessao, caplog):
    interacoes = [_linha(1, "2026-11-01T12:00:00Z"), _linha(2, "2026-11-05T12:00:00Z")]
    loja = _loja_com_ultimos("2026-11-05T12:00:00Z", "2026-11-05T12:00:00Z")
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[loja], interacoes=interacoes))

    with caplog.at_level(logging.DEBUG, logger="crm"):
        assert cliente.patch(_um_contacto_url(_id(102)), json={"data": "2026-10-20"}).status_code == 200

    assert _ultimos(cliente.base) == ("2026-11-01T12:00:00Z", "2026-11-01T12:00:00Z")
    assert _linhas_crm(caplog) == []


def test_passar_de_visita_a_chamada_faz_recuar_so_a_ultima_visita(sessao):
    interacoes = [_linha(1, "2026-11-01T12:00:00Z"), _linha(2, "2026-11-05T12:00:00Z")]
    loja = _loja_com_ultimos("2026-11-05T12:00:00Z", "2026-11-05T12:00:00Z")
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[loja], interacoes=interacoes))

    assert cliente.patch(_um_contacto_url(_id(102)), json={"tipo": "chamada"}).status_code == 200

    assert _ultimos(cliente.base) == ("2026-11-05T12:00:00Z", "2026-11-01T12:00:00Z")


def test_apagar_faz_recuar_o_ultimo_contacto(sessao, caplog):
    interacoes = [_linha(1, "2026-11-01T12:00:00Z", "chamada"), _linha(2, "2026-11-05T12:00:00Z")]
    loja = _loja_com_ultimos("2026-11-05T12:00:00Z", "2026-11-05T12:00:00Z")
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[loja], interacoes=interacoes))

    with caplog.at_level(logging.DEBUG, logger="crm"):
        assert cliente.delete(_um_contacto_url(_id(102))).status_code == 200

    assert _ultimos(cliente.base) == ("2026-11-01T12:00:00Z", None)
    assert _linhas_crm(caplog) == []


def test_apagar_o_ultimo_contacto_deixa_os_campos_a_null(sessao):
    loja = _loja_com_ultimos("2026-11-05T12:00:00Z", "2026-11-05T12:00:00Z")
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[loja], interacoes=[_linha()]))

    assert cliente.delete(_um_contacto_url(_id(101))).status_code == 200

    assert _ultimos(cliente.base) == (None, None)


def test_o_recalculo_conta_as_amostras_e_as_entregas_e_a_mensagem_so_no_primeiro_campo(sessao):
    interacoes = [
        _linha(1, "2026-11-06T12:00:00Z", "chamada"),
        _linha(2, "2026-11-01T12:00:00Z", "amostra", resultado="entregue", utilizador_id="u-ana"),
        _linha(3, "2026-11-02T12:00:00Z", "entrega", resultado="entregue", utilizador_id="u-ana"),
        _linha(4, "2026-11-04T12:00:00Z", "mensagem"),
    ]
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes=interacoes))

    assert cliente.delete(_um_contacto_url(_id(101))).status_code == 200

    assert _ultimos(cliente.base) == ("2026-11-04T12:00:00Z", "2026-11-02T12:00:00Z")


def test_o_recalculo_nao_conta_notas_nem_mudancas_de_fase_nem_outras_lojas(sessao):
    interacoes = [
        _linha(1, "2026-11-01T12:00:00Z", "chamada"),
        _linha(2, "2026-11-05T12:00:00Z", "mudanca_fase", resultado="potencial→contactada"),
        _linha(3, "2026-11-06T12:00:00Z", "nota"),
        _linha(4, "2026-11-07T09:00:00Z", "visita", loja_id=BAR),
    ]
    cliente = sessao(RUI_UTILIZADOR, _base(lojas=[_loja(), _loja(2)], interacoes=interacoes))

    assert cliente.patch(_um_contacto_url(_id(101)), json={"resumo": "Outro."}).status_code == 200

    assert _ultimos(cliente.base) == ("2026-11-01T12:00:00Z", None)


@pytest.mark.parametrize("metodo, corpo", [("PATCH", {"data": "2026-10-20"}), ("DELETE", None)], ids=["alterar", "apagar"])
@pytest.mark.parametrize("falha", FALHAS)
def test_uma_falha_no_recalculo_nao_desfaz_o_contacto(sessao, caplog, metodo, corpo, falha):
    lojas = ColeccaoFalsa([_loja()], falhar={"update_one": falha}, nome="crm_lojas")
    cliente = sessao(RUI_UTILIZADOR, _base(lojas_coleccao=lojas, interacoes=[_linha()]))

    with caplog.at_level(logging.DEBUG, logger="crm"):
        r = _pedir(cliente, metodo, _um_contacto_url(_id(101)), corpo)

    assert r.status_code == 200
    [registo] = _linhas_crm(caplog)
    assert registo.getMessage() == (
        f"[crm] loja {CAFE}: o contacto mudou, mas o último contacto da loja não se atualizou "
        f"({type(falha).__name__})"
    )
    for dado in ("Amélia", "segredo", "u-rui", "Resumo 1"):
        assert dado not in caplog.text, dado


def test_uma_falha_a_ler_as_interacoes_no_recalculo_tambem_nao_desfaz_o_contacto(sessao, caplog):
    interacoes = ColeccaoFalsa([_linha()], nome="crm_interacoes")
    falhou = []

    def _falhar_uma_vez_depois_de_apagar(_docs):
        if interacoes.chamadas("delete_one") and not falhou:
            falhou.append(True)
            raise RuntimeError("x")

    interacoes.antes_de("find", _falhar_uma_vez_depois_de_apagar)
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes_coleccao=interacoes))

    with caplog.at_level(logging.DEBUG, logger="crm"):
        r = cliente.delete(_um_contacto_url(_id(101)))

    assert (r.status_code, r.json()) == (200, {"hoje": HOJE, "contactos": []})
    assert len(_linhas_crm(caplog)) == 1
    assert cliente.base.crm_lojas.chamadas("update_one") == []


# --- DELETE --------------------------------------------------------------------------------------------


def test_apagar_responde_com_a_lista_renumerada(sessao):
    interacoes = [_linha(1, "2026-11-01T12:00:00Z"), _linha(2, "2026-11-03T12:00:00Z"), _linha(3, "2026-11-05T12:00:00Z")]
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes=interacoes))

    r = cliente.delete(_um_contacto_url(_id(102)))

    assert r.status_code == 200, r.text
    assert r.json()["hoje"] == HOJE
    assert [(c["id"], c["numero"]) for c in r.json()["contactos"]] == [(_id(103), 2), (_id(101), 1)]
    assert [linha["id"] for linha in cliente.base.crm_interacoes.docs] == [_id(101), _id(103)]


def test_o_administrador_do_crm_apaga_o_de_outro(sessao):
    cliente = sessao(ANA_ADMIN_DO_CRM, _base(interacoes=[_linha()]))
    assert cliente.delete(_um_contacto_url(_id(101))).status_code == 200
    assert cliente.base.crm_interacoes.docs == []


def test_apagar_ignora_o_corpo_mesmo_partido(sessao):
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes=[_linha()]))
    r = cliente.request("DELETE", _um_contacto_url(_id(101)), content=b"[", headers=JSON)
    assert r.status_code == 200


def test_apagar_duas_vezes_da_404(sessao):
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes=[_linha()]))
    assert cliente.delete(_um_contacto_url(_id(101))).status_code == 200
    r = cliente.delete(_um_contacto_url(_id(101)))
    assert (r.status_code, r.json()) == (404, CONTACTO_NAO_ENCONTRADO)


def test_apagado_por_outra_pessoa_entre_a_leitura_e_a_escrita_da_404(sessao):
    interacoes = ColeccaoFalsa([_linha()], nome="crm_interacoes")
    interacoes.antes_de("delete_one", lambda docs: docs.clear())
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes_coleccao=interacoes))

    r = cliente.delete(_um_contacto_url(_id(101)))

    assert (r.status_code, r.json()) == (404, CONTACTO_NAO_ENCONTRADO)
    assert cliente.base.crm_lojas.chamadas("update_one") == []


def test_apagar_nao_muda_a_fase_nem_o_atualizado_em_da_loja(sessao):
    cliente = sessao(RUI_UTILIZADOR, _base(interacoes=[_linha()]))

    cliente.delete(_um_contacto_url(_id(101)))

    guardada = _guardada(cliente.base)
    assert (guardada["fase"], guardada["fase_desde"], guardada["atualizado_em"]) == ("potencial", CRIADA_EM, VERSAO)


# --- A loja com contactos -------------------------------------------------------------------------------


def test_uma_loja_com_contactos_nao_se_apaga_e_sem_eles_ja_se_apaga(sessao):
    cliente = sessao(RUI_UTILIZADOR)
    contacto = cliente.post(CONTACTOS_URL, json=_corpo()).json()["contactos"][0]

    r = cliente.delete(LOJA_URL)

    assert r.status_code == 409
    assert r.json()["detail"]["codigo"] == "loja_com_historico"
    assert len(cliente.base.crm_lojas.docs) == 1

    assert cliente.delete(_um_contacto_url(contacto["id"])).status_code == 200
    assert cliente.delete(LOJA_URL).status_code == 200
    assert cliente.base.crm_lojas.docs == []


def test_a_ficha_aberta_antes_de_um_contacto_guarda_sem_conflito(sessao):
    """O `atualizado_em` da loja não muda, e a ficha lê os dois campos novos."""
    cliente = sessao(RUI_UTILIZADOR)
    ficha = cliente.get(LOJA_URL).json()

    assert cliente.post(CONTACTOS_URL, json=_corpo()).status_code == 201

    r = cliente.patch(LOJA_URL, json={"telefone": "912 345 678", "atualizado_em": ficha["atualizado_em"]})
    assert r.status_code == 200, r.text
    assert r.json()["ultima_interacao_em"] == AGORA_INSTANTE


# --- De ponta a ponta: a sessão verdadeira do portal ---------------------------------------------------

SEGREDO = "segredo-de-teste-crm-contactos"
AGORA_TOKEN = int(time.time())


def _cabecalho(user_id):
    dados = {
        "user_id": user_id, "email": "qualquer@example.com", "role": "colaborador",
        "iat": AGORA_TOKEN, "exp": AGORA_TOKEN + 3600,
    }
    return {"Authorization": f"Bearer {jwt.encode(dados, SEGREDO, algorithm='HS256')}"}


@pytest.fixture
def portal(monkeypatch):
    """O router do CRM com a sessão verdadeira (faturacao.auth) e a mesma base
    falsa para o portal e para o CRM."""
    monkeypatch.setenv("JWT_SECRET", SEGREDO)
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    monkeypatch.setattr(relogio, "agora", lambda: AGORA)
    base = _base()
    monkeypatch.setattr(faturacao.auth, "obter_db", lambda: base)
    monkeypatch.setattr(crm.db, "obter_db", lambda: base)
    app = FastAPI()
    app.include_router(crm.router)
    cliente = TestClient(app)
    cliente.base = base
    return cliente


@pytest.mark.parametrize("metodo, url, corpo", TODAS, ids=IDS_TODAS)
def test_sem_sessao_da_o_403_herdado_e_nada_se_le(portal, metodo, url, corpo):
    r = _pedir(portal, metodo, url, corpo)
    assert (r.status_code, r.json()) == (403, {"detail": "Not authenticated"})
    assert _leituras_e_escritas(portal.base) == []


def test_sem_cabecalho_e_com_json_partido_da_o_403_herdado_e_nunca_400(portal):
    r = portal.post(CONTACTOS_URL, content=b"[", headers=JSON)
    assert (r.status_code, r.json()) == (403, {"detail": "Not authenticated"})


def test_de_ponta_a_ponta_guardar_corrigir_ver_noutra_conta_e_apagar(portal):
    rui = _cabecalho("u-rui")
    ana = _cabecalho("u-ana")
    tia = _cabecalho("u-tia")

    r = portal.post(CONTACTOS_URL, json=_corpo(client_uuid=UUID_DO_BLOCO), headers=rui)
    assert r.status_code == 201, r.text
    [contacto] = r.json()["contactos"]
    assert (contacto["numero"], contacto["autor"], contacto["pode_alterar"]) == (1, "Rui Costa", True)

    r = portal.post(CONTACTOS_URL, json=_corpo(client_uuid=UUID_DO_BLOCO), headers=rui)
    assert r.status_code == 201
    assert len(r.json()["contactos"]) == 1, "O reenvio não criou outra linha."

    url = _um_contacto_url(contacto["id"])
    assert portal.get(CONTACTOS_URL, headers=tia).json()["contactos"][0]["pode_alterar"] is False
    assert (portal.patch(url, json={"resumo": "x"}, headers=tia).status_code) == 403

    r = portal.patch(url, json={"tipo": "chamada", "data": "2026-11-01"}, headers=rui)
    assert r.status_code == 200, r.text
    assert (r.json()["contactos"][0]["data"], r.json()["contactos"][0]["corrigido"]) == ("2026-11-01", True)
    assert _ultimos(portal.base) == ("2026-11-01T12:00:00Z", None)

    r = portal.delete(url, headers=ana)
    assert (r.status_code, r.json()) == (200, {"hoje": HOJE, "contactos": []})
    assert _ultimos(portal.base) == (None, None)
