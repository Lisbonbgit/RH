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
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from faturacao import dashboard as dashboard_mod
from faturacao.dashboard import calcula_dashboard, obter_dashboard
from faturacao.db import COLECOES

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

def test_sem_documentos_ha_vendas_e_falso_e_tudo_a_zero():
    resultado = calcula_dashboard([], [], AGORA, com_iva=True)
    assert resultado["ha_vendas"] is False
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
    com zeros — não desaparece do dashboard."""
    lojas = [{"id": "l1", "nome": "Loja Alfa"}]
    resultado = calcula_dashboard([], lojas, AGORA, com_iva=True)
    assert resultado["por_loja"] == [
        {"loja_id": "l1", "nome": "Loja Alfa", "hoje": 0, "mensal": 0, "serie_diaria": resultado["por_loja"][0]["serie_diaria"]}
    ]
    assert len(resultado["por_loja"][0]["serie_diaria"]) == 30


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
    assert resultado["ha_vendas"] is True


def test_so_documentos_anulados_ha_vendas_continua_falso():
    documentos = [_doc("l1", _agora(2026, 8, 13, 9, 0), 999.00, 900.00, anulado=True)]
    resultado = calcula_dashboard(documentos, [], AGORA, com_iva=True)
    assert resultado["ha_vendas"] is False


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

class CursorFalso:
    def __init__(self, dados):
        self._dados = dados

    async def to_list(self, limite):
        return list(self._dados)


class ColeccaoFalsa:
    def __init__(self, dados, registo, nome):
        self._dados = dados
        self.registo = registo
        self.nome = nome

    def find(self, filtro=None, projecao=None):
        self.registo.append((self.nome, filtro))
        return CursorFalso(self._dados)


class DbFalsa:
    def __init__(self, documentos=None, lojas=None, registo=None):
        self.registo = registo if registo is not None else []
        self._coleccoes = {
            COLECOES["documentos"]: ColeccaoFalsa(documentos or [], self.registo, "documentos"),
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


def test_endpoint_consulta_documentos_desde_o_inicio_do_ano_e_lojas(monkeypatch):
    registo = []
    monkeypatch.setattr(dashboard_mod, "obter_db", lambda: DbFalsa(registo=registo))
    _corre(obter_dashboard(com_iva=True, _={}))
    nomes_consultados = [c[0] for c in registo]
    assert "documentos" in nomes_consultados
    assert "lojas" in nomes_consultados
    filtro_documentos = next(f for (n, f) in registo if n == "documentos")
    assert "emitido_em" in filtro_documentos and "$gte" in filtro_documentos["emitido_em"]


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
