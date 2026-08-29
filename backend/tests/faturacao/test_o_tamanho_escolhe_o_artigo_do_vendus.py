"""**Cada tamanho de açaí é um artigo diferente no Vendus.**

Palavra do dono: «hoje temos somente um produto açaí (pois a personalização é
dentro do produto), só que no Vendus são produtos diferentes — e hoje estão
todos a ser faturados no Açaí Regular».

É verdade e está medido: em produção o produto «Açaí» tem `vendus_ref`
145268982 e o tamanho é um grupo de personalização com quatro opções (Mini
5,85 €, Small 7,20 €, Regular 8,99 €, Supreme 14,10 €). Todas as linhas
viajavam com a referência do PRODUTO, portanto todas caíam no mesmo artigo.

**O dinheiro sempre esteve certo** — o `gross_price` é o nosso e o Vendus
respeita-o. O que estava errado era o artigo, e isso estraga tudo o que se
pergunta ao catálogo do Vendus: quantos Supremes se venderam, que margem dá
o Mini, que stock baixar.

A regra: **só um grupo de VARIANTE desvia o artigo.** Um tamanho É outro
artigo; um topping é o mesmo artigo com mais uma coisa lá dentro. Sem esta
restrição, ligar a Nutella ao artigo dela para efeitos de stock passava a
facturar o açaí inteiro como «Nutella».
"""
import pytest

from faturacao.precos import id_vendus_da_variante, linha_de_venda

ACAI = {"id": "p-acai", "nome": "Açaí", "preco": 0.0, "tax_id": "INT",
        "vendus_ref": "145268982"}


def _opcao(nome, preco, grupo, ref=None):
    o = {"id": "o-" + nome.lower(), "nome": nome, "preco": preco,
         "nome_grupo": grupo}
    if ref is not None:
        o["vendus_ref"] = ref
    return o


# --- a escolha do artigo, sozinha -------------------------------------------

def test_o_tamanho_com_referencia_devolve_o_artigo_dele():
    assert id_vendus_da_variante(
        [_opcao("Supreme", 14.10, "Tamanho", "171258999")]) == 171258999


def test_um_TOPPING_com_referencia_NAO_desvia_o_artigo():
    """A restrição que impede o pior caso. O grupo «Toppings» não é de
    variante — a Nutella não é outro açaí, é o mesmo açaí com Nutella."""
    assert id_vendus_da_variante(
        [_opcao("Nutella", 1.0, "Toppings", "999999999")]) is None


def test_o_tamanho_SEM_referencia_nao_desvia_nada():
    """O estado do dia do deploy: o grupo existe, as ligações ainda não estão
    feitas. Tem de continuar a facturar como facturava — nunca a falhar."""
    assert id_vendus_da_variante([_opcao("Mini", 5.85, "Tamanho")]) is None


def test_uma_referencia_que_nao_e_um_INTEIRO_POSITIVO_nao_vai():
    """A mesma guarda do produto, e é a mesma função: um `id` que o Vendus não
    reconheça arrisca a recusa do documento INTEIRO com o cliente à frente."""
    for lixo in ("", "  ", "abc", "-3", "12.5", None):
        assert id_vendus_da_variante([_opcao("Mini", 5.85, "Tamanho", lixo)]) is None, lixo


def test_o_grupo_de_variante_reconhece_se_pelo_nome_com_acentos_e_maiusculas():
    for grupo in ("Tamanho", "TAMANHO", "Tamanhos", "Tamanho do açaí", "Size"):
        assert id_vendus_da_variante(
            [_opcao("Mini", 5.85, grupo, "171258472")]) == 171258472, grupo


def test_sem_opcoes_nenhumas_nao_rebenta():
    assert id_vendus_da_variante(None) is None
    assert id_vendus_da_variante([]) is None


# --- a linha inteira, que é o que viaja para o Vendus ------------------------

def test_a_linha_do_MINI_vai_com_o_artigo_do_Mini_e_nao_com_o_do_produto():
    linha = linha_de_venda(ACAI, 1, [_opcao("Mini", 5.85, "Tamanho", "171258472")])
    assert linha["id"] == 171258472, "o Mini foi facturado no artigo do produto"
    assert linha["gross_price"] == 5.85


def test_a_linha_do_SUPREME_vai_com_o_artigo_do_Supreme():
    linha = linha_de_venda(ACAI, 1, [_opcao("Supreme", 14.10, "Tamanho", "171258999")])
    assert linha["id"] == 171258999
    assert linha["gross_price"] == 14.10


def test_dois_tamanhos_com_referencia_diferente_dao_artigos_DIFERENTES():
    """O teste que o defeito não passava: a mesma linha, o mesmo produto, e o
    artigo a mudar com o tamanho. Antes, os dois davam 145268982."""
    mini = linha_de_venda(ACAI, 1, [_opcao("Mini", 5.85, "Tamanho", "171258472")])
    sup = linha_de_venda(ACAI, 1, [_opcao("Supreme", 14.10, "Tamanho", "171258999")])
    assert mini["id"] != sup["id"]


def test_sem_ligacao_no_tamanho_a_linha_volta_ao_artigo_do_PRODUTO():
    """O caminho de sempre, intacto. É o que garante que o deploy não muda
    nada até o dono fazer as ligações no backoffice."""
    linha = linha_de_venda(ACAI, 1, [_opcao("Regular", 8.99, "Tamanho")])
    assert linha["id"] == 145268982


def test_o_TOPPING_nao_rouba_o_artigo_ao_tamanho():
    """Uma linha real: tamanho + toppings, e só o tamanho manda."""
    linha = linha_de_venda(ACAI, 1, [
        _opcao("Mini", 5.85, "Tamanho", "171258472"),
        _opcao("Nutella", 1.0, "Toppings", "999999999"),
    ])
    assert linha["id"] == 171258472
    assert linha["gross_price"] == 6.85


def test_o_titulo_e_o_preco_NAO_mudam_com_a_referencia():
    """O `id` liga a linha ao artigo certo e mais nada — está provado contra a
    conta real. Se ele passasse a mandar no título ou no preço, a fatura
    deixava de dizer o que o cliente comprou."""
    com = linha_de_venda(ACAI, 2, [_opcao("Mini", 5.85, "Tamanho", "171258472")])
    sem = linha_de_venda(ACAI, 2, [_opcao("Mini", 5.85, "Tamanho")])
    assert com["title"] == sem["title"]
    assert com["gross_price"] == sem["gross_price"] == 5.85
    assert com["qty"] == sem["qty"] == 2
    assert com["tax_id"] == sem["tax_id"]
