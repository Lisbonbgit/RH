"""Validação dos modelos de Loja e Caixa e dos endpoints de apagar (sem base de dados).

Os endpoints são chamados directamente (sem HTTP nem Mongo), com um duplo de base de
dados que regista as chamadas e devolve resultados à escolha do teste — o mesmo padrão
de test_indices.py.
"""
import asyncio

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from faturacao import lojas as lojas_mod
from faturacao.lojas import CaixaEntrada, LojaEntrada, apagar_caixa, apagar_loja


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class ResultadoDelete:
    """Duplo do resultado de delete_one do Motor — só o campo que o código usa."""

    def __init__(self, deleted_count):
        self.deleted_count = deleted_count


class ColeccaoFalsa:
    """Duplo de uma colecção Mongo: regista as chamadas e devolve resultados à escolha do teste."""

    def __init__(self, registo, count_documents_devolve=0, delete_one_devolve=0):
        self.registo = registo
        self._count_documents_devolve = count_documents_devolve
        self._delete_one_devolve = delete_one_devolve

    async def count_documents(self, filtro):
        self.registo.append(("count_documents", filtro))
        return self._count_documents_devolve

    async def delete_one(self, filtro):
        self.registo.append(("delete_one", filtro))
        return ResultadoDelete(self._delete_one_devolve)


class DbFalsa:
    def __init__(self, colecoes):
        self._colecoes = colecoes

    def __getitem__(self, nome):
        return self._colecoes[nome]


def test_loja_minima():
    lj = LojaEntrada(nome="L'Açaí Belém")
    assert lj.nome == "L'Açaí Belém"
    assert lj.cae is None


def test_loja_sem_nome_e_recusada():
    with pytest.raises(ValidationError):
        LojaEntrada(nome="")


def test_loja_completa():
    lj = LojaEntrada(
        nome="L'Açaí Algueirão",
        morada="Rua Ribeiro dos Reis 15B",
        codigo_postal="2725-175",
        localidade="Algueirão",
        email="geral@olacai.com",
        telefone="216086715",
        cae="56103",
    )
    assert lj.codigo_postal == "2725-175"


def test_codigo_postal_invalido_e_recusado():
    with pytest.raises(ValidationError):
        LojaEntrada(nome="X", codigo_postal="2725")


def test_caixa_exige_nome():
    with pytest.raises(ValidationError):
        CaixaEntrada(nome="")


def test_caixa_nao_tem_campo_de_register_vendus():
    """O register_id do Vendus é configuração do sistema, nunca da interface."""
    assert "register_id" not in CaixaEntrada.model_fields
    assert "vendus_register_id" not in CaixaEntrada.model_fields


def test_codigo_postal_vazio_e_tratado_como_none():
    """"" é falsy e passava despercebido pelo validador — tem de virar None,
    para não ficar um código postal vazio guardado a fingir que foi preenchido."""
    lj = LojaEntrada(nome="X", codigo_postal="")
    assert lj.codigo_postal is None


def test_codigo_postal_com_newline_final_e_recusado():
    """$ casa antes de um '\\n' final em Python — \\Z fecha essa fresta."""
    with pytest.raises(ValidationError):
        LojaEntrada(nome="X", codigo_postal="2725-175\n")


def test_apagar_loja_inexistente_devolve_404(monkeypatch):
    registo = []
    db = DbFalsa(
        {
            "fat_caixas": ColeccaoFalsa(registo, count_documents_devolve=0),
            "fat_lojas": ColeccaoFalsa(registo, delete_one_devolve=0),
        }
    )
    monkeypatch.setattr(lojas_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(apagar_loja("id-que-nao-existe", _={}))
    assert excinfo.value.status_code == 404


def test_apagar_loja_com_caixas_continua_a_recusar_409(monkeypatch):
    """Regressão: a guarda existente (loja com caixas) tem de continuar a funcionar."""
    registo = []
    db = DbFalsa(
        {
            "fat_caixas": ColeccaoFalsa(registo, count_documents_devolve=2),
            "fat_lojas": ColeccaoFalsa(registo, delete_one_devolve=1),
        }
    )
    monkeypatch.setattr(lojas_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(apagar_loja("loja-com-caixas", _={}))
    assert excinfo.value.status_code == 409
    assert ("delete_one", {"id": "loja-com-caixas"}) not in registo


def test_apagar_loja_existente_sem_caixas_e_apagada(monkeypatch):
    """Regressão: o caminho feliz continua a devolver sucesso."""
    registo = []
    db = DbFalsa(
        {
            "fat_caixas": ColeccaoFalsa(registo, count_documents_devolve=0),
            "fat_lojas": ColeccaoFalsa(registo, delete_one_devolve=1),
        }
    )
    monkeypatch.setattr(lojas_mod, "obter_db", lambda: db)

    resultado = _corre(apagar_loja("loja-normal", _={}))
    assert resultado == {"apagada": True}


def test_apagar_caixa_inexistente_devolve_404(monkeypatch):
    registo = []
    db = DbFalsa({"fat_caixas": ColeccaoFalsa(registo, delete_one_devolve=0)})
    monkeypatch.setattr(lojas_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(apagar_caixa("id-que-nao-existe", _={}))
    assert excinfo.value.status_code == 404


def test_apagar_caixa_existente_e_apagada(monkeypatch):
    """Regressão: o caminho feliz continua a devolver sucesso."""
    registo = []
    db = DbFalsa({"fat_caixas": ColeccaoFalsa(registo, delete_one_devolve=1)})
    monkeypatch.setattr(lojas_mod, "obter_db", lambda: db)

    resultado = _corre(apagar_caixa("caixa-normal", _={}))
    assert resultado == {"apagada": True}
