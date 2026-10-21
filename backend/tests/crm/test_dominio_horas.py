"""As horas da rota em segundos desde a meia-noite local (crm/dominio/horas.py), F3 / T3.2.

Plano F3 §1 ("Horas"): as horas contam-se em segundos desde a meia-noite
local, a partir do texto "HH:MM" (`h*3600 + m*60`), nunca a partir de
instantes UTC. Por isso não mudam nos dias de mudança de hora: "02:30" a
2026-03-29 (uma hora que não existe em Lisboa) conta pelo texto do relógio.

- `segundos("HH:MM")`, validada por `janelas.hora` (vazia → `ValueError`);
- `hora_de_segundos(s)`: o minuto arredondado meio-para-longe-do-zero
  (`numeros.arredondar`, nunca o `round` do Python); a partir das 24:00
  depois de arredondar → `None` (a chegada já é do dia seguinte);
- `minutos_de_segundos(s)`: a espera em minutos inteiros;
- `janelas_em_segundos(lista da base)`: `[]` → `None` (sem restrição);
- `janelas_vroom(janelas_s, servico_s)`: as janelas de início do serviço
  para o VROOM, `[a, b − s]`, só onde o serviço cabe (`b − s ≥ a`).
"""
import ast
import math
import random
from pathlib import Path

import pytest

import crm.dominio.horas as horas
from crm.dominio import janelas
from crm.dominio.horas import (
    hora_de_segundos,
    janelas_em_segundos,
    janelas_vroom,
    minutos_de_segundos,
    segundos,
)

FICHEIRO = Path(horas.__file__)


def _todas_as_horas():
    return [f"{h:02d}:{m:02d}" for h in range(24) for m in range(60)]


# --- segundos -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("08:00", 28800),
        ("00:00", 0),
        ("23:59", 86340),
        ("19:00", 68400),
        ("10:30", 37800),
        ("00:01", 60),
        ("01:00", 3600),
        ("12:34", 45240),
    ],
)
def test_segundos_desde_a_meia_noite(texto, esperado):
    assert segundos(texto) == esperado
    assert type(segundos(texto)) is int


def test_uma_hora_que_nao_existe_no_dia_da_mudanca_de_hora_conta_pelo_texto():
    """A 2026-03-29 os relógios de Lisboa saltam das 01:00 para as 02:00: "02:30"
    não existe nesse dia, mas a rota conta pelo texto do relógio."""
    assert segundos("02:30") == 9000
    assert segundos("01:30") == 5400


def test_segundos_e_a_conta_das_horas_e_dos_minutos_em_todas_as_horas_do_dia():
    for texto in _todas_as_horas():
        h, m = int(texto[:2]), int(texto[3:])
        assert segundos(texto) == h * 3600 + m * 60


@pytest.mark.parametrize(
    "texto",
    [
        "8:00", "", None, "24:00", "08:60", "08:0", "0800", " 08:00", "08:00 ", "08:00\n",
        "٠٨:٠٠", "０８:００", "08.00", "-1:00", "8h", "08:00:00",
        8, 8.0, True, False, ["08:00"], {"h": 8}, b"08:00",
    ],
)
def test_segundos_recusa_o_que_nao_e_uma_hora_hh_mm(texto):
    with pytest.raises(ValueError):
        segundos(texto)


def test_segundos_valida_pela_regra_das_janelas_da_loja():
    """As mesmas horas que a ficha aceita (`janelas.hora`), nem mais nem menos."""
    candidatos = _todas_as_horas() + ["24:00", "7:00", "07:5", "", "23:60", "99:99", "0:00"]
    for texto in candidatos:
        aceite = janelas.hora(texto) == (texto, None)
        if aceite:
            segundos(texto)
        else:
            with pytest.raises(ValueError):
                segundos(texto)


# --- hora_de_segundos -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "valor, esperado",
    [
        (30600, "08:30"),
        (0, "00:00"),
        (28800, "08:00"),
        (86340, "23:59"),
        (1770, "00:30"),  # 29,5 min → 30 (meio-para-longe-do-zero)
        (1769, "00:29"),
        (1830, "00:31"),  # 30,5 min → 31; o round do Python dava 30 (para o par)
        (1829, "00:30"),
        (29.9, "00:00"),
        (30, "00:01"),  # 0,5 min → 1
        (30600.0, "08:30"),
        (3570, "01:00"),  # 59,5 min → 60 → passa à hora seguinte
        (86369, "23:59"),  # 1439,48 min
        (86369.9, "23:59"),
    ],
)
def test_hora_de_segundos_arredonda_o_minuto_meio_para_longe_do_zero(valor, esperado):
    assert hora_de_segundos(valor) == esperado


def test_a_meia_do_minuto_vai_sempre_para_cima_tambem_nos_minutos_pares():
    """O caso que o `round` do Python (para o par) troca: os minutos pares + 30 s."""
    for minuto in range(0, 1439):
        assert hora_de_segundos(minuto * 60 + 30) == hora_de_segundos((minuto + 1) * 60)


@pytest.mark.parametrize("valor", [86370, 86370.0, 86399, 86400, 90000, 10**9, 2**63, 2**80])
def test_a_partir_das_24_00_depois_de_arredondar_nao_ha_hora(valor):
    """86 370 s = 1439,5 min → 1440 → "24:00": a chegada já é do dia seguinte."""
    assert hora_de_segundos(valor) is None


@pytest.mark.parametrize(
    "valor",
    [-1, -0.5, -29, -30, -60, -86400, math.nan, math.inf, -math.inf, True, False, None, "08:00", "30600", [30600]],
)
def test_hora_de_segundos_sem_hora_para_negativos_nao_finitos_e_o_que_nao_e_numero(valor):
    assert hora_de_segundos(valor) is None


def test_hora_de_segundos_e_o_inverso_de_segundos_em_todas_as_horas_do_dia():
    for texto in _todas_as_horas():
        assert hora_de_segundos(segundos(texto)) == texto


def test_hora_de_segundos_contra_a_conta_feita_a_mao_com_inteiros():
    """Propriedade com uma semente fixa: o minuto arredondado meio-para-cima,
    contado só com inteiros (s + 30) // 60, sem floats nem Decimal."""
    gerador = random.Random(20261011)
    for _ in range(3000):
        valor = gerador.randrange(0, 86400)
        minutos = (valor + 30) // 60
        esperado = None if minutos >= 1440 else f"{minutos // 60:02d}:{minutos % 60:02d}"
        assert hora_de_segundos(valor) == esperado, valor


# --- minutos_de_segundos ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "valor, esperado",
    [
        (89.9, 1),
        (0, 0),
        (0.0, 0),
        (29.9, 0),
        (30, 1),
        (90, 2),  # 1,5 min → 2
        (150, 3),  # 2,5 min → 3 (o round do Python dava 2)
        (3000, 50),
        (6600, 110),
        (7500, 125),
        (86400, 1440),
    ],
)
def test_minutos_de_segundos(valor, esperado):
    assert minutos_de_segundos(valor) == esperado
    assert type(minutos_de_segundos(valor)) is int


@pytest.mark.parametrize("valor", [-1, -0.5, math.nan, math.inf, True, False, None, "60", [60]])
def test_minutos_de_segundos_recusa_o_que_nao_e_uma_duracao(valor):
    with pytest.raises(ValueError):
        minutos_de_segundos(valor)


# --- janelas_em_segundos ----------------------------------------------------------------------


def test_sem_janelas_nao_ha_restricao():
    assert janelas_em_segundos([]) is None


def test_janelas_da_base_em_segundos():
    lista = [{"inicio": "10:00", "fim": "13:00"}, {"inicio": "15:00", "fim": "19:00"}]
    assert janelas_em_segundos(lista) == [(36000, 46800), (54000, 68400)]


def test_uma_so_janela():
    assert janelas_em_segundos([{"inicio": "08:30", "fim": "12:00"}]) == [(30600, 43200)]


def test_janelas_em_segundos_devolve_uma_lista_nova_e_nao_muda_a_da_base():
    lista = [{"inicio": "10:00", "fim": "13:00"}]
    copia = [dict(j) for j in lista]
    resultado = janelas_em_segundos(lista)
    assert lista == copia
    assert resultado is not lista
    assert janelas_em_segundos(lista) is not resultado


@pytest.mark.parametrize(
    "lista",
    [
        None,
        "10:00-13:00",
        [{"inicio": "13:00", "fim": "10:00"}],  # o fim antes do início
        [{"inicio": "10:00", "fim": "10:00"}],
        [{"inicio": "10:00"}],
        [{"inicio": "10:00", "fim": None}],
        [{"inicio": "10:00", "fim": "13:00", "extra": 1}],
        [{"inicio": "10:00", "fim": "13:00"}, {"inicio": "12:00", "fim": "19:00"}],  # sobrepostas
        [{"inicio": "15:00", "fim": "19:00"}, {"inicio": "10:00", "fim": "13:00"}],  # fora de ordem
        [{"inicio": "08:00", "fim": "09:00"}, {"inicio": "10:00", "fim": "11:00"}, {"inicio": "12:00", "fim": "13:00"}],
        [{"inicio": "8:00", "fim": "13:00"}],
        [["10:00", "13:00"]],
    ],
)
def test_janelas_em_segundos_so_aceita_o_que_a_base_guarda(lista):
    """As janelas gravadas passaram pelo `validador_loja.janelas_para_lista`:
    outra coisa é um erro de programação (`ValueError`), nunca uma janela inventada."""
    with pytest.raises(ValueError):
        janelas_em_segundos(lista)


# --- janelas_vroom ----------------------------------------------------------------------------


def test_sem_janelas_o_vroom_nao_recebe_restricao():
    assert janelas_vroom(None, 600) is None


def test_a_janela_do_vroom_e_a_do_inicio_do_servico():
    """O serviço tem de acabar dentro da janela: começa no máximo em b − s."""
    assert janelas_vroom([(36000, 46800)], 600) == [[36000, 46200]]


def test_duas_janelas():
    assert janelas_vroom([(36000, 46800), (54000, 68400)], 900) == [[36000, 45900], [54000, 67500]]


def test_uma_janela_mais_curta_do_que_o_servico_sai():
    assert janelas_vroom([(36000, 36300), (54000, 68400)], 600) == [[54000, 67800]]


def test_todas_as_janelas_curtas_demais_dao_uma_lista_vazia():
    """`[]` (nenhuma janela leva o serviço) é diferente de `None` (sem restrição):
    a paragem é impossível e não vai ao VROOM (T3.6)."""
    assert janelas_vroom([(36000, 36300), (54000, 54500)], 600) == []


def test_quando_o_servico_enche_a_janela_toda_fica_um_instante():
    """`b − s == a`: o serviço só cabe a começar mesmo à abertura."""
    assert janelas_vroom([(36000, 36600)], 600) == [[36000, 36000]]
    assert janelas_vroom([(36000, 36599)], 600) == []


def test_janelas_vroom_sem_servico():
    assert janelas_vroom([(36000, 46800)], 0) == [[36000, 46800]]


def test_janelas_vroom_devolve_listas_novas():
    entrada = [(36000, 46800)]
    primeira = janelas_vroom(entrada, 600)
    segunda = janelas_vroom(entrada, 600)
    assert primeira == segunda
    assert primeira is not segunda
    assert primeira[0] is not segunda[0]
    assert all(type(j) is list for j in primeira)
    assert entrada == [(36000, 46800)]


def test_janelas_vroom_devolve_inteiros():
    resultado = janelas_vroom(janelas_em_segundos([{"inicio": "10:00", "fim": "13:00"}]), 900)
    assert resultado == [[36000, 45900]]
    assert all(type(x) is int for janela in resultado for x in janela)


@pytest.mark.parametrize("servico", [-1, 600.0, True, None, "600", math.nan])
def test_janelas_vroom_recusa_um_servico_que_nao_e_um_inteiro_de_segundos(servico):
    with pytest.raises(ValueError):
        janelas_vroom([(36000, 46800)], servico)
    with pytest.raises(ValueError):
        janelas_vroom(None, servico)


@pytest.mark.parametrize(
    "janelas_s",
    [[(36000,)], [(36000, 46800, 1)], [("10:00", "13:00")], [(36000.0, 46800)], [(True, 46800)], "36000", [36000]],
)
def test_janelas_vroom_recusa_janelas_que_nao_sao_pares_de_segundos(janelas_s):
    with pytest.raises(ValueError):
        janelas_vroom(janelas_s, 600)


# --- O módulo nunca passa por instantes ----------------------------------------------------------


def _importacoes(codigo):
    nomes = set()
    for no in ast.walk(ast.parse(codigo)):
        if isinstance(no, ast.Import):
            nomes |= {alias.name.split(".")[0] for alias in no.names}
        elif isinstance(no, ast.ImportFrom) and no.module:
            nomes.add(no.module.split(".")[0])
    return nomes


def test_horas_nao_importa_datetime_nem_zoneinfo_nem_time():
    """As horas nunca passam por instantes (plano §1, risco R8)."""
    assert _importacoes(FICHEIRO.read_text(encoding="utf-8")) & {"datetime", "zoneinfo", "time", "pytz"} == set()


def test_o_varrimento_das_importacoes_ve_as_duas_formas():
    assert _importacoes("import datetime\nfrom zoneinfo import ZoneInfo\nimport time as t\n") == {"datetime", "zoneinfo", "time"}


def test_horas_nunca_chama_o_round_do_python():
    """O `round` arredonda para o par (1830 s → 00:30): usa-se `numeros.arredondar`."""
    chamadas = [
        no for no in ast.walk(ast.parse(FICHEIRO.read_text(encoding="utf-8")))
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Name) and no.func.id == "round"
    ]
    assert chamadas == []
