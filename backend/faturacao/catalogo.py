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
from .precos import (
    _CODIGOS_IVA_VALIDOS,
    _tem_mais_de_2_casas_decimais,
    e_grupo_de_variante,
    erros_do_produto,
    id_vendus_do_produto,
)

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


# As unidades em que se escreve o que uma opção GASTA (não o que custa) e as
# que um artigo do Estoque pode ter. Vivem em `unidades.py`, com a conversão,
# porque é a mesma pergunta feita de dois lados — e duas cópias do mapa é uma
# divergência que erra por um factor de mil.
from .unidades import (  # noqa: E402
    FAMILIA_DO_ARTIGO,
    UNIDADES_DE_ARTIGO,
    UNIDADES_DE_CONSUMO,
    familia,
)


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
    # **O artigo do Vendus que ESTA opção representa** — o mesmo campo que o
    # produto já tem, um nível abaixo.
    #
    # Existe por uma razão de faturação e não de arrumação: no nosso catálogo
    # há UM açaí e o tamanho é uma personalização dele; no Vendus, o Mini, o
    # Small, o Regular e o Supreme são quatro artigos diferentes. Sem isto, a
    # linha viajava sempre com a referência do produto — e as cinco lojas
    # estiveram a faturar todos os açaís como «Açaí Regular», fosse qual
    # fosse o tamanho. O total em dinheiro estava certo; o artigo é que não.
    #
    # `None` na esmagadora maioria das opções: um topping não é outro artigo.
    vendus_ref: Optional[str] = None

    # **O que esta opção GASTA** — quanto, de quê, e de qual artigo do Estoque.
    #
    # Nasce para o stock descer sozinho com as vendas: escrever aqui «30 g de
    # granola» é o que permite, depois, somar o que saiu num período e
    # descontá-lo. Nesta fase só se ESCREVE — nada aqui desconta nada.
    #
    # `estoque_produto_id` e NÃO o `vendus_ref` que está mesmo por cima, ainda
    # que a tentação seja evidente: são dois espaços de identificadores a
    # servir dois sistemas diferentes. O catálogo já recusa a confusão por
    # escrito em `precos.id_vendus_da_variante` — só uma opção de um grupo de
    # VARIANTE pode desviar o artigo do Vendus, e sem essa guarda «ligar um
    # topping ao artigo dele no Vendus para efeitos de stock passava a
    # facturar o açaí inteiro como Nutella». O dinheiro da fatura e o peso do
    # armazém não podem partilhar o mesmo campo.
    #
    # ge=0: um consumo negativo ACRESCENTAVA stock a cada venda.
    # allow_inf_nan=False: mesma razão que o preço — `Infinity` não é negativo
    # e o json do Python aceita o literal sem se queixar.
    # `le=10000`: não é um limite físico, é o apanha-zeros. Escrever 30000 em
    # vez de 30 gravava 30 kg de granola por dose, e o relatório do mês passava
    # a dizer que saíram toneladas sem nada se queixar. Nenhuma dose de um copo
    # de açaí chega perto de dez mil seja do que for.
    consumo: Optional[float] = Field(default=None, ge=0, le=10000, allow_inf_nan=False)
    consumo_unidade: Optional[str] = None
    estoque_produto_id: Optional[str] = None
    # **A unidade em que o ARTIGO do Estoque conta** — e não a que se escreveu
    # na ficha. Carimba-se aqui, na configuração, porque o movimento de stock
    # não leva unidade nenhuma: manda um número cru, interpretado do lado de
    # lá. Sem saber que a granola se conta em quilos, «30 g» ia como `30` e
    # tirava 30 kg por dose. Vem do artigo escolhido no ecrã.
    estoque_unidade_medida: Optional[str] = None

    @field_validator("preco")
    @classmethod
    def _valida_preco(cls, v):
        return _recusa_mais_de_2_casas(v)

    @field_validator("consumo_unidade")
    @classmethod
    def _valida_unidade_de_consumo(cls, v):
        if v is not None and v not in UNIDADES_DE_CONSUMO:
            raise ValueError(
                "Unidade de consumo desconhecida: '%s'. Use uma destas: %s"
                % (v, ", ".join(sorted(UNIDADES_DE_CONSUMO)))
            )
        return v

    @model_validator(mode="after")
    def _valida_consumo(self):
        """Ou se escrevem os dois campos, ou não se escreve nenhum.

        Um `30` sozinho não quer dizer nada: 30 gramas de granola e 30
        mililitros de leite condensado escrevem-se com o mesmo algarismo e
        descontam coisas diferentes. E uma unidade sem número não desconta de
        todo. Quem lesse isto a seguir tinha de adivinhar — e adivinhava
        contra o stock.

        `is None` e não a falsidade do valor: `consumo=0` é uma resposta
        legítima (o palito, o guardanapo) e é diferente de «não sei».
        """
        if (self.consumo is None) != (self.consumo_unidade is None):
            raise ValueError(
                "O consumo de uma opção escreve-se com número E unidade (ex.: 30 «g»), "
                "ou deixa-se os dois em branco."
            )
        return self

    @model_validator(mode="after")
    def _valida_o_artigo_do_estoque(self):
        """A ficha e o artigo têm de medir a MESMA coisa.

        Sem isto, «30 g» ligado a um artigo contado em unidades descontava
        trinta pacotes de granola por copo, e ninguém dava por isso senão na
        contagem do mês — o movimento de stock não leva unidade nenhuma para
        o Estoque poder recusar.

        A `caixa` recusa-se à cara: uma caixa de quê, com quantos? Só o
        Estoque sabe, e nem sempre. Deixar ligar e nunca descontar era o pior
        dos dois — uma ficha preenchida que não faz nada.
        """
        if self.estoque_unidade_medida is None:
            # **Ausente é ACEITE, de propósito.** As personalizações ligadas na
            # Fase 1 têm artigo e não têm este campo, porque ele ainda não
            # existia. Recusá-las aqui fechava o ecrã à chave: a mensagem
            # mandava escolher o artigo outra vez, o ecrã reenviava o mesmo
            # pedido, e falhava na mesma — sem saída pela interface.
            #
            # A guarda que interessa não é esta: é a do DESCONTO
            # (`estoque_saida.saidas_de_uma_venda`), que salta e regista toda a
            # opção sem unidade do artigo em vez de adivinhar. Uma ficha por
            # acertar não desconta nada; nunca desconta errado.
            return self
        if self.estoque_unidade_medida not in UNIDADES_DE_ARTIGO:
            raise ValueError(
                "Este artigo do Estoque conta em «%s» e não há conversão para isso. "
                "Ligue a uma medida em %s, ou deixe a personalização sem artigo."
                % (self.estoque_unidade_medida, ", ".join(sorted(UNIDADES_DE_ARTIGO)))
            )
        se_a_ficha = familia(self.consumo_unidade)
        if se_a_ficha and se_a_ficha != FAMILIA_DO_ARTIGO[self.estoque_unidade_medida]:
            raise ValueError(
                "A ficha está escrita em «%s» e este artigo do Estoque conta em «%s» — "
                "são medidas de coisas diferentes." % (self.consumo_unidade, self.estoque_unidade_medida)
            )
        return self


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


# Os campos que descrevem o que uma opção gasta. Andam sempre juntos porque
# são a mesma frase («30 g de granola») repartida por três casas — e é por
# isso que se preservam EM BLOCO. Ver a docstring abaixo.
_CAMPOS_DE_CONSUMO = (
    "consumo", "consumo_unidade", "estoque_produto_id", "estoque_unidade_medida")

# Os que se preservam um a um: cada um é uma frase inteira sozinho.
#
# O `vendus_ref` entra aqui porque tem exactamente o mesmo buraco e é o
# incidente que a docstring abaixo invoca como precedente: é campo declarado
# com `default=None`, portanto o `model_dump()` emite-o a nulo quando o pedido
# não fala dele, e o `$set` do modelo inteiro grava-o a nulo. O backoffice
# reenvia-o sempre — mas essa defesa vive no browser, e um curl, um script de
# importação ou um separador com um build antigo desligavam a ligação do
# tamanho ao artigo do Vendus sem deixar rasto. Foi assim que a conta do
# Vendus ficou com 14 «Açaí Mini», 13 deles lixo.
_CAMPOS_PRESERVADOS_UM_A_UM = ("vendus_ref",)


def _preserva_o_que_o_pedido_nao_falou(
    opcoes: List[dict], entradas: List["OpcaoEntrada"], gravadas: List[dict]
) -> List[dict]:
    """Um pedido que não fala do consumo de uma opção não lhe toca.

    Porquê isto existe: este PUT substitui o registo inteiro (`$set` do modelo
    todo) e, dentro dele, o array `opcoes` por completo. O ecrã do backoffice
    monta cada opção campo a campo. Junte-se as duas coisas e uma ida às
    Personalizações para corrigir um PREÇO levava consigo, em silêncio, as
    gramagens de todas as opções do grupo.

    É a repetição exacta do defeito que obrigou à guarda `model_fields_set` no
    PUT do produto — o `vendus_ref` que se apagava sozinho e encheu a conta do
    Vendus de artigos-lixo. E, tal como lá, a defesa não pode viver no
    browser: um curl, um script, ou um ecrã novo que reutilize este endpoint
    desligavam-na sem deixar rasto.

    Casa-se por `id` e nunca por posição: uma opção acrescentada no meio da
    lista herdava o consumo da vizinha, e a Banana passava a descontar
    granola. Uma opção sem id é nova — nasce sem consumo, que é o que se quer.

    Quem QUISER mesmo apagar manda o campo a nulo explicitamente; quem não
    falar dele não lhe toca.

    **O consumo preserva-se EM BLOCO, e isto não é arrumação.** O
    `_valida_consumo` promete que nunca se grava número sem unidade — mas
    valida o PEDIDO, e a preservação corre depois. Campo a campo, um PUT com
    `{"consumo": null}` que não mencionasse a unidade passava a validação (no
    pedido os dois estão a None) e saía daqui com `consumo=None,
    consumo_unidade="g"` — exactamente o par que o validador existe para
    recusar. Ao contrário, `{"consumo_unidade": null}` sozinho gravava
    `consumo=30, consumo_unidade=None`, e o carimbo em `venda.py` (que só
    pergunta `consumo is not None`) levava-o para as linhas, onde o relatório
    o deitava fora em silêncio por não saber converter a unidade.

    Por isso a regra é a da frase: se o pedido não falar de NENHUM dos três,
    repõem-se os três; se falar de algum, aceitam-se os três tal como vieram —
    e aí o validador já os viu juntos.
    """
    por_id = {o.get("id"): o for o in gravadas if o.get("id")}
    resultado = []
    for opcao, entrada in zip(opcoes, entradas):
        opcao = dict(opcao)
        anterior = por_id.get(opcao.get("id"))
        if anterior is not None:
            if not any(c in entrada.model_fields_set for c in _CAMPOS_DE_CONSUMO):
                for campo in _CAMPOS_DE_CONSUMO:
                    opcao[campo] = anterior.get(campo)
            for campo in _CAMPOS_PRESERVADOS_UM_A_UM:
                if campo not in entrada.model_fields_set:
                    opcao[campo] = anterior.get(campo)
        resultado.append(opcao)
    return resultado


@router.get("/grupos-personalizacao")
async def listar_grupos(_: dict = Depends(gestor_atual)) -> List[dict]:
    db = obter_db()
    grupos = (
        await db[COLECOES["grupos_personalizacao"]]
        .find({}, {"_id": 0})
        .sort("nome", 1)
        .to_list(200)
    )
    # **`e_variante` calculado AQUI e não adivinhado no ecrã.** É o grupo do
    # TAMANHO — o único cujas opções podem apontar para outro artigo do Vendus
    # (ver `precos.id_vendus_da_variante`), e é ele que decide se o backoffice
    # mostra a ligação em cada opção.
    #
    # Vai no ar em vez de o ecrã repetir a regra: uma segunda cópia da
    # heurística no JavaScript acabava a discordar desta, e o dia em que
    # discordassem o dono via o campo, preenchia-o, e a emissão ignorava-o —
    # sem erro nenhum.
    for grupo in grupos:
        grupo["e_variante"] = e_grupo_de_variante(grupo.get("nome"))
    return grupos


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
    # O grupo lê-se ANTES de se escrever, para o consumo que o pedido não
    # mencionar poder ser preservado. Ver `_preserva_o_consumo_que_o_pedido_
    # nao_falou`: sem esta leitura não há com o que comparar, e o `$set` do
    # modelo inteiro apagava as gramagens.
    gravado = await db[COLECOES["grupos_personalizacao"]].find_one({"id": grupo_id}, {"_id": 0})
    if gravado is None:
        raise HTTPException(status_code=404, detail="Grupo de personalização não encontrado")

    grupo = dados.model_dump()
    grupo["opcoes"] = _preserva_o_que_o_pedido_nao_falou(
        _opcoes_com_id(grupo["opcoes"]), dados.opcoes, gravado.get("opcoes") or []
    )
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
    # **O que ESTE artigo custa a fazer** — opcional, e é o que acende as
    # colunas "Custos" e "Resultado" dos relatórios. Sem ele o relatório mostra
    # "—" nessas células: um zero ali fazia o lucro parecer total, que é a
    # mentira mais cara que um relatório pode contar.
    #
    # É um número escrito à mão, e é assumidamente o degrau antes da ficha
    # técnica (a receita por ingrediente, que há-de calcular isto sozinha). O
    # campo fica o mesmo; o que muda é quem o preenche.
    preco_custo: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
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


@router.get("/produtos/sem-vendus")
async def produtos_sem_vendus(_: dict = Depends(gestor_atual)) -> List[dict]:
    """Os produtos que a emissão NÃO consegue ligar a um artigo do Vendus.

    A pergunta do dono — «estão todos os artigos ligados a um produto no
    Vendus, para não ficar a criar artigo de cada vez que faz uma fatura?» —
    tinha resposta no ecrã, mas um produto de cada vez: um ícone pequeno ao
    lado da linha da tabela. Ninguém percorre 200 produtos à mão, e por isso
    a resposta na prática era «não sei».

    **A regra é a da emissão, e não uma cópia dela.** Quem decide é
    `precos.id_vendus_do_produto` — a MESMA função que monta o `id` da linha
    em `precos.linha_de_venda`. Reimplementar aqui "tem vendus_ref?" era uma
    segunda leitura da mesma verdade, e a divergência apareceria no pior
    sítio: o ecrã a dizer que está tudo ligado enquanto o Vendus enche de
    órfãos. Assim, o vazio, o texto (`VACA…`), o zero e o negativo caem todos
    do mesmo lado — porque é assim que a fatura os trata.

    Sem `id`, o Vendus não casa a linha pelo título: cria um produto novo e
    inventa-lhe um código. Medido na conta real: 14 "Açaí Mini", 13 deles sem
    categoria nenhuma. A 5 lojas × ~200 vendas/dia, o catálogo do Vendus fica
    inutilizável em semanas.

    O `ativo` viaja tal e qual para o ecrã os poder separar: um produto
    desligado não está na grelha do POS, e prometer "cada venda cria um
    artigo" sobre um que ninguém vende era assustar por nada.
    """
    db = obter_db()
    produtos = await db[COLECOES["produtos"]].find({}, {"_id": 0}).sort("nome", 1).to_list(2000)
    return [p for p in produtos if id_vendus_do_produto(p) is None]


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
