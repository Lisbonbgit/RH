"""Dashboard do módulo Faturação — o primeiro ecrã que o dono vê.

Decisão do dono (2026-08-14): lê as NOSSAS vendas (fat_documentos), nunca o
Vendus — por isso não há aqui nada de rede nem de chave de API. Enquanto o POS
próprio (Plano 2) não vender nada, os cartões são zero e `ha_vendas` é False.

A maior parte destes testes chama `calcula_dashboard` directamente com listas
de dicionários simples — é lógica praticamente pura, sem Mongo. Só os testes
da secção "endpoint" usam duplos de base de dados (mesmo padrão de
test_pagamentos_endpoints.py e test_indices.py) para verificar a ligação:
o filtro da consulta, o parâmetro com_iva e a exigência de gestor_atual.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from faturacao import dashboard as dashboard_mod
from faturacao.dashboard import calcula_dashboard, obter_dashboard
from faturacao.db import COLECOES
from faturacao.periodos import janela_anterior_equivalente, janela_ano

LISBOA = ZoneInfo("Europe/Lisbon")


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _agora(ano, mes, dia, hora=15, minuto=0):
    return datetime(ano, mes, dia, hora, minuto, tzinfo=LISBOA)


def _doc(loja_id, quando_lisboa, total_bruto, total_liquido, tipo="FS", anulado=False):
    return {
        "loja_id": loja_id,
        "emitido_em": quando_lisboa.astimezone(timezone.utc).isoformat(),
        "total_bruto": total_bruto,
        "total_liquido": total_liquido,
        "tipo": tipo,
        "anulado": anulado,
    }


AGORA = _agora(2026, 8, 13, 15, 0)


# --- calcula_dashboard: sem vendas ------------------------------------------
#
# `ha_vendas` NÃO faz parte da resposta de `calcula_dashboard` (I3, ver
# secção mais abaixo "ha_vendas — pergunta à BD, não deduz"): é o endpoint
# que a acrescenta, com uma pergunta directa à base de dados — nunca
# deduzida da janela de `documentos` que aqui entra.

def test_sem_documentos_tudo_a_zero():
    resultado = calcula_dashboard([], [], AGORA, com_iva=True)
    for cartao in resultado["cartoes"].values():
        assert cartao["valor"] == 0
        assert cartao["valor_comparado"] == 0
        assert cartao["variacao"] is None  # não se inventa "-100%" com o anterior a zero
    assert len(resultado["serie_diaria"]) == 30
    assert all(p["valor"] == 0 for p in resultado["serie_diaria"])
    assert len(resultado["ultimos_6_meses"]) == 6
    assert all(m["valor"] == 0 for m in resultado["ultimos_6_meses"])
    assert resultado["por_loja"] == []


def test_lojas_sem_documentos_aparecem_em_por_loja_a_zero():
    """Uma loja configurada mas que ainda não vendeu nada aparece na lista,
    com zeros (incluindo os campos de comparação, ricos, novos) — não
    desaparece do dashboard."""
    lojas = [{"id": "l1", "nome": "Loja Alfa"}]
    resultado = calcula_dashboard([], lojas, AGORA, com_iva=True)
    loja = resultado["por_loja"][0]
    assert loja["loja_id"] == "l1"
    assert loja["nome"] == "Loja Alfa"
    assert loja["hoje"] == 0
    assert loja["hoje_anterior"] == 0
    assert loja["variacao_hoje"] is None  # sem período anterior, não se inventa percentagem
    assert loja["mensal"] == 0
    assert loja["mensal_anterior"] == 0
    assert loja["variacao_mensal"] is None
    assert len(loja["serie_diaria"]) == 30
    assert len(loja["serie_mensal"]) == 6


# --- cartão "hoje" -----------------------------------------------------------

def test_cartao_hoje_soma_so_os_documentos_de_hoje():
    documentos = [
        _doc("l1", _agora(2026, 8, 13, 10, 0), 25.00, 20.33),
        _doc("l1", _agora(2026, 8, 12, 10, 0), 999.00, 900.00),  # ontem: não conta em "hoje"
    ]
    resultado = calcula_dashboard(documentos, [], AGORA, com_iva=True)
    assert resultado["cartoes"]["hoje"]["valor"] == 25.00


def test_cartao_hoje_compara_com_ontem():
    documentos = [
        _doc("l1", _agora(2026, 8, 13, 10, 0), 25.00, 20.33),
        _doc("l1", _agora(2026, 8, 12, 9, 0), 10.00, 8.00),
    ]
    resultado = calcula_dashboard(documentos, [], AGORA, com_iva=True)
    cartao = resultado["cartoes"]["hoje"]
    assert cartao["valor"] == 25.00
    assert cartao["valor_comparado"] == 10.00
    assert cartao["variacao"] == 150.0  # (25-10)/10 * 100
    assert "13 de agosto de 2026" in cartao["comparacao"]
    assert "12 de agosto de 2026" in cartao["comparacao"]


def test_cartao_hoje_no_dia_da_mudanca_da_hora_nao_rebenta():
    """2026-03-29: o dia só tem 23 horas em Lisboa. O cartão 'hoje' não pode
    rebentar nem dar um resultado incoerente nesse dia."""
    agora_dst = _agora(2026, 3, 29, 20, 0)
    resultado = calcula_dashboard([], [], agora_dst, com_iva=True)
    assert resultado["cartoes"]["hoje"]["valor"] == 0


def test_cartao_hoje_negocio_estavel_nao_mostra_queda_de_manha():
    """C2: um negócio com o MESMO valor todos os dias não pode mostrar uma
    queda só porque ainda é de manhã. Antes desta correcção, 'ontem'
    contava o dia inteiro (incl. a noite, ainda por vir hoje) — aqui 'ontem'
    pára às 09:00, a mesma hora a que 'hoje' já vai."""
    agora = _agora(2026, 8, 13, 9, 0)
    documentos = [
        _doc("l1", _agora(2026, 8, 13, 8, 0), 500.00, 400.00),    # hoje, antes das 9h
        _doc("l1", _agora(2026, 8, 12, 8, 0), 500.00, 400.00),    # ontem, à mesma hora: conta
        _doc("l1", _agora(2026, 8, 12, 20, 0), 1000.00, 800.00),  # ontem à noite: NÃO pode contar
    ]
    resultado = calcula_dashboard(documentos, [], agora, com_iva=True)
    cartao = resultado["cartoes"]["hoje"]
    assert cartao["valor"] == 500.00
    assert cartao["valor_comparado"] == 500.00
    assert cartao["variacao"] == 0.0
    assert "até às 09:00" in cartao["comparacao"]


# --- cartão "mensal" — a correção do defeito do Vendus ----------------------

def test_cartao_mensal_compara_1_a_13_de_julho_e_nao_julho_inteiro():
    """O defeito do Vendus: 13 dias de agosto contra julho inteiro (31 dias).
    Um documento de 20 de julho (fora do período equivalente 1-13) não pode
    entrar na comparação."""
    documentos = [
        _doc("l1", _agora(2026, 8, 5, 10, 0), 80.00, 70.00),   # agosto: conta em "valor"
        _doc("l1", _agora(2026, 7, 5, 10, 0), 50.00, 40.00),   # 1-13 julho: conta no equivalente
        _doc("l1", _agora(2026, 7, 20, 10, 0), 999.00, 900.00),  # fora do 1-13: NÃO pode contar
    ]
    resultado = calcula_dashboard(documentos, [], AGORA, com_iva=True)
    cartao = resultado["cartoes"]["mensal"]
    assert cartao["valor"] == 80.00
    assert cartao["valor_comparado"] == 50.00  # não 50 + 999


def test_cartao_anual_compara_periodo_equivalente_do_ano_anterior():
    """225 dias de 2026 contra os primeiros 225 dias de 2025 (também até 13 de
    agosto, porque 2025 não é bissexto) — não o ano de 2025 inteiro."""
    documentos = [
        _doc("l1", _agora(2026, 6, 1, 10, 0), 100.00, 90.00),      # 2026: conta em "valor"
        _doc("l1", _agora(2025, 6, 1, 10, 0), 60.00, 50.00),       # dentro de 1/1-13/8/2025: conta
        _doc("l1", _agora(2025, 12, 1, 10, 0), 999.00, 900.00),    # fora do equivalente: NÃO conta
    ]
    resultado = calcula_dashboard(documentos, [], AGORA, com_iva=True)
    cartao = resultado["cartoes"]["anual"]
    assert cartao["valor"] == 100.00
    assert cartao["valor_comparado"] == 60.00


def test_cartao_mensal_marco_mais_longo_que_fevereiro_nao_finge_crescimento():
    """I1: negócio estável (1500€/dia). A 31 de março, o mês tem 31 dias mas
    fevereiro só 28 — se só se encurtasse fevereiro, março (31 dias
    inteiros) pareceria maior por causa do calendário, não das vendas. Os
    dois lados ficam em 1-28."""
    agora = _agora(2026, 3, 31, 18, 0)
    documentos = (
        [_doc("l1", _agora(2026, 2, dia, 10, 0), 1500.00, 1200.00) for dia in range(1, 29)]
        + [_doc("l1", _agora(2026, 3, dia, 10, 0), 1500.00, 1200.00) for dia in range(1, 32)]
    )
    resultado = calcula_dashboard(documentos, [], agora, com_iva=True)
    cartao = resultado["cartoes"]["mensal"]
    assert cartao["valor"] == 28 * 1500.00        # só 1-28 de março contam (29-31 ficam de fora)
    assert cartao["valor_comparado"] == 28 * 1500.00  # fevereiro inteiro (é tudo o que ele tem)
    assert cartao["variacao"] == 0.0
    assert cartao["comparacao"] == "1–28 de março de 2026, comparado com 1–28 de fevereiro de 2026"


def test_cartoes_mensal_e_anual_a_1_de_janeiro_nao_ficam_vermelhos_o_dia_inteiro():
    """C2, o caso extremo do brief: às 09:00 de 1 de Janeiro, tanto o mês
    como o ano mal começaram. Comparar com Dezembro/o ano anterior inteiros
    (o defeito) dava sempre queda; com o corte por hora, um negócio estável
    mostra 0% em ambos os cartões."""
    agora = _agora(2027, 1, 1, 9, 0)
    documentos = [
        _doc("l1", _agora(2027, 1, 1, 8, 0), 500.00, 400.00),     # este mês E este ano, antes das 9h
        _doc("l1", _agora(2026, 12, 1, 8, 0), 500.00, 400.00),    # dezembro anterior, à mesma hora: conta (mensal)
        _doc("l1", _agora(2026, 12, 1, 20, 0), 999.00, 900.00),   # dezembro anterior, à noite: NÃO pode contar
        _doc("l1", _agora(2026, 1, 1, 8, 0), 500.00, 400.00),     # ano anterior, à mesma hora: conta (anual)
        _doc("l1", _agora(2026, 1, 1, 20, 0), 999.00, 900.00),    # ano anterior, à noite: NÃO pode contar
    ]
    resultado = calcula_dashboard(documentos, [], agora, com_iva=True)
    assert resultado["cartoes"]["mensal"]["valor"] == 500.00
    assert resultado["cartoes"]["mensal"]["valor_comparado"] == 500.00
    assert resultado["cartoes"]["mensal"]["variacao"] == 0.0
    assert resultado["cartoes"]["anual"]["valor"] == 500.00
    assert resultado["cartoes"]["anual"]["valor_comparado"] == 500.00
    assert resultado["cartoes"]["anual"]["variacao"] == 0.0


# --- notas de crédito e documentos anulados ---------------------------------

def test_nota_de_credito_conta_com_sinal_negativo():
    documentos = [
        _doc("l1", _agora(2026, 8, 13, 9, 0), 25.00, 20.00, tipo="FS"),
        _doc("l1", _agora(2026, 8, 13, 11, 0), 5.00, 4.00, tipo="NC"),
    ]
    resultado = calcula_dashboard(documentos, [], AGORA, com_iva=True)
    assert resultado["cartoes"]["hoje"]["valor"] == 20.00  # 25 - 5


def test_nota_de_credito_guardada_negativa_nao_duplica_o_sinal():
    """Defesa: se uma NC viesse guardada já com o campo negativo, não se pode
    voltar a negar (o que a tornaria positiva por engano)."""
    documentos = [_doc("l1", _agora(2026, 8, 13, 9, 0), -5.00, -4.00, tipo="NC")]
    resultado = calcula_dashboard(documentos, [], AGORA, com_iva=True)
    assert resultado["cartoes"]["hoje"]["valor"] == -5.00


def test_documento_anulado_nao_conta():
    documentos = [
        _doc("l1", _agora(2026, 8, 13, 9, 0), 25.00, 20.00, tipo="FS"),
        _doc("l1", _agora(2026, 8, 13, 11, 0), 999.00, 900.00, tipo="FS", anulado=True),
    ]
    resultado = calcula_dashboard(documentos, [], AGORA, com_iva=True)
    assert resultado["cartoes"]["hoje"]["valor"] == 25.00


# --- com_iva troca de campo, nunca inventa uma taxa -------------------------

def test_com_iva_verdadeiro_usa_total_bruto():
    documentos = [_doc("l1", _agora(2026, 8, 13, 9, 0), 123.45, 100.00)]
    resultado = calcula_dashboard(documentos, [], AGORA, com_iva=True)
    assert resultado["cartoes"]["hoje"]["valor"] == 123.45


def test_com_iva_falso_usa_total_liquido_sem_inventar_taxa():
    """100.00 não é 123.45 a dividir por 1.13 nem por 1.23 — é o campo
    total_liquido, lido directamente, tal como precos.py nunca inventa IVA."""
    documentos = [_doc("l1", _agora(2026, 8, 13, 9, 0), 123.45, 100.00)]
    resultado = calcula_dashboard(documentos, [], AGORA, com_iva=False)
    assert resultado["cartoes"]["hoje"]["valor"] == 100.00


# --- por_loja isola correctamente cada loja ---------------------------------

def test_por_loja_nao_mistura_vendas_de_lojas_diferentes():
    lojas = [{"id": "l1", "nome": "Loja Alfa"}, {"id": "l2", "nome": "Loja Beta"}]
    documentos = [
        _doc("l1", _agora(2026, 8, 13, 9, 0), 25.00, 20.00),
        _doc("l2", _agora(2026, 8, 13, 9, 0), 40.00, 32.00),
    ]
    resultado = calcula_dashboard(documentos, lojas, AGORA, com_iva=True)
    por_loja = {p["nome"]: p for p in resultado["por_loja"]}
    assert por_loja["Loja Alfa"]["hoje"] == 25.00
    assert por_loja["Loja Beta"]["hoje"] == 40.00


def test_por_loja_nota_de_credito_conta_negativa_e_anulado_nao_conta():
    """A regra da NC (sinal negativo) e do anulado (não conta) vale por loja,
    não só no total (era o que faltava antes desta tarefa)."""
    lojas = [{"id": "l1", "nome": "Loja Alfa"}]
    documentos = [
        _doc("l1", _agora(2026, 8, 13, 9, 0), 25.00, 20.00, tipo="FS"),
        _doc("l1", _agora(2026, 8, 13, 11, 0), 5.00, 4.00, tipo="NC"),
        _doc("l1", _agora(2026, 8, 13, 12, 0), 999.00, 900.00, tipo="FS", anulado=True),
    ]
    resultado = calcula_dashboard(documentos, lojas, AGORA, com_iva=True)
    assert resultado["por_loja"][0]["hoje"] == 20.00  # 25 - 5, o anulado fica de fora


# --- por_loja "rico": hoje_anterior/variacao_hoje, mensal_anterior/variacao_mensal, serie_mensal ---
#
# O pedido do dono: cada loja do backoffice do Vendus mostra QUATRO números
# (hoje+ontem+sparkline, mensal+anterior+mini-gráfico), não dois. Estes testes
# provam que a loja usa exactamente as MESMAS janelas (`j_hoje_anterior`,
# `j_mes`/`j_mes_anterior`) que os cartões do total — nunca uma versão
# encurtada ou reinventada por loja (era esse, literalmente, o defeito do
# Vendus que periodos.py corrige: comparar com o dia/mês anterior INTEIRO em
# vez do período equivalente).

def test_por_loja_hoje_anterior_usa_o_periodo_equivalente_nao_o_dia_inteiro():
    """Réplica, por loja, de test_cartao_hoje_negocio_estavel_nao_mostra_queda_de_manha:
    um negócio estável não pode mostrar queda de manhã só porque 'ontem'
    seria contado por inteiro (24h) em vez de até à mesma hora do relógio."""
    agora = _agora(2026, 8, 13, 9, 0)
    lojas = [{"id": "l1", "nome": "Loja Alfa"}]
    documentos = [
        _doc("l1", _agora(2026, 8, 13, 8, 0), 500.00, 400.00),    # hoje, antes das 9h
        _doc("l1", _agora(2026, 8, 12, 8, 0), 500.00, 400.00),    # ontem, à mesma hora: conta
        _doc("l1", _agora(2026, 8, 12, 20, 0), 1000.00, 800.00),  # ontem à noite: NÃO pode contar
    ]
    resultado = calcula_dashboard(documentos, lojas, agora, com_iva=True)
    loja = resultado["por_loja"][0]
    assert loja["hoje"] == 500.00
    assert loja["hoje_anterior"] == 500.00  # não 1500.00 (dia de ontem inteiro)
    assert loja["variacao_hoje"] == 0.0
    # E tem de bater com o cartão do total, que usa a mesma janela e o mesmo
    # único documento/loja neste teste.
    assert loja["hoje_anterior"] == resultado["cartoes"]["hoje"]["valor_comparado"]


def test_por_loja_mensal_anterior_usa_1_a_13_de_julho_e_nao_julho_inteiro():
    """Réplica, por loja, de test_cartao_mensal_compara_1_a_13_de_julho_e_nao_julho_inteiro."""
    lojas = [{"id": "l1", "nome": "Loja Alfa"}]
    documentos = [
        _doc("l1", _agora(2026, 8, 5, 10, 0), 80.00, 70.00),      # agosto: conta em "mensal"
        _doc("l1", _agora(2026, 7, 5, 10, 0), 50.00, 40.00),      # 1-13 julho: conta no equivalente
        _doc("l1", _agora(2026, 7, 20, 10, 0), 999.00, 900.00),   # fora do 1-13: NÃO pode contar
    ]
    resultado = calcula_dashboard(documentos, lojas, AGORA, com_iva=True)
    loja = resultado["por_loja"][0]
    assert loja["mensal"] == 80.00
    assert loja["mensal_anterior"] == 50.00  # não 50 + 999 (julho inteiro)
    assert loja["mensal_anterior"] == resultado["cartoes"]["mensal"]["valor_comparado"]


def test_por_loja_variacao_e_com_iva_trocam_de_campo_tal_como_o_total():
    """com_iva tem de valer também nos campos novos por loja — nunca uma
    percentagem calculada com o campo errado."""
    lojas = [{"id": "l1", "nome": "Loja Alfa"}]
    documentos = [
        _doc("l1", _agora(2026, 8, 13, 10, 0), 123.45, 100.00),
        _doc("l1", _agora(2026, 8, 12, 9, 0), 100.00, 80.00),
    ]
    com_iva = calcula_dashboard(documentos, lojas, AGORA, com_iva=True)
    sem_iva = calcula_dashboard(documentos, lojas, AGORA, com_iva=False)
    loja_com_iva = com_iva["por_loja"][0]
    loja_sem_iva = sem_iva["por_loja"][0]
    assert loja_com_iva["hoje"] == 123.45
    assert loja_com_iva["hoje_anterior"] == 100.00
    assert loja_sem_iva["hoje"] == 100.00
    assert loja_sem_iva["hoje_anterior"] == 80.00


def test_por_loja_serie_mensal_tem_6_meses_isolados_por_loja():
    lojas = [{"id": "l1", "nome": "Loja Alfa"}, {"id": "l2", "nome": "Loja Beta"}]
    documentos = [
        _doc("l1", _agora(2026, 8, 5, 9, 0), 80.00, 70.00),
        _doc("l1", _agora(2026, 3, 5, 9, 0), 30.00, 25.00),
        _doc("l2", _agora(2026, 8, 5, 9, 0), 999.00, 900.00),
    ]
    resultado = calcula_dashboard(documentos, lojas, AGORA, com_iva=True)
    por_loja = {p["nome"]: p for p in resultado["por_loja"]}

    serie_alfa = por_loja["Loja Alfa"]["serie_mensal"]
    assert [m["mes"] for m in serie_alfa] == ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
    assert serie_alfa[0]["valor"] == 30.00
    assert serie_alfa[-1]["valor"] == 80.00  # bate com o "mensal" da própria loja
    assert serie_alfa[-1]["valor"] == por_loja["Loja Alfa"]["mensal"]

    # Isolamento: a Loja Beta não vê o valor da Loja Alfa nem vice-versa.
    assert por_loja["Loja Beta"]["serie_mensal"][-1]["valor"] == 999.00


# --- mais_vendidos / mais_rentaveis: sem linhas de artigos, sem dados ------
#
# fat_documentos, hoje, não guarda as LINHAS dos artigos vendidos (isso só
# chega com o POS próprio, fase seguinte) — sem linhas não há como saber o
# que vendeu mais ou deu mais margem. Devolve-se sempre lista vazia; o ecrã
# mostra "Sem informação disponível", tal como o Vendus mostra hoje ao dono
# (porque também não tem essa configuração feita).

def test_mais_vendidos_e_mais_rentaveis_sao_sempre_listas_vazias():
    documentos = [_doc("l1", _agora(2026, 8, 13, 9, 0), 25.00, 20.00)]
    resultado = calcula_dashboard(documentos, [{"id": "l1", "nome": "Loja Alfa"}], AGORA, com_iva=True)
    assert resultado["mais_vendidos"] == []
    assert resultado["mais_rentaveis"] == []


def test_mais_vendidos_e_mais_rentaveis_sem_documentos_tambem_vazios():
    resultado = calcula_dashboard([], [], AGORA, com_iva=True)
    assert resultado["mais_vendidos"] == []
    assert resultado["mais_rentaveis"] == []


# --- série diária e série mensal --------------------------------------------

def test_serie_diaria_tem_30_dias_terminando_hoje():
    documentos = [_doc("l1", _agora(2026, 8, 13, 9, 0), 25.00, 20.00)]
    resultado = calcula_dashboard(documentos, [], AGORA, com_iva=True)
    serie = resultado["serie_diaria"]
    assert len(serie) == 30
    assert serie[-1]["data"] == "2026-08-13"
    assert serie[-1]["valor"] == 25.00
    assert serie[0]["data"] == "2026-07-15"  # 30 dias antes, inclusive


def test_ultimos_6_meses_tem_6_entradas_e_o_ultimo_bate_com_o_cartao_mensal():
    documentos = [
        _doc("l1", _agora(2026, 8, 5, 9, 0), 80.00, 70.00),
        _doc("l1", _agora(2026, 3, 5, 9, 0), 30.00, 25.00),
    ]
    resultado = calcula_dashboard(documentos, [], AGORA, com_iva=True)
    meses = resultado["ultimos_6_meses"]
    assert [m["mes"] for m in meses] == ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
    assert meses[0]["valor"] == 30.00
    assert meses[-1]["mes"] == "2026-08"
    assert meses[-1]["valor"] == resultado["cartoes"]["mensal"]["valor"]


# --- endpoint (com duplos de base de dados) ---------------------------------

def _como_o_motor(documento):
    """A cópia que o Motor devolve — e que este duplo tem de devolver também.

    O `find`/`find_one` reais descodificam BSON de fresco a cada chamada: o
    resultado NUNCA está ligado ao que está no Mongo. Um duplo que devolvesse
    o próprio objecto guardado deixa um teste passar por ALIASING — o código
    de produção muta o que "leu" e o Mongo falso muda sozinho, sem nenhuma
    escrita. Já apanhou um caso real neste módulo (`cancelar_venda`, em
    faturacao/venda.py).

    Cópia FUNDA por regra da casa, ainda que os documentos DESTE ficheiro
    (`fat_documentos`, `fat_lojas`) sejam hoje todos planos: uma cópia rasa
    passaria a estar errada no dia em que um documento ganhasse `linhas` —
    exactamente o que o Plano 2 promete guardar aqui para os "mais vendidos"
    — e o aliasing voltava sem ninguém dar por ele.
    """
    return deepcopy(documento)


class CursorFalso:
    def __init__(self, dados):
        self._dados = dados

    async def to_list(self, limite):
        return [_como_o_motor(d) for d in self._dados]


class ColeccaoFalsa:
    def __init__(self, dados, registo, nome, existe_documento=None):
        self._dados = dados
        self.registo = registo
        self.nome = nome
        # I3: resultado canónico para find_one, INDEPENDENTE de `dados` (que
        # alimenta .find(), a consulta principal por janela) — por omissão
        # deriva de `dados` (o primeiro não-anulado), mas um teste pode
        # definir isto à parte para simular uma venda FORA da janela que
        # .find() devolve, exactamente o cenário que I3 corrige.
        self._existe_documento = existe_documento

    def find(self, filtro=None, projecao=None):
        self.registo.append((self.nome, filtro))
        return CursorFalso(self._dados)

    async def find_one(self, filtro=None, projecao=None):
        self.registo.append((self.nome, filtro))
        if self._existe_documento is not None:
            return {"_id": "fixture"} if self._existe_documento else None
        for doc in self._dados:
            if not doc.get("anulado"):
                return _como_o_motor(doc)
        return None


class DbFalsa:
    def __init__(self, documentos=None, lojas=None, registo=None, existe_documento=None):
        self.registo = registo if registo is not None else []
        self._coleccoes = {
            COLECOES["documentos"]: ColeccaoFalsa(
                documentos or [], self.registo, "documentos", existe_documento=existe_documento
            ),
            COLECOES["lojas"]: ColeccaoFalsa(lojas or [], self.registo, "lojas"),
        }

    def __getitem__(self, nome):
        return self._coleccoes[nome]


def test_endpoint_sem_vendas_devolve_zeros_e_ha_vendas_falso(monkeypatch):
    monkeypatch.setattr(dashboard_mod, "obter_db", lambda: DbFalsa())
    resposta = _corre(obter_dashboard(com_iva=True, _={}))
    assert resposta["ha_vendas"] is False
    assert resposta["cartoes"]["hoje"]["valor"] == 0
    assert len(resposta["serie_diaria"]) == 30
    assert len(resposta["ultimos_6_meses"]) == 6
    assert resposta["por_loja"] == []


# --- ha_vendas — pergunta à BD, não deduz da janela carregada (I3) ---------
#
# O defeito: `ha_vendas` deduzia-se de `documentos`, que só cobre desde o
# início do ano anterior (C1) — a consulta certa para os cartões/gráficos,
# mas errada para "alguma vez existiu uma venda?". A 1 de Janeiro, com um
# negócio que vendeu há anos e nada este ano nem o anterior, a janela
# carregada estaria vazia e a faixa "ainda não há vendas" apareceria por
# engano. Aqui `ha_vendas` vem de uma pergunta DIRECTA à BD (find_one),
# desligada da janela que .find() devolve — os testes a seguir provam essa
# independência dos dois lados.

def test_endpoint_ha_vendas_verdadeiro_mesmo_com_janela_de_documentos_vazia(monkeypatch):
    """O cenário do brief: a consulta principal (a janela) não devolve nada,
    mas alguma vez existiu uma venda (fora dessa janela) — ha_vendas tem de
    ser True."""
    db = DbFalsa(documentos=[], existe_documento=True)
    monkeypatch.setattr(dashboard_mod, "obter_db", lambda: db)
    resposta = _corre(obter_dashboard(com_iva=True, _={}))
    assert resposta["ha_vendas"] is True
    assert resposta["cartoes"]["hoje"]["valor"] == 0  # a janela em si continua vazia


def test_endpoint_ha_vendas_falso_apesar_de_documentos_na_janela_se_bd_disser_que_nao(monkeypatch):
    """O inverso, para provar a independência dos dois lados: mesmo com
    documentos na janela carregada, ha_vendas segue o que find_one disser —
    nunca volta a deduzir de `documentos`."""
    doc = {
        "loja_id": "l1",
        "emitido_em": datetime.now(timezone.utc).isoformat(),
        "total_bruto": 123.45,
        "total_liquido": 100.00,
        "tipo": "FS",
        "anulado": False,
    }
    db = DbFalsa(documentos=[doc], existe_documento=False)
    monkeypatch.setattr(dashboard_mod, "obter_db", lambda: db)
    resposta = _corre(obter_dashboard(com_iva=True, _={}))
    assert resposta["ha_vendas"] is False


def test_endpoint_ha_vendas_pergunta_por_documento_nao_anulado(monkeypatch):
    """A pergunta directa à BD tem de excluir documentos anulados — não
    'alguma vez existiu um documento', mas 'alguma vez existiu uma venda'."""
    registo = []
    db = DbFalsa(registo=registo)
    monkeypatch.setattr(dashboard_mod, "obter_db", lambda: db)
    _corre(obter_dashboard(com_iva=True, _={}))
    filtros_documentos = [f for (n, f) in registo if n == "documentos"]
    # duas consultas a "documentos": a principal (find, por janela) e a
    # directa (find_one, por existência) — a segunda filtra por "anulado".
    assert any(f.get("anulado") == {"$ne": True} for f in filtros_documentos)


def test_existe_venda_verdadeiro_quando_ha_documento_nao_anulado():
    registo = []
    db = DbFalsa(documentos=[{"anulado": False}], registo=registo)
    assert _corre(dashboard_mod._existe_venda(db)) is True


def test_existe_venda_falso_quando_so_ha_documentos_anulados():
    db = DbFalsa(documentos=[{"anulado": True}])
    assert _corre(dashboard_mod._existe_venda(db)) is False


def test_existe_venda_falso_quando_a_coleccao_esta_vazia():
    db = DbFalsa(documentos=[])
    assert _corre(dashboard_mod._existe_venda(db)) is False


def test_endpoint_consulta_documentos_desde_o_inicio_do_ano_anterior_e_lojas(monkeypatch):
    """A maior janela que o dashboard usa não é o ano corrente — é o cartão
    Anual, que compara com o ANO ANTERIOR equivalente (sempre a começar a 1
    de Janeiro do ano passado, ver janela_anterior_equivalente). Ir buscar só
    desde o início do ano CORRENTE (o defeito original, C1) deixava de fora
    todo o ano anterior, sem erro nem aviso: o cartão Anual ficava sempre
    'Sem período anterior comparável' e metade das barras/dias das séries
    ficavam a zero perto do início do ano."""
    registo = []
    monkeypatch.setattr(dashboard_mod, "obter_db", lambda: DbFalsa(registo=registo))
    _corre(obter_dashboard(com_iva=True, _={}))
    nomes_consultados = [c[0] for c in registo]
    assert "documentos" in nomes_consultados
    assert "lojas" in nomes_consultados
    filtro_documentos = next(f for (n, f) in registo if n == "documentos")
    assert "emitido_em" in filtro_documentos and "$gte" in filtro_documentos["emitido_em"]

    # O limite tem de bater com o início do ANO ANTERIOR equivalente (o
    # mesmo cálculo que o cartão Anual usa) — nunca o início do ano corrente.
    agora = datetime.now(timezone.utc)
    j_ano = janela_ano(agora)
    _, j_ano_anterior = janela_anterior_equivalente(j_ano.inicio, j_ano.fim, "ano")
    assert filtro_documentos["emitido_em"]["$gte"] == j_ano_anterior.inicio.isoformat()
    # E, por construção, isso é sempre um ano inteiro antes do início do ano
    # corrente — nunca o início do ano corrente (é essa a distinção que
    # importa: o defeito original passava aqui).
    assert filtro_documentos["emitido_em"]["$gte"] != j_ano.inicio.isoformat()


def test_endpoint_respeita_o_parametro_com_iva(monkeypatch):
    doc = {
        "loja_id": "l1",
        "emitido_em": datetime.now(timezone.utc).isoformat(),
        "total_bruto": 123.45,
        "total_liquido": 100.00,
        "tipo": "FS",
        "anulado": False,
    }
    monkeypatch.setattr(dashboard_mod, "obter_db", lambda: DbFalsa(documentos=[doc]))

    com_iva = _corre(obter_dashboard(com_iva=True, _={}))
    sem_iva = _corre(obter_dashboard(com_iva=False, _={}))
    assert com_iva["cartoes"]["hoje"]["valor"] == 123.45
    assert sem_iva["cartoes"]["hoje"]["valor"] == 100.00


def test_endpoint_exige_gestor_atual():
    """Guarda de regressão local — a guarda geral está em test_protecao_rotas.py,
    mas aqui confirmamos que é este endpoint concreto que a declara."""
    import inspect

    assinatura = inspect.signature(obter_dashboard)
    assert "gestor_atual" in repr(assinatura.parameters["_"].default)


# --- O CONTRATO com quem grava os documentos ---------------------------------
#
# Os testes de cima provam que `com_iva` troca de campo. Nenhum deles provava a
# única coisa que interessa ao dono: que o número que ele vê é o número da
# fatura que saiu. Este ecrã somava `total_bruto`/`total_liquido` e o único
# escritor de `fat_documentos` em todo o backend gravava só `total` — os dois
# campos do contrato não existiam em documento nenhum, `float(None or 0)` dá
# 0,00 € sem levantar nada, e o dono via HOJE 0,00 €, MÊS 0,00 €, ANO 0,00 €
# todos os dias, com as Faturas Simplificadas reais a entrarem na AT ao lado.
#
# Por isso o teste que faltava não é sobre campos: é sobre o DOCUMENTO REAL. O
# primeiro chama `fiscal.py::_gravar_documento` — o escritor a sério — e soma o
# que ele gravar. Se um dia alguém lá mudar o nome de um campo, é aqui que
# aparece, e não numa reunião em que o dono pergunta porque é que vendeu zero.


class ColeccaoParaGravar:
    """Colecção mínima para deixar correr o escritor real de documentos."""

    def __init__(self):
        self.documentos = []

    async def insert_one(self, doc):
        self.documentos.append(deepcopy(doc))

    async def find_one(self, filtro=None, projecao=None):
        return None

    async def update_one(self, filtro, atualizacao):
        return None


class DbParaGravar:
    def __init__(self):
        self._coleccoes = {}

    def __getitem__(self, nome):
        return self._coleccoes.setdefault(nome, ColeccaoParaGravar())


def _documento_como_o_pos_o_grava(total_bruto=8.99, total_liquido=7.96):
    """O documento tal como ele fica em `fat_documentos` depois de uma venda
    real — gravado pelo escritor de `fiscal.py`, não escrito à mão aqui."""
    from faturacao import fiscal as fiscal_mod

    db = DbParaGravar()
    bruto = {
        "id": 998877, "numero": "FS 2026/1234", "atcud": "JFT7X4K9-1234",
        "total": total_bruto, "total_bruto": total_bruto,
        "total_liquido": total_liquido, "modo": "normal", "talao_escpos": b"",
    }
    _corre(fiscal_mod._gravar_documento(
        db, "pos-loja-1-sessao-1-venda-1",
        {"id": "venda-1", "loja_id": "l1"}, bruto, reserva_id=None,
    ))
    return db[COLECOES["documentos"]].documentos[0]


def test_o_documento_que_o_pos_grava_conta_mesmo_no_dashboard():
    """O caminho feliz inteiro, do lado do dinheiro: um açaí de 8,99 € com
    IVA (7,96 € sem), a FS gravada pelo escritor real, e o cartão HOJE a
    mostrar 8,99 € — não 0,00 €."""
    doc = _documento_como_o_pos_o_grava()
    doc["emitido_em"] = _agora(2026, 8, 13, 10, 0).astimezone(timezone.utc).isoformat()

    com_iva = calcula_dashboard([doc], [], AGORA, com_iva=True)
    sem_iva = calcula_dashboard([doc], [], AGORA, com_iva=False)
    assert com_iva["cartoes"]["hoje"]["valor"] == 8.99
    assert sem_iva["cartoes"]["hoje"]["valor"] == 7.96


def test_documento_antigo_so_com_total_continua_a_contar_com_iva():
    """`total` e `total_bruto` são o MESMO número do Vendus (`amount_gross`)
    com dois nomes. Os documentos gravados antes de o contrato existir só têm
    o nome antigo e ficam em `fat_documentos` para sempre: um dashboard que
    os ignorasse mostrava a receita a começar do zero no dia do deploy — o
    mesmo defeito, com outra data."""
    doc = {
        "loja_id": "l1",
        "emitido_em": _agora(2026, 8, 13, 10, 0).astimezone(timezone.utc).isoformat(),
        "total": 8.99, "tipo": "FS",
    }
    resultado = calcula_dashboard([doc], [], AGORA, com_iva=True)
    assert resultado["cartoes"]["hoje"]["valor"] == 8.99


def test_documento_antigo_so_com_total_nao_finge_um_valor_sem_iva():
    """A metade que NÃO tem alternativa, e é uma decisão: nenhum campo antigo
    guarda o líquido, e derivá-lo do bruto obrigava a assumir uma taxa — as
    lojas vendem a 13 % (comida) e a 23 % (refrigerantes), muitas vezes na
    mesma venda. Zero é uma falta visível; um número inventado ninguém o
    consegue contestar. Mesma regra de precos.py e de _valor_monetario."""
    doc = {
        "loja_id": "l1",
        "emitido_em": _agora(2026, 8, 13, 10, 0).astimezone(timezone.utc).isoformat(),
        "total": 8.99, "tipo": "FS",
    }
    resultado = calcula_dashboard([doc], [], AGORA, com_iva=False)
    assert resultado["cartoes"]["hoje"]["valor"] == 0.0


def test_uma_fatura_de_zero_euros_nao_cai_para_o_campo_antigo():
    """`is None`, e não `or`: um `total_bruto` de 0,00 € é um valor legítimo
    e tem de ser respeitado. Com `or`, um documento assim ia buscar o `total`
    antigo e o dashboard somava um valor que o contrato diz que é zero."""
    doc = {
        "loja_id": "l1",
        "emitido_em": _agora(2026, 8, 13, 10, 0).astimezone(timezone.utc).isoformat(),
        "total_bruto": 0.0, "total": 999.00, "tipo": "FS",
    }
    resultado = calcula_dashboard([doc], [], AGORA, com_iva=True)
    assert resultado["cartoes"]["hoje"]["valor"] == 0.0


def test_ha_vendas_e_o_valor_dizem_a_mesma_coisa_sobre_um_documento_do_pos(monkeypatch):
    """Os dois lados do ecrã têm de concordar. O POS nunca grava `anulado`
    (por isso `_existe_venda` pergunta por `$ne: True`, que no Mongo casa com
    o campo ausente) — e enquanto o valor vinha a zero, o ecrã afirmava que
    havia vendas e mostrava 0,00 € em tudo: a pior das combinações, porque
    nem sequer aparecia a faixa a explicar porquê."""
    doc = _documento_como_o_pos_o_grava()
    assert "anulado" not in doc, "o POS passou a gravar `anulado` — rever _existe_venda"
    doc["emitido_em"] = datetime.now(timezone.utc).isoformat()

    monkeypatch.setattr(dashboard_mod, "obter_db", lambda: DbFalsa(documentos=[doc]))
    resposta = _corre(obter_dashboard(com_iva=True, _={}))
    assert resposta["ha_vendas"] is True
    assert resposta["cartoes"]["hoje"]["valor"] == 8.99


# --- «Ontem: 0,00 €» quando ontem foram 45,90 € ------------------------------
#
# O dono, a olhar para o painel: «teve faturação ontem em oeiras. mas está a
# dizer que foi 0,00 €.»
#
# A conta estava certa e a etiqueta é que mentia. O «Ontem» dos cartões não é
# ontem inteiro — é ontem desde a meia-noite até à MESMA HORA do relógio a que
# hoje ainda vai (`janela_ontem_equivalente`), e é assim de propósito: comparar
# cinco horas de hoje com vinte e quatro de ontem mostrava uma queda enorme
# todas as manhãs.
#
# Só que a loja do Oeiras abriu a caixa às 19:09 nesse dia, e o painel foi
# visto às 17:25. Ontem, até às 17:25, tinha vendido mesmo zero — e a etiqueta
# dizia «Ontem: 0,00 €», que se lê como «ontem a loja não fez nada».
#
# A frase que resolve isto JÁ EXISTIA (`descreve_comparacao`, que acrescenta
# «até às HH:MM» exactamente para este caso) — as linhas por loja é que a
# deitavam fora, ficando só com o número. O que falta é a hora de corte chegar
# ao ecrã.


def test_o_dashboard_diz_a_HORA_DE_CORTE_da_comparacao(monkeypatch):
    """Sem ela, o ecrã não tem como escrever «Ontem até às 17:25» — e um
    número parcial com etiqueta de dia inteiro é uma leitura errada que
    ninguém tem como desconfiar."""
    agora = datetime(2026, 8, 28, 16, 25, tzinfo=timezone.utc)  # 17:25 em Lisboa
    saida = calcula_dashboard([], [], agora)
    assert saida["hora_de_corte"] == "17:25", saida.get("hora_de_corte")


def test_uma_comparacao_SEM_corte_nao_inventa_uma_hora(monkeypatch):
    """À meia-noite em ponto os dois lados fecham o dia inteiro: não há hora
    nenhuma a assinalar, e escrever «até às 00:00» era ruído."""
    agora = datetime(2026, 8, 27, 23, 0, tzinfo=timezone.utc)  # 00:00 em Lisboa
    saida = calcula_dashboard([], [], agora)
    assert saida["hora_de_corte"] is None, saida.get("hora_de_corte")


def test_o_ONTEM_de_uma_loja_e_o_mesmo_que_o_do_total(monkeypatch):
    """O caso do dono, com os números dele: 45,90 € faturados às 19:09 de
    ontem não entram num «ontem até às 17:25» — nem para a loja nem para o
    total. O que este teste prende é que os dois concordam: uma loja a dizer
    45,90 € e o total a dizer 0,00 € era o pior dos dois mundos."""
    ontem_tarde = "2026-08-27T18:30:00+00:00"   # 19:30 em Lisboa
    docs = [{"id": "d1", "loja_id": "l-oeiras", "tipo": "FS", "total_bruto": 45.90,
             "emitido_em": ontem_tarde}]
    lojas = [{"id": "l-oeiras", "nome": "L'açaí Oeiras"}]
    agora = datetime(2026, 8, 28, 16, 25, tzinfo=timezone.utc)  # 17:25 em Lisboa
    saida = calcula_dashboard(docs, lojas, agora)
    da_loja = saida["por_loja"][0]
    assert da_loja["hoje_anterior"] == saida["cartoes"]["hoje"]["valor_comparado"]
    assert da_loja["hoje_anterior"] == 0.0
