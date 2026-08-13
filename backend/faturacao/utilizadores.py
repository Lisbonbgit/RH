"""Utilizadores do POS.

Entram com PIN de 4 dígitos, nunca vêem o backoffice. Quem sai da empresa fica
INACTIVO, nunca apagado — o histórico de vendas aponta para o utilizador, e
apagá-lo deixaria vendas órfãs. Por isso não há DELETE aqui.

O campo employee_id liga (opcionalmente) ao colaborador do RH, para herdar a
foto que já existe no perfil dele e mostrá-la na tela de descanso do POS.

Unicidade do PIN (Regra 2): o PIN tem de ser único entre os utilizadores
ACTIVOS cujo âmbito de lojas se sobreponha. Não pode ser garantido por um
índice — o bcrypt usa sal, por isso o mesmo PIN "1234" produz um pin_hash
diferente de cada vez (ver faturacao/pins.py e faturacao/db.py). A única
forma de verificar é buscar os candidatos activos e comparar um a um com
bcrypt.checkpw (via pin_valido).

Essa verificação só corre em dois sítios: ao CRIAR um utilizador e ao MUDAR
um PIN — são os dois únicos momentos em que o servidor tem o PIN em claro na
mão. Editar nome/perfil/lojas (endpoint /utilizadores/{id}) não mexe no PIN
por isso mesmo: se editar pudesse voltar a validar a unicidade, precisava do
PIN em claro para comparar com bcrypt, e o servidor só guarda o hash — não há
como. Mover alguém para uma loja nova sem lhe mudar o PIN é, por isso, um
buraco conhecido e aceite desta escolha de desenho (o mesmo problema, aliás,
que impede um índice: bcrypt não deixa comparar hashes entre si).
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from .auth import gestor_atual
from .db import COLECOES, obter_db
from .pins import hash_pin, normalizar_pin, pin_valido

router = APIRouter()

PERFIS_POS = ["administrador", "operador_caixa", "contabilista"]


class _CamposComuns(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    perfil: str
    lojas: List[str] = []
    employee_id: Optional[str] = None

    @field_validator("perfil")
    @classmethod
    def _valida_perfil(cls, v):
        if v not in PERFIS_POS:
            raise ValueError("Perfil desconhecido: " + str(v))
        return v

    @model_validator(mode="after")
    def _operador_precisa_de_loja(self):
        if self.perfil == "operador_caixa" and not self.lojas:
            raise ValueError("Um operador de caixa tem de ter pelo menos uma loja.")
        return self


class UtilizadorEntrada(_CamposComuns):
    """Dados para criar um utilizador do POS. O PIN inicial só se define
    aqui — depois disto, só muda em /utilizadores/{id}/pin."""

    pin: str

    @field_validator("pin")
    @classmethod
    def _valida_pin(cls, v):
        return normalizar_pin(v)


class UtilizadorEdicao(_CamposComuns):
    """Dados para editar nome/perfil/lojas/employee_id. Sem campo pin de
    propósito — ver nota no topo do ficheiro sobre porque é que mudar de loja
    aqui não repete a verificação de unicidade do PIN."""


class MudarPin(BaseModel):
    pin: str

    @field_validator("pin")
    @classmethod
    def _valida(cls, v):
        return normalizar_pin(v)


class MudarEstado(BaseModel):
    ativo: bool


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _publico(u: dict) -> dict:
    """Nunca devolver o hash do PIN para fora."""
    return {k: v for k, v in u.items() if k not in ("_id", "pin_hash")}


def _sobrepoe_lojas(lojas_a: List[str], lojas_b: List[str]) -> bool:
    """Duas listas de lojas "sobrepõem-se" se partilharem alguma loja — ou se
    QUALQUER uma das duas for vazia. Lista vazia é o administrador (entra em
    qualquer loja), por isso o âmbito dele colide potencialmente com o de
    toda a gente, em qualquer loja."""
    if not lojas_a or not lojas_b:
        return True
    return bool(set(lojas_a) & set(lojas_b))


async def _pin_em_uso(db, pin: str, lojas: List[str], excluir_id: Optional[str] = None) -> bool:
    """Regra 2: verifica se `pin` já pertence a outro utilizador ACTIVO cujo
    âmbito de lojas se sobreponha a `lojas`. `excluir_id` tira o próprio
    utilizador da comparação — sem isso, mudar alguém para o PIN que já tinha
    seria sempre recusado, porque o PIN novo bate sempre certo com o hash
    antigo dela própria."""
    ativos = await db[COLECOES["utilizadores"]].find({"ativo": True}).to_list(1000)
    for outro in ativos:
        if excluir_id is not None and outro.get("id") == excluir_id:
            continue
        if not _sobrepoe_lojas(lojas, outro.get("lojas") or []):
            continue
        if pin_valido(pin, outro.get("pin_hash")):
            return True
    return False


_MSG_PIN_REPETIDO = "Já existe um utilizador activo com este PIN numa das lojas indicadas."


@router.get("/utilizadores")
async def listar(_: dict = Depends(gestor_atual)) -> List[dict]:
    db = obter_db()
    us = await db[COLECOES["utilizadores"]].find({}).sort("nome", 1).to_list(500)
    return [_publico(u) for u in us]


@router.post("/utilizadores", status_code=201)
async def criar(dados: UtilizadorEntrada, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    if await _pin_em_uso(db, dados.pin, dados.lojas):
        raise HTTPException(status_code=409, detail=_MSG_PIN_REPETIDO)
    u = dados.model_dump()
    pin = u.pop("pin")
    u.update({
        "id": str(uuid.uuid4()),
        "pin_hash": hash_pin(pin),
        "ativo": True,
        "criado_em": _agora(),
    })
    await db[COLECOES["utilizadores"]].insert_one(dict(u))
    return _publico(u)


@router.put("/utilizadores/{utilizador_id}")
async def editar(utilizador_id: str, dados: UtilizadorEdicao,
                 _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    r = await db[COLECOES["utilizadores"]].update_one(
        {"id": utilizador_id}, {"$set": dados.model_dump()}
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Utilizador não encontrado")
    return _publico(await db[COLECOES["utilizadores"]].find_one({"id": utilizador_id}))


@router.put("/utilizadores/{utilizador_id}/pin")
async def mudar_pin(utilizador_id: str, dados: MudarPin,
                    _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    atual = await db[COLECOES["utilizadores"]].find_one({"id": utilizador_id})
    if not atual:
        raise HTTPException(status_code=404, detail="Utilizador não encontrado")
    if await _pin_em_uso(db, dados.pin, atual.get("lojas") or [], excluir_id=utilizador_id):
        raise HTTPException(status_code=409, detail=_MSG_PIN_REPETIDO)
    await db[COLECOES["utilizadores"]].update_one(
        {"id": utilizador_id}, {"$set": {"pin_hash": hash_pin(dados.pin)}}
    )
    return {"atualizado": True}


@router.put("/utilizadores/{utilizador_id}/estado")
async def mudar_estado(utilizador_id: str, dados: MudarEstado,
                       _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    r = await db[COLECOES["utilizadores"]].update_one(
        {"id": utilizador_id}, {"$set": {"ativo": dados.ativo}}
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Utilizador não encontrado")
    return {"ativo": dados.ativo}
