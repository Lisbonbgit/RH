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
import textwrap
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


# --- O relatório Z, em papel --------------------------------------------------
#
# Puro como o resto do ficheiro: recebe o dicionário que `caixa.fechar_caixa`
# devolve — os MESMOS números que a operadora acabou de ver no ecrã — e
# devolve texto. **Não soma nada.** Nem um cêntimo: a aritmética do dinheiro é
# do servidor e já foi feita (`caixa_math`, `mapa_imposto`), e um total
# recalculado aqui era uma segunda verdade a contradizer o ecrã que a
# funcionária assinou.
#
# 42 colunas, que é a largura de uma impressora de 80 mm com a fonte normal.
# Um Z mais largo do que o papel não fica ilegível: fica ENGANADOR — as
# colunas dão a volta e a diferença da gaveta aparece por baixo do rótulo
# errado.

_LARGURA = 42


def _euros(valor) -> str:
    """`8,99` — vírgula decimal, como tudo o que a funcionária lê.

    `None` sai como `—` e nunca como `0,00`: o Z distingue "não há" de "é
    zero" em pelo menos dois sítios que custam dinheiro (uma taxa
    desconhecida no mapa de imposto, uma contagem que não foi feita), e
    escrever zero onde não se sabe é a mentira mais fácil de imprimir."""
    if valor is None:
        return "—"
    return ("%.2f" % float(valor)).replace(".", ",")


def _dobrar(texto: str) -> str:
    """O texto dobrado às `_LARGURA` colunas, nas palavras.

    **Dobrado aqui e nunca pela impressora.** Uma impressora que recebe uma
    linha maior do que o papel corta-a onde calhar — a meio de uma palavra, a
    meio de um número — e o resto aparece encostado à esquerda por baixo, onde
    parece o valor do rótulo seguinte. Foi isso que este ficheiro mediu com o
    nome de uma caixa comprido: 51 colunas de rótulo num papel de 42.

    `textwrap` da biblioteca padrão, e não um laço escrito à mão: dobrar texto
    nas palavras tem casos de borda (uma palavra maior do que a linha, espaços
    a mais) que já estão resolvidos há vinte anos."""
    return "\n".join(textwrap.wrap(texto, _LARGURA) or [""])


def _linha(esquerda: str, direita: str) -> str:
    """Rótulo à esquerda, valor encostado à direita, espaço pelo meio — e nunca
    cortado: um rótulo comprido de mais dobra-se e empurra o valor para a
    linha seguinte, em vez de o mandar dar a volta.

    Um valor que dá a volta aparece por baixo do rótulo SEGUINTE, e é assim
    que se lê uma diferença de caixa como se fosse outra coisa."""
    espaco = _LARGURA - len(esquerda) - len(direita)
    if espaco >= 1:
        return esquerda + " " * espaco + direita
    # Não cabem os dois na mesma linha: o rótulo fica em cima, dobrado, e o
    # valor por baixo, encostado à direita — também ele dobrado, porque o
    # comprido tanto pode ser um (o nome de uma caixa) como o outro.
    linhas = textwrap.wrap(esquerda, _LARGURA) or [""]
    linhas += [parte.rjust(_LARGURA) for parte in (textwrap.wrap(direita, _LARGURA) or [""])]
    return "\n".join(linhas)


def _titulo(texto: str) -> str:
    return "\n" + texto + "\n" + "-" * _LARGURA


def relatorio_z(z: Dict) -> str:
    """O Z do turno, tal como sai no papel que a funcionária assina.

    A ordem é a que ela lê de cima para baixo quando está a contar a gaveta:
    primeiro QUEM e QUANDO (é o que identifica o papel daqui a um mês),
    depois a GAVETA (fundo, vendas em dinheiro, entradas, saídas, esperado,
    contado, diferença — a conta que ela acabou de fazer com as notas na
    mão), só depois o desdobramento por meio de pagamento e o mapa de
    imposto, que são para o gestor e para a contabilista.

    **Os avisos vão ao FIM e por extenso.** O que ficou por cobrar, o que
    saiu da gaveta a mais, as devoluções acima do recebido: são as três
    coisas que fazem alguém pegar no telefone, e um número solto numa tabela
    não faz ninguém pegar em telefone nenhum."""
    partes = [
        "RELATORIO Z".center(_LARGURA),
        "Fecho de caixa".center(_LARGURA),
        "=" * _LARGURA,
        _linha("Caixa", str(z.get("caixa_id") or "—")),
        _linha("Sessao", str(z.get("id") or "—")),
        _linha("Aberta por", str((z.get("aberta_por") or {}).get("nome") or "—")),
        _linha("Aberta em", str(z.get("aberta_em") or "—")),
        _linha("Fechada por", str((z.get("fechada_por") or {}).get("nome") or "—")),
        _linha("Fechada em", str(z.get("fechada_em") or "—")),
        _titulo("GAVETA"),
        _linha("Fundo de maneio", _euros(z.get("fundo"))),
        _linha("Vendas em dinheiro", _euros(z.get("vendas_dinheiro"))),
        _linha("Entradas", _euros(z.get("entradas"))),
        _linha("Saidas", _euros(z.get("saidas"))),
        _linha("ESPERADO", _euros(z.get("esperado"))),
        _linha("CONTADO", _euros(z.get("contado"))),
        _linha("DIFERENCA", _euros(z.get("diferenca"))),
    ]

    partes.append(_titulo("PAGAMENTOS"))
    for linha in z.get("pagamentos") or []:
        partes.append(_linha(str(linha.get("nome") or "—"), _euros(linha.get("total"))))
    # SEMPRE presente, mesmo a zero — a mesma regra do ecrã (`caixa.py`): quem
    # lê o papel não pode ter de adivinhar se a ausência da linha quer dizer
    # "está tudo cobrado" ou "esta versão não sabe responder a isso".
    partes.append(_linha("Por registar", _euros(z.get("pagamentos_por_registar"))))

    partes.append(_titulo("IMPOSTO"))
    partes.append(_linha("Taxa  Doc.        Base", "IVA"))
    for linha in z.get("mapa_imposto") or []:
        taxa = linha.get("taxa")
        # Uma taxa que o sistema não conhece sai como `?` e o total continua
        # a somar — nunca se inventa uma percentagem, e nunca se deita fora o
        # dinheiro (ver `mapa_imposto.mapa_de_imposto`).
        rotulo = "%s%%" % _euros(taxa) if taxa is not None else "?"
        partes.append(_linha(
            "%-6s%-5s%s" % (rotulo, linha.get("documentos") or 0, _euros(linha.get("base"))),
            _euros(linha.get("iva")),
        ))
    partes.append(_linha("Base tributavel", _euros(z.get("base_tributavel"))))
    partes.append(_linha("IVA", _euros(z.get("iva_total"))))
    partes.append(_linha("TOTAL FATURADO", _euros(z.get("total_faturado"))))
    partes.append(_linha("Documentos emitidos", str(z.get("quantos_documentos") or 0)))

    avisos = []
    abertas = z.get("contas_abertas") or {}
    if abertas.get("quantas"):
        avisos.append(
            "Ficaram %s contas ABERTAS neste turno, no valor de %s. Nao "
            "entraram neste Z e nao foram cobradas." % (
                abertas.get("quantas"), _euros(abertas.get("total")))
        )
    if z.get("tirado_da_gaveta_a_mais"):
        avisos.append(
            "Sairam %s da gaveta a mais do que este turno recebeu em "
            "dinheiro." % _euros(z.get("tirado_da_gaveta_a_mais"))
        )
    if z.get("devolucoes_acima_do_recebido"):
        avisos.append(
            "Devolveram-se %s por um meio de pagamento que as faturas "
            "devolvidas nao receberam." % _euros(z.get("devolucoes_acima_do_recebido"))
        )
    if avisos:
        partes.append(_titulo("ATENCAO"))
        partes.extend(_dobrar(aviso) for aviso in avisos)

    partes.append("")
    partes.append("Assinatura: ______________________")
    return "\n".join(partes) + "\n"
