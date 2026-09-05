"""O email de segunda-feira.

Um email não é uma página: o Outlook desenha com o motor do Word e o Gmail
apaga o `<style>`. O que se defende aqui é isso, e sobretudo a regra do
módulo — o que não se sabe escreve-se por extenso e nunca como "0,00 €".
"""
from datetime import date

import pytest

from plataformas import email_semanal as mail
from plataformas import resumo

from .test_resumo import QUINZENA, SEGUNDA, SEMANA, SEMANA_ANTES, registo


def dados(registos=(), avisos=()):
    return resumo.montar_relatorio(hoje=SEGUNDA, ate="08:00",
                                   registos=list(registos), avisos=list(avisos))


def html(registos=(), avisos=(), url=None):
    return mail.html_do_relatorio(dados(registos, avisos), url_do_painel=url)


COMPLETO = [
    # A Uber manda um relatório POR LOJA — é assim que eles chegam a sério.
    registo("uber", *SEMANA, loja="Alfragide", liquido=700.0, pedidos=120,
            problemas=["3 pedidos cancelados por falta de estafeta"]),
    registo("uber", *SEMANA, loja="Oeiras", liquido=500.0, pedidos=90),
    registo("bolt", *SEMANA, liquido=540.25, pedidos=95),
    registo("glovo", *QUINZENA, liquido=880.10, pedidos=140),
    registo("uber", *SEMANA_ANTES, liquido=1000.0, pedidos=190),
    registo("bolt", *SEMANA_ANTES, liquido=500.0, pedidos=88),
]


# --- As regras do meio: nada que o Outlook não desenhe -----------------------

@pytest.mark.parametrize("proibido", [
    "display:flex", "display:grid", "var(--", "<style", "@media", "<svg",
])
def test_o_email_nao_usa_nada_que_o_outlook_apague(proibido):
    assert proibido not in html(COMPLETO)


def test_o_email_e_uma_pagina_html_completa():
    saida = html(COMPLETO)
    assert saida.startswith("<!doctype html>")
    assert saida.rstrip().endswith("</html>")


def test_as_pecas_emprestadas_do_relatorio_diario_continuam_a_existir():
    """Este módulo importa a paleta e os formatadores do email do relatório
    diário. Se alguém lá mudar um nome, o desfecho tem de ser este teste
    vermelho — e não o email de segunda-feira a não sair."""
    from faturacao import relatorio_email as base

    for nome in ("FUNDO", "CARTAO", "TEXTO", "TEXTO_FRACO", "PRIMARIA", "LINHA",
                 "BOM", "MAU", "AVISO", "AVISO_FUNDO", "FONTE", "LARGURA",
                 "PRIMARIA_FRACA", "_euros", "_texto", "_pilula", "_cartao",
                 "_dia_curto", "_percentagem", "_titulo_de_seccao",
                 "_barra_de_proporcao"):
        assert hasattr(base, nome), "faltou %s" % nome


# --- O que falta escreve-se, não se arredonda a zero ------------------------

def test_uma_plataforma_sem_relatorio_diz_o_que_falta_e_nao_mostra_zero():
    saida = html([registo("uber", *SEMANA, liquido=1200.0, pedidos=210)])
    assert "Relatório não recebido" in saida
    assert "não são zero" in saida
    # **Só a Uber tem um valor "A receber".** A Bolt e a Glovo não chegaram, e
    # um cartão delas com um número seria um número inventado. (O rótulo do
    # total é "A receber esta semana", por isso não entra nesta contagem.)
    assert saida.count(">A receber <span") == 1


def test_o_total_parcial_avisa_que_e_parcial():
    saida = html([registo("uber", *SEMANA, liquido=1200.0)])
    assert "Este total est\xe1 incompleto" in saida
    assert "Falta o relat\xf3rio da Bolt Food" in saida
    assert "(parcial)" in mail.assunto(dados([registo("uber", *SEMANA, liquido=1200.0)]))


def test_um_total_parcial_nao_diz_que_falta_a_semana_anterior():
    """Semana anterior há. O que não há é uma comparação honesta a fazer com
    um total ao qual falta uma plataforma — e as duas frases significam coisas
    diferentes para quem lê."""
    saida = html([registo("uber", *SEMANA, liquido=1200.0),
                  registo("uber", *SEMANA_ANTES, liquido=1000.0),
                  registo("bolt", *SEMANA_ANTES, liquido=500.0)])
    assert "Compara\xe7\xe3o suspensa" in saida
    assert "Sem semana anterior para comparar" not in saida


def test_nenhuma_entidade_HTML_aparece_escrita_a_letra():
    """`_titulo_de_seccao` escapa o que recebe (é texto, não marcação): um
    `&middot;` passado lá para dentro saía escrito à letra no email."""
    for saida in (html(COMPLETO), html([])):
        for entidade in ("&amp;middot;", "&amp;mdash;", "&amp;nbsp;", "&amp;#8239;"):
            assert entidade not in saida


def test_com_tudo_lido_nao_aparece_o_aviso_de_parcial():
    saida = html(COMPLETO)
    assert "Este total est\xe1 incompleto" not in saida
    assert "(parcial)" not in mail.assunto(dados(COMPLETO))


def test_sem_relatorio_nenhum_o_email_sai_a_dizer_isso():
    """A segunda-feira em que nada chegou é precisamente a que tem de sair —
    um email que não sai lê-se como "não houve nada a assinalar"."""
    saida = html([])
    assert saida.count("Relatório não recebido") == 3
    assert "&mdash;" in saida


# --- O que o dono abre o email para saber -----------------------------------

def test_o_email_diz_quando_entra_o_dinheiro_de_cada_plataforma():
    saida = html(COMPLETO)
    assert "Pago hoje (31 ago)" in saida          # Uber e Bolt, na segunda
    assert "Entra a 5 set" in saida               # a quinzena fechada da Glovo


def test_uma_plataforma_sem_relatorio_diz_PREVISTO_e_nao_pago():
    """«Pago hoje» ao lado de «relatório não recebido» lê-se como se alguma
    coisa tivesse entrado. A data é do calendário; o valor é desconhecido."""
    saida = html([registo("uber", *SEMANA, liquido=1200.0)])
    assert "Pagamento previsto para hoje (31 ago)" in saida
    assert saida.count("Pago hoje (31 ago)") == 1   # só o cartão da Uber


def test_a_glovo_tem_calendario_mesmo_quando_nao_chegou_email_nenhum():
    saida = html([])
    assert "calend\xe1rio de pagamentos" in saida
    assert "Quinzena a decorrer" in saida
    assert "16 a 31 ago" in saida
    assert "Quinzena fechada" in saida
    assert "1 a 15 ago" in saida


def test_os_problemas_aparecem_com_a_plataforma_ao_lado():
    saida = html(COMPLETO)
    assert "3 pedidos cancelados por falta de estafeta" in saida
    assert "Problemas e cobran\xe7as" in saida


def test_sem_problemas_o_bloco_diz_que_nao_houve_nenhum():
    saida = html([registo("uber", *SEMANA, liquido=10.0)])
    assert "Nenhum relat\xf3rio assinalou problemas" in saida


def test_as_lojas_aparecem_uma_a_uma_e_o_cartao_diz_quantas_sao():
    saida = html(COMPLETO)
    assert "Alfragide" in saida and "Oeiras" in saida
    # De quantas lojas e' o numero grande — sem isso, 1 200 EUR de duas lojas
    # le-se igual a 1 200 EUR de quatro.
    assert "2 lojas" in saida


def test_os_avisos_da_recolha_vao_no_email():
    saida = html([], avisos=["A caixa nao@exemplo.pt não respondeu."])
    assert "Notas da recolha" in saida
    assert "n\xe3o respondeu" in saida


def test_o_botao_do_painel_so_aparece_quando_ha_endereco():
    assert "Ver no painel" not in html(COMPLETO)
    assert "Ver no painel" in html(COMPLETO, url="https://rh.lisbonb.com/admin/painel")


# --- Texto que vem de fora é dado, nunca marcação ---------------------------

def test_o_nome_de_uma_loja_com_HTML_la_dentro_e_escapado():
    saida = html([registo("uber", *SEMANA, liquido=10.0,
                          loja="<script>alerta()</script>")])
    assert "<script>" not in saida
    assert "&lt;script&gt;" in saida


def test_um_problema_com_HTML_la_dentro_e_escapado():
    saida = html([registo("uber", *SEMANA, liquido=10.0,
                          problemas=["<img src=x onerror=1>"])])
    assert "<img src=x" not in saida


def test_o_endereco_do_painel_e_escapado_no_atributo():
    saida = html(COMPLETO, url='https://x.pt/" onmouseover="mau()')
    assert 'onmouseover="mau()' not in saida


# --- O assunto --------------------------------------------------------------

def test_o_assunto_leva_o_numero_e_a_data():
    assunto = mail.assunto(dados(COMPLETO))
    assert assunto.startswith("Plataformas · semana até 30/08 ·")
    assert "1 740,25" in assunto.replace(" ", " ")


def test_o_assunto_nao_leva_entidades_HTML():
    assunto = mail.assunto(dados(COMPLETO))
    assert "&nbsp;" not in assunto and "&#8239;" not in assunto


# --- Períodos que atravessam dois meses -------------------------------------

def test_uma_semana_entre_dois_meses_mostra_os_dois_meses():
    """«31 a 6 set» lê-se como se fosse tudo em Setembro."""
    assert mail._intervalo("2026-08-31", "2026-09-06") == "31 ago a 6 set"
    assert mail._intervalo("2026-08-24", "2026-08-30") == "24 a 30 ago"


def test_uma_loja_que_faltou_nao_se_escreve_como_falta_de_semana_anterior():
    """Semana anterior há — o que mudou foram as lojas que reportaram. As duas
    frases significam coisas diferentes para quem lê."""
    saida = html([
        registo("uber", *SEMANA, loja="Amadora", liquido=100.0),
        registo("uber", *SEMANA_ANTES, loja="Amadora", liquido=90.0),
        registo("uber", *SEMANA_ANTES, loja="Oeiras", liquido=200.0),
    ])
    assert "Compara\xe7\xe3o suspensa &mdash; mudaram as lojas" in saida
    assert "Sem semana anterior para comparar" not in saida
    # E o motivo aparece por extenso na lista de problemas.
    assert "N\xe3o chegou o relat\xf3rio da loja \xabOeiras\xbb" in saida


def test_uma_plataforma_que_chegou_sem_valores_diz_isso_e_nao_zero():
    """A Bolt manda o relatório sem números quando os links não se leem.
    «Recebido sem valores» manda alguém ao portal; «não recebido» não."""
    saida = html([registo("bolt", *SEMANA, loja="Amadora", liquido=None)])
    assert "Relat\xf3rio recebido, sem valores" in saida
    assert "n\xe3o s\xe3o zero" in saida
