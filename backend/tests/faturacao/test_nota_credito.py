"""A NOTA DE CRÉDITO — o documento fiscal REAL que corrige uma Fatura
Simplificada já entregue à AT, e o dinheiro que ela devolve.

Três famílias, pela ordem do risco:

1. **o FISCAL** — a reserva atómica por INTENÇÃO (e não pelo documento de
   origem, que é o que deixa existir a segunda parcial), o duplo-toque, o
   desfecho incerto, e o que a API do Vendus exige numa NC;
2. **o TRAVÃO** — duas parciais não podem somar mais do que a fatura tinha, e
   quem recusa é o SERVIDOR;
3. **o DINHEIRO do turno** — a devolução em dinheiro sai da gaveta, a
   devolução no Glovo não lhe toca, e o Z conta as duas no sítio delas.

Os valores expõem o cêntimo de propósito (0,29 · 1,15 · 10,20): a 8,50 e a
0,30 quase toda a aritmética de IVA parece certa.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from faturacao import nota_credito as nc_mod
from faturacao import caixa as caixa_mod
from faturacao import db as db_mod
from faturacao.caixa_math import por_tipo_de_pagamento, soma_vendas_dinheiro
from faturacao.db import COLECOES
from faturacao.mapa_imposto import mapa_de_imposto, mapa_da_nota, totais_do_mapa
from faturacao.nota_credito import (
    NotaDeCreditoInvalida,
    _centimos,
    escolher_linhas,
    emitir_nota_credito,
    ext_ref_da_intencao,
    ja_creditado_por_linha,
    itens_vendus_da_nota,
    linhas_creditaveis,
    pre_visualizar_nota_credito,
    preparar_nota_credito,
    PedidoNotaCredito,
    PedidoPreVisualizar,
    total_das_linhas,
)
from faturacao.vendus.cliente import VendusErro, VendusIndisponivel
from faturacao.vendus.emissao import NotaDeCreditoSemMotivo, RegisterIdInvalido

from tests.faturacao.test_fiscal import (
    ColeccaoFalsa,
    CursorFalso,
    DbFalsa,
    _configura_vendus_env,
    _corre,
    _operador,
    _tipo_pagamento,
    _unicos_de,
    _venda,
)


# --- O cenário: uma fatura com três linhas e dois IVAs -----------------------
#
# Açaí 10,20 × 2 (INT 13 %) · Água 0,29 × 1 (INT) · Coca-Cola 1,15 × 3 (NOR
# 23 %). Total 24,14 €. Nenhum destes valores é redondo a nenhuma taxa —
# é isso que os torna úteis.

def _linha_acai(**over):
    li = {
        "id": "linha-acai", "produto_id": "prod-acai", "produto_nome": "Açaí Regular",
        "produto_preco": 10.20, "produto_tax_id": "INT", "quantidade": 2, "opcoes": [],
        "preco_override": None, "tax_override": None, "desconto_pct": None,
        "desconto_eur": None, "produto_vendus_ref": 9001,
    }
    li.update(over)
    return li


def _linha_agua(**over):
    li = {
        "id": "linha-agua", "produto_id": "prod-agua", "produto_nome": "Água 33cl",
        "produto_preco": 0.29, "produto_tax_id": "INT", "quantidade": 1, "opcoes": [],
        "preco_override": None, "tax_override": None, "desconto_pct": None,
        "desconto_eur": None, "produto_vendus_ref": 9002,
    }
    li.update(over)
    return li


def _linha_cola(**over):
    li = {
        "id": "linha-cola", "produto_id": "prod-cola", "produto_nome": "Coca-Cola",
        "produto_preco": 1.15, "produto_tax_id": "NOR", "quantidade": 3, "opcoes": [],
        "preco_override": None, "tax_override": None, "desconto_pct": None,
        "desconto_eur": None, "produto_vendus_ref": 9003,
    }
    li.update(over)
    return li


def _venda_faturada(**over):
    v = _venda(
        estado="emitida",
        linhas=[_linha_acai(), _linha_agua(), _linha_cola()],
        cliente_nif=None,
    )
    v.update(over)
    return v


def _documento_fs(**over):
    d = {
        "id": "doc-1", "venda_id": "venda-1", "loja_id": "loja-1",
        "tipo": "FS", "numero": "FS 05P2026/1824", "atcud": "ATCUD-FS-1824",
        "total": 24.14, "modo": "tests",
        "emitido_em": "2026-08-22T10:00:00+00:00",
        "ext_ref": "pos-loja-1-sessao-1-venda-1",
        "vendus_document_id": 1824,
    }
    d.update(over)
    return d


def _bruto_nc(**over):
    b = {
        "id": 7001, "numero": "NC 05P2026/12", "atcud": "ATCUD-NC-12",
        "total": 10.20, "talao_escpos": b"talao-nc", "modo": "tests",
    }
    b.update(over)
    return b


def _sessao(**over):
    s = {"id": "sessao-1", "loja_id": "loja-1", "caixa_id": "caixa-1", "estado": "aberta"}
    s.update(over)
    return s


def _db_nc(vendas=None, documentos=None, notas=None, sessoes=None, tipos=None, caixas=None):
    return DbFalsa({
        COLECOES["vendas"]: ColeccaoFalsa(
            [_venda_faturada()] if vendas is None else vendas),
        COLECOES["documentos"]: ColeccaoFalsa(
            [_documento_fs()] if documentos is None else documentos,
            indices_unicos=_unicos_de("fat_documentos")),
        COLECOES["notas_credito"]: ColeccaoFalsa(
            notas, indices_unicos=_unicos_de("fat_notas_credito")),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa(
            [_sessao()] if sessoes is None else sessoes),
        COLECOES["caixas"]: ColeccaoFalsa(
            [{"id": "caixa-1", "loja_id": "loja-1", "nome": "Caixa 1"}]
            if caixas is None else caixas),
        COLECOES["tipos_pagamento"]: ColeccaoFalsa(
            [_tipo_pagamento(), _tipo_pagamento(
                id="tipo-glovo", nome="Glovo", tipo_fiscal="OU",
                vendus_payment_method_id="316430999")]
            if tipos is None else tipos),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(
            None, indices_unicos=_unicos_de("fat_refs_fiscais")),
        COLECOES["movimentos_caixa"]: ColeccaoFalsa([]),
    })


class VendusNCFalso:
    """Duplo do cliente de emissão para a NOTA DE CRÉDITO. Guarda o que lhe
    entregaram — é sobre isso que os testes do `reference_document` e do
    motivo afirmam."""

    instancias = []
    emitidos = 0

    def __init__(self, chave):
        self.chave = chave
        self.chamadas_criar = []
        self.chamadas_procurar = []
        VendusNCFalso.emitidos += 1
        self.resposta_criar = _bruto_nc(
            id=7000 + VendusNCFalso.emitidos,
            numero="NC 05P2026/%d" % (11 + VendusNCFalso.emitidos),
            atcud="ATCUD-NC-%d" % (11 + VendusNCFalso.emitidos))
        self.erro_criar = None
        self.resposta_procurar = None
        self.erro_procurar = None
        VendusNCFalso.instancias.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def criar_nota_credito(self, linhas, pagamentos, external_reference,
                           register_id, motivo, modo=None):
        self.chamadas_criar.append({
            "linhas": linhas, "pagamentos": pagamentos,
            "external_reference": external_reference,
            "register_id": register_id, "motivo": motivo,
        })
        if self.erro_criar is not None:
            raise self.erro_criar
        return self.resposta_criar

    def procurar_por_referencia_externa(self, external_reference, register_id):
        self.chamadas_procurar.append(external_reference)
        if self.erro_procurar is not None:
            raise self.erro_procurar
        return self.resposta_procurar


@pytest.fixture(autouse=True)
def _ambiente(monkeypatch):
    """Cada teste começa com o índice único CONFIRMADO e o duplo do Vendus
    limpo. O índice é o pré-requisito da rota (503 sem ele, e há um teste
    dedicado a essa recusa) — deixá-lo por confirmar aqui punha todos os
    outros a medir a mensagem de erro em vez do que dizem medir."""
    db_mod.marcar_indice_notas_credito(True)
    _configura_vendus_env(monkeypatch)
    VendusNCFalso.instancias.clear()
    VendusNCFalso.emitidos = 0
    monkeypatch.setattr(nc_mod, "ClienteEmissaoVendus", VendusNCFalso)
    yield
    db_mod.marcar_indice_notas_credito(None)


def _pedido(**over):
    p = {
        "intencao_id": "11111111-1111-4111-8111-111111111111",
        "caixa_id": "caixa-1",
        "motivo": "Cliente devolveu o açaí — veio com a fruta trocada.",
        "tipo_pagamento_id": "tipo-dinheiro",
        "linhas": [{"indice": 1, "quantidade": 1}],
    }
    p.update(over)
    return PedidoNotaCredito(**p)


def _intencao_presa(**over):
    """Uma intenção que RESERVOU e ficou por lá — o estado em que a rota morre
    entre o `insert_one` e o `$set` final (um reinício, um deploy a meio, o 409
    da corrida do crédito). **Nada foi enviado à AT**, e é isso que torna a
    frase «já foi creditado» uma mentira."""
    n = {
        "id": "11111111-1111-4111-8111-111111111111",
        "loja_id": "loja-1", "caixa_id": "caixa-1", "sessao_id": "sessao-1",
        "documento_id": "doc-1", "venda_id": "venda-1",
        "numero_origem": "FS 05P2026/1824",
        "motivo": "Cliente devolveu o açaí.",
        "linhas": [{"indice": 1, "titulo": "Açaí Regular", "tax_id": "INT",
                    "quantidade": 2, "preco_unitario": 10.20, "total": 20.40}],
        "total": 20.40,
        "devolucao": {"tipo_pagamento_id": "tipo-dinheiro", "nome": "Dinheiro",
                      "tipo_fiscal": "NU", "valor": 20.40},
        "ext_ref": ("pos-loja-1-sessao-1-nc-"
                    "11111111-1111-4111-8111-111111111111"),
        "estado": "reservada",
        "criada_em": "2026-08-22T10:00:00+00:00",
    }
    n.update(over)
    return n


def _emitir(db, monkeypatch, pedido=None, documento_id="doc-1", operador=None):
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    return _corre(emitir_nota_credito(
        documento_id, pedido or _pedido(), operador=operador or _operador()))


# --- 1. O dinheiro das linhas, e o mapa de imposto ---------------------------


def test_o_total_das_linhas_soma_em_centimos_e_nao_em_virgula_flutuante():
    """0,29 + 1,15 + 10,20. Em `float` puro isto dá 11,639999999999999 e um
    `round` a dois já o esconde — mas a soma tem de nascer inteira, que é a
    regra 1 da casa."""
    linhas = [{"total": 0.29}, {"total": 1.15}, {"total": 10.20}]
    assert total_das_linhas(linhas) == 11.64


def test_creditar_a_fatura_inteira_cancela_a_exactamente_ao_centimo():
    """O guarda do SINAL em `_base_em_centimos`. A base de +10,20 a 13 % é
    9,03; a divisão inteira do Python sobre −1020 arredondaria para
    −infinito e dava −9,04 — um cêntimo a mais na devolução do que na
    fatura, e um turno todo creditado que não fechava a zero."""
    venda = _venda_faturada()
    creditaveis = linhas_creditaveis(venda, [])
    tudo = escolher_linhas(creditaveis, [
        {"indice": linha["indice"], "quantidade": linha["disponivel"]}
        for linha in creditaveis
    ])
    nota = {"linhas": tudo, "estado": "emitida"}

    so_a_fatura = totais_do_mapa(mapa_de_imposto([venda]))
    com_a_nota = totais_do_mapa(mapa_de_imposto([venda], [nota]))

    assert so_a_fatura["total"] == 24.14
    assert com_a_nota == {"base": 0.0, "iva": 0.0, "total": 0.0}


def test_a_base_mais_o_iva_da_nota_dao_exactamente_o_total_dela():
    """`base + iva == total` por construção, também com o sinal ao contrário
    — é a propriedade que `mapa_imposto.py` garante e que a NC não pode
    quebrar."""
    creditaveis = linhas_creditaveis(_venda_faturada(), [])
    escolhidas = escolher_linhas(creditaveis, [
        {"indice": 1, "quantidade": 1},   # açaí 10,20 a 13 %
        {"indice": 2, "quantidade": 1},   # água 0,29 a 13 %
        {"indice": 3, "quantidade": 2},   # 2 colas 2,30 a 23 %
    ])
    mapa = mapa_da_nota({"linhas": escolhidas})
    for linha in mapa:
        assert round(linha["base"] + linha["iva"], 2) == linha["total"]
    totais = totais_do_mapa(mapa)
    assert round(totais["base"] + totais["iva"], 2) == totais["total"]
    assert totais["total"] == 12.79  # 10,20 + 0,29 + 2,30


def test_o_mapa_da_nota_mostra_se_em_positivo_e_desconta_no_turno():
    """O ecrã lê a nota em POSITIVO (é como uma NC se lê no papel) e o turno
    lê-a em NEGATIVO. Os dois saem da mesma decomposição."""
    creditaveis = linhas_creditaveis(_venda_faturada(), [])
    escolhidas = escolher_linhas(creditaveis, [{"indice": 1, "quantidade": 1}])
    nota = {"linhas": escolhidas, "estado": "emitida"}

    assert totais_do_mapa(mapa_da_nota(nota))["total"] == 10.20

    turno = totais_do_mapa(mapa_de_imposto([_venda_faturada()], [nota]))
    assert turno["total"] == 13.94


def test_uma_nota_por_apurar_nao_desconta_o_mapa_de_imposto_do_turno():
    """A `incerta` trava o crédito (não se credita por cima do que talvez já
    tenha saído) mas NÃO desconta o Z: ninguém sabe se o documento existe."""
    creditaveis = linhas_creditaveis(_venda_faturada(), [])
    escolhidas = escolher_linhas(creditaveis, [{"indice": 1, "quantidade": 1}])
    incerta = {"linhas": escolhidas, "estado": "incerta"}
    assert totais_do_mapa(
        mapa_de_imposto([_venda_faturada()], [incerta]))["total"] == 24.14


def test_a_nota_conta_como_um_documento_fiscal_do_turno():
    """Um documento a mais na coluna que a contabilista reconcilia."""
    creditaveis = linhas_creditaveis(_venda_faturada(), [])
    nota = {"linhas": escolher_linhas(
        creditaveis, [{"indice": 1, "quantidade": 1}]), "estado": "emitida"}
    mapa = mapa_de_imposto([_venda_faturada()], [nota])
    linha_int = next(li for li in mapa if li["tax_id"] == "INT")
    assert linha_int["documentos"] == 2  # a fatura e a nota


def test_creditar_uma_fatura_com_desconto_nao_devolve_o_bruto():
    """A fatura levou 10 % de desconto global: o cliente pagou 9,18 pelo
    açaí, e é 9,18 que se lhe devolve. Sem o `desconto_percentagem` a viajar
    com a linha, a nota de crédito devolvia 10,20 — 1,02 € de prejuízo por
    devolução."""
    venda = _venda_faturada(desconto_global_pct=10)
    creditaveis = linhas_creditaveis(venda, [])
    escolhidas = escolher_linhas(creditaveis, [{"indice": 1, "quantidade": 1}])
    assert escolhidas[0]["total"] == 9.18
    assert total_das_linhas(escolhidas) == 9.18


# --- 2. O TRAVÃO: duas parciais não somam mais do que a fatura tinha ---------


def test_o_ecra_recebe_o_maximo_creditavel_de_cada_linha():
    creditaveis = linhas_creditaveis(_venda_faturada(), [])
    assert [(li["indice"], li["quantidade"], li["disponivel"]) for li in creditaveis] == [
        (1, 2, 2.0), (2, 1, 1.0), (3, 3, 3.0),
    ]


def test_creditar_mais_do_que_a_fatura_tem_e_recusado_com_o_que_ainda_da():
    creditaveis = linhas_creditaveis(_venda_faturada(), [])
    with pytest.raises(NotaDeCreditoInvalida) as erro:
        escolher_linhas(creditaveis, [{"indice": 1, "quantidade": 3}])
    assert "Açaí Regular" in str(erro.value)
    assert "2 de 2" in str(erro.value)


def test_duas_parciais_somam_ate_ao_limite_e_a_terceira_e_recusada():
    """O caso do dono: o cliente devolve hoje um açaí e amanhã o outro. As
    duas passam; a terceira não tem de onde sair."""
    venda = _venda_faturada()
    primeira = {"estado": "emitida", "linhas": [{"indice": 1, "quantidade": 1}]}
    disponivel = linhas_creditaveis(venda, [primeira])
    assert disponivel[0]["creditado"] == 1.0
    assert disponivel[0]["disponivel"] == 1.0

    segunda = {"estado": "emitida", "linhas": [{"indice": 1, "quantidade": 1}]}
    esgotado = linhas_creditaveis(venda, [primeira, segunda])
    assert esgotado[0]["disponivel"] == 0.0

    with pytest.raises(NotaDeCreditoInvalida) as erro:
        escolher_linhas(esgotado, [{"indice": 1, "quantidade": 1}])
    assert "já foi creditado" in str(erro.value)


def test_o_travao_conta_as_notas_por_apurar_e_as_que_estao_a_meio():
    """Uma nota `incerta` pode ter saído mesmo, e uma `reservada` está a
    falar com o Vendus AGORA. Creditar por cima de qualquer uma delas era
    arriscar duas notas reais sobre a mesma linha."""
    linhas = [{"indice": 1, "quantidade": 2}]
    assert ja_creditado_por_linha([{"estado": "emitida", "linhas": linhas}]) == {1: 200000}
    assert ja_creditado_por_linha([{"estado": "incerta", "linhas": linhas}]) == {1: 200000}
    assert ja_creditado_por_linha([{"estado": "reservada", "linhas": linhas}]) == {1: 200000}


def test_uma_nota_libertada_por_erro_provado_nao_trava_nada():
    """Um estado que não é nenhum dos três não conta — e é isso que deixa a
    operadora repetir depois de um erro que provou que nada saiu."""
    assert ja_creditado_por_linha(
        [{"estado": "cancelada", "linhas": [{"indice": 1, "quantidade": 2}]}]) == {}


def test_as_quantidades_comparam_se_em_inteiros_e_nao_em_virgula_flutuante():
    """**O resto EXACTO de uma linha tem de caber nela.**

    Um açaí dividido por uma conta repartida deixa partes com 5 casas
    (`lib/pos.js::CASAS_DA_QUANTIDADE_POS`). Creditou-se 0,55 de uma unidade;
    restam 0,45, e é isso que o servidor manda ao ecrã. Em vírgula flutuante
    `0.45 × 100000` dá 45000,000000000007 e o que resta dá 45000,0 — o `>` cru
    RECUSA a operadora com «só pode creditar 0,45» numa linha que tem
    exactamente 0,45 por creditar. Em inteiros os dois são 45000."""
    venda = _venda_faturada(linhas=[_linha_acai(quantidade=1)])
    anteriores = [{"estado": "emitida", "linhas": [{"indice": 1, "quantidade": 0.55}]}]
    creditaveis = linhas_creditaveis(venda, anteriores)
    assert creditaveis[0]["disponivel"] == 0.45
    escolhidas = escolher_linhas(creditaveis, [{"indice": 1, "quantidade": 0.45}])
    assert escolhidas[0]["quantidade"] == 0.45


def test_uma_linha_que_a_fatura_nao_tem_e_recusada():
    creditaveis = linhas_creditaveis(_venda_faturada(), [])
    with pytest.raises(NotaDeCreditoInvalida) as erro:
        escolher_linhas(creditaveis, [{"indice": 9, "quantidade": 1}])
    assert "nenhum artigo nº 9" in str(erro.value)


def test_a_mesma_linha_duas_vezes_no_mesmo_pedido_e_recusada():
    """Sem isto, `{1: 1} + {1: 1}` contra uma linha de 1 unidade passava as
    duas — cada uma cabia sozinha no disponível."""
    creditaveis = linhas_creditaveis(_venda_faturada(linhas=[_linha_agua()]), [])
    with pytest.raises(NotaDeCreditoInvalida) as erro:
        escolher_linhas(creditaveis, [
            {"indice": 1, "quantidade": 1}, {"indice": 1, "quantidade": 1}])
    assert "duas vezes" in str(erro.value)


def test_nenhuma_linha_escolhida_e_recusado():
    with pytest.raises(NotaDeCreditoInvalida):
        escolher_linhas(linhas_creditaveis(_venda_faturada(), []), [])


def test_o_travao_e_do_servidor_e_a_rota_recusa_com_422(monkeypatch):
    """O ecrã mostra o máximo, mas quem RECUSA é a rota — um browser com um
    defeito (ou alguém a falar directamente com a API) não credita a mais."""
    db = _db_nc()
    with pytest.raises(HTTPException) as erro:
        _emitir(db, monkeypatch, _pedido(linhas=[{"indice": 1, "quantidade": 5}]))
    assert erro.value.status_code == 422
    assert "2 de 2" in erro.value.detail
    assert VendusNCFalso.instancias == []  # nunca se falou com o Vendus


def test_a_segunda_parcial_da_mesma_fatura_e_recusada_pela_rota_quando_esgota(monkeypatch):
    """Ponta a ponta e com o estado GRAVADO pela primeira: a segunda nota vê
    o que a primeira já creditou."""
    db = _db_nc()
    _emitir(db, monkeypatch, _pedido(linhas=[{"indice": 2, "quantidade": 1}]))
    with pytest.raises(HTTPException) as erro:
        _emitir(db, monkeypatch, _pedido(
            intencao_id="22222222-2222-4222-8222-222222222222",
            linhas=[{"indice": 2, "quantidade": 1}]))
    assert erro.value.status_code == 422
    assert "Água 33cl" in erro.value.detail


# --- 3. A IDEMPOTÊNCIA: a referência é da INTENÇÃO --------------------------


def test_a_referencia_externa_deriva_da_intencao_e_nao_do_documento_de_origem():
    """É esta escolha que deixa existir a segunda parcial. Uma referência
    `nc-{documento}` tornava-a impossível de emitir para sempre."""
    a = ext_ref_da_intencao("loja-1", "sessao-1", "intencao-a")
    b = ext_ref_da_intencao("loja-1", "sessao-1", "intencao-b")
    assert a == "pos-loja-1-sessao-1-nc-intencao-a"
    assert a != b


def test_a_referencia_mantem_o_prefixo_que_a_reconciliacao_do_fecho_procura():
    """`fiscal._reconciliar_vendas_dinheiro` separa os NOSSOS documentos dos
    da app L'Açaí na mesma caixa API por este prefixo. Sem ele, a devolução
    em dinheiro era descontada do nosso lado e não do lado do Vendus, e o
    fecho acusava uma diferença todas as noites em que houvesse devolução."""
    assert ext_ref_da_intencao("loja-7", "sessao-9", "x").startswith("pos-loja-7-sessao-9-")


def test_o_duplo_toque_no_botao_emite_uma_so_nota_de_credito(monkeypatch):
    """O mesmo `intencao_id` duas vezes: o índice único de
    `fat_notas_credito.id` apanha a segunda ANTES de ela falar com o Vendus.
    Uma NC a dobrar é um documento fiscal a mais entregue à AT.

    **A LINHA INTEIRA, e é isso que faz este guarda valer.** Com o `_pedido()`
    por omissão (1 de 2) este teste esteve verde pela razão errada durante uma
    ronda inteira: sobrava 1 por creditar, a segunda chamada passava o travão
    e só então batia no índice único. Com a linha creditada por INTEIRO — que
    é o que o ecrã propõe ao marcar o artigo — o travão vê `disponivel: 0` e,
    se a pergunta «esta intenção já foi resolvida?» não vier primeiro, a
    operadora leva 422 «já foi creditado» por uma nota que ACABOU DE SAIR."""
    db = _db_nc()
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    pedido = _pedido(linhas=[{"indice": 1, "quantidade": 2}])

    primeira = _corre(emitir_nota_credito("doc-1", pedido, operador=_operador()))
    segunda = _corre(emitir_nota_credito("doc-1", pedido, operador=_operador()))

    assert len(VendusNCFalso.instancias) == 1
    assert len(VendusNCFalso.instancias[0].chamadas_criar) == 1
    assert primeira["numero"] == segunda["numero"] == "NC 05P2026/12"
    assert db[COLECOES["notas_credito"]].chamadas_insert == 1


def test_o_toque_repetido_devolve_o_NUMERO_e_o_ATCUD_da_nota_que_saiu(monkeypatch):
    """**O SÉTIMO defeito, e é o que faz a operadora não entregar o dinheiro.**

    Ao balcão: a rede pisca, ela carrega outra vez, a nota JÁ FOI para a AT.
    O que ela tem de ler é o documento — número, ATCUD e a instrução de
    entregar o dinheiro —, e não um erro vermelho.

    Medido antes da correcção, pelas rotas reais e com a linha creditada por
    inteiro: 1.ª chamada NC 05P2026/12 emitida; 2.ª, MESMA intenção, 422
    «Açaí Regular já foi creditado (2) — desta fatura ainda só se pode
    creditar 0 de 2»."""
    db = _db_nc()
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    pedido = _pedido(linhas=[{"indice": 1, "quantidade": 2}])

    primeira = _corre(emitir_nota_credito("doc-1", pedido, operador=_operador()))
    segunda = _corre(emitir_nota_credito("doc-1", pedido, operador=_operador()))

    assert segunda["numero"] == primeira["numero"] == "NC 05P2026/12"
    assert segunda["atcud"] == primeira["atcud"] == "ATCUD-NC-12"
    assert segunda["total"] == primeira["total"]
    assert segunda["devolucao"]["valor"] == 20.40


def _ha_segundos(segundos):
    """Um `criada_em` a uma distância CONHECIDA do relógio de agora.

    Uma data fixa escrita à mão não serve para medir esta janela: ela afasta-se
    do presente todos os dias, e o guarda deixa de saber distinguir 5 minutos
    de um dia inteiro (foi assim que uma mutação que punha o relógio em 24 h
    sobreviveu)."""
    return (datetime.now(timezone.utc) - timedelta(seconds=segundos)).isoformat()


def test_a_intencao_PRESA_HA_SEGUNDOS_responde_espere_e_nao_ja_foi_creditado(monkeypatch):
    """O pior ramo: a intenção ficou `reservada` e **nada** foi enviado à AT.

    Antes: o mesmo toque levava 422 «já foi creditado (2)» — uma frase que
    mente, sobre uma nota que não creditou nada, e que deixava a fatura
    increditável por qualquer caminho com a caixa trancada.

    **Reservou AGORA**, e é isso que faz «espere alguns segundos» ser verdade:
    a emissão pode estar a falar com o Vendus neste instante. É o CONTROLO do
    teste a seguir."""
    db = _db_nc(notas=[_intencao_presa(criada_em=_ha_segundos(2))])
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as erro:
        _corre(emitir_nota_credito(
            "doc-1", _pedido(linhas=[{"indice": 1, "quantidade": 2}]),
            operador=_operador()))
    assert erro.value.status_code == 409
    assert "já está a ser emitida" in erro.value.detail
    assert "já foi creditado" not in erro.value.detail
    assert VendusNCFalso.instancias == []


def test_o_MESMO_BOTAO_numa_nota_presa_HA_HORAS_nomeia_o_gestor(monkeypatch):
    """**Quem insiste no mesmo botão nunca sabia que é o gestor que destrava.**

    Ao balcão, insistir no mesmo botão é o que se faz quando a rede pisca —
    logo é precisamente quem mais precisa da saída que nunca a lia. A resposta
    a este toque não olhava para a idade da intenção: uma `reservada` presa há
    HORAS respondia «Espere alguns segundos: se ela sair, aparece aqui
    sozinha» **para sempre**, e nunca nomeava o gestor. Uma janela NOVA sobre
    a mesma nota já dizia onde ir.

    O relógio é o mesmo de `_nota_presa` (`_SEGUNDOS_DE_EMISSAO_NORMAL`), e é
    por isso que a frase manda a um sítio que já a deixa entrar: passada esta
    janela é também a partir dela que as rotas do gestor lhe mexem."""
    db = _db_nc(notas=[_intencao_presa(criada_em=_ha_segundos(2 * 3600))])
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as erro:
        _corre(emitir_nota_credito(
            "doc-1", _pedido(linhas=[{"indice": 1, "quantidade": 2}]),
            operador=_operador()))
    assert erro.value.status_code == 409
    assert "Reservas Fiscais Presas" in erro.value.detail
    assert "Notas de Crédito Presas" in erro.value.detail
    assert "NÃO devolva o dinheiro" in erro.value.detail
    # E não a frase que nunca mais vai ser verdade.
    assert "Espere alguns segundos" not in erro.value.detail
    assert "já foi creditado" not in erro.value.detail
    assert VendusNCFalso.instancias == []


@pytest.mark.parametrize("desvio,espera_o_gestor", [(-1, False), (+1, True)])
def test_a_JANELA_de_uma_emissao_normal_e_a_fronteira_das_duas_frases(
        monkeypatch, desvio, espera_o_gestor):
    """A fronteira medida no próprio relógio, e não numa data escrita à mão:
    um segundo antes de `_SEGUNDOS_DE_EMISSAO_NORMAL` a emissão ainda pode
    estar a falar com o Vendus; um segundo depois já não, e a saída é o
    gestor. É o mesmo relógio que as rotas dele usam para aceitar mexer-lhe."""
    idade = nc_mod._SEGUNDOS_DE_EMISSAO_NORMAL + desvio
    db = _db_nc(notas=[_intencao_presa(criada_em=_ha_segundos(idade))])
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as erro:
        _corre(emitir_nota_credito(
            "doc-1", _pedido(linhas=[{"indice": 1, "quantidade": 2}]),
            operador=_operador()))
    assert erro.value.status_code == 409
    assert ("Notas de Crédito Presas" in erro.value.detail) is espera_o_gestor
    assert ("Espere alguns segundos" in erro.value.detail) is not espera_o_gestor


def test_a_saida_que_o_mesmo_botao_nomeia_e_a_MESMA_da_janela_nova(monkeypatch):
    """As duas metades da mesma mentira mandam agora ao mesmo sítio — era
    exactamente a divergência que fazia o segundo toque ser um beco."""
    db = _db_nc(notas=[_intencao_presa(criada_em=_ha_segundos(2 * 3600))])
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as mesmo_botao:
        _corre(emitir_nota_credito(
            "doc-1", _pedido(linhas=[{"indice": 1, "quantidade": 2}]),
            operador=_operador()))
    with pytest.raises(HTTPException) as janela_nova:
        _corre(emitir_nota_credito(
            "doc-1", _pedido(intencao_id="99999999-9999-4999-8999-999999999999",
                             linhas=[{"indice": 1, "quantidade": 2}]),
            operador=_operador()))
    for erro in (mesmo_botao, janela_nova):
        assert "Faturação → Reservas Fiscais Presas" in erro.value.detail


def test_uma_JANELA_NOVA_travada_por_uma_nota_PRESA_ouve_a_verdade(monkeypatch):
    """A outra metade da mesma mentira: outra intenção, outra janela. O travão
    recusa — e bem, porque a presa pode ter saído —, mas a frase não pode
    dizer «já foi creditado» quando ninguém sabe se foi. Diz o que é, e diz a
    quem chamar."""
    db = _db_nc(notas=[_intencao_presa()])
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as erro:
        _corre(emitir_nota_credito(
            "doc-1", _pedido(intencao_id="99999999-9999-4999-8999-999999999999",
                             linhas=[{"indice": 1, "quantidade": 2}]),
            operador=_operador()))
    assert erro.value.status_code == 422
    assert "POR APURAR" in erro.value.detail
    assert "Notas de Crédito Presas" in erro.value.detail
    assert "já foi creditado" not in erro.value.detail


def test_uma_linha_creditada_por_uma_nota_EMITIDA_continua_a_dizer_ja_creditado(monkeypatch):
    """O CONTROLO do de cima: uma frase de «por apurar» que estivesse sempre
    lá não distinguia nada. Aqui a nota anterior saiu mesmo, e a recusa é a
    normal."""
    db = _db_nc()
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    _corre(emitir_nota_credito(
        "doc-1", _pedido(linhas=[{"indice": 1, "quantidade": 2}]),
        operador=_operador()))

    with pytest.raises(HTTPException) as erro:
        _corre(emitir_nota_credito(
            "doc-1", _pedido(intencao_id="99999999-9999-4999-8999-999999999999",
                             linhas=[{"indice": 1, "quantidade": 2}]),
            operador=_operador()))
    assert erro.value.status_code == 422
    assert "já foi creditado" in erro.value.detail
    assert "POR APURAR" not in erro.value.detail


def test_uma_intencao_INCERTA_repetida_manda_chamar_o_gestor(monkeypatch):
    """Uma intenção que ficou por apurar não é «espere alguns segundos»: não
    há nada a esperar dela, e a operadora NÃO pode devolver o dinheiro. A
    resposta é a mesma que ela leu na tentativa que a deixou assim."""
    db = _db_nc(notas=[_intencao_presa(estado="incerta")])
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as erro:
        _corre(emitir_nota_credito(
            "doc-1", _pedido(linhas=[{"indice": 1, "quantidade": 2}]),
            operador=_operador()))
    # 503 e a MESMA frase de `_MSG_DESFECHO_INCERTO`: é o que ela leu na
    # tentativa que deixou a intenção assim, e é a única resposta certa.
    assert erro.value.status_code == 503
    assert "NÃO devolva o dinheiro" in erro.value.detail


def test_dois_toques_CONCORRENTES_emitem_uma_so_nota_de_credito(monkeypatch):
    """A corrida verdadeira: as duas chamadas entram ao mesmo tempo. O duplo
    da colecção cede o controlo no `insert_one` antes de verificar os únicos,
    que é onde a corrida real acontece."""
    db = _db_nc()
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)

    async def duas():
        return await asyncio.gather(
            emitir_nota_credito("doc-1", _pedido(), operador=_operador()),
            emitir_nota_credito("doc-1", _pedido(), operador=_operador()),
            return_exceptions=True,
        )

    resultados = _corre(duas())
    emitidas = [r for r in resultados if isinstance(r, dict)]
    # Uma emite; a outra ou lê a nota já emitida ou leva o 409 de "está a
    # sair neste momento" — nunca uma segunda nota real.
    assert sum(len(i.chamadas_criar) for i in VendusNCFalso.instancias) == 1
    assert db[COLECOES["notas_credito"]].chamadas_insert == 1
    for resultado in resultados:
        assert isinstance(resultado, (dict, HTTPException))
        if isinstance(resultado, HTTPException):
            assert resultado.status_code == 409
    assert emitidas


def test_uma_nota_NOVA_da_mesma_fatura_e_outra_intencao_e_passa(monkeypatch):
    """O outro lado da mesma moeda: outra janela, outro uuid, outra
    referência — a parcial seguinte tem de poder sair."""
    db = _db_nc()
    primeira = _emitir(db, monkeypatch, _pedido(linhas=[{"indice": 1, "quantidade": 1}]))
    segunda = _emitir(db, monkeypatch, _pedido(
        intencao_id="33333333-3333-4333-8333-333333333333",
        linhas=[{"indice": 1, "quantidade": 1}]))
    assert primeira["id"] != segunda["id"]
    assert sum(len(i.chamadas_criar) for i in VendusNCFalso.instancias) == 2
    refs = [c["external_reference"]
            for i in VendusNCFalso.instancias for c in i.chamadas_criar]
    assert len(set(refs)) == 2


def test_uma_intencao_repetida_de_outra_fatura_nao_devolve_a_nota_alheia(monkeypatch):
    """O `intencao_id` vem do browser. Sem esta confirmação, um identificador
    repetido devolvia a nota de crédito de OUTRA fatura a quem perguntasse —
    e um ecrã a dizer que a devolução estava feita quando não estava."""
    db = _db_nc(
        documentos=[_documento_fs(), _documento_fs(
            id="doc-2", venda_id="venda-2", numero="FS 05P2026/1825",
            atcud="ATCUD-FS-1825", vendus_document_id=1825)],
        vendas=[_venda_faturada(), _venda_faturada(id="venda-2")],
    )
    _emitir(db, monkeypatch, _pedido())
    with pytest.raises(HTTPException) as erro:
        _emitir(db, monkeypatch, _pedido(), documento_id="doc-2")
    assert erro.value.status_code == 409
    assert "já foi usado noutra nota de crédito" in erro.value.detail


def test_um_intencao_id_que_nao_e_uuid_e_recusado():
    """Sem o formato fechado, um ecrã com um defeito (ou um `"1"` à mão)
    colidia com a intenção de outra loja."""
    with pytest.raises(Exception):
        _pedido(intencao_id="1")


def test_sem_o_indice_unico_confirmado_a_rota_recusa_se_a_emitir(monkeypatch):
    """A reserva atómica ou está garantida pela base de dados ou não está.
    Sem ela, dois toques inserem as duas intenções e saem DUAS notas reais."""
    db_mod.marcar_indice_notas_credito(False)
    db = _db_nc()
    with pytest.raises(HTTPException) as erro:
        _emitir(db, monkeypatch, _pedido())
    assert erro.value.status_code == 503
    assert VendusNCFalso.instancias == []


# --- 4. O DESFECHO: o que se liberta e o que fica incerto -------------------


def test_um_erro_que_prova_que_nada_saiu_liberta_a_intencao(monkeypatch):
    """O `register_id` errado rebenta ANTES de qualquer pedido à rede: a
    prova de que nada saiu é o próprio erro. A intenção desaparece e a
    operadora pode repetir."""
    db = _db_nc()
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)

    class Rebenta(VendusNCFalso):
        def __init__(self, chave):
            super().__init__(chave)
            self.erro_criar = RegisterIdInvalido("register_id não bate")
    monkeypatch.setattr(nc_mod, "ClienteEmissaoVendus", Rebenta)

    with pytest.raises(HTTPException) as erro:
        _corre(emitir_nota_credito("doc-1", _pedido(), operador=_operador()))
    assert erro.value.status_code == 502
    assert "NÃO foi emitida" in erro.value.detail
    assert _corre(db[COLECOES["notas_credito"]].find_one({})) is None


def test_um_timeout_com_verificacao_limpa_liberta_a_intencao(monkeypatch):
    """Perguntou-se ao Vendus e ele disse que não tem nada com esta
    referência — o pedido não chegou a ser processado."""
    db = _db_nc()
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)

    class Timeout(VendusNCFalso):
        def __init__(self, chave):
            super().__init__(chave)
            self.erro_criar = VendusIndisponivel("timeout")
            self.resposta_procurar = None
    monkeypatch.setattr(nc_mod, "ClienteEmissaoVendus", Timeout)

    with pytest.raises(HTTPException) as erro:
        _corre(emitir_nota_credito("doc-1", _pedido(), operador=_operador()))
    assert erro.value.status_code == 502
    assert _corre(db[COLECOES["notas_credito"]].find_one({})) is None


def test_um_timeout_com_verificacao_que_ENCONTRA_nao_emite_segunda_vez(monkeypatch):
    """A nota saiu, só a resposta é que se perdeu. Usa-se a que está lá."""
    db = _db_nc()
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)

    class Encontra(VendusNCFalso):
        def __init__(self, chave):
            super().__init__(chave)
            self.erro_criar = VendusIndisponivel("timeout")
            self.resposta_procurar = _bruto_nc()
    monkeypatch.setattr(nc_mod, "ClienteEmissaoVendus", Encontra)

    saida = _corre(emitir_nota_credito("doc-1", _pedido(), operador=_operador()))
    assert saida["numero"] == "NC 05P2026/12"
    assert len(VendusNCFalso.instancias[0].chamadas_criar) == 1
    nota = _corre(db[COLECOES["notas_credito"]].find_one({}))
    assert nota["estado"] == "emitida"


def test_um_timeout_cuja_verificacao_TAMBEM_falha_fica_incerto_e_nao_devolve(monkeypatch):
    """O pior caso: ninguém sabe se o documento saiu. A operadora NÃO devolve
    o dinheiro, a intenção fica gravada e trava novos créditos daquela linha."""
    db = _db_nc()
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)

    class Cego(VendusNCFalso):
        def __init__(self, chave):
            super().__init__(chave)
            self.erro_criar = VendusIndisponivel("timeout")
            self.erro_procurar = VendusIndisponivel("também não responde")
    monkeypatch.setattr(nc_mod, "ClienteEmissaoVendus", Cego)

    with pytest.raises(HTTPException) as erro:
        _corre(emitir_nota_credito("doc-1", _pedido(), operador=_operador()))
    assert erro.value.status_code == 503
    assert "NÃO devolva o dinheiro" in erro.value.detail
    nota = _corre(db[COLECOES["notas_credito"]].find_one({}))
    assert nota["estado"] == "incerta"


def test_um_erro_depois_do_2xx_fica_incerto_e_nao_liberta(monkeypatch):
    """Uma resposta ilegível chega DEPOIS de o documento já existir do lado
    da AT. Libertar aqui era autorizar uma segunda nota real."""
    db = _db_nc()
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)

    class Ilegivel(VendusNCFalso):
        def __init__(self, chave):
            super().__init__(chave)
            self.erro_criar = VendusErro("resposta ilegível")
    monkeypatch.setattr(nc_mod, "ClienteEmissaoVendus", Ilegivel)

    with pytest.raises(HTTPException) as erro:
        _corre(emitir_nota_credito("doc-1", _pedido(), operador=_operador()))
    assert erro.value.status_code == 503
    assert _corre(db[COLECOES["notas_credito"]].find_one({}))["estado"] == "incerta"


def test_uma_nota_incerta_trava_o_credito_da_mesma_linha(monkeypatch):
    """Ponta a ponta: depois do desfecho incerto, ninguém credita por cima."""
    db = _db_nc()
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)

    class Cego(VendusNCFalso):
        def __init__(self, chave):
            super().__init__(chave)
            self.erro_criar = VendusIndisponivel("timeout")
            self.erro_procurar = VendusIndisponivel("nada")
    monkeypatch.setattr(nc_mod, "ClienteEmissaoVendus", Cego)
    with pytest.raises(HTTPException):
        _corre(emitir_nota_credito("doc-1", _pedido(
            linhas=[{"indice": 2, "quantidade": 1}]), operador=_operador()))

    monkeypatch.setattr(nc_mod, "ClienteEmissaoVendus", VendusNCFalso)
    with pytest.raises(HTTPException) as erro:
        _corre(emitir_nota_credito("doc-1", _pedido(
            intencao_id="44444444-4444-4444-8444-444444444444",
            linhas=[{"indice": 2, "quantidade": 1}]), operador=_operador()))
    assert erro.value.status_code == 422


# --- 5. O que a API do Vendus exige numa NC --------------------------------


def test_cada_linha_da_nota_aponta_para_a_linha_exacta_da_fatura():
    """`reference_document` com `document_number` e `document_row` — exigido
    pela API («unequivocally identifies an existing line on the original
    invoice»). Sem ele o Vendus recusa o documento."""
    creditaveis = linhas_creditaveis(_venda_faturada(), [])
    escolhidas = escolher_linhas(creditaveis, [{"indice": 3, "quantidade": 2}])
    itens = itens_vendus_da_nota(escolhidas, "FS 05P2026/1824")
    assert itens[0]["reference_document"] == {
        "document_number": "FS 05P2026/1824", "document_row": 3,
    }
    assert itens[0]["qty"] == 2
    assert itens[0]["id"] == 9003  # o produto do Vendus, nunca um novo


def test_a_rota_entrega_ao_vendus_o_numero_da_fatura_original(monkeypatch):
    db = _db_nc()
    _emitir(db, monkeypatch, _pedido(linhas=[{"indice": 1, "quantidade": 1}]))
    chamada = VendusNCFalso.instancias[0].chamadas_criar[0]
    assert chamada["linhas"][0]["reference_document"]["document_number"] == "FS 05P2026/1824"
    assert chamada["motivo"].startswith("Cliente devolveu")
    assert chamada["pagamentos"] == [{"id": "316430468", "amount": 10.20}]


def test_uma_nota_de_credito_sem_motivo_e_recusada_antes_de_sair_para_a_rede(monkeypatch):
    """`notes` é exigido pela API do Vendus e pela lei portuguesa (uma NC tem
    de dizer o que rectifica e porquê). Recusar aqui poupa à operadora um 4xx
    opaco com o cliente à frente."""
    from faturacao.vendus.emissao import ClienteEmissaoVendus
    _configura_vendus_env(monkeypatch)
    with ClienteEmissaoVendus("chave-teste") as cliente:
        with pytest.raises(NotaDeCreditoSemMotivo):
            cliente.criar_nota_credito(
                linhas=[], pagamentos=[], external_reference="pos-x-y-nc-z",
                register_id=7, motivo="   ")


def test_o_pedido_sem_motivo_nem_chega_a_ser_um_pedido():
    with pytest.raises(Exception):
        _pedido(motivo="   ")


def test_so_se_credita_uma_fatura_simplificada(monkeypatch):
    db = _db_nc(documentos=[_documento_fs(tipo="NC")])
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    with pytest.raises(HTTPException) as erro:
        _corre(preparar_nota_credito("doc-1", operador=_operador()))
    assert erro.value.status_code == 422


def test_uma_fatura_sem_numero_nao_se_credita(monkeypatch):
    """Sem `document_number` não há `reference_document`, e uma NC sem a
    fatura que rectifica não é um documento legal."""
    db = _db_nc(documentos=[_documento_fs(numero=None)])
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    with pytest.raises(HTTPException) as erro:
        _corre(preparar_nota_credito("doc-1", operador=_operador()))
    assert erro.value.status_code == 409


def test_uma_fatura_de_outra_loja_e_404_e_nunca_403(monkeypatch):
    db = _db_nc()
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    with pytest.raises(HTTPException) as erro:
        _corre(preparar_nota_credito("doc-1", operador=_operador(loja_id="loja-9")))
    assert erro.value.status_code == 404


def test_o_id_do_produto_no_vendus_nunca_sai_para_o_ecra(monkeypatch):
    """A mesma regra do `vendus_payment_method_id` em
    `pos_catalogo.tipos_pagamento_do_pos`: configuração da ligação não vai ao
    balcão."""
    db = _db_nc()
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    saida = _corre(preparar_nota_credito("doc-1", operador=_operador()))
    for linha in saida["linhas"]:
        assert "id_vendus" not in linha


def test_o_id_do_vendus_tambem_nao_sai_pela_PRE_VISUALIZACAO(monkeypatch):
    """**A irmã que o deixava sair.** São as TRÊS rotas do mesmo ecrã, e só a
    de cima escondia o campo — a pré-visualização devolvia-o a cada caixa que
    a operadora marcava. A inconsistência entre as duas é o que tornava fácil
    alguém passar a depender dele."""
    db = _db_nc()
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    saida = _corre(pre_visualizar_nota_credito(
        "doc-1",
        PedidoPreVisualizar(linhas=[
            {"indice": 1, "quantidade": 1}, {"indice": 3, "quantidade": 1}]),
        operador=_operador()))
    assert saida["linhas"]
    for linha in saida["linhas"]:
        assert "id_vendus" not in linha
    # E o dinheiro continua todo lá: esconder o id não pode comer uma linha.
    assert saida["total"] == 11.35


def test_o_id_do_vendus_tambem_nao_sai_na_RESPOSTA_DA_EMISSAO(monkeypatch):
    """A terceira, e é a que a operadora tem à frente depois de a nota sair —
    as MESMAS linhas que a pré-visualização mostrou."""
    db = _db_nc()
    saida = _emitir(db, monkeypatch, _pedido(linhas=[{"indice": 1, "quantidade": 2}]))
    assert saida["linhas"]
    for linha in saida["linhas"]:
        assert "id_vendus" not in linha
    assert saida["total_das_linhas"] == 20.40
    # E o que FOI ao Vendus levou-o na mesma: é ele que impede o Vendus de
    # criar um artigo novo a cada documento.
    enviadas = VendusNCFalso.instancias[0].chamadas_criar[0]["linhas"]
    assert all(li.get("id") for li in enviadas)


# --- 6. O DINHEIRO DO TURNO: a devolução segue o meio de pagamento ---------
#
# A decisão do dono, nas palavras dele: «se a nota de crédito estiver lá que
# a devolução foi em dinheiro, sim sai da gaveta. se não, sai dos outros
# lugares.»


def _venda_paga(tipo_fiscal="NU", nome="Dinheiro", valor=24.14, tipo_id="tipo-dinheiro"):
    return _venda_faturada(pagamentos=[{
        "tipo_pagamento_id": tipo_id, "nome": nome,
        "tipo_fiscal": tipo_fiscal, "valor": valor,
    }])


def _nota_devolvida(tipo_fiscal, nome, valor, tipo_id, estado="emitida"):
    return {
        "estado": estado,
        "linhas": [{"indice": 1, "quantidade": 1, "tax_id": "INT", "total": valor}],
        "devolucao": {
            "tipo_pagamento_id": tipo_id, "nome": nome,
            "tipo_fiscal": tipo_fiscal, "valor": valor,
        },
    }


def test_uma_devolucao_em_DINHEIRO_sai_da_gaveta():
    """O buraco que a nota de crédito veio tapar: hoje o dinheiro devolvido
    não entrava em lado nenhum e a gaveta fechava a acusar uma falta que
    ninguém sabia explicar."""
    vendas = [_venda_paga()]
    nota = _nota_devolvida("NU", "Dinheiro", 10.20, "tipo-dinheiro")
    assert soma_vendas_dinheiro(vendas) == 24.14
    assert soma_vendas_dinheiro(vendas, [nota]) == 13.94


def test_uma_devolucao_no_GLOVO_nao_toca_na_gaveta():
    """«se não, sai dos outros lugares.»"""
    vendas = [_venda_paga()]
    nota = _nota_devolvida("OU", "Glovo", 10.20, "tipo-glovo")
    assert soma_vendas_dinheiro(vendas, [nota]) == 24.14

    linhas = {li["nome"]: li["total"] for li in por_tipo_de_pagamento(vendas, [nota])}
    assert linhas["Dinheiro"] == 24.14
    assert linhas["Glovo"] == -10.20


def test_uma_devolucao_no_multibanco_fica_negativa_na_linha_do_multibanco():
    vendas = [_venda_paga(tipo_fiscal="CD", nome="Multibanco", tipo_id="tipo-mb")]
    nota = _nota_devolvida("CD", "Multibanco", 1.15, "tipo-mb")
    linhas = {li["nome"]: li["total"] for li in por_tipo_de_pagamento(vendas, [nota])}
    assert linhas["Multibanco"] == 22.99
    assert soma_vendas_dinheiro(vendas, [nota]) == 0.0  # nada em dinheiro, nada sai


def test_uma_devolucao_num_meio_que_o_turno_nao_teve_aparece_sozinha_e_negativa():
    """Nada se perde: se o Glovo não vendeu nada neste turno mas houve uma
    devolução por lá, a linha aparece na mesma — é onde alguém dá por ela."""
    linhas = por_tipo_de_pagamento(
        [_venda_paga()], [_nota_devolvida("OU", "Glovo", 0.29, "tipo-glovo")])
    glovo = next(li for li in linhas if li["nome"] == "Glovo")
    assert glovo["total"] == -0.29


def test_uma_devolucao_por_apurar_nao_desconta_a_gaveta():
    """Descontá-la era mandar a operadora justificar uma falta que talvez não
    exista."""
    vendas = [_venda_paga()]
    incerta = _nota_devolvida("NU", "Dinheiro", 10.20, "tipo-dinheiro", estado="incerta")
    assert soma_vendas_dinheiro(vendas, [incerta]) == 24.14


def test_o_ponto_de_caixa_e_o_Z_leem_a_devolucao_pela_mesma_funcao():
    """`_resumo_do_turno` é a ÚNICA aritmética dos dois ecrãs — a operadora
    não pode ver um número às 15h e outro no Z das 23h."""
    sessao = _sessao(fundo=50.0)
    vendas = [_venda_paga()]
    nota = _nota_devolvida("NU", "Dinheiro", 10.20, "tipo-dinheiro")
    resumo = caixa_mod._resumo_do_turno(sessao, [], vendas, [nota])
    assert resumo["vendas_dinheiro"] == 13.94
    assert resumo["esperado"] == 63.94
    assert resumo["quantos_documentos"] == 2  # a fatura e a nota


def test_o_Z_nao_desconta_a_devolucao_feita_no_glovo_do_dinheiro_esperado():
    sessao = _sessao(fundo=50.0)
    resumo = caixa_mod._resumo_do_turno(
        sessao, [], [_venda_paga()],
        [_nota_devolvida("OU", "Glovo", 10.20, "tipo-glovo")])
    assert resumo["vendas_dinheiro"] == 24.14
    assert resumo["esperado"] == 74.14
    assert resumo["total_faturado"] == 13.94


def test_a_rota_grava_o_retrato_do_tipo_de_pagamento_da_devolucao(monkeypatch):
    """Um retrato, e não uma referência: renomear o "Glovo" para "Glovo PT"
    amanhã não pode reescrever o Z de ontem."""
    db = _db_nc()
    saida = _emitir(db, monkeypatch, _pedido(tipo_pagamento_id="tipo-glovo"))
    assert saida["devolucao"] == {
        "tipo_pagamento_id": "tipo-glovo", "nome": "Glovo",
        "tipo_fiscal": "OU", "valor": 10.20,
        # A fatura por omissão não tem `pagamentos` gravados (é o retrato de
        # uma venda emitida por uma versão anterior): nesse caso NADA daquele
        # meio está disponível, e a devolução inteira fica acima do recebido.
        # É a resposta honesta — e é a que põe o número à frente da operadora.
        "acima_do_recebido": 10.20,
    }


def test_um_tipo_de_pagamento_sem_metodo_do_vendus_nao_devolve_dinheiro(monkeypatch):
    db = _db_nc(tipos=[_tipo_pagamento(vendus_payment_method_id=None)])
    with pytest.raises(HTTPException) as erro:
        _emitir(db, monkeypatch, _pedido())
    assert erro.value.status_code == 422
    assert VendusNCFalso.instancias == []


def test_um_tipo_de_pagamento_inactivo_nao_devolve_dinheiro(monkeypatch):
    db = _db_nc(tipos=[_tipo_pagamento(ativo=False)])
    with pytest.raises(HTTPException) as erro:
        _emitir(db, monkeypatch, _pedido())
    assert erro.value.status_code == 422


# --- 7. A NOTA E O FECHO DE CAIXA ------------------------------------------


def test_uma_nota_de_credito_A_MEIO_trava_o_fecho_da_caixa(monkeypatch):
    """O mesmo par (marcar, depois perguntar) da emissão de faturas: ou o
    fecho vê esta intenção e recusa, ou a nota vê a marca do fecho e aborta.
    Sem isto, a devolução saía DEPOIS de o Z estar assinado."""
    db = _db_nc(notas=[{
        "id": "intencao-viva", "sessao_id": "sessao-1", "estado": "reservada",
        "documento_id": "doc-1", "linhas": [], "devolucao": {},
    }])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)
    presa = _corre(caixa_mod._nota_de_credito_em_curso(db, _sessao()))
    assert presa is not None and presa["id"] == "intencao-viva"


def test_uma_nota_ja_emitida_nao_trava_o_fecho():
    """Ela já entrou no resumo do turno — é isso que o Z tem de dizer."""
    db = _db_nc(notas=[{
        "id": "n1", "sessao_id": "sessao-1", "estado": "emitida",
        "documento_id": "doc-1", "linhas": [], "devolucao": {},
    }])
    assert _corre(caixa_mod._nota_de_credito_em_curso(db, _sessao())) is None


def test_uma_nota_incerta_nao_prende_a_caixa_da_loja():
    """Não há nada a esperar dela: ninguém sabe se o documento saiu, e
    prender a caixa até alguém ir ao Vendus era pior do que o problema."""
    db = _db_nc(notas=[{
        "id": "n1", "sessao_id": "sessao-1", "estado": "incerta",
        "documento_id": "doc-1", "linhas": [], "devolucao": {},
    }])
    assert _corre(caixa_mod._nota_de_credito_em_curso(db, _sessao())) is None


def test_o_turno_le_so_as_notas_DESTA_sessao():
    """A devolução conta no turno em que o dinheiro se mexeu, não no da
    fatura: o cliente que volta amanhã é creditado na gaveta de amanhã."""
    db = _db_nc(notas=[
        {"id": "n1", "sessao_id": "sessao-1", "estado": "emitida",
         "documento_id": "doc-1", "linhas": [], "devolucao": {}},
        {"id": "n2", "sessao_id": "sessao-OUTRA", "estado": "emitida",
         "documento_id": "doc-1", "linhas": [], "devolucao": {}},
    ])
    do_turno = _corre(caixa_mod._notas_de_credito_do_turno(db, _sessao()))
    assert [n["id"] for n in do_turno] == ["n1"]


def test_sem_caixa_aberta_nao_se_emite_nota_de_credito(monkeypatch):
    """A nota ficaria fora de todos os Z e o dinheiro devolvido não entrava
    em conta nenhuma."""
    db = _db_nc(sessoes=[_sessao(estado="fechada")])
    with pytest.raises(HTTPException):
        _emitir(db, monkeypatch, _pedido())
    assert VendusNCFalso.instancias == []


def test_a_caixa_que_fecha_a_meio_da_preparacao_aborta_sem_emitir(monkeypatch):
    """A releitura da sessão DEPOIS da reserva — o passo 3. Nada vai ao
    Vendus e nenhum dinheiro sai."""
    db = _db_nc()
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    sessoes = db[COLECOES["sessoes_caixa"]]
    original = sessoes.find_one
    chamadas = {"n": 0}

    async def fecha_a_meio(filtro, projecao=None):
        chamadas["n"] += 1
        # A primeira leitura (a de `_sessao_aberta`) vê a sessão aberta; a
        # RELEITURA, já depois da intenção estar gravada, vê-a fechada.
        if chamadas["n"] > 1:
            return {**_sessao(), "estado": "fechada"}
        return await original(filtro, projecao)
    sessoes.find_one = fecha_a_meio

    with pytest.raises(HTTPException) as erro:
        _corre(emitir_nota_credito("doc-1", _pedido(), operador=_operador()))
    assert erro.value.status_code == 409
    assert "NADA foi enviado ao Vendus" in erro.value.detail
    assert VendusNCFalso.instancias == []
    # E a intenção foi libertada: a operadora repete no turno novo.
    assert _corre(db[COLECOES["notas_credito"]].find_one({})) is None


def test_uma_caixa_de_outra_loja_nao_serve_para_devolver(monkeypatch):
    db = _db_nc(caixas=[{"id": "caixa-1", "loja_id": "loja-9"}])
    with pytest.raises(HTTPException) as erro:
        _emitir(db, monkeypatch, _pedido())
    assert erro.value.status_code == 404


# --- 8. O que fica gravado -------------------------------------------------


def test_a_nota_emitida_grava_se_em_fat_documentos_com_tipo_NC(monkeypatch):
    """É isso que faz o Dashboard descontar a devolução da receita e o
    separador Faturação mostrar a nota ao lado da fatura que ela corrige."""
    db = _db_nc()
    _emitir(db, monkeypatch, _pedido())
    nc = _corre(db[COLECOES["documentos"]].find_one({"tipo": "NC"}))
    assert nc["numero"] == "NC 05P2026/12"
    assert nc["documento_origem_id"] == "doc-1"
    assert nc["numero_origem"] == "FS 05P2026/1824"
    assert nc["ext_ref"] == "pos-loja-1-sessao-1-nc-11111111-1111-4111-8111-111111111111"


def test_o_documento_da_nota_nao_leva_venda_id(monkeypatch):
    """Gravá-lo fazia `documentos.obter_documento` desenhar a nota com os
    artigos TODOS da conta original e um mapa de imposto que não é o dela —
    um documento fiscal a mostrar números que não são os seus."""
    db = _db_nc()
    _emitir(db, monkeypatch, _pedido())
    nc = _corre(db[COLECOES["documentos"]].find_one({"tipo": "NC"}))
    assert "venda_id" not in nc


def test_a_resposta_assinala_uma_divergencia_entre_o_nosso_total_e_o_do_vendus(monkeypatch):
    """As linhas vão com o preço e o desconto da fatura e a fórmula é a do
    Vendus — os dois totais deviam bater. É por isso que uma divergência tem
    de aparecer no ecrã em vez de ser escolhida em silêncio."""
    db = _db_nc()
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)

    class Divergente(VendusNCFalso):
        def __init__(self, chave):
            super().__init__(chave)
            self.resposta_criar = _bruto_nc(total=10.19)
    monkeypatch.setattr(nc_mod, "ClienteEmissaoVendus", Divergente)

    saida = _corre(emitir_nota_credito("doc-1", _pedido(), operador=_operador()))
    assert saida["total"] == 10.19
    assert saida["total_das_linhas"] == 10.20
    assert saida["total_divergente"] is True


def test_sem_divergencia_a_bandeira_fica_em_baixo(monkeypatch):
    db = _db_nc()
    saida = _emitir(db, monkeypatch, _pedido())
    assert saida["total_divergente"] is False


def test_o_ecra_ve_as_notas_anteriores_desta_fatura(monkeypatch):
    """A operadora tem de saber que o cliente já cá veio, e com que
    documento."""
    db = _db_nc()
    _emitir(db, monkeypatch, _pedido(linhas=[{"indice": 2, "quantidade": 1}]))
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    saida = _corre(preparar_nota_credito("doc-1", operador=_operador()))
    assert len(saida["notas_anteriores"]) == 1
    assert saida["notas_anteriores"][0]["numero"] == "NC 05P2026/12"
    assert saida["notas_anteriores"][0]["estado"] == "emitida"
    # E a linha já creditada aparece esgotada, em vez de desaparecer.
    agua = next(li for li in saida["linhas"] if li["indice"] == 2)
    assert agua["disponivel"] == 0.0
    assert agua["creditado"] == 1.0


# --- 9. A PRÉ-VISUALIZAÇÃO: o ecrã não soma euros --------------------------


def test_a_pre_visualizacao_devolve_o_mapa_de_imposto_do_servidor(monkeypatch):
    db = _db_nc()
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    saida = _corre(pre_visualizar_nota_credito(
        "doc-1",
        PedidoPreVisualizar(linhas=[
            {"indice": 1, "quantidade": 1}, {"indice": 3, "quantidade": 1}]),
        operador=_operador()))
    assert saida["total"] == 11.35   # 10,20 + 1,15
    assert saida["subtotal"] == round(saida["total"] - saida["totais_imposto"]["iva"], 2)
    taxas = {li["taxa"]: li["total"] for li in saida["mapa_imposto"]}
    assert taxas == {13: 10.20, 23: 1.15}


def test_a_pre_visualizacao_sem_nada_escolhido_nao_pinta_o_ecra_de_vermelho(monkeypatch):
    """É o estado em que o ecrã abre — zero, e não um 422."""
    db = _db_nc()
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    saida = _corre(pre_visualizar_nota_credito(
        "doc-1", PedidoPreVisualizar(linhas=[]), operador=_operador()))
    assert saida["total"] == 0.0
    assert saida["mapa_imposto"] == []


def test_a_pre_visualizacao_aplica_o_MESMO_travao_da_emissao(monkeypatch):
    """A operadora vê a recusa enquanto escolhe, e não depois de carregar em
    EMITIR com o cliente à frente."""
    db = _db_nc()
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    with pytest.raises(HTTPException) as erro:
        _corre(pre_visualizar_nota_credito(
            "doc-1", PedidoPreVisualizar(linhas=[{"indice": 1, "quantidade": 9}]),
            operador=_operador()))
    assert erro.value.status_code == 422


# --- 10. A CORRIDA: duas notas concorrentes sobre a MESMA fatura -------------
#
# O travão da quantidade (`linhas_creditaveis` → `escolher_linhas`) é
# ler-verificar-escrever, e sozinho não trava nada: duas rotas em paralelo lêem
# as mesmas notas (nenhuma) e emitem as duas. O índice único de
# `fat_notas_credito.id` é sobre a INTENÇÃO — por desenho deixa haver várias
# notas por fatura — e por isso não fecha esta corrida.
#
# **Medido, com o duplo de Mongo a ceder o event loop em cada leitura:** uma
# fatura de 11,29 € paga em dinheiro, dois POST concorrentes com intenções
# diferentes → estados [201, 201], DUAS emissões reais no Vendus, dois
# documentos NC, o esperado da gaveta em 38,71 € em vez de 50,00 e o
# `total_faturado` do turno em −11,29 €. Sem o `to_list` a ceder, a corrida
# não existe no arnês e continua a existir em produção.


class CursorQueCede(CursorFalso):
    """Um cursor cujo `to_list` CEDE o event loop, como uma leitura de rede
    faz. Sem isto, `find(...).to_list(...)` corre de fio a pavio dentro de uma
    só tarefa e as duas rotas nunca se cruzam — o arnês media um mundo em que
    a corrida é impossível."""

    async def to_list(self, n=None):
        await asyncio.sleep(0)
        return await CursorFalso.to_list(self, n)


class ColeccaoQueCede(ColeccaoFalsa):
    def find(self, filtro=None, projecao=None):
        return CursorQueCede(ColeccaoFalsa.find(self, filtro, projecao)._itens)


def _db_que_cede(**kwargs):
    """O mesmo `_db_nc`, com todas as colecções a ceder nas leituras."""
    db = _db_nc(**kwargs)
    for nome, coleccao in list(db._coleccoes.items()):
        db._coleccoes[nome] = ColeccaoQueCede(
            coleccao._documentos, indices_unicos=coleccao._indices_unicos)
    return db


def _pedido_da_fatura_inteira(intencao):
    return _pedido(intencao_id=intencao, linhas=[
        {"indice": 1, "quantidade": 2},
        {"indice": 2, "quantidade": 1},
        {"indice": 3, "quantidade": 3},
    ])


def _duas_em_paralelo(db, monkeypatch):
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    a = emitir_nota_credito(
        "doc-1", _pedido_da_fatura_inteira("11111111-1111-4111-8111-111111111111"),
        operador=_operador())
    b = emitir_nota_credito(
        "doc-1", _pedido_da_fatura_inteira("22222222-2222-4222-8222-222222222222"),
        operador=_operador())
    return _corre(asyncio.gather(a, b, return_exceptions=True))


def test_duas_notas_concorrentes_da_MESMA_fatura_so_uma_emite(monkeypatch):
    """**O defeito que punha DOIS documentos fiscais reais na AT.** Duas
    janelas abertas na mesma fatura, dois toques ao mesmo tempo: a segunda
    perde a escrita condicional que reserva o crédito, e perde ANTES de falar
    com o Vendus."""
    db = _db_que_cede()
    resultados = _duas_em_paralelo(db, monkeypatch)

    codigos = sorted(
        r.status_code if isinstance(r, HTTPException) else 201 for r in resultados)
    assert codigos == [201, 409]
    # UMA emissão real, e um só documento — é isto que a AT vê.
    assert sum(len(v.chamadas_criar) for v in VendusNCFalso.instancias) == 1
    documentos = db[COLECOES["documentos"]]._documentos
    assert len([d for d in documentos if d["tipo"] == "NC"]) == 1


def test_a_nota_que_PERDEU_a_corrida_nao_deixa_intencao_nenhuma(monkeypatch):
    """Perder aqui não custa documento nenhum — e não pode custar o fecho da
    caixa: uma intenção `reservada` deixada para trás travava o turno."""
    db = _db_que_cede()
    _duas_em_paralelo(db, monkeypatch)
    notas = db[COLECOES["notas_credito"]]._documentos
    assert [n["estado"] for n in notas] == ["emitida"]


def test_a_corrida_perdida_NAO_desconta_a_gaveta_duas_vezes(monkeypatch):
    """O dinheiro, que é o que se estava a perder. A fatura de 24,14 € paga em
    dinheiro creditada por inteiro deixa a gaveta no fundo — e não 24,14 €
    abaixo dele."""
    venda = _venda_faturada()
    venda["pagamentos"] = [{"tipo_pagamento_id": "tipo-dinheiro",
                            "nome": "Dinheiro", "tipo_fiscal": "NU",
                            "valor": 24.14}]
    db = _db_que_cede(vendas=[venda])
    _duas_em_paralelo(db, monkeypatch)

    emitidas = [n for n in db[COLECOES["notas_credito"]]._documentos
                if n["estado"] == "emitida"]
    assert soma_vendas_dinheiro([venda], emitidas) == 0.0
    assert totais_do_mapa(mapa_de_imposto([venda], emitidas))["total"] == 0.0


def test_a_recusa_da_corrida_diz_a_operadora_o_que_fazer(monkeypatch):
    db = _db_que_cede()
    resultados = _duas_em_paralelo(db, monkeypatch)
    recusa = next(r for r in resultados if isinstance(r, HTTPException))
    assert "NÃO saiu" in recusa.detail
    assert "abra a nota de crédito outra vez" in recusa.detail


def test_duas_notas_de_LINHAS_DIFERENTES_da_mesma_fatura_passam_as_duas(monkeypatch):
    """O controlo, e é o que impede a correcção de ser um cadeado por fatura:
    duas parciais legítimas — o refrigerante hoje, o açaí amanhã — continuam a
    poder existir. Aqui, uma de cada vez, como acontece ao balcão."""
    db = _db_nc()
    primeira = _emitir(db, monkeypatch, _pedido(linhas=[{"indice": 3, "quantidade": 3}]))
    segunda = _emitir(db, monkeypatch, _pedido(
        intencao_id="22222222-2222-4222-8222-222222222222",
        linhas=[{"indice": 1, "quantidade": 2}]))
    # `total` é o do DOCUMENTO que o Vendus devolveu; `total_das_linhas` é o
    # que este servidor somou — e é este que diz o que cada parcial creditou.
    assert primeira["total_das_linhas"] == 3.45
    assert segunda["total_das_linhas"] == 20.40
    assert len([d for d in db[COLECOES["documentos"]]._documentos
                if d["tipo"] == "NC"]) == 2


def test_o_selo_do_credito_avanca_a_cada_nota_emitida(monkeypatch):
    """A escrita condicional é sobre este selo, e ele vive na FATURA — é o
    recurso partilhado pelas duas notas."""
    db = _db_nc()
    documento = db[COLECOES["documentos"]]._documentos[0]
    assert "nc_reserva_seq" not in documento
    _emitir(db, monkeypatch, _pedido(linhas=[{"indice": 3, "quantidade": 1}]))
    assert documento["nc_reserva_seq"] == 1
    _emitir(db, monkeypatch, _pedido(
        intencao_id="22222222-2222-4222-8222-222222222222",
        linhas=[{"indice": 3, "quantidade": 1}]))
    assert documento["nc_reserva_seq"] == 2


# --- 11. O CÊNTIMO das parciais ----------------------------------------------


def test_as_parciais_de_uma_LINHA_somam_exactamente_a_linha(monkeypatch):
    """Creditar 1 açaí hoje e 1 amanhã devolve os mesmos 20,40 € que creditar
    os dois de uma vez — e a fatura fica a zero no Z."""
    venda = _venda_faturada()
    notas = []
    for _ in range(2):
        escolhidas = escolher_linhas(
            linhas_creditaveis(venda, notas), [{"indice": 1, "quantidade": 1}])
        notas.append({"linhas": escolhidas, "estado": "emitida",
                      "total": total_das_linhas(escolhidas)})
    assert round(sum(n["total"] for n in notas), 2) == 20.40


def test_uma_linha_de_dez_a_cinco_centimos_em_cem_fatias_devolve_meio_euro():
    """**O caso que mostra a raiz.** Cada fatia de 0,1 valia
    `round(0,1 × 0,05, 2) = 0,01 €` por si só, e cem cêntimos são um euro: a
    linha de 0,50 € devolvia 1,00 €. E a regra valia para qualquer preço."""
    venda = _venda_faturada(linhas=[_linha_agua(
        produto_nome="Topping", produto_preco=0.05, quantidade=10)])
    notas = []
    for _ in range(100):
        escolhidas = escolher_linhas(
            linhas_creditaveis(venda, notas), [{"indice": 1, "quantidade": 0.1}])
        notas.append({"linhas": escolhidas, "estado": "emitida",
                      "total": total_das_linhas(escolhidas)})
    assert round(sum(n["total"] for n in notas), 2) == 0.50
    assert totais_do_mapa(mapa_de_imposto([venda], notas))["total"] == 0.0


@pytest.mark.parametrize("preco,quantidade,fatias", [
    (0.05, 10, 100),
    (0.29, 3, 3),
    (1.15, 3, 7),
    (10.20, 2, 3),
    (9.85, 6, 4),
])
def test_fuzz_as_parciais_fraccionarias_nunca_devolvem_mais_do_que_a_fatura(
        preco, quantidade, fatias):
    """Parciais FRACCIONÁRIAS — que é o que o campo da quantidade aceita, e o
    que uma conta repartida produz (0,33337 de um açaí). Medido antes da
    correcção, em 4986 faturas ao acaso creditadas em duas parciais: 1279
    devolviam um valor diferente do que a fatura cobrou (441 a mais, 838 a
    menos, até 0,03 €)."""
    venda = _venda_faturada(linhas=[_linha_agua(
        produto_preco=preco, quantidade=quantidade)])
    esperado = total_das_linhas(linhas_creditaveis(venda, []))
    notas = []
    restante = float(quantidade)
    for i in range(fatias):
        fatia = round(quantidade / fatias, 5) if i < fatias - 1 else round(restante, 5)
        restante = round(restante - fatia, 5)
        if fatia <= 0:
            continue
        escolhidas = escolher_linhas(
            linhas_creditaveis(venda, notas), [{"indice": 1, "quantidade": fatia}])
        notas.append({"linhas": escolhidas, "estado": "emitida",
                      "total": total_das_linhas(escolhidas)})
    assert round(sum(n["total"] for n in notas), 2) == esperado


def test_o_desconto_que_vai_ao_VENDUS_reproduz_o_centimo_que_gravamos():
    """As linhas da nota levam `qty` e `gross_price`, e o Vendus faz a conta
    dele: `round(bruto × (1 − pct/100), 2)`. Se o desconto enviado não
    reproduzisse o valor acumulado, o documento entregue à AT dizia um número
    e nós gravávamos outro — a divergir a cada parcial."""
    venda = _venda_faturada(linhas=[_linha_agua(
        produto_preco=0.05, quantidade=10)])
    notas = []
    for _ in range(3):
        escolhidas = escolher_linhas(
            linhas_creditaveis(venda, notas), [{"indice": 1, "quantidade": 0.1}])
        for linha in escolhidas:
            bruto = round(linha["quantidade"] * linha["preco_unitario"], 2)
            pct = linha.get("desconto_percentagem") or 0.0
            assert round(bruto * (1 - pct / 100.0), 2) == linha["total"]
        notas.append({"linhas": escolhidas, "estado": "emitida",
                      "total": total_das_linhas(escolhidas)})


# --- 11-B. A PARCIAL FRACCIONÁRIA e o cêntimo que a AT não via ---------------
#
# **A nossa soma fechava e a fatia que não somava estava do lado do Vendus.**
# A meia Coca-Cola de 1,15 €: ia `qty=0.5 gross=1.15 discount_percentage=None`,
# nós gravávamos **0,58** (o acumulado, que é o que faz as parciais somarem a
# linha), o Vendus calculava `round(0.5 × 1,15, 2) = 0,57` — e **a gaveta era
# descontada pelo nosso 0,58**. Um a três cêntimos por nota, sempre com a AT a
# MENOS, e o ecrã só gritava (`total_divergente`) depois de o documento real já
# lá estar.
#
# Medido nas rotas de cálculo, em 2660 parciais de metades (preços de 0,01 a
# 3,99, linhas de 1 a 4 unidades): **340 divergiam, todas em −0,01 €**.
#
# A causa: `fiscal._percentagem_que_reproduz` só sabe DESCONTAR (`max(0.0, …)`)
# e o meio-cêntimo do acumulado sobe (`parte_acumulada` arredonda o meio para
# CIMA, em inteiros) onde `round(0.5 × 1,15, 2)` desce. Nenhuma regra de
# arredondamento fecha isto: seis meias unidades de um artigo de 0,25 € têm de
# somar 0,75 €, e seis vezes o tecto de 0,12 € são 0,72 € — o tecto é o
# problema, não o arredondamento.


def _liquido_como_o_vendus(item):
    """A conta que o Vendus faz do lado dele, linha a linha — a MESMA fórmula
    de `mapa_imposto._liquido_da_linha` e do oráculo de `test_fiscal`:
    `round(qty × gross_price, 2)`, e sobre isso `× (1 − pct/100)`.

    Escrita aqui de propósito, e não importada: é o ORÁCULO deste guarda. Se
    fosse a nossa função, o teste comparava o código com ele próprio."""
    bruto = round(item["qty"] * item["gross_price"], 2)
    pct = item.get("discount_percentage") or 0.0
    return round(bruto * (1 - pct / 100.0), 2)


def test_a_MEIA_COCA_COLA_de_1_15_chega_a_AT_pelos_mesmos_centimos_da_gaveta():
    """**O defeito, na fatura deste ficheiro.** A linha 3 é Coca-Cola 1,15 × 3;
    metade de uma vale 0,575 €. Nós gravamos 0,58 (é o acumulado que faz as
    seis metades somarem 3,45) e a gaveta é descontada por 0,58 — logo o
    documento entregue à AT tem de dizer 0,58, e não 0,57."""
    escolhidas = escolher_linhas(
        linhas_creditaveis(_venda_faturada(), []),
        [{"indice": 3, "quantidade": 0.5}])
    assert escolhidas[0]["total"] == 0.58
    itens = itens_vendus_da_nota(escolhidas, "FS 05P2026/1824")
    assert _liquido_como_o_vendus(itens[0]) == 0.58


def test_NENHUMA_parcial_de_metades_deixa_a_AT_ao_lado_do_que_gravamos():
    """A varredura que mediu o defeito, agora como guarda: 2660 parciais de
    metades. Antes: 340 divergentes, todas com a AT um cêntimo abaixo. Não é
    «poucas»: é ZERO, porque cada uma delas é um documento fiscal real."""
    divergentes = []
    for centimos in range(1, 400, 3):
        preco = centimos / 100.0
        for quantidade in (1, 2, 3, 4):
            venda = _venda_faturada(linhas=[_linha_agua(
                produto_preco=preco, quantidade=quantidade)])
            notas = []
            for _ in range(quantidade * 2):
                escolhidas = escolher_linhas(
                    linhas_creditaveis(venda, notas),
                    [{"indice": 1, "quantidade": 0.5}])
                item = itens_vendus_da_nota(escolhidas, "FS 1")[0]
                if _liquido_como_o_vendus(item) != escolhidas[0]["total"]:
                    divergentes.append((preco, quantidade, escolhidas[0]["total"],
                                        _liquido_como_o_vendus(item)))
                notas.append({"linhas": escolhidas, "estado": "emitida"})
    assert divergentes == []

def test_NENHUMA_fraccao_deixa_a_AT_ao_lado_do_que_gravamos():
    """**A varredura das metades, alargada ao resto das fracções e às linhas
    COM desconto** — que é onde os dois mecanismos se cruzam.

    A varredura acima só mede metades de linhas sem desconto. Uma conta
    repartida por três, por quatro ou por cinco produz as outras fracções, e
    uma fatura com desconto produz uma linha em que o preço tem de SUBIR (para
    o bruto chegar ao acumulado) e a percentagem tem de DESCONTAR (para o
    bruto voltar a descer até ele) na mesma linha. Medido: nos preços de 1
    cêntimo a 3,99 €, isso acontece em 5 linhas com desconto e em 400 sem —
    raro, e por isso mesmo o sítio onde uma regressão passava despercebida.

    864 sequências, cada uma a creditar a linha inteira em fatias de 1/n. Por
    fatia compara-se o cêntimo que GRAVAMOS com o que a AT vai calcular; no
    fim, a soma das fatias com o líquido da linha."""
    divergentes = []
    for preco in (0.05, 0.25, 0.29, 0.55, 0.75, 1.15, 1.25, 2.45,
                  3.33, 5.05, 7.77, 10.20):
        for quantidade in (1, 2, 3, 4):
            for fatias_por_unidade in (2, 3, 4, 5, 8, 10):
                for desconto in (None, 10, 33):
                    venda = _venda_faturada(linhas=[_linha_agua(
                        produto_preco=preco, quantidade=quantidade,
                        desconto_pct=desconto)])
                    esperado = _centimos(
                        linhas_creditaveis(venda, [])[0]["total"])
                    fatia = round(1.0 / fatias_por_unidade, 5)
                    notas, somado = [], 0
                    for _ in range(quantidade * fatias_por_unidade):
                        escolhidas = escolher_linhas(
                            linhas_creditaveis(venda, notas),
                            [{"indice": 1, "quantidade": fatia}])
                        gravado = _centimos(escolhidas[0]["total"])
                        item = itens_vendus_da_nota(escolhidas, "FS 1")[0]
                        na_at = _centimos(_liquido_como_o_vendus(item))
                        if na_at != gravado:
                            divergentes.append(
                                (preco, quantidade, fatia, desconto,
                                 gravado, na_at))
                        somado += gravado
                        notas.append({"linhas": escolhidas, "estado": "emitida"})
                    if somado != esperado:
                        divergentes.append(
                            (preco, quantidade, fatia, desconto,
                             "soma", somado, esperado))
    assert divergentes == []


def test_a_GAVETA_sai_pelos_MESMOS_centimos_que_a_AT_recebe(monkeypatch):
    """**Os três números, na rota real e de uma só vez.** Uma meia Coca-Cola
    de 1,15 €: o que a nota GRAVA (`total`), o que sai da GAVETA
    (`devolucao.valor`, que é o que o Ponto de Caixa e o Z descontam) e o que
    a AT recebe (a linha que foi mesmo entregue ao cliente do Vendus) têm de
    ser o MESMO número — 0,58 €.

    Os testes acima medem-no nas funções de cálculo. Este mede-o na rota, e é
    o único que prova que o preço corrigido chega ao PAYLOAD: entre
    `escolher_linhas` e o Vendus há `itens_vendus_da_nota`, e uma nota gravada
    com o cêntimo certo e enviada com o preço da fatura era exactamente o
    defeito."""
    db = _db_nc()
    resposta = _emitir(db, monkeypatch, _pedido(
        linhas=[{"indice": 3, "quantidade": 0.5}]))

    gravado = _centimos(resposta["total_das_linhas"])
    gaveta = _centimos(resposta["devolucao"]["valor"])
    enviadas = VendusNCFalso.instancias[-1].chamadas_criar[0]["linhas"]
    na_at = _centimos(_liquido_como_o_vendus(enviadas[0]))

    assert gravado == 58
    assert gaveta == 58
    assert na_at == 58


def test_o_PRECO_que_vai_ao_Vendus_so_sobe_quando_o_centimo_o_obriga():
    """**O controlo, e é o que impede a correcção de ser um preço inventado.**
    A linha inteira, e a metade de um preço PAR, não mexem no preço nenhum: o
    documento diz o mesmo preço unitário da fatura, que é o caso normal.

    Onde ele sobe, sobe o MÍNIMO — um cêntimo — e é isso que põe o produto
    fora da fronteira do meio-cêntimo: `0,5 × 1,16 = 0,58` exacto, sem
    arredondamento nenhum pelo meio, e por isso o mesmo número em qualquer
    motor que faça esta conta."""
    inteira = escolher_linhas(
        linhas_creditaveis(_venda_faturada(), []),
        [{"indice": 3, "quantidade": 3}])
    assert inteira[0]["preco_unitario_vendus"] == 1.15

    venda_par = _venda_faturada(linhas=[_linha_agua(produto_preco=1.10, quantidade=2)])
    metade_par = escolher_linhas(
        linhas_creditaveis(venda_par, []), [{"indice": 1, "quantidade": 0.5}])
    assert metade_par[0]["preco_unitario_vendus"] == 1.10

    metade_impar = escolher_linhas(
        linhas_creditaveis(_venda_faturada(), []),
        [{"indice": 3, "quantidade": 0.5}])
    assert metade_impar[0]["preco_unitario_vendus"] == 1.16
    # E o que o ECRÃ mostra continua a ser o preço da FATURA — é esse que a
    # operadora tem à frente e o que o cliente pagou.
    assert metade_impar[0]["preco_unitario"] == 1.15


def test_um_centimo_IRREPRODUZIVEL_e_recusado_ANTES_de_ir_a_AT(monkeypatch):
    """A última rede, e a razão de ela existir: o ecrã já gritava
    `total_divergente`, mas só DEPOIS de o documento real estar na AT. Se
    alguma parcial não se conseguir reproduzir, a rota recusa — a operadora
    lê o porquê e a fatura fica exactamente como estava.

    Aqui o instrumento é o preço travado no valor da fatura (o tecto da
    subida a zero), que é o mundo em que o defeito existia."""
    monkeypatch.setattr(nc_mod, "_MAXIMO_DE_CENTIMOS_A_SUBIR", 0)
    with pytest.raises(NotaDeCreditoInvalida) as erro:
        escolher_linhas(linhas_creditaveis(_venda_faturada(), []),
                        [{"indice": 3, "quantidade": 0.5}])
    assert "0,58" in str(erro.value)
    assert "não se emite" in str(erro.value)


def test_creditar_a_fatura_INTEIRA_de_uma_vez_continua_a_devolver_o_liquido():
    """O controlo do repartidor: nas contas normais — a esmagadora maioria —
    o número não muda."""
    venda = _venda_faturada(desconto_global_pct=10)
    creditaveis = linhas_creditaveis(venda, [])
    escolhidas = escolher_linhas(creditaveis, [{"indice": 1, "quantidade": 1}])
    assert escolhidas[0]["total"] == 9.18


# --- 12. Como a fatura foi PAGA, e a devolução confrontada com isso ----------
#
# `preparar_nota_credito` nem devolvia os pagamentos, por isso o ecrã não os
# podia mostrar e a operadora escolhia o meio da devolução às cegas. Medido:
# fatura de 11,29 € paga 5,00 em dinheiro + 6,29 em Multibanco, creditado só o
# açaí de 9,85 € com devolução em DINHEIRO → `vendas_dinheiro` de 5,00 para
# −4,85 € e o esperado da gaveta de 55,00 para 45,15 €, abaixo do fundo.


def _venda_mista(**over):
    v = _venda_faturada(**over)
    v["pagamentos"] = [
        {"tipo_pagamento_id": "tipo-dinheiro", "nome": "Dinheiro",
         "tipo_fiscal": "NU", "valor": 5.00},
        {"tipo_pagamento_id": "tipo-glovo", "nome": "Glovo",
         "tipo_fiscal": "OU", "valor": 19.14},
    ]
    return v


def test_o_ecra_da_nota_recebe_COMO_A_FATURA_FOI_PAGA(monkeypatch):
    db = _db_nc(vendas=[_venda_mista()])
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    saida = _corre(preparar_nota_credito("doc-1", operador=_operador()))
    por_nome = {p["nome"]: p for p in saida["pagamentos"]}
    assert por_nome["Dinheiro"]["recebido"] == 5.00
    assert por_nome["Dinheiro"]["disponivel"] == 5.00
    assert por_nome["Glovo"]["recebido"] == 19.14


def test_o_que_ja_foi_devolvido_sai_do_DISPONIVEL_daquele_meio():
    """As notas `emitida`, `incerta` e `reservada` contam — as mesmas do
    travão da quantidade, e pela mesma razão: o que talvez tenha saído não se
    pode contar como disponível outra vez."""
    notas = [
        {"estado": "emitida", "devolucao": {"tipo_pagamento_id": "tipo-dinheiro",
                                            "nome": "Dinheiro", "valor": 1.15}},
        {"estado": "incerta", "devolucao": {"tipo_pagamento_id": "tipo-dinheiro",
                                            "nome": "Dinheiro", "valor": 0.29}},
    ]
    por_nome = {p["nome"]: p
                for p in nc_mod.pagamentos_da_fatura(_venda_mista(), notas)}
    assert por_nome["Dinheiro"]["devolvido"] == 1.44
    assert por_nome["Dinheiro"]["disponivel"] == 3.56


def test_a_nota_GRAVA_quanto_a_devolucao_passa_o_que_aquele_meio_recebeu(monkeypatch):
    """O facto fica registado — o gestor encontra-o depois, em vez de
    encontrar uma gaveta abaixo do fundo sem explicação nenhuma."""
    db = _db_nc(vendas=[_venda_mista()])
    saida = _emitir(db, monkeypatch, _pedido(linhas=[{"indice": 1, "quantidade": 1}]))
    assert saida["devolucao"]["valor"] == 10.20
    assert saida["devolucao"]["acima_do_recebido"] == 5.20  # 10,20 − 5,00


def test_uma_devolucao_que_CABE_no_meio_nao_marca_nada(monkeypatch):
    """O controlo: uma marca que estivesse sempre lá não era marca nenhuma."""
    venda = _venda_faturada()
    venda["pagamentos"] = [{"tipo_pagamento_id": "tipo-dinheiro",
                            "nome": "Dinheiro", "tipo_fiscal": "NU",
                            "valor": 24.14}]
    db = _db_nc(vendas=[venda])
    saida = _emitir(db, monkeypatch, _pedido(linhas=[{"indice": 1, "quantidade": 1}]))
    assert saida["devolucao"]["acima_do_recebido"] == 0.0


def test_devolver_por_um_meio_que_a_fatura_NUNCA_usou_marca_o_valor_TODO():
    pagamentos = nc_mod.pagamentos_da_fatura(_venda_mista(), [])
    # O TIPO inteiro (id + nome), e não só o id: o emparelhamento precisa do
    # nome para as faturas cujo pagamento não tem id nenhum — ver
    # `nota_credito._e_o_mesmo_meio` e
    # `test_o_pagamento_sem_id_emparelha_pelo_nome.py`.
    assert nc_mod.acima_do_recebido(
        pagamentos, {"id": "tipo-mb", "nome": "Multibanco"}, 9.85) == 9.85


def test_um_TECTO_por_meio_de_pagamento_fechava_a_porta_sem_abrir_outra():
    """**A justificação de não recusar, medida.** Recusar o que passa o que
    cada meio recebeu era a defesa mais forte — e nesta fatura fecha a porta:
    o cliente devolve o açaí de 10,20 € e NENHUM dos meios chega
    (dinheiro 5,00, Glovo 19,14... e com a fatura de 11,29 € da reprodução,
    5,00 e 6,29). Uma nota de crédito credita LINHAS, e as mesmas linhas não
    se creditam duas vezes: não há como partir a devolução em duas notas.

    Este teste guarda a DECISÃO, não o código: mostra que existe uma
    devolução legítima para a qual nenhum meio chega, e é por isso que o
    servidor mostra em vez de recusar."""
    venda = _venda_faturada()
    venda["pagamentos"] = [
        {"tipo_pagamento_id": "tipo-dinheiro", "nome": "Dinheiro",
         "tipo_fiscal": "NU", "valor": 5.00},
        {"tipo_pagamento_id": "tipo-glovo", "nome": "Glovo",
         "tipo_fiscal": "OU", "valor": 6.29},
    ]
    pagamentos = nc_mod.pagamentos_da_fatura(venda, [])
    devolucao = 10.20
    assert all(
        nc_mod.acima_do_recebido(pagamentos, {"id": p["tipo_pagamento_id"],
                                              "nome": p["nome"]}, devolucao) > 0
        for p in pagamentos
    )


# --- 13. A saída da NOTA PRESA ----------------------------------------------
#
# Uma intenção fica `reservada` sempre que a rota morre entre o `insert` e o
# `$set` final — um reinício, um deploy, o 409 da corrida. E o fecho recusa
# enquanto ela existir: medido, três tentativas seguidas de fechar a caixa,
# 409 sempre, e nenhuma rota de backoffice sobre `fat_notas_credito`.

_GESTOR = {"user_id": "u-1", "email": "gestor@lisbonb.com"}


def _nota_presa(**over):
    n = {
        "id": "33333333-3333-4333-8333-333333333333", "loja_id": "loja-1",
        "caixa_id": "caixa-1", "sessao_id": "sessao-1", "documento_id": "doc-1",
        "estado": "reservada", "total": 10.20, "numero_origem": "FS 05P2026/1824",
        "ext_ref": "pos-loja-1-sessao-1-nc-33333333-3333-4333-8333-333333333333",
        "criada_em": "2020-01-01T00:00:00+00:00", "linhas": [],
        "motivo": "Cliente devolveu o açaí.",
        "devolucao": {"tipo_pagamento_id": "tipo-dinheiro", "nome": "Dinheiro",
                      "tipo_fiscal": "NU", "valor": 10.20},
    }
    n.update(over)
    return n


def test_a_nota_presa_APARECE_ao_gestor_com_o_que_ele_precisa(monkeypatch):
    db = _db_nc(notas=[_nota_presa()])
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    presas = _corre(nc_mod.listar_notas_credito_presas(_=_GESTOR))
    assert len(presas) == 1
    presa = presas[0]
    assert presa["ext_ref"].endswith("nc-33333333-3333-4333-8333-333333333333")
    assert presa["numero_origem"] == "FS 05P2026/1824"
    assert presa["total"] == 10.20
    assert presa["presa_ha_segundos"] > 0
    assert presa["emissao_talvez_a_decorrer"] is False


def test_uma_nota_EMITIDA_nunca_aparece_nessa_lista(monkeypatch):
    """O controlo: a lista é das PRESAS. Uma nota que saiu não tem nada a ser
    resolvido — e uma lista que a mostrasse convidava o gestor a apagar a
    intenção de um documento fiscal real."""
    db = _db_nc(notas=[_nota_presa(estado="emitida"), _nota_presa(
        id="44444444-4444-4444-8444-444444444444", estado="incerta")])
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    assert _corre(nc_mod.listar_notas_credito_presas(_=_GESTOR)) == []


def test_libertar_SEM_confirmar_no_vendus_e_recusado_e_diz_o_que_ir_ver(monkeypatch):
    """Libertar uma nota que SAIU é autorizar uma segunda nota real da mesma
    devolução. Um clique distraído não pode chegar aqui."""
    db = _db_nc(notas=[_nota_presa()])
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    with pytest.raises(HTTPException) as erro:
        _corre(nc_mod.libertar_nota_credito_presa(
            _nota_presa()["id"], nc_mod.PedidoLibertarNota(), gestor=_GESTOR))
    assert erro.value.status_code == 422
    assert "procure a referência externa" in erro.value.detail
    assert db[COLECOES["notas_credito"]]._documentos  # nada foi apagado


def test_libertar_COM_confirmacao_apaga_a_intencao_e_DESTRANCA_o_fecho(monkeypatch):
    db = _db_nc(notas=[_nota_presa()])
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)
    sessao = db[COLECOES["sessoes_caixa"]]._documentos[0]

    assert _corre(caixa_mod._nota_de_credito_em_curso(db, sessao)) is not None
    saida = _corre(nc_mod.libertar_nota_credito_presa(
        _nota_presa()["id"],
        nc_mod.PedidoLibertarNota(confirmado_no_vendus=True, nota="Não está lá."),
        gestor=_GESTOR))
    assert saida["libertada"] is True
    assert db[COLECOES["notas_credito"]]._documentos == []
    assert _corre(caixa_mod._nota_de_credito_em_curso(db, sessao)) is None


def test_libertar_uma_nota_que_JA_TEM_documento_e_recusado(monkeypatch):
    """A confirmação humana pode estar errada, e há coisas que a máquina sabe
    melhor."""
    presa = _nota_presa()
    db = _db_nc(notas=[presa], documentos=[_documento_fs(), {
        "id": "doc-nc", "tipo": "NC", "loja_id": "loja-1",
        "numero": "NC 05P2026/9", "atcud": "ATCUD-NC-9",
        "ext_ref": presa["ext_ref"]}])
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    with pytest.raises(HTTPException) as erro:
        _corre(nc_mod.libertar_nota_credito_presa(
            presa["id"], nc_mod.PedidoLibertarNota(confirmado_no_vendus=True),
            gestor=_GESTOR))
    assert erro.value.status_code == 409
    assert "NC 05P2026/9" in erro.value.detail
    assert db[COLECOES["notas_credito"]]._documentos


def test_uma_nota_RECENTE_nao_se_mexe(monkeypatch):
    """Dentro da janela de uma emissão normal ela pode estar a falar com o
    Vendus NESTE instante — e nenhum gestor consegue ter confirmado o Vendus
    dentro dela."""
    agora = datetime.now(timezone.utc).isoformat()
    db = _db_nc(notas=[_nota_presa(criada_em=agora)])
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    for chamada in (
        nc_mod.libertar_nota_credito_presa(
            _nota_presa()["id"],
            nc_mod.PedidoLibertarNota(confirmado_no_vendus=True), gestor=_GESTOR),
        nc_mod.marcar_nota_credito_por_apurar(
            _nota_presa()["id"], nc_mod.PedidoLibertarNota(), gestor=_GESTOR),
    ):
        with pytest.raises(HTTPException) as erro:
            _corre(chamada)
        assert erro.value.status_code == 409
        assert "NESTE instante" in erro.value.detail


def test_marcar_POR_APURAR_destranca_o_fecho_sem_apagar_nada(monkeypatch):
    """A saída SEGURA, para quando a nota está no Vendus ou não se apura: ela
    continua a travar novo crédito das mesmas linhas, continua a não descontar
    a gaveta, e deixa de travar o fecho."""
    presa = _nota_presa()
    db = _db_nc(notas=[presa])
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)
    sessao = db[COLECOES["sessoes_caixa"]]._documentos[0]

    saida = _corre(nc_mod.marcar_nota_credito_por_apurar(
        presa["id"], nc_mod.PedidoLibertarNota(nota="Vi a NC 2026/9 no Vendus."),
        gestor=_GESTOR))
    assert saida["por_apurar"] is True
    guardada = db[COLECOES["notas_credito"]]._documentos[0]
    assert guardada["estado"] == "incerta"
    assert "Vi a NC 2026/9 no Vendus." in guardada["incerta_porque"]
    assert _corre(caixa_mod._nota_de_credito_em_curso(db, sessao)) is None
    # E continua a travar o crédito das mesmas linhas.
    assert ja_creditado_por_linha([guardada]) == ja_creditado_por_linha([presa])


def test_resolver_uma_nota_que_JA_NAO_esta_presa_nao_faz_nada(monkeypatch):
    db = _db_nc(notas=[_nota_presa(estado="emitida")])
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    with pytest.raises(HTTPException) as erro:
        _corre(nc_mod.marcar_nota_credito_por_apurar(
            _nota_presa()["id"], nc_mod.PedidoLibertarNota(), gestor=_GESTOR))
    assert erro.value.status_code == 409
    assert "já não está presa" in erro.value.detail


def test_a_mensagem_do_fecho_NOMEIA_a_saida_que_existe():
    """Sem a última frase, a loja lia «espere alguns segundos», esperava, e
    levava 409 outra vez, sem fim — com UM PC por loja, o turno não fechava e
    ninguém tinha botão.

    **E a morada tem de ser a REAL.** Ela dizia «na lista de notas de crédito
    presas do backoffice» — uma lista que não existia em ecrã nenhum. Agora
    nomeia o caminho que o gestor percorre com o rato: Faturação → Reservas
    Fiscais Presas, e o cartão lá dentro."""
    mensagem = caixa_mod._MSG_FECHO_COM_NOTA_DE_CREDITO_EM_CURSO
    assert "Reservas Fiscais Presas" in mensagem
    assert "Notas de Crédito Presas" in mensagem


def test_as_rotas_da_nota_presa_sao_de_GESTAO_e_existem():
    caminhos = [r.path for r in nc_mod.router.routes]
    assert "/fiscal/notas-credito-presas" in caminhos
    assert "/fiscal/notas-credito/{intencao_id}/libertar" in caminhos
    assert "/fiscal/notas-credito/{intencao_id}/por-apurar" in caminhos


def test_quem_le_o_SALDO_e_e_ultrapassado_antes_de_ler_as_NOTAS_perde(monkeypatch):
    """**A ORDEM das duas leituras é a garantia, e é ela que este guarda
    prende.**

    O selo lê-se ANTES das notas, e quem reserva mexe no selo DEPOIS de gravar
    a intenção. Isso deixa exactamente duas ordens possíveis para quem chega a
    seguir, e as duas acabam bem: ou ele já vê a intenção nas notas (e leva a
    recusa normal do travão), ou ainda não a viu — e então também ainda não
    viu o selo mexido, e a escrita condicional dele falha.

    Invertida a ordem (as notas primeiro, o selo depois), abre-se o buraco: um
    pedido pode ler as notas VAZIAS, ser ultrapassado por inteiro, e só depois
    ler o selo JÁ MEXIDO — validando contra um retrato velho e ganhando a
    escrita condicional com o valor novo. Duas notas de crédito reais da mesma
    fatura.

    Aqui a corrida não se deixa ao acaso: o segundo pedido é suspenso no
    instante exacto entre as duas leituras, o primeiro corre até ao fim, e só
    então ele continua."""
    db = _db_nc()
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    original = nc_mod._notas_do_documento
    chegou = asyncio.Event()
    seguir = asyncio.Event()

    async def _com_pausa(db_, documento_id):
        notas = await original(db_, documento_id)
        if not chegou.is_set():
            chegou.set()
            await seguir.wait()
        return notas

    monkeypatch.setattr(nc_mod, "_notas_do_documento", _com_pausa)

    async def cenario():
        atrasado = asyncio.ensure_future(emitir_nota_credito(
            "doc-1",
            _pedido_da_fatura_inteira("22222222-2222-4222-8222-222222222222"),
            operador=_operador()))
        await chegou.wait()
        primeiro = await emitir_nota_credito(
            "doc-1",
            _pedido_da_fatura_inteira("11111111-1111-4111-8111-111111111111"),
            operador=_operador())
        seguir.set()
        return primeiro, (await asyncio.gather(atrasado, return_exceptions=True))[0]

    primeiro, segundo = _corre(cenario())
    assert primeiro["numero"]
    assert isinstance(segundo, HTTPException) and segundo.status_code == 409
    assert len([d for d in db[COLECOES["documentos"]]._documentos
                if d["tipo"] == "NC"]) == 1
    assert sum(len(v.chamadas_criar) for v in VendusNCFalso.instancias) == 1


# --- o NIF da devolução: a nota desconta no cliente da FATURA -----------------

def test_a_nota_leva_o_NIF_da_FATURA_que_corrige(monkeypatch):
    """Sem isto, a devolução nunca descontava do que o cliente gastou.

    O ecrã de Clientes lista documentos com NIF e desconta os de `tipo: "NC"`
    — mas nenhuma nota de crédito levava NIF, e esse ramo era código morto: um
    açaí comprado e devolvido continuava a contar inteiro na ficha da pessoa.
    """
    db = _db_nc(documentos=[_documento_fs(cliente_nif="517542510")])
    _emitir(db, monkeypatch)

    nc = [d for d in db[COLECOES["documentos"]]._documentos if d.get("tipo") == "NC"]
    assert len(nc) == 1
    assert nc[0]["cliente_nif"] == "517542510"


def test_a_nota_de_uma_fatura_SEM_NIF_tambem_fica_sem_NIF(monkeypatch):
    """Consumidor Final devolve: não se inventa um cliente para a nota."""
    db = _db_nc(documentos=[_documento_fs()])
    _emitir(db, monkeypatch)

    nc = [d for d in db[COLECOES["documentos"]]._documentos if d.get("tipo") == "NC"]
    assert nc[0]["cliente_nif"] is None


def test_o_NIF_da_nota_sai_do_DOCUMENTO_e_nao_da_venda(monkeypatch):
    """Os dois deviam dizer o mesmo. Quando discordarem, manda a FATURA: a
    nota tem de descontar no MESMO cliente a quem a fatura somou.

    Pela venda, uma divergência punha o total de um cliente a descer e o de
    outro a ficar inflacionado — e nenhum dos dois números parecia errado."""
    db = _db_nc(
        documentos=[_documento_fs(cliente_nif="517542510")],
        vendas=[_venda_faturada(cliente_nif="295258144")],
    )
    _emitir(db, monkeypatch)

    nc = [d for d in db[COLECOES["documentos"]]._documentos if d.get("tipo") == "NC"]
    assert nc[0]["cliente_nif"] == "517542510", "manda a fatura, não a venda"
