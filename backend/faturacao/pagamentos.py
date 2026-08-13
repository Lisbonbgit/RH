"""Tipos de pagamento do POS.

Um tipo tem um nome livre (o que a funcionária vê: "Glovo", "Uber Eats") e um
código fiscal do Vendus por trás (TB, NU, CD...). É por isso que "Glovo" pode ser
um botão próprio sem deixar de ser transferência bancária aos olhos do fisco.

NUNCA escrevemos nos métodos de pagamento do Vendus — só mapeamos.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from .auth import gestor_atual
from .db import COLECOES, obter_db

router = APIRouter()

# Códigos documentados em https://www.vendus.pt/ws/v1.1/registers/movements.doc
TIPOS_FISCAIS = {
    "NU": "Numerário",
    "CD": "Cartão de Débito",
    "CC": "Cartão de Crédito",
    "TB": "Transferência Bancária",
    "MB": "Referência MB",
    "MBWAY": "MB Way",
    "CH": "Cheque",
    "TR": "Ticket Restaurante",
    "CO": "Cartão Oferta",
    "CS": "Compensação de Saldos",
    "OU": "Outro",
}


class TipoPagamentoEntrada(BaseModel):
    nome: str = Field(min_length=1, max_length=60)
    tipo_fiscal: str
    da_troco: bool = False
    ordem: int = 0
    ativo: bool = True
    vendus_payment_method_id: Optional[str] = None

    @field_validator("tipo_fiscal")
    @classmethod
    def _valida(cls, v):
        if v not in TIPOS_FISCAIS:
            raise ValueError("Tipo fiscal desconhecido: " + str(v))
        return v


@router.get("/tipos-pagamento")
async def listar(_: dict = Depends(gestor_atual)) -> List[dict]:
    db = obter_db()
    return await db[COLECOES["tipos_pagamento"]].find({}, {"_id": 0}).sort("ordem", 1).to_list(100)


@router.get("/tipos-pagamento/codigos-fiscais")
async def codigos(_: dict = Depends(gestor_atual)) -> dict:
    return TIPOS_FISCAIS


@router.post("/tipos-pagamento", status_code=201)
async def criar(dados: TipoPagamentoEntrada, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    tipo = dados.model_dump()
    tipo.update({"id": str(uuid.uuid4()), "protegido": False,
                 "criado_em": datetime.now(timezone.utc).isoformat()})
    await db[COLECOES["tipos_pagamento"]].insert_one(dict(tipo))
    return tipo


@router.put("/tipos-pagamento/{tipo_id}")
async def editar(tipo_id: str, dados: TipoPagamentoEntrada, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    atual = await db[COLECOES["tipos_pagamento"]].find_one({"id": tipo_id}, {"_id": 0})
    if not atual:
        raise HTTPException(status_code=404, detail="Tipo de pagamento não encontrado")
    if atual.get("protegido"):
        raise HTTPException(
            status_code=409,
            detail="Este tipo de pagamento é usado pela app L'Açaí e não pode ser alterado.",
        )
    await db[COLECOES["tipos_pagamento"]].update_one({"id": tipo_id}, {"$set": dados.model_dump()})
    return await db[COLECOES["tipos_pagamento"]].find_one({"id": tipo_id}, {"_id": 0})


@router.delete("/tipos-pagamento/{tipo_id}")
async def apagar(tipo_id: str, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    atual = await db[COLECOES["tipos_pagamento"]].find_one({"id": tipo_id})
    if atual and atual.get("protegido"):
        raise HTTPException(
            status_code=409,
            detail="Este tipo de pagamento é usado pela app L'Açaí e não pode ser apagado.",
        )
    await db[COLECOES["tipos_pagamento"]].delete_one({"id": tipo_id})
    return {"apagado": True}
