# O NIF da conta da app no cartão Cliente do POS — desenho

**Data:** 2026-10-24 · **Ramos:** `matheus-nif-da-app` em `~/applacai` (worktree `~/applacai-nif-da-app`, a partir de `main` b95d896) e em `~/Developer/RH` (worktree `~/Developer/RH-nif-da-app`, a partir de `origin/main` 1980bb8). O mesmo documento vive nos dois repos.

## Porquê

Cerca de um terço das faturas das lojas leva NIF (211 de 651 em quatro dias de setembro), e hoje o NIF é sempre ditado e escrito à mão. É esse o caminho por onde entram os enganos: um telefone escrito como NIF deu cerca de uma recusa do Vendus por dia antes de 2026-09-11, e o dígito de controlo só apanha nove em cada dez. Quem mostra o QR da app na caixa já tem, muitas vezes, o NIF na conta. A app já faz isto no checkout dela (`frontend/app/pagamento.tsx:58-62`: «Fatura com NIF» desligado, e ao ligar vem preenchido com o NIF da conta).

## Decisões do dono

1. **Perguntar sempre, nunca preencher sozinho.** Muitos clientes não querem NIF na fatura, e uma FS com um NIF que não pediram só se corrige com nota de crédito.
2. **Um botão no cartão Cliente** do ecrã de pagamento, e não uma janela nova depois do QR: **«Usar o NIF da app · 2•• ••• •89»**. A funcionária pergunta «contribuinte?» como já faz. Quem não quer NIF não gasta toque nenhum.
3. O botão só aparece quando há **QR lido nesta conta**, a conta tem **NIF válido** e o **campo do NIF está vazio**.
4. **O NIF aparece escondido** no botão e continua escondido no cartão depois do toque (o ecrã está virado para a fila). A fatura sai com o NIF completo.
5. O **«Remover»** do cartão de pontos tira também o NIF, se ainda for o da app.
6. **Muda a regra 6 do desenho de 2026-09-15** («o POS mostra só o primeiro nome»): o NIF completo chega ao PC da loja logo na leitura do QR, mesmo que o cliente diga que não. Fica só na gaveta do separador presa àquela conta — nem no ecrã, nem em nenhuma base de dados. A versão fechada (só a máscara na leitura e o NIF completo pedido à app ao tocar) foi posta de lado: mais código e mais uma chamada que pode falhar ao balcão.
7. **Textos legais da app:** uma frase na Privacidade e outra nos Termos a dizer que a loja recebe o NIF da conta e que ele só entra na fatura se o cliente o confirmar na caixa.
8. **Sem build da app.** Só servidores e o ecrã do POS.

## Fora de âmbito

- Uma preferência na app («pôr sempre o meu NIF») — precisa de build e ninguém a pediu.
- Avisar no ecrã do QR da app que a caixa pode perguntar pelo NIF — precisa de build.
- Aviso quando o NIF escrito à mão é diferente do da conta: silêncio, de propósito.
- Listar o Vendus e o servidor do POS como destinatários na Privacidade §3: buraco que já existia (também nas faturas da app), fica para outra vez.

## Fluxo

```
Cliente (app)          POS (browser)                    RH backend                       App backend
QR na caixa ──lido──▶  PosLerQr ─────────────────────▶ POST /pos/pontos/ler ──────────▶ POST /pos-integracao/ligar
                                                                                          lê users.nif (+ projeção)
                                                                                          valid_nif → "nif" ou None
                       gaveta pos_pontos_da_conta ◀──── {ligacao_id, primeiro_nome,  ◀── {..., "nif"}
                       {id, primeiro_nome,              fatura_por_email,
                        fatura_por_email, nif}          nif: _nif_da_app(...)}
                       CartaoCliente vazio:
                       [Usar o NIF da app · 2•• ••• •89]
                       toque → setNifTexto(nif) → gaveta do NIF (como se fosse ditado)
                       EMITIR ─────────────────────────▶ finalizar: `nif` de sempre (fiscal.py::_valida_nif)
```

O NIF viaja no EMITIR pelo campo `nif` de sempre. **Nunca** dentro de `pontos_ligacao`, que continua `{id, primeiro_nome}`.

## As peças

### 1. App — `backend/routes_pos_integracao.py::ligar`

- A projeção do `db.users.find_one` (117-119) ganha `"nif": 1`. **O duplo do Mongo ignora a projeção** (`test_pos_integracao_unit.py:309-321`): sem um teste com espião da projeção, a suite fica verde e em produção o NIF vem sempre `None`.
- `nif = str(user.get("nif") or "").strip()`; `nif = nif if valid_nif(nif) else None`.
- A resposta ganha `"nif": nif`, **sempre presente** (`None` quando não há).
- **Não** se grava o NIF em `db.pos_ligacoes`: o `delete_account` (`routes_customer.py:2100`) só faz `$unset user_id` nas ligações, e um NIF lá ficava depois de a conta ser apagada.
- O comentário 142-149 («só o primeiro nome… o POS recebe um sim/não e mais nada») é a regra de privacidade escrita no código: reescreve-se a explicar a exceção do NIF (serve para entrar no documento fiscal e só entra se o cliente o confirmar na caixa; quem esconde é o POS). O email continua sem sair.

### 2. Servidor do POS — `backend/faturacao/pontos_app.py::ler_qr_de_pontos`

- Função nova `_nif_da_app(cru) -> Optional[str]`: aceita só `str`/`int` (não `bool`), filtra `c in "0123456789"` (o alfabeto de `fiscal.py:1986`, nunca `isdigit()`), deita fora `999999990`, devolve os 9 dígitos se `_nif_portugues_valido` passar; senão `None`. **Nunca levanta** — nesta altura a app já gastou o QR do cliente — e **nunca escreve o número no log**. `_nif_portugues_valido` importa-se dentro da função (o `fiscal` só importa `pontos_app` de forma preguiçosa, de propósito; um import de topo podia fechar o ciclo um dia).
- A resposta (235-245) ganha `"nif": _nif_da_app(corpo.get("nif"))`, sempre presente. Não se grava em `fat_pontos_qr` nem na venda.
- O log da «resposta inesperada» (230-232) deixa de despejar `resposta.text[:200]`: passa a escrever o estado HTTP e as chaves do corpo. Com o NIF no corpo, um 200 sem `ligacao_id` metia-o no log.
- Docstrings do módulo (10-15) e da rota (179-195) atualizadas: deixam de dizer «só o primeiro nome e um sim/não».

### 3. Ecrã do POS

- **`PosLerQr.js:150-157`** — a desestruturação e o `onLigada` ganham `nif: nif || null`. As duas portas da leitura (o cartão e a pergunta do FINALIZAR) passam por aqui.
- **`lib/pos.js::guardarPontosDaConta`** (253-257) — a lista branca da gaveta ganha `nif: ligacao.nif || null` (forma sempre presente, regra de 249-252). Comentários 239-243 e 276-281 atualizados.
- **`lib/pos.js`** — duas funções puras, exportadas e testadas:
  - `nifMascarado(nif)`: `'219363935'` → `'2•• ••• •35'` (1.º dígito, 2 pontos · 3 pontos · 1 ponto e os 2 últimos).
  - `nifDaAppParaOferecer({ ligacao, nifTexto })`: os 9 dígitos se houver ligação, `nifValidoPT(ligacao.nif)` e `nifTexto` sem nenhum dígito; senão `null`. Tolera gavetas antigas sem `nif`.
- **`PosFinalizar.js`**
  - junto a `digitosNif` (≈1399): `const nifDaApp = nifDaAppParaOferecer({ ligacao, nifTexto })`;
  - `CartaoCliente` recebe `nifDaApp`, `nifDaLigacao` (o `ligacao?.nif`) e `onUsarNifDaApp={() => setNifTexto(nifDaApp)}` — pelo `setNifTexto`, nunca pela gaveta à mão, para o efeito da linha 1314 gravar e o `motivoBloqueio` ver o NIF;
  - no cartão **fechado** e vazio (466-470), debaixo de «Consumidor Final»: o botão «Usar o NIF da app · 2•• ••• •89». No cartão fechado de propósito: o editor depende do `PosCampoValor` verdadeiro, que o banco de ensaio substitui;
  - com 9 dígitos válidos iguais a `nifDaLigacao`, o título mostra `nifMascarado` em vez de `nifPorExtenso`; abrir o editor (lápis) mostra os dígitos, que é uma ação explícita;
  - `removerOCliente` (1297): antes do `mudarLigacao(null)`, `if (ligacao?.nif && soDigitos(nifTexto) === ligacao.nif) setNifTexto('')`. Compara valores, sem estado de origem guardado (um NIF escrito à mão igual ao da app também sai — aceitável).
  - `pontos_ligacao` (1684) **não muda**.
- **`PosVenda.js`** — sem alterações: `esquecerOsPontosDaMae` já apaga a ligação (e o `nif` com ela) e a gaveta do NIF, de entrada única, não passa para as partes. Fica um teste de ecrã a prendê-lo.

Comportamento que resulta das regras, e que é o pretendido:
- NIF escrito antes do QR → sem botão, nada é sobreposto.
- Um dígito escrito depois da leitura → o botão desaparece.
- Campo esvaziado (Consumidor Final ou Limpar) → o botão volta. Não é preenchimento automático.
- NIF da app usado e depois editado → o «Remover» não o apaga.

### 4. Textos legais da app — `backend/legal_pages.py`

- **Privacidade §1**, item «Pontos dados na caixa» (≈61-66): *«Quando a caixa lê o seu QR, a loja recebe da app o seu primeiro nome e, se tiver NIF na conta, esse NIF. O NIF só entra na fatura dessa compra se o confirmar na caixa.»* Data da última atualização (43) para 24 de outubro de 2026.
- **Termos 4.2**, junto ao parágrafo «Fatura por email» (≈276), que aparece sempre (o `_QR_NA_CAIXA` só aparece com o «Ler fatura» desligado): *«NIF na fatura. Se tiver NIF na conta, a caixa pode perguntar-lhe se o quer na fatura. Só é usado se disser que sim e vale apenas para essa compra. Depois de emitida, a fatura não pode ser alterada.»*
- `tests/test_termos_unit.py` ganha os asserts das duas frases, no estilo do teste da linha 62.
- **Mudar o texto dos Termos obriga, no mesmo commit, a mudar a «Última atualização» dos Termos (`legal_pages.py:184`) e a `TERMOS_VERSAO` (`auth.py`) para `"2026-10-24"`** (o comentário junto à constante exige-o; senão as contas novas carimbam a aceitação com uma versão que não leram). A asserção fixa em `tests/test_ponte_categorias_unit.py` acompanha. Ninguém é obrigado a aceitar outra vez: só o `carimbo_dos_termos` lê a constante.

## Testes

**App (`backend/tests/test_pos_integracao_unit.py`)**, ao lado de 281 e 302:
- conta com NIF válido → `r["nif"]` igual, com espião da projeção (`pedida.get("nif") == 1`);
- conta sem NIF e conta com NIF inválido → `r["nif"] is None`;
- `"nif" not in db.pos_ligacoes.docs[0]`;
- continua `"@" not in str(r)`.
- Mutação obrigatória: tirar `"nif": 1` da projeção tem de pôr o primeiro vermelho.

**Servidor do POS (`backend/tests/faturacao/test_os_pontos_da_app.py`)**:
- a igualdade exata da linha 130 passa a 4 chaves (`"nif": None`);
- `'517 542 510'` → `'517542510'`; `219363931` → `None`; `'51754251X'`, lista, dict, `True` → `None` **sem 500**; `999999990` → `None`; ausente → `None`;
- corpo da app com `email` → a resposta tem exatamente as 4 chaves (o teste de fuga que falta do lado do servidor);
- o log da resposta inesperada não contém o NIF.

**Ecrã do POS** (banco de ensaio em `backend/tests/faturacao/`):
- atualizar os dicionários exatos que fixam a forma do `onLigada` e da gaveta (≈10 asserts em `test_os_pontos_no_ecra_do_pos.py`, `test_os_pontos_da_conta_no_pos.py`, `test_a_fatura_por_email_no_ecra_do_pos.py`, `test_o_cartao_do_voucher_no_pos.py`) — a forma é sempre presente, não se põe o `nif` só quando existe;
- funções puras: `nifMascarado`; `nifDaAppParaOferecer` (sem ligação, NIF inválido, gaveta antiga sem `nif`, campo com dígitos → `null`; campo vazio → NIF);
- com `POST /pos/pontos/ler` a devolver `nif: '219363935'`, **pelas duas portas** (cartão e pergunta do FINALIZAR):
  - o botão aparece com «2•• ••• •35» e nem `219363935` nem `219 363 935` estão no texto visível;
  - EMITIR sem tocar → `nif is None` (a guarda do «nunca preencher sozinho»);
  - tocar → o cartão mostra a máscara e o EMITIR leva `nif == '219363935'` e `pontos_ligacao == {id, primeiro_nome}`;
  - Remover limpa o NIF não mexido e mantém o editado;
  - NIF escrito → sem botão;
  - dividir/separar depois do QR → a parte não tem botão e `nif is None`.
- Validação por mutação das guardas principais (o `nif` no `onLigada`, a condição do campo vazio, o `setNifTexto('')` do Remover, a máscara depois do toque).

Armadilhas conhecidas do banco de ensaio: o `Botao` falso deita fora `aria-label`/`variant` (encontrar o botão pelo texto); o `PosCampoValor` está substituído (não abrir o editor); `_arranque` responde «Não» à pergunta sozinho sem `parar_nos_pontos=True`; o efeito `[venda?.id]` só se prova a desenhar outra vez na MESMA raiz; sem `frontend/node_modules` os testes de ecrã saltam em silêncio — ler `passed` E `skipped`.

## Publicação

Qualquer ordem é segura: o POS monta a resposta campo a campo e deita fora chaves que não conhece, e um POS novo com a app antiga recebe `nif` ausente e não mostra o botão. Ordem escolhida: **app primeiro** (API + textos legais), **depois o POS** (backend + frontend com `--no-cache`, provado no bundle servido). Os PCs das lojas apanham a mudança ao recarregar a página.

Prova depois do deploy: o bundle servido tem «Usar o NIF da app» (fragmento só-ASCII); de dentro do contentor da app, `ligar` com a projeção nova devolve `nif` para uma conta com NIF; e **com o dono, numa compra a sério** (uma FS é um documento fiscal — não se emite «de teste»): QR → botão mascarado → toque → a FS sai com o NIF.
