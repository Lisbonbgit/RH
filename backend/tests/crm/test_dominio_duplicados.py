"""Duplicados a menos de 50 m e o pré-filtro do Mongo (crm/dominio/geo.py).

Porta de src/Dominio/Geo/Duplicados.php, com todos os casos de
tests/Unit/Dominio/DuplicadosTest.php do CRM autónomo (mesmos cenários, nomes
em pt-PT), e os ids em texto (uuid4) como no portal.

O autónomo escolhia os candidatos com uma caixa em graus no índice (lat, lng)
do MariaDB (`Duplicados::caixa`, 1 m de folga). No portal, o pré-filtro é um
círculo de 60 m no índice `2dsphere` de `loc` (`$geoWithin` + `$centerSphere`,
plano §1 e dossiê §5.5); os testes da caixa passam a ser os do círculo: tem o
raio certo, põe a longitude primeiro (GeoJSON), não depende da latitude, nunca
deixa de fora um duplicado e não é muito maior do que o círculo dos 50 m.

Armadilhas do Python (plano §9 e §10; dossiê §2.1 e §5.5):

- o `round()` do Python arredonda para o par: uma loja a 30,5 m mostrava-se a
  30 m; a distância arredonda-se com `numeros.arredondar` (→ 31);
- `distancia_m` é um `int` (o `(int) round(…)` do PHP), e `49 == 49.0` em
  Python: o tipo confere-se à parte;
- no Mongo, `lat` e `lng` são números (o PDO do autónomo devolvia texto).
"""
import math

import pytest

from crm.dominio import geo
from crm.dominio.geo import (
    FOLGA_PREFILTRO_M,
    METROS_POR_GRAU,
    RAIO_DUPLICADOS_M,
    RAIO_TERRA_M,
    TOLERANCIA_M,
    distancia_metros,
    encontrar_duplicados,
    filtro_candidatos,
)
from crm.dominio.numeros import arredondar

LAT = 38.707500
LNG = -9.136400


def _id(n: int) -> str:
    """Um uuid4 em texto, como os ids do portal; o número só ajuda a ler."""
    return f"00000000-0000-4000-8000-{n:012d}"


def _loja(n: int, nome: str, metros: float) -> dict:
    """Uma loja a uma distância exata (em metros) a norte do ponto de teste."""
    return {"id": _id(n), "nome": nome, "lat": LAT + metros / METROS_POR_GRAU, "lng": LNG}


def _destino(lat: float, lng: float, metros: float, rumo: int) -> tuple[float, float]:
    """O ponto a uma distância e num rumo (graus a partir do norte, no sentido
    dos ponteiros) de outro, pela fórmula do destino sobre a esfera."""
    angulo = metros / RAIO_TERRA_M
    fi = math.radians(lat)
    teta = math.radians(rumo)
    fi2 = math.asin(math.sin(fi) * math.cos(angulo) + math.cos(fi) * math.sin(angulo) * math.cos(teta))
    lambda_ = math.atan2(
        math.sin(teta) * math.sin(angulo) * math.cos(fi),
        math.cos(angulo) - math.sin(fi) * math.sin(fi2),
    )

    return math.degrees(fi2), lng + math.degrees(lambda_)


def _angulo(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """O ângulo ao centro da Terra entre dois pontos, em radianos, pelos
    vetores unitários (atan2 de |a×b| e a·b, a conta do S2 que o Mongo usa no
    `$centerSphere`): não passa pela haversine do `distancia_metros`."""

    def vetor(lat, lng):
        fi, lam = math.radians(lat), math.radians(lng)
        return (math.cos(fi) * math.cos(lam), math.cos(fi) * math.sin(lam), math.sin(fi))

    a, b = vetor(lat1, lng1), vetor(lat2, lng2)
    cruz = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])

    return math.atan2(math.hypot(*cruz), sum(x * y for x, y in zip(a, b)))


def _raio_do_filtro(filtro: dict) -> float:
    return filtro["loc"]["$geoWithin"]["$centerSphere"][1]


# --- Duplicados (DuplicadosTest.php) ---


def test_o_raio_e_50_metros():
    assert RAIO_DUPLICADOS_M == 50
    assert type(RAIO_DUPLICADOS_M) is int


def test_encontra_as_lojas_a_menos_de_50_metros_por_ordem_de_distancia():
    candidatos = [
        _loja(1, "A 51 m", 51.0),
        _loja(2, "A 49 m", 49.0),
        _loja(3, "A 20 m", 20.0),
        _loja(4, "A 300 m", 300.0),
    ]

    assert encontrar_duplicados(candidatos, LAT, LNG) == [
        {"id": _id(3), "nome": "A 20 m", "distancia_m": 20},
        {"id": _id(2), "nome": "A 49 m", "distancia_m": 49},
    ]


def test_exatamente_50_metros_nao_e_duplicado():
    # A conta dá 49,99999999972 m: é a TOLERANCIA_M que a deixa de fora.
    assert encontrar_duplicados([_loja(1, "A 50 m", 50.0)], LAT, LNG) == []


@pytest.mark.parametrize(
    "metros, duplicado, distancia_m",
    [
        (49.4, True, 49),
        (30.6, True, 31),
        (49.6, True, 49),
        (49.7, True, 49),
        (49.99, True, 49),
        (50.01, False, 50),
        (0.4, True, 0),
        (0.0, True, 0),
    ],
    ids=[
        "49,4 m conta como 49",
        "30,6 m arredonda para 31",
        "49,6 m é duplicado e mostra-se 49",
        "49,7 m é duplicado e mostra-se 49",
        "49,99 m é duplicado e mostra-se 49",
        "50,01 m não é duplicado",
        "0,4 m conta como 0",
        "no mesmo ponto",
    ],
)
def test_conta_as_distancias_em_metros_inteiros(metros, duplicado, distancia_m):
    encontradas = encontrar_duplicados([_loja(1, "Café", metros)], LAT, LNG)

    assert encontradas == ([{"id": _id(1), "nome": "Café", "distancia_m": distancia_m}] if duplicado else [])
    assert all(type(loja["distancia_m"]) is int for loja in encontradas)


def test_com_as_coordenadas_como_a_base_as_guarda_a_49_virgula_7_metros_e_duplicado():
    # A base guarda 6 casas: esta loja fica a 49,70 m (e não a 49,7 m exatos).
    lat = arredondar(LAT + 49.7 / METROS_POR_GRAU, 6)
    candidatos = [{"id": _id(2), "nome": "Quiosque", "lat": lat, "lng": arredondar(LNG, 6)}]

    assert lat == 38.707947
    assert distancia_metros(LAT, LNG, lat, LNG) == pytest.approx(49.70, abs=0.01)
    assert encontrar_duplicados(candidatos, LAT, LNG) == [{"id": _id(2), "nome": "Quiosque", "distancia_m": 49}]


def test_com_outro_raio_a_distancia_tambem_fica_abaixo_dele():
    assert encontrar_duplicados([_loja(1, "A 99,8 m", 99.8)], LAT, LNG, None, 100) == [
        {"id": _id(1), "nome": "A 99,8 m", "distancia_m": 99}
    ]


def test_ignora_a_loja_excluida():
    candidatos = [_loja(7, "Ela própria", 0.0), _loja(8, "A vizinha", 30.0)]

    assert encontrar_duplicados(candidatos, LAT, LNG, _id(7)) == [
        {"id": _id(8), "nome": "A vizinha", "distancia_m": 30}
    ]


def test_aceita_outro_raio():
    candidatos = [_loja(1, "A 51 m", 51.0), _loja(2, "A 120 m", 120.0)]

    assert encontrar_duplicados(candidatos, LAT, LNG, None, 100) == [
        {"id": _id(1), "nome": "A 51 m", "distancia_m": 51}
    ]


def test_sem_candidatos_nao_ha_duplicados():
    assert encontrar_duplicados([], LAT, LNG) == []


def test_aceita_os_documentos_como_o_mongo_os_devolve():
    # Era "aceita as linhas da BD com números em texto": o PDO devolvia o id e
    # as colunas DECIMAL(9,6) em texto. No Mongo, o id é um uuid em texto e
    # lat/lng são números com 6 casas; os outros campos do documento não
    # passam para a resposta. 0,0004° de latitude ≈ 44,5 m.
    candidatos = [
        {
            "id": "5b1c7a3e-9d2f-4e8a-b6c4-1f0e2d3c4b5a",
            "nome": "Mercearia",
            "lat": 38.707900,
            "lng": -9.136400,
            "fase": "potencial",
            "loc": {"type": "Point", "coordinates": [-9.136400, 38.707900]},
        }
    ]

    encontradas = encontrar_duplicados(candidatos, LAT, LNG)

    assert encontradas == [{"id": "5b1c7a3e-9d2f-4e8a-b6c4-1f0e2d3c4b5a", "nome": "Mercearia", "distancia_m": 44}]
    assert list(encontradas[0]) == ["id", "nome", "distancia_m"]


def test_a_exclusao_funciona_com_o_id_em_texto():
    candidatos = [{"id": "5b1c7a3e-9d2f-4e8a-b6c4-1f0e2d3c4b5a", "nome": "Mercearia", "lat": 38.7075, "lng": -9.1364}]

    assert encontrar_duplicados(candidatos, LAT, LNG, "5b1c7a3e-9d2f-4e8a-b6c4-1f0e2d3c4b5a") == []


def test_com_a_mesma_distancia_ordena_pelo_id():
    candidatos = [_loja(9, "Nove", 10.0), _loja(4, "Quatro", 10.0), _loja(6, "Seis", 5.0)]

    assert [loja["id"] for loja in encontrar_duplicados(candidatos, LAT, LNG)] == [_id(6), _id(4), _id(9)]


# --- Armadilhas do Python e pormenores do PHP ---


def test_ordena_pela_distancia_exata_e_nao_pela_arredondada():
    # As duas mostram-se a 10 m; a de 9,6 m vem primeiro, mesmo com o id
    # maior (o usort do PHP comparava os metros sem arredondar).
    candidatos = [_loja(1, "A 10,4 m", 10.4), _loja(2, "A 9,6 m", 9.6)]

    assert encontrar_duplicados(candidatos, LAT, LNG) == [
        {"id": _id(2), "nome": "A 9,6 m", "distancia_m": 10},
        {"id": _id(1), "nome": "A 10,4 m", "distancia_m": 10},
    ]


def test_o_id_desempata_pelo_texto():
    # Os ids do portal são uuids em texto: o desempate é pela ordem do texto.
    candidatos = [
        {"id": "f3a1c2d4-0000-4000-8000-000000000000", "nome": "F", "lat": LAT, "lng": LNG},
        {"id": "0b9e8d7c-0000-4000-8000-000000000000", "nome": "Zero", "lat": LAT, "lng": LNG},
        {"id": "a1b2c3d4-0000-4000-8000-000000000000", "nome": "A", "lat": LAT, "lng": LNG},
    ]

    assert [loja["nome"] for loja in encontrar_duplicados(candidatos, LAT, LNG)] == ["Zero", "A", "F"]


@pytest.mark.parametrize(
    "metros, distancia_m",
    [
        (0.5, 1),
        (2.5, 3),
        (30.5, 31),
        (48.5, 49),
        (48.49999999999999, 48),
        (49.5, 49),
        (49.9999989, 49),
    ],
    ids=[
        "0,5 m mostra-se 1 (o round do Python dava 0)",
        "2,5 m mostra-se 3 (o round do Python dava 2)",
        "30,5 m mostra-se 31 (o round do Python dava 30)",
        "48,5 m mostra-se 49 (o round do Python dava 48)",
        "mesmo abaixo de 48,5 m mostra-se 48",
        "49,5 m arredonda para 50 e mostra-se 49",
        "mesmo abaixo da tolerância mostra-se 49",
    ],
)
def test_o_meio_metro_arredonda_para_longe_do_zero(monkeypatch, metros, distancia_m):
    # Distâncias exatas, que pelas coordenadas não se conseguem: a distância
    # fingida é a latitude do candidato.
    monkeypatch.setattr(geo, "distancia_metros", lambda lat1, lng1, lat2, lng2: lat2)

    encontradas = encontrar_duplicados([{"id": _id(1), "nome": "Café", "lat": metros, "lng": 0.0}], LAT, LNG)

    assert encontradas == [{"id": _id(1), "nome": "Café", "distancia_m": distancia_m}]
    assert type(encontradas[0]["distancia_m"]) is int


@pytest.mark.parametrize(
    "metros",
    [50 - TOLERANCIA_M, 49.9999999997, 50.0, 50.4],
    ids=["no limite da tolerância", "50 m com o erro das contas", "50 m exatos", "50,4 m (arredondaria para 50)"],
)
def test_a_tolerancia_deixa_de_fora_o_que_mede_50_metros(monkeypatch, metros):
    monkeypatch.setattr(geo, "distancia_metros", lambda lat1, lng1, lat2, lng2: lat2)

    assert encontrar_duplicados([{"id": _id(1), "nome": "Café", "lat": metros, "lng": 0.0}], LAT, LNG) == []


def test_a_tolerancia_e_um_milionesimo_de_metro():
    assert TOLERANCIA_M == 1e-6


def test_nao_mexe_nos_candidatos():
    candidatos = [_loja(1, "A 20 m", 20.0), _loja(2, "A 60 m", 60.0)]
    copia = [dict(loja) for loja in candidatos]

    encontrar_duplicados(candidatos, LAT, LNG, _id(2))

    assert candidatos == copia


# --- Pré-filtro do Mongo (eram os testes de Duplicados::caixa) ---


def test_o_pre_filtro_e_um_circulo_de_60_metros_a_volta_do_ponto():
    assert filtro_candidatos(38.7, -9.1) == {"loc": {"$geoWithin": {"$centerSphere": [[-9.1, 38.7], 60 / 6371000]}}}


def test_a_folga_do_pre_filtro_e_10_metros():
    assert FOLGA_PREFILTRO_M == 10
    assert _raio_do_filtro(filtro_candidatos(LAT, LNG)) * RAIO_TERRA_M == pytest.approx(60.0, abs=1e-9)


def test_o_pre_filtro_poe_a_longitude_primeiro():
    # GeoJSON: [lng, lat]. Trocadas, a loja de Lisboa ia procurar-se no Índico.
    centro = filtro_candidatos(LAT, LNG)["loc"]["$geoWithin"]["$centerSphere"][0]

    assert centro == [LNG, LAT]


def test_com_excluir_id_o_pre_filtro_deixa_de_fora_a_propria_loja():
    assert filtro_candidatos(38.7, -9.1, excluir_id="x") == {
        "loc": {"$geoWithin": {"$centerSphere": [[-9.1, 38.7], 60 / 6371000]}},
        "id": {"$ne": "x"},
    }


def test_sem_excluir_id_o_pre_filtro_nao_olha_para_o_id():
    assert "id" not in filtro_candidatos(38.7, -9.1)
    assert "id" not in filtro_candidatos(38.7, -9.1, None)


def test_o_pre_filtro_usa_o_raio_dos_duplicados_por_omissao():
    assert filtro_candidatos(LAT, LNG) == filtro_candidatos(LAT, LNG, None, RAIO_DUPLICADOS_M)


def test_com_outro_raio_o_pre_filtro_alarga_com_a_mesma_folga():
    assert _raio_do_filtro(filtro_candidatos(LAT, LNG, None, 100)) == 110 / 6371000


def test_o_raio_do_pre_filtro_nao_depende_da_latitude():
    # A caixa do autónomo alargava a longitude por 1/cos(lat); o círculo do
    # $centerSphere é um ângulo ao centro da Terra, igual em todo o lado.
    assert _raio_do_filtro(filtro_candidatos(0.0, 0.0)) == _raio_do_filtro(filtro_candidatos(42.2, -6.1))


def test_o_pre_filtro_e_uma_estrutura_nova_em_cada_chamada():
    # Quem chama pode juntar-lhe chaves sem estragar a chamada seguinte.
    primeiro = filtro_candidatos(LAT, LNG)
    primeiro["loc"]["$geoWithin"]["$centerSphere"][0].append(0)
    primeiro["id"] = {"$ne": "x"}

    assert filtro_candidatos(LAT, LNG) == {"loc": {"$geoWithin": {"$centerSphere": [[LNG, LAT], 60 / 6371000]}}}


@pytest.mark.parametrize("lat", [37.018, 38.7075, 42.2], ids=["Faro", "Lisboa", "limite norte"])
def test_o_pre_filtro_nunca_deixa_de_fora_um_duplicado(lat):
    # O duplicado mais longe está quase a 50 m. Medem-se pontos a 49,99 m e a
    # 50,5 m em 72 rumos, como chegam e com as 6 casas com que se guardam: o
    # ângulo ao centro é sempre menor do que o raio do $centerSphere.
    raio = _raio_do_filtro(filtro_candidatos(lat, LNG))

    for metros in (49.99, 50.5):
        for rumo in range(0, 360, 5):
            lat_ponto, lng_ponto = _destino(lat, LNG, metros, rumo)
            guardado = (arredondar(lat_ponto, 6), arredondar(lng_ponto, 6))

            assert distancia_metros(lat, LNG, lat_ponto, lng_ponto) == pytest.approx(metros, abs=1e-6)
            assert _angulo(lat, LNG, lat_ponto, lng_ponto) < raio, f"{metros} m, rumo {rumo}°"
            assert _angulo(lat, LNG, *guardado) < raio, f"{metros} m com 6 casas, rumo {rumo}°"


@pytest.mark.parametrize("lat", [37.018, 38.7075, 42.2], ids=["Faro", "Lisboa", "limite norte"])
def test_tudo_o_que_e_duplicado_esta_dentro_do_pre_filtro(lat):
    # Visto do outro lado: cada loja que o encontrar_duplicados dá como
    # duplicada (a 49,99 m, guardada com 6 casas) está dentro do círculo do
    # pré-filtro (as duas contas são da mesma esfera).
    raio = _raio_do_filtro(filtro_candidatos(lat, LNG))
    candidatos = {}
    for rumo in range(0, 360, 5):
        lat_ponto, lng_ponto = _destino(lat, LNG, 49.99, rumo)
        candidatos[_id(rumo)] = {
            "id": _id(rumo),
            "nome": f"Rumo {rumo}",
            "lat": arredondar(lat_ponto, 6),
            "lng": arredondar(lng_ponto, 6),
        }

    encontradas = encontrar_duplicados(list(candidatos.values()), lat, LNG)

    assert len(encontradas) > 0
    for loja in encontradas:
        guardada = candidatos[loja["id"]]
        assert _angulo(lat, LNG, guardada["lat"], guardada["lng"]) < raio, loja["nome"]


def test_o_pre_filtro_nao_e_muito_maior_do_que_o_circulo():
    raio = _raio_do_filtro(filtro_candidatos(LAT, LNG))

    a_norte = _destino(LAT, LNG, 60.5, 0)
    a_leste = _destino(LAT, LNG, 60.5, 90)

    assert _angulo(LAT, LNG, *a_norte) > raio
    assert _angulo(LAT, LNG, *a_leste) > raio
