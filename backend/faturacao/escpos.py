"""Os bytes ESC/POS que ESTE sistema constrói — e só esses.

**O talão do cliente NÃO passa por aqui.** Esse vem certificado do Vendus, já
em ESC/POS (`vendus/emissao._talao_de`), e vai para a impressora tal e qual:
não se lhe acrescenta um byte à frente nem atrás. Um talão certificado é um
documento fiscal em papel — quem lhe mexe assume a responsabilidade do que
sai, e este módulo não a quer.

O que se constrói aqui são as TRÊS coisas que o Vendus não dá:
- o **pedido da cozinha** (o texto de `talao.pedido_da_cozinha`);
- o **relatório Z** do fecho (o texto de `talao.relatorio_z`);
- a **abertura da gaveta**, que não é papel nenhum — é um impulso eléctrico
  que a impressora manda pelo cabo RJ11 da gaveta.

E a **página de teste**, que é a única forma de o dono descobrir num clique
se os bytes estão a entrar em cru na impressora ou se o driver do Windows os
está a "desenhar" (ver `pagina_de_teste`).

## Porque é que isto é um módulo à parte, e puro

Nada aqui toca em rede, base de dados ou Windows: entra texto, saem bytes.
É o que permite prender cada byte a um teste NESTE Mac — e é preciso, porque
a parte que fala com a impressora (`agente_impressao/windows.py`) não se pode
provar sem uma impressora à frente.

## O que NÃO se consegue provar daqui, e é dito com todas as letras

Estes comandos são os que os manuais da Epson descrevem e os que a esmagadora
maioria das impressoras ESC/POS implementa. Que a **TM-m30** e a **TP8002 das
lojas** os obedecem é uma afirmação sobre hardware, e hardware não se prova
com um teste: prova-se carregando no botão «Imprimir página de teste» à frente
da impressora. Os dois candidatos a falhar estão isolados de propósito, cada
um numa constante só, para se poderem trocar sem mexer em mais nada:
`_CORTAR` e `_TABELA_DE_CARACTERES`.
"""
from typing import Optional

# `ESC @` — reinicia a impressora: apaga o negrito, o tamanho duplo e o
# alinhamento que o trabalho ANTERIOR possa ter deixado ligados. Sem isto, um
# talão que acabasse a meio de um comando pintava o pedido seguinte todo em
# tamanho duplo, e ninguém percebia porquê.
_INICIAR = b"\x1b@"

# `ESC t n` — a tabela de caracteres. 19 é a PC858, que é a PC850 com o
# símbolo do euro; é a que a Epson documenta para o mercado europeu e a que
# tem os acentos do português (á, ã, ç, é, ó).
#
# **É AQUI que a TP8002 pode discordar**, e é por isso que está numa constante
# só. Se a página de teste sair com "Acai" em vez de "Açaí" — ou com símbolos
# a mais no meio das palavras — a tabela desta impressora é outra, e o que se
# muda é este número (16 = WPC1252 é o outro candidato normal). Nada mais do
# sistema precisa de saber.
_TABELA_DE_CARACTERES = b"\x1bt\x13"  # ESC t 19
_CODIFICACAO = "cp858"

# `GS V 66 n` — avança `n` linhas e faz corte PARCIAL (deixa um pedacinho de
# papel agarrado, que é o que impede o talão de cair ao chão).
#
# O avanço vai a ZERO aqui e as linhas em branco são escritas à mão logo
# antes: numa impressora que não implemente o avanço deste comando, o texto
# ficava colado à lâmina e cortado a meio da última linha. Escritas como `\n`
# normais, o papel avança sempre — mesmo que o corte não aconteça de todo.
#
# **É o segundo candidato a falhar na TP8002.** Se o papel não cortar, é este
# byte que se muda (`\x1dV\x00` é o corte total, o comando mais antigo e o
# mais implementado de todos). Se cortar mas comer a última linha, aumenta-se
# `_LINHAS_ANTES_DO_CORTE`.
_CORTAR = b"\x1dV\x42\x00"
_LINHAS_ANTES_DO_CORTE = 5

# `ESC p m t1 t2` — o impulso que abre a gaveta. `m=0` é o pino 2 do conector
# RJ11 (o que praticamente todas as gavetas usam; `m=1` é o pino 5, e é o
# outro sítio onde se procura quando a gaveta não abre). `t1` e `t2` são o
# tempo com corrente e sem corrente, em unidades de 2 ms: 25 → 50 ms de
# impulso, 250 → 500 ms de descanso. São os valores dos exemplos da Epson.
#
# A gaveta é uma bobina: um impulso demasiado longo aquece-a. Estes números
# não se aumentam "para ver se abre" — se não abrir com 50 ms, o problema é o
# pino (`m`) ou o cabo, nunca a duração.
_GAVETA = b"\x1bp\x00\x19\xfa"


def _texto(conteudo: str) -> bytes:
    """O texto codificado para a impressora.

    `errors="replace"` e nunca uma excepção: um caractere que a PC858 não
    tenha (um emoji no nome que o cliente ditou, um "ł" de um nome polaco)
    sai como `?` e o resto do pedido sai inteiro. Rebentar aqui era deitar
    fora o pedido todo da cozinha por causa de uma letra — e o pedido é
    exactamente o que a cozinha precisa de ler para fazer o copo certo.

    As mudanças de linha vão como `\\n` puro: o ESC/POS trata `LF` como
    "imprime a linha e avança", e um `\\r\\n` faz algumas impressoras
    avançarem duas.
    """
    return conteudo.replace("\r\n", "\n").encode(_CODIFICACAO, errors="replace")


def documento(conteudo: str) -> bytes:
    """Um talão de texto simples: reiniciar, escolher a tabela, escrever,
    avançar, cortar.

    Sem negrito, sem tamanho duplo, sem centrar. Não é modéstia: cada
    comando destes é mais uma coisa que uma das duas impressoras pode não
    obedecer, e um pedido de cozinha ilegível é pior do que um pedido feio.
    Quando o dono quiser o nome do cliente maior, isso acrescenta-se AQUI e a
    página de teste diz num clique se aquela impressora obedece.
    """
    return (
        _INICIAR
        + _TABELA_DE_CARACTERES
        + _texto(conteudo)
        + b"\n" * _LINHAS_ANTES_DO_CORTE
        + _CORTAR
    )


def abrir_gaveta() -> bytes:
    """Só o impulso. Não imprime nada — nem uma linha em branco.

    Um `documento("")` para abrir a gaveta gastava 8 cm de papel de cada vez
    que a operadora precisasse de trocos, e ao fim do dia era um rolo. E
    `_INICIAR` vai à frente pela mesma razão de sempre: se o trabalho
    anterior deixou a impressora a meio de um comando, o impulso perdia-se lá
    dentro e a gaveta não abria.
    """
    return _INICIAR + _GAVETA


def pagina_de_teste(
    impressora: str, loja: Optional[str] = None, servidor: Optional[str] = None
) -> bytes:
    """A página que o dono manda sair para saber se está tudo bem.

    **Este é o único teste que existe para a metade Windows deste sistema.**
    Num Mac não há forma de provar que os bytes entram na impressora; esta
    página é a prova, e por isso o que ela imprime foi escolhido para
    RESPONDER, não para enfeitar:

    - **os acentos** («Açaí, ção, º») — se saírem trocados, a tabela de
      caracteres desta impressora não é a PC858 (ver `_TABELA_DE_CARACTERES`);
    - **a linha de 42 colunas** — se der a volta e continuar na linha de
      baixo, o papel é de 58 mm e não de 80 mm, e os talões vão sair todos
      partidos;
    - **o nome da impressora e da loja** — é o que diz se a configuração
      aponta ao sítio certo, e é a diferença entre "não imprimiu" e "imprimiu
      na impressora da cozinha";
    - **o corte** — se a página sair mas o papel não cortar, é `_CORTAR`.

    E o pior desfecho de todos tem resposta própria: se em vez desta página
    sair uma folha cheia de letras e sinais soltos — `ESC @ ESC t` escritos
    como texto — então o Windows não está a mandar os bytes em cru, está a
    "desenhá-los". Isso resolve-se nas definições da impressora (ver
    INSTALAR-IMPRESSAO.md), nunca no código.
    """
    linhas = [
        "PAGINA DE TESTE",
        "Agente de impressao L'Acai",
        "",
        "Impressora: %s" % impressora,
    ]
    if loja:
        linhas.append("Loja: %s" % loja)
    if servidor:
        linhas.append("Servidor: %s" % servidor)
    linhas += [
        "",
        "Acentos: Acai, cao, 3o, 1a, euro",
        "Acentos: Açaí, ção, 3º, 1ª, €",
        "",
        "Largura (42 colunas, 80mm):",
        "123456789012345678901234567890123456789012",
        "..........|.........|.........|.........|",
        "",
        "Se leu isto tudo em UMA linha cada,",
        "a impressora esta' bem configurada.",
        "",
    ]
    return documento("\n".join(linhas) + "\n")
