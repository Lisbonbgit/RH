import pytest
from faturacao.reparticao import (
    parte_acumulada, quantidade_para, repartir_centimos)


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


# --- `parte_acumulada`: as parciais de uma nota de crédito somam a linha ------
#
# A propriedade que faltava, e o defeito que ela fecha: creditar uma linha em
# várias vezes devolvia mais (ou menos) do que a linha valia, porque cada
# parcial arredondava o seu próprio meio-cêntimo para cima.


def test_as_parciais_de_uma_linha_somam_sempre_a_LINHA():
    """**A regra que não se negoceia, agora no tempo.** Uma linha creditada em
    quantas parciais forem, por que ordem for, devolve exactamente o que a
    fatura cobrou.

    Sem isto, medido pelas rotas reais: uma linha de 10 × 0,05 € (0,50 €)
    creditada em 100 fatias de 0,1 devolvia **1,00 €, o dobro** — e a regra
    valia para qualquer preço."""
    for total in range(0, 400, 7):
        for quantidade in (1, 2, 3, 10):
            unidades = quantidade * 100000  # 5 casas decimais, como o POS
            for fatias in (1, 2, 3, 4, 7, 100):
                cortes = [
                    (unidades * i) // fatias for i in range(fatias + 1)]
                partes = [
                    parte_acumulada(total, unidades, cortes[i + 1])
                    - parte_acumulada(total, unidades, cortes[i])
                    for i in range(fatias)
                ]
                assert sum(partes) == total, (total, quantidade, fatias, partes)


def test_a_linha_de_dez_a_cinco_centimos_em_cem_fatias_devolve_meio_euro():
    """O caso nomeado, à letra: 10 × 0,05 € creditados em 100 fatias de 0,1."""
    unidades = 10 * 100000
    devolvido = 0
    for i in range(100):
        antes = (unidades * i) // 100
        depois = (unidades * (i + 1)) // 100
        devolvido += (parte_acumulada(50, unidades, depois)
                      - parte_acumulada(50, unidades, antes))
    assert devolvido == 50


def test_a_parte_acumulada_nunca_ANDA_PARA_TRAS():
    """Monotonia — é ela que garante que nenhuma parcial sai negativa. Uma
    parcial negativa era uma nota de crédito a COBRAR ao cliente."""
    unidades = 200000
    anterior = 0
    for ate_aqui in range(0, unidades + 1, 137):
        agora = parte_acumulada(1029, unidades, ate_aqui)
        assert agora >= anterior
        anterior = agora


def test_creditar_a_linha_INTEIRA_de_uma_vez_da_o_total_da_linha():
    """Os dois extremos, que são o que faz a soma telescopar."""
    assert parte_acumulada(1029, 200000, 0) == 0
    assert parte_acumulada(1029, 200000, 200000) == 1029


def test_uma_quantidade_acima_do_total_nao_devolve_mais_do_que_a_linha():
    """A guarda do tecto, aqui também: nenhuma aritmética a jusante pode
    produzir mais do que a linha vale."""
    assert parte_acumulada(1029, 200000, 999999) == 1029


def test_uma_linha_sem_quantidade_nao_rebenta_e_nao_devolve_nada():
    assert parte_acumulada(1029, 0, 5) == 0


def test_a_fatia_e_o_centimo_MAIS_PROXIMO_da_parte_dela_e_nunca_o_de_baixo():
    """O meio-cêntimo arredonda para CIMA, e é a escolha que se toma — a mesma
    de `mapa_imposto._base_em_centimos`, e pela mesma razão: `round()` sobre
    floats faz arredondamento bancário sobre a representação binária, e a
    truncatura empurra sistematicamente a primeira fatia para baixo.

    Medido: metade de uma linha de 0,29 € vale 0,145 €. Com o meio-cêntimo
    para cima a primeira metade devolve 0,15 € e a segunda 0,14 €; com
    truncatura devolvia 0,14 € e 0,15 €. **A soma fecha nos dois casos** — por
    isso a soma sozinha não prende esta decisão, e sem este teste ela ficava
    por escrever no sítio onde se vê."""
    metade = 100000  # 1 de 2, a 5 casas decimais
    assert parte_acumulada(29, 200000, metade) == 15
    assert parte_acumulada(29, 200000, 200000) - 15 == 14
    # E o caso simétrico, que é o que a truncatura acertaria por acaso.
    assert parte_acumulada(30, 200000, metade) == 15
