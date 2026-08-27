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
4. e o que a operadora **LÊ** — não o `textContent`, que é o que está escrito
   no ficheiro, mas o que fica no ecrã depois de o `display` e a `visibility`
   decidirem. Um atacante desligou esta faixa de oito maneiras sem partir uma
   linha de lógica: trocar `flex` por `hidden` na className, passar os textos
   para atributos, desligar o bloco do JSX com um `false &&`, prender o efeito
   em `[]` no dia do emparelhamento, deixar cair o relógio da releitura. As
   oito estavam verdes e estão todas guardadas aqui — cada uma com o cenário
   em que se mediu.

**O que este ficheiro NÃO cobre, dito com todas as letras.** O que se vê
mede-se com uma folha de estilo escrita à mão (`ESTILOS`, no preâmbulo de
montagem) que declara as classes do Tailwind que decidem visibilidade —
`hidden`, `flex`, `block`, `invisible`, `sr-only`. Esconder a faixa por outro
caminho (largura zero, `opacity-0`, mandá-la para fora do ecrã com
`position`) passa por aqui sem acordar ninguém. E o jsdom não tem media
queries, por isso as variantes responsivas não se avaliam: o que se mede é o
ECRÃ ESTREITO, que é o pior caso.

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
        # A folha de estilo mínima: sem ela, «está no DOM» e «vê-se» são a
        # mesma coisa, e uma palavra (`flex` -> `hidden`) apaga a faixa do ecrã
        # com a suite verde. As classes do Tailwind não são CSS até alguém o
        # gerar; aqui declaram-se À MÃO as que decidem se uma coisa se vê, e o
        # `getComputedStyle` do jsdom faz a cascata a sério sobre elas (há um
        # guarda que verifica que esta técnica funciona — `test_a_TECNICA_...`).
        #
        # O que NÃO está aqui, de propósito: as variantes responsivas
        # (`lg:block`, `sm:block`). O jsdom não tem media queries, por isso a
        # classe base ganha e o que se mede é o ECRÃ ESTREITO — o pior caso, e
        # o que a barra do POS foi desenhada para aguentar: o título tem de
        # caber sempre, o porquê é que pode cair.
        "const ESTILOS = [",
        "  '.hidden{display:none}',",
        "  '.flex{display:flex}', '.inline-flex{display:inline-flex}',",
        "  '.block{display:block}', '.inline-block{display:inline-block}',",
        "  '.inline{display:inline}', '.grid{display:grid}', '.table{display:table}',",
        "  '.invisible{visibility:hidden}',",
        # sr-only: existe para o leitor de ecrã, e não para os olhos de quem
        # está ao balcão. Quem lê é a operadora.
        "  '.sr-only{display:none}',",
        "].join('');",
        "const dom = new JSDOM('<!doctype html><html><head><style>' + ESTILOS +",
        "  '</style></head><body><div id=\"raiz\"></div></body></html>',",
        "  { url: 'http://localhost/' });",
        "global.window = dom.window;",
        "global.document = dom.window.document;",
        "global.navigator = dom.window.navigator;",
        "global.localStorage = dom.window.localStorage;",
        # O `sessionStorage` e' onde a SESSAO DO OPERADOR passou a viver: e' o
        # que distingue um F5 (mantem) de desligar o PC (esquece). Sem ele
        # exposto aqui, os ecras montavam sem operador nenhum.
        "global.sessionStorage = dom.window.sessionStorage;",
        "global.IS_REACT_ACT_ENVIRONMENT = true;",
        # --- o relógio, na mão ------------------------------------------------
        # O `setInterval` não chega a agendar nada: fica registado, e um cenário
        # faz-lhe bater a hora quando quiser. É a única maneira de guardar o
        # «a rede volta e a faixa recupera sozinha» sem esperar 60 segundos por
        # teste — e sem ele, apagar a linha do `setInterval` não parte guarda
        # nenhum: o ecrã do arranque continua certo, e o que morre é a
        # recuperação, que só se vê minutos depois.
        "const relogios = [];",
        "global.setInterval = (fn, ms) => {",
        "  relogios.push({ fn, ms });",
        "  return { relogioFalso: relogios.length };",
        "};",
        "global.clearInterval = () => {};",
        "dom.window.setInterval = global.setInterval;",
        "dom.window.clearInterval = global.clearInterval;",
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
        # A chave pode nomear o MÉTODO (`'POST /pos/…'`) ou só o caminho.
        # Sem isso, um ecrã que faz GET e POST no MESMO caminho — a nota de
        # crédito faz: `GET …/nota-credito` prepara e `POST …/nota-credito`
        # emite — não tinha como fabricar duas respostas diferentes. As chaves
        # sem espaço continuam a casar como sempre casaram.
        "function responder(config) {",
        "  const url = String(config.url);",
        "  const metodo = String(config.metodo || '').toUpperCase();",
        "  const tabela = url.includes('/pos/') ? RESPOSTAS_POS : RESPOSTAS_GESTAO;",
        "  const casa = (c) => (c.includes(' ')",
        "    ? (c.split(' ')[0] === metodo && url.endsWith(c.split(' ')[1]))",
        "    : url.endsWith(c));",
        "  const chave = Object.keys(tabela).find((c) => c.includes(' ') && casa(c))",
        "    || Object.keys(tabela).find((c) => !c.includes(' ') && casa(c));",
        "  if (!chave) {",
        "    const e = new Error('pedido nao fabricado: ' + url);",
        "    e.response = { status: 404 };",
        "    throw e;",
        "  }",
        "  return tabela[chave]();",
        "}",
        # Uma instância que CORRE os interceptores de pedido que lhe
        # registarem, e guarda de cada chamada o que ela leva mesmo: a URL, os
        # cabeçalhos e o TECTO DE ESPERA. Sem isto, «por qual axios perguntou»
        # era a única coisa afirmável — e essa pergunta deixa de fazer sentido
        # assim que um ficheiro passa a ter a sua própria instância. O que
        # interessa não é o objecto: é o que o pedido leva.
        #
        # A herança é a do axios a sério, e é deliberado: `axios.create()`
        # COPIA os `defaults` no instante da criação e nunca mais olha para
        # eles (medido no axios 1.18.1 deste repositório). Uma instância criada
        # antes do login nasce sem o `Authorization` e fica sem ele para
        # sempre — por isso quem cria uma instância tem de ir buscar o JWT no
        # pedido, e é isso que se guarda aqui.
        "const METODOS = ['get', 'post', 'put', 'delete', 'patch'];",
        "const SEM_CORPO = new Set(['get', 'delete']);",
        "function instancia(base) {",
        "  const interceptores = [];",
        "  const inst = {",
        "    defaults: base,",
        "    interceptors: {",
        "      request: { use: (fn) => interceptores.push(fn) },",
        "      response: { use: () => {} },",
        "    },",
        "  };",
        "  for (const metodo of METODOS) {",
        "    inst[metodo] = async (url, ...resto) => {",
        "      const opcoes = SEM_CORPO.has(metodo) ? resto[0] : resto[1];",
        "      let config = {",
        "        metodo,",
        "        url: (base.baseURL || '') + url,",
        "        headers: Object.assign({}, (base.headers && base.headers.common) || {}),",
        "        timeout: (opcoes && opcoes.timeout !== undefined) ? opcoes.timeout : base.timeout,",
        # O CORPO do pedido, que faltava. «Por qual axios perguntou» e «com que
        # cabeçalhos» não chegam para um ecrã cujo defeito é MANDAR o número
        # errado: o tecto da quantidade da nota de crédito prova-se no
        # `{ linhas: [...] }` que sai, não no caminho.
        "        corpo: SEM_CORPO.has(metodo) ? undefined : resto[0],",
        # Os PARÂMETROS DE QUERY, que faltavam. Sem eles, um ecrã que mande o
        # filtro errado (o literal "todas" em vez de nenhum filtro) passava
        # despercebido: o teste via a chamada, não via o que ela pedia.
        # Medido: a mutação que fazia viajar o "todas" deixava a suite verde.
        "        params: (opcoes && opcoes.params) || undefined,",
        "      };",
        "      for (const fn of interceptores) config = fn(config) || config;",
        "      pedidos.push(config);",
        "      return responder(config);",
        "    };",
        "  }",
        "  return inst;",
        "}",
        # O axios GLOBAL: é ele que leva o JWT de gestão em
        # `defaults.headers.common`, posto pelo AuthContext depois do login.
        "const axiosFalso = instancia(",
        "  { headers: { common: { Authorization: 'Bearer JWT-DE-GESTAO' } } });",
        "axiosFalso.create = (config) => instancia(Object.assign({}, config || {}));",
        # --- o que entra substituído -----------------------------------------
        "const icones = new Proxy({}, { get: (_, nome) => (",
        "  typeof nome === 'string' && nome !== '__esModule'",
        "    ? () => React.createElement('i', { 'data-icone': String(nome) })",
        "    : undefined",
        ") });",
        # As marcas guardam os props que receberam: é por eles que um cenário
        # pode CARREGAR no que o ecrã substituído oferecia — aceitar o código
        # de emparelhamento, entrar com o PIN — sem ter de montar esses ecrãs.
        "const ultimosProps = {};",
        "const marca = (nome) => {",
        "  const C = (props) => {",
        "    ultimosProps[nome] = props;",
        "    return React.createElement('div', { 'data-substituto': nome },",
        "      props && props.children);",
        "  };",
        "  C.displayName = nome;",
        "  return C;",
        "};",
        # `__esModule: true` para o `import X from ...` também funcionar: sem
        # ele o interop do babel embrulha o proxy inteiro em `{ default: ... }`
        # e o ecrã rebenta com «Element type is invalid» na primeira marca
        # importada por omissão (o `PageHeader` do FatDashboard).
        "const marcas = new Proxy({}, { get: (_, nome) => (",
        "  nome === '__esModule' ? true",
        "    : (typeof nome === 'string' ? marca(String(nome)) : undefined)",
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
        # **As marcas da biblioteca de UI, ou o que o CENÁRIO puser em vez
        # delas.** Por omissão fica tudo como estava — `global.__componentes` é
        # `undefined` e as marcas ganham, e é isso que mantém este ficheiro
        # exactamente como estava. Um cenário que precise de um botão que
        # RESPONDA AO DEDO (o separador Faturação, em
        # `test_o_separador_de_faturacao_no_ecra.py`: o painel só abre depois
        # de alguém carregar) põe lá os seus, ANTES do primeiro `carregar`.
        # Sem este gancho, a alternativa era uma segunda cópia deste
        # carregador — e uma segunda cópia diverge da primeira.
        "    if (pedido.startsWith('@/components/'))",
        "      return (global.__componentes || marcas);",
        "    if (pedido.startsWith('@/')) return carregar(path.join(RAIZ, pedido.slice(2)) + '.js');",
        "    if (pedido.startsWith('.')) {",
        "      const resolvido = path.resolve(path.dirname(ficheiro), pedido);",
        # A mesma regra do `@/components/`, dita sobre o caminho já resolvido:
        # há ecrãs (o FatDashboard) que os importam por caminho relativo, e um
        # deles arrastava metade da biblioteca de UI para dentro do guarda.
        "      if (resolvido.startsWith(path.join(RAIZ, 'components')))",
        "        return (global.__componentes || marcas);",
        "      return carregar(resolvido + '.js');",
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
        # --- o que a OPERADORA lê -------------------------------------------
        # `textContent` é o que está escrito no ficheiro; isto é o que está no
        # ecrã. A diferença mediu-se: `flex` -> `hidden` na classe da faixa
        # (UMA palavra) apaga-a do balcão — `display: none`,
        # `getClientRects().length === 0`, e o `innerText` do browser sem a
        # frase — enquanto o `textContent` a continua a ter toda. E os textos
        # postos em atributos (`data-titulo={faixa.titulo}`) desenham uma barra
        # âmbar com o escudo e ZERO palavras, indistinguível da vermelha.
        #
        # Duas regras, e as duas são o que os olhos fazem: um ramo apagado não
        # se lê, e um valor guardado num atributo não é texto nenhum — só se
        # apanham nós de texto.
        "function textoVisivel(raiz) {",
        "  const janela = raiz.ownerDocument.defaultView;",
        "  const partes = [];",
        "  (function andar(no) {",
        "    if (no.nodeType === 3) { partes.push(no.data); return; }",
        "    if (no.nodeType !== 1) return;",
        "    if (no.hasAttribute('hidden')) return;",
        "    const estilo = janela.getComputedStyle(no);",
        "    if (estilo.display === 'none' || estilo.visibility === 'hidden') return;",
        "    for (const filho of no.childNodes) andar(filho);",
        "  })(raiz);",
        "  return partes.join(' ').replace(/\\s+/g, ' ').trim();",
        "}",
        # --- montar, e olhar -------------------------------------------------
        # Devolve os dois: `html` (o que está no DOM) e `visivel` (o que se lê).
        # Os guardas que interessam afirmam o SEGUNDO — o primeiro fica para as
        # afirmações de identidade («é mesmo esta a barra que está montada»).
        "async function montar(elemento) {",
        "  const alvo = document.getElementById('raiz');",
        "  const raiz = createRoot(alvo);",
        "  await act(async () => { raiz.render(elemento); });",
        "  await act(async () => {});",
        "  const saida = { html: alvo.innerHTML, visivel: textoVisivel(alvo) };",
        "  await act(async () => { raiz.unmount(); });",
        "  alvo.innerHTML = '';",
        "  return saida;",
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
    # A quinta não é uma resposta: é a AUSÊNCIA dela. O servidor aceita o
    # pedido e nunca responde — o Wi-Fi da loja a piscar, o proxy a segurar a
    # ligação. É o estado em que o ecrã passa a espera toda, e é o mais fácil
    # de esquecer porque nenhum `catch` chega a correr.
    "  ['pendente', () => new Promise(() => {})],",
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
    html = barras_do_pos[barra + "/tests"]["html"]
    assert _LOJA_DO_GUARDA in html, "Não é a barra do POS que está aqui montada."
    assert _FAIXA_TESTES in html
    assert "Autoridade Tributária" in html


@pytest.mark.parametrize("barra", ["aberta", "fechada"])
def test_a_barra_do_POS_montada_fica_MUDA_quando_o_servidor_diz_normal(barras_do_pos, barra):
    """E muda de verdade: a barra continua lá inteira, sem faixa nenhuma."""
    html = barras_do_pos[barra + "/normal"]["html"]
    assert _LOJA_DO_GUARDA in html, "Não é a barra do POS que está aqui montada."
    assert _FAIXA_TESTES not in html
    assert _FAIXA_DESCONHECIDO not in html
    assert 'role="alert"' not in html


@pytest.mark.parametrize("barra", ["aberta", "fechada"])
@pytest.mark.parametrize("resposta", ["sem-modo", "sem-rota"])
def test_a_barra_do_POS_montada_avisa_quando_nao_se_sabe(barras_do_pos, barra, resposta):
    """Um 200 sem modo e a rota em baixo dão o MESMO ecrã: o aviso do terceiro
    estado. Nunca o silêncio de `normal`, que é o engano caro."""
    html = barras_do_pos[barra + "/" + resposta]["html"]
    assert _LOJA_DO_GUARDA in html, "Não é a barra do POS que está aqui montada."
    assert _FAIXA_DESCONHECIDO in html
    assert _FAIXA_TESTES not in html


@pytest.mark.parametrize("barra", ["aberta", "fechada"])
def test_o_HTML_das_duas_barras_MUDA_com_o_que_o_servidor_responde(barras_do_pos, barra):
    """Três respostas, três ecrãs diferentes — a afirmação directa contra o
    prop cravado. Um `estado` escrito à mão dá três HTML iguais, e cai aqui
    mesmo que alguém invente um quarto estado com o texto certo."""
    html = [barras_do_pos["%s/%s" % (barra, r)]["html"]
            for r in ("tests", "normal", "sem-modo")]
    assert len(set(html)) == 3


# --- E agora o que a operadora LÊ mesmo ---------------------------------------
#
# Os quatro de cima olham para o HTML: chegam para o prop cravado, e não chegam
# para a faixa escondida nem para os textos em atributos. Estes olham para o
# ecrã.


@pytest.mark.parametrize("barra", ["aberta", "fechada"])
def test_a_operadora_LE_a_faixa_de_testes_no_ecra(barras_do_pos, barra):
    """`flex` -> `hidden` na className: a faixa continua no DOM, com o texto
    todo lá dentro, e não está no ecrã. Uma palavra, e cinco lojas a facturar o
    dia inteiro para o vazio.

    Afirma-se o TÍTULO e não o porquê: numa barra de 64 px o que tem de caber
    sempre é a frase que faz parar (o porquê é `lg:block`, e no ecrã estreito
    cai de propósito)."""
    lido = barras_do_pos[barra + "/tests"]["visivel"]
    assert _LOJA_DO_GUARDA in lido, "Não é a barra do POS que está aqui montada."
    assert _FAIXA_TESTES in lido, (
        "A faixa está no DOM mas a operadora não a lê. O que ficou no ecrã: %r" % lido
    )


@pytest.mark.parametrize("barra", ["aberta", "fechada"])
@pytest.mark.parametrize("resposta", ["sem-modo", "sem-rota"])
def test_a_operadora_LE_o_aviso_do_terceiro_estado(barras_do_pos, barra, resposta):
    lido = barras_do_pos["%s/%s" % (barra, resposta)]["visivel"]
    assert _LOJA_DO_GUARDA in lido, "Não é a barra do POS que está aqui montada."
    assert _FAIXA_DESCONHECIDO in lido, (
        "O aviso está no DOM mas a operadora não o lê. O que ficou no ecrã: %r" % lido
    )


@pytest.mark.parametrize("barra", ["aberta", "fechada"])
def test_ENQUANTO_ESPERA_a_barra_do_POS_ja_avisa(barras_do_pos, barra):
    """O servidor aceitou o pedido e nunca respondeu — e a espera pode durar o
    turno inteiro.

    Este é o buraco por onde o valor por omissão desce até ao JSX:
    `estado={modo === undefined ? 'normal' : modo}` no `PosMenuCaixa` deixa o
    `useState(undefined)` intacto lá em cima (e o guarda dele verde) e apaga a
    faixa durante a espera toda. Medido com o servidor a demorar 8 s: ecrã de
    venda sem faixa nenhuma, indistinguível de `normal`.

    Enquanto não se sabe, diz-se que não se sabe."""
    ecra = barras_do_pos[barra + "/pendente"]
    assert _LOJA_DO_GUARDA in ecra["visivel"], "Não é a barra do POS que está aqui montada."
    assert _FAIXA_DESCONHECIDO in ecra["visivel"], (
        "Enquanto espera pela resposta, a barra do POS não avisa de nada. O "
        "que ficou no ecrã: %r" % ecra["visivel"]
    )


@pytest.mark.parametrize("barra", ["aberta", "fechada"])
def test_o_que_a_operadora_LE_muda_com_o_que_o_servidor_responde(barras_do_pos, barra):
    """A afirmação que apanha as duas saídas de uma vez.

    - com a faixa escondida (`hidden`), as três respostas dão o mesmo ecrã: a
      barra sem faixa nenhuma;
    - com os textos em atributos, `tests` e «não sabemos» dão ZERO palavras os
      dois — dois rectângulos coloridos, e a cor não é uma frase.

    Três respostas do servidor, três coisas diferentes para ler."""
    lido = [barras_do_pos["%s/%s" % (barra, r)]["visivel"]
            for r in ("tests", "normal", "sem-modo")]
    assert len(set(lido)) == 3, (
        "O que se LÊ na barra não muda com o modo — a faixa pode estar montada "
        "e invisível, ou a desenhar cor sem palavras. Ecrãs: %r" % (lido,)
    )


def test_no_arranque_o_POS_PERGUNTA_ao_servidor_em_que_modo_esta(barras_do_pos):
    """A pergunta é feita, e é feita pela rota do POS — com o axios do POS, que
    é o que leva o token do dispositivo.

    Apagar o `ler();` do `useEffect` do `PosApp` (deixando lá o `const ler` e o
    `setInterval`) deixava a suite inteira verde: ninguém guardava o ARRANQUE,
    só a função que ele chama. Sem a pergunta, a barra fica presa no terceiro
    estado durante os primeiros 60 segundos de cada turno."""
    perguntas = [p for p in barras_do_pos["pedidos"]
                 if p["url"].endswith("/pos/modo-de-emissao")]
    assert perguntas, "O POS montou-se sem perguntar ao servidor em que modo está a emitir."
    # E leva o token do DISPOSITIVO — deliberadamente não o do operador: a
    # faixa tem de continuar de pé durante a troca de operador, e nesse
    # instante o ecrã não tem token de operador nenhum.
    for pergunta in perguntas:
        assert pergunta["headers"].get("X-Device-Token"), (
            "A pergunta do modo saiu sem o token do dispositivo: %r" % (pergunta,)
        )
        assert "Authorization" not in pergunta["headers"], (
            "A pergunta do POS levou o JWT de gestão, que o balcão não tem: %r" % (pergunta,)
        )
        assert pergunta["timeout"], (
            "A pergunta do modo saiu sem tecto de espera: um pedido pendurado "
            "deixa a faixa presa no terceiro estado para sempre. %r" % (pergunta,)
        )
    # Uma por montagem: as dez do cruzamento (duas barras x cinco respostas).
    assert len(perguntas) == 10, (
        "O arranque perguntou %d vezes em vez de uma por montagem. Se passou a "
        "haver outra leitura legítima, este número acompanha-a — mas confirme "
        "primeiro que não é o ecrã a remontar-se em ciclo." % len(perguntas)
    )

# --- A técnica de VER, ela própria guardada -----------------------------------
#
# Tudo o que se segue afirma o que a operadora LÊ, e não o que está escrito no
# ficheiro. A diferença não é teórica — mediu-se com o servidor em `tests`:
#
# - `flex` -> `hidden` na className do `PosFaixaModo`: UMA palavra, e a faixa
#   desaparece do balcão (`display: none`, `getClientRects().length === 0`, o
#   `innerText` do browser sem a frase) enquanto o `textContent` — o que um
#   guarda de HTML lê — a continua a ter toda;
# - os textos passados para atributos (`data-titulo={faixa.titulo}`): uma barra
#   âmbar com o escudo e ZERO palavras, e o estado `tests` e o «não sabemos»
#   passam a ser dois rectângulos coloridos indistinguíveis.
#
# É a saída que resta a quem já não consegue partir a lógica, e é também a mais
# fácil de provocar sem querer — com qualquer arrumação de layout na barra.
#
# Este guarda mede a MEDIDA: se o `textoVisivel` deixar de distinguir as duas
# coisas, tudo o que vem a seguir fica verde por engano, e é aqui que se dá por
# isso.


@pytest.fixture(scope="module")
def tecnica_de_ver(tmp_path_factory):
    cenario = "\n".join([
        "const Fabricado = () => React.createElement('div', { className: 'flex' },",
        "  React.createElement('span', null, 'LE-SE'),",
        "  React.createElement('span', { className: 'hidden' }, 'RAMO-APAGADO'),",
        "  React.createElement('span', { 'data-titulo': 'EM-ATRIBUTO' }),",
        "  React.createElement('span', { className: 'invisible' }, 'INVISIVEL'),",
        "  React.createElement('span', { className: 'sr-only' }, 'SO-PARA-O-LEITOR'),",
        ");",
        "(async () => {",
        "  process.stdout.write(JSON.stringify(",
        "    await montar(React.createElement(Fabricado))));",
        "})().catch((e) => { console.error(e); process.exit(3); });",
    ])
    return _montar_no_node(cenario, tmp_path_factory.mktemp("ver"), "ver.js")


def test_a_TECNICA_de_ver_distingue_o_que_esta_no_DOM_do_que_se_LE(tecnica_de_ver):
    """As quatro maneiras de uma palavra estar no ficheiro e não estar no ecrã.

    O HTML tem-nas todas — é exactamente por isso que um guarda de
    `textContent` não vale nada aqui."""
    for palavra in ("LE-SE", "RAMO-APAGADO", "EM-ATRIBUTO", "INVISIVEL", "SO-PARA-O-LEITOR"):
        assert palavra in tecnica_de_ver["html"], (
            "%s nem no DOM está — o guarda da técnica não montou o que julga." % palavra
        )
    assert tecnica_de_ver["visivel"] == "LE-SE", (
        "O `textoVisivel` deixou de distinguir «está no DOM» de «vê-se»: leu %r."
        % tecnica_de_ver["visivel"]
    )



# --- Quando a rede volta ------------------------------------------------------
#
# A faixa é relida de minuto a minuto, e não por gosto: é a ÚNICA maneira de o
# ecrã sair do terceiro estado sozinho. Sem isso, a operadora que apanhou a
# rede em baixo ao abrir a caixa fica com a barra vermelha o turno inteiro,
# sobre um servidor que já responde há uma hora — e a saída (F5) não é uma
# coisa que alguém ao balcão tenha razão para adivinhar.
#
# Medido com o `setInterval(ler, 60000)` apagado: 78 segundos depois, presa em
# «não sabemos», um único pedido em toda a sessão. E a variante que mantém o
# `ler()` e perde só o relógio dá exactamente o mesmo — os guardas do arranque
# ficam todos verdes, porque o arranque continua a acontecer.


@pytest.fixture(scope="module")
def a_rede_volta(tmp_path_factory):
    """O POS com a rede em baixo, e depois com ela de volta — sem F5, sem
    remontar nada, e sem esperar 60 segundos: o relógio bate à mão."""
    cenario = "\n".join([
        "const lib = carregar(path.join(RAIZ, 'lib', 'pos.js'));",
        "lib.guardarDispositivo({ device_token: 'dt', loja_id: 'l1', loja_nome: %s });"
        % json.dumps(_LOJA_DO_GUARDA),
        "lib.guardarOperador('ot', { id: 'o1', nome: 'Ana' });",
        "const PosApp = carregar(path.join(POS, 'PosApp.js')).default;",
        "const CAIXA = { id: 'c1', nome: 'Caixa 1' };",
        "const SESSAO = { aberta_por: { nome: 'Ana' }, aberta_em: '2026-08-20T09:00:00', fundo: 50 };",
        "RESPOSTAS_POS['/pos/caixa/estado'] = () => ({ data: {",
        "  caixas: [CAIXA], caixa: CAIXA, sessao_aberta: SESSAO, ultimo_fecho: null,",
        "} });",
        "RESPOSTAS_POS['/pos/modo-de-emissao'] = () => { throw new Error('Network Error'); };",
        "(async () => {",
        "  const alvo = document.getElementById('raiz');",
        "  const raiz = createRoot(alvo);",
        "  const passos = {};",
        "  const olhar = async (nome) => {",
        "    await act(async () => {});",
        "    passos[nome] = { html: alvo.innerHTML, visivel: textoVisivel(alvo) };",
        "  };",
        "  await act(async () => { raiz.render(React.createElement(PosApp)); });",
        "  await olhar('rede-em-baixo');",
        # A rede volta. Nada no ecrã muda por isso — o que muda é o que o
        # servidor responderia se alguém voltasse a perguntar.
        "  RESPOSTAS_POS['/pos/modo-de-emissao'] = () => ({ data: { modo: 'tests' } });",
        "  await olhar('rede-de-volta-sem-perguntar');",
        # E o relógio bate.
        "  passos.relogios = relogios.map((r) => r.ms);",
        "  await act(async () => { await Promise.all(relogios.map((r) => r.fn())); });",
        "  await olhar('depois-do-relogio');",
        "  await act(async () => { raiz.unmount(); });",
        "  process.stdout.write(JSON.stringify(passos));",
        "})().catch((e) => { console.error(e); process.exit(3); });",
    ])
    return _montar_no_node(cenario, tmp_path_factory.mktemp("rede"), "montar-rede.js")


def test_com_a_rede_em_baixo_a_faixa_avisa_e_NAO_se_cura_sozinha(a_rede_volta):
    """As duas metades do ponto de partida: a barra avisa, e continua a avisar
    enquanto ninguém voltar a perguntar. Sem esta segunda metade, o guarda de
    baixo podia ficar verde por o ecrã nunca ter chegado a estar errado."""
    assert _FAIXA_DESCONHECIDO in a_rede_volta["rede-em-baixo"]["visivel"]
    assert _FAIXA_DESCONHECIDO in a_rede_volta["rede-de-volta-sem-perguntar"]["visivel"]


def test_o_POS_volta_a_PERGUNTAR_sozinho_de_minuto_a_minuto(a_rede_volta):
    """Há um relógio, e bate a horas que servem para alguma coisa.

    Apagar o `setInterval` — ou deixar o `ler()` e levar só o relógio — cai
    aqui: não fica relógio nenhum registado."""
    relogios = a_rede_volta["relogios"]
    assert relogios, (
        "O POS não deixou nenhum relógio a reler o modo: a barra fica no "
        "estado em que apanhou o arranque até alguém fazer F5."
    )
    for ms in relogios:
        assert 0 < ms <= 300000, (
            "O relógio da faixa bate de %s em %s ms — a operadora que apanhar "
            "a rede em baixo fica com a barra errada até lá." % (ms, ms)
        )


def test_quando_a_rede_VOLTA_a_faixa_recupera_sem_F5(a_rede_volta):
    """O relógio bate, o POS volta a perguntar, e a barra passa a dizer a
    verdade — sem ninguém ao balcão ter de adivinhar que devia recarregar."""
    ecra = a_rede_volta["depois-do-relogio"]
    assert _LOJA_DO_GUARDA in ecra["visivel"], "Não é a barra do POS que está aqui montada."
    assert _FAIXA_TESTES in ecra["visivel"], (
        "A rede voltou, o relógio bateu, e a barra não recuperou. O que ficou "
        "no ecrã: %r" % ecra["visivel"]
    )
    assert _FAIXA_DESCONHECIDO not in ecra["visivel"]


# --- O DIA 1 de cada loja: o emparelhamento -----------------------------------
#
# **O caminho que a fixture de cima nunca percorre.** O `barras_do_pos` semeia
# o `localStorage` ANTES de montar, por isso o dispositivo já lá está no
# primeiro render e o efeito do modo corre. O caminho REAL do primeiro dia é o
# inverso: o POS monta-se SEM dispositivo nenhum, o
# `if (!dispositivo) return undefined;` sai logo, e só depois — quando o gestor
# der o código e a operadora entrar — é que passa a haver dispositivo.
#
# Trocar `}, [dispositivo]);` por `}, []);` no `PosApp` deixava os 1453 testes
# verdes. Percorrido no browser com o pacote mutado (código de emparelhamento →
# PIN → ecrã de venda): barra VERMELHA «NÃO SABEMOS SE ESTAS FATURAS SÃO REAIS»
# permanente, com o servidor a responder `{"modo": "tests"}` sem falhar uma
# vez, e `performance.getEntriesByType` filtrado por `modo-de-emissao` a dar
# ZERO pedidos. Um F5 cura — que é precisamente o que faria isto passar
# despercebido a quem testasse por recarregamento.
#
# São cinco lojas, e é o primeiro dia de cada uma delas.


@pytest.fixture(scope="module")
def dia_do_emparelhamento(tmp_path_factory):
    """O POS montado como no dia 1: `localStorage` vazio, e o dispositivo e a
    operadora a APARECEREM depois, pelos caminhos verdadeiros do `PosApp`.

    Não se remonta nada pelo caminho — é a mesma árvore de React do princípio
    ao fim, tal como no balcão."""
    cenario = "\n".join([
        "const lib = carregar(path.join(RAIZ, 'lib', 'pos.js'));",
        "lib.esquecerDispositivo();",
        "const PosApp = carregar(path.join(POS, 'PosApp.js')).default;",
        "const CAIXA = { id: 'c1', nome: 'Caixa 1' };",
        "const SESSAO = { aberta_por: { nome: 'Ana' }, aberta_em: '2026-08-20T09:00:00', fundo: 50 };",
        "RESPOSTAS_POS['/pos/caixa/estado'] = () => ({ data: {",
        "  caixas: [CAIXA], caixa: CAIXA, sessao_aberta: SESSAO, ultimo_fecho: null,",
        "} });",
        # O servidor está em `tests` desde o primeiro instante e responde
        # sempre: se a faixa não o disser, não foi por falta de resposta.
        "RESPOSTAS_POS['/pos/modo-de-emissao'] = () => ({ data: { modo: 'tests' } });",
        "(async () => {",
        "  const alvo = document.getElementById('raiz');",
        "  const raiz = createRoot(alvo);",
        "  const passos = {};",
        "  const olhar = async (nome) => {",
        "    await act(async () => {});",
        "    passos[nome] = { html: alvo.innerHTML, visivel: textoVisivel(alvo) };",
        "  };",
        "  await act(async () => { raiz.render(React.createElement(PosApp)); });",
        "  await olhar('sem-dispositivo');",
        # O gestor dá o código e o `PosEmparelhar` aceita-o: guarda o
        # dispositivo (é ele que o faz, no ecrã a sério) e avisa o `PosApp`.
        "  await act(async () => {",
        "    lib.guardarDispositivo({ device_token: 'dt', loja_id: 'l1', loja_nome: %s });"
        % json.dumps(_LOJA_DO_GUARDA),
        "    ultimosProps.PosEmparelhar.onEmparelhado(",
        "      { token: 'dt', lojaId: 'l1', lojaNome: %s });" % json.dumps(_LOJA_DO_GUARDA),
        "  });",
        "  await olhar('emparelhado');",
        # E a operadora entra com o PIN.
        "  await act(async () => {",
        "    ultimosProps.PosEntrar.onEntrar('ot', { id: 'o1', nome: 'Ana' });",
        "  });",
        "  await olhar('a-vender');",
        "  await act(async () => { raiz.unmount(); });",
        "  passos.pedidos = pedidos;",
        "  process.stdout.write(JSON.stringify(passos));",
        "})().catch((e) => { console.error(e); process.exit(3); });",
    ])
    return _montar_no_node(
        cenario, tmp_path_factory.mktemp("dia1"), "montar-dia-1.js"
    )


def test_no_dia_1_o_POS_arranca_mesmo_SEM_dispositivo(dia_do_emparelhamento):
    """A afirmação de que este guarda percorre o caminho que diz percorrer: se
    o POS já tivesse dispositivo à partida, isto media outra vez a fixture de
    cima e ficava verde com a mutação lá dentro."""
    assert 'data-substituto="PosEmparelhar"' in dia_do_emparelhamento["sem-dispositivo"]["html"], (
        "O POS não arrancou no ecrã de emparelhamento — o `localStorage` não "
        "estava vazio, e este guarda deixou de medir o dia 1."
    )


def test_no_dia_1_a_faixa_LE_o_modo_assim_que_ha_dispositivo(dia_do_emparelhamento):
    """O emparelhamento acontece, a operadora entra, e a barra tem de dizer a
    verdade — sem F5.

    Com `}, []);` em vez de `}, [dispositivo]);`, o efeito corre uma única vez,
    no render em que ainda não há dispositivo, sai pelo `return undefined` e
    NUNCA MAIS corre: a barra fica vermelha o dia inteiro por cima de um
    servidor que respondeu à primeira."""
    ecra = dia_do_emparelhamento["a-vender"]
    assert _LOJA_DO_GUARDA in ecra["visivel"], "Não se chegou ao ecrã de venda."
    assert _FAIXA_TESTES in ecra["visivel"], (
        "Depois do emparelhamento a faixa não diz o modo. O que ficou no "
        "ecrã: %r" % ecra["visivel"]
    )
    assert _FAIXA_DESCONHECIDO not in ecra["visivel"]


def test_no_dia_1_o_POS_chega_a_PERGUNTAR_em_que_modo_esta(dia_do_emparelhamento):
    """E pergunta mesmo: com o efeito preso em `[]` são ZERO pedidos ao
    `/pos/modo-de-emissao` do princípio ao fim do dia — medido no browser."""
    perguntas = [p for p in dia_do_emparelhamento["pedidos"]
                 if p["url"].endswith("/pos/modo-de-emissao")]
    assert perguntas, (
        "O POS emparelhou, a operadora entrou, e ninguém perguntou ao servidor "
        "em que modo está a emitir."
    )

# --- Nível 3b: o ecrã da CONFIRMAÇÃO, montado ---------------------------------
#
# **O buraco que este nível veio tapar, medido.** O guarda que cobria este ecrã
# (`test_o_ecra_da_confirmacao_usa_o_CARIMBO_do_documento`) extrai a linha
# `const avisoDoModo = avisoDoDocumento(documento);` e corre-a: prova que o
# aviso é CALCULADO, nunca que é DESENHADO. Envolver o bloco do JSX em
# `{false && avisoDoModo && (` deixava os 1453 testes verdes e os três
# documentos — `tests`, sem carimbo, e `normal` — davam HTML IDÊNTICO no ecrã:
# «Documento emitido / FS 1/1 / ATCUD — / Nova Venda», sem uma palavra sobre o
# talão que a operadora tem na mão não valer nada.
#
# É o ecrã onde o engano custa mais caro: ela acabou de emitir, está a entregar
# o talão ao cliente, e é a ÚLTIMA vez que alguém olha para aquele documento.
#
# Aqui monta-se o `PosFinalizar` a sério, com os três documentos fabricados, e
# o que se afirma é o ecrã que sai. `documento` presente manda-o directo ao
# ramo `DocumentoEmitido` — é esse o ecrã da confirmação.

_AVISO_DOC_TESTES = "Documento SEM VALOR FISCAL"
_AVISO_DOC_DESCONHECIDO = "NÃO SABEMOS SE ESTA FATURA É REAL"


@pytest.fixture(scope="module")
def confirmacao_do_pos(tmp_path_factory):
    """O `PosFinalizar` montado com um documento já emitido, uma vez por cada
    carimbo possível — devolve o ecrã que ficou à frente da operadora."""
    cenario = "\n".join([
        "const Finalizar = carregar(path.join(POS, 'PosFinalizar.js')).default;",
        "const VENDA = { id: 'v1', totais: { total: 12.5 }, linhas: [] };",
        "const DOCUMENTOS = [",
        "  ['tests', { numero: 'FS 1/1', atcud: 'AAA-1', modo: 'tests' }],",
        "  ['normal', { numero: 'FS 1/1', atcud: 'AAA-1', modo: 'normal' }],",
        "  ['sem-carimbo', { numero: 'FS 1/1', atcud: 'AAA-1' }],",
        "];",
        "(async () => {",
        "  const saida = {};",
        "  for (const [nome, documento] of DOCUMENTOS) {",
        "    saida[nome] = await montar(React.createElement(Finalizar, {",
        "      venda: VENDA, documento, tiposPagamento: [],",
        "      onVoltar: () => {}, onEmitir: () => {}, onAplicarDesconto: () => {},",
        "    }));",
        "  }",
        "  process.stdout.write(JSON.stringify(saida));",
        "})().catch((e) => { console.error(e); process.exit(3); });",
    ])
    return _montar_no_node(
        cenario, tmp_path_factory.mktemp("confirmacao"), "montar-confirmacao.js"
    )


def test_a_confirmacao_montada_DIZ_que_o_documento_de_testes_nao_vale(confirmacao_do_pos):
    """O ecrã, montado, com um documento carimbado `tests`.

    Não é «a função devolveu o aviso»: é o aviso no ecrã, com as palavras que
    fazem a operadora parar antes de entregar o talão."""
    ecra = confirmacao_do_pos["tests"]
    assert "Documento emitido" in ecra["html"], "Não é o ecrã da confirmação que está montado."
    assert _AVISO_DOC_TESTES in ecra["visivel"], (
        "O aviso não está no ecrã da confirmação. O que lá ficou: %r" % ecra["visivel"]
    )
    assert "Autoridade Tributária" in ecra["visivel"]


def test_a_confirmacao_montada_avisa_quando_o_documento_veio_SEM_carimbo(confirmacao_do_pos):
    """Um documento sem o campo `modo` (um servidor mais velho, uma releitura
    que o perdeu) não é um documento normal: é um documento que não se sabe.
    «Nada» lê-se como «é real», e é esse o engano caro."""
    ecra = confirmacao_do_pos["sem-carimbo"]
    assert "Documento emitido" in ecra["html"], "Não é o ecrã da confirmação que está montado."
    assert _AVISO_DOC_DESCONHECIDO in ecra["visivel"], (
        "O aviso não está no ecrã da confirmação. O que lá ficou: %r" % ecra["visivel"]
    )
    assert _AVISO_DOC_TESTES not in ecra["visivel"]


def test_a_confirmacao_montada_do_documento_REAL_nao_inventa_aviso(confirmacao_do_pos):
    """E cala-se de verdade: um aviso permanente por cima de todas as faturas
    reais ensinava a operadora a passar por cima dos outros dois."""
    ecra = confirmacao_do_pos["normal"]
    assert "Documento emitido" in ecra["html"], "Não é o ecrã da confirmação que está montado."
    assert _AVISO_DOC_TESTES not in ecra["html"]
    assert _AVISO_DOC_DESCONHECIDO not in ecra["html"]


def test_os_TRES_ecras_de_confirmacao_sao_diferentes_uns_dos_outros(confirmacao_do_pos):
    """A afirmação directa contra o bloco desligado: `{false && avisoDoModo &&`
    deixa a linha escrita, o aviso continua a ser CALCULADO — e os três
    documentos dão o MESMO ecrã. Três carimbos, três ecrãs."""
    ecras = [confirmacao_do_pos[c]["visivel"] for c in ("tests", "normal", "sem-carimbo")]
    assert len(set(ecras)) == 3, (
        "O carimbo do documento não muda o que a operadora LÊ na confirmação: "
        "os três documentos deram o mesmo ecrã. %r" % (ecras,)
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
    assert "A emitir faturas reais" in modo_no_backoffice["normal"]["html"]
    assert ("MODO DE TESTES — as lojas não estão a facturar"
            in modo_no_backoffice["tests"]["html"])
    for resposta in ("sem-modo", "sem-rota"):
        assert ("NÃO SABEMOS EM QUE MODO O POS ESTÁ A EMITIR"
                in modo_no_backoffice[resposta]["html"])
    tres = [modo_no_backoffice[r]["html"] for r in ("tests", "normal", "sem-modo")]
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
        assert pedido["url"].endswith("/api/faturacao/modo-de-emissao"), pedido
        assert "/pos/" not in pedido["url"], pedido
        assert pedido["headers"].get("Authorization") == "Bearer JWT-DE-GESTAO", (
            "O ecrã do gestor perguntou sem o JWT de gestão. Isto acontece "
            "quando o pedido sai por uma instância de axios criada ANTES do "
            "login: `axios.create()` copia os `defaults` no instante da "
            "criação e nunca mais olha para eles. %r" % (pedido,)
        )
        assert "X-Device-Token" not in pedido["headers"], (
            "O ecrã do gestor perguntou com os tokens do POS, que o browser "
            "dele não tem: %r" % (pedido,)
        )


def test_o_painel_do_gestor_MOSTRA_MESMO_a_resposta(tmp_path_factory):
    """O painel montado, e a resposta lida nele.

    `{false && <FatModoDeEmissao />}` deixa a linha escrita no ficheiro — o
    guarda textual aqui em baixo continua verde — e abre o painel sem faixa
    nenhuma. O gestor entra para confirmar em que modo as lojas estão a emitir
    e não encontra a resposta em lado nenhum, que é o estado a que isto veio
    pôr fim.

    O pedido do dashboard não é fabricado de propósito: a faixa fica ANTES dos
    números e tem de aparecer mesmo quando eles não carregam."""
    cenario = "\n".join([
        "const Painel = carregar(%s).default;" % json.dumps(str(_DASHBOARD)),
        "RESPOSTAS_GESTAO['/faturacao/modo-de-emissao'] = () => ({ data: { modo: 'tests' } });",
        "(async () => {",
        "  process.stdout.write(JSON.stringify(",
        "    await montar(React.createElement(Painel))));",
        "})().catch((e) => { console.error(e); process.exit(3); });",
    ])
    ecra = _montar_no_node(
        cenario, tmp_path_factory.mktemp("painel"), "montar-painel.js"
    )
    assert "MODO DE TESTES — as lojas não estão a facturar" in ecra["visivel"], (
        "O painel do gestor abriu sem dizer em que modo as lojas estão a "
        "emitir. O que lá ficou: %r" % ecra["visivel"][:400]
    )


def test_o_painel_do_gestor_monta_esta_linha():
    """Textual, e sabe-se pouco valioso — serve só para a linha não ficar
    escrita num ficheiro que ninguém desenha. O que ela DIZ está guardado
    acima, com o ecrã montado."""
    dashboard = _ler(_DASHBOARD)
    assert "<FatModoDeEmissao" in dashboard


# --- O ecrã do gestor não pode mentir PARA SEMPRE -----------------------------
#
# O `FatModoDeEmissao` responde à pergunta que o dono fez — «está tudo em teste
# né? posso fazer faturas aqui normal.» — e tem duas maneiras de a responder
# mal, as duas silenciosas:
#
# 1. **arrancar num dos dois lados.** `useState('normal')` fica verde em tudo o
#    resto e, durante a espera, o gestor lê «A emitir faturas reais» com um
#    visto verde ao lado. O valor inicial de um estado do React é uma resposta
#    que ninguém deu.
# 2. **nunca sair da espera.** O `lib/faturacao.js` não tinha tecto de espera
#    NENHUM — usa o axios global, e não há `axios.defaults.timeout` em lado
#    nenhum deste repositório (só o `lib/pos.js` os tem). Um pedido pendurado
#    — o Wi-Fi a piscar, o servidor a não fechar a ligação — deixa o ecrã no
#    estado inicial **para sempre**, sem erro, sem spinner que acabe e sem
#    ninguém a saber que está a ler uma resposta que nunca chegou.
#
# Juntas, as duas dão a mentira permanente: um ecrã que afirma «faturas reais»
# por cima de um servidor que nunca respondeu.
#
# O tecto não é só desta chamada: são as 51 exportações do mesmo ficheiro, e é
# por isso que este guarda as CHAMA a todas em vez de olhar para uma.

_RE_ESTADO_INICIAL_BACKOFFICE = re.compile(r"const \[estado, setEstado\] = useState\((.*?)\);")


def test_antes_de_o_servidor_responder_o_ecra_do_GESTOR_nao_sabe(tmp_path):
    """O gémeo do `test_antes_de_o_servidor_responder_o_ecra_NAO_SABE` do POS.

    Aqui o engano é maior, não menor: no backoffice `normal` RESPONDE (é a
    saída deliberada da regra), por isso um estado inicial em `'normal'` não
    fica calado — afirma «A emitir faturas reais», com um visto verde, sobre um
    servidor que ainda não disse nada."""
    inicial = _expressao(
        _ler(_BACKOFFICE), _RE_ESTADO_INICIAL_BACKOFFICE, _BACKOFFICE,
        "o estado inicial do modo",
    )
    aviso = _correr_no_node(
        "\n".join([
            _decisao_solta(),
            "process.stdout.write(JSON.stringify(avisoDoModoNoBackoffice(%s)));" % inicial,
        ]),
        tmp_path,
        "inicial-backoffice.js",
    )
    assert aviso["tom"] == "perigo", (
        "O ecrã do gestor arranca com o estado em %s, e isso lê-se como %r — "
        "uma resposta que ninguém deu." % (inicial, aviso["titulo"])
    )
    assert aviso["titulo"] == "NÃO SABEMOS EM QUE MODO O POS ESTÁ A EMITIR"


@pytest.fixture(scope="module")
def chamadas_do_backoffice(tmp_path_factory):
    """TODAS as exportações do `lib/faturacao.js`, chamadas de verdade com o
    axios fabricado à frente — devolve, por função, o que cada pedido levou.

    O JWT é posto DEPOIS do import de propósito: é essa a ordem real (o
    `AuthContext` só o põe quando a sessão abre) e é a única que apanha uma
    instância de axios que copiou uns `defaults` ainda vazios."""
    cenario = "\n".join([
        "const faturacao = carregar(path.join(RAIZ, 'lib', 'faturacao.js'));",
        "axiosFalso.defaults.headers.common.Authorization = 'Bearer JWT-POSTO-DEPOIS';",
        "(async () => {",
        "  const saida = {};",
        "  for (const nome of Object.keys(faturacao)) {",
        "    if (typeof faturacao[nome] !== 'function') continue;",
        # O servidor fabricado não conhece nenhuma destas rotas e responde 404
        # a todas — não interessa: o que se está a medir é o que o pedido
        # LEVOU, e isso já ficou registado antes de a resposta existir.
        "    const antes = pedidos.length;",
        "    try { await faturacao[nome]('ID-1', { campo: 1 }, { campo: 2 }); }",
        "    catch (e) { /* 404 do servidor fabricado */ }",
        "    saida[nome] = pedidos.slice(antes).map((p) => ({",
        "      url: p.url,",
        "      timeout: p.timeout === undefined ? null : p.timeout,",
        "      autorizacao: p.headers.Authorization || null,",
        "    }));",
        "  }",
        "  process.stdout.write(JSON.stringify(saida));",
        "})().catch((e) => { console.error(e); process.exit(3); });",
    ])
    return _montar_no_node(
        cenario, tmp_path_factory.mktemp("chamadas"), "chamadas-backoffice.js"
    )


def _pedidos_do_backoffice(chamadas):
    return [(nome, pedido) for nome, lista in chamadas.items() for pedido in lista]


def test_nenhuma_chamada_do_backoffice_espera_PARA_SEMPRE(chamadas_do_backoffice):
    """Sem `timeout`, o axios espera para sempre — e um ecrã preso no estado
    inicial não tem nada que o diga a quem está a olhar para ele.

    Chamam-se todas, e não a do modo, porque foi assim que isto começou: a do
    modo era só a que se viu."""
    todos = _pedidos_do_backoffice(chamadas_do_backoffice)
    assert len(todos) >= 40, (
        "Só %d chamadas do lib/faturacao.js chegaram a sair. Ou o ficheiro "
        "encolheu, ou este guarda deixou de as saber chamar — e um guarda que "
        "não chama nada fica verde por não medir nada." % len(todos)
    )
    sem_tecto = [(nome, p["url"]) for nome, p in todos if not p["timeout"]]
    assert not sem_tecto, (
        "%d chamadas do backoffice saem sem tecto de espera. Uma delas "
        "pendurada deixa o ecrã no estado inicial para sempre: %r"
        % (len(sem_tecto), sem_tecto[:5])
    )


def test_as_chamadas_do_backoffice_levam_o_JWT_posto_DEPOIS_do_import(
    chamadas_do_backoffice,
):
    """A armadilha do `axios.create()`: os `defaults` são COPIADOS no instante
    da criação e nunca mais relidos (medido no axios 1.18.1 deste repositório).

    Um ficheiro que passe a ter a sua própria instância — para lhe pôr o
    `timeout`, por exemplo — deixa de ver o `Authorization` que o
    `AuthContext` põe no login, e o backoffice inteiro passa a responder 401
    sem que nada disto o note. O JWT é posto aqui DEPOIS do import."""
    todos = _pedidos_do_backoffice(chamadas_do_backoffice)
    sem_jwt = [(nome, p["url"]) for nome, p in todos
               if p["autorizacao"] != "Bearer JWT-POSTO-DEPOIS"]
    assert not sem_jwt, (
        "%d chamadas do backoffice saem sem o JWT de gestão que o login pôs: %r"
        % (len(sem_jwt), sem_jwt[:5])
    )
