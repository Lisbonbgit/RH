"""O cliente do openrouteservice (crm/servicos/ors.py), F3 / T3.11.

Plano F3 §1 ("openrouteservice", "Testes do ORS"), §0 regras 2 e 12 e risco
R1; dossiê §8. O molde é o cliente da Geoapify (`geoapify.obter_json`, testado
em test_morada.py):

- `otimizar(pedido)` faz um POST a `{base}/optimization` e `direcoes(pedido)`
  a `{base}/v2/directions/driving-car/json`, com o corpo
  `json.dumps(pedido, allow_nan=False)`;
- a chave (`CRM_ORS_CHAVE`) vai SÓ no cabeçalho `Authorization`, tal e qual:
  nunca no URL, nas mensagens das falhas nem nos registos (chave canária com o
  `caplog` em DEBUG no root, no `httpx` e no `httpcore`, em todos os
  caminhos);
- sem chave, `FalhaOrs(tipo="sem_chave")` sem pedido nenhum;
- não segue redireções; 15 s (otimização) e 10 s (Directions) ao todo, 3 s
  para ligar;
- 429 → `limite`; um 2010 com o número do ponto → `ponto_sem_estrada` com o
  `indice`; o resto → `indisponivel` com um `motivo` só com o estado HTTP ou o
  tipo da exceção.

Correções aplicadas (secção "Correções obrigatórias" do plano):
- "T3.11": o erro na forma do VROOM (`{"code": 3, "error": "<texto>"}`) é
  `indisponivel`, sem rebentar com o `error` em texto e sem o texto (que traz
  coordenadas) no `motivo` nem nos registos; o 2010 aceita "coordinate N" e o
  antigo "point N"; o 403 (quota diária esgotada ou chave inválida) é
  `indisponivel` com "estado HTTP 403";
- "T3.11 (conftest: guarda contra a rede)": a guarda do conftest regista os
  pedidos, responde 599 e rebenta no fim do teste; tira `CRM_ORS_CHAVE` e
  `CRM_ORS_URL` do ambiente. Os meta-testes chamam o gerador à mão;
- "T3.11 (CRM_ORS_URL e a chave em texto claro)": o `url_base()` só aceita
  `https://…` ou `http://` para 127.0.0.1, localhost ou [::1] (o simulador);
  o resto é `FalhaOrs("CRM_ORS_URL recusado", "indisponivel")`, sem pedido.

Nenhum teste sai para a rede: os pedidos vão para um `httpx.MockTransport` ou,
nos testes do transporte verdadeiro, para uma porta em 127.0.0.1.
"""
import ast
import json
import logging
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import pytest

from crm.dominio.directions import pedido_direcoes
from crm.dominio.vroom import ParagemCalculo, pedido_otimizacao
from crm.servicos import ors
from crm.servicos.ors import FalhaOrs, RespostaOrs, interpretar_erro, interpretar_resposta

from .conftest import ESTADO_DA_GUARDA_ORS, MENSAGEM_DA_GUARDA_ORS, guarda_contra_o_ors
from .duplos import correr

FIXTURES = Path(__file__).parent / "fixtures" / "ors"
FICHEIRO = Path(ors.__file__)

CHAVE = "ors-CANARIA-chave-5b3ce3597851110001cf6248"
OUTRA_CHAVE = "ors-OUTRA-CANARIA-9d1e"
BASE = "https://ors.teste"
OUTRA_BASE = "https://outro-ors.teste"

# Coordenadas canárias: vão no corpo dos pedidos e nunca podem aparecer nos
# registos nem nos motivos das falhas.
LAT_CANARIA = 38.765432
LNG_CANARIA = -9.123457
COORDENADAS_CANARIAS = ("38.765432", "9.123457", "38.7654320", "9.1234570")

FABRICA = (38.7223, -9.1393)

PEDIDO_DIRECOES = pedido_direcoes([FABRICA, (LAT_CANARIA, LNG_CANARIA), FABRICA], True)
PEDIDO_OTIMIZACAO = pedido_otimizacao(
    [ParagemCalculo("p1", LAT_CANARIA, LNG_CANARIA, 600, [[32400, 43200]], "entrega")],
    FABRICA,
    FABRICA,
    28800,
    68400,
).corpo

URL_OTIMIZACAO = "https://ors.teste/optimization"
URL_DIRECOES = "https://ors.teste/v2/directions/driving-car/json"

SERVICOS = {
    "otimizar": (ors.otimizar, PEDIDO_OTIMIZACAO, "/optimization"),
    "direcoes": (ors.direcoes, PEDIDO_DIRECOES, "/v2/directions/driving-car/json"),
}
NOMES_SERVICOS = list(SERVICOS)

VARIAVEIS_DE_PROXY = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")

RESPOSTA_DIRECOES = {"routes": [{"summary": {"distance": 1.0, "duration": 2.0}}]}


def _ler_fixture(nome):
    return (FIXTURES / nome).read_bytes()


def _json(dados):
    return json.dumps(dados).encode("utf-8")


class OrsFalso:
    """O openrouteservice falso, como handler de um `httpx.MockTransport`:
    responde sempre o mesmo (ou falha) e guarda os pedidos recebidos."""

    def __init__(self, responder):
        self.pedidos = []
        self._responder = responder

    def __call__(self, pedido):
        self.pedidos.append(pedido)
        return self._responder(pedido)

    @classmethod
    def responde(cls, dados=None, estado=200, corpo=None, cabecalhos=None):
        def _responder(pedido):
            conteudo = corpo(pedido) if callable(corpo) else corpo
            if conteudo is None:
                conteudo = _json(dados if dados is not None else {})
            return httpx.Response(estado, content=conteudo, headers=cabecalhos or {})

        return cls(_responder)

    @classmethod
    def falha(cls, excecao):
        def _responder(pedido):
            raise excecao(pedido)

        return cls(_responder)


@pytest.fixture
def transporte(monkeypatch):
    """`transporte(ors_falso)` instala o ORS falso no cliente; devolve-o."""
    for nome in VARIAVEIS_DE_PROXY:
        monkeypatch.delenv(nome, raising=False)

    def _instalar(falso):
        monkeypatch.setattr(ors, "_transporte", httpx.MockTransport(falso))
        return falso

    return _instalar


@pytest.fixture
def com_chave(monkeypatch):
    """A chave canária e o URL de teste no ambiente."""
    monkeypatch.setenv(ors.VARIAVEL_CHAVE, CHAVE)
    monkeypatch.setenv(ors.VARIAVEL_URL, BASE)


def _chamar(servico, **argumentos):
    funcao, pedido, _ = SERVICOS[servico]
    return correr(funcao(pedido, **argumentos))


def _falha(servico="direcoes", **argumentos):
    """A `FalhaOrs` que a chamada lança (o teste falha se não lançar)."""
    with pytest.raises(FalhaOrs) as apanhada:
        _chamar(servico, **argumentos)
    return apanhada.value


def _segredos(pedido):
    """A chave e o corpo do pedido: as exceções falsas trazem-nos na mensagem,
    como as do httpx trazem o URL."""
    return f"{pedido.headers.get('authorization')} {pedido.content.decode('utf-8')}"


FALHAS_DA_REDE = [
    lambda p: httpx.ReadTimeout(f"tempo esgotado {_segredos(p)}", request=p),
    lambda p: httpx.ConnectTimeout(f"tempo esgotado a ligar {_segredos(p)}", request=p),
    lambda p: httpx.ConnectError(f"sem ligação {_segredos(p)}", request=p),
    lambda p: httpx.ReadError(f"leitura falhou {_segredos(p)}", request=p),
    lambda p: httpx.RemoteProtocolError(f"protocolo partido {_segredos(p)}", request=p),
    lambda p: httpx.TooManyRedirects(f"redireções a mais {_segredos(p)}", request=p),
    lambda p: httpx.DecodingError(f"gzip partido {_segredos(p)}", request=p),
    lambda p: httpx.UnsupportedProtocol(f"protocolo desconhecido {_segredos(p)}", request=p),
    lambda p: httpx.InvalidURL(f"URL inválido {_segredos(p)}"),
    lambda p: RuntimeError(f"avaria inesperada {_segredos(p)}"),
]
NOMES_DAS_FALHAS = [
    "ReadTimeout",
    "ConnectTimeout",
    "ConnectError",
    "ReadError",
    "RemoteProtocolError",
    "TooManyRedirects",
    "DecodingError",
    "UnsupportedProtocol",
    "InvalidURL",
    "RuntimeError",
]


# --- A guarda do conftest (correção "T3.11 (conftest: guarda contra a rede)") ------------


def test_por_omissao_os_testes_do_crm_tem_a_guarda_e_nao_tem_chave_nem_url(pedidos_ao_ors_sem_transporte):
    """Sem transporte próprio, o pedido vai à guarda: fica registado e recebe
    599 (→ `indisponivel`). O teste limpa a lista no fim, senão a guarda
    rebentava (é o que o meta-teste a seguir prova)."""
    assert ors.VARIAVEL_CHAVE not in os.environ
    assert ors.VARIAVEL_URL not in os.environ
    assert isinstance(ors._transporte, httpx.MockTransport)
    falha = _falha(chave=CHAVE, url=BASE)
    assert (falha.tipo, falha.motivo) == ("indisponivel", f"estado HTTP {ESTADO_DA_GUARDA_ORS}")
    assert [str(p.url) for p in pedidos_ao_ors_sem_transporte] == [URL_DIRECOES]
    pedidos_ao_ors_sem_transporte.clear()


def test_um_teste_sem_transporte_proprio_rebenta_no_fim():
    """O meta-teste: o gerador do fixture chamado à mão, com um MonkeyPatch
    próprio. Um pedido sem o transporte do teste faz o fim do fixture
    levantar, mesmo quando o teste esperava uma falha (o 503 da rota)."""
    with pytest.MonkeyPatch.context() as mp:
        gerador = guarda_contra_o_ors(mp)
        pedidos = next(gerador)
        mp.setenv(ors.VARIAVEL_CHAVE, CHAVE)
        falha = _falha()
        assert falha.tipo == "indisponivel"
        assert len(pedidos) == 1
        with pytest.raises(AssertionError, match=MENSAGEM_DA_GUARDA_ORS):
            next(gerador)


def test_um_teste_sem_pedidos_passa_a_guarda():
    with pytest.MonkeyPatch.context() as mp:
        gerador = guarda_contra_o_ors(mp)
        assert next(gerador) == []
        with pytest.raises(StopIteration):
            next(gerador)


def test_a_guarda_tira_a_chave_e_o_url_do_ambiente_e_repoe_os_no_fim():
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv(ors.VARIAVEL_CHAVE, CHAVE)
        mp.setenv(ors.VARIAVEL_URL, BASE)
        antes = ors._transporte
        with pytest.MonkeyPatch.context() as interno:
            gerador = guarda_contra_o_ors(interno)
            next(gerador)
            assert ors.VARIAVEL_CHAVE not in os.environ
            assert ors.VARIAVEL_URL not in os.environ
            assert ors._transporte is not antes
            with pytest.raises(StopIteration):
                next(gerador)
        assert (os.environ[ors.VARIAVEL_CHAVE], os.environ[ors.VARIAVEL_URL]) == (CHAVE, BASE)
        assert ors._transporte is antes


def test_um_teste_com_transporte_proprio_nao_toca_na_guarda(transporte, com_chave, pedidos_ao_ors_sem_transporte):
    falso = transporte(OrsFalso.responde(RESPOSTA_DIRECOES))
    assert _chamar("direcoes") == RESPOSTA_DIRECOES
    assert len(falso.pedidos) == 1
    assert pedidos_ao_ors_sem_transporte == []


# --- O pedido -------------------------------------------------------------------------------


@pytest.mark.parametrize("servico", NOMES_SERVICOS)
def test_faz_um_post_com_a_chave_so_no_authorization(transporte, com_chave, servico):
    falso = transporte(OrsFalso.responde({"code": 0}))
    _, pedido, caminho = SERVICOS[servico]
    assert _chamar(servico) == {"code": 0}
    [enviado] = falso.pedidos
    assert enviado.method == "POST"
    assert str(enviado.url) == BASE + caminho
    assert enviado.headers.get_list("authorization") == [CHAVE]
    assert enviado.headers.get_list("content-type") == ["application/json"]
    assert enviado.headers.get_list("accept") == ["application/json"]
    assert enviado.content == json.dumps(pedido, allow_nan=False).encode("utf-8")
    assert json.loads(enviado.content) == pedido


@pytest.mark.parametrize("servico", NOMES_SERVICOS)
def test_a_chave_nunca_vai_no_url_nem_no_corpo(transporte, com_chave, servico):
    falso = transporte(OrsFalso.responde({}))
    _chamar(servico)
    [enviado] = falso.pedidos
    assert enviado.url.query == b""
    assert CHAVE not in str(enviado.url)
    assert CHAVE.lower() not in str(enviado.url).lower()
    assert CHAVE not in enviado.content.decode("utf-8")
    assert "api_key" not in str(enviado.url)


def test_os_caminhos_dos_dois_servicos():
    assert ors.CAMINHO_OTIMIZACAO == "/optimization"
    assert ors.CAMINHO_DIRECOES == "/v2/directions/driving-car/json"
    assert ors.URL_POR_OMISSAO == "https://api.openrouteservice.org"
    assert (ors.VARIAVEL_CHAVE, ors.VARIAVEL_URL) == ("CRM_ORS_CHAVE", "CRM_ORS_URL")


@pytest.mark.parametrize(
    "base, esperado",
    [
        ("https://ors.teste", URL_DIRECOES),
        ("https://ors.teste/", URL_DIRECOES),
        ("https://ors.teste//", URL_DIRECOES),
        ("http://127.0.0.1:8013", "http://127.0.0.1:8013/v2/directions/driving-car/json"),
        ("http://127.0.0.1:8013/ors/", "http://127.0.0.1:8013/ors/v2/directions/driving-car/json"),
    ],
    ids=["sem barra", "com barra", "duas barras", "simulador", "com caminho"],
)
def test_a_base_com_ou_sem_barra_no_fim(transporte, monkeypatch, base, esperado):
    monkeypatch.setenv(ors.VARIAVEL_CHAVE, CHAVE)
    monkeypatch.setenv(ors.VARIAVEL_URL, base)
    falso = transporte(OrsFalso.responde({}))
    _chamar("direcoes")
    assert [str(p.url) for p in falso.pedidos] == [esperado]


def test_a_chave_vai_tal_e_qual(transporte, monkeypatch):
    """Sem `Bearer`, sem aparar e sem codificar (a chave do ORS é um texto
    opaco que vai inteiro no `Authorization`)."""
    chave = "  aB3+/=_-.~ chave  "
    monkeypatch.setenv(ors.VARIAVEL_CHAVE, chave)
    falso = transporte(OrsFalso.responde({}))
    _chamar("otimizar", url=BASE)
    assert falso.pedidos[0].headers.get_list("authorization") == [chave]


def test_a_chave_e_o_url_leem_se_do_ambiente_a_cada_chamada(transporte, monkeypatch):
    falso = transporte(OrsFalso.responde({}))
    monkeypatch.setenv(ors.VARIAVEL_CHAVE, CHAVE)
    monkeypatch.setenv(ors.VARIAVEL_URL, BASE)
    _chamar("direcoes")
    monkeypatch.setenv(ors.VARIAVEL_CHAVE, OUTRA_CHAVE)
    monkeypatch.setenv(ors.VARIAVEL_URL, OUTRA_BASE)
    _chamar("direcoes")
    assert [(str(p.url), p.headers["authorization"]) for p in falso.pedidos] == [
        (URL_DIRECOES, CHAVE),
        (OUTRA_BASE + "/v2/directions/driving-car/json", OUTRA_CHAVE),
    ]


@pytest.mark.parametrize("servico", NOMES_SERVICOS)
def test_a_chave_e_o_url_por_parametro_ganham_ao_ambiente(transporte, com_chave, servico):
    """O gravador (T3.12) passa a chave do seu ficheiro e o URL oficial."""
    falso = transporte(OrsFalso.responde({}))
    _chamar(servico, chave=OUTRA_CHAVE, url=OUTRA_BASE)
    [enviado] = falso.pedidos
    assert str(enviado.url) == OUTRA_BASE + SERVICOS[servico][2]
    assert enviado.headers.get_list("authorization") == [OUTRA_CHAVE]


def test_chave_e_url_base_leem_o_ambiente(monkeypatch):
    assert ors.chave() == ""
    assert ors.url_base() == ors.URL_POR_OMISSAO
    monkeypatch.setenv(ors.VARIAVEL_URL, "")
    assert ors.url_base() == ors.URL_POR_OMISSAO
    monkeypatch.setenv(ors.VARIAVEL_CHAVE, CHAVE)
    monkeypatch.setenv(ors.VARIAVEL_URL, BASE)
    assert (ors.chave(), ors.url_base()) == (CHAVE, BASE)


@pytest.mark.parametrize("servico", NOMES_SERVICOS)
@pytest.mark.parametrize(
    "ambiente, argumentos",
    [
        (None, {}),
        ("", {}),
        (None, {"chave": ""}),
        (CHAVE, {"chave": ""}),
    ],
    ids=["sem variável", "variável vazia", "parâmetro vazio", "parâmetro vazio ganha ao ambiente"],
)
def test_sem_chave_nao_ha_pedido_nenhum(transporte, monkeypatch, servico, ambiente, argumentos):
    if ambiente is not None:
        monkeypatch.setenv(ors.VARIAVEL_CHAVE, ambiente)
    monkeypatch.setenv(ors.VARIAVEL_URL, BASE)
    falso = transporte(OrsFalso.responde({}))
    falha = _falha(servico, **argumentos)
    assert (falha.tipo, falha.motivo, falha.indice) == ("sem_chave", "sem chave", None)
    assert falso.pedidos == []
    assert (falha.__cause__, falha.__context__) == (None, None)


@pytest.mark.parametrize("valor", [float("nan"), float("inf"), float("-inf")], ids=["NaN", "inf", "-inf"])
@pytest.mark.parametrize("com_a_chave", [True, False], ids=["com chave", "sem chave"])
def test_um_numero_que_nao_e_json_e_um_engano_do_codigo(transporte, monkeypatch, valor, com_a_chave):
    """`json.dumps(…, allow_nan=False)`: o `ValueError` sobe (não é uma
    `FalhaOrs`, que daria um 503 a esconder o engano) e não há pedido."""
    if com_a_chave:
        monkeypatch.setenv(ors.VARIAVEL_CHAVE, CHAVE)
    falso = transporte(OrsFalso.responde({}))
    pedido = {"coordinates": [[valor, 38.7], [-9.1, 38.7]]}
    with pytest.raises(ValueError):
        correr(ors.direcoes(pedido, url=BASE))
    assert falso.pedidos == []


@pytest.mark.parametrize("pedido", [None, [], "{}", 3], ids=["None", "lista", "texto", "número"])
def test_um_pedido_que_nao_e_um_objeto_e_um_engano_do_codigo(transporte, com_chave, pedido):
    falso = transporte(OrsFalso.responde({}))
    with pytest.raises(TypeError):
        correr(ors.otimizar(pedido))
    assert falso.pedidos == []


@pytest.mark.parametrize("chave", [b"bytes", 3, True], ids=["bytes", "número", "bool"])
def test_uma_chave_que_nao_e_texto_e_um_engano_do_codigo(transporte, chave):
    falso = transporte(OrsFalso.responde({}))
    with pytest.raises(TypeError):
        correr(ors.direcoes(PEDIDO_DIRECOES, chave=chave, url=BASE))
    assert falso.pedidos == []


@pytest.mark.parametrize("estado", [301, 302, 303, 307, 308])
def test_nao_segue_redirecoes(transporte, com_chave, estado):
    falso = transporte(OrsFalso.responde({}, estado=estado, cabecalhos={"Location": BASE + "/outro-sitio"}))
    falha = _falha("otimizar")
    assert (falha.tipo, falha.motivo) == ("indisponivel", f"estado HTTP {estado}")
    assert [str(p.url) for p in falso.pedidos] == [URL_OTIMIZACAO]


@pytest.mark.parametrize(
    "servico, tempo, total",
    [("otimizar", httpx.Timeout(15.0, connect=3.0), 15.0), ("direcoes", httpx.Timeout(10.0, connect=3.0), 10.0)],
    ids=NOMES_SERVICOS,
)
def test_o_cliente_usa_o_tempo_do_servico_e_nao_segue_redirecoes(transporte, com_chave, monkeypatch, servico, tempo, total):
    criados = []
    esperas = []
    original = httpx.AsyncClient
    espera_original = ors.asyncio.wait_for

    def espiao(*args, **kwargs):
        criados.append(kwargs)
        return original(*args, **kwargs)

    async def espera_espia(coro, limite):
        esperas.append(limite)
        return await espera_original(coro, limite)

    monkeypatch.setattr(ors.httpx, "AsyncClient", espiao)
    monkeypatch.setattr(ors.asyncio, "wait_for", espera_espia)
    transporte(OrsFalso.responde({}))
    _chamar(servico)
    assert len(criados) == 1
    assert criados[0]["timeout"] == tempo
    assert criados[0]["follow_redirects"] is False
    assert criados[0]["transport"] is ors._transporte
    assert esperas == [total]


def test_os_tempos_limite():
    """Plano §1: 3 s para ligar; 15 s ao todo na otimização e 10 s no
    Directions (o `otimizar` da T3.22 fica abaixo dos 25 s, contra os 35 s do
    cliente)."""
    assert ors.TEMPO_OTIMIZACAO == httpx.Timeout(15.0, connect=3.0)
    assert (ors.TEMPO_OTIMIZACAO.connect, ors.TEMPO_OTIMIZACAO.read) == (3.0, 15.0)
    assert ors.TOTAL_OTIMIZACAO_S == 15.0
    assert ors.TEMPO_DIRECOES == httpx.Timeout(10.0, connect=3.0)
    assert (ors.TEMPO_DIRECOES.connect, ors.TEMPO_DIRECOES.read) == (3.0, 10.0)
    assert ors.TOTAL_DIRECOES_S == 10.0


@pytest.mark.parametrize("servico, total", [("otimizar", "TOTAL_OTIMIZACAO_S"), ("direcoes", "TOTAL_DIRECOES_S")])
def test_um_transporte_pendurado_esgota_o_tempo_total(transporte, com_chave, monkeypatch, servico, total):
    monkeypatch.setattr(ors, total, 0.05)

    async def pendurado(pedido):
        await ors.asyncio.sleep(2)
        return httpx.Response(200, json={})

    transporte(pendurado)
    inicio = time.monotonic()
    falha = _falha(servico)
    assert (falha.tipo, falha.motivo) == ("indisponivel", "sem resposta (TimeoutError)")
    assert (falha.__cause__, falha.__context__) == (None, None)
    assert time.monotonic() - inicio < 1.0


@pytest.mark.parametrize("curto, longo", [("otimizar", "direcoes"), ("direcoes", "otimizar")])
def test_cada_servico_usa_o_seu_tempo_total(transporte, com_chave, monkeypatch, curto, longo):
    nomes = {"otimizar": "TOTAL_OTIMIZACAO_S", "direcoes": "TOTAL_DIRECOES_S"}
    monkeypatch.setattr(ors, nomes[curto], 0.05)
    monkeypatch.setattr(ors, nomes[longo], 5.0)

    async def devagar(pedido):
        await ors.asyncio.sleep(0.3)
        return httpx.Response(200, json={"ok": 1})

    transporte(devagar)
    assert _falha(curto).motivo == "sem resposta (TimeoutError)"
    assert _chamar(longo) == {"ok": 1}


# --- O URL base (correção "T3.11 (CRM_ORS_URL e a chave em texto claro)") ----------------


@pytest.mark.parametrize(
    "base",
    [
        "https://api.openrouteservice.org",
        "https://ors.teste/",
        "HTTPS://ors.teste",
        "https://ors.teste:8443/ors",
        "http://127.0.0.1:8013",
        "http://127.0.0.1",
        "http://localhost:8013/",
        "http://LOCALHOST:8013",
        "http://[::1]:8013",
    ],
)
def test_o_url_base_aceita_https_ou_http_so_para_o_simulador_local(transporte, monkeypatch, base):
    monkeypatch.setenv(ors.VARIAVEL_URL, base)
    assert ors.url_base() == base
    monkeypatch.setenv(ors.VARIAVEL_CHAVE, CHAVE)
    falso = transporte(OrsFalso.responde({}))
    _chamar("direcoes")
    assert len(falso.pedidos) == 1


URLS_RECUSADOS = [
    "http://exemplo.invalid",
    "http://api.openrouteservice.org",
    "http://127.0.0.1.exemplo.invalid",
    "http://localhost.exemplo.invalid:8013",
    "http://127.0.0.2:8013",
    "http://0.0.0.0:8013",
    "http://127.0.0.1@exemplo.invalid",
    "https://utilizador:senha@ors.teste",
    "http://exemplo.invalid@127.0.0.1:8013",
    "ftp://ors.teste",
    "ws://localhost:8013",
    "ors.teste",
    "//ors.teste",
    "https://",
    "https:///v2",
    "https://ors.teste?api_key=x",
    "https://ors.teste/?",
    "https://ors.teste#fim",
    "https://ors.teste:porta",
    "http://127.0.0.1:99999",
    "http://[::1",
    " https://ors.teste",
    "https://ors.teste ",
    "https://ors teste",
    "https://ors.teste\n",
]


@pytest.mark.parametrize("base", URLS_RECUSADOS)
def test_o_url_base_recusa_o_resto_sem_pedido_nenhum(transporte, monkeypatch, base):
    """Um `http://` para fora mandava a chave sem cifra; um URL com
    utilizador trocava o `Authorization` pelo do URL. Nunca se faz o pedido."""
    monkeypatch.setenv(ors.VARIAVEL_URL, base)
    with pytest.raises(FalhaOrs) as apanhada:
        ors.url_base()
    assert (apanhada.value.tipo, apanhada.value.motivo) == ("indisponivel", "CRM_ORS_URL recusado")
    monkeypatch.setenv(ors.VARIAVEL_CHAVE, CHAVE)
    falso = transporte(OrsFalso.responde({}))
    for servico in NOMES_SERVICOS:
        falha = _falha(servico)
        assert (falha.tipo, falha.motivo, falha.indice) == ("indisponivel", "CRM_ORS_URL recusado", None)
        assert (falha.__cause__, falha.__context__) == (None, None)
    assert falso.pedidos == []


@pytest.mark.parametrize(
    "base",
    ["http://exemplo.invalid", "", "https://ors.teste?x=1", "https://ors.teste/\x00"],
    ids=["http para fora", "vazio", "query", "NUL"],
)
def test_o_url_por_parametro_tambem_se_verifica(transporte, base):
    """Um `url=` vazio não cai no ambiente: é recusado. O NUL só se prova
    aqui: o `os.environ` não guarda um valor com NUL (`ValueError: embedded
    null byte`), por isso não entra em `URLS_RECUSADOS`."""
    falso = transporte(OrsFalso.responde({}))
    falha = _falha("otimizar", chave=CHAVE, url=base)
    assert (falha.tipo, falha.motivo) == ("indisponivel", "CRM_ORS_URL recusado")
    assert falso.pedidos == []


def test_o_motivo_do_url_recusado_nao_traz_o_url(transporte, monkeypatch):
    monkeypatch.setenv(ors.VARIAVEL_CHAVE, CHAVE)
    monkeypatch.setenv(ors.VARIAVEL_URL, f"http://{CHAVE}.exemplo.invalid")
    transporte(OrsFalso.responde({}))
    falha = _falha()
    assert CHAVE not in str(falha) and CHAVE not in repr(falha)


# --- As respostas ---------------------------------------------------------------------------


@pytest.mark.parametrize("estado", [200, 201, 299])
@pytest.mark.parametrize("servico", NOMES_SERVICOS)
def test_um_2xx_com_um_objeto_json_devolve_o_dicionario(transporte, com_chave, servico, estado):
    transporte(OrsFalso.responde({"code": 0, "routes": []}, estado=estado))
    assert _chamar(servico) == {"code": 0, "routes": []}


@pytest.mark.parametrize(
    "servico, fixture",
    [("otimizar", "otimizacao-todas.json"), ("direcoes", "direcoes-tres-paragens.json")],
    ids=NOMES_SERVICOS,
)
def test_le_as_respostas_gravadas(transporte, com_chave, servico, fixture):
    transporte(OrsFalso.responde(corpo=_ler_fixture(fixture)))
    assert _chamar(servico) == json.loads(_ler_fixture(fixture))


@pytest.mark.parametrize(
    "corpo, motivo",
    [
        (b"[]", "resposta que não é um objeto JSON"),
        (b'[{"routes": []}]', "resposta que não é um objeto JSON"),
        (b"<html>502 Bad Gateway</html>", "resposta que não é JSON (JSONDecodeError)"),
        (b"", "resposta que não é JSON (JSONDecodeError)"),
        (b'{"routes": NaN}', "resposta que não é JSON (ValueError)"),
        (b'{"a": Infinity}', "resposta que não é JSON (ValueError)"),
        (b'"texto"', "resposta que não é JSON (ValueError)"),
        (b"3", "resposta que não é JSON (ValueError)"),
        (b"\xff\xfe{}", "resposta que não é JSON (UnicodeDecodeError)"),
        (b'{"a": "\\ud800"}', "resposta que não é JSON (UnicodeEncodeError)"),
    ],
    ids=["lista", "lista com objeto", "html", "vazio", "NaN", "Infinity", "texto", "número", "UTF-16", "surrogate"],
)
def test_um_2xx_que_nao_e_um_objeto_json_e_indisponivel(transporte, com_chave, corpo, motivo):
    transporte(OrsFalso.responde(corpo=corpo))
    for servico in NOMES_SERVICOS:
        falha = _falha(servico)
        assert (falha.tipo, falha.motivo, falha.indice) == ("indisponivel", motivo, None)
        assert (falha.__cause__, falha.__context__) == (None, None)


@pytest.mark.parametrize(
    "corpo",
    [_ler_fixture("erro-429.json"), b"", b"<html>Too Many Requests</html>", _ler_fixture("direcoes-erro-2010.json")],
    ids=["fixture", "vazio", "html", "com um 2010"],
)
@pytest.mark.parametrize("servico", NOMES_SERVICOS)
def test_o_429_e_o_limite(transporte, com_chave, servico, corpo):
    transporte(OrsFalso.responde(corpo=corpo, estado=429))
    falha = _falha(servico)
    assert (falha.tipo, falha.motivo, falha.indice) == ("limite", "estado HTTP 429", None)


def test_a_fixture_do_429_e_manual():
    """Correção "T3.12 / T3.43": o 429 não se grava de forma garantida e fica
    sempre manual (o gravador grava só a lista fechada)."""
    dados = json.loads(_ler_fixture("erro-429.json"))
    assert dados["_origem"].startswith("manual — nunca se regrava")
    assert set(dados) == {"_origem", "error"}


MENSAGEM_2010 = "Could not find routable point within a radius of 350.0 meters of specified coordinate {n}: -9.1234570 38.7654320."
MENSAGEM_2010_ANTIGA = "Could not find point {n}: -9.1234570 38.7654320 within a radius of 350.0 meters."


def _erro_2010(mensagem, codigo=2010):
    return _json({"error": {"code": codigo, "message": mensagem}, "info": {"engine": {"version": "9.1.2"}}})


@pytest.mark.parametrize("estado", [400, 404, 500])
@pytest.mark.parametrize("modelo", [MENSAGEM_2010, MENSAGEM_2010_ANTIGA], ids=["coordinate N", "point N"])
def test_o_2010_do_directions_e_um_ponto_sem_estrada_com_o_indice(transporte, com_chave, estado, modelo):
    transporte(OrsFalso.responde(corpo=_erro_2010(modelo.format(n=3)), estado=estado))
    falha = _falha("direcoes")
    assert (falha.tipo, falha.indice) == ("ponto_sem_estrada", 3)
    assert falha.motivo == f"estado HTTP {estado} (código 2010)"
    assert (falha.__cause__, falha.__context__) == (None, None)


@pytest.mark.parametrize("indice", [0, 1, 9, 10, 49])
def test_o_indice_do_2010_e_o_numero_do_texto(transporte, com_chave, indice):
    """O ORS conta as coordenadas a partir de 0 (o início): quem traduz o
    índice para a paragem é a rota (T3.21/T3.22)."""
    transporte(OrsFalso.responde(corpo=_erro_2010(MENSAGEM_2010.format(n=indice)), estado=404))
    assert _falha("direcoes").indice == indice


def test_a_fixture_do_2010(transporte, com_chave):
    """`direcoes-erro-2010.json` (fábrica → Marquês → rio → fábrica): o ponto
    no rio é a coordenada 2."""
    transporte(OrsFalso.responde(corpo=_ler_fixture("direcoes-erro-2010.json"), estado=404))
    falha = _falha("direcoes")
    assert (falha.tipo, falha.indice, falha.motivo) == ("ponto_sem_estrada", 2, "estado HTTP 404 (código 2010)")


@pytest.mark.parametrize("corpo", [_erro_2010(MENSAGEM_2010.format(n=2)), _ler_fixture("direcoes-erro-2010.json")])
def test_na_otimizacao_um_2010_da_a_mensagem_geral(transporte, com_chave, corpo):
    """Correção "T3.11": na otimização, o ponto fora da estrada dá a mensagem
    geral (o índice não diria que paragem é); o "Recalcular horas"
    identifica-a."""
    transporte(OrsFalso.responde(corpo=corpo, estado=404))
    falha = _falha("otimizar")
    assert (falha.tipo, falha.motivo, falha.indice) == ("indisponivel", "estado HTTP 404 (código 2010)", None)


@pytest.mark.parametrize("estado", [400, 401, 403, 404, 500, 502, 503, 599])
@pytest.mark.parametrize("servico", NOMES_SERVICOS)
def test_os_outros_estados_sao_indisponivel_com_o_estado(transporte, com_chave, servico, estado):
    corpo = _json({"error": {"code": 2099, "message": f"{CHAVE} {LAT_CANARIA}"}})
    transporte(OrsFalso.responde(corpo=corpo, estado=estado))
    falha = _falha(servico)
    assert (falha.tipo, falha.motivo, falha.indice) == ("indisponivel", f"estado HTTP {estado}", None)


@pytest.mark.parametrize(
    "corpo",
    [_json({"error": "Quota exceeded"}), _json({"error": "Access to this API has been disallowed"}), b""],
    ids=["quota", "chave inválida", "vazio"],
)
def test_o_403_e_indisponivel_quota_ou_chave(transporte, com_chave, corpo):
    """Correção "T3.11": o ORS dá 403 tanto com a quota diária esgotada como
    com a chave inválida (dossiê §8/§14)."""
    transporte(OrsFalso.responde(corpo=corpo, estado=403))
    falha = _falha("direcoes")
    assert (falha.tipo, falha.motivo) == ("indisponivel", "estado HTTP 403")


@pytest.mark.parametrize("estado", [400, 500])
@pytest.mark.parametrize(
    "corpo",
    [
        {"code": 3, "error": "Unfound route(s) from location [-9.123457,38.765432]"},
        {"code": 2, "error": "Invalid profile: car."},
        {"code": 1, "error": None},
        {"code": 3, "error": ["x"]},
    ],
    ids=["unfound route", "texto", "null", "lista"],
)
def test_o_erro_na_forma_do_vroom_e_indisponivel_sem_o_texto(transporte, com_chave, caplog, estado, corpo):
    """Correção "T3.11" (a): os erros da otimização vêm como
    `{"code": 3, "error": "<texto>"}`, com as coordenadas no texto."""
    transporte(OrsFalso.responde(corpo=_json(corpo), estado=estado))
    with caplog.at_level(logging.DEBUG):
        falha = _falha("otimizar")
    assert (falha.tipo, falha.motivo, falha.indice) == ("indisponivel", f"estado HTTP {estado}", None)
    for texto in COORDENADAS_CANARIAS + ("Unfound", "Invalid profile"):
        assert texto not in str(falha) and texto not in repr(falha) and texto not in caplog.text


# --- interpretar_erro: função pura ------------------------------------------------------------


@pytest.mark.parametrize(
    "estado, corpo, esperado",
    [
        (429, b"", ("limite", "estado HTTP 429", None)),
        (429, _erro_2010(MENSAGEM_2010.format(n=1)), ("limite", "estado HTTP 429", None)),
        (404, _erro_2010(MENSAGEM_2010.format(n=3)), ("ponto_sem_estrada", "estado HTTP 404 (código 2010)", 3)),
        (400, _erro_2010(MENSAGEM_2010_ANTIGA.format(n=0)), ("ponto_sem_estrada", "estado HTTP 400 (código 2010)", 0)),
        (404, _erro_2010("Specified COORDINATE 7: x"), ("ponto_sem_estrada", "estado HTTP 404 (código 2010)", 7)),
        (404, _erro_2010("could not find Point 12: x"), ("ponto_sem_estrada", "estado HTTP 404 (código 2010)", 12)),
        (404, _erro_2010("a\tcoordinate\t5: x"), ("ponto_sem_estrada", "estado HTTP 404 (código 2010)", 5)),
        (404, _erro_2010("Could not find routable point within a radius."), ("indisponivel", "estado HTTP 404", None)),
        (404, _erro_2010("specified coordinates 2 and 3"), ("indisponivel", "estado HTTP 404", None)),
        (404, _erro_2010("coordinate x3"), ("indisponivel", "estado HTTP 404", None)),
        (404, _erro_2010("coordinate ٣: x"), ("indisponivel", "estado HTTP 404", None)),
        (404, _erro_2010("coordinate 1234567: x"), ("indisponivel", "estado HTTP 404", None)),
        (404, _erro_2010("coordinate " + "9" * 5000), ("indisponivel", "estado HTTP 404", None)),
        (404, _erro_2010("coordinate 3", codigo=2009), ("indisponivel", "estado HTTP 404", None)),
        (404, _erro_2010("coordinate 3", codigo="2010"), ("indisponivel", "estado HTTP 404", None)),
        (404, _erro_2010("coordinate 3", codigo=2010.0), ("indisponivel", "estado HTTP 404", None)),
        (404, _erro_2010("coordinate 3", codigo=True), ("indisponivel", "estado HTTP 404", None)),
        (404, _json({"error": {"code": 2010, "message": None}}), ("indisponivel", "estado HTTP 404", None)),
        (404, _json({"error": {"code": 2010, "message": ["coordinate 3"]}}), ("indisponivel", "estado HTTP 404", None)),
        (404, _json({"error": {"code": 2010}}), ("indisponivel", "estado HTTP 404", None)),
        (404, _json({"error": "coordinate 3"}), ("indisponivel", "estado HTTP 404", None)),
        (404, _json({"code": 2010, "message": "coordinate 3"}), ("indisponivel", "estado HTTP 404", None)),
        (404, _json([{"error": {"code": 2010, "message": "coordinate 3"}}]), ("indisponivel", "estado HTTP 404", None)),
        (404, b'{"error": {"code": 2010, "message": "coordinate 3", "x": NaN}}', ("indisponivel", "estado HTTP 404", None)),
        (404, b"<html>coordinate 3</html>", ("indisponivel", "estado HTTP 404", None)),
        (500, _json({"code": 3, "error": "Unfound route(s) from location [-9.2,38.6]"}), ("indisponivel", "estado HTTP 500", None)),
        (403, _json({"error": "Quota exceeded"}), ("indisponivel", "estado HTTP 403", None)),
        (401, b"", ("indisponivel", "estado HTTP 401", None)),
        (502, b"", ("indisponivel", "estado HTTP 502", None)),
        (301, b"", ("indisponivel", "estado HTTP 301", None)),
    ],
)
def test_interpretar_erro(estado, corpo, esperado):
    falha = interpretar_erro(estado, corpo)
    assert isinstance(falha, FalhaOrs)
    assert (falha.tipo, falha.motivo, falha.indice) == esperado
    assert str(falha) == falha.motivo
    assert (falha.__cause__, falha.__context__) == (None, None)


def test_interpretar_erro_aceita_bytearray():
    assert interpretar_erro(404, bytearray(_erro_2010(MENSAGEM_2010.format(n=4)))).indice == 4


@pytest.mark.parametrize(
    "estado, corpo, erro",
    [
        ("404", b"", TypeError),
        (404.0, b"", TypeError),
        (True, b"", TypeError),
        (404, "texto", TypeError),
        (404, None, TypeError),
        (404, {"error": {}}, TypeError),
    ],
)
def test_interpretar_erro_com_entradas_estragadas_e_um_engano_do_codigo(estado, corpo, erro):
    with pytest.raises(erro):
        interpretar_erro(estado, corpo)


def test_interpretar_resposta():
    assert interpretar_resposta(200, b'{"a": 1}') == {"a": 1}
    with pytest.raises(FalhaOrs) as apanhada:
        interpretar_resposta(404, _erro_2010(MENSAGEM_2010.format(n=2)))
    assert (apanhada.value.tipo, apanhada.value.indice) == ("ponto_sem_estrada", 2)
    with pytest.raises(FalhaOrs) as apanhada:
        interpretar_resposta(404, _erro_2010(MENSAGEM_2010.format(n=2)), indice_2010=False)
    assert (apanhada.value.tipo, apanhada.value.indice) == ("indisponivel", None)
    assert apanhada.value.motivo == "estado HTTP 404 (código 2010)"
    assert (apanhada.value.__cause__, apanhada.value.__context__) == (None, None)


# --- enviar: o pedido sem interpretar (o gravador, T3.12) -------------------------------------


@pytest.mark.parametrize("servico, caminho", [("otimizacao", "/optimization"), ("direcoes", "/v2/directions/driving-car/json")])
def test_enviar_devolve_o_estado_e_o_corpo_em_bruto(transporte, com_chave, servico, caminho):
    corpo = _ler_fixture("direcoes-erro-2010.json")
    falso = transporte(OrsFalso.responde(corpo=corpo, estado=404))
    resposta = correr(ors.enviar(servico, PEDIDO_DIRECOES))
    assert resposta == RespostaOrs(404, corpo)
    assert (resposta.estado, resposta.corpo) == (404, corpo)
    assert [str(p.url) for p in falso.pedidos] == [BASE + caminho]


def test_enviar_um_servico_desconhecido_e_um_engano_do_codigo(transporte, com_chave):
    falso = transporte(OrsFalso.responde({}))
    with pytest.raises(ValueError):
        correr(ors.enviar("matrix", PEDIDO_DIRECOES))
    assert falso.pedidos == []


# --- A FalhaOrs -------------------------------------------------------------------------------


def test_a_falha_ors():
    falha = FalhaOrs("estado HTTP 404 (código 2010)", "ponto_sem_estrada", 2)
    assert isinstance(falha, Exception)
    assert str(falha) == falha.motivo == "estado HTTP 404 (código 2010)"
    assert (falha.tipo, falha.indice) == ("ponto_sem_estrada", 2)
    assert repr(falha) == "FalhaOrs(motivo='estado HTTP 404 (código 2010)', tipo='ponto_sem_estrada', indice=2)"
    assert FalhaOrs("sem chave", "sem_chave").indice is None
    assert ors.TIPOS == ("sem_chave", "indisponivel", "limite", "ponto_sem_estrada")


def test_a_falha_ors_so_aceita_os_tipos_conhecidos():
    with pytest.raises(ValueError):
        FalhaOrs("x", "outro")


# --- As falhas da rede ------------------------------------------------------------------------


@pytest.mark.parametrize("servico", NOMES_SERVICOS)
@pytest.mark.parametrize("excecao, nome", list(zip(FALHAS_DA_REDE, NOMES_DAS_FALHAS)), ids=NOMES_DAS_FALHAS)
def test_uma_falha_da_rede_e_indisponivel_so_com_o_tipo(transporte, com_chave, servico, excecao, nome):
    transporte(OrsFalso.falha(excecao))
    falha = _falha(servico)
    assert (falha.tipo, falha.motivo, falha.indice) == ("indisponivel", f"sem resposta ({nome})", None)
    assert (falha.__cause__, falha.__context__) == (None, None)
    for segredo in (CHAVE,) + COORDENADAS_CANARIAS:
        assert segredo not in str(falha) and segredo not in repr(falha)


def _porta_livre():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_sem_ninguem_a_escutar_na_porta_e_indisponivel(monkeypatch):
    """Com o transporte verdadeiro, numa porta livre de 127.0.0.1."""
    monkeypatch.setattr(ors, "_transporte", None)
    for nome in VARIAVEIS_DE_PROXY:
        monkeypatch.delenv(nome, raising=False)
    falha = _falha("direcoes", chave=CHAVE, url=f"http://127.0.0.1:{_porta_livre()}")
    assert (falha.tipo, falha.motivo) == ("indisponivel", "sem resposta (ConnectError)")


class _OrsLocal(BaseHTTPRequestHandler):
    """Um servidor HTTP em 127.0.0.1 que guarda o que recebe (o caminho, os
    cabeçalhos `Authorization` e o corpo) e responde um objeto JSON."""

    def do_POST(self):  # noqa: N802 — nome do BaseHTTPRequestHandler
        tamanho = int(self.headers.get("Content-Length", "0"))
        corpo = self.rfile.read(tamanho)
        self.server.recebidos.append((self.path, self.headers.get_all("Authorization"), corpo))
        resposta = b'{"routes": []}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resposta)))
        self.end_headers()
        self.wfile.write(resposta)

    def log_message(self, *argumentos):
        pass


def test_com_o_transporte_verdadeiro_a_chave_vai_so_no_authorization_e_nao_nos_registos(monkeypatch, caplog):
    """O httpx verdadeiro, com o httpx e o httpcore em DEBUG antes do pedido:
    o servidor recebe a chave só no cabeçalho, o caminho sem query e o corpo;
    os registos não têm a chave nem as coordenadas."""
    monkeypatch.setattr(ors, "_transporte", None)
    for nome in VARIAVEIS_DE_PROXY:
        monkeypatch.delenv(nome, raising=False)
    servidor = HTTPServer(("127.0.0.1", 0), _OrsLocal)
    servidor.recebidos = []
    fio = threading.Thread(target=servidor.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    fio.start()
    try:
        base = f"http://127.0.0.1:{servidor.server_address[1]}"
        with caplog.at_level(logging.DEBUG), caplog.at_level(logging.DEBUG, logger="httpx"), caplog.at_level(
            logging.DEBUG, logger="httpcore"
        ):
            logging.getLogger("httpx").setLevel(logging.DEBUG)
            logging.getLogger("httpcore").setLevel(logging.DEBUG)
            resposta = correr(ors.direcoes(PEDIDO_DIRECOES, chave=CHAVE, url=base))
    finally:
        servidor.shutdown()
        servidor.server_close()
        fio.join(timeout=2)
    assert resposta == {"routes": []}
    assert servidor.recebidos == [
        ("/v2/directions/driving-car/json", [CHAVE], json.dumps(PEDIDO_DIRECOES, allow_nan=False).encode("utf-8"))
    ]
    for segredo in (CHAVE,) + COORDENADAS_CANARIAS:
        assert segredo not in caplog.text


# --- A chave canária nos registos, em todos os caminhos ---------------------------------------


def _caminhos():
    """`(nome, fábrica do ORS falso, (tipo, motivo) esperado ou None)`. A
    fábrica dá um `OrsFalso` novo a cada teste: um só objeto partilhado pelos
    dois serviços somava os pedidos de um no outro."""
    corpo_2010 = _erro_2010(MENSAGEM_2010.format(n=1))
    eco = lambda p: _json({"error": {"code": 2099, "message": _segredos(p)}})  # noqa: E731
    caminhos = [
        ("sucesso", lambda: OrsFalso.responde({"code": 0}), None),
        ("lista", lambda: OrsFalso.responde(corpo=b"[]"), ("indisponivel", "resposta que não é um objeto JSON")),
        ("não JSON", lambda: OrsFalso.responde(corpo=lambda p: f"<html>{_segredos(p)}</html>".encode()),
         ("indisponivel", "resposta que não é JSON (JSONDecodeError)")),
        ("NaN", lambda: OrsFalso.responde(corpo=b'{"a": NaN}'), ("indisponivel", "resposta que não é JSON (ValueError)")),
        ("429", lambda: OrsFalso.responde(corpo=eco, estado=429), ("limite", "estado HTTP 429")),
        ("2010", lambda: OrsFalso.responde(corpo=corpo_2010, estado=404), None),
        ("2010 sem número", lambda: OrsFalso.responde(corpo=_erro_2010("sem numero -9.1234570 38.7654320"), estado=404),
         ("indisponivel", "estado HTTP 404")),
        ("401", lambda: OrsFalso.responde(corpo=eco, estado=401), ("indisponivel", "estado HTTP 401")),
        ("403", lambda: OrsFalso.responde(corpo=eco, estado=403), ("indisponivel", "estado HTTP 403")),
        ("500", lambda: OrsFalso.responde(corpo=eco, estado=500), ("indisponivel", "estado HTTP 500")),
        ("VROOM", lambda: OrsFalso.responde({"code": 3, "error": "Unfound route(s) from location [-9.123457,38.765432]"},
                                            estado=500), ("indisponivel", "estado HTTP 500")),
        ("301", lambda: OrsFalso.responde(corpo=eco, estado=301, cabecalhos={"Location": BASE + "/x"}),
         ("indisponivel", "estado HTTP 301")),
    ]
    caminhos += [
        (nome, lambda excecao=excecao: OrsFalso.falha(excecao), ("indisponivel", f"sem resposta ({nome})"))
        for excecao, nome in zip(FALHAS_DA_REDE, NOMES_DAS_FALHAS)
    ]
    return caminhos


CAMINHOS = _caminhos()


def _registos_fora_do_ciclo(caplog):
    """Os registos que não são do próprio ciclo de eventos: o `correr()` dos
    duplos cria um ciclo novo, e o asyncio regista "Using selector: …" em
    DEBUG ao criá-lo. Esse registo não é do cliente."""
    return [registo for registo in caplog.records if registo.name != "asyncio"]


def _sem_segredos_nos_registos(caplog, falha=None):
    for segredo in (CHAVE,) + COORDENADAS_CANARIAS:
        assert segredo not in caplog.text
        for registo in caplog.records:
            assert segredo not in registo.getMessage()
            assert segredo not in str(registo.args)
        if falha is not None:
            assert segredo not in str(falha)
            assert segredo not in repr(falha)
            assert segredo not in falha.motivo


@pytest.mark.parametrize("servico", NOMES_SERVICOS)
@pytest.mark.parametrize("nome, fabrica, esperado", CAMINHOS, ids=[c[0] for c in CAMINHOS])
def test_a_chave_canaria_nunca_vai_para_os_registos(transporte, com_chave, caplog, servico, nome, fabrica, esperado):
    """Risco R1: com o `caplog` em DEBUG no root, no `httpx` e no `httpcore`,
    a chave e as coordenadas do corpo nunca aparecem nos registos nem na
    falha (`str`, `repr`, `motivo`)."""
    falso = transporte(fabrica())
    falha = None
    with caplog.at_level(logging.DEBUG), caplog.at_level(logging.DEBUG, logger="httpx"), caplog.at_level(
        logging.DEBUG, logger="httpcore"
    ):
        try:
            _chamar(servico)
        except FalhaOrs as exc:
            falha = exc
    if nome == "sucesso":
        assert falha is None
    elif nome == "2010":
        esperado = ("ponto_sem_estrada", "estado HTTP 404 (código 2010)") if servico == "direcoes" else (
            "indisponivel", "estado HTTP 404 (código 2010)")
    if esperado is not None:
        assert (falha.tipo, falha.motivo) == esperado
    assert len(falso.pedidos) == 1
    _sem_segredos_nos_registos(caplog, falha)


@pytest.mark.parametrize("ambiente", [{}, {"CRM_ORS_URL": "http://exemplo.invalid"}], ids=["sem chave", "URL recusado"])
def test_sem_pedido_tambem_nao_ha_segredos_nos_registos(transporte, monkeypatch, caplog, ambiente):
    for nome, valor in ambiente.items():
        monkeypatch.setenv(nome, valor)
        monkeypatch.setenv(ors.VARIAVEL_CHAVE, CHAVE)
    falso = transporte(OrsFalso.responde({}))
    with caplog.at_level(logging.DEBUG):
        falha = _falha()
    assert falso.pedidos == []
    _sem_segredos_nos_registos(caplog, falha)
    assert _registos_fora_do_ciclo(caplog) == []


def test_cada_pedido_volta_a_por_o_httpx_e_o_httpcore_em_warning(transporte, com_chave):
    """Se alguém puser o httpx em DEBUG (para depurar outra integração), o
    pedido ao ORS volta a pô-lo em WARNING antes de pedir (como a Geoapify)."""
    transporte(OrsFalso.responde({}))
    registos = [logging.getLogger(nome) for nome in ("httpx", "httpcore")]
    antes = [registo.level for registo in registos]
    try:
        for registo in registos:
            registo.setLevel(logging.DEBUG)
        _chamar("otimizar")
        assert [registo.level for registo in registos] == [logging.WARNING, logging.WARNING]
    finally:
        for registo, nivel in zip(registos, antes):
            registo.setLevel(nivel)


# --- O código do módulo (varrimento) ----------------------------------------------------------


def _arvore():
    return ast.parse(FICHEIRO.read_text(encoding="utf-8"))


def test_o_ors_py_nao_regista_nada_nem_imprime():
    """Quem chama (a rota, T3.21) regista só o `motivo`. O módulo nunca
    escreve registos: nem `logging` nem `print`."""
    arvore = _arvore()
    importados = {
        alias.name.split(".")[0]
        for no in ast.walk(arvore)
        if isinstance(no, (ast.Import, ast.ImportFrom))
        for alias in no.names
    } | {no.module.split(".")[0] for no in ast.walk(arvore) if isinstance(no, ast.ImportFrom) and no.module}
    assert "logging" not in importados
    chamadas = {no.func.id for no in ast.walk(arvore) if isinstance(no, ast.Call) and isinstance(no.func, ast.Name)}
    assert "print" not in chamadas


def test_o_ors_py_nunca_segue_redirecoes_nem_mete_a_chave_no_url():
    arvore = _arvore()
    valores = [
        palavra.value
        for no in ast.walk(arvore)
        if isinstance(no, ast.Call)
        for palavra in no.keywords
        if palavra.arg == "follow_redirects"
    ]
    assert valores and all(isinstance(v, ast.Constant) and v.value is False for v in valores)
    textos = [no.value for no in ast.walk(arvore) if isinstance(no, ast.Constant) and isinstance(no.value, str)]
    assert not any("api_key" in texto for texto in textos)


def test_o_ors_py_lanca_as_falhas_sem_causa():
    """Nenhum `raise … from …` (a falha nunca arrasta a exceção do httpx, que
    pode trazer o pedido)."""
    assert [no for no in ast.walk(_arvore()) if isinstance(no, ast.Raise) and no.cause is not None] == []
