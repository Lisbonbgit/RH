"""Matemática da caixa — puro, sem I/O (Task 3 do Plano 2A, spec §7.2/§7.6).

`esperado` é o número que a funcionária tem de bater ao contar a gaveta: o
fundo de maneio + as vendas em dinheiro + as entradas - as saídas. Vive
sozinho, sem Mongo, porque é a parte que tem de estar matematicamente
certa — é o que sustenta a confiança entre o dono e a equipa quando a
contagem não bate e alguém tem de explicar a diferença.
"""
from faturacao.caixa_math import (
    diferenca,
    esperado,
    soma_vendas_dinheiro,
    total_movimentos,
    total_por_tipo,
)


def _mov(tipo, valor):
    return {"tipo": tipo, "valor": valor}


def _pagamento(**over):
    p = {"tipo_pagamento_id": "tipo-dinheiro", "nome": "Dinheiro", "tipo_fiscal": "NU", "valor": 8.99}
    p.update(over)
    return p


def _venda(**over):
    v = {"id": "venda-1", "estado": "emitida", "pagamentos": [_pagamento()]}
    v.update(over)
    return v


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


# --- soma_vendas_dinheiro (Task 4 do Plano 2B) ----------------------------------
#
# Uma venda paga em dinheiro conta para o esperado do fecho; uma venda em
# multibanco não. Lê o snapshot de `tipo_fiscal` gravado em cada pagamento
# no momento da emissão (fiscal.py::finalizar) — nunca reconsulta
# fat_tipos_pagamento ao vivo (que podia ter mudado entretanto).


def test_soma_vendas_dinheiro_com_uma_venda_em_dinheiro():
    assert soma_vendas_dinheiro([_venda()]) == 8.99


def test_soma_vendas_dinheiro_ignora_venda_so_em_multibanco():
    venda_mb = _venda(pagamentos=[_pagamento(tipo_fiscal="CD", valor=8.99)])
    assert soma_vendas_dinheiro([venda_mb]) == 0.0


def test_soma_vendas_dinheiro_com_pagamento_misto_conta_so_a_parte_em_dinheiro():
    """A regra central da Task 4: um pagamento MISTO (parte dinheiro, parte
    cartão) só soma a parte em dinheiro para o esperado da gaveta."""
    venda_mista = _venda(pagamentos=[
        _pagamento(valor=10.0),
        _pagamento(tipo_pagamento_id="tipo-mb", nome="Multibanco", tipo_fiscal="CD", valor=7.98),
    ])
    assert soma_vendas_dinheiro([venda_mista]) == 10.0


def test_soma_vendas_dinheiro_com_varias_vendas_soma_todas():
    vendas = [_venda(id="v1"), _venda(id="v2", pagamentos=[_pagamento(valor=2.5)])]
    assert soma_vendas_dinheiro(vendas) == 11.49


def test_soma_vendas_dinheiro_ignora_venda_nao_emitida():
    """Uma venda 'aberta' (nunca chegou a emitir) ou 'cancelada' não pode
    contar para o esperado — só o dinheiro de vendas REALMENTE facturadas."""
    venda_aberta = _venda(estado="aberta")
    venda_cancelada = _venda(estado="cancelada")
    assert soma_vendas_dinheiro([venda_aberta, venda_cancelada]) == 0.0


def test_soma_vendas_dinheiro_com_lista_vazia_e_zero():
    assert soma_vendas_dinheiro([]) == 0.0


def test_soma_vendas_dinheiro_venda_sem_pagamentos_nao_rebenta():
    """Defensivo: uma venda emitida sem o campo 'pagamentos' (não devia
    acontecer, mas não pode rebentar o fecho de caixa)."""
    venda_sem_pagamentos = _venda()
    del venda_sem_pagamentos["pagamentos"]
    assert soma_vendas_dinheiro([venda_sem_pagamentos]) == 0.0
