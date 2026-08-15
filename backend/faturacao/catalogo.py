"""Catálogo — Categorias e Grupos de Personalização (Task 19 do Plano 1).

Nascem antes dos Produtos (Task 20) porque um produto vai apontar para uma
categoria e para grupos de personalização.

Categorias são as do Vendus — "Venda ao Público" e "Vendas Aplicações"
(decisão D7 da spec, §9.1): cada produto pertence a uma e só uma, com um
preço e um IVA (ver faturacao/precos.py).

Grupos de personalização seguem o modelo que a app L'Açaí já usa em
produção — a mesma forma que o Vendus usa: `min_select`/`max_select` e
opções com preço próprio. A semântica é DERIVADA, sem campos redundantes:
- obrigatório = min_select >= 1
- escolha única (radio) = max_select == 1
- max_select == 0 = ilimitado
Não se acrescenta um campo "obrigatorio" nem "tipo" — seriam uma segunda
fonte de verdade para a mesma informação.
"""
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from .auth import gestor_atual
from .db import COLECOES, obter_db
from .precos import _tem_mais_de_2_casas_decimais

router = APIRouter()


# --- Categorias ----------------------------------------------------------------


class CategoriaEntrada(BaseModel):
    nome: str = Field(min_length=1, max_length=80)
    ordem: int = 0
    ativa: bool = True


@router.get("/categorias")
async def listar_categorias(_: dict = Depends(gestor_atual)) -> List[dict]:
    db = obter_db()
    return await db[COLECOES["categorias"]].find({}, {"_id": 0}).sort("ordem", 1).to_list(200)


@router.post("/categorias", status_code=201)
async def criar_categoria(dados: CategoriaEntrada, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    categoria = dados.model_dump()
    categoria["id"] = str(uuid.uuid4())
    await db[COLECOES["categorias"]].insert_one(dict(categoria))
    return categoria


@router.put("/categorias/{categoria_id}")
async def editar_categoria(
    categoria_id: str, dados: CategoriaEntrada, _: dict = Depends(gestor_atual)
) -> dict:
    db = obter_db()
    r = await db[COLECOES["categorias"]].update_one(
        {"id": categoria_id}, {"$set": dados.model_dump()}
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")
    return await db[COLECOES["categorias"]].find_one({"id": categoria_id}, {"_id": 0})


@router.delete("/categorias/{categoria_id}")
async def apagar_categoria(categoria_id: str, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    # Guarda: um produto órfão (categoria_id apontando para nada) é pior do
    # que recusar o apagar. Mesmo padrão do apagar_loja com as caixas.
    if await db[COLECOES["produtos"]].count_documents({"categoria_id": categoria_id}) > 0:
        raise HTTPException(
            status_code=409,
            detail="Esta categoria ainda tem produtos. Mude-os de categoria primeiro.",
        )
    r = await db[COLECOES["categorias"]].delete_one({"id": categoria_id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")
    return {"apagada": True}


# --- Grupos de personalização ----------------------------------------------------


class OpcaoEntrada(BaseModel):
    """Uma opção dentro de um grupo (ex.: "Nutella", €0,95).

    O `id` vem vazio numa opção nova — o servidor atribui-lhe um ao gravar
    (ver `_opcoes_com_id`) — e é preservado numa opção já existente, para o
    histórico de vendas continuar a apontar para o mesmo id mesmo que o
    nome ou o preço mudem.
    """

    id: Optional[str] = None
    nome: str = Field(min_length=1, max_length=60)
    preco: float = 0.0
    ativa: bool = True

    @field_validator("preco")
    @classmethod
    def _valida_preco(cls, v):
        # Mesmo crivo do precos.py, reutilizado e não reescrito: round(x, 2)
        # sobre a representação binária come cêntimos sem avisar.
        if _tem_mais_de_2_casas_decimais(v):
            raise ValueError(
                "O preço %s tem mais de 2 casas decimais — a fatura recusa-o "
                "para não perder um cêntimo no arredondamento." % v
            )
        return v


class GrupoPersonalizacaoEntrada(BaseModel):
    nome: str = Field(min_length=1, max_length=80)
    min_select: int = 0
    max_select: int = 0
    opcoes: List[OpcaoEntrada] = Field(default_factory=list)
    ativo: bool = True

    @model_validator(mode="after")
    def _valida_selecao(self):
        if self.max_select > 0 and self.min_select > self.max_select:
            raise ValueError(
                "O mínimo de escolhas (%d) não pode ser maior do que o máximo (%d)."
                % (self.min_select, self.max_select)
            )
        if self.min_select > len(self.opcoes):
            raise ValueError(
                "O mínimo de escolhas (%d) não pode ser maior do que o número de opções "
                "do grupo (%d)." % (self.min_select, len(self.opcoes))
            )
        return self


def _opcoes_com_id(opcoes: List[dict]) -> List[dict]:
    """Atribui um id novo só às opções que ainda não têm (novas); preserva o
    id das que já vinham com um, para o histórico de vendas continuar válido."""
    resultado = []
    for opcao in opcoes:
        opcao = dict(opcao)
        if not opcao.get("id"):
            opcao["id"] = str(uuid.uuid4())
        resultado.append(opcao)
    return resultado


@router.get("/grupos-personalizacao")
async def listar_grupos(_: dict = Depends(gestor_atual)) -> List[dict]:
    db = obter_db()
    return (
        await db[COLECOES["grupos_personalizacao"]]
        .find({}, {"_id": 0})
        .sort("nome", 1)
        .to_list(200)
    )


@router.post("/grupos-personalizacao", status_code=201)
async def criar_grupo(dados: GrupoPersonalizacaoEntrada, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    grupo = dados.model_dump()
    grupo["opcoes"] = _opcoes_com_id(grupo["opcoes"])
    grupo["id"] = str(uuid.uuid4())
    await db[COLECOES["grupos_personalizacao"]].insert_one(dict(grupo))
    return grupo


@router.put("/grupos-personalizacao/{grupo_id}")
async def editar_grupo(
    grupo_id: str, dados: GrupoPersonalizacaoEntrada, _: dict = Depends(gestor_atual)
) -> dict:
    db = obter_db()
    grupo = dados.model_dump()
    grupo["opcoes"] = _opcoes_com_id(grupo["opcoes"])
    r = await db[COLECOES["grupos_personalizacao"]].update_one({"id": grupo_id}, {"$set": grupo})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Grupo de personalização não encontrado")
    return await db[COLECOES["grupos_personalizacao"]].find_one({"id": grupo_id}, {"_id": 0})


@router.delete("/grupos-personalizacao/{grupo_id}")
async def apagar_grupo(grupo_id: str, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    r = await db[COLECOES["grupos_personalizacao"]].delete_one({"id": grupo_id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Grupo de personalização não encontrado")
    return {"apagado": True}
