"""`/api/crm/membros` — quem entra no CRM e com que perfil (só admin do CRM).

Desenho §3.1; plano §4; dossiê §4 e §6. Nesta tarefa (T1.6) só as leituras:

- `GET /membros`: o admin master primeiro — admin do CRM sem linha em
  `crm_membros`, por isso `id: null` —, depois os membros por nome sem
  acentos nem maiúsculas (`dominio.texto.chave_comparacao`; empate pelo `id`,
  como o `ORDER BY nome, id` do CRM autónomo). O nome, o email e o tipo de
  conta vêm da conta do portal. Um membro cuja conta foi apagada fica no fim,
  com `conta_existe: false` e nome/email/tipo de conta a null: já não entra
  (a sessão dá 401), e o admin vê-o para o retirar.
- `GET /membros/candidatos`: as contas do portal que ainda não são membros nem
  são o admin master — a lista de onde o admin escolhe quem juntar.

Das contas (`users`, do portal) pede-se só `id`, `name`, `email` e `role`
(`PROJECAO_CONTAS`): a `password` (o hash) nunca sai da base. As escritas
(POST, PATCH, DELETE) chegam na T1.7, com `/membros/{membro_id}` declarada
DEPOIS de `/membros/candidatos` (senão "candidatos" podia ser lido como id).
"""
from typing import Dict, List

from fastapi import APIRouter, Depends

from . import db as bd
from .auth import SO_ADMIN, e_admin_master, email_admin_master
from .dominio.membros import erro_perfil, tipo_conta
from .dominio.texto import chave_comparacao

router = APIRouter()

# O mínimo de cada conta do portal que o CRM mostra. Nunca a `password`.
PROJECAO_CONTAS = {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1}

# Teto das leituras de listas: o volume esperado é de dezenas de membros e de
# contas do portal (centenas no máximo); o teto só trava um caso patológico.
LIMITE_LISTA = 5000


def _texto(valor):
    """O valor se for texto; senão None (uma conta mal formada não rebenta)."""
    return valor if isinstance(valor, str) else None


def _id_de_texto(valor) -> bool:
    return isinstance(valor, str) and valor != ""


def _dados_conta(conta) -> Dict:
    """`{nome, email, tipo_conta}` de uma conta de `users` (ou tudo a null)."""
    conta = conta or {}
    return {
        "nome": _texto(conta.get("name")),
        "email": _texto(conta.get("email")),
        "tipo_conta": tipo_conta(conta.get("role")),
    }


def _chave_nome(nome) -> str:
    return chave_comparacao(nome) if isinstance(nome, str) else ""


async def _conta_admin_master(base):
    """A conta do admin master, ou None. Com ADMIN_EMAIL vazio não se procura:
    `{"email": ""}` apanhava contas sem email, e um email vazio nunca é o
    admin master (`auth.e_admin_master`)."""
    email = email_admin_master()
    if email == "":
        return None
    return await base.users.find_one({"email": email}, PROJECAO_CONTAS)


@router.get("/membros")
async def listar_membros(admin: Dict = Depends(SO_ADMIN)) -> List[Dict]:
    """`[{id|null, user_id, nome, email, tipo_conta, perfil, admin_master,
    conta_existe, criado_em}]`, com o admin master primeiro."""
    base = bd.obter_db()
    linhas = await base[bd.COLECOES["membros"]].find(
        {}, {"_id": 0, "id": 1, "user_id": 1, "perfil": 1, "criado_em": 1}
    ).to_list(LIMITE_LISTA)

    ids_contas = sorted({linha.get("user_id") for linha in linhas if _id_de_texto(linha.get("user_id"))})
    contas = {}
    if ids_contas:
        for conta in await base.users.find({"id": {"$in": ids_contas}}, PROJECAO_CONTAS).to_list(LIMITE_LISTA):
            contas[conta.get("id")] = conta

    admin_master = await _conta_admin_master(base)
    id_admin_master = admin_master.get("id") if admin_master else None
    primeira = {
        "id": None,
        "user_id": _texto(id_admin_master),
        **_dados_conta(admin_master),
        "perfil": "admin",
        "admin_master": True,
        "conta_existe": admin_master is not None,
        "criado_em": None,
    }

    membros = []
    for linha in linhas:
        user_id = linha.get("user_id")
        # Uma linha antiga do próprio admin master (de antes de o ADMIN_EMAIL
        # ser esta conta) não o repete: ele já é a primeira linha, sempre admin.
        if id_admin_master is not None and user_id == id_admin_master:
            continue
        conta = contas.get(user_id) if _id_de_texto(user_id) else None
        perfil = linha.get("perfil")
        membros.append({
            "id": linha.get("id"),
            "user_id": user_id,
            **_dados_conta(conta),
            # Fechado por omissão, como no /eu: um perfil que não é dos três
            # não dá acesso e sai como null; a linha fica para o admin a
            # corrigir ou retirar.
            "perfil": perfil if erro_perfil(perfil) is None else None,
            "admin_master": False,
            "conta_existe": conta is not None,
            "criado_em": linha.get("criado_em"),
        })
    membros.sort(key=lambda m: (not m["conta_existe"], _chave_nome(m["nome"]), str(m["id"] or "")))
    return [primeira] + membros


@router.get("/membros/candidatos")
async def listar_candidatos(admin: Dict = Depends(SO_ADMIN)) -> List[Dict]:
    """`[{id, nome, email, tipo_conta}]` das contas do portal que podem entrar,
    por nome (sem acentos nem maiúsculas; empate pelo `id`)."""
    base = bd.obter_db()
    linhas = await base[bd.COLECOES["membros"]].find({}, {"_id": 0, "user_id": 1}).to_list(LIMITE_LISTA)
    # Todas as linhas contam, mesmo com um perfil desconhecido: o índice único
    # de `user_id` recusava juntar a conta outra vez (corrige-se o perfil).
    ja_membros = {linha["user_id"] for linha in linhas if _id_de_texto(linha.get("user_id"))}
    contas = await base.users.find({}, PROJECAO_CONTAS).to_list(LIMITE_LISTA)
    candidatos = [
        {"id": conta["id"], **_dados_conta(conta)}
        for conta in contas
        # Sem `id` de texto não se pode juntar (o POST precisa do `user_id`).
        if _id_de_texto(conta.get("id")) and conta["id"] not in ja_membros and not e_admin_master(conta)
    ]
    candidatos.sort(key=lambda c: (_chave_nome(c["nome"]), c["id"]))
    return candidatos
