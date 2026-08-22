"""A faixa que diz em que modo o POS está a emitir — **executada**, não lida.

**Porque este ficheiro existe.** O dono aceitou a faixa com uma condição só:
«concordo totalmente que esta faixa. **é importante que ela funcione.**» Esta
frase é o requisito. A faixa previne dois enganos simétricos e os dois caros:

- em `tests` sem faixa, a operadora julga que está a vender a sério — o cliente
  leva um talão sem valor, **nada chega à Autoridade Tributária**, e a loja
  pensa que facturou o dia;
- em `normal` com faixa, ela julga que está a treinar e emite **Faturas
  Simplificadas REAIS** em nome da Fordaimon Foods.

Por isso a faixa não pode adivinhar, e por isso há **TRÊS** estados e não dois.
O terceiro — «não se sabe» — é o que decide se isto funciona: um ecrã que, ao
não conseguir perguntar, decide não mostrar nada cai exactamente no primeiro
engano, e cai em silêncio.

**Porque é que os guardas CORREM o código em vez de o lerem.** Já aconteceu
duas vezes neste módulo um guarda verificar que certos nomes apareciam num
ficheiro e ficar verde com a decisão desligada por trás deles. Aqui há três
níveis, e nenhum é textual:

1. a decisão dos três estados vive em `lib/pos.js` e corre-se em **Node**,
   extraída do ficheiro (nunca uma cópia escrita aqui — uma cópia ficava verde
   com o ecrã errado, que é a forma de falhar que isto existe para apanhar);
2. a **faixa em si** (`pages/pos/PosFaixaModo.js`) é montada em React e
   renderizada para HTML, e o que se afirma é o que sai no ecrã: em `tests`
   aparece, em `normal` não aparece **nada**, e sem resposta aparece um aviso
   PRÓPRIO, distinto do de `tests`. Os ecrãs do POS desenham-se sem servidor
   nenhum — dois defeitos foram a produção exactamente assim, e um deles teve
   o POS inteiramente morto com a suite verde.
3. e a **MONTAGEM** — o `PosApp` montado num DOM a sério, com o servidor
   fabricado, porque testar as duas peças não testa o fio entre elas: cravar
   o prop no ecrã de venda (`<PosFaixaModo estado={"normal"} />`) deixava os
   1440 testes verdes e a faixa desaparecia do balcão. Foi medido.

A extracção e o `node` deste Mac vêm do guarda irmão
(`test_arredondamento_do_ecra.py`), importados de lá e não copiados.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

from .test_arredondamento_do_ecra import (
    _LIB_POS,
    _corpo_da_funcao,
    _corpo_da_seta,
    _ler,
    _node,
)

_RAIZ = Path(__file__).resolve().parents[3]
_FRONTEND = _RAIZ / "frontend"
_FAIXA = _FRONTEND / "src" / "pages" / "pos" / "PosFaixaModo.js"
_MENU = _FRONTEND / "src" / "pages" / "pos" / "PosMenuCaixa.js"
_APP = _FRONTEND / "src" / "pages" / "pos" / "PosApp.js"
_FINALIZAR = _FRONTEND / "src" / "pages" / "pos" / "PosFinalizar.js"

_ASSINATURA_ESTADO = "export const estadoDoModo = (bruto) =>"
_ASSINATURA_LIDO = "export const estadoDoModoLido = async (pedir) =>"
_ASSINATURA_FAIXA = "export const faixaDoModo = (estado) =>"
_ASSINATURA_DOCUMENTO = "export const avisoDoDocumento = (documento) =>"
_ASSINATURA_BACKOFFICE = "export const avisoDoModoNoBackoffice = (estado) =>"
_ASSINATURAS_CONSTANTES = (
    "export const MODO_TESTES =",
    "export const MODO_NORMAL =",
    "export const MODO_DESCONHECIDO =",
)


def _decisao_solta() -> str:
    """As cinco funções da decisão, extraídas do `lib/pos.js` e prontas a
    correr como um guião solto (sem `export`, sem `import`).

    `estadoDoModoLido` chama quem lhe passarem — é um parâmetro, não um
    import —, e é isso que a torna executável aqui: o «servidor não respondeu»
    reproduz-se com uma função que rebenta, sem rede nenhuma."""
    lib = _ler(_LIB_POS)
    pedacos = [
        _corpo_da_seta(lib, assinatura, _LIB_POS) for assinatura in _ASSINATURAS_CONSTANTES
    ]
    pedacos += [
        _corpo_da_funcao(lib, assinatura, _LIB_POS)
        for assinatura in (
            _ASSINATURA_ESTADO,
            _ASSINATURA_LIDO,
            _ASSINATURA_FAIXA,
            _ASSINATURA_DOCUMENTO,
            _ASSINATURA_BACKOFFICE,
        )
    ]
    return "\n".join(p.replace("export ", "", 1) for p in pedacos)


def _correr_no_node(guiao: str, tmp_path: Path, nome: str):
    ficheiro = tmp_path / nome
    ficheiro.write_text(guiao, encoding="utf-8")
    resultado = subprocess.run(
        [_node(), str(ficheiro)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(_FRONTEND),
        env={"NODE_PATH": str(_FRONTEND / "node_modules"), "PATH": "/usr/bin:/bin"},
    )
    if resultado.returncode != 0:
        pytest.fail(
            "O JavaScript do ecrã não correu:\n%s"
            % resultado.stderr.decode("utf-8", "replace")
        )
    return json.loads(resultado.stdout.decode("utf-8"))


# --- Nível 1: a decisão dos três estados, corrida ------------------------------


def _decidir(entradas, tmp_path):
    """Corre `estadoDoModo` sobre cada valor cru — o que o servidor devolveu no
    campo `modo`."""
    return _correr_no_node(
        "\n".join([
            _decisao_solta(),
            "const entradas = %s;" % json.dumps(entradas),
            "process.stdout.write(JSON.stringify(entradas.map(estadoDoModo)));",
        ]),
        tmp_path,
        "decisao.js",
    )


def test_o_servidor_diz_tests_e_o_ecra_fica_em_tests(tmp_path):
    assert _decidir(["tests"], tmp_path) == ["tests"]


def test_o_servidor_diz_normal_e_o_ecra_fica_em_normal(tmp_path):
    assert _decidir(["normal"], tmp_path) == ["normal"]


@pytest.mark.parametrize(
    "valor",
    [None, "", "producao", "TESTS", "tests ", "Normal", 0, 1, True, [], {}, "null"],
)
def test_tudo_o_que_nao_se_percebe_cai_no_TERCEIRO_estado(tmp_path, valor):
    """Nem `tests` nem `normal`: qualquer outra coisa é «não se sabe».

    Repare-se em `"TESTS"` e `"tests "` — o servidor recusa-se a emitir com
    esses valores (`vendus/emissao.py::_MODOS_VALIDOS` compara-os tal e qual),
    e o ecrã tem de os ler da mesma maneira. Um `toLowerCase()` ou um `trim()`
    de cortesia aqui fazia o ecrã dizer «modo de testes» sobre uma emissão que
    nem sequer acontece."""
    assert _decidir([valor], tmp_path) == ["desconhecido"]


def _ler_com(pedir_js, tmp_path):
    """Corre `estadoDoModoLido` com um `pedir` fabricado — é assim que se
    reproduz um servidor que não responde, sem rede nenhuma."""
    return _correr_no_node(
        "\n".join([
            _decisao_solta(),
            "const pedir = %s;" % pedir_js,
            "estadoDoModoLido(pedir)",
            "  .then((estado) => process.stdout.write(JSON.stringify(estado)))",
            "  .catch((e) => { console.error(e); process.exit(3); });",
        ]),
        tmp_path,
        "leitura.js",
    )


@pytest.mark.parametrize(
    "pedir_js,esperado",
    [
        ("async () => ({ data: { modo: 'tests' } })", "tests"),
        ("async () => ({ data: { modo: 'normal' } })", "normal"),
        # A ROTA FALHOU — as várias maneiras de ela falhar.
        ("async () => { throw new Error('Network Error'); }", "desconhecido"),
        ("async () => { const e = new Error('timeout'); e.code = 'ECONNABORTED'; throw e; }",
         "desconhecido"),
        ("async () => { const e = new Error('404'); e.response = { status: 404 }; throw e; }",
         "desconhecido"),
        ("async () => { const e = new Error('401'); e.response = { status: 401 }; throw e; }",
         "desconhecido"),
        # RESPOSTA ESTRANHA — 200, mas o corpo não é o que se esperava. É o
        # caso do proxy que devolve a página de manutenção em HTML, ou de uma
        # versão do servidor anterior a esta rota.
        ("async () => ({ data: null })", "desconhecido"),
        ("async () => ({ data: {} })", "desconhecido"),
        ("async () => ({ data: '<html>manutencao</html>' })", "desconhecido"),
        ("async () => ({ data: { modo: null } })", "desconhecido"),
        ("async () => ({})", "desconhecido"),
        ("async () => undefined", "desconhecido"),
    ],
)
def test_o_que_o_ecra_conclui_de_cada_resposta(tmp_path, pedir_js, esperado):
    assert _ler_com(pedir_js, tmp_path) == esperado


def test_a_leitura_nunca_rebenta_para_fora(tmp_path):
    """Uma promessa rejeitada que escapasse daqui apanhava o `useEffect` do
    ecrã sem `catch` e deixava a faixa por montar — o estado por omissão do
    React é «nada no ecrã», que é o primeiro engano outra vez."""
    assert _ler_com("() => { throw new Error('sincrono'); }", tmp_path) == "desconhecido"


# --- Nível 1b: o que a faixa DIZ em cada estado -------------------------------


def _faixas(tmp_path):
    return _correr_no_node(
        "\n".join([
            _decisao_solta(),
            "const estados = ['tests', 'normal', 'desconhecido'];",
            "process.stdout.write(JSON.stringify(",
            "  Object.fromEntries(estados.map((e) => [e, faixaDoModo(e)])),",
            "));",
        ]),
        tmp_path,
        "faixas.js",
    )


def test_em_normal_nao_ha_faixa_nenhuma(tmp_path):
    """`normal` é o estado normal de trabalho: silêncio. Uma faixa permanente
    treinava a operadora a ignorá-la, e nesse dia ela ignorava a de `tests`."""
    assert _faixas(tmp_path)["normal"] is None


def test_em_tests_ha_faixa_e_ela_diz_o_que_isso_significa(tmp_path):
    faixa = _faixas(tmp_path)["tests"]
    assert faixa is not None
    assert faixa["titulo"] == "MODO DE TESTES — estas faturas não valem nada"
    assert faixa["texto"] == (
        "Nada do que emitir aqui chega à Autoridade Tributária. Serve para "
        "treinar; não serve para vender."
    )


def test_no_terceiro_estado_ha_um_aviso_PROPRIO_e_diferente(tmp_path):
    """Distinto do de `tests`, e não uma variação dele: são coisas diferentes.
    Em `tests` sabe-se que não vale; aqui não se sabe nada, e o que se pede à
    operadora também é diferente — parar."""
    faixas = _faixas(tmp_path)
    aviso = faixas["desconhecido"]
    assert aviso is not None
    assert aviso["titulo"] == "NÃO SABEMOS SE ESTAS FATURAS SÃO REAIS"
    assert aviso["texto"] == (
        "O servidor não disse em que modo está a emitir. Não venda até isto "
        "estar resolvido — chame o gestor."
    )
    assert aviso["titulo"] != faixas["tests"]["titulo"]
    assert aviso["texto"] != faixas["tests"]["texto"]
    assert aviso["tom"] != faixas["tests"]["tom"]


def test_um_estado_inventado_nao_apaga_a_faixa(tmp_path):
    """Se alguém passar à faixa um estado que não é nenhum dos três, o que sai
    é o aviso do terceiro estado — nunca `null`. É a mesma regra de sempre: na
    dúvida não se escolhe um dos dois lados conhecidos."""
    resultado = _correr_no_node(
        "\n".join([
            _decisao_solta(),
            "const entradas = [undefined, null, '', 'TESTS', 'a-sério', 42];",
            "process.stdout.write(JSON.stringify(entradas.map(",
            "  (e) => (faixaDoModo(e) || {}).titulo || null,",
            ")));",
        ]),
        tmp_path,
        "faixa-invalida.js",
    )
    assert resultado == ["NÃO SABEMOS SE ESTAS FATURAS SÃO REAIS"] * 6


# --- Nível 1c: o CARIMBO daquela fatura em concreto ---------------------------
#
# O documento vem carimbado com o modo (`fiscal.py`, campo `modo`), e é esse o
# modo daquela fatura — não o do instante em que a página foi carregada. Um
# turno que começou em `tests` e a que o gestor mudou o servidor a meio tem
# documentos dos dois tipos, e o ecrã da confirmação tem de dizer a verdade de
# CADA um.


def _avisos_de_documento(documentos, tmp_path):
    return _correr_no_node(
        "\n".join([
            _decisao_solta(),
            "const docs = %s;" % json.dumps(documentos),
            "process.stdout.write(JSON.stringify(docs.map(avisoDoDocumento)));",
        ]),
        tmp_path,
        "documento.js",
    )


def test_o_documento_normal_nao_leva_aviso_nenhum(tmp_path):
    assert _avisos_de_documento([{"numero": "FS 1/1", "modo": "normal"}], tmp_path) == [None]


def test_o_documento_de_testes_diz_que_nao_vale(tmp_path):
    (aviso,) = _avisos_de_documento([{"numero": "FS 1/1", "modo": "tests"}], tmp_path)
    assert aviso["titulo"] == "Documento SEM VALOR FISCAL"


@pytest.mark.parametrize(
    "documento",
    [
        {"numero": "FS 1/1"},          # sem o campo (um servidor mais velho)
        {"numero": "FS 1/1", "modo": None},
        {"numero": "FS 1/1", "modo": "producao"},
        {},
        None,
    ],
)
def test_o_documento_sem_carimbo_legivel_cai_no_terceiro_estado(tmp_path, documento):
    """**Este é o caso que faltava.** O ecrã da confirmação já avisava do modo
    `tests`, mas um documento SEM o campo `modo` — ou com um valor que não se
    percebe — não mostrava nada, e «nada» lê-se como «é real». Um documento que
    não diz o que é obriga quem o lê a adivinhar, e a adivinha, aqui, decide se
    o cliente leva ou não uma fatura."""
    (aviso,) = _avisos_de_documento([documento], tmp_path)
    assert aviso is not None
    assert aviso["titulo"] == "NÃO SABEMOS SE ESTA FATURA É REAL"


# --- Nível 2: a faixa montada em React, tal como sai no ecrã ------------------
#
# Os ecrãs do POS desenham-se sem servidor nenhum. Correr a decisão prova que a
# decisão está certa; não prova que o ecrã a OBEDECE. Estes três montam o
# componente real e olham para o HTML que sai dele.


def _renderizar(estados, tmp_path):
    """`estados` são EXPRESSÕES JavaScript, não valores JSON — `undefined` é
    um dos estados que interessam (é o que lá está no primeiro render, antes de
    a resposta chegar) e o JSON não o sabe transportar. A expressão serve
    também de chave do resultado."""
    if not (_FRONTEND / "node_modules" / "react-dom").exists():
        pytest.skip("Sem node_modules no frontend para montar o componente.")
    guiao = "\n".join([
        "const fs = require('fs');",
        "const path = require('path');",
        "const Module = require('module');",
        "const babel = require('@babel/core');",
        "const React = require('react');",
        "const { renderToStaticMarkup } = require('react-dom/server');",
        "const RAIZ = %s;" % json.dumps(str(_FRONTEND / "src")),
        # Os ícones do lucide-react não interessam ao que se está a medir e
        # arrastavam o pacote inteiro para dentro do guião: entram como um
        # <i> qualquer, por nome.
        "const icones = new Proxy({}, { get: (_, nome) => (",
        "  typeof nome === 'string' && nome !== '__esModule'",
        "    ? () => React.createElement('i', { 'data-icone': String(nome) })",
        "    : undefined",
        ") });",
        "const cache = new Map();",
        "function carregar(ficheiro) {",
        "  if (cache.has(ficheiro)) return cache.get(ficheiro).exports;",
        "  const codigo = babel.transformSync(fs.readFileSync(ficheiro, 'utf-8'), {",
        "    presets: [[require.resolve('@babel/preset-react'), { runtime: 'classic' }]],",
        "    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],",
        "    filename: ficheiro, babelrc: false, configFile: false,",
        "  }).code;",
        "  const m = new Module(ficheiro, null);",
        "  m.filename = ficheiro;",
        "  m.paths = Module._nodeModulePaths(path.dirname(ficheiro));",
        "  cache.set(ficheiro, m);",
        "  const originalRequire = m.require.bind(m);",
        # O `@/` do jsconfig, resolvido à mão: é o mesmo alias que o build usa.
        "  m.require = (pedido) => {",
        "    if (pedido === 'lucide-react') return icones;",
        "    if (pedido.startsWith('@/')) return carregar(path.join(RAIZ, pedido.slice(2)) + '.js');",
        "    return originalRequire(pedido);",
        "  };",
        "  m._compile(codigo, ficheiro);",
        "  return m.exports;",
        "}",
        "const Faixa = carregar(%s).default;" % json.dumps(str(_FAIXA)),
        "const estados = [%s];" % ", ".join("[%s, %s]" % (json.dumps(e), e) for e in estados),
        "process.stdout.write(JSON.stringify(Object.fromEntries(estados.map(",
        "  ([nome, e]) => [nome, renderToStaticMarkup(React.createElement(Faixa, { estado: e }))],",
        "))));",
    ])
    return _correr_no_node(guiao, tmp_path, "render.js")


def test_no_ecra_o_modo_tests_ACENDE_a_faixa(tmp_path):
    html = _renderizar(["'tests'"], tmp_path)["'tests'"]
    assert "MODO DE TESTES" in html
    assert "Autoridade Tributária" in html


def test_no_ecra_o_modo_normal_NAO_desenha_absolutamente_nada(tmp_path):
    """String vazia, e não «uma faixa discreta»: em `normal` a faixa não ocupa
    um pixel. O dono já se queixou de o ecrã do POS ser grande de mais e pediu
    uma área de trabalho mais contida — o estado normal de trabalho não pode
    pagar espaço a um aviso que não tem nada para avisar."""
    assert _renderizar(["'normal'"], tmp_path)["'normal'"] == ""


def test_no_ecra_o_terceiro_estado_desenha_o_SEU_aviso(tmp_path):
    """Não é o de `tests`, e não é o silêncio de `normal`."""
    html = _renderizar(["'desconhecido'", "'tests'"], tmp_path)
    aviso = html["'desconhecido'"]
    assert aviso != ""
    assert "NÃO SABEMOS SE ESTAS FATURAS SÃO REAIS" in aviso
    assert "MODO DE TESTES" not in aviso
    assert aviso != html["'tests'"]


def test_no_ecra_um_estado_por_apurar_nunca_fica_em_branco(tmp_path):
    """`undefined` é o que lá está no primeiro render, antes de a resposta
    chegar — e é também o que lá fica para sempre se o pedido nunca voltar.
    Nesse instante o ecrã não sabe, e tem de o dizer."""
    html = _renderizar(["undefined"], tmp_path)["undefined"]
    assert "NÃO SABEMOS SE ESTAS FATURAS SÃO REAIS" in html


# --- Nível 3: o POS INTEIRO montado, com o servidor fabricado ------------------
#
# **O buraco que este nível veio tapar, medido.** Os guardas de cima testam as
# PEÇAS — a decisão (`lib/pos.js`) e a faixa (`PosFaixaModo`), cada uma
# sozinha — e nenhum testava a MONTAGEM. Cravar o prop no ecrã de venda
# (`<PosFaixaModo estado={"normal"} />` no `PosMenuCaixa`) deixava a suite
# INTEIRA verde e fazia a faixa desaparecer do balcão: cinco lojas a vender um
# dia inteiro em modo de testes, sem nada chegar à Autoridade Tributária, com
# tudo verde a dizer que estava bem. A única coisa que cobria a ligação era um
# guarda de texto (`"<PosFaixaModo" in texto`), e é a quarta vez neste módulo
# que um guarda de texto fica verde com a decisão desligada por trás dele.
#
# **O que se faz aqui.** Monta-se o `PosApp` A SÉRIO — o componente de topo, o
# mesmo que o browser monta — num DOM (jsdom), com o servidor fabricado à
# frente do axios do `lib/pos`: nenhuma rede, e o caminho todo é o verdadeiro
# (o `useEffect` do arranque, o `lerEstadoDoModo`, a leitura do `modo`, o prop
# a descer, a faixa a desenhar-se). O que se afirma é o HTML que fica no ecrã.
#
# É por isso um DOM e não o `renderToStaticMarkup` do nível 2: o
# `renderToStaticMarkup` não corre `useEffect` nenhum, e era precisamente o
# arranque — a pergunta ao servidor e a resposta a chegar à barra — que ficava
# por guardar. Apagar o `ler();` do `useEffect` do `PosApp` deixava, também
# ele, a suite inteira verde.
#
# As duas barras da sessão de trabalho saem das duas ramificações reais do
# `PosApp`: com sessão aberta é o `PosMenuCaixa` (o ecrã de venda), sem sessão
# é o `TopoSimples` (a caixa fechada). Não se importa nenhum dos dois à mão —
# quem os escolhe é o próprio `PosApp`, que é o que está a ser medido.
#
# O que entra SUBSTITUÍDO são só os ecrãs que não estão a ser medidos
# (`PosVenda`, `PosEntrar`, `PosBloqueado`, …), os componentes de UI e os
# ícones. A faixa, as duas barras, o `PosApp` e o `lib/pos` inteiro entram
# REAIS — se algum deles entrasse substituído, este guarda media um ecrã que
# não existe.

_BACKOFFICE = _FRONTEND / "src" / "pages" / "admin" / "faturacao" / "FatModoDeEmissao.js"
_DASHBOARD = _FRONTEND / "src" / "pages" / "admin" / "faturacao" / "FatDashboard.js"

# Os ecrãs que entram como marcas vazias: nenhum deles tem nada a ver com o
# modo de emissão, e alguns (o `PosVenda`) arrastariam meia aplicação e uma
# dúzia de chamadas ao servidor para dentro deste guarda.
_ECRAS_SUBSTITUIDOS = (
    "PosEmparelhar", "PosEntrar", "PosBloqueado", "PosCaixaFechada",
    "PosFecharCaixa", "PosVenda", "PosCampoValor", "PosResumoDoTurno",
)


def _preambulo_de_montagem() -> str:
    """O carregador que monta ecrãs REAIS do repositório em Node, com DOM e com
    o servidor fabricado. Devolve JavaScript; quem o usa acrescenta-lhe o
    cenário."""
    return "\n".join([
        "const fs = require('fs');",
        "const path = require('path');",
        "const Module = require('module');",
        "const babel = require('@babel/core');",
        "const { JSDOM } = require('jsdom');",
        "const dom = new JSDOM('<!doctype html><html><body><div id=\"raiz\"></div></body></html>',",
        "  { url: 'http://localhost/' });",
        "global.window = dom.window;",
        "global.document = dom.window.document;",
        "global.navigator = dom.window.navigator;",
        "global.localStorage = dom.window.localStorage;",
        "global.IS_REACT_ACT_ENVIRONMENT = true;",
        "const React = require('react');",
        "const { act } = require('react');",
        "const { createRoot } = require('react-dom/client');",
        "const RAIZ = %s;" % json.dumps(str(_FRONTEND / "src")),
        "const POS = %s;" % json.dumps(str(_FRONTEND / "src" / "pages" / "pos")),
        # --- o servidor fabricado, à frente do axios -------------------------
        # Duas famílias, como no código: a instância criada com `axios.create()`
        # é a do POS (cabeçalhos de dispositivo/operador) e o `axios` global é o
        # do backoffice (o JWT de gestão, posto pelo AuthContext). Ficam
        # separadas aqui de propósito — é assim que se vê por qual delas cada
        # ecrã perguntou.
        "const RESPOSTAS_POS = {};",
        "const RESPOSTAS_GESTAO = {};",
        "const pedidos = [];",
        "function responder(tabela, url) {",
        "  const chave = Object.keys(tabela).find((c) => String(url).endsWith(c));",
        "  if (!chave) {",
        "    const e = new Error('pedido nao fabricado: ' + url);",
        "    e.response = { status: 404 };",
        "    throw e;",
        "  }",
        "  return tabela[chave]();",
        "}",
        "const instanciaPos = {",
        "  interceptors: { request: { use: () => {} }, response: { use: () => {} } },",
        "  get: async (url) => { pedidos.push('pos:' + url); return responder(RESPOSTAS_POS, url); },",
        "  post: async (url) => { pedidos.push('pos:' + url); return responder(RESPOSTAS_POS, url); },",
        "};",
        "const axiosFalso = {",
        "  create: () => instanciaPos,",
        "  defaults: { headers: { common: { Authorization: 'Bearer JWT-DE-GESTAO' } } },",
        "  get: async (url) => { pedidos.push('gestao:' + url); return responder(RESPOSTAS_GESTAO, url); },",
        "  post: async (url) => { pedidos.push('gestao:' + url); return responder(RESPOSTAS_GESTAO, url); },",
        "};",
        # --- o que entra substituído -----------------------------------------
        "const icones = new Proxy({}, { get: (_, nome) => (",
        "  typeof nome === 'string' && nome !== '__esModule'",
        "    ? () => React.createElement('i', { 'data-icone': String(nome) })",
        "    : undefined",
        ") });",
        "const marca = (nome) => {",
        "  const C = (props) => React.createElement('div', { 'data-substituto': nome },",
        "    props && props.children);",
        "  C.displayName = nome;",
        "  return C;",
        "};",
        "const marcas = new Proxy({}, { get: (_, nome) => (",
        "  typeof nome === 'string' && nome !== '__esModule' ? marca(String(nome)) : undefined",
        ") });",
        "const sonner = { toast: Object.assign(() => {},",
        "  { success: () => {}, error: () => {}, info: () => {}, warning: () => {} }) };",
        "const SUBSTITUIDOS = new Set(%s.map((n) => path.join(POS, n + '.js')));"
        % json.dumps(list(_ECRAS_SUBSTITUIDOS)),
        # --- o carregador -----------------------------------------------------
        "const cache = new Map();",
        "function carregar(ficheiro) {",
        "  if (cache.has(ficheiro)) return cache.get(ficheiro).exports;",
        "  if (SUBSTITUIDOS.has(ficheiro)) {",
        "    return { __esModule: true, default: marca(path.basename(ficheiro, '.js')) };",
        "  }",
        "  const codigo = babel.transformSync(fs.readFileSync(ficheiro, 'utf-8'), {",
        "    presets: [[require.resolve('@babel/preset-react'), { runtime: 'classic' }]],",
        "    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],",
        "    filename: ficheiro, babelrc: false, configFile: false,",
        "  }).code;",
        "  const m = new Module(ficheiro, null);",
        "  m.filename = ficheiro;",
        "  m.paths = Module._nodeModulePaths(path.dirname(ficheiro));",
        "  cache.set(ficheiro, m);",
        "  const originalRequire = m.require.bind(m);",
        "  m.require = (pedido) => {",
        "    if (pedido === 'lucide-react') return icones;",
        "    if (pedido === 'sonner') return sonner;",
        "    if (pedido === 'axios') return { __esModule: true, default: axiosFalso };",
        "    if (pedido.startsWith('@/components/')) return marcas;",
        "    if (pedido.startsWith('@/')) return carregar(path.join(RAIZ, pedido.slice(2)) + '.js');",
        "    if (pedido.startsWith('.')) {",
        "      return carregar(path.resolve(path.dirname(ficheiro), pedido) + '.js');",
        "    }",
        "    return originalRequire(pedido);",
        "  };",
        "  m._compile(codigo, ficheiro);",
        "  return m.exports;",
        "}",
        # --- montar, e esperar que as respostas cheguem ao ecrã ---------------
        # O segundo `act` vazio é o que deixa passar as promessas do arranque:
        # sem ele media-se o primeiro render, antes de o servidor ter respondido
        # — e o ecrã do primeiro render está certo por outra razão (o terceiro
        # estado), o que dava um guarda verde por engano.
        "async function montar(elemento) {",
        "  const alvo = document.getElementById('raiz');",
        "  const raiz = createRoot(alvo);",
        "  await act(async () => { raiz.render(elemento); });",
        "  await act(async () => {});",
        "  const html = alvo.innerHTML;",
        "  await act(async () => { raiz.unmount(); });",
        "  alvo.innerHTML = '';",
        "  return html;",
        "}",
    ])


def _montar_no_node(cenario: str, tmp_path: Path, nome: str):
    for modulo in ("react-dom", "jsdom", "@babel/core"):
        if not (_FRONTEND / "node_modules" / modulo).exists():
            pytest.skip("Sem %s no frontend para montar os ecrãs." % modulo)
    return _correr_no_node(
        "\n".join([_preambulo_de_montagem(), cenario]), tmp_path, nome
    )


# As quatro respostas possíveis do servidor à pergunta do modo — as duas que se
# percebem, e as duas maneiras de não se perceber (um 200 sem modo, e a rota a
# falhar). As duas últimas TÊM de dar o mesmo ecrã.
_RESPOSTAS_DO_MODO = "\n".join([
    "const RESPOSTAS_DO_MODO = [",
    "  ['tests', () => ({ data: { modo: 'tests' } })],",
    "  ['normal', () => ({ data: { modo: 'normal' } })],",
    "  ['sem-modo', () => ({ data: { modo: null } })],",
    "  ['sem-rota', () => { throw new Error('Network Error'); }],",
    "];",
])

_FAIXA_TESTES = "MODO DE TESTES — estas faturas não valem nada"
_FAIXA_DESCONHECIDO = "NÃO SABEMOS SE ESTAS FATURAS SÃO REAIS"
_LOJA_DO_GUARDA = "Loja do Guarda"


@pytest.fixture(scope="module")
def barras_do_pos(tmp_path_factory):
    """O `PosApp` montado a sério, uma vez por cada cruzamento de (barra) com
    (resposta do servidor) — devolve o HTML que ficou no ecrã.

    `aberta` é o ecrã de venda (barra `PosMenuCaixa`); `fechada` é a caixa por
    abrir (barra `TopoSimples`). Quem escolhe entre as duas é o `PosApp`, a
    partir do que o servidor disse da sessão."""
    cenario = "\n".join([
        "const lib = carregar(path.join(RAIZ, 'lib', 'pos.js'));",
        # Emparelhado e com operadora dentro: é o estado em que o balcão passa
        # o dia, e o único em que há barra — sem dispositivo ou sem operadora o
        # `PosApp` mostra o emparelhamento ou o teclado do PIN, e não há topo.
        "lib.guardarDispositivo({ device_token: 'dt', loja_id: 'l1', loja_nome: %s });"
        % json.dumps(_LOJA_DO_GUARDA),
        "lib.guardarOperador('ot', { id: 'o1', nome: 'Ana' });",
        "const PosApp = carregar(path.join(POS, 'PosApp.js')).default;",
        "const CAIXA = { id: 'c1', nome: 'Caixa 1' };",
        "const SESSAO = { aberta_por: { nome: 'Ana' }, aberta_em: '2026-08-20T09:00:00', fundo: 50 };",
        _RESPOSTAS_DO_MODO,
        "(async () => {",
        "  const saida = {};",
        "  for (const [barra, sessao] of [['aberta', SESSAO], ['fechada', null]]) {",
        "    RESPOSTAS_POS['/pos/caixa/estado'] = () => ({ data: {",
        "      caixas: [CAIXA], caixa: CAIXA, sessao_aberta: sessao, ultimo_fecho: null,",
        "    } });",
        "    for (const [nome, resposta] of RESPOSTAS_DO_MODO) {",
        "      RESPOSTAS_POS['/pos/modo-de-emissao'] = resposta;",
        "      saida[barra + '/' + nome] = await montar(React.createElement(PosApp));",
        "    }",
        "  }",
        "  saida.pedidos = pedidos;",
        "  process.stdout.write(JSON.stringify(saida));",
        "})().catch((e) => { console.error(e); process.exit(3); });",
    ])
    return _montar_no_node(cenario, tmp_path_factory.mktemp("pos"), "montar-pos.js")


@pytest.mark.parametrize("barra", ["aberta", "fechada"])
def test_a_barra_do_POS_montada_ACENDE_quando_o_servidor_diz_tests(barras_do_pos, barra):
    """O ecrã inteiro, montado, com o servidor a responder `tests`.

    É este o guarda que o prop cravado (`estado={"normal"}` escrito à mão no
    `PosMenuCaixa`) não sobrevive — e era exactamente essa a mutação que
    deixava os 1440 testes verdes com a faixa desaparecida do balcão."""
    html = barras_do_pos[barra + "/tests"]
    assert _LOJA_DO_GUARDA in html, "Não é a barra do POS que está aqui montada."
    assert _FAIXA_TESTES in html
    assert "Autoridade Tributária" in html


@pytest.mark.parametrize("barra", ["aberta", "fechada"])
def test_a_barra_do_POS_montada_fica_MUDA_quando_o_servidor_diz_normal(barras_do_pos, barra):
    """E muda de verdade: a barra continua lá inteira, sem faixa nenhuma."""
    html = barras_do_pos[barra + "/normal"]
    assert _LOJA_DO_GUARDA in html, "Não é a barra do POS que está aqui montada."
    assert _FAIXA_TESTES not in html
    assert _FAIXA_DESCONHECIDO not in html
    assert 'role="alert"' not in html


@pytest.mark.parametrize("barra", ["aberta", "fechada"])
@pytest.mark.parametrize("resposta", ["sem-modo", "sem-rota"])
def test_a_barra_do_POS_montada_avisa_quando_nao_se_sabe(barras_do_pos, barra, resposta):
    """Um 200 sem modo e a rota em baixo dão o MESMO ecrã: o aviso do terceiro
    estado. Nunca o silêncio de `normal`, que é o engano caro."""
    html = barras_do_pos[barra + "/" + resposta]
    assert _LOJA_DO_GUARDA in html, "Não é a barra do POS que está aqui montada."
    assert _FAIXA_DESCONHECIDO in html
    assert _FAIXA_TESTES not in html


@pytest.mark.parametrize("barra", ["aberta", "fechada"])
def test_o_HTML_das_duas_barras_MUDA_com_o_que_o_servidor_responde(barras_do_pos, barra):
    """Três respostas, três ecrãs diferentes — a afirmação directa contra o
    prop cravado. Um `estado` escrito à mão dá três HTML iguais, e cai aqui
    mesmo que alguém invente um quarto estado com o texto certo."""
    html = [barras_do_pos["%s/%s" % (barra, r)] for r in ("tests", "normal", "sem-modo")]
    assert len(set(html)) == 3


def test_no_arranque_o_POS_PERGUNTA_ao_servidor_em_que_modo_esta(barras_do_pos):
    """A pergunta é feita, e é feita pela rota do POS — com o axios do POS, que
    é o que leva o token do dispositivo.

    Apagar o `ler();` do `useEffect` do `PosApp` (deixando lá o `const ler` e o
    `setInterval`) deixava a suite inteira verde: ninguém guardava o ARRANQUE,
    só a função que ele chama. Sem a pergunta, a barra fica presa no terceiro
    estado durante os primeiros 60 segundos de cada turno."""
    perguntas = [p for p in barras_do_pos["pedidos"] if p.endswith("/pos/modo-de-emissao")]
    assert perguntas, "O POS montou-se sem perguntar ao servidor em que modo está a emitir."
    assert all(p.startswith("pos:") for p in perguntas)
    # Uma por montagem: as oito do cruzamento (duas barras x quatro respostas).
    assert len(perguntas) == 8, (
        "O arranque perguntou %d vezes em vez de uma por montagem. Se passou a "
        "haver outra leitura legítima, este número acompanha-a — mas confirme "
        "primeiro que não é o ecrã a remontar-se em ciclo." % len(perguntas)
    )

# --- Onde a faixa aparece -----------------------------------------------------


def test_a_faixa_esta_montada_nas_duas_barras_do_pos():
    """A barra de cima do POS é a mesma em toda a sessão de trabalho — com a
    caixa aberta (`PosMenuCaixa`) e com ela fechada (`TopoSimples`, dentro do
    `PosApp`). A faixa vive lá dentro, e não numa linha por cima: assim não
    tira um pixel à área de trabalho.

    Este guarda é textual e sabe-se pouco valioso — sobrevive a um prop
    cravado, que é a mutação que interessa. Quem a apanha são os do nível 3,
    que montam as duas barras a sério; este fica por ser o que falha primeiro
    e com a frase certa quando alguém apaga a linha."""
    for ficheiro in (_MENU, _APP):
        texto = _ler(ficheiro)
        assert "<PosFaixaModo" in texto, (
            "A faixa deixou de estar montada em %s." % ficheiro.name
        )


# --- O que o PosApp faz com o modo, corrido ----------------------------------
#
# Estes três nasceram da prova por mutação: as versões anteriores eram guardas
# de TEXTO ("o nome `lerEstadoDoModo` aparece no ficheiro") e sobreviveram
# intactas a três mutações que partiam a faixa a sério — começar em 'normal',
# deixar de ler o modo, e o ecrã da confirmação voltar a decidir sozinho pelo
# campo cru. É a terceira vez neste módulo que um guarda de texto fica verde
# com a decisão desligada por trás dele.


_RE_ESTADO_INICIAL = re.compile(r"const \[modo, setModo\] = useState\((.*?)\);")
_ASSINATURA_LER = "const ler = ("
_ASSINATURA_AVISO_NO_ECRA = "const avisoDoModo ="


def _ate_ao_ponto_e_virgula(texto: str, assinatura: str, ficheiro: Path) -> str:
    """Uma declaração completa, do início da assinatura até ao `;` que a fecha
    — contando as chavetas e os parênteses pelo caminho.

    O `_corpo_da_seta` do guarda irmão pára no PRIMEIRO `;`, e isso chega para
    uma arrow de uma expressão só; aqui não chega, porque as duas declarações
    que se extraem (`const ler = ...` no PosApp e `const avisoDoModo = ...` no
    PosFinalizar) podem levar um `;` DENTRO de um bloco. Truncar no primeiro
    dava um guião com um parêntese por fechar, e o teste falhava com
    SyntaxError em vez de medir o que veio buscar."""
    if assinatura not in texto:
        pytest.fail(
            "Não encontrei `%s` em %s. Se mudou de nome ou de sítio, a decisão "
            "que ela toma continua a ter de ser guardada." % (assinatura, ficheiro.name)
        )
    inicio = texto.index(assinatura)
    profundidade = 0
    for fim in range(inicio, len(texto)):
        c = texto[fim]
        if c in "{([":
            profundidade += 1
        elif c in "})]":
            profundidade -= 1
        elif c == ";" and profundidade == 0:
            return texto[inicio:fim + 1]
    pytest.fail("A declaração `%s` em %s não fecha." % (assinatura, ficheiro.name))


def _expressao(texto, expressao_re, ficheiro, o_que):
    achado = expressao_re.search(texto)
    if not achado:
        pytest.fail(
            "Não encontrei %s em %s. Se mudou de forma, este guarda tem de ir "
            "atrás dela — não se apaga." % (o_que, ficheiro.name)
        )
    return achado.group(1)


def test_antes_de_o_servidor_responder_o_ecra_NAO_SABE(tmp_path):
    """**O valor inicial do estado do React é uma resposta que ninguém deu.**

    Não se lê o nome dele: tira-se a EXPRESSÃO que está lá escrita e passa-se
    pela decisão a sério. `useState(undefined)` dá o aviso do terceiro estado;
    `useState('normal')` dá `null` — o ecrã calado por cima de um servidor que
    ainda não disse nada, que é o primeiro engano no seu instante mais
    provável, o arranque do turno."""
    inicial = _expressao(_ler(_APP), _RE_ESTADO_INICIAL, _APP, "o estado inicial do modo")
    resultado = _correr_no_node(
        "\n".join([
            _decisao_solta(),
            "const faixa = faixaDoModo(%s);" % inicial,
            "process.stdout.write(JSON.stringify(faixa && faixa.estado));",
        ]),
        tmp_path,
        "inicial.js",
    )
    assert resultado == "desconhecido", (
        "O `PosApp` arranca com o modo em %s, e a faixa lê isso como %r em vez "
        "do terceiro estado." % (inicial, resultado)
    )


def test_o_PosApp_LE_mesmo_o_modo_e_guarda_o_que_leu(tmp_path):
    """A função de leitura do `PosApp`, extraída e CORRIDA com um
    `lerEstadoDoModo` fabricado: o que ela leu tem de chegar ao estado.

    Uma versão que não chame nada (ou que chame e deite fora o resultado)
    deixa a faixa presa no valor inicial para sempre — e o ecrã passa o dia a
    gritar «não sabemos» sobre um servidor que responde à primeira."""
    corpo = _ate_ao_ponto_e_virgula(_ler(_APP), _ASSINATURA_LER, _APP)
    resultado = _correr_no_node(
        "\n".join([
            "let guardado = 'NUNCA-CHAMADO';",
            "const vivo = true;",
            "const setModo = (v) => { guardado = v; };",
            "const lerEstadoDoModo = async () => 'tests';",
            corpo,
            "Promise.resolve(ler()).then(() => "
            "  process.stdout.write(JSON.stringify(guardado)));",
        ]),
        tmp_path,
        "leitura-do-app.js",
    )
    assert resultado == "tests"


def test_o_ecra_da_confirmacao_usa_o_CARIMBO_do_documento(tmp_path):
    """E não o modo do momento em que a página foi carregada.

    A linha que o `PosFinalizar` escreve é extraída e corrida sobre os três
    documentos: a que decidir por sua conta (`documento.modo === 'tests'`, que
    foi o que lá esteve) deixa o documento sem carimbo a passar como se fosse
    real, e cai aqui."""
    linha = _ate_ao_ponto_e_virgula(_ler(_FINALIZAR), _ASSINATURA_AVISO_NO_ECRA, _FINALIZAR)
    resultado = _correr_no_node(
        "\n".join([
            _decisao_solta(),
            "const decidir = (documento) => { %s; return avisoDoModo; };" % linha.rstrip(";"),
            "const docs = [{ modo: 'normal' }, { modo: 'tests' }, {}];",
            "process.stdout.write(JSON.stringify(",
            "  docs.map((d) => { const a = decidir(d); return a && a.titulo; }),",
            "));",
        ]),
        tmp_path,
        "documento-no-ecra.js",
    )
    assert resultado == [
        None,
        "Documento SEM VALOR FISCAL",
        "NÃO SABEMOS SE ESTA FATURA É REAL",
    ]


# --- O backoffice, e a única saída deliberada da regra ------------------------
#
# No POS, `normal` é silêncio. Aqui não é, e é de propósito: o pedido nasceu de
# o dono não conseguir responder à pergunta «está tudo em teste né?» sem ir ao
# servidor. O ALARME obedece à mesma regra dos três estados; o que muda é que o
# estado normal também se lê.


def _avisos_de_backoffice(tmp_path):
    return _correr_no_node(
        "\n".join([
            _decisao_solta(),
            "const estados = ['tests', 'normal', 'desconhecido', undefined];",
            "process.stdout.write(JSON.stringify(",
            "  estados.map((e) => avisoDoModoNoBackoffice(e)),",
            "));",
        ]),
        tmp_path,
        "backoffice.js",
    )


def test_no_backoffice_o_gestor_ve_a_resposta_tambem_em_normal(tmp_path):
    """A saída deliberada, escrita com todas as letras para não ser
    "corrigida" um dia por quem compare com o POS e ache que é um esquecimento.

    Nunca `null`: o gestor entra aqui para CONFIRMAR, e um ecrã calado obriga-o
    a saber de cor que o silêncio quer dizer «sim» — que foi exactamente o
    problema que isto veio resolver."""
    testes, normal, desconhecido, por_apurar = _avisos_de_backoffice(tmp_path)
    assert normal is not None
    assert normal["titulo"] == "A emitir faturas reais"
    # Calmo, e não um alarme: o estado normal informa, não assusta. Se este tom
    # passasse a 'alarme', o gestor via um aviso vermelho todos os dias e
    # deixava de olhar para ele no dia em que ele quisesse dizer alguma coisa.
    assert normal["tom"] == "calmo"
    assert testes["tom"] == "alarme"
    assert desconhecido["tom"] == "perigo"
    # E o terceiro estado continua a ser o que sai de um estado por apurar.
    assert por_apurar == desconhecido


def test_no_backoffice_os_tres_estados_dizem_coisas_diferentes(tmp_path):
    """Três títulos distintos. Um gestor que veja a mesma frase nos três
    estados não está a ler nenhum deles."""
    titulos = [a["titulo"] for a in _avisos_de_backoffice(tmp_path)]
    assert len(set(titulos[:3])) == 3
# --- O ecrã do backoffice, montado ele também --------------------------------
#
# Este guarda era inteiramente textual — procurava nomes de funções e a
# ausência de `/pos/` no ficheiro — e sobrevivia a qualquer mutação que
# mantivesse os nomes e partisse o que eles fazem. Agora monta-se o ecrã com o
# servidor fabricado, e o que se afirma é o que o gestor lê.


@pytest.fixture(scope="module")
def modo_no_backoffice(tmp_path_factory):
    cenario = "\n".join([
        "const Ecra = carregar(%s).default;" % json.dumps(str(_BACKOFFICE)),
        _RESPOSTAS_DO_MODO,
        "(async () => {",
        "  const saida = {};",
        "  for (const [nome, resposta] of RESPOSTAS_DO_MODO) {",
        "    RESPOSTAS_GESTAO['/faturacao/modo-de-emissao'] = resposta;",
        "    saida[nome] = await montar(React.createElement(Ecra));",
        "  }",
        "  saida.pedidos = pedidos;",
        "  process.stdout.write(JSON.stringify(saida));",
        "})().catch((e) => { console.error(e); process.exit(3); });",
    ])
    return _montar_no_node(
        cenario, tmp_path_factory.mktemp("backoffice"), "montar-backoffice.js"
    )


def test_no_backoffice_montado_o_gestor_ve_a_resposta_em_cada_um_dos_tres_estados(
    modo_no_backoffice,
):
    """Incluindo `normal`, a saída deliberada da regra do POS: o gestor entra
    aqui para CONFIRMAR, e um ecrã calado obriga-o a saber de cor que o
    silêncio quer dizer «sim»."""
    assert "A emitir faturas reais" in modo_no_backoffice["normal"]
    assert "MODO DE TESTES — as lojas não estão a facturar" in modo_no_backoffice["tests"]
    for resposta in ("sem-modo", "sem-rota"):
        assert "NÃO SABEMOS EM QUE MODO O POS ESTÁ A EMITIR" in modo_no_backoffice[resposta]
    tres = [modo_no_backoffice[r] for r in ("tests", "normal", "sem-modo")]
    assert len(set(tres)) == 3


def test_o_ecra_do_backoffice_pergunta_pela_rota_dele_e_com_o_axios_de_gestao(
    modo_no_backoffice,
):
    """Nunca pela rota do POS: essa pede o token do dispositivo, que o browser
    do gestor não tem — o painel caía no terceiro estado para sempre, sem
    ninguém perceber porquê. E nunca pela instância de axios do POS, que é a
    que não leva o JWT de gestão.

    Aqui isto vê-se: o servidor fabricado separa as duas famílias, e o que se
    afirma é por qual delas o ecrã perguntou."""
    pedidos = modo_no_backoffice["pedidos"]
    assert pedidos, "O ecrã do backoffice montou-se sem perguntar nada ao servidor."
    for pedido in pedidos:
        assert pedido.startswith("gestao:"), (
            "O ecrã do backoffice perguntou pelo axios do POS: %s" % pedido
        )
        assert pedido.endswith("/api/faturacao/modo-de-emissao"), pedido
        assert "/pos/" not in pedido, pedido


def test_o_painel_do_gestor_monta_esta_linha():
    """Textual, e sabe-se pouco valioso — serve só para a linha não ficar
    escrita num ficheiro que ninguém desenha. O que ela DIZ está guardado
    acima, com o ecrã montado."""
    dashboard = _ler(_DASHBOARD)
    assert "<FatModoDeEmissao" in dashboard
