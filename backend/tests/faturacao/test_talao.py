"""O texto do pedido da cozinha — lógica pura, sem I/O.

O agente de impressão (Plano 3) ainda não existe; isto só constrói o texto
que ele vai imprimir, para não haver nada a mexer aqui quando ele chegar.
"""
from faturacao.talao import pedido_da_cozinha


def test_o_pedido_sai_no_formato_que_o_dono_escreveu():
    venda = {"linhas": [{
        "produto_nome": "Açaí Small", "quantidade": 1,
        "respostas_texto": [{"grupo_id": "g0", "nome_grupo": "Nome", "texto": "Maria"}],
        "opcoes": [
            {"id": "o0", "grupo_id": "g1", "nome": "Levar", "preco": 0, "sai_na_fatura": False},
            {"id": "o1", "grupo_id": "g2", "nome": "Leite condensado", "preco": 0},
            {"id": "o2", "grupo_id": "g2", "nome": "Nutella", "preco": 0.95},
            {"id": "o2", "grupo_id": "g2", "nome": "Nutella", "preco": 0.95},
        ],
    }]}
    assert pedido_da_cozinha(venda) == (
        "Pedido\n"
        "\n"
        "1 Açaí Small — MARIA\n"
        "Levar\n"
        "\n"
        "1x Leite condensado\n"
        "2x Nutella\n"
    )


def test_opcao_PAGA_de_grupo_escondido_vai_com_a_dose_e_nao_ao_servico():
    """A cozinha tem de fazer as duas doses que a fatura cobra.

    O interruptor `sai_na_fatura` esconde o que não custa nada, nunca um euro
    — a mesma regra do título da fatura (`precos._descricao_das_opcoes`) e do
    resumo do ecrã do POS. Estava escrita neste ficheiro ("as opções SEM
    preço de grupos que não vão à fatura") mas não estava no código, que só
    olhava para o interruptor: com um grupo de toppings desligado por engano,
    o "Extra caramelo" pago descia às indicações de serviço, dito uma vez e
    sem dose. A cozinha punha UMA colher, a Fatura Simplificada cobrava duas
    ("Extra caramelo 2×"), e o cliente reclamava com toda a razão."""
    venda = {"linhas": [{
        "produto_nome": "Açaí Small", "quantidade": 1,
        "opcoes": [
            {"id": "o0", "grupo_id": "g1", "nome": "Levar", "preco": 0, "sai_na_fatura": False},
            {"id": "o1", "grupo_id": "g2", "nome": "Extra caramelo", "preco": 0.5,
             "sai_na_fatura": False},
            {"id": "o1", "grupo_id": "g2", "nome": "Extra caramelo", "preco": 0.5,
             "sai_na_fatura": False},
        ],
    }]}
    assert pedido_da_cozinha(venda) == (
        "Pedido\n"
        "\n"
        "1 Açaí Small\n"
        "Levar\n"
        "\n"
        "2x Extra caramelo\n"
    )


def test_uma_linha_sem_nome_nem_opcoes_sai_na_mesma():
    venda = {"linhas": [{"produto_nome": "Café Expresso", "quantidade": 2}]}
    assert pedido_da_cozinha(venda) == "Pedido\n\n2 Café Expresso\n"


def test_duas_linhas_ficam_separadas():
    venda = {"linhas": [
        {"produto_nome": "Café Expresso", "quantidade": 1},
        {"produto_nome": "Água 50cl", "quantidade": 1},
    ]}
    assert pedido_da_cozinha(venda) == (
        "Pedido\n\n1 Café Expresso\n\n1 Água 50cl\n"
    )


# --- O relatório Z, em papel --------------------------------------------------
#
# O Z é o papel que a funcionária ASSINA e leva. Por isso a regra deste bloco
# não é sobre formatação: é que os números do papel são os MESMOS do ecrã, sem
# uma soma nova pelo meio. A aritmética do dinheiro é do servidor e já foi
# feita (`caixa_math`, `mapa_imposto`); um total recalculado aqui era uma
# segunda verdade a contradizer o papel assinado.

from faturacao.talao import relatorio_z


def _z(**over):
    """O que `caixa.fechar_caixa` devolve — os mesmos números que a operadora
    acabou de ver no ecrã do fecho."""
    z = {
        "id": "sessao-1", "caixa_id": "Balcão", "loja_id": "loja-1",
        "aberta_por": {"nome": "Rafaela"}, "aberta_em": "2026-08-22T09:00:00+00:00",
        "fechada_por": {"nome": "Ana"}, "fechada_em": "2026-08-22T23:10:00+00:00",
        "fundo": 50.0, "vendas_dinheiro": 118.55, "entradas": 0.0, "saidas": 20.0,
        "esperado": 148.55, "contado": 148.05, "diferenca": -0.50,
        "pagamentos": [
            {"nome": "Dinheiro", "total": 118.55},
            {"nome": "Multibanco", "total": 210.40},
        ],
        "pagamentos_por_registar": 0.0,
        "mapa_imposto": [
            {"tax_id": "INT", "taxa": 13.0, "documentos": 31, "base": 291.11, "iva": 37.84},
            {"tax_id": "NOR", "taxa": 23.0, "documentos": 4, "base": 0.0, "iva": 0.0},
        ],
        "base_tributavel": 291.11, "iva_total": 37.84, "total_faturado": 328.95,
        "quantos_documentos": 31,
        "contas_abertas": {"quantas": 0, "total": 0.0},
        "tirado_da_gaveta_a_mais": 0.0,
        "devolucoes_acima_do_recebido": 0.0,
    }
    z.update(over)
    return z


def test_o_Z_leva_a_conta_da_GAVETA_que_a_funcionaria_acabou_de_fazer():
    """Fundo, vendas em dinheiro, entradas, saídas, esperado, contado,
    diferença — pela ordem em que ela as fez com as notas na mão."""
    papel = relatorio_z(_z())
    for linha in ("Fundo de maneio", "Vendas em dinheiro", "Entradas", "Saidas",
                  "ESPERADO", "CONTADO", "DIFERENCA"):
        assert linha in papel
    assert "50,00" in papel and "118,55" in papel and "148,55" in papel
    assert "-0,50" in papel


def test_os_numeros_do_papel_sao_os_do_ECRA_e_nao_uma_soma_nova():
    """O Z é assinado. Um total recalculado aqui podia discordar do que ficou
    gravado na sessão, e a assinatura passava a valer para dois números."""
    papel = relatorio_z(_z(total_faturado=999.99, base_tributavel=1.0, iva_total=2.0))
    assert "999,99" in papel
    assert "328,95" not in papel


def test_a_virgula_decimal_porque_e_o_que_a_funcionaria_le():
    assert "148,55" in relatorio_z(_z())
    assert "148.55" not in relatorio_z(_z())


def test_uma_contagem_que_NAO_foi_feita_nao_sai_como_zero():
    """`—` e nunca `0,00`. Escrever zero onde não se sabe é a mentira mais
    fácil de imprimir, e num Z é uma diferença inventada."""
    papel = relatorio_z(_z(contado=None, diferenca=None))
    assert "CONTADO" in papel
    assert "0,00" not in papel.split("CONTADO")[1].split("\n")[0]


def test_o_desdobramento_por_meio_de_pagamento_vai_TODO():
    """É o que permite bater o rolo do Multibanco e o extracto do Glovo contra
    o turno — sem ele o gestor fecha o mês a somar à mão."""
    papel = relatorio_z(_z())
    assert "Dinheiro" in papel and "118,55" in papel
    assert "Multibanco" in papel and "210,40" in papel


def test_o_que_foi_facturado_e_nao_tem_pagamento_por_baixo_sai_SEMPRE():
    """Mesmo a zero: quem lê o papel não pode ter de adivinhar se a ausência
    da linha quer dizer «está tudo cobrado» ou «esta versão não sabe
    responder a isso»."""
    assert "Por registar" in relatorio_z(_z())
    assert "Por registar" in relatorio_z(_z(pagamentos_por_registar=1.15))


def test_uma_taxa_DESCONHECIDA_sai_com_ponto_de_interrogacao_e_o_dinheiro_fica():
    """Nunca se inventa uma percentagem, e nunca se deita fora o dinheiro
    (a regra de `mapa_imposto.mapa_de_imposto`)."""
    papel = relatorio_z(_z(mapa_imposto=[
        {"tax_id": "XPT", "taxa": None, "documentos": 2, "base": None,
         "iva": None, "total": 9.90},
    ]))
    assert "?" in papel
    assert "TOTAL FATURADO" in papel


def test_as_contas_que_ficaram_ABERTAS_saem_por_extenso_no_papel():
    """Um número solto numa tabela não faz ninguém pegar no telefone."""
    papel = " ".join(relatorio_z(
        _z(contas_abertas={"quantas": 2, "total": 21.15})).split())
    assert "ATENCAO" in papel
    assert "2 contas ABERTAS" in papel
    assert "21,15" in papel
    assert "nao foram cobradas" in papel


def test_o_que_saiu_da_gaveta_a_mais_sai_por_extenso_no_papel():
    papel = relatorio_z(_z(tirado_da_gaveta_a_mais=15.40))
    assert "ATENCAO" in papel
    assert "15,40" in papel


def test_um_turno_SEM_avisos_nao_imprime_a_seccao_de_avisos():
    """Uma secção «ATENÇÃO» que aparece todas as noites deixa de ser lida."""
    assert "ATENCAO" not in relatorio_z(_z())


def test_nenhuma_linha_do_Z_passa_da_largura_do_papel():
    """80 mm são 42 colunas. Um Z mais largo do que o papel não fica ilegível —
    fica ENGANADOR: as colunas dão a volta e a diferença da gaveta aparece por
    baixo do rótulo errado."""
    papel = relatorio_z(_z(contas_abertas={"quantas": 2, "total": 21.15},
                           tirado_da_gaveta_a_mais=15.40,
                           devolucoes_acima_do_recebido=3.30))
    assert [l for l in papel.split("\n") if len(l) > 42] == []


def test_um_rotulo_comprido_de_mais_empurra_o_valor_para_a_linha_de_baixo():
    """Nunca corta e nunca deixa dar a volta: um valor que dá a volta aparece
    debaixo do rótulo seguinte, e é assim que se lê uma diferença como se
    fosse outra coisa."""
    z = _z(caixa_id="Balcão do drive-thru da loja do Guarda em Vila Real")
    for linha in relatorio_z(z).split("\n"):
        assert len(linha) <= 42, linha


def test_o_Z_traz_QUEM_e_QUANDO_porque_o_papel_le_se_um_mes_depois():
    papel = relatorio_z(_z())
    assert "Rafaela" in papel and "Ana" in papel
    assert "2026-08-22T23:10:00+00:00" in papel


def test_o_Z_tem_onde_assinar():
    assert "Assinatura" in relatorio_z(_z())
