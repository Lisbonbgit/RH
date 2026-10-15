"""Variáveis de ambiente que têm de estar definidas ANTES de qualquer módulo de
teste do CRM ser colectado — o mesmo problema de ordem descrito em
tests/faturacao/conftest.py (ler esse docstring).

O pytest colecciona por ordem alfabética, e tests/crm vem ANTES de
tests/faturacao. O pacote `crm` vai importar `faturacao.auth` (T1.4), e com ele
o `faturacao/__init__.py` inteiro, logo `faturacao.pos_auth`, que lê
`POS_JWT_SECRET` de `os.environ` UMA VEZ, à importação. Sem isto aqui, o
conftest da faturação chegava tarde e o POS ficava com `None` na suite inteira.

O mesmo vale para o `server.py` (test_montagem.py, T1.9): lê `JWT_SECRET`,
`MONGO_URL` e `DB_NAME` ao ser importado. Se fosse importado antes de alguém
definir `JWT_SECRET`, congelava o valor por omissão enquanto `faturacao.auth`
lê "segredo-de-teste" do ambiente — e test_seguranca_login.py deixava de bater
certo.

Os valores são EXACTAMENTE os que os testes existentes já usam
(tests/faturacao/conftest.py, tests/faturacao/test_auth.py,
tests/test_seguranca_login.py, tests/fin/*). `setdefault` nunca sobrepõe um
valor que já lá esteja. `teste_sem_ligacao` é um nome de base que nenhum teste
chega a abrir: os testes do CRM usam sempre o duplo da base.

No fim fica a guarda contra o openrouteservice verdadeiro (F3, T3.11): um
fixture `autouse` que nenhum teste do CRM consegue esquecer.
"""
import os

import pytest

os.environ.setdefault("POS_JWT_SECRET", "segredo-de-teste-pos")
os.environ.setdefault("JWT_SECRET", "segredo-de-teste")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")


# --- A guarda contra o openrouteservice verdadeiro (plano F3, T3.11) -----------------------
#
# Nenhum teste do CRM pode fazer um pedido ao openrouteservice (§0, regra 2).
# Por omissão, o cliente (`crm.servicos.ors`) fica com um transporte que só
# regista o pedido e responde 599; no fim de cada teste, um pedido registado
# faz o teste falhar (correção "T3.11 (conftest: guarda contra a rede)": um
# transporte que levantasse uma exceção virava uma `FalhaOrs` e um 503, e um
# teste que esperasse esse 503 passava pelo motivo errado). Quem precisa do
# ORS instala o seu `httpx.MockTransport` (monkeypatch de `ors._transporte`).
#
# A guarda tira também `CRM_ORS_CHAVE` e `CRM_ORS_URL` do ambiente: os testes
# não dependem da shell, e quem precisa de chave põe-na com `setenv`.
#
# Os `import` ficam dentro da função, depois das `setdefault` do topo (o pacote
# `crm` importa o `faturacao`, que lê o ambiente à importação).


ESTADO_DA_GUARDA_ORS = 599
MENSAGEM_DA_GUARDA_ORS = "pedido ao openrouteservice sem o transporte do teste"


def guarda_contra_o_ors(monkeypatch):
    """O gerador do fixture `pedidos_ao_ors_sem_transporte`, à parte para os
    meta-testes o poderem chamar à mão (test_ors.py). Dá a lista dos pedidos
    que chegaram à guarda e, no fim, exige que esteja vazia."""
    import httpx

    from crm.servicos import ors

    pedidos = []

    def _guarda(pedido):
        pedidos.append(pedido)
        return httpx.Response(ESTADO_DA_GUARDA_ORS)

    monkeypatch.delenv(ors.VARIAVEL_CHAVE, raising=False)
    monkeypatch.delenv(ors.VARIAVEL_URL, raising=False)
    monkeypatch.setattr(ors, "_transporte", httpx.MockTransport(_guarda))
    yield pedidos
    assert pedidos == [], MENSAGEM_DA_GUARDA_ORS


@pytest.fixture(autouse=True)
def pedidos_ao_ors_sem_transporte(monkeypatch):
    """Em todos os testes do CRM: a guarda contra o openrouteservice."""
    yield from guarda_contra_o_ors(monkeypatch)
