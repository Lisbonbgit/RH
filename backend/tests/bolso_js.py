"""Correr JavaScript do frontend em Node, a partir do pytest.

Não há jest a correr neste repositório: o JavaScript do ecrã testa-se a partir da suite do
backend, em Node, com o código VERDADEIRO dos ficheiros (nunca uma cópia escrita no teste —
uma cópia ficava verde com o ecrã errado). É a técnica de
`tests/faturacao/test_a_faixa_do_modo_no_ecra.py`, posta num sítio só para o calendário e
para a Fase 3 (Face ID) a reusarem.

O guião corre dentro de uma função `async` e tem à mão:

- `importar('lib/calendario')` — um módulo de `frontend/src`, transformado pelo babel (JSX
  e `import`), com o alias `@/` resolvido como no build;
- `devolve(valor)` — o que o Python recebe (JSON; chamar UMA vez);
- `React` e `REGISTO` (uma lista onde os módulos simulados apontam o que lhes pedem);
- com `dom=True`: um DOM (jsdom) e `montar(elemento)`, `esperar()`, `clicar(el)`,
  `escrever(el, valor)`, `botao(rotulo)`, `texto()` e `pararRelogio(ano, mes, dia, h, m)`.

`simulados` troca módulos inteiros, pelo nome com que são importados, por uma expressão
JavaScript. O `lucide-react` vem sempre simulado (cada ícone é um `<i data-icone>`).
"""
import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional

import pytest

RAIZ = Path(__file__).resolve().parents[2]
FRONTEND = RAIZ / "frontend"
SRC = FRONTEND / "src"

# O axios trocado por um servidor fabricado: cada pedido fica em `REGISTO` como
# [verbo, url, corpo, params] e a resposta vem de `global.SERVIDOR(método, url, corpo, params)`,
# que o guião define. Se a resposta trouxer `erro`, o pedido falha com esse objecto (ex.:
# `{ erro: { response: { status: 409, data: { detail: '…' } } } }`). As instâncias de
# `axios.create()` — a do `lib/bolso.js` — passam por aqui com o código delas intacto.
AXIOS_FABRICADO = r"""(() => {
  const instancia = () => {
    const inst = { interceptors: { request: { use: () => {} }, response: { use: () => {} } } };
    for (const metodo of ['get', 'post', 'put', 'delete', 'patch']) {
      inst[metodo] = async (url, a, b) => {
        const semCorpo = metodo === 'get' || metodo === 'delete';
        const corpo = semCorpo ? null : (a === undefined ? null : a);
        const params = ((semCorpo ? a : b) || {}).params || null;
        REGISTO.push([metodo.toUpperCase(), url, corpo, params]);
        const resposta = global.SERVIDOR(metodo.toUpperCase(), url, corpo, params || {});
        if (resposta && resposta.erro) throw resposta.erro;
        return { data: resposta };
      };
    }
    return inst;
  };
  return Object.assign(instancia(), { create: instancia, defaults: { headers: { common: {} } } });
})()"""

# A sessão e a navegação, ESTÁVEIS entre renders (um `useNavigate` que devolvesse uma função
# nova a cada render punha os `useEffect` que dependem dele a correr sem fim).
SESSAO_SIMULADA = {
    "react-router-dom": "(() => { const navegar = (para) => REGISTO.push(['navigate', para]);"
                        " return { useNavigate: () => navegar }; })()",
    "@/contexts/AuthContext": "(() => { const sessao = { logout: () => REGISTO.push(['logout']),"
                              " user: { name: 'Débora Ferreira' } }; return { useAuth: () => sessao }; })()",
}


def _node() -> str:
    caminho = shutil.which("node")
    if caminho:
        return caminho
    candidato = Path.home() / ".local" / "node" / "bin" / "node"
    if candidato.exists():
        return str(candidato)
    pytest.skip("Sem `node` (nem no PATH nem em ~/.local/node/bin): este JavaScript NÃO foi testado.")


_DOM = r"""
const { JSDOM } = require('jsdom');
const dom = new JSDOM('<!doctype html><html><head></head><body></body></html>',
  { url: 'http://localhost/', pretendToBeVisual: true });
global.window = dom.window;
global.document = dom.window.document;
for (const chave of Object.getOwnPropertyNames(dom.window)) {
  if (!(chave in global)) { try { global[chave] = dom.window[chave]; } catch (e) { /* só de leitura */ } }
}
// O Node já traz alguns destes, e os dele não servem: o jsdom recusa o `Event` do Node
// («parameter 1 is not of type 'Event'» — medido com o Sheet do Radix), o `localStorage` do
// Node é um getter experimental que devolve `undefined` sem `--localstorage-file`, e
// `global.navigator = …` não pega a partir do Node 21. Ficam os do jsdom, por definição.
for (const chave of ['Event', 'CustomEvent', 'EventTarget', 'navigator', 'localStorage', 'sessionStorage']) {
  Object.defineProperty(global, chave, { value: dom.window[chave], configurable: true, writable: true });
}
global.IS_REACT_ACT_ENVIRONMENT = true;
"""

_CARREGADOR = r"""
const fs = require('fs');
const path = require('path');
const Module = require('module');
const babel = require('@babel/core');
const React = require('react');
const SRC = %(src)s;
const REGISTO = [];
const SIMULADOS = {
  'lucide-react': new Proxy({}, { get: (_, nome) => (
    typeof nome === 'string' && nome !== '__esModule'
      ? (props) => React.createElement('i', { 'data-icone': nome, className: props && props.className })
      : undefined) }),
};
function resolver(base) {
  for (const fim of ['', '.js', '.jsx', '/index.js']) {
    const f = base + fim;
    if (fs.existsSync(f) && fs.statSync(f).isFile()) return f;
  }
  throw new Error('Não encontrei ' + base);
}
const cache = new Map();
function carregar(ficheiro) {
  if (cache.has(ficheiro)) return cache.get(ficheiro).exports;
  const codigo = babel.transformSync(fs.readFileSync(ficheiro, 'utf-8'), {
    presets: [[require.resolve('@babel/preset-react'), { runtime: 'classic' }]],
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    filename: ficheiro, babelrc: false, configFile: false,
  }).code;
  const m = new Module(ficheiro, null);
  m.filename = ficheiro;
  m.paths = Module._nodeModulePaths(path.dirname(ficheiro));
  cache.set(ficheiro, m);
  const original = m.require.bind(m);
  m.require = (pedido) => {
    if (Object.prototype.hasOwnProperty.call(SIMULADOS, pedido)) return SIMULADOS[pedido];
    if (pedido.startsWith('@/')) return carregar(resolver(path.join(SRC, pedido.slice(2))));
    if (pedido.startsWith('.')) return carregar(resolver(path.join(path.dirname(ficheiro), pedido)));
    return original(pedido);
  };
  m._compile(codigo, ficheiro);
  return m.exports;
}
const importar = (relativo) => carregar(resolver(path.join(SRC, relativo)));
const devolve = (valor) => process.stdout.write(JSON.stringify(valor === undefined ? null : valor));
"""

_MONTAGEM = r"""
const { act } = require('react');
const { createRoot } = require('react-dom/client');
async function montar(elemento) {
  const caixa = document.createElement('div');
  document.body.appendChild(caixa);
  const raiz = createRoot(caixa);
  await act(async () => { raiz.render(elemento); });
  return raiz;
}
async function esperar() {
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}
async function clicar(el) {
  if (!el) throw new Error('clicar: não encontrei o elemento');
  await act(async () => { el.dispatchEvent(new window.MouseEvent('click', { bubbles: true })); });
}
async function escrever(el, valor) {
  if (!el) throw new Error('escrever: não encontrei o elemento');
  const proto = el.tagName === 'SELECT' ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, valor);
  await act(async () => {
    el.dispatchEvent(new window.Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }));
  });
}
const texto = () => document.body.textContent;
// O botão pelo texto (exacto, sem espaços à volta) ou pelo aria-label.
const botao = (rotulo, dentro = document) => [...dentro.querySelectorAll('button')].find(
  (b) => b.textContent.trim() === rotulo || b.getAttribute('aria-label') === rotulo);
const DataReal = Date;
function pararRelogio(ano, mes, dia, hora = 12, minuto = 0) {
  const fixo = new DataReal(ano, mes - 1, dia, hora, minuto).getTime();
  class DataParada extends DataReal {
    constructor(...a) { if (a.length) super(...a); else super(fixo); }
    static now() { return fixo; }
  }
  global.Date = DataParada;
  window.Date = DataParada;
}
"""


def correr_js(guiao: str, tmp_path: Path, simulados: Optional[Dict[str, str]] = None, dom: bool = False):
    """Corre `guiao` em Node e devolve o que ele passou a `devolve()`. Um erro no JavaScript
    (ou qualquer linha no stderr) falha o teste com a mensagem do Node."""
    if not (FRONTEND / "node_modules" / "@babel" / "core").exists():
        pytest.skip("Sem frontend/node_modules (ln -sfn ~/Developer/RH/frontend/node_modules "
                    "frontend/node_modules): este JavaScript NÃO foi testado.")
    partes = [_DOM if dom else "", _CARREGADOR % {"src": json.dumps(str(SRC))}, _MONTAGEM if dom else ""]
    partes += ["SIMULADOS[%s] = %s;" % (json.dumps(nome), expressao) for nome, expressao in (simulados or {}).items()]
    partes.append(
        "(async () => {\n%s\n})().catch((e) => {\n"
        "  console.error((e && e.stack) || e);\n"
        "  if (e && e.errors) e.errors.forEach((x) => console.error((x && x.stack) || x));\n"
        "  process.exit(1);\n});" % guiao)
    ficheiro = tmp_path / "guiao.js"
    ficheiro.write_text("\n".join(partes), encoding="utf-8")
    resultado = subprocess.run(
        [_node(), str(ficheiro)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(FRONTEND),
        env={"NODE_PATH": str(FRONTEND / "node_modules"), "PATH": "/usr/bin:/bin", "TZ": "Europe/Lisbon"},
        timeout=180)
    # O stderr conta mesmo com saída 0: é lá que o React deixa as excepções dos handlers (que
    # apanha e não relança) e os avisos de act(). Ignorá-lo deixava os testes negativos verdes.
    if resultado.returncode != 0 or resultado.stderr.strip():
        pytest.fail("O JavaScript não correu (ou escreveu no stderr):\n%s"
                    % resultado.stderr.decode("utf-8", "replace"))
    saida = resultado.stdout.decode("utf-8")
    return json.loads(saida) if saida else None
