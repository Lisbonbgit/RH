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
# Cinco chegam e o Vendus aceita-as (medido contra a conta real).
CASAS_DA_QUANTIDADE = 5


def repartir_centimos(total_centimos: int, partes: int) -> List[int]:
    """Reparte `total_centimos` por `partes`, e as partes **somam sempre** o
    total.

    O cêntimo que sobra vai para as PRIMEIRAS partes, não para a última: a
    diferença entre duas pessoas nunca passa de um cêntimo, e quem paga
    primeiro é quem leva o cêntimo a mais — o que é mais fácil de explicar ao
    balcão do que a última pessoa levar todos os que sobraram.
    """
    if partes < 1:
        raise ValueError("Uma conta reparte-se por pelo menos uma parte.")
    base, resto = divmod(int(total_centimos), int(partes))
    return [base + (1 if i < resto else 0) for i in range(partes)]


def quantidade_para(valor_centimos: int, preco: float) -> float:
    """A quantidade que, ao preço dado, produz exactamente este valor.

    Não devolve a fracção "bonita" (1/3): devolve a que o Vendus, ao fazer
    `qty × gross_price` e arredondar a 2 casas, transforma no valor exacto
    desta parte. E **confirma-o antes de devolver** — o Vendus arredonda de
    forma previsível, mas a defesa deste módulo nunca é acreditar num
    comportamento externo; é medi-lo. Medido: `0.3333 × 8.99` sai 3,00 € na
    conta real, e é assim que se escolhe o número.
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
