"""**Os pontos L'Açaí dados na caixa** — o POS a falar com a app.

A regra do dono: ganha os pontos quem mostra a app na caixa ANTES de pagar. O
talão deixa de ser um bilhete ao portador, porque o que dá pontos já não é o
QR fiscal impresso — é o QR da app, lido pela funcionária e preso a UMA venda.

Três peças, e uma regra acima das três: **nada daqui pode impedir uma fatura
de sair nem atrasar o EMITIR.**

1. **Ler** (`POST /pos/pontos/ler`) — troca o código do QR por uma ligação na
   app e devolve só o primeiro nome e um sim/não à fatura por email. Não grava
   nada na VENDA — é o ecrã que guarda a ligação e a manda no finalizar
   (`fiscal.PedidoFinalizarVenda`) — mas grava a preferência do email em
   `fat_pontos_qr`, porque suprimir um documento fiscal não se decide por um
   campo do corpo de um pedido do browser.
2. **A fila** (`fat_pontos_app`) — uma linha por crédito (FS) e por estorno
   (NC), com chave única. Nasce DEPOIS de o documento existir e nunca antes:
   os pontos só entram com a fatura já entregue à AT.
3. **O envio** — reserva a linha, fala com a app (4 s) e grava o desfecho. O
   que for técnico (rede, 5xx, chave errada) volta a tentar-se com espera
   crescente; o que for de negócio (`recusado`) não se repete.

A app é idempotente por ATCUD e por nota de crédito, e é isso que deixa este
lado ser simples: um reenvio nunca credita duas vezes.
"""
import asyncio
import base64
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from .auth import gestor_atual
from .db import COLECOES, obter_db
from .pos_auth import operador_atual
from .precos import CODIGO_NAO_SUJEITO
from .venda import (
    _aplicar_as_linhas,
    _garante_aberta,
    _garante_do_balcao,
    _garante_sem_emissao,
    _garante_sessao_desta_venda_aberta,
    _linha_vendus,
    _obter_venda_da_loja,
    _venda_publica,
)
from .vendus.cliente import ClienteVendus, obter_conta

logger = logging.getLogger(__name__)

router = APIRouter()

# 4 segundos, como o desconto de stock (`estoque_cliente.TIMEOUT_SAIDA_SEGUNDOS`)
# e pela mesma razão: quem espera pelo Ler é a funcionária com o cliente à
# frente. Uma app em baixo diz-se depressa, e a fatura segue sem pontos.
TIMEOUT_SEGUNDOS = 4.0

# **O tempo por ACÇÃO.** Os 4 s acima são para quem está ao balcão à espera (o
# Ler, o creditar, o estornar): uma app em baixo diz-se depressa e a fatura
# segue sem pontos. O envio da fatura por email é outra coisa — leva o PDF em
# base64 (~120 KB de texto) e corre em segundo plano, onde ninguém espera por
# ele. Com 4 s cortava-se um envio que ia bem a meio, e a fila repetia-o para
# sempre a cada volta do cron.
_TIMEOUT_POR_ACCAO = {"fatura-email": 25.0}

# Os testes trocam isto por um `httpx.MockTransport`; `None` é o transporte
# normal do httpx.
_transporte = None

_MSG_QR_INVALIDO = "QR inválido ou expirado — peça ao cliente para abrir o QR outra vez."
_MSG_APP_INDISPONIVEL = (
    "Não foi possível falar com a app agora. A fatura pode seguir sem pontos."
)


class IntegracaoNaoConfigurada(Exception):
    """Falta `APP_LACAI_URL` ou `APP_LACAI_CHAVE`. Não é uma avaria — é uma
    instalação por acabar."""


async def _chamar_app(acao: str, corpo: Dict) -> httpx.Response:
    """`POST {APP_LACAI_URL}/api/pos-integracao/{acao}` com a chave de serviço.

    As duas variáveis lêem-se a CADA chamada e não à importação (o molde é
    `estoque_cliente.chave_de_servico`): o `.env` pode ganhá-las sem o portal
    reiniciar, e uma constante de módulo congelava o «não configurado».

    A chave vai no CABEÇALHO e nunca no URL: um `?key=` fica escrito nos
    registos de quem estiver pelo meio."""
    url = (os.environ.get("APP_LACAI_URL") or "").strip().rstrip("/")
    chave = (os.environ.get("APP_LACAI_CHAVE") or "").strip()
    if not url or not chave:
        raise IntegracaoNaoConfigurada("integração não configurada")
    async with httpx.AsyncClient(
        timeout=_TIMEOUT_POR_ACCAO.get(acao, TIMEOUT_SEGUNDOS),
        transport=_transporte,
    ) as http:
        return await http.post(
            "%s/api/pos-integracao/%s" % (url, acao),
            json=corpo,
            headers={"X-Service-Key": chave},
        )


def _json_ou_nada(resposta: httpx.Response):
    try:
        return resposta.json()
    except ValueError:
        return None


# --- Ler o QR -----------------------------------------------------------------


class PedidoLerQr(BaseModel):
    venda_id: str = Field(min_length=1, max_length=100)
    # O código vai CRU: quem o normaliza (espaços, maiúsculas) é a app, que é
    # quem conhece o formato. Aqui só se trava o tamanho — um leitor avariado
    # não manda um livro à app.
    codigo: str = Field(min_length=1, max_length=200)


async def _gravar_qr_da_ligacao(db, ligacao_id: str, fatura_por_email: bool) -> bool:
    """Grava em `fat_pontos_qr` a preferência desta leitura, e diz se ficou lá.

    **É esta linha, e não o corpo do EMITIR, que decide se sai papel**
    (`enfileirar_fatura_email`). A ligação já viaja no `dados_pagamento` do
    finalizar (`fiscal.py:2136`) e isso é aceitável para pontos; para SUPRIMIR
    um documento fiscal não é — um campo forjado pelo browser, ou um defeito no
    ecrã, fazia desaparecer o documento do cliente. Esta linha é do servidor e
    caduca sozinha em 2 horas.

    **Só se escreve quando a preferência está LIGADA.** Uma preferência
    desligada e uma linha que não existe querem dizer exactamente a mesma coisa
    — sai papel — e a colecção fica com uma linha por fatura desmaterializada
    em vez de uma por leitura do QR.

    **Nunca levanta.** Uma escrita falhada é papel a sair, que é o lado seguro;
    levantar era um 503 ao balcão depois de a app já ter consumido o código do
    QR, e a funcionária a pedir ao cliente um código novo que já não servia.

    **Idempotente por leitura antes de escrever.** Chamada duas vezes para a
    mesma ligação (o botão «Ligar» do cartão carregado duas vezes) não pode
    deixar duas linhas — não há índice único sobre `ligacao_id` (só o TTL de
    `criada_em`) a impedi-lo."""
    if not fatura_por_email:
        return False
    try:
        if await db[COLECOES["pontos_qr"]].find_one({"ligacao_id": ligacao_id}):
            return True
        await db[COLECOES["pontos_qr"]].insert_one({
            "ligacao_id": ligacao_id,
            "fatura_por_email": True,
            # Uma DATA a sério e não a string ISO do resto do módulo: o índice
            # TTL de `db.py` só expira por um campo do tipo Date.
            "criada_em": datetime.now(timezone.utc),
        })
    except Exception as e:  # noqa: BLE001 — sem linha sai papel, que é o lado seguro
        logger.error(
            "[faturacao] a preferência de fatura por email da ligação %s NÃO ficou "
            "gravada (a fatura desta venda sai em papel): %s", ligacao_id, e)
        return False
    return True


@router.post("/pos/pontos/ler")
async def ler_qr_de_pontos(
    dados: PedidoLerQr, operador: Dict = Depends(operador_atual)
) -> dict:
    """Troca o QR que o cliente mostra por uma ligação na app.

    **A venda confere-se ANTES de falar com a app**, e a ordem não é gosto: a
    app consome o token do QR na primeira leitura. Perguntar-lhe primeiro e
    recusar depois (venda de outra loja, já emitida) gastava o QR do cliente
    para nada, e ele tinha de o abrir outra vez. As recusas são as das outras
    rotas de venda (`venda.py`): 404 «Venda não encontrada.» para uma venda que
    não existe OU é de outra loja, 409 para uma que já não está aberta (a
    frase própria da conta dividida, `_MSG_VENDA_SEPARADA`, ou a genérica).

    **Não grava nada na venda.** A ligação volta ao ecrã, que a guarda presa ao
    id da conta e a manda no finalizar. Uma leitura que não acabe em fatura
    não deixa lixo em lado nenhum deste servidor.

    A loja e o operador vão pelo NOME e saem do TOKEN, nunca do corpo: são o
    registo de quem associou que conta a que venda, para o relatório de
    concentração da 2.ª fase."""
    db = obter_db()
    venda = await _obter_venda_da_loja(db, dados.venda_id, operador["loja_id"])
    _garante_aberta(venda)
    loja = await db[COLECOES["lojas"]].find_one(
        {"id": operador["loja_id"]}, {"_id": 0, "nome": 1})
    try:
        resposta = await _chamar_app("ligar", {
            "codigo": dados.codigo,
            "loja_nome": (loja or {}).get("nome") or "",
            "operador_nome": operador.get("nome") or "",
        })
    # `Exception` e não `httpx.HTTPError`: um erro de dedo na PORTA do
    # `APP_LACAI_URL` (`8OO1` com letras) levanta `httpx.InvalidURL`, que herda
    # directamente de `Exception` e escapava ao tuplo. Para a funcionária tudo
    # o que venha daqui é o mesmo: a app não respondeu, a fatura segue sem
    # pontos — «Internal Server Error» não era a frase de ninguém.
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[faturacao] ler QR de pontos (venda %s): a app não respondeu — %s: %s",
            dados.venda_id, type(e).__name__, e)
        raise HTTPException(status_code=503, detail=_MSG_APP_INDISPONIVEL)
    # **Só é «QR inválido» o 404 que o contrato descreve** — o da app, que traz
    # sempre `{"estado": "recusado", "motivo": "qr_invalido"}`. Um 404 do
    # FastAPI da app (`{"detail": "Not Found"}`, a rota por deployar) ou de um
    # proxy pelo meio (404 em HTML) é a app a não estar lá, e a frase certa é a
    # do 503: traduzido para «peça outro QR», a funcionária pedia ao cliente um
    # código novo vezes sem conta e nenhum ia funcionar.
    corpo_do_404 = _json_ou_nada(resposta) if resposta.status_code == 404 else None
    if isinstance(corpo_do_404, dict) and corpo_do_404.get("motivo") == "qr_invalido":
        raise HTTPException(status_code=404, detail=_MSG_QR_INVALIDO)
    corpo = _json_ou_nada(resposta) if resposta.status_code == 200 else None
    if not isinstance(corpo, dict) or not corpo.get("ligacao_id"):
        # 401 (chave trocada), 5xx, ou um 200 sem a forma do contrato: para a
        # funcionária é tudo «a app não está a responder»; o pormenor fica no log.
        logger.error(
            "[faturacao] ler QR de pontos (venda %s): resposta inesperada da app "
            "(HTTP %s): %s", dados.venda_id, resposta.status_code, resposta.text[:200])
        raise HTTPException(status_code=503, detail=_MSG_APP_INDISPONIVEL)
    ligacao_id = str(corpo["ligacao_id"])
    return {
        "ligacao_id": ligacao_id,
        "primeiro_nome": str(corpo.get("primeiro_nome") or ""),
        # **O que se devolve é o que ficou GRAVADO**, nunca o que a app disse.
        # O ecrã usa isto só para desenhar o cartão do Finalizar; se ele for
        # adulterado, o pior que acontece é o cartão mentir ao staff — mas se
        # devolvêssemos a preferência da app sem a gravar, o cartão prometia
        # email por cima de um talão a sair, que é a mentira que interessa.
        "fatura_por_email": await _gravar_qr_da_ligacao(
            db, ligacao_id, bool(corpo.get("fatura_por_email"))),
    }


# --- A preferência (o botão do cartão, depois de o QR já estar lido) -----------


async def _apagar_qr_da_ligacao(db, ligacao_id: str) -> bool:
    """O inverso de `_gravar_qr_da_ligacao`: tira a linha de `fat_pontos_qr`
    desta ligação, e — a MESMA forma do irmão — diz o que FICOU lá.

    **É este apagamento, e não a falta de escrita, que faz o «Voltar ao papel»
    funcionar.** `_gravar_qr_da_ligacao` só grava quando a preferência está
    LIGADA e nunca apaga nada — sem isto, desligar deixava a linha antiga viva
    e o talão do cliente continuava suprimido depois de ele ter pedido papel.

    `delete_many` e não `delete_one`: não há índice único sobre `ligacao_id`
    (só o TTL de `criada_em`), por isso a colecção pode ter mais do que uma
    linha para a mesma ligação, e uma que ficasse para trás era o mesmo
    defeito outra vez.

    **Nunca levanta, e um apagamento FALHADO devolve `True`.** Levantar era um
    «Internal Server Error» ao balcão — a frase que este módulo inteiro existe
    para evitar — e, pior, o desfecho mais mentiroso possível: a linha do
    `fat_pontos_qr` SOBREVIVE a uma escrita falhada, e é ela que manda saltar
    o papel (`enfileirar_fatura_email`). A funcionária carregava em «Voltar ao
    papel», via um erro, e o talão continuava suprimido na mesma. Devolver
    `True` é dizer a verdade — a linha ficou lá, a fatura ainda vai por email —
    e é o que faz o cartão do ecrã mostrar o estado a sério, para ela voltar a
    tentar."""
    try:
        await db[COLECOES["pontos_qr"]].delete_many({"ligacao_id": ligacao_id})
    except Exception as e:  # noqa: BLE001 — a linha ficou lá, e é isso que se devolve
        logger.error(
            "[faturacao] a preferência de fatura por email da ligação %s NÃO foi "
            "apagada (a fatura desta venda continua a ir por email): %s",
            ligacao_id, e)
        return True
    return False


class PedidoPreferenciaPontos(BaseModel):
    venda_id: str = Field(min_length=1, max_length=100)
    ligacao_id: str = Field(min_length=1, max_length=100)
    valor: bool


_MSG_LIGACAO_JA_USADA = (
    "Este QR já foi usado nesta ou noutra fatura — peça ao cliente para o "
    "abrir outra vez."
)
_MSG_LIGACAO_EXPIRADA = (
    "A leitura do QR já expirou — peça ao cliente para o mostrar outra vez."
)
_MSG_RECUSA_GENERICA = (
    "Não foi possível gravar a preferência agora — peça ao cliente para "
    "mostrar o QR outra vez."
)

# O motivo CRU da app (`_recusa` do lado dela é 200 com o motivo, nunca um
# 4xx) → (status HTTP, frase em português). Um motivo que não esteja aqui leva
# a frase genérica — mas NUNCA o código-máquina, que não diz à funcionária o
# que fazer a seguir.
_RECUSAS_DA_PREFERENCIA = {
    "ligacao_desconhecida": (409, _MSG_LIGACAO_JA_USADA),
    "ligacao_ja_usada": (409, _MSG_LIGACAO_JA_USADA),
    "fora_da_janela": (409, _MSG_LIGACAO_EXPIRADA),
}


@router.post("/pos/pontos/preferencia")
async def preferencia_de_pontos(
    dados: PedidoPreferenciaPontos, operador: Dict = Depends(operador_atual)
) -> dict:
    """Liga ou desliga a fatura por email de uma ligação já lida — o botão do
    cartão do Finalizar.

    **A venda confere-se ANTES de falar com a app**, o mesmo molde do
    `ler_qr_de_pontos` — mas aqui a razão não é poupar um QR de uso único (essa
    ligação já foi consumida na leitura): é que mudar a preferência de uma
    venda que já não está aberta não muda nada nenhures, e só mentia ao ecrã.

    **A app é quem decide** — é dela o consentimento do cliente e a auditoria
    de quem ligou a preferência e onde. A resposta que sai daqui nunca é o
    `valor` pedido: é o que FICOU em `fat_pontos_qr` depois de a app
    responder, a mesma regra do `ler`."""
    db = obter_db()
    venda = await _obter_venda_da_loja(db, dados.venda_id, operador["loja_id"])
    _garante_aberta(venda)
    loja = await db[COLECOES["lojas"]].find_one(
        {"id": operador["loja_id"]}, {"_id": 0, "nome": 1})
    try:
        resposta = await _chamar_app("preferencia", {
            "ligacao_id": dados.ligacao_id,
            "valor": dados.valor,
            "loja_nome": (loja or {}).get("nome") or "",
            "operador_nome": operador.get("nome") or "",
        })
    # O mesmo `except Exception` do `ler`, e pela mesma razão: um erro de dedo
    # na PORTA do `APP_LACAI_URL` levanta `httpx.InvalidURL`, que não é
    # `HTTPError`. Para a funcionária tudo o que vier daqui é «a app não
    # respondeu» — nunca um «Internal Server Error».
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[faturacao] preferência de pontos (venda %s, ligação %s): a app "
            "não respondeu — %s: %s", dados.venda_id, dados.ligacao_id,
            type(e).__name__, e)
        raise HTTPException(status_code=503, detail=_MSG_APP_INDISPONIVEL)
    corpo = _json_ou_nada(resposta) if resposta.status_code == 200 else None
    estado = corpo.get("estado") if isinstance(corpo, dict) else None
    if estado == "recusado":
        # `str(...)` e não o `.get` cru: a chave de um dicionário tem de ser
        # lavável, e um `motivo` não-escalar (uma LISTA, um objecto) levanta
        # `TypeError: unhashable type` — aqui FORA do `try` de cima, por isso
        # subia crua e a funcionária lia «Internal Server Error», que é a frase
        # que este módulo inteiro existe para não mostrar. Convertido, um motivo
        # que não esteja no mapa leva a frase genérica, como qualquer outro.
        status, frase = _RECUSAS_DA_PREFERENCIA.get(
            str(corpo.get("motivo") or ""), (409, _MSG_RECUSA_GENERICA))
        raise HTTPException(status_code=status, detail=frase)
    if estado != "gravada":
        # 401 (chave trocada), 5xx, ou um 200 sem a forma do contrato: a
        # mesma frase do `ler` — para a funcionária, a app não está a
        # responder.
        logger.error(
            "[faturacao] preferência de pontos (venda %s, ligação %s): "
            "resposta inesperada da app (HTTP %s): %s", dados.venda_id,
            dados.ligacao_id, resposta.status_code, resposta.text[:200])
        raise HTTPException(status_code=503, detail=_MSG_APP_INDISPONIVEL)
    fatura_por_email = bool(corpo.get("fatura_por_email"))
    if fatura_por_email:
        gravado = await _gravar_qr_da_ligacao(db, dados.ligacao_id, True)
    else:
        # Apagar, e não só deixar de escrever — ver `_apagar_qr_da_ligacao`. E
        # o que se devolve é o que ELE diz que ficou, nunca um `False` assumido:
        # um apagamento falhado deixa a linha viva e a fatura continua a ir por
        # email.
        gravado = await _apagar_qr_da_ligacao(db, dados.ligacao_id)
    return {"fatura_por_email": gravado}


# --- O voucher ao balcão ---------------------------------------------------------
#
# A peça exactamente INVERSA dos pontos. Os pontos mandam informação DEPOIS da
# fatura (creditar); um desconto tem de ser decidido ANTES do EMITIR.
#
# A regra do dono: a recompensa fica na carteira e vale nos dois sítios — no
# checkout da app e ao balcão. Quem chegar primeiro usa-a. **A app decide o
# desconto**, porque é uma regra de dinheiro e vive num sítio só; o POS
# aplica-o na linha e emite.
#
# E as duas regras acima de tudo o resto:
#
# 1. **Nada disto pode impedir uma fatura de sair.** App em baixo, tecto de
#    espera esgotado ou resposta estranha = venda normal, sem desconto.
# 2. **Falhar fechado e EM VOZ ALTA.** Uma categoria sem correspondência é
#    *sem desconto*, nunca um desconto errado — mas grita no registo e volta ao
#    cartão da caixa com o motivo. Um voucher que não se aplica sem ninguém
#    perceber porquê é o pior desfecho de todos.


class PedidoVoucher(BaseModel):
    # **`None` é o «Remover» do cartão dos pontos, e não um pedido vazio.** O
    # ecrã tira o cliente da fatura e chama esta rota com `ligacao_id: null`
    # para o desconto sair da conta com ele (`lib/pos.js::pedirVoucherDaConta`).
    #
    # Com `min_length=1` isto era 422, e por aí saía dinheiro: o `catch` do ecrã
    # engole o erro em silêncio, a marca e o desconto FICAM na linha, e a partir
    # daí ou a funcionária cobra os 7,20 € e o EMITIR recusa (a soma dos
    # pagamentos não bate com um total de 0,00 € — **a fatura não sai**, com o
    # cliente à frente), ou emite a 0,00 € sem pagamento nenhum e sem ligação de
    # pontos: o `/creditar` nunca corre, o voucher nunca é consumido e volta a
    # `active`. Açaí de graça E recompensa devolvida.
    #
    # Sem `min_length` de propósito: um `""` normaliza-se para `None` na rota em
    # vez de virar outro 422 no mesmo sítio.
    ligacao_id: Optional[str] = Field(None, max_length=100)


async def escolher_voucher(
    ligacao_id: str, linhas: List[Dict], *, venda_id: str = ""
) -> Optional[Dict]:
    """Pergunta à app que recompensa desconta esta conta. **`None` quer dizer
    «não sei»** — e é essa diferença que manda em tudo o resto.

    O molde é o do `ler_qr_de_pontos`: os mesmos 4 s de tecto (`_chamar_app`,
    `TIMEOUT_SEGUNDOS`) porque quem espera é a funcionária com o cliente à
    frente, e o mesmo `except Exception` largo — um erro de dedo na PORTA do
    `APP_LACAI_URL` (`8OO1` com letras) levanta `httpx.InvalidURL`, que herda
    directamente de `Exception` e escaparia a um tuplo de `httpx.HTTPError`.

    **Qualquer falha significa SEM DESCONTO, nunca um desconto errado**: rede em
    baixo, tecto esgotado, 401 (chave trocada), 5xx, ou um 200 sem a forma do
    contrato. Devolver `None` é dizer «não sei», e quem chama deixa a conta
    exactamente como ela estava.

    O `{}` da app (não há voucher para esta conta) e o `{"motivo": ...}` (recusa
    de negócio, em 200 como as rotas irmãs) **são respostas e não falhas**:
    voltam tal e qual, para o cartão da caixa poder dizer porquê."""
    try:
        resposta = await _chamar_app(
            "voucher", {"ligacao_id": ligacao_id, "linhas": linhas})
    except Exception as e:  # noqa: BLE001 — ver a docstring: qualquer falha é «sem desconto»
        logger.warning(
            "[faturacao] voucher ao balcão (venda %s, ligação %s): a app não "
            "respondeu — %s: %s (a venda segue SEM desconto)",
            venda_id, ligacao_id, type(e).__name__, e)
        return None
    corpo = _json_ou_nada(resposta) if resposta.status_code == 200 else None
    if not isinstance(corpo, dict):
        logger.error(
            "[faturacao] voucher ao balcão (venda %s, ligação %s): resposta "
            "inesperada da app (HTTP %s): %s (a venda segue SEM desconto)",
            venda_id, ligacao_id, resposta.status_code, resposta.text[:200])
        return None
    return corpo


async def _libertar_na_app(ligacao_id: str, venda_id: str) -> None:
    """Diz à app que esta venda ficou SEM desconto, para ela libertar o voucher
    que já tinha reservado.

    **O desfecho que isto impede: o cliente paga tudo E perde a recompensa.**
    Há saídas desta rota em que a app JÁ reservou o voucher e já armou o
    `/creditar` (a ligação guarda o `voucher_id`) e a conta, aqui, não levou
    desconto nenhum — a linha alvo desapareceu, o contrato veio partido, a
    escrita perdeu a corrida. Sem este aviso a Fatura Simplificada sai ao preço
    cheio com a ligação dos pontos preenchida, o `/creditar` consome o voucher, e
    o cliente fica sem os dois. É a regra de ouro 3 ao contrário.

    **É a MESMA rota do voucher com as `linhas` VAZIAS**, e não uma rota nova de
    nenhum dos lados: é o contrato que a app já tem — nenhuma linha serve, logo a
    reserva liberta-se e o `voucher_id` da ligação volta a `None`
    (`routes_pos_integracao.voucher`).

    **Nunca levanta e nunca muda a resposta ao ecrã.** `escolher_voucher` já
    engole tudo o que corra mal, que é a regra de ouro 1: a app em baixo aqui não
    pode virar um erro ao balcão. Falhado o aviso, a reserva morre sozinha do
    lado da app ao fim de 15 minutos
    (`services_vouchers.release_stale_reservations`) — o voucher volta ao
    cliente, que é o lado seguro."""
    await escolher_voucher(ligacao_id, [], venda_id=venda_id)


async def _linhas_para_a_app(db, venda: Dict) -> List[Dict]:
    """As linhas desta conta no formato do contrato:
    `[{linha_id, categoria_vendus_ref, unit_price, qty}]`.

    **A ponte entre os dois catálogos é a CATEGORIA, e só ela.** O campo
    `vendus_ref` existe dos dois lados e guarda coisas DIFERENTES: aqui é o
    `id` do artigo no Vendus (`precos.id_vendus_do_produto`), na app é a
    `reference` do artigo. Não se casam — e casar por produto seria mau
    negócio de qualquer forma (são centenas, mudam todas as semanas, e a
    elegibilidade do voucher nem sequer trabalha a esse nível). As categorias
    dos dois catálogos vieram do MESMO catálogo Vendus e guardam o id da
    categoria de lá: é essa a única chave partilhada.

    **O `linha_id` vai e a categoria não chega.** Duas linhas podem partilhar
    categoria, e é UMA delas que leva o desconto — é a app que diz qual.

    **O preço unitário sai de `_linha_vendus`**, nunca de uma conta feita aqui:
    é o mesmo número que vai para a fatura, já com as personalizações somadas e
    arredondado uma só vez. Uma segunda aritmética divergia no dia em que a
    primeira mudasse, e a elegibilidade é exactamente `unit_price >= valor` do
    voucher.

    **Uma categoria sem `vendus_ref` viaja a `None` e GRITA no registo.** Não se
    adivinha nada — quem decide é a app, que responde
    `categoria_sem_correspondencia` —, mas o sintoma de uma categoria por
    preencher é um voucher que não se aplica, e isso não pode ficar calado.

    Duas leituras e não duas por linha: ao balcão, com o cliente à frente, cada
    ida à base de dados conta contra os 4 s da chamada à app."""
    linhas = venda.get("linhas") or []
    if not linhas:
        return []
    produtos = {
        p["id"]: p
        for p in await db[COLECOES["produtos"]].find(
            {"id": {"$in": [li.get("produto_id") for li in linhas]}},
            {"_id": 0, "id": 1, "categoria_id": 1},
        ).to_list(500)
    }
    categorias = {
        c["id"]: c
        # **A projecção é afirmada à mão no teste** (`test_voucher_ao_balcao.py::
        # test_a_projeccao_das_categorias_PEDE_o_vendus_ref`), porque o duplo
        # desta casa aceita-a e IGNORA-A: sem essa prova, apagar `vendus_ref`
        # daqui deixava a suite inteira verde e, em produção, TODAS as categorias
        # chegavam sem o campo — o desconto ao balcão deixava de existir para
        # toda a gente. Guarda-se a selecção (e não se lê a categoria inteira)
        # porque quem espera por estes 4 s é a funcionária com o cliente à frente.
        for c in await db[COLECOES["categorias"]].find(
            {"id": {"$in": [p.get("categoria_id") for p in produtos.values()]}},
            {"_id": 0, "id": 1, "nome": 1, "vendus_ref": 1},
        ).to_list(500)
    }
    saida = []
    for li in linhas:
        try:
            preco_unitario = _linha_vendus(li)["gross_price"]
        except HTTPException as e:
            # Uma linha que nem sequer se consegue calcular (produto sem IVA,
            # sem preço, override impossível) não pode levar desconto nenhum —
            # e o 422 dela é problema do EMITIR, não deste cartão. Devolver
            # lista vazia deixa a app sem por onde escolher e a venda segue
            # normal, que é a regra de ouro desta integração.
            logger.error(
                "[faturacao] voucher ao balcão (venda %s): a linha %s não se "
                "consegue calcular (%s) — a conta vai SEM desconto",
                venda.get("id"), li.get("id"), e.detail)
            return []
        categoria = categorias.get(
            (produtos.get(li.get("produto_id")) or {}).get("categoria_id")) or {}
        referencia = categoria.get("vendus_ref")
        if not referencia:
            logger.error(
                "[faturacao] voucher ao balcão (venda %s): a categoria %r do "
                "produto %r não tem `vendus_ref` — nenhuma recompensa da app "
                "consegue casar com esta linha até alguém o preencher no "
                "catálogo", venda.get("id"),
                categoria.get("nome") or categoria.get("id"),
                li.get("produto_nome"))
        saida.append({
            "linha_id": li.get("id"),
            "categoria_vendus_ref": str(referencia) if referencia else None,
            "unit_price": preco_unitario,
            "qty": li.get("quantidade") or 1,
        })
    return saida


def _resposta_do_voucher(
    venda: Dict, *, voucher_id: Optional[str] = None, valor: Optional[float] = None,
    titulo: Optional[str] = None, linha_id_alvo: Optional[str] = None,
    motivo: Optional[str] = None, app_indisponivel: bool = False,
) -> Dict:
    """As cinco chaves do contrato — **sempre presentes**, a `None` quando não
    há — mais a conta como ela FICOU e o `app_indisponivel`.

    Chaves sempre presentes é a regra da casa (ver `_venda_publica`): o ecrã não
    pode ter de adivinhar se a ausência de `voucher_id` quer dizer «não há
    voucher» ou «esta versão do servidor não sabe responder a isso».

    **O que se devolve é o que ficou GRAVADO na conta**, nunca o que a app
    disse — a mesma regra do `fatura_por_email` do `ler`. Um `voucher_id` que a
    app escolheu mas que não chegou a entrar em linha nenhuma era o cartão a
    prometer à funcionária um desconto que o total não tem.

    **A conta vai junta, e é por ela que o total do ecrã fica certo.** O
    desconto foi escrito aqui, do lado do servidor; sem a conta de volta o ecrã
    mostrava o total de antes e a funcionária cobrava o que não é.

    **`app_indisponivel` guarda a diferença entre «não sei» e «não há».**
    `escolher_voucher` distingue as duas (`None` é a app em baixo, `{}` é não há
    voucher) e sem este campo a rota deitava a diferença fora: as duas produziam
    o mesmo corpo com as chaves a `None`. O caso: desconto aplicado, cartão a
    dizer «Açaí Médio grátis», a app cai, a funcionária carrega em EMITIR, esta
    rota responde 200 — e o ecrã apagava a recompensa do cartão e recusava a
    emissão com «A recompensa desta conta mudou», que é FALSO: não mudou nada,
    foi a app que não respondeu. Falhar fechado é a regra de ouro 2; falhar
    fechado **em silêncio, a mentir**, é o contrário dela."""
    return {
        "voucher_id": voucher_id,
        "valor": valor,
        "titulo": titulo,
        "linha_id_alvo": linha_id_alvo,
        "motivo": motivo,
        "app_indisponivel": app_indisponivel,
        "venda": _venda_publica(venda),
    }


@router.post("/pos/venda/{venda_id}/voucher")
async def voucher_ao_balcao(
    venda_id: str, dados: PedidoVoucher, operador: Dict = Depends(operador_atual)
) -> dict:
    """A recompensa L'Açaí aplicada à conta do balcão, lida pelo MESMO QR que já
    dá pontos.

    Monta as linhas, pergunta à app qual é o desconto (4 s), escreve-o no
    `desconto_eur` da linha que ela escolheu e marca essa linha com o
    `voucher_id`. Daí para a frente é máquina que já existe: `_itens_vendus`
    converte qualquer desconto na percentagem que reproduz o líquido ao cêntimo
    (`fiscal._percentagem_que_reproduz`), pelo único campo cuja semântica já foi
    confirmada contra o Vendus.

    **A MARCA na linha é metade do ponto desta rota.** Sem ela, depois de
    emitida ninguém distingue um desconto de voucher de um que a funcionária deu
    de cabeça: o talão não pode dizer «Oferta L'Açaí», os relatórios não sabem
    quanto custou a fidelidade ao balcão, e — o que decide — o travão da conta a
    zero (`fiscal.finalizar`) não teria como saber que aquele 0,00 € é uma
    oferta e não um desconto manual de 100 %.

    **É chamada DUAS vezes**, ao ler o QR (para a funcionária ver antes de
    cobrar) e ao EMITIR (a conta pode ter mudado pelo meio). A segunda com a
    mesma ligação devolve a mesma reserva do lado da app; se as linhas mudaram e
    o voucher deixou de servir, a app liberta-o e escolhe outro — por isso o que
    ela responde AGORA é o que vale, e uma marca antiga limpa-se sempre antes de
    escrever a nova.

    **As MESMAS quatro guardas das rotas que escrevem linhas** (`venda.py`), e
    não as duas do `ler`: isto ESCREVE na conta. Uma conta com reserva fiscal
    está congelada e não pode ganhar um desconto a meio de virar Fatura
    Simplificada, e uma sessão de caixa a fechar não pode ver o seu turno mudar
    por baixo do Z. Correm ANTES de falar com a app, o mesmo molde do `ler`: uma
    recusa depois da chamada deixava do outro lado uma reserva de voucher por
    uma conta que nunca ia ser cobrada.

    **A app em baixo deixa a conta EXACTAMENTE como estava** — nem limpa o que
    já lá está. É a regra de ouro: nada daqui pode impedir uma fatura de sair, e
    tirar um desconto já aplicado no instante do EMITIR mudava o total depois de
    o dinheiro estar contado, e a soma dos pagamentos deixava de bater. Mas
    **diz-se que foi «não sei»** (`app_indisponivel`): sem isso o ecrã lia esta
    resposta como «a app diz que não há voucher» e acusava o cliente de uma
    mudança que não houve.

    **`ligacao_id` a `None` é o «Remover»**, não um pedido vazio: tira o desconto
    e a marca da conta sem falar com a app. Ver `PedidoVoucher`."""
    db = obter_db()
    venda = await _obter_venda_da_loja(db, venda_id, operador["loja_id"])
    _garante_aberta(venda)
    _garante_do_balcao(venda)
    await _garante_sem_emissao(db, venda_id)
    await _garante_sessao_desta_venda_aberta(db, venda)

    # **Sem ligação é o «Remover», e aí não há nada a perguntar a ninguém.** O
    # que o ecrã pede é «tira o desconto e a marca desta conta» — e um `{}` é
    # exactamente «não há voucher», que é a resposta que o caminho abaixo já sabe
    # tratar (limpa a marca e o desconto das linhas). A reserva do lado da app
    # fica sem quem a liberte daqui — não temos ligação nenhuma para a nomear —
    # e morre sozinha em 15 minutos
    # (`services_vouchers.release_stale_reservations`): o voucher volta ao
    # cliente, que é o lado seguro.
    ligacao_id = (dados.ligacao_id or "").strip() or None
    corpo: Optional[Dict] = {}
    if ligacao_id:
        corpo = await escolher_voucher(
            ligacao_id, await _linhas_para_a_app(db, venda), venda_id=venda_id)
    if corpo is None:
        # «Não sei», e o ecrã tem de o poder separar de «não há» — ver
        # `_resposta_do_voucher`.
        return _resposta_do_voucher(venda, app_indisponivel=True)

    titulo = str(corpo.get("titulo") or "") or None
    motivo = str(corpo.get("motivo") or "") or None
    voucher_id = str(corpo.get("voucher_id") or "") or None
    alvo_id = str(corpo.get("linha_id_alvo") or "") or None
    valor = round(float(corpo.get("valor") or 0), 2)
    if voucher_id and (not alvo_id or valor <= 0):
        # Um voucher sem linha alvo ou sem valor é o contrato partido. Vale a
        # regra de sempre: sem desconto, e a gritar — nunca um desconto errado.
        logger.error(
            "[faturacao] voucher ao balcão (venda %s): a app escolheu o voucher "
            "%s mas mandou linha_id_alvo=%r e valor=%r — a conta vai SEM "
            "desconto", venda_id, voucher_id, corpo.get("linha_id_alvo"),
            corpo.get("valor"))
        # E avisa-se a app: ela reservou este voucher e armou o `/creditar` com
        # ele. Ver `_libertar_na_app` — sem isto o cliente pagava tudo e perdia a
        # recompensa na mesma venda.
        await _libertar_na_app(ligacao_id, venda_id)
        voucher_id, motivo = None, motivo or "contrato_partido"

    if not voucher_id and not any(
            li.get("voucher_id") for li in venda.get("linhas") or []):
        # Nada para escrever — o caso normal, a esmagadora maioria das contas.
        # Escrever à mesma incrementava o `linhas_versao` e disputava a conta
        # com o ecrã por nada (ver `_aplicar_as_linhas`).
        return _resposta_do_voucher(venda, titulo=titulo, motivo=motivo)

    def aplicar(conta):
        linhas = list(conta.get("linhas") or [])
        # **Limpar PRIMEIRO, sempre.** A rota corre duas vezes e a conta pode
        # ter mudado pelo meio: uma marca antiga deixada para trás era um
        # produto oferecido com um voucher que a app já libertou.
        for li in linhas:
            if li.get("voucher_id"):
                li["voucher_id"] = None
                # O desconto vai com a marca: foi esta rota que o pôs, e
                # deixá-lo era uma oferta sem voucher nenhum por trás.
                #
                # ponytail: um desconto manual que já estivesse NESTA linha
                # antes do voucher perde-se aqui, e a operadora volta a pô-lo.
                # Guardar o valor anterior era um campo novo por um caso que ao
                # balcão não acontece — a alternativa é gravá-lo se aparecer.
                li["desconto_eur"] = None
        alvo = (next((li for li in linhas if li.get("id") == alvo_id), None)
                if voucher_id else None)
        if alvo is not None:
            candidata = dict(alvo, voucher_id=voucher_id, desconto_eur=valor)
            # Valida a versão com desconto ANTES de gravar, como o
            # `venda.editar_linha`: um desconto maior do que a linha inteira
            # produziria uma linha NEGATIVA numa fatura real
            # (`precos.linha_de_venda`). A elegibilidade da app impede-o
            # (`unit_price >= valor`), e é por isso mesmo que se confirma aqui.
            _linha_vendus(candidata)
            alvo.update({"voucher_id": voucher_id, "desconto_eur": valor})
        return linhas

    try:
        venda = await _aplicar_as_linhas(
            db, venda_id, operador["loja_id"], aplicar, venda)
    except HTTPException:
        # A escrita não passou: a conta mudou por baixo quatro vezes seguidas
        # (409), deixou de estar aberta, nasceu-lhe uma reserva fiscal, ou a
        # linha com desconto não se consegue calcular (422 do `_linha_vendus`).
        # O desconto NÃO entrou na conta e o voucher está reservado do lado da
        # app — libertá-lo ANTES de subir é o que impede o cliente de pagar tudo
        # e ficar sem a recompensa. Ver `_libertar_na_app`.
        if voucher_id:
            await _libertar_na_app(ligacao_id, venda_id)
        raise
    if voucher_id and not any(
            li.get("voucher_id") == voucher_id for li in venda["linhas"]):
        # A app escolheu uma linha que já não está na conta (foi removida entre
        # a leitura e a escrita). Sem desconto, e a dizê-lo: a funcionária ainda
        # vai a tempo de perceber porque é que o cartão mudou.
        logger.error(
            "[faturacao] voucher ao balcão (venda %s): a app escolheu a linha "
            "%r e ela já não está na conta — a venda segue SEM desconto",
            venda_id, alvo_id)
        # A app reservou o voucher e armou o `/creditar` por uma linha que já não
        # existe: sem o aviso, a FS saía ao preço cheio e o crédito consumia-o.
        await _libertar_na_app(ligacao_id, venda_id)
        return _resposta_do_voucher(
            venda, titulo=titulo, motivo="linha_desapareceu")
    if not voucher_id:
        return _resposta_do_voucher(venda, titulo=titulo, motivo=motivo)
    return _resposta_do_voucher(
        venda, voucher_id=voucher_id, valor=valor, titulo=titulo,
        linha_id_alvo=alvo_id, motivo=motivo)


# --- A fila -------------------------------------------------------------------

# **O «nunca» de `a_enviar_ate`, e não `None`.** No Mongo, `null` não casa com
# `$lt` de uma string — os operadores de comparação só comparam dentro do mesmo
# tipo. Uma linha nascida com `a_enviar_ate: None` nunca era reservada por
# ninguém: ficava pendente para sempre, sem um erro.
_NUNCA = "1970-01-01T00:00:00+00:00"

# Quanto tempo uma linha fica reservada a quem a está a enviar. Muito acima dos
# 4 s do pedido: passado isto, só um processo morto a meio a deixa presa, e a
# volta seguinte do cron pega-lhe.
_RESERVA_SEGUNDOS = 60

# A espera antes da tentativa seguinte, em minutos: 1, 2, 5, 10 e daí em diante
# 30. Ao fim de 24 h **a falhar** (contadas da primeira falha técnica, ver
# `_falhou`), desiste-se (`falhado`).
_ESPERAS_EM_MINUTOS = (1, 2, 5, 10, 30)
_DESISTIR_AO_FIM_DE = timedelta(hours=24)

# `enviado`/`ja_enviado` são a resposta do envio da fatura por email — o segundo
# é a idempotência da app a dizer «esta fatura já saiu». Fora desta lista, um
# `ja_enviado` caía no saco do 5xx: 13 tentativas espalhadas por 24 h de uma
# fatura que o cliente já tinha na caixa de correio.
#
# **`sem_pontos` é o açaí OFERECIDO, e é um desfecho normal.** A app responde-o
# em 200 quando a conta ficou a 0,00 € por causa de um voucher ao balcão: a
# Fatura Simplificada saiu, o voucher foi consumido, e não há euros nenhuns para
# converter em pontos (`routes_pos_integracao.creditar`). Fora desta lista não
# era recusa nem sem efeito — caía no último `return _falhou` de `enviar` como
# falha TÉCNICA: 13 chamadas inúteis à app espalhadas por 24 h e, no fim, estado
# `falhado`. Era o painel do Faturação pintado de vermelho a cada oferta, que é
# exactamente o que a app evitou ao deixar de lhe chamar `sem_valor`. Fecha em
# `feito` com `pontos: 0`, e o detalhe do documento lê «0 pontos para a Ana»,
# que é a verdade.
#
# Verificadas as três rotas que esta fila chama: `/creditar` responde
# `creditado`, `ja_creditado`, `sem_pontos` ou `recusado`; `/estornar`,
# `estornado`, `ja_estornado` ou `sem_efeito`; `/fatura-email`, `enviado` ou
# `ja_enviado`. Não há mais nenhum desfecho normal fora desta lista.
_RESPOSTAS_FEITAS = ("creditado", "ja_creditado", "sem_pontos",
                     "estornado", "ja_estornado", "enviado", "ja_enviado")

# As tentativas imediatas ainda a correr — ver `tentar_ja`.
_EM_CURSO = set()


def _iso(momento: datetime) -> str:
    """Todas as datas da fila no MESMO formato, ao segundo e em UTC: a reserva
    compara-as como texto, e dois formatos diferentes ordenam-se mal."""
    return momento.astimezone(timezone.utc).isoformat(timespec="seconds")


# --- O «por enviar», num sítio só ---------------------------------------------

# Os becos sem saída de uma linha: nenhum destes volta a ser tentado sozinho.
ESTADOS_SEM_SAIDA = ("falhado", "recusado", "sem_efeito")

# **Quando é que um `pendente` deixa de ser «a caminho» e passa a avaria.** O
# cron corre de minuto a minuto e a maior espera entre tentativas técnicas é de
# 30 minutos (`_ESPERAS_EM_MINUTOS`), por isso o caminho normal — emitir,
# enviar, `feito` — nunca chega aqui. Chegam os encalhes, que de outra maneira
# não se dizem em lado nenhum:
#
# - a chave da app por configurar: o `except IntegracaoNaoConfigurada` de
#   `enviar` reagenda de minuto a minuto **para sempre**, sem gastar tentativa e
#   sem carimbar `primeira_falha_tecnica_em` — a linha nunca chega a `falhado`;
# - o cron por instalar: ninguém pega na linha e ela fica `pendente` intacta;
# - a app em baixo há mais de meia hora, antes de as 24 h desistirem.
#
# Em todos eles **não saiu email e não saiu papel** (a decisão do dono é não
# imprimir quando o email foi enfileirado): é exactamente o caso que o alarme da
# loja existe para apanhar, e sem esta janela ele dizia ZERO.
MINUTOS_ATE_O_PENDENTE_ACENDER = 30


def filtro_das_faturas_por_enviar(loja_id: str, agora: datetime) -> Dict:
    """**O predicado do «por enviar» — e vive aqui para viver só num sítio.**

    Responde a «esta loja tem faturas que iam por email e não foram?», e é o
    mesmo filtro para os três consumidores:

    - o ALARME do balcão conta-o (`impressao.estado_da_impressao`);
    - o «Já vi» carimba exactamente o que o alarme contou
      (`impressao.marcar_falhados_vistos`) — carimbar mais do que isso era
      calar uma falha que ainda não aconteceu;
    - o `fatura_email_por_enviar` da lista do POS tem de sair daqui também
      (plano C, Task 4). Um botão e um alarme a contar coisas diferentes são
      duas mentiras: o aviso vermelho sem nenhuma fatura no filtro, ou a
      fatura no filtro sem aviso nenhum.

    `visto_em` não nasce na linha de propósito (`_linha_nova`): a igualdade a
    `None` do Mongo casa com o campo ausente, e só o «Já vi» o escreve."""
    return {
        "loja_id": loja_id,
        "tipo": "fatura_email",
        "visto_em": None,
        "$or": [
            {"estado": {"$in": list(ESTADOS_SEM_SAIDA)}},
            # A janela: ver `MINUTOS_ATE_O_PENDENTE_ACENDER`. É `criado_em` e
            # não `atualizado_em` porque a linha encalhada na configuração
            # reescreve o `atualizado_em` a cada minuto — contra esse campo, a
            # janela nunca fechava e o pior dos encalhes ficava calado.
            {"estado": "pendente", "criado_em": {"$lte": _iso(
                agora - timedelta(minutes=MINUTOS_ATE_O_PENDENTE_ACENDER))}},
        ],
    }


def _linha_nova(tipo: str, chave: str, payload: Dict, agora: datetime, **campos) -> Dict:
    """Uma linha da fila com TODOS os campos presentes desde o nascimento: a
    reserva compara `proxima_tentativa_em` e `a_enviar_ate`, e um campo ausente
    não casa com comparação nenhuma."""
    quando = _iso(agora)
    linha = {
        "id": str(uuid.uuid4()),
        "chave": chave,
        "tipo": tipo,
        "documento_id": None,
        "nc_documento_id": None,
        "venda_id": None,
        # Para o backoffice dizer «17 pontos para Ana» sem perguntar à app.
        "primeiro_nome": None,
        "payload": payload,
        "estado": "pendente",
        "pontos": None,
        "motivo": None,
        "tentativas": 0,
        "ultimo_erro": None,
        "criado_em": quando,
        "atualizado_em": quando,
        "proxima_tentativa_em": quando,
        "a_enviar_ate": _NUNCA,
        # **O relógio das 24 h, e é ESTE e não `criado_em`.** Carimba-se na
        # primeira falha TÉCNICA (a app a responder mal, a rede em baixo) e
        # nunca mais se mexe. Contado desde o nascimento, uma linha que esperou
        # legitimamente — integração por configurar, crontab por instalar —
        # desistia na primeira falha real depois de a chave chegar, com a app
        # em baixo 4 segundos, e os pontos daquela compra perdiam-se.
        "primeira_falha_tecnica_em": None,
    }
    linha.update(campos)
    return linha


async def _enfileirar(db, linha: Dict) -> bool:
    """Insere a linha e manda-a já, em segundo plano. Devolve `False` se a
    chave já lá estava.

    `DuplicateKeyError` engole-se e não é erro nenhum: o gancho da emissão
    (`fiscal._ligar_venda_ao_documento`) corre mais do que uma vez por venda —
    o retry que reencontra o documento, a reconciliação de uma reserva presa —
    e a segunda passagem é a defesa a funcionar."""
    try:
        await db[COLECOES["pontos_app"]].insert_one(dict(linha))
    except DuplicateKeyError:
        return False
    tentar_ja(db, linha["id"])
    return True


def tentar_ja(db, linha_id: str) -> None:
    """A tentativa imediata, em SEGUNDO PLANO: agenda o envio e volta logo.

    Quem chama está dentro do EMITIR, com a fatura já na AT e a funcionária à
    espera da resposta. Esperar aqui pela app eram até 4 s de balcão parado por
    causa de pontos — e se a app estiver em baixo a linha fica pendente e o
    cron de 1 em 1 minuto pega-lhe. Com dois workers, o outro processo e o cron
    não a enviam ao mesmo tempo: a reserva de `enviar` decide.

    A tarefa fica em `_EM_CURSO` até acabar: o asyncio só guarda uma referência
    FRACA às tarefas, e uma tarefa que ninguém segura pode ser recolhida a
    meio."""
    tarefa = asyncio.get_running_loop().create_task(_tentar_em_silencio(db, linha_id))
    _EM_CURSO.add(tarefa)
    tarefa.add_done_callback(_EM_CURSO.discard)


async def _tentar_em_silencio(db, linha_id: str) -> None:
    try:
        await enviar(db, linha_id)
    except Exception as e:  # noqa: BLE001 — em segundo plano não há a quem devolver o erro
        logger.error(
            "[faturacao] envio imediato da linha de pontos %s falhou (o cron repete): %s",
            linha_id, e)


async def enviar(db, linha_id: Optional[str] = None, *, agora: Optional[datetime] = None) -> Optional[Dict]:
    """Reserva UMA linha pendente e vencida (esta, se vier `linha_id`), manda-a
    à app e grava o desfecho. Devolve a linha como ficou, ou `None` se não
    havia nada para reservar.

    **A reserva é a primeira escrita, e é condicional.** Dois workers do
    uvicorn e o cron podem pegar na mesma linha no mesmo segundo; o
    `find_one_and_update` com `a_enviar_ate < agora` deixa passar exactamente
    um. A app é idempotente de qualquer forma — a reserva é para não a
    incomodar duas vezes e para duas respostas não se escreverem por cima.

    **Um estorno só sai com o crédito `feito`.** Com o crédito ainda pendente
    espera (sem gastar tentativas: não é uma falha); com o crédito recusado ou
    falhado não há pontos a tirar e fica `sem_efeito` sem falar com a app."""
    agora = agora or datetime.now(timezone.utc)
    filtro = {
        "estado": "pendente",
        "proxima_tentativa_em": {"$lte": _iso(agora)},
        "a_enviar_ate": {"$lt": _iso(agora)},
    }
    if linha_id is not None:
        filtro["id"] = linha_id
    reserva = _iso(agora + timedelta(seconds=_RESERVA_SEGUNDOS))
    linha = await db[COLECOES["pontos_app"]].find_one_and_update(
        filtro, {"$set": {"a_enviar_ate": reserva}},
        projection={"_id": 0}, return_document=ReturnDocument.AFTER)
    if linha is None:
        return None

    if linha["tipo"] == "estorno":
        credito = await db[COLECOES["pontos_app"]].find_one(
            {"chave": "credito:%s" % linha["documento_id"]}, {"_id": 0, "estado": 1})
        estado_do_credito = (credito or {}).get("estado")
        if estado_do_credito == "pendente":
            return await _fechar(db, linha, reserva, agora, {
                "proxima_tentativa_em": _iso(agora + timedelta(minutes=1)),
                "ultimo_erro": "à espera do crédito da fatura",
            })
        if estado_do_credito != "feito":
            return await _fechar(db, linha, reserva, agora, {
                "estado": "sem_efeito",
                "motivo": "credito_%s" % (estado_do_credito or "inexistente"),
            })

    # **`.get` e nunca `[...]`.** Um `KeyError` aqui levantava-se DEPOIS de a
    # reserva estar feita e subia por `cron_pontos_app`, que não tem `try`
    # nenhum: a volta do cron respondia 500 e morria, parando os pontos e os
    # emails de todas as lojas em silêncio, de minuto a minuto. É a avaria que
    # o comentário logo abaixo (o `except Exception` da rede) existe para
    # impedir, e o ternário de antes nunca a podia provocar.
    acao = _ACCAO_DO_TIPO.get(linha["tipo"])
    if acao is None:
        logger.error(
            "[faturacao] pontos da app: a linha %s (%s) tem um tipo que este "
            "servidor não conhece (%r) — fica sem efeito e a volta do cron "
            "continua", linha["id"], linha["chave"], linha["tipo"])
        return await _fechar(db, linha, reserva, agora, {
            "estado": "sem_efeito", "motivo": "tipo_desconhecido"})
    corpo_do_pedido = linha["payload"]
    if linha["tipo"] == "fatura_email":
        # **Sem PDF não se chama a app.** Mandá-la enviar um email sem anexo era
        # entregar ao cliente uma fatura que não é fatura nenhuma. É falha
        # TÉCNICA (o Vendus pode estar em baixo, a conta por configurar) e por
        # isso a fila repete — com a espera crescente e as 24 h de sempre.
        try:
            pdf = await _pdf_da_fatura(linha["payload"])
        except Exception as e:  # noqa: BLE001 — o que vier do Vendus é técnico
            return await _falhou(db, linha, reserva, agora,
                                 "PDF do Vendus: %s %s" % (type(e).__name__, e))
        if not pdf:
            return await _falhou(db, linha, reserva, agora,
                                 "o Vendus não devolveu PDF nenhum")
        # O corpo é construído campo a campo e não é o payload com mais uma
        # chave: o `vendus_document_id` e o `modo` são nossos, servem para ir
        # buscar o PDF, e a app não tem nada que os receber.
        corpo_do_pedido = {
            "ligacao_id": linha["payload"]["ligacao_id"],
            "documento_id": linha["payload"]["documento_id"],
            "numero": linha["payload"].get("numero") or "",
            "pdf_base64": base64.b64encode(pdf).decode(),
        }
        # **O `forcar`, e SÓ quando ele lá está.** A app deduplica por
        # `documento_id` sem validade nenhuma: sem este campo, a segunda vez
        # que a mesma fatura lhe bate à porta responde `ja_enviado` **sem
        # mandar email nenhum** — e `ja_enviado` está em `_RESPOSTAS_FEITAS`,
        # por isso a linha fechava em `feito` e o gestor lia sucesso por cima
        # de nada. É exactamente o caso do botão «Reenviar»: o cliente liga a
        # dizer que não recebeu, a linha já está em `feito`.
        #
        # **Quem o põe é só a rota `reenviar-email`**, no payload da linha (e
        # fica lá, para as repetições desta reposição o levarem também). A fila
        # normal — o `tentar_ja` da emissão e o cron — nunca o manda: o
        # `.get` devolve `None` e a chave nem aparece no corpo. Uma app velha
        # que o receba tem de o ignorar (o contrato proíbe `extra="forbid"` do
        # lado dela), e um POS velho que não o mande continua como sempre.
        if linha["payload"].get("forcar"):
            corpo_do_pedido["forcar"] = True
    try:
        resposta = await _chamar_app(acao, corpo_do_pedido)
    except IntegracaoNaoConfigurada:
        # «Não se perde nada»: sem configuração a linha ESPERA — não falhou.
        # O molde é o do estorno à espera do crédito, aqui em cima: não gasta
        # tentativa (senão a primeira tentativa a sério só acontecia 30 min
        # depois de a chave chegar) e não carimba `primeira_falha_tecnica_em`,
        # por isso as 24 h nem sequer arrancaram. As 24 h são para a app em
        # baixo, não para um servidor por acabar de instalar.
        return await _fechar(db, linha, reserva, agora, {
            "proxima_tentativa_em": _iso(agora + timedelta(minutes=1)),
            "ultimo_erro": "integração não configurada",
        })
    # Tudo o resto que venha de `_chamar_app` é falha TÉCNICA — e `Exception` e
    # não `httpx.HTTPError` porque `httpx.InvalidURL` (a porta do
    # `APP_LACAI_URL` mal escrita) não é `HTTPError`. Escapando daqui, a linha
    # ficava presa com a reserva já feita e desfecho nenhum gravado — pendente
    # com 0 tentativas e sem relógio das 24 h — e a volta do cron morria nela,
    # parando os pontos de todas as lojas em silêncio.
    except Exception as e:  # noqa: BLE001
        return await _falhou(db, linha, reserva, agora, "rede: %s %s" % (type(e).__name__, e))

    corpo = _json_ou_nada(resposta) if resposta.status_code == 200 else None
    estado_da_app = corpo.get("estado") if isinstance(corpo, dict) else None
    if estado_da_app in _RESPOSTAS_FEITAS:
        return await _fechar(db, linha, reserva, agora,
                             {"estado": "feito", "pontos": corpo.get("pontos")})
    if estado_da_app == "recusado":
        # Uma recusa de negócio (plataforma, acima do teto, ligação já usada…)
        # não muda por se repetir — e repeti-la era bater à porta da app de 30
        # em 30 minutos durante um dia inteiro.
        return await _fechar(db, linha, reserva, agora,
                             {"estado": "recusado", "motivo": corpo.get("motivo")})
    if estado_da_app == "sem_efeito":
        return await _fechar(db, linha, reserva, agora, {"estado": "sem_efeito"})
    # **As recusas da PORTA da app também não mudam por se repetirem.** Um 422
    # é o corpo recusado pelo validador (`CreditarReq`) e nunca vai passar a
    # 200; no saco do 5xx eram 13 tentativas espalhadas por 24 h e, no fim, a
    # frase «Falhou ao fim de 24 h» — a de uma app em baixo, não a de um
    # contrato partido. O gestor vê o problema em minutos e a app deixa de
    # levar pedidos que já se sabe que vai recusar.
    #
    # O 404 fica DE FORA de propósito: é a rota por deployar (o RH a subir
    # antes da app) e essa passa sozinha. O 401 também — chaves trocadas
    # arranjam-se no `.env` sem reemitir nada.
    if resposta.status_code in (400, 413, 422):
        return await _fechar(db, linha, reserva, agora, {
            "estado": "recusado", "motivo": "contrato_recusado",
            "ultimo_erro": "HTTP %s: %s" % (resposta.status_code, resposta.text[:200]),
        })
    # 401 (chaves trocadas), 5xx, ou um 200 que não diz nada do contrato.
    return await _falhou(db, linha, reserva, agora,
                         "HTTP %s: %s" % (resposta.status_code, resposta.text[:200]))


async def _falhou(db, linha: Dict, reserva: str, agora: datetime, erro: str) -> Dict:
    """Uma falha TÉCNICA: conta a tentativa, afasta a seguinte e, ao fim de 24 h
    **a falhar**, desiste.

    O relógio conta de `primeira_falha_tecnica_em` e não de `criado_em`: uma
    linha que esperou pela configuração (ver o `except IntegracaoNaoConfigurada`
    de `enviar`) não pode desistir na primeira falha real, e é isso que
    `criado_em` fazia — a app em baixo 4 segundos e os pontos perdidos."""
    tentativas = int(linha.get("tentativas") or 0) + 1
    espera = _ESPERAS_EM_MINUTOS[min(tentativas, len(_ESPERAS_EM_MINUTOS)) - 1]
    primeira = linha.get("primeira_falha_tecnica_em") or _iso(agora)
    campos = {
        "tentativas": tentativas,
        "ultimo_erro": erro[:300],
        "proxima_tentativa_em": _iso(agora + timedelta(minutes=espera)),
        # Escrito sempre com o valor que já lá estava (ou o de agora, na
        # primeira): carimba uma vez e fica — recarimbá-lo a cada falha adiava
        # as 24 h para sempre.
        "primeira_falha_tecnica_em": primeira,
    }
    if agora - datetime.fromisoformat(primeira) >= _DESISTIR_AO_FIM_DE:
        campos["estado"] = "falhado"
    logger.warning(
        "[faturacao] pontos da app: a linha %s (%s) não chegou à app (tentativa %d): %s",
        linha["id"], linha["chave"], tentativas, erro)
    return await _fechar(db, linha, reserva, agora, campos)


async def _fechar(db, linha: Dict, reserva: str, agora: datetime, campos: Dict) -> Dict:
    """Grava o desfecho e larga a reserva — só se a reserva ainda for ESTA. Se
    o envio demorou mais do que `_RESERVA_SEGUNDOS` e outro processo pegou na
    linha entretanto, é a escrita dele que vale.

    **Uma linha que ACABA em beco sem saída volta a acender o alarme.** O «Já
    vi» do balcão (`impressao.marcar_falhados_vistos`) carimba tudo o que o
    alarme contou — e o predicado conta os `pendente` com mais de
    `MINUTOS_ATE_O_PENDENTE_ACENDER`, que ainda estão a ser tentados. Carimbado
    esse, a linha saía do alarme E do filtro «Por enviar» PARA SEMPRE: se o
    envio viesse depois a falhar de vez, o balcão nunca mais o sabia — e é o
    caso em que não há papel nenhum a compensar o email que não saiu. Tirar o
    carimbo aqui é dizer «isto é NOVO»: o que o toque de ontem calou foi um
    envio a caminho, não esta falha.

    Só nos becos sem saída (`ESTADOS_SEM_SAIDA`), e não a cada tentativa
    falhada: um `pendente` a repetir continua a ser o que a pessoa deu por
    visto, e reacender a cada volta do cron era o aviso que se aprende a
    ignorar."""
    campos = dict(campos, a_enviar_ate=_NUNCA, atualizado_em=_iso(agora))
    if campos.get("estado") in ESTADOS_SEM_SAIDA:
        campos["visto_em"] = None
    await db[COLECOES["pontos_app"]].update_one(
        {"id": linha["id"], "a_enviar_ate": reserva}, {"$set": campos})
    linha.update(campos)
    return linha


# **O tipo da linha → a rota da app, por MAPA e não por ternário.** O ternário
# que aqui estava (`"creditar" if tipo == "credito" else "estornar"`) mandava
# qualquer tipo NOVO para `/estornar`: a app recebia um corpo que não conhece,
# respondia 422, e a linha fechava `recusado` sem ninguém perceber que o envio
# nunca tinha sido tentado.
_ACCAO_DO_TIPO = {
    "credito": "creditar",
    "estorno": "estornar",
    "fatura_email": "fatura-email",
}


async def _pdf_da_fatura(payload: Dict) -> bytes:
    """O PDF **certificado** desta fatura, ido buscar ao Vendus. `b""` quando
    não há por onde o ir buscar.

    **Não é um PDF nosso, e é de propósito**: o documento fiscal é o do Vendus,
    com o ATCUD, o hash e o QR que a Autoridade Tributária conhece. É a mesma
    ida buscar que o botão «PDF da fatura» do backoffice já faz
    (`documentos.pdf_do_documento`).

    **O `mode` é o DO DOCUMENTO** e vem gravado no payload da linha, nunca o
    modo em que a loja está hoje: um documento emitido em `tests` pedido com
    `mode=normal` responde 404 — o Vendus guarda os dois mundos separados
    (medido ao vivo na conta real, ver `ClienteVendus.pdf_do_documento`). Um
    botão que mude o modo da loja não pode partir o reenvio de faturas antigas.

    Numa thread porque o cliente do Vendus é síncrono e a fila corre no event
    loop — o mesmo `asyncio.to_thread` da emissão e do botão do backoffice."""
    vendus_id = payload.get("vendus_document_id")
    if not vendus_id:
        return b""
    conta = obter_conta()
    if conta is None:
        return b""
    with ClienteVendus(conta.chave) as cliente:
        return await asyncio.to_thread(
            cliente.pdf_do_documento, vendus_id, payload.get("modo") or "normal")


# --- O crédito, na emissão ------------------------------------------------------


async def enfileirar_credito(db, venda_id: str, documento: Dict, *,
                             agora: Optional[datetime] = None) -> None:
    """Põe na fila o crédito desta Fatura Simplificada, se a venda tiver um
    cliente ligado. Chamado no fim de `fiscal._ligar_venda_ao_documento`.

    - **Só o modo `normal`.** Uma fatura em `tests` não existe na AT, e
      creditar pontos por ela era dar pontos por nada.
    - **A ligação lê-se da VENDA gravada**, não do pedido: é a venda que chega
      aos cinco caminhos da emissão, a reconciliação incluída.
    - **O corpo é o contrato de `/api/pos-integracao/creditar`**, e fica
      gravado na linha: os reenvios mandam exactamente o mesmo, dias depois
      se for preciso, sem voltar a ler a venda.

    Os meios de pagamento vão pelo id do VENDUS — é por eles, e só por eles,
    que a app recusa Uber Eats, Glovo e Bolt — e saem do RETRATO gravado na
    venda (`fiscal.finalizar`), que é o que valia no dia. A releitura de
    `fat_tipos_pagamento` é só o recuo para as vendas de antes desse campo
    existir; um pagamento que não dê id nenhum fica de fora da lista, mas
    NUNCA em silêncio (é assim que a recusa por plataforma falharia aberta).
    A caução vai à parte (`deposito`, carimbado no documento pela emissão): os
    pontos contam sobre o total sem ela. O operador é o dono da CONTA
    (`operador_id` da venda), o mesmo que o backoffice mostra no documento."""
    if documento.get("modo") != "normal":
        return
    venda = await db[COLECOES["vendas"]].find_one({"id": venda_id})
    ligacao = (venda or {}).get("pontos_ligacao")
    if not ligacao:
        return
    # **Sem ATCUD não há linha nenhuma a fazer.** Um documento REAL pode não o
    # ter: o Vendus só é recusado quando faltam o `id` E o `atcud`
    # (`vendus/emissao._documento_da_criacao`), por isso um 2xx com `id` e sem
    # ATCUD é aceite de propósito e gravado com `atcud: None`. A app exige-o
    # (`CreditarReq.atcud`, `min_length=1`) e é por ele que deduplica — enfileirar
    # assim eram 24 h de 422 e os pontos perdidos na mesma. Mas nunca em
    # silêncio: é o único rasto de que aquele cliente mostrou a app e não
    # recebeu nada.
    atcud = documento.get("atcud")
    if not atcud:
        logger.error(
            "[faturacao] pontos da app: o documento %s da venda %s não tem ATCUD — "
            "o crédito NÃO entra na fila (a app precisa dele para deduplicar) e o "
            "cliente que mostrou a app fica sem pontos", documento["id"], venda_id)
        return
    meios = []
    for pagamento in venda.get("pagamentos") or []:
        identificador = pagamento.get("vendus_payment_method_id")
        if not identificador:
            tipo = await db[COLECOES["tipos_pagamento"]].find_one(
                {"id": pagamento.get("tipo_pagamento_id")},
                {"_id": 0, "vendus_payment_method_id": 1})
            identificador = (tipo or {}).get("vendus_payment_method_id")
        if identificador:
            meios.append(str(identificador))
        else:
            # Uma lista mais curta do que os pagamentos é a recusa por
            # plataforma a falhar ABERTA — a app não tem como saber que aquele
            # pagamento foi Glovo. Não se adivinha nada, mas fica escrito: é o
            # único sítio onde alguém pode vir a perceber porque é que aquela
            # fatura deu pontos.
            logger.error(
                "[faturacao] pontos da app: o pagamento %r da venda %s (documento "
                "%s) não tem id do Vendus — `meios_pagamento` vai mais curto e a "
                "app não consegue recusar uma plataforma por ele",
                pagamento.get("tipo_pagamento_id"), venda_id, documento["id"])
    loja = await db[COLECOES["lojas"]].find_one(
        {"id": venda.get("loja_id")}, {"_id": 0, "nome": 1})
    operador = await db[COLECOES["utilizadores"]].find_one(
        {"id": venda.get("operador_id")}, {"_id": 0, "nome": 1})
    payload = {
        "ligacao_id": ligacao.get("id"),
        "documento_id": documento["id"],
        "atcud": atcud,
        # `or ""` e não o `.get` cru: os campos de texto da app têm default
        # vazio, mas em pydantic 2 um `None` explícito NÃO cai no default de um
        # `str` — rebenta com 422. O número é só o histórico do cliente e não
        # vale perder os pontos por ele faltar.
        "numero": documento.get("numero") or "",
        "emitido_em": documento.get("emitido_em"),
        "total": round(float(documento.get("total") or 0), 2),
        "caucao": round(float(documento.get("deposito") or 0), 2),
        "meios_pagamento": meios,
        "loja_nome": (loja or {}).get("nome") or "",
        "operador_nome": (operador or {}).get("nome") or "",
    }
    await _enfileirar(db, _linha_nova(
        "credito", "credito:%s" % documento["id"], payload,
        agora or datetime.now(timezone.utc),
        documento_id=documento["id"], venda_id=venda_id,
        primeiro_nome=ligacao.get("primeiro_nome")))


# --- A fatura por email, na emissão ---------------------------------------------


async def enfileirar_fatura_email(db, venda: Dict, documento: Dict, *,
                                  agora: Optional[datetime] = None) -> bool:
    """Põe na fila o envio por email desta Fatura Simplificada. **Devolve `True`
    só quando, no fim, existe mesmo a linha `fatura_email:<documento_id>`** — e
    é por esse `True` que `fiscal.finalizar` decide não pôr papel na fila.

    As duas decisões são UMA: o papel só se salta se o email foi mesmo
    enfileirado. Nunca há desfecho em que não saia papel nem email.

    Devolve `False` — e o talão sai como sempre — quando:

    - `documento["modo"] != "normal"`: uma fatura em `tests` não existe na AT, e
      o Vendus nem devolve PDF dela pela porta normal;
    - `documento["vendus_document_id"]` está vazio: **sem o id do Vendus não há
      PDF para ir buscar**, hoje nem daqui a um mês. O Vendus só é recusado
      quando faltam o `id` E o `atcud` (`vendus/emissao._documento_da_criacao`),
      por isso um 2xx com ATCUD e sem `id` é aceite de propósito e gravado com
      `vendus_document_id: None` — é o caso que `documentos.pdf_do_documento`
      traduz num 422 dedicado. Saltar o papel aqui era 13 tentativas de um PDF
      que nunca vem e o cliente sem talão E sem email;
    - a venda não tem `pontos_ligacao`: sem QR não há para onde enviar;
    - não há linha em `fat_pontos_qr` para aquela ligação, ou ela diz `False`:
      **é essa linha, do servidor, que decide**. Um `pontos_ligacao` forjado no
      corpo do EMITIR não pode fazer desaparecer o documento de ninguém;
    - a escrita falhou por qualquer razão.

    **O NIF não está nesta lista, e é de propósito.** O seletor do cliente é o
    único que manda: com a preferência ligada a fatura vai por email haja ou não
    haja NIF, e o NIF vai escrito nela como sempre foi (a emissão copia-o da
    venda para o documento, `fiscal.py:1266`). Quem mostra a app e quem pede a
    fatura são a mesma pessoa; num grupo, quando querem faturas separadas,
    dividem a conta e cada parte leva o seu QR e o seu NIF. O caso em que uma
    pessoa mostra a app e outra pede a fatura com o NIF dela, sem dividirem a
    conta, é risco assumido pelo dono: essa fatura vai para o email de quem
    mostrou a app, e recupera-se reimprimindo no separador Faturação.

    **Um `DuplicateKeyError` conta como `True`.** A linha já lá estava — o
    gancho da emissão corre mais do que uma vez por venda — e devolver `False`
    aí fazia sair papel numa fatura que já ia por email.

    **Não herda a guarda do ATCUD do `enfileirar_credito`**: um documento REAL
    pode não o ter, a app precisa dele para deduplicar os PONTOS, e o email
    precisa é do id do VENDUS (acima). Herdá-la era o caso em que não sai papel
    nem email e não fica linha nenhuma para alguém ver.

    A venda vem de quem chama e é a GRAVADA (`fiscal.py:2271`), nunca o corpo do
    pedido: quem perde a corrida da reserva também chega àquela linha, e só a
    venda gravada tem a verdade.

    **O PDF não entra na linha**, só o id do documento e o modo com que ele foi
    emitido: a fila não tem TTL e fica para sempre, e 92 KB por fatura para
    sempre não. Quem o vai buscar é o envio (`_pdf_da_fatura`)."""
    if documento.get("modo") != "normal":
        return False
    if not documento.get("vendus_document_id"):
        logger.error(
            "[faturacao] a fatura %s não tem id do Vendus — sem ele não há PDF "
            "para enviar, e o talão sai em PAPEL como sempre", documento["id"])
        return False
    ligacao = (venda or {}).get("pontos_ligacao") or {}
    if not ligacao.get("id"):
        return False
    # **Nenhuma guarda ao `cliente_nif`**, e é a decisão do dono: o seletor do
    # cliente é o único que manda, e uma fatura com NIF vai por email como
    # qualquer outra — com o NIF escrito nela (`fiscal.py:1266`).

    linha = _linha_nova(
        "fatura_email", "fatura_email:%s" % documento["id"],
        {
            "ligacao_id": str(ligacao["id"]),
            "documento_id": documento["id"],
            # Nosso e não da app: é por ele que se pede o PDF ao Vendus.
            "vendus_document_id": documento.get("vendus_document_id"),
            # `or ""` e não o `.get` cru, pela razão do crédito: em pydantic 2
            # um `None` explícito NÃO cai no default de um `str`.
            "numero": documento.get("numero") or "",
            # **O modo DO DOCUMENTO**, carimbado agora: um documento emitido em
            # `tests` pedido com `mode=normal` responde 404, e o botão que muda
            # o modo da loja não pode partir o reenvio de faturas antigas.
            "modo": documento.get("modo") or "normal",
        },
        agora or datetime.now(timezone.utc),
        documento_id=documento["id"], venda_id=venda.get("id"),
        # **A loja vai na linha**, e é por ela que o alarme do POS conta os
        # envios sem saída (`impressao.estado_da_impressao`).
        loja_id=venda.get("loja_id"),
        primeiro_nome=ligacao.get("primeiro_nome"))

    # A leitura do QR e a escrita da linha DENTRO do mesmo `try`: se a leitura
    # rebentasse cá fora, o `except` da rota do finalizar engolia-a e não saía
    # papel NEM email — o único desfecho que este desenho não admite.
    try:
        marca = await db[COLECOES["pontos_qr"]].find_one(
            {"ligacao_id": str(ligacao["id"])}, {"_id": 0, "fatura_por_email": 1})
        if not (marca or {}).get("fatura_por_email"):
            return False
        await db[COLECOES["pontos_app"]].insert_one(dict(linha))
    except DuplicateKeyError:
        return True
    except Exception as e:  # noqa: BLE001 — sem linha, o papel sai
        logger.error(
            "[faturacao] a fatura %s não entrou na fila do email (o talão sai em "
            "papel): %s", documento["id"], e)
        return False
    tentar_ja(db, linha["id"])
    return True


# --- O estorno, na nota de crédito ----------------------------------------------


async def enfileirar_estorno(db, nota: Dict, documento_nc: Dict, *,
                             agora: Optional[datetime] = None) -> None:
    """Põe na fila o estorno desta nota de crédito, se a fatura de origem tiver
    uma linha de crédito. Chamado em `nota_credito.emitir_nota_credito`, logo a
    seguir à marca `emitida`.

    Não interessa aqui se o crédito já chegou à app: a linha entra na mesma, e
    é o ENVIO que espera por ele (ou a fecha `sem_efeito` se ele nunca entrar).

    **A caução da nota são as linhas `NS`.** O depósito de embalagem é a única
    coisa deste POS fora do imposto (`precos.CODIGO_NAO_SUJEITO`), e a nota
    credita-o como qualquer outra linha da fatura. Os pontos contam sem ela,
    por isso a app precisa de a saber para tirar a proporção certa. Somada em
    cêntimos inteiros, como todo o dinheiro deste módulo."""
    if documento_nc.get("modo") != "normal":
        return
    credito = await db[COLECOES["pontos_app"]].find_one(
        {"chave": "credito:%s" % nota["documento_id"]}, {"_id": 0})
    if not credito:
        return
    caucao_em_centimos = sum(
        round(float(linha.get("total") or 0) * 100)
        for linha in nota.get("linhas") or []
        if linha.get("tax_id") == CODIGO_NAO_SUJEITO
    )
    payload = {
        "atcud_origem": credito["payload"]["atcud"],
        "nc_id": documento_nc["id"],
        # `or ""` pela razão do crédito: um `None` explícito é 422 na app. O
        # `atcud_origem` fica protegido por arrasto — sem ATCUD não chegou a
        # existir linha de crédito, e sem ela não se enfileira estorno nenhum.
        "numero_nc": documento_nc.get("numero") or "",
        "valor_nc": round(float(nota.get("total") or 0), 2),
        "caucao_nc": caucao_em_centimos / 100.0,
    }
    await _enfileirar(db, _linha_nova(
        "estorno", "estorno:%s" % documento_nc["id"], payload,
        agora or datetime.now(timezone.utc),
        documento_id=nota["documento_id"], nc_documento_id=documento_nc["id"],
        venda_id=nota.get("venda_id"), primeiro_nome=credito.get("primeiro_nome")))


# --- A volta do cron -------------------------------------------------------------

# O tecto de linhas por volta. Com a app em baixo, cada linha pode gastar os 4 s
# do pedido: 50 são 200 s no pior caso, e duas voltas sobrepostas não se pisam
# (a reserva decide). Num dia normal a volta encontra zero ou uma.
_LIMITE_POR_VOLTA = 50


@router.post("/cron/pontos-app")
async def cron_pontos_app(key: str = Query(...)) -> dict:
    """A porta de 1 em 1 minuto (`faturacao-pontos-cron.sh`). Protegida pela
    `CRON_KEY`, sem JWT — o mesmo padrão de `/cron/sincronizar-app`: sem a
    variável no ambiente ninguém entra, e `compare_digest` para o tempo da
    comparação não dizer quantos caracteres estavam certos.

    Envia uma a uma as linhas pendentes que já chegaram à hora e pára quando
    não houver mais nenhuma — uma linha que falha fica com a próxima tentativa
    no futuro, por isso a mesma volta não lhe volta a pegar."""
    chave = os.environ.get("CRON_KEY")
    if not chave or not secrets.compare_digest(str(key), str(chave)):
        raise HTTPException(status_code=403, detail="Acesso negado.")
    db = obter_db()
    enviadas = 0
    for _ in range(_LIMITE_POR_VOLTA):
        if await enviar(db) is None:
            break
        enviadas += 1
    return {"enviadas": enviadas}


# --- O backoffice ---------------------------------------------------------------


# Só os campos que o ecrã escreve («17 pontos para Ana», «A tentar enviar (3
# tentativas — último erro: …)», «Recusado: pagamento por plataforma»). O corpo
# enviado à app fica de fora: tem a ligação do cliente, e o ecrã não precisa
# dela para nada.
_CAMPOS_PARA_O_ECRA = (
    "tipo", "estado", "pontos", "primeiro_nome", "motivo",
    "tentativas", "ultimo_erro", "atualizado_em")


async def _linha_para_o_ecra(db, chave: str) -> Optional[Dict]:
    linha = await db[COLECOES["pontos_app"]].find_one({"chave": chave}, {"_id": 0})
    if not linha:
        return None
    return {campo: linha.get(campo) for campo in _CAMPOS_PARA_O_ECRA}


async def pontos_app_do_documento(db, documento: Dict) -> Dict:
    """As duas linhas da fila que o detalhe de um documento no backoffice
    mostra: `pontos` (numa fatura o crédito, numa nota de crédito o estorno
    DELA) e `fatura_email` (o envio da fatura por email). Cada uma `None` quando
    não existe — o cliente não mostrou a app, ou levou talão.

    **Duas e não uma, porque nem sempre andam juntas.** Um documento REAL sem
    ATCUD não chega a ter linha de crédito (`enfileirar_credito` desiste, a app
    deduplica os pontos por ele) e tem linha de email à mesma — o envio não
    herda essa guarda. Procurar só por `credito:<id>` deixava esse envio
    invisível para toda a gente, e é exactamente a fatura em que alguém precisa
    de o ver."""
    tipo = "estorno" if documento.get("tipo") == "NC" else "credito"
    return {
        "pontos": await _linha_para_o_ecra(db, "%s:%s" % (tipo, documento.get("id"))),
        # Uma nota de crédito nunca tem linha de email (as notas saem sempre em
        # papel — a devolução é o momento em que o cliente está chateado), e a
        # chave `fatura_email:<nc-id>` não existe: dá `None` por si só.
        "fatura_email": await _linha_para_o_ecra(
            db, "fatura_email:%s" % documento.get("id")),
    }


_MSG_SEM_LINHA_DE_EMAIL = (
    "Esta fatura não tem envio por email — o cliente não mostrou a app na caixa, "
    "ou pediu o talão. O documento fiscal continua bom e reimprime-se na loja."
)


@router.post("/documentos/{documento_id}/reenviar-email")
async def reenviar_fatura_por_email(
    documento_id: str, _: dict = Depends(gestor_atual)
) -> dict:
    """«Reenviar» — a fatura volta à fila do email. **Para QUALQUER documento
    com linha, não só para os falhados.**

    O caso frequente não é o da linha vermelha: é «não me chegou» com a linha em
    `feito`. «Enviado» aqui quer dizer «o Resend aceitou», não «entregou» — uma
    caixa cheia, um relay com o reencaminhamento desligado, a pasta do spam.
    Deixar este botão só para as falhadas era não ter botão nenhum para o
    problema que as pessoas trazem.

    **Repõe NOVE campos numa escrita, e só depois manda.** Repor só o estado é
    um botão que dá uma tentativa e volta logo a `falhado`:

    - `tentativas` a 0, senão a espera seguinte começa já nos 30 minutos;
    - `primeira_falha_tecnica_em` a `None`, senão o relógio das 24 h vinha de
      ontem e a primeira falha a seguir ao toque desistia na hora;
    - `proxima_tentativa_em` a agora, senão a linha ficava à espera da hora que
      a última falha lhe marcou;
    - `a_enviar_ate` ao `_NUNCA`, senão uma reserva presa de um processo morto
      fazia o `find_one_and_update` de `enviar` nunca mais lhe pegar;
    - `estado` a `pendente`, que é o que o cron procura;
    - `ultimo_erro` e `motivo` a `None`, porque são o que o detalhe do documento
      ESCREVE no ecrã (`_CAMPOS_PARA_O_ECRA`): deixados lá, o gestor lia «A
      tentar enviar (0 tentativas — último erro: HTTP 503: em baixo)» ou
      «Recusado: contrato_recusado» sobre uma linha acabada de repor;
    - `visto_em` a `None`, senão a linha renasce INVISÍVEL. O «Já vi» do balcão
      (`impressao.marcar_falhados_vistos`) carimba este campo, e é ele que o
      predicado do «por enviar» exige a `None`
      (`filtro_das_faturas_por_enviar`) — o MESMO predicado do alarme da loja e
      do filtro «Por enviar» do separador Faturação. Uma linha reposta a
      `pendente` com `tentativas: 0` é, por definição, «outra vez a caminho»:
      se voltar a falhar tem de acender como qualquer outra, e com o carimbo
      antigo o alarme dizia zero, o botão dizia (0) e a lista dizia «Nenhuma
      fatura desta loja está à espera»;
    - `payload.forcar` a `True` — **e é ele que faz o botão reenviar mesmo.** A
      chave de idempotência da app é o `documento_id` e não tem validade: sem
      este campo, o `tentar_ja` aqui em baixo manda exactamente o mesmo corpo
      de antes, a app responde `ja_enviado` **sem mandar email nenhum**, e como
      `ja_enviado` está em `_RESPOSTAS_FEITAS` a linha fecha outra vez em
      `feito` — o ecrã dizia «sai no minuto seguinte», um minuto depois dizia
      «Enviada», e não tinha saído nada. Fica no PAYLOAD (e não só no corpo
      desta tentativa) para as repetições desta reposição o levarem também, se
      a primeira falhar. Ver o corpo do `fatura_email` em `enviar`.

    Uma escrita condicional só no fim (`find_one_and_update`) e não uma leitura
    seguida de um `update`: duas pessoas a carregar no botão ao mesmo tempo
    escrevem a mesma coisa, e a resposta traz a linha como ficou.

    **Não cria linha nenhuma.** Uma fatura sem envio por email é uma fatura sem
    QR lido: não há endereço para onde mandar, e inventar um destinatário era
    mandar o documento de um cliente para a conta de outro. O que essa fatura
    tem é o «Imprimir» do separador Faturação."""
    db = obter_db()
    agora = datetime.now(timezone.utc)
    linha = await db[COLECOES["pontos_app"]].find_one_and_update(
        {"chave": "fatura_email:%s" % documento_id},
        {"$set": {
            "estado": "pendente",
            "tentativas": 0,
            "primeira_falha_tecnica_em": None,
            "proxima_tentativa_em": _iso(agora),
            "a_enviar_ate": _NUNCA,
            "ultimo_erro": None,
            "motivo": None,
            "visto_em": None,
            # O caminho com ponto escreve DENTRO do payload e deixa o resto
            # dele intacto — o `ligacao_id`, o `vendus_document_id` e o `modo`
            # do documento continuam lá.
            "payload.forcar": True,
            "atualizado_em": _iso(agora),
        }},
        projection={"_id": 0}, return_document=ReturnDocument.AFTER)
    if linha is None:
        raise HTTPException(status_code=404, detail=_MSG_SEM_LINHA_DE_EMAIL)
    tentar_ja(db, linha["id"])
    return {"reenviado": True, "estado": linha["estado"]}
