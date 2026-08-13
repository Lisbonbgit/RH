"""Preços, IVA e construção da linha de venda — puro, sem I/O.

Regra de ouro deste módulo: NUNCA inventar um IVA. A app antiga tinha
`vat_rate = prod.get('vat_rate', 13)`, e bastava criar um refrigerante sem IVA
para o faturar a 13% em vez de 23% durante meses. Aqui, sem IVA não há venda.

Modelo (spec D7): um produto pertence a uma categoria — Venda ao Público ou
Vendas Aplicações — e tem UM preço e UM IVA.
"""
from typing import Dict, List, Optional

# Códigos de imposto do Vendus.
_TAXAS = {23: "NOR", 13: "INT", 6: "RED", 0: "ISE"}


def tax_id_de_taxa(taxa) -> Optional[str]:
    """Converte uma percentagem de IVA no código do Vendus. Devolve None se a
    taxa for desconhecida ou ausente — quem chama tem de tratar isso."""
    try:
        return _TAXAS.get(int(round(float(taxa))))
    except (TypeError, ValueError):
        return None


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


def erros_do_produto(produto: Dict) -> List[str]:
    """Lista, em português, o que falta a um produto para poder ser vendido."""
    erros = []
    if produto.get("preco") is None:
        erros.append("Sem preço definido")
    if not produto.get("tax_id"):
        erros.append("Sem IVA definido")
    return erros


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
    tax_id = tax_override or produto.get("tax_id")
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
    nomes = [o.get("nome") for o in opcoes if o.get("nome")]
    if nomes:
        titulo = "%s (%s)" % (titulo, ", ".join(nomes))

    linha = {
        "title": titulo[:100],
        "qty": quantidade or 1,
        "gross_price": round(float(base) + extra, 2),
        "tax_id": tax_id,
    }

    # O Vendus só aceita um dos dois por linha. O € tem precedência.
    if desconto_eur:
        if _tem_mais_de_2_casas_decimais(desconto_eur):
            raise ValueError(
                "O desconto de %s € tem mais de 2 casas decimais — a fatura recusa-o "
                "para não perder um cêntimo no arredondamento." % desconto_eur
            )
        linha["discount_amount"] = round(float(desconto_eur), 2)
    elif desconto_pct:
        linha["discount_percentage"] = float(desconto_pct)

    return linha
