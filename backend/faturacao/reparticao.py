"""A matemática de repartir uma conta — pura, sem I/O.

Tudo aqui se conta em **cêntimos inteiros**, nunca em vírgula flutuante. É a
mesma razão que está no cabeçalho de `precos.py`: `round()` sobre a
representação binária come cêntimos sem avisar. Numa conta dividida isso não
é um arredondamento infeliz — é a soma das faturas a declarar à AT um valor
diferente do que entrou na gaveta, e a acumular em cada divisão do dia.
"""
from typing import List

# Casas decimais da QUANTIDADE. São mais do que as 2 dos preços de propósito,
# e por uma razão diferente: uma quantidade não é dinheiro, é o que PRODUZ o
# dinheiro, e é preciso resolução para o valor final cair no cêntimo certo.
# Medido contra a conta real: a 3 casas, qty 0.333 facturava 2,99 € (errado —
# a parte era 3,00 €); a 4 casas, qty 0.3333 já facturava os 3,00 € certos.
# Cinco dá margem extra para preços mais altos do cardápio (ver
# test_a_quantidade_produto_de_preco_acima_dos_10_euros, 17,98 €), mas isso
# é suposição, não medição — ninguém mostrou o Vendus a preservar uma 5.ª
# casa decimal da quantidade.
CASAS_DA_QUANTIDADE = 5


def repartir_centimos(total_centimos: int, partes: int) -> List[int]:
    """Reparte `total_centimos` por `partes`, e as partes **somam sempre** o
    total.

    O cêntimo que sobra vai para as PRIMEIRAS partes, não para a última: a
    diferença entre duas pessoas nunca passa de um cêntimo, e quem paga
    primeiro é quem leva o cêntimo a mais — o que é mais fácil de explicar ao
    balcão do que a última pessoa levar todos os que sobraram.

    `total_centimos` tem de ser mesmo um `int` — 899, não 8.99. É uma
    unidade fácil de confundir com a irmã deste ficheiro em `fiscal.py`
    (`_distribuir_centimos`, essa sim em EUROS): esta recusa apanha um total
    em euros passado como `float` — 8.99, mas também um redondo como 9.0,
    que sem o `isinstance` passava em silêncio e devolvia cêntimos cem vezes
    a menos (`repartir_centimos(9.0, 3)` dava `[3, 3, 3]` em vez de
    `[300, 300, 299]`).

    O que esta guarda NÃO apanha é um total em euros passado já como `int`
    (9 em vez de 900): olhando só para o valor, é indistinguível de uma
    conta genuína de 9 cêntimos, e nenhuma guarda resolve isso a partir do
    número sozinho — a defesa aí tem de estar no chamador, não aqui.
    """
    if partes < 1:
        raise ValueError("Uma conta reparte-se por pelo menos uma parte.")
    if not isinstance(total_centimos, int):
        raise ValueError(
            "repartir_centimos espera cêntimos inteiros (ex.: 899 para "
            "8,99 €), não euros — recebeu %r." % (total_centimos,)
        )
    base, resto = divmod(int(total_centimos), int(partes))
    return [base + (1 if i < resto else 0) for i in range(partes)]


def quantidade_para(valor_centimos: int, preco: float) -> float:
    """A quantidade que, ao preço dado, produz exactamente este valor.

    Não devolve a fracção "bonita" (1/3): devolve a que o Vendus, ao fazer
    `qty × gross_price` e arredondar a 2 casas, transforma no valor exacto
    desta parte. E **confirma-o antes de devolver** — o Vendus arredonda de
    forma previsível, mas a defesa deste módulo nunca é acreditar num
    comportamento externo; é medi-lo.

    O que foi medido contra a conta real: a 3 casas, `0.333 × 8.99` fatura
    2,99 € (errado); a 4 casas, `0.3333 × 8.99` já fatura os 3,00 € certos.
    Isso valida a RESOLUÇÃO de `CASAS_DA_QUANTIDADE`, não o número exacto que
    esta função devolve hoje — a 5 casas (o valor em vigor),
    `quantidade_para(300, 8.99)` devolve `0.3337`, não `0.3333`: outro
    candidato, encontrado pela mesma verificação, que também acerta o
    cêntimo.
    """
    if not preco:
        raise ValueError(
            "Não há quantidade que produza %d cêntimos a um preço de %s."
            % (valor_centimos, preco)
        )
    alvo = valor_centimos / 100.0
    q = round(alvo / preco, CASAS_DA_QUANTIDADE)
    if round(q * preco, 2) == alvo:
        return q
    # O arredondamento da divisão caiu do lado errado. Anda um passo mínimo
    # para cada lado — mais do que isso e o preço é que não produz este valor.
    # Para os preços reais de um item de açaí (abaixo dos 1000 €) este ramo é
    # matematicamente inalcançável — a prova está na docstring do teste que o
    # cobre (test_a_quantidade_recusa_quando_nenhum_candidato_bate_certo).
    # Fica na mesma: é uma rede para lá desse domínio, e o pior que este laço
    # faz, mesmo errado, é recusar a fatura — nunca emiti-la com o cêntimo
    # trocado.
    passo = 10 ** -CASAS_DA_QUANTIDADE
    for candidato in (round(q + passo, CASAS_DA_QUANTIDADE),
                      round(q - passo, CASAS_DA_QUANTIDADE)):
        if round(candidato * preco, 2) == alvo:
            return candidato
    raise ValueError(
        "Nenhuma quantidade com %d casas produz %.2f € ao preço de %s — "
        "repartir esta linha perderia um cêntimo."
        % (CASAS_DA_QUANTIDADE, alvo, preco)
    )


def parte_acumulada(
    total_centimos: int, quantidade_total: int, quantidade_ate_aqui: int
) -> int:
    """Quanto vale, em cêntimos, **a primeira `quantidade_ate_aqui` de uma
    linha** que vale `total_centimos` por `quantidade_total` — o repartidor
    das notas de crédito PARCIAIS.

    As quantidades vêm nos inteiros que valem a 5 casas decimais
    (`nota_credito._quantidade_em_inteiros`), nunca em vírgula flutuante.

    ## Porque não `repartir_centimos` nem `_distribuir_centimos`

    Os dois repartem um total por partes que se conhecem TODAS ao mesmo
    tempo — as pessoas de uma conta dividida, as linhas de um desconto
    global. Uma fatura creditada em parciais não é isso: a segunda parcial
    pode ser amanhã, e quem a calcula já não tem a primeira à frente para
    lhe compensar o cêntimo. O que se reparte aqui reparte-se **no tempo**,
    e a única forma de a soma fechar é cada parcial ser a DIFERENÇA de dois
    acumulados — `parte_acumulada(…, antes + pedida) − parte_acumulada(…,
    antes)`. Telescopa: creditada a linha inteira, em quantas vezes for, a
    soma é `parte_acumulada(L, Q, Q) − parte_acumulada(L, Q, 0)`, que é
    exactamente `L`.

    O arredondamento é o meio-cêntimo para CIMA em aritmética inteira —
    `(2·num + den) // (2·den)`, o mesmo idioma de
    `mapa_imposto._base_em_centimos`, e pela mesma razão: `round()` sobre
    floats faz arredondamento bancário sobre a representação binária.

    **O que isto corrige, medido.** Uma linha de 10 × 0,05 € (0,50 €)
    creditada em 100 fatias de 0,1 devolvia **1,00 € — o dobro**: cada
    fatia valia `round(0,1 × 0,05, 2) = 0,01 €` por si só, e cem cêntimos
    são um euro. Com o acumulado, as mesmas 100 fatias devolvem 0,50 €. E
    em 4986 faturas ao acaso creditadas em duas parciais fraccionárias, a
    soma devolvida diferia da fatura em 1279 delas (441 a mais, 838 a
    menos, até 0,03 €); passa a zero.
    """
    if quantidade_total <= 0:
        return 0
    ate_aqui = max(0, min(int(quantidade_ate_aqui), int(quantidade_total)))
    numerador = int(total_centimos) * ate_aqui
    denominador = int(quantidade_total)
    sinal = -1 if numerador < 0 else 1
    return sinal * ((2 * abs(numerador) + denominador) // (2 * denominador))


def ordem_das_fatias(valores_por_linha: List[List[int]], alvos: List[int]) -> List[List[int]]:
    """Quem leva cada fatia de cada linha, para cada pessoa aterrar no seu
    ALVO — devolve, por linha, `ordem[pessoa] = índice da fatia que ela leva`.

    **O defeito que isto fecha, dito pelo dono a olhar para o ecrã:** uma conta
    de 23,40 € dividida por dois dava **11,71 e 11,69**. A soma estava certa e
    ninguém perdia dinheiro, mas 23,40 divide-se ao meio sem resto e o ecrã
    prometia um número que ninguém faz de cabeça.

    A causa é a repartição ser feita LINHA A LINHA (é a única forma de cada
    parte sair como uma fatura com artigos, que é o que o Vendus precisa): cada
    linha ímpar dá o seu cêntimo à primeira pessoa, e duas linhas ímpares
    empilham dois cêntimos nela. Com quatro, 11,72 contra 11,68.

    A correcção não muda as fatias — muda quem as leva. Os valores de cada
    linha são os mesmos (é por isso que a soma continua a fechar por
    construção, e que cada fatia continua a ter uma quantidade que o Vendus
    factura ao cêntimo); o que se escolhe aqui é a PESSOA de cada uma, dando
    sempre a maior fatia a quem está mais longe do seu alvo.

    Os alvos vêm de `repartir_centimos(total, n)`, e é isso que dá a regra que
    o dono descreveu: divisível, todos pagam o mesmo; indivisível, **a primeira
    pessoa é que paga o cêntimo a mais**.

    Uma fatia que não existe (a pessoa que não leva nada daquela linha) conta
    como zero e entra na ordenação como qualquer outra — pode calhar a
    qualquer pessoa, e é o que se quer: é a fatia mais pequena de todas.
    """
    n = len(alvos)
    falta = list(alvos)
    ordens = []
    for valores in valores_por_linha:
        if len(valores) != n:
            raise ValueError(
                "Cada linha tem de trazer uma fatia por pessoa — %d fatias "
                "para %d pessoas." % (len(valores), n)
            )
        # As fatias da maior para a menor, e as pessoas da maior falta para a
        # menor. O desempate é sempre pelo ÍNDICE ascendente, nos dois lados:
        # com tudo igual, o cêntimo a mais fica com a primeira pessoa, que é a
        # regra que o balcão diz em voz alta.
        fatias = sorted(range(n), key=lambda j: (-valores[j], j))
        pessoas = sorted(range(n), key=lambda i: (-falta[i], i))
        ordem = [0] * n
        for k, pessoa in enumerate(pessoas):
            ordem[pessoa] = fatias[k]
            falta[pessoa] -= valores[fatias[k]]
        ordens.append(ordem)

    # **A escolha acima é MÍOPE, e sozinha não chega.** Decide linha a linha,
    # sem saber o que as linhas seguintes ainda trazem, e por isso há contas em
    # que aterra ao lado: medido em 300 contas ao acaso, 19 ficavam com as
    # pessoas certas ao cêntimo mas com o cêntimo a mais na pessoa errada
    # (`[3536, 3537, 3537, 3537]` em vez de `[3537, 3537, 3537, 3536]`).
    # A soma nunca esteve em risco — isto são sempre as MESMAS fatias, trocadas
    # de mãos — mas a regra do balcão é que quem paga o cêntimo a mais é a
    # primeira pessoa, e uma regra que falha uma vez em quinze não é regra.
    #
    # A reparação é uma troca de fatias entre quem está acima do alvo e quem
    # está abaixo, numa linha onde a troca aproxime os dois sem os fazer passar
    # ao lado um do outro. Cada troca aproxima pelo menos um cêntimo, por isso
    # o ciclo acaba; o tecto está lá na mesma, porque um ciclo sem tecto sobre
    # dados de fora é um ciclo que um dia não acaba.
    somas = [
        sum(valores[ordem[i]] for valores, ordem in zip(valores_por_linha, ordens))
        for i in range(n)
    ]
    for _ in range(2 * n * len(ordens) + 1):
        acima = [i for i in range(n) if somas[i] > alvos[i]]
        abaixo = [i for i in range(n) if somas[i] < alvos[i]]
        if not acima or not abaixo:
            break
        i, j = acima[0], abaixo[0]
        for valores, ordem in zip(valores_por_linha, ordens):
            diferenca = valores[ordem[i]] - valores[ordem[j]]
            if diferenca <= 0:
                continue
            if diferenca > somas[i] - alvos[i] or diferenca > alvos[j] - somas[j]:
                continue
            ordem[i], ordem[j] = ordem[j], ordem[i]
            somas[i] -= diferenca
            somas[j] += diferenca
            break
        else:
            # Não há troca que aproxime sem ultrapassar. Fica como está: as
            # partes continuam a somar o total exacto (são as mesmas fatias) e
            # continuam a menos de um cêntimo umas das outras — só o cêntimo a
            # mais é que pode calhar a outra pessoa que não a primeira.
            break
    return ordens
