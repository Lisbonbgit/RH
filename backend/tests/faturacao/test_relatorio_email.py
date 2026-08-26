"""**O email do relatório diário** — o HTML, sem Mongo e sem envio.

Um email não é uma página: o Gmail apaga `<svg>` e `<style>`, o Outlook
desenha com o motor do Word (sem flexbox, sem grid, sem `border-radius` em
metade dos sítios) e nenhum dos dois percebe CSS variables. Por isso o
desenho é feito com tabelas aninhadas e estilos em linha, e as alturas das
colunas do gráfico vêm em PIXÉIS calculados aqui — uma altura em
percentagem não é fiável em cliente de email nenhum.

Estes testes guardam o que não pode falhar num email que fala de dinheiro:
que os números aparecem, que aparecem UMA vez cada, que nada rebenta num dia
vazio, e que o que o cliente de email não suporta nunca chega a ser escrito.
O que eles NÃO conseguem medir é se está bonito — isso vê-se, e viu-se.
"""
import re

import pytest

from faturacao.relatorio_email import (
    _altura_da_coluna,
    _euros,
    html_do_relatorio,
)


def _dados(**kw):
    base = {
        "dia": "2026-08-26",
        "ate": "23:30",
        "com_iva": True,
        "ha_vendas": True,
        "geral": {
            "faturacao": 977.38,
            "faturacao_ontem": 1213.05,
            "dia_de_ontem": "2026-08-25",
            "variacao": -19.45,
            "documentos": 42,
            "caixa": {"estado": "fechado", "esperado": 310.5, "contado": 308.0,
                      "diferenca": -2.5, "turnos_abertos": 0},
            "pagamentos": [{"nome": "Multibanco", "total": 600.0, "quantos": 30},
                           {"nome": "Dinheiro", "total": 377.38, "quantos": 20}],
        },
        "serie": [{"data": "2026-08-2%d" % d, "valor": v, "hoje": d == 6}
                  for d, v in ((4, 800.0), (5, 1213.05), (6, 977.38))],
        "lojas": [
            {"id": "l1", "nome": "L'açaí Alfragide", "faturacao": 600.0,
             "documentos": 25, "sem_vendas": False,
             "caixa": {"estado": "fechado", "esperado": 200.0, "contado": 198.0,
                       "diferenca": -2.0, "turnos_abertos": 0},
             "pagamentos": [{"nome": "Multibanco", "total": 400.0, "quantos": 15}]},
            {"id": "l2", "nome": "L'açaí Oeiras", "faturacao": 377.38,
             "documentos": 17, "sem_vendas": False,
             "caixa": {"estado": "aberto", "esperado": 110.5, "contado": None,
                       "diferenca": None, "turnos_abertos": 1},
             "pagamentos": []},
        ],
        "artigos": [
            {"nome": "Açaí", "quantidade": 41,
             "variantes": [{"nome": "Small", "quantidade": 26},
                           {"nome": "Regular", "quantidade": 15}]},
            {"nome": "Água 33cl", "quantidade": 12, "variantes": []},
        ],
    }
    base.update(kw)
    return base


@pytest.fixture(scope="module")
def html():
    return html_do_relatorio(_dados())


# --- O que o cliente de email não perdoa -------------------------------------


def test_o_email_NAO_leva_svg(html):
    """O Gmail apaga-o. Um gráfico em SVG chegava como um buraco branco."""
    assert "<svg" not in html.lower()


def test_o_email_NAO_leva_variaveis_css(html):
    """`hsl(var(--primary))` não existe em email nenhum: a cor cai para preto
    ou para nada, e o desenho desfaz-se todo."""
    assert "var(--" not in html


def test_o_email_NAO_depende_de_flex_nem_de_grid(html):
    """O Outlook desenha com o motor do Word. Uma linha de cartões em flex
    empilha-se toda numa coluna e o relatório fica ilegível."""
    assert "display:flex" not in html.replace(" ", "")
    assert "display:grid" not in html.replace(" ", "")


def test_as_alturas_das_colunas_vao_em_PIXEIS(html):
    """Uma altura em percentagem não é fiável em cliente de email nenhum — a
    coluna aparece com 0 de altura e o gráfico some-se."""
    barras = re.findall(r'data-coluna="[^"]*"[^>]*height:\s*(\d+)px', html)
    assert barras, "Não se encontraram colunas com altura em pixéis."


# --- Os números aparecem, e aparecem certos ----------------------------------


def test_a_faturacao_do_dia_aparece(html):
    assert _euros(977.38) in html


def test_a_variacao_contra_ontem_aparece_com_SINAL_e_palavra(html):
    """Cor sozinha não pode carregar significado: quem não distingue verde de
    vermelho tem de ler a mesma coisa. Por isso o sinal e a palavra."""
    assert "19,45" in html
    assert "ontem" in html.lower()


def test_o_caixa_geral_mostra_esperado_contado_e_diferenca(html):
    assert _euros(310.5) in html
    assert _euros(308.0) in html
    assert "2,50" in html


def test_cada_loja_aparece_com_a_sua_faturacao(html):
    assert "L'açaí Alfragide" in html or "L&#39;açaí Alfragide" in html
    assert _euros(600.0) in html
    assert _euros(377.38) in html


def test_a_loja_com_o_turno_ABERTO_diz_o_em_palavras(html):
    """Sem isto, uma gaveta por contar aparecia com um traço e lia-se como
    zero — que é o número mais caro que um relatório pode dizer."""
    assert "aberto" in html.lower()


def test_os_pagamentos_totais_aparecem(html):
    assert "Multibanco" in html
    assert _euros(600.0) in html


def test_o_top_de_artigos_traz_o_ACAI_e_os_TAMANHOS(html):
    """O pedido do dono: o Açaí no top, e por baixo como se reparte."""
    assert "Açaí" in html
    assert "41" in html
    assert "Small" in html and "26" in html
    assert "Regular" in html


def test_a_HORA_do_corte_esta_escrita_no_email(html):
    """O buraco conhecido das 23:30, dito no próprio email: quem o lê nunca
    tem de adivinhar o que está lá dentro."""
    assert "23:30" in html


# --- Os dias difíceis --------------------------------------------------------


def test_um_dia_SEM_VENDAS_nao_rebenta_e_diz_o():
    """Envia-se na mesma: um email que não chega é ambíguo — avariou, ou não
    houve movimento?"""
    vazio = _dados(ha_vendas=False, serie=[], lojas=[], artigos=[], geral={
        "faturacao": 0.0, "faturacao_ontem": 0.0, "dia_de_ontem": None,
        "variacao": None, "documentos": 0,
        "caixa": {"estado": "sem_turno", "esperado": None, "contado": None,
                  "diferenca": None, "turnos_abertos": 0},
        "pagamentos": []})
    saida = html_do_relatorio(vazio)
    assert "sem vendas" in saida.lower()
    assert "<svg" not in saida.lower()


def test_uma_serie_toda_a_ZERO_nao_divide_por_zero():
    """Uma loja nova, ou um dia de encerramento: o gráfico tem de desenhar-se
    a zeros em vez de rebentar o email da noite inteira."""
    saida = html_do_relatorio(_dados(serie=[
        {"data": "2026-08-25", "valor": 0.0, "hoje": False},
        {"data": "2026-08-26", "valor": 0.0, "hoje": True}]))
    assert "<td" in saida


def test_o_nome_de_uma_loja_com_HTML_la_dentro_nao_escapa(html):
    """Os nomes vêm da base de dados e são dados, não marcação. Um `<` num
    nome de loja partia o email — e, num que se reencaminha, é pior do que
    isso."""
    saida = html_do_relatorio(_dados(lojas=[{
        "id": "x", "nome": "<script>alert(1)</script>", "faturacao": 1.0,
        "documentos": 1, "sem_vendas": False,
        "caixa": {"estado": "sem_turno", "esperado": None, "contado": None,
                  "diferenca": None, "turnos_abertos": 0},
        "pagamentos": []}]))
    assert "<script>" not in saida
    assert "&lt;script&gt;" in saida


# --- A altura das colunas ----------------------------------------------------


def test_a_coluna_do_MAIOR_dia_e_a_mais_alta():
    assert _altura_da_coluna(100.0, 100.0, 90) == 90


def test_uma_coluna_de_ZERO_continua_a_VER_SE():
    """Um dia sem vendas com altura 0 desaparece do gráfico, e o leitor conta
    treze colunas onde devia contar catorze."""
    assert _altura_da_coluna(0.0, 100.0, 90) >= 2


def test_a_coluna_e_PROPORCIONAL_ao_valor():
    assert _altura_da_coluna(50.0, 100.0, 90) == 45


def test_um_maximo_a_ZERO_nao_divide_por_zero():
    assert _altura_da_coluna(0.0, 0.0, 90) >= 2


# --- O defeito visto no email desenhado --------------------------------------


def test_com_um_turno_ABERTO_o_esperado_mostrado_e_o_COMPARAVEL():
    """O cartão mostrava «Esperado 588,94 · Contado 484,85» e «Falta 6,75 €»:
    os três certos e, juntos, a mentir — o esperado somava as lojas todas e o
    contado só as que fecharam a gaveta. Quem subtrai os dois números que tem
    à frente dá 104,09 e conclui que o relatório se enganou.

    Apanhado a olho, no email já desenhado. Nenhum dos outros testes o via,
    porque cada número, sozinho, estava certo."""
    dados = _dados()
    dados["geral"]["caixa"] = {
        "estado": "aberto", "esperado": 588.94, "esperado_contado": 491.60,
        "esperado_aberto": 97.34, "contado": 484.85, "diferenca": -6.75,
        "turnos_abertos": 1}
    saida = html_do_relatorio(dados)
    assert _euros(491.6) in saida, "Não mostra o esperado dos turnos contados."
    assert _euros(588.94) not in saida, (
        "Ainda mostra o esperado de TODAS as lojas ao lado do contado — é o par "
        "que convida à subtracção errada.")
    assert "contados" in saida.lower(), "O rótulo não diz que é só dos contados."
    assert _euros(97.34) in saida, "Não diz quanto ficou por contar."
