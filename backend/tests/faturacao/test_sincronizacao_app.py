"""**Quem entra e quem fica de fora** — as contas puras da sincronização das
faturas da app, sem Mongo e sem rede.

Os casos não são inventados: são os documentos que estavam mesmo na Caixa
Online do Vendus a 2026-09-04, lidos em produção. Os cinco orçamentos de
740,15 € são a razão de este ficheiro existir — uma regra que só olhasse para o
prefixo `pos-` importava-os como receita.
"""
from faturacao.sincronizacao_app import (
    E_NOSSO,
    TIPOS_ACEITES,
    deve_importar,
    estado_do_vendus,
)


def _doc(**campos):
    base = {"id": 370665072, "type": "FS", "status": "N",
            "external_reference": "LA00028", "amount_gross": "6.85"}
    base.update(campos)
    return base


def test_a_fatura_da_app_entra():
    entra, motivo = deve_importar(_doc())
    assert entra is True, motivo


def test_uma_fatura_nossa_fica_de_fora():
    entra, motivo = deve_importar(_doc(external_reference="pos-abc-def-ghi"))
    assert entra is False
    assert "pos" in motivo


def test_um_orcamento_de_740_euros_nao_e_facturacao():
    # O caso real: 5 destes na Caixa Online, 3.582,10 € que nunca foram vendas.
    entra, motivo = deve_importar(
        _doc(type="OT", external_reference="", amount_gross="740.15"))
    assert entra is False
    assert "OT" in motivo


def test_um_recibo_nao_entra_porque_o_dinheiro_ja_foi_contado():
    entra, motivo = deve_importar(_doc(type="RG", external_reference=""))
    assert entra is False
    assert "RG" in motivo


def test_uma_nota_de_credito_da_app_entra():
    entra, _ = deve_importar(_doc(type="NC", external_reference="LA00031"))
    assert entra is True


def test_um_tipo_que_o_vendus_invente_amanha_fica_de_fora_sozinho():
    entra, motivo = deve_importar(_doc(type="XPTO"))
    assert entra is False
    assert "XPTO" in motivo


def test_um_documento_anulado_nao_entra():
    entra, motivo = deve_importar(_doc(status="A"))
    assert entra is False
    assert "anulad" in motivo.lower()


def test_o_estado_le_se_na_lista_e_no_detalhe():
    # Na lista o Vendus manda a string; no GET por id manda o dicionário.
    assert estado_do_vendus({"status": "N"}) == "N"
    assert estado_do_vendus({"status": {"id": "A", "date": "..."}}) == "A"
    assert estado_do_vendus({}) is None


def test_uma_fatura_de_teste_nunca_entra():
    entra, motivo = deve_importar(_doc(number="FS T06P2026/3"))
    assert entra is False
    assert "teste" in motivo.lower()


def test_uma_fatura_a_mao_sem_referencia_entra_na_mesma():
    # Receita real da Caixa Online que não é nossa: entra, e o log avisa.
    entra, _ = deve_importar(_doc(external_reference=""))
    assert entra is True


def test_so_fs_e_nc():
    assert TIPOS_ACEITES == frozenset({"FS", "NC"})


def test_e_nosso_nao_se_engana_com_none():
    assert E_NOSSO("pos-abc") is True
    assert E_NOSSO("LA00028") is False
    assert E_NOSSO(None) is False
    assert E_NOSSO("") is False
