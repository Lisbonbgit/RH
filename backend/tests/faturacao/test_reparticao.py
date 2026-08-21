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


def test_recusa_um_total_que_afinal_e_euros_nao_centimos():
    """`repartir_centimos` tem uma quase-homónima em `fiscal.py`
    (`_distribuir_centimos`) que recebe EUROS, não cêntimos — é fácil trocar
    as duas. Sem esta recusa, `repartir_centimos(8.99, 3)` truncava em
    silêncio (`int(8.99) == 8`) e devolvia `[3, 3, 2]`, que soma 8, não 8.99:
    a garantia da docstring ("as partes somam sempre o total") ficava falsa
    exactamente no caso em que mais importa — três Faturas Simplificadas de
    0,03 € em vez de 3,00 € cada."""
    with pytest.raises(ValueError):
        repartir_centimos(8.99, 3)


def test_recusa_um_total_em_euros_redondos_tambem():
    """A metade traiçoeira do mesmo engano: um total em EUROS que por
    acaso é redondo (9.0, não 8.99) passava a guarda antiga em silêncio —
    `total_centimos != int(total_centimos)` só apanha fracção de cêntimo, e
    9.0 == int(9.0). `repartir_centimos(9.0, 3)` dava `[3, 3, 3]` (soma 9,
    não 900): três Faturas Simplificadas de 0,03 € em vez de 3,00 € cada,
    exactamente o cenário que esta função existe para impedir."""
    with pytest.raises(ValueError):
        repartir_centimos(9.0, 3)


def test_a_quantidade_reproduz_o_valor_ao_centimo():
    """O que interessa não é a fracção bonita — é que `qty × preço`,
    arredondado como o Vendus arredonda, dê EXACTAMENTE o valor da parte."""
    for centimos in (300, 299, 1, 899):
        q = quantidade_para(centimos, 8.99)
        assert round(q * 8.99, 2) == centimos / 100


def test_a_quantidade_produto_de_preco_acima_dos_10_euros():
    """Estrutural: todos os outros casos deste ficheiro usam `preco=8.99`,
    e abaixo dos 10 € três casas decimais de quantidade ainda chegam para
    reproduzir o cêntimo — por isso nenhum apanharia `CASAS_DA_QUANTIDADE`
    cair de 5 para 3. A Taça Família (17,98 €, dois açaís de 8,99 €, um
    preço que já existe noutros testes deste módulo) fecha esse buraco: a
    3 casas, `quantidade_para(600, 17.98)` nem produz quantidade válida —
    rebenta com `ValueError` em vez de deixar dividir a conta por três."""
    q = quantidade_para(600, 17.98)
    assert round(q * 17.98, 2) == 6.00


def test_a_quantidade_de_um_preco_zero_e_recusada():
    """Um preço zero não produz valor nenhum: não há quantidade que o
    resolva, e devolver 0 escondia o problema numa fatura."""
    with pytest.raises(ValueError):
        quantidade_para(300, 0)


def test_a_quantidade_recusa_quando_nenhum_candidato_bate_certo():
    """A verificação de `quantidade_para` (o `if`, os dois vizinhos e o
    `raise` final) não tem nenhum caso real de açaí que a dispare — e
    prova-se numa linha, não por amostragem: `round(alvo/preco,
    CASAS_DA_QUANTIDADE)` desvia da divisão exacta, no máximo, meia unidade
    da última casa — `preco × 0,5 × 10⁻⁵`. Para qualquer preço abaixo de
    1000 €, isso é menos de `1000 × 5×10⁻⁶ = 0,005 €`: meio cêntimo, que é
    exactamente o que separa dois valores ao arredondar a 2 casas. Por isso
    `round(q × preco, 2)` acerta sempre o cêntimo certo para os preços de um
    item de açaí, e o `if` nunca cai para o ramo dos vizinhos nem para o
    `raise`. Sem um caso real, este teste teria de usar um preço fora desse
    intervalo para provar que a verificação continua lá: a 1000,37 €
    (deliberadamente acima dos 1000 € — só para forçar o desvio de
    arredondamento de 5 casas), nem a quantidade nem os dois vizinhos mais
    próximos reproduzem os 13,52 €, e a função tem de recusar
    em vez de devolver um valor que perde o cêntimo em silêncio. Se
    `quantidade_para` for um dia simplificada para
    `round(alvo / preco, CASAS_DA_QUANTIDADE)` sem esta verificação — a
    "leitura sugere que o `if` parece sempre verdadeiro" — é este teste que
    fica vermelho, não o `test_a_quantidade_reproduz_o_valor_ao_centimo`
    (esse só apanha uma perda de RESOLUÇÃO, 5 para 2 casas, não a remoção da
    verificação em si)."""
    with pytest.raises(ValueError):
        quantidade_para(1352, 1000.37)
