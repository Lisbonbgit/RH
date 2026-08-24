"""O texto do pedido que vai para a cozinha.

Puro e sem I/O de propósito: recebe a venda tal como `venda._venda_publica`
a devolve e produz o que se imprime. O agente de impressão já leva isto ao
papel numa loja a sério — o que se muda aqui sai em papel na cozinha.

## Quem lê isto

Está de costas para o balcão, com as mãos ocupadas e o papel à distância de
um braço. Por isso a ficha tem HIERARQUIA, e a hierarquia é feita de comandos
ESC/POS a sério (`GS !` para o corpo, `ESC E` para o negrito, `ESC a` para o
alinhamento) e nunca de maiúsculas ou espaços a fingir de destaque — o dono
imprimiu a primeira versão, toda no mesmo corpo de letra, e disse que "não
está parecendo um papel para a cozinha fazer os pedidos".

A ordem, de cima para baixo e do maior para o menor:

1. o **NOME do cliente**, o maior elemento do talão — é o que se grita e o
   que se escreve no copo;
2. a **quantidade e o produto**, em corpo alto — o que se vai fazer;
3. as **respostas de serviço** (levar / comer aqui), a negrito, porque mudam
   o que se faz ao copo;
4. os **toppings com as doses** (`2x Nutella`), agrupados sob o grupo a que
   pertencem — "2x Nutella" lê-se de relance e "Nutella, Nutella" não;
5. e o **cabeçalho** por cima de tudo: o que é, a hora e um número curto para
   se falar dele em voz alta.

Um traço a toda a largura separa um artigo do seguinte: colados, a cozinha
troca copos.

## A regra que não se negoceia: NADA DO QUE FOI PERGUNTADO DESAPARECE

A ficha é o REGISTO do que foi pedido ao balcão. Tudo o que o sistema
perguntou à operadora e ela respondeu tem de aparecer, e com o título do
grupo que a explica — "Comer aqui" sozinho adivinha-se, "Consumir em loja:
Comer aqui" lê-se.

Dois buracos silenciosos que esta ficha teve, e que este ficheiro existe para
não repetir:

- só a PRIMEIRA resposta de texto saía. Um copo com dois grupos de texto
  ("Nome" e "Observações") perdia o segundo, e o papel saía bonito, sem a
  observação;
- as respostas saíam sem a pergunta que as originou, e um grupo de serviço
  que o gestor tenha configurado para SAIR NA FATURA não passa por
  `_e_indicacao_de_servico` — descia aos toppings, "Sem colher" misturado com
  a Nutella e sem nada a dizer de onde vinha. Agora desce na mesma, mas sob o
  título "Talheres:", e lê-se;
- e a DOSE perdia-se num grupo de toppings GRÁTIS com o interruptor
  `sai_na_fatura` desligado: essas opções sobem às indicações de serviço (é
  tudo o que `_e_indicacao_de_servico` sabe perguntar) e eram deduplicadas —
  duas "Granola" saíam uma vez, e a cozinha punha uma colher onde o cliente
  pediu duas. Nenhuma das duas metades da ficha deduplica seja o que for.

**E a QUANTIDADE também é dado, não enfeite.** Uma parte de uma conta
repartida traz `0.3333`, e o papel imprimia-a com `"%d"` — «0 Açaí Regular»,
que é a cozinha a não fazer copo nenhum (ver `_quantidade`).

**O título do grupo aparece em todo o lado menos no nome do copo.** Aí é
ruído: "Nome:" gastava 5 das 21 colunas do corpo duplo para dizer o que o
tamanho da letra já diz.

## Acentos

Saem tal e qual, com acento. A codificação é da impressora e não daqui
(`escpos._TABELA_DE_CARACTERES`, PC858, a que a Epson documenta para o
mercado europeu e a que tem os acentos do português) — e `escpos.pagina_de_teste`
é o botão que responde num clique se aquela impressora concorda. Os textos
que aqui se escrevem à mão não têm acentos nenhuns por acaso: "PEDIDO
COZINHA" não precisa. O que traz acentos é o que vem dos dados — o nome do
produto, o nome do cliente, o título do grupo — e esses não se podem
descaracterizar, porque são o que a cozinha lê.
"""
import textwrap
from datetime import datetime, timezone
from math import isfinite
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from .escpos import (
    ALTO, A_ESQUERDA, CENTRADO, CORPO_NORMAL, DUPLO, NEGRITO, SEM_NEGRITO,
)
from .reparticao import CASAS_DA_QUANTIDADE

# 80 mm de papel. Em corpo normal cabem 42 colunas; em corpo DUPLO (dobro em
# largura) cabe metade, 21. Uma linha que dê a volta numa ficha de cozinha faz
# ler o topping errado — a linha de baixo aparece encostada à esquerda, por
# baixo do artigo seguinte.
_LARGURA = 42
_LARGURA_DUPLA = 21

# O fuso em que a hora se lê, e não o fuso em que ela foi gravada: as vendas
# guardam-se em UTC (`venda._agora`) e no Verão isso são menos uma hora do que
# o relógio da parede da loja. É o mesmo `Europe/Lisbon` que o resto do
# sistema usa para tudo o que uma pessoa lê (`server.LISBON_TZ`).
_LISBOA = ZoneInfo("Europe/Lisbon")

# --- Os comandos ESC/POS que fazem a hierarquia -------------------------------
#
# `DUPLO`, `ALTO`, `NEGRITO`, `CENTRADO` e os pares que os desligam vêm de
# `escpos.py`, onde estão definidos UMA vez só. É de propósito: é a
# `escpos.pagina_de_teste` que os experimenta à frente da impressora, e uma
# segunda cópia aqui fazia esse botão diagnosticar bytes diferentes dos que
# os talões mandam — a pior resposta que ele podia dar.
#
# Vão dentro do texto, como caracteres de controlo, e `escpos.documento`
# entrega-os à impressora sem lhes tocar (`cp858` deixa os bytes abaixo de
# 0x80 exactamente como estão). O `escpos.documento` começa por `ESC @`, que
# apaga tudo isto — mas cada comando aberto aqui é FECHADO aqui, porque uma
# linha que ficasse com o corpo duplo ligado pintava o resto do talão.


def _partir(texto: str, colunas: int = _LARGURA, recuo: str = "") -> List[str]:
    """O texto dobrado às colunas do papel, nas palavras.

    **Dobrado aqui e nunca pela impressora.** Uma impressora que recebe uma
    linha maior do que o papel corta-a onde calhar — a meio de uma palavra, a
    meio de um nome — e o resto aparece encostado à esquerda por baixo, onde
    parece pertencer ao artigo seguinte.

    `textwrap` da biblioteca padrão, e não um laço escrito à mão: dobrar texto
    nas palavras tem casos de borda (uma palavra maior do que a linha, espaços
    a mais) que já estão resolvidos há vinte anos."""
    return textwrap.wrap(texto, colunas, subsequent_indent=recuo) or [""]


def _bloco(
    texto: str, corpo: str = "", colunas: int = _LARGURA,
    negrito: bool = False, recuo: str = "",
) -> List[str]:
    """As linhas de `texto`, dobradas às colunas do corpo de letra pedido e
    já com os comandos que o ligam e o desligam.

    Os comandos abrem na PRIMEIRA linha e fecham na ÚLTIMA, e não uma vez por
    linha: o corpo e o negrito atravessam a mudança de linha na impressora, e
    repeti-los era gastar bytes para dizer o mesmo. Fechar é que não é
    opcional — ver o comentário das constantes.

    **`recuo` não é enfeite, e quem chama tem de o passar.** Uma continuação
    encostada à coluna 0 é exactamente o erro que este ficheiro existe para
    evitar (ver `_partir`): medido numa ficha de dois copos, «Toppings
    gratis: 2x Granola, Leite» dobrava e o «condensado» aparecia por cima de
    «Toppings:», onde parece um artigo novo."""
    linhas = _partir(texto, colunas, recuo)
    if corpo:
        linhas[0] = corpo + linhas[0]
        linhas[-1] = linhas[-1] + CORPO_NORMAL
    if negrito:
        linhas[0] = NEGRITO + linhas[0]
        linhas[-1] = linhas[-1] + SEM_NEGRITO
    return linhas


def _quantidade(bruto) -> str:
    """A quantidade como a cozinha a lê: `2`, `0,3333`, ou `?`.

    O papel imprimia isto com `"%d"`, e o `"%d"` mentia de duas maneiras
    diferentes — as duas medidas nesta loja:

    - uma quantidade FRACCIONÁRIA saía a ZERO. As partes de uma conta
      repartida derivam a quantidade do valor em cêntimos
      (`venda._partes_de_uma_linha` → `reparticao.quantidade_para`), e um
      terço de um açaí é `0.3333`: a cozinha lia «0 Açaí Regular» e não fazia
      copo nenhum;
    - uma quantidade a `None` — que `venda._linha_vendus` aceita e deixa
      gravada — levantava `TypeError`, e o que se perdia não era a linha, era
      a FICHA INTEIRA: quem carregou no botão via um erro no ecrã e a cozinha
      ficava sem papel, com o resto do pedido lá dentro.

    As casas decimais são as mesmas com que a quantidade foi GRAVADA
    (`reparticao.CASAS_DA_QUANTIDADE`) e os zeros à direita caem, para o caso
    normal — o esmagador — continuar a ser um número inteiro e limpo: «2», e
    nunca «2,00000».

    **O que não se sabe sai como `?` e nunca como `1`.** É a mesma regra do
    `_euros` do Z aqui em baixo: escrever um número onde não se sabe é a
    mentira mais fácil de imprimir, e esta mandava fazer um copo a menos.

    **`nan` e `inf` são desse lado, e eram o buraco que faltava tapar.** O
    `try` só apanhava o `float(bruto)`, e a linha seguinte (`q == int(q)`)
    levanta `ValueError` com `nan` e `OverflowError` com `inf` — o mesmo
    estrago do `None` a meio fechar: quem carregou no botão via um erro no
    ecrã e a cozinha ficava sem papel, com o resto do pedido lá dentro, e
    aquela conta nunca mais mandava ficha nenhuma. O diálogo do POS manda
    sempre um inteiro ≥ 1, mas a API aceita o literal `NaN` do JSON — a
    porta fecha-se nos dois sítios (ver `venda._recusa_quantidade_impossivel`
    para o outro)."""
    try:
        q = float(bruto)
    except (TypeError, ValueError):
        return "?"
    if not isfinite(q):
        return "?"
    if q == int(q):
        return "%d" % int(q)
    return ("%.*f" % (CASAS_DA_QUANTIDADE, q)).rstrip("0").rstrip(".").replace(".", ",")


def _contar(opcoes: List[Dict]) -> Dict[str, int]:
    """Quantas vezes cada opção foi escolhida, pela ordem da primeira escolha
    (um `dict` mantém a ordem de inserção desde o Python 3.7).

    **Contadas UMA vez para as duas metades da ficha.** As doses dos toppings
    e as respostas de serviço saem em formatos diferentes mas da mesma
    contagem — e foi terem sido duas contagens que deixou uma delas a
    deduplicar com `dict.fromkeys` e a deitar fora a dose."""
    contagem: Dict[str, int] = {}
    for o in opcoes or []:
        nome = o.get("nome")
        if nome:
            contagem[nome] = contagem.get(nome, 0) + 1
    return contagem


def _doses(opcoes: List[Dict]) -> List[str]:
    """As opções agregadas, pela ordem da primeira escolha. Mesma regra do
    título da fatura (`precos._descricao_das_opcoes`), outro formato: aqui a
    dose vem À FRENTE, que é como uma ficha de cozinha se lê."""
    return ["%dx %s" % (n, nome) for nome, n in _contar(opcoes).items()]


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
    cobrava as duas ("Extra caramelo 2×").

    **O que esta pergunta NÃO decide é se a resposta aparece, nem a dose com
    que aparece.** Ela decide só o DESTAQUE: as indicações de serviço saem a
    negrito, logo por baixo do artigo, porque mudam o que se faz ao copo. O
    que cá cai continua a ser CONTADO (`_contar`) — um grupo de toppings
    grátis com o interruptor desligado responde "sim" aqui, e a cozinha tem de
    ver as duas doses de "Granola" na mesma. Uma pergunta de serviço que o
    gestor tenha configurado para sair na fatura responde "não" aqui e desce
    aos toppings — mas desce com o título do grupo dela por cima, e por isso
    continua a ler-se."""
    return opcao.get("sai_na_fatura") is False and float(opcao.get("preco", 0) or 0) == 0


def _respostas_dadas(linha: Dict) -> List[Dict]:
    """TODAS as respostas de texto da linha que trazem alguma coisa escrita,
    pela ordem em que foram dadas — e não só a primeira.

    A primeira era o que este ficheiro devolvia, e a razão escrita era uma
    convenção ("quem põe um grupo de texto num açaí está a pedir o nome do
    cliente"). A convenção continua a valer para a PRIMEIRA — é a que sai em
    corpo duplo no copo — mas não pode continuar a ser a desculpa para deitar
    fora a segunda: um copo com um grupo "Nome" e um grupo "Observações"
    perdia a observação, em silêncio, e a cozinha fazia o açaí com a granola
    que o cliente pediu para tirar."""
    return [
        dict(r, texto=(r.get("texto") or "").strip())
        for r in linha.get("respostas_texto") or []
        if (r.get("texto") or "").strip()
    ]


def _nome_no_copo(linha: Dict) -> str:
    """A PRIMEIRA resposta de texto da linha — o nome que se escreve no copo.

    Continua a ser a primeira, e continua a ser convenção e não configuração:
    um ajuste por grupo para dizer qual das respostas é o nome seria uma
    definição a mais para o mesmo resultado. As OUTRAS respostas já não se
    perdem — saem mais abaixo, com o título do grupo delas
    (`_respostas_dadas`)."""
    respostas = _respostas_dadas(linha)
    return respostas[0]["texto"] if respostas else ""


def _grupos(opcoes) -> List[Tuple[Optional[str], List[Dict]]]:
    """As opções arrumadas pelo grupo a que pertencem, pela ordem em que cada
    grupo apareceu — `[(título, opções), ...]`.

    O título é o `nome_grupo` que a opção traz carimbado
    (`venda._carimbar_sai_na_fatura`), tirado da primeira opção do grupo. Uma
    linha gravada ANTES de esse carimbo existir não o tem: o título vem a
    `None` e as respostas saem sem ele, exactamente como saíam. Nada rebenta,
    e nada se perde."""
    ordem: List = []
    por_grupo: Dict = {}
    for o in opcoes:
        chave = o.get("grupo_id")
        if chave not in por_grupo:
            ordem.append(chave)
            por_grupo[chave] = ((o.get("nome_grupo") or "").strip() or None, [])
        por_grupo[chave][1].append(o)
    return [por_grupo[c] for c in ordem]


def _hora_de(bruto) -> str:
    """A hora de Lisboa, `HH:MM` — ou nada, se não se souber.

    Nada e nunca uma hora inventada: uma ficha sem hora lê-se na mesma, uma
    ficha com a hora errada manda a cozinha discutir com o balcão sobre qual
    dos pedidos é que é o antigo."""
    if isinstance(bruto, datetime):
        quando = bruto
    elif bruto:
        try:
            quando = datetime.fromisoformat(str(bruto).replace("Z", "+00:00"))
        except ValueError:
            return ""
    else:
        return ""
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=timezone.utc)
    return quando.astimezone(_LISBOA).strftime("%H:%M")


def _cabecalho(venda: Dict) -> List[str]:
    """O que é, quando foi, e como se lhe chama em voz alta.

    O número curto são os 4 últimos caracteres do `id` da venda. Não é bonito
    e não é único no universo — é único no turno, que é o que basta para
    alguém gritar "o F2C está pronto" por cima do barulho da loja. O `id`
    inteiro (um uuid) não se lê em voz alta nem cabe no papel."""
    linhas = _bloco("PEDIDO COZINHA", ALTO, negrito=True)
    marca = "#%s" % (str(venda.get("id") or "").upper()[-4:] or "?")
    linhas.append(("%s  %s" % (marca, _hora_de(venda.get("criada_em")))).strip())
    linhas[0] = CENTRADO + linhas[0]
    linhas[-1] = linhas[-1] + A_ESQUERDA
    return linhas + ["=" * _LARGURA]


def _ficha_do_artigo(linha: Dict) -> List[str]:
    """Um copo. Pela ordem por que se lê, do maior para o menor."""
    respostas = _respostas_dadas(linha)
    saida: List[str] = []

    # 1. O NOME, o maior elemento do talão, em corpo duplo e a negrito. Em
    #    maiúsculas porque é assim que ele vai para o copo, e sem o título do
    #    grupo à frente: "Nome:" gastava 5 das 21 colunas para dizer o que o
    #    tamanho da letra já diz.
    if respostas:
        saida += _bloco(respostas[0]["texto"].upper(), DUPLO, _LARGURA_DUPLA,
                        negrito=True)

    # 2. A quantidade e o produto, em corpo ALTO — a seguir em tamanho, e sem
    #    gastar colunas nenhumas (o dobro é só na altura).
    saida += _bloco(
        "%s %s" % (_quantidade(linha.get("quantidade", 1)),
                   linha.get("produto_nome") or "?"), ALTO)

    opcoes = linha.get("opcoes") or []

    # 3. As indicações de serviço, a negrito e logo por baixo do artigo,
    #    porque mudam o que se faz ao copo. Uma linha por GRUPO respondido,
    #    com o título à frente: "Comer aqui" sozinho adivinha-se, "Consumir em
    #    loja: Comer aqui" lê-se.
    #
    #    **E com a DOSE, quando ela for mais do que uma.** Aqui caem também os
    #    grupos de TOPPINGS GRÁTIS que o gestor configurou com o interruptor
    #    `sai_na_fatura` desligado (preço zero + interruptor desligado é tudo o
    #    que `_e_indicacao_de_servico` sabe perguntar). Estavam a ser
    #    deduplicados com `dict.fromkeys`: duas doses de «Granola» saíam uma
    #    vez, e a cozinha punha uma colher onde o cliente pediu duas. Uma
    #    resposta dada UMA vez — que é o caso de todas as perguntas de serviço
    #    a sério — sai sem dose nenhuma: «1x Levar» era ruído numa linha que
    #    existe para se ler de relance.
    for titulo, opcoes_do_grupo in _grupos(
            o for o in opcoes if _e_indicacao_de_servico(o) and o.get("nome")):
        respondido = ", ".join(
            nome if n == 1 else "%dx %s" % (n, nome)
            for nome, n in _contar(opcoes_do_grupo).items())
        saida += _bloco("%s: %s" % (titulo, respondido) if titulo else respondido,
                        negrito=True, recuo="   ")

    # 4. Tudo o resto que se escolheu, grupo a grupo, com as doses à frente.
    #    O título por cima e as doses recuadas: é o que faz um grupo de
    #    serviço que caiu aqui (porque o gestor o pôs a sair na fatura) ser
    #    lido como o que é, em vez de aparecer misturado com a Nutella.
    for titulo, opcoes_do_grupo in _grupos(
            o for o in opcoes if not _e_indicacao_de_servico(o)):
        doses = _doses(opcoes_do_grupo)
        if not doses:
            continue
        recuo = ""
        if titulo:
            saida += _bloco("%s:" % titulo)
            recuo = "  "
        for dose in doses:
            saida += _bloco(recuo + dose, recuo=recuo + "   ")

    # 5. As outras respostas de texto — as que se perdiam. A negrito e no fim,
    #    junto dos toppings, porque é quase sempre sobre eles que falam ("sem
    #    granola"), e com o título do grupo porque uma frase solta no fundo do
    #    papel não se sabe a que pergunta responde.
    for resposta in respostas[1:]:
        titulo = (resposta.get("nome_grupo") or "").strip()
        texto = resposta["texto"]
        saida += _bloco("%s: %s" % (titulo, texto) if titulo else texto,
                        negrito=True, recuo="   ")

    return saida


def pedido_da_cozinha(venda: Dict) -> str:
    """A ficha de UMA conta, com os copos bem separados.

    Uma ficha por conta e não uma por copo: é o que o código já fazia, é o
    menor salto, e é o que permite à cozinha ver de uma vez o que sai junto
    para a mesma pessoa. O traço a toda a largura entre artigos é o que
    impede o erro que a versão anterior fazia — dois copos colados, e a
    cozinha a pôr a Nutella do segundo no primeiro."""
    partes = _cabecalho(venda)
    for i, linha in enumerate(venda.get("linhas") or []):
        if i:
            partes.append("-" * _LARGURA)
        partes.extend(_ficha_do_artigo(linha))
    return "\n".join(partes) + "\n"


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
    a mais) que já estão resolvidos há vinte anos — é o mesmo `_partir` da
    ficha da cozinha, uma dobra só para as duas metades do ficheiro."""
    return "\n".join(_partir(texto))


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
