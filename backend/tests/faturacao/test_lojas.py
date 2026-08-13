"""Validação dos modelos de Loja e Caixa (sem base de dados)."""
import pytest
from pydantic import ValidationError

from faturacao.lojas import CaixaEntrada, LojaEntrada


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
