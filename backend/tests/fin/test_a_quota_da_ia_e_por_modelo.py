"""**Quando a quota de um modelo acaba, bate-se à porta seguinte.**

A quota gratuita do Gemini é 20 pedidos por dia **e por modelo**. O Financeiro
usava UM só, e ainda por cima o alias `gemini-flash-latest`, que aponta sempre
para o de quota mais apertada — por isso ficava sem leituras a meio do dia e
os extratos não entravam.

O módulo das plataformas já resolvia isto (plataformas/leitura.py:147-167) e
deixou a medição escrita: com o primeiro modelo esgotado, os outros respondiam
à primeira, no mesmo instante. Esperar não devolve quota DIÁRIA — mudar de
porta devolve.

Este teste defende as duas metades: à primeira volta muda-se de modelo **sem
dormir**, e só se todos recusarem é que se espera (aí já não é a quota do dia,
é o limite por minuto).
"""
import os

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402


class RespostaFalsa:
    def __init__(self, status, corpo=None):
        self.status_code = status
        self._corpo = corpo or {}

    def json(self):
        return self._corpo


BOA = {"candidates": [{"finishReason": "STOP",
                       "content": {"parts": [{"text": '{"ok": true}'}]}}]}
CHEIA = {"error": {"message": "You exceeded your current quota, limit: 20, retry in 58.8s"}}


class ClienteFalso:
    """Um httpx.Client de mentira que guarda a que portas se bateu."""

    def __init__(self, respostas, urls):
        self._respostas = respostas
        self._urls = urls

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, json=None):
        self._urls.append(url)
        return self._respostas.pop(0)


@pytest.fixture
def sem_dormir(monkeypatch):
    dormidas = []
    monkeypatch.setattr(server._time, "sleep", lambda s: dormidas.append(s))
    monkeypatch.setenv("GEMINI_API_KEY", "chave-de-teste")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    return dormidas


def _monta(monkeypatch, respostas):
    urls = []
    monkeypatch.setattr(server.httpx, "Client",
                        lambda timeout=None: ClienteFalso(respostas, urls))
    return urls


def test_o_modelo_por_omissao_nao_e_o_alias_latest():
    # `-latest` aponta sempre para o modelo de quota mais apertada, e muda
    # debaixo dos pés. Tem de ser um nome fixo.
    assert "latest" not in server._fin_gemini_modelos()[0]


def test_ha_mais_do_que_uma_porta():
    modelos = server._fin_gemini_modelos()
    assert len(modelos) >= 3, "com um modelo só, 20 leituras por dia é o tecto"
    assert len(set(modelos)) == len(modelos), "modelo repetido gasta uma volta à toa"


def test_com_o_primeiro_esgotado_usa_o_seguinte_sem_esperar(monkeypatch, sem_dormir):
    urls = _monta(monkeypatch, [RespostaFalsa(429, CHEIA), RespostaFalsa(200, BOA)])

    raw, finish = server._fin_gemini_call(b"%PDF-1.4", "prompt", 2048, 60)

    assert finish == "STOP" and raw == '{"ok": true}'
    assert sem_dormir == [], "dormiu à espera de quota DIÁRIA — isso não a devolve"
    assert len(urls) == 2
    assert server._fin_gemini_modelos()[0] in urls[0]
    assert server._fin_gemini_modelos()[1] in urls[1]


def test_so_espera_quando_todas_as_portas_recusam(monkeypatch, sem_dormir):
    modelos = server._fin_gemini_modelos()
    # Uma volta inteira a 429 (sem dormir), e na segunda volta o primeiro cede.
    respostas = [RespostaFalsa(429, CHEIA) for _ in modelos] + [RespostaFalsa(200, BOA)]
    _monta(monkeypatch, respostas)

    raw, finish = server._fin_gemini_call(b"%PDF-1.4", "prompt", 2048, 60)

    assert finish == "STOP"
    assert sem_dormir, "todas recusaram: aí é o limite por minuto e vale a pena esperar"


def test_a_variavel_de_ambiente_continua_a_mandar(monkeypatch, sem_dormir):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    modelos = server._fin_gemini_modelos()

    assert modelos[0] == "gemini-3.5-flash-lite"
    assert modelos.count("gemini-3.5-flash-lite") == 1
