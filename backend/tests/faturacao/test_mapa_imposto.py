"""O mapa de imposto do turno — taxa · nº de documentos · base · IVA · total.

O que estes testes existem para provar, e que ninguém tinha provado: **a
soma das bases mais a soma dos IVAs por taxa dá EXACTAMENTE o total dos
documentos da sessão**. É a única coisa que interessa num mapa de imposto —
se não bater, o que a contabilista declara não é o que a AT recebeu.

Os valores são escolhidos entre os que EXPÕEM a diferença, não entre os que
a escondem: 0,29 · 1,15 · 10,20 e os 8,99 divididos por três (3,00 · 3,00 ·
2,99). Três guardas anteriores deste módulo revelaram-se inúteis por terem
escolhido 0,30 e 8,50, que dão conta exacta em qualquer modo.
"""
from faturacao.mapa_imposto import mapa_de_imposto, totais_do_mapa
from faturacao.reparticao import quantidade_para
from faturacao.venda import _totais

# Os dois IVAs que se misturam na mesma conta no cardápio real: 13 % nos
# açaís, 23 % nos refrigerantes / brigadeiros / embalagem / entrega.
ACAI = "INT"
REFRI = "NOR"


def _linha(nome, preco, tax_id, quantidade=1, **extra):
    linha = {
        "id": "linha-%s" % nome,
        "produto_nome": nome,
        "produto_preco": preco,
        "produto_tax_id": tax_id,
        "quantidade": quantidade,
    }
    linha.update(extra)
    return linha


def _venda(linhas, **extra):
    venda = {
        "id": "venda-1",
        "estado": "emitida",
        "linhas": linhas,
        "desconto_global_pct": None,
        "desconto_global_eur": None,
    }
    venda.update(extra)
    return venda


def _por_taxa(mapa):
    return {linha["taxa"]: linha for linha in mapa}


def _soma_dos_documentos(vendas):
    """O total dos documentos da sessão pelo caminho INDEPENDENTE do mapa:
    `venda._totais`, que é o número contra o qual `fiscal.finalizar` validou
    a soma dos pagamentos antes de emitir. Se o mapa não der isto, o mapa
    está errado."""
    return round(
        sum(
            _totais(venda)["total"]
            for venda in vendas
            if venda.get("estado") == "emitida"
        ),
        2,
    )


# --- A prova ao cêntimo --------------------------------------------------------


def test_bases_mais_ivas_dao_o_total_dos_documentos_com_as_duas_taxas_e_desconto_global():
    """O caso que tem risco todo junto: duas taxas na mesma conta, desconto
    por LINHA (em % e em €) e desconto GLOBAL por cima — que incide sobre o
    líquido já depois dos de linha e tem de ser repartido pelas taxas na
    mesma proporção.

    Valores que expõem o cêntimo: 0,29 · 1,15 · 10,20, com 12,5 % de
    desconto global."""
    vendas = [
        _venda(
            [
                _linha("Brigadeiro", 0.29, REFRI, quantidade=3),
                _linha("Coca-Cola", 1.15, REFRI, desconto_eur=0.29),
                _linha("Açaí XL", 10.20, ACAI, quantidade=2, desconto_pct=10),
                _linha("Açaí Mini", 0.29, ACAI),
            ],
            desconto_global_pct=12.5,
        ),
    ]
    mapa = mapa_de_imposto(vendas)

    soma = round(
        sum(linha["base"] for linha in mapa) + sum(linha["iva"] for linha in mapa), 2
    )
    assert soma == _soma_dos_documentos(vendas)
    assert totais_do_mapa(mapa)["total"] == _soma_dos_documentos(vendas)


def test_bases_mais_ivas_dao_o_total_numa_sessao_inteira_de_varios_documentos():
    """A mesma prova, mas sobre um TURNO: sete documentos com as duas taxas
    misturadas, descontos de linha, desconto global em % e em €, e os 8,99 €
    divididos por três (3,00 · 3,00 · 2,99 — a fatia que não é redonda é a
    que apanha o erro)."""
    fatia = quantidade_para(300, 8.99)
    fatia_curta = quantidade_para(299, 8.99)
    vendas = [
        _venda([_linha("Açaí", 8.99, ACAI, quantidade=fatia)], id="v1"),
        _venda([_linha("Açaí", 8.99, ACAI, quantidade=fatia)], id="v2"),
        _venda([_linha("Açaí", 8.99, ACAI, quantidade=fatia_curta)], id="v3"),
        _venda(
            [
                _linha("Açaí XL", 10.20, ACAI),
                _linha("Coca-Cola", 1.15, REFRI, quantidade=7),
            ],
            id="v4",
            desconto_global_eur=5.00,
        ),
        _venda(
            [
                _linha("Brigadeiro", 0.29, REFRI, quantidade=3),
                _linha("Açaí", 8.99, ACAI, desconto_pct=33.3333),
            ],
            id="v5",
            desconto_global_pct=7,
        ),
        _venda([_linha("Entrega", 1.15, REFRI)], id="v6"),
        _venda([_linha("Açaí Mini", 0.29, ACAI, quantidade=4)], id="v7"),
    ]
    mapa = mapa_de_imposto(vendas)
    esperado = _soma_dos_documentos(vendas)

    assert round(sum(l["base"] for l in mapa) + sum(l["iva"] for l in mapa), 2) == esperado
    assert totais_do_mapa(mapa)["total"] == esperado


def test_base_mais_iva_batem_o_total_em_cada_linha_do_mapa():
    """Por LINHA e não só no somatório: um mapa em que as duas taxas se
    compensam mutuamente daria a soma certa com as duas linhas erradas."""
    vendas = [
        _venda(
            [
                _linha("Açaí", 10.20, ACAI),
                _linha("Coca-Cola", 1.15, REFRI),
                _linha("Brigadeiro", 0.29, REFRI),
            ],
            desconto_global_pct=12.5,
        )
    ]
    for linha in mapa_de_imposto(vendas):
        assert round(linha["base"] + linha["iva"], 2) == linha["total"]


def test_o_desconto_global_reparte_se_pelas_taxas_na_proporcao_de_cada_uma():
    """O desconto global não pode cair todo em cima de uma taxa. Com 10,20 €
    a 13 % e 1,15 € a 23 % (total 11,35 €) e 1,15 € de desconto global, a
    fatia de cada taxa é proporcional ao que ela pesa — e é exactamente a
    que a emissão mandou para a AT, porque sai da mesma função que construiu
    as linhas do documento."""
    sem_desconto = _por_taxa(mapa_de_imposto([
        _venda([_linha("Açaí", 10.20, ACAI), _linha("Coca-Cola", 1.15, REFRI)])
    ]))
    com_desconto = _por_taxa(mapa_de_imposto([
        _venda(
            [_linha("Açaí", 10.20, ACAI), _linha("Coca-Cola", 1.15, REFRI)],
            desconto_global_eur=1.15,
        )
    ]))

    assert sem_desconto[13]["total"] == 10.20
    assert sem_desconto[23]["total"] == 1.15
    # 1,15 € repartido a 10,20:1,15 dá 1,03 € ao açaí e 0,12 € ao refrigerante.
    assert com_desconto[13]["total"] == 9.17
    assert com_desconto[23]["total"] == 1.03
    assert round(com_desconto[13]["total"] + com_desconto[23]["total"], 2) == 10.20


def test_as_taxas_saem_separadas_e_com_a_percentagem_certa():
    mapa = mapa_de_imposto([
        _venda([_linha("Açaí", 10.20, ACAI), _linha("Coca-Cola", 1.15, REFRI)])
    ])
    assert [linha["taxa"] for linha in mapa] == [13, 23]
    assert [linha["tax_id"] for linha in mapa] == ["INT", "NOR"]
    # 10,20 € a 13 %: base 9,03 €, IVA 1,17 €.
    assert (mapa[0]["base"], mapa[0]["iva"]) == (9.03, 1.17)
    # 1,15 € a 23 %: base 0,93 €, IVA 0,22 €.
    assert (mapa[1]["base"], mapa[1]["iva"]) == (0.93, 0.22)


# --- Nº de documentos ----------------------------------------------------------


def test_documentos_conta_documentos_e_nao_linhas():
    """Um talão com dois açaís e duas Coca-Colas é UM documento em cada
    taxa, não dois. Contar linhas era o erro fácil, e enchia o mapa de
    números que não querem dizer nada."""
    mapa = _por_taxa(mapa_de_imposto([
        _venda(
            [
                _linha("Açaí", 10.20, ACAI),
                _linha("Açaí Mini", 0.29, ACAI),
                _linha("Coca-Cola", 1.15, REFRI),
                _linha("Brigadeiro", 0.29, REFRI),
            ]
        )
    ]))
    assert mapa[13]["documentos"] == 1
    assert mapa[23]["documentos"] == 1


def test_um_documento_so_conta_na_taxa_que_tem():
    mapa = _por_taxa(mapa_de_imposto([
        _venda([_linha("Açaí", 10.20, ACAI)], id="v1"),
        _venda([_linha("Açaí", 0.29, ACAI)], id="v2"),
        _venda([_linha("Coca-Cola", 1.15, REFRI)], id="v3"),
    ]))
    assert mapa[13]["documentos"] == 2
    assert mapa[23]["documentos"] == 1


# --- O que NÃO entra -----------------------------------------------------------


def test_conta_aberta_ou_cancelada_nao_entra_no_mapa():
    """Uma conta aberta não é documento nenhum e uma cancelada nunca chegou
    a ser — nenhuma das duas foi entregue à AT."""
    vendas = [
        _venda([_linha("Açaí", 10.20, ACAI)], id="v1", estado="aberta"),
        _venda([_linha("Açaí", 10.20, ACAI)], id="v2", estado="cancelada"),
        _venda([_linha("Coca-Cola", 1.15, REFRI)], id="v3"),
    ]
    mapa = mapa_de_imposto(vendas)
    assert [linha["taxa"] for linha in mapa] == [23]
    assert totais_do_mapa(mapa)["total"] == 1.15


def test_sessao_sem_vendas_da_mapa_vazio():
    assert mapa_de_imposto([]) == []
    assert totais_do_mapa([])["total"] == 0.0


def test_tax_id_desconhecido_nao_inventa_taxa_mas_tambem_nao_perde_o_dinheiro():
    """Nada no caminho de hoje produz um `tax_id` fora de NOR/INT/RED/ISE,
    mas o `produto_tax_id` da linha é um retrato gravado e um retrato antigo
    pode trazer o que lá estiver. A regra de ouro de `precos.py` é nunca
    inventar um IVA — e a regra desta tabela é nunca deixar cair dinheiro:
    a linha sai sem taxa, sem base e sem IVA, com o total preenchido."""
    mapa = mapa_de_imposto([
        _venda([_linha("Açaí", 10.20, ACAI), _linha("Misterioso", 1.15, "XPTO")])
    ])
    desconhecida = [linha for linha in mapa if linha["tax_id"] == "XPTO"]
    assert len(desconhecida) == 1
    assert desconhecida[0]["taxa"] is None
    assert desconhecida[0]["base"] is None
    assert desconhecida[0]["iva"] is None
    assert desconhecida[0]["total"] == 1.15
    # E vai para o FIM da tabela, não desaparece no meio das taxas reais.
    assert mapa[-1]["tax_id"] == "XPTO"
    assert totais_do_mapa(mapa)["total"] == 11.35


# --- A última linha da tabela --------------------------------------------------


def test_os_totais_do_mapa_sao_a_soma_de_cada_coluna():
    """A linha do fim é a soma da tabela que está por cima dela — e é ela que
    torna visível ao balcão a garantia toda: base + IVA = total."""
    vendas = [
        _venda([_linha("Açaí", 10.20, ACAI), _linha("Coca-Cola", 1.15, REFRI)], id="v1"),
        _venda([_linha("Brigadeiro", 0.29, REFRI, quantidade=3)], id="v2"),
    ]
    mapa = mapa_de_imposto(vendas)
    totais = totais_do_mapa(mapa)

    assert totais["base"] == round(sum(l["base"] for l in mapa), 2)
    assert totais["iva"] == round(sum(l["iva"] for l in mapa), 2)
    assert totais["total"] == round(sum(l["total"] for l in mapa), 2)
    assert round(totais["base"] + totais["iva"], 2) == totais["total"]
    assert totais["total"] == _soma_dos_documentos(vendas)


def test_uma_taxa_desconhecida_conta_no_total_e_nao_na_base_nem_no_iva():
    """E é assim que tem de dar nas vistas: as duas primeiras colunas deixam
    de fechar com a terceira, que é o sinal de que há dinheiro sem imposto
    declarado. Calá-lo — pondo a base igual ao total, por exemplo — era
    inventar um IVA de 0 %."""
    totais = totais_do_mapa(mapa_de_imposto([
        _venda([_linha("Açaí", 10.20, ACAI), _linha("Misterioso", 1.15, "XPTO")])
    ]))
    assert totais["total"] == 11.35
    assert totais["base"] == 9.03
    assert totais["iva"] == 1.17
    assert round(totais["base"] + totais["iva"], 2) != totais["total"]
