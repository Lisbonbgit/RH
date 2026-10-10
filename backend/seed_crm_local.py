"""Seed local do CRM Purple House: contas de demonstração e membros do CRM, SÓ em local.

Uso (a partir de backend/):
    .venv/bin/python seed_crm_local.py --env-file .env.local [--repor]

- Lê o ficheiro de ambiente com dotenv_values (não mexe no os.environ deste processo).
- Guarda: recusa tudo o que não seja um MongoDB local (mongodb:// com todos os anfitriões
  em 127.0.0.1, localhost ou ::1) e uma base cujo nome acabe em _local. A guarda corre
  ANTES de se criar qualquer cliente Mongo.
- Cria 4 contas "(demo)" @example.com e 3 membros do CRM. É idempotente: o que já existe
  fica como está; sem --repor as palavras-passe nunca mudam.
- --repor gera palavras-passe novas para as 4 contas de demonstração.
- As palavras-passe novas vão para ~/.config/lisbonb-crm-local/credenciais.txt (modo 600);
  no ecrã só aparece o caminho desse ficheiro.
"""
import argparse
import os
import secrets
import string
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import bcrypt
from dotenv import dotenv_values
from pymongo import MongoClient, uri_parser
from pymongo.errors import ServerSelectionTimeoutError

COLECAO_CONTAS = "users"
COLECAO_MEMBROS = "crm_membros"  # na T1.2 confirma-se contra crm.db.COLECOES["membros"]
CRIADO_POR = "seed-local"
PREFIXO_URI = "mongodb://"
ANFITRIOES_LOCAIS = frozenset({"127.0.0.1", "localhost", "::1"})
SUFIXO_BASE = "_local"
ESPERA_MONGO_MS = 3000
FICHEIRO_CREDENCIAIS = Path.home() / ".config" / "lisbonb-crm-local" / "credenciais.txt"

MENSAGEM_RECUSA = (
    "Recusado: o seed só corre num MongoDB local (mongodb://127.0.0.1) e numa base *_local."
)
MENSAGEM_SEM_MONGO = (
    "Erro: o MongoDB local não respondeu (está a correr? "
    "brew services start mongodb/brew/mongodb-community@8.0)."
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


# ---------------------------------------------------------------- guarda

def uri_e_local(uri) -> bool:
    """Verdadeiro só para mongodb:// com TODOS os anfitriões locais.

    Recusa-se o que não começa por mongodb:// antes de interpretar o URI (um mongodb+srv://
    faria uma consulta DNS). Qualquer erro ao interpretar conta como não local.
    """
    if not isinstance(uri, str) or not uri.startswith(PREFIXO_URI):
        return False
    try:
        nos = uri_parser.parse_uri(uri)["nodelist"]
    except Exception:
        return False
    return bool(nos) and all(
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
    parser = argparse.ArgumentParser(description="Seed local do CRM (contas de demonstração).")
    parser.add_argument("--env-file", required=True, help="ficheiro de ambiente local (ex.: .env.local)")
    parser.add_argument("--repor", action="store_true",
                        help="gera palavras-passe novas para as contas de demonstração")
    args = parser.parse_args(argv)

    caminho_env = Path(args.env_file)
    if not caminho_env.is_file():
        raise SystemExit(f"Recusado: o ficheiro de ambiente não existe: {caminho_env}")
    uri, nome = verificar_ambiente(dotenv_values(caminho_env))

    cliente = MongoClient(uri, serverSelectionTimeoutMS=ESPERA_MONGO_MS)
    try:
        novas = aplicar_contas(cliente[nome], datetime.now(timezone.utc), gerar_palavra_passe,
                               repor=args.repor)
    except ServerSelectionTimeoutError:
        raise SystemExit(MENSAGEM_SEM_MONGO) from None
    finally:
        cliente.close()

    if novas:
        escrever_credenciais(FICHEIRO_CREDENCIAIS, novas)
        print(f"Palavras-passe das contas de demonstração ({len(novas)} novas): {FICHEIRO_CREDENCIAIS}")
    else:
        print(f"Contas de demonstração já existiam; palavras-passe sem alteração em: {FICHEIRO_CREDENCIAIS} "
              "(use --repor para gerar novas).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
