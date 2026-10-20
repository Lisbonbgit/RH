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

import jwt
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


# --- lib/sessao.js ---------------------------------------------------------------


def _token(email):
    """Um token com a forma do `create_token` do server.py (o browser só lê o
    corpo; a assinatura não conta). O `x` obriga o corpo a ter `-` e `_` do
    base64url: um `atob` que não os trocasse por `+` e `/` rebentava."""
    corpo = {"user_id": "u-" + email.split("@")[0], "email": email, "role": "gerente",
             "employee_id": None, "must_change_password": False,
             "iat": 1700000000, "exp": 1700086400, "x": "???>>>"}
    t = jwt.encode(corpo, "segredo-dos-testes-com-mais-de-32-bytes", algorithm="HS256")
    assert "-" in t.split(".")[1] and "_" in t.split(".")[1]
    return t


def _sessao(email):
    """A sessão aberta no browser é a de `email` (o token no localStorage)."""
    return "localStorage.setItem('token', %s);" % json.dumps(_token(email))


# A sessão aberta é a da Carol, a mesma que ligou o Face ID (decisão 1A do dono:
# o Face ID só actua sobre a conta que o ligou).
_SESSAO_DA_CAROL = _sessao("carol@lisbonb.com")


def test_sem_plugin_a_sessao_nao_fecha_nem_reentra_nem_pergunta(tmp_path):
    r = _corre("""
      const s = lib('lib/sessao');
      let logins = 0;
      s.ligarEntrada(async () => { logins += 1; });
      return {
        fechadaAoCarregar: s.barreiraFechada(), fechou: s.fecharBarreira(),
        fechada: s.barreiraFechada(), saiu: localStorage.getItem('saiuAs'),
        reentrou: await s.reentrar(), logins,
        depois: await s.depoisDoLoginComSenha('carol@lisbonb.com', 'x'), chamadas: NB.chamadas,
      };
    """, tmp_path, antes="NB.presente = false;" + _LIGADO + _SESSAO_DA_CAROL)
    assert r == {"fechadaAoCarregar": False, "fechou": False, "fechada": False, "saiu": None,
                 "reentrou": False, "logins": 0, "depois": "nada", "chamadas": []}


def test_dois_401_ao_mesmo_tempo_dao_uma_so_reentrada(tmp_path):
    r = _corre("""
      const s = lib('lib/sessao');
      const logins = [];
      s.ligarEntrada(async (email, senha) => {
        logins.push([email, senha]);
        await new Promise((r) => setTimeout(r, 10));
      });
      const [a, b] = await Promise.all([s.reentrar(), s.reentrar()]);
      const rostos = NB.chamadas.filter((c) => c.startsWith('verifyIdentity')).length;
      const depois = await s.reentrar();   // acabada a primeira, a próxima tenta de novo
      return { a, b, depois, logins, rostos };
    """, tmp_path, antes=_LIGADO + _SESSAO_DA_CAROL)
    assert r == {"a": True, "b": True, "depois": True, "rostos": 1,
                 "logins": [["carol@lisbonb.com", "segredo"], ["carol@lisbonb.com", "segredo"]]}


@pytest.mark.parametrize("estado,apaga", [(401, True), (429, False), (None, False)])
def test_so_o_401_do_login_apaga_o_keychain(tmp_path, estado, apaga):
    """401 = a senha guardada já não é a certa. 429 (limite de tentativas) e
    a rede em baixo (`None`: erro sem resposta) não dizem nada da senha."""
    r = _corre("""
      const s = lib('lib/sessao');
      const estado = %s;
      s.ligarEntrada(async () => {
        const e = new Error('falhou');
        if (estado) e.response = { status: estado };
        throw e;
      });
      const ok = await s.reentrar();
      return { ok, keychain: NB.keychain !== null, email: localStorage.getItem('faceid_email') };
    """ % json.dumps(estado), tmp_path, antes=_LIGADO + _SESSAO_DA_CAROL)
    assert r["ok"] is False
    assert r["keychain"] is (not apaga)
    assert (r["email"] is None) is apaga


def test_cancelar_o_face_id_na_reentrada_nao_entra_e_guarda_o_keychain(tmp_path):
    r = _corre("""
      const s = lib('lib/sessao');
      let logins = 0;
      s.ligarEntrada(async () => { logins += 1; });
      NB.rosto = 'cancela';
      return { ok: await s.reentrar(), logins, keychain: NB.keychain !== null };
    """, tmp_path, antes=_LIGADO + _SESSAO_DA_CAROL)
    assert r == {"ok": False, "logins": 0, "keychain": True}


@pytest.mark.parametrize("saiu_ha_ms,fechada", [
    (None, True),                 # sem `saiuAs`: conta como arranque
    (5 * 60 * 1000, False),       # voltou aos 5 minutos certos: não pede
    (5 * 60 * 1000 + 1, True),    # passou dos 5 minutos: pede
    (-1, True),                   # `saiuAs` no futuro (relógio a recuar): pede
])
def test_ao_carregar_a_barreira_fecha_se_nao_voltou_a_tempo(tmp_path, saiu_ha_ms, fechada):
    antes = _RELOGIO + _LIGADO + _SESSAO_DA_CAROL
    if saiu_ha_ms is not None:
        antes += "localStorage.setItem('saiuAs', String(AGORA - %d));" % saiu_ha_ms
    r = _corre("return lib('lib/sessao').barreiraFechada();", tmp_path, antes=antes)
    assert r is fechada


def test_esconder_com_a_barreira_aberta_grava_a_hora_e_fecha(tmp_path):
    """`saiuAs` é a hora a que se saiu de uma sessão ABERTA. Esconder com a barreira
    ainda fechada (o rosto por passar) não é sair: se gravasse, voltar logo a seguir
    contava como «voltou a tempo» e a barreira abria sem ninguém ter passado o rosto."""
    r = _corre("""
      const s = lib('lib/sessao');
      // Sem `saiuAs` = arranque: a barreira começa fechada.
      const fechadaNaoGrava = { fechou: s.fecharBarreira(AGORA - 1000), saiu: localStorage.getItem('saiuAs') };
      s.abrirBarreira();
      const fechou = s.fecharBarreira();
      return { fechadaNaoGrava, fechou, fechada: s.barreiraFechada(), saiu: localStorage.getItem('saiuAs'),
               aos5: s.voltouATempo(AGORA + 5 * 60 * 1000),
               depois: s.voltouATempo(AGORA + 5 * 60 * 1000 + 1) };
    """, tmp_path, antes=_RELOGIO + _LIGADO + _SESSAO_DA_CAROL)
    assert r == {"fechadaNaoGrava": {"fechou": True, "saiu": None},
                 "fechou": True, "fechada": True, "saiu": "1700000000000",
                 "aos5": True, "depois": False}


def test_os_pedidos_esperam_que_a_barreira_abra(tmp_path):
    r = _corre("""
      const s = lib('lib/sessao');
      let passou = false;
      s.esperarBarreira().then(() => { passou = true; });
      await new Promise((r) => setTimeout(r, 20));
      const antes = passou;
      s.abrirBarreira();
      await new Promise((r) => setTimeout(r, 0));
      return { antes, depois: passou };
    """, tmp_path, antes=_LIGADO + _SESSAO_DA_CAROL)
    assert r == {"antes": False, "depois": True}


def test_o_nao_fica_lembrado_por_email(tmp_path):
    r = _corre("""
      const s = lib('lib/sessao');
      const primeira = await s.depoisDoLoginComSenha('debora@lisbonb.com', 'x');
      s.recusar('debora@lisbonb.com');
      const segunda = await s.depoisDoLoginComSenha('debora@lisbonb.com', 'x');
      const outraPessoa = await s.depoisDoLoginComSenha('carol@lisbonb.com', 'y');
      s.esquecerRecusa('debora@lisbonb.com');
      const mudouDeIdeias = await s.depoisDoLoginComSenha('debora@lisbonb.com', 'x');
      return { primeira, segunda, outraPessoa, mudouDeIdeias };
    """, tmp_path)
    assert r == {"primeira": "perguntar", "segunda": "nada", "outraPessoa": "perguntar",
                 "mudouDeIdeias": "perguntar"}


def test_quem_ja_tem_face_id_nao_e_perguntado_e_a_senha_nova_substitui_a_guardada(tmp_path):
    r = _corre("""
      const s = lib('lib/sessao');
      const resposta = await s.depoisDoLoginComSenha('carol@lisbonb.com', 'senha-nova');
      return { resposta, keychain: NB.keychain };
    """, tmp_path, antes=_LIGADO)
    assert r == {"resposta": "nada", "keychain": {"username": "carol@lisbonb.com",
                 "password": "senha-nova", "server": "gestao.lisbonb.com"}}


def test_ligar_o_face_id_so_guarda_depois_de_o_rosto_passar(tmp_path):
    r = _corre("""
      const s = lib('lib/sessao');
      NB.rosto = 'cancela';
      const cancelado = await s.ligarFaceId('carol@lisbonb.com', 'segredo');
      const nada = { keychain: NB.keychain, email: localStorage.getItem('faceid_email') };
      NB.rosto = 'certo';
      const ligado = await s.ligarFaceId('carol@lisbonb.com', 'segredo');
      return { cancelado, nada, ligado, email: localStorage.getItem('faceid_email') };
    """, tmp_path)
    assert r == {"cancelado": False, "nada": {"keychain": None, "email": None},
                 "ligado": True, "email": "carol@lisbonb.com"}


# --- decisão 1A do dono (2026-10-15): o Face ID só actua sobre a conta que o ligou ---
#
# Dois gestores no mesmo iPhone: a sessão aberta é a da Débora e o Face ID é o da
# Carol (a última que o ligou).


# Uma sessão VIVA de quem não é dona do Face ID: saiu agora mesmo e voltou (sem
# isto, o arranque a frio já lhe tinha tirado o token — decisão A).
_VOLTOU_AGORA = "localStorage.setItem('saiuAs', String(AGORA));"


@pytest.mark.parametrize("sessao,com_token", [
    # a Débora voltou a tempo: o token dela sobrevive ao carregar (decisão A) e é
    # ele que expira às 24 h
    (_RELOGIO + _sessao("debora@lisbonb.com") + _VOLTOU_AGORA, True),
    ("", False),                                          # sem sessão nenhuma
    ("localStorage.setItem('token', 'velho');", True),    # token ilegível
], ids=["sessao-de-outra-conta", "sem-sessao", "token-ilegivel"])
def test_a_reentrada_so_usa_o_keychain_da_conta_cuja_sessao_expirou(tmp_path, sessao, com_token):
    """Com a sessão da Débora expirada, entrar com a senha da Carol punha a conta
    da Carol (e as empresas dela) por baixo dos ecrãs da Débora, sem o dizer. Sem
    sessão, ou com um token que não se lê, não se sabe de quem era: login normal.
    Nem se pede o rosto (`chamadas` vazio): não há nada a fazer com ele."""
    r = _corre("""
      const s = lib('lib/sessao');
      let logins = 0;
      s.ligarEntrada(async () => { logins += 1; });
      const token = localStorage.getItem('token') !== null;
      return { ok: await s.reentrar(), logins, chamadas: NB.chamadas, token };
    """, tmp_path, antes=_LIGADO + sessao)
    # `token`: a sessão da Débora tem de estar viva; sem ela o caso fica igual a
    # «sem-sessao» e já não prende a guarda da 1A.
    assert r == {"ok": False, "logins": 0, "chamadas": [], "token": com_token}


def test_esconder_com_a_sessao_de_outra_conta_nao_fecha_a_barreira_mas_grava_a_hora(tmp_path):
    """Senão a Débora, ao voltar, via «Entrar como carol@…» por cima dos números
    dela — e o rosto da Carol abria a sessão da Débora. A hora grava-se: é ela que
    decide, ao voltar, se a Débora volta à senha (decisão A)."""
    r = _corre("""
      const s = lib('lib/sessao');
      s.abrirBarreira();
      return { fechou: s.fecharBarreira(), fechada: s.barreiraFechada(),
               saiu: localStorage.getItem('saiuAs') };
    """, tmp_path, antes=_RELOGIO + _LIGADO + _sessao("debora@lisbonb.com")
       + "localStorage.setItem('saiuAs', String(AGORA - 1000));")
    assert r == {"fechou": False, "fechada": False, "saiu": "1700000000000"}


# --- decisão A do dono (2026-10-17): a sessão de outra conta volta à senha ---------

@pytest.mark.parametrize("saiu_ha_ms,fica", [
    (None, False),                # arranque a frio: volta à senha
    (5 * 60 * 1000, True),        # voltou a tempo (o iOS matou a WebView): fica
    (5 * 60 * 1000 + 1, False),   # passou dos 5 minutos: volta à senha
])
def test_ao_carregar_a_sessao_de_outra_conta_volta_a_senha(tmp_path, saiu_ha_ms, fica):
    """Onde a Carol teria a barreira, a Débora perde a sessão: o AuthContext lê o
    token DEPOIS de o `lib/sessao` carregar e, sem ele, mostra o login. Nunca há
    barreira por cima dela (o rosto da Carol não abre a sessão da Débora)."""
    antes = _RELOGIO + _LIGADO + _sessao("debora@lisbonb.com")
    if saiu_ha_ms is not None:
        antes += "localStorage.setItem('saiuAs', String(AGORA - %d));" % saiu_ha_ms
    r = _corre("""
      const s = lib('lib/sessao');
      return { fechada: s.barreiraFechada(), token: localStorage.getItem('token') !== null };
    """, tmp_path, antes=antes)
    assert r == {"fechada": False, "token": fica}


@pytest.mark.parametrize("sessao,sai", [
    (_sessao("debora@lisbonb.com"), True),
    (_SESSAO_DA_CAROL, False),     # a dona do Face ID tem a barreira, não a senha
    ("", False),                   # sem sessão não há nada de que sair
], ids=["outra-conta", "dona-do-face-id", "sem-sessao"])
def test_ao_voltar_depois_de_5_minutos_so_a_sessao_de_outra_conta_tem_de_sair(tmp_path, sessao, sai):
    r = _corre("""
      const s = lib('lib/sessao');
      s.abrirBarreira();
      s.fecharBarreira();
      return { aos5: s.outraContaTemDeSair(AGORA + 5 * 60 * 1000),
               depois: s.outraContaTemDeSair(AGORA + 5 * 60 * 1000 + 1) };
    """, tmp_path, antes=_RELOGIO + _LIGADO + sessao + _VOLTOU_AGORA)
    assert r == {"aos5": False, "depois": sai}


def test_sem_plugin_a_sessao_de_outra_conta_nao_sai(tmp_path):
    """No browser e na build 2 não há Face ID de ninguém: tudo como hoje."""
    r = _corre("""
      const s = lib('lib/sessao');
      return { sai: s.outraContaTemDeSair(), token: localStorage.getItem('token') !== null };
    """, tmp_path, antes="NB.presente = false;" + _RELOGIO + _LIGADO + _sessao("debora@lisbonb.com"))
    assert r == {"sai": False, "token": True}


def test_com_a_peca_mas_sem_face_id_ligado_a_sessao_fica_como_hoje(tmp_path):
    """O caso mais comum da build 3: a peça existe, ninguém ligou o Face ID (disse
    «Não», ou ainda não lho perguntaram) e há uma sessão aberta. Sem dono do Face
    ID não há «outra conta»: o arranque não lhe tira o token, esconder não fecha
    nem grava `saiuAs`, e voltar não a manda para a senha. Sem isto, trocar o
    `faceIdLigado()` do `sessaoDeOutraConta` por `pluginPresente()` deixava esta
    gente sem sessão a cada arranque — e a suite verde (os outros casos com a peça
    põem todos `_LIGADO`)."""
    r = _corre("""
      const s = lib('lib/sessao');
      const token = localStorage.getItem('token') !== null;
      const fechadaAoCarregar = s.barreiraFechada();
      const fechou = s.fecharBarreira();
      return { fechada: fechadaAoCarregar, token, fechou,
               saiu: localStorage.getItem('saiuAs'), sai: s.outraContaTemDeSair() };
    """, tmp_path, antes=_RELOGIO + _sessao("debora@lisbonb.com"))
    assert r == {"fechada": False, "token": True, "fechou": False, "saiu": None, "sai": False}


def test_com_um_atob_que_exige_o_igual_a_sessao_le_se_na_mesma(tmp_path):
    """O corpo do token vem sem o `=` do fim (base64url). O `atob` do Node e o do
    jsdom aceitam-no assim; motores mais antigos não. Aqui o `atob` é estrito: sem
    o `=` reposto a sessão não se lia, e a barreira nunca fechava ao esconder."""
    assert len(_token("carol@lisbonb.com").split(".")[1]) % 4   # precisa mesmo do `=`
    r = _corre("""
      const s = lib('lib/sessao');
      s.abrirBarreira();
      return s.fecharBarreira();
    """, tmp_path, antes=_RELOGIO + _LIGADO + _SESSAO_DA_CAROL + """
      const atobSolto = atob;
      Object.defineProperty(globalThis, 'atob', { configurable: true, value: (s) => {
        if (s.length % 4) throw new Error('InvalidCharacterError');
        return atobSolto(s);
      } });
    """)
    assert r is True


# --- lib/bolso.js: o cliente de todos os ecrãs do bolso ------------------------

# Um servidor de mentira à frente do axios VERDADEIRO (o `adapter` é a última
# peça antes da rede: os interceptores correm todos). `RESPOSTAS['GET /bolso/painel']`
# é `[estado, corpo]`, uma fila `[[estado, corpo], …]` ou `'rede'` (sem resposta).
_SERVIDOR = r"""
const axios = require('axios');
global.RESPOSTAS = {};
global.PEDIDOS = [];
global.CABECALHOS = [];
axios.defaults.adapter = async (config) => {
  const caminho = ((config.baseURL || '') + config.url).replace(/^.*\/api/, '');
  const chave = config.method.toUpperCase() + ' ' + caminho;
  PEDIDOS.push(chave);
  CABECALHOS.push(config.headers && config.headers.Authorization || null);
  const fila = RESPOSTAS[chave];
  const r = Array.isArray(fila) && Array.isArray(fila[0]) ? fila.shift() : fila;
  if (r === 'rede' || !r) { const e = new Error('Network Error'); e.config = config; throw e; }
  const [status, data] = r;
  if (status >= 400) {
    const e = new Error('HTTP ' + status); e.config = config; e.response = { status, data }; throw e;
  }
  return { data, status, statusText: 'OK', headers: {}, config };
};
"""


def test_bolso_401_reentra_e_repete_o_pedido_com_o_token_novo(tmp_path):
    r = _corre("""
      const s = lib('lib/sessao');
      s.abrirBarreira();
      s.ligarEntrada(async () => { localStorage.setItem('token', 'novo'); });
      const { data } = await lib('lib/bolso').getPainel('all');
      return { data, pedidos: PEDIDOS, cabecalhos: CABECALHOS };
    """, tmp_path, antes=_SERVIDOR + _LIGADO + _SESSAO_DA_CAROL + r"""
      RESPOSTAS['GET /bolso/painel'] = [[401, {}], [200, { ok: true }]];
    """)
    assert r == {"data": {"ok": True}, "pedidos": ["GET /bolso/painel", "GET /bolso/painel"],
                 "cabecalhos": ["Bearer " + _token("carol@lisbonb.com"), "Bearer novo"]}


def test_bolso_401_depois_de_reentrar_nao_volta_a_tentar(tmp_path):
    """Repete UMA vez. Sem isto, um 401 que se repete era um ciclo sem fim."""
    r = _corre("""
      const s = lib('lib/sessao');
      s.abrirBarreira();
      let logins = 0;
      s.ligarEntrada(async () => { logins += 1; });
      let estado = null;
      try { await lib('lib/bolso').getPainel('all'); } catch (e) { estado = e.response.status; }
      return { pedidos: PEDIDOS.length, logins, estado };
    """, tmp_path, antes=_SERVIDOR + _LIGADO + _SESSAO_DA_CAROL
       + "RESPOSTAS['GET /bolso/painel'] = [401, {}];")
    assert r == {"pedidos": 2, "logins": 1, "estado": 401}


def test_bolso_sem_face_id_o_401_chega_ao_ecra_como_sempre(tmp_path):
    r = _corre("""
      let estado = null;
      try { await lib('lib/bolso').getPainel('all'); } catch (e) { estado = e.response.status; }
      return { pedidos: PEDIDOS.length, estado, chamadas: NB.chamadas };
    """, tmp_path, antes=_SERVIDOR + "NB.presente = false; RESPOSTAS['GET /bolso/painel'] = [401, {}];")
    assert r == {"pedidos": 1, "estado": 401, "chamadas": []}


def test_bolso_com_a_barreira_fechada_nenhum_pedido_sai(tmp_path):
    r = _corre("""
      const s = lib('lib/sessao');
      const pedido = lib('lib/bolso').getPainel('all');
      await new Promise((r) => setTimeout(r, 20));
      const antes = PEDIDOS.length;
      s.abrirBarreira();
      await pedido;
      return { antes, depois: PEDIDOS.length };
    """, tmp_path, antes=_SERVIDOR + _LIGADO + _SESSAO_DA_CAROL
       + "RESPOSTAS['GET /bolso/painel'] = [200, {}];")
    assert r == {"antes": 0, "depois": 1}


# --- AuthContext: o arranque, a re-entrada e o Terminar sessão ------------------

_EU = '{"id": "u1", "email": "carol@lisbonb.com", "role": "admin", "name": "Carol"}'

# `espera(ms)` deixa correr os efeitos e as promessas dentro do `act`.
_ESPERA = """
const espera = (ms = 0) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });
const texto = () => document.body.textContent;
"""

# O AuthProvider VERDADEIRO, com um espião que guarda o que o contexto expõe.
_ESPIAO = r"""
      const { AuthProvider, useAuth } = lib('contexts/AuthContext');
      let auth = null;
      // Cada render fica no histórico: [email, semLigacao, loading].
      const historico = [];
      const Espiao = () => {
        auth = useAuth();
        historico.push([auth.user && auth.user.email, auth.semLigacao, auth.loading]);
        return null;
      };
      const raiz = createRoot(document.getElementById('raiz'));
      await act(async () => {
        raiz.render(React.createElement(AuthProvider, null, React.createElement(Espiao)));
      });
      await espera(50);
      const estado = () => ({ user: auth.user && auth.user.email, semLigacao: auth.semLigacao,
                              loading: auth.loading, token: localStorage.getItem('token') });
"""

# O `/auth/me` sem resposta deixa de propósito uma linha no stderr (o AuthContext
# regista o pedido que falhou), e o `_corre` falha qualquer stderr. Nos testes que
# a provocam cala-se SÓ essa linha: qualquer outra continua a falhar o teste.
_SEM_LIGACAO_ESPERADO = r"""
const erroDaConsola = console.error;
console.error = (...a) => {
  if (!String(a[0]).startsWith('Não foi possível confirmar a sessão')) erroDaConsola(...a);
};
"""


@pytest.mark.parametrize("falha", ["[502, {}]", "'rede'"])
def test_arranque_sem_resposta_do_servidor_e_sem_ligacao_e_nao_login(tmp_path, falha):
    """`rede` leva ~3 s: são as três tentativas (1 s + 2 s) que já existiam."""
    r = _corre(_ESPIAO + """
      await espera(3200);
      return estado();
    """, tmp_path, dom=True, antes=_SERVIDOR + _ESPERA + _SEM_LIGACAO_ESPERADO + r"""
      localStorage.setItem('token', 't');
      RESPOSTAS['GET /auth/me'] = %s;
    """ % falha)
    assert r == {"user": None, "semLigacao": True, "loading": False, "token": "t"}


def test_tentar_de_novo_volta_a_perguntar_e_entra(tmp_path):
    r = _corre(_ESPIAO + """
      const antes = estado();
      RESPOSTAS['GET /auth/me'] = [200, %s];
      historico.length = 0;
      await act(async () => { auth.tentarDeNovo(); });
      await espera(50);
      return { antes, depois: estado(), renders: historico };
    """ % _EU, tmp_path, dom=True, antes=_SERVIDOR + _ESPERA + _SEM_LIGACAO_ESPERADO + r"""
      localStorage.setItem('token', 't');
      RESPOSTAS['GET /auth/me'] = [502, {}];
    """)
    assert r["antes"]["semLigacao"] is True
    assert r["depois"] == {"user": "carol@lisbonb.com", "semLigacao": False, "loading": False,
                           "token": "t"}
    # Entre o toque e a resposta NUNCA pode haver «sem user, com ligação, sem
    # loading»: o ProtectedRoute mandava para o /login a cada tentativa.
    assert r["renders"] and [None, False, False] not in r["renders"]


def test_sem_ligacao_com_a_barreira_fechada_o_tentar_de_novo_nao_espera_por_ela(tmp_path):
    """O «Sem ligação» aparece no lugar dos ecrãs, por isso sem a Barreira montada:
    o `/auth/me` do AuthContext não passa pelo `esperarBarreira` do `lib/bolso`, e
    o «tentar de novo» entra com a barreira ainda fechada (é a Barreira, depois,
    que pede o rosto)."""
    r = _corre(_ESPIAO + """
      const s = lib('lib/sessao');
      const antes = { ...estado(), barreira: s.barreiraFechada() };
      RESPOSTAS['GET /auth/me'] = [200, %s];
      await act(async () => { auth.tentarDeNovo(); });
      await espera(50);
      return { antes: [antes.semLigacao, antes.barreira],
               depois: [estado().user, estado().semLigacao, s.barreiraFechada()],
               pedidos: PEDIDOS };
    """ % _EU, tmp_path, dom=True, antes=_SERVIDOR + _ESPERA + _SEM_LIGACAO_ESPERADO + _LIGADO + _SESSAO_DA_CAROL
       + r"""
      RESPOSTAS['GET /auth/me'] = [502, {}];
    """)
    assert r == {"antes": [True, True], "depois": ["carol@lisbonb.com", False, True],
                 "pedidos": ["GET /auth/me", "GET /auth/me"]}


def test_arranque_com_a_sessao_expirada_e_face_id_reentra_sem_login(tmp_path):
    # A sessão expirada é a da Carol (token com a forma do servidor): a re-entrada
    # só usa o Keychain da conta cuja sessão expirou (decisão 1A).
    r = _corre(_ESPIAO + """
      await espera(50);
      return { ...estado(), pedidos: PEDIDOS, barreira: lib('lib/sessao').barreiraFechada() };
    """, tmp_path, dom=True, antes=_SERVIDOR + _ESPERA + _LIGADO + _SESSAO_DA_CAROL + r"""
      RESPOSTAS['GET /auth/me'] = [[401, {}], [200, %s]];
      RESPOSTAS['POST /auth/login'] = [200, { token: 'novo', user: %s }];
    """ % (_EU, _EU))
    # A re-entrada já fez o Face ID: entra-se, e a barreira fica aberta (um rosto só).
    assert r == {"user": "carol@lisbonb.com", "semLigacao": False, "loading": False,
                 "token": "novo", "barreira": False,
                 "pedidos": ["GET /auth/me", "POST /auth/login", "GET /auth/me"]}


def test_arranque_com_a_sessao_expirada_sem_face_id_vai_para_o_login(tmp_path):
    r = _corre(_ESPIAO + """
      return { ...estado(), pedidos: PEDIDOS };
    """, tmp_path, dom=True, antes=_SERVIDOR + _ESPERA + r"""
      localStorage.setItem('token', 'velho');
      RESPOSTAS['GET /auth/me'] = [401, {}];
    """)
    assert r == {"user": None, "semLigacao": False, "loading": False, "token": None,
                 "pedidos": ["GET /auth/me"]}


def test_terminar_sessao_apaga_o_keychain_e_o_logout_nao(tmp_path):
    r = _corre(_ESPIAO + """
      await act(async () => { auth.logout(); });
      const depoisDoLogout = { keychain: NB.keychain !== null, email: localStorage.getItem('faceid_email') };
      localStorage.setItem('token', 't');
      await act(async () => { auth.terminarSessao(); });
      await espera();
      return { depoisDoLogout, ...estado(), keychain: NB.keychain,
               email: localStorage.getItem('faceid_email') };
    """, tmp_path, dom=True, antes=_SERVIDOR + _ESPERA + _LIGADO + r"""
      localStorage.setItem('token', 't');
      RESPOSTAS['GET /auth/me'] = [200, %s];
    """ % _EU)
    assert r == {"depoisDoLogout": {"keychain": True, "email": "carol@lisbonb.com"},
                 "user": None, "semLigacao": False, "loading": False, "token": None,
                 "keychain": None, "email": None}


def test_entrar_e_sair_limpam_o_aviso_de_ligacao(tmp_path):
    """Quem passou do «Sem ligação» ao /login e entrou não pode, ao sair mais tarde,
    dar outra vez com um «Sem ligação» que já não é verdade (o `ProtectedRoute`
    mostrava-o em vez do login)."""
    r = _corre(_ESPIAO + """
      const inicio = estado().semLigacao;
      RESPOSTAS['GET /auth/me'] = [200, %s];
      await act(async () => { await auth.login('carol@lisbonb.com', 'segredo'); });
      await espera(50);
      const depoisDoLogin = estado().semLigacao;
      // Um piscar de rede com a sessão aberta volta a pô-lo de pé…
      RESPOSTAS['GET /auth/me'] = [502, {}];
      await act(async () => { auth.tentarDeNovo(); });
      await espera(50);
      const comSessao = estado();
      // …e o logout (o de um 401, o de Terminar sessão) tem de o esquecer.
      await act(async () => { auth.logout(); });
      return { inicio, depoisDoLogin, comSessao: [comSessao.user, comSessao.semLigacao],
               depoisDoLogout: estado().semLigacao };
    """ % _EU, tmp_path, dom=True, antes=_SERVIDOR + _ESPERA + _SEM_LIGACAO_ESPERADO + r"""
      localStorage.setItem('token', 't');
      RESPOSTAS['GET /auth/me'] = [502, {}];
      RESPOSTAS['POST /auth/login'] = [200, { token: 'novo', user: %s }];
    """ % _EU)
    assert r == {"inicio": True, "depoisDoLogin": False,
                 "comSessao": ["carol@lisbonb.com", True], "depoisDoLogout": False}


@pytest.mark.parametrize("ligado_a,fica", [
    ("carol@lisbonb.com", "senha-nova"),   # o Face ID é desta conta: o Keychain leva a senha nova
    ("debora@lisbonb.com", "segredo"),     # é de outra pessoa neste iPhone: não se lhe mexe
])
def test_mudar_a_senha_leva_a_nova_ao_keychain_so_de_quem_tem_o_face_id(tmp_path, ligado_a, fica):
    """O `/alterar-senha` (senha provisória): sem isto o Keychain ficava com a senha
    antiga, a próxima re-entrada dava 401 e o Face ID perdia-se."""
    r = _corre(_ESPIAO + """
      await act(async () => { await auth.changePassword('segredo', 'senha-nova'); });
      await espera(50);
      return { dono: NB.keychain.username, senha: NB.keychain.password };
    """, tmp_path, dom=True, antes=_SERVIDOR + _ESPERA + r"""
      const dono = %s;
      localStorage.setItem('token', 't');
      localStorage.setItem('faceid_email', dono);
      NB.keychain = { username: dono, password: 'segredo', server: 'gestao.lisbonb.com' };
      RESPOSTAS['GET /auth/me'] = [200, %s];
      RESPOSTAS['POST /auth/change-password'] = [200, { token: 'novo' }];
    """ % (json.dumps(ligado_a), _EU))
    assert r == {"dono": ligado_a, "senha": fica}


# --- LoginPage: «Usar Face ID para entrar?» -------------------------------------

# O login VERDADEIRO dentro de um router, vindo de /bolso/calendario (o
# `state.from` que o ProtectedRoute lá põe). Escreve email e senha e carrega
# em Entrar.
_LOGIN = r"""
      const { AuthProvider } = lib('contexts/AuthContext');
      const LoginPage = lib('pages/LoginPage').default;
      const { MemoryRouter, Routes, Route } = require('react-router-dom');
      const raiz = createRoot(document.getElementById('raiz'));
      const el = React.createElement;
      await act(async () => {
        raiz.render(el(AuthProvider, null,
          el(MemoryRouter, { initialEntries: [{ pathname: '/login', state: { from: '/bolso/calendario' } }] },
            el(Routes, null,
              el(Route, { path: '/login', element: el(LoginPage) }),
              el(Route, { path: '/bolso/calendario', element: el('p', null, 'CALENDARIO') })))));
      });
      await espera();
      const escrever = (id, valor) => {
        const campo = document.getElementById(id);
        Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(campo, valor);
        campo.dispatchEvent(new window.Event('input', { bubbles: true }));
      };
      await act(async () => { escrever('login-email', 'Carol@Lisbonb.com'); escrever('login-password', 'segredo'); });
      await act(async () => { document.querySelector('[data-testid=login-submit-btn]').click(); });
      await espera(20);
      const botao = (nome) => [...document.querySelectorAll('button')].find((b) => b.textContent === nome);
"""

# O servidor devolve o email como está na conta (minúsculas): é ESSE que se guarda.
_LOGIN_OK = r"""
      RESPOSTAS['POST /auth/login'] = [200, { token: 'novo', user: %s }];
      RESPOSTAS['GET /auth/me'] = [200, %s];
""" % (_EU, _EU)


@pytest.mark.parametrize("resposta", ["Agora não", "Usar Face ID"])
def test_depois_da_senha_pergunta_antes_de_sair_do_login(tmp_path, resposta):
    r = _corre(_LOGIN + r"""
      const pergunta = { aberta: texto().includes('Usar Face ID para entrar?'),
                         jaSaiu: texto().includes('CALENDARIO') };
      await act(async () => { botao(%s).click(); });
      await espera(20);
      return { pergunta, saiu: texto().includes('CALENDARIO'),
               recusa: localStorage.getItem('faceid_recusado:carol@lisbonb.com'),
               keychain: NB.keychain, email: localStorage.getItem('faceid_email') };
    """ % json.dumps(resposta), tmp_path, dom=True, antes=_SERVIDOR + _ESPERA + _LOGIN_OK)
    assert r["pergunta"] == {"aberta": True, "jaSaiu": False}
    assert r["saiu"] is True   # e foi para o sítio de onde veio (state.from)
    if resposta == "Agora não":
        assert (r["recusa"], r["keychain"], r["email"]) == ("1", None, None)
    else:
        assert r["recusa"] is None
        assert r["keychain"] == {"username": "carol@lisbonb.com", "password": "segredo",
                                 "server": "gestao.lisbonb.com"}
        assert r["email"] == "carol@lisbonb.com"


def test_sem_plugin_o_login_nao_pergunta_nada(tmp_path):
    r = _corre(_LOGIN + r"""
      return { pergunta: texto().includes('Usar Face ID para entrar?'),
               saiu: texto().includes('CALENDARIO'), chamadas: NB.chamadas };
    """, tmp_path, dom=True, antes=_SERVIDOR + _ESPERA + _LOGIN_OK + "NB.presente = false;")
    assert r == {"pergunta": False, "saiu": True, "chamadas": []}


def test_quem_ja_disse_que_nao_entra_sem_pergunta(tmp_path):
    r = _corre(_LOGIN + r"""
      return { pergunta: texto().includes('Usar Face ID para entrar?'), saiu: texto().includes('CALENDARIO') };
    """, tmp_path, dom=True, antes=_SERVIDOR + _ESPERA + _LOGIN_OK
        + "localStorage.setItem('faceid_recusado:carol@lisbonb.com', '1');")
    assert r == {"pergunta": False, "saiu": True}


_EU_PROVISORIA = ('{"id": "u1", "email": "carol@lisbonb.com", "role": "admin", "name": "Carol",'
                  ' "must_change_password": true}')


def test_com_senha_provisoria_nao_pergunta(tmp_path):
    """A senha provisória vai ser trocada já a seguir (/alterar-senha): guardá-la
    deixava no Keychain uma senha morta. Nem se pergunta ao iPhone se tem Face ID."""
    r = _corre(_LOGIN + r"""
      return { pergunta: texto().includes('Usar Face ID para entrar?'),
               saiu: texto().includes('CALENDARIO'), chamadas: NB.chamadas };
    """, tmp_path, dom=True, antes=_SERVIDOR + _ESPERA + r"""
      RESPOSTAS['POST /auth/login'] = [200, { token: 'novo', user: %s }];
      RESPOSTAS['GET /auth/me'] = [200, %s];
    """ % (_EU_PROVISORIA, _EU_PROVISORIA))
    assert r == {"pergunta": False, "saiu": True, "chamadas": []}
