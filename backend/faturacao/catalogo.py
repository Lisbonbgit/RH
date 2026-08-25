"""Catálogo — Categorias e Grupos de Personalização (Task 19 do Plano 1).

Nascem antes dos Produtos (Task 20) porque um produto vai apontar para uma
categoria e para grupos de personalização.

Categorias são as do Vendus — "Venda ao Público" e "Vendas Aplicações"
(decisão D7 da spec, §9.1): cada produto pertence a uma e só uma, com um
preço e um IVA (ver faturacao/precos.py).

Grupos de personalização seguem o modelo que a app L'Açaí já usa em
produção — a mesma forma que o Vendus usa: `min_select`/`max_select` e
opções com preço próprio. A semântica de obrigatório/escolha única é
DERIVADA, sem campo redundante:
- obrigatório = min_select >= 1
- escolha única (radio) = max_select == 1
- max_select == 0 = ilimitado
Não se acrescenta um campo "obrigatorio" — seria uma segunda fonte de
verdade para a mesma informação. `tipo` já existe ("opcoes" | "texto"),
mas não é redundante: distingue um grupo de escolhas de um campo de texto
livre (o "Nome" do copo do açaí), coisa que min_select/max_select não
conseguem exprimir.
"""
import re
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from .auth import gestor_atual
from .db import COLECOES, obter_db
from .fotos import origem_de_uma_gravacao_do_backoffice
from .precos import _CODIGOS_IVA_VALIDOS, _tem_mais_de_2_casas_decimais, erros_do_produto

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
    # Id da categoria no Vendus — só preenchido pela importação
    # (faturacao/importacao.py). Uma categoria criada aqui à mão fica sem
    # ele; é por isso que a importação casa por ele quando existe, e cai
    # para o nome só como reserva (ver a docstring de importacao.py).
    vendus_ref: Optional[str] = None


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


# --- Subcategorias ---------------------------------------------------------------
#
# **Uma subcategoria vive DENTRO de uma categoria** — «Venda ao Público →
# Açaís, Salgados, Bebidas» — e foi assim que o dono a pediu, depois de eu ter
# proposto uma lista única partilhada pelas duas categorias. O preço dessa
# escolha é conhecido e aceite: um nome que faça sentido nos dois sítios
# («Bebidas») cria-se duas vezes, uma em cada categoria.
#
# **São só nossas.** O Vendus não tem este nível, a importação não as conhece e
# nunca lhes toca — o que ela reescreve é a CATEGORIA do produto, que continua
# a ser dela. Servem para arrumar a grelha do POS e mais nada: não entram na
# fatura, no IVA nem nos relatórios.


class SubcategoriaEntrada(BaseModel):
    nome: str = Field(min_length=1, max_length=80)
    categoria_id: str = Field(min_length=1)
    ordem: int = 0
    ativa: bool = True


async def _garante_categoria(db, categoria_id: str) -> None:
    if not await db[COLECOES["categorias"]].find_one({"id": categoria_id}):
        raise HTTPException(
            status_code=422, detail="Categoria inexistente: %s" % categoria_id)


@router.get("/subcategorias")
async def listar_subcategorias(
    categoria_id: Optional[str] = None, _: dict = Depends(gestor_atual)
) -> List[dict]:
    """Todas, ou só as de uma categoria. O ecrã das Categorias pede-as todas de
    uma vez (é uma lista pequena e são para mostrar dentro de cada categoria);
    o `categoria_id` existe para a ficha do produto, que só quer as da
    categoria escolhida."""
    db = obter_db()
    filtro = {"categoria_id": categoria_id} if categoria_id else {}
    return await (
        db[COLECOES["subcategorias"]].find(filtro, {"_id": 0})
        .sort("ordem", 1).to_list(500)
    )


@router.post("/subcategorias", status_code=201)
async def criar_subcategoria(
    dados: SubcategoriaEntrada, _: dict = Depends(gestor_atual)
) -> dict:
    db = obter_db()
    await _garante_categoria(db, dados.categoria_id)
    subcategoria = dados.model_dump()
    subcategoria["id"] = str(uuid.uuid4())
    await db[COLECOES["subcategorias"]].insert_one(dict(subcategoria))
    return subcategoria


@router.put("/subcategorias/{subcategoria_id}")
async def editar_subcategoria(
    subcategoria_id: str, dados: SubcategoriaEntrada, _: dict = Depends(gestor_atual)
) -> dict:
    """**Mudar uma subcategoria de categoria arrastaria os produtos dela para
    uma categoria que não é a deles** — e um produto cuja subcategoria pertence
    a outra categoria não aparece em grelha nenhuma: some do ecrã sem ninguém
    perceber porquê. Recusa-se enquanto ela tiver produtos; sem produtos, muda
    à vontade."""
    db = obter_db()
    atual = await db[COLECOES["subcategorias"]].find_one({"id": subcategoria_id})
    if not atual:
        raise HTTPException(status_code=404, detail="Subcategoria não encontrada")
    await _garante_categoria(db, dados.categoria_id)
    if dados.categoria_id != atual.get("categoria_id"):
        quantos = await db[COLECOES["produtos"]].count_documents(
            {"subcategoria_id": subcategoria_id})
        if quantos:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Esta subcategoria tem %d produto(s) e não se pode mudar "
                    "para outra categoria — eles deixariam de aparecer na "
                    "grelha. Tire-os dela primeiro." % quantos
                ),
            )
    await db[COLECOES["subcategorias"]].update_one(
        {"id": subcategoria_id}, {"$set": dados.model_dump()}
    )
    return await db[COLECOES["subcategorias"]].find_one({"id": subcategoria_id}, {"_id": 0})


@router.delete("/subcategorias/{subcategoria_id}")
async def apagar_subcategoria(
    subcategoria_id: str, _: dict = Depends(gestor_atual)
) -> dict:
    """Apagar uma subcategoria com produtos NÃO os apaga nem os esconde: eles
    voltam a ser produtos da categoria, sem subcategoria nenhuma, e continuam
    a aparecer na grelha (em «Outros»). É por isso que isto não pede para os
    mudar primeiro, ao contrário do apagar uma CATEGORIA — lá o produto ficava
    órfão a apontar para nada, aqui não fica: o campo limpa-se."""
    db = obter_db()
    r = await db[COLECOES["subcategorias"]].delete_one({"id": subcategoria_id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Subcategoria não encontrada")
    soltos = await db[COLECOES["produtos"]].update_many(
        {"subcategoria_id": subcategoria_id}, {"$set": {"subcategoria_id": None}}
    )
    return {"apagada": True, "produtos_soltos": getattr(soltos, "modified_count", 0)}


# --- Grupos de personalização ----------------------------------------------------


# Um grupo é uma lista de opções (o de sempre) ou um campo de texto livre.
# O texto nasceu do "Nome" que se escreve no copo do açaí: é a única coisa
# do pedido guiado que não é uma escolha entre alternativas.
TIPOS_DE_GRUPO = frozenset({"opcoes", "texto"})


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
    # baixava o total da linha em vez de o subir. allow_inf_nan=False:
    # Infinity não é negativo nem tem casas decimais — passava por todas as
    # outras guardas, e o json do Python aceita o literal sem se queixar.
    preco: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    ativa: bool = True

    @field_validator("preco")
    @classmethod
    def _valida_preco(cls, v):
        return _recusa_mais_de_2_casas(v)


class GrupoPersonalizacaoEntrada(BaseModel):
    nome: str = Field(min_length=1, max_length=80)
    # ge=0: é nestes dois números que vive toda a semântica de selecção
    # (0=ilimitado, 1=escolha única) — sem esta guarda, min_select=-3 e
    # max_select=-5 gravavam sem queixa e o POS ia depender disso.
    min_select: int = Field(default=0, ge=0)
    max_select: int = Field(default=0, ge=0)
    opcoes: List[OpcaoEntrada] = Field(default_factory=list)
    ativo: bool = True
    tipo: str = "opcoes"
    # Se as escolhas deste grupo entram no título da linha da Fatura
    # Simplificada. Liga-se nos toppings (que descrevem o produto e mudam o
    # preço) e desliga-se no Nome e no "Consumir na loja", que são para a
    # cozinha. Ver `precos._descricao_das_opcoes`: uma opção COM PREÇO sai
    # na fatura de qualquer maneira — este interruptor esconde o que não
    # custa nada, nunca um euro. "Com preço" é preço DIFERENTE de zero, o
    # negativo incluído: um desconto gravado como opção mexe no dinheiro da
    # linha tanto como um topping, e escondê-lo tirava o euro da fatura sem
    # deixar rasto. As duas promessas dizem o mesmo de propósito — é a
    # mesma regra, escrita no sítio onde o gestor liga o interruptor e no
    # sítio onde ela se cumpre.
    sai_na_fatura: bool = True

    @field_validator("tipo")
    @classmethod
    def _valida_tipo(cls, v):
        if v not in TIPOS_DE_GRUPO:
            raise ValueError(
                "Tipo de grupo desconhecido: '%s'. Use um destes: %s"
                % (v, ", ".join(sorted(TIPOS_DE_GRUPO)))
            )
        return v

    @model_validator(mode="after")
    def _valida_selecao(self):
        # Um grupo de TEXTO não tem opções: `min_select >= 1` quer dizer
        # "resposta obrigatória", e comparar isso com len(opcoes) recusava
        # sempre um Nome obrigatório. As duas guardas abaixo são sobre
        # escolher de uma lista, e só a essa se aplicam.
        if self.tipo != "opcoes":
            return self
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
    # A subcategoria é OPCIONAL e é só arrumação da grelha do POS: um produto
    # sem ela aparece na mesma, em «Outros». Tem de pertencer à categoria do
    # produto (`_valida_referencias`) — uma subcategoria de outra categoria
    # fazia o produto desaparecer da grelha sem ninguém perceber porquê.
    subcategoria_id: Optional[str] = None
    preco: float = Field(ge=0, allow_inf_nan=False)
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


async def _valida_referencias(
    db, categoria_id: str, grupos: List[str], subcategoria_id: Optional[str] = None
) -> None:
    """Recusa uma categoria, subcategoria ou grupos de personalização
    inexistentes — um produto órfão a apontar para nada é pior do que recusar a
    gravação (mesmo raciocínio do apagar_categoria e do apagar_grupo, ao
    contrário).

    **A subcategoria tem de ser DA categoria do produto.** Não é zelo: a grelha
    do POS mostra as subcategorias da categoria que está à frente, e um produto
    com a subcategoria de outra categoria não cabe em nenhuma delas —
    desaparecia do ecrã, com o artigo à venda na loja."""
    if not await db[COLECOES["categorias"]].find_one({"id": categoria_id}):
        raise HTTPException(status_code=422, detail="Categoria inexistente: %s" % categoria_id)
    if subcategoria_id:
        sub = await db[COLECOES["subcategorias"]].find_one({"id": subcategoria_id})
        if not sub:
            raise HTTPException(
                status_code=422, detail="Subcategoria inexistente: %s" % subcategoria_id)
        if sub.get("categoria_id") != categoria_id:
            raise HTTPException(
                status_code=422,
                detail=(
                    "A subcategoria \"%s\" é de outra categoria — o produto "
                    "deixaria de aparecer na grelha." % sub.get("nome")
                ),
            )
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
    await _valida_referencias(
        db, dados.categoria_id, dados.grupos_personalizacao, dados.subcategoria_id)
    produto = dados.model_dump()
    produto["id"] = str(uuid.uuid4())
    # De onde veio a foto, gravado ao lado dela — é este campo que decide, na
    # reimportação seguinte, se o Vendus lhe pode tocar. Um produto criado
    # aqui com foto tem uma foto NOSSA, por definição: não há mais ninguém a
    # criar produtos por esta porta. Ver `fotos.py`.
    produto["foto_origem"] = origem_de_uma_gravacao_do_backoffice(dados.foto_url, None)
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
    await _valida_referencias(
        db, dados.categoria_id, dados.grupos_personalizacao, dados.subcategoria_id)

    alteracoes = dados.model_dump()
    # O `vendus_ref` NÃO se apaga por omissão. Este PUT substitui o registo
    # inteiro (`$set` do modelo todo) e o campo tem `= None` por omissão no
    # ProdutoEntrada — um pedido que não o repita punha-o a nulo.
    #
    # Isso deixou de ser um detalhe: é este id que a emissão manda em cada
    # linha da fatura (precos.linha_de_venda) para o Vendus LIGAR a linha ao
    # produto que já lá existe. Sem ele, o Vendus não casa por nome e cria um
    # produto novo A CADA VENDA — foi assim que a conta ficou com 14 "Açaí
    # Mini", 13 deles lixo sem categoria, com referências VACA…
    #
    # O backoffice já reenvia o valor (FatProdutos.js), mas essa defesa vive
    # no browser: um script, um curl, ou um ecrã novo que reutilize este
    # endpoint desligava a correcção em silêncio. Quem quiser mesmo desligar
    # a ligação manda o campo explicitamente; quem não falar dele não lhe
    # toca.
    if "vendus_ref" not in dados.model_fields_set:
        alteracoes.pop("vendus_ref", None)

    # **A ORIGEM DA FOTO calcula-se contra o que está GRAVADO**, e por isso o
    # produto lê-se ANTES de se escrever. A regra fácil — «tudo o que passa
    # pelo backoffice é nosso» — tinha uma consequência que não se quer:
    # corrigir o NOME de um produto congelava a foto que tinha vindo do
    # Vendus, e o dono deixava de receber aqui as trocas que fizesse lá. O que
    # marca a foto como nossa é MEXER-LHE. Ver `fotos.py`.
    existente = await db[COLECOES["produtos"]].find_one({"id": produto_id}, {"_id": 0})
    if existente is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    alteracoes["foto_origem"] = origem_de_uma_gravacao_do_backoffice(
        dados.foto_url, existente)

    r = await db[COLECOES["produtos"]].update_one({"id": produto_id}, {"$set": alteracoes})
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
