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

    def criar_nota_credito(self, linhas, pagamentos, external_reference, register_id, motivo):
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
    Uma NC a dobrar é um documento fiscal a mais entregue à AT."""
    db = _db_nc()
    monkeypatch.setattr(nc_mod, "obter_db", lambda: db)
    pedido = _pedido()

    primeira = _corre(emitir_nota_credito("doc-1", pedido, operador=_operador()))
    segunda = _corre(emitir_nota_credito("doc-1", pedido, operador=_operador()))

    assert len(VendusNCFalso.instancias) == 1
    assert len(VendusNCFalso.instancias[0].chamadas_criar) == 1
    assert primeira["numero"] == segunda["numero"] == "NC 05P2026/12"
    assert db[COLECOES["notas_credito"]].chamadas_insert == 1


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
