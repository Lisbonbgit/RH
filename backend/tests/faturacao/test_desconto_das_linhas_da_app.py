# -*- coding: utf-8 -*-
"""**O desconto da linha, nas faturas que a app L'Açaí emite.**

O Vendus manda, em cada linha de um documento lido, um `amounts.gross_total`
que é o valor ANTES do desconto e um `discounts.calculated_percentage` à parte.
Os dois leitores destas linhas — o motor dos Relatórios e o ecrã de Documentos
— liam o primeiro como se fosse o valor final e ignoravam o segundo.

**O que isso custava, em euros, em produção.** A `FS 06P2026/1081` é um resgate
de recompensa: um açaí de 5,85 € oferecido, 0,00 € cobrados. O documento está
gravado certo (`total_bruto: 0.0`), o Dashboard mostrava 0,00 € — e as NOVE
vistas dos Relatórios mostravam 5,85 € de receita que nunca existiu, enquanto o
ecrã de Documentos acendia `total_divergente` (0,00 € contra 5,85 €) a acusar de
estragada uma fatura sã. Numa app de fidelização, isto acontece todos os dias.

**A prova que este ficheiro exige é uma só: a soma das linhas tem de bater com
o `amount_gross` do documento**, ao cêntimo, nos dois documentos reais medidos.
É a mesma pergunta que `total_divergente` faz ao ecrã todos os dias — e é a
única que apanha, de uma vez, tanto o desconto esquecido como um desconto
contado a dobrar.

Os dois documentos foram lidos no Vendus a 2026-09-05 (`GET documents/{id}/`).
Os campos citados são os medidos; `qty`, `title` e o código de imposto da
`FS 1081` não vinham no excerto registado — a taxa de 13 % é a que o próprio
documento declara em `taxes`, e o título é o do artigo da recompensa.
"""
import asyncio

from faturacao.documentos import (
    _detalhe_do_documento, _linhas_das_linhas_vendus, _mapa_das_linhas_vendus,
)
from faturacao.relatorios import _artigos_das_linhas_vendus, centimos

# ---------------------------------------------------------------------------
# FS 06P2026/1081 (id 371939543) — o resgate de recompensa.
#
#   documento:  amount_gross "0.00"   amount_net "0.00"
#               discounts {"amount": "5.85", "total": "5.85"}
#               taxes [{"total": "0.00", "base": "0.00", "amount": "0.00",
#                       "rate": 13}]
#   item:       amounts {"net_unit": "5.18", "net_total": "5.18",
#                        "gross_unit": "5.85", "gross_total": "5.85"}
#               discounts {"calculated_percentage": 100}
# ---------------------------------------------------------------------------
LINHA_1081 = {
    "qty": 1, "title": "Açaí Mini",
    "amounts": {"net_unit": "5.18", "net_total": "5.18",
                "gross_unit": "5.85", "gross_total": "5.85"},
    "discounts": {"calculated_percentage": 100},
    "tax": {"id": "INT", "rate": 13},
}
FS_1081 = {
    "id": "uuid-1081", "numero": "FS 06P2026/1081", "atcud": "J6SHGSNX-1081",
    "tipo": "FS", "modo": "normal",
    # O que `sincronizacao_app.documento_para_gravar` grava do `amount_gross`.
    "total": 0.0, "total_bruto": 0.0, "total_liquido": 0.0,
    "emitido_em": "2026-09-05T13:00:00+00:00", "loja_id": "loja-app",
    "venda_id": None, "origem": "app", "linhas_vendus": [LINHA_1081],
}
AMOUNT_GROSS_1081 = 0.00

# ---------------------------------------------------------------------------
# FS 06P2026/446 (id 370665072) — uma venda paga normal.
#
#   documento:  amount_gross "6.85"   (sem `discounts`)
#   item:       amounts {..., "gross_total": "6.85"}   discounts null
# ---------------------------------------------------------------------------
LINHA_446 = {
    "qty": 1, "title": "Açaí Mini",
    "amounts": {"gross_total": "6.85", "net_total": "6.06"},
    "discounts": None,
    "tax": {"id": "INT", "rate": 13},
}
FS_446 = {
    "id": "uuid-446", "numero": "FS 06P2026/446", "atcud": "J6SHGSNX-446",
    "tipo": "FS", "modo": "normal",
    "total": 6.85, "total_bruto": 6.85, "total_liquido": 6.06,
    "emitido_em": "2026-09-01T13:43:25+00:00", "loja_id": "loja-app",
    "venda_id": None, "origem": "app", "linhas_vendus": [LINHA_446],
}
AMOUNT_GROSS_446 = 6.85

REAIS = ((FS_1081, AMOUNT_GROSS_1081), (FS_446, AMOUNT_GROSS_446))


class _DBSemVenda:
    """A fatura da app não tem venda, nem caixa, nem operador — e é mesmo isso
    que as leituras do detalhe encontram em produção."""

    def __getitem__(self, _coleccao):
        return self

    async def find_one(self, *_args, **_kwargs):
        return None


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ===========================================================================
# A prova de sanidade: soma das linhas == `amount_gross` do documento.
# ===========================================================================

def test_no_ecra_de_documentos_a_soma_das_linhas_bate_com_o_amount_gross():
    """Os dois documentos reais, ao cêntimo, pelo caminho do ecrã.

    Sem o desconto aplicado, a `FS 1081` soma 5,85 € de linhas contra um
    documento de 0,00 € — 5,85 € de diferença numa fatura que está certa.
    """
    for documento, amount_gross in REAIS:
        soma = sum(li["total"] for li in _linhas_das_linhas_vendus(documento))
        assert centimos(soma) == centimos(amount_gross), (
            "%s: as linhas somam %.2f € e o documento vale %.2f €"
            % (documento["numero"], soma, amount_gross)
        )


def test_o_total_divergente_nao_acende_em_nenhuma_das_duas_faturas_sas():
    """O mesmo, pelo detalhe inteiro — que é o que o dono vê.

    `total_divergente` é o aviso «esta fatura não está bem, veja-a no Vendus».
    Aceso numa fatura sã, ensina a ignorá-lo — e no dia em que houver uma
    fatura mesmo estragada ninguém olha.
    """
    for documento, amount_gross in REAIS:
        d = _corre(_detalhe_do_documento(_DBSemVenda(), documento))
        assert d["total_das_linhas"] == amount_gross, documento["numero"]
        assert d["total_divergente"] is False, documento["numero"]


def test_nos_relatorios_a_soma_dos_artigos_bate_com_o_amount_gross():
    """Os mesmos dois documentos, pelo motor das nove vistas dos Relatórios.

    É o número que o defeito inflacionava: 585 cêntimos de receita inventada
    por cada recompensa resgatada.
    """
    for documento, amount_gross in REAIS:
        artigos = _artigos_das_linhas_vendus(documento, {})
        soma_c = sum(a["bruto_c"] for a in artigos)
        assert soma_c == centimos(amount_gross), (
            "%s: os artigos somam %d cêntimos e o documento vale %d"
            % (documento["numero"], soma_c, centimos(amount_gross))
        )


# ===========================================================================
# O que cada ecrã passa a mostrar para a recompensa.
# ===========================================================================

def test_a_recompensa_aparece_como_desconto_e_nao_como_artigo_sem_preco():
    """5,85 € de preço, 5,85 € de desconto, 0,00 € a pagar.

    Com o `desconto` a zero (como estava), o ecrã escrevia um açaí que nunca
    teve preço em vez de um açaí que foi oferecido — o dinheiro batia certo e a
    tabela mentia na única coisa que se abre esta fatura para ver.
    """
    linha = _linhas_das_linhas_vendus(FS_1081)[0]
    assert linha["preco_unitario"] == 5.85
    assert linha["desconto"] == 5.85
    assert linha["total"] == 0.0
    assert linha["quantidade"] == 1.0


def test_o_mapa_de_imposto_da_recompensa_e_o_que_o_vendus_declarou():
    """O documento declara `taxes: base 0,00 / imposto 0,00 / total 0,00`.

    O `net_total` da linha (5,18 €) também é ANTERIOR ao desconto: descontar só
    o bruto punha o IVA a valer 0,00 − 5,18 = −5,18 € no mapa do ecrã — imposto
    NEGATIVO numa fatura sã.
    """
    mapa = _mapa_das_linhas_vendus(FS_1081)
    assert len(mapa) == 1
    assert mapa[0]["tax_id"] == "INT"
    assert mapa[0]["taxa"] == 13
    assert mapa[0]["total"] == 0.0
    assert mapa[0]["base"] == 0.0
    assert mapa[0]["iva"] == 0.0


def test_o_liquido_dos_relatorios_da_recompensa_tambem_e_zero():
    """`liquido_c` é a base sem IVA do que a linha vale. Zero a pagar, zero de
    base — e não os 518 cêntimos que o `net_total` da linha ainda diz."""
    artigo = _artigos_das_linhas_vendus(FS_1081, {})[0]
    assert artigo["bruto_c"] == 0
    assert artigo["liquido_c"] == 0


def test_a_venda_paga_nao_muda_um_centimo():
    """A `FS 446` não tem desconto nenhum (`discounts: null`) e tem de sair
    exactamente como saía — senão a correcção pagava-se com um defeito novo em
    todas as outras faturas."""
    linha = _linhas_das_linhas_vendus(FS_446)[0]
    assert (linha["preco_unitario"], linha["desconto"], linha["total"]) == (6.85, 0.0, 6.85)
    artigo = _artigos_das_linhas_vendus(FS_446, {})[0]
    assert artigo["bruto_c"] == 685
    mapa = _mapa_das_linhas_vendus(FS_446)
    assert (mapa[0]["total"], mapa[0]["base"], mapa[0]["iva"]) == (6.85, 6.06, 0.79)


# ===========================================================================
# O desconto do DOCUMENTO não se soma ao da linha.
# ===========================================================================

def test_o_desconto_do_documento_nao_se_conta_a_dobrar():
    """A `FS 1081` diz `discounts.amount = "5.85"` no documento E 100 % na
    linha: é o MESMO desconto, uma vez repartido e outra em rodapé.

    Descontar os dois dava −5,85 € numa fatura de 0,00 €. Este teste fixa que o
    documento traz esse campo e que ele NÃO entra na conta — e é ele que trava
    quem, a ler o payload, decidir «também há um desconto aqui, vamos aplicá-lo».
    """
    doc = dict(FS_1081, discounts={"amount": "5.85", "total": "5.85"})
    assert sum(li["total"] for li in _linhas_das_linhas_vendus(doc)) == 0.0
    assert sum(a["bruto_c"] for a in _artigos_das_linhas_vendus(doc, {})) == 0


# ===========================================================================
# As bordas, e a interacção que já lá estava.
# ===========================================================================

def test_uma_percentagem_parcial_usa_a_formula_do_vendus():
    """`bruto × (1 − pct/100)` arredondado ao cêntimo, linha a linha — a mesma
    de `_liquido_da_linha`. 10 % de 6,85 € deixa 6,17 €."""
    linha = dict(LINHA_446, discounts={"calculated_percentage": 10})
    doc = dict(FS_446, linhas_vendus=[linha])
    assert _linhas_das_linhas_vendus(doc)[0]["total"] == 6.17
    assert _artigos_das_linhas_vendus(doc, {})[0]["bruto_c"] == 617


def test_um_desconto_ilegivel_ou_ausente_vale_zero_por_cento():
    """Ilegível é o mesmo que ausente — a regra que estes leitores já seguem
    para tudo o que vem do Vendus. E um NaN não pode virar 100 % (a linha
    inteira de graça): passava incólume pelo `min`/`max` sem a guarda."""
    for descontos in (None, {}, [], "50", {"calculated_percentage": None},
                      {"calculated_percentage": "cem"},
                      {"calculated_percentage": float("nan")},
                      {"calculated_percentage": -50}):
        doc = dict(FS_446, linhas_vendus=[dict(LINHA_446, discounts=descontos)])
        assert _linhas_das_linhas_vendus(doc)[0]["total"] == 6.85, descontos


def test_uma_percentagem_acima_de_cem_nao_torna_a_linha_negativa():
    doc = dict(FS_446, linhas_vendus=[
        dict(LINHA_446, discounts={"calculated_percentage": 150})])
    assert _linhas_das_linhas_vendus(doc)[0]["total"] == 0.0


def test_o_abs_da_nota_de_credito_continua_a_ser_so_da_nota():
    """`_artigos_das_linhas_vendus` põe o valor em absoluto SÓ quando o tipo é
    `NC` — quem aplica o sinal é o `agregar`, pelo tipo do documento. Uma NC
    que anule uma recompensa credita ZERO (não havia nada a devolver), e uma NC
    normal continua a creditar o que sempre creditou."""
    nota_da_recompensa = dict(FS_1081, tipo="NC", linhas_vendus=[dict(
        LINHA_1081, qty=-1,
        amounts=dict(LINHA_1081["amounts"], gross_total="-5.85"))])
    a = _artigos_das_linhas_vendus(nota_da_recompensa, {})[0]
    assert (a["bruto_c"], a["quantidade"]) == (0, 1.0)

    nota_normal = dict(FS_446, tipo="NC", linhas_vendus=[dict(
        LINHA_446, qty=-1, amounts={"gross_total": "-6.85", "net_total": "-6.06"})])
    b = _artigos_das_linhas_vendus(nota_normal, {})[0]
    assert (b["bruto_c"], b["quantidade"]) == (685, 1.0)
