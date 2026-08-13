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


# --- Achado 1: hash bcrypt truncado não pode rebentar bcrypt.checkpw --------
#
# bcrypt 4.1.3 (motor em Rust) levanta pyo3_runtime.PanicException — que
# herda de BaseException, não de Exception — quando recebe um hash com o
# prefixo válido mas truncado. A correcção valida o FORMATO do hash antes
# de chamar o bcrypt, para nunca lhe entregar lixo.

_HASH_BCRYPT_VALIDO = "$2b$12$kuClUVV4uYb54wzqtY9oGexTxMMFOLROpvlJoAS6WAfOScecBBFcG"


def test_hash_truncado_reproduz_o_caso_do_crash():
    """Caso exacto apontado na revisão: prefixo válido, hash truncado."""
    assert pin_valido("1234", "$2b$12$curto") is False


def test_hash_truncado_varios_comprimentos_nao_rebenta():
    prefixo_len = len("$2b$12$")
    comprimentos = [
        0,
        1,
        prefixo_len,
        prefixo_len + 1,
        prefixo_len + 10,
        len(_HASH_BCRYPT_VALIDO) - 10,
        len(_HASH_BCRYPT_VALIDO) - 1,
    ]
    for comprimento in comprimentos:
        truncado = _HASH_BCRYPT_VALIDO[:comprimento]
        assert pin_valido("1234", truncado) is False, "falhou para comprimento %d" % comprimento


def test_hash_vazio_nao_rebenta():
    assert pin_valido("1234", "") is False


def test_hash_none_nao_rebenta():
    assert pin_valido("1234", None) is False


def test_hash_lixo_completo_nao_rebenta():
    assert pin_valido("1234", "lixo completamente aleatorio, nada a ver com bcrypt !!!") is False


def test_hash_com_prefixo_invalido_nao_rebenta():
    assert pin_valido("1234", "$1$naoebcrypt$restoqualquer") is False


# --- Achado 4: pin_valido tem de normalizar como o hash_pin -----------------


def test_verificacao_aceita_espacos_a_volta_como_hash_pin():
    h = hash_pin("1234")
    assert pin_valido(" 1234 ", h) is True


def test_verificacao_pin_invalido_nunca_rebenta():
    """pin_valido nunca pode levantar — devolve False para entrada inválida,
    ao contrário de normalizar_pin, que levanta ValueError."""
    h = hash_pin("1234")
    assert pin_valido("12a4", h) is False
    assert pin_valido("abcd", h) is False
    assert pin_valido("123", h) is False
    assert pin_valido("", h) is False
    assert pin_valido(None, h) is False


# --- Achado 5: normalizar_pin só trata None como vazio -----------------------


def test_normalizar_pin_trata_so_none_como_vazio():
    """Um valor falsy que NÃO seja None (ex.: um objecto cujo __bool__ dá
    False mas cujo __str__ dá um PIN válido) não pode ser esmagado para "".
    Só None deve ser tratado como PIN vazio."""

    class ValorFalsyComStrValido:
        def __bool__(self):
            return False

        def __str__(self):
            return "1234"

    assert normalizar_pin(ValorFalsyComStrValido()) == "1234"


def test_normalizar_pin_none_continua_invalido():
    with pytest.raises(ValueError):
        normalizar_pin(None)
