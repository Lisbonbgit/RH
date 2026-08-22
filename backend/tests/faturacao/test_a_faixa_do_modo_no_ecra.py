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
ficheiro e ficar verde com a decisão desligada por trás deles. Aqui há dois
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


# --- Onde a faixa aparece -----------------------------------------------------


def test_a_faixa_esta_montada_nas_duas_barras_do_pos():
    """A barra de cima do POS é a mesma em toda a sessão de trabalho — com a
    caixa aberta (`PosMenuCaixa`) e com ela fechada (`TopoSimples`, dentro do
    `PosApp`). A faixa vive lá dentro, e não numa linha por cima: assim não
    tira um pixel à área de trabalho.

    Este guarda é textual e sabe-se pouco valioso — é por isso que os de cima
    existem. Serve só para a faixa não ficar montada num sítio só e o outro
    ecrã passar o dia sem ela."""
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


def test_o_ecra_do_backoffice_le_o_modo_com_o_jwt_de_gestao():
    """E pela rota do backoffice, nunca pela do POS: a do POS pede o token do
    dispositivo, que o browser do gestor não tem — o painel caía no terceiro
    estado para sempre, sem ninguém perceber porquê."""
    ecra = _ler(_RAIZ / "frontend" / "src" / "pages" / "admin" / "faturacao" / "FatModoDeEmissao.js")
    assert "getModoDeEmissaoDoBackoffice" in ecra
    assert "estadoDoModoLido" in ecra
    assert "/pos/" not in ecra

    dashboard = _ler(
        _RAIZ / "frontend" / "src" / "pages" / "admin" / "faturacao" / "FatDashboard.js"
    )
    assert "<FatModoDeEmissao" in dashboard
