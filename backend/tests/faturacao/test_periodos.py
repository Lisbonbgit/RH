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

def test_mensal_compara_13_dias_de_agosto_com_13_dias_de_julho_nao_o_mes_inteiro():
    """O defeito do Vendus: 13 dias de agosto contra julho INTEIRO (31 dias).
    Aqui tem de ser 1-13 de julho — o mesmo número de dias, não os 31."""
    actual = janela_mes(_agora(2026, 8, 13, 15, 32))
    anterior = janela_anterior_equivalente(actual.inicio, actual.fim, "mes")
    assert anterior.inicio.astimezone(LISBOA) == datetime(2026, 7, 1, 0, 0, tzinfo=LISBOA)
    # fim é exclusivo: 14/07 00:00 cobre exactamente os dias 1 a 13 de julho.
    assert anterior.fim.astimezone(LISBOA) == datetime(2026, 7, 14, 0, 0, tzinfo=LISBOA)


def test_anual_compara_com_o_mesmo_numero_de_dias_do_ano_anterior_nao_o_ano_inteiro():
    """13 de agosto: 225 dias de 2026 contra os primeiros 225 dias de 2025 —
    que também terminam a 13 de agosto (2025 não é bissexto) — não os 365
    dias inteiros do ano anterior."""
    actual = janela_ano(_agora(2026, 8, 13, 15, 32))
    anterior = janela_anterior_equivalente(actual.inicio, actual.fim, "ano")
    assert anterior.inicio.astimezone(LISBOA) == datetime(2025, 1, 1, 0, 0, tzinfo=LISBOA)
    # fim é exclusivo: 14/08/2025 00:00 cobre exactamente 1-13 de agosto de 2025.
    assert anterior.fim.astimezone(LISBOA) == datetime(2025, 8, 14, 0, 0, tzinfo=LISBOA)


def test_mes_de_31_dias_fica_limitado_ao_anterior_de_30():
    """31 de maio (31 dias decorridos no mês): o mês anterior é abril, que só
    tem 30. O período equivalente não pode 'transbordar' para maio outra vez
    — fica em abril inteiro (30 dias), não avança para 1 de maio."""
    actual = janela_mes(_agora(2026, 5, 31, 23, 0))
    anterior = janela_anterior_equivalente(actual.inicio, actual.fim, "mes")
    assert anterior.inicio.astimezone(LISBOA) == datetime(2026, 4, 1, 0, 0, tzinfo=LISBOA)
    assert anterior.fim.astimezone(LISBOA) == datetime(2026, 5, 1, 0, 0, tzinfo=LISBOA)


def test_ano_bissexto_nao_rebenta_a_comparar_com_ano_nao_bissexto():
    """2028 é bissexto; 2027 não. O dia 61 de 2028 (1 de março, contando o 29
    de fevereiro) não pode rebentar a mapear para 2027 (um `.replace(year=)`
    ingénuo sobre 29/02 rebentaria com ValueError se caísse exactamente nesse
    dia) — e cai a 3 de março de 2027, porque esse ano não teve 29 de
    fevereiro para 'gastar' nesse dia 61."""
    actual = janela_ano(_agora(2028, 3, 1, 9, 0))
    anterior = janela_anterior_equivalente(actual.inicio, actual.fim, "ano")
    assert anterior.inicio.astimezone(LISBOA) == datetime(2027, 1, 1, 0, 0, tzinfo=LISBOA)
    assert anterior.fim.astimezone(LISBOA) == datetime(2027, 3, 3, 0, 0, tzinfo=LISBOA)


def test_janela_anterior_equivalente_recusa_unidade_desconhecida():
    janela = janela_mes(_agora(2026, 8, 13))
    with pytest.raises(ValueError):
        janela_anterior_equivalente(janela.inicio, janela.fim, "semana")


def test_janela_anterior_equivalente_exige_periodo_a_comecar_no_dia_1():
    inicio = _agora(2026, 8, 5).astimezone(timezone.utc)
    fim = _agora(2026, 8, 13).astimezone(timezone.utc)
    with pytest.raises(ValueError):
        janela_anterior_equivalente(inicio, fim, "mes")


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


# --- descreve_comparacao ---------------------------------------------------

def test_descreve_comparacao_mensal_diz_por_escrito_o_que_comparou():
    actual = janela_mes(_agora(2026, 8, 13, 15, 32))
    anterior = janela_anterior_equivalente(actual.inicio, actual.fim, "mes")
    frase = descreve_comparacao(actual, anterior)
    assert frase == "1–13 de agosto de 2026, comparado com 1–13 de julho de 2026"


def test_descreve_comparacao_periodo_que_atravessa_meses_usa_datas_completas():
    actual = janela_ano(_agora(2026, 8, 13, 15, 32))
    anterior = janela_anterior_equivalente(actual.inicio, actual.fim, "ano")
    frase = descreve_comparacao(actual, anterior)
    assert "1 de janeiro de 2026" in frase
    assert "13 de agosto de 2026" in frase
    assert "1 de janeiro de 2025" in frase
    assert "13 de agosto de 2025" in frase


def test_descreve_comparacao_um_so_dia():
    janela = janela_hoje(_agora(2026, 8, 13, 15, 32))
    anterior = janela_hoje(_agora(2026, 8, 12, 15, 32))
    frase = descreve_comparacao(janela, anterior)
    assert frase == "13 de agosto de 2026, comparado com 12 de agosto de 2026"
