"""As datas de pagamento das três plataformas.

É o único sítio do módulo onde vive a regra de negócio do dono, e é a parte
que ninguém consegue confirmar a olho no email: um erro aqui não se vê, só se
descobre no dia em que o dinheiro não entra na data que o relatório prometeu.
"""
from datetime import date

from plataformas import calendario as cal


# --- Uber Eats e Bolt Food: segunda a domingo, pago na segunda seguinte ------

def test_na_segunda_a_semana_e_a_que_acabou_ontem():
    # Segunda, 31 de Agosto de 2026 — o dia em que o relatório sai.
    inicio, fim = cal.semana_fechada(date(2026, 8, 31))
    assert inicio == date(2026, 8, 24)  # segunda anterior
    assert fim == date(2026, 8, 30)     # domingo, ontem
    assert fim.weekday() == 6 and inicio.weekday() == 0


def test_a_meio_da_semana_continua_a_ser_a_semana_anterior():
    """Nunca a semana em curso: a meio dela as plataformas ainda não fecharam
    contas nenhumas, e os números mudavam depois de o email sair."""
    for dia, esperado in (
        (date(2026, 9, 2), (date(2026, 8, 24), date(2026, 8, 30))),   # quarta
        (date(2026, 9, 6), (date(2026, 8, 24), date(2026, 8, 30))),   # domingo
        (date(2026, 9, 7), (date(2026, 8, 31), date(2026, 9, 6))),    # segunda
    ):
        assert cal.semana_fechada(dia) == esperado


def test_a_uber_e_a_bolt_pagam_na_segunda_a_seguir_ao_domingo():
    _, fim = cal.semana_fechada(date(2026, 8, 31))
    pagamento = cal.pagamento_semanal(fim)
    assert pagamento == date(2026, 8, 31)
    assert pagamento.weekday() == 0


def test_a_semana_atravessa_a_viragem_do_mes_e_do_ano():
    inicio, fim = cal.semana_fechada(date(2027, 1, 4))  # segunda
    assert (inicio, fim) == (date(2026, 12, 28), date(2027, 1, 3))
    assert cal.pagamento_semanal(fim) == date(2027, 1, 4)


def test_a_chave_da_semana_e_ISO_e_nao_o_ano_civil():
    """A semana que começa a 30/12/2024 é a PRIMEIRA de 2025 no calendário ISO.
    Com o ano civil do dia de início chamar-se-ia `2024-W01` — a mesma chave da
    primeira semana de Janeiro de 2024, e o relatório não saía por «já ter sido
    enviado» um ano antes.

    E 2026 tem 53 semanas ISO: a que começa a 28/12/2026 ainda é de 2026.
    """
    assert cal.chave_da_semana(date(2024, 12, 30)) == "2025-W01"
    assert cal.chave_da_semana(date(2026, 12, 28)) == "2026-W53"
    assert cal.chave_da_semana(date(2026, 8, 24)) == "2026-W35"


def test_duas_semanas_seguidas_nunca_partilham_a_chave():
    vistas = set()
    dia = date(2025, 1, 6)  # uma segunda-feira
    for _ in range(400):  # quase oito anos de segundas seguidas
        chave = cal.chave_da_semana(dia)
        assert chave not in vistas, "chave repetida em %s" % dia
        vistas.add(chave)
        dia = date.fromordinal(dia.toordinal() + 7)


# --- Glovo: quinzenas, pagas no mês seguinte --------------------------------

def test_a_quinzena_de_um_dia():
    assert cal.quinzena_de(date(2026, 8, 1)) == (date(2026, 8, 1), date(2026, 8, 15))
    assert cal.quinzena_de(date(2026, 8, 15)) == (date(2026, 8, 1), date(2026, 8, 15))
    assert cal.quinzena_de(date(2026, 8, 16)) == (date(2026, 8, 16), date(2026, 8, 31))
    assert cal.quinzena_de(date(2026, 8, 31)) == (date(2026, 8, 16), date(2026, 8, 31))


def test_a_segunda_quinzena_acaba_no_ultimo_dia_do_mes_seja_ele_qual_for():
    assert cal.quinzena_de(date(2026, 4, 20))[1] == date(2026, 4, 30)   # 30 dias
    assert cal.quinzena_de(date(2026, 2, 20))[1] == date(2026, 2, 28)   # Fevereiro
    assert cal.quinzena_de(date(2028, 2, 20))[1] == date(2028, 2, 29)   # bissexto


def test_a_quinzena_fechada_no_dia_16_e_a_de_1_a_15():
    assert cal.quinzena_fechada(date(2026, 8, 16)) == (date(2026, 8, 1), date(2026, 8, 15))


def test_a_quinzena_que_fecha_HOJE_ainda_nao_conta_como_fechada():
    """O defeito que isto apanhou: a 31 de Agosto, «ontem» (dia 30) ainda
    pertence à quinzena de 16 a 31, que só acaba ao fim do dia de hoje. O
    relatório dava-a como fechada com as vendas de hoje por contar."""
    assert cal.quinzena_fechada(date(2026, 8, 31)) == (date(2026, 8, 1), date(2026, 8, 15))
    # O mesmo no dia 15, o último da primeira quinzena.
    assert cal.quinzena_fechada(date(2026, 8, 15)) == (date(2026, 7, 16), date(2026, 7, 31))


def test_a_quinzena_fechada_no_dia_1_e_a_do_mes_passado():
    assert cal.quinzena_fechada(date(2026, 9, 1)) == (date(2026, 8, 16), date(2026, 8, 31))
    # E a 1 de Janeiro, a do mês passado é do ANO passado.
    assert cal.quinzena_fechada(date(2027, 1, 1)) == (date(2026, 12, 16), date(2026, 12, 31))


def test_a_glovo_paga_no_dia_5_e_no_dia_20_do_mes_SEGUINTE():
    # Vendas de 1 a 15 de Agosto -> 5 de Setembro.
    assert cal.pagamento_glovo(date(2026, 8, 1)) == date(2026, 9, 5)
    # Vendas de 16 a 31 de Agosto -> 20 de Setembro.
    assert cal.pagamento_glovo(date(2026, 8, 16)) == date(2026, 9, 20)


def test_o_pagamento_da_glovo_de_dezembro_cai_em_janeiro_do_ano_seguinte():
    assert cal.pagamento_glovo(date(2026, 12, 1)) == date(2027, 1, 5)
    assert cal.pagamento_glovo(date(2026, 12, 16)) == date(2027, 1, 20)


def test_o_pagamento_da_glovo_e_sempre_depois_do_fim_da_quinzena():
    """Uma data de pagamento ANTES de o período fechar seria absurda, e é o
    desfecho de qualquer engano no mês (um `mes` em vez de `mes + 1`)."""
    dia = date(2026, 1, 1)
    while dia < date(2029, 1, 1):
        inicio, fim = cal.quinzena_de(dia)
        assert cal.pagamento_glovo(inicio) > fim
        dia = date.fromordinal(dia.toordinal() + 1)


# --- O formato comum que o email consome ------------------------------------

def test_o_periodo_tem_o_mesmo_formato_para_as_tres_plataformas():
    hoje = date(2026, 8, 31)
    for chave in ("uber", "bolt", "glovo"):
        p = cal.periodo_da_plataforma(chave, hoje)
        assert set(p) == {"tipo", "inicio", "fim", "chave", "pagamento",
                          "dias_para_pagamento", "pago"}
        assert p["inicio"] <= p["fim"] < p["pagamento"]


def test_na_segunda_a_uber_e_a_bolt_sao_pagas_HOJE_e_a_glovo_nao():
    hoje = date(2026, 8, 31)
    uber = cal.periodo_da_plataforma("uber", hoje)
    assert uber["dias_para_pagamento"] == 0 and uber["pago"] is True

    glovo = cal.periodo_da_plataforma("glovo", hoje)
    # A 31 de Agosto, a quinzena fechada é a de 1 a 15 e é paga a 5 de Setembro.
    assert glovo["inicio"] == "2026-08-01" and glovo["fim"] == "2026-08-15"
    assert glovo["pagamento"] == "2026-09-05"
    assert glovo["dias_para_pagamento"] == 5 and glovo["pago"] is False


def test_o_calendario_da_glovo_diz_a_quinzena_em_curso_e_a_que_espera_pagamento():
    c = cal.calendario_glovo(date(2026, 8, 31))
    assert c["em_curso"]["inicio"] == "2026-08-16"
    assert c["em_curso"]["fim"] == "2026-08-31"
    assert c["em_curso"]["dias_para_fechar"] == 0        # fecha hoje
    assert c["em_curso"]["pagamento"] == "2026-09-20"
    assert c["fechada"]["inicio"] == "2026-08-01"
    assert c["fechada"]["pagamento"] == "2026-09-05"
    assert c["fechada"]["pago"] is False


def test_uma_data_ja_passada_da_dias_negativos_e_nao_zero():
    """Zero lia-se «é hoje». O que aconteceu ontem tem de se distinguir do que
    acontece hoje, senão o email diz «paga hoje» durante uma semana."""
    assert cal.dias_ate(date(2026, 8, 30), date(2026, 8, 31)) == -1
    assert cal.dias_ate(date(2026, 8, 31), date(2026, 8, 31)) == 0
