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


def tirado_da_gaveta_a_mais(vendas_dinheiro: float) -> float:
    """Quanto é que saiu da gaveta ALÉM do que as vendas deste turno lá
    puseram — `0.00` no turno normal.

    **Um turno só pode tirar da gaveta o que lá pôs**, e isso lê-se nas VENDAS
    EM DINHEIRO: o dinheiro das faturas menos o das devoluções
    (`soma_vendas_dinheiro`). Se essa soma fica negativa, saiu da gaveta
    dinheiro que aquele turno nunca recebeu. Medido pelas rotas reais: fatura
    de 24,14 € paga 5,00 em dinheiro + 19,14 em Multibanco, açaí de 20,40 €
    devolvido em DINHEIRO → `vendas_dinheiro` **−15,40 €**. A operadora conta
    a gaveta, bate certo — e saíram 15,40 € que aquele turno não recebeu.

    **NÃO é `fundo − esperado`, e essa era a versão anterior desta função.**
    O `esperado` inclui os movimentos de caixa, e por isso falhava nos dois
    sentidos, medidos os dois por `_resumo_do_turno`:

    - **mascarado**: os mesmos −15,40 € com um reforço de troco de 20,00 €
      dão `esperado` 54,60 € e aviso **0,00** — o vazamento continua lá e o
      ecrã fica sem uma palavra. Bastava uma entrada de 15,40 € para o apagar;
    - **falso positivo**: sem devolução nenhuma, vendas em dinheiro de 24,14 €
      e uma saída de 30,00 € para o cofre davam aviso **5,86 €**. Sangrias e
      pagamentos a fornecedor em dinheiro são rotina (têm rota e ecrã
      próprios, `POST /pos/caixa/movimento`): numa loja com depósito diário
      isto acendia todas as noites, e a noite em que acendesse pela razão
      verdadeira era igual às outras.

    Nenhum movimento de caixa mexe nas vendas em dinheiro — é isso que torna
    este número impossível de mascarar e impossível de acender por engano.

    Não é uma recusa (uma devolução legítima tem de poder acontecer, e o
    `nota_credito.pagamentos_da_fatura` explica porque é que recusar por meio
    de pagamento fecha a porta sem abrir outra): é o NÚMERO, para ele aparecer
    no Ponto de Caixa e no Z ao lado da gaveta, em vez de não aparecer em
    lado nenhum. Em cêntimos inteiros, como todo o dinheiro da casa."""
    return max(0, -_centimos(vendas_dinheiro)) / 100.0


def devolucoes_acima_do_recebido(notas_credito: List[Dict] = None) -> float:
    """**O leitor que faltava a `nota_credito.devolucao.acima_do_recebido`.**

    Quanto é que as devoluções deste turno passaram o que as faturas delas
    tinham recebido NAQUELE meio de pagamento — `0.00` no caso normal. É a
    EXPLICAÇÃO do que saiu da gaveta a mais, e é por isso que anda ao lado
    dela: sem este número, «faltam 15,40 €» é uma acusação, e com ele é uma
    frase.

    **E tem PREDICADO PRÓPRIO no ecrã**, e não o do
    `tirado_da_gaveta_a_mais`: são duas perguntas diferentes e podem
    responder-se ao contrário uma da outra. Um turno com uma fatura de 100,00 €
    paga em dinheiro e outra de 11,29 € paga 5,00 em dinheiro + 6,29 em
    Multibanco, creditada em DINHEIRO por 9,85 €, tem `vendas_dinheiro`
    +95,15 € (a gaveta do turno está bem) e 4,85 € devolvidos por um meio que
    aquela fatura não recebeu. Encostar esta frase ao aviso da gaveta fazia-a
    desaparecer com ele — e este campo voltava a ser só de escrita, que é
    exactamente o defeito que ele veio fechar.

    O campo era gravado com o comentário «o gestor encontra isso depois» — e
    um `grep` em todo o repositório dava só a escrita. Ele não encontrava:
    não havia leitor nenhum, em ecrã nenhum.

    Só as `emitida`, a mesma regra de `por_tipo_de_pagamento` e pela mesma
    razão: uma nota por apurar não devolveu nada a ninguém."""
    return round(
        sum(
            _centimos((nota.get("devolucao") or {}).get("acima_do_recebido"))
            for nota in notas_credito or []
            if nota.get("estado") == "emitida"
        ) / 100.0,
        2,
    )


def diferenca(esperado_valor: float, contado: float) -> float:
    """contado - esperado: positivo é sobra na gaveta, negativo é falta. É
    este número que a funcionária tem de explicar quando não bate — por
    isso o fecho (faturacao/caixa.py) NUNCA bloqueia por causa dele, só o
    regista (Task 4 do Plano 2A, spec §7.6)."""
    return round(float(contado or 0) - float(esperado_valor or 0), 2)


def soma_vendas_dinheiro(vendas: List[Dict], notas_credito: List[Dict] = None) -> float:
    """A parte em DINHEIRO das vendas emitidas de uma sessão (Task 4 do
    Plano 2B, spec §6/§7.6) — é isto que entra no `vendas_dinheiro` de
    `esperado`, acima.

    **E MENOS o que saiu da gaveta em devoluções.** Uma nota de crédito
    devolvida em dinheiro é dinheiro que a operadora tirou da gaveta e pôs na
    mão do cliente; se não entrasse aqui, a gaveta fechava a acusar uma falta
    que ninguém sabia explicar — que é exactamente o buraco que a nota de
    crédito veio tapar. Uma devolução por Multibanco, Uber, Bolt ou Glovo NÃO
    passa por este filtro (o `tipo_fiscal` dela não é `NU`) e não mexe na
    gaveta: fica na linha do meio de pagamento dela, negativa, no
    desdobramento aqui em baixo.

    Só conta vendas `estado == "emitida"` (uma venda aberta ou cancelada
    nunca foi facturada, não pode contar para a gaveta) e, dentro de cada
    uma, só os pagamentos com `tipo_fiscal == "NU"` — um pagamento MISTO
    (parte dinheiro, parte multibanco) só soma a parte em dinheiro. Lê o
    `tipo_fiscal` do SNAPSHOT gravado em cada pagamento no momento da
    emissão (faturacao/fiscal.py::finalizar), nunca reconsulta
    fat_tipos_pagamento ao vivo — um tipo de pagamento reconfigurado
    amanhã não pode mudar retroactivamente o Z de uma sessão já fechada.

    **Calculado a partir de `por_tipo_de_pagamento`, e não em paralelo com
    ela.** As duas respondem à mesma pergunta (quanto entrou, e em quê) e
    são mostradas lado a lado no mesmo ecrã: o Ponto de Caixa e o Z põem o
    "Vendas em dinheiro" logo por cima da linha "Dinheiro" do
    desdobramento. Duas somas independentes que "têm de concordar" acabam
    sempre por discordar — neste módulo já aconteceu três vezes — e aqui a
    discordância seria visível ao balcão, na mesma janela, sem ninguém
    saber qual das duas está certa. Por isso só existe uma soma: esta filtra
    as linhas `NU` daquela."""
    return round(
        sum(
            linha["total"]
            for linha in por_tipo_de_pagamento(vendas, notas_credito)
            if linha["tipo_fiscal"] == "NU"
        ),
        2,
    )


def _centimos(valor) -> int:
    """Um valor em euros nos cêntimos INTEIROS que ele vale.

    Os pagamentos entram no Mongo já limitados a 2 casas decimais (a soma
    deles é validada contra o total da venda em `fiscal.py::finalizar`, e o
    total sai de `precos.linha_de_venda`, que recusa 3 casas), por isso o
    `round` aqui não pode comer nada — só desfaz o ruído binário de
    `8.99 * 100 == 898.9999...`."""
    return int(round(float(valor or 0) * 100))


def por_tipo_de_pagamento(vendas: List[Dict], notas_credito: List[Dict] = None) -> List[Dict]:
    """Quanto entrou em CADA tipo de pagamento nas vendas emitidas de uma
    sessão — dinheiro, multibanco, Uber Eats, Bolt, Glovo — **menos o que
    saiu por devoluções**.

    **O dinheiro segue o meio de pagamento**, que é a decisão do dono: uma
    nota de crédito devolvida em dinheiro sai da gaveta, uma devolvida no
    Glovo fica no Glovo, e a gaveta não mexe. Aqui isso é uma única regra e
    não um caso especial: a devolução é um valor NEGATIVO na linha do meio
    de pagamento por onde foi devolvida, e tudo o que lê esta tabela — o
    `soma_vendas_dinheiro` aqui em cima (e logo o `esperado` da gaveta), o
    Ponto de Caixa e o Z — passa a contá-la sem uma linha nova.

    **Não há aqui uma segunda contabilidade das devoluções**, de propósito:
    a nota de crédito não tem uma coluna própria nem um total à parte no
    fecho. Se tivesse, haveria dois números a explicar a mesma gaveta.

    É a pergunta que o Z não sabia responder: ele dava o total em dinheiro
    (`soma_vendas_dinheiro`) e mais nada, e ao fechar ninguém conseguia
    bater o rolo do terminal de Multibanco nem o extracto do Glovo contra o
    turno — o gestor fechava o mês a somar à mão. A MESMA função serve o
    Ponto de Caixa (a conferência a meio do turno) e o Z (o fecho): não são
    dois cálculos que têm de dar o mesmo, é um só, chamado duas vezes.

    Agrupa pelo `tipo_pagamento_id` do SNAPSHOT gravado em cada pagamento
    (`fiscal.py::finalizar`), nunca por `fat_tipos_pagamento` ao vivo —
    renomear o "Uber Eats" para "Uber" amanhã não pode reescrever o Z de
    ontem. O `nome` e o `tipo_fiscal` que saem são os do PRIMEIRO pagamento
    visto para esse id, pela mesma razão.

    Soma em CÊNTIMOS INTEIROS e só converte a euros no fim: `0.29 + 1.15 +
    10.20` em vírgula flutuante dá `11.639999999999999`, e um turno tem
    centenas de parcelas.

    A ordem é por total decrescente (o que mais entrou primeiro, que é o
    que a operadora procura), com o nome a desempatar — determinística, para
    duas leituras seguidas do mesmo turno não trocarem as linhas de sítio.
    """
    linhas: Dict = {}
    for venda in vendas or []:
        if venda.get("estado") != "emitida":
            continue
        for pagamento in venda.get("pagamentos") or []:
            # O `nome` como chave de recurso: um pagamento sem
            # `tipo_pagamento_id` (não devia existir) não pode desaparecer
            # da conta — dinheiro que se cala é o pior desfecho possível.
            chave = pagamento.get("tipo_pagamento_id") or pagamento.get("nome")
            linha = linhas.get(chave)
            if linha is None:
                linha = linhas[chave] = {
                    "tipo_pagamento_id": pagamento.get("tipo_pagamento_id"),
                    "nome": pagamento.get("nome"),
                    "tipo_fiscal": pagamento.get("tipo_fiscal"),
                    "centimos": 0,
                    "quantos": 0,
                }
            linha["centimos"] += _centimos(pagamento.get("valor"))
            linha["quantos"] += 1

    # As devoluções, pela MESMA porta e com o sinal ao contrário. Só as
    # `emitida`: uma nota de crédito cuja emissão ficou por apurar não
    # devolveu nada a ninguém, e descontá-la da gaveta era mandar a operadora
    # justificar uma falta que talvez não exista.
    #
    # O `devolucao` é o retrato do tipo de pagamento gravado no instante em
    # que a nota saiu (nome, `tipo_fiscal`, id) — a mesma regra dos
    # pagamentos aqui em cima, e pela mesma razão: renomear o "Glovo" para
    # "Glovo PT" amanhã não pode reescrever o Z de ontem.
    for nota in notas_credito or []:
        if nota.get("estado") != "emitida":
            continue
        devolucao = nota.get("devolucao") or {}
        chave = devolucao.get("tipo_pagamento_id") or devolucao.get("nome")
        linha = linhas.get(chave)
        if linha is None:
            linha = linhas[chave] = {
                "tipo_pagamento_id": devolucao.get("tipo_pagamento_id"),
                "nome": devolucao.get("nome"),
                "tipo_fiscal": devolucao.get("tipo_fiscal"),
                "centimos": 0,
                "quantos": 0,
            }
        linha["centimos"] -= _centimos(devolucao.get("valor"))
        linha["quantos"] += 1

    saida = [
        {
            "tipo_pagamento_id": linha["tipo_pagamento_id"],
            "nome": linha["nome"],
            "tipo_fiscal": linha["tipo_fiscal"],
            "total": linha["centimos"] / 100.0,
            # Quantos pagamentos (não quantas vendas): uma venda paga metade
            # em dinheiro e metade em multibanco conta uma vez em cada linha.
            "quantos": linha["quantos"],
        }
        for linha in linhas.values()
    ]
    saida.sort(key=lambda linha: (-linha["total"], linha["nome"] or ""))
    return saida
