"""`/api/crm/regioes` — as regiões que filtram as lojas no mapa (plano T2.9;
dossiê §5.8 e §6).

Porta de tests/Integration/Api/RegioesTest.php do CRM autónomo (etiqueta
`referencia-standalone`): todos os casos, com os nomes de lá, e os dados dos
`DataProvider` com os mesmos nomes. Adaptações ao portal:

- `GET` para o escritório (admin e utilizador do CRM); `POST`, `PATCH` e
  `DELETE` só para o admin do CRM (403 `sem_permissao`; quem não é membro,
  403 `sem_acesso_crm`). Sem sessão, os 403/401 herdados do portal, em vez
  do 401 `nao_autenticado` do autónomo.
- Ids uuid4 em texto (lá eram inteiros) e o `nome_chave` gravado com a região:
  o índice único em `nome_chave` faz o papel da collation unicode_ci.
- Sem transações (o autónomo bloqueava a linha da região): o nome repetido
  verifica-se antes de gravar — também vale sem o índice único — e o
  `DuplicateKeyError` só é 409 quando há OUTRA região com o nome; no PATCH,
  com `{"nome_chave": k, "id": {"$ne": regiao_id}}`, para corrigir as
  maiúsculas do próprio nome não ser repetição (correções do plano, linha
  "T2.9"). Uma região apagada entre a leitura e a escrita dá 404.
- `GET /regioes` ordena por `(ordem, chave_comparacao(nome), id)` (correções,
  linha "T2.30 e T2.9").

Rotas por `TestClient` com `dependency_overrides[utilizador_atual]` e
`monkeypatch.setattr(crm.db, "obter_db", …)` (plano §10); as corridas a sério
com duas corrotinas no duplo (`correr`, nunca `asyncio.run`); no fim, de ponta
a ponta com a sessão verdadeira do portal (JWT + conta lida da base).
"""
import asyncio
import time
import uuid

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

import crm
import crm.db
import faturacao.auth
from crm import regioes as rotas_regioes
from crm.auth import ESCRITORIO, SO_ADMIN, membro_crm_atual
from crm.dominio import validador_loja
from crm.pedidos import corpo_json
from faturacao.auth import utilizador_atual

from .duplos import BaseFalsa, ColeccaoFalsa, correr

REGIOES_URL = "/api/crm/regioes"
UMA_REGIAO_URL = "/api/crm/regioes/{regiao_id}"
ADMIN_LOCAL = "admin.local@example.com"
JSON = {"Content-Type": "application/json"}

INDIQUE_O_NOME = "Indique o nome."
ORDEM_INVALIDA = "A ordem tem de ser um número inteiro."
NAO_ENCONTRADA = {"detail": {"codigo": "nao_encontrado", "mensagem": "Região não encontrada."}}
REGIAO_REPETIDA = {"detail": {"codigo": "regiao_repetida", "mensagem": "Já existe uma região com este nome."}}
REGIAO_COM_LOJAS = {"detail": {
    "codigo": "regiao_com_lojas", "mensagem": "Esta região tem lojas — mude-lhe o nome em vez de a apagar.",
}}
JSON_INVALIDO = {"detail": {"codigo": "json_invalido", "mensagem": "O pedido não é JSON válido."}}
SEM_PERMISSAO = {"detail": {"codigo": "sem_permissao", "mensagem": "Sem permissão para esta ação."}}
SEM_ACESSO = {"detail": {"codigo": "sem_acesso_crm", "mensagem": "Sem acesso ao CRM."}}

PROJECAO_REGIAO = {"_id": 0, "id": 1, "nome": 1, "ordem": 1}
PROJECAO_ID = {"_id": 0, "id": 1}


def _id(n):
    """Um uuid4 em texto, fixo para os testes serem legíveis."""
    return f"00000000-0000-4000-8000-{n:012d}"


LISBOA, PORTO, ALGARVE, EVORA, SETUBAL = _id(1), _id(2), _id(3), _id(4), _id(5)
NAO_EXISTE = _id(999)


def _regiao(regiao_id, nome, ordem, chave):
    """Uma região como fica gravada (a chave escrita à mão, de propósito: não
    se calcula com o código que se está a testar)."""
    return {"id": regiao_id, "nome": nome, "nome_chave": chave, "ordem": ordem}


def _url(regiao_id):
    return f"{REGIOES_URL}/{regiao_id}"


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

# As três rotas de escrita, com um corpo válido para cada uma (o `rotasDeAdmin`).
ESCRITAS = [
    ("POST", REGIOES_URL, {"nome": "Porto", "ordem": 2}),
    ("PATCH", _url(LISBOA), {"nome": "Grande Lisboa", "ordem": 5}),
    ("DELETE", _url(LISBOA), None),
]
IDS_ESCRITAS = ["criar", "alterar", "apagar"]
COM_CORPO = ESCRITAS[:2]
IDS_COM_CORPO = IDS_ESCRITAS[:2]


def _base(regioes=(), lojas=(), membros=MEMBROS, users=USERS):
    return BaseFalsa({
        "crm_membros": list(membros),
        "users": list(users),
        "crm_regioes": list(regioes),
        "crm_lojas": list(lojas),
    })


def _escritas(base):
    """As escritas em `crm_regioes` e `crm_lojas`, pela ordem."""
    return [
        c
        for coleccao in (base.crm_regioes, base.crm_lojas)
        for c in coleccao.registo
        if c[0] in ("insert_one", "update_one", "find_one_and_update", "delete_one", "delete_many")
    ]


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
    """Todos os `call` das dependências da rota, recursivamente (molde de
    tests/faturacao/test_protecao_rotas.py)."""
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
    `dependency_overrides` e a base do CRM trocada pelo único ponto.
    `sessao(utilizador, base)` devolve o cliente (com `cliente.base`); para
    outra pessoa na mesma base, `sessao(outra, cliente.base)`."""
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)

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


@pytest.fixture
def direto(monkeypatch):
    """Para chamar as funções das rotas diretamente (as corridas): a base
    trocada e os membros como a guarda os devolve."""
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)

    def _montar(base):
        monkeypatch.setattr(crm.db, "obter_db", lambda: base)
        admin = {**ADMIN_MASTER, "crm_perfil": "admin", "crm_admin_master": True}
        ana = {**ANA_ADMIN_DO_CRM, "crm_perfil": "admin", "crm_admin_master": False}
        return admin, ana

    return _montar


# --- As rotas: onde estão, quem as guarda e por que ordem -------------------------------


ROTAS = [("GET", REGIOES_URL), ("POST", REGIOES_URL), ("PATCH", UMA_REGIAO_URL), ("DELETE", UMA_REGIAO_URL)]
IDS_ROTAS = ["listar", "criar", "alterar", "apagar"]


@pytest.mark.parametrize("metodo, caminho", ROTAS, ids=IDS_ROTAS)
def test_as_rotas_existem_e_vivem_em_crm_regioes(metodo, caminho):
    rota = _rota(caminho, metodo)
    assert rota.methods == {metodo}
    assert rota.endpoint.__module__ == "crm.regioes"


def test_criar_responde_201():
    assert _rota(REGIOES_URL, "POST").status_code == 201


@pytest.mark.parametrize(
    "metodo, caminho, guarda",
    [
        ("GET", REGIOES_URL, ESCRITORIO),
        ("POST", REGIOES_URL, SO_ADMIN),
        ("PATCH", UMA_REGIAO_URL, SO_ADMIN),
        ("DELETE", UMA_REGIAO_URL, SO_ADMIN),
    ],
    ids=IDS_ROTAS,
)
def test_listar_e_do_escritorio_e_as_escritas_so_do_admin_do_crm(metodo, caminho, guarda):
    """Exatamente uma guarda de perfil, sobre `membro_crm_atual`."""
    dependencias = _dependencias(_rota(caminho, metodo))
    assert membro_crm_atual in dependencias
    assert [d for d in dependencias if hasattr(d, "perfis_crm")] == [guarda]


@pytest.mark.parametrize("metodo, caminho", [("POST", REGIOES_URL), ("PATCH", UMA_REGIAO_URL)], ids=IDS_COM_CORPO)
def test_a_guarda_de_perfil_vem_antes_do_corpo(metodo, caminho):
    """Correções do plano, linha "T1.3 / T2.15": o FastAPI resolve as
    dependências pela ordem em que estão declaradas."""
    diretas = [d.call for d in _rota(caminho, metodo).dependant.dependencies]
    assert diretas == [SO_ADMIN, corpo_json]


@pytest.mark.parametrize("metodo, caminho", [("GET", REGIOES_URL), ("DELETE", UMA_REGIAO_URL)], ids=["listar", "apagar"])
def test_listar_e_apagar_nao_leem_o_corpo(metodo, caminho):
    assert corpo_json not in _dependencias(_rota(caminho, metodo))


# --- GET /regioes ---------------------------------------------------------------------------


def test_quem_tem_sessao_lista_as_regioes_por_ordem_e_depois_por_nome(sessao):
    """`quemTemSessaoListaAsRegioesPorOrdemEDepoisPorNome`."""
    base = _base([
        _regiao(PORTO, "Porto", 2, "porto"),
        _regiao(LISBOA, "Lisboa", 1, "lisboa"),
        _regiao(ALGARVE, "Algarve", 2, "algarve"),
        _regiao(EVORA, "Évora", 0, "evora"),
    ])
    r = sessao(ZE_UTILIZADOR, base).get(REGIOES_URL)
    assert r.status_code == 200
    assert r.json() == [
        {"id": EVORA, "nome": "Évora", "ordem": 0},
        {"id": LISBOA, "nome": "Lisboa", "ordem": 1},
        {"id": ALGARVE, "nome": "Algarve", "ordem": 2},
        {"id": PORTO, "nome": "Porto", "ordem": 2},
    ]
    # Cada região sai como {id, nome, ordem}, por esta ordem, e nunca com a nome_chave.
    assert [list(regiao) for regiao in r.json()] == [["id", "nome", "ordem"]] * 4


def test_sem_regioes_a_lista_vem_vazia(sessao):
    """`semRegioesAListaVemVazia`."""
    r = sessao(ADMIN_MASTER).get(REGIOES_URL)
    assert (r.status_code, r.json()) == (200, [])


@pytest.mark.parametrize(
    "utilizador", [ADMIN_MASTER, ANA_ADMIN_DO_CRM, ZE_UTILIZADOR], ids=["admin master", "admin", "utilizador"]
)
def test_o_escritorio_lista(sessao, utilizador):
    base = _base([_regiao(LISBOA, "Lisboa", 1, "lisboa")])
    r = sessao(utilizador, base).get(REGIOES_URL)
    assert (r.status_code, r.json()) == (200, [{"id": LISBOA, "nome": "Lisboa", "ordem": 1}])


def test_o_motorista_nao_lista_as_regioes_na_f2(sessao):
    """As permissões do terreno chegam na F4 (plano §1, "Perfis por rota")."""
    cliente = sessao(ALVARO_MOTORISTA, _base([_regiao(LISBOA, "Lisboa", 1, "lisboa")]))
    r = cliente.get(REGIOES_URL)
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)
    assert cliente.base.crm_regioes.registo == []


def test_quem_nao_e_membro_nao_lista(sessao):
    r = sessao(BEA_NAO_MEMBRO, _base([_regiao(LISBOA, "Lisboa", 1, "lisboa")])).get(REGIOES_URL)
    assert (r.status_code, r.json()) == (403, SEM_ACESSO)


def test_listar_pede_so_o_id_o_nome_e_a_ordem(sessao):
    cliente = sessao(ZE_UTILIZADOR, _base([_regiao(LISBOA, "Lisboa", 1, "lisboa")]))
    assert cliente.get(REGIOES_URL).status_code == 200
    assert cliente.base.crm_regioes.registo == [("find", {}, PROJECAO_REGIAO)]


def test_listar_ordena_o_nome_sem_maiusculas_nem_acentos_e_nao_pelos_caracteres(sessao):
    """O caso do `ordenarRegioes` (definicoes-regioes.test.js), que o ecrã
    repete: pelos caracteres seria Faro < Porto < aveiro < évora."""
    base = _base([
        _regiao(_id(4), "évora", 1, "evora"),
        _regiao(_id(2), "Porto", 0, "porto"),
        _regiao(_id(3), "Faro", 1, "faro"),
        _regiao(_id(1), "aveiro", 0, "aveiro"),
    ])
    r = sessao(ADMIN_MASTER, base).get(REGIOES_URL)
    assert [regiao["id"] for regiao in r.json()] == [_id(1), _id(2), _id(4), _id(3)]


def test_listar_ordena_as_ordens_como_numeros_e_as_negativas_primeiro(sessao):
    base = _base([
        _regiao(_id(1), "A", 10, "a"),
        _regiao(_id(2), "B", 2, "b"),
        _regiao(_id(3), "C", -3, "c"),
        _regiao(_id(4), "D", 2147483647, "d"),
        _regiao(_id(5), "E", -2147483648, "e"),
        _regiao(_id(6), "F", 0, "f"),
    ])
    r = sessao(ADMIN_MASTER, base).get(REGIOES_URL)
    assert [regiao["nome"] for regiao in r.json()] == ["E", "C", "F", "B", "A", "D"]


def test_listar_desempata_pelo_id_quando_a_ordem_e_o_nome_sao_iguais(sessao):
    """Só sem o índice único (o CRM arranca sem índices se o Mongo falhar) há
    dois nomes com a mesma chave; o `id` desempata, pelos caracteres."""
    regioes = ColeccaoFalsa(
        [
            _regiao("f0000000-0000-4000-8000-000000000000", "Lisboa", 1, "lisboa"),
            _regiao("0a000000-0000-4000-8000-000000000000", "LISBOA", 1, "lisboa"),
            _regiao("50000000-0000-4000-8000-000000000000", "lisboa", 1, "lisboa"),
        ],
        unicos=("id",),
    )
    base = BaseFalsa({"crm_membros": list(MEMBROS), "crm_regioes": regioes})
    r = sessao(ADMIN_MASTER, base).get(REGIOES_URL)
    assert [regiao["nome"] for regiao in r.json()] == ["LISBOA", "lisboa", "Lisboa"]


def test_listar_quando_a_base_falha_e_um_erro(sessao):
    base = BaseFalsa({
        "crm_membros": list(MEMBROS),
        "crm_regioes": ColeccaoFalsa([], falhar={"find": RuntimeError("base em baixo")}),
    })
    assert sessao(ADMIN_MASTER, base, levantar=False).get(REGIOES_URL).status_code == 500


# --- Quem pode escrever -------------------------------------------------------------------------


@pytest.mark.parametrize("metodo, url, corpo", ESCRITAS, ids=IDS_ESCRITAS)
@pytest.mark.parametrize("utilizador", [ZE_UTILIZADOR, ALVARO_MOTORISTA], ids=["utilizador", "motorista"])
def test_um_utilizador_recebe_403_ao_mexer_nas_regioes(sessao, metodo, url, corpo, utilizador):
    """`umUtilizadorRecebe403AoMexerNasRegioes`: e nada mudou, nem se leu."""
    cliente = sessao(utilizador, _base([_regiao(LISBOA, "Lisboa", 1, "lisboa")]))
    antes = cliente.base.crm_regioes.sem_id()
    r = _pedir(cliente, metodo, url, corpo)
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)
    assert cliente.base.crm_regioes.sem_id() == antes
    assert cliente.base.crm_regioes.registo == []
    assert cliente.base.crm_lojas.registo == []


@pytest.mark.parametrize("metodo, url, corpo", ESCRITAS, ids=IDS_ESCRITAS)
def test_quem_nao_e_membro_recebe_403_sem_acesso_e_nada_muda(sessao, metodo, url, corpo):
    cliente = sessao(BEA_NAO_MEMBRO, _base([_regiao(LISBOA, "Lisboa", 1, "lisboa")]))
    r = _pedir(cliente, metodo, url, corpo)
    assert (r.status_code, r.json()) == (403, SEM_ACESSO)
    assert cliente.base.crm_regioes.registo == []


@pytest.mark.parametrize("metodo, url, _corpo", COM_CORPO, ids=IDS_COM_CORPO)
@pytest.mark.parametrize(
    "utilizador, esperado",
    [(ZE_UTILIZADOR, SEM_PERMISSAO), (BEA_NAO_MEMBRO, SEM_ACESSO)],
    ids=["sem perfil", "não membro"],
)
def test_sem_perfil_e_com_json_partido_da_403_e_nunca_400(sessao, metodo, url, _corpo, utilizador, esperado):
    r = sessao(utilizador).request(metodo, url, content=b"[", headers=JSON)
    assert (r.status_code, r.json()) == (403, esperado)


@pytest.mark.parametrize("utilizador", [ADMIN_MASTER, ANA_ADMIN_DO_CRM], ids=["admin master", "membro admin"])
def test_o_admin_master_e_os_membros_admin_escrevem(sessao, utilizador):
    cliente = sessao(utilizador, _base([_regiao(LISBOA, "Lisboa", 1, "lisboa")]))
    assert cliente.post(REGIOES_URL, json={"nome": "Porto", "ordem": 2}).status_code == 201
    assert cliente.patch(_url(LISBOA), json={"nome": "Grande Lisboa", "ordem": 5}).status_code == 200
    assert cliente.delete(_url(LISBOA)).status_code == 200


# --- POST /regioes ------------------------------------------------------------------------------------


def test_o_admin_cria_uma_regiao(sessao):
    """`oAdminCriaUmaRegiao`: o nome perde os espaços das pontas (também os
    Unicode) e a região grava-se com a `nome_chave`."""
    cliente = sessao(ADMIN_MASTER)
    r = cliente.post(REGIOES_URL, json={"nome": "  Lisboa  ", "ordem": 3})
    assert r.status_code == 201
    novo_id = r.json()["id"]
    assert r.json() == {"id": novo_id, "nome": "Lisboa", "ordem": 3}
    assert list(r.json()) == ["id", "nome", "ordem"]
    assert cliente.base.crm_regioes.sem_id() == [{"id": novo_id, "nome": "Lisboa", "nome_chave": "lisboa", "ordem": 3}]


def test_sem_ordem_a_nova_regiao_fica_com_zero(sessao):
    """`semOrdemANovaRegiaoFicaComZero`."""
    cliente = sessao(ADMIN_MASTER)
    r = cliente.post(REGIOES_URL, json={"nome": "Porto"})
    assert r.status_code == 201
    assert r.json()["ordem"] == 0
    assert cliente.base.crm_regioes.sem_id()[0]["ordem"] == 0


def test_criar_grava_a_chave_sem_maiusculas_nem_acentos(sessao):
    cliente = sessao(ADMIN_MASTER)
    assert cliente.post(REGIOES_URL, json={"nome": " SETÚBAL e Península ", "ordem": 1}).status_code == 201
    assert cliente.base.crm_regioes.sem_id()[0]["nome"] == "SETÚBAL e Península"
    assert cliente.base.crm_regioes.sem_id()[0]["nome_chave"] == "setubal e peninsula"


def test_criar_da_um_id_uuid4_em_texto_que_as_lojas_aceitam(sessao):
    """Correções da T2.5: uma loja só aceita um `regiao_id` que seja o
    `str(uuid.uuid4())`; cada região tem o seu."""
    cliente = sessao(ADMIN_MASTER)
    um = cliente.post(REGIOES_URL, json={"nome": "Lisboa"}).json()["id"]
    outro = cliente.post(REGIOES_URL, json={"nome": "Porto"}).json()["id"]
    for novo_id in (um, outro):
        assert isinstance(novo_id, str)
        assert uuid.UUID(novo_id).version == 4
        assert str(uuid.UUID(novo_id)) == novo_id
        _dados, erros = validador_loja.criacao({"regiao_id": novo_id})
        assert "regiao_id" not in erros
    assert um != outro


def test_criar_ignora_as_outras_chaves_e_calcula_a_chave(sessao):
    """`id`, `nome_chave`, `_id`… do corpo ignoram-se: a chave vem do nome."""
    cliente = sessao(ADMIN_MASTER, _base([_regiao(LISBOA, "Lisboa", 1, "lisboa")]))
    r = cliente.post(REGIOES_URL, json={
        "nome": "Porto", "ordem": 2, "id": LISBOA, "nome_chave": "lisboa", "_id": "x", "Nome": "Faro",
    })
    assert r.status_code == 201
    novo_id = r.json()["id"]
    assert novo_id != LISBOA
    assert r.json() == {"id": novo_id, "nome": "Porto", "ordem": 2}
    assert cliente.base.crm_regioes.sem_id() == [
        _regiao(LISBOA, "Lisboa", 1, "lisboa"),
        {"id": novo_id, "nome": "Porto", "nome_chave": "porto", "ordem": 2},
    ]


def test_uma_chave_forjada_no_corpo_nao_escapa_ao_repetido(sessao):
    cliente = sessao(ADMIN_MASTER, _base([_regiao(LISBOA, "Lisboa", 1, "lisboa")]))
    r = cliente.post(REGIOES_URL, json={"nome": "LISBOA", "nome_chave": "outra-chave"})
    assert (r.status_code, r.json()) == (409, REGIAO_REPETIDA)
    assert len(cliente.base.crm_regioes.docs) == 1


NOVAS_INVALIDAS = [
    ({}, {"nome": INDIQUE_O_NOME}),
    ({"nome": "", "ordem": 1}, {"nome": INDIQUE_O_NOME}),
    ({"nome": "   "}, {"nome": INDIQUE_O_NOME}),
    ({"nome": " 　"}, {"nome": INDIQUE_O_NOME}),
    ({"nome": 42}, {"nome": INDIQUE_O_NOME}),
    ({"nome": "a" * 101}, {"nome": "O nome tem no máximo 100 caracteres."}),
    ({"nome": "Porto", "ordem": "2"}, {"ordem": ORDEM_INVALIDA}),
    ({"nome": "Porto", "ordem": 1.5}, {"ordem": ORDEM_INVALIDA}),
    ({"nome": "Porto", "ordem": None}, {"ordem": ORDEM_INVALIDA}),
    ({"nome": "Porto", "ordem": 2147483648}, {"ordem": ORDEM_INVALIDA}),
    ({"nome": " ", "ordem": False}, {"nome": INDIQUE_O_NOME, "ordem": ORDEM_INVALIDA}),
]
IDS_NOVAS_INVALIDAS = [
    "corpo vazio",
    "nome vazio",
    "nome só com espaços",
    "nome só com espaços Unicode",
    "nome que não é texto",
    "nome com 101 caracteres",
    "ordem como texto",
    "ordem decimal",
    "ordem nula",
    "ordem acima de um INT",
    "os dois",
]


@pytest.mark.parametrize("corpo, campos", NOVAS_INVALIDAS, ids=IDS_NOVAS_INVALIDAS)
def test_criar_com_campos_invalidos_da_422(sessao, corpo, campos):
    """`criarComCamposInvalidosDa422` (`novasInvalidas`): e nem se lê a base."""
    cliente = sessao(ADMIN_MASTER)
    r = cliente.post(REGIOES_URL, json=corpo)
    assert r.status_code == 422
    assert r.json() == {"detail": {"codigo": "validacao", "mensagem": "Verifique os campos assinalados.", "campos": campos}}
    # Pela ordem do formulário: o nome, depois a ordem.
    assert list(r.json()["detail"]["campos"]) == list(campos)
    assert cliente.base.crm_regioes.sem_id() == []
    assert cliente.base.crm_regioes.registo == []


def test_criar_com_o_corpo_vazio_da_422_no_nome(sessao):
    """Sem bytes nenhuns o corpo é `{}` (como no autónomo): falta o nome."""
    cliente = sessao(ADMIN_MASTER)
    r = cliente.post(REGIOES_URL, content=b"", headers=JSON)
    assert r.status_code == 422
    assert r.json()["detail"]["campos"] == {"nome": INDIQUE_O_NOME}


@pytest.mark.parametrize(
    "existente, chave, novo",
    [
        ("Lisboa", "lisboa", "Lisboa"),
        ("Lisboa", "lisboa", " LISBOA "),
        ("Setúbal", "setubal", "Setubal"),
        ("Setubal", "setubal", "SETÚBAL"),
        ("Lisboa", "lisboa", "\u180eLisboa\u180e"),
    ],
    ids=["igual", "com maiúsculas e espaços", "sem o acento", "com o acento à parte (NFD)", "com U+180E nas pontas"],
)
def test_criar_com_um_nome_que_ja_existe_da_409(sessao, existente, chave, novo):
    """`criarComUmNomeQueJaExisteDa409` (`nomesRepetidos`)."""
    cliente = sessao(ADMIN_MASTER, _base([_regiao(LISBOA, existente, 1, chave)]))
    antes = cliente.base.crm_regioes.sem_id()
    r = cliente.post(REGIOES_URL, json={"nome": novo, "ordem": 2})
    assert (r.status_code, r.json()) == (409, REGIAO_REPETIDA)
    assert cliente.base.crm_regioes.sem_id() == antes
    assert _escritas(cliente.base) == []


def test_criar_procura_o_repetido_pela_chave(sessao):
    cliente = sessao(ADMIN_MASTER)
    assert cliente.post(REGIOES_URL, json={"nome": "Setúbal"}).status_code == 201
    assert cliente.base.crm_regioes.chamadas("find_one") == [("find_one", {"nome_chave": "setubal"}, PROJECAO_ID)]


def test_criar_um_repetido_da_409_mesmo_sem_o_indice_unico(sessao):
    """Se o arranque não conseguiu criar os índices (o CRM arranca sem eles),
    a verificação antes de gravar continua a recusar o repetido."""
    base = BaseFalsa({
        "crm_membros": list(MEMBROS),
        "crm_regioes": ColeccaoFalsa([_regiao(SETUBAL, "Setúbal", 1, "setubal")], unicos=("id",)),
    })
    r = sessao(ADMIN_MASTER, base).post(REGIOES_URL, json={"nome": "setubal"})
    assert (r.status_code, r.json()) == (409, REGIAO_REPETIDA)
    assert len(base.crm_regioes.docs) == 1


class _OutroAdminCriaDepoisDaVerificacao(ColeccaoFalsa):
    """Outro admin grava "Setúbal" logo a seguir à primeira leitura deste
    pedido: a verificação passou, e é o índice único que recusa."""

    async def find_one(self, filtro=None, projecao=None, *, projection=None):
        doc = await super().find_one(filtro, projecao, projection=projection)
        if not getattr(self, "_ja_criou", False):
            self._ja_criou = True
            self.docs.append(_regiao(SETUBAL, "Setúbal", 4, "setubal"))
        return doc


def test_criar_quando_o_insert_da_chave_repetida_de_outra_regiao_e_409(sessao):
    regioes = _OutroAdminCriaDepoisDaVerificacao(unicos=("id", "nome_chave"))
    base = BaseFalsa({"crm_membros": list(MEMBROS), "crm_regioes": regioes})
    r = sessao(ADMIN_MASTER, base).post(REGIOES_URL, json={"nome": "setubal", "ordem": 1})
    assert (r.status_code, r.json()) == (409, REGIAO_REPETIDA)
    assert regioes.sem_id() == [_regiao(SETUBAL, "Setúbal", 4, "setubal")]
    # Verificou, tentou gravar e, recusado, confirmou que é outra região.
    assert [c[0] for c in regioes.registo] == ["find_one", "insert_one", "find_one"]


def test_criar_quando_o_insert_da_chave_repetida_sem_outra_regiao_com_o_nome_e_um_erro(sessao):
    """O `DuplicateKeyError` só é `regiao_repetida` quando há outra região com
    o nome; doutro modo não se disfarça de 409 (correções, linha "T2.9")."""
    base = BaseFalsa({
        "crm_membros": list(MEMBROS),
        "crm_regioes": ColeccaoFalsa([], falhar={"insert_one": DuplicateKeyError("E11000 id_1", 11000)}),
    })
    r = sessao(ADMIN_MASTER, base, levantar=False).post(REGIOES_URL, json={"nome": "Lisboa"})
    assert r.status_code == 500


def test_dois_admins_a_criar_a_mesma_regiao_ao_mesmo_tempo_so_um_grava(direto):
    """A corrida a sério: as duas verificações passam antes de qualquer insert
    (o duplo cede o controlo em cada operação) e é o índice único que decide."""
    base = _base()
    admin, ana = direto(base)

    async def _ao_mesmo_tempo():
        return await asyncio.gather(
            rotas_regioes.criar_regiao(admin, {"nome": "Setúbal", "ordem": 1}),
            rotas_regioes.criar_regiao(ana, {"nome": "SETUBAL", "ordem": 4}),
            return_exceptions=True,
        )

    primeiro, segundo = correr(_ao_mesmo_tempo())
    assert primeiro == {"id": primeiro["id"], "nome": "Setúbal", "ordem": 1}
    assert isinstance(segundo, HTTPException)
    assert (segundo.status_code, segundo.detail) == (409, REGIAO_REPETIDA["detail"])
    assert [c[0] for c in base.crm_regioes.registo] == ["find_one", "find_one", "insert_one", "insert_one", "find_one"]
    assert base.crm_regioes.sem_id() == [{"id": primeiro["id"], "nome": "Setúbal", "nome_chave": "setubal", "ordem": 1}]


def test_criar_quando_a_base_falha_e_um_erro(sessao):
    base = BaseFalsa({
        "crm_membros": list(MEMBROS),
        "crm_regioes": ColeccaoFalsa([], falhar={"insert_one": RuntimeError("base em baixo")}),
    })
    assert sessao(ADMIN_MASTER, base, levantar=False).post(REGIOES_URL, json={"nome": "Lisboa"}).status_code == 500


@pytest.mark.parametrize("bruto", [b"[]", b'"Lisboa"', b"null", b"{partido"], ids=["lista", "texto", "null", "partido"])
def test_criar_com_um_corpo_que_nao_e_um_objeto_json_da_400(sessao, bruto):
    cliente = sessao(ADMIN_MASTER)
    r = cliente.post(REGIOES_URL, content=bruto, headers=JSON)
    assert (r.status_code, r.json()) == (400, JSON_INVALIDO)
    assert cliente.base.crm_regioes.registo == []


# --- PATCH /regioes/{regiao_id} --------------------------------------------------------------------


def test_o_patch_muda_o_nome(sessao):
    """`oPatchMudaONome`: e a chave acompanha o nome novo."""
    cliente = sessao(ADMIN_MASTER, _base([_regiao(LISBOA, "Lisboa", 1, "lisboa")]))
    r = cliente.patch(_url(LISBOA), json={"nome": " Grande Lisboa "})
    assert r.status_code == 200
    assert r.json() == {"id": LISBOA, "nome": "Grande Lisboa", "ordem": 1}
    assert list(r.json()) == ["id", "nome", "ordem"]
    assert cliente.base.crm_regioes.sem_id() == [_regiao(LISBOA, "Grande Lisboa", 1, "grande lisboa")]
    assert cliente.base.crm_regioes.chamadas("find_one_and_update") == [(
        "find_one_and_update", {"id": LISBOA}, {"$set": {"nome": "Grande Lisboa", "nome_chave": "grande lisboa"}},
        PROJECAO_REGIAO, False, ReturnDocument.AFTER,
    )]


def test_o_patch_muda_a_ordem_e_a_lista_segue_a_nova(sessao):
    """`oPatchMudaAOrdemEAListaSegueANova`: só a ordem, sem procurar repetidos."""
    cliente = sessao(ADMIN_MASTER, _base([
        _regiao(LISBOA, "Lisboa", 1, "lisboa"),
        _regiao(PORTO, "Porto", 2, "porto"),
    ]))
    r = cliente.patch(_url(PORTO), json={"ordem": 0})
    assert (r.status_code, r.json()) == (200, {"id": PORTO, "nome": "Porto", "ordem": 0})
    assert cliente.base.crm_regioes.chamadas("find_one_and_update") == [
        ("find_one_and_update", {"id": PORTO}, {"$set": {"ordem": 0}}, PROJECAO_REGIAO, False, ReturnDocument.AFTER)
    ]
    assert cliente.base.crm_regioes.chamadas("find_one") == [("find_one", {"id": PORTO}, PROJECAO_REGIAO)]
    assert [regiao["id"] for regiao in cliente.get(REGIOES_URL).json()] == [PORTO, LISBOA]


def test_o_patch_muda_o_nome_e_a_ordem_juntos_e_so_esses(sessao):
    """`oPatchMudaONomeEAOrdemJuntosESoEsses`: `id` (e `nome_chave`) do corpo ignoram-se."""
    cliente = sessao(ADMIN_MASTER, _base([_regiao(LISBOA, "Lisboa", 1, "lisboa")]))
    r = cliente.patch(_url(LISBOA), json={
        "nome": "Lisboa e Vale do Tejo", "ordem": 7, "id": 99, "nome_chave": "x",
    })
    assert (r.status_code, r.json()) == (200, {"id": LISBOA, "nome": "Lisboa e Vale do Tejo", "ordem": 7})
    assert cliente.base.crm_regioes.sem_id() == [_regiao(LISBOA, "Lisboa e Vale do Tejo", 7, "lisboa e vale do tejo")]
    assert cliente.base.crm_regioes.chamadas("find_one_and_update") == [(
        "find_one_and_update",
        {"id": LISBOA},
        {"$set": {"nome": "Lisboa e Vale do Tejo", "nome_chave": "lisboa e vale do tejo", "ordem": 7}},
        PROJECAO_REGIAO,
        False,
        ReturnDocument.AFTER,
    )]


@pytest.mark.parametrize(
    "antigo, chave, novo",
    [("lisboa", "lisboa", "Lisboa"), ("setubal", "setubal", "Setúbal")],
    ids=["maiúscula", "acento"],
)
def test_corrigir_as_maiusculas_do_proprio_nome_nao_e_repetido(sessao, antigo, chave, novo):
    """`corrigirAsMaiusculasDoProprioNomeNaoEhRepetido` (correções, linha "T2.9"):
    a procura exclui a própria região."""
    cliente = sessao(ADMIN_MASTER, _base([
        _regiao(LISBOA, antigo, 1, chave),
        _regiao(PORTO, "Porto", 2, "porto"),
    ]))
    r = cliente.patch(_url(LISBOA), json={"nome": novo})
    assert r.status_code == 200
    assert r.json()["nome"] == novo
    assert cliente.base.crm_regioes.sem_id()[0] == _regiao(LISBOA, novo, 1, chave)
    assert ("find_one", {"nome_chave": chave, "id": {"$ne": LISBOA}}, PROJECAO_ID) in cliente.base.crm_regioes.registo


def test_o_patch_para_o_nome_de_outra_regiao_da_409(sessao):
    """`oPatchParaONomeDeOutraRegiaoDa409`: nada mudou, nem a ordem."""
    cliente = sessao(ADMIN_MASTER, _base([
        _regiao(LISBOA, "Lisboa", 1, "lisboa"),
        _regiao(PORTO, "Porto", 2, "porto"),
    ]))
    antes = cliente.base.crm_regioes.sem_id()
    r = cliente.patch(_url(PORTO), json={"nome": "lisboa", "ordem": 5})
    assert (r.status_code, r.json()) == (409, REGIAO_REPETIDA)
    assert cliente.base.crm_regioes.sem_id() == antes
    assert _escritas(cliente.base) == []


ALTERACOES_INVALIDAS = [
    ({"nome": ""}, {"nome": INDIQUE_O_NOME}),
    ({"nome": None}, {"nome": INDIQUE_O_NOME}),
    ({"ordem": "primeira"}, {"ordem": ORDEM_INVALIDA}),
    ({"nome": "Grande Lisboa", "ordem": None}, {"ordem": ORDEM_INVALIDA}),
]
IDS_ALTERACOES_INVALIDAS = ["nome vazio", "nome nulo", "ordem como texto", "um válido e um inválido (nada se grava)"]


@pytest.mark.parametrize("corpo, campos", ALTERACOES_INVALIDAS, ids=IDS_ALTERACOES_INVALIDAS)
def test_um_patch_com_valores_invalidos_da_422(sessao, corpo, campos):
    """`umPatchComValoresInvalidosDa422` (`alteracoesInvalidas`)."""
    cliente = sessao(ADMIN_MASTER, _base([_regiao(LISBOA, "Lisboa", 1, "lisboa")]))
    antes = cliente.base.crm_regioes.sem_id()
    r = cliente.patch(_url(LISBOA), json=corpo)
    assert r.status_code == 422
    assert r.json() == {"detail": {"codigo": "validacao", "mensagem": "Verifique os campos assinalados.", "campos": campos}}
    assert cliente.base.crm_regioes.sem_id() == antes
    assert _escritas(cliente.base) == []


def test_o_patch_valida_o_corpo_antes_de_procurar_a_regiao(sessao):
    """Como o autónomo (`validar` antes da transação): 422 antes do 404."""
    cliente = sessao(ADMIN_MASTER)
    r = cliente.patch(_url(NAO_EXISTE), json={"nome": "", "ordem": 1.5})
    assert r.status_code == 422
    assert r.json()["detail"]["campos"] == {"nome": INDIQUE_O_NOME, "ordem": ORDEM_INVALIDA}
    assert cliente.base.crm_regioes.registo == []


@pytest.mark.parametrize("regiao_id", ["999", NAO_EXISTE], ids=["número", "uuid"])
def test_uma_regiao_que_nao_existe_da_404(sessao, regiao_id):
    """`umaRegiaoQueNaoExisteDa404`: no PATCH e no DELETE."""
    cliente = sessao(ADMIN_MASTER, _base([_regiao(LISBOA, "Lisboa", 1, "lisboa")]))
    r = cliente.patch(_url(regiao_id), json={"nome": "Nenhures"})
    assert (r.status_code, r.json()) == (404, NAO_ENCONTRADA)
    r = cliente.delete(_url(regiao_id))
    assert (r.status_code, r.json()) == (404, NAO_ENCONTRADA)
    assert _escritas(cliente.base) == []


def test_o_patch_de_uma_regiao_que_nao_existe_da_404_antes_do_repetido(sessao):
    """Como o autónomo: primeiro a região (o `bloquear`), depois o nome."""
    cliente = sessao(ADMIN_MASTER, _base([_regiao(LISBOA, "Lisboa", 1, "lisboa")]))
    r = cliente.patch(_url(NAO_EXISTE), json={"nome": "Lisboa"})
    assert (r.status_code, r.json()) == (404, NAO_ENCONTRADA)


@pytest.mark.parametrize(
    "corpo", [{}, {"id": PORTO, "nome_chave": "porto", "Nome": "Porto", "ORDEM": 3}], ids=["vazio", "só outras chaves"]
)
def test_o_patch_sem_campos_da_200_com_a_regiao_e_nao_escreve(sessao, corpo):
    """O `alterar` do autónomo com `[]`: devolve a região tal como está (e o
    `$set` vazio, que o Mongo recusa, nunca se envia)."""
    cliente = sessao(ADMIN_MASTER, _base([_regiao(LISBOA, "Lisboa", 1, "lisboa")]))
    r = cliente.patch(_url(LISBOA), json=corpo)
    assert (r.status_code, r.json()) == (200, {"id": LISBOA, "nome": "Lisboa", "ordem": 1})
    assert _escritas(cliente.base) == []


def test_o_patch_sem_campos_de_uma_regiao_que_nao_existe_da_404(sessao):
    r = sessao(ADMIN_MASTER).patch(_url(NAO_EXISTE), json={})
    assert (r.status_code, r.json()) == (404, NAO_ENCONTRADA)


def test_o_patch_com_o_mesmo_nome_e_a_mesma_ordem_da_200(sessao):
    cliente = sessao(ADMIN_MASTER, _base([_regiao(LISBOA, "Lisboa", 1, "lisboa")]))
    r = cliente.patch(_url(LISBOA), json={"nome": "Lisboa", "ordem": 1})
    assert (r.status_code, r.json()) == (200, {"id": LISBOA, "nome": "Lisboa", "ordem": 1})
    assert cliente.base.crm_regioes.sem_id() == [_regiao(LISBOA, "Lisboa", 1, "lisboa")]


def test_depois_de_mudar_o_nome_o_antigo_fica_livre(sessao):
    cliente = sessao(ADMIN_MASTER, _base([_regiao(LISBOA, "Lisboa", 1, "lisboa")]))
    assert cliente.patch(_url(LISBOA), json={"nome": "Grande Lisboa"}).status_code == 200
    assert cliente.post(REGIOES_URL, json={"nome": "lisboa"}).status_code == 201
    r = cliente.patch(_url(LISBOA), json={"nome": "LISBOA"})
    assert (r.status_code, r.json()) == (409, REGIAO_REPETIDA)


def test_o_patch_repetido_da_409_mesmo_sem_o_indice_unico(sessao):
    base = BaseFalsa({
        "crm_membros": list(MEMBROS),
        "crm_regioes": ColeccaoFalsa(
            [_regiao(LISBOA, "Lisboa", 1, "lisboa"), _regiao(PORTO, "Porto", 2, "porto")], unicos=("id",)
        ),
    })
    r = sessao(ADMIN_MASTER, base).patch(_url(PORTO), json={"nome": "LISBOA"})
    assert (r.status_code, r.json()) == (409, REGIAO_REPETIDA)
    assert [d["nome"] for d in base.crm_regioes.docs] == ["Lisboa", "Porto"]


class _OutroAdminRenomeiaDepoisDaVerificacao(ColeccaoFalsa):
    """Outro admin dá o nome "Centro" a Lisboa logo a seguir à procura de
    repetidos deste pedido (a que tem `nome_chave` no filtro)."""

    async def find_one(self, filtro=None, projecao=None, *, projection=None):
        doc = await super().find_one(filtro, projecao, projection=projection)
        if "nome_chave" in (filtro or {}) and not getattr(self, "_ja_renomeou", False):
            self._ja_renomeou = True
            lisboa = next(d for d in self.docs if d["id"] == LISBOA)
            lisboa.update(nome="Centro", nome_chave="centro")
        return doc


def test_o_patch_quando_o_update_da_chave_repetida_de_outra_regiao_e_409(sessao):
    regioes = _OutroAdminRenomeiaDepoisDaVerificacao(
        [_regiao(LISBOA, "Lisboa", 1, "lisboa"), _regiao(PORTO, "Porto", 2, "porto")],
        unicos=("id", "nome_chave"),
    )
    base = BaseFalsa({"crm_membros": list(MEMBROS), "crm_regioes": regioes})
    r = sessao(ADMIN_MASTER, base).patch(_url(PORTO), json={"nome": "CENTRO", "ordem": 9})
    assert (r.status_code, r.json()) == (409, REGIAO_REPETIDA)
    assert regioes.sem_id() == [_regiao(LISBOA, "Centro", 1, "centro"), _regiao(PORTO, "Porto", 2, "porto")]
    assert regioes.registo[-1] == ("find_one", {"nome_chave": "centro", "id": {"$ne": PORTO}}, PROJECAO_ID)


def test_o_patch_quando_o_update_da_chave_repetida_sem_outra_regiao_com_o_nome_e_um_erro(sessao):
    """Correções, linha "T2.9": 409 só quando vem de outra região."""
    regioes = ColeccaoFalsa(
        [_regiao(LISBOA, "Lisboa", 1, "lisboa")],
        falhar={"find_one_and_update": DuplicateKeyError("E11000 nome_chave_1", 11000)},
    )
    base = BaseFalsa({"crm_membros": list(MEMBROS), "crm_regioes": regioes})
    r = sessao(ADMIN_MASTER, base, levantar=False).patch(_url(LISBOA), json={"nome": "Grande Lisboa"})
    assert r.status_code == 500


def test_dois_admins_a_dar_o_mesmo_nome_a_duas_regioes_ao_mesmo_tempo(direto):
    base = _base([_regiao(LISBOA, "Lisboa", 1, "lisboa"), _regiao(PORTO, "Porto", 2, "porto")])
    admin, ana = direto(base)

    async def _ao_mesmo_tempo():
        return await asyncio.gather(
            rotas_regioes.alterar_regiao(LISBOA, admin, {"nome": "Centro"}),
            rotas_regioes.alterar_regiao(PORTO, ana, {"nome": "CENTRO", "ordem": 0}),
            return_exceptions=True,
        )

    primeiro, segundo = correr(_ao_mesmo_tempo())
    assert primeiro == {"id": LISBOA, "nome": "Centro", "ordem": 1}
    assert isinstance(segundo, HTTPException)
    assert (segundo.status_code, segundo.detail) == (409, REGIAO_REPETIDA["detail"])
    assert base.crm_regioes.sem_id() == [_regiao(LISBOA, "Centro", 1, "centro"), _regiao(PORTO, "Porto", 2, "porto")]
    # As duas verificações correram antes das escritas.
    assert [c[0] for c in base.crm_regioes.registo] == [
        "find_one", "find_one", "find_one", "find_one", "find_one_and_update", "find_one_and_update", "find_one",
    ]


class _OutroAdminMudaONomeDepoisDeLer(ColeccaoFalsa):
    """Outro admin muda o nome do Porto para "Norte" logo a seguir à leitura
    da região por este pedido (o `antes`), e antes da escrita dele."""

    async def find_one(self, filtro=None, projecao=None, *, projection=None):
        doc = await super().find_one(filtro, projecao, projection=projection)
        if (filtro or {}).get("id") == PORTO and not getattr(self, "_ja_mudou", False):
            self._ja_mudou = True
            porto = next(d for d in self.docs if d["id"] == PORTO)
            porto.update(nome="Norte", nome_chave="norte")
        return doc


def test_o_patch_responde_com_a_regiao_como_ficou_gravada(sessao):
    """Revisão da F2: o autónomo bloqueava a linha (`bloquear`) e respondia com
    o que gravou. Sem bloqueio, responder com o `antes` lido mais o pedido
    devolvia o nome velho que outro admin já tinha mudado; a resposta tem de
    ser igual ao `GET` seguinte."""
    regioes = _OutroAdminMudaONomeDepoisDeLer(
        [_regiao(LISBOA, "Lisboa", 1, "lisboa"), _regiao(PORTO, "Porto", 2, "porto")],
        unicos=("id", "nome_chave"),
    )
    cliente = sessao(ADMIN_MASTER, BaseFalsa({"crm_membros": list(MEMBROS), "crm_regioes": regioes}))
    r = cliente.patch(_url(PORTO), json={"ordem": 0})
    assert (r.status_code, r.json()) == (200, {"id": PORTO, "nome": "Norte", "ordem": 0})
    assert r.json() == next(g for g in cliente.get(REGIOES_URL).json() if g["id"] == PORTO)
    assert regioes.sem_id()[1] == _regiao(PORTO, "Norte", 0, "norte")


def test_dois_admins_a_mudar_campos_diferentes_da_mesma_regiao_ao_mesmo_tempo(direto):
    """Revisão da F2: os dois leem a região antes de qualquer escrita; um muda
    a ordem e o outro o nome. Na base ficam as duas mudanças, e cada resposta
    é a região como ficou logo a seguir à sua escrita: a do último a gravar é
    igual ao `GET` seguinte (antes, trazia a ordem velha)."""
    base = _base([_regiao(LISBOA, "Lisboa", 1, "lisboa"), _regiao(PORTO, "Porto", 2, "porto")])
    admin, ana = direto(base)

    async def _ao_mesmo_tempo():
        return await asyncio.gather(
            rotas_regioes.alterar_regiao(PORTO, admin, {"ordem": 0}),
            rotas_regioes.alterar_regiao(PORTO, ana, {"nome": "Norte"}),
        )

    da_ordem, do_nome = correr(_ao_mesmo_tempo())
    assert base.crm_regioes.sem_id()[1] == _regiao(PORTO, "Norte", 0, "norte")
    # A ordem grava primeiro (o pedido do nome ainda procura repetidos).
    assert da_ordem == {"id": PORTO, "nome": "Porto", "ordem": 0}
    assert do_nome == {"id": PORTO, "nome": "Norte", "ordem": 0}
    lista = correr(rotas_regioes.listar_regioes(admin))
    assert do_nome == next(g for g in lista if g["id"] == PORTO)


class _ApagadaDepoisDeLer(ColeccaoFalsa):
    """Outro admin apaga a região logo a seguir à primeira leitura."""

    async def find_one(self, filtro=None, projecao=None, *, projection=None):
        doc = await super().find_one(filtro, projecao, projection=projection)
        if not getattr(self, "_ja_apagou", False):
            self._ja_apagou = True
            self.docs.clear()
        return doc


@pytest.mark.parametrize("corpo", [{"ordem": 4}, {"nome": "Grande Lisboa", "ordem": 4}], ids=["só a ordem", "nome e ordem"])
def test_o_patch_de_uma_regiao_apagada_entretanto_da_404_e_nao_a_ressuscita(sessao, corpo):
    regioes = _ApagadaDepoisDeLer([_regiao(LISBOA, "Lisboa", 1, "lisboa")], unicos=("id", "nome_chave"))
    base = BaseFalsa({"crm_membros": list(MEMBROS), "crm_regioes": regioes})
    r = sessao(ADMIN_MASTER, base).patch(_url(LISBOA), json=corpo)
    assert (r.status_code, r.json()) == (404, NAO_ENCONTRADA)
    assert regioes.docs == []
    assert all(c[4] is False for c in regioes.chamadas("find_one_and_update")), "nunca com upsert"


@pytest.mark.parametrize("bruto", [b"[]", b"null", b"{partido"], ids=["lista", "null", "partido"])
def test_o_patch_com_um_corpo_que_nao_e_um_objeto_json_da_400(sessao, bruto):
    cliente = sessao(ADMIN_MASTER, _base([_regiao(LISBOA, "Lisboa", 1, "lisboa")]))
    r = cliente.patch(_url(LISBOA), content=bruto, headers=JSON)
    assert (r.status_code, r.json()) == (400, JSON_INVALIDO)
    assert cliente.base.crm_regioes.registo == []


# --- DELETE /regioes/{regiao_id} -------------------------------------------------------------------


def _loja(loja_id, regiao_id):
    return {"id": loja_id, "nome": f"Loja {loja_id}", "regiao_id": regiao_id}


def test_apagar_uma_regiao_sem_lojas_da_200(sessao):
    """`apagarUmaRegiaoSemLojasDa200`: e depois já não existe (404)."""
    cliente = sessao(ADMIN_MASTER, _base([
        _regiao(LISBOA, "Lisboa", 1, "lisboa"),
        _regiao(PORTO, "Porto", 2, "porto"),
    ]))
    r = cliente.delete(_url(LISBOA))
    assert (r.status_code, r.json()) == (200, {"apagada": True})
    assert r.json()["apagada"] is True, "um booleano JSON, não 1 (em Python, 1 == True)"
    assert cliente.base.crm_regioes.sem_id() == [_regiao(PORTO, "Porto", 2, "porto")]
    assert [regiao["id"] for regiao in cliente.get(REGIOES_URL).json()] == [PORTO]
    assert cliente.base.crm_lojas.chamadas("count_documents") == [("count_documents", {"regiao_id": LISBOA})]
    assert cliente.base.crm_regioes.chamadas("delete_one") == [("delete_one", {"id": LISBOA})]
    r = cliente.delete(_url(LISBOA))
    assert (r.status_code, r.json()) == (404, NAO_ENCONTRADA)


def test_uma_regiao_com_lojas_nao_se_apaga(sessao):
    """`umaRegiaoComLojasNaoSeApaga`: a região continua, e a loja continua nela."""
    lojas = [{"id": "l-baixa", "nome": "Mercearia da Baixa", "regiao_id": LISBOA}]
    cliente = sessao(ADMIN_MASTER, _base([_regiao(LISBOA, "Lisboa", 1, "lisboa")], lojas=lojas))
    antes = cliente.base.crm_regioes.sem_id()
    r = cliente.delete(_url(LISBOA))
    assert (r.status_code, r.json()) == (409, REGIAO_COM_LOJAS)
    assert cliente.base.crm_regioes.sem_id() == antes
    assert [loja["regiao_id"] for loja in cliente.base.crm_lojas.sem_id()] == [LISBOA]
    assert _escritas(cliente.base) == []


def test_lojas_de_outras_regioes_ou_sem_regiao_nao_impedem_de_apagar(sessao):
    lojas = [_loja("l-porto", PORTO), _loja("l-sem", None), {"id": "l-sem-campo", "nome": "Sem campo"}]
    cliente = sessao(ADMIN_MASTER, _base(
        [_regiao(LISBOA, "Lisboa", 1, "lisboa"), _regiao(PORTO, "Porto", 2, "porto")], lojas=lojas,
    ))
    assert cliente.delete(_url(LISBOA)).status_code == 200
    assert len(cliente.base.crm_lojas.docs) == 3


def test_apagar_uma_regiao_que_nao_existe_da_404_mesmo_com_lojas_que_a_apontam(sessao):
    """Primeiro a região (como o `bloquear` do autónomo), depois as lojas."""
    cliente = sessao(ADMIN_MASTER, _base(lojas=[_loja("l-orfa", NAO_EXISTE)]))
    r = cliente.delete(_url(NAO_EXISTE))
    assert (r.status_code, r.json()) == (404, NAO_ENCONTRADA)
    assert cliente.base.crm_lojas.registo == []


def test_apagar_uma_regiao_apagada_entretanto_da_404(sessao):
    regioes = _ApagadaDepoisDeLer([_regiao(LISBOA, "Lisboa", 1, "lisboa")], unicos=("id", "nome_chave"))
    base = BaseFalsa({"crm_membros": list(MEMBROS), "crm_regioes": regioes})
    r = sessao(ADMIN_MASTER, base).delete(_url(LISBOA))
    assert (r.status_code, r.json()) == (404, NAO_ENCONTRADA)


def test_apagar_quando_a_base_falha_e_um_erro(sessao):
    base = BaseFalsa({
        "crm_membros": list(MEMBROS),
        "crm_regioes": ColeccaoFalsa(
            [_regiao(LISBOA, "Lisboa", 1, "lisboa")], falhar={"delete_one": RuntimeError("base em baixo")}
        ),
    })
    assert sessao(ADMIN_MASTER, base, levantar=False).delete(_url(LISBOA)).status_code == 500


# --- De ponta a ponta: a sessão verdadeira do portal ---------------------------------------------

SEGREDO = "segredo-de-teste-crm-regioes"
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
    base = _base([_regiao(LISBOA, "Lisboa", 1, "lisboa")])
    monkeypatch.setattr(faturacao.auth, "obter_db", lambda: base)
    monkeypatch.setattr(crm.db, "obter_db", lambda: base)
    app = FastAPI()
    app.include_router(crm.router)
    cliente = TestClient(app)
    cliente.base = base
    return cliente


TODAS = [("GET", REGIOES_URL, None)] + ESCRITAS
IDS_TODAS = ["listar"] + IDS_ESCRITAS


@pytest.mark.parametrize("metodo, url, corpo", TODAS, ids=IDS_TODAS)
def test_sem_sessao_da_o_403_herdado(portal, metodo, url, corpo):
    """`semSessaoListarDa401` e `semSessaoMexerNasRegioesDa401`: no portal,
    sem cabeçalho é o 403 do HTTPBearer (o frontend trata-o como sessão em
    falta)."""
    r = _pedir(portal, metodo, url, corpo)
    assert (r.status_code, r.json()) == (403, {"detail": "Not authenticated"})
    assert portal.base.crm_regioes.registo == []


@pytest.mark.parametrize("metodo, url, _corpo", COM_CORPO, ids=IDS_COM_CORPO)
def test_sem_cabecalho_e_com_json_partido_da_o_403_herdado_e_nunca_400(portal, metodo, url, _corpo):
    """Correções do plano, linha "T1.3 / T2.15"."""
    r = portal.request(metodo, url, content=b"[", headers=JSON)
    assert (r.status_code, r.json()) == (403, {"detail": "Not authenticated"})
    assert portal.base.users.registo == []
    assert portal.base.crm_regioes.registo == []


@pytest.mark.parametrize("metodo, url, corpo", TODAS, ids=IDS_TODAS)
def test_uma_conta_apagada_da_401_sessao_terminada(portal, metodo, url, corpo):
    r = _pedir(portal, metodo, url, corpo, headers=_cabecalho("u-apagada"))
    assert (r.status_code, r.json()) == (401, {"detail": "Sessão terminada"})
    assert portal.base.crm_regioes.registo == []


def test_de_ponta_a_ponta_criar_listar_mudar_e_apagar(portal):
    admin = _cabecalho("u-admin", email=ADMIN_LOCAL, role="admin")
    ze = _cabecalho("u-ze")

    r = portal.post(REGIOES_URL, json={"nome": "Setúbal", "ordem": 0}, headers=admin)
    assert r.status_code == 201
    setubal = r.json()["id"]
    assert portal.get(REGIOES_URL, headers=ze).json() == [
        {"id": setubal, "nome": "Setúbal", "ordem": 0},
        {"id": LISBOA, "nome": "Lisboa", "ordem": 1},
    ]
    r = portal.post(REGIOES_URL, json={"nome": "Faro"}, headers=ze)
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)

    r = portal.post(REGIOES_URL, json={"nome": "SETUBAL"}, headers=admin)
    assert (r.status_code, r.json()) == (409, REGIAO_REPETIDA)

    r = portal.patch(_url(setubal), json={"nome": "Península de Setúbal", "ordem": 2}, headers=admin)
    assert (r.status_code, r.json()) == (200, {"id": setubal, "nome": "Península de Setúbal", "ordem": 2})
    assert [regiao["id"] for regiao in portal.get(REGIOES_URL, headers=ze).json()] == [LISBOA, setubal]

    assert portal.delete(_url(setubal), headers=admin).json() == {"apagada": True}
    assert portal.get(REGIOES_URL, headers=ze).json() == [{"id": LISBOA, "nome": "Lisboa", "ordem": 1}]
