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

Um segundo defeito do Vendus, mais subtil, que este módulo também evita: ele
comparava um período EM CURSO (hoje, o mês corrente) com um período anterior
COMPLETO (ontem inteiro, o mês passado inteiro) — às 9 da manhã, "hoje" só
tinha uma fatia de vendas, "ontem" tinha o dia inteiro, e a diferença parecia
uma queda de vendas que nunca existiu. Aqui, o período anterior termina
sempre ao MESMO TEMPO DECORRIDO que o actual — o mesmo dia relativo, à mesma
hora do relógio — nunca um dia/mês/ano anterior inteiro só porque calha de
estar fechado.
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

# O par que `janela_anterior_equivalente` devolve: o período ACTUAL (por
# vezes encurtado — ver essa função) e o período ANTERIOR equivalente. Os
# dois viajam sempre juntos porque nascem do mesmo cálculo — nunca se deve
# reconstruir um dos dois lados por conta própria (arrisca divergir do
# outro).
Comparacao = namedtuple("Comparacao", ["actual", "anterior"])

_MESES_PT = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]


def _combina(dia: date, hora: time = time(0, 0)) -> datetime:
    """Junta uma DATA e uma HORA-do-dia (Lisboa) num instante UTC.

    Construído a partir dos componentes (nunca com aritmética de timedelta
    sobre um instante UTC/aware já resolvido), para que o dia da mudança de
    hora — que em Lisboa só tem 23 horas — dê sempre a hora de relógio certa
    em vez de ficar deslocado. `timedelta` sobre um datetime aware desloca a
    hora local quando atravessa uma fronteira de DST; construir a partir de
    (ano, mês, dia, hora) não — o `zoneinfo` resolve o offset certo para
    ESSA data em concreto.
    """
    return datetime(
        dia.year, dia.month, dia.day,
        hora.hour, hora.minute, hora.second, hora.microsecond,
        tzinfo=LISBON_TZ,
    ).astimezone(timezone.utc)


def _meia_noite_lisboa(dia: date) -> datetime:
    """Meia-noite (00:00) em Lisboa do dia dado, devolvida em UTC."""
    return _combina(dia)


def janela_de_datas(de: date, ate: date) -> Janela:
    """A janela [inicio, fim) em UTC de um intervalo escolhido à mão — de
    meia-noite de `de` a meia-noite do dia SEGUINTE a `ate`, hora de Lisboa.

    O `ate` é INCLUSIVO para quem escolhe (escolher "1 a 25" quer dizer o dia
    25 inteiro) e o `fim` continua exclusivo para quem filtra, que é a
    convenção deste módulo. Somar um dia à data — e não 24 horas ao instante —
    é o que faz isto continuar certo no dia da mudança da hora, que em Lisboa
    só tem 23.
    """
    if ate < de:
        raise ValueError("A data final é anterior à inicial.")
    return Janela(_meia_noite_lisboa(de), _meia_noite_lisboa(ate + timedelta(days=1)))


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


def janela_ontem_equivalente(agora: datetime) -> Janela:
    """[meia-noite de ontem, a mesma hora de ontem que "agora" é hoje) —
    NUNCA ontem inteiro (24h).

    O cartão "Hoje" compara sempre um dia em curso (só algumas horas de
    vendas) com "ontem". Se "ontem" fosse o dia completo (como janela_hoje
    devolveria), a comparação seria sempre injusta: poucas horas contra 24 —
    e mostraria uma queda enorme todas as manhãs, mesmo num negócio
    perfeitamente estável. Aqui "ontem" pára à mesma hora do relógio a que
    "hoje" ainda vai.
    """
    agora_lisboa = agora.astimezone(LISBON_TZ)
    ontem = agora_lisboa.date() - timedelta(days=1)
    hora_actual = agora_lisboa.timetz().replace(tzinfo=None)
    return Janela(_meia_noite_lisboa(ontem), _combina(ontem, hora_actual))


def janela_anterior_equivalente(inicio: datetime, fim: datetime, unidade: str) -> Comparacao:
    """Compara um período [inicio, fim) que começa no dia 1 do mês/ano com o
    período equivalente do mês/ano anterior. Devolve um `Comparacao(actual,
    anterior)` — os DOIS lados, porque por vezes o `actual` também precisa
    de ser encurtado (ver I1 abaixo). `unidade` é "mes" ou "ano" — indica se
    se recua um mês ou um ano; a partir só de (inicio, fim) não há como
    adivinhar isto sozinho: um período de 1-13 de Janeiro é simultaneamente
    "início do mês" e "início do ano", e as duas respostas corretas
    (Dezembro anterior vs ano anterior) são diferentes. Por isso o chamador
    (janela_mes/janela_ano) diz qual quer.

    Dois defeitos do Vendus evitados aqui, não só um:

    1. Comparar com o mês/ano anterior INTEIRO em vez do mesmo número de
       dias (ex.: 13 dias de Agosto contra Julho inteiro). Aqui é sempre o
       mesmo número de dias, a contar do dia 1.

    2. Comparar um período em curso (termina "agora", a meio de um dia) com
       um anterior fechado por DIAS inteiros (termina à meia-noite). 12 dias
       e meio de Agosto contra 13 dias INTEIROS de Julho ainda é injusto,
       mesmo com "o mesmo número de dias" arredondado para cima. Aqui o
       anterior termina à MESMA HORA do relógio que o actual — dia 13, às
       09:30, dos dois lados.

    E, quando o mês/ano anterior é mais curto que o actual (ex.: Março, 31
    dias, contra Fevereiro, 28) — encurtar só o anterior deixaria o actual
    com dias a mais, fabricando crescimento que não existe. Os dois lados
    encolhem juntos até ao comprimento do mais curto, em dias inteiros (sem
    hora parcial: o corte aqui é do calendário, não do relógio).

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

    # Dias INTEIROS já decorridos (sem contar um último dia parcial) e a
    # hora-do-dia em que o período corta nesse último dia — 00:00 se "fim"
    # cair mesmo à meia-noite (período fechado, sem dia parcial nenhum).
    dias_completos = (fim_lisboa.date() - inicio_lisboa.date()).days
    hora_corte = fim_lisboa.timetz().replace(tzinfo=None)

    # Dias de calendário "tocados" pelo período — os inteiros, mais um se o
    # último ainda estiver a meio (mesmo parcial, esse dia já teve vendas
    # dele próprio, por isso conta para ver se cabe no mês/ano anterior).
    dias_tocados = dias_completos + (0 if hora_corte == time(0, 0) else 1)

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

    if dias_tocados > dias_no_periodo_anterior:
        # O mês/ano anterior é mais curto: os dois lados ficam limitados ao
        # comprimento dele, em dias inteiros — nunca só o anterior (era esse
        # o defeito: "31 dias de Março contra 28 de Fevereiro" a fingir-se
        # "o mesmo período").
        dias_finais = dias_no_periodo_anterior
        hora_final = time(0, 0)
    else:
        dias_finais = dias_completos
        hora_final = hora_corte

    fim_actual = _combina(inicio_lisboa.date() + timedelta(days=dias_finais), hora_final)
    fim_anterior = _combina(inicio_anterior + timedelta(days=dias_finais), hora_final)

    return Comparacao(
        Janela(inicio, fim_actual),
        Janela(_meia_noite_lisboa(inicio_anterior), fim_anterior),
    )


def variacao(actual: float, anterior: float) -> Optional[float]:
    """Percentagem de variação de `anterior` para `actual`.

    Devolve None se `anterior` for zero — sem período anterior para comparar
    não há percentagem que faça sentido; não se inventa um "-100%" nem um
    "+∞%" quando na verdade é "não havia nada para comparar".

    O denominador é `abs(anterior)`, não `anterior` — com um anterior
    NEGATIVO (mais notas de crédito do que vendas nesse período), a fórmula
    directa inverte o sinal: variacao(100, -50) daria "-300%" para uma
    melhoria enorme (de -50€ para +100€). Com abs(), o sinal do resultado
    segue sempre o sentido real da variação (melhorou → positivo, piorou →
    negativo), mesmo quando se atravessa o zero.
    """
    if not anterior:
        return None
    return (actual - anterior) / abs(anterior) * 100


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


def hora_de_corte(janela_actual: Janela, janela_anterior: Janela) -> Optional[time]:
    """A hora (Lisboa) em que a comparação foi cortada a meio de um dia — ou
    None se os dois lados terminarem exactamente à meia-noite (período
    fechado, sem corte de relógio nenhum a assinalar — só o intervalo de
    datas, que já fala por si).

    Em condições normais os dois lados de uma `Comparacao` terminam à mesma
    hora (é o que janela_anterior_equivalente garante — C2); no caso do
    cartão "Hoje" só o lado anterior ("ontem", via janela_ontem_equivalente)
    é que fica cortado — "hoje" continua a ser o dia inteiro como rótulo.
    Por isso procura-se nos dois lados, não só num."""
    for janela in (janela_anterior, janela_actual):
        hora = janela.fim.astimezone(LISBON_TZ).time()
        if hora != time(0, 0):
            return hora
    return None


def descreve_comparacao(janela_actual: Janela, janela_anterior: Janela) -> str:
    """A frase que o ecrã mostra: diz por escrito o que foi comparado com o
    quê, para nunca deixar dúvidas do género "mensal comparado com o quê,
    exactamente?" — a pergunta que o dashboard do Vendus nunca respondia.

    Quando a comparação foi cortada a meio de um dia (C2 — ex.: às 09:30),
    a frase acrescenta "até às HH:MM": sem isso, "1–13 de agosto, comparado
    com 1–13 de julho" lê-se como dois períodos completos, quando na
    verdade os dois pararam a meio do dia 13."""
    frase = "%s, comparado com %s" % (_formata_periodo(janela_actual), _formata_periodo(janela_anterior))
    hora_corte = hora_de_corte(janela_actual, janela_anterior)
    if hora_corte is not None:
        frase += ", até às %02d:%02d" % (hora_corte.hour, hora_corte.minute)
    return frase
