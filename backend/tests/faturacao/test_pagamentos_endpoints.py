"""Comportamento dos endpoints editar/apagar de tipos de pagamento (sem base de dados).

Cobre a guarda de 'protegido' (spec §12): o tipo de pagamento usado pela app
L'Açaí não pode ser alterado nem apagado por este ecrã — senão a app passava a
cobrar no Stripe sem emitir factura, em silêncio. Mesmo padrão de duplo de
base de dados que test_lojas.py e test_indices.py.
"""
import asyncio

import pytest
from fastapi import HTTPException

from faturacao import pagamentos as pagamentos_mod
from faturacao.pagamentos import TipoPagamentoEntrada, apagar, editar


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class ResultadoDelete:
    """Duplo do resultado de delete_one do Motor — só o campo que o código usa."""

    def __init__(self, deleted_count):
        self.deleted_count = deleted_count


class ColeccaoFalsa:
    """Duplo de uma colecção Mongo: regista as chamadas e devolve resultados à escolha do teste."""

    def __init__(self, registo, find_one_devolve=None, delete_one_devolve=0):
        self.registo = registo
        self._find_one_devolve = find_one_devolve
        self._delete_one_devolve = delete_one_devolve

    async def find_one(self, filtro, projecao=None):
        self.registo.append(("find_one", filtro))
        return self._find_one_devolve

    async def update_one(self, filtro, atualizacao):
        self.registo.append(("update_one", filtro, atualizacao))
        return None

    async def delete_one(self, filtro):
        self.registo.append(("delete_one", filtro))
        return ResultadoDelete(self._delete_one_devolve)


class DbFalsa:
    def __init__(self, coleccao):
        self._coleccao = coleccao

    def __getitem__(self, nome):
        return self._coleccao


_DADOS = TipoPagamentoEntrada(nome="Glovo", tipo_fiscal="TB", da_troco=False)


def test_editar_tipo_protegido_e_recusado_409(monkeypatch):
    """A guarda central da tarefa: o tipo usado pela app L'Açaí não pode ser alterado."""
    registo = []
    coleccao = ColeccaoFalsa(registo, find_one_devolve={"id": "x", "protegido": True})
    monkeypatch.setattr(pagamentos_mod, "obter_db", lambda: DbFalsa(coleccao))

    with pytest.raises(HTTPException) as excinfo:
        _corre(editar("x", _DADOS, _={}))
    assert excinfo.value.status_code == 409
    assert not any(chamada[0] == "update_one" for chamada in registo)


def test_editar_tipo_inexistente_devolve_404(monkeypatch):
    registo = []
    coleccao = ColeccaoFalsa(registo, find_one_devolve=None)
    monkeypatch.setattr(pagamentos_mod, "obter_db", lambda: DbFalsa(coleccao))

    with pytest.raises(HTTPException) as excinfo:
        _corre(editar("nao-existe", _DADOS, _={}))
    assert excinfo.value.status_code == 404


def test_editar_tipo_normal_e_editado(monkeypatch):
    """Regressão: um tipo não protegido continua a poder ser editado."""
    registo = []
    coleccao = ColeccaoFalsa(registo, find_one_devolve={"id": "x", "protegido": False})
    monkeypatch.setattr(pagamentos_mod, "obter_db", lambda: DbFalsa(coleccao))

    _corre(editar("x", _DADOS, _={}))
    assert any(chamada[0] == "update_one" for chamada in registo)


def test_apagar_tipo_protegido_e_recusado_409(monkeypatch):
    """A mesma guarda ao apagar: sem isto, a app L'Açaí passava a cobrar sem
    emitir factura, em silêncio."""
    registo = []
    coleccao = ColeccaoFalsa(registo, find_one_devolve={"id": "x", "protegido": True})
    monkeypatch.setattr(pagamentos_mod, "obter_db", lambda: DbFalsa(coleccao))

    with pytest.raises(HTTPException) as excinfo:
        _corre(apagar("x", _={}))
    assert excinfo.value.status_code == 409
    assert not any(chamada[0] == "delete_one" for chamada in registo)


def test_apagar_tipo_inexistente_devolve_404(monkeypatch):
    """Um tipo que não existe não pode ser apagado."""
    registo = []
    coleccao = ColeccaoFalsa(registo, find_one_devolve=None, delete_one_devolve=0)
    monkeypatch.setattr(pagamentos_mod, "obter_db", lambda: DbFalsa(coleccao))

    with pytest.raises(HTTPException) as excinfo:
        _corre(apagar("nao-existe", _={}))
    assert excinfo.value.status_code == 404
    assert "Tipo de pagamento não encontrado" in excinfo.value.detail


def test_apagar_tipo_normal_e_apagado(monkeypatch):
    """Regressão: o caminho feliz continua a devolver sucesso."""
    registo = []
    coleccao = ColeccaoFalsa(
        registo, find_one_devolve={"id": "x", "protegido": False}, delete_one_devolve=1
    )
    monkeypatch.setattr(pagamentos_mod, "obter_db", lambda: DbFalsa(coleccao))

    resultado = _corre(apagar("x", _={}))
    assert resultado == {"apagado": True}
