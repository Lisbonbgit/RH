"""O relógio do CRM (crm/relogio.py): a fonte única do "agora" e o formato dos
instantes guardados.

Porta mínima de src/Dominio/Relogio/* do CRM autónomo (RelogioTest.php):
instantes sempre em UTC. Formato fixado no plano (§1 Tempo e correções da
T2.8): todos os instantes `*_em` e `fase_desde`, exceto `atualizado_em`, têm
largura fixa `AAAA-MM-DDTHH:MM:SSZ` e são escritos só por `instante()` — o
texto ordena por caracteres, e misturar `+00:00` (isoformat) ou casas
decimais partia a ordenação e o `$max` (F4).

Os carimbos (T2.8) são os `atualizado_em`: sempre com 6 casas
(`AAAA-MM-DDTHH:MM:SS.ffffffZ`) e estritamente crescentes. São a versão do
bloqueio otimista: `carimbo` é o `Formatar::instanteMicro` do autónomo,
`ler_carimbo` o `Formatar::lerInstanteMicro` (casos do FormatarTest.php) e
`proximo_carimbo` o `GREATEST(?, atualizado_em + INTERVAL 1 MICROSECOND)` do
`LojasRepositorio::atualizar`.

O relógio é substituível: os testes das rotas trocam `relogio.agora` com
monkeypatch e tudo o que lê as horas passa a ver esse instante.

O "hoje" das rotas (F3, T3.1) é o dia em Lisboa (`Europe/Lisbon`), venha o
processo com o fuso que vier: os casos com outro fuso usam o fixture
`fuso_de_toquio`, nunca `monkeypatch.setenv("TZ", …)` (correção "T3.1": o
monkeypatch repõe a variável mas não volta a chamar o `time.tzset()`).
"""
import os
import random
import re
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from crm import relogio
from crm.relogio import FUSO_LISBOA, carimbo, hoje, ler_carimbo, proximo_carimbo

FORMATO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
FORMATO_CARIMBO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z")
UTC = timezone.utc
UM_MICRO = timedelta(microseconds=1)


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


# --- carimbo: o atualizado_em com 6 casas (T2.8) ------------------------------------


def _aleatorio(gerador, de=1, ate=9999):
    """Um instante UTC qualquer, ao microssegundo, entre os anos `de` e `ate`."""
    inicio = datetime(de, 1, 1, tzinfo=UTC)
    fim = datetime(ate, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)
    passos = (fim - inicio) // UM_MICRO
    return inicio + gerador.randrange(passos + 1) * UM_MICRO


def test_carimbo_tem_sempre_as_seis_casas():
    momento = datetime(2026, 10, 10, 9, 0, 0, 123456, tzinfo=UTC)
    assert carimbo(momento) == "2026-10-10T09:00:00.123456Z"


@pytest.mark.parametrize(
    "micro, texto",
    [(0, "2026-10-03T09:00:00.000000Z"), (1, "2026-10-03T09:00:00.000001Z"), (250000, "2026-10-03T09:00:00.250000Z"),
     (999999, "2026-10-03T09:00:00.999999Z")],
    ids=["zero fica com os seis zeros", "um microssegundo", "zeros no fim ficam", "o último antes do segundo seguinte"],
)
def test_carimbo_escreve_os_microssegundos_com_zeros_a_esquerda_e_a_direita(micro, texto):
    # FormatarTest::oInstanteComMicrossegundosGuardaOsSeisAlgarismos
    assert carimbo(datetime(2026, 10, 3, 9, 0, 0, micro, tzinfo=UTC)) == texto


def test_carimbo_converte_para_utc_e_muda_de_dia_quando_e_preciso():
    lisboa_no_verao = timezone(timedelta(hours=1))
    assert carimbo(datetime(2026, 10, 11, 0, 30, 0, 5, tzinfo=lisboa_no_verao)) == "2026-10-10T23:30:00.000005Z"
    menos_tres = timezone(timedelta(hours=-3))
    assert carimbo(datetime(2026, 12, 31, 22, 0, 0, 7, tzinfo=menos_tres)) == "2027-01-01T01:00:00.000007Z"


def test_carimbo_tem_largura_fixa_tambem_antes_do_ano_mil():
    assert carimbo(datetime(999, 1, 2, 3, 4, 5, 6, tzinfo=UTC)) == "0999-01-02T03:04:05.000006Z"


def test_carimbo_recusa_uma_hora_sem_fuso():
    with pytest.raises(ValueError):
        carimbo(datetime(2026, 10, 10, 9, 0, 0, 123456))


def test_carimbo_sem_argumento_usa_o_relogio_substituivel(monkeypatch):
    monkeypatch.setattr(relogio, "agora", lambda: datetime(2026, 10, 10, 9, 0, 0, 42, tzinfo=UTC))
    assert carimbo() == "2026-10-10T09:00:00.000042Z"


def test_carimbo_sem_argumento_e_o_de_agora():
    texto = carimbo()
    assert FORMATO_CARIMBO.fullmatch(texto)
    lido = datetime.strptime(texto, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    assert abs(lido - datetime.now(UTC)) < timedelta(seconds=5)


def test_carimbo_e_instante_partilham_o_segundo_cortado_e_nao_arredondado():
    """O instante é o carimbo sem as casas: 09:00:00.999999 é 09:00:00 nos
    dois (nunca o segundo seguinte)."""
    gerador = random.Random(2808)
    for momento in [datetime(2026, 10, 10, 9, 0, 0, 999999, tzinfo=UTC)] + [_aleatorio(gerador) for _ in range(2000)]:
        assert carimbo(momento)[:19] + "Z" == relogio.instante(momento)


def test_o_texto_dos_carimbos_ordena_como_o_tempo():
    """O Mongo compara os atualizado_em como texto (o filtro do bloqueio
    otimista e qualquer ordenação): a largura fixa faz a ordem do texto igual
    à do tempo, também no mesmo segundo e entre anos com menos algarismos."""
    gerador = random.Random(2026)
    base = datetime(2026, 10, 10, 9, 0, 0, tzinfo=UTC)
    momentos = [_aleatorio(gerador) for _ in range(3000)]
    momentos += [base + gerador.randrange(1_000_000) * UM_MICRO for _ in range(1000)]
    momentos += [datetime(999, 12, 31, 23, 59, 59, 999999, tzinfo=UTC), datetime(1000, 1, 1, tzinfo=UTC)]
    assert sorted(momentos, key=carimbo) == sorted(momentos)


# --- ler_carimbo: o atualizado_em que o cliente devolve no PATCH --------------------


@pytest.mark.parametrize(
    "texto",
    ["2026-10-03T09:00:00.250000Z", "2026-12-31T23:59:59.999999Z", "2026-10-03T00:00:00.000000Z",
     "2028-02-29T12:00:00.000001Z", "0999-01-02T03:04:05.000006Z", "9999-12-31T23:59:59.999999Z"],
    ids=["o do FormatarTest", "o último microssegundo do ano", "meia-noite certa", "29 de fevereiro num ano bissexto",
         "antes do ano mil", "o último que existe"],
)
def test_ler_carimbo_devolve_o_proprio_texto_quando_e_um_carimbo(texto):
    # FormatarTest::oAtualizadoEmQueOClienteDevolveLeSeNoFormatoDaBd: a versão
    # guarda-se no mesmo formato da API, por isso lê-se tal e qual (é o valor
    # do filtro {"id", "atualizado_em": versao} da atualização condicional).
    lido = ler_carimbo(texto)
    assert lido == texto
    assert type(lido) is str


def test_ler_carimbo_e_o_inverso_de_carimbo():
    gerador = random.Random(1003)
    for momento in (_aleatorio(gerador) for _ in range(3000)):
        assert ler_carimbo(carimbo(momento)) == carimbo(momento)


@pytest.mark.parametrize(
    "valor",
    [
        # FormatarTest::versoesInvalidas, tal e qual
        None, "", 1759482000, ["2026-10-03T09:00:00.250000Z"], "2026-10-03 09:00:00.250000",
        "2026-10-03T09:00:00Z", "2026-10-03T09:00:00.250Z", "2026-10-03T09:00:00.250000+00:00",
        "2026-10-03T09:00:00.250000", " 2026-10-03T09:00:00.250000Z", "2026-10-03T09:00:00.250000Z\n",
        "2026-02-30T09:00:00.000000Z", "2026-10-03T24:00:00.000000Z",
        # armadilhas do Python e do Mongo
        True, 1759482000.25, {"$gt": ""}, {"$ne": None}, b"2026-10-03T09:00:00.250000Z",
        "2026-10-03T09:00:00.250000z", "2026-10-03t09:00:00.250000Z", "2026-10-03T09:00:00,250000Z",
        "2026-10-03T09:00:00.2500000Z", "2026-1-03T09:00:00.250000Z", "2026-10-3T9:00:00.250000Z",
        "2026-10-03T09:00:00.250000Z ", " 2026-10-03T09:00:00.250000Z", "2026-10-03T09:00:00.250000Z\x00",
        "٢٠٢٦-١٠-٠٣T٠٩:٠٠:٠٠.٢٥٠٠٠٠Z", "２０２６-10-03T09:00:00.250000Z", "2026-10-03T09:00:00.25000٠Z",
        "2025-02-29T09:00:00.000000Z", "2026-13-03T09:00:00.000000Z", "2026-00-03T09:00:00.000000Z",
        "2026-10-00T09:00:00.000000Z", "2026-10-03T09:60:00.000000Z", "2026-10-03T09:00:60.000000Z",
        "0000-01-01T00:00:00.000000Z", "+2026-10-03T09:00:00.250000Z", "-2026-10-03T09:00:00.250000Z",
        "12026-10-03T09:00:00.250000Z", "2026-10-03T09:00:00.-50000Z", "2026-10-03T09:00:00.+50000Z",
        "2026-10-03T09:00:00.250000Z2026-10-03T09:00:00.250000Z", "2026-10-03T09:00:00.0250000Z",
        "٢٠٢٦-10-03T09:00:00.250000Z", "2026-١٠-03T09:00:00.250000Z", "2026-10-٠٣T09:00:00.250000Z",
        "2026-10-03T٠٩:00:00.250000Z", "2026-10-03T09:٠٠:00.250000Z", "2026-10-03T09:00:٠٠.250000Z",
    ],
    ids=[
        "null", "vazio", "um número", "uma lista", "no formato da BD", "sem microssegundos", "com milissegundos",
        "com o fuso por extenso", "sem o Z", "com espaços", "com mudança de linha no fim", "um dia que não existe",
        "uma hora que não existe",
        "verdadeiro", "um número com casas", "um operador do Mongo", "outro operador do Mongo", "bytes",
        "z minúsculo", "t minúsculo", "vírgula nas casas", "sete casas", "mês com um algarismo",
        "dia e hora com um algarismo", "espaço no fim", "espaço sem quebra no início", "NUL no fim",
        "algarismos árabes", "algarismos de largura total", "um algarismo árabe nas casas",
        "29 de fevereiro num ano comum", "mês 13", "mês 0", "dia 0", "minuto 60", "segundo 60",
        "ano zero", "sinal de mais", "ano negativo", "ano com cinco algarismos", "casas com sinal de menos",
        "casas com sinal de mais", "dois carimbos seguidos", "sete casas a começar por zero",
        "algarismos árabes só no ano", "só no mês", "só no dia", "só na hora", "só nos minutos", "só nos segundos",
    ],
)
def test_um_atualizado_em_que_nao_veio_da_api_nao_se_le(valor):
    # FormatarTest::umAtualizadoEmQueNaoVeioDaApiNaoSeLe
    assert ler_carimbo(valor) is None


# --- proximo_carimbo: a versão nova muda sempre ---------------------------------------


def test_proximo_carimbo_e_o_de_agora_quando_o_relogio_vai_a_frente():
    agora = datetime(2026, 10, 10, 9, 0, 1, 500000, tzinfo=UTC)
    assert proximo_carimbo(agora, "2026-10-10T09:00:00.123456Z") == "2026-10-10T09:00:01.500000Z"


def test_proximo_carimbo_no_mesmo_microssegundo_avanca_um():
    agora = datetime(2026, 10, 10, 9, 0, 0, 123456, tzinfo=UTC)
    assert proximo_carimbo(agora, "2026-10-10T09:00:00.123456Z") == "2026-10-10T09:00:00.123457Z"


def test_proximo_carimbo_com_o_relogio_atrasado_avanca_um_sobre_o_anterior():
    # O GREATEST do LojasRepositorio::atualizar: a versão gravada por outro
    # processo (ou antes de um acerto do relógio) pode estar à frente do agora.
    agora = datetime(2026, 10, 10, 8, 59, 0, tzinfo=UTC)
    assert proximo_carimbo(agora, "2026-10-10T09:00:00.123456Z") == "2026-10-10T09:00:00.123457Z"


@pytest.mark.parametrize(
    "anterior, seguinte",
    [("2026-10-10T09:00:00.999999Z", "2026-10-10T09:00:01.000000Z"),
     ("2026-10-10T23:59:59.999999Z", "2026-10-11T00:00:00.000000Z"),
     ("2026-12-31T23:59:59.999999Z", "2027-01-01T00:00:00.000000Z"),
     ("2028-02-28T23:59:59.999999Z", "2028-02-29T00:00:00.000000Z")],
    ids=["muda de segundo", "muda de dia", "muda de ano", "chega a 29 de fevereiro"],
)
def test_proximo_carimbo_leva_o_microssegundo_ao_segundo_seguinte(anterior, seguinte):
    agora = datetime(2026, 1, 1, tzinfo=UTC)
    assert proximo_carimbo(agora, anterior) == seguinte


def test_proximo_carimbo_converte_o_agora_para_utc():
    lisboa_no_verao = timezone(timedelta(hours=1))
    agora = datetime(2026, 10, 10, 10, 0, 0, 7, tzinfo=lisboa_no_verao)
    assert proximo_carimbo(agora, "2026-10-10T08:00:00.000000Z") == "2026-10-10T09:00:00.000007Z"


def test_proximo_carimbo_recusa_um_agora_sem_fuso():
    with pytest.raises(ValueError):
        proximo_carimbo(datetime(2026, 10, 10, 9, 0, 0), "2026-10-10T08:00:00.000000Z")


@pytest.mark.parametrize(
    "anterior",
    [None, "", "2026-10-10T09:00:00Z", "2026-10-10T09:00:00.123456+00:00", "2026-02-30T09:00:00.000000Z",
     1759482000, {"$gt": ""}],
    ids=["null", "vazio", "sem microssegundos", "isoformat", "um dia que não existe", "um número", "um operador"],
)
def test_proximo_carimbo_recusa_um_anterior_que_nao_e_carimbo(anterior):
    # Sem ler o anterior não se garante que o novo é maior: nunca se grava
    # uma versão que possa não mudar (o PATCH só chega aqui com a versão lida
    # por ler_carimbo e igual à guardada).
    with pytest.raises(ValueError):
        proximo_carimbo(datetime(2026, 10, 10, 9, 0, 0, tzinfo=UTC), anterior)


def test_proximo_carimbo_depois_do_ultimo_que_existe_rebenta_em_vez_de_repetir():
    with pytest.raises(OverflowError):
        proximo_carimbo(datetime(2026, 10, 10, tzinfo=UTC), "9999-12-31T23:59:59.999999Z")


def test_proximo_carimbo_e_sempre_maior_e_nunca_salta_sem_razao():
    """Propriedade: o novo é sempre um carimbo, maior do que o anterior no
    tempo e no texto, e é exatamente max(agora, anterior + 1 µs)."""
    gerador = random.Random(1010)
    for _ in range(5000):
        anterior_dt = _aleatorio(gerador, 2, 9998)  # sem o ano 1: o agora pode recuar
        escolha = gerador.randrange(4)
        if escolha == 0:
            agora = anterior_dt
        elif escolha == 1:
            agora = anterior_dt + gerador.randrange(1, 3) * UM_MICRO
        elif escolha == 2:
            agora = anterior_dt - gerador.randrange(1, 10**9) * UM_MICRO
        else:
            agora = _aleatorio(gerador, 1, 9998)
        anterior = carimbo(anterior_dt)
        novo = proximo_carimbo(agora, anterior)
        assert ler_carimbo(novo) == novo
        assert novo > anterior
        assert novo == carimbo(max(agora, anterior_dt + UM_MICRO))


def test_com_o_relogio_parado_os_carimbos_seguidos_sao_estritamente_crescentes():
    parado = datetime(2026, 10, 10, 9, 0, 0, 999990, tzinfo=UTC)
    versoes = [carimbo(parado)]
    for _ in range(1000):
        versoes.append(proximo_carimbo(parado, versoes[-1]))
    assert versoes == sorted(set(versoes))
    assert versoes[-1] == "2026-10-10T09:00:01.000990Z"


# --- hoje: o dia de hoje em Lisboa (F3, T3.1) ---------------------------------------


# (instante UTC do relógio parado, dia em Lisboa). Lisboa está a UTC+1 no
# verão (WEST) e a UTC+0 no inverno (WET); em 2026 a hora muda a 29 de março
# e a 25 de outubro, às 01:00 UTC.
CASOS_DE_HOJE = [
    (datetime(2026, 10, 10, 22, 59, 59, tzinfo=UTC), date(2026, 10, 10)),
    (datetime(2026, 10, 10, 23, 0, 0, tzinfo=UTC), date(2026, 10, 11)),
    (datetime(2026, 10, 25, 0, 59, 59, tzinfo=UTC), date(2026, 10, 25)),
    (datetime(2026, 10, 25, 23, 30, 0, tzinfo=UTC), date(2026, 10, 25)),
    (datetime(2026, 3, 29, 0, 59, 59, tzinfo=UTC), date(2026, 3, 29)),
    (datetime(2026, 3, 29, 23, 30, 0, tzinfo=UTC), date(2026, 3, 30)),
    (datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC), date(2026, 12, 31)),
    (datetime(2026, 12, 31, 23, 59, 59, 999999, tzinfo=UTC), date(2026, 12, 31)),
    (datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC), date(2027, 1, 1)),
    (datetime(2026, 6, 30, 23, 0, 0, tzinfo=UTC), date(2026, 7, 1)),
]
IDS_DE_HOJE = [
    "22:59:59Z no verão ainda é o próprio dia",
    "23:00:00Z no verão já é o dia seguinte (WEST)",
    "01:59:59 WEST no dia em que a hora atrasa",
    "23:30Z depois de a hora atrasar fica no mesmo dia (WET)",
    "00:59:59Z no dia em que a hora adianta ainda é WET",
    "23:30Z depois de a hora adiantar já é o dia seguinte",
    "o último segundo do ano no inverno",
    "o último microssegundo do ano",
    "a meia-noite do ano novo",
    "o fim de junho já é julho em Lisboa",
]


def test_o_fuso_de_lisboa_e_o_europe_lisbon():
    assert isinstance(FUSO_LISBOA, ZoneInfo)
    assert FUSO_LISBOA.key == "Europe/Lisbon"
    assert relogio.FUSO_LISBOA is FUSO_LISBOA


@pytest.mark.parametrize("momento, dia", CASOS_DE_HOJE, ids=IDS_DE_HOJE)
def test_hoje_e_o_dia_em_lisboa_do_relogio_parado(monkeypatch, momento, dia):
    monkeypatch.setattr(relogio, "agora", lambda: momento)
    resultado = hoje()
    assert resultado == dia
    assert type(resultado) is date  # um dia, nunca um datetime


@pytest.mark.parametrize("momento, dia", CASOS_DE_HOJE, ids=IDS_DE_HOJE)
def test_hoje_nao_depende_do_fuso_do_processo(fuso_de_toquio, monkeypatch, momento, dia):
    # O Mac está em Lisboa e o contentor em UTC; aqui o processo está em
    # Tóquio (UTC+9), onde 2026-10-10T22:59:59Z já é dia 11.
    monkeypatch.setattr(relogio, "agora", lambda: momento)
    assert time.localtime(momento.timestamp()).tm_gmtoff == 9 * 3600  # o fixture mudou mesmo o fuso
    assert hoje() == dia


def test_hoje_aceita_um_agora_com_outro_desvio(monkeypatch):
    # O relógio devolve sempre UTC, mas o resultado só depende do instante.
    toquio = timezone(timedelta(hours=9))
    monkeypatch.setattr(relogio, "agora", lambda: datetime(2026, 10, 11, 7, 59, 59, tzinfo=toquio))
    assert hoje() == date(2026, 10, 10)  # 22:59:59Z, 23:59:59 em Lisboa


def test_hoje_recusa_um_agora_sem_fuso(monkeypatch):
    # Uma datetime sem fuso seria lida na hora local do processo.
    monkeypatch.setattr(relogio, "agora", lambda: datetime(2026, 10, 10, 23, 30, 0))
    with pytest.raises(ValueError):
        hoje()


def test_hoje_sem_relogio_parado_e_o_dia_atual_em_lisboa():
    antes = datetime.now(ZoneInfo("Europe/Lisbon")).date()
    resultado = hoje()
    depois = datetime.now(ZoneInfo("Europe/Lisbon")).date()
    assert resultado in {antes, depois}


def test_hoje_e_o_dia_utc_no_inverno_e_o_de_utc_mais_uma_hora_no_verao(monkeypatch):
    """Propriedade, sem passar pelo ZoneInfo: de novembro a fevereiro Lisboa
    está em UTC+0 (o dia é o de UTC) e de abril a setembro em UTC+1."""
    gerador = random.Random(311)
    inicio = datetime(2000, 1, 1, tzinfo=UTC)
    vistos = {"inverno": 0, "verao": 0}
    for _ in range(4000):
        momento = inicio + timedelta(seconds=gerador.randrange(40 * 366 * 86400))
        monkeypatch.setattr(relogio, "agora", lambda m=momento: m)
        if momento.month in (11, 12, 1, 2):
            assert hoje() == momento.date()
            vistos["inverno"] += 1
        elif 4 <= momento.month <= 9:
            assert hoje() == (momento + timedelta(hours=1)).date()
            vistos["verao"] += 1
    assert min(vistos.values()) > 500
