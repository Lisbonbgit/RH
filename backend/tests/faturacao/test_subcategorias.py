"""**Subcategorias: as gavetas dentro de cada categoria.**

Pedido do dono: «backoffice → gestão → produtos → categorias → dentro do Venda
ao Público quero criar uma subcategoria». São só nossas — o Vendus não tem este
nível — e servem para arrumar a grelha do POS: não entram na fatura, no IVA nem
nos relatórios.

O que se guarda aqui são as regras que fazem um produto DESAPARECER do ecrã se
ninguém as impuser: a grelha mostra as subcategorias da categoria que está à
frente, por isso um produto com a subcategoria de OUTRA categoria não cabe em
lado nenhum. Recusa-se nos dois sítios por onde isso podia entrar — ao gravar o
produto, e ao mudar a subcategoria de categoria.
"""
import pytest
from fastapi import HTTPException

from faturacao import catalogo as catalogo_mod
from faturacao.catalogo import (
    ProdutoEntrada, SubcategoriaEntrada, _valida_referencias, apagar_subcategoria,
    criar_subcategoria, editar_subcategoria,
)

from .test_catalogo import ColeccaoFalsa, DbFalsa, _corre


def _db(monkeypatch, **colecoes):
    db = DbFalsa(colecoes)
    monkeypatch.setattr(catalogo_mod, "obter_db", lambda: db)
    return db


def test_criar_dentro_de_uma_categoria_que_existe(monkeypatch):
    registo = []
    _db(monkeypatch,
        fat_categorias=ColeccaoFalsa(registo, find_one_devolve={"id": "cat-1"}),
        fat_subcategorias=ColeccaoFalsa(registo))

    sub = _corre(criar_subcategoria(
        SubcategoriaEntrada(nome="Açaís", categoria_id="cat-1", ordem=1), _={}))

    assert sub["nome"] == "Açaís" and sub["categoria_id"] == "cat-1"
    assert sub["id"] and sub["ativa"] is True


def test_criar_numa_categoria_que_nao_existe_e_recusado(monkeypatch):
    registo = []
    _db(monkeypatch,
        fat_categorias=ColeccaoFalsa(registo, find_one_devolve=None),
        fat_subcategorias=ColeccaoFalsa(registo))

    with pytest.raises(HTTPException) as e:
        _corre(criar_subcategoria(
            SubcategoriaEntrada(nome="Açaís", categoria_id="nao-existe"), _={}))
    assert e.value.status_code == 422
    assert not [c for c in registo if c[0] == "insert_one"]


def test_mudar_de_categoria_uma_subcategoria_COM_produtos_e_recusado(monkeypatch):
    """Os produtos dela ficariam com a subcategoria de outra categoria — e um
    produto assim não aparece em separador nenhum da grelha. Some do ecrã com
    o artigo à venda na loja."""
    registo = []
    _db(monkeypatch,
        fat_categorias=ColeccaoFalsa(registo, find_one_devolve={"id": "cat-2"}),
        fat_subcategorias=ColeccaoFalsa(
            registo, find_one_devolve={"id": "sub-1", "categoria_id": "cat-1"}),
        fat_produtos=ColeccaoFalsa(registo, count_documents_devolve=3))

    with pytest.raises(HTTPException) as e:
        _corre(editar_subcategoria(
            "sub-1", SubcategoriaEntrada(nome="Açaís", categoria_id="cat-2"), _={}))
    assert e.value.status_code == 409
    assert "3 produto" in e.value.detail
    assert not [c for c in registo if c[0] == "update_one"]


def test_renomear_sem_mudar_de_categoria_passa(monkeypatch):
    registo = []
    _db(monkeypatch,
        fat_categorias=ColeccaoFalsa(registo, find_one_devolve={"id": "cat-1"}),
        fat_subcategorias=ColeccaoFalsa(
            registo, find_one_devolve={"id": "sub-1", "categoria_id": "cat-1"}),
        fat_produtos=ColeccaoFalsa(registo, count_documents_devolve=3))

    _corre(editar_subcategoria(
        "sub-1", SubcategoriaEntrada(nome="Açaís e Taças", categoria_id="cat-1"), _={}))

    assert [c for c in registo if c[0] == "update_one"]


def test_apagar_solta_os_produtos_em_vez_de_os_prender(monkeypatch):
    """Ao contrário do apagar uma CATEGORIA (que recusa enquanto tiver
    produtos, para não os deixar órfãos), apagar uma subcategoria não deixa
    ninguém órfão: o campo limpa-se e os produtos voltam a aparecer na grelha,
    em «Outros»."""
    registo = []
    _db(monkeypatch,
        fat_subcategorias=ColeccaoFalsa(registo, delete_one_devolve=1),
        fat_produtos=ColeccaoFalsa(registo))

    r = _corre(apagar_subcategoria("sub-1", _={}))

    assert r["apagada"] is True
    limpezas = [c for c in registo if c[0] == "update_many"]
    assert limpezas, "os produtos têm de ficar sem subcategoria: %s" % registo


def test_apagar_uma_que_nao_existe_da_404(monkeypatch):
    registo = []
    _db(monkeypatch,
        fat_subcategorias=ColeccaoFalsa(registo, delete_one_devolve=0),
        fat_produtos=ColeccaoFalsa(registo))
    with pytest.raises(HTTPException) as e:
        _corre(apagar_subcategoria("sub-1", _={}))
    assert e.value.status_code == 404


# --- E a mesma regra no produto ----------------------------------------------


def test_um_produto_nao_se_grava_com_a_subcategoria_de_OUTRA_categoria(monkeypatch):
    registo = []
    db = _db(monkeypatch,
             fat_categorias=ColeccaoFalsa(registo, find_one_devolve={"id": "cat-1"}),
             fat_subcategorias=ColeccaoFalsa(
                 registo, find_one_devolve={"id": "sub-1", "categoria_id": "cat-OUTRA",
                                            "nome": "Bebidas"}))

    with pytest.raises(HTTPException) as e:
        _corre(_valida_referencias(db, "cat-1", [], "sub-1"))
    assert e.value.status_code == 422
    assert "outra categoria" in e.value.detail


def test_um_produto_sem_subcategoria_e_perfeitamente_valido(monkeypatch):
    registo = []
    db = _db(monkeypatch,
             fat_categorias=ColeccaoFalsa(registo, find_one_devolve={"id": "cat-1"}))
    _corre(_valida_referencias(db, "cat-1", [], None))
    assert ProdutoEntrada(
        nome="Água", categoria_id="cat-1", preco=1.0, tax_id="NOR"
    ).subcategoria_id is None
