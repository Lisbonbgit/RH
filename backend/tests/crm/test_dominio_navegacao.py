"""Os links de navegação do Google Maps e do Waze e os blocos de 9 (crm/dominio/navegacao.py), F3 / T3.10.

Desenho original §8.2 e plano F3 §1 ("Links de navegação"): os links calculam-se
no servidor e vão na API (`paragem.links`, `rota.blocos_google`); o frontend só
os desenha como `<a href>` tocados pela pessoa, depois do `hrefNavegacao`. Nenhum
precisa de chave da Google.

- por paragem, um destino só (o Waze só aceita um):
  - `https://www.google.com/maps/dir/?api=1&destination=LAT,LNG&travelmode=driving&dir_action=navigate[&avoid=tolls]`
  - `https://waze.com/ul?ll=LAT,LNG&navigate=yes[&avoid_tolls=true]`
- "Abrir paragens X–Y no Google Maps" em blocos de 9, **sem origem** (parte de
  onde o telemóvel está), com os 8 primeiros em `waypoints` (separados por `|`
  codificado, `%7C`) e o 9.º como destino; o rótulo diz quantas paragens leva.

As coordenadas vão com 6 casas, arredondadas meio-para-longe-do-zero (como se
guardam). Uma coordenada que não é um número (NaN, `None`, `bool`, texto) não dá
link (`None`); nos blocos, essa paragem fica de fora.

Correção "T3.10" do plano: o `avoid_tolls=true` do Waze não está na documentação
oficial dos deep links (lá é uma definição da app); o link mantém-se fiel ao
§8.2 e a confirmação no telemóvel da carrinha fica no §14 do dossiê.
"""
import ast
import math
from pathlib import Path

import pytest

import crm.dominio.navegacao as navegacao
from crm.dominio.navegacao import TAMANHO_BLOCO_GOOGLE, blocos_google, link_google, link_waze

FICHEIRO = Path(navegacao.__file__)

GOOGLE = "https://www.google.com/maps/dir/?api=1"
WAZE = "https://waze.com/ul?"

# Pontos públicos de Lisboa (os dos cenários do ORS, T3.6), com 6 casas.
PONTOS = [
    (38.7075, -9.1364),
    (38.7253, -9.15),
    (38.6916, -9.216),
    (38.7223, -9.1393),
    (38.7139, -9.1334),
    (38.7369, -9.1427),
    (38.7046, -9.1774),
    (38.7578, -9.1557),
    (38.7166, -9.1397),
    (38.7686, -9.0949),
]


def _paragens(n):
    """`n` paragens numeradas de 1 a n, com coordenadas que dão para ler no link."""
    return [(numero, 38.0 + numero / 1000, -9.0 - numero / 1000) for numero in range(1, n + 1)]


def _texto(numero):
    return f"{38.0 + numero / 1000:.6f},{-9.0 - numero / 1000:.6f}"


# --- link_google ----------------------------------------------------------------------------------


def test_link_google_exato():
    assert link_google(38.7108, -9.1369, False) == (
        "https://www.google.com/maps/dir/?api=1&destination=38.710800,-9.136900&travelmode=driving&dir_action=navigate"
    )


def test_link_google_a_evitar_portagens_acaba_em_avoid_tolls():
    assert link_google(38.7108, -9.1369, True) == (
        "https://www.google.com/maps/dir/?api=1&destination=38.710800,-9.136900"
        "&travelmode=driving&dir_action=navigate&avoid=tolls"
    )


def test_link_google_nunca_leva_origem_nem_waypoints():
    for evitar in (False, True):
        link = link_google(38.7108, -9.1369, evitar)
        assert "origin" not in link
        assert "waypoints" not in link


# --- link_waze ------------------------------------------------------------------------------------


def test_link_waze_exato():
    assert link_waze(38.7108, -9.1369, False) == "https://waze.com/ul?ll=38.710800,-9.136900&navigate=yes"


def test_link_waze_a_evitar_portagens_leva_avoid_tolls_true():
    assert link_waze(38.7108, -9.1369, True) == "https://waze.com/ul?ll=38.710800,-9.136900&navigate=yes&avoid_tolls=true"


def test_o_waze_usa_o_nome_dele_e_nao_o_do_google():
    assert "avoid=tolls" not in link_waze(38.7108, -9.1369, True)
    assert "avoid_tolls" not in link_google(38.7108, -9.1369, True)


# --- As coordenadas -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lat, lng, texto",
    [
        (38.7223445, -9.1393005, "38.722345,-9.139301"),  # meio-para-longe-do-zero (o round dava 38.722344,-9.139300)
        (38.1234564, -9.1234564, "38.123456,-9.123456"),
        (39, -8, "39.000000,-8.000000"),  # inteiros
        (38.7, -9.1, "38.700000,-9.100000"),
        (-0.0000001, 0.0000001, "0.000000,0.000000"),  # sem "-0.000000"
        (90, 180, "90.000000,180.000000"),
        (-90, -180, "-90.000000,-180.000000"),
    ],
)
def test_coordenadas_com_6_casas_arredondadas_como_se_guardam(lat, lng, texto):
    assert link_google(lat, lng, False) == f"{GOOGLE}&destination={texto}&travelmode=driving&dir_action=navigate"
    assert link_waze(lat, lng, False) == f"{WAZE}ll={texto}&navigate=yes"


@pytest.mark.parametrize(
    "lat, lng",
    [
        (math.nan, -9.1),
        (38.7, math.nan),
        (None, -9.1),
        (38.7, None),
        (True, -9.1),
        (38.7, False),
        (math.inf, -9.1),
        (38.7, -math.inf),
        ("38.7", -9.1),
        (38.7, "-9.1"),
        ([38.7], -9.1),
        (90.0000001, -9.1),
        (38.7, -180.000001),
        (2**1100, -9.1),
    ],
)
def test_sem_coordenadas_validas_nao_ha_link(lat, lng):
    assert link_google(lat, lng, False) is None
    assert link_waze(lat, lng, False) is None
    assert link_google(lat, lng, True) is None
    assert link_waze(lat, lng, True) is None


@pytest.mark.parametrize("evitar", [None, 1, 0, "true", "", [], 1.0])
def test_evitar_portagens_so_aceita_bool(evitar):
    with pytest.raises(ValueError):
        link_google(38.7, -9.1, evitar)
    with pytest.raises(ValueError):
        link_waze(38.7, -9.1, evitar)
    with pytest.raises(ValueError):
        blocos_google(_paragens(2), evitar)


def test_os_links_nao_tem_espacos_aspas_nem_sinais_de_html():
    """O `hrefNavegacao` do frontend (T3.26) recusa-os; o servidor nunca os gera."""
    links = [link_google(38.7, -9.1, e) for e in (False, True)] + [link_waze(38.7, -9.1, e) for e in (False, True)]
    links += [bloco["href"] for e in (False, True) for bloco in blocos_google(_paragens(19), e)]
    for link in links:
        assert not set(link) & set(" \t\n\"'<>|\\`")
        assert link.startswith((GOOGLE + "&", WAZE))


# --- blocos_google --------------------------------------------------------------------------------


def test_o_bloco_tem_9_paragens():
    assert TAMANHO_BLOCO_GOOGLE == 9


def test_uma_paragem_e_um_bloco_sem_waypoints():
    assert blocos_google([(1, 38.7108, -9.1369)], False) == [
        {
            "de": 1,
            "ate": 1,
            "quantas": 1,
            "rotulo": "Abrir paragem 1 no Google Maps (1 paragem)",
            "href": "https://www.google.com/maps/dir/?api=1&destination=38.710800,-9.136900&travelmode=driving&dir_action=navigate",
        }
    ]


def test_o_bloco_de_uma_paragem_e_o_link_da_paragem():
    for evitar in (False, True):
        [bloco] = blocos_google([(7, 38.7108, -9.1369)], evitar)
        assert bloco["href"] == link_google(38.7108, -9.1369, evitar)
        assert bloco["rotulo"] == "Abrir paragem 7 no Google Maps (1 paragem)"


def test_nove_paragens_sao_um_bloco_com_8_waypoints_e_o_destino_no_9():
    paragens = [(numero, lat, lng) for numero, (lat, lng) in enumerate(PONTOS[:9], start=1)]
    assert blocos_google(paragens, False) == [
        {
            "de": 1,
            "ate": 9,
            "quantas": 9,
            "rotulo": "Abrir paragens 1–9 no Google Maps (9 paragens)",
            "href": (
                "https://www.google.com/maps/dir/?api=1&destination=38.716600,-9.139700"
                "&waypoints=38.707500,-9.136400%7C38.725300,-9.150000%7C38.691600,-9.216000%7C38.722300,-9.139300"
                "%7C38.713900,-9.133400%7C38.736900,-9.142700%7C38.704600,-9.177400%7C38.757800,-9.155700"
                "&travelmode=driving&dir_action=navigate"
            ),
        }
    ]


def test_a_evitar_portagens_o_bloco_acaba_em_avoid_tolls():
    [bloco] = blocos_google(_paragens(3), True)
    assert bloco["href"] == (
        f"{GOOGLE}&destination={_texto(3)}&waypoints={_texto(1)}%7C{_texto(2)}"
        "&travelmode=driving&dir_action=navigate&avoid=tolls"
    )


def test_os_blocos_nunca_tem_origem():
    """Sem origem: o Google Maps parte de onde o telemóvel está (desenho §8.2)."""
    for n in (1, 2, 9, 10, 48):
        for bloco in blocos_google(_paragens(n), False):
            assert "origin" not in bloco["href"]
            assert "dir_action=navigate" in bloco["href"]


def test_o_separador_dos_waypoints_vai_codificado():
    [bloco] = blocos_google(_paragens(3), False)
    assert "|" not in bloco["href"]
    assert f"waypoints={_texto(1)}%7C{_texto(2)}&" in bloco["href"]


@pytest.mark.parametrize(
    "n, esperado",
    [
        (2, [(1, 2, 2)]),
        (8, [(1, 8, 8)]),
        (9, [(1, 9, 9)]),
        (10, [(1, 9, 9), (10, 10, 1)]),
        (11, [(1, 9, 9), (10, 11, 2)]),
        (18, [(1, 9, 9), (10, 18, 9)]),
        (19, [(1, 9, 9), (10, 18, 9), (19, 19, 1)]),
        (48, [(1, 9, 9), (10, 18, 9), (19, 27, 9), (28, 36, 9), (37, 45, 9), (46, 48, 3)]),
    ],
)
def test_blocos_de_9_e_o_resto(n, esperado):
    blocos = blocos_google(_paragens(n), False)
    assert [(b["de"], b["ate"], b["quantas"]) for b in blocos] == esperado
    for bloco in blocos:
        assert list(bloco) == ["de", "ate", "quantas", "rotulo", "href"]
        numeros = range(bloco["de"], bloco["ate"] + 1)
        # O destino é a última do bloco; as outras vão por ordem nos waypoints.
        assert f"&destination={_texto(bloco['ate'])}&" in bloco["href"]
        if bloco["quantas"] == 1:
            assert "waypoints" not in bloco["href"]
            assert bloco["rotulo"] == f"Abrir paragem {bloco['de']} no Google Maps (1 paragem)"
        else:
            pontos = "%7C".join(_texto(numero) for numero in numeros[:-1])
            assert f"&waypoints={pontos}&" in bloco["href"]
            assert bloco["rotulo"] == (
                f"Abrir paragens {bloco['de']}–{bloco['ate']} no Google Maps ({bloco['quantas']} paragens)"
            )


def test_o_rotulo_usa_o_travessao_e_o_plural():
    blocos = blocos_google(_paragens(11), False)
    assert [b["rotulo"] for b in blocos] == [
        "Abrir paragens 1–9 no Google Maps (9 paragens)",
        "Abrir paragens 10–11 no Google Maps (2 paragens)",
    ]
    assert "–" in blocos[0]["rotulo"]


def test_sem_paragens_nao_ha_blocos():
    assert blocos_google([], False) == []
    assert blocos_google((), True) == []


def test_so_as_paragens_com_coordenadas_entram_nos_blocos():
    paragens = _paragens(11)
    paragens[2] = (3, None, -9.1)
    paragens[4] = (5, 38.7, math.nan)
    paragens[6] = (7, True, -9.1)
    blocos = blocos_google(paragens, False)
    # Ficam 8: um só bloco, de 1 a 11, que diz quantas leva de facto.
    assert [(b["de"], b["ate"], b["quantas"]) for b in blocos] == [(1, 11, 8)]
    assert blocos[0]["rotulo"] == "Abrir paragens 1–11 no Google Maps (8 paragens)"
    pontos = "%7C".join(_texto(n) for n in (1, 2, 4, 6, 8, 9, 10))
    assert blocos[0]["href"] == f"{GOOGLE}&destination={_texto(11)}&waypoints={pontos}&travelmode=driving&dir_action=navigate"


def test_sem_nenhuma_coordenada_valida_nao_ha_blocos():
    assert blocos_google([(1, None, None), (2, math.nan, -9.1)], False) == []


def test_os_blocos_seguem_a_ordem_recebida():
    """A ordem é a da rota (quem chama passa a secção "rota" pela ordem): não se reordena."""
    paragens = [(2, 38.002, -9.002), (1, 38.001, -9.001)]
    [bloco] = blocos_google(paragens, False)
    assert bloco["href"] == f"{GOOGLE}&destination={_texto(1)}&waypoints={_texto(2)}&travelmode=driving&dir_action=navigate"
    assert (bloco["de"], bloco["ate"]) == (2, 1)


@pytest.mark.parametrize("tamanho, esperado", [(1, [1, 1, 1]), (2, [2, 1]), (3, [3]), (10, [3])])
def test_outro_tamanho_de_bloco(tamanho, esperado):
    assert [b["quantas"] for b in blocos_google(_paragens(3), False, tamanho=tamanho)] == esperado


@pytest.mark.parametrize("tamanho", [0, -1, 11, True, 9.0, "9", None])
def test_tamanho_do_bloco_invalido(tamanho):
    """De 1 a 10: o Google aceita no máximo 9 waypoints mais o destino."""
    with pytest.raises(ValueError):
        blocos_google(_paragens(3), False, tamanho=tamanho)


@pytest.mark.parametrize(
    "paragens",
    [
        [(1, 38.7)],
        [(1, 38.7, -9.1, 4)],
        [{"numero": 1, "lat": 38.7, "lng": -9.1}],
        ["1,38.7,-9.1"],
        [(True, 38.7, -9.1)],
        [(0, 38.7, -9.1)],
        [(1.0, 38.7, -9.1)],
        [("1", 38.7, -9.1)],
        [(None, 38.7, -9.1)],
    ],
)
def test_paragens_numeradas_estragadas(paragens):
    with pytest.raises(ValueError):
        blocos_google(paragens, False)


@pytest.mark.parametrize("paragens", [None, "abc", 3, {(1, 38.7, -9.1)}, (p for p in [(1, 38.7, -9.1)])])
def test_paragens_tem_de_vir_numa_lista(paragens):
    with pytest.raises(TypeError):
        blocos_google(paragens, False)


def test_blocos_devolve_estruturas_novas_e_nao_muda_a_entrada():
    paragens = _paragens(10)
    copia = list(paragens)
    primeiro = blocos_google(paragens, False)
    segundo = blocos_google(paragens, False)
    assert paragens == copia
    assert primeiro == segundo
    assert primeiro is not segundo
    assert all(a is not b for a, b in zip(primeiro, segundo))


# --- O módulo -------------------------------------------------------------------------------------


def test_navegacao_nunca_chama_o_round_do_python():
    """O `round` arredonda para o par (38,7223445 → 38,722344): usa-se `numeros.arredondar`."""
    chamadas = [
        no for no in ast.walk(ast.parse(FICHEIRO.read_text(encoding="utf-8")))
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Name) and no.func.id == "round"
    ]
    assert chamadas == []


def test_navegacao_nao_importa_nada_da_rede_nem_chaves():
    """Os links não precisam de chave nem de pedidos (desenho §8.2): o módulo é puro."""
    nomes = set()
    for no in ast.walk(ast.parse(FICHEIRO.read_text(encoding="utf-8"))):
        if isinstance(no, ast.Import):
            nomes |= {alias.name.split(".")[0] for alias in no.names}
        elif isinstance(no, ast.ImportFrom) and no.module:
            nomes.add(no.module.split(".")[0])
    assert nomes & {"os", "httpx", "requests", "urllib", "socket", "dotenv"} == set()
