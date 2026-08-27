"""Os bytes ESC/POS que este sistema constrói.

**O que estes testes provam e o que NÃO provam, dito à cabeça.** Provam que os
bytes que saem daqui são exactamente os comandos que os manuais descrevem — a
inicialização, a tabela de caracteres, o corte, o impulso da gaveta — e que o
texto português sobrevive à codificação. **Não provam que a Epson TM-m30 e a
TP8002 das lojas os obedecem**: isso é uma afirmação sobre hardware, e
hardware não se prova num Mac. Prova-se carregando no botão «Imprimir página
de teste» à frente da impressora.

Por isso os bytes estão escritos aqui em literal, um a um, e não derivados das
constantes do módulo. Uma comparação contra `escpos._CORTAR` ficava verde com
o comando trocado, que é exactamente a mudança que alguém vai fazer no dia em
que a TP8002 não cortar o papel — e o que se quer nesse dia é este ficheiro a
acender, para a mudança ser deliberada e não distraída.
"""
from faturacao import escpos


# --- Os comandos, byte a byte -------------------------------------------------


def test_todo_o_papel_comeca_por_reiniciar_a_impressora():
    """`ESC @`. Sem isto, um talão que acabasse a meio de um comando pintava o
    pedido seguinte todo em tamanho duplo, e ninguém percebia porquê."""
    assert escpos.documento("olá").startswith(b"\x1b@")
    assert escpos.abrir_gaveta().startswith(b"\x1b@")


def test_a_tabela_de_caracteres_e_escolhida_e_nao_assumida():
    """`ESC t 2` — a PC850. **O número está aqui em literal de propósito**: foi
    trocado uma vez, com o papel na mão, e há-de ser trocado outra vez.

    Esteve aqui o 19 (a PC858 da Epson) até uma TP8002 da iggual imprimir
    «AΘaκ» onde dizia «Açaí». Está reproduzido byte a byte no teste a seguir.
    O 2 é o único valor que quer dizer PC850 em todas as tabelas conhecidas —
    o que serve as duas impressoras da loja, e não só a da cozinha."""
    assert escpos.documento("x").startswith(b"\x1b@\x1bt\x02")


def test_a_TP8002_lia_em_GREGO_o_que_o_servidor_mandava():
    """A prova de campo, em código, para ninguém ter de acreditar em mim.

    Os bytes que este módulo mandava até 27/08/2026, lidos na tabela em que a
    TP8002 estava, dão exactamente o que saiu no papel da loja. É isto — e não
    um palpite — que justifica a troca do número acima."""
    assert "Açaí Pó".encode("cp858") == bytes.fromhex("41 87 61 A1 20 50 A2")
    assert "Açaí Pó".encode("cp858").decode("cp737") == "AΘaκ Pλ"


def test_o_defeito_e_um_dos_CANDIDATOS_do_varrimento():
    """O par número/codificação anda sempre junto. Mudar um sem o outro é
    exactamente o defeito que estamos a corrigir — bytes de uma tabela lidos
    noutra — e passaria em silêncio, porque nada rebenta: só sai grego."""
    assert (escpos._TABELA_DE_CARACTERES[-1], escpos._CODIFICACAO) in escpos._CANDIDATOS


def test_o_papel_avanca_ANTES_do_corte_e_com_linhas_a_serio():
    """As linhas em branco são `\\n` normais e não o avanço do próprio comando
    de corte: numa impressora que não implemente esse avanço, o texto ficava
    colado à lâmina e cortado a meio da última linha. Escritas como `\\n`, o
    papel avança sempre — mesmo que o corte não aconteça de todo."""
    saiu = escpos.documento("linha")
    assert saiu.endswith(b"\n\n\n\n\n\x1dV\x42\x00")


def test_a_gaveta_e_um_IMPULSO_e_nao_um_talao():
    """`ESC p 0 25 250` — pino 2, 50 ms com corrente, 500 ms sem. E mais nada:
    um `documento("")` para abrir a gaveta gastava 8 cm de papel de cada vez
    que a operadora precisasse de trocos, e ao fim do dia era um rolo."""
    assert escpos.abrir_gaveta() == b"\x1b@\x1bp\x00\x19\xfa"


def test_a_gaveta_nao_leva_comando_de_corte_nenhum():
    assert b"\x1dV" not in escpos.abrir_gaveta()


# --- O texto ------------------------------------------------------------------


def test_o_portugues_sobrevive_a_codificacao():
    """«Açaí» é o nome do produto que estas cinco lojas vendem. Um talão que o
    escreva mal em todas as linhas não é um pormenor estético — é a ficha que
    a cozinha lê."""
    saiu = escpos.documento("Açaí à moda, 3º")
    assert "Açaí à moda, 3º".encode("cp850") in saiu


def test_um_caractere_impossivel_nao_deita_fora_o_pedido_TODO():
    """Um emoji no nome que o cliente ditou, um «ł» de um nome polaco. Rebentar
    aqui era perder o pedido inteiro da cozinha por causa de uma letra — e o
    pedido é exactamente o que a cozinha precisa para fazer o copo certo."""
    saiu = escpos.documento("Maria 🙂 ł")
    assert b"Maria" in saiu
    assert "Maria".encode("cp850") in saiu


def test_o_fim_de_linha_do_windows_nao_faz_a_impressora_saltar_duas():
    """O ESC/POS trata `LF` como «imprime e avança». Um `\\r\\n` faz algumas
    impressoras avançarem duas linhas, e um pedido de cozinha com o dobro do
    espaçamento gasta o dobro do papel e corta mal."""
    assert b"\r" not in escpos.documento("uma\r\noutra")
    assert b"uma\noutra" in escpos.documento("uma\r\noutra")


# --- A página de teste --------------------------------------------------------
#
# É o único teste que existe para a metade Windows deste sistema, e por isso o
# que ela imprime foi escolhido para RESPONDER a perguntas. Cada uma delas está
# aqui guardada: apagar uma linha da página de teste é apagar a resposta a uma
# pergunta que o dono vai fazer à frente da impressora, sozinho, sem ninguém a
# quem perguntar.


def _pagina():
    return escpos.pagina_de_teste("EPSON TM-m30", loja="Loja do Guarda",
                                  servidor="https://lisbonb.com")


def test_a_pagina_de_teste_diz_QUAL_a_impressora_e_QUAL_a_loja():
    """É a diferença entre «não imprimiu» e «imprimiu na impressora da
    cozinha» — e essa diferença resolve-se num clique ou numa hora ao
    telefone."""
    saiu = _pagina()
    assert b"EPSON TM-m30" in saiu
    assert "Loja do Guarda".encode("cp850") in saiu
    assert b"https://lisbonb.com" in saiu


def test_a_pagina_de_teste_VARRE_as_tabelas_candidatas():
    """**A página já não pergunta se está bem: diz qual é o número certo.**

    A mesma amostra sob cada tabela candidata, e cada linha tem de trazer três
    coisas — o comando que muda mesmo de tabela, o rótulo que NOMEIA o número,
    e o texto codificado na tabela que o rótulo anuncia. Uma linha com o codec
    trocado era uma folha que mente a quem está à frente da impressora, e o
    engano voltava para o código como um número errado."""
    saiu = _pagina()
    for n, codec in escpos._CANDIDATOS:
        linha = (b"\x1bt" + bytes([n])
                 + ("n=%-3d%-7s" % (n, codec)).encode("ascii")
                 + escpos._AMOSTRA_DE_ACENTOS.encode(codec, errors="replace"))
        assert linha in saiu, "falta a linha do n=%d" % n


def test_o_rotulo_de_cada_linha_do_varrimento_e_LEGIVEL_em_qualquer_tabela():
    """O rótulo é ASCII puro, que é igual em todas estas tabelas. A linha que
    sair em grego sai com o número legível à mesma — e é justamente essa a
    linha que quem está ao balcão precisa de saber identificar."""
    for n, codec in escpos._CANDIDATOS:
        assert ("n=%-3d%-7s" % (n, codec)).encode("ascii").isascii()


def test_o_varrimento_REPOE_a_tabela_por_defeito():
    """Sem isto a impressora ficava na última tabela varrida — o grego — e o
    trabalho seguinte herdava-a. Esse trabalho pode ser a Fatura Simplificada
    certificada de um cliente."""
    saiu = _pagina()
    assert escpos._varrimento().endswith(escpos._TABELA_DE_CARACTERES)
    assert saiu[saiu.rindex(b"\x1bt"):].startswith(escpos._TABELA_DE_CARACTERES)


def test_a_pagina_de_teste_mede_a_LARGURA_do_papel():
    """42 caracteres numa linha. Se der a volta e continuar na linha de baixo,
    o papel é de 58 mm e não de 80 mm — e os talões vão sair todos partidos, o
    dia inteiro, sem ninguém perceber porquê."""
    saiu = _pagina()
    regua = b"123456789012345678901234567890123456789012"
    assert len(regua) == 42
    assert regua in saiu


def test_a_pagina_de_teste_EXPERIMENTA_a_hierarquia_da_ficha_da_cozinha():
    """**A pergunta que faltava, e é a que vai a 5 lojas com duas impressoras
    diferentes.**

    A ficha da cozinha inteira assenta em três comandos — `GS !` para o corpo,
    `ESC E` para o negrito, `ESC a` para o alinhamento (ver `talao.py`) — e a
    página de teste não mandava nenhum deles: dizia que os acentos, a largura
    e o corte estavam bem, e a primeira ficha saía na mesma toda plana, que é
    exactamente a reclamação do dono que a hierarquia existe para resolver.

    Uma impressora que ignore estes comandos imprime o texto e cala-se — não
    dá erro nenhum. Por isso as três linhas dizem POR EXTENSO o que deviam
    parecer: quem está à frente do papel compara-as com as de cima e responde
    sozinho, sem ninguém a quem perguntar.

    Os bytes estão aqui em literal, e não vindos das constantes do módulo,
    pela mesma razão do resto do ficheiro: uma comparação contra a constante
    ficava verde com o comando trocado."""
    saiu = _pagina()
    assert b"\x1d!\x11" in saiu   # GS ! 17 — corpo duplo, o nome no copo
    assert b"\x1bE\x01" in saiu   # ESC E 1 — negrito, as respostas de serviço
    assert b"\x1ba\x01" in saiu   # ESC a 1 — centrado, o cabeçalho


def test_a_pagina_de_teste_DESLIGA_tudo_o_que_ligou():
    """Um comando que fique ligado no fim desta página pinta o TALÃO SEGUINTE
    — e o seguinte é a Fatura Simplificada de um cliente, que sai da caixa em
    bytes certificados a que ninguém pode tocar.

    (`escpos.documento` começa sempre por `ESC @`, que apaga tudo; isto é o
    cinto por cima dos suspensórios, e é barato.)"""
    saiu = _pagina()
    for ligar, desligar in ((b"\x1d!\x11", b"\x1d!\x00"),
                            (b"\x1bE\x01", b"\x1bE\x00"),
                            (b"\x1ba\x01", b"\x1ba\x00")):
        assert saiu.rindex(desligar) > saiu.rindex(ligar), ligar


def test_a_pagina_de_teste_tambem_CORTA():
    """Se a página sair mas o papel não cortar, o candidato é um byte só."""
    assert _pagina().endswith(b"\x1dV\x42\x00")


def test_a_pagina_de_teste_sai_sem_loja_nem_servidor_configurados():
    """É o estado em que ela é mais precisa: a primeira vez, antes de
    qualquer coisa estar preenchida."""
    saiu = escpos.pagina_de_teste("Microsoft Print to PDF")
    assert b"Microsoft Print to PDF" in saiu
    assert saiu.startswith(b"\x1b@")


def test_a_pagina_de_teste_VOLTA_a_esquerda_no_inicio_de_uma_linha():
    """A página de teste existe para dizer a verdade sobre a impressora — e
    tinha o mesmo defeito que a ficha da cozinha teve: o `ESC a 0` colado ao
    FIM da linha centrada.

    A maioria das impressoras térmicas só obedece ao `ESC a` quando ele chega
    ANTES de qualquer texto da linha. Nas que o ignoram a meio, tudo o que
    vem depois — incluindo o «Se leu isto tudo em UMA linha cada» — saía
    centrado, e quem estava à frente do papel não tinha como saber se era
    assim de propósito. Uma ferramenta de diagnóstico com o defeito que
    diagnostica é a pior das duas."""
    papel = _pagina().decode("latin-1")
    for i, linha in enumerate(papel.split("\n")):
        if "\x1ba\x00" not in linha:
            continue
        antes = linha.split("\x1ba\x00")[0]
        imprimivel = "".join(
            c for c in antes if c.isprintable() and c not in "\x1b\x1d")
        # Só sobram os argumentos dos comandos (a, E, !, e os seus bytes).
        assert not imprimivel.strip("aE!@"), (
            "O `ESC a 0` da linha %d vem depois de texto — a impressora "
            "ignora-o: %r" % (i, linha))
