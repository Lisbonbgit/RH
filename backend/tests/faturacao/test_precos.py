"""Preços, IVA e linhas de venda — lógica pura, sem I/O.

Modelo: um produto pertence a uma categoria (Venda ao Público ou Vendas Aplicações)
e tem UM preço e UM IVA — como no Vendus (spec D7).
"""
import pytest

from faturacao.precos import (
    erros_do_produto,
    id_vendus_do_produto,
    linha_de_venda,
    tax_id_de_taxa,
)


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


def test_opcao_repetida_aparece_com_a_dose_no_titulo():
    nutella = {"nome": "Nutella", "preco": 0.95}
    linha = linha_de_venda({"nome": "Açaí Small", "preco": 7.20, "tax_id": "INT"},
                           1, [nutella, nutella, {"nome": "Morango", "preco": 0}])
    assert linha["title"] == "Açaí Small (Nutella 2×, Morango)"
    # duas doses pagas: 7,20 + 0,95 + 0,95
    assert linha["gross_price"] == 9.10


def test_a_ordem_do_titulo_e_a_da_primeira_escolha():
    """Agregar não pode reordenar: a operadora escolheu por uma ordem e o
    cliente lê essa ordem no talão.

    Os nomes estão AO CONTRÁRIO da ordem alfabética de propósito. Com
    "Morango" antes de "Nutella" — como este teste nasceu — a ordem da
    escolha e a ordem alfabética eram a mesma, e o teste ficava verde mesmo
    com o `for nome in ordem` trocado por `for nome in sorted(ordem)`: não
    havia mutação nenhuma que o pusesse vermelho, ou seja, não estava a
    defender coisa nenhuma. Trocados, é a ordem da escolha — e só ela — que
    o mantém verde."""
    a = {"nome": "Nutella", "preco": 0.95}
    b = {"nome": "Morango", "preco": 0}
    linha = linha_de_venda({"nome": "Açaí", "preco": 5.0, "tax_id": "INT"}, 1, [a, b, a])
    assert linha["title"] == "Açaí (Nutella 2×, Morango)"


def test_opcao_gratuita_de_grupo_escondido_nao_vai_ao_titulo():
    linha = linha_de_venda(
        {"nome": "Açaí", "preco": 5.0, "tax_id": "INT"}, 1,
        [{"nome": "Levar", "preco": 0, "sai_na_fatura": False},
         {"nome": "Nutella", "preco": 0.95}],
    )
    assert linha["title"] == "Açaí (Nutella)"
    assert linha["gross_price"] == 5.95


def test_opcao_PAGA_vai_ao_titulo_mesmo_com_o_interruptor_desligado():
    """O interruptor esconde o que não custa nada. Nunca um euro: o cliente
    está a ser cobrado por isto e a fatura tem de o dizer."""
    linha = linha_de_venda(
        {"nome": "Açaí", "preco": 5.0, "tax_id": "INT"}, 1,
        [{"nome": "Whey", "preco": 0.95, "sai_na_fatura": False}],
    )
    assert linha["title"] == "Açaí (Whey)"
    assert linha["gross_price"] == 5.95


def test_opcao_de_preco_NEGATIVO_vai_ao_titulo_mesmo_com_o_interruptor_desligado():
    """Um euro a menos também é um euro: o interruptor esconde o que não
    custa nada, e um desconto gravado como opção custa.

    Com o `> 0` de antes, esta opção contava como grátis: o título saía
    "Açaí" limpinho e o `gross_price` 4,00 € — a linha da Fatura
    Simplificada mais barata um euro do que o que lá está escrito, sem
    rasto nenhum de onde ele foi. O catálogo já não deixa gravar preços
    negativos (`ge=0`), mas as `opcoes` do pedido são `List[Dict]` cru e o
    `pos_catalogo` devolve o preço gravado sem o revalidar — uma opção
    negativa gravada antes dessa guarda ainda chega aqui."""
    linha = linha_de_venda(
        {"nome": "Açaí", "preco": 5.0, "tax_id": "INT"}, 1,
        [{"nome": "Desconto fidelidade", "preco": -1.00, "sai_na_fatura": False}],
    )
    assert linha["title"] == "Açaí (Desconto fidelidade)"
    assert linha["gross_price"] == 4.0


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


# --- O `id` do produto no Vendus (o catálogo que se enchia de órfãos) ------
#
# A linha saía só com o título. O Vendus não casa por nome: não encontrando
# referência, CRIA um produto novo e inventa-lhe um código `VACA…`. Medido na
# conta real: 95 produtos, 7 títulos repetidos, o "Açaí Mini" com 14 — um
# verdadeiro (id 171258472, com categoria) e 13 órfãos sem categoria nenhuma.
# A 5 lojas × ~200 vendas/dia isso são milhares de produtos por mês.
#
# Provado contra a conta real, em mode=tests: `{"id": 171258472, "qty": 1,
# "gross_price": 5.85, "tax_id": "INT"}` emitiu a FS T06P2026/17 sem criar
# produto nenhum; e com o NOSSO título e um preço DIFERENTE do do catálogo
# o documento saiu a 7,75 € (o nosso preço) e devolveu o nosso título —
# o `id` liga ao produto e não substitui nem o preço nem o título.

def test_linha_leva_o_id_do_produto_no_vendus():
    li = linha_de_venda(_produto(vendus_ref="171258472"), 1)
    assert li["id"] == 171258472


def test_id_vai_como_inteiro_e_nao_como_texto():
    """O corpo do documento vai em JSON e o que está provado contra a conta
    real é um INTEIRO. O `vendus_ref` guarda-se como texto (importacao.py faz
    `str(p["id"])`), por isso a conversão tem de acontecer aqui — um
    `"171258472"` entre aspas no corpo é outra coisa."""
    li = linha_de_venda(_produto(vendus_ref="171258472"), 1)
    assert isinstance(li["id"], int)
    assert li["id"] == 171258472


def test_produto_sem_vendus_ref_continua_a_poder_ser_vendido_e_nao_leva_o_campo():
    """Um artigo criado à mão no backoffice (nunca importado) não tem
    `vendus_ref`. A linha sai como saía até aqui e o Vendus cria o produto —
    feio, mas MUITO melhor do que recusar a venda: a operadora ficava com o
    cliente à frente sem poder cobrar."""
    li = linha_de_venda(_produto(), 1)
    assert "id" not in li
    assert li == {"title": "Açaí Regular", "qty": 1, "gross_price": 8.99, "tax_id": "INT"}


def test_vendus_ref_a_none_nao_manda_id_nulo():
    """Um `id: null` no corpo é pior do que campo nenhum — é um valor
    ENVIADO, e não um campo omitido."""
    li = linha_de_venda(_produto(vendus_ref=None), 1)
    assert "id" not in li


def test_vendus_ref_com_lixo_nao_vai_para_um_documento_fiscal():
    """Um `id` que o Vendus não reconheça arrisca a recusa do documento
    INTEIRO com o cliente à frente. Vale mais o produto órfão."""
    # O "\u00b2" está aqui de propósito: passa no `isdigit()` mas faz o `int()`
    # levantar ValueError — um erro cru a parar a venda ao balcão por causa
    # de um campo do catálogo. O "0" não é id de produto nenhum no Vendus.
    for lixo in ("", "   ", "abc", "VACA123", "-1", "8.7", "171258472x", "\u00b2", "0"):
        li = linha_de_venda(_produto(vendus_ref=lixo), 1)
        assert "id" not in li, lixo


def test_vendus_ref_com_espacos_a_mais_continua_a_ligar():
    li = linha_de_venda(_produto(vendus_ref="  171258472  "), 1)
    assert li["id"] == 171258472


def test_o_id_nao_mexe_em_nada_do_dinheiro():
    """A regra desta alteração: o `id` LIGA a linha ao produto e mais nada.
    Preço, IVA, título e desconto da linha com `vendus_ref` são, campo a
    campo, os mesmos da linha sem ele."""
    opcoes = [{"nome": "Nutella", "preco": 0.95}]
    sem = linha_de_venda(_produto(), 3, opcoes=opcoes, desconto_pct=10)
    com = linha_de_venda(_produto(vendus_ref="171258472"), 3, opcoes=opcoes, desconto_pct=10)
    assert com.pop("id") == 171258472
    assert com == sem


def test_o_id_nao_mexe_no_desconto_em_euros_nem_no_tecto():
    sem = linha_de_venda(_produto(), 1, desconto_eur=8.99)
    com = linha_de_venda(_produto(vendus_ref="171258472"), 1, desconto_eur=8.99)
    assert com.pop("id") == 171258472
    assert com == sem


def test_o_id_nao_mexe_nos_overrides_de_preco_e_de_iva():
    """O caso provado na conta real: o nosso preço (7,75 €) e o nosso título
    ganham ao do produto do catálogo, mesmo com o `id` presente."""
    li = linha_de_venda(
        _produto(vendus_ref="171258472", nome="Açaí Mini", preco=5.85),
        1,
        opcoes=[{"nome": "Nutella 2×", "preco": 1.90}],
        tax_override="NOR",
    )
    assert li == {
        "id": 171258472,
        "title": "Açaí Mini (Nutella 2×)",
        "qty": 1,
        "gross_price": 7.75,
        "tax_id": "NOR",
    }


def test_id_vendus_do_produto_isolado():
    """A função sozinha, para o defeito ficar nomeado num sítio só."""
    assert id_vendus_do_produto({"vendus_ref": "171258472"}) == 171258472
    assert id_vendus_do_produto({"vendus_ref": 171258472}) == 171258472
    assert id_vendus_do_produto({"vendus_ref": None}) is None
    assert id_vendus_do_produto({}) is None
    assert id_vendus_do_produto({"vendus_ref": "VACA123"}) is None
