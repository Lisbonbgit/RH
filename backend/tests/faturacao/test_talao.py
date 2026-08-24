"""O texto do pedido da cozinha — lógica pura, sem I/O.

O agente de impressão já imprime este texto numa loja a sério: o que se muda
aqui sai em papel na cozinha.

## Como se prende a FORMA e não só as palavras

Uma ficha de cozinha vive da hierarquia — o nome do cliente maior do que
tudo, o artigo a seguir, o serviço destacado — e a hierarquia é feita de
comandos ESC/POS, que são bytes de controlo invisíveis no meio do texto. Um
teste que só procure «MARIA» no papel passa com o talão plano que o dono
reclamou.

`_analisar` desmonta o papel como a impressora o lê: devolve, por linha, o
texto limpo E o estado em que ela vai imprimi-lo (corpo, negrito,
alinhamento). É isso que permite afirmar «o nome sai em corpo duplo» e «esta
linha não passa das colunas do corpo dela» — e é isso que fica vermelho
quando se apaga um comando.
"""
from faturacao.talao import pedido_da_cozinha


def _analisar(papel):
    """As linhas do papel, cada uma com o estado da impressora ao imprimi-la:
    `{"texto", "corpo", "negrito", "centrado"}`.

    O estado ATRAVESSA as mudanças de linha, como na impressora a sério: um
    `GS !` aberto numa linha continua ligado na seguinte até alguém o
    desligar (é por isso que `escpos.documento` começa sempre por `ESC @`).
    O `corpo` de uma linha é o maior que esteve ligado enquanto ela era
    escrita — o que interessa para saber quantas colunas ela ocupa."""
    lidas = []
    corpo, negrito, centrado = 0, False, False
    for bruto in papel.split("\n"):
        texto, corpo_da_linha, negrito_da_linha, centrado_da_linha = "", 0, False, False
        i = 0
        while i < len(bruto):
            c, seguinte = bruto[i], bruto[i + 1:i + 2]
            if c == "\x1d" and seguinte == "!":
                corpo = ord(bruto[i + 2]); i += 3
            elif c == "\x1b" and seguinte == "E":
                negrito = bool(ord(bruto[i + 2])); i += 3
            elif c == "\x1b" and seguinte == "a":
                centrado = ord(bruto[i + 2]) == 1; i += 3
            else:
                texto += c; i += 1
                corpo_da_linha = max(corpo_da_linha, corpo)
                negrito_da_linha = negrito_da_linha or negrito
                centrado_da_linha = centrado_da_linha or centrado
        lidas.append({"texto": texto, "corpo": corpo_da_linha,
                      "negrito": negrito_da_linha, "centrado": centrado_da_linha})
    return lidas


def _sem_comandos(papel):
    return "\n".join(l["texto"] for l in _analisar(papel))


def _duplo(linha):
    """Dobro em LARGURA — é a metade do `GS ! n` que gasta colunas."""
    return bool(linha["corpo"] & 0xF0)


def _alto(linha):
    """Dobro em ALTURA — o que faz um artigo saltar à vista sem gastar
    colunas nenhumas."""
    return bool(linha["corpo"] & 0x0F)



def test_NENHUMA_resposta_dada_ao_balcao_pode_faltar_na_ficha():
    """A ficha da cozinha é o REGISTO do que foi pedido ao balcão.

    Dois buracos, ambos silenciosos, ambos medidos no código anterior:

    - `_nome_no_copo` devolvia só a PRIMEIRA resposta de texto. Um copo com
      dois grupos de texto — «Nome» e «Observações» — perdia o segundo, e
      ninguém dava por isso: o papel saía bonito, sem a observação.
    - as respostas saíam sem a pergunta que as originou, e um grupo que o
      gestor tenha configurado para SAIR NA FATURA não passa por
      `_e_indicacao_de_servico` — caía nos toppings, «Sem colher» misturado
      com a Nutella e sem nada a dizer de onde vinha.

    O critério é binário: tudo o que o sistema perguntou e a operadora
    respondeu aparece."""
    venda = {"linhas": [{
        "produto_nome": "Açaí Large", "quantidade": 1,
        "respostas_texto": [
            {"grupo_id": "g-nome", "nome_grupo": "Nome", "texto": "Maria"},
            {"grupo_id": "g-obs", "nome_grupo": "Observações", "texto": "sem granola"},
        ],
        "opcoes": [
            {"id": "o1", "grupo_id": "g-servico", "nome": "Comer aqui", "preco": 0,
             "nome_grupo": "Consumir em loja", "sai_na_fatura": False},
            # A SEGUNDA pergunta de serviço, esta configurada para sair na
            # fatura: `_e_indicacao_de_servico` diz que não é serviço, e por
            # isso ela desce aos toppings — mas continua a ter de aparecer, e
            # com o título que a explica.
            {"id": "o2", "grupo_id": "g-colher", "nome": "Sem colher", "preco": 0,
             "nome_grupo": "Talheres"},
            {"id": "o3", "grupo_id": "g-top", "nome": "Nutella", "preco": 0.95,
             "nome_grupo": "Toppings"},
            {"id": "o3", "grupo_id": "g-top", "nome": "Nutella", "preco": 0.95,
             "nome_grupo": "Toppings"},
            {"id": "o4", "grupo_id": "g-top", "nome": "Leite condensado", "preco": 0,
             "nome_grupo": "Toppings"},
        ],
    }]}
    papel = _sem_comandos(pedido_da_cozinha(venda))

    assert "MARIA" in papel                      # a primeira resposta de texto
    assert "Observações: sem granola" in papel   # a SEGUNDA, que se perdia
    assert "Consumir em loja: Comer aqui" in papel
    assert "Talheres" in papel and "Sem colher" in papel
    assert "2x Nutella" in papel
    assert "1x Leite condensado" in papel


def test_a_HIERARQUIA_de_leitura_esta_no_papel_e_nao_so_as_palavras():
    """O dono imprimiu a primeira versão e disse: «está muito pequeno as
    letras, está saindo tipo sem título, está tudo no mesmo tamanho, não está
    parecendo um papel para a cozinha fazer os pedidos».

    Quem lê está de costas para o balcão, com as mãos ocupadas e o papel à
    distância de um braço. Este teste afirma a ORDEM DE IMPORTÂNCIA — o
    cabeçalho por cima, o nome maior do que tudo, o artigo a seguir, o serviço
    destacado, os toppings sob o artigo certo — e não o texto: é a
    formatação que o dono reclamou, e uma frase encontrada no meio do papel
    não prende formatação nenhuma."""
    venda = {
        "id": "3b91c0de-0000-4000-8000-00000000f2c4",
        "criada_em": "2026-08-24T20:47:00+00:00",
        "linhas": [{
            "produto_nome": "Açaí Small", "quantidade": 1,
            "respostas_texto": [{"grupo_id": "g0", "nome_grupo": "Nome", "texto": "Maria"}],
            "opcoes": [
                {"id": "o0", "grupo_id": "g1", "nome": "Levar", "preco": 0,
                 "nome_grupo": "Consumir em loja", "sai_na_fatura": False},
                {"id": "o1", "grupo_id": "g2", "nome": "Leite condensado", "preco": 0,
                 "nome_grupo": "Toppings"},
                {"id": "o2", "grupo_id": "g2", "nome": "Nutella", "preco": 0.95,
                 "nome_grupo": "Toppings"},
                {"id": "o2", "grupo_id": "g2", "nome": "Nutella", "preco": 0.95,
                 "nome_grupo": "Toppings"},
            ],
        }],
    }
    papel = _analisar(pedido_da_cozinha(venda))
    texto = [l["texto"] for l in papel]

    # O cabeçalho: o que é, centrado e em corpo maior do que o normal, com a
    # hora de LISBOA (a venda está gravada em UTC) e um número curto para se
    # falar dele em voz alta.
    titulo = papel[texto.index("PEDIDO COZINHA")]
    assert _alto(titulo) and titulo["negrito"] and titulo["centrado"]
    assert "#F2C4" in "\n".join(texto)
    assert "21:47" in "\n".join(texto)  # 20:47 UTC são 21:47 na parede da loja

    # 1. O NOME é o maior elemento do talão — o único em corpo DUPLO.
    nome = papel[texto.index("MARIA")]
    assert _duplo(nome) and nome["negrito"]
    assert [l["texto"] for l in papel if _duplo(l)] == ["MARIA"]

    # 2. O artigo abre com a quantidade e o produto, e vem a seguir em
    #    tamanho: alto, mas não duplo (não gasta colunas).
    artigo = papel[texto.index("1 Açaí Small")]
    assert _alto(artigo) and not _duplo(artigo)
    assert texto.index("1 Açaí Small") > texto.index("MARIA")

    # 3. A resposta de serviço vem destacada e COM A PERGUNTA — muda o que se
    #    faz ao copo.
    servico = papel[texto.index("Consumir em loja: Levar")]
    assert servico["negrito"]
    assert texto.index("Consumir em loja: Levar") > texto.index("1 Açaí Small")

    # 4. Os toppings, com as doses, sob o grupo a que pertencem e depois de
    #    tudo o resto.
    assert texto.index("Toppings:") > texto.index("Consumir em loja: Levar")
    assert texto[texto.index("Toppings:") + 1:texto.index("Toppings:") + 3] == [
        "  1x Leite condensado", "  2x Nutella",
    ]

    # E o que é destaque tem de ser POUCO: um talão todo a negrito e todo
    # centrado é outra vez um talão sem hierarquia nenhuma. Os toppings leem-se
    # em corpo normal, e o corpo do talão é encostado à esquerda — só o
    # cabeçalho é que vai ao meio.
    assert not papel[texto.index("  2x Nutella")]["negrito"]
    assert papel[texto.index("  2x Nutella")]["corpo"] == 0
    assert not papel[texto.index("1 Açaí Small")]["centrado"]


def test_nenhuma_linha_passa_das_colunas_do_CORPO_DE_LETRA_dela():
    """42 colunas em corpo normal, 21 em corpo duplo. Uma linha que dê a volta
    numa ficha de cozinha faz ler o topping errado: a sobra aparece encostada
    à esquerda, por baixo, onde parece pertencer ao artigo seguinte."""
    venda = {
        "id": "3b91c0de-0000-4000-8000-00000000f2c4",
        "criada_em": "2026-08-24T20:47:00+00:00",
        "linhas": [{
            "produto_nome": "Açaí Extra Large com granola da casa e fruta da época",
            "quantidade": 3,
            "respostas_texto": [
                {"grupo_id": "g0", "nome_grupo": "Nome", "texto": "Maria da Conceição Rodrigues"},
                {"grupo_id": "g9", "nome_grupo": "Observações do cliente",
                 "texto": "tirar a granola toda e pôr o leite condensado à parte, por favor"},
            ],
            "opcoes": [
                {"id": "o0", "grupo_id": "g1", "nome": "Comer aqui na esplanada de fora",
                 "preco": 0, "nome_grupo": "Consumir em loja ou levar para fora",
                 "sai_na_fatura": False},
                {"id": "o1", "grupo_id": "g2", "preco": 0.95,
                 "nome": "Manteiga de amendoim com pedaços de amendoim torrado",
                 "nome_grupo": "Toppings extra que se pagam à parte"},
            ],
        }],
    }
    for linha in _analisar(pedido_da_cozinha(venda)):
        colunas = 21 if _duplo(linha) else 42
        assert len(linha["texto"]) <= colunas, (linha["texto"], colunas)


def test_um_artigo_fica_SEPARADO_do_seguinte_porque_a_cozinha_troca_copos():
    """Colados, a Nutella do segundo copo lê-se como sendo do primeiro."""
    venda = {"linhas": [
        {"produto_nome": "Açaí Small", "quantidade": 1,
         "respostas_texto": [{"grupo_id": "g0", "nome_grupo": "Nome", "texto": "Maria"}]},
        {"produto_nome": "Açaí Large", "quantidade": 1,
         "respostas_texto": [{"grupo_id": "g0", "nome_grupo": "Nome", "texto": "João"}]},
    ]}
    texto = [l["texto"] for l in _analisar(pedido_da_cozinha(venda))]
    separador = "-" * 42
    assert separador in texto
    assert texto.index("MARIA") < texto.index(separador) < texto.index("JOÃO")


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
            {"id": "o0", "grupo_id": "g1", "nome": "Levar", "preco": 0,
             "nome_grupo": "Consumir em loja", "sai_na_fatura": False},
            {"id": "o1", "grupo_id": "g2", "nome": "Extra caramelo", "preco": 0.5,
             "nome_grupo": "Toppings", "sai_na_fatura": False},
            {"id": "o1", "grupo_id": "g2", "nome": "Extra caramelo", "preco": 0.5,
             "nome_grupo": "Toppings", "sai_na_fatura": False},
        ],
    }]}
    texto = [l["texto"] for l in _analisar(pedido_da_cozinha(venda))]
    assert "  2x Extra caramelo" in texto
    assert "Consumir em loja: Levar" in texto
    assert "1x Extra caramelo" not in texto


def test_uma_linha_sem_nome_nem_opcoes_sai_na_mesma():
    texto = [l["texto"] for l in
             _analisar(pedido_da_cozinha({"linhas": [
                 {"produto_nome": "Café Expresso", "quantidade": 2}]}))]
    assert "2 Café Expresso" in texto


def test_uma_linha_GRAVADA_ANTES_do_carimbo_do_titulo_sai_sem_titulo_e_inteira():
    """As contas que já estavam abertas não têm `nome_grupo` nas opções. O
    título vem a `None`, as respostas saem sem ele — exactamente como saíam —
    e nada se perde. Uma ficha que rebentasse aqui era a cozinha sem papel."""
    venda = {"linhas": [{
        "produto_nome": "Açaí Small", "quantidade": 1,
        "respostas_texto": [{"grupo_id": "g0", "texto": "Maria"}],
        "opcoes": [
            {"id": "o0", "grupo_id": "g1", "nome": "Levar", "preco": 0,
             "sai_na_fatura": False},
            {"id": "o1", "grupo_id": "g2", "nome": "Nutella", "preco": 0.95},
        ],
    }]}
    texto = [l["texto"] for l in _analisar(pedido_da_cozinha(venda))]
    assert "MARIA" in texto and "Levar" in texto and "1x Nutella" in texto


def test_uma_venda_SEM_hora_nao_inventa_uma():
    """Uma ficha sem hora lê-se na mesma; uma ficha com a hora errada manda a
    cozinha discutir com o balcão sobre qual dos pedidos é o antigo."""
    papel = pedido_da_cozinha({"id": "abcd", "criada_em": "nao e' uma data",
                               "linhas": []})
    assert "#ABCD" in _sem_comandos(papel)
    assert ":" not in _sem_comandos(papel)


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
