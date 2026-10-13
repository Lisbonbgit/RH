"""O duplo do Mongo (tests/crm/duplos.py) porta-se como o Motor nos pontos de
que os testes do CRM dependem — senão um teste verde não prova nada.

Molde: `_como_o_motor` de tests/faturacao/test_catalogo.py e o duplo de
tests/faturacao/test_fiscal.py (únicos, cópias fundas, cedência ao ciclo).
"""
import asyncio
import copy
from pathlib import Path

import pytest
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, OperationFailure

from .duplos import BaseFalsa, ColeccaoFalsa, correr, unicos_declarados


# --- correr(): nunca mexe no ciclo de eventos da thread principal ------------


async def _devolve(valor):
    await asyncio.sleep(0)
    return valor


def test_correr_devolve_o_resultado_da_corrotina():
    assert correr(_devolve(42)) == 42


def test_correr_nao_mexe_no_ciclo_de_eventos_da_thread_principal():
    """Correção obrigatória do plano (§10): o asyncio.run, ao terminar, chama
    set_event_loop(None), e dezenas de testes da Faturação/Financeiro que
    usam asyncio.get_event_loop() rebentavam a seguir na suite completa."""
    antes = asyncio.get_event_loop()
    correr(_devolve(1))
    assert asyncio.get_event_loop() is antes
    assert not antes.is_closed()


def test_nenhum_teste_do_crm_usa_o_run_do_asyncio():
    """A mesma regra, guardada para sempre (o grep da T1.15/T2.32)."""
    proibido = "asyncio.run" + "("
    pasta = Path(__file__).parent
    culpados = [
        p.name for p in sorted(pasta.rglob("*.py")) if proibido in p.read_text(encoding="utf-8")
    ]
    assert culpados == []


# --- BaseFalsa ----------------------------------------------------------------


def test_base_devolve_a_mesma_coleccao_por_nome_e_por_atributo():
    base = BaseFalsa()
    assert base["crm_membros"] is base["crm_membros"]
    assert base.crm_membros is base["crm_membros"]
    assert base.users.nome == "users"


@pytest.mark.parametrize("nome", ["_pytest_algo", "__deepcopy__", "__wrapped__", "_colecoes_x"])
def test_base_levanta_attributeerror_para_nomes_com_sublinhado(nome):
    """Como a Database do Motor: nomes começados por `_` nunca são coleções
    (senão o copy/inspect/pytest recebiam uma ColeccaoFalsa e davam erros
    estranhos)."""
    base = BaseFalsa()
    with pytest.raises(AttributeError):
        getattr(base, nome)
    assert not hasattr(base, nome)


def test_base_pode_ser_copiada_a_fundo_sem_erros_estranhos():
    base = BaseFalsa({"users": [{"id": "u1"}]})
    copia = copy.deepcopy(base)
    assert correr(copia["users"].find_one({"id": "u1"}, {"_id": 0})) == {"id": "u1"}


def test_base_aceita_listas_de_documentos_e_coleccoes_ja_feitas():
    feita = ColeccaoFalsa([{"chave": "fabrica_lat"}], unicos=("chave",))
    base = BaseFalsa({"users": [{"id": "u1", "email": "a@example.com"}], "crm_definicoes": feita})
    assert base["crm_definicoes"] is feita
    assert feita.nome == "crm_definicoes"
    assert correr(base.users.count_documents({})) == 1


def test_base_copia_os_documentos_iniciais():
    """Mudar a lista do teste depois de criar a base não muda a base."""
    inicial = [{"id": "u1", "nome": "Ana"}]
    base = BaseFalsa({"users": inicial})
    inicial[0]["nome"] = "mudado"
    assert correr(base.users.find_one({"id": "u1"}))["nome"] == "Ana"


def test_unicos_vem_dos_indices_declarados_em_crm_db():
    """O duplo impõe os mesmos únicos que a produção declara (crm.db.INDICES)."""
    assert BaseFalsa()["crm_membros"].unicos == unicos_declarados("crm_membros")
    assert set(unicos_declarados("crm_membros")) == {"id", "user_id"}


def test_coleccao_fora_dos_indices_tem_id_unico_por_omissao():
    assert unicos_declarados("users") == ("id",)
    assert BaseFalsa().users.unicos == ("id",)


def test_unicos_ignora_indices_parciais_esparsos_e_compostos(monkeypatch):
    import crm.db

    monkeypatch.setattr(
        crm.db,
        "INDICES",
        [
            ("crm_x", [("id", 1)], {"unique": True}),
            ("crm_x", [("client_uuid", 1)], {"unique": True, "partialFilterExpression": {"client_uuid": {"$type": "string"}}}),
            ("crm_x", [("talvez", 1)], {"unique": True, "sparse": True}),
            ("crm_x", [("a", 1), ("b", 1)], {"unique": True}),
            ("crm_x", [("loja_id", 1)], {}),
            ("crm_y", [("chave", 1)], {"unique": True}),
        ],
    )
    assert unicos_declarados("crm_x") == ("id",)
    assert unicos_declarados("crm_y") == ("chave",)


# --- Campos únicos -------------------------------------------------------------


def test_recusa_o_segundo_insert_one_com_o_mesmo_user_id():
    col = ColeccaoFalsa(unicos=("id", "user_id"))
    correr(col.insert_one({"id": "m1", "user_id": "u1", "perfil": "admin"}))
    with pytest.raises(DuplicateKeyError):
        correr(col.insert_one({"id": "m2", "user_id": "u1", "perfil": "utilizador"}))
    assert [d["id"] for d in col.docs] == ["m1"]


def test_base_recusa_membro_repetido_sem_configuracao_extra():
    base = BaseFalsa()
    correr(base.crm_membros.insert_one({"id": "m1", "user_id": "u1"}))
    with pytest.raises(DuplicateKeyError):
        correr(base.crm_membros.insert_one({"id": "m2", "user_id": "u1"}))


def test_campo_unico_em_falta_conta_como_null_e_colide_como_no_mongo():
    """No Mongo real um campo em falta entra num índice único como null, e o
    segundo documento sem ele dá E11000 — é a armadilha de pôr `id` único em
    crm_definicoes (correções do plano, T1.2/T2.8)."""
    col = ColeccaoFalsa(unicos=("id",))
    correr(col.insert_one({"chave": "fabrica_lat"}))
    with pytest.raises(DuplicateKeyError):
        correr(col.insert_one({"chave": "fabrica_lng"}))


def test_update_one_que_repete_um_unico_de_outro_documento_e_recusado():
    col = ColeccaoFalsa([{"id": "r1", "nome_chave": "lisboa"}, {"id": "r2", "nome_chave": "porto"}], unicos=("id", "nome_chave"))
    with pytest.raises(DuplicateKeyError):
        correr(col.update_one({"id": "r2"}, {"$set": {"nome_chave": "lisboa"}}))
    assert correr(col.find_one({"id": "r2"}))["nome_chave"] == "porto"


def test_update_one_pode_manter_o_proprio_valor_unico():
    col = ColeccaoFalsa([{"id": "r1", "nome_chave": "setubal", "nome": "setubal"}], unicos=("id", "nome_chave"))
    r = correr(col.update_one({"id": "r1"}, {"$set": {"nome_chave": "setubal", "nome": "Setúbal"}}))
    assert (r.matched_count, r.modified_count) == (1, 1)


# --- insert_one ---------------------------------------------------------------


def test_insert_one_poe_id_mongo_no_dicionario_de_quem_chama_como_o_pymongo():
    """O PyMongo acrescenta `_id` ao próprio dicionário passado. Devolver esse
    dicionário numa resposta dá um ObjectId que o FastAPI não serializa — o
    duplo reproduz isto para os testes das rotas o apanharem."""
    col = ColeccaoFalsa()
    doc = {"id": "l1", "nome": "Loja"}
    r = correr(col.insert_one(doc))
    assert "_id" in doc
    assert r.inserted_id == doc["_id"]
    assert correr(col.find_one({"id": "l1"}, {"_id": 0})) == {"id": "l1", "nome": "Loja"}


def test_insert_one_guarda_uma_copia():
    col = ColeccaoFalsa()
    doc = {"id": "l1", "janelas": [{"inicio": "10:00"}]}
    correr(col.insert_one(doc))
    doc["janelas"][0]["inicio"] = "mudado"
    assert col.docs[0]["janelas"][0]["inicio"] == "10:00"


# --- find_one / find -------------------------------------------------------------


def test_find_one_devolve_copia_e_mutar_o_resultado_nao_muda_a_base():
    col = ColeccaoFalsa([{"id": "l1", "janelas": [{"inicio": "10:00"}]}])
    lido = correr(col.find_one({"id": "l1"}))
    lido["janelas"][0]["inicio"] = "mudado"
    lido["nome"] = "novo"
    assert correr(col.find_one({"id": "l1"}, {"_id": 0})) == {"id": "l1", "janelas": [{"inicio": "10:00"}]}


def test_find_one_sem_resultado_devolve_none():
    assert correr(ColeccaoFalsa().find_one({"id": "nada"})) is None


def test_find_one_aceita_projection_por_nome():
    col = ColeccaoFalsa([{"id": "u1", "password": "hash"}])
    assert correr(col.find_one({"id": "u1"}, projection={"_id": 0, "id": 1})) == {"id": "u1"}


def test_find_devolve_cursor_com_sort_limit_e_to_list():
    col = ColeccaoFalsa([
        {"id": "a", "ordem": 2, "nome": "B"},
        {"id": "b", "ordem": 1, "nome": "Z"},
        {"id": "c", "ordem": 1, "nome": "A"},
        {"id": "d", "ordem": 3, "nome": "C"},
    ])
    docs = correr(col.find({}, {"_id": 0, "id": 1}).sort([("ordem", 1), ("nome", 1)]).to_list(100))
    assert [d["id"] for d in docs] == ["c", "b", "a", "d"]
    docs = correr(col.find({}, {"_id": 0}).sort("ordem", -1).limit(2).to_list(100))
    assert [d["id"] for d in docs] == ["d", "a"]
    assert len(correr(col.find({}).to_list(3))) == 3
    assert len(correr(col.find({}).to_list(None))) == 4


def test_sort_poe_os_campos_em_falta_primeiro_como_o_mongo():
    col = ColeccaoFalsa([{"id": "a", "regiao_id": "r2"}, {"id": "b"}, {"id": "c", "regiao_id": "r1"}])
    docs = correr(col.find({}).sort("regiao_id", 1).to_list(10))
    assert [d["id"] for d in docs] == ["b", "c", "a"]


def test_find_le_a_base_so_no_to_list_como_o_motor():
    col = ColeccaoFalsa()
    cursor = col.find({})
    correr(col.insert_one({"id": "l1"}))
    assert [d["id"] for d in correr(cursor.to_list(10))] == ["l1"]


def test_find_devolve_copias():
    col = ColeccaoFalsa([{"id": "l1", "dias_fechada": ["dom"]}])
    docs = correr(col.find({}).to_list(10))
    docs[0]["dias_fechada"].append("seg")
    assert col.docs[0]["dias_fechada"] == ["dom"]


def test_cursor_aceita_async_for():
    col = ColeccaoFalsa([{"id": "a"}, {"id": "b"}])

    async def _ler():
        return [d["id"] async for d in col.find({})]

    assert correr(_ler()) == ["a", "b"]


# --- Filtros ----------------------------------------------------------------


DOCS_FILTRO = [
    {"id": "a", "fase": "cliente", "regiao_id": "r1", "dias_fechada": ["dom"], "loc": {"type": "Point", "coordinates": [-9.1, 38.7]}},
    {"id": "b", "fase": "potencial", "regiao_id": None, "dias_fechada": []},
    {"id": "c", "fase": "perdida", "dias_fechada": ["sab", "dom"], "loc": None},
]


def _ids(filtro):
    col = ColeccaoFalsa(DOCS_FILTRO)
    return [d["id"] for d in correr(col.find(filtro).to_list(100))]


@pytest.mark.parametrize(
    "filtro, esperado",
    [
        ({}, ["a", "b", "c"]),
        (None, ["a", "b", "c"]),
        ({"fase": "cliente"}, ["a"]),
        ({"fase": "cliente", "regiao_id": "r2"}, []),
        ({"regiao_id": None}, ["b", "c"]),  # null casa com null e com campo em falta
        ({"dias_fechada": "dom"}, ["a", "c"]),  # igualdade dentro de lista
        ({"dias_fechada": []}, ["b"]),
        ({"fase": {"$ne": "cliente"}}, ["b", "c"]),
        ({"regiao_id": {"$ne": None}}, ["a"]),
        ({"fase": {"$in": ["cliente", "perdida"]}}, ["a", "c"]),
        ({"fase": {"$nin": ["cliente", "perdida"]}}, ["b"]),
        ({"regiao_id": {"$exists": True}}, ["a", "b"]),
        ({"regiao_id": {"$exists": False}}, ["c"]),
        ({"id": {"$ne": "a"}, "fase": {"$in": ["cliente", "potencial"]}}, ["b"]),
        ({"loc.type": "Point"}, ["a"]),
    ],
    ids=[
        "vazio", "none", "igualdade", "duas-condicoes", "null-e-em-falta", "dentro-de-lista",
        "lista-vazia", "ne", "ne-null", "in", "nin", "exists-true", "exists-false",
        "ne-e-in", "caminho-com-ponto",
    ],
)
def test_filtros(filtro, esperado):
    assert _ids(filtro) == esperado


def test_geowithin_e_uma_simplificacao_que_devolve_todos_com_loc():
    """Simplificação documentada: o duplo não faz geometria. Devolve todas as
    lojas com `loc` e a regra exata dos 50 m é provada no domínio (T2.3) e no
    Mongo local (T2.17)."""
    filtro = {"loc": {"$geoWithin": {"$centerSphere": [[-9.1, 38.7], 60 / 6371000]}}}
    assert _ids(filtro) == ["a"]


def test_booleano_nao_casa_com_inteiro():
    col = ColeccaoFalsa([{"id": "a", "ativo": True}, {"id": "b", "ativo": 1}])
    assert [d["id"] for d in correr(col.find({"ativo": True}).to_list(10))] == ["a"]


@pytest.mark.parametrize("filtro", [{"n": {"$gt": 1}}, {"$or": [{"id": "a"}]}])
def test_operador_nao_suportado_rebenta_em_vez_de_mentir(filtro):
    col = ColeccaoFalsa([{"id": "a", "n": 2}])
    with pytest.raises(NotImplementedError):
        correr(col.find_one(filtro))


# --- Projeções -------------------------------------------------------------------


def test_projecao_de_inclusao_com_id_a_zero():
    col = ColeccaoFalsa([{"id": "u1", "name": "Ana", "email": "a@example.com", "password": "hash"}])
    lido = correr(col.find_one({"id": "u1"}, {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1}))
    assert lido == {"id": "u1", "name": "Ana", "email": "a@example.com"}


def test_projecao_de_inclusao_mantem_id_mongo_se_nao_for_pedido_a_zero():
    col = ColeccaoFalsa([{"id": "u1", "name": "Ana"}])
    lido = correr(col.find_one({"id": "u1"}, {"name": 1}))
    assert set(lido) == {"_id", "name"}


def test_projecao_de_exclusao():
    col = ColeccaoFalsa([{"id": "u1", "name": "Ana", "password": "hash"}])
    assert correr(col.find_one({"id": "u1"}, {"_id": 0, "password": 0})) == {"id": "u1", "name": "Ana"}
    assert correr(col.find_one({"id": "u1"}, {"_id": 0})) == {"id": "u1", "name": "Ana", "password": "hash"}


def test_projecao_que_mistura_inclusao_e_exclusao_e_recusada_como_no_mongo():
    col = ColeccaoFalsa([{"id": "u1", "name": "Ana", "password": "hash"}])
    with pytest.raises(OperationFailure):
        correr(col.find_one({"id": "u1"}, {"name": 1, "password": 0}))


# --- update_one --------------------------------------------------------------------


def test_update_one_com_filtro_que_nao_coincide_da_matched_count_zero():
    col = ColeccaoFalsa([{"id": "l1", "atualizado_em": "2026-10-10T09:00:00.000001Z", "telefone": None}])
    r = correr(col.update_one({"id": "l1", "atualizado_em": "versao-velha"}, {"$set": {"telefone": "+351 000"}}))
    assert r.matched_count == 0
    assert r.modified_count == 0
    assert r.upserted_id is None
    assert col.docs[0]["telefone"] is None


def test_update_one_com_set_altera_so_o_primeiro_que_coincide():
    col = ColeccaoFalsa([{"id": "a", "fase": "potencial"}, {"id": "b", "fase": "potencial"}])
    r = correr(col.update_one({"fase": "potencial"}, {"$set": {"fase": "cliente"}}))
    assert (r.matched_count, r.modified_count) == (1, 1)
    assert [d["fase"] for d in col.docs] == ["cliente", "potencial"]


def test_update_one_sem_mudanca_da_modified_count_zero():
    col = ColeccaoFalsa([{"id": "a", "fase": "cliente"}])
    r = correr(col.update_one({"id": "a"}, {"$set": {"fase": "cliente"}}))
    assert (r.matched_count, r.modified_count) == (1, 0)


def test_update_one_guarda_copia_do_set():
    col = ColeccaoFalsa([{"id": "a"}])
    janelas = [{"inicio": "10:00", "fim": "12:00"}]
    correr(col.update_one({"id": "a"}, {"$set": {"janelas": janelas}}))
    janelas[0]["fim"] = "mudado"
    assert col.docs[0]["janelas"][0]["fim"] == "12:00"


def test_update_one_com_upsert_cria_a_partir_do_filtro_e_do_set():
    col = ColeccaoFalsa(unicos=("chave",))
    r = correr(col.update_one({"chave": "fabrica_lat"}, {"$set": {"valor": "38.722300"}}, upsert=True))
    assert (r.matched_count, r.modified_count) == (0, 0)
    assert r.upserted_id is not None
    correr(col.update_one({"chave": "fabrica_lng"}, {"$set": {"valor": "-9.139300"}}, upsert=True))
    r = correr(col.update_one({"chave": "fabrica_lat"}, {"$set": {"valor": "38.700000"}}, upsert=True))
    assert (r.matched_count, r.modified_count, r.upserted_id) == (1, 1, None)
    assert col.sem_id() == [
        {"chave": "fabrica_lat", "valor": "38.700000"},
        {"chave": "fabrica_lng", "valor": "-9.139300"},
    ]


def test_update_one_com_set_on_insert_so_escreve_ao_criar():
    col = ColeccaoFalsa(unicos=("chave",))
    atualizacao = {"$set": {"valor": "1"}, "$setOnInsert": {"criado_em": "t0"}}
    correr(col.update_one({"chave": "k"}, atualizacao, upsert=True))
    correr(col.update_one({"chave": "k"}, {"$set": {"valor": "2"}, "$setOnInsert": {"criado_em": "t1"}}, upsert=True))
    assert col.sem_id() == [{"chave": "k", "valor": "2", "criado_em": "t0"}]


def test_update_one_sem_operadores_e_recusado_como_no_pymongo():
    col = ColeccaoFalsa([{"id": "a"}])
    with pytest.raises(ValueError):
        correr(col.update_one({"id": "a"}, {"fase": "cliente"}))


def test_update_one_com_operador_nao_suportado_rebenta():
    col = ColeccaoFalsa([{"id": "a", "n": 1}])
    with pytest.raises(NotImplementedError):
        correr(col.update_one({"id": "a"}, {"$inc": {"n": 1}}))


# --- find_one_and_update ------------------------------------------------------------


def test_find_one_and_update_devolve_o_documento_depois_com_a_projecao():
    col = ColeccaoFalsa([{"id": "r1", "nome": "Porto", "nome_chave": "porto", "ordem": 2}])
    depois = correr(col.find_one_and_update(
        {"id": "r1"}, {"$set": {"ordem": 0}}, projection={"_id": 0, "id": 1, "nome": 1, "ordem": 1},
        return_document=ReturnDocument.AFTER,
    ))
    assert depois == {"id": "r1", "nome": "Porto", "ordem": 0}
    assert col.sem_id() == [{"id": "r1", "nome": "Porto", "nome_chave": "porto", "ordem": 0}]
    assert col.chamadas("find_one_and_update") == [(
        "find_one_and_update", {"id": "r1"}, {"$set": {"ordem": 0}},
        {"_id": 0, "id": 1, "nome": 1, "ordem": 1}, False, ReturnDocument.AFTER,
    )]


def test_find_one_and_update_por_omissao_devolve_o_documento_antes_como_o_pymongo():
    col = ColeccaoFalsa([{"id": "r1", "ordem": 2}])
    antes = correr(col.find_one_and_update({"id": "r1"}, {"$set": {"ordem": 0}}, projection={"_id": 0}))
    assert antes == {"id": "r1", "ordem": 2}
    assert col.sem_id() == [{"id": "r1", "ordem": 0}]


def test_find_one_and_update_sem_documento_devolve_none_e_nao_cria():
    col = ColeccaoFalsa([{"id": "r1", "ordem": 2}])
    assert correr(col.find_one_and_update(
        {"id": "nada"}, {"$set": {"ordem": 0}}, return_document=ReturnDocument.AFTER
    )) is None
    assert col.sem_id() == [{"id": "r1", "ordem": 2}]


def test_find_one_and_update_que_repete_um_unico_de_outro_documento_e_recusado():
    col = ColeccaoFalsa([{"id": "a", "nome_chave": "lisboa"}, {"id": "b", "nome_chave": "porto"}], unicos=("id", "nome_chave"))
    with pytest.raises(DuplicateKeyError):
        correr(col.find_one_and_update({"id": "b"}, {"$set": {"nome_chave": "lisboa"}}))
    assert col.sem_id() == [{"id": "a", "nome_chave": "lisboa"}, {"id": "b", "nome_chave": "porto"}]


def test_find_one_and_update_devolve_copia():
    col = ColeccaoFalsa([{"id": "a", "janelas": [{"inicio": "10:00"}]}])
    depois = correr(col.find_one_and_update({"id": "a"}, {"$set": {"x": 1}}, return_document=ReturnDocument.AFTER))
    depois["janelas"][0]["inicio"] = "mudado"
    assert col.docs[0]["janelas"][0]["inicio"] == "10:00"


@pytest.mark.parametrize("atualizacao, erro", [
    ({"ordem": 0}, ValueError),
    ({}, ValueError),
    ({"$inc": {"ordem": 1}}, NotImplementedError),
], ids=["sem operadores", "vazia", "operador não suportado"])
def test_find_one_and_update_recusa_o_que_o_pymongo_recusa_ou_o_duplo_nao_conhece(atualizacao, erro):
    col = ColeccaoFalsa([{"id": "a", "ordem": 2}])
    with pytest.raises(erro):
        correr(col.find_one_and_update({"id": "a"}, atualizacao))
    assert col.sem_id() == [{"id": "a", "ordem": 2}]


def test_find_one_and_update_com_upsert_nao_esta_modelado():
    col = ColeccaoFalsa()
    with pytest.raises(NotImplementedError):
        correr(col.find_one_and_update({"id": "a"}, {"$set": {"ordem": 0}}, upsert=True))


# --- delete / count / create_index ------------------------------------------------


def test_delete_one_e_delete_many_devolvem_deleted_count():
    col = ColeccaoFalsa([
        {"id": "i1", "loja_id": "l1", "tipo": "mudanca_fase"},
        {"id": "i2", "loja_id": "l1", "tipo": "mudanca_fase"},
        {"id": "i3", "loja_id": "l2", "tipo": "mudanca_fase"},
    ])
    assert correr(col.delete_one({"id": "nada"})).deleted_count == 0
    assert correr(col.delete_one({"id": "i3"})).deleted_count == 1
    assert correr(col.delete_many({"loja_id": "l1", "tipo": "mudanca_fase"})).deleted_count == 2
    assert col.docs == []


def test_count_documents():
    col = ColeccaoFalsa([{"id": "l1", "regiao_id": "r1"}, {"id": "l2", "regiao_id": "r1"}, {"id": "l3"}])
    assert correr(col.count_documents({"regiao_id": "r1"})) == 2
    assert correr(col.count_documents({})) == 3


def test_create_index_regista_e_devolve_o_nome():
    col = ColeccaoFalsa()
    assert correr(col.create_index([("id", 1)], unique=True)) == "id_1"
    assert correr(col.create_index([("loc", "2dsphere")])) == "loc_2dsphere"
    assert col.chamadas("create_index") == [
        ("create_index", [("id", 1)], {"unique": True}),
        ("create_index", [("loc", "2dsphere")], {}),
    ]


# --- Registo e falhas injetáveis -----------------------------------------------------


def test_registo_guarda_as_chamadas_por_ordem_e_em_copia():
    col = ColeccaoFalsa([{"id": "u1", "password": "hash"}])
    filtro = {"id": "u1"}
    correr(col.find_one(filtro, {"_id": 0, "id": 1}))
    correr(col.find(filtro, {"_id": 0}).to_list(10))
    correr(col.update_one(filtro, {"$set": {"x": 1}}))
    filtro["id"] = "mudado"
    assert col.registo == [
        ("find_one", {"id": "u1"}, {"_id": 0, "id": 1}),
        ("find", {"id": "u1"}, {"_id": 0}),
        ("update_one", {"id": "u1"}, {"$set": {"x": 1}}, False),
    ]


def test_insert_one_regista_o_documento_como_foi_passado_sem_id_mongo():
    col = ColeccaoFalsa()
    correr(col.insert_one({"id": "l1"}))
    assert col.chamadas("insert_one") == [("insert_one", {"id": "l1"})]


@pytest.mark.parametrize("operacao", ["insert_one", "find_one", "update_one", "find_one_and_update", "delete_one", "delete_many", "count_documents", "create_index", "find"])
def test_falhas_injetaveis(operacao):
    erro = RuntimeError("Mongo em baixo (simulado)")
    col = ColeccaoFalsa([{"id": "a"}], falhar={operacao: erro})
    chamadas = {
        "insert_one": lambda: col.insert_one({"id": "b"}),
        "find_one": lambda: col.find_one({"id": "a"}),
        "update_one": lambda: col.update_one({"id": "a"}, {"$set": {"x": 1}}),
        "find_one_and_update": lambda: col.find_one_and_update({"id": "a"}, {"$set": {"x": 1}}),
        "delete_one": lambda: col.delete_one({"id": "a"}),
        "delete_many": lambda: col.delete_many({}),
        "count_documents": lambda: col.count_documents({}),
        "create_index": lambda: col.create_index([("id", 1)], unique=True),
        "find": lambda: col.find({}).to_list(10),
    }
    with pytest.raises(RuntimeError, match="simulado"):
        correr(chamadas[operacao]())
    assert col.sem_id() == [{"id": "a"}]
    assert [c[0] for c in col.registo] == [operacao]


def test_falha_injetada_de_chave_duplicada_simula_a_corrida():
    col = ColeccaoFalsa(falhar={"insert_one": DuplicateKeyError("E11000 (simulado)")})
    with pytest.raises(DuplicateKeyError):
        correr(col.insert_one({"id": "m1", "user_id": "u1"}))
    assert col.docs == []


def test_falhar_com_operacao_desconhecida_e_um_erro_do_teste():
    with pytest.raises(ValueError):
        ColeccaoFalsa(falhar={"insert": RuntimeError("gralha")})
