# Pontos L'Açaí no POS das lojas — desenho

**Data:** 2026-09-15 · **Ramos:** `matheus-pontos-no-pos` em `~/applacai` (a partir de `main` 17822fb) e em `~/Developer/RH` (a partir de `main` f455a1b). O mesmo documento vive nos dois repos.

## Porquê

O talão das lojas é um bilhete ao portador: qualquer pessoa que o apanhe lê o QR fiscal na app e fica com os pontos. O prazo de 5 minutos está ligado desde 2026-09-08 e as burlas continuam. O POS próprio está nas 5 lojas desde 2026-08-27, por isso a compra ao balcão já passa toda por um sistema nosso.

A regra nova: **ganha os pontos quem mostra a app na caixa antes de pagar**. O talão das lojas deixa de dar pontos.

## Decisões do dono

1. A funcionária lê o QR que o cliente mostra na app: câmara do Surface, ou o leitor incorporado do POS HP (numa loja).
2. Os pontos só entram depois de a Fatura Simplificada sair com sucesso no Vendus.
3. O "Ler fatura" da app deixa de dar pontos nas faturas das lojas **no dia em que sair o build** com o QR. Faz-se com um interruptor no backoffice, sem deploy.
4. Nota de crédito sobre uma fatura com pontos **retira os pontos na proporção** do valor devolvido. O saldo nunca fica negativo.
5. Os pontos contam sobre o **total sem a caução** da embalagem.
6. Depois de ler o QR, o POS mostra **só o primeiro nome** do cliente.
7. **Sem QR não há pontos.** Não existe código escrito à mão.
8. Tudo em ramo próprio; nada vai para o ar até estar tudo certo.

As restantes regras são as do "Ler fatura" de hoje: 1 ponto por euro arredondado para cima (`points_per_euro`), multiplicador de campanha, nada em Uber Eats/Glovo/Bolt, teto de `INVOICE_MAX_VALUE` (100 €) por fatura.

## Fora de âmbito (2.ª fase)

- Relatório de concentração (a mesma conta pontuada muitas vezes, a mesma funcionária a associar sempre a mesma conta). **Os dados ficam gravados desde o primeiro dia.**
- Tetos de pontos por conta por dia.
- Subir o brilho do ecrã quando o QR abre (é módulo nativo; só se as leituras falharem na prática).

## Fluxo

```
Cliente (app)                 POS (browser)              RH backend                      App backend
Início → Código → QR ──lido──▶ cartão "Pontos"  ──────▶ POST /pos/pontos/ler ──────────▶ POST /pos-integracao/ligar
                                "Pontos para: Ana ✓" ◀── {ligacao_id, primeiro_nome} ◀── consome o token, cria ligação
                              EMITIR ─────────────────▶ finalizar (dados_pagamento.pontos_ligacao)
                                                          FS emitida → _ligar_venda_ao_documento
                                                          → fila fat_pontos_app (chave única)
                                                          → envio imediato + cron de 1 em 1 min ─▶ POST /pos-integracao/creditar
                                                                                                    regras → invoice_claims → award
                              Nota de crédito ────────▶ NC emitida → fila (estorno) ─────────▶ POST /pos-integracao/estornar
```

## App L'Açaí — servidor (sem build)

### Código do QR

- `POST /customer/qr` passa a gerar `LQ` seguido de 22 caracteres de `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` (sem I, O, 0, 1). Validade de 45 s e uso único, como hoje.
- Só maiúsculas e dígitos: um leitor em modo teclado com o layout trocado troca símbolos, e o Caps Lock inverte a caixa. O servidor normaliza o que recebe (`strip` + remover espaços + `upper`).
- Nenhuma app publicada chama esta rota hoje, por isso mudar o formato não parte nada.

### Autenticação entre servidores

- Router novo `routes_pos_integracao.py`, prefixo `/api/pos-integracao`.
- Chave em `POS_INTEGRACAO_CHAVE` (env). Cabeçalho `X-Service-Key`, comparado com `hmac.compare_digest`.
- Chave não configurada → 503. Chave errada ou em falta → 401.
- Nenhuma destas rotas aceita JWT de cliente, loja ou admin.

### `POST /api/pos-integracao/ligar`

Pedido: `{codigo, loja_nome, operador_nome}`.

1. Normaliza o código e consome o token **atomicamente**: `find_one_and_update({token, used: false, expires_at > agora}, {$set: {used: true, used_at, used_by: "pos"}})`. Duas leituras seguidas do mesmo QR nunca criam duas ligações.
2. O utilizador tem de existir, ser cliente e não estar apagado/anonimizado nem bloqueado.
3. Falha em 1 ou 2 → **404** `{estado: "recusado", motivo: "qr_invalido"}` (a mesma resposta nos dois casos).
4. Cria `pos_ligacoes`: `{id (uuid), user_id, criada_em, loja_nome, operador_nome, usada_em: null, atcud: null}`.
5. Responde **200** `{ligacao_id, primeiro_nome}` (primeira palavra do nome).

### `POST /api/pos-integracao/creditar`

Pedido: `{ligacao_id, documento_id, atcud, numero, emitido_em (ISO, UTC), total, caucao, meios_pagamento: [id Vendus], loja_nome, operador_nome}`. Valores em euros com 2 casas.

Recusas de negócio respondem **200** `{estado: "recusado", motivo}` e **não se repetem**. Os motivos:

| motivo | quando |
|---|---|
| `ligacao_desconhecida` | não existe ligação com esse id |
| `ligacao_expirada` | `emitido_em` fora de `[criada_em − 2 min, criada_em + 2 h]` |
| `ligacao_ja_usada` | a ligação já creditou **outro** ATCUD |
| `plataforma` | algum meio de pagamento é Uber Eats/Glovo/Bolt (`plataformas.py`) |
| `sem_valor` | `total − caucao ≤ 0` |
| `acima_do_teto` | `total − caucao > INVOICE_MAX_VALUE` |
| `fatura_bloqueada` | o ATCUD está em `blocked_atcuds` |
| `fatura_de_outra_conta` | o ATCUD já está em `invoice_claims` com **outro** utilizador (fica no log como aviso) |

Caminho feliz:

1. `base = total − caucao`; `pontos = ceil(base × points_per_euro)`; multiplicador de campanha como no claim (`int(pontos × mult)` se `mult > 1`).
2. Grava em `invoice_claims` (índice único em `atcud`, normalizado): `{id, atcud, doc_no: numero, user_id, total: base, points, invoice_date (AAAAMMDD de Lisboa a partir de emitido_em), claimed_at, origem: "pos", pos: {documento_id, loja_nome, operador_nome, ligacao_id}, creditado_em: null}`.
3. `award(source="invoice", spent=base, description="Compra na loja · {numero}" [+ " (pontos ×N)"], extra={atcud})`, depois `advance_on_purchase`.
4. Marca `creditado_em` no claim e `usada_em`/`atcud` na ligação.
5. Responde **200** `{estado: "creditado", pontos}`.

**Idempotência:** se o ATCUD já estiver em `invoice_claims` com o **mesmo** utilizador, responde `{estado: "ja_creditado", pontos}`. Se esse claim ficou a meio (`creditado_em` null), primeiro completa-o: procura em `transactions` `{user_id, source: "invoice", atcud}`; se existir marca `creditado_em`, senão chama `award`. Um reenvio nunca credita duas vezes e nunca deixa uma fatura "usada" sem pontos.

Erros técnicos (Mongo em baixo, exceção) → 5xx: o RH volta a tentar.

### `POST /api/pos-integracao/estornar`

Pedido: `{atcud_origem, nc_id, numero_nc, valor_nc, caucao_nc}`.

1. O claim do `atcud_origem` tem de ter `origem: "pos"` e `creditado_em`. Senão → **200** `{estado: "sem_efeito"}`.
2. Idempotência por `nc_id`: o `$push` em `claim.estornos` só entra se o `nc_id` ainda lá não estiver (update condicional). Se já estava → `{estado: "ja_estornado", pontos}`.
3. `devolvido = soma das bases das NCs desta fatura (valor_nc − caucao_nc)`; `alvo = min(points, round_half_up(points × devolvido / claim.total))`; `retirar = alvo − já retirado`.
4. Retira `retirar` pontos sem deixar o saldo negativo, com as mesmas peças da reversão dos pedidos (`estorno_de_pontos`, `_tirar_ao_mes`, `_desfazer_marcos`), transação `source="estorno"`, `description="Devolução na loja · {numero_nc}"`.
5. Responde **200** `{estado: "estornado", pontos: retirar}`.

### Interruptor do "Ler fatura" nas lojas

- Campo novo na config `loyalty`: `faturas_da_loja_no_ler_fatura` (booleano, **por omissão `true`**, ou seja, tudo fica como hoje).
- Backoffice → Definições: "Faturas das lojas dão pontos no Ler fatura" (ligado/desligado).
- Em `/customer/claim-invoice`, com o documento do Vendus já em mãos: se o interruptor estiver desligado e o `external_reference` começar por `pos-`, recusa com a mensagem *"Nas lojas, os pontos ganham-se na caixa: antes de pagar, mostra o QR da app (Início → Código)."* A mensagem vem do servidor, por isso a app antiga mostra-a.

## App L'Açaí — ecrã (precisa de build, **só com autorização do dono**)

- Início: a estatística "Código" do cartão de pontos abre o ecrã **"O meu QR"**:
  - QR grande em fundo branco com margem, o código de cliente por baixo e "renova em Ns";
  - texto: "Mostra este QR na caixa antes de pagar para ganhares pontos.";
  - pede um token novo a cada 40 s e sempre que o ecrã ganha foco; sem rede, mostra o erro e um "Tentar de novo";
  - mantém o ecrã aceso enquanto está aberto (`expo-keep-awake`, já instalado).
- A biblioteca `react-native-qrcode-svg` e o `react-native-svg` já estão no binário 1.0.6.
- `app.config.js`: o texto da permissão da câmara deixa de falar do caixa ("usada para ler o QR Code das faturas").
- FAQ (`institucional.tsx`): explica que nas lojas os pontos se ganham a mostrar o QR na caixa.

## POS (RH) — ecrã

- **Cartão novo "Pontos L'Açaí"** no Finalizar, entre Cliente e Pagamento:
  - vazio: botão "Ler QR do cliente";
  - ligado: "Pontos para: {primeiro_nome} ✓" e "Remover".
- **Janela "Ler QR"** com dois caminhos:
  - campo de texto com foco automático, para o leitor do POS HP (escreve o código e dá Enter);
  - botão "Usar câmara": `getUserMedia` com escolha de câmara e descodificação com `jsQR`. O Chrome para Windows não tem `BarcodeDetector`.
  - O código lido vai para `POST /api/faturacao/pos/pontos/ler`.
  - Erros: "QR inválido ou expirado — peça ao cliente para abrir o QR outra vez." / "Não foi possível falar com a app agora. A fatura pode seguir sem pontos."
- A ligação guarda-se em `sessionStorage` **presa ao id da conta**, com o mesmo molde do NIF. Numa conta dividida ou separada não passa para as partes: lê-se o QR na parte de quem mostra a app.
- **O cartão nunca bloqueia o EMITIR** (não entra no `motivoBloqueio`).
- **Campo do NIF:** uma alteração que traga letras é ignorada por inteiro. É assim que se reconhece o leitor a escrever o QR com o foco no sítio errado; senão os dígitos do código iam parar ao NIF da fatura.

## POS (RH) — servidor

### Ler

`POST /api/faturacao/pos/pontos/ler` (sessão do operador) com `{venda_id, codigo}`:

- A venda tem de estar aberta e ser da loja do token.
- Chama `/pos-integracao/ligar` com o nome da loja e do operador do token.
- Devolve `{ligacao_id, primeiro_nome}`. **Não grava nada na venda.**
- App em baixo ou sem configuração → 503 com a mensagem acima. QR recusado → 404.

### Emitir

- `PedidoFinalizarVenda` ganha `pontos_ligacao: {id, primeiro_nome} | null`.
- Entra em `dados_pagamento` **sempre presente** (null quando não há), como o `cliente_nif`. Uma tentativa falhada nunca deixa um cliente antigo agarrado à venda.

### Fila `fat_pontos_app`

Documento: `{id, chave (única), tipo: "credito"|"estorno", documento_id, nc_documento_id, venda_id, payload, estado, pontos, motivo, tentativas, ultimo_erro, criado_em, atualizado_em, proxima_tentativa_em, a_enviar_ate}`.

- `estado` ∈ `pendente | feito | recusado | sem_efeito | falhado`.
- **Crédito:** no fim de `_ligar_venda_ao_documento` (fiscal.py), a única escrita de "emitida" por onde passam os 5 caminhos. Dentro de `try/except`, ao lado do stock. Se a venda tiver `pontos_ligacao` e o documento for do modo `normal`, insere a linha com chave `credito:{documento_id}`. `DuplicateKeyError` é engolido, porque este gancho corre mais de uma vez por venda. Documentos em modo `tests` nunca enfileiram.
- **Estorno:** logo depois da escrita "emitida" da nota de crédito (nota_credito.py), se a FS de origem tiver linha de crédito, insere `estorno:{nc_documento_id}`.
  - Um estorno só se envia com o crédito já `feito`.
  - Crédito `recusado` ou `falhado` → estorno fica `sem_efeito`.
- **Envio:**
  - `httpx.AsyncClient`, timeout de 4 s, cabeçalho `X-Service-Key`.
  - URL em `APP_LACAI_URL` (em produção `http://olacai-api:8001`, pela rede interna); chave em `APP_LACAI_CHAVE`.
  - Antes de enviar, reserva a linha com `find_one_and_update({estado: "pendente", proxima_tentativa_em ≤ agora, a_enviar_ate < agora})`: dois workers e o cron nunca enviam a mesma linha ao mesmo tempo. A app é idempotente de qualquer forma.
- **Resposta:**
  - `creditado`/`ja_creditado`/`estornado`/`ja_estornado` → `feito` + pontos;
  - `recusado` → `recusado` + motivo;
  - `sem_efeito` → `sem_efeito`;
  - 401/503/5xx/rede/timeout → continua `pendente`, `tentativas + 1`, `ultimo_erro`, próxima tentativa com espera crescente (1, 2, 5, 10, 30 min…). Ao fim de 24 h passa a `falhado`.
  - Sem `APP_LACAI_URL`/`APP_LACAI_CHAVE` → fica `pendente` com "integração não configurada". Não se perde nada.
- **Tentativa imediata:** depois de a FS sair, em segundo plano. Nunca atrasa nem parte a resposta do EMITIR.
- **Cron:** `POST /api/faturacao/cron/pontos-app` com a `CRON_KEY` (mesmo padrão da sincronização) e um script de crontab de 1 em 1 minuto.

### Backoffice

- O detalhe da fatura em Documentos mostra a linha **"Pontos L'Açaí"**: "17 pontos para Ana" · "A tentar enviar (3 tentativas — último erro: …)" · "Recusado: pagamento por plataforma" · "Falhou ao fim de 24 h".
- O detalhe da nota de crédito mostra o estorno.

## Ordem de arranque

1. Tudo nos ramos, com os testes verdes.
2. Deploy do servidor da app com as rotas novas e o interruptor **ligado** (o Ler fatura continua igual) + `POS_INTEGRACAO_CHAVE`. É inofensivo: ninguém chama as rotas.
3. Build 1.0.7 (iOS + Android) **com autorização do dono**, juntando o que houver em fila para a app.
4. Com o build aprovado nas lojas: deploy do RH + `APP_LACAI_URL`/`APP_LACAI_CHAVE` + crontab.
5. Teste real com o dono numa loja: QR do telemóvel → FS real → pontos na app → nota de crédito → pontos retirados.
6. O dono desliga "Faturas das lojas dão pontos no Ler fatura".

## Testes

**App:**
- formato e normalização do código;
- ligação atómica (duas leituras simultâneas → uma ligação);
- chave: 503 sem configuração, 401 errada;
- cada motivo de recusa da tabela;
- caução fora da base, multiplicador;
- idempotência: mesmo utilizador, outro utilizador, claim a meio;
- estorno: parcial duas vezes, total, nunca negativo, idempotente por `nc_id`;
- interruptor: `pos-` recusado quando desligado e aceite quando ligado; FS de fora do POS continua a passar.

**RH:**
- `pontos_ligacao` sempre presente em `dados_pagamento`;
- o gancho enfileira uma vez em todos os caminhos até "emitida";
- modo `tests` não enfileira;
- máquina de estados do envio contra respostas simuladas com as formas exatas desta spec;
- reserva da linha;
- NC enfileira estorno; estorno espera pelo crédito;
- caminhos novos do `lib/pos.js` confrontados com o router (`test_caminhos_do_pos.py`);
- campo NIF ignora letras.

**As guardas principais validam-se por mutação:** um teste só conta depois de o ver falhar pela razão certa.

## Riscos aceites

- **Uma funcionária pode ler o QR da própria conta** em vendas de clientes que não querem pontos. Fica registado (operador, loja, fatura) para o relatório da 2.ª fase.
- **Um screenshot enviado a um amigo** dentro dos 45 s funciona.
- **Clientes com versões antigas** ficam sem pontos nas lojas até atualizarem; a mensagem do servidor diz-lhes como.
