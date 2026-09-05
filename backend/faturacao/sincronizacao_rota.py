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


def _saltar(resultado: Dict, doc: Dict, motivo: str) -> None:
    """Conta o documento como ignorado **e deixa-o à vista de quem pode agir.**

    Um documento que fica de fora por avaria fica de fora PARA SEMPRE: a
    janela da volta só olha para hoje e ontem, e a volta seguinte nem sequer o
    tenta outra vez com outro resultado. Contá-lo em `motivos` e escrevê-lo no
    log deixa-o só onde ninguém olha — `assinalados` é o que aparece a quem
    carregou no botão.
    """
    _contar(resultado, motivo)
    resultado["assinalados"].append(
        "%s: %s" % (doc.get("number") or "id %s" % doc.get("id"), motivo))


async def sincronizar(db, *, dias: List[str], simular: bool = False) -> Dict:
    """Lê os dias pedidos e grava o que for para gravar.

    **Falha inteira, nunca a meio.** Se o Vendus não responder, a volta acaba
    sem gravar e diz porquê — a volta seguinte (5 minutos) apanha tudo. É o que
    torna isto seguro de correr tantas vezes quantas se quiser.

    `simular=True` faz tudo menos a gravação: é como se prova, contra a
    produção, o que ia acontecer antes de deixar acontecer.

    `assinalados` é a lista dos documentos que ficaram de fora por AVARIA (sem
    id na lista, sem ATCUD, total ilegível, desapareceu do Vendus) — um por
    linha, identificado pelo número do Vendus e com a razão. Não é o mesmo que
    `motivos`, que conta também as exclusões normais e de propósito (um
    orçamento, uma fatura nossa). Uma FS real de 6,85 € que caia num destes
    casos não volta a ser tentada: sem esta lista, desaparecia do Dashboard e
    do relatório com o cron a parecer saudável.
    """
    resultado = {"lidos": 0, "gravados": 0, "ignorados": 0, "repetidos": 0,
                 "motivos": {}, "assinalados": [], "erros": [],
                 "simulado": simular}

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

                    # `deve_importar` não exige `id` — decide por tipo, ref e
                    # estado. Sem esta guarda, o `int(doc["id"])` de baixo
                    # levantava `KeyError`, que NÃO é `VendusErro` e por isso
                    # escapava à volta inteira: o cron levava um 500 de cinco
                    # em cinco minutos e nem os documentos seguintes entravam.
                    if not doc.get("id"):
                        _saltar(resultado, doc, "sem id na lista do Vendus")
                        continue
                    # Um `id` presente mas ilegível (ex.: texto em vez de
                    # número) faz o mesmo estrago: `int()` levanta
                    # `ValueError`, também não é `VendusErro`, e escapava do
                    # mesmo jeito. Converte-se uma vez aqui e reutiliza-se o
                    # valor a seguir.
                    try:
                        doc_id = int(doc["id"])
                    except (TypeError, ValueError):
                        _saltar(resultado, doc,
                                "id do Vendus ilegível: %r" % doc.get("id"))
                        continue

                    # Um documento que já temos não se vai buscar outra vez: é
                    # um pedido ao Vendus por documento, e a esmagadora maioria
                    # das voltas relê dias inteiros que já estão gravados.
                    if await coleccao.find_one(
                            {"vendus_document_id": doc_id}, {"_id": 1}):
                        resultado["repetidos"] += 1
                        continue

                    # O ATCUD e as linhas só existem no GET por id.
                    cru = await asyncio.to_thread(cliente.ler_documento, doc["id"])
                    if cru is None:
                        _saltar(resultado, doc, "desapareceu do Vendus")
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
                        _saltar(resultado, doc, str(e))
                        continue

                    resultado["gravados"] += 1
                    if simular:
                        continue
                    try:
                        await coleccao.insert_one(pronto)
                    except DuplicateKeyError:
                        resultado["gravados"] -= 1
                        # `fat_documentos` tem TRÊS chaves únicas
                        # (db.py:132-158): `vendus_document_id`, `atcud` e o
                        # parcial `ext_ref`. Só a primeira é "o mesmo
                        # documento outra vez" — as outras duas são um
                        # documento DIFERENTE a colidir, e engoli-las era
                        # deitá-lo fora em silêncio, com `erros: []`, a gastar
                        # um `ler_documento` por volta para sempre. O caso
                        # real: uma NC da app que traga a `external_reference`
                        # da FS que anula — a fatura ficava, o estorno nunca
                        # entrava, e a receita daquela loja ficava inflacionada
                        # sem nada a assinalar. Pergunta-se à base qual dos
                        # dois é.
                        if await coleccao.find_one(
                                {"vendus_document_id": pronto["vendus_document_id"]},
                                {"_id": 1}):
                            # Duas voltas em cima uma da outra. Não é avaria.
                            resultado["repetidos"] += 1
                        else:
                            # O espírito do `ConflitoDocumentoFiscal` de
                            # `fiscal.py:1287`: nada foi sobreposto, e isto
                            # precisa de olhos.
                            resultado["erros"].append(
                                "documento %s (id=%s, ATCUD=%s) colide com "
                                "outro já gravado — mesmo `atcud` ou mesma "
                                "`ext_ref` com id DIFERENTE. Nada foi "
                                "sobreposto e este documento NÃO entrou: "
                                "precisa de investigação manual." % (
                                    pronto.get("numero"),
                                    pronto.get("vendus_document_id"),
                                    pronto.get("atcud")))
                            logger.error("[sinc-app] conflito ao gravar %s",
                                         pronto.get("numero"))
    except VendusErro as e:
        # A volta acaba aqui. O que já foi gravado fica (cada documento é uma
        # gravação independente e idempotente); o que faltava vem na próxima.
        resultado["erros"].append("%s: %s" % (type(e).__name__, e))
        logger.warning("[sinc-app] volta interrompida: %s", e)

    logger.info("[sinc-app] %s: lidos=%d gravados=%d ignorados=%d repetidos=%d %s",
                "ENSAIO" if simular else "a sério", resultado["lidos"],
                resultado["gravados"], resultado["ignorados"],
                resultado["repetidos"], resultado["motivos"])
    for linha in resultado["assinalados"]:
        logger.warning("[sinc-app] assinalado: %s", linha)
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
    db = obter_db()
    # Uma `loja_id` que não existe em `fat_lojas` não dá erro nenhum a gravar,
    # e depois a FS da app fica invisível em toda a vista filtrada por loja
    # enquanto continua a contar no total de "todas as lojas" — dois números
    # diferentes que ninguém consegue explicar. Mesma guarda de
    # `lojas.criar_caixa` e de `pos_auth.gerar_codigo_emparelhamento`.
    if dados.loja_id and not await db[COLECOES["lojas"]].find_one(
            {"id": dados.loja_id}):
        raise HTTPException(status_code=404, detail="Loja não encontrada")
    await db[COLECOES["definicoes"]].update_one(
        {"id": CHAVE}, {"$set": dados.model_dump()}, upsert=True)
    return await _definicoes(db)


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
