"""**Os pontos L'Açaí no ecrã do POS** — montado e carregado, não lido.

A regra nova do dono: ganha os pontos quem mostra a app na caixa antes de
pagar. A funcionária lê o QR com o leitor do POS HP (um teclado: escreve e dá
Enter) ou com a câmara do Surface, e o Finalizar diz «Pontos para: Ana ✓».

Os ecrãs do POS desenham-se sem servidor nenhum, e já foram defeitos a
produção assim. Por isso aqui monta-se a janela e o `PosVenda` a sério, com o
servidor fabricado à frente do axios, escreve-se no campo, submete-se o
formulário, e afirma-se o PEDIDO que sai e o que fica no ecrã.

**O que este ficheiro NÃO cobre:** a câmara. O jsdom não tem `getUserMedia`
nem `<canvas>`; a câmara vê-se no browser (Task 6 do plano C2) e, a sério,
com o dono na loja.
"""
import json

import pytest

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _COMPONENTES
from .test_o_dividir_e_o_separar_no_ecra import (
    _ACAI, _COOKIE, _L_ACAI, _L_COOKIE, _arranque, _conta, _correr, _linha)

_CODIGO = "LQ7K2MN8P3QRSTUV4WXYZ9AB"
_MSG_QR_INVALIDO = "QR inválido ou expirado — peça ao cliente para abrir o QR outra vez."
_MSG_APP_EM_BAIXO = "Não foi possível falar com a app agora. A fatura pode seguir sem pontos."

_UTEIS = "\n".join([
    "function escrever(el, valor) {",
    "  Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, 'value')",
    "    .set.call(el, valor);",
    "  el.dispatchEvent(new dom.window.Event('input', { bubbles: true }));",
    "}",
    # O leitor escreve o código e dá Enter; o Enter de um campo dentro de um
    # <form> é a submissão do formulário. O jsdom não faz essa submissão
    # implícita, por isso submete-se o FORMULÁRIO — o caminho do browser.
    "async function lerComOLeitor(alvo, codigo) {",
    "  const campo = alvo.querySelector('#qr-dos-pontos');",
    "  if (!campo) throw new Error('a janela Ler QR não tem o campo do leitor: '",
    "    + textoVisivel(alvo).slice(0, 400));",
    "  await act(async () => { escrever(campo, codigo); });",
    "  await act(async () => { campo.closest('form').dispatchEvent(",
    "    new dom.window.Event('submit', { bubbles: true, cancelable: true })); });",
    "  await act(async () => {});",
    "}",
    "const falha = (status, detail) => () => {",
    "  const e = new Error('Request failed with status code ' + status);",
    "  e.response = { status, data: detail ? { detail } : {} };",
    "  throw e;",
    "};",
])


# --- A janela, sozinha ----------------------------------------------------------


@pytest.fixture(scope="module")
def janela(tmp_path_factory):
    cenario = "\n".join([
        _COMPONENTES,
        _UTEIS,
        "const lib = carregar(path.join(RAIZ, 'lib', 'pos.js'));",
        "lib.guardarOperador('ot', { id: 'o1', nome: 'Ana' });",
        "const PosLerQr = carregar(path.join(POS, 'PosLerQr.js')).default;",
        "const ANA = () => ({ data: { ligacao_id: 'lig-1', primeiro_nome: 'Ana' } });",
        "async function abrir(resposta) {",
        "  RESPOSTAS_POS['POST /pos/pontos/ler'] = resposta;",
        "  pedidos.length = 0;",
        "  const ligadas = [];",
        "  const alvo = document.getElementById('raiz');",
        "  const raiz = createRoot(alvo);",
        "  await act(async () => { raiz.render(React.createElement(PosLerQr, {",
        "    vendaId: 'v-1', onLigada: (l) => ligadas.push(l), onFechar: () => {},",
        "  })); });",
        "  return {",
        "    alvo, ligadas,",
        "    lidos: () => pedidos.filter((p) => p.url.endsWith('/pos/pontos/ler')),",
        "    fechar: async () => {",
        "      await act(async () => { raiz.unmount(); });",
        "      alvo.innerHTML = '';",
        "    },",
        "  };",
        "}",
        "(async () => {",
        "  const saida = {};",
        "  {",
        "    const j = await abrir(ANA);",
        "    await lerComOLeitor(j.alvo, %s);" % json.dumps("  " + _CODIGO + " "),
        "    saida.lido = { ligadas: j.ligadas, corpos: j.lidos().map((p) => p.corpo) };",
        "    await j.fechar();",
        "  }",
        "  {",
        "    const j = await abrir(ANA);",
        "    await lerComOLeitor(j.alvo, '   ');",
        "    saida.vazio = j.lidos().length;",
        "    await j.fechar();",
        "  }",
        # O código da CONTA («LA» + 8 dígitos) escrito no campo do leitor. A
        # janela tem de o reconhecer SOZINHA — sem pedido nenhum ao servidor.
        "  {",
        "    const j = await abrir(ANA);",
        "    await lerComOLeitor(j.alvo, 'LA12345678');",
        "    saida.conta = { visivel: textoVisivel(j.alvo), lidos: j.lidos().length,",
        "      ligadas: j.ligadas, campo: j.alvo.querySelector('#qr-dos-pontos').value };",
        "    await j.fechar();",
        "  }",
        "  for (const [nome, resposta] of [",
        "    ['invalido', falha(404, %s)]," % json.dumps(_MSG_QR_INVALIDO),
        "    ['em_baixo', falha(503, %s)]," % json.dumps(_MSG_APP_EM_BAIXO),
        "    ['sem_resposta', () => { throw new Error('Network Error'); }],",
        "  ]) {",
        "    const j = await abrir(resposta);",
        "    await lerComOLeitor(j.alvo, %s);" % json.dumps(_CODIGO),
        "    saida[nome] = { visivel: textoVisivel(j.alvo), ligadas: j.ligadas,",
        "      campo: j.alvo.querySelector('#qr-dos-pontos').value };",
        "    await j.fechar();",
        "  }",
        "  {",
        "    let soltar = null;",
        "    const j = await abrir(() => new Promise((r) => { soltar = r; }));",
        "    const campo = j.alvo.querySelector('#qr-dos-pontos');",
        "    await act(async () => { escrever(campo, %s); });" % json.dumps(_CODIGO),
        "    const submeter = () => campo.closest('form').dispatchEvent(",
        "      new dom.window.Event('submit', { bubbles: true, cancelable: true }));",
        "    await act(async () => { submeter(); submeter(); });",
        "    saida.duplo = j.lidos().length;",
        "    await act(async () => { if (soltar) soltar(ANA()); });",
        "    await j.fechar();",
        "  }",
        "  process.stdout.write(JSON.stringify(saida));",
        "})().catch((e) => { console.error(e); process.exit(3); });",
    ])
    return _montar_no_node(
        cenario, tmp_path_factory.mktemp("janela-qr"), "montar-janela-qr.js")


def test_o_codigo_do_leitor_vai_ao_servidor_com_a_conta_e_liga_o_cliente(janela):
    """Os espaços que o leitor ou a mão deixem à volta não viajam."""
    assert janela["lido"]["corpos"] == [{"venda_id": "v-1", "codigo": _CODIGO}]
    assert janela["lido"]["ligadas"] == [{"id": "lig-1", "primeiro_nome": "Ana"}]


def test_um_Enter_sem_codigo_nao_pergunta_nada(janela):
    assert janela["vazio"] == 0


def test_o_codigo_da_CONTA_e_explicado_pela_JANELA_sem_perguntar_ao_servidor(janela):
    """**A guarda do formato tem de estar LIGADA ao ecrã, não só existir.**

    A função pura `recadoDeCodigoQrErrado` prova-se sozinha em
    test_o_codigo_errado_no_qr_do_pos.py — mas nada obrigava o `PosLerQr` a
    chamá-la. Trocar a linha por `const recado = null` deixava a suite inteira
    verde (442 passed) e o balcão voltava a ouvir «QR inválido ou expirado» para
    um código de conta, que é a frase que originou este pedido.

    Três coisas de uma vez: a frase certa aparece, NÃO se gasta uma viagem ao
    servidor, e o campo fica limpo para a leitura seguinte (o leitor escreve por
    cima, e com o código recusado lá dentro a leitura seguinte chegava colada a
    ele).
    """
    conta = janela["conta"]
    assert "código da conta do cliente" in conta["visivel"], conta["visivel"][:400]
    assert conta["lidos"] == 0, "o código da conta não pode ir ao servidor"
    assert conta["ligadas"] == []
    assert conta["campo"] == ""


@pytest.mark.parametrize("caso,frase", [
    ("invalido", _MSG_QR_INVALIDO),
    ("em_baixo", _MSG_APP_EM_BAIXO),
    ("sem_resposta", _MSG_APP_EM_BAIXO),
])
def test_uma_leitura_recusada_diz_porque_e_nao_liga_ninguem(janela, caso, frase):
    """A frase do servidor no 404 e no 503; sem resposta nenhuma, a do 503 —
    para o balcão é a mesma coisa: a fatura segue sem pontos."""
    assert frase in janela[caso]["visivel"], janela[caso]["visivel"][:400]
    assert janela[caso]["ligadas"] == []


def test_depois_de_uma_recusa_o_campo_fica_limpo_para_a_leitura_seguinte(janela):
    """O leitor escreve POR CIMA do que estiver no campo. Com o código gasto lá
    dentro, a leitura seguinte chegava colada a ele — e era recusada sempre."""
    assert janela["invalido"]["campo"] == ""


def test_dois_Enter_seguidos_so_perguntam_uma_vez(janela):
    """Uma leitura de cada vez. A câmara descodifica várias imagens por segundo
    e um leitor pode mandar o Enter duas vezes."""
    assert janela["duplo"] == 1


# --- O cartão no Finalizar, e o que o EMITIR leva -----------------------------
#
# Pelo `PosVenda` montado, e não pelo `PosFinalizar` sozinho: o que interessa
# provar é o CORPO do `POST /pos/venda/{id}/finalizar`, e entre o cartão e esse
# pedido há dois ficheiros. Um `pontos_ligacao` que o `PosVenda` deixasse cair
# pelo caminho tinha um cartão verde no ecrã e nenhum ponto na app.
#
# (A única excepção é a última fixture, `parte_seguinte`: essa monta o
# `PosFinalizar` sozinho de propósito, porque o que ela precisa de fazer é
# trocar a venda COM o ecrã montado — a razão está escrita lá em baixo.)

_EMITIDA = dict(
    _conta("v-1", [_L_COOKIE, _L_ACAI], estado="emitida"),
    documento={"id": "d-1", "numero": "FS 01P2026/99", "atcud": "A-99",
               "total": 12.79, "modo": "normal", "vendus_document_id": 1},
)


def _no_finalizar(extra):
    return _arranque("\n".join([
        "RESPOSTAS_POS['/pos/venda/aberta'] = () => ({ data: %s });"
        % json.dumps(_conta("v-1", [_L_COOKIE, _L_ACAI]), ensure_ascii=False),
        "RESPOSTAS_POS['POST /pos/venda/v-1/finalizar'] = () => ({ data: %s });"
        % json.dumps(_EMITIDA, ensure_ascii=False),
        _UTEIS,
        extra,
    ]))


# Escolher o pagamento e emitir. `carregar_em` REBENTA se o botão estiver
# morto — é isso que torna «o EMITIR está vivo» uma afirmação e não um desejo.
_EMITIR = "\n".join([
    "await carregar_em('Dinheiro');",
    "const emitirVivo = !!botao('EMITIR DOCUMENTO');",
    "await carregar_em('EMITIR DOCUMENTO');",
    "await act(async () => {});",
    "const corpos = pedidos.filter((p) => p.url.endsWith('/pos/venda/v-1/finalizar'))",
    "  .map((p) => p.corpo);",
])


@pytest.fixture(scope="module")
def sem_pontos(tmp_path_factory):
    """Sem QR nenhum — a venda mais comum. E com uma ligação guardada para
    OUTRA conta, que não pode aparecer nesta."""
    cenario = _no_finalizar(
        "lib.guardarPontosDaConta('v-0', { id: 'lig-0', primeiro_nome: 'Rui' });")
    return _correr("\n".join([
        cenario,
        "const noFinalizar = textoVisivel(alvo);",
        _EMITIR,
        "process.stdout.write(JSON.stringify({ noFinalizar, emitirVivo, corpos }));",
    ]), tmp_path_factory, "pontos-sem")


@pytest.fixture(scope="module")
def lido(tmp_path_factory):
    cenario = _no_finalizar(
        "RESPOSTAS_POS['POST /pos/pontos/ler'] = () => ({"
        " data: { ligacao_id: 'lig-1', primeiro_nome: 'Ana' } });")
    return _correr("\n".join([
        cenario,
        "await carregar_em('Ler QR do cliente');",
        "await lerComOLeitor(alvo, %s);" % json.dumps(_CODIGO),
        "const ligado = textoVisivel(alvo);",
        "const guardada = lib.lerPontosDaConta('v-1');",
        # Sair para a conta e voltar: o cliente lembrou-se de mais uma coisa.
        "const seta = [...alvo.querySelectorAll('button')].find(",
        "  (b) => b.querySelector('[data-icone=\"ArrowLeft\"]'));",
        "if (!seta) throw new Error('sem seta de voltar no Finalizar');",
        "await act(async () => { seta.click(); });",
        "await act(async () => {});",
        "await carregar_em('FINALIZAR');",
        "const depoisDeVoltar = textoVisivel(alvo);",
        _EMITIR,
        "process.stdout.write(JSON.stringify({",
        "  ligado, guardada, depoisDeVoltar, emitirVivo, corpos }));",
    ]), tmp_path_factory, "pontos-lido")


@pytest.fixture(scope="module")
def recusado(tmp_path_factory):
    cenario = _no_finalizar(
        "RESPOSTAS_POS['POST /pos/pontos/ler'] = falha(404, %s);"
        % json.dumps(_MSG_QR_INVALIDO))
    return _correr("\n".join([
        cenario,
        "await carregar_em('Ler QR do cliente');",
        "await lerComOLeitor(alvo, %s);" % json.dumps(_CODIGO),
        "const comErro = textoVisivel(alvo);",
        _EMITIR,
        "process.stdout.write(JSON.stringify({ comErro, emitirVivo, corpos }));",
    ]), tmp_path_factory, "pontos-recusado")


@pytest.fixture(scope="module")
def guardado(tmp_path_factory):
    cenario = _no_finalizar(
        "lib.guardarPontosDaConta('v-1', { id: 'lig-9', primeiro_nome: 'Rui' });")
    return _correr("\n".join([
        cenario,
        "const comRui = textoVisivel(alvo);",
        "await carregar_em('Remover');",
        "const depoisDeRemover = textoVisivel(alvo);",
        "const guardadaDepois = lib.lerPontosDaConta('v-1');",
        _EMITIR,
        "process.stdout.write(JSON.stringify({",
        "  comRui, depoisDeRemover, guardadaDepois, emitirVivo, corpos }));",
    ]), tmp_path_factory, "pontos-guardado")


def test_o_cartao_dos_pontos_esta_entre_o_Cliente_e_o_Pagamento(sem_pontos):
    ecra = sem_pontos["noFinalizar"]
    assert "Pontos L'Açaí" in ecra, ecra[:600]
    assert ecra.index("Cliente") < ecra.index("Pontos L'Açaí") < ecra.index("Pagamento"), ecra[:600]


def test_sem_leitura_o_cartao_so_oferece_ler_o_QR(sem_pontos):
    assert "Ler QR do cliente" in sem_pontos["noFinalizar"]
    assert "Pontos para" not in sem_pontos["noFinalizar"]


def test_a_ligacao_de_OUTRA_conta_nao_aparece_nesta(sem_pontos):
    assert "Rui" not in sem_pontos["noFinalizar"], sem_pontos["noFinalizar"][:600]


def test_sem_pontos_o_EMITIR_manda_pontos_ligacao_a_null_e_nao_o_omite(sem_pontos):
    """**Sempre presente.** É assim que o servidor grava
    `dados_pagamento.pontos_ligacao` em cada tentativa, e uma tentativa sem
    pontos nunca deixa agarrado à venda o cliente de uma anterior."""
    assert sem_pontos["emitirVivo"] is True
    assert len(sem_pontos["corpos"]) == 1, sem_pontos["corpos"]
    corpo = sem_pontos["corpos"][0]
    assert "pontos_ligacao" in corpo, "o EMITIR deixou de mandar pontos_ligacao: %s" % corpo
    assert corpo["pontos_ligacao"] is None


def test_ler_o_QR_mostra_so_o_primeiro_nome_e_o_Remover(lido):
    assert "Pontos para: Ana ✓" in lido["ligado"], lido["ligado"][:600]
    assert "Remover" in lido["ligado"]
    assert "Ler QR do cliente" not in lido["ligado"], (
        "A janela ficou aberta, ou o cartão continua vazio, depois de ligar o cliente.")


def test_a_ligacao_fica_guardada_com_a_conta_e_sobrevive_a_voltar_a_conta(lido):
    assert lido["guardada"] == {"id": "lig-1", "primeiro_nome": "Ana"}
    assert "Pontos para: Ana ✓" in lido["depoisDeVoltar"], lido["depoisDeVoltar"][:600]


def test_o_EMITIR_leva_o_cliente_dos_pontos_ao_servidor(lido):
    assert len(lido["corpos"]) == 1, lido["corpos"]
    corpo = lido["corpos"][0]
    assert corpo["pontos_ligacao"] == {"id": "lig-1", "primeiro_nome": "Ana"}, corpo
    assert corpo["pagamentos"] == [{"tipo_pagamento_id": "tp-1", "valor": 12.79}], corpo
    assert corpo["nif"] is None


def test_uma_leitura_recusada_diz_porque_e_NAO_bloqueia_o_EMITIR(recusado):
    """**O cartão nunca entra no `motivoBloqueio`.** App em baixo, QR
    expirado, cliente sem telemóvel: a venda segue sem pontos."""
    assert _MSG_QR_INVALIDO in recusado["comErro"], recusado["comErro"][:600]
    assert "Pontos para" not in recusado["comErro"]
    assert recusado["emitirVivo"] is True
    assert recusado["corpos"][0]["pontos_ligacao"] is None


def test_Remover_esquece_o_cliente_e_o_EMITIR_segue_sem_pontos(guardado):
    assert "Pontos para: Rui ✓" in guardado["comRui"], guardado["comRui"][:600]
    assert "Ler QR do cliente" in guardado["depoisDeRemover"]
    assert guardado["guardadaDepois"] is None
    assert guardado["corpos"][0]["pontos_ligacao"] is None


# --- Trocar de PESSOA sem o ecrã se desmontar ---------------------------------
#
# **A guarda central da spec — «numa conta dividida não passa para as partes» —
# pelo caminho que o POS usa mesmo.** Entre pessoas não se desmonta nada:
# cobrada a parte 1, o `voltarDoFinalizar` faz `aplicarVenda(null)` e chama
# logo o `cobrarParte` da seguinte (`PosVenda.js:2400-2402`); o `cobrarParte`
# só troca a venda e mantém `setVista('finalizar')` (`PosVenda.js:2059-2066`);
# e o `<PosFinalizar>` (`PosVenda.js:2612-2621`) não leva `key`. Muda-lhe o
# PROP `venda` — o ecrã é o MESMO, com o mesmo estado — e a única coisa que
# limpa o cliente dos pontos é a linha `setLigacao(lerPontosDaConta(venda?.id))`
# do `useEffect([venda?.id])`.
#
# Por isso aqui não se monta de raiz: desenha-se a parte 1 e a seguir a parte 2
# na MESMA raiz, que é a única forma de exercer essa linha. Montado de raiz
# (como as fixtures de cima), quem responde é o inicializador do `useState` — e
# apagar a linha do efeito deixava-as todas verdes, com a pessoa 2 a ver
# «Pontos para: Ana ✓» e o EMITIR dela a mandar a ligação da pessoa 1: a app
# recusa-a (`ligacao_ja_usada`), a linha da fila fica `recusado`, e fica o nome
# errado à frente do cliente na caixa.

_PARTE_1 = _conta("p-1", [_L_COOKIE], mae="v-1")
_PARTE_2 = _conta("p-2", [_L_ACAI], mae="v-1")


@pytest.fixture(scope="module")
def parte_seguinte(tmp_path_factory):
    """O Finalizar a passar da pessoa 1 para a pessoa 2 SEM desmontar."""
    return _correr("\n".join([
        _COMPONENTES,
        "const lib = carregar(path.join(RAIZ, 'lib', 'pos.js'));",
        "const Finalizar = carregar(path.join(POS, 'PosFinalizar.js')).default;",
        "const TIPOS = [{ id: 'tp-1', nome: 'Dinheiro', da_troco: true, pronto: true }];",
        "const emitidos = [];",
        "const alvo = document.getElementById('raiz');",
        "const raiz = createRoot(alvo);",
        # `raiz.render` OUTRA VEZ, na mesma raiz e com o mesmo componente na
        # mesma posição: é exactamente o que o React faz quando o PosVenda
        # troca a venda entre pessoas. Uma montagem nova não provaria nada.
        "const desenhar = async (venda, numero) => {",
        "  await act(async () => { raiz.render(React.createElement(Finalizar, {",
        "    venda, tiposPagamento: TIPOS,",
        "    parte: { numero, de: 2, restanteCentimos: 0 },",
        "    onVoltar: () => {}, onAplicarDesconto: () => {},",
        "    onEmitir: (dados) => emitidos.push(dados),",
        "  })); });",
        "  await act(async () => {});",
        "};",
        "sessionStorage.clear();",
        "lib.guardarPontosDaConta('p-1', { id: 'lig-1', primeiro_nome: 'Ana' });",
        "await desenhar(%s, 1);" % json.dumps(_PARTE_1, ensure_ascii=False),
        "const naPessoa1 = textoVisivel(alvo);",
        "await desenhar(%s, 2);" % json.dumps(_PARTE_2, ensure_ascii=False),
        "const naPessoa2 = textoVisivel(alvo);",
        "const botao = (texto) => [...alvo.querySelectorAll('button')].find(",
        "  (b) => (b.textContent || '').includes(texto) && !b.disabled);",
        "const carregar_em = async (texto) => {",
        "  const b = botao(texto);",
        "  if (!b) throw new Error('sem botão vivo com o texto ' + texto + ' — no ecrã: '",
        "    + textoVisivel(alvo).slice(0, 500));",
        "  await act(async () => { b.click(); });",
        "  await act(async () => {});",
        "};",
        "await carregar_em('Dinheiro');",
        "await carregar_em('EMITIR DOCUMENTO');",
        "await act(async () => { raiz.unmount(); });",
        "process.stdout.write(JSON.stringify({ naPessoa1, naPessoa2, emitidos,",
        "  guardadaNaPessoa1: lib.lerPontosDaConta('p-1'),",
        "  guardadaNaPessoa2: lib.lerPontosDaConta('p-2') }));",
    ]), tmp_path_factory, "pontos-parte-seguinte")


def test_a_pessoa_SEGUINTE_da_conta_dividida_nao_herda_o_cliente_da_anterior(parte_seguinte):
    """**A guarda da spec, pelo caminho real.** O ecrã não se desmonta entre
    pessoas — o que muda é o prop `venda`."""
    assert "Pontos para: Ana ✓" in parte_seguinte["naPessoa1"], (
        parte_seguinte["naPessoa1"][:600])
    assert "Pontos para" not in parte_seguinte["naPessoa2"], (
        "A pessoa 2 ficou com o cliente dos pontos da pessoa 1: %s"
        % parte_seguinte["naPessoa2"][:600])
    assert "Ler QR do cliente" in parte_seguinte["naPessoa2"], (
        parte_seguinte["naPessoa2"][:600])
    assert parte_seguinte["guardadaNaPessoa2"] is None
    # E desenhar a pessoa 2 não escreveu na gaveta: o cliente da pessoa 1
    # continua lá. A gaveta muda-se no GESTO (ler ou remover), nunca ao montar.
    assert parte_seguinte["guardadaNaPessoa1"] == {"id": "lig-1", "primeiro_nome": "Ana"}


def test_o_EMITIR_da_pessoa_SEGUINTE_vai_sem_pontos(parte_seguinte):
    """A fatura da pessoa 2 não pode levar a ligação da pessoa 1: a app só
    credita UMA fatura por ligação e recusa-a com `ligacao_ja_usada` — quem
    mostrou a app ficava sem nada e a caixa com o nome errado no ecrã."""
    assert len(parte_seguinte["emitidos"]) == 1, parte_seguinte["emitidos"]
    dados = parte_seguinte["emitidos"][0]
    assert "pontos_ligacao" in dados, (
        "o EMITIR deixou de mandar pontos_ligacao: %s" % dados)
    assert dados["pontos_ligacao"] is None, (
        "O EMITIR da pessoa 2 levou a ligação da pessoa 1: %s" % dados)


# --- A pergunta ANTES do ecrã de pagamento ------------------------------------
#
# **O cartão do ecrã de pagamento não chegava: ninguém carregava nele.** Quando
# a operadora lá chegava, o cliente já tinha guardado o telemóvel — e os pontos
# do balcão dependem de alguém se lembrar de os pedir com a fila à frente.
#
# Agora o FINALIZAR abre primeiro a MESMA janela (`PosLerQr`), com a câmara já
# acesa: mostrar o QR é o «sim» e não custa um clique nenhum; «Não» é o único
# botão. As duas saídas seguem para o pagamento — esta pergunta nunca prende
# uma venda, que é a regra dos pontos desde o princípio.
#
# Prova-se pelo `PosVenda` montado, e não por leitura: entre o botão e o pedido
# que sai há três ficheiros (PosVenda → PosLerQr → PosFinalizar), e a ligação
# passa de um para o outro pela gaveta da sessão. Um `guardarPontosDaConta` que
# ficasse pelo caminho dava um ecrã verde e nenhum ponto na app.


def _na_pergunta(extra):
    """O POS com a conta feita e o FINALIZAR já carregado — com a pergunta dos
    pontos à frente, que é o passo novo."""
    return _arranque("\n".join([
        "RESPOSTAS_POS['/pos/venda/aberta'] = () => ({ data: %s });"
        % json.dumps(_conta("v-1", [_L_COOKIE, _L_ACAI]), ensure_ascii=False),
        "RESPOSTAS_POS['POST /pos/venda/v-1/finalizar'] = () => ({ data: %s });"
        % json.dumps(_EMITIDA, ensure_ascii=False),
        _UTEIS,
        extra,
    ]), parar_nos_pontos=True)


@pytest.fixture(scope="module")
def pergunta(tmp_path_factory):
    """O que está no ecrã no instante a seguir ao FINALIZAR."""
    return _correr("\n".join([
        _na_pergunta(""),
        "const naPergunta = textoVisivel(alvo);",
        "const temCampoDoLeitor = !!alvo.querySelector('#qr-dos-pontos');",
        "const temNao = !!botao('Não');",
        "process.stdout.write(JSON.stringify({ naPergunta, temCampoDoLeitor, temNao }));",
    ]), tmp_path_factory, "pontos-pergunta")


@pytest.fixture(scope="module")
def pergunta_nao(tmp_path_factory):
    """«Não» — a venda mais comum, a de quem não tem a app."""
    return _correr("\n".join([
        _na_pergunta(""),
        "await carregar_em('Não');",
        "const noFinalizar = textoVisivel(alvo);",
        "const guardada = lib.lerPontosDaConta('v-1');",
        _EMITIR,
        "process.stdout.write(JSON.stringify({",
        "  noFinalizar, guardada, emitirVivo, corpos }));",
    ]), tmp_path_factory, "pontos-pergunta-nao")


@pytest.fixture(scope="module")
def pergunta_lida(tmp_path_factory):
    """O QR lido NA PERGUNTA — o «sim» que não é botão nenhum."""
    return _correr("\n".join([
        _na_pergunta(
            "RESPOSTAS_POS['POST /pos/pontos/ler'] = () => ({"
            " data: { ligacao_id: 'lig-1', primeiro_nome: 'Ana' } });"),
        "await lerComOLeitor(alvo, %s);" % json.dumps(_CODIGO),
        "const noFinalizar = textoVisivel(alvo);",
        "const guardada = lib.lerPontosDaConta('v-1');",
        _EMITIR,
        "process.stdout.write(JSON.stringify({",
        "  noFinalizar, guardada, emitirVivo, corpos }));",
    ]), tmp_path_factory, "pontos-pergunta-lida")


def test_o_FINALIZAR_pergunta_pelos_pontos_antes_do_ecra_de_pagamento(pergunta):
    """A pergunta do dono, palavra por palavra, e ANTES do pagamento.

    O `EMITIR DOCUMENTO` é o que separa os dois ecrãs: se ele já estiver aqui,
    a pergunta passou a ser um enfeite POR CIMA do pagamento e deixou de estar
    no caminho — que é a única coisa que a faz ser usada."""
    ecra = pergunta["naPergunta"]
    assert "Quer atribuir os pontos?" in ecra, ecra[:600]
    assert "EMITIR DOCUMENTO" not in ecra, (
        "A pergunta deixou de estar ENTRE o FINALIZAR e o pagamento: %s" % ecra[:600])


def test_a_pergunta_e_a_MESMA_janela_do_QR_e_a_saida_chama_se_Nao(pergunta):
    """O campo do leitor é a assinatura do `PosLerQr`: é nele que o leitor do
    POS HP escreve, e é ele que a câmara dispensa. Uma pergunta que fosse só um
    «sim/não» mandava a operadora abrir a janela a seguir — dois cliques em vez
    de nenhum, que era o problema a resolver.

    E a saída chama-se «Não», não «Fechar»: quem não pediu para ler nada tem de
    ver num relance por onde segue."""
    assert pergunta["temCampoDoLeitor"] is True, pergunta["naPergunta"][:600]
    assert pergunta["temNao"] is True, pergunta["naPergunta"][:600]
    assert "O cliente abre a app L'Açaí" in pergunta["naPergunta"]


def test_o_Nao_segue_para_o_pagamento_e_a_fatura_sai_sem_pontos(pergunta_nao):
    """**A pergunta nunca prende uma venda.** «Não» é um clique e o ecrã de
    pagamento aparece, com o cartão dos pontos vazio, como sempre esteve."""
    ecra = pergunta_nao["noFinalizar"]
    assert "Quer atribuir os pontos?" not in ecra, ecra[:600]
    assert "Ler QR do cliente" in ecra, ecra[:600]
    assert "Pontos para" not in ecra, ecra[:600]
    assert pergunta_nao["guardada"] is None
    assert pergunta_nao["emitirVivo"] is True
    assert pergunta_nao["corpos"][0]["pontos_ligacao"] is None


def test_o_QR_lido_NA_PERGUNTA_chega_ao_ecra_de_pagamento_e_ao_EMITIR(pergunta_lida):
    """**O trajecto todo, que é onde isto se podia partir.** A janela vive no
    `PosVenda` e o cartão vive no `PosFinalizar`: entre os dois só está a gaveta
    da sessão (`guardarPontosDaConta`). Sem essa escrita, a operadora via o
    apito e o nome na janela, o ecrã de pagamento aparecia vazio, e a fatura
    saía sem pontos nenhuns — com o cliente convencido de que os tinha."""
    ecra = pergunta_lida["noFinalizar"]
    assert "Quer atribuir os pontos?" not in ecra, (
        "A janela não fechou depois de ler o QR: %s" % ecra[:600])
    assert "Pontos para: Ana ✓" in ecra, ecra[:600]
    assert pergunta_lida["guardada"] == {"id": "lig-1", "primeiro_nome": "Ana"}
    assert len(pergunta_lida["corpos"]) == 1, pergunta_lida["corpos"]
    assert pergunta_lida["corpos"][0]["pontos_ligacao"] == {
        "id": "lig-1", "primeiro_nome": "Ana"}


def test_a_conta_que_JA_tem_cliente_nao_volta_a_ser_perguntada(lido):
    """Saiu do pagamento para juntar mais um artigo e voltou a carregar em
    FINALIZAR. Perguntar outra vez era um obstáculo a meio do caminho e, pior,
    um convite a ler um SEGUNDO QR por cima do primeiro — a app só credita uma
    fatura por ligação, e o segundo cliente ficava sem nada."""
    assert "Quer atribuir os pontos?" not in lido["depoisDeVoltar"], (
        lido["depoisDeVoltar"][:600])
    assert "Pontos para: Ana ✓" in lido["depoisDeVoltar"], lido["depoisDeVoltar"][:600]


# --- A conta que se PARTE esquece o cliente que lhe foi lido -------------------
#
# **A pergunta chega antes de se saber quem paga o quê, e não podia ser de outra
# maneira: «Dividir Conta» e «Separar Conta» só existem no ecrã de pagamento, ou
# seja, a JUSANTE do FINALIZAR.** Toda a conta que vai ser repartida passa
# primeiro pela pergunta — e a ligação fica presa ao id da conta INTEIRA.
#
# Daí saíam duas coisas más, as duas medidas a correr antes de isto existir:
#  · **separar** — a mãe sobrevive com o resto lá dentro, e a ligação ia com
#    ela: a fatura de quem pagava o resto saía com o nome de quem tinha
#    mostrado a app, e quem a mostrou ficava sem os pontos da SUA compra;
#  · **dividir** — a mãe fica `separada` e nunca é faturada: a ligação morria
#    ali, depois de o cliente ter ouvido o apito e visto o nome no ecrã.
#
# A regra que fica é a que já estava escrita em `lib/pos.js` («numa conta
# dividida lê-se o QR na parte de quem o mostra»): repartir ESQUECE o cliente da
# mãe, diz isso à operadora, e volta a perguntar na conta seguinte.

_PARTE_COOKIE = _conta("p-1", [_linha("x1", "p-cookie", _COOKIE, 3.80)], mae="v-1")
_PARTE_ACAI = _conta("p-2", [_linha("x2", "p-acai", _ACAI, 8.99)], mae="v-1")
_RESTO = _conta("v-1", [_L_ACAI])

# O `sonner` do banco de ensaio engole os avisos. Aqui eles interessam: esquecer
# a leitura EM SILÊNCIO era o defeito, não a correcção.
_APANHAR_AVISOS = "\n".join([
    "const avisos = [];",
    "sonner.toast.info = (m) => { avisos.push(String(m)); };",
])

_LER_QR = ("RESPOSTAS_POS['POST /pos/pontos/ler'] = () => ({"
           " data: { ligacao_id: 'lig-1', primeiro_nome: 'Ana' } });")


@pytest.fixture(scope="module")
def dividir_depois_do_qr(tmp_path_factory):
    return _correr("\n".join([
        _na_pergunta("\n".join([
            _LER_QR,
            "RESPOSTAS_POS['POST /pos/venda/v-1/dividir'] = () => ({ data: %s });"
            % json.dumps({
                "modo": "dividir",
                "conta_mae": _conta("v-1", [_L_COOKIE, _L_ACAI], estado="separada"),
                "partes": [_PARTE_COOKIE, _PARTE_ACAI],
            }, ensure_ascii=False),
            "RESPOSTAS_POS['POST /pos/venda/p-1/finalizar'] = () => ({ data: %s });"
            % json.dumps(dict(_conta("p-1", [_linha("x1", "p-cookie", _COOKIE, 3.80)],
                                     estado="emitida", mae="v-1"),
                              documento={"id": "d-2", "numero": "FS 01P2026/98", "atcud": "A-98",
                                         "total": 3.80, "modo": "normal",
                                         "vendus_document_id": 2}),
                         ensure_ascii=False),
            _APANHAR_AVISOS,
        ])),
        "await lerComOLeitor(alvo, %s);" % json.dumps(_CODIGO),
        "const comAna = textoVisivel(alvo);",
        "await carregar_em('Dividir Conta');",
        "const naPrimeiraParte = textoVisivel(alvo);",
        "await carregar_em('Dinheiro');",
        "await carregar_em('EMITIR DOCUMENTO');",
        "await act(async () => {});",
        "const corpos = pedidos.filter((p) => p.url.endsWith('/pos/venda/p-1/finalizar'))",
        "  .map((p) => p.corpo);",
        "process.stdout.write(JSON.stringify({ comAna, naPrimeiraParte, avisos, corpos,",
        "  guardadaNaMae: lib.lerPontosDaConta('v-1') }));",
    ]), tmp_path_factory, "pontos-dividir-depois-do-qr")


@pytest.fixture(scope="module")
def separar_depois_do_qr(tmp_path_factory):
    """O caminho inteiro do bloqueador: ler o QR na pergunta, separar a parte de
    uma pessoa, cobrá-la, e voltar ao RESTO — que é a MESMA conta v-1."""
    return _correr("\n".join([
        _na_pergunta("\n".join([
            _LER_QR,
            "RESPOSTAS_POS['POST /pos/venda/v-1/separar-parte'] = () => ({ data: %s });"
            % json.dumps({"parte": _PARTE_COOKIE, "conta": _RESTO}, ensure_ascii=False),
            "RESPOSTAS_POS['POST /pos/venda/p-1/finalizar'] = () => ({ data: %s });"
            % json.dumps(dict(_conta("p-1", [_linha("x1", "p-cookie", _COOKIE, 3.80)],
                                     estado="emitida", mae="v-1"),
                              documento={"id": "d-2", "numero": "FS 01P2026/98", "atcud": "A-98",
                                         "total": 3.80, "modo": "normal",
                                         "vendus_document_id": 2}),
                         ensure_ascii=False),
            _APANHAR_AVISOS,
        ])),
        "await lerComOLeitor(alvo, %s);" % json.dumps(_CODIGO),
        "await carregar_em('Separar Conta');",
        # A LINHA da conta, e não o cartão da grelha: os dois têm o nome do
        # artigo e só a linha tem o «cada» do preço unitário.
        "const linhaDoCookie = [...alvo.querySelectorAll('button')].find(",
        "  (b) => (b.textContent || '').includes(%s)" % json.dumps(_COOKIE),
        "    && (b.textContent || '').includes('cada'));",
        "if (!linhaDoCookie) throw new Error('sem linha do cookie: '",
        "  + textoVisivel(alvo).slice(0, 400));",
        "await act(async () => { linhaDoCookie.click(); });",
        "await act(async () => {});",
        "await carregar_em('COBRAR ESTA PESSOA');",
        "const naParte = textoVisivel(alvo);",
        "const guardadaNaMae = lib.lerPontosDaConta('v-1');",
        # Cobrada a parte, volta-se ao balcão e o que lá está é o RESTO — a
        # mesma conta v-1, com o açaí da outra pessoa.
        "await carregar_em('Dinheiro');",
        "await carregar_em('EMITIR DOCUMENTO');",
        "await act(async () => {});",
        "RESPOSTAS_POS['/pos/venda/aberta'] = () => ({ data: %s });"
        % json.dumps(_RESTO, ensure_ascii=False),
        "await carregar_em('Nova Venda');",
        "await carregar_em('FINALIZAR');",
        "const noResto = textoVisivel(alvo);",
        "if (botao('Não')) await carregar_em('Não');",
        "const noPagamentoDoResto = textoVisivel(alvo);",
        "await carregar_em('Dinheiro');",
        "await carregar_em('EMITIR DOCUMENTO');",
        "await act(async () => {});",
        "process.stdout.write(JSON.stringify({ naParte, guardadaNaMae, noResto,",
        "  noPagamentoDoResto, avisos,",
        "  corpoDoResto: pedidos.filter((p) => p.url.endsWith('/pos/venda/v-1/finalizar'))",
        "    .map((p) => p.corpo) }));",
    ]), tmp_path_factory, "pontos-separar-depois-do-qr")


def test_dividir_depois_da_pergunta_esquece_o_cliente_e_DIZ_que_o_esqueceu(dividir_depois_do_qr):
    """A mãe dividida nunca é faturada: a ligação lida nela não chega a fatura
    nenhuma. Deixá-la na gaveta era prometer pontos que ninguém receberia — e
    deixá-la SEM AVISO era o cliente a descobrir isso em casa."""
    r = dividir_depois_do_qr
    assert "Pontos para: Ana ✓" in r["comAna"], r["comAna"][:600]
    assert r["guardadaNaMae"] is None, (
        "A ligação da conta inteira ficou na gaveta depois de dividir.")
    assert "Pontos para" not in r["naPrimeiraParte"], r["naPrimeiraParte"][:600]
    assert r["corpos"] and r["corpos"][0]["pontos_ligacao"] is None, r["corpos"]
    assert any("leia outra vez o QR" in a for a in r["avisos"]), r["avisos"]


def test_separar_nao_deixa_o_cliente_ir_parar_a_fatura_de_OUTRA_pessoa(separar_depois_do_qr):
    """**O bloqueador.** A conta v-1 SOBREVIVE ao separar — passa a ser o resto.
    Com a ligação lá dentro, a fatura de quem pagava o resto saía com o nome de
    quem tinha mostrado a app noutra parte: a app credita UMA fatura por ligação,
    portanto quem mostrou o QR ficava sem os pontos da sua compra e a caixa tinha
    o nome errado à frente do cliente."""
    r = separar_depois_do_qr
    assert r["guardadaNaMae"] is None, (
        "A ligação continuou agarrada ao RESTO da conta: %s" % r["guardadaNaMae"])
    assert "Pontos para" not in r["naParte"], r["naParte"][:600]
    assert "Pontos para" not in r["noPagamentoDoResto"], (
        "O ecrã do cliente do resto mostra o cliente de outra pessoa: %s"
        % r["noPagamentoDoResto"][:600])
    assert r["corpoDoResto"] and r["corpoDoResto"][-1]["pontos_ligacao"] is None, (
        "A fatura do RESTO levou a ligação da parte anterior: %s" % r["corpoDoResto"])


def test_a_conta_que_perdeu_a_leitura_volta_a_ser_perguntada(separar_depois_do_qr):
    """Esquecer a ligação sem voltar a perguntar deixava o cliente do resto sem
    caminho nenhum para os pontos, com a câmara calada. Quem perde a leitura
    ganha a pergunta de volta."""
    assert "Quer atribuir os pontos?" in separar_depois_do_qr["noResto"], (
        separar_depois_do_qr["noResto"][:600])


# --- Uma pergunta por conta, e uma janela que se cala ao fechar ----------------


@pytest.fixture(scope="module")
def nao_repetido(tmp_path_factory):
    """O `_arranque` já respondeu «Não». Sai-se do pagamento (o cliente
    lembrou-se de mais uma coisa) e volta-se a carregar em FINALIZAR."""
    return _correr("\n".join([
        _no_finalizar(""),
        "const seta = [...alvo.querySelectorAll('button')].find(",
        "  (b) => b.querySelector('[data-icone=\"ArrowLeft\"]'));",
        "if (!seta) throw new Error('sem seta de voltar no Finalizar');",
        "await act(async () => { seta.click(); });",
        "await act(async () => {});",
        "await carregar_em('FINALIZAR');",
        "process.stdout.write(JSON.stringify({ segundaVez: textoVisivel(alvo) }));",
    ]), tmp_path_factory, "pontos-nao-repetido")


@pytest.fixture(scope="module")
def resposta_atrasada(tmp_path_factory):
    """A operadora lê o QR, a app não responde, ela desiste e carrega em «Não» —
    e a resposta chega depois, com a janela já desmontada."""
    return _correr("\n".join([
        _na_pergunta("\n".join([
            "let responder;",
            "RESPOSTAS_POS['POST /pos/pontos/ler'] = () => new Promise((ok) => {",
            "  responder = () => ok({ data: { ligacao_id: 'lig-1', primeiro_nome: 'Ana' } });",
            "});",
        ])),
        "await lerComOLeitor(alvo, %s);" % json.dumps(_CODIGO),
        "await carregar_em('Não');",
        "const noPagamento = textoVisivel(alvo);",
        # Agora a app responde, ao ecrã que já não é aquele.
        "await act(async () => { responder(); });",
        "await act(async () => {});",
        "await act(async () => {});",
        "process.stdout.write(JSON.stringify({ noPagamento,",
        "  depoisDaResposta: textoVisivel(alvo),",
        "  guardada: lib.lerPontosDaConta('v-1') }));",
    ]), tmp_path_factory, "pontos-resposta-atrasada")


def test_quem_responde_Nao_nao_leva_com_a_camara_outra_vez_na_MESMA_conta(nao_repetido):
    """A maioria das vendas é sem app. Perguntar outra vez por cada artigo que o
    cliente se lembra de juntar era acender a câmara à cara de quem já disse que
    não — e o «Não» não deixa rasto nenhum na gaveta dos pontos, por isso a
    guarda da leitura sozinha não o apanhava. Quem mudar de ideias tem o «Ler QR
    do cliente» no cartão do pagamento, que é onde essa intenção já vive."""
    assert "Quer atribuir os pontos?" not in nao_repetido["segundaVez"], (
        nao_repetido["segundaVez"][:600])
    assert "EMITIR DOCUMENTO" in nao_repetido["segundaVez"].upper(), (
        nao_repetido["segundaVez"][:600])


def test_a_janela_fechada_nao_liga_ninguem_com_a_resposta_atrasada(resposta_atrasada):
    """**Uma janela fechada não fala mais.** O desmontar não cancela o pedido:
    o `ler` continua vivo no closure e voltava a um ecrã que já era outro —
    apitava um «leu» sobre um ecrã sem leitura nenhuma, guardava na conta a
    ligação que a operadora tinha recusado, e mandava o ecrã para o pagamento
    outra vez, por cima de uma Fatura Simplificada já emitida."""
    r = resposta_atrasada
    assert "Quer atribuir os pontos?" not in r["noPagamento"], r["noPagamento"][:400]
    assert r["guardada"] is None, (
        "A resposta atrasada guardou na conta a ligação que a operadora recusou.")
    assert "Pontos para" not in r["depoisDaResposta"], r["depoisDaResposta"][:600]


def test_a_janela_nao_se_fecha_com_um_toque_fora_dela():
    """**Este é o único aqui que se prova a LER, e a razão é do banco de ensaio:**
    o `Dialog` do jsdom é um `<div>` fabricado (test_as_fotos_no_ecra::_COMPONENTES)
    e não tem cortina nem camada de dispensa — `onInteractOutside` não existe lá
    para ser exercido. A ler, portanto, e no browser com o dono.

    Porque importa: a cortina do Radix cobre o ecrã TODO, o botão FINALIZAR
    incluído. Numa caixa onde se carrega duas vezes por hábito, o segundo toque
    do duplo-clique aterrava na cortina e despachava a pergunta em silêncio — a
    operadora via o ecrã de pagamento e nunca saberia que lhe tinham perguntado
    alguma coisa."""
    from pathlib import Path
    ecra = (Path(__file__).resolve().parents[3] / "frontend" / "src" / "pages"
            / "pos" / "PosLerQr.js").read_text(encoding="utf-8")
    assert "onInteractOutside={(e) => e.preventDefault()}" in ecra, (
        "A janela do QR voltou a fechar-se com um toque fora dela.")


@pytest.fixture(scope="module")
def pergunta_pegajosa(tmp_path_factory):
    """A conta desaparece por baixo da janela aberta, e a seguir começa outro
    cliente. O 409 aqui é o gatilho mais curto para o estado que interessa —
    conta largada com a pergunta em pé —, o mesmo a que se chega no balcão
    quando a escrita que estava no ar volta recusada."""
    return _correr("\n".join([
        _na_pergunta("\n".join([
            "RESPOSTAS_POS['POST /pos/venda/v-1/linhas'] = () => {",
            "  const e = new Error('Request failed with status code 409');",
            "  e.response = { status: 409, data: { detail: 'Esta conta já não aceita alterações.' } };",
            "  throw e;",
            "};",
            "RESPOSTAS_POS['POST /pos/venda'] = () => ({ data: %s });"
            % json.dumps(_conta("v-2", []), ensure_ascii=False),
            "RESPOSTAS_POS['POST /pos/venda/v-2/linhas'] = () => ({ data: %s });"
            % json.dumps(_conta("v-2", [_L_COOKIE]), ensure_ascii=False),
        ])),
        "const naPergunta = textoVisivel(alvo);",
        # O cartão do produto na grelha (o da conta traz o «cada» do preço
        # unitário). No banco de ensaio o diálogo é um `<div>` e não tapa nada,
        # por isso o toque chega lá — e é o mesmo estado a que o balcão chega
        # pela escrita que já ia no ar quando ela carregou em FINALIZAR.
        "const cartao = (nome) => [...alvo.querySelectorAll('button')].find(",
        "  (b) => (b.textContent || '').includes(nome)",
        "    && !(b.textContent || '').includes('cada'));",
        # A releitura corre DENTRO do tratamento do 409, por isso a resposta
        # «já não há conta aberta» tem de estar posta antes do toque.
        "RESPOSTAS_POS['/pos/venda/aberta'] = () => ({ data: null });",
        "await act(async () => { cartao(%s).click(); });" % json.dumps(_COOKIE),
        "await act(async () => {});",
        "await act(async () => {});",
        "const semConta = textoVisivel(alvo);",
        # Cliente seguinte: o primeiro produto abre uma conta NOVA.
        "await act(async () => { cartao(%s).click(); });" % json.dumps(_COOKIE),
        "await act(async () => {});",
        "await act(async () => {});",
        "process.stdout.write(JSON.stringify({ naPergunta, semConta,",
        "  noClienteSeguinte: textoVisivel(alvo) }));",
    ]), tmp_path_factory, "pontos-pergunta-pegajosa")


def test_a_pergunta_nao_ressuscita_no_cliente_SEGUINTE(pergunta_pegajosa):
    """**A pergunta é de uma CONTA, não um interruptor do ecrã.** Guardada num
    booleano, ela sobrevivia à conta que a abriu: largada essa conta (o gestor
    resolveu-a, o turno fechou, a escrita voltou 409), a janela sumia do ecrã
    mas o booleano ficava — e o primeiro produto do cliente seguinte fazia a
    câmara acender-se sozinha, sem ninguém lhe ter tocado no FINALIZAR."""
    r = pergunta_pegajosa
    assert "Quer atribuir os pontos?" in r["naPergunta"], r["naPergunta"][:400]
    assert "Quer atribuir os pontos?" not in r["semConta"], r["semConta"][:400]
    assert "Quer atribuir os pontos?" not in r["noClienteSeguinte"], (
        "A pergunta ressuscitou na conta do cliente seguinte: %s"
        % r["noClienteSeguinte"][:600])
