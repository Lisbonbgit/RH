"""**Os pontos L'Açaí dados na caixa** — o POS a falar com a app.

A regra do dono: ganha os pontos quem mostra a app na caixa ANTES de pagar. O
talão deixa de ser um bilhete ao portador, porque o que dá pontos já não é o
QR fiscal impresso — é o QR da app, lido pela funcionária e preso a UMA venda.

Três peças, e uma regra acima das três: **nada daqui pode impedir uma fatura
de sair nem atrasar o EMITIR.**

1. **Ler** (`POST /pos/pontos/ler`) — troca o código do QR por uma ligação na
   app e devolve só o primeiro nome. Não grava nada na venda: é o ecrã que
   guarda a ligação e a manda no finalizar (`fiscal.PedidoFinalizarVenda`).
2. **A fila** (`fat_pontos_app`) — uma linha por crédito (FS) e por estorno
   (NC), com chave única. Nasce DEPOIS de o documento existir e nunca antes:
   os pontos só entram com a fatura já entregue à AT.
3. **O envio** — reserva a linha, fala com a app (4 s) e grava o desfecho. O
   que for técnico (rede, 5xx, chave errada) volta a tentar-se com espera
   crescente; o que for de negócio (`recusado`) não se repete.

A app é idempotente por ATCUD e por nota de crédito, e é isso que deixa este
lado ser simples: um reenvio nunca credita duas vezes.
"""
import logging
import os
from typing import Dict

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .db import COLECOES, obter_db
from .pos_auth import operador_atual
from .venda import _garante_aberta, _obter_venda_da_loja

logger = logging.getLogger(__name__)

router = APIRouter()

# 4 segundos, como o desconto de stock (`estoque_cliente.TIMEOUT_SAIDA_SEGUNDOS`)
# e pela mesma razão: quem espera pelo Ler é a funcionária com o cliente à
# frente. Uma app em baixo diz-se depressa, e a fatura segue sem pontos.
TIMEOUT_SEGUNDOS = 4.0

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
    async with httpx.AsyncClient(timeout=TIMEOUT_SEGUNDOS, transport=_transporte) as http:
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
    except (IntegracaoNaoConfigurada, httpx.HTTPError) as e:
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
    return {
        "ligacao_id": str(corpo["ligacao_id"]),
        "primeiro_nome": str(corpo.get("primeiro_nome") or ""),
    }
