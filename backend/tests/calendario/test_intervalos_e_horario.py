"""Horas, intervalos e o horário de cada loja num dia (desenho, secção 2, passo 1)."""
from datetime import date

import calendario

from . import dados_semana_normal as sn


def _loja(nome):
    return next(l for l in sn.semana_normal()["lojas"] if l["name"] == nome)


def test_horas_em_minutos_e_de_volta():
    assert calendario.minutos("11:30") == 690
    assert calendario.hhmm(690) == "11:30"
    assert calendario.hhmm(calendario.minutos("09:05")) == "09:05"


def test_horas_e_datas_como_se_escrevem_numa_mensagem():
    assert calendario.hora_curta("10:00") == "10h"
    assert calendario.hora_curta("11:30") == "11h30"
    assert calendario.data_curta("2026-10-21") == "21/10"
    assert calendario.primeiro_nome("Débora Ferreira") == "Débora"
    assert calendario.primeiro_nome("  ") == ""
    assert calendario.primeiro_nome(None) == ""


def test_unir_junta_sobrepostos_e_encostados_e_deita_fora_os_vazios():
    assert calendario.unir([(1000, 1100), (600, 840), (840, 900), (1050, 1200), (5, 5)]) == [(600, 900), (1000, 1200)]


def test_subtrair_da_os_buracos():
    alfragide = [(600, 1380)]
    assert calendario.subtrair(alfragide, [(840, 1380)]) == [(600, 840)]          # só a Emily
    assert calendario.subtrair(alfragide, [(600, 1140), (840, 1380)]) == []       # as duas
    assert calendario.subtrair([(780, 1320)], [(900, 1000)]) == [(780, 900), (1000, 1320)]
    assert calendario.subtrair([(780, 1320)], []) == [(780, 1320)]
    assert calendario.subtrair([(780, 1320)], [(0, 1439)]) == []


def test_recortar_ao_horario_e_encostar_nao_e_tocar():
    assert calendario.recortar((750, 1320), (780, 1320)) == (780, 1320)
    assert calendario.recortar((720, 780), (780, 1320)) is None
    assert calendario.recortar((480, 720), (780, 1320)) is None


def test_o_horario_geral():
    assert calendario.horario_do_dia(_loja("Oeiras"), date(2026, 10, 27)) == ("aberta", (780, 1320))
    assert calendario.horario_do_dia(_loja("Belém"), date(2026, 10, 31)) == ("aberta", (690, 1140))  # sábado


def test_a_excecao_de_domingo_de_belem():
    assert calendario.horario_do_dia(_loja("Belém"), date(2026, 11, 1)) == ("aberta", (690, 1200))


def test_belem_fecha_a_terca():
    assert calendario.horario_do_dia(_loja("Belém"), date(2026, 10, 27)) == ("fechada", None)


def test_benfica_antes_e_depois_de_abrir():
    assert calendario.horario_do_dia(_loja("Benfica"), date(2026, 10, 23)) == ("por_abrir", None)
    assert calendario.horario_do_dia(_loja("Benfica"), date(2026, 10, 24)) == ("aberta", (780, 1320))


def test_sem_horario_nao_entra_no_calendario():
    assert calendario.horario_do_dia(_loja("Pizzaria"), date(2026, 10, 27)) == ("sem_horario", None)
    assert calendario.horario_do_dia(None, date(2026, 10, 27)) == ("sem_horario", None)


def test_feriado_nao_fecha_a_loja():
    # 05/10 é feriado nacional e há lojas abertas (desenho, medido 5).
    assert calendario.horario_do_dia(_loja("Alfragide"), date(2026, 10, 5)) == ("aberta", (600, 1380))
