"""Os links de navegação por paragem (Google Maps e Waze) e os blocos de 9 do
Google Maps, F3.

Desenho original §8.2 e plano F3 §1 ("Links de navegação"): calculam-se no
servidor e vão na API (`paragem.links` e `rota.blocos_google`, T3.16); o
frontend só os desenha como `<a href>` tocados pela pessoa, depois do
`hrefNavegacao` (`lib/crm/dom.js`, T3.26). Nenhum precisa de chave, por isso o
módulo é puro: não lê o ambiente nem faz pedidos.

- Por paragem, um destino só (o Waze só aceita um):
  - `https://www.google.com/maps/dir/?api=1&destination=LAT,LNG&travelmode=driving&dir_action=navigate[&avoid=tolls]`
  - `https://waze.com/ul?ll=LAT,LNG&navigate=yes[&avoid_tolls=true]`
- "Abrir paragens X–Y no Google Maps" em blocos de 9 (`TAMANHO_BLOCO_GOOGLE`),
  **sem origem** (o Google Maps parte de onde o telemóvel está): os 8
  primeiros em `waypoints`, separados por `|` codificado (`%7C`), e o 9.º como
  destino. Os blocos seguem a ordem recebida (a da secção "rota") e o rótulo
  diz quantas paragens leva de facto.

As coordenadas vão com 6 casas, arredondadas meio-para-longe-do-zero como se
guardam (`numeros.arredondar`, nunca o `round` do Python) e sem "-0.000000".
Uma coordenada que não é um número do JSON (NaN, inf, `None`, bool, texto) ou
está fora de ±90/±180 não dá link (`None`); nos blocos, essa paragem fica de
fora e não conta. `evitar` é um bool a sério (outra coisa → `ValueError`),
como o `evitar_portagens` das definições do dia.

O `avoid=tolls` do Google Maps está documentado (Maps URLs). O
`avoid_tolls=true` do Waze não está na documentação oficial dos deep links
(lá, evitar portagens é uma definição da app) e pode ser ignorado sem aviso:
o link mantém-se fiel ao §8.2, a confirmação no telemóvel da carrinha fica no
§14 do dossiê (ponto 11) e o detalhe da paragem avisa (`rota.js`, T3.27).
"""
from crm.dominio.numeros import arredondar, e_inteiro_json, e_numero_json

# Paragens por bloco do Google Maps: 8 `waypoints` mais o destino.
TAMANHO_BLOCO_GOOGLE = 9

# O Google Maps aceita no máximo 9 `waypoints` mais o destino.
_TAMANHO_MAXIMO = 10

_GOOGLE = "https://www.google.com/maps/dir/?api=1"
_WAZE = "https://waze.com/ul?"

# O `|` codificado: o `hrefNavegacao` do frontend recusa o `|` em claro.
_SEPARADOR_WAYPOINTS = "%7C"

# As casas com que as coordenadas se guardam (validador_loja).
_CASAS = 6

# Os limites do mundo, não os de Portugal: um link é só um destino, e quem
# guarda a loja já exigiu Portugal continental (geo.contem_latitude).
_LAT_MAXIMA = 90
_LNG_MAXIMA = 180


def _casas(valor) -> str:
    """Um número às 6 casas, meio-para-longe-do-zero, sem o sinal de um zero
    negativo (-0,0000001 → "0.000000", nunca "-0.000000")."""
    arredondado = arredondar(valor, _CASAS)
    if arredondado == 0:
        arredondado = 0.0
    return f"{arredondado:.6f}"


def _destino(lat, lng):
    """O texto "LAT,LNG" de um link, ou `None` quando uma das duas não é uma
    coordenada: não é um número do JSON (NaN, inf, bool, texto, `None`…) ou
    está fora de ±90/±180 (visto antes de arredondar: 90,0000001 não entra)."""
    if not (e_numero_json(lat) and e_numero_json(lng)):
        return None
    if not (-_LAT_MAXIMA <= lat <= _LAT_MAXIMA and -_LNG_MAXIMA <= lng <= _LNG_MAXIMA):
        return None
    return f"{_casas(lat)},{_casas(lng)}"


def _exigir_bool(evitar) -> None:
    if type(evitar) is not bool:
        raise ValueError("evitar portagens tem de ser verdadeiro ou falso")


def _href_google(destino: str, waypoints, evitar: bool) -> str:
    """O link do Google Maps para um destino e, nos blocos, os `waypoints`
    pela ordem; nunca leva origem."""
    link = f"{_GOOGLE}&destination={destino}"
    if waypoints:
        link += "&waypoints=" + _SEPARADOR_WAYPOINTS.join(waypoints)
    link += "&travelmode=driving&dir_action=navigate"
    if evitar:
        link += "&avoid=tolls"
    return link


def link_google(lat, lng, evitar: bool):
    """O link de navegação do Google Maps para uma paragem, ou `None` sem
    coordenadas válidas. Com `evitar` acaba em `&avoid=tolls`."""
    _exigir_bool(evitar)
    destino = _destino(lat, lng)
    if destino is None:
        return None
    return _href_google(destino, [], evitar)


def link_waze(lat, lng, evitar: bool):
    """O link de navegação do Waze para uma paragem, ou `None` sem
    coordenadas válidas. Com `evitar` acaba em `&avoid_tolls=true` (o nome do
    Waze, não o `avoid=tolls` do Google)."""
    _exigir_bool(evitar)
    destino = _destino(lat, lng)
    if destino is None:
        return None
    link = f"{_WAZE}ll={destino}&navigate=yes"
    if evitar:
        link += "&avoid_tolls=true"
    return link


def blocos_google(paragens, evitar: bool, tamanho: int = TAMANHO_BLOCO_GOOGLE):
    """Os blocos "Abrir paragens X–Y no Google Maps" de uma rota.

    `paragens` é uma lista (ou tuplo) de `(numero, lat, lng)` pela ordem da
    rota, com `numero` inteiro ≥ 1 (outra forma → `ValueError`; outra coleção
    → `TypeError`). Só as paragens com coordenadas válidas entram, e são essas
    que se contam para os blocos de `tamanho` (1 a 10). Cada bloco é um
    dicionário novo `{de, ate, quantas, rotulo, href}`: `de`/`ate` são os
    números da primeira e da última paragem do bloco, `quantas` as que leva de
    facto, e o `href` tem as primeiras em `waypoints` e a última como destino
    (um bloco de uma paragem é o `link_google` dela).
    """
    _exigir_bool(evitar)
    if type(tamanho) is not int or not 1 <= tamanho <= _TAMANHO_MAXIMO:
        raise ValueError(f"o bloco do Google Maps tem de 1 a {_TAMANHO_MAXIMO} paragens")
    if not isinstance(paragens, (list, tuple)):
        raise TypeError("as paragens numeradas têm de vir numa lista")

    com_coordenadas = []
    for paragem in paragens:
        if not isinstance(paragem, (list, tuple)) or len(paragem) != 3:
            raise ValueError("cada paragem numerada é (numero, lat, lng)")
        numero, lat, lng = paragem
        if not e_inteiro_json(numero) or numero < 1:
            raise ValueError("o número da paragem é um inteiro a partir de 1")
        destino = _destino(lat, lng)
        if destino is not None:
            com_coordenadas.append((numero, destino))

    blocos = []
    for inicio in range(0, len(com_coordenadas), tamanho):
        bloco = com_coordenadas[inicio : inicio + tamanho]
        de = bloco[0][0]
        ate = bloco[-1][0]
        quantas = len(bloco)
        pontos = [destino for _, destino in bloco]
        if quantas == 1:
            rotulo = f"Abrir paragem {de} no Google Maps (1 paragem)"
        else:
            rotulo = f"Abrir paragens {de}–{ate} no Google Maps ({quantas} paragens)"
        blocos.append(
            {
                "de": de,
                "ate": ate,
                "quantas": quantas,
                "rotulo": rotulo,
                "href": _href_google(pontos[-1], pontos[:-1], evitar),
            }
        )
    return blocos
