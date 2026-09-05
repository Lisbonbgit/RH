"""**Ir buscar ao Vendus as faturas que não saíram do nosso POS.**

A app L'Açaí emite pela MESMA caixa API e pela MESMA série que as cinco lojas.
Este módulo lê essa caixa, deixa passar só o que é venda e não é nosso, e grava
na loja que o gestor escolher. Não escreve nada no Vendus e não sabe o que é a
app: só sabe ler uma caixa e reconhecer o que lá não devia estar sozinho.

A decisão de quem entra vive em `sincronizacao_app.py`, sem Mongo nem rede.
Aqui é só a autorização, a configuração e a gravação.
"""
import asyncio
import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

from .auth import gestor_atual
from .db import COLECOES, obter_db
from .periodos import LISBON_TZ
from .sincronizacao_app import deve_importar, documento_para_gravar
from .vendus.cliente import obter_conta
from .vendus.emissao import (
    ClienteEmissaoVendus,
    VendusErro,
    VendusRespostaIlegivel,
    _register_id_configurado,
)

logger = logging.getLogger(__name__)
router = APIRouter()

CHAVE = "sincronizacao_app"
PRIMEIRO_DIA = "2026-09-01"   # decisão do dono; a app emite desde 18/08


class DefinicoesEntrada(BaseModel):
    loja_id: Optional[str] = None
    ativo: bool = True


async def _definicoes(db) -> Dict:
    doc = await db[COLECOES["definicoes"]].find_one({"id": CHAVE}, {"_id": 0})
    return doc or {}


def _contar(resultado: Dict, motivo: str) -> None:
    resultado["ignorados"] += 1
    resultado["motivos"][motivo] = resultado["motivos"].get(motivo, 0) + 1


async def sincronizar(db, *, dias: List[str], simular: bool = False) -> Dict:
    """Lê os dias pedidos e grava o que for para gravar.

    **Falha inteira, nunca a meio.** Se o Vendus não responder, a volta acaba
    sem gravar e diz porquê — a volta seguinte (5 minutos) apanha tudo. É o que
    torna isto seguro de correr tantas vezes quantas se quiser.

    `simular=True` faz tudo menos a gravação: é como se prova, contra a
    produção, o que ia acontecer antes de deixar acontecer.
    """
    resultado = {"lidos": 0, "gravados": 0, "ignorados": 0, "repetidos": 0,
                 "motivos": {}, "erros": [], "simulado": simular}

    definicoes = await _definicoes(db)
    loja_id = definicoes.get("loja_id")
    if not loja_id:
        resultado["erros"].append(
            "sem loja escolhida para as vendas da app — escolha-a em "
            "Configuração → Lojas. Adivinhar a loja era pôr a receita da app "
            "na loja errada.")
        return resultado
    if not definicoes.get("ativo", True):
        resultado["erros"].append("desligada nas definições")
        return resultado

    conta = obter_conta()
    if conta is None:
        resultado["erros"].append("sem conta Vendus configurada")
        return resultado
    register_id = _register_id_configurado()
    if register_id is None:
        resultado["erros"].append("VENDUS_REGISTER_ID não configurado")
        return resultado

    coleccao = db[COLECOES["documentos"]]
    try:
        # O cliente do Vendus é SÍNCRONO e isto é `async`: cada chamada vai
        # numa thread, como `fiscal._verificar_fecho_contra_o_vendus` já faz.
        # Sem isto, um Vendus lento pendurava o event loop do portal inteiro.
        with ClienteEmissaoVendus(conta.chave, timeout=60) as cliente:
            for dia in dias:
                documentos = await asyncio.to_thread(
                    cliente.listar_documentos_por_dia, dia, register_id)
                resultado["lidos"] += len(documentos)

                for doc in documentos:
                    entra, motivo = deve_importar(doc)
                    if not entra:
                        _contar(resultado, motivo)
                        continue

                    # Um documento que já temos não se vai buscar outra vez: é
                    # um pedido ao Vendus por documento, e a esmagadora maioria
                    # das voltas relê dias inteiros que já estão gravados.
                    if await coleccao.find_one(
                            {"vendus_document_id": int(doc["id"])}, {"_id": 1}):
                        resultado["repetidos"] += 1
                        continue

                    # O ATCUD e as linhas só existem no GET por id.
                    cru = await asyncio.to_thread(cliente.ler_documento, doc["id"])
                    if cru is None:
                        _contar(resultado, "desapareceu do Vendus")
                        continue

                    try:
                        pronto = documento_para_gravar(cru, loja_id)
                    except (ValueError, VendusRespostaIlegivel) as e:
                        # Sem ATCUD, sem id, ou com um total que não se lê:
                        # fica de fora, mas em voz alta.
                        #
                        # `VendusRespostaIlegivel` é uma `VendusErro` e sem
                        # esta linha caía no `except` de baixo, que acaba a
                        # volta INTEIRA. Só que, ao contrário do Vendus em
                        # baixo, isto não passa com o tempo: o mesmo documento
                        # volta a aparecer daí a cinco minutos e tudo o que
                        # vem a seguir a ele nunca mais entrava. Um documento
                        # que não se sabe ler é um documento a assinalar, não
                        # uma fila a bloquear.
                        logger.warning("[sinc-app] documento %s não se grava: %s",
                                       doc.get("number"), e)
                        _contar(resultado, str(e))
                        continue

                    resultado["gravados"] += 1
                    if simular:
                        continue
                    try:
                        await coleccao.insert_one(pronto)
                    except DuplicateKeyError:
                        # Duas voltas em cima uma da outra. Não é avaria.
                        resultado["gravados"] -= 1
                        resultado["repetidos"] += 1
    except VendusErro as e:
        # A volta acaba aqui. O que já foi gravado fica (cada documento é uma
        # gravação independente e idempotente); o que faltava vem na próxima.
        resultado["erros"].append("%s: %s" % (type(e).__name__, e))
        logger.warning("[sinc-app] volta interrompida: %s", e)

    logger.info("[sinc-app] %s: lidos=%d gravados=%d ignorados=%d repetidos=%d %s",
                "ENSAIO" if simular else "a sério", resultado["lidos"],
                resultado["gravados"], resultado["ignorados"],
                resultado["repetidos"], resultado["motivos"])
    return resultado


def _dias_da_volta() -> List[str]:
    """Hoje e ontem, em dias de Lisboa.

    Ontem também, sempre: apanha a fatura das 23h50 que o Vendus só mostrou
    depois da meia-noite, e as anulações do dia anterior. Duas leituras por
    volta é o preço de não precisar de guardar estado nenhum.
    """
    hoje = datetime.now(LISBON_TZ).date()
    return [(hoje - timedelta(days=1)).isoformat(), hoje.isoformat()]


@router.get("/sincronizacao-app/definicoes")
async def ler_definicoes_app(_: dict = Depends(gestor_atual)) -> dict:
    return await _definicoes(obter_db())


@router.put("/sincronizacao-app/definicoes")
async def gravar_definicoes_app(dados: DefinicoesEntrada,
                                _: dict = Depends(gestor_atual)) -> dict:
    await obter_db()[COLECOES["definicoes"]].update_one(
        {"id": CHAVE}, {"$set": dados.model_dump()}, upsert=True)
    return await _definicoes(obter_db())


@router.post("/sincronizacao-app/sincronizar-agora")
async def sincronizar_agora(_: dict = Depends(gestor_atual)) -> dict:
    """O botão do backoffice. Lê hoje e ontem, como o cron."""
    return await sincronizar(obter_db(), dias=_dias_da_volta())


@router.post("/cron/sincronizar-app")
async def cron_sincronizar_app(key: str = Query(...)) -> dict:
    """A porta dos 5 minutos. Protegida pela `CRON_KEY`, sem JWT — o mesmo
    padrão de `/cron/relatorio-diario` e de `/api/fin/cron/*`.

    `compare_digest` e não `==`: uma comparação que pára no primeiro carácter
    diferente diz, pelo tempo que demora, quantos caracteres estavam certos.
    """
    chave = os.environ.get("CRON_KEY")
    if not chave or not secrets.compare_digest(str(key), str(chave)):
        raise HTTPException(status_code=403, detail="Acesso negado.")
    return await sincronizar(obter_db(), dias=_dias_da_volta())
