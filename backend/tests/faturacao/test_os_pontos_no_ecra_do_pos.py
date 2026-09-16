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
