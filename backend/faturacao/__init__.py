"""Módulo Faturação L'Açaí — POS e backoffice das lojas.

Vive como pacote próprio (e não dentro do server.py) por duas razões: o server.py
já tem 8150 linhas, e um pacote isolado significa que uma avaria aqui não derruba
o RH, o Financeiro nem o Marketing.
"""
import asyncio
import logging

from fastapi import APIRouter

from .db import COLECOES, criar_indices, obter_db  # noqa: F401

logger = logging.getLogger(__name__)

# Tempo máximo (segundos) para a criação de índices no arranque. criar_indices já
# apanha a falha de CADA índice individualmente, mas com 9 índices e o Mongo
# lento cada create_index pode esperar até ao tempo limite de selecção de
# servidor (30s por omissão) — minutos de soma, com o portal a não responder, e
# o HEALTHCHECK do Dockerfile marca unhealthy aos 110s. Este limite corta a
# espera total; se estourar, o módulo arranca sem índices (mais lento, não
# indisponível).
LIMITE_INDICES_SEGUNDOS = 10

router = APIRouter(prefix="/api/faturacao", tags=["faturacao"])

from .lojas import router as _lojas
router.include_router(_lojas)

from .pagamentos import router as _pagamentos
router.include_router(_pagamentos)

from .utilizadores import router as _utilizadores
router.include_router(_utilizadores)

from .motivos import router as _motivos
router.include_router(_motivos)

from .catalogo import router as _catalogo
router.include_router(_catalogo)

from .importacao import router as _importacao
router.include_router(_importacao)

from .dashboard import router as _dashboard
router.include_router(_dashboard)

from .pos_auth import router as _pos_auth
router.include_router(_pos_auth)

from .caixa import router as _caixa
router.include_router(_caixa)

from .venda import router as _venda
router.include_router(_venda)


async def arrancar():
    """Chamado pelo server.py no arranque.

    Todo o corpo está dentro de um único try/except: o desenho promete (ver a
    docstring do módulo) que uma avaria aqui nunca derruba o RH, o Financeiro
    nem o Marketing, que correm no mesmo server.py e estão em produção. Antes
    o try/except só existia dentro de criar_indices, à volta de cada
    create_index — mas obter_db() era chamado fora dele, e é aí que o cliente
    Motor é construído. Com um URI mongodb+srv:// (o que a produção usa, é
    Atlas), o PyMongo resolve o DNS de forma síncrona na construção do
    cliente e levanta ConfigurationError se falhar; essa excepção saía de
    arrancar() sem ninguém a apanhar, rebentava o evento de arranque do
    FastAPI e abortava o worker do uvicorn — caía tudo. Por isso nada, nem a
    construção do cliente nem a criação dos índices, pode propagar daqui.
    """
    try:
        db = obter_db()
        await asyncio.wait_for(criar_indices(db), timeout=LIMITE_INDICES_SEGUNDOS)
    except asyncio.TimeoutError:
        logger.error(
            "[faturacao] criação de índices excedeu %ss — módulo arrancado sem eles",
            LIMITE_INDICES_SEGUNDOS,
        )
    except Exception as e:  # noqa: BLE001 — nada pode propagar daqui, ver docstring acima
        logger.error("[faturacao] arranque do módulo falhou: %s", e)


@router.get("/saude")
async def saude():
    """Diz que o módulo está montado. Não toca na base de dados de propósito."""
    return {"estado": "ok", "modulo": "faturacao"}
