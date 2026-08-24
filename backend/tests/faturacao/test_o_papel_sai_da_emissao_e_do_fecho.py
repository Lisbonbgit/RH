"""**O fio entre a venda e o papel — percorrido, não lido.**

`test_impressao.py` prova que a fila funciona. Isto prova outra coisa, e é a
que já falhou neste repositório mais do que uma vez: que alguém a CHAMA.

Uma função de enfileirar perfeita e ninguém a chamar é o defeito mais barato
de escrever e o mais caro de descobrir — descobre-se ao balcão, com o cliente
à frente e o talão que nunca sai. Por isso aqui não se chama `enfileirar`:
chama-se a **rota real** (`fiscal.finalizar`, `caixa.fechar_caixa`), com os
duplos que os testes dessas rotas já usam, e olha-se para a fila no fim.

E prova-se a promessa inversa, que é a mais importante das duas:
**a fatura continua boa quando a impressão falha.** O talão é consequência do
documento fiscal, nunca condição dele.
"""
import base64

import pytest

from faturacao import db as db_mod
from faturacao import impressao as imp
from faturacao.db import COLECOES

from . import test_fiscal as tf
from .test_venda import ColeccaoFalsa, DbFalsa, _corre


@pytest.fixture(autouse=True)
def _indice_confirmado():
    """A rota `finalizar` recusa emitir sem o índice de idempotência
    confirmado no arranque (I3). É a mesma marca que `test_fiscal.py` põe, e
    é posta aqui pela mesma razão: sem ela estes testes mediam o 503 da
    configuração em falta e nunca chegavam ao papel."""
    db_mod.marcar_indice_idempotencia(True)
    yield
    db_mod.marcar_indice_idempotencia(None)


def _chave_do_trabalho(doc):
    return doc.get("chave")


def _com_fila(db):
    """Acrescenta a colecção da fila ao duplo de `test_fiscal`, com o índice
    único a ser cumprido — é ele que decide se a mesma emissão a passar duas
    vezes faz um talão ou dois."""
    db._coleccoes[COLECOES["trabalhos_impressao"]] = ColeccaoFalsa(
        [], [], unico=_chave_do_trabalho)
    return db


def _fila(db):
    return db._coleccoes[COLECOES["trabalhos_impressao"]]._documentos


# --- A emissão ----------------------------------------------------------------


def _finalizar(db, monkeypatch):
    tf._configura_vendus_env(monkeypatch)
    monkeypatch.setattr(tf.fiscal_mod, "obter_db", lambda: db)
    monkeypatch.setattr(
        tf.fiscal_mod, "ClienteEmissaoVendus", tf.ClienteEmissaoVendusFalso)
    tf.ClienteEmissaoVendusFalso.instancias.clear()
    return _corre(tf.finalizar(
        "venda-1",
        tf.PedidoFinalizarVenda(pagamentos=[
            tf.PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)]),
        operador=tf._operador(),
    ))


def _db_de_venda():
    return _com_fila(tf._db(
        vendas=[tf._venda(linhas=[tf._linha()])],
        tipos_pagamento=[tf._tipo_pagamento()],
    ))


def test_FINALIZAR_uma_venda_poe_UM_papel_na_fila_e_e_o_do_CLIENTE(monkeypatch):
    """O caminho inteiro: a rota que a operadora toca, o Vendus a devolver o
    documento, e o papel na fila da loja. **Um, e não dois.**

    O dono corrigiu o pressuposto de que esta rota partia: «não tem nada a
    ver com fatura, o staff é o único que faz a impressão do pedido». A ficha
    da cozinha sai quando alguém carrega em «Imprimir Pedido»
    (`impressao.imprimir_pedido`) — que é como um balcão trabalha: pica-se,
    manda-se para a cozinha, cobra-se no fim. Emitir a fatura já não manda
    papel nenhum à cozinha; se mandasse, uma conta dividida por três mandava
    três fichas do mesmo copo.

    Apagar a linha do `finalizar` que enfileira deixa todo o
    `test_impressao.py` verde — a fila continua perfeita, e o cliente fica
    sem o documento em papel que a lei lhe deve."""
    db = _db_de_venda()
    resultado = _finalizar(db, monkeypatch)
    assert resultado["estado"] == "emitida"

    (trabalho,) = _fila(db)
    assert trabalho["impressora"] == imp.CAIXA
    assert trabalho["tipo"] == imp.TALAO
    assert trabalho["loja_id"] == "loja-1"
    assert trabalho["estado"] == imp.PENDENTE
    assert imp.COZINHA not in [t["impressora"] for t in _fila(db)]


def test_o_papel_do_cliente_e_o_talao_CERTIFICADO_que_o_vendus_devolveu(monkeypatch):
    """Byte a byte o que veio da emissão, e não uma reconstrução nossa: é o
    documento fiscal em papel, com o ATCUD e o QR que a app de fidelização
    lê."""
    db = _db_de_venda()
    _finalizar(db, monkeypatch)
    documento = db._coleccoes[COLECOES["documentos"]]._documentos[0]
    talao = [t for t in _fila(db) if t["impressora"] == imp.CAIXA][0]
    assert base64.b64decode(talao["bytes_b64"]) == documento["talao_escpos"]


def test_a_FATURA_CONTINUA_BOA_quando_a_fila_de_impressao_rebenta(monkeypatch):
    """**A promessa que sustenta o desenho todo.**

    Uma emissão bem sucedida — com Fatura Simplificada REAL já entregue à
    Autoridade Tributária — a devolver erro por causa do papel era o pior
    desfecho possível: o ecrã lê um erro com a venda aparentemente por emitir
    como «não saiu nada, pode repetir», e a operadora emite a segunda fatura
    do mesmo cliente.

    Aqui a fila rebenta em cheio (a colecção levanta em cada escrita) e a
    resposta da rota tem de sair igual: venda emitida, documento gravado."""
    db = _db_de_venda()

    class Explode:
        async def insert_one(self, doc):
            raise RuntimeError("Atlas em baixo")

    db._coleccoes[COLECOES["trabalhos_impressao"]] = Explode()
    resultado = _finalizar(db, monkeypatch)
    assert resultado["estado"] == "emitida"
    assert resultado["documento"]["atcud"] == "ATCUD-1"


def test_um_RETRY_da_mesma_emissao_nao_faz_um_segundo_talao(monkeypatch):
    """A rota é idempotente por desenho: a segunda tentativa encontra o
    documento já gravado e devolve-o tal e qual. Sem a chave da fila, essa
    segunda passagem enfileirava um segundo talão do mesmo cliente — e a
    operadora ficava com dois papéis iguais sem saber qual era qual."""
    db = _db_de_venda()
    _finalizar(db, monkeypatch)
    # A venda volta a `aberta` sem se lhe tirar a reserva nem o documento: é o
    # retrato de um retry que chega depois de a fatura já ter saído.
    db._coleccoes[COLECOES["vendas"]]._documentos[0]["estado"] = "aberta"
    _finalizar(db, monkeypatch)
    assert len(_fila(db)) == 1


# --- O fecho ------------------------------------------------------------------


def _db_de_fecho(vendas=None):
    return DbFalsa({
        COLECOES["caixas"]: ColeccaoFalsa([], [
            {"id": "caixa-1", "loja_id": "loja-1", "nome": "Balcão"}]),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa([], [{
            "id": "sessao-1", "caixa_id": "caixa-1", "loja_id": "loja-1",
            "aberta_por": {"id": "op-1", "nome": "Rafaela"},
            "aberta_em": "2026-08-22T09:00:00+00:00", "fundo": 50.0,
            "estado": "aberta", "movimentos_confirmados": [],
        }]),
        COLECOES["movimentos_caixa"]: ColeccaoFalsa([], []),
        COLECOES["vendas"]: ColeccaoFalsa([], vendas or []),
        COLECOES["notas_credito"]: ColeccaoFalsa([], []),
        COLECOES["refs_fiscais"]: ColeccaoFalsa([], []),
        COLECOES["dispositivos"]: ColeccaoFalsa([], []),
        COLECOES["trabalhos_impressao"]: ColeccaoFalsa([], [], unico=_chave_do_trabalho),
    })


def _fechar(db, monkeypatch, contado=50.0):
    from faturacao import caixa as caixa_mod

    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)
    return _corre(caixa_mod.fechar_caixa(
        caixa_mod.PedidoFecharCaixa(caixa_id="caixa-1", contado=contado),
        operador={"operador_id": "op-1", "nome": "Ana", "loja_id": "loja-1",
                  "dispositivo_id": "pc-1"},
    ))


def test_FECHAR_a_caixa_poe_o_Z_na_fila_da_impressora_do_balcao(monkeypatch):
    db = _db_de_fecho()
    z = _fechar(db, monkeypatch)
    assert z["estado"] == "fechada"
    (trabalho,) = _fila(db)
    assert trabalho["tipo"] == imp.Z
    assert trabalho["impressora"] == imp.CAIXA
    assert trabalho["loja_id"] == "loja-1"


def test_o_papel_do_Z_traz_os_NUMEROS_do_Z_que_ficou_gravado(monkeypatch):
    """O Z é o papel que a funcionária assina. Um papel que não corresponda ao
    que ficou gravado na sessão é a pior espécie de papel que esta loja pode
    produzir."""
    db = _db_de_fecho()
    z = _fechar(db, monkeypatch, contado=42.5)
    (trabalho,) = _fila(db)
    saiu = base64.b64decode(trabalho["bytes_b64"]).decode("cp858")
    assert "42,50" in saiu
    assert ("%.2f" % z["diferenca"]).replace(".", ",") in saiu


def test_o_FECHO_continua_feito_quando_a_fila_de_impressao_rebenta(monkeypatch):
    """Regra 3 do dono: o fecho nunca bloqueia. Um 500 aqui mandava a
    funcionária fechar outra vez uma caixa já fechada."""
    db = _db_de_fecho()

    class Explode:
        async def insert_one(self, doc):
            raise RuntimeError("Atlas em baixo")

    db._coleccoes[COLECOES["trabalhos_impressao"]] = Explode()
    z = _fechar(db, monkeypatch)
    assert z["estado"] == "fechada"
    assert z["esperado"] == 50.0
