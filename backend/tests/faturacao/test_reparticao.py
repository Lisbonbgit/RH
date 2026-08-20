import pytest
from faturacao.reparticao import quantidade_para, repartir_centimos


def test_as_partes_somam_sempre_o_total():
    """A regra que não se negoceia. Sem ela, as faturas de uma conta
    dividida declaram à AT um valor diferente do que entrou na gaveta."""
    for total in range(1, 400):
        for n in range(1, 8):
            partes = repartir_centimos(total, n)
            assert sum(partes) == total, (total, n, partes)
            assert len(partes) == n


def test_o_centimo_que_sobra_vai_para_as_primeiras():
    # 899 cêntimos por três: 300, 300, 299 — nunca mais de um cêntimo de
    # diferença entre duas pessoas.
    assert repartir_centimos(899, 3) == [300, 300, 299]
    assert repartir_centimos(1000, 3) == [334, 333, 333]
    assert repartir_centimos(10, 4) == [3, 3, 2, 2]


def test_divisao_exacta_nao_inventa_diferencas():
    assert repartir_centimos(900, 3) == [300, 300, 300]


def test_uma_parte_leva_tudo():
    assert repartir_centimos(899, 1) == [899]


def test_zero_partes_e_recusado():
    with pytest.raises(ValueError):
        repartir_centimos(899, 0)


def test_a_quantidade_reproduz_o_valor_ao_centimo():
    """O que interessa não é a fracção bonita — é que `qty × preço`,
    arredondado como o Vendus arredonda, dê EXACTAMENTE o valor da parte."""
    for centimos in (300, 299, 1, 899):
        q = quantidade_para(centimos, 8.99)
        assert round(q * 8.99, 2) == centimos / 100


def test_a_quantidade_de_um_preco_zero_e_recusada():
    """Um preço zero não produz valor nenhum: não há quantidade que o
    resolva, e devolver 0 escondia o problema numa fatura."""
    with pytest.raises(ValueError):
        quantidade_para(300, 0)
