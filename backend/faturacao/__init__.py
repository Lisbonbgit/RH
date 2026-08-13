"""Módulo Faturação L'Açaí — POS e backoffice das lojas.

Vive como pacote próprio (e não dentro do server.py) por duas razões: o server.py
já tem 8150 linhas, e um pacote isolado significa que uma avaria aqui não derruba
o RH, o Financeiro nem o Marketing.
"""
from fastapi import APIRouter

from .db import COLECOES, criar_indices, obter_db  # noqa: F401

router = APIRouter(prefix="/api/faturacao", tags=["faturacao"])

from .lojas import router as _lojas
router.include_router(_lojas)

from .pagamentos import router as _pagamentos
router.include_router(_pagamentos)

from .utilizadores import router as _utilizadores
router.include_router(_utilizadores)


async def arrancar():
    """Chamado pelo server.py no arranque."""
    await criar_indices(obter_db())


@router.get("/saude")
async def saude():
    """Diz que o módulo está montado. Não toca na base de dados de propósito."""
    return {"estado": "ok", "modulo": "faturacao"}
