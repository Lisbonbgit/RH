"""Preços, IVA e construção da linha de venda — puro, sem I/O.

Regra de ouro deste módulo: NUNCA inventar um IVA. A app antiga tinha
`vat_rate = prod.get('vat_rate', 13)`, e bastava criar um refrigerante sem IVA
para o faturar a 13% em vez de 23% durante meses. Aqui, sem IVA não há venda.

Modelo (spec D7): um produto pertence a uma categoria — Venda ao Público ou
Vendas Aplicações — e tem UM preço e UM IVA.
"""
import unicodedata
from typing import Dict, List, Optional

# Códigos de imposto do Vendus.
_TAXAS = {23: "NOR", 13: "INT", 6: "RED", 0: "ISE"}

# Fonte de verdade única dos códigos válidos — reutilizada em catalogo.py
# (validação do ProdutoEntrada.tax_id) e aqui em erros_do_produto, para as
# duas nunca divergirem.
_CODIGOS_IVA_VALIDOS = frozenset(_TAXAS.values())


def tax_id_de_taxa(taxa) -> Optional[str]:
    """Converte uma percentagem de IVA no código do Vendus. Devolve None se a
    taxa for desconhecida ou ausente — quem chama tem de tratar isso."""
    try:
        return _TAXAS.get(int(round(float(taxa))))
    except (TypeError, ValueError):
        return None


# **Que personalização é que define uma VARIANTE do produto** — o tamanho.
#
# O dono criou UM artigo "Açaí" e pôs-lhe dentro os tamanhos (mini, small,
# regular, supreme); um "Nutella 2×" é um extra e não uma variante. Dois sítios
# precisam de saber a diferença e têm de a saber da MESMA maneira: o relatório
# diário (que parte o top de artigos por tamanho) e a ficha da cozinha (que
# cola o tamanho ao nome do produto, «1 x Açaí Mini»).
#
# Vive aqui, e não num deles, porque `precos.py` não importa nada do pacote:
# a ficha da cozinha a importar o relatório diário fazia um ciclo
# (talão → relatório → caixa → impressão → talão).
#
# ponytail: heurística pelo NOME do grupo, porque não há no catálogo nenhum
# campo que diga "este grupo define a variante". Sem acentos e sem maiúsculas,
# e por CONTER e não por igualar, para apanhar "Tamanho", "Tamanhos" e
# "Tamanho do açaí". Upgrade: um interruptor por grupo no backoffice no dia em
# que um grupo de variante não se chamar tamanho.
_PALAVRAS_DE_VARIANTE = ("tamanho", "size")


def _sem_acentos(texto) -> str:
    normalizado = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(c for c in normalizado if not unicodedata.combining(c)).lower()


def e_grupo_de_variante(grupo_nome, grupos_de_variante=None) -> bool:
    nome = _sem_acentos(grupo_nome)
    if not nome:
        return False
    if grupos_de_variante is not None:
        return any(_sem_acentos(g) == nome for g in grupos_de_variante)
    return any(palavra in nome for palavra in _PALAVRAS_DE_VARIANTE)


def _tem_mais_de_2_casas_decimais(valor) -> bool:
    """Diz se `valor` foi escrito com mais de 2 casas decimais.

    Porquê isto existe: `round(x, 2)` faz arredondamento bancário sobre a
    representação BINÁRIA do float, e isso come cêntimos sem avisar — p.ex.
    `round(2.675, 2)` dá `2.67`, não `2.68`. A defesa não é "arredondar
    melhor", é não deixar entrar valores com 3+ casas: se tudo o que entra
    numa linha tem no máximo 2 casas, a soma exacta também tem 2 casas e o
    `round(x, 2)` já não perde nada.

    E porque não `round(valor, 2) == valor`? Porque essa comparação volta a
    fazer contas em binário sobre o próprio valor que se quer proteger — é o
    mesmo arredondamento que estamos a tentar evitar, só que escondido numa
    comparação. Em vez disso, olhamos para o texto da representação decimal
    mais curta que reconstrói o float (a mesma que o Python usa em `repr`):
    é aí, sem arredondar nada, que se vê quantas casas decimais o valor tem
    "de origem" — e é por isso que `8.99`, `8.9`, `9` e `0` passam sempre,
    sejam int ou float.
    """
    texto = repr(float(valor))
    casas = texto.partition(".")[2]
    return len(casas) > 2


def id_vendus_da_variante(opcoes) -> Optional[int]:
    """O artigo do Vendus que o TAMANHO escolhido representa — ou `None`.

    Só uma opção de um grupo de VARIANTE pode desviar o artigo, e é uma
    restrição a sério, não uma formalidade: sem ela, ligar um topping ao
    artigo dele no Vendus para efeitos de stock passava a facturar o açaí
    inteiro como «Nutella». Um tamanho É outro artigo; um topping é o mesmo
    artigo com mais uma coisa dentro.

    A primeira que sirva, pela ordem em que a operadora as escolheu — uma
    linha com dois tamanhos não existe (o grupo é de escolha única), e se
    alguma vez existir, escolher em silêncio o último era pior do que
    escolher o primeiro: pelo menos assim a regra é dizível.

    Reutiliza `id_vendus_do_produto` para a validação do valor, que é a mesma
    (inteiro positivo, senão não vai): duas cópias dessa guarda acabavam a
    discordar, e a que discordasse mandava um `id` que o Vendus não reconhece
    para dentro de um documento fiscal.
    """
    for opcao in opcoes or []:
        if not e_grupo_de_variante(opcao.get("nome_grupo")):
            continue
        id_vendus = id_vendus_do_produto(opcao)
        if id_vendus is not None:
            return id_vendus
    return None


def id_vendus_do_produto(produto: Dict) -> Optional[int]:
    """O id do produto no Vendus (`vendus_ref`) pronto a viajar na linha como
    `id` — ou `None` quando não há nenhum que se possa enviar.

    **Porque é que este campo tem de ir.** Sem `id`, o Vendus não casa a
    linha pelo título: não encontrando referência nenhuma, CRIA um produto
    novo e inventa-lhe um código (`VACA…`). Medido na conta real: 95
    produtos e 7 títulos repetidos, o pior deles o "Açaí Mini" com 14 — um
    verdadeiro (id `171258472`, com categoria) e 13 órfãos sem categoria
    nenhuma. A 5 lojas × ~200 vendas/dia isso são milhares de produtos por
    mês e o catálogo do Vendus inutilizável em semanas.

    **Inteiro, e não a string tal e qual.** O corpo do documento vai em JSON,
    e o que está provado contra a conta real é `{"id": 171258472, …}` — um
    inteiro. O `vendus_ref` guarda-se como texto (`importacao.py` faz
    `str(p["id"])`), por isso a conversão vive aqui, no único sítio que o
    envia, e não espalhada por quem chama.

    **O que NÃO é um id positivo não vai.** Um produto criado à mão no nosso
    backoffice (que nunca veio da importação) não tem `vendus_ref`; um campo
    escrito à mão pode ter lá qualquer coisa. Nesses casos a linha sai como
    saía até aqui, só com o título, e o Vendus cria o produto — feio, mas
    inofensivo. O contrário é que era grave: mandar um `id` que o Vendus não
    reconheça arrisca a recusa do documento INTEIRO com o cliente à frente,
    e recusar a venda por causa disto seria muito pior do que um produto
    órfão no catálogo — a operadora ficava sem poder cobrar."""
    ref = produto.get("vendus_ref")
    if ref is None:
        return None
    texto = str(ref).strip()
    # `isdecimal()` e NÃO `isdigit()`: os dois parecem dizer o mesmo ("são
    # todos dígitos"), mas só o primeiro garante que o `int()` a seguir não
    # rebenta — `"²".isdigit()` é `True` e `int("²")` levanta `ValueError`.
    # Um `ValueError` cru vindo daqui parava a venda ao balcão por causa de
    # um campo do catálogo. De caminho, recusa o vazio, o negativo, o
    # decimal e o texto, sem nenhum deles entrar num documento fiscal real.
    if not texto.isdecimal():
        return None
    numero = int(texto)
    # `0` não é id de produto nenhum no Vendus — só lá chegaria escrito à
    # mão, e enviá-lo era arriscar a recusa do documento INTEIRO.
    if numero <= 0:
        return None
    return numero


def erros_do_produto(produto: Dict) -> List[str]:
    """Lista, em português, o que falta a um produto para poder ser vendido.

    O `tax_id` não só tem de existir como tem de ser um dos códigos do
    Vendus (NOR/INT/RED/ISE) — sem isto, um `tax_id` corrompido ou escrito
    à mão (ex.: 'XPTO') passava por "IVA definido" e só rebentava mais
    tarde, no `linha_de_venda`."""
    erros = []
    if produto.get("preco") is None:
        erros.append("Sem preço definido")
    tax_id = produto.get("tax_id")
    if not tax_id:
        erros.append("Sem IVA definido")
    elif tax_id not in _CODIGOS_IVA_VALIDOS:
        erros.append("Código de IVA desconhecido: %s" % tax_id)
    return erros


def _descricao_das_opcoes(opcoes: List[Dict]) -> str:
    """As opções como saem no título da linha: "Nutella 2×, Morango".

    Duas regras, e as duas nasceram de uma decisão do dono:

    - **As repetições agregam-se.** Cada toque na Nutella junta uma dose e
      cobra outra vez; escrever "Nutella, Nutella, Nutella" no talão do
      cliente é a mesma informação, ilegível. A ORDEM é a da primeira
      escolha — agregar não pode reordenar, porque a operadora escolheu por
      uma ordem e é essa que o cliente lê.
    - **Um grupo com `sai_na_fatura` desligado não aparece.** É o caso do
      "Nome" (que é do copo) e do "Consumir na loja" (que é da cozinha):
      não descrevem o produto e não têm valor fiscal.

    A excepção que não se negoceia: **uma opção com PREÇO aparece sempre**,
    esteja o interruptor como estiver. O cliente está a ser cobrado por ela
    e a fatura tem de o dizer — o interruptor esconde o que não custa nada,
    nunca um euro. Sem esta linha, desligar o interruptor por engano num
    grupo de toppings escondia da fatura o que lá foi cobrado.

    "Com preço" é `!= 0`, e não `> 0`: uma opção de preço NEGATIVO (um
    desconto gravado como opção) também mexe no dinheiro da linha, e com o
    `> 0` contava como grátis — desaparecia do título e levava o euro com
    ela, deixando a linha da Fatura Simplificada mais barata do que o que lá
    está escrito, sem rasto nenhum. O catálogo de hoje já não deixa gravar
    preços negativos (`ge=0` no `OpcaoEntrada`), mas o caminho até aqui
    continua aberto: as `opcoes` de um pedido são `List[Dict]` cru e o
    `pos_catalogo` devolve o preço gravado sem o revalidar, por isso uma
    opção negativa gravada antes dessa guarda ainda chega ao balcão.
    """
    contagem = {}   # nome -> doses
    ordem = []      # os nomes pela ordem da primeira escolha
    for o in opcoes:
        nome = o.get("nome")
        if not nome:
            continue
        pago = float(o.get("preco", 0) or 0) != 0
        if not pago and o.get("sai_na_fatura") is False:
            continue
        if nome not in contagem:
            ordem.append(nome)
            contagem[nome] = 0
        contagem[nome] += 1
    return ", ".join(
        nome if contagem[nome] == 1 else "%s %d×" % (nome, contagem[nome])
        for nome in ordem
    )


def linha_de_venda(
    produto: Dict,
    quantidade: int = 1,
    opcoes: Optional[List[Dict]] = None,
    preco_override: Optional[float] = None,
    tax_override: Optional[str] = None,
    desconto_pct: Optional[float] = None,
    desconto_eur: Optional[float] = None,
) -> Dict:
    """Constrói a linha no formato que o Vendus aceita.

    As personalizações somam ao preço unitário (é o que a app já faz em produção)
    e os nomes vão entre parêntesis no título, para saírem no talão.
    """
    # O diálogo do produto, no POS, deixa a operadora forçar o IVA de uma
    # linha. Esse valor tem de passar pelo mesmo crivo do IVA do produto
    # (erros_do_produto) — sem isto, um "XPTO" escrito à mão seguia sem
    # validação nenhuma até o Vendus recusar o documento à frente do
    # cliente, ou pior, aceitá-lo com o imposto errado.
    if tax_override is not None:
        if tax_override not in _CODIGOS_IVA_VALIDOS:
            raise ValueError("Código de IVA desconhecido: %s" % tax_override)
        tax_id = tax_override
    else:
        tax_id = produto.get("tax_id")

    if not tax_id:
        raise ValueError(
            "O produto '%s' não tem IVA definido e não pode ser vendido."
            % produto.get("nome", "?")
        )

    # Cuidado: `preco_override or produto[...]` daria 8,99 quando o override é 0.
    base = preco_override if preco_override is not None else produto.get("preco")
    if base is None:
        raise ValueError("O produto '%s' não tem preço definido." % produto.get("nome", "?"))
    if _tem_mais_de_2_casas_decimais(base):
        raise ValueError(
            "O preço %s do produto '%s' tem mais de 2 casas decimais — a fatura recusa-o "
            "para não perder um cêntimo no arredondamento." % (base, produto.get("nome", "?"))
        )

    opcoes = opcoes or []
    for o in opcoes:
        preco_opcao = o.get("preco", 0) or 0
        if _tem_mais_de_2_casas_decimais(preco_opcao):
            raise ValueError(
                "O preço %s da opção '%s' tem mais de 2 casas decimais — a fatura recusa-o "
                "para não perder um cêntimo no arredondamento."
                % (preco_opcao, o.get("nome", "?"))
            )
    extra = sum(float(o.get("preco", 0) or 0) for o in opcoes)

    titulo = produto.get("nome", "Produto")
    descricao = _descricao_das_opcoes(opcoes)
    if descricao:
        titulo = "%s (%s)" % (titulo, descricao)

    linha = {
        "title": titulo[:100],
        "qty": quantidade or 1,
        "gross_price": round(float(base) + extra, 2),
        "tax_id": tax_id,
    }

    # O id do produto no Vendus, quando o temos: é o que impede o Vendus de
    # criar um produto novo a cada venda (ver `id_vendus_do_produto`). Só
    # entra no dicionário SE existir — um `id: null` no corpo é pior do que
    # campo nenhum, porque é um valor enviado, e não um campo omitido.
    #
    # O `id` LIGA a linha ao produto certo e mais nada: está provado contra a
    # conta real que não substitui nem o título nem o preço. Emitido com o
    # nosso título e um preço diferente do do catálogo
    # (`{"id": 171258472, "title": "Açaí Mini (Nutella 2×)", "gross_price":
    # 7.75}`), o documento saiu a 7,75 € — o NOSSO preço — e a leitura
    # devolveu o NOSSO título. Por isso o `gross_price`, o `tax_id`, o título
    # e os descontos acima ficam exactamente como estavam.
    # **O TAMANHO manda no artigo.** No nosso catálogo há UM açaí e o tamanho
    # é uma personalização dele; no Vendus, o Mini, o Small, o Regular e o
    # Supreme são quatro artigos diferentes. Sem isto, todas as linhas viajavam
    # com a referência do produto e as cinco lojas facturaram meses de açaís
    # como «Açaí Regular», fosse qual fosse o tamanho — o dinheiro certo, o
    # artigo errado, e o catálogo do Vendus a não servir para nada.
    id_vendus = id_vendus_da_variante(opcoes) or id_vendus_do_produto(produto)
    if id_vendus is not None:
        linha["id"] = id_vendus

    # O Vendus só aceita um dos dois por linha. O € tem precedência.
    if desconto_eur:
        if _tem_mais_de_2_casas_decimais(desconto_eur):
            raise ValueError(
                "O desconto de %s € tem mais de 2 casas decimais — a fatura recusa-o "
                "para não perder um cêntimo no arredondamento." % desconto_eur
            )
        # Tecto: o desconto não pode exceder o bruto da linha INTEIRA (preço
        # unitário × quantidade, já com as personalizações somadas) — sem
        # isto, nada impedia um desconto maior do que a própria linha, o que
        # produziria discount_amount > gross_price*qty: uma linha NEGATIVA
        # numa fatura real, ou seja, uma nota de crédito escondida dentro de
        # uma fatura (buraco achado no Plano 2B, Task 3).
        bruto_linha = round(linha["gross_price"] * linha["qty"], 2)
        if float(desconto_eur) > bruto_linha:
            raise ValueError(
                "O desconto de %s € é maior do que o valor desta linha (%s €) — "
                "produziria uma linha negativa numa fatura real." % (desconto_eur, bruto_linha)
            )
        linha["discount_amount"] = round(float(desconto_eur), 2)
    elif desconto_pct:
        linha["discount_percentage"] = float(desconto_pct)

    return linha
