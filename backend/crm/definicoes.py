"""`/api/crm/definicoes` — as definições da fábrica (a morada e o ponto) e das rotas (F3).

Plano T2.13; dossiê §5.9 e §6. Porta de src/Http/Controladores/
DefinicoesControlador.php e de src/Repositorios/DefinicoesRepositorio.php do
CRM autónomo. As regras do corpo e os padrões estão em
`dominio/definicoes.py` (T2.7): aqui só se lê, grava e responde.

- `GET /definicoes` (admin do CRM) → `{fabrica_morada, fabrica_lat,
  fabrica_lng, rota_hora_saida, rota_hora_regresso, servico_entrega_min,
  servico_amostra_min, servico_acompanhamento_min, servico_angariacao_min}`:
  os padrões com o que o admin alterou por cima, com as coordenadas e os
  minutos como números (`combinar`; as chaves das rotas são da F3, T3.5).
- `PATCH /definicoes` (admin) com só as chaves que mudam → 200 com as
  definições em vigor, relidas da base. Ordem: o corpo (400) → as regras
  (422, sem tocar na base nem no relógio) → uma escrita por chave → reler.
  Um PATCH vazio não escreve nada e devolve as definições.

`crm_definicoes` guarda só o que o admin alterou, `{chave, valor (texto),
atualizado_em, atualizado_por}` (plano §3), com um upsert por `chave` (índice
único; nunca `id`, crm/db.py). O `atualizado_em` é um carimbo de 6 casas em
UTC (plano §1; o autónomo usava `DATETIME` sem casas), o mesmo para todas as
chaves do pedido (um só `relogio.agora()`, o `$quando` do repositório);
`atualizado_por` é o id da conta do portal. As definições não têm bloqueio
otimista: o carimbo só diz quando mudou.

Sem transações (o autónomo gravava tudo numa): as chaves gravam-se pela ordem
dos `PADROES` (morada, lat, lng). Uma falha a meio responde 500 e deixa
gravadas as anteriores; repetir o pedido acerta (os upserts são idempotentes).
Dois admins a mudar o ponto ao mesmo tempo podem deixar a latitude de um e a
longitude do outro — cada uma vista contra Portugal continental, por isso o
ponto fica sempre lá dentro (diferença assumida, dossiê §5.9).

`em_vigor(base)` é a leitura única, partilhada com o `GET /config` (o centro
do mapa, crm/config_mapa.py).
"""
import logging
from typing import Dict

from fastapi import APIRouter, Depends

from . import db as bd
from . import relogio
from .auth import SO_ADMIN
from .dominio import definicoes as regras
from .erros import validacao
from .pedidos import corpo_json

logger = logging.getLogger(__name__)

router = APIRouter()

# O que se lê de cada definição guardada (o `SELECT chave, valor` do autónomo).
PROJECAO_GUARDADA = {"_id": 0, "chave": 1, "valor": 1}

# Teto da leitura: hoje são no máximo três linhas (mais as de versões novas).
LIMITE_LISTA = 5000


def _colecao(base):
    return base[bd.COLECOES["definicoes"]]


def _legivel(guardada: Dict) -> bool:
    """Uma linha que o `combinar` sabe ler: chave de texto e valor de texto
    (o que o CRM grava) ou um número escrito à mão (nunca um bool)."""
    valor = guardada.get("valor")
    return isinstance(guardada.get("chave"), str) and (isinstance(valor, str) or type(valor) in (int, float))


async def em_vigor(base) -> Dict:
    """As definições em vigor: os padrões com o que está guardado por cima.

    Uma linha estragada à mão (sem chave de texto, valor null, bool, lista…)
    ignora-se, com uma linha `[crm]` no registo só com a contagem: o
    `combinar` recusava-a (TypeError → 500), e o `/config` lê o mesmo — todo
    o escritório ficava sem mapa por causa de uma linha.
    """
    guardadas = await _colecao(base).find({}, PROJECAO_GUARDADA).to_list(LIMITE_LISTA)
    legiveis = [guardada for guardada in guardadas if _legivel(guardada)]
    if len(legiveis) != len(guardadas):
        logger.warning(
            "[crm] definições guardadas ignoradas por estarem estragadas: %d", len(guardadas) - len(legiveis)
        )
    return regras.combinar({guardada["chave"]: guardada["valor"] for guardada in legiveis})


@router.get("/definicoes")
async def ver_definicoes(admin: Dict = Depends(SO_ADMIN)) -> Dict:
    """As 9 definições em vigor (`combinar`), com as coordenadas e os minutos como números."""
    return await em_vigor(bd.obter_db())


@router.patch("/definicoes")
async def alterar_definicoes(admin: Dict = Depends(SO_ADMIN), corpo: Dict = Depends(corpo_json)) -> Dict:
    """Só as chaves que mudam, dos `PADROES` (a latitude e a longitude
    juntas) → as definições em vigor depois de gravar. Uma chave
    desconhecida, ou um valor inválido, dá 422 e não se grava nada."""
    valores, erros = regras.alteracao(corpo)
    if erros:
        raise validacao(erros)
    base = bd.obter_db()
    if valores:
        quando = relogio.carimbo(relogio.agora())
        definicoes = _colecao(base)
        # Pela ordem dos PADROES (a da `alteracao`): ver o docstring do módulo.
        for chave, valor in valores.items():
            await definicoes.update_one(
                {"chave": chave},
                {"$set": {"valor": valor, "atualizado_em": quando, "atualizado_por": admin["user_id"]}},
                upsert=True,
            )
    return await em_vigor(base)
