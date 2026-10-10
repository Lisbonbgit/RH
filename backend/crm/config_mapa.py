"""`GET /api/crm/config` — a configuração do mapa: os mosaicos, a alternativa
e o centro.

Plano T2.13; dossiê §6 e §8. Porta de src/Http/ConfigMapa.php do CRM
autónomo, onde este "mapa" vinha dentro do `GET /api/sessao`; aqui é uma
rota própria, para o escritório (admin e utilizador do CRM; o motorista só
entra na F4). Responde `{mosaicos: {url, atribuicao}, alternativa: {url},
centro: {lat, lng}}`:

- Com a chave dos mosaicos (`CRM_GEOAPIFY_CHAVE_MOSAICOS`), a URL principal é
  a da Geoapify com `?apiKey=<chave codificada>` e a atribuição é
  `geoapify`. A chave vai para o browser de propósito (é a dos mosaicos, não
  a do servidor) e fica restrita por Referer no painel da Geoapify (dossiê
  §8); por isso esta rota nunca é pública.
- Sem chave (o normal em local), a principal passa a ser a alternativa do
  OpenStreetMap, com a atribuição `osm`.
- A alternativa vem sempre: o mapa muda para ela sozinho se os mosaicos
  falharem (mosaicos.js).
- O centro é o ponto da fábrica, das definições em vigor (o mapa usa-o quando
  ainda não há lojas).

A chave lê-se do ambiente a cada pedido (não à importação) e nunca se escreve
nos registos.
"""
import os
from typing import Dict
from urllib.parse import quote

from fastapi import APIRouter, Depends

from . import db as bd
from .auth import ESCRITORIO
from .definicoes import em_vigor

router = APIRouter()

VARIAVEL_CHAVE = "CRM_GEOAPIFY_CHAVE_MOSAICOS"
MODELO_MOSAICOS = "https://maps.geoapify.com/v1/tile/osm-bright/{z}/{x}/{y}.png"
ALTERNATIVA = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"


def chave_mosaicos() -> str:
    """A chave dos mosaicos, lida do ambiente a cada chamada ("" sem ela)."""
    return os.environ.get(VARIAVEL_CHAVE, "")


def _codificar(chave: str) -> str:
    """O `rawurlencode` do PHP (RFC 3986): só `A-Za-z0-9-_.~` ficam, a barra
    também se codifica (`safe=""`). Os bytes que não são UTF-8 numa variável
    de ambiente chegam ao Python como surrogates (surrogateescape) e voltam a
    ser esses bytes, codificados um a um — como o PHP, sem rebentar."""
    return quote(chave.encode("utf-8", "surrogateescape"), safe="")


def config_mapa(chave: str, definicoes: Dict, modelo: str = MODELO_MOSAICOS, alternativa: str = ALTERNATIVA) -> Dict:
    """O "mapa" a partir da chave dos mosaicos e das definições em vigor
    (`definicoes.em_vigor` / `dominio.definicoes.combinar`). Só a chave vazia
    conta como "sem chave", como no autónomo (`$chave === ''`). Um modelo que
    já tem parâmetros recebe a chave com `&`."""
    if chave == "":
        mosaicos = {"url": alternativa, "atribuicao": "osm"}
    else:
        separador = "&" if "?" in modelo else "?"
        mosaicos = {"url": f"{modelo}{separador}apiKey={_codificar(chave)}", "atribuicao": "geoapify"}

    return {
        "mosaicos": mosaicos,
        "alternativa": {"url": alternativa},
        "centro": {"lat": definicoes["fabrica_lat"], "lng": definicoes["fabrica_lng"]},
    }


@router.get("/config")
async def ver_config(membro: Dict = Depends(ESCRITORIO)) -> Dict:
    """`{mosaicos: {url, atribuicao}, alternativa: {url}, centro: {lat, lng}}`."""
    return config_mapa(chave_mosaicos(), await em_vigor(bd.obter_db()))
