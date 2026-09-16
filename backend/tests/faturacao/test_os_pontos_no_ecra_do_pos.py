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
from .test_o_dividir_e_o_separar_no_ecra import _L_ACAI, _L_COOKIE, _arranque, _conta, _correr

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
