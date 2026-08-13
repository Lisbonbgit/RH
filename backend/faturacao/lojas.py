"""Lojas e Caixas — Configuração do módulo Faturação.

Uma loja tem uma ou mais caixas. A caixa é o sítio onde a sessão de dinheiro
vive (Plano 2). O register_id do Vendus NÃO aparece aqui de propósito: é um só
para todo o sistema e vive em variável de ambiente.
"""
import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from .auth import gestor_atual
from .db import COLECOES, obter_db

router = APIRouter()

_CP = re.compile(r"^\d{4}-\d{3}$")


class LojaEntrada(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    morada: Optional[str] = None
    codigo_postal: Optional[str] = None
    localidade: Optional[str] = None
    email: Optional[str] = None
    telefone: Optional[str] = None
    cae: Optional[str] = None
    empresa_id: Optional[str] = None
    rh_location_id: Optional[str] = None
    ativa: bool = True

    @field_validator("codigo_postal")
    @classmethod
    def _valida_cp(cls, v):
        if v and not _CP.match(v):
            raise ValueError("Código postal tem de ser no formato 0000-000")
        return v


class CaixaEntrada(BaseModel):
    nome: str = Field(min_length=1, max_length=60)
    ativa: bool = True


def _agora():
    return datetime.now(timezone.utc).isoformat()


@router.get("/lojas")
async def listar_lojas(_: dict = Depends(gestor_atual)) -> List[dict]:
    db = obter_db()
    return await db[COLECOES["lojas"]].find({}, {"_id": 0}).sort("nome", 1).to_list(500)


@router.post("/lojas", status_code=201)
async def criar_loja(dados: LojaEntrada, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    loja = dados.model_dump()
    loja.update({"id": str(uuid.uuid4()), "criada_em": _agora()})
    await db[COLECOES["lojas"]].insert_one(dict(loja))
    return loja


@router.get("/lojas/{loja_id}")
async def obter_loja(loja_id: str, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    loja = await db[COLECOES["lojas"]].find_one({"id": loja_id}, {"_id": 0})
    if not loja:
        raise HTTPException(status_code=404, detail="Loja não encontrada")
    return loja


@router.put("/lojas/{loja_id}")
async def editar_loja(loja_id: str, dados: LojaEntrada, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    r = await db[COLECOES["lojas"]].update_one({"id": loja_id}, {"$set": dados.model_dump()})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Loja não encontrada")
    return await db[COLECOES["lojas"]].find_one({"id": loja_id}, {"_id": 0})


@router.delete("/lojas/{loja_id}")
async def apagar_loja(loja_id: str, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    if await db[COLECOES["caixas"]].count_documents({"loja_id": loja_id}) > 0:
        raise HTTPException(status_code=409, detail="A loja ainda tem caixas. Apague-as primeiro.")
    await db[COLECOES["lojas"]].delete_one({"id": loja_id})
    return {"apagada": True}


@router.get("/lojas/{loja_id}/caixas")
async def listar_caixas(loja_id: str, _: dict = Depends(gestor_atual)) -> List[dict]:
    db = obter_db()
    return await db[COLECOES["caixas"]].find({"loja_id": loja_id}, {"_id": 0}).to_list(100)


@router.post("/lojas/{loja_id}/caixas", status_code=201)
async def criar_caixa(loja_id: str, dados: CaixaEntrada, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    if not await db[COLECOES["lojas"]].find_one({"id": loja_id}):
        raise HTTPException(status_code=404, detail="Loja não encontrada")
    caixa = dados.model_dump()
    caixa.update({"id": str(uuid.uuid4()), "loja_id": loja_id, "criada_em": _agora()})
    await db[COLECOES["caixas"]].insert_one(dict(caixa))
    return caixa


@router.put("/caixas/{caixa_id}")
async def editar_caixa(caixa_id: str, dados: CaixaEntrada, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    r = await db[COLECOES["caixas"]].update_one({"id": caixa_id}, {"$set": dados.model_dump()})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Caixa não encontrada")
    return await db[COLECOES["caixas"]].find_one({"id": caixa_id}, {"_id": 0})


@router.delete("/caixas/{caixa_id}")
async def apagar_caixa(caixa_id: str, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    await db[COLECOES["caixas"]].delete_one({"id": caixa_id})
    return {"apagada": True}
