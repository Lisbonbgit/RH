"""Seed local do CRM: a guarda (só MongoDB local e base *_local) e as contas de demonstração.

O seed usa o pymongo (síncrono), por isso este ficheiro tem o seu próprio duplo síncrono da
base (o duplos.py do CRM, assíncrono, só nasce na T1.2). Nenhum teste liga a um MongoDB.
"""
import copy
import os
import stat
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import bcrypt
import pytest
from pymongo.errors import ServerSelectionTimeoutError

import seed_crm_local

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
    """Só o que o seed pode usar: insert_one, find_one, update_one ($set) e count_documents."""

    def __init__(self):
        self.docs = []

    def insert_one(self, doc):
        self.docs.append(copy.deepcopy(doc))
        return SimpleNamespace(inserted_id=len(self.docs))

    def find_one(self, filtro, projecao=None):
        for doc in self.docs:
            if _corresponde(doc, filtro):
                return copy.deepcopy(doc)
        return None

    def update_one(self, filtro, alteracao):
        assert set(alteracao) == {"$set"}, f"operador não previsto no duplo: {alteracao}"
        for doc in self.docs:
            if _corresponde(doc, filtro):
                doc.update(copy.deepcopy(alteracao["$set"]))
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)

    def count_documents(self, filtro):
        return sum(1 for doc in self.docs if _corresponde(doc, filtro))


class BaseFalsa(dict):
    def __missing__(self, nome):
        self[nome] = ColecaoFalsa()
        return self[nome]


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
    assert criados == [("mongodb://127.0.0.1:27017", {"serverSelectionTimeoutMS": 3000})]
    assert cliente.clientes[0].nomes == ["lisbonb_crm_local"]
    assert cliente.clientes[0].fechado is True
    assert base["users"].count_documents({}) == 4
    assert base["crm_membros"].count_documents({}) == 3

    # Escreve as palavras-passe só no ficheiro (modo 600) e só mostra o caminho.
    assert stat.S_IMODE(credenciais.stat().st_mode) == 0o600
    assert stat.S_IMODE(credenciais.parent.stat().st_mode) == 0o700
    guardadas = seed_crm_local.ler_credenciais(credenciais)
    assert sorted(guardadas) == sorted(c["email"] for c in seed_crm_local.contas_demo())
    for email, palavra in guardadas.items():
        assert _confere(palavra, _conta(base, email)["password"])
    escrito = capsys.readouterr()
    assert str(credenciais) in escrito.out
    for palavra in guardadas.values():
        assert palavra not in escrito.out and palavra not in escrito.err


def test_cli_sem_resposta_do_mongo_sai_com_mensagem_e_fecha_o_cliente(tmp_path, monkeypatch):
    class ColecaoSemServidor(ColecaoFalsa):
        def find_one(self, filtro, projecao=None):
            raise ServerSelectionTimeoutError("127.0.0.1:27017: Connection refused")

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
