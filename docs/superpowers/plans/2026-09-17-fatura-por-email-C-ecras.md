# Fatura por email — C: ecrãs (POS e backoffice) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-09-17-fatura-por-email-design.md` — secção «POS (RH) — ecrã», o parágrafo do `CartaoPontos`, o «Não há lista nova» de «O que a loja vê», e a parte de ecrã de «Backoffice: o detalhe do documento» e «Reenviar».

**Goal:** ao balcão, depois de ler o QR do cliente, a funcionária vê e muda num toque se aquela fatura vai por email ou em papel — sem nunca ver o endereço —, e o gestor vê no backoffice o que aconteceu ao envio e pode reenviá-lo.

**Architecture:** tudo do lado do browser. O `fatura_por_email` viaja na resposta do `POST /pos/pontos/ler` (Frente B), entra no `onLigada` do `PosLerQr` e fica na mesma gaveta de `sessionStorage` onde já vive o `{id, primeiro_nome}` — **só para desenhar o cartão**: quem decide o papel é o servidor, pelo `fat_pontos_qr`, e uma gaveta adulterada faz o cartão mentir à operadora, não faz desaparecer o documento. Os dois botões do cartão chamam `POST /pos/pontos/preferencia` e gravam o que o SERVIDOR devolveu. A decisão «vai por email?» vive em `lib/pos.js`, onde um teste lhe chega, e não dentro do JSX; a decisão «está por enviar?» vive no SERVIDOR, que já a calcula para o alarme da loja. O separador Faturação ganha um filtro, não uma lista. O backoffice ganha um bloco irmão do «Pontos L'Açaí» e um terceiro botão ao lado dos dois que já lá estão.

**Tech Stack:** React 19 + CRA/craco + shadcn/ui + lucide-react (frontend); testes em pytest que montam os ecrãs REAIS em Node com jsdom e o servidor fabricado à frente do axios (`backend/tests/faturacao/test_a_faixa_do_modo_no_ecra.py::_montar_no_node`).

## Global Constraints

- **Repositório e ramo:** `/Users/matheus.moraes/Developer/RH`, ramo `matheus-fatura-por-email` (já é o ramo actual). Nunca no `main`. **Sem deploy, sem push.**
- **Este plano não toca em código do servidor.** Só `frontend/src/**` e ficheiros de teste em `backend/tests/faturacao/`. `backend/faturacao/*.py` é da Frente B.
- **Contrato com o servidor (Frente B), fixo:**
  - `POST /api/faturacao/pos/pontos/ler` → 200 `{ligacao_id: str, primeiro_nome: str, fatura_por_email: bool}`. **Nunca traz o email, nem mascarado.**
  - `POST /api/faturacao/pos/pontos/preferencia`, sessão do operador, corpo `{venda_id: str, ligacao_id: str, valor: bool}` → 200 `{fatura_por_email: bool}` (o valor COMO FICOU do lado da app). Recusa (ligação já usada, fora da janela) → 4xx com `detail` em português.
  - `GET /api/faturacao/pos/documentos` → cada documento da lista ganha **`fatura_email_por_enviar: bool`**. `true` só quando aquela fatura ia por email e o envio está num dos estados que o alarme da loja conta — `pendente` há mais do que a janela, `falhado`, `recusado`, `sem_efeito` (spec, «O que a loja vê»); `false` em tudo o resto, incluindo a esmagadora maioria, que nunca ia por email. **É o MESMO predicado do `count_documents` que o `estado_da_impressao` (`impressao.py:742`) passa a ter**, calculado uma vez e do lado onde a janela vive: o botão do separador e o alarme da loja têm de contar a mesma coisa, senão a operadora vê o alarme aceso e não encontra a fatura no filtro. O estado cru (`pendente`/`feito`/…) **não** vai para a lista do POS: o balcão não o desenha em lado nenhum.
  - `GET /api/faturacao/documentos/{id}` (gestor) ganha `fatura_email: null | {estado, tentativas: int, ultimo_erro: str|null, motivo: str|null, atualizado_em: str ISO}`.
  - `POST /api/faturacao/documentos/{id}/reenviar-email` (gestor) → 200.
- **O `/pos/` da spec:162 é gralha.** A spec escreve `POST /pos/faturacao/documentos/{id}/reenviar-email`, mas as rotas do gestor vivem em `${API_URL}/faturacao/...` (`lib/faturacao.js:8` e `:273-274`, `documentos.py:839`, `impressao.py:924` — todas `/documentos/...`, sem `/pos/`). O caminho acordado com a Frente B é **`POST /api/faturacao/documentos/{id}/reenviar-email`**, montado no `router` do módulo `faturacao` ao lado do `/documentos/{documento_id}/reimprimir`.
- **O endereço de email NUNCA aparece no POS** e nunca entra na gaveta do `sessionStorage`. Só o sim/não.
- **A preferência NUNCA viaja no corpo do EMITIR.** O `pontos_ligacao` do `POST /pos/venda/{id}/finalizar` continua a ser exactamente `{id, primeiro_nome}` ou `null` (`PosFinalizar.js:1330`) — o servidor nunca lê a preferência do corpo de um pedido do browser.
- **O ecrã não diz «enviada» no instante do EMITIR:** o `tentar_ja` agenda e volta logo (`pontos_app.py:253-267`). A frase é `Fatura vai por email — não é preciso esperar pelo papel.`
- **Das CINCO condições do servidor, o ecrã aplica TRÊS.** O servidor só salta o papel quando, tudo junto: `documento["modo"] == "normal"`; `documento["vendus_document_id"]` não está vazio; a venda tem `pontos_ligacao`; existe linha em `fat_pontos_qr` para aquela ligação e ela diz `fatura_por_email: True`; e a escrita na fila correu (spec, «Emitir», e os Global Constraints do plano B). **O ecrã aplica as três que chegam ao browser:** a ligação com a preferência ligada, o `modo` e o `vendus_document_id` — os dois últimos vêm no `_resposta_documento` (`fiscal.py:1988-1998`), que manda seis campos, e o `vendus_document_id` até já está desenhado no ecrã (`PosFinalizar.js:961`). **As duas que ficam de fora** são a linha do `fat_pontos_qr` em si — este lado vê só a CÓPIA da preferência que ficou na gaveta ao ler o QR, e uma gaveta adulterada faz o cartão mentir à operadora sem mudar o que o servidor faz — e a escrita na fila. Por isso a frase do ecrã é sobre a INTENÇÃO («vai por email») e nunca sobre o desfecho («enviada»).
- **O NIF não decide nada: o seletor do cliente é o único que manda** (decisão do dono, 2026-09-17, e substitui o que este plano dizia antes). Com a preferência ligada a fatura vai por email **haja ou não haja NIF**; o NIF vai escrito na fatura como sempre foi, e ela segue por email para o email da conta de quem mostrou o QR. A razão é do balcão, e é dele: quem mostra a app e quem pede a fatura são a mesma pessoa; num grupo só uma pessoa fica com os pontos e, quando querem faturas separadas, dividem a conta — e aí cada parte fica com o seu QR e o seu NIF. Medido antes de decidir: **10,4% das vendas levam NIF** (286 em 2755 nos últimos 30 dias) e só **1,6%** são partes de conta dividida — manter a regra antiga custava 1 em cada 10 faturas que podiam poupar papel. **Risco aceite pelo dono, explicitamente:** se num grupo uma pessoa mostrar a app e OUTRA pedir a fatura com o NIF dela, sem dividirem a conta, essa fatura vai para o email de quem mostrou a app — recupera-se a reimprimir no separador Faturação, que já o faz a um toque. **Para este plano isto quer dizer uma coisa só: o ecrã não lê o NIF de lado nenhum** — e com isso cai a razão de ir buscar o `cliente_nif` da venda gravada.
- **A gaveta da conta passa a ter TRÊS campos, sempre** — `{id, primeiro_nome, fatura_por_email}`, escolhidos um a um. Isso parte seis asserções de igualdade exacta que já existem, e a Task 1 actualiza-as no mesmo commit (Step 4): não se afrouxa nenhuma para `>=` nem se apaga comparação nenhuma — são os guardas que protegem a gaveta.
- **Não há lista nova no POS.** Só um filtro «por enviar» no separador que já existe.
- **Depende da Frente B.** As Tasks 2 e 5 acrescentam chamadas novas; as Tasks 1, 3 e 4 não acrescentam chamada nenhuma. **Ordem: ou a Frente B primeiro, ou as Tasks 1, 3 e 4 primeiro** (o ficheiro de teste nasce na Task 1 já com todos os imports no cabeçalho, por isso a Task 3 corre sem a Task 2).
  - Task 2 → o guarda é `test_caminhos_do_pos.py::test_todas_as_chamadas_do_pos_apontam_para_rotas_que_existem`, e a frase é «**Estas chamadas do POS** apontam para caminhos que o servidor não serve».
  - Task 5 → o guarda é `test_caminhos_do_pos.py::test_todas_as_chamadas_do_backoffice_apontam_para_rotas_que_existem` (`:200-214`), e a frase é «**Estas chamadas do backoffice** apontam para caminhos que o servidor não serve».
- **Testes:** `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest -q` → `0 failed`, `0 skipped` (a suite andava nos 3296 à data deste plano). Config única: `backend/pytest.ini`. Nenhum teste liga à rede nem à base de dados. **Sem `frontend/node_modules` os testes de ecrã SALTAM em silêncio** — ler sempre `passed` E `skipped`.
- **Nunca correr a suite enquanto outro trabalho muta a mesma árvore** (workflows paralelos dão falhas diferentes no mesmo commit).
- **Armadilhas dos ecrãs, já medidas:** afirmar sobre `textoVisivel()`, **nunca** sobre `textContent`; o duplo `Campo` deita fora props que não estejam na lista dele (o `Div` reencaminha `onClick` e `data-testid`, e mais nada); um campo controlado do React não muda com `el.value` (usar o `escrever` de `_UTEIS`); `_ECRAS_SUBSTITUIDOS` monta o `PosVenda` vazio e é preciso `SUBSTITUIDOS.delete` (o `_arranque` já o faz); o `p.url` guardado em `pedidos` traz o prefixo `undefined/api` (o `REACT_APP_BACKEND_URL` não existe em Node), por isso os caminhos afirmam-se com `endswith` e nunca por igualdade (`test_o_ecra_de_documentos_no_backoffice.py:118-139`).
- **PT-PT** em texto visível, comentários, docstrings e nomes de testes (em frase). Comentários explicam o PORQUÊ.
- **Commits** com `git add` de caminhos explícitos, mensagem em PT a terminar com `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

### Task 1: A preferência vem da leitura do QR e fica na gaveta da conta

**Files:**
- Modify: `frontend/src/lib/pos.js:234-241` (`guardarPontosDaConta`) e `:258-260` (o comentário do contrato de `lerQrDePontos`)
- Modify: `frontend/src/pages/pos/PosLerQr.js:128-130`
- Modify: `backend/tests/faturacao/test_os_pontos_da_conta_no_pos.py:17` (o `_ANA` partilhado pelas três comparações das linhas 35, 59 e 85)
- Modify: `backend/tests/faturacao/test_os_pontos_no_ecra_do_pos.py:140`, `:337`, `:449`
- Create: `backend/tests/faturacao/test_a_fatura_por_email_no_ecra_do_pos.py`

**Interfaces:**
- Consumes (Frente B): `POST /pos/pontos/ler` → `{ligacao_id, primeiro_nome, fatura_por_email}`.
- Produces: `guardarPontosDaConta(vendaId, ligacao|null)` e `lerPontosDaConta(vendaId) -> {id, primeiro_nome, fatura_por_email}|null` — os TRÊS campos, sempre, e só estes. `PosLerQr::onLigada({id, primeiro_nome, fatura_por_email})`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `backend/tests/faturacao/test_a_fatura_por_email_no_ecra_do_pos.py`:

```python
"""**A fatura por email no ecrã do POS** — montado e tocado, não lido.

O cliente que mostra o QR na caixa pode levar a fatura por email em vez do
talão. O ecrã do balcão diz qual dos dois vai acontecer, deixa trocar num
toque, e **nunca mostra o endereço** — um ecrã de caixa com o email de quem
está à frente é uma porta de enumeração, e o balcão não precisa dele para
nada (o servidor nem sequer o manda).

Os ecrãs do POS desenham-se todos sem servidor nenhum, e já foram defeitos a
produção exactamente assim. Por isso aqui monta-se o `PosLerQr` e o `PosVenda`
INTEIROS, com o servidor fabricado à frente do axios, carrega-se nos botões, e
o que se afirma é o que a operadora LÊ (`textoVisivel`) e o que o ecrã MANDA
(`pedidos[i].corpo`).

O `PosVenda` inteiro e não o `PosFinalizar` sozinho: entre o cartão e o
`POST /pos/venda/{id}/finalizar` há dois ficheiros, e o que se quer provar
também é o CORPO desse pedido.
"""
import json

import pytest

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _COMPONENTES
# São SEIS nomes, e estão todos AQUI EM CIMA de propósito. Dois deles — o
# `_UTEIS` e o `_CODIGO` — são usados já pela fixture desta task, aqui mesmo em
# baixo; os outros quatro (`_correr`, `_EMITIDA`, `_EMITIR`, `_no_finalizar`) só
# pelas partes de baixo do ficheiro, o cartão e o ecrã do documento emitido. Um
# import acrescentado a meio do ficheiro fazia a parte que o usasse rebentar na
# RECOLHA — `NameError` antes de correr teste nenhum — se alguém executasse as
# tarefas deste plano por outra ordem.
from .test_o_dividir_e_o_separar_no_ecra import _correr  # noqa: F401
from .test_os_pontos_no_ecra_do_pos import (  # noqa: F401
    _CODIGO, _EMITIDA, _EMITIR, _UTEIS, _no_finalizar,
)

# O endereço que o servidor NÃO manda — posto aqui de propósito na resposta
# fabricada. Se algum dia alguém o acrescentar do outro lado (ou passar a
# guardar a resposta inteira na gaveta), é este teste que grita.
_EMAIL_DO_CLIENTE = "ana.silva@exemplo.pt"


@pytest.fixture(scope="module")
def leitura(tmp_path_factory):
    """A janela «Ler QR do cliente» sozinha: o que ela entrega ao Finalizar, e
    o que a gaveta da conta faz com a resposta CRUA do servidor."""
    cenario = "\n".join([
        _COMPONENTES,
        _UTEIS,
        "const lib = carregar(path.join(RAIZ, 'lib', 'pos.js'));",
        "lib.guardarOperador('ot', { id: 'o1', nome: 'Ana' });",
        "const PosLerQr = carregar(path.join(POS, 'PosLerQr.js')).default;",
        "RESPOSTAS_POS['POST /pos/pontos/ler'] = () => ({ data: {",
        "  ligacao_id: 'lig-1', primeiro_nome: 'Ana', fatura_por_email: true,",
        "  email: %s } });" % json.dumps(_EMAIL_DO_CLIENTE),
        "(async () => {",
        "  const ligadas = [];",
        "  const alvo = document.getElementById('raiz');",
        "  const raiz = createRoot(alvo);",
        "  await act(async () => { raiz.render(React.createElement(PosLerQr, {",
        "    vendaId: 'v-1', onLigada: (l) => ligadas.push(l), onFechar: () => {},",
        "  })); });",
        "  await lerComOLeitor(alvo, %s);" % json.dumps(_CODIGO),
        "  lib.guardarPontosDaConta('v-1', ligadas[0]);",
        "  const saida = {",
        "    ligadas,",
        "    guardada: lib.lerPontosDaConta('v-1'),",
        "    visivel: textoVisivel(alvo),",
        "  };",
        # **A gaveta escrita com a FORMA CRUA do servidor**, e não com o objecto
        # que o PosLerQr já filtrou. É a única escrita que prova a filtragem da
        # GAVETA: alimentada com os três campos limpos, um `{ ...ligacao }` lá
        # dentro passava despercebido para sempre.
        "  lib.guardarPontosDaConta('v-2', { id: 'lig-2', primeiro_nome: 'Ana',",
        "    fatura_por_email: true, email: %s });" % json.dumps(_EMAIL_DO_CLIENTE),
        "  saida.guardadaCrua = lib.lerPontosDaConta('v-2');",
        "  saida.gaveta = sessionStorage.getItem('pos_pontos_da_conta');",
        "  await act(async () => { raiz.unmount(); });",
        "  process.stdout.write(JSON.stringify(saida));",
        "})().catch((e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });",
    ])
    return _montar_no_node(
        cenario, tmp_path_factory.mktemp("qr-email"), "montar-qr-email.js")


def test_a_preferencia_lida_no_QR_chega_ao_Finalizar_e_sobrevive_a_gaveta(leitura):
    """**Os três campos, e só estes.** O `fatura_por_email` serve para desenhar
    o cartão e mais nada: quem decide se o papel sai é o servidor, pelo
    `fat_pontos_qr` que ele próprio gravou ao ler o QR."""
    assert leitura["ligadas"] == [
        {"id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": True}]
    assert leitura["guardada"] == {
        "id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": True}


def test_o_ENDERECO_do_cliente_nao_entra_na_gaveta_nem_no_ecra(leitura):
    """A gaveta escolhe campo a campo de propósito, e prova-se com a resposta
    crua: um `{ ...ligacao }` a copiar o que o servidor mandou punha o email de
    cada cliente no `sessionStorage` do PC do balcão — e o `sessionStorage` do
    POS é lido por tudo o que corra naquela aba."""
    assert leitura["guardadaCrua"] == {
        "id": "lig-2", "primeiro_nome": "Ana", "fatura_por_email": True}
    assert _EMAIL_DO_CLIENTE not in leitura["gaveta"], leitura["gaveta"]
    assert _EMAIL_DO_CLIENTE not in leitura["visivel"], leitura["visivel"][:400]
```

- [ ] **Step 2: Correr e ver falhar**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_a_fatura_por_email_no_ecra_do_pos.py -q`

Expected: FAIL nos DOIS testes. O primeiro com `assert [{'id': 'lig-1', 'primeiro_nome': 'Ana'}] == [{'id': 'lig-1', 'primeiro_nome': 'Ana', 'fatura_por_email': True}]` (o `PosLerQr` deita fora o campo, e a gaveta também); o segundo com `assert {'id': 'lig-2', 'primeiro_nome': 'Ana'} == {'id': 'lig-2', 'primeiro_nome': 'Ana', 'fatura_por_email': True}`.

- [ ] **Step 3: Implementação mínima**

Em `frontend/src/lib/pos.js`, substituir `guardarPontosDaConta` (linhas 234-241):

```js
export const guardarPontosDaConta = (vendaId, ligacao) => {
  // Sem conta não se escreve nada: a gaveta é uma só (ver guardarNifDaConta).
  if (!vendaId) return;
  guardarNaSessao(CHAVE_PONTOS_DA_CONTA, JSON.stringify({
    vendaId,
    // **Campo a campo, e nunca `{ ...ligacao }`.** São estes três e mais
    // nenhum: o endereço de email do cliente não entra aqui, nem hoje (o
    // servidor não o manda) nem no dia em que alguém o acrescentar do outro
    // lado — o `sessionStorage` do POS é lido por tudo o que corra naquela aba.
    //
    // O `fatura_por_email` é a preferência DAQUELA leitura e serve SÓ para
    // desenhar o cartão. Quem decide se o papel sai é o servidor, pelo
    // `fat_pontos_qr` que ele gravou ao ler o QR: adulterar esta gaveta faz o
    // cartão mentir à operadora, não faz desaparecer o documento do cliente.
    //
    // **Está SEMPRE presente, mesmo a `false`.** Uma forma que mudasse com a
    // resposta do servidor punha o ecrã a ter de distinguir «não vai por
    // email» de «esta gaveta é de uma versão antiga» — e essa é a distinção
    // que ninguém faz bem às três da tarde.
    ligacao: ligacao ? {
      id: ligacao.id,
      primeiro_nome: ligacao.primeiro_nome,
      fatura_por_email: !!ligacao.fatura_por_email,
    } : null,
  }));
};
```

Ainda em `frontend/src/lib/pos.js`, o comentário do contrato (linhas 258-260) passa a:

```js
// `POST /pos/pontos/ler` → `{ ligacao_id, primeiro_nome, fatura_por_email }`.
// 404 é QR recusado e 503 é a app em baixo; as frases vêm no `detail`. A conta
// vai no pedido para o servidor confirmar que está aberta e é desta loja.
//
// O `fatura_por_email` é o sim/não da preferência daquele cliente — **e é só
// isso que vem**: o endereço nunca sai da app, nem mascarado.
```

Em `frontend/src/pages/pos/PosLerQr.js`, linhas 128-130:

```js
      const { ligacao_id: id, primeiro_nome, fatura_por_email } =
        await lerQrDePontos(vendaId, lido);
      APITO_LIDO();
      onLigada({ id, primeiro_nome, fatura_por_email: !!fatura_por_email });
```

- [ ] **Step 4: Actualizar os guardas que já existiam**

A gaveta e o `onLigada` passam a ter três campos sempre, e seis asserções de igualdade EXACTA comparam com dois. **Actualizam-se, não se afrouxam:** são elas que impedem a gaveta de crescer com campos que ninguém pediu.

Em `backend/tests/faturacao/test_os_pontos_da_conta_no_pos.py`, a linha 17 (usada nas comparações das linhas 35, 59 e 85):

```python
# Os TRÊS campos da gaveta. O `fatura_por_email` entrou a 2026-09-17 com a
# fatura por email e está sempre presente, mesmo a `False` — ver
# `lib/pos.js::guardarPontosDaConta`.
_ANA = {"id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False}
```

Em `backend/tests/faturacao/test_os_pontos_no_ecra_do_pos.py`, a linha 140:

```python
    assert janela["lido"]["ligadas"] == [
        {"id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False}]
```

a linha 337:

```python
    assert lido["guardada"] == {
        "id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False}
```

e a linha 449:

```python
    assert parte_seguinte["guardadaNaPessoa1"] == {
        "id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False}
```

**A linha 344 NÃO muda, e é essa a prova:**
`assert corpo["pontos_ligacao"] == {"id": "lig-1", "primeiro_nome": "Ana"}` — o corpo do EMITIR continua com dois campos (`PosFinalizar.js:1330` escolhe-os um a um). A gaveta cresceu; o pedido ao servidor não.

- [ ] **Step 5: Correr e ver passar**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_a_fatura_por_email_no_ecra_do_pos.py tests/faturacao/test_os_pontos_da_conta_no_pos.py tests/faturacao/test_os_pontos_no_ecra_do_pos.py -q`

Expected: PASS (0 failed, 0 skipped — se aparecer `skipped`, falta o `frontend/node_modules`).

- [ ] **Step 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH
git add frontend/src/lib/pos.js frontend/src/pages/pos/PosLerQr.js \
  backend/tests/faturacao/test_a_fatura_por_email_no_ecra_do_pos.py \
  backend/tests/faturacao/test_os_pontos_da_conta_no_pos.py \
  backend/tests/faturacao/test_os_pontos_no_ecra_do_pos.py
git commit -F - <<'EOF'
POS: a preferência de fatura por email viaja da leitura do QR para a gaveta

O /pos/pontos/ler passa a trazer fatura_por_email e o PosLerQr entrega-o ao
Finalizar; a gaveta do sessionStorage guarda os três campos ESCOLHIDOS um a
um — o endereço do cliente não entra lá. É só para desenhar o cartão: quem
decide o papel é o servidor, pelo fat_pontos_qr.

Os seis guardas que comparavam a gaveta com dois campos aprenderam o terceiro;
o corpo do EMITIR continua a levar dois, e esse guarda fica como estava.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 2: O cartão dos pontos diz para onde vai a fatura, e deixa trocar

**Files:**
- Modify: `frontend/src/lib/pos.js:262` (acrescentar a chamada da preferência a seguir ao `lerQrDePontos`)
- Modify: `frontend/src/pages/pos/PosFinalizar.js:15-20` (import do `lib/pos`), `:562-599` (o comentário do cartão e a função `CartaoPontos` — **a linha 560 é o separador `// --- Pontos L'Açaí ---` e fica onde está**), `:1039-1043` (estado), `:1412-1417` (uso do cartão)
- Test: `backend/tests/faturacao/test_a_fatura_por_email_no_ecra_do_pos.py`

**Interfaces:**
- Consumes: `lerPontosDaConta(vendaId) -> {id, primeiro_nome, fatura_por_email}|null` (Task 1); `POST /pos/pontos/preferencia` (Frente B).
- Produces: `guardarPreferenciaDeFaturaPorEmail(vendaId, ligacaoId, valor) -> Promise<{fatura_por_email: bool}>`; `CartaoPontos({ ligacao, onLer, onRemover, onPreferencia, aMudarPreferencia, desativado })`, com `data-testid="cartao-pontos"` no ramo COM ligação.

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar ao fim de `backend/tests/faturacao/test_a_fatura_por_email_no_ecra_do_pos.py` (os imports já estão no cabeçalho, da Task 1):

```python
# --- O cartão no Finalizar, pelo PosVenda inteiro ------------------------------


@pytest.fixture(scope="module")
def cartao(tmp_path_factory):
    """Lê o QR com a preferência LIGADA e carrega no botão três vezes, com o
    servidor a responder de três maneiras: a concordar, a recusar, e a DIVERGIR
    do que se pediu."""
    cenario = _no_finalizar("\n".join([
        "RESPOSTAS_POS['POST /pos/pontos/ler'] = () => ({ data: {",
        "  ligacao_id: 'lig-1', primeiro_nome: 'Ana', fatura_por_email: true,",
        "  email: %s } });" % json.dumps(_EMAIL_DO_CLIENTE),
        # A rota da preferência responde o que a variável disser no instante do
        # toque — é o mesmo botão nos três casos.
        "let respostaDaPreferencia = () => ({ data: { fatura_por_email: false } });",
        "RESPOSTAS_POS['POST /pos/pontos/preferencia'] = () => respostaDaPreferencia();",
    ]))
    return _correr("\n".join([
        cenario,
        # O cartão SOZINHO, e não o ecrã todo: a asserção do «@» tem de falar
        # do cartão. Um endereço de suporte no rodapé, ou um artigo com «@» no
        # nome, punha este teste vermelho por uma fuga que não existe.
        "const cartao = () => {",
        "  const el = alvo.querySelector('[data-testid=\"cartao-pontos\"]');",
        "  if (!el) throw new Error('sem cartão dos pontos no ecrã: '",
        "    + textoVisivel(alvo).slice(0, 400));",
        "  return textoVisivel(el);",
        "};",
        "await carregar_em('Ler QR do cliente');",
        "await lerComOLeitor(alvo, %s);" % json.dumps(_CODIGO),
        "const porEmail = cartao();",
        "const ecraTodo = textoVisivel(alvo);",
        # 1) O servidor concorda com o que se pediu.
        "await carregar_em('Voltar ao papel');",
        "const noPapel = cartao();",
        "const guardada = lib.lerPontosDaConta('v-1');",
        # 2) O servidor RECUSA (a ligação já foi usada).
        "respostaDaPreferencia = () => {",
        "  const e = new Error('Request failed with status code 409');",
        "  e.response = { status: 409, data: { detail: 'Esse QR já foi usado.' } };",
        "  throw e;",
        "};",
        "await carregar_em('Enviar por email');",
        "const depoisDaRecusa = cartao();",
        "const guardadaDepois = lib.lerPontosDaConta('v-1');",
        # 3) O servidor responde 200 mas DIVERGE do pedido: pediu-se `true` e
        #    ele diz que ficou `false` (a app já tinha desligado a preferência).
        "respostaDaPreferencia = () => ({ data: { fatura_por_email: false } });",
        "await carregar_em('Enviar por email');",
        "const depoisDaDivergencia = cartao();",
        "const guardadaDivergente = lib.lerPontosDaConta('v-1');",
        "const corposPreferencia = pedidos.filter(",
        "  (p) => p.url.endsWith('/pos/pontos/preferencia')).map((p) => p.corpo);",
        _EMITIR,
        "process.stdout.write(JSON.stringify({ porEmail, ecraTodo, noPapel, guardada,",
        "  corposPreferencia, depoisDaRecusa, guardadaDepois, depoisDaDivergencia,",
        "  guardadaDivergente, emitirVivo, corpos }));",
    ]), tmp_path_factory, "cartao-email")


def test_com_a_preferencia_LIGADA_o_cartao_diz_email_e_oferece_voltar_ao_papel(cartao):
    assert "Pontos para: Ana ✓ · Fatura por email ✉" in cartao["porEmail"], \
        cartao["porEmail"][:600]
    assert "Voltar ao papel" in cartao["porEmail"], cartao["porEmail"][:600]
    assert "Remover" in cartao["porEmail"], cartao["porEmail"][:600]


def test_o_endereco_NUNCA_aparece_no_ecra_do_balcao(cartao):
    """Só o sim/não. O ecrã da caixa está à vista da loja inteira, e um email
    por cima dele é uma porta de enumeração. O «@» afirma-se sobre o CARTÃO; o
    endereço, sobre o ecrã todo."""
    assert _EMAIL_DO_CLIENTE not in cartao["ecraTodo"], cartao["ecraTodo"][:600]
    assert "@" not in cartao["porEmail"], cartao["porEmail"][:600]


def test_voltar_ao_papel_pede_ao_SERVIDOR_e_so_depois_muda_o_ecra(cartao):
    """A preferência é do cliente e vive na app: quem a grava é o servidor."""
    assert cartao["corposPreferencia"][0] == {
        "venda_id": "v-1", "ligacao_id": "lig-1", "valor": False}
    assert "Pontos para: Ana ✓ · Fatura em papel" in cartao["noPapel"], \
        cartao["noPapel"][:600]
    assert "Enviar por email" in cartao["noPapel"], cartao["noPapel"][:600]
    assert cartao["guardada"] == {
        "id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False}


def test_uma_RECUSA_do_servidor_nao_mente_no_cartao(cartao):
    """O toque em «Enviar por email» com a app a recusar não pode deixar o
    cartão a prometer email: quem vier a seguir lê a promessa, não o toast."""
    assert cartao["corposPreferencia"][1] == {
        "venda_id": "v-1", "ligacao_id": "lig-1", "valor": True}
    assert "Fatura em papel" in cartao["depoisDaRecusa"], \
        cartao["depoisDaRecusa"][:600]
    assert "Fatura por email" not in cartao["depoisDaRecusa"], \
        cartao["depoisDaRecusa"][:600]
    assert cartao["guardadaDepois"] == {
        "id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False}


def test_o_cartao_escreve_o_que_o_SERVIDOR_devolveu_e_nao_o_que_se_pediu(cartao):
    """**O caso que mata a escrita optimista.** Aqui o pedido é `true` e a
    resposta é 200 com `false` — a app já tinha desligado a preferência pelo
    telemóvel, ou o valor de lá é outro. Um `mudarLigacao({ ...ligacao,
    fatura_por_email: valor })` deixava o cartão a prometer email com a app a
    dizer o contrário, e passava nos outros CINCO testes do cartão — contados
    um a um: o inicial, o do endereço, o «voltar ao papel», o do corpo do
    EMITIR, e a RECUSA, onde o `await` rebenta ANTES da escrita e por isso o
    cartão fica certo por acidente."""
    assert cartao["corposPreferencia"][2] == {
        "venda_id": "v-1", "ligacao_id": "lig-1", "valor": True}
    assert "Fatura em papel" in cartao["depoisDaDivergencia"], \
        cartao["depoisDaDivergencia"][:600]
    assert "Fatura por email" not in cartao["depoisDaDivergencia"], \
        cartao["depoisDaDivergencia"][:600]
    assert cartao["guardadaDivergente"] == {
        "id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False}


def test_a_preferencia_NAO_viaja_no_corpo_do_EMITIR(cartao):
    """**A decisão de não imprimir um documento fiscal não pode vir do corpo de
    um pedido do browser.** O servidor lê a preferência do `fat_pontos_qr` que
    é dele; o `pontos_ligacao` continua a ser os mesmos dois campos de sempre —
    um campo a mais aqui era um documento a desaparecer com um curl."""
    assert cartao["emitirVivo"] is True
    assert len(cartao["corpos"]) == 1, cartao["corpos"]
    assert cartao["corpos"][0]["pontos_ligacao"] == {
        "id": "lig-1", "primeiro_nome": "Ana"}
```

- [ ] **Step 2: Correr e ver falhar**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_a_fatura_por_email_no_ecra_do_pos.py -q`

Expected: FAIL nos seis testes novos (todos partilham a fixture), com `Failed: O JavaScript do ecrã não correu:` seguido de `Error: sem cartão dos pontos no ecrã: ...` — o `data-testid="cartao-pontos"` ainda não existe, e o cartão só tem o «Remover».

- [ ] **Step 3: Implementação mínima**

Em `frontend/src/lib/pos.js`, a seguir ao `lerQrDePontos` (depois da linha 262):

```js

// `POST /pos/pontos/preferencia` → `{ fatura_por_email }`. **O que conta é o
// que o servidor devolve, e não o que se pediu:** quem grava a preferência é a
// app (é dela o consentimento do cliente, e é ela que o audita), e uma recusa
// — a ligação já usada, o QR lido há muito — não pode ficar no cartão como se
// tivesse passado. A conta vai no pedido pela razão do `ler`: o servidor
// confirma que está aberta e é desta loja.
export const guardarPreferenciaDeFaturaPorEmail = async (vendaId, ligacaoId, valor) =>
  (await api.post('/pos/pontos/preferencia',
    { venda_id: vendaId, ligacao_id: ligacaoId, valor })).data;
```

Em `frontend/src/pages/pos/PosFinalizar.js`, acrescentar ao import do `@/lib/pos` (linhas 15-20) a entrada `guardarPreferenciaDeFaturaPorEmail,` a seguir a `lerPontosDaConta,`.

Substituir o comentário e a função `CartaoPontos` (linhas **562-599**, deixando o separador `// --- Pontos L'Açaí ---` da linha 560 intacto) por:

```js
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
//
// **E para onde vai a fatura** — email ou papel —, que é a única coisa que
// muda entre as duas frases. **O ENDEREÇO NUNCA APARECE**: só o sim/não. Um
// ecrã de caixa com o email de um cliente por cima é uma porta de enumeração,
// e o POS não precisa dele para nada (o servidor nem sequer o manda).
//
// **O que este cartão diz pode ser mentira, e isso está decidido.** A
// preferência vem da gaveta do `sessionStorage`; quem decide mesmo se o papel
// sai é o servidor, pelo `fat_pontos_qr` que ele gravou ao ler o QR. Uma
// gaveta adulterada faz o cartão mentir à operadora — não faz desaparecer o
// documento do cliente.
function CartaoPontos({ ligacao, onLer, onRemover, onPreferencia, aMudarPreferencia, desativado }) {
  const porEmail = !!(ligacao && ligacao.fatura_por_email);
  return (
    <Cartao titulo="Pontos L'Açaí" icone={Gift}>
      {ligacao ? (
        // O `data-testid` existe para os guardas poderem ler ESTE cartão e não
        // o ecrã inteiro: a prova de que o endereço não aparece tem de ser
        // sobre o sítio onde ele apareceria.
        <div
          className="flex flex-wrap items-center justify-between gap-3"
          data-testid="cartao-pontos"
        >
          <p className="font-heading font-bold text-2xl min-w-0 break-words">
            {`Pontos para: ${ligacao.primeiro_nome} ✓ · ${
              porEmail ? 'Fatura por email ✉' : 'Fatura em papel'}`}
          </p>
          <div className="flex flex-wrap gap-2">
            {/* Ao lado do «Remover» que já lá estava, e não por cima dele: são
                duas coisas diferentes — tirar o cliente da fatura, e escolher
                por onde ele a recebe. */}
            <Button
              type="button"
              variant="outline"
              className="h-12"
              onClick={() => onPreferencia(!porEmail)}
              disabled={desativado || aMudarPreferencia}
            >
              {aMudarPreferencia && <Loader2 className="h-5 w-5 mr-2 animate-spin" />}
              {porEmail ? 'Voltar ao papel' : 'Enviar por email'}
            </Button>
            <Button type="button" variant="outline" className="h-12" onClick={onRemover} disabled={desativado}>
              Remover
            </Button>
          </div>
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

A seguir ao `mudarLigacao` (linhas 1040-1043), acrescentar:

```js
  const [aMudarPreferencia, setAMudarPreferencia] = useState(false);
  // **Primeiro o servidor, e depois o que ELE devolveu.** A preferência é um
  // consentimento do cliente: quem a grava (e a audita, e avisa o telemóvel
  // dele) é a app, através do servidor. Escrever no ecrã antes da resposta era
  // deixar o cartão a prometer email com a app a ter recusado a mudança — e
  // quem vier a seguir lê a promessa, não a mensagem que já passou.
  //
  // E escreve-se `dados.fatura_por_email`, nunca o `valor` que se pediu: um
  // 200 pode trazer outro valor (o cliente desligou a preferência no telemóvel
  // entretanto), e nesse caso quem tem razão é a app.
  const mudarPreferencia = async (valor) => {
    if (!ligacao || aMudarPreferencia) return;
    setAMudarPreferencia(true);
    try {
      const dados = await guardarPreferenciaDeFaturaPorEmail(venda?.id, ligacao.id, valor);
      mudarLigacao({ ...ligacao, fatura_por_email: !!(dados && dados.fatura_por_email) });
    } catch (error) {
      toast.error(detalhesErroPos(
        error, 'Não foi possível mudar isto agora — a fatura sai em papel.').mensagem);
    } finally {
      setAMudarPreferencia(false);
    }
  };
```

E o uso do cartão (linhas 1412-1417):

```jsx
          <CartaoPontos
            ligacao={ligacao}
            onLer={() => setALerQr(true)}
            onRemover={() => mudarLigacao(null)}
            onPreferencia={mudarPreferencia}
            aMudarPreferencia={aMudarPreferencia}
            desativado={aEmitir || congelada}
          />
```

- [ ] **Step 4: Correr e ver passar**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_a_fatura_por_email_no_ecra_do_pos.py tests/faturacao/test_os_pontos_no_ecra_do_pos.py tests/faturacao/test_caminhos_do_pos.py -q`

Expected: PASS. **Se o `test_caminhos_do_pos.py` falhar** com «Estas chamadas do POS apontam para caminhos que o servidor não serve — POST /api/faturacao/pos/pontos/preferencia», é a Frente B que ainda não foi juntada: juntá-la antes de fechar esta task (o guarda está certo, a chamada é que ainda não tem rota).

- [ ] **Step 5: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH
git add frontend/src/lib/pos.js frontend/src/pages/pos/PosFinalizar.js \
  backend/tests/faturacao/test_a_fatura_por_email_no_ecra_do_pos.py
git commit -F - <<'EOF'
POS: o cartão dos pontos diz para onde vai a fatura e deixa trocar num toque

«Pontos para: Ana ✓ · Fatura por email ✉» com «Voltar ao papel», ou «· Fatura
em papel» com «Enviar por email». O endereço nunca aparece — só o sim/não. O
botão pede ao servidor e escreve o que ELE devolveu, mesmo quando a resposta
diverge do que se pediu; a preferência continua a não viajar no corpo do
EMITIR.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 3: Depois do EMITIR, o ecrã diz que a fatura vai por email

**Files:**
- Modify: `frontend/src/lib/pos.js:1404` (função nova a seguir ao `avisoDoDocumento`)
- Modify: `frontend/src/pages/pos/PosFinalizar.js:3-7` (ícone `Mail`), `:15-20` (import do `lib/pos`), `:823` (assinatura do `DocumentoEmitido`), `:949-959` (a frase do papel), `:1336-1342` (uso do `DocumentoEmitido`)
- Test: `backend/tests/faturacao/test_a_fatura_por_email_no_ecra_do_pos.py`

**Interfaces:**
- Consumes: `estadoDoModo`, `MODO_NORMAL` (já em `lib/pos.js:1302-1318`); `lerPontosDaConta` (Task 1).
- Produces: `aFaturaVaiPorEmail({ ligacao, documento }) -> boolean`; `DocumentoEmitido({ documento, troco, recuperado, onVoltar, rotuloVoltar, porEmail })`.
- **Não consome o NIF, e é de propósito:** o seletor do cliente é o único que manda (ver Global Constraints). O ecrã não lê `venda.cliente_nif` nem `nifTexto` para esta decisão.

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar ao fim de `backend/tests/faturacao/test_a_fatura_por_email_no_ecra_do_pos.py`:

```python
# --- Depois do EMITIR ---------------------------------------------------------
#
# Quatro montagens, porque são quatro regras diferentes e cada uma tem de poder
# falhar sozinha. TRÊS são as condições do servidor que este lado consegue
# aplicar — a preferência, o `modo` e o `vendus_document_id` —, e a quarta é a
# decisão do dono sobre o NIF, provada pelo avesso: a spec REVOGOU essa regra, e
# o teste existe para que repô-la fique vermelho. As respostas do `finalizar`
# são a do `_no_finalizar`, com o que é preciso trocado.

_FRASE_EMAIL = "Fatura vai por email — não é preciso esperar pelo papel."
_FRASE_PAPEL = "assim que o agente de impressão da loja existir"

_LIDO_COM_EMAIL = "\n".join([
    "RESPOSTAS_POS['POST /pos/pontos/ler'] = () => ({ data: {",
    "  ligacao_id: 'lig-1', primeiro_nome: 'Ana', fatura_por_email: true } });",
])


def _emitiu(extra, tmp_path_factory, nome):
    cenario = _no_finalizar("\n".join([_LIDO_COM_EMAIL, extra]))
    return _correr("\n".join([
        cenario,
        "await carregar_em('Ler QR do cliente');",
        "await lerComOLeitor(alvo, %s);" % json.dumps(_CODIGO),
        _EMITIR,
        "process.stdout.write(JSON.stringify({",
        "  emitido: textoVisivel(alvo), emitirVivo, corpos }));",
    ]), tmp_path_factory, nome)


@pytest.fixture(scope="module")
def emitida_por_email(tmp_path_factory):
    return _emitiu("", tmp_path_factory, "emitida-email")


@pytest.fixture(scope="module")
def emitida_com_nif(tmp_path_factory):
    """**Com NIF, e com a preferência ligada: vai por email à mesma.**

    As DUAS fontes do NIF na MESMA montagem, de propósito — a que a operadora
    tem escrita na caixa (a gaveta da conta, de onde o ecrã a lê ao montar:
    `lerNifDaConta`, `PosFinalizar.js:1034`) e a que ficou gravada na venda e
    volta na resposta do EMITIR (`cliente_nif`, `fiscal.py:2308`). Se alguém
    voltar a pôr o NIF a decidir — por uma delas ou pela outra —, é aqui que
    fica vermelho, e é por isso que não são duas montagens."""
    return _emitiu("\n".join([
        "lib.guardarNifDaConta('v-1', '517542510');",
        "RESPOSTAS_POS['POST /pos/venda/v-1/finalizar'] = () => ({ data: %s });"
        % json.dumps(dict(_EMITIDA, cliente_nif="517542510"), ensure_ascii=False),
    ]), tmp_path_factory, "emitida-com-nif")


@pytest.fixture(scope="module")
def emitida_em_testes(tmp_path_factory):
    """Modo `tests`: papel e nenhum email — o documento não vale nada e não há
    nada para mandar a ninguém."""
    em_testes = dict(_EMITIDA, documento=dict(_EMITIDA["documento"], modo="tests"))
    return _emitiu(
        "RESPOSTAS_POS['POST /pos/venda/v-1/finalizar'] = () => ({ data: %s });"
        % json.dumps(em_testes, ensure_ascii=False),
        tmp_path_factory, "emitida-testes")


@pytest.fixture(scope="module")
def emitida_sem_id_do_vendus(tmp_path_factory):
    """**Sem `vendus_document_id` o servidor manda PAPEL, e o ecrã tem de dizer
    o mesmo.**

    Não é um caso inventado: um 2xx do Vendus com ATCUD e sem `id` é aceite de
    propósito (`vendus/emissao.py:702` só recusa quando faltam os DOIS) e grava
    `vendus_document_id: None`. Nesse documento não há PDF para ir buscar — é o
    mesmo caso que responde 422 no botão «PDF da fatura»
    (`documentos.py:894`) —, por isso `enfileirar_fatura_email` devolve `False`
    (plano B) e o talão sai pela `enfileirar_venda_emitida`.

    O ecrã VÊ este campo: vem no `_resposta_documento` (`fiscal.py:1988-1998`) e
    o próprio `PosFinalizar.js:961` já o desenha. Prometer email aqui mandava a
    operadora dar o cliente por servido, e ele saía sem talão e sem email."""
    sem_id = dict(_EMITIDA,
                  documento=dict(_EMITIDA["documento"], vendus_document_id=None))
    return _emitiu(
        "RESPOSTAS_POS['POST /pos/venda/v-1/finalizar'] = () => ({ data: %s });"
        % json.dumps(sem_id, ensure_ascii=False),
        tmp_path_factory, "emitida-sem-id")


def test_com_a_preferencia_ligada_o_ecra_do_documento_diz_que_vai_por_email(emitida_por_email):
    assert _FRASE_EMAIL in emitida_por_email["emitido"], \
        emitida_por_email["emitido"][:800]
    assert _FRASE_PAPEL not in emitida_por_email["emitido"], \
        emitida_por_email["emitido"][:800]


def test_o_ecra_NAO_diz_enviada_no_instante_do_EMITIR(emitida_por_email):
    """No instante do EMITIR o envio ainda não aconteceu: o `tentar_ja` agenda
    e volta logo (`pontos_app.py:253-267`). «Enviada» é uma afirmação sobre uma
    coisa que pode ainda falhar treze vezes — e o ecrã não afirma o que não
    sabe."""
    ecra = emitida_por_email["emitido"]
    assert "enviada" not in ecra.lower(), ecra[:800]


def test_o_NIF_NAO_muda_a_frase_porque_quem_manda_e_o_seletor(emitida_com_nif):
    """**O contribuinte deixou de decidir seja o que for** (decisão do dono,
    2026-09-17): «depende da opção se quer ou não por email a fatura; o seletor
    é que manda». Com a preferência ligada a fatura vai por email haja ou não
    haja NIF — o NIF vai escrito nela como sempre foi —, e segue para o email
    da conta de quem mostrou o QR.

    Ao balcão quem mostra a app e quem pede a fatura são a mesma pessoa; num
    grupo só uma pessoa fica com os pontos e, quando querem faturas separadas,
    dividem a conta, e aí cada parte leva o seu QR e o seu NIF.

    **O risco está aceite e escrito:** se uma pessoa do grupo mostrar a app e
    OUTRA pedir a fatura com o NIF dela sem dividirem a conta, essa fatura vai
    para o email de quem mostrou a app — e recupera-se a reimprimir no
    separador Faturação, a um toque."""
    assert _FRASE_EMAIL in emitida_com_nif["emitido"], \
        emitida_com_nif["emitido"][:800]
    assert _FRASE_PAPEL not in emitida_com_nif["emitido"], \
        emitida_com_nif["emitido"][:800]


def test_em_modo_de_TESTES_o_ecra_continua_a_falar_de_PAPEL(emitida_em_testes):
    assert _FRASE_PAPEL in emitida_em_testes["emitido"], emitida_em_testes["emitido"][:800]
    assert "por email" not in emitida_em_testes["emitido"], emitida_em_testes["emitido"][:800]
    # E a faixa do modo continua lá: o documento de testes não vale nada.
    assert "SEM VALOR FISCAL" in emitida_em_testes["emitido"], \
        emitida_em_testes["emitido"][:800]


def test_um_documento_SEM_id_do_Vendus_fala_de_PAPEL(emitida_sem_id_do_vendus):
    """**A condição que faltava ao ecrã.** Com a preferência ligada e o modo
    `normal`, mas sem id do Vendus, o servidor põe o talão na fila — e um ecrã
    a dizer «não é preciso esperar pelo papel» deixava o cliente sem nada."""
    ecra = emitida_sem_id_do_vendus["emitido"]
    assert _FRASE_PAPEL in ecra, ecra[:800]
    assert "por email" not in ecra, ecra[:800]
```

- [ ] **Step 2: Correr e ver falhar**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_a_fatura_por_email_no_ecra_do_pos.py -q -k "documento or enviada or NIF or TESTES"`

(**O `-k` nomeia os cinco TESTES desta task, e não as fixtures nem palavras do nome do ficheiro.** São duas armadilhas, as duas medidas neste repositório: o `-k` casa com o nome do teste **e com o dos pais dele**, mas nunca com o nome de uma fixture. Em `test_os_pontos_no_ecra_do_pos.py`, `-k guardado` (uma fixture) dá «no tests collected (19 deselected)» e `-k no_ecra_do_pos` (o nome do MÓDULO) colhe os 19. Como este ficheiro se chama `test_a_fatura_por_email...`, um `-k` com «fatura», «por_email» ou «ecra» apanhava o ficheiro inteiro; e um `-k` que não apanha nada parece um Step 2 a correr bem. O quinto teste, `test_um_documento_SEM_id_do_Vendus_fala_de_PAPEL`, entra pela palavra «documento» — contado nome a nome: essa palavra não aparece em nenhum dos oito testes das Tasks 1 e 2, nem no nome do módulo.)

Expected: FAIL **em DOIS** — `test_com_a_preferencia_ligada_o_ecra_do_documento_diz_que_vai_por_email` e `test_o_NIF_NAO_muda_a_frase_porque_quem_manda_e_o_seletor`, os dois com `assert 'Fatura vai por email — não é preciso esperar pelo papel.' in '...O talão passa a sair sozinho assim que o agente de impressão da loja existir...'` (o ecrã do documento emitido só conhece a frase do papel, e não a diz a ninguém).

**Os outros TRÊS passam já, e é suposto:** o do modo e o do id do Vendus são os guardas contra a implementação ingénua (`porEmail = !!(ligacao && ligacao.fatura_por_email)`, sem mais nada) e o do «enviada» é o guarda contra a frase que afirma o desfecho. Antes da implementação o ecrã fala sempre de papel, por isso os três passam por não haver ainda frase nenhuma de email — a prova deles é por mutação, no Step 4.

**O do NIF conta duas vezes**, e é o único assim: falha agora porque o ecrã ainda não tem frase de email nenhuma, passa com a implementação deste Step 3 — e volta a falhar no dia em que alguém puser o NIF a decidir outra vez (Step 4, mutação 2). É o guarda da decisão do dono, e é por isso que o caso do NIF não desapareceu do ficheiro: inverteu-se.

- [ ] **Step 3: Implementação mínima**

Em `frontend/src/lib/pos.js`, a seguir ao `avisoDoDocumento` (depois da linha 1404):

```js

// **A fatura desta venda vai por email?** — a pergunta do ecrã do documento
// emitido, e só dele.
//
// São TRÊS das CINCO condições que o servidor usa para saltar o papel
// (`backend/faturacao/pontos_app.py::enfileirar_fatura_email`, ao lado do
// `enfileirar_credito` — o `fiscal.py` só a chama). As duas que faltam não
// chegam a este lado: a linha do `fat_pontos_qr` em si (aqui há só a cópia da
// preferência que ficou na gaveta) e a escrita na fila. Por isso a frase do
// ecrã é sobre a INTENÇÃO («vai por email») e nunca sobre o desfecho
// («enviada») — quem decide é o servidor, e no instante do EMITIR o envio
// ainda nem começou.
//
// - sem ligação, ou com a preferência desligada, sai papel como sempre;
// - **sem `vendus_document_id` sai papel**, e é uma condição do ecrã e não só
//   do servidor: um 2xx do Vendus com ATCUD e sem `id` é aceite de propósito e
//   grava `vendus_document_id: None`, e sem o id não há PDF para mandar a
//   ninguém (é o 422 do botão «PDF da fatura», `documentos.py:894`). O
//   servidor põe o talão na fila nesse caso; um ecrã a prometer email deixava
//   o cliente sem talão E sem email. Este lado VÊ o campo — vem no
//   `_resposta_documento` e já está desenhado no ecrã;
// - **o NIF não decide nada, e isso está decidido** (o dono, 2026-09-17): o
//   seletor do cliente é o único que manda. Com a preferência ligada a fatura
//   vai por email haja ou não haja NIF — o NIF vai escrito nela como sempre
//   foi — e segue para o email da conta de quem mostrou o QR. Quem mostra a
//   app e quem pede a fatura são a mesma pessoa; um grupo que queira faturas
//   separadas divide a conta, e aí cada parte leva o seu QR e o seu NIF. Por
//   isso esta função **não recebe NIF nenhum**: um parâmetro que ninguém lê é
//   um convite a voltar a lê-lo;
// - um documento que não é `normal` (o modo `tests`) sai em papel e não vai a
//   lado nenhum: não vale nada e não há o que mandar.
//
// Vive aqui e não dentro do JSX pela regra do módulo: uma condição escrita no
// meio de um `<span>` não se corre em teste nenhum.
export const aFaturaVaiPorEmail = ({ ligacao, documento }) => (
  !!(ligacao && ligacao.fatura_por_email)
  && !!(documento && documento.vendus_document_id)
  && estadoDoModo(documento && documento.modo) === MODO_NORMAL
);
```

Em `frontend/src/pages/pos/PosFinalizar.js`:

1. no import dos ícones (linhas 3-7), acrescentar `Mail,` à lista;
2. no import do `@/lib/pos` (linhas 15-20), acrescentar `aFaturaVaiPorEmail,`;
3. a assinatura do `DocumentoEmitido` (linha 823) passa a:

```js
function DocumentoEmitido({ documento, troco, recuperado, onVoltar, rotuloVoltar, porEmail }) {
```

4. a secção do talão (linhas 949-959) passa a:

```jsx
          {/* Para onde vai o documento do cliente. Duas frases, e a diferença
              entre elas é se alguém tem de esperar ali de pé.

              **Não diz «enviada»**: no instante do EMITIR o envio ainda não
              aconteceu — o `tentar_ja` agenda em segundo plano e volta logo
              (`pontos_app.py`). O que se promete é a INTENÇÃO, que é o que
              este lado sabe; se falhar, aparece no alarme da loja e no
              relatório da noite, não aqui.

              O talão sai sozinho quando o agente de impressão existir (Plano
              3). Enquanto não existir, isto é uma frase e não um botão: um
              botão "Imprimir" que não imprime nada fazia a operadora carregar
              três vezes e dar o cliente por servido sem talão nenhum. */}
          <section className="rounded-2xl border bg-card p-4 text-sm text-muted-foreground flex items-start gap-2">
            {porEmail
              ? <Mail className="h-4 w-4 shrink-0 mt-0.5" />
              : <Printer className="h-4 w-4 shrink-0 mt-0.5" />}
            <span>
              {porEmail
                ? 'Fatura vai por email — não é preciso esperar pelo papel.'
                : 'O talão passa a sair sozinho assim que o agente de impressão da loja '
                  + 'existir — ainda não existe. Por agora, o documento fica no Vendus e '
                  + 'pode ser reimpresso a partir de lá.'}
            </span>
          </section>
```

5. o uso do `DocumentoEmitido` (linhas 1336-1342) passa a:

```jsx
      <DocumentoEmitido
        documento={documento}
        troco={trocoEntregue}
        recuperado={documentoRecuperado}
        onVoltar={onVoltar}
        rotuloVoltar={parte ? 'Voltar às partes' : null}
        // **O NIF não entra aqui, e é de propósito** (decisão do dono,
        // 2026-09-17): o seletor do cliente é o único que manda. Com a
        // preferência ligada a fatura vai por email com NIF e sem NIF — o NIF
        // vai escrito nela —, para o email da conta de quem mostrou o QR. Nem
        // `venda?.cliente_nif`, nem `nifTexto`: se algum deles voltar a esta
        // chamada, o `test_o_NIF_NAO_muda_a_frase...` fica vermelho.
        porEmail={aFaturaVaiPorEmail({ ligacao, documento })}
      />
```

- [ ] **Step 4: Correr e ver passar**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_a_fatura_por_email_no_ecra_do_pos.py tests/faturacao/test_a_faixa_do_modo_no_ecra.py tests/faturacao/test_o_nif_que_nao_existe_no_pos.py -q`

Expected: PASS

E os guardas provam-se por mutação, à mão, antes do commit (desfazer as três mutações a seguir):

1. tirar a linha do `estadoDoModo` do `aFaturaVaiPorEmail` → `test_em_modo_de_TESTES...` tem de ficar VERMELHO;
2. **repor o NIF a decidir**, que é a regra que saiu: no `PosFinalizar.js`, trocar a chamada por `porEmail={aFaturaVaiPorEmail({ ligacao, documento }) && !venda?.cliente_nif && !nifTexto}` → `test_o_NIF_NAO_muda_a_frase...` tem de ficar VERMELHO. É esta a mutação que prova a decisão do dono: sem ela, o caso do NIF passava a ser um teste que nada consegue partir.
3. tirar a linha do `vendus_document_id` do `aFaturaVaiPorEmail` → `test_um_documento_SEM_id_do_Vendus_fala_de_PAPEL` tem de ficar VERMELHO, e mais nenhum: as outras três montagens trazem o `vendus_document_id: 1` do `_EMITIDA`.

- [ ] **Step 5: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH
git add frontend/src/lib/pos.js frontend/src/pages/pos/PosFinalizar.js \
  backend/tests/faturacao/test_a_fatura_por_email_no_ecra_do_pos.py
git commit -F - <<'EOF'
POS: depois do EMITIR o ecrã diz que a fatura vai por email

«Fatura vai por email — não é preciso esperar pelo papel.», e nunca
«enviada»: no instante do EMITIR o envio ainda não aconteceu. A decisão é do
aFaturaVaiPorEmail em lib/pos.js — preferência ligada, documento em modo
normal e com id do Vendus: as TRÊS das cinco condições do servidor que chegam
ao browser. Sem id do Vendus não há PDF para mandar e o servidor põe o talão
na fila, por isso o ecrã fala de papel.

O NIF não decide nada: o seletor do cliente é o único que manda. Com a
preferência ligada a fatura vai por email haja ou não haja NIF, com o NIF
escrito nela, para o email da conta de quem mostrou o QR. O ecrã deixou de
ler o NIF, e o teste que dizia o contrário está invertido a prová-lo.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 4: O separador Faturação do POS ganha o filtro «por enviar»

**Files:**
- Modify: `frontend/src/pages/pos/PosFaturacao.js:3-6` (ícone `Mail`), `:383` (estado), `:532` (a lista filtrada), `:612-620` (a barra da pesquisa), `:635-640` (a lista vazia)
- Create: `backend/tests/faturacao/test_o_filtro_por_enviar_no_separador_de_faturacao.py`

**Interfaces:**
- Consumes (Frente B): cada documento de `GET /pos/documentos` traz `fatura_email_por_enviar: bool` — o mesmo sinal, já com janela, que o `estado_da_impressao` conta para o alarme da loja.
- Produces: nada novo em `lib/pos.js`. **Não há decisão nenhuma neste lado** — é por isso que o campo vem decidido do servidor: o botão e o alarme não podem contar coisas diferentes.

- [ ] **Step 1: Escrever o teste que falha**

Criar `backend/tests/faturacao/test_o_filtro_por_enviar_no_separador_de_faturacao.py`:

```python
"""O filtro **«por enviar»** do separador Faturação — executado, não lido.

**Não há lista nova.** O separador já lista os documentos da loja e já tem um
«Imprimir» em cada um: quem ficou sem email e precisa de papel tem-no a um
toque. O que faltava era a PERGUNTA — quais é que estão por enviar —, e isso é
um filtro sobre a lista que já existe.

**E a pergunta responde-se no SERVIDOR.** O documento traz
`fatura_email_por_enviar`, que é o mesmo sinal que o alarme da loja conta
(`impressao.py::estado_da_impressao`), janela incluída. Decidido aqui, o botão
acendia no minuto normal entre o EMITIR e o cron — em TODAS as faturas por
email — com o alarme calado ao lado, e um contador que acende no caso normal
ensina-se a ignorar. Pior ainda ao contrário: um `pendente` encalhado acendia o
alarme e não aparecia neste filtro, e a operadora não tinha onde dar o papel.

A técnica é a do `test_o_separador_de_faturacao_no_ecra.py`, e o molde da
biblioteca de UI e dos documentos vem de lá inteiro (uma segunda cópia
divergia da primeira no dia em que uma fosse corrigida). O que se afirma é o
que a operadora LÊ.
"""
import json

import pytest

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_o_separador_de_faturacao_no_ecra import _COMPONENTES, _documento

# Cinco documentos da mesma loja, e os cinco casos que existem ao balcão.
# Os dois primeiros são os que interessam: o cliente está neste momento sem
# documento nenhum, porque o talão não saiu.
_ENCALHADA = _documento(id="doc-1", numero="FS 05P2026/1824",
                        fatura_email_por_enviar=True)
_FALHADA = _documento(id="doc-2", numero="FS 05P2026/1825",
                      fatura_email_por_enviar=True)
_ENVIADA = _documento(id="doc-3", numero="FS 05P2026/1826",
                      fatura_email_por_enviar=False)
# Acabou de sair e vai a caminho: o servidor ainda não a conta, e o ecrã também
# não. O minuto normal entre o EMITIR e o cron não é um alarme.
_A_CAMINHO = _documento(id="doc-4", numero="FS 05P2026/1827",
                        fatura_email_por_enviar=False)
# A esmagadora maioria: o cliente não mostrou a app, e o talão saiu como sempre.
_EM_PAPEL = _documento(id="doc-5", numero="FS 05P2026/1828",
                       fatura_email_por_enviar=False)


def _cenario(documentos):
    return "\n".join([
        _COMPONENTES,
        "const PosFaturacao = carregar(path.join(POS, 'PosFaturacao.js')).default;",
        "RESPOSTAS_POS['/pos/documentos'] = () => ({ data: { documentos: %s,"
        " limite: 200, ha_mais: false } });" % json.dumps(documentos, ensure_ascii=False),
        "RESPOSTAS_POS['/pos/venda/aberta'] = () => ({ data: null });",
        "RESPOSTAS_POS['/pos/impressao/estado'] = () => ({ data:"
        " { ha_programa: true, por_sair: 0, falhados: 0 } });",
        "(async () => {",
        "  const alvo = document.getElementById('raiz');",
        "  const raiz = createRoot(alvo);",
        "  await act(async () => { raiz.render(React.createElement(",
        "    PosFaturacao, { caixa: { id: 'c1', nome: 'Balcão' }, onContaCopiada: () => {} }));",
        "  });",
        "  await act(async () => {});",
        "  const carregar_em = async (texto) => {",
        "    const b = [...alvo.querySelectorAll('button')].find(",
        "      (x) => (x.textContent || '').includes(texto) && !x.disabled);",
        "    if (!b) throw new Error('sem botão vivo com o texto ' + texto + ' — no ecrã: '",
        "      + textoVisivel(alvo).slice(0, 500));",
        "    await act(async () => { b.click(); });",
        "    await act(async () => {});",
        "  };",
        "  await carregar_em('Documentos');",
        "  await carregar_em('Faturação');",
        "  const todas = textoVisivel(alvo);",
        "  await carregar_em('Por enviar');",
        "  const filtrada = textoVisivel(alvo);",
        "  await carregar_em('Por enviar');",
        "  const outra_vez = textoVisivel(alvo);",
        "  process.stdout.write(JSON.stringify({ todas, filtrada, outra_vez }));",
        "})().catch((e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });",
    ])


@pytest.fixture(scope="module")
def ecra(tmp_path_factory):
    return _montar_no_node(
        _cenario([_ENCALHADA, _FALHADA, _ENVIADA, _A_CAMINHO, _EM_PAPEL]),
        tmp_path_factory.mktemp("por-enviar"), "por-enviar.js")


@pytest.fixture(scope="module")
def ecra_sem_nenhuma(tmp_path_factory):
    return _montar_no_node(
        _cenario([_ENVIADA, _A_CAMINHO, _EM_PAPEL]),
        tmp_path_factory.mktemp("por-enviar-zero"), "por-enviar-zero.js")


def test_a_lista_abre_com_TUDO_e_o_botao_diz_quantas_estao_por_enviar(ecra):
    """O número no botão é a razão de ele existir: sem ele, a operadora tinha
    de o carregar para saber se havia alguma."""
    for numero in ("FS 05P2026/1824", "FS 05P2026/1825", "FS 05P2026/1826",
                   "FS 05P2026/1827", "FS 05P2026/1828"):
        assert numero in ecra["todas"], ecra["todas"][:600]
    assert "Por enviar (2)" in ecra["todas"], ecra["todas"][:600]


def test_o_filtro_deixa_so_as_que_o_SERVIDOR_marcou_como_por_enviar(ecra):
    """**E nenhuma delas tem papel a compensá-la**, porque o talão não saiu: o
    cliente daquela fatura está neste momento sem documento nenhum. Uma fatura
    já enviada, uma que acabou de entrar na fila, ou uma que nunca foi por
    email, não têm nada a fazer nesta lista."""
    assert "FS 05P2026/1824" in ecra["filtrada"], ecra["filtrada"][:600]
    assert "FS 05P2026/1825" in ecra["filtrada"], ecra["filtrada"][:600]
    assert "FS 05P2026/1826" not in ecra["filtrada"], ecra["filtrada"][:600]
    assert "FS 05P2026/1827" not in ecra["filtrada"], ecra["filtrada"][:600]
    assert "FS 05P2026/1828" not in ecra["filtrada"], ecra["filtrada"][:600]


def test_desligar_o_filtro_devolve_a_lista_inteira(ecra):
    """Um filtro que não se desliga é uma lista nova com outro nome."""
    assert "FS 05P2026/1828" in ecra["outra_vez"], ecra["outra_vez"][:600]


def test_sem_nenhuma_por_enviar_o_ecra_DIZ_isso_e_nao_fala_de_pesquisa(ecra_sem_nenhuma):
    """«Nenhuma fatura destas bate com o que escreveu» a quem não escreveu nada
    é uma resposta a uma pergunta que ninguém fez — e manda-a procurar um erro
    de escrita que não existe."""
    assert "está à espera de ir por email" in ecra_sem_nenhuma["filtrada"], \
        ecra_sem_nenhuma["filtrada"][:600]
    assert "bate com o que escreveu" not in ecra_sem_nenhuma["filtrada"], \
        ecra_sem_nenhuma["filtrada"][:600]
```

- [ ] **Step 2: Correr e ver falhar**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_o_filtro_por_enviar_no_separador_de_faturacao.py -q`

Expected: FAIL nos quatro testes com `Failed: O JavaScript do ecrã não correu:` e `Error: sem botão vivo com o texto Por enviar — no ecrã: ...` (o separador ainda só tem a pesquisa).

- [ ] **Step 3: Implementação mínima**

Em `frontend/src/pages/pos/PosFaturacao.js`:

1. no import dos ícones (linhas 3-6), acrescentar `Mail,`;
2. a seguir ao `const [pesquisa, setPesquisa] = useState('');` (linha 383):

```js
  // **Só as que estão por enviar por email.** Um filtro, e não uma lista nova:
  // a lista dos documentos da loja já existe e já tem o «Imprimir» em cada um.
  const [soPorEnviar, setSoPorEnviar] = useState(false);
```

3. a linha 532 passa a:

```js
  // **Quem decide se uma fatura está «por enviar» é o servidor**, e chega aqui
  // já decidido em `fatura_email_por_enviar`: é o mesmo sinal — janela
  // incluída — que o alarme da loja conta (`impressao.py::estado_da_impressao`).
  // Decidido neste lado, o número do botão e o do alarme divergiam, e o dia em
  // que o alarme dissesse a verdade era o dia em que a fatura não estava aqui.
  const documentos = (lista?.documentos || [])
    .filter((d) => casaComAPesquisaPos(d, pesquisa))
    .filter((d) => !soPorEnviar || d.fatura_email_por_enviar);
  // Contado sobre a lista INTEIRA e não sobre a filtrada: é o número que diz
  // se vale a pena carregar no botão, e um número que mudasse com a pesquisa
  // respondia a outra pergunta.
  const porEnviar = (lista?.documentos || [])
    .filter((d) => d.fatura_email_por_enviar).length;
```

4. a barra da pesquisa (linhas 612-620) passa a ficar dentro de uma linha com o botão:

```jsx
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative flex-1 min-w-[12rem]">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    value={pesquisa}
                    onChange={(e) => setPesquisa(e.target.value)}
                    placeholder="Número, valor, artigo ou pagamento"
                    className="pl-9 h-11"
                  />
                </div>
                {/* O número à vista no próprio botão: sem ele, a operadora
                    tinha de o carregar para saber se havia alguma coisa por
                    enviar — e o normal é não haver. */}
                <Button
                  type="button"
                  variant={soPorEnviar ? 'default' : 'outline'}
                  className="h-11"
                  aria-pressed={soPorEnviar}
                  onClick={() => setSoPorEnviar((v) => !v)}
                >
                  <Mail className="h-4 w-4 mr-1" />
                  Por enviar{porEnviar > 0 ? ` (${porEnviar})` : ''}
                </Button>
              </div>
```

5. a lista vazia (linhas 635-640) passa a:

```jsx
                    {documentos.length === 0 ? (
                      <p className="px-4 py-6 text-sm text-muted-foreground text-center">
                        {(lista.documentos || []).length === 0
                          ? 'Ainda não há nenhuma fatura emitida nesta loja.'
                          : soPorEnviar
                            // Dizer «nenhuma bate com o que escreveu» a quem não
                            // escreveu nada manda-a procurar um erro de escrita
                            // que não existe.
                            ? 'Nenhuma fatura desta loja está à espera de ir por email.'
                            : 'Nenhuma fatura destas bate com o que escreveu.'}
                      </p>
                    ) : documentos.map((d) => (
```

- [ ] **Step 4: Correr e ver passar**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_o_filtro_por_enviar_no_separador_de_faturacao.py tests/faturacao/test_o_separador_de_faturacao_no_ecra.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH
git add frontend/src/pages/pos/PosFaturacao.js \
  backend/tests/faturacao/test_o_filtro_por_enviar_no_separador_de_faturacao.py
git commit -F - <<'EOF'
POS: o separador Faturação ganha o filtro «por enviar»

Um filtro sobre a lista que já existe, e não uma lista nova: quem ficou sem
email aparece aqui com o «Imprimir» ao lado. Quem decide quais são é o
servidor, no fatura_email_por_enviar — o MESMO sinal, com a mesma janela, que
o alarme da loja conta; o botão e o alarme não podem contar coisas diferentes.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 5: O backoffice mostra o estado do envio e reenvia

**Files:**
- Modify: `frontend/src/lib/faturacao.js:273-274` (chamada nova a seguir ao `reimprimirDocumento`)
- Modify: `frontend/src/pages/admin/faturacao/FatDocumentos.js:2-5` (import do `lib/faturacao`), `:19-21` (ícone `Mail`), `:110` (função nova a seguir ao `textoDosPontosApp`), `:123` (estado), `:200` (handler novo a seguir ao `abrirPdf`), `:515` (bloco novo a seguir ao dos pontos), `:575` (botão novo a seguir ao «PDF da fatura»)
- Create: `backend/tests/faturacao/test_o_reenvio_por_email_no_backoffice.py`

**Interfaces:**
- Consumes (Frente B): `GET /faturacao/documentos/{id}` → `fatura_email: null | {estado, tentativas, ultimo_erro, motivo, atualizado_em}`; `POST /faturacao/documentos/{id}/reenviar-email`.
- Produces: `reenviarEmailDocumento(id) -> Promise<AxiosResponse>`; `textoDoEnvioPorEmail(e) -> string`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `backend/tests/faturacao/test_o_reenvio_por_email_no_backoffice.py`:

```python
"""**O envio por email no detalhe do documento** — montado e carregado, não lido.

O gestor é quem atende o «não me chegou». A linha `fatura_email:<id>` da fila
existe do lado do servidor desde a emissão, e sem este ecrã não aparecia em
lado nenhum: nem o estado, nem a razão, nem uma forma de repetir.

O botão **reenvia qualquer documento**, e não só os falhados — o caso
frequente é a linha estar em `feito` e o cliente não ter o email na caixa.
Quem repõe os cinco campos da linha é o servidor; daqui vai o id.

A técnica é a de `test_o_ecra_de_documentos_no_backoffice.py`: jsdom, o React
a sério, o axios de GESTÃO fabricado à frente, e o que se afirma é o que o
gestor LÊ (`textoVisivel`) e o que o ecrã MANDA. Os caminhos comparam-se com
`endswith`: o `url` guardado traz o prefixo do `REACT_APP_BACKEND_URL`, que em
Node não existe e vem literalmente como `undefined/api`.
"""
import json

import pytest

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_as_fotos_no_ecra import _COMPONENTES
from .test_o_ecra_de_documentos_no_backoffice import _FATURA, _LISTA, _LOJAS

_FALHADA = dict(_FATURA, fatura_email={
    "estado": "falhado", "tentativas": 13, "motivo": None,
    "ultimo_erro": "HTTP 500: {\"detail\":\"envio falhou\"}",
    "atualizado_em": "2026-09-17T18:05:00+00:00"})
# Como a linha fica DEPOIS de o botão a repor: pendente, zero tentativas, sem
# erro nenhum — é o que prova que o ecrã releu o documento em vez de desenhar
# o que tinha.
_REPOSTA = dict(_FATURA, fatura_email={
    "estado": "pendente", "tentativas": 0, "motivo": None, "ultimo_erro": None,
    "atualizado_em": "2026-09-17T18:30:00+00:00"})
_RECUSADA = dict(_FATURA, fatura_email={
    "estado": "recusado", "tentativas": 1, "motivo": "ligacao_ja_usada",
    "ultimo_erro": None, "atualizado_em": "2026-09-17T18:05:00+00:00"})
_SEM_EMAIL = dict(_FATURA, fatura_email=None)


def _cenario(detalhe_inicial):
    return "\n".join([
        _COMPONENTES,
        "const ADMIN = path.join(RAIZ, 'pages', 'admin', 'faturacao');",
        "const FatDocumentos = carregar(path.join(ADMIN, 'FatDocumentos.js')).default;",
        "RESPOSTAS_GESTAO['/faturacao/lojas'] = () => ({ data: %s });"
        % json.dumps(_LOJAS, ensure_ascii=False),
        "RESPOSTAS_GESTAO['/faturacao/documentos'] = () => ({ data: %s });"
        % json.dumps(_LISTA, ensure_ascii=False),
        "let detalhe = %s;" % json.dumps(detalhe_inicial, ensure_ascii=False),
        "const REPOSTA = %s;" % json.dumps(_REPOSTA, ensure_ascii=False),
        "RESPOSTAS_GESTAO['/faturacao/documentos/d1'] = () => ({ data: detalhe });",
        # O servidor repõe a linha e responde; a leitura seguinte já traz a
        # linha reposta. É assim que se vê se o ecrã releu ou se mentiu.
        "RESPOSTAS_GESTAO['POST /faturacao/documentos/d1/reenviar-email'] = () => {",
        "  detalhe = REPOSTA;",
        "  return { data: { reenviada: true } };",
        "};",
        "(async () => {",
        "  const alvo = document.getElementById('raiz');",
        "  const raiz = createRoot(alvo);",
        "  await act(async () => { raiz.render(React.createElement(FatDocumentos)); });",
        "  await act(async () => {});",
        "  await act(async () => {});",
        "  const linha = alvo.querySelector('[data-testid=\"documento-d1\"]');",
        "  if (!linha) throw new Error('sem linha da fatura: '",
        "    + textoVisivel(alvo).slice(0, 400));",
        "  await act(async () => { linha.click(); });",
        "  await act(async () => {});",
        "  const bloco = () => alvo.querySelector('[data-testid=\"documento-fatura-email\"]');",
        "  const botao = () => alvo.querySelector('[data-testid=\"documento-reenviar-email\"]');",
        "  const saida = {",
        "    aberto: bloco() ? textoVisivel(bloco()) : null,",
        "    tem_botao: !!botao(),",
        "    reimprimir: !!alvo.querySelector('[data-testid=\"documento-reimprimir\"]'),",
        "    pdf: !!alvo.querySelector('[data-testid=\"documento-pdf\"]'),",
        # Sempre presente, para a falha de antes da implementação ser uma
        # asserção legível e não um KeyError vindo do Python.
        "    depois: null,",
        "  };",
        "  if (botao()) {",
        "    await act(async () => { botao().click(); });",
        "    await act(async () => {});",
        "    saida.depois = bloco() ? textoVisivel(bloco()) : null;",
        "  }",
        "  saida.pedidos = pedidos.map((p) => p.metodo.toUpperCase() + ' ' + p.url);",
        "  process.stdout.write(JSON.stringify(saida));",
        "})().catch((e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });",
    ])


def _quantos(pedidos, sufixo):
    return sum(1 for p in pedidos if p.endswith(sufixo))


@pytest.fixture(scope="module")
def falhada(tmp_path_factory):
    return _montar_no_node(
        _cenario(_FALHADA), tmp_path_factory.mktemp("reenvio"), "reenvio.js")


@pytest.fixture(scope="module")
def recusada(tmp_path_factory):
    return _montar_no_node(
        _cenario(_RECUSADA), tmp_path_factory.mktemp("reenvio-recusada"),
        "reenvio-recusada.js")


@pytest.fixture(scope="module")
def sem_email(tmp_path_factory):
    return _montar_no_node(
        _cenario(_SEM_EMAIL), tmp_path_factory.mktemp("reenvio-sem"), "reenvio-sem.js")


def test_o_detalhe_diz_que_o_envio_FALHOU_e_o_ultimo_erro(falhada):
    """«Falhou ao fim de 24 h» sem o erro é uma notícia sem saída: o gestor
    tem de poder dizer à loja se foi o endereço, se foi a app ou se foi o
    envio."""
    assert falhada["aberto"] is not None, "o detalhe não mostra a linha do email"
    assert "Fatura por email" in falhada["aberto"], falhada["aberto"]
    assert "Falhou ao fim de 24 h" in falhada["aberto"], falhada["aberto"]
    assert "envio falhou" in falhada["aberto"], falhada["aberto"]
    assert "ficou sem documento" in falhada["aberto"], falhada["aberto"]


def test_um_motivo_de_recusa_aparece_em_PORTUGUES_como_o_dos_pontos(recusada):
    """Os dois blocos ficam lado a lado no mesmo diálogo, e a fila é a mesma
    (`fat_pontos_app`): um em português e outro em código-máquina era o mesmo
    motivo escrito de duas maneiras à mesma pessoa. O mapa
    `MOTIVOS_DOS_PONTOS` já existe no mesmo ficheiro (`FatDocumentos.js:66-79`),
    é o que o `textoDosPontosApp` (`:81-110`) usa, e a função nova entra logo a
    seguir a ele — não se escreve uma segunda tabela."""
    assert "aquele QR já deu pontos noutra fatura" in recusada["aberto"], \
        recusada["aberto"]
    assert "ligacao_ja_usada" not in recusada["aberto"], recusada["aberto"]


def test_o_botao_de_reenviar_esta_ao_lado_dos_dois_que_ja_la_estavam(falhada):
    assert falhada["tem_botao"] is True
    assert falhada["reimprimir"] is True
    assert falhada["pdf"] is True


def test_reenviar_pede_ao_servidor_e_RELE_o_documento(falhada):
    """O ecrã não escreve «a caminho» por sua conta: volta a perguntar ao
    servidor e desenha a linha como ela ficou. Um ecrã que se pintasse sozinho
    dizia «à espera» mesmo quando a reposição falhou."""
    assert _quantos(falhada["pedidos"],
                    "POST /faturacao/documentos/d1/reenviar-email") == 1, \
        falhada["pedidos"]
    assert _quantos(falhada["pedidos"], "GET /faturacao/documentos/d1") == 2, \
        falhada["pedidos"]
    assert falhada["depois"] is not None, "o bloco do email desapareceu do ecrã"
    assert "À espera de ser enviada." in falhada["depois"], falhada["depois"]
    assert "Falhou" not in falhada["depois"], falhada["depois"]


def test_um_documento_que_NAO_ia_por_email_nao_mostra_bloco_nem_botao(sem_email):
    """A esmagadora maioria dos documentos. Um bloco vazio ou um «—» lia-se
    como «o email perdeu-se», e o botão convidava a mandar por email uma
    fatura de um cliente que nunca deu email nenhum."""
    assert sem_email["aberto"] is None
    assert sem_email["tem_botao"] is False
```

- [ ] **Step 2: Correr e ver falhar**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_o_reenvio_por_email_no_backoffice.py -q`

Expected: FAIL em QUATRO dos cinco:
- `test_o_detalhe_diz_que_o_envio_FALHOU_e_o_ultimo_erro` — `AssertionError: o detalhe não mostra a linha do email` (o `FatDocumentos` ainda não conhece o `fatura_email`);
- `test_um_motivo_de_recusa_aparece_em_PORTUGUES_como_o_dos_pontos` — `TypeError: argument of type 'NoneType' is not iterable` sobre `recusada["aberto"]`;
- `test_o_botao_de_reenviar_esta_ao_lado_dos_dois_que_ja_la_estavam` — `assert False is True`;
- `test_reenviar_pede_ao_servidor_e_RELE_o_documento` — `assert 0 == 1` no `POST …/reenviar-email`.

`test_um_documento_que_NAO_ia_por_email_nao_mostra_bloco_nem_botao` passa já: é o guarda do ramo que tem de continuar vazio.

- [ ] **Step 3: Implementação mínima**

Em `frontend/src/lib/faturacao.js`, a seguir ao `reimprimirDocumento` (depois da linha 274):

```js

// **Reenviar a fatura por email** — para QUALQUER documento que tenha linha de
// email, e não só para os falhados: o caso frequente é «não me chegou» com a
// linha em `feito` (o Resend aceitar não quer dizer que a caixa do cliente
// recebeu, e não há recetor de devoluções em lado nenhum). Quem repõe a linha
// da fila — estado, tentativas, relógios — é o servidor; daqui vai só o id.
//
// O caminho é o das rotas do GESTOR (`${API_URL}/faturacao/...`), ao lado do
// `reimprimir` aqui em cima. O `/pos/` que a especificação escreve é gralha:
// nenhuma rota de gestão vive lá.
export const reenviarEmailDocumento = (id) => api.post(
  `${API_URL}/faturacao/documentos/${id}/reenviar-email`);
```

Em `frontend/src/pages/admin/faturacao/FatDocumentos.js`:

1. no import do `lib/faturacao` (linhas 2-5), acrescentar `reenviarEmailDocumento,`;
2. no import dos ícones (linhas 19-21), acrescentar `Mail,`;
3. a seguir ao `textoDosPontosApp` (depois da linha 110):

```js

// **O que aconteceu ao email desta fatura.** O servidor manda `fatura_email` —
// a linha `fatura_email:<id>` da mesma fila `fat_pontos_app`. `null` quando
// esta fatura não ia por email (a esmagadora maioria: sem QR não há email), e
// aí não se desenha nada.
//
// **«Enviada» quer dizer «o servidor de envio aceitou», e não «o cliente
// recebeu».** Não há recetor de devoluções em lado nenhum: uma caixa cheia, ou
// um relay com o reencaminhamento desligado, fecha a linha como feita na mesma.
// A frase diz o que se sabe e nada mais — é isso que impede o gestor de
// responder «foi enviada» a quem está a dizer a verdade.
const textoDoEnvioPorEmail = (e) => {
  if (e.estado === 'feito') {
    return 'Enviada — aceite pelo servidor de envio (não é prova de entrega)';
  }
  if (e.estado === 'pendente') {
    if (e.tentativas > 0) {
      return `A tentar enviar (${e.tentativas} ${e.tentativas === 1 ? 'tentativa' : 'tentativas'} — último erro: ${e.ultimo_erro || 'sem detalhe'})`;
    }
    // Pendente com 0 tentativas não quer dizer «acabou de sair»: há caminhos
    // que esperam de propósito sem gastar tentativa (a integração sem chave é
    // o grave — nada está a ser enviado em lado nenhum).
    if (e.ultimo_erro) return `À espera — último erro: ${e.ultimo_erro}`;
    return 'À espera de ser enviada.';
  }
  if (e.estado === 'recusado') {
    // **O mesmo mapa dos pontos**, e nunca uma segunda tabela: a fila é a
    // mesma e os motivos são os mesmos. Os dois blocos ficam lado a lado neste
    // diálogo — um em português e outro em cru era o mesmo motivo escrito de
    // duas maneiras à mesma pessoa. Motivos novos, só do email, acrescentam-se
    // ao MOTIVOS_DOS_PONTOS aqui em cima.
    return `Recusado pela app: ${MOTIVOS_DOS_PONTOS[e.motivo] || e.motivo || 'sem motivo'}`;
  }
  if (e.estado === 'sem_efeito') {
    return 'Sem efeito — esta fatura não chegou a ir por email.';
  }
  if (e.estado === 'falhado') {
    // **O cliente ficou sem documento nenhum** — o talão não saiu. É o risco
    // aceite pelo dono, e a única forma de alguém dar por ele é estar escrito.
    return `Falhou ao fim de 24 h${e.ultimo_erro ? ` — último erro: ${e.ultimo_erro}` : ''}. O cliente ficou sem documento: reenvie, ou mande reimprimir na loja.`;
  }
  return `Estado desconhecido: ${e.estado}`;
};
```

4. a seguir ao `const [aPdf, setAPdf] = useState(false);` (linha 123): `const [aReenviar, setAReenviar] = useState(false);`
5. a seguir ao handler `abrirPdf` (depois da linha 200):

```js

  const reenviar = async () => {
    if (!aberto || aReenviar) return;
    setAReenviar(true);
    try {
      await reenviarEmailDocumento(aberto.id);
      // O que se promete é o que se sabe: a linha voltou à FILA. Dizer
      // «enviada» daqui era afirmar o que só o envio dirá — e este botão
      // existe precisamente porque «enviada» já tinha sido dito uma vez.
      toast.success('Fatura outra vez na fila do email — sai no minuto seguinte.');
      // E relê-se o documento: o estado que fica no ecrã é o que o servidor
      // gravou, e não o que este lado gostava que tivesse acontecido.
      const { data } = await getDocumento(aberto.id);
      setAberto(data);
    } catch (error) {
      toast.error(detalhesErro(error, 'Não foi possível reenviar esta fatura.').mensagem);
    } finally {
      setAReenviar(false);
    }
  };
```

6. a seguir ao bloco dos pontos (depois da linha 515):

```jsx
              {aberto.fatura_email && (
                <div className="rounded-xl border p-3 text-sm" data-testid="documento-fatura-email">
                  <p className="text-xs uppercase tracking-wide text-muted-foreground mb-1">
                    Fatura por email
                  </p>
                  <p className="font-medium">{textoDoEnvioPorEmail(aberto.fatura_email)}</p>
                  {aberto.fatura_email.atualizado_em && (
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Atualizado {formatarData(aberto.fatura_email.atualizado_em)}
                    </p>
                  )}
                </div>
              )}
```

7. dentro do `<div className="flex flex-wrap gap-2">` dos botões, a seguir ao botão «PDF da fatura» (depois da linha 575):

```jsx
                {/* Só aparece quando esta fatura tem linha de email: um botão
                    para mandar por email uma fatura de um cliente que nunca
                    deu email nenhum não tem para onde a mandar. Sai do ecrã em
                    vez de ficar cinzento, pela regra do «Reimprimir» aqui ao
                    lado. */}
                {aberto.fatura_email && (
                  <Button
                    variant="outline"
                    onClick={reenviar}
                    disabled={aReenviar}
                    title="Volta a pôr esta fatura na fila do email, para o endereço da conta do cliente"
                    data-testid="documento-reenviar-email"
                  >
                    {aReenviar
                      ? <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      : <Mail className="h-4 w-4 mr-2" />}
                    Reenviar por email
                  </Button>
                )}
```

- [ ] **Step 4: Correr e ver passar**

Run: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest tests/faturacao/test_o_reenvio_por_email_no_backoffice.py tests/faturacao/test_o_ecra_de_documentos_no_backoffice.py tests/faturacao/test_caminhos_do_pos.py -q`

Expected: PASS. **Se o `test_caminhos_do_pos.py` falhar** com «Estas chamadas do **backoffice** apontam para caminhos que o servidor não serve: POST /api/faturacao/documentos/{}/reenviar-email» (o guarda é o `test_todas_as_chamadas_do_backoffice_apontam_para_rotas_que_existem`, `:200-214`), falta juntar a rota da Frente B.

Depois, a suite inteira: `cd /Users/matheus.moraes/Developer/RH/backend && .venv/bin/pytest -q` → `0 failed`, `0 skipped`.

- [ ] **Step 5: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH
git add frontend/src/lib/faturacao.js frontend/src/pages/admin/faturacao/FatDocumentos.js \
  backend/tests/faturacao/test_o_reenvio_por_email_no_backoffice.py
git commit -F - <<'EOF'
Backoffice: o detalhe do documento diz o que aconteceu ao email, e reenvia

Bloco ao lado do «Pontos L'Açaí» com o estado da linha da fila e o último
erro — com os motivos traduzidos pelo mapa que já lá estava —, e o botão
«Reenviar por email» ao lado do «Reimprimir na loja» e do «PDF da fatura»,
para qualquer documento com linha de email: o caso frequente é «não me
chegou» com a linha em feito. Depois de reenviar, o ecrã relê o documento em
vez de se pintar sozinho.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Notas da revisão

Onze pontos aplicados. Três mereceram desvio, e a razão vai escrita porque muda o que o executor tem à frente:

1. **«Ler o NIF de `documento.cliente_nif`» estava errado — e depois a decisão do dono deitou fora a pergunta toda.** A revisão tinha apanhado que o campo não existe aí: `_resposta_documento` (`fiscal.py:1988-1998`) manda exactamente seis campos — `id`, `vendus_document_id`, `numero`, `atcud`, `total`, `modo` — e o `cliente_nif` viaja no nível da **venda**, acrescentado à mão em `fiscal.py:2308`, com o `PosVenda` a aplicá-lo em `aplicarVenda(data)`; a fonte certa seria `venda?.cliente_nif ?? nifTexto`. **A 2026-09-17 o dono decidiu que o NIF não decide nada** — «depende da opção se quer ou não por email a fatura; o seletor é que manda» —, e com isso caiu a condição, a fonte, o `?? nifTexto` e uma das montagens: restou UM teste, invertido, a provar que o NIF **não** muda a frase, com as duas fontes do NIF no mesmo cenário para nenhuma delas poder voltar em silêncio. A confirmação sobre `_resposta_documento` fica escrita porque continua a valer para quem for lá buscar outro campo — e o número da linha estava errado nesta nota (`1257-1268` é o registo do documento que se GRAVA, esse sim com `cliente_nif`).
2. **O filtro «por enviar»: escolhida a segunda das duas vias, e não a primeira.** Contar só os becos sem saída (`falhado`/`recusado`/`sem_efeito`) tapava o buraco do contador que acende no minuto normal, mas abria outro pior: um `pendente` encalhado acende o alarme da loja (que tem janela) e não apareceria no filtro — a operadora vê o aviso e não encontra a fatura a que tem de dar papel. Por isso o contrato da lista do POS passa a trazer `fatura_email_por_enviar: bool`, calculado pelo MESMO predicado do `count_documents` do alarme. Consequência prática: a Task 4 deixa de acrescentar função nenhuma a `lib/pos.js` (não há decisão neste lado para testar) e o campo `fatura_email` cru sai do contrato da lista do POS — o balcão não o desenha em lado nenhum.
3. **Um defeito que a crítica não apanhou, e que teria posto a Task 5 vermelha na mesma:** o teste comparava `saida.pedidos` por igualdade (`"POST /faturacao/..." in pedidos`). O `url` guardado em `pedidos` é `(baseURL || '') + url`, e o `API_URL` do backoffice é `process.env.REACT_APP_BACKEND_URL + '/api'` — em Node essa variável não existe e o caminho chega literalmente como `undefined/api/faturacao/...`. A casa já compara com `endswith` (`test_o_ecra_de_documentos_no_backoffice.py:118-139`); o teste da Task 5 passa a fazer o mesmo, com um `_quantos()` para contar as duas leituras do documento.

E duas confirmações que mudaram números no plano: a linha 560 do `PosFinalizar.js` é mesmo o separador `// --- Pontos L'Açaí ---` (o intervalo da Task 2 passou a 562-599), e o handler novo do backoffice entra depois da linha 200 (o `abrirPdf` acaba aí, não na 198).

Duas correcções de passagem, à volta da decisão do dono, as duas medidas no repositório e não de cabeça:

- **O import do `@/lib/pos` no `PosFinalizar.js` é 15-20, não 14-20** (a linha 14 é o `import PosLerQr from './PosLerQr';`). Corrigido nas Tasks 2 e 3, nos quatro sítios onde aparecia.
- **O `-k emitida` do Step 2 da Task 3 não colhia teste nenhum.** O `-k` do pytest casa com o nome do teste e com o dos pais dele, **nunca com o nome de uma fixture** — e `emitida...` só existia em fixtures. Ao mesmo tempo, o nome do MÓDULO conta: num ficheiro chamado `test_a_fatura_por_email_no_ecra_do_pos.py`, um `-k` com «fatura» ou «por_email» colhe o ficheiro inteiro. Medido nos dois sentidos em `test_os_pontos_no_ecra_do_pos.py`: `-k guardado` (fixture) dá «no tests collected (19 deselected)» e `-k no_ecra_do_pos` (módulo) colhe os 19. O Step 2 passou a `-k "documento or enviada or NIF or TESTES"`, que nomeia os testes daquela task e mais nenhum (eram quatro nessa passagem; são cinco depois de a condição do `vendus_document_id` trazer o seu). Um `-k` vazio é o pior dos enganos num Step «correr e ver falhar»: não falha nada, e parece que correu bem.

### Segunda passagem — os achados do verificador, aplicados

Sete pontos, e o buraco de desenho fechado. Todos se confirmaram no código real antes de mexer; nenhum ficou por aplicar por estar errado.

1. **O buraco do `vendus_document_id`: FECHADO, com teste.** Era a decisão que faltava tomar. Com `documento["vendus_document_id"]` vazio o servidor devolve `False` no `enfileirar_fatura_email` e manda imprimir (`enfileirar_venda_emitida`) — e o ecrã prometia «Fatura vai por email». Não é caso de laboratório: `vendus/emissao.py:702` só recusa um 2xx quando faltam `id` **E** `atcud`, portanto um documento real pode ficar com `vendus_document_id: None`, e é esse mesmo caso que dá 422 no botão «PDF da fatura» (`documentos.py:894`). O ecrã **vê** o campo — `_resposta_documento` manda-o nos seus seis campos (`fiscal.py:1988-1998`) e o `PosFinalizar.js:961` já o desenha —, por isso o velho «menos a que este lado não pode ver» era falso a dobrar. O `aFaturaVaiPorEmail` ganhou `&& !!(documento && documento.vendus_document_id)`, e com ele veio a montagem própria (`emitida_sem_id_do_vendus`, feita como a do modo `tests`: `dict(_EMITIDA, documento=dict(_EMITIDA["documento"], vendus_document_id=None))`), o teste `test_um_documento_SEM_id_do_Vendus_fala_de_PAPEL` e a mutação 3 do Step 4. **Neste ficheiro nenhuma condição entra sem a montagem que a parte.**
2. **«As duas condições que o ecrã pode ver» era um decremento mecânico.** O servidor tem CINCO (`modo`, `vendus_document_id`, `pontos_ligacao`, a linha do `fat_pontos_qr`, a escrita na fila — plano B, Global Constraints) e o ecrã aplica TRÊS. As duas que ficam de fora estão agora nomeadas: a linha do `fat_pontos_qr` (este lado tem só a cópia da gaveta) e a escrita na fila.
3. **O apontador do módulo estava a mandar o executor ao ficheiro errado.** O `enfileirar_fatura_email` é da Frente B e nasce em `backend/faturacao/pontos_app.py`, ao lado do `enfileirar_credito`; o `fiscal.py` só o chama. O comentário do `aFaturaVaiPorEmail` dizia `faturacao/fiscal.py::enfileirar_fatura_email`.
4. **Contagens corrigidas, contadas e não estimadas.** Os imports do cabeçalho da Task 1 são SEIS e não cinco (`_correr`, `_CODIGO`, `_EMITIDA`, `_EMITIR`, `_UTEIS`, `_no_finalizar`), e dois deles — `_UTEIS` e `_CODIGO` — são usados já pela fixture da própria Task 1, não «pelas partes de baixo». A escrita optimista do cartão passaria nos outros CINCO testes do cartão (não «quatro deste ficheiro»), a RECUSA incluída, onde o `await` rebenta antes da escrita e o cartão fica certo por acidente. O `MOTIVOS_DOS_PONTOS` não está «dez linhas acima»: está em `FatDocumentos.js:66-79`, o `textoDosPontosApp` que o usa ocupa `:81-110`, e a função nova entra a seguir à 110. E o bloco «Depois do EMITIR» tem agora QUATRO montagens — três condições do servidor mais a decisão do dono provada pelo avesso —, e não «três regras da spec»: a spec revogou a do NIF.
5. **O `-k` continua a nomear só os testes desta task, agora cinco.** O teste novo entra pela palavra «documento», que não aparece em nenhum dos oito testes das Tasks 1 e 2 nem no nome do módulo — verificado nome a nome. E o Step 2 passa a esperar FAIL em DOIS com TRÊS a passar já: antes da implementação o ecrã fala sempre de papel.
6. **Uma correcção que não vinha nos achados, medida agora:** o `tentar_ja` está em `pontos_app.py:253-267`; o `243-256` que o plano citava nos dois sítios apanhava o fim da docstring da função anterior. É o mesmo defeito do ponto 3 — um apontador que manda o executor ler outra coisa —, por isso foi corrigido na mesma passagem.
7. **O NIF continua a não decidir nada, e o guarda é partível.** Confirmado por leitura do ficheiro inteiro: o `aFaturaVaiPorEmail` não recebe `nif`, a chamada no `PosFinalizar.js` não passa `venda?.cliente_nif` nem `nifTexto`, e a mutação 2 do Step 4 repõe a regra morta e põe o teste vermelho. Nada a mudar.
