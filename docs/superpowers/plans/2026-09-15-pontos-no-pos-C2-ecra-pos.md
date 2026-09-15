# Pontos L'Açaí no POS — C2: ecrã do POS e linha no backoffice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-09-15-pontos-no-pos-design.md` — secções «POS (RH) — ecrã» e a parte de ecrã de «Backoffice».

**Goal:** a funcionária lê no Finalizar o QR que o cliente mostra na app (leitor do POS HP ou câmara do Surface), vê «Pontos para: Ana ✓», e o EMITIR leva essa ligação ao servidor em `pontos_ligacao`; no backoffice, o detalhe da fatura/nota de crédito diz o que aconteceu aos pontos.

**Architecture:** tudo do lado do browser. `lib/pos.js` ganha a chamada `POST /pos/pontos/ler` e a gaveta da ligação em `sessionStorage` presa ao id da conta (molde do NIF). Um ficheiro novo, `PosLerQr.js`, é a janela com os dois caminhos de leitura (campo com foco + `<form>` para o leitor; `getUserMedia` + `jsQR` para a câmara), montada só enquanto está aberta — é isso que garante que a câmara desliga. O `PosFinalizar` ganha o cartão entre Cliente e Pagamento, fora do `motivoBloqueio`, e manda `pontos_ligacao` (sempre presente) no `onEmitir`; o `PosVenda` passa esses `dados` tal e qual a `finalizarVenda` e não muda. O campo do NIF fecha-se durante a rajada de teclas do leitor. O `FatDocumentos` desenha `pontos_app` que o servidor (C1) já manda.

**Verificação prévia deste plano:** o código e os testes daqui foram aplicados numa cópia descartável do repo (fora da worktree, com um `jsqr` de mentira): cada teste falha e passa como os passos dizem, cada mutação fica vermelha pela razão indicada, e `CI=false yarn build` compila sem avisos novos. Os números esperados abaixo são os medidos. **Acrescentado DEPOIS dessa verificação, a seguir a uma revisão** (números deduzidos, não medidos — se divergirem, o que manda é a RAZÃO da falha, não a contagem): a fixture `parte_seguinte` da Task 4 e a mutação (c) do Step 5 dessa Task, e o Step 5 da Task 6 (a câmara no browser).

**Tech Stack:** React 19 + CRA/craco + shadcn/ui + lucide-react (frontend); `jsqr@1.4.0` (dependência nova, fixada); testes em pytest que montam os ecrãs reais em Node com jsdom e o servidor fabricado à frente do axios (`backend/tests/faturacao/test_a_faixa_do_modo_no_ecra.py::_montar_no_node`).

## Global Constraints

- **Worktree:** `/Users/matheus.moraes/Developer/RH-pontos`, ramo `matheus-pontos-no-pos`. Nunca no `main`. **Sem deploy, sem push.**
- **Este plano não toca em código do backend** (`backend/faturacao/*.py` é do plano C1). Só `frontend/` e ficheiros de teste em `backend/tests/faturacao/`.
- **PATH do node:** `export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH"` antes de qualquer `yarn`/`node`/`npx`.
- **Testes:** `cd /Users/matheus.moraes/Developer/RH-pontos/backend && .venv/bin/pytest tests/faturacao/<ficheiro> -q`. Nenhum teste liga à rede nem à base de dados: o axios é o duplo do preâmbulo de montagem. `frontend/node_modules` e `backend/.venv` são symlinks para `~/Developer/RH` — **sem `frontend/node_modules` os testes de ecrã SALTAM em silêncio**; ler sempre `passed` E `skipped`.
- **Nunca correr a suite enquanto outro trabalho muta a mesma árvore** (workflows paralelos dão falhas diferentes no mesmo commit).
- **Contrato com o servidor RH (fixo, igual ao C1):**
  - `POST /api/faturacao/pos/pontos/ler`, sessão do operador (`X-Operator-Token`), corpo `{venda_id: str, codigo: str}`.
  - 200 → `{ligacao_id: str, primeiro_nome: str}`.
  - 404 → `{detail: "QR inválido ou expirado — peça ao cliente para abrir o QR outra vez."}`.
  - 503 → `{detail: "Não foi possível falar com a app agora. A fatura pode seguir sem pontos."}`.
  - Venda não aberta / de outra loja → os códigos e frases que as outras rotas de venda do POS já usam (documentados no C1); o ecrã mostra o `detail` do servidor.
  - `POST /api/faturacao/pos/venda/{id}/finalizar` ganha `pontos_ligacao: {id: str, primeiro_nome: str} | null` — **o ecrã manda-o SEMPRE**, `null` quando não há.
  - `GET /api/faturacao/documentos/{id}` (gestor) ganha `pontos_app: null | {tipo: "credito"|"estorno", estado: "pendente"|"feito"|"recusado"|"sem_efeito"|"falhado", pontos: int|null, primeiro_nome: str|null, motivo: str|null, tentativas: int, ultimo_erro: str|null, atualizado_em: str ISO}`. FS → linha de crédito; NC → linha de estorno dessa NC.
- **`lib/pos.js` (contrato):** `lerQrDePontos(vendaId, codigo) -> Promise<{ligacao_id, primeiro_nome}>`; `guardarPontosDaConta(vendaId, ligacao|null)`; `lerPontosDaConta(vendaId) -> {id, primeiro_nome}|null`.
- **Formato do código do QR** (spec, app): `LQ` + 22 caracteres de `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`. Código de exemplo dos testes: `LQ7K2MN8P3QRSTUV4WXYZ9AB`.
- **Textos do ecrã (spec):** cartão «Pontos L'Açaí»; vazio «Ler QR do cliente»; ligado «Pontos para: {primeiro_nome} ✓» e «Remover»; janela «Ler QR do cliente» com o campo do leitor e «Usar câmara».
- **O cartão nunca entra no `motivoBloqueio`.** O EMITIR não depende dos pontos.
- **Campo do NIF:** uma alteração com letras é ignorada por inteiro — e, porque o leitor escreve uma tecla de cada vez, as alterações que chegam até `ESPERA_DO_LEITOR_MS = 500` ms depois da anterior ignorada também (ver Task 2).
- **Backoffice (spec):** «17 pontos para Ana» · «A tentar enviar (3 tentativas — último erro: …)» · «Recusado: pagamento por plataforma» · «Falhou ao fim de 24 h»; a NC mostra o estorno.
- **`jsqr` 1.4.0** (`npm view jsqr version` → `1.4.0`, 2026-09-15), instalado com `yarn add jsqr@1.4.0 --exact` — o build de produção é `yarn install` sobre o `yarn.lock` (`frontend/Dockerfile`).
- **Se algum teste de ecrã falhar com `Cannot find module 'jsqr'`**, alguém correu `yarn install` em `~/Developer/RH` e apagou-o: o `frontend/node_modules` desta worktree é um symlink para lá. A partir da Task 4 o `PosFinalizar` importa o `PosLerQr`, que importa o `jsqr` — ou seja, TODOS os testes que montam o `PosFinalizar`/`PosVenda` passam a carregá-lo, e sem ele **falham alto, não saltam** (o `_montar_no_node` só salta por falta de `react-dom`, `jsdom` ou `@babel/core`: `test_a_faixa_do_modo_no_ecra.py:757-762`). Remédio: `export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH" && cd /Users/matheus.moraes/Developer/RH-pontos/frontend && yarn add jsqr@1.4.0 --exact` e voltar a correr — sem commitar nada de novo, que o `package.json` e o `yarn.lock` já o têm desde a Task 3.
- **PT-PT** em texto visível, comentários, docstrings e nomes de testes (em frase). Comentários explicam o PORQUÊ.
- **Prova por mutação** nas guardas marcadas: estragar, ver vermelho pela razão certa, repor.
- **Commits** com `git add` de caminhos explícitos e mensagem em PT a terminar com `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- **Lição do projeto:** os ecrãs do POS desenham-se sem servidor nenhum; ver o ecrã não prova as chamadas. O que prova as chamadas neste plano são os testes montados (corpo dos pedidos) e o `test_caminhos_do_pos.py`. O happy-path real (QR do telemóvel → FS real → pontos) é com o dono no dia D, fora deste plano.

## File Structure

| Ficheiro | O quê |
|---|---|
| `frontend/src/lib/pos.js` (modificar) | secção «Os pontos L'Açaí da conta»: `guardarPontosDaConta`, `lerPontosDaConta`, `MSG_PONTOS_SEM_RESPOSTA`, `lerQrDePontos`; comentário do `finalizarVenda` |
| `frontend/src/pages/pos/PosLerQr.js` (**criar**) | a janela «Ler QR do cliente»: campo do leitor em `<form>`, câmara com `getUserMedia` + `jsQR` + escolha de câmara |
| `frontend/src/pages/pos/PosFinalizar.js` (modificar) | `escritaNoNif` no campo do NIF; `CartaoPontos`; estado da ligação; `pontos_ligacao` no `onEmitir` |
| `frontend/src/pages/pos/PosVenda.js` | **não muda**: `emitir` (linhas 1766-1791) passa `dados` tal e qual a `finalizarVenda` (linha 1776). O teste montado da Task 4 prova-o no corpo do pedido |
| `frontend/src/pages/admin/faturacao/FatDocumentos.js` (modificar) | bloco «Pontos L'Açaí» no detalhe do documento |
| `frontend/package.json`, `frontend/yarn.lock` (modificar) | `jsqr` 1.4.0 |
| `backend/tests/faturacao/test_os_pontos_da_conta_no_pos.py` (**criar**) | a gaveta por conta e a chamada `lerQrDePontos`, corridas em Node |
| `backend/tests/faturacao/test_o_nif_que_nao_existe_no_pos.py` (modificar) | o leitor com o foco no NIF (função pura + ecrã montado) |
| `backend/tests/faturacao/test_os_pontos_no_ecra_do_pos.py` (**criar**) | a janela montada; o cartão e o EMITIR pelo `PosVenda` montado |
| `backend/tests/faturacao/test_o_ecra_de_documentos_no_backoffice.py` (modificar) | os textos de cada estado no detalhe |

---

## Task 1: A ligação dos pontos presa à conta, e a chamada que a pede

**Files:**
- Modify: `frontend/src/lib/pos.js` — inserir secção nova antes da linha 219 (`// --- Dispositivo ---`); comentário das linhas 654-655.
- Create: `backend/tests/faturacao/test_os_pontos_da_conta_no_pos.py`

**Interfaces:**
- Consumes: `guardarNaSessao(chave, valor)` (`lib/pos.js:127`); `api` (`lib/pos.js:77`, baseURL `…/api/faturacao`, interceptor com `X-Operator-Token`); rota `POST /pos/pontos/ler` do C1.
- Produces:
  - `export const guardarPontosDaConta = (vendaId, ligacao) => void` — `ligacao: {id: string, primeiro_nome: string} | null`
  - `export const lerPontosDaConta = (vendaId) => ({id, primeiro_nome} | null)`
  - `export const MSG_PONTOS_SEM_RESPOSTA: string`
  - `export const lerQrDePontos = async (vendaId, codigo) => ({ligacao_id, primeiro_nome})`

- [ ] **Step 0: Registar a linha de base da suite (antes de mexer em nada)**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && .venv/bin/pytest tests/faturacao -q 2>&1 | tail -3
```

Anotar `N passed, M skipped`. O `M` é o número contra o qual a Task 7 compara. Se `M` for da ordem das centenas, falta `frontend/node_modules` — parar e resolver antes de continuar.

- [ ] **Step 1: Escrever o teste que falha**

Criar `backend/tests/faturacao/test_os_pontos_da_conta_no_pos.py`:

```python
"""**O cliente dos pontos fica preso à CONTA onde o QR foi lido.**

A funcionária lê o QR que o cliente mostra na app e o POS guarda a ligação até
ao EMITIR. Guarda-a no `sessionStorage`, com o id da conta, pelo mesmo molde
do NIF (`test_o_nif_da_conta_no_pos.py`): voltar à conta para juntar mais um
artigo não pode perder o cliente, e desligar o PC tem de o esquecer.

**A peça que interessa é o id da conta.** Uma conta repartida cobra-se parte a
parte no mesmo ecrã. Uma ligação que passasse da primeira parte para a segunda
dava os pontos da fatura de uma pessoa a outra — e como a app só credita UMA
fatura por ligação, quem mostrou a app ficava sem nada.
"""
import json

from .test_a_faixa_do_modo_no_ecra import _montar_no_node

_ANA = {"id": "lig-1", "primeiro_nome": "Ana"}
_CODIGO = "LQ7K2MN8P3QRSTUV4WXYZ9AB"


def _correr(guiao: str, tmp_path):
    return _montar_no_node(
        "\n".join([
            "const lib = carregar(path.join(RAIZ, 'lib', 'pos.js'));",
            guiao,
        ]), tmp_path, "pontos-da-conta.js")


def test_a_ligacao_volta_para_a_MESMA_conta(tmp_path):
    """O cliente lembra-se de mais um artigo: sai-se do Finalizar e volta-se."""
    saida = _correr("\n".join([
        "lib.guardarPontosDaConta('venda-1', %s);" % json.dumps(_ANA),
        "process.stdout.write(JSON.stringify({ lida: lib.lerPontosDaConta('venda-1') }));",
    ]), tmp_path)
    assert saida["lida"] == _ANA


def test_a_ligacao_NAO_passa_para_OUTRA_conta(tmp_path):
    """**A guarda que faz isto ser seguro.** Sem ela, a segunda parte de uma
    conta repartida — ou a venda seguinte — levava os pontos de quem mostrou
    a app na anterior."""
    saida = _correr("\n".join([
        "lib.guardarPontosDaConta('venda-1', %s);" % json.dumps(_ANA),
        "process.stdout.write(JSON.stringify({ outra: lib.lerPontosDaConta('venda-2') }));",
    ]), tmp_path)
    assert saida["outra"] is None, (
        "A ligação de uma conta apareceu noutra — os pontos iam para quem "
        "não os ganhou.")


def test_a_ligacao_sobrevive_a_um_F5_e_MORRE_ao_desligar_o_PC(tmp_path):
    saida = _correr("\n".join([
        "lib.guardarPontosDaConta('venda-1', %s);" % json.dumps(_ANA),
        "const depoisDoF5 = lib.lerPontosDaConta('venda-1');",
        "sessionStorage.clear();",
        "process.stdout.write(JSON.stringify({",
        "  depoisDoF5, depoisDeDesligar: lib.lerPontosDaConta('venda-1') }));",
    ]), tmp_path)
    assert saida["depoisDoF5"] == _ANA
    assert saida["depoisDeDesligar"] is None


def test_remover_a_ligacao_no_ecra_apaga_a_guardada(tmp_path):
    """O «Remover» do cartão escreve `null`. Se isso não apagasse, o cliente
    voltava sozinho ao cartão depois de a funcionária o ter tirado."""
    saida = _correr("\n".join([
        "lib.guardarPontosDaConta('venda-1', %s);" % json.dumps(_ANA),
        "lib.guardarPontosDaConta('venda-1', null);",
        "process.stdout.write(JSON.stringify({ lida: lib.lerPontosDaConta('venda-1') }));",
    ]), tmp_path)
    assert saida["lida"] is None


def test_uma_escrita_SEM_CONTA_nao_apaga_a_ligacao_que_la_estava(tmp_path):
    """A gaveta é UMA só, e o ecrã pode desenhar-se um instante antes de a
    conta chegar. Lido pela conta certa, e não por `undefined`: por essa porta
    responde primeiro a guarda da leitura e a da escrita nunca era medida."""
    saida = _correr("\n".join([
        "lib.guardarPontosDaConta('venda-1', %s);" % json.dumps(_ANA),
        "lib.guardarPontosDaConta(undefined, { id: 'lig-2', primeiro_nome: 'Rui' });",
        "process.stdout.write(JSON.stringify({",
        "  aindaLa: lib.lerPontosDaConta('venda-1'),",
        "  semId: lib.lerPontosDaConta(undefined) }));",
    ]), tmp_path)
    assert saida["aindaLa"] == _ANA, "a escrita sem conta apagou a ligação da conta"
    assert saida["semId"] is None


def test_ler_o_QR_pergunta_ao_servidor_pela_conta_e_devolve_o_primeiro_nome(tmp_path):
    """O pedido que sai do browser: método, caminho, corpo e a sessão da
    operadora. É o servidor (C1) que fala com a app — daqui só sai o código
    lido e a conta."""
    saida = _correr("\n".join([
        "lib.guardarOperador('ot', { id: 'o1', nome: 'Ana' });",
        "RESPOSTAS_POS['POST /pos/pontos/ler'] = () => ({",
        "  data: { ligacao_id: 'lig-1', primeiro_nome: 'Ana' } });",
        "(async () => {",
        "  const resposta = await lib.lerQrDePontos('venda-1', %s);" % json.dumps(_CODIGO),
        "  const p = pedidos[pedidos.length - 1];",
        "  process.stdout.write(JSON.stringify({ resposta, metodo: p.metodo, url: p.url,",
        "    corpo: p.corpo, operador: p.headers['X-Operator-Token'] }));",
        "})().catch((e) => { console.error(e); process.exit(3); });",
    ]), tmp_path)
    assert saida["resposta"] == {"ligacao_id": "lig-1", "primeiro_nome": "Ana"}
    assert saida["metodo"] == "post"
    assert saida["url"].endswith("/api/faturacao/pos/pontos/ler"), saida["url"]
    assert saida["corpo"] == {"venda_id": "venda-1", "codigo": _CODIGO}
    assert saida["operador"] == "ot"
```

- [ ] **Step 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && .venv/bin/pytest tests/faturacao/test_os_pontos_da_conta_no_pos.py -q
```

Esperado: `6 failed`, cada um com `Failed: O JavaScript do ecrã não correu:` e `TypeError: lib.guardarPontosDaConta is not a function` (o último com `lib.lerQrDePontos is not a function`). Se aparecer `skipped`, falta `frontend/node_modules`.

- [ ] **Step 3: Escrever o mínimo que faz passar**

Em `frontend/src/lib/pos.js`, logo a seguir ao fim de `nifValidoPT` (linha 216) e antes de `// --- Dispositivo ---` (linha 219), inserir:

```js
// --- Os pontos L'Açaí da conta -----------------------------------------------
//
// **Ganha os pontos quem mostra a app na caixa antes de pagar.** O talão das
// lojas era um bilhete ao portador: quem o apanhasse lia o QR fiscal na app e
// ficava com os pontos. Agora a funcionária lê o QR que o CLIENTE mostra
// (`lerQrDePontos`), o servidor pede à app uma ligação e devolve só o primeiro
// nome, e o POS guarda-a até ao EMITIR, que a manda em `pontos_ligacao`. Nada
// se grava na venda antes disso.
//
// Guardada com o ID DA CONTA, pelo molde do NIF aqui em cima e pela mesma
// razão: numa conta repartida, uma ligação que passasse da primeira parte para
// a segunda dava os pontos da fatura de uma pessoa a outra — e a app só
// credita UMA fatura por ligação, por isso quem mostrou a app ficava sem nada.
// Numa conta dividida lê-se o QR na parte de quem o mostra.
const CHAVE_PONTOS_DA_CONTA = 'pos_pontos_da_conta';

export const guardarPontosDaConta = (vendaId, ligacao) => {
  // Sem conta não se escreve nada: a gaveta é uma só (ver guardarNifDaConta).
  if (!vendaId) return;
  guardarNaSessao(CHAVE_PONTOS_DA_CONTA, JSON.stringify({
    vendaId,
    ligacao: ligacao ? { id: ligacao.id, primeiro_nome: ligacao.primeiro_nome } : null,
  }));
};

export const lerPontosDaConta = (vendaId) => {
  if (!vendaId) return null;
  try {
    const guardado = JSON.parse(sessionStorage.getItem(CHAVE_PONTOS_DA_CONTA));
    // A comparação de ids É a garantia. Sem ela, isto era um cliente à solta.
    return guardado && guardado.vendaId === vendaId ? guardado.ligacao || null : null;
  } catch (e) { return null; }
};

// Para quando o servidor nem chegou a responder (rede, tecto de espera). É a
// frase do 503 da rota, porque para o balcão a consequência é a mesma: a
// fatura segue sem pontos.
export const MSG_PONTOS_SEM_RESPOSTA =
  'Não foi possível falar com a app agora. A fatura pode seguir sem pontos.';

// `POST /pos/pontos/ler` → `{ ligacao_id, primeiro_nome }`. 404 é QR recusado
// e 503 é a app em baixo; as frases vêm no `detail`. A conta vai no pedido
// para o servidor confirmar que está aberta e é desta loja.
export const lerQrDePontos = async (vendaId, codigo) =>
  (await api.post('/pos/pontos/ler', { venda_id: vendaId, codigo })).data;

```

E no comentário do `finalizarVenda` (linhas 654-655), substituir:

```js
// A emissão da Fatura Simplificada real. `dados` = { pagamentos: [{
// tipo_pagamento_id, valor }], nif }. Os erros deste pedido NÃO são todos
```

por:

```js
// A emissão da Fatura Simplificada real. `dados` = { pagamentos: [{
// tipo_pagamento_id, valor }], nif, pontos_ligacao } — `pontos_ligacao` vai
// SEMPRE, `null` quando não houve QR (ver PosFinalizar::emitir). Os erros deste pedido NÃO são todos
```

- [ ] **Step 4: Correr e ver passar**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && .venv/bin/pytest tests/faturacao/test_os_pontos_da_conta_no_pos.py tests/faturacao/test_o_nif_da_conta_no_pos.py -q
```

Esperado: `11 passed`, `0 skipped`.

- [ ] **Step 5: Validação por mutação (guarda da conta e escrita sem conta)**

a) Em `lerPontosDaConta`, trocar `guardado && guardado.vendaId === vendaId ? guardado.ligacao || null : null` por `guardado ? guardado.ligacao || null : null` (atenção: o `lerNifDaConta` tem um pedaço parecido — não é esse). Correr o Step 4. Esperado: `test_a_ligacao_NAO_passa_para_OUTRA_conta` FAILED com `A ligação de uma conta apareceu noutra`. Repor.

b) Em `guardarPontosDaConta`, apagar `if (!vendaId) return;`. Correr o Step 4. Esperado: `test_uma_escrita_SEM_CONTA_nao_apaga_a_ligacao_que_la_estava` FAILED com `a escrita sem conta apagou a ligação da conta`. Repor.

Correr o Step 4 outra vez: `11 passed`.

- [ ] **Step 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos
git add frontend/src/lib/pos.js backend/tests/faturacao/test_os_pontos_da_conta_no_pos.py
git commit -F - <<'EOF'
POS: a ligação dos pontos L'Açaí fica presa à conta onde o QR foi lido

lerQrDePontos pede a ligação ao servidor (POST /pos/pontos/ler) e a gaveta
em sessionStorage só a devolve à mesma conta — pelo molde do NIF, para uma
conta repartida não dar os pontos de uma pessoa a outra.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 2: O campo do NIF não aceita o QR escrito pelo leitor

**Files:**
- Modify: `frontend/src/pages/pos/PosFinalizar.js` — linha 1 (import de `useRef`); depois da linha 151 (fim de `nifAteNove`); linhas 387-388 (início de `CartaoCliente`); linha 473 (`onChange` do campo `nif-cliente`).
- Modify: `backend/tests/faturacao/test_o_nif_que_nao_existe_no_pos.py` — imports (linhas 27-34) e testes novos no fim.

**Interfaces:**
- Consumes: `nifAteNove(texto)` (`PosFinalizar.js:144`).
- Produces (privadas do módulo, extraídas pelos testes pelo texto):
  - `const ESPERA_DO_LEITOR_MS = 500;`
  - `const escritaNoNif = (texto, agora, fechadoAte) => ({ texto: string | null, fechadoAte: number })`

**Porque não basta «ignorar a alteração com letras»:** o leitor do POS HP é um teclado e escreve o código uma tecla de cada vez; cada tecla chega ao `onChange` como uma alteração SEPARADA. Ignorar só as que trazem letras deixa os dígitos do código entrarem um a um (medido num protótipo montado em jsdom: `5175` + `L` fica `5175`, + `7` fica `51757`). Por isso uma letra fecha o campo durante a rajada.

- [ ] **Step 1: Escrever o teste que falha**

Em `backend/tests/faturacao/test_o_nif_que_nao_existe_no_pos.py`, substituir os imports:

```python
from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_arredondamento_do_ecra import _corpo_da_funcao, _ler
```

por:

```python
from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_arredondamento_do_ecra import _corpo_da_funcao, _corpo_da_seta, _ler
from .test_as_fotos_no_ecra import _COMPONENTES as _COMPONENTES_COM_ID
```

E acrescentar no fim do ficheiro:

```python
# --- O leitor de QR com o foco no campo do NIF --------------------------------
#
# Os pontos L'Açaí passam a ganhar-se a mostrar o QR da app na caixa, e o
# leitor do POS HP é um TECLADO: escreve `LQ` + 22 letras e dígitos, uma tecla
# de cada vez, e dá Enter. Com o foco no NIF por engano, cada tecla chega ao
# `onChange` sozinha — e ignorar só as alterações com letras deixava entrar os
# dígitos do código, um a um, no NIF da fatura. Uma fatura real à AT com um
# NIF feito de pedaços de um QR.

_CODIGO_DO_QR = "LQ7K2MN8P3QRSTUV4WXYZ9AB"


def _no_campo(inicial, teclas, tmp_path):
    """Corre o `escritaNoNif` do próprio ecrã sobre `teclas` —
    `[[tecla, ms desde a anterior], ...]` — como o browser as entrega: cada
    uma acrescentada ao que o campo tem. Devolve o que fica no campo."""
    ecra = _ler(_POS_FINALIZAR)
    saida = _montar_no_node("\n".join([
        _corpo_da_funcao(ecra, "const nifAteNove = (texto) =>", _POS_FINALIZAR),
        _corpo_da_seta(ecra, "const ESPERA_DO_LEITOR_MS =", _POS_FINALIZAR),
        _corpo_da_funcao(
            ecra, "const escritaNoNif = (texto, agora, fechadoAte) =>", _POS_FINALIZAR),
        "let campo = %s;" % json.dumps(inicial),
        "let fechadoAte = 0;",
        "let agora = 1000;",
        "for (const [tecla, passou] of %s) {" % json.dumps(teclas),
        "  agora += passou;",
        "  const escrita = escritaNoNif(campo + tecla, agora, fechadoAte);",
        "  fechadoAte = escrita.fechadoAte;",
        "  if (escrita.texto !== null) campo = escrita.texto;",
        "}",
        "process.stdout.write(JSON.stringify({ campo }));",
    ]), tmp_path, "escrita-no-nif.js")
    return saida["campo"]


@pytest.mark.parametrize("inicial", ["", "5175"])
def test_o_QR_escrito_pelo_leitor_no_campo_do_NIF_nao_deixa_la_nenhum_digito(inicial, tmp_path):
    """A rajada do leitor: 15 ms entre teclas. Nem as letras nem os dígitos do
    código entram — com o NIF vazio ou a meio."""
    teclas = [[tecla, 15] for tecla in _CODIGO_DO_QR]
    assert _no_campo(inicial, teclas, tmp_path) == inicial, (
        "Os dígitos do QR entraram no NIF da fatura.")


def test_depois_de_uma_letra_por_engano_a_mao_volta_a_escrever_passado_meio_segundo(tmp_path):
    """O fecho não pode prender quem escreveu uma letra à mão: meio segundo
    depois, o campo aceita outra vez."""
    assert _no_campo("5175", [["a", 0], ["6", 600]], tmp_path) == "51756"


def test_digitos_e_espacos_escritos_a_mao_continuam_a_entrar(tmp_path):
    """O guarda contra o crivo apertado de mais: a escrita normal, aos grupos
    de três, com o ritmo de um dedo."""
    teclas = [[tecla, 150] for tecla in "219 363 935"]
    assert _no_campo("", teclas, tmp_path) == "219 363 935"


@pytest.fixture(scope="module")
def leitor_no_nif(tmp_path_factory):
    """O `PosFinalizar` montado com o editor do NIF ABERTO — o sítio errado
    para o leitor escrever. Primeiro uma tecla à mão (a prova de que escrever
    no campo funciona nesta montagem: sem ela, um campo que não aceitasse
    nada deixava o guarda verde), depois a rajada do QR."""
    cenario = "\n".join([
        _COMPONENTES_COM_ID,
        # O teclado do NIF vem do PosCampoValor, que o preâmbulo substitui por
        # uma marca; sem o verdadeiro, abrir o editor rebentava.
        "SUBSTITUIDOS.delete(path.join(POS, 'PosCampoValor.js'));",
        "const lib = carregar(path.join(RAIZ, 'lib', 'pos.js'));",
        "const Finalizar = carregar(path.join(POS, 'PosFinalizar.js')).default;",
        "function escrever(el, valor) {",
        "  Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, 'value')",
        "    .set.call(el, valor);",
        "  el.dispatchEvent(new dom.window.Event('input', { bubbles: true }));",
        "}",
        "(async () => {",
        "  sessionStorage.clear();",
        "  lib.guardarNifDaConta('v1', '5175');",
        "  const alvo = document.getElementById('raiz');",
        "  const raiz = createRoot(alvo);",
        "  await act(async () => { raiz.render(React.createElement(Finalizar, {",
        "    venda: %s," % _VENDA,
        "    tiposPagamento: [{ id: 't1', nome: 'Dinheiro', pronto: true }],",
        "    onVoltar: () => {}, onEmitir: () => {}, onAplicarDesconto: () => {},",
        "  })); });",
        "  await act(async () => {});",
        "  const terminar = [...alvo.querySelectorAll('button')]",
        "    .find((b) => (b.textContent || '').includes('Terminar o NIF'));",
        "  if (!terminar) throw new Error('sem o botão Terminar o NIF: '",
        "    + textoVisivel(alvo).slice(0, 400));",
        "  await act(async () => { terminar.click(); });",
        "  const campo = () => alvo.querySelector('#nif-cliente');",
        "  if (!campo()) throw new Error('o editor do NIF não abriu: '",
        "    + textoVisivel(alvo).slice(0, 400));",
        "  await act(async () => { escrever(campo(), campo().value + '6'); });",
        "  const aMao = campo().value;",
        "  for (const tecla of %s) {" % json.dumps(_CODIGO_DO_QR),
        "    await act(async () => { escrever(campo(), campo().value + tecla); });",
        "  }",
        "  const depoisDoLeitor = campo().value;",
        "  await act(async () => { raiz.unmount(); });",
        "  process.stdout.write(JSON.stringify({ aMao, depoisDoLeitor }));",
        "})().catch((e) => { console.error(e); process.exit(3); });",
    ])
    return _montar_no_node(
        cenario, tmp_path_factory.mktemp("leitor-no-nif"), "montar-leitor-no-nif.js")


def test_no_ecra_montado_uma_tecla_a_mao_entra_no_NIF(leitor_no_nif):
    assert leitor_no_nif["aMao"] == "51756", (
        "Escrever no campo não funciona nesta montagem — o guarda seguinte "
        "mediria o vazio.")


def test_no_ecra_montado_o_QR_do_leitor_nao_mexe_no_NIF(leitor_no_nif):
    """O fio entre a regra e o campo: um `onChange` que voltasse a chamar o
    `nifAteNove` directamente punha aqui `517567283`."""
    assert leitor_no_nif["depoisDoLeitor"] == "51756", (
        "O leitor escreveu no NIF: %r" % leitor_no_nif["depoisDoLeitor"])
```

- [ ] **Step 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && .venv/bin/pytest tests/faturacao/test_o_nif_que_nao_existe_no_pos.py -q
```

Esperado: `5 failed, 24 passed` — os 4 testes de `_no_campo` FAILED com `Failed: Não encontrei \`const ESPERA_DO_LEITOR_MS =\` em PosFinalizar.js.`; `test_no_ecra_montado_o_QR_do_leitor_nao_mexe_no_NIF` FAILED com `O leitor escreveu no NIF: '517567283'`; `test_no_ecra_montado_uma_tecla_a_mao_entra_no_NIF` e os testes antigos passam.

- [ ] **Step 3: Escrever o mínimo que faz passar**

Em `frontend/src/pages/pos/PosFinalizar.js`, linha 1, substituir:

```js
import React, { useEffect, useMemo, useState } from 'react';
```

por:

```js
import React, { useEffect, useMemo, useRef, useState } from 'react';
```

Logo a seguir ao fim de `nifAteNove` (a linha `};` da linha 151), inserir:

```js

// **O leitor de QR com o foco no sítio errado.** O leitor do POS HP é um
// teclado: escreve o código dos pontos L'Açaí (`LQ` + 22 letras e dígitos)
// uma tecla de cada vez e dá Enter. Se o foco estiver aqui, cada tecla chega
// como uma alteração SEPARADA — e ignorar só as que trazem letras não chega:
// as letras caíam, os dígitos do código entravam um a um, e a fatura saía com
// um NIF feito de pedaços do QR (com o QR de exemplo, «5175» passava a
// «517572834»).
//
// Por isso uma letra FECHA o campo, e cada alteração que chegue com ele
// fechado volta a empurrar o fecho: a rajada do leitor (dezenas de ms entre
// teclas) cai inteira, e quem escreveu uma letra à mão volta a escrever
// passado meio segundo. `texto: null` = deixar o campo como estava.
const ESPERA_DO_LEITOR_MS = 500;

const escritaNoNif = (texto, agora, fechadoAte) => {
  if (/\p{L}/u.test(String(texto || '')) || agora < fechadoAte) {
    return { texto: null, fechadoAte: agora + ESPERA_DO_LEITOR_MS };
  }
  return { texto: nifAteNove(texto), fechadoAte };
};
```

No início de `CartaoCliente` (linhas 387-388), substituir:

```js
function CartaoCliente({ nifTexto, onNifTexto, desativado }) {
  const [aEditar, setAEditar] = useState(false);
```

por:

```js
function CartaoCliente({ nifTexto, onNifTexto, desativado }) {
  const [aEditar, setAEditar] = useState(false);
  // Até quando o campo ignora escrita — ver `escritaNoNif`.
  const fechadoAte = useRef(0);
```

Na linha 473, substituir:

```js
                onChange={(e) => onNifTexto(nifAteNove(e.target.value))}
```

por:

```js
                onChange={(e) => {
                  const escrita = escritaNoNif(e.target.value, Date.now(), fechadoAte.current);
                  fechadoAte.current = escrita.fechadoAte;
                  if (escrita.texto !== null) onNifTexto(escrita.texto);
                }}
```

- [ ] **Step 4: Correr e ver passar**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && .venv/bin/pytest tests/faturacao/test_o_nif_que_nao_existe_no_pos.py tests/faturacao/test_o_nif_da_conta_no_pos.py -q
```

Esperado: `34 passed` (28 que já existiam nos dois ficheiros + 6 novos), `0 skipped`.

- [ ] **Step 5: Validação por mutação (o fecho durante a rajada e o fio ao campo)**

a) Em `escritaNoNif`, apagar ` || agora < fechadoAte` (fica a regra literal «ignorar só com letras»). Correr o Step 4. Esperado: `3 failed` — `test_o_QR_escrito_pelo_leitor_no_campo_do_NIF_nao_deixa_la_nenhum_digito[5175]` (`'517572834' == '5175'`), `[]` (`'728349' == ''`) e `test_no_ecra_montado_o_QR_do_leitor_nao_mexe_no_NIF` (`'517567283'`). Repor.

b) Voltar temporariamente a linha 473 a `onChange={(e) => onNifTexto(nifAteNove(e.target.value))}`. Correr o Step 4. Esperado: só `test_no_ecra_montado_o_QR_do_leitor_nao_mexe_no_NIF` FAILED (`O leitor escreveu no NIF: '517567283'`). Repor.

Correr o Step 4 outra vez: `0 failed`.

- [ ] **Step 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos
git add frontend/src/pages/pos/PosFinalizar.js backend/tests/faturacao/test_o_nif_que_nao_existe_no_pos.py
git commit -F - <<'EOF'
POS: o QR do leitor com o foco no NIF já não escreve no NIF da fatura

O leitor do POS HP escreve uma tecla de cada vez: ignorar só as alterações
com letras deixava entrar os dígitos do código. Uma letra fecha o campo e
cada tecla que chegue fechado empurra o fecho (500 ms).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 3: A janela «Ler QR do cliente» (leitor e câmara)

**Files:**
- Create: `frontend/src/pages/pos/PosLerQr.js`
- Modify: `frontend/package.json`, `frontend/yarn.lock` (`jsqr` 1.4.0)
- Create: `backend/tests/faturacao/test_os_pontos_no_ecra_do_pos.py`

**Interfaces:**
- Consumes: `lerQrDePontos`, `MSG_PONTOS_SEM_RESPOSTA` (Task 1); `detalhesErroPos(error, fallback) -> {campo, mensagem}` (`lib/pos.js:286`); `jsQR(data: Uint8ClampedArray, width: number, height: number, { inversionAttempts }) -> { data: string } | null` (pacote `jsqr`).
- Produces: `export default function PosLerQr({ vendaId: string, onLigada: ({ id: string, primeiro_nome: string }) => void, onFechar: () => void })`. Campo com `id="qr-dos-pontos"` dentro de um `<form>`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `backend/tests/faturacao/test_os_pontos_no_ecra_do_pos.py`:

```python
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
```

- [ ] **Step 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && .venv/bin/pytest tests/faturacao/test_os_pontos_no_ecra_do_pos.py -q
```

Esperado: `7 errors` na fixture `janela` com `Failed: O JavaScript do ecrã não correu:` e `Error: ENOENT: no such file or directory, open '…/frontend/src/pages/pos/PosLerQr.js'`.

- [ ] **Step 3: Instalar o `jsqr` fixado**

O `frontend/node_modules` desta worktree é um symlink para `~/Developer/RH/frontend/node_modules`: o `yarn add` escreve LÁ. Só é seguro se os dois lados tiverem o mesmo `package.json` e `yarn.lock` (senão o yarn reconcilia o `node_modules` do repo principal com o ramo).

```bash
cmp /Users/matheus.moraes/Developer/RH/frontend/yarn.lock /Users/matheus.moraes/Developer/RH-pontos/frontend/yarn.lock && cmp /Users/matheus.moraes/Developer/RH/frontend/package.json /Users/matheus.moraes/Developer/RH-pontos/frontend/package.json && echo IGUAIS
```

Esperado: `IGUAIS`. Se não, **parar e perguntar** — não instalar.

```bash
export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH"
cd /Users/matheus.moraes/Developer/RH-pontos/frontend && yarn add jsqr@1.4.0 --exact
git -C /Users/matheus.moraes/Developer/RH-pontos status --short -- frontend
node -e "const m = require('jsqr'); console.log(typeof m, typeof m.default)"
```

Esperado: o `status` — limitado de propósito a `frontend/`, porque o teste criado no Step 1 ainda está por commitar e os ficheiros de plano também — mostra só `M frontend/package.json` e `M frontend/yarn.lock`: **nada em `frontend/src` nem em `frontend/node_modules`** (a instalação não pode mexer no que não é dela). `package.json` tem `"jsqr": "1.4.0"` (sem `^`); o `node -e` imprime `function` numa das duas posições (o `import jsQR from 'jsqr'` funciona nos dois casos, com o interop do webpack e do babel). Se o yarn recusar por `engine`, repetir com `--ignore-engines` e anotá-lo no relatório.

Nota: o `package-lock.json` não se toca — o build de produção usa `yarn.lock` (`frontend/Dockerfile`).

- [ ] **Step 4: Escrever o mínimo que faz passar**

Criar `frontend/src/pages/pos/PosLerQr.js`:

```jsx
import React, { useEffect, useRef, useState } from 'react';
import jsQR from 'jsqr';
import { AlertTriangle, Camera, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { lerQrDePontos, detalhesErroPos, MSG_PONTOS_SEM_RESPOSTA } from '@/lib/pos';

// A janela «Ler QR do cliente» dos pontos L'Açaí. Dois caminhos para o MESMO
// pedido (`lib/pos.js::lerQrDePontos`):
//
//  · o leitor do POS HP, que é um teclado: escreve o código onde estiver o
//    foco e dá Enter. Por isso o campo abre COM o foco e vive dentro de um
//    <form> — o Enter de um campo num formulário é a submissão, sem apanhar
//    teclas à mão;
//  · a câmara do Surface: `getUserMedia` e o `jsQR` a descodificar as imagens.
//    O Chrome para Windows não tem `BarcodeDetector`.
//
// **A câmara desliga porque esta janela só existe montada enquanto está
// aberta** (o PosFinalizar desmonta-a ao fechar). O efeito que liga a câmara
// devolve a limpeza que pára as pistas, e desmontar corre-a sempre: fechar
// pela cruz, pelo «Fechar», por uma leitura bem sucedida ou por trocar de
// conta. Uma luz de câmara acesa no balcão depois de fechar a janela é o
// defeito que isto evita.

// A câmara escolhida NESTE PC. Um Surface tem duas e só uma está virada para o
// cliente; sem isto, a funcionária escolhia-a em cada venda. É do PC e não da
// sessão — `localStorage` —, e o ecrã funciona sem ele.
const CHAVE_CAMERA = 'pos_camera_do_qr';
const cameraGuardada = () => {
  try { return localStorage.getItem(CHAVE_CAMERA) || ''; } catch (e) { return ''; }
};
const guardarCamera = (id) => {
  try { localStorage.setItem(CHAVE_CAMERA, id); } catch (e) { /* sem storage */ }
};

const MSG_SEM_CAMERA =
  'Não foi possível abrir a câmara. Confirme que o browser a pode usar, ou leia o QR com o leitor.';

export default function PosLerQr({ vendaId, onLigada, onFechar }) {
  const [codigo, setCodigo] = useState('');
  const [aLer, setALer] = useState(false);
  const [erro, setErro] = useState(null);
  // `null` = câmara desligada; '' = a câmara por omissão do sistema; outro
  // texto = o `deviceId` escolhido.
  const [camera, setCamera] = useState(null);
  const [cameras, setCameras] = useState([]);
  const video = useRef(null);
  // Uma leitura de cada vez. O `aLer` do estado chega tarde de mais para
  // decidir: dois Enter seguidos correm antes do render, e a câmara
  // descodifica várias imagens por segundo.
  const ocupado = useRef(false);
  // O último código que a CÂMARA mandou. Depois de uma recusa o QR continua à
  // frente dela, e sem isto cada imagem voltava a perguntar pelo mesmo código
  // gasto. O leitor não passa por aqui: quem volta a ler com ele fá-lo de
  // propósito.
  const ultimoDaCamera = useRef('');

  const ler = async (texto) => {
    const lido = String(texto || '').trim();
    if (!lido || ocupado.current) return;
    ocupado.current = true;
    setALer(true);
    setErro(null);
    try {
      const { ligacao_id: id, primeiro_nome } = await lerQrDePontos(vendaId, lido);
      onLigada({ id, primeiro_nome });
    } catch (error) {
      // 404 e 503 trazem a frase do servidor; sem resposta nenhuma (rede,
      // tecto de espera) a consequência para o balcão é a do 503.
      setErro(detalhesErroPos(error, MSG_PONTOS_SEM_RESPOSTA).mensagem);
      // O leitor escreve POR CIMA do que estiver no campo: com o código
      // recusado lá dentro, a leitura seguinte chegava colada a ele e era
      // recusada também — sempre.
      setCodigo('');
    } finally {
      ocupado.current = false;
      setALer(false);
    }
  };
  // O ciclo da câmara corre fora do render e ficava com o `ler` do primeiro.
  const lerAgora = useRef(ler);
  lerAgora.current = ler;

  useEffect(() => {
    if (camera === null) return undefined;
    let parado = false;
    let stream = null;
    let volta = 0;
    const tela = document.createElement('canvas');
    const parar = () => {
      if (stream) stream.getTracks().forEach((pista) => pista.stop());
    };

    const olhar = () => {
      if (parado) return;
      const v = video.current;
      if (v && v.videoWidth > 0) {
        tela.width = v.videoWidth;
        tela.height = v.videoHeight;
        const ctx = tela.getContext('2d', { willReadFrequently: true });
        ctx.drawImage(v, 0, 0, tela.width, tela.height);
        const imagem = ctx.getImageData(0, 0, tela.width, tela.height);
        // O QR da app é preto sobre branco: não vale a pena procurar o inverso.
        const achado = jsQR(imagem.data, tela.width, tela.height, { inversionAttempts: 'dontInvert' });
        if (achado?.data && achado.data !== ultimoDaCamera.current) {
          ultimoDaCamera.current = achado.data;
          lerAgora.current(achado.data);
        }
      }
      volta = requestAnimationFrame(olhar);
    };

    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: camera ? { deviceId: { exact: camera } } : true,
        });
        // Fechou-se a janela enquanto o browser abria a câmara: a limpeza já
        // correu, sem pistas para parar — param-se aqui.
        if (parado) { parar(); return; }
        video.current.srcObject = stream;
        await video.current.play();
        // Os nomes das câmaras só vêm DEPOIS da autorização.
        const todas = await navigator.mediaDevices.enumerateDevices();
        if (parado) return;
        setCameras(todas.filter((d) => d.kind === 'videoinput'));
        olhar();
      } catch (e) {
        if (parado) return;
        parar();
        // Uma câmara guardada que já não existe não pode prender a janela
        // nesta mensagem para sempre.
        if (camera) guardarCamera('');
        setErro(MSG_SEM_CAMERA);
        setCamera(null);
      }
    })();

    return () => {
      parado = true;
      if (volta) cancelAnimationFrame(volta);
      parar();
    };
  }, [camera]);

  return (
    <Dialog open onOpenChange={(aberta) => { if (!aberta) onFechar(); }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Ler QR do cliente</DialogTitle>
          <DialogDescription>
            O cliente abre a app L'Açaí em Início → Código e mostra o QR antes de pagar.
          </DialogDescription>
        </DialogHeader>

        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); ler(codigo); }}>
          <Input
            id="qr-dos-pontos"
            value={codigo}
            onChange={(e) => setCodigo(e.target.value)}
            autoFocus
            autoComplete="off"
            placeholder="Leia o QR com o leitor…"
            className="h-14 flex-1 font-mono text-lg"
          />
          <Button type="submit" className="h-14 px-6" disabled={aLer || !codigo.trim()}>
            {aLer ? <Loader2 className="h-5 w-5 animate-spin" /> : 'Ler'}
          </Button>
        </form>

        {erro && (
          <div className="flex items-start gap-2 rounded-xl border border-destructive/40 bg-destructive/10 px-4 py-3">
            <AlertTriangle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
            <p className="text-sm">{erro}</p>
          </div>
        )}

        {camera === null ? (
          <Button
            type="button"
            variant="outline"
            className="h-12 w-full"
            onClick={() => { setErro(null); setCamera(cameraGuardada()); }}
          >
            <Camera className="h-5 w-5 mr-2" />
            Usar câmara
          </Button>
        ) : (
          <div className="space-y-2">
            <video ref={video} muted playsInline className="w-full rounded-xl bg-black" />
            {cameras.length > 1 && (
              <select
                aria-label="Câmara"
                value={camera}
                onChange={(e) => { guardarCamera(e.target.value); setCamera(e.target.value); }}
                className="h-12 w-full rounded-md border bg-background px-3"
              >
                <option value="">Câmara por omissão</option>
                {cameras.map((c, i) => (
                  <option key={c.deviceId || i} value={c.deviceId}>
                    {c.label || `Câmara ${i + 1}`}
                  </option>
                ))}
              </select>
            )}
          </div>
        )}

        <Button type="button" variant="outline" className="h-12 w-full" onClick={onFechar}>
          Fechar
        </Button>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 5: Correr e ver passar**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && .venv/bin/pytest tests/faturacao/test_os_pontos_no_ecra_do_pos.py -q
```

Esperado: `7 passed`, `0 skipped`.

- [ ] **Step 6: Validação por mutação (campo limpo e uma leitura de cada vez)**

a) Em `ler`, apagar `setCodigo('');`. Correr o Step 5. Esperado: `test_depois_de_uma_recusa_o_campo_fica_limpo_para_a_leitura_seguinte` FAILED (`'LQ7K2MN8P3QRSTUV4WXYZ9AB' == ''`). Repor.

b) Trocar `if (!lido || ocupado.current) return;` por `if (!lido) return;`. Correr o Step 5. Esperado: `test_dois_Enter_seguidos_so_perguntam_uma_vez` FAILED (`2 == 1`). Repor.

Correr o Step 5 outra vez: `7 passed`.

- [ ] **Step 7: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos
git add frontend/package.json frontend/yarn.lock frontend/src/pages/pos/PosLerQr.js backend/tests/faturacao/test_os_pontos_no_ecra_do_pos.py
git commit -F - <<'EOF'
POS: a janela Ler QR do cliente — leitor do POS HP e câmara com jsQR

O campo abre com o foco dentro de um form (o Enter do leitor submete); a
câmara usa getUserMedia com escolha de câmara e pára as pistas ao
desmontar. jsqr fixado em 1.4.0.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 4: O cartão «Pontos L'Açaí» no Finalizar e o EMITIR com `pontos_ligacao`

**Files:**
- Modify: `frontend/src/pages/pos/PosFinalizar.js` — imports (linhas 3-18); `CartaoPontos` antes de `// --- Pagamento ---` (linha 531 original); estado junto do NIF (linhas 962-968 originais); `onEmitir` (linhas 1237-1243 originais); render depois de `<CartaoCliente …/>` (linha 1322 original). (As linhas deslocam-se com a Task 2 — procurar pelos textos citados.)
- Modify: `backend/tests/faturacao/test_os_pontos_no_ecra_do_pos.py` — import e testes novos.
- `frontend/src/pages/pos/PosVenda.js`: **não muda** (`emitir`, linhas 1766-1791, passa `dados` a `finalizarVenda(vendaId, dados)` na linha 1776). **Mas é ele que obriga ao efeito:** numa conta dividida, o `voltarDoFinalizar` faz `aplicarVenda(null)` e chama o `cobrarParte` da pessoa seguinte (linhas 2400-2402), o `cobrarParte` só troca a venda e mantém a vista no finalizar (linhas 2059-2066), e o `<PosFinalizar>` (linhas 2612-2621) não leva `key` — o ecrã NÃO se desmonta entre pessoas, só lhe muda o prop `venda`. É a fixture `parte_seguinte` que mede isso.

**Interfaces:**
- Consumes: `guardarPontosDaConta`, `lerPontosDaConta` (Task 1); `PosLerQr` (Task 3); `Cartao({ titulo, icone, children })` (`PosFinalizar.js:192`); `_arranque(respostas_extra)`, `_conta(id_, linhas, estado, mae)`, `_linha`, `_L_COOKIE`, `_L_ACAI`, `_correr(cenario, tmp_path_factory, nome)` de `test_o_dividir_e_o_separar_no_ecra.py`.
- Produces: `onEmitir({ pagamentos, nif, pontos_ligacao: {id, primeiro_nome} | null })` — chega ao corpo de `POST /pos/venda/{id}/finalizar`.

- [ ] **Step 1: Escrever o teste que falha**

Em `backend/tests/faturacao/test_os_pontos_no_ecra_do_pos.py`, substituir:

```python
from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _COMPONENTES
```

por:

```python
from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _COMPONENTES
from .test_o_dividir_e_o_separar_no_ecra import _L_ACAI, _L_COOKIE, _arranque, _conta, _correr
```

E acrescentar no fim do ficheiro:

```python
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
```

- [ ] **Step 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && .venv/bin/pytest tests/faturacao/test_os_pontos_no_ecra_do_pos.py -q
```

Esperado: `5 failed, 8 passed, 5 errors`. FAILED: `test_o_cartao_dos_pontos_esta_entre_o_Cliente_e_o_Pagamento`, `test_sem_leitura_o_cartao_so_oferece_ler_o_QR` e `test_sem_pontos_o_EMITIR_manda_pontos_ligacao_a_null_e_nao_o_omite` (`o EMITIR deixou de mandar pontos_ligacao: {'pagamentos': [...], 'nif': None}`), mais os dois do `parte_seguinte` — `test_a_pessoa_SEGUINTE_da_conta_dividida_nao_herda_o_cliente_da_anterior` (não há cartão nenhum no ecrã, por isso falta «Pontos para: Ana ✓» na pessoa 1) e `test_o_EMITIR_da_pessoa_SEGUINTE_vai_sem_pontos` (`o EMITIR deixou de mandar pontos_ligacao`). ERROR nas fixtures `lido`, `recusado` (`sem botão vivo com o texto Ler QR do cliente`) e `guardado` (`… Remover`) — a `parte_seguinte` NÃO erra, porque só carrega em botões que já existem. Passam os 7 da janela e `test_a_ligacao_de_OUTRA_conta_nao_aparece_nesta` (é uma guarda: já é verdade antes do cartão existir).

- [ ] **Step 3: Escrever o mínimo que faz passar**

Em `frontend/src/pages/pos/PosFinalizar.js`, substituir os imports:

```js
import {
  ArrowLeft, Pencil, X, ChevronDown, Loader2, AlertTriangle, CheckCircle2,
  ShieldAlert, Ban, User, Receipt, Printer, CreditCard, Coins, Divide, Scissors, Users,
  Minus, Plus,
} from 'lucide-react';
```

por:

```js
import {
  ArrowLeft, Pencil, X, ChevronDown, Loader2, AlertTriangle, CheckCircle2,
  ShieldAlert, Ban, User, Receipt, Printer, CreditCard, Coins, Divide, Scissors, Users,
  Minus, Plus, Gift, QrCode,
} from 'lucide-react';
```

Substituir:

```js
import PosCampoValor, { TecladoNumerico, comVirgula } from './PosCampoValor';
import {
  contaTravada, duvidaPorApurar, detalhesErroPos, eurosPos as euros,
  temMaisDe2CasasDecimaisPos, avisoDoDocumento, previsaoDoDividir,
  guardarNifDaConta, lerNifDaConta, nifValidoPT,
} from '@/lib/pos';
```

por:

```js
import PosCampoValor, { TecladoNumerico, comVirgula } from './PosCampoValor';
import PosLerQr from './PosLerQr';
import {
  contaTravada, duvidaPorApurar, detalhesErroPos, eurosPos as euros,
  temMaisDe2CasasDecimaisPos, avisoDoDocumento, previsaoDoDividir,
  guardarNifDaConta, lerNifDaConta, nifValidoPT,
  guardarPontosDaConta, lerPontosDaConta,
} from '@/lib/pos';
```

Imediatamente antes da linha `// --- Pagamento ---------------------------------------------------------------`, inserir:

```jsx
// --- Pontos L'Açaí -----------------------------------------------------------

// **Ganha os pontos quem mostra a app na caixa antes de pagar.** A funcionária
// lê o QR que o cliente mostra (a janela `PosLerQr`), e a ligação viaja no
// EMITIR em `pontos_ligacao`; os pontos só entram depois de a Fatura
// Simplificada sair, do lado do servidor.
//
// **Este cartão nunca entra no `motivoBloqueio`.** Os pontos são do cliente,
// não da fatura: com a app em baixo, um QR expirado ou um cliente sem
// telemóvel, a venda segue. Um EMITIR preso por causa dos pontos era a fila
// parada por uma coisa que não é fiscal.
//
// Só o PRIMEIRO nome, cortado pela app: o ecrã da caixa está à vista da loja.
function CartaoPontos({ ligacao, onLer, onRemover, desativado }) {
  return (
    <Cartao titulo="Pontos L'Açaí" icone={Gift}>
      {ligacao ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="font-heading font-bold text-2xl min-w-0 break-words">
            {`Pontos para: ${ligacao.primeiro_nome} ✓`}
          </p>
          <Button type="button" variant="outline" className="h-12" onClick={onRemover} disabled={desativado}>
            Remover
          </Button>
        </div>
      ) : (
        <Button
          type="button"
          variant="outline"
          className="h-12 mt-2 w-full sm:w-auto"
          onClick={onLer}
          disabled={desativado}
        >
          <QrCode className="h-5 w-5 mr-2" />
          Ler QR do cliente
        </Button>
      )}
    </Cartao>
  );
}

```

Substituir:

```js
  // O NIF sobrevive a sair deste ecrã para juntar mais um artigo à conta —
  // preso ao id DESTA conta, ver `lib/pos.js::guardarNifDaConta`.
  const [nifTexto, setNifTexto] = useState(() => lerNifDaConta(venda?.id));

  // Trocar de conta (cobrar outra parte de uma conta repartida) recomeça do
  // NIF daquela conta — nunca herda o da anterior.
  useEffect(() => { setNifTexto(lerNifDaConta(venda?.id)); }, [venda?.id]);
```

por:

```js
  // O NIF sobrevive a sair deste ecrã para juntar mais um artigo à conta —
  // preso ao id DESTA conta, ver `lib/pos.js::guardarNifDaConta`.
  const [nifTexto, setNifTexto] = useState(() => lerNifDaConta(venda?.id));
  // O cliente dos pontos L'Açaí, pelo mesmo molde e pela mesma razão
  // (`lib/pos.js::guardarPontosDaConta`). Guarda-se no gesto — ler ou remover —
  // e não num efeito, para a montagem do ecrã nunca escrever na gaveta.
  const [ligacao, setLigacao] = useState(() => lerPontosDaConta(venda?.id));
  const [aLerQr, setALerQr] = useState(false);
  const mudarLigacao = (nova) => {
    setLigacao(nova);
    guardarPontosDaConta(venda?.id, nova);
  };

  // Trocar de conta (cobrar outra parte de uma conta repartida) recomeça do
  // NIF e dos pontos daquela conta — nunca herda os da anterior. E fecha a
  // janela do QR, que era da outra conta.
  useEffect(() => {
    setNifTexto(lerNifDaConta(venda?.id));
    setLigacao(lerPontosDaConta(venda?.id));
    setALerQr(false);
  }, [venda?.id]);
```

Substituir:

```js
    onEmitir({
      pagamentos: pagamentos.map((p) => ({
        tipo_pagamento_id: p.tipo_pagamento_id,
        valor: Number(p.valor),
      })),
      nif: digitosNif || null,
    });
```

por:

```js
    onEmitir({
      pagamentos: pagamentos.map((p) => ({
        tipo_pagamento_id: p.tipo_pagamento_id,
        valor: Number(p.valor),
      })),
      nif: digitosNif || null,
      // SEMPRE presente, `null` quando não houve QR: o servidor grava-o em
      // `dados_pagamento` em cada tentativa, e uma tentativa sem pontos nunca
      // deixa agarrado à venda o cliente de uma anterior.
      pontos_ligacao: ligacao ? { id: ligacao.id, primeiro_nome: ligacao.primeiro_nome } : null,
    });
```

Substituir:

```jsx
          <CartaoCliente nifTexto={nifTexto} onNifTexto={setNifTexto} desativado={aEmitir || congelada} />
```

por:

```jsx
          <CartaoCliente nifTexto={nifTexto} onNifTexto={setNifTexto} desativado={aEmitir || congelada} />

          <CartaoPontos
            ligacao={ligacao}
            onLer={() => setALerQr(true)}
            onRemover={() => mudarLigacao(null)}
            desativado={aEmitir || congelada}
          />
          {/* Montada só enquanto está aberta: desmontar é o que desliga a
              câmara (ver PosLerQr). */}
          {aLerQr && (
            <PosLerQr
              vendaId={venda?.id}
              onLigada={(nova) => { mudarLigacao(nova); setALerQr(false); }}
              onFechar={() => setALerQr(false)}
            />
          )}
```

- [ ] **Step 4: Correr e ver passar**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && .venv/bin/pytest tests/faturacao/test_os_pontos_no_ecra_do_pos.py tests/faturacao/test_o_dividir_e_o_separar_no_ecra.py tests/faturacao/test_o_nif_que_nao_existe_no_pos.py tests/faturacao/test_campos_de_valor_no_ecra.py -q
```

Esperado: `84 passed`, `0 skipped` (18 em `test_os_pontos_no_ecra_do_pos.py`).

- [ ] **Step 5: Validação por mutação (sempre presente, fora do `motivoBloqueio`, e a troca de pessoa)**

(Os números são sobre os 84 testes do comando do Step 4.)

a) No `onEmitir`, trocar a linha do `pontos_ligacao` por `...(ligacao ? { pontos_ligacao: { id: ligacao.id, primeiro_nome: ligacao.primeiro_nome } } : {}),`. Correr o Step 4. Esperado: `4 failed, 80 passed` — `test_sem_pontos_o_EMITIR_manda_pontos_ligacao_a_null_e_nao_o_omite` e `test_o_EMITIR_da_pessoa_SEGUINTE_vai_sem_pontos` com `o EMITIR deixou de mandar pontos_ligacao`, e os de `recusado`/`guardado` com `KeyError: 'pontos_ligacao'`. Repor.

b) No `motivoBloqueio`, logo a seguir a `if (pagamentos.length === 0) return { texto: 'Escolha como o cliente vai pagar.' };`, acrescentar `if (!ligacao) return { texto: 'Leia o QR do cliente.' };`. Correr o Step 4. Esperado: `8 errors` — as fixtures `sem_pontos`, `recusado`, `guardado` e `parte_seguinte` rebentam com `Error: sem botão vivo com o texto EMITIR DOCUMENTO`; os 76 restantes passam. Repor.

c) **A guarda da conta dividida.** No `useEffect([venda?.id])` do `PosFinalizar`, apagar a linha `setLigacao(lerPontosDaConta(venda?.id));` (deixar lá o `setNifTexto` e o `setALerQr(false)`). Correr o Step 4. Esperado: `2 failed, 82 passed` — `test_a_pessoa_SEGUINTE_da_conta_dividida_nao_herda_o_cliente_da_anterior` com `A pessoa 2 ficou com o cliente dos pontos da pessoa 1: … Pontos para: Ana ✓ …` e `test_o_EMITIR_da_pessoa_SEGUINTE_vai_sem_pontos` com `O EMITIR da pessoa 2 levou a ligação da pessoa 1: {… 'pontos_ligacao': {'id': 'lig-1', 'primeiro_nome': 'Ana'}}`. **Que os outros 82 fiquem verdes é metade da prova:** nenhuma outra fixture troca a venda com o ecrã montado, por isso nenhuma delas vê este defeito. Repor.

Correr o Step 4 outra vez: `0 failed`.

- [ ] **Step 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos
git add frontend/src/pages/pos/PosFinalizar.js backend/tests/faturacao/test_os_pontos_no_ecra_do_pos.py
git commit -F - <<'EOF'
POS: cartão Pontos L'Açaí no Finalizar e pontos_ligacao no EMITIR

Entre Cliente e Pagamento: «Ler QR do cliente» ou «Pontos para: Ana ✓» e
Remover. Presa à conta, nunca bloqueia o EMITIR, e o EMITIR manda sempre
pontos_ligacao (null sem QR). O PosVenda passa os dados tal e qual.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 5: A linha «Pontos L'Açaí» no detalhe do documento (backoffice)

**Files:**
- Modify: `frontend/src/pages/admin/faturacao/FatDocumentos.js` — depois da linha 56 (`const primeiroDoMes = …`); antes da linha 449 (comentário «Quem emitiu, onde e quando»).
- Modify: `backend/tests/faturacao/test_o_ecra_de_documentos_no_backoffice.py` — testes novos no fim.

**Interfaces:**
- Consumes: `GET /api/faturacao/documentos/{id}` → `pontos_app` (forma nas Global Constraints; do C1); `formatarData(iso)` (`FatDocumentos.js:39`).
- Produces: bloco `data-testid="documento-pontos-app"`; `textoDosPontosApp(p) -> string` (privada do módulo).

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar no fim de `backend/tests/faturacao/test_o_ecra_de_documentos_no_backoffice.py`:

```python
# --- Os pontos L'Açaí do documento ---------------------------------------------
#
# A pergunta que chega ao gestor: «mostrei a app na caixa e não recebi os
# pontos». O detalhe da fatura responde com a linha da fila `fat_pontos_app`
# que o servidor manda em `pontos_app` — numa fatura o crédito, numa nota de
# crédito o estorno. Cada estado em palavras, e um motivo que o ecrã ainda não
# conheça aparece em cru: nunca em silêncio.

_BASE_PONTOS = {
    "tipo": "credito", "estado": "pendente", "pontos": None, "primeiro_nome": "Ana",
    "motivo": None, "tentativas": 0, "ultimo_erro": None,
    "atualizado_em": "2026-08-10T12:01:00+00:00",
}

_ESTADOS_DOS_PONTOS = [
    ("credito_feito", "FS", {"estado": "feito", "pontos": 17, "tentativas": 1},
     "17 pontos para Ana"),
    ("um_ponto", "FS", {"estado": "feito", "pontos": 1, "tentativas": 1},
     "1 ponto para Ana"),
    ("a_tentar", "FS", {"tentativas": 3, "ultimo_erro": "HTTP 503"},
     "A tentar enviar (3 tentativas — último erro: HTTP 503)"),
    ("a_espera", "FS", {},
     "À espera de ser enviado."),
    ("plataforma", "FS", {"estado": "recusado", "motivo": "plataforma", "tentativas": 1},
     "Recusado: pagamento por plataforma"),
    ("motivo_novo", "FS", {"estado": "recusado", "motivo": "motivo_que_ainda_nao_existe"},
     "Recusado: motivo_que_ainda_nao_existe"),
    ("falhado", "FS", {"estado": "falhado", "tentativas": 40, "ultimo_erro": "timeout"},
     "Falhou ao fim de 24 h"),
    ("estorno_feito", "NC", {"tipo": "estorno", "estado": "feito", "pontos": 5},
     "Retirados 5 pontos a Ana"),
    ("estorno_sem_efeito", "NC", {"tipo": "estorno", "estado": "sem_efeito"},
     "Sem efeito — a fatura não chegou a dar pontos."),
]


@pytest.fixture(scope="module")
def pontos(tmp_path_factory):
    casos = {
        nome: dict(_FATURA, tipo=tipo, pontos_app=dict(_BASE_PONTOS, **mudancas))
        for nome, tipo, mudancas, _frase in _ESTADOS_DOS_PONTOS
    }
    casos["sem_pontos"] = dict(_FATURA, pontos_app=None)
    cenario = "\n".join([
        _COMPONENTES,
        "const ADMIN = path.join(RAIZ, 'pages', 'admin', 'faturacao');",
        "const FatDocumentos = carregar(path.join(ADMIN, 'FatDocumentos.js')).default;",
        "const CASOS = %s;" % json.dumps(casos, ensure_ascii=False),
        "RESPOSTAS_GESTAO['/faturacao/lojas'] = () => ({ data: %s });"
        % json.dumps(_LOJAS, ensure_ascii=False),
        "RESPOSTAS_GESTAO['/faturacao/documentos'] = () => ({ data: %s });"
        % json.dumps(_LISTA, ensure_ascii=False),
        "const alvo = document.getElementById('raiz');",
        "const raiz = createRoot(alvo);",
        "await act(async () => { raiz.render(React.createElement(FatDocumentos)); });",
        "await act(async () => {});",
        "await act(async () => {});",
        "const linha = alvo.querySelector('[data-testid=\"documento-d1\"]');",
        "if (!linha) throw new Error('sem linha da fatura: ' + textoVisivel(alvo).slice(0, 400));",
        "const saida = {};",
        # Cada caso é o MESMO documento aberto outra vez com outra resposta do
        # servidor — o `sem_pontos` fica em último de propósito: prova que o
        # bloco desaparece, e não só que nunca apareceu.
        "for (const [nome, documento] of Object.entries(CASOS)) {",
        "  RESPOSTAS_GESTAO['/faturacao/documentos/d1'] = () => ({ data: documento });",
        "  await act(async () => { linha.click(); });",
        "  await act(async () => {});",
        "  const bloco = alvo.querySelector('[data-testid=\"documento-pontos-app\"]');",
        "  saida[nome] = { aberta: textoVisivel(alvo).includes('Itens'),",
        "    pontos: bloco ? textoVisivel(bloco) : null };",
        "}",
        "process.stdout.write(JSON.stringify(saida));",
    ])
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => {"
        " process.stderr.write(String(e && e.stack || e)); process.exit(1); });"
        % cenario, tmp_path_factory.mktemp("documentos-pontos"), "montar-documentos-pontos.js")


@pytest.mark.parametrize("nome,frase", [(n, f) for n, _t, _m, f in _ESTADOS_DOS_PONTOS])
def test_o_detalhe_diz_o_que_aconteceu_aos_pontos_L_Acai(pontos, nome, frase):
    caso = pontos[nome]
    assert caso["aberta"], "o detalhe do documento não abriu"
    assert caso["pontos"] is not None, "o detalhe não mostra a linha dos pontos L'Açaí"
    assert "Pontos L'Açaí" in caso["pontos"], caso["pontos"]
    assert frase in caso["pontos"], caso["pontos"]


def test_um_documento_sem_QR_nao_mostra_linha_de_pontos(pontos):
    """A maioria dos documentos. Uma linha vazia ou um «—» lia-se como «os
    pontos perderam-se»."""
    assert pontos["sem_pontos"]["aberta"]
    assert pontos["sem_pontos"]["pontos"] is None
```

- [ ] **Step 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && .venv/bin/pytest tests/faturacao/test_o_ecra_de_documentos_no_backoffice.py -q
```

Esperado: `9 failed, 9 passed` — os 9 `test_o_detalhe_diz_o_que_aconteceu_aos_pontos_L_Acai[…]` FAILED com `o detalhe não mostra a linha dos pontos L'Açaí`; passam `test_um_documento_sem_QR_nao_mostra_linha_de_pontos` e os 8 antigos.

- [ ] **Step 3: Escrever o mínimo que faz passar**

Em `frontend/src/pages/admin/faturacao/FatDocumentos.js`, logo a seguir a:

```js
const primeiroDoMes = () => hoje().slice(0, 8) + '01';
```

inserir:

```js

// **O que aconteceu aos pontos L'Açaí deste documento.** O servidor manda
// `pontos_app` — a linha da fila `fat_pontos_app`: numa fatura, o crédito ao
// cliente que mostrou a app na caixa; numa nota de crédito, o estorno que ela
// provocou. `null` quando não houve QR (a maioria), e aí não se desenha nada.
//
// É para o gestor responder a quem diz que não recebeu os pontos, por isso
// cada estado diz em palavras o que se passou, e um estado ou motivo que este
// ecrã ainda não conheça aparece em cru — nunca em silêncio.
const MOTIVOS_DOS_PONTOS = {
  plataforma: 'pagamento por plataforma',
  sem_valor: 'a fatura não tem valor para pontos (só caução)',
  acima_do_teto: 'a fatura passa o valor máximo que dá pontos',
  fatura_bloqueada: 'a fatura está bloqueada na app',
  fatura_de_outra_conta: 'a fatura já deu pontos a outra conta',
  ligacao_desconhecida: 'a app não reconhece a leitura do QR',
  ligacao_expirada: 'a fatura saiu muito depois de o QR ser lido',
  ligacao_ja_usada: 'aquele QR já deu pontos noutra fatura',
};

const textoDosPontosApp = (p) => {
  const pontos = p.pontos == null ? 'pontos' : `${p.pontos} ${p.pontos === 1 ? 'ponto' : 'pontos'}`;
  if (p.estado === 'feito' && p.tipo === 'estorno') {
    return `Retirados ${pontos}${p.primeiro_nome ? ` a ${p.primeiro_nome}` : ''}`;
  }
  if (p.estado === 'feito') {
    return `${pontos[0].toUpperCase()}${pontos.slice(1)}${p.primeiro_nome ? ` para ${p.primeiro_nome}` : ''}`;
  }
  if (p.estado === 'pendente') {
    return p.tentativas > 0
      ? `A tentar enviar (${p.tentativas} ${p.tentativas === 1 ? 'tentativa' : 'tentativas'} — último erro: ${p.ultimo_erro || 'sem detalhe'})`
      : 'À espera de ser enviado.';
  }
  if (p.estado === 'recusado') {
    return `Recusado: ${MOTIVOS_DOS_PONTOS[p.motivo] || p.motivo || 'sem motivo'}`;
  }
  if (p.estado === 'sem_efeito') return 'Sem efeito — a fatura não chegou a dar pontos.';
  if (p.estado === 'falhado') {
    return `Falhou ao fim de 24 h${p.ultimo_erro ? ` — último erro: ${p.ultimo_erro}` : ''}`;
  }
  return `Estado desconhecido: ${p.estado}`;
};
```

E imediatamente antes de:

```jsx
              {/* Quem emitiu, onde e quando — as três perguntas que a fatura
```

inserir:

```jsx
              {aberto.pontos_app && (
                <div className="rounded-xl border p-3 text-sm" data-testid="documento-pontos-app">
                  <p className="text-xs uppercase tracking-wide text-muted-foreground mb-1">
                    Pontos L'Açaí
                  </p>
                  <p className="font-medium">{textoDosPontosApp(aberto.pontos_app)}</p>
                  {aberto.pontos_app.atualizado_em && (
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Atualizado {formatarData(aberto.pontos_app.atualizado_em)}
                    </p>
                  )}
                </div>
              )}

```

- [ ] **Step 4: Correr e ver passar**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && .venv/bin/pytest tests/faturacao/test_o_ecra_de_documentos_no_backoffice.py -q
```

Esperado: `18 passed`, `0 skipped`.

- [ ] **Step 5: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos
git add frontend/src/pages/admin/faturacao/FatDocumentos.js backend/tests/faturacao/test_o_ecra_de_documentos_no_backoffice.py
git commit -F - <<'EOF'
Documentos: a linha Pontos L'Açaí no detalhe da fatura e da nota de crédito

Mostra o pontos_app do servidor em palavras — «17 pontos para Ana», «A
tentar enviar (3 tentativas — último erro: …)», «Recusado: pagamento por
plataforma», «Falhou ao fim de 24 h» — e o estorno na nota de crédito.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 6: Compilar e percorrer o Finalizar no browser com o servidor simulado

**Isto NÃO prova as chamadas ao servidor real** (é um servidor de mentira que responde o que lhe mandam responder). Prova o que os testes em jsdom não veem: o foco automático no Chrome, o Enter a submeter, a janela a abrir e fechar, a câmara a ligar/desligar, e o aspeto. As chamadas estão provadas pelos testes montados e pelo `test_caminhos_do_pos.py` (Task 7).

**Files:**
- Create (FORA do repo, no scratchpad da sessão do executor): `pos-mock.js`
- Nenhum ficheiro do repo muda nesta Task.

**Interfaces:**
- Consumes: o build (`frontend/build`, ignorado pelo git) servido na mesma origem da API simulada.

- [ ] **Step 1: Compilar**

```bash
export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH"
cd /Users/matheus.moraes/Developer/RH-pontos/frontend && REACT_APP_BACKEND_URL= CI=false yarn build 2>&1 | tail -40
```

`REACT_APP_BACKEND_URL=` vazio é obrigatório: o `.env.production` é versionado (app Capacitor) e sem isto o build aponta para produção. Esperado (medido, ~20 s): `Compiled with warnings.` com a lista de ficheiros de sempre — `AuthContext.js`, `LoginPage.js`, `admin/*`, `admin/faturacao/FatConsumo.js`, `FatDocumentos.js` (o `procurar` do `useEffect`, que já existia), `FatRelatorios.js`, `financeiro/*`, `EmployeeDocuments.js`, `pos/PosVenda.js` (`cobrarParte`, já existia). **Nenhum aviso em `pos/PosLerQr.js` nem em `pos/PosFinalizar.js`.**

- [ ] **Step 2: Criar o servidor de mentira**

No scratchpad da sessão (nunca dentro do repo), criar `pos-mock.js`:

```js
// Servidor de mentira do Finalizar com os pontos L'Açaí (plano C2, Task 6).
// Serve o build do frontend e responde às rotas do POS que o arranque, o
// Finalizar e a leitura do QR usam. Não fala com servidor real nenhum.
//
// A rota dos pontos decide pelo código lido:
//   contém EXPIRADO -> 404 (QR recusado)
//   contém EMBAIXO  -> 503 (app em baixo)
//   outro qualquer  -> 200, ligação da Ana
const http = require('http');
const fs = require('fs');
const path = require('path');

const BUILD = path.resolve(process.argv[2]);
const PORTA = 8765;

const CAIXA = { id: 'c1', nome: 'Caixa 1' };
const LINHA = {
  id: 'l1', produto_id: 'p-acai', produto_nome: 'Açaí Regular', produto_preco: 8.99,
  produto_tax_id: 'INT', quantidade: 1, opcoes: [], respostas_texto: [],
  preco_override: null, tax_override: null, desconto_pct: null, desconto_eur: null,
};
const VENDA = {
  id: 'v-1', loja_id: 'l1', caixa_id: 'c1', sessao_id: 's1', operador_id: 'o1',
  linhas: [LINHA], desconto_global_pct: null, desconto_global_eur: null,
  estado: 'aberta', criada_em: '2026-09-15T10:00:00+00:00', cancelada_em: null,
  cancelada_por: null, conta_mae_id: null, emissao_por_confirmar: false,
  entregue_ao_gestor_em: null, entregue_ao_gestor_por: null,
  totais: { subtotal: 8.99, desconto_linhas: 0, desconto_global: 0, deposito: 0, embalagens: 0, total: 8.99 },
};
const PRODUTO = {
  id: 'p-acai', nome: 'Açaí Regular', categoria_id: 'cat-1', preco: 8.99, tax_id: 'INT',
  foto_url: null, grupos_personalizacao: [], ativo: true, vendavel: true, erros: [],
};
let emitida = false;

const ROTAS = {
  'GET /api/faturacao/pos/caixa/estado': () => [200, {
    caixas: [CAIXA], caixa: CAIXA, ultimo_fecho: null,
    sessao_aberta: { id: 's1', aberta_por: { nome: 'Ana' }, aberta_em: '2026-09-15T09:00:00+00:00', fundo: 50 },
  }],
  'GET /api/faturacao/pos/modo-de-emissao': () => [200, { modo: 'normal' }],
  'GET /api/faturacao/pos/impressao/estado': () => [200, { ha_programa: true, por_sair: 0, falhados: 0 }],
  'GET /api/faturacao/pos/catalogo': () => [200, {
    categorias: [{ id: 'cat-1', nome: 'Venda ao Público', ordem: 0, ativa: true }],
    produtos: [PRODUTO],
  }],
  'GET /api/faturacao/pos/tipos-pagamento': () => [200, [
    { id: 'tp-1', nome: 'Dinheiro', da_troco: true, pronto: true, ordem: 0 },
    { id: 'tp-2', nome: 'Multibanco', da_troco: false, pronto: true, ordem: 1 },
  ]],
  'GET /api/faturacao/pos/venda/aberta': () => [200, emitida ? null : VENDA],
  'GET /api/faturacao/pos/venda/repartidas': () => [200, { grupos: [] }],
  'POST /api/faturacao/pos/pontos/ler': (corpo) => {
    console.log('PONTOS/LER ' + JSON.stringify(corpo));
    const codigo = String(corpo.codigo || '').toUpperCase();
    if (codigo.includes('EXPIRADO')) {
      return [404, { detail: 'QR inválido ou expirado — peça ao cliente para abrir o QR outra vez.' }];
    }
    if (codigo.includes('EMBAIXO')) {
      return [503, { detail: 'Não foi possível falar com a app agora. A fatura pode seguir sem pontos.' }];
    }
    return [200, { ligacao_id: 'lig-1', primeiro_nome: 'Ana' }];
  },
  'POST /api/faturacao/pos/venda/v-1/finalizar': (corpo) => {
    console.log('FINALIZAR ' + JSON.stringify(corpo));
    emitida = true;
    return [200, {
      ...VENDA, estado: 'emitida',
      documento: { id: 'd-1', numero: 'FS 01P2026/99', atcud: 'ABCD-99', total: 8.99, modo: 'normal', vendus_document_id: 1 },
    }];
  },
};

const TIPOS = {
  '.html': 'text/html; charset=utf-8', '.js': 'application/javascript', '.css': 'text/css',
  '.json': 'application/json', '.png': 'image/png', '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon', '.woff2': 'font/woff2', '.map': 'application/json',
};

http.createServer((req, res) => {
  const url = req.url.split('?')[0];
  let bruto = '';
  req.on('data', (pedaco) => { bruto += pedaco; });
  req.on('end', () => {
    if (url.startsWith('/api/')) {
      const rota = ROTAS[`${req.method} ${url}`];
      if (!rota) console.log('SEM ROTA ' + req.method + ' ' + url);
      const [status, corpo] = rota
        ? rota(bruto ? JSON.parse(bruto) : {})
        : [404, { detail: `rota não simulada: ${req.method} ${url}` }];
      res.writeHead(status, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(corpo));
      return;
    }
    const pedido = path.join(BUILD, path.normalize(url));
    const existe = pedido.startsWith(BUILD) && fs.existsSync(pedido) && fs.statSync(pedido).isFile();
    const ficheiro = existe ? pedido : path.join(BUILD, 'index.html');
    res.writeHead(200, { 'Content-Type': TIPOS[path.extname(ficheiro)] || 'application/octet-stream' });
    fs.createReadStream(ficheiro).pipe(res);
  });
}).listen(PORTA, () => console.log(`simulado em http://localhost:${PORTA}/faturacao/pos`));
```

- [ ] **Step 3: Arrancar o servidor em segundo plano**

```bash
export PATH="$HOME/.local/node/bin:$PATH"
node "<scratchpad da sessão>/pos-mock.js" /Users/matheus.moraes/Developer/RH-pontos/frontend/build
```

(em segundo plano; a saída deste processo é o registo `PONTOS/LER …`, `FINALIZAR …` e `SEM ROTA …` que os passos seguintes leem). Esperado: `simulado em http://localhost:8765/faturacao/pos`.

- [ ] **Step 4: Percorrer no browser**

1. Abrir `http://localhost:8765/faturacao/pos`. Semear, por JavaScript na página:
   ```js
   localStorage.setItem('pos_device_token', 'dt');
   localStorage.setItem('pos_loja_id', 'l1');
   localStorage.setItem('pos_loja_nome', 'Loja de Ensaio');
   localStorage.setItem('pos_caixa_id', 'c1');
   sessionStorage.setItem('pos_operator_token', 'ot');
   sessionStorage.setItem('pos_operador', JSON.stringify({ id: 'o1', nome: 'Ana' }));
   location.reload();
   ```
2. A conta com o Açaí Regular aparece. Tocar **FINALIZAR**. Esperado: cartões pela ordem Total → Cliente → **Pontos L'Açaí** («Ler QR do cliente») → Pagamento. Captura de ecrã.
3. Tocar **Ler QR do cliente**. Esperado: janela aberta e, por JavaScript, `document.activeElement.id === 'qr-dos-pontos'` → `true` (o foco automático que o leitor precisa).
4. Escrever `LQEXPIRADO` no campo e carregar **Enter**. Esperado: registo `PONTOS/LER {"venda_id":"v-1","codigo":"LQEXPIRADO"}`; frase vermelha «QR inválido ou expirado — peça ao cliente para abrir o QR outra vez.»; o campo fica vazio.
5. Escrever `LQEMBAIXO` e **Enter**. Esperado: «Não foi possível falar com a app agora. A fatura pode seguir sem pontos.».
6. Tocar **Usar câmara**. Esperado: ou a imagem da câmara, ou a frase «Não foi possível abrir a câmara. …» (o painel do browser pode não ter câmara — as duas saídas estão certas; um erro na consola não). Tocar **Fechar**. Esperado, por JavaScript: `document.querySelector('video') === null` e `document.getElementById('qr-dos-pontos') === null`.
7. Tocar outra vez **Ler QR do cliente**, escrever `LQ7K2MN8P3QRSTUV4WXYZ9AB` e **Enter**. Esperado: a janela fecha e o cartão diz **«Pontos para: Ana ✓»** com **Remover**. Captura de ecrã.
8. Seta de voltar → conta → **FINALIZAR**. Esperado: o cartão continua «Pontos para: Ana ✓»; por JavaScript, `sessionStorage.getItem('pos_pontos_da_conta')` contém `"vendaId":"v-1"`.
9. Tocar **Remover**. Esperado: volta «Ler QR do cliente». Repetir o ponto 7.
10. Tocar **Dinheiro** e **EMITIR DOCUMENTO**. Esperado: registo `FINALIZAR {…"pontos_ligacao":{"id":"lig-1","primeiro_nome":"Ana"}}` e o ecrã «Documento emitido» com `FS 01P2026/99`.
11. Rever o registo: qualquer `SEM ROTA` é só ruído do simulador se o ecrã não mostrou erro; anotar no relatório.

- [ ] **Step 5: A câmara — que ela PÁRA, e que uma câmara guardada que já não existe não prende a janela**

**Porque é aqui e não nos testes montados:** o jsdom não tem `getUserMedia`, nem `HTMLMediaElement.play`, nem `canvas` (o pacote `canvas` não está instalado), por isso este caminho não se monta em Node. E são dois defeitos que só se sentem na loja: uma luz de câmara acesa depois de fechar a janela, e um `deviceId` guardado de uma câmara que já não existe a recusar a câmara em TODAS as vendas seguintes. O painel deste browser pode nem ter câmara — por isso troca-se a de verdade por uma **`MediaStream` a sério feita de um `<canvas>`** (o `srcObject` do Chrome não aceita imitações), que se pode parar e inspecionar.

O Step 4 acabou com a fatura emitida, e aí não há conta nenhuma: **reiniciar o `pos-mock.js`** (mata-se e arranca-se outra vez — o `emitida` volta a `false`), recarregar a página e tocar **FINALIZAR** para voltar ao ecrã de pagamento.

Depois, no console da página (com o Finalizar à frente, antes de abrir a janela do QR):

```js
window.__camaras = { pedidos: [], pistas: [], recusar: null };
const tela = document.createElement('canvas');
tela.width = 320; tela.height = 240;
tela.getContext('2d').fillRect(0, 0, 320, 240);
navigator.mediaDevices.getUserMedia = async (c) => {
  window.__camaras.pedidos.push(JSON.stringify(c));
  const pedida = c && c.video && c.video.deviceId && c.video.deviceId.exact;
  if (window.__camaras.recusar && pedida === window.__camaras.recusar) {
    throw new DOMException('já não existe', 'NotFoundError');
  }
  const stream = tela.captureStream(5);
  window.__camaras.pistas.push(...stream.getTracks());
  return stream;
};
navigator.mediaDevices.enumerateDevices = async () => ([
  { kind: 'videoinput', deviceId: 'cam-1', label: 'Câmara da frente' },
  { kind: 'videoinput', deviceId: 'cam-2', label: 'Câmara de trás' },
]);
localStorage.removeItem('pos_camera_do_qr');
```

1. **Ler QR do cliente** → **Usar câmara**. Esperado: aparece o `<video>` com imagem, e o selector das câmaras com três opções («Câmara por omissão», «Câmara da frente», «Câmara de trás») — por JavaScript, `document.querySelectorAll('select option').length === 3` e `window.__camaras.pedidos[0] === '{"video":true}'`.
2. Escolher **Câmara de trás** no selector. Esperado, por JavaScript: `localStorage.getItem('pos_camera_do_qr') === 'cam-2'`; `window.__camaras.pedidos[1]` contém `"exact":"cam-2"`; e a pista da câmara anterior já parou — `window.__camaras.pistas[0].readyState === 'ended'` (trocar de câmara refaz o efeito, e a limpeza dele pára a que estava aberta — senão ficavam duas acesas).
3. Tocar **Fechar**. Esperado, por JavaScript: `document.querySelector('video') === null` **e** `window.__camaras.pistas.every((p) => p.readyState === 'ended')` → `true`. **É esta a afirmação que falta aos testes montados**: a câmara desliga porque a janela desmonta.
4. `window.__camaras.recusar = 'cam-2';` no console. Abrir outra vez **Ler QR do cliente** → **Usar câmara**. Esperado: a frase «Não foi possível abrir a câmara. Confirme que o browser a pode usar, ou leia o QR com o leitor.», o botão «Usar câmara» de volta, e — a parte que interessa — `localStorage.getItem('pos_camera_do_qr') === ''`: a câmara guardada que já não existe foi esquecida. Tocar **Usar câmara** outra vez: o pedido volta a ser `{"video":true}` e a imagem aparece. Sem isto, este PC ficava sem câmara para sempre.
5. Tocar **Fechar** e recarregar a página (`location.reload()`) — o stub morre com o reload e os pontos seguintes voltam ao browser a sério.

Qualquer um destes pontos que falhe é um defeito do `PosLerQr`, não do ensaio: anotar o que se viu e parar.

- [ ] **Step 6: Matar o servidor**

Parar o processo do `pos-mock.js` (o do Step 3, ou o que o Step 5 reiniciou). Confirmar com `lsof -i :8765` → sem saída. Nada a commitar nesta Task.

---

## Task 7: A suite inteira e o confronto com o router

**Depende do plano C1:** `test_caminhos_do_pos.py` confronta cada `api.<verbo>('/pos/…')` do `lib/pos.js` com as rotas reais do `router`. A rota `POST /api/faturacao/pos/pontos/ler` só existe depois de o C1 estar no ramo. **Esta Task corre-se no fim, com o C1 já integrado.**

**Files:** nenhum (só verificação).

**Interfaces:**
- Consumes: `faturacao.router` com a rota do C1; linha de base registada no Step 0 da Task 1.

- [ ] **Step 1: Confronto das chamadas com o router**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && .venv/bin/pytest tests/faturacao/test_caminhos_do_pos.py -q
```

Esperado: `12 passed`. Sem o C1 no ramo, o resultado é `1 failed, 11 passed` com `Left contains one more item: 'POST /api/faturacao/pos/pontos/ler'` em `test_todas_as_chamadas_do_pos_apontam_para_rotas_que_existem` (medido): **parar e dizê-lo** — não tirar a chamada, não mudar o caminho. Qualquer outra órfã é um defeito deste plano.

- [ ] **Step 2: A suite de faturação inteira (sem outro trabalho a mexer na árvore)**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos/backend && .venv/bin/pytest tests/faturacao -q 2>&1 | tail -5
```

Esperado: `0 failed`; `passed` = linha de base + os testes novos deste plano + os do C1; **`skipped` igual ao `M` do Step 0 da Task 1**. Um `skipped` maior quer dizer testes de ecrã a saltar (sem `node` ou sem `frontend/node_modules`) — a suite não está verde, está calada.

**Falhas com `Cannot find module 'jsqr'` não são testes a saltar, são a suite a falhar alto de propósito:** desde a Task 4 o `PosFinalizar` importa o `PosLerQr`, que importa o `jsqr`, e o `frontend/node_modules` é partilhado com `~/Developer/RH` — um `yarn install` feito lá apaga-o. Remédio (sem commitar nada: o `package.json` e o `yarn.lock` já o têm): `export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH" && cd /Users/matheus.moraes/Developer/RH-pontos/frontend && yarn add jsqr@1.4.0 --exact`, e voltar a correr.

- [ ] **Step 3: Os testes jest do `lib/pos.js`**

```bash
export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH"
cd /Users/matheus.moraes/Developer/RH-pontos/frontend && CI=true npx craco test --watchAll=false --testPathPattern="src/lib/pos"
```

Esperado: `Tests: … passed`, `0 failed` (o `pos.impressao.test.js` importa o `lib/pos.js` alterado).

- [ ] **Step 4: Árvore limpa**

```bash
cd /Users/matheus.moraes/Developer/RH-pontos && git status --short && git log --oneline -6
```

Esperado: **nenhuma linha `M` ou `D` em `frontend/` nem em `backend/`** — tudo o que este plano escreveu está commitado (o `frontend/build` é ignorado). Os `??` dos ficheiros de plano por commitar (`docs/superpowers/plans/2026-09-15-pontos-no-pos-C1…md` e `…C2…md`) são esperados e não são sujidade. E os 5 commits deste plano no topo (ou intercalados com os do C1).

---

## Decisões deste plano (tomadas por falta de informação na spec)

1. **Campo do NIF — fecho de 500 ms** além de «ignorar alterações com letras»: o leitor escreve uma tecla de cada vez, e a regra literal deixava os dígitos do código entrar (medido num protótipo jsdom). `ESPERA_DO_LEITOR_MS` é o botão de calibração.
2. **`PosVenda.js` não muda:** já passa `dados` intactos a `finalizarVenda`; o teste montado prova o corpo.
3. **Câmara guardada por PC** em `localStorage` (`pos_camera_do_qr`), e câmara por omissão `video: true` (sem adivinhar `facingMode`).
4. **A câmara não repete o mesmo código** depois de uma recusa (precisa de um QR novo — a app renova a cada 40 s); o leitor repete sempre.
5. **Um 401 na leitura** mostra a frase do servidor na janela (o `PosFinalizar` não tem o `operadorInvalido`); o EMITIR seguinte trata o 401 como sempre.
6. **Textos** dos motivos (exceto «pagamento por plataforma»), «À espera de ser enviado.», «Sem efeito — a fatura não chegou a dar pontos.» e «Retirados N pontos a Ana» são deste plano.
7. **`jsqr` por import estático** (entra no bundle principal), não por `import()` preguiçoso.
8. **A câmara não tem teste montado** — o jsdom não tem `getUserMedia`, `play()` nem `canvas`, e montar um faz-de-conta desses três media o faz-de-conta e não o Chrome do Surface. A rede que ela tem é o Step 5 da Task 6: uma `MediaStream` verdadeira feita de um `<canvas>`, para afirmar no browser as duas coisas que doem na loja — as pistas param ao fechar a janela, e uma câmara guardada que já não existe é esquecida em vez de prender o PC. O resto da câmara (descodificar um QR de verdade) é com o dono, no dia D.
