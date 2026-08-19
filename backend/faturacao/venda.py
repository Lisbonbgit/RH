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

from .caixa import _obter_caixa_da_loja, _quem, _sessao_aberta
from .db import COLECOES, obter_db
from .pos_auth import operador_atual
from .precos import _tem_mais_de_2_casas_decimais, erros_do_produto, linha_de_venda

router = APIRouter()

_MSG_VENDA_INEXISTENTE = "Venda não encontrada."
_MSG_VENDA_NAO_ABERTA = "Esta venda já foi emitida ou cancelada — não aceita alterações."
_MSG_LINHA_INEXISTENTE = "Linha não encontrada nesta venda."
_MSG_PRODUTO_INEXISTENTE = "Produto não encontrado."
# A MESMA mensagem para as cinco rotas de escrita (juntar/editar/remover
# linha, desconto global, cancelar): o que a operadora precisa de saber é
# igual nas cinco — esta conta está TRAVADA e quem a destranca é o gestor,
# depois de olhar para o Vendus. Deixou de dizer "não pode ser cancelada"
# porque deixou de ser só sobre o cancelamento.
_MSG_VENDA_COM_EMISSAO = (
    "Esta conta tem uma emissão de fatura em curso ou por confirmar — está "
    "travada e não aceita alterações nem cancelamento. Chame o gestor: só "
    "depois de se confirmar no Vendus se a Fatura Simplificada chegou a sair "
    "é que se sabe o que fazer a esta conta."
)
# As duas mensagens do cancelamento COMPENSADO (ver `_porque_nao_foi_cancelada`):
# o 409 tem de descrever a conta como ela está no instante em que a operadora
# o lê, e não como estava quando a compensação começou.
_MSG_VENDA_EMITIDA_ENTRETANTO = (
    "Esta conta NÃO foi cancelada: a fatura saiu mesmo, mesmo agora — a "
    "Fatura Simplificada está entregue à Autoridade Tributária. Uma venda "
    "faturada não se cancela; o que estiver errado nela corrige-se com uma "
    "nota de crédito."
)
_MSG_CANCELAMENTO_ABORTADO_SEM_EMISSAO = (
    "Esta conta NÃO foi cancelada: estava a decorrer uma emissão, que "
    "entretanto foi abortada sem chegar a emitir — NÃO saiu nenhuma Fatura "
    "Simplificada e a conta está outra vez aberta. Carregue em Cancelar "
    "outra vez."
)


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


async def _tem_reserva_fiscal(db, venda_id: str) -> bool:
    """Existe uma reserva de emissão para esta venda?

    O `estado` da venda não conta a história toda: `fiscal.py::_reservar`
    insere um documento em `fat_refs_fiscais` ANTES de falar com o Vendus, e
    a venda só passa a `emitida` no fim (`_gravar_documento`). Entre as duas
    coisas — que são segundos de espera pela resposta do Vendus, ou horas se
    a reserva ficar `incerta` — a venda continua a dizer `aberta` enquanto
    pode estar a nascer uma Fatura Simplificada real do outro lado.

    A pergunta é pelo `venda_id` e NÃO pela `ext_ref`: a fórmula da ext_ref é
    a chave da idempotência e não pode ter uma segunda fonte (uma cópia dela
    aqui divergia no dia em que a original mudasse, e a idempotência morria
    em silêncio); e importar `ext_ref_determinista` de `fiscal.py` fechava um
    ciclo, porque é o `fiscal.py` que importa deste módulo. O campo
    `venda_id` é gravado em toda a reserva desde sempre, e é por ele que a
    gestão já liga as reservas às vendas (`fiscal.py::listar_reservas_presas`).
    """
    reserva = await db[COLECOES["refs_fiscais"]].find_one({"venda_id": venda_id})
    return reserva is not None


async def _garante_sem_emissao(db, venda_id: str) -> None:
    """**Uma venda com reserva fiscal fica CONGELADA** — nenhuma das rotas de
    escrita lhe toca até a reserva desaparecer ou a venda ficar `emitida`.

    `_garante_aberta` sozinho é o critério insuficiente que a docstring de
    `_tem_reserva_fiscal` descreve, e não era só o cancelamento que decidia
    por ele: `juntar_linha`, `editar_linha`, `remover_linha` e
    `aplicar_desconto_global` decidiam TODAS só com ele. O estrago, medido
    num guião de reprodução: o Vendus dá timeout, a verificação também falha,
    a reserva fica `incerta` e a venda fica `aberta` (é o desenho, ver
    `fiscal.py::VerificacaoFiscalIncerta`) — a FS de 8,99 € até pode ter
    saído. A conta continua no ecrã, aceita um segundo açaí (201) e um
    desconto de 10 % (200), e mais tarde a retoma encontra o documento
    original e liga-lhe a venda: fica no sistema uma venda `emitida` de
    16,18 € contra um documento fiscal real de 8,99 €. O Z não apanha a
    divergência (soma os `pagamentos`, não os `_totais`) e ela não aparece em
    lado nenhum.

    Factorizada, e não copiada cinco vezes, por uma razão concreta: no dia em
    que este critério mudar (uma reserva com idade, uma reserva de outra
    sessão), tem de mudar nos cinco sítios ao mesmo tempo — quatro em cinco
    era exactamente o estado que isto veio corrigir."""
    if await _tem_reserva_fiscal(db, venda_id):
        raise HTTPException(status_code=409, detail=_MSG_VENDA_COM_EMISSAO)


async def _porque_nao_foi_cancelada(db, venda_id: str) -> str:
    """A mensagem do 409 do cancelamento compensado — escolhida pelo estado
    que a conta tem NO MOMENTO EM QUE A MENSAGEM É ENVIADA, e não pelo que
    ela tinha quando a compensação começou.

    A3 (achado desta ronda, sem estrago fiscal mas com estrago humano): o
    cancelar escrevia `cancelada`, a releitura do `finalizar` via-a, libertava
    a reserva e abortava sem emitir, e a compensação repunha `aberta`. A conta
    acabava `aberta`, sem reserva e sem emissão nenhuma — e a operadora ouvia
    "esta conta tem uma emissão de fatura em curso... Chame o gestor". Bastava
    voltar a carregar em Cancelar. Chamar o gestor a uma loja cheia por causa
    de uma conta perfeitamente boa é o mesmo tipo de erro que dizer "tente
    novamente" onde não se pode tentar — só que ao contrário.

    As três saídas possíveis, todas verdadeiras no instante em que se lêem:
    1. a venda ficou `emitida` — a emissão ganhou mesmo, e o que a operadora
       precisa de saber é que a fatura SAIU (nota de crédito, nunca cancelar);
    2. a reserva ainda lá está — a emissão continua viva ou ficou por
       confirmar: é o caso em que o gestor faz falta, e a mensagem de sempre
       (`_MSG_VENDA_COM_EMISSAO`) está certa;
    3. nem uma coisa nem outra — a emissão abortou sem emitir e a conta está
       outra vez aberta: carregar de novo resolve."""
    venda = await db[COLECOES["vendas"]].find_one({"id": venda_id})
    estado = (venda or {}).get("estado")
    if estado == "emitida":
        return _MSG_VENDA_EMITIDA_ENTRETANTO
    if await _tem_reserva_fiscal(db, venda_id):
        return _MSG_VENDA_COM_EMISSAO
    if estado == "aberta":
        return _MSG_CANCELAMENTO_ABORTADO_SEM_EMISSAO
    # Estado inesperado (a venda desapareceu, ou ficou num estado que este
    # módulo não escreve): não se inventa um diagnóstico — vale a mensagem
    # mais conservadora, a que manda confirmar antes de mexer.
    return _MSG_VENDA_COM_EMISSAO


async def _escrever_se_ainda_aberta(db, venda_id: str, atualizacao: Dict) -> None:
    """A escrita das QUATRO rotas de alteração (juntar/editar/remover linha e
    desconto global), sempre CONDICIONADA a `{"estado": "aberta"}` — e é o
    `matched_count`, não o `_garante_aberta` lá de cima, que decide.

    As cinco rotas de escrita já tinham todas a PERGUNTA
    (`_garante_sem_emissao`); só o `cancelar_venda` é que tinha também a
    escrita condicional. As outras quatro escreviam
    `update_one({"id": venda_id}, ...)` sem condição nenhuma, e entre a
    pergunta e a escrita ainda há `await`s (o `find_one` do produto em
    `juntar_linha`, o próprio I/O da escrita) — janela estreita, mas
    suficiente: reproduzido em processo, com a emissão a correr INTEIRA
    nessa janela, ficava no Mongo uma venda `emitida` com 2 linhas e
    17,98 € contra um documento fiscal REAL de 8,99 €. E ninguém dava por
    isso: o Z soma os `pagamentos`, não os `_totais`.

    A mensagem é a de sempre (`_MSG_VENDA_NAO_ABERTA`) porque descreve
    exactamente o estado em que a conta ficou — emitida ou cancelada por
    quem chegou primeiro."""
    resultado = await db[COLECOES["vendas"]].update_one(
        {"id": venda_id, "estado": "aberta"}, {"$set": atualizacao}
    )
    if resultado.matched_count == 0:
        raise HTTPException(status_code=409, detail=_MSG_VENDA_NAO_ABERTA)


async def _emissao_por_confirmar(db, venda: Dict) -> bool:
    """O travão desta conta, tal como o ecrã do POS tem de o ver: existe uma
    reserva fiscal E a venda ainda não está `emitida` — exactamente o estado
    em que `_garante_sem_emissao` recusa qualquer escrita.

    A venda `emitida` responde `False` de propósito: a reserva de uma venda
    emitida NÃO desaparece (é ela que sustenta a idempotência, ver
    `fiscal.py::_gravar_documento`), por isso "tem reserva" sozinho marcaria
    para sempre como "por confirmar" toda a conta que correu bem.

    Isto vai à base de dados; `_venda_publica` é síncrono e não tem `db`, por
    isso a resposta compõe-se dos dois (ver o parâmetro
    `emissao_por_confirmar` lá em baixo)."""
    if venda.get("estado") == "emitida":
        return False
    return await _tem_reserva_fiscal(db, venda["id"])


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


def _venda_publica(venda: Dict, emissao_por_confirmar: bool = False) -> Dict:
    """A conta como o ecrã a vê.

    `emissao_por_confirmar` é o TRAVÃO desta conta (ver
    `_emissao_por_confirmar`) e chega aqui já calculado, em vez de ser lido
    aqui dentro: esta função é SÍNCRONA e não tem `db` — e continua a ser,
    porque `fiscal.py` também a usa e `_totais` (que ela chama) é o núcleo
    puro dos totais, que nenhum I/O tem de atravessar.

    O `False` por omissão nunca é uma adivinha; é verdade em cada um dos
    sítios que o usam:
    - as quatro rotas de escrita só chegam aqui DEPOIS de
      `_garante_sem_emissao` ter confirmado que não existe reserva;
    - `abrir_venda` acabou de gerar o `id` da venda neste instante — nenhuma
      reserva pode existir para um uuid que ainda ninguém viu;
    - a resposta de `fiscal.finalizar` traz a venda já `emitida`, que por
      definição responde `False` (ver `_emissao_por_confirmar`).
    Quem NÃO está nesse caso — `GET /pos/venda/aberta`, que é por onde o ecrã
    recupera uma conta que pode ter ficado travada — calcula-o e passa-o.

    O campo está SEMPRE na resposta, mesmo `False`: o ecrã não pode ter de
    adivinhar se a ausência da chave quer dizer "não há emissão pendente" ou
    "versão antiga da API" (mesma regra de `cancelada_em`/`cancelada_por`)."""
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
        # O cancelamento também se mostra: sem isto, `cancelada_em` era
        # escrito e nunca lido por ninguém — um dado cego. Quem cancelou é a
        # primeira pergunta quando falta dinheiro na gaveta ao fim do dia
        # (picar, receber, cancelar a conta é o esquema clássico ao balcão), e
        # a resposta não pode viver só dentro do Mongo. `None` nas contas que
        # não foram canceladas, que é a esmagadora maioria.
        "cancelada_em": venda.get("cancelada_em"),
        "cancelada_por": venda.get("cancelada_por"),
        # O travão, para o ecrã o poder MOSTRAR em vez de o guardar só na
        # memória do browser: até aqui o POS só sabia da emissão incerta pelo
        # 503 que tinha acabado de receber, e dois toques (um F5, a tela de
        # descanso, o browser a ir abaixo) apagavam essa memória — a conta
        # voltava a parecer normal e a operadora continuava a picar por cima
        # de uma fatura que podia ter saído. Agora vem do SERVIDOR em todas
        # as respostas de venda.
        "emissao_por_confirmar": emissao_por_confirmar,
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
        # Do TOKEN, nunca do corpo — como tudo o resto neste módulo. É o que
        # dá a `GET /pos/venda/aberta` o segundo âmbito que lhe faltava: ver
        # a docstring dessa rota, e `pos_auth.py::entrar`, que põe o
        # `dispositivo_id` no token do operador.
        "dispositivo_id": operador.get("dispositivo_id"),
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
    """A conta em curso deste PC — ou `null`, se não houver nenhuma.

    Sem isto, `POST /pos/venda` era a única entrada e criava SEMPRE uma conta
    nova: a tela de descanso ao fim de 5 minutos, um F5 no PC da loja ou um
    browser que vai abaixo faziam a operadora perder o que já tinha picado
    (com o cliente à frente) e deixavam para trás uma venda `aberta` órfã em
    fat_vendas por cada recarregamento, para sempre.

    O âmbito é a sessão aberta da caixa **e o dispositivo**, e NÃO o operador
    — as duas coisas são decisões, não esquecimentos:

    - Não é o operador, porque ao balcão a conta é do posto, não da pessoa.
      Se a Rafaela picar três artigos e a Ana entrar a seguir com o PIN dela
      (a tela de descanso caiu, é o cliente que está à espera), a conta tem de
      continuar lá. Quem fez a venda continua registado em `operador_id`.
    - É também o dispositivo, porque a sessão de caixa sozinha não chega. Uma
      loja com UMA caixa e dois PCs emparelhados (o "PC Balcão" e o "PC
      Drive-Thru" — é para isso que o `nome` do dispositivo existe, e
      `caixa.estado_caixa` resolve automaticamente essa única caixa para os
      dois) tinha os dois PCs a recuperar a MESMA conta: o cliente do balcão
      pagava o açaí do drive-thru. Não era uma corrida de milissegundos — era
      o estado estável dessa configuração, o dia inteiro.

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
    #
    # `dispositivo_id` vem do token (pos_auth.py::entrar), nunca da query.
    #
    # Um token emitido ANTES desta alteração não o traz, e as vendas abertas
    # com ele também não têm o campo. Filtrar por `None` casa, no Mongo, com
    # o campo AUSENTE e com o campo a `null` — é a semântica da igualdade a
    # null, e é o que faz esta mudança não precisar de migração nenhuma:
    # token antigo só encontra conta antiga, token novo só encontra conta
    # nova, e os dois nunca se cruzam. Não é suposição: os quatro
    # cruzamentos estão provados em test_venda.py.
    abertas = await (
        db[COLECOES["vendas"]]
        .find({
            "sessao_id": sessao["id"],
            "estado": "aberta",
            "dispositivo_id": operador.get("dispositivo_id"),
        })
        .sort("criada_em", -1)
        .to_list(1)
    )
    if not abertas:
        return None

    # Mesmo formato de `_venda_publica` (com `totais`) das outras rotas: o
    # ecrã não pode ter dois formatos diferentes da mesma conta, um para
    # quando a abre e outro para quando a recupera.
    #
    # É a ÚNICA rota de venda que tem mesmo de ir perguntar pelo travão à
    # base de dados, e é a que mais precisa dele: é por aqui que o ecrã
    # recupera a conta depois da tela de descanso, de um F5 ou de o browser
    # ir abaixo — precisamente os três acidentes que apagavam do browser a
    # memória de que a emissão desta conta ficou por confirmar.
    conta = abertas[0]
    return _venda_publica(conta, emissao_por_confirmar=await _emissao_por_confirmar(db, conta))


@router.post("/pos/venda/{venda_id}/linhas", status_code=201)
async def juntar_linha(
    venda_id: str, dados: PedidoJuntarLinha, operador: Dict = Depends(operador_atual)
) -> dict:
    db = obter_db()
    venda = await _obter_venda_da_loja(db, venda_id, operador["loja_id"])
    _garante_aberta(venda)
    await _garante_sem_emissao(db, venda_id)

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
    await _escrever_se_ainda_aberta(db, venda_id, {"linhas": linhas})
    return _venda_publica(venda)


@router.put("/pos/venda/{venda_id}/linhas/{linha_id}")
async def editar_linha(
    venda_id: str, linha_id: str, dados: PedidoEditarLinha, operador: Dict = Depends(operador_atual)
) -> dict:
    db = obter_db()
    venda = await _obter_venda_da_loja(db, venda_id, operador["loja_id"])
    _garante_aberta(venda)
    await _garante_sem_emissao(db, venda_id)

    linhas = venda.get("linhas", [])
    alvo = next((li for li in linhas if li["id"] == linha_id), None)
    if alvo is None:
        raise HTTPException(status_code=404, detail=_MSG_LINHA_INEXISTENTE)

    alteracoes = dados.model_dump(exclude_unset=True)
    candidata = dict(alvo)
    candidata.update(alteracoes)
    _linha_vendus(candidata)  # valida a versão editada ANTES de gravar

    alvo.update(alteracoes)
    await _escrever_se_ainda_aberta(db, venda_id, {"linhas": linhas})
    return _venda_publica(venda)


@router.delete("/pos/venda/{venda_id}/linhas/{linha_id}")
async def remover_linha(
    venda_id: str, linha_id: str, operador: Dict = Depends(operador_atual)
) -> dict:
    db = obter_db()
    venda = await _obter_venda_da_loja(db, venda_id, operador["loja_id"])
    _garante_aberta(venda)
    await _garante_sem_emissao(db, venda_id)

    linhas = venda.get("linhas", [])
    restantes = [li for li in linhas if li["id"] != linha_id]
    if len(restantes) == len(linhas):
        raise HTTPException(status_code=404, detail=_MSG_LINHA_INEXISTENTE)

    venda["linhas"] = restantes
    await _escrever_se_ainda_aberta(db, venda_id, {"linhas": restantes})
    return _venda_publica(venda)


@router.put("/pos/venda/{venda_id}/desconto")
async def aplicar_desconto_global(
    venda_id: str, dados: PedidoDescontoGlobal, operador: Dict = Depends(operador_atual)
) -> dict:
    db = obter_db()
    venda = await _obter_venda_da_loja(db, venda_id, operador["loja_id"])
    _garante_aberta(venda)
    await _garante_sem_emissao(db, venda_id)

    atualizacao = {
        "desconto_global_pct": dados.desconto_pct,
        "desconto_global_eur": dados.desconto_eur,
    }
    venda.update(atualizacao)
    await _escrever_se_ainda_aberta(db, venda_id, atualizacao)
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

    **"Aberta" não chega para decidir isto.** A emissão reserva em
    `fat_refs_fiscais` ANTES de falar com o Vendus (`fiscal.py::_reservar`) e
    só marca a venda `emitida` no fim — enquanto essa reserva existir, uma
    venda que diz `aberta` pode ter uma Fatura Simplificada real a nascer, ou
    já nascida e por confirmar. Eram dois estragos concretos:

    - A operadora carrega em FINALIZAR, a emissão fica à espera do Vendus, e
      ela carrega em Cancelar. Respondia-se "cancelada" — e a seguir o
      `_gravar_documento` punha `emitida` por cima (o $set dele não tem
      condição de estado nenhuma). Ela foi informada de que a conta tinha
      sido deitada fora enquanto saía uma FS com ATCUD, voltava a picar
      tudo, e o cliente levava DUAS faturas.
    - Pior: o Vendus dá timeout, a verificação também falha, e a reserva fica
      `incerta` com a venda `aberta` (é o desenho — ver
      VerificacaoFiscalIncerta). É essa conta que aparece como "conta em
      curso"; cancelá-la fazia desaparecer a última venda `aberta` ligada a
      uma FS que pode ter saído mesmo: o Z fecha curto
      (`caixa_math.soma_vendas_dinheiro` só soma as `emitida`) e a reserva
      incerta fica presa para sempre, só resolúvel com Mongo à mão.

    Por isso: reserva presente → 409 e o gestor. Nunca um "tente novamente",
    que só convidava a operadora a carregar outra vez no mesmo botão.
    """
    db = obter_db()
    venda = await _obter_venda_da_loja(db, venda_id, operador["loja_id"])
    _garante_aberta(venda)

    await _garante_sem_emissao(db, venda_id)

    # A escrita é CONDICIONADA a {"estado": "aberta"} — a mesma técnica de I2
    # em caixa.py, e aqui pela pior das razões: entre o `_garante_aberta`
    # acima e esta linha, o `finalizar` (fiscal.py) pode ter emitido esta
    # mesma venda. Um $set incondicional carimbava "cancelada" por cima de
    # uma venda que ACABOU de receber uma Fatura Simplificada real, e ela
    # sumia-se do fecho de caixa (`caixa_math.soma_vendas_dinheiro` só soma
    # as `emitida`): o dinheiro ficava na gaveta sem nada que o explicasse.
    # É o `matched_count`, não a leitura de cima, que decide esta corrida.
    #
    # `cancelada_por` fica gravado com o MESMO `_quem` do resto do módulo
    # (caixa.py, reutilizado e não reescrito): sem ele, o único nome na venda
    # era o `operador_id` de quem a ABRIU. A Rafaela abria e picava 24 €, a
    # Ana entrava com o PIN dela e cancelava, e ficava lá o nome da Rafaela —
    # a atribuição não estava só ausente, estava ERRADA, no vector de fraude
    # mais banal que há ao balcão (picar, receber o dinheiro, cancelar a
    # conta).
    atualizacao = {
        "estado": "cancelada",
        "cancelada_em": _agora(),
        "cancelada_por": _quem(operador),
    }
    resultado = await db[COLECOES["vendas"]].update_one(
        {"id": venda_id, "estado": "aberta"}, {"$set": atualizacao}
    )
    if resultado.matched_count == 0:
        raise HTTPException(status_code=409, detail=_MSG_VENDA_NAO_ABERTA)

    # A janela que a verificação lá de cima não fecha: entre ela e a escrita
    # acima, o `finalizar` pode ter reservado. Por isso pergunta-se OUTRA VEZ,
    # depois de escrever — e, se entretanto apareceu uma reserva, desfaz-se o
    # cancelamento.
    #
    # É uma compensação, não uma transacção (não temos transacções
    # multi-documento aqui), e é segura por três razões:
    # 1. A escrita é condicionada a {"estado": "cancelada"} — o único estado
    #    que a NOSSA escrita pode ter deixado. Se o `_gravar_documento` já
    #    tiver posto `emitida` por cima dela (o $set dele é incondicional),
    #    o filtro não casa e não lhe tocamos: uma compensação incondicional
    #    ressuscitava como `aberta` uma venda com FS real e ATCUD, que é
    #    precisamente o estrago que este código existe para evitar.
    # 2. Ninguém mais neste módulo escreve "cancelada", por isso a conta que
    #    reabrimos é a que nós próprios acabámos de fechar.
    # 3. `aberta` é o estado em que ela estava um segundo antes, e nada se
    #    perde: os carimbos do cancelamento voltam a `None` na mesma escrita.
    #
    # Em qualquer dos desfechos a operadora ouve o MESMO 409 — a conta não
    # foi cancelada, e é isso que ela precisa de saber antes de mexer em mais
    # alguma coisa. (No desfecho raro em que a venda já ficou `emitida`, os
    # carimbos do cancelamento ficam colados a ela; ficam à VISTA em
    # `_venda_publica`, e a venda conta como emitida no Z, que é o que
    # fiscalmente interessa — nenhuma escrita nossa pode limpá-los sem voltar
    # a correr o risco de mexer num documento fiscal real.)
    if await _tem_reserva_fiscal(db, venda_id):
        await db[COLECOES["vendas"]].update_one(
            {"id": venda_id, "estado": "cancelada"},
            {"$set": {"estado": "aberta", "cancelada_em": None, "cancelada_por": None}},
        )
        raise HTTPException(
            status_code=409, detail=await _porque_nao_foi_cancelada(db, venda_id)
        )

    venda.update(atualizacao)
    return _venda_publica(venda)
