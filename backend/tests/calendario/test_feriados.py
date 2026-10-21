"""Feriados com nome (desenho, secção 2, «Feriados do dia», e Testes 5).

Os nacionais vêm de um dicionário construído à parte; o `server.get_pt_holidays`, que o
saldo de férias usa, continua a dar o mesmo `set` e a cache dele não é tocada.
"""
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")
os.environ.setdefault("JWT_SECRET", "segredo-de-teste")
os.environ.setdefault("POS_JWT_SECRET", "segredo-de-teste-pos")

from datetime import date, timedelta  # noqa: E402

import calendario  # noqa: E402
import server  # noqa: E402

from . import dados_semana_normal as sn  # noqa: E402

PERSONALIZADOS = [
    {"name": "Santo António", "month": 6, "day": 13, "company_id": None, "location_id": None},
    {"name": "Dia da Fordaimon", "month": 10, "day": 7, "company_id": sn.FORDAIMON, "location_id": None},
    {"name": "Feriado de Oeiras", "month": 6, "day": 7, "company_id": None, "location_id": sn.OEIRAS},
    {"name": "Impossível", "month": 2, "day": 30, "company_id": None, "location_id": None},
    {"name": "Lixo", "month": "x", "day": None},
]


def _loja(nome):
    return next(l for l in sn.semana_normal()["lojas"] if l["name"] == nome)


def test_os_nacionais_tem_nome():
    nacionais = calendario.feriados_nacionais(2026)
    assert nacionais[date(2026, 10, 5)] == "Implantação da República"
    assert nacionais[date(2026, 11, 1)] == "Todos os Santos"
    assert nacionais[date(2026, 4, 3)] == "Sexta-feira Santa"   # Páscoa de 2026: 5 de abril
    assert nacionais[date(2026, 6, 4)] == "Corpo de Deus"


def test_os_nacionais_sao_as_mesmas_datas_do_saldo_de_ferias():
    for ano in range(2024, 2032):
        assert set(calendario.feriados_nacionais(ano)) == server.get_pt_holidays(ano), ano


def test_os_feriados_com_nome_nao_mexem_na_cache_do_saldo_de_ferias():
    server.get_pt_holidays(2026)
    antes = dict(server._pt_holiday_cache)
    for ano in range(2024, 2032):
        calendario.feriados_nacionais(ano)
    assert server._pt_holiday_cache == antes
    assert all(server._pt_holiday_cache[ano] is antes[ano] for ano in antes)


def test_do_dia_sao_os_nacionais_e_os_do_grupo():
    assert calendario.feriados_do_dia(date(2026, 10, 5), PERSONALIZADOS) == ["Implantação da República"]
    assert calendario.feriados_do_dia(date(2026, 6, 13), PERSONALIZADOS) == ["Santo António"]
    assert calendario.feriados_do_dia(date(2026, 10, 7), PERSONALIZADOS) == []   # é da empresa, não do grupo


def test_da_loja_sao_os_da_empresa_dela_e_os_dela():
    assert calendario.feriados_da_loja(date(2026, 10, 7), PERSONALIZADOS, _loja("Alfragide")) == ["Dia da Fordaimon"]
    assert calendario.feriados_da_loja(date(2026, 10, 7), PERSONALIZADOS, _loja("Pizzaria")) == []
    assert calendario.feriados_da_loja(date(2026, 6, 7), PERSONALIZADOS, _loja("Oeiras")) == ["Feriado de Oeiras"]
    assert calendario.feriados_da_loja(date(2026, 6, 7), PERSONALIZADOS, _loja("Alfragide")) == []
    assert calendario.feriados_da_loja(date(2026, 6, 13), PERSONALIZADOS, _loja("Oeiras")) == []  # o do grupo vai no dia


def test_um_dia_impossivel_ou_lixo_nao_rebenta():
    dia = date(2028, 2, 1)
    while dia.month in (2, 3):
        assert "Impossível" not in calendario.feriados_do_dia(dia, PERSONALIZADOS)
        dia += timedelta(days=1)
