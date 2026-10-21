"""A polyline codificada (o "Encoded Polyline Algorithm Format" da Google), F3.

O Directions do openrouteservice devolve a linha da rota assim, com 5 casas
decimais (sem elevação). A F3 guarda-a tal como vem, em `calculo.geometria`
(plano §3), e descodifica-a para as sugestões no caminho (T3.9).

O formato: cada ponto é a diferença para o anterior, em inteiros (graus ×
10^precisão); cada inteiro vai com o sinal no bit mais baixo (`~` nos
negativos) e é cortado em blocos de 5 bits, do mais baixo para o mais alto,
com o bit 0x20 ligado em todos menos no último; a cada bloco soma-se 63, o que
dá caracteres de "?" (63) a "~" (126).

- `descodificar` é estrito: um carácter fora de 63..126, um valor cortado a
  meio, uma latitude sem longitude ou um valor com mais de 12 blocos (60
  bits, muito acima de uma coordenada) dão `ValueError`.
- `codificar` (correção "T3.7 / T3.9 / T3.13 / T3.21": nasce aqui e o
  simulador e os testes das rotas importam-no) arredonda como as coordenadas
  se guardam: meio-para-longe-do-zero, pelo texto do número (o
  `numeros.arredondar`), nunca o `round` do Python (que vai para o par).
"""
from decimal import ROUND_HALF_UP, Decimal

from .numeros import e_inteiro_json, e_numero_json

# A precisão do Directions do ORS (e do exemplo da Google): 5 casas decimais.
PRECISAO = 5
PRECISAO_MAXIMA = 10

_DESVIO = 63
_BITS = 5
_MASCARA = 0x1F
_CONTINUA = 0x20
_MAXIMO_BLOCOS = 12

LATITUDE_MAXIMA = 90
LONGITUDE_MAXIMA = 180


def descodificar(texto, precisao=PRECISAO) -> list:
    """A polyline → `[(lat, lng), …]` em graus (`float`), numa lista nova.

    `""` dá `[]`. O que não é texto é `TypeError`; um texto estragado ou uma
    precisão fora de 0..10 é `ValueError`.
    """
    if not isinstance(texto, str):
        raise TypeError("A polyline tem de ser texto.")
    escala = _escala(precisao)

    valores = []
    valor = deslocamento = blocos = 0
    for caracter in texto:
        bloco = ord(caracter) - _DESVIO
        if not 0 <= bloco <= _MASCARA | _CONTINUA:
            raise ValueError("A polyline tem um carácter fora de '?'..'~'.")
        blocos += 1
        if blocos > _MAXIMO_BLOCOS:
            raise ValueError("A polyline tem um valor grande demais.")
        valor |= (bloco & _MASCARA) << deslocamento
        deslocamento += _BITS
        if bloco & _CONTINUA:
            continue
        valores.append(~(valor >> 1) if valor & 1 else valor >> 1)
        valor = deslocamento = blocos = 0
    if blocos:
        raise ValueError("A polyline acaba a meio de um valor.")
    if len(valores) % 2:
        raise ValueError("A polyline tem uma latitude sem longitude.")

    pontos = []
    lat = lng = 0
    for indice in range(0, len(valores), 2):
        lat += valores[indice]
        lng += valores[indice + 1]
        pontos.append((lat / escala, lng / escala))
    return pontos


def codificar(pontos, precisao=PRECISAO) -> str:
    """`[(lat, lng), …]` (tuplos ou listas, em graus) → a polyline.

    `[]` dá `""`. O que não é uma lista é `TypeError`; um ponto que não é um
    par de números do JSON, fora de ±90/±180, ou uma precisão fora de 0..10 é
    `ValueError`.
    """
    if not isinstance(pontos, (list, tuple)):
        raise TypeError("codificar recebe uma lista de pares (lat, lng).")
    _escala(precisao)

    partes = []
    lat_anterior = lng_anterior = 0
    for par in pontos:
        lat, lng = _par(par)
        lat_inteiro = _inteiro(lat, precisao)
        lng_inteiro = _inteiro(lng, precisao)
        partes.append(_valor(lat_inteiro - lat_anterior))
        partes.append(_valor(lng_inteiro - lng_anterior))
        lat_anterior, lng_anterior = lat_inteiro, lng_inteiro
    return "".join(partes)


def _escala(precisao) -> int:
    if not e_inteiro_json(precisao) or not 0 <= precisao <= PRECISAO_MAXIMA:
        raise ValueError(f"A precisão da polyline é um inteiro de 0 a {PRECISAO_MAXIMA}.")
    return 10**precisao


def _par(par) -> tuple:
    if not isinstance(par, (tuple, list)) or len(par) != 2:
        raise ValueError("Um ponto é um par (lat, lng).")
    lat, lng = par
    if not e_numero_json(lat) or not e_numero_json(lng):
        raise ValueError("A latitude e a longitude têm de ser números.")
    if not -LATITUDE_MAXIMA <= lat <= LATITUDE_MAXIMA or not -LONGITUDE_MAXIMA <= lng <= LONGITUDE_MAXIMA:
        raise ValueError("O ponto fica fora do mundo.")
    return lat, lng


def _inteiro(graus, precisao) -> int:
    """Graus × 10^precisão, meio-para-longe-do-zero sobre o texto do número
    (como o `numeros.arredondar`: 38,7223445 às 6 casas → 38 722 345)."""
    return int(Decimal(repr(float(graus))).scaleb(precisao).to_integral_value(rounding=ROUND_HALF_UP))


def _valor(numero) -> str:
    """Um inteiro com sinal → os seus caracteres da polyline."""
    numero <<= 1
    if numero < 0:
        numero = ~numero
    caracteres = []
    while numero >= _CONTINUA:
        caracteres.append(chr((_CONTINUA | (numero & _MASCARA)) + _DESVIO))
        numero >>= _BITS
    caracteres.append(chr(numero + _DESVIO))
    return "".join(caracteres)
