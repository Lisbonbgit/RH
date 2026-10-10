"""Onde fica uma loja: Portugal continental, distâncias e a precisão do GPS.

Porta de src/Dominio/Geo/{Portugal,Distancia,PrecisaoGps}.php do CRM autónomo
(dossiê §5.3–5.5). Os duplicados a menos de 50 m (Duplicados.php) e o
pré-filtro do Mongo juntam-se aqui na T2.3.

Quem chama valida primeiro que a coordenada é um número do JSON ("A latitude
tem de ser um número.") e arredonda-a às 6 casas com que se guarda; só depois
pergunta se está em Portugal.
"""
import math

from crm.dominio.numeros import arredondar, e_numero_json

# --- Portugal continental ---
# A carrinha não serve as ilhas (plano §9 do autónomo). É uma caixa aproximada,
# com os limites incluídos: apanha também um pouco de Espanha junto à
# fronteira, o que se aceita.

LAT_MINIMA = 36.8
LAT_MAXIMA = 42.2
LNG_MINIMA = -9.6
LNG_MAXIMA = -6.1

MENSAGEM_PORTUGAL = "Fora de Portugal"


def contem_latitude(lat) -> bool:
    """`36,8 ≤ lat ≤ 42,2`. Um bool, um texto ou um não-finito nunca contam
    (o PHP recebia um `float`; aqui não rebenta com TypeError)."""
    return e_numero_json(lat) and LAT_MINIMA <= lat <= LAT_MAXIMA


def contem_longitude(lng) -> bool:
    """`−9,6 ≤ lng ≤ −6,1`, com as mesmas regras de `contem_latitude`."""
    return e_numero_json(lng) and LNG_MINIMA <= lng <= LNG_MAXIMA


# --- Distância ---
# A Terra tratada como uma esfera (fórmula de haversine, plano D3 do
# autónomo). Ao metro, chega para os duplicados a 50 m.

RAIO_TERRA_M = 6_371_000

# Os metros de um grau de latitude (≈ 111 195 m); um grau de longitude mede
# isto vezes cos(lat). Pela mesma ordem do PHP (RAIO_TERRA_M * M_PI / 180).
METROS_POR_GRAU = RAIO_TERRA_M * math.pi / 180


def _radianos(graus: float) -> float:
    # O deg2rad() do PHP faz (graus / 180) * M_PI; o math.radians() do Python
    # multiplica por pi / 180, o que pode mudar a última casa binária.
    return graus / 180.0 * math.pi


def distancia_metros(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """A distância em metros entre dois pontos em graus decimais (o
    `Distancia::metros` do autónomo). Recebe números finitos já validados:
    com inf, o `math.sin` do Python rebenta (o do PHP dava NAN)."""
    fi1 = _radianos(lat1)
    fi2 = _radianos(lat2)
    h = math.sin((fi2 - fi1) / 2) ** 2 + math.cos(fi1) * math.cos(fi2) * math.sin(_radianos(lng2 - lng1) / 2) ** 2

    return 2 * RAIO_TERRA_M * math.asin(math.sqrt(h))


# --- Precisão do GPS de "Estou nesta loja" ---
# Pior do que 50 m, a pessoa tem de arrastar o pino e a origem passa a
# pin_manual (desenho original §6.2, plano D2 do autónomo).

# Igual a LIMITE_PRECISAO_M em frontend/src/lib/crm/gps.js (test_consistencia_frontend.py, T2.20).
LIMITE_PRECISAO_M = 50

# Igual a MENSAGEM_LOCALIZACAO_IMPRECISA em frontend/src/lib/crm/gps.js (test_consistencia_frontend.py, T2.20).
MENSAGEM_GPS = "Localização imprecisa — ajuste o pino"


def precisao_aceitavel(precisao_m) -> bool:
    """Uma precisão em metros, arredondada ao metro como se guarda: 50,4 → 50
    é aceitável; 50,5 → 51 não é (o `round()` do Python dava 50).

    Sem precisão, ou com uma que não seja um número ≥ 0 do JSON, não é
    aceitável: nem `None`, nem `"10"`, nem `True`/`False` (em Python o False
    seria um GPS de 0 m), nem inf ou nan. Aceite, guarda-se
    `int(arredondar(precisao_m))`, o `(int) round(…)` do autónomo.
    """
    return e_numero_json(precisao_m) and precisao_m >= 0 and arredondar(precisao_m) <= LIMITE_PRECISAO_M
