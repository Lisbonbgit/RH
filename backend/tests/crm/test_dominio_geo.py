"""Portugal continental, distância e precisão do GPS (crm/dominio/geo.py).

Porta de src/Dominio/Geo/{Portugal,Distancia,PrecisaoGps}.php, com todos os
casos de tests/Unit/Dominio/{PortugalTest,DistanciaTest,PrecisaoGpsTest}.php
do CRM autónomo (mesmos nomes nos `ids`). Os duplicados a menos de 50 m
(Duplicados.php) juntam-se a este módulo na T2.3.

Armadilhas do Python (plano §9; dossiê §2.1 e §5.3–5.5):

- o `round()` do Python arredonda para o par: um GPS de 50,5 m daria 50 e
  seria aceite; a precisão arredonda-se com `numeros.arredondar` (→ 51);
- `False` é 0 em Python: sem olhar para o tipo, `precisao_m: false` passava
  como um GPS de 0 m; o PHP nunca conta um bool como número;
- o `json` do Python lê `NaN`, `Infinity` e `1e400` (→ inf).

Os valores "conferidos com o PHP" saíram das próprias classes do CRM autónomo
(etiqueta `referencia-standalone`) no PHP 8.4.26, com `var_export`.

`LIMITE_PRECISAO_M` e `MENSAGEM_GPS` são iguais a `LIMITE_PRECISAO_M` e
`MENSAGEM_LOCALIZACAO_IMPRECISA` de frontend/src/lib/crm/gps.js, o que o
test_consistencia_frontend.py (T2.20) confere.
"""
import json
import math

import pytest

from crm.dominio.geo import (
    LAT_MAXIMA,
    LAT_MINIMA,
    LIMITE_PRECISAO_M,
    LNG_MAXIMA,
    LNG_MINIMA,
    MENSAGEM_GPS,
    MENSAGEM_PORTUGAL,
    METROS_POR_GRAU,
    RAIO_TERRA_M,
    _radianos,
    contem_latitude,
    contem_longitude,
    distancia_metros,
    precisao_aceitavel,
)
from crm.dominio.numeros import arredondar


# --- Portugal continental (PortugalTest.php) ---


@pytest.mark.parametrize(
    "lat",
    [36.8, 37.018, 38.7075, 41.1578, 42.2],
    ids=["limite sul", "Faro", "Lisboa", "Porto", "limite norte"],
)
def test_aceita_latitudes_do_continente_com_os_limites(lat):
    assert contem_latitude(lat) is True


@pytest.mark.parametrize(
    "lat",
    [36.799999, 42.200001, 32.65, 0.0],
    ids=["logo a sul", "logo a norte", "Madeira", "Equador"],
)
def test_recusa_latitudes_fora_do_continente(lat):
    assert contem_latitude(lat) is False


@pytest.mark.parametrize(
    "lng",
    [-9.6, -9.5005, -9.1364, -6.1],
    ids=["limite oeste", "Cabo da Roca", "Lisboa", "limite leste"],
)
def test_aceita_longitudes_do_continente_com_os_limites(lng):
    assert contem_longitude(lng) is True


@pytest.mark.parametrize(
    "lng",
    [-9.600001, -6.099999, -25.67, -3.7038, 0.0, 9.1364],
    ids=["logo a oeste", "logo a leste", "Açores", "Madrid", "Greenwich", "positiva (sinal trocado)"],
)
def test_recusa_longitudes_fora_do_continente(lng):
    assert contem_longitude(lng) is False


def test_a_mensagem_e_fora_de_portugal():
    assert MENSAGEM_PORTUGAL == "Fora de Portugal"


def test_a_caixa_de_portugal_continental():
    # Plano §9 do autónomo: uma caixa aproximada, que apanha também um pouco
    # de Espanha junto à fronteira (aceita-se); as ilhas ficam de fora.
    assert (LAT_MINIMA, LAT_MAXIMA, LNG_MINIMA, LNG_MAXIMA) == (36.8, 42.2, -9.6, -6.1)


def test_aceita_coordenadas_inteiras():
    # Um número inteiro do JSON também é uma coordenada (o `float` do PHP
    # aceitava um int).
    assert contem_latitude(39) is True
    assert contem_longitude(-8) is True
    assert contem_latitude(43) is False
    assert contem_longitude(-10) is False


@pytest.mark.parametrize(
    "valor",
    [True, False, "38.7", "-9.1", None, [38.7], {"lat": 38.7}, math.nan, math.inf, -math.inf, 10**400],
    ids=[
        "verdadeiro",
        "falso",
        "latitude em texto",
        "longitude em texto",
        "nula",
        "lista",
        "objeto",
        "NaN",
        "infinita",
        "menos infinita",
        "inteiro que não cabe num float",
    ],
)
def test_o_que_nao_e_um_numero_json_nunca_esta_em_portugal(valor):
    # Quem chama valida primeiro ("A latitude tem de ser um número."); isto
    # é a rede: nem um bool conta como número, nem um texto rebenta com
    # TypeError (o que daria um 500).
    assert contem_latitude(valor) is False
    assert contem_longitude(valor) is False


@pytest.mark.parametrize(
    "valor, arredondada, lat, lng",
    [
        (36.7999996, 36.8, True, False),
        (36.7999994, 36.799999, False, False),
        (42.2000004, 42.2, True, False),
        (42.2000005, 42.200001, False, False),
        (-9.6000004, -9.6, False, True),
        (-9.6000005, -9.600001, False, False),
        (-6.0999995, -6.1, False, True),
        (-6.0999994, -6.099999, False, False),
    ],
    ids=[
        "sul: arredonda para o limite",
        "sul: arredonda para fora",
        "norte: arredonda para o limite",
        "norte: o meio arredonda para fora",
        "oeste: arredonda para o limite",
        "oeste: o meio arredonda para fora",
        "leste: o meio arredonda para o limite",
        "leste: arredonda para fora",
    ],
)
def test_a_coordenada_conta_depois_de_arredondada_as_6_casas_conferido_com_o_php(valor, arredondada, lat, lng):
    # O validador da loja e as definições arredondam às 6 casas com que se
    # guarda e só depois veem se está em Portugal (ValidadorLoja::coordenada,
    # Definicoes::coordenada). Valores do round() + Portugal do PHP 8.4.26.
    assert arredondar(valor, 6) == arredondada
    assert contem_latitude(arredondada) is lat
    assert contem_longitude(arredondada) is lng


# --- Distância (DistanciaTest.php) ---

PRACA_DO_COMERCIO = (38.707500, -9.136400)
ROSSIO = (38.713900, -9.139100)
PORTO = (41.157800, -8.629100)


def test_da_praca_do_comercio_ao_rossio_sao_750_metros():
    assert distancia_metros(*PRACA_DO_COMERCIO, *ROSSIO) == pytest.approx(750.0, abs=10.0)


def test_o_mesmo_ponto_da_0():
    metros = distancia_metros(*PRACA_DO_COMERCIO, *PRACA_DO_COMERCIO)

    assert metros == 0.0
    assert type(metros) is float


def test_e_igual_nos_dois_sentidos():
    assert distancia_metros(*PRACA_DO_COMERCIO, *PORTO) == pytest.approx(
        distancia_metros(*PORTO, *PRACA_DO_COMERCIO), abs=1e-6
    )


def test_usa_o_raio_medio_da_terra():
    assert RAIO_TERRA_M == 6_371_000
    assert type(RAIO_TERRA_M) is int
    assert METROS_POR_GRAU == pytest.approx(111_194.93, abs=0.01)
    assert distancia_metros(38.0, -9.0, 39.0, -9.0) == pytest.approx(METROS_POR_GRAU, abs=1e-6)


def test_um_grau_de_longitude_encurta_com_a_latitude():
    no_equador = distancia_metros(0.0, -9.0, 0.0, -8.0)
    em_lisboa = distancia_metros(38.7075, -9.0, 38.7075, -8.0)

    assert no_equador == pytest.approx(METROS_POR_GRAU, abs=1e-6)
    assert em_lisboa == pytest.approx(METROS_POR_GRAU * math.cos(math.radians(38.7075)), abs=5.0)


def test_os_antipodas_ficam_a_meia_volta():
    metros = distancia_metros(38.7075, -9.1364, -38.7075, 170.8636)

    assert metros == pytest.approx(math.pi * RAIO_TERRA_M, abs=1.0)


@pytest.mark.parametrize(
    "pontos, php",
    [
        ((38.7075, -9.1364, 38.7139, -9.1391), 749.21622837273),
        ((38.7075, -9.1364, 41.1578, -8.6291), 275871.38819268305),
        ((37.018, -7.9304, 42.2, -8.0), 576242.8925294456),
        ((38.7075, -9.1364, 38.70795, -9.1364), 50.03771698914294),
        ((36.8, -9.6, 42.2, -6.1), 671200.9184584067),
        ((38.7075, -9.1364, -38.7075, 170.8636), 20015086.79602057),
    ],
    ids=[
        "Praça do Comércio ao Rossio",
        "Lisboa ao Porto",
        "Faro ao limite norte",
        "um pouco mais de 50 m a norte",
        "cantos opostos da caixa de Portugal",
        "antípodas",
    ],
)
def test_distancias_conferidas_com_o_php(pontos, php):
    # Distancia::metros() do PHP 8.4.26. A tolerância só cobre a última casa
    # do seno e do cosseno de cada sistema (libm do macOS ou do Linux).
    assert distancia_metros(*pontos) == pytest.approx(php, rel=1e-12, abs=1e-9)


@pytest.mark.parametrize(
    "graus, php",
    [
        (38.7075, 0.6755733202157052),
        (-9.1364, -0.1594602617792099),
        (41.1578, 0.7183391228773223),
        (36.8, 0.6422811647339132),
        (-6.1, -0.10646508437165408),
    ],
    ids=["Lisboa (lat)", "Lisboa (lng)", "Porto (lat)", "limite sul", "limite leste"],
)
def test_os_graus_passam_a_radianos_como_no_deg2rad_do_php(graus, php):
    # deg2rad() do PHP 8.4.26 faz (graus / 180) * M_PI. O math.radians() do
    # Python multiplica por pi / 180 e muda a última casa binária nos quatro
    # últimos (nas antípodas, isso chegava a 0,19 m de diferença). Uma divisão
    # e uma multiplicação dão o mesmo resultado em qualquer sistema (IEEE 754),
    # por isso compara-se ao bit, ao contrário do seno e do cosseno.
    assert _radianos(graus) == php


def test_metros_por_grau_conferido_com_o_php():
    # Distancia::METROS_POR_GRAU = RAIO_TERRA_M * M_PI / 180, pela mesma ordem.
    assert METROS_POR_GRAU == 111194.92664455873


def test_os_antipodas_nao_saem_do_dominio_do_asin():
    # Aqui a soma da haversine dá 1,0000000000000002 (uma casa acima de 1).
    # O asin do PHP daria NAN acima de 1 e o do Python rebenta com
    # ValueError; a raiz quadrada devolve 1,0 e a conta chega à meia volta.
    metros = distancia_metros(-79.897806, 133.203656, 79.897806, -46.796344)

    assert metros == pytest.approx(math.pi * RAIO_TERRA_M, abs=1.0)


def test_aceita_coordenadas_inteiras_na_distancia():
    assert distancia_metros(38, -9, 39, -9) == pytest.approx(METROS_POR_GRAU, abs=1e-6)


def test_cinquenta_metros_para_norte_medem_cinquenta_metros():
    # A base dos testes dos duplicados (T2.3): um ponto a N metros para norte
    # fica a N / METROS_POR_GRAU graus de latitude.
    lat, lng = PRACA_DO_COMERCIO

    assert distancia_metros(lat, lng, lat + 50 / METROS_POR_GRAU, lng) == pytest.approx(50.0, abs=1e-6)


# --- Precisão do GPS (PrecisaoGpsTest.php) ---


def test_o_limite_e_50_metros():
    assert LIMITE_PRECISAO_M == 50
    assert type(LIMITE_PRECISAO_M) is int


def test_a_mensagem_e_igual_a_do_telemovel():
    # frontend/src/lib/crm/gps.js: MENSAGEM_LOCALIZACAO_IMPRECISA
    assert MENSAGEM_GPS == "Localização imprecisa — ajuste o pino"


@pytest.mark.parametrize(
    "precisao_m",
    [50, 12, 0, 50.4, 12.0],
    ids=["50 m (o limite)", "12 m", "0 m", "50,4 m (guarda-se 50)", "12,0 m"],
)
def test_aceita_ate_50_metros(precisao_m):
    assert precisao_aceitavel(precisao_m) is True


@pytest.mark.parametrize(
    "precisao_m",
    [51, 50.5, 80, -1, None, "10", True, math.inf, math.nan],
    ids=[
        "51 m",
        "50,5 m (guarda-se 51)",
        "80 m",
        "negativa",
        "sem precisão",
        "texto",
        "verdadeiro",
        "infinita",
        "NaN",
    ],
)
def test_recusa_acima_de_50_metros_ou_sem_precisao(precisao_m):
    assert precisao_aceitavel(precisao_m) is False


@pytest.mark.parametrize(
    "precisao_m",
    [49.5, 50.49999999999999, 0.0, -0.0],
    ids=["49,5 m (guarda-se 50)", "mesmo abaixo de 50,5 m", "zero decimal", "menos zero (≥ 0, como no PHP)"],
)
def test_aceita_tambem_conferido_com_o_php(precisao_m):
    assert precisao_aceitavel(precisao_m) is True


@pytest.mark.parametrize(
    "precisao_m",
    [False, -0.4, -math.inf, 1e20, 2**63 - 1, 2**63, 10**400, "50", [10], {"m": 10}],
    ids=[
        "falso (em Python é 0)",
        "negativa que arredonda a zero",
        "menos infinita",
        "enorme",
        "o maior inteiro de 64 bits",
        "inteiro fora dos 64 bits",
        "inteiro que não cabe num float",
        "texto do limite",
        "lista",
        "objeto",
    ],
)
def test_recusa_tambem_as_armadilhas_do_python(precisao_m):
    # O PHP 8.4.26 recusa os mesmos (`false`, -0,4, -INF, 1e20 e
    # PHP_INT_MAX conferidos); sem olhar para o tipo, o False passava como
    # um GPS de 0 m e um inteiro enorme rebentava no float() com
    # OverflowError.
    assert precisao_aceitavel(precisao_m) is False


@pytest.mark.parametrize(
    "texto_json, aceitavel",
    [
        ("50", True),
        ("50.4", True),
        ("50.5", False),
        ("-0.0", True),
        ("false", False),
        ("NaN", False),
        ("Infinity", False),
        ("1e400", False),
        ('"10"', False),
        ("null", False),
    ],
    ids=["50", "50.4", "50.5", "-0.0", "false", "NaN", "Infinity", "1e400", "texto", "null"],
)
def test_precisao_lida_pelo_json_do_python(texto_json, aceitavel):
    # É assim que a precisão chega à API (corpo JSON lido pelo `json` do
    # Python, que aceita NaN, Infinity e 1e400).
    assert precisao_aceitavel(json.loads(texto_json)) is aceitavel
