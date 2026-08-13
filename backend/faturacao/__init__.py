"""Módulo Faturação L'Açaí — POS e backoffice das lojas.

Vive como pacote próprio (e não dentro do server.py) por duas razões: o server.py
já tem 8150 linhas, e um pacote isolado significa que uma avaria aqui não derruba
o RH, o Financeiro nem o Marketing.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/faturacao", tags=["faturacao"])


@router.get("/saude")
async def saude():
    """Diz que o módulo está montado. Não toca na base de dados de propósito."""
    return {"estado": "ok", "modulo": "faturacao"}
