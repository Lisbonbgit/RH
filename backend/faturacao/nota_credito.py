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

from .auth import gestor_atual
from .caixa import _obter_caixa_da_loja, _sessao_aberta
from .db import (
    COLECOES,
    indice_notas_credito_confirmado,
    obter_db,
)
from .documentos import _centimos, _documento_da_loja
from .fiscal import (
    _ERROS_COM_PROVA_DE_QUE_NADA_SAIU,
    _itens_vendus,
    _percentagem_que_reproduz,
    ext_ref_determinista,
    MARCA_NOTA_CREDITO,
)
from .importacao import _nif_configurado
from .mapa_imposto import _liquido_da_linha, mapa_da_nota, totais_do_mapa
from .pos_auth import operador_atual
from .reparticao import parte_acumulada
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
_MSG_CREDITO_TOMADO_ENTRETANTO = (
    "Outra nota de crédito desta fatura foi emitida neste instante — esta NÃO "
    "saiu e nada foi enviado à Autoridade Tributária. Feche esta janela e abra "
    "a nota de crédito outra vez, para ver o que a fatura ainda deixa creditar."
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


def pagamentos_da_fatura(venda: Optional[Dict], notas: List[Dict]) -> List[Dict]:
    """**Como é que esta fatura foi PAGA, e quanto de cada meio ainda não foi
    devolvido.**

    Existia um buraco entre a regra do dono — «a devolução segue o meio de
    pagamento» — e o que o sistema fazia: nada comparava o meio da devolução
    com os da fatura, e `preparar_nota_credito` nem sequer devolvia os
    pagamentos, por isso o ecrã também não os podia mostrar. A operadora
    escolhia às cegas. Medido: uma fatura de 11,29 € paga **5,00 em dinheiro
    + 6,29 em Multibanco**, creditado só o açaí de 9,85 € com devolução em
    DINHEIRO — `vendas_dinheiro` de 5,00 para **−4,85 €** e o esperado da
    gaveta de 55,00 para **45,15 €, abaixo do fundo inicial**. Saíram 9,85 €
    em notas de uma venda que só pôs 5,00 € na gaveta.

    **E o servidor NÃO recusa — mostra.** Recusar por meio de pagamento é a
    defesa mais forte e foi a primeira escolha, até se medir o que ela faz ao
    balcão: nesta mesma fatura, o cliente devolve o açaí de 9,85 € e NENHUM
    dos dois meios chega (dinheiro tem 5,00 €, Multibanco tem 6,29 €). Uma
    nota de crédito credita LINHAS, e as mesmas linhas não se creditam duas
    vezes — não há como partir a devolução em duas notas. A recusa fechava a
    porta sem abrir outra, e uma devolução legítima ficava impossível com o
    cliente à frente.

    O que se faz em vez disso é o que a regra do dono descreve mesmo: pôr os
    números à frente da operadora ANTES do toque, e **deixar registado**
    quando a devolução passa o que aquele meio recebeu
    (`devolucao.acima_do_recebido`) — o gestor encontra isso depois, em vez
    de encontrar uma gaveta abaixo do fundo sem explicação.

    `devolvido` conta as notas `emitida`, `incerta` e `reservada`, as mesmas
    do travão da quantidade e pela mesma razão: o que talvez tenha saído não
    se pode contar como disponível outra vez."""
    linhas: Dict[str, Dict] = {}
    for pagamento in (venda or {}).get("pagamentos") or []:
        chave = pagamento.get("tipo_pagamento_id") or pagamento.get("nome")
        linha = linhas.get(chave)
        if linha is None:
            linha = linhas[chave] = {
                "tipo_pagamento_id": pagamento.get("tipo_pagamento_id"),
                "nome": pagamento.get("nome"),
                "tipo_fiscal": pagamento.get("tipo_fiscal"),
                "recebido_centimos": 0,
                "devolvido_centimos": 0,
            }
        linha["recebido_centimos"] += _centimos(pagamento.get("valor"))

    for nota in notas or []:
        if nota.get("estado") not in ("emitida", "incerta", "reservada"):
            continue
        devolucao = nota.get("devolucao") or {}
        chave = devolucao.get("tipo_pagamento_id") or devolucao.get("nome")
        linha = linhas.get(chave)
        if linha is None:
            # Uma devolução por um meio que a fatura não usou: entra com
            # `recebido` a zero, que é a verdade e é o que a operadora tem de
            # ver. Escondê-la fazia a soma da coluna não bater com a gaveta.
            linha = linhas[chave] = {
                "tipo_pagamento_id": devolucao.get("tipo_pagamento_id"),
                "nome": devolucao.get("nome"),
                "tipo_fiscal": devolucao.get("tipo_fiscal"),
                "recebido_centimos": 0,
                "devolvido_centimos": 0,
            }
        linha["devolvido_centimos"] += _centimos(devolucao.get("valor"))

    saida = []
    for linha in linhas.values():
        recebido = linha.pop("recebido_centimos")
        devolvido = linha.pop("devolvido_centimos")
        linha["recebido"] = recebido / 100.0
        linha["devolvido"] = devolvido / 100.0
        linha["disponivel"] = (recebido - devolvido) / 100.0
        saida.append(linha)
    saida.sort(key=lambda li: (-_centimos(li["recebido"]), li["nome"] or ""))
    return saida


def acima_do_recebido(
    pagamentos: List[Dict], tipo_pagamento_id: str, total: float
) -> float:
    """Quanto desta devolução passa o que a fatura ainda tem naquele meio —
    `0.0` no caso normal.

    Em cêntimos inteiros e do lado do servidor, como tudo o que é dinheiro
    neste módulo. Um meio que a fatura não usou dá `disponivel` zero, e a
    devolução inteira fica acima do recebido — que é exactamente o que ela
    é."""
    disponivel = 0
    for linha in pagamentos or []:
        if linha.get("tipo_pagamento_id") == tipo_pagamento_id:
            disponivel = _centimos(linha.get("disponivel"))
            break
    return max(0, _centimos(total) - disponivel) / 100.0


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
        # **O dinheiro desta parcial é a DIFERENÇA DE DOIS ACUMULADOS**, e
        # não o líquido da parcial calculado por si só.
        #
        # Calculado por si só — `round(qty × preço, 2)` e depois o desconto,
        # que era o que estava aqui — cada parcial arredonda para cima o seu
        # próprio meio-cêntimo, e as parciais de uma linha deixam de somar a
        # linha. Medido: uma linha de 10 × 0,05 € (0,50 €) creditada em 100
        # fatias de 0,1 devolvia **1,00 €, o dobro**; e em 4986 faturas ao
        # acaso creditadas em duas parciais fraccionárias, 1279 devolviam
        # um valor diferente do que a fatura cobrou.
        #
        # Com o acumulado (`reparticao.parte_acumulada`, ver lá o porquê de
        # não ser `repartir_centimos` nem `_distribuir_centimos`) a soma das
        # parciais de uma linha é, por construção, o líquido da linha —
        # creditada em quantas vezes for e por que ordem for.
        total_da_linha = _centimos(linha.get("total"))
        original = _quantidade_em_inteiros(linha["quantidade"])
        antes_desta = _quantidade_em_inteiros(linha["creditado"])
        total = (
            parte_acumulada(total_da_linha, original, antes_desta + pedida)
            - parte_acumulada(total_da_linha, original, antes_desta)
        ) / 100.0
        # **E o desconto que vai ao Vendus é o que REPRODUZ esse cêntimo.**
        # As linhas da nota levam `qty` e `gross_price`, e o Vendus faz a
        # conta dele: sem esta conversão, o documento entregue à AT dizia o
        # líquido ingénuo da parcial e nós gravávamos o acumulado — as duas
        # a discordar, e a discordância a aparecer em `total_divergente` a
        # cada parcial. É o mesmo instrumento que a Fatura Simplificada usa
        # para fechar o cêntimo do desconto global (`fiscal._itens_vendus`),
        # e o desconto próprio da linha já vem lá dentro: o alvo é o líquido,
        # não o bruto.
        bruto = round(quantidade * (linha["preco_unitario"] or 0), 2)
        escolhidas.append({
            "indice": indice,
            "titulo": linha.get("titulo"),
            "tax_id": linha.get("tax_id"),
            "quantidade": quantidade,
            "preco_unitario": linha["preco_unitario"],
            "desconto_percentagem": _percentagem_que_reproduz(bruto, total),
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
    explicar.

    O `nc-` é `fiscal.MARCA_NOTA_CREDITO` e o resto é
    `fiscal.ext_ref_determinista` — as duas metades vêm de lá, e não de um
    formato escrito outra vez aqui. É por essa marca que a reconciliação do
    fecho sabe que este documento é uma DEVOLUÇÃO e não uma venda
    (`fiscal._e_nota_de_credito`); uma segunda cópia do formato divergia da
    primeira, e a divergência aparecia como uma diferença de gaveta."""
    return ext_ref_determinista(
        loja_id, sessao_id, MARCA_NOTA_CREDITO + intencao_id)


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


async def _selo_e_notas(db, documento_id: str):
    """O SELO do saldo desta fatura e as notas que contam para o travão —
    lidos NESTA ordem, que é o que torna a reserva do crédito atómica.

    **O travão sozinho é ler-verificar-escrever, e isso não trava nada.**
    Duas rotas em paralelo lêem as mesmas notas (nenhuma), concluem as duas
    que a fatura está por creditar, e emitem as duas — cada uma com a sua
    intenção, cada uma legítima pelo índice único de `fat_notas_credito.id`,
    que é a identidade da INTENÇÃO e por desenho deixa haver várias notas
    por fatura. Medido pelas rotas reais, com o duplo de Mongo a ceder o
    event loop em cada leitura: uma fatura de 11,29 € paga em dinheiro,
    dois `POST` concorrentes com intenções diferentes → **[201, 201], duas
    emissões REAIS no Vendus, dois documentos NC**, o esperado da gaveta em
    38,71 € em vez de 50,00 e o `total_faturado` do turno em −11,29 €. O Z
    fechava a 200 por cima disso.

    O recurso a proteger não é a venda (essa é a da Fatura Simplificada): é
    **a quantidade creditável de cada linha da fatura**. O selo é o contador
    de reservas de crédito que vive na PRÓPRIA fatura
    (`fat_documentos.nc_reserva_seq`), e quem reserva escreve-o
    CONDICIONALMENTE ao valor que leu (`_reservar_o_credito`) — quem chegar
    depois não casa e perde, sem nunca chegar a falar com o Vendus.

    **A ordem das duas leituras é a garantia, e não é decorativa.** O selo
    lê-se ANTES das notas, e quem reserva bump-a o selo DEPOIS de gravar a
    intenção. Assim, para as duas ordens possíveis:

    - se o outro pedido ainda não gravou a intenção quando lemos as notas,
      então também ainda não bump-ou o selo — mas vai bump-á-lo antes de
      emitir, e a nossa escrita condicional (feita sobre o selo antigo)
      falha;
    - se já a gravou, então lemos a intenção dele nas notas — ela conta para
      o travão (`ja_creditado_por_linha` conta a `reservada`) e a recusa é a
      normal, com a frase que diz quanto ainda dá.

    Não há terceira ordem: o selo lê-se antes das notas, por isso um selo
    novo implica que a intenção que o produziu já estava gravada."""
    documento = await db[COLECOES["documentos"]].find_one(
        {"id": documento_id}, {"_id": 0, "nc_reserva_seq": 1})
    selo = (documento or {}).get("nc_reserva_seq")
    notas = await _notas_do_documento(db, documento_id)
    return selo, notas


async def _reservar_o_credito(db, documento_id: str, selo) -> bool:
    """A RESERVA ATÓMICA do crédito — a escrita condicional que só ganha se
    ninguém tiver mexido no saldo desde que o lemos.

    É o `matched_count` que decide, como em todo o módulo (`_reservar`,
    `cancelar_venda`, a marca do fecho). `{"nc_reserva_seq": None}` é o caso
    da PRIMEIRA nota desta fatura: no Mongo — e no duplo — um filtro por
    `None` casa também com o campo ausente, por isso não é preciso semear
    campo nenhum nas faturas que já existem."""
    resultado = await db[COLECOES["documentos"]].update_one(
        {"id": documento_id, "nc_reserva_seq": selo},
        {"$set": {"nc_reserva_seq": (selo or 0) + 1}},
    )
    return resultado.matched_count == 1


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
        # **Como a fatura foi paga, e quanto de cada meio ainda não voltou.**
        # Sem isto o ecrã não podia mostrar nada, e a operadora escolhia o
        # meio da devolução às cegas — ver `pagamentos_da_fatura`.
        "pagamentos": pagamentos_da_fatura(venda, notas),
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
    2. **a intenção grava-se ANTES de falar com o Vendus** — o índice único
       em `fat_notas_credito.id` é o que faz o duplo-toque nunca chegar a
       emitir duas vezes — e logo a seguir **reserva-se o CRÉDITO**, com a
       escrita condicional de `_reservar_o_credito`. São coisas diferentes:
       a primeira protege a INTENÇÃO (o mesmo toque repetido), a segunda
       protege a QUANTIDADE CREDITÁVEL DA FATURA (duas notas diferentes,
       duas janelas, a creditar a mesma linha). Sem a segunda, o travão era
       um ler-verificar-escrever e duas notas reais saíam para a AT;
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

    # O SELO do saldo ANTES das notas — ver `_selo_e_notas`: é essa ordem, e
    # a escrita condicional lá em baixo, que fazem a reserva do crédito ser
    # atómica em vez de um ler-verificar-escrever que não trava nada.
    selo, notas = await _selo_e_notas(db, documento_id)
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
            # **Quanto desta devolução passa o que a fatura recebeu NESTE
            # meio** — 0,00 no caso normal. Não é uma recusa (ver
            # `pagamentos_da_fatura` para o porquê): é o facto gravado, para
            # o gestor o encontrar depois em vez de encontrar uma gaveta
            # abaixo do fundo sem explicação nenhuma.
            "acima_do_recebido": acima_do_recebido(
                pagamentos_da_fatura(venda, notas), tipo["id"], total),
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

    # **A RESERVA DO CRÉDITO**, e é ela que impede duas notas concorrentes de
    # creditarem a mesma linha. Feita DEPOIS de a intenção estar gravada (é
    # essa ordem que faz o outro pedido ver sempre uma das duas: ou a intenção
    # nas notas, ou o selo mexido) e ANTES de qualquer palavra ao Vendus —
    # perder aqui não custa documento fiscal nenhum, só a intenção que se
    # liberta a seguir.
    if not await _reservar_o_credito(db, documento["id"], selo):
        await _libertar_intencao(db, nota["id"])
        raise HTTPException(status_code=409, detail=_MSG_CREDITO_TOMADO_ENTRETANTO)

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


# --- Gestão: as notas de crédito PRESAS ---------------------------------------
#
# **A saída que faltava, e é a mesma que a Fatura Simplificada já tem.**
#
# Uma intenção fica `reservada` sempre que a rota morre entre o `insert_one` e
# o `$set` final: um reinício do servidor, um deploy a meio de uma devolução,
# ou o 409 da corrida do crédito. E `caixa._nota_de_credito_em_curso` recusa o
# fecho enquanto existir UMA — com a frase «espere alguns segundos», que aqui
# nunca chega a ser verdade. Medido: três tentativas seguidas de fechar a
# caixa, 409 sempre. Com UM PC por loja, é a loja sem conseguir fechar o turno
# e sem botão nenhum.
#
# O desenho é o de `fiscal.py` e não um segundo: uma LISTAGEM que diz o que
# aconteceu, e as duas saídas que existem consoante o que o gestor encontrar
# no Vendus —
#
#   - **não está lá**: `libertar`, que apaga a intenção. A fatura volta a
#     deixar creditar aquelas linhas e o turno fecha. Exige
#     `confirmado_no_vendus=true` com todas as letras, pela mesma razão que a
#     reserva fiscal: libertar uma nota que SAIU é autorizar uma segunda nota
#     real da mesma devolução;
#   - **está lá, ou não se consegue apurar**: `por-apurar`, que a marca
#     `incerta` — o estado que este módulo já tinha para isto. Conta para o
#     travão (não se credita por cima do que talvez já tenha saído), NÃO
#     desconta a gaveta (não se devolve dinheiro que talvez não tenha saído) e
#     não trava o fecho. É a saída SEGURA, e por isso não pede confirmação
#     nenhuma.
#
# Não há aqui um `reconciliar` como o da FS. A razão é que não faz falta: o
# documento da nota entra no Z pelo `fat_documentos` da fatura, e uma nota
# `incerta` que se confirme ter saído resolve-se no Vendus com os números que
# esta listagem dá (a `ext_ref`, a loja e o total) — inventar uma rota de
# reconciliação sem ninguém a precisar dela era inventar um segundo desenho.

_LIMITE_NOTAS_PRESAS = 500

# O mesmo relógio de `fiscal._SEGUNDOS_DE_EMISSAO_NORMAL`: dentro desta janela
# a nota é quase de certeza uma emissão a decorrer NESTE instante, e nenhum
# gestor consegue ter confirmado o Vendus dentro dela.
_SEGUNDOS_DE_EMISSAO_NORMAL = 300.0

_MSG_NOTA_PRESA_INEXISTENTE = (
    "Não há nenhuma nota de crédito com este identificador — nada para "
    "resolver."
)
_MSG_NOTA_PRESA_JA_RESOLVIDA = (
    "Esta nota de crédito já não está presa: está %s. Não há nada a fazer-lhe "
    "aqui."
)
_MSG_NOTA_PRESA_RECENTE = (
    "Esta nota de crédito reservou há %.0f segundos — abaixo dos %d de uma "
    "emissão normal, o que quer dizer que ela pode estar a falar com o Vendus "
    "NESTE instante. Não se mexe: espere e volte a esta lista."
)
_MSG_NOTA_PRESA_SEM_CONFIRMACAO = (
    "Antes de libertar: abra o Vendus e procure a referência externa «%s». "
    "LIBERTAR quer dizer «não existe lá nenhuma nota de crédito com esta "
    "referência». Libertar uma que SAIU é autorizar uma segunda nota de "
    "crédito real da mesma devolução — dois documentos entregues à "
    "Autoridade Tributária a devolver o mesmo dinheiro. Se ela estiver lá, ou "
    "se não conseguir apurar, use «por apurar» em vez desta."
)
_MSG_NOTA_PRESA_COM_DOCUMENTO = (
    "Esta nota de crédito TEM um documento gravado (%s, ATCUD %s) — ela saiu. "
    "Não se liberta; a confirmação estava errada."
)
_MSG_NOTA_PRESA_ULTRAPASSADA = (
    "A nota de crédito mudou de estado enquanto isto era decidido — nada foi "
    "alterado. Volte a esta lista e olhe para ela outra vez."
)
_MSG_NOTA_PRESA_O_QUE_CONFIRMOU = (
    "Confirmou que NÃO existe no Vendus nenhuma nota de crédito com a "
    "referência externa «%s»."
)
_MSG_NOTA_PRESA_A_SEGUIR = (
    "A intenção foi apagada: a fatura volta a deixar creditar estas linhas e o "
    "fecho desta caixa deixa de ser recusado por causa dela."
)
_MSG_NOTA_POR_APURAR_A_SEGUIR = (
    "A nota ficou marcada POR APURAR: continua a travar novo crédito destas "
    "linhas (não se credita por cima do que talvez já tenha saído), NÃO "
    "desconta a gaveta (não se devolve dinheiro que talvez não tenha saído) e "
    "já não trava o fecho da caixa."
)


def _segundos_desde(instante: Optional[str], agora: datetime) -> Optional[float]:
    """Há quantos segundos foi `instante` — ou `None` se não se consegue ler.

    `None` não trava nada, pela mesma razão de `fiscal.libertar_reserva_presa`:
    uma emissão a decorrer tem SEMPRE um `criada_em` legível, escrito por
    `_agora()` na própria rota; uma nota sem ele é, por construção, dados
    estragados de há muito — exactamente o caso que estas rotas existem para
    desentalar."""
    if not instante:
        return None
    try:
        lido = datetime.fromisoformat(str(instante))
    except (TypeError, ValueError):
        return None
    if lido.tzinfo is None:
        lido = lido.replace(tzinfo=timezone.utc)
    return (agora - lido).total_seconds()


@router.get("/fiscal/notas-credito-presas")
async def listar_notas_credito_presas(_: Dict = Depends(gestor_atual)) -> List[Dict]:
    """Todas as notas de crédito PRESAS — as que reservaram e ficaram
    `reservada`, que são exactamente as que `caixa._nota_de_credito_em_curso`
    usa para recusar o fecho.

    Cada uma traz o que o gestor precisa para ir ver ao Vendus (a `ext_ref`, a
    loja, o número da fatura de origem, o total e o motivo), há quanto tempo
    está presa, e as duas saídas ditas por extenso."""
    db = obter_db()
    agora = datetime.now(timezone.utc)
    presas = await db[COLECOES["notas_credito"]].find(
        {"estado": "reservada"}, {"_id": 0}
    ).to_list(_LIMITE_NOTAS_PRESAS)
    saida = []
    for nota in presas:
        presa_ha_segundos = _segundos_desde(nota.get("criada_em"), agora)
        saida.append({
            "id": nota.get("id"),
            "ext_ref": nota.get("ext_ref"),
            "loja_id": nota.get("loja_id"),
            "caixa_id": nota.get("caixa_id"),
            "sessao_id": nota.get("sessao_id"),
            "documento_id": nota.get("documento_id"),
            "numero_origem": nota.get("numero_origem"),
            "motivo": nota.get("motivo"),
            "total": nota.get("total"),
            "devolucao": nota.get("devolucao"),
            "operador": nota.get("operador"),
            "criada_em": nota.get("criada_em"),
            "presa_ha_segundos": presa_ha_segundos,
            # Uma nota dentro da janela de uma emissão normal pode estar a
            # falar com o Vendus AGORA — e as duas rotas recusam-na. Dito aqui
            # para o gestor não carregar num botão que já se sabe recusado.
            "emissao_talvez_a_decorrer": (
                presa_ha_segundos is not None
                and presa_ha_segundos < _SEGUNDOS_DE_EMISSAO_NORMAL
            ),
            "saidas": (
                "Procure a referência externa no Vendus. NÃO está lá: "
                "LIBERTAR. Está lá, ou não consegue apurar: POR APURAR."
            ),
        })
    saida.sort(key=lambda n: n.get("criada_em") or "")
    return saida


class PedidoLibertarNota(BaseModel):
    """A confirmação do gestor, exigida com todas as letras — o mesmo contrato
    de `fiscal.PedidoLibertarReserva`, e sem valor por omissão útil de
    propósito."""

    confirmado_no_vendus: bool = False
    nota: Optional[str] = None


async def _nota_presa(db, intencao_id: str, agora: datetime) -> Dict:
    """A nota presa, ou o 4xx que diz porque não se lhe pode tocar."""
    nota = await db[COLECOES["notas_credito"]].find_one(
        {"id": intencao_id}, {"_id": 0})
    if nota is None:
        raise HTTPException(status_code=404, detail=_MSG_NOTA_PRESA_INEXISTENTE)
    if nota.get("estado") != "reservada":
        raise HTTPException(
            status_code=409,
            detail=_MSG_NOTA_PRESA_JA_RESOLVIDA % (nota.get("estado") or "num estado desconhecido"),
        )
    presa_ha_segundos = _segundos_desde(nota.get("criada_em"), agora)
    if presa_ha_segundos is not None and presa_ha_segundos < _SEGUNDOS_DE_EMISSAO_NORMAL:
        raise HTTPException(
            status_code=409,
            detail=_MSG_NOTA_PRESA_RECENTE % (
                presa_ha_segundos, int(_SEGUNDOS_DE_EMISSAO_NORMAL)),
        )
    return nota


@router.post("/fiscal/notas-credito/{intencao_id}/libertar")
async def libertar_nota_credito_presa(
    intencao_id: str,
    dados: PedidoLibertarNota,
    gestor: Dict = Depends(gestor_atual),
) -> Dict:
    """Apaga a intenção de uma nota de crédito presa — a saída para quando o
    gestor CONFIRMOU no Vendus que ela não saiu.

    De gestão, nunca do balcão (`gestor_atual`, o token do backoffice — não o
    PIN da operadora), e recusa-se em quatro casos: a nota não existe (404),
    já não está `reservada` (409), reservou há menos do que uma emissão normal
    (409 — pode estar a falar com o Vendus neste instante), ou já tem um
    documento gravado (409 — ela saiu mesmo, e a confirmação humana estava
    errada).

    **O apagar é CONDICIONAL ao estado `reservada`**, e é o `deleted_count`
    que decide: entre as guardas acima e esta linha corre um `await` (a
    procura do documento) em que a emissão original pode ter acordado e
    emitido. Apagar-lhe a intenção por baixo era autorizar a segunda nota
    real — a mesma disciplina de `fiscal._libertar_reserva_se_intacta`."""
    db = obter_db()
    agora = datetime.now(timezone.utc)
    nota = await _nota_presa(db, intencao_id, agora)
    ext_ref = nota.get("ext_ref")

    if not dados.confirmado_no_vendus:
        raise HTTPException(
            status_code=422,
            detail=_MSG_NOTA_PRESA_SEM_CONFIRMACAO % (ext_ref or "(sem referência)"),
        )

    documento = await db[COLECOES["documentos"]].find_one({"ext_ref": ext_ref})
    if ext_ref and documento is not None:
        raise HTTPException(
            status_code=409,
            detail=_MSG_NOTA_PRESA_COM_DOCUMENTO % (
                documento.get("numero"), documento.get("atcud")),
        )

    resultado = await db[COLECOES["notas_credito"]].delete_one(
        {"id": intencao_id, "estado": "reservada"})
    if resultado.deleted_count != 1:
        raise HTTPException(status_code=409, detail=_MSG_NOTA_PRESA_ULTRAPASSADA)

    # Apagar a intenção de um documento fiscal à mão é um acto sério, e a
    # intenção desaparece com ele: sem este registo não ficava rasto de quem a
    # libertou nem do que disse ter confirmado.
    logger.warning(
        "[faturacao] nota de crédito presa libertada à mão: id=%s ext_ref=%s "
        "loja=%s total=%s por=%s nota=%r",
        intencao_id, ext_ref, nota.get("loja_id"), nota.get("total"),
        gestor.get("email") or gestor.get("user_id"), dados.nota,
    )
    return {
        "libertada": True,
        "id": intencao_id,
        "ext_ref": ext_ref,
        "o_que_confirmou": _MSG_NOTA_PRESA_O_QUE_CONFIRMOU % (ext_ref or "(sem referência)"),
        "a_seguir": _MSG_NOTA_PRESA_A_SEGUIR,
    }


@router.post("/fiscal/notas-credito/{intencao_id}/por-apurar")
async def marcar_nota_credito_por_apurar(
    intencao_id: str,
    dados: PedidoLibertarNota,
    gestor: Dict = Depends(gestor_atual),
) -> Dict:
    """Marca uma nota de crédito presa como POR APURAR (`incerta`) — a saída
    SEGURA, para quando a nota está no Vendus ou não se consegue apurar.

    Não pede confirmação nenhuma, e é de propósito: esta é a direcção que
    nunca pode fazer estrago. A nota continua a travar novo crédito das mesmas
    linhas, continua a não descontar a gaveta, e deixa de travar o fecho —
    que é exactamente o estado em que uma emissão sem desfecho conhecido já
    ficava por si (`_marcar_incerta`).

    A marca é CONDICIONAL ao estado `reservada`, pela razão de sempre: entre a
    leitura e a escrita a emissão original pode ter acordado e concluído, e
    marcar `incerta` por cima de uma nota `emitida` era apagar do Z uma
    devolução que aconteceu."""
    db = obter_db()
    agora = datetime.now(timezone.utc)
    nota = await _nota_presa(db, intencao_id, agora)

    porque = "marcada por apurar pelo gestor%s" % (
        "" if not dados.nota else ": %s" % dados.nota)
    resultado = await db[COLECOES["notas_credito"]].update_one(
        {"id": intencao_id, "estado": "reservada"},
        {"$set": {"estado": "incerta", "incerta_porque": porque,
                  "incerta_em": _agora()}},
    )
    if resultado.matched_count != 1:
        raise HTTPException(status_code=409, detail=_MSG_NOTA_PRESA_ULTRAPASSADA)

    logger.warning(
        "[faturacao] nota de crédito presa marcada POR APURAR: id=%s ext_ref=%s "
        "loja=%s total=%s por=%s nota=%r",
        intencao_id, nota.get("ext_ref"), nota.get("loja_id"), nota.get("total"),
        gestor.get("email") or gestor.get("user_id"), dados.nota,
    )
    return {
        "por_apurar": True,
        "id": intencao_id,
        "ext_ref": nota.get("ext_ref"),
        "a_seguir": _MSG_NOTA_POR_APURAR_A_SEGUIR,
    }
