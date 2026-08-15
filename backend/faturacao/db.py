"""Acesso à base de dados do módulo Faturação.

O cliente é criado à PRIMEIRA UTILIZAÇÃO (e não ao importar o módulo) para que o
pacote possa ser importado em testes sem MONGO_URL/DB_NAME definidos.
"""
import logging
import os
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)

# Nomes das colecções, todos com prefixo fat_ (convenção do repositório: fin_, mkt_).
COLECOES = {
    "lojas": "fat_lojas",
    "caixas": "fat_caixas",
    "utilizadores": "fat_utilizadores",
    "tipos_pagamento": "fat_tipos_pagamento",
    "motivos_nc": "fat_motivos_nc",
    "categorias": "fat_categorias",
    "grupos_personalizacao": "fat_grupos_personalizacao",
    "produtos": "fat_produtos",
    # Documentos fiscais emitidos pelo POS próprio (Plano 2 enche esta colecção;
    # até lá está vazia, e uma procura numa colecção vazia devolve vazio — não
    # dá erro). É esta colecção, não o Vendus, que o Dashboard (Plano 3) lê.
    "documentos": "fat_documentos",
    # Dispositivos do POS: um código de emparelhamento de uso único (gerado
    # pelo gestor) que se troca por um token de dispositivo persistente (ver
    # faturacao/pos_auth.py). O PC da loja guarda o token no localStorage.
    "dispositivos": "fat_dispositivos",
}

_cliente = None  # type: Optional[AsyncIOMotorClient]


def obter_db():
    """Devolve a base de dados, criando o cliente na primeira chamada."""
    global _cliente
    if _cliente is None:
        _cliente = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return _cliente[os.environ["DB_NAME"]]


# (coleccao, chaves, opcoes). Declarados como dados para serem testáveis sem Mongo.
#
# NOTA: propositadamente NÃO há índice único sobre pin_hash. O bcrypt usa sal
# aleatório, por isso o mesmo PIN gera um pin_hash diferente de cada vez — um
# índice único sobre esse campo nunca detectaria PINs repetidos. Ver
# test_nao_existe_indice_unico_sobre_pin_hash e o comentário em
# faturacao/pins.py sobre como a unicidade do PIN é garantida.
INDICES = [
    ("fat_lojas", [("empresa_id", 1)], {}),
    ("fat_caixas", [("loja_id", 1)], {}),
    ("fat_utilizadores", [("ativo", 1)], {}),
    ("fat_tipos_pagamento", [("ordem", 1)], {}),
    ("fat_categorias", [("ordem", 1)], {}),
    ("fat_produtos", [("categoria_id", 1)], {}),
    ("fat_produtos", [("ativo", 1)], {}),
    ("fat_produtos", [("vendus_ref", 1)], {"sparse": True}),
    ("fat_grupos_personalizacao", [("nome", 1)], {}),
    # Dashboard: a série diária/mensal lê por data (todas as lojas) e por loja+data.
    ("fat_documentos", [("emitido_em", 1)], {}),
    ("fat_documentos", [("loja_id", 1), ("emitido_em", 1)], {}),
    # Entrada no POS: busca o dispositivo pelo hash do código (emparelhar) ou
    # do token (dispositivo_atual, em cada pedido).
    ("fat_dispositivos", [("codigo_hash", 1)], {"sparse": True}),
    ("fat_dispositivos", [("token_hash", 1)], {"sparse": True}),
]


async def criar_indices(db):
    """Aplica os índices. Uma falha é registada mas NÃO impede o arranque —
    o módulo tem de subir mesmo que um índice não possa ser criado."""
    for coleccao, chaves, opcoes in INDICES:
        try:
            await db[coleccao].create_index(chaves, **opcoes)
        except Exception as e:  # noqa: BLE001 — arrancar é mais importante
            logger.error("[faturacao] índice %s %s falhou: %s", coleccao, chaves, e)
