"""Janelas de tempo e comparação de períodos — puro, sem I/O, sem Mongo.

O defeito do Vendus que este módulo evita: no dia 13 de agosto o dashboard dele
comparava 13 dias de agosto com julho INTEIRO (31 dias), e dava "-64,31%"; e
comparava 225 dias de 2026 com o ano de 2025 inteiro (365 dias), e dava
"-28,76%" quando o negócio ia na verdade acima do ano anterior. Aqui a
comparação é sempre com o período equivalente — o mesmo número de dias, no
mês/ano anterior — nunca com o período inteiro.
"""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from faturacao.periodos import (
    descreve_comparacao,
    janela_ano,
    janela_anterior_equivalente,
    janela_hoje,
    janela_mes,
    janela_ontem_equivalente,
    variacao,
)

LISBOA = ZoneInfo("Europe/Lisbon")


def _agora(ano, mes, dia, hora=12, minuto=0):
    return datetime(ano, mes, dia, hora, minuto, tzinfo=LISBOA)


# --- janela_hoje -------------------------------------------------------------

def test_janela_hoje_vai_da_meia_noite_a_meia_noite_seguinte_em_lisboa():
    janela = janela_hoje(_agora(2026, 8, 13, 15, 32))
    assert janela.inicio.astimezone(LISBOA) == datetime(2026, 8, 13, 0, 0, tzinfo=LISBOA)
    assert janela.fim.astimezone(LISBOA) == datetime(2026, 8, 14, 0, 0, tzinfo=LISBOA)


def test_janela_hoje_no_dia_da_mudanca_da_hora_tem_23_horas():
    """No dia em que os relógios avançam (último domingo de março), o dia em
    Lisboa só tem 23 horas — 2026-03-29 é esse dia. Se o código somasse
    timedelta(hours=24) em vez de avançar a DATA e reconverter para UTC, este
    teste apanhava-o: dava meia-noite errada (01:00 em vez de 00:00 Lisboa)."""
    janela = janela_hoje(_agora(2026, 3, 29, 10, 0))
    assert janela.fim - janela.inicio == timedelta(hours=23)
    assert janela.inicio.astimezone(LISBOA) == datetime(2026, 3, 29, 0, 0, tzinfo=LISBOA)
    assert janela.fim.astimezone(LISBOA) == datetime(2026, 3, 30, 0, 0, tzinfo=LISBOA)


# --- janela_mes ----------------------------------------------------------------

def test_janela_mes_vai_do_dia_1_ate_agora():
    agora = _agora(2026, 8, 13, 15, 32)
    janela = janela_mes(agora)
    assert janela.inicio.astimezone(LISBOA) == datetime(2026, 8, 1, 0, 0, tzinfo=LISBOA)
    assert janela.fim == agora.astimezone(timezone.utc)


# --- janela_ano ------------------------------------------------------------

def test_janela_ano_vai_de_1_de_janeiro_ate_agora():
    agora = _agora(2026, 8, 13, 15, 32)
    janela = janela_ano(agora)
    assert janela.inicio.astimezone(LISBOA) == datetime(2026, 1, 1, 0, 0, tzinfo=LISBOA)
    assert janela.fim == agora.astimezone(timezone.utc)


# --- janela_anterior_equivalente — o coração da correção do Vendus --------
#
# `janela_anterior_equivalente` devolve um par (actual, anterior) — não só o
# anterior. Duas razões, C2 e I1 (ver dashboard-fix-report.md):
#
# C2: o período ACTUAL está quase sempre a meio (termina em "agora", a uma
# hora do dia) mas o ANTERIOR, se só se cortasse por DIAS inteiros, ficava
# sempre um dia inteiro mais "cheio" — 13 dias e meio de agosto contra 13
# dias INTEIROS de julho. A comparação só é justa se os dois terminarem à
# mesma hora do relógio (dia 13, às 09:30, dos dois lados).
#
# I1: quando o mês/ano anterior é mais curto (ex.: março, 31 dias, contra
# fevereiro, 28), encurtar só o anterior deixava o actual com dias a mais —
# "31 dias contra 28" a fingir-se "o mesmo período". Os dois lados encolhem
# juntos até ao comprimento do mais curto.

def test_mensal_13_de_agosto_as_09h30_compara_ate_a_mesma_hora_em_julho():
    """C2: às 09h30 de 13 de agosto, o mês só tem 12 dias e meio decorridos.
    Comparar com 1-13 de julho INTEIRO (julho às 00:00 do dia 14) é injusto
    — tem de ser 1-13 de julho, também só até às 09h30."""
    actual = janela_mes(_agora(2026, 8, 13, 9, 30))
    comparacao = janela_anterior_equivalente(actual.inicio, actual.fim, "mes")
    # actual não muda (o mês corrente nunca "transborda" — só o anterior é
    # que precisa de ser cortado à mesma hora).
    assert comparacao.actual == actual
    assert comparacao.anterior.inicio.astimezone(LISBOA) == datetime(2026, 7, 1, 0, 0, tzinfo=LISBOA)
    assert comparacao.anterior.fim.astimezone(LISBOA) == datetime(2026, 7, 13, 9, 30, tzinfo=LISBOA)


def test_anual_13_de_agosto_as_09h30_compara_ate_a_mesma_hora_no_ano_anterior():
    """O mesmo defeito (C2), na janela anual: 225 dias e um bocado de 2026
    contra os primeiros 225 dias INTEIROS de 2025 não é justo — tem de ser
    até às 09h30 de 13 de agosto de 2025 também."""
    actual = janela_ano(_agora(2026, 8, 13, 9, 30))
    comparacao = janela_anterior_equivalente(actual.inicio, actual.fim, "ano")
    assert comparacao.actual == actual
    assert comparacao.anterior.inicio.astimezone(LISBOA) == datetime(2025, 1, 1, 0, 0, tzinfo=LISBOA)
    assert comparacao.anterior.fim.astimezone(LISBOA) == datetime(2025, 8, 13, 9, 30, tzinfo=LISBOA)


def test_dia_1_do_mes_compara_com_a_mesma_hora_do_dia_1_do_mes_anterior():
    """C2 no caso extremo: dia 1 do mês, ainda por decorrer quase nada. Sem
    este corte, o anterior seria o dia 1 do mês passado INTEIRO (24h) contra
    umas horas do dia 1 deste mês — sempre '-100%' logo de manhã no dia 1."""
    actual = janela_mes(_agora(2026, 4, 1, 10, 0))
    comparacao = janela_anterior_equivalente(actual.inicio, actual.fim, "mes")
    assert comparacao.actual == actual
    assert comparacao.anterior.inicio.astimezone(LISBOA) == datetime(2026, 3, 1, 0, 0, tzinfo=LISBOA)
    assert comparacao.anterior.fim.astimezone(LISBOA) == datetime(2026, 3, 1, 10, 0, tzinfo=LISBOA)


def test_31_de_marco_trunca_tambem_o_actual_ao_comprimento_de_fevereiro():
    """I1: 31 de março (31 dias decorridos) contra fevereiro, que só tem 28.
    Encurtar só o anterior (fevereiro inteiro, 28 dias) contra o actual
    inteiro (31 dias de março) fabrica crescimento que não existe — os dois
    ficam em 1-28 (28 dias em cada lado), nunca 31 contra 28."""
    actual = janela_mes(_agora(2026, 3, 31, 18, 0))
    comparacao = janela_anterior_equivalente(actual.inicio, actual.fim, "mes")
    # actual TRUNCADO: já não vai até 31 de março, pára no dia 28.
    assert comparacao.actual.inicio.astimezone(LISBOA) == datetime(2026, 3, 1, 0, 0, tzinfo=LISBOA)
    assert comparacao.actual.fim.astimezone(LISBOA) == datetime(2026, 3, 29, 0, 0, tzinfo=LISBOA)
    # anterior: fevereiro inteiro (28 dias, é tudo o que ele tem).
    assert comparacao.anterior.inicio.astimezone(LISBOA) == datetime(2026, 2, 1, 0, 0, tzinfo=LISBOA)
    assert comparacao.anterior.fim.astimezone(LISBOA) == datetime(2026, 3, 1, 0, 0, tzinfo=LISBOA)
    # os dois lados têm exactamente o mesmo número de dias.
    dias_actual = (comparacao.actual.fim - comparacao.actual.inicio).days
    dias_anterior = (comparacao.anterior.fim - comparacao.anterior.inicio).days
    assert dias_actual == dias_anterior == 28


def test_mes_de_31_dias_fica_limitado_ao_anterior_de_30():
    """31 de maio (31 dias decorridos no mês): o mês anterior é abril, que só
    tem 30. O período equivalente não pode 'transbordar' para maio outra vez
    — fica em abril inteiro (30 dias), não avança para 1 de maio. E o actual
    (I1) fica também limitado a 1-30 de maio, não 1-31."""
    actual = janela_mes(_agora(2026, 5, 31, 23, 0))
    comparacao = janela_anterior_equivalente(actual.inicio, actual.fim, "mes")
    assert comparacao.actual.fim.astimezone(LISBOA) == datetime(2026, 5, 31, 0, 0, tzinfo=LISBOA)
    assert comparacao.anterior.inicio.astimezone(LISBOA) == datetime(2026, 4, 1, 0, 0, tzinfo=LISBOA)
    assert comparacao.anterior.fim.astimezone(LISBOA) == datetime(2026, 5, 1, 0, 0, tzinfo=LISBOA)


def test_ano_bissexto_nao_rebenta_a_comparar_com_ano_nao_bissexto():
    """2028 é bissexto; 2027 não. 1 de março de 2028, às 09:00 (60 dias
    inteiros decorridos desde 1 de Janeiro, contando o 29 de fevereiro) não
    pode rebentar a mapear para 2027 (um `.replace(year=)` ingénuo sobre
    29/02 rebentaria com ValueError se caísse exactamente nesse dia) —
    desloca-se para 2 de março de 2027 às 09:00, porque esse ano não teve 29
    de fevereiro para 'gastar' nesse 60º dia."""
    actual = janela_ano(_agora(2028, 3, 1, 9, 0))
    comparacao = janela_anterior_equivalente(actual.inicio, actual.fim, "ano")
    assert comparacao.anterior.inicio.astimezone(LISBOA) == datetime(2027, 1, 1, 0, 0, tzinfo=LISBOA)
    assert comparacao.anterior.fim.astimezone(LISBOA) == datetime(2027, 3, 2, 9, 0, tzinfo=LISBOA)


def test_janela_anterior_equivalente_recusa_unidade_desconhecida():
    janela = janela_mes(_agora(2026, 8, 13))
    with pytest.raises(ValueError):
        janela_anterior_equivalente(janela.inicio, janela.fim, "semana")


def test_janela_anterior_equivalente_exige_periodo_a_comecar_no_dia_1():
    inicio = _agora(2026, 8, 5).astimezone(timezone.utc)
    fim = _agora(2026, 8, 13).astimezone(timezone.utc)
    with pytest.raises(ValueError):
        janela_anterior_equivalente(inicio, fim, "mes")


# --- janela_ontem_equivalente — o mesmo defeito (C2) no cartão "Hoje" ------

def test_ontem_as_09h30_vai_so_ate_as_09h30_de_ontem_nao_o_dia_inteiro():
    """C2, cartão Hoje: às 09h30, 'ontem' não pode ser o dia inteiro (24h) —
    tem de ser só até às 09h30 de ontem, a mesma fatia de tempo que 'hoje'
    já teve para acumular vendas."""
    janela = janela_ontem_equivalente(_agora(2026, 8, 13, 9, 30))
    assert janela.inicio.astimezone(LISBOA) == datetime(2026, 8, 12, 0, 0, tzinfo=LISBOA)
    assert janela.fim.astimezone(LISBOA) == datetime(2026, 8, 12, 9, 30, tzinfo=LISBOA)


def test_ontem_a_meia_noite_e_uma_janela_vazia():
    """Um caso degenerado mas coerente: mesmo à meia-noite exacta (zero
    tempo decorrido hoje), a janela de 'ontem' fica vazia (mesmo início e
    fim) — nunca um dia inteiro."""
    janela = janela_ontem_equivalente(_agora(2026, 8, 13, 0, 0))
    assert janela.inicio == janela.fim
    assert janela.inicio.astimezone(LISBOA) == datetime(2026, 8, 12, 0, 0, tzinfo=LISBOA)


# --- variacao ------------------------------------------------------------------

def test_variacao_positiva():
    assert variacao(150, 100) == 50.0


def test_variacao_negativa():
    assert variacao(50, 100) == -50.0


def test_variacao_com_anterior_zero_devolve_none():
    """Não se inventa um '-100%': sem período anterior para comparar (zero),
    não há percentagem que faça sentido."""
    assert variacao(100, 0) is None
    assert variacao(0, 0) is None


def test_variacao_actual_acima_do_anterior_apesar_do_vendus_dizer_negativo():
    """O caso real: ~334k no ano anterior (até 13/08) contra 385761 este ano
    — 15% acima, não "-28,76%" como o Vendus mostrava ao comparar com o ano
    inteiro."""
    v = variacao(385761, 334000)
    assert v > 0
    assert round(v, 0) == 15


def test_variacao_com_anterior_negativo_mostra_crescimento_como_positivo():
    """M3: de um período com -50€ (mais notas de crédito do que vendas) para
    +100€ é uma melhoria enorme — tem de dar um número POSITIVO. A fórmula
    directa ((100-(-50))/-50*100 = -300%) inverte o sinal e mostra uma
    queda; isso é o defeito a corrigir."""
    assert variacao(100, -50) > 0


def test_variacao_com_anterior_negativo_que_piora_mostra_queda():
    """De -50€ para -100€ (a perda duplicou) é uma piora — tem de continuar
    negativo, não inverter para positivo só porque o anterior era negativo."""
    assert variacao(-100, -50) < 0


def test_variacao_com_anterior_negativo_que_melhora_mas_continua_negativo():
    """De -50€ para -25€ (a perda encolheu para metade) é uma melhoria, mas
    o resultado continua negativo (-25€) — tem de dar positivo (melhorou),
    não confundir com "ainda pior"."""
    assert variacao(-25, -50) == 50.0


# --- descreve_comparacao ---------------------------------------------------
#
# C2: quando a comparação foi cortada a meio de um dia (não à meia-noite), a
# frase tem de o dizer — senão "1–13 de agosto, comparado com 1–13 de julho"
# lê-se como dois períodos completos, quando na verdade os dois pararam às
# 09:30. Quando o corte é à meia-noite exacta (período fechado — ex.: depois
# do truncamento de I1), não há nada de parcial a assinalar.

def test_descreve_comparacao_mensal_diz_por_escrito_o_que_comparou():
    actual = janela_mes(_agora(2026, 8, 13, 15, 32))
    comparacao = janela_anterior_equivalente(actual.inicio, actual.fim, "mes")
    frase = descreve_comparacao(comparacao.actual, comparacao.anterior)
    assert frase == "1–13 de agosto de 2026, comparado com 1–13 de julho de 2026, até às 15:32"


def test_descreve_comparacao_periodo_que_atravessa_meses_usa_datas_completas():
    actual = janela_ano(_agora(2026, 8, 13, 15, 32))
    comparacao = janela_anterior_equivalente(actual.inicio, actual.fim, "ano")
    frase = descreve_comparacao(comparacao.actual, comparacao.anterior)
    assert "1 de janeiro de 2026" in frase
    assert "13 de agosto de 2026" in frase
    assert "1 de janeiro de 2025" in frase
    assert "13 de agosto de 2025" in frase
    assert "até às 15:32" in frase


def test_descreve_comparacao_um_so_dia():
    janela = janela_hoje(_agora(2026, 8, 13, 15, 32))
    anterior = janela_hoje(_agora(2026, 8, 12, 15, 32))
    frase = descreve_comparacao(janela, anterior)
    assert frase == "13 de agosto de 2026, comparado com 12 de agosto de 2026"


def test_descreve_comparacao_hoje_vs_ontem_equivalente_mostra_a_hora_do_corte():
    """O caso real do cartão Hoje: 'hoje' é sempre o dia inteiro (rótulo),
    mas 'ontem' foi cortado às 09:30 (C2) — a frase tem de avisar disso,
    senão parece uma comparação entre dois dias completos."""
    agora = _agora(2026, 8, 13, 9, 30)
    hoje = janela_hoje(agora)
    ontem = janela_ontem_equivalente(agora)
    frase = descreve_comparacao(hoje, ontem)
    assert frase == "13 de agosto de 2026, comparado com 12 de agosto de 2026, até às 09:30"


def test_descreve_comparacao_periodo_ja_fechado_nao_mostra_hora():
    """Quando os dois lados terminam exactamente à meia-noite (aqui, depois
    do truncamento de I1 — 31 de março contra fevereiro, que é mais curto),
    não faz sentido dizer 'até às 00:00': o período está completo, sem corte
    de relógio nenhum a assinalar — só a compressão de dias, que já está no
    próprio intervalo de datas."""
    actual = janela_mes(_agora(2026, 3, 31, 18, 0))
    comparacao = janela_anterior_equivalente(actual.inicio, actual.fim, "mes")
    frase = descreve_comparacao(comparacao.actual, comparacao.anterior)
    assert "até às" not in frase
    assert frase == "1–28 de março de 2026, comparado com 1–28 de fevereiro de 2026"
