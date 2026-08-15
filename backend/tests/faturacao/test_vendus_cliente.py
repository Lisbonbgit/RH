"""Cliente de leitura do catálogo Vendus (Task 21) — sem rede: `transport`
injectado via `httpx.MockTransport`, mesmo padrão de
~/dev/pizzaria/backend/tests/vendus/test_client.py.

A ARMADILHA que este ficheiro existe para nunca deixar voltar a acontecer
aqui: a importação do menu da pizzaria chamava a API sem `per_page` — o
Vendus devolve 20 resultados por omissão. Importava 20 produtos, dizia que
tinha corrido bem, e ninguém deu por isso durante semanas.
`test_pagina_ate_ao_fim_pelos_cabecalhos` é o teste directo dessa armadilha:
uma resposta de 3 páginas tem de ser lida por inteiro, não só a primeira.
"""
import httpx
import pytest

from faturacao.vendus.cliente import (
    ClienteVendus,
    ContaVendus,
    VendusHTTPErro,
    obter_conta,
)


def _cliente(handler):
    return ClienteVendus("chave-teste", transport=httpx.MockTransport(handler))


# --- Paginação ---------------------------------------------------------------


def test_pagina_ate_ao_fim_pelos_cabecalhos():
    """3 páginas de 100+100+37 produtos: o cliente tem de ler as 237, não só
    os 100 da primeira página. Teste directo da armadilha do brief."""
    paginas = {
        1: [{"id": i} for i in range(1, 101)],
        2: [{"id": i} for i in range(101, 201)],
        3: [{"id": i} for i in range(201, 238)],
    }
    pedidos = []

    def handler(request: httpx.Request):
        pagina = int(request.url.params.get("page"))
        pedidos.append((pagina, request.url.params.get("per_page")))
        return httpx.Response(
            200,
            json=paginas[pagina],
            headers={"X-Paginator-Items": "237", "X-Paginator-Pages": "3"},
        )

    produtos = _cliente(handler).listar_produtos()
    assert len(produtos) == 237
    assert [p["id"] for p in produtos] == list(range(1, 238))
    assert pedidos == [(1, "100"), (2, "100"), (3, "100")]  # per_page SEMPRE presente


def test_uma_pagina_so_para_quando_pages_e_1():
    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json=[{"id": 1}, {"id": 2}],
            headers={"X-Paginator-Items": "2", "X-Paginator-Pages": "1"},
        )

    assert len(_cliente(handler).listar_produtos()) == 2


def test_sem_cabecalho_de_paginacao_cai_para_sinal_fraco():
    """Uma resposta sem X-Paginator-Pages (API antiga ou mock incompleto)
    ainda assim não fica presa: usa o sinal fraco (página mais curta que
    per_page = última), o mesmo que o Financeiro já usa em server.py."""
    paginas = {1: [{"id": i} for i in range(100)], 2: [{"id": 100}, {"id": 101}]}

    def handler(request: httpx.Request):
        pagina = int(request.url.params.get("page"))
        return httpx.Response(200, json=paginas[pagina])  # sem X-Paginator-*

    assert len(_cliente(handler).listar_produtos()) == 102


def test_per_page_esta_sempre_no_pedido():
    """Regressão directa da armadilha: per_page nunca pode faltar do pedido."""
    vistos = []

    def handler(request: httpx.Request):
        vistos.append(request.url.params.get("per_page"))
        return httpx.Response(200, json=[], headers={"X-Paginator-Pages": "1"})

    _cliente(handler).listar_categorias()
    assert vistos == ["100"]


def test_paginacao_excessiva_levanta_em_vez_de_ficar_presa():
    """Limite defensivo (mesmo espírito dos limites do Financeiro em
    server.py): um catálogo de lojas de açaí nunca tem milhares de páginas —
    se tiver, é configuração errada, não algo a engolir em silêncio."""

    def handler(request: httpx.Request):
        pagina = int(request.url.params.get("page"))
        return httpx.Response(
            200, json=[{"id": pagina}], headers={"X-Paginator-Pages": "999999"}
        )

    with pytest.raises(Exception):
        _cliente(handler).listar_produtos()


# --- 404 "zero resultados" (código A001) -------------------------------------


def test_404_com_a001_e_zero_resultados_nao_e_avaria():
    def handler(request: httpx.Request):
        return httpx.Response(404, json={"errors": [{"code": "A001", "message": "No data"}]})

    assert _cliente(handler).listar_produtos() == []


def test_404_sem_a001_propaga_como_erro():
    def handler(request: httpx.Request):
        return httpx.Response(404, json={"errors": [{"code": "X999", "message": "Nope"}]})

    with pytest.raises(VendusHTTPErro):
        _cliente(handler).listar_produtos()


# --- obter_conta ---------------------------------------------------------


def test_obter_conta_encontra_pelo_nif(monkeypatch):
    monkeypatch.setenv(
        "VENDUS_ACCOUNTS",
        '[{"key":"k1","company_nif":"111111111"},{"key":"k2","company_nif":"517542510"}]',
    )
    assert obter_conta("517542510") == ContaVendus(chave="k2", company_nif="517542510")


def test_obter_conta_ignora_pontuacao_no_nif(monkeypatch):
    monkeypatch.setenv("VENDUS_ACCOUNTS", '[{"key":"k1","company_nif":"517 542 510"}]')
    assert obter_conta("517542510").chave == "k1"


def test_obter_conta_sem_env_devolve_none(monkeypatch):
    monkeypatch.delenv("VENDUS_ACCOUNTS", raising=False)
    assert obter_conta("517542510") is None


def test_obter_conta_json_invalido_devolve_none_nao_rebenta(monkeypatch):
    monkeypatch.setenv("VENDUS_ACCOUNTS", "isto não é json")
    assert obter_conta("517542510") is None


def test_obter_conta_nif_sem_correspondencia_devolve_none(monkeypatch):
    monkeypatch.setenv("VENDUS_ACCOUNTS", '[{"key":"k1","company_nif":"999999990"}]')
    assert obter_conta("517542510") is None


def test_obter_conta_usa_fat_nif_do_ambiente_por_omissao(monkeypatch):
    monkeypatch.setenv("VENDUS_ACCOUNTS", '[{"key":"k1","company_nif":"517542510"}]')
    monkeypatch.delenv("FAT_NIF", raising=False)
    assert obter_conta().company_nif == "517542510"


def test_obter_conta_entrada_sem_key_e_ignorada(monkeypatch):
    monkeypatch.setenv("VENDUS_ACCOUNTS", '[{"company_nif":"517542510"}]')
    assert obter_conta("517542510") is None
