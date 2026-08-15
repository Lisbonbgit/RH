"""Sessão de caixa do POS: abrir e registar movimentos (Task 3 do Plano 2A).

Mesmo padrão de duplo de base de dados que test_pos_auth.py: find()/find_one()
filtram de facto pelos campos do filtro, para que "caixa já aberta" e "sem
sessão aberta" provem comportamento real, e não apenas confiem que o Mongo
filtraria por nós. Nenhum teste liga a uma base de dados nem à rede.
"""
import asyncio

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from faturacao import caixa as caixa_mod
from faturacao.caixa import (
    PedidoAbrirCaixa,
    PedidoMovimento,
    abrir_caixa,
    registar_movimento,
)
from faturacao.db import COLECOES


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- Duplo de base de dados ----------------------------------------------------


def _corresponde(item, filtro):
    """Réplica minimalista do casamento de filtro do Mongo: igualdade exacta
    em cada campo pedido."""
    if not filtro:
        return True
    return all(item.get(chave) == valor for chave, valor in filtro.items())


class CursorFalso:
    def __init__(self, itens):
        self._itens = itens

    def sort(self, *args, **kwargs):
        return self

    async def to_list(self, n=None):
        return self._itens


class ColeccaoFalsa:
    """Duplo de uma colecção Mongo: find()/find_one() filtram de facto."""

    def __init__(self, registo, documentos=None):
        self.registo = registo
        self._documentos = documentos if documentos is not None else []

    def find(self, filtro=None):
        self.registo.append(("find", filtro))
        return CursorFalso([d for d in self._documentos if _corresponde(d, filtro)])

    async def find_one(self, filtro, projecao=None):
        self.registo.append(("find_one", filtro))
        encontrados = [d for d in self._documentos if _corresponde(d, filtro)]
        return encontrados[0] if encontrados else None

    async def insert_one(self, doc):
        self.registo.append(("insert_one", dict(doc)))
        self._documentos.append(doc)
        return None

    async def update_one(self, filtro, atualizacao):
        self.registo.append(("update_one", filtro, atualizacao))
        alvos = [d for d in self._documentos if _corresponde(d, filtro)]
        if alvos:
            alvos[0].update(atualizacao.get("$set", {}))
        return None


class DbFalsa:
    """Duplo de db com várias colecções — caixas, sessões e movimentos têm
    estados independentes na mesma chamada a obter_db()."""

    def __init__(self, coleccoes):
        self._coleccoes = coleccoes

    def __getitem__(self, nome):
        return self._coleccoes.setdefault(nome, ColeccaoFalsa([]))


def _db(registo, caixas=None, sessoes=None, movimentos=None):
    return DbFalsa({
        COLECOES["caixas"]: ColeccaoFalsa(registo, caixas),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa(registo, sessoes),
        COLECOES["movimentos_caixa"]: ColeccaoFalsa(registo, movimentos),
    })


def _operador(**over):
    o = {"operador_id": "op-1", "nome": "Rafaela", "perfil": "operador_caixa", "loja_id": "loja-1"}
    o.update(over)
    return o


def _caixa(**over):
    c = {"id": "caixa-1", "loja_id": "loja-1", "nome": "Balcão"}
    c.update(over)
    return c


def _sessao(**over):
    s = {
        "id": "sessao-1", "caixa_id": "caixa-1", "loja_id": "loja-1",
        "aberta_por": {"id": "op-1", "nome": "Rafaela"}, "aberta_em": "2026-08-15T09:00:00+00:00",
        "fundo": 50.0, "estado": "aberta", "fechada_por": None, "fechada_em": None,
        "contado": None, "esperado": None, "diferenca": None,
    }
    s.update(over)
    return s


# --- Abrir caixa -----------------------------------------------------------------


def test_abrir_caixa_com_sucesso(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(
        abrir_caixa(PedidoAbrirCaixa(caixa_id="caixa-1", fundo=50.0), operador=_operador())
    )
    assert resultado["estado"] == "aberta"
    assert resultado["fundo"] == 50.0
    assert resultado["caixa_id"] == "caixa-1"
    assert resultado["loja_id"] == "loja-1"
    assert resultado["aberta_por"] == {"id": "op-1", "nome": "Rafaela"}


def test_abrir_caixa_ja_aberta_e_recusado_409(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(abrir_caixa(PedidoAbrirCaixa(caixa_id="caixa-1", fundo=50.0), operador=_operador()))
    assert excinfo.value.status_code == 409
    # Não deve ter tentado gravar uma segunda sessão.
    assert not any(chamada[0] == "insert_one" for chamada in registo)


def test_abrir_caixa_inexistente_e_recusado_404(monkeypatch):
    registo = []
    db = _db(registo, caixas=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(abrir_caixa(PedidoAbrirCaixa(caixa_id="nao-existe", fundo=50.0), operador=_operador()))
    assert excinfo.value.status_code == 404


def test_abrir_caixa_de_outra_loja_e_recusado_404(monkeypatch):
    """Uma caixa de outra loja não pode ser aberta por um operador desta loja
    — mesmo que o id exista, o âmbito é sempre o da loja do operador."""
    registo = []
    db = _db(registo, caixas=[_caixa(loja_id="loja-2")])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(abrir_caixa(PedidoAbrirCaixa(caixa_id="caixa-1", fundo=50.0), operador=_operador()))
    assert excinfo.value.status_code == 404


def test_abrir_caixa_com_fundo_negativo_e_recusado():
    with pytest.raises(ValidationError):
        PedidoAbrirCaixa(caixa_id="caixa-1", fundo=-10.0)


def test_abrir_caixa_com_fundo_com_3_casas_e_recusado():
    with pytest.raises(ValidationError):
        PedidoAbrirCaixa(caixa_id="caixa-1", fundo=50.995)


def test_abrir_caixa_com_fundo_zero_e_aceite(monkeypatch):
    """Zero é um fundo legítimo (loja que ainda não recebeu o troco do dia) —
    o que não pode é ser negativo."""
    registo = []
    db = _db(registo, caixas=[_caixa()])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(
        abrir_caixa(PedidoAbrirCaixa(caixa_id="caixa-1", fundo=0.0), operador=_operador())
    )
    assert resultado["fundo"] == 0.0


# --- Movimentos --------------------------------------------------------------------


def test_movimento_de_entrada_com_sucesso(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(registar_movimento(
        PedidoMovimento(caixa_id="caixa-1", tipo="entrada", valor=20.0), operador=_operador()
    ))
    assert resultado["sessao_id"] == "sessao-1"
    assert resultado["tipo"] == "entrada"
    assert resultado["valor"] == 20.0
    assert resultado["por"] == {"id": "op-1", "nome": "Rafaela"}


def test_movimento_de_saida_sem_motivo_e_recusado():
    with pytest.raises(ValidationError):
        PedidoMovimento(caixa_id="caixa-1", tipo="saida", valor=10.0)


def test_movimento_de_saida_com_motivo_vazio_e_recusado():
    with pytest.raises(ValidationError):
        PedidoMovimento(caixa_id="caixa-1", tipo="saida", valor=10.0, motivo="   ")


def test_movimento_de_saida_com_motivo_passa(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(registar_movimento(
        PedidoMovimento(caixa_id="caixa-1", tipo="saida", valor=10.0, motivo="Troco ao banco"),
        operador=_operador(),
    ))
    assert resultado["motivo"] == "Troco ao banco"


def test_movimento_de_entrada_nao_exige_motivo(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resultado = _corre(registar_movimento(
        PedidoMovimento(caixa_id="caixa-1", tipo="entrada", valor=20.0), operador=_operador()
    ))
    assert resultado["motivo"] is None


def test_movimento_com_valor_negativo_e_recusado_422():
    with pytest.raises(ValidationError):
        PedidoMovimento(caixa_id="caixa-1", tipo="entrada", valor=-5.0)


def test_movimento_com_valor_zero_e_recusado_422():
    with pytest.raises(ValidationError):
        PedidoMovimento(caixa_id="caixa-1", tipo="entrada", valor=0)


def test_movimento_com_valor_de_3_casas_e_recusado():
    with pytest.raises(ValidationError):
        PedidoMovimento(caixa_id="caixa-1", tipo="entrada", valor=20.995)


def test_movimento_sem_sessao_aberta_e_recusado_409(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(registar_movimento(
            PedidoMovimento(caixa_id="caixa-1", tipo="entrada", valor=20.0), operador=_operador()
        ))
    assert excinfo.value.status_code == 409
    assert not any(chamada[0] == "insert_one" for chamada in registo)


def test_movimento_em_caixa_de_outra_loja_e_recusado_404(monkeypatch):
    registo = []
    db = _db(registo, caixas=[_caixa(loja_id="loja-2")], sessoes=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(registar_movimento(
            PedidoMovimento(caixa_id="caixa-1", tipo="entrada", valor=20.0), operador=_operador()
        ))
    assert excinfo.value.status_code == 404


def test_movimento_ignora_sessao_id_vindo_do_corpo_mesmo_que_apareca(monkeypatch):
    """A regra central da tarefa: a sessão é resolvida no servidor a partir
    da caixa + operador, nunca de um sessao_id que venha no pedido — senão
    qualquer um lançava movimentos na sessão de outra loja. Simula um corpo
    desactualizado/malicioso que ainda traz sessao_id e confirma que é
    ignorado por completo: o modelo nem sequer declara esse campo, por isso
    o movimento tem sempre de ficar preso à sessão aberta da PRÓPRIA caixa
    pedida, nunca à sessão "sugerida" no pedido.

    Mutação verificada manualmente (ver relatório da tarefa): se
    PedidoMovimento ganhasse um campo `sessao_id` e o endpoint passasse a
    confiar nele em vez de resolver sempre pela caixa, este teste fica
    vermelho."""
    registo = []
    sessao_amiga = _sessao(id="sessao-amiga", caixa_id="caixa-1", loja_id="loja-1")
    sessao_estranha = _sessao(id="sessao-estranha", caixa_id="caixa-2", loja_id="loja-2")
    db = _db(
        registo,
        caixas=[_caixa(id="caixa-1", loja_id="loja-1"), _caixa(id="caixa-2", loja_id="loja-2")],
        sessoes=[sessao_amiga, sessao_estranha],
    )
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    dados = PedidoMovimento.model_validate({
        "caixa_id": "caixa-1", "tipo": "entrada", "valor": 10.0,
        "sessao_id": "sessao-estranha",
    })
    resultado = _corre(registar_movimento(dados, operador=_operador()))
    assert resultado["sessao_id"] == "sessao-amiga"
