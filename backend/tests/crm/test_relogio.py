"""O relógio do CRM (crm/relogio.py): a fonte única do "agora" e o formato dos
instantes guardados.

Porta mínima de src/Dominio/Relogio/* do CRM autónomo (RelogioTest.php):
instantes sempre em UTC. Formato fixado no plano (§1 Tempo e correções da
T2.8): todos os instantes `*_em` e `fase_desde`, exceto `atualizado_em`, têm
largura fixa `AAAA-MM-DDTHH:MM:SSZ` e são escritos só por `instante()` — o
texto ordena por caracteres, e misturar `+00:00` (isoformat) ou casas
decimais partia a ordenação e o `$max` (F4). A T2.8 acrescenta carimbo,
ler_carimbo e proximo_carimbo (os `atualizado_em` com 6 casas).

O relógio é substituível: os testes das rotas trocam `relogio.agora` com
monkeypatch e tudo o que lê as horas passa a ver esse instante.
"""
import os
import re
import time
from datetime import datetime, timedelta, timezone

import pytest

from crm import relogio

FORMATO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
UTC = timezone.utc


def test_agora_e_um_instante_com_fuso_em_utc():
    antes = datetime.now(UTC)
    agora = relogio.agora()
    depois = datetime.now(UTC)
    assert agora.tzinfo is not None
    assert agora.utcoffset() == timedelta(0)
    assert antes <= agora <= depois


@pytest.fixture
def fuso_de_toquio():
    """Muda o fuso por omissão do processo e repõe-no no fim (sem monkeypatch:
    o time.tzset() tem de correr DEPOIS de repor a variável TZ)."""
    anterior = os.environ.get("TZ")
    os.environ["TZ"] = "Asia/Tokyo"
    time.tzset()
    try:
        yield
    finally:
        if anterior is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = anterior
        time.tzset()


def test_agora_e_utc_mesmo_com_outro_fuso_por_omissao(fuso_de_toquio):
    # O Mac está em Lisboa e o contentor em UTC: o resultado não pode depender
    # disso (RelogioTest::relogioSistemaDevolveOInstanteAtualEmUtc…).
    agora = relogio.agora()
    assert agora.utcoffset() == timedelta(0)
    assert abs(agora - datetime.now(UTC)) < timedelta(seconds=5)
    assert relogio.instante(datetime(2026, 10, 10, 9, 0, 0, tzinfo=UTC)) == "2026-10-10T09:00:00Z"


def test_instante_formata_em_utc_com_z():
    assert relogio.instante(datetime(2026, 10, 10, 9, 0, 0, tzinfo=UTC)) == "2026-10-10T09:00:00Z"


def test_instante_converte_para_utc_um_instante_com_outro_desvio():
    # RelogioTest::relogioFixoConverteParaUtcUmInstanteComOutroDesvio
    hora_de_verao_em_lisboa = timezone(timedelta(hours=1))
    momento = datetime(2026, 10, 10, 10, 0, 0, tzinfo=hora_de_verao_em_lisboa)
    assert relogio.instante(momento) == "2026-10-10T09:00:00Z"


def test_instante_converte_e_muda_de_dia_quando_e_preciso():
    momento = datetime(2026, 10, 11, 0, 30, 0, tzinfo=timezone(timedelta(hours=1)))
    assert relogio.instante(momento) == "2026-10-10T23:30:00Z"


def test_instante_nao_tem_microssegundos_e_corta_sem_arredondar():
    # 09:00:00.999999 é ainda 09:00:00 (como o format('s') do PHP); arredondar
    # punha o instante no segundo seguinte, no futuro.
    momento = datetime(2026, 10, 10, 9, 0, 0, 999999, tzinfo=UTC)
    assert relogio.instante(momento) == "2026-10-10T09:00:00Z"


def test_instante_tem_sempre_a_mesma_largura():
    momento = datetime(999, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert relogio.instante(momento) == "0999-01-02T03:04:05Z"


def test_instante_sem_argumento_e_o_de_agora_e_tem_o_formato_fixo():
    texto = relogio.instante()
    assert FORMATO.fullmatch(texto)
    lido = datetime.strptime(texto, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert abs(lido - datetime.now(UTC)) < timedelta(seconds=5)


def test_o_relogio_e_substituivel(monkeypatch):
    # Os testes das rotas (T1.7 em diante) param o relógio assim.
    parado = datetime(2026, 10, 10, 9, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(relogio, "agora", lambda: parado)
    assert relogio.instante() == "2026-10-10T09:00:00Z"


def test_instante_recusa_uma_hora_sem_fuso():
    # Uma datetime sem fuso é ambígua: datetime.now() seria a hora de Lisboa
    # no Mac e a de UTC no contentor. Melhor rebentar já do que gravar mal.
    with pytest.raises(ValueError):
        relogio.instante(datetime(2026, 10, 10, 9, 0, 0))
