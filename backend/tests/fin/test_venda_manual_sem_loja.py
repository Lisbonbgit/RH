"""**Uma venda manual sem loja não pode somar-se por cima da automática.**

A guarda do `fin_create_sale` existe para uma coisa só: se já há vendas
automáticas (Vendus/Moloni) naquele dia, lançar à mão soma por cima — e o
painel conta o dia a DOBRAR.

O furo era o `unit_id`. A guarda procurava `{"unit_id": doc.get("unit_id")}`,
e com a loja em branco isso procura linhas automáticas **sem loja** — que não
existem, porque o sync grava sempre com a unidade preenchida. A guarda passava
sempre, e a venda entrava. O painel soma por EMPRESA, por isso o dia ficava
contado duas vezes com o total credível de quem não desconfia.

A outra metade é o `_fin_supersede_manual_sales`, que limpa as manuais quando o
automático chega: filtrava pelo mesmo `unit_id` e também não via as que não
tinham loja — essas ficavam lá para sempre.
"""
import asyncio
import os

import pytest
from fastapi import HTTPException

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _casa(doc, filtro):
    """O mínimo de Mongo que estes testes precisam: igualdade e `$in`.

    **Isto não é adorno.** Um duplo que respondesse sempre o mesmo, olhasse o
    filtro para o que olhasse, passava na mesma COM o defeito lá dentro — e
    já aconteceu cinco vezes neste repositório um teste ficar a defender um
    defeito por causa de um duplo complacente. Aqui a linha automática tem
    mesmo uma loja, e é o filtro que decide se ela é encontrada."""
    for campo, esperado in filtro.items():
        valor = doc.get(campo)
        if isinstance(esperado, dict) and "$in" in esperado:
            if valor not in esperado["$in"]:
                return False
        elif valor != esperado:
            return False
    return True


class VendasFalsas:
    """Uma `fin_sales` de mentira com documentos a sério lá dentro, e que
    guarda o filtro de cada pergunta."""

    def __init__(self, guardadas=None):
        self.guardadas = list(guardadas or [])
        self.filtros = []
        self.inseridos = []
        self.apagados = []

    async def find_one(self, filtro, proj=None):
        # A releitura final do `fin_create_sale` (pelo id) não é a pergunta
        # que interessa aqui: devolve-se qualquer coisa para a rota terminar.
        if "id" in filtro:
            return {"id": filtro["id"]}
        self.filtros.append(filtro)
        for doc in self.guardadas:
            if _casa(doc, filtro):
                return doc
        return None

    async def insert_one(self, doc):
        self.inseridos.append(doc)

    async def delete_many(self, filtro):
        self.apagados.append(filtro)
        class Res:
            deleted_count = 0
        return Res()


class BaseFalsa:
    def __init__(self, vendas):
        self.fin_sales = vendas


@pytest.fixture
def sem_permissoes(monkeypatch):
    async def passa(*a, **kw):
        return None
    monkeypatch.setattr(server, "fin_require_editor", passa)


def _payload(unit_id):
    return server.FinSaleCreate(
        company_id="emp-1", unit_id=unit_id, date="2026-08-20", amount=100.0
    )


def test_sem_loja_a_guarda_pergunta_pela_EMPRESA_inteira(monkeypatch, sem_permissoes):
    """Sem loja escolhida, a pergunta certa é "esta empresa já tem automático
    neste dia?" — e não "há automático sem loja?", que nunca há."""
    vendas = VendasFalsas()
    monkeypatch.setattr(server, "db", BaseFalsa(vendas))

    _corre(server.fin_create_sale(_payload(None), {"user_id": "u1"}))

    guarda = vendas.filtros[0]
    assert "unit_id" not in guarda, (
        "com a loja em branco, filtrar por unit_id=None procura linhas "
        "automáticas sem loja — que não existem — e a guarda passa sempre"
    )
    assert guarda["company_id"] == "emp-1"
    assert guarda["date"] == "2026-08-20"
    assert guarda["source"] == {"$in": ["vendus", "moloni"]}


def test_sem_loja_e_com_automatico_no_dia_a_venda_e_recusada(monkeypatch, sem_permissoes):
    """O caso a sério: a Fordaimon já tem o dia sincronizado do Vendus e
    alguém lança 100 € à mão sem escolher loja. Antes entrava e o painel
    passava a mostrar o dia a dobrar."""
    # Como está na base a sério: a linha do Vendus tem a loja preenchida —
    # é por isso que um filtro `unit_id: None` nunca lhe chegava.
    vendas = VendasFalsas([{
        "id": "auto-1", "company_id": "emp-1", "unit_id": "loja-belem",
        "date": "2026-08-20", "source": "vendus",
    }])
    monkeypatch.setattr(server, "db", BaseFalsa(vendas))

    with pytest.raises(HTTPException) as e:
        _corre(server.fin_create_sale(_payload(None), {"user_id": "u1"}))

    assert e.value.status_code == 409
    assert "dobrar" in e.value.detail
    assert vendas.inseridos == [], "não pode ter gravado nada"


def test_com_loja_escolhida_a_guarda_continua_a_ser_por_loja(monkeypatch, sem_permissoes):
    """A correcção não pode alargar a guarda onde ela já estava certa: com
    loja, a dupla contagem é por loja, e recusar por causa de OUTRA loja da
    mesma empresa impedia um lançamento legítimo."""
    vendas = VendasFalsas([{
        "id": "auto-1", "company_id": "emp-1", "unit_id": "loja-oeiras",
        "date": "2026-08-20", "source": "vendus",
    }])
    monkeypatch.setattr(server, "db", BaseFalsa(vendas))

    # Oeiras já está sincronizada; lançar à mão em BELÉM é legítimo e tem de
    # passar — a dupla contagem é por loja quando há loja.
    _corre(server.fin_create_sale(_payload("loja-belem"), {"user_id": "u1"}))

    assert vendas.filtros[0]["unit_id"] == "loja-belem"
    assert len(vendas.inseridos) == 1, "a venda de Belém tinha de entrar"


def test_a_limpeza_do_automatico_tambem_apanha_as_manuais_sem_loja(monkeypatch):
    """A outra metade: quando o automático grava, arruma as manuais do mesmo
    dia. Uma manual sem loja era invisível a este filtro e ficava ao lado da
    automática — a somar em cima dela, para sempre."""
    vendas = VendasFalsas()
    monkeypatch.setattr(server, "db", BaseFalsa(vendas))

    _corre(server._fin_supersede_manual_sales("emp-1", "loja-belem", ["2026-08-20"]))

    filtro = vendas.apagados[0]
    assert filtro["unit_id"] == {"$in": ["loja-belem", None]}
    assert filtro["source"] == "manual", "nunca pode apagar linhas automáticas"
    assert filtro["date"] == {"$in": ["2026-08-20"]}
