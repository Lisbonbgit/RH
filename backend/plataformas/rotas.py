"""**As portas do relatório das plataformas** — a única peça que toca no Mongo,
na caixa de email e na rede.

Aqui não se faz nenhuma conta. Lê a base de dados, entrega os registos ao
`resumo.montar_relatorio`, dá o resultado ao `email_semanal.html_do_relatorio`
e envia. Se um número estiver errado, o erro está num desses dois módulos — e
é lá que tem teste, sem Mongo e sem email pelo meio.

**A idempotência não precisa de índice nenhum, e é de propósito.** As duas
chaves deste módulo são o `_id` do Mongo:

- `plat_relatorios._id` é `"uber:2026-08-24..2026-08-30"`, por isso ler a mesma
  caixa duas vezes reescreve o mesmo documento em vez de criar dois;
- `plat_envios._id` é a semana ISO (`"2026-W35"`), por isso o segundo `insert`
  da mesma segunda-feira rebenta com `DuplicateKeyError` antes de o email
  chegar a ser enviado.

O `_id` é único no Mongo sem ninguém declarar nada — e uma garantia que não
depende de um índice ter sido criado com sucesso no arranque é uma garantia a
menos para confirmar (ver o que `faturacao/db.py` teve de escrever à volta
disso).
"""
import asyncio
import logging
import os
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from pymongo.errors import DuplicateKeyError

# A base de dados é a MESMA e o cliente também: um segundo
# `AsyncIOMotorClient` era um segundo conjunto de ligações ao Atlas para ler
# três documentos por semana.
from faturacao.auth import gestor_atual
from faturacao.db import obter_db

from . import leitura
from .calendario import chave_da_semana, semana_fechada
from .email_semanal import assunto as assunto_do_email
from .email_semanal import html_do_relatorio
from .resumo import montar_relatorio

logger = logging.getLogger(__name__)
router = APIRouter()

LISBOA = ZoneInfo("Europe/Lisbon")

COLECOES = {
    "relatorios": "plat_relatorios",
    "definicoes": "plat_definicoes",
    "envios": "plat_envios",
}

CHAVE_DEFINICOES = "relatorio_plataformas"

# Quantos dias de registos se lêem para montar o relatório. Sessenta chegam
# para o período em curso e para o anterior de qualquer das três plataformas
# (a quinzena da Glovo mais a anterior não passam de 32 dias), com folga para
# um relatório que chegue atrasado.
DIAS_DE_HISTORICO = 60

# Sem índice nenhum: são três linhas por semana. Ao fim de um ano são ~156
# documentos, e uma leitura completa de 156 documentos não é um problema que
# valha um índice para manter.
#
# ponytail: leitura completa da colecção; se um dia isto crescer (mais
# plataformas, mais anos), põe-se um índice em `periodo_inicio`.
LIMITE_DE_LEITURA = 5000

_MSG_SEM_DESTINATARIOS = (
    "Não há nenhum email na lista de destinatários. Junte pelo menos um em "
    "Painel → Plataformas.")


# --- Definições (quem recebe) ------------------------------------------------

class DefinicoesEntrada(BaseModel):
    # `EmailStr` e não uma expressão à mão: um email mal escrito faz o Resend
    # recusar o envio INTEIRO, e o relatório de segunda não sai para ninguém —
    # não só para quem se enganou a escrever.
    emails: List[EmailStr] = Field(default_factory=list, max_length=25)
    ativo: bool = True


async def _definicoes(db) -> Dict:
    doc = await db[COLECOES["definicoes"]].find_one(
        {"id": CHAVE_DEFINICOES}, {"_id": 0})
    if not doc:
        # Ausente é o estado NORMAL até alguém configurar; devolve-se o mesmo
        # formato para o ecrã não ter de distinguir "nunca configurado" de
        # "configurado a vazio".
        return {"id": CHAVE_DEFINICOES, "emails": [], "ativo": True}
    return doc


@router.get("/definicoes")
async def ler_definicoes(_: dict = Depends(gestor_atual)) -> dict:
    doc = await _definicoes(obter_db())
    return {"emails": doc.get("emails") or [], "ativo": doc.get("ativo", True)}


@router.put("/definicoes")
async def gravar_definicoes(
    dados: DefinicoesEntrada, _: dict = Depends(gestor_atual)
) -> dict:
    vistos: List[str] = []
    for email in dados.emails:
        limpo = str(email).strip().lower()
        if limpo and limpo not in vistos:
            vistos.append(limpo)
    await obter_db()[COLECOES["definicoes"]].update_one(
        {"id": CHAVE_DEFINICOES},
        {"$set": {"id": CHAVE_DEFINICOES, "emails": vistos, "ativo": dados.ativo}},
        upsert=True,
    )
    return {"emails": vistos, "ativo": dados.ativo}


# --- Os registos lidos -------------------------------------------------------

def _hoje_em_lisboa() -> date:
    """O dia lisboeta. **O servidor corre em UTC** e, à hora a que este cron
    dispara (madrugada/manhã), o dia em UTC e o dia em Lisboa podem ser o
    mesmo — mas não é disso que se depende: uma corrida manual à meia-noite e
    meia de Lisboa está no dia anterior em UTC, e o relatório saía com a
    semana errada."""
    return datetime.now(timezone.utc).astimezone(LISBOA).date()


async def _registos_recentes(db, hoje: date) -> List[Dict]:
    desde = (hoje - timedelta(days=DIAS_DE_HISTORICO)).isoformat()
    return await db[COLECOES["relatorios"]].find(
        {"periodo_inicio": {"$gte": desde}}, {"_id": 0}
    ).to_list(LIMITE_DE_LEITURA)


async def _gravar_registos(db, registos: List[Dict]) -> int:
    """Grava cada registo no seu `_id`. Reler a mesma caixa reescreve o mesmo
    documento — nunca cria um segundo."""
    for registo in registos:
        documento = dict(registo)
        documento["_id"] = documento["id"]
        await db[COLECOES["relatorios"]].replace_one(
            {"_id": documento["_id"]}, documento, upsert=True)
    return len(registos)


async def _recolher_e_gravar(db, hoje: date) -> Dict:
    """Lê as caixas (numa thread — `imaplib` e `httpx` são síncronos, como no
    `fin_cron_ingest`) e grava o que encontrar."""
    saida = await asyncio.to_thread(leitura.recolher, hoje)
    gravados = await _gravar_registos(db, saida["registos"])
    return {"lidos": gravados, "avisos": saida["avisos"]}


@router.get("/relatorio")
async def ver_relatorio(_: dict = Depends(gestor_atual)) -> dict:
    """O relatório de hoje a partir do que JÁ está guardado — não vai à caixa
    de email. É o que o ecrã do Painel mostra, e abrir o ecrã não pode custar
    uma leitura IMAP e uma factura da IA."""
    hoje = _hoje_em_lisboa()
    db = obter_db()
    return montar_relatorio(
        hoje=hoje, ate=datetime.now(timezone.utc).astimezone(LISBOA).strftime("%H:%M"),
        registos=await _registos_recentes(db, hoje))


@router.get("/historico")
async def ver_historico(
    limite: int = Query(60, ge=1, le=500), _: dict = Depends(gestor_atual)
) -> dict:
    """As semanas e quinzenas já lidas, das mais recentes para as mais antigas.
    É a tabela do ecrã."""
    registos = await obter_db()[COLECOES["relatorios"]].find({}, {"_id": 0}).sort(
        [("periodo_inicio", -1), ("plataforma", 1)]).to_list(limite)
    return {"registos": registos}


@router.post("/recolher-agora")
async def recolher_agora(_: dict = Depends(gestor_atual)) -> dict:
    """Ler a caixa agora, sem enviar email nenhum. É o botão para confirmar que
    a leitura funciona antes de contar com ela na segunda-feira."""
    hoje = _hoje_em_lisboa()
    db = obter_db()
    resultado = await _recolher_e_gravar(db, hoje)
    return dict(resultado, hoje=hoje.isoformat())


# --- O envio -----------------------------------------------------------------

async def _enviar(html: str, para: List[str], titulo: str) -> Dict:
    """O envio pelo Resend — o mesmo caminho que o resto do portal já usa.

    Importado aqui dentro e não no topo: o `resend` é opcional (o `server.py`
    também o trata assim) e um contentor sem ele não pode falhar a ARRANCAR
    por causa do email de segunda-feira.
    """
    chave = os.environ.get("RESEND_API_KEY")
    if not chave:
        raise HTTPException(
            status_code=503,
            detail="RESEND_API_KEY não está configurada no servidor — o "
                   "relatório não pode ser enviado.")
    try:
        import resend
    except ImportError:  # pragma: no cover — a biblioteca está no requirements
        raise HTTPException(status_code=503, detail="Biblioteca de email indisponível.")

    resend.api_key = chave
    parametros = {
        "from": os.environ.get("SENDER_EMAIL", "onboarding@resend.dev"),
        "to": para,
        "subject": titulo,
        "html": html,
    }
    try:
        resposta = await asyncio.to_thread(resend.Emails.send, parametros)
    except Exception as e:  # noqa: BLE001 — a biblioteca levanta de tudo
        logger.error("[plataformas] envio falhou: %s", e)
        raise HTTPException(status_code=502, detail="O envio do email falhou: %s" % e)
    return {"id": (resposta or {}).get("id")}


async def _produzir_e_enviar(db, hoje: date, para: List[str], avisos: List[str]) -> Dict:
    dados = montar_relatorio(hoje=hoje, ate="08:00",
                             registos=await _registos_recentes(db, hoje),
                             avisos=avisos)
    envio = await _enviar(html_do_relatorio(dados, os.environ.get("URL_DO_PAINEL")),
                          para, assunto_do_email(dados))
    return {
        "enviado_para": para,
        "email_id": envio.get("id"),
        "semana": dados["semana"],
        "total": dados["total_da_semana"]["liquido"],
        "completo": dados["total_da_semana"]["completo"],
    }


class EnvioEntrada(BaseModel):
    # Sem isto vai para a lista configurada. Com isto, vai só para o endereço
    # indicado — é o "envia-me isso agora para eu ver", sem acordar as cinco
    # pessoas da lista a meio da tarde.
    para: Optional[EmailStr] = None
    # Ler a caixa antes de enviar. Por omissão NÃO lê: o botão serve para ver o
    # email desenhado, e uma leitura IMAP + IA a cada carregar do botão custa
    # dinheiro e demora.
    recolher: bool = False


@router.post("/enviar-agora")
async def enviar_agora(dados: EnvioEntrada, _: dict = Depends(gestor_atual)) -> dict:
    db = obter_db()
    hoje = _hoje_em_lisboa()
    para = [str(dados.para).strip().lower()] if dados.para else \
        (await _definicoes(db)).get("emails") or []
    if not para:
        raise HTTPException(status_code=400, detail=_MSG_SEM_DESTINATARIOS)
    avisos: List[str] = []
    if dados.recolher:
        avisos = (await _recolher_e_gravar(db, hoje))["avisos"]
    # **Não consome a reserva da semana.** Este botão é para ver; o email das
    # 08:00 tem de sair na mesma.
    return await _produzir_e_enviar(db, hoje, para, avisos)


@router.post("/cron/semanal")
async def cron_semanal(key: str = Query(...), forcar: bool = Query(False)) -> dict:
    """A porta das 08:00 de segunda-feira. Protegida pela `CRON_KEY`, sem JWT —
    o mesmo padrão de `/api/fin/cron/*` e de `/api/faturacao/cron/*`.

    `compare_digest` e não `==`: uma comparação que pára no primeiro carácter
    diferente diz, pelo tempo que demora, quantos caracteres estavam certos.
    """
    chave = os.environ.get("CRON_KEY")
    if not chave or not secrets.compare_digest(str(key), str(chave)):
        raise HTTPException(status_code=403, detail="Acesso negado.")

    db = obter_db()
    hoje = _hoje_em_lisboa()
    definicoes = await _definicoes(db)
    if not definicoes.get("ativo", True):
        # Desligado no backoffice não é um erro: é uma decisão.
        return {"enviado": False, "razao": "desligado nas definições"}
    para = definicoes.get("emails") or []
    if not para:
        logger.warning("[plataformas] sem destinatários — nada enviado.")
        return {"enviado": False, "razao": "sem destinatários"}

    # A leitura acontece SEMPRE, mesmo que o email já tenha saído: um relatório
    # que chegue à tarde tem de aparecer no painel na mesma.
    recolha = await _recolher_e_gravar(db, hoje)

    inicio, _fim = semana_fechada(hoje)
    marca = chave_da_semana(inicio)
    if not forcar:
        try:
            await db[COLECOES["envios"]].insert_one({
                "_id": marca, "id": marca, "para": para,
                "iniciado_em": datetime.now(timezone.utc).isoformat(),
            })
        except DuplicateKeyError:
            # Já saiu esta semana. O cron pode disparar duas vezes (uma
            # retentativa, um `crontab` duplicado); dois emails iguais na mesma
            # manhã lêem-se como um erro do sistema.
            return dict(recolha, enviado=False,
                        razao="o email desta semana (%s) já foi enviado" % marca)

    try:
        resultado = await _produzir_e_enviar(db, hoje, para, recolha["avisos"])
    except Exception:
        # **A reserva desfaz-se quando o envio falha.** Sem isto, uma falha do
        # Resend marcava a semana como enviada e o email nunca mais saía — a
        # avaria silenciosa exactamente na peça que existe para avisar.
        if not forcar:
            await db[COLECOES["envios"]].delete_one({"_id": marca})
        raise

    await db[COLECOES["envios"]].update_one(
        {"_id": marca},
        {"$set": {"enviado_em": datetime.now(timezone.utc).isoformat(),
                  "email_id": resultado.get("email_id")}},
        upsert=True)
    logger.info("[plataformas] %s enviado para %d destinatário(s): %s",
                marca, len(para), resultado.get("email_id"))
    return dict(recolha, enviado=True, semana_chave=marca, **resultado)
