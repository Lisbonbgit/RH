"""A NOTA DE CRÉDITO — o documento que corrige uma Fatura Simplificada já
entregue à Autoridade Tributária, e o dinheiro que ela devolve.

Uma NC é um documento fiscal REAL. Vale-lhe tudo o que `fiscal.py` endureceu
para a fatura, e por isso este ficheiro é uma releitura desse, com uma
diferença de fundo (a idempotência, ver já a seguir) e duas somas novas (o
travão do que já foi creditado, e a devolução a mexer — ou não — na gaveta).

## A idempotência: a referência é da INTENÇÃO, e não do documento de origem

A da fatura vem de `ext_ref_determinista`: `pos-{loja}-{sessão}-{venda}`, a
identidade da VENDA. Duas tentativas da mesma venda dão a mesma referência,
a reserva atómica recusa a segunda, e é isso que impede a fatura a dobrar.

**Aqui isso não serve, e a razão é a nota PARCIAL.** Contra a mesma fatura
pode haver várias notas de crédito — o cliente devolve hoje o refrigerante e
amanhã o açaí, e as duas são documentos legítimos e diferentes. Uma
referência derivada do documento de origem (`nc-{documento}`, que é o que o
POS da Pizzaria usa, e é por isso que lá só existe a NC TOTAL) tornava a
segunda impossível de emitir para sempre. Uma derivada do CONTEÚDO
(as linhas escolhidas) é pior ainda: duas devoluções legítimas e iguais — o
mesmo café devolvido duas vezes ao mesmo cliente — colidiam, e a segunda
devolução do dinheiro ficava por fazer sem ninguém perceber porquê.

**O que se faz em vez disso:** grava-se primeiro a INTENÇÃO da nota, com
identidade própria (`fat_notas_credito.id`, o uuid que o ecrã gera quando a
operadora abre a janela da nota de crédito), e a referência externa deriva
DELA: `pos-{loja}-{sessão}-nc-{intenção}`. As três propriedades que
interessam saem de graça:

- **o mesmo toque repetido é idempotente** — o ecrã manda o mesmo
  `intencao_id` em cada retentativa, o `insert_one` apanha
  `DuplicateKeyError` no índice único (db.py) e ninguém fala com o Vendus
  uma segunda vez;
- **uma nota NOVA é outra intenção** — outra janela, outro uuid, outra
  referência: a segunda parcial da mesma fatura passa;
- **a reconciliação do fecho continua a reconhecer o documento como nosso**
  — o prefixo `pos-{loja}-{sessão}-` é o que `fiscal._reconciliar_vendas_
  dinheiro` procura para separar os nossos documentos dos da app L'Açaí na
  mesma caixa API partilhada. A sessão que lá vai é a do turno em que o
  dinheiro se mexeu, que é o turno que a reconciliação está a fechar.

O `intencao_id` é validado como UUID: sem isso, um ecrã com um defeito (ou
alguém a mandar `"1"` à mão) podia colidir com a intenção de OUTRA loja, e a
resposta idempotente devolvia-lhe uma nota de crédito que não é dele. Com a
colisão fechada pelo formato, a resposta idempotente ainda confirma a loja e
a fatura antes de devolver o que quer que seja.

## O travão: duas parciais não podem somar mais do que a fatura tinha

`linhas_creditaveis` responde, por linha da fatura, quanto AINDA se pode
creditar — a quantidade original menos tudo o que já saiu em notas
anteriores. O travão é **do servidor** e é sobre a QUANTIDADE, não sobre o
euro: o ecrã mostra o máximo ao lado do campo, mas quem recusa é a rota, com
uma frase que diz quanto ainda dá.

Contam para o travão as notas `emitida` **e as `incerta`** — uma nota cuja
emissão ficou por apurar pode ter saído mesmo, e deixar creditar por cima
dela era arriscar creditar a mesma linha duas vezes. Para o DINHEIRO do
turno conta só a `emitida` (ver `caixa_math.por_tipo_de_pagamento`): o que
não se sabe se saiu não se desconta da gaveta.

## O dinheiro segue o meio de pagamento

Decisão do dono, nas palavras dele: «se a nota de crédito estiver lá que a
devolução foi em dinheiro, sim sai da gaveta. se não, sai dos outros
lugares.» Aqui isso é uma linha só — a devolução grava-se como um retrato do
tipo de pagamento escolhido (`devolucao`), e o Ponto de Caixa e o Z lêem-na
como um valor NEGATIVO nesse tipo, pelas mesmas funções que somam as vendas.
Não há uma segunda contabilidade das devoluções: se houvesse, haveria dois
números a explicar a mesma gaveta.

## O que a API do Vendus exige, e o que fica por confirmar

Ver `vendus/emissao.py::criar_nota_credito` — a citação da documentação
oficial está lá, e o que não se conseguiu confirmar (não há chave de API
nesta máquina) está lá dito como não confirmado, em vez de inventado.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from pymongo.errors import DuplicateKeyError

from .caixa import _obter_caixa_da_loja, _sessao_aberta
from .db import (
    COLECOES,
    indice_notas_credito_confirmado,
    obter_db,
)
from .documentos import _centimos, _documento_da_loja
from .fiscal import _ERROS_COM_PROVA_DE_QUE_NADA_SAIU, _itens_vendus
from .importacao import _nif_configurado
from .mapa_imposto import _liquido_da_linha, mapa_da_nota, totais_do_mapa
from .pos_auth import operador_atual
from .vendus.cliente import VendusErro, VendusIndisponivel, obter_conta
from .vendus.emissao import ClienteEmissaoVendus, _register_id_configurado

logger = logging.getLogger(__name__)

router = APIRouter()

# As quantidades comparam-se em INTEIROS, como o dinheiro — e com as mesmas 5
# casas decimais que o POS já usa nas partes de uma conta dividida
# (`lib/pos.js::CASAS_DA_QUANTIDADE_POS`): a parte de um açaí dividido por
# três é 0.33337. Comparar `0.1 + 0.2 <= 0.3` em vírgula flutuante é falso, e
# aqui essa falsidade é a operadora a levar com "só pode creditar 0,3" numa
# linha que tem exactamente 0,3 por creditar.
_CASAS_DA_QUANTIDADE = 5
_ESCALA_DA_QUANTIDADE = 10 ** _CASAS_DA_QUANTIDADE

_MSG_INDICE_EM_FALTA = (
    "O índice único das notas de crédito (fat_notas_credito.id) não está "
    "confirmado no arranque — o POS recusa emitir notas de crédito até isto "
    "ser corrigido, para nunca arriscar duas notas reais da mesma devolução."
)
_MSG_SO_SE_CREDITA_UMA_FATURA = (
    "Só se pode emitir uma nota de crédito sobre uma Fatura Simplificada. "
    "Este documento é %s."
)
_MSG_DOCUMENTO_SEM_NUMERO = (
    "Este documento não tem número gravado — e uma nota de crédito tem de "
    "dizer QUE documento rectifica, linha a linha. Sem o número não se emite; "
    "chame quem trata do sistema."
)
_MSG_SEM_CONTA_DE_ORIGEM = (
    "A conta de origem desta fatura já não está guardada — não há linhas para "
    "creditar. Uma nota de crédito desta fatura tem de ser feita no Vendus."
)
_MSG_SEM_LINHAS_ESCOLHIDAS = (
    "Escolha pelo menos um artigo para creditar."
)
_MSG_LINHA_REPETIDA = "O artigo nº %d aparece duas vezes no pedido."
_MSG_LINHA_INEXISTENTE = "Esta fatura não tem nenhum artigo nº %d."
_MSG_QUANTIDADE_NAO_POSITIVA = (
    "A quantidade a creditar de «%s» tem de ser maior do que zero."
)
_MSG_JA_CREDITADO = (
    "«%s» já foi creditado%s — desta fatura ainda só se pode creditar %s de "
    "%s. Uma nota de crédito não pode devolver mais do que a fatura cobrou."
)
_MSG_TOTAL_NAO_POSITIVO = (
    "O total a creditar tem de ser positivo — confirme as quantidades."
)
_MSG_MOTIVO_EM_FALTA = (
    "Escreva o motivo da nota de crédito: a lei obriga a que o documento diga "
    "porque é que rectifica a fatura, e é isso que sai impresso."
)
_MSG_TIPO_PAGAMENTO_INEXISTENTE = "Tipo de pagamento não encontrado ou inactivo."
_MSG_TIPO_PAGAMENTO_SEM_VENDUS = (
    "Este tipo de pagamento não tem um método do Vendus associado — não pode "
    "ser usado para devolver dinheiro numa nota de crédito real."
)
_MSG_EMISSAO_EM_CURSO = (
    "Esta nota de crédito já está a ser emitida neste momento — não se "
    "carrega duas vezes. Espere alguns segundos: se ela sair, aparece aqui "
    "sozinha; nada é emitido duas vezes."
)
_MSG_INTENCAO_DE_OUTRA_FATURA = (
    "O identificador desta devolução já foi usado noutra nota de crédito. "
    "Feche esta janela e abra a nota de crédito outra vez."
)
_MSG_NADA_SAIU = (
    "A nota de crédito NÃO foi emitida e nada foi enviado à Autoridade "
    "Tributária: %s. A fatura fica exactamente como estava e pode tentar "
    "outra vez."
)
_MSG_DESFECHO_INCERTO = (
    "NÃO se sabe se a nota de crédito chegou a ser emitida — o Vendus não "
    "respondeu de forma conclusiva. NÃO devolva o dinheiro e NÃO repita: "
    "chame o gestor, que confirma no Vendus se o documento saiu. Esta fatura "
    "fica travada para esta devolução até isso ser esclarecido."
)
_MSG_CONFLITO_DOCUMENTO = (
    "O Vendus devolveu uma nota de crédito que colide com outro documento já "
    "gravado — nada foi sobreposto, e isto precisa de investigação manual."
)
_MSG_SESSAO_FECHOU_ENTRETANTO = (
    "A caixa fechou enquanto esta nota de crédito era preparada — NADA foi "
    "enviado ao Vendus e nenhum dinheiro saiu. Abra a caixa e faça a "
    "devolução no turno novo, para o dinheiro entrar no Z certo."
)


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _quantidade_em_inteiros(quantidade) -> int:
    """Uma quantidade nos INTEIROS que ela vale, a 5 casas decimais — a
    mesma conversão que `_centimos` faz ao dinheiro, e pela mesma razão."""
    try:
        return int(round(float(quantidade or 0) * _ESCALA_DA_QUANTIDADE))
    except (TypeError, ValueError):
        return 0


def _quantidade_legivel(inteiros: int) -> float:
    return inteiros / _ESCALA_DA_QUANTIDADE


def ja_creditado_por_linha(notas: List[Dict]) -> Dict[int, int]:
    """Quanto já foi creditado de cada linha da fatura, em quantidade
    inteira (5 casas), somando as notas de crédito que CONTAM para o travão.

    Contam a `emitida` e a `incerta`. A `incerta` conta porque pode ter saído
    mesmo — creditar por cima dela era arriscar entregar à AT duas notas
    sobre a mesma linha, que é o estrago que este módulo inteiro existe para
    não fazer. Uma `reservada` (uma emissão a decorrer neste instante)
    também conta, pela mesma razão e ainda mais forte: ela pode estar a
    falar com o Vendus agora."""
    ja: Dict[int, int] = {}
    for nota in notas or []:
        if nota.get("estado") not in ("emitida", "incerta", "reservada"):
            continue
        for linha in nota.get("linhas") or []:
            indice = linha.get("indice")
            if indice is None:
                continue
            ja[indice] = ja.get(indice, 0) + _quantidade_em_inteiros(
                linha.get("quantidade"))
    return ja


def linhas_creditaveis(venda: Optional[Dict], notas: List[Dict]) -> List[Dict]:
    """As linhas da fatura como o ecrã da nota de crédito as mostra: Produto ·
    Qtd. (editável, com o MÁXIMO à vista) · Preço/Uni. · Total.

    **O `indice` é a identidade da linha, e é 1 a N pela ordem em que ela foi
    entregue à AT** (`fiscal._itens_vendus`, a MESMA função que construiu a
    fatura). É ele que vai no `document_row` do `reference_document` da nota
    de crédito, e é por ele que o travão sabe do que está a falar. Não é o
    `id` da linha da nossa conta: esse nunca chega ao Vendus.

    `disponivel` é o que AINDA se pode creditar. Uma linha inteiramente
    creditada fica na lista com `disponivel: 0` — some-la era pior: a
    operadora procurava o artigo que o cliente traz na mão, não o encontrava,
    e concluía que a fatura não era aquela."""
    itens = _itens_vendus(venda or {})
    ja = ja_creditado_por_linha(notas)
    creditaveis = []
    for posicao, item in enumerate(itens, start=1):
        original = _quantidade_em_inteiros(item.get("qty"))
        creditado = min(ja.get(posicao, 0), original)
        creditaveis.append({
            "indice": posicao,
            "titulo": item.get("title"),
            "tax_id": item.get("tax_id"),
            "quantidade": item.get("qty"),
            "creditado": _quantidade_legivel(creditado),
            "disponivel": _quantidade_legivel(max(0, original - creditado)),
            "preco_unitario": item.get("gross_price"),
            # O desconto da linha na FATURA — próprio dela mais a fatia do
            # desconto global que lhe calhou, já como a percentagem que
            # reproduz o cêntimo exacto (`fiscal._percentagem_que_reproduz`).
            # **Sem ele aqui, a nota de crédito devolvia o BRUTO**: uma fatura
            # com desconto era creditada por mais dinheiro do que a loja
            # recebeu. Vai junto com a linha, e não é recalculado noutro sítio
            # a partir da venda outra vez.
            "desconto_percentagem": item.get("discount_percentage"),
            # O id do produto no Vendus, tal como foi na fatura: é ele que
            # impede o Vendus de criar um produto NOVO a cada documento (a
            # conta real ficou com 14 "Açaí Mini" assim). Nunca sai para o
            # ecrã — ver `preparar_nota_credito`.
            "id_vendus": item.get("id"),
            # O líquido da linha INTEIRA, como a fatura o mostra — o que o
            # cliente pagou por ela, já com os descontos. Somado do lado do
            # servidor, como tudo o que é dinheiro neste módulo.
            "total": _liquido_da_linha(item),
        })
    return creditaveis


class NotaDeCreditoInvalida(Exception):
    """O pedido da operadora não pode virar nota de crédito nenhuma — e a
    mensagem diz porquê, em português de balcão. Vira 422 na rota."""


def _numero_legivel(inteiros: int) -> str:
    """Uma quantidade para a MENSAGEM: `1` e não `1.0`, `0,5` e não
    `0.50000` — a operadora lê isto com um cliente à frente."""
    valor = _quantidade_legivel(inteiros)
    if valor == int(valor):
        return str(int(valor))
    return ("%.5f" % valor).rstrip("0").rstrip(".").replace(".", ",")


def escolher_linhas(creditaveis: List[Dict], escolhas: List[Dict]) -> List[Dict]:
    """As linhas a creditar, validadas contra o que a fatura ainda tem — o
    TRAVÃO, e é do servidor.

    Devolve, por linha escolhida, o retrato que fica gravado na nota (e que o
    Z e o mapa de imposto vão ler): `indice`, `titulo`, `tax_id`,
    `quantidade`, `preco_unitario` e o `total` DESSA quantidade, calculado
    pela MESMA fórmula que o Vendus aplica linha a linha
    (`mapa_imposto._liquido_da_linha`) — nunca uma proporção do total da
    linha inteira, que dava outro cêntimo.

    Recusa, com a frase que diz o que fazer: uma linha repetida, uma que a
    fatura não tem, uma quantidade não positiva, e — a que interessa — uma
    quantidade acima do que ainda resta."""
    por_indice = {linha["indice"]: linha for linha in creditaveis}
    vistos = set()
    escolhidas = []
    for escolha in escolhas or []:
        indice = escolha.get("indice")
        if indice in vistos:
            raise NotaDeCreditoInvalida(_MSG_LINHA_REPETIDA % indice)
        vistos.add(indice)
        linha = por_indice.get(indice)
        if linha is None:
            raise NotaDeCreditoInvalida(_MSG_LINHA_INEXISTENTE % indice)

        pedida = _quantidade_em_inteiros(escolha.get("quantidade"))
        if pedida <= 0:
            raise NotaDeCreditoInvalida(
                _MSG_QUANTIDADE_NAO_POSITIVA % linha.get("titulo"))
        disponivel = _quantidade_em_inteiros(linha["disponivel"])
        if pedida > disponivel:
            creditado = _quantidade_em_inteiros(linha["creditado"])
            raise NotaDeCreditoInvalida(_MSG_JA_CREDITADO % (
                linha.get("titulo"),
                "" if creditado == 0 else " (%s)" % _numero_legivel(creditado),
                _numero_legivel(disponivel),
                _numero_legivel(_quantidade_em_inteiros(linha["quantidade"])),
            ))

        quantidade = _quantidade_legivel(pedida)
        # O líquido DESTA quantidade, pela fórmula do Vendus: bruto
        # arredondado ao cêntimo e depois a percentagem de desconto da linha
        # original, que é exactamente o que ele vai fazer do lado dele quando
        # receber esta linha na nota de crédito.
        total = _liquido_da_linha({
            "qty": quantidade,
            "gross_price": linha["preco_unitario"],
            "discount_percentage": linha.get("desconto_percentagem"),
        })
        escolhidas.append({
            "indice": indice,
            "titulo": linha.get("titulo"),
            "tax_id": linha.get("tax_id"),
            "quantidade": quantidade,
            "preco_unitario": linha["preco_unitario"],
            "desconto_percentagem": linha.get("desconto_percentagem"),
            "id_vendus": linha.get("id_vendus"),
            "total": total,
        })
    if not escolhidas:
        raise NotaDeCreditoInvalida(_MSG_SEM_LINHAS_ESCOLHIDAS)
    return escolhidas


def total_das_linhas(linhas: List[Dict]) -> float:
    """A soma das linhas creditadas, em CÊNTIMOS INTEIROS — a regra 1 da
    casa. Uma nota de 0,29 € + 1,15 € + 10,20 € não se soma em vírgula
    flutuante."""
    return sum(_centimos(linha.get("total")) for linha in linhas or []) / 100.0


def ext_ref_da_intencao(loja_id: str, sessao_id: str, intencao_id: str) -> str:
    """`pos-{loja}-{sessão}-nc-{intenção}` — ver o cabeçalho do módulo.

    O prefixo `pos-{loja}-{sessão}-` não é decorativo: é por ele que
    `fiscal._reconciliar_vendas_dinheiro` reconhece um documento como NOSSO e
    DESTE turno quando compara a gaveta contra o Vendus no fecho. Uma
    referência que não o tivesse deixava a devolução em dinheiro descontada
    do nosso lado e não do lado do Vendus — e o fecho acusava, todas as
    noites em que houvesse uma devolução, uma diferença que ninguém sabia
    explicar."""
    return "pos-%s-%s-nc-%s" % (loja_id, sessao_id, intencao_id)


def itens_vendus_da_nota(linhas: List[Dict], numero_original: str) -> List[Dict]:
    """As linhas da nota de crédito no formato do Vendus, cada uma a apontar
    para a linha EXACTA da fatura que rectifica.

    O `reference_document` (`document_number` + `document_row`) é o que a
    documentação da API exige numa NC, e o `document_row` é o `indice` desta
    linha — a posição dela no documento original. Ver
    `vendus/emissao.py::criar_nota_credito` para o que está confirmado e para
    o que não está."""
    itens = []
    for linha in linhas:
        item = {
            "title": linha.get("titulo"),
            "qty": linha["quantidade"],
            "gross_price": linha["preco_unitario"],
            "tax_id": linha.get("tax_id"),
            "reference_document": {
                "document_number": numero_original,
                "document_row": linha["indice"],
            },
        }
        if linha.get("id_vendus") is not None:
            item["id"] = linha["id_vendus"]
        if linha.get("desconto_percentagem"):
            item["discount_percentage"] = linha["desconto_percentagem"]
        itens.append(item)
    return itens


# --- As rotas -----------------------------------------------------------------


class LinhaEscolhida(BaseModel):
    indice: int = Field(ge=1)
    quantidade: float = Field(gt=0, allow_inf_nan=False)


class PedidoPreVisualizar(BaseModel):
    linhas: List[LinhaEscolhida] = Field(default_factory=list)


class PedidoNotaCredito(BaseModel):
    # O uuid que o ecrã gera ao abrir a janela e repete em cada retentativa
    # do MESMO toque — a identidade da intenção, de onde sai a referência
    # externa. Ver o cabeçalho do módulo.
    intencao_id: str = Field(min_length=1, max_length=64)
    caixa_id: str = Field(min_length=1)
    motivo: str = Field(min_length=1, max_length=200)
    tipo_pagamento_id: str = Field(min_length=1)
    linhas: List[LinhaEscolhida] = Field(default_factory=list)

    @field_validator("intencao_id")
    @classmethod
    def _valida_intencao(cls, v):
        try:
            uuid.UUID(str(v))
        except (TypeError, ValueError):
            raise ValueError(
                "O identificador da devolução tem de ser um UUID — é ele que "
                "torna esta nota de crédito única e a repetição do mesmo "
                "toque inofensiva."
            )
        return str(v)

    @field_validator("motivo")
    @classmethod
    def _valida_motivo(cls, v):
        if not str(v).strip():
            raise ValueError(_MSG_MOTIVO_EM_FALTA)
        return str(v).strip()


async def _notas_do_documento(db, documento_id: str) -> List[Dict]:
    return await db[COLECOES["notas_credito"]].find(
        {"documento_id": documento_id}, {"_id": 0}
    ).to_list(500)


async def _fatura_creditavel(db, documento_id: str, loja_id: str):
    """O documento e a venda dele, confirmados como creditáveis — ou o 4xx
    que diz porque não.

    A mesma porta de `documentos.py` para o âmbito da loja (um documento de
    outra loja é 404, nunca 403), mais as duas condições próprias da nota de
    crédito: tem de ser uma Fatura Simplificada, e tem de ter NÚMERO — sem
    ele não há `document_number` para pôr no `reference_document`, e uma NC
    sem a fatura que rectifica não é um documento legal."""
    documento = await _documento_da_loja(db, documento_id, loja_id)
    if documento.get("tipo") != "FS":
        raise HTTPException(
            status_code=422,
            detail=_MSG_SO_SE_CREDITA_UMA_FATURA % (
                "uma nota de crédito" if documento.get("tipo") == "NC"
                else "do tipo %s" % (documento.get("tipo") or "desconhecido")),
        )
    if not documento.get("numero"):
        raise HTTPException(status_code=409, detail=_MSG_DOCUMENTO_SEM_NUMERO)
    venda = await db[COLECOES["vendas"]].find_one({"id": documento.get("venda_id")})
    if venda is None or not venda.get("linhas"):
        raise HTTPException(status_code=409, detail=_MSG_SEM_CONTA_DE_ORIGEM)
    return documento, venda


def _resumo_da_nota(linhas: List[Dict]) -> Dict:
    """O dinheiro de uma selecção de linhas: o mapa de imposto (Taxa · Base ·
    IVA · Total), o subtotal e o total.

    **Tudo somado aqui, e nada no ecrã.** É a regra 1 da casa, e neste ecrã
    ela é mais do que um princípio: os números mudam a cada caixa que a
    operadora marca, e um browser a somar euros ao lado de um servidor a
    somar cêntimos era a divergência garantida — com a diferença a aparecer
    na nota de crédito real.

    O `subtotal` é a base tributável e o `total` é com IVA, que é como o
    print do Vendus os mostra; os dois saem do MESMO mapa que está desenhado
    por cima deles, e não de uma segunda soma."""
    mapa = mapa_da_nota({"linhas": linhas})
    totais = totais_do_mapa(mapa)
    return {
        "linhas": linhas,
        "mapa_imposto": mapa,
        "totais_imposto": totais,
        "subtotal": totais["base"],
        "total": totais["total"],
    }


@router.get("/pos/documentos/{documento_id}/nota-credito")
async def preparar_nota_credito(
    documento_id: str, operador: Dict = Depends(operador_atual)
) -> dict:
    """O ecrã da nota de crédito, antes de a operadora escolher seja o que
    for: o documento original, o cliente, e as linhas com o que AINDA se
    pode creditar de cada uma."""
    db = obter_db()
    documento, venda = await _fatura_creditavel(db, documento_id, operador["loja_id"])
    notas = await _notas_do_documento(db, documento_id)
    return {
        "documento": {
            "id": documento.get("id"),
            "numero": documento.get("numero"),
            "atcud": documento.get("atcud"),
            "tipo": documento.get("tipo"),
            "modo": documento.get("modo"),
            "emitido_em": documento.get("emitido_em"),
            "total": documento.get("total"),
        },
        "cliente_nif": venda.get("cliente_nif"),
        # O `id_vendus` de cada linha fica DE FORA: é configuração interna
        # da ligação ao Vendus e o balcão não tem nada que a ver — a mesma
        # regra do `vendus_payment_method_id` em
        # `pos_catalogo.tipos_pagamento_do_pos`, que só deixa sair o booleano.
        "linhas": [
            {chave: valor for chave, valor in linha.items() if chave != "id_vendus"}
            for linha in linhas_creditaveis(venda, notas)
        ],
        # As notas de crédito que esta fatura já tem — a operadora tem de
        # saber que o cliente já cá veio, e com que documento. Uma que ficou
        # por apurar aparece com o estado à vista: é a única forma de alguém
        # ir ver o que aconteceu.
        "notas_anteriores": [
            {
                "id": nota.get("id"),
                "numero": nota.get("numero"),
                "estado": nota.get("estado"),
                "total": nota.get("total"),
                "motivo": nota.get("motivo"),
                "emitido_em": nota.get("emitido_em"),
            }
            for nota in sorted(notas, key=lambda n: n.get("criada_em") or "")
        ],
    }


@router.post("/pos/documentos/{documento_id}/nota-credito/pre-visualizar")
async def pre_visualizar_nota_credito(
    documento_id: str,
    dados: PedidoPreVisualizar,
    operador: Dict = Depends(operador_atual),
) -> dict:
    """O dinheiro das linhas seleccionadas — o mapa de imposto, o subtotal e
    o total, somados pelo SERVIDOR a cada mudança da selecção.

    Existe porque a alternativa era o ecrã somar euros, e neste módulo isso
    já custou dinheiro. É a MESMA validação da emissão (o travão incluído):
    a operadora vê a recusa enquanto escolhe, e não depois de carregar em
    EMITIR com o cliente à frente."""
    db = obter_db()
    _, venda = await _fatura_creditavel(db, documento_id, operador["loja_id"])
    notas = await _notas_do_documento(db, documento_id)
    creditaveis = linhas_creditaveis(venda, notas)
    if not dados.linhas:
        # Nenhuma linha escolhida não é um erro: é o estado em que o ecrã
        # abre. Responde-se com o dinheiro a zero, e não com um 422 que
        # pintava o ecrã de vermelho antes de a operadora tocar em nada.
        return _resumo_da_nota([])
    try:
        escolhidas = escolher_linhas(
            creditaveis, [linha.model_dump() for linha in dados.linhas])
    except NotaDeCreditoInvalida as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _resumo_da_nota(escolhidas)


async def _libertar_intencao(db, intencao_id: str) -> None:
    """Apaga a intenção — SÓ quando há prova de que nada saiu para a AT.

    É o gémeo de `fiscal._libertar_reserva`, e a regra é a mesma: libertar é
    dizer «não saiu nota nenhuma, podem emitir de novo». Só se chama a partir
    da lista curta de erros que provam que o pedido não chegou a ser
    processado (`fiscal._ERROS_COM_PROVA_DE_QUE_NADA_SAIU`) ou de uma
    verificação por referência externa que correu bem e não encontrou nada.
    Tudo o resto fica marcado `incerta`."""
    await db[COLECOES["notas_credito"]].delete_one({"id": intencao_id})


async def _marcar_incerta(db, intencao_id: str, porque: str) -> None:
    """A nota que pode ter saído. Fica gravada, conta para o travão (não se
    credita por cima do que talvez já tenha sido creditado) e NÃO conta para
    o dinheiro do turno (não se desconta da gaveta um dinheiro que talvez não
    tenha saído)."""
    await db[COLECOES["notas_credito"]].update_one(
        {"id": intencao_id},
        {"$set": {"estado": "incerta", "incerta_porque": porque,
                  "incerta_em": _agora()}},
    )


async def _gravar_documento_da_nota(
    db, nota: Dict, bruto: Dict
) -> Dict:
    """Grava a nota de crédito em `fat_documentos` — a MESMA colecção das
    faturas, com `tipo: "NC"`.

    É isso que faz o Dashboard descontar a devolução da receita sem uma linha
    nova (`dashboard._valor_documento` já lê `tipo == "NC"` como sinal
    negativo, e está lá escrito à espera deste dia) e o separador Faturação
    mostrar a nota ao lado da fatura que ela corrige.

    **`venda_id` NÃO se grava, de propósito.** Uma nota de crédito não é a
    venda: as linhas dela são as CREDITADAS, que podem ser parte das da
    conta. Gravá-lo fazia `documentos.obter_documento` desenhar a nota com os
    artigos todos da conta original e um mapa de imposto que não é o dela —
    um documento fiscal a mostrar números que não são os seus."""
    documento = {
        "id": str(uuid.uuid4()),
        "vendus_document_id": bruto.get("id"),
        "atcud": bruto.get("atcud"),
        "numero": bruto.get("numero"),
        "total": bruto.get("total"),
        "total_bruto": bruto.get("total_bruto"),
        "total_liquido": bruto.get("total_liquido"),
        "tipo": "NC",
        "modo": bruto.get("modo"),
        "ext_ref": nota["ext_ref"],
        "loja_id": nota["loja_id"],
        "emitido_em": bruto.get("emitido_em") or _agora(),
        # A ligação nos dois sentidos, e é por ela que o ecrã sabe desenhar
        # esta nota: as linhas creditadas e o motivo vivem em
        # `fat_notas_credito`, e é este campo que lá chega.
        "nota_credito_id": nota["id"],
        "documento_origem_id": nota["documento_id"],
        "numero_origem": nota["numero_origem"],
    }
    try:
        await db[COLECOES["documentos"]].insert_one(dict(documento))
    except DuplicateKeyError:
        existente = await db[COLECOES["documentos"]].find_one(
            {"ext_ref": nota["ext_ref"]}, {"_id": 0})
        if existente is not None and (
            existente.get("vendus_document_id") == bruto.get("id")
        ):
            # Uma tentativa anterior desta MESMA intenção já gravou esta
            # MESMA nota (um retry depois de a resposta se ter perdido) —
            # reutiliza-se, sem inventar um segundo documento.
            return existente
        # Ou o Vendus devolveu OUTRO documento para esta referência, ou este
        # documento colide com um já gravado (os únicos em
        # `vendus_document_id` e `atcud`). Nos dois casos há um documento
        # fiscal real envolvido: a intenção NÃO se liberta.
        logger.error(
            "[faturacao] conflito ao gravar a nota de crédito %s (ext_ref=%s, "
            "vendus_document_id=%r, atcud=%r)",
            nota["id"], nota["ext_ref"], bruto.get("id"), bruto.get("atcud"),
        )
        raise HTTPException(status_code=500, detail=_MSG_CONFLITO_DOCUMENTO)
    return documento


async def _emitir_no_vendus(
    db,
    nota: Dict,
    emitir: Callable[[str], Awaitable[Dict]],
    verificar: Callable[[str], Awaitable[Optional[Dict]]],
) -> Dict:
    """Chama `emitir`, com o único recurso permitido (o mesmo de
    `fiscal._emitir_e_gravar`): um timeout/indisponibilidade tenta UMA
    verificação exacta por referência externa, nunca uma segunda emissão às
    cegas.

    Os três desfechos, e a consequência de cada um sobre a intenção:

    1. a verificação ENCONTRA o documento → usa-se esse, e nunca se emite
       outra vez;
    2. a verificação corre bem e não encontra nada → o Vendus não chegou a
       processar o pedido; a intenção liberta-se e a operadora pode repetir;
    3. a verificação REBENTA (ou a emissão falha de uma forma que não prova
       nada, tipicamente já depois de um 2xx) → não se sabe se saiu: a
       intenção fica `incerta` e o dinheiro NÃO se devolve."""
    ext_ref = nota["ext_ref"]
    try:
        return await emitir(ext_ref)
    except VendusIndisponivel as e:
        logger.warning(
            "[faturacao] nota de crédito %s: emissão indisponível (%s) — a "
            "verificar por referência externa", nota["id"], e)
        try:
            encontrado = await verificar(ext_ref)
        except Exception as erro_verificacao:  # noqa: BLE001 — nada se prova
            await _marcar_incerta(
                db, nota["id"],
                "timeout na emissão e a verificação também falhou: %s"
                % erro_verificacao)
            raise HTTPException(status_code=503, detail=_MSG_DESFECHO_INCERTO)
        if encontrado is not None:
            return encontrado
        await _libertar_intencao(db, nota["id"])
        raise HTTPException(status_code=502, detail=_MSG_NADA_SAIU % e)
    except _ERROS_COM_PROVA_DE_QUE_NADA_SAIU as e:
        # A lista curta do `fiscal.py`: erros levantados ANTES de qualquer
        # pedido sair para a rede, um 429 a todas as tentativas, ou um 4xx
        # que não é 429. Em todos, a prova de que nada saiu é o próprio erro.
        await _libertar_intencao(db, nota["id"])
        raise HTTPException(status_code=502, detail=_MSG_NADA_SAIU % e)
    except VendusErro as e:
        # Tudo o que possa acontecer DEPOIS de uma resposta 2xx — uma
        # resposta ilegível, por exemplo. O documento pode existir.
        await _marcar_incerta(db, nota["id"], "erro sem desfecho conhecido: %s" % e)
        raise HTTPException(status_code=503, detail=_MSG_DESFECHO_INCERTO)
    except Exception as e:  # noqa: BLE001 — o desfecho desconhecido é o pior caso
        await _marcar_incerta(db, nota["id"], "falha inesperada: %s" % e)
        logger.error("[faturacao] nota de crédito %s sem desfecho: %s", nota["id"], e)
        raise HTTPException(status_code=503, detail=_MSG_DESFECHO_INCERTO)


def _resposta_da_nota(nota: Dict, documento: Dict) -> Dict:
    """O que o ecrã lê depois de a nota sair.

    `total_divergente` é a única coisa aqui que não é uma cópia: o `total` do
    DOCUMENTO é o que o Vendus devolveu (e o que a AT tem) e o `total` da
    NOTA é o que este servidor somou das linhas. Deviam ser o mesmo número —
    as linhas vão com o preço e o desconto da fatura original, e a fórmula é
    a dele — e é precisamente por isso que uma divergência tem de aparecer no
    ecrã em vez de ser escolhida em silêncio."""
    total_documento = documento.get("total")
    mapa = mapa_da_nota(nota)
    return {
        "id": nota["id"],
        "documento_id": documento.get("id"),
        "numero": documento.get("numero"),
        "atcud": documento.get("atcud"),
        "tipo": documento.get("tipo"),
        "modo": documento.get("modo"),
        "emitido_em": documento.get("emitido_em"),
        "numero_origem": nota.get("numero_origem"),
        "motivo": nota.get("motivo"),
        "devolucao": nota.get("devolucao"),
        "linhas": nota.get("linhas"),
        "mapa_imposto": mapa,
        "totais_imposto": totais_do_mapa(mapa),
        "total": total_documento,
        "total_das_linhas": nota.get("total"),
        "total_divergente": (
            total_documento is not None
            and _centimos(total_documento) != _centimos(nota.get("total"))
        ),
    }


@router.post("/pos/documentos/{documento_id}/nota-credito", status_code=201)
async def emitir_nota_credito(
    documento_id: str,
    dados: PedidoNotaCredito,
    operador: Dict = Depends(operador_atual),
) -> dict:
    """Emite a NOTA DE CRÉDITO real desta fatura, e devolve o dinheiro pelo
    meio de pagamento escolhido.

    **Quem pode: qualquer operadora com o PIN dela** — decisão do dono. Não
    há aqui verificação de perfil nem PIN de gestor, de propósito: a
    dependência é a mesma `operador_atual` de vender e de finalizar.

    A ordem das coisas é a de `fiscal.finalizar`, e é ela que faz as
    garantias valerem:

    1. **toda a validação ANTES de gravar seja o que for** — a fatura, as
       linhas escolhidas contra o travão, o motivo, o tipo de pagamento e a
       configuração do Vendus. Um erro de dados não pode gastar uma intenção
       nem confundir a operadora com um 502;
    2. **a intenção grava-se ANTES de falar com o Vendus** — é ela a reserva
       atómica (índice único em `fat_notas_credito.id`), e é o que faz o
       duplo-toque nunca chegar a emitir duas vezes;
    3. **a sessão relê-se DEPOIS de a intenção estar gravada** — o mesmo par
       (escrever, depois perguntar) que fecha a janela do fecho de caixa: ou
       o fecho vê esta intenção (`caixa._nota_de_credito_em_curso`) e
       recusa-se, ou esta releitura vê a marca do fecho e aborta sem emitir.
       Não há terceira ordem;
    4. **emitir**, com a verificação por referência externa como único
       recurso a um timeout;
    5. **gravar** o documento e marcar a intenção `emitida` — e é essa marca
       que põe a devolução no Ponto de Caixa e no Z.
    """
    if not indice_notas_credito_confirmado():
        raise HTTPException(status_code=503, detail=_MSG_INDICE_EM_FALTA)

    db = obter_db()
    documento, venda = await _fatura_creditavel(db, documento_id, operador["loja_id"])

    caixa = await _obter_caixa_da_loja(db, dados.caixa_id, operador["loja_id"])
    # A devolução acontece no turno de AGORA e não no da fatura: o cliente que
    # volta amanhã é creditado amanhã, e é da gaveta de amanhã que sai o
    # dinheiro. Sem sessão aberta não se emite — a nota ficaria fora de todos
    # os Z, e o dinheiro devolvido não entrava em conta nenhuma.
    sessao = await _sessao_aberta(db, caixa["id"])

    notas = await _notas_do_documento(db, documento_id)
    creditaveis = linhas_creditaveis(venda, notas)
    try:
        escolhidas = escolher_linhas(
            creditaveis, [linha.model_dump() for linha in dados.linhas])
    except NotaDeCreditoInvalida as e:
        raise HTTPException(status_code=422, detail=str(e))

    total = total_das_linhas(escolhidas)
    if total <= 0:
        raise HTTPException(status_code=422, detail=_MSG_TOTAL_NAO_POSITIVO)

    tipo = await db[COLECOES["tipos_pagamento"]].find_one(
        {"id": dados.tipo_pagamento_id})
    if not tipo or not tipo.get("ativo", True):
        raise HTTPException(status_code=422, detail=_MSG_TIPO_PAGAMENTO_INEXISTENTE)
    if not tipo.get("vendus_payment_method_id"):
        raise HTTPException(status_code=422, detail=_MSG_TIPO_PAGAMENTO_SEM_VENDUS)

    conta = obter_conta(_nif_configurado())
    if conta is None:
        raise HTTPException(
            status_code=502,
            detail=(
                "Conta Vendus não configurada para o NIF %s. Defina "
                "VENDUS_ACCOUNTS no .env — sem isto não há como emitir."
                % _nif_configurado()
            ),
        )
    register_id = _register_id_configurado()
    if register_id is None:
        raise HTTPException(
            status_code=502,
            detail="VENDUS_REGISTER_ID não está configurado — sem isto não há como emitir.",
        )

    nota = {
        "id": dados.intencao_id,
        "loja_id": operador["loja_id"],
        "caixa_id": caixa["id"],
        "sessao_id": sessao["id"],
        "documento_id": documento["id"],
        "venda_id": venda.get("id"),
        "numero_origem": documento.get("numero"),
        "operador": {"id": operador.get("operador_id"), "nome": operador.get("nome")},
        "motivo": dados.motivo,
        "linhas": escolhidas,
        "total": total,
        # O RETRATO do tipo de pagamento por onde o dinheiro volta — nome,
        # código fiscal e id, como `fiscal.finalizar` faz com os pagamentos
        # da venda. É deste retrato que o Ponto de Caixa e o Z lêem a
        # devolução, e é ele que faz o dinheiro seguir o meio de pagamento:
        # `tipo_fiscal == "NU"` sai da gaveta, tudo o resto não lhe toca.
        "devolucao": {
            "tipo_pagamento_id": tipo["id"],
            "nome": tipo.get("nome"),
            "tipo_fiscal": tipo.get("tipo_fiscal"),
            "valor": total,
        },
        "ext_ref": ext_ref_da_intencao(
            operador["loja_id"], sessao["id"], dados.intencao_id),
        "estado": "reservada",
        "criada_em": _agora(),
    }

    # A RESERVA ATÓMICA. Daqui para baixo, ou esta intenção emite ou fica
    # marcada — nunca há duas a falar com o Vendus sobre a mesma devolução.
    try:
        await db[COLECOES["notas_credito"]].insert_one(dict(nota))
    except DuplicateKeyError:
        return await _resposta_de_quem_repetiu(db, dados.intencao_id, documento)

    # A releitura da sessão, DEPOIS da reserva — ver o passo 3 da docstring.
    sessao_agora = await db[COLECOES["sessoes_caixa"]].find_one({"id": sessao["id"]})
    if (sessao_agora or {}).get("estado") != "aberta":
        await _libertar_intencao(db, nota["id"])
        raise HTTPException(status_code=409, detail=_MSG_SESSAO_FECHOU_ENTRETANTO)

    itens = itens_vendus_da_nota(escolhidas, documento["numero"])
    pagamentos = [{"id": tipo["vendus_payment_method_id"], "amount": total}]

    with ClienteEmissaoVendus(conta.chave) as cliente_vendus:

        async def emitir(ref: str) -> Dict:
            return await asyncio.to_thread(
                cliente_vendus.criar_nota_credito,
                linhas=itens,
                pagamentos=pagamentos,
                external_reference=ref,
                register_id=register_id,
                motivo=dados.motivo,
            )

        async def verificar(ref: str) -> Optional[Dict]:
            return await asyncio.to_thread(
                cliente_vendus.procurar_por_referencia_externa, ref, register_id
            )

        bruto = await _emitir_no_vendus(db, nota, emitir, verificar)

    documento_nc = await _gravar_documento_da_nota(db, nota, bruto)
    await db[COLECOES["notas_credito"]].update_one(
        {"id": nota["id"]},
        {"$set": {
            "estado": "emitida",
            "documento_nc_id": documento_nc.get("id"),
            "vendus_document_id": documento_nc.get("vendus_document_id"),
            "numero": documento_nc.get("numero"),
            "atcud": documento_nc.get("atcud"),
            "modo": documento_nc.get("modo"),
            "emitido_em": documento_nc.get("emitido_em"),
        }},
    )
    return _resposta_da_nota(nota, documento_nc)


async def _resposta_de_quem_repetiu(db, intencao_id: str, documento: Dict) -> Dict:
    """O segundo toque no mesmo botão.

    A intenção já existe — ou porque a primeira ainda está a falar com o
    Vendus, ou porque já emitiu e a resposta se perdeu a caminho do ecrã. Nos
    dois casos NADA se emite outra vez; o que muda é o que a operadora lê.

    **E confirma-se de quem é a intenção antes de responder o que quer que
    seja.** O `intencao_id` vem do browser: sem esta confirmação, um
    identificador repetido devolvia a nota de crédito de OUTRA fatura (ou de
    outra loja) a quem perguntasse — dados de uma devolução que não é dele, e
    um ecrã a dizer que a devolução foi feita quando não foi."""
    existente = await db[COLECOES["notas_credito"]].find_one(
        {"id": intencao_id}, {"_id": 0})
    if existente is None:
        # Corrida rara: a intenção existia no instante do insert e já não
        # existe (uma libertação por erro provado). Nada saiu — a operadora
        # repete, e é isso que a mensagem diz.
        raise HTTPException(status_code=409, detail=_MSG_EMISSAO_EM_CURSO)
    if existente.get("documento_id") != documento.get("id"):
        raise HTTPException(status_code=409, detail=_MSG_INTENCAO_DE_OUTRA_FATURA)
    if existente.get("estado") != "emitida":
        raise HTTPException(status_code=409, detail=_MSG_EMISSAO_EM_CURSO)
    documento_nc = await db[COLECOES["documentos"]].find_one(
        {"id": existente.get("documento_nc_id")}, {"_id": 0})
    return _resposta_da_nota(existente, documento_nc or {})
