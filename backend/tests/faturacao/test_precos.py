"""Preços, IVA e linhas de venda — lógica pura, sem I/O.

Modelo: um produto pertence a uma categoria (Venda ao Público ou Vendas Aplicações)
e tem UM preço e UM IVA — como no Vendus (spec D7).
"""
import pytest

from faturacao.precos import erros_do_produto, linha_de_venda, tax_id_de_taxa


def _produto(**over):
    p = {"id": "p1", "nome": "Açaí Regular", "preco": 8.99, "tax_id": "INT"}
    p.update(over)
    return p


# --- IVA -------------------------------------------------------------------

def test_taxas_conhecidas():
    assert tax_id_de_taxa(23) == "NOR"
    assert tax_id_de_taxa(13) == "INT"
    assert tax_id_de_taxa(6) == "RED"
    assert tax_id_de_taxa(0) == "ISE"


def test_taxa_desconhecida_nao_inventa_nada():
    """A app antiga devolvia INT por omissão. Aqui devolve None: quem chama decide,
    e o produto fica marcado como incompleto em vez de sair a 13% em silêncio."""
    assert tax_id_de_taxa(17) is None
    assert tax_id_de_taxa(None) is None
    assert tax_id_de_taxa("treze") is None


# --- Validação -------------------------------------------------------------

def test_produto_completo_nao_tem_erros():
    assert erros_do_produto(_produto()) == []


def test_produto_sem_iva_tem_erro():
    p = _produto()
    del p["tax_id"]
    assert erros_do_produto(p) == ["Sem IVA definido"]


def test_produto_sem_preco_tem_erro():
    p = _produto()
    del p["preco"]
    assert erros_do_produto(p) == ["Sem preço definido"]


def test_produto_sem_preco_nem_iva():
    assert erros_do_produto({"nome": "X"}) == ["Sem preço definido", "Sem IVA definido"]


def test_produto_com_tax_id_desconhecido_tem_erro():
    """MINOR: `erros_do_produto` só verificava que `tax_id` existe, não que é
    um dos códigos válidos do Vendus (NOR/INT/RED/ISE) — o ecrã 'Produtos
    sem IVA' apoia-se nesta função para avisar ANTES da venda."""
    assert erros_do_produto(_produto(tax_id="XPTO")) == ["Código de IVA desconhecido: XPTO"]


def test_preco_zero_e_valido():
    """Um artigo a 0,00€ (ex.: 'Incluído') é legítimo — o que não pode é faltar o campo."""
    assert erros_do_produto(_produto(preco=0)) == []


# --- Linha de venda --------------------------------------------------------

def test_linha_simples():
    li = linha_de_venda(_produto(), 2)
    assert li == {"title": "Açaí Regular", "qty": 2, "gross_price": 8.99, "tax_id": "INT"}


def test_linha_com_opcoes_soma_ao_preco_unitario():
    """As personalizações entram no preço unitário da linha, como a app já faz em
    produção — e não como linhas separadas na fatura."""
    opcoes = [{"nome": "Nutella", "preco": 0.95}, {"nome": "Banana", "preco": 0.0}]
    li = linha_de_venda(_produto(), 1, opcoes=opcoes)
    assert li["gross_price"] == 9.94
    assert li["title"] == "Açaí Regular (Nutella, Banana)"


def test_linha_recusa_produto_sem_iva():
    p = _produto()
    del p["tax_id"]
    with pytest.raises(ValueError) as e:
        linha_de_venda(p, 1)
    assert "IVA" in str(e.value)


def test_linha_recusa_produto_sem_preco():
    p = _produto()
    del p["preco"]
    with pytest.raises(ValueError) as e:
        linha_de_venda(p, 1)
    assert "preço" in str(e.value)


def test_override_de_preco_e_de_iva():
    li = linha_de_venda(_produto(), 1, preco_override=7.5, tax_override="NOR")
    assert li["gross_price"] == 7.5
    assert li["tax_id"] == "NOR"


def test_override_de_iva_invalido_e_recusado():
    """O diálogo do produto no POS deixa a operadora forçar o IVA de uma
    linha — esse valor tem de passar pelo mesmo crivo do IVA do produto,
    senão um 'XPTO' escrito à mão sai para o Vendus sem validação nenhuma."""
    with pytest.raises(ValueError) as e:
        linha_de_venda(_produto(), 1, tax_override="XPTO")
    assert "IVA" in str(e.value)


def test_override_de_iva_none_usa_o_iva_do_produto():
    li = linha_de_venda(_produto(tax_id="RED"), 1, tax_override=None)
    assert li["tax_id"] == "RED"


def test_override_de_preco_zero_e_respeitado():
    """0 é um preço, não é 'vazio'. Um `if preco_override:` daria 8,99 aqui."""
    assert linha_de_venda(_produto(), 1, preco_override=0)["gross_price"] == 0.0


def test_desconto_em_euros_tem_precedencia_sobre_percentagem():
    """O Vendus só aceita um dos dois por linha. O € ganha, como na Pizzaria."""
    li = linha_de_venda(_produto(), 1, desconto_pct=10, desconto_eur=2)
    assert li["discount_amount"] == 2.0
    assert "discount_percentage" not in li


def test_desconto_em_percentagem():
    li = linha_de_venda(_produto(), 1, desconto_pct=10)
    assert li["discount_percentage"] == 10.0
    assert "discount_amount" not in li


def test_quantidade_zero_conta_como_um():
    assert linha_de_venda(_produto(), 0)["qty"] == 1


# --- Precisão dos valores (o cêntimo que não pode desaparecer) -------------
#
# round(2.675, 2) == 2.67 e round(8.995, 2) == 8.99 — o arredondamento
# bancário do Python sobre a representação binária come um cêntimo sem
# ninguém dar por isso. A defesa é recusar à entrada qualquer valor com mais
# de 2 casas decimais: se tudo o que entra tem no máximo 2 casas, a soma
# exacta também tem 2 casas e o round(x, 2) final recupera-a sem perda.

def test_preco_base_do_produto_com_3_casas_e_recusado():
    with pytest.raises(ValueError) as e:
        linha_de_venda(_produto(preco=8.995), 1)
    assert "8.995" in str(e.value)


def test_preco_override_com_3_casas_e_recusado():
    with pytest.raises(ValueError) as e:
        linha_de_venda(_produto(), 1, preco_override=8.995)
    assert "8.995" in str(e.value)


def test_preco_de_opcao_com_3_casas_e_recusado():
    opcoes = [{"nome": "Nutella", "preco": 0.995}]
    with pytest.raises(ValueError) as e:
        linha_de_venda(_produto(), 1, opcoes=opcoes)
    assert "0.995" in str(e.value)


def test_desconto_eur_com_3_casas_e_recusado():
    with pytest.raises(ValueError) as e:
        linha_de_venda(_produto(), 1, desconto_eur=2.005)
    assert "2.005" in str(e.value)


@pytest.mark.parametrize("preco", [8.99, 8.9, 9, 0, 0.0])
def test_precos_com_ate_2_casas_sao_aceites(preco):
    """8,99 / 8,9 / 9 / 0 / 0.0 têm no máximo 2 casas decimais (ou nenhuma) e
    não podem ser recusados — só o que passa dos 2 é problema."""
    li = linha_de_venda(_produto(preco=preco), 1)
    assert li["gross_price"] == round(float(preco), 2)


@pytest.mark.parametrize("preco", [8.99, 8.9, 9, 0, 0.0])
def test_precos_de_opcao_com_ate_2_casas_sao_aceites(preco):
    opcoes = [{"nome": "Extra", "preco": preco}]
    li = linha_de_venda(_produto(), 1, opcoes=opcoes)
    assert li["gross_price"] == round(8.99 + float(preco), 2)


@pytest.mark.parametrize("desconto", [8.99, 8.9, 5, 0, 0.0])
def test_desconto_eur_com_ate_2_casas_e_aceite(desconto):
    """9 (int) saiu desta lista de propósito: o produto de teste custa 8,99€,
    e 9€ de desconto numa linha de 8,99€ é EXACTAMENTE o caso que o tecto do
    desconto (ver os testes abaixo) passou a recusar — ficou coberto lá, não
    aqui."""
    li = linha_de_venda(_produto(), 1, desconto_eur=desconto)
    if desconto:
        assert li["discount_amount"] == round(float(desconto), 2)
    else:
        assert "discount_amount" not in li


# --- Tecto do desconto em euros (buraco achado no Plano 2B, Task 3) --------
#
# Nada impedia um desconto_eur maior do que o valor da própria linha — o que
# produzia uma linha com discount_amount > gross_price*qty, ou seja, uma
# linha NEGATIVA numa fatura real: uma nota de crédito escondida dentro de
# uma fatura. O tecto é o próprio bruto da linha (preço unitário × quantidade,
# já com as personalizações somadas) — igual ao que venda.py::_bruto_da_linha
# calcula a partir desta mesma linha.

def test_desconto_eur_maior_que_o_bruto_da_linha_e_recusado():
    with pytest.raises(ValueError) as e:
        linha_de_venda(_produto(preco=8.99), 1, desconto_eur=9.00)
    assert "9.0" in str(e.value) or "9.00" in str(e.value)


def test_desconto_eur_maior_que_o_bruto_com_quantidade_e_recusado():
    """O tecto é sobre a linha INTEIRA (preço × quantidade), não só o preço
    unitário — um desconto de 15€ é legítimo em 2 unidades a 8,99€ (bruto
    17,98€) mas não seria legítimo numa só."""
    with pytest.raises(ValueError):
        linha_de_venda(_produto(preco=8.99), 1, desconto_eur=15.00)


def test_desconto_eur_maior_que_o_bruto_com_2_unidades_e_aceite():
    li = linha_de_venda(_produto(preco=8.99), 2, desconto_eur=15.00)
    assert li["discount_amount"] == 15.00


def test_desconto_eur_igual_ao_bruto_da_linha_e_aceite():
    """Igual ao bruto é legítimo (linha a zero, ex.: brinde) — só o que
    ULTRAPASSA o bruto é que produz uma linha negativa."""
    li = linha_de_venda(_produto(preco=8.99), 1, desconto_eur=8.99)
    assert li["discount_amount"] == 8.99


def test_desconto_eur_maior_que_o_bruto_com_opcoes_considera_o_extra():
    """O tecto tem de incluir o preço das personalizações, não só o preço
    base do produto — senão um desconto que já era maior do que o produto
    sozinho, mas cabia no produto+extras, era recusado por engano."""
    opcoes = [{"nome": "Nutella", "preco": 0.95}]
    li = linha_de_venda(_produto(preco=8.99), 1, opcoes=opcoes, desconto_eur=9.94)
    assert li["discount_amount"] == 9.94
