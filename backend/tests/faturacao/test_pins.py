"""PIN de 4 dígitos do POS — lógica pura."""
import pytest

from faturacao.pins import hash_pin, normalizar_pin, pin_valido


def test_normaliza_espacos():
    assert normalizar_pin(" 1234 ") == "1234"


def test_recusa_pin_curto():
    with pytest.raises(ValueError):
        normalizar_pin("123")


def test_recusa_pin_longo():
    with pytest.raises(ValueError):
        normalizar_pin("12345")


def test_recusa_letras():
    with pytest.raises(ValueError):
        normalizar_pin("12a4")


def test_aceita_pin_com_zeros_a_esquerda():
    assert normalizar_pin("0007") == "0007"


def test_hash_nao_e_o_pin():
    assert hash_pin("1234") != "1234"


def test_hash_muda_de_cada_vez():
    """bcrypt tem sal — dois hashes do mesmo PIN são diferentes."""
    assert hash_pin("1234") != hash_pin("1234")


def test_verificacao():
    h = hash_pin("1234")
    assert pin_valido("1234", h) is True
    assert pin_valido("4321", h) is False


def test_verificacao_com_hash_lixo_nao_rebenta():
    assert pin_valido("1234", "isto-nao-e-um-hash") is False
