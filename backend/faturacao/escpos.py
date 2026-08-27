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

# `ESC t n` — a tabela de caracteres. **n=2 é a PC850**, e a escolha tem uma
# história curta, escrita em papel.
#
# Até 27/08/2026 estava aqui o 19, que é o que a Epson documenta para a PC858.
# Numa **TP8002 da iggual** — a impressora que a maior parte destas lojas tem —
# a ficha da cozinha saiu com «AΘaκ» onde dizia «Açaí», e «Pλ» onde dizia
# «Pó». Não é aleatório e não é ruído: `"Açaí Pó".encode("cp858")` dá os bytes
# `41 87 61 A1 20 50 A2`, e esses bytes lidos em **cp737** (o grego do MS-DOS)
# dão exactamente `AΘaκ Pλ`. Nesta impressora, o n=19 selecciona GREGO — ou
# seja, a numeração dela NÃO é a da Epson.
#
# **Porquê o 2 e não o 14**, que é onde a PC858 fica nas tabelas destes clones:
# o 2 é o único valor que significa PC850 em TODAS as tabelas conhecidas — a da
# Epson, a da HPRT, a da Bixolon e as duas famílias de clone chinês. O 14, numa
# Epson genuína, é PC737: escolhê-lo corrigia a cozinha e mudava exactamente a
# mesma avaria para a impressora do BALCÃO, que é onde sai a Fatura Simplificada
# do cliente. O 2 serve as duas impressoras ao mesmo tempo, e numa loja onde os
# acentos já saíam bem continua a sair bem.
#
# O que se perde da PC858 para a PC850 é o símbolo do euro. Não custa nada:
# `talao._euros` escreve só o número com vírgula, e o único `€` que este sistema
# imprimia estava na linha de acentos da página de teste — que agora o imprime
# dentro do varrimento, nas tabelas que o têm.
#
# Se uma unidade discordar à mesma, quem responde é a `pagina_de_teste`: ela
# imprime a mesma amostra sob cada um dos `_CANDIDATOS`, com o número ao lado,
# e a linha que sair legível diz o valor a pôr aqui. Nada mais do sistema
# precisa de saber, e o `.exe` das lojas não muda nem uma vírgula.
_TABELA_DE_CARACTERES = b"\x1bt\x02"  # ESC t 2
_CODIFICACAO = "cp850"

# Os valores que a `pagina_de_teste` varre, pela ordem em que saem no papel. O
# primeiro é o que está em uso — se essa linha sair certa, acabou, não é preciso
# ler o resto. O último é o 19, que ficou provado errado na TP8002 e está aqui
# de propósito, como controlo: numa Epson genuína ele sai CERTO, e é assim que
# uma folha só distingue as duas famílias de impressora.
_CANDIDATOS = (
    (2, "cp850"),    # PC850 — o defeito, igual em todas as tabelas conhecidas
    (3, "cp860"),    # PC860 — o português do MS-DOS, também estável em todas
    (14, "cp858"),   # PC858 nos clones (mas PC737 grego numa Epson)
    (11, "cp1252"),  # WPC1252 nos clones
    (16, "cp1252"),  # WPC1252 na numeração da Epson
    (19, "cp858"),   # o que aqui estava: PC858 na Epson, GREGO na TP8002
)
_AMOSTRA_DE_ACENTOS = "Açaí ção 3º 1ª €"

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


def documento(conteudo) -> bytes:
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

    **Aceita `bytes` além de `str`**, e é por uma razão só: a página de teste
    precisa de escrever linhas em codificações DIFERENTES umas das outras (é
    isso o varrimento das tabelas), o que nenhum `str` consegue exprimir. Sem
    isto, a página de teste teria de repetir aqui a moldura — o `ESC @`, a
    tabela, o avanço e o corte — e o comando de corte passava a viver em dois
    sítios. Um deles ficaria para trás no dia em que a TP8002 não cortasse.
    """
    corpo = conteudo if isinstance(conteudo, bytes) else _texto(conteudo)
    return (
        _INICIAR
        + _TABELA_DE_CARACTERES
        + corpo
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


def _varrimento() -> bytes:
    """A mesma amostra de acentos impressa sob CADA tabela candidata.

    É a resposta à pergunta que só o papel sabe responder: qual é o número da
    tabela desta impressora. Antes, a página imprimia os acentos numa tabela
    só e quem estivesse à frente do papel via que estava errado — mas não o que
    pôr no lugar, e isso custava uma ida à loja e um segundo deploy às cegas.

    Duas decisões que fazem a folha valer:

    - **o rótulo de cada linha é ASCII puro** (`n=2  cp850`), e o ASCII é igual
      em todas estas tabelas. A linha que sair em grego sai com o rótulo
      legível à mesma — senão a folha era ilegível exactamente onde interessa;
    - **repõe a tabela por defeito no fim**. Sem isto a impressora ficava na
      última tabela varrida — o grego — e o trabalho SEGUINTE herdava-a. Esse
      trabalho pode ser a Fatura Simplificada certificada de um cliente.
    """
    saiu = b""
    for n, codec in _CANDIDATOS:
        rotulo = ("n=%-3d%-7s" % (n, codec)).encode("ascii")
        saiu += (
            b"\x1bt" + bytes([n])
            + rotulo
            + _AMOSTRA_DE_ACENTOS.encode(codec, errors="replace")
            + b"\n"
        )
    return saiu + _TABELA_DE_CARACTERES


def pagina_de_teste(
    impressora: str, loja: Optional[str] = None, servidor: Optional[str] = None
) -> bytes:
    """A página que o dono manda sair para saber se está tudo bem.

    **Este é o único teste que existe para a metade Windows deste sistema.**
    Num Mac não há forma de provar que os bytes entram na impressora; esta
    página é a prova, e por isso o que ela imprime foi escolhido para
    RESPONDER, não para enfeitar:

    - **a tabela de letras** — a mesma amostra de acentos impressa sob CADA
      tabela candidata, com o número de cada uma ao lado (ver `_varrimento`).
      A página já não pergunta «está bem?»: dá a resposta escrita. A linha que
      sair legível é o valor a pôr em `_TABELA_DE_CARACTERES`, e se saírem
      TODAS estragadas então a impressora está a ignorar o comando e o que se
      muda é a configuração dela, não este ficheiro;
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
        "TABELA DE LETRAS - qual linha sai certa?",
        "Deve ler-se: Acai cao 3o 1a euro",
        "",
    ]
    # A cauda começa DEPOIS do varrimento, que é bytes e não texto.
    cauda = [
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
    return documento(
        _texto("\n".join(linhas) + "\n")
        + _varrimento()
        + _texto("\n".join(cauda) + "\n")
    )
