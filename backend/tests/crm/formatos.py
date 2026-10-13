"""Verificadores do formato dos instantes, para os testes do CRM (correções do
plano, linha "§1 Decisões (Tempo) / T2.8"; provados em
test_instantes_gravados.py).

- `instantes_fora_do_formato(documento)`: num documento gravado (ou numa
  resposta), os `*_em` e `*_desde` têm de ser `AAAA-MM-DDTHH:MM:SSZ` ou null,
  e o `atualizado_em` um carimbo `AAAA-MM-DDTHH:MM:SS.ffffffZ` (nunca null).
  Os testes das escritas aplicam-no ao que o duplo guardou: T2.10 ao
  `documento_loja` e à loja gravada, T2.11 à interação e ao `$set` do PATCH,
  T2.13 às definições.
- `usos_proibidos_do_relogio(codigo, e_o_relogio=False)`: o varrimento do
  código do pacote `crm` — nunca `.isoformat` e, fora do `crm/relogio.py`,
  nem `strftime` nem leituras do relógio.

As expressões são escritas aqui de propósito, sem as do `crm/relogio.py`: um
erro no formato da produção não pode passar por estar copiado no teste.
"""
import ast
import re
from datetime import datetime

_INSTANTE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_CARIMBO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z")


def _existe(texto, formato):
    try:
        datetime.strptime(texto, formato)
    except ValueError:
        return False
    return True


def _instante_valido(valor):
    return (
        isinstance(valor, str)
        and _INSTANTE.fullmatch(valor) is not None
        and _existe(valor, "%Y-%m-%dT%H:%M:%SZ")
    )


def _carimbo_valido(valor):
    return (
        isinstance(valor, str)
        and _CARIMBO.fullmatch(valor) is not None
        and _existe(valor, "%Y-%m-%dT%H:%M:%S.%fZ")
    )


def _e_instante(campo):
    return isinstance(campo, str) and (campo.endswith("_em") or campo.endswith("_desde"))


def instantes_fora_do_formato(documento):
    """[(caminho, valor)] dos instantes fora do formato, pela ordem do
    documento; procura também em subdocumentos e listas (caminho com pontos,
    ex.: "paragens.1.feita_em"). [] quando está tudo certo."""
    problemas = []

    def _visitar(valor, caminho):
        if isinstance(valor, dict):
            for campo, dentro in valor.items():
                aqui = f"{caminho}.{campo}" if caminho else str(campo)
                if campo == "atualizado_em":
                    if not _carimbo_valido(dentro):
                        problemas.append((aqui, dentro))
                elif _e_instante(campo):
                    if dentro is not None and not _instante_valido(dentro):
                        problemas.append((aqui, dentro))
                else:
                    _visitar(dentro, aqui)
        elif isinstance(valor, list):
            for posicao, dentro in enumerate(valor):
                _visitar(dentro, f"{caminho}.{posicao}" if caminho else str(posicao))

    _visitar(documento, "")
    return problemas


# Formatam ou leem o relógio: só o crm/relogio.py os pode usar.
_SO_NO_RELOGIO = {"now", "utcnow", "today", "fromtimestamp", "utcfromtimestamp", "strftime"}
# time.time() e time.time_ns(): só com o módulo time à esquerda (o `time` de
# outro objeto — ex.: uma hora `datetime.time` — não é o relógio).
_DO_MODULO_TIME = {"time", "time_ns"}


def usos_proibidos_do_relogio(codigo, e_o_relogio=False):
    """[(linha, nome)] dos usos proibidos no código-fonte `codigo`, pela ordem
    em que aparecem. Lê o AST: as docstrings e os comentários que explicam a
    regra não contam. `e_o_relogio=True` para o próprio crm/relogio.py, onde
    só o isoformat é proibido."""
    encontrados = []
    for no in ast.walk(ast.parse(codigo)):
        if not isinstance(no, ast.Attribute):
            continue
        if no.attr == "isoformat":
            encontrados.append((no.lineno, no.col_offset, "isoformat"))
        elif e_o_relogio:
            continue
        elif no.attr in _SO_NO_RELOGIO:
            encontrados.append((no.lineno, no.col_offset, no.attr))
        elif no.attr in _DO_MODULO_TIME and isinstance(no.value, ast.Name) and no.value.id == "time":
            encontrados.append((no.lineno, no.col_offset, "time." + no.attr))
    encontrados.sort(key=lambda e: (e[0], e[1]))  # estável: na mesma posição fica a ordem do ast.walk
    return [(linha, nome) for (linha, _coluna, nome) in encontrados]
