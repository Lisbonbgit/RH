"""**«Não sujeito» não é IVA a 0%** — e a diferença é o que o SAF-T lê.

`ISE` é isento: está DENTRO do imposto, com taxa zero, e entra na base
tributável. `NS` é o que fica FORA. O único uso que tem cá é o depósito de
embalagem, que por lei «não está sujeito a tributação» (artigo 30.º-E do
Decreto-Lei n.º 152-D/2017).

Se o depósito entrar na base tributável, o Z que a operadora assina e a
declaração que vai para a Autoridade Tributária passam a declarar imposto
sobre uma caução — dinheiro que não é nosso e que o cliente pode reaver.
"""
import pytest

from faturacao.mapa_imposto import (
    _mapa_dos_documentos, rotulo_da_taxa, totais_do_mapa,
)
from faturacao.precos import (
    CODIGO_NAO_SUJEITO, _CODIGOS_IVA_VALIDOS, erros_do_produto, tax_id_de_taxa,
)


# --- o código em si -----------------------------------------------------------

def test_o_NS_nao_e_uma_taxa_e_nenhuma_percentagem_o_devolve():
    """Se `tax_id_de_taxa(0)` devolvesse `NS`, um produto isento passava a
    facturar fora do imposto sem ninguém ter escolhido isso."""
    for taxa in (0, 6, 13, 23, 0.0, "0"):
        assert tax_id_de_taxa(taxa) != CODIGO_NAO_SUJEITO, taxa
    assert tax_id_de_taxa(0) == "ISE", "o isento é que é a taxa de 0%"


def test_o_NS_NAO_e_um_codigo_de_IVA_de_um_PRODUTO():
    """A lista de códigos do catálogo não o inclui — é ela que o backoffice
    usa para validar a ficha do produto."""
    assert CODIGO_NAO_SUJEITO not in _CODIGOS_IVA_VALIDOS


def test_um_produto_com_NS_e_recusado_e_DIZ_PORQUE(monkeypatch):
    """Recusado, e com a razão à frente. «Código de IVA desconhecido» mandava
    procurar um erro de escrita; NS não é desconhecido, é um código real do
    Vendus usado no sítio errado."""
    erros = erros_do_produto({"preco": 1.0, "tax_id": CODIGO_NAO_SUJEITO})
    assert len(erros) == 1
    assert "depósito" in erros[0].lower(), erros
    assert "desconhecido" not in erros[0].lower(), erros


def test_um_codigo_ESTRAGADO_continua_a_dizer_desconhecido():
    """A mensagem nova é só para o NS. Um `XPTO` continua a ser o que era."""
    erros = erros_do_produto({"preco": 1.0, "tax_id": "XPTO"})
    assert "desconhecido" in erros[0].lower(), erros


@pytest.mark.parametrize("codigo", ["NOR", "INT", "RED", "ISE"])
def test_os_codigos_de_sempre_continuam_a_passar(codigo):
    assert erros_do_produto({"preco": 1.0, "tax_id": codigo}) == []


# --- o mapa de imposto --------------------------------------------------------

def test_o_nao_sujeito_fica_FORA_da_base_tributavel():
    """A propriedade que interessa toda. 10 € a 13% e 0,10 € de depósito: a
    base tributável é a dos 10 €, e o depósito conta só no total."""
    mapa = _mapa_dos_documentos([{"INT": 1000, CODIGO_NAO_SUJEITO: 10}])
    totais = totais_do_mapa(mapa)

    linha_ns = next(l for l in mapa if l["tax_id"] == CODIGO_NAO_SUJEITO)
    assert linha_ns["base"] is None and linha_ns["iva"] is None
    assert linha_ns["total"] == 0.10

    linha_int = next(l for l in mapa if l["tax_id"] == "INT")
    assert linha_int["base"] == 8.85 and linha_int["iva"] == 1.15

    assert totais["base"] == 8.85, "o depósito entrou na base tributável"
    assert totais["iva"] == 1.15
    assert totais["total"] == 10.10, "o depósito tem de contar no total"


def test_o_ISENTO_e_diferente_do_NAO_SUJEITO():
    """Os dois valem imposto zero e são coisas distintas: o isento TEM base
    (está dentro do imposto), o não sujeito não."""
    mapa = _mapa_dos_documentos([{"ISE": 500, CODIGO_NAO_SUJEITO: 500}])
    ise = next(l for l in mapa if l["tax_id"] == "ISE")
    ns = next(l for l in mapa if l["tax_id"] == CODIGO_NAO_SUJEITO)

    assert ise["base"] == 5.00 and ise["iva"] == 0.0
    assert ns["base"] is None
    assert totais_do_mapa(mapa)["base"] == 5.00, "só o isento é base tributável"


def test_a_devolucao_do_deposito_cancela_o_deposito_ao_centimo():
    """Uma nota de crédito entra com cêntimos negativos. Creditar o depósito
    por inteiro tem de o pôr exactamente a zero — não a −0,00 nem a um resto."""
    mapa = _mapa_dos_documentos([
        {CODIGO_NAO_SUJEITO: 30}, {CODIGO_NAO_SUJEITO: -30}])
    assert next(l for l in mapa if l["tax_id"] == CODIGO_NAO_SUJEITO)["total"] == 0.0


# --- o rótulo -----------------------------------------------------------------

def test_o_rotulo_do_nao_sujeito_nao_e_um_ponto_de_interrogacao():
    """`?` é o rótulo de uma taxa que o sistema NÃO conhece, e isso é um
    aviso. Escrever o depósito assim mandava a contabilista procurar um
    defeito onde está a lei."""
    assert rotulo_da_taxa({"tax_id": CODIGO_NAO_SUJEITO, "taxa": None}) == "N/Sujeito"


def test_o_rotulo_de_uma_taxa_DESCONHECIDA_continua_a_avisar():
    assert rotulo_da_taxa({"tax_id": "XPTO", "taxa": None}) == "?"
    assert rotulo_da_taxa({"tax_id": None, "taxa": None}) == "?"


@pytest.mark.parametrize("taxa,esperado", [(23, "23%"), (13, "13%"), (6, "6%"), (0, "0%")])
def test_o_rotulo_de_uma_taxa_normal_e_a_percentagem(taxa, esperado):
    assert rotulo_da_taxa({"tax_id": "INT", "taxa": taxa}) == esperado
