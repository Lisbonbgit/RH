"""O texto do pedido que vai para a cozinha.

Puro e sem I/O de propósito: recebe a venda tal como `venda._venda_publica`
a devolve e produz texto. O agente de impressão (Plano 3) ainda não existe —
quando existir, é este texto que sai em papel, sem se mexer aqui.

O formato é o que o dono escreveu, e cada linha dele tem uma razão: o NOME em
maiúsculas na linha do artigo porque é o que se escreve no copo e é o que a
pessoa da cozinha procura primeiro; o serviço (levar/comer aqui) logo a
seguir porque muda o que ela faz com o copo; e as doses à frente do topping
porque "2x Nutella" lê-se de relance e "Nutella, Nutella" não.
"""
from typing import Dict, List


def _doses(opcoes: List[Dict]) -> List[str]:
    """As opções agregadas, pela ordem da primeira escolha. Mesma regra do
    título da fatura (`precos._descricao_das_opcoes`), outro formato: aqui a
    dose vem À FRENTE, que é como uma ficha de cozinha se lê."""
    contagem = {}
    ordem = []
    for o in opcoes or []:
        nome = o.get("nome")
        if not nome:
            continue
        if nome not in contagem:
            ordem.append(nome)
            contagem[nome] = 0
        contagem[nome] += 1
    return ["%dx %s" % (contagem[n], n) for n in ordem]


def _nome_no_copo(linha: Dict) -> str:
    """A PRIMEIRA resposta de texto da linha. Convenção, não configuração:
    quem põe um grupo de texto num açaí está a pedir o nome do cliente, e um
    ajuste por grupo para dizer onde é que cada resposta aparece no talão
    seria uma definição a mais para o mesmo resultado."""
    for r in linha.get("respostas_texto") or []:
        texto = (r.get("texto") or "").strip()
        if texto:
            return texto
    return ""


def pedido_da_cozinha(venda: Dict) -> str:
    partes = ["Pedido\n"]
    for linha in venda.get("linhas") or []:
        nome = _nome_no_copo(linha)
        cabecalho = "%d %s" % (linha.get("quantidade", 1), linha.get("produto_nome") or "?")
        if nome:
            cabecalho += " — %s" % nome.upper()
        bloco = [cabecalho]

        # As opções SEM preço de grupos que não vão à fatura são as
        # indicações de serviço (Levar / Comer aqui): vão logo por baixo do
        # artigo, sem dose, porque só há uma.
        servico = [o.get("nome") for o in (linha.get("opcoes") or [])
                   if o.get("sai_na_fatura") is False and o.get("nome")]
        bloco.extend(dict.fromkeys(servico))

        toppings = _doses([o for o in (linha.get("opcoes") or [])
                           if o.get("sai_na_fatura") is not False])
        if toppings:
            bloco.append("")
            bloco.extend(toppings)
        partes.append("\n".join(bloco) + "\n")
    return "\n".join(partes)
