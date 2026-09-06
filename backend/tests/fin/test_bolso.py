"""**A matemática do painel de bolso.**

Todos estes testes correm sem Mongo e sem FastAPI — é essa a razão de a
matemática viver no `bolso.py` e a rota no `server.py`.

O que se defende aqui é sobretudo uma coisa: **o painel não pode inventar uma
percentagem.** Foi por percentagens inventadas que o dashboard do Vendus
anunciou −64% num mês que estava a subir, e é o defeito que este módulo existe
para não repetir.
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import bolso


# `None` é um VALOR legítimo do `amount_net` (é o que as linhas do nosso POS
# levam), por isso o sentinela do ajudante não pode ser `None` — era, e o teste
# do líquido em falta estava a passar um valor calculado sem dar por isso.
_POR_CALCULAR = object()


def _linha(dia, valor, unit_id="u1", company_id="e1", liquido=_POR_CALCULAR):
    return {
        "date": dia, "amount": valor, "company_id": company_id, "unit_id": unit_id,
        "amount_net": round(valor / 1.13, 2) if liquido is _POR_CALCULAR else liquido,
    }


# --- O dia de hoje -----------------------------------------------------------

def test_hoje_e_o_dia_de_LISBOA_e_nao_o_de_utc():
    """00:30 de 4 de Setembro em Lisboa é ainda 23:30 do dia 3 em UTC. O
    servidor corre em UTC: sem esta conversão, o painel mostrava o dia
    anterior a quem fecha a caixa depois da meia-noite."""
    meia_noite_e_meia = datetime(2026, 9, 3, 23, 30, tzinfo=ZoneInfo("UTC"))
    assert bolso.hoje_em_lisboa(meia_noite_e_meia) == date(2026, 9, 4)


# --- As janelas --------------------------------------------------------------

def test_o_mes_compara_os_MESMOS_dias_do_mes_anterior():
    """O defeito do Vendus, evitado: a 5 de Setembro compara-se 1–4 de
    Setembro com 1–4 de Agosto — nunca com Agosto inteiro."""
    js = bolso.janelas(date(2026, 9, 5))

    assert js["mes_completo"] == (date(2026, 9, 1), date(2026, 9, 4))
    assert js["mes_anterior"] == (date(2026, 8, 1), date(2026, 8, 4))


def test_o_ano_compara_os_mesmos_dias_do_ano_anterior():
    js = bolso.janelas(date(2026, 9, 5))

    assert js["ano_completo"] == (date(2026, 1, 1), date(2026, 9, 4))
    assert js["ano_anterior"] == (date(2025, 1, 1), date(2025, 9, 4))


def test_o_valor_do_mes_inclui_hoje_mas_a_comparacao_nao():
    """São duas janelas e não uma, de propósito: o gestor quer ver quanto vai
    o mês HOJE, mas comparar um mês a meio de um dia com um mês inteiro é o
    erro que se está a evitar."""
    js = bolso.janelas(date(2026, 9, 5))

    assert js["mes"] == (date(2026, 9, 1), date(2026, 9, 5)), "o valor inclui hoje"
    assert js["mes_completo"][1] == date(2026, 9, 4), "a comparação pára ontem"


def test_no_dia_1_nao_ha_comparacao_do_mes_e_isso_e_uma_resposta():
    """A 1 de Setembro não existe um único dia completo deste mês. Comparar
    contra nada dava −100%; não comparar é a verdade."""
    js = bolso.janelas(date(2026, 9, 1))

    assert js["mes_completo"] is None
    assert js["mes_anterior"] is None
    assert js["mes"] == (date(2026, 9, 1), date(2026, 9, 1)), "o valor do dia existe na mesma"


def test_o_dia_30_comparado_com_fevereiro_nao_rebenta():
    """31 de Fevereiro não existe. A trava do último dia do mês morde aqui: a
    31 de Março, os dias completos são 1–30 de Março, e o mês anterior
    equivalente teria de ir até 30 de Fevereiro — que não existe. Sem a
    trava, o painel levantava excepção em vez de mostrar números."""
    js = bolso.janelas(date(2026, 3, 31))  # ontem = 30 de Março

    assert js["mes_completo"] == (date(2026, 3, 1), date(2026, 3, 30))
    assert js["mes_anterior"] == (date(2026, 2, 1), date(2026, 2, 28))


def test_no_dia_1_de_abril_o_mes_de_abril_ainda_nao_tem_dias_completos():
    """E é a resposta certa: o cartão do mês mostra o valor de hoje e não
    compara. Comparar Abril (um dia) com Março (inteiro) é exactamente o
    defeito que este módulo existe para não repetir."""
    js = bolso.janelas(date(2026, 4, 1))

    assert js["mes_completo"] is None
    assert js["mes"] == (date(2026, 4, 1), date(2026, 4, 1))


def test_29_de_fevereiro_compara_com_28_no_ano_seguinte():
    js = bolso.janelas(date(2025, 3, 1))  # ontem = 28 de Fevereiro de 2025

    assert js["ano_anterior"][1] == date(2024, 2, 28)


def test_em_janeiro_o_mes_anterior_e_dezembro_do_ano_passado():
    js = bolso.janelas(date(2026, 1, 10))

    assert js["mes_anterior"] == (date(2025, 12, 1), date(2025, 12, 9))


# --- As somas ----------------------------------------------------------------

def test_a_soma_respeita_as_pontas_do_intervalo():
    linhas = [_linha("2026-09-01", 10.0), _linha("2026-09-05", 20.0),
              _linha("2026-09-06", 999.0)]

    r = bolso.somar(linhas, (date(2026, 9, 1), date(2026, 9, 5)))

    assert r["total"] == 30.0
    assert r["linhas"] == 2


def test_uma_linha_sem_valor_sem_iva_deixa_o_periodo_INTEIRO_sem_ele():
    """As linhas que vêm do nosso POS podem não trazer o valor sem IVA. Somar
    só as outras dava um número MENOR do que a verdade, e é dele que sai a
    margem — prefere-se dizer que não se sabe."""
    linhas = [_linha("2026-09-01", 10.0, liquido=8.85),
              _linha("2026-09-02", 20.0, liquido=None)]

    r = bolso.somar(linhas, (date(2026, 9, 1), date(2026, 9, 2)))

    assert r["total"] == 30.0, "o valor com IVA conta na mesma"
    assert r["sem_iva"] is None


def test_um_intervalo_que_nao_existe_da_None_e_nao_zero():
    """Zero é uma afirmação ("não se vendeu nada"); a ausência de período não
    é. O cartão do mês no dia 1 depende disto."""
    r = bolso.somar([_linha("2026-09-01", 10.0)], None)

    assert r["total"] is None


# --- Os cartões --------------------------------------------------------------

def test_o_cartao_de_ontem_compara_com_anteontem():
    hoje = date(2026, 9, 5)
    js = bolso.janelas(hoje)
    linhas = [_linha("2026-09-04", 120.0), _linha("2026-09-03", 100.0)]

    c = bolso.cartao(linhas, js["ontem"], js["ontem"], js["anteontem"])

    assert c["valor"] == 120.0
    assert c["anterior"] == 100.0
    assert c["variacao"] == pytest.approx(20.0)
    assert "4 de setembro" in c["comparacao"] and "3 de setembro" in c["comparacao"]


def test_o_cartao_de_HOJE_nunca_leva_variacao():
    """A regra que não se negoceia. O `fin_sales` guarda dias, não horas:
    comparar as vendas das 9h da manhã com ontem INTEIRO dá −85% todas as
    manhãs — uma queda que nunca existiu."""
    hoje = date(2026, 9, 5)
    js = bolso.janelas(hoje)

    c = bolso.cartao([_linha("2026-09-05", 30.0)], js["hoje"], nota="dia a decorrer")

    assert c["valor"] == 30.0
    assert c["variacao"] is None
    assert c["anterior"] is None
    assert c["nota"] == "dia a decorrer"


def test_sem_periodo_anterior_nao_se_inventa_percentagem():
    """Primeiro mês de vida do negócio: não há nada com que comparar, e um
    "+100%" seria uma invenção."""
    hoje = date(2026, 9, 5)
    js = bolso.janelas(hoje)

    c = bolso.cartao([_linha("2026-09-04", 120.0)], js["ontem"], js["ontem"], js["anteontem"])

    assert c["valor"] == 120.0
    assert c["variacao"] is None, "anterior a zero não dá percentagem"


# --- As séries ---------------------------------------------------------------

def test_a_serie_de_dias_inclui_os_dias_SEM_vendas():
    """O `fin_sales` não gera linha para um dia sem vendas. Saltar esses dias
    no gráfico encolhia os domingos fechados e mentia sobre o ritmo."""
    hoje = date(2026, 9, 5)
    serie = bolso.serie_de_dias([_linha("2026-09-05", 10.0)], hoje, dias=3)

    assert [p["dia"] for p in serie] == ["2026-09-03", "2026-09-04", "2026-09-05"]
    assert [p["valor"] for p in serie] == [0.0, 0.0, 10.0]


def test_a_serie_de_meses_marca_o_mes_em_curso():
    serie = bolso.serie_de_meses([_linha("2026-09-01", 10.0)], date(2026, 9, 5), meses=3)

    assert [p["mes"] for p in serie] == ["2026-07", "2026-08", "2026-09"]
    assert serie[-1]["em_curso"] is True and serie[0]["em_curso"] is False


def test_a_serie_de_meses_atravessa_a_viragem_do_ano():
    serie = bolso.serie_de_meses([], date(2026, 1, 15), meses=3)

    assert [p["mes"] for p in serie] == ["2025-11", "2025-12", "2026-01"]


# --- A repartição ------------------------------------------------------------

def test_a_reparticao_ordena_da_maior_para_a_menor():
    linhas = [_linha("2026-09-01", 10.0, unit_id="u1"),
              _linha("2026-09-01", 50.0, unit_id="u2")]

    r = bolso.repartir(linhas, (date(2026, 9, 1), date(2026, 9, 1)), "unit_id",
                       {"u1": "Belém", "u2": "Alfragide"})

    assert [x["nome"] for x in r] == ["Alfragide", "Belém"]
    assert r[0]["valor"] == 50.0


def test_uma_linha_sem_loja_aparece_como_SEM_LOJA_e_nao_desaparece():
    """Uma venda manual sem loja tem de continuar a somar no total do painel.
    Escondê-la fazia a soma das lojas não bater com o total — e ninguém
    saberia porquê."""
    linhas = [_linha("2026-09-01", 10.0, unit_id="u1"),
              _linha("2026-09-01", 7.0, unit_id=None)]

    r = bolso.repartir(linhas, (date(2026, 9, 1), date(2026, 9, 1)), "unit_id", {"u1": "Belém"})

    sem = [x for x in r if x["id"] is None]
    assert sem and sem[0]["valor"] == 7.0
    assert sem[0]["nome"] == "Sem loja atribuída"
    assert round(sum(x["valor"] for x in r), 2) == 17.0, "a soma das partes é o total"


# --- Os dias sem vendas ------------------------------------------------------

def test_os_dias_sem_vendas_nao_incluem_hoje():
    """Hoje ainda está a decorrer: não ter vendas às 9h não é um dia sem
    vendas, e marcá-lo dava um alarme falso todas as manhãs."""
    hoje = date(2026, 9, 5)
    faltam = bolso.dias_sem_linha([_linha("2026-09-04", 10.0)], hoje, dias=3)

    assert "2026-09-05" not in faltam
    assert "2026-09-04" not in faltam
    assert faltam == ["2026-09-03", "2026-09-02"]


# --- As frases que explicam a comparação -------------------------------------

def test_a_comparacao_do_ano_diz_de_que_ANO_fala():
    """Sem o ano na frase, o cartão do Ano dizia "1/1 a 5/9 vs 1/1 a 5/9" — a
    mesma frase dos dois lados, como se comparasse o período consigo próprio.
    Apanhado a olhar para o ecrã, não por um teste: é por isso que existe
    agora um."""
    hoje = date(2026, 9, 5)
    js = bolso.janelas(hoje)

    c = bolso.cartao([_linha("2026-05-01", 10.0)], js["ano"], js["ano_completo"], js["ano_anterior"])

    assert "2026" in c["comparacao"] and "2025" in c["comparacao"], c["comparacao"]
    assert c["comparacao"].count("de 2026") == 1
