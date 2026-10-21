"""As datas das rotas: o dia `AAAA-MM-DD`, em hora de Lisboa (F3).

Uma rota por dia (`crm_rotas.data`, índice único). O dia chega no caminho
(`/rotas/{data}`) e nos parâmetros (`de`, `ate`) como texto e lê-se aqui; o
"hoje" vem de `relogio.hoje()`. O texto tem largura fixa, por isso ordena
como as datas (o filtro `$gte`/`$lte` do `GET /rotas`).

Armadilhas (plano F3 §10): `fullmatch` e `[0-9]` (o `$` e o `match`
aceitavam um "\\n" final, o `\\d` os algarismos árabes e de largura total);
nunca `fromisoformat` (no Python 3.11 aceita "20261012"), `strftime` nem
`isoformat` (varrimento do tests/crm/test_instantes_gravados.py): o texto
escreve-se por f-string.
"""
import re
from datetime import date, timedelta

from .campos_loja import DIAS

# Não se criam rotas a mais de um ano de hoje (422, T3.4).
MAXIMO_DIAS_FUTURO = 365

_FORMATO = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")


def ler_data(valor) -> "date | None":
    """O dia `AAAA-MM-DD` de `valor`, ou None se não for exatamente esse texto
    com um dia que exista (nada antes nem depois, só algarismos ASCII). O
    ano 0, o 29 de fevereiro de um ano comum e o mês 13 dão None."""
    if not isinstance(valor, str):
        return None
    partes = _FORMATO.fullmatch(valor)
    if partes is None:
        return None
    try:
        return date(*(int(p) for p in partes.groups()))
    except ValueError:  # ano 0, mês 13, 29 de fevereiro num ano comum…
        return None


def texto_data(dia: date) -> str:
    """O dia como `AAAA-MM-DD`, sempre com a mesma largura (o inverso de
    `ler_data`)."""
    return f"{dia.year:04d}-{dia.month:02d}-{dia.day:02d}"


def dia_da_semana(dia: date) -> str:
    """O nome do dia da semana, com os nomes dos `dias_fechada` da loja
    (`campos_loja.DIAS`: "seg" … "dom")."""
    return DIAS[dia.weekday()]


def somar_dias(dia: date, n: int) -> date:
    """O dia `n` dias de calendário depois (ou antes, com `n` negativo)."""
    return dia + timedelta(days=n)
