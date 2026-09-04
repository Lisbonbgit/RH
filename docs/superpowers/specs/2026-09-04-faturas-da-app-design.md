# As faturas da app L'Açaí no módulo de Faturação

**Data:** 2026-09-04
**Estado:** especificação aprovada em conversa, por implementar
**Ramo:** `matheus-faturas-app-lacai`

## O problema

A app móvel L'Açaí emite Faturas Simplificadas reais pelo Vendus desde 18/08/2026.
Sai tudo pela **mesma caixa API** (`VENDUS_REGISTER_ID`, a "Caixa Online") e pela
**mesma série** (`06P2026`) que o POS das cinco lojas usa — mas o portal Lisbonb
nunca soube da existência delas.

Vê-se na numeração: entre a `FS 06P2026/445` e a `FS 06P2026/447`, ambas nossas,
está a `FS 06P2026/446` que o portal não tem. É da app.

**O que isto NÃO é.** Isto não explica a diferença que deu origem à conversa
(Vendus 465,77 € contra portal 521,56 €). Essa diferença tem o portal **acima** do
Vendus, e faturas da app em falta puxam o portal para **baixo**. Medido contra a
produção a 2026-09-04: desde 01/09 a app emitiu **uma** fatura, de **6,85 €**. A
divergência dos 55,79 € é outra coisa — o atraso de ~10 minutos com que o painel
do Vendus mostra os seus próprios documentos é a explicação conhecida
(ver `faturacao-lacai-vendus-vs-lisbonb-divergencias`).

O que esta obra resolve é o **buraco permanente**: hoje vale 6,85 €, e cresce com a
app. Fechado agora, nunca mais é preciso pensar nele.

## A decisão

O Lisbonb passa a **ir buscar** as faturas da app ao Vendus, de 5 em 5 minutos, e
grava-as em `fat_documentos` com a `loja_id` da loja **"App Online"**
(`98331284-ba8d-41b8-b074-4059902d68a9`), que o dono criou a 2026-09-04.

Descartadas, e porquê:

- **A app empurrar para o Lisbonb** — obrigava a mexer e a publicar no backend da
  app, e criava uma dependência nova: Lisbonb em baixo passava a ser fatura
  perdida, a menos que a app guardasse fila e reenviasse.
- **A app passar a emitir através do Lisbonb** — mexia no fluxo de pagamento, no
  PDF que segue por email e no resgate de pontos pelo ATCUD. Risco enorme para
  um problema de leitura.

Ir buscar não toca na app, é idempotente por construção (o Vendus é a única
fonte da verdade) e recupera sozinho de qualquer falha: a volta seguinte apanha
o que a anterior não apanhou.

## O que entra e o que fica de fora

Esta é a parte onde é fácil enganar-se e cara enganar-se. A Caixa Online **não
tem só faturas da app lá dentro**. Medido em produção a 2026-09-04, desde 01/09:

| O que lá está | Quantos | Valor | Entra? |
|---|---|---|---|
| `FS`/`NC` com referência a começar por `pos-` | 515 | 6.515,23 € | **Não** — são nossas, já lá estão |
| `FS` com referência `LA…` | 1 | 6,85 € | **Sim** — é a app |
| `OT` (orçamentos, feitos à mão no painel do Vendus) | 5 | 3.582,10 € | **Não** — orçamento não é venda |
| `RG` (recibos) | 2 | 14,09 € | **Não** — é o pagamento de uma fatura já contada |

Os 3.596,19 € de orçamentos e recibos são o motivo pelo qual a regra **não** pode
ser "tudo o que não começa por `pos-`". Um orçamento não é faturação nenhuma; um
recibo é dinheiro que já foi contado quando a fatura saiu. Importados, punham
3.596 € de receita inventada no Dashboard do dono.

**A regra, então.** Um documento entra se, e só se, as três forem verdade:

1. Está na caixa configurada (`VENDUS_REGISTER_ID`) — isto já exclui documentos
   de outras caixas e outras séries (havia um `DC 05P2026/56` noutra caixa).
2. O tipo é `FS` (soma) ou `NC` (subtrai). Tudo o resto — `OT`, `RG`, `PF`, `DC`,
   `GT` e o que o Vendus venha a inventar — fica de fora, registado no log.
   **Lista de permitidos, não de proibidos**: um tipo novo que apareça amanhã fica
   de fora sozinho, em vez de entrar a contar dinheiro.

   Só estes dois, e não também `FT`/`FR`, porque `documentos._TIPOS = {"FS", "NC"}`
   (documentos.py:476) responde **422** a qualquer outro no filtro do backoffice: um
   documento com tipo `FT` entrava na base e depois não se conseguia listar. A app só
   emite `FS`; se um dia emitir outra coisa, alarga-se `_TIPOS` ao mesmo tempo.
3. A referência externa **não** começa por `pos-` (essas são do nosso POS).

A app carimba as suas com `LA` + 5 dígitos (`routes_customer.py::_next_order_number`).
Uma FS de venda naquela caixa com referência vazia ou estranha (alguém a emitir
à mão pelo painel do Vendus) entra na mesma, com `origem: "app"` e um aviso no
log a dizer que a referência não era `LA…`: é receita real daquela caixa e
escondê-la era mentir ao dono. O que a protege de ser lixo é o filtro do tipo,
não o da referência.

**Modo.** Só documentos emitidos em modo real. O modo lê-se do próprio documento
(a série de testes vem prefixada por `T`, como em `FS T06P2026/3`), nunca do modo
em que o portal está agora — um documento de teste vale zero e o portal já trata o
`modo` assim em todo o lado.

## O que se grava

Um documento da app fica em `fat_documentos` com o mesmo formato dos nossos. O
formato é a lista fechada de 15 campos que `fiscal._gravar_documento` monta
(fiscal.py:1197-1250); a tradução do documento do Vendus para lá já existe e
chama-se `vendus/emissao._normaliza_documento` (emissao.py:776) — preenche `id`,
`numero`, `atcud`, `total`, `total_bruto`, `total_liquido`, `modo` e `emitido_em`.
O que ela **não** traz e o cron tem de ir buscar ao documento cru: `cliente_nif`,
`tipo` e as linhas.

Campos preenchidos: `id` (uuid nosso, não o do Vendus — é por ele que os ecrãs e o
PDF abrem o documento), `vendus_document_id`, `atcud`, `numero`, `tipo`, `modo`,
`total`, `total_bruto`, `total_liquido`, `cliente_nif`, `emitido_em`, `loja_id`,
`ext_ref`. Mais dois campos novos:

- `origem: "app"` — o que distingue estes de tudo o resto. Ausente nos nossos, que
  continuam a ser lidos como POS (nenhuma migração, nenhuma escrita nos 748
  documentos que já lá estão).
- `linhas_vendus` — as linhas como o Vendus as devolve. Guardadas agora para o
  dia em que se quiser a repartição por produto, sem ter de voltar a ler nada.

E **três campos que ficam vazios de propósito**: `venda_id`, e por consequência a
caixa e o operador. Não há conta de balcão, não há sessão de caixa, não há quem
atendeu. O `ext_ref` guarda a referência do Vendus (`LA00028`), que é o que liga
a fatura ao pedido na app.

**O dia a que pertence.** O `emitido_em` é a hora que o Vendus carimbou
(`local_time`), convertida para UTC — nunca a hora a que a sincronização a
descobriu. A fatura das 23h50 de ontem, importada às 00h05, tem de contar para
ontem. Isto não se escreve de novo: `vendus/emissao._instante_do_vendus`
(emissao.py:736) já o faz, e já trata o caso da hora sem fuso como hora de Lisboa.

**O formato importa mais do que parece.** O `emitido_em` é uma **string** ISO com
offset (`...+00:00`), como `fiscal._agora()` produz — e os filtros por intervalo
comparam **strings**, não datas (dashboard.py:498, relatorios.py:620). Um sufixo
`Z` ordena depois de `+` e partia silenciosamente os limites dos intervalos.

**Sem fecho de caixa.** A loja "App Online" não tem sessão de caixa nenhuma, e
não vai ter. Cada fatura conta para o dia (Lisboa) em que o Vendus a emitiu;
virou a meia-noite, conta para o dia seguinte. Não há Z, não há gaveta, não há
contagem de dinheiro — a app cobra por Stripe.

## Onde aparece

- **Dashboard** — entra em Faturação Hoje / Mensal / Anual e ganha o seu cartão de
  loja, como as outras cinco.
- **Relatórios** (as nove vistas) — **é aqui que está o trabalho a sério**, e o
  mapeamento do código mostrou que é pior do que parecia.

  `relatorios._artigos_da_fatura` começa com `if not venda: return []`
  (relatorios.py:391) — **devolve lista vazia, não levanta excepção**. O documento
  não é descartado: entra na lista de eventos (relatorios.py:561) com
  `bruto_c`/`liquido_c`/`quantidade` a somar uma lista vazia, ou seja **zero**. Sem
  fazer nada, uma fatura da app aparece com o valor certo no Dashboard (que lê
  `total_bruto` do documento, dashboard.py:120) e a **0,00 €** nas nove vistas dos
  Relatórios. Os dois números passam a discordar sem nenhum estar visivelmente errado.

  Pior: o aviso que existe precisamente para isto — "N faturas de hoje não se
  deixaram repartir por artigo" — conta `len(documentos) - len(eventos)`
  (dashboard.py:519), e como o evento **é** criado, o contador fica a zero. A
  ausência nascia invisível.

  **A correcção:** em `relatorios.eventos_dos_documentos`, quando não há venda mas
  o documento tem `linhas_vendus`, constroem-se os artigos a partir dessas linhas
  (`amounts.gross_total`, `amounts.net_total`, `qty`, `title`). Isto resolve as nove
  vistas de uma vez — dinheiro, quantidade, e as vistas por artigo — em vez de
  remendar cada uma.

  **O custo tem de ser `None`, nunca 0.** Com `artigos = []`, `custo_c` sai a **0**
  e não a `None` (`any([])` é `False`, `sum([])` é `0` — relatorios.py:578), e um
  custo de 0 € contra 6,85 € de venda dá **100% de margem** no relatório de
  rentabilidade. Não sabemos o custo dos artigos da app; `None` é a verdade, e o
  motor já sabe mostrar "—".
- **Produtos e Categorias** — os artigos da app entram como "App L'Açaí (sem
  correspondência)" (o `_SEM_DEFINICAO` que o motor já usa), com o dinheiro e a
  quantidade certos. Assim o total destas duas vistas continua igual ao do Diário.
  Casar os artigos com o nosso catálogo fica para depois.
- **Documentos** — na lista com filtro de loja; ao abrir mostra "Origem: App
  L'Açaí", as linhas do Vendus, o NIF, e o PDF do Vendus. **Sem Reimprimir** — não
  há talão nosso nem impressora naquela loja.
- **Clientes** — um NIF pedido na app passa a aparecer, com as compras dele.
- **Email diário das 23:30** — a loja aparece com faturação e nº de documentos; a
  coluna da caixa fica vazia (não "não fechou") e não entra na repartição por tipo
  de pagamento, porque a app não passa pela gaveta.
- **Movimentos de Caixa, Fechos, Z** — a loja nunca lá aparece.

## Como corre

- **A leitura do Vendus já está escrita.**
  `ClienteEmissaoVendus.listar_documentos_por_dia(data, register_id)`
  (emissao.py:475) faz o dia inteiro, paginado por `X-Paginator-Pages`, e recusa-se
  a sair para a rede se o `register_id` não for o configurado. Medido a 2026-09-04:
  devolve os 128 documentos de 01/09 e a `FS 06P2026/446` lá está.

  **Mas a lista não chega.** Medido: a lista (mesmo com `view=detailed`) **não traz
  `atcud` nem `items`**. Os dois vêm só do `GET documents/{id}/`, e esse **não aceita
  `view`** (responde 403 P001). Logo: um método novo `ler_documento(id)` em
  `ClienteEmissaoVendus`, chamado uma vez por documento novo.

  **Armadilha medida:** na lista o `status` é a string `"N"`; no documento por id é
  um **dicionário** `{"id": "N", ...}`. Quem escrever `status == "A"` para detectar
  anulações no detalhe nunca acerta.

  O cliente é **síncrono** — o cron embrulha-o em `asyncio.to_thread`, como
  `fiscal.py:1808` já faz.
- **Endpoint** `POST /api/faturacao/cron/sincronizar-app?key=<CRON_KEY>`, protegido
  por `CRON_KEY` com `compare_digest`, no mesmo padrão de `/cron/relatorio-diario`.
- **Script** `faturacao-app-cron.sh` na raiz do repositório, com a linha de
  `crontab` escrita lá dentro e a explicação da hora — o servidor corre em UTC.
  De **5 em 5 minutos**.
- **Botão "Sincronizar agora"** no backoffice, junto à definição da loja, para não
  ser preciso esperar.
- **Janela.** Cada volta relê **hoje e ontem** (apanha atrasos e anulações). O
  histórico desde **01/09/2026** é lido uma vez, na primeira volta, dia a dia.
- **O histórico faz-se uma vez, à mão.** O cron sabe ler dois dias e mais nada. Os
  dias de 01/09 até hoje correm-se uma única vez, no ensaio, com a lista de dias
  passada à mão. Guardar estado de retoma para uma coisa que acontece uma vez era
  código a mais para manter para sempre; e se falhar, repete-se — é idempotente.
- **A loja é uma definição**, não um valor no código: `fat_definicoes`, escolhida no
  backoffice. Sem loja escolhida a sincronização **recusa-se a correr** e diz
  porquê. Nunca adivinha.

## Quando corre mal

- **Vendus em baixo, lento ou a limitar (429)** — a volta falha inteira, não deixa
  nada a meio, regista porquê. A volta seguinte apanha tudo. Nada do portal depende
  disto: é um cron próprio, num módulo próprio.
- **Repetidos** — os índices únicos de `vendus_document_id` (db.py:132) e `atcud`
  (db.py:133) já existem. Chegar duas vezes grava uma; o conflito é ignorado em
  silêncio, não é erro.

  **Mas os dois são únicos SIMPLES, não `sparse`** — dois documentos com o campo a
  `None` colidem um com o outro. Um documento do Vendus sem `atcud` ou sem `id`
  **não se grava**: fica de fora, contado e registado. E o `ext_ref` tem índice único
  **parcial sobre strings** (db.py:153-156): a string vazia É uma string, por isso
  gravar `ext_ref: ""` faria a segunda fatura da app rebentar. Referência vazia
  grava-se `None`, nunca `""`.
- **Anulada depois de importada** — como cada volta relê hoje e ontem, se o estado
  passar a `A` marca-se `anulado` e deixa de contar. **Uma anulação com mais de dois
  dias não é apanhada** — é o limite conhecido, e está aqui escrito para não ser
  uma surpresa.
- **Notas de crédito** — a app hoje não emite nenhuma (`services_vendus.py` só tem
  `emit_fs_invoice`). Se aparecer uma naquela caixa sem o nosso prefixo, entra como
  `NC` e subtrai.
- **Configuração em falta** — caixa do Vendus não configurada ou loja não escolhida:
  recusa e diz qual falta.
- **O que nunca faz** — escrever no Vendus; tocar em `fat_vendas`, sessões de caixa
  ou reservas fiscais; chamar `registers/movements` (fechava a caixa por baixo da
  app).

## Como se prova

1. **Partes puras** — classificar (nosso / app / a ignorar), converter um documento
   do Vendus no nosso formato, cêntimos, fuso, e construir os artigos a partir das
   linhas do Vendus. Com os casos reais medidos como material de teste: um `OT` de
   740,15 € fica de fora, um `RG` fica de fora, a `FS 06P2026/446` (6,85 €, um
   "Açaí Mini" a 13%) entra e vale 6,85 € nas nove vistas com custo `None`.
2. **Rotas** com um Vendus falso. Nunca a rede.
3. **Ensaio contra a produção, sem gravar nada** — a sincronização corre em modo
   simulação e diz "encontrei N, ia gravar isto". Comparo com o Relatório Diário do
   Vendus **antes** de a deixar escrever.
4. **Depois de ligada** — os totais de 01/09 e 02/09 no Lisbonb têm de ficar iguais
   aos do Vendus para os mesmos dias e a mesma caixa. É este o critério de sucesso,
   e os números apuram-se no ensaio (o valor de 01/09 no portal é hoje 1.545,65 €;
   com a fatura da app passa a 1.552,50 €).

## As armadilhas medidas, num sítio só

Estão espalhadas pelo documento; ficam aqui juntas porque cada uma delas, sozinha,
chega para pôr números errados no ecrã do dono.

| Armadilha | O que acontece se se ignorar |
|---|---|
| A lista do Vendus não traz `atcud` nem `items` | Documento sem ATCUD não se grava (índice único) e fica tudo a zero nos artigos |
| `GET documents/{id}/` não aceita `view` | 403 P001 |
| `status` é string na lista, dicionário no detalhe | `status == "A"` nunca acerta e nada é marcado como anulado |
| `atcud` e `vendus_document_id` são únicos **simples** | Dois documentos com `None` colidem entre si |
| `ext_ref` é único parcial **sobre strings** | Gravar `""` faz a segunda fatura da app rebentar |
| `total_liquido` não tem campo alternativo | O Dashboard "sem IVA" mostra a app a 0,00 € |
| `emitido_em` é comparado como **string** | Um `Z` em vez de `+00:00` parte os intervalos em silêncio |
| `_artigos_da_fatura` devolve `[]`, não levanta | A app vale 0,00 € nas nove vistas e o aviso de "por repartir" fica a zero |
| `custo_c` de uma lista vazia é `0`, não `None` | 100% de margem no relatório de rentabilidade |
| `documentos._TIPOS = {"FS", "NC"}` | Um `FT` entra na base e depois dá 422 a listar |

## O que fica de fora, de propósito

- **Repartição por produto** das faturas da app (casar os artigos do Vendus com o
  nosso catálogo). Fica para quando o dono a pedir; as `linhas_vendus` já ficam
  guardadas para isso não custar nada.
- **Reimprimir** talão de um documento da app.
- **Anulações com mais de dois dias.**
- **Importar antes de 01/09/2026** — decisão do dono; a app emite desde 18/08 e
  esses dias ficam como estão.
