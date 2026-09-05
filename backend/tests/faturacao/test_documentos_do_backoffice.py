"""**O ecrã de Documentos do backoffice** — as faturas de todas as lojas.

Até aqui só o POS lia `fat_documentos`, e lia à sua maneira: a loja do TOKEN,
sem filtros, com um tecto pequeno. É a pergunta do balcão («onde está a fatura
daquele cliente?»). A do gestor é outra — «o que se emitiu, em que loja, naquele
intervalo?» — e por isso tem rotas próprias.

O que este ficheiro guarda:

1. **as datas são as de LISBOA**, e a venda das 00h30 tem de cair no dia certo;
2. **a nota de crédito SUBTRAI** no resumo — somá-la como positiva declara o
   dobro do que entrou;
3. a pesquisa encontra pelo número E pelo NIF (que nem sequer está no
   documento: está na venda), e um `(` escrito na caixa não rebenta a rota;
4. a paginação não mente: o total é do conjunto filtrado, não da página.
"""
import pytest
from fastapi import HTTPException

from faturacao import documentos as doc_mod
from faturacao.db import COLECOES
from faturacao.documentos import documento_do_backoffice, documentos_do_backoffice

from .test_venda import ColeccaoFalsa, DbFalsa, _corre


def _documento(id_, numero, total, emitido_em, loja_id="loja-1", tipo="FS", venda_id=None):
    return {
        "id": id_, "numero": numero, "total": total, "emitido_em": emitido_em,
        "loja_id": loja_id, "tipo": tipo, "venda_id": venda_id or ("v-" + id_),
        "atcud": "ATCUD-" + id_, "modo": "normal",
    }


def _venda(id_, cliente_nif=None):
    return {
        "id": id_, "loja_id": "loja-1", "caixa_id": "c1", "sessao_id": "s1",
        "operador_id": "op-1", "estado": "emitida", "cliente_nif": cliente_nif,
        "linhas": [], "criada_em": "2026-08-10T10:00:00+00:00",
    }


def _db(monkeypatch, documentos, vendas=None):
    registo = []
    db = DbFalsa({
        COLECOES["documentos"]: ColeccaoFalsa(registo, documentos),
        COLECOES["vendas"]: ColeccaoFalsa(registo, vendas or []),
    })
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)
    return db


# --- As datas -----------------------------------------------------------------


def test_o_intervalo_e_em_horas_de_LISBOA(monkeypatch):
    """Uma venda das 00h30 de Lisboa do dia 1 está gravada como 23h30 UTC do
    dia 31 — filtrar pela data em cru deixava-a fora do mês, e o dia 1
    aparecia sempre a menos. E a das 23h50 do dia 25 (22h50 UTC) tem de
    entrar: o `ate` é INCLUSIVO para quem escolhe."""
    _db(monkeypatch, [
        _documento("d1", "FS 1/1", 10.0, "2026-07-31T23:30:00+00:00"),   # 00h30 de 1/8
        _documento("d2", "FS 1/2", 20.0, "2026-08-25T22:50:00+00:00"),   # 23h50 de 25/8
        _documento("d3", "FS 1/3", 30.0, "2026-08-25T23:30:00+00:00"),   # 00h30 de 26/8
        _documento("d4", "FS 1/4", 40.0, "2026-07-31T22:30:00+00:00"),   # 23h30 de 31/7
    ])

    r = _corre(documentos_do_backoffice(de="2026-08-01", ate="2026-08-25", _={}))

    assert [d["numero"] for d in r["documentos"]] == ["FS 1/2", "FS 1/1"]
    assert r["total"] == 2


def test_uma_data_sozinha_e_recusada(monkeypatch):
    _db(monkeypatch, [])
    with pytest.raises(HTTPException) as e:
        _corre(documentos_do_backoffice(de="2026-08-01", _={}))
    assert e.value.status_code == 422


def test_datas_ao_contrario_sao_recusadas(monkeypatch):
    _db(monkeypatch, [])
    with pytest.raises(HTTPException) as e:
        _corre(documentos_do_backoffice(de="2026-08-25", ate="2026-08-01", _={}))
    assert e.value.status_code == 422


# --- O dinheiro ---------------------------------------------------------------


def test_a_nota_de_credito_SUBTRAI_no_resumo(monkeypatch):
    _db(monkeypatch, [
        _documento("d1", "FS 1/1", 10.20, "2026-08-10T12:00:00+00:00"),
        _documento("d2", "FS 1/2", 1.15, "2026-08-10T13:00:00+00:00"),
        _documento("d3", "NC 1/1", 1.15, "2026-08-10T14:00:00+00:00", tipo="NC"),
    ])

    r = _corre(documentos_do_backoffice(_={}))

    assert r["resumo"]["faturas"] == 2
    assert r["resumo"]["notas_credito"] == 1
    assert r["resumo"]["total"] == 10.20, (
        "a NC tem de subtrair: 10,20 + 1,15 − 1,15"
    )
    assert r["resumo"]["truncado"] is False


def test_o_resumo_e_do_conjunto_filtrado_e_nao_da_pagina(monkeypatch):
    """A pergunta é «quanto se faturou naquele intervalo», não «quanto vale
    esta página». Com 60 documentos e 50 por página, o resumo tem de somar os
    60."""
    _db(monkeypatch, [
        _documento("d%02d" % i, "FS 1/%d" % i, 1.00,
                   "2026-08-10T%02d:00:00+00:00" % (i % 24))
        for i in range(60)
    ])

    r = _corre(documentos_do_backoffice(_={}))

    assert len(r["documentos"]) == 50
    assert r["total"] == 60
    assert r["resumo"]["total"] == 60.0


def test_a_segunda_pagina_traz_os_que_faltam(monkeypatch):
    _db(monkeypatch, [
        _documento("d%02d" % i, "FS 1/%02d" % i, 1.00,
                   "2026-08-%02dT12:00:00+00:00" % (i + 1))
        for i in range(60)
    ])

    primeira = _corre(documentos_do_backoffice(pagina=1, _={}))
    segunda = _corre(documentos_do_backoffice(pagina=2, _={}))

    assert len(segunda["documentos"]) == 10
    assert not (
        {d["id"] for d in primeira["documentos"]}
        & {d["id"] for d in segunda["documentos"]}
    ), "as duas páginas não podem repetir documentos"


# --- Os filtros ---------------------------------------------------------------


def test_filtrar_por_loja_e_por_tipo(monkeypatch):
    _db(monkeypatch, [
        _documento("d1", "FS 1/1", 10.0, "2026-08-10T12:00:00+00:00", loja_id="loja-1"),
        _documento("d2", "FS 2/1", 20.0, "2026-08-10T13:00:00+00:00", loja_id="loja-2"),
        _documento("d3", "NC 1/1", 5.0, "2026-08-10T14:00:00+00:00", loja_id="loja-1", tipo="NC"),
    ])

    so_loja = _corre(documentos_do_backoffice(loja_id="loja-2", _={}))
    assert [d["numero"] for d in so_loja["documentos"]] == ["FS 2/1"]

    so_nc = _corre(documentos_do_backoffice(tipo="NC", _={}))
    assert [d["numero"] for d in so_nc["documentos"]] == ["NC 1/1"]


def test_um_tipo_desconhecido_e_recusado(monkeypatch):
    _db(monkeypatch, [])
    with pytest.raises(HTTPException) as e:
        _corre(documentos_do_backoffice(tipo="RECIBO", _={}))
    assert e.value.status_code == 422


def test_a_pesquisa_encontra_pelo_numero(monkeypatch):
    _db(monkeypatch, [
        _documento("d1", "FS 01P2026/17", 10.0, "2026-08-10T12:00:00+00:00"),
        _documento("d2", "FS 01P2026/18", 20.0, "2026-08-10T13:00:00+00:00"),
    ])

    r = _corre(documentos_do_backoffice(q="/17", _={}))
    assert [d["numero"] for d in r["documentos"]] == ["FS 01P2026/17"]


def test_a_pesquisa_encontra_pelo_NIF_que_esta_na_VENDA(monkeypatch):
    """O NIF não está no documento — está na venda. Sem ir lá buscá-lo, esta
    pesquisa não encontrava nunca a fatura de um cliente com NIF, que é
    precisamente quem volta a pedi-la."""
    _db(monkeypatch, [
        _documento("d1", "FS 1/1", 10.0, "2026-08-10T12:00:00+00:00", venda_id="v-com-nif"),
        _documento("d2", "FS 1/2", 20.0, "2026-08-10T13:00:00+00:00", venda_id="v-sem-nif"),
    ], vendas=[_venda("v-com-nif", cliente_nif="517542510"), _venda("v-sem-nif")])

    r = _corre(documentos_do_backoffice(q="517542510", _={}))
    assert [d["numero"] for d in r["documentos"]] == ["FS 1/1"]


def test_a_pesquisa_com_um_parentese_nao_rebenta(monkeypatch):
    """Um `(` escrito na caixa de pesquisa é um regex inválido: sem escapar, a
    rota respondia 500 a quem só estava a escrever."""
    _db(monkeypatch, [_documento("d1", "FS 1/1", 10.0, "2026-08-10T12:00:00+00:00")],
        vendas=[_venda("v-d1")])

    r = _corre(documentos_do_backoffice(q="(", _={}))
    assert r["documentos"] == []


# --- A fatura aberta ----------------------------------------------------------


def test_o_detalhe_e_o_MESMO_que_o_POS_mostra(monkeypatch):
    """Mesmo montador: `_detalhe_do_documento`. Duas montagens da mesma fatura
    acabam a dizer números diferentes."""
    _db(monkeypatch,
        [_documento("d1", "FS 1/1", 10.20, "2026-08-10T12:00:00+00:00", venda_id="v1")],
        vendas=[_venda("v1", cliente_nif="517542510")])

    r = _corre(documento_do_backoffice("d1", _={}))

    assert r["numero"] == "FS 1/1"
    assert r["total"] == 10.20
    assert r["cliente_nif"] == "517542510"
    assert r["tem_venda"] is True


def test_um_documento_que_nao_existe_da_404(monkeypatch):
    _db(monkeypatch, [])
    with pytest.raises(HTTPException) as e:
        _corre(documento_do_backoffice("nao-existe", _={}))
    assert e.value.status_code == 404


# --- O NIF de uma fatura da APP -----------------------------------------------

# Uma FS da app como `sincronizacao_app.documento_para_gravar` a grava: SEM
# venda nenhuma (`venda_id: None`) e com o NIF no PRÓPRIO documento. A FS
# 06P2026/446 real, lida em produção, traz um NIF verdadeiro — e as três
# leituras deste ecrã iam buscá-lo à venda, que aqui não existe.
def _da_app(id_="a1", numero="FS 06P2026/446", nif="244772903"):
    return {
        "id": id_, "numero": numero, "total": 6.85, "total_bruto": 6.85,
        "total_liquido": 6.06, "emitido_em": "2026-09-01T13:43:25+00:00",
        "loja_id": "loja-app", "tipo": "FS", "venda_id": None,
        "atcud": "J6SHGSNX-446", "modo": "normal", "origem": "app",
        "cliente_nif": nif,
        "linhas_vendus": [{"qty": 1, "title": "Açaí Mini",
                           "amounts": {"gross_total": "6.85",
                                       "net_total": "6.06"},
                           "tax": {"id": "INT", "rate": 13}}],
    }


def test_a_lista_mostra_o_NIF_QUE_ESTA_NO_DOCUMENTO(monkeypatch):
    """Medido a correr: a lista escrevia `cliente_nif: None` numa fatura que
    TEM NIF, e o ecrã pinta isso como «Consumidor Final»."""
    _db(monkeypatch, [_da_app()])
    r = _corre(documentos_do_backoffice(_={}))
    assert r["documentos"][0]["cliente_nif"] == "244772903"


def test_o_detalhe_mostra_o_NIF_QUE_ESTA_NO_DOCUMENTO(monkeypatch):
    _db(monkeypatch, [_da_app()])
    r = _corre(documento_do_backoffice("a1", _={}))
    assert r["cliente_nif"] == "244772903"


def test_a_pesquisa_encontra_pelo_NIF_DO_DOCUMENTO(monkeypatch):
    """Procurar pelo NIF real da fatura da app devolvia ZERO resultados — a
    pesquisa só olhava para as vendas, e uma fatura da app não tem nenhuma.
    O NIF é por onde o gestor procura a fatura de uma empresa."""
    _db(monkeypatch,
        [_da_app(),
         _documento("d2", "FS 1/2", 20.0, "2026-08-10T13:00:00+00:00")],
        vendas=[_venda("v-d2")])
    r = _corre(documentos_do_backoffice(q="244772903", _={}))
    assert [d["numero"] for d in r["documentos"]] == ["FS 06P2026/446"]


def test_o_NIF_do_documento_tem_precedencia_sobre_o_da_venda(monkeypatch):
    """A mesma regra de `relatorios.py:640`, e não é decorativa: escrita ao
    contrário (`venda or documento`), a linha voltava a ler a venda primeiro e
    as faturas da app perdiam o NIF outra vez assim que uma venda órfã
    aparecesse com o campo a `None`."""
    doc = dict(_da_app(id_="a2"), venda_id="v-a2")
    _db(monkeypatch, [doc], vendas=[_venda("v-a2", cliente_nif=None)])
    r = _corre(documento_do_backoffice("a2", _={}))
    assert r["cliente_nif"] == "244772903"
