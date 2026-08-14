"""Dashboard do módulo Faturação — o primeiro ecrã que o dono vê quando abre o
módulo.

Decisão do dono (2026-08-14): este ecrã lê as NOSSAS vendas (fat_documentos),
nunca o Vendus. O POS próprio (Plano 2) ainda não vende nada — por isso a
colecção existe mas está vazia, os cartões mostram zero e `ha_vendas` é False.
No dia em que a primeira loja faturar, o dashboard acende sozinho: não há
aqui nenhuma chave de API, nenhum pedido de rede, nada que dependa de um
serviço de terceiros.

O defeito do Vendus que este ecrã corrige (ver periodos.py para o porquê): ele
comparava períodos desiguais (13 dias de agosto contra julho inteiro). Aqui a
comparação é sempre com o período equivalente, e cada cartão diz por escrito
o que foi comparado com o quê (campo `comparacao`).
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends

from .auth import gestor_atual
from .db import COLECOES, obter_db
from .periodos import (
    LISBON_TZ,
    Janela,
    descreve_comparacao,
    janela_ano,
    janela_anterior_equivalente,
    janela_hoje,
    janela_mes,
    variacao,
)

router = APIRouter()

DIAS_SERIE_DIARIA = 30
MESES_SERIE_MENSAL = 6

# Tecto defensivo do to_list — não é um limite de negócio, é só para nunca
# ficar bloqueado a carregar um cursor infinito.
LIMITE_DOCUMENTOS = 100_000
LIMITE_LOJAS = 500


# --- lógica pura (sem I/O) — o essencial é testável sem Mongo --------------

def _campo_valor(com_iva: bool) -> str:
    """com_iva troca de CAMPO — nunca faz contas com uma taxa assumida. Mesma
    regra de ouro de precos.py: sem o campo certo, não se inventa nada."""
    return "total_bruto" if com_iva else "total_liquido"


def _parse_utc(valor) -> Optional[datetime]:
    """Interpreta um `emitido_em` (ISO, UTC) guardado como string. Devolve
    None se estiver ausente ou for ilegível — um documento assim não conta
    para janela nenhuma, em vez de rebentar o dashboard inteiro."""
    if not valor:
        return None
    try:
        dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _valor_documento(doc: Dict, campo: str) -> float:
    """Uma nota de crédito (NC) conta com sinal negativo; um documento
    anulado não conta nada. O abs() só se aplica à NC — defende contra uma NC
    que já viesse guardada negativa (sem duplicar o sinal); um FS não é
    tocado, para não mascarar silenciosamente um valor errado na origem."""
    if doc.get("anulado"):
        return 0.0
    valor = float(doc.get(campo) or 0)
    if doc.get("tipo") == "NC":
        return -abs(valor)
    return valor


def _soma_periodo(documentos: List[Dict], campo: str, janela: Janela, loja_id: Optional[str] = None) -> float:
    total = 0.0
    for doc in documentos:
        if loja_id is not None and doc.get("loja_id") != loja_id:
            continue
        dt = _parse_utc(doc.get("emitido_em"))
        if dt is None or not (janela.inicio <= dt < janela.fim):
            continue
        total += _valor_documento(doc, campo)
    return total


def _arredonda_opcional(valor: Optional[float]) -> Optional[float]:
    return None if valor is None else round(valor, 2)


def _janela_de_mes(ano: int, mes: int, agora: datetime) -> Janela:
    """Janela [dia 1 às 00:00 Lisboa, dia 1 do mês seguinte) — excepto para o
    mês corrente (ou um mês no futuro, defensivamente), em que o fim fica em
    "agora": nunca se conta um dia que ainda não aconteceu."""
    inicio = datetime(ano, mes, 1, tzinfo=LISBON_TZ).astimezone(timezone.utc)
    if mes == 12:
        proximo_mes = datetime(ano + 1, 1, 1, tzinfo=LISBON_TZ)
    else:
        proximo_mes = datetime(ano, mes + 1, 1, tzinfo=LISBON_TZ)
    fim = proximo_mes.astimezone(timezone.utc)
    agora_utc = agora.astimezone(timezone.utc)
    if agora_utc < fim:
        fim = agora_utc
    return Janela(inicio, fim)


def _serie_diaria(documentos: List[Dict], campo: str, agora: datetime, dias: int,
                   loja_id: Optional[str] = None) -> List[Dict]:
    hoje_lisboa = agora.astimezone(LISBON_TZ).date()
    serie = []
    for offset in range(dias - 1, -1, -1):
        dia = hoje_lisboa - timedelta(days=offset)
        # Meio-dia em Lisboa reaproveita janela_hoje sem repetir a conversão
        # de fuso aqui — janela_hoje só olha para a DATA do instante recebido.
        janela = janela_hoje(datetime(dia.year, dia.month, dia.day, 12, tzinfo=LISBON_TZ))
        serie.append({
            "data": dia.isoformat(),
            "valor": round(_soma_periodo(documentos, campo, janela, loja_id), 2),
        })
    return serie


def _serie_mensal(documentos: List[Dict], campo: str, agora: datetime, meses: int,
                   loja_id: Optional[str] = None) -> List[Dict]:
    agora_lisboa = agora.astimezone(LISBON_TZ)
    serie = []
    for offset in range(meses - 1, -1, -1):
        ano, mes = agora_lisboa.year, agora_lisboa.month - offset
        while mes < 1:
            mes += 12
            ano -= 1
        janela = _janela_de_mes(ano, mes, agora)
        serie.append({
            "mes": "%04d-%02d" % (ano, mes),
            "valor": round(_soma_periodo(documentos, campo, janela, loja_id), 2),
        })
    return serie


def _cartao(documentos: List[Dict], campo: str, janela_actual: Janela, janela_ant: Janela) -> Dict:
    valor_actual = _soma_periodo(documentos, campo, janela_actual)
    valor_anterior = _soma_periodo(documentos, campo, janela_ant)
    return {
        "valor": round(valor_actual, 2),
        "valor_comparado": round(valor_anterior, 2),
        "variacao": _arredonda_opcional(variacao(valor_actual, valor_anterior)),
        "comparacao": descreve_comparacao(janela_actual, janela_ant),
    }


def calcula_dashboard(documentos: List[Dict], lojas: List[Dict], agora: datetime,
                       com_iva: bool = True) -> Dict:
    """Constrói toda a resposta do dashboard a partir de dados já em memória —
    puro no sentido em que não toca em Mongo nem na rede; só o endpoint (mais
    abaixo) é que vai buscar `documentos`/`lojas` à base de dados."""
    campo = _campo_valor(com_iva)

    j_hoje = janela_hoje(agora)
    # "Ontem" reaproveita janela_hoje com um instante um microssegundo antes
    # da meia-noite de hoje — dá sempre a data certa (mesmo no dia da mudança
    # de hora) sem repetir aqui a lógica de fuso de periodos.py.
    j_hoje_anterior = janela_hoje(j_hoje.inicio - timedelta(microseconds=1))

    j_mes = janela_mes(agora)
    j_mes_anterior = janela_anterior_equivalente(j_mes.inicio, j_mes.fim, "mes")

    j_ano = janela_ano(agora)
    j_ano_anterior = janela_anterior_equivalente(j_ano.inicio, j_ano.fim, "ano")

    cartoes = {
        "hoje": _cartao(documentos, campo, j_hoje, j_hoje_anterior),
        "mensal": _cartao(documentos, campo, j_mes, j_mes_anterior),
        "anual": _cartao(documentos, campo, j_ano, j_ano_anterior),
    }

    por_loja = []
    for loja in sorted(lojas, key=lambda l: l.get("nome") or ""):
        loja_id = loja.get("id")
        por_loja.append({
            "loja_id": loja_id,
            "nome": loja.get("nome"),
            "hoje": round(_soma_periodo(documentos, campo, j_hoje, loja_id), 2),
            "mensal": round(_soma_periodo(documentos, campo, j_mes, loja_id), 2),
            "serie_diaria": _serie_diaria(documentos, campo, agora, DIAS_SERIE_DIARIA, loja_id),
        })

    return {
        "cartoes": cartoes,
        "serie_diaria": _serie_diaria(documentos, campo, agora, DIAS_SERIE_DIARIA),
        "ultimos_6_meses": _serie_mensal(documentos, campo, agora, MESES_SERIE_MENSAL),
        "por_loja": por_loja,
        # Falso enquanto ninguém vendeu — é o que diz ao ecrã para mostrar
        # "ainda não há vendas" em vez de um gráfico de zeros sem explicação.
        "ha_vendas": any(not doc.get("anulado") for doc in documentos),
    }


# --- endpoint ----------------------------------------------------------------

@router.get("/dashboard")
async def obter_dashboard(com_iva: bool = True, _: dict = Depends(gestor_atual)) -> Dict:
    db = obter_db()
    agora = datetime.now(timezone.utc)

    # Só é preciso ir buscar desde o início do ano: é a maior janela que o
    # dashboard usa (o cartão anual). Comparação por string funciona porque
    # emitido_em é sempre ISO em UTC (mesmo padrão do server.py: LISBON_TZ,
    # day_start_utc = ...isoformat(), filtro por $gte sobre a string).
    inicio_ano = janela_ano(agora).inicio.isoformat()
    documentos = await db[COLECOES["documentos"]].find(
        {"emitido_em": {"$gte": inicio_ano}}, {"_id": 0}
    ).to_list(LIMITE_DOCUMENTOS)

    lojas = await db[COLECOES["lojas"]].find(
        {}, {"_id": 0, "id": 1, "nome": 1}
    ).to_list(LIMITE_LOJAS)

    return calcula_dashboard(documentos, lojas, agora, com_iva)
