"""Seed local do CRM Purple House: contas de demonstração, membros do CRM e as regiões e
lojas de demonstração, SÓ em local.

Uso (a partir de backend/):
    .venv/bin/python seed_crm_local.py --env-file .env.local [--repor]

- Lê o ficheiro de ambiente com dotenv_values (não mexe no os.environ deste processo).
- Guarda: recusa tudo o que não seja um MongoDB local (mongodb:// com uma só máquina, em
  127.0.0.1, localhost ou ::1) e uma base cujo nome acabe em _local. A guarda corre
  ANTES de se criar qualquer cliente Mongo, e o cliente liga-se só a essa máquina
  (directConnection: não segue para os outros membros de um conjunto de réplicas).
- Contas (T0.7): 4 contas "(demo)" @example.com e 3 membros do CRM. O que já existe fica
  como está; sem --repor as palavras-passe nunca mudam.
- Regiões e lojas (T2.18): as 4 regiões e as 24 lojas "(demo)" do src/Cli/DadosDemo.php do
  CRM autónomo (nomes inventados, telefones +351 000 que não ligam a ninguém, as 5 fases, 2
  lojas sem região, todas a mais de 200 m umas das outras; desde 2026-10-13, 2 com um
  Instagram de demonstração — perfis com "demo" no nome — e 1 com um site num domínio
  example.com, reservado pela RFC 2606: nada disto aponta para ninguém). Construídas com o
  `formatar.documento_loja` (a forma que o POST /lojas grava), com o início da fase recuado
  pelos dias na fase de cada uma. Recusa se a base já tiver lojas ou regiões — antes de
  qualquer escrita, também das contas.
- --repor gera palavras-passe novas para as 4 contas e apaga TODAS as lojas, regiões e
  interações do CRM (só essas três coleções, e só na base *_local) para as criar de novo.
- Sem transações (o MongoDB local não as tem; plano §1): tudo é construído e validado antes
  da primeira escrita, e se uma escrita falhar o seed repõe a cópia do que havia nas
  coleções que mexeu ("nada mudou", como a transação do autónomo).
- As palavras-passe novas vão para ~/.config/lisbonb-crm-local/credenciais.txt (modo 600),
  logo a seguir às contas (uma falha nas lojas não as perde); no ecrã só aparece o caminho.
"""
import argparse
import os
import secrets
import string
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
from dotenv import dotenv_values
from pymongo import MongoClient, uri_parser
from pymongo.errors import BulkWriteError, PyMongoError, ServerSelectionTimeoutError

from crm import formatar, relogio
from crm.db import COLECOES
from crm.dominio import regioes as regras_regioes
from crm.dominio import validador_loja

COLECAO_CONTAS = "users"
COLECAO_MEMBROS = "crm_membros"  # na T1.2 confirma-se contra crm.db.COLECOES["membros"]
COLECAO_REGIOES = COLECOES["regioes"]
COLECAO_LOJAS = COLECOES["lojas"]
COLECAO_INTERACOES = COLECOES["interacoes"]
# O que o --repor apaga, por esta ordem: as interações vão com as lojas, e as regiões só
# depois das lojas (o DELETE das lojas com CASCADE e o das regiões com RESTRICT do autónomo).
COLECOES_REPOR = (COLECAO_LOJAS, COLECAO_INTERACOES, COLECAO_REGIOES)
CRIADO_POR = "seed-local"
PREFIXO_URI = "mongodb://"
ANFITRIOES_LOCAIS = frozenset({"127.0.0.1", "localhost", "::1"})
SUFIXO_BASE = "_local"
ESPERA_MONGO_MS = 3000
# Só a máquina do URI (revisão da F2): sem directConnection, o PyMongo 4 descobre o conjunto
# de réplicas a partir do nó local e manda as escritas para o primário que ele anunciar,
# mesmo noutra máquina. Estas opções ganham às do URI (um `?directConnection=false` ou um
# `?replicaSet=…` não as desfazem). O ensaio da T2.17 liga-se da mesma maneira.
OPCOES_CLIENTE = {"directConnection": True, "serverSelectionTimeoutMS": ESPERA_MONGO_MS}
FICHEIRO_CREDENCIAIS = Path.home() / ".config" / "lisbonb-crm-local" / "credenciais.txt"

MENSAGEM_RECUSA = (
    "Recusado: o seed só corre num MongoDB local (mongodb://127.0.0.1) e numa base *_local."
)
MENSAGEM_SEM_MONGO = (
    "Erro: o MongoDB local não respondeu (está a correr? "
    "brew services start mongodb/brew/mongodb-community@8.0)."
)
MENSAGEM_JA_HA_DADOS = (
    "Recusado: a base de dados já tem {lojas} e {regioes}. Use --repor para apagar todas as lojas"
    " e regiões e criar os dados de demonstração de novo."
)
MENSAGEM_APAGADAS = "Apagadas: {lojas} e {regioes}."
MENSAGEM_CRIADAS = "Criadas: {regioes} e {lojas} de demonstração."
MENSAGEM_NADA_MUDOU = "Erro: os dados de demonstração não foram criados (nada mudou): {causa}"
MENSAGEM_A_MEIO = (
    "Erro: os dados de demonstração não foram criados e não foi possível repor o que havia; "
    "a base pode ter ficado a meio. Corra o seed de novo com --repor. Causa: {causa}"
)
CABECALHO_CREDENCIAIS = (
    "# Contas de demonstração do CRM — só para o portal local. Não partilhar nem versionar.\n"
    "# email<TAB>palavra-passe\n"
)

_CONTAS_DEMO = (
    # (email, nome, role no portal, perfil no CRM ou None se não for membro)
    ("gestor.demo@example.com", "Gestor (demo)", "gerente", None),
    ("escritorio.demo@example.com", "Escritório (demo)", "gerente", "utilizador"),
    ("colaborador.demo@example.com", "Colaborador (demo)", "colaborador", "utilizador"),
    ("motorista.demo@example.com", "Motorista (demo)", "colaborador", "motorista"),
)


# As regiões e as lojas do src/Cli/DadosDemo.php do CRM autónomo (nomes e coordenadas
# inventados, aproximados, em Portugal continental).

# Nome da região e ordem nas listas.
REGIOES_DEMO = (("Lisboa", 1), ("Porto", 2), ("Setúbal", 3), ("Algarve", 4))

# Campos opcionais de cada loja, quando a linha não os indica. O Instagram e o site
# (2026-10-13) vão já na forma normalizada, como os telefones.
_PADROES = {
    "origem_coords": "pin_manual",
    "precisao_m": None,
    "telefone": None,
    "pessoa_contacto": None,
    "instagram": None,
    "site": None,
    "notas": None,
    "janela1": (None, None),
    "janela2": (None, None),
    "dias_fechada": (),
}

# Cada linha: nome, fase, região (None = sem região), localidade, lat, lng, dias na fase, opcionais.
_LOJAS_DEMO = (
    ("Mercearia da Baixa", "cliente", "Lisboa", "Lisboa", 38.710800, -9.136900, 120, {
        "telefone": "+351 000 000 001", "pessoa_contacto": "Ana",
        "instagram": "https://www.instagram.com/mercearia.da.baixa.demo/",
        "site": "https://mercearia-da-baixa.example.com",
        "janela1": ("09:00", "12:00"), "janela2": ("14:30", "18:00"), "dias_fechada": ("dom",),
        "notas": "Encomenda todas as semanas. Descarga pela porta lateral.",
    }),
    ("Café do Bairro Alto", "amostra", "Lisboa", "Lisboa", 38.713500, -9.145800, 5, {
        "telefone": "+351 000 000 002", "janela1": ("10:00", "13:00"), "dias_fechada": ("seg",),
    }),
    ("Gelataria do Rato", "contactada", "Lisboa", "Lisboa", 38.722400, -9.145200, 12, {
        "pessoa_contacto": "Rui",
    }),
    ("Pastelaria Saldanha", "cliente", "Lisboa", "Lisboa", 38.736900, -9.142600, 200, {
        "origem_coords": "gps", "precisao_m": 12, "telefone": "+351 000 000 003",
        "janela1": ("08:00", "11:00"), "dias_fechada": ("sab", "dom"),
    }),
    ("Minimercado Entrecampos", "potencial", "Lisboa", "Lisboa", 38.746500, -9.147900, 2),
    ("Quiosque de Alfama", "perdida", "Lisboa", "Lisboa", 38.711900, -9.130100, 45, {
        "notas": "Não tem arca congeladora.",
    }),
    ("Snack-bar de Belém", "potencial", "Lisboa", "Lisboa", 38.697200, -9.206300, 1),

    ("Mercearia dos Aliados", "cliente", "Porto", "Porto", 41.145600, -8.611000, 90, {
        "telefone": "+351 000 000 004", "pessoa_contacto": "Joana",
        "janela1": ("09:00", "12:30"), "dias_fechada": ("dom",),
    }),
    ("Café da Ribeira", "contactada", "Porto", "Porto", 41.142200, -8.614500, 20),
    ("Gelataria da Boavista", "amostra", "Porto", "Porto", 41.157800, -8.629600, 9, {
        "telefone": "+351 000 000 005",
    }),
    ("Frutaria das Antas", "potencial", "Porto", "Porto", 41.161500, -8.583600, 3),
    ("Bar da Foz", "cliente", "Porto", "Porto", 41.152000, -8.672000, 35, {
        "telefone": "+351 000 000 006", "janela1": ("15:00", "19:00"), "dias_fechada": ("seg", "ter"),
    }),
    ("Cantina da Asprela", "potencial", "Porto", "Porto", 41.178200, -8.598000, 6),

    ("Frutaria do Bocage", "cliente", "Setúbal", "Setúbal", 38.524500, -8.891800, 60, {
        "origem_coords": "gps", "precisao_m": 25, "telefone": "+351 000 000 007",
        "janela1": ("07:30", "10:30"), "dias_fechada": ("dom",),
    }),
    ("Café do Bonfim", "contactada", "Setúbal", "Setúbal", 38.526900, -8.881300, 15),
    ("Gelataria da Avenida", "amostra", "Setúbal", "Setúbal", 38.530800, -8.900500, 3, {
        "telefone": "+351 000 000 008",
    }),
    ("Padaria de São Sebastião", "potencial", "Setúbal", "Setúbal", 38.535000, -8.876000, 4),

    ("Gelataria da Sé", "cliente", "Algarve", "Faro", 37.018000, -7.933500, 150, {
        "telefone": "+351 000 000 009", "instagram": "https://www.instagram.com/gelataria.da.se.demo/",
        "janela1": ("10:00", "12:00"), "janela2": ("16:00", "19:00"), "dias_fechada": ("qua",),
    }),
    ("Mercearia do Largo", "contactada", "Algarve", "Faro", 37.019800, -7.929000, 8),
    ("Bar da Praia", "amostra", "Algarve", "Albufeira", 37.092000, -8.247000, 14, {
        "telefone": "+351 000 000 010",
    }),
    ("Café da Marina", "potencial", "Algarve", "Lagos", 37.104500, -8.676500, 10),
    ("Quiosque de Tavira", "perdida", "Algarve", "Tavira", 37.128500, -7.652500, 80, {
        "notas": "Fechou para obras. Voltar a tentar na primavera.",
    }),

    ("Café da Universidade", "contactada", None, "Coimbra", 40.207500, -8.426500, 25, {
        "telefone": "+351 000 000 011",
    }),
    ("Mercearia do Giraldo", "potencial", None, "Évora", 38.571500, -7.909300, 30),
)


# ---------------------------------------------------------------- guarda

def uri_e_local(uri) -> bool:
    """Verdadeiro só para mongodb:// com UMA máquina, e local.

    Recusa-se o que não começa por mongodb:// antes de interpretar o URI (um mongodb+srv://
    faria uma consulta DNS). Qualquer erro ao interpretar conta como não local. Mais de uma
    máquina, mesmo todas locais, recusa-se: o cliente liga-se com directConnection
    (OPCOES_CLIENTE), que só aceita uma (revisão da F2).
    """
    if not isinstance(uri, str) or not uri.startswith(PREFIXO_URI):
        return False
    try:
        nos = uri_parser.parse_uri(uri)["nodelist"]
    except Exception:
        return False
    return len(nos) == 1 and all(
        isinstance(anfitriao, str) and anfitriao.lower() in ANFITRIOES_LOCAIS
        for anfitriao, _porta in nos
    )


def bd_e_local(nome) -> bool:
    return isinstance(nome, str) and len(nome) > len(SUFIXO_BASE) and nome.endswith(SUFIXO_BASE)


def verificar_ambiente(env) -> tuple:
    """Devolve (uri, nome_da_base) ou sai com a mensagem de recusa."""
    uri = env.get("MONGO_URL")
    nome = env.get("DB_NAME")
    if not (uri_e_local(uri) and bd_e_local(nome)):
        raise SystemExit(MENSAGEM_RECUSA)
    return uri, nome


# ---------------------------------------------------------------- contas

def contas_demo() -> list:
    return [
        {"email": email, "name": nome, "role": role, "perfil": perfil}
        for email, nome, role, perfil in _CONTAS_DEMO
    ]


def gerar_palavra_passe() -> str:
    alfabeto = string.ascii_letters + string.digits
    return "".join(secrets.choice(alfabeto) for _ in range(16))


def _cifrar(palavra: str) -> str:
    # O mesmo bcrypt do server.py (hash_password).
    return bcrypt.hashpw(palavra.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _instante(momento: datetime) -> str:
    # Instantes do CRM: largura fixa, UTC com Z (sem microssegundos).
    return momento.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def aplicar_contas(db, agora, gerar_palavra_passe, repor=False) -> dict:
    """Garante as contas de demonstração e os membros do CRM. Devolve {email: palavra-passe nova}.

    Sem repor, uma conta que já existe fica intacta (e não entra no resultado); com repor,
    recebe uma palavra-passe nova. Só usa insert_one, find_one, update_one e count_documents.
    """
    contas = db[COLECAO_CONTAS]
    membros = db[COLECAO_MEMBROS]
    novas = {}

    for demo in contas_demo():
        conta = contas.find_one({"email": demo["email"]}, {"_id": 0, "id": 1})
        if conta is None:
            palavra = gerar_palavra_passe()
            user_id = str(uuid.uuid4())
            contas.insert_one({
                "id": user_id,
                "email": demo["email"],
                "password": _cifrar(palavra),
                "name": demo["name"],
                "role": demo["role"],
                "employee_id": None,
                "must_change_password": False,
                "created_at": agora.isoformat(),
            })
            novas[demo["email"]] = palavra
        else:
            user_id = conta["id"]
            if repor:
                palavra = gerar_palavra_passe()
                contas.update_one({"id": user_id}, {"$set": {
                    "password": _cifrar(palavra),
                    "must_change_password": False,
                    # Mesma regra do portal: sessões abertas antes da troca deixam de valer.
                    "password_mudada_em": int(agora.timestamp()),
                }})
                novas[demo["email"]] = palavra

        if demo["perfil"] is not None and membros.count_documents({"user_id": user_id}) == 0:
            membros.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "perfil": demo["perfil"],
                "criado_em": _instante(agora),
                "criado_por": CRIADO_POR,
            })

    return novas


# ---------------------------------------------------------------- regiões e lojas

def quantas(total: int, singular: str, plural: str) -> str:
    """"1 loja", "0 lojas", "25 lojas"."""
    return f"1 {singular}" if total == 1 else f"{total} {plural}"


def regioes_demo() -> list:
    """As 4 regiões como o POST /regioes as grava (T2.9): `{id, nome, nome_chave, ordem}`,
    com ids novos em cada chamada. Sem `nome_chave`, a segunda colidia no índice único."""
    return [
        {"id": str(uuid.uuid4()), "nome": nome, "nome_chave": regras_regioes.nome_chave(nome), "ordem": ordem}
        for nome, ordem in REGIOES_DEMO
    ]


def dados_lojas_demo() -> list:
    """As 24 lojas do DadosDemo::lojas(), numa lista nova em cada chamada: os campos da API
    (`dias_fechada` em lista, as janelas planas; sem morada nem código postal), mais a
    `regiao` (nome ou None) e os `dias_na_fase`."""
    lojas = []
    for nome, fase, regiao, localidade, lat, lng, dias, *resto in _LOJAS_DEMO:
        opcionais = {**_PADROES, **(resto[0] if resto else {})}
        lojas.append({
            "nome": f"{nome} (demo)",
            "fase": fase,
            "regiao": regiao,
            "localidade": localidade,
            "lat": lat,
            "lng": lng,
            "dias_na_fase": dias,
            "origem_coords": opcionais["origem_coords"],
            "precisao_m": opcionais["precisao_m"],
            "telefone": opcionais["telefone"],
            "pessoa_contacto": opcionais["pessoa_contacto"],
            "instagram": opcionais["instagram"],
            "site": opcionais["site"],
            "notas": opcionais["notas"],
            "janela1_inicio": opcionais["janela1"][0],
            "janela1_fim": opcionais["janela1"][1],
            "janela2_inicio": opcionais["janela2"][0],
            "janela2_fim": opcionais["janela2"][1],
            "dias_fechada": list(opcionais["dias_fechada"]),
        })
    return lojas


def lojas_demo(regioes, agora) -> list:
    """As 24 lojas como ficam em `crm_lojas`, com os ids das `regioes` (as do
    `regioes_demo`, pelo nome).

    Cada uma passa pelo `validador_loja.criacao` (uma loja inválida é ValueError, antes de
    qualquer escrita) e é construída pelo `formatar.documento_loja` com o `agora`, como no
    POST /lojas. Depois, o início da fase recua os dias na fase de cada uma (correções do
    plano, linha "T2.18"; os alertas da F5 contam com fases de idades diferentes), e a
    loja foi criada nesse instante, como no autónomo. Os dias contam-se em UTC.
    """
    ids = {regiao["nome"]: regiao["id"] for regiao in regioes}
    agora_utc = agora.astimezone(timezone.utc)
    documentos = []
    for dados in dados_lojas_demo():
        regiao_id = None if dados["regiao"] is None else ids[dados["regiao"]]
        validados, erros = validador_loja.criacao({**dados, "regiao_id": regiao_id})
        if erros:
            raise ValueError(f"Loja de demonstração inválida: {dados['nome']}: {erros}")
        documento = formatar.documento_loja(validados, CRIADO_POR, agora)
        inicio_da_fase = relogio.instante(agora_utc - timedelta(days=dados["dias_na_fase"]))
        documento["fase_desde"] = inicio_da_fase
        documento["criado_em"] = inicio_da_fase
        documentos.append(documento)
    return documentos


def verificar_lojas(db, repor=False) -> None:
    """Sem `repor`, sai com a recusa se a base já tiver lojas ou regiões (que podem ser
    verdadeiras: o seed não as distingue). Só lê."""
    if repor:
        return
    lojas = db[COLECAO_LOJAS].count_documents({})
    regioes = db[COLECAO_REGIOES].count_documents({})
    if lojas or regioes:
        raise SystemExit(MENSAGEM_JA_HA_DADOS.format(
            lojas=quantas(lojas, "loja", "lojas"), regioes=quantas(regioes, "região", "regiões"),
        ))


def _descrever(erro) -> str:
    """O erro numa linha: o tipo e a mensagem; num BulkWriteError (o insert_many), a do
    primeiro documento recusado, em vez do relatório inteiro."""
    mensagem = str(erro)
    if isinstance(erro, BulkWriteError):
        recusados = (erro.details or {}).get("writeErrors") or []
        if recusados:
            mensagem = recusados[0].get("errmsg", mensagem)
    return f"{type(erro).__name__}: {mensagem}"


def _repor_copias(db, copias: dict) -> None:
    """Deixa cada coleção de `copias` exatamente com os documentos copiados (com o `_id`)."""
    for nome, documentos in copias.items():
        db[nome].delete_many({})
        if documentos:  # o insert_many do pymongo recusa uma lista vazia
            db[nome].insert_many(documentos)


def aplicar_lojas(db, agora, repor=False) -> list:
    """Cria as regiões e as lojas de demonstração. Devolve as linhas para o ecrã.

    Sem `repor`, recusa (SystemExit) se já houver lojas ou regiões. Com `repor`, apaga
    primeiro tudo o que há nas lojas, interações e regiões (só essas três coleções).
    Ordem das escritas: os apagamentos, as regiões, as lojas (que apontam para elas).

    Tudo é construído antes da primeira escrita. Se uma escrita falhar, as coleções que o
    seed mexe voltam à cópia do que tinham (o MongoDB local não tem transações) e sai com
    "nada mudou"; se nem isso der, diz que a base pode ter ficado a meio.
    """
    verificar_lojas(db, repor)
    regioes = regioes_demo()
    lojas = lojas_demo(regioes, agora)

    if repor:
        copias = {nome: list(db[nome].find({})) for nome in COLECOES_REPOR}
    else:
        copias = {COLECAO_LOJAS: [], COLECAO_REGIOES: []}  # vazias: o verificar_lojas viu

    linhas = []
    try:
        if repor:
            lojas_apagadas = db[COLECAO_LOJAS].delete_many({}).deleted_count
            db[COLECAO_INTERACOES].delete_many({})
            regioes_apagadas = db[COLECAO_REGIOES].delete_many({}).deleted_count
            linhas.append(MENSAGEM_APAGADAS.format(
                lojas=quantas(lojas_apagadas, "loja", "lojas"),
                regioes=quantas(regioes_apagadas, "região", "regiões"),
            ))
        db[COLECAO_REGIOES].insert_many(regioes)
        db[COLECAO_LOJAS].insert_many(lojas)
    except PyMongoError as erro:
        causa = _descrever(erro)
        try:
            _repor_copias(db, copias)
        except PyMongoError:
            raise SystemExit(MENSAGEM_A_MEIO.format(causa=causa)) from None
        raise SystemExit(MENSAGEM_NADA_MUDOU.format(causa=causa)) from None

    linhas.append(MENSAGEM_CRIADAS.format(
        regioes=quantas(len(regioes), "região", "regiões"), lojas=quantas(len(lojas), "loja", "lojas"),
    ))
    return linhas


# ---------------------------------------------------------------- ficheiro das credenciais

def ler_credenciais(caminho) -> dict:
    caminho = Path(caminho)
    if not caminho.exists():
        return {}
    guardadas = {}
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if not linha or linha.startswith("#") or "\t" not in linha:
            continue
        email, palavra = linha.split("\t", 1)
        guardadas[email] = palavra
    return guardadas


def escrever_credenciais(caminho, novas: dict) -> None:
    """Junta as palavras-passe novas às já guardadas; ficheiro em modo 600 (pasta em 700)."""
    caminho = Path(caminho)
    if not caminho.parent.exists():
        caminho.parent.mkdir(parents=True, mode=0o700)
        os.chmod(caminho.parent, 0o700)
    todas = ler_credenciais(caminho)
    todas.update(novas)
    texto = CABECALHO_CREDENCIAIS + "".join(f"{email}\t{palavra}\n" for email, palavra in todas.items())

    temporario = caminho.with_name(caminho.name + ".tmp")
    descritor = os.open(temporario, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descritor, "w", encoding="utf-8") as ficheiro:
            ficheiro.write(texto)
        os.chmod(temporario, 0o600)
        os.replace(temporario, caminho)
    finally:
        if temporario.exists():
            temporario.unlink()
    os.chmod(caminho, 0o600)


# ---------------------------------------------------------------- CLI

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed local do CRM: contas de demonstração, 4 regiões e 24 lojas de demonstração.",
    )
    parser.add_argument("--env-file", required=True, help="ficheiro de ambiente local (ex.: .env.local)")
    parser.add_argument("--repor", action="store_true",
                        help="gera palavras-passe novas para as contas de demonstração e apaga todas as "
                             "lojas, regiões e interações do CRM (só na base *_local) para as criar de novo")
    args = parser.parse_args(argv)

    caminho_env = Path(args.env_file)
    if not caminho_env.is_file():
        raise SystemExit(f"Recusado: o ficheiro de ambiente não existe: {caminho_env}")
    uri, nome = verificar_ambiente(dotenv_values(caminho_env))

    cliente = MongoClient(uri, **OPCOES_CLIENTE)
    try:
        db = cliente[nome]
        agora = datetime.now(timezone.utc)
        # A recusa vem antes de qualquer escrita, também das contas: ou --repor, ou nada muda.
        verificar_lojas(db, args.repor)
        novas = aplicar_contas(db, agora, gerar_palavra_passe, repor=args.repor)
        # As palavras-passe novas guardam-se já: se as lojas falharem, as contas ficam com elas.
        if novas:
            escrever_credenciais(FICHEIRO_CREDENCIAIS, novas)
            print(f"Palavras-passe das contas de demonstração ({len(novas)} novas): {FICHEIRO_CREDENCIAIS}")
        else:
            print(f"Contas de demonstração já existiam; palavras-passe sem alteração em: {FICHEIRO_CREDENCIAIS} "
                  "(--repor gera novas e repõe as lojas e as regiões de demonstração).")
        for linha in aplicar_lojas(db, agora, repor=args.repor):
            print(linha)
    except ServerSelectionTimeoutError:
        raise SystemExit(MENSAGEM_SEM_MONGO) from None
    finally:
        cliente.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
