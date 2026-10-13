"""`POST /api/crm/membros`, `PATCH` e `DELETE /api/crm/membros/{membro_id}` —
adicionar, mudar e retirar membros, só admin do CRM (plano T1.7; desenho §3.1;
dossiê §4 e §6).

- POST `{user_id, perfil}` → 201 com a mesma forma de uma linha do
  `GET /membros`; grava `{id (uuid4), user_id, perfil, criado_em, criado_por}`.
  Ordem: campos (422) → a conta existe (422 em `user_id`) → é o admin master
  (409 `admin_master`) → já é membro (409 `ja_membro`, também na corrida, pelo
  índice único de `user_id`).
- PATCH `{perfil}` → 200 com a linha; 422 antes do 404 (como o autónomo, que
  valida o corpo antes de procurar).
- DELETE → 200 `{retirado: true}`; outra vez → 404.
- A dependência de perfil vem antes de `corpo_json`: sem sessão (ou sem perfil)
  e com JSON partido dá 403, nunca 400 (correções, linha "T1.3 / T2.15").

Rotas por `TestClient` com `dependency_overrides[utilizador_atual]` e
`monkeypatch.setattr(crm.db, "obter_db", …)` (plano §10); o relógio parado com
`monkeypatch.setattr(relogio, "agora", …)`; no fim, de ponta a ponta com a
sessão verdadeira do portal (JWT + conta lida da base).
"""
import asyncio
import time
import uuid
from datetime import datetime, timezone

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

import crm
import crm.db
import faturacao.auth
from crm import membros as rotas_membros
from crm import relogio
from crm.auth import SO_ADMIN, membro_crm_atual
from crm.pedidos import corpo_json
from faturacao.auth import utilizador_atual

from .duplos import BaseFalsa, ColeccaoFalsa, correr

MEMBROS_URL = "/api/crm/membros"
UM_MEMBRO_URL = "/api/crm/membros/{membro_id}"
ADMIN_LOCAL = "admin.local@example.com"
JSON = {"Content-Type": "application/json"}

AGORA = datetime(2026, 10, 10, 9, 30, 15, 987654, tzinfo=timezone.utc)
CRIADO_EM = "2026-10-10T09:30:15Z"

MENSAGEM_PERFIL = "Escolha um perfil: admin, utilizador ou motorista."
ESCOLHER_CONTA = "Escolha uma conta do portal."
CONTA_INEXISTENTE = "A conta não existe."
NAO_ENCONTRADO = {"detail": {"codigo": "nao_encontrado", "mensagem": "Membro não encontrado."}}
JA_MEMBRO = {"detail": {"codigo": "ja_membro", "mensagem": "Esta pessoa já é membro do CRM."}}
ADMIN_MASTER_409 = {"detail": {"codigo": "admin_master", "mensagem": "O administrador principal já é admin do CRM."}}
JSON_INVALIDO = {"detail": {"codigo": "json_invalido", "mensagem": "O pedido não é JSON válido."}}
SEM_PERMISSAO = {"detail": {"codigo": "sem_permissao", "mensagem": "Sem permissão para esta ação."}}
SEM_ACESSO = {"detail": {"codigo": "sem_acesso_crm", "mensagem": "Sem acesso ao CRM."}}

CHAVES_MEMBRO = {
    "id", "user_id", "nome", "email", "tipo_conta", "perfil", "admin_master", "conta_existe", "criado_em",
}
CHAVES_GUARDADAS = {"id", "user_id", "perfil", "criado_em", "criado_por"}
PROJECAO_CONTAS = {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1}

USERS = [
    {"id": "u-admin", "email": ADMIN_LOCAL, "name": "Administrador Principal", "role": "admin",
     "password": "$2b$12$hash-do-admin"},
    {"id": "u-ana", "email": "ana@example.com", "name": "Ana Reis", "role": "contabilista",
     "password": "$2b$12$hash-da-ana"},
    {"id": "u-ze", "email": "ze@example.com", "name": "Zé Silva", "role": "colaborador",
     "password": "$2b$12$hash-do-ze"},
    {"id": "u-alv", "email": "alvaro@example.com", "name": "álvaro Costa", "role": "gerente",
     "password": "$2b$12$hash-do-alvaro"},
    {"id": "u-bea", "email": "bea@example.com", "name": "Beatriz Lopes", "role": "colaborador",
     "password": "$2b$12$hash-da-bea"},
    {"id": "u-eli", "email": "elio@example.com", "name": "Élio Matos", "role": "gerente",
     "password": "$2b$12$hash-do-elio"},
]
MEMBROS = [
    {"id": "m-ana", "user_id": "u-ana", "perfil": "admin",
     "criado_em": "2026-10-03T09:00:00Z", "criado_por": "u-admin"},
    {"id": "m-ze", "user_id": "u-ze", "perfil": "utilizador",
     "criado_em": "2026-10-01T09:00:00Z", "criado_por": "u-admin"},
    {"id": "m-alv", "user_id": "u-alv", "perfil": "motorista",
     "criado_em": "2026-10-02T09:00:00Z", "criado_por": "u-ana"},
    {"id": "m-apagada", "user_id": "u-apagada", "perfil": "utilizador",
     "criado_em": "2026-09-30T09:00:00Z", "criado_por": "u-admin"},
]

ADMIN_MASTER = {"user_id": "u-admin", "email": ADMIN_LOCAL, "role": "admin"}
ANA_ADMIN_DO_CRM = {"user_id": "u-ana", "email": "ana@example.com", "role": "contabilista"}
ZE_UTILIZADOR = {"user_id": "u-ze", "email": "ze@example.com", "role": "colaborador"}
ALVARO_MOTORISTA = {"user_id": "u-alv", "email": "alvaro@example.com", "role": "gerente"}
BEA_NAO_MEMBRO = {"user_id": "u-bea", "email": "bea@example.com", "role": "colaborador"}

LINHA_ZE = {
    "id": "m-ze", "user_id": "u-ze", "nome": "Zé Silva", "email": "ze@example.com", "tipo_conta": "colaborador",
    "perfil": "utilizador", "admin_master": False, "conta_existe": True, "criado_em": "2026-10-01T09:00:00Z",
}

# As três rotas de escrita, com um corpo válido para cada uma.
ESCRITAS = [
    ("POST", MEMBROS_URL, {"user_id": "u-bea", "perfil": "utilizador"}),
    ("PATCH", MEMBROS_URL + "/m-ze", {"perfil": "admin"}),
    ("DELETE", MEMBROS_URL + "/m-ze", None),
]
IDS_ESCRITAS = ["criar", "mudar", "retirar"]
COM_CORPO = ESCRITAS[:2]
IDS_COM_CORPO = IDS_ESCRITAS[:2]


def _base(membros=MEMBROS, users=USERS):
    return BaseFalsa({"crm_membros": list(membros), "users": list(users)})


def _guardado(base, membro_id):
    achados = [d for d in base.crm_membros.sem_id() if d.get("id") == membro_id]
    assert len(achados) <= 1
    return achados[0] if achados else None


def _escritas(base):
    return [c for c in base.crm_membros.registo if c[0] in ("insert_one", "update_one", "delete_one", "delete_many")]


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
    `dependency_overrides`, a base do CRM trocada pelo único ponto e o relógio
    parado em AGORA. `sessao(utilizador, base)` devolve o cliente (com
    `cliente.base`); para outra pessoa na mesma base, `sessao(outra, cliente.base)`."""
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


# --- As rotas: onde estão, quem as guarda e por que ordem ----------------------------


@pytest.mark.parametrize(
    "metodo, caminho",
    [("POST", MEMBROS_URL), ("PATCH", UM_MEMBRO_URL), ("DELETE", UM_MEMBRO_URL)],
    ids=IDS_ESCRITAS,
)
def test_as_rotas_de_escrita_existem_e_vivem_em_crm_membros(metodo, caminho):
    rota = _rota(caminho, metodo)
    assert rota.methods == {metodo}
    assert rota.endpoint.__module__ == "crm.membros"


def test_criar_responde_201():
    assert _rota(MEMBROS_URL, "POST").status_code == 201


@pytest.mark.parametrize(
    "metodo, caminho",
    [("POST", MEMBROS_URL), ("PATCH", UM_MEMBRO_URL), ("DELETE", UM_MEMBRO_URL)],
    ids=IDS_ESCRITAS,
)
def test_as_rotas_de_escrita_sao_so_do_admin_do_crm(metodo, caminho):
    """Exatamente uma guarda de perfil, a SO_ADMIN, sobre `membro_crm_atual`."""
    dependencias = _dependencias(_rota(caminho, metodo))
    assert membro_crm_atual in dependencias
    assert [d for d in dependencias if hasattr(d, "perfis_crm")] == [SO_ADMIN]


@pytest.mark.parametrize("metodo, caminho", [("POST", MEMBROS_URL), ("PATCH", UM_MEMBRO_URL)], ids=IDS_COM_CORPO)
def test_a_guarda_de_perfil_vem_antes_do_corpo(metodo, caminho):
    """Correções do plano, linha "T1.3 / T2.15": o FastAPI resolve as
    dependências pela ordem em que estão declaradas."""
    diretas = [d.call for d in _rota(caminho, metodo).dependant.dependencies]
    assert diretas == [SO_ADMIN, corpo_json]


def test_retirar_nao_le_o_corpo():
    assert corpo_json not in _dependencias(_rota(UM_MEMBRO_URL, "DELETE"))


def test_candidatos_continua_a_ser_a_lista_e_nao_um_membro(sessao):
    """`/membros/candidatos` vem antes de `/membros/{membro_id}`: o GET dá a
    lista; um PATCH ou DELETE com "candidatos" é só um id que não existe."""
    cliente = sessao(ADMIN_MASTER)
    r = cliente.get(MEMBROS_URL + "/candidatos")
    assert r.status_code == 200
    assert [c["id"] for c in r.json()] == ["u-bea", "u-eli"]
    r = cliente.patch(MEMBROS_URL + "/candidatos", json={"perfil": "admin"})
    assert (r.status_code, r.json()) == (404, NAO_ENCONTRADO)
    r = cliente.delete(MEMBROS_URL + "/candidatos")
    assert (r.status_code, r.json()) == (404, NAO_ENCONTRADO)


# --- Quem pode escrever ----------------------------------------------------------------


@pytest.mark.parametrize("metodo, url, corpo", ESCRITAS, ids=IDS_ESCRITAS)
@pytest.mark.parametrize("utilizador", [ZE_UTILIZADOR, ALVARO_MOTORISTA], ids=["utilizador", "motorista"])
def test_um_membro_que_nao_e_admin_recebe_403_sem_permissao_e_nada_muda(sessao, metodo, url, corpo, utilizador):
    cliente = sessao(utilizador)
    antes = cliente.base.crm_membros.sem_id()
    r = _pedir(cliente, metodo, url, corpo)
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)
    assert cliente.base.crm_membros.sem_id() == antes
    assert _escritas(cliente.base) == []
    assert cliente.base.users.registo == []


@pytest.mark.parametrize("metodo, url, corpo", ESCRITAS, ids=IDS_ESCRITAS)
def test_quem_nao_e_membro_recebe_403_sem_acesso_e_nada_muda(sessao, metodo, url, corpo):
    cliente = sessao(BEA_NAO_MEMBRO)
    r = _pedir(cliente, metodo, url, corpo)
    assert (r.status_code, r.json()) == (403, SEM_ACESSO)
    assert _escritas(cliente.base) == []


@pytest.mark.parametrize("metodo, url, _corpo", COM_CORPO, ids=IDS_COM_CORPO)
@pytest.mark.parametrize(
    "utilizador, esperado",
    [(ZE_UTILIZADOR, SEM_PERMISSAO), (BEA_NAO_MEMBRO, SEM_ACESSO)],
    ids=["sem-perfil", "nao-membro"],
)
def test_sem_perfil_e_com_json_partido_da_403_e_nunca_400(sessao, metodo, url, _corpo, utilizador, esperado):
    r = sessao(utilizador).request(metodo, url, content=b"[", headers=JSON)
    assert (r.status_code, r.json()) == (403, esperado)


@pytest.mark.parametrize("utilizador", [ADMIN_MASTER, ANA_ADMIN_DO_CRM], ids=["admin-master", "membro-admin"])
def test_o_admin_master_e_os_membros_admin_escrevem(sessao, utilizador):
    cliente = sessao(utilizador)
    assert cliente.post(MEMBROS_URL, json={"user_id": "u-bea", "perfil": "utilizador"}).status_code == 201
    assert cliente.patch(MEMBROS_URL + "/m-alv", json={"perfil": "utilizador"}).status_code == 200
    assert cliente.delete(MEMBROS_URL + "/m-alv").status_code == 200


# --- POST /membros ------------------------------------------------------------------------


def test_criar_da_201_com_a_linha_da_lista_e_grava_quem_e_quando(sessao):
    cliente = sessao(ADMIN_MASTER)
    r = cliente.post(MEMBROS_URL, json={"user_id": "u-eli", "perfil": "utilizador"})
    assert r.status_code == 201
    corpo = r.json()
    novo_id = corpo["id"]
    assert corpo == {
        "id": novo_id, "user_id": "u-eli", "nome": "Élio Matos", "email": "elio@example.com",
        "tipo_conta": "gestor", "perfil": "utilizador", "admin_master": False, "conta_existe": True,
        "criado_em": CRIADO_EM,
    }
    assert set(corpo) == CHAVES_MEMBRO
    assert _guardado(cliente.base, novo_id) == {
        "id": novo_id, "user_id": "u-eli", "perfil": "utilizador",
        "criado_em": CRIADO_EM, "criado_por": "u-admin",
    }


def test_criar_da_um_id_uuid4_em_texto_e_cada_membro_tem_o_seu(sessao):
    cliente = sessao(ADMIN_MASTER)
    um = cliente.post(MEMBROS_URL, json={"user_id": "u-bea", "perfil": "utilizador"}).json()["id"]
    outro = cliente.post(MEMBROS_URL, json={"user_id": "u-eli", "perfil": "motorista"}).json()["id"]
    for novo_id in (um, outro):
        assert isinstance(novo_id, str)
        assert uuid.UUID(novo_id).version == 4
        assert str(uuid.UUID(novo_id)) == novo_id
    assert um != outro


def test_criar_regista_como_autor_o_admin_que_pediu(sessao):
    cliente = sessao(ANA_ADMIN_DO_CRM)
    novo_id = cliente.post(MEMBROS_URL, json={"user_id": "u-bea", "perfil": "admin"}).json()["id"]
    assert _guardado(cliente.base, novo_id)["criado_por"] == "u-ana"


def test_criar_grava_so_os_campos_do_membro_e_ignora_as_outras_chaves(sessao):
    """`id`, `criado_por`, `criado_em`, `admin_master`… do corpo ignoram-se."""
    cliente = sessao(ADMIN_MASTER)
    r = cliente.post(MEMBROS_URL, json={
        "user_id": "u-bea", "perfil": "motorista", "id": "m-forjado", "criado_por": "u-ze",
        "criado_em": "1999-01-01T00:00:00Z", "admin_master": True, "atualizado_em": "x", "_id": "y",
    })
    assert r.status_code == 201
    novo_id = r.json()["id"]
    assert novo_id != "m-forjado"
    assert r.json()["admin_master"] is False
    guardado = _guardado(cliente.base, novo_id)
    assert set(guardado) == CHAVES_GUARDADAS
    assert guardado["criado_por"] == "u-admin"
    assert guardado["criado_em"] == CRIADO_EM


def test_o_membro_novo_aparece_na_lista_e_sai_dos_candidatos(sessao):
    cliente = sessao(ADMIN_MASTER)
    novo = cliente.post(MEMBROS_URL, json={"user_id": "u-bea", "perfil": "utilizador"}).json()
    lista = cliente.get(MEMBROS_URL).json()
    assert novo in lista
    assert [linha["user_id"] for linha in lista] == ["u-admin", "u-alv", "u-ana", "u-bea", "u-ze", "u-apagada"]
    assert [c["id"] for c in cliente.get(MEMBROS_URL + "/candidatos").json()] == ["u-eli"]


def test_o_membro_novo_entra_no_crm_no_pedido_seguinte(sessao):
    base = sessao(ADMIN_MASTER).base
    bea = sessao(BEA_NAO_MEMBRO, base)
    assert bea.get("/api/crm/eu").json() == {"membro": False, "perfil": None, "admin_master": False}
    admin = sessao(ADMIN_MASTER, base)
    assert admin.post(MEMBROS_URL, json={"user_id": "u-bea", "perfil": "admin"}).status_code == 201
    bea = sessao(BEA_NAO_MEMBRO, base)
    assert bea.get("/api/crm/eu").json() == {"membro": True, "perfil": "admin", "admin_master": False}
    assert bea.get(MEMBROS_URL).status_code == 200


@pytest.mark.parametrize(
    "corpo, campos",
    [
        ({}, {"user_id": ESCOLHER_CONTA, "perfil": MENSAGEM_PERFIL}),
        ({"user_id": "", "perfil": "utilizador"}, {"user_id": ESCOLHER_CONTA}),
        ({"user_id": "   ", "perfil": "utilizador"}, {"user_id": ESCOLHER_CONTA}),
        ({"user_id": None, "perfil": "utilizador"}, {"user_id": ESCOLHER_CONTA}),
        ({"user_id": 7, "perfil": "utilizador"}, {"user_id": ESCOLHER_CONTA}),
        ({"user_id": True, "perfil": "utilizador"}, {"user_id": ESCOLHER_CONTA}),
        ({"user_id": ["u-bea"], "perfil": "utilizador"}, {"user_id": ESCOLHER_CONTA}),
        ({"user_id": "u-bea", "perfil": "chefe"}, {"perfil": MENSAGEM_PERFIL}),
        ({"user_id": "u-bea", "perfil": "Admin"}, {"perfil": MENSAGEM_PERFIL}),
        ({"user_id": "u-bea", "perfil": None}, {"perfil": MENSAGEM_PERFIL}),
        ({"user_id": "u-bea"}, {"perfil": MENSAGEM_PERFIL}),
        ({"perfil": 1, "user_id": {"id": "u-bea"}}, {"user_id": ESCOLHER_CONTA, "perfil": MENSAGEM_PERFIL}),
    ],
    ids=[
        "corpo vazio",
        "conta vazia",
        "conta so com espacos",
        "conta nula",
        "conta que e um numero",
        "conta que e verdadeiro",
        "conta numa lista",
        "perfil desconhecido",
        "perfil com maiuscula",
        "perfil nulo",
        "perfil em falta",
        "os dois errados",
    ],
)
def test_criar_com_campos_invalidos_da_422_e_nada_se_grava(sessao, corpo, campos):
    cliente = sessao(ADMIN_MASTER)
    r = cliente.post(MEMBROS_URL, json=corpo)
    assert r.status_code == 422
    assert r.json() == {"detail": {"codigo": "validacao", "mensagem": "Verifique os campos assinalados.", "campos": campos}}
    # A ordem dos campos é a do formulário: a conta, depois o perfil.
    assert list(r.json()["detail"]["campos"]) == list(campos)
    assert _escritas(cliente.base) == []
    # Com os campos errados nem se procura a conta.
    assert cliente.base.users.registo == []


@pytest.mark.parametrize("user_id", ["u-nao-existe", "u-apagada", " u-bea "], ids=["inventada", "apagada", "com espacos"])
def test_criar_com_uma_conta_que_nao_existe_da_422_na_conta(sessao, user_id):
    """O id não se apara: " u-bea " não é a conta da Bea."""
    cliente = sessao(ADMIN_MASTER)
    r = cliente.post(MEMBROS_URL, json={"user_id": user_id, "perfil": "utilizador"})
    assert r.status_code == 422
    assert r.json()["detail"]["campos"] == {"user_id": CONTA_INEXISTENTE}
    assert _escritas(cliente.base) == []


def test_criar_procura_a_conta_so_com_a_projecao_minima(sessao):
    cliente = sessao(ADMIN_MASTER)
    assert cliente.post(MEMBROS_URL, json={"user_id": "u-bea", "perfil": "utilizador"}).status_code == 201
    assert cliente.base.users.chamadas("find_one") == [("find_one", {"id": "u-bea"}, PROJECAO_CONTAS)]
    assert cliente.base.users.chamadas("find") == []


@pytest.mark.parametrize("utilizador", [ADMIN_MASTER, ANA_ADMIN_DO_CRM], ids=["o-proprio", "outro-admin"])
@pytest.mark.parametrize("perfil", ["admin", "motorista"])
def test_criar_o_admin_master_da_409_admin_master(sessao, utilizador, perfil):
    cliente = sessao(utilizador)
    r = cliente.post(MEMBROS_URL, json={"user_id": "u-admin", "perfil": perfil})
    assert (r.status_code, r.json()) == (409, ADMIN_MASTER_409)
    assert _escritas(cliente.base) == []


def test_criar_o_admin_master_da_409_mesmo_com_uma_linha_antiga_dele(sessao):
    """O admin master vem antes do "já é membro": a linha antiga não conta."""
    membros = MEMBROS + [{"id": "m-antiga", "user_id": "u-admin", "perfil": "utilizador"}]
    r = sessao(ADMIN_MASTER, _base(membros=membros)).post(MEMBROS_URL, json={"user_id": "u-admin", "perfil": "admin"})
    assert (r.status_code, r.json()) == (409, ADMIN_MASTER_409)


@pytest.mark.parametrize("user_id", ["u-ze", "u-ana", "u-alv"])
def test_criar_quem_ja_e_membro_da_409_ja_membro_e_nada_muda(sessao, user_id):
    cliente = sessao(ADMIN_MASTER)
    antes = cliente.base.crm_membros.sem_id()
    r = cliente.post(MEMBROS_URL, json={"user_id": user_id, "perfil": "admin"})
    assert (r.status_code, r.json()) == (409, JA_MEMBRO)
    assert cliente.base.crm_membros.sem_id() == antes


def test_criar_com_uma_linha_de_perfil_desconhecido_da_409_ja_membro(sessao):
    """A linha existe (corrige-se o perfil com o PATCH em vez de a juntar)."""
    membros = MEMBROS + [{"id": "m-bea", "user_id": "u-bea", "perfil": "gestor"}]
    r = sessao(ADMIN_MASTER, _base(membros=membros)).post(MEMBROS_URL, json={"user_id": "u-bea", "perfil": "utilizador"})
    assert (r.status_code, r.json()) == (409, JA_MEMBRO)


def test_criar_quem_ja_e_membro_da_409_mesmo_sem_o_indice_unico(sessao):
    """Se o arranque não conseguiu criar os índices (o CRM arranca sem eles),
    a verificação antes de gravar continua a recusar o repetido."""
    base = BaseFalsa({
        "crm_membros": ColeccaoFalsa(MEMBROS, unicos=("id",)),
        "users": list(USERS),
    })
    r = sessao(ADMIN_MASTER, base).post(MEMBROS_URL, json={"user_id": "u-ze", "perfil": "admin"})
    assert (r.status_code, r.json()) == (409, JA_MEMBRO)
    assert [d["user_id"] for d in base.crm_membros.docs].count("u-ze") == 1


def test_criar_quando_o_insert_da_chave_repetida_e_409_ja_membro(sessao):
    """A corrida: outro admin juntou a mesma conta entre a verificação e o
    insert; o índice único de `user_id` recusa-o."""
    base = BaseFalsa({
        "crm_membros": ColeccaoFalsa(MEMBROS, falhar={"insert_one": DuplicateKeyError("E11000 user_id", 11000)}),
        "users": list(USERS),
    })
    r = sessao(ADMIN_MASTER, base).post(MEMBROS_URL, json={"user_id": "u-bea", "perfil": "utilizador"})
    assert (r.status_code, r.json()) == (409, JA_MEMBRO)


def test_dois_admins_a_juntar_a_mesma_conta_ao_mesmo_tempo_so_um_grava(monkeypatch):
    """A corrida a sério: as duas verificações passam antes de qualquer insert
    (o duplo cede o controlo em cada operação) e é o índice único que decide."""
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    monkeypatch.setattr(relogio, "agora", lambda: AGORA)
    base = _base()
    monkeypatch.setattr(crm.db, "obter_db", lambda: base)
    admin = {**ADMIN_MASTER, "crm_perfil": "admin", "crm_admin_master": True}
    ana = {**ANA_ADMIN_DO_CRM, "crm_perfil": "admin", "crm_admin_master": False}

    async def _ao_mesmo_tempo():
        return await asyncio.gather(
            rotas_membros.adicionar_membro(admin, {"user_id": "u-bea", "perfil": "utilizador"}),
            rotas_membros.adicionar_membro(ana, {"user_id": "u-bea", "perfil": "admin"}),
            return_exceptions=True,
        )

    primeiro, segundo = correr(_ao_mesmo_tempo())
    assert primeiro["user_id"] == "u-bea"
    assert isinstance(segundo, HTTPException)
    assert (segundo.status_code, segundo.detail) == (409, JA_MEMBRO["detail"])
    assert len(base.crm_membros.chamadas("find_one")) == 2, "as duas verificações correram antes dos inserts"
    assert [d["user_id"] for d in base.crm_membros.docs].count("u-bea") == 1


def test_criar_quando_a_base_falha_e_um_erro(sessao):
    base = BaseFalsa({
        "crm_membros": ColeccaoFalsa(MEMBROS, unicos=("id", "user_id"), falhar={"insert_one": RuntimeError("base em baixo")}),
        "users": list(USERS),
    })
    r = sessao(ADMIN_MASTER, base, levantar=False).post(MEMBROS_URL, json={"user_id": "u-bea", "perfil": "utilizador"})
    assert r.status_code == 500


@pytest.mark.parametrize(
    "bruto", [b"[]", b'"u-bea"', b"null", b"{partido"], ids=["lista", "texto", "null", "partido"]
)
def test_criar_com_um_corpo_que_nao_e_um_objeto_json_da_400(sessao, bruto):
    cliente = sessao(ADMIN_MASTER)
    r = cliente.post(MEMBROS_URL, content=bruto, headers=JSON)
    assert (r.status_code, r.json()) == (400, JSON_INVALIDO)
    assert _escritas(cliente.base) == []


# --- PATCH /membros/{membro_id} ---------------------------------------------------------------


def test_mudar_o_perfil_da_200_com_a_linha_e_so_muda_o_perfil(sessao):
    cliente = sessao(ADMIN_MASTER)
    antes = _guardado(cliente.base, "m-ze")
    r = cliente.patch(MEMBROS_URL + "/m-ze", json={"perfil": "admin"})
    assert r.status_code == 200
    assert r.json() == {**LINHA_ZE, "perfil": "admin"}
    assert _guardado(cliente.base, "m-ze") == {**antes, "perfil": "admin"}


def test_mudar_escreve_so_o_perfil_e_ignora_as_outras_chaves(sessao):
    cliente = sessao(ADMIN_MASTER)
    r = cliente.patch(MEMBROS_URL + "/m-ze", json={
        "perfil": "motorista", "user_id": "u-bea", "id": "m-outro", "criado_por": "u-eli", "criado_em": "x",
    })
    assert r.status_code == 200
    assert r.json() == {**LINHA_ZE, "perfil": "motorista"}
    assert cliente.base.crm_membros.chamadas("update_one") == [
        ("update_one", {"id": "m-ze"}, {"$set": {"perfil": "motorista"}}, False)
    ]


def test_mudar_para_o_mesmo_perfil_da_200_e_nada_muda(sessao):
    cliente = sessao(ADMIN_MASTER)
    antes = cliente.base.crm_membros.sem_id()
    r = cliente.patch(MEMBROS_URL + "/m-ze", json={"perfil": "utilizador"})
    assert (r.status_code, r.json()) == (200, LINHA_ZE)
    assert cliente.base.crm_membros.sem_id() == antes


@pytest.mark.parametrize(
    "corpo",
    [{}, {"perfil": "chefe"}, {"perfil": "Admin"}, {"perfil": None}, {"perfil": ["admin"]}, {"perfil": True}],
    ids=["perfil em falta", "desconhecido", "com maiuscula", "nulo", "lista", "verdadeiro"],
)
def test_mudar_para_um_perfil_invalido_da_422_e_nada_se_grava(sessao, corpo):
    cliente = sessao(ADMIN_MASTER)
    antes = cliente.base.crm_membros.sem_id()
    r = cliente.patch(MEMBROS_URL + "/m-ze", json=corpo)
    assert r.status_code == 422
    assert r.json() == {"detail": {
        "codigo": "validacao", "mensagem": "Verifique os campos assinalados.", "campos": {"perfil": MENSAGEM_PERFIL},
    }}
    assert cliente.base.crm_membros.sem_id() == antes
    assert _escritas(cliente.base) == []


def test_mudar_um_membro_que_nao_existe_da_404(sessao):
    cliente = sessao(ADMIN_MASTER)
    r = cliente.patch(MEMBROS_URL + "/m-nao-existe", json={"perfil": "admin"})
    assert (r.status_code, r.json()) == (404, NAO_ENCONTRADO)
    assert _escritas(cliente.base) == []


def test_mudar_valida_o_corpo_antes_de_procurar_o_membro(sessao):
    """Como o autónomo (UtilizadoresControlador::alterar): 422 antes do 404."""
    cliente = sessao(ADMIN_MASTER)
    r = cliente.patch(MEMBROS_URL + "/m-nao-existe", json={"perfil": "chefe"})
    assert r.status_code == 422
    # O admin master nem lê crm_membros para entrar: qualquer find_one aqui
    # seria a procura do membro, que só vem depois de validar o corpo.
    assert cliente.base.crm_membros.chamadas("find_one") == []


class _RetiradoDepoisDeLer(ColeccaoFalsa):
    """Outro admin retira o membro logo a seguir a esta leitura."""

    async def find_one(self, filtro=None, projecao=None, *, projection=None):
        doc = await super().find_one(filtro, projecao, projection=projection)
        self.docs.clear()
        return doc


def test_mudar_um_membro_retirado_entretanto_da_404_e_nao_o_ressuscita(sessao):
    base = BaseFalsa({
        "crm_membros": _RetiradoDepoisDeLer(MEMBROS, unicos=("id", "user_id")),
        "users": list(USERS),
    })
    r = sessao(ADMIN_MASTER, base).patch(MEMBROS_URL + "/m-ze", json={"perfil": "admin"})
    assert (r.status_code, r.json()) == (404, NAO_ENCONTRADO)
    assert base.crm_membros.docs == []


def test_mudar_um_membro_com_a_conta_apagada_da_200_como_na_lista(sessao):
    r = sessao(ADMIN_MASTER).patch(MEMBROS_URL + "/m-apagada", json={"perfil": "motorista"})
    assert r.status_code == 200
    assert r.json() == {
        "id": "m-apagada", "user_id": "u-apagada", "nome": None, "email": None, "tipo_conta": None,
        "perfil": "motorista", "admin_master": False, "conta_existe": False, "criado_em": "2026-09-30T09:00:00Z",
    }


def test_mudar_uma_linha_sem_user_id_nao_a_junta_a_uma_conta_sem_id(sessao):
    """Uma linha estragada, sem `user_id`: não se pergunta `{"id": None}` às
    contas, que apanhava a conta sem `id`."""
    membros = MEMBROS + [{"id": "m-sem-conta", "perfil": "utilizador", "criado_em": "2026-10-05T09:00:00Z"}]
    users = USERS + [{"email": "sem.id@example.com", "name": "Sem Id", "role": "colaborador"}]
    cliente = sessao(ADMIN_MASTER, _base(membros=membros, users=users))
    r = cliente.patch(MEMBROS_URL + "/m-sem-conta", json={"perfil": "motorista"})
    assert r.status_code == 200
    assert r.json() == {
        "id": "m-sem-conta", "user_id": None, "nome": None, "email": None, "tipo_conta": None,
        "perfil": "motorista", "admin_master": False, "conta_existe": False, "criado_em": "2026-10-05T09:00:00Z",
    }
    assert cliente.base.users.chamadas("find_one") == []


def test_mudar_corrige_uma_linha_com_perfil_desconhecido_e_a_pessoa_passa_a_entrar(sessao):
    membros = MEMBROS + [{"id": "m-bea", "user_id": "u-bea", "perfil": "gestor", "criado_em": "2026-10-04T09:00:00Z"}]
    base = sessao(ADMIN_MASTER, _base(membros=membros)).base
    assert sessao(BEA_NAO_MEMBRO, base).get("/api/crm/eu").json()["membro"] is False
    r = sessao(ADMIN_MASTER, base).patch(MEMBROS_URL + "/m-bea", json={"perfil": "utilizador"})
    assert r.status_code == 200
    assert r.json()["perfil"] == "utilizador"
    assert sessao(BEA_NAO_MEMBRO, base).get("/api/crm/eu").json() == {
        "membro": True, "perfil": "utilizador", "admin_master": False,
    }


def test_mudar_uma_linha_antiga_do_admin_master_da_409_admin_master(sessao):
    """O perfil do admin master não se muda: é sempre admin, sem linha."""
    membros = MEMBROS + [{"id": "m-antiga", "user_id": "u-admin", "perfil": "utilizador"}]
    cliente = sessao(ANA_ADMIN_DO_CRM, _base(membros=membros))
    r = cliente.patch(MEMBROS_URL + "/m-antiga", json={"perfil": "admin"})
    assert (r.status_code, r.json()) == (409, ADMIN_MASTER_409)
    assert cliente.base.crm_membros.chamadas("update_one") == []


def test_despromovido_perde_o_acesso_de_admin_logo_no_pedido_seguinte(sessao):
    base = sessao(ADMIN_MASTER).base
    assert sessao(ANA_ADMIN_DO_CRM, base).get(MEMBROS_URL).status_code == 200
    assert sessao(ADMIN_MASTER, base).patch(MEMBROS_URL + "/m-ana", json={"perfil": "utilizador"}).status_code == 200
    r = sessao(ANA_ADMIN_DO_CRM, base).get(MEMBROS_URL)
    assert (r.status_code, r.json()) == (403, SEM_PERMISSAO)


def test_um_admin_pode_mudar_o_proprio_perfil_o_admin_master_continua(sessao):
    """Não há regra do "último admin": o admin master é sempre admin."""
    cliente = sessao(ANA_ADMIN_DO_CRM)
    assert cliente.patch(MEMBROS_URL + "/m-ana", json={"perfil": "utilizador"}).status_code == 200
    assert cliente.get(MEMBROS_URL).status_code == 403
    assert sessao(ADMIN_MASTER, cliente.base).get(MEMBROS_URL).status_code == 200


@pytest.mark.parametrize("bruto", [b"[]", b"null", b"{partido"], ids=["lista", "null", "partido"])
def test_mudar_com_um_corpo_que_nao_e_um_objeto_json_da_400(sessao, bruto):
    cliente = sessao(ADMIN_MASTER)
    r = cliente.patch(MEMBROS_URL + "/m-ze", content=bruto, headers=JSON)
    assert (r.status_code, r.json()) == (400, JSON_INVALIDO)
    assert _escritas(cliente.base) == []


# --- DELETE /membros/{membro_id} --------------------------------------------------------------


def test_retirar_da_200_retirado_e_depois_404(sessao):
    cliente = sessao(ADMIN_MASTER)
    r = cliente.delete(MEMBROS_URL + "/m-ze")
    assert (r.status_code, r.json()) == (200, {"retirado": True})
    assert _guardado(cliente.base, "m-ze") is None
    assert cliente.base.crm_membros.chamadas("delete_one") == [("delete_one", {"id": "m-ze"})]
    r = cliente.delete(MEMBROS_URL + "/m-ze")
    assert (r.status_code, r.json()) == (404, NAO_ENCONTRADO)


def test_retirar_so_tira_esse_membro(sessao):
    cliente = sessao(ADMIN_MASTER)
    assert cliente.delete(MEMBROS_URL + "/m-alv").status_code == 200
    assert [d["id"] for d in cliente.base.crm_membros.sem_id()] == ["m-ana", "m-ze", "m-apagada"]


def test_retirar_um_membro_que_nao_existe_da_404(sessao):
    cliente = sessao(ADMIN_MASTER)
    antes = cliente.base.crm_membros.sem_id()
    r = cliente.delete(MEMBROS_URL + "/m-nao-existe")
    assert (r.status_code, r.json()) == (404, NAO_ENCONTRADO)
    assert cliente.base.crm_membros.sem_id() == antes


def test_retirado_perde_o_acesso_e_volta_aos_candidatos(sessao):
    base = sessao(ADMIN_MASTER).base
    assert sessao(ZE_UTILIZADOR, base).get("/api/crm/eu").json()["membro"] is True
    assert sessao(ADMIN_MASTER, base).delete(MEMBROS_URL + "/m-ze").status_code == 200
    assert sessao(ZE_UTILIZADOR, base).get("/api/crm/eu").json() == {
        "membro": False, "perfil": None, "admin_master": False,
    }
    candidatos = sessao(ADMIN_MASTER, base).get(MEMBROS_URL + "/candidatos").json()
    assert "u-ze" in [c["id"] for c in candidatos]


def test_retirar_um_membro_com_a_conta_apagada(sessao):
    cliente = sessao(ADMIN_MASTER)
    assert cliente.delete(MEMBROS_URL + "/m-apagada").status_code == 200
    assert "m-apagada" not in [linha["id"] for linha in cliente.get(MEMBROS_URL).json()]


def test_retirar_uma_linha_antiga_do_admin_master_limpa_a_e_ele_continua_admin(sessao):
    membros = MEMBROS + [{"id": "m-antiga", "user_id": "u-admin", "perfil": "utilizador"}]
    cliente = sessao(ADMIN_MASTER, _base(membros=membros))
    assert cliente.delete(MEMBROS_URL + "/m-antiga").status_code == 200
    assert _guardado(cliente.base, "m-antiga") is None
    assert cliente.get("/api/crm/eu").json() == {"membro": True, "perfil": "admin", "admin_master": True}


def test_um_admin_pode_retirar_se_a_si_proprio(sessao):
    cliente = sessao(ANA_ADMIN_DO_CRM)
    assert cliente.delete(MEMBROS_URL + "/m-ana").status_code == 200
    assert (cliente.get(MEMBROS_URL).status_code, cliente.get(MEMBROS_URL).json()) == (403, SEM_ACESSO)


def test_retirar_quando_a_base_falha_e_um_erro(sessao):
    base = BaseFalsa({
        "crm_membros": ColeccaoFalsa(MEMBROS, falhar={"delete_one": RuntimeError("base em baixo")}),
        "users": list(USERS),
    })
    assert sessao(ADMIN_MASTER, base, levantar=False).delete(MEMBROS_URL + "/m-ze").status_code == 500


# --- De ponta a ponta: a sessão verdadeira do portal ---------------------------------------

SEGREDO = "segredo-de-teste-crm-membros-escrever"
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
    base = _base()
    monkeypatch.setattr(faturacao.auth, "obter_db", lambda: base)
    monkeypatch.setattr(crm.db, "obter_db", lambda: base)
    app = FastAPI()
    app.include_router(crm.router)
    cliente = TestClient(app)
    cliente.base = base
    return cliente


@pytest.mark.parametrize("metodo, url, _corpo", COM_CORPO, ids=IDS_COM_CORPO)
def test_sem_cabecalho_e_com_json_partido_da_o_403_herdado_e_nunca_400(portal, metodo, url, _corpo):
    """Correções do plano, linha "T1.3 / T2.15"."""
    r = portal.request(metodo, url, content=b"[", headers=JSON)
    assert (r.status_code, r.json()) == (403, {"detail": "Not authenticated"})
    assert portal.base.users.registo == []
    assert portal.base.crm_membros.registo == []


def test_retirar_sem_cabecalho_da_o_403_herdado(portal):
    r = portal.delete(MEMBROS_URL + "/m-ze")
    assert (r.status_code, r.json()) == (403, {"detail": "Not authenticated"})
    assert _guardado(portal.base, "m-ze") is not None


@pytest.mark.parametrize("metodo, url, corpo", ESCRITAS, ids=IDS_ESCRITAS)
def test_uma_conta_apagada_da_401_sessao_terminada(portal, metodo, url, corpo):
    r = _pedir(portal, metodo, url, corpo, headers=_cabecalho("u-apagada"))
    assert (r.status_code, r.json()) == (401, {"detail": "Sessão terminada"})
    assert portal.base.crm_membros.registo == []


def test_um_token_com_o_email_do_admin_master_nao_chega_para_escrever(portal):
    r = portal.post(MEMBROS_URL, json={"user_id": "u-eli", "perfil": "admin"},
                    headers=_cabecalho("u-bea", email=ADMIN_LOCAL, role="admin"))
    assert (r.status_code, r.json()) == (403, SEM_ACESSO)
    assert _escritas(portal.base) == []


def test_de_ponta_a_ponta_juntar_mudar_e_retirar_a_bea(portal):
    admin = _cabecalho("u-admin", email=ADMIN_LOCAL, role="admin")
    bea = _cabecalho("u-bea")
    assert portal.get("/api/crm/eu", headers=bea).json()["membro"] is False

    r = portal.post(MEMBROS_URL, json={"user_id": "u-bea", "perfil": "utilizador"}, headers=admin)
    assert r.status_code == 201
    membro_id = r.json()["id"]
    assert _guardado(portal.base, membro_id)["criado_por"] == "u-admin"
    assert portal.get("/api/crm/eu", headers=bea).json() == {"membro": True, "perfil": "utilizador", "admin_master": False}
    assert portal.get(MEMBROS_URL, headers=bea).json() == SEM_PERMISSAO

    assert portal.patch(f"{MEMBROS_URL}/{membro_id}", json={"perfil": "admin"}, headers=admin).status_code == 200
    assert portal.get(MEMBROS_URL, headers=bea).status_code == 200

    assert portal.delete(f"{MEMBROS_URL}/{membro_id}", headers=admin).json() == {"retirado": True}
    assert portal.get("/api/crm/eu", headers=bea).json()["membro"] is False
    r = portal.get(MEMBROS_URL, headers=bea)
    assert (r.status_code, r.json()) == (403, SEM_ACESSO)
