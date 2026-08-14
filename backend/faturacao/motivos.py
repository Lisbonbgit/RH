"""Motivos para emissão de notas de crédito.

Em Portugal o motivo vai em texto livre no campo `notes` do documento — o campo
`ncr_id` da API do Vendus está marcado como específico de Cabo Verde.
Usado no Plano 2, configurado aqui.
"""
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .auth import gestor_atual
from .db import COLECOES, obter_db

router = APIRouter()


class MotivoEntrada(BaseModel):
    texto: str = Field(min_length=1, max_length=200)


@router.get("/motivos-nc")
async def listar(_: dict = Depends(gestor_atual)) -> List[dict]:
    db = obter_db()
    return await db[COLECOES["motivos_nc"]].find({}, {"_id": 0}).sort("texto", 1).to_list(100)


@router.post("/motivos-nc", status_code=201)
async def criar(dados: MotivoEntrada, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    m = {"id": str(uuid.uuid4()), "texto": dados.texto, "predefinido": False}
    await db[COLECOES["motivos_nc"]].insert_one(dict(m))
    return m


@router.put("/motivos-nc/{motivo_id}")
async def editar(motivo_id: str, dados: MotivoEntrada, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    r = await db[COLECOES["motivos_nc"]].update_one(
        {"id": motivo_id}, {"$set": {"texto": dados.texto}}
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Motivo não encontrado")
    return await db[COLECOES["motivos_nc"]].find_one({"id": motivo_id}, {"_id": 0})


@router.put("/motivos-nc/{motivo_id}/predefinir")
async def predefinir(motivo_id: str, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    # Verificar que o motivo existe ANTES de qualquer alteração.
    # A ordem importa: se o motivo_id não existir, devolvemos 404 sem ter escrito nada.
    # Assim evitamos deixar o sistema num estado pior (sem nenhum predefinido)
    # por causa de um clique num registo que entretanto foi apagado.
    motivo = await db[COLECOES["motivos_nc"]].find_one({"id": motivo_id}, {"_id": 0})
    if motivo is None:
        raise HTTPException(status_code=404, detail="Motivo não encontrado")

    # Agora podemos desmarcar todos os outros com confiança
    await db[COLECOES["motivos_nc"]].update_many({}, {"$set": {"predefinido": False}})

    # E marcar o escolhido (com verificação da escrita final)
    r = await db[COLECOES["motivos_nc"]].update_one(
        {"id": motivo_id}, {"$set": {"predefinido": True}}
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Motivo não encontrado")
    return {"predefinido": motivo_id}


@router.delete("/motivos-nc/{motivo_id}")
async def apagar(motivo_id: str, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    r = await db[COLECOES["motivos_nc"]].delete_one({"id": motivo_id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Motivo não encontrado")
    return {"apagado": True}
