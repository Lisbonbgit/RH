"""A conta do balcão — Plano 2B, Task 2 (spec §7.3/§7.4, `fat_vendas`).

A operadora vai tocando em produtos no ecrã; cada toque junta uma linha a
esta conta. Uma venda nasce `aberta` e sai daqui por um de dois caminhos:
`emitida` (Plano 2B Task 3, `fiscal.py`) — depois disso, nenhuma alteração é
aceite aqui: emitir corta a fatura, e alterar uma conta já faturada é
exactamente o tipo de coisa que obriga a uma nota de crédito — ou
`cancelada`, a conta que o cliente desistiu de levar.

Regras que não se negoceiam (brief da Task 2):

- **A sessão e o operador vêm SEMPRE do token, nunca do corpo.** Os modelos
  de entrada nem sequer declaram esses campos — mesmo padrão de
  `faturacao/caixa.py` (ver a docstring desse módulo). A venda resolve a
  sessão a partir da caixa indicada + a loja do operador autenticado,
  reutilizando `_obter_caixa_da_loja`/`_sessao_aberta` de `caixa.py` — a
  MESMA resolução, não uma segunda implementação que podia divergir.
- **Os totais derivam sempre de `precos.linha_de_venda`** — a mesma função
  que vai construir as linhas que saem para o Vendus na Task 3. Este módulo
  NUNCA soma preços "por fora": cada linha guardada é um conjunto de
  ingredientes brutos (produto, quantidade, opções, overrides), e o total é
  sempre recalculado chamando `linha_de_venda` sobre eles. Uma só fonte de
  verdade — senão o que a operadora vê no ecrã e o que sai no papel
  divergiam ao cêntimo, sem ninguém perceber porquê.
- **Um produto sem IVA (ou sem preço) definido não entra na conta.** Erro
  claro (422, reaproveitando `precos.erros_do_produto` — a mesma função que
  já avisa disto no ecrã "Produtos sem IVA" do catálogo), nunca um valor
  assumido. Isto é verificado no PRODUTO do catálogo, antes de qualquer
  override: um override é para ajustar uma linha excepcionalmente, não para
  contornar um artigo mal configurado.
- **Uma venda já emitida (ou cancelada) recusa qualquer alteração.** Todas as
  rotas que escrevem confirmam `estado == "aberta"` antes de tocar em nada.
"""
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from .caixa import _obter_caixa_da_loja, _sessao_aberta
from .db import COLECOES, obter_db
from .pos_auth import operador_atual
from .precos import _tem_mais_de_2_casas_decimais, erros_do_produto, linha_de_venda

router = APIRouter()

_MSG_VENDA_INEXISTENTE = "Venda não encontrada."
_MSG_VENDA_NAO_ABERTA = "Esta venda já foi emitida ou cancelada — não aceita alterações."
_MSG_LINHA_INEXISTENTE = "Linha não encontrada nesta venda."
_MSG_PRODUTO_INEXISTENTE = "Produto não encontrado."


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _recusa_mais_de_2_casas(v):
    """Mesmo crivo de precos.py, reutilizado e não reescrito — usado aqui só
    para os campos que `linha_de_venda` NÃO valida por si (o desconto
    GLOBAL, que actua sobre a venda inteira, não sobre uma linha)."""
    if v is not None and _tem_mais_de_2_casas_decimais(v):
        raise ValueError(
            "O valor %s tem mais de 2 casas decimais — a conta recusa-o "
            "para não perder um cêntimo no arredondamento." % v
        )
    return v


class PedidoNovaVenda(BaseModel):
    caixa_id: str = Field(min_length=1)


class PedidoJuntarLinha(BaseModel):
    produto_id: str = Field(min_length=1)
    quantidade: int = Field(default=1, ge=1)
    opcoes: List[Dict] = Field(default_factory=list)
    preco_override: Optional[float] = None
    tax_override: Optional[str] = None
    desconto_pct: Optional[float] = Field(default=None, ge=0, le=100)
    desconto_eur: Optional[float] = Field(default=None, ge=0)


class PedidoEditarLinha(BaseModel):
    # Tudo opcional: só os campos PRESENTES no pedido são alterados (lidos
    # com model_dump(exclude_unset=True)) — permite, por exemplo, limpar um
    # preco_override de volta a None sem ter de repetir o resto da linha.
    quantidade: Optional[int] = Field(default=None, ge=1)
    opcoes: Optional[List[Dict]] = None
    preco_override: Optional[float] = None
    tax_override: Optional[str] = None
    desconto_pct: Optional[float] = Field(default=None, ge=0, le=100)
    desconto_eur: Optional[float] = Field(default=None, ge=0)


class PedidoDescontoGlobal(BaseModel):
    desconto_pct: Optional[float] = Field(default=None, ge=0, le=100)
    desconto_eur: Optional[float] = Field(default=None, ge=0)

    @field_validator("desconto_eur")
    @classmethod
    def _valida_eur(cls, v):
        return _recusa_mais_de_2_casas(v)


async def _obter_venda_da_loja(db, venda_id: str, loja_id: str) -> Dict:
    """Confirma que a venda existe E pertence à loja do operador autenticado
    — mesmo raciocínio de `_obter_caixa_da_loja` em caixa.py: o âmbito nunca
    é só o id."""
    venda = await db[COLECOES["vendas"]].find_one({"id": venda_id})
    if not venda or venda.get("loja_id") != loja_id:
        raise HTTPException(status_code=404, detail=_MSG_VENDA_INEXISTENTE)
    return venda


def _garante_aberta(venda: Dict) -> None:
    if venda.get("estado") != "aberta":
        raise HTTPException(status_code=409, detail=_MSG_VENDA_NAO_ABERTA)


def _produto_snapshot(linha: Dict) -> Dict:
    """O que `linha_de_venda` precisa de um "produto", tirado do retrato
    gravado na própria linha (nome/preço/tax_id no momento em que foi
    adicionada) — não do catálogo ao vivo, que pode ter mudado ou ter sido
    apagado entretanto."""
    return {
        "nome": linha.get("produto_nome"),
        "preco": linha.get("produto_preco"),
        "tax_id": linha.get("produto_tax_id"),
    }


def _linha_vendus(linha: Dict) -> Dict:
    """A linha no formato do Vendus, sempre construída por
    `precos.linha_de_venda` — nunca calculada aqui à parte (ver a docstring
    do módulo). Um `ValueError` de `linha_de_venda` (produto sem preço/IVA,
    override inválido, mais de 2 casas decimais) vira um 422 claro."""
    try:
        return linha_de_venda(
            _produto_snapshot(linha),
            linha.get("quantidade", 1),
            linha.get("opcoes"),
            linha.get("preco_override"),
            linha.get("tax_override"),
            linha.get("desconto_pct"),
            linha.get("desconto_eur"),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


def _bruto_da_linha(li_vendus: Dict) -> float:
    return round(li_vendus["qty"] * li_vendus["gross_price"], 2)


def _desconto_da_linha(li_vendus: Dict) -> float:
    """O desconto EM EUROS que esta linha, sozinha, já dá — seja ele
    guardado em euros ou em percentagem (o Vendus só aceita um dos dois por
    linha, ver precos.linha_de_venda)."""
    if "discount_amount" in li_vendus:
        return round(li_vendus["discount_amount"], 2)
    if "discount_percentage" in li_vendus:
        return round(_bruto_da_linha(li_vendus) * li_vendus["discount_percentage"] / 100, 2)
    return 0.0


def _desconto_global_eur(venda: Dict, base: float) -> float:
    """O desconto da conta TODA, em euros — o € tem precedência sobre a
    percentagem, mesma regra do desconto por linha. Incide sobre `base`
    (o líquido depois dos descontos por linha): é o ÚLTIMO passo, não um
    desconto em paralelo com os que já foram dados linha a linha."""
    eur = venda.get("desconto_global_eur")
    pct = venda.get("desconto_global_pct")
    if eur:
        return round(float(eur), 2)
    if pct:
        return round(base * float(pct) / 100, 2)
    return 0.0


def _totais(venda: Dict) -> Dict:
    linhas_vendus = [_linha_vendus(li) for li in venda.get("linhas", [])]
    subtotal = round(sum(_bruto_da_linha(li) for li in linhas_vendus), 2)
    desconto_linhas = round(sum(_desconto_da_linha(li) for li in linhas_vendus), 2)
    liquido_linhas = round(subtotal - desconto_linhas, 2)
    desconto_global = _desconto_global_eur(venda, liquido_linhas)
    total = round(liquido_linhas - desconto_global, 2)
    return {
        "subtotal": subtotal,
        "desconto_linhas": desconto_linhas,
        "desconto_global": desconto_global,
        "total": total,
    }


def _venda_publica(venda: Dict) -> Dict:
    return {
        "id": venda["id"],
        "loja_id": venda["loja_id"],
        "caixa_id": venda["caixa_id"],
        "sessao_id": venda["sessao_id"],
        "operador_id": venda["operador_id"],
        "linhas": venda.get("linhas", []),
        "desconto_global_pct": venda.get("desconto_global_pct"),
        "desconto_global_eur": venda.get("desconto_global_eur"),
        "estado": venda["estado"],
        "criada_em": venda["criada_em"],
        "totais": _totais(venda),
    }


@router.post("/pos/venda", status_code=201)
async def abrir_venda(dados: PedidoNovaVenda, operador: Dict = Depends(operador_atual)) -> dict:
    db = obter_db()
    await _obter_caixa_da_loja(db, dados.caixa_id, operador["loja_id"])
    sessao = await _sessao_aberta(db, dados.caixa_id)

    venda = {
        "id": str(uuid.uuid4()),
        "loja_id": operador["loja_id"],
        "caixa_id": dados.caixa_id,
        "sessao_id": sessao["id"],
        "operador_id": operador.get("operador_id"),
        "linhas": [],
        "desconto_global_pct": None,
        "desconto_global_eur": None,
        "estado": "aberta",
        "criada_em": _agora(),
    }
    await db[COLECOES["vendas"]].insert_one(dict(venda))
    return _venda_publica(venda)


# Declarada ANTES de todas as rotas com {venda_id}: o FastAPI serve a
# PRIMEIRA rota que casa com o caminho, e uma `GET /pos/venda/{venda_id}`
# acrescentada acima desta engolia "aberta" como se fosse um id de venda — a
# operadora apanhava um 404 e voltava a picar a conta toda. Hoje nenhuma rota
# de {venda_id} tem só três segmentos (nem aqui nem em fiscal.py), por isso o
# conflito ainda não existe; esta ordem é a defesa contra a rota que vier a
# seguir. Provado em test_venda.py, no router montado de verdade.
@router.get("/pos/venda/aberta")
async def venda_aberta(
    caixa_id: str, operador: Dict = Depends(operador_atual)
) -> Optional[dict]:
    """A conta em curso desta caixa — ou `null`, se não houver nenhuma.

    Sem isto, `POST /pos/venda` era a única entrada e criava SEMPRE uma conta
    nova: a tela de descanso ao fim de 5 minutos, um F5 no PC da loja ou um
    browser que vai abaixo faziam a operadora perder o que já tinha picado
    (com o cliente à frente) e deixavam para trás uma venda `aberta` órfã em
    fat_vendas por cada recarregamento, para sempre.

    O âmbito é a SESSÃO aberta da caixa, e NÃO o operador — decisão, não
    esquecimento: ao balcão a conta é da caixa, não da pessoa. Se a Rafaela
    picar três artigos e a Ana entrar a seguir com o PIN dela (a tela de
    descanso caiu, é o cliente que está à espera), a conta tem de continuar
    lá. Quem fez a venda continua registado em `operador_id`.

    Sem sessão aberta, o 409 de `_sessao_aberta` está certo: sem caixa aberta
    não há conta nenhuma para recuperar. Sem venda aberta, 200 com `null` —
    é o estado normal do início do dia, não um erro.
    """
    db = obter_db()
    await _obter_caixa_da_loja(db, caixa_id, operador["loja_id"])
    sessao = await _sessao_aberta(db, caixa_id)

    # A MAIS RECENTE. Uma sessão pode ter várias contas abertas ao mesmo
    # tempo (o `POST /pos/venda` cria sempre uma nova, e as órfãs de antes
    # desta rota continuam lá); a que a operadora tem à frente é sempre a
    # última que abriu, nunca a primeira que o Mongo calhar devolver.
    abertas = await (
        db[COLECOES["vendas"]]
        .find({"sessao_id": sessao["id"], "estado": "aberta"})
        .sort("criada_em", -1)
        .to_list(1)
    )
    # Mesmo formato de `_venda_publica` (com `totais`) das outras rotas: o
    # ecrã não pode ter dois formatos diferentes da mesma conta, um para
    # quando a abre e outro para quando a recupera.
    return _venda_publica(abertas[0]) if abertas else None


@router.post("/pos/venda/{venda_id}/linhas", status_code=201)
async def juntar_linha(
    venda_id: str, dados: PedidoJuntarLinha, operador: Dict = Depends(operador_atual)
) -> dict:
    db = obter_db()
    venda = await _obter_venda_da_loja(db, venda_id, operador["loja_id"])
    _garante_aberta(venda)

    produto = await db[COLECOES["produtos"]].find_one({"id": dados.produto_id}, {"_id": 0})
    if not produto:
        raise HTTPException(status_code=404, detail=_MSG_PRODUTO_INEXISTENTE)

    # A regra que não se negoceia (brief da Task 2): sem preço/IVA no
    # PRÓPRIO produto do catálogo, nem entra na conta — independentemente de
    # a operadora vir a dar um override a seguir. Reaproveita a mesma função
    # que já avisa disto no ecrã "Produtos sem IVA" do catálogo.
    erros = erros_do_produto(produto)
    if erros:
        raise HTTPException(status_code=422, detail="; ".join(erros))

    linha = {
        "id": str(uuid.uuid4()),
        "produto_id": produto["id"],
        "produto_nome": produto.get("nome"),
        "produto_preco": produto.get("preco"),
        "produto_tax_id": produto.get("tax_id"),
        "quantidade": dados.quantidade,
        "opcoes": dados.opcoes,
        "preco_override": dados.preco_override,
        "tax_override": dados.tax_override,
        "desconto_pct": dados.desconto_pct,
        "desconto_eur": dados.desconto_eur,
    }
    _linha_vendus(linha)  # valida (levanta 422 antes de gravar, se algo bater mal)

    linhas = venda.get("linhas", [])
    linhas.append(linha)
    await db[COLECOES["vendas"]].update_one({"id": venda_id}, {"$set": {"linhas": linhas}})
    return _venda_publica(venda)


@router.put("/pos/venda/{venda_id}/linhas/{linha_id}")
async def editar_linha(
    venda_id: str, linha_id: str, dados: PedidoEditarLinha, operador: Dict = Depends(operador_atual)
) -> dict:
    db = obter_db()
    venda = await _obter_venda_da_loja(db, venda_id, operador["loja_id"])
    _garante_aberta(venda)

    linhas = venda.get("linhas", [])
    alvo = next((li for li in linhas if li["id"] == linha_id), None)
    if alvo is None:
        raise HTTPException(status_code=404, detail=_MSG_LINHA_INEXISTENTE)

    alteracoes = dados.model_dump(exclude_unset=True)
    candidata = dict(alvo)
    candidata.update(alteracoes)
    _linha_vendus(candidata)  # valida a versão editada ANTES de gravar

    alvo.update(alteracoes)
    await db[COLECOES["vendas"]].update_one({"id": venda_id}, {"$set": {"linhas": linhas}})
    return _venda_publica(venda)


@router.delete("/pos/venda/{venda_id}/linhas/{linha_id}")
async def remover_linha(
    venda_id: str, linha_id: str, operador: Dict = Depends(operador_atual)
) -> dict:
    db = obter_db()
    venda = await _obter_venda_da_loja(db, venda_id, operador["loja_id"])
    _garante_aberta(venda)

    linhas = venda.get("linhas", [])
    restantes = [li for li in linhas if li["id"] != linha_id]
    if len(restantes) == len(linhas):
        raise HTTPException(status_code=404, detail=_MSG_LINHA_INEXISTENTE)

    venda["linhas"] = restantes
    await db[COLECOES["vendas"]].update_one({"id": venda_id}, {"$set": {"linhas": restantes}})
    return _venda_publica(venda)


@router.put("/pos/venda/{venda_id}/desconto")
async def aplicar_desconto_global(
    venda_id: str, dados: PedidoDescontoGlobal, operador: Dict = Depends(operador_atual)
) -> dict:
    db = obter_db()
    venda = await _obter_venda_da_loja(db, venda_id, operador["loja_id"])
    _garante_aberta(venda)

    atualizacao = {
        "desconto_global_pct": dados.desconto_pct,
        "desconto_global_eur": dados.desconto_eur,
    }
    venda.update(atualizacao)
    await db[COLECOES["vendas"]].update_one({"id": venda_id}, {"$set": atualizacao})
    return _venda_publica(venda)


@router.post("/pos/venda/{venda_id}/cancelar")
async def cancelar_venda(venda_id: str, operador: Dict = Depends(operador_atual)) -> dict:
    """Deita fora uma conta aberta: o cliente desistiu, ou a operadora
    começou a picar na caixa errada.

    Passa-a a `cancelada`, e é isso que a tira da frente — deixa de ser
    devolvida por `GET /pos/venda/aberta` e nenhuma rota deste módulo volta a
    aceitar alterações nela (`_garante_aberta`).

    Só se cancela o que está ABERTO. Uma venda `emitida` tem uma Fatura
    Simplificada REAL entregue à AT: mudar-lhe o estado à socapa apagava do
    nosso sistema um documento que continua a existir lá fora — isso
    corrige-se com uma nota de crédito, nunca aqui. Cancelar uma já
    cancelada cai no mesmo 409 de propósito: a idempotência não interessa a
    ninguém ao balcão, mas dizer à operadora que aquela conta já estava
    cancelada interessa.
    """
    db = obter_db()
    venda = await _obter_venda_da_loja(db, venda_id, operador["loja_id"])
    _garante_aberta(venda)

    # A escrita é CONDICIONADA a {"estado": "aberta"} — a mesma técnica de I2
    # em caixa.py, e aqui pela pior das razões: entre o `_garante_aberta`
    # acima e esta linha, o `finalizar` (fiscal.py) pode ter emitido esta
    # mesma venda. Um $set incondicional carimbava "cancelada" por cima de
    # uma venda que ACABOU de receber uma Fatura Simplificada real, e ela
    # sumia-se do fecho de caixa (`caixa_math.soma_vendas_dinheiro` só soma
    # as `emitida`): o dinheiro ficava na gaveta sem nada que o explicasse.
    # É o `matched_count`, não a leitura de cima, que decide esta corrida.
    atualizacao = {"estado": "cancelada", "cancelada_em": _agora()}
    resultado = await db[COLECOES["vendas"]].update_one(
        {"id": venda_id, "estado": "aberta"}, {"$set": atualizacao}
    )
    if resultado.matched_count == 0:
        raise HTTPException(status_code=409, detail=_MSG_VENDA_NAO_ABERTA)

    venda.update(atualizacao)
    return _venda_publica(venda)
