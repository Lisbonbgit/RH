"""O pedido ao Directions do openrouteservice e a leitura dos troços
(crm/dominio/directions.py), F3 / T3.7.

Plano F3 §1 ("Directions") e §0 regra 12: o pedido é `POST
/v2/directions/driving-car/json` com `{coordinates, instructions: true,
geometry: true, elevation: false, units: "m"}` e, quando se evitam portagens,
`options.avoid_features: ["tollways"]`. Ao openrouteservice só vão
coordenadas e essas constantes — nunca nomes, telefones, moradas ou uuids (o
teste dos canários, risco R4). O `instructions: true` é preciso para os
`segments` (risco R2).

A resposta lê-se com um parser estrito (risco R3): o que não bater certo é a
`RespostaInvalida` do `vroom.py` (→ 503 nas rotas, T3.21). Correções aplicadas:
- "T3.7 (+ T3.13, T3.21)": o ORS deixa de fora a `distance`/`duration` de um
  troço (ou do `summary`) quando valem 0 (pontos repetidos): uma chave em
  falta conta como 0; presente, negativa, não finita ou `bool` continua
  inválida; sem `summary`, os totais são a soma dos troços. A fixture
  `direcoes-ponto-repetido.json` traz um troço só com `steps`;
- "T3.12 / T3.43": os testes sobre as fixtures (que o dono vai regravar)
  verificam só a forma (`segments` = n − 1); os valores exatos vêm de
  respostas escritas no próprio teste. O `direcoes-erro-2010` usa um ponto
  fixo no Tejo (`rio_tejo` no `cenarios.json`);
- "T3.7 / T3.9 / T3.13 / T3.21": as geometrias dos testes fazem-se com o
  `polilinha.codificar`.
"""
import ast
import copy
import json
import math
import re
from pathlib import Path

import pytest

import crm.dominio.directions as directions
from crm.dominio import geo, rotas, vroom
from crm.dominio.directions import Trocos, interpretar_direcoes, pedido_direcoes
from crm.dominio.polilinha import codificar, descodificar
from crm.dominio.vroom import RespostaInvalida, paragem_calculo

from .test_dominio_vroom import CANARIOS_TEXTO, MEMBRO, REGIAO, _cenario_completo, _folhas

FIXTURES = Path(__file__).parent / "fixtures" / "ors"
FICHEIRO = Path(directions.__file__)

FABRICA = (38.7223, -9.1393)
COMERCIO = (38.7075, -9.1364)
MARQUES = (38.7253, -9.15)
BELEM = (38.6916, -9.216)


def _ler(nome):
    return json.loads((FIXTURES / nome).read_text(encoding="utf-8"))


# --- pedido_direcoes ------------------------------------------------------------------------


def test_o_corpo_sem_portagens_a_evitar():
    corpo = pedido_direcoes([FABRICA, MARQUES, COMERCIO, BELEM, FABRICA], False)
    assert corpo == {
        "coordinates": [[-9.1393, 38.7223], [-9.15, 38.7253], [-9.1364, 38.7075], [-9.216, 38.6916], [-9.1393, 38.7223]],
        "instructions": True,
        "geometry": True,
        "elevation": False,
        "units": "m",
    }
    assert "options" not in corpo


def test_o_corpo_a_evitar_portagens():
    corpo = pedido_direcoes([FABRICA, COMERCIO, FABRICA], True)
    assert corpo == {
        "coordinates": [[-9.1393, 38.7223], [-9.1364, 38.7075], [-9.1393, 38.7223]],
        "instructions": True,
        "geometry": True,
        "elevation": False,
        "units": "m",
        "options": {"avoid_features": ["tollways"]},
    }


def test_os_booleanos_do_corpo_sao_mesmo_booleanos():
    corpo = pedido_direcoes([FABRICA, COMERCIO], False)
    assert corpo["instructions"] is True and corpo["geometry"] is True and corpo["elevation"] is False


def test_as_coordenadas_vao_como_lng_lat_arredondadas_meio_para_longe_do_zero_as_6_casas():
    """O mesmo arredondamento do pedido ao VROOM (`vroom.ponto_ors`): 38,7223445
    → 38,722345 e −9,1393005 → −9,139301 (o `round` dava 38,722344 e −9,1393)."""
    corpo = pedido_direcoes([(38.7223445, -9.1393005), (38.7075, -9.1364)], False)
    assert corpo["coordinates"] == [[-9.139301, 38.722345], [-9.1364, 38.7075]]


def test_os_pontos_podem_ser_tuplos_ou_listas_e_vao_pela_ordem_recebida():
    corpo = pedido_direcoes(([38.7253, -9.15], (38.7075, -9.1364), [38.6916, -9.216]), False)
    assert corpo["coordinates"] == [[-9.15, 38.7253], [-9.1364, 38.7075], [-9.216, 38.6916]]


def test_pontos_repetidos_vao_como_vieram():
    """Duas lojas nas mesmas coordenadas: o Directions aceita-as (o troço entre elas tem 0 m)."""
    corpo = pedido_direcoes([FABRICA, COMERCIO, COMERCIO, FABRICA], False)
    assert corpo["coordinates"][1] == corpo["coordinates"][2] == [-9.1364, 38.7075]


def test_dois_pontos_chegam_e_menos_de_dois_nao():
    assert len(pedido_direcoes([FABRICA, COMERCIO], False)["coordinates"]) == 2
    for pontos in ([], [FABRICA]):
        with pytest.raises(ValueError):
            pedido_direcoes(pontos, False)


def test_no_maximo_50_pontos():
    """O Directions aceita 50 coordenadas: as 48 paragens da rota mais o início e o fim."""
    assert directions.MAXIMO_PONTOS == 50
    assert directions.MAXIMO_PONTOS == rotas.LIMITE_PARAGENS + 2
    assert len(pedido_direcoes([COMERCIO] * 50, False)["coordinates"]) == 50
    with pytest.raises(ValueError):
        pedido_direcoes([COMERCIO] * 51, False)


@pytest.mark.parametrize("evitar", [1, 0, None, "true", "sim", [], 1.0])
def test_evitar_portagens_tem_de_ser_um_booleano(evitar):
    with pytest.raises(ValueError):
        pedido_direcoes([FABRICA, COMERCIO], evitar)


@pytest.mark.parametrize(
    "ponto",
    [None, (38.7,), (38.7, -9.1, 0), ("38.7", "-9.1"), (math.nan, -9.1), (38.7, math.inf), (True, -9.1),
     (38.7, False), {"lat": 38.7, "lng": -9.1}, "38.7,-9.1"],
)
def test_recusa_um_ponto_que_nao_e_um_par_lat_lng(ponto):
    with pytest.raises(ValueError):
        pedido_direcoes([FABRICA, ponto, FABRICA], False)


@pytest.mark.parametrize("pontos", [None, "38.7,-9.1", {"lat": 38.7, "lng": -9.1}, (p for p in (FABRICA, COMERCIO)), 3])
def test_os_pontos_tem_de_vir_numa_lista(pontos):
    with pytest.raises(TypeError):
        pedido_direcoes(pontos, False)


def test_pedido_direcoes_nao_muda_os_pontos_e_devolve_estruturas_novas():
    pontos = [[38.7223, -9.1393], [38.7075, -9.1364]]
    copia = copy.deepcopy(pontos)
    primeiro = pedido_direcoes(pontos, True)
    segundo = pedido_direcoes(pontos, True)
    assert pontos == copia
    assert primeiro == segundo
    assert primeiro["coordinates"] is not segundo["coordinates"]
    assert primeiro["coordinates"][0] is not pontos[0]
    assert primeiro["options"] is not segundo["options"]
    assert primeiro["options"]["avoid_features"] is not segundo["options"]["avoid_features"]


def test_o_corpo_e_json_sem_nan():
    json.dumps(pedido_direcoes([FABRICA, MARQUES, COMERCIO], True), allow_nan=False)


# --- Sem dados pessoais (canários) -----------------------------------------------------------

CHAVES_TOPO = {"coordinates", "instructions", "geometry", "elevation", "units", "options"}
CHAVES_OBRIGATORIAS = {"coordinates", "instructions", "geometry", "elevation", "units"}
TEXTOS_PERMITIDOS = {"m", "tollways"}


def _so_coordenadas_e_constantes(corpo):
    """A lista branca recursiva das chaves e dos valores do pedido ao Directions."""
    assert CHAVES_OBRIGATORIAS <= set(corpo) <= CHAVES_TOPO
    assert corpo["instructions"] is True and corpo["geometry"] is True and corpo["elevation"] is False
    assert corpo["units"] == "m"
    if "options" in corpo:
        assert corpo["options"] == {"avoid_features": ["tollways"]}
    coordenadas = corpo["coordinates"]
    assert isinstance(coordenadas, list) and len(coordenadas) >= 2
    assert all(isinstance(par, list) and len(par) == 2 for par in coordenadas)
    folhas = list(_folhas(corpo))
    assert {folha for folha in folhas if isinstance(folha, str)} <= TEXTOS_PERMITIDOS
    assert len([folha for folha in folhas if isinstance(folha, bool)]) == 3
    numeros = [folha for folha in folhas if not isinstance(folha, (str, bool))]
    assert all(type(folha) in (int, float) and math.isfinite(folha) for folha in numeros)
    assert len(numeros) == 2 * len(coordenadas)


@pytest.mark.parametrize("evitar", [False, True])
def test_o_pedido_nao_leva_nomes_telefones_moradas_nem_uuids(evitar):
    """Lojas completas (validador_loja.criacao + formatar.documento_loja) e paragens
    completas do §3: ao Directions só chegam as coordenadas, por `paragem_calculo`."""
    lojas, paragens = _cenario_completo()
    calculo = [paragem_calculo(p, l) for p, l in zip(paragens, lojas)]
    pontos = [FABRICA, *((c.lat, c.lng) for c in calculo), (38.71, -9.14)]
    corpo = pedido_direcoes(pontos, evitar)
    texto = json.dumps(corpo, allow_nan=False, ensure_ascii=False)

    proibidos = [*CANARIOS_TEXTO, MEMBRO, REGIAO, *(l["id"] for l in lojas), *(p["id"] for p in paragens), "2026-10"]
    assert [canario for canario in proibidos if canario in texto] == []
    assert [canario for canario in proibidos if canario.lower() in texto.lower()] == []
    _so_coordenadas_e_constantes(corpo)
    assert len(corpo["coordinates"]) == 6
    assert ("options" in corpo) is evitar


def test_uma_loja_inteira_no_lugar_de_um_ponto_e_recusada():
    """Mesmo por engano, o pedido não leva um documento: só pares de números."""
    lojas, _ = _cenario_completo()
    with pytest.raises(ValueError):
        pedido_direcoes([FABRICA, lojas[0], FABRICA], False)
    with pytest.raises(ValueError):
        pedido_direcoes([FABRICA, (lojas[0]["nome"], lojas[0]["telefone"]), FABRICA], False)


def test_a_lista_branca_apanha_um_texto_ou_uma_chave_a_mais():
    """Os verificadores do teste dos canários rebentam com o que devem (meta-teste)."""
    corpo = pedido_direcoes([FABRICA, COMERCIO], True)
    _so_coordenadas_e_constantes(corpo)
    _so_coordenadas_e_constantes(pedido_direcoes([FABRICA, COMERCIO], False))
    estragados = [
        {**corpo, "extra": 1},
        {**corpo, "language": "pt"},
        {**corpo, "units": "km"},
        {**corpo, "instructions": 1},
        {**corpo, "options": {"avoid_features": ["tollways"], "profile_params": {"x": 1}}},
        {**corpo, "options": {"avoid_features": ["CANARIO-NOME"]}},
        {**corpo, "coordinates": [[-9.1393, 38.7223], [-9.1364, 38.7075, "Café X"]]},
        {**corpo, "coordinates": [[-9.1393, 38.7223], ["-9.1364", 38.7075]]},
        {**corpo, "coordinates": [[-9.1393, 38.7223], [math.nan, 38.7075]]},
        {**corpo, "coordinates": [[-9.1393, 38.7223], [True, 38.7075]]},
        {**corpo, "coordinates": [[-9.1393, 38.7223]]},
        {**corpo, "id": "5a1e6c7d-8b9f-4e0a-9b1c-2d3e4f5a6b7c"},
    ]
    for estragado in estragados:
        with pytest.raises(AssertionError):
            _so_coordenadas_e_constantes(estragado)


# --- interpretar_direcoes -------------------------------------------------------------------

PONTOS_LINHA = [FABRICA, (38.7246, -9.1478), MARQUES, (38.7139, -9.1394), COMERCIO, (38.716, -9.137), FABRICA]
GEOMETRIA = codificar(PONTOS_LINHA)
_SEM = object()


def _segmento(distancia=_SEM, duracao=_SEM, **mais):
    segmento = {"steps": [{"type": 11, "instruction": "Head west", "name": "-", "way_points": [0, 1]},
                          {"type": 10, "instruction": "Arrive at your destination", "name": "-", "way_points": [1, 1]}]}
    if distancia is not _SEM:
        segmento["distance"] = distancia
    if duracao is not _SEM:
        segmento["duration"] = duracao
    return {**segmento, **mais}


def _resposta(segmentos=None, resumo=_SEM, geometria=GEOMETRIA, **mais):
    """Uma resposta do Directions para 4 pontos (fábrica → Marquês → Comércio → fábrica)."""
    if segmentos is None:
        segmentos = [_segmento(1342.6, 238.4), _segmento(2917.3, 478.9), _segmento(2605.4, 431.0)]
    if resumo is _SEM:
        resumo = {"distance": 6865.3, "duration": 1148.3}
    rota = {"segments": segmentos, "bbox": [-9.15, 38.7075, -9.1364, 38.7253], "way_points": [0, 2, 4, 6]}
    if resumo is not None:
        rota["summary"] = resumo
    if geometria is not _SEM:
        rota["geometry"] = geometria
    return {"bbox": [-9.15, 38.7075, -9.1364, 38.7253], "routes": [rota],
            "metadata": {"attribution": "openrouteservice.org | OpenStreetMap contributors", "service": "routing"}, **mais}


def _rota(resposta):
    return resposta["routes"][0]


def test_le_os_trocos_e_os_totais():
    assert interpretar_direcoes(_resposta(), 4) == Trocos(
        duracoes=[238.4, 478.9, 431.0],
        distancias=[1342.6, 2917.3, 2605.4],
        distancia_m=6865,
        duracao_s=1148,
        geometria=GEOMETRIA,
    )


def test_os_campos_dos_trocos():
    assert Trocos._fields == ("duracoes", "distancias", "distancia_m", "duracao_s", "geometria")


def test_os_tipos_dos_trocos():
    trocos = interpretar_direcoes(_resposta([_segmento(1000, 200), _segmento(2000.5, 300), _segmento(0, 0)]), 4)
    assert trocos.duracoes == [200.0, 300.0, 0.0] and trocos.distancias == [1000.0, 2000.5, 0.0]
    assert all(type(valor) is float for valor in trocos.duracoes + trocos.distancias)
    assert type(trocos.distancia_m) is int and type(trocos.duracao_s) is int
    assert type(trocos.geometria) is str


def test_os_totais_vem_do_resumo_e_nao_da_soma_dos_trocos():
    trocos = interpretar_direcoes(_resposta(resumo={"distance": 7000.0, "duration": 1200.0}), 4)
    assert (trocos.distancia_m, trocos.duracao_s) == (7000, 1200)


def test_os_totais_arredondam_meio_para_longe_do_zero():
    """7000,5 → 7001 e 1200,5 → 1201; o `round` do Python dava 7000 e 1200 (vai para o par)."""
    trocos = interpretar_direcoes(_resposta(resumo={"distance": 7000.5, "duration": 1200.5}), 4)
    assert (trocos.distancia_m, trocos.duracao_s) == (7001, 1201)
    trocos = interpretar_direcoes(_resposta(resumo={"distance": 7000.49, "duration": 1199.5}), 4)
    assert (trocos.distancia_m, trocos.duracao_s) == (7000, 1200)


def test_sem_resumo_os_totais_sao_a_soma_dos_trocos():
    """Correção "T3.7": sem `summary`, os totais são a soma dos troços."""
    segmentos = [_segmento(1000.25, 100.25), _segmento(2000.25, 100.25), _segmento(500.0, 50.0)]
    trocos = interpretar_direcoes(_resposta(segmentos, resumo=None), 4)
    assert (trocos.distancia_m, trocos.duracao_s) == (3501, 251)
    assert trocos.duracoes == [100.25, 100.25, 50.0]


def test_um_troco_sem_distancia_nem_duracao_conta_como_zero():
    """Correção "T3.7": o ORS deixa de fora as chaves que valem 0 (pontos repetidos,
    ou dois pontos que encaixam no mesmo sítio da estrada)."""
    segmentos = [_segmento(1342.6, 238.4), _segmento(), _segmento(1500.0, 260.0)]
    trocos = interpretar_direcoes(_resposta(segmentos, resumo={"distance": 2842.6, "duration": 498.4}), 4)
    assert trocos.duracoes == [238.4, 0.0, 260.0]
    assert trocos.distancias == [1342.6, 0.0, 1500.0]
    assert (trocos.distancia_m, trocos.duracao_s) == (2843, 498)


@pytest.mark.parametrize("chave", ["distance", "duration"])
def test_so_uma_das_chaves_em_falta_tambem_conta_como_zero(chave):
    segmento = _segmento(10.0, 5.0)
    del segmento[chave]
    trocos = interpretar_direcoes(_resposta([_segmento(1.0, 1.0), segmento, _segmento(2.0, 2.0)]), 4)
    if chave == "distance":
        assert (trocos.distancias[1], trocos.duracoes[1]) == (0.0, 5.0)
    else:
        assert (trocos.distancias[1], trocos.duracoes[1]) == (10.0, 0.0)


def test_um_resumo_sem_as_chaves_conta_como_zero():
    """Uma rota de comprimento zero (todos os pontos iguais): nem os troços nem o `summary` trazem as chaves."""
    geometria = codificar([COMERCIO, COMERCIO])
    trocos = interpretar_direcoes(_resposta([_segmento(), _segmento(), _segmento()], resumo={}, geometria=geometria), 4)
    assert trocos == Trocos([0.0, 0.0, 0.0], [0.0, 0.0, 0.0], 0, 0, geometria)


@pytest.mark.parametrize("chave", ["distance", "duration"])
def test_um_resumo_so_com_uma_das_chaves(chave):
    trocos = interpretar_direcoes(_resposta(resumo={chave: 100.0}), 4)
    assert (trocos.distancia_m, trocos.duracao_s) == ((100, 0) if chave == "distance" else (0, 100))


def test_dois_pontos_um_troco():
    trocos = interpretar_direcoes(_resposta([_segmento(812.0, 120.0)], resumo={"distance": 812.0, "duration": 120.0}), 2)
    assert trocos == Trocos([120.0], [812.0], 812, 120, GEOMETRIA)


def test_le_os_trocos_de_uma_rota_de_50_pontos():
    segmentos = [_segmento(100.0 + i, 10.0 + i) for i in range(49)]
    trocos = interpretar_direcoes(_resposta(segmentos, resumo=None), 50)
    assert len(trocos.duracoes) == 49 and trocos.duracoes[48] == 58.0


def test_menos_trocos_do_que_pares_de_pontos_e_invalido():
    with pytest.raises(RespostaInvalida):
        interpretar_direcoes(_resposta(), 5)


def test_mais_trocos_do_que_pares_de_pontos_e_invalido():
    with pytest.raises(RespostaInvalida):
        interpretar_direcoes(_resposta(), 3)


@pytest.mark.parametrize("valor", [-0.1, -1, -1e-9, math.nan, math.inf, -math.inf, True, False, "100", None, [100], {"v": 1}, 2**1100])
@pytest.mark.parametrize("chave", ["distance", "duration"])
def test_um_troco_com_um_numero_negativo_nao_finito_ou_que_nao_e_numero_e_invalido(chave, valor):
    """Correção "T3.7": em falta conta 0; presente, tem de ser um número ≥ 0 do JSON."""
    segmento = _segmento(10.0, 5.0)
    segmento[chave] = valor
    with pytest.raises(RespostaInvalida):
        interpretar_direcoes(_resposta([_segmento(1.0, 1.0), segmento, _segmento(2.0, 2.0)]), 4)


@pytest.mark.parametrize("valor", [-0.1, math.nan, math.inf, True, "100", None])
@pytest.mark.parametrize("chave", ["distance", "duration"])
def test_um_resumo_com_um_numero_negativo_nao_finito_ou_que_nao_e_numero_e_invalido(chave, valor):
    resumo = {"distance": 6865.3, "duration": 1148.3, chave: valor}
    with pytest.raises(RespostaInvalida):
        interpretar_direcoes(_resposta(resumo=resumo), 4)


@pytest.mark.parametrize("resumo", [[], "6865", 0, True, [6865.3, 1148.3]])
def test_um_resumo_que_nao_e_um_objeto_e_invalido(resumo):
    with pytest.raises(RespostaInvalida):
        interpretar_direcoes(_resposta(resumo=resumo), 4)


def test_um_resumo_nulo_e_invalido():
    resposta = _resposta()
    _rota(resposta)["summary"] = None
    with pytest.raises(RespostaInvalida):
        interpretar_direcoes(resposta, 4)


def test_zero_negativo_conta_como_zero():
    trocos = interpretar_direcoes(_resposta([_segmento(-0.0, -0.0), _segmento(1.0, 1.0), _segmento(1.0, 1.0)]), 4)
    assert trocos.duracoes[0] == 0.0 and trocos.distancias[0] == 0.0


@pytest.mark.parametrize("resposta", [None, [], "ok", 0, True, [{"routes": []}]])
def test_uma_resposta_que_nao_e_um_objeto_e_invalida(resposta):
    with pytest.raises(RespostaInvalida):
        interpretar_direcoes(resposta, 4)


def test_sem_routes_e_invalido():
    resposta = _resposta()
    del resposta["routes"]
    with pytest.raises(RespostaInvalida):
        interpretar_direcoes(resposta, 4)


def test_o_corpo_de_um_erro_do_ors_e_invalido():
    erro = {"error": {"code": 2010, "message": "Could not find routable point within a radius of 350.0 meters of specified coordinate 2: -9.0350000 38.7200000."}}
    with pytest.raises(RespostaInvalida):
        interpretar_direcoes(erro, 4)


@pytest.mark.parametrize("rotas_", [None, {}, "[]", 0, [], {"0": {}}])
def test_routes_que_nao_sao_uma_lista_com_uma_rota_sao_invalidas(rotas_):
    with pytest.raises(RespostaInvalida):
        interpretar_direcoes(_resposta(routes=rotas_), 4)


def test_mais_de_uma_rota_e_invalido():
    resposta = _resposta()
    resposta["routes"] = [_rota(resposta), copy.deepcopy(_rota(resposta))]
    with pytest.raises(RespostaInvalida):
        interpretar_direcoes(resposta, 4)


@pytest.mark.parametrize("rota", [None, [], "rota", 1])
def test_uma_rota_que_nao_e_um_objeto_e_invalida(rota):
    with pytest.raises(RespostaInvalida):
        interpretar_direcoes(_resposta(routes=[rota]), 4)


@pytest.mark.parametrize("segmentos", [None, {}, "segments", 3, {"0": {}}])
def test_segments_que_nao_sao_uma_lista_sao_invalidos(segmentos):
    resposta = _resposta()
    _rota(resposta)["segments"] = segmentos
    with pytest.raises(RespostaInvalida):
        interpretar_direcoes(resposta, 4)


def test_sem_segments_e_invalido():
    """Sem `instructions: true` o ORS não manda os `segments` (risco R2)."""
    resposta = _resposta()
    del _rota(resposta)["segments"]
    with pytest.raises(RespostaInvalida):
        interpretar_direcoes(resposta, 4)


@pytest.mark.parametrize("segmento", [None, 1342.6, "troço", [1342.6, 238.4]])
def test_um_troco_que_nao_e_um_objeto_e_invalido(segmento):
    with pytest.raises(RespostaInvalida):
        interpretar_direcoes(_resposta([_segmento(1.0, 1.0), segmento, _segmento(2.0, 2.0)]), 4)


def test_sem_geometria_e_invalido():
    with pytest.raises(RespostaInvalida):
        interpretar_direcoes(_resposta(geometria=_SEM), 4)


@pytest.mark.parametrize("geometria", [None, 123, [[-9.1393, 38.7223], [-9.15, 38.7253]], {"type": "LineString"}, b"k}ikFr_xv@", True])
def test_uma_geometria_que_nao_e_texto_e_invalida(geometria):
    with pytest.raises(RespostaInvalida):
        interpretar_direcoes(_resposta(geometria=geometria), 4)


@pytest.mark.parametrize("geometria", [GEOMETRIA[:-1], GEOMETRIA + " ", "é" + GEOMETRIA, "_p~iF", "~" * 40])
def test_uma_geometria_que_nao_se_descodifica_e_invalida(geometria):
    with pytest.raises(RespostaInvalida):
        interpretar_direcoes(_resposta(geometria=geometria), 4)


@pytest.mark.parametrize("geometria", ["", "_p~iF~ps|U"])
def test_uma_geometria_com_menos_de_dois_pontos_e_invalida(geometria):
    with pytest.raises(RespostaInvalida):
        interpretar_direcoes(_resposta(geometria=geometria), 4)


def test_a_geometria_volta_tal_como_veio():
    """Guarda-se em `calculo.geometria` tal como o ORS a mandou (precisão 5)."""
    trocos = interpretar_direcoes(_resposta(), 4)
    assert trocos.geometria == GEOMETRIA
    assert descodificar(trocos.geometria) == PONTOS_LINHA


@pytest.mark.parametrize("n_pontos", [1, 0, -1, 51, True, 4.0, "4", None])
def test_interpretar_recusa_um_numero_de_pontos_impossivel(n_pontos):
    """`n_pontos` vem do próprio pedido: um valor errado é um engano do código (`ValueError`)."""
    with pytest.raises(ValueError):
        interpretar_direcoes(_resposta(), n_pontos)


def test_as_chaves_desconhecidas_da_resposta_ignoram_se():
    resposta = _resposta(_origem="manual — regravar", info={"x": 1})
    _rota(resposta)["warnings"] = [{"code": 1, "message": "There may be restrictions on some roads"}]
    _rota(resposta)["segments"][0]["ascent"] = 10
    assert interpretar_direcoes(resposta, 4) == interpretar_direcoes(_resposta(), 4)


def test_interpretar_nao_muda_a_resposta_e_devolve_listas_novas():
    resposta = _resposta()
    copia = copy.deepcopy(resposta)
    primeira = interpretar_direcoes(resposta, 4)
    segunda = interpretar_direcoes(resposta, 4)
    assert resposta == copia
    assert primeira == segunda
    assert primeira.duracoes is not segunda.duracoes and primeira.distancias is not segunda.distancias


def test_a_resposta_invalida_e_a_do_vroom():
    """A T3.7 importa-a do `vroom.py`: as rotas apanham uma só exceção para os dois serviços."""
    assert directions.RespostaInvalida is vroom.RespostaInvalida


def test_a_resposta_invalida_traz_o_motivo_sem_nada_da_resposta():
    """O motivo vai para os registos (T3.21/T3.22): só textos fixos, sem
    coordenadas nem o que o ORS mandou. Lançada fora de qualquer `except`."""
    estragadas = [
        "CANARIO",
        {"error": {"code": 2010, "message": "CANARIO coordinate 2: -9.123456 38.654321"}},
        _resposta(routes="CANARIO-ROTAS"),
        _resposta(routes=[{"segments": "CANARIO-TROÇOS", "geometry": GEOMETRIA}]),
        _resposta([_segmento(1.0, 1.0), _segmento("CANARIO-DIST", 1.0), _segmento(1.0, 1.0)]),
        _resposta([_segmento(1.0, 1.0), _segmento(-38.654321, 1.0), _segmento(1.0, 1.0)]),
        _resposta([_segmento(1.0, 1.0), "CANARIO-SEG", _segmento(1.0, 1.0)]),
        _resposta(resumo={"distance": "CANARIO-RESUMO"}),
        _resposta(resumo="CANARIO-RESUMO"),
        _resposta(geometria="CANARIO é -9.123456"),
        _resposta(geometria=["CANARIO", -9.123456, 38.654321]),
        _resposta(geometria="_p~iF~ps|U"),
    ]
    for resposta in estragadas:
        with pytest.raises(RespostaInvalida) as erro:
            interpretar_direcoes(resposta, 4)
        motivo = erro.value.motivo
        assert isinstance(motivo, str) and motivo
        assert str(erro.value) == motivo
        assert "CANARIO" not in motivo and "38.65" not in motivo and "-9.12" not in motivo
        assert erro.value.__cause__ is None
        assert erro.value.__context__ is None


# --- As fixtures (forma; o dono vai regravá-las, T3.12) ---------------------------------------


def _cenario(nome):
    cenarios = _ler("cenarios.json")
    cenario = cenarios["direcoes"][nome]
    return [(cenarios["pontos"][ponto]["lat"], cenarios["pontos"][ponto]["lng"]) for ponto in cenario["pontos"]], cenario


def _pedido_do_cenario(nome):
    """O pedido de um cenário do Directions, como o gravador (T3.12) o monta."""
    pontos, cenario = _cenario(nome)
    return pedido_direcoes(pontos, cenario["evitar_portagens"])


def test_os_cenarios_do_directions():
    cenarios = _ler("cenarios.json")
    assert set(cenarios["direcoes"]) == {"direcoes-tres-paragens", "direcoes-erro-2010"}
    for cenario in cenarios["direcoes"].values():
        assert set(cenario["pontos"]) <= set(cenarios["pontos"])
        assert type(cenario["evitar_portagens"]) is bool
    assert len(cenarios["direcoes"]["direcoes-tres-paragens"]["pontos"]) == 5


def test_o_ponto_no_rio_e_uma_paragem_do_cenario_do_erro_2010():
    """O `rio_tejo` (correção "T3.12 / T3.43") fica no meio da lista: é uma
    paragem e não o início nem o fim. Está em Portugal continental, longe dos
    outros pontos, e só entra no cenário do erro."""
    cenarios = _ler("cenarios.json")
    rio = cenarios["pontos"]["rio_tejo"]
    assert geo.contem_latitude(rio["lat"]) and geo.contem_longitude(rio["lng"])
    assert all(
        geo.distancia_metros(rio["lat"], rio["lng"], ponto["lat"], ponto["lng"]) > 5000
        for nome, ponto in cenarios["pontos"].items() if nome != "rio_tejo"
    )
    pontos = cenarios["direcoes"]["direcoes-erro-2010"]["pontos"]
    assert pontos.count("rio_tejo") == 1 and pontos[0] != "rio_tejo" and pontos[-1] != "rio_tejo"
    assert "rio_tejo" not in cenarios["direcoes"]["direcoes-tres-paragens"]["pontos"]
    for cenario in cenarios["otimizacao"].values():
        assert "rio_tejo" not in {cenario["inicio"], cenario["fim"], *(p["ponto"] for p in cenario["paragens"])}


@pytest.mark.parametrize("nome", ["direcoes-tres-paragens", "direcoes-erro-2010"])
def test_os_pedidos_dos_cenarios_so_levam_coordenadas(nome):
    corpo = _pedido_do_cenario(nome)
    _so_coordenadas_e_constantes(corpo)
    texto = json.dumps(corpo, allow_nan=False)
    assert all(ponto not in texto for ponto in ("fabrica", "praca", "marques", "torre", "rio"))


def test_a_resposta_gravada_das_tres_paragens_le_se():
    resposta = _ler("direcoes-tres-paragens.json")
    assert resposta["_origem"].startswith(("manual — regravar", "gravado em "))
    pontos, _ = _cenario("direcoes-tres-paragens")
    trocos = interpretar_direcoes(resposta, len(pontos))
    assert len(trocos.duracoes) == len(trocos.distancias) == len(pontos) - 1
    assert all(valor > 0 for valor in trocos.duracoes + trocos.distancias)  # 5 pontos diferentes
    assert trocos.distancia_m > 0 and trocos.duracao_s > 0
    assert len(descodificar(trocos.geometria)) >= 2


def test_a_resposta_gravada_do_erro_2010():
    """O corpo do erro (o ORS responde com um estado 4xx; o `ors.py` da T3.11 lê-o).
    Só a forma: o código 2010 e a mensagem com o número de uma das coordenadas enviadas."""
    resposta = _ler("direcoes-erro-2010.json")
    assert resposta["_origem"].startswith(("manual — regravar", "gravado em "))
    assert type(resposta["error"]["code"]) is int and resposta["error"]["code"] == 2010
    mensagem = resposta["error"]["message"]
    numero = re.search(r"(?:coordinate|point) (\d+)", mensagem)
    pontos, _ = _cenario("direcoes-erro-2010")
    assert numero is not None and 0 <= int(numero.group(1)) < len(pontos)
    with pytest.raises(RespostaInvalida):
        interpretar_direcoes(resposta, len(pontos))


def test_a_resposta_com_um_ponto_repetido():
    """Correção "T3.7": o 2.º troço (entre duas lojas nas mesmas coordenadas) só traz os `steps`."""
    resposta = _ler("direcoes-ponto-repetido.json")
    assert resposta["_origem"].startswith("manual")
    coordenadas = resposta["metadata"]["query"]["coordinates"]
    assert len(coordenadas) == 4 and coordenadas[1] == coordenadas[2]
    segmento = resposta["routes"][0]["segments"][1]
    assert "distance" not in segmento and "duration" not in segmento and segmento["steps"]

    trocos = interpretar_direcoes(resposta, 4)
    assert trocos.duracoes[1] == 0.0 and trocos.distancias[1] == 0.0
    assert all(valor > 0 for i, valor in enumerate(trocos.duracoes + trocos.distancias) if i % 3 != 1)
    assert trocos.distancia_m > 0 and trocos.duracao_s > 0


# --- O módulo -------------------------------------------------------------------------------


def test_directions_nunca_chama_o_round_do_python():
    """Os totais arredondam-se com `numeros.arredondar` (meio-para-longe-do-zero)."""
    chamadas = [
        no for no in ast.walk(ast.parse(FICHEIRO.read_text(encoding="utf-8")))
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Name) and no.func.id == "round"
    ]
    assert chamadas == []
