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


# --- Task 3: traduzir o documento do Vendus para o formato de `fat_documentos` ---

import pytest

from faturacao.sincronizacao_app import documento_para_gravar
from faturacao.vendus.emissao import VendusRespostaIlegivel

LOJA = "98331284-ba8d-41b8-b074-4059902d68a9"

# O documento como o Vendus o devolveu mesmo, lido em produção a 2026-09-04.
FS_446 = {
    "id": 370665072, "type": "FS", "number": "FS 06P2026/446",
    "atcud": "J6SHGSNX-446", "date": "2026-09-01",
    "local_time": "2026-09-01 14:43:25",
    "status": {"id": "N", "date": "2026-09-01 13:43:25"},
    "amount_gross": "6.85", "amount_net": "6.06",
    "external_reference": "LA00028",
    "client": {"name": "Matheus Augusto Flores de Moraes", "fiscal_id": "244772903"},
    "items": [{"qty": 1, "title": "Açaí Mini",
               "amounts": {"gross_total": "6.85", "net_total": "6.06"},
               "tax": {"id": "INT", "rate": 13}}],
}


def test_traz_os_dois_totais_porque_o_liquido_nao_tem_alternativa():
    d = documento_para_gravar(FS_446, LOJA)
    assert d["total_bruto"] == 6.85
    assert d["total_liquido"] == 6.06
    assert d["total"] == 6.85


def test_o_numero_vem_do_vendus_e_o_modo_e_sempre_normal():
    # Provado por mutação: trocar "numero" por None ou "modo" por "tests"
    # deixava a suite toda verde — nenhum teste prendia nenhum dos dois.
    d = documento_para_gravar(FS_446, LOJA)
    assert d["numero"] == "FS 06P2026/446"
    assert d["modo"] == "normal"


def test_um_total_ilegivel_levanta_em_vez_de_gravar_none_para_sempre():
    # `_valor_monetario` devolvia `None` em silêncio para um `amount_gross`
    # presente mas ilegível — e um documento gravado com `total: None` fica
    # assim PARA SEMPRE, porque os índices únicos de `atcud` e
    # `vendus_document_id` impedem uma segunda tentativa. `_total_do_documento`
    # (a mesma que `_normaliza_documento` usa) tem de levantar tipado, para
    # quem chama tratar a leitura como incerta e tentar outra vez.
    cru = dict(FS_446, amount_gross="seis euros")
    with pytest.raises(VendusRespostaIlegivel):
        documento_para_gravar(cru, LOJA)


def test_a_hora_e_a_do_vendus_e_sai_em_utc_com_offset():
    d = documento_para_gravar(FS_446, LOJA)
    # 14:43 de Lisboa em Setembro (UTC+1) são 13:43 UTC.
    assert d["emitido_em"].startswith("2026-09-01T13:43:25")
    assert d["emitido_em"].endswith("+00:00"), "um Z parte os filtros por string"
    assert "Z" not in d["emitido_em"]


def test_guarda_a_loja_a_origem_e_as_linhas():
    d = documento_para_gravar(FS_446, LOJA)
    assert d["loja_id"] == LOJA
    assert d["origem"] == "app"
    assert d["linhas_vendus"][0]["title"] == "Açaí Mini"


def test_nao_tem_venda_nem_talao():
    d = documento_para_gravar(FS_446, LOJA)
    assert d["venda_id"] is None
    assert "talao_escpos" not in d


def test_o_id_e_nosso_e_o_do_vendus_fica_a_parte():
    d = documento_para_gravar(FS_446, LOJA)
    assert d["vendus_document_id"] == 370665072
    assert d["id"] != 370665072
    assert len(d["id"]) == 36, "uuid nosso — é por ele que o ecrã abre o documento"


def test_copia_o_nif_do_cliente():
    d = documento_para_gravar(FS_446, LOJA)
    assert d["cliente_nif"] == "244772903"


def test_um_consumidor_final_nao_leva_nif_de_tracinhos():
    cru = dict(FS_446, client={"name": "Consumidor Final", "fiscal_id": "---------"})
    assert documento_para_gravar(cru, LOJA)["cliente_nif"] is None


def test_uma_referencia_vazia_grava_none_e_nunca_string_vazia():
    # O índice de ext_ref é único parcial SOBRE STRINGS: dois "" colidem.
    cru = dict(FS_446, external_reference="")
    assert documento_para_gravar(cru, LOJA)["ext_ref"] is None


def test_sem_atcud_recusa_se_a_gravar():
    cru = dict(FS_446); cru.pop("atcud")
    with pytest.raises(ValueError, match="ATCUD"):
        documento_para_gravar(cru, LOJA)


def test_sem_id_do_vendus_recusa_se_a_gravar():
    cru = dict(FS_446); cru.pop("id")
    with pytest.raises(ValueError, match="id"):
        documento_para_gravar(cru, LOJA)


def test_uma_nota_de_credito_guarda_o_tipo_para_o_sinal_ficar_certo():
    cru = dict(FS_446, type="NC")
    assert documento_para_gravar(cru, LOJA)["tipo"] == "NC"


def test_sem_data_legivel_recusa_se_a_gravar():
    """**Recusar, e não cair no instante actual como o POS faz.**

    `_instante_do_vendus` devolve `None` quando nem `local_time` nem `date` se
    lêem, e a docstring dela diz «quem chama cai no instante actual» — é o que
    `fiscal.py:1196` faz (`bruto.get("emitido_em") or _agora()`). Aqui não
    pode ser, por duas razões medidas:

    - `emitido_em: None` gravava e o documento ficava INVISÍVEL para sempre:
      todos os filtros por intervalo comparam `emitido_em` (dashboard.py:498,
      relatorios.py:620), portanto ele não contava para janela nenhuma e
      desaparecia de todos os ecrãs de dinheiro, sem erro nenhum;
    - o instante actual punha a fatura no dia ERRADO — uma FS de 01/09 lida a
      05/09 ia para o dia 5 — e como `atcud` e `vendus_document_id` são
      índices únicos, nunca mais poderia ser regravada no dia certo.

    Recusar deixa-a de fora com um `assinalado` visível
    (`sincronizacao_rota._saltar`), e isso é recuperável.
    """
    sem_data = dict(FS_446)
    sem_data.pop("local_time")
    sem_data.pop("date")
    with pytest.raises(ValueError, match="data"):
        documento_para_gravar(sem_data, LOJA)


def test_uma_data_ilegivel_tambem_recusa():
    """`_instante_do_vendus` não levanta num valor ilegível: avisa no log e
    devolve `None`. Sem esta guarda, o `None` chegava intacto à gravação."""
    ilegivel = dict(FS_446, local_time="ontem à tarde", date="não sei")
    with pytest.raises(ValueError, match="data"):
        documento_para_gravar(ilegivel, LOJA)
