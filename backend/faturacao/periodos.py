"""Janelas de tempo e comparação de períodos — puro, sem I/O, sem Mongo.

Existe por causa de um defeito concreto do dashboard do Vendus: no dia 13 de
agosto ele mostrava "Mensal €21.180,28, −64,31%" comparando 13 dias de agosto
com JULHO INTEIRO (31 dias) — e "Anual −28,76%" comparando 225 dias de 2026
com os 365 dias inteiros de 2025, quando à mesma data o negócio ia na
verdade ~15% ACIMA do ano anterior. Aqui a comparação é sempre com o período
equivalente: o mesmo número de dias, no mês/ano anterior. Nunca com o
período inteiro.

Fuso: os registos guardam-se em UTC (convenção do repositório — ver
LISBON_TZ em server.py), mas as fronteiras dos dias/meses/anos são as de
Lisboa. Todas as janelas devolvidas aqui são [inicio, fim) em UTC — o fim é
EXCLUSIVO, para se poder usar directamente num filtro Mongo com $gte/$lt.
"""
import calendar
from collections import namedtuple
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

LISBON_TZ = ZoneInfo("Europe/Lisbon")

# [inicio, fim) em UTC — intervalo meio-aberto, pronto a usar num filtro Mongo
# ($gte inicio, $lt fim) sem mais conversões.
Janela = namedtuple("Janela", ["inicio", "fim"])

_MESES_PT = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]


def _meia_noite_lisboa(dia: date) -> datetime:
    """Meia-noite (00:00) em Lisboa do dia dado, devolvida em UTC.

    Construído a partir da DATA (não com aritmética de timedelta sobre um
    instante UTC), para que o dia da mudança de hora — que em Lisboa só tem
    23 horas — dê a meia-noite certa em vez de ficar deslocado uma hora.
    """
    return datetime(dia.year, dia.month, dia.day, tzinfo=LISBON_TZ).astimezone(timezone.utc)


def janela_hoje(agora: datetime) -> Janela:
    """[meia-noite de hoje, meia-noite de amanhã) em Lisboa, convertido para UTC."""
    hoje = agora.astimezone(LISBON_TZ).date()
    amanha = hoje + timedelta(days=1)
    return Janela(_meia_noite_lisboa(hoje), _meia_noite_lisboa(amanha))


def janela_mes(agora: datetime) -> Janela:
    """[dia 1 do mês corrente às 00:00 Lisboa, agora) — mês até à data."""
    agora_lisboa = agora.astimezone(LISBON_TZ)
    inicio = agora_lisboa.date().replace(day=1)
    return Janela(_meia_noite_lisboa(inicio), agora.astimezone(timezone.utc))


def janela_ano(agora: datetime) -> Janela:
    """[1 de janeiro do ano corrente às 00:00 Lisboa, agora) — ano até à data."""
    agora_lisboa = agora.astimezone(LISBON_TZ)
    inicio = agora_lisboa.date().replace(month=1, day=1)
    return Janela(_meia_noite_lisboa(inicio), agora.astimezone(timezone.utc))


def janela_anterior_equivalente(inicio: datetime, fim: datetime, unidade: str) -> Janela:
    """Período equivalente do mês/ano anterior a um período que começa no dia 1.

    `unidade` é "mes" ou "ano" — indica se se recua um mês ou um ano; a partir
    só de (inicio, fim) não há como adivinhar isto sozinho: um período de
    1-13 de Janeiro é simultaneamente "início do mês" e "início do ano", e as
    duas respostas corretas (Dezembro anterior vs ano anterior) são
    diferentes. Por isso o chamador (janela_mes/janela_ano) diz qual quer.

    A regra é **o mesmo número de dias**, a contar também do dia 1, no
    mês/ano anterior — nunca o mês/ano anterior inteiro (o defeito do
    Vendus). Se o mês/ano anterior for mais curto (ex.: 31 dias de Maio
    contra Abril, que só tem 30), o período fica limitado a esse mês/ano
    anterior inteiro — nunca "transborda" para o seguinte.

    Aritmética por contagem de dias a partir do dia 1 (nunca `.replace(year=)`
    sobre uma data em concreto): assim um período que inclua 29 de Fevereiro
    nunca rebenta ao mapear para um ano não bissexto — desloca-se, em vez de
    dar erro.
    """
    if unidade not in ("mes", "ano"):
        raise ValueError("unidade tem de ser 'mes' ou 'ano', recebi: %r" % (unidade,))

    inicio_lisboa = inicio.astimezone(LISBON_TZ)
    fim_lisboa = fim.astimezone(LISBON_TZ)
    if inicio_lisboa.day != 1:
        raise ValueError(
            "janela_anterior_equivalente espera um período que comece no dia 1 "
            "do mês/ano — é o que janela_mes/janela_ano devolvem."
        )

    # Número de dias decorridos no período actual, contando o dia de "fim"
    # (tipicamente "agora", a meio do dia) como um dia inteiro.
    num_dias = (fim_lisboa.date() - inicio_lisboa.date()).days + 1

    if unidade == "mes":
        if inicio_lisboa.month == 1:
            ano_anterior, mes_anterior = inicio_lisboa.year - 1, 12
        else:
            ano_anterior, mes_anterior = inicio_lisboa.year, inicio_lisboa.month - 1
        inicio_anterior = date(ano_anterior, mes_anterior, 1)
        dias_no_periodo_anterior = calendar.monthrange(ano_anterior, mes_anterior)[1]
    else:  # unidade == "ano"
        ano_anterior = inicio_lisboa.year - 1
        inicio_anterior = date(ano_anterior, 1, 1)
        dias_no_periodo_anterior = 366 if calendar.isleap(ano_anterior) else 365

    dias_a_usar = min(num_dias, dias_no_periodo_anterior)
    fim_anterior = inicio_anterior + timedelta(days=dias_a_usar)

    return Janela(_meia_noite_lisboa(inicio_anterior), _meia_noite_lisboa(fim_anterior))


def variacao(actual: float, anterior: float) -> Optional[float]:
    """Percentagem de variação de `anterior` para `actual`.

    Devolve None se `anterior` for zero — sem período anterior para comparar
    não há percentagem que faça sentido; não se inventa um "-100%" nem um
    "+∞%" quando na verdade é "não havia nada para comparar".
    """
    if not anterior:
        return None
    return (actual - anterior) / anterior * 100


def _formata_dia(dia: date) -> str:
    return "%d de %s de %d" % (dia.day, _MESES_PT[dia.month - 1], dia.year)


def _ultimo_dia_incluido(fim_lisboa: datetime) -> date:
    """O `fim` de uma Janela é exclusivo. Se cair exactamente à meia-noite (um
    período fechado, ex.: um mês anterior completo), o último dia incluído é
    o dia anterior a essa meia-noite. Senão (o `fim` é "agora", a meio de um
    dia), esse próprio dia conta como incluído por inteiro na descrição — é o
    que se espera ler em "1–13 de agosto", não "1 a 12 e parte do 13"."""
    if fim_lisboa.time() == time(0, 0):
        return (fim_lisboa - timedelta(days=1)).date()
    return fim_lisboa.date()


def _formata_periodo(janela: Janela) -> str:
    inicio_lisboa = janela.inicio.astimezone(LISBON_TZ)
    fim_lisboa = janela.fim.astimezone(LISBON_TZ)
    primeiro = inicio_lisboa.date()
    ultimo = _ultimo_dia_incluido(fim_lisboa)

    if primeiro == ultimo:
        return _formata_dia(primeiro)
    if primeiro.year == ultimo.year and primeiro.month == ultimo.month:
        return "%d–%d de %s de %d" % (primeiro.day, ultimo.day, _MESES_PT[primeiro.month - 1], primeiro.year)
    return "%s – %s" % (_formata_dia(primeiro), _formata_dia(ultimo))


def descreve_comparacao(janela_actual: Janela, janela_anterior: Janela) -> str:
    """A frase que o ecrã mostra: diz por escrito o que foi comparado com o
    quê, para nunca deixar dúvidas do género "mensal comparado com o quê,
    exactamente?" — a pergunta que o dashboard do Vendus nunca respondia."""
    return "%s, comparado com %s" % (_formata_periodo(janela_actual), _formata_periodo(janela_anterior))
