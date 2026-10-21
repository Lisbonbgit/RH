"""`/api/crm/morada/inversa` — a morada sugerida do ponto do GPS ("Estou
nesta loja"), para o escritório (admin e utilizador do CRM).

Plano T2.15; dossiê §6 e §8. Porta de src/Http/Controladores/
MoradaControlador.php do CRM autónomo. É o servidor que pede à Geoapify, com
a chave do servidor, que nunca vai para o browser nem para os registos (o
cliente e as regras dos registos estão em crm/servicos/geoapify.py).

Desde a G18 do plano do mapa Google, a Geoapify fica só para esta morada: a
pesquisa de moradas é a da própria Google, no browser (o `GET
/morada/pesquisa` saiu e dá 404), e o ecrã só pede a inversa para o ponto do
GPS, nunca para um ponto vindo da Google (a morada desse vem da Google, ou
escreve-se à mão).

- `GET /morada/inversa?lat=&lng=` → a morada do ponto, `{rotulo, morada,
  codigo_postal, localidade, lat, lng}`, ou `null` se a Geoapify não tiver
  uma. O ponto tem de estar em Portugal continental (422), o único sítio
  onde pode ficar uma loja.
- Sem chave do servidor (o normal em local), ou com a Geoapify em baixo →
  503 `morada_indisponivel`; o pino e o GPS continuam a funcionar. Sem chave
  nem se chama a Geoapify. A ordem é: a guarda de perfil → o pedido (422) →
  a chave (503) → a Geoapify.

`lat` e `lng` leem-se como texto opcional e validam-se aqui, e não com tipos
do FastAPI (correções do plano, linhas "T2.15" e "T1.3 / T2.15"): um `float`
dava o 422 em lista e em inglês do Pydantic, e aceitava `1e2`, `nan` e
`inf`. Um número é o que o browser escreve (`NUMERO`). Um parâmetro repetido
vale o último, como o `$_GET` do PHP; um `lat[]=…` é outro nome e conta como
"sem latitude".

Uma falha da Geoapify fica num registo `[crm]` (WARNING) só com o motivo — o
código HTTP ou o tipo da exceção —, nunca com o URL, a chave ou o ponto (o
RegistoErros do autónomo nunca registava a query).

No autónomo, a sessão PHP libertava-se antes de chamar a Geoapify. No portal
não há sessões trancadas: o cliente é assíncrono e, enquanto espera pela
Geoapify (até 5 s), o servidor continua a responder aos outros pedidos.
"""
import logging
import re
from typing import Dict, Optional, Tuple

from fastapi import APIRouter, Depends

from .auth import ESCRITORIO
from .dominio.geo import MENSAGEM_PORTUGAL, contem_latitude, contem_longitude
from .erros import erro, validacao
from .servicos import geoapify

logger = logging.getLogger(__name__)

router = APIRouter()

# Igual à MENSAGEM_MORADA_SUGERIDA_INDISPONIVEL de frontend/src/lib/crm/morada.js
# (test_consistencia_frontend.py, T2.22).
INVERSA_INDISPONIVEL = "Morada sugerida indisponível — escreva a morada à mão."

MENSAGEM_LATITUDE = "A latitude tem de ser um número."
MENSAGEM_LONGITUDE = "A longitude tem de ser um número."

# Um número decimal como o browser o escreve (38.7223, -9.1393): sem expoente,
# vírgula, sinal + nem espaços, só algarismos ASCII. Com `fullmatch` (o `$` do
# Python aceitava uma quebra de linha no fim; o `/D` do PHP não).
NUMERO = re.compile(r"-?[0-9]{1,3}(\.[0-9]+)?")


def numero(valor: Optional[str]) -> Optional[float]:
    """O número de um parâmetro, ou `None` se faltar ou não for `NUMERO`."""
    return float(valor) if isinstance(valor, str) and NUMERO.fullmatch(valor) else None


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
