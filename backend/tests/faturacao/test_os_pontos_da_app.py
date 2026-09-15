"""**Os pontos L'Açaí dados na caixa** — o lado do POS.

O que este ficheiro prende, por ordem de gravidade:

1. **nada disto pode impedir uma fatura de sair** — os ganchos da emissão e da
   nota de crédito vivem dentro de `except Exception`, e a tentativa imediata
   corre em segundo plano;
2. **um crédito por fatura** — a chave única da fila, e a reserva da linha
   antes de falar com a app;
3. **a máquina de estados do envio**, contra respostas com as formas EXACTAS do
   contrato da app (`/api/pos-integracao/ligar|creditar|estornar`);
4. **`pontos_ligacao` sempre presente** no que o finalizar grava na venda.

Nenhum teste fala com a app a sério: o transporte do httpx é um
`MockTransport`, e sem `APP_LACAI_URL` no ambiente nem sequer há endereço.
"""
import asyncio
import json
import logging
import os
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from faturacao import db as db_mod
from faturacao import fiscal as fiscal_mod
from faturacao import nota_credito as nc_mod
from faturacao import pontos_app
from faturacao.db import COLECOES
from faturacao.fiscal import PagamentoEntrada, PedidoFinalizarVenda
from tests.faturacao.test_fiscal import (
    ClienteEmissaoVendusFalso,
    ColeccaoFalsa,
    DbFalsa,
    _bruto,
    _configura_vendus_env,
    _corre,
    _db,
    _linha,
    _operador,
    _tipo_pagamento,
    _unicos_de,
    _venda,
)
from tests.faturacao.test_nota_credito import VendusNCFalso, _db_nc, _emitir


# --- A app a fingir -------------------------------------------------------------


class _App:
    """A app L'Açaí a fingir: responde o que o teste mandar e regista cada
    pedido. Uma resposta NOVA por pedido — um `httpx.Response` reaproveitado
    entre pedidos não é o que a rede faz."""

    def __init__(self):
        self.pedidos = []
        self._estado_http, self._corpo, self._erro = 200, {}, None

    def responde(self, estado_http, corpo=None):
        self._estado_http, self._corpo, self._erro = estado_http, corpo, None

    def rebenta(self, erro):
        self._erro = erro

    def corpo(self, i=-1):
        return json.loads(self.pedidos[i].content)

    def __call__(self, pedido):
        self.pedidos.append(pedido)
        if self._erro is not None:
            raise self._erro
        if self._corpo is None:
            return httpx.Response(self._estado_http, text="Internal Server Error")
        return httpx.Response(self._estado_http, json=self._corpo)


@pytest.fixture
def app(monkeypatch):
    falsa = _App()
    monkeypatch.setattr(pontos_app, "_transporte", httpx.MockTransport(falsa))
    monkeypatch.setenv("APP_LACAI_URL", "http://olacai-api:8001")
    monkeypatch.setenv("APP_LACAI_CHAVE", "chave-de-teste")
    return falsa


# --- Ler o QR -----------------------------------------------------------------

_MSG_QR = "QR inválido ou expirado — peça ao cliente para abrir o QR outra vez."
_MSG_APP = "Não foi possível falar com a app agora. A fatura pode seguir sem pontos."


def _venda_aberta(**over):
    v = {"id": "venda-1", "loja_id": "loja-1", "sessao_id": "sessao-1",
         "operador_id": "op-1", "estado": "aberta", "linhas": []}
    v.update(over)
    return v


def _db_do_ler(vendas=None):
    return DbFalsa({
        COLECOES["vendas"]: ColeccaoFalsa([_venda_aberta()] if vendas is None else vendas),
        COLECOES["lojas"]: ColeccaoFalsa([{"id": "loja-1", "nome": "Belém"}]),
    })


def _ler(monkeypatch, db, codigo="LQABCDEFGHJKLMNPQRSTUVWX", venda_id="venda-1"):
    monkeypatch.setattr(pontos_app, "obter_db", lambda: db)
    return _corre(pontos_app.ler_qr_de_pontos(
        pontos_app.PedidoLerQr(venda_id=venda_id, codigo=codigo), operador=_operador()))


def test_ler_o_qr_devolve_a_ligacao_e_so_o_primeiro_nome(monkeypatch, app):
    app.responde(200, {"ligacao_id": "lig-1", "primeiro_nome": "Ana"})
    assert _ler(monkeypatch, _db_do_ler()) == {"ligacao_id": "lig-1", "primeiro_nome": "Ana"}


def test_ler_manda_a_loja_e_o_operador_do_TOKEN_com_a_chave_no_cabecalho(monkeypatch, app):
    """A chave no cabeçalho e nunca no URL: um `?key=` fica escrito nos
    registos de quem estiver pelo meio. E 4 s de tecto — é a funcionária com o
    cliente à frente que espera por isto."""
    app.responde(200, {"ligacao_id": "lig-1", "primeiro_nome": "Ana"})
    _ler(monkeypatch, _db_do_ler(), codigo="LQ23456789ABCDEFGHJKLMNP")

    pedido = app.pedidos[0]
    assert pedido.method == "POST"
    assert str(pedido.url) == "http://olacai-api:8001/api/pos-integracao/ligar"
    assert pedido.headers["X-Service-Key"] == "chave-de-teste"
    assert "chave-de-teste" not in str(pedido.url)
    assert app.corpo() == {
        "codigo": "LQ23456789ABCDEFGHJKLMNP", "loja_nome": "Belém", "operador_nome": "Rafaela",
    }
    assert pedido.extensions["timeout"]["read"] == 4.0


def test_ler_nao_grava_nada_na_venda(monkeypatch, app):
    """A ligação volta ao ecrã. Uma leitura que não acabe em fatura não pode
    deixar um cliente agarrado à conta."""
    app.responde(200, {"ligacao_id": "lig-1", "primeiro_nome": "Ana"})
    db = _db_do_ler()
    _ler(monkeypatch, db)
    assert _corre(db[COLECOES["vendas"]].find_one({"id": "venda-1"})) == _venda_aberta()


def test_um_QR_recusado_pela_app_da_404_com_a_frase_da_funcionaria(monkeypatch, app):
    app.responde(404, {"estado": "recusado", "motivo": "qr_invalido"})
    with pytest.raises(HTTPException) as e:
        _ler(monkeypatch, _db_do_ler())
    assert (e.value.status_code, e.value.detail) == (404, _MSG_QR)


@pytest.mark.parametrize("corpo", [{"detail": "Not Found"}, None],
                         ids=["fastapi_sem_a_rota", "sem_json_nenhum"])
def test_um_404_do_SERVIDOR_da_app_nao_culpa_o_QR_do_cliente(monkeypatch, app, corpo):
    """O dia em que o RH sobe antes da app (a rota `/pos-integracao/ligar`
    ainda não lá está) ou o `APP_LACAI_URL` tem a porta trocada: o FastAPI da
    app responde `{"detail": "Not Found"}`, que não é o 404 do contrato.

    Traduzido para «QR inválido», a funcionária pedia ao cliente um QR novo
    vezes sem conta — e nenhum ia funcionar. A frase certa é a do 503: a app
    não está a responder, a fatura segue sem pontos."""
    app.responde(404, corpo)
    with pytest.raises(HTTPException) as e:
        _ler(monkeypatch, _db_do_ler())
    assert (e.value.status_code, e.value.detail) == (503, _MSG_APP)


@pytest.mark.parametrize("estado_http", [401, 500, 502, 503])
def test_a_app_a_responder_mal_da_503_e_a_fatura_segue(monkeypatch, app, estado_http):
    app.responde(estado_http, {"detail": "qualquer coisa"})
    with pytest.raises(HTTPException) as e:
        _ler(monkeypatch, _db_do_ler())
    assert (e.value.status_code, e.value.detail) == (503, _MSG_APP)


def test_a_app_calada_ate_ao_tecto_da_503(monkeypatch, app):
    app.rebenta(httpx.ReadTimeout("a app não respondeu"))
    with pytest.raises(HTTPException) as e:
        _ler(monkeypatch, _db_do_ler())
    assert (e.value.status_code, e.value.detail) == (503, _MSG_APP)


def test_um_200_sem_a_forma_do_contrato_da_503(monkeypatch, app):
    app.responde(200, {"estado": "ok"})
    with pytest.raises(HTTPException) as e:
        _ler(monkeypatch, _db_do_ler())
    assert (e.value.status_code, e.value.detail) == (503, _MSG_APP)


@pytest.mark.parametrize("variavel", ["APP_LACAI_URL", "APP_LACAI_CHAVE"])
def test_sem_configuracao_da_503_e_nem_sai_para_a_rede(monkeypatch, app, variavel):
    """Sem chave não se telefona com uma chave vazia: a app respondia 401 e a
    razão verdadeira (uma instalação por acabar) ficava escondida."""
    monkeypatch.delenv(variavel)
    with pytest.raises(HTTPException) as e:
        _ler(monkeypatch, _db_do_ler())
    assert (e.value.status_code, e.value.detail) == (503, _MSG_APP)
    assert app.pedidos == []


def test_uma_venda_de_OUTRA_loja_e_404_e_a_app_nem_e_chamada(monkeypatch, app):
    """A app consome o QR na primeira leitura: perguntar-lhe antes de conferir
    a venda gastava o QR do cliente numa recusa."""
    with pytest.raises(HTTPException) as e:
        _ler(monkeypatch, _db_do_ler(vendas=[_venda_aberta(loja_id="loja-2")]))
    assert (e.value.status_code, e.value.detail) == (404, "Venda não encontrada.")
    assert app.pedidos == []


@pytest.mark.parametrize("estado", ["emitida", "cancelada", "separada"])
def test_uma_venda_que_ja_nao_esta_aberta_e_409_e_a_app_nem_e_chamada(monkeypatch, app, estado):
    with pytest.raises(HTTPException) as e:
        _ler(monkeypatch, _db_do_ler(vendas=[_venda_aberta(estado=estado)]))
    assert e.value.status_code == 409
    assert app.pedidos == []


def test_a_rota_de_ler_esta_montada_no_router_do_modulo():
    """A rota tem de existir no router que o `server.py` monta — é contra ele
    que o `test_caminhos_do_pos.py` confronta o `lib/pos.js`, e é por ele que o
    `test_protecao_rotas.py` exige a sessão do operador."""
    from faturacao import router
    assert any(r.path == "/api/faturacao/pos/pontos/ler" and "POST" in r.methods
               for r in router.routes)
