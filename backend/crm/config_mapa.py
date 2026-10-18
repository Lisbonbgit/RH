"""`GET /api/crm/config` — a configuração do mapa: a chave do navegador e o
Map ID da Google, e o centro.

Plano do mapa Google (G2; antes T2.13); dossiê §6 e §8. Porta de
src/Http/ConfigMapa.php do CRM autónomo, onde este "mapa" vinha dentro do
`GET /api/sessao`; aqui é uma rota própria, para o escritório (admin e
utilizador do CRM; o motorista só entra na F4). Responde
`{google: {chave, map_id} | null, centro: {lat, lng}}`:

- `google` leva a chave do navegador (`CRM_GOOGLE_CHAVE_NAVEGADOR`) e o Map ID
  (`CRM_GOOGLE_MAP_ID`), tal e qual (vão no JSON, não num URL). As duas são
  obrigatórias: falta uma, ou está vazia, e vai `null` — o ecrã diz "Mapa não
  configurado". Não há mapa alternativo.
- A chave do navegador é pública por natureza (qualquer membro a vê nas
  ferramentas do browser): o que a protege é a restrição por referrer e por
  API na consola Google (Maps JavaScript + Places (New), `https://lisbonb.com/*`)
  e os tetos de uso. Por isso vai ao browser de propósito, só a membros do
  escritório (esta rota nunca é pública) e sem proxy no servidor.
- O centro é o ponto da fábrica, das definições em vigor (o mapa usa-o quando
  ainda não há lojas).

A chave e o Map ID leem-se do ambiente a cada pedido (não à importação) e
nunca se escrevem nos registos.
"""
import os
from typing import Dict, Optional

from fastapi import APIRouter, Depends

from . import db as bd
from .auth import ESCRITORIO
from .definicoes import em_vigor

router = APIRouter()

VARIAVEL_CHAVE = "CRM_GOOGLE_CHAVE_NAVEGADOR"
VARIAVEL_MAP_ID = "CRM_GOOGLE_MAP_ID"


def chave_navegador() -> str:
    """A chave do navegador, lida do ambiente a cada chamada ("" sem ela)."""
    return os.environ.get(VARIAVEL_CHAVE, "")


def map_id_google() -> str:
    """O Map ID, lido do ambiente a cada chamada ("" sem ele)."""
    return os.environ.get(VARIAVEL_MAP_ID, "")


def config_mapa(chave: str, map_id: str, definicoes: Dict) -> Dict:
    """O "mapa" a partir da chave do navegador, do Map ID e das definições em
    vigor (`definicoes.em_vigor` / `dominio.definicoes.combinar`). Só o texto
    vazio conta como "sem valor", como no autónomo (`$chave === ''`); os dois
    têm de existir para o mapa carregar."""
    google: Optional[Dict] = None if chave == "" or map_id == "" else {"chave": chave, "map_id": map_id}

    return {
        "google": google,
        "centro": {"lat": definicoes["fabrica_lat"], "lng": definicoes["fabrica_lng"]},
    }


@router.get("/config")
async def ver_config(membro: Dict = Depends(ESCRITORIO)) -> Dict:
    """`{google: {chave, map_id} | null, centro: {lat, lng}}`."""
    return config_mapa(chave_navegador(), map_id_google(), await em_vigor(bd.obter_db()))
