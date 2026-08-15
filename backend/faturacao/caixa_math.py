"""Matemática da sessão de caixa — puro, sem I/O (Task 3 do Plano 2A, spec §7.2/§7.6).

`esperado` é o número que a funcionária tem de bater ao contar a gaveta: o
fundo de maneio que entrou de manhã, mais as vendas em dinheiro do dia, mais
as entradas de dinheiro registadas, menos as saídas. Vive isolado do resto do
módulo (sem Mongo, sem FastAPI) para poder ser testado a sério — é esta parte
que tem de estar matematicamente certa, porque é o que sustenta a
responsabilização quando a contagem não bate e alguém tem de explicar a
diferença.

Precisão: quem chama (faturacao/caixa.py) já recusou à entrada qualquer valor
com mais de 2 casas decimais, reutilizando o crivo de faturacao/precos.py
(`_tem_mais_de_2_casas_decimais`) — por isso aqui basta arredondar o
resultado final a 2 casas para limpar o ruído do binário, sem risco de comer
um cêntimo (ver a docstring dessa função para a explicação completa).
"""
from typing import Dict, List


def total_por_tipo(movimentos: List[Dict], tipo: str) -> float:
    """Soma os valores dos movimentos de um único tipo ('entrada' ou 'saida')."""
    total = sum(float(m.get("valor", 0) or 0) for m in (movimentos or []) if m.get("tipo") == tipo)
    return round(total, 2)


def total_movimentos(movimentos: List[Dict]) -> float:
    """Saldo líquido dos movimentos: entradas somam, saídas subtraem."""
    return round(total_por_tipo(movimentos, "entrada") - total_por_tipo(movimentos, "saida"), 2)


def esperado(fundo: float, vendas_dinheiro: float, movimentos: List[Dict]) -> float:
    """O valor que devia estar na gaveta: fundo de maneio + vendas em
    dinheiro + entradas - saídas."""
    return round(float(fundo or 0) + float(vendas_dinheiro or 0) + total_movimentos(movimentos), 2)


def diferenca(esperado_valor: float, contado: float) -> float:
    """contado - esperado: positivo é sobra na gaveta, negativo é falta. É
    este número que a funcionária tem de explicar quando não bate — por
    isso o fecho (faturacao/caixa.py) NUNCA bloqueia por causa dele, só o
    regista (Task 4 do Plano 2A, spec §7.6)."""
    return round(float(contado or 0) - float(esperado_valor or 0), 2)
