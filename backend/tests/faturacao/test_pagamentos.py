"""Tipos de pagamento: nome livre + código fiscal do Vendus + dá troco."""
import pytest
from pydantic import ValidationError

from faturacao.pagamentos import TIPOS_FISCAIS, TipoPagamentoEntrada


def test_codigos_fiscais_do_vendus():
    """Os códigos são os documentados em registers/movements.doc."""
    assert TIPOS_FISCAIS["NU"] == "Numerário"
    assert TIPOS_FISCAIS["CD"] == "Cartão de Débito"
    assert TIPOS_FISCAIS["CC"] == "Cartão de Crédito"
    assert TIPOS_FISCAIS["TB"] == "Transferência Bancária"
    assert TIPOS_FISCAIS["MBWAY"] == "MB Way"


def test_tipo_valido():
    t = TipoPagamentoEntrada(nome="Glovo", tipo_fiscal="TB", da_troco=False)
    assert t.tipo_fiscal == "TB"


def test_tipo_fiscal_desconhecido_e_recusado():
    with pytest.raises(ValidationError):
        TipoPagamentoEntrada(nome="Inventado", tipo_fiscal="XX")


def test_dinheiro_da_troco_por_omissao_e_falso():
    """Quem cria decide. Não se adivinha — 'Glovo' com troco seria um erro caro."""
    assert TipoPagamentoEntrada(nome="X", tipo_fiscal="NU").da_troco is False


def test_nome_obrigatorio():
    with pytest.raises(ValidationError):
        TipoPagamentoEntrada(nome="", tipo_fiscal="NU")
