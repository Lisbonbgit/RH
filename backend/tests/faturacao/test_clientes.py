"""**Os clientes que pedem fatura com NIF.**

«Nada mais é do que salvar os clientes que pedirem fatura com NIF», nas
palavras do dono — e a decisão que isso obriga a tomar é: **um cliente nasce de
uma compra**, nunca de um formulário. A lista deriva dos documentos; a ficha
guarda só o que eles não sabem (nome, contacto).

O que se guarda aqui é o que separa uma lista de clientes de uma agenda:

1. quem nunca comprou não entra, nem sequer por um `PUT` — senão o ecrã enchia-
   se de gente que nunca cá pôs os pés e a pergunta «quanto gastou este
   cliente?» deixava de ter resposta;
2. a nota de crédito SUBTRAI no que ele gastou, e conta à parte;
3. o NIF é a chave e não se edita: trocá-lo era passar as compras de uma
   pessoa para outra.
"""
import pytest
from fastapi import HTTPException

from faturacao import clientes as clientes_mod
from faturacao.clientes import ClienteEntrada, gravar_cliente, listar_clientes, obter_cliente
from faturacao.db import COLECOES

from .test_venda import ColeccaoFalsa, DbFalsa, _corre


def _doc(nif, total, quando, tipo="FS"):
    return {"id": "d-%s-%s" % (nif, quando), "cliente_nif": nif, "total": total,
            "tipo": tipo, "emitido_em": quando, "loja_id": "loja-1"}


def _db(monkeypatch, documentos, fichas=None):
    registo = []
    db = DbFalsa({
        COLECOES["documentos"]: ColeccaoFalsa(registo, documentos),
        COLECOES["clientes"]: ColeccaoFalsa(registo, fichas or []),
    })
    monkeypatch.setattr(clientes_mod, "obter_db", lambda: db)
    return db


def test_a_lista_sao_os_NIFs_que_compraram_do_maior_para_o_menor(monkeypatch):
    _db(monkeypatch, [
        _doc("517542510", 10.20, "2026-08-10T12:00:00+00:00"),
        _doc("517542510", 5.00, "2026-08-11T12:00:00+00:00"),
        _doc("123456789", 40.00, "2026-08-09T12:00:00+00:00"),
        # Consumidor Final não é cliente nenhum: não tem NIF e não entra.
        {"id": "d9", "cliente_nif": None, "total": 99.0, "tipo": "FS",
         "emitido_em": "2026-08-12T12:00:00+00:00"},
    ])

    r = _corre(listar_clientes(_={}))

    assert [c["nif"] for c in r["clientes"]] == ["123456789", "517542510"]
    assert r["clientes"][1]["total"] == 15.20
    assert r["clientes"][1]["faturas"] == 2
    assert r["clientes"][1]["ultima_compra_em"] == "2026-08-11T12:00:00+00:00"
    assert r["truncado"] is False


def test_a_nota_de_credito_SUBTRAI_ao_que_o_cliente_gastou(monkeypatch):
    _db(monkeypatch, [
        _doc("517542510", 10.20, "2026-08-10T12:00:00+00:00"),
        _doc("517542510", 1.15, "2026-08-10T13:00:00+00:00", tipo="NC"),
    ])

    r = _corre(listar_clientes(_={}))

    assert r["clientes"][0]["total"] == 9.05
    assert r["clientes"][0]["faturas"] == 1
    assert r["clientes"][0]["notas_credito"] == 1


def test_a_ficha_junta_o_nome_ao_NIF(monkeypatch):
    _db(monkeypatch,
        [_doc("517542510", 10.20, "2026-08-10T12:00:00+00:00")],
        fichas=[{"nif": "517542510", "nome": "Fordaimon Foods", "email": None,
                 "telefone": None, "notas": None}])

    r = _corre(listar_clientes(_={}))
    assert r["clientes"][0]["nome"] == "Fordaimon Foods"


def test_a_pesquisa_encontra_por_NIF_ou_por_NOME(monkeypatch):
    _db(monkeypatch, [
        _doc("517542510", 10.20, "2026-08-10T12:00:00+00:00"),
        _doc("123456789", 40.00, "2026-08-09T12:00:00+00:00"),
    ], fichas=[{"nif": "123456789", "nome": "Padaria do Bairro"}])

    por_nif = _corre(listar_clientes(q="5175", _={}))
    assert [c["nif"] for c in por_nif["clientes"]] == ["517542510"]

    por_nome = _corre(listar_clientes(q="padaria", _={}))
    assert [c["nif"] for c in por_nome["clientes"]] == ["123456789"]


def test_gravar_o_nome_de_quem_JA_COMPROU(monkeypatch):
    db = _db(monkeypatch, [_doc("517542510", 10.20, "2026-08-10T12:00:00+00:00")])

    r = _corre(gravar_cliente(
        "517542510", ClienteEntrada(nome="Fordaimon Foods", email="geral@exemplo.pt"), _={}))

    assert r["nome"] == "Fordaimon Foods"
    assert r["total"] == 10.20
    assert db._coleccoes[COLECOES["clientes"]]._documentos[0]["nif"] == "517542510"


def test_NAO_se_grava_um_cliente_que_nunca_comprou(monkeypatch):
    """Um `upsert` livre transformava isto numa agenda de contactos com gente
    que nunca cá entrou — e a lista deixava de responder à pergunta para que
    existe."""
    db = _db(monkeypatch, [_doc("517542510", 10.20, "2026-08-10T12:00:00+00:00")])

    with pytest.raises(HTTPException) as e:
        _corre(gravar_cliente("999999999", ClienteEntrada(nome="Inventado"), _={}))
    assert e.value.status_code == 404
    assert db._coleccoes[COLECOES["clientes"]]._documentos == []


def test_um_NIF_que_nunca_comprou_da_404(monkeypatch):
    _db(monkeypatch, [_doc("517542510", 10.20, "2026-08-10T12:00:00+00:00")])
    with pytest.raises(HTTPException) as e:
        _corre(obter_cliente("999999999", _={}))
    assert e.value.status_code == 404


def test_o_NIF_nao_e_um_campo_da_ficha(monkeypatch):
    """A chave vem no caminho. Se fosse editável, mudá-la passava as compras de
    uma pessoa para outra sem ninguém ver."""
    assert "nif" not in ClienteEntrada.model_fields
