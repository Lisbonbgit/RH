"""Módulo CRM Purple House — mapa das lojas, fases e (mais tarde) rotas.

Vive como pacote próprio (e não dentro do server.py), no molde de `faturacao/`
e `plataformas/`: o server.py já é enorme e partilhado, e um pacote isolado
significa que uma avaria aqui não derruba o RH, o Financeiro nem a Faturação.
O server.py só monta o router e chama o arranque (T1.9); tudo o resto do CRM
(base, autenticação dos membros, regras de negócio) fica cá dentro.
"""
import asyncio
import logging

from fastapi import APIRouter

from . import db

logger = logging.getLogger(__name__)

# Tempo máximo (segundos) para criar os índices no arranque. criar_indices já
# apanha a falha de cada índice, mas com o Mongo lento cada create_index pode
# esperar até ao tempo limite de seleção de servidor (30 s por omissão) e o
# HEALTHCHECK do Dockerfile marca o portal inteiro como unhealthy. Se estourar,
# o CRM arranca sem índices (mais lento, não indisponível).
LIMITE_INDICES_SEGUNDOS = 10

router = APIRouter(prefix="/api/crm", tags=["crm"])


@router.get("/saude")
async def saude():
    """Diz que o módulo está montado. Pública e não toca na base de propósito."""
    return {"estado": "ok", "modulo": "crm"}


# As rotas de cada área vivem no seu módulo (molde de faturacao/__init__.py) e
# entram aqui. Cada rota nova é classificada no teste de proteção (T1.8).
from .eu import router as _eu  # noqa: E402
from .lojas import router as _lojas  # noqa: E402
from .membros import router as _membros  # noqa: E402
from .regioes import router as _regioes  # noqa: E402

router.include_router(_eu)
router.include_router(_membros)
router.include_router(_regioes)
router.include_router(_lojas)


async def arrancar():
    """Chamado pelo server.py no arranque (T1.9). Nunca levanta.

    Tudo dentro de um único try: é em `db.obter_db()` que o cliente Motor é
    construído, e com um URI mongodb+srv:// (o Atlas da produção) o PyMongo
    resolve o DNS de forma síncrona e levanta ConfigurationError se falhar.
    Essa exceção, solta, rebentava o evento de arranque do FastAPI e caía o
    portal todo (a lição de faturacao/__init__.py::arrancar). A base e os
    índices são lidos pelo módulo `db` para os testes os trocarem lá.
    """
    try:
        base = db.obter_db()
        await asyncio.wait_for(db.criar_indices(base), timeout=LIMITE_INDICES_SEGUNDOS)
    except asyncio.TimeoutError:
        logger.error(
            "[crm] criação de índices excedeu %ss — módulo arrancado sem eles",
            LIMITE_INDICES_SEGUNDOS,
        )
    except Exception as e:  # noqa: BLE001 — nada pode propagar daqui, ver docstring
        logger.error("[crm] arranque do módulo falhou: %s: %s", type(e).__name__, e)
