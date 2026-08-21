"""Guarda de regressão: uma conta repartida não engole a conta do balcão.

Duas contas do mesmo balcão a existir ao mesmo tempo — as partes de quem
dividiu e a venda de quem está agora à frente — e o ecrã tem UM lugar para a
conta em curso e UM lugar para a repartição. É nessa aritmética que os dois
defeitos deste ficheiro nasceram, e os dois deixavam dinheiro aberto no
servidor sem uma palavra no ecrã:

1. **A seta de voltar do finalizar largava a conta do balcão.** A condição era
   "há partes por cobrar", quando a pergunta é "esta conta é uma delas". Com
   8,99 € divididos por três e a pessoa 1 já cobrada, a conta seguinte do
   balcão (uma Embalagem de 0,15 €) ia ao finalizar, e a seta de cima — cujo
   `aria-label` diz "Voltar à conta" — largava-a (`aplicarVenda(null)`) e
   aterrava em "Cobrar as partes" do cliente ANTERIOR. O painel do balcão
   ficava vazio, a conta continuava `aberta` no servidor, e o toque seguinte
   abria uma TERCEIRA conta por cima dela: órfã e invisível. A mesma linha
   fazia o "Nova Venda" de uma venda já emitida aterrar nas partes de outra
   pessoa.

2. **Uma segunda repartição apagava a primeira.** Só há um `reparticao` no
   ecrã. Separada uma conta de 16,41 € em 8,41 + 8,00, as duas por cobrar,
   bastava começar a conta do cliente seguinte e tocar em "Dividir Conta" só
   para ver a previsão: a mãe e as partes passavam a ser as da conta nova, e
   recuar com as duas setas levava a faixa "Faltam cobrar 2 pessoas de 2"
   com elas. Os 16,41 € continuavam por receber no servidor, sem nada no ecrã
   a dizê-lo.

Como se guarda uma decisão que vive dentro de um componente React. As duas
perguntas passaram a viver em `lib/pos.js` (`ehUmaDasPartes` e
`partesAbertas`) — puras, sem React nada — e é isso que este ficheiro
executa em Node, pela técnica do `test_resumo_do_ecra.py`. O que não se
consegue executar (os `useCallback` do PosVenda importam React e os
`@/components/ui`) guarda-se pelo texto, como no
`test_caminhos_do_pos.py`: prova-se que a decisão é feita POR ESSAS funções e
não outra vez à mão, que é a única forma de a mesma troca não voltar a
escrever-se ali dentro.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

# backend/tests/faturacao/este_ficheiro.py -> raiz do repositório
_RAIZ = Path(__file__).resolve().parents[3]
_LIB_POS = _RAIZ / "frontend" / "src" / "lib" / "pos.js"
_POS_VENDA = _RAIZ / "frontend" / "src" / "pages" / "pos" / "PosVenda.js"
_POS_FINALIZAR = _RAIZ / "frontend" / "src" / "pages" / "pos" / "PosFinalizar.js"

_ASSINATURA_ABERTAS = "export const partesAbertas = (partes) =>"
_ASSINATURA_EH_PARTE = "export const ehUmaDasPartes = (venda, partes) =>"
_ASSINATURA_VOLTAR = "const voltarDoFinalizar = useCallback(() =>"
_ASSINATURA_ABRIR = "const abrirReparticao = useCallback((modo) =>"


def _ler(ficheiro: Path) -> str:
    if not ficheiro.exists():
        pytest.fail(
            "Não encontrei %s. Se o ecrã mudou de sítio, este guarda tem de ir "
            "atrás dele — não se apaga." % ficheiro
        )
    return ficheiro.read_text(encoding="utf-8")


def _corpo_da_funcao(texto: str, assinatura: str, ficheiro: Path) -> str:
    """O código de uma função, do início da assinatura até à chaveta que a
    fecha. Falha alto se a assinatura desapareceu: um guarda que não encontra
    o que devia vigiar e se cala passa a verde para sempre."""
    if assinatura not in texto:
        pytest.fail(
            "Não encontrei `%s` em %s. Se a função foi renomeada ou movida, a "
            "regra que ela cumpre continua a ter de ser guardada."
            % (assinatura, ficheiro.name)
        )
    inicio = texto.index(assinatura)
    i = texto.index("{", inicio)
    profundidade = 0
    for fim in range(i, len(texto)):
        if texto[fim] == "{":
            profundidade += 1
        elif texto[fim] == "}":
            profundidade -= 1
            if profundidade == 0:
                return texto[inicio:fim + 1]
    pytest.fail("A função `%s` em %s não fecha." % (assinatura, ficheiro.name))


def _corpo_da_seta(texto: str, assinatura: str, ficheiro: Path) -> str:
    """O mesmo, para uma arrow function de uma expressão só: até ao `;`."""
    if assinatura not in texto:
        pytest.fail("Não encontrei `%s` em %s." % (assinatura, ficheiro.name))
    inicio = texto.index(assinatura)
    fim = texto.index(";", inicio)
    return texto[inicio:fim + 1]


def _sem_comentarios(codigo: str) -> str:
    """O código sem os comentários. É preciso porque os comentários deste
    ficheiro descrevem o defeito COM AS PALAVRAS DELE ("a condição era só
    'há partes por cobrar'"), e um guarda que procurasse essas palavras no
    texto todo ficava vermelho por causa da explicação em vez do código."""
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", codigo, flags=re.S))


def _so_codigo(codigo: str) -> str:
    """Sem comentários E sem o texto das cadeias de caracteres. A segunda
    metade faz falta porque o nome da vista é literalmente `'reparticao'`
    (`setVista('reparticao')`), e contar a palavra no texto todo confundia o
    NOME do ecrã com uma leitura do estado."""
    sem = _sem_comentarios(codigo)
    for aspas in ("'", '"', "`"):
        sem = re.sub(r"%s(?:\\.|[^%s\\])*%s" % (aspas, aspas, aspas), "''", sem)
    return sem


def _node() -> str:
    caminho = shutil.which("node")
    if caminho:
        return caminho
    # O node deste Mac vive fora do PATH (ver a memória do projecto). Sem ele
    # o teste diz porque não correu, em vez de ficar verde a fingir — e os
    # guardas de texto, esses, correm sempre.
    candidato = Path.home() / ".local" / "node" / "bin" / "node"
    if candidato.exists():
        return str(candidato)
    pytest.skip(
        "Sem `node` para executar o JavaScript do ecrã "
        "(nem no PATH nem em ~/.local/node/bin)."
    )


def _perguntas_do_ecra(casos, tmp_path: Path):
    """Corre em Node as duas perguntas, tal como estão escritas no
    `lib/pos.js` — sem cópia nenhuma delas escrita aqui."""
    lib = _ler(_LIB_POS)
    guiao = tmp_path / "partes.js"
    guiao.write_text(
        "\n".join([
            # `export` fora: isto corre como um guião solto, não como módulo.
            _corpo_da_seta(lib, _ASSINATURA_ABERTAS, _LIB_POS).replace("export ", "", 1),
            _corpo_da_seta(lib, _ASSINATURA_EH_PARTE, _LIB_POS).replace("export ", "", 1),
            "const casos = %s;" % json.dumps(casos),
            "process.stdout.write(JSON.stringify(casos.map(({ venda, partes }) => ({",
            "  abertas: partesAbertas(partes).length,",
            "  ehParte: ehUmaDasPartes(venda, partes),",
            "}))));",
        ]),
        encoding="utf-8",
    )
    resultado = subprocess.run(
        [_node(), str(guiao)], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if resultado.returncode != 0:
        pytest.fail(
            "O JavaScript do ecrã não correu:\n%s"
            % resultado.stderr.decode("utf-8", "replace")
        )
    return json.loads(resultado.stdout.decode("utf-8"))


# A conta do browser: 8,99 € divididos por três, a pessoa 1 já cobrada, e a
# conta seguinte do balcão (a Embalagem de 0,15 €) à frente da operadora.
_PARTES = [
    {"id": "p1", "estado": "emitida", "totais": {"total": 3.00}},
    {"id": "p2", "estado": "aberta", "totais": {"total": 3.00}},
    {"id": "p3", "estado": "aberta", "totais": {"total": 2.99}},
]
_EMBALAGEM = {"id": "897f2ad9", "estado": "aberta", "totais": {"total": 0.15}}


def test_a_conta_do_balcao_nao_e_uma_das_partes(tmp_path):
    """O defeito, escrito com os números que se viram no ecrã. A Embalagem de
    0,15 € não é parte nenhuma — e é por isso que a seta de voltar não a pode
    largar nem levar a operadora às partes do cliente anterior."""
    saida = _perguntas_do_ecra([{"venda": _EMBALAGEM, "partes": _PARTES}], tmp_path)[0]
    assert saida["ehParte"] is False, (
        "A conta do balcão passou por uma das partes. É esta resposta que "
        "decide se a seta de voltar a larga do ecrã."
    )
    assert saida["abertas"] == 2, "Faltam cobrar duas pessoas — a nota do painel diz isso."


def test_a_parte_que_esta_a_ser_cobrada_e_reconhecida(tmp_path):
    """O outro lado da mesma pergunta: a cobrar uma PARTE, o que está atrás
    não é o balcão, são as outras pessoas da mesma conta — e voltar tem de ir
    lá dar."""
    for parte in _PARTES:
        saida = _perguntas_do_ecra([{"venda": parte, "partes": _PARTES}], tmp_path)[0]
        assert saida["ehParte"] is True, (
            "A parte %s não se reconheceu na sua própria lista." % parte["id"]
        )


@pytest.mark.parametrize(
    "venda,partes,esperado",
    [
        # Sem repartição nenhuma viva não há parte nenhuma a que voltar.
        (_EMBALAGEM, None, False),
        (_EMBALAGEM, [], False),
        # Uma conta que ainda não nasceu no servidor não é parte de coisa
        # nenhuma — e comparar `undefined` com `undefined` dava "sim".
        (None, _PARTES, False),
        ({"estado": "aberta"}, [{"estado": "aberta"}], False),
    ],
)
def test_os_casos_vazios_nunca_dizem_que_sim(venda, partes, esperado, tmp_path):
    saida = _perguntas_do_ecra([{"venda": venda, "partes": partes}], tmp_path)[0]
    assert saida["ehParte"] is esperado


def test_so_conta_por_cobrar_o_que_o_servidor_deu_por_aberto(tmp_path):
    """`partesAbertas` é o que decide a nota do painel, o travão da segunda
    repartição e a razão encostada aos botões. Uma parte emitida ou cancelada
    não é dinheiro por receber: contá-la punha a faixa a pedir dinheiro que
    ninguém deve."""
    todas_resolvidas = [
        {"id": "p1", "estado": "emitida"},
        {"id": "p2", "estado": "cancelada"},
    ]
    saida = _perguntas_do_ecra([{"venda": _EMBALAGEM, "partes": todas_resolvidas}], tmp_path)[0]
    assert saida["abertas"] == 0


# --- Os guardas do que não se consegue executar -------------------------------


def test_a_seta_de_voltar_pergunta_se_a_conta_e_uma_das_partes():
    """O `voltarDoFinalizar` decide POR `ehUmaDasPartes` e não outra vez à
    mão. Enquanto a decisão estava escrita ali dentro, ela era `reparticao?.
    partes && !porApurar` — "há partes", não "esta é uma delas" — e foi essa
    troca que largou a conta do balcão."""
    corpo = _so_codigo(
        _corpo_da_funcao(_ler(_POS_VENDA), _ASSINATURA_VOLTAR, _POS_VENDA))
    assert "ehUmaDasPartes(" in corpo, (
        "O `voltarDoFinalizar` deixou de perguntar `ehUmaDasPartes`. A pergunta "
        "é 'esta conta é uma das partes?' e vive em lib/pos.js — escrita outra "
        "vez aqui dentro, volta a ser 'há partes por cobrar?', que larga a "
        "conta do balcão."
    )
    assert corpo.count("reparticao") == 1, (
        "O `voltarDoFinalizar` voltou a olhar para a `reparticao` por sua "
        "conta. A única leitura que ela pode fazer é passá-la a "
        "`ehUmaDasPartes`."
    )


def test_nao_se_abre_uma_reparticao_por_cima_de_outra_por_cobrar():
    """O `abrirReparticao` recusa enquanto houver partes por cobrar. Sem esta
    recusa, `setReparticao(...)` escrevia por cima da repartição anterior e o
    `sairDaReparticao` (que com `partes` a `null` a deita fora) levava as
    partes por cobrar com ele."""
    texto = _ler(_POS_VENDA)
    corpo = _sem_comentarios(_corpo_da_funcao(texto, _ASSINATURA_ABRIR, _POS_VENDA))
    assert "partesAbertas(" in corpo, (
        "O `abrirReparticao` deixou de perguntar quantas partes ficaram por "
        "cobrar. Sem essa pergunta, tocar em 'Dividir Conta' na conta seguinte "
        "— mesmo só para ver a previsão — apaga do ecrã as partes que ainda "
        "têm dinheiro por receber."
    )
    assert "razaoDeNaoRepartir(" in corpo, (
        "A recusa deixou de dizer porquê pela mesma frase que desliga os "
        "botões — quem lá chegar por outro caminho fica sem explicação."
    )
    posicao_recusa = corpo.index("partesAbertas(")
    posicao_escrita = corpo.index("setReparticao(")
    assert posicao_recusa < posicao_escrita, (
        "A recusa do `abrirReparticao` passou para DEPOIS do `setReparticao` — "
        "a repartição anterior já foi escrita por cima quando ela corre."
    )
    assert "return;" in corpo[posicao_recusa:posicao_escrita], (
        "O `abrirReparticao` avisa mas segue em frente: sem o `return`, a "
        "repartição anterior é escrita por cima na mesma."
    )


def test_os_botoes_de_repartir_dizem_porque_estao_desligados():
    """A razão vive encostada ao botão que ela está a tentar carregar, como o
    `motivoBloqueio` do EMITIR: a MESMA frase que desliga os dois botões é a
    que aparece por cima deles. Um botão desligado sem explicação manda-a
    carregar dez vezes; um botão vivo que não faz nada é pior ainda."""
    venda = _ler(_POS_VENDA)
    assert "impedeRepartir={impedeRepartir}" in venda, (
        "O PosVenda deixou de dizer ao finalizar por que é que não se pode "
        "repartir — os botões voltam a convidar ao que o `abrirReparticao` "
        "recusa."
    )
    assert "const impedeRepartir = razaoDeNaoRepartir(" in venda, (
        "A razão que desliga os botões deixou de ser a MESMA que o "
        "`abrirReparticao` diz. Duas frases para o mesmo dinheiro por receber "
        "acabam a dizer coisas diferentes sobre ele."
    )
    finalizar = _sem_comentarios(_ler(_POS_FINALIZAR))
    assert finalizar.count("|| !!impedeRepartir") == 2, (
        "Os dois botões de repartir (Dividir Conta e Separar Conta) têm de "
        "ficar desligados com a mesma razão — encontrei %d."
        % finalizar.count("|| !!impedeRepartir")
    )
    assert "{impedeRepartir}" in finalizar, (
        "O PosFinalizar recebe a razão mas não a mostra em lado nenhum."
    )


# --- E depois de o browser se ter esquecido de tudo ---------------------------
#
# O terceiro defeito da mesma família, e o mais fundo: o `reparticao` vivia SÓ
# na memória do browser. Um F5, a tela de descanso, um "Trocar de operador" ou
# o browser a ir abaixo, e a faixa "Faltam cobrar 2 pessoas de 2 — 14,10 €"
# desaparecia sem uma palavra, com as duas partes bem `aberta` no servidor.
# Medido: `abertas no servidor: v-5, v-6, v-7` → o ecrã recuperava `v-7`.
#
# A verdade passou a vir do servidor (`GET /pos/venda/repartidas`, guardado em
# `test_partes_recuperadas.py`). O que se guarda AQUI é o lado do ecrã: que ele
# faz mesmo a pergunta ao arrancar, e que a resposta é traduzida por UMA função
# (`reparticaoDoServidor`) e não montada à mão — enquanto o arranque montasse o
# objecto por sua conta, bastava o servidor ganhar um campo para o caminho do
# F5 ficar com uma repartição diferente da do toque.

_ASSINATURA_CARREGAR = "const carregarTudo = useCallback(async () =>"


def test_o_arranque_do_ecra_pergunta_ao_servidor_pelas_partes_por_cobrar():
    corpo = _sem_comentarios(
        _corpo_da_funcao(_ler(_POS_VENDA), _ASSINATURA_CARREGAR, _POS_VENDA))
    assert "getContasRepartidas(" in corpo, (
        "O arranque do ecrã deixou de perguntar ao servidor quem ficou por "
        "cobrar. Sem essa pergunta, um F5 volta a apagar do ecrã o dinheiro "
        "por receber — que continua lá, aberto, no servidor."
    )
    assert "reparticaoDoServidor(" in corpo, (
        "A resposta do servidor voltou a ser traduzida à mão no arranque. A "
        "tradução vive em lib/pos.js para o caminho do F5 e o do toque "
        "montarem a MESMA repartição."
    )
    assert ".catch(" in corpo, (
        "A pergunta pelas partes voltou a poder derrubar o arranque: um "
        "`Promise.all` rejeita inteiro à primeira falha, e o balcão ficava sem "
        "catálogo e sem a conta em curso por causa de uma pergunta nova."
    )


# --- As três portas por onde uma conta saía em silêncio -----------------------
#
# A regra do ficheiro é uma só: **uma conta só sai do ecrã pelo
# `porContaDeLado`**, que a grava e deixa uma nota permanente no painel. Havia
# três sítios a não cumpri-la, e os dois primeiros custaram contas medidas no
# browser:
#
#   1. `cobrarParte` fazia `aplicarVenda(parte)` sem olhar para a frente: com
#      um Café Expresso de 1,00 € picado (`v-9`), "Voltar às partes" →
#      "Cobrar" → voltar dava "Não existem produtos associados" no painel
#      enquanto o servidor respondia `v-9: aberta 1 ['Café Expresso']`.
#   2. `terminarReparticao` (o "Nova Venda" das partes) fazia
#      `aplicarVenda(null)` pela mesma razão: duas contas do balcão abertas no
#      servidor e nenhuma no ecrã.
#   3. E o terceiro era não haver mais nenhum — percorridos um a um todos os
#      `aplicarVenda(` do ficheiro. Os que ficaram guardam-se com o teste do
#      fim desta secção, que conta as saídas permitidas.

_ASSINATURA_COBRAR = "const cobrarParte = useCallback((parte) =>"
_ASSINATURA_TERMINAR = "const terminarReparticao = useCallback(() =>"
_ASSINATURA_CEDER = "const cederOLugarDaConta = useCallback(() =>"
_ASSINATURA_POR_DE_LADO = "const porContaDeLado = useCallback((motivo = 'travada') =>"


def test_cobrar_uma_parte_nao_larga_a_conta_que_esta_a_frente():
    texto = _ler(_POS_VENDA)
    corpo = _so_codigo(_corpo_da_funcao(texto, _ASSINATURA_COBRAR, _POS_VENDA))
    assert "cederOLugarDaConta()" in corpo, (
        "O `cobrarParte` voltou a pôr a parte à frente sem olhar para a conta "
        "que lá estava. Essa conta fica `aberta` no servidor e invisível no "
        "ecrã, e o toque seguinte abre outra por cima dela."
    )
    assert corpo.index("cederOLugarDaConta()") < corpo.index("aplicarVenda("), (
        "O lugar é cedido DEPOIS de a parte já estar à frente — quando isso "
        "corre, a conta anterior já foi largada."
    )


def test_o_nova_venda_das_partes_nao_larga_a_conta_que_esta_a_frente():
    corpo = _so_codigo(
        _corpo_da_funcao(_ler(_POS_VENDA), _ASSINATURA_TERMINAR, _POS_VENDA))
    assert "cederOLugarDaConta()" in corpo, (
        "O `terminarReparticao` voltou a largar a conta do balcão. Medido: "
        "duas contas abertas no servidor e nenhuma no ecrã."
    )
    assert "aplicarVenda(" not in corpo, (
        "O `terminarReparticao` voltou a mexer na conta em curso por sua "
        "conta. Quem a tira da frente é o `cederOLugarDaConta`, que sabe "
        "quando é preciso deixar uma nota."
    )


_ASSINATURA_MOTIVO = "export const motivoDeQuemCedeOLugar = (venda) =>"
_ASSINATURA_TRAVADA = "export const contaTravada = (venda) =>"


def _motivos_do_ecra(vendas, tmp_path: Path):
    """Corre em Node o `motivoDeQuemCedeOLugar` tal como está escrito no
    `lib/pos.js` — sem cópia nenhuma dele escrita aqui.

    **Porque é que este teste teve de passar a EXECUTAR o JavaScript.** A
    decisão vivia dentro do `useCallback` do `cederOLugarDaConta`, e um guarda
    de texto só conseguia procurar `porContaDeLado(` no corpo da função —
    nunca com que argumento. Mutação medida nesta ronda: trocar `'balcao'` por
    `'travada'` deixava os 1029 testes verdes. Passou a viver em `lib/pos.js`
    exactamente para isto deixar de ser possível."""
    lib = _ler(_LIB_POS)
    guiao = tmp_path / "motivos.js"
    guiao.write_text(
        "\n".join([
            _corpo_da_seta(lib, _ASSINATURA_TRAVADA, _LIB_POS).replace("export ", "", 1),
            _corpo_da_seta(lib, _ASSINATURA_MOTIVO, _LIB_POS).replace("export ", "", 1),
            "const vendas = %s;" % json.dumps(vendas),
            "process.stdout.write(JSON.stringify("
            "vendas.map((v) => motivoDeQuemCedeOLugar(v))));",
        ]),
        encoding="utf-8",
    )
    resultado = subprocess.run(
        [_node(), str(guiao)], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if resultado.returncode != 0:
        pytest.fail(
            "O JavaScript do ecrã não correu:\n%s"
            % resultado.stderr.decode("utf-8", "replace")
        )
    return json.loads(resultado.stdout.decode("utf-8"))


def test_uma_conta_TRAVADA_que_cede_o_lugar_leva_a_nota_de_travada(tmp_path):
    """O defeito: `cederOLugarDaConta` passava sempre `'balcao'`. A nota que
    ficava no painel dizia "à espera de ser cobrada ou cancelada" sobre uma
    conta que não pode ser NENHUMA das duas — tem uma emissão por confirmar, e
    é o gestor que a resolve. A nota certa já existia e o ecrã já a sabia
    desenhar; faltava escolhê-la."""
    normal = {"id": "v-9", "estado": "aberta", "totais": {"total": 1.00}}
    travada = dict(normal, id="v-10", emissao_por_confirmar=True)

    assert _motivos_do_ecra([normal, travada], tmp_path) == ["balcao", "travada"], (
        "A conta travada voltou a sair da frente com a nota do balcão — a que "
        "lhe promete um «Retomar esta conta» que não a desbloqueia, e que lhe "
        "esconde a única coisa verdadeira sobre ela."
    )


def test_uma_conta_normal_nunca_leva_a_nota_da_travada(tmp_path):
    """O reverso, e vale tanto como o de cima: pôr a nota da travada em
    qualquer conta que ceda o lugar mandava a operadora chamar o gestor por
    causa de um café — e tirava-lhe o «Retomar esta conta», que é a única
    saída que a conta normal tem.

    Os dois casos são o mesmo de outra maneira: o campo AUSENTE (uma resposta
    de uma versão do servidor anterior a ele) tem de ler-se como conta normal,
    e não como travada."""
    sem_campo = {"id": "v-1", "estado": "aberta"}
    a_false = {"id": "v-2", "estado": "aberta", "emissao_por_confirmar": False}

    assert _motivos_do_ecra([sem_campo, a_false], tmp_path) == ["balcao", "balcao"]


def test_a_porta_de_saida_e_mesmo_o_por_conta_de_lado():
    """`cederOLugarDaConta` não pode ser um SEGUNDO caminho de saída: tem de
    acabar no `porContaDeLado`, que é o que grava a conta e deixa a nota — e o
    motivo tem de sair do `motivoDeQuemCedeOLugar`, nunca de um literal
    escrito à mão aqui dentro (que é onde nenhum teste lhe chega)."""
    corpo = _so_codigo(
        _corpo_da_funcao(_ler(_POS_VENDA), _ASSINATURA_CEDER, _POS_VENDA))
    assert "motivoDeQuemCedeOLugar(" in corpo, (
        "O `cederOLugarDaConta` voltou a decidir o motivo por sua conta. "
        "Escrito aqui dentro, o motivo deixa de ser executável por um teste — "
        "e foi assim que ele ficou preso em `'balcao'` durante duas rondas."
    )
    assert "porContaDeLado(" in corpo, (
        "O `cederOLugarDaConta` deixou de acabar no `porContaDeLado` — passou "
        "a ser um segundo caminho por onde uma conta sai do ecrã, que é "
        "exactamente o que a regra deste ficheiro proíbe."
    )
    assert "ehUmaDasPartes(" in corpo, (
        "O `cederOLugarDaConta` deixou de distinguir uma PARTE (que não sai de "
        "vista nenhuma — está na lista) de uma conta do balcão. Sem isso, "
        "trocar de pessoa a cobrar enchia o painel de notas sobre contas que "
        "ninguém perdeu."
    )


def test_a_nota_do_painel_e_uma_LISTA_e_nao_um_lugar_so():
    """Pôr uma segunda conta de lado apagava a nota da primeira — a mesma
    desaparição silenciosa que estas notas existem para impedir, e logo sobre a
    conta TRAVADA, que é a que o gestor precisa de ir buscar. Com dois
    caminhos novos a chamar isto, deixou de ser uma hipótese remota."""
    corpo = _sem_comentarios(
        _corpo_da_funcao(_ler(_POS_VENDA), _ASSINATURA_POR_DE_LADO, _POS_VENDA))
    assert "setContasDeLado((postas) =>" in corpo, (
        "O `porContaDeLado` voltou a escrever uma conta só. A segunda apaga a "
        "nota da primeira."
    )
    assert "...postas" in corpo, (
        "O `porContaDeLado` deixou de ACRESCENTAR à lista das contas de lado — "
        "escreve por cima dela."
    )
    venda = _ler(_POS_VENDA)
    assert "contasDeLado.map((conta) =>" in venda, (
        "O painel voltou a desenhar uma nota só, e não uma por conta."
    )


def test_as_saidas_da_conta_em_curso_estao_todas_contadas():
    """A rede por baixo dos três testes de cima: percorridos um a um TODOS os
    `aplicarVenda(` do ficheiro, os únicos que largam a conta em curso
    (`aplicarVenda(null)`) são os que já se sabe porque o fazem. Um número a
    subir sem uma linha neste teste é um caminho novo por onde uma conta pode
    voltar a sair em silêncio — e obriga a olhar para ele."""
    codigo = _so_codigo(_ler(_POS_VENDA))
    largam = codigo.count("aplicarVenda(null)")
    assert largam == 12, (
        "O número de sítios que largam a conta em curso mudou (encontrei %d, "
        "eram 12). Os doze, e a razão de cada um:\n"
        "  1. `recarregarVenda` — o servidor RESPONDEU e recusou: sabe-se que\n"
        "     o ecrã está errado, e mostrar a antiga era manter um estado já\n"
        "     sabido falso.\n"
        "  2. `carregarTudo` — a conta que a `GET /pos/venda/aberta` devolveu\n"
        "     é uma das PARTES recuperadas: vai-se à lista delas, não se\n"
        "     apresenta uma pessoa como se fosse a conta toda.\n"
        "  3. `cancelarConta` — acabou de ser cancelada no servidor.\n"
        "  4. `porContaDeLado` — A PORTA: grava a conta e deixa a nota.\n"
        "  5. e 6. `cederOLugarDaConta` — os dois casos em que não há nada a\n"
        "     perder de vista: uma PARTE (está na lista das partes) e uma\n"
        "     conta que o servidor já deu por terminada.\n"
        "  7. `repartir` — a mãe passou a `separada` e não emite mais nada.\n"
        "  8. e 9. `repartir`, sem resposta do servidor — a mãe foi mesmo\n"
        "     repartida, ou já não estava aberta: nos dois casos a conta que\n"
        "     estava à frente deixou de existir.\n"
        " 10. `perguntarPelaConta` — a conta À FRENTE já não está aberta: foi\n"
        "     resolvida pelo gestor.\n"
        " 11. `voltarDoFinalizar` — a venda foi emitida e há documento à\n"
        "     vista.\n"
        " 12. `voltarDoFinalizar` — a PARTE sai da frente para a lista das\n"
        "     partes, para onde o ecrã vai a seguir.\n"
        "Se acrescentou um, confirme que a conta que ele larga não fica aberta "
        "no servidor sem nada no ecrã a dizê-lo — e actualize este número."
        % largam
    )


# --- "0.9666699999999999 Uni." -----------------------------------------------
#
# O painel escreve "N Produtos / N Uni.", e as unidades eram somadas em cru:
# `soma + Number(li.quantidade)`. Numa parte recuperada de uma conta dividida,
# cujas quantidades têm CINCO casas (`reparticao.CASAS_DA_QUANTIDADE`), isso
# dava **"2 Produtos / 0.9666699999999999 Uni."**. Não mexe em dinheiro — o
# total é sempre o `venda.totais.total` do servidor —, mas é o género de número
# que faz a operadora desconfiar de tudo o resto que está no mesmo ecrã, e ela
# tem o cliente à frente.

_ASSINATURA_UNIDADES = "export const unidadesDaConta = (linhas) =>"
_LINHA_CASAS = "export const CASAS_DA_QUANTIDADE_POS = "
_LINHA_UNIDADES_POR_QTD = "const UNIDADES_POR_QUANTIDADE = "


def _linha_solta(texto: str, prefixo: str) -> str:
    if prefixo not in texto:
        pytest.fail("Não encontrei `%s` em %s." % (prefixo, _LIB_POS.name))
    inicio = texto.index(prefixo)
    return texto[inicio:texto.index("\n", inicio)].replace("export ", "", 1)


def test_a_resolucao_da_quantidade_e_a_MESMA_dos_dois_lados():
    """O ecrã soma quantidades que o SERVIDOR gravou com
    `reparticao.CASAS_DA_QUANTIDADE` casas. Duas resoluções diferentes davam
    duas contagens diferentes da mesma conta — e a do ecrã seria a errada."""
    from faturacao.reparticao import CASAS_DA_QUANTIDADE

    linha = _linha_solta(_ler(_LIB_POS), _LINHA_CASAS)
    valor = int(linha.split("=")[1].strip().rstrip(";"))
    assert valor == CASAS_DA_QUANTIDADE, (
        "O POS conta as quantidades a %d casas e o servidor grava-as a %d."
        % (valor, CASAS_DA_QUANTIDADE)
    )


def _unidades_no_ecra(contas, tmp_path: Path):
    """Corre em Node a soma das unidades TAL COMO ela está no `lib/pos.js`, e
    ao lado dela a soma em cru que lá estava antes — para se ver a diferença
    em vez de se acreditar nela."""
    lib = _ler(_LIB_POS)
    guiao = tmp_path / "unidades.js"
    guiao.write_text(
        "\n".join([
            _linha_solta(lib, _LINHA_CASAS),
            _linha_solta(lib, _LINHA_UNIDADES_POR_QTD),
            _corpo_da_funcao(lib, _ASSINATURA_UNIDADES, _LIB_POS).replace("export ", "", 1),
            # A versão de antes, escrita aqui de propósito: é o único sítio do
            # repositório onde ela ainda existe, e é ela que dá sentido ao
            # teste — sem uma referência do defeito, o guarda podia estar a
            # comparar a correcção consigo própria.
            "const emCru = (linhas) => (linhas || []).reduce("
            "  (soma, li) => soma + (Number(li.quantidade) || 0), 0);",
            "const contas = %s;" % json.dumps(contas),
            "process.stdout.write(JSON.stringify(contas.map((linhas) => ({",
            "  agora: String(unidadesDaConta(linhas)),",
            "  antes: String(emCru(linhas)),",
            "}))));",
        ]),
        encoding="utf-8",
    )
    resultado = subprocess.run(
        [_node(), str(guiao)], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if resultado.returncode != 0:
        pytest.fail(
            "O JavaScript do ecrã não correu:\n%s"
            % resultado.stderr.decode("utf-8", "replace")
        )
    return json.loads(resultado.stdout.decode("utf-8"))


def _contas_de_partes_reais():
    """Contas montadas com as quantidades que o SERVIDOR produz mesmo ao
    repartir — `venda._partes_de_uma_linha`, a função a sério. Inventar aqui
    quantidades de cinco casas dava um teste sobre números que o balcão nunca
    vê."""
    from faturacao.venda import _partes_de_uma_linha

    modelo = {
        "id": "linha-1", "produto_id": "prod-1", "produto_nome": "Açaí Regular",
        "produto_preco": 8.99, "produto_tax_id": "INT", "quantidade": 1, "opcoes": [],
        "preco_override": None, "tax_override": None, "desconto_pct": None,
        "desconto_eur": None,
    }
    contas = []
    for preco in (8.99, 7.05, 7.15, 12.34, 3.50):
        for quantidade in (1, 2, 3):
            for pessoas in (2, 3, 5, 6, 7):
                linha = dict(modelo, produto_preco=preco, quantidade=quantidade)
                try:
                    fatias = [p for p in _partes_de_uma_linha(linha, pessoas) if p]
                except ValueError:
                    continue
                # Uma conta de UMA parte (uma linha), e a conta inteira das
                # fatias todas: as duas aparecem no painel em momentos
                # diferentes.
                contas.append([fatias[0]])
                contas.append(fatias)
    return contas


def test_as_unidades_de_uma_parte_recuperada_ja_nao_tem_lixo(tmp_path):
    """Para cada conta possível, o que o painel escreve é a soma exacta das
    quantidades — nunca uma cauda de dígitos da vírgula flutuante."""
    from decimal import Decimal

    contas = _contas_de_partes_reais()
    saida = _unidades_no_ecra(contas, tmp_path)

    errados = []
    for linhas, r in zip(contas, saida):
        exacto = sum(
            (Decimal(str(li["quantidade"])) for li in linhas), Decimal("0")
        ).normalize()
        if Decimal(r["agora"]) != exacto:
            errados.append((linhas, r["agora"], str(exacto)))
    assert errados == [], (
        "As unidades do painel deixaram de ser a soma exacta das quantidades. "
        "Os primeiros: %s" % errados[:3]
    )


def test_a_malha_das_unidades_apanha_mesmo_a_soma_em_cru(tmp_path):
    """A prova por mutação: com a soma de antes, ALGUM destes casos tem de sair
    com a cauda de dígitos. Sem isto, o teste de cima podia estar a verificar
    uma malha onde as duas somas dão sempre o mesmo — verde para sempre, e sem
    defender nada."""
    contas = _contas_de_partes_reais()
    saida = _unidades_no_ecra(contas, tmp_path)

    com_lixo = [r["antes"] for r in saida if len(r["antes"]) > 8]
    assert com_lixo, (
        "Com a soma em cru, nenhuma destas contas produziu lixo decimal — a "
        "malha de casos deixou de ter quantidades repartidas."
    )
    # E a correcção não deixa passar nenhum deles.
    assert [r["agora"] for r in saida if len(r["agora"]) > 8] == [], (
        "A soma corrigida ainda escreve caudas de dígitos: %s"
        % [r["agora"] for r in saida if len(r["agora"]) > 8][:3]
    )
