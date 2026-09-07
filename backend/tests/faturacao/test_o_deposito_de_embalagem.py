"""**O depósito de embalagem (SDR)** — a caução que a lei manda cobrar.

0,10 € por embalagem de plástico ou metal com menos de 3 litros, discriminada
em linha separada e **não sujeita a tributação** (artigo 30.º-E do Decreto-Lei
n.º 152-D/2017). Obrigatório desde 10 de abril de 2026.

As três propriedades que este ficheiro guarda, e que são as que custam dinheiro
ou credibilidade se partirem:

1. **A caução não é receita.** Entra na gaveta, sai da facturação.
2. **A caução não leva desconto.** Descontar uma caução é devolver ao cliente
   dinheiro que ainda é dele.
3. **O que já foi vendido não muda** porque alguém mexeu na configuração.
"""
import pytest

from faturacao.dashboard import _valor_documento
from faturacao.deposito import (
    TITULO, VALOR_LEGAL, embalagens_da_venda, linha_do_deposito,
    linhas_do_deposito, valor_do_deposito,
)
from faturacao.fiscal import _itens_vendus
from faturacao.precos import CODIGO_NAO_SUJEITO

REF = "345983786"   # o artigo de depósito real da conta Vendus do dono


def _linha(nome, preco, tax="INT", qtd=1, deposito=None, **extra):
    li = {
        "id": "l-" + nome, "produto_id": "p-" + nome, "produto_nome": nome,
        "produto_preco": preco, "produto_tax_id": tax, "quantidade": qtd,
        "opcoes": [], "respostas_texto": [],
    }
    if deposito is not None:
        li["deposito_unitario"] = deposito
    li.update(extra)
    return li


def _venda(*linhas, **extra):
    v = {"id": "v1", "loja_id": "loja-1", "sessao_id": "s1", "linhas": list(linhas)}
    v.update(extra)
    return v


# --- contar embalagens --------------------------------------------------------

def test_conta_QUANTIDADES_e_nao_linhas():
    """Três águas numa linha só são três embalagens. Contar linhas cobrava
    0,10 € a quem levou três garrafas."""
    v = _venda(_linha("Água", 1.45, qtd=3, deposito=0.10))
    assert embalagens_da_venda(v) == 3
    assert valor_do_deposito(v) == 0.30


def test_uma_conta_REPARTIDA_leva_a_fracao_que_lhe_toca():
    """Repartir por três grava quantidades fraccionárias (0,3337). A caução
    reparte-se com o resto — cobrar 0,10 a cada um dos três por uma garrafa
    era cobrar 0,30 por uma embalagem."""
    v = _venda(_linha("Água", 1.45, qtd=0.3333, deposito=0.10))
    assert embalagens_da_venda(v) == 0.3333
    assert valor_do_deposito(v) == 0.03


def test_um_produto_SEM_carimbo_nao_conta():
    assert embalagens_da_venda(_venda(_linha("Açaí", 8.99))) == 0
    assert valor_do_deposito(_venda(_linha("Açaí", 8.99))) == 0.0


def test_uma_conta_VAZIA_nao_rebenta():
    assert embalagens_da_venda(None) == 0
    assert embalagens_da_venda({}) == 0
    assert valor_do_deposito(None) == 0.0


def test_o_valor_vem_do_CARIMBO_e_nao_da_configuracao_de_hoje():
    """Uma conta aberta ontem fecha-se ao valor a que foi aberta. Ler a
    configuração de agora fazia o total mudar debaixo do cliente."""
    v = _venda(_linha("Água", 1.45, qtd=2, deposito=0.08))
    assert valor_do_deposito(v) == 0.16, "usou o valor de hoje em vez do carimbado"


# --- a linha que viaja para o Vendus ------------------------------------------

def test_a_linha_e_NAO_SUJEITO_e_nao_isento():
    """`ISE` é isento (dentro do imposto, taxa zero). `NS` é fora do imposto.
    A diferença é o que o SAF-T lê."""
    linha = linha_do_deposito(2, 0.10, REF)
    assert linha["tax_id"] == CODIGO_NAO_SUJEITO
    assert linha["tax_id"] != "ISE"


def test_a_linha_leva_o_ARTIGO_do_Vendus():
    assert linha_do_deposito(1, 0.10, REF)["id"] == 345983786


def test_uma_referencia_que_nao_presta_NAO_vai():
    """Mandar ao Vendus um `id` que ele não reconheça arrisca a recusa do
    documento INTEIRO com o cliente à frente. Sem `id` ele cria um artigo —
    feio, e nunca impeditivo."""
    for lixo in (None, "", "  ", "VDEP63-26061226", "-3", "0", "abc"):
        assert "id" not in linha_do_deposito(1, 0.10, lixo), lixo


def test_sem_embalagens_NAO_ha_linha_nenhuma():
    """Uma fatura de dois açaís não pode levar uma linha de depósito a zero."""
    assert linha_do_deposito(0, 0.10, REF) is None
    assert linhas_do_deposito(_venda(_linha("Açaí", 8.99))) == []


def test_a_linha_NAO_TEM_por_onde_levar_desconto():
    """A garantia é a assinatura da função, não uma guarda que se possa
    esquecer de aplicar: não há parâmetro de desconto."""
    import inspect
    assert set(inspect.signature(linha_do_deposito).parameters) == {
        "quantidade", "valor", "vendus_ref"}
    assert "discount_percentage" not in linha_do_deposito(1, 0.10, REF)
    assert "discount_amount" not in linha_do_deposito(1, 0.10, REF)


def test_dois_valores_diferentes_dao_DUAS_linhas():
    """O carimbo é por linha. Se o valor for afinado a meio de uma conta
    aberta, somar tudo a um preço só cobrava um valor que nunca existiu."""
    v = _venda(_linha("Água", 1.45, deposito=0.10),
               _linha("Cola", 1.90, deposito=0.15))
    linhas = linhas_do_deposito(v, REF)
    assert [l["gross_price"] for l in linhas] == [0.10, 0.15]
    assert [l["qty"] for l in linhas] == [1, 1]


# --- na fatura, ao lado das outras linhas ------------------------------------

def test_o_deposito_e_a_ULTIMA_linha_da_fatura():
    """Em linha separada do preço do produto, como a lei exige — e no fim,
    que é onde o Vendus a põe e onde o cliente a procura."""
    v = _venda(_linha("Açaí", 8.99), _linha("Água", 1.45, deposito=0.10))
    itens = _itens_vendus(v, REF)
    assert len(itens) == 3
    assert itens[-1]["title"] == TITULO
    assert itens[-1]["tax_id"] == CODIGO_NAO_SUJEITO


def test_o_DESCONTO_GLOBAL_nao_toca_no_deposito():
    """A propriedade que mais custa se partir: o desconto distribui-se pelas
    linhas dos produtos e a caução fica inteira. 50% de desconto sobre uma
    conta com uma água não pode devolver 0,05 € de caução ao cliente."""
    v = _venda(_linha("Açaí", 10.00), _linha("Água", 2.00, deposito=0.10),
               desconto_global_pct=50)
    deposito = [i for i in _itens_vendus(v, REF) if i["title"] == TITULO][0]
    assert deposito["gross_price"] == 0.10
    assert "discount_percentage" not in deposito
    produtos = [i for i in _itens_vendus(v, REF) if i["title"] != TITULO]
    assert all(i.get("discount_percentage") for i in produtos), (
        "o desconto tinha de ter caído nos produtos")


def test_uma_conta_sem_bebidas_sai_EXACTAMENTE_como_saía():
    """A esmagadora maioria das contas. Nada muda para elas."""
    v = _venda(_linha("Açaí", 8.99))
    assert _itens_vendus(v, REF) == _itens_vendus(v)
    assert len(_itens_vendus(v, REF)) == 1


# --- o dinheiro ---------------------------------------------------------------

def test_a_caucao_NAO_E_RECEITA():
    """O `total` do documento traz a caução lá dentro — o Vendus soma-a como
    soma tudo. Na facturação ela sai: é dinheiro do cliente à guarda da loja."""
    doc = {"total": 10.10, "deposito": 0.10, "tipo": "FS"}
    assert _valor_documento(doc, "total") == 10.00


def test_um_documento_ANTIGO_sem_o_campo_vale_o_que_valia():
    """Nenhum documento anterior a isto cobrou depósito. Nada muda para eles
    — e um `None` não pode virar uma subtracção de nada."""
    assert _valor_documento({"total": 10.00, "tipo": "FS"}, "total") == 10.00
    assert _valor_documento({"total": 10.00, "deposito": None, "tipo": "FS"}, "total") == 10.00


def test_a_NOTA_DE_CREDITO_tambem_desconta_a_caucao_devolvida():
    """Uma devolução que credite o depósito tem de o tirar dos dois lados —
    senão creditar uma fatura inteira deixava a caução na receita, negativa."""
    doc = {"total": 10.10, "deposito": 0.10, "tipo": "NC"}
    assert _valor_documento(doc, "total") == -10.00


def test_um_documento_ANULADO_continua_a_valer_zero():
    doc = {"total": 10.10, "deposito": 0.10, "tipo": "FS", "anulado": True}
    assert _valor_documento(doc, "total") == 0.0


def test_o_valor_legal_e_dez_centimos():
    assert VALOR_LEGAL == 0.10


# --- o Z: a caução dita por extenso ------------------------------------------

def _venda_emitida(*linhas, dinheiro):
    return {
        "id": "v1", "estado": "emitida", "linhas": list(linhas),
        "pagamentos": [{"tipo_pagamento_id": "t-nu", "nome": "Dinheiro",
                        "tipo_fiscal": "NU", "valor": dinheiro}],
        "desconto_global_pct": None, "desconto_global_eur": None,
    }


def _resumo(*vendas):
    from faturacao import caixa as caixa_mod
    return caixa_mod._resumo_do_turno(
        {"id": "sessao-1", "fundo": 50.00}, [], list(vendas), [])


def test_o_Z_DIZ_quanto_cobrou_de_caucao():
    """A caução está no `total_faturado` (é dinheiro que entrou) e não está na
    facturação do painel (não é receita). Os dois números são os dois certos
    e, lado a lado sem legenda, produzem uma leitura falsa. Esta é a legenda.
    """
    resumo = _resumo(_venda_emitida(
        _linha("Açaí", 8.99), _linha("Água", 1.45, qtd=2, deposito=0.10),
        dinheiro=11.89))
    assert resumo["depositos"] == 0.20


def test_o_Z_traz_o_campo_MESMO_a_zero():
    """Sempre presente, como o `pagamentos_por_registar`: quem desenha não
    pode ter de adivinhar se a ausência quer dizer «não se cobrou» ou «esta
    versão do servidor não sabe responder a isso»."""
    resumo = _resumo(_venda_emitida(_linha("Açaí", 8.99), dinheiro=8.99))
    assert resumo["depositos"] == 0.0


def test_uma_venda_POR_EMITIR_nao_conta_caucao_nenhuma():
    """Uma conta aberta na gaveta ainda não cobrou nada a ninguém."""
    venda = _venda_emitida(_linha("Água", 1.45, deposito=0.10), dinheiro=1.55)
    venda["estado"] = "aberta"
    assert _resumo(venda)["depositos"] == 0.0


def test_a_caucao_do_Z_esta_DENTRO_do_dinheiro_esperado():
    """A propriedade que fecha as contas do papel: o depósito é dinheiro que
    entrou na gaveta, e a operadora tem de o ter lá."""
    resumo = _resumo(_venda_emitida(
        _linha("Água", 1.45, deposito=0.10), dinheiro=1.55))
    assert resumo["depositos"] == 0.10
    assert resumo["esperado"] == 51.55, "50 de fundo + 1,55 cobrados"
