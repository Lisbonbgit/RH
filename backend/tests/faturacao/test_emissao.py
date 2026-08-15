"""Emissão de documentos fiscais no Vendus (Plano 2B, Task 1) — sem rede:
`transport` injectado via `httpx.MockTransport`, mesmo padrão de
test_vendus_cliente.py e de ~/dev/pizzaria/backend/tests/vendus/test_client.py.

Este módulo (`vendus/emissao.py`) é o ÚNICO do pacote que ESCREVE no Vendus —
`vendus/cliente.py` é só de leitura e assim fica. Por isso aqui não há testes
de leitura (paginação, 404/A001); há testes de EMISSÃO: o payload que sai, as
retentativas de rede (429/5xx) e a recusa do `register_id` errado antes de
qualquer pedido.
"""
import base64
import json

import httpx
import pytest

from faturacao.vendus.cliente import VendusHTTPErro, VendusIndisponivel
from faturacao.vendus.emissao import (
    ClienteEmissaoVendus,
    RegisterIdInvalido,
    VendusRateLimitado,
)


def _dormidas():
    """Fake de `dormir` que só regista quanto "dormiu" — os testes nunca
    esperam a sério."""
    chamadas = []

    def dormir(segundos):
        chamadas.append(segundos)

    dormir.chamadas = chamadas
    return dormir


def _cliente(handler, chave="chave-teste", dormir=None):
    return ClienteEmissaoVendus(
        chave, transport=httpx.MockTransport(handler), dormir=dormir or _dormidas()
    )


def _linhas():
    return [{"title": "Açaí Regular", "qty": 1, "gross_price": 8.99, "tax_id": "INT"}]


def _pagamentos():
    return [{"id": 316430468, "amount": 8.99}]


# --- Emissão feliz -----------------------------------------------------------


def test_emissao_feliz_monta_o_payload_e_devolve_id_numero_atcud_total_e_talao(monkeypatch):
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")
    monkeypatch.setenv("VENDUS_MODE", "normal")
    talao_bytes = b"\x1b@ESC/POS talao..."
    seen = {}

    def handler(request: httpx.Request):
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content.decode())
        seen["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "id": 123,
                "number": "FS 2026/45",
                "atcud": "ABCD1234-45",
                "amount_gross": 8.99,
                "output": base64.b64encode(talao_bytes).decode(),
            },
        )

    resultado = _cliente(handler, chave="testkey").criar_fatura_simplificada(
        linhas=_linhas(),
        pagamentos=_pagamentos(),
        cliente=None,
        external_reference="pos-loja1-sessao1-venda1",
        register_id=7,
    )

    assert seen["auth"] == "Basic dGVzdGtleTo="
    assert "documents/" in seen["url"]
    b = seen["body"]
    assert b["type"] == "FS"
    assert b["register_id"] == 7
    assert b["items"] == _linhas()
    assert b["payments"] == _pagamentos()
    assert b["external_reference"] == "pos-loja1-sessao1-venda1"
    assert b["output"] == "escpos"
    assert b["mode"] == "normal"
    assert "client" not in b  # sem cliente -> sem NIF, o Vendus assume Consumidor Final

    assert resultado["id"] == 123
    assert resultado["numero"] == "FS 2026/45"
    assert resultado["atcud"] == "ABCD1234-45"
    assert resultado["total"] == 8.99
    assert resultado["talao_escpos"] == talao_bytes


def test_emissao_com_cliente_inclui_o_nif_no_payload(monkeypatch):
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")
    seen = {}

    def handler(request: httpx.Request):
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"id": 1, "number": "FS 1", "atcud": "X-1", "amount_gross": 8.99})

    _cliente(handler).criar_fatura_simplificada(
        linhas=_linhas(), pagamentos=_pagamentos(), cliente={"fiscal_id": "500000000"},
        external_reference="pos-loja1-sessao1-venda2", register_id=7,
    )
    assert seen["body"]["client"] == {"fiscal_id": "500000000"}


def test_emissao_sem_output_no_corpo_da_resposta_devolve_talao_vazio(monkeypatch):
    """Defensivo: se por algum motivo o Vendus não devolver `output` (não
    devia acontecer, pedimos sempre output=escpos), a emissão não rebenta —
    devolve bytes vazios, não um None a espalhar erro pelo código acima."""
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")

    def handler(request: httpx.Request):
        return httpx.Response(200, json={"id": 1, "number": "FS 1", "atcud": "X-1", "amount_gross": 8.99})

    resultado = _cliente(handler).criar_fatura_simplificada(
        linhas=_linhas(), pagamentos=_pagamentos(), cliente=None,
        external_reference="pos-loja1-sessao1-venda3", register_id=7,
    )
    assert resultado["talao_escpos"] == b""


def test_mode_por_omissao_e_tests(monkeypatch):
    """Sem VENDUS_MODE definido, o omisso é 'tests' — nunca 'normal' por
    acidente (spec §13: 'nada de mode=tests com clientes reais', o inverso
    também vale: nunca arrancar em 'normal' sem ninguém ter decidido isso)."""
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")
    monkeypatch.delenv("VENDUS_MODE", raising=False)
    seen = {}

    def handler(request: httpx.Request):
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"id": 1, "number": "FS 1", "atcud": "X-1", "amount_gross": 8.99})

    _cliente(handler).criar_fatura_simplificada(
        linhas=_linhas(), pagamentos=_pagamentos(), cliente=None,
        external_reference="pos-loja1-sessao1-venda4", register_id=7,
    )
    assert seen["body"]["mode"] == "tests"


# --- 429: lê Rate-Limit-Reset e repete ---------------------------------------


def test_429_le_rate_limit_reset_e_repete_ate_ter_sucesso(monkeypatch):
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")
    pedidos = []

    def handler(request: httpx.Request):
        pedidos.append(request)
        if len(pedidos) == 1:
            return httpx.Response(429, json={"errors": ["rate"]}, headers={"Rate-Limit-Reset": "2"})
        return httpx.Response(200, json={"id": 1, "number": "FS 1", "atcud": "X-1", "amount_gross": 8.99})

    dormir = _dormidas()
    resultado = _cliente(handler, dormir=dormir).criar_fatura_simplificada(
        linhas=_linhas(), pagamentos=_pagamentos(), cliente=None,
        external_reference="pos-loja1-sessao1-venda5", register_id=7,
    )
    assert len(pedidos) == 2  # repetiu exactamente uma vez
    assert dormir.chamadas == [2.0]  # esperou os segundos do cabeçalho
    assert resultado["id"] == 1


def test_429_sem_cabecalho_rate_limit_reset_cai_para_1_segundo(monkeypatch):
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")
    pedidos = []

    def handler(request: httpx.Request):
        pedidos.append(request)
        if len(pedidos) == 1:
            return httpx.Response(429, json={"errors": ["rate"]})  # sem o cabeçalho
        return httpx.Response(200, json={"id": 1, "number": "FS 1", "atcud": "X-1", "amount_gross": 8.99})

    dormir = _dormidas()
    _cliente(handler, dormir=dormir).criar_fatura_simplificada(
        linhas=_linhas(), pagamentos=_pagamentos(), cliente=None,
        external_reference="pos-loja1-sessao1-venda6", register_id=7,
    )
    assert dormir.chamadas == [1.0]


def test_429_persistente_desiste_com_erro_tipado_apos_as_tentativas_permitidas(monkeypatch):
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")
    pedidos = []

    def handler(request: httpx.Request):
        pedidos.append(request)
        return httpx.Response(429, json={"errors": ["rate"]}, headers={"Rate-Limit-Reset": "1"})

    dormir = _dormidas()
    with pytest.raises(VendusRateLimitado):
        _cliente(handler, dormir=dormir).criar_fatura_simplificada(
            linhas=_linhas(), pagamentos=_pagamentos(), cliente=None,
            external_reference="pos-loja1-sessao1-venda7", register_id=7,
        )
    assert len(pedidos) == 3  # tentativa original + 2 repetições, nunca mais


# --- 5xx: repete e desiste com erro tipado -----------------------------------


def test_5xx_repete_e_recupera_se_a_tentativa_seguinte_tiver_sucesso(monkeypatch):
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")
    pedidos = []

    def handler(request: httpx.Request):
        pedidos.append(request)
        if len(pedidos) < 2:
            return httpx.Response(503, text="down")
        return httpx.Response(200, json={"id": 1, "number": "FS 1", "atcud": "X-1", "amount_gross": 8.99})

    resultado = _cliente(handler).criar_fatura_simplificada(
        linhas=_linhas(), pagamentos=_pagamentos(), cliente=None,
        external_reference="pos-loja1-sessao1-venda8", register_id=7,
    )
    assert len(pedidos) == 2
    assert resultado["id"] == 1


def test_5xx_persistente_desiste_com_erro_tipado_apos_as_tentativas_permitidas(monkeypatch):
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")
    pedidos = []

    def handler(request: httpx.Request):
        pedidos.append(request)
        return httpx.Response(500, text="erro interno")

    with pytest.raises(VendusIndisponivel):
        _cliente(handler).criar_fatura_simplificada(
            linhas=_linhas(), pagamentos=_pagamentos(), cliente=None,
            external_reference="pos-loja1-sessao1-venda9", register_id=7,
        )
    assert len(pedidos) == 3  # nunca fica preso a repetir para sempre


def test_4xx_que_nao_seja_429_levanta_de_imediato_sem_repetir(monkeypatch):
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")
    pedidos = []

    def handler(request: httpx.Request):
        pedidos.append(request)
        return httpx.Response(400, text="corpo inválido")

    with pytest.raises(VendusHTTPErro):
        _cliente(handler).criar_fatura_simplificada(
            linhas=_linhas(), pagamentos=_pagamentos(), cliente=None,
            external_reference="pos-loja1-sessao1-venda10", register_id=7,
        )
    assert len(pedidos) == 1  # um 4xx "normal" não é transitório -> não repete


# --- register_id: recusa ANTES de sair para a rede ---------------------------


def test_register_id_diferente_do_configurado_e_recusado_antes_da_rede(monkeypatch):
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")
    chamou_rede = []

    def handler(request: httpx.Request):
        chamou_rede.append(request)
        return httpx.Response(200, json={"id": 1})

    with pytest.raises(RegisterIdInvalido):
        _cliente(handler).criar_fatura_simplificada(
            linhas=_linhas(), pagamentos=_pagamentos(), cliente=None,
            external_reference="pos-loja1-sessao1-venda11", register_id=999,
        )
    assert chamou_rede == []  # nenhum pedido saiu


def test_register_id_sem_vendus_register_id_configurado_e_recusado(monkeypatch):
    """Sem a variável de ambiente, não há 'o único configurado' para bater
    certo — recusa-se sempre, nunca se assume um valor por omissão para uma
    caixa fiscal."""
    monkeypatch.delenv("VENDUS_REGISTER_ID", raising=False)
    chamou_rede = []

    def handler(request: httpx.Request):
        chamou_rede.append(request)
        return httpx.Response(200, json={"id": 1})

    with pytest.raises(RegisterIdInvalido):
        _cliente(handler).criar_fatura_simplificada(
            linhas=_linhas(), pagamentos=_pagamentos(), cliente=None,
            external_reference="pos-loja1-sessao1-venda12", register_id=7,
        )
    assert chamou_rede == []
