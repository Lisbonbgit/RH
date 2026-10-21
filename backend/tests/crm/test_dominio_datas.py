"""As datas das rotas `AAAA-MM-DD` (crm/dominio/datas.py), F3 / T3.1.

Uma rota por dia: `crm_rotas.data` é o dia em Lisboa como texto
`AAAA-MM-DD` (plano F3 §1 "Uma rota por dia" e "Datas e fecho simples"). O
texto tem largura fixa, por isso ordena como as datas (o `GET /rotas?de=&ate=`
filtra com `$gte`/`$lte` sobre ele). O dia chega no caminho e nos parâmetros
como texto e lê-se aqui: só algarismos ASCII (`[0-9]`, nunca `\\d`), com
`fullmatch` (o `$` e o `match` aceitavam um "\\n" final) e uma data que exista.
Nunca `fromisoformat` (no Python 3.11 aceita "20261012"), `strftime` nem
`isoformat` (o varrimento do test_instantes_gravados.py).
"""
import ast
import random
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

import crm.dominio.datas as datas
from crm.dominio.campos_loja import DIAS
from crm.dominio.datas import MAXIMO_DIAS_FUTURO, dia_da_semana, ler_data, somar_dias, texto_data

FORMATO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _dia_aleatorio(gerador):
    return date(1, 1, 1) + timedelta(days=gerador.randrange((date(9999, 12, 31) - date(1, 1, 1)).days + 1))


# --- ler_data ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "texto, dia",
    [("2026-10-12", date(2026, 10, 12)), ("2028-02-29", date(2028, 2, 29)), ("2026-01-05", date(2026, 1, 5)),
     ("2026-12-31", date(2026, 12, 31)), ("0001-01-01", date(1, 1, 1)), ("9999-12-31", date(9999, 12, 31)),
     ("2000-02-29", date(2000, 2, 29))],
    ids=["um dia qualquer", "29 de fevereiro num ano bissexto", "mês e dia com zero à esquerda", "o fim do ano",
         "o primeiro dia que existe", "o último dia que existe", "29 de fevereiro de 2000 (múltiplo de 400)"],
)
def test_ler_data_aceita_um_dia_que_existe(texto, dia):
    lido = ler_data(texto)
    assert lido == dia
    assert type(lido) is date


@pytest.mark.parametrize(
    "valor",
    [
        # os do plano (T3.1)
        "2026-02-29", "2026-13-01", "2026-1-5", "20261012", " 2026-10-12", "2026-10-12\n", "２０２６-10-12",
        "٢٠٢٦-10-12", "0000-01-01", None, 20261012, True, ["2026-10-12"],
        # mais armadilhas
        "", "2026-10-12 ", "2026-10-1٢", "2026-١٠-12", "2026-00-10", "2026-10-00", "2026-10-32", "2026-04-31",
        "1900-02-29", "2026/10/12", "12-10-2026", "2026-10-12T00:00:00Z", "+2026-10-12", "-2026-10-12",
        "12026-10-12", "2026-10-012", "2026-10-12\x00", "2026_10_12", "2026-W42-1", False, 2026.10,
        {"$gt": ""}, b"2026-10-12", date(2026, 10, 12),
    ],
    ids=[
        "29 de fevereiro num ano comum", "mês 13", "mês e dia com um algarismo", "sem hífenes", "espaço no início",
        "mudança de linha no fim", "algarismos de largura total", "algarismos árabes no ano", "ano zero", "null",
        "um número", "verdadeiro", "uma lista",
        "vazio", "espaço no fim", "um algarismo árabe no dia", "algarismos árabes no mês", "mês 0", "dia 0",
        "dia 32", "31 de abril", "29 de fevereiro de 1900 (múltiplo de 100)", "com barras", "dia-mês-ano",
        "um instante", "sinal de mais", "ano negativo", "ano com cinco algarismos", "dia com três algarismos",
        "NUL no fim", "sublinhados", "semana ISO", "falso", "um número com casas", "um operador do Mongo", "bytes",
        "uma date do Python (a API só traz texto)",
    ],
)
def test_ler_data_recusa_o_que_nao_e_um_dia_aaaa_mm_dd(valor):
    assert ler_data(valor) is None


# --- texto_data ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dia, texto",
    [(date(2026, 1, 5), "2026-01-05"), (date(2026, 10, 12), "2026-10-12"), (date(999, 1, 2), "0999-01-02"),
     (date(1, 1, 1), "0001-01-01"), (date(9999, 12, 31), "9999-12-31")],
    ids=["zeros à esquerda no mês e no dia", "sem zeros", "antes do ano mil", "o primeiro dia", "o último dia"],
)
def test_texto_data_escreve_aaaa_mm_dd_com_largura_fixa(dia, texto):
    assert texto_data(dia) == texto


def test_a_ida_e_volta_entre_o_dia_e_o_texto_e_sem_perda():
    assert ler_data(texto_data(date(2026, 1, 5))) == date(2026, 1, 5)
    assert texto_data(ler_data("2026-01-05")) == "2026-01-05"
    gerador = random.Random(31)
    for _ in range(3000):
        dia = _dia_aleatorio(gerador)
        texto = texto_data(dia)
        assert FORMATO.fullmatch(texto)
        assert ler_data(texto) == dia
        assert texto_data(ler_data(texto)) == texto


def test_o_texto_das_datas_ordena_como_as_datas():
    """O `GET /rotas?de=&ate=` filtra `data` com `$gte`/`$lte`: o Mongo
    compara o texto por caracteres, e a largura fixa faz essa ordem igual à
    das datas, também entre anos com menos algarismos."""
    gerador = random.Random(1012)
    dias = [_dia_aleatorio(gerador) for _ in range(3000)]
    dias += [date(999, 12, 31), date(1000, 1, 1), date(2026, 9, 30), date(2026, 10, 1)]
    assert sorted(dias, key=texto_data) == sorted(dias)


# --- dia_da_semana -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dia, nome",
    [(date(2026, 10, 12), "seg"), (date(2026, 10, 13), "ter"), (date(2026, 10, 14), "qua"),
     (date(2026, 10, 15), "qui"), (date(2026, 10, 16), "sex"), (date(2026, 10, 17), "sab"),
     (date(2026, 10, 18), "dom")],
    ids=["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"],
)
def test_dia_da_semana_usa_os_nomes_dos_dias_fechados_da_loja(dia, nome):
    assert dia_da_semana(dia) == nome


def test_dia_da_semana_percorre_os_dias_da_loja_pela_ordem():
    # Os mesmos nomes de `dias_fechada` (campos_loja.DIAS): é com eles que a
    # paragem fica "⚠️ Fechada neste dia".
    segunda = date(2026, 10, 12)
    assert [dia_da_semana(somar_dias(segunda, i)) for i in range(7)] == list(DIAS)
    gerador = random.Random(7)
    for _ in range(2000):
        dia = _dia_aleatorio(gerador)
        if dia > date(9999, 12, 24):
            continue
        assert dia_da_semana(dia) in DIAS
        assert dia_da_semana(somar_dias(dia, 7)) == dia_da_semana(dia)
        seguinte = DIAS[(DIAS.index(dia_da_semana(dia)) + 1) % 7]
        assert dia_da_semana(somar_dias(dia, 1)) == seguinte


def test_dia_da_semana_nos_dias_em_que_a_hora_muda():
    assert dia_da_semana(date(2026, 3, 29)) == "dom"
    assert dia_da_semana(date(2026, 10, 25)) == "dom"
    assert dia_da_semana(date(2028, 2, 29)) == "ter"


# --- somar_dias ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dia, n, resultado",
    [(date(2026, 10, 30), 3, date(2026, 11, 2)), (date(2026, 10, 11), 0, date(2026, 10, 11)),
     (date(2026, 10, 11), -14, date(2026, 9, 27)), (date(2026, 10, 11), 60, date(2026, 12, 10)),
     (date(2026, 12, 31), 1, date(2027, 1, 1)), (date(2028, 2, 28), 1, date(2028, 2, 29)),
     (date(2026, 10, 11), 365, date(2027, 10, 11)), (date(2026, 3, 28), 2, date(2026, 3, 30))],
    ids=["muda de mês", "zero dias", "para trás (o de do GET /rotas)", "para a frente (o ate do GET /rotas)",
         "muda de ano", "chega a 29 de fevereiro", "um ano (o máximo no futuro)", "atravessa a mudança de hora"],
)
def test_somar_dias_conta_dias_de_calendario(dia, n, resultado):
    somado = somar_dias(dia, n)
    assert somado == resultado
    assert type(somado) is date


def test_somar_dias_nao_muda_o_dia_recebido():
    dia = date(2026, 10, 30)
    somar_dias(dia, 3)
    assert dia == date(2026, 10, 30)


# --- MAXIMO_DIAS_FUTURO ----------------------------------------------------------------------


def test_nao_se_planeia_a_mais_de_um_ano():
    assert MAXIMO_DIAS_FUTURO == 365
    assert type(MAXIMO_DIAS_FUTURO) is int


# --- o módulo não formata nem lê datas pelas funções do Python --------------------------------


def test_o_modulo_nao_usa_fromisoformat_strptime_strftime_nem_isoformat():
    codigo = Path(datas.__file__).read_text(encoding="utf-8")
    proibidos = {"fromisoformat", "strptime", "strftime", "isoformat", "today", "now"}
    usados = sorted(
        (no.lineno, no.attr) for no in ast.walk(ast.parse(codigo)) if isinstance(no, ast.Attribute) and no.attr in proibidos
    )
    assert usados == []
