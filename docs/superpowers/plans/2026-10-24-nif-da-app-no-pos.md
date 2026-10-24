# O NIF da conta da app no cartão Cliente do POS — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quando a caixa lê o QR da app e a conta tem NIF válido, o cartão Cliente do pagamento oferece «Usar o NIF da app · 2•• ••• •89»; um toque preenche o NIF da fatura.

**Architecture:** A app passa a devolver `nif` no `/api/pos-integracao/ligar` (sem o gravar). O servidor do POS valida-o outra vez e passa-o ao ecrã no `/pos/pontos/ler`. O ecrã guarda-o na gaveta da ligação, mostra o botão mascarado no cartão Cliente e, ao toque, escreve no campo NIF de sempre — o EMITIR não muda.

**Tech Stack:** FastAPI + Motor (app e POS), React (POS), banco de ensaio de ecrãs em pytest + node/jsdom (`backend/tests/faturacao`).

**Spec:** `docs/superpowers/specs/2026-10-24-nif-da-app-no-pos-design.md` (nos dois repos).

## Global Constraints

- Nunca preencher o NIF sozinho: só o toque no botão escreve no campo.
- `nif` está SEMPRE presente nas respostas (`/ligar`, `/pos/pontos/ler`, `onLigada`, gaveta `pos_pontos_da_conta`): string de 9 dígitos ou `None`/`null`.
- O NIF NÃO se grava em `db.pos_ligacoes` (app), `fat_pontos_qr` nem na venda (POS), e NUNCA vai dentro de `pontos_ligacao` (continua `{id, primeiro_nome}`).
- O NIF nunca se escreve em logs.
- Máscara: `'219363935'` → `'2•• ••• •35'`.
- Texto do botão: `Usar o NIF da app · <máscara>`.
- Sem build da app. Comentários e nomes de testes em PT-PT, no estilo dos ficheiros vizinhos.
- Commits terminam com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- `PYTHONDONTWRITEBYTECODE=1` em todas as corridas; ler sempre `passed` E `skipped`.
- Worktrees: app em `/Users/matheus.moraes/applacai-nif-da-app`, POS em `/Users/matheus.moraes/Developer/RH-nif-da-app` (ramo `matheus-nif-da-app` nas duas). NUNCA tocar em `~/applacai` nem `~/Developer/RH`. NUNCA copiar o `.env` de `~/applacai/backend` (aponta para a produção).

## Ordem

- **App:** A1 → A2 (mesma worktree, em série).
- **POS:** R1 → R2 → R3 (mesma worktree, em série).
- As duas cadeias podem correr em paralelo (worktrees diferentes). Dentro de cada worktree, nunca duas tarefas ao mesmo tempo: as verificações por mutação mexem no código e fariam a outra suite mentir.

---

### Task A1: o `/ligar` devolve o NIF da conta (sem o guardar na ligação)

**Repo/worktree:** `/Users/matheus.moraes/applacai-nif-da-app`

**Files:**
- Modify: `backend/routes_pos_integracao.py:32` (import), `:117-119` (projeção), `:133-134` (cálculo do `nif`), `:143-151` (comentário de privacidade + resposta)
- Test: `backend/tests/test_pos_integracao_unit.py` (2 testes novos, a seguir a `test_quem_ligou_o_interruptor_na_app_chega_a_caixa_ja_com_a_escolha_feita`, que acaba na linha 335)

**Interfaces:**
- Consumes: `auth.valid_nif(nif: str) -> bool` (`backend/auth.py:180-188`; faz strip, exige 9 dígitos e confere o dígito de controlo); o campo `users.nif` (fica AUSENTE quando não há NIF, por causa do índice unique+sparse).
- Produces: `POST /api/pos-integracao/ligar` responde **exatamente** `{"ligacao_id": str, "primeiro_nome": str, "fatura_por_email": bool, "nif": str | None}`. `nif` vem sempre: é uma string de 9 dígitos válida, ou `None`. O servidor do POS (Task do RH) lê `corpo.get("nif")`. `db.pos_ligacoes` **não** ganha a chave `nif`.

- [ ] **Step 1: Write the failing test(s)**: em `backend/tests/test_pos_integracao_unit.py`, a seguir à linha 335 (`    assert db.pos_ligacoes.docs[0]["fatura_por_email"] is True`) e às duas linhas em branco, antes de `def test_a_troca_ao_balcao_vale_para_a_venda_e_nao_mexe_no_que_o_cliente_marcou(db):`, inserir:

```python
def test_o_ligar_traz_o_nif_da_conta_para_a_caixa_o_oferecer_e_nao_o_guarda_na_ligacao(db):
    """Hoje o NIF é ditado e escrito à mão na caixa, e é por aí que entram os
    enganos. Quem mostra o QR já o tem, muitas vezes, na conta: o /ligar passa-o
    ao POS para ele o OFERECER num botão — nunca para o pôr sozinho.

    Não fica na ligação: o `delete_account` só tira o `user_id` às ligações, e
    um NIF gravado ali sobrevivia à conta apagada. E o resto continua fechado: a
    resposta tem estas quatro chaves e nenhuma outra, e o email não sai.
    """
    db.users.docs[0]["nif"] = "219363935"
    db.users.docs[0]["email"] = "ana@exemplo.pt"
    # A PROJEÇÃO, à mão, pela mesma razão do teste de cima: o duplo devolve o
    # documento inteiro, e sem `"nif": 1` na rota a suite ficava verde e, contra
    # o Mongo a sério, o NIF vinha sempre None — o botão nunca aparecia.
    pedida = {}
    original = db.users.find_one

    async def espiar(filtro, proj=None):
        pedida.update(proj or {})
        return await original(filtro, proj)

    db.users.find_one = espiar

    r = _ligar(_token(db))
    assert pedida.get("nif") == 1, f"a rota não pediu o NIF à base: {pedida}"
    assert r["nif"] == "219363935"
    assert set(r) == {"ligacao_id", "primeiro_nome", "fatura_por_email", "nif"}, r
    assert "@" not in str(r), r
    assert "nif" not in db.pos_ligacoes.docs[0], db.pos_ligacoes.docs[0]


@pytest.mark.parametrize("nif", ["ausente", "219363931"])
def test_conta_sem_nif_ou_com_nif_que_nao_vale_chega_a_caixa_com_nif_none(db, nif):
    """Sem NIF na conta, ou com um que falha o dígito de controlo, a caixa não
    oferece nada. A chave vem SEMPRE, a None: o POS lê uma forma só, e uma conta
    antiga sem o campo não é um caso à parte."""
    if nif != "ausente":
        db.users.docs[0]["nif"] = nif
    r = _ligar(_token(db))
    assert "nif" in r and r["nif"] is None, r
    assert "nif" not in db.pos_ligacoes.docs[0], db.pos_ligacoes.docs[0]
```

(Deixar duas linhas em branco entre o último teste novo e `def test_a_troca_ao_balcao_...`.)

- [ ] **Step 2: Run to verify it fails**

```bash
cd /Users/matheus.moraes/applacai-nif-da-app/backend && PYTHONDONTWRITEBYTECODE=1 ~/applacai/backend/.venv/bin/python -m pytest tests/test_pos_integracao_unit.py tests/test_termos_unit.py -q
```

Esperado: `3 failed, 97 passed`, 0 skipped. As mensagens:
- `test_o_ligar_traz_o_nif_da_conta_para_a_caixa_o_oferecer_e_nao_o_guarda_na_ligacao` → `AssertionError: a rota não pediu o NIF à base: {'_id': 0, 'name': 1, 'roles': 1, 'is_active': 1, 'fatura_por_email': 1}`
- `test_conta_sem_nif_ou_com_nif_que_nao_vale_chega_a_caixa_com_nif_none[ausente]` e `[219363931]` → `AssertionError: {'fatura_por_email': False, 'ligacao_id': '…', 'primeiro_nome': 'Ana'}` / `assert ('nif' in {...})`

- [ ] **Step 3: Implement**: quatro edições em `backend/routes_pos_integracao.py`.

(a) Linha 32, antes:
```python
from auditoria import registar
from auth import iso, now_utc
from campaigns_engine import active_multiplier, advance_on_purchase
```
depois:
```python
from auditoria import registar
from auth import iso, now_utc, valid_nif
from campaigns_engine import active_multiplier, advance_on_purchase
```

(b) Linhas 117-119, antes:
```python
    user = await db.users.find_one({"id": token.get("user_id")},
                                   {"_id": 0, "name": 1, "roles": 1, "is_active": 1,
                                    "fatura_por_email": 1})
```
depois:
```python
    user = await db.users.find_one({"id": token.get("user_id")},
                                   {"_id": 0, "name": 1, "roles": 1, "is_active": 1,
                                    "fatura_por_email": 1, "nif": 1})
```

(c) Linhas 133-134, antes:
```python
    prefere_email = bool(user.get("fatura_por_email"))
    await db.pos_ligacoes.insert_one({
```
depois:
```python
    prefere_email = bool(user.get("fatura_por_email"))
    # O NIF da conta, para a caixa o OFERECER. Passa outra vez pelo `valid_nif`:
    # um NIF que não vale não chega ao ecrã e o botão não aparece. NÃO se grava
    # na ligação: o `delete_account` só tira o `user_id` às ligações, e um NIF
    # gravado aqui sobrevivia à conta apagada.
    nif = str(user.get("nif") or "").strip()
    nif = nif if valid_nif(nif) else None
    await db.pos_ligacoes.insert_one({
```
(O `insert_one` que vem a seguir **não muda**.)

(d) Linhas 143-151, antes:
```python
    # Só o primeiro nome: é o que a funcionária precisa para confirmar "é a Ana?",
    # e é tudo o que o ecrã da caixa (virado para a fila) deve mostrar. O email
    # NÃO sai daqui, nem mascarado — o POS recebe um sim/não e mais nada.
    # Devolve-se a MESMA variável que acabou de ser gravada, e não uma releitura
    # da ligação: ler o campo de volta era fingir uma consulta que não existe, e
    # abria a porta a o ecrã dizer uma coisa e a linha gravada dizer outra.
    return {"ligacao_id": lid,
            "primeiro_nome": ((user.get("name") or "").split() or [""])[0],
            "fatura_por_email": prefere_email}
```
depois:
```python
    # Do nome, só o primeiro: é o que a funcionária precisa para confirmar "é a
    # Ana?". O email NÃO sai daqui, nem mascarado — o POS recebe um sim/não.
    # O NIF é a exceção, e sai inteiro porque é para entrar num documento fiscal:
    # o POS oferece-o num botão e só entra na fatura se o cliente o confirmar na
    # caixa. Quem o esconde da fila é o POS, que o mostra mascarado. A chave vem
    # sempre, a None quando a conta não tem um NIF que valha.
    # Devolve-se a MESMA variável que acabou de ser gravada, e não uma releitura
    # da ligação: ler o campo de volta era fingir uma consulta que não existe, e
    # abria a porta a o ecrã dizer uma coisa e a linha gravada dizer outra.
    return {"ligacao_id": lid,
            "primeiro_nome": ((user.get("name") or "").split() or [""])[0],
            "fatura_por_email": prefere_email,
            "nif": nif}
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd /Users/matheus.moraes/applacai-nif-da-app/backend && PYTHONDONTWRITEBYTECODE=1 ~/applacai/backend/.venv/bin/python -m pytest tests/test_pos_integracao_unit.py tests/test_termos_unit.py -q
```
Esperado: `100 passed`, 0 skipped.

Vizinhos que importam a rota (devem continuar verdes, sem skips):
```bash
cd /Users/matheus.moraes/applacai-nif-da-app/backend && PYTHONDONTWRITEBYTECODE=1 ~/applacai/backend/.venv/bin/python -m pytest tests/test_canecas_unit.py tests/test_fatura_por_email_unit.py tests/test_fs_client_unit.py tests/test_o_contrato_com_o_pos.py tests/test_voucher_ao_balcao_unit.py -q -rs
```
Esperado: `118 passed`, 0 skipped.

- [ ] **Step 5: Mutation check**: cada uma à vez, voltar a pôr o ficheiro como estava depois de cada uma, e correr o comando do Step 4:
  1. Tirar `, "nif": 1` da projeção (linha 119) → fica vermelho **só** `test_o_ligar_traz_o_nif_da_conta_para_a_caixa_o_oferecer_e_nao_o_guarda_na_ligacao` (`a rota não pediu o NIF à base`): `1 failed, 99 passed`. É a mutação obrigatória do spec.
  2. Apagar a linha `nif = nif if valid_nif(nif) else None` → ficam vermelhos `[ausente]` e `[219363931]` (o ausente também, porque sem a linha vem `""` e não `None`): `2 failed, 98 passed`.
  3. Na linha 144 do `insert_one` (só nessa, porque há outra linha com `"fatura_por_email": prefere_email,` no `return`), pôr `"fatura_por_email": prefere_email, "nif": nif,` → os 3 testes novos ficam vermelhos em `assert 'nif' not in {...}`: `3 failed, 97 passed`.
  4. Acrescentar `"email": 1` à projeção e `"email": user.get("email")` ao `return` → ficam vermelhos `test_o_ligar_diz_se_a_fatura_vai_por_email_e_nunca_o_endereco` e o teste novo do NIF (chaves a mais e `@`): `2 failed, 98 passed`.

- [ ] **Step 6: Commit**

```bash
cd /Users/matheus.moraes/applacai-nif-da-app && git add backend/routes_pos_integracao.py backend/tests/test_pos_integracao_unit.py && git commit -F - <<'EOF'
O /ligar passa à caixa o NIF da conta, para o POS o oferecer num botão

Hoje o NIF das faturas das lojas é ditado e escrito à mão, e é por aí que
entram os enganos. Quem mostra o QR já o tem muitas vezes na conta: o /ligar
passa a devolvê-lo (chave "nif", sempre presente, None quando a conta não tem
um NIF que passe no valid_nif). O POS mostra-o mascarado e só o põe na fatura
se o cliente disser que sim na caixa.

Não se grava em pos_ligacoes: o delete_account só tira o user_id às ligações,
e um NIF gravado ali sobrevivia à conta apagada. O email continua sem sair.

O duplo do Mongo ignora a projeção. O teste novo espia-a, e vi-o vermelho ao
tirar o "nif": 1. Também ficam vermelhos: sem o valid_nif, com o NIF gravado
na ligação e com o email na resposta. A resposta fica presa a exatamente
quatro chaves.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task A2: textos legais (Privacidade §1 e Termos 4.2) e a versão dos Termos

**Repo/worktree:** `/Users/matheus.moraes/applacai-nif-da-app`

**Files:**
- Modify: `backend/legal_pages.py:43` (data da Privacidade), `:65` (item «Pontos dados na caixa»), `:184` (data dos Termos), `:276` (Termos 4.2, parágrafo novo a seguir à «Fatura por email»)
- Modify: `backend/auth.py:344` (`TERMOS_VERSAO`)
- Test: `backend/tests/test_termos_unit.py` (aperta 1 assert na linha 58 e acrescenta 2 testes no fim), `backend/tests/test_ponte_categorias_unit.py:329-330` (versão fixada)

**Interfaces:**
- Consumes: nada da A1 (as tarefas são independentes). As contagens abaixo assumem a A1 já feita.
- Produces: `auth.TERMOS_VERSAO == "2026-10-24"`. É o carimbo `termos_versao` que as contas novas gravam ao aceitar os Termos. `/termos` e `/privacidade` dizem «Última atualização: 24 de outubro de 2026».

- [ ] **Step 1: Write the failing test(s)**

(a) `backend/tests/test_termos_unit.py`, linha 58, dentro de `test_os_termos_dizem_para_onde_vai_a_fatura_e_como_se_volta_ao_papel`. Antes:
```python
        assert "não lhe é entregue talão em papel" in html
        assert "vale apenas para essa compra" in html
        assert "pode pedir o talão em papel" in html
```
depois:
```python
        assert "não lhe é entregue talão em papel" in html
        # Com a marcação: o parágrafo do NIF diz a mesma frase, e sem ela este
        # assert passava com a «Fatura por email» apagada.
        assert "A escolha <strong>vale apenas para essa compra</strong>" in html
        assert "pode pedir o talão em papel" in html
```

(b) No fim de `backend/tests/test_termos_unit.py`, depois de `    assert "[[" not in html` (a última linha de `test_a_privacidade_declara_a_finalidade_nova_e_que_a_escolha_se_guarda`), acrescentar:
```python


# --- o NIF da conta na caixa ----------------------------------------------------

def test_os_termos_dizem_que_o_nif_da_conta_so_entra_na_fatura_se_o_cliente_disser_que_sim():
    """A caixa passa a receber o NIF da conta e a oferecê-lo. Os Termos têm de
    dizer que é uma pergunta e não um preenchimento, que vale só para aquela
    compra e que uma fatura emitida já não se altera. Nas duas versões da 4.2:
    o parágrafo vive ao lado da «Fatura por email», que aparece sempre — no
    `_QR_NA_CAIXA` desaparecia com o «Ler fatura» ligado."""
    for ligado in (True, False):
        html = pagina_termos("5 minutos", 1, 100.0, ler_fatura=ligado)
        assert ("<strong>NIF na fatura.</strong> Se tiver NIF na conta, a caixa pode "
                "perguntar-lhe se o quer na fatura. Só é usado se disser que sim e vale "
                "apenas para essa compra. Depois de emitida, a fatura não pode ser "
                "alterada.") in html


def test_a_privacidade_diz_o_que_a_loja_recebe_da_app_quando_le_o_qr():
    """O /ligar passou a dar à loja o NIF da conta, além do primeiro nome: é um
    dado pessoal a ir para outro sítio, e tem de estar escrito antes de o
    primeiro QR o levar. O texto quebra linhas no HTML; compara-se sem elas."""
    texto = " ".join(asyncio.run(privacy_policy()).split())
    assert ("Quando a caixa lê o seu QR, a loja recebe da app o seu primeiro nome e, "
            "se tiver NIF na conta, esse NIF. O NIF só entra na fatura dessa compra "
            "se o confirmar na caixa.") in texto
    assert "Última atualização: 24 de outubro de 2026" in texto
```
(O ficheiro termina com uma única quebra de linha depois de `in texto`.)

(c) `backend/tests/test_ponte_categorias_unit.py:329-330`. Antes:
```python
    assert auth.TERMOS_VERSAO == "2026-10-14", \
        "o NIF passou a opcional na secção 3.2 a 14/10: a versão dos Termos é essa"
```
depois:
```python
    assert auth.TERMOS_VERSAO == "2026-10-24", \
        "o NIF da conta na caixa entrou na secção 4.2 a 24/10: a versão dos Termos é essa"
```

- [ ] **Step 2: Run to verify it fails**: o `test_pos_integracao_unit.py` tem de vir PRIMEIRO na lista (ver Notas: sozinho, o `test_termos_unit.py` não chega a ser recolhido neste worktree):

```bash
cd /Users/matheus.moraes/applacai-nif-da-app/backend && PYTHONDONTWRITEBYTECODE=1 ~/applacai/backend/.venv/bin/python -m pytest tests/test_pos_integracao_unit.py tests/test_termos_unit.py tests/test_ponte_categorias_unit.py tests/test_registo_social_unit.py tests/test_nif_opcional_unit.py tests/test_canecas_rotas_unit.py -q
```
Esperado: `3 failed, 220 passed`, 0 skipped. Falham:
- `test_os_termos_dizem_que_o_nif_da_conta_so_entra_na_fatura_se_o_cliente_disser_que_sim` → `assert '<strong>NIF na fatura.</strong> Se tiver NIF na conta, …' in '…'`
- `test_a_privacidade_diz_o_que_a_loja_recebe_da_app_quando_le_o_qr` → `assert 'Quando a caixa lê o seu QR, …' in '<!doctype html> …'`
- `test_a_data_da_pagina_e_a_versao_dos_termos_mudaram_juntas` → `AssertionError: o NIF da conta na caixa entrou na secção 4.2 a 24/10: …` / `assert '2026-10-14' == '2026-10-24'`

(O assert apertado em (a) passa já antes da mudança. É um reforço, não um teste novo.)

- [ ] **Step 3: Implement**

(a) `backend/legal_pages.py:43`. Antes:
```html
<h1>Política de Privacidade</h1>
<p class="updated">Última atualização: 17 de setembro de 2026</p>
```
depois:
```html
<h1>Política de Privacidade</h1>
<p class="updated">Última atualização: 24 de outubro de 2026</p>
```

(b) `backend/legal_pages.py:64-65`, fim do item «Pontos dados na caixa». Antes:
```html
receber a fatura dessa compra por email, guardamos essa escolha, o número do documento e
o momento do envio — para lhe enviarmos a fatura e podermos mostrar que foi enviada.</li>
<li><strong>Notificações:</strong> um identificador técnico do dispositivo (token) para
```
depois:
```html
receber a fatura dessa compra por email, guardamos essa escolha, o número do documento e
o momento do envio — para lhe enviarmos a fatura e podermos mostrar que foi enviada.
Quando a caixa lê o seu QR, a loja recebe da app o seu primeiro nome e, se tiver NIF na
conta, esse NIF. O NIF só entra na fatura dessa compra se o confirmar na caixa.</li>
<li><strong>Notificações:</strong> um identificador técnico do dispositivo (token) para
```

(c) `backend/legal_pages.py:183-184`. Antes:
```python
_TERMOS = """
<p class="updated">Última atualização: 14 de outubro de 2026</p>
```
depois:
```python
_TERMOS = """
<p class="updated">Última atualização: 24 de outubro de 2026</p>
```

(d) `backend/legal_pages.py:276-278`. Antes (a linha 276 é a da «Fatura por email», numa linha só):
```html
<p><strong>Fatura por email.</strong> Se, na caixa, escolher receber por email a fatura dessa compra, ela é enviada para o email da sua conta e <strong>não lhe é entregue talão em papel</strong>. A escolha <strong>vale apenas para essa compra</strong>: na seguinte volta a receber talão, a não ser que a faça outra vez. Antes de pagar, pode voltar ao papel dizendo-o na caixa; depois de pagar, pode pedir o talão em papel na loja. As notas de crédito são sempre entregues em papel.</p>

<h3>4.3 Ganhar pontos com pedidos na app</h3>
```
depois:
```html
<p><strong>Fatura por email.</strong> Se, na caixa, escolher receber por email a fatura dessa compra, ela é enviada para o email da sua conta e <strong>não lhe é entregue talão em papel</strong>. A escolha <strong>vale apenas para essa compra</strong>: na seguinte volta a receber talão, a não ser que a faça outra vez. Antes de pagar, pode voltar ao papel dizendo-o na caixa; depois de pagar, pode pedir o talão em papel na loja. As notas de crédito são sempre entregues em papel.</p>
<p><strong>NIF na fatura.</strong> Se tiver NIF na conta, a caixa pode perguntar-lhe se o quer na fatura. Só é usado se disser que sim e vale apenas para essa compra. Depois de emitida, a fatura não pode ser alterada.</p>

<h3>4.3 Ganhar pontos com pedidos na app</h3>
```
(Não se mexe no `_QR_NA_CAIXA` (≈527): só aparece com o «Ler fatura» desligado.)

(e) `backend/auth.py:344`. Antes:
```python
TERMOS_VERSAO = "2026-10-14"
```
depois:
```python
TERMOS_VERSAO = "2026-10-24"
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd /Users/matheus.moraes/applacai-nif-da-app/backend && PYTHONDONTWRITEBYTECODE=1 ~/applacai/backend/.venv/bin/python -m pytest tests/test_pos_integracao_unit.py tests/test_termos_unit.py tests/test_ponte_categorias_unit.py tests/test_registo_social_unit.py tests/test_nif_opcional_unit.py tests/test_canecas_rotas_unit.py -q -rs
```
Esperado: `223 passed`, 0 skipped. Baseline do branch para os mesmos 6 ficheiros: 218. Mais 3 da A1 e 2 da A2.

E o par de referência do spec:
```bash
cd /Users/matheus.moraes/applacai-nif-da-app/backend && PYTHONDONTWRITEBYTECODE=1 ~/applacai/backend/.venv/bin/python -m pytest tests/test_pos_integracao_unit.py tests/test_termos_unit.py -q
```
Esperado: `102 passed`, 0 skipped.

- [ ] **Step 5: Mutation check**: uma de cada vez, repondo depois de cada uma, e correr o comando de 6 ficheiros do Step 4:
  1. Apagar as duas linhas novas da Privacidade (as de «Quando a caixa lê o seu QR…») → vermelho `test_a_privacidade_diz_o_que_a_loja_recebe_da_app_quando_le_o_qr` (`1 failed, 222 passed`).
  2. Repor a data da Privacidade em «17 de setembro de 2026» → vermelho o mesmo teste (`1 failed, 222 passed`).
  3. Apagar a linha `<p><strong>NIF na fatura.</strong>…` → vermelho `test_os_termos_dizem_que_o_nif_da_conta_so_entra_na_fatura_se_o_cliente_disser_que_sim` (`1 failed, 222 passed`).
  4. Mudar esse parágrafo para o fim do `_QR_NA_CAIXA` → vermelho o mesmo teste, na volta `ler_fatura=True` (`1 failed, 222 passed`).
  5. Repor `TERMOS_VERSAO = "2026-10-14"` → vermelhos `test_a_data_da_pagina_e_a_versao_dos_termos_mudaram_juntas` e `test_a_versao_dos_termos_bate_com_a_pagina_que_e_servida` (`2 failed, 221 passed`).
  6. Repor a data dos Termos em «14 de outubro de 2026» → vermelhos os mesmos dois (`2 failed, 221 passed`).
  7. Na «Fatura por email», apagar `A escolha <strong>vale apenas para essa compra</strong>: na seguinte volta a receber talão, a não ser que a faça outra vez. ` → vermelho `test_os_termos_dizem_para_onde_vai_a_fatura_e_como_se_volta_ao_papel` (`1 failed`). Com o assert antigo (`"vale apenas para essa compra" in html`) esta mesma mutação dava `223 passed`. Medi-o, e é por isso que o assert foi apertado.

- [ ] **Step 6: Commit**

```bash
cd /Users/matheus.moraes/applacai-nif-da-app && git add backend/legal_pages.py backend/auth.py backend/tests/test_termos_unit.py backend/tests/test_ponte_categorias_unit.py && git commit -F - <<'EOF'
Privacidade e Termos dizem que a caixa recebe o NIF da conta e só o usa com um sim

A Privacidade (secção 1, «Pontos dados na caixa») passa a dizer o que a loja
recebe da app quando lê o QR: o primeiro nome e, se houver, o NIF da conta,
que só entra na fatura se o cliente o confirmar na caixa. Os Termos (secção
4.2) ganham o parágrafo «NIF na fatura», ao lado da «Fatura por email», que
aparece com o «Ler fatura» ligado e desligado.

O texto legal mudou, por isso as duas datas e a TERMOS_VERSAO mudam no mesmo
commit (24 de outubro de 2026 / "2026-10-24"). A asserção que fixa a versão em
test_ponte_categorias_unit.py acompanha.

O parágrafo novo repete «vale apenas para essa compra», o que deixava passar
o teste da fatura por email mesmo com a frase apagada desse parágrafo. Medi-o, e o
assert passa a incluir a marcação. Vi vermelho: ao tirar cada frase nova, ao repor cada
data, ao pôr o parágrafo só no _QR_NA_CAIXA e ao voltar a versão atrás.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```


---

### Task R1: O servidor do POS devolve o NIF da conta da app no «Ler» do QR

**Repo/worktree:** `/Users/matheus.moraes/Developer/RH-nif-da-app` (ramo `matheus-nif-da-app`)

**Files:**
- Modify: `backend/faturacao/pontos_app.py:10-15` (docstring do módulo), `:129-132` (helper novo a seguir a `PedidoLerQr`), `:189-191` (docstring da rota), `:228-232` (log da «resposta inesperada»), `:243-245` (resposta da rota)
- Test: `backend/tests/faturacao/test_os_pontos_da_app.py` (alterar 121-131; inserir depois de 158 e depois de 203)

**Interfaces:**
- Consumes: a chave `"nif"` da resposta de `POST {APP_LACAI_URL}/api/pos-integracao/ligar` (tarefa da app). Pode faltar: app antiga ou conta sem NIF. Também usa `faturacao.fiscal._nif_portugues_valido(digitos: str) -> bool`, importado dentro da função.
- Produces:
  - `faturacao.pontos_app._nif_da_app(cru) -> Optional[str]`
  - A resposta de `POST /api/faturacao/pos/pontos/ler` passa a ser **sempre** `{"ligacao_id": str, "primeiro_nome": str, "fatura_por_email": bool, "nif": Optional[str]}`.
  - `nif` são 9 algarismos ASCII com dígito de controlo válido, nunca `"999999990"`, ou `None`.
  - Não se grava em `fat_pontos_qr`, na venda nem no log.
  - É isto que `PosLerQr.js` / `lib/pos.js` (tarefas do ecrã) vão ler como `nif`.

- [ ] **Step 1: Write the failing test(s)**

1a. Em `backend/tests/faturacao/test_os_pontos_da_app.py`, substituir o corpo de `test_ler_o_qr_devolve_a_ligacao_o_primeiro_nome_e_o_SIM_NAO_do_email` (linhas 122-131). O nome fica igual.

Antes:
```python
    """A resposta tem TRÊS chaves e não duas — e o `False` aqui não é um
    pormenor: o corpo da app não trouxe `fatura_por_email` nenhum, e o que sai
    é o que FICOU GRAVADO em `fat_pontos_qr` (nada), nunca o que a app disse.

    Sem linha não se promete email: o cartão do Finalizar desenha-se pelo valor
    que sai daqui, e um cartão a dizer «Fatura por email» por cima de um talão
    a sair é o ecrã a mentir à funcionária."""
    app.responde(200, {"ligacao_id": "lig-1", "primeiro_nome": "Ana"})
    assert _ler(monkeypatch, _db_do_ler()) == {
        "ligacao_id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False}
```
Depois:
```python
    """A resposta tem QUATRO chaves, sempre — e o `False` aqui não é um
    pormenor: o corpo da app não trouxe `fatura_por_email` nenhum, e o que sai
    é o que FICOU GRAVADO em `fat_pontos_qr` (nada), nunca o que a app disse.

    Sem linha não se promete email: o cartão do Finalizar desenha-se pelo valor
    que sai daqui, e um cartão a dizer «Fatura por email» por cima de um talão
    a sair é o ecrã a mentir à funcionária.

    E o `nif` vem `None` em vez de faltar: uma app antiga (ou uma conta sem
    NIF) não manda nada, e o ecrã simplesmente não mostra o botão."""
    app.responde(200, {"ligacao_id": "lig-1", "primeiro_nome": "Ana"})
    assert _ler(monkeypatch, _db_do_ler()) == {
        "ligacao_id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False,
        "nif": None}
```

1b. Inserir depois de `test_ler_nao_grava_nada_na_venda` (a seguir à linha 158, `assert _corre(db[COLECOES["vendas"]].find_one({"id": "venda-1"})) == _venda_aberta()`) e antes de `def test_um_QR_recusado_pela_app_da_404_com_a_frase_da_funcionaria`:
```python


@pytest.mark.parametrize("nif_da_app, nif", [
    ("517542510", "517542510"),
    ("517 542 510", "517542510"),
    (517542510, "517542510"),
    (219363931, None),
    ("51754251X", None),
    ("٢١٩٣٦٣٩٣٥", None),
    (["517542510"], None),
    ({"nif": "517542510"}, None),
    (True, None),
    ("999999990", None),
    (None, None),
], ids=["nove_digitos", "com_espacos", "numero_inteiro", "o_telefone_de_Lisboa",
        "com_uma_letra", "algarismos_arabes", "lista", "objecto", "booleano",
        "consumidor_final", "nulo"])
def test_o_NIF_da_conta_so_chega_ao_ecra_se_for_um_NIF_que_a_fatura_aceita(
        monkeypatch, app, nif_da_app, nif):
    """O mesmo crivo do `nif` do finalizar (`fiscal._valida_nif`): só os
    algarismos do teclado — o `int()` do dígito de controlo rebentava com um
    «X» ou um «²», e aceitava os algarismos árabes, que chegavam ao ecrã como
    se fossem um NIF — e o dígito de controlo, que trava o telefone de Lisboa
    ditado como NIF.

    Uma lista ou um objecto passados a texto escondiam nove dígitos válidos, e
    o 999999990 é o «Consumidor Final» genérico: passa a conta, mas não é o NIF
    de ninguém.

    **Nada disto pode dar 500**: a app já gastou o QR do cliente quando
    chegamos aqui. Um NIF que não presta vale `None` — sem botão, a funcionária
    pergunta como sempre."""
    app.responde(200, {"ligacao_id": "lig-1", "primeiro_nome": "Ana", "nif": nif_da_app})
    assert _ler(monkeypatch, _db_do_ler())["nif"] == nif


def test_o_que_a_app_mandar_a_mais_nao_passa_para_o_ecra_da_caixa(monkeypatch, app):
    """A resposta monta-se campo a campo, e é isso que segura a privacidade do
    lado do servidor: o ecrã da caixa está virado para a fila, e o que a app
    mandar a mais — o email da conta, num deploy enganado — fica aqui. Até
    hoje só o banco de ensaio do ecrã o provava."""
    app.responde(200, {"ligacao_id": "lig-1", "primeiro_nome": "Ana",
                       "fatura_por_email": False, "nif": "517542510",
                       "email": "ana@exemplo.pt", "telefone": "+351912345678"})
    assert _ler(monkeypatch, _db_do_ler()) == {
        "ligacao_id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False,
        "nif": "517542510"}


def test_o_NIF_da_conta_nao_fica_gravado_nem_na_venda_nem_na_coleccao_do_qr(monkeypatch, app):
    """O NIF volta ao ecrã e a mais lado nenhum: só entra na fatura se o
    cliente o confirmar na caixa, e gravado aqui ficava preso a uma conta que
    pode nunca chegar a fatura — e a um cliente que disse que não."""
    app.responde(200, {"ligacao_id": "lig-1", "primeiro_nome": "Ana",
                       "fatura_por_email": True, "nif": "517542510"})
    db = _db_do_ler()

    assert _ler(monkeypatch, db)["nif"] == "517542510"

    assert _corre(db[COLECOES["vendas"]].find_one({"id": "venda-1"})) == _venda_aberta()
    [linha] = db[COLECOES["pontos_qr"]]._documentos
    assert "517542510" not in str(linha)
```
(A string `"٢١٩٣٦٣٩٣٥"` são os algarismos árabe-índicos U+0662… do mesmo exemplo de `fiscal.py:1983`. Tem de ser colada tal e qual, sem a passar a ASCII.)

1c. Inserir depois de `test_um_200_sem_a_forma_do_contrato_da_503` (a seguir à linha 203, `assert (e.value.status_code, e.value.detail) == (503, _MSG_APP)`) e antes de `@pytest.mark.parametrize("variavel", ["APP_LACAI_URL", "APP_LACAI_CHAVE"])`. O `logging` já está importado na linha 20.
```python


def test_a_resposta_inesperada_fica_no_log_com_as_CHAVES_e_sem_o_NIF(monkeypatch, app, caplog):
    """Um 200 sem `ligacao_id` é a app fora do contrato, e o pormenor fica no
    log — mas o pormenor é o estado HTTP e as CHAVES do corpo, nunca o texto:
    com o NIF a viajar na resposta do `ligar`, despejar o corpo metia-o no log."""
    app.responde(200, {"primeiro_nome": "Ana", "nif": "517542510"})
    with caplog.at_level(logging.ERROR, logger="faturacao.pontos_app"):
        with pytest.raises(HTTPException) as e:
            _ler(monkeypatch, _db_do_ler())
    assert (e.value.status_code, e.value.detail) == (503, _MSG_APP)
    assert "517542510" not in caplog.text and "Ana" not in caplog.text
    assert "HTTP 200" in caplog.text and "'nif', 'primeiro_nome'" in caplog.text
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /Users/matheus.moraes/Developer/RH-nif-da-app/backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/faturacao/test_os_pontos_da_app.py -q
```
Resultado esperado: `15 failed, 114 passed`, 0 skipped. Os motivos:
- `test_ler_o_qr_devolve_a_ligacao_o_primeiro_nome_e_o_SIM_NAO_do_email`: `AssertionError … Right contains 1 more item: {'nif': None}`
- os 11 casos de `test_o_NIF_da_conta_so_chega_ao_ecra_se_for_um_NIF_que_a_fatura_aceita[...]`: `KeyError: 'nif'`
- `test_o_que_a_app_mandar_a_mais_nao_passa_para_o_ecra_da_caixa`: `Right contains 1 more item: {'nif': '517542510'}`
- `test_o_NIF_da_conta_nao_fica_gravado_nem_na_venda_nem_na_coleccao_do_qr`: `KeyError: 'nif'`
- `test_a_resposta_inesperada_fica_no_log_com_as_CHAVES_e_sem_o_NIF`: `'517542510' is contained here: a","nif":"517542510"})`. O log antigo despeja `(HTTP 200): {"primeiro_nome":"Ana","nif":"517542510"}`.

- [ ] **Step 3: Implement**

Todas as alterações são em `backend/faturacao/pontos_app.py`.

3a. Docstring do módulo (linhas 10-15).

Antes:
```python
1. **Ler** (`POST /pos/pontos/ler`) — troca o código do QR por uma ligação na
   app e devolve só o primeiro nome e um sim/não à fatura por email. Não grava
   nada na VENDA — é o ecrã que guarda a ligação e a manda no finalizar
   (`fiscal.PedidoFinalizarVenda`) — mas grava a preferência do email em
   `fat_pontos_qr`, porque suprimir um documento fiscal não se decide por um
   campo do corpo de um pedido do browser.
```
Depois:
```python
1. **Ler** (`POST /pos/pontos/ler`) — troca o código do QR por uma ligação na
   app e devolve o primeiro nome, um sim/não à fatura por email e o NIF da
   conta (ou `None`), que só entra na fatura se o cliente o confirmar na
   caixa. Não grava nada na VENDA — é o ecrã que guarda a ligação e a manda no
   finalizar (`fiscal.PedidoFinalizarVenda`) — mas grava a preferência do
   email em `fat_pontos_qr`, porque suprimir um documento fiscal não se decide
   por um campo do corpo de um pedido do browser. O NIF não se grava em lado
   nenhum.
```

3b. Helper novo entre `PedidoLerQr` e `_gravar_qr_da_ligacao` (linhas 129-132).

Antes:
```python
    codigo: str = Field(min_length=1, max_length=200)


async def _gravar_qr_da_ligacao(db, ligacao_id: str, fatura_por_email: bool) -> bool:
```
Depois:
```python
    codigo: str = Field(min_length=1, max_length=200)


def _nif_da_app(cru) -> Optional[str]:
    """O NIF da conta da app, só se for um NIF que o finalizar aceitaria; senão
    `None`.

    **Nunca levanta**: quando chegamos aqui a app já gastou o QR do cliente, e
    um 500 era a funcionária a pedir-lhe um código novo que já não servia. Daí
    o tipo conferido primeiro (uma lista ou um objecto, passados a texto,
    escondiam nove dígitos) e o alfabeto de `fiscal._valida_nif` —
    `c in "0123456789"`, nunca `isdigit()` — antes do dígito de controlo, que
    faz `int()` a cada carácter.

    O 999999990 é o «Consumidor Final» genérico e passa o dígito de controlo:
    na conta de alguém não é um NIF. E o número nunca vai para o log."""
    # Importado aqui e não no topo: o `fiscal` só importa este módulo tarde, de
    # propósito, e um import de topo para o lado de lá podia fechar o ciclo.
    from .fiscal import _nif_portugues_valido

    if type(cru) not in (str, int):  # `bool` é um `int` em Python e fica de fora
        return None
    digitos = "".join(c for c in str(cru) if c in "0123456789")
    if digitos == "999999990" or not _nif_portugues_valido(digitos):
        return None
    return digitos


async def _gravar_qr_da_ligacao(db, ligacao_id: str, fatura_por_email: bool) -> bool:
```

3c. Docstring de `ler_qr_de_pontos` (linhas 189-195).

Antes:
```python
    **Não grava nada na venda.** A ligação volta ao ecrã, que a guarda presa ao
    id da conta e a manda no finalizar. Uma leitura que não acabe em fatura
    não deixa lixo em lado nenhum deste servidor.

    A loja e o operador vão pelo NOME e saem do TOKEN, nunca do corpo: são o
```
Depois:
```python
    **Não grava nada na venda.** A ligação volta ao ecrã, que a guarda presa ao
    id da conta e a manda no finalizar. Uma leitura que não acabe em fatura
    não deixa lixo em lado nenhum deste servidor.

    **O NIF da conta volta ao ecrã e a mais lado nenhum** (`_nif_da_app`): nem
    na venda, nem em `fat_pontos_qr`, nem no log. O ecrã esconde-o e só o põe
    no campo do NIF se a funcionária tocar no botão, depois de perguntar ao
    cliente; entra na fatura pelo `nif` de sempre do finalizar, que o valida
    outra vez.

    A loja e o operador vão pelo NOME e saem do TOKEN, nunca do corpo: são o
```

3d. O log da resposta inesperada (linhas 228-232).

Antes:
```python
        # 401 (chave trocada), 5xx, ou um 200 sem a forma do contrato: para a
        # funcionária é tudo «a app não está a responder»; o pormenor fica no log.
        logger.error(
            "[faturacao] ler QR de pontos (venda %s): resposta inesperada da app "
            "(HTTP %s): %s", dados.venda_id, resposta.status_code, resposta.text[:200])
        raise HTTPException(status_code=503, detail=_MSG_APP_INDISPONIVEL)
    ligacao_id = str(corpo["ligacao_id"])
```
Depois:
```python
        # 401 (chave trocada), 5xx, ou um 200 sem a forma do contrato: para a
        # funcionária é tudo «a app não está a responder»; o pormenor fica no log.
        # O estado e as CHAVES do corpo, nunca o texto: um 200 sem `ligacao_id`
        # pode trazer o NIF da conta, e o NIF não vai para o log.
        logger.error(
            "[faturacao] ler QR de pontos (venda %s): resposta inesperada da app "
            "(HTTP %s, chaves %s)", dados.venda_id, resposta.status_code,
            sorted(corpo) if isinstance(corpo, dict) else None)
        raise HTTPException(status_code=503, detail=_MSG_APP_INDISPONIVEL)
    ligacao_id = str(corpo["ligacao_id"])
```
O bloco antigo só existe uma vez. A rota `/pos/pontos/preferencia` tem uma frase parecida mas não igual (`"resposta inesperada da app (HTTP %s): %s", dados.venda_id,` + `dados.ligacao_id, …`), por isso a Edit não lhe toca.

3e. A resposta (linhas 243-245).

Antes:
```python
        "fatura_por_email": await _gravar_qr_da_ligacao(
            db, ligacao_id, bool(corpo.get("fatura_por_email"))),
    }
```
Depois:
```python
        "fatura_por_email": await _gravar_qr_da_ligacao(
            db, ligacao_id, bool(corpo.get("fatura_por_email"))),
        # Sempre presente, `None` quando não há. Só volta ao ecrã — ver a
        # docstring acima.
        "nif": _nif_da_app(corpo.get("nif")),
    }
```
Este bloco também só aparece uma vez. O `_apagar_qr_da_ligacao`/preferência usa outras variáveis.

- [ ] **Step 4: Run to verify it passes**

```bash
cd /Users/matheus.moraes/Developer/RH-nif-da-app/backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/faturacao/test_os_pontos_da_app.py -q
```
Esperado: `129 passed`, 0 skipped (eram 115; mais 14 testes novos).

Depois corre-se a pasta `faturacao` inteira, porque os testes de ecrã que fixam as formas do `onLigada`/gaveta não podem partir com esta tarefa:
```bash
cd /Users/matheus.moraes/Developer/RH-nif-da-app/backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/faturacao -q
```
Esperado: `3234 passed`, **0 skipped** (o ramo de partida dá `3220 passed`, 0 skipped). Se aparecer `skipped`, é o `frontend/node_modules` que falta.

- [ ] **Step 5: Mutation check**

Cada linha foi revertida à vez e verificada. Depois de cada mutação, voltar a pôr o código e correr de novo (tem de dar `129 passed`).

| Mutação em `pontos_app.py` | Fica vermelho |
|---|---|
| apagar `if type(cru) not in (str, int): … return None` | `…_que_a_fatura_aceita[lista]` e `[objecto]` |
| `if c in "0123456789")` → `if c.isdigit())` | `…[algarismos_arabes]` (`assert '٢١٩٣٦٣٩٣٥' == None`) |
| `digitos = "".join(…)` → `digitos = str(cru)` | `…[com_espacos]`, `[com_uma_letra]` (`ValueError: invalid literal for int() with base 10: 'X'`, ou seja o 500) e `[algarismos_arabes]` |
| tirar `digitos == "999999990" or ` | `…[consumidor_final]` |
| apagar a linha `"nif": _nif_da_app(corpo.get("nif")),` | `test_ler_o_qr_devolve_…_SIM_NAO_do_email`, os 11 casos parametrizados, `test_o_que_a_app_mandar_a_mais_…` e `test_o_NIF_da_conta_nao_fica_gravado_…` (14 vermelhos) |
| `"nif": _nif_da_app(corpo.get("nif"))` → `"nif": corpo.get("nif")` | 9 casos parametrizados (todos menos `nove_digitos` e `nulo`) |
| voltar a pôr `resposta.text[:200])` no log | `test_a_resposta_inesperada_fica_no_log_com_as_CHAVES_e_sem_o_NIF` |
| (injeção) acrescentar `"nif": "517542510",` ao `insert_one` de `_gravar_qr_da_ligacao` | `test_o_NIF_da_conta_nao_fica_gravado_nem_na_venda_nem_na_coleccao_do_qr` |

- [ ] **Step 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-nif-da-app && git add backend/faturacao/pontos_app.py backend/tests/faturacao/test_os_pontos_da_app.py && git commit -F - <<'EOF'
POS: o «Ler» do QR devolve o NIF da conta da app (ou None)

_nif_da_app só deixa passar 9 algarismos do teclado com o dígito de controlo
certo (nunca o 999999990) e nunca levanta — a app já gastou o QR. O NIF volta
ao ecrã e a mais lado nenhum: nem na venda, nem em fat_pontos_qr, nem no log
(a «resposta inesperada» passa a escrever o estado HTTP e as chaves do corpo
em vez do texto).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```


---

### Task R2: O NIF da leitura chega à gaveta dos pontos + as duas funções puras (máscara e «oferecer?»)

**Repo/worktree:** /Users/matheus.moraes/Developer/RH-nif-da-app

**Files:**
- Modify: `frontend/src/pages/pos/PosLerQr.js:150-157`
- Modify: `frontend/src/lib/pos.js:216-218` (new functions after `nifValidoPT`), `:239-257` (the `guardarPontosDaConta` whitelist and its comments), `:276-281` (the `lerQrDePontos` comment)
- Test: `backend/tests/faturacao/test_os_pontos_no_ecra_do_pos.py` (the `janela` fixture at 88-93, the test at 139-143, and the dicts at 340-341, 453-454, 592-593)
- Test: `backend/tests/faturacao/test_os_pontos_da_conta_no_pos.py` (header 13-20, plus new tests at the end of the file, after line 111)
- Test: `backend/tests/faturacao/test_a_fatura_por_email_no_ecra_do_pos.py` (72, 87, 90-93, 101-102, 189-190, 202-203, 221-222)

**Interfaces:**
- Consumes: the response of `POST /pos/pontos/ler` can bring `nif` (a string of 9 ASCII digits, or `null`/absent). That comes from the server task (`pontos_app.py::_nif_da_app`). The bench fakes the server, so this task does not depend on it to go green.
- Produces:
  - The `onLigada` payload of `PosLerQr` is ALWAYS `{ id, primeiro_nome, fatura_por_email: bool, nif: string|null }`, through both doors.
  - The `pos_pontos_da_conta` drawer: `.ligacao` has the same 4 keys, always present (`nif: null` when there is none).
  - `export const nifMascarado = (nif) => string`: `'219363935'` → `'2•• ••• •35'`; `''` when the input is not exactly 9 ASCII digits.
  - `export const nifDaAppParaOferecer = ({ ligacao, nifTexto }) => string|null`: returns the 9 digits only if `ligacao` exists, `ligacao.nif` is exactly 9 ASCII digits, `nifValidoPT(ligacao.nif)` passes and `nifTexto` has no digit at all. Otherwise `null`. An old drawer without `nif` gives `null`.

- [ ] **Step 1: Write the failing test(s)**

**1a.** `backend/tests/faturacao/test_os_pontos_no_ecra_do_pos.py`, `janela` fixture. Insert the new block right after the first block, the one that writes `saida.lido` (lines 88-93):

Before:
```python
        "    saida.lido = { ligadas: j.ligadas, corpos: j.lidos().map((p) => p.corpo) };",
        "    await j.fechar();",
        "  }",
        "  {",
        "    const j = await abrir(ANA);",
        "    await lerComOLeitor(j.alvo, '   ');",
```
After:
```python
        "    saida.lido = { ligadas: j.ligadas, corpos: j.lidos().map((p) => p.corpo) };",
        "    await j.fechar();",
        "  }",
        # A conta da app com NIF: o servidor manda-o na leitura.
        "  {",
        "    const j = await abrir(() => ({ data: { ligacao_id: 'lig-1', primeiro_nome: 'Ana',",
        "      nif: '219363935' } }));",
        "    await lerComOLeitor(j.alvo, %s);" % json.dumps(_CODIGO),
        "    saida.comNif = j.ligadas;",
        "    await j.fechar();",
        "  }",
        "  {",
        "    const j = await abrir(ANA);",
        "    await lerComOLeitor(j.alvo, '   ');",
```

**1b.** Same file, lines 139-146. Change the dict and add the new test before `test_um_Enter_sem_codigo_nao_pergunta_nada`:

Before:
```python
    assert janela["lido"]["ligadas"] == [
        {"id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False}]


def test_um_Enter_sem_codigo_nao_pergunta_nada(janela):
```
After:
```python
    assert janela["lido"]["ligadas"] == [
        {"id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False, "nif": None}]


def test_o_NIF_da_conta_que_o_servidor_manda_segue_para_o_Finalizar(janela):
    """As duas portas da leitura — o cartão e a pergunta do FINALIZAR — passam
    por este `onLigada`. Um `nif` que ficasse aqui pelo caminho apagava o botão
    «Usar o NIF da app» nas duas, sem uma palavra."""
    assert janela["comNif"] == [{"id": "lig-1", "primeiro_nome": "Ana",
                                 "fatura_por_email": False, "nif": "219363935"}]


def test_um_Enter_sem_codigo_nao_pergunta_nada(janela):
```

**1c.** Same file, three more exact dicts. Each is the closing line of a `== {` assert, at 341, 454 and 593 (before the edit in 1a/1b). They are identical, so make three separate edits, each with the line above it as context:

- line 340-341 (`lido["guardada"]`), line 453-454 (`parte_seguinte["guardadaNaPessoa1"]`), line 592-593 (`pergunta_lida["guardada"]`):

Before (each of the three):
```python
        "id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False}
```
After (each of the three):
```python
        "id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False, "nif": None}
```

**1d.** `backend/tests/faturacao/test_os_pontos_da_conta_no_pos.py`, header (lines 13-20):

Before:
```python
import json

from .test_a_faixa_do_modo_no_ecra import _montar_no_node

# Os TRÊS campos da gaveta. O `fatura_por_email` entrou a 2026-09-17 com a
# fatura por email e está sempre presente, mesmo a `False` — ver
# `lib/pos.js::guardarPontosDaConta`.
_ANA = {"id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False}
_CODIGO = "LQ7K2MN8P3QRSTUV4WXYZ9AB"
```
After:
```python
import json

import pytest

from .test_a_faixa_do_modo_no_ecra import _montar_no_node

# Os QUATRO campos da gaveta. O `fatura_por_email` entrou a 2026-09-17 com a
# fatura por email e o `nif` da conta da app a 2026-10-24; estão sempre
# presentes, mesmo a `False` e a `None` — ver `lib/pos.js::guardarPontosDaConta`.
_ANA = {"id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False, "nif": None}
# A mesma cliente, com NIF na conta da app: o telefone da queixa de 2026-09-11
# com o dígito de controlo certo (test_o_nif_que_nao_existe_no_pos.py).
_ANA_COM_NIF = dict(_ANA, nif="219363935")
_CODIGO = "LQ7K2MN8P3QRSTUV4WXYZ9AB"
```

**1e.** Same file, append at the end (after `assert saida["operador"] == "ot"`, line 111):
```python


def test_o_NIF_da_conta_da_app_fica_na_gaveta_da_MESMA_conta_e_so_dessa(tmp_path):
    """O NIF que o servidor mandou na leitura fica com a ligação, para o cartão
    Cliente o poder OFERECER — e morre com ela: outra conta não o vê."""
    saida = _correr("\n".join([
        "lib.guardarPontosDaConta('venda-1', %s);" % json.dumps(_ANA_COM_NIF),
        "process.stdout.write(JSON.stringify({",
        "  lida: lib.lerPontosDaConta('venda-1'), outra: lib.lerPontosDaConta('venda-2') }));",
    ]), tmp_path)
    assert saida["lida"] == _ANA_COM_NIF
    assert saida["outra"] is None


# --- O NIF da app no cartão Cliente: as duas decisões, corridas a sério -------


def _em_node(expressoes, tmp_path):
    """As funções REAIS do `lib/pos.js` sobre cada expressão, numa só viagem
    ao Node."""
    return _correr(
        "process.stdout.write(JSON.stringify([%s]));" % ", ".join(expressoes), tmp_path)


def test_a_mascara_mostra_so_o_primeiro_digito_e_os_dois_ultimos(tmp_path):
    """O ecrã da caixa está virado para a fila: chega para a funcionária
    confirmar «é este?», e o resto não se lê por cima do ombro."""
    assert _em_node(["lib.nifMascarado('219363935')", "lib.nifMascarado('517542510')"],
                    tmp_path) == ["2•• ••• •35", "5•• ••• •10"]


def test_a_mascara_de_um_numero_que_nao_tem_nove_digitos_nao_mostra_nada(tmp_path):
    """Uma máscara que deixasse passar o número inteiro não escondia coisa
    nenhuma — e com dez dígitos o `slice` dos dois últimos mostrava três."""
    assert _em_node([
        "lib.nifMascarado('')", "lib.nifMascarado(null)", "lib.nifMascarado(undefined)",
        "lib.nifMascarado('12345')", "lib.nifMascarado('2193639351')",
    ], tmp_path) == [""] * 5


def _oferece(ligacao, nif_texto):
    return "lib.nifDaAppParaOferecer({ ligacao: %s, nifTexto: %s })" % (
        json.dumps(ligacao), "undefined" if nif_texto is None else json.dumps(nif_texto))


def test_com_o_campo_do_NIF_vazio_oferece_se_o_NIF_da_app(tmp_path):
    """Vazio, só com espaços, ou nunca escrito: o botão aparece, com os nove
    dígitos que o toque vai pôr no campo."""
    assert _em_node([_oferece(_ANA_COM_NIF, ""), _oferece(_ANA_COM_NIF, "   "),
                     _oferece(_ANA_COM_NIF, None)], tmp_path) == ["219363935"] * 3


@pytest.mark.parametrize("ligacao, nif_texto", [
    (None, ""),                                   # nenhum QR lido nesta conta
    (_ANA, ""),                                   # a conta da app não tem NIF
    ({"id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False}, ""),  # gaveta antiga
    (dict(_ANA, nif="219363931"), ""),            # o telefone da queixa: não é NIF
    (dict(_ANA, nif="219 363 935"), ""),          # o servidor manda nove dígitos e mais nada
    (_ANA_COM_NIF, "5"),                          # um dígito escrito depois da leitura
    (_ANA_COM_NIF, "517 542 510"),                # o NIF ditado ANTES do QR
    (_ANA_COM_NIF, "219363935"),                  # o próprio, já no campo
])
def test_o_NIF_da_app_NAO_se_oferece(ligacao, nif_texto, tmp_path):
    """**Perguntar sempre, nunca tapar o que lá está.** Sem cliente lido, sem
    NIF que passe o dígito de controlo, ou com QUALQUER dígito no campo, não há
    botão: o que a operadora escreveu não se substitui por baixo dela, e um
    botão que pusesse um número inválido acendia o aviso vermelho do cartão."""
    assert _em_node([_oferece(ligacao, nif_texto)], tmp_path) == [None]
```

**1f.** `backend/tests/faturacao/test_a_fatura_por_email_no_ecra_do_pos.py`:
- line 72: `        # GAVETA: alimentada com os três campos limpos, um `{ ...ligacao }` lá` → `        # GAVETA: alimentada com os quatro campos limpos, um `{ ...ligacao }` lá`
- line 87: `    """**Os três campos, e só estes.** O `fatura_por_email` serve para desenhar` → `    """**Os quatro campos, e só estes.** O `fatura_por_email` serve para desenhar`
- line 91: `        {"id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": True}]` → `        {"id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": True, "nif": None}]`
- line 93: `        "id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": True}` → `        "id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": True, "nif": None}`
- line 102: `        "id": "lig-2", "primeiro_nome": "Ana", "fatura_por_email": True}` → `        "id": "lig-2", "primeiro_nome": "Ana", "fatura_por_email": True, "nif": None}`
- lines 190, 203, 222: each is `        "id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False}`, and each becomes `        "id": "lig-1", "primeiro_nome": "Ana", "fatura_por_email": False, "nif": None}`. These are the closing lines of `cartao["guardada"] == {`, `cartao["guardadaDepois"] == {` and `cartao["guardadaDivergente"] == {`.

(Mechanical equivalent of 1c and the 1f dicts, with the counts checked. This is what was run in the verification.)
```bash
cd /Users/matheus.moraes/Developer/RH-nif-da-app/backend/tests/faturacao && python3 - <<'EOF'
import re
for nome, n in {"test_os_pontos_no_ecra_do_pos.py": 4, "test_os_pontos_da_conta_no_pos.py": 1,
                "test_a_fatura_por_email_no_ecra_do_pos.py": 6}.items():
    s = open(nome, encoding="utf-8").read()
    s, feitas = re.subn(r'"fatura_por_email": (True|False)\}', r'"fatura_por_email": \1, "nif": None}', s)
    assert feitas == n, (nome, feitas)
    open(nome, "w", encoding="utf-8").write(s)
EOF
```
Run this BEFORE 1d. If you run it after, `_ANA` already has `"nif": None` and the count for that file comes out 0.

- [ ] **Step 2: Run to verify it fails**

```bash
cd /Users/matheus.moraes/Developer/RH-nif-da-app/backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/faturacao/test_os_pontos_no_ecra_do_pos.py tests/faturacao/test_os_pontos_da_conta_no_pos.py tests/faturacao/test_a_fatura_por_email_no_ecra_do_pos.py -q
```
Expected: `25 failed, 61 passed`. The failures are for the right reasons:
- `TypeError: lib.nifMascarado is not a function` (and the same for `nifDaAppParaOferecer`) in the 12 new pure-function tests.
- `Right contains 1 more item: {'nif': None}` (or `{'nif': '219363935'}`) in the exact dicts.
- `At index 0 diff: {... 'fatura_por_email': False} != {..., 'nif': '219363935'}` in `test_o_NIF_da_conta_que_o_servidor_manda_segue_para_o_Finalizar`.

- [ ] **Step 3: Implement**

**3a.** `frontend/src/pages/pos/PosLerQr.js:150-157`

Before:
```js
      const { ligacao_id: id, primeiro_nome, fatura_por_email } =
        await lerQrDePontos(vendaId, lido);
      // A guarda do ecrã já fechado vem do caminho dos pontos e vale igual aqui:
      // sem ela, um QR lido mesmo antes de sair do ecrã chamava o `onLigada` de
      // um componente que já não existe. O `catch` abaixo tem a mesma.
      if (!vivo.current) return;
      APITO_LIDO();
      onLigada({ id, primeiro_nome, fatura_por_email: !!fatura_por_email });
```
After:
```js
      const { ligacao_id: id, primeiro_nome, fatura_por_email, nif } =
        await lerQrDePontos(vendaId, lido);
      // A guarda do ecrã já fechado vem do caminho dos pontos e vale igual aqui:
      // sem ela, um QR lido mesmo antes de sair do ecrã chamava o `onLigada` de
      // um componente que já não existe. O `catch` abaixo tem a mesma.
      if (!vivo.current) return;
      APITO_LIDO();
      // O `nif` é o da conta da app, e só OFERECE o botão do cartão Cliente:
      // ler o QR nunca o põe na fatura (ver `lib/pos.js::nifDaAppParaOferecer`).
      onLigada({ id, primeiro_nome, fatura_por_email: !!fatura_por_email, nif: nif || null });
```

**3b.** `frontend/src/lib/pos.js`, after `nifValidoPT` (lines 215-218):

Before:
```js
  return (resto < 2 ? 0 : 11 - resto) === Number(digitos[8]);
};

// --- Os pontos L'Açaí da conta -----------------------------------------------
```
After:
```js
  return (resto < 2 ? 0 : 11 - resto) === Number(digitos[8]);
};

// **O NIF da conta da app, escondido.** O ecrã da caixa está virado para a
// fila: o primeiro dígito e os dois últimos chegam para a funcionária
// confirmar «é este?», e o resto não se lê por cima do ombro de ninguém.
// Fora de nove dígitos não mostra nada — uma máscara que deixasse passar um
// número inteiro não escondia coisa nenhuma.
export const nifMascarado = (nif) => {
  const digitos = String(nif || '');
  return /^\d{9}$/.test(digitos) ? `${digitos[0]}•• ••• •${digitos.slice(7)}` : '';
};

// **O botão «Usar o NIF da app» aparece?** Devolve os nove dígitos quando há
// cliente lido NESTA conta, o NIF da conta dele passa o dígito de controlo e o
// campo do NIF não tem dígito nenhum; senão `null`.
//
// Perguntar sempre, nunca preencher sozinho (decisão do dono): muitos clientes
// não querem NIF na fatura, e uma FS com um NIF que ninguém pediu só se
// corrige com nota de crédito. Com qualquer dígito no campo — ditado antes do
// QR, ou escrito depois — não se oferece nada: o que a operadora escreveu não
// se tapa. Uma gaveta de antes desta versão não tem `nif` e dá `null`.
export const nifDaAppParaOferecer = ({ ligacao, nifTexto }) => {
  const nif = ligacao ? String(ligacao.nif || '') : '';
  return /^\d{9}$/.test(nif) && nifValidoPT(nif) && !/\d/.test(String(nifTexto || ''))
    ? nif : null;
};

// --- Os pontos L'Açaí da conta -----------------------------------------------
```

**3c.** `frontend/src/lib/pos.js`, `guardarPontosDaConta` (lines 239-257):

Before:
```js
    // **Campo a campo, e nunca `{ ...ligacao }`.** São estes três e mais
    // nenhum: o endereço de email do cliente não entra aqui, nem hoje (o
    // servidor não o manda) nem no dia em que alguém o acrescentar do outro
    // lado — o `sessionStorage` do POS é lido por tudo o que corra naquela aba.
    //
    // O `fatura_por_email` é a preferência DAQUELA leitura e serve SÓ para
```
After:
```js
    // **Campo a campo, e nunca `{ ...ligacao }`.** São estes quatro e mais
    // nenhum: o endereço de email do cliente não entra aqui, nem hoje (o
    // servidor não o manda) nem no dia em que alguém o acrescentar do outro
    // lado — o `sessionStorage` do POS é lido por tudo o que corra naquela aba.
    //
    // O `nif` é o da conta da app, inteiro, e fica SÓ aqui: o ecrã mostra-o
    // mascarado (`nifMascarado`) e ele só entra na fatura se a operadora tocar
    // no botão — e aí vai pela gaveta do NIF, como um NIF ditado.
    //
    // O `fatura_por_email` é a preferência DAQUELA leitura e serve SÓ para
```
Before:
```js
    // **Está SEMPRE presente, mesmo a `false`.** Uma forma que mudasse com a
    // resposta do servidor punha o ecrã a ter de distinguir «não vai por
    // email» de «esta gaveta é de uma versão antiga» — e essa é a distinção
    // que ninguém faz bem às três da tarde.
    ligacao: ligacao ? {
      id: ligacao.id,
      primeiro_nome: ligacao.primeiro_nome,
      fatura_por_email: !!ligacao.fatura_por_email,
    } : null,
```
After:
```js
    // **Estão SEMPRE presentes, mesmo a `false` ou a `null`.** Uma forma que
    // mudasse com a resposta do servidor punha o ecrã a ter de distinguir «não
    // vai por email» de «esta gaveta é de uma versão antiga» — e essa é a
    // distinção que ninguém faz bem às três da tarde.
    ligacao: ligacao ? {
      id: ligacao.id,
      primeiro_nome: ligacao.primeiro_nome,
      fatura_por_email: !!ligacao.fatura_por_email,
      nif: ligacao.nif || null,
    } : null,
```

**3d.** `frontend/src/lib/pos.js:276-281`

Before:
```js
// `POST /pos/pontos/ler` → `{ ligacao_id, primeiro_nome, fatura_por_email }`.
// 404 é QR recusado e 503 é a app em baixo; as frases vêm no `detail`. A conta
// vai no pedido para o servidor confirmar que está aberta e é desta loja.
//
// O `fatura_por_email` é o sim/não da preferência daquele cliente — **e é só
// isso que vem**: o endereço nunca sai da app, nem mascarado.
```
After:
```js
// `POST /pos/pontos/ler` → `{ ligacao_id, primeiro_nome, fatura_por_email, nif }`.
// 404 é QR recusado e 503 é a app em baixo; as frases vêm no `detail`. A conta
// vai no pedido para o servidor confirmar que está aberta e é desta loja.
//
// O `fatura_por_email` é o sim/não da preferência daquele cliente — **e o
// endereço nunca sai da app**, nem mascarado. O `nif` é o da conta (ou `null`)
// e vem inteiro, porque é para entrar num documento fiscal; quem o esconde é o
// ecrã (`nifMascarado`).
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd /Users/matheus.moraes/Developer/RH-nif-da-app/backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/faturacao/test_os_pontos_no_ecra_do_pos.py tests/faturacao/test_os_pontos_da_conta_no_pos.py tests/faturacao/test_a_fatura_por_email_no_ecra_do_pos.py tests/faturacao/test_o_cartao_do_voucher_no_pos.py tests/faturacao/test_o_nif_que_nao_existe_no_pos.py tests/faturacao/test_o_nif_da_conta_no_pos.py tests/faturacao/test_o_dividir_e_o_separar_no_ecra.py -q
```
Expected: `151 passed`, with no `skipped` (the baseline of these 7 screen files is 138, and this task adds 13). With `tests/faturacao/test_os_pontos_da_app.py` included, the count is 266 if the server task has not landed yet; if it has, add its new tests. Read `passed` and `skipped`: without `frontend/node_modules` everything gives SKIP.

- [ ] **Step 5: Mutation check** (one at a time, revert after each)

| Mutation | Expected red test |
|---|---|
| `PosLerQr.js`: `onLigada({ id, primeiro_nome, fatura_por_email: !!fatura_por_email, nif: nif \|\| null });` → `onLigada({ id, primeiro_nome, fatura_por_email: !!fatura_por_email });` | `test_os_pontos_no_ecra_do_pos.py::test_o_NIF_da_conta_que_o_servidor_manda_segue_para_o_Finalizar` |
| `lib/pos.js`: delete the line `      nif: ligacao.nif \|\| null,` | `test_os_pontos_da_conta_no_pos.py::test_o_NIF_da_conta_da_app_fica_na_gaveta_da_MESMA_conta_e_so_dessa` (and the exact dicts) |
| `lib/pos.js`: delete ` && !/\d/.test(String(nifTexto \|\| ''))` | `test_o_NIF_da_app_NAO_se_oferece[ligacao5-5]`, `[ligacao6-517 542 510]`, `[ligacao7-219363935]` |
| `lib/pos.js`: `/^\d{9}$/.test(nif) && nifValidoPT(nif)` → `nifValidoPT(nif)` | `test_o_NIF_da_app_NAO_se_oferece[ligacao4-]` |
| `lib/pos.js`: `/^\d{9}$/.test(nif) && nifValidoPT(nif)` → `/^\d{9}$/.test(nif)` | `test_o_NIF_da_app_NAO_se_oferece[ligacao3-]` |
| `lib/pos.js` (`nifMascarado`): `return /^\d{9}$/.test(digitos) ? \`...\` : '';` → `return \`${digitos[0]}•• ••• •${digitos.slice(7)}\`;` | `test_a_mascara_de_um_numero_que_nao_tem_nove_digitos_nao_mostra_nada` |

(All verified red in the throwaway worktree.)

- [ ] **Step 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-nif-da-app
git add frontend/src/pages/pos/PosLerQr.js frontend/src/lib/pos.js \
  backend/tests/faturacao/test_os_pontos_no_ecra_do_pos.py \
  backend/tests/faturacao/test_os_pontos_da_conta_no_pos.py \
  backend/tests/faturacao/test_a_fatura_por_email_no_ecra_do_pos.py
git commit -m "$(cat <<'EOF'
POS: o NIF da conta da app chega à gaveta dos pontos, mais a máscara

O PosLerQr passa o `nif` da leitura ao onLigada (as duas portas, o
cartão e a pergunta do FINALIZAR, passam por ali) e a gaveta
pos_pontos_da_conta guarda-o, com a forma sempre presente (`null` sem
NIF). Duas funções puras no lib/pos.js: nifMascarado ('219363935' →
'2•• ••• •35') e nifDaAppParaOferecer (só com QR lido nesta conta, NIF
de nove dígitos que passa o controlo e o campo do NIF sem dígitos).
Os dicionários exatos do banco de ensaio passam a ter `nif`.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task R3: O ecrã de pagamento, com o botão «Usar o NIF da app · máscara» no cartão Cliente

**Repo/worktree:** /Users/matheus.moraes/Developer/RH-nif-da-app

**Files:**
- Modify: `frontend/src/pages/pos/PosFinalizar.js:21` (import), `:425` (the `CartaoCliente` signature and header comment), `:466-470` (title + new button), `:1297-1301` (`removerOCliente`), `:1399` (`nifDaApp`), `:1785` (render of `CartaoCliente`)
- Test: `backend/tests/faturacao/test_o_nif_da_app_no_pos.py` (NEW)
- `PosVenda.js`: NO changes. It is pinned by the dividir/separar tests below.

**Interfaces:**
- Consumes (from R2): `nifMascarado`, `nifDaAppParaOferecer`, and `ligacao.nif` in the drawer and in `onLigada`.
- Produces:
  - `CartaoCliente` gets three new props: `nifDaApp` (string|null), `nifDaLigacao` (`ligacao?.nif`) and `onUsarNifDaApp` (`() => setNifTexto(nifDaApp)`).
  - The button text is exactly `Usar o NIF da app · ${nifMascarado(nifDaApp)}`. This is the ASCII fragment «Usar o NIF da app» used for the post-deploy check of the served bundle.
  - The EMITIR body keeps its shape: `nif: digitosNif || null` and `pontos_ligacao: { id, primeiro_nome } | null`. The NIF NEVER goes inside `pontos_ligacao`.

- [ ] **Step 1: Write the failing test(s)**: create `backend/tests/faturacao/test_o_nif_da_app_no_pos.py` with exactly:

```python
"""**O NIF da conta da app no cartão Cliente** — montado e tocado, não lido.

Cerca de um terço das faturas das lojas leva NIF, e o NIF é sempre ditado e
escrito à mão: é por aí que entram os enganos (um telefone escrito como NIF
dava uma recusa do Vendus por dia). Quem mostra o QR da app na caixa já tem,
muitas vezes, o NIF na conta — e a leitura passa a trazê-lo.

As decisões do dono que isto guarda (spec de 2026-10-24):

- **perguntar sempre, nunca preencher sozinho** — um botão «Usar o NIF da app
  · 2•• ••• •35» no cartão Cliente, e uma fatura sem toque sai sem NIF;
- **o NIF aparece escondido**, no botão e no cartão depois do toque: o ecrã da
  caixa está virado para a fila;
- **o «Remover» tira o NIF se ainda for o da app**, e deixa ficar o que a
  operadora mudou;
- **um NIF já escrito não se tapa**, e uma conta repartida não o passa às
  partes.

Pelo `PosVenda` montado e pelas DUAS portas da leitura — o «Ler QR do cliente»
do cartão e a pergunta do FINALIZAR —, com o servidor fabricado à frente do
axios: o que se afirma é o que a operadora LÊ e o CORPO do EMITIR.
"""
import json

import pytest

from .test_o_dividir_e_o_separar_no_ecra import (
    _COOKIE, _L_ACAI, _L_COOKIE, _conta, _correr, _linha)
from .test_os_pontos_no_ecra_do_pos import (
    _CODIGO, _EMITIR, _PARTE_ACAI, _PARTE_COOKIE, _RESTO, _na_pergunta, _no_finalizar)

# O telefone da queixa de 2026-09-11 com o dígito de controlo certo
# (test_o_nif_que_nao_existe_no_pos.py) — e um segundo NIF, o que a operadora
# escreve à mão.
_NIF = "219363935"
_MASCARA = "2•• ••• •35"
_OUTRO_NIF = "517542510"

_LER_COM_NIF = (
    "RESPOSTAS_POS['POST /pos/pontos/ler'] = () => ({ data: {"
    " ligacao_id: 'lig-1', primeiro_nome: 'Ana', fatura_por_email: false,"
    " nif: %s } });" % json.dumps(_NIF))

# O cartão Cliente SOZINHO — a secção com o título «Cliente». «Consumidor
# Final» também é um botão do editor, e um guarda que lesse o ecrã inteiro
# media outra coisa.
_OLHAR = "\n".join([
    "const seccaoCliente = () => [...alvo.querySelectorAll('section')].find(",
    "  (s) => (s.querySelector('p') || {}).textContent === 'Cliente');",
    "const cartaoCliente = () => {",
    "  const el = seccaoCliente();",
    "  if (!el) throw new Error('sem cartão Cliente no ecrã: '",
    "    + textoVisivel(alvo).slice(0, 400));",
    "  return textoVisivel(el);",
    "};",
])

# As DUAS portas. Pelo cartão, o `_arranque` já respondeu «Não» à pergunta e a
# operadora carrega em «Ler QR do cliente»; pela pergunta, o QR lê-se na
# janela que o FINALIZAR abre e o ecrã de pagamento apanha a ligação da gaveta
# ao montar. São caminhos diferentes até ao `CartaoCliente`, e só um deles
# passa pelo `onLigada` do `PosFinalizar`.
_PORTAS = {
    "cartao": (_no_finalizar, "await carregar_em('Ler QR do cliente');"),
    "pergunta": (_na_pergunta, ""),
}


def _lido_com_nif(porta, extra=""):
    arranque, abrir = _PORTAS[porta]
    return "\n".join([
        arranque("\n".join([_LER_COM_NIF, extra])),
        _OLHAR,
        abrir,
        "await lerComOLeitor(alvo, %s);" % json.dumps(_CODIGO),
    ])


@pytest.fixture(scope="module", params=sorted(_PORTAS))
def sem_toque(request, tmp_path_factory):
    """O QR lido, o botão à vista — e ninguém lhe toca."""
    return _correr("\n".join([
        _lido_com_nif(request.param),
        "const noCartao = cartaoCliente();",
        "const visivel = textoVisivel(alvo);",
        "const html = alvo.innerHTML;",
        _EMITIR,
        "process.stdout.write(JSON.stringify({ noCartao, visivel, html, emitirVivo, corpos }));",
    ]), tmp_path_factory, "nif-da-app-sem-toque-" + request.param)


@pytest.fixture(scope="module", params=sorted(_PORTAS))
def com_toque(request, tmp_path_factory):
    """O QR lido e o cliente a dizer que sim: um toque no botão."""
    return _correr("\n".join([
        _lido_com_nif(request.param),
        "await carregar_em('Usar o NIF da app');",
        "const noCartao = cartaoCliente();",
        "const visivel = textoVisivel(alvo);",
        "const html = alvo.innerHTML;",
        "const nifGuardado = lib.lerNifDaConta('v-1');",
        _EMITIR,
        "process.stdout.write(JSON.stringify({",
        "  noCartao, visivel, html, nifGuardado, emitirVivo, corpos }));",
    ]), tmp_path_factory, "nif-da-app-com-toque-" + request.param)


def test_o_botao_aparece_com_o_NIF_ESCONDIDO_e_o_numero_inteiro_nao_esta_no_ecra(sem_toque):
    """O ecrã da caixa está virado para a fila: o número inteiro não se lê, nem
    junto nem aos grupos de três — e não está no DOM, nem num atributo."""
    assert "Usar o NIF da app · " + _MASCARA in sem_toque["noCartao"], sem_toque["noCartao"]
    assert "Consumidor Final" in sem_toque["noCartao"], sem_toque["noCartao"]
    for inteiro in (_NIF, "219 363 935"):
        assert inteiro not in sem_toque["visivel"], sem_toque["visivel"][:600]
        assert inteiro not in sem_toque["html"]


def test_sem_tocar_no_botao_a_fatura_sai_SEM_NIF(sem_toque):
    """**Perguntar sempre, nunca preencher sozinho.** Muitos clientes não
    querem NIF na fatura, e uma Fatura Simplificada com um NIF que ninguém
    pediu só se corrige com nota de crédito. Os pontos seguem na mesma."""
    assert sem_toque["emitirVivo"] is True
    assert len(sem_toque["corpos"]) == 1, sem_toque["corpos"]
    corpo = sem_toque["corpos"][0]
    assert corpo["nif"] is None, corpo
    assert corpo["pontos_ligacao"] == {"id": "lig-1", "primeiro_nome": "Ana"}, corpo


def test_um_toque_poe_o_NIF_da_app_no_cartao_e_ele_continua_ESCONDIDO(com_toque):
    """Depois do toque o cartão diz que há NIF — mascarado, como no botão — e o
    botão sai. O NIF fica na gaveta do NIF desta conta, como um NIF ditado: é
    isso que o faz sobreviver a voltar à conta para juntar mais um artigo."""
    assert _MASCARA in com_toque["noCartao"], com_toque["noCartao"]
    assert "Usar o NIF da app" not in com_toque["noCartao"], com_toque["noCartao"]
    assert "Consumidor Final" not in com_toque["noCartao"], com_toque["noCartao"]
    for inteiro in (_NIF, "219 363 935"):
        assert inteiro not in com_toque["visivel"], com_toque["visivel"][:600]
        assert inteiro not in com_toque["html"]
    assert com_toque["nifGuardado"] == _NIF


def test_depois_do_toque_o_EMITIR_leva_o_NIF_no_campo_de_sempre_e_nunca_nos_pontos(com_toque):
    """O NIF viaja no `nif` de sempre e o servidor valida-o como a qualquer
    outro (`fiscal.py::_valida_nif`). O `pontos_ligacao` continua a ser os dois
    campos de sempre: um NIF lá dentro ficava gravado na venda."""
    assert com_toque["emitirVivo"] is True
    assert len(com_toque["corpos"]) == 1, com_toque["corpos"]
    corpo = com_toque["corpos"][0]
    assert corpo["nif"] == _NIF, corpo
    assert corpo["pontos_ligacao"] == {"id": "lig-1", "primeiro_nome": "Ana"}, corpo


# --- O «Remover» do cartão dos pontos -----------------------------------------


@pytest.fixture(scope="module")
def remover_sem_mexer(tmp_path_factory):
    """O NIF da app usado, e o cliente tirado da fatura logo a seguir."""
    return _correr("\n".join([
        _lido_com_nif("cartao"),
        "await carregar_em('Usar o NIF da app');",
        "await carregar_em('Remover');",
        "const noCartao = cartaoCliente();",
        "const visivel = textoVisivel(alvo);",
        "const nifGuardado = lib.lerNifDaConta('v-1');",
        _EMITIR,
        "process.stdout.write(JSON.stringify({",
        "  noCartao, visivel, nifGuardado, emitirVivo, corpos }));",
    ]), tmp_path_factory, "nif-da-app-remover")


@pytest.fixture(scope="module")
def remover_editado(tmp_path_factory):
    """O NIF da app usado e depois MUDADO pela operadora (o cliente quis o da
    empresa), e só então o «Remover»."""
    return _correr("\n".join([
        # O editor do NIF usa o teclado do PosCampoValor, que o preâmbulo
        # substitui por uma marca; sem o verdadeiro, abrir o lápis rebentava.
        # Antes do `_arranque`, que é onde o PosFinalizar carrega.
        "SUBSTITUIDOS.delete(path.join(POS, 'PosCampoValor.js'));",
        _lido_com_nif("cartao"),
        "await carregar_em('Usar o NIF da app');",
        # O lápis do cartão Cliente: o `Botao` do banco de ensaio deita fora o
        # `aria-label`, por isso apanha-se pelo ícone, dentro da secção.
        "const lapis = seccaoCliente().querySelector('[data-icone=\"Pencil\"]').closest('button');",
        "await act(async () => { lapis.click(); });",
        "const noEditor = alvo.querySelector('#nif-cliente').value;",
        "await act(async () => { escrever(alvo.querySelector('#nif-cliente'), %s); });"
        % json.dumps(_OUTRO_NIF),
        # O «Confirmar» DO CARTÃO, e não o primeiro do ecrã com essa palavra.
        "const confirmar = [...seccaoCliente().querySelectorAll('button')].find(",
        "  (b) => (b.textContent || '').includes('Confirmar'));",
        "await act(async () => { confirmar.click(); });",
        "const editorFechado = !alvo.querySelector('#nif-cliente');",
        "await carregar_em('Remover');",
        "const noCartao = cartaoCliente();",
        _EMITIR,
        "process.stdout.write(JSON.stringify({",
        "  noEditor, editorFechado, noCartao, emitirVivo, corpos }));",
    ]), tmp_path_factory, "nif-da-app-remover-editado")


def test_o_Remover_tira_tambem_o_NIF_da_app_que_ninguem_mexeu(remover_sem_mexer):
    """Tirar o cliente da fatura e deixar lá o NIF dele era meia remoção: a
    fatura saía em nome de quem a funcionária acabou de tirar."""
    r = remover_sem_mexer
    assert "Consumidor Final" in r["noCartao"], r["noCartao"]
    assert _MASCARA not in r["visivel"], r["visivel"][:600]
    assert "Usar o NIF da app" not in r["visivel"], r["visivel"][:600]
    assert r["nifGuardado"] == ""
    assert r["corpos"][0]["nif"] is None, r["corpos"][0]
    assert r["corpos"][0]["pontos_ligacao"] is None, r["corpos"][0]


def test_o_Remover_deixa_ficar_o_NIF_que_a_operadora_MUDOU(remover_editado):
    """Um NIF mudado à mão deixou de ser o da app: é da operadora, e o
    «Remover» dos pontos não lhe toca. E o lápis mostra os dígitos — abri-lo é
    uma acção explícita, e é lá que ela os confirma com o cliente."""
    r = remover_editado
    assert r["noEditor"] == _NIF
    assert r["editorFechado"] is True
    assert "517 542 510" in r["noCartao"], r["noCartao"]
    assert r["corpos"][0]["nif"] == _OUTRO_NIF, r["corpos"][0]
    assert r["corpos"][0]["pontos_ligacao"] is None, r["corpos"][0]


# --- Um NIF já escrito não se tapa --------------------------------------------


@pytest.fixture(scope="module")
def nif_escrito_antes(tmp_path_factory):
    """O cliente ditou um NIF ANTES de mostrar a app."""
    return _correr("\n".join([
        _lido_com_nif("cartao", "lib.guardarNifDaConta('v-1', %s);" % json.dumps(_OUTRO_NIF)),
        "const noCartao = cartaoCliente();",
        "const visivel = textoVisivel(alvo);",
        _EMITIR,
        "process.stdout.write(JSON.stringify({ noCartao, visivel, emitirVivo, corpos }));",
    ]), tmp_path_factory, "nif-da-app-escrito-antes")


def test_com_um_NIF_ja_escrito_nao_ha_botao_e_a_fatura_leva_o_ESCRITO(nif_escrito_antes):
    """O que a operadora escreveu não se substitui por baixo dela — nem com um
    botão a convidar a isso. E de propósito sem aviso nenhum sobre a diferença
    (decisão do dono)."""
    r = nif_escrito_antes
    assert "Pontos para: Ana ✓" in r["visivel"], r["visivel"][:600]
    assert "Usar o NIF da app" not in r["visivel"], r["visivel"][:600]
    assert "517 542 510" in r["noCartao"], r["noCartao"]
    assert r["corpos"][0]["nif"] == _OUTRO_NIF, r["corpos"][0]


# --- A conta que se PARTE não passa o NIF da app às partes ---------------------
#
# **Nada disto é código novo no `PosVenda`, e é por isso que precisa de guarda.**
# `esquecerOsPontosDaMae` apaga a ligação (e o `nif` vai com ela), e a gaveta
# do NIF tem uma entrada só: montar o ecrã de pagamento de uma parte grava lá
# `{parte, ''}` por cima do NIF da mãe. Qualquer refactor de uma das duas
# gavetas reabria a fuga — o NIF de quem mostrou a app na fatura de outra
# pessoa — sem uma linha deste ficheiro a mudar.

_P1_EMITIDA = dict(
    _conta("p-1", [_linha("x1", "p-cookie", _COOKIE, 3.80)], estado="emitida", mae="v-1"),
    documento={"id": "d-2", "numero": "FS 01P2026/98", "atcud": "A-98",
               "total": 3.80, "modo": "normal", "vendus_document_id": 2},
)

_EMITIR_A_PARTE = "\n".join([
    "await carregar_em('Dinheiro');",
    "await carregar_em('EMITIR DOCUMENTO');",
    "await act(async () => {});",
])


@pytest.fixture(scope="module")
def dividir_depois_do_toque(tmp_path_factory):
    """Pela pergunta do FINALIZAR: o QR lido, o NIF da app usado, e a conta
    dividida."""
    return _correr("\n".join([
        _lido_com_nif("pergunta", "\n".join([
            "RESPOSTAS_POS['POST /pos/venda/v-1/dividir'] = () => ({ data: %s });"
            % json.dumps({
                "modo": "dividir",
                "conta_mae": _conta("v-1", [_L_COOKIE, _L_ACAI], estado="separada"),
                "partes": [_PARTE_COOKIE, _PARTE_ACAI],
            }, ensure_ascii=False),
            "RESPOSTAS_POS['POST /pos/venda/p-1/finalizar'] = () => ({ data: %s });"
            % json.dumps(_P1_EMITIDA, ensure_ascii=False),
        ])),
        "await carregar_em('Usar o NIF da app');",
        "const naMae = cartaoCliente();",
        "await carregar_em('Dividir Conta');",
        "const naParte = cartaoCliente();",
        "const visivelNaParte = textoVisivel(alvo);",
        _EMITIR_A_PARTE,
        "process.stdout.write(JSON.stringify({ naMae, naParte, visivelNaParte,",
        "  corpos: pedidos.filter((p) => p.url.endsWith('/pos/venda/p-1/finalizar'))",
        "    .map((p) => p.corpo) }));",
    ]), tmp_path_factory, "nif-da-app-dividir")


@pytest.fixture(scope="module")
def separar_depois_do_toque(tmp_path_factory):
    """Pelo cartão: o QR lido, o NIF da app usado, uma parte separada e
    cobrada — e o RESTO, que é a MESMA conta v-1 onde o NIF foi posto."""
    return _correr("\n".join([
        _lido_com_nif("cartao", "\n".join([
            "RESPOSTAS_POS['POST /pos/venda/v-1/separar-parte'] = () => ({ data: %s });"
            % json.dumps({"parte": _PARTE_COOKIE, "conta": _RESTO}, ensure_ascii=False),
            "RESPOSTAS_POS['POST /pos/venda/p-1/finalizar'] = () => ({ data: %s });"
            % json.dumps(_P1_EMITIDA, ensure_ascii=False),
        ])),
        "await carregar_em('Usar o NIF da app');",
        "const naMae = cartaoCliente();",
        "await carregar_em('Separar Conta');",
        # A LINHA da conta, e não o cartão da grelha: só a linha tem o «cada».
        "const linhaDoCookie = [...alvo.querySelectorAll('button')].find(",
        "  (b) => (b.textContent || '').includes(%s)" % json.dumps(_COOKIE),
        "    && (b.textContent || '').includes('cada'));",
        "if (!linhaDoCookie) throw new Error('sem linha do cookie: '",
        "  + textoVisivel(alvo).slice(0, 400));",
        "await act(async () => { linhaDoCookie.click(); });",
        "await act(async () => {});",
        "await carregar_em('COBRAR ESTA PESSOA');",
        "const naParte = cartaoCliente();",
        "const visivelNaParte = textoVisivel(alvo);",
        _EMITIR_A_PARTE,
        "RESPOSTAS_POS['/pos/venda/aberta'] = () => ({ data: %s });"
        % json.dumps(_RESTO, ensure_ascii=False),
        "await carregar_em('Nova Venda');",
        "await carregar_em('FINALIZAR');",
        "if (botao('Não')) await carregar_em('Não');",
        "const noResto = cartaoCliente();",
        "const visivelNoResto = textoVisivel(alvo);",
        "await carregar_em('Dinheiro');",
        "await carregar_em('EMITIR DOCUMENTO');",
        "await act(async () => {});",
        "const corpos = (id) => pedidos.filter(",
        "  (p) => p.url.endsWith('/pos/venda/' + id + '/finalizar')).map((p) => p.corpo);",
        "process.stdout.write(JSON.stringify({ naMae, naParte, visivelNaParte, noResto,",
        "  visivelNoResto, corpoDaParte: corpos('p-1'), corpoDoResto: corpos('v-1') }));",
    ]), tmp_path_factory, "nif-da-app-separar")


def test_dividir_depois_do_toque_a_parte_nao_leva_o_NIF_da_app(dividir_depois_do_toque):
    r = dividir_depois_do_toque
    assert _MASCARA in r["naMae"], "o toque não chegou a pôr o NIF na conta: %s" % r["naMae"]
    assert "Consumidor Final" in r["naParte"], r["naParte"]
    assert "Usar o NIF da app" not in r["visivelNaParte"], r["visivelNaParte"][:600]
    assert r["corpos"] and r["corpos"][0]["nif"] is None, r["corpos"]


def test_separar_depois_do_toque_nem_a_parte_nem_o_RESTO_levam_o_NIF_da_app(
        separar_depois_do_toque):
    """O resto é a MESMA conta onde o NIF foi posto, e quem o paga é outra
    pessoa: com o NIF de quem mostrou a app lá dentro, a fatura dela saía em
    nome de outro — um erro fiscal a sério, e silencioso."""
    r = separar_depois_do_toque
    assert _MASCARA in r["naMae"], "o toque não chegou a pôr o NIF na conta: %s" % r["naMae"]
    assert "Consumidor Final" in r["naParte"], r["naParte"]
    assert "Usar o NIF da app" not in r["visivelNaParte"], r["visivelNaParte"][:600]
    assert r["corpoDaParte"] and r["corpoDaParte"][0]["nif"] is None, r["corpoDaParte"]
    assert "Consumidor Final" in r["noResto"], r["noResto"]
    assert "Usar o NIF da app" not in r["visivelNoResto"], r["visivelNoResto"][:600]
    assert r["corpoDoResto"] and r["corpoDoResto"][-1]["nif"] is None, r["corpoDoResto"]
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /Users/matheus.moraes/Developer/RH-nif-da-app/backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/faturacao/test_o_nif_da_app_no_pos.py -q
```
Expected: `2 failed, 3 passed, 8 errors`.
- The 8 errors are fixtures that die in `Error: sem botão vivo com o texto Usar o NIF da app — no ecrã: Finalizar Total € 12,79 Cliente Consumidor Final Pontos L'Açaí Pontos para: Ana ✓ …`.
- The 2 failures are `test_o_botao_aparece_…[cartao|pergunta]` with `AssertionError: Cliente Consumidor Final`.
- The 3 that pass are absence guards: `test_sem_tocar…[cartao|pergunta]` and `test_com_um_NIF_ja_escrito…`. They are proven in Step 5.

- [ ] **Step 3: Implement**: `frontend/src/pages/pos/PosFinalizar.js`

**3a.** Import (line 21):

Before:
```js
  guardarNifDaConta, lerNifDaConta, nifValidoPT,
```
After:
```js
  guardarNifDaConta, lerNifDaConta, nifValidoPT, nifMascarado, nifDaAppParaOferecer,
```

**3b.** Signature (lines 424-425):

Before:
```js
// Final) sem ser preciso reabrir o lápis.
function CartaoCliente({ nifTexto, onNifTexto, desativado }) {
```
After:
```js
// Final) sem ser preciso reabrir o lápis.
//
// **O NIF da conta da app** (`nifDaApp`, ver `lib/pos.js::nifDaAppParaOferecer`)
// oferece-se num botão e nunca se põe sozinho: muitos clientes não o querem na
// fatura. Escondido no botão e escondido no título depois do toque — o ecrã
// está virado para a fila; quem abre o lápis vê os dígitos, de propósito.
function CartaoCliente({ nifTexto, onNifTexto, desativado, nifDaApp, nifDaLigacao, onUsarNifDaApp }) {
```

**3c.** Title and button (lines 466-474):

Before:
```js
      ) : (
        <p className="font-heading font-bold text-2xl">
          {digitos.length === 9 ? nifPorExtenso(digitos) : 'Consumidor Final'}
        </p>
      )}

      {/* As duas saídas à distância de um toque, com o editor FECHADO: quem
```
After:
```js
      ) : (
        <p className="font-heading font-bold text-2xl">
          {digitos.length !== 9 ? 'Consumidor Final'
            : digitos === nifDaLigacao ? nifMascarado(digitos) : nifPorExtenso(digitos)}
        </p>
      )}

      {/* No cartão FECHADO: o editor é a outra porta, e quem o abre vai
          escrever. A funcionária pergunta «contribuinte?» como sempre, e quem
          não quer NIF não gasta toque nenhum. */}
      {nifDaApp && !aEditar && (
        <Button
          type="button"
          variant="outline"
          className="h-12 mt-3 w-full sm:w-auto"
          onClick={onUsarNifDaApp}
          disabled={desativado}
        >
          {`Usar o NIF da app · ${nifMascarado(nifDaApp)}`}
        </Button>
      )}

      {/* As duas saídas à distância de um toque, com o editor FECHADO: quem
```

**3d.** `removerOCliente` (lines 1297-1301):

Before:
```js
  const removerOCliente = () => {
    mudarLigacao(null);
    setVoucher(null);
    pedirOVoucher(null);
  };
```
After:
```js
  const removerOCliente = () => {
    // E o NIF, se ainda for o da app tal e qual: um NIF que a operadora mudou
    // é dela e fica. Compara-se o valor — um NIF ditado igual ao da app também
    // sai, e está bem assim.
    if (ligacao?.nif && soDigitos(nifTexto) === ligacao.nif) setNifTexto('');
    mudarLigacao(null);
    setVoucher(null);
    pedirOVoucher(null);
  };
```

**3e.** Next to `digitosNif` (line 1399):

Before:
```js
  const nifValido = digitosNif.length === 0 || nifValidoPT(digitosNif);

  // As DUAS razões para congelar este ecrã — e são duas porque uma delas não
```
After:
```js
  const nifValido = digitosNif.length === 0 || nifValidoPT(digitosNif);
  // O NIF da conta da app que o cartão Cliente OFERECE, ou `null`.
  const nifDaApp = nifDaAppParaOferecer({ ligacao, nifTexto });

  // As DUAS razões para congelar este ecrã — e são duas porque uma delas não
```

**3f.** Render (line 1785):

Before:
```js
          <CartaoCliente nifTexto={nifTexto} onNifTexto={setNifTexto} desativado={aEmitir || congelada} />
```
After:
```js
          <CartaoCliente
            nifTexto={nifTexto}
            onNifTexto={setNifTexto}
            desativado={aEmitir || congelada}
            nifDaApp={nifDaApp}
            nifDaLigacao={ligacao?.nif}
            // Pelo `setNifTexto`, como um NIF ditado: é ele que grava a gaveta
            // do NIF e é dele que o `motivoBloqueio` e o EMITIR lêem.
            onUsarNifDaApp={() => setNifTexto(nifDaApp)}
          />
```

Do NOT touch `pontos_ligacao` (line 1684) or `PosVenda.js`.

- [ ] **Step 4: Run to verify it passes**

```bash
cd /Users/matheus.moraes/Developer/RH-nif-da-app/backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/faturacao/test_o_nif_da_app_no_pos.py tests/faturacao/test_os_pontos_no_ecra_do_pos.py tests/faturacao/test_os_pontos_da_conta_no_pos.py tests/faturacao/test_a_fatura_por_email_no_ecra_do_pos.py tests/faturacao/test_o_cartao_do_voucher_no_pos.py tests/faturacao/test_o_nif_que_nao_existe_no_pos.py tests/faturacao/test_o_nif_da_conta_no_pos.py tests/faturacao/test_o_dividir_e_o_separar_no_ecra.py -q
```
Expected: `164 passed`, with no `skipped` (the 13 of the new file plus 151 from R2). The new file alone gives `13 passed` in about 6 s.

Final check: `pytest tests/faturacao -q` gives `3246 passed`, with no `skipped`. This was measured with R2 and R3 applied and the server task not yet applied.

- [ ] **Step 5: Mutation check** (one at a time, revert after each; all verified red)

| Mutation in `PosFinalizar.js` | Expected red test |
|---|---|
| after `const nifDaApp = …;` add `useEffect(() => { if (nifDaApp) setNifTexto(nifDaApp); }, [nifDaApp]); // eslint-disable-line` (fills it in by itself) | `test_sem_tocar_no_botao_a_fatura_sai_SEM_NIF[cartao]` and `[pergunta]` |
| `nifDaAppParaOferecer({ ligacao, nifTexto })` → `nifDaAppParaOferecer({ ligacao, nifTexto: '' })` (ignores the field) | `test_com_um_NIF_ja_escrito_nao_ha_botao_e_a_fatura_leva_o_ESCRITO` |
| delete the line `if (ligacao?.nif && soDigitos(nifTexto) === ligacao.nif) setNifTexto('');` | `test_o_Remover_tira_tambem_o_NIF_da_app_que_ninguem_mexeu` |
| `if (ligacao?.nif && soDigitos(nifTexto) === ligacao.nif)` → `if (ligacao?.nif)` | `test_o_Remover_deixa_ficar_o_NIF_que_a_operadora_MUDOU` |
| `: digitos === nifDaLigacao ? nifMascarado(digitos) : nifPorExtenso(digitos)}` → `: nifPorExtenso(digitos)}` (mask after the tap) | `test_um_toque_poe_o_NIF_da_app_no_cartao_e_ele_continua_ESCONDIDO[cartao|pergunta]` |
| `onUsarNifDaApp={() => setNifTexto(nifDaApp)}` → `onUsarNifDaApp={() => {}}` | `test_depois_do_toque_o_EMITIR_leva_o_NIF_no_campo_de_sempre_e_nunca_nos_pontos[cartao|pergunta]` |
| (pins existing code) `PosVenda.js::esquecerOsPontosDaMae`: delete `    guardarPontosDaConta(maeId, null);` | `test_separar_depois_do_toque_nem_a_parte_nem_o_RESTO_levam_o_NIF_da_app` |
| (pins existing code) `lib/pos.js::lerNifDaConta`: `guardado && guardado.vendaId === vendaId ? String(guardado.nif \|\| '') : ''` → `guardado ? String(guardado.nif \|\| '') : ''` | `test_dividir_depois_do_toque…` and `test_separar_depois_do_toque…` |

- [ ] **Step 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-nif-da-app
git add frontend/src/pages/pos/PosFinalizar.js backend/tests/faturacao/test_o_nif_da_app_no_pos.py
git commit -m "$(cat <<'EOF'
POS: «Usar o NIF da app» no cartão Cliente, escondido e só com um toque

Com QR lido nesta conta, NIF válido na conta da app e o campo do NIF
vazio, o cartão Cliente fechado oferece «Usar o NIF da app · 2•• ••• •35».
Nunca preenche sozinho: o toque passa pelo setNifTexto, como um NIF
ditado, e o EMITIR leva-o no `nif` de sempre (o pontos_ligacao não
muda). Depois do toque o título continua mascarado. O «Remover» tira o
NIF se ainda for o da app e deixa ficar o que a operadora mudou. Testes
de ecrã pelas duas portas da leitura, e o dividir/separar a provar que
o NIF não passa às partes nem ao resto.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```


---

## Notas dos redatores (verificadas numa worktree descartável)

### app

- **O spec esqueceu a versão dos Termos.** Mudar o texto de `/termos` obriga, no mesmo commit, a mudar a «Última atualização» dos Termos (`legal_pages.py:184`) e a `TERMOS_VERSAO` (`auth.py:344`, o comentário 337-343 exige-o). Obriga também a mudar a asserção fixa em `tests/test_ponte_categorias_unit.py:329`. O spec só fala na data da Privacidade. Se só se mudar o texto, nenhum teste falha. Mas as contas novas passam a carimbar a aceitação com uma versão que já não é a que leram. Foi o padrão do commit be246b0. Nada no código obriga a aceitar outra vez quando a versão muda: só o `carimbo_dos_termos` lê a constante.
- **`test_termos_unit.py` não pode correr sozinho neste worktree.** Rebenta na recolha com `KeyError: 'MONGO_URL'`: não há `.env` no worktree, e só o `test_pos_integracao_unit.py` faz `os.environ.setdefault`. Já era assim no HEAD. Pôr sempre o `test_pos_integracao_unit.py` primeiro na lista, ou dar `MONGO_URL=mongodb://localhost:27017 DB_NAME=test JWT_SECRET=test-secret`. Nunca copiar o `.env` de `~/applacai/backend`: aponta para a PRODUÇÃO.
- **No zsh, `$T` sem aspas não se parte em palavras.** Um ciclo de mutação com `pytest $T` não corre nada e não imprime nada. Usar `${=T}` ou escrever os ficheiros na linha.
- **O parágrafo dos Termos enfraquecia um teste antigo.** A frase do spec («vale apenas para essa compra») é igual a um assert de `test_termos_unit.py:58`. Medi-o: com o assert antigo, apagar a frase da «Fatura por email» deixava tudo verde. O assert foi apertado com a marcação `<strong>`.
- **A Privacidade quebra as linhas no HTML** (e os Termos não). Por isso o teste da Privacidade compara depois de `" ".join(html.split())`. A frase nova foi acrescentada ao FIM do item «Pontos dados na caixa», depois da frase da fatura por email.
- **Fica igual na A1:** a frase «Devolve-se a MESMA variável que acabou de ser gravada», que continua a falar do `prefere_email`. O `nif` não é gravado, e a frase das linhas 134-137 di-lo. O `insert_one` de `pos_ligacoes` não muda.
- **Há duas linhas `"fatura_por_email": prefere_email,` no ficheiro:** a do `insert_one` (144) e a do `return` (160). Uma mutação com `sed` sem número de linha mexe nas duas.
- **`test_o_contrato_com_o_pos.py` correu sem skip** (118 passed com os vizinhos). Não cobre o `/ligar`, por isso não é guarda desta funcionalidade.
- Fora de âmbito, sem mexer: `backend/static/privacidade.html` é uma cópia antiga da Privacidade, de julho de 2026, servida em `/static`. Já está marcada para retirar em `docs/superpowers/specs/2026-09-15-termos-pendentes.md:23`. Continua sem a frase nova.
- Números reais: import do `auth` na linha 32, projeção em 117-119, `prefere_email` em 133, comentário de privacidade em 143-148 e `return` em 149-151. Na Privacidade: data em 43 e item em 61-65. Nos Termos: data em 184 e «Fatura por email» em 276. `valid_nif` está em `auth.py:180-188`. O worktree de ensaio foi removido.

### pos-server

- **A exclusão do `bool` não muda nada no comportamento.** `str(True)` é `"True"`, sem algarismos, por isso dá `None` com ou sem exclusão. A mutação `type(cru) not in (str, int)` → `isinstance(cru, (str, int))` sobrevive. Ficou `type(...) not in (...)`, que é uma só condição sem ramo morto. O que segura a verificação do tipo são os casos `lista`/`objecto`: passados a texto, escondem `517542510` válido. O caso `booleano` fica no teste só como guarda de «sem 500».
- **Só o caso árabe-índico apanha o `isdigit()`.** O `int()` do Python aceita esses algarismos, e o `_nif_portugues_valido` deixava-os passar. É preciso mantê-lo.
- **A docstring da rota (179-195) nunca dizia «só o primeiro nome e um sim/não», ao contrário do que a spec dá a entender.** Só a docstring do módulo (10-15) o dizia. Na rota acrescentou-se um parágrafo e não se substituiu nada.
- **Números de linha verificados em b3aaf72:**
  - o log está em 228-232 (o comentário começa em 228; a spec diz 230-232);
  - a resposta está em 235-245;
  - `_nif_portugues_valido` está em `fiscal.py:1912`;
  - o filtro `c in "0123456789"` está em `fiscal.py:1986`.
- **Há uma segunda «resposta inesperada» que ainda despeja `resposta.text[:200]`.** Fica em `/pos/pontos/preferencia`, nas linhas 368-371 originais. A resposta da app a `/preferencia` é `estado/fatura_por_email` e não leva NIF, por isso ficou de fora (não está na spec). Se um dia a app lá puser dados pessoais, tem de levar a mesma correção.
- **Um log que não é 200 escreve agora `chaves None`.** O `corpo` só se lê quando o estado é 200, e o estado HTTP (401, 5xx) é a informação que conta. O pormenor `{"detail": …}` dos 4xx deixa de aparecer no log, e foi de propósito.
- **Nenhum outro teste em `backend/tests` fixa o texto antigo do log nem a resposta de 3 chaves do servidor.**
  - Os dicionários de 3 chaves dos testes de ecrã são a forma do `onLigada`/gaveta do frontend, com o servidor fingido por `RESPOSTAS_POS`. São da tarefa do ecrã:
    - `test_os_pontos_no_ecra_do_pos.py:143/341/454/593`
    - `test_a_fatura_por_email_no_ecra_do_pos.py:91-102, 190-222`
    - `test_os_pontos_da_conta_no_pos.py:20`
  - Continuam verdes depois do R1: a pasta `faturacao` inteira dá 3234 passed, 0 skipped.
- **O `_NIF_VAZIO` de `sincronizacao_app.py:129` não foi reutilizado.** É uma constante privada de outro módulo, e o `""`/`"---------"` que contém já ficam de fora pelo filtro de algarismos. Basta uma comparação com o literal.
- **Python:** o venv local é 3.9.6 e o Dockerfile de produção é `python:3.11-slim`. O código não usa nada que mude entre as duas versões.

### pos-screen

- **The spec line numbers are correct** on `matheus-nif-da-app` b3aaf72:
  - PosLerQr 150-157.
  - lib/pos.js 209-216, 239-257, 276-281.
  - PosFinalizar 21, 425, 466-470, 1297, 1399, 1785, 1684.
  - The bench dicts are at `test_os_pontos_no_ecra_do_pos.py` 142-143, 340-341, 453-454 and 592-593. The mapping said "452" for one of them; it is 453-454.
- **`test_o_cartao_do_voucher_no_pos.py` does not break.** It only pins `pontos_ligacao`. The spec talks of "≈10 asserts em 4 ficheiros"; the real number is 11 dicts in 3 files plus `_ANA`.
- **`PosCampoValor` trap.** `SUBSTITUIDOS.delete(path.join(POS, 'PosCampoValor.js'))` must come BEFORE `_arranque(...)`/`_no_finalizar(...)`. The `PosVenda`→`PosFinalizar` are loaded inside `_arranque`, before `respostas_extra`, so putting the delete inside `extra` is too late: the marker gets used and the editor crashes (`TecladoNumerico` undefined). Putting it in front works because `SUBSTITUIDOS` lives in the preamble.
- **`carregar_em('Confirmar')` is ambiguous** in the mounted `PosVenda`. It clicks the first live button with that word in the whole screen. The test clicks the one inside the Cliente section and asserts `editorFechado`. Without that, the "edited" test could pass with the editor still open: the title shows the same `517 542 510`.
- **`nifDaAppParaOferecer` is stricter than the spec.** It also requires `/^\d{9}$/`, because `nifValidoPT` strips non-digits and would accept `'219 363 935'`. That keeps the Remover comparison (`soDigitos(nifTexto) === ligacao.nif`) and the title-mask comparison (`digitos === nifDaLigacao`) consistent. In the same spirit, `nifMascarado` returns `''` for anything that is not exactly 9 digits. The spec did not say what to do there, and a `slice(7)` over 10 digits would show 3.
- **`999999990` passes `nifValidoPT`.** The screen does not filter it, by design: it relies on the server's `_nif_da_app` (the other task) to drop it.
- **Three new screen tests pass before R3.** They are absence guards ("no tap → `nif None`" through both doors, and "NIF already written → no button"). This is expected; they are proven by the first two mutations in R3's Step 5. The split tests pin code that does not change (`esquecerOsPontosDaMae` and the single-entry NIF drawer). Their mutations are in `PosVenda.js` and `lib/pos.js::lerNifDaConta`.
- **`mudarPreferencia` keeps `nif`** because it does `{ ...ligacao, fatura_por_email }`, so the NIF survives «Enviar por email/Voltar ao papel». The exact dicts after the preference have `"nif": None` only because the fake response of `ler` in those files has no `nif`.
- **The full NIF is in `sessionStorage` from the read on.** The `pos_pontos_da_conta` drawer holds it, as decided (spec, decision 6). It is NOT in the DOM, neither before nor after the tap, because the editor is closed; the tests assert `innerHTML` as well as `textoVisivel`. Do not add a test saying the NIF is not in the drawer.
- **Test counts.** Step 4 of each task deliberately leaves out `test_os_pontos_da_app.py`, which the server task changes. With it in and without the server task: R2 → 266, R3 → 279. The whole `tests/faturacao` directory gives 3246 passed and 0 skipped with R2 and R3 (3220 before).
- **Reference diff.** The whole verified diff (both tasks, identical to the code above) is at `/private/tmp/claude-501/-Users-matheus-moraes-Library-CloudStorage-OneDrive-Pessoal-Claude/cb8a391f-dcc9-4b24-8e25-5b8bfd5b1350/scratchpad/rh-ecra-final.diff`. It passes `git apply --check` against `matheus-nif-da-app` HEAD. The new test file is also saved at `…/scratchpad/test_o_nif_da_app_no_pos.py`. The throwaway worktree has been removed, and `RH-nif-da-app` is still clean.

