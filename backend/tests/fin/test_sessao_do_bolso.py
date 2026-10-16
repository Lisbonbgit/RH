"""Face ID e sessão da app «Gestão Lisbonb» — CORRIDOS em Node, com o iPhone simulado.

O que se guarda aqui é o desenho de 2026-10-14, secção 5 (testes 10 e 11):
cancelar o Face ID fecha a porta; dois 401 dão UMA re-entrada; só o 401 do
login apaga o Keychain (429 e rede não); o «não» fica lembrado; Terminar sessão
apaga o Keychain e o 401 não; sem a peça nativa nada muda.

**Como corre.** Cada teste escreve um guião de Node que carrega os ficheiros
REAIS de `frontend/src` (o Babel transforma-os à entrada, o `@/` resolve-se como
no build) e troca UM só módulo: o `@capacitor/core`, cujo `registerPlugin`
devolve o `NB` daqui — uma peça nativa de mentira com o Keychain numa variável
e um registo de chamadas. O axios é o verdadeiro, com o `adapter` trocado (o
servidor fabricado). Os ecrãs montam-se num jsdom com o React verdadeiro.

Nunca uma cópia do código do site: uma cópia ficava verde com o site errado.
"""
import json
import subprocess
from pathlib import Path

import pytest

from ..bolso_js import _node

_RAIZ = Path(__file__).resolve().parents[3]
_FRONTEND = _RAIZ / "frontend"
# `resolve()`: o Node compara caminhos REAIS. Se a pasta viesse por um atalho,
# nenhum ficheiro passava pelo Babel — e o Node recente carrega-os na mesma, como
# módulos ES, com o `@capacitor/core` VERDADEIRO: o simulado ficava de fora sem
# um erro. É também por isso que se contam as consultas ao simulado.
_SRC = (_FRONTEND / "src").resolve()

# A peça nativa de mentira. `NB.rosto` decide o que o Face ID responde:
# 'certo' passa; 'cancela' (16) e 'errado' (10) recusam; 'sistema' (15) é o
# iOS a interromper; 'espera' fica pendurado até `NB.soltar()`.
_PLUGIN = r"""
global.NB = {
  presente: true, disponivel: true, rosto: 'certo', keychain: null, chamadas: [],
  async isAvailable() {
    this.chamadas.push('isAvailable');
    return { isAvailable: this.disponivel, biometryType: 2 };
  },
  async verifyIdentity(o) {
    this.chamadas.push('verifyIdentity:' + JSON.stringify(o));
    if (this.rosto === 'espera') { await new Promise((soltar) => { this.soltar = soltar; }); return; }
    const codigos = { cancela: '16', errado: '10', sistema: '15' };
    if (this.rosto !== 'certo') { const e = new Error('nao'); e.code = codigos[this.rosto]; throw e; }
  },
  async setCredentials(c) { this.chamadas.push('setCredentials'); this.keychain = c; },
  async getCredentials(o) {
    this.chamadas.push('getCredentials');
    if (!this.keychain || this.keychain.server !== o.server) throw new Error('No password');
    return { username: this.keychain.username, password: this.keychain.password };
  },
  // Como o iOS: sem o `server` certo não se apaga nada (o Keychain fica).
  async deleteCredentials(o) {
    this.chamadas.push('deleteCredentials');
    if ((o || {}).server !== 'gestao.lisbonb.com') throw new Error('No server');
    this.keychain = null;
  },
};
"""

_CAPACITOR_SIMULADO = r"""
global.CONSULTAS_AO_CAPACITOR = 0;
module.exports = {
  Capacitor: {
    isPluginAvailable: (nome) => {
      global.CONSULTAS_AO_CAPACITOR += 1;
      return nome === 'NativeBiometric' && global.NB.presente;
    },
    isNativePlatform: () => global.NB.presente,
    getPlatform: () => (global.NB.presente ? 'ios' : 'web'),
  },
  registerPlugin: () => global.NB,
};
"""

_CARREGADOR = r"""
const fs = require('fs');
const path = require('path');
const Module = require('module');
const babel = require('@babel/core');
const RAIZ = %(raiz)s;
const SIMULADOS = %(simulados)s;
process.env.REACT_APP_BACKEND_URL = '';
const resolver = Module._resolveFilename;
Module._resolveFilename = function (pedido, pai, ...resto) {
  if (SIMULADOS[pedido]) return SIMULADOS[pedido];
  if (pedido.startsWith('@/')) pedido = path.join(RAIZ, pedido.slice(2));
  return resolver.call(this, pedido, pai, ...resto);
};
const carregarJs = Module._extensions['.js'];
const compilar = function (m, ficheiro) {
  if (!ficheiro.startsWith(RAIZ)) return carregarJs(m, ficheiro);
  const codigo = babel.transformSync(fs.readFileSync(ficheiro, 'utf-8'), {
    presets: [[require.resolve('@babel/preset-react'), { runtime: 'classic' }]],
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    filename: ficheiro, babelrc: false, configFile: false,
  }).code;
  m._compile(codigo, ficheiro);
};
Module._extensions['.js'] = compilar;
Module._extensions['.jsx'] = compilar;
const lib = (nome) => require(path.join(RAIZ, nome));
"""

# Para os ecrãs: um jsdom a fazer de browser, com `document.hidden` na mão
# (`esconder(true)` = a app foi para segundo plano).
_DOM = r"""
const { JSDOM } = require('jsdom');
const dom = new JSDOM('<!doctype html><html><body><div id="raiz"></div></body></html>',
  { url: 'http://localhost/bolso', pretendToBeVisual: true });
global.window = dom.window;
// O que o React e o Radix procuram no global (MutationObserver,
// getComputedStyle, HTMLElement…): o que o Node não tem vem do jsdom.
for (const nome of Object.getOwnPropertyNames(dom.window)) {
  if (nome in globalThis) continue;
  const v = dom.window[nome];
  globalThis[nome] = typeof v === 'function' && !/^[A-Z]/.test(nome) ? v.bind(dom.window) : v;
}
// O Node recente traz `navigator`, `localStorage`, `Event` e `CustomEvent`
// seus, e a atribuição simples não pega (memória
// «node-navigator-nao-se-substitui»); um `CustomEvent` do Node num `document`
// do jsdom rebenta o Radix. Redefinem-se.
for (const nome of ['navigator', 'localStorage', 'sessionStorage', 'Event', 'CustomEvent', 'EventTarget']) {
  Object.defineProperty(globalThis, nome, { configurable: true, value: dom.window[nome] });
}
global.IS_REACT_ACT_ENVIRONMENT = true;
// O jsdom 16 não tem `showModal`: aqui basta o `open`.
dom.window.HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
let escondido = false;
Object.defineProperty(dom.window.document, 'hidden', { configurable: true, get: () => escondido });
global.esconder = (sim) => {
  escondido = sim;
  dom.window.document.dispatchEvent(new dom.window.Event('visibilitychange'));
};
const React = require('react');
const { act } = require('react');
const { createRoot } = require('react-dom/client');
"""

_SEM_DOM = r"""
const memoria = {};
Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
  getItem: (k) => (k in memoria ? memoria[k] : null),
  setItem: (k, v) => { memoria[k] = String(v); },
  removeItem: (k) => { delete memoria[k]; },
} });
"""

# O relógio na mão: o `Date.now` de todos os módulos passa a ser `AGORA`.
_RELOGIO = "global.AGORA = 1700000000000; Date.now = () => global.AGORA;"

# A Carol activou o Face ID neste iPhone.
_LIGADO = (
    "localStorage.setItem('faceid_email', 'carol@lisbonb.com');"
    " NB.keychain = { username: 'carol@lisbonb.com', password: 'segredo',"
    " server: 'gestao.lisbonb.com' };"
)


def _corre(cenario: str, tmp_path: Path, dom: bool = False, antes: str = ""):
    # Duplica parte do `tests/bolso_js.py` (Babel, jsdom, stderr que falha) DE
    # PROPÓSITO nesta fase: as Tarefas 2 a 7 assentam neste `_corre` tal como está.
    # Unifica-se com o `correr_js` depois da Fase 3.
    """Corre `cenario` (corpo de uma função async; o `return` é o resultado, em
    JSON) depois de `antes` (que corre ANTES de qualquer módulo do site ser
    carregado — é aí que se prepara o localStorage e o NB)."""
    if not (_FRONTEND / "node_modules" / "@babel" / "core").exists():
        pytest.skip(
            "Sem frontend/node_modules: ln -sfn ~/Developer/RH/frontend/node_modules "
            "frontend/node_modules"
        )
    simulado = tmp_path / "capacitor_core.js"
    simulado.write_text(_CAPACITOR_SIMULADO, encoding="utf-8")
    guiao = "\n".join([
        _CARREGADOR % {
            "raiz": json.dumps(str(_SRC)),
            "simulados": json.dumps({"@capacitor/core": str(simulado)}),
        },
        _DOM if dom else _SEM_DOM,
        _PLUGIN,
        antes,
        "(async () => {",
        cenario,
        # Sair pela mão: um temporizador pendurado (do React, do jsdom) não
        # pode prender o processo. Sai-se só DEPOIS de o stdout escrever.
        # O stderr também se esvazia antes de sair: é ele que o Python lê para falhar.
        "})().then(",
        "  (r) => process.stdout.write(JSON.stringify(r === undefined ? null : r),",
        "    () => process.stderr.write('', () => process.exit(0))),",
        "  (e) => {",
        "    console.error((e && e.stack) || e, (e && e.errors || []).map((x) => x.stack).join('\\n'));",
        "    process.exit(1);",
        "  });",
    ])
    ficheiro = tmp_path / "cenario.js"
    ficheiro.write_text(guiao, encoding="utf-8")
    r = subprocess.run(
        [_node(), str(ficheiro)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(_FRONTEND),
        timeout=30,
        # Como o `tests/bolso_js.py`: o browserslist avisa no stderr quando a base do
        # caniuse-lite faz 6 meses, e o stderr falha o teste — calado aqui.
        env={"NODE_PATH": str(_FRONTEND / "node_modules"), "PATH": "/usr/bin:/bin",
             "TZ": "Europe/Lisbon", "BROWSERSLIST_IGNORE_OLD_DATA": "1"},
    )
    # O stderr conta mesmo com saída 0: é lá que o React deixa as excepções dos
    # handlers (apanha-as e não as relança). Sem isto um teste negativo («a
    # barreira não abriu») ficava verde com o ecrã a rebentar.
    if r.returncode != 0 or r.stderr.strip():
        pytest.fail("O JavaScript não correu (ou escreveu no stderr):\n%s"
                    % r.stderr.decode("utf-8", "replace"))
    return json.loads(r.stdout.decode("utf-8"))


# --- o próprio _corre --------------------------------------------------------------


def test_uma_excepcao_num_clique_do_react_falha_o_teste(tmp_path):
    """O React apanha a excepção do handler e só a escreve no stderr: o Node sai com 0."""
    with pytest.raises(pytest.fail.Exception, match="handler rebentou"):
        _corre("""
          const caixa = document.getElementById('raiz');
          const raiz = createRoot(caixa);
          await act(async () => { raiz.render(React.createElement('button',
            { onClick: () => { throw new Error('handler rebentou'); } }, 'Ir')); });
          await act(async () => {
            caixa.querySelector('button').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
          });
          return 'continuou';
        """, tmp_path, dom=True)


def test_o_aviso_da_base_do_browserslist_nao_falha_o_teste(tmp_path):
    """Com o relógio em 2027 a base do caniuse-lite tem mais de 6 meses e o
    browserslist avisa no stderr ao primeiro ficheiro que o Babel transforma.
    (Ele mede com `new Date()`, não com `Date.now`: troca-se a classe.)"""
    r = _corre("return lib('lib/faceid').JANELA_MS;", tmp_path, antes=(
        "const DataReal = Date; global.Date = class extends DataReal {"
        " constructor(...a) { super(...(a.length ? a : [2027, 5, 1])); } };"))
    assert r == 60000


# --- lib/faceid.js ---------------------------------------------------------------


def test_sem_plugin_o_faceid_diz_que_nao_e_nao_toca_na_peca(tmp_path):
    """Browser, build 2 da casca, app do ponto: tudo «não», nada rebenta."""
    r = _corre("""
      const f = lib('lib/faceid');
      const r = {
        tem: await f.temFaceId(), ligado: f.faceIdLigado(), verificar: await f.verificar(),
        ler: await f.ler(), guardar: await f.guardar('carol@lisbonb.com', 'x'),
      };
      await f.apagar();
      return { ...r, email: localStorage.getItem('faceid_email'), chamadas: NB.chamadas,
               consultouOSimulado: CONSULTAS_AO_CAPACITOR > 0 };
    """, tmp_path, antes="NB.presente = false; localStorage.setItem('faceid_email', 'carol@lisbonb.com');")
    assert r == {"tem": False, "ligado": False, "verificar": False, "ler": None,
                 "guardar": False, "email": None, "chamadas": [], "consultouOSimulado": True}


def test_ler_so_depois_do_face_id_e_so_com_biometria(tmp_path):
    """A versão 6 do plugin NÃO prende a senha ao Face ID: quem a prende é o
    `ler()`. Cancelado ou interrompido o rosto, o Keychain nem é tocado."""
    r = _corre("""
      const f = lib('lib/faceid');
      NB.rosto = 'cancela';
      const cancelado = await f.ler();
      NB.rosto = 'sistema';
      const interrompido = await f.ler();
      const tocouNoKeychain = NB.chamadas.includes('getCredentials');
      NB.rosto = 'certo';
      const lido = await f.ler();
      const pedido = NB.chamadas.filter((c) => c.startsWith('verifyIdentity')).pop();
      return { cancelado, interrompido, tocouNoKeychain, lido, pedido };
    """, tmp_path, antes=_LIGADO)
    assert r["cancelado"] is None
    # Interrompido pelo iOS (`null`) também não é rosto: a porta fica fechada.
    assert r["interrompido"] is None
    assert r["tocouNoKeychain"] is False
    assert r["lido"] == {"email": "carol@lisbonb.com", "senha": "segredo"}
    assert '"useFallback":false' in r["pedido"]


def test_verificar_distingue_recusa_de_interrupcao_e_um_rosto_vale_60_segundos(tmp_path):
    r = _corre("""
      const f = lib('lib/faceid');
      const r = {};
      for (const rosto of ['cancela', 'errado', 'sistema']) { NB.rosto = rosto; r[rosto] = await f.verificar(); }
      NB.rosto = 'certo'; r.certo = await f.verificar();
      NB.rosto = 'cancela';
      AGORA += 59 * 1000; r.aos59s = await f.verificar();
      AGORA += 2 * 1000; r.aos61s = await f.verificar();
      return r;
    """, tmp_path, antes=_RELOGIO)
    assert r == {"cancela": False, "errado": False, "sistema": None, "certo": True,
                 "aos59s": True, "aos61s": False}


def test_com_o_relogio_a_recuar_o_rosto_pede_se_outra_vez(tmp_path):
    """Acerto da hora (ou mudança à mão para trás): a diferença fica negativa,
    menor que 60 s, e o rosto antigo passava a valer até o relógio o alcançar."""
    r = _corre("""
      const f = lib('lib/faceid');
      await f.verificar();
      NB.rosto = 'cancela';
      AGORA -= 10 * 60 * 1000;
      return await f.verificar();
    """, tmp_path, antes=_RELOGIO)
    assert r is False


def test_guardar_e_apagar_mexem_no_keychain_e_no_email(tmp_path):
    r = _corre("""
      const f = lib('lib/faceid');
      const guardou = await f.guardar('carol@lisbonb.com', 'segredo');
      const depois = { keychain: NB.keychain, email: f.emailGuardado(), ligado: f.faceIdLigado() };
      await f.apagar();
      return { guardou, depois,
               apagado: { keychain: NB.keychain, email: f.emailGuardado(), ligado: f.faceIdLigado() } };
    """, tmp_path)
    assert r == {
        "guardou": True,
        "depois": {"keychain": {"username": "carol@lisbonb.com", "password": "segredo",
                                "server": "gestao.lisbonb.com"},
                   "email": "carol@lisbonb.com", "ligado": True},
        "apagado": {"keychain": None, "email": None, "ligado": False},
    }


def test_guardar_sem_conseguir_escrever_o_email_nao_deixa_a_senha_no_keychain(tmp_path):
    """Sem o `faceid_email` o site dá o Face ID por desligado (`faceIdLigado()`
    falso) e nunca usa essa senha: ficava órfã no Keychain."""
    r = _corre("""
      const f = lib('lib/faceid');
      const guardou = await f.guardar('carol@lisbonb.com', 'segredo');
      return { guardou, keychain: NB.keychain, chamadas: NB.chamadas };
    """, tmp_path, antes="localStorage.setItem = () => { throw new Error('QuotaExceededError'); };")
    assert r == {"guardou": False, "keychain": None,
                 "chamadas": ["setCredentials", "deleteCredentials"]}


def test_dois_rostos_pedidos_ao_mesmo_tempo_sao_um_pedido_ao_iphone(tmp_path):
    """No ensaio (`craco start`) o `<React.StrictMode>` do `index.js` monta a
    Barreira duas vezes: dois `verificar()` ao mesmo tempo. Dois pedidos ao iPhone
    podiam cancelar-se um ao outro (um logout falso) ou pedir o rosto duas vezes."""
    r = _corre("""
      const f = lib('lib/faceid');
      const r = await Promise.all([f.verificar(), f.verificar()]);
      return { r, rostos: NB.chamadas.filter((c) => c.startsWith('verifyIdentity')).length };
    """, tmp_path)
    assert r == {"r": [True, True], "rostos": 1}
