"""Comportamento dos endpoints de motivos de nota de crédito (sem base de dados).

Mesmo padrão de duplo de base de dados que test_pagamentos_endpoints.py: o duplo
imita o Motor (update_one devolve matched_count, delete_one devolve deleted_count).
"""
import asyncio

import pytest
from fastapi import HTTPException

from faturacao import motivos as motivos_mod
from faturacao.motivos import MotivoEntrada, apagar, editar, listar, predefinir


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class CursorFalso:
    """Duplo de um cursor Mongo: imita find().sort().to_list() do Motor."""

    def __init__(self, dados):
        self._dados = dados
        self._ordem = None  # Tuplo (campo, direcção)

    def sort(self, campo, direcção=1):
        """Sort por campo (1=asc, -1=desc). Devolve o próprio cursor como o Motor."""
        self._ordem = (campo, direcção)
        return self

    async def to_list(self, limite):
        """Devolve os dados, ordenados se sort() foi chamado."""
        dados = list(self._dados)
        if self._ordem:
            campo, direcção = self._ordem
            reverse = (direcção == -1)
            dados.sort(key=lambda d: d.get(campo, ""), reverse=reverse)
        return dados


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
        find_devolve=None,
    ):
        self.registo = registo
        self._update_one_matched = update_one_matched
        self._delete_one_devolve = delete_one_devolve
        self._find_one_devolve = find_one_devolve
        self._find_devolve = find_devolve or []

    def find(self, filtro, projecao=None):
        """Devolve um cursor falso que suporta sort().to_list()."""
        self.registo.append(("find", filtro))
        return CursorFalso(self._find_devolve)

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
    coleccao = ColeccaoFalsa(
        registo,
        update_one_matched=1,
        find_one_devolve={"id": "x", "texto": "Erro na fatura", "predefinido": False},
    )
    monkeypatch.setattr(motivos_mod, "obter_db", lambda: DbFalsa(coleccao))

    resultado = _corre(predefinir("x", _={}))
    assert resultado == {"predefinido": "x"}
    assert registo[0] == ("find_one", {"id": "x"})
    assert registo[1] == ("update_many", {}, {"$set": {"predefinido": False}})
    assert registo[2] == ("update_one", {"id": "x"}, {"$set": {"predefinido": True}})


def test_predefinir_motivo_inexistente_devolve_404_sem_escrever_nada(monkeypatch):
    """Com um motivo_id inexistente, o endpoint devolve 404 e não escreve nada.

    A ordem das operações importa: verificar a existência ANTES de desmarcar todos
    evita deixar o sistema num estado pior do que estava (sem nenhum predefinido).
    Usa o registo de chamadas para garantir que update_many e update_one nunca foram
    invocados — mesmo que o BD estivesse no ar, não haveria efeitos secundários.
    """
    registo = []
    coleccao = ColeccaoFalsa(registo, update_one_matched=0)
    monkeypatch.setattr(motivos_mod, "obter_db", lambda: DbFalsa(coleccao))

    with pytest.raises(HTTPException) as excinfo:
        _corre(predefinir("nao-existe", _={}))
    assert excinfo.value.status_code == 404
    assert not any(chamada[0] == "update_many" for chamada in registo), \
        "update_many não deve ser chamado com id inexistente"
    assert not any(chamada[0] == "update_one" for chamada in registo), \
        "update_one não deve ser chamado com id inexistente"


def test_predefinir_janela_estreita_motivo_apagado_entre_find_e_update(monkeypatch):
    """A janela: find_one encontra o motivo, mas o update_one final falha.

    Cenário: o motivo é apagado por outro pedido entre o find_one e o update_one final.
    O endpoint deve detetar isso e devolver 404, não 200 "sucesso" falso.

    Defesa de duas camadas: o find_one evita desmarcar tudo sem motivo,
    o matched_count do update_one apanha a corrida.
    """
    registo = []
    coleccao = ColeccaoFalsa(
        registo,
        update_one_matched=0,  # O update_one final não encontra nada
        find_one_devolve={"id": "x", "texto": "Erro na fatura", "predefinido": False},
    )
    monkeypatch.setattr(motivos_mod, "obter_db", lambda: DbFalsa(coleccao))

    with pytest.raises(HTTPException) as excinfo:
        _corre(predefinir("x", _={}))
    assert excinfo.value.status_code == 404
    assert "Motivo não encontrado" in excinfo.value.detail
    # Confirma a sequência: find_one passou, mas update_one falhou
    assert any(chamada[0] == "find_one" for chamada in registo)
    assert any(chamada[0] == "update_one" for chamada in registo)


def test_listar_motivos_ordenados_por_texto(monkeypatch):
    """O endpoint listar() devolve motivos ordenados por texto (ascendente).

    Coerência com lojas.py e pagamentos.py, que ordenam igualmente.
    Importante num dropdown: o utilizador espera uma ordem previsível.
    """
    registo = []
    dados = [
        {"id": "z", "texto": "Zebra", "predefinido": False},
        {"id": "a", "texto": "Apple", "predefinido": False},
        {"id": "m", "texto": "Middle", "predefinido": True},
    ]
    coleccao = ColeccaoFalsa(registo, find_devolve=dados)
    monkeypatch.setattr(motivos_mod, "obter_db", lambda: DbFalsa(coleccao))

    resultado = _corre(listar(_={}))
    assert len(resultado) == 3
    assert resultado[0]["texto"] == "Apple"
    assert resultado[1]["texto"] == "Middle"
    assert resultado[2]["texto"] == "Zebra"
