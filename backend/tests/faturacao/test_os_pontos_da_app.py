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


def test_um_URL_com_a_porta_estragada_da_503_e_nao_um_500(monkeypatch, app):
    """Um erro de dedo na PORTA do `APP_LACAI_URL` — `8OO1` com letras O em vez
    de zeros — levanta `httpx.InvalidURL`, que NÃO é `httpx.HTTPError` (herda
    directamente de `Exception`). Apanhado só o `HTTPError`, a excepção subia e
    a funcionária lia «Internal Server Error» em vez da frase que lhe diz que a
    fatura pode seguir sem pontos."""
    monkeypatch.setenv("APP_LACAI_URL", "http://olacai-api:8OO1")
    with pytest.raises(HTTPException) as e:
        _ler(monkeypatch, _db_do_ler())
    assert (e.value.status_code, e.value.detail) == (503, _MSG_APP)


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




# --- A fila e o envio ---------------------------------------------------------


def _casa(doc, filtro):
    """Igualdade, `$lt` e `$lte` — e as comparações só entre STRINGS, como o
    Mongo: um `null` não casa com `$lt` de uma string. É essa regra que obriga
    a linha a nascer com `a_enviar_ate` preenchido (`pontos_app._NUNCA`)."""
    for campo, valor in filtro.items():
        atual = doc.get(campo)
        if isinstance(valor, dict):
            for operador, alvo in valor.items():
                if not isinstance(atual, str):
                    return False
                if operador == "$lt" and not atual < alvo:
                    return False
                if operador == "$lte" and not atual <= alvo:
                    return False
        elif atual != valor:
            return False
    return True


class _Fila(ColeccaoFalsa):
    """`fat_pontos_app`: o duplo de `test_fiscal` — com o único de `chave` LIDO
    de `db.INDICES`, para o teste cair se o índice desaparecer — mais a reserva
    atómica. Cede o controlo ANTES de ler e escreve sem mais nenhum `await`, que
    é a garantia que o `find_one_and_update` do Mongo dá."""

    def __init__(self, linhas=None):
        super().__init__(linhas, indices_unicos=_unicos_de("fat_pontos_app"))

    async def find_one_and_update(self, filtro, atualizacao, projection=None,
                                  return_document=None):
        await asyncio.sleep(0)
        for doc in self._documentos:
            if _casa(doc, filtro):
                doc.update(atualizacao["$set"])
                return deepcopy(doc)
        return None

    def linhas(self):
        return self._documentos


AGORA = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)


def _credito(**over):
    linha = pontos_app._linha_nova(
        "credito", "credito:doc-1",
        {"ligacao_id": "lig-1", "documento_id": "doc-1", "atcud": "JJ3K-1824",
         "numero": "FS 05P2026/1824", "emitido_em": "2026-09-15T11:59:58+00:00",
         "total": 12.1, "caucao": 0.2, "meios_pagamento": ["316430468"],
         "loja_nome": "Belém", "operador_nome": "Rafaela"},
        AGORA, documento_id="doc-1", venda_id="venda-1", primeiro_nome="Ana")
    linha.update(over)
    return linha


def _estorno(**over):
    linha = pontos_app._linha_nova(
        "estorno", "estorno:nc-1",
        {"atcud_origem": "JJ3K-1824", "nc_id": "nc-1", "numero_nc": "NC 05P2026/12",
         "valor_nc": 10.2, "caucao_nc": 0.0},
        AGORA, documento_id="doc-1", nc_documento_id="nc-1", venda_id="venda-1",
        primeiro_nome="Ana")
    linha.update(over)
    return linha


def _db_da_fila(*linhas):
    fila = _Fila(list(linhas))
    return DbFalsa({COLECOES["pontos_app"]: fila}), fila


def _iso(momento):
    return pontos_app._iso(momento)


def test_a_linha_nasce_pendente_e_ja_se_pode_reservar():
    linha = _credito()
    assert (linha["estado"], linha["tentativas"], linha["pontos"]) == ("pendente", 0, None)
    assert linha["primeira_falha_tecnica_em"] is None, (
        "o relógio das 24 h só arranca na primeira falha TÉCNICA")
    assert linha["proxima_tentativa_em"] <= _iso(AGORA)
    assert linha["a_enviar_ate"] < _iso(AGORA), (
        "a_enviar_ate tem de nascer comparável e no passado — a None nunca casa com $lt")


def test_a_mesma_chave_so_entra_uma_vez_na_fila(monkeypatch):
    enviados = []
    monkeypatch.setattr(pontos_app, "tentar_ja", lambda db, linha_id: enviados.append(linha_id))
    db, fila = _db_da_fila()

    assert _corre(pontos_app._enfileirar(db, _credito())) is True
    assert _corre(pontos_app._enfileirar(db, _credito())) is False

    assert len(fila.linhas()) == 1
    assert enviados == [fila.linhas()[0]["id"]], "a segunda passagem não pode mandar nada"


@pytest.mark.parametrize("resposta", ["creditado", "ja_creditado"])
def test_um_credito_aceite_fica_feito_com_os_pontos(monkeypatch, app, resposta):
    db, fila = _db_da_fila(_credito())
    app.responde(200, {"estado": resposta, "pontos": 17})

    linha = _corre(pontos_app.enviar(db, agora=AGORA))

    gravada = fila.linhas()[0]
    assert (gravada["estado"], gravada["pontos"]) == ("feito", 17)
    assert gravada["a_enviar_ate"] == pontos_app._NUNCA, "a reserva tem de ser largada"
    assert linha["estado"] == "feito"
    assert str(app.pedidos[0].url) == "http://olacai-api:8001/api/pos-integracao/creditar"
    assert app.pedidos[0].headers["X-Service-Key"] == "chave-de-teste"
    assert app.corpo() == gravada["payload"]


def test_uma_recusa_fica_recusada_com_o_motivo_e_nunca_se_repete(monkeypatch, app):
    db, fila = _db_da_fila(_credito())
    app.responde(200, {"estado": "recusado", "motivo": "plataforma"})

    _corre(pontos_app.enviar(db, agora=AGORA))

    gravada = fila.linhas()[0]
    assert (gravada["estado"], gravada["motivo"]) == ("recusado", "plataforma")
    assert _corre(pontos_app.enviar(db, agora=AGORA + timedelta(days=1))) is None
    assert len(app.pedidos) == 1


@pytest.mark.parametrize("estado_http", [401, 500, 503])
def test_um_erro_tecnico_fica_pendente_conta_a_tentativa_e_espera_um_minuto(
        monkeypatch, app, estado_http):
    db, fila = _db_da_fila(_credito())
    app.responde(estado_http, {"detail": "em baixo"})

    _corre(pontos_app.enviar(db, agora=AGORA))

    gravada = fila.linhas()[0]
    assert (gravada["estado"], gravada["tentativas"]) == ("pendente", 1)
    assert "HTTP %d" % estado_http in gravada["ultimo_erro"]
    assert gravada["proxima_tentativa_em"] == _iso(AGORA + timedelta(minutes=1))
    assert gravada["a_enviar_ate"] == pontos_app._NUNCA


@pytest.mark.parametrize("erro", [httpx.ConnectError("sem rota"),
                                  httpx.ReadTimeout("a app não respondeu")])
def test_a_rede_em_baixo_ou_o_tecto_dos_4_segundos_fica_pendente(monkeypatch, app, erro):
    db, fila = _db_da_fila(_credito())
    app.rebenta(erro)

    _corre(pontos_app.enviar(db, agora=AGORA))

    gravada = fila.linhas()[0]
    assert (gravada["estado"], gravada["tentativas"]) == ("pendente", 1)
    assert gravada["ultimo_erro"].startswith("rede: ")


def test_um_URL_com_a_porta_estragada_conta_tentativa_e_nao_congela_a_fila(monkeypatch, app):
    """**O defeito que isto prende.** `httpx.InvalidURL` — o que um `8OO1` com
    letras no `APP_LACAI_URL` do `.env` levanta — não é `httpx.HTTPError`, e
    escapava ao `except`. A linha já estava RESERVADA quando a excepção subia:
    ninguém gravava desfecho nenhum, ela ficava `pendente` com 0 tentativas e
    sem relógio das 24 h (o backoffice a dizer «À espera de ser enviado.» para
    sempre) — e a volta do cron morria nessa primeira linha, com os pontos de
    todas as lojas parados em silêncio."""
    monkeypatch.setenv("APP_LACAI_URL", "http://olacai-api:8OO1")
    db, fila = _db_da_fila(_credito())

    _corre(pontos_app.enviar(db, agora=AGORA))

    gravada = fila.linhas()[0]
    assert (gravada["estado"], gravada["tentativas"]) == ("pendente", 1)
    assert gravada["primeira_falha_tecnica_em"] == _iso(AGORA), (
        "o relógio das 24 h tem de arrancar — isto é uma falha técnica")
    assert gravada["a_enviar_ate"] == pontos_app._NUNCA, "a reserva tem de ser largada"


def test_um_200_com_um_estado_que_o_contrato_nao_tem_e_erro_tecnico(monkeypatch, app):
    db, fila = _db_da_fila(_credito())
    app.responde(200, {"estado": "talvez"})
    _corre(pontos_app.enviar(db, agora=AGORA))
    assert (fila.linhas()[0]["estado"], fila.linhas()[0]["tentativas"]) == ("pendente", 1)


def test_a_espera_cresce_1_2_5_10_30_e_fica_nos_30(monkeypatch, app):
    db, _ = _db_da_fila(_credito())
    app.responde(503, {"detail": "em baixo"})
    quando, esperas = AGORA, []
    for _ in range(6):
        linha = _corre(pontos_app.enviar(db, agora=quando))
        seguinte = datetime.fromisoformat(linha["proxima_tentativa_em"])
        esperas.append(int((seguinte - quando).total_seconds() // 60))
        quando = seguinte
    assert esperas == [1, 2, 5, 10, 30, 30]


def test_antes_da_hora_da_proxima_tentativa_ninguem_lhe_pega(monkeypatch, app):
    db, _ = _db_da_fila(_credito())
    app.responde(503, {"detail": "em baixo"})
    _corre(pontos_app.enviar(db, agora=AGORA))
    assert _corre(pontos_app.enviar(db, agora=AGORA + timedelta(seconds=59))) is None
    assert len(app.pedidos) == 1


def test_ao_fim_de_24_horas_A_FALHAR_passa_a_falhado(monkeypatch, app):
    """24 h **a falhar**, contadas da primeira falha técnica — por isso são
    precisas DUAS passagens: a que carimba o relógio e a que o lê."""
    db, fila = _db_da_fila(_credito())
    app.responde(503, {"detail": "em baixo"})

    _corre(pontos_app.enviar(db, agora=AGORA))
    assert fila.linhas()[0]["primeira_falha_tecnica_em"] == _iso(AGORA)

    _corre(pontos_app.enviar(db, agora=AGORA + timedelta(hours=24)))
    assert fila.linhas()[0]["estado"] == "falhado"


def test_um_minuto_antes_das_24_horas_ainda_tenta(monkeypatch, app):
    db, fila = _db_da_fila(_credito())
    app.responde(503, {"detail": "em baixo"})
    _corre(pontos_app.enviar(db, agora=AGORA))
    _corre(pontos_app.enviar(db, agora=AGORA + timedelta(hours=23, minutes=59)))
    assert fila.linhas()[0]["estado"] == "pendente"


def test_a_primeira_falha_tecnica_carimba_se_UMA_vez(monkeypatch, app):
    """O relógio arranca uma vez e fica. Recarimbá-lo a cada falha adiava as
    24 h para sempre e a linha nunca desistia."""
    db, fila = _db_da_fila(_credito())
    app.responde(503, {"detail": "em baixo"})
    _corre(pontos_app.enviar(db, agora=AGORA))
    _corre(pontos_app.enviar(db, agora=AGORA + timedelta(minutes=5)))
    assert fila.linhas()[0]["primeira_falha_tecnica_em"] == _iso(AGORA)


def test_sem_configuracao_espera_sem_rede_e_nunca_passa_a_falhado(monkeypatch, app):
    """«Não se perde nada»: as 24 h são para a app em baixo, não para um
    servidor por acabar de instalar. E esperar não é falhar — não gasta
    tentativa nem arranca o relógio."""
    monkeypatch.delenv("APP_LACAI_URL")
    db, fila = _db_da_fila(_credito())

    _corre(pontos_app.enviar(db, agora=AGORA + timedelta(hours=30)))

    gravada = fila.linhas()[0]
    assert (gravada["estado"], gravada["tentativas"]) == ("pendente", 0)
    assert gravada["ultimo_erro"] == "integração não configurada"
    assert gravada["primeira_falha_tecnica_em"] is None
    assert gravada["proxima_tentativa_em"] == _iso(AGORA + timedelta(hours=30, minutes=1))
    assert app.pedidos == []


def test_a_linha_que_ESPEROU_pela_configuracao_nao_desiste_a_primeira_falha(monkeypatch, app):
    """**O defeito que isto prende.** Com o relógio a contar desde `criado_em`,
    uma linha que esperou dois dias pela chave (integração por configurar,
    crontab por instalar — o passo 4 da ordem de arranque da spec) passava a
    `falhado` na PRIMEIRA falha real depois de a configuração chegar, mesmo com
    a app em baixo 4 segundos. Os pontos daquela compra perdiam-se para sempre
    e o backoffice escrevia «Falhou ao fim de 24 h», que era falso sobre o que
    tinha acontecido."""
    monkeypatch.delenv("APP_LACAI_URL")
    db, fila = _db_da_fila(_credito())
    for horas in (16, 32, 48):
        _corre(pontos_app.enviar(db, agora=AGORA + timedelta(hours=horas)))
    assert (fila.linhas()[0]["estado"], fila.linhas()[0]["tentativas"]) == ("pendente", 0)

    # A chave chega (deploy do RH) e a app está a reiniciar nesse instante.
    monkeypatch.setenv("APP_LACAI_URL", "http://olacai-api:8001")
    app.responde(503, {"detail": "a reiniciar"})
    quando = AGORA + timedelta(hours=48, minutes=1)
    _corre(pontos_app.enviar(db, agora=quando))

    gravada = fila.linhas()[0]
    assert gravada["estado"] == "pendente", "4 segundos de app em baixo não perdem os pontos"
    assert (gravada["tentativas"], gravada["primeira_falha_tecnica_em"]) == (1, _iso(quando))
    assert gravada["proxima_tentativa_em"] == _iso(quando + timedelta(minutes=1)), (
        "a espera recomeça no primeiro degrau: as passagens sem configuração "
        "não gastaram o escalonamento")


def test_uma_linha_que_JA_FALHOU_e_aceite_na_tentativa_seguinte(monkeypatch, app):
    """O caminho feliz DEPOIS de uma falha — a app volta e a linha fecha-se.
    Sem ele, a máquina de estados só estava provada em cadeias de falhas e em
    sucessos à primeira."""
    db, fila = _db_da_fila(_credito())
    app.responde(503, {"detail": "em baixo"})
    _corre(pontos_app.enviar(db, agora=AGORA))

    app.responde(200, {"estado": "creditado", "pontos": 17})
    linha = _corre(pontos_app.enviar(db, agora=AGORA + timedelta(minutes=1)))

    gravada = fila.linhas()[0]
    assert (linha["estado"], gravada["estado"]) == ("feito", "feito")
    assert (gravada["pontos"], gravada["tentativas"]) == (17, 1)
    assert gravada["a_enviar_ate"] == pontos_app._NUNCA
    assert gravada["ultimo_erro"].startswith("HTTP 503"), (
        "o erro de ontem fica escrito — é o que explica ao gestor a tentativa gasta")


def test_dois_envios_AO_MESMO_TEMPO_da_mesma_linha_falam_com_a_app_uma_vez(monkeypatch, app):
    """Dois workers do uvicorn e o cron no mesmo segundo. Sem a reserva, as duas
    leituras viam a linha pendente e as duas telefonavam."""
    db, fila = _db_da_fila(_credito())
    app.responde(200, {"estado": "creditado", "pontos": 17})
    linha_id = fila.linhas()[0]["id"]

    async def _os_dois():
        return await asyncio.gather(
            pontos_app.enviar(db, linha_id, agora=AGORA),
            pontos_app.enviar(db, linha_id, agora=AGORA))

    resultados = _corre(_os_dois())
    assert len(app.pedidos) == 1
    assert sorted(r is None for r in resultados) == [False, True]


def test_uma_linha_RESERVADA_por_outro_processo_so_se_apanha_quando_a_reserva_caduca(
        monkeypatch, app):
    db, _ = _db_da_fila(_credito(a_enviar_ate=_iso(AGORA + timedelta(seconds=30))))
    app.responde(200, {"estado": "creditado", "pontos": 17})

    assert _corre(pontos_app.enviar(db, agora=AGORA)) is None
    assert app.pedidos == []
    # O processo que a reservou morreu a meio: passada a reserva, o cron pega-lhe.
    assert _corre(pontos_app.enviar(db, agora=AGORA + timedelta(seconds=31)))["estado"] == "feito"


def test_uma_resposta_que_chega_DEPOIS_de_a_reserva_caducar_nao_escreve_por_cima(monkeypatch, app):
    """O processo A reservou e ficou pendurado; passada a reserva, B pegou na
    linha e a app creditou. Quando A acorda com o seu 503 atrasado, não pode
    pôr outra vez a pendente uma linha que já está feita."""
    db, fila = _db_da_fila(_credito())
    linha_id = fila.linhas()[0]["id"]

    async def _cenario():
        chegou, porta, pedidos = asyncio.Event(), asyncio.Event(), []

        async def _app_lenta(pedido):
            pedidos.append(pedido)
            if len(pedidos) == 1:
                chegou.set()
                await porta.wait()
                return httpx.Response(503, json={"detail": "tarde demais"})
            return httpx.Response(200, json={"estado": "creditado", "pontos": 17})

        monkeypatch.setattr(pontos_app, "_transporte", httpx.MockTransport(_app_lenta))
        lento = asyncio.ensure_future(pontos_app.enviar(db, linha_id, agora=AGORA))
        await chegou.wait()
        await pontos_app.enviar(db, linha_id, agora=AGORA + timedelta(seconds=61))
        porta.set()
        await lento

    _corre(_cenario())
    gravada = fila.linhas()[0]
    assert (gravada["estado"], gravada["pontos"], gravada["tentativas"]) == ("feito", 17, 0)


def test_o_estorno_espera_pelo_credito_sem_gastar_tentativas(monkeypatch, app):
    db, fila = _db_da_fila(_credito(), _estorno())
    estorno_id = fila.linhas()[1]["id"]

    linha = _corre(pontos_app.enviar(db, estorno_id, agora=AGORA))

    assert (linha["estado"], linha["tentativas"]) == ("pendente", 0)
    assert linha["proxima_tentativa_em"] == _iso(AGORA + timedelta(minutes=1))
    assert app.pedidos == []


@pytest.mark.parametrize("resposta", ["estornado", "ja_estornado"])
def test_com_o_credito_feito_o_estorno_segue_para_a_app(monkeypatch, app, resposta):
    db, fila = _db_da_fila(_credito(estado="feito", pontos=17), _estorno())
    app.responde(200, {"estado": resposta, "pontos": 9})

    linha = _corre(pontos_app.enviar(db, agora=AGORA))

    assert (linha["tipo"], linha["estado"], linha["pontos"]) == ("estorno", "feito", 9)
    assert str(app.pedidos[0].url) == "http://olacai-api:8001/api/pos-integracao/estornar"
    assert app.corpo() == fila.linhas()[1]["payload"]


@pytest.mark.parametrize("estado_do_credito", ["recusado", "falhado"])
def test_um_credito_que_nunca_entrou_deixa_o_estorno_sem_efeito_e_sem_rede(
        monkeypatch, app, estado_do_credito):
    db, _ = _db_da_fila(_credito(estado=estado_do_credito), _estorno())

    linha = _corre(pontos_app.enviar(db, agora=AGORA))

    assert (linha["tipo"], linha["estado"]) == ("estorno", "sem_efeito")
    assert app.pedidos == []


def test_a_app_a_dizer_sem_efeito_fica_sem_efeito(monkeypatch, app):
    db, _ = _db_da_fila(_credito(estado="feito", pontos=17), _estorno())
    app.responde(200, {"estado": "sem_efeito"})
    assert _corre(pontos_app.enviar(db, agora=AGORA))["estado"] == "sem_efeito"


def test_a_tentativa_imediata_volta_logo_e_engole_os_erros(monkeypatch):
    """Quem chama é o EMITIR, com a fatura já na AT. `tentar_ja` agenda e volta:
    se esperasse pela app, a funcionária esperava 4 s por causa de pontos."""

    async def _cenario():
        porta = asyncio.Event()
        chamadas = []

        async def _enviar_lento(db, linha_id=None, agora=None):
            chamadas.append(linha_id)
            await porta.wait()
            raise RuntimeError("a app rebentou a meio")

        monkeypatch.setattr(pontos_app, "enviar", _enviar_lento)
        pontos_app.tentar_ja(object(), "linha-1")
        tarefas = list(pontos_app._EM_CURSO)
        porta.set()
        for _ in range(5):
            await asyncio.sleep(0)
        return chamadas, tarefas, len(pontos_app._EM_CURSO)

    chamadas, tarefas, no_fim = _corre(_cenario())
    assert len(tarefas) == 1 and chamadas == ["linha-1"]
    assert tarefas[0].done() and tarefas[0].exception() is None, "o erro saiu da tarefa"
    assert no_fim == 0, "a tarefa acabada tem de sair de _EM_CURSO"


# --- O crédito, na emissão ------------------------------------------------------

_FATURACAO = Path(__file__).resolve().parents[2] / "faturacao"


@pytest.fixture
def envios(monkeypatch):
    """Substitui a tentativa imediata por um registo: aqui só importa QUE linha
    se mandou, e nenhuma tarefa fica a correr depois do teste."""
    enviados = []
    monkeypatch.setattr(pontos_app, "tentar_ja", lambda db, linha_id: enviados.append(linha_id))
    return enviados


def _venda_com_pontos(**over):
    """Uma venda ANTIGA de propósito: os pagamentos não têm o retrato do id do
    Vendus (`vendus_payment_method_id`), que só passa a ser gravado nesta task.
    É o caminho de recuo — a releitura de `fat_tipos_pagamento` — que fica
    assim exercitado por omissão."""
    v = {
        "id": "venda-1", "loja_id": "loja-1", "sessao_id": "sessao-1",
        "caixa_id": "caixa-1", "operador_id": "op-1", "estado": "aberta",
        "linhas": [], "cliente_nif": None,
        "pagamentos": [
            {"tipo_pagamento_id": "tipo-dinheiro", "nome": "Dinheiro", "tipo_fiscal": "NU", "valor": 2.0},
            {"tipo_pagamento_id": "tipo-glovo", "nome": "Glovo", "tipo_fiscal": "OU", "valor": 10.1},
        ],
        "pontos_ligacao": {"id": "lig-1", "primeiro_nome": "Ana"},
    }
    v.update(over)
    return v


def _documento_fs(**over):
    d = {"id": "doc-1", "venda_id": "venda-1", "loja_id": "loja-1", "tipo": "FS",
         "modo": "normal", "numero": "FS 05P2026/1824", "atcud": "JJ3K-1824",
         "total": 12.1, "deposito": 0.2, "emitido_em": "2026-09-15T11:59:58+00:00"}
    d.update(over)
    return d


def _db_da_emissao(venda):
    fila = _Fila()
    db = DbFalsa({
        COLECOES["vendas"]: ColeccaoFalsa([venda]),
        COLECOES["refs_fiscais"]: ColeccaoFalsa([]),
        COLECOES["tipos_pagamento"]: ColeccaoFalsa([
            _tipo_pagamento(),
            _tipo_pagamento(id="tipo-glovo", nome="Glovo", tipo_fiscal="OU",
                            vendus_payment_method_id="176663078"),
        ]),
        COLECOES["lojas"]: ColeccaoFalsa([{"id": "loja-1", "nome": "Belém"}]),
        COLECOES["utilizadores"]: ColeccaoFalsa([{"id": "op-1", "nome": "Rafaela"}]),
        COLECOES["pontos_app"]: fila,
    })
    return db, fila


def _ligar(db, documento):
    _corre(fiscal_mod._ligar_venda_ao_documento(
        db, "ext-1", "venda-1", documento, reserva_id="ref-1"))


def test_a_fatura_emitida_com_cliente_ligado_enfileira_o_credito_com_o_contrato_da_app(envios):
    db, fila = _db_da_emissao(_venda_com_pontos())

    _ligar(db, _documento_fs())

    [linha] = fila.linhas()
    assert (linha["chave"], linha["tipo"], linha["estado"]) == ("credito:doc-1", "credito", "pendente")
    assert (linha["documento_id"], linha["venda_id"], linha["primeiro_nome"]) == ("doc-1", "venda-1", "Ana")
    assert linha["payload"] == {
        "ligacao_id": "lig-1", "documento_id": "doc-1", "atcud": "JJ3K-1824",
        "numero": "FS 05P2026/1824", "emitido_em": "2026-09-15T11:59:58+00:00",
        "total": 12.1, "caucao": 0.2, "meios_pagamento": ["316430468", "176663078"],
        "loja_nome": "Belém", "operador_nome": "Rafaela",
    }
    assert envios == [linha["id"]], "a tentativa imediata tem de sair logo"


def test_o_id_do_VENDUS_vem_do_retrato_da_venda_mesmo_sem_o_tipo_de_pagamento(envios):
    """`meios_pagamento` é a ÚNICA coisa por onde a app recusa Uber Eats, Glovo
    e Bolt (`plataformas.py`, que compara ids). Reconstruí-la de
    `fat_tipos_pagamento` no instante de enfileirar — e este gancho também
    corre na reconciliação, dias depois de o gestor mexer nos tipos — dava uma
    lista mais curta por causa de um tipo apagado, e a guarda falhava ABERTA:
    pontos numa encomenda de plataforma, que é a fuga que o motivo `plataforma`
    existe para tapar."""
    venda = _venda_com_pontos(pagamentos=[
        {"tipo_pagamento_id": "tipo-glovo", "nome": "Glovo", "tipo_fiscal": "OU",
         "valor": 12.1, "vendus_payment_method_id": "176663078"},
    ])
    db, fila = _db_da_emissao(venda)
    db._coleccoes[COLECOES["tipos_pagamento"]] = ColeccaoFalsa([])  # o gestor apagou o tipo

    _ligar(db, _documento_fs())

    assert fila.linhas()[0]["payload"]["meios_pagamento"] == ["176663078"]


def test_um_pagamento_sem_id_do_vendus_nao_encolhe_a_lista_em_SILENCIO(envios, caplog):
    """Uma venda de ANTES do retrato, cujo tipo perdeu entretanto o mapeamento:
    já não há como saber se foi Glovo, e a lista sai mais curta do que os
    pagamentos. Não se inventa nada — mas também não acontece em silêncio: é o
    único rasto de que a recusa por plataforma pode ter falhado aberta naquela
    fatura."""
    db, fila = _db_da_emissao(_venda_com_pontos())
    db._coleccoes[COLECOES["tipos_pagamento"]] = ColeccaoFalsa([_tipo_pagamento()])  # sem o Glovo

    with caplog.at_level(logging.ERROR, logger="faturacao.pontos_app"):
        _ligar(db, _documento_fs())

    assert fila.linhas()[0]["payload"]["meios_pagamento"] == ["316430468"]
    assert "tipo-glovo" in caplog.text and "doc-1" in caplog.text


def test_o_gancho_corre_duas_vezes_e_o_credito_entra_uma(envios):
    """`_ligar_venda_ao_documento` corre mais do que uma vez para a mesma venda
    (o retry que reencontra o documento, a reconciliação por cima de uma
    emissão em voo)."""
    db, fila = _db_da_emissao(_venda_com_pontos())
    _ligar(db, _documento_fs())
    _ligar(db, _documento_fs())
    assert len(fila.linhas()) == 1
    assert len(envios) == 1


_EXT_REF = "pos-loja-1-sessao-1-venda-1"


def _db_da_reconciliacao(venda):
    """A venda que ficou para trás em `aberta` com a FS REAL já gravada: o ramo
    de `reconciliar_reserva_presa` (fiscal.py:3442) que religa a venda ao
    documento sem precisar de falar com o Vendus."""
    db, fila = _db_da_emissao(venda)
    db._coleccoes[COLECOES["documentos"]] = ColeccaoFalsa(
        [_documento_fs(ext_ref=_EXT_REF)], indices_unicos=_unicos_de("fat_documentos"))
    db._coleccoes[COLECOES["refs_fiscais"]] = ColeccaoFalsa([{
        "id": "r1", "ext_ref": _EXT_REF, "venda_id": "venda-1",
        "criado_em": "2026-09-14T20:00:00+00:00", "incerta": True}])
    db._coleccoes[COLECOES["sessoes_caixa"]] = ColeccaoFalsa([{
        "id": "sessao-1", "loja_id": "loja-1", "caixa_id": "caixa-1", "estado": "aberta"}])
    return db, fila


def test_a_venda_salva_pela_RECONCILIACAO_tambem_da_os_pontos(monkeypatch, envios):
    """O caminho até `emitida` mais fácil de esquecer: dias depois, o gestor
    traz para o sistema a fatura que o Vendus já tinha. Quem mostrou a app na
    caixa recebe os pontos à mesma — e é aqui que a venda é RELIDA, com os
    tipos de pagamento possivelmente já mexidos."""
    db, fila = _db_da_reconciliacao(_venda_com_pontos())
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    resposta = _corre(fiscal_mod.reconciliar_reserva_presa(
        "venda-1", None, gestor={"email": "dono@lacai.pt"}))

    assert resposta["veio_do_vendus_agora"] is False
    [linha] = fila.linhas()
    assert (linha["chave"], linha["venda_id"]) == ("credito:doc-1", "venda-1")
    assert linha["payload"]["meios_pagamento"] == ["316430468", "176663078"]
    assert envios == [linha["id"]]


def test_um_documento_em_modo_tests_nunca_enfileira(envios):
    db, fila = _db_da_emissao(_venda_com_pontos())
    _ligar(db, _documento_fs(modo="tests"))
    assert fila.linhas() == [] and envios == []


def test_uma_venda_sem_cliente_ligado_nao_enfileira(envios):
    db, fila = _db_da_emissao(_venda_com_pontos(pontos_ligacao=None))
    _ligar(db, _documento_fs())
    assert fila.linhas() == [] and envios == []


def test_os_pontos_a_rebentar_nao_impedem_a_venda_de_ficar_emitida(monkeypatch):
    db, _ = _db_da_emissao(_venda_com_pontos())

    async def _explode(*a, **kw):
        raise RuntimeError("tudo mal")

    monkeypatch.setattr(pontos_app, "enfileirar_credito", _explode)
    _ligar(db, _documento_fs())

    gravada = _corre(db[COLECOES["vendas"]].find_one({"id": "venda-1"}))
    assert (gravada["estado"], gravada["documento_id"]) == ("emitida", "doc-1")


def test_o_enganche_dos_pontos_esta_dentro_de_um_except_generico():
    """Um `except` que nomeasse excepções deixava passar as outras — e uma
    excepção que suba daqui devolve 500 ao balcão com a fatura já na AT."""
    texto = (_FATURACAO / "fiscal.py").read_text(encoding="utf-8")
    bloco = texto[texto.index("from .pontos_app import enfileirar_credito"):]
    bloco = bloco[:bloco.index("\n\nasync def")]
    assert "except Exception" in bloco, bloco[:400]


class _VendusNormal(ClienteEmissaoVendusFalso):
    """O duplo do Vendus da rota, a devolver uma fatura REAL (modo `normal`) —
    só essas dão pontos."""

    def __init__(self, chave):
        super().__init__(chave)
        self.resposta_criar = _bruto(modo="normal")


def _finalizar(monkeypatch, venda, **pedido):
    _configura_vendus_env(monkeypatch)
    monkeypatch.setattr(db_mod, "_indice_idempotencia_ok", True)
    db = _db(vendas=[venda], tipos_pagamento=[_tipo_pagamento()])
    db._coleccoes[COLECOES["lojas"]] = ColeccaoFalsa([{"id": "loja-1", "nome": "Belém"}])
    db._coleccoes[COLECOES["utilizadores"]] = ColeccaoFalsa([{"id": "op-1", "nome": "Rafaela"}])
    fila = _Fila()
    db._coleccoes[COLECOES["pontos_app"]] = fila
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", _VendusNormal)
    _corre(fiscal_mod.finalizar(
        "venda-1",
        PedidoFinalizarVenda(
            pagamentos=[PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)],
            **pedido),
        operador=_operador()))
    return db, fila


def test_o_finalizar_grava_a_ligacao_na_venda_e_a_fatura_enfileira_o_credito(monkeypatch, envios):
    db, fila = _finalizar(monkeypatch, _venda(linhas=[_linha()]),
                          pontos_ligacao={"id": "lig-1", "primeiro_nome": "Ana"})

    gravada = _corre(db[COLECOES["vendas"]].find_one({"id": "venda-1"}))
    assert gravada["pontos_ligacao"] == {"id": "lig-1", "primeiro_nome": "Ana"}
    [linha] = fila.linhas()
    assert linha["payload"]["ligacao_id"] == "lig-1"
    assert (linha["payload"]["atcud"], linha["payload"]["numero"]) == ("ATCUD-1", "FS 2026/1")
    assert (linha["payload"]["total"], linha["payload"]["caucao"]) == (8.99, 0.0)
    assert linha["payload"]["meios_pagamento"] == ["316430468"]
    assert len(envios) == 1


def test_sem_ligacao_o_finalizar_grava_pontos_ligacao_a_None_por_cima_da_antiga(monkeypatch, envios):
    """Uma tentativa anterior leu o QR do Rui e falhou; a operadora repetiu sem
    ele. A venda não pode ficar com o Rui agarrado — e a fatura não lhe pode
    dar os pontos."""
    velha = _venda(linhas=[_linha()], pontos_ligacao={"id": "lig-velha", "primeiro_nome": "Rui"})

    db, fila = _finalizar(monkeypatch, velha)

    gravada = _corre(db[COLECOES["vendas"]].find_one({"id": "venda-1"}))
    assert "pontos_ligacao" in gravada and gravada["pontos_ligacao"] is None
    assert fila.linhas() == [] and envios == []


def test_uma_ligacao_sem_id_e_recusada_antes_da_rota_correr():
    """422 no validador, antes da reserva fiscal — como o NIF mal escrito."""
    with pytest.raises(ValidationError):
        PedidoFinalizarVenda(
            pagamentos=[PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)],
            pontos_ligacao={"id": "", "primeiro_nome": "Ana"})


# --- O estorno, na nota de crédito ----------------------------------------------


def _nota(**over):
    n = {
        "id": "intencao-1", "documento_id": "doc-1", "venda_id": "venda-1",
        "total": 10.4,
        "linhas": [
            {"indice": 1, "titulo": "Açaí Regular", "tax_id": "INT", "total": 10.2},
            {"indice": 4, "titulo": "Depósito", "tax_id": "NS", "total": 0.2},
        ],
    }
    n.update(over)
    return n


def _documento_nc(**over):
    d = {"id": "nc-1", "tipo": "NC", "numero": "NC 05P2026/12", "modo": "normal"}
    d.update(over)
    return d


def test_a_nota_de_uma_fatura_com_pontos_enfileira_o_estorno_com_o_contrato_da_app(envios):
    db, fila = _db_da_fila(_credito(estado="feito", pontos=17))

    _corre(pontos_app.enfileirar_estorno(db, _nota(), _documento_nc()))

    linha = fila.linhas()[1]
    assert (linha["chave"], linha["tipo"], linha["estado"]) == ("estorno:nc-1", "estorno", "pendente")
    assert (linha["documento_id"], linha["nc_documento_id"]) == ("doc-1", "nc-1")
    assert linha["primeiro_nome"] == "Ana"
    assert linha["payload"] == {
        "atcud_origem": "JJ3K-1824", "nc_id": "nc-1", "numero_nc": "NC 05P2026/12",
        "valor_nc": 10.4, "caucao_nc": 0.2,
    }
    assert envios == [linha["id"]]


def test_a_nota_de_uma_fatura_SEM_pontos_nao_enfileira_nada(envios):
    db, fila = _db_da_fila()
    _corre(pontos_app.enfileirar_estorno(db, _nota(), _documento_nc()))
    assert fila.linhas() == [] and envios == []


def test_uma_nota_em_modo_tests_nao_tira_pontos_a_ninguem(envios):
    db, fila = _db_da_fila(_credito(estado="feito", pontos=17))
    _corre(pontos_app.enfileirar_estorno(db, _nota(), _documento_nc(modo="tests")))
    assert len(fila.linhas()) == 1 and envios == []


def test_a_mesma_nota_so_enfileira_um_estorno(envios):
    db, fila = _db_da_fila(_credito(estado="feito", pontos=17))
    _corre(pontos_app.enfileirar_estorno(db, _nota(), _documento_nc()))
    _corre(pontos_app.enfileirar_estorno(db, _nota(), _documento_nc()))
    assert len(fila.linhas()) == 2 and len(envios) == 1


def _ambiente_da_nota(monkeypatch):
    monkeypatch.setattr(db_mod, "_indice_notas_credito_ok", True)
    _configura_vendus_env(monkeypatch)
    VendusNCFalso.instancias.clear()
    VendusNCFalso.emitidos = 0
    monkeypatch.setattr(nc_mod, "ClienteEmissaoVendus", VendusNCFalso)


def test_a_rota_da_nota_enfileira_o_estorno_DEPOIS_de_a_marcar_emitida(monkeypatch):
    _ambiente_da_nota(monkeypatch)
    db = _db_nc()
    vistas = []

    async def _regista(db_, nota, documento_nc, agora=None):
        gravada = await db_[COLECOES["notas_credito"]].find_one({"id": nota["id"]})
        vistas.append((gravada["estado"], documento_nc["numero"], nota["documento_id"]))

    monkeypatch.setattr(pontos_app, "enfileirar_estorno", _regista)
    resposta = _emitir(db, monkeypatch)

    assert vistas == [("emitida", resposta["numero"], "doc-1")]


def test_os_pontos_a_rebentar_nao_estragam_a_nota_de_credito(monkeypatch):
    _ambiente_da_nota(monkeypatch)
    db = _db_nc()

    async def _explode(*a, **kw):
        raise RuntimeError("tudo mal")

    monkeypatch.setattr(pontos_app, "enfileirar_estorno", _explode)
    resposta = _emitir(db, monkeypatch)

    assert resposta["numero"]
    gravada = _corre(db[COLECOES["notas_credito"]].find_one({"id": resposta["id"]}))
    assert gravada["estado"] == "emitida"


# --- A volta do cron -------------------------------------------------------------

_SCRIPT_DO_CRON = Path(__file__).resolve().parents[3] / "faturacao-pontos-cron.sh"


def test_sem_a_chave_certa_a_porta_do_cron_fecha(monkeypatch):
    monkeypatch.setenv("CRON_KEY", "a-chave-certa")
    with pytest.raises(HTTPException) as e:
        _corre(pontos_app.cron_pontos_app(key="a-errada"))
    assert e.value.status_code == 403


def test_sem_CRON_KEY_no_ambiente_nem_a_palavra_None_abre_a_porta(monkeypatch):
    monkeypatch.delenv("CRON_KEY", raising=False)
    with pytest.raises(HTTPException) as e:
        _corre(pontos_app.cron_pontos_app(key="None"))
    assert e.value.status_code == 403


def test_a_volta_envia_as_linhas_vencidas_e_deixa_as_outras(monkeypatch, app):
    agora = datetime.now(timezone.utc)
    antes = agora - timedelta(minutes=5)
    vencida_1 = _credito(chave="credito:doc-1", criado_em=_iso(antes), proxima_tentativa_em=_iso(antes))
    vencida_2 = _credito(chave="credito:doc-2", criado_em=_iso(antes), proxima_tentativa_em=_iso(antes))
    futura = _credito(chave="credito:doc-3", proxima_tentativa_em=_iso(agora + timedelta(hours=1)))
    db, fila = _db_da_fila(vencida_1, futura, vencida_2)
    monkeypatch.setattr(pontos_app, "obter_db", lambda: db)
    monkeypatch.setenv("CRON_KEY", "a-chave-certa")
    app.responde(200, {"estado": "creditado", "pontos": 17})

    assert _corre(pontos_app.cron_pontos_app(key="a-chave-certa")) == {"enviadas": 2}
    assert [l["estado"] for l in fila.linhas()] == ["feito", "pendente", "feito"]


def test_com_a_app_em_baixo_a_volta_tenta_cada_linha_uma_vez_e_para(monkeypatch, app):
    antes = _iso(datetime.now(timezone.utc) - timedelta(minutes=5))
    db, _ = _db_da_fila(_credito(criado_em=antes, proxima_tentativa_em=antes))
    monkeypatch.setattr(pontos_app, "obter_db", lambda: db)
    monkeypatch.setenv("CRON_KEY", "a-chave-certa")
    app.responde(503, {"detail": "em baixo"})

    assert _corre(pontos_app.cron_pontos_app(key="a-chave-certa")) == {"enviadas": 1}
    assert len(app.pedidos) == 1


def test_o_script_do_cron_bate_numa_rota_POST_que_existe_mesmo():
    """O endereço LIDO do script é confrontado com o router — nunca afirmado
    à mão (um caminho errado dá 404 de minuto a minuto, e um cron que falha não
    avisa ninguém)."""
    from faturacao import router
    texto = _SCRIPT_DO_CRON.read_text(encoding="utf-8")
    enderecos = re.findall(r'"http://localhost:8000(/api/[^"?]+)', texto)
    assert enderecos, "o script não chama nenhum endereço — foi reescrito?"
    posts = {r.path for r in router.routes if "POST" in r.methods}
    assert set(enderecos) <= posts, (enderecos, sorted(p for p in posts if "/cron/" in p))
    assert 'os.environ["CRON_KEY"]' in texto, "a chave vem do contentor, nunca do crontab"


def test_o_script_do_cron_e_executavel_e_diz_como_se_instala_de_minuto_a_minuto():
    texto = _SCRIPT_DO_CRON.read_text(encoding="utf-8")
    assert os.access(_SCRIPT_DO_CRON, os.X_OK), (
        "falta o bit de execução: git update-index --chmod=+x faturacao-pontos-cron.sh")
    assert re.search(r"^#\s+\* \* \* \* \*\s+/root/RH/faturacao-pontos-cron\.sh",
                     texto, re.MULTILINE)
