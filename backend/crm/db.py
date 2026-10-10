"""Acesso à base de dados do CRM.

Não há cliente próprio: `obter_db()` devolve a base da Faturação
(`faturacao.db.obter_db`), para o portal ter um só conjunto de ligações ao
Atlas. O cliente é criado à primeira utilização, por isso o pacote importa-se
nos testes sem MONGO_URL nem DB_NAME.

Todos os módulos do CRM chamam a base ATRAVÉS deste módulo
(`from crm import db as bd` → `bd.obter_db()`), nunca com
`from crm.db import obter_db`: assim os testes trocam a base num sítio só
(`monkeypatch.setattr(crm.db, "obter_db", lambda: base)`).
"""
import logging

from faturacao import db as _fat_db

logger = logging.getLogger(__name__)

# Nomes das coleções, todos com o prefixo crm_ (convenção do repositório:
# fat_, fin_, mkt_). Cada coleção entra aqui com a tarefa que a usa — na F1 só
# existem os membros; regiões, lojas, interações e definições chegam na F2.
COLECOES = {
    # Quem entra no CRM e com que perfil (admin, utilizador, motorista). O
    # admin master do portal é admin do CRM sem precisar de linha aqui.
    "membros": "crm_membros",
}

# (coleção, chaves, opções). Declarados como dados para serem testáveis sem
# Mongo (tests/crm/test_indices.py). Toda a coleção tem `id` único, exceto
# crm_definicoes (chega na F2), que tem `chave` único e NUNCA índice em `id`:
# os documentos não têm `id`, e um campo em falta entra num índice único como
# null — o segundo upsert dava E11000.
INDICES = [
    ("crm_membros", [("id", 1)], {"unique": True}),
    # Uma conta do portal é membro no máximo uma vez. É a garantia contra
    # duas pessoas a adicionarem a mesma conta ao mesmo tempo (T1.7).
    ("crm_membros", [("user_id", 1)], {"unique": True}),
]


def obter_db():
    """A base do portal, pelo cliente da Faturação (um só conjunto de ligações)."""
    return _fat_db.obter_db()


async def criar_indices(db):
    """Aplica os índices. Uma falha é registada mas NÃO impede os seguintes nem
    o arranque — o CRM tem de subir mesmo que um índice não possa ser criado."""
    for coleccao, chaves, opcoes in INDICES:
        try:
            await db[coleccao].create_index(chaves, **opcoes)
        except Exception as e:  # noqa: BLE001 — arrancar é mais importante
            logger.error("[crm] índice %s %s falhou: %s: %s", coleccao, chaves, type(e).__name__, e)
