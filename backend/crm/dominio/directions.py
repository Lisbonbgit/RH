"""O pedido ao Directions do openrouteservice e a leitura dos troços (F3).

Plano F3 §1 ("Directions", "Horas") e §0 regra 12. As horas da rota vêm só do
Directions, por uma chamada pela ordem fixa: `POST
/v2/directions/driving-car/json` com os pontos do início ao fim.

- `pedido_direcoes` monta o corpo **só com coordenadas e constantes**:
  `{coordinates: [[lng, lat]…], instructions: true, geometry: true,
  elevation: false, units: "m"}` e, quando se evitam portagens,
  `options.avoid_features: ["tollways"]`. Os pontos são pares `(lat, lng)` de
  números, arredondados como no pedido ao VROOM (`vroom.ponto_ors`); um
  documento, um texto ou um uuid nunca passam (risco R4). O `instructions:
  true` é o que traz os `segments` (risco R2). No máximo 50 pontos: as 48
  paragens (`rotas.LIMITE_PARAGENS`) mais o início e o fim.
- `interpretar_direcoes` lê a resposta com um parser estrito (risco R3): o que
  não bater certo é a `RespostaInvalida` do `vroom.py` (→ 503 nas rotas, nada
  muda), com um motivo fixo, sem nada da resposta, lançada fora de qualquer
  `except`. Correção "T3.7": o ORS deixa de fora a `distance`/`duration` de
  um troço (e do `summary`) quando valem 0 — pontos repetidos, como duas
  lojas na mesma morada, ou uma paragem na própria fábrica —, por isso uma
  chave em falta conta como 0; presente, tem de ser um número do JSON ≥ 0.
  Sem `summary`, os totais são a soma dos troços.

A geometria é a polyline codificada (precisão 5, `polilinha`), devolvida tal
como veio para se guardar em `calculo.geometria`.
"""
import math
from typing import NamedTuple

from . import polilinha
from .numeros import arredondar, e_inteiro_json, e_numero_json
from .vroom import RespostaInvalida, ponto_ors

UNIDADES = "m"
PORTAGENS = "tollways"

# O Directions do ORS aceita 50 coordenadas: as 48 paragens, o início e o fim.
MINIMO_PONTOS = 2
MAXIMO_PONTOS = 50

_MEDIDAS = {"distance": "distância", "duration": "duração"}


class Trocos(NamedTuple):
    """O que o Directions disse: por troço (do ponto i ao i + 1) a duração em
    segundos e a distância em metros (`float`, 0 quando o ORS as deixou de
    fora); os totais em `int` (meio-para-longe-do-zero); e a polyline."""

    duracoes: list
    distancias: list
    distancia_m: int
    duracao_s: int
    geometria: str


def pedido_direcoes(pontos, evitar_portagens) -> dict:
    """O corpo do pedido para os `pontos` (pares `(lat, lng)`, do início ao fim,
    pela ordem recebida). Estruturas novas a cada chamada.

    O que não é uma lista ou um tuplo é `TypeError`; menos de 2 ou mais de 50
    pontos, um ponto estragado ou um `evitar_portagens` que não é `bool` são
    `ValueError` (enganos do código: o validador já os recusou).
    """
    if not isinstance(pontos, (list, tuple)):
        raise TypeError("pedido_direcoes recebe uma lista de pares (lat, lng).")
    if type(evitar_portagens) is not bool:
        raise ValueError("evitar_portagens tem de ser True ou False.")
    _quantos(len(pontos))
    corpo = {
        "coordinates": [ponto_ors(ponto) for ponto in pontos],
        "instructions": True,
        "geometry": True,
        "elevation": False,
        "units": UNIDADES,
    }
    if evitar_portagens:
        corpo["options"] = {"avoid_features": [PORTAGENS]}
    return corpo


def interpretar_direcoes(resposta, n_pontos) -> Trocos:
    """Os troços da (única) rota da resposta, para um pedido de `n_pontos`.

    `RespostaInvalida` quando a resposta não é um objeto; `routes` não é uma
    lista com exatamente uma rota (ou a rota não é um objeto); `segments` não
    é uma lista de `n_pontos − 1` objetos; uma distância ou duração presente
    não é um número do JSON ≥ 0 (no troço ou no `summary`); o `summary`
    presente não é um objeto; a geometria não é texto ou não se descodifica em
    pelo menos 2 pontos. `n_pontos` fora de 2..50 é `ValueError`.
    """
    _quantos(n_pontos)
    if not isinstance(resposta, dict):
        raise RespostaInvalida("a resposta do Directions não é um objeto")
    rotas_ = resposta.get("routes")
    if not isinstance(rotas_, list) or not rotas_:
        raise RespostaInvalida("o Directions não trouxe a rota")
    if len(rotas_) > 1:
        raise RespostaInvalida("o Directions devolveu mais de uma rota")
    rota = rotas_[0]
    if not isinstance(rota, dict):
        raise RespostaInvalida("a rota do Directions não é um objeto")

    segmentos = rota.get("segments")
    if not isinstance(segmentos, list):
        raise RespostaInvalida("o Directions não trouxe a lista dos troços")
    if len(segmentos) != n_pontos - 1:
        raise RespostaInvalida("o Directions não trouxe um troço por cada par de pontos seguidos")
    duracoes = []
    distancias = []
    for segmento in segmentos:
        if not isinstance(segmento, dict):
            raise RespostaInvalida("um troço do Directions não é um objeto")
        duracoes.append(_medida(segmento, "duration"))
        distancias.append(_medida(segmento, "distance"))

    if "summary" in rota:
        resumo = rota["summary"]
        if not isinstance(resumo, dict):
            raise RespostaInvalida("o resumo do Directions não é um objeto")
        distancia = _medida(resumo, "distance")
        duracao = _medida(resumo, "duration")
    else:
        distancia = math.fsum(distancias)
        duracao = math.fsum(duracoes)

    geometria = rota.get("geometry")
    if not isinstance(geometria, str):
        raise RespostaInvalida("a geometria do Directions não é texto")
    if len(_pontos_da_linha(geometria)) < 2:
        raise RespostaInvalida("a geometria do Directions não se descodifica numa linha")

    return Trocos(duracoes, distancias, int(arredondar(distancia)), int(arredondar(duracao)), geometria)


def _medida(objeto, chave) -> float:
    """A `distance` ou a `duration` de um troço ou do resumo: em falta conta 0
    (o ORS deixa-a de fora quando vale 0); presente, um número do JSON ≥ 0."""
    if chave not in objeto:
        return 0.0
    valor = objeto[chave]
    if not e_numero_json(valor) or valor < 0:
        raise RespostaInvalida(f"o Directions trouxe uma {_MEDIDAS[chave]} que não é um número ≥ 0")
    return float(valor)


def _pontos_da_linha(geometria) -> list:
    # Sem levantar dentro do `except`: a RespostaInvalida sai sem `__context__`.
    try:
        return polilinha.descodificar(geometria)
    except ValueError:
        return []


def _quantos(n_pontos) -> None:
    if not e_inteiro_json(n_pontos) or not MINIMO_PONTOS <= n_pontos <= MAXIMO_PONTOS:
        raise ValueError(f"O Directions leva de {MINIMO_PONTOS} a {MAXIMO_PONTOS} pontos, não {n_pontos!r}.")
