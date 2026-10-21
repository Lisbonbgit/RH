"""`GET /api/crm/morada/inversa` — a morada sugerida do ponto do GPS, pedida
pelo servidor à Geoapify com a chave do servidor, que nunca vai para o browser
nem para os registos (plano T2.15; dossiê §6 e §8). A pesquisa de moradas
(`GET /api/crm/morada/pesquisa`) saiu na G18 do plano do mapa Google: é a da
própria Google, no browser; aqui fica a prova de que a rota dá 404.

Porta, com os nomes de lá nos docstrings e nos `ids`, dos casos da inversa e do
cliente de tests/Unit/Http/Controladores/MoradaControladorTest.php,
tests/Integration/Api/MoradaTest.php e
tests/Integration/Servicos/ClienteHttpCurlTest.php do CRM autónomo (etiqueta
`referencia-standalone`). Os casos da pesquisa saíram com ela (G18); os que só
a usavam para chegar à Geoapify (o cliente, as variáveis, os registos) passaram
para a inversa, e os casos do regex `NUMERO` que só a pesquisa tinha entraram
nos 422 da inversa. Adaptações ao portal:

- A rede é um `httpx.MockTransport` em `geoapify._transporte` (molde de
  faturacao/pontos_app.py), no lugar do `ClienteHttpFalso`. Por omissão, os
  testes instalam uma Geoapify "proibida", que regista e falha se for chamada:
  nenhum teste chega à Geoapify verdadeira.
- O "servidor de respostas gravadas" (tests/fixtures/servidor.php, porta
  8099) é aqui um `http.server` em 127.0.0.1 numa porta livre, com o cliente
  httpx verdadeiro (MoradaTest e ClienteHttpCurlTest). Só o loopback: nada
  sai do Mac.
- Sem sessão, o portal responde o 403 herdado ("Not authenticated"), e não o
  401 `nao_autenticado` do autónomo; o motorista (403 `sem_permissao`) e quem
  não é membro (403 `sem_acesso_crm`) também não chegam à Geoapify.
- O portal não tem sessões PHP trancadas (JWT): o caso
  `aSessaoLibertaSeAntesDeChamarAGeoapify` / `enquantoEsperaPelaGeoapify…`
  passa a "enquanto espera pela Geoapify, o servidor continua a responder"
  (o ciclo de eventos não fica bloqueado).
- O `Cache-Control: no-store, private` não se porta (a mesma diferença
  assumida da T2.9).
- As respostas de sucesso vêm diretas (objeto ou `null`), sem o
  `{"dados": …}` do autónomo (plano §4).

Decisões fixadas aqui (correções do plano, linhas "T2.15" e "T1.3 / T2.15"):

- `lat` e `lng` leem-se como texto opcional e validam-se no código do CRM
  (nunca o 422 em lista do FastAPI): o número é o regex `NUMERO` do
  autónomo, por isso `1e2`, `nan` e `inf` não são números (422);
- a chave e o URL base leem-se do ambiente a cada pedido; só a chave vazia
  conta como "sem chave" (como o `$chave === ''`);
- qualquer falha do pedido (estado fora de 2xx, rede, tempo, URL mal escrito,
  resposta que não é JSON pelo `json_decode` do PHP) → 503
  `morada_indisponivel`, com um registo só com o tipo da exceção ou o código
  HTTP — nunca o URL, a chave ou o ponto.
"""
import asyncio
import json
import logging
import socket
import socketserver
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl, unquote, urlsplit

import httpx
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import crm
import crm.db
import faturacao.auth
from crm import morada
from crm.auth import ESCRITORIO, membro_crm_atual
from crm.pedidos import corpo_json
from crm.servicos import geoapify
from crm.servicos.geoapify import (
    FalhaServicoExterno,
    ler_json,
    normalizar_inversa,
    obter_json,
    url_inversa,
)
from faturacao.auth import utilizador_atual

from .duplos import BaseFalsa, correr

PESQUISA_URL = "/api/crm/morada/pesquisa"
INVERSA_URL = "/api/crm/morada/inversa"
ADMIN_LOCAL = "admin.local@example.com"

# Os do MoradaControladorTest.php.
BASE = "http://127.0.0.1:8099/geoapify"
CHAVE = "chave-teste-servidor"

GRAVADAS = Path(__file__).parent / "fixtures" / "geoapify"

INVERSA_INDISPONIVEL = {
    "detail": {"codigo": "morada_indisponivel", "mensagem": "Morada sugerida indisponível — escreva a morada à mão."}
}
SEM_PERMISSAO = {"detail": {"codigo": "sem_permissao", "mensagem": "Sem permissão para esta ação."}}
SEM_ACESSO = {"detail": {"codigo": "sem_acesso_crm", "mensagem": "Sem acesso ao CRM."}}

NUMERO_LAT = "A latitude tem de ser um número."
NUMERO_LNG = "A longitude tem de ser um número."
FORA = "Fora de Portugal"

RESULTADO = {
    "country_code": "pt",
    "city": "Lisboa",
    "postcode": "1100-048",
    "street": "Rua Augusta",
    "housenumber": "24",
    "lon": -9.13712,
    "lat": 38.70921,
    "formatted": "Rua Augusta 24, 1100-048 Lisboa, Portugal",
}

SUGESTAO = {
    "rotulo": "Rua Augusta 24, 1100-048 Lisboa, Portugal",
    "morada": "Rua Augusta 24",
    "codigo_postal": "1100-048",
    "localidade": "Lisboa",
    "lat": 38.70921,
    "lng": -9.13712,
}

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c63606060f80f0001040100a0f6b6b00000000049454e44ae426082"
)

VARIAVEIS_DE_PROXY = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")

USERS = [
    {"id": "u-admin", "email": ADMIN_LOCAL, "name": "Administrador Principal", "role": "admin",
     "password": "$2b$12$hash-do-admin"},
    {"id": "u-ana", "email": "ana@example.com", "name": "Ana Reis", "role": "contabilista",
     "password": "$2b$12$hash-da-ana"},
    {"id": "u-ze", "email": "ze@example.com", "name": "Zé Silva", "role": "colaborador",
     "password": "$2b$12$hash-do-ze"},
    {"id": "u-alv", "email": "alvaro@example.com", "name": "Álvaro Costa", "role": "gerente",
     "password": "$2b$12$hash-do-alvaro"},
    {"id": "u-bea", "email": "bea@example.com", "name": "Beatriz Lopes", "role": "colaborador",
     "password": "$2b$12$hash-da-bea"},
]
MEMBROS = [
    {"id": "m-ana", "user_id": "u-ana", "perfil": "admin", "criado_em": "2026-10-03T09:00:00Z"},
    {"id": "m-ze", "user_id": "u-ze", "perfil": "utilizador", "criado_em": "2026-10-01T09:00:00Z"},
    {"id": "m-alv", "user_id": "u-alv", "perfil": "motorista", "criado_em": "2026-10-02T09:00:00Z"},
    {"id": "m-apagada", "user_id": "u-apagada", "perfil": "utilizador", "criado_em": "2026-09-30T09:00:00Z"},
]

ADMIN_MASTER = {"user_id": "u-admin", "email": ADMIN_LOCAL, "role": "admin"}
ANA_ADMIN_DO_CRM = {"user_id": "u-ana", "email": "ana@example.com", "role": "contabilista"}
ZE_UTILIZADOR = {"user_id": "u-ze", "email": "ze@example.com", "role": "colaborador"}
ALVARO_MOTORISTA = {"user_id": "u-alv", "email": "alvaro@example.com", "role": "gerente"}
BEA_NAO_MEMBRO = {"user_id": "u-bea", "email": "bea@example.com", "role": "colaborador"}


# --- A Geoapify falsa (o ClienteHttpFalso do autónomo) --------------------------------------


class GeoapifyFalsa:
    """O `ClienteHttpFalso` do autónomo como handler de um `httpx.MockTransport`:
    responde sempre o mesmo (ou falha) e guarda os pedidos recebidos.

    A `proibida()` regista o pedido e falha com uma exceção: nos testes "sem
    chamar a Geoapify" confere-se sempre também que `pedidos == []` (o 503 da
    exceção, sozinho, não bastava, porque é o que esses testes esperam)."""

    def __init__(self, responder):
        self.pedidos = []
        self._responder = responder

    def __call__(self, pedido):
        self.pedidos.append(pedido)
        return self._responder(pedido)

    @property
    def urls(self):
        return [str(p.url) for p in self.pedidos]

    @classmethod
    def responde(cls, dados=None, estado=200, corpo=None, cabecalhos=None):
        """Responde `dados` em JSON (ou o `corpo` em bytes, ou o que a função
        `corpo(pedido)` devolver) com o `estado`."""

        def _responder(pedido):
            conteudo = corpo(pedido) if callable(corpo) else corpo
            if conteudo is None:
                conteudo = json.dumps(dados).encode("utf-8")
            return httpx.Response(estado, content=conteudo, headers=cabecalhos or {})

        return cls(_responder)

    @classmethod
    def falha(cls, excecao):
        """Lança `excecao(pedido)` a cada pedido, como uma Geoapify em baixo."""

        def _responder(pedido):
            raise excecao(pedido)

        return cls(_responder)

    @classmethod
    def proibida(cls):
        def _responder(pedido):
            raise AssertionError("Não se devia ter chamado a Geoapify.")

        return cls(_responder)


def _base(membros=MEMBROS, users=USERS):
    return BaseFalsa({"crm_membros": list(membros), "users": list(users)})


@pytest.fixture
def sessao(monkeypatch):
    """`sessao(utilizador, geo, rede=False)` → um TestClient com o router do
    CRM, o utilizador do portal já autenticado e a Geoapify `geo` (por
    omissão, a proibida). A chave e o URL base são os do autónomo; `rede=True`
    usa o transporte verdadeiro do httpx (para o servidor de respostas em
    127.0.0.1)."""
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    monkeypatch.setenv(geoapify.VARIAVEL_CHAVE_SERVIDOR, CHAVE)
    monkeypatch.setenv(geoapify.VARIAVEL_URL, BASE)
    for nome in VARIAVEIS_DE_PROXY:
        monkeypatch.delenv(nome, raising=False)

    def _montar(utilizador=ZE_UTILIZADOR, geo=None, rede=False):
        geo = geo if geo is not None else GeoapifyFalsa.proibida()
        monkeypatch.setattr(geoapify, "_transporte", None if rede else httpx.MockTransport(geo))
        base = _base()
        monkeypatch.setattr(crm.db, "obter_db", lambda: base)
        app = FastAPI()
        app.include_router(crm.router)
        app.dependency_overrides[utilizador_atual] = lambda: dict(utilizador)
        cliente = TestClient(app)
        cliente.geo = geo
        return cliente

    return _montar


def _inversa(lat, lng):
    return {"lat": lat, "lng": lng}


def _rota(caminho):
    achadas = [
        r for r in crm.router.routes
        if getattr(r, "path", None) == caminho and "GET" in getattr(r, "methods", ())
    ]
    assert len(achadas) == 1, f"GET {caminho} não está (uma só vez) no router do CRM"
    return achadas[0]


def _dependencias(rota):
    encontrados = []

    def _procura(dependente):
        for d in dependente.dependencies:
            encontrados.append(d.call)
            _procura(d)

    _procura(rota.dependant)
    return encontrados


def _parametros(url):
    """Os parâmetros do URL, por ordem, como pares."""
    return parse_qsl(urlsplit(url).query, keep_blank_values=True, strict_parsing=True)


def _gravada(ficheiro):
    return json.loads((GRAVADAS / ficheiro).read_text(encoding="utf-8"))


# --- As rotas ------------------------------------------------------------------------------


def test_a_rota_da_inversa_existe_e_vive_em_crm_morada():
    rota = _rota(INVERSA_URL)
    assert rota.methods == {"GET"}
    assert rota.endpoint.__module__ == "crm.morada"


def test_a_inversa_e_do_escritorio_com_uma_so_guarda_e_sem_corpo():
    """A guarda de perfil é a única dependência (correções, linha "T1.3 /
    T2.15"): os parâmetros não são dependências e nunca se lê um corpo."""
    dependencias = _dependencias(_rota(INVERSA_URL))
    assert membro_crm_atual in dependencias
    assert [d for d in dependencias if hasattr(d, "perfis_crm")] == [ESCRITORIO]
    assert corpo_json not in dependencias
    assert _rota(INVERSA_URL).body_field is None


@pytest.mark.parametrize(
    "utilizador", [ADMIN_MASTER, ANA_ADMIN_DO_CRM, ZE_UTILIZADOR], ids=["admin master", "admin", "utilizador"]
)
def test_a_pesquisa_de_moradas_saiu_e_da_o_404_do_fastapi_com_sessao(sessao, utilizador):
    """G18 do plano do mapa Google: a pesquisa de moradas é a da Google, no
    browser, e a Geoapify fica só para a morada sugerida do ponto do GPS. Com
    a sessão do escritório e um pedido que antes era válido, `GET
    /morada/pesquisa` é o "Not Found" do FastAPI (nenhum método a serve) e a
    Geoapify nunca é chamada."""
    assert [r for r in crm.router.routes if getattr(r, "path", None) == PESQUISA_URL] == []
    cliente = sessao(utilizador)
    r = cliente.get(PESQUISA_URL, params={"texto": "Rua Augusta", "lat": "38.7223", "lng": "-9.1393"})
    assert (r.status_code, r.json()) == (404, {"detail": "Not Found"})
    assert cliente.geo.pedidos == []


def test_o_modulo_da_morada_so_tem_a_inversa():
    """O que era só da pesquisa saiu de crm/morada.py (G18); a mensagem da
    inversa fica, igual à do morada.js (test_consistencia_frontend.py)."""
    for nome in ("pesquisa", "texto_da_pesquisa", "bias", "TEXTO_MINIMO", "TEXTO_MAXIMO",
                 "MENSAGEM_TEXTO_CURTO", "MENSAGEM_TEXTO_LONGO", "PESQUISA_INDISPONIVEL"):
        assert not hasattr(morada, nome), nome
    assert morada.INVERSA_INDISPONIVEL == INVERSA_INDISPONIVEL["detail"]["mensagem"]


# --- MoradaControladorTest.php -------------------------------------------------------------


def test_sem_chave_do_servidor_a_inversa_da_503_sem_chamar_a_geoapify(sessao, monkeypatch):
    """`semChaveDoServidorAInversaDa503SemChamarAGeoapify`."""
    monkeypatch.delenv(geoapify.VARIAVEL_CHAVE_SERVIDOR)
    cliente = sessao()
    r = cliente.get(INVERSA_URL, params=_inversa("38.7075", "-9.1364"))
    assert (r.status_code, r.json()) == (503, INVERSA_INDISPONIVEL)
    assert cliente.geo.pedidos == []


def test_sem_chave_um_ponto_fora_de_portugal_continua_a_dar_422(sessao, monkeypatch):
    """O mesmo na inversa: primeiro o pedido, depois a chave."""
    monkeypatch.delenv(geoapify.VARIAVEL_CHAVE_SERVIDOR)
    cliente = sessao()
    r = cliente.get(INVERSA_URL, params=_inversa("95", "-9.1364"))
    assert (r.status_code, r.json()["detail"]["campos"]) == (422, {"lat": FORA})
    assert cliente.geo.pedidos == []


def test_a_inversa_pede_a_morada_do_ponto_e_devolve_a_primeira_valida(sessao):
    """`aInversaPedeAMoradaDoPontoEDevolveAPrimeiraValida`."""
    cliente = sessao(geo=GeoapifyFalsa.responde({"results": [RESULTADO]}))
    r = cliente.get(INVERSA_URL, params=_inversa("38.7075", "-9.1364"))
    assert (r.status_code, r.json()) == (200, SUGESTAO)
    assert list(r.json()) == list(SUGESTAO)
    assert cliente.geo.urls == [url_inversa(BASE, CHAVE, 38.7075, -9.1364)]


def test_sem_morada_valida_a_inversa_devolve_null(sessao):
    """`semMoradaValidaAInversaDevolveNull`."""
    r = sessao(geo=GeoapifyFalsa.responde({"results": []})).get(INVERSA_URL, params=_inversa("38.7075", "-9.1364"))
    assert (r.status_code, r.text) == (200, "null")


def test_a_inversa_aceita_os_limites_de_portugal_continental(sessao):
    """`aInversaAceitaOsLimitesDePortugalContinental`."""
    cliente = sessao(geo=GeoapifyFalsa.responde({"results": []}))
    cliente.get(INVERSA_URL, params=_inversa("36.8", "-6.1"))
    cliente.get(INVERSA_URL, params=_inversa("42.2", "-9.6"))
    assert cliente.geo.urls == [url_inversa(BASE, CHAVE, 36.8, -6.1), url_inversa(BASE, CHAVE, 42.2, -9.6)]


@pytest.mark.parametrize(
    "parametros, campos",
    [
        ({}, {"lat": NUMERO_LAT, "lng": NUMERO_LNG}),
        ({"lng": "-9.1364"}, {"lat": NUMERO_LAT}),
        ({"lat": "38.7075", "lng": ""}, {"lng": NUMERO_LNG}),
        ({"lat": "abc", "lng": "-9.1364"}, {"lat": NUMERO_LAT}),
        ({"lat": "3.87075e1", "lng": "-9.1364"}, {"lat": NUMERO_LAT}),
        ({"lat": "38,7075", "lng": "-9.1364"}, {"lat": NUMERO_LAT}),
        ({"lat[]": "38.7075", "lng": "-9.1364"}, {"lat": NUMERO_LAT}),
        ({"lat": "91", "lng": "-9.1364"}, {"lat": FORA}),
        ({"lat": "32.6669", "lng": "-16.9241"}, {"lat": FORA, "lng": FORA}),
        ({"lat": "40.4168", "lng": "-3.7038"}, {"lng": FORA}),
        ({"lat": "42.2001", "lng": "-8.5"}, {"lat": FORA}),
        # Correções do plano, linha "T2.15": `lat=1e2` dá 422 na inversa.
        ({"lat": "1e2", "lng": "-9.1364"}, {"lat": NUMERO_LAT}),
        ({"lat": "nan", "lng": "inf"}, {"lat": NUMERO_LAT, "lng": NUMERO_LNG}),
        ({"lat": "-0", "lng": "-9.1364"}, {"lat": FORA}),
        ({"lat": "38.7075", "lng": "abc"}, {"lng": NUMERO_LNG}),
        ({"lat": "0038.7075", "lng": "-0009.1364"}, {"lat": NUMERO_LAT, "lng": NUMERO_LNG}),
        ({"lat": "1000", "lng": "-9.1364"}, {"lat": NUMERO_LAT}),
        ({"lat": "38.7075", "lng": "-9.1364\n"}, {"lng": NUMERO_LNG}),
        # G18: os casos do regex `NUMERO` que só a pesquisa (que saiu) tinha.
        ({"lat": "38.7075"}, {"lng": NUMERO_LNG}),
        ({"lat": " 38.7075", "lng": "-9.1364"}, {"lat": NUMERO_LAT}),
        ({"lat": "38.7075", "lng": "-Infinity"}, {"lng": NUMERO_LNG}),
        ({"lat": "+38.7075", "lng": "-9.1364"}, {"lat": NUMERO_LAT}),
        ({"lat": "38.", "lng": "-9.1364"}, {"lat": NUMERO_LAT}),
        ({"lat": ".5", "lng": "-9.1364"}, {"lat": NUMERO_LAT}),
        ({"lat": "٣٨.٧", "lng": "-9.1364"}, {"lat": NUMERO_LAT}),
    ],
    ids=["sem ponto", "sem latitude", "longitude vazia", "latitude com letras", "notação científica",
         "vírgula decimal", "lista (lat[]=…)", "latitude acima de 90", "Madeira", "Madrid",
         "logo a norte da caixa", "1e2", "nan e inf", "-0", "longitude com letras",
         "quatro algarismos que davam um ponto em Portugal", "quatro algarismos", "quebra de linha no fim",
         "sem longitude", "espaço à frente", "-Infinity", "sinal +", "ponto sem casas", "sem a parte inteira",
         "algarismos árabes"],
)
def test_um_ponto_invalido_ou_fora_de_portugal_na_inversa_da_422_sem_chamar_a_geoapify(sessao, parametros, campos):
    """`umPontoInvalidoOuForaDePortugalNaInversaDa422SemChamarAGeoapify`: o
    ponto tem de estar em Portugal continental, o único sítio onde pode
    ficar uma loja. Os erros vêm pela ordem lat, lng. Os últimos casos são
    do regex `NUMERO` (^-?[0-9]{1,3}(\\.[0-9]+)?$, só algarismos ASCII e sem
    a quebra de linha que o `$` do Python aceitava)."""
    cliente = sessao()
    r = cliente.get(INVERSA_URL, params=parametros)
    assert r.status_code == 422
    assert r.json() == {
        "detail": {"codigo": "validacao", "mensagem": "Verifique os campos assinalados.", "campos": campos}
    }
    assert list(r.json()["detail"]["campos"]) == list(campos)
    assert cliente.geo.pedidos == []


def test_uma_falha_da_geoapify_na_inversa_da_503(sessao):
    """`umaFalhaDaGeoapifyNaInversaDa503`."""
    geo = GeoapifyFalsa.falha(lambda p: httpx.ConnectError("sem ligação", request=p))
    r = sessao(geo=geo).get(INVERSA_URL, params=_inversa("38.7075", "-9.1364"))
    assert (r.status_code, r.json()) == (503, INVERSA_INDISPONIVEL)
    assert len(geo.pedidos) == 1


def test_enquanto_espera_pela_geoapify_o_servidor_continua_a_responder(monkeypatch):
    """`aSessaoLibertaSeAntesDeChamarAGeoapify` e
    `enquantoEsperaPelaGeoapifyASessaoNaoFicaTrancada`, no portal: não há
    sessões PHP trancadas, mas um cliente que bloqueasse o ciclo de eventos
    fazia os outros pedidos esperar pela Geoapify (até 5 s). A Geoapify só
    responde depois de "outro pedido" correr enquanto ela espera."""
    monkeypatch.setenv(geoapify.VARIAVEL_CHAVE_SERVIDOR, CHAVE)
    monkeypatch.setenv(geoapify.VARIAVEL_URL, BASE)

    async def cenario():
        entrou, libertar = asyncio.Event(), asyncio.Event()

        async def geoapify_lenta(pedido):
            entrou.set()
            await asyncio.wait_for(libertar.wait(), 2)
            return httpx.Response(200, json={"results": []})

        monkeypatch.setattr(geoapify, "_transporte", httpx.MockTransport(geoapify_lenta))

        async def outro_pedido():
            await asyncio.wait_for(entrou.wait(), 2)
            libertar.set()
            return "servido"

        pedido = morada.inversa(membro={}, lat="38.7075", lng="-9.1364")
        return await asyncio.gather(pedido, outro_pedido())

    assert correr(cenario()) == [None, "servido"]


# --- Pormenores do pedido: o texto, os parâmetros e as variáveis -----------------------------


def test_um_parametro_repetido_vale_o_ultimo(sessao):
    """Como o `$_GET` do PHP: `?lat=abc&lat=38.7075` pede o ponto do último, e
    `?lat=38.7075&lat=abc` dá 422."""
    cliente = sessao(geo=GeoapifyFalsa.responde({"results": []}))
    r = cliente.get(INVERSA_URL, params=[("lat", "abc"), ("lat", "38.7075"), ("lng", "-9.1364")])
    assert r.status_code == 200
    assert cliente.geo.urls == [url_inversa(BASE, CHAVE, 38.7075, -9.1364)]
    r = cliente.get(INVERSA_URL, params=[("lat", "38.7075"), ("lat", "abc"), ("lng", "-9.1364")])
    assert (r.status_code, r.json()["detail"]["campos"]) == (422, {"lat": NUMERO_LAT})
    assert len(cliente.geo.pedidos) == 1


def test_a_geoapify_recebe_um_get_que_aceita_json_sem_referer(sessao):
    """O `CURLOPT_HTTPGET` e o `Accept: application/json` do
    ClienteHttpCurl; o servidor não manda `Referer` (é a chave do navegador
    da Google que é restrita por referrer, não a do servidor)."""
    cliente = sessao(geo=GeoapifyFalsa.responde({"results": []}))
    cliente.get(INVERSA_URL, params=_inversa("38.7075", "-9.1364"))
    [pedido] = cliente.geo.pedidos
    assert pedido.method == "GET"
    assert pedido.headers["accept"] == "application/json"
    assert "referer" not in pedido.headers
    assert pedido.content == b""


def test_os_nomes_das_variaveis_e_o_url_por_omissao():
    assert geoapify.VARIAVEL_CHAVE_SERVIDOR == "CRM_GEOAPIFY_CHAVE_SERVIDOR"
    assert geoapify.VARIAVEL_URL == "CRM_GEOAPIFY_URL"
    assert geoapify.URL_POR_OMISSAO == "https://api.geoapify.com"


@pytest.mark.parametrize("valor", [None, ""], ids=["sem a variável", "variável vazia"])
def test_sem_o_url_base_pede_a_geoapify(sessao, monkeypatch, valor):
    """`CRM_GEOAPIFY_URL` é opcional (dossiê §9). A Geoapify continua falsa:
    só se confere o URL que se lhe pede."""
    if valor is None:
        monkeypatch.delenv(geoapify.VARIAVEL_URL)
    else:
        monkeypatch.setenv(geoapify.VARIAVEL_URL, valor)
    cliente = sessao(geo=GeoapifyFalsa.responde({"results": []}))
    cliente.get(INVERSA_URL, params=_inversa("38.7075", "-9.1364"))
    assert cliente.geo.urls == [url_inversa("https://api.geoapify.com", CHAVE, 38.7075, -9.1364)]


def test_a_chave_e_o_url_leem_se_a_cada_pedido(sessao, monkeypatch):
    """Não à importação: mudar o `.env` não pede outro código (molde de
    faturacao/pontos_app.py; o `config_mapa` lê assim a chave do navegador
    da Google)."""
    ponto = _inversa("38.7075", "-9.1364")
    cliente = sessao(geo=GeoapifyFalsa.responde({"results": []}))
    cliente.get(INVERSA_URL, params=ponto)
    monkeypatch.setenv(geoapify.VARIAVEL_CHAVE_SERVIDOR, "segunda-chave")
    monkeypatch.setenv(geoapify.VARIAVEL_URL, "https://outra.example/")
    cliente.get(INVERSA_URL, params=ponto)
    monkeypatch.delenv(geoapify.VARIAVEL_CHAVE_SERVIDOR)
    r = cliente.get(INVERSA_URL, params=ponto)
    assert r.status_code == 503
    assert cliente.geo.urls == [
        url_inversa(BASE, CHAVE, 38.7075, -9.1364),
        url_inversa("https://outra.example", "segunda-chave", 38.7075, -9.1364),
    ]


def test_so_a_chave_vazia_conta_como_sem_chave(sessao, monkeypatch):
    """Como o `$chave === ''` do autónomo e a chave do navegador da Google no
    `config_mapa`: uma chave só com espaços vai, codificada, e a Geoapify
    recusa-a (→ 503)."""
    monkeypatch.setenv(geoapify.VARIAVEL_CHAVE_SERVIDOR, "")
    cliente = sessao()
    assert cliente.get(INVERSA_URL, params=_inversa("38.7075", "-9.1364")).status_code == 503
    assert cliente.geo.pedidos == []

    monkeypatch.setenv(geoapify.VARIAVEL_CHAVE_SERVIDOR, " ")
    cliente = sessao(geo=GeoapifyFalsa.responde({"results": []}))
    cliente.get(INVERSA_URL, params=_inversa("38.7075", "-9.1364"))
    assert cliente.geo.urls == [url_inversa(BASE, " ", 38.7075, -9.1364)]
    assert cliente.geo.urls[0].endswith("&apiKey=%20")


def test_a_geoapify_recebe_os_parametros_da_t2_14_e_a_chave_do_servidor(sessao, monkeypatch):
    """O pedido tem exatamente os parâmetros da inversa da T2.14, por esta
    ordem, e o `apiKey` é o `CRM_GEOAPIFY_CHAVE_SERVIDOR`."""
    monkeypatch.setenv(geoapify.VARIAVEL_CHAVE_SERVIDOR, "a chave/do+servidor")
    cliente = sessao(geo=GeoapifyFalsa.responde({"results": []}))
    cliente.get(INVERSA_URL, params=_inversa("38.7075", "-9.1364"))
    [url] = cliente.geo.urls
    assert url.startswith(BASE + "/v1/geocode/reverse?")
    assert _parametros(url) == [
        ("lat", "38.7075"),
        ("lon", "-9.1364"),
        ("lang", "pt"),
        ("format", "json"),
        ("apiKey", "a chave/do+servidor"),
    ]


# --- Perfis e sessão -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "utilizador", [ADMIN_MASTER, ANA_ADMIN_DO_CRM, ZE_UTILIZADOR], ids=["admin master", "admin", "utilizador"]
)
def test_o_escritorio_pede_a_morada_sugerida(sessao, utilizador):
    """A morada sugerida não é só para o admin (o Rui do MoradaTest é
    utilizador)."""
    cliente = sessao(utilizador, geo=GeoapifyFalsa.responde({"results": [RESULTADO]}))
    assert cliente.get(INVERSA_URL, params=_inversa("38.7075", "-9.1364")).json() == SUGESTAO


@pytest.mark.parametrize(
    "utilizador, esperado",
    [(ALVARO_MOTORISTA, SEM_PERMISSAO), (BEA_NAO_MEMBRO, SEM_ACESSO)],
    ids=["motorista (F4)", "não é membro"],
)
@pytest.mark.parametrize(
    "parametros", [_inversa("38.7075", "-9.1364"), _inversa("abc", "")], ids=["inversa", "inversa inválida"]
)
def test_sem_o_perfil_do_escritorio_da_403_sem_chamar_a_geoapify(sessao, utilizador, esperado, parametros):
    """A guarda responde antes de tudo (nem o 422 do pedido)."""
    cliente = sessao(utilizador)
    r = cliente.get(INVERSA_URL, params=parametros)
    assert (r.status_code, r.json()) == (403, esperado)
    assert cliente.geo.pedidos == []


SEGREDO = "segredo-de-teste-crm-morada"
AGORA_TOKEN = int(time.time())


def _token(user_id, email="qualquer@example.com", role="colaborador"):
    dados = {"user_id": user_id, "email": email, "role": role, "iat": AGORA_TOKEN, "exp": AGORA_TOKEN + 3600}
    return jwt.encode(dados, SEGREDO, algorithm="HS256")


def _cabecalho(user_id, **kw):
    return {"Authorization": f"Bearer {_token(user_id, **kw)}"}


@pytest.fixture
def portal(monkeypatch):
    """A sessão verdadeira do portal (`faturacao.auth`), com a base falsa e a
    Geoapify falsa que responde com a Rua Augusta."""
    monkeypatch.setenv("JWT_SECRET", SEGREDO)
    monkeypatch.setenv("ADMIN_EMAIL", ADMIN_LOCAL)
    monkeypatch.setenv(geoapify.VARIAVEL_CHAVE_SERVIDOR, CHAVE)
    monkeypatch.setenv(geoapify.VARIAVEL_URL, BASE)
    geo = GeoapifyFalsa.responde({"results": [RESULTADO]})
    monkeypatch.setattr(geoapify, "_transporte", httpx.MockTransport(geo))
    base = _base()
    monkeypatch.setattr(faturacao.auth, "obter_db", lambda: base)
    monkeypatch.setattr(crm.db, "obter_db", lambda: base)
    app = FastAPI()
    app.include_router(crm.router)
    cliente = TestClient(app)
    cliente.geo = geo
    return cliente


def test_sem_sessao_da_o_403_herdado_sem_chamar_a_geoapify(portal):
    """`semSessaoDa401SemChamarAGeoapify`, com o 403 herdado do portal."""
    r = portal.get(INVERSA_URL, params=_inversa("38.7075", "-9.1364"))
    assert (r.status_code, r.json()) == (403, {"detail": "Not authenticated"})
    assert portal.geo.pedidos == []


def test_uma_conta_apagada_da_401_sem_chamar_a_geoapify(portal):
    r = portal.get(INVERSA_URL, params=_inversa("38.7075", "-9.1364"), headers=_cabecalho("u-apagada"))
    assert (r.status_code, r.json()) == (401, {"detail": "Sessão terminada"})
    assert portal.geo.pedidos == []


def test_com_a_sessao_verdadeira_o_utilizador_pede_a_morada_sugerida(portal):
    r = portal.get(INVERSA_URL, params=_inversa("38.7075", "-9.1364"), headers=_cabecalho("u-ze"))
    assert (r.status_code, r.json()) == (200, SUGESTAO)
    assert portal.geo.urls == [url_inversa(BASE, CHAVE, 38.7075, -9.1364)]


# --- O cliente: ClienteHttpCurlTest.php ----------------------------------------------------


@pytest.fixture
def transporte(monkeypatch):
    """`transporte(geo)` instala a Geoapify falsa no cliente; devolve-a."""
    for nome in VARIAVEIS_DE_PROXY:
        monkeypatch.delenv(nome, raising=False)

    def _instalar(geo):
        monkeypatch.setattr(geoapify, "_transporte", httpx.MockTransport(geo))
        return geo

    return _instalar


URL_INVERSA = url_inversa(BASE, CHAVE, 38.7075, -9.1364)


def _falha(url=URL_INVERSA):
    """A `FalhaServicoExterno` que `obter_json(url)` lança (o teste falha se
    não lançar)."""
    with pytest.raises(FalhaServicoExterno) as apanhada:
        correr(obter_json(url))
    return apanhada.value


def test_devolve_o_json_descodificado(transporte):
    """`devolveOJsonDescodificado`."""
    corpo = (GRAVADAS / "reverse-praca-comercio.json").read_bytes()
    transporte(GeoapifyFalsa.responde(corpo=corpo))
    assert correr(obter_json(URL_INVERSA)) == _gravada("reverse-praca-comercio.json")


def test_faz_um_get_com_os_parametros_do_url(transporte):
    """`fazUmGetComOsParametrosDoUrl`: o URL vai tal e qual (o httpx não o
    volta a codificar)."""
    geo = transporte(GeoapifyFalsa.responde({"results": []}))
    url = url_inversa(BASE, "c a/n+ária ~ €!*'()", 38.7, -9.1)
    correr(obter_json(url))
    assert [(p.method, str(p.url)) for p in geo.pedidos] == [("GET", url)]


@pytest.mark.parametrize(
    "estado, corpo, motivo",
    [
        (500, b'{"statusCode":500,"error":"Internal Server Error","message":"Falha simulada"}', "estado HTTP 500"),
        (404, b'{"statusCode":404,"error":"Not Found","message":"Rota desconhecida"}', "estado HTTP 404"),
        (200, PNG_1X1, "resposta que não é JSON"),
        (401, b'{"statusCode":401,"error":"Unauthorized","message":"Invalid apiKey"}', "estado HTTP 401"),
        (301, b"", "estado HTTP 301"),
        (300, b'{"results":[]}', "estado HTTP 300"),
        (204, b"", "resposta que não é JSON"),
        (200, b'"texto"', "resposta que não é JSON"),
        (200, b'{"results": NaN}', "resposta que não é JSON"),
    ],
    ids=["estado 500", "estado 404", "não é JSON (um PNG)", "estado 401 (chave recusada)",
         "redireção 301 (não se segue)", "estado 300", "204 sem corpo", "JSON que não é objeto nem lista",
         "NaN (o json_decode do PHP recusa)"],
)
def test_uma_resposta_que_nao_serve_e_uma_falha(transporte, estado, corpo, motivo):
    """`umaRespostaQueNaoServeEUmaFalha`: estado diferente de 2xx ou um corpo
    que não é JSON. O motivo diz só o código HTTP ou o tipo."""
    transporte(GeoapifyFalsa.responde(estado=estado, corpo=corpo))
    assert _falha().motivo.startswith(motivo)


@pytest.mark.parametrize("estado", [200, 201, 299])
def test_qualquer_estado_2xx_serve(transporte, estado):
    """O `$estado < 200 || $estado > 299` do ClienteHttpCurl."""
    transporte(GeoapifyFalsa.responde({"results": []}, estado=estado))
    assert correr(obter_json(URL_INVERSA)) == {"results": []}


def test_nao_segue_redirecionamentos(transporte):
    """`CURLOPT_FOLLOWLOCATION => false`: uma redireção é uma falha, e o
    sítio para onde apontava nunca recebe a chave."""
    geo = transporte(GeoapifyFalsa.responde(
        estado=302, corpo=b"", cabecalhos={"Location": "https://outro.example/?apiKey=" + CHAVE}
    ))
    assert _falha().motivo == "estado HTTP 302"
    assert geo.urls == [URL_INVERSA]


FALHAS_DA_REDE = [
    lambda p: httpx.ReadTimeout(f"tempo esgotado em {p.url}", request=p),
    lambda p: httpx.ConnectTimeout(f"tempo esgotado a ligar a {p.url}", request=p),
    lambda p: httpx.ConnectError(f"sem ligação a {p.url}", request=p),
    lambda p: httpx.ReadError(f"leitura falhou em {p.url}", request=p),
    lambda p: httpx.RemoteProtocolError(f"protocolo partido em {p.url}", request=p),
    lambda p: httpx.TooManyRedirects(f"redireções a mais em {p.url}", request=p),
    lambda p: httpx.DecodingError(f"gzip partido em {p.url}", request=p),
    lambda p: httpx.UnsupportedProtocol(f"protocolo desconhecido em {p.url}", request=p),
    lambda p: httpx.InvalidURL(f"URL inválido: {p.url}"),
    lambda p: RuntimeError(f"avaria inesperada com {p.url}"),
]
NOMES_DAS_FALHAS = ["ReadTimeout", "ConnectTimeout", "ConnectError", "ReadError", "RemoteProtocolError",
                    "TooManyRedirects", "DecodingError", "UnsupportedProtocol", "InvalidURL", "RuntimeError"]


@pytest.mark.parametrize("excecao, nome", list(zip(FALHAS_DA_REDE, NOMES_DAS_FALHAS)), ids=NOMES_DAS_FALHAS)
def test_uma_falha_da_rede_e_uma_falha_so_com_o_tipo(transporte, excecao, nome):
    """Correções do plano, linha "T2.15 (chave fora dos registos)": a base
    `httpx.HTTPError` e mais — o `httpx.InvalidURL` não herda dela (httpx
    0.28) e um erro inesperado também não pode levar o URL para os registos
    (molde de faturacao/pontos_app.py, que apanha `Exception`)."""
    transporte(GeoapifyFalsa.falha(excecao))
    assert _falha().motivo == f"sem resposta ({nome})"


def test_a_mensagem_da_falha_nao_traz_o_url_nem_a_chave(transporte):
    """`aMensagemDaFalhaNaoTrazOUrlNemAChave`, e a falha não arrasta a
    exceção do httpx (cuja mensagem traz o URL) como causa ou contexto: um
    `logger.exception` mais acima também não a escrevia."""
    url = url_inversa(BASE, "chave-teste-secreta", 38.7075, -9.1364)
    for excecao in FALHAS_DA_REDE:
        transporte(GeoapifyFalsa.falha(excecao))
        falha = _falha(url)
        assert "chave-teste-secreta" not in str(falha)
        assert "geocode/reverse" not in str(falha)
        assert (falha.__cause__, falha.__context__) == (None, None)
    for estado in (500, 200):
        transporte(GeoapifyFalsa.responde(estado=estado, corpo=lambda p: str(p.url).encode()))
        falha = _falha(url)
        assert "chave-teste-secreta" not in str(falha)
        assert (falha.__cause__, falha.__context__) == (None, None)


def _porta_livre():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_sem_ninguem_a_escutar_na_porta_e_uma_falha(monkeypatch):
    """`semNinguemAEscutarNaPortaEUmaFalha`, com o transporte verdadeiro."""
    monkeypatch.setattr(geoapify, "_transporte", None)
    for nome in VARIAVEIS_DE_PROXY:
        monkeypatch.delenv(nome, raising=False)
    falha = _falha(f"http://127.0.0.1:{_porta_livre()}/v1/geocode/reverse")
    assert falha.motivo == "sem resposta (ConnectError)"


def test_um_servidor_que_nao_responde_a_tempo_e_uma_falha(monkeypatch):
    """`umServidorQueNaoRespondeATempoEUmaFalha`: aceita a ligação (o sistema
    completa-a na fila do socket), mas nunca responde. Com o transporte
    verdadeiro e o tempo limite de leitura a 0,5 s."""
    monkeypatch.setattr(geoapify, "_transporte", None)
    monkeypatch.setattr(geoapify, "TEMPO_LIMITE", httpx.Timeout(0.5, connect=0.5))
    for nome in VARIAVEIS_DE_PROXY:
        monkeypatch.delenv(nome, raising=False)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as servidor:
        servidor.bind(("127.0.0.1", 0))
        servidor.listen(1)
        porta = servidor.getsockname()[1]
        inicio = time.monotonic()
        falha = _falha(f"http://127.0.0.1:{porta}/v1/geocode/reverse")
        assert falha.motivo == "sem resposta (ReadTimeout)"
        assert time.monotonic() - inicio < 2.0


def test_os_tempos_limite_por_defeito_sao_5s_e_3s_para_ligar():
    """`osTemposLimitePorDefeitoSao5sE3sParaLigar`. O `CURLOPT_TIMEOUT_MS` do
    autónomo era o pedido inteiro; os do httpx são por fase, por isso há
    também um limite total de 5 s."""
    assert geoapify.TEMPO_LIMITE == httpx.Timeout(5.0, connect=3.0)
    assert (geoapify.TEMPO_LIMITE.connect, geoapify.TEMPO_LIMITE.read) == (3.0, 5.0)
    assert geoapify.TEMPO_TOTAL_SEGUNDOS == 5.0


def test_o_pedido_inteiro_tem_um_limite_de_tempo(transporte, monkeypatch):
    """Uma Geoapify que vai respondendo devagar nunca esgota o tempo de cada
    leitura do httpx; o limite total corta-a (como o `CURLOPT_TIMEOUT_MS`)."""
    monkeypatch.setattr(geoapify, "TEMPO_TOTAL_SEGUNDOS", 0.05)

    async def devagar(pedido):
        await asyncio.sleep(2)
        return httpx.Response(200, json={"results": []})

    transporte(devagar)
    inicio = time.monotonic()
    assert _falha().motivo == "sem resposta (TimeoutError)"
    assert time.monotonic() - inicio < 1.0


def test_o_cliente_usa_o_tempo_limite_e_nao_segue_redirecionamentos(transporte, monkeypatch):
    """O cliente httpx é criado com o `TEMPO_LIMITE` do módulo (lido a cada
    pedido) e sem seguir redireções."""
    criados = []
    original = httpx.AsyncClient

    def espiao(*args, **kwargs):
        criados.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(geoapify.httpx, "AsyncClient", espiao)
    transporte(GeoapifyFalsa.responde({"results": []}))
    correr(obter_json(URL_INVERSA))
    assert len(criados) == 1
    assert criados[0]["timeout"] == httpx.Timeout(5.0, connect=3.0)
    assert criados[0]["follow_redirects"] is False


# --- A resposta lida como o json_decode do PHP -------------------------------------------------

ANINHADAS_511 = b"[" * 511 + b"]" * 511
ANINHADAS_512 = b"[" * 512 + b"]" * 512


@pytest.mark.parametrize(
    "corpo, esperado",
    [
        (b'{"results": []}', {"results": []}),
        (b"[]", []),
        (b" [] ", []),
        (b"\t\n\r{}\n", {}),
        (b"[1e400]", [float("inf")]),
        ('["\\ud83d\\ude00", "\\uDBFF\\uDFFF"]'.encode(), ["😀", "\U0010ffff"]),
        (b'{"a":1,"a":2}', {"a": 2}),
        (b'["\\u0000"]', ["\x00"]),
        ('{"localidade": "Óbidos"}'.encode(), {"localidade": "Óbidos"}),
        (b"[[[[1]]]]", [[[[1]]]]),
    ],
    ids=["objeto", "lista vazia", "espaços nas pontas", "tab e quebras", "1e400 é infinito", "pares UTF-16",
         "chave repetida fica a última", "\\u0000", "UTF-8", "níveis"],
)
def test_le_o_json_como_o_json_decode_do_php(corpo, esperado):
    assert ler_json(corpo) == esperado


def test_511_niveis_ainda_se_leem():
    """O `json_decode(…, true, 512)` do PHP 8.4 aceita 511 níveis e recusa
    512 (conferido no PHP 8.4.26)."""
    dados = ler_json(ANINHADAS_511)
    niveis = 0
    while isinstance(dados, list):
        niveis += 1
        dados = dados[0] if dados else None
    assert niveis == 511
    assert ler_json(b'{"a":' * 510 + b"{}" + b"}" * 510) is not None


@pytest.mark.parametrize(
    "corpo",
    [
        b"", b" ", b"1", b'"x"', b"null", b"true",
        b'{"a":NaN}', b"[Infinity]", b"[-Infinity]",
        b"\xef\xbb\xbf{}",
        b'"\\ud800"', b'["\\ud800"]', b'["\\udc00"]', b'{"\\ud800":1}', b'["\\uD800\\u0041"]',
        b'["\xff"]', b"\xc0\x80", b'["\xed\xa0\x80"]', b'["\xf4\x90\x80\x80"]',
        "{}".encode("utf-16"),
        b"[01]", b'["\x01"]', b"\x00[]", b"[]\x00", b"[1,]", b"\x0c[]", b"[TRUE]", b"[.5]", b"[+1]",
        ANINHADAS_512,
        b'{"a":' * 511 + b"{}" + b"}" * 511,
        b"[" * 100000 + b"]" * 100000,
    ],
    ids=["vazio", "só um espaço", "número", "texto", "null", "true",
         "NaN", "Infinity", "-Infinity", "BOM do UTF-8",
         "surrogate sozinho", "surrogate alto sozinho numa lista", "surrogate baixo sozinho",
         "surrogate sozinho numa chave", "surrogate alto seguido de outra coisa",
         "byte que não é UTF-8", "UTF-8 sobrelongo", "surrogate em UTF-8", "acima de U+10FFFF",
         "UTF-16 (o json.loads do Python aceitava-o em bytes)",
         "zero à esquerda", "carácter de controlo", "NUL antes", "NUL depois", "vírgula a mais", "form feed",
         "TRUE", "sem a parte inteira", "sinal +",
         "512 listas", "512 objetos", "100 000 níveis (RecursionError no Python)"],
)
def test_o_que_o_json_decode_do_php_recusa_e_um_value_error(corpo):
    """O `json_decode($corpo, true, 512, JSON_THROW_ON_ERROR)` + `is_array`
    do ClienteHttpCurl, conferido no PHP 8.4.26. O `json` do Python aceitava
    NaN, Infinity, surrogates sozinhos (que depois partiam a resposta com
    500), UTF-16 e mais níveis; e com níveis a mais lançava RecursionError,
    que não é um ValueError."""
    with pytest.raises(ValueError):
        ler_json(corpo)


# --- A chave fora dos registos (desenho §4.1; correções, linha "T2.15") ----------------------

CANARIA = "canaria-servidor-0123456789"
# O ponto do GPS de quem pede também nunca vai para os registos: um ponto em
# Lisboa com algarismos que não estão em mais lado nenhum (nem na RESULTADO,
# nem nas respostas gravadas), tal como vai no URL (6 casas, sem zeros).
PONTO_CANARIO = ("38.712345", "-9.154321")


def test_os_registos_do_httpx_e_do_httpcore_ficam_em_warning():
    """O httpx regista em INFO cada pedido com o URL inteiro (e a chave)."""
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


def test_basta_importar_o_crm_para_os_registos_ficarem_em_warning():
    """Num processo novo, sem nenhum pedido: o `server.py` faz
    `logging.basicConfig(level=INFO)` e importa o CRM no arranque, por isso o
    httpx não chega a registar o primeiro pedido à Geoapify (nem os de
    outros módulos do portal)."""
    codigo = (
        "import logging; logging.basicConfig(level=logging.INFO); import crm; "
        "print(logging.getLogger('httpx').level, logging.getLogger('httpcore').level)"
    )
    saida = subprocess.run(
        [sys.executable, "-c", codigo], cwd=Path(crm.__file__).parent.parent,
        capture_output=True, text=True, timeout=60, check=True,
    )
    assert saida.stdout.split() == [str(logging.WARNING), str(logging.WARNING)]


def _sem_canarias(caplog, resposta):
    for segredo in (CANARIA, "canaria-servidor", *PONTO_CANARIO):
        assert segredo not in caplog.text
        assert segredo not in resposta.text
    for registo in caplog.records:
        assert CANARIA not in str(registo.args)
        assert CANARIA not in registo.getMessage()


def _registos_do_crm(caplog):
    return [(r.name, r.levelname, r.getMessage()) for r in caplog.records if r.name.startswith("crm")]


def test_a_chave_nao_vai_para_os_registos_num_sucesso(sessao, monkeypatch, caplog):
    """Com `caplog` em DEBUG e uma chave canária: nem o pedido do httpx nem
    o ponto pedido ficam escritos."""
    monkeypatch.setenv(geoapify.VARIAVEL_CHAVE_SERVIDOR, CANARIA)
    cliente = sessao(geo=GeoapifyFalsa.responde({"results": [RESULTADO]}))
    with caplog.at_level(logging.DEBUG):
        r = cliente.get(INVERSA_URL, params=_inversa(*PONTO_CANARIO))
    assert (r.status_code, r.json()) == (200, SUGESTAO)
    assert CANARIA in cliente.geo.urls[0]
    assert all(coordenada in cliente.geo.urls[0] for coordenada in PONTO_CANARIO)
    _sem_canarias(caplog, r)
    assert _registos_do_crm(caplog) == []


def test_mesmo_com_o_httpx_posto_em_debug_a_chave_nao_vai_para_os_registos(sessao, monkeypatch, caplog):
    """Se alguém puser o httpx em DEBUG (para depurar outra integração), o
    pedido à Geoapify volta a pô-lo em WARNING antes de pedir."""
    monkeypatch.setenv(geoapify.VARIAVEL_CHAVE_SERVIDOR, CANARIA)
    cliente = sessao(geo=GeoapifyFalsa.responde({"results": []}))
    registos = [logging.getLogger(nome) for nome in ("httpx", "httpcore")]
    antes = [registo.level for registo in registos]
    try:
        # setLevel, e não mexer no atributo: limpa a cache do isEnabledFor.
        for registo in registos:
            registo.setLevel(logging.DEBUG)
        with caplog.at_level(logging.DEBUG):
            r = cliente.get(INVERSA_URL, params=_inversa(*PONTO_CANARIO))
        assert r.status_code == 200
        _sem_canarias(caplog, r)
        assert [registo.level for registo in registos] == [logging.WARNING, logging.WARNING]
    finally:
        for registo, nivel in zip(registos, antes):
            registo.setLevel(nivel)


FALHAS_PARA_OS_REGISTOS = [
    (GeoapifyFalsa.responde, {"estado": 500, "corpo": lambda p: f'{{"message": "{p.url}"}}'.encode()},
     "estado HTTP 500"),
    (GeoapifyFalsa.responde, {"estado": 401, "corpo": lambda p: f'{{"message": "{p.url}"}}'.encode()},
     "estado HTTP 401"),
    (GeoapifyFalsa.responde, {"estado": 301, "corpo": b"", "cabecalhos": {"Location": f"https://x.example/?k={CANARIA}"}},
     "estado HTTP 301"),
    (GeoapifyFalsa.responde, {"corpo": lambda p: f"não é JSON {p.url}".encode()}, "resposta que não é JSON"),
    (GeoapifyFalsa.responde, {"corpo": b'{"results": NaN}'}, "resposta que não é JSON"),
] + [(GeoapifyFalsa.falha, {"excecao": e}, f"sem resposta ({n})") for e, n in zip(FALHAS_DA_REDE, NOMES_DAS_FALHAS)]
IDS_FALHAS_PARA_OS_REGISTOS = ["estado 500", "estado 401", "redireção 301", "não é JSON", "NaN"] + NOMES_DAS_FALHAS


@pytest.mark.parametrize("fabrica, argumentos, motivo", FALHAS_PARA_OS_REGISTOS, ids=IDS_FALHAS_PARA_OS_REGISTOS)
def test_cada_falha_da_503_e_um_registo_so_com_o_tipo_ou_o_codigo(
    sessao, monkeypatch, caplog, fabrica, argumentos, motivo
):
    """Correções do plano, linha "T2.15 (chave fora dos registos)": 503 com a
    mensagem exata, um só registo `[crm]` (WARNING) com o motivo — o tipo da
    exceção ou o código HTTP — e nunca `str(exc)`, o URL, a chave ou o
    ponto, nem no registo nem no `detail`."""
    monkeypatch.setenv(geoapify.VARIAVEL_CHAVE_SERVIDOR, CANARIA)
    cliente = sessao(geo=fabrica(**argumentos))
    with caplog.at_level(logging.DEBUG):
        r = cliente.get(INVERSA_URL, params=_inversa(*PONTO_CANARIO))
    assert (r.status_code, r.json()) == (503, INVERSA_INDISPONIVEL)
    _sem_canarias(caplog, r)
    [(nome, nivel, mensagem)] = _registos_do_crm(caplog)
    assert (nome, nivel) == ("crm.morada", "WARNING")
    assert mensagem.startswith(f"[crm] morada: a Geoapify falhou na inversa — {motivo}")


@pytest.mark.parametrize(
    "url_base, motivo",
    [("http://127.0.0.1:8O99/geoapify", "InvalidURL"), ("api.geoapify.com", "UnsupportedProtocol"),
     ("http://[::1", "InvalidURL")],
    ids=["porta com letras", "sem http(s)://", "IPv6 por fechar"],
)
def test_um_url_base_mal_escrito_da_503_sem_a_chave_nos_registos(sessao, monkeypatch, caplog, url_base, motivo):
    """Um erro de dedo no `CRM_GEOAPIFY_URL` rebenta ao montar o pedido (o
    `InvalidURL` não é um `httpx.HTTPError`) e a mensagem do httpx traz o URL
    com a chave. Com o transporte verdadeiro: nada chega a sair."""
    monkeypatch.setenv(geoapify.VARIAVEL_CHAVE_SERVIDOR, CANARIA)
    monkeypatch.setenv(geoapify.VARIAVEL_URL, url_base)
    cliente = sessao(rede=True)
    with caplog.at_level(logging.DEBUG):
        r = cliente.get(INVERSA_URL, params=_inversa(*PONTO_CANARIO))
    assert (r.status_code, r.json()) == (503, INVERSA_INDISPONIVEL)
    _sem_canarias(caplog, r)
    [(_, _, mensagem)] = _registos_do_crm(caplog)
    assert mensagem == f"[crm] morada: a Geoapify falhou na inversa — sem resposta ({motivo})"


def test_sem_chave_nao_ha_registo(sessao, monkeypatch, caplog):
    """Sem chave é o normal em local (dossiê §8): 503 sem encher os
    registos."""
    monkeypatch.delenv(geoapify.VARIAVEL_CHAVE_SERVIDOR)
    with caplog.at_level(logging.DEBUG):
        r = sessao().get(INVERSA_URL, params=_inversa("38.7075", "-9.1364"))
    assert r.status_code == 503
    assert _registos_do_crm(caplog) == []


# --- MoradaTest.php: com o servidor de respostas e o cliente verdadeiro ------------------------


class _ServidorLocal(ThreadingHTTPServer):
    """Um `ThreadingHTTPServer` sem o `socket.getfqdn` do `HTTPServer.server_bind`:
    essa pesquisa de DNS inversa do 127.0.0.1 chegou a demorar 35 s nesta
    máquina (e podia sair do Mac)."""

    daemon_threads = True

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


@pytest.fixture
def respostas():
    """O servidor de respostas gravadas do autónomo (tests/fixtures/
    servidor.php), em 127.0.0.1 numa porta livre:

    - `/geoapify/v1/geocode/reverse`: a gravada da inversa, seja qual for o
      ponto;
    - o resto → 404 (o autocomplete da pesquisa saiu na G18; um URL base
      errado também cai aqui).

    Guarda o último pedido `{metodo, caminho, parametros, referer}`."""
    ultimo = {"pedido": None}

    class Pedidos(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — o nome é o do http.server
            partes = urlsplit(self.path)
            caminho = unquote(partes.path)
            parametros = dict(parse_qsl(partes.query, keep_blank_values=True))
            ultimo["pedido"] = {
                "metodo": "GET",
                "caminho": caminho,
                "parametros": parametros,
                "referer": self.headers.get("Referer"),
            }
            if caminho == "/geoapify/v1/geocode/reverse":
                self._responder(200, (GRAVADAS / "reverse-praca-comercio.json").read_bytes())
            else:
                self._responder(404, b'{"statusCode":404,"error":"Not Found","message":"Rota desconhecida"}')

        def _responder(self, estado, corpo):
            self.send_response(estado)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def log_message(self, formato, *args):
            pass

    servidor = _ServidorLocal(("127.0.0.1", 0), Pedidos)
    fio = threading.Thread(target=servidor.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    fio.start()
    try:
        yield SimpleNamespace(base=f"http://127.0.0.1:{servidor.server_port}/geoapify", ultimo=ultimo)
    finally:
        servidor.shutdown()
        servidor.server_close()
        fio.join(2)


@pytest.fixture
def rui(sessao, respostas, monkeypatch):
    """O Rui (perfil utilizador) do MoradaTest, com a Geoapify do servidor de
    respostas e o cliente httpx verdadeiro."""
    monkeypatch.setenv(geoapify.VARIAVEL_URL, respostas.base)
    cliente = sessao(ZE_UTILIZADOR, rede=True)
    cliente.ultimo = respostas.ultimo
    return cliente


def _pedido(caminho, parametros):
    return {"metodo": "GET", "caminho": caminho, "parametros": parametros, "referer": None}


def test_a_inversa_devolve_a_morada_do_ponto(rui):
    """`aInversaDevolveAMoradaDoPonto`."""
    r = rui.get(INVERSA_URL + "?lat=38.7075&lng=-9.1364")
    assert r.status_code == 200, r.text
    assert r.json() == normalizar_inversa(_gravada("reverse-praca-comercio.json"))
    assert r.json()["localidade"] == "Lisboa"
    assert rui.ultimo["pedido"] == _pedido(
        "/geoapify/v1/geocode/reverse",
        {"lat": "38.7075", "lon": "-9.1364", "lang": "pt", "format": "json", "apiKey": CHAVE},
    )


@pytest.mark.parametrize(
    "consulta, campos",
    [("lat=abc&lng=-9.1364", {"lat": NUMERO_LAT}), ("lng=-9.1364", {"lat": NUMERO_LAT}),
     ("lat=95&lng=-9.1364", {"lat": FORA})],
    ids=["latitude com letras", "sem latitude", "latitude fora de Portugal"],
)
def test_uma_latitude_invalida_na_inversa_da_422_sem_chamar_a_geoapify(rui, consulta, campos):
    """`umaLatitudeInvalidaNaInversaDa422SemChamarAGeoapify`."""
    r = rui.get(INVERSA_URL + "?" + consulta)
    assert r.status_code == 422
    assert r.json() == {
        "detail": {"codigo": "validacao", "mensagem": "Verifique os campos assinalados.", "campos": campos}
    }
    assert rui.ultimo["pedido"] is None


def test_com_a_rede_verdadeira_a_chave_nao_vai_para_os_registos(sessao, respostas, monkeypatch, caplog):
    """O mesmo da chave canária, agora com o httpx e o httpcore verdadeiros
    (ligação, cabeçalhos, leitura) em DEBUG: um sucesso e uma falha (um URL
    base que o servidor de respostas não conhece dá 404)."""
    monkeypatch.setenv(geoapify.VARIAVEL_URL, respostas.base)
    monkeypatch.setenv(geoapify.VARIAVEL_CHAVE_SERVIDOR, CANARIA)
    cliente = sessao(rede=True)
    with caplog.at_level(logging.DEBUG):
        r = cliente.get(INVERSA_URL, params=_inversa(*PONTO_CANARIO))
        monkeypatch.setenv(geoapify.VARIAVEL_URL, respostas.base + "/avariada")
        falha = cliente.get(INVERSA_URL, params=_inversa(*PONTO_CANARIO))
    assert (r.status_code, falha.status_code) == (200, 503)
    assert falha.json() == INVERSA_INDISPONIVEL
    assert respostas.ultimo["pedido"]["caminho"] == "/geoapify/avariada/v1/geocode/reverse"
    assert respostas.ultimo["pedido"]["parametros"]["apiKey"] == CANARIA
    _sem_canarias(caplog, r)
    _sem_canarias(caplog, falha)
    assert [m for _, _, m in _registos_do_crm(caplog)] == [
        "[crm] morada: a Geoapify falhou na inversa — estado HTTP 404"
    ]
