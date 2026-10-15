"""O duplo do Mongo (tests/crm/duplos.py) porta-se como o Motor nos pontos de
que os testes do CRM dependem — senão um teste verde não prova nada.

Molde: `_como_o_motor` de tests/faturacao/test_catalogo.py e o duplo de
tests/faturacao/test_fiscal.py (únicos, cópias fundas, cedência ao ciclo).
"""
import asyncio
import copy
from pathlib import Path

import pytest
from bson import ObjectId
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


@pytest.mark.parametrize("filtro", [{"n": {"$regex": "a"}}, {"$or": [{"id": "a"}]}])
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
        correr(col.update_one({"id": "a"}, {"$mul": {"n": 2}}))


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
    ({"$mul": {"ordem": 2}}, NotImplementedError),
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


# --- T3.14: caminhos com pontos e índices, $inc, $push e o conflito 40 ---------------
# (as rotas: o escritório escreve em `paragens.<índice>.<campo>` e acrescenta com
# $push, sempre condicionado à versão e a "nenhuma paragem com registo".)


ROTA = {
    "id": "r1",
    "data": "2026-10-20",
    "estado": "rascunho",
    "versao": 3,
    "paragens": [
        {"id": "p1", "loja_id": "l1", "ordem": 0, "estado": "pendente", "resultado": None, "concluida_em": None},
        {"id": "p2", "loja_id": "l2", "ordem": 1, "estado": "pendente", "resultado": None, "concluida_em": None},
    ],
    "calculo": None,
}

FILTRO_DO_ESCRITORIO = {
    "id": "r1",
    "versao": 3,
    "estado": {"$in": ["rascunho", "planeada"]},
    "paragens.estado": {"$nin": ["feita", "nao_feita"]},
}


def _rota():
    return ColeccaoFalsa([ROTA], unicos=("id", "data"))


def _guardada(col):
    return col.sem_id()[0]


# $set com pontos e índices


def test_set_com_caminho_por_indice_escreve_so_nessa_paragem():
    col = _rota()
    resultado = correr(col.update_one({"id": "r1"}, {"$set": {"paragens.1.ordem": 0, "paragens.0.ordem": 1}}))
    assert (resultado.matched_count, resultado.modified_count) == (1, 1)
    guardada = _guardada(col)
    assert [p["ordem"] for p in guardada["paragens"]] == [1, 0]
    assert guardada["paragens"][1]["estado"] == "pendente"
    assert len(guardada["paragens"]) == 2


def test_set_com_indice_para_la_do_fim_rebenta_e_nao_estica_a_lista():
    """O Mongo esticava a lista com nulls; o duplo rebenta, porque um índice
    para lá do fim é sempre um erro do código do escritório."""
    col = _rota()
    with pytest.raises(NotImplementedError):
        correr(col.update_one({"id": "r1"}, {"$set": {"paragens.2.ordem": 2}}))
    with pytest.raises(NotImplementedError):
        correr(col.find_one_and_update({"id": "r1"}, {"$set": {"paragens.7.ordem": 2}}))
    assert _guardada(col) == ROTA


def test_set_com_caminho_sem_indice_numa_lista_e_recusado_como_no_mongo():
    col = _rota()
    with pytest.raises(OperationFailure) as excinfo:
        correr(col.update_one({"id": "r1"}, {"$set": {"paragens.ordem": 0}}))
    assert excinfo.value.code == 28
    assert _guardada(col) == ROTA


def test_set_com_caminho_num_subdocumento_cria_o_que_falta_como_o_mongo():
    col = ColeccaoFalsa([{"id": "r1"}])
    correr(col.update_one({"id": "r1"}, {"$set": {"calculo.atual": True}}))
    assert col.sem_id() == [{"id": "r1", "calculo": {"atual": True}}]
    correr(col.update_one({"id": "r1"}, {"$set": {"calculo.assinatura": "x"}}))
    assert col.sem_id() == [{"id": "r1", "calculo": {"atual": True, "assinatura": "x"}}]


@pytest.mark.parametrize("caminho", ["calculo.atual", "versao.x", "paragens.0.estado.x"], ids=["null", "número", "texto"])
def test_set_com_caminho_atraves_de_null_ou_de_um_escalar_e_recusado_como_no_mongo(caminho):
    col = ColeccaoFalsa([{"id": "r1", "calculo": None, "versao": 3, "paragens": [{"estado": "pendente"}]}])
    with pytest.raises(OperationFailure) as excinfo:
        correr(col.update_one({"id": "r1"}, {"$set": {caminho: 1}}))
    assert excinfo.value.code == 28
    assert col.sem_id() == [{"id": "r1", "calculo": None, "versao": 3, "paragens": [{"estado": "pendente"}]}]


def test_set_por_indice_guarda_copia_e_so_altera_o_primeiro_que_coincide():
    col = ColeccaoFalsa([ROTA, {**ROTA, "id": "r2", "data": "2026-10-21"}], unicos=("id", "data"))
    valor = {"lat": 38.7, "lng": -9.1}
    correr(col.update_one({"estado": "rascunho"}, {"$set": {"paragens.0.loc": valor}}))
    valor["lat"] = 0
    assert col.docs[0]["paragens"][0]["loc"] == {"lat": 38.7, "lng": -9.1}
    assert "loc" not in col.docs[1]["paragens"][0]


# $inc


def test_inc_soma_ao_valor_e_cria_o_campo_em_falta_com_o_proprio_valor():
    col = ColeccaoFalsa([{"id": "r1", "versao": 3, "paragens": [{"n": 1}]}])
    resultado = correr(col.update_one(
        {"id": "r1"}, {"$inc": {"versao": 1, "tentativas": 2, "paragens.0.n": -1, "resumo.total": 0.5}}
    ))
    assert (resultado.matched_count, resultado.modified_count) == (1, 1)
    assert col.sem_id() == [{"id": "r1", "versao": 4, "tentativas": 2, "paragens": [{"n": 0}], "resumo": {"total": 0.5}}]


@pytest.mark.parametrize("valor", ["3", True, None, [1], {"n": 1}], ids=["texto", "booleano", "null", "lista", "dicionário"])
def test_inc_num_campo_que_nao_e_numero_e_recusado_como_no_mongo(valor):
    col = ColeccaoFalsa([{"id": "r1", "versao": valor}])
    with pytest.raises(OperationFailure) as excinfo:
        correr(col.update_one({"id": "r1"}, {"$inc": {"versao": 1}}))
    assert excinfo.value.code == 14
    assert col.sem_id() == [{"id": "r1", "versao": valor}]


@pytest.mark.parametrize("argumento", ["1", True, None, [1]], ids=["texto", "booleano", "null", "lista"])
def test_inc_com_argumento_que_nao_e_numero_e_recusado_como_no_mongo(argumento):
    col = ColeccaoFalsa([{"id": "r1", "versao": 3}])
    with pytest.raises(OperationFailure) as excinfo:
        correr(col.update_one({"id": "r1"}, {"$inc": {"versao": argumento}}))
    assert excinfo.value.code == 14
    assert col.sem_id() == [{"id": "r1", "versao": 3}]


# $push


def test_push_acrescenta_ao_fim_e_cria_a_lista_em_falta():
    col = ColeccaoFalsa([{"id": "r1", "paragens": [{"id": "p1"}]}])
    resultado = correr(col.update_one(
        {"id": "r1"}, {"$push": {"paragens": {"id": "p2"}, "avisos": "x", "resumo.itens": 1}}
    ))
    assert (resultado.matched_count, resultado.modified_count) == (1, 1)
    assert col.sem_id() == [{"id": "r1", "paragens": [{"id": "p1"}, {"id": "p2"}], "avisos": ["x"], "resumo": {"itens": [1]}}]


def test_push_guarda_uma_copia():
    col = ColeccaoFalsa([{"id": "r1", "paragens": []}])
    paragem = {"id": "p1", "janelas": [{"inicio": "10:00"}]}
    correr(col.update_one({"id": "r1"}, {"$push": {"paragens": paragem}}))
    paragem["janelas"][0]["inicio"] = "mudado"
    assert col.docs[0]["paragens"] == [{"id": "p1", "janelas": [{"inicio": "10:00"}]}]


@pytest.mark.parametrize("valor", ["x", None, {"id": "p1"}, 3], ids=["texto", "null", "dicionário", "número"])
def test_push_num_campo_que_nao_e_lista_e_recusado_como_no_mongo(valor):
    col = ColeccaoFalsa([{"id": "r1", "paragens": valor}])
    with pytest.raises(OperationFailure) as excinfo:
        correr(col.find_one_and_update({"id": "r1"}, {"$push": {"paragens": {"id": "p2"}}}))
    assert excinfo.value.code == 2
    assert col.sem_id() == [{"id": "r1", "paragens": valor}]


def test_push_com_modificadores_nao_esta_modelado():
    col = ColeccaoFalsa([{"id": "r1", "paragens": []}])
    with pytest.raises(NotImplementedError):
        correr(col.update_one({"id": "r1"}, {"$push": {"paragens": {"$each": [{"id": "p1"}]}}}))
    assert col.sem_id() == [{"id": "r1", "paragens": []}]


# O conflito de caminhos (código 40 do Mongo)


def test_push_e_set_por_indice_no_mesmo_caminho_dao_o_conflito_40_do_mongo():
    col = _rota()
    atualizacao = {"$push": {"paragens": {"id": "p3"}}, "$set": {"paragens.0.ordem": 1}}
    with pytest.raises(OperationFailure) as excinfo:
        correr(col.update_one({"id": "r1"}, atualizacao))
    assert excinfo.value.code == 40
    assert str(excinfo.value).startswith(
        "Updating the path 'paragens.0.ordem' would create a conflict at 'paragens'"
    )
    assert _guardada(col) == ROTA
    # O Mongo lê a atualização antes de procurar o documento: rebenta mesmo sem nenhum coincidir.
    with pytest.raises(OperationFailure) as excinfo:
        correr(col.find_one_and_update({"id": "nada"}, atualizacao))
    assert excinfo.value.code == 40


@pytest.mark.parametrize("atualizacao, caminho, em", [
    ({"$set": {"versao": 1}, "$inc": {"versao": 1}}, "versao", "versao"),
    ({"$set": {"calculo": None, "calculo.atual": True}}, "calculo.atual", "calculo"),
    ({"$inc": {"paragens.0.n": 1}, "$push": {"paragens": {}}}, "paragens.0.n", "paragens"),
    ({"$set": {"paragens.0.ordem": 1}, "$inc": {"paragens.0.ordem": 1}}, "paragens.0.ordem", "paragens.0.ordem"),
], ids=["set e inc no mesmo campo", "o pai e o filho no mesmo set", "inc por índice e push", "set e inc por índice"])
def test_dois_caminhos_em_que_um_e_prefixo_do_outro_dao_o_conflito_40(atualizacao, caminho, em):
    col = _rota()
    with pytest.raises(OperationFailure) as excinfo:
        correr(col.update_one({"id": "r1"}, atualizacao))
    assert excinfo.value.code == 40
    assert str(excinfo.value).startswith("Updating the path '%s' would create a conflict at '%s'" % (caminho, em))
    assert _guardada(col) == ROTA


def test_caminhos_irmaos_ou_so_com_o_mesmo_prefixo_de_texto_nao_dao_conflito():
    col = _rota()
    correr(col.update_one(
        {"id": "r1"},
        {"$set": {"paragens.0.ordem": 1, "paragens.1.ordem": 0, "paragensx": 1, "calculo": {"atual": True}}, "$inc": {"versao": 1}},
    ))
    guardada = _guardada(col)
    assert [p["ordem"] for p in guardada["paragens"]] == [1, 0]
    assert (guardada["paragensx"], guardada["calculo"], guardada["versao"]) == (1, {"atual": True}, 4)


# Filtros: comparações e caminhos através de listas


DOCS_ROTAS = [
    {"id": "a", "data": "2026-10-10", "versao": 1, "paragens": [
        {"loja_id": "l1", "estado": "pendente", "ordem": 0}, {"loja_id": "l2", "estado": "feita", "ordem": 1},
    ]},
    {"id": "b", "data": "2026-10-12", "versao": 2.5, "paragens": [
        {"loja_id": "l2", "estado": "pendente", "ordem": 0}, {"loja_id": "l3", "ordem": 1},
    ]},
    {"id": "c", "data": "2026-10-20", "versao": "3", "paragens": []},
    {"id": "d", "data": "2026-09-01", "versao": True},
]


def _ids_rotas(filtro):
    col = ColeccaoFalsa(DOCS_ROTAS, unicos=("id", "data"))
    return [d["id"] for d in correr(col.find(filtro).to_list(100))]


@pytest.mark.parametrize(
    "filtro, esperado",
    [
        ({"versao": {"$gt": 1}}, ["b"]),
        ({"versao": {"$gte": 1}}, ["a", "b"]),
        ({"versao": {"$lt": 2}}, ["a"]),
        ({"versao": {"$lte": 2.5}}, ["a", "b"]),
        ({"versao": {"$gt": "2"}}, ["c"]),
        ({"versao": {"$gte": "3"}}, ["c"]),
        ({"data": {"$gte": "2026-10-10", "$lte": "2026-10-12"}}, ["a", "b"]),
        ({"data": {"$lt": "2026-10-10"}}, ["d"]),
        ({"paragens.loja_id": "l2"}, ["a", "b"]),
        ({"paragens.loja_id": {"$in": ["l3", "l9"]}}, ["b"]),
        ({"paragens.loja_id": {"$ne": "l1"}}, ["b", "c", "d"]),
        ({"paragens.estado": {"$nin": ["feita", "nao_feita"]}}, ["b", "c", "d"]),
        ({"paragens.estado": "feita"}, ["a"]),
        ({"paragens.estado": None}, ["b", "c", "d"]),
        ({"paragens.estado": {"$exists": True}}, ["a", "b"]),
        ({"paragens.estado": {"$exists": False}}, ["c", "d"]),
        ({"paragens.ordem": {"$gt": 0}}, ["a", "b"]),
        ({"paragens.1.estado": "feita"}, ["a"]),
        ({"paragens.1.estado": None}, ["b", "c", "d"]),
        ({"paragens.0.loja_id": {"$in": ["l1", "l2"]}}, ["a", "b"]),
        ({"paragens.5.estado": {"$exists": True}}, []),
        ({"paragens.0.ordem": {"$lte": 0}}, ["a", "b"]),
        ({"id": "a", "versao": 1, "paragens.estado": {"$nin": ["feita", "nao_feita"]}}, []),
        ({"id": "b", "versao": 2.5, "paragens.estado": {"$nin": ["feita", "nao_feita"]}}, ["b"]),
    ],
    ids=[
        "gt-numero", "gte-numero", "lt-numero", "lte-numero", "gt-texto", "gte-texto", "intervalo-de-datas",
        "lt-data", "algum-elemento", "in-algum-elemento", "ne-nenhum-elemento", "nin-nenhum-elemento",
        "igualdade-algum-elemento", "null-elemento-sem-campo-lista-vazia-ou-sem-lista", "exists-algum-elemento",
        "exists-false", "gt-algum-elemento", "indice-no-filtro", "indice-em-falta-e-null", "indice-com-in",
        "indice-fora-do-fim", "indice-com-lte", "escrita-do-escritorio-recusada", "escrita-do-escritorio-aceite",
    ],
)
def test_filtros_com_comparacoes_e_caminhos_atraves_de_listas(filtro, esperado):
    assert _ids_rotas(filtro) == esperado


@pytest.mark.parametrize("argumento", [None, True, [1], {"a": 1}], ids=["null", "booleano", "lista", "dicionário"])
def test_comparacao_com_argumento_que_nao_e_numero_nem_texto_nao_esta_modelada(argumento):
    col = ColeccaoFalsa([{"id": "a", "n": 1}])
    with pytest.raises(NotImplementedError):
        correr(col.find_one({"n": {"$gt": argumento}}))


# find_one_and_update com todos os operadores e a escrita condicional do escritório


def test_find_one_and_update_aplica_set_por_indice_inc_e_push_juntos():
    col = _rota()
    depois = correr(col.find_one_and_update(
        FILTRO_DO_ESCRITORIO,
        {"$set": {"paragens.0.ordem": 1, "paragens.1.ordem": 0, "atualizado_em": "x"}, "$inc": {"versao": 1}},
        projection={"_id": 0},
        return_document=ReturnDocument.AFTER,
    ))
    assert depois["versao"] == 4
    assert [p["ordem"] for p in depois["paragens"]] == [1, 0]
    assert depois["atualizado_em"] == "x"
    depois = correr(col.find_one_and_update(
        {**FILTRO_DO_ESCRITORIO, "versao": 4},
        {"$push": {"paragens": {"id": "p3", "loja_id": "l3", "ordem": 2, "estado": "pendente"}}, "$inc": {"versao": 1}},
        projection={"_id": 0},
        return_document=ReturnDocument.AFTER,
    ))
    assert depois["versao"] == 5
    assert [p["id"] for p in depois["paragens"]] == ["p1", "p2", "p3"]
    assert _guardada(col) == depois


def test_a_escrita_condicional_do_escritorio_nao_passa_com_uma_paragem_feita_nem_com_outra_versao():
    com_registo = copy.deepcopy(ROTA)
    com_registo["paragens"][1]["estado"] = "feita"
    col = ColeccaoFalsa([com_registo], unicos=("id", "data"))
    assert correr(col.find_one_and_update(FILTRO_DO_ESCRITORIO, {"$inc": {"versao": 1}})) is None
    assert col.sem_id() == [com_registo]
    col = _rota()
    assert correr(col.find_one_and_update({**FILTRO_DO_ESCRITORIO, "versao": 2}, {"$inc": {"versao": 1}})) is None
    assert _guardada(col) == ROTA


# O gancho antes_de: a escrita concorrente do motorista (F4) entre a leitura e a escrita


def test_antes_de_corre_o_gancho_antes_da_operacao_sobre_os_proprios_documentos():
    col = _rota()
    chamadas = []

    def motorista(docs):
        chamadas.append(len(docs))
        docs[0]["paragens"][1]["estado"] = "feita"

    col.antes_de("find_one_and_update", motorista)
    assert correr(col.find_one_and_update(FILTRO_DO_ESCRITORIO, {"$inc": {"versao": 1}})) is None
    assert chamadas == [1]
    assert col.docs[0]["paragens"][1]["estado"] == "feita"
    assert col.docs[0]["versao"] == 3
    assert [c[0] for c in col.registo] == ["find_one_and_update"]


def test_antes_de_corre_em_cada_chamada_ate_ser_retirado():
    col = ColeccaoFalsa([{"id": "r1", "versao": 1}])
    col.antes_de("find_one_and_update", lambda docs: docs[0].__setitem__("versao", docs[0]["versao"] + 1))
    for esperado in (2, 3):
        depois = correr(col.find_one_and_update(
            {"id": "r1"}, {"$inc": {"tentativas": 1}}, return_document=ReturnDocument.AFTER
        ))
        assert depois["versao"] == esperado
    col.antes_de("find_one_and_update", None)
    depois = correr(col.find_one_and_update({"id": "r1"}, {"$inc": {"tentativas": 1}}, return_document=ReturnDocument.AFTER))
    assert (depois["versao"], depois["tentativas"]) == (3, 3)


def test_antes_de_no_find_corre_no_to_list_e_nao_ao_chamar_o_find():
    col = ColeccaoFalsa([{"id": "a"}])
    col.antes_de("find", lambda docs: docs.append({"id": "b", "_id": ObjectId()}))
    cursor = col.find({})
    assert col.sem_id() == [{"id": "a"}]
    assert [d["id"] for d in correr(cursor.to_list(10))] == ["a", "b"]


def test_antes_de_so_para_a_operacao_indicada_e_corre_antes_da_falha_injetada():
    col = ColeccaoFalsa([{"id": "a"}], falhar={"insert_one": RuntimeError("em baixo")})
    visto = []
    col.antes_de("insert_one", lambda docs: visto.append("gancho"))
    with pytest.raises(RuntimeError):
        correr(col.insert_one({"id": "b"}))
    correr(col.find_one({"id": "a"}))
    correr(col.update_one({"id": "a"}, {"$set": {"x": 1}}))
    assert visto == ["gancho"]


def test_antes_de_com_operacao_desconhecida_e_um_erro_do_teste():
    with pytest.raises(ValueError):
        ColeccaoFalsa().antes_de("insert", lambda docs: None)
