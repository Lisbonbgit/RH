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


# --- A GAVETA ABAIXO DO FUNDO, e o campo que ninguém lia -----------------------
#
# **`devolucao.acima_do_recebido` era um campo só de escrita.** Gravado em
# `nota_credito.py` com o comentário «o gestor encontra isso depois» — e um
# `grep` em todo o repositório dava só a escrita e os testes. Ninguém o lia,
# em lado nenhum.
#
# Medido pelas rotas reais: fatura de 24,14 € paga **5,00 em dinheiro + 19,14
# em Multibanco**, açaí de 20,40 € devolvido em **DINHEIRO** →
# `vendas_dinheiro` **−15,40 €** e o esperado da gaveta **34,60 €** com fundo
# de 50,00. **15,40 € abaixo do fundo**, e nenhum campo do resumo do turno o
# dizia: nem o esperado abaixo do fundo, nem as vendas em dinheiro negativas.
# A operadora conta a gaveta às 23h, encontra 34,60 € e bate certo — com
# 15,40 € que aquele turno nunca lá pôs.

from faturacao.caixa_math import devolucoes_acima_do_recebido, tirado_da_gaveta_a_mais


def _nota_devolvida(valor, acima=0.0, estado="emitida", tipo_fiscal="NU"):
    return {
        "estado": estado,
        "devolucao": {"tipo_pagamento_id": "t-nu", "nome": "Dinheiro",
                      "tipo_fiscal": tipo_fiscal, "valor": valor,
                      "acima_do_recebido": acima},
    }


def test_tirado_da_gaveta_a_mais_diz_quanto_saiu_alem_do_que_entrou():
    """Vendas em dinheiro **−15,40 €**: saíram 15,40 € da gaveta que aquele
    turno nunca lá pôs — a fatura recebeu 5,00 em dinheiro e a devolução
    levou 20,40."""
    assert tirado_da_gaveta_a_mais(-15.40) == 15.40


def test_tirado_da_gaveta_a_mais_e_ZERO_num_turno_normal():
    """O controlo: um aviso que estivesse sempre lá não era aviso nenhum."""
    assert tirado_da_gaveta_a_mais(24.14) == 0.0
    assert tirado_da_gaveta_a_mais(0.0) == 0.0
    assert tirado_da_gaveta_a_mais(None) == 0.0


def test_tirado_da_gaveta_a_mais_conta_em_CENTIMOS_INTEIROS():
    """0,29 + 1,15 + 10,20 em vírgula flutuante dá 11,639999999999999 — e este
    número aparece a dizer a uma operadora que a gaveta está mal."""
    assert tirado_da_gaveta_a_mais(-(0.29 + 1.15 + 10.20)) == 11.64


def test_tirado_da_gaveta_a_mais_NAO_pergunta_pelo_fundo_nem_pelo_esperado():
    """**O oitavo defeito, na assinatura.** A versão anterior era
    `abaixo_do_fundo(fundo, esperado)` — e o `esperado` inclui os movimentos de
    caixa, o que a fazia falhar nos dois sentidos (ver os dois cenários em
    `test_ponto_de_caixa.py`). O invariante é sobre as VENDAS EM DINHEIRO, e é
    por isso que esta função só tem um argumento: não há por onde um movimento
    lhe entrar."""
    import inspect

    assert list(inspect.signature(tirado_da_gaveta_a_mais).parameters) == [
        "vendas_dinheiro"]


def test_devolucoes_acima_do_recebido_SOMA_o_campo_que_ninguem_lia():
    """O leitor que faltava. Duas devoluções, 15,40 € e 0,29 € para lá do que
    aquelas faturas receberam naqueles meios."""
    notas = [_nota_devolvida(20.40, acima=15.40), _nota_devolvida(0.29, acima=0.29)]
    assert devolucoes_acima_do_recebido(notas) == 15.69


def test_devolucoes_acima_do_recebido_ignora_a_que_nao_saiu():
    """Só a `emitida`, a mesma regra de `por_tipo_de_pagamento`: uma nota por
    apurar não devolveu nada a ninguém e não pode explicar gaveta nenhuma."""
    notas = [_nota_devolvida(20.40, acima=15.40, estado="incerta"),
             _nota_devolvida(20.40, acima=15.40, estado="reservada")]
    assert devolucoes_acima_do_recebido(notas) == 0.0


def test_devolucoes_acima_do_recebido_e_ZERO_quando_cabe_tudo():
    assert devolucoes_acima_do_recebido([_nota_devolvida(9.85)]) == 0.0
    assert devolucoes_acima_do_recebido([]) == 0.0


def test_uma_nota_gravada_ANTES_deste_campo_nao_rebenta_o_fecho():
    """Defensivo, e é o caso real das notas já gravadas: sem o campo, soma
    zero — nunca uma excepção no meio de um fecho de caixa."""
    nota = {"estado": "emitida", "devolucao": {"valor": 9.85}}
    assert devolucoes_acima_do_recebido([nota]) == 0.0
