"""Autenticação dos membros do CRM, sobre a sessão do portal.

O CRM não tem login nem sessões próprias. Assenta em
`faturacao.auth.utilizador_atual` (como o pacote `plataformas`) e herda dele,
a cada pedido: o papel e o email lidos da BASE, a recusa de contas apagadas
(401 "Sessão terminada") e a recusa de sessões anteriores a uma troca de
palavra-passe. Aqui só se acrescenta "é membro do CRM, e com que perfil?"
(desenho §4.2; dossiê §4):

- **Admin master** — a conta cujo email (o da base) é igual a `ADMIN_EMAIL` —
  é sempre `admin` do CRM, sem linha em `crm_membros`. O CRM nunca fica sem
  admin, por isso não há regra do "último admin".
- Os outros são membros por uma linha `{user_id, perfil}` em `crm_membros`.
  O papel no portal (gestor ou colaborador) não conta para o CRM.

Os 403 do CRM têm a forma `{"codigo", "mensagem"}` (crm/erros.py); os 401/403
herdados da sessão continuam em texto. A base lê-se sempre por `bd.obter_db()`
(os testes trocam-na num só sítio).
"""
import os
from typing import Dict

from fastapi import Depends

from faturacao.auth import utilizador_atual

from . import db as bd
from .dominio.membros import PERFIS, erro_perfil
from .erros import erro

# Valor por omissão do ADMIN_EMAIL, copiado de server.py:61
# (`os.environ.get('ADMIN_EMAIL', 'geral@olacai.com')`). A paridade é
# deliberada: se este módulo e o server.py divergirem no valor por omissão, o
# portal continua a tratar como admin master a conta do seu próprio valor
# assim que ADMIN_EMAIL não estiver definido no ambiente, e o CRM passa a
# negar-lhe a área de admin — ou a dá-la a outra conta. O teste lê o server.py
# como texto e falha se os dois se separarem.
ADMIN_EMAIL_POR_OMISSAO = "geral@olacai.com"

MENSAGEM_SEM_ACESSO = "Sem acesso ao CRM."
MENSAGEM_SEM_PERMISSAO = "Sem permissão para esta ação."


def email_admin_master() -> str:
    """O email do admin master, lido do ambiente a cada chamada."""
    return os.environ.get("ADMIN_EMAIL", ADMIN_EMAIL_POR_OMISSAO)


def _e_admin_master(utilizador: Dict) -> bool:
    """Compara tal e qual, como o server.py (`user["email"] == MASTER_ADMIN_EMAIL`):
    o CRM não dá admin a quem o portal não reconhece como admin master. Um
    email vazio nunca conta (um ADMIN_EMAIL vazio por engano não faz de uma
    conta sem email o admin master)."""
    email = utilizador.get("email")
    return isinstance(email, str) and email != "" and email == email_admin_master()


async def estado_crm(utilizador: Dict) -> Dict:
    """`{membro, perfil, admin_master}` da sessão `utilizador` (o dicionário de
    `utilizador_atual`, com `user_id` e o `email` da base).

    - admin master → `{True, "admin", True}`, sem ler `crm_membros`;
    - linha com um dos PERFIS → `{True, perfil, False}`;
    - sem linha, com um perfil que não é dos três (fechado por omissão) ou
      sem `user_id` de texto → `{False, None, False}`. Sem `user_id` nem se
      pergunta: `{"user_id": None}` no Mongo apanhava linhas sem `user_id`.
    """
    if _e_admin_master(utilizador):
        return {"membro": True, "perfil": "admin", "admin_master": True}
    user_id = utilizador.get("user_id")
    if not isinstance(user_id, str) or user_id == "":
        return {"membro": False, "perfil": None, "admin_master": False}
    linha = await bd.obter_db()[bd.COLECOES["membros"]].find_one(
        {"user_id": user_id}, {"_id": 0, "perfil": 1}
    )
    perfil = (linha or {}).get("perfil")
    if erro_perfil(perfil) is not None:
        return {"membro": False, "perfil": None, "admin_master": False}
    return {"membro": True, "perfil": perfil, "admin_master": False}


async def membro_crm_atual(utilizador: Dict = Depends(utilizador_atual)) -> Dict:
    """Dependência das rotas do CRM: a sessão do portal mais `crm_perfil` e
    `crm_admin_master` (numa cópia; o dicionário da sessão não muda).
    Não-membro → 403 `sem_acesso_crm`. Lido da base a cada pedido: retirar um
    membro corta-lhe o acesso no pedido seguinte."""
    estado = await estado_crm(utilizador)
    if not estado["membro"]:
        raise erro(403, "sem_acesso_crm", MENSAGEM_SEM_ACESSO)
    return {**utilizador, "crm_perfil": estado["perfil"], "crm_admin_master": estado["admin_master"]}


def exigir_perfil(*perfis: str):
    """Dependência que deixa passar só os membros com um destes perfis do CRM
    (os outros → 403 `sem_permissao`) e devolve o membro.

    A função devolvida tem o atributo `perfis_crm` (frozenset), que o teste de
    proteção das rotas (T1.8) compara com a tabela de perfis por rota. Um
    perfil que não existe é um erro de programação (ValueError) apanhado ao
    importar o módulo das rotas, e não uma rota que não deixa entrar ninguém.
    """
    if not perfis:
        raise ValueError("exigir_perfil precisa de pelo menos um perfil")
    desconhecidos = [p for p in perfis if erro_perfil(p) is not None]
    if desconhecidos:
        raise ValueError(f"Perfis do CRM desconhecidos: {desconhecidos!r} (válidos: {PERFIS})")
    permitidos = frozenset(perfis)

    async def guarda(membro: Dict = Depends(membro_crm_atual)) -> Dict:
        if membro["crm_perfil"] not in permitidos:
            raise erro(403, "sem_permissao", MENSAGEM_SEM_PERMISSAO)
        return membro

    guarda.perfis_crm = permitidos
    nome = "exigir_perfil_" + "_".join(p for p in PERFIS if p in permitidos)
    guarda.__name__ = guarda.__qualname__ = nome
    return guarda


# Os perfis de rota da F1 e da F2. O motorista não entra no /crm nem usa rotas
# da F2: as permissões do terreno chegam na F4 (não antecipar).
SO_ADMIN = exigir_perfil("admin")
ESCRITORIO = exigir_perfil("admin", "utilizador")
