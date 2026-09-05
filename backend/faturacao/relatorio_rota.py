"""**As portas do relatório diário** — a única peça que toca no Mongo e na rede.

Três rotas de gestão (a lista de quem recebe, e o "enviar agora" para o dono
testar sem esperar pelas 23:30) e uma de cron, protegida pela `CRON_KEY` e sem
JWT — o mesmo padrão das que já existem no `server.py`.

**Aqui não se faz nenhuma conta.** Lê a base de dados, entrega as listas a
`relatorio_diario.montar_relatorio`, dá o resultado a
`relatorio_email.html_do_relatorio` e envia. Se um número estiver errado, o
erro está num desses dois módulos — e é lá que tem teste, sem Mongo e sem
email pelo meio.
"""
import asyncio
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field

from .auth import gestor_atual
from .db import COLECOES, obter_db
from .periodos import LISBON_TZ
from .relatorio_diario import montar_relatorio
from .relatorio_email import html_do_relatorio
# A chave da definição da sincronização da app, importada e não copiada: a
# loja onde as faturas da app são gravadas é a MESMA que o email tem de
# reconhecer, e duas cópias da string divergem no dia em que uma mudar.
from .sincronizacao_rota import CHAVE as CHAVE_SINCRONIZACAO_APP

logger = logging.getLogger(__name__)
router = APIRouter()

CHAVE_DEFINICOES = "relatorio_diario"
# Quantos dias entram no gráfico de colunas. Catorze cabem em 600 px com
# 24 px por coluna e ainda deixam ler as três etiquetas.
DIAS_NO_GRAFICO = 14

_MSG_SEM_DESTINATARIOS = (
    "Não há nenhum email na lista de destinatários do relatório diário. "
    "Junte pelo menos um em Faturação → Configuração → Relatório diário."
)


class DefinicoesEntrada(BaseModel):
    # `EmailStr` e não uma expressão regular à mão: um email mal escrito na
    # lista faz o Resend recusar o envio INTEIRO, e o relatório da noite não
    # sai para ninguém — não só para quem se enganou a escrever.
    emails: List[EmailStr] = Field(default_factory=list, max_length=25)
    ativo: bool = True


async def _definicoes(db) -> Dict:
    doc = await db[COLECOES["definicoes"]].find_one(
        {"id": CHAVE_DEFINICOES}, {"_id": 0})
    if not doc:
        # Ausente é o estado NORMAL até alguém configurar. Devolve-se o mesmo
        # formato de sempre para o ecrã não ter de distinguir "nunca
        # configurado" de "configurado a vazio" — são a mesma coisa aqui.
        return {"id": CHAVE_DEFINICOES, "emails": [], "ativo": True}
    return doc


@router.get("/relatorio-diario/definicoes")
async def ler_definicoes(_: dict = Depends(gestor_atual)) -> dict:
    doc = await _definicoes(obter_db())
    return {"emails": doc.get("emails") or [], "ativo": doc.get("ativo", True)}


@router.put("/relatorio-diario/definicoes")
async def gravar_definicoes(
    dados: DefinicoesEntrada, _: dict = Depends(gestor_atual)
) -> dict:
    db = obter_db()
    # Sem duplicados e sem maiúsculas a fingir de emails diferentes: o mesmo
    # destinatário duas vezes recebia o relatório duas vezes.
    vistos = []
    for email in dados.emails:
        limpo = str(email).strip().lower()
        if limpo and limpo not in vistos:
            vistos.append(limpo)
    await db[COLECOES["definicoes"]].update_one(
        {"id": CHAVE_DEFINICOES},
        {"$set": {"id": CHAVE_DEFINICOES, "emails": vistos, "ativo": dados.ativo}},
        upsert=True,
    )
    return {"emails": vistos, "ativo": dados.ativo}


def _janela_do_dia(agora: datetime):
    """O dia lisboeta a que este relatório diz respeito, e o instante do corte.

    Corre às 23:30 e fala do dia que está a acabar — não do anterior. É por
    isso que a hora vai escrita no email: uma venda depois do corte entra no
    dia seguinte, e isso tem de se ler sem se ir perguntar a ninguém.
    """
    local = agora.astimezone(LISBON_TZ)
    return local.date().isoformat(), local.strftime("%H:%M")


async def _juntar_dados(db, dia: str) -> Dict:
    """Tudo o que `montar_relatorio` precisa, lido de uma vez.

    Os documentos vêm dos últimos `DIAS_NO_GRAFICO` dias porque o gráfico
    precisa deles; a comparação com ontem sai da mesma lista. Uma leitura em
    vez de três, e sem a possibilidade de quem chama passar um "hoje" e um
    "ontem" que não são dias seguidos.
    """
    inicio = (datetime.fromisoformat(dia).replace(tzinfo=LISBON_TZ)
              - timedelta(days=DIAS_NO_GRAFICO)).astimezone(timezone.utc)
    documentos = await db[COLECOES["documentos"]].find(
        {"emitido_em": {"$gte": inicio.isoformat()}}, {"_id": 0, "talao_escpos": 0}
    ).to_list(20000)

    lojas = await db[COLECOES["lojas"]].find(
        {}, {"_id": 0, "id": 1, "nome": 1}).sort("nome", 1).to_list(200)

    # As sessões de caixa do dia: as que abriram hoje (fechadas ou não).
    inicio_do_dia = datetime.fromisoformat(dia).replace(
        tzinfo=LISBON_TZ).astimezone(timezone.utc)
    sessoes = await db[COLECOES["sessoes_caixa"]].find(
        {"aberta_em": {"$gte": inicio_do_dia.isoformat()}}, {"_id": 0}
    ).to_list(500)

    # A loja da app: fatura, mas não tem gaveta nenhuma para conferir. Quem
    # sabe qual é, é a definição da sincronização — ver
    # `relatorio_diario.montar_relatorio`.
    definicao_da_app = await db[COLECOES["definicoes"]].find_one(
        {"id": CHAVE_SINCRONIZACAO_APP}, {"_id": 0}) or {}

    turnos = []
    for sessao in sessoes:
        movimentos = await db[COLECOES["movimentos_caixa"]].find(
            {"sessao_id": sessao["id"]}, {"_id": 0}).to_list(500)
        vendas = await db[COLECOES["vendas"]].find(
            {"sessao_id": sessao["id"]}, {"_id": 0}).to_list(5000)
        notas = await db[COLECOES["notas_credito"]].find(
            {"sessao_id": sessao["id"]}, {"_id": 0}).to_list(500)
        turnos.append({"sessao": sessao, "movimentos": movimentos,
                       "vendas": vendas, "notas_credito": notas})
    return {"documentos": documentos, "lojas": lojas, "turnos": turnos,
            "loja_da_app": definicao_da_app.get("loja_id")}


async def _enviar(html: str, para: List[str], assunto: str) -> Dict:
    """O envio, pelo Resend — o mesmo caminho que o resto do portal já usa.

    Importado aqui dentro e não no topo do módulo: o `resend` é opcional (o
    `server.py` também o trata assim) e um contentor sem ele não pode falhar a
    ARRANCAR por causa do relatório da noite.
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
    params = {
        "from": os.environ.get("SENDER_EMAIL", "onboarding@resend.dev"),
        "to": para,
        "subject": assunto,
        "html": html,
    }
    try:
        resposta = await asyncio.to_thread(resend.Emails.send, params)
    except Exception as e:  # noqa: BLE001 — a biblioteca levanta de tudo
        logger.error("[relatorio-diario] envio falhou: %s", e)
        raise HTTPException(status_code=502, detail="O envio do email falhou: %s" % e)
    return {"id": (resposta or {}).get("id")}


def _assunto(dados: Dict) -> str:
    """O assunto leva o NÚMERO. É o que se lê na lista da caixa de entrada sem
    abrir nada, e no telemóvel é muitas vezes tudo o que se lê."""
    from .relatorio_email import _euros
    total = _euros(dados["geral"]["faturacao"]).replace("&nbsp;", " ").replace("&#8239;", " ")
    dia = dados["dia"]
    return "Relatório diário · %s/%s · %s" % (dia[8:10], dia[5:7], total)


async def _produzir_e_enviar(para: List[str], url_do_painel: Optional[str]) -> Dict:
    db = obter_db()
    dia, ate = _janela_do_dia(datetime.now(timezone.utc))
    partes = await _juntar_dados(db, dia)
    dados = montar_relatorio(
        dia=dia, ate=ate, lojas=partes["lojas"],
        documentos=partes["documentos"], turnos=partes["turnos"],
        loja_da_app=partes["loja_da_app"])
    html = html_do_relatorio(dados, url_do_painel=url_do_painel)
    envio = await _enviar(html, para, _assunto(dados))
    return {
        "enviado_para": para,
        "email_id": envio.get("id"),
        "dia": dia,
        "ate": ate,
        "faturacao": dados["geral"]["faturacao"],
        "lojas": len(dados["lojas"]),
    }


class EnvioEntrada(BaseModel):
    # Opcional: sem isto vai para a lista configurada. Com isto, vai só para o
    # endereço indicado — é o "envia-me isso agora para eu ver" do dono, sem
    # acordar as cinco pessoas da lista às três da tarde.
    para: Optional[EmailStr] = None


@router.post("/relatorio-diario/enviar-agora")
async def enviar_agora(
    dados: EnvioEntrada, _: dict = Depends(gestor_atual)
) -> dict:
    para = [str(dados.para).strip().lower()] if dados.para else \
        (await _definicoes(obter_db())).get("emails") or []
    if not para:
        raise HTTPException(status_code=400, detail=_MSG_SEM_DESTINATARIOS)
    return await _produzir_e_enviar(para, os.environ.get("URL_DO_PAINEL"))


@router.post("/cron/relatorio-diario")
async def cron_relatorio_diario(key: str = Query(...)) -> dict:
    """A porta das 23:30. Protegida pela `CRON_KEY`, sem JWT — o mesmo padrão
    de `/api/fin/cron/*`.

    `compare_digest` e não `==`: uma comparação que pára no primeiro carácter
    diferente diz, pelo tempo que demora, quantos caracteres estavam certos.
    """
    chave = os.environ.get("CRON_KEY")
    if not chave or not secrets.compare_digest(str(key), str(chave)):
        raise HTTPException(status_code=403, detail="Acesso negado.")

    definicoes = await _definicoes(obter_db())
    if not definicoes.get("ativo", True):
        # Desligado no backoffice não é um erro: é uma decisão. Responde-se
        # com o que aconteceu, para o registo do cron o dizer por extenso.
        return {"enviado": False, "razao": "desligado nas definições"}
    para = definicoes.get("emails") or []
    if not para:
        logger.warning("[relatorio-diario] sem destinatários — nada enviado.")
        return {"enviado": False, "razao": "sem destinatários"}

    resultado = await _produzir_e_enviar(para, os.environ.get("URL_DO_PAINEL"))
    logger.info("[relatorio-diario] enviado para %d destinatário(s): %s",
                len(para), resultado.get("email_id"))
    return dict(resultado, enviado=True)
