"""Comportamento dos endpoints de motivos de nota de crédito (sem base de dados).

Mesmo padrão de duplo de base de dados que test_pagamentos_endpoints.py: o duplo
imita o Motor (update_one devolve matched_count, delete_one devolve deleted_count).
"""
import asyncio

import pytest
from fastapi import HTTPException

from faturacao import motivos as motivos_mod
from faturacao.motivos import MotivoEntrada, apagar, editar, predefinir


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class ResultadoUpdate:
    """Duplo do resultado de update_one/update_many do Motor — só o campo usado."""

    def __init__(self, matched_count):
        self.matched_count = matched_count


class ResultadoDelete:
    """Duplo do resultado de delete_one do Motor — só o campo que o código usa."""

    def __init__(self, deleted_count):
        self.deleted_count = deleted_count


class ColeccaoFalsa:
    """Duplo de uma colecção Mongo: regista as chamadas e devolve resultados à escolha do teste."""

    def __init__(
        self,
        registo,
        update_one_matched=0,
        delete_one_devolve=0,
        find_one_devolve=None,
    ):
        self.registo = registo
        self._update_one_matched = update_one_matched
        self._delete_one_devolve = delete_one_devolve
        self._find_one_devolve = find_one_devolve

    async def find_one(self, filtro, projecao=None):
        self.registo.append(("find_one", filtro))
        return self._find_one_devolve

    async def update_one(self, filtro, atualizacao):
        self.registo.append(("update_one", filtro, atualizacao))
        return ResultadoUpdate(self._update_one_matched)

    async def update_many(self, filtro, atualizacao):
        self.registo.append(("update_many", filtro, atualizacao))
        return ResultadoUpdate(0)

    async def delete_one(self, filtro):
        self.registo.append(("delete_one", filtro))
        return ResultadoDelete(self._delete_one_devolve)


class DbFalsa:
    def __init__(self, coleccao):
        self._coleccao = coleccao

    def __getitem__(self, nome):
        return self._coleccao


_DADOS = MotivoEntrada(texto="Erro na fatura")


def test_editar_motivo_inexistente_devolve_404(monkeypatch):
    registo = []
    coleccao = ColeccaoFalsa(registo, update_one_matched=0)
    monkeypatch.setattr(motivos_mod, "obter_db", lambda: DbFalsa(coleccao))

    with pytest.raises(HTTPException) as excinfo:
        _corre(editar("nao-existe", _DADOS, _={}))
    assert excinfo.value.status_code == 404


def test_editar_motivo_existente_e_editado(monkeypatch):
    registo = []
    coleccao = ColeccaoFalsa(
        registo,
        update_one_matched=1,
        find_one_devolve={"id": "x", "texto": "Erro na fatura", "predefinido": False},
    )
    monkeypatch.setattr(motivos_mod, "obter_db", lambda: DbFalsa(coleccao))

    resultado = _corre(editar("x", _DADOS, _={}))
    assert resultado["texto"] == "Erro na fatura"
    assert any(chamada[0] == "update_one" for chamada in registo)


def test_apagar_motivo_inexistente_devolve_404(monkeypatch):
    """Coerência com o resto do módulo (regra C7): apagar um id inexistente dá 404."""
    registo = []
    coleccao = ColeccaoFalsa(registo, delete_one_devolve=0)
    monkeypatch.setattr(motivos_mod, "obter_db", lambda: DbFalsa(coleccao))

    with pytest.raises(HTTPException) as excinfo:
        _corre(apagar("nao-existe", _={}))
    assert excinfo.value.status_code == 404
    assert "Motivo não encontrado" in excinfo.value.detail


def test_apagar_motivo_existente_e_apagado(monkeypatch):
    registo = []
    coleccao = ColeccaoFalsa(registo, delete_one_devolve=1)
    monkeypatch.setattr(motivos_mod, "obter_db", lambda: DbFalsa(coleccao))

    resultado = _corre(apagar("x", _={}))
    assert resultado == {"apagado": True}


def test_predefinir_motivo_existente_desmarca_os_outros(monkeypatch):
    registo = []
    coleccao = ColeccaoFalsa(registo, update_one_matched=1)
    monkeypatch.setattr(motivos_mod, "obter_db", lambda: DbFalsa(coleccao))

    resultado = _corre(predefinir("x", _={}))
    assert resultado == {"predefinido": "x"}
    assert registo[0] == ("update_many", {}, {"$set": {"predefinido": False}})
    assert registo[1] == ("update_one", {"id": "x"}, {"$set": {"predefinido": True}})


def test_predefinir_motivo_inexistente_devolve_404_mas_ja_desmarcou_todos(monkeypatch):
    """Documenta um comportamento do código do brief que NÃO foi alterado sem decisão:

    o update_many (desmarcar todos) corre incondicionalmente, ANTES de se saber se o
    motivo_id existe. Se o id não existir, o 404 é lançado depois do efeito secundário
    já ter acontecido — a lista fica sem nenhum motivo predefinido por causa de um
    clique num registo que já não existe. Ver task-9-report.md: sinalizado ao humano,
    não corrigido por decisão de desenho, não por omissão.
    """
    registo = []
    coleccao = ColeccaoFalsa(registo, update_one_matched=0)
    monkeypatch.setattr(motivos_mod, "obter_db", lambda: DbFalsa(coleccao))

    with pytest.raises(HTTPException) as excinfo:
        _corre(predefinir("nao-existe", _={}))
    assert excinfo.value.status_code == 404
    assert any(chamada[0] == "update_many" for chamada in registo)
