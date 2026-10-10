"""`/api/crm/morada/pesquisa` e `/api/crm/morada/inversa` — a pesquisa de
morada e a morada sugerida, para o escritório (admin e utilizador do CRM).

Plano T2.15; dossiê §6 e §8. Porta de src/Http/Controladores/
MoradaControlador.php do CRM autónomo. É o servidor que pede à Geoapify, com
a chave do servidor, que nunca vai para o browser nem para os registos (o
cliente e as regras dos registos estão em crm/servicos/geoapify.py).

- `GET /morada/pesquisa?texto=&lat=&lng=` → `[{rotulo, morada, codigo_postal,
  localidade, lat, lng}]`, até 5, só de Portugal continental. O texto tem de
  ter de 3 a 200 caracteres depois de aparado com o `trim()` do PHP (422): um
  texto maior nem chega à Geoapify, que o recusaria e daria um 503
  enganador. O ponto só serve de bias: se faltar ou não for válido,
  pesquisa-se sem ele; pode estar em qualquer sítio do mundo.
- `GET /morada/inversa?lat=&lng=` → a morada do ponto, ou `null` se a
  Geoapify não tiver uma. O ponto tem de estar em Portugal continental (422),
  o único sítio onde pode ficar uma loja.
- Sem chave do servidor (o normal em local), ou com a Geoapify em baixo →
  503 `morada_indisponivel`; o pino e o GPS continuam a funcionar. Sem chave
  nem se chama a Geoapify. A ordem é: a guarda de perfil → o pedido (422) →
  a chave (503) → a Geoapify.

`texto`, `lat` e `lng` leem-se como texto opcional e validam-se aqui, e não
com tipos do FastAPI (correções do plano, linhas "T2.15" e "T1.3 / T2.15"):
um `float` dava o 422 em lista e em inglês do Pydantic, e aceitava `1e2`,
`nan` e `inf`. Um número é o que o browser escreve (`NUMERO`). Um parâmetro
repetido vale o último, como o `$_GET` do PHP; um `texto[]=…` é outro nome e
conta como "sem texto".

Uma falha da Geoapify fica num registo `[crm]` (WARNING) só com o motivo — o
código HTTP ou o tipo da exceção —, nunca com o URL, a chave ou o texto
pesquisado (o RegistoErros do autónomo nunca registava a query: pode trazer
moradas escritas pela pessoa).

No autónomo, a sessão PHP libertava-se antes de chamar a Geoapify. No portal
não há sessões trancadas: o cliente é assíncrono e, enquanto espera pela
Geoapify (até 5 s), o servidor continua a responder aos outros pedidos.
"""
import logging
import re
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends

from .auth import ESCRITORIO
from .dominio.geo import MENSAGEM_PORTUGAL, contem_latitude, contem_longitude
from .erros import erro, validacao
from .servicos import geoapify

logger = logging.getLogger(__name__)

router = APIRouter()

PESQUISA_INDISPONIVEL = "Pesquisa de morada indisponível — coloque o pino no mapa ou use 'Estou nesta loja'"
INVERSA_INDISPONIVEL = "Morada sugerida indisponível — escreva a morada à mão."

TEXTO_MINIMO = 3

# Chega para uma morada (255 caracteres na loja) e o URL do pedido à Geoapify
# fica curto.
TEXTO_MAXIMO = 200

MENSAGEM_TEXTO_CURTO = "Escreva pelo menos 3 caracteres."
MENSAGEM_TEXTO_LONGO = f"A pesquisa tem no máximo {TEXTO_MAXIMO} caracteres."
MENSAGEM_LATITUDE = "A latitude tem de ser um número."
MENSAGEM_LONGITUDE = "A longitude tem de ser um número."

# Um número decimal como o browser o escreve (38.7223, -9.1393): sem expoente,
# vírgula, sinal + nem espaços, só algarismos ASCII. Com `fullmatch` (o `$` do
# Python aceitava uma quebra de linha no fim; o `/D` do PHP não).
NUMERO = re.compile(r"-?[0-9]{1,3}(\.[0-9]+)?")


def numero(valor: Optional[str]) -> Optional[float]:
    """O número de um parâmetro, ou `None` se faltar ou não for `NUMERO`."""
    return float(valor) if isinstance(valor, str) and NUMERO.fullmatch(valor) else None


def texto_da_pesquisa(texto: Optional[str]) -> Tuple[str, Dict[str, str]]:
    """`(texto aparado, erros)`: 3 a 200 caracteres (não bytes) depois do
    `trim()` do PHP. Sem texto, o mesmo erro que com menos de 3."""
    aparado = geoapify.trim_do_php(texto) if isinstance(texto, str) else ""

    if len(aparado) < TEXTO_MINIMO:
        return aparado, {"texto": MENSAGEM_TEXTO_CURTO}

    if len(aparado) > TEXTO_MAXIMO:
        return aparado, {"texto": MENSAGEM_TEXTO_LONGO}

    return aparado, {}


def bias(lat: Optional[str], lng: Optional[str]) -> Optional[Dict[str, float]]:
    """O ponto de onde se pesquisa, `{"lat", "lng"}`, se vierem a latitude e
    a longitude válidas (em qualquer sítio do mundo: é só para ordenar os
    resultados); senão, `None`."""
    lat_numero = numero(lat)
    lng_numero = numero(lng)

    if lat_numero is None or lng_numero is None or abs(lat_numero) > 90 or abs(lng_numero) > 180:
        return None

    return {"lat": lat_numero, "lng": lng_numero}


def ponto_da_inversa(lat: Optional[str], lng: Optional[str]) -> Tuple[Optional[Tuple[float, float]], Dict[str, str]]:
    """`((lat, lng), {})`, ou `(None, erros)` pela ordem lat, lng: cada um tem
    de ser um número e estar em Portugal continental."""
    lat_numero = numero(lat)
    lng_numero = numero(lng)
    erros = {}

    if lat_numero is None:
        erros["lat"] = MENSAGEM_LATITUDE
    elif not contem_latitude(lat_numero):
        erros["lat"] = MENSAGEM_PORTUGAL

    if lng_numero is None:
        erros["lng"] = MENSAGEM_LONGITUDE
    elif not contem_longitude(lng_numero):
        erros["lng"] = MENSAGEM_PORTUGAL

    if erros:
        return None, erros

    return (lat_numero, lng_numero), {}


async def _pedir(servico: str, url_de, indisponivel: str):
    """O JSON da Geoapify para o URL `url_de(url_base, chave)`.

    503 `morada_indisponivel` (com a mensagem `indisponivel`) sem chave — sem
    chamar a Geoapify nem registar nada — ou se a Geoapify falhar, com um
    registo só com o motivo."""
    chave = geoapify.chave_servidor()

    if chave == "":
        raise erro(503, "morada_indisponivel", indisponivel)

    try:
        return await geoapify.obter_json(url_de(geoapify.url_base(), chave))
    except geoapify.FalhaServicoExterno as falha:
        motivo = falha.motivo

    logger.warning("[crm] morada: a Geoapify falhou na %s — %s", servico, motivo)
    raise erro(503, "morada_indisponivel", indisponivel)


@router.get("/morada/pesquisa")
async def pesquisa(
    membro: Dict = Depends(ESCRITORIO),
    texto: Optional[str] = None,
    lat: Optional[str] = None,
    lng: Optional[str] = None,
) -> List[Dict]:
    """Até 5 `{rotulo, morada, codigo_postal, localidade, lat, lng}`."""
    aparado, erros = texto_da_pesquisa(texto)

    if erros:
        raise validacao(erros)

    perto = bias(lat, lng)
    resposta = await _pedir(
        "pesquisa",
        lambda base, chave: geoapify.url_pesquisa(base, chave, aparado, perto),
        PESQUISA_INDISPONIVEL,
    )

    return geoapify.normalizar_autocomplete(resposta)


@router.get("/morada/inversa")
async def inversa(
    membro: Dict = Depends(ESCRITORIO),
    lat: Optional[str] = None,
    lng: Optional[str] = None,
) -> Optional[Dict]:
    """A morada do ponto `{rotulo, morada, codigo_postal, localidade, lat,
    lng}`, ou `null`."""
    ponto, erros = ponto_da_inversa(lat, lng)

    if erros:
        raise validacao(erros)

    lat_numero, lng_numero = ponto
    resposta = await _pedir(
        "inversa",
        lambda base, chave: geoapify.url_inversa(base, chave, lat_numero, lng_numero),
        INVERSA_INDISPONIVEL,
    )

    return geoapify.normalizar_inversa(resposta)
