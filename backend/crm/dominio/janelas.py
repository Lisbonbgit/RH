"""O horário de receção de uma loja: até duas janelas "HH:MM", em hora de Lisboa.

Porta de src/Dominio/Lojas/Janelas.php do CRM autónomo (dossiê §5.6). Sem
janelas, a loja recebe a qualquer hora do dia de trabalho. Na API as janelas
são as quatro horas planas de `CAMPOS`; na base ficam em lista (`janelas:
[{inicio, fim}]`, plano §1 "Janelas"; a conversão é a
`validador_loja.janelas_para_lista` / `campos_de_janelas`, T2.6).
"""
import re

# Pela ordem da tabela dos campos da loja (dossiê §5.2).
CAMPOS = ("janela1_inicio", "janela1_fim", "janela2_inicio", "janela2_fim")

MENSAGEM_FORMATO = "A hora tem de estar no formato HH:MM."

# `fullmatch` e `[0-9]`: o `$` aceitaria um "\n" final e o `\d` os
# algarismos árabes (plano §10). As horas não se aparam: " 10:00" é um erro.
_FORMATO = re.compile(r"([01][0-9]|2[0-3]):[0-5][0-9]")


def hora(valor):
    """Uma hora, validada sozinha: `(hora, erro)`. Vazia ("" ou `None`) fica `None`."""
    if valor is None or (isinstance(valor, str) and valor == ""):
        return None, None
    if not isinstance(valor, str) or _FORMATO.fullmatch(valor) is None:
        return None, MENSAGEM_FORMATO
    return valor, None


def erros(loja) -> dict:
    """A coerência das quatro horas de uma loja: `{campo: erro}`, vazio se estiver tudo bem.

    As horas têm de vir já validadas uma a uma com `hora` ("HH:MM" ou
    `None`; as chaves que faltam contam como `None`, as outras chaves da loja
    ignoram-se). Início e fim vão juntos, o início vem antes do fim, e a
    janela 2 só existe com a janela 1 e começa depois do fim dela. Numa
    alteração chama-se com a loja já alterada (T2.6/T2.11).

    Os erros vêm pela ordem em que o PHP os junta; o `+=` dos arrays do PHP
    não substitui um erro que já lá está (daí o `setdefault`): a janela 2 só
    com o fim diz "Indique também o início." e não "Preencha primeiro a
    janela 1.".
    """
    inicio1, fim1, inicio2, fim2 = (_hora_validada(loja, campo) for campo in CAMPOS)

    resultado = {**_erros_janela("janela1", inicio1, fim1), **_erros_janela("janela2", inicio2, fim2)}

    if inicio2 is not None or fim2 is not None:
        if inicio1 is None and fim1 is None:
            resultado.setdefault("janela2_inicio", "Preencha primeiro a janela 1.")
        elif fim1 is not None and inicio2 is not None and inicio2 <= fim1:
            resultado.setdefault("janela2_inicio", "A janela 2 tem de começar depois do fim da janela 1.")

    return resultado


def _hora_validada(loja, campo):
    # O PHP (strict_types) rebentava com TypeError no `?string` da função que
    # lê as quatro horas; aqui também, em vez de comparar outra coisa com
    # texto em silêncio. "HH:MM" tem largura fixa: comparar o texto é
    # comparar a hora.
    valor = loja.get(campo)
    if valor is not None and not isinstance(valor, str):
        raise TypeError(f"{campo} tem de ser uma hora já validada (HH:MM ou None), não {type(valor).__name__}")
    return valor


def _erros_janela(janela, inicio, fim) -> dict:
    if inicio is not None and fim is None:
        return {f"{janela}_fim": "Indique também o fim."}
    if inicio is None and fim is not None:
        return {f"{janela}_inicio": "Indique também o início."}
    if inicio is not None and inicio >= fim:
        return {f"{janela}_fim": "O fim tem de ser depois do início."}
    return {}
