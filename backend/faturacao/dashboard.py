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
    janela_ontem_equivalente,
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
    # "Ontem" NÃO é o dia anterior inteiro (24h) — seria comparar um dia a
    # meio (poucas horas de vendas) com um dia completo, e mostraria sempre
    # uma queda enorme de manhã (C2). janela_ontem_equivalente pára "ontem"
    # à mesma hora do relógio a que "hoje" ainda vai.
    j_hoje_anterior = janela_ontem_equivalente(agora)

    # janela_anterior_equivalente devolve os DOIS lados (actual, anterior):
    # o anterior termina sempre à mesma hora do relógio que o actual (C2), e
    # se o mês/ano anterior for mais curto, o actual também é encurtado
    # (I1) — daí reatribuir j_mes/j_ano aqui, em vez de só ler ".anterior".
    j_mes_bruto = janela_mes(agora)
    j_mes, j_mes_anterior = janela_anterior_equivalente(j_mes_bruto.inicio, j_mes_bruto.fim, "mes")

    j_ano_bruto = janela_ano(agora)
    j_ano, j_ano_anterior = janela_anterior_equivalente(j_ano_bruto.inicio, j_ano_bruto.fim, "ano")

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

    # NOTA: `ha_vendas` não faz parte desta resposta (I3) — é o endpoint que
    # a acrescenta, com uma pergunta directa à base de dados (`_existe_venda`).
    # `documentos` aqui está limitado à janela que os cartões/gráficos
    # precisam (desde o início do ano anterior, ver o endpoint) — deduzir
    # "alguma vez existiu uma venda?" a partir dessa janela dava um "não"
    # errado sempre que o negócio tivesse vendas mais antigas do que ela.
    return {
        "cartoes": cartoes,
        "serie_diaria": _serie_diaria(documentos, campo, agora, DIAS_SERIE_DIARIA),
        "ultimos_6_meses": _serie_mensal(documentos, campo, agora, MESES_SERIE_MENSAL),
        "por_loja": por_loja,
    }


# --- endpoint ----------------------------------------------------------------

async def _existe_venda(db) -> bool:
    """Pergunta DIRECTAMENTE à base de dados se alguma vez existiu um
    documento de venda não anulado (I3) — independente da janela de datas
    que a consulta principal usa (essa está limitada ao ano anterior para
    trás, só para alimentar os cartões/gráficos). Um negócio pode ter
    vendido antes dessa janela; a faixa "ainda não há vendas" não pode
    ignorar isso só porque a janela dos gráficos não chega lá."""
    doc = await db[COLECOES["documentos"]].find_one({"anulado": {"$ne": True}}, {"_id": 1})
    return doc is not None


@router.get("/dashboard")
async def obter_dashboard(com_iva: bool = True, _: dict = Depends(gestor_atual)) -> Dict:
    db = obter_db()
    agora = datetime.now(timezone.utc)

    # A maior janela que o dashboard usa não é o ano corrente — é o cartão
    # Anual, que compara com o ANO ANTERIOR equivalente (janela_anterior_
    # equivalente começa sempre a 1 de Janeiro do ano passado). Ir buscar só
    # desde o início do ano corrente deixava o ano anterior inteiro de fora,
    # sem erro nem aviso: o cartão Anual ficava sempre "Sem período anterior
    # comparável" e as séries ficavam a zero perto do início do ano. Compa-
    # ração por string funciona porque emitido_em é sempre ISO em UTC (mesmo
    # padrão do server.py: LISBON_TZ, day_start_utc = ...isoformat(), filtro
    # por $gte sobre a string).
    j_ano = janela_ano(agora)
    _, j_ano_anterior = janela_anterior_equivalente(j_ano.inicio, j_ano.fim, "ano")
    inicio_consulta = j_ano_anterior.inicio.isoformat()
    documentos = await db[COLECOES["documentos"]].find(
        {"emitido_em": {"$gte": inicio_consulta}}, {"_id": 0}
    ).to_list(LIMITE_DOCUMENTOS)

    lojas = await db[COLECOES["lojas"]].find(
        {}, {"_id": 0, "id": 1, "nome": 1}
    ).to_list(LIMITE_LOJAS)

    resultado = calcula_dashboard(documentos, lojas, agora, com_iva)
    # I3: pergunta à parte, nunca deduzida de `documentos` (essa janela é
    # limitada, ver acima — não serve para responder "alguma vez vendeu?").
    resultado["ha_vendas"] = await _existe_venda(db)
    return resultado
