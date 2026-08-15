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
    VendusModoInvalido,
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
    assert resultado["modo"] == "normal"  # o ecrã tem de poder avisar em que modo saiu


def test_emissao_com_cliente_inclui_o_nif_no_payload(monkeypatch):
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")
    monkeypatch.setenv("VENDUS_MODE", "tests")
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
    monkeypatch.setenv("VENDUS_MODE", "tests")

    def handler(request: httpx.Request):
        return httpx.Response(200, json={"id": 1, "number": "FS 1", "atcud": "X-1", "amount_gross": 8.99})

    resultado = _cliente(handler).criar_fatura_simplificada(
        linhas=_linhas(), pagamentos=_pagamentos(), cliente=None,
        external_reference="pos-loja1-sessao1-venda3", register_id=7,
    )
    assert resultado["talao_escpos"] == b""


def test_vendus_mode_nao_configurado_e_recusado_antes_da_rede(monkeypatch):
    """Buraco achado no Plano 2B, Task 3: a versão anterior caía em 'tests'
    em silêncio quando VENDUS_MODE não estava definido — uma loja podia
    passar o dia inteiro a emitir documentos SEM VALOR FISCAL sem ninguém dar
    por isso. Agora, sem configuração válida, a emissão recusa-se ANTES de
    qualquer pedido à rede — nunca assume 'tests' nem 'normal' por omissão."""
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")
    monkeypatch.delenv("VENDUS_MODE", raising=False)
    chamou_rede = []

    def handler(request: httpx.Request):
        chamou_rede.append(request)
        return httpx.Response(200, json={"id": 1})

    with pytest.raises(VendusModoInvalido):
        _cliente(handler).criar_fatura_simplificada(
            linhas=_linhas(), pagamentos=_pagamentos(), cliente=None,
            external_reference="pos-loja1-sessao1-venda4", register_id=7,
        )
    assert chamou_rede == []


def test_vendus_mode_com_valor_desconhecido_e_recusado_antes_da_rede(monkeypatch):
    """Um valor escrito à mão errado (ex.: 'producao' em vez de 'normal') não
    pode cair silenciosamente para nenhum dos dois modos — recusa-se, tal
    como a ausência total da variável."""
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")
    monkeypatch.setenv("VENDUS_MODE", "producao")
    chamou_rede = []

    def handler(request: httpx.Request):
        chamou_rede.append(request)
        return httpx.Response(200, json={"id": 1})

    with pytest.raises(VendusModoInvalido):
        _cliente(handler).criar_fatura_simplificada(
            linhas=_linhas(), pagamentos=_pagamentos(), cliente=None,
            external_reference="pos-loja1-sessao1-venda4b", register_id=7,
        )
    assert chamou_rede == []


def test_vendus_mode_tests_e_aceite_e_vai_no_payload(monkeypatch):
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")
    monkeypatch.setenv("VENDUS_MODE", "tests")
    seen = {}

    def handler(request: httpx.Request):
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"id": 1, "number": "FS 1", "atcud": "X-1", "amount_gross": 8.99})

    resultado = _cliente(handler).criar_fatura_simplificada(
        linhas=_linhas(), pagamentos=_pagamentos(), cliente=None,
        external_reference="pos-loja1-sessao1-venda4c", register_id=7,
    )
    assert seen["body"]["mode"] == "tests"
    assert resultado["modo"] == "tests"


# --- 429: lê Rate-Limit-Reset e repete ---------------------------------------


def test_429_le_rate_limit_reset_e_repete_ate_ter_sucesso(monkeypatch):
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")
    monkeypatch.setenv("VENDUS_MODE", "tests")
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
    monkeypatch.setenv("VENDUS_MODE", "tests")
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
    monkeypatch.setenv("VENDUS_MODE", "tests")
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
    monkeypatch.setenv("VENDUS_MODE", "tests")
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
    monkeypatch.setenv("VENDUS_MODE", "tests")
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
    monkeypatch.setenv("VENDUS_MODE", "tests")
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


# --- Verificação por referência externa (Task 3, passo 4) --------------------
#
# UMA chamada exacta — GET documents/?external_reference={ref} — usada só
# depois de uma emissão falhar por timeout, para saber se o Vendus chegou a
# processar o pedido antes de repetir. NUNCA um varrimento dos documentos do
# dia (a armadilha da Pizzaria com per_page=200 sem paginar).


def test_procurar_por_referencia_externa_encontra_o_documento(monkeypatch):
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")
    vistos = {}

    def handler(request: httpx.Request):
        vistos["url"] = str(request.url)
        vistos["method"] = request.method
        return httpx.Response(200, json=[{
            "id": 55, "number": "FS 2026/9", "atcud": "ABCD-9",
            "amount_gross": 17.98, "external_reference": "pos-loja1-sessao1-venda1",
            "status": "N",
        }])

    resultado = _cliente(handler).procurar_por_referencia_externa(
        "pos-loja1-sessao1-venda1", register_id=7
    )
    assert vistos["method"] == "GET"
    assert "external_reference=pos-loja1-sessao1-venda1" in vistos["url"]
    assert resultado["id"] == 55
    assert resultado["numero"] == "FS 2026/9"
    assert resultado["atcud"] == "ABCD-9"
    assert resultado["total"] == 17.98


def test_procurar_por_referencia_externa_sem_documento_devolve_none(monkeypatch):
    """404 com A001 é 'sem resultados' — não é avaria (mesma armadilha
    documentada em vendus/cliente.py)."""
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")

    def handler(request: httpx.Request):
        return httpx.Response(404, text='{"errors":["A001 - No data"]}')

    resultado = _cliente(handler).procurar_por_referencia_externa(
        "pos-loja1-sessao1-venda-inexistente", register_id=7
    )
    assert resultado is None


def test_procurar_por_referencia_externa_ignora_documento_anulado(monkeypatch):
    """Um documento ANULADO (status A) não conta como "já emitido" — a venda
    tem de poder emitir um novo."""
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")

    def handler(request: httpx.Request):
        return httpx.Response(200, json=[{
            "id": 55, "number": "FS 2026/9", "atcud": "ABCD-9", "amount_gross": 17.98,
            "external_reference": "pos-loja1-sessao1-venda1", "status": "A",
        }])

    resultado = _cliente(handler).procurar_por_referencia_externa(
        "pos-loja1-sessao1-venda1", register_id=7
    )
    assert resultado is None


def test_procurar_por_referencia_externa_recusa_register_id_errado_antes_da_rede(monkeypatch):
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")
    chamou_rede = []

    def handler(request: httpx.Request):
        chamou_rede.append(request)
        return httpx.Response(200, json=[])

    with pytest.raises(RegisterIdInvalido):
        _cliente(handler).procurar_por_referencia_externa("pos-x", register_id=999)
    assert chamou_rede == []


def test_procurar_por_referencia_externa_500_levanta_vendus_indisponivel(monkeypatch):
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")
    pedidos = []

    def handler(request: httpx.Request):
        pedidos.append(request)
        return httpx.Response(500, text="erro interno")

    with pytest.raises(VendusIndisponivel):
        _cliente(handler, dormir=_dormidas()).procurar_por_referencia_externa("pos-x", register_id=7)
    assert len(pedidos) == 3  # mesma retentativa de 5xx do POST


# --- Leitura paginada por dia (Task 4: reconciliação do fecho) ---------------
#
# Paginação SEMPRE completa (per_page=100 + X-Paginator-Pages), nunca a
# armadilha per_page=200 sem paginar.


def test_listar_documentos_por_dia_pagina_ate_esgotar(monkeypatch):
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")
    pedidos = []

    def handler(request: httpx.Request):
        pedidos.append(request)
        pagina = int(dict(request.url.params).get("page", "1"))
        if pagina == 1:
            return httpx.Response(
                200, headers={"X-Paginator-Pages": "2"},
                json=[{"id": i, "external_reference": "pos-x-%d" % i, "status": "N"} for i in range(100)],
            )
        return httpx.Response(
            200, headers={"X-Paginator-Pages": "2"},
            json=[{"id": 200, "external_reference": "pos-x-200", "status": "N"}],
        )

    documentos = _cliente(handler).listar_documentos_por_dia("2026-08-15", register_id=7)
    assert len(pedidos) == 2  # as DUAS páginas foram pedidas — nunca só a primeira
    assert len(documentos) == 101


def test_listar_documentos_por_dia_sem_resultados_devolve_lista_vazia(monkeypatch):
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")

    def handler(request: httpx.Request):
        return httpx.Response(404, text='{"errors":["A001 - No data"]}')

    assert _cliente(handler).listar_documentos_por_dia("2026-08-15", register_id=7) == []


def test_listar_documentos_por_dia_recusa_register_id_errado_antes_da_rede(monkeypatch):
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")
    chamou_rede = []

    def handler(request: httpx.Request):
        chamou_rede.append(request)
        return httpx.Response(200, json=[])

    with pytest.raises(RegisterIdInvalido):
        _cliente(handler).listar_documentos_por_dia("2026-08-15", register_id=999)
    assert chamou_rede == []
