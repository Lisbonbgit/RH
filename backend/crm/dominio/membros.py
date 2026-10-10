"""Regras dos membros do CRM: os perfis e o tipo de conta do portal.

Qualquer conta do portal (gestor ou colaborador) pode ser membro do CRM, com
um perfil só do CRM (desenho §4.2; dossiê §4). O papel no portal não conta
para o CRM — o `tipo_conta` é só a etiqueta que o admin vê ao escolher.

O corpo do `POST /membros` (`{user_id, perfil}`) valida-se aqui, só no
formato; se a conta existe, se é o admin master ou se já é membro decide a
rota (crm/membros.py), que é quem lê a base.
"""
from faturacao.auth import PERFIS_GESTAO

from .texto import aparar

# Os perfis do CRM, por esta ordem (é a ordem em que aparecem nos ecrãs):
# - admin: tudo, incluindo membros, regiões e definições;
# - utilizador: lojas e mapa (F2), planear rotas e encomendas (F3, F5);
# - motorista: rota do dia e o terreno (F4); na F1–F2 não entra no /crm.
PERFIS = ("admin", "utilizador", "motorista")

MENSAGEM_PERFIL = "Escolha um perfil: admin, utilizador ou motorista."
MENSAGEM_ESCOLHER_CONTA = "Escolha uma conta do portal."
MENSAGEM_CONTA_INEXISTENTE = "A conta não existe."


def erro_perfil(perfil) -> "str | None":
    """None se `perfil` for um dos PERFIS, tal e qual (texto, minúsculas, sem
    espaços); senão a mensagem para o campo `perfil`."""
    return None if isinstance(perfil, str) and perfil in PERFIS else MENSAGEM_PERFIL


def tipo_conta(papel) -> "str | None":
    """O tipo de conta do portal a partir do `role` da conta.

    - os papéis de gestão do portal (faturacao.auth.PERFIS_GESTAO, cópia do
      MANAGER_ROLES do server.py: admin, gerente, contabilista) → "gestor";
    - qualquer outro texto → "colaborador": é o que o portal faz, que manda
      para a área do colaborador tudo o que não é gestão (App.js);
    - sem papel, ou um papel que não é texto → None.
    """
    if not isinstance(papel, str):
        return None
    return "gestor" if papel in PERFIS_GESTAO else "colaborador"


def erro_conta(user_id) -> "str | None":
    """None se foi escolhida uma conta (`user_id` em texto, com alguma coisa
    além de espaços); senão a mensagem para o campo `user_id`.

    O id não se apara nem se normaliza: é comparado tal e qual com o `id` das
    contas, e " u-1 " não é a conta "u-1" (dá "A conta não existe.").
    """
    return None if isinstance(user_id, str) and aparar(user_id) != "" else MENSAGEM_ESCOLHER_CONTA


def erros_membro_novo(corpo: dict) -> dict:
    """Os erros de campo do corpo do `POST /membros`, `{campo: mensagem}`, pela
    ordem do formulário (a conta, depois o perfil); `{}` se não houver. As
    outras chaves do corpo ignoram-se."""
    erros = {"user_id": erro_conta(corpo.get("user_id")), "perfil": erro_perfil(corpo.get("perfil"))}
    return {campo: mensagem for campo, mensagem in erros.items() if mensagem is not None}
