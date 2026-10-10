"""Números que chegam no JSON e o arredondamento do PHP.

O CRM autónomo valida os números com `is_int` / `is_float` + `is_finite` e
arredonda com o `round()` do PHP. Em Python há três armadilhas (plano §9;
dossiê §2.1), e as regras do domínio passam todas por aqui:

- o `round()` do Python arredonda para o par (`round(50.5) == 50`, o que
  aceitaria um GPS a 51 m); o do PHP vai para longe do zero (50,5 → 51);
- `True` é um `int` em Python (`isinstance(True, int)`), e o PHP nunca conta
  um bool como número: daí `type(x) is int`;
- o `json` do Python aceita `NaN`, `Infinity` e `1e400` (→ inf) e lê
  inteiros de qualquer tamanho; o PHP lia um inteiro fora dos 64 bits como
  `float` (e INF se nem num float coubesse).
"""
import math
from decimal import ROUND_HALF_UP, Context, Decimal

# Os inteiros que o json_decode do PHP lê como `int` (PHP_INT_MIN e
# PHP_INT_MAX), que são também os que o MongoDB guarda (8 bytes).
_INTEIRO_MIN = -(2**63)
_INTEIRO_MAX = 2**63 - 1

# Precisão do Decimal que chega para qualquer float finito (até ~1,8e308, 309
# algarismos) mais as casas pedidas; a de omissão (28) dava InvalidOperation
# no quantize de um número grande.
_ALGARISMOS_DO_MAIOR_FLOAT = 310


def e_inteiro_json(valor) -> bool:
    """O `is_int` do PHP sobre um valor do JSON: um inteiro de 64 bits.

    Nunca um bool, nem um decimal (`1.0` é float, como no PHP), nem um
    inteiro fora dos 64 bits (que o PHP lia como float).
    """
    return type(valor) is int and _INTEIRO_MIN <= valor <= _INTEIRO_MAX


def e_numero_json(valor) -> bool:
    """O `is_int($x) || (is_float($x) && is_finite($x))` do PHP sobre um valor
    do JSON: um inteiro ou um decimal finito.

    Nunca um bool, um texto ("1"), `inf` ou `nan`. Um inteiro fora dos 64 bits
    conta se couber num float (o PHP lia-o como float); maior do que isso, o
    PHP lia INF e não conta.
    """
    if type(valor) is int:
        try:
            float(valor)
        except OverflowError:
            return False
        return True
    return type(valor) is float and math.isfinite(valor)


def arredondar(valor, casas: int = 0) -> float:
    """O `round($valor, $casas)` do PHP: meio-para-longe-do-zero.

    50,5 → 51, 49,5 → 50, -0,5 → -1; às 6 casas, 38,1234566 → 38,123457.
    Como o PHP, conta o número tal como se escreve (o `repr`, a forma mais
    curta que volta ao mesmo float), e não o binário: 0,285 às 2 casas dá
    0,29. Devolve sempre um float, também para inteiros (round(5, 6) → 5.0);
    quem precisar de um int converte, como o `(int) round(…)` do autónomo.

    Só aceita números do JSON (e_numero_json) e `casas` inteiro ≥ 0: quem
    chama verifica primeiro, e isto é a rede para um bool não virar 1.0.
    """
    if not e_numero_json(valor):
        raise ValueError(f"arredondar só aceita números do JSON (int ou float finito), não {type(valor).__name__}")
    if type(casas) is not int or casas < 0:
        raise ValueError("as casas decimais têm de ser um inteiro ≥ 0")
    # float() primeiro, como o PHP (round de um int com casas ≥ 0 é o float dele).
    escrito = Decimal(repr(float(valor)))
    contexto = Context(prec=_ALGARISMOS_DO_MAIOR_FLOAT + casas)
    return float(escrito.quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP, context=contexto))
