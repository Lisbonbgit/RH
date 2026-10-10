"""As fases do funil e a ordem das regras automáticas.

Porta de src/Dominio/Fases.php do CRM autónomo (desenho original §4.1). A
ORDEM é a das regras automáticas (F4/F5), que só sobem nela; a exceção é
"Não interessado", que passa a loja a `perdida` exceto se for `cliente`. À
mão, na ficha, a fase muda sempre (dossiê §5.1).
"""

# Igual a ORDEM em frontend/src/lib/crm/fases.js (test_consistencia_frontend.py, T2.20): manter numa só linha.
ORDEM = ("perdida", "potencial", "contactada", "amostra", "cliente")


def fase_valida(fase) -> bool:
    """Só um dos nomes exatos da ORDEM (texto, minúsculas, sem espaços).

    É o `in_array($fase, ORDEM, true)` do PHP: "Cliente", " cliente ", um
    número (a posição) ou uma lista não são fases.
    """
    return isinstance(fase, str) and fase in ORDEM
