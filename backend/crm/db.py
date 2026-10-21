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
# fat_, fin_, mkt_). Cada coleção entra aqui com a tarefa que a usa: os
# membros na F1; regiões, lojas, interações e definições na F2 (T2.8); as
# rotas na F3 (T3.14). As encomendas (F4–F5) entram com as suas tarefas.
COLECOES = {
    # Quem entra no CRM e com que perfil (admin, utilizador, motorista). O
    # admin master do portal é admin do CRM sem precisar de linha aqui.
    "membros": "crm_membros",
    # {id, nome, nome_chave, ordem}: as regiões para filtrar as lojas no mapa.
    "regioes": "crm_regioes",
    # As lojas e o seu lugar no funil (plano §3); `loc` é o ponto GeoJSON.
    "lojas": "crm_lojas",
    # A linha do tempo de cada loja (na F2 só `mudanca_fase`).
    "interacoes": "crm_interacoes",
    # {chave, valor (texto), atualizado_em, atualizado_por}: só o que o admin
    # alterou; os padrões vivem no código (crm/dominio/definicoes.py).
    "definicoes": "crm_definicoes",
    # Uma rota por dia (plano F3 §3): {id, data "AAAA-MM-DD" (Lisboa), estado,
    # versao, hora_saida, hora_regresso_limite, inicio, fim, evitar_portagens,
    # paragens embutidas (lista só de acrescentar; o terreno da F4 escreve nos
    # seus campos de cada paragem), calculo (o último Directions)}.
    "rotas": "crm_rotas",
}

# (coleção, chaves, opções). Declarados como dados para serem testáveis sem
# Mongo (tests/crm/test_indices.py, que fixa a lista exata de cada coleção).
# Toda a coleção tem `id` único, exceto crm_definicoes, que tem `chave` único
# e NUNCA índice em `id`: os documentos não têm `id`, e um campo em falta
# entra num índice único como null — o segundo upsert dava E11000.
INDICES = [
    ("crm_membros", [("id", 1)], {"unique": True}),
    # Uma conta do portal é membro no máximo uma vez. É a garantia contra
    # duas pessoas a adicionarem a mesma conta ao mesmo tempo (T1.7).
    ("crm_membros", [("user_id", 1)], {"unique": True}),
    ("crm_regioes", [("id", 1)], {"unique": True}),
    # O nome sem maiúsculas nem acentos (dominio.regioes.nome_chave): "setubal"
    # e "Setúbal" são a mesma região, sem collation do Mongo. Garante o 409
    # regiao_repetida também na corrida (DuplicateKeyError, T2.9).
    ("crm_regioes", [("nome_chave", 1)], {"unique": True}),
    ("crm_lojas", [("id", 1)], {"unique": True}),
    # O pré-filtro dos duplicados a 50 m ($geoWithin $centerSphere, T2.3).
    # `loc` tem de ser sempre um Point válido: o Mongo recusa gravar outro.
    ("crm_lojas", [("loc", "2dsphere")], {}),
    # "Esta região tem lojas?" (DELETE /regioes). Nunca único: há muitas lojas
    # por região e muitas sem região (null).
    ("crm_lojas", [("regiao_id", 1)], {}),
    ("crm_interacoes", [("id", 1)], {"unique": True}),
    # A linha do tempo de uma loja, por ordem (ix_interacoes_loja do autónomo).
    ("crm_interacoes", [("loja_id", 1), ("ocorrida_em", 1)], {}),
    # O registo feito sem rede (F4): um client_uuid repetido é o mesmo registo.
    # Único SÓ quando é texto: um índice único normal (ou sparse, que indexa o
    # null) fazia colidir todas as interações sem ele, que são todas as da F2.
    (
        "crm_interacoes",
        [("client_uuid", 1)],
        {"unique": True, "partialFilterExpression": {"client_uuid": {"$type": "string"}}},
    ),
    ("crm_definicoes", [("chave", 1)], {"unique": True}),
    ("crm_rotas", [("id", 1)], {"unique": True}),
    # Uma rota por dia (plano F3 §1): a `data` ("AAAA-MM-DD", hora de Lisboa) é
    # única. Na corrida de dois "Adicionar à rota" do mesmo dia, o segundo
    # insert dá DuplicateKeyError e o código volta a ler e acrescenta (T3.19).
    ("crm_rotas", [("data", 1)], {"unique": True}),
    # "Esta loja está numa rota?" (DELETE /lojas, T3.24) e as rotas de uma
    # loja. Multikey (uma entrada por paragem) e NUNCA único: a mesma loja está
    # em rotas de dias diferentes, e numa paragem retirada e noutra reativada.
    ("crm_rotas", [("paragens.loja_id", 1)], {}),
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
