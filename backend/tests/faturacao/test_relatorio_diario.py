"""**Os números do relatório diário** — aritmética pura, sem Mongo e sem email.

O dono quer, todos os dias às 23:30, um email com o que as lojas fizeram: a
faturação geral e por loja, quanto está em cada caixa e no caixa geral, o
artigo mais vendido partido pelos tamanhos, e os tipos de pagamento por loja e
no total.

**A regra que este módulo não pode quebrar: não há somas novas.** A faturação
sai de `dashboard._valor_documento` (a mesma que o Dashboard usa, com a nota de
crédito a subtrair e o anulado a não contar) e o caixa sai de
`caixa._resumo_do_turno` — a MESMA função que serve o Ponto de Caixa e o Z. Uma
terceira contabilidade sobre a mesma gaveta era a maneira mais certa de o email
e o Z discordarem um dia, e o dono não ter como saber qual deles mente.

Por isso a maior parte destes testes não mede uma fórmula nova: mede que o
relatório **usa a que já existe** e que não perde nada pelo caminho.
"""
import pytest

from faturacao.relatorio_diario import montar_relatorio

_HOJE = "2026-08-26"
_ONTEM = "2026-08-25"

_LOJAS = [
    {"id": "l1", "nome": "L'açaí Alfragide"},
    {"id": "l2", "nome": "L'açaí Oeiras"},
]


def _doc(loja_id, valor, data=_HOJE, **extra):
    d = {
        "id": "d-%s-%s" % (loja_id, valor),
        "loja_id": loja_id,
        "tipo": "FS",
        "total_bruto": valor,
        "total_liquido": round(valor / 1.13, 2),
        "emitido_em": "%sT14:30:00+01:00" % data,
    }
    d.update(extra)
    return d


def _pagamento(nome, valor, tipo_id=None):
    """O `tipo_fiscal` NÃO é decorativo: é ele — e não o nome — que faz um
    pagamento contar como DINHEIRO na gaveta (`caixa_math.soma_vendas_dinheiro`
    filtra por `NU`). Um duplo sem ele media um turno em que nada é dinheiro,
    e o `esperado` do caixa vinha só com o fundo de maneio."""
    return {
        "tipo_pagamento_id": tipo_id or nome.lower(),
        "nome": nome,
        "valor": valor,
        "tipo_fiscal": "NU" if nome == "Dinheiro" else "CD",
    }


def _venda(loja_id, pagamentos, linhas=None, estado="emitida"):
    return {
        "id": "v-%s-%d" % (loja_id, len(pagamentos)),
        "loja_id": loja_id,
        "estado": estado,
        "pagamentos": pagamentos,
        "linhas": linhas or [],
    }


def _linha(nome, quantidade=1, preco=8.99, opcoes=None):
    """Com `produto_tax_id`, porque uma linha real tem: o `_resumo_do_turno`
    calcula o mapa de imposto do turno por cima destas linhas e recusa-se a
    inventar uma taxa. Um duplo sem ele rebentava com 422 — que é o mesmo que
    o servidor faz a sério, e por isso o duplo é que estava errado."""
    return {
        "produto_nome": nome,
        "quantidade": quantidade,
        "produto_preco": preco,
        "produto_tax_id": "INT",
        "opcoes": opcoes or [],
    }


def _opcao(grupo, nome, preco=0.0):
    return {"grupo_nome": grupo, "nome": nome, "preco": preco}


def _turno(loja_id, fundo=50.0, contado=None, estado="fechada", vendas=None,
           movimentos=None, notas_credito=None):
    return {
        "sessao": {
            "id": "s-%s" % loja_id, "loja_id": loja_id, "fundo": fundo,
            "estado": estado, "contado": contado,
        },
        "movimentos": movimentos or [],
        "vendas": vendas or [],
        "notas_credito": notas_credito or [],
    }


def _relatorio(**kw):
    base = dict(dia=_HOJE, ate="23:30", lojas=_LOJAS,
                documentos=[], turnos=[], com_iva=True)
    base.update(kw)
    return montar_relatorio(**base)


# --- Faturação ---------------------------------------------------------------


def test_a_faturacao_geral_e_a_soma_dos_documentos_do_dia():
    r = _relatorio(documentos=[_doc("l1", 100.0), _doc("l2", 50.5)])
    assert r["geral"]["faturacao"] == 150.5


def test_os_documentos_de_ONTEM_nao_entram_na_faturacao_de_hoje():
    """Entram para a comparação, e é a única coisa para que servem."""
    r = _relatorio(documentos=[_doc("l1", 100.0), _doc("l1", 900.0, data=_ONTEM)])
    assert r["geral"]["faturacao"] == 100.0
    assert r["geral"]["faturacao_ontem"] == 900.0


def test_uma_NOTA_DE_CREDITO_do_dia_SUBTRAI():
    """A regra é a do Dashboard, e não uma inventada aqui: uma devolução de
    20 € num dia de 100 € deixa 80 €, nunca 120 €."""
    r = _relatorio(documentos=[_doc("l1", 100.0), _doc("l1", 20.0, tipo="NC")])
    assert r["geral"]["faturacao"] == 80.0


def test_um_documento_ANULADO_nao_conta_nada():
    r = _relatorio(documentos=[_doc("l1", 100.0), _doc("l1", 999.0, anulado=True)])
    assert r["geral"]["faturacao"] == 100.0


def test_a_faturacao_por_loja_soma_so_a_dessa_loja():
    r = _relatorio(documentos=[
        _doc("l1", 100.0), _doc("l1", 25.0), _doc("l2", 60.0)])
    por_id = {l["id"]: l for l in r["lojas"]}
    assert por_id["l1"]["faturacao"] == 125.0
    assert por_id["l2"]["faturacao"] == 60.0


def test_uma_loja_SEM_VENDAS_aparece_na_mesma_a_zero():
    """Uma loja que desaparece do relatório lê-se como «não existe», não como
    «não vendeu» — e é precisamente a que o dono quer ver."""
    r = _relatorio(documentos=[_doc("l1", 100.0)])
    por_id = {l["id"]: l for l in r["lojas"]}
    assert por_id["l2"]["faturacao"] == 0.0
    assert por_id["l2"]["sem_vendas"] is True


def test_a_soma_das_lojas_BATE_com_o_geral():
    """O guarda que apanha uma loja esquecida: se o geral e a soma das partes
    discordarem, o email mostra dois totais diferentes na mesma página."""
    r = _relatorio(documentos=[
        _doc("l1", 100.0), _doc("l1", 25.5), _doc("l2", 60.25), _doc("l2", 0.29)])
    assert round(sum(l["faturacao"] for l in r["lojas"]), 2) == r["geral"]["faturacao"]


def test_a_variacao_contra_ontem():
    r = _relatorio(documentos=[_doc("l1", 80.0), _doc("l1", 100.0, data=_ONTEM)])
    assert r["geral"]["variacao"] == -20.0


def test_sem_ontem_a_variacao_e_NULA_e_nao_zero():
    """Zero por cento diria «igual a ontem», que é falso — ontem não houve
    nada com que comparar."""
    r = _relatorio(documentos=[_doc("l1", 80.0)])
    assert r["geral"]["variacao"] is None


def test_o_dia_sem_vendas_nenhumas_diz_se():
    r = _relatorio()
    assert r["ha_vendas"] is False
    assert r["geral"]["faturacao"] == 0.0


# --- Caixa -------------------------------------------------------------------


def test_o_caixa_de_uma_loja_traz_o_esperado_e_o_CONTADO():
    """Os dois lado a lado, com a diferença — foi o que o dono escolheu, para
    apanhar uma falta na manhã seguinte sem abrir o sistema."""
    vendas = [_venda("l1", [_pagamento("Dinheiro", 30.0)])]
    r = _relatorio(documentos=[_doc("l1", 30.0)],
                   turnos=[_turno("l1", fundo=50.0, contado=78.0, vendas=vendas)])
    caixa = r["lojas"][0]["caixa"]
    assert caixa["esperado"] == 80.0      # 50 de fundo + 30 em dinheiro
    assert caixa["contado"] == 78.0
    assert caixa["diferenca"] == -2.0     # faltam 2 €
    assert caixa["estado"] == "fechado"


def test_um_turno_AINDA_ABERTO_nao_inventa_um_contado():
    """Ninguém contou a gaveta. Mostrar lá um número — o esperado, um zero —
    era pôr no email uma contagem que não aconteceu."""
    vendas = [_venda("l1", [_pagamento("Dinheiro", 30.0)])]
    r = _relatorio(documentos=[_doc("l1", 30.0)],
                   turnos=[_turno("l1", fundo=50.0, contado=None,
                                  estado="aberta", vendas=vendas)])
    caixa = r["lojas"][0]["caixa"]
    assert caixa["estado"] == "aberto"
    assert caixa["esperado"] == 80.0
    assert caixa["contado"] is None
    assert caixa["diferenca"] is None


def test_uma_loja_que_nao_abriu_caixa_diz_se():
    r = _relatorio(documentos=[])
    assert r["lojas"][0]["caixa"]["estado"] == "sem_turno"


def test_o_caixa_GERAL_soma_as_lojas_todas():
    v1 = [_venda("l1", [_pagamento("Dinheiro", 30.0)])]
    v2 = [_venda("l2", [_pagamento("Dinheiro", 10.0)])]
    r = _relatorio(
        documentos=[_doc("l1", 30.0), _doc("l2", 10.0)],
        turnos=[_turno("l1", fundo=50.0, contado=78.0, vendas=v1),
                _turno("l2", fundo=20.0, contado=30.0, vendas=v2)])
    caixa = r["geral"]["caixa"]
    assert caixa["esperado"] == 110.0   # (50+30) + (20+10)
    assert caixa["contado"] == 108.0
    assert caixa["diferenca"] == -2.0


def test_o_caixa_geral_NAO_soma_o_contado_de_um_turno_aberto():
    """Somar só os fechados e dizer quantos ficaram por fechar. Misturar os
    dois dava um «contado» que não é o de lado nenhum."""
    v1 = [_venda("l1", [_pagamento("Dinheiro", 30.0)])]
    v2 = [_venda("l2", [_pagamento("Dinheiro", 10.0)])]
    r = _relatorio(
        documentos=[_doc("l1", 30.0), _doc("l2", 10.0)],
        turnos=[_turno("l1", fundo=50.0, contado=78.0, vendas=v1),
                _turno("l2", fundo=20.0, contado=None, estado="aberta", vendas=v2)])
    caixa = r["geral"]["caixa"]
    assert caixa["contado"] == 78.0
    assert caixa["turnos_abertos"] == 1


# --- Tipos de pagamento ------------------------------------------------------


def test_os_pagamentos_de_uma_loja_vem_desdobrados():
    vendas = [_venda("l1", [_pagamento("Dinheiro", 30.0),
                            _pagamento("Multibanco", 19.14)])]
    r = _relatorio(documentos=[_doc("l1", 49.14)], turnos=[_turno("l1", vendas=vendas)])
    por_nome = {p["nome"]: p["total"] for p in r["lojas"][0]["pagamentos"]}
    assert por_nome == {"Dinheiro": 30.0, "Multibanco": 19.14}


def test_os_pagamentos_TOTAIS_somam_as_lojas_por_tipo():
    """Um «Multibanco» de Alfragide e outro de Oeiras são a mesma linha no
    total — é essa a pergunta: quanto entrou por cada meio, na empresa."""
    v1 = [_venda("l1", [_pagamento("Dinheiro", 30.0), _pagamento("Multibanco", 20.0)])]
    v2 = [_venda("l2", [_pagamento("Multibanco", 15.5)])]
    r = _relatorio(documentos=[_doc("l1", 50.0), _doc("l2", 15.5)],
                   turnos=[_turno("l1", vendas=v1), _turno("l2", vendas=v2)])
    por_nome = {p["nome"]: p["total"] for p in r["geral"]["pagamentos"]}
    assert por_nome == {"Multibanco": 35.5, "Dinheiro": 30.0}


def test_os_pagamentos_totais_BATEM_com_a_soma_das_lojas():
    """As duas somas aparecem na MESMA página do email: a linha «Multibanco»
    do total e as linhas «Multibanco» de cada loja. Se discordarem num
    cêntimo, o dono vê dois números diferentes para a mesma coisa e deixa de
    confiar no relatório inteiro.

    Valores escolhidos para o pior caso da vírgula flutuante — `0.29 + 1.15 +
    10.20` somados em euros dá 11.639999999999999."""
    v1 = [_venda("l1", [_pagamento("Multibanco", 0.29),
                        _pagamento("Multibanco", 1.15)])]
    v2 = [_venda("l2", [_pagamento("Multibanco", 10.20)])]
    r = _relatorio(documentos=[_doc("l1", 1.44), _doc("l2", 10.20)],
                   turnos=[_turno("l1", vendas=v1), _turno("l2", vendas=v2)])
    total_geral = {p["nome"]: p["total"] for p in r["geral"]["pagamentos"]}
    soma_das_lojas = {}
    for loja in r["lojas"]:
        for p in loja["pagamentos"]:
            soma_das_lojas[p["nome"]] = round(
                soma_das_lojas.get(p["nome"], 0) + p["total"], 2)
    assert total_geral == soma_das_lojas
    assert total_geral["Multibanco"] == 11.64


def test_um_pagamento_gravado_em_TEXTO_nao_derruba_o_relatorio():
    """`"8.99"` em vez de `8.99` acontece — um documento reconciliado do
    Vendus, um registo de uma versão anterior. Um relatório que não sai por
    causa disso é dinheiro que se cala, na versão silenciosa.

    Mede a CADEIA inteira (venda -> `por_tipo_de_pagamento` -> total do
    relatório), e não uma função em particular: é lá dentro, no `caixa_math`,
    que o texto é convertido. Dito por inteiro para ninguém o ler como um
    guarda do `_junta_pagamentos` — esse não é observável por aqui."""
    v1 = [_venda("l1", [_pagamento("Multibanco", "8.99")])]
    r = _relatorio(documentos=[_doc("l1", 8.99)], turnos=[_turno("l1", vendas=v1)])
    assert r["geral"]["pagamentos"][0]["total"] == 8.99


def test_os_pagamentos_totais_vem_do_MAIOR_para_o_menor():
    v1 = [_venda("l1", [_pagamento("Dinheiro", 10.0), _pagamento("Multibanco", 90.0)])]
    r = _relatorio(documentos=[_doc("l1", 100.0)], turnos=[_turno("l1", vendas=v1)])
    assert [p["nome"] for p in r["geral"]["pagamentos"]] == ["Multibanco", "Dinheiro"]


# --- Artigos -----------------------------------------------------------------


def test_o_top_de_artigos_conta_as_UNIDADES_vendidas():
    vendas = [_venda("l1", [_pagamento("Dinheiro", 30.0)], linhas=[
        _linha("Açaí", quantidade=2), _linha("Água", quantidade=5)])]
    r = _relatorio(documentos=[_doc("l1", 30.0)], turnos=[_turno("l1", vendas=vendas)])
    por_nome = {a["nome"]: a["quantidade"] for a in r["artigos"]}
    assert por_nome == {"Água": 5, "Açaí": 2}


def test_o_ACAI_parte_se_pelos_TAMANHOS_que_tem_dentro():
    """O pedido do dono, literalmente: «criei um artigo chamado açaí e dentro
    vêm as personalizações de tamanho — mini, small, regular e supreme»."""
    vendas = [_venda("l1", [_pagamento("Dinheiro", 30.0)], linhas=[
        _linha("Açaí", quantidade=3, opcoes=[_opcao("Tamanho", "Small")]),
        _linha("Açaí", quantidade=1, opcoes=[_opcao("Tamanho", "Supreme")]),
        _linha("Açaí", quantidade=2, opcoes=[_opcao("Tamanho", "Small")]),
    ])]
    r = _relatorio(documentos=[_doc("l1", 30.0)], turnos=[_turno("l1", vendas=vendas)])
    acai = next(a for a in r["artigos"] if a["nome"] == "Açaí")
    assert acai["quantidade"] == 6
    assert [(v["nome"], v["quantidade"]) for v in acai["variantes"]] == [
        ("Small", 5), ("Supreme", 1)]


def test_uma_personalizacao_que_NAO_e_tamanho_nao_parte_o_artigo():
    """«Nutella 2×» é um extra, não uma variante do produto. Parti-lo por aí
    dava um top com uma linha por combinação — ilegível e falso."""
    vendas = [_venda("l1", [_pagamento("Dinheiro", 30.0)], linhas=[
        _linha("Açaí", quantidade=2, opcoes=[
            _opcao("Tamanho", "Regular"), _opcao("Extras", "Nutella")]),
    ])]
    r = _relatorio(documentos=[_doc("l1", 30.0)], turnos=[_turno("l1", vendas=vendas)])
    acai = next(a for a in r["artigos"] if a["nome"] == "Açaí")
    assert [v["nome"] for v in acai["variantes"]] == ["Regular"]


def test_um_artigo_SEM_tamanho_nenhum_nao_leva_variantes():
    vendas = [_venda("l1", [_pagamento("Dinheiro", 5.0)],
                     linhas=[_linha("Água", quantidade=5)])]
    r = _relatorio(documentos=[_doc("l1", 5.0)], turnos=[_turno("l1", vendas=vendas)])
    assert r["artigos"][0]["variantes"] == []


def test_uma_venda_por_EMITIR_nao_conta_para_os_artigos():
    """A mesma regra de `por_tipo_de_pagamento`: uma conta aberta ainda não
    vendeu nada a ninguém."""
    vendas = [_venda("l1", [], linhas=[_linha("Açaí", quantidade=9)], estado="aberta")]
    r = _relatorio(documentos=[], turnos=[_turno("l1", vendas=vendas)])
    assert r["artigos"] == []


# --- O cabeçalho -------------------------------------------------------------


def test_o_relatorio_diz_o_DIA_e_a_HORA_do_corte():
    """O buraco conhecido das 23:30 fica escrito no próprio relatório: quem o
    lê nunca tem de adivinhar o que está lá dentro."""
    r = _relatorio()
    assert r["dia"] == _HOJE
    assert r["ate"] == "23:30"
