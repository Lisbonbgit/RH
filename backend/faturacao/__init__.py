"""Módulo Faturação L'Açaí — POS e backoffice das lojas.

Vive como pacote próprio (e não dentro do server.py) por duas razões: o server.py
já tem 8150 linhas, e um pacote isolado significa que uma avaria aqui não derruba
o RH, o Financeiro nem o Marketing.
"""
import asyncio
import logging

from fastapi import APIRouter

from .db import (  # noqa: F401
    COLECOES,
    criar_indices,
    indice_idempotencia_presente,
    indice_notas_credito_presente,
    marcar_indice_idempotencia,
    marcar_indice_notas_credito,
    obter_db,
)

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

# As fotos dos produtos: carregar uma do computador do dono, e servi-la.
#
# As rotas vivem debaixo de `/produtos/` e o catálogo já lá tem
# `/produtos/{produto_id}` — o FastAPI resolve pela ORDEM de registo, por isso
# o cruzamento merece ser visto e não presumido: `POST /produtos/fotos` não
# colide (a única POST do catálogo é em `/produtos`) e `GET
# /produtos/fotos/{nome}` tem DOIS segmentos, que nenhuma rota do catálogo
# apanha. Quem mexer nestes caminhos tem `test_fotos_dos_produtos.py::
# test_as_rotas_das_fotos_nao_sao_TAPADAS_pelas_do_catalogo` a resolvê-los
# contra o router a sério.
from .fotos import router as _fotos
router.include_router(_fotos)

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

from .fiscal import router as _fiscal
router.include_router(_fiscal)

from .pos_catalogo import router as _pos_catalogo
router.include_router(_pos_catalogo)

from .modo import router as _modo
router.include_router(_modo)

# O separador Faturação do POS: ler os documentos já emitidos, e as acções
# sobre um deles. Entra DEPOIS de `venda` e de `fiscal` de propósito — é deles
# que importa `abrir_venda`/`juntar_linha` e `_itens_vendus`, e nenhum dos dois
# importa este, por isso não há ciclo nenhum a adiar.
from .documentos import router as _documentos
router.include_router(_documentos)

# A nota de crédito, dentro de uma fatura do separador acima. Depois de
# `documentos` porque é de lá que importa o âmbito da loja (`_documento_da_loja`)
# e as linhas da fatura, e depois de `fiscal` porque partilha com ele a forma da
# emissão (reservar antes de falar com o Vendus, verificar por referência
# externa depois de um timeout).
from .nota_credito import router as _nota_credito
router.include_router(_nota_credito)

# A FILA DE IMPRESSÃO e as rotas do programa da loja. Entra por último de
# propósito: é o único módulo que ninguém mais importa por dentro (o
# `fiscal.py` e o `caixa.py` importam-no LOCALMENTE, dentro da função que
# enfileira, para não fechar o ciclo `impressao → talao → ...`), e é o único
# cuja avaria não pode travar nada — sem ele o POS vende e emite na mesma, só
# não sai papel.
from .impressao import router as _impressao
router.include_router(_impressao)


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
        try:
            await asyncio.wait_for(criar_indices(db), timeout=LIMITE_INDICES_SEGUNDOS)
        except asyncio.TimeoutError:
            logger.error(
                "[faturacao] criação de índices excedeu %ss — módulo arrancado sem eles",
                LIMITE_INDICES_SEGUNDOS,
            )
        # I3: nunca ASSUMIR que o índice único de fat_refs_fiscais.ext_ref
        # (a garantia central da idempotência do POS) ficou criado só
        # porque criar_indices não levantou nada — com um Atlas lento, é o
        # último dos 22 índices declarados, o primeiro a ficar por criar
        # quando o LIMITE_INDICES_SEGUNDOS corta a espera. Verificado a
        # sério, SEMPRE, independentemente de criar_indices ter conseguido
        # correr até ao fim ou não.
        #
        # Achado da re-revisão do núcleo fiscal: esta chamada corria FORA do
        # wait_for que protege criar_indices — com o Mongo pendurado (não a
        # levantar excepção, só nunca a responder: um Atlas em baixo,
        # index_information() bloqueado à espera de selecção de servidor),
        # isto somava o tempo limite por omissão do PyMongo (~30s) ao
        # arranque do PORTAL INTEIRO, RH e Financeiro incluídos — mesmo com
        # criar_indices já bem-sucedido. Envolvida no MESMO limite; esgotar
        # o tempo conta como "não está presente", nunca como "não consegui
        # verificar, assumo que está lá".
        try:
            indice_ok = await asyncio.wait_for(
                indice_idempotencia_presente(db), timeout=LIMITE_INDICES_SEGUNDOS
            )
        except asyncio.TimeoutError:
            logger.error(
                "[faturacao] verificação do índice de idempotência excedeu "
                "%ss — tratada como ausente",
                LIMITE_INDICES_SEGUNDOS,
            )
            indice_ok = False
        marcar_indice_idempotencia(indice_ok)
        # A segunda reserva atómica do módulo, confirmada com o mesmo
        # critério e dentro do mesmo limite de tempo: sem o único de
        # `fat_notas_credito.id`, o duplo-toque no botão «Emitir Nota de
        # Crédito» entrega DUAS notas reais à AT — e a rota recusa-se a
        # emitir até isto estar confirmado (`nota_credito.py`).
        try:
            indice_nc_ok = await asyncio.wait_for(
                indice_notas_credito_presente(db), timeout=LIMITE_INDICES_SEGUNDOS
            )
        except asyncio.TimeoutError:
            logger.error(
                "[faturacao] verificação do índice das notas de crédito "
                "excedeu %ss — tratada como ausente",
                LIMITE_INDICES_SEGUNDOS,
            )
            indice_nc_ok = False
        marcar_indice_notas_credito(indice_nc_ok)
        if not indice_nc_ok:
            logger.error(
                "[faturacao] índice único de fat_notas_credito.id não "
                "confirmado — o POS vai recusar emitir notas de crédito "
                "até isto ser corrigido (ver faturacao.nota_credito)."
            )
        if not indice_ok:
            logger.error(
                "[faturacao] índice único de fat_refs_fiscais.ext_ref não "
                "confirmado — o POS vai recusar emitir faturas até isto "
                "ser corrigido (ver faturacao.fiscal.finalizar)."
            )
    except Exception as e:  # noqa: BLE001 — nada pode propagar daqui, ver docstring acima
        marcar_indice_idempotencia(False)
        marcar_indice_notas_credito(False)
        logger.error("[faturacao] arranque do módulo falhou: %s", e)


@router.get("/saude")
async def saude():
    """Diz que o módulo está montado. Não toca na base de dados de propósito."""
    return {"estado": "ok", "modulo": "faturacao"}
