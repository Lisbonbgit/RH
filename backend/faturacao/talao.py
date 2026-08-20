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


def _e_indicacao_de_servico(opcao: Dict) -> bool:
    """Se uma opção é uma INDICAÇÃO DE SERVIÇO (Levar / Comer aqui) e não uma
    escolha que se prepara com a colher.

    A pergunta é a MESMA do título da fatura
    (`precos._descricao_das_opcoes`) e a mesma do resumo do ecrã
    (`ehIndicacaoDeServico`, no POS): o interruptor `sai_na_fatura` esconde o
    que não custa nada, nunca um euro. Uma opção COM PREÇO é sempre uma
    escolha, esteja o interruptor como estiver.

    A regra estava escrita neste ficheiro ("as opções SEM preço de grupos que
    não vão à fatura") mas não estava no código, que só olhava para o
    interruptor: um "Extra caramelo" pago de um grupo com o interruptor
    desligado ia parar às indicações de serviço, dito uma vez e sem dose — a
    cozinha punha UMA colher onde o cliente pagou DUAS, e a fatura, essa,
    cobrava as duas ("Extra caramelo 2×")."""
    return opcao.get("sai_na_fatura") is False and float(opcao.get("preco", 0) or 0) == 0


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
        # artigo, sem dose, porque só há uma. É `_e_indicacao_de_servico` que
        # responde, e é lá que está escrito porquê.
        servico = [o.get("nome") for o in (linha.get("opcoes") or [])
                   if _e_indicacao_de_servico(o) and o.get("nome")]
        bloco.extend(dict.fromkeys(servico))

        toppings = _doses([o for o in (linha.get("opcoes") or [])
                           if not _e_indicacao_de_servico(o)])
        if toppings:
            bloco.append("")
            bloco.extend(toppings)
        partes.append("\n".join(bloco) + "\n")
    return "\n".join(partes)
