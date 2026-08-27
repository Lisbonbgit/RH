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
    # Os títulos dos grupos saíram do papel a pedido do dono (Agosto/2026) —
    # o que NÃO pode sair são as respostas. Esta é a mesma regra de sempre,
    # medida contra a arrumação nova.
    assert "Comer aqui" in papel
    assert "Sem colher" in papel
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

    # 1. O ARTIGO é o maior elemento do talão — e é a primeira coisa depois
    #    do cabeçalho. A ordem inverteu-se em Agosto/2026: quem faz os açaís
    #    precisa de ver primeiro o que vai FAZER.
    artigo = papel[texto.index("1 x Açaí Small")]
    assert artigo["corpo"] == 0x11, artigo   # 2x nos dois sentidos
    assert artigo["negrito"]

    # 2. O NOME do cliente vem a seguir, do mesmo tamanho e SEM negrito — a
    #    hierarquia é a ordem, não o tamanho (ver o teste da letra
    #    proporcional, no fim do ficheiro).
    nome = papel[texto.index("MARIA")]
    assert nome["corpo"] == 0x11, nome
    assert not nome["negrito"]
    assert texto.index("MARIA") > texto.index("1 x Açaí Small")

    # 3. A resposta de serviço vem destacada e COM A PERGUNTA — muda o que se
    #    faz ao copo.
    servico = papel[texto.index("Levar")]
    assert servico["negrito"]
    assert texto.index("Levar") > texto.index("1 x Açaí Small")

    # 4. Os toppings, com as doses e SEM o título do grupo, depois de tudo o
    #    resto. Cada título era uma linha inteira num papel de 42 colunas.
    assert "Toppings:" not in texto
    assert texto.index("1x Leite condensado") > texto.index("Levar")
    assert texto.index("2x Nutella") > texto.index("Levar")

    # E o que é destaque tem de ser POUCO: um talão todo a negrito e todo
    # centrado é outra vez um talão sem hierarquia nenhuma. Os toppings leem-se
    # em corpo normal, e o corpo do talão é encostado à esquerda — só o
    # cabeçalho é que vai ao meio.
    assert not papel[texto.index("2x Nutella")]["negrito"]
    assert papel[texto.index("2x Nutella")]["corpo"] == 0
    assert not papel[texto.index("1 x Açaí Small")]["centrado"]


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
    assert "2x Extra caramelo" in texto
    assert "Levar" in texto
    assert "1x Extra caramelo" not in texto


def test_um_topping_GRATIS_de_grupo_escondido_nao_perde_a_DOSE():
    """A outra metade do defeito de cima, e esta perde-se sem custar um euro
    — que é exactamente porque ninguém dava por ela.

    O backoffice deixa configurar um grupo de TOPPINGS GRÁTIS com o
    interruptor `sai_na_fatura` desligado (`catalogo.py`: o interruptor é por
    GRUPO). Essas opções respondem "sim" a `_e_indicacao_de_servico` — preço
    zero e interruptor desligado — e as indicações de serviço eram
    deduplicadas com `dict.fromkeys`: duas doses de «Granola» saíam como
    «Toppings gratis: Granola», uma vez e sem dose. **A cozinha punha uma
    colher onde o cliente pediu duas.**

    E o que a dose NÃO pode fazer é encher o resto de ruído: uma pergunta de
    serviço respondida uma vez — que é o caso de todas elas — continua a sair
    «Consumir em loja: Levar», e nunca «1x Levar»."""
    venda = {"linhas": [{
        "produto_nome": "Açaí Small", "quantidade": 1,
        "opcoes": [
            {"id": "o0", "grupo_id": "g1", "nome": "Levar", "preco": 0,
             "nome_grupo": "Consumir em loja", "sai_na_fatura": False},
            {"id": "o1", "grupo_id": "g2", "nome": "Granola", "preco": 0,
             "nome_grupo": "Toppings gratis", "sai_na_fatura": False},
            {"id": "o1", "grupo_id": "g2", "nome": "Granola", "preco": 0,
             "nome_grupo": "Toppings gratis", "sai_na_fatura": False},
        ],
    }]}
    texto = [l["texto"] for l in _analisar(pedido_da_cozinha(venda))]
    assert "2x Granola" in texto
    assert "Levar" in texto
    assert "Consumir em loja: 1x Levar" not in texto


def test_a_quantidade_de_uma_PARTE_nao_imprime_ZERO_e_um_None_nao_apaga_a_ficha():
    """Três casos, e dois deles saíam do balcão hoje com o `"%d"` do papel.

    - **`0.3333`** — a quantidade de uma conta REPARTIDA, derivada do valor em
      cêntimos (`venda._partes_de_uma_linha`, `reparticao.quantidade_para`).
      Com `%d` imprimia «0 Açaí Regular»: a cozinha lê zero e não faz copo
      nenhum.
    - **`None`** — que `venda._linha_vendus` aceita e deixa gravado.
      Com `%d` levantava `TypeError: %d format: a number is required`, e a
      ficha INTEIRA desaparecia: quem carregou no botão via um erro e a
      cozinha ficava sem papel, com o resto do pedido lá dentro.
    - **`2`** — o caso normal, que continua a sair «2» e nunca «2,0».

    Uma quantidade que não se sabe sai como `?` e nunca como `1`: é a mesma
    regra do `_euros` do Z — escrever um número onde não se sabe é a mentira
    mais fácil de imprimir, e aqui ela mandava fazer um copo a menos."""
    venda = {"linhas": [
        {"produto_nome": "Açaí Regular", "quantidade": 0.3333},
        {"produto_nome": "Açaí Regular", "quantidade": None},
        {"produto_nome": "Açaí Regular", "quantidade": 2},
    ]}
    texto = [l["texto"] for l in _analisar(pedido_da_cozinha(venda))]
    assert "0,3333 x Açaí Regular" in texto
    assert "? x Açaí Regular" in texto
    assert "2 x Açaí Regular" in texto
    assert "0 x Açaí Regular" not in texto


def test_uma_linha_sem_nome_nem_opcoes_sai_na_mesma():
    texto = [l["texto"] for l in
             _analisar(pedido_da_cozinha({"linhas": [
                 {"produto_nome": "Café Expresso", "quantidade": 2}]}))]
    assert "2 x Café Expresso" in texto


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


def test_NaN_e_INFINITO_nao_apagam_a_ficha_da_cozinha():
    """O buraco que ficou do `None`, e que era o mesmo estrago.

    O `try` do `_quantidade` só apanhava o `float(bruto)`; a linha seguinte
    — `q == int(q)` — levanta `ValueError` com `nan` e `OverflowError` com
    `inf`. Medido pela rota real: `POST /pos/venda/{id}/linhas` com o corpo
    `{"produto_id":"prod-1","quantidade":NaN}` era ACEITE (o `json.loads` do
    FastAPI lê o literal), e a partir daí o botão «Imprimir Pedido» dava 500
    no ecrã — aquela conta nunca mais mandava ficha à cozinha, com o resto do
    pedido lá dentro.

    A porta está fechada nos DOIS sítios: `venda._recusa_quantidade_impossivel`
    já não deixa entrar (ver o teste de lá), e isto é o que salva as linhas
    que entraram antes.

    `?` e nunca `1`: escrever um número onde não se sabe manda fazer um copo
    a menos."""
    venda = {"linhas": [
        {"produto_nome": "Açaí Regular", "quantidade": float("nan")},
        {"produto_nome": "Açaí Large", "quantidade": float("inf")},
        {"produto_nome": "Café Expresso", "quantidade": 2},
    ]}
    texto = [l["texto"] for l in _analisar(pedido_da_cozinha(venda))]
    assert "? x Açaí Regular" in texto
    assert "? x Açaí Large" in texto
    # A ficha INTEIRA sai — era isto que se perdia, e não só a linha.
    assert "2 x Café Expresso" in texto


def test_uma_linha_que_DOBRA_continua_RECUADA_e_nao_na_coluna_zero():
    """**O erro que a docstring do `_partir` diz que este ficheiro existe para
    evitar**, e que estava a acontecer em dois dos cinco passos da ficha.

    Medido numa ficha de dois copos: «Toppings gratis: 2x Granola, Leite» /
    «condensado», e «Observações: sem granola por cima, muito» / «frio» — as
    duas continuações começavam na COLUNA 0, logo por cima de «Toppings:»,
    onde parecem um artigo novo. O bloco dos toppings (passo 4) já passava
    `recuo`; os passos 3 e 5 não.

    O recuo é o que distingue «isto é a continuação de cima» de «isto é
    coisa nova» num papel lido de relance e à distância de um braço."""
    venda = {"linhas": [{
        "produto_nome": "Açaí Regular", "quantidade": 1,
        "respostas_texto": [
            {"grupo_id": "g-nome", "nome_grupo": "Nome", "texto": "Rafaela"},
            {"grupo_id": "g-obs", "nome_grupo": "Observações",
             "texto": "sem granola por cima, muito frio"},
        ],
        "opcoes": [
            {"id": "t1", "grupo_id": "g2", "nome_grupo": "Toppings gratis",
             "nome": "Granola", "preco": 0, "sai_na_fatura": False},
            {"id": "t2", "grupo_id": "g2", "nome_grupo": "Toppings gratis",
             "nome": "Granola", "preco": 0, "sai_na_fatura": False},
            # Nome comprido de propósito: sem o título do grupo (que saiu do
            # papel em Agosto/2026) a linha deixou de dobrar, e este teste
            # existe para medir a DOBRA. Encurtá-lo era deixar de medir.
            {"id": "t3", "grupo_id": "g2", "nome_grupo": "Toppings gratis",
             "nome": "Leite condensado caseiro extra doce", "preco": 0,
             "sai_na_fatura": False},
            {"id": "t4", "grupo_id": "g3", "nome_grupo": "Toppings",
             "nome": "Nutella", "preco": 0.95},
        ],
    }]}
    texto = [l["texto"] for l in _analisar(pedido_da_cozinha(venda))]

    # 3. a indicação de serviço que dobra
    assert "2x Granola, Leite condensado caseiro extra" in texto
    assert "   doce" in texto
    assert "doce" not in texto

    # 5. a observação que dobra
    assert "Observações: sem granola por cima, muito" in texto
    assert "   frio" in texto
    assert "frio" not in texto


# --- A ficha rearrumada, com o papel a sério à frente ------------------------
#
# O dono mandou uma FOTO da ficha que sai na loja e disse como a quer:
#
#     1 x acai mini (tamanho da letra 4)
#     nome do cliente (tamanho da letra 3)
#     só a resposta de tampa ou sem tampa
#     1 x leite condensado
#     2 x morango
#
# Três mudanças, e a primeira inverte o que este ficheiro dizia até aqui:
#
# 1. **o PRODUTO passa a ser o maior elemento**, com o tamanho colado ao nome
#    («1 x Açaí Mini»), e o nome do cliente desce para segundo. A versão
#    anterior punha o nome em cima, e a razão escrita era boa — «é o que se
#    grita e o que se escreve no copo». Quem faz os açaís todos os dias diz
#    que o que precisa de ver primeiro é o que vai fazer;
# 2. **os títulos dos grupos saem** — nem «Tamanho:» nem «Toppings:». Num
#    papel estreito cada título é uma linha que empurra o resto para baixo;
# 3. **as perguntas de serviço saem só com a RESPOSTA**, sem o título.
#
# O que NÃO muda é a regra que não se negoceia: nada do que foi perguntado ao
# balcão desaparece do papel. O `test_NENHUMA_resposta_dada_ao_balcao_pode_
# faltar_na_ficha`, lá em cima, continua a valer sem uma linha alterada.

# GS ! 0x11 — 2× em largura E em altura: letra quadrada, 21 colunas.
_DOIS_PROPORCIONAL = 0x11


def _venda_da_foto():
    """A ficha da foto que o dono mandou, com o tamanho num grupo à parte —
    que é como o catálogo dele o tem."""
    return {
        "id": "aaaa-bbbb-cccc-1287",
        "criada_em": "2026-08-27T23:26:00+00:00",
        "linhas": [{
            "produto_nome": "Açaí", "quantidade": 1,
            "respostas_texto": [{"grupo_id": "g0", "nome_grupo": "Nome", "texto": "Débora"}],
            "opcoes": [
                {"id": "o0", "grupo_id": "g1", "nome": "Sim", "preco": 0,
                 "nome_grupo": "Consumir em loja ?", "sai_na_fatura": False},
                {"id": "ot", "grupo_id": "gt", "nome": "Mini", "preco": 0,
                 "nome_grupo": "Tamanho"},
                {"id": "o1", "grupo_id": "g2", "nome": "Leite Condensado", "preco": 0,
                 "nome_grupo": "Toppings"},
                {"id": "o2", "grupo_id": "g2", "nome": "Morango", "preco": 0,
                 "nome_grupo": "Toppings"},
                {"id": "o2", "grupo_id": "g2", "nome": "Morango", "preco": 0,
                 "nome_grupo": "Toppings"},
            ],
        }],
    }


def test_o_PRODUTO_COM_O_TAMANHO_e_a_primeira_linha_e_a_maior():
    """«1 x acai mini (tamanho da letra 4)» — literalmente o pedido."""
    papel = [l for l in _analisar(pedido_da_cozinha(_venda_da_foto())) if l["texto"].strip()]
    do_artigo = papel[3:]      # depois das duas linhas do cabeçalho e do traço
    primeira = do_artigo[0]
    assert "Açaí" in primeira["texto"] and "Mini" in primeira["texto"], primeira["texto"]
    assert primeira["corpo"] == _DOIS_PROPORCIONAL, (
        "A linha do produto não está no corpo 2 proporcional: %r" % primeira)


def test_o_NOME_do_cliente_vem_a_seguir_e_MENOR_que_o_produto():
    papel = [l for l in _analisar(pedido_da_cozinha(_venda_da_foto())) if l["texto"].strip()]
    do_artigo = papel[3:]
    nome = next(l for l in do_artigo if "DÉBORA" in l["texto"].upper())
    produto = do_artigo[0]
    assert nome["corpo"] == _DOIS_PROPORCIONAL, nome
    # Os dois ficaram do MESMO tamanho, por escolha do dono. A hierarquia
    # passa a vir da ORDEM e do negrito: o produto primeiro e a negrito, o
    # nome logo a seguir sem ele. Um dos dois maior obrigava a esticar a letra
    # (foi disso que ele se queixou) ou a dobrar os nomes compridos.
    assert produto["negrito"] and not nome["negrito"]
    assert do_artigo.index(nome) > do_artigo.index(produto)


def test_o_TAMANHO_deixa_de_ser_uma_linha_a_parte():
    """Subiu para a linha do produto. Repeti-lo em baixo era dizer duas vezes
    a mesma coisa num papel onde cada linha custa."""
    texto = _sem_comandos(pedido_da_cozinha(_venda_da_foto()))
    assert "1x Mini" not in texto
    assert "Tamanho" not in texto


def test_os_TITULOS_dos_grupos_desaparecem_do_papel():
    """Nem «Tamanho:» nem «Toppings:» — cada um era uma linha que empurrava o
    resto para baixo."""
    texto = _sem_comandos(pedido_da_cozinha(_venda_da_foto()))
    assert "Toppings:" not in texto
    assert "Tamanho:" not in texto


def test_a_pergunta_de_SERVICO_sai_so_com_a_resposta():
    """«Consumir em loja ?: Sim» passa a «Sim». Foi o dono a escolher, com o
    aviso de que «Sim» sozinho no papel diz pouco."""
    texto = _sem_comandos(pedido_da_cozinha(_venda_da_foto()))
    assert "Consumir em loja" not in texto
    assert "Sim" in texto


def test_os_TOPPINGS_mantem_as_doses():
    """Dois morangos são «2x Morango» e nunca «Morango, Morango» — nem uma vez
    só, que é o defeito que punha uma colher onde o cliente pediu duas."""
    texto = _sem_comandos(pedido_da_cozinha(_venda_da_foto()))
    assert "2x Morango" in texto
    assert "1x Leite Condensado" in texto


def test_um_produto_SEM_tamanho_nenhum_sai_com_o_nome_tal_e_qual():
    venda = _venda_da_foto()
    venda["linhas"][0]["produto_nome"] = "Água 33cl"
    venda["linhas"][0]["opcoes"] = []
    texto = _sem_comandos(pedido_da_cozinha(venda))
    assert "1 x Água 33cl" in texto or "1 x Água 33cl" in texto


def test_um_produto_que_JA_TEM_o_tamanho_no_nome_nao_o_repete():
    """O catálogo tem produtos antigos chamados «Açaí Small». Colar-lhes o
    tamanho outra vez dava «1 x Açaí Small Small» no papel da cozinha —
    ridículo, e o tipo de coisa que ninguém corrige porque ninguém percebe de
    onde veio."""
    venda = _venda_da_foto()
    venda["linhas"][0]["produto_nome"] = "Açaí Mini"
    texto = _sem_comandos(pedido_da_cozinha(venda))
    assert "Mini Mini" not in texto


def test_NADA_do_que_foi_perguntado_desaparece_com_a_arrumacao_nova():
    """A regra que não se negoceia, medida contra a arrumação nova: uma
    observação escrita ao balcão continua a sair no papel."""
    venda = _venda_da_foto()
    venda["linhas"][0]["respostas_texto"].append(
        {"grupo_id": "g9", "nome_grupo": "Observações", "texto": "sem granola"})
    texto = _sem_comandos(pedido_da_cozinha(venda))
    assert "sem granola" in texto
    assert "Débora" in texto or "DÉBORA" in texto


# --- O alinhamento, corrigido com o papel na mão -----------------------------


def test_o_CORPO_da_ficha_e_encostado_a_esquerda_e_so_o_cabecalho_vai_ao_meio():
    """**O comando de voltar à esquerda tem de chegar no INÍCIO de uma linha.**

    Estava no fim da linha do número (`"#1287  00:26" + ESC a 0`), e a maioria
    das impressoras térmicas só obedece ao `ESC a` quando ele chega antes de
    qualquer texto da linha — as outras aceitam-no a meio. O código dizia
    "alinha à esquerda" e o papel saía todo centrado; foi preciso a foto de
    uma ficha a sair na loja para se ver.

    Este teste mede a POSIÇÃO do comando, e não só a sua presença: um teste
    que procurasse `ESC a 0` no papel ficava verde com ele exactamente onde
    estava a falhar."""
    papel = pedido_da_cozinha(_venda_da_foto())
    linhas = papel.split("\n")
    a_esquerda = [i for i, l in enumerate(linhas) if "\x1ba\x00" in l]
    assert a_esquerda, "O papel nunca volta a alinhar à esquerda."
    for i in a_esquerda:
        antes = linhas[i].split("\x1ba\x00")[0]
        # Só comandos antes dele — nada de texto imprimível.
        assert not antes.replace("\x1b", "").replace("\x1d", "").strip("aE!@\x00\x01\x02\x03\x11"), (
            "O `ESC a 0` da linha %d vem depois de texto — a impressora ignora-o: %r"
            % (i, linhas[i]))


def test_o_cabecalho_CONTINUA_centrado():
    """A única coisa que vai ao meio, e é o que o dono quis manter."""
    papel = _analisar(pedido_da_cozinha(_venda_da_foto()))
    titulo = next(l for l in papel if "PEDIDO COZINHA" in l["texto"])
    assert titulo["centrado"]
    artigo = next(l for l in papel if "Açaí" in l["texto"])
    assert not artigo["centrado"], "O corpo da ficha não pode sair centrado."
    nome = next(l for l in papel if "DÉBORA" in l["texto"])
    assert not nome["centrado"]


def test_a_letra_do_produto_e_PROPORCIONAL_e_nao_esticada():
    """«as letras esta muito esticada para cima por que ?» — porque eu tinha
    pedido 4× em altura com a largura normal, para nada dobrar. Passa a ser
    2× nos dois sentidos: quadrada, e cabem 21 caracteres."""
    papel = _analisar(pedido_da_cozinha(_venda_da_foto()))
    artigo = next(l for l in papel if "Açaí" in l["texto"])
    largura = (artigo["corpo"] & 0xF0) >> 4
    altura = artigo["corpo"] & 0x0F
    assert largura == altura, (
        "A letra do produto está esticada: %d× em largura e %d× em altura."
        % (largura + 1, altura + 1))
    assert altura == 1, artigo   # 2× (o valor 1 é "o dobro")


def test_o_nome_do_cliente_tambem_e_proporcional():
    papel = _analisar(pedido_da_cozinha(_venda_da_foto()))
    nome = next(l for l in papel if "DÉBORA" in l["texto"])
    assert (nome["corpo"] & 0xF0) >> 4 == nome["corpo"] & 0x0F == 1, nome


def test_um_produto_de_nome_COMPRIDO_dobra_e_nao_da_a_volta():
    """A 2× cabem 21 caracteres. «Saco de Transporte» passa disso e tem de
    DOBRAR nas palavras — dar a volta punha a sobra encostada à esquerda, por
    baixo, onde parece um artigo novo."""
    venda = _venda_da_foto()
    venda["linhas"][0]["produto_nome"] = "Saco de Transporte App"
    venda["linhas"][0]["opcoes"] = []
    papel = _analisar(pedido_da_cozinha(venda))
    do_produto = [l for l in papel if (l["corpo"] & 0xF0) and l["texto"].strip()]
    assert len(do_produto) >= 2, [l["texto"] for l in do_produto]
    for l in do_produto:
        assert len(l["texto"].rstrip()) <= 21, l
