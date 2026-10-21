"""Seed local do CRM: a guarda (só MongoDB local e base *_local), as contas de demonstração
(T0.7) e as regiões e lojas de demonstração (T2.18).

O seed usa o pymongo (síncrono), por isso este ficheiro tem o seu próprio duplo síncrono da
base (o duplos.py do CRM, assíncrono, só nasce na T1.2). Nenhum teste liga a um MongoDB: o
seed das lojas numa base verdadeira (índices, validador do Mongo) está no ensaio
tests/crm/test_mongo_local.py.

As regiões e as lojas são as do src/Cli/DadosDemo.php do CRM autónomo, e os cenários os do
tests/Integration/Cli/SeedDemoTest.php (nomes dos testes em pt-PT, pela mesma ordem). O
autónomo gravava numa transação ("ou ficam todos os dados, ou nada muda"); o MongoDB local
não tem transações (plano §1), por isso o seed guarda uma cópia do que vai apagar e, se uma
escrita falhar, repõe-na.
"""
import copy
import math
import os
import re
import stat
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import bcrypt
import pytest
from pymongo import MongoClient
from pymongo.errors import AutoReconnect, BulkWriteError, ServerSelectionTimeoutError, WriteError

import seed_crm_local
from crm import formatar
from crm.db import COLECOES
from crm.dominio import validador_loja
from crm.dominio.geo import encontrar_duplicados

from .formatos import instantes_fora_do_formato

MENSAGEM_RECUSA = (
    "Recusado: o seed só corre num MongoDB local (mongodb://127.0.0.1) e numa base *_local."
)
AGORA = datetime(2026, 10, 10, 9, 0, 0, 123456, tzinfo=timezone.utc)
CAMPOS_CONTA = {
    "id", "email", "password", "name", "role", "employee_id", "must_change_password", "created_at",
}
CAMPOS_MEMBRO = {"id", "user_id", "perfil", "criado_em", "criado_por"}


# ---------------------------------------------------------------- duplos síncronos

def _corresponde(doc, filtro):
    return all(doc.get(chave) == valor for chave, valor in filtro.items())


class ColecaoFalsa:
    """Só o que o seed pode usar: insert_one, insert_many, find_one, find, update_one ($set),
    delete_many e count_documents (filtros só de igualdade; `{}` apanha tudo).

    `recusar` (documento → bool) faz de validador do Mongo: o insert_many grava pela ordem
    até ao primeiro recusado e rebenta com BulkWriteError (como um insert_many ordenado do
    pymongo); o insert_one, com WriteError. Cada escrita fica em `registo` como
    (coleção, operação), para os testes verem a ordem das escritas.
    """

    def __init__(self, nome="", registo=None):
        self.nome = nome
        self.docs = []
        self.recusar = None
        self.registo = registo if registo is not None else []

    def _escrita(self, operacao):
        self.registo.append((self.nome, operacao))

    def _recusado(self, doc):
        return self.recusar is not None and self.recusar(doc)

    def insert_one(self, doc):
        self._escrita("insert_one")
        if self._recusado(doc):
            raise WriteError("falha simulada", 121)
        self.docs.append(copy.deepcopy(doc))
        return SimpleNamespace(inserted_id=len(self.docs))

    def insert_many(self, docs):
        self._escrita("insert_many")
        docs = list(docs)
        if not docs:
            raise TypeError("documents must be a non-empty list")  # como o pymongo
        for posicao, doc in enumerate(docs):
            if self._recusado(doc):
                raise BulkWriteError({
                    "writeErrors": [{"index": posicao, "code": 121, "errmsg": "falha simulada"}],
                    "writeConcernErrors": [], "nInserted": posicao, "nUpserted": 0,
                    "nMatched": 0, "nModified": 0, "nRemoved": 0, "upserted": [],
                })
            self.docs.append(copy.deepcopy(doc))
        return SimpleNamespace(inserted_ids=list(range(len(docs))))

    def find_one(self, filtro, projecao=None):
        for doc in self.docs:
            if _corresponde(doc, filtro):
                return copy.deepcopy(doc)
        return None

    def find(self, filtro=None, projecao=None):
        return [copy.deepcopy(doc) for doc in self.docs if _corresponde(doc, filtro or {})]

    def update_one(self, filtro, alteracao):
        self._escrita("update_one")
        assert set(alteracao) == {"$set"}, f"operador não previsto no duplo: {alteracao}"
        for doc in self.docs:
            if _corresponde(doc, filtro):
                doc.update(copy.deepcopy(alteracao["$set"]))
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)

    def delete_many(self, filtro):
        self._escrita("delete_many")
        ficam = [doc for doc in self.docs if not _corresponde(doc, filtro)]
        apagados = len(self.docs) - len(ficam)
        self.docs = ficam
        return SimpleNamespace(deleted_count=apagados)

    def count_documents(self, filtro):
        return sum(1 for doc in self.docs if _corresponde(doc, filtro))


class BaseFalsa(dict):
    def __init__(self):
        super().__init__()
        self.registo = []

    def __missing__(self, nome):
        self[nome] = ColecaoFalsa(nome, self.registo)
        return self[nome]


def _estado(db):
    """Uma cópia de tudo o que está na base falsa: {coleção: [documentos]}. As coleções
    vazias não contam (o duplo cria-as só por serem lidas; o Mongo não)."""
    return {nome: copy.deepcopy(colecao.docs) for nome, colecao in db.items() if colecao.docs}


def _gerador(prefixo="Palavra"):
    contador = iter(range(1, 1000))
    chamadas = []

    def gerar():
        palavra = f"{prefixo}{next(contador):04d}xyz"
        chamadas.append(palavra)
        return palavra

    gerar.chamadas = chamadas
    return gerar


def _confere(palavra, cifra):
    return bcrypt.checkpw(palavra.encode("utf-8"), cifra.encode("utf-8"))


def _conta(db, email):
    return db["users"].find_one({"email": email})


# ---------------------------------------------------------------- guarda: URI

@pytest.mark.parametrize("uri", [
    "mongodb://127.0.0.1:27017",
    "mongodb://localhost",
    "mongodb://[::1]:27017/x",
])
def test_uri_local_e_aceite(uri):
    assert seed_crm_local.uri_e_local(uri) is True


@pytest.mark.parametrize("uri", [
    "mongodb+srv://cluster0.abcd.mongodb.net",
    "mongodb://u:p@cluster0.abcd.mongodb.net",
    "mongodb://127.0.0.1.evil.com",
    "mongodb://127.0.0.1@evil.com",           # o anfitrião é o que vem depois do último @
    "mongodb://127.0.0.1,atlas.mongodb.net",  # todos os anfitriões têm de ser locais
    "mongodb://127.0.0.1:27017,localhost:27018",  # uma só máquina (revisão da F2: directConnection)
    "mongodb://evil.com/?h=127.0.0.1",
    "",
    None,
])
def test_uri_que_nao_e_local_e_recusado(uri):
    assert seed_crm_local.uri_e_local(uri) is False


@pytest.mark.parametrize("uri", [
    "mongodb+srv://cluster0.abcd.mongodb.net",  # interpretar faria uma consulta DNS
    " mongodb://127.0.0.1",
    "MONGODB://127.0.0.1",
    "",
    None,
])
def test_o_que_nao_comeca_por_mongodb_e_recusado_sem_interpretar_o_uri(monkeypatch, uri):
    chamadas = []

    def espiao(*args, **kwargs):
        chamadas.append(args)
        raise AssertionError("parse_uri não devia ser chamado")

    monkeypatch.setattr(seed_crm_local.uri_parser, "parse_uri", espiao)
    assert seed_crm_local.uri_e_local(uri) is False
    assert chamadas == []


def test_erro_ao_interpretar_o_uri_conta_como_nao_local(monkeypatch):
    def rebenta(*args, **kwargs):
        raise ValueError("URI estranho")

    monkeypatch.setattr(seed_crm_local.uri_parser, "parse_uri", rebenta)
    assert seed_crm_local.uri_e_local("mongodb://127.0.0.1:27017") is False


# ---------------------------------------------------------------- guarda: base

@pytest.mark.parametrize("nome", ["lisbonb_crm_local", "x_local"])
def test_base_local_e_aceite(nome):
    assert seed_crm_local.bd_e_local(nome) is True


@pytest.mark.parametrize("nome", ["rh", "lisbonb", "", None, "lisbonb_crm_teste", "_local", "lisbonb_local_x"])
def test_base_que_nao_acaba_em_local_e_recusada(nome):
    assert seed_crm_local.bd_e_local(nome) is False


# ---------------------------------------------------------------- guarda: ambiente

def test_ambiente_local_passa_e_devolve_uri_e_base():
    env = {"MONGO_URL": "mongodb://127.0.0.1:27017", "DB_NAME": "lisbonb_crm_local", "JWT_SECRET": "x"}
    assert seed_crm_local.verificar_ambiente(env) == ("mongodb://127.0.0.1:27017", "lisbonb_crm_local")


@pytest.mark.parametrize("env", [
    {"MONGO_URL": "mongodb+srv://cluster0.abcd.mongodb.net", "DB_NAME": "lisbonb_crm_local"},
    {"MONGO_URL": "mongodb://u:p@cluster0.abcd.mongodb.net", "DB_NAME": "lisbonb_crm_local"},
    {"MONGO_URL": "mongodb://127.0.0.1:27017", "DB_NAME": "rh"},
    {"MONGO_URL": "mongodb://127.0.0.1:27017", "DB_NAME": "lisbonb"},
    {"MONGO_URL": "mongodb://127.0.0.1:27017"},
    {"DB_NAME": "lisbonb_crm_local"},
    {"MONGO_URL": None, "DB_NAME": None},
    {},
])
def test_ambiente_que_nao_e_local_e_recusado_com_a_mensagem(env):
    with pytest.raises(SystemExit) as erro:
        seed_crm_local.verificar_ambiente(env)
    assert erro.value.code == MENSAGEM_RECUSA


# ---------------------------------------------------------------- CLI: nunca liga antes da guarda

def _cliente_falso(registo, base=None):
    class ClienteFalso:
        def __init__(self, uri, **opcoes):
            registo.append((uri, opcoes))
            self.base = base if base is not None else BaseFalsa()
            self.nomes = []
            self.fechado = False
            registo_clientes.append(self)

        def __getitem__(self, nome):
            self.nomes.append(nome)
            return self.base

        def close(self):
            self.fechado = True

    registo_clientes = []
    ClienteFalso.clientes = registo_clientes
    return ClienteFalso


def _ficheiro_env(tmp_path, uri, nome):
    caminho = tmp_path / ".env.local"
    caminho.write_text(f"MONGO_URL={uri}\nDB_NAME={nome}\nJWT_SECRET=nao-interessa\n", encoding="utf-8")
    return caminho


@pytest.mark.parametrize("uri,nome", [
    ("mongodb+srv://cluster0.abcd.mongodb.net", "lisbonb_crm_local"),
    ("mongodb://u:p@cluster0.abcd.mongodb.net", "lisbonb_crm_local"),
    ("mongodb://127.0.0.1:27017", "lisbonb"),
    ("mongodb://127.0.0.1:27017,localhost:27018", "lisbonb_crm_local"),
])
def test_cli_recusa_antes_de_criar_o_cliente_mongo(tmp_path, monkeypatch, uri, nome):
    criados = []
    monkeypatch.setattr(seed_crm_local, "MongoClient", _cliente_falso(criados))
    monkeypatch.setattr(seed_crm_local, "FICHEIRO_CREDENCIAIS", tmp_path / "cfg" / "credenciais.txt")

    with pytest.raises(SystemExit) as erro:
        seed_crm_local.main(["--env-file", str(_ficheiro_env(tmp_path, uri, nome))])

    assert erro.value.code == MENSAGEM_RECUSA
    assert criados == []
    assert not (tmp_path / "cfg").exists()


@pytest.mark.parametrize("uri", [
    "mongodb://127.0.0.1:27017",
    "mongodb://127.0.0.1:27017/?directConnection=false",
    "mongodb://localhost/?replicaSet=rs0",
], ids=["sem opções", "directConnection=false no URI", "replicaSet no URI"])
def test_o_cliente_do_seed_fala_so_com_a_maquina_do_uri(uri):
    """Revisão da F2: sem `directConnection=True`, o PyMongo 4 descobre o
    conjunto de réplicas a partir do nó local e manda as escritas para o
    primário que ele anunciar, mesmo noutra máquina. Com as opções do seed, a
    topologia é sempre `Single` (só a máquina do URI), também quando o URI
    pede o contrário: as opções do MongoClient ganham às do URI. Não liga a
    nada (`connect=False`)."""
    sem_as_opcoes = MongoClient(uri, connect=False)
    com_as_opcoes = MongoClient(uri, connect=False, **seed_crm_local.OPCOES_CLIENTE)
    try:
        assert sem_as_opcoes.topology_description.topology_type_name != "Single"
        assert com_as_opcoes.topology_description.topology_type_name == "Single"
    finally:
        sem_as_opcoes.close()
        com_as_opcoes.close()


def test_cli_recusa_se_o_ficheiro_de_ambiente_nao_existe(tmp_path, monkeypatch):
    criados = []
    monkeypatch.setattr(seed_crm_local, "MongoClient", _cliente_falso(criados))

    with pytest.raises(SystemExit) as erro:
        seed_crm_local.main(["--env-file", str(tmp_path / "nao-existe.env")])

    assert str(erro.value.code).startswith("Recusado: o ficheiro de ambiente não existe")
    assert criados == []


def test_cli_le_o_ficheiro_sem_mexer_no_ambiente_do_processo(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("MONGO_URL", raising=False)
    monkeypatch.delenv("DB_NAME", raising=False)
    criados = []
    base = BaseFalsa()
    cliente = _cliente_falso(criados, base)
    credenciais = tmp_path / "cfg" / "credenciais.txt"
    monkeypatch.setattr(seed_crm_local, "MongoClient", cliente)
    monkeypatch.setattr(seed_crm_local, "FICHEIRO_CREDENCIAIS", credenciais)

    saida = seed_crm_local.main(
        ["--env-file", str(_ficheiro_env(tmp_path, "mongodb://127.0.0.1:27017", "lisbonb_crm_local"))]
    )

    assert saida == 0
    assert "MONGO_URL" not in os.environ and "DB_NAME" not in os.environ
    assert criados == [("mongodb://127.0.0.1:27017", {"directConnection": True, "serverSelectionTimeoutMS": 3000})]
    assert cliente.clientes[0].nomes == ["lisbonb_crm_local"]
    assert cliente.clientes[0].fechado is True
    assert base["users"].count_documents({}) == 4
    assert base["crm_membros"].count_documents({}) == 3
    assert base["crm_regioes"].count_documents({}) == 4
    assert base["crm_lojas"].count_documents({}) == 24

    # Escreve as palavras-passe só no ficheiro (modo 600) e só mostra o caminho.
    assert stat.S_IMODE(credenciais.stat().st_mode) == 0o600
    assert stat.S_IMODE(credenciais.parent.stat().st_mode) == 0o700
    guardadas = seed_crm_local.ler_credenciais(credenciais)
    assert sorted(guardadas) == sorted(c["email"] for c in seed_crm_local.contas_demo())
    for email, palavra in guardadas.items():
        assert _confere(palavra, _conta(base, email)["password"])
    escrito = capsys.readouterr()
    assert escrito.out.splitlines() == [
        f"Palavras-passe das contas de demonstração (4 novas): {credenciais}",
        CRIADAS,
    ]
    assert escrito.err == ""
    for palavra in guardadas.values():
        assert palavra not in escrito.out and palavra not in escrito.err


def test_cli_sem_resposta_do_mongo_sai_com_mensagem_e_fecha_o_cliente(tmp_path, monkeypatch):
    class ColecaoSemServidor(ColecaoFalsa):
        def _sem_servidor(self, *args, **kwargs):
            raise ServerSelectionTimeoutError("127.0.0.1:27017: Connection refused")

        find_one = find = count_documents = _sem_servidor

    class BaseSemServidor(dict):
        def __missing__(self, nome):
            self[nome] = ColecaoSemServidor()
            return self[nome]

    criados = []
    cliente = _cliente_falso(criados, BaseSemServidor())
    monkeypatch.setattr(seed_crm_local, "MongoClient", cliente)
    monkeypatch.setattr(seed_crm_local, "FICHEIRO_CREDENCIAIS", tmp_path / "cfg" / "credenciais.txt")

    with pytest.raises(SystemExit) as erro:
        seed_crm_local.main(
            ["--env-file", str(_ficheiro_env(tmp_path, "mongodb://127.0.0.1:27017", "lisbonb_crm_local"))]
        )

    assert str(erro.value.code).startswith("Erro: o MongoDB local não respondeu")
    assert cliente.clientes[0].fechado is True
    assert not (tmp_path / "cfg").exists()


# ---------------------------------------------------------------- contas de demonstração

def test_contas_demo_sao_as_quatro_previstas():
    contas = seed_crm_local.contas_demo()
    assert [(c["email"], c["role"], c["perfil"]) for c in contas] == [
        ("gestor.demo@example.com", "gerente", None),
        ("escritorio.demo@example.com", "gerente", "utilizador"),
        ("colaborador.demo@example.com", "colaborador", "utilizador"),
        ("motorista.demo@example.com", "colaborador", "motorista"),
    ]
    assert all("(demo)" in c["name"] for c in contas)


def test_colecao_dos_membros_tem_o_nome_do_crm():
    assert seed_crm_local.COLECAO_MEMBROS == "crm_membros"


def test_aplicar_contas_cria_as_contas_e_os_membros():
    db = BaseFalsa()
    gerar = _gerador()

    palavras = seed_crm_local.aplicar_contas(db, AGORA, gerar)

    contas = seed_crm_local.contas_demo()
    assert db["users"].count_documents({}) == 4
    assert db["crm_membros"].count_documents({}) == 3
    assert sorted(palavras) == sorted(c["email"] for c in contas)
    assert sorted(palavras.values()) == sorted(gerar.chamadas)

    for esperada in contas:
        conta = _conta(db, esperada["email"])
        assert set(conta) == CAMPOS_CONTA
        assert uuid.UUID(conta["id"]).version == 4
        assert conta["name"] == esperada["name"]
        assert conta["role"] == esperada["role"]
        assert conta["employee_id"] is None
        assert conta["must_change_password"] is False
        assert conta["created_at"] == "2026-10-10T09:00:00.123456+00:00"
        assert conta["password"].startswith("$2")
        assert _confere(palavras[esperada["email"]], conta["password"])

        membro = db["crm_membros"].find_one({"user_id": conta["id"]})
        if esperada["perfil"] is None:
            assert membro is None
            continue
        assert set(membro) == CAMPOS_MEMBRO
        assert uuid.UUID(membro["id"]).version == 4
        assert membro["perfil"] == esperada["perfil"]
        assert membro["criado_em"] == "2026-10-10T09:00:00Z"
        assert membro["criado_por"] == "seed-local"


def test_aplicar_contas_segunda_vez_nao_duplica_nem_muda_palavras_passe():
    db = BaseFalsa()
    seed_crm_local.aplicar_contas(db, AGORA, _gerador("Primeira"))
    antes_contas = copy.deepcopy(db["users"].docs)
    antes_membros = copy.deepcopy(db["crm_membros"].docs)
    gerar = _gerador("Segunda")

    palavras = seed_crm_local.aplicar_contas(db, AGORA, gerar)

    assert palavras == {}
    assert gerar.chamadas == []
    assert db["users"].docs == antes_contas
    assert db["crm_membros"].docs == antes_membros


def test_aplicar_contas_completa_o_que_falta_e_nao_toca_noutras_contas():
    db = BaseFalsa()
    admin = {"id": "admin-1", "email": "admin.local@example.com", "password": "cifra-do-admin",
             "name": "Administrador Principal", "role": "admin"}
    escritorio = {"id": "u-existente", "email": "escritorio.demo@example.com", "password": "cifra-antiga",
                  "name": "Escritório (demo)", "role": "gerente"}
    db["users"].insert_one(admin)
    db["users"].insert_one(escritorio)
    gerar = _gerador()

    palavras = seed_crm_local.aplicar_contas(db, AGORA, gerar)

    assert db["users"].count_documents({}) == 5
    assert _conta(db, "admin.local@example.com") == admin
    assert _conta(db, "escritorio.demo@example.com") == escritorio
    assert "escritorio.demo@example.com" not in palavras
    assert len(palavras) == 3
    membro = db["crm_membros"].find_one({"user_id": "u-existente"})
    assert membro["perfil"] == "utilizador"
    assert db["crm_membros"].count_documents({}) == 3
    assert db["crm_membros"].find_one({"user_id": "admin-1"}) is None


def test_aplicar_contas_com_repor_gera_palavras_passe_novas_sem_duplicar():
    db = BaseFalsa()
    antigas = seed_crm_local.aplicar_contas(db, AGORA, _gerador("Antiga"))
    ids_antes = sorted(c["id"] for c in db["users"].docs)
    membros_antes = copy.deepcopy(db["crm_membros"].docs)
    gerar = _gerador("Nova")

    novas = seed_crm_local.aplicar_contas(db, AGORA, gerar, repor=True)

    assert sorted(novas) == sorted(antigas)
    assert sorted(novas.values()) == sorted(gerar.chamadas)
    assert sorted(c["id"] for c in db["users"].docs) == ids_antes
    assert db["crm_membros"].docs == membros_antes
    for email, palavra in novas.items():
        conta = _conta(db, email)
        assert _confere(palavra, conta["password"])
        assert not _confere(antigas[email], conta["password"])
        assert conta["must_change_password"] is False
        # sessões abertas antes da troca deixam de valer (mesma regra do portal)
        assert conta["password_mudada_em"] == int(AGORA.timestamp())


# ---------------------------------------------------------------- ficheiro das credenciais

def test_escrever_credenciais_junta_ao_que_ja_existe_com_modo_600(tmp_path):
    caminho = tmp_path / "cfg" / "credenciais.txt"
    seed_crm_local.escrever_credenciais(caminho, {"a.demo@example.com": "Aaa111", "b.demo@example.com": "Bbb222"})
    os.chmod(caminho, 0o644)

    seed_crm_local.escrever_credenciais(caminho, {"b.demo@example.com": "Ccc333"})

    assert seed_crm_local.ler_credenciais(caminho) == {
        "a.demo@example.com": "Aaa111",
        "b.demo@example.com": "Ccc333",
    }
    assert stat.S_IMODE(caminho.stat().st_mode) == 0o600
    assert stat.S_IMODE(caminho.parent.stat().st_mode) == 0o700
    assert [p.name for p in caminho.parent.iterdir()] == ["credenciais.txt"]


def test_ler_credenciais_sem_ficheiro_devolve_vazio(tmp_path):
    assert seed_crm_local.ler_credenciais(tmp_path / "nao-existe.txt") == {}


def test_palavra_passe_gerada_tem_16_letras_ou_algarismos():
    palavras = {seed_crm_local.gerar_palavra_passe() for _ in range(20)}
    assert len(palavras) == 20
    for palavra in palavras:
        assert len(palavra) == 16 and palavra.isascii() and palavra.isalnum()


# ================================================================ regiões e lojas de demonstração (T2.18)

CRIADAS = "Criadas: 4 regiões e 24 lojas de demonstração."
USE_REPOR = " Use --repor para apagar todas as lojas e regiões e criar os dados de demonstração de novo."
NADA_MUDOU = "Erro: os dados de demonstração não foram criados (nada mudou): "
A_MEIO = (
    "Erro: os dados de demonstração não foram criados e não foi possível repor o que havia; "
    "a base pode ter ficado a meio. Corra o seed de novo com --repor. Causa: "
)
FASES = ["amostra", "cliente", "contactada", "perdida", "potencial"]
LOJAS = COLECOES["lojas"]
REGIOES = COLECOES["regioes"]
INTERACOES = COLECOES["interacoes"]

# As 24 lojas do src/Cli/DadosDemo.php, pela ordem: nome, fase, região, localidade, lat, lng, dias na fase.
LOJAS_DO_AUTONOMO = [
    ("Mercearia da Baixa (demo)", "cliente", "Lisboa", "Lisboa", 38.710800, -9.136900, 120),
    ("Café do Bairro Alto (demo)", "amostra", "Lisboa", "Lisboa", 38.713500, -9.145800, 5),
    ("Gelataria do Rato (demo)", "contactada", "Lisboa", "Lisboa", 38.722400, -9.145200, 12),
    ("Pastelaria Saldanha (demo)", "cliente", "Lisboa", "Lisboa", 38.736900, -9.142600, 200),
    ("Minimercado Entrecampos (demo)", "potencial", "Lisboa", "Lisboa", 38.746500, -9.147900, 2),
    ("Quiosque de Alfama (demo)", "perdida", "Lisboa", "Lisboa", 38.711900, -9.130100, 45),
    ("Snack-bar de Belém (demo)", "potencial", "Lisboa", "Lisboa", 38.697200, -9.206300, 1),
    ("Mercearia dos Aliados (demo)", "cliente", "Porto", "Porto", 41.145600, -8.611000, 90),
    ("Café da Ribeira (demo)", "contactada", "Porto", "Porto", 41.142200, -8.614500, 20),
    ("Gelataria da Boavista (demo)", "amostra", "Porto", "Porto", 41.157800, -8.629600, 9),
    ("Frutaria das Antas (demo)", "potencial", "Porto", "Porto", 41.161500, -8.583600, 3),
    ("Bar da Foz (demo)", "cliente", "Porto", "Porto", 41.152000, -8.672000, 35),
    ("Cantina da Asprela (demo)", "potencial", "Porto", "Porto", 41.178200, -8.598000, 6),
    ("Frutaria do Bocage (demo)", "cliente", "Setúbal", "Setúbal", 38.524500, -8.891800, 60),
    ("Café do Bonfim (demo)", "contactada", "Setúbal", "Setúbal", 38.526900, -8.881300, 15),
    ("Gelataria da Avenida (demo)", "amostra", "Setúbal", "Setúbal", 38.530800, -8.900500, 3),
    ("Padaria de São Sebastião (demo)", "potencial", "Setúbal", "Setúbal", 38.535000, -8.876000, 4),
    ("Gelataria da Sé (demo)", "cliente", "Algarve", "Faro", 37.018000, -7.933500, 150),
    ("Mercearia do Largo (demo)", "contactada", "Algarve", "Faro", 37.019800, -7.929000, 8),
    ("Bar da Praia (demo)", "amostra", "Algarve", "Albufeira", 37.092000, -8.247000, 14),
    ("Café da Marina (demo)", "potencial", "Algarve", "Lagos", 37.104500, -8.676500, 10),
    ("Quiosque de Tavira (demo)", "perdida", "Algarve", "Tavira", 37.128500, -7.652500, 80),
    ("Café da Universidade (demo)", "contactada", None, "Coimbra", 40.207500, -8.426500, 25),
    ("Mercearia do Giraldo (demo)", "potencial", None, "Évora", 38.571500, -7.909300, 30),
]

# Os campos opcionais das lojas que os têm, como no DadosDemo.php: origem, precisão, telefone,
# pessoa de contacto, notas, as quatro horas das janelas e os dias fechada. As outras ficam com os padrões.
OPCIONAIS_DO_AUTONOMO = {
    "Mercearia da Baixa (demo)": (
        "pin_manual", None, "+351 000 000 001", "Ana",
        "Encomenda todas as semanas. Descarga pela porta lateral.", "09:00", "12:00", "14:30",
        "18:00", ["dom"],
    ),
    "Café do Bairro Alto (demo)": (
        "pin_manual", None, "+351 000 000 002", None, None, "10:00", "13:00", None, None, ["seg"],
    ),
    "Gelataria do Rato (demo)": ("pin_manual", None, None, "Rui", None, None, None, None, None, []),
    "Pastelaria Saldanha (demo)": (
        "gps", 12, "+351 000 000 003", None, None, "08:00", "11:00", None, None, ["sab", "dom"],
    ),
    "Quiosque de Alfama (demo)": (
        "pin_manual", None, None, None, "Não tem arca congeladora.", None, None, None, None, [],
    ),
    "Mercearia dos Aliados (demo)": (
        "pin_manual", None, "+351 000 000 004", "Joana", None, "09:00", "12:30", None, None,
        ["dom"],
    ),
    "Gelataria da Boavista (demo)": (
        "pin_manual", None, "+351 000 000 005", None, None, None, None, None, None, [],
    ),
    "Bar da Foz (demo)": (
        "pin_manual", None, "+351 000 000 006", None, None, "15:00", "19:00", None, None,
        ["seg", "ter"],
    ),
    "Frutaria do Bocage (demo)": (
        "gps", 25, "+351 000 000 007", None, None, "07:30", "10:30", None, None, ["dom"],
    ),
    "Gelataria da Avenida (demo)": (
        "pin_manual", None, "+351 000 000 008", None, None, None, None, None, None, [],
    ),
    "Gelataria da Sé (demo)": (
        "pin_manual", None, "+351 000 000 009", None, None, "10:00", "12:00", "16:00", "19:00",
        ["qua"],
    ),
    "Bar da Praia (demo)": (
        "pin_manual", None, "+351 000 000 010", None, None, None, None, None, None, [],
    ),
    "Quiosque de Tavira (demo)": (
        "pin_manual", None, None, None, "Fechou para obras. Voltar a tentar na primavera.", None,
        None, None, None, [],
    ),
    "Café da Universidade (demo)": (
        "pin_manual", None, "+351 000 000 011", None, None, None, None, None, None, [],
    ),
}


def _demo(agora=AGORA):
    regioes = seed_crm_local.regioes_demo()
    return regioes, seed_crm_local.lojas_demo(regioes, agora)


def _ids_das_regioes(regioes):
    return {regiao["nome"]: regiao["id"] for regiao in regioes}


def _e_uuid4(texto):
    return isinstance(texto, str) and str(uuid.UUID(texto)) == texto and uuid.UUID(texto).version == 4


def _distancia_m(a, b):
    """Haversine, escrita aqui como no SeedDemoTest (não a do domínio)."""
    lat1, lng1, lat2, lng2 = (math.radians(g) for g in (a["lat"], a["lng"], b["lat"], b["lng"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def _instante_dias_antes(agora, dias):
    """`agora` menos `dias` dias, ao segundo e em UTC, escrito com o strftime (não o relógio do CRM)."""
    return (agora - timedelta(days=dias)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _base_com_dados_verdadeiros():
    """Uma região, uma loja e uma interação que não são de demonstração, e outras coleções
    que o seed das lojas nunca toca."""
    db = BaseFalsa()
    db[REGIOES].insert_one({"id": "r-minho", "nome": "Minho", "nome_chave": "minho", "ordem": 9})
    db[LOJAS].insert_one({"id": "l-verdadeira", "nome": "Loja verdadeira", "regiao_id": "r-minho"})
    db[INTERACOES].insert_one({"id": "i-1", "loja_id": "l-verdadeira", "tipo": "mudanca_fase",
                               "resultado": "potencial→contactada"})
    db["crm_membros"].insert_one({"id": "m-1", "user_id": "u-1", "perfil": "admin"})
    db["crm_definicoes"].insert_one({"chave": "fabrica_lat", "valor": "38.7"})
    db["users"].insert_one({"id": "u-1", "email": "alguem@example.com"})
    db["fat_lojas"].insert_one({"id": "f-1", "nome": "Loja da faturação"})
    db.registo.clear()
    return db


# ---------------------------------------------------------------- os dados

def test_regioes_demo_sao_as_quatro_pela_ordem():
    regioes = seed_crm_local.regioes_demo()

    assert [(r["nome"], r["ordem"]) for r in regioes] == [
        ("Lisboa", 1), ("Porto", 2), ("Setúbal", 3), ("Algarve", 4),
    ]
    # A forma que o POST /regioes grava (T2.9): sem nome_chave, a segunda região colidia no
    # índice único (dois null).
    assert [list(r) for r in regioes] == [["id", "nome", "nome_chave", "ordem"]] * 4
    assert [r["nome_chave"] for r in regioes] == ["lisboa", "porto", "setubal", "algarve"]
    assert all(_e_uuid4(r["id"]) for r in regioes)
    assert all(isinstance(r["ordem"], int) and not isinstance(r["ordem"], bool) for r in regioes)


def test_cada_chamada_da_regioes_demo_tem_ids_novos():
    primeiras = {r["id"] for r in seed_crm_local.regioes_demo()}
    segundas = {r["id"] for r in seed_crm_local.regioes_demo()}

    assert len(primeiras) == 4 and len(segundas) == 4
    assert primeiras.isdisjoint(segundas)


def test_os_dados_das_lojas_sao_os_24_do_autonomo():
    dados = seed_crm_local.dados_lojas_demo()

    assert [
        (d["nome"], d["fase"], d["regiao"], d["localidade"], d["lat"], d["lng"], d["dias_na_fase"])
        for d in dados
    ] == LOJAS_DO_AUTONOMO


def test_cria_24_lojas_com_demo_no_nome():
    _regioes, lojas = _demo()
    nomes = [loja["nome"] for loja in lojas]

    assert len(nomes) == 24
    assert len(set(nomes)) == 24, "Os nomes não se repetem."
    for nome in nomes:
        assert re.fullmatch(r".*\S \(demo\)", nome), nome


def test_estao_presentes_as_cinco_fases():
    _regioes, lojas = _demo()

    assert sorted({loja["fase"] for loja in lojas}) == FASES
    assert Counter(loja["fase"] for loja in lojas) == {
        "potencial": 7, "cliente": 6, "contactada": 5, "amostra": 4, "perdida": 2,
    }


def test_as_coordenadas_ficam_em_portugal_continental():
    _regioes, lojas = _demo()

    for loja in lojas:
        assert 36.8 <= loja["lat"] <= 42.2, loja["nome"]
        assert -9.6 <= loja["lng"] <= -6.1, loja["nome"]
        assert loja["loc"] == {"type": "Point", "coordinates": [loja["lng"], loja["lat"]]}, loja["nome"]


def test_duas_lojas_ficam_sem_regiao_e_todas_as_regioes_tem_lojas():
    regioes, lojas = _demo()
    ids = _ids_das_regioes(regioes)

    assert [loja["nome"] for loja in lojas if loja["regiao_id"] is None] == [
        "Café da Universidade (demo)", "Mercearia do Giraldo (demo)",
    ]
    assert {loja["regiao_id"] for loja in lojas} - {None} == set(ids.values())
    por_regiao = Counter(loja["regiao_id"] for loja in lojas)
    assert {nome: por_regiao[regiao_id] for nome, regiao_id in ids.items()} == {
        "Lisboa": 7, "Porto": 6, "Setúbal": 4, "Algarve": 5,
    }


def test_nenhuma_loja_fica_perto_de_outra():
    _regioes, lojas = _demo()

    for i, a in enumerate(lojas):
        for b in lojas[i + 1:]:
            distancia = _distancia_m(a, b)
            assert distancia >= 200, f"{a['nome']} e {b['nome']} estão a {distancia} m."
        # Nenhum par é duplicado (a regra dos 50 m, T2.3), nem sequer a 200 m.
        assert encontrar_duplicados(lojas, a["lat"], a["lng"], excluir_id=a["id"]) == []
        assert encontrar_duplicados(lojas, a["lat"], a["lng"], excluir_id=a["id"], raio=200) == []


def test_algumas_lojas_tem_telefone_mas_nunca_um_numero_que_exista():
    _regioes, lojas = _demo()
    telefones = [loja["telefone"] for loja in lojas if loja["telefone"] is not None]

    assert telefones == [f"+351 000 000 {n:03d}" for n in range(1, 12)]
    for telefone in telefones:
        # Em Portugal nenhum número começa por 0: "Ligar" numa loja de demonstração não liga a ninguém.
        assert re.fullmatch(r"\+351 000 000 [0-9]{3}", telefone)


def test_os_campos_seguem_as_regras_das_lojas():
    regioes, lojas = _demo()
    ids = _ids_das_regioes(regioes)

    for dados, loja in zip(seed_crm_local.dados_lojas_demo(), lojas):
        nome = loja["nome"]
        # Válidas pelo validador da API, e já normalizadas: o validador não muda nada.
        validados, erros = validador_loja.criacao({**dados, "regiao_id": ids.get(dados["regiao"])})
        assert erros == {}, nome
        assert validados == {
            **{campo: dados.get(campo) for campo in validador_loja.CAMPOS},
            "regiao_id": ids.get(dados["regiao"]),
        }, nome

        assert loja["origem_coords"] in ("pin_manual", "gps", "geocoder"), nome
        if loja["origem_coords"] == "gps":
            assert type(loja["precisao_m"]) is int and loja["precisao_m"] <= 50, nome
        else:
            assert loja["precisao_m"] is None, nome
        assert 0 <= len(loja["janelas"]) <= 2, nome
        for janela in loja["janelas"]:
            assert janela["inicio"] < janela["fim"], nome
        if len(loja["janelas"]) == 2:
            assert loja["janelas"][0]["fim"] < loja["janelas"][1]["inicio"], nome

    gps = [(loja["nome"], loja["precisao_m"]) for loja in lojas if loja["origem_coords"] == "gps"]
    assert gps == [("Pastelaria Saldanha (demo)", 12), ("Frutaria do Bocage (demo)", 25)]


def test_cada_loja_tem_a_forma_do_documento_loja_e_le_se_pela_api():
    regioes, lojas = _demo()
    ids = _ids_das_regioes(regioes)

    for dados, loja in zip(seed_crm_local.dados_lojas_demo(), lojas):
        validados, _erros = validador_loja.criacao({**dados, "regiao_id": ids.get(dados["regiao"])})
        esperada = formatar.documento_loja(validados, "seed-local", AGORA)
        assert list(loja) == list(esperada), loja["nome"]
        # Igual ao que o POST /lojas gravava, menos o id (novo) e o início da fase.
        assert {c for c in esperada if loja[c] != esperada[c]} == {"id", "fase_desde", "criado_em"}
        assert _e_uuid4(loja["id"])

        api = formatar.loja_api(loja)
        assert list(api) == list(formatar.CAMPOS_API)
        for campo in validador_loja.CAMPOS:
            esperado = ids.get(dados["regiao"]) if campo == "regiao_id" else dados.get(campo)
            assert api[campo] == esperado, (loja["nome"], campo)


def test_a_primeira_loja_por_inteiro():
    regioes, lojas = _demo()
    loja = lojas[0]

    assert list(loja) == [
        "id", "nome", "fase", "fase_desde", "regiao_id", "morada", "codigo_postal", "localidade",
        "lat", "lng", "loc", "origem_coords", "precisao_m", "google_place_id", "telefone", "pessoa_contacto",
        "instagram", "site", "notas", "janelas", "dias_fechada", "visita_pendente_motivo", "visita_pendente_desde",
        "ultima_interacao_em", "ultima_visita_ou_entrega_em", "criado_por", "criado_em", "atualizado_em",
    ]
    assert {**loja, "id": "<uuid4>"} == {
        "id": "<uuid4>",
        "nome": "Mercearia da Baixa (demo)",
        "fase": "cliente",
        "fase_desde": "2026-06-12T09:00:00Z",
        "regiao_id": _ids_das_regioes(regioes)["Lisboa"],
        "morada": None,
        "codigo_postal": None,
        "localidade": "Lisboa",
        "lat": 38.7108,
        "lng": -9.1369,
        "loc": {"type": "Point", "coordinates": [-9.1369, 38.7108]},
        "origem_coords": "pin_manual",
        "precisao_m": None,
        "google_place_id": None,
        "telefone": "+351 000 000 001",
        "pessoa_contacto": "Ana",
        "instagram": "https://www.instagram.com/mercearia.da.baixa.demo/",
        "site": "https://mercearia-da-baixa.example.com",
        "notas": "Encomenda todas as semanas. Descarga pela porta lateral.",
        "janelas": [{"inicio": "09:00", "fim": "12:00"}, {"inicio": "14:30", "fim": "18:00"}],
        "dias_fechada": ["dom"],
        "visita_pendente_motivo": None,
        "visita_pendente_desde": None,
        "ultima_interacao_em": None,
        "ultima_visita_ou_entrega_em": None,
        "criado_por": "seed-local",
        "criado_em": "2026-06-12T09:00:00Z",
        "atualizado_em": "2026-10-10T09:00:00.123456Z",
    }


def test_os_campos_opcionais_sao_os_do_autonomo():
    _regioes, lojas = _demo()
    padroes = ("pin_manual", None, None, None, None, None, None, None, None, [])

    for dados, loja in zip(seed_crm_local.dados_lojas_demo(), lojas):
        esperados = OPCIONAIS_DO_AUTONOMO.get(dados["nome"], padroes)
        assert tuple(dados[c] for c in (
            "origem_coords", "precisao_m", "telefone", "pessoa_contacto", "notas",
            "janela1_inicio", "janela1_fim", "janela2_inicio", "janela2_fim", "dias_fechada",
        )) == esperados, dados["nome"]
        janelas = [
            {"inicio": inicio, "fim": fim}
            for inicio, fim in (esperados[5:7], esperados[7:9]) if inicio is not None
        ]
        assert (loja["origem_coords"], loja["precisao_m"], loja["telefone"], loja["pessoa_contacto"],
                loja["notas"], loja["janelas"], loja["dias_fechada"]) == (*esperados[:5], janelas, esperados[9])
    assert len(OPCIONAIS_DO_AUTONOMO) == 14


def test_duas_lojas_tem_instagram_e_site_de_demonstracao_e_as_outras_nao():
    """2026-10-13: o Instagram e o site não existiam no autónomo. Duas lojas
    levam exemplos (um perfil com "demo" no nome e um domínio `example.com`,
    reservado pela RFC 2606: não apontam para ninguém); as outras ficam a null."""
    _regioes, lojas = _demo()
    com_valores = {
        loja["nome"]: (loja["instagram"], loja["site"])
        for loja in lojas if loja["instagram"] is not None or loja["site"] is not None
    }
    assert com_valores == {
        "Mercearia da Baixa (demo)": (
            "https://www.instagram.com/mercearia.da.baixa.demo/", "https://mercearia-da-baixa.example.com",
        ),
        "Gelataria da Sé (demo)": ("https://www.instagram.com/gelataria.da.se.demo/", None),
    }
    for loja in lojas:
        assert "instagram" in loja and "site" in loja, loja["nome"]


def test_usa_o_instante_do_relogio_e_a_fase_comeca_nos_dias_na_fase():
    """Correções do plano, linha "T2.18": os `dias_na_fase` do autónomo dão `fase_desde`
    variados (os alertas da F5 contam com eles); `criado_em` é o mesmo instante (nunca
    depois do início da fase) e `atualizado_em` o carimbo do relógio."""
    _regioes, lojas = _demo()

    for dados, loja in zip(seed_crm_local.dados_lojas_demo(), lojas):
        assert loja["fase_desde"] == _instante_dias_antes(AGORA, dados["dias_na_fase"]), loja["nome"]
        assert loja["criado_em"] <= loja["fase_desde"], loja["nome"]
        assert loja["criado_em"] == loja["fase_desde"], loja["nome"]
        assert loja["fase_desde"] < "2026-10-10T09:00:00Z", loja["nome"]
        assert loja["atualizado_em"] == "2026-10-10T09:00:00.123456Z"
        assert loja["criado_por"] == "seed-local"
        assert [loja[c] for c in ("visita_pendente_motivo", "visita_pendente_desde",
                                  "ultima_interacao_em", "ultima_visita_ou_entrega_em")] == [None] * 4
        assert instantes_fora_do_formato(loja) == [], loja["nome"]

    por_nome = {loja["nome"]: loja["fase_desde"] for loja in lojas}
    assert por_nome["Pastelaria Saldanha (demo)"] == "2026-03-24T09:00:00Z"   # 200 dias
    assert por_nome["Snack-bar de Belém (demo)"] == "2026-10-09T09:00:00Z"    # 1 dia
    assert por_nome["Mercearia do Giraldo (demo)"] == "2026-09-10T09:00:00Z"  # 30 dias
    assert len(set(por_nome.values())) > 5


def test_o_inicio_da_fase_e_em_utc_venha_o_agora_com_o_fuso_que_vier():
    """Os dias contam-se em UTC: com a hora de Lisboa, 200 dias antes de outubro (hora de
    verão) cai em março, antes da mudança da hora — contados no relógio de parede de Lisboa,
    o início da fase sairia uma hora depois."""
    agora = datetime(2026, 10, 10, 10, 0, 0, 123456, tzinfo=ZoneInfo("Europe/Lisbon"))  # 09:00:00.123456Z

    _regioes, lojas = _demo(agora)
    por_nome = {loja["nome"]: loja for loja in lojas}

    assert por_nome["Mercearia da Baixa (demo)"]["fase_desde"] == "2026-06-12T09:00:00Z"
    assert por_nome["Pastelaria Saldanha (demo)"]["fase_desde"] == "2026-03-24T09:00:00Z"
    assert por_nome["Pastelaria Saldanha (demo)"]["criado_em"] == "2026-03-24T09:00:00Z"
    assert all(loja["atualizado_em"] == "2026-10-10T09:00:00.123456Z" for loja in lojas)


def test_lojas_demo_nao_partilha_listas_com_os_dados_nem_entre_chamadas():
    regioes = seed_crm_local.regioes_demo()
    primeiras = seed_crm_local.lojas_demo(regioes, AGORA)
    primeiras[0]["dias_fechada"].append("seg")
    primeiras[0]["janelas"].clear()
    seed_crm_local.dados_lojas_demo()[0]["dias_fechada"].append("ter")

    segundas = seed_crm_local.lojas_demo(regioes, AGORA)

    assert segundas[0]["dias_fechada"] == ["dom"]
    assert len(segundas[0]["janelas"]) == 2
    assert {loja["id"] for loja in primeiras}.isdisjoint({loja["id"] for loja in segundas})


def test_uma_loja_de_demonstracao_invalida_e_um_erro_antes_de_qualquer_escrita(monkeypatch):
    dados = seed_crm_local.dados_lojas_demo()
    dados[3]["lat"] = 51.5   # Londres
    monkeypatch.setattr(seed_crm_local, "dados_lojas_demo", lambda: dados)
    db = BaseFalsa()

    with pytest.raises(ValueError) as erro:
        seed_crm_local.aplicar_lojas(db, AGORA)

    assert str(erro.value) == (
        "Loja de demonstração inválida: Pastelaria Saldanha (demo): {'lat': 'Fora de Portugal'}"
    )
    assert db.registo == []


# ---------------------------------------------------------------- gravar na base

@pytest.mark.parametrize("total,texto", [(0, "0 lojas"), (1, "1 loja"), (2, "2 lojas"), (25, "25 lojas")])
def test_quantas_escreve_o_singular_so_para_um(total, texto):
    assert seed_crm_local.quantas(total, "loja", "lojas") == texto


def test_quantas_regioes():
    assert seed_crm_local.quantas(1, "região", "regiões") == "1 região"
    assert seed_crm_local.quantas(5, "região", "regiões") == "5 regiões"


def test_cria_as_quatro_regioes_e_as_24_lojas():
    db = BaseFalsa()

    linhas = seed_crm_local.aplicar_lojas(db, AGORA)

    assert linhas == [CRIADAS]
    assert [(r["nome"], r["ordem"]) for r in db[REGIOES].docs] == [
        ("Lisboa", 1), ("Porto", 2), ("Setúbal", 3), ("Algarve", 4),
    ]
    assert [loja["nome"] for loja in db[LOJAS].docs] == [linha[0] for linha in LOJAS_DO_AUTONOMO]
    ids = _ids_das_regioes(db[REGIOES].docs)
    assert [loja["regiao_id"] for loja in db[LOJAS].docs] == [
        ids.get(linha[2]) for linha in LOJAS_DO_AUTONOMO
    ]
    # Não cria interações; as regiões primeiro, porque as lojas apontam para elas.
    assert db.registo == [(REGIOES, "insert_many"), (LOJAS, "insert_many")]


def test_recusa_se_ja_houver_lojas():
    db = BaseFalsa()
    db[LOJAS].insert_one({"id": "l-verdadeira", "nome": "Loja verdadeira", "regiao_id": None})
    antes = _estado(db)
    db.registo.clear()

    with pytest.raises(SystemExit) as recusa:
        seed_crm_local.aplicar_lojas(db, AGORA)

    assert recusa.value.code == "Recusado: a base de dados já tem 1 loja e 0 regiões." + USE_REPOR
    assert _estado(db) == antes
    assert db.registo == []


def test_recusa_se_ja_houver_regioes():
    db = BaseFalsa()
    db[REGIOES].insert_one({"id": "r-1", "nome": "Lisboa", "nome_chave": "lisboa", "ordem": 0})
    db[REGIOES].insert_one({"id": "r-2", "nome": "Minho", "nome_chave": "minho", "ordem": 0})
    antes = _estado(db)
    db.registo.clear()

    with pytest.raises(SystemExit) as recusa:
        seed_crm_local.aplicar_lojas(db, AGORA)

    assert recusa.value.code == "Recusado: a base de dados já tem 0 lojas e 2 regiões." + USE_REPOR
    assert _estado(db) == antes
    assert db.registo == []


def test_a_segunda_vez_sem_repor_recusa_e_nao_duplica():
    db = BaseFalsa()
    seed_crm_local.aplicar_lojas(db, AGORA)
    antes = _estado(db)

    with pytest.raises(SystemExit) as recusa:
        seed_crm_local.aplicar_lojas(db, AGORA)

    assert recusa.value.code == "Recusado: a base de dados já tem 24 lojas e 4 regiões." + USE_REPOR
    assert _estado(db) == antes


def test_repor_apaga_todas_as_lojas_regioes_e_interacoes_e_cria_de_novo():
    db = BaseFalsa()
    seed_crm_local.aplicar_lojas(db, AGORA)
    db[REGIOES].insert_one({"id": "r-minho", "nome": "Minho", "nome_chave": "minho", "ordem": 0})
    db[LOJAS].insert_one({"id": "l-verdadeira", "nome": "Loja verdadeira", "regiao_id": "r-minho"})
    db[INTERACOES].insert_one({"id": "i-1", "loja_id": "l-verdadeira", "tipo": "mudanca_fase",
                               "resultado": "potencial→contactada"})
    for nome in ("crm_membros", "crm_definicoes", "users", "fat_lojas"):
        db[nome].insert_one({"id": f"{nome}-1"})
    intactas = {nome: copy.deepcopy(db[nome].docs) for nome in ("crm_membros", "crm_definicoes", "users", "fat_lojas")}
    ids_antes = {loja["id"] for loja in db[LOJAS].docs}
    db.registo.clear()

    linhas = seed_crm_local.aplicar_lojas(db, AGORA, repor=True)

    assert linhas == ["Apagadas: 25 lojas e 5 regiões.", CRIADAS]
    assert len(db[LOJAS].docs) == 24
    assert [loja for loja in db[LOJAS].docs if loja["nome"] == "Loja verdadeira"] == []
    assert ids_antes.isdisjoint(loja["id"] for loja in db[LOJAS].docs)
    assert sorted(r["nome"] for r in db[REGIOES].docs) == ["Algarve", "Lisboa", "Porto", "Setúbal"]
    assert db[INTERACOES].docs == []
    # Só apaga e grava nas três coleções, por esta ordem: as interações vão com as lojas,
    # e as regiões só depois das lojas.
    assert db.registo == [
        (LOJAS, "delete_many"), (INTERACOES, "delete_many"), (REGIOES, "delete_many"),
        (REGIOES, "insert_many"), (LOJAS, "insert_many"),
    ]
    assert {nome: db[nome].docs for nome in intactas} == intactas


def test_repor_conta_as_lojas_e_regioes_apagadas():
    db = _base_com_dados_verdadeiros()

    linhas = seed_crm_local.aplicar_lojas(db, AGORA, repor=True)

    assert linhas == ["Apagadas: 1 loja e 1 região.", CRIADAS]
    assert [loja["nome"] for loja in db[LOJAS].docs if not loja["nome"].endswith(" (demo)")] == []
    assert db[INTERACOES].docs == []


def test_repor_numa_base_vazia_so_cria():
    db = BaseFalsa()

    linhas = seed_crm_local.aplicar_lojas(db, AGORA, repor=True)

    assert linhas == ["Apagadas: 0 lojas e 0 regiões.", CRIADAS]
    assert len(db[LOJAS].docs) == 24 and len(db[REGIOES].docs) == 4


@pytest.mark.parametrize(
    "colecao,recusado",
    [
        (LOJAS, "Mercearia da Baixa (demo)"),
        (LOJAS, "Bar da Foz (demo)"),
        (LOJAS, "Mercearia do Giraldo (demo)"),
        (REGIOES, "Setúbal"),
    ],
    ids=["a-primeira-loja", "uma-loja-a-meio", "a-ultima-loja", "uma-regiao"],
)
def test_se_uma_insercao_falhar_nada_muda(colecao, recusado):
    db = BaseFalsa()
    db[colecao].recusar = lambda doc: doc["nome"] == recusado

    with pytest.raises(SystemExit) as erro:
        seed_crm_local.aplicar_lojas(db, AGORA)

    assert erro.value.code == NADA_MUDOU + "BulkWriteError: falha simulada"
    assert db[REGIOES].docs == [], "As regiões também voltam atrás."
    assert db[LOJAS].docs == []


def test_se_o_repor_falhar_fica_tudo_como_estava():
    db = _base_com_dados_verdadeiros()
    antes = _estado(db)
    # Como um validador do Mongo que só recusa as lojas de demonstração.
    db[LOJAS].recusar = lambda doc: doc["nome"].endswith(" (demo)")

    with pytest.raises(SystemExit) as erro:
        seed_crm_local.aplicar_lojas(db, AGORA, repor=True)

    assert erro.value.code == NADA_MUDOU + "BulkWriteError: falha simulada"
    assert _estado(db) == antes


def test_uma_falha_que_nao_e_de_escrita_tambem_se_descreve_numa_linha():
    db = _base_com_dados_verdadeiros()
    antes = _estado(db)

    inserir = db[LOJAS].insert_many
    falhou = []

    def sem_ligacao_da_primeira_vez(docs):
        if not falhou:
            falhou.append(True)
            raise AutoReconnect("ligação perdida")
        return inserir(docs)   # a reposição da loja verdadeira já passa

    db[LOJAS].insert_many = sem_ligacao_da_primeira_vez

    with pytest.raises(SystemExit) as erro:
        seed_crm_local.aplicar_lojas(db, AGORA, repor=True)

    assert erro.value.code == NADA_MUDOU + "AutoReconnect: ligação perdida"
    assert _estado(db) == antes


def test_se_nem_repor_o_que_havia_conseguir_diz_que_a_base_pode_ter_ficado_a_meio():
    db = _base_com_dados_verdadeiros()
    db[LOJAS].recusar = lambda doc: True   # recusa também a loja verdadeira, ao repô-la

    with pytest.raises(SystemExit) as erro:
        seed_crm_local.aplicar_lojas(db, AGORA, repor=True)

    assert erro.value.code == A_MEIO + "BulkWriteError: falha simulada"


# ---------------------------------------------------------------- CLI com as lojas

def _correr_cli(tmp_path, monkeypatch, base, *argumentos):
    criados = []
    cliente = _cliente_falso(criados, base)
    credenciais = tmp_path / "cfg" / "credenciais.txt"
    monkeypatch.setattr(seed_crm_local, "MongoClient", cliente)
    monkeypatch.setattr(seed_crm_local, "FICHEIRO_CREDENCIAIS", credenciais)
    caminho_env = _ficheiro_env(tmp_path, "mongodb://127.0.0.1:27017", "lisbonb_crm_local")
    try:
        return seed_crm_local.main(["--env-file", str(caminho_env), *argumentos]), cliente, credenciais
    finally:
        assert all(c.fechado for c in cliente.clientes)


def test_cli_com_lojas_na_base_recusa_sem_criar_contas_nem_o_ficheiro(tmp_path, monkeypatch, capsys):
    base = BaseFalsa()
    base[LOJAS].insert_one({"id": "l-verdadeira", "nome": "Loja verdadeira", "regiao_id": None})
    base.registo.clear()

    with pytest.raises(SystemExit) as recusa:
        _correr_cli(tmp_path, monkeypatch, base)

    assert recusa.value.code == "Recusado: a base de dados já tem 1 loja e 0 regiões." + USE_REPOR
    assert base.registo == []
    assert not (tmp_path / "cfg").exists()
    assert capsys.readouterr().out == ""


def test_cli_repor_gera_palavras_passe_novas_e_repoe_as_lojas(tmp_path, monkeypatch, capsys):
    base = BaseFalsa()
    _correr_cli(tmp_path, monkeypatch, base)
    regioes_antes = {r["id"] for r in base[REGIOES].docs}
    capsys.readouterr()

    saida, _cliente, credenciais = _correr_cli(tmp_path, monkeypatch, base, "--repor")

    assert saida == 0
    assert capsys.readouterr().out.splitlines() == [
        f"Palavras-passe das contas de demonstração (4 novas): {credenciais}",
        "Apagadas: 24 lojas e 4 regiões.",
        CRIADAS,
    ]
    assert len(base[LOJAS].docs) == 24 and len(base[REGIOES].docs) == 4
    assert regioes_antes.isdisjoint(r["id"] for r in base[REGIOES].docs)
    for email, palavra in seed_crm_local.ler_credenciais(credenciais).items():
        assert _confere(palavra, _conta(base, email)["password"])


def test_cli_se_as_lojas_falharem_as_palavras_passe_novas_ficam_guardadas(tmp_path, monkeypatch, capsys):
    base = BaseFalsa()
    base[LOJAS].recusar = lambda doc: True

    with pytest.raises(SystemExit) as erro:
        _correr_cli(tmp_path, monkeypatch, base)

    assert erro.value.code == NADA_MUDOU + "BulkWriteError: falha simulada"
    credenciais = tmp_path / "cfg" / "credenciais.txt"
    guardadas = seed_crm_local.ler_credenciais(credenciais)
    assert len(guardadas) == 4
    for email, palavra in guardadas.items():
        assert _confere(palavra, _conta(base, email)["password"])
    assert capsys.readouterr().out.splitlines() == [
        f"Palavras-passe das contas de demonstração (4 novas): {credenciais}",
    ]
    assert base[REGIOES].docs == [] and base[LOJAS].docs == []


def test_cli_a_ajuda_diz_o_que_o_repor_apaga(capsys):
    with pytest.raises(SystemExit) as saida:
        seed_crm_local.main(["--help"])

    assert saida.value.code == 0
    texto = " ".join(capsys.readouterr().out.split())
    assert "4 regiões e 24 lojas de demonstração" in texto
    assert "apaga todas as lojas, regiões e interações do CRM (só na base *_local)" in texto
