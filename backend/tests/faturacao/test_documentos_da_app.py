"""**Uma fatura da app aberta no ecrã de Documentos.**

O detalhe monta-se a partir da venda. Estes documentos não têm venda nenhuma, e
o ecrã não pode ler essa ausência como "esta fatura não levou nada" — pior,
`total_divergente` compara o total com a soma das linhas e acendia um aviso de
fatura estragada numa fatura sã.

**A FORMA importa tanto como os números.** As linhas e o mapa de imposto saem na
mesma resposta que o ecrã já desenha (`FatDocumentos.js`): a coluna «Produto» lê
`titulo`, e `totais_do_mapa` soma a chave `total` de cada linha do mapa a
direito. Um dicionário com outros nomes não dá erro nenhum no servidor — dá uma
tabela em branco e um 500 ao abrir a fatura, que é o género de defeito que só
aparece com o ecrã à frente.
"""
import asyncio

import pytest

from faturacao.documentos import _detalhe_do_documento

LINHA = {"qty": 1, "title": "Açaí Mini",
         "amounts": {"gross_total": "6.85", "net_total": "6.06"},
         "tax": {"id": "INT", "rate": 13}}

DOC = {"id": "abc", "numero": "FS 06P2026/446", "atcud": "J6SHGSNX-446",
       "tipo": "FS", "modo": "normal", "total": 6.85, "total_bruto": 6.85,
       "total_liquido": 6.06, "emitido_em": "2026-09-01T13:43:25+00:00",
       "loja_id": "loja-app", "venda_id": None, "origem": "app",
       "linhas_vendus": [LINHA]}


class _DBSemVenda:
    """O mínimo de Mongo que o detalhe usa: um `find_one` que nunca encontra.

    Não é preguiça do teste — é o retrato do caso: a fatura da app não tem
    venda, não tem caixa e não tem operador, e as três leituras que o detalhe
    faz voltam mesmo vazias em produção.
    """

    def __getitem__(self, _coleccao):
        return self

    async def find_one(self, *_args, **_kwargs):
        return None


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_as_linhas_da_app_aparecem_no_detalhe():
    d = _corre(_detalhe_do_documento(_DBSemVenda(), DOC))
    assert len(d["linhas"]) == 1
    # `titulo` e não outro nome qualquer: é a chave que a coluna «Produto» do
    # ecrã lê (FatDocumentos.js), a mesma de `_linhas_da_fatura`. Com outra, a
    # fatura abria com a linha lá e o nome do artigo em branco.
    assert d["linhas"][0]["titulo"] == "Açaí Mini"


def test_a_linha_traz_o_dinheiro_e_a_taxa_que_o_ecra_desenha():
    linha = _corre(_detalhe_do_documento(_DBSemVenda(), DOC))["linhas"][0]
    assert linha["total"] == 6.85
    assert linha["quantidade"] == 1
    assert linha["preco_unitario"] == 6.85
    assert linha["taxa"] == 13


def test_o_preco_unitario_de_uma_linha_com_varias_unidades():
    """O Vendus manda o dinheiro da LINHA. O «P. Unit.» é o que o cliente pagou
    por cada um — e não o total repetido, que numa linha de três se lia como
    triplo do preço."""
    doc = dict(DOC, linhas_vendus=[{
        "qty": 2, "title": "Água 50cl",
        "amounts": {"gross_total": "3.00", "net_total": "2.44"},
        "tax": {"id": "NOR", "rate": 23}}])
    linha = _corre(_detalhe_do_documento(_DBSemVenda(), doc))["linhas"][0]
    assert linha["preco_unitario"] == 1.50
    assert linha["total"] == 3.00


def test_o_total_nao_aparece_divergente():
    # `total_divergente` compara o total com a soma das linhas. Sem as linhas
    # da app, o ecrã acendia um aviso de fatura estragada numa fatura sã.
    d = _corre(_detalhe_do_documento(_DBSemVenda(), DOC))
    assert d["total_divergente"] is False
    assert d["total_das_linhas"] == 6.85


def test_o_mapa_de_imposto_da_app_nao_vem_vazio():
    d = _corre(_detalhe_do_documento(_DBSemVenda(), DOC))
    assert d["mapa_imposto"] == [{"tax_id": "INT", "taxa": 13, "documentos": 1,
                                  "base": 6.06, "iva": 0.79, "total": 6.85}]


def test_os_totais_do_imposto_batem_com_o_documento():
    """`totais_do_mapa` soma `linha["total"]` a direito — um mapa sem essa
    chave levantava `KeyError` e a fatura abria com um 500. E somado do MAPA
    ERRADO (o da venda que não existe) dava 0,00 € por baixo de uma tabela com
    6,85 €."""
    d = _corre(_detalhe_do_documento(_DBSemVenda(), DOC))
    assert d["totais_imposto"] == {"base": 6.06, "iva": 0.79, "total": 6.85}


def test_duas_taxas_dao_duas_linhas_no_mapa():
    doc = dict(DOC, total=9.85, linhas_vendus=[
        LINHA,
        {"qty": 2, "title": "Água 50cl",
         "amounts": {"gross_total": "3.00", "net_total": "2.44"},
         "tax": {"id": "NOR", "rate": 23}}])
    d = _corre(_detalhe_do_documento(_DBSemVenda(), doc))
    assert [(l["taxa"], l["total"]) for l in d["mapa_imposto"]] == [(13, 6.85), (23, 3.00)]
    assert d["totais_imposto"]["total"] == 9.85
    assert d["total_divergente"] is False


def test_sem_net_total_o_iva_nao_e_o_total_inteiro():
    """Uma linha sem a base do Vendus decompõe-se pelo código de imposto — a
    fórmula do Z (`mapa_imposto._base_em_centimos`). Sem isto, `base = 0` fazia
    o IVA valer a fatura inteira."""
    doc = dict(DOC, linhas_vendus=[{
        "qty": 1, "title": "Açaí Mini", "amounts": {"gross_total": "6.85"},
        "tax": {"id": "INT", "rate": 13}}])
    linha = _corre(_detalhe_do_documento(_DBSemVenda(), doc))["mapa_imposto"][0]
    assert linha["base"] == 6.06
    assert linha["iva"] == 0.79


@pytest.mark.parametrize("sinal", [1, -1],
                         ids=["a api devolve positivo", "a api devolve negativo"])
def test_a_nota_de_credito_da_app_nao_acende_o_aviso(sinal):
    """O sinal de uma NC lida do Vendus não é nosso — a API tanto a devolve
    negativa como positiva, e a casa já o documenta e testa nos dois sentidos
    (`relatorios._artigos_das_linhas_vendus`). Com a comparação por sinal, uma
    nota sã acendia «a soma das linhas não bate com o total do documento».
    """
    nota = dict(DOC, tipo="NC", total=6.85, linhas_vendus=[{
        "qty": sinal, "title": "Açaí Mini",
        "amounts": {"gross_total": "%.2f" % (sinal * 6.85),
                    "net_total": "%.2f" % (sinal * 6.06)},
        "tax": {"id": "INT", "rate": 13}}])
    d = _corre(_detalhe_do_documento(_DBSemVenda(), nota))
    assert d["total_divergente"] is False


def test_um_total_que_nao_bate_continua_a_acender_o_aviso():
    """O aviso não se apagou — só deixou de olhar para o sinal."""
    doc = dict(DOC, total=9.99)
    assert _corre(_detalhe_do_documento(_DBSemVenda(), doc))["total_divergente"] is True


def test_a_origem_diz_app_e_nao_pos():
    d = _corre(_detalhe_do_documento(_DBSemVenda(), DOC, com_contexto=True))
    assert d["origem"] == "App L'Açaí"
    assert d["operador_nome"] is None
    assert d["caixa_nome"] is None


def test_nao_ha_talao_para_reimprimir():
    d = _corre(_detalhe_do_documento(_DBSemVenda(), DOC))
    assert d["tem_talao"] is False


def test_uma_fatura_do_pos_continua_a_montar_se_pela_venda():
    """A guarda é `venda is None and linhas_vendus`, e o `venda is None` tem de
    estar lá: um documento NOSSO que ganhasse `linhas_vendus` um dia passava a
    ignorar a venda — os toppings, o desconto e o operador desapareciam do
    ecrã (a mesma guarda, e a mesma razão, de `relatorios.py`)."""
    class _DBComVenda(_DBSemVenda):
        async def find_one(self, filtro=None, *_a, **_k):
            if (filtro or {}).get("id") == "v-1":
                return {"id": "v-1", "estado": "emitida", "linhas": [{
                    "produto_nome": "Açaí Supremo", "produto_preco": 10.20,
                    "produto_tax_id": "INT", "quantidade": 1}]}
            return None

    # Sem `origem: "app"` — é um documento do POS, e o rótulo sai do DOCUMENTO
    # e não da venda: uma fatura da app é da app mesmo que um dia se lhe
    # encoste uma conta.
    doc = dict(DOC, venda_id="v-1", total=10.20, origem=None,
               linhas_vendus=[LINHA])
    d = _corre(_detalhe_do_documento(_DBComVenda(), doc, com_contexto=True))
    assert d["linhas"][0]["titulo"] == "Açaí Supremo"
    assert d["linhas"][0]["preco_unitario"] == 10.20
    assert d["origem"] == "POS"
