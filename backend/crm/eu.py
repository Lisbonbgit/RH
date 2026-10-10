"""`GET /api/crm/eu` — "sou membro do CRM, e com que perfil?" (desenho §4.2).

A única rota da família "qualquer sessão válida" (teste de proteção, T1.8):
depende de `faturacao.auth.utilizador_atual` e NUNCA de `membro_crm_atual`.
O frontend pergunta isto a todas as sessões, uma vez por token, para decidir
se mostra o CRM (`lib/crm/eu.js`); quem não é membro recebe
`{"membro": false, "perfil": null, "admin_master": false}` e nunca 403.

Os 401/403 da sessão são os herdados (sem cabeçalho, token inválido, conta
apagada, sessão anterior à troca de palavra-passe). Uma falha da base sai como
erro (500) e não como "não-membro": o frontend esconde o CRM e volta a
perguntar no pedido seguinte, em vez de guardar um falso "não" para o token.
"""
from typing import Dict

from fastapi import APIRouter, Depends

from faturacao.auth import utilizador_atual

from .auth import estado_crm

router = APIRouter()


@router.get("/eu")
async def eu(utilizador: Dict = Depends(utilizador_atual)):
    """`{membro, perfil, admin_master}` da sessão (regras em `auth.estado_crm`)."""
    return await estado_crm(utilizador)
