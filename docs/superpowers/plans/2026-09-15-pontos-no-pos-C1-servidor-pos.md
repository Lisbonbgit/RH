# Pontos L'Açaí no POS — C1: servidor do POS (RH) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O servidor do POS lê o QR da app L'Açaí, guarda o cliente ligado na venda ao emitir, e entrega à app — por uma fila com chave única, reserva atómica, tentativa imediata e cron — o crédito de cada Fatura Simplificada e o estorno de cada nota de crédito, mostrando o estado no detalhe do documento do backoffice.

**Architecture:** Um ficheiro novo, `backend/faturacao/pontos_app.py`, com tudo o que é dos pontos: o cliente httpx da app, a rota `POST /pos/pontos/ler`, a fila `fat_pontos_app` (enfileirar, reservar, enviar, gravar o desfecho), a rota do cron e a leitura para o backoffice. O resto do módulo só ganha três ganchos de uma chamada, todos dentro de `try/except Exception` e com import LOCAL (o molde do desconto de stock): no fim de `fiscal._ligar_venda_ao_documento` (crédito), a seguir à marca `emitida` da nota de crédito (estorno) e na rota GET do gestor em `documentos.py` (leitura). O `PedidoFinalizarVenda` ganha `pontos_ligacao`, que vai sempre para `dados_pagamento`.

**Tech Stack:** Python 3.9 · FastAPI · Pydantic v2 · Motor/PyMongo 4 (`find_one_and_update`, `ReturnDocument`) · httpx 0.28 (`AsyncClient`, `MockTransport` nos testes) · pytest com os duplos de Mongo de `tests/faturacao/test_fiscal.py`.

## Global Constraints

- **Português de Portugal** em código, comentários, nomes de testes e commits. Docstrings dizem o PORQUÊ.
- **Python 3.9** (o `.venv` é 3.9.6): nada de `X | Y` em anotações, nada de `match`.
- **Nenhum teste toca no Mongo nem na rede.** Base de dados = duplos (`test_fiscal.ColeccaoFalsa/DbFalsa`, `test_venda.ColeccaoFalsa/DbFalsa`); app = `httpx.MockTransport` em `pontos_app._transporte`.
- **Nada daqui pode impedir uma fatura ou uma nota de crédito de sair.** Os ganchos em `fiscal.py` e `nota_credito.py` ficam em `try/except Exception`; a tentativa imediata corre em segundo plano (`asyncio` task).
- Rota nova `POST /api/faturacao/pos/pontos/ler`, dependência `operador_atual`. Pedido `{venda_id: str, codigo: str}`. **200** `{ligacao_id: str, primeiro_nome: str}`.
- QR recusado → **404** `{"detail": "QR inválido ou expirado — peça ao cliente para abrir o QR outra vez."}`, e **só** quando o 404 da app traz o corpo do contrato (`{"estado": "recusado", "motivo": "qr_invalido"}`) — é a única forma de 404 que a spec descreve.
- App em baixo / sem configuração / timeout / 401 / 5xx / **404 sem esse corpo** (o FastAPI da app a responder `{"detail": "Not Found"}` porque a rota `/api/pos-integracao/ligar` ainda não está lá, ou porque o `APP_LACAI_URL` tem o caminho ou a porta trocados) / 200 sem `ligacao_id` → **503** `{"detail": "Não foi possível falar com a app agora. A fatura pode seguir sem pontos."}`.
- Venda inexistente ou de outra loja → **404** `"Venda não encontrada."` (`venda._MSG_VENDA_INEXISTENTE`, via `venda._obter_venda_da_loja`). Venda não aberta → **409** `"Esta venda já foi emitida ou cancelada — não aceita alterações."` (`venda._MSG_VENDA_NAO_ABERTA`) ou, se `estado == "separada"`, **409** com `venda._MSG_VENDA_SEPARADA` (via `venda._garante_aberta`). Corpo inválido → 422 do Pydantic. **A venda confere-se ANTES de chamar a app** (a app consome o QR). O Ler **não grava nada na venda**.
- `POST /api/faturacao/pos/venda/{id}/finalizar`: o corpo ganha `pontos_ligacao: {id: str (1..100), primeiro_nome: str (≤100)} | null`, gravado em `dados_pagamento.pontos_ligacao` **SEMPRE presente** (`None` quando não há).
- Variáveis de ambiente `APP_LACAI_URL` (produção `http://olacai-api:8001`) e `APP_LACAI_CHAVE`, lidas a cada chamada. Cabeçalho `X-Service-Key`. `httpx.AsyncClient`, timeout **4 s**. Caminhos `{APP_LACAI_URL}/api/pos-integracao/ligar|creditar|estornar`.
- Contrato com a app (spec):
  - `ligar` ← `{codigo, loja_nome, operador_nome}`; → 200 `{ligacao_id, primeiro_nome}` · 404 `{estado: "recusado", motivo: "qr_invalido"}`.
  - `creditar` ← `{ligacao_id, documento_id, atcud, numero, emitido_em (ISO, UTC), total, caucao, meios_pagamento: [id Vendus], loja_nome, operador_nome}` (euros com 2 casas); → 200 `{estado: "creditado"|"ja_creditado", pontos}` · 200 `{estado: "recusado", motivo}` · 5xx técnico.
  - `estornar` ← `{atcud_origem, nc_id, numero_nc, valor_nc, caucao_nc}`; → 200 `{estado: "estornado"|"ja_estornado", pontos}` · 200 `{estado: "sem_efeito"}`.
- Coleção `fat_pontos_app` (`COLECOES["pontos_app"]`), índice **único** em `chave`. Chaves `credito:{documento_id}` e `estorno:{nc_documento_id}`. Documento: `{id, chave, tipo: "credito"|"estorno", documento_id, nc_documento_id, venda_id, payload, estado, pontos, motivo, tentativas, ultimo_erro, criado_em, atualizado_em, proxima_tentativa_em, a_enviar_ate}` + `primeiro_nome` (para o backoffice) + `primeira_falha_tecnica_em` (o relógio das 24 h — ver abaixo).
- `estado` ∈ `pendente | feito | recusado | sem_efeito | falhado`.
- Resposta → estado: `creditado`/`ja_creditado`/`estornado`/`ja_estornado` → `feito` + `pontos`; `recusado` → `recusado` + `motivo`; `sem_efeito` → `sem_efeito`; 401/503/5xx/rede/timeout/qualquer outra coisa → continua `pendente`, `tentativas + 1`, `ultimo_erro`, próxima tentativa daqui a **1, 2, 5, 10, 30 min** (e 30 daí em diante); ao fim de **24 h desde a PRIMEIRA falha técnica** (`primeira_falha_tecnica_em`, carimbado nessa primeira e nunca mais mexido) → `falhado`. **Nunca desde `criado_em`:** uma linha que esperou legitimamente — integração por configurar, crontab por instalar — passava a `falhado` na primeira falha real depois de a chave chegar, com a app em baixo 4 segundos, e os pontos dessa compra perdiam-se para sempre.
- Sem `APP_LACAI_URL`/`APP_LACAI_CHAVE` → a linha **espera**, com o molde do estorno à espera do crédito: fica `pendente` com `ultimo_erro = "integração não configurada"`, **sem gastar tentativa**, nova tentativa daqui a 1 min, e nunca carimba `primeira_falha_tecnica_em`. Uma instalação por acabar não é uma avaria da app: não gasta o escalonamento (senão a primeira tentativa a sério só acontecia 30 min depois de a chave chegar) nem o relógio das 24 h.
- Reserva antes de enviar: `find_one_and_update({estado: "pendente", proxima_tentativa_em ≤ agora, a_enviar_ate < agora}, {$set: {a_enviar_ate: agora + 60 s}})`.
- Crédito: enfileira-se no fim de `fiscal._ligar_venda_ao_documento` se a venda tiver `pontos_ligacao` e o documento for do modo `normal`; `DuplicateKeyError` engolido; modo `tests` nunca enfileira.
- Estorno: enfileira-se logo depois da escrita `emitida` da nota de crédito, se a FS de origem tiver linha de crédito. Só se envia com o crédito `feito`; crédito `recusado`/`falhado` → estorno `sem_efeito`.
- Cron `POST /api/faturacao/cron/pontos-app?key=<CRON_KEY>` (403 `"Acesso negado."` sem `CRON_KEY` ou com chave errada, `secrets.compare_digest`) + `faturacao-pontos-cron.sh` executável, crontab `* * * * *`.
- `GET /api/faturacao/documentos/{documento_id}` (gestor) ganha `pontos_app: null | {tipo, estado, pontos, primeiro_nome, motivo, tentativas, ultimo_erro, atualizado_em}` — numa FS a linha de crédito, numa NC a linha de estorno dessa NC.
- **Fora deste plano:** `frontend/src/lib/pos.js` e o ecrã (C2). O `test_caminhos_do_pos.py` corre no fim do C2.

## File Structure

- **Create** `backend/faturacao/pontos_app.py` — cliente da app, rota Ler, fila, envio, crédito, estorno, cron, leitura do backoffice.
- **Create** `backend/tests/faturacao/test_os_pontos_da_app.py` — todos os testes do ficheiro acima e dos ganchos.
- **Create** `faturacao-pontos-cron.sh` (raiz do repo, executável) — a volta de 1 em 1 minuto.
- **Modify** `backend/faturacao/__init__.py:135-136` — montar o router.
- **Modify** `backend/faturacao/db.py:87-88` e `:373-374` — coleção e índices.
- **Modify** `backend/faturacao/fiscal.py:1417-1421` (gancho), `:1922-1923` (`PedidoFinalizarVenda`), `:2051-2062` (o id do Vendus no retrato do pagamento), `:2080-2087` (`dados_pagamento`).
- **Modify** `backend/faturacao/nota_credito.py:1414-1416` — gancho do estorno.
- **Modify** `backend/faturacao/documentos.py:88-89` e `:838-848` — `pontos_app` no detalhe do gestor.
- **Modify** `backend/tests/faturacao/test_fiscal.py:1341-1343` — o retrato do pagamento passa a levar o id do Vendus.
- **Modify** `backend/tests/faturacao/test_protecao_rotas.py:56-61` — a porta nova do cron.
- **Modify** `backend/tests/faturacao/test_documentos_do_backoffice.py` (fim) — testes do detalhe.
- **Modify** `backend/.env.example` (fim) — as duas variáveis e a linha do crontab.

## Antes da Task 1 — linha de base

- [ ] **Confirmar o ambiente e anotar a suite de hoje**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos
git status --short          # limpo, ramo matheus-pontos-no-pos
ls -la frontend/node_modules backend/.venv   # os dois symlinks para ~/Developer/RH
cd backend && PYTHONDONTWRITEBYTECODE=1 /Users/matheus.moraes/Developer/RH/backend/.venv/bin/python -m pytest -p no:cacheprovider -q tests 2>&1 | tail -3
```

Anotar os números `passed` e `skipped`. A Task 7 compara com eles. Se `skipped` não for 0 com o `node_modules` ligado, parar e perceber porquê antes de começar.

---

### Task 1: O cliente da app e a rota Ler

**Files:**
- Create: `backend/faturacao/pontos_app.py`
- Create: `backend/tests/faturacao/test_os_pontos_da_app.py`
- Modify: `backend/faturacao/__init__.py:135-136`

**Interfaces:**
- Consumes: `venda._obter_venda_da_loja(db, venda_id: str, loja_id: str) -> Dict` (404), `venda._garante_aberta(venda: Dict) -> None` (409), `pos_auth.operador_atual` (payload do token: `loja_id`, `nome`, `operador_id`), `db.COLECOES["lojas"]`.
- Produces:
  - `pontos_app.router: APIRouter` com `POST /pos/pontos/ler`.
  - `pontos_app.TIMEOUT_SEGUNDOS = 4.0`, `pontos_app._transporte = None` (os testes trocam por `httpx.MockTransport`).
  - `class IntegracaoNaoConfigurada(Exception)`.
  - `async def _chamar_app(acao: str, corpo: Dict) -> httpx.Response` — levanta `IntegracaoNaoConfigurada` ou `httpx.HTTPError`.
  - `def _json_ou_nada(resposta: httpx.Response)` — o JSON ou `None`.
  - `class PedidoLerQr(BaseModel): venda_id: str; codigo: str`.
  - `async def ler_qr_de_pontos(dados: PedidoLerQr, operador: Dict) -> dict` → `{"ligacao_id": str, "primeiro_nome": str}`.

- [ ] **Step 1: Escrever os testes que falham**

**Criar** `backend/tests/faturacao/test_os_pontos_da_app.py`:

```python
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
```

- [ ] **Step 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && PYTHONDONTWRITEBYTECODE=1 /Users/matheus.moraes/Developer/RH/backend/.venv/bin/python -m pytest -p no:cacheprovider -q tests/faturacao/test_os_pontos_da_app.py
```

Esperado: `1 error` na colecção — `ModuleNotFoundError: No module named 'faturacao.pontos_app'`.

- [ ] **Step 3: Implementar o cliente e a rota**

**Criar** `backend/faturacao/pontos_app.py`:

```python
"""**Os pontos L'Açaí dados na caixa** — o POS a falar com a app.

A regra do dono: ganha os pontos quem mostra a app na caixa ANTES de pagar. O
talão deixa de ser um bilhete ao portador, porque o que dá pontos já não é o
QR fiscal impresso — é o QR da app, lido pela funcionária e preso a UMA venda.

Três peças, e uma regra acima das três: **nada daqui pode impedir uma fatura
de sair nem atrasar o EMITIR.**

1. **Ler** (`POST /pos/pontos/ler`) — troca o código do QR por uma ligação na
   app e devolve só o primeiro nome. Não grava nada na venda: é o ecrã que
   guarda a ligação e a manda no finalizar (`fiscal.PedidoFinalizarVenda`).
2. **A fila** (`fat_pontos_app`) — uma linha por crédito (FS) e por estorno
   (NC), com chave única. Nasce DEPOIS de o documento existir e nunca antes:
   os pontos só entram com a fatura já entregue à AT.
3. **O envio** — reserva a linha, fala com a app (4 s) e grava o desfecho. O
   que for técnico (rede, 5xx, chave errada) volta a tentar-se com espera
   crescente; o que for de negócio (`recusado`) não se repete.

A app é idempotente por ATCUD e por nota de crédito, e é isso que deixa este
lado ser simples: um reenvio nunca credita duas vezes.
"""
import logging
import os
from typing import Dict

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .db import COLECOES, obter_db
from .pos_auth import operador_atual
from .venda import _garante_aberta, _obter_venda_da_loja

logger = logging.getLogger(__name__)

router = APIRouter()

# 4 segundos, como o desconto de stock (`estoque_cliente.TIMEOUT_SAIDA_SEGUNDOS`)
# e pela mesma razão: quem espera pelo Ler é a funcionária com o cliente à
# frente. Uma app em baixo diz-se depressa, e a fatura segue sem pontos.
TIMEOUT_SEGUNDOS = 4.0

# Os testes trocam isto por um `httpx.MockTransport`; `None` é o transporte
# normal do httpx.
_transporte = None

_MSG_QR_INVALIDO = "QR inválido ou expirado — peça ao cliente para abrir o QR outra vez."
_MSG_APP_INDISPONIVEL = (
    "Não foi possível falar com a app agora. A fatura pode seguir sem pontos."
)


class IntegracaoNaoConfigurada(Exception):
    """Falta `APP_LACAI_URL` ou `APP_LACAI_CHAVE`. Não é uma avaria — é uma
    instalação por acabar."""


async def _chamar_app(acao: str, corpo: Dict) -> httpx.Response:
    """`POST {APP_LACAI_URL}/api/pos-integracao/{acao}` com a chave de serviço.

    As duas variáveis lêem-se a CADA chamada e não à importação (o molde é
    `estoque_cliente.chave_de_servico`): o `.env` pode ganhá-las sem o portal
    reiniciar, e uma constante de módulo congelava o «não configurado».

    A chave vai no CABEÇALHO e nunca no URL: um `?key=` fica escrito nos
    registos de quem estiver pelo meio."""
    url = (os.environ.get("APP_LACAI_URL") or "").strip().rstrip("/")
    chave = (os.environ.get("APP_LACAI_CHAVE") or "").strip()
    if not url or not chave:
        raise IntegracaoNaoConfigurada("integração não configurada")
    async with httpx.AsyncClient(timeout=TIMEOUT_SEGUNDOS, transport=_transporte) as http:
        return await http.post(
            "%s/api/pos-integracao/%s" % (url, acao),
            json=corpo,
            headers={"X-Service-Key": chave},
        )


def _json_ou_nada(resposta: httpx.Response):
    try:
        return resposta.json()
    except ValueError:
        return None


# --- Ler o QR -----------------------------------------------------------------


class PedidoLerQr(BaseModel):
    venda_id: str = Field(min_length=1, max_length=100)
    # O código vai CRU: quem o normaliza (espaços, maiúsculas) é a app, que é
    # quem conhece o formato. Aqui só se trava o tamanho — um leitor avariado
    # não manda um livro à app.
    codigo: str = Field(min_length=1, max_length=200)


@router.post("/pos/pontos/ler")
async def ler_qr_de_pontos(
    dados: PedidoLerQr, operador: Dict = Depends(operador_atual)
) -> dict:
    """Troca o QR que o cliente mostra por uma ligação na app.

    **A venda confere-se ANTES de falar com a app**, e a ordem não é gosto: a
    app consome o token do QR na primeira leitura. Perguntar-lhe primeiro e
    recusar depois (venda de outra loja, já emitida) gastava o QR do cliente
    para nada, e ele tinha de o abrir outra vez. As recusas são as das outras
    rotas de venda (`venda.py`): 404 «Venda não encontrada.» para uma venda que
    não existe OU é de outra loja, 409 para uma que já não está aberta (a
    frase própria da conta dividida, `_MSG_VENDA_SEPARADA`, ou a genérica).

    **Não grava nada na venda.** A ligação volta ao ecrã, que a guarda presa ao
    id da conta e a manda no finalizar. Uma leitura que não acabe em fatura
    não deixa lixo em lado nenhum deste servidor.

    A loja e o operador vão pelo NOME e saem do TOKEN, nunca do corpo: são o
    registo de quem associou que conta a que venda, para o relatório de
    concentração da 2.ª fase."""
    db = obter_db()
    venda = await _obter_venda_da_loja(db, dados.venda_id, operador["loja_id"])
    _garante_aberta(venda)
    loja = await db[COLECOES["lojas"]].find_one(
        {"id": operador["loja_id"]}, {"_id": 0, "nome": 1})
    try:
        resposta = await _chamar_app("ligar", {
            "codigo": dados.codigo,
            "loja_nome": (loja or {}).get("nome") or "",
            "operador_nome": operador.get("nome") or "",
        })
    except (IntegracaoNaoConfigurada, httpx.HTTPError) as e:
        logger.warning(
            "[faturacao] ler QR de pontos (venda %s): a app não respondeu — %s: %s",
            dados.venda_id, type(e).__name__, e)
        raise HTTPException(status_code=503, detail=_MSG_APP_INDISPONIVEL)
    # **Só é «QR inválido» o 404 que o contrato descreve** — o da app, que traz
    # sempre `{"estado": "recusado", "motivo": "qr_invalido"}`. Um 404 do
    # FastAPI da app (`{"detail": "Not Found"}`, a rota por deployar) ou de um
    # proxy pelo meio (404 em HTML) é a app a não estar lá, e a frase certa é a
    # do 503: traduzido para «peça outro QR», a funcionária pedia ao cliente um
    # código novo vezes sem conta e nenhum ia funcionar.
    corpo_do_404 = _json_ou_nada(resposta) if resposta.status_code == 404 else None
    if isinstance(corpo_do_404, dict) and corpo_do_404.get("motivo") == "qr_invalido":
        raise HTTPException(status_code=404, detail=_MSG_QR_INVALIDO)
    corpo = _json_ou_nada(resposta) if resposta.status_code == 200 else None
    if not isinstance(corpo, dict) or not corpo.get("ligacao_id"):
        # 401 (chave trocada), 5xx, ou um 200 sem a forma do contrato: para a
        # funcionária é tudo «a app não está a responder»; o pormenor fica no log.
        logger.error(
            "[faturacao] ler QR de pontos (venda %s): resposta inesperada da app "
            "(HTTP %s): %s", dados.venda_id, resposta.status_code, resposta.text[:200])
        raise HTTPException(status_code=503, detail=_MSG_APP_INDISPONIVEL)
    return {
        "ligacao_id": str(corpo["ligacao_id"]),
        "primeiro_nome": str(corpo.get("primeiro_nome") or ""),
    }
```

**Em** `backend/faturacao/__init__.py`, **substituir:**

```python
from .sincronizacao_rota import router as _sincronizacao
router.include_router(_sincronizacao)
```

**por:**

```python
from .sincronizacao_rota import router as _sincronizacao
router.include_router(_sincronizacao)

# Os pontos L'Açaí dados na caixa: ler o QR da app, a fila dos créditos e
# estornos, e a volta do cron que a esvazia. O `fiscal.py` e o
# `nota_credito.py` chamam-no LOCALMENTE, dentro do gancho que enfileira, pela
# mesma razão do stock e do papel: uma avaria aqui não pode travar uma fatura.
from .pontos_app import router as _pontos_app
router.include_router(_pontos_app)
```

- [ ] **Step 4: Correr e ver passar (com a guarda das rotas)**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && PYTHONDONTWRITEBYTECODE=1 /Users/matheus.moraes/Developer/RH/backend/.venv/bin/python -m pytest -p no:cacheprovider -q tests/faturacao/test_os_pontos_da_app.py tests/faturacao/test_protecao_rotas.py
```

Esperado: `23 passed` (19 em `test_os_pontos_da_app.py`, 4 em `test_protecao_rotas.py`). O `test_protecao_rotas.py` passa sem mexer: a rota está debaixo de `/pos/` e depende de `operador_atual`.

- [ ] **Step 5: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos
git add backend/faturacao/pontos_app.py backend/faturacao/__init__.py backend/tests/faturacao/test_os_pontos_da_app.py
git commit -m "$(cat <<'EOF'
Ler o QR da app no POS: a venda confere-se antes de a app gastar o código

POST /api/faturacao/pos/pontos/ler troca o código do QR por uma ligação na
app L'Açaí e devolve só o primeiro nome. Não grava nada na venda. A loja e a
operadora saem do token; a chave de serviço vai no cabeçalho, 4 s de tecto.
404 para QR recusado, 503 para tudo o que seja a app em baixo ou por
configurar — a fatura segue sem pontos.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: Validação por mutação (quatro guardas)**

Uma de cada vez; depois de cada uma, `git checkout -- backend/faturacao/pontos_app.py` repõe o que ficou no commit.

1. Chave de serviço: em `_chamar_app` trocar `headers={"X-Service-Key": chave},` por `headers={},`. Correr o comando do Step 4. Esperado: FAILED `test_ler_manda_a_loja_e_o_operador_do_TOKEN_com_a_chave_no_cabecalho` (KeyError `x-service-key`). Repor.
2. Sem chave não se telefona: trocar `    if not url or not chave:` por `    if not url:`. Esperado: FAILED `test_sem_configuracao_da_503_e_nem_sai_para_a_rede[APP_LACAI_CHAVE]` (`app.pedidos` não vazio). Repor.
3. A venda antes da app: mover as duas linhas `venda = await _obter_venda_da_loja(...)` / `_garante_aberta(venda)` para logo antes de `corpo_do_404 = _json_ou_nada(resposta) if resposta.status_code == 404 else None`. Esperado: 4 FAILED — `test_uma_venda_de_OUTRA_loja_e_404_e_a_app_nem_e_chamada` e os três `test_uma_venda_que_ja_nao_esta_aberta_e_409_e_a_app_nem_e_chamada[...]`. Repor.
4. Só o 404 do contrato culpa o QR: trocar as duas linhas

   ```python
   corpo_do_404 = _json_ou_nada(resposta) if resposta.status_code == 404 else None
   if isinstance(corpo_do_404, dict) and corpo_do_404.get("motivo") == "qr_invalido":
   ```

   por `    if resposta.status_code == 404:` (a versão que não lê o corpo). Esperado: 2 FAILED — `test_um_404_do_SERVIDOR_da_app_nao_culpa_o_QR_do_cliente[fastapi_sem_a_rota]` e `[sem_json_nenhum]` (dão 404 em vez de 503). Repor.

Correr o Step 4 outra vez: `23 passed`. `git status --short` limpo.

---

### Task 2: A fila `fat_pontos_app` e a máquina de estados do envio

**Files:**
- Modify: `backend/faturacao/db.py:87-88` e `:373-374`
- Modify: `backend/faturacao/pontos_app.py` (imports; fim do ficheiro)
- Modify: `backend/tests/faturacao/test_os_pontos_da_app.py` (fim)

**Interfaces:**
- Consumes: `pontos_app._chamar_app`, `pontos_app.IntegracaoNaoConfigurada`, `pontos_app._json_ou_nada` (Task 1).
- Produces:
  - `COLECOES["pontos_app"] == "fat_pontos_app"`; `INDICES` com `("fat_pontos_app", [("chave", 1)], {"unique": True})` e `("fat_pontos_app", [("estado", 1), ("proxima_tentativa_em", 1)], {})`.
  - `pontos_app._NUNCA = "1970-01-01T00:00:00+00:00"`, `_RESERVA_SEGUNDOS = 60`, `_ESPERAS_EM_MINUTOS = (1, 2, 5, 10, 30)`, `_DESISTIR_AO_FIM_DE = timedelta(hours=24)`, `_EM_CURSO: set`.
  - `def _iso(momento: datetime) -> str` — ISO UTC ao segundo.
  - `def _linha_nova(tipo: str, chave: str, payload: Dict, agora: datetime, **campos) -> Dict`.
  - `async def _enfileirar(db, linha: Dict) -> bool` — `False` se a chave já existia; chama `tentar_ja` quando insere.
  - `def tentar_ja(db, linha_id: str) -> None` — agenda `enviar` numa task e volta.
  - `async def enviar(db, linha_id: Optional[str] = None, *, agora: Optional[datetime] = None) -> Optional[Dict]`.

- [ ] **Step 1: Escrever os testes que falham**

**Acrescentar ao fim de** `backend/tests/faturacao/test_os_pontos_da_app.py`:

```python


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
```

- [ ] **Step 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && PYTHONDONTWRITEBYTECODE=1 /Users/matheus.moraes/Developer/RH/backend/.venv/bin/python -m pytest -p no:cacheprovider -q tests/faturacao/test_os_pontos_da_app.py
```

Esperado: `29 failed, 19 passed` — os 19 da Task 1 passam; os novos falham com `AttributeError: module 'faturacao.pontos_app' has no attribute '_linha_nova'` (e `tentar_ja`).

- [ ] **Step 3: Implementar a coleção, os índices e o envio**

**Em** `backend/faturacao/db.py`, **substituir:**

```python
    "trabalhos_impressao": "fat_trabalhos_impressao",
}
```

**por:**

```python
    "trabalhos_impressao": "fat_trabalhos_impressao",
    # A FILA DOS PONTOS L'AÇAÍ (`faturacao/pontos_app.py`): um crédito por
    # Fatura Simplificada lida com o QR da app, e um estorno por nota de
    # crédito dessa fatura, à espera de chegarem à app. Fica para sempre, como
    # os documentos: é o registo de quem ganhou que pontos em que fatura, e a
    # 2.ª fase lê-o para o relatório de concentração.
    "pontos_app": "fat_pontos_app",
}
```

**Em** `backend/faturacao/db.py`, **substituir:**

```python
    ("fat_trabalhos_impressao", [("apagar_depois_de", 1)], {"expireAfterSeconds": 0}),
]
```

**por:**

```python
    ("fat_trabalhos_impressao", [("apagar_depois_de", 1)], {"expireAfterSeconds": 0}),
    # **UM CRÉDITO POR FATURA, UM ESTORNO POR NOTA** (`pontos_app._enfileirar`).
    # A chave é `credito:{documento_id}` ou `estorno:{nc_documento_id}`, e o
    # gancho que a insere (`fiscal._ligar_venda_ao_documento`) corre mais do
    # que uma vez por venda — é este índice, e não uma leitura antes de
    # inserir, que faz a segunda passagem não entrar.
    ("fat_pontos_app", [("chave", 1)], {"unique": True}),
    # A pergunta do envio e do cron, uma vez por minuto: «que linhas pendentes
    # já chegaram à hora?».
    ("fat_pontos_app", [("estado", 1), ("proxima_tentativa_em", 1)], {}),
]
```

**Em** `backend/faturacao/pontos_app.py`, **substituir:**

```python
import logging
import os
from typing import Dict

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
```

**por:**

```python
import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
```

**Acrescentar ao fim de** `backend/faturacao/pontos_app.py`:

```python


# --- A fila -------------------------------------------------------------------

# **O «nunca» de `a_enviar_ate`, e não `None`.** No Mongo, `null` não casa com
# `$lt` de uma string — os operadores de comparação só comparam dentro do mesmo
# tipo. Uma linha nascida com `a_enviar_ate: None` nunca era reservada por
# ninguém: ficava pendente para sempre, sem um erro.
_NUNCA = "1970-01-01T00:00:00+00:00"

# Quanto tempo uma linha fica reservada a quem a está a enviar. Muito acima dos
# 4 s do pedido: passado isto, só um processo morto a meio a deixa presa, e a
# volta seguinte do cron pega-lhe.
_RESERVA_SEGUNDOS = 60

# A espera antes da tentativa seguinte, em minutos: 1, 2, 5, 10 e daí em diante
# 30. Ao fim de 24 h **a falhar** (contadas da primeira falha técnica, ver
# `_falhou`), desiste-se (`falhado`).
_ESPERAS_EM_MINUTOS = (1, 2, 5, 10, 30)
_DESISTIR_AO_FIM_DE = timedelta(hours=24)

_RESPOSTAS_FEITAS = ("creditado", "ja_creditado", "estornado", "ja_estornado")

# As tentativas imediatas ainda a correr — ver `tentar_ja`.
_EM_CURSO = set()


def _iso(momento: datetime) -> str:
    """Todas as datas da fila no MESMO formato, ao segundo e em UTC: a reserva
    compara-as como texto, e dois formatos diferentes ordenam-se mal."""
    return momento.astimezone(timezone.utc).isoformat(timespec="seconds")


def _linha_nova(tipo: str, chave: str, payload: Dict, agora: datetime, **campos) -> Dict:
    """Uma linha da fila com TODOS os campos presentes desde o nascimento: a
    reserva compara `proxima_tentativa_em` e `a_enviar_ate`, e um campo ausente
    não casa com comparação nenhuma."""
    quando = _iso(agora)
    linha = {
        "id": str(uuid.uuid4()),
        "chave": chave,
        "tipo": tipo,
        "documento_id": None,
        "nc_documento_id": None,
        "venda_id": None,
        # Para o backoffice dizer «17 pontos para Ana» sem perguntar à app.
        "primeiro_nome": None,
        "payload": payload,
        "estado": "pendente",
        "pontos": None,
        "motivo": None,
        "tentativas": 0,
        "ultimo_erro": None,
        "criado_em": quando,
        "atualizado_em": quando,
        "proxima_tentativa_em": quando,
        "a_enviar_ate": _NUNCA,
        # **O relógio das 24 h, e é ESTE e não `criado_em`.** Carimba-se na
        # primeira falha TÉCNICA (a app a responder mal, a rede em baixo) e
        # nunca mais se mexe. Contado desde o nascimento, uma linha que esperou
        # legitimamente — integração por configurar, crontab por instalar —
        # desistia na primeira falha real depois de a chave chegar, com a app
        # em baixo 4 segundos, e os pontos daquela compra perdiam-se.
        "primeira_falha_tecnica_em": None,
    }
    linha.update(campos)
    return linha


async def _enfileirar(db, linha: Dict) -> bool:
    """Insere a linha e manda-a já, em segundo plano. Devolve `False` se a
    chave já lá estava.

    `DuplicateKeyError` engole-se e não é erro nenhum: o gancho da emissão
    (`fiscal._ligar_venda_ao_documento`) corre mais do que uma vez por venda —
    o retry que reencontra o documento, a reconciliação de uma reserva presa —
    e a segunda passagem é a defesa a funcionar."""
    try:
        await db[COLECOES["pontos_app"]].insert_one(dict(linha))
    except DuplicateKeyError:
        return False
    tentar_ja(db, linha["id"])
    return True


def tentar_ja(db, linha_id: str) -> None:
    """A tentativa imediata, em SEGUNDO PLANO: agenda o envio e volta logo.

    Quem chama está dentro do EMITIR, com a fatura já na AT e a funcionária à
    espera da resposta. Esperar aqui pela app eram até 4 s de balcão parado por
    causa de pontos — e se a app estiver em baixo a linha fica pendente e o
    cron de 1 em 1 minuto pega-lhe. Com dois workers, o outro processo e o cron
    não a enviam ao mesmo tempo: a reserva de `enviar` decide.

    A tarefa fica em `_EM_CURSO` até acabar: o asyncio só guarda uma referência
    FRACA às tarefas, e uma tarefa que ninguém segura pode ser recolhida a
    meio."""
    tarefa = asyncio.get_running_loop().create_task(_tentar_em_silencio(db, linha_id))
    _EM_CURSO.add(tarefa)
    tarefa.add_done_callback(_EM_CURSO.discard)


async def _tentar_em_silencio(db, linha_id: str) -> None:
    try:
        await enviar(db, linha_id)
    except Exception as e:  # noqa: BLE001 — em segundo plano não há a quem devolver o erro
        logger.error(
            "[faturacao] envio imediato da linha de pontos %s falhou (o cron repete): %s",
            linha_id, e)


async def enviar(db, linha_id: Optional[str] = None, *, agora: Optional[datetime] = None) -> Optional[Dict]:
    """Reserva UMA linha pendente e vencida (esta, se vier `linha_id`), manda-a
    à app e grava o desfecho. Devolve a linha como ficou, ou `None` se não
    havia nada para reservar.

    **A reserva é a primeira escrita, e é condicional.** Dois workers do
    uvicorn e o cron podem pegar na mesma linha no mesmo segundo; o
    `find_one_and_update` com `a_enviar_ate < agora` deixa passar exactamente
    um. A app é idempotente de qualquer forma — a reserva é para não a
    incomodar duas vezes e para duas respostas não se escreverem por cima.

    **Um estorno só sai com o crédito `feito`.** Com o crédito ainda pendente
    espera (sem gastar tentativas: não é uma falha); com o crédito recusado ou
    falhado não há pontos a tirar e fica `sem_efeito` sem falar com a app."""
    agora = agora or datetime.now(timezone.utc)
    filtro = {
        "estado": "pendente",
        "proxima_tentativa_em": {"$lte": _iso(agora)},
        "a_enviar_ate": {"$lt": _iso(agora)},
    }
    if linha_id is not None:
        filtro["id"] = linha_id
    reserva = _iso(agora + timedelta(seconds=_RESERVA_SEGUNDOS))
    linha = await db[COLECOES["pontos_app"]].find_one_and_update(
        filtro, {"$set": {"a_enviar_ate": reserva}},
        projection={"_id": 0}, return_document=ReturnDocument.AFTER)
    if linha is None:
        return None

    if linha["tipo"] == "estorno":
        credito = await db[COLECOES["pontos_app"]].find_one(
            {"chave": "credito:%s" % linha["documento_id"]}, {"_id": 0, "estado": 1})
        estado_do_credito = (credito or {}).get("estado")
        if estado_do_credito == "pendente":
            return await _fechar(db, linha, reserva, agora, {
                "proxima_tentativa_em": _iso(agora + timedelta(minutes=1)),
                "ultimo_erro": "à espera do crédito da fatura",
            })
        if estado_do_credito != "feito":
            return await _fechar(db, linha, reserva, agora, {
                "estado": "sem_efeito",
                "motivo": "credito_%s" % (estado_do_credito or "inexistente"),
            })

    acao = "creditar" if linha["tipo"] == "credito" else "estornar"
    try:
        resposta = await _chamar_app(acao, linha["payload"])
    except IntegracaoNaoConfigurada:
        # «Não se perde nada»: sem configuração a linha ESPERA — não falhou.
        # O molde é o do estorno à espera do crédito, aqui em cima: não gasta
        # tentativa (senão a primeira tentativa a sério só acontecia 30 min
        # depois de a chave chegar) e não carimba `primeira_falha_tecnica_em`,
        # por isso as 24 h nem sequer arrancaram. As 24 h são para a app em
        # baixo, não para um servidor por acabar de instalar.
        return await _fechar(db, linha, reserva, agora, {
            "proxima_tentativa_em": _iso(agora + timedelta(minutes=1)),
            "ultimo_erro": "integração não configurada",
        })
    except httpx.HTTPError as e:
        return await _falhou(db, linha, reserva, agora, "rede: %s %s" % (type(e).__name__, e))

    corpo = _json_ou_nada(resposta) if resposta.status_code == 200 else None
    estado_da_app = corpo.get("estado") if isinstance(corpo, dict) else None
    if estado_da_app in _RESPOSTAS_FEITAS:
        return await _fechar(db, linha, reserva, agora,
                             {"estado": "feito", "pontos": corpo.get("pontos")})
    if estado_da_app == "recusado":
        # Uma recusa de negócio (plataforma, acima do teto, ligação já usada…)
        # não muda por se repetir — e repeti-la era bater à porta da app de 30
        # em 30 minutos durante um dia inteiro.
        return await _fechar(db, linha, reserva, agora,
                             {"estado": "recusado", "motivo": corpo.get("motivo")})
    if estado_da_app == "sem_efeito":
        return await _fechar(db, linha, reserva, agora, {"estado": "sem_efeito"})
    # 401 (chaves trocadas), 5xx, ou um 200 que não diz nada do contrato.
    return await _falhou(db, linha, reserva, agora,
                         "HTTP %s: %s" % (resposta.status_code, resposta.text[:200]))


async def _falhou(db, linha: Dict, reserva: str, agora: datetime, erro: str) -> Dict:
    """Uma falha TÉCNICA: conta a tentativa, afasta a seguinte e, ao fim de 24 h
    **a falhar**, desiste.

    O relógio conta de `primeira_falha_tecnica_em` e não de `criado_em`: uma
    linha que esperou pela configuração (ver o `except IntegracaoNaoConfigurada`
    de `enviar`) não pode desistir na primeira falha real, e é isso que
    `criado_em` fazia — a app em baixo 4 segundos e os pontos perdidos."""
    tentativas = int(linha.get("tentativas") or 0) + 1
    espera = _ESPERAS_EM_MINUTOS[min(tentativas, len(_ESPERAS_EM_MINUTOS)) - 1]
    primeira = linha.get("primeira_falha_tecnica_em") or _iso(agora)
    campos = {
        "tentativas": tentativas,
        "ultimo_erro": erro[:300],
        "proxima_tentativa_em": _iso(agora + timedelta(minutes=espera)),
        # Escrito sempre com o valor que já lá estava (ou o de agora, na
        # primeira): carimba uma vez e fica — recarimbá-lo a cada falha adiava
        # as 24 h para sempre.
        "primeira_falha_tecnica_em": primeira,
    }
    if agora - datetime.fromisoformat(primeira) >= _DESISTIR_AO_FIM_DE:
        campos["estado"] = "falhado"
    logger.warning(
        "[faturacao] pontos da app: a linha %s (%s) não chegou à app (tentativa %d): %s",
        linha["id"], linha["chave"], tentativas, erro)
    return await _fechar(db, linha, reserva, agora, campos)


async def _fechar(db, linha: Dict, reserva: str, agora: datetime, campos: Dict) -> Dict:
    """Grava o desfecho e larga a reserva — só se a reserva ainda for ESTA. Se
    o envio demorou mais do que `_RESERVA_SEGUNDOS` e outro processo pegou na
    linha entretanto, é a escrita dele que vale."""
    campos = dict(campos, a_enviar_ate=_NUNCA, atualizado_em=_iso(agora))
    await db[COLECOES["pontos_app"]].update_one(
        {"id": linha["id"], "a_enviar_ate": reserva}, {"$set": campos})
    linha.update(campos)
    return linha
```

- [ ] **Step 4: Correr e ver passar (com os índices)**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && PYTHONDONTWRITEBYTECODE=1 /Users/matheus.moraes/Developer/RH/backend/.venv/bin/python -m pytest -p no:cacheprovider -q tests/faturacao/test_os_pontos_da_app.py tests/faturacao/test_indices.py
```

Esperado: `65 passed` — 48 em `test_os_pontos_da_app.py` e `test_indices.py` todo verde (17) (o `test_criar_indices_aplica_todos` lê `len(INDICES)`, e o TTL continua a ser só o da impressão).

- [ ] **Step 5: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos
git add backend/faturacao/db.py backend/faturacao/pontos_app.py backend/tests/faturacao/test_os_pontos_da_app.py
git commit -m "$(cat <<'EOF'
A fila dos pontos da app: uma linha por chave, reservada antes de telefonar

fat_pontos_app com índice único em chave. enviar() reserva a linha com
find_one_and_update (dois workers e o cron nunca a mandam ao mesmo tempo),
fala com a app e grava o desfecho: feito, recusado (não se repete),
sem_efeito, ou pendente com espera de 1, 2, 5, 10 e 30 minutos até 24 h a
falhar — contadas da primeira falha técnica e nunca do nascimento da linha,
para que uma que esperou pela configuração não desista à primeira falha real.
Sem APP_LACAI_URL/CHAVE a linha espera, sem gastar tentativa. Um estorno
espera pelo crédito feito. A tentativa imediata corre em segundo plano e
engole os erros.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: Validação por mutação (oito guardas)**

Uma de cada vez, com o comando do Step 4 (só `tests/faturacao/test_os_pontos_da_app.py` chega); depois de cada uma, `git checkout -- backend/faturacao/pontos_app.py backend/faturacao/db.py`.

1. **Reserva:** apagar a linha `        "a_enviar_ate": {"$lt": _iso(agora)},` do filtro de `enviar`. Esperado: FAILED `test_dois_envios_AO_MESMO_TEMPO_da_mesma_linha_falam_com_a_app_uma_vez` (2 pedidos) e `test_uma_linha_RESERVADA_por_outro_processo_so_se_apanha_quando_a_reserva_caduca`.
2. **Chave única:** em `db.py`, trocar `("fat_pontos_app", [("chave", 1)], {"unique": True}),` por `("fat_pontos_app", [("chave", 1)], {}),`. Esperado: FAILED `test_a_mesma_chave_so_entra_uma_vez_na_fila` (a segunda inserção entra).
3. **Fecho condicional:** em `_fechar`, trocar `{"id": linha["id"], "a_enviar_ate": reserva}` por `{"id": linha["id"]}`. Esperado: FAILED `test_uma_resposta_que_chega_DEPOIS_de_a_reserva_caducar_nao_escreve_por_cima` (a linha volta a `pendente`).
4. **Estorno espera pelo crédito:** trocar `        if estado_do_credito == "pendente":` por `        if False:`. Esperado: FAILED `test_o_estorno_espera_pelo_credito_sem_gastar_tentativas` (a linha fica `sem_efeito`).
5. **Recusa não se repete:** trocar `    if estado_da_app == "recusado":` por `    if False:`. Esperado: FAILED `test_uma_recusa_fica_recusada_com_o_motivo_e_nunca_se_repete`.
6. **Segundo plano engole:** em `_tentar_em_silencio`, trocar `except Exception as e:` por `except KeyError as e:`. Esperado: FAILED `test_a_tentativa_imediata_volta_logo_e_engole_os_erros` («o erro saiu da tarefa»).
7. **O relógio das 24 h (o defeito que isto prende):** em `_falhou`, trocar `    if agora - datetime.fromisoformat(primeira) >= _DESISTIR_AO_FIM_DE:` por `    if agora - datetime.fromisoformat(linha["criado_em"]) >= _DESISTIR_AO_FIM_DE:`. Esperado: FAILED `test_a_linha_que_ESPEROU_pela_configuracao_nao_desiste_a_primeira_falha` (a linha fica `falhado`). `test_ao_fim_de_24_horas_A_FALHAR_passa_a_falhado` continua VERDE — é por isso que a mutação é precisa: sem o teste novo, este defeito ficava escondido por baixo de um teste verde.
8. **Sem configuração não é falhar:** no `except IntegracaoNaoConfigurada` de `enviar`, trocar o `_fechar(...)` inteiro por `        return await _falhou(db, linha, reserva, agora, "integração não configurada")`. Esperado: 2 FAILED — `test_sem_configuracao_espera_sem_rede_e_nunca_passa_a_falhado` (gasta uma tentativa) e `test_a_linha_que_ESPEROU_pela_configuracao_nao_desiste_a_primeira_falha`.

No fim: Step 4 outra vez verde, `git status --short` limpo.

---

### Task 3: O crédito na emissão (`pontos_ligacao` no finalizar + gancho)

**Files:**
- Modify: `backend/faturacao/fiscal.py:1417-1421` (fim de `_ligar_venda_ao_documento`), `:1922-1923` (`PedidoFinalizarVenda`), `:2051-2062` (o id do Vendus no retrato do pagamento), `:2080-2087` (`dados_pagamento`)
- Modify: `backend/faturacao/pontos_app.py` (fim)
- Modify: `backend/tests/faturacao/test_os_pontos_da_app.py` (fim)
- Modify: `backend/tests/faturacao/test_fiscal.py:1341-1343` (o retrato do pagamento ganha um campo)

**Interfaces:**
- Consumes: `pontos_app._linha_nova`, `pontos_app._enfileirar` (Task 2); `fiscal._ligar_venda_ao_documento(db, ext_ref, venda_id, documento, *, reserva_id)` — async, a única escrita de `emitida` numa venda, chamada pela emissão feliz, pelas duas retomas e por `fiscal.reconciliar_reserva_presa` (fiscal.py:3442); o `documento` gravado tem `id, atcud, numero, total, deposito, modo, emitido_em`; a venda gravada tem `loja_id, operador_id, pagamentos[].tipo_pagamento_id` e, a partir desta task, `pagamentos[].vendus_payment_method_id` e `pontos_ligacao`.
- Produces:
  - `fiscal.LigacaoDePontos(BaseModel)`: `id: str (1..100)`, `primeiro_nome: str (≤100)`.
  - `fiscal.PedidoFinalizarVenda.pontos_ligacao: Optional[LigacaoDePontos] = None`.
  - `dados_pagamento == {"pagamentos": [...], "cliente_nif": ..., "pontos_ligacao": {"id", "primeiro_nome"} | None}`, com cada pagamento a levar também `vendus_payment_method_id` (o retrato do dia, como o `nome` e o `tipo_fiscal`).
  - `async def pontos_app.enfileirar_credito(db, venda_id: str, documento: Dict, *, agora: Optional[datetime] = None) -> None`.

- [ ] **Step 1: Escrever os testes que falham**

**Acrescentar ao fim de** `backend/tests/faturacao/test_os_pontos_da_app.py`:

```python


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
```

- [ ] **Step 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && PYTHONDONTWRITEBYTECODE=1 /Users/matheus.moraes/Developer/RH/backend/.venv/bin/python -m pytest -p no:cacheprovider -q tests/faturacao/test_os_pontos_da_app.py
```

Esperado: `10 failed, 50 passed` (60 recolhidos) — `ValueError: substring not found` no teste do enganche, «DID NOT RAISE» na ligação sem id, e nos outros a fila vazia (`IndexError`/`not enough values to unpack`), o `KeyError: 'pontos_ligacao'` na venda gravada ou o Rui ainda agarrado à venda. `test_uma_venda_sem_cliente_ligado_nao_enfileira` e `test_um_documento_em_modo_tests_nunca_enfileira` já passam (não há gancho nenhum) — são o travão para a mutação 2 do Step 6.

- [ ] **Step 3: Implementar**

**Em** `backend/faturacao/fiscal.py`, **substituir:**

```python
            "[faturacao] o desconto de stock da venda %s falhou (a fatura saiu na "
            "mesma): %s", venda_id, e,
        )
```

**por:**

```python
            "[faturacao] o desconto de stock da venda %s falhou (a fatura saiu na "
            "mesma): %s", venda_id, e,
        )

    # **OS PONTOS L'AÇAÍ entram na fila AQUI**, pelas razões do stock logo
    # acima: é a única escrita de `emitida` e por aqui passam os cinco
    # caminhos que acabam num documento fiscal. Uma venda salva pela
    # reconciliação dá os pontos a quem mostrou a app, como a emissão feliz.
    #
    # Um `try` à parte e não o do stock: um Estoque em baixo não pode levar os
    # pontos do cliente, nem o contrário. E `except Exception` pela mesma regra
    # de ouro — um 500 aqui era a funcionária a emitir a fatura outra vez.
    try:
        from .pontos_app import enfileirar_credito
        await enfileirar_credito(db, venda_id, documento)
    except Exception as e:  # noqa: BLE001 — os pontos nunca podem parar uma fatura
        logger.error(
            "[faturacao] os pontos L'Açaí da venda %s não entraram na fila (a "
            "fatura saiu na mesma): %s", venda_id, e,
        )
```

**Em** `backend/faturacao/fiscal.py`, **substituir:**

```python
class PedidoFinalizarVenda(BaseModel):
    pagamentos: List[PagamentoEntrada] = Field(min_length=1)
```

**por:**

```python
class LigacaoDePontos(BaseModel):
    """A ligação que o `POST /pos/pontos/ler` devolveu e o ecrã guardou.

    Só o id e o primeiro nome: o id é o que a app precisa para creditar, e o
    nome é o que o backoffice mostra («17 pontos para Ana»). Nada disto é
    validado contra a app aqui — um id inventado chega à app, que responde
    `ligacao_desconhecida`, e a fatura já saiu sem esperar por isso."""

    id: str = Field(min_length=1, max_length=100)
    primeiro_nome: str = Field(max_length=100)


class PedidoFinalizarVenda(BaseModel):
    pagamentos: List[PagamentoEntrada] = Field(min_length=1)
    # O cliente que mostrou a app na caixa, ou `None`. Opcional e nunca
    # obrigatório: o cartão dos pontos no ecrã não bloqueia o EMITIR.
    pontos_ligacao: Optional[LigacaoDePontos] = None
```

**Em** `backend/faturacao/fiscal.py`, **substituir** (o retrato do tipo de pagamento, fiscal.py:2051-2062):

```python
        pagamentos_venda.append({
            "tipo_pagamento_id": tipo["id"],
            "nome": tipo.get("nome"),
            "tipo_fiscal": tipo.get("tipo_fiscal"),
            "valor": p.valor,
        })
```

**por:**

```python
        pagamentos_venda.append({
            "tipo_pagamento_id": tipo["id"],
            "nome": tipo.get("nome"),
            "tipo_fiscal": tipo.get("tipo_fiscal"),
            # O id do Vendus vai no retrato pela MESMA razão dos outros dois, e
            # com um motivo a mais: é por esta lista que a app L'Açaí recusa
            # pontos em encomendas de plataforma (Uber Eats, Glovo, Bolt, que
            # ela conhece por id). Reconstruí-la mais tarde de
            # `fat_tipos_pagamento` — e `pontos_app.enfileirar_credito` corre
            # também na reconciliação, dias depois — encolhia-a em silêncio se
            # o gestor tivesse mexido no tipo, e a recusa falhava ABERTA. A
            # linha acima garante que ele existe sempre neste instante (422).
            "vendus_payment_method_id": tipo["vendus_payment_method_id"],
            "valor": p.valor,
        })
```

**Em** `backend/tests/faturacao/test_fiscal.py`, **substituir** (a única afirmação da suite sobre a forma exacta do retrato, test_fiscal.py:1341-1343):

```python
    assert resultado["pagamentos"] == [
        {"tipo_pagamento_id": "tipo-dinheiro", "nome": "Dinheiro", "tipo_fiscal": "NU", "valor": 8.99}
    ]
```

**por:**

```python
    assert resultado["pagamentos"] == [
        {"tipo_pagamento_id": "tipo-dinheiro", "nome": "Dinheiro", "tipo_fiscal": "NU",
         # O id do Vendus é retrato como o nome e o tipo fiscal: é por ele que
         # os pontos da app recusam as plataformas (`pontos_app`).
         "vendus_payment_method_id": "316430468", "valor": 8.99}
    ]
```

**Em** `backend/faturacao/fiscal.py`, **substituir:**

```python
    dados_pagamento = {"pagamentos": pagamentos_venda, "cliente_nif": dados.nif}
```

**por:**

```python
    #
    # `pontos_ligacao` vai SEMPRE, a `None` quando não há — como o
    # `cliente_nif`. Uma tentativa falhada com o QR de um cliente, repetida
    # depois sem ele, não pode deixar esse cliente agarrado à venda: o gancho
    # da emissão lê a venda, e dava-lhe os pontos de uma compra que não fez.
    dados_pagamento = {
        "pagamentos": pagamentos_venda,
        "cliente_nif": dados.nif,
        "pontos_ligacao": dados.pontos_ligacao.model_dump() if dados.pontos_ligacao else None,
    }
```

**Acrescentar ao fim de** `backend/faturacao/pontos_app.py`:

```python


# --- O crédito, na emissão ------------------------------------------------------


async def enfileirar_credito(db, venda_id: str, documento: Dict, *,
                             agora: Optional[datetime] = None) -> None:
    """Põe na fila o crédito desta Fatura Simplificada, se a venda tiver um
    cliente ligado. Chamado no fim de `fiscal._ligar_venda_ao_documento`.

    - **Só o modo `normal`.** Uma fatura em `tests` não existe na AT, e
      creditar pontos por ela era dar pontos por nada.
    - **A ligação lê-se da VENDA gravada**, não do pedido: é a venda que chega
      aos cinco caminhos da emissão, a reconciliação incluída.
    - **O corpo é o contrato de `/api/pos-integracao/creditar`**, e fica
      gravado na linha: os reenvios mandam exactamente o mesmo, dias depois
      se for preciso, sem voltar a ler a venda.

    Os meios de pagamento vão pelo id do VENDUS — é por eles, e só por eles,
    que a app recusa Uber Eats, Glovo e Bolt — e saem do RETRATO gravado na
    venda (`fiscal.finalizar`), que é o que valia no dia. A releitura de
    `fat_tipos_pagamento` é só o recuo para as vendas de antes desse campo
    existir; um pagamento que não dê id nenhum fica de fora da lista, mas
    NUNCA em silêncio (é assim que a recusa por plataforma falharia aberta).
    A caução vai à parte (`deposito`, carimbado no documento pela emissão): os
    pontos contam sobre o total sem ela. O operador é o dono da CONTA
    (`operador_id` da venda), o mesmo que o backoffice mostra no documento."""
    if documento.get("modo") != "normal":
        return
    venda = await db[COLECOES["vendas"]].find_one({"id": venda_id})
    ligacao = (venda or {}).get("pontos_ligacao")
    if not ligacao:
        return
    meios = []
    for pagamento in venda.get("pagamentos") or []:
        identificador = pagamento.get("vendus_payment_method_id")
        if not identificador:
            tipo = await db[COLECOES["tipos_pagamento"]].find_one(
                {"id": pagamento.get("tipo_pagamento_id")},
                {"_id": 0, "vendus_payment_method_id": 1})
            identificador = (tipo or {}).get("vendus_payment_method_id")
        if identificador:
            meios.append(str(identificador))
        else:
            # Uma lista mais curta do que os pagamentos é a recusa por
            # plataforma a falhar ABERTA — a app não tem como saber que aquele
            # pagamento foi Glovo. Não se adivinha nada, mas fica escrito: é o
            # único sítio onde alguém pode vir a perceber porque é que aquela
            # fatura deu pontos.
            logger.error(
                "[faturacao] pontos da app: o pagamento %r da venda %s (documento "
                "%s) não tem id do Vendus — `meios_pagamento` vai mais curto e a "
                "app não consegue recusar uma plataforma por ele",
                pagamento.get("tipo_pagamento_id"), venda_id, documento["id"])
    loja = await db[COLECOES["lojas"]].find_one(
        {"id": venda.get("loja_id")}, {"_id": 0, "nome": 1})
    operador = await db[COLECOES["utilizadores"]].find_one(
        {"id": venda.get("operador_id")}, {"_id": 0, "nome": 1})
    payload = {
        "ligacao_id": ligacao.get("id"),
        "documento_id": documento["id"],
        "atcud": documento.get("atcud"),
        "numero": documento.get("numero"),
        "emitido_em": documento.get("emitido_em"),
        "total": round(float(documento.get("total") or 0), 2),
        "caucao": round(float(documento.get("deposito") or 0), 2),
        "meios_pagamento": meios,
        "loja_nome": (loja or {}).get("nome") or "",
        "operador_nome": (operador or {}).get("nome") or "",
    }
    await _enfileirar(db, _linha_nova(
        "credito", "credito:%s" % documento["id"], payload,
        agora or datetime.now(timezone.utc),
        documento_id=documento["id"], venda_id=venda_id,
        primeiro_nome=ligacao.get("primeiro_nome")))
```

- [ ] **Step 4: Correr e ver passar (com a emissão e o stock)**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && PYTHONDONTWRITEBYTECODE=1 /Users/matheus.moraes/Developer/RH/backend/.venv/bin/python -m pytest -p no:cacheprovider -q tests/faturacao/test_os_pontos_da_app.py tests/faturacao/test_fiscal.py tests/faturacao/test_o_desconto_de_stock.py
```

Esperado: tudo verde (`test_os_pontos_da_app.py` com 60; `320 passed` no total dos três ficheiros — 60 + 229 + 31). O `test_o_desconto_de_stock.py::test_so_ha_UM_sitio_a_marcar_uma_venda_como_emitida` continua a garantir que o gancho está no único caminho de `emitida`, e o `test_fiscal.py` inteiro tem de continuar verde com o campo novo no retrato do pagamento (a única afirmação sobre a forma exacta está no Step 3).

- [ ] **Step 5: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos
git add backend/faturacao/fiscal.py backend/faturacao/pontos_app.py backend/tests/faturacao/test_os_pontos_da_app.py backend/tests/faturacao/test_fiscal.py
git commit -m "$(cat <<'EOF'
A fatura que sai com o cliente ligado põe o crédito dos pontos na fila

O finalizar aceita pontos_ligacao e grava-o sempre em dados_pagamento (None
quando não há), como o NIF: uma tentativa falhada com o QR de alguém não
deixa essa pessoa agarrada à venda. No fim de _ligar_venda_ao_documento, num
try à parte do stock, a FS em modo normal enfileira credito:{documento} com o
corpo do contrato da app (total, caução, meios de pagamento pelo id Vendus).

O id do Vendus passa a ir no retrato do pagamento gravado na venda, como o
nome e o tipo fiscal: é por essa lista que a app recusa Uber Eats, Glovo e
Bolt, e reconstruí-la mais tarde de fat_tipos_pagamento encolhia-a em
silêncio — a recusa a falhar aberta numa venda reconciliada dias depois.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: Validação por mutação (cinco guardas)**

Uma de cada vez, com `tests/faturacao/test_os_pontos_da_app.py`; depois de cada uma, `git checkout -- backend/faturacao/fiscal.py backend/faturacao/pontos_app.py`.

1. **Sempre presente:** em `fiscal.py`, apagar a linha `        "pontos_ligacao": dados.pontos_ligacao.model_dump() if dados.pontos_ligacao else None,` e pôr, logo a seguir ao `}` do dicionário, `    if dados.pontos_ligacao:` / `        dados_pagamento["pontos_ligacao"] = dados.pontos_ligacao.model_dump()`. Esperado: FAILED `test_sem_ligacao_o_finalizar_grava_pontos_ligacao_a_None_por_cima_da_antiga` (o Rui fica e a fila ganha uma linha).
2. **Modo tests:** em `enfileirar_credito`, apagar as duas linhas `    if documento.get("modo") != "normal":` / `        return`. Esperado: FAILED `test_um_documento_em_modo_tests_nunca_enfileira`.
3. **Except genérico:** no gancho de `fiscal.py`, trocar `    except Exception as e:  # noqa: BLE001 — os pontos nunca podem parar uma fatura` por `    except KeyError as e:  # noqa: BLE001 — os pontos nunca podem parar uma fatura`. Esperado: FAILED `test_os_pontos_a_rebentar_nao_impedem_a_venda_de_ficar_emitida` (RuntimeError sobe) e `test_o_enganche_dos_pontos_esta_dentro_de_um_except_generico`.
4. **O id do Vendus vem do retrato:** em `enfileirar_credito`, trocar `        identificador = pagamento.get("vendus_payment_method_id")` por `        identificador = None`. Esperado: FAILED `test_o_id_do_VENDUS_vem_do_retrato_da_venda_mesmo_sem_o_tipo_de_pagamento` (`meios_pagamento` vazio — a lista encolheu e a app deixava de poder recusar a plataforma).
5. **A lista não encolhe em silêncio:** em `enfileirar_credito`, apagar o `else:` inteiro (as 5 linhas do comentário e o `logger.error`). Esperado: FAILED `test_um_pagamento_sem_id_do_vendus_nao_encolhe_a_lista_em_SILENCIO` (o `caplog` vem vazio).

No fim: Step 4 outra vez verde, `git status --short` limpo.

---

### Task 4: O estorno na nota de crédito

**Files:**
- Modify: `backend/faturacao/nota_credito.py:1414-1416` (a seguir ao `$set` de `emitida`)
- Modify: `backend/faturacao/pontos_app.py` (imports; fim)
- Modify: `backend/tests/faturacao/test_os_pontos_da_app.py` (fim)

**Interfaces:**
- Consumes: `pontos_app._linha_nova`, `_enfileirar` (Task 2); a linha `credito:{documento_id}` (Task 3), com `payload["atcud"]` e `primeiro_nome`; em `emitir_nota_credito`, `nota` (`id`, `documento_id` = FS de origem, `venda_id`, `total` somado em cêntimos, `linhas[]` com `tax_id` e `total`) e `documento_nc` (`id`, `numero`, `modo`); `precos.CODIGO_NAO_SUJEITO == "NS"` (só o depósito de embalagem é NS).
- Produces: `async def pontos_app.enfileirar_estorno(db, nota: Dict, documento_nc: Dict, *, agora: Optional[datetime] = None) -> None` — linha `estorno:{documento_nc.id}` com payload `{atcud_origem, nc_id, numero_nc, valor_nc, caucao_nc}`.

- [ ] **Step 1: Escrever os testes que falham**

**Acrescentar ao fim de** `backend/tests/faturacao/test_os_pontos_da_app.py`:

```python


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
```

- [ ] **Step 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && PYTHONDONTWRITEBYTECODE=1 /Users/matheus.moraes/Developer/RH/backend/.venv/bin/python -m pytest -p no:cacheprovider -q tests/faturacao/test_os_pontos_da_app.py
```

Esperado: `6 failed, 60 passed` (66 recolhidos) — `AttributeError: ... has no attribute 'enfileirar_estorno'` nos quatro directos e no `monkeypatch.setattr` dos dois da rota.

- [ ] **Step 3: Implementar**

**Em** `backend/faturacao/pontos_app.py`, **substituir:**

```python
from .pos_auth import operador_atual
```

**por:**

```python
from .pos_auth import operador_atual
from .precos import CODIGO_NAO_SUJEITO
```

**Acrescentar ao fim de** `backend/faturacao/pontos_app.py`:

```python


# --- O estorno, na nota de crédito ----------------------------------------------


async def enfileirar_estorno(db, nota: Dict, documento_nc: Dict, *,
                             agora: Optional[datetime] = None) -> None:
    """Põe na fila o estorno desta nota de crédito, se a fatura de origem tiver
    uma linha de crédito. Chamado em `nota_credito.emitir_nota_credito`, logo a
    seguir à marca `emitida`.

    Não interessa aqui se o crédito já chegou à app: a linha entra na mesma, e
    é o ENVIO que espera por ele (ou a fecha `sem_efeito` se ele nunca entrar).

    **A caução da nota são as linhas `NS`.** O depósito de embalagem é a única
    coisa deste POS fora do imposto (`precos.CODIGO_NAO_SUJEITO`), e a nota
    credita-o como qualquer outra linha da fatura. Os pontos contam sem ela,
    por isso a app precisa de a saber para tirar a proporção certa. Somada em
    cêntimos inteiros, como todo o dinheiro deste módulo."""
    if documento_nc.get("modo") != "normal":
        return
    credito = await db[COLECOES["pontos_app"]].find_one(
        {"chave": "credito:%s" % nota["documento_id"]}, {"_id": 0})
    if not credito:
        return
    caucao_em_centimos = sum(
        round(float(linha.get("total") or 0) * 100)
        for linha in nota.get("linhas") or []
        if linha.get("tax_id") == CODIGO_NAO_SUJEITO
    )
    payload = {
        "atcud_origem": credito["payload"]["atcud"],
        "nc_id": documento_nc["id"],
        "numero_nc": documento_nc.get("numero"),
        "valor_nc": round(float(nota.get("total") or 0), 2),
        "caucao_nc": caucao_em_centimos / 100.0,
    }
    await _enfileirar(db, _linha_nova(
        "estorno", "estorno:%s" % documento_nc["id"], payload,
        agora or datetime.now(timezone.utc),
        documento_id=nota["documento_id"], nc_documento_id=documento_nc["id"],
        venda_id=nota.get("venda_id"), primeiro_nome=credito.get("primeiro_nome")))
```

**Em** `backend/faturacao/nota_credito.py`, **substituir:**

```python
            "emitido_em": documento_nc.get("emitido_em"),
        }},
    )
```

**por:**

```python
            "emitido_em": documento_nc.get("emitido_em"),
        }},
    )
    # **OS PONTOS DESTA DEVOLUÇÃO**, logo a seguir à marca `emitida` e antes
    # do papel: se a fatura de origem deu pontos pela app, a nota tira-lhos na
    # proporção do que devolve (a conta é da app). Nada aqui pode estragar uma
    # nota de crédito REAL já entregue à AT — um 500 era o ecrã a convidar a
    # operadora a devolver o dinheiro outra vez. O import é local pela razão do
    # `fiscal.py`.
    try:
        from .pontos_app import enfileirar_estorno
        await enfileirar_estorno(db, nota, documento_nc)
    except Exception as e:  # noqa: BLE001 — os pontos nunca podem parar uma devolução
        logger.error(
            "[faturacao] a nota de crédito %s saiu mas o estorno dos pontos L'Açaí "
            "não entrou na fila: %s", nota["id"], e,
        )
```

- [ ] **Step 4: Correr e ver passar (com as notas de crédito)**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && PYTHONDONTWRITEBYTECODE=1 /Users/matheus.moraes/Developer/RH/backend/.venv/bin/python -m pytest -p no:cacheprovider -q tests/faturacao/test_os_pontos_da_app.py tests/faturacao/test_nota_credito.py
```

Esperado: tudo verde (`test_os_pontos_da_app.py` com 66; `183 passed` no total dos dois ficheiros — 66 + 117). As notas do `test_nota_credito.py` são de faturas em modo `tests` e sem linha de crédito: o gancho sai logo.

- [ ] **Step 5: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos
git add backend/faturacao/nota_credito.py backend/faturacao/pontos_app.py backend/tests/faturacao/test_os_pontos_da_app.py
git commit -m "$(cat <<'EOF'
A nota de crédito de uma fatura com pontos põe o estorno na fila

Logo a seguir à marca emitida, num try que engole tudo, a NC em modo normal
enfileira estorno:{nc} se a FS de origem tiver linha de crédito: valor da
nota, caução (as linhas NS, somadas em cêntimos) e o ATCUD da fatura. O envio
já espera pelo crédito feito.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: Validação por mutação (três guardas)**

Uma de cada vez, com `tests/faturacao/test_os_pontos_da_app.py`; depois de cada uma, `git checkout -- backend/faturacao/nota_credito.py backend/faturacao/pontos_app.py`.

1. **Caução só das linhas NS:** em `enfileirar_estorno`, apagar a linha `        if linha.get("tax_id") == CODIGO_NAO_SUJEITO`. Esperado: FAILED `test_a_nota_de_uma_fatura_com_pontos_enfileira_o_estorno_com_o_contrato_da_app` (`caucao_nc` 10.4 em vez de 0.2).
2. **Except genérico:** em `nota_credito.py`, trocar `    except Exception as e:  # noqa: BLE001 — os pontos nunca podem parar uma devolução` por `    except KeyError as e:  # noqa: BLE001 — os pontos nunca podem parar uma devolução`. Esperado: FAILED `test_os_pontos_a_rebentar_nao_estragam_a_nota_de_credito`.
3. **Depois da marca `emitida`:** mover o bloco inteiro do gancho (do comentário `# **OS PONTOS DESTA DEVOLUÇÃO**` ao fim do `except`) para logo ANTES de `    await db[COLECOES["notas_credito"]].update_one(` que escreve `"estado": "emitida"`. Esperado: FAILED `test_a_rota_da_nota_enfileira_o_estorno_DEPOIS_de_a_marcar_emitida` (vê `reservada`).

No fim: Step 4 outra vez verde, `git status --short` limpo.

---

### Task 5: A volta do cron (rota + script)

**Files:**
- Modify: `backend/faturacao/pontos_app.py` (imports; fim)
- Create: `faturacao-pontos-cron.sh` (executável)
- Modify: `backend/tests/faturacao/test_protecao_rotas.py:56-61`
- Modify: `backend/tests/faturacao/test_os_pontos_da_app.py` (fim)
- Modify: `backend/.env.example` (fim)

**Interfaces:**
- Consumes: `pontos_app.enviar(db, linha_id=None, *, agora=None) -> Optional[Dict]` (Task 2); `obter_db()`; `CRON_KEY` do ambiente (o padrão de `sincronizacao_rota.cron_sincronizar_app`).
- Produces: `POST /api/faturacao/cron/pontos-app?key=...` → `async def cron_pontos_app(key: str) -> dict` = `{"enviadas": int}`; `pontos_app._LIMITE_POR_VOLTA = 50`; `faturacao-pontos-cron.sh`.

- [ ] **Step 1: Escrever os testes que falham**

**Em** `backend/tests/faturacao/test_protecao_rotas.py`, **substituir:**

```python
                 "/api/faturacao/cron/sincronizar-app"}
```

**por:**

```python
                 "/api/faturacao/cron/sincronizar-app",
                 # O envio dos pontos L'Açaí à app, de 1 em 1 minuto. Mesma
                 # guarda, com testes próprios em `test_os_pontos_da_app.py`.
                 "/api/faturacao/cron/pontos-app"}
```

**Acrescentar ao fim de** `backend/tests/faturacao/test_os_pontos_da_app.py`:

```python


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
    """O endereço LIDO do script e resolvido contra o router — nunca afirmado
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
```

- [ ] **Step 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && PYTHONDONTWRITEBYTECODE=1 /Users/matheus.moraes/Developer/RH/backend/.venv/bin/python -m pytest -p no:cacheprovider -q tests/faturacao/test_os_pontos_da_app.py tests/faturacao/test_protecao_rotas.py
```

Esperado: `7 failed, 69 passed` (76 recolhidos) — os 4 da rota (`AttributeError: ... has no attribute 'cron_pontos_app'`), os 2 do script (`FileNotFoundError`) e `test_protecao_rotas.py::test_saude_e_o_bootstrap_do_pos_sao_as_unicas_rotas_sem_guarda` (a lista espera uma porta que ainda não existe).

- [ ] **Step 3: Implementar a rota, o script e a documentação**

**Em** `backend/faturacao/pontos_app.py`, **substituir:**

```python
import os
import uuid
```

**por:**

```python
import os
import secrets
import uuid
```

**Em** `backend/faturacao/pontos_app.py`, **substituir:**

```python
from fastapi import APIRouter, Depends, HTTPException
```

**por:**

```python
from fastapi import APIRouter, Depends, HTTPException, Query
```

**Acrescentar ao fim de** `backend/faturacao/pontos_app.py`:

```python


# --- A volta do cron -------------------------------------------------------------

# O tecto de linhas por volta. Com a app em baixo, cada linha pode gastar os 4 s
# do pedido: 50 são 200 s no pior caso, e duas voltas sobrepostas não se pisam
# (a reserva decide). Num dia normal a volta encontra zero ou uma.
_LIMITE_POR_VOLTA = 50


@router.post("/cron/pontos-app")
async def cron_pontos_app(key: str = Query(...)) -> dict:
    """A porta de 1 em 1 minuto (`faturacao-pontos-cron.sh`). Protegida pela
    `CRON_KEY`, sem JWT — o mesmo padrão de `/cron/sincronizar-app`: sem a
    variável no ambiente ninguém entra, e `compare_digest` para o tempo da
    comparação não dizer quantos caracteres estavam certos.

    Envia uma a uma as linhas pendentes que já chegaram à hora e pára quando
    não houver mais nenhuma — uma linha que falha fica com a próxima tentativa
    no futuro, por isso a mesma volta não lhe volta a pegar."""
    chave = os.environ.get("CRON_KEY")
    if not chave or not secrets.compare_digest(str(key), str(chave)):
        raise HTTPException(status_code=403, detail="Acesso negado.")
    db = obter_db()
    enviadas = 0
    for _ in range(_LIMITE_POR_VOLTA):
        if await enviar(db) is None:
            break
        enviadas += 1
    return {"enviadas": enviadas}
```

**Criar** `faturacao-pontos-cron.sh`:

```bash
#!/usr/bin/env bash
# Pontos L'Acai dados na caixa — de 1 em 1 minuto.
#
# Envia a app L'Acai as linhas da fila fat_pontos_app que estao pendentes e ja
# chegaram a hora: o credito de cada fatura das lojas em que a funcionaria leu
# o QR da app, e o estorno de cada nota de credito dessas faturas. A tentativa
# imediata sai logo a seguir a fatura, em segundo plano; este cron e a rede
# para quando a app estava em baixo e para o que um reinicio deixou a meio.
#
# De 1 em 1 minuto e nao de 5: e o tempo que o cliente espera entre pagar e ver
# os pontos na app. Uma volta sem nada para enviar e uma leitura ao Mongo.
#
# Uma linha que falha espera 1, 2, 5, 10 e depois 30 minutos, e passa a
# "falhado" ao fim de 24 h A FALHAR - contadas da primeira falha tecnica e nao
# do nascimento da linha (o backoffice mostra-o no detalhe da fatura). Sem
# APP_LACAI_URL/APP_LACAI_CHAVE no .env espera, sem gastar tentativas, e nao se
# perde nada: e por isso que a ordem de arranque poe a app a andar primeiro.
#
# Corre DENTRO do contentor backend (localhost:8000, sem o proxy pelo meio), no
# mesmo padrao dos outros crons desta casa. A CRON_KEY vem do ambiente do
# contentor, nunca do crontab.
#
# Instalar (no servidor), UMA vez:
#   crontab -e
#   * * * * *  /root/RH/faturacao-pontos-cron.sh >> /var/log/rh-pontos-app.log 2>&1
cd /root/RH || exit 1
docker compose exec -T backend python -c 'import os, urllib.request as u; print(u.urlopen(u.Request("http://localhost:8000/api/faturacao/cron/pontos-app?key="+os.environ["CRON_KEY"], method="POST"), timeout=300).read().decode()[:400])'
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) envio dos pontos da app disparado"
```

```bash
cd /Users/matheus.moraes/Developer/RH-pontos && chmod +x faturacao-pontos-cron.sh
```

**Acrescentar ao fim de** `backend/.env.example`:

```bash

# ============================================================================
# Pontos L'Açaí dados na caixa (faturacao/pontos_app.py)
# ============================================================================
# O POS lê o QR da app do cliente e, depois de a fatura sair, credita-lhe os
# pontos na app L'Açaí; a nota de crédito retira-os. Fala com o servidor da
# app pela rede interna, com a chave partilhada que lá se chama
# POS_INTEGRACAO_CHAVE. Sem as duas variáveis o «Ler QR» responde que a app não
# está disponível, e o que estiver na fila espera — nada se perde.
# NOTA: sem aspas — o docker-compose lê o .env literalmente.
# Em produção: APP_LACAI_URL=http://olacai-api:8001
APP_LACAI_URL=
APP_LACAI_CHAVE=
#
# Cron (no servidor), de 1 em 1 minuto — reutiliza a CRON_KEY acima:
#   * * * * *  /root/RH/faturacao-pontos-cron.sh >> /var/log/rh-pontos-app.log 2>&1
```

- [ ] **Step 4: Correr e ver passar**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && PYTHONDONTWRITEBYTECODE=1 /Users/matheus.moraes/Developer/RH/backend/.venv/bin/python -m pytest -p no:cacheprovider -q tests/faturacao/test_os_pontos_da_app.py tests/faturacao/test_protecao_rotas.py
```

Esperado: `76 passed` (72 em `test_os_pontos_da_app.py`, 4 em `test_protecao_rotas.py`).

- [ ] **Step 5: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos
git add backend/faturacao/pontos_app.py faturacao-pontos-cron.sh backend/tests/faturacao/test_protecao_rotas.py backend/tests/faturacao/test_os_pontos_da_app.py backend/.env.example
git ls-files -s faturacao-pontos-cron.sh   # tem de começar por 100755
git commit -m "$(cat <<'EOF'
Ligar o envio dos pontos da app de 1 em 1 minuto

POST /api/faturacao/cron/pontos-app com a CRON_KEY (403 sem ela, nem a
palavra None a abre) esvazia as linhas pendentes que já chegaram à hora, até
50 por volta. O script corre dentro do contentor, como os outros crons, e o
teste lê o endereço dele e confronta-o com o router.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: Validação por mutação (a porta)**

Em `cron_pontos_app`, trocar `    if not chave or not secrets.compare_digest(str(key), str(chave)):` por `    if not secrets.compare_digest(str(key), str(chave)):`. Correr o Step 4. Esperado: FAILED `test_sem_CRON_KEY_no_ambiente_nem_a_palavra_None_abre_a_porta` (a palavra "None" entra). `git checkout -- backend/faturacao/pontos_app.py`, Step 4 verde, `git status --short` limpo.

---

### Task 6: Os pontos no detalhe do documento do backoffice

**Files:**
- Modify: `backend/faturacao/pontos_app.py` (fim)
- Modify: `backend/faturacao/documentos.py:88-89` (import) e `:838-848` (`documento_do_backoffice`)
- Modify: `backend/tests/faturacao/test_documentos_do_backoffice.py` (fim)

**Interfaces:**
- Consumes: linhas de `fat_pontos_app` (Tasks 2-4); `documentos._detalhe_do_documento(db, documento, com_contexto=True) -> dict` (partilhado com o POS — NÃO se mexe nele).
- Produces: `async def pontos_app.pontos_app_do_documento(db, documento: Dict) -> Optional[Dict]`; `GET /api/faturacao/documentos/{documento_id}` devolve também `pontos_app: None | {"tipo", "estado", "pontos", "primeiro_nome", "motivo", "tentativas", "ultimo_erro", "atualizado_em"}` (é isto que o ecrã do C2 lê).

- [ ] **Step 1: Escrever os testes que falham**

**Em** `backend/tests/faturacao/test_documentos_do_backoffice.py`, **substituir:**

```python
from faturacao.documentos import documento_do_backoffice, documentos_do_backoffice
```

**por:**

```python
from faturacao.documentos import (
    documento_do_backoffice, documentos_do_backoffice, obter_documento,
)
```

**Acrescentar ao fim de** `backend/tests/faturacao/test_documentos_do_backoffice.py`:

```python


# --- Os pontos L'Açaí no detalhe ------------------------------------------------


def _linha_de_pontos(chave, **over):
    linha = {
        "id": "p-" + chave, "chave": chave, "tipo": chave.split(":")[0],
        "estado": "feito", "pontos": 17, "primeiro_nome": "Ana", "motivo": None,
        "tentativas": 1, "ultimo_erro": None, "atualizado_em": "2026-09-15T12:00:05+00:00",
        "payload": {"ligacao_id": "lig-1", "atcud": "ATCUD-d1"},
        "a_enviar_ate": "1970-01-01T00:00:00+00:00",
    }
    linha.update(over)
    return linha


def _com_pontos(db, *linhas):
    db._coleccoes[COLECOES["pontos_app"]] = ColeccaoFalsa([], list(linhas))


def test_o_detalhe_da_fatura_diz_os_pontos_da_app(monkeypatch):
    db = _db(monkeypatch,
             [_documento("d1", "FS 1/1", 10.20, "2026-08-10T12:00:00+00:00", venda_id="v1")],
             vendas=[_venda("v1")])
    _com_pontos(db, _linha_de_pontos("credito:d1"))

    r = _corre(documento_do_backoffice("d1", _={}))

    assert r["pontos_app"] == {
        "tipo": "credito", "estado": "feito", "pontos": 17, "primeiro_nome": "Ana",
        "motivo": None, "tentativas": 1, "ultimo_erro": None,
        "atualizado_em": "2026-09-15T12:00:05+00:00",
    }


def test_o_detalhe_da_nota_de_credito_mostra_o_ESTORNO_dela_e_nao_o_credito_da_fatura(monkeypatch):
    db = _db(monkeypatch,
             [_documento("n1", "NC 1/1", 10.20, "2026-08-11T12:00:00+00:00", tipo="NC")])
    _com_pontos(db,
                _linha_de_pontos("credito:d1"),
                _linha_de_pontos("estorno:n1", estado="pendente", pontos=None, tentativas=3,
                                 ultimo_erro="HTTP 503: em baixo"))

    r = _corre(documento_do_backoffice("n1", _={}))

    assert (r["pontos_app"]["tipo"], r["pontos_app"]["estado"]) == ("estorno", "pendente")
    assert (r["pontos_app"]["tentativas"], r["pontos_app"]["ultimo_erro"]) == (3, "HTTP 503: em baixo")


def test_uma_fatura_sem_app_mostrada_tem_pontos_app_a_None(monkeypatch):
    db = _db(monkeypatch,
             [_documento("d1", "FS 1/1", 10.20, "2026-08-10T12:00:00+00:00", venda_id="v1")],
             vendas=[_venda("v1")])
    _com_pontos(db, _linha_de_pontos("credito:outro"))
    assert _corre(documento_do_backoffice("d1", _={}))["pontos_app"] is None


def test_o_corpo_enviado_a_app_nao_sai_para_o_ecra(monkeypatch):
    """O `payload` leva a ligação do cliente; o ecrã não precisa dela."""
    db = _db(monkeypatch,
             [_documento("d1", "FS 1/1", 10.20, "2026-08-10T12:00:00+00:00", venda_id="v1")],
             vendas=[_venda("v1")])
    _com_pontos(db, _linha_de_pontos("credito:d1"))
    r = _corre(documento_do_backoffice("d1", _={}))
    assert "payload" not in r["pontos_app"] and "lig-1" not in str(r)


def test_o_detalhe_do_POS_continua_SEM_a_linha_dos_pontos(monkeypatch):
    """A promessa feita ao C2: o `GET /pos/documentos/{id}` fica igual — o
    balcão não mostra pontos e o `lib/pos.js` não os lê.

    O montador (`_detalhe_do_documento`) é o MESMO para as duas rotas, e a
    linha nova está a um `resposta[...] =` de distância de escorregar para lá:
    é este teste que prende a promessa."""
    db = _db(monkeypatch,
             [_documento("d1", "FS 1/1", 10.20, "2026-08-10T12:00:00+00:00", venda_id="v1")],
             vendas=[_venda("v1")])
    _com_pontos(db, _linha_de_pontos("credito:d1"))

    do_pos = _corre(obter_documento("d1", operador={"loja_id": "loja-1"}))

    assert "pontos_app" not in do_pos
    assert "Ana" not in str(do_pos)
```

- [ ] **Step 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && PYTHONDONTWRITEBYTECODE=1 /Users/matheus.moraes/Developer/RH/backend/.venv/bin/python -m pytest -p no:cacheprovider -q tests/faturacao/test_documentos_do_backoffice.py
```

Esperado: `4 failed, 18 passed` (22 recolhidos) — `KeyError: 'pontos_app'` nos quatro. O `test_o_detalhe_do_POS_continua_SEM_a_linha_dos_pontos` já passa (ninguém a acrescentou ainda) — é o travão da mutação 3 do Step 6.

- [ ] **Step 3: Implementar**

**Acrescentar ao fim de** `backend/faturacao/pontos_app.py`:

```python


# --- O backoffice ---------------------------------------------------------------


async def pontos_app_do_documento(db, documento: Dict) -> Optional[Dict]:
    """A linha «Pontos L'Açaí» do detalhe de um documento no backoffice: numa
    fatura o crédito, numa nota de crédito o estorno DELA. `None` quando não há
    linha nenhuma — o cliente não mostrou a app.

    Só os campos que o ecrã escreve («17 pontos para Ana», «A tentar enviar (3
    tentativas — último erro: …)», «Recusado: pagamento por plataforma»). O
    corpo enviado à app fica de fora: tem a ligação do cliente, e o ecrã não
    precisa dela para nada."""
    tipo = "estorno" if documento.get("tipo") == "NC" else "credito"
    linha = await db[COLECOES["pontos_app"]].find_one(
        {"chave": "%s:%s" % (tipo, documento.get("id"))}, {"_id": 0})
    if not linha:
        return None
    return {campo: linha.get(campo) for campo in (
        "tipo", "estado", "pontos", "primeiro_nome", "motivo",
        "tentativas", "ultimo_erro", "atualizado_em")}
```

**Em** `backend/faturacao/documentos.py`, **substituir:**

```python
from .periodos import janela_de_datas
from .pos_auth import operador_atual
```

**por:**

```python
from .periodos import janela_de_datas
from .pontos_app import pontos_app_do_documento
from .pos_auth import operador_atual
```

**Em** `backend/faturacao/documentos.py`, **substituir:**

```python
    """A MESMA fatura que o POS mostra — mesmo montador, sem o âmbito da loja
    (o gestor vê todas)."""
    db = obter_db()
    documento = await db[COLECOES["documentos"]].find_one({"id": documento_id})
    if not documento:
        raise HTTPException(status_code=404, detail="Documento não encontrado")
    return await _detalhe_do_documento(db, documento, com_contexto=True)
```

**por:**

```python
    """A MESMA fatura que o POS mostra — mesmo montador, sem o âmbito da loja
    (o gestor vê todas).

    Mais a linha **«Pontos L'Açaí»** (`pontos_app`), que só o gestor vê: numa
    fatura o crédito, numa nota de crédito o estorno dela, `None` quando o
    cliente não mostrou a app. O balcão não precisa dela e o POS não a lê."""
    db = obter_db()
    documento = await db[COLECOES["documentos"]].find_one({"id": documento_id})
    if not documento:
        raise HTTPException(status_code=404, detail="Documento não encontrado")
    resposta = await _detalhe_do_documento(db, documento, com_contexto=True)
    resposta["pontos_app"] = await pontos_app_do_documento(db, documento)
    return resposta
```

(O import no topo de `documentos.py` não fecha ciclo nenhum: `pontos_app` só importa `db`, `pos_auth`, `precos` e `venda`, e nenhum deles importa `documentos`.)

- [ ] **Step 4: Correr e ver passar**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && PYTHONDONTWRITEBYTECODE=1 /Users/matheus.moraes/Developer/RH/backend/.venv/bin/python -m pytest -p no:cacheprovider -q tests/faturacao/test_documentos_do_backoffice.py tests/faturacao/test_documentos.py tests/faturacao/test_os_pontos_da_app.py tests/faturacao/test_nota_credito.py
```

Esperado: `247 passed` (22 em `test_documentos_do_backoffice.py`, 36 em `test_documentos.py`, 72 em `test_os_pontos_da_app.py`, 117 em `test_nota_credito.py`).

- [ ] **Step 5: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos
git add backend/faturacao/pontos_app.py backend/faturacao/documentos.py backend/tests/faturacao/test_documentos_do_backoffice.py
git commit -m "$(cat <<'EOF'
O detalhe do documento no backoffice diz o que aconteceu aos pontos da app

GET /api/faturacao/documentos/{id} ganha pontos_app: numa fatura a linha do
crédito, numa nota de crédito o estorno dela, None sem app mostrada. Só os
campos que o ecrã escreve — o corpo enviado à app, com a ligação do cliente,
não sai. O detalhe do POS fica igual.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: Validação por mutação**

1. Em `pontos_app_do_documento`, trocar `    tipo = "estorno" if documento.get("tipo") == "NC" else "credito"` por `    tipo = "credito"`. Correr o Step 2. Esperado: FAILED `test_o_detalhe_da_nota_de_credito_mostra_o_ESTORNO_dela_e_nao_o_credito_da_fatura`. `git checkout -- backend/faturacao/pontos_app.py`.
2. Trocar `    return {campo: linha.get(campo) for campo in (` por `    return linha or {campo: linha.get(campo) for campo in (`. Esperado: FAILED `test_o_detalhe_da_fatura_diz_os_pontos_da_app` e `test_o_corpo_enviado_a_app_nao_sai_para_o_ecra`. `git checkout -- backend/faturacao/pontos_app.py`.
3. **O POS fica igual:** em `documentos.py`, na rota `obter_documento`, trocar

   ```python
       return await _detalhe_do_documento(db, documento)
   ```

   por

   ```python
       resposta = await _detalhe_do_documento(db, documento)
       resposta["pontos_app"] = await pontos_app_do_documento(db, documento)
       return resposta
   ```

   Correr o Step 2. Esperado: FAILED `test_o_detalhe_do_POS_continua_SEM_a_linha_dos_pontos`. `git checkout -- backend/faturacao/documentos.py`.

Step 4 verde, `git status --short` limpo.

---

### Task 7: A suite inteira

**Files:** nenhum.

- [ ] **Step 1: Confirmar o ambiente**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos
ls -la frontend/node_modules    # symlink para ~/Developer/RH/frontend/node_modules
git status --short              # limpo
```

Se o `node_modules` não existir: `ln -sfn /Users/matheus.moraes/Developer/RH/frontend/node_modules frontend/node_modules`. Sem ele a suite salta os testes de ecrã EM SILÊNCIO.

- [ ] **Step 2: Correr tudo (sem nenhum outro pytest a correr nesta árvore ao mesmo tempo)**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && PYTHONDONTWRITEBYTECODE=1 /Users/matheus.moraes/Developer/RH/backend/.venv/bin/python -m pytest -p no:cacheprovider -q tests 2>&1 | tail -5
```

Esperado: `0 failed`, `passed` = linha de base + **77** (72 novos em `test_os_pontos_da_app.py` e 5 em `test_documentos_do_backoffice.py`; o `test_fiscal.py` fica nos mesmos 229 — a alteração lá é a uma afirmação, não um teste novo). A linha de base medida neste ramo a 2026-09-16 foi `3138 passed, 0 skipped`, logo **3215**. E `skipped` IGUAL ao da linha de base. Ler os dois números — um `skipped` que subiu é ambiente, não código, e é sempre a favor do falso verde.

- [ ] **Step 3: Conferir o que ficou no ramo**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos && git log --oneline origin/main..HEAD && git diff --stat origin/main..HEAD -- backend faturacao-pontos-cron.sh
```

Esperado: os 6 commits deste plano por cima do da spec; ficheiros tocados = os da secção File Structure, e nada em `frontend/`.

---

## Decisões tomadas neste plano (por falta de informação na spec)

1. **`operador_nome` do crédito** = nome do dono da CONTA (`venda.operador_id` → `fat_utilizadores`), o mesmo que o backoffice mostra no documento. O gancho da emissão não tem o token de quem carregou em EMITIR; a app já guarda na ligação quem LEU o QR.
2. **`meios_pagamento`** = `vendus_payment_method_id` de cada pagamento da venda, lido do RETRATO gravado na venda pelo `finalizar` (campo novo nesta ronda, ao lado do `nome` e do `tipo_fiscal`), com a releitura de `fat_tipos_pagamento` só como recuo para vendas antigas; enviado como **texto** (é como está gravado; a app faz `int()`). Reler os tipos no instante de enfileirar era o defeito: a app recusa as plataformas só por esta lista, e uma lista encurtada por um tipo que o gestor apagou fazia a guarda falhar ABERTA — na emissão feliz a janela é de milissegundos, mas o mesmo gancho corre na reconciliação de uma reserva presa, dias depois. Um pagamento sem id nenhum fica de fora, mas com `logger.error` — nunca em silêncio.
3. **`caucao_nc`** = soma, em cêntimos, das linhas creditadas com `tax_id == "NS"` (o depósito é a única coisa NS). **`valor_nc`** = `nota["total"]` (a soma do servidor, com a caução), não o `total` que o Vendus devolveu. **`nc_id`** = id do documento da NC em `fat_documentos` (o mesmo da chave `estorno:`), não o `intencao_id`.
4. **Estorno à espera do crédito** não gasta tentativas nem passa a `falhado` por esperar; o crédito resolve-se primeiro (nasce antes). **Sem configuração** é o mesmo caso: espera de 1 em 1 minuto, sem gastar tentativa, e nunca passa a `falhado`.
   E **as 24 h contam-se da primeira falha TÉCNICA** (`primeira_falha_tecnica_em`), nunca de `criado_em`: é a diferença entre «a app esteve 24 h em baixo, desisto» e «esta linha existe há 24 h». Uma linha que tenha esperado pela configuração ou pelo crontab desistia à primeira falha real, com a app em baixo 4 segundos, e os pontos daquela compra perdiam-se para sempre — com o backoffice a escrever «Falhou ao fim de 24 h», que era falso sobre o que tinha acontecido.
5. **NC em modo `tests`** não enfileira estorno (guarda a mais, simétrica à do crédito).
6. **`primeiro_nome`** gravado na linha da fila (campo além do documento da spec) para o backoffice não ter de perguntar à app.
7. **Reserva de 60 s** e **50 linhas por volta** do cron; datas da fila em ISO UTC ao segundo; `a_enviar_ate` nasce `"1970-01-01T00:00:00+00:00"` (um `null` não casa com `$lt`).
8. **Um 404 ou 422 no `/creditar`/`/estornar`** conta como erro técnico (volta a tentar-se e acaba `falhado`): o contrato diz que as recusas de negócio são 200. No `/ligar` é a mesma regra pela mesma razão: só é «QR inválido» o 404 que traz o corpo do contrato (`motivo: "qr_invalido"`); um `{"detail": "Not Found"}` do FastAPI da app, ou um 404 em HTML de um proxy, é a app a não estar lá e dá 503 — traduzido para «peça outro QR», a funcionária pedia ao cliente códigos novos que nunca iam funcionar.
9. **Sem verificação do índice único de `fat_pontos_app.chave` no arranque** (ao contrário do das faturas): sem ele, o pior é enviar duas vezes, e a app é idempotente por ATCUD e por `nc_id`.
10. **Um processo que morra entre a marca `emitida` da NC e o gancho** perde o estorno (fica o cliente com os pontos). Não há reconciliação de NC que o apanhe — risco aceite por ser a favor do cliente e raro.
    O simétrico é **contra** o cliente e vale a pena escrevê-lo: **um `insert_one` da linha de crédito que falhe** (Mongo com soluço, disco cheio). O `except Exception` de `fiscal._ligar_venda_ao_documento` engole tudo — e tem de engolir, a fatura já está na AT — mas nada volta a criar a linha: a venda já ficou `emitida` e ligada ao documento, por isso nem a reconciliação lá volta a passar. A fatura sai, a venda fica com `pontos_ligacao`, e o cliente nunca recebe os pontos. Risco aceite **com o socorro escrito**: o `logger.error` do gancho diz a venda, e a pergunta que as encontra todas é «vendas emitidas com `pontos_ligacao` e sem linha `credito:{documento_id}`» — os dois dados existem, e com eles a linha refaz-se à mão ou por um script de uma volta. Fora deste plano por não valer, hoje, um caminho de reconciliação próprio.
11. **Rede entre contentores:** o `docker-compose.yml` do RH não está na rede do `olacai-api`. Pô-los a falar (rede externa partilhada ou URL pública) é do deploy (passo 4 da ordem de arranque), não deste plano.
