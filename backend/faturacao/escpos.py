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

# --- Os comandos que fazem a HIERARQUIA de um talão ---------------------------
#
# Definidos aqui e só aqui, e usados por `talao.py` a partir daqui: são o que
# a ficha da cozinha usa para o nome do cliente ser maior do que tudo, e são
# o que a `pagina_de_teste` experimenta. Duas cópias — uma para imprimir e
# outra para diagnosticar — davam a pior das respostas possíveis: a página a
# dizer que a impressora obedece a um byte que os talões não mandam.
#
# São `str` e não `bytes` porque viajam DENTRO do texto, como caracteres de
# controlo (`_texto` codifica-os em cp858, que deixa tudo abaixo de 0x80
# exactamente como está). Cada comando que se liga tem o par que o desliga, e
# desligar não é opcional: um corpo duplo deixado ligado pinta o talão
# seguinte — e o seguinte pode ser a Fatura Simplificada certificada de um
# cliente.
#
# **São o terceiro candidato a falhar numa impressora que não seja a Epson**,
# e é por isso que a página de teste os manda: uma impressora que os ignore
# não dá erro nenhum, imprime o texto e cala-se.
DUPLO = "\x1d!\x11"        # GS ! 17 — dobro em largura E em altura
ALTO = "\x1d!\x01"         # GS ! 1  — dobro só em altura (não gasta colunas)
CORPO_NORMAL = "\x1d!\x00"  # GS ! 0
NEGRITO = "\x1bE\x01"      # ESC E 1
SEM_NEGRITO = "\x1bE\x00"  # ESC E 0
CENTRADO = "\x1ba\x01"     # ESC a 1
A_ESQUERDA = "\x1ba\x00"   # ESC a 0


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
    """Um talão: reiniciar, escolher a tabela, escrever, avançar, cortar.

    **O negrito, o corpo duplo e o alinhamento vão DENTRO do `conteudo`**, e
    não em parâmetros desta função: quem os liga e os desliga é quem escreve
    o texto (`talao.py`), linha a linha, com as constantes daqui de cima. Esta
    função não lhes toca — passa o texto tal e qual, e o `ESC @` do princípio
    garante que nenhum deles chega ligado de um trabalho anterior.

    Cada um destes comandos é mais uma coisa que uma das duas impressoras
    pode não obedecer — e é por isso que a `pagina_de_teste` os manda também:
    ela responde num clique, à frente da impressora, antes de a cozinha
    receber a primeira ficha plana.
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
    - **a HIERARQUIA** — corpo duplo, negrito e centrado, uma linha cada. É
      nestes três comandos que assenta a ficha da cozinha inteira (o nome do
      cliente maior do que tudo, o serviço destacado, o cabeçalho ao meio), e
      uma impressora que os ignore não dá erro: imprime o texto e cala-se.
      Sem estas linhas, a página dizia que estava tudo bem e a primeira ficha
      saía toda plana — que é a reclamação do dono que a hierarquia existe
      para resolver;
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
        # As três linhas da hierarquia da ficha da cozinha. Cada uma DIZ o que
        # devia parecer: quem está à frente do papel compara-a com esta linha
        # de texto normal e responde sozinho, sem ninguém a quem perguntar. O
        # corpo duplo gasta o dobro das colunas — 21, e não 42 —, por isso a
        # frase dele é curta de propósito.
        "Hierarquia (a ficha da cozinha usa-a):",
        DUPLO + "CORPO DUPLO" + CORPO_NORMAL,
        NEGRITO + "Esta linha e' a negrito." + SEM_NEGRITO,
        # O A_ESQUERDA abre a linha SEGUINTE, e nao fecha esta: a maioria
        # das impressoras termicas so' obedece ao `ESC a` quando ele chega
        # antes de qualquer texto da linha. Colado ao fim desta, as que o
        # ignoram deixavam TUDO o que vem a seguir centrado — numa pagina
        # cujo trabalho e' dizer a verdade sobre a impressora. Mesmo defeito
        # que a ficha da cozinha teve, e que so' se viu numa foto do papel.
        CENTRADO + "Esta linha vai ao meio.",
        A_ESQUERDA + "",
        "Se leu isto tudo em UMA linha cada,",
        "a impressora esta' bem configurada.",
        "",
    ]
    return documento("\n".join(linhas) + "\n")
