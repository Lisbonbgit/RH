# Fatura por email em vez de talão — desenho

**Data:** 2026-09-17 · **Ramo:** `matheus-fatura-por-email` (nos dois repos)

## Porquê

Gasta-se muito papel térmico nas lojas. Quem tem a app L'Açaí já mostra o QR na caixa para
receber os pontos ([[2026-09-15-pontos-no-pos-design]]); a partir daí o sistema sabe quem é o
cliente e a app sabe o email dele. A fatura pode ir por email e o talão não se imprime.

## O tecto da poupança, medido antes de construir (2026-09-17)

| dia | faturas emitidas | com QR lido |
|---|---|---|
| 11/09 | 147 | 0 |
| 12/09 | 144 | 0 |
| 13/09 | 169 | 0 |
| 14/09 | 127 | 0 |
| 15/09 | 107 | 0 |
| 16/09 | 120 | 3 |
| 17/09 | 81 | 1 |

As 4 leituras são o ensaio do dono (a fila tem 2 créditos feitos, 2 recusados e 2 estornos). **Nenhum
cliente usou ainda o QR**, porque a 1.0.7 — a primeira versão que o desenha — está no TestFlight e o
AAB ainda não foi carregado no Play. Esta funcionalidade só poupa papel a quem mostra o QR: o tecto
dela é a adopção do QR, que hoje é zero. Construir agora é legítimo (fica pronta para quando a
adopção vier), mas **o número a vigiar primeiro é quantas faturas têm QR**, não este código.

E o talão do cliente é só um dos papéis da loja: a ficha da cozinha, o Z do fecho e as segundas vias
continuam a sair.

## Decisões do dono

1. **Falhando o email, não se imprime nada.** A falha fica registada e trata-se depois (o risco foi
   dito e aceite: um cliente pode ficar sem documento).
2. **Caixa primeiro, app no build seguinte.** A Fase 1 não espera por build nenhum.
3. **As notas de crédito saem sempre em papel.** A devolução é rara e é o momento em que o cliente
   está chateado.
4. **Sem pontos, sem email.** Quem não mostra o QR leva talão, como sempre.

## Mudanças ao desenho aprovado no chat (e porquê)

Vinte achados sobreviveram à verificação de 42 agentes contra o código. Cinco mudam o desenho:

- **A preferência não se grava na conta na Fase 1**: vale só para aquela venda. Enquanto a app não
  tiver o interruptor, uma preferência permanente ligada pelo staff é um consentimento que o cliente
  não vê nem consegue desligar. Na Fase 2 passa a preferência de conta, como o dono pediu.
- **O papel só se salta se a linha do email foi mesmo criada** — as duas decisões passam a ser uma só.
- **Com NIF escrito, o papel sai à mesma.** O NIF é por parte da conta e a ligação do QR é de quem
  mostrou a app: quando divergem, a fatura da empresa ia para a caixa de correio do colega.
- **Quem descarrega o PDF do Vendus é o POS, não a app** — o POS já tem o código medido e passa o
  `mode` do próprio documento; a app nunca fala com o Vendus nesta frente.
- **O email do cliente não sai da app, nem mascarado.** O POS recebe só um sim/não.

## Fora de âmbito

- Lista "As minhas faturas" dentro da app (precisa de build; o email é o arquivo).
- Notas de crédito por email.
- Escolher um email diferente do da conta.
- Tratamento de devoluções de email (bounces): o Resend aceitar não é o mesmo que entregar, e não há
  hoje recetor de bounces em lado nenhum. Fica escrito como limitação conhecida.

## Fluxo

```
QR do cliente ──lido──▶ POST /pos/pontos/ler ──────▶ POST /pos-integracao/ligar
                              │                             └─▶ {ligacao_id, primeiro_nome,
                              │                                  fatura_por_email}
                              ├─ grava fat_pontos_qr {ligacao_id, fatura_por_email}  ← a VERDADE
                              └─ devolve ao ecrã (só para desenhar o cartão)

EMITIR ──▶ fiscal.finalizar ──▶ documento fiscal na AT
              └─ if not enfileirar_fatura_email(...):  enfileirar_venda_emitida(...)   ← papel
                                    │
                                    ▼
                        fila fat_pontos_app, tipo "fatura_email"
                                    │  (cron 1/1 min + tentativa imediata)
                                    ├─ POS descarrega o PDF do Vendus (mode do documento)
                                    └─▶ POST /pos-integracao/fatura-email {ligacao_id,
                                          documento_id, numero, pdf_base64}
                                              └─▶ Resend, para o email da conta
```

## POS (RH) — servidor

### Ler o QR

`POST /pos/pontos/ler` (`pontos_app.py:106`) passa a devolver `fatura_por_email: bool`, vindo da
resposta do `/ligar`. **E grava-o**: uma linha em `fat_pontos_qr` `{ligacao_id, fatura_por_email,
criada_em}` com índice TTL de 2 horas (uma conta pode ficar aberta muito depois da leitura; e a
falta da linha faz sair papel, que é o lado seguro). Entrada nova em `COLECOES` e o índice em `db.py`.

Porquê gravar, contra a docstring que diz "não grava nada na venda": a decisão de **não imprimir um
documento fiscal não pode vir do corpo de um pedido do browser**. Hoje o `pontos_ligacao` viaja no
`dados_pagamento` (`fiscal.py:2136`) e isso é aceitável para pontos; para suprimir papel, um campo
forjado (ou um defeito no ecrã) fazia desaparecer o documento do cliente. O `fat_pontos_qr` é a fonte
da verdade, é do servidor, e caduca sozinho.

O `LigacaoDePontos` (`fiscal.py:1947`) **não ganha campo nenhum** — o servidor nunca lê a preferência
do corpo do EMITIR. O ecrã guarda o `fatura_por_email` no `sessionStorage` ao lado do
`{id, primeiro_nome}` que já lá está (`lib/pos.js:238`), mas **só para desenhar o cartão**: se ele for
adulterado, o pior que acontece é o cartão mentir ao staff — o papel continua a ser decidido pelo
`fat_pontos_qr`.

### Emitir

Em `fiscal.py:2298`, dentro do `try` que já lá está, a única linha que põe papel na fila passa a:

```python
if not await enfileirar_fatura_email(db, venda_actualizada or venda, documento):
    await enfileirar_venda_emitida(db, venda_actualizada or venda, documento)
```

`enfileirar_fatura_email` devolve `True` (o papel salta-se) **só** quando, no fim, existe mesmo uma
linha `fatura_email:<documento_id>` na fila. Devolve `False` — e o papel sai — quando:

- `documento["modo"] != "normal"` (o ponto 8: em `tests` o papel sai e não há email);
- a venda não tem `pontos_ligacao`;
- o `fat_pontos_qr` daquele `ligacao_id` não existe ou tem `fatura_por_email: False`;
- `venda["cliente_nif"]` está preenchido (quem escreve um NIF quer o documento ali);
- a escrita na fila falhou por qualquer razão.

**Um `DuplicateKeyError` conta como `True`**: a linha já lá estava (a rota corre mais do que uma vez
por venda), e devolver `False` aí fazia sair papel numa fatura que já ia por email.

A leitura é do `venda_actualizada` (`fiscal.py:2287`), nunca do corpo: quem perde a corrida da reserva
(`_esperar_documento_do_vencedor`) também chega a esta linha e só a venda gravada tem a verdade.

**Não herda as guardas do `enfileirar_credito`**: nem a do ATCUD (`pontos_app.py:452` — um documento
real pode não o ter, e o email só precisa do id do documento), nem mais nenhuma. Herdá-las era o caso
em que não sai papel nem email e não fica linha nenhuma para alguém ver.

### Fila `fat_pontos_app` — tipo `fatura_email`

Chave `fatura_email:<documento_id>`, na colecção que já existe, com o índice único que já existe
(`db.py:385`). Payload: `{ligacao_id, documento_id, vendus_document_id, numero, modo}`. **Sem bytes
do PDF** — a fila não tem TTL e fica para sempre; 92 KB por fatura para sempre não.

Três mudanças no módulo:

1. `acao = ...` (`pontos_app.py:323`) deixa de ser um ternário e passa a mapa
   `{"credito": "creditar", "estorno": "estornar", "fatura_email": "fatura-email"}`. Como está, um
   tipo novo era enviado para `/estornar`.
2. `_RESPOSTAS_FEITAS` (`pontos_app.py:189`) ganha `"enviado"` e `"ja_enviado"`.
3. `_chamar_app` ganha um `timeout` por acção. Os 4 s são para quem está ao balcão à espera; o envio
   corre em segundo plano e leva 25 s. O ramo do estorno que espera pelo crédito não toca neste tipo.

O envio, dentro de `enviar`, para este tipo: descarrega o PDF com `ClienteVendus.pdf_do_documento`
(`vendus/cliente.py:218`) passando o `modo` **do documento** — está medido na conta real que um
documento emitido em `tests` pedido com `mode=normal` responde 404, e que o PDF vem em base64 dentro
do JSON, não no corpo. Sem PDF, não chama a app: falha técnica, e a fila repete.

### Backoffice: o detalhe do documento

`pontos_app_do_documento` (`pontos_app.py:599`) procura a linha por `credito:<id>` ou `estorno:<id>` —
uma linha `fatura_email:<id>` não aparece em lado nenhum. Passa a devolver também a linha do email, e o
diálogo do `FatDocumentos.js` ganha o estado do envio ao lado da linha "Pontos L'Açaí" que já lá está,
e o botão de reenviar ao lado de "Reimprimir na loja" e "PDF da fatura".

### Reenviar

`POST /pos/faturacao/documentos/{id}/reenviar-email` (gestor) **para qualquer documento**, não só para
os falhados — o caso frequente é "não me chegou" com a linha em `feito`. Repõe ou cria a linha com
**cinco campos** numa escrita: `estado="pendente"`, `tentativas=0`, `primeira_falha_tecnica_em=None`,
`proxima_tentativa_em=agora`, `a_enviar_ate=_NUNCA`; só depois `tentar_ja`. Repor só o estado é um
botão que dá uma tentativa e volta logo a `falhado`.

### O que a loja vê

- `estado_da_impressao` (`impressao.py:742`) ganha mais um `count_documents`: faturas daquela loja com
  tipo `fatura_email` e estado em `('pendente' há mais de X, 'falhado', 'recusado', 'sem_efeito')` — as
  três últimas são becos sem saída e **nenhuma delas tem papel a compensá-la**. Para isto a linha nasce
  com `loja_id` (o `**campos` de `_linha_nova` já o leva). O POS já acende um alarme de 20 em 20 segundos com esta resposta — é o
  caminho mais barato para a falha chegar a uma pessoa no mesmo dia.
- **Não há lista nova.** O separador Faturação do POS já lista os documentos da loja e já tem
  "Imprimir" em cada um (`PosFaturacao.js:199-226`, `impressao.py:963-978`): quem precisa de papel
  dá-o a um toque. Acrescenta-se só um filtro "por enviar".
- O relatório diário que já sai por email ao dono à noite (`relatorio_rota.py:189-199`) leva uma linha:
  *"X faturas por email, Y em papel"*, e o aviso quando houver falhadas. É a medição que transforma a
  promessa num número, no canal que já existe.

## POS (RH) — ecrã

No `CartaoPontos` do Finalizar (`PosFinalizar.js:573-584`), no ramo COM ligação:

- preferência ligada: `Pontos para: Matheus ✓ · Fatura por email ✉` + botão **"Voltar ao papel"**, ao
  lado do "Remover" que já lá está;
- preferência desligada: `Pontos para: Matheus ✓ · Fatura em papel` + botão **"Enviar por email"**.

**O endereço nunca aparece** — só o sim/não. Um ecrã de caixa com o email de um cliente por cima é
uma porta de enumeração, e o POS não precisa dele para nada.

Depois do EMITIR, a mensagem de sucesso (`PosFinalizar.js:975-980`) diz **"Fatura vai por email — não
é preciso esperar pelo papel."** Não diz "enviada": no instante do EMITIR o envio ainda não aconteceu
(`tentar_ja` agenda e volta logo, `pontos_app.py:243-256`), e o ecrã não pode afirmar o que não sabe.

## App L'Açaí — servidor (sem build)

### `POST /api/pos-integracao/ligar` (mudança)

A resposta ganha `fatura_por_email: bool`. Na Fase 1 lê-se da própria ligação (nasce a `False`); na
Fase 2 passa a ler de `users.fatura_por_email`. **O email não sai daqui, nem mascarado.**

### `POST /api/pos-integracao/preferencia` (nova)

Corpo: `{ligacao_id, valor: bool, operador_nome, loja_nome}`. Escreve o valor **na ligação** (Fase 1),
não na conta. Recusa quando a ligação não existe, já foi usada (`atcud` preenchido) ou está fora da
janela de tempo que a rota de creditar já usa — a preferência só se muda com um QR lido agora, ao
balcão, com o cliente à frente.

Regista em `auditoria` (`auditoria.registar`, que já existe): quem ligou, em que loja, para que
cliente. Sem isto não há prova nenhuma de que o cliente aceitou receber a fatura desmaterializada, e
essa aceitação é dele, não do staff.

Manda uma push transacional (`type: "points"`, o único que as apps publicadas sabem encaminhar):
*"A fatura desta compra vai para o teu email."*

### `POST /api/pos-integracao/fatura-email` (nova)

Corpo: `{ligacao_id, documento_id, numero, pdf_base64}`.

1. **Prende a ligação ao documento numa escrita condicional**, antes de tudo:
   `find_one_and_update({id, documento_id: None}, {$set: {documento_id}})`. Sem isto, quem tiver a
   chave de serviço manda a fatura de um cliente para a conta de outro.
2. **Chave de idempotência** `_id = documento_id` numa colecção própria, com estado
   `a_enviar` → `enviado` / `falhado`. Duplicado em `a_enviar` responde 503 (a fila repete); em
   `enviado` responde `ja_enviado`; em `falhado` tenta outra vez. Sem isto, 13 tentativas da fila são
   13 emails da mesma fatura.
3. Envia por `send_email` com o PDF em anexo (`build_pdf_attachment`, que já higieniza o número da FS).
4. **Só responde `enviado` quando `send_email` devolveu `True`.** Qualquer outro caso é **5xx** —
   nunca 400/413/422, que a fila fecha como `recusado` sem repetir e sem aparecer em lado nenhum.

## App L'Açaí — ecrã (Fase 2, precisa de build)

Interruptor "Receber faturas por email" no ecrã Conta, com o endereço à vista e uma linha a explicar
que deixa de receber talão na loja. A partir daí a preferência é da conta e o botão da caixa passa a
escrever lá.

## Páginas legais (no mesmo dia do deploy, sem build)

`legal_pages.py` é uma f-string servida pela API — muda-se sem build e sem revisão da Apple. Três
linhas: uma finalidade nova na Política de Privacidade (*"Enviar por email a fatura das suas compras
nas lojas, quando escolher recebê-la assim"*), a menção de que se guarda essa escolha, e uma frase nos
Termos a dizer para onde vai a fatura e como se volta ao papel.

## Ordem de arranque

1. App: rotas novas + `fatura_por_email` no `/ligar` + páginas legais. Sem isto, o `/ligar` não traz
   o campo, `fatura_por_email` é falso e **o papel sai como sempre** — a ordem é segura.
2. POS: `fat_pontos_qr`, o tipo novo na fila, a guarda do papel, o ecrã.
3. Ensaio numa loja com o dono, antes de contar com isto.

## Testes

No ficheiro que já existe para isto — `backend/tests/faturacao/test_o_papel_sai_da_emissao_e_do_fecho.py`,
cujo cabeçalho diz a razão de existir: *"apagar a linha do `finalizar` que enfileira deixa todo o
`test_impressao.py` verde"*. Quatro casos, todos pela **rota real**:

1. sem ligação → um trabalho TALAO e zero linhas de email;
2. com a preferência ligada → zero papel e uma linha `fatura_email:<documento_id>`;
3. a colecção `fat_pontos_app` a levantar em cada escrita (molde da classe `Explode`) → **o papel sai
   à mesma** e a resposta continua `emitida` (as duas chamadas estão no mesmo `try/except`);
4. `modo: "tests"` → papel e nenhuma linha de email.

**Armadilha do banco de ensaio:** o `_com_fila` só dá unicidade a `fat_trabalhos_impressao`, e o
`DbFalsa.__getitem__` faz `setdefault` — `fat_pontos_app` nasce sem índice nenhum e uma prova de
idempotência ali não prova nada. Acrescentar a colecção ao duplo com `unico=` pela chave, senão o
caso 2 passa por acaso.

Do lado da app: um teste que prove que a segunda chamada à mesma fatura devolve `ja_enviado` e não
manda segundo email, e um que prove que sem PDF a resposta é 5xx.

## Riscos aceites

- **Um cliente pode ficar sem documento nenhum** se o envio falhar de todo e ninguém olhar para o
  alarme da loja nem para o relatório da noite. Decisão do dono.
- **"Enviado" é "o Resend aceitou", não "entregou".** Não há recetor de bounces; uma caixa cheia ou um
  relay da Apple com reencaminhamento desligado fecha a linha como feita. Não se bloqueiam endereços
  de relay — são endereços a sério e bloqueá-los tirava a funcionalidade a todos os clientes de iPhone
  com login Apple. **Por medir:** quantas contas usam relay (a leitura da base de clientes foi travada
  em 2026-09-17; repetir com autorização).
- **A poupança da Fase 1 é limitada pela adopção do QR**, que hoje é zero.
