# Fase 3 — Face ID e as duas correcções do login — Plano de execução

> **Para agentes:** SUB-SKILL OBRIGATÓRIO: usar superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para executar este plano tarefa a tarefa. Os passos usam caixas (- [ ]).

**Objetivo:** Na app «Gestão Lisbonb» (casca iOS), entrar com Face ID em vez da senha diária; no site, mostrar «Sem ligação — tentar de novo» em vez do login quando o servidor não responde ao arranque, e voltar ao ecrã de onde se veio depois de um 401 no bolso.

**Arquitectura:** Tudo o que decide vive em dois módulos puros do site — `lib/faceid.js` (a ponte para a peça nativa `NativeBiometric`, que só existe na casca) e `lib/sessao.js` (barreira de 5 minutos, re-entrada partilhada, «não» lembrado) — testados em Node com o `@capacitor/core` simulado. O `AuthContext` liga-os ao login; o cliente `lib/bolso.js` faz por TODOS os ecrãs do bolso a espera pela barreira e a re-entrada num 401; uma `Barreira` (um `<dialog>` modal) envolve as rotas `/bolso*`. O servidor não muda. Depois de o site estar no ar, a casca `app-bolso/` ganha a peça nativa e sai como build 3 no TestFlight.

**Tecnologia:** React 19 + CRA/craco + Tailwind + shadcn (Radix), axios 1.18, `@capacitor/core` 6.2 (só `registerPlugin`/`isPluginAvailable`), Capacitor 6 iOS + CocoaPods 1.16, `@capgo/capacitor-native-biometric@6.0.4`, Xcode 26.6; testes em pytest (Python 3.9.6 local) que correm Node com Babel e jsdom 16.

## Restrições globais

- Fonte de verdade: `docs/superpowers/specs/2026-10-14-calendario-gestao-design.md`, secção 5 e testes 10, 11, 13 e 14. Não mudar decisões do dono.
- Peça nativa: `@capgo/capacitor-native-biometric@6.0.4`, **versão fixa** (sem `^`), instalada **só** em `app-bolso/`; regista-se como `NativeBiometric`. O site **não** a leva como dependência: usa o `registerPlugin('NativeBiometric')` do `@capacitor/core` 6 que já tem, **sem implementação web**.
- `NSFaceIDUsageDescription` = «Usamos o Face ID para entrar na Gestão Lisbonb sem escrever a senha.»
- Build 3: `CURRENT_PROJECT_VERSION = 3` (as duas configurações); `MARKETING_VERSION` fica `1.0`.
- O site só actua com `Capacitor.isPluginAvailable('NativeBiometric')`: browser, build 2 e a app do ponto ficam como hoje.
- A versão 6 guarda email e senha no Keychain (`kSecClassInternetPassword`, por `server`) **sem os prender ao Face ID**: `verifyIdentity` com `useFallback: false` **antes** de qualquer `getCredentials`.
- Primeiro login com senha → «Usar Face ID para entrar?». Sim → guarda o email **devolvido pelo servidor** e a senha. Não → `faceid_recusado:<email>` no `localStorage`; «Usar Face ID» no menu lateral para quem mudar de ideias.
- Barreira: ao abrir a app e ao voltar depois de **mais de 5 minutos** fora, ecrã opaco «Entrar como <email>» até o Face ID passar. `saiuAs` no `localStorage`, gravado ao esconder; sem ele conta como arranque. Fecha **logo** ao esconder; com ela fechada os dados não se pedem.
- Face ID falhou ou cancelado → `logout()` (apaga o token, **não** o Keychain) e login normal.
- Sessão expirada → **uma só re-entrada partilhada**: Face ID (se a barreira não acabou de o fazer) → Keychain → `POST /auth/login` → grava o token → repete o pedido **uma vez**. Falhou → login normal.
- **Só um 401 do `POST /auth/login` apaga o Keychain.** 429 e rede em baixo mantêm-no.
- Terminar sessão = `terminarSessao()` = `logout()` + apagar o Keychain. O `logout()` dos 401 não apaga o Keychain.
- Dois gestores no mesmo iPhone: fica o último que activou o Face ID; a barreira diz sempre «Entrar como <email>».
- **No servidor não muda nada:** as 24 h ficam; o formato do token não muda (a app do ponto leva o código congelado).
- Sem ligação: o `/auth/me` do arranque a falhar **sem ser 401/403** → `semLigacao` → o `ProtectedRoute` mostra «Sem ligação — tentar de novo». Muda também o portal no browser (é a mesma peça).
- O 401 do bolso leva `state.from`: depois de entrar volta-se ao ecrã de onde se veio.
- Python local 3.9.6 (nada de `X | Y` em anotações, nada de `match`). Correr testes: `cd /Users/matheus.moraes/Developer/RH-calendario/backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest <caminho> -q`; ler **sempre** `passed` **e** `skipped`.
- Antes da primeira corrida: `ln -sfn ~/Developer/RH/frontend/node_modules /Users/matheus.moraes/Developer/RH-calendario/frontend/node_modules` (sem isto os testes de JavaScript saltam em silêncio).
- Não tocar em `~/Developer/RH` (é de outra sessão). Nunca ler nem escrever na base de produção.
- Publicar o site (fluxo B), enviar para o App Store Connect e qualquer passo com a conta Apple do dono: **só depois de um «sim» do dono no chat**.
- Regra da casa: cada teste é visto **vermelho pela razão certa** (prova por mutação) antes de se aceitar o verde.

---

## O que já existe (Fases 1 e 2 feitas) e o que se assume

- `frontend/src/pages/bolso/partilhado.js` com o `MenuLateral` (☰, `Sheet side="left"`): itens **Faturação**, **Calendário** e **Terminar sessão** (Fase 2).
- `frontend/src/pages/bolso/BolsoCalendario.js` e a rota `/bolso/calendario` no `App.js`, irmã de `/bolso` (Fase 2).
- `frontend/src/lib/bolso.js` com a instância `api` do axios e as chamadas do calendário (Fase 2).
- `backend/tests/bolso_js.py` (Fase 2): `correr_js(guiao, tmp_path, simulados=None, dom=False)`, `AXIOS_FABRICADO`, `SESSAO_SIMULADA` (um `useAuth()` de mentira que regista `['logout']`); `backend/tests/calendario/test_menu_do_bolso.py`, que prende o «Terminar sessão» do menu como `[['logout'], ['navigate', '/login']]`; `backend/tests/calendario/test_ecra_do_calendario.py`, cujo `test_sessao_expirada_sai_para_o_login` prende o 401 do `BolsoCalendario` (o `semSessao()` da Fase 2) como `[['logout'], ['navigate', '/login']]`; e `backend/tests/calendario/test_painel_da_ida.py` (o `PainelIda`, montado sem `SESSAO_SIMULADA`). A Tarefa 7 muda os quatro (o «Terminar sessão» passa a `terminarSessao()`; um 401 que chegue a um ecrã passa a ser só `logout()`). Os testes NOVOS desta fase não usam o `correr_js`: precisam do `AuthContext`, do axios e do `react-router-dom` VERDADEIROS (o `SESSAO_SIMULADA` e o `AXIOS_FABRICADO` substituem precisamente as peças que aqui se testam) e de um `@capacitor/core` simulado; o carregador está na Tarefa 1.
- As linhas citadas por número referem-se ao main `57d5f6f`; depois das Fases 1 e 2 podem ter mudado — procura-se sempre pelo texto.

## Mapa de ficheiros

| Ficheiro | Criar/Modificar | Responsabilidade |
|---|---|---|
| `frontend/src/lib/faceid.js` | Criar | Ponte para a peça nativa: `temFaceId`, `verificar` (só biometria, um rosto vale 60 s, um pedido de rosto de cada vez), `ler` (só depois de `verificar`), `guardar`, `apagar`, `emailGuardado`, `faceIdLigado`. Sem a peça, tudo «não». |
| `frontend/src/lib/sessao.js` | Criar | Decisões sem React: a barreira (estado, `saiuAs` só ao sair com ela aberta, 5 min, `esperarBarreira`), a re-entrada partilhada (`reentrar`, `ligarEntrada`), o «não» por email, `depoisDoLoginComSenha`, `ligarFaceId`. |
| `frontend/src/lib/bolso.js` | Modificar | Interceptor de pedido: espera pela barreira. Interceptor de resposta: 401 → `reentrar()` → repete o pedido uma vez. |
| `frontend/src/contexts/AuthContext.js` | Modificar | `semLigacao` + `tentarDeNovo()` (o login e o logout limpam-no); 401 do arranque → `reentrar()`; `login()` abre a barreira e é a porta da re-entrada (`ligarEntrada`); `logout` estável; `terminarSessao()`; `changePassword` leva a senha nova ao Keychain de quem tem o Face ID. |
| `frontend/src/pages/LoginPage.js` | Modificar | Depois de um login com senha na casca, «Usar Face ID para entrar?» (AlertDialog) antes de sair do login; com a senha provisória (`must_change_password`) não pergunta. |
| `frontend/src/pages/bolso/Barreira.js` | Criar | `Barreira` (o `<dialog>` modal «Entrar como <email>», abre/fecha com a visibilidade; sem Face ID possível → `logout()`) e `UsarFaceId` (o item do menu lateral). |
| `frontend/src/App.js` | Modificar | `SemLigacao` («Sem ligação — tentar de novo»), mostrado pelo `ProtectedRoute` e pelo `RoleRedirect` (a rota `/`); `RotaDoBolso` (ProtectedRoute + Barreira) em todas as rotas `/bolso*`. |
| `frontend/src/pages/bolso/BolsoApp.js` | Modificar | 401 → só `logout()` (o `ProtectedRoute` leva o `state.from`); sai o `useNavigate`. |
| `frontend/src/pages/bolso/BolsoCalendario.js` (Fase 2) | Modificar | O `semSessao()` sai: nos 401, só `logout()`; sai o `useNavigate`. |
| `frontend/src/pages/bolso/PainelIda.js` (Fase 2) | Modificar | Um 401 ao gravar ou apagar → `logout()` (era um erro dentro do painel). |
| `frontend/src/pages/bolso/partilhado.js` | Modificar | `MenuLateral`: «Usar Face ID» antes de Terminar sessão; Terminar sessão → `terminarSessao`. |
| `backend/tests/fin/test_sessao_do_bolso.py` | Criar | Os testes 10 e 11 do desenho, corridos em Node (módulos e ecrãs reais, peça nativa simulada). |
| `backend/tests/fin/test_casca_do_bolso.py` | Criar | Guarda da casca: versão fixa da peça, texto do Face ID, build 3, `server.url` de produção. |
| `backend/tests/bolso_js.py` (Fase 2) | Modificar | `SESSAO_SIMULADA` ganha `terminarSessao`. |
| `backend/tests/calendario/test_menu_do_bolso.py` (Fase 2) | Modificar | «Terminar sessão» passa a esperar `[['terminarSessao']]`. |
| `backend/tests/calendario/test_ecra_do_calendario.py` (Fase 2) | Modificar | O 401 do calendário passa a esperar `[['logout']]` (o teste muda de nome). |
| `backend/tests/calendario/test_painel_da_ida.py` (Fase 2) | Modificar | Monta o painel com o `SESSAO_SIMULADA`; teste novo do 401 ao gravar e ao apagar. |
| `app-bolso/package.json`, `app-bolso/package-lock.json` | Modificar | `@capgo/capacitor-native-biometric` `6.0.4` exacto. |
| `app-bolso/ios/App/Podfile`, `app-bolso/ios/App/Podfile.lock` | Modificar (pelo `npx cap sync ios`) | O pod `CapgoCapacitorNativeBiometric`. |
| `app-bolso/ios/App/App/Info.plist` | Modificar | `NSFaceIDUsageDescription`. |
| `app-bolso/ios/App/App.xcodeproj/project.pbxproj` | Modificar | `CURRENT_PROJECT_VERSION = 3`. |
| `/Users/matheus.moraes/Library/CloudStorage/OneDrive-Pessoal/Claude/.claude/launch.json` | Modificar (fora do repositório) | Entradas `rh-calendario-f3-api` e `rh-calendario-f3-web` para o ensaio local (Tarefa 8; a Tarefa 11 reusa-as). |

## Como as peças conversam (para quem não conhece o código)

```
arranque da casca ──► AuthProvider.fetchUser ──► GET /auth/me
                         ├─ 200 ─────────────► user ──► RotaDoBolso ──► Barreira ──► BolsoApp / BolsoCalendario
                         ├─ 401 ─► sessao.reentrar() ─► faceid.ler() (Face ID) ─► login() ─► abre a barreira
                         │            └─ falhou ─► logout() ─► ProtectedRoute ─► /login (state.from)
                         ├─ 403 ─► logout()
                         └─ outro / sem rede ─► semLigacao ─► «Sem ligação — tentar de novo»

pedido de um ecrã do bolso ─► lib/bolso.js
   ├─ pedido: await esperarBarreira()            (barreira fechada = o pedido espera)
   └─ resposta 401: await reentrar() ─► repete UMA vez; senão o 401 chega ao ecrã ─► logout()
```

A casca (`app-bolso/`) carrega `https://rh.lisbonb.com/bolso`: o site chega à app sem build nova. Só a peça nativa, o texto do Face ID e o número da build exigem a build 3.

---

### Tarefa 1: `lib/faceid.js` — a ponte para a peça nativa

A peça nativa só existe dentro da casca. Este módulo é o ÚNICO sítio do site que lhe fala, e a regra que mais importa está nele: a versão 6 do plugin devolve a senha do Keychain sem pedir nada, por isso `ler()` só lê depois de `verificar()` passar.

**Ficheiros:**
- Criar: `frontend/src/lib/faceid.js`
- Criar: `backend/tests/fin/test_sessao_do_bolso.py` (o carregador de Node + os testes desta tarefa; as Tarefas 2 a 7 acrescentam-lhe testes no fim)
- Testes: `backend/tests/fin/test_sessao_do_bolso.py`

**Interfaces:**
- Consome: `Capacitor.isPluginAvailable(nome: string): boolean` e `registerPlugin(nome: string)` de `@capacitor/core` 6.2; `_node() -> str` de `backend/tests/faturacao/test_arredondamento_do_ecra.py` (já existe).
- Produz (`frontend/src/lib/faceid.js`, usado pelas Tarefas 2, 4, 5 e 6):
  - `JANELA_MS: number` = `60000` — um rosto vale 60 s;
  - `pluginPresente(): boolean`;
  - `emailGuardado(): string | null` — `localStorage['faceid_email']`;
  - `faceIdLigado(): boolean` — `pluginPresente() && !!emailGuardado()`;
  - `temFaceId(): Promise<boolean>` — peça presente e `isAvailable({useFallback:false}).isAvailable === true`;
  - `verificar(): Promise<true | false | null>` — `true` passou (ou passou há menos de `JANELA_MS`); `false` falhou/cancelou; `null` interrompido pelo sistema (códigos `'11'`, `'13'`, `'15'`); dois `verificar()` ao mesmo tempo partilham UM pedido de rosto;
  - `ler(): Promise<{ email: string, senha: string } | null>` — só depois de `verificar() === true`;
  - `guardar(email: string, senha: string): Promise<boolean>` — Keychain + `faceid_email`;
  - `apagar(): Promise<void>` — Keychain + `faceid_email`;
  - Keychain: `server = 'gestao.lisbonb.com'`.
- Produz (Python, em `test_sessao_do_bolso.py`, usado pelas Tarefas 2 a 7): `_corre(cenario: str, tmp_path: Path, dom: bool = False, antes: str = "") -> object`, `_SRC: Path`, `_LIGADO: str` (a Carol com Face ID ligado), `_RELOGIO: str` (`Date.now()` = `AGORA`). Dentro do guião: `lib(nome)`, `NB` (peça simulada: `presente`, `disponivel`, `rosto` ∈ `certo|cancela|errado|sistema|espera`, `keychain`, `chamadas`, `soltar()`), `AGORA`, `CONSULTAS_AO_CAPACITOR`; com `dom=True` também `React`, `act`, `createRoot`, `esconder(sim)`.

- [ ] **Passo 1: Preparar o `node_modules` e confirmar o Babel**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
[ -e frontend/node_modules ] || ln -s ~/Developer/RH/frontend/node_modules frontend/node_modules
ls frontend/node_modules/@babel/core/package.json frontend/node_modules/jsdom/package.json
```

Esperado: os dois caminhos impressos, sem «No such file». (O `[ -e … ] ||` não mexe num `node_modules` que já lá esteja — a Tarefa 8 pode trocar o atalho por uma instalação própria.)

Registar a linha de base da suite inteira, ANTES de mexer em código (a Tarefa 7 compara com ela):

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest -q 2>&1 | tail -3
```

Anotar `N passed, M skipped` (e `failed`, se houver — esses já vinham das Fases 1/2 e não são desta fase; dizê-lo ao dono antes de continuar).

- [ ] **Passo 2: Escrever o teste que falha**

Criar `backend/tests/fin/test_sessao_do_bolso.py` com exactamente isto:

```python
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

from ..faturacao.test_arredondamento_do_ecra import _node

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
  async deleteCredentials() { this.chamadas.push('deleteCredentials'); this.keychain = null; },
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
        "})().then(",
        "  (r) => process.stdout.write(JSON.stringify(r === undefined ? null : r), () => process.exit(0)),",
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
        env={"NODE_PATH": str(_FRONTEND / "node_modules"), "PATH": "/usr/bin:/bin"},
    )
    if r.returncode != 0:
        pytest.fail("O JavaScript não correu:\n%s" % r.stderr.decode("utf-8", "replace"))
    return json.loads(r.stdout.decode("utf-8"))


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
    `ler()`. Cancelado o rosto, o Keychain nem é tocado."""
    r = _corre("""
      const f = lib('lib/faceid');
      NB.rosto = 'cancela';
      const cancelado = await f.ler();
      const tocouNoKeychain = NB.chamadas.includes('getCredentials');
      NB.rosto = 'certo';
      const lido = await f.ler();
      const pedido = NB.chamadas.filter((c) => c.startsWith('verifyIdentity')).pop();
      return { cancelado, tocouNoKeychain, lido, pedido };
    """, tmp_path, antes=_LIGADO)
    assert r["cancelado"] is None
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
```

- [ ] **Passo 3: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/fin/test_sessao_do_bolso.py -q
```

Esperado: `5 failed`, cada um com `Error: Cannot find module '…/frontend/src/lib/faceid'`. Se aparecer `skipped`, o Passo 1 não pegou — parar e corrigir.

- [ ] **Passo 4: Implementação mínima**

Criar `frontend/src/lib/faceid.js`:

```javascript
// Face ID da app «Gestão Lisbonb» — a ponte para a peça nativa da casca.
//
// A peça é o `@capgo/capacitor-native-biometric@6.0.4`, instalada SÓ na casca
// (`app-bolso/`). O site não a leva como dependência: regista-a pelo nome com o
// `registerPlugin` do `@capacitor/core` que já tem. **Sem implementação web de
// propósito** — com uma, o `isPluginAvailable` dava `true` no browser.
//
// **A versão 6 guarda a senha no Keychain SEM a prender ao Face ID**: o
// `getCredentials` devolve-a sem pedir nada. Quem garante o Face ID é este
// ficheiro: `ler()` só lê depois de `verificar()` passar. Nunca chamar o
// `getCredentials` por outro caminho.
//
// Nada aqui rebenta: sem a peça (browser, build 2 da casca, app do ponto) tudo
// devolve «não» e o resto do site fica como estava.
import { Capacitor, registerPlugin } from '@capacitor/core';

const NOME = 'NativeBiometric';
const NativeBiometric = registerPlugin(NOME);

// O `server` do Keychain (kSecAttrServer). Fixo: é a chave da gaveta, não um endereço.
const SERVIDOR = 'gestao.lisbonb.com';
// Quem activou o Face ID neste telemóvel. Serve para a barreira dizer «Entrar
// como …» SEM ler o Keychain antes do Face ID.
const CHAVE_EMAIL = 'faceid_email';

// A barreira e a re-entrada podem pedir o Face ID com segundos de diferença
// (arranque com a sessão expirada): um rosto vale este tempo, e não se pede outro.
export const JANELA_MS = 60 * 1000;
let verificadoAs = 0;

// Códigos do plugin (BiometricAuthError) que NÃO são a pessoa a recusar: a app
// a perder o primeiro plano, o sistema a interromper. Não terminam a sessão.
const INTERROMPIDO = ['11', '13', '15'];

// Um pedido de rosto de cada vez: um `verificar()` que chegue enquanto outro
// corre partilha-o (o `<React.StrictMode>` do `craco start` monta a Barreira
// duas vezes). Dois pedidos seguidos ao iPhone podiam cancelar-se um ao outro.
let emVerificacao = null;

export const pluginPresente = () => Capacitor.isPluginAvailable(NOME);

export const emailGuardado = () => {
  try { return localStorage.getItem(CHAVE_EMAIL); } catch (e) { return null; }
};

// Ligado = a peça existe E alguém activou o Face ID neste telemóvel. Síncrono.
export const faceIdLigado = () => pluginPresente() && !!emailGuardado();

// O telemóvel consegue fazer Face ID agora (tem a peça, o rosto registado e a licença dada).
export async function temFaceId() {
  if (!pluginPresente()) return false;
  try {
    const r = await NativeBiometric.isAvailable({ useFallback: false });
    return r?.isAvailable === true;
  } catch (e) {
    return false;
  }
}

// true = passou · false = falhou ou a pessoa cancelou · null = interrompido pelo sistema.
// Só biometria (`useFallback: false`): o código do iPhone não abre a senha da gestão.
export async function verificar() {
  if (Date.now() - verificadoAs < JANELA_MS) return true;
  if (!pluginPresente()) return false;
  emVerificacao ??= NativeBiometric.verifyIdentity({
    reason: 'Entrar na Gestão Lisbonb',
    title: 'Gestão Lisbonb',
    useFallback: false,
  })
    .then(() => { verificadoAs = Date.now(); return true; })
    .catch((e) => (INTERROMPIDO.includes(String(e?.code)) ? null : false))
    .finally(() => { emVerificacao = null; });
  return emVerificacao;
}

// { email, senha } ou null. **Só depois do Face ID** — ver o topo do ficheiro.
export async function ler() {
  if ((await verificar()) !== true) return null;
  try {
    const c = await NativeBiometric.getCredentials({ server: SERVIDOR });
    return c?.username && c?.password ? { email: c.username, senha: c.password } : null;
  } catch (e) {
    return null;
  }
}

export async function guardar(email, senha) {
  if (!pluginPresente()) return false;
  try {
    await NativeBiometric.setCredentials({ username: email, password: senha, server: SERVIDOR });
    localStorage.setItem(CHAVE_EMAIL, email);
    return true;
  } catch (e) {
    return false;
  }
}

export async function apagar() {
  try { localStorage.removeItem(CHAVE_EMAIL); } catch (e) { /* modo privado */ }
  if (!pluginPresente()) return;
  try { await NativeBiometric.deleteCredentials({ server: SERVIDOR }); } catch (e) { /* já não havia */ }
}
```

- [ ] **Passo 5: Correr e ver passar**

Mesmo comando do Passo 3. Esperado: `5 passed`, **0 skipped**.

- [ ] **Passo 6: Prova por mutação** (estragar, ver vermelho pela razão certa, repor; uma de cada vez)

| Estragar em `frontend/src/lib/faceid.js` | Comando (`-k`) | Esperado |
|---|---|---|
| apagar a linha `  if ((await verificar()) !== true) return null;` (dentro de `ler`) | `-k ler_so` | `1 failed` — `tocouNoKeychain` passa a `True` |
| `const INTERROMPIDO = ['11', '13', '15'];` → `const INTERROMPIDO = [];` | `-k distingue` | `1 failed` — `sistema` dá `False` em vez de `None` |
| apagar a linha `  if (Date.now() - verificadoAs < JANELA_MS) return true;` | `-k distingue` | `1 failed` — `aos59s` dá `False` |
| `useFallback: false,` (dentro de `verifyIdentity`) → `useFallback: true,` | `-k ler_so` | `1 failed` — o pedido já não leva `"useFallback":false` |
| apagar a linha `    localStorage.setItem(CHAVE_EMAIL, email);` | `-k guardar_e` | `1 failed` — `email` fica `None` |
| `  emVerificacao ??= NativeBiometric.verifyIdentity({` → `  emVerificacao = NativeBiometric.verifyIdentity({` | `-k rostos_pedidos` | `1 failed` — `rostos: 2` |
| apagar a linha `    .finally(() => { emVerificacao = null; });` | `-k distingue` | `1 failed` — `sistema` dá `False`: o primeiro resultado ficava para sempre |

Comando base: `cd /Users/matheus.moraes/Developer/RH-calendario/backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/fin/test_sessao_do_bolso.py -q -k <filtro>`. Depois de cada uma, repor o texto original e confirmar `5 passed`.

- [ ] **Passo 7: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add frontend/src/lib/faceid.js backend/tests/fin/test_sessao_do_bolso.py
git commit -F - <<'MSG'
Face ID: a ponte do site para a peça nativa da casca (lib/faceid.js)

A versão 6 do plugin NativeBiometric guarda a senha no Keychain sem a
prender ao Face ID: o getCredentials devolve-a sem pedir nada. Por isso a
leitura só existe depois de um verifyIdentity só com biometria, e é este
módulo o único sítio do site que fala com a peça. Sem a peça (browser,
build 2, app do ponto) tudo responde «não» e nada rebenta. Um pedido de
rosto de cada vez: o StrictMode do ensaio monta a barreira duas vezes.

A app do ponto é o mesmo frontend/ (Capacitor): a próxima build dela leva
este módulo e o registerPlugin('NativeBiometric'). Sem a peça nativa é
inofensivo (isPluginAvailable dá false).

Os testes correm o ficheiro real em Node com o @capacitor/core simulado.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
MSG
```

---

### Tarefa 2: `lib/sessao.js` — barreira, re-entrada e o «não» lembrado

As decisões da sessão, fora do React para se poderem correr em Node: quando a barreira fecha e abre (5 minutos, `saiuAs`), uma só re-entrada para todos os 401 ao mesmo tempo, quem apaga o Keychain, e o que acontece depois de um login com senha.

**Ficheiros:**
- Criar: `frontend/src/lib/sessao.js`
- Modificar: `backend/tests/fin/test_sessao_do_bolso.py` (acrescentar no fim)
- Testes: `backend/tests/fin/test_sessao_do_bolso.py`

**Interfaces:**
- Consome: de `./faceid` (Tarefa 1) `apagar`, `emailGuardado`, `faceIdLigado`, `guardar`, `ler`, `temFaceId`, `verificar`.
- Produz (`frontend/src/lib/sessao.js`, usado pelas Tarefas 3 a 6):
  - `CINCO_MINUTOS: number` = `300000`;
  - `voltouATempo(agora?: number): boolean` — `saiuAs` existe e `agora − saiuAs ≤ 5 min`;
  - `barreiraFechada(): boolean` — decidido ao carregar: `faceIdLigado() && !voltouATempo()`;
  - `abrirBarreira(): void` — abre e solta os pedidos à espera;
  - `fecharBarreira(agora?: number): boolean` — só com Face ID ligado: grava `saiuAs` (só se estava ABERTA) e fecha; devolve se fechou;
  - `esperarBarreira(): Promise<void>` — resolve já se aberta, senão quando abrir;
  - `ligarEntrada(fn: (email: string, senha: string) => Promise<any>): void` — o `login` do AuthContext;
  - `reentrar(): Promise<boolean>` — partilhada enquanto corre; limpa-se depois de acabar;
  - `recusar(email: string): void` / `esquecerRecusa(email: string): void` — `localStorage['faceid_recusado:' + email]`;
  - `depoisDoLoginComSenha(email: string, senha: string): Promise<'perguntar' | 'nada'>`;
  - `ligarFaceId(email: string, senha: string): Promise<boolean>` — Face ID primeiro, depois guarda.

- [ ] **Passo 1: Escrever os testes que falham**

Acrescentar ao **fim** de `backend/tests/fin/test_sessao_do_bolso.py`:

```python


# --- lib/sessao.js ---------------------------------------------------------------


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
    """, tmp_path, antes="NB.presente = false;" + _LIGADO)
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
    """, tmp_path, antes=_LIGADO)
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
    """ % json.dumps(estado), tmp_path, antes=_LIGADO)
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
    """, tmp_path, antes=_LIGADO)
    assert r == {"ok": False, "logins": 0, "keychain": True}


@pytest.mark.parametrize("saiu_ha_ms,fechada", [
    (None, True),                 # sem `saiuAs`: conta como arranque
    (5 * 60 * 1000, False),       # voltou aos 5 minutos certos: não pede
    (5 * 60 * 1000 + 1, True),    # passou dos 5 minutos: pede
])
def test_ao_carregar_a_barreira_fecha_se_nao_voltou_a_tempo(tmp_path, saiu_ha_ms, fechada):
    antes = _RELOGIO + _LIGADO
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
    """, tmp_path, antes=_RELOGIO + _LIGADO)
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
    """, tmp_path, antes=_LIGADO)
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
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/fin/test_sessao_do_bolso.py -q
```

Esperado: `14 failed, 5 passed` — os 14 novos com `Cannot find module '…/frontend/src/lib/sessao'`.

- [ ] **Passo 3: Implementação mínima**

Criar `frontend/src/lib/sessao.js`:

```javascript
// A sessão da app «Gestão Lisbonb» com Face ID — as decisões, fora do React.
//
// Três peças, todas testadas em Node (backend/tests/fin/test_sessao_do_bolso.py):
//   1. a BARREIRA: um ecrã opaco depois de mais de 5 minutos fora; enquanto está
//      fechada, os pedidos do `lib/bolso.js` esperam (`esperarBarreira`);
//   2. a RE-ENTRADA: a sessão de 24 h expirou → Face ID → Keychain → login,
//      UMA só para todos os pedidos que deram 401 ao mesmo tempo;
//   3. a PERGUNTA depois de um login com senha, e o «não» lembrado por email.
//
// Sem a peça nativa (browser, build 2, app do ponto) nada disto actua.
import {
  apagar, emailGuardado, faceIdLigado, guardar, ler, temFaceId, verificar,
} from './faceid';

export const CINCO_MINUTOS = 5 * 60 * 1000;
const CHAVE_SAIU = 'saiuAs';
const CHAVE_RECUSA = 'faceid_recusado:';

const lerLocal = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
const gravarLocal = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* modo privado */ } };

// --- 1. A barreira -------------------------------------------------------------

// Saiu há 5 minutos ou menos? Sem `saiuAs` conta como arranque (→ não).
export const voltouATempo = (agora = Date.now()) => {
  const saiu = Number(lerLocal(CHAVE_SAIU));
  return saiu > 0 && agora - saiu <= CINCO_MINUTOS;
};

// Decide-se ao carregar a página, antes de qualquer ecrã montar: os efeitos dos
// filhos correm ANTES dos do pai, e o primeiro pedido do painel não pode sair
// à frente da barreira.
let fechada = faceIdLigado() && !voltouATempo();
let aEspera = [];

export const barreiraFechada = () => fechada;

export function abrirBarreira() {
  fechada = false;
  aEspera.splice(0).forEach((soltar) => soltar());
}

// Ao esconder. Sem Face ID ligado não fecha nada: no browser, esconder o
// separador fechava a porta e ninguém a voltava a abrir.
export function fecharBarreira(agora = Date.now()) {
  if (!faceIdLigado()) return false;
  // `saiuAs` = a hora a que se saiu de uma sessão ABERTA. Com a barreira ainda
  // fechada (ir ao ecrã principal enquanto o Face ID pede o rosto) não se grava:
  // senão, ao voltar logo, contava como «voltou a tempo» e abria sem rosto.
  if (!fechada) gravarLocal(CHAVE_SAIU, String(agora));
  fechada = true;
  return true;
}

export const esperarBarreira = () => (
  fechada ? new Promise((soltar) => { aEspera.push(soltar); }) : Promise.resolve()
);

// --- 2. A re-entrada -----------------------------------------------------------

// O `login(email, senha)` do AuthContext: grava o token, o cabeçalho e o estado.
let entrar = null;
export const ligarEntrada = (fn) => { entrar = fn; };

async function tentarReentrar() {
  if (!entrar || !faceIdLigado()) return false;
  const credenciais = await ler(); // pede o Face ID, salvo se acabou de passar
  if (!credenciais) return false;
  try {
    await entrar(credenciais.email, credenciais.senha);
    return true;
  } catch (e) {
    // **Só o 401 do login apaga o Keychain**: a senha guardada já não é a certa.
    // Um 429 (limite de tentativas) ou a rede em baixo não dizem nada da senha.
    if (e?.response?.status === 401) await apagar();
    return false;
  }
}

// Dois pedidos com 401 ao mesmo tempo → uma só re-entrada (um só Face ID, um
// só login). Limpa-se DEPOIS de acabar, para a próxima expiração tentar de novo.
let emCurso = null;
export function reentrar() {
  if (!emCurso) {
    emCurso = tentarReentrar()
      .catch(() => false)
      .finally(() => { emCurso = null; });
  }
  return emCurso;
}

// --- 3. Depois de um login com senha -------------------------------------------

export const recusar = (email) => gravarLocal(CHAVE_RECUSA + email, '1');
export const esquecerRecusa = (email) => {
  try { localStorage.removeItem(CHAVE_RECUSA + email); } catch (e) { /* modo privado */ }
};

// 'perguntar' ou 'nada'. Quem já tem o Face ID ligado com este email não é
// perguntado: a senha que acabou de escrever substitui a guardada (é assim
// que uma senha trocada se cura sozinha).
export async function depoisDoLoginComSenha(email, senha) {
  if (!(await temFaceId())) return 'nada';
  if (emailGuardado() === email) {
    await guardar(email, senha);
    return 'nada';
  }
  return lerLocal(CHAVE_RECUSA + email) ? 'nada' : 'perguntar';
}

// O «Sim»: o Face ID passa primeiro (é aqui que o iPhone pede a licença), só
// depois se guarda. Recusar a licença não deixa uma senha guardada sem uso.
export async function ligarFaceId(email, senha) {
  if ((await verificar()) !== true) return false;
  return guardar(email, senha);
}
```

- [ ] **Passo 4: Correr e ver passar**

Mesmo comando. Esperado: `19 passed`, 0 skipped.

- [ ] **Passo 5: Prova por mutação** (em `frontend/src/lib/sessao.js`, uma de cada vez; repor e confirmar `19 passed` no fim)

| Estragar | `-k` | Esperado |
|---|---|---|
| `  if (!emCurso) {` → `  {` (em `reentrar`) | `uma_so` | `1 failed` — dois logins e dois rostos |
| apagar a linha `      .finally(() => { emCurso = null; });` | `uma_so` | `1 failed` — a terceira re-entrada não faz login |
| `if (e?.response?.status === 401) await apagar();` → `await apagar();` | `keychain` | `2 failed` (429 e rede) |
| apagar a linha `  if (!faceIdLigado()) return false;` dentro de `fecharBarreira` | `sem_plugin` | `1 failed` — o browser fechava a porta |
| `agora - saiu <= CINCO_MINUTOS` → `agora - saiu < CINCO_MINUTOS` | `"carregar or esconder"` | `2 failed` — a fronteira dos 5 minutos |
| `  if (!fechada) gravarLocal(CHAVE_SAIU, String(agora));` → `  gravarLocal(CHAVE_SAIU, String(agora));` | `esconder` | `1 failed` — `fechadaNaoGrava.saiu` passa a `"1699999999000"` |
| apagar a linha `    await guardar(email, senha);` dentro de `depoisDoLoginComSenha` | `senha_nova` | `1 failed` |
| apagar a linha `  if ((await verificar()) !== true) return false;` dentro de `ligarFaceId` | `ligar_o` | `1 failed` — guardava sem rosto |
| `return lerLocal(CHAVE_RECUSA + email) ? 'nada' : 'perguntar';` → `return 'perguntar';` | `lembrado` | `1 failed` |
| `  fechada ? new Promise((soltar) => { aEspera.push(soltar); }) : Promise.resolve()` → `  Promise.resolve()` | `esperam` | `1 failed` |

- [ ] **Passo 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add frontend/src/lib/sessao.js backend/tests/fin/test_sessao_do_bolso.py
git commit -F - <<'MSG'
Face ID: as decisões da sessão num módulo puro (lib/sessao.js)

A barreira dos 5 minutos (saiuAs no localStorage, decidida ao carregar a
página para nenhum pedido sair à frente dela; só se grava ao sair com ela
aberta, senão voltar logo a seguir abria-a sem rosto), a re-entrada partilhada
quando a sessão de 24 h expira (dois 401 = um rosto e um login), e o «não»
lembrado por email. Só um 401 do login apaga o Keychain: 429 e rede em
baixo não dizem nada sobre a senha guardada.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
MSG
```

---

### Tarefa 3: `lib/bolso.js` — esperar pela barreira e reentrar num 401, por todos os ecrãs

Todas as chamadas do bolso (painel, calendário, idas) passam pela instância `api` deste ficheiro. É aqui, e não em cada ecrã, que (1) um pedido espera enquanto a barreira está fechada e (2) um 401 dispara a re-entrada e repete o pedido **uma** vez. O desenho pede que «os ecrãs do bolso usem `reentrar()` nos 401»: fazem-no todos por aqui, incluindo as chamadas que a Fase 2 escreveu.

**Ficheiros:**
- Modificar: `frontend/src/lib/bolso.js` (o import do topo e o `api.interceptors.request.use`, ~linhas 13-40 no main `57d5f6f`)
- Modificar: `backend/tests/fin/test_sessao_do_bolso.py` (acrescentar no fim)
- Testes: `backend/tests/fin/test_sessao_do_bolso.py`, `backend/tests/fin/test_caminhos_do_bolso.py` (tem de continuar verde)

**Interfaces:**
- Consome: `esperarBarreira(): Promise<void>` e `reentrar(): Promise<boolean>` de `./sessao` (Tarefa 2).
- Produz: o mesmo `lib/bolso.js` de antes (mesmas exportações). Comportamento novo: pedidos esperam a barreira; 401 → `reentrar()` → repete com `repetido: true` na config; um 401 com `repetido` ou sem re-entrada é atirado ao ecrã tal como vinha.
- Produz (Python, para as Tarefas 4 a 6): `_SERVIDOR: str` — no guião, `RESPOSTAS[chave]` (`'GET /bolso/painel'`, `'GET /auth/me'`, `'POST /auth/login'` → `[estado, corpo]`, fila `[[…], […]]` ou `'rede'`), `PEDIDOS` (chaves por ordem) e `CABECALHOS` (o `Authorization` de cada pedido).

- [ ] **Passo 1: Escrever os testes que falham**

Acrescentar ao fim de `backend/tests/fin/test_sessao_do_bolso.py`:

```python


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
    """, tmp_path, antes=_SERVIDOR + _LIGADO + r"""
      localStorage.setItem('token', 'velho');
      RESPOSTAS['GET /bolso/painel'] = [[401, {}], [200, { ok: true }]];
    """)
    assert r == {"data": {"ok": True}, "pedidos": ["GET /bolso/painel", "GET /bolso/painel"],
                 "cabecalhos": ["Bearer velho", "Bearer novo"]}


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
    """, tmp_path, antes=_SERVIDOR + _LIGADO + "RESPOSTAS['GET /bolso/painel'] = [401, {}];")
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
    """, tmp_path, antes=_SERVIDOR + _LIGADO + "RESPOSTAS['GET /bolso/painel'] = [200, {}];")
    assert r == {"antes": 0, "depois": 1}
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/fin/test_sessao_do_bolso.py -q -k bolso_
```

Esperado: `3 failed, 1 passed`. Falham `…reentra_e_repete…` (só um pedido, o 401 chega ao fim), `…nao_volta_a_tentar` (`pedidos: 1, logins: 0`) e `…barreira_fechada…` (`antes: 1`). Passa `…sem_face_id…` — é o comportamento de hoje, e tem de continuar a passar.

- [ ] **Passo 3: Implementação mínima**

Em `frontend/src/lib/bolso.js`, logo a seguir a `import axios from 'axios';`, acrescentar:

```javascript
import { esperarBarreira, reentrar } from './sessao';
```

E substituir o bloco inteiro

```javascript
api.interceptors.request.use((config) => {
  let token = null;
  try { token = localStorage.getItem('token'); } catch (e) { /* modo privado */ }
  config.headers = config.headers || {};
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});
```

por

```javascript
api.interceptors.request.use(async (config) => {
  // Com a barreira do Face ID fechada, nenhum pedido sai (ver lib/sessao.js).
  await esperarBarreira();
  let token = null;
  try { token = localStorage.getItem('token'); } catch (e) { /* modo privado */ }
  config.headers = config.headers || {};
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// **401 → uma re-entrada pelo Face ID e o MESMO pedido mais uma vez.** Aqui, e
// não em cada ecrã: todas as chamadas do bolso passam por esta instância.
// Sem Face ID (browser, build 2) a re-entrada diz logo «não» e o 401 segue
// para o ecrã como sempre seguiu.
api.interceptors.response.use(undefined, async (erro) => {
  const pedido = erro?.config;
  if (erro?.response?.status !== 401 || !pedido || pedido.repetido) throw erro;
  if (!(await reentrar())) throw erro;
  return api({ ...pedido, repetido: true });
});
```

(O token continua a ler-se a cada pedido: é isso que faz a repetição levar o token novo.)

- [ ] **Passo 4: Correr e ver passar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/fin/test_sessao_do_bolso.py tests/fin/test_caminhos_do_bolso.py -q
```

Esperado: tudo `passed`, 0 skipped (23 deste ficheiro + os do guarda de caminhos). O guarda de caminhos lê `api.<verbo>('…')`; o `api({...})` da repetição não é uma chamada nova e não lhe interessa.

- [ ] **Passo 5: Prova por mutação** (em `frontend/src/lib/bolso.js`; repor depois de cada uma)

| Estragar | `-k` | Esperado |
|---|---|---|
| apagar a linha `  await esperarBarreira();` | `bolso_com` | `1 failed` — `antes: 1` |
| `  return api({ ...pedido, repetido: true });` → `  return api({ ...pedido });` | `nao_volta` | `1 failed` **depois de ~30 s** (o ciclo sem fim só pára no `timeout` do teste — é exactamente o que o teste prende) |
| `  if (!(await reentrar())) throw erro;` + a linha seguinte → só `  throw erro;` | `token_novo` | `1 failed` — um pedido só |

- [ ] **Passo 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add frontend/src/lib/bolso.js backend/tests/fin/test_sessao_do_bolso.py
git commit -F - <<'MSG'
Bolso: os pedidos esperam pela barreira e um 401 tenta o Face ID uma vez

Num sítio só — a instância axios por onde passam o painel e o calendário —
em vez de em cada ecrã. Com a barreira fechada nenhum pedido sai; um 401
dispara a re-entrada partilhada e repete o pedido uma única vez com o
token novo. Sem Face ID o 401 chega ao ecrã como sempre chegou.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
MSG
```

---

### Tarefa 4: `AuthContext` — «Sem ligação», re-entrada no arranque e `terminarSessao()`

Hoje, se o `/auth/me` do arranque falha sem ser 401/403, o token fica mas o `user` não, e o `ProtectedRoute` manda para o login (desenho, medido 9). Passa a haver `semLigacao`, que o `login()` e o `logout()` limpam (senão quem passou do «Sem ligação» ao `/login`, entrou, e mais tarde carregou em Terminar sessão via outra vez «Sem ligação» em vez do login). Um 401 no arranque (as 24 h acabaram) tenta a re-entrada pelo Face ID antes do `logout()`. O `login()` passa a ser a porta da re-entrada (`ligarEntrada`) e a abrir a barreira. `terminarSessao()` sai **e** esquece o Face ID; o `logout()` não. E o `changePassword` (o ecrã `/alterar-senha`) leva a senha nova ao Keychain de quem tem o Face ID ligado para essa conta: senão a próxima re-entrada dava 401 e o Face ID perdia-se.

**Ficheiros:**
- Modificar: `frontend/src/contexts/AuthContext.js` (ficheiro inteiro tem 120 linhas no main `57d5f6f`)
- Modificar: `backend/tests/fin/test_sessao_do_bolso.py` (acrescentar no fim)
- Testes: `backend/tests/fin/test_sessao_do_bolso.py`

**Interfaces:**
- Consome: `apagar`, `emailGuardado`, `guardar` de `../lib/faceid` (Tarefa 1); `abrirBarreira`, `ligarEntrada`, `reentrar` de `../lib/sessao` (Tarefa 2).
- Produz (no valor do contexto, `useAuth()`), além do que já havia:
  - `semLigacao: boolean` — `true` só depois de um `/auth/me` sem resposta (ou 5xx); `login()` e `logout()` põem-no a `false`;
  - `tentarDeNovo(): void` — limpa `semLigacao`, põe `loading` e volta a perguntar `/auth/me`;
  - `terminarSessao(): void` — `logout()` + `faceid.apagar()`;
  - `logout` passa a ser **estável** (`useCallback`) — a Barreira (Tarefa 6) depende dele num efeito;
  - `changePassword(actual, nova)` — como antes; e, se `emailGuardado() === user.email`, `guardar(user.email, nova)`.
- Produz (Python, para as Tarefas 5 e 6): `_EU: str` (a conta da Carol em JSON), `_ESPERA: str` (no guião: `espera(ms)` e `texto()`), `_ESPIAO: str`.

- [ ] **Passo 1: Escrever os testes que falham**

Acrescentar ao fim de `backend/tests/fin/test_sessao_do_bolso.py`:

```python


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
      const Espiao = () => { auth = useAuth(); return null; };
      const raiz = createRoot(document.getElementById('raiz'));
      await act(async () => {
        raiz.render(React.createElement(AuthProvider, null, React.createElement(Espiao)));
      });
      await espera(50);
      const estado = () => ({ user: auth.user && auth.user.email, semLigacao: auth.semLigacao,
                              loading: auth.loading, token: localStorage.getItem('token') });
"""


@pytest.mark.parametrize("falha", ["[502, {}]", "'rede'"])
def test_arranque_sem_resposta_do_servidor_e_sem_ligacao_e_nao_login(tmp_path, falha):
    """`rede` leva ~3 s: são as três tentativas (1 s + 2 s) que já existiam."""
    r = _corre(_ESPIAO + """
      await espera(3200);
      return estado();
    """, tmp_path, dom=True, antes=_SERVIDOR + _ESPERA + r"""
      localStorage.setItem('token', 't');
      RESPOSTAS['GET /auth/me'] = %s;
    """ % falha)
    assert r == {"user": None, "semLigacao": True, "loading": False, "token": "t"}


def test_tentar_de_novo_volta_a_perguntar_e_entra(tmp_path):
    r = _corre(_ESPIAO + """
      const antes = estado();
      RESPOSTAS['GET /auth/me'] = [200, %s];
      await act(async () => { auth.tentarDeNovo(); });
      await espera(50);
      return { antes, depois: estado() };
    """ % _EU, tmp_path, dom=True, antes=_SERVIDOR + _ESPERA + r"""
      localStorage.setItem('token', 't');
      RESPOSTAS['GET /auth/me'] = [502, {}];
    """)
    assert r["antes"]["semLigacao"] is True
    assert r["depois"] == {"user": "carol@lisbonb.com", "semLigacao": False, "loading": False,
                           "token": "t"}


def test_arranque_com_a_sessao_expirada_e_face_id_reentra_sem_login(tmp_path):
    r = _corre(_ESPIAO + """
      await espera(50);
      return { ...estado(), pedidos: PEDIDOS, barreira: lib('lib/sessao').barreiraFechada() };
    """, tmp_path, dom=True, antes=_SERVIDOR + _ESPERA + _LIGADO + r"""
      localStorage.setItem('token', 'velho');
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
    """ % _EU, tmp_path, dom=True, antes=_SERVIDOR + _ESPERA + r"""
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
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/fin/test_sessao_do_bolso.py -q
```

Esperado: `8 failed, 24 passed`. Os 8 que falham: o contexto não tem `semLigacao` (sai `None`), `tentarDeNovo`/`terminarSessao` não existem (`is not a function`), o 401 do arranque faz `logout()` sem tentar o Face ID (`token: None`) e o `changePassword` não toca no Keychain (`senha: 'segredo'` no caso da Carol). O caso `[debora@lisbonb.com-segredo]` passa já: descreve o que não pode mudar (o Keychain de outra pessoa).

- [ ] **Passo 3: Implementação mínima** (nove edições em `frontend/src/contexts/AuthContext.js`)

3.1 — Imports. Substituir

```javascript
import React, { createContext, useContext, useState, useEffect } from 'react';
import axios from 'axios';
```

por

```javascript
import React, { createContext, useCallback, useContext, useState, useEffect } from 'react';
import axios from 'axios';
import { apagar as apagarFaceId, emailGuardado, guardar as guardarFaceId } from '../lib/faceid';
import { abrirBarreira, ligarEntrada, reentrar } from '../lib/sessao';
```

3.2 — Estado. Logo a seguir a `  const [loading, setLoading] = useState(true);` acrescentar:

```javascript
  // O `/auth/me` do arranque falhou SEM ser o servidor a recusar a sessão (rede
  // em baixo, 502 do deploy). O token fica; o `ProtectedRoute` mostra «Sem
  // ligação — tentar de novo» em vez de mandar para o login.
  const [semLigacao, setSemLigacao] = useState(false);
```

3.3 — O comentário por cima do `fetchUser`. Substituir as três linhas

```javascript
  // isso) e, se mesmo assim não vier resposta, o token **fica**. Aí o ecrã de
  // entrar aparece na mesma (o `isAuthenticated` é `!!user`), mas o próximo
  // recarregamento já recupera a sessão sozinho, sem escrever nada.
```

por

```javascript
  // isso) e, se mesmo assim não vier resposta, o token **fica** e o
  // `ProtectedRoute` mostra «Sem ligação — tentar de novo» (`semLigacao`) em
  // vez do ecrã de entrar: pedir a senha por um pedido sem resposta era
  // afirmar que a sessão acabou sem o saber.
```

3.4 — O 401 e o 403. Substituir

```javascript
      if (status === 401 || status === 403) {
        logout();
        return;
      }
```

por

```javascript
      // Sessão expirada (24 h): na casca com Face ID tenta-se a re-entrada;
      // sem Face ID, `reentrar()` diz logo que não e fica tudo como era.
      if (status === 401) {
        if (!(await reentrar())) logout();
        return;
      }
      if (status === 403) {
        logout();
        return;
      }
```

3.5 — Sem resposta. Substituir

```javascript
      console.error('Não foi possível confirmar a sessão (a sessão não foi terminada):', error);
```

por

```javascript
      console.error('Não foi possível confirmar a sessão (a sessão não foi terminada):', error);
      setSemLigacao(true);
```

3.6 — O `login`. Substituir

```javascript
    setToken(newToken);
    setUser(userData);
    return userData;
  };
```

por

```javascript
    setToken(newToken);
    setUser(userData);
    // Entrou: o servidor respondeu. Um «Sem ligação» de antes já não é verdade.
    setSemLigacao(false);
    // Quem acabou de entrar (senha ou Face ID) não leva com a barreira a seguir.
    abrirBarreira();
    return userData;
  };
  // A re-entrada do Face ID entra por aqui, para o token, o cabeçalho e o
  // estado ficarem iguais aos de um login com senha. Atribuição simples a cada
  // render (o `login` só usa setters e o localStorage — nunca fica velho).
  ligarEntrada(login);

  const tentarDeNovo = () => {
    setSemLigacao(false);
    setLoading(true);
    fetchUser();
  };
```

3.7 — O `logout`. Substituir

```javascript
  const logout = () => {
    localStorage.removeItem('token');
    delete axios.defaults.headers.common['Authorization'];
    setToken(null);
    setUser(null);
  };
```

por

```javascript
  // Estável (useCallback): a Barreira e o BolsoApp dependem dele em efeitos.
  // **Não apaga o Keychain** — é o que corre num 401 ou num Face ID cancelado.
  const logout = useCallback(() => {
    localStorage.removeItem('token');
    delete axios.defaults.headers.common['Authorization'];
    setToken(null);
    setUser(null);
    // Sem isto, quem saísse depois de um «Sem ligação» via-o outra vez em vez do login.
    setSemLigacao(false);
  }, []);

  // O botão «Terminar sessão»: sair E esquecer o Face ID deste telemóvel.
  const terminarSessao = useCallback(() => {
    logout();
    apagarFaceId();
  }, [logout]);
```

3.8 — O `changePassword` (o ecrã `/alterar-senha`). Substituir a linha (é a única do ficheiro)

```javascript
    return response.data;
```

por

```javascript
    // Com o Face ID ligado PARA ESTA CONTA, o Keychain leva a senha nova: senão a
    // próxima re-entrada dava 401 e o Face ID perdia-se. O de outra pessoa fica.
    if (emailGuardado() === user?.email) await guardarFaceId(user.email, newPassword);
    return response.data;
```

3.9 — O valor do contexto. Substituir

```javascript
      logout,
      changePassword,
```

por

```javascript
      logout,
      terminarSessao,
      semLigacao,
      tentarDeNovo,
      changePassword,
```

- [ ] **Passo 4: Correr e ver passar**

Mesmo comando do Passo 2. Esperado: `32 passed`, 0 skipped (≈12 s: o caso `'rede'` espera as três tentativas que já existiam).

- [ ] **Passo 5: Prova por mutação** (em `AuthContext.js`; repor depois de cada uma)

| Estragar | `-k` | Esperado |
|---|---|---|
| apagar a linha `      setSemLigacao(true);` | `sem_ligacao` | `2 failed` |
| `        if (!(await reentrar())) logout();` → `        logout();` | `expirada` | `1 failed` — `token: None` |
| apagar a linha `    abrirBarreira();` (no `login`) | `expirada` | `1 failed` — `barreira: True` |
| apagar a linha `  ligarEntrada(login);` | `expirada` | `1 failed` — a re-entrada não tem por onde entrar |
| apagar a linha `    apagarFaceId();` (no `terminarSessao`) | `terminar` | `1 failed` — o Keychain fica |
| no `login`, apagar a linha `    setSemLigacao(false);` (a seguir a `setUser(userData);`) | `limpam_o_aviso` | `1 failed` — `depoisDoLogin: True` |
| no `logout`, apagar a linha `    setSemLigacao(false);` (a seguir a `setUser(null);`) | `limpam_o_aviso` | `1 failed` — `depoisDoLogout: True` |
| apagar a linha `    if (emailGuardado() === user?.email) await guardarFaceId(user.email, newPassword);` | `mudar_a_senha` | `1 failed` (caso da Carol: `senha: 'segredo'`) |
| `if (emailGuardado() === user?.email) await` → `if (true) await` | `mudar_a_senha` | `1 failed` (caso da Débora: o Keychain dela passava a ser o da Carol) |

- [ ] **Passo 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add frontend/src/contexts/AuthContext.js backend/tests/fin/test_sessao_do_bolso.py
git commit -F - <<'MSG'
Sessão: «Sem ligação» em vez do login, e o Face ID a tapar as 24 h

Um /auth/me sem resposta (ou com 502) no arranque deixava o token e mandava
para o login na mesma: pedia-se a senha por um pedido que ninguém
respondeu. Passa a haver semLigacao, que o ProtectedRoute vai mostrar; o
login e o logout limpam-no, para um «Sem ligação» antigo não aparecer no
lugar do login depois de Terminar sessão.

Um 401 no arranque tenta primeiro a re-entrada pelo Face ID (sem a peça
nativa diz logo que não, como hoje). O login() passa a ser a porta dessa
re-entrada e abre a barreira. terminarSessao() esquece o Face ID; o
logout() dos 401 não. Mudar a senha no /alterar-senha leva a nova ao
Keychain de quem tem o Face ID ligado para essa conta.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
MSG
```

---

### Tarefa 5: `LoginPage` — «Usar Face ID para entrar?» depois da senha

Só na casca com a peça nativa, só depois de um login com **senha** e nunca com a senha provisória (`must_change_password`: vai ser trocada já a seguir no `/alterar-senha`, e guardá-la deixava no Keychain uma senha morta — a nova chega ao Keychain pelo `changePassword`, Tarefa 4). O defeito que este passo tem de evitar: o `login()` põe o `user` antes de a decisão chegar, e o efeito que já existe (`if (isAuthenticated && user) navigate(...)`) levava a pessoa embora antes de a pergunta aparecer. Um trinco (`aDecidir`) segura o efeito enquanto se decide.

**Ficheiros:**
- Modificar: `frontend/src/pages/LoginPage.js` (220 linhas no main `57d5f6f`: imports 1-12, estado ~43-52, `handleLogin` ~54-66, fim do JSX ~215-219)
- Modificar: `backend/tests/fin/test_sessao_do_bolso.py` (acrescentar no fim)
- Testes: `backend/tests/fin/test_sessao_do_bolso.py`

**Interfaces:**
- Consome: `depoisDoLoginComSenha`, `ligarFaceId`, `recusar` de `../lib/sessao` (Tarefa 2); `login()` do `useAuth()` (Tarefa 4: abre a barreira); `AlertDialog*` de `../components/ui/alert-dialog` (já existe).
- Produz: no ecrã de login, o diálogo «Usar Face ID para entrar?» com «Agora não» (→ `recusar(email)`) e «Usar Face ID» (→ `ligarFaceId(email, senha)`), sempre com o **email devolvido pelo servidor**; nada disto com `userData.must_change_password`; depois navega para `state.from` (ou `rotaDeAterragem`), como hoje.

- [ ] **Passo 1: Escrever os testes que falham**

Acrescentar ao fim de `backend/tests/fin/test_sessao_do_bolso.py`:

```python


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
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/fin/test_sessao_do_bolso.py -q -k "antes_de_sair or nao_pergunta or sem_pergunta"
```

Esperado: `2 failed, 3 passed` — os dois `…antes_de_sair_do_login[…]` falham (`aberta: False`, a página já saiu para o calendário). Os outros três (`…nao_pergunta_nada`, `…sem_pergunta`, `…provisoria_nao_pergunta`) descrevem o comportamento de hoje e têm de continuar a passar.

- [ ] **Passo 3: Implementação mínima** (seis edições em `frontend/src/pages/LoginPage.js`)

3.1 — Substituir `import React, { useState } from 'react';` por `import React, { useRef, useState } from 'react';`.

3.2 — Logo a seguir a `import { rotaDeAterragem } from '../lib/resumo';` acrescentar:

```javascript
import { depoisDoLoginComSenha, ligarFaceId, recusar } from '../lib/sessao';
```

3.3 — Logo a seguir a `import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';` acrescentar:

```javascript
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '../components/ui/alert-dialog';
```

3.4 — Substituir

```javascript
  const [loginPassword, setLoginPassword] = useState('');

  React.useEffect(() => {
    if (isAuthenticated && user) {
```

por

```javascript
  const [loginPassword, setLoginPassword] = useState('');
  // «Usar Face ID para entrar?» — só na casca com a peça nativa, depois de um
  // login com senha. `{ email, senha, papel }` enquanto a pergunta está aberta.
  const [pergunta, setPergunta] = useState(null);
  // Enquanto o login com senha decide se pergunta, o efeito de baixo não pode
  // levar a pessoa embora: o `login()` põe o `user` ANTES de a decisão chegar.
  const aDecidir = useRef(false);

  React.useEffect(() => {
    if (isAuthenticated && user && !aDecidir.current) {
```

3.5 — Substituir o corpo do `handleLogin`, de

```javascript
    setLoading(true);
    try {
      const userData = await login(loginEmail, loginPassword);
      toast.success('Sessão iniciada com sucesso!');
      navigate(paraOndeVoltar(userData.role));
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao iniciar sessão');
    } finally {
      setLoading(false);
    }
  };
```

para

```javascript
    setLoading(true);
    aDecidir.current = true;
    try {
      const userData = await login(loginEmail, loginPassword);
      toast.success('Sessão iniciada com sucesso!');
      // Com a senha provisória não se pergunta: vai ser trocada já a seguir
      // (/alterar-senha) e o Keychain ficava com uma senha morta.
      const decisao = userData.must_change_password ? 'nada' : await depoisDoLoginComSenha(userData.email, loginPassword);
      if (decisao === 'perguntar') {
        setPergunta({ email: userData.email, senha: loginPassword, papel: userData.role });
        return;
      }
      aDecidir.current = false;
      navigate(paraOndeVoltar(userData.role));
    } catch (error) {
      aDecidir.current = false;
      toast.error(error.response?.data?.detail || 'Erro ao iniciar sessão');
    } finally {
      setLoading(false);
    }
  };

  const responder = async (sim) => {
    const { email, senha, papel } = pergunta;
    if (sim) {
      if (await ligarFaceId(email, senha)) toast.success('Face ID ligado.');
      else toast.error('Não foi possível ligar o Face ID. Pode tentar no menu, em «Usar Face ID».');
    } else {
      recusar(email);
    }
    setPergunta(null);
    aDecidir.current = false;
    navigate(paraOndeVoltar(papel));
  };
```

3.6 — No fim do JSX, substituir

```javascript
          <p className="text-center text-xs text-muted-foreground/70 mt-1">v{APP_VERSION}</p>
        </div>
      </div>
```

por

```javascript
          <p className="text-center text-xs text-muted-foreground/70 mt-1">v{APP_VERSION}</p>
        </div>
      </div>

      <AlertDialog open={!!pergunta}>
        <AlertDialogContent className="max-w-[calc(100vw-2rem)] rounded-2xl">
          <AlertDialogHeader>
            <AlertDialogTitle>Usar Face ID para entrar?</AlertDialogTitle>
            <AlertDialogDescription>
              Da próxima vez entra com o rosto, sem escrever a senha.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className="gap-2">
            <AlertDialogCancel className="h-11" onClick={() => responder(false)}>Agora não</AlertDialogCancel>
            <AlertDialogAction className="h-11" onClick={() => responder(true)}>Usar Face ID</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
```

(O `<AlertDialog>` fica dentro do `<div className="min-h-screen flex">` de topo, a seguir à coluna do formulário; o conteúdo vai num portal, o sítio não muda o desenho.)

- [ ] **Passo 4: Correr e ver passar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/fin/test_sessao_do_bolso.py -q
```

Esperado: `37 passed`, 0 skipped.

- [ ] **Passo 5: Prova por mutação** (em `LoginPage.js`; repor depois de cada uma)

| Estragar | `-k` | Esperado |
|---|---|---|
| `if (isAuthenticated && user && !aDecidir.current)` → `if (isAuthenticated && user)` | `antes_de_sair` | `2 failed` — sai antes de perguntar |
| `setPergunta({ email: userData.email, senha` → `setPergunta({ email: loginEmail, senha` | `antes_de_sair` | `2 failed` — guardava `Carol@Lisbonb.com`, que o login (igualdade exacta no servidor) não aceita |
| apagar a linha `      recusar(email);` | `antes_de_sair` | `1 failed` («Agora não») |
| `    navigate(paraOndeVoltar(papel));` → `    navigate('/admin');` | `antes_de_sair` | `2 failed` — perdia o `state.from` |
| `userData.must_change_password ? 'nada' :` → `false ? 'nada' :` | `provisoria` | `1 failed` — perguntava (e `chamadas: ['isAvailable']`) |

- [ ] **Passo 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add frontend/src/pages/LoginPage.js backend/tests/fin/test_sessao_do_bolso.py
git commit -F - <<'MSG'
Login: perguntar «Usar Face ID para entrar?» depois da senha, na casca

Só com a peça nativa presente e só depois de um login com senha. O «Sim»
pede o Face ID primeiro (é aí que o iPhone pede a licença) e guarda o
email devolvido pelo servidor; o «Agora não» fica lembrado por email. Com a
senha provisória não se pergunta (vai ser trocada já a seguir). Um trinco
segura o efeito que levava a pessoa embora antes de a pergunta aparecer.
No browser e na build 2 o login fica igual.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
MSG
```

---

### Tarefa 6: a `Barreira` e o item «Usar Face ID» (`pages/bolso/Barreira.js`)

O ecrã opaco «Entrar como <email>». Três decisões de forma, todas medidas noutros sítios desta casa:

- é um **`<dialog>` aberto com `showModal()`**, não um `div fixed z-50`: os portais do Radix (o painel «Tapar» do calendário é um `Sheet`) pintam-se por cima de um `div` com o mesmo `z-50` (memória «Barreira de ecrã = dialog modal»); leva `pointer-events-auto` (com um Radix modal aberto o `body` fica `pointer-events:none`) e `stopPropagation` no `pointerdown` (senão o toque fechava o `Sheet` de baixo);
- os filhos ficam **montados por baixo**: quem estava a marcar uma ida e foi ao WhatsApp não perde o que escreveu; os dados não se pedem porque o `lib/bolso.js` espera pela barreira (Tarefa 3);
- `verificar()` a devolver `null` (o iOS interrompeu) **não** termina a sessão: fica a barreira com o botão;
- com a peça mas **sem Face ID possível** (bloqueado depois de cinco rostos errados — noutra app, até —, rosto apagado, licença retirada nas Definições) a barreira **não abre sozinha**: não há como verificar ninguém, e o desenho diz «até o Face ID passar» (§5.2) e «falhou → `logout()`» (§5.3). Sai-se para o login; o Keychain fica.

**Ficheiros:**
- Criar: `frontend/src/pages/bolso/Barreira.js`
- Modificar: `backend/tests/fin/test_sessao_do_bolso.py` (acrescentar no fim)
- Testes: `backend/tests/fin/test_sessao_do_bolso.py`

**Interfaces:**
- Consome: `useAuth()` → `logout` (estável, Tarefa 4) e `user`; `emailGuardado`, `temFaceId`, `verificar` de `@/lib/faceid`; `abrirBarreira`, `barreiraFechada`, `esquecerRecusa`, `fecharBarreira`, `voltouATempo` de `@/lib/sessao`; `ScanFace` de `lucide-react` (0.507, existe); `toast` de `sonner`.
- Produz (usado pela Tarefa 7):
  - `export default function Barreira({ children })` — desenha os filhos e, fechada, o `<dialog open>` com o botão `Entrar como <email>`;
  - `export function UsarFaceId({ className = '' })` — `<button>` «Usar Face ID» só com a peça, rosto disponível e `emailGuardado() !== user.email`; ao tocar: `esquecerRecusa(user.email)`, aviso «Entre com a senha para ligar o Face ID.» e `logout()` (sem tocar no Keychain). O `ProtectedRoute` leva ao login com `state.from`, e o login (Tarefa 5) volta a perguntar.

- [ ] **Passo 1: Escrever os testes que falham**

Acrescentar ao fim de `backend/tests/fin/test_sessao_do_bolso.py`:

```python


# --- A Barreira (pages/bolso/Barreira.js) -----------------------------------------

# A Barreira VERDADEIRA dentro do AuthProvider VERDADEIRO, com um filho que, ao
# montar, pede o painel pelo `lib/bolso.js` — como o BolsoApp faz.
_BARREIRA = r"""
      const { AuthProvider } = lib('contexts/AuthContext');
      const Barreira = lib('pages/bolso/Barreira').default;
      const { getPainel } = lib('lib/bolso');
      const Filho = () => {
        React.useEffect(() => { getPainel('all').catch(() => {}); }, []);
        return React.createElement('p', null, 'NUMEROS');
      };
      const raiz = createRoot(document.getElementById('raiz'));
      await act(async () => {
        raiz.render(React.createElement(AuthProvider, null,
          React.createElement(Barreira, null, React.createElement(Filho))));
      });
      await espera(20);
      const cortina = () => !!document.querySelector('dialog[open]');
      const rostos = () => NB.chamadas.filter((c) => c.startsWith('verifyIdentity')).length;
      const painel = () => PEDIDOS.filter((p) => p === 'GET /bolso/painel').length;
"""

_SESSAO_VALIDA = r"""
      localStorage.setItem('token', 't');
      RESPOSTAS['GET /auth/me'] = [200, %s];
      RESPOSTAS['GET /bolso/painel'] = [200, {}];
""" % _EU


def test_a_barreira_tapa_e_segura_os_pedidos_ate_o_rosto_passar(tmp_path):
    r = _corre(_BARREIRA + r"""
      const antes = { cortina: cortina(), diz: document.querySelector('dialog').textContent,
                      filhoMontado: texto().includes('NUMEROS'), painel: painel() };
      await act(async () => { NB.soltar(); });
      await espera(20);
      return { antes, depois: { cortina: cortina(), painel: painel() } };
    """, tmp_path, dom=True,
        antes=_SERVIDOR + _ESPERA + _LIGADO + _SESSAO_VALIDA + "NB.rosto = 'espera';")
    assert r["antes"]["cortina"] is True
    assert "Entrar como carol@lisbonb.com" in r["antes"]["diz"]
    assert r["antes"]["filhoMontado"] is True   # por baixo, montado (não perde o que se escrevia)
    assert r["antes"]["painel"] == 0            # mas sem pedir nada
    assert r["depois"] == {"cortina": False, "painel": 1}


def test_a_barreira_fecha_ao_esconder_e_so_pede_o_rosto_depois_de_5_minutos(tmp_path):
    r = _corre(_BARREIRA + r"""
      const passos = [['arranque', cortina(), rostos()]];
      await act(async () => { esconder(true); });
      passos.push(['escondida', cortina(), rostos(), localStorage.getItem('saiuAs')]);
      AGORA += 5 * 60 * 1000;
      await act(async () => { esconder(false); });
      await espera();
      passos.push(['voltou aos 5 min', cortina(), rostos()]);
      await act(async () => { esconder(true); });
      AGORA += 5 * 60 * 1000 + 1;
      await act(async () => { esconder(false); });
      await espera();
      passos.push(['voltou depois dos 5 min', cortina(), rostos()]);
      return passos;
    """, tmp_path, dom=True, antes=_SERVIDOR + _ESPERA + _RELOGIO + _LIGADO + _SESSAO_VALIDA)
    assert r == [
        ["arranque", False, 1],
        ["escondida", True, 1, "1700000000000"],
        ["voltou aos 5 min", False, 1],
        ["voltou depois dos 5 min", False, 2],
    ]


def test_cancelar_o_rosto_na_barreira_sai_mas_guarda_o_keychain(tmp_path):
    r = _corre(_BARREIRA + r"""
      return { token: localStorage.getItem('token'), keychain: NB.keychain !== null,
               email: localStorage.getItem('faceid_email'), painel: painel() };
    """, tmp_path, dom=True,
        antes=_SERVIDOR + _ESPERA + _LIGADO + _SESSAO_VALIDA + "NB.rosto = 'cancela';")
    assert r == {"token": None, "keychain": True, "email": "carol@lisbonb.com", "painel": 0}


def test_interrompido_pelo_sistema_fica_fechada_sem_sair(tmp_path):
    r = _corre(_BARREIRA + r"""
      return { cortina: cortina(), token: localStorage.getItem('token'), painel: painel() };
    """, tmp_path, dom=True,
        antes=_SERVIDOR + _ESPERA + _LIGADO + _SESSAO_VALIDA + "NB.rosto = 'sistema';")
    assert r == {"cortina": True, "token": "t", "painel": 0}


def test_ir_ao_ecra_principal_com_o_rosto_por_passar_nao_abre_a_barreira(tmp_path):
    """Abrir a app e ir ao ecrã principal enquanto o Face ID pede o rosto: o iOS
    interrompe (`null`) e a barreira fica. Voltar logo a seguir NÃO é «voltou dentro
    dos 5 minutos» — ninguém passou o rosto, e a sessão nunca chegou a abrir."""
    r = _corre(_BARREIRA + r"""
      await act(async () => { esconder(true); });
      await act(async () => { esconder(false); });
      await espera();
      return { cortina: cortina(), painel: painel(), saiu: localStorage.getItem('saiuAs') };
    """, tmp_path, dom=True,
        antes=_SERVIDOR + _ESPERA + _RELOGIO + _LIGADO + _SESSAO_VALIDA + "NB.rosto = 'sistema';")
    assert r == {"cortina": True, "painel": 0, "saiu": None}


def test_barreira_e_reentrada_logo_a_seguir_pedem_um_so_rosto(tmp_path):
    """A barreira passa e o primeiro pedido dá 401 (as 24 h acabaram): a
    re-entrada não volta a pedir o rosto — acabou de passar."""
    r = _corre(_BARREIRA + r"""
      await espera(20);
      return { rostos: rostos(), painel: painel(), token: localStorage.getItem('token'),
               logins: PEDIDOS.filter((p) => p === 'POST /auth/login').length };
    """, tmp_path, dom=True, antes=_SERVIDOR + _ESPERA + _LIGADO + r"""
      localStorage.setItem('token', 'velho');
      RESPOSTAS['GET /auth/me'] = [200, %s];
      RESPOSTAS['GET /bolso/painel'] = [[401, {}], [200, {}]];
      RESPOSTAS['POST /auth/login'] = [200, { token: 'novo', user: %s }];
    """ % (_EU, _EU))
    assert r == {"rostos": 1, "painel": 2, "token": "novo", "logins": 1}


@pytest.mark.parametrize("caso", ["sem-plugin", "face-id-indisponivel"])
def test_sem_a_peca_nao_ha_barreira_e_sem_face_id_disponivel_sai(tmp_path, caso):
    """Sem a peça (browser, build 2) a barreira não existe. Com a peça mas sem Face ID
    possível (bloqueado depois de cinco rostos errados noutra app, rosto apagado,
    licença retirada) NÃO abre sozinha — era abrir sem verificar ninguém: sai-se para
    o login (desenho §5.2 e §5.3), sem pedir rosto e sem apagar o Keychain."""
    r = _corre(_BARREIRA + r"""
      const inicio = { cortina: cortina(), filho: texto().includes('NUMEROS'), painel: painel() };
      await act(async () => { esconder(true); });
      await act(async () => { esconder(false); });
      await espera();
      return { inicio, depois: cortina(), token: localStorage.getItem('token'), rostos: rostos(),
               keychain: NB.keychain !== null };
    """, tmp_path, dom=True, antes=_SERVIDOR + _ESPERA + _LIGADO + _SESSAO_VALIDA
        + ("NB.presente = false;" if caso == "sem-plugin" else "NB.disponivel = false;"))
    if caso == "sem-plugin":
        assert r == {"inicio": {"cortina": False, "filho": True, "painel": 1}, "depois": False,
                     "token": "t", "rostos": 0, "keychain": True}
    else:
        assert r == {"inicio": {"cortina": True, "filho": True, "painel": 0}, "depois": True,
                     "token": None, "rostos": 0, "keychain": True}


# --- «Usar Face ID» no menu lateral ----------------------------------------------


@pytest.mark.parametrize("caso,mostra", [
    ("recusou-antes", True), ("ja-ligado", False), ("sem-plugin", False),
])
def test_usar_face_id_no_menu(tmp_path, caso, mostra):
    r = _corre(r"""
      const { AuthProvider } = lib('contexts/AuthContext');
      const { UsarFaceId } = lib('pages/bolso/Barreira');
      const raiz = createRoot(document.getElementById('raiz'));
      await act(async () => {
        raiz.render(React.createElement(AuthProvider, null, React.createElement(UsarFaceId)));
      });
      await espera(20);
      const botao = [...document.querySelectorAll('button')].find((b) => b.textContent === 'Usar Face ID');
      if (!botao) return { mostra: false };
      await act(async () => { botao.click(); });
      await espera();
      return { mostra: true, token: localStorage.getItem('token'),
               recusa: localStorage.getItem('faceid_recusado:carol@lisbonb.com') };
    """, tmp_path, dom=True, antes=_SERVIDOR + _ESPERA + _SESSAO_VALIDA + r"""
      localStorage.setItem('faceid_recusado:carol@lisbonb.com', '1');
      const caso = %s;
      if (caso === 'ja-ligado') localStorage.setItem('faceid_email', 'carol@lisbonb.com');
      if (caso === 'sem-plugin') NB.presente = false;
    """ % json.dumps(caso))
    if mostra:
        # Esquece o «não» e sai (sem tocar no Keychain): o login, depois da
        # senha, volta a perguntar.
        assert r == {"mostra": True, "token": None, "recusa": None}
    else:
        assert r == {"mostra": False}
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/fin/test_sessao_do_bolso.py -q
```

Esperado: `11 failed, 37 passed` — os 11 novos com `Cannot find module '…/frontend/src/pages/bolso/Barreira'`.

- [ ] **Passo 3: Implementação mínima**

Criar `frontend/src/pages/bolso/Barreira.js`:

```javascript
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ScanFace } from 'lucide-react';
import { toast } from 'sonner';
import { useAuth } from '@/contexts/AuthContext';
import { emailGuardado, temFaceId, verificar } from '@/lib/faceid';
import {
  abrirBarreira, barreiraFechada, esquecerRecusa, fecharBarreira, voltouATempo,
} from '@/lib/sessao';

// **A barreira do Face ID** — o ecrã opaco por cima do bolso ao abrir a app e ao
// voltar depois de mais de 5 minutos fora. Só existe na casca com Face ID
// ligado; no browser e na build 2 desenha os filhos e mais nada.
//
// Os filhos ficam MONTADOS por baixo: quem estava a marcar uma ida e foi ver o
// WhatsApp não perde o que escreveu. Os números não aparecem porque a barreira
// é um <dialog> modal (camada de cima do browser, por cima até das janelas do
// Radix), e não se pedem porque o `lib/bolso.js` espera por ela
// (`esperarBarreira`). Ver a memória «Barreira de ecrã = dialog modal».
//
// Fecha LOGO ao esconder (a miniatura do selector de apps não pode mostrar
// números). Face ID falhado ou cancelado → `logout()` (o Keychain fica) e o
// `ProtectedRoute` leva ao login com `state.from`. Interrompido pelo sistema
// (`null`) → fica fechada, com o botão. Sem Face ID possível → `logout()`: a
// barreira nunca abre sem um rosto (ou sem ter voltado dentro dos 5 minutos).
export default function Barreira({ children }) {
  const { logout } = useAuth();
  const [fechada, setFechada] = useState(barreiraFechada);

  const abrir = useCallback(() => { abrirBarreira(); setFechada(false); }, []);
  const entrar = useCallback(async () => {
    const r = await verificar();
    if (r === true) abrir();
    else if (r === false) logout();
  }, [abrir, logout]);

  // Voltou dentro dos 5 minutos → abre sem rosto. Senão, o rosto. Sem Face ID
  // possível (bloqueado depois de rostos errados — noutra app, até —, rosto
  // apagado, licença retirada) não há como verificar ninguém: login, como num
  // rosto falhado (desenho §5.2 e §5.3). O Keychain fica para quando voltar.
  const decidir = useCallback(async () => {
    if (!barreiraFechada()) return;
    if (voltouATempo()) abrir();
    else if (await temFaceId()) entrar();
    else logout();
  }, [abrir, entrar, logout]);

  useEffect(() => {
    decidir();
    const aoMudar = () => {
      if (!document.hidden) { decidir(); return; }
      if (fecharBarreira()) setFechada(true);
    };
    document.addEventListener('visibilitychange', aoMudar);
    return () => document.removeEventListener('visibilitychange', aoMudar);
  }, [decidir]);

  return (
    <>
      {children}
      {fechada && <Cortina email={emailGuardado()} onEntrar={entrar} />}
    </>
  );
}

function Cortina({ email, onEntrar }) {
  const ref = useRef(null);
  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal();
  }, []);
  return (
    // `pointer-events-auto`: com uma janela do Radix aberta por baixo, o body
    // fica com `pointer-events:none` e a barreira herdava-o. O `stopPropagation`
    // impede o toque de chegar ao `document`, onde o Radix fecharia a janela.
    <dialog
      ref={ref}
      aria-label="Entrar com Face ID"
      onCancel={(e) => e.preventDefault()}
      onPointerDown={(e) => e.stopPropagation()}
      className="pointer-events-auto fixed inset-0 m-0 h-[100dvh] max-h-none w-screen max-w-none
                 bg-background p-0 text-foreground backdrop:bg-background"
    >
      <div className="flex h-full flex-col items-center justify-center gap-6 px-6 safe-area-inset-top">
        <ScanFace className="h-14 w-14 text-muted-foreground" aria-hidden="true" />
        <p className="text-center text-[15px] font-semibold">Gestão Lisbonb</p>
        <button
          type="button"
          onClick={onEntrar}
          className="h-12 w-full max-w-xs rounded-2xl bg-primary px-4 text-[15px] font-semibold
                     text-primary-foreground dark:text-background focus-visible:outline-none
                     focus-visible:ring-2 focus-visible:ring-ring"
        >
          Entrar como {email}
        </button>
      </div>
    </dialog>
  );
}

// O item «Usar Face ID» do menu lateral, para quem disse «Agora não» e mudou de
// ideias (ou trocou de conta neste telemóvel). Para guardar a senha é preciso
// escrevê-la: esquece-se o «não», termina-se a sessão (sem tocar no Keychain) e
// o login, depois da senha, pergunta outra vez. A `className` vem do menu, para
// ficar igual aos outros itens (o ícone também).
export function UsarFaceId({ className = '' }) {
  const { user, logout } = useAuth();
  const [mostrar, setMostrar] = useState(false);
  useEffect(() => {
    let vivo = true;
    temFaceId().then((tem) => {
      if (vivo) setMostrar(tem && !!user?.email && emailGuardado() !== user.email);
    });
    return () => { vivo = false; };
  }, [user]);
  if (!mostrar) return null;
  return (
    <button
      type="button"
      className={className}
      onClick={() => {
        esquecerRecusa(user.email);
        toast('Entre com a senha para ligar o Face ID.');
        logout();
      }}
    >
      <ScanFace className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
      Usar Face ID
    </button>
  );
}
```

- [ ] **Passo 4: Correr e ver passar**

Mesmo comando. Esperado: `48 passed`, 0 skipped.

- [ ] **Passo 5: Prova por mutação** (em `Barreira.js`; repor depois de cada uma)

Comando base: `cd /Users/matheus.moraes/Developer/RH-calendario/backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/fin/test_sessao_do_bolso.py -q -k <filtro>`.

1. `      if (fecharBarreira()) setFechada(true);` → `      fecharBarreira();` — `-k 5_minutos` → `1 failed` (escondida sem cortina: a miniatura mostrava os números).
2. Apagar a linha `    else if (r === false) logout();` — `-k cancelar_o_rosto` → `1 failed` (o token fica).
3. `    else if (r === false) logout();` → `    else logout();` — `-k interrompido` → `1 failed` (o iOS a interromper deitava a pessoa fora).
4. No `decidir`, `    else logout();` → `    else abrir();` (o comportamento antigo) — `-k indisponivel` → `1 failed` (caso «face-id-indisponivel»: a barreira abria sem verificar ninguém).
5. `    if (voltouATempo()) abrir();` → `    if (true) abrir();` — `-k 5_minutos` → `1 failed` (nunca mais pedia o rosto).
6. Apagar a linha `      {fechada && <Cortina email={emailGuardado()} onEntrar={entrar} />}` — `-k segura` → `1 failed`.
7. Apagar a linha `        esquecerRecusa(user.email);` — `-k usar_face` → `1 failed`.
8. `setMostrar(tem && !!user?.email && emailGuardado() !== user.email)` → `setMostrar(tem)` — `-k usar_face` → `1 failed` (caso «ja-ligado»).
9. Em `frontend/src/lib/sessao.js` (o defeito que esta tarefa monta por inteiro): `  if (!fechada) gravarLocal(CHAVE_SAIU, String(agora));` → `  gravarLocal(CHAVE_SAIU, String(agora));` — `-k rosto_por_passar` → `1 failed` (`saiu` gravado; ao voltar a barreira abria sem rosto: `cortina: False`, `painel: 1`).

- [ ] **Passo 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add frontend/src/pages/bolso/Barreira.js backend/tests/fin/test_sessao_do_bolso.py
git commit -F - <<'MSG'
Bolso: a barreira do Face ID e o item «Usar Face ID» do menu

Um <dialog> modal opaco («Entrar como <email>») ao abrir a app e ao voltar
depois de mais de 5 minutos fora; fecha logo ao esconder, para a miniatura
do selector de apps não mostrar números. Os ecrãs ficam montados por baixo
(quem marcava uma ida e foi ao WhatsApp não perde o que escreveu) e não
pedem nada enquanto ela está fechada. Rosto cancelado → logout sem apagar
o Keychain; o iOS a interromper não termina a sessão (e esconder com o
rosto por passar não conta como «voltou a tempo»). Sem a peça nativa não
existe; com a peça e sem Face ID possível (bloqueado, rosto apagado) não
abre sozinha: sai para o login, como o desenho pede.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
MSG
```

---

### Tarefa 7: ligar tudo — `App.js`, os ecrãs do bolso e o menu lateral

As peças das Tarefas 1-6 só funcionam montadas. Quatro avarias que nenhum teste anterior apanha e que este passo previne: (1) uma rota `/bolso*` sem `Barreira` — com o Face ID ligado, os pedidos do `lib/bolso.js` esperavam por ela **para sempre** (a app parada num spinner); (2) um ecrã do bolso a mandar para o login com `navigate('/login')` — perde o `state.from` e, depois de entrar, a pessoa ia parar ao `/admin/resumo` (o `BolsoApp` fá-lo hoje; o `BolsoCalendario` da Fase 2 também, pelo `semSessao()`); (3) um 401 que chega ao `PainelIda` (a re-entrada não deu) e aparece como um erro dentro do painel, numa app já sem sessão, em vez do login (desenho §5.4: «falhou → login normal»); (4) um «Terminar sessão» que não esquece o Face ID. E o «Sem ligação» passa a aparecer também na rota `/` (o `RoleRedirect`, por onde o portal abre no browser), que mandava para o login como o `ProtectedRoute` mandava.

**Ficheiros:**
- Modificar: `frontend/src/App.js` (imports ~82; `ProtectedRoute` ~100-130; `RoleRedirect` ~156-180; rotas `/bolso` ~206-210 e `/bolso/calendario`, que a Fase 2 pôs logo a seguir)
- Modificar: `frontend/src/pages/bolso/BolsoApp.js` (`useNavigate` ~2 e ~435; o `catch` do `carregar`, ~468-480)
- Modificar: `frontend/src/pages/bolso/BolsoCalendario.js` (Fase 2: o `semSessao` e os dois ramos do 401 do `carregar`/`carregarContagem`) e `frontend/src/pages/bolso/PainelIda.js` (Fase 2: os `catch` do `gravar` e do `apagar`)
- Modificar: `frontend/src/pages/bolso/partilhado.js` (o `MenuLateral` da Fase 2)
- Modificar: `backend/tests/fin/test_sessao_do_bolso.py` (acrescentar no fim)
- Modificar: `backend/tests/bolso_js.py` (o `SESSAO_SIMULADA` da Fase 2 ganha `terminarSessao`), `backend/tests/calendario/test_menu_do_bolso.py` (o teste do «Terminar sessão» passa a esperar `terminarSessao`), `backend/tests/calendario/test_ecra_do_calendario.py` (o 401 passa a esperar só `logout`) e `backend/tests/calendario/test_painel_da_ida.py` (monta com o `SESSAO_SIMULADA`; teste novo do 401)
- Testes: `backend/tests/fin/test_sessao_do_bolso.py`, os três de `backend/tests/calendario/` acima e a suite inteira

**Interfaces:**
- Consome: `Barreira` e `UsarFaceId` de `./pages/bolso/Barreira` (Tarefa 6); `semLigacao`, `tentarDeNovo`, `terminarSessao`, `logout` de `useAuth()` (Tarefa 4); `Button` de `./components/ui/button` (existe); `SESSAO_SIMULADA`, `AXIOS_FABRICADO`, `correr_js` de `tests/bolso_js.py` (Fase 2).
- Produz: `SemLigacao()` em `App.js` (o ecrã «Sem ligação — tentar de novo», mostrado pelo `ProtectedRoute` e pelo `RoleRedirect`); `RotaDoBolso({ children })` em `App.js` = `ProtectedRoute` com os papéis `admin`/`gerente`/`contabilista` + `Barreira`.

- [ ] **Passo 1: Escrever os guardas que falham**

Acrescentar ao fim de `backend/tests/fin/test_sessao_do_bolso.py`:

```python


# --- A montagem: App.js e os ecrãs do bolso (guardas de texto) -------------------
#
# O App.js importa o portal inteiro e não se monta aqui; o que se vê nele é o
# ensaio no browser (Tarefa 8). Estes guardas apanham as duas avarias que
# nenhum teste de cima apanha: uma rota /bolso SEM Barreira (com o Face ID
# ligado os pedidos esperavam por ela para sempre) e um ecrã do bolso que volte
# a mandar para o login à mão (perdia o `state.from`) ou a sair sem esquecer o
# Face ID.
import re  # noqa: E402

_RE_ROTA = re.compile(r'<Route\s+path="(/bolso[^"]*)"\s+element=\{\s*<(\w+)')


def test_todas_as_rotas_do_bolso_passam_pela_barreira():
    app = (_SRC / "App.js").read_text(encoding="utf-8")
    rotas = _RE_ROTA.findall(app)
    assert {"/bolso", "/bolso/calendario"} <= {caminho for caminho, _ in rotas}, rotas
    assert all(quem == "RotaDoBolso" for _, quem in rotas), rotas
    rota = app[app.index("const RotaDoBolso"):]
    rota = rota[:rota.index(");")]
    assert "<ProtectedRoute" in rota and "<Barreira>" in rota


def test_o_protected_route_e_o_role_redirect_mostram_sem_ligacao_antes_do_login():
    """O `ProtectedRoute` (o bolso e o portal) e o `RoleRedirect` (a rota `/`, por onde
    o portal abre no browser): os dois mandavam para o login sem resposta do servidor."""
    app = (_SRC / "App.js").read_text(encoding="utf-8")

    def corpo(nome):
        resto = app[app.index("const %s = " % nome):]
        return resto[:resto.index("\n};\n")]

    for nome in ("ProtectedRoute", "RoleRedirect"):
        c = corpo(nome)
        assert "if (!isAuthenticated && semLigacao) return <SemLigacao />;" in c, nome
        assert c.index("<SemLigacao />") < c.index('<Navigate to="/login"'), nome
    tela = corpo("SemLigacao")
    assert "onClick={tentarDeNovo}" in tela and "Tentar de novo" in tela


def test_no_bolso_ninguem_vai_ao_login_a_mao_e_sair_esquece_o_face_id():
    pasta = _SRC / "pages" / "bolso"
    for ficheiro in sorted(pasta.glob("*.js")):
        texto = ficheiro.read_text(encoding="utf-8")
        assert not re.search(r"navigate\(\s*['\"]/login['\"]", texto), ficheiro.name
        if "Terminar sessão" in texto:
            assert "terminarSessao" in texto, ficheiro.name
            assert not re.search(r"logout\(\);\s*navigate", texto), ficheiro.name
    # Os dois ecrãs: um 401 que chega ao ecrã (a re-entrada não deu) faz logout().
    for ecra in ("BolsoApp.js", "BolsoCalendario.js"):
        texto = (pasta / ecra).read_text(encoding="utf-8")
        assert re.search(r"status\s*===\s*401\)\s*\{\s*logout\(\);", texto), ecra
    menu = (pasta / "partilhado.js").read_text(encoding="utf-8")
    assert "<UsarFaceId" in menu
```

E mudar o que a Fase 2 prende do «Terminar sessão» (era `logout()` + `navigate('/login')`; passa a ser `terminarSessao()` e mais nada):

1b.1 — Em `backend/tests/bolso_js.py`, no `SESSAO_SIMULADA`, substituir

```python
    "@/contexts/AuthContext": "(() => { const sessao = { logout: () => REGISTO.push(['logout']),"
                              " user: { name: 'Débora Ferreira' } }; return { useAuth: () => sessao }; })()",
```

por

```python
    "@/contexts/AuthContext": "(() => { const sessao = { logout: () => REGISTO.push(['logout']),"
                              " terminarSessao: () => REGISTO.push(['terminarSessao']),"
                              " user: { name: 'Débora Ferreira' } }; return { useAuth: () => sessao }; })()",
```

1b.2 — Em `backend/tests/calendario/test_menu_do_bolso.py`, substituir

```python
def test_terminar_sessao_sai_e_vai_para_o_login(tmp_path):
```

por

```python
def test_terminar_sessao_esquece_o_face_id_e_sai(tmp_path):
    """Fase 3: `terminarSessao()` = logout + apagar o Face ID deste telemóvel. Não se
    navega à mão: o ProtectedRoute leva ao login com o `state.from`."""
```

e, no fim desse teste, `    assert r == [["logout"], ["navigate", "/login"]]` por `    assert r == [["terminarSessao"]]`.

1b.3 — Em `backend/tests/calendario/test_ecra_do_calendario.py` (o 401 do `BolsoCalendario` deixa de navegar à mão), substituir

```python
def test_sessao_expirada_sai_para_o_login(tmp_path):
    mes, _ = _servidor()
    r = _ecra(tmp_path, "devolve(REGISTO.filter((x) => x[0] !== 'GET'));", mes, falha={"response": {"status": 401}})
    assert r == [["logout"], ["navigate", "/login"]]
```

por

```python
def test_um_401_que_chega_ao_ecra_so_faz_logout(tmp_path):
    """Fase 3: o `lib/bolso.js` já tentou a re-entrada pelo Face ID. Não se navega à mão:
    o ProtectedRoute leva ao login com o `state.from` e, depois de entrar, volta-se aqui."""
    mes, _ = _servidor()
    r = _ecra(tmp_path, "devolve(REGISTO.filter((x) => x[0] !== 'GET'));", mes, falha={"response": {"status": 401}})
    assert r == [["logout"]]
```

1b.4 — Em `backend/tests/calendario/test_painel_da_ida.py` (o painel passa a usar o `useAuth()`, que fora de um `AuthProvider` rebenta: monta-se com o `SESSAO_SIMULADA`, como o ecrã do calendário). Substituir

```python
import json

import calendario
from tests.bolso_js import AXIOS_FABRICADO, correr_js
```

por

```python
import json

import pytest

import calendario
from tests.bolso_js import AXIOS_FABRICADO, SESSAO_SIMULADA, correr_js
```

substituir (no `_painel`)

```python
    ]), tmp_path, simulados={"axios": AXIOS_FABRICADO}, dom=True)
```

por

```python
    ]), tmp_path, simulados=dict(SESSAO_SIMULADA, axios=AXIOS_FABRICADO), dom=True)
```

e acrescentar no fim do ficheiro:

```python


@pytest.mark.parametrize("painel,botoes,verbo", [
    (TAPAR_OEIRAS, ["Marcar 1 ida"], "POST"),
    (IDA, ["Apagar", "Tocar de novo para apagar"], "DELETE"),
])
def test_um_401_ao_gravar_ou_apagar_faz_logout_sem_mostrar_erro(tmp_path, painel, botoes, verbo):
    """Fase 3: o 401 só chega ao painel se a re-entrada pelo Face ID não deu
    (`lib/bolso.js`) → login normal (desenho §5.4), e não um erro num painel sem sessão."""
    r = _painel(tmp_path, painel, """
for (const nome of %s) await clicar(botao(nome, dlg));
await esperar();
devolve({ registo: REGISTO.map((x) => x[0]), erroAVista: texto().includes('Sessão expirada.') });
""" % json.dumps(botoes, ensure_ascii=False),
        resposta={"erro": {"response": {"status": 401, "data": {"detail": "Sessão expirada."}}}})
    assert r == {"registo": [verbo, "logout"], "erroAVista": False}
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/fin/test_sessao_do_bolso.py tests/calendario/test_menu_do_bolso.py tests/calendario/test_ecra_do_calendario.py tests/calendario/test_painel_da_ida.py -q -k "rotas_do_bolso or sem_ligacao_antes or a_mao or terminar_sessao_esquece or um_401"
```

Esperado: `7 failed` — as rotas usam `ProtectedRoute` (não `RotaDoBolso`); o guarda do «Sem ligação» falha com `AssertionError: ProtectedRoute` (ainda sem o ramo); `BolsoApp.js` ainda tem `navigate('/login')`; o menu ainda regista `[['logout'], ['navigate', '/login']]`; o calendário ainda regista `[['logout'], ['navigate', '/login']]` (o `semSessao`); e os dois casos do painel mostram o erro sem `logout` (`registo: ['POST']` / `['DELETE']`, `erroAVista: True`). Os outros testes de `test_painel_da_ida.py` (fora do filtro) continuam verdes com o `SESSAO_SIMULADA`: o painel ainda não usa o `useAuth()`.

- [ ] **Passo 3: `App.js`**

3.1 — Logo a seguir a `import BolsoApp from './pages/bolso/BolsoApp';` (o import do `BolsoCalendario` da Fase 2 fica onde está) acrescentar:

```javascript
import Barreira from './pages/bolso/Barreira';
import { Button } from './components/ui/button';
```

3.2 — O ecrã «Sem ligação». Substituir

```javascript
// Protected Route Component - checks for authentication and must_change_password
const ProtectedRoute = ({ children, allowedRoles }) => {
```

por

```javascript
// O arranque não conseguiu perguntar ao servidor se a sessão vale (rede em
// baixo, 502 de um deploy). O token ficou: mandar para o login era pedir a
// senha por causa de um pedido que nunca foi respondido. Mostrado pelo
// `ProtectedRoute` e pelo `RoleRedirect` (a rota `/` do portal no browser).
const SemLigacao = () => {
  const { tentarDeNovo } = useAuth();
  return (
    <div className="min-h-[100dvh] flex flex-col items-center justify-center gap-2 bg-background px-6 text-center">
      <p className="text-base font-semibold">Sem ligação</p>
      <p className="text-sm text-muted-foreground">Não foi possível falar com o servidor.</p>
      <Button className="mt-3 h-11 px-6" onClick={tentarDeNovo}>Tentar de novo</Button>
    </div>
  );
};

// Protected Route Component - checks for authentication and must_change_password
const ProtectedRoute = ({ children, allowedRoles }) => {
```

3.3 — No `ProtectedRoute`, substituir

```javascript
  const { user, loading, isAuthenticated, mustChangePassword } = useAuth();
  // De ONDE veio
```

por

```javascript
  const { user, loading, isAuthenticated, mustChangePassword, semLigacao } = useAuth();
  // De ONDE veio
```

e, ainda no `ProtectedRoute`, substituir

```javascript
  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
```

por

```javascript
  if (!isAuthenticated && semLigacao) return <SemLigacao />;

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
```

3.3b — No `RoleRedirect` (a rota `/`), o mesmo ramo. Substituir

```javascript
const RoleRedirect = () => {
  const { user, loading, isAuthenticated, mustChangePassword } = useAuth();
```

por

```javascript
const RoleRedirect = () => {
  const { user, loading, isAuthenticated, mustChangePassword, semLigacao } = useAuth();
  // Antes do `loading` sem perigo: o `semLigacao` só fica de pé com o `loading` já em baixo.
  if (!isAuthenticated && semLigacao) return <SemLigacao />;
```

(O `ChangePasswordRoute` tem um `if (!isAuthenticated) { return <Navigate to="/login" replace />; }` igual, mas fica: o `/alterar-senha` só se abre depois de um login.)

3.4 — Entre o fim do `ProtectedRoute` e a linha `// Change Password Route - only accessible when must_change_password is true`, acrescentar:

```javascript
// As rotas da app «Gestão Lisbonb»: o login do portal e, na casca com Face ID,
// a Barreira. **TODAS as rotas /bolso passam por aqui**: com o Face ID ligado,
// os pedidos do `lib/bolso.js` esperam que a Barreira abra — uma rota /bolso
// sem ela ficava à espera para sempre (guardado em test_sessao_do_bolso.py).
const RotaDoBolso = ({ children }) => (
  <ProtectedRoute allowedRoles={['admin', 'gerente', 'contabilista']}>
    <Barreira>{children}</Barreira>
  </ProtectedRoute>
);

```

3.5 — As rotas. Ver como estão:

```bash
grep -n 'path="/bolso' /Users/matheus.moraes/Developer/RH-calendario/frontend/src/App.js
```

No main `57d5f6f` a de `/bolso` é este bloco de cinco linhas, e a Fase 2 pôs a de `/bolso/calendario` a seguir com a mesma forma (`<ProtectedRoute …><BolsoCalendario /></ProtectedRoute>`):

```javascript
      <Route path="/bolso" element={
        <ProtectedRoute allowedRoles={['admin', 'gerente', 'contabilista']}>
          <BolsoApp />
        </ProtectedRoute>
      } />
```

Substituir os DOIS blocos inteiros (de `<Route path="/bolso` até ao `} />` de cada um) por estas duas linhas, mantendo o comentário que está por cima:

```javascript
      <Route path="/bolso" element={<RotaDoBolso><BolsoApp /></RotaDoBolso>} />
      <Route path="/bolso/calendario" element={<RotaDoBolso><BolsoCalendario /></RotaDoBolso>} />
```

- [ ] **Passo 4: `BolsoApp.js`**

4.1 — Substituir

```javascript
      if (status === 401) { logout(); navigate('/login'); return; }
```

por

```javascript
      // 401: o `lib/bolso.js` já tentou a re-entrada pelo Face ID e não deu.
      // Só `logout()`: o ProtectedRoute leva ao login COM o `state.from`, e
      // depois de entrar volta-se a este ecrã (era o `/admin/resumo`).
      if (status === 401) { logout(); return; }
```

4.2 — Arrumar o `navigate`. A Fase 2 (Tarefa 11, troca 8) tirou o «Terminar sessão» do fundo do `BolsoApp` para o menu, por isso o 401 era o último uso do `navigate` neste ficheiro. Apagar a linha `import { useNavigate } from 'react-router-dom';` e a linha `  const navigate = useNavigate();`, e trocar `  }, [logout, navigate]);` (o fim do `carregar`) por `  }, [logout]);`. Confirmar:

```bash
grep -n "navigate\|Terminar sessão" /Users/matheus.moraes/Developer/RH-calendario/frontend/src/pages/bolso/BolsoApp.js
```

Esperado: nada. (Se aparecer alguma linha, a Fase 2 ficou diferente do seu plano: parar e perceber antes de seguir.)

- [ ] **Passo 5: `BolsoCalendario.js` e `PainelIda.js` (Fase 2)**

O `BolsoCalendario` da Fase 2 (Tarefa 13) não chama `navigate('/login')` directamente: tem `const semSessao = useCallback(() => { logout(); navigate('/login'); }, [logout, navigate]);` e chama `semSessao()` nos dois ramos do 401. O `semSessao` sai.

5.1 — Em `frontend/src/pages/bolso/BolsoCalendario.js`, substituir

```javascript
  const semSessao = useCallback(() => { logout(); navigate('/login'); }, [logout, navigate]);

  const carregar = useCallback(async () => {
```

por

```javascript
  // 401 nos pedidos de baixo: o `lib/bolso.js` já tentou a re-entrada pelo Face ID
  // e não deu. Só `logout()`: o ProtectedRoute leva ao login COM o `state.from`, e
  // depois de entrar volta-se a este ecrã.
  const carregar = useCallback(async () => {
```

5.2 — No mesmo ficheiro, as duas linhas iguais (uma no `carregar`, outra no `carregarContagem`)

```javascript
      if (e?.response?.status === 401) { semSessao(); return; }
```

passam ambas a

```javascript
      if (e?.response?.status === 401) { logout(); return; }
```

5.3 — As dependências: `  }, [ano, mes, semSessao]);` → `  }, [ano, mes, logout]);` (fim do `carregar`) e `  }, [ano, semSessao]);` → `  }, [ano, logout]);` (fim do `carregarContagem`).

5.4 — O `navigate` deixou de ser usado: apagar a linha `import { useNavigate } from 'react-router-dom';` e a linha `  const navigate = useNavigate();`. Confirmar:

```bash
grep -n "navigate\|semSessao" /Users/matheus.moraes/Developer/RH-calendario/frontend/src/pages/bolso/BolsoCalendario.js
```

Esperado: nada. (O `useCallback` continua importado: o `carregar` usa-o.)

5.5 — Em `frontend/src/pages/bolso/PainelIda.js`, logo a seguir a `import { Sheet, SheetClose, SheetContent, SheetTitle } from '@/components/ui/sheet';` acrescentar:

```javascript
import { useAuth } from '@/contexts/AuthContext';
```

5.6 — Logo a seguir a `export default function PainelIda({ painel, dados, hoje, onFechar, onGuardado }) {` acrescentar:

```javascript
  const { logout } = useAuth();
```

5.7 — No `catch` do `gravar`, substituir

```javascript
    } catch (e) {
      setErro(mensagemDeErro(e));
      setAGravar(false);
    }
  };
```

por

```javascript
    } catch (e) {
      // 401: o `lib/bolso.js` já tentou a re-entrada pelo Face ID e não deu → login
      // normal (desenho §5.4). Mostrar o erro deixava a pessoa num painel sem sessão.
      if (e?.response?.status === 401) { logout(); return; }
      setErro(mensagemDeErro(e));
      setAGravar(false);
    }
  };
```

5.8 — No `catch` do `apagar`, substituir

```javascript
    } catch (e) {
      setErro(mensagemDeErro(e));
      setAGravar(false);
      setConfirmarApagar(false);
```

por

```javascript
    } catch (e) {
      if (e?.response?.status === 401) { logout(); return; }
      setErro(mensagemDeErro(e));
      setAGravar(false);
      setConfirmarApagar(false);
```

- [ ] **Passo 6: `partilhado.js` — o `MenuLateral`**

O `MenuLateral` é o da Tarefa 11 do plano da Fase 2 (`export function MenuLateral({ aberto, onFechar, actual })`). Os textos abaixo são os desse plano; se a revisão da Fase 2 os tiver mudado, localizar com

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/frontend/src/pages/bolso && grep -n "export function MenuLateral\|useAuth()\|Terminar sessão\|</nav>\|navigate('/login')" partilhado.js
```

e aplicar o mesmo sentido.

6.1 — Junto aos outros imports do topo de `partilhado.js`, acrescentar:

```javascript
import { UsarFaceId } from './Barreira';
```

6.2 — Dentro do `MenuLateral`, substituir

```javascript
  const { logout, user } = useAuth();
```

por

```javascript
  const { terminarSessao, user } = useAuth();
```

6.3 — No botão do «Terminar sessão», substituir

```javascript
            type="button" onClick={() => { onFechar(); logout(); navigate('/login'); }}
```

por

```javascript
            type="button" onClick={() => { onFechar(); terminarSessao(); }}
```

(Sem navegar: o `logout()` dentro do `terminarSessao()` basta, e o `ProtectedRoute` leva ao login com o `state.from`. O `navigate` continua a servir o `ir(caminho)` dos destinos.)

6.4 — O item novo, logo a seguir aos destinos e dentro do `<nav>`, com a mesma `className` dos botões dos destinos (sem o realce do ecrã actual). Substituir

```javascript
              </button>
            ))}
          </nav>
```

por

```javascript
              </button>
            ))}
            <UsarFaceId
              className="w-full h-12 px-4 flex items-center gap-3 text-left text-[15px] font-semibold
                         active:bg-accent/60 focus-visible:outline-none focus-visible:ring-2
                         focus-visible:ring-ring focus-visible:ring-inset"
            />
          </nav>
```

Ordem final do menu, como no desenho §4: Faturação, Calendário, Usar Face ID, Terminar sessão. O item só aparece na casca com a peça nativa e com o Face ID por ligar para esta conta: no browser e nos testes da Fase 2 (sem peça e com um `user` sem email) desenha `null`, e o `test_o_menu_abre_com_faturacao_calendario_e_terminar_sessao` continua a ver só `["Faturação", "Calendário"]` no `<nav>`.

- [ ] **Passo 7: Correr e ver passar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/fin/test_sessao_do_bolso.py tests/fin/test_caminhos_do_bolso.py tests/calendario/test_menu_do_bolso.py tests/calendario/test_ecra_do_calendario.py tests/calendario/test_painel_da_ida.py -q
cd /Users/matheus.moraes/Developer/RH-calendario/backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest -q 2>&1 | tail -3
```

Esperado: o primeiro só com `passed` e 0 skipped — `51` de `test_sessao_do_bolso.py` mais os do guarda de caminhos e os três da Fase 2 (com os 2 casos novos do painel). A suite inteira: `0 failed`, `passed` = o da linha de base (Tarefa 1, Passo 1) **+ 53** (51 deste ficheiro + 2 do painel; o teste renomeado do calendário não conta a mais), e `skipped` **igual** ao da linha de base. Se o `skipped` subiu, há testes a saltar em silêncio — parar e ver porquê (`-rs`).

- [ ] **Passo 8: Prova por mutação** (repor depois de cada uma)

1. Em `App.js`, a linha da rota `/bolso/calendario` → `<Route path="/bolso/calendario" element={<ProtectedRoute allowedRoles={['admin', 'gerente', 'contabilista']}><BolsoCalendario /></ProtectedRoute>} />` — `-k rotas_do_bolso` → `1 failed`.
2. No `RotaDoBolso`, `<Barreira>{children}</Barreira>` → `{children}` — `-k rotas_do_bolso` → `1 failed`.
3. No `ProtectedRoute`, apagar a linha `  if (!isAuthenticated && semLigacao) return <SemLigacao />;` — `-k sem_ligacao_antes` → `1 failed` (`ProtectedRoute`).
3b. No `RoleRedirect`, apagar a mesma linha — `-k sem_ligacao_antes` → `1 failed` (`RoleRedirect`).
4. Em `BolsoApp.js`, `if (status === 401) { logout(); return; }` → `if (status === 401) { logout(); navigate('/login'); return; }` — `-k a_mao` → `1 failed` (o guarda é de texto: apanha-o mesmo sem o `useNavigate` no ficheiro).
5. Em `partilhado.js`, apagar a linha do `<UsarFaceId … />` — `-k a_mao` → `1 failed`.
6. Em `BolsoCalendario.js`, no `carregar`, `      if (e?.response?.status === 401) { logout(); return; }` → `      if (e?.response?.status === 401) { return; }` — `tests/calendario/test_ecra_do_calendario.py -k um_401` → `1 failed` (`[]`). (O guarda de texto não a apanha: a linha igual do `carregarContagem` continua lá. É o teste do ecrã que a prende.)
7. Em `partilhado.js`, `onClick={() => { onFechar(); terminarSessao(); }}` → `onClick={() => { onFechar(); }}` — `tests/calendario/test_menu_do_bolso.py -k terminar_sessao_esquece` → `1 failed` (`[]`).
8. Em `PainelIda.js`, no `catch` do `gravar`, apagar a linha `      if (e?.response?.status === 401) { logout(); return; }` — `tests/calendario/test_painel_da_ida.py -k um_401` → `1 failed` (caso `POST`: `erroAVista: True`, sem `logout`).
9. Em `PainelIda.js`, no `catch` do `apagar`, apagar a mesma linha — `tests/calendario/test_painel_da_ida.py -k um_401` → `1 failed` (caso `DELETE`).

- [ ] **Passo 9: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add frontend/src/App.js frontend/src/pages/bolso/BolsoApp.js frontend/src/pages/bolso/partilhado.js \
        frontend/src/pages/bolso/BolsoCalendario.js frontend/src/pages/bolso/PainelIda.js \
        backend/tests/fin/test_sessao_do_bolso.py backend/tests/bolso_js.py \
        backend/tests/calendario/test_menu_do_bolso.py backend/tests/calendario/test_ecra_do_calendario.py \
        backend/tests/calendario/test_painel_da_ida.py
git status --short
git commit -F - <<'MSG'
Bolso: Barreira em todas as rotas, «Sem ligação» e o 401 com state.from

As rotas /bolso e /bolso/calendario passam por RotaDoBolso (login do
portal + Barreira): com o Face ID ligado os pedidos esperam pela Barreira,
e uma rota sem ela ficava à espera para sempre. O ProtectedRoute e o
RoleRedirect (a rota /) mostram «Sem ligação — tentar de novo» quando o
arranque não teve resposta (também no portal no browser). Os ecrãs do
bolso deixam de mandar para o login à mão (o BolsoApp e o semSessao do
calendário): o logout() basta e o ProtectedRoute leva o state.from, para
se voltar ao ecrã de onde se veio. Um 401 no painel da ida também sai para
o login, em vez de um erro num painel já sem sessão. O menu ganha «Usar
Face ID»; Terminar sessão esquece o Face ID deste telemóvel.

A app do ponto é o mesmo frontend/ (Capacitor): a próxima build dela leva
o «Sem ligação» no lugar do login quando o servidor não responde ao abrir.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
MSG
```

(O `git status --short` antes do commit tem de mostrar só ficheiros desta tarefa, todos já no índice.)

---

### Tarefa 8: ensaio local no browser (sem a peça nativa: tudo como hoje + «Sem ligação»)

Os testes provam as peças e o fio; o que se vê só se vê a correr. No browser não há peça nativa, por isso este ensaio prova o que **não** pode mudar (login, painel, calendário, menu sem «Usar Face ID») e as duas correcções (o `state.from` depois de um 401 e o «Sem ligação»). A barreira e a pergunta do Face ID vêem-se na Tarefa 11, no simulador.

**Ficheiros:**
- Modificar (fora do repositório): `/Users/matheus.moraes/Library/CloudStorage/OneDrive-Pessoal/Claude/.claude/launch.json`
- Criar (fora do repositório, nunca versionados): `$HOME/.cache/lisbonb-calendario-local/fase3/{jwt,senha,mongo/,mongod.log}`
- Testes: o ensaio em si (nada a commitar)

**Interfaces:**
- Consome: o site com as Tarefas 1-7; o backend do ramo (inclui as rotas do calendário da Fase 2); as ferramentas do painel do browser (`preview_start`, `navigate`, `resize_window`, `get_page_text`, `find`, `form_input`, `computer`, `javascript_tool`, `read_console_messages`).
- Produz: as entradas `rh-calendario-f3-api` (porta 8013) e `rh-calendario-f3-web` (porta 3013) no `launch.json`, que a Tarefa 11 reusa; a conta de ensaio `gestora.ensaio@example.com` (admin master LOCAL, criada pelo `ensure_master_admin_exists` a partir do `ADMIN_EMAIL`/`ADMIN_PASSWORD`).

- [ ] **Passo 1: Um `node_modules` com tudo**

O `node_modules` partilhado (`~/Developer/RH/frontend/node_modules`) não tem o `leaflet` que o CRM pôs no `package.json` (medido a 2026-10-15): os testes não precisam dele, mas o `craco start` não compila sem ele. Não se instala nada em `~/Developer/RH` (é de outra sessão).

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/frontend
ls node_modules/leaflet/package.json 2>/dev/null || {
  rm node_modules   # é um atalho: sem barra no fim, apaga só o atalho
  export PATH="$HOME/.local/node/bin:$PATH"
  yarn install --frozen-lockfile --network-timeout 600000
}
ls node_modules/leaflet/package.json node_modules/@babel/core/package.json
cd ../backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/fin/test_sessao_do_bolso.py -q
```

Esperado: os dois `package.json` existem; `51 passed`, 0 skipped (agora contra o `node_modules` desta árvore).

- [ ] **Passo 2: Os segredos de ensaio (só locais)**

```bash
D="$HOME/.cache/lisbonb-calendario-local/fase3"; mkdir -p "$D/mongo"; chmod 700 "$D"
[ -f "$D/senha" ] || python3 -c "import secrets; print(secrets.token_urlsafe(16))" > "$D/senha"
[ -f "$D/jwt" ]   || python3 -c "import secrets; print(secrets.token_urlsafe(32))" > "$D/jwt"
chmod 600 "$D/senha" "$D/jwt"; ls -l "$D"
```

A senha lê-se do ficheiro quando for precisa e **nunca** se escreve no chat.

- [ ] **Passo 3: As duas entradas no `launch.json`**

Ler `/Users/matheus.moraes/Library/CloudStorage/OneDrive-Pessoal/Claude/.claude/launch.json` e acrescentar ao array `configurations` (se já existirem entradas com estes nomes, substituí-las):

```json
    {
      "name": "rh-calendario-f3-api",
      "runtimeExecutable": "bash",
      "runtimeArgs": [
        "-c",
        "D=$HOME/.cache/lisbonb-calendario-local/fase3; nc -z 127.0.0.1 27098 || /opt/homebrew/bin/mongod --dbpath $D/mongo --port 27098 --bind_ip 127.0.0.1 --fork --logpath $D/mongod.log >/dev/null; cd $HOME/Developer/RH-calendario/backend && MONGO_URL=mongodb://127.0.0.1:27098 DB_NAME=rh_calendario_f3_local POS_JWT_SECRET=pos-ensaio-local ADMIN_EMAIL=gestora.ensaio@example.com JWT_SECRET=$(cat $D/jwt) ADMIN_PASSWORD=$(cat $D/senha) exec $HOME/Developer/RH/backend/.venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8013"
      ],
      "port": 8013
    },
    {
      "name": "rh-calendario-f3-web",
      "runtimeExecutable": "bash",
      "runtimeArgs": [
        "-c",
        "cd $HOME/Developer/RH-calendario/frontend && export PATH=$HOME/.local/node/bin:$PATH BROWSER=none PORT=3013 REACT_APP_BACKEND_URL=http://localhost:8013 && exec npx craco start"
      ],
      "port": 3013
    }
```

O `JWT_SECRET` e a senha vêm dos ficheiros a cada arranque: é assim que os Passos 7 e 8 (e a Tarefa 11) forçam «sessão expirada» e «senha trocada» sem tocar no código.

- [ ] **Passo 4: Arrancar e entrar**

1. `preview_start` com `name: "rh-calendario-f3-api"`; `preview_logs` até aparecer `Application startup complete`.
2. `preview_start` com `name: "rh-calendario-f3-web"`; `preview_logs` com `search: "Compiled"` até aparecer `Compiled` (ou `Compiled with warnings` — os avisos `react-hooks/exhaustive-deps` do `AuthContext.js` e do `LoginPage.js` já existiam).
3. `resize_window` com `preset: "mobile"` e `colorScheme: "light"`.
4. `navigate` para `http://localhost:3013/bolso`. Esperado: vai parar ao `/login` (`get_page_text` com «Bem-vindo de volta»).
5. Entrar: `find` «login-email» e «login-password»; `form_input` no email com `gestora.ensaio@example.com`; ler a senha com `cat "$HOME/.cache/lisbonb-calendario-local/fase3/senha"` e pô-la no campo da palavra-passe com `form_input`; carregar em «Entrar».

Esperado: chega a `/bolso` (o `state.from`) **sem** nenhuma pergunta de Face ID (`get_page_text` sem «Usar Face ID para entrar?»).

- [ ] **Passo 5: Sem a peça nativa, o menu fica como na Fase 2**

Abrir o ☰. Esperado: Faturação, Calendário, Terminar sessão — e **nenhum** «Usar Face ID». Tocar em «Calendário»: abre `/bolso/calendario` com os dados (sem spinner pendurado — prova de que a `Barreira` não segura nada sem Face ID). `screenshot` do menu aberto.

- [ ] **Passo 6: Terminar sessão e voltar ao mesmo sítio**

No `/bolso/calendario`, ☰ → «Terminar sessão». Esperado: `/login`; `javascript_tool` com `localStorage.getItem('token')` → `null`. Entrar outra vez (Passo 4.5). Esperado: volta a `/bolso/calendario`.

- [ ] **Passo 7: Um 401 a meio leva o `state.from`**

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > "$HOME/.cache/lisbonb-calendario-local/fase3/jwt"
```

`preview_stop` da API e `preview_start` outra vez (`rh-calendario-f3-api`); esperar `Application startup complete`. No browser, ainda em `/bolso/calendario`, mudar de mês (›) para disparar um pedido. Esperado: vai para `/login`; `javascript_tool` com `JSON.stringify(window.history.state && window.history.state.usr)` → contém `"from":"/bolso/calendario"`. Entrar: volta a `/bolso/calendario` (antes desta fase ia para `/admin/resumo`).

- [ ] **Passo 8: «Sem ligação — tentar de novo»**

1. `preview_stop` da API. No browser, `navigate` para `http://localhost:3013/bolso` (recarregar). Esperado, ~3 s depois (as três tentativas): «Sem ligação», «Não foi possível falar com o servidor.» e o botão «Tentar de novo» — **não** o login. `screenshot` a 375 px, claro.
2. `resize_window` com `colorScheme: "dark"`, recarregar, esperar, `screenshot`. Ver que o texto se lê e o botão tem contraste (o par `--primary`/`--primary-foreground` do portal no escuro é a dívida conhecida de 3,4:1 — se o botão sair assim, anotar; não é desta fase).
3. O mesmo no portal: `navigate` para `http://localhost:3013/admin` → «Sem ligação» (o desenho aceita: «muda também o portal»); e `navigate` para `http://localhost:3013/` (o `RoleRedirect`, por onde o portal abre) → «Sem ligação», **não** o login.
4. `preview_start` da API; esperar `Application startup complete`; carregar em «Tentar de novo». Esperado: entra no ecrã **sem** pedir a senha (o token ficou).

- [ ] **Passo 9: Consola limpa e repor**

`read_console_messages` com `onlyErrors: true`: nenhum erro que mencione `faceid`, `sessao`, `Barreira` ou `NativeBiometric` (os `ERR_CONNECTION_REFUSED` do Passo 8 são esperados). Depois `resize_window` com `preset: "desktop"` e `colorScheme: "light"`. Deixar a API e o site a correr para a Tarefa 11.

Se algum passo não der o esperado: parar, `superpowers:systematic-debugging`, corrigir com um teste novo em `test_sessao_do_bolso.py` (visto vermelho primeiro) e repetir esta tarefa.

---

### Tarefa 9: publicar o site (fluxo B, com o «sim» do dono) e ver o que ficou no ar

O site primeiro, a build 3 depois (desenho, «Entrega por fases»). Com a build 2 da casca e no browser, a peça nativa não existe: muda só o «Sem ligação» e o regresso ao ecrã de onde se veio. **Nada desta tarefa corre sem o dono dizer «sim» no chat** (empurra para o GitHub e publica em produção).

**Ficheiros:**
- Nenhum ficheiro novo. Mexe no `main` do GitHub e no servidor `root@187.124.4.163` (`~/RH`).
- Testes: a suite inteira; o ficheiro servido em produção.

**Interfaces:**
- Consome: o ramo `matheus-calendario-gestao` com as Tarefas 1-7 commitadas; o skill `fluxo` (B).
- Produz: o `main` com a Fase 3 do site, publicado em `https://rh.lisbonb.com` (é esse o endereço que a casca carrega) e `https://lisbonb.com`.

- [ ] **Passo 1: Suite inteira verde**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario && git status --short
cd backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest -q 2>&1 | tail -3
```

Esperado: `git status` vazio (o `frontend/node_modules` não aparece: está no `.gitignore`); `0 failed`; `passed` = linha de base + 53; `skipped` = o da linha de base.

- [ ] **Passo 2: Pedir o «sim» do dono** (PARAR aqui até ele responder)

Mostrar-lhe:

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git fetch origin
git log --oneline origin/main..HEAD
git diff --stat origin/main...HEAD
```

E dizer, em poucas linhas: «Vou publicar o site da Fase 3 (fluxo B). Com a app que tens hoje (build 2) não muda nada de visível, excepto duas coisas: se o servidor não responder ao abrir, aparece "Sem ligação — tentar de novo" em vez do login (também no portal no browser); e depois de a sessão expirar, voltas ao ecrã onde estavas. O Face ID só aparece com a build 3. Posso?» Só continuar com um «sim» claro.

- [ ] **Passo 3: Guardar o nome do ficheiro servido ANTES**

```bash
ANTES=$(curl -s https://rh.lisbonb.com/bolso | grep -oE '/static/js/main\.[a-z0-9]+\.js' | head -1); echo "$ANTES"
```

- [ ] **Passo 4: Ramo → GitHub, e juntar ao `main` actualizado**

O `main` está aberto noutra árvore (`~/Developer/RH-qr-aplicacoes`), por isso `git checkout main` aqui falha. Junta-se numa árvore temporária, sem tocar nas outras:

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git push -u origin matheus-calendario-gestao
git fetch origin
git worktree add --detach /tmp/rh-main-fase3 origin/main
cd /tmp/rh-main-fase3
git merge --no-ff matheus-calendario-gestao -F - <<'MSG'
merge: calendário Fase 3 — Face ID na Gestão Lisbonb (site) e as duas correcções do login

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
MSG
git log --oneline -3
```

Se o `merge` parar em conflitos: **parar**, `git merge --abort`, explicar ao dono em linguagem simples que ficheiros chocam, e resolver com ele. Nunca forçar.

- [ ] **Passo 5: `main` → GitHub e arrumar a árvore temporária**

```bash
cd /tmp/rh-main-fase3 && git push origin HEAD:main
cd /Users/matheus.moraes/Developer/RH-calendario && git worktree remove /tmp/rh-main-fase3
```

Se o `push` for recusado (`non-fast-forward`: alguém juntou ao `main` entretanto), voltar ao Passo 4 desde o `git fetch origin` (apagar antes a árvore temporária com `git worktree remove --force /tmp/rh-main-fase3`).

- [ ] **Passo 6: Publicar no servidor — só o `main`**

```bash
ssh root@187.124.4.163 'cd ~/RH && git checkout main && git pull && docker compose up -d --build'
curl -s https://rh.lisbonb.com/api/health; echo; curl -s https://lisbonb.com/api/health; echo
```

Esperado: as duas respostas com `healthy`.

- [ ] **Passo 7: O ficheiro servido é o novo** (o `deploy` já entregou código antigo a dizer «concluído»)

```bash
for H in rh.lisbonb.com lisbonb.com; do
  JS=$(curl -s "https://$H/bolso" | grep -oE '/static/js/main\.[a-z0-9]+\.js' | head -1)
  echo "$H $JS"
  curl -s "https://$H$JS" | grep -c 'faceid_recusado'
  curl -s "https://$H$JS" | grep -c 'saiuAs'
done
echo "antes: $ANTES"
```

Esperado: o nome do `main.*.js` **diferente** de `$ANTES`, e as duas contagens ≥ 1 nos dois domínios (marcadores sem acentos de propósito: com acentos o `grep` dá falso negativo). Se o nome não mudou ou dá 0:

```bash
ssh root@187.124.4.163 'cd ~/RH && docker compose build --no-cache frontend && docker compose up -d frontend'
```

e repetir o Passo 7.

- [ ] **Passo 8: O caminho feliz — o que se pode ver daqui, e o que é do dono**

1. No painel do browser (sem entrar — a senha de produção nunca se escreve): `navigate` para `https://rh.lisbonb.com/bolso`. Esperado: o login («Bem-vindo de volta») ou, se o painel já tiver sessão, o bolso; `read_console_messages` com `onlyErrors: true` sem erros de `faceid`/`sessao`/`Barreira`.
2. **DONO** (no iPhone dele, app «Gestão Lisbonb» build 2): abrir a app → como antes (login se a sessão tiver expirado, depois os números); ☰ → Faturação, Calendário, Terminar sessão, **sem** «Usar Face ID»; Terminar sessão → login → entrar → volta ao bolso. Pedir-lhe que confirme no chat. Se algo estiver diferente do que era: parar e tratar antes da Tarefa 10.

- [ ] **Passo 9: Deixar escrito na memória que a app do ponto também leva isto**

O `frontend/` é também a app do ponto dos colaboradores (Capacitor: `frontend/package.json` tem `@capacitor/ios` e `@capacitor/android`), com o código congelado no bundle de cada build. A próxima build dela (AAB/iOS) leva o que acabou de ir para o `main`: o «Sem ligação — tentar de novo» no lugar do login quando o servidor não responde ao abrir, e o `registerPlugin('NativeBiometric')` (inofensivo: sem a peça nativa o `isPluginAvailable` dá `false` e nada do Face ID actua). Acrescentar uma linha com a data e o commit do merge a `/Users/matheus.moraes/.claude/projects/-Users-matheus-moraes-Library-CloudStorage-OneDrive-Pessoal-Claude/memory/rh-lisbonb-project.md`, para quem fizer essa build saber o que muda nela.

---

### Tarefa 10: a casca — peça nativa, texto do Face ID e build 3

Só a casca (`app-bolso/`). A peça entra pelo `npm` com a versão fixa e o `npx cap sync ios` acrescenta o pod; o `Info.plist` ganha o texto que o iPhone mostra ao pedir licença (sem ele o iOS **fecha a app** no primeiro pedido de Face ID); o número da build passa a 3.

**Ficheiros:**
- Criar: `backend/tests/fin/test_casca_do_bolso.py`
- Modificar: `app-bolso/package.json`, `app-bolso/package-lock.json` (pelo `npm`)
- Modificar: `app-bolso/ios/App/Podfile`, `app-bolso/ios/App/Podfile.lock` (pelo `npx cap sync ios`)
- Modificar: `app-bolso/ios/App/App/Info.plist` (a seguir a `ITSAppUsesNonExemptEncryption`, linhas 5-6)
- Modificar: `app-bolso/ios/App/App.xcodeproj/project.pbxproj` (`CURRENT_PROJECT_VERSION`, linhas 351 e 372)
- Testes: `backend/tests/fin/test_casca_do_bolso.py`

**Interfaces:**
- Consome: nada das tarefas anteriores (o site já no ar desde a Tarefa 9 é o que a casca vai carregar).
- Produz: a casca com o plugin `NativeBiometric` registado no iOS — é o que faz o `Capacitor.isPluginAvailable('NativeBiometric')` do site passar a `true`; `App.app` compilado para o simulador em `$HOME/.cache/lisbonb-calendario-local/fase3/sim-build/Build/Products/Debug-iphonesimulator/App.app` (usado na Tarefa 11).

- [ ] **Passo 1: Escrever o guarda que falha**

Criar `backend/tests/fin/test_casca_do_bolso.py`:

```python
"""A casca iOS «Gestão Lisbonb» (`app-bolso/`): o que vai no TestFlight como build 3.

A casca carrega o site que está no ar; o que ela própria leva é pouco, e cada
coisa daqui é uma build nova se sair errada:

- a peça nativa do Face ID, numa versão FIXA — a 6.0.4 é a única que aceita o
  Capacitor 6 e traz as cinco funções de que o site precisa; um `^` deixava o
  `npm install` trazer outra;
- o texto que o iPhone mostra ao pedir licença para o Face ID (sem ele, o iOS
  fecha a app no primeiro pedido);
- o número da build (o App Store Connect recusa um número repetido);
- o endereço que a casca abre: o ensaio no simulador troca-o por um local, e
  uma build enviada assim abria um ecrã branco nos telemóveis dos gestores.
"""
import json
import re
from pathlib import Path

_CASCA = Path(__file__).resolve().parents[3] / "app-bolso"
_IOS = _CASCA / "ios" / "App"


def test_a_casca_da_build_3_leva_o_face_id_e_abre_a_producao():
    pacote = json.loads((_CASCA / "package.json").read_text(encoding="utf-8"))
    assert pacote["dependencies"].get("@capgo/capacitor-native-biometric") == "6.0.4"

    plist = (_IOS / "App" / "Info.plist").read_text(encoding="utf-8")
    assert re.search(
        r"<key>NSFaceIDUsageDescription</key>\s*<string>Usamos o Face ID para entrar na "
        r"Gestão Lisbonb sem escrever a senha\.</string>",
        plist,
    )
    # O ensaio no simulador abre a rede local; isso nunca vai numa build.
    assert "NSAppTransportSecurity" not in plist

    projecto = (_IOS / "App.xcodeproj" / "project.pbxproj").read_text(encoding="utf-8")
    assert re.findall(r"CURRENT_PROJECT_VERSION = (\d+);", projecto) == ["3", "3"]
    assert re.findall(r"MARKETING_VERSION = ([\d.]+);", projecto) == ["1.0", "1.0"]

    config = json.loads((_CASCA / "capacitor.config.json").read_text(encoding="utf-8"))
    assert config["server"]["url"] == "https://rh.lisbonb.com/bolso"
    assert config["server"].get("cleartext") is False

    assert "CapgoCapacitorNativeBiometric" in (_IOS / "Podfile").read_text(encoding="utf-8")
    assert "CapgoCapacitorNativeBiometric" in (_IOS / "Podfile.lock").read_text(encoding="utf-8")
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/fin/test_casca_do_bolso.py -q
```

Esperado: `1 failed` — `assert None == '6.0.4'` (a peça ainda não está no `package.json`).

- [ ] **Passo 3: A peça, com a versão fixa**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/app-bolso
export PATH="/opt/homebrew/bin:$HOME/.local/node/bin:$PATH" LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
npm ci
npm install --save-exact @capgo/capacitor-native-biometric@6.0.4
grep -n '"@capgo/capacitor-native-biometric"' package.json
```

Esperado: `"@capgo/capacitor-native-biometric": "6.0.4"` — sem `^`. (O `app-bolso/node_modules` está no `.gitignore` da casca.)

- [ ] **Passo 4: O texto do Face ID**

Em `app-bolso/ios/App/App/Info.plist`, substituir

```xml
	<key>ITSAppUsesNonExemptEncryption</key>
	<false/>
```

por

```xml
	<key>ITSAppUsesNonExemptEncryption</key>
	<false/>
	<key>NSFaceIDUsageDescription</key>
	<string>Usamos o Face ID para entrar na Gestão Lisbonb sem escrever a senha.</string>
```

```bash
plutil -lint /Users/matheus.moraes/Developer/RH-calendario/app-bolso/ios/App/App/Info.plist
```

Esperado: `… OK`.

- [ ] **Passo 5: Build 3**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/app-bolso/ios/App
sed -i '' 's/CURRENT_PROJECT_VERSION = 2;/CURRENT_PROJECT_VERSION = 3;/' App.xcodeproj/project.pbxproj
grep -c 'CURRENT_PROJECT_VERSION = 3;' App.xcodeproj/project.pbxproj
```

Esperado: `2` (Debug e Release). O `MARKETING_VERSION` fica `1.0`.

- [ ] **Passo 6: `cap sync` (instala o pod)**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/app-bolso
export PATH="/opt/homebrew/bin:$HOME/.local/node/bin:$PATH" LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
npx cap sync ios
grep -n "CapgoCapacitorNativeBiometric" ios/App/Podfile ios/App/Podfile.lock
grep -c "rh.lisbonb.com/bolso" ios/App/App/capacitor.config.json
```

Esperado: o `cap sync` lista 2 plugins (`@capacitor/status-bar` e `@capgo/capacitor-native-biometric`) e acaba sem erro; o pod aparece no `Podfile` (`pod 'CapgoCapacitorNativeBiometric', :path => '../../node_modules/@capgo/capacitor-native-biometric'`) e no `Podfile.lock`; o `capacitor.config.json` gerado continua a apontar para produção (`1`). Se o `pod install` falhar com `Unicode Normalization not appropriate for ASCII-8BIT`, é o locale: confirmar o `LANG`/`LC_ALL` desta mesma linha de comandos.

- [ ] **Passo 7: Correr o guarda e ver passar**

Mesmo comando do Passo 2. Esperado: `1 passed`.

- [ ] **Passo 8: Compila? (para o simulador)**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/app-bolso/ios/App
xcodebuild -workspace App.xcworkspace -scheme App -configuration Debug -sdk iphonesimulator \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -derivedDataPath "$HOME/.cache/lisbonb-calendario-local/fase3/sim-build" build 2>&1 | tail -5
ls "$HOME/.cache/lisbonb-calendario-local/fase3/sim-build/Build/Products/Debug-iphonesimulator/App.app/Frameworks" | grep -i biometric
```

Esperado: `** BUILD SUCCEEDED **` e `CapgoCapacitorNativeBiometric.framework` dentro da app (`use_frameworks!` no `Podfile`). Avisos de Swift do plugin (`var` nunca mudada) são do pacote e não se mexe neles.

- [ ] **Passo 9: Prova por mutação**

1. Em `app-bolso/capacitor.config.json`, `"url": "https://rh.lisbonb.com/bolso"` → `"url": "http://localhost:3013/bolso"` — Passo 2 → `1 failed` (`server.url`). Repor.
2. Em `app-bolso/package.json`, `"6.0.4"` → `"^6.0.4"` — `1 failed`. Repor.
3. Em `project.pbxproj`, só uma das duas linhas a `3` (a outra de volta a `2`) — `1 failed` (`['2', '3']`). Repor e confirmar `grep -c` = 2.

- [ ] **Passo 10: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git status --short app-bolso backend/tests/fin
git add app-bolso/package.json app-bolso/package-lock.json app-bolso/ios/App/Podfile app-bolso/ios/App/Podfile.lock \
        app-bolso/ios/App/App/Info.plist app-bolso/ios/App/App.xcodeproj/project.pbxproj \
        backend/tests/fin/test_casca_do_bolso.py
git commit -F - <<'MSG'
Casca da Gestão Lisbonb: peça do Face ID (6.0.4 fixa) e build 3

O @capgo/capacitor-native-biometric 6.0.4 é a única versão que aceita o
Capacitor 6 e traz isAvailable, verifyIdentity e as três operações do
Keychain numa peça só; vai com a versão fixa. O Info.plist leva o texto do
Face ID (sem ele o iOS fecha a app no primeiro pedido) e a build passa a 3.
Um guarda prende tudo isto e o server.url de produção: o ensaio no
simulador troca-o por um local, e uma build enviada assim abria um ecrã
branco nos telemóveis dos gestores.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
MSG
```

(O `git status --short` antes do `add` só pode mostrar estes sete ficheiros. Se aparecer outro, perceber porquê antes de commitar.)

---

### Tarefa 11: ensaio da casca no simulador iOS (o teste 13 do desenho, primeira metade)

O simulador corre a peça nativa a sério (Keychain e Face ID simulados pelo iOS). Para não escrever a senha de produção — que nunca se escreve — a casca aponta **temporariamente** para o site e a API locais da Tarefa 8, com a conta de ensaio. Tudo o que se muda para o ensaio volta atrás no fim e **não** se commita (o guarda da Tarefa 10 apanha um esquecimento).

**Ficheiros:**
- Modificar **temporariamente** (repor no Passo 9): `app-bolso/capacitor.config.json`, `app-bolso/ios/App/App/Info.plist`
- Testes: o ensaio; no fim, `backend/tests/fin/test_casca_do_bolso.py` outra vez verde

**Interfaces:**
- Consome: as entradas `rh-calendario-f3-api`/`rh-calendario-f3-web` e os ficheiros `$HOME/.cache/lisbonb-calendario-local/fase3/{jwt,senha}` (Tarefa 8); a casca da Tarefa 10; a ferramenta do simulador (`mcp__Claude_Code_iOS_Simulator__control`: `attach`, `launch`, `screenshot`, `tap`, `text`, `button`, `touch_path`).
- Produz: capturas de ecrã de cada cenário, para mostrar ao dono.

Comandos que se repetem (definir uma vez por terminal):

```bash
export PATH="/opt/homebrew/bin:$HOME/.local/node/bin:$PATH" LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
D="$HOME/.cache/lisbonb-calendario-local/fase3"
APP="$D/sim-build/Build/Products/Debug-iphonesimulator/App.app"
# Face ID do simulador: rosto certo / rosto errado (com o pedido de Face ID no ecrã)
ROSTO_CERTO='xcrun simctl spawn booted notifyutil -p com.apple.BiometricKit_Sim.pearl.match'
ROSTO_ERRADO='xcrun simctl spawn booted notifyutil -p com.apple.BiometricKit_Sim.pearl.nomatch'
```

«Esperar mais de 5 minutos fora»: com a app em segundo plano, correr `sleep 310` com `run_in_background: true` e continuar quando acabar (o `sleep` em primeiro plano está bloqueado).

- [ ] **Passo 1: Apontar a casca para o local (temporário)**

Em `app-bolso/capacitor.config.json`, substituir

```json
    "url": "https://rh.lisbonb.com/bolso",
    "cleartext": false
```

por

```json
    "url": "http://localhost:3013/bolso",
    "cleartext": true
```

Em `app-bolso/ios/App/App/Info.plist`, logo a seguir à `<string>` do `NSFaceIDUsageDescription`, acrescentar (o ATS do iOS bloqueia `http://` sem isto):

```xml
	<key>NSAppTransportSecurity</key>
	<dict>
		<key>NSAllowsLocalNetworking</key>
		<true/>
	</dict>
```

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/app-bolso && npx cap copy ios
grep -c "localhost:3013" ios/App/App/capacitor.config.json
cd ios/App && xcodebuild -workspace App.xcworkspace -scheme App -configuration Debug -sdk iphonesimulator \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -derivedDataPath "$D/sim-build" build 2>&1 | tail -2
curl -s http://localhost:8013/api/health; echo; curl -s -o /dev/null -w '%{http_code}\n' http://localhost:3013/bolso
```

Esperado: `1`; `** BUILD SUCCEEDED **`; a API `healthy` e o site `200` (se não: `preview_start` das entradas da Tarefa 8).

- [ ] **Passo 2: Simulador com Face ID registado, painel aberto, app instalada**

```bash
xcrun simctl boot "iPhone 17 Pro" 2>/dev/null; open -a Simulator
xcrun simctl spawn booted notifyutil -s com.apple.BiometricKit.enrollmentChanged '1'
xcrun simctl spawn booted notifyutil -p com.apple.BiometricKit.enrollmentChanged
```

Depois: `control` com `action: "attach"` e `device: "iPhone 17 Pro"` (o painel para o dono ver); `control` com `action: "launch"` e `app_path` = o `$APP` acima (expandido). Se as linhas `notifyutil` não registarem o rosto (o pedido de Face ID diz que não há rosto), usar o menu do Simulador **Features ▸ Face ID ▸ Enrolled** (pelo skill `anthropic-skills:computer-use`).

- [ ] **Passo 3: Primeiro login com senha → «Usar Face ID para entrar?» → Sim**

1. A app abre no login. `tap` no campo do email; `text` `gestora.ensaio@example.com`; `tap` na palavra-passe; `text` com o conteúdo de `$D/senha` (ler com `cat`, nunca escrever no chat); `tap` em «Entrar».
2. Esperado: o diálogo «Usar Face ID para entrar?» (`screenshot`). `tap` em «Usar Face ID».
3. Esperado: o alerta do iOS a pedir licença, com o texto **«Usamos o Face ID para entrar na Gestão Lisbonb sem escrever a senha.»** (`screenshot`) → `tap` em OK.
4. Com o Face ID a pedir o rosto: `eval "$ROSTO_CERTO"`. Esperado: «Face ID ligado.» e o painel do bolso.

- [ ] **Passo 4: Voltar dentro de 5 minutos não pede nada; a miniatura não mostra números**

1. `button` `HOME`; logo a seguir `xcrun simctl launch booted com.lisbonb.gestao`. Esperado: o painel, **sem** barreira nem Face ID.
2. `button` `HOME`; abrir o selector de apps (`touch_path` a partir de 2 pt acima do fundo, ao centro, a subir até meio do ecrã com uma pausa de ~600 ms no fim); `screenshot`. Esperado: o cartão da «Gestão Lisbonb» mostra a barreira (o rosto e «Entrar como …»), **não** os números. Se mostrar números: guardar o `screenshot` e anotar «miniatura com números»; **não** corrigir nesta fase (a correcção seria nativa, no `AppDelegate` da casca — fora do desenho). A decisão é pedida ao dono na Tarefa 12, Passo 2, **antes** de arquivar: uma build 3 que saísse assim obrigava a uma build 4. Sair do selector com `button` `HOME`.

- [ ] **Passo 5: Mais de 5 minutos fora → barreira, e o que se estava a fazer fica**

1. Abrir a app; ☰ → Calendário → «+ Marcar ida» (abre o painel de baixo). Escolher qualquer coisa nele (por exemplo uma pessoa).
2. `button` `HOME`; `sleep 310` em segundo plano; quando acabar, `xcrun simctl launch booted com.lisbonb.gestao`.
3. Esperado: ecrã opaco «Entrar como gestora.ensaio@example.com», sem nada do calendário à vista (`screenshot`), e o Face ID a pedir o rosto. `eval "$ROSTO_CERTO"`.
4. Esperado: a barreira desaparece e o painel «+ Marcar ida» continua aberto com o que se escolheu.

- [ ] **Passo 6: Rosto errado e cancelar → login normal, Keychain guardado**

1. `button` `HOME`; `sleep 310` em segundo plano; abrir a app → barreira + Face ID.
2. `eval "$ROSTO_ERRADO"` → o iOS mostra que não reconheceu (`screenshot`) → `tap` em «Cancelar».
3. Esperado: o login normal. Entrar com a senha (como no Passo 3.1). Esperado: **sem** pergunta (o Face ID continua ligado para este email; a senha escrita substituiu a guardada) e o painel.

- [ ] **Passo 7: Sessão expirada e senha trocada**

Sessão expirada (as 24 h, forçadas com um segredo novo):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > "$D/jwt"
```

`preview_stop` + `preview_start` de `rh-calendario-f3-api`. Na app: `button` `HOME` e reabrir logo (dentro dos 5 min, sem barreira) — o painel volta a pedir os números, recebe 401, e o Face ID pede o rosto: `eval "$ROSTO_CERTO"`. Esperado: os números, **sem** ecrã de login; `preview_logs` da API com `search: "auth/login"` mostra **um** `POST /api/auth/login` depois do arranque.

Senha trocada (a senha do Keychain deixa de servir):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(16))" > "$D/senha"
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > "$D/jwt"
```

`preview_stop` + `preview_start` da API (o `ensure_master_admin_exists` muda a senha da conta de ensaio). Na app: `HOME` e reabrir → 401 → Face ID → `eval "$ROSTO_CERTO"` → o login com a senha antiga dá 401 → Keychain apagado. Esperado: o ecrã de login. Entrar com a senha NOVA (`cat "$D/senha"`). Esperado: a pergunta «Usar Face ID para entrar?» outra vez → «Usar Face ID» → `eval "$ROSTO_CERTO"` → painel.

- [ ] **Passo 8: Terminar sessão, «Agora não», «Usar Face ID» no menu; app morta e reaberta**

1. ☰ → «Terminar sessão» → login → entrar com a senha → a pergunta aparece (o Face ID foi esquecido) → «Agora não» → painel.
2. ☰ → agora há «Usar Face ID» (`screenshot` do menu) → `tap` → login com o aviso «Entre com a senha para ligar o Face ID.» → entrar → a pergunta → «Usar Face ID» → `eval "$ROSTO_CERTO"` → painel; ☰ → «Usar Face ID» já não aparece.
3. `xcrun simctl terminate booted com.lisbonb.gestao`; `sleep 310` em segundo plano; `xcrun simctl launch booted com.lisbonb.gestao`. Esperado: barreira no arranque → `eval "$ROSTO_CERTO"` → painel.

- [ ] **Passo 9: Repor a casca e confirmar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/app-bolso
git checkout -- capacitor.config.json ios/App/App/Info.plist
npx cap copy ios
grep -c "rh.lisbonb.com/bolso" ios/App/App/capacitor.config.json
git status --short .
cd ../backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/fin/test_casca_do_bolso.py -q
```

Esperado: `1`; `git status` vazio; `1 passed`. Mostrar ao dono as capturas dos Passos 3.3, 4.2, 5.3 e 8.2 (com `SendUserFile`) e o que correu diferente do esperado, se alguma coisa (a miniatura do Passo 4.2 fica para a Tarefa 12, Passo 2).

Se um cenário falhar por defeito do site: parar, `superpowers:systematic-debugging`, teste novo em `test_sessao_do_bolso.py` visto vermelho primeiro, correcção, e — como o site já está no ar — voltar à Tarefa 9 para publicar a correcção antes da Tarefa 12.

---

### Tarefa 12: arquivar a build 3, enviar para o TestFlight e provar no telemóvel do dono

As builds da casca fazem-se **localmente** neste Mac (o Xcode Cloud está desligado desde 2026-09-07 e nunca produziu uma; foi assim que a build 2 subiu). App Store Connect: app id **6809239676**, equipa **P58HVPWKS8** (é `8`, não `B`), grupo de TestFlight **«Gestores»**. Os passos marcados **DONO** são com a conta Apple dele; os marcados **com o «sim» do dono** só correm depois de ele o dizer no chat. O «sim» pede-se **antes de arquivar**: o arquivo já usa a conta dele (`-allowProvisioningUpdates` pode criar ou renovar certificados e perfis no App Store Connect).

**Ficheiros:**
- Nenhum ficheiro do repositório. Cria o arquivo `~/Library/Developer/Xcode/Archives/<data>/GestaoLisbonb-build3.xcarchive` (é a pasta que o Organizer do Xcode lista) e um `ExportOptions.plist` numa pasta temporária.
- Testes: o arquivo em si (número da build, texto do Face ID, `server.url`, a peça lá dentro); o teste no iPhone do dono.

**Interfaces:**
- Consome: a casca da Tarefa 10, reposta na Tarefa 11 (`test_casca_do_bolso.py` verde, `git status` limpo); o site da Tarefa 9 no ar.
- Produz: a build 1.0 (3) no App Store Connect / TestFlight.

- [ ] **Passo 1: Antes de arquivar — a casca é a de produção**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git status --short app-bolso
cd backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/fin/test_casca_do_bolso.py -q
grep -c "rh.lisbonb.com/bolso" ../app-bolso/ios/App/App/capacitor.config.json
```

Esperado: `git status` vazio; `1 passed`; `1`. (O `capacitor.config.json` que vai na app é o GERADO, em `ios/App/App/` — por isso o `grep` além do teste.)

- [ ] **Passo 2: A miniatura e o «sim» do dono** (PARAR até ele responder)

Primeiro, a miniatura do selector de apps (Tarefa 11, Passo 4.2):

- Se mostrou a barreira: nada a decidir.
- Se mostrou **números**: mostrar-lhe a captura (`SendUserFile`) e dizer, em linguagem simples: «No selector de apps, a miniatura da Gestão Lisbonb mostra os números por um instante, apesar da barreira. Tapá-la é uma mudança na parte nativa da app (o `AppDelegate`), que o desenho não previa e que leva o seu próprio desenho e plano. Prefere (a) enviar a build 3 assim e tratar a miniatura numa build seguinte, ou (b) parar aqui e fazê-la primeiro?» Com (b): **parar o plano aqui** — não se arquiva. Com (a): seguir.

Depois, o «sim»: «A build 3 da Gestão Lisbonb (1.0 (3), com o Face ID) está pronta para arquivar e enviar para o App Store Connect com a tua conta Apple — o arquivo pode criar ou renovar certificados e perfis nessa conta. Depois de processada (10 a 30 minutos) aparece no TestFlight, no grupo Gestores. Posso?» Só continuar com um «sim» claro (e, havendo números na miniatura, com a escolha (a)).

- [ ] **Passo 3: Arquivar** (com o «sim» do Passo 2)

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/app-bolso/ios/App
export PATH="/opt/homebrew/bin:$HOME/.local/node/bin:$PATH" LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
ARQ="$HOME/Library/Developer/Xcode/Archives/$(date +%Y-%m-%d)/GestaoLisbonb-build3.xcarchive"
xcodebuild -workspace App.xcworkspace -scheme App -configuration Release \
  -destination 'generic/platform=iOS' -archivePath "$ARQ" -allowProvisioningUpdates archive 2>&1 | tail -3
echo "$ARQ"
```

Esperado: `** ARCHIVE SUCCEEDED **`. Se falhar na assinatura (`No Account for Team "P58HVPWKS8"`, `No profiles for 'com.lisbonb.gestao'`): a sessão da conta Apple no Xcode expirou — **DONO**: Xcode ▸ Settings ▸ Accounts, voltar a entrar com a conta dele; depois repetir este passo.

- [ ] **Passo 4: Ver o que ficou no arquivo**

```bash
APPF="$ARQ/Products/Applications/App.app"
/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$APPF/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APPF/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :NSFaceIDUsageDescription' "$APPF/Info.plist"
/usr/libexec/PlistBuddy -c 'Print :NSAppTransportSecurity' "$APPF/Info.plist" 2>&1 | head -1
grep -c "https://rh.lisbonb.com/bolso" "$APPF/capacitor.config.json"
ls "$APPF/Frameworks" | grep -i biometric
```

Esperado, por esta ordem: `3`; `1.0`; `Usamos o Face ID para entrar na Gestão Lisbonb sem escrever a senha.`; `Print: Entry, ":NSAppTransportSecurity", Does Not Exist`; `1`; `CapgoCapacitorNativeBiometric.framework`. Qualquer outra coisa: parar, não enviar.

- [ ] **Passo 5: Enviar** (com o «sim» do Passo 2, e só se o Passo 4 deu tudo o esperado)

```bash
TMPX=$(mktemp -d -t gestao-build3)
cat > "$TMPX/ExportOptions.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>method</key>
	<string>app-store-connect</string>
	<key>destination</key>
	<string>upload</string>
	<key>teamID</key>
	<string>P58HVPWKS8</string>
	<key>signingStyle</key>
	<string>automatic</string>
	<key>uploadSymbols</key>
	<true/>
	<key>manageAppVersionAndBuildNumber</key>
	<false/>
</dict>
</plist>
PLIST
xcodebuild -exportArchive -archivePath "$ARQ" -exportOptionsPlist "$TMPX/ExportOptions.plist" \
  -exportPath "$TMPX/export" -allowProvisioningUpdates 2>&1 | tail -5
```

Esperado: `** EXPORT SUCCEEDED **` (com `destination = upload`, o `xcodebuild` envia para o App Store Connect). O `manageAppVersionAndBuildNumber = false` impede o Xcode de mudar o número sozinho.

Se o envio falhar por sessão/conta, ou se o App Store Connect recusar o número 3 por já haver um maior: **DONO**, no Xcode: Window ▸ Organizer ▸ Archives ▸ «GestaoLisbonb-build3» ▸ **Distribute App** ▸ **App Store Connect** ▸ **Upload** ▸ seguir com as opções por omissão. (Se o número for recusado, dizer-me qual o App Store Connect aceita: muda-se o `CURRENT_PROJECT_VERSION` e o guarda da Tarefa 10, com um commit, e arquiva-se de novo.)

- [ ] **Passo 6: TestFlight** (**DONO**, no App Store Connect com a conta dele)

1. App Store Connect ▸ Apps ▸ **Gestão Lisbonb** (id 6809239676) ▸ **TestFlight**. Esperar que a build **1.0 (3)** saia de «A processar» (10–30 min; chega um email quando estiver pronta).
2. Em **Grupos ▸ Gestores ▸ Builds**: se a 1.0 (3) não estiver lá, «+» e escolhê-la.
3. Se pedir «Informação de conformidade de exportação»: a casca já declara `ITSAppUsesNonExemptEncryption = NO`, não devia pedir; se pedir, responder que não usa encriptação além da do sistema.
4. Confirmar que os testadores do grupo incluem a Carol e a Débora (elas já têm a app; a build nova aparece-lhes no TestFlight como actualização).

- [ ] **Passo 7: No iPhone do dono** (**DONO**; o teste 13 do desenho, segunda metade)

1. TestFlight ▸ Gestão Lisbonb ▸ **Actualizar** para a 1.0 (3); abrir.
2. Entrar com a senha → «Usar Face ID para entrar?» → **Usar Face ID** → o iPhone pede licença com o texto «Usamos o Face ID para entrar na Gestão Lisbonb sem escrever a senha.» → OK → Face ID → os números.
3. Ir ao ecrã principal, esperar **mais de 5 minutos**, abrir: «Entrar como <o teu email>» → Face ID → os números, sem senha.
4. No dia seguinte (a sessão de 24 h já acabou): abrir → Face ID → os números, **sem** ecrã de login.
5. Dizer-me no chat o que viu (e, se puder, uma captura do passo 3). Depois, a Carol e a Débora fazem o mesmo nos telemóveis delas.

- [ ] **Passo 8: Guardar o estado na memória do projecto**

Actualizar (só os factos novos, com data):
- `/Users/matheus.moraes/.claude/projects/-Users-matheus-moraes-Library-CloudStorage-OneDrive-Pessoal-Claude/memory/bolso-app-gestao.md` — build 3 (Face ID, peça 6.0.4) enviada a <data>, estado no TestFlight, o que o dono viu no telemóvel;
- `/Users/matheus.moraes/.claude/projects/-Users-matheus-moraes-Library-CloudStorage-OneDrive-Pessoal-Claude/memory/calendario-gestao.md` — Fase 3 no ar (site a <data>, commit do merge), build 3 no TestFlight, o resultado do Passo 4.2 da Tarefa 11 (a miniatura do selector de apps) e, se houve, a escolha do dono no Passo 2;
- a linha correspondente em `MEMORY.md` (o índice).

---

## Auto-revisão

### Cobertura do desenho (secção 5 e testes 10, 11, 13, 14)

| Requisito do desenho | Onde |
|---|---|
| Peça `@capgo/capacitor-native-biometric@6.0.4`, versão fixa, regista-se como `NativeBiometric` | T10 (npm `--save-exact`, guarda), T12 P4 |
| `NSFaceIDUsageDescription` com o texto exacto | T10 P4 + guarda; T11 P3.3; T12 P4 |
| Build 3 (`CURRENT_PROJECT_VERSION = 3`) | T10 P5 + guarda; T12 P4 |
| `verifyIdentity` com `useFallback: false` **antes** de ler o Keychain | T1 (`ler`, teste `ler_so_depois…`, mutações) |
| `lib/faceid.js` só actua com `isPluginAvailable('NativeBiometric')`; `registerPlugin` do core 6 do site, sem implementação web | T1 (teste «sem plugin», contador do simulado) |
| 1. Primeiro login com senha → pergunta; Sim guarda o email do servidor e a senha; Não → `faceid_recusado:<email>`; «Usar Face ID» no menu | T2 (`depoisDoLoginComSenha`, `recusar`, `ligarFaceId`), T5 (diálogo, email do servidor, «não» lembrado, nunca com a senha provisória), T4 (`changePassword` leva a senha nova ao Keychain), T6 (`UsarFaceId`), T7 (no `MenuLateral`), T11 P3 e P8 |
| 2. Barreira ao abrir e depois de > 5 min, **até o Face ID passar**; `saiuAs` no `localStorage` ao esconder; sem ele = arranque; dados não se pedem; fecha logo ao esconder | T2 (estado ao carregar, fronteira dos 5 min, `saiuAs` só ao sair com ela aberta), T3 (`esperarBarreira` no cliente), T6 (`<dialog>`, esconder/voltar, esconder com o rosto por passar não abre, sem Face ID possível não abre), T7 (`RotaDoBolso`), T11 P4, P5, P8.3; a miniatura decide-se em T12 P2, antes de arquivar |
| 3. Face ID falhou ou cancelado → `logout()` sem apagar o Keychain | T2 (re-entrada cancelada), T6 (barreira cancelada; Face ID indisponível também → `logout()`), T1 (um pedido de rosto de cada vez: o StrictMode do ensaio não gera um logout falso), T11 P6 |
| 4. Sessão expirada → uma só re-entrada partilhada; Face ID se a barreira não acabou de o fazer; repete o pedido uma vez; falhou → login | T1 (janela de 60 s), T2 (`reentrar`), T3 (repete uma vez, sem ciclo), T4 (401 no arranque), T6 (barreira + re-entrada = um rosto), T7 (um 401 que chegue ao `BolsoApp`, ao `BolsoCalendario` ou ao `PainelIda` → `logout()`), T11 P7 |
| 5. Só um 401 do login apaga o Keychain; 429 e rede mantêm | T2 (parametrizado 401/429/rede), T11 P7 (senha trocada) |
| 6. Terminar sessão = `terminarSessao()`; o `logout()` dos 401 não apaga o Keychain | T4 (teste dos dois), T7 (menu e `BolsoApp`), T8 P6, T11 P8 |
| 7. Dois gestores no mesmo iPhone: fica o último que activou; «Entrar como <email>» | T1 (`guardar` substitui o `faceid_email`; o plugin actualiza o item do mesmo `server`), T6 (o texto da barreira) |
| No servidor não muda nada | Nenhuma tarefa toca no `backend/server.py` |
| Sem ligação: `/auth/me` do arranque sem ser 401/403 → «Sem ligação — tentar de novo» (também no portal) | T4 (`semLigacao`, `tentarDeNovo`, 502 e rede; o login e o logout limpam-no), T7 (`SemLigacao` no `ProtectedRoute` e no `RoleRedirect` + guarda), T8 P8; a app do ponto leva-o na próxima build dela (T7 commit, T9 P9) |
| O 401 do bolso leva `state.from` | T5 (volta a `/bolso/calendario`), T7 (sem `navigate('/login')` + guarda), T8 P7 |
| Teste 10 (Face ID e sessão com o plugin simulado) | T1-T7, `test_sessao_do_bolso.py` (51 testes) + 2 em `test_painel_da_ida.py` |
| Teste 11 (cada teste visto vermelho primeiro) | o passo «Prova por mutação» de T1-T7 e T10 |
| Teste 13 (simulador: rosto certo, errado, cancelar, sessão expirada, senha trocada, app morta e reaberta; depois o telemóvel do dono) | T11 P3-P8; T12 P7 |
| Teste 14 (depois do deploy: ficheiro servido novo + caminho feliz) | T9 P7-P8 |
| Entrega: primeiro o site (com a build 2 nada muda excepto as duas correcções), depois a build 3 | T9 antes de T10-T12; T9 P8.2 (dono confirma a build 2) |

### Nomes que atravessam tarefas (verificados)

- `lib/faceid.js` (T1): `JANELA_MS`, `pluginPresente`, `emailGuardado`, `faceIdLigado`, `temFaceId`, `verificar`, `ler`, `guardar`, `apagar` — usados em T2 (`apagar`, `emailGuardado`, `faceIdLigado`, `guardar`, `ler`, `temFaceId`, `verificar`), T4 (`apagar`, `emailGuardado`, `guardar`), T6 (`emailGuardado`, `temFaceId`, `verificar`).
- `lib/sessao.js` (T2): `CINCO_MINUTOS`, `voltouATempo`, `barreiraFechada`, `abrirBarreira`, `fecharBarreira`, `esperarBarreira`, `ligarEntrada`, `reentrar`, `recusar`, `esquecerRecusa`, `depoisDoLoginComSenha`, `ligarFaceId` — usados em T3 (`esperarBarreira`, `reentrar`), T4 (`abrirBarreira`, `ligarEntrada`, `reentrar`), T5 (`depoisDoLoginComSenha`, `ligarFaceId`, `recusar`), T6 (`abrirBarreira`, `barreiraFechada`, `esquecerRecusa`, `fecharBarreira`, `voltouATempo`).
- `useAuth()` (T4): `semLigacao`, `tentarDeNovo`, `terminarSessao`, `logout` (estável), `changePassword` — usados em T6 (`logout`, `user`) e T7 (`semLigacao`, `tentarDeNovo`, `terminarSessao`, `logout`; o `PainelIda` e o `BolsoCalendario` só `logout`). `lib/faceid.js` em T4: `apagar` como `apagarFaceId`, `emailGuardado`, `guardar` como `guardarFaceId`.
- `pages/bolso/Barreira.js` (T6): `default Barreira`, `UsarFaceId` — usados em T7. `App.js` (T7): `SemLigacao`, `RotaDoBolso`.
- Chaves do `localStorage`: `token` (já existia), `faceid_email`, `faceid_recusado:<email>`, `saiuAs`. Keychain: `server = 'gestao.lisbonb.com'`.
- Python em `test_sessao_do_bolso.py`: `_corre`, `_SRC`, `_LIGADO`, `_RELOGIO` (T1); `_SERVIDOR` (T3); `_EU`, `_ESPERA`, `_ESPIAO` (T4); `_LOGIN`, `_LOGIN_OK`, `_EU_PROVISORIA` (T5); `_BARREIRA`, `_SESSAO_VALIDA` (T6); `_RE_ROTA` (T7). Contagem acumulada: 5 → 19 → 23 → 32 → 37 → 48 → 51 (e, na suite inteira, +2 do `test_painel_da_ida.py` = linha de base + 53). Filtros `-k` das mutações que não se cruzam: `rostos_pedidos`, `limpam_o_aviso` (não contém `sem_ligacao`), `mudar_a_senha`, `provisoria`, `indisponivel`, `rosto_por_passar`, `um_401`.
- Ensaio local: `rh-calendario-f3-api` (8013, mongod 27098, base `rh_calendario_f3_local`) e `rh-calendario-f3-web` (3013); segredos em `$HOME/.cache/lisbonb-calendario-local/fase3/`; conta `gestora.ensaio@example.com`.
- O código das Tarefas 1-6 e o `App.js` da Tarefa 7 (passos 3.1-3.4) foram montados a partir DESTE texto numa cópia do `frontend/src` do main e corridos (Node 20, jsdom 16 do `node_modules` partilhado): os 48 testes das Tarefas 1-6 e o guarda do «Sem ligação» passam; cada mutação das Tarefas 1, 2, 4, 5 e 6 e as duas do `SemLigacao` ficam vermelhas com o número indicado, cada uma contra o ficheiro de testes tal como está no fim da sua tarefa; os «ver falhar» da T4 (`8 failed, 24 passed`) e da T5 (`2 failed, 3 passed`) conferem; os ficheiros mudados passam pelo `babel-preset-react-app`. **Não corridos aqui** (dependem do código da Fase 2, que ainda não existe na árvore): os guardas `rotas_do_bolso` e `a_mao`, as mudanças ao `BolsoCalendario`/`PainelIda` e os testes da Fase 2 que a T7 muda — conferidos por leitura contra o texto do plano da Fase 2 (Tarefas 8, 11, 12 e 13). O executor vê-os vermelhos e verdes na T7, Passos 2, 7 e 8.

### Decisões de implementação que o desenho não fixava (para o revisor)

- **Os ecrãs ficam montados debaixo da barreira** e os pedidos esperam no `lib/bolso.js`, em vez de desmontar os ecrãs: quem estava a marcar uma ida e foi ao WhatsApp não perde o que escreveu.
- **A re-entrada e a espera vivem no cliente `lib/bolso.js`** (um interceptor), não em cada ecrã: apanham também as chamadas da Fase 2 sem as conhecer. Os ecrãs só fazem `logout()` num 401 que lhes chegue.
- **`verificar()` devolve `null` quando o iOS interrompe** (códigos 11, 13, 15): a barreira fica com o botão e não termina a sessão. O desenho diz «falhou ou cancelado → logout()»; interrompido pelo sistema não é nenhum dos dois. E esconder a app com a barreira ainda fechada **não grava `saiuAs`**: senão ir ao ecrã principal com o Face ID a pedir o rosto e voltar logo abria a barreira sem rosto.
- **Sem Face ID possível, a barreira não abre: sai para o login** (desenho §5.2 «até o Face ID passar» e §5.3). Abri-la sozinha deixava entrar sem verificação quem falhasse cinco rostos noutra app. O preço, aceite por ser raro: quem tirar o Face ID à app nas Definições (ou apagar o rosto) escreve a senha a cada abertura até carregar em Terminar sessão, que esquece o Face ID.
- **Um pedido de rosto de cada vez** (`verificar()` partilha o que está a correr): o `<React.StrictMode>` do `craco start` monta a Barreira duas vezes, e o ensaio no simulador (T11) tem de mostrar o que acontece em produção.
- **Senha provisória (`must_change_password`): não se pergunta pelo Face ID** (a senha vai mudar a seguir); e o `changePassword` leva a senha nova ao Keychain de quem já tinha o Face ID ligado para essa conta.
- **Um 401 que chegue ao `PainelIda` faz `logout()`** como nos outros ecrãs (desenho §5.4 «falhou → login normal»): o que se estava a escrever perde-se, mas o painel já não tinha sessão para gravar.
- **Um rosto vale 60 s** (`JANELA_MS`): é o «se a barreira não acabou de o fazer» do desenho.
- **«Usar Face ID» no menu termina a sessão** (sem tocar no Keychain) para a pessoa escrever a senha no login, que depois pergunta: guardar a senha exige tê-la.
- **Matar a app e reabri-la menos de 5 minutos depois de a esconder não pede Face ID**: é o que dá o `saiuAs` no `localStorage` (que sobrevive a matar a app). Uma app morta sem ter sido escondida (ou reaberta depois dos 5 minutos) pede.

### Para o dono decidir (não aplicado: o plano segue o desenho §5.7 tal como está)

- **Dois gestores no mesmo iPhone.** Com a sessão do B aberta e o Face ID ligado ao A (o último que o activou), a barreira diz «Entrar como A» por cima dos números do B, e uma re-entrada (sessão de 24 h expirada) entra **na conta do A** sem o dizer — possivelmente com outras empresas à vista. Correcção barata, se o dono a quiser: só fechar a barreira ao esconder quando `emailGuardado() === user?.email` (no `aoMudar` da `Barreira`, Tarefa 6), e só reentrar com o Keychain quando o email guardado for o da sessão que expirou. O desenho fixou «fica o último que activou o Face ID; a barreira diz sempre "Entrar como <email>"», por isso não se muda sem ele.
- **Face ID indisponível → login** (Tarefa 6): segue o desenho; se o dono preferir conforto a segurança neste caso raro, a alternativa é abrir a barreira sem rosto quando o iPhone não faz Face ID — mas aí cinco rostos errados noutra app abrem a Gestão Lisbonb a quem tiver o telemóvel desbloqueado na mão.
