"""As coleções e os índices do CRM são declarados como dados (crm/db.py) e
aplicados por criar_indices — testáveis sem Mongo.

Molde: tests/faturacao/test_indices.py. As coleções entram em COLECOES uma a
uma, com a tarefa que as usa (correções do plano, T1.2/T2.8): na F1 só existe
crm_membros.
"""
import logging

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


def test_na_f1_so_existe_a_colecao_dos_membros():
    assert COLECOES == {"membros": "crm_membros"}


def test_crm_membros_tem_id_unico_e_user_id_unico():
    unicos = _unicos_de_um_campo(INDICES, "crm_membros")
    assert "id" in unicos
    assert "user_id" in unicos


def test_todas_as_colecoes_cumprem_a_regra_de_unicidade():
    assert _problemas_de_unicidade(COLECOES, INDICES) == []


def test_crm_definicoes_nunca_tem_indice_em_id():
    """Asserção explícita (correções do plano, T1.2): vale já hoje e continua a
    valer quando a F2 acrescentar crm_definicoes."""
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
