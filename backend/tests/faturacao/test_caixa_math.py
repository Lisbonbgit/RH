"""Matemática da caixa — puro, sem I/O (Task 3 do Plano 2A, spec §7.2/§7.6).

`esperado` é o número que a funcionária tem de bater ao contar a gaveta: o
fundo de maneio + as vendas em dinheiro + as entradas - as saídas. Vive
sozinho, sem Mongo, porque é a parte que tem de estar matematicamente
certa — é o que sustenta a confiança entre o dono e a equipa quando a
contagem não bate e alguém tem de explicar a diferença.
"""
from faturacao.caixa_math import diferenca, esperado, total_movimentos, total_por_tipo


def _mov(tipo, valor):
    return {"tipo": tipo, "valor": valor}


# --- total_por_tipo ------------------------------------------------------------


def test_total_por_tipo_soma_so_o_tipo_pedido():
    movimentos = [_mov("entrada", 10.0), _mov("saida", 4.0), _mov("entrada", 1.5)]
    assert total_por_tipo(movimentos, "entrada") == 11.5
    assert total_por_tipo(movimentos, "saida") == 4.0


def test_total_por_tipo_com_lista_vazia_e_zero():
    assert total_por_tipo([], "entrada") == 0.0
    assert total_por_tipo([], "saida") == 0.0


def test_total_por_tipo_ignora_tipos_diferentes():
    movimentos = [_mov("entrada", 10.0)]
    assert total_por_tipo(movimentos, "saida") == 0.0


# --- total_movimentos ------------------------------------------------------------


def test_total_movimentos_e_entradas_menos_saidas():
    movimentos = [_mov("entrada", 20.0), _mov("saida", 8.0)]
    assert total_movimentos(movimentos) == 12.0


def test_total_movimentos_com_lista_vazia_e_zero():
    assert total_movimentos([]) == 0.0


def test_total_movimentos_so_saidas_e_negativo():
    movimentos = [_mov("saida", 5.0), _mov("saida", 3.0)]
    assert total_movimentos(movimentos) == -8.0


# --- esperado ------------------------------------------------------------------


def test_esperado_so_com_fundo_sem_vendas_nem_movimentos():
    assert esperado(50.0, 0.0, []) == 50.0


def test_esperado_soma_fundo_e_vendas_em_dinheiro():
    assert esperado(50.0, 120.5, []) == 170.5


def test_esperado_soma_entradas():
    movimentos = [_mov("entrada", 20.0), _mov("entrada", 5.0)]
    assert esperado(50.0, 0.0, movimentos) == 75.0


def test_esperado_subtrai_saidas():
    movimentos = [_mov("saida", 15.0)]
    assert esperado(50.0, 0.0, movimentos) == 35.0


def test_esperado_combina_fundo_vendas_entradas_e_saidas():
    movimentos = [_mov("entrada", 20.0), _mov("saida", 8.0), _mov("entrada", 2.0)]
    assert esperado(50.0, 100.0, movimentos) == 164.0


def test_esperado_com_lista_vazia_de_movimentos():
    assert esperado(50.0, 100.0, []) == 150.0


def test_esperado_com_fundo_e_vendas_a_zero():
    assert esperado(0.0, 0.0, []) == 0.0


# --- diferenca (Task 4: fecho de caixa) -----------------------------------------
#
# contado - esperado: positivo é sobra na gaveta, negativo é falta. É este
# número que a funcionária tem de explicar quando não bate.


def test_diferenca_positiva_quando_ha_sobra():
    assert diferenca(100.0, 105.0) == 5.0


def test_diferenca_negativa_quando_falta_dinheiro():
    assert diferenca(100.0, 92.5) == -7.5


def test_diferenca_zero_quando_bate_certo():
    assert diferenca(100.0, 100.0) == 0.0
