"""`/api/crm/membros` — quem entra no CRM e com que perfil (só admin do CRM).

Desenho §3.1; plano §4; dossiê §4 e §6. As leituras (T1.6):

- `GET /membros`: o admin master primeiro — admin do CRM sem linha em
  `crm_membros`, por isso `id: null` —, depois os membros por nome sem
  acentos nem maiúsculas (`dominio.texto.chave_comparacao`; empate pelo `id`,
  como o `ORDER BY nome, id` do CRM autónomo). O nome, o email e o tipo de
  conta vêm da conta do portal. Um membro cuja conta foi apagada fica no fim,
  com `conta_existe: false` e nome/email/tipo de conta a null: já não entra
  (a sessão dá 401), e o admin vê-o para o retirar.
- `GET /membros/candidatos`: as contas do portal que ainda não são membros nem
  são o admin master — a lista de onde o admin escolhe quem juntar.

As escritas (T1.7), todas com a guarda de perfil declarada ANTES de
`corpo_json` (sem sessão e com JSON partido → 403, nunca 400):

- `POST /membros` `{user_id, perfil}` → 201 com a mesma forma de uma linha do
  `GET /membros`. Ordem: campos (422) → a conta existe (422 em `user_id`) →
  é o admin master (409 `admin_master`: é sempre admin, sem linha) → já é
  membro (409 `ja_membro`). Grava `{id (uuid4), user_id, perfil, criado_em,
  criado_por}`; as outras chaves do corpo ignoram-se.
- `PATCH /membros/{membro_id}` `{perfil}` → 200 com a linha. O corpo valida-se
  antes de procurar o membro (422 antes do 404, como o autónomo). Uma linha
  antiga do admin master → 409 `admin_master`. Não grava `atualizado_em`: os
  membros não têm bloqueio otimista, e o formato de 6 casas só chega com o
  `relogio.carimbo` (T2.8).
- `DELETE /membros/{membro_id}` → `{retirado: true}`; outra vez → 404. Um admin
  pode mudar o próprio perfil ou retirar-se: o admin master é sempre admin,
  por isso não há regra do "último admin".

Declaradas DEPOIS de `/membros/candidatos`: senão "candidatos" podia ser lido
como o id de um membro.

Das contas (`users`, do portal) pede-se só `id`, `name`, `email` e `role`
(`PROJECAO_CONTAS`): a `password` (o hash) nunca sai da base.
"""
import uuid
from typing import Dict, List

from fastapi import APIRouter, Depends
from pymongo.errors import DuplicateKeyError

from . import db as bd
from . import relogio
from .auth import SO_ADMIN, e_admin_master, email_admin_master
from .dominio.membros import MENSAGEM_CONTA_INEXISTENTE, erro_perfil, erros_membro_novo, tipo_conta
from .dominio.texto import chave_comparacao
from .erros import erro, nao_encontrado, validacao
from .pedidos import corpo_json

router = APIRouter()

# O mínimo de cada conta do portal que o CRM mostra. Nunca a `password`.
PROJECAO_CONTAS = {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1}

# O que se lê de uma linha de `crm_membros` para a mostrar.
PROJECAO_MEMBRO = {"_id": 0, "id": 1, "user_id": 1, "perfil": 1, "criado_em": 1}

# Teto das leituras de listas: o volume esperado é de dezenas de membros e de
# contas do portal (centenas no máximo); o teto só trava um caso patológico.
LIMITE_LISTA = 5000

MENSAGEM_NAO_ENCONTRADO = "Membro não encontrado."
MENSAGEM_JA_MEMBRO = "Esta pessoa já é membro do CRM."
MENSAGEM_ADMIN_MASTER = "O administrador principal já é admin do CRM."


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


def _linha_membro(linha, conta) -> Dict:
    """Uma linha de `crm_membros` na forma da API (a do `GET /membros`), com
    os dados da `conta` do portal (None → conta apagada)."""
    perfil = linha.get("perfil")
    return {
        "id": linha.get("id"),
        "user_id": linha.get("user_id"),
        **_dados_conta(conta),
        # Fechado por omissão, como no /eu: um perfil que não é dos três
        # não dá acesso e sai como null; a linha fica para o admin a
        # corrigir ou retirar.
        "perfil": perfil if erro_perfil(perfil) is None else None,
        "admin_master": False,
        "conta_existe": conta is not None,
        "criado_em": linha.get("criado_em"),
    }


def _chave_nome(nome) -> str:
    return chave_comparacao(nome) if isinstance(nome, str) else ""


async def _conta(base, user_id):
    """A conta `user_id` do portal (projeção mínima), ou None. Sem id de texto
    nem se pergunta: `{"id": None}` apanhava contas sem `id`."""
    if not _id_de_texto(user_id):
        return None
    return await base.users.find_one({"id": user_id}, PROJECAO_CONTAS)


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
    linhas = await base[bd.COLECOES["membros"]].find({}, PROJECAO_MEMBRO).to_list(LIMITE_LISTA)

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
        membros.append(_linha_membro(linha, conta))
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


@router.post("/membros", status_code=201)
async def adicionar_membro(admin: Dict = Depends(SO_ADMIN), corpo: Dict = Depends(corpo_json)) -> Dict:
    """`{user_id, perfil}` → 201 com a linha do membro novo."""
    campos = erros_membro_novo(corpo)
    if campos:
        raise validacao(campos)
    user_id, perfil = corpo["user_id"], corpo["perfil"]
    base = bd.obter_db()
    conta = await _conta(base, user_id)
    if conta is None:
        raise validacao({"user_id": MENSAGEM_CONTA_INEXISTENTE})
    if e_admin_master(conta):
        raise erro(409, "admin_master", MENSAGEM_ADMIN_MASTER)
    membros = base[bd.COLECOES["membros"]]
    # Verifica-se antes de gravar mesmo havendo o índice único de `user_id`:
    # se o arranque não o conseguiu criar (o CRM arranca sem índices), esta é
    # a única defesa. Qualquer linha conta, mesmo com um perfil desconhecido
    # (corrige-se com o PATCH).
    if await membros.find_one({"user_id": user_id}, {"_id": 0, "id": 1}) is not None:
        raise erro(409, "ja_membro", MENSAGEM_JA_MEMBRO)
    linha = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "perfil": perfil,
        "criado_em": relogio.instante(),
        "criado_por": admin["user_id"],
    }
    try:
        # O insert_one acrescenta `_id` (ObjectId) a `linha`; não sai na
        # resposta, porque `_linha_membro` só copia as chaves da API.
        await membros.insert_one(linha)
    except DuplicateKeyError:
        # A corrida: outro admin juntou a mesma conta depois da verificação.
        # O `id` é um uuid4 novo e o `_id` vem do driver, por isso a chave
        # repetida é o `user_id`.
        raise erro(409, "ja_membro", MENSAGEM_JA_MEMBRO) from None
    return _linha_membro(linha, conta)


@router.patch("/membros/{membro_id}")
async def mudar_perfil_membro(
    membro_id: str, admin: Dict = Depends(SO_ADMIN), corpo: Dict = Depends(corpo_json)
) -> Dict:
    """`{perfil}` → 200 com a linha do membro. Só o perfil muda; as outras
    chaves do corpo ignoram-se."""
    mensagem = erro_perfil(corpo.get("perfil"))
    if mensagem is not None:
        raise validacao({"perfil": mensagem})
    perfil = corpo["perfil"]
    base = bd.obter_db()
    membros = base[bd.COLECOES["membros"]]
    linha = await membros.find_one({"id": membro_id}, PROJECAO_MEMBRO)
    if linha is None:
        raise nao_encontrado(MENSAGEM_NAO_ENCONTRADO)
    conta = await _conta(base, linha.get("user_id"))
    if conta is not None and e_admin_master(conta):
        # Uma linha antiga do admin master: ele é sempre admin, sem linha (a
        # lista nem a mostra). Retirá-la é permitido; mudar-lhe o perfil não.
        raise erro(409, "admin_master", MENSAGEM_ADMIN_MASTER)
    resultado = await membros.update_one({"id": membro_id}, {"$set": {"perfil": perfil}})
    if resultado.matched_count == 0:
        # Retirado por outro admin entre a leitura e a escrita.
        raise nao_encontrado(MENSAGEM_NAO_ENCONTRADO)
    return _linha_membro({**linha, "perfil": perfil}, conta)


@router.delete("/membros/{membro_id}")
async def retirar_membro(membro_id: str, admin: Dict = Depends(SO_ADMIN)) -> Dict:
    """→ `{retirado: true}`. O acesso corta-se no pedido seguinte (o perfil
    lê-se da base a cada pedido)."""
    resultado = await bd.obter_db()[bd.COLECOES["membros"]].delete_one({"id": membro_id})
    if resultado.deleted_count == 0:
        raise nao_encontrado(MENSAGEM_NAO_ENCONTRADO)
    return {"retirado": True}
