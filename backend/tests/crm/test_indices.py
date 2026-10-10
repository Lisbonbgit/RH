"""As coleções e os índices do CRM são declarados como dados (crm/db.py) e
aplicados por criar_indices — testáveis sem Mongo.

Molde: tests/faturacao/test_indices.py. As coleções entram em COLECOES com a
tarefa que as usa (correções do plano, T1.2/T2.8): a F1 trouxe crm_membros e
a T2.8 as quatro da F2, com os índices do plano §3.

Cada coleção tem a lista EXATA dos seus índices: um índice a mais também é um
erro (ex.: `regiao_id` único deixava uma só loja por região; `client_uuid`
único sem ser parcial fazia colidir as interações sem ele).
"""
import logging

import pytest
from pymongo.errors import DuplicateKeyError

import crm.db
import seed_crm_local
from crm.db import COLECOES, INDICES, criar_indices

from .duplos import BaseFalsa, ColeccaoFalsa, correr


def _unicos_de_um_campo(indices, coleccao):
    return [
        chaves[0][0]
        for (c, chaves, opcoes) in indices
        if c == coleccao and opcoes.get("unique") and len(chaves) == 1
    ]


def _problemas_de_unicidade(colecoes, indices):
    """A regra de unicidade de todas as coleções do CRM, numa função só para
    poder ser provada com declarações falsas (ver os testes "a regra apanha").

    - toda a coleção tem `id` único, EXCETO crm_definicoes;
    - crm_definicoes tem `chave` único e NÃO tem índice nenhum em `id`: os
      documentos são {chave, valor, …}, sem `id`, e no Mongo real um campo em
      falta entra num índice único como null — o segundo upsert (fabrica_lat e
      fabrica_lng gravam-se juntos) dava E11000.
    """
    problemas = []
    for nome in colecoes.values():
        unicos = _unicos_de_um_campo(indices, nome)
        if nome == "crm_definicoes":
            if "chave" not in unicos:
                problemas.append((nome, "falta chave único"))
            if any(campo == "id" for (c, chaves, _o) in indices if c == nome for campo, _d in chaves):
                problemas.append((nome, "não pode ter índice em id"))
        elif "id" not in unicos:
            problemas.append((nome, "falta id único"))
    return problemas


# --- Declarações ------------------------------------------------------------------


def _indices_de(coleccao):
    return [(list(chaves), dict(opcoes)) for (c, chaves, opcoes) in INDICES if c == coleccao]


UNICO = {"unique": True}


def test_as_colecoes_da_f1_e_da_f2():
    assert COLECOES == {
        "membros": "crm_membros",
        "regioes": "crm_regioes",
        "lojas": "crm_lojas",
        "interacoes": "crm_interacoes",
        "definicoes": "crm_definicoes",
    }


def test_crm_membros_tem_id_unico_e_user_id_unico():
    unicos = _unicos_de_um_campo(INDICES, "crm_membros")
    assert "id" in unicos
    assert "user_id" in unicos
    assert _indices_de("crm_membros") == [([("id", 1)], UNICO), ([("user_id", 1)], UNICO)]


def test_crm_regioes_tem_id_unico_e_nome_chave_unico():
    """`nome_chave` (sem maiúsculas nem acentos) único: "setubal" e "Setúbal"
    são a mesma região, sem precisar de collation do Mongo (plano §1)."""
    assert _indices_de("crm_regioes") == [([("id", 1)], UNICO), ([("nome_chave", 1)], UNICO)]


def test_crm_lojas_tem_id_unico_loc_2dsphere_e_regiao_id_sem_ser_unico():
    """`loc` 2dsphere para o pré-filtro dos duplicados ($geoWithin, T2.3);
    `regiao_id` para o "esta região tem lojas?" do DELETE — nunca único (há
    muitas lojas por região e muitas sem região)."""
    assert _indices_de("crm_lojas") == [
        ([("id", 1)], UNICO),
        ([("loc", "2dsphere")], {}),
        ([("regiao_id", 1)], {}),
    ]


def test_crm_interacoes_tem_a_linha_do_tempo_e_client_uuid_unico_so_quando_e_texto():
    """(loja_id, ocorrida_em) é a linha do tempo de cada loja (o
    ix_interacoes_loja do autónomo). `client_uuid` é único só quando é texto:
    um índice único normal (ou `sparse`, que indexa o null) fazia colidir as
    interações sem ele — todas as da F2 (o registo sem rede só chega na F4)."""
    assert _indices_de("crm_interacoes") == [
        ([("id", 1)], UNICO),
        ([("loja_id", 1), ("ocorrida_em", 1)], {}),
        ([("client_uuid", 1)], {"unique": True, "partialFilterExpression": {"client_uuid": {"$type": "string"}}}),
    ]


def test_crm_definicoes_tem_so_chave_unico():
    assert _indices_de("crm_definicoes") == [([("chave", 1)], UNICO)]


def test_toda_a_colecao_declarada_tem_indices():
    assert set(COLECOES.values()) <= {c for (c, _k, _o) in INDICES}


def test_todas_as_colecoes_cumprem_a_regra_de_unicidade():
    assert _problemas_de_unicidade(COLECOES, INDICES) == []


def test_crm_definicoes_nunca_tem_indice_em_id():
    """Asserção explícita (correções do plano, T1.2/T2.8): crm_definicoes já
    está declarada (T2.8) e não pode ter índice nenhum em `id`."""
    em_id = [
        (chaves, opcoes)
        for (c, chaves, opcoes) in INDICES
        if c == "crm_definicoes" and any(campo == "id" for campo, _d in chaves)
    ]
    assert em_id == []


def test_a_regra_apanha_colecao_sem_id_unico():
    colecoes = {"membros": "crm_membros", "lojas": "crm_lojas"}
    indices = [("crm_membros", [("id", 1)], {"unique": True}), ("crm_lojas", [("id", 1)], {})]
    assert _problemas_de_unicidade(colecoes, indices) == [("crm_lojas", "falta id único")]


def test_a_regra_apanha_crm_definicoes_com_id_ou_sem_chave():
    colecoes = {"definicoes": "crm_definicoes"}
    com_id = [("crm_definicoes", [("chave", 1)], {"unique": True}), ("crm_definicoes", [("id", 1)], {"unique": True})]
    assert _problemas_de_unicidade(colecoes, com_id) == [("crm_definicoes", "não pode ter índice em id")]
    sem_chave = [("crm_definicoes", [("chave", 1)], {})]
    assert _problemas_de_unicidade(colecoes, sem_chave) == [("crm_definicoes", "falta chave único")]
    certo = [("crm_definicoes", [("chave", 1)], {"unique": True})]
    assert _problemas_de_unicidade(colecoes, certo) == []


def test_os_indices_so_falam_de_colecoes_declaradas():
    assert {c for (c, _k, _o) in INDICES} <= set(COLECOES.values())


def test_todas_as_colecoes_tem_o_prefixo_crm():
    assert all(nome.startswith("crm_") for nome in COLECOES.values())


def test_o_seed_local_usa_a_mesma_colecao_de_membros():
    """O seed (T0.7) fixou o nome antes de crm.db existir; daqui em diante os
    dois não podem divergir (correções do plano, linha da T0.7)."""
    assert seed_crm_local.COLECAO_MEMBROS == COLECOES["membros"]


# --- O duplo do Mongo impõe os mesmos únicos ---------------------------------------
# (tests/crm/duplos.py lê-os de INDICES; os parciais não são modelados — o
# ensaio no Mongo local, T2.17, prova-os a sério.)


def test_no_duplo_duas_regioes_com_o_mesmo_nome_chave_colidem():
    base = BaseFalsa()
    correr(base.crm_regioes.insert_one({"id": "r1", "nome": "Setúbal", "nome_chave": "setubal", "ordem": 0}))
    with pytest.raises(DuplicateKeyError):
        correr(base.crm_regioes.insert_one({"id": "r2", "nome": "setubal", "nome_chave": "setubal", "ordem": 1}))


def test_no_duplo_ha_muitas_lojas_na_mesma_regiao_e_sem_regiao():
    base = BaseFalsa()
    for i, regiao in enumerate(["r1", "r1", None, None]):
        correr(base.crm_lojas.insert_one({"id": "l%d" % i, "regiao_id": regiao}))
    assert len(base.crm_lojas.docs) == 4


def test_no_duplo_duas_interacoes_sem_client_uuid_nao_colidem():
    base = BaseFalsa()
    correr(base.crm_interacoes.insert_one({"id": "i1", "loja_id": "l1", "tipo": "mudanca_fase"}))
    correr(base.crm_interacoes.insert_one({"id": "i2", "loja_id": "l1", "tipo": "mudanca_fase"}))
    assert len(base.crm_interacoes.docs) == 2


def test_no_duplo_dois_upserts_de_definicoes_seguidos_nao_colidem():
    """A armadilha da correção T1.2/T2.8: fabrica_lat e fabrica_lng gravam-se
    juntas; com `id` único (os documentos não têm `id`) a segunda dava E11000."""
    base = BaseFalsa()
    for chave, valor in (("fabrica_lat", "38.700000"), ("fabrica_lng", "-9.100000")):
        correr(base.crm_definicoes.update_one({"chave": chave}, {"$set": {"valor": valor}}, upsert=True))
    assert sorted(d["chave"] for d in base.crm_definicoes.docs) == ["fabrica_lat", "fabrica_lng"]
    with pytest.raises(DuplicateKeyError):
        correr(base.crm_definicoes.insert_one({"chave": "fabrica_lat", "valor": "0"}))


# --- obter_db: um só conjunto de ligações -------------------------------------------


def test_obter_db_devolve_a_base_da_faturacao(monkeypatch):
    import faturacao.db

    base = object()
    monkeypatch.setattr(faturacao.db, "obter_db", lambda: base)
    assert crm.db.obter_db() is base


# --- criar_indices -------------------------------------------------------------------


def test_criar_indices_cria_todos_os_declarados_por_ordem():
    base = BaseFalsa()
    correr(criar_indices(base))
    criados = [
        (nome, chamada[1], chamada[2])
        for nome in sorted({c for (c, _k, _o) in INDICES})
        for chamada in base[nome].chamadas("create_index")
    ]
    assert sorted(criados, key=repr) == sorted(
        [(c, list(k), dict(o)) for (c, k, o) in INDICES], key=repr
    )
    assert base.crm_membros.chamadas("create_index") == [
        ("create_index", list(k), dict(o)) for (c, k, o) in INDICES if c == "crm_membros"
    ]


def test_uma_falha_num_indice_nao_impede_os_seguintes(monkeypatch, caplog):
    rebentada = ColeccaoFalsa(falhar={"create_index": RuntimeError("dados antigos repetidos")})
    base = BaseFalsa({"crm_rebenta": rebentada})
    monkeypatch.setattr(crm.db, "INDICES", [("crm_rebenta", [("id", 1)], {"unique": True})] + list(INDICES))

    with caplog.at_level(logging.ERROR, logger="crm"):
        correr(criar_indices(base))  # não pode levantar

    assert len(rebentada.chamadas("create_index")) == 1
    assert len(base.crm_membros.chamadas("create_index")) == len(
        [1 for (c, _k, _o) in INDICES if c == "crm_membros"]
    )
    erros = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(erros) == 1
    assert erros[0].startswith("[crm]")
    assert "crm_rebenta" in erros[0]
