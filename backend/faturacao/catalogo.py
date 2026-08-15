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
import re
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from .auth import gestor_atual
from .db import COLECOES, obter_db
from .precos import _TAXAS, _tem_mais_de_2_casas_decimais, erros_do_produto

router = APIRouter()


def _recusa_mais_de_2_casas(v):
    """Mesmo crivo do precos.py, reutilizado e não reescrito: round(x, 2) sobre a
    representação binária come cêntimos sem avisar — p.ex. round(2.675, 2) dá
    2.67, não 2.68."""
    if _tem_mais_de_2_casas_decimais(v):
        raise ValueError(
            "O preço %s tem mais de 2 casas decimais — a fatura recusa-o "
            "para não perder um cêntimo no arredondamento." % v
        )
    return v


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
    # ge=0: deixado em aberto na Task 19 — sem esta guarda um topping a -2€
    # baixava o total da linha em vez de o subir.
    preco: float = Field(default=0.0, ge=0)
    ativa: bool = True

    @field_validator("preco")
    @classmethod
    def _valida_preco(cls, v):
        return _recusa_mais_de_2_casas(v)


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
    # Guarda deixada em aberto na Task 19 (o campo que liga produtos a grupos
    # só nasce agora, com os Produtos): mesmo padrão do apagar_loja com as
    # caixas e do apagar de categorias — um grupo atribuído a produtos não
    # pode desaparecer debaixo deles.
    if await db[COLECOES["produtos"]].count_documents({"grupos_personalizacao": grupo_id}) > 0:
        raise HTTPException(
            status_code=409,
            detail="Este grupo de personalização ainda está atribuído a produtos. "
            "Retire-o dos produtos primeiro.",
        )
    r = await db[COLECOES["grupos_personalizacao"]].delete_one({"id": grupo_id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Grupo de personalização não encontrado")
    return {"apagado": True}


# --- Produtos ---------------------------------------------------------------------


_CODIGOS_IVA_VALIDOS = frozenset(_TAXAS.values())


class ProdutoEntrada(BaseModel):
    """Um produto pertence a uma categoria e tem UM preço e UM tax_id (spec D7,
    ver faturacao/precos.py). O mesmo artigo pode existir duas vezes — ex.:
    "Açaí Regular" na Venda ao Público a €8,99 e "Açaí Regular App" nas Vendas
    Aplicações a €10,99 — é decisão do dono manter os dois, como está hoje no
    Vendus.

    `tax_id` é OBRIGATÓRIO, sem valor por omissão — a regra que não se
    negoceia. Ver o cabeçalho de precos.py sobre a app L'Açaí em produção que
    faturou refrigerantes a 13% em vez de 23% durante meses por causa de um
    `prod.get('vat_rate', 13)`. Aqui, sem IVA, o pydantic já recusa o produto
    à entrada — não há valor por omissão para inventar.
    """

    nome: str = Field(min_length=1, max_length=120)
    categoria_id: str = Field(min_length=1)
    preco: float = Field(ge=0)
    tax_id: str
    foto_url: Optional[str] = None
    grupos_personalizacao: List[str] = Field(default_factory=list)
    ativo: bool = True
    vendus_ref: Optional[str] = None

    @field_validator("preco")
    @classmethod
    def _valida_preco(cls, v):
        return _recusa_mais_de_2_casas(v)

    @field_validator("tax_id")
    @classmethod
    def _valida_tax_id(cls, v):
        # Códigos do Vendus (precos.py): NOR, INT, RED, ISE. Nada de inventar
        # um código novo aqui — a mesma fonte de verdade que faz a venda.
        if v not in _CODIGOS_IVA_VALIDOS:
            raise ValueError(
                "Código de IVA desconhecido: '%s'. Use um destes: %s"
                % (v, ", ".join(sorted(_CODIGOS_IVA_VALIDOS)))
            )
        return v


class ProdutoEstado(BaseModel):
    ativo: bool


async def _valida_referencias(db, categoria_id: str, grupos: List[str]) -> None:
    """Recusa uma categoria ou grupos de personalização inexistentes — um
    produto órfão a apontar para nada é pior do que recusar a gravação (mesmo
    raciocínio do apagar_categoria e do apagar_grupo, ao contrário)."""
    if not await db[COLECOES["categorias"]].find_one({"id": categoria_id}):
        raise HTTPException(status_code=422, detail="Categoria inexistente: %s" % categoria_id)
    if grupos:
        existentes = await (
            db[COLECOES["grupos_personalizacao"]]
            .find({"id": {"$in": grupos}}, {"_id": 0, "id": 1})
            .to_list(len(grupos))
        )
        ids_existentes = {g["id"] for g in existentes}
        em_falta = [g for g in grupos if g not in ids_existentes]
        if em_falta:
            raise HTTPException(
                status_code=422,
                detail="Grupo(s) de personalização inexistente(s): %s" % ", ".join(em_falta),
            )


@router.get("/produtos")
async def listar_produtos(
    categoria_id: Optional[str] = None,
    texto: Optional[str] = None,
    _: dict = Depends(gestor_atual),
) -> List[dict]:
    db = obter_db()
    filtro = {}
    if categoria_id:
        filtro["categoria_id"] = categoria_id
    if texto:
        filtro["nome"] = {"$regex": re.escape(texto), "$options": "i"}
    return await db[COLECOES["produtos"]].find(filtro, {"_id": 0}).sort("nome", 1).to_list(2000)


@router.get("/produtos/sem-iva")
async def produtos_sem_iva(_: dict = Depends(gestor_atual)) -> List[dict]:
    """Para o backoffice avisar ANTES de se chegar ao precos.py — apoia-se em
    erros_do_produto (a mesma regra usada no momento da venda), não a
    reimplementa."""
    db = obter_db()
    produtos = await db[COLECOES["produtos"]].find({}, {"_id": 0}).sort("nome", 1).to_list(2000)
    incompletos = []
    for produto in produtos:
        erros = erros_do_produto(produto)
        if erros:
            incompletos.append(dict(produto, erros=erros))
    return incompletos


@router.post("/produtos", status_code=201)
async def criar_produto(dados: ProdutoEntrada, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    await _valida_referencias(db, dados.categoria_id, dados.grupos_personalizacao)
    produto = dados.model_dump()
    produto["id"] = str(uuid.uuid4())
    await db[COLECOES["produtos"]].insert_one(dict(produto))
    return produto


@router.get("/produtos/{produto_id}")
async def obter_produto(produto_id: str, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    produto = await db[COLECOES["produtos"]].find_one({"id": produto_id}, {"_id": 0})
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    return produto


@router.put("/produtos/{produto_id}")
async def editar_produto(
    produto_id: str, dados: ProdutoEntrada, _: dict = Depends(gestor_atual)
) -> dict:
    db = obter_db()
    await _valida_referencias(db, dados.categoria_id, dados.grupos_personalizacao)
    r = await db[COLECOES["produtos"]].update_one({"id": produto_id}, {"$set": dados.model_dump()})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    return await db[COLECOES["produtos"]].find_one({"id": produto_id}, {"_id": 0})


@router.delete("/produtos/{produto_id}")
async def apagar_produto(produto_id: str, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    r = await db[COLECOES["produtos"]].delete_one({"id": produto_id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    return {"apagado": True}


@router.put("/produtos/{produto_id}/estado")
async def mudar_estado_produto(
    produto_id: str, dados: ProdutoEstado, _: dict = Depends(gestor_atual)
) -> dict:
    db = obter_db()
    r = await db[COLECOES["produtos"]].update_one(
        {"id": produto_id}, {"$set": {"ativo": dados.ativo}}
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    return {"ativo": dados.ativo}
