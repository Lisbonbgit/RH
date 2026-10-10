"""Módulo CRM Purple House — mapa das lojas, fases e (mais tarde) rotas.

Vive como pacote próprio (e não dentro do server.py), no molde de `faturacao/`
e `plataformas/`: o server.py já é enorme e partilhado, e um pacote isolado
significa que uma avaria aqui não derruba o RH, o Financeiro nem a Faturação.
O server.py só monta o router e chama o arranque (T1.9); tudo o resto do CRM
(base, autenticação dos membros, regras de negócio) fica cá dentro.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/crm", tags=["crm"])


@router.get("/saude")
async def saude():
    """Diz que o módulo está montado. Pública e não toca na base de propósito."""
    return {"estado": "ok", "modulo": "crm"}
