# A Conciliação: o Excel da diretora financeira dentro do Financeiro

**Data:** 2026-09-05
**Estado:** especificação aprovada em conversa, por implementar
**Ramo:** `matheus-conciliacao`

## O problema

A diretora financeira faz o fecho do mês num ficheiro Excel — `Financeiro L'açai 2026`,
um separador por mês, de Fevereiro a Dezembro. Dentro de cada separador:

- **Despesas e renda mensal** — uma tabela com `Categoria · Descrição · Montante ·
  Contas a Pagar · Anotações`, uma linha por movimento do banco, copiada à mão.
- **Resumo do orçamento** — o total de cada categoria (Entradas, Utilitários,
  Serviços, Fornecedor, Supermercado, Seguros, Impostos, Marketing…).
- **Resumo em %** — cada categoria a dividir pelo total de Entradas.
- **Valor Contas** — o saldo de cada banco (Millennium 3.192,91 €, Revolut 41,77 €).
- **Plataformas** — quanto entrou por Glovo, Uber, Bolt, Stripe, Fecho TPA,
  Vendas Diretas.

O custo disto não é o tempo dela. É que **o fecho do mês vive fora do sistema**:
ninguém mais lhe toca, não se cruza com as faturas que já estão no portal, não se
audita, e no dia em que o ficheiro se perder perde-se o ano.

O portal já tem os movimentos do banco (`fin_movements`) e as faturas
(`fin_invoices`), e já sabe ligar uns aos outros. O que não tem é **o ecrã onde ela
trabalha o mês**.

## O que o sistema já tem — e o que não tem

Medido por leitura do repo a 2026-09-05. Três pressupostos da conversa inicial
estavam errados e é melhor tê-los por escrito:

| Pressuposto | Verdade |
|---|---|
| "os extratos dos bancos entram por email" | **Não.** Por email entram só faturas de fornecedores (`fin_cron_ingest`, lidas pelo Gemini). O extrato entra à mão no ecrã Extrato: `.xlsx` do Millennium (parseado no *browser*) ou PDF (`POST /fin/movements/import-pdf`). |
| "as categorias do Excel existem no sistema" | **Não.** A lista real é `mercadoria, rendas, energia_agua, salarios, servicos, impostos, outros`, escrita à mão em `FinPagamentos.js:48` e duplicada em `FinRelatorios.js:35`. Só *Serviços* e *Impostos* coincidem. |
| "não existe conciliação" | **Existe, e é boa.** `_fin_reconcile_score` (server.py:4990) pontua pares fatura↔movimento, `_fin_learn_carimbo` (4955) aprende a assinatura de cada fornecedor, `_fin_auto_reconcile` (5141) corre sozinho depois de cada importação. Tem ecrã numa aba do Pagamentos. **Não tem um único teste.** |

O que **não existe** e vai ter de se construir:

- `category` no movimento. O documento gravado (server.py:4725-4741 e 6780-6796)
  não tem o campo. Categoria hoje só existe na *fatura*.
- **Saldo por conta bancária.** Os dois sítios que calculam saldo (server.py:7141 e
  8777) somam todas as contas num número só.
- Anexar ou ligar documento a um movimento de **entrada**. Toda a maquinaria
  existente está travada a `amount < 0`.

## A decisão

Uma secção nova no Financeiro, por baixo do Extrato:
`/admin/financeiro/conciliacao`, entrada nova em `AdminLayout.js:109-113`.

**Divisão de trabalho:** o **Extrato é a porta** (carregar o ficheiro do banco);
a **Conciliação é a mesa de trabalho** (o mês inteiro, classificado, anotado,
com documentos ligados).

**Uma linha = um movimento bancário.** A verdade é o extrato. Mas ela pode
acrescentar linhas à mão (o "Dinheiro Restante Mês Anterior" do Excel), e essas
ficam **marcadas como manuais** — nunca se confundem com dinheiro que passou
mesmo na conta.

**Cada empresa tem o seu Excel.** Empresa e mês vêm do seletor global do topo
(`useOutletContext`) e do `MonthPicker`, como em todas as páginas do Financeiro.
A lista de categorias é **por empresa**.

## O modelo de dados

Três campos novos em `fin_movements`, todos opcionais:

| Campo | Tipo | Para quê |
|---|---|---|
| `category` | string (slug) | a coluna Categoria; slug, não etiqueta — mudar o nome não órfã as linhas |
| `note` | string | a coluna Anotações ("Ordenado Rafaela", "Já cobrado em Agosto") |
| `manual` | bool | linha escrita à mão; sem `dedup_key`, sem saldo, apagável |

A coluna **Descrição** não precisa de campo novo: mostra `title` se existir, senão
`description` (o texto cru do banco). Editar escreve em `title` — que é o campo
que o Extrato já chama "Justificação". É o mesmo campo, com dois nomes; **passa a
chamar-se Descrição nos dois ecrãs.**

Um campo novo em `fin_companies`:

| Campo | Tipo | Para quê |
|---|---|---|
| `categorias` | `[{id, label}]` | a lista da empresa, editável em Financeiro → Configurações |

Guardado no documento da empresa, não em coleção nova: é uma lista de quinze
strings. O `PUT /fin/companies/{id}` que já existe passa a aceitá-la.

## As categorias: uma língua só

Decisão: **a lista dela passa a ser a lista do sistema**, partilhada com as
faturas. Só assim o que ela classifica na Conciliação é o que aparece no relatório
de Resultados. Duas listas dariam dois números para a mesma pergunta.

Lista por omissão de cada empresa (a do Excel, mais as duas que só existem no
sistema, para nada ficar órfão):

`entradas · salarios · utilitarios · servicos · impostos · investimento ·
supermercado · fornecedor · seguros · marketing · cartoes_credito ·
dominios_sites · transporte · rendas · outros`

Migração única das faturas já gravadas:

| Valor de hoje | Passa a |
|---|---|
| `mercadoria` | `fornecedor` |
| `energia_agua` | `utilitarios` |
| `salarios` | `salarios` |
| `servicos` | `servicos` |
| `impostos` | `impostos` |
| `rendas` | `rendas` |
| `outros` | `outros` |

`CAT_LABEL` sai de `FinRelatorios.js:35` e a lista sai de `FinPagamentos.js:48`;
as duas passam a ler a lista da empresa. **Extrair para `lib/finance.js` antes de
mexer em mais nada** — senão a coluna nova cria uma terceira cópia da lista.

Nota: `entradas` é uma categoria de movimento, não de fatura. O relatório de
Resultados só vê faturas, por isso nunca a soma.

## A tabela mensal

Molde: `FinPagamentos.js:903-960` — `<Table>` do shadcn dentro de
`<div className="overflow-x-auto">`, com o `<Select>` inline dentro da `TableCell`
(linhas 930-943) que já é exatamente o padrão da célula editável.

| Coluna | Comportamento |
|---|---|
| **Data** | `date_lancamento`, ordenada. Não existe no Excel; existe aqui porque isto é um extrato bancário. Tira-se se ela não a quiser. |
| **Categoria** | `<Select>` na própria célula, lista da empresa |
| **Descrição** | editável no sítio (Enter/blur guarda), por omissão o texto do banco |
| **Montante** | `eur()`, vermelho a sair, verde a entrar — como no Extrato |
| **Faturas** | ver abaixo |
| **Anotações** | editável no sítio, texto livre |

**Coluna Faturas.** Se o movimento já tem fatura ligada: mostra
`fornecedor · nº`, abre o PDF, e tem um `×` para desligar. Se não tem, abre um
diálogo com, por esta ordem:

1. **Sugestões do motor** — `GET /fin/reconcile/suggestions`, com o badge de
   confiança e os chips de razão que o Pagamentos já desenha (1030-1108).
2. **Procurar fatura** — por fornecedor ou número.
3. **Anexar PDF** — `POST /fin/movements/{id}/attach`.

As faturas que as lojas mandam pelo Estoque **já entram nesta lista sem trabalho
nenhum**: são `fin_invoices` com `source="estoque"`, não são coleção à parte.

**Linhas à mão.** Botão `+ Linha` acima da tabela; pede data, categoria,
descrição, montante. Grava com `manual: true` e um selo visível na linha. Só estas
se apagam.

## Os cartões de topo

Quatro blocos, na ordem do Excel. Molde visual: `Kpi` de `FinRelatorios.js:43-60`
e a linha label/valor de `FinRelatorios.js:386-396`.

1. **Resumo do orçamento** — total por categoria do mês.
2. **Resumo em %** — cada categoria a dividir pelo total de Entradas.
   *A folha dela tem os rótulos trocados* — "Entradas/TVDE 2,02%" é na verdade o
   Marketing (153,91 / 7.630,69) e "Entradas/Fornecedor 3,00%" devia dar 31,03%.
   Fazemos a conta certa; não copiamos o erro.
3. **Valor Contas** — saldo de cada banco e total. **Único cartão que precisa de
   backend novo.**
4. **Plataformas** — as linhas de categoria `entradas` agrupadas pela Descrição.
   Sem campo novo: ela escreve "Glovo", "Fecho TPA Teya", e o cartão monta-se.

O "Valor após Pagar Contas" do Excel cai — foi-se com a coluna *Contas a Pagar*,
que ela dispensou. No lugar, um quinto cartão **Faturas por pagar**, que sai de
graça do `GET /fin/reconcile/pending` (já sabe vencimento efetivo e débitos
diretos).

Os cartões 1, 2 e 4 calculam-se **no ecrã**, a partir dos movimentos do mês que a
página já carregou — não levam endpoint. O 5 chama um endpoint que já existe. Só
o 3 leva código novo no servidor.

## O que se constrói no backend

| O quê | Onde |
|---|---|
| `GET /fin/bank-accounts/balances?company_id&month` | saldo por conta: último movimento de cada conta, com o mesmo desempate `[("date_lancamento",-1),("_id",-1)]` que server.py:7141 usa. **Não pode ser feito no browser** — o `_id` vem excluído de todas as projeções, e num dia com vários movimentos na mesma conta o saldo sairia arbitrário. |
| `PUT /fin/movements/{id}` | aceita `{title?, category?, note?}`. O `set-title` fica como está (o Extrato usa-o). |
| `POST /fin/movements` | linha manual. `manual: true`, sem `dedup_key`, sem `balance`. |
| `DELETE /fin/movements/{id}` | **só** se `manual` for verdadeiro. |
| `categorias` no `PUT /fin/companies/{id}` | a lista por empresa |
| Índice em `fin_movements` | `(company_id, date_lancamento)`. Hoje a coleção não tem índice nenhum e a vista mensal varre-a inteira. Junto aos índices de `fin_sales` (server.py:8972). |
| Levantar a tranca do sinal | anexar e ligar deixam de exigir `amount < 0`. Confirmar se a tranca é só do ecrã (`FinExtrato.js`) ou também do servidor. |

Permissões: `fin_require_member` para ler, `fin_require_editor` para escrever
(server.py:3278-3323). O contabilista fica só-leitura, como em todo o Financeiro.
`company_id="all"` passa por `_fin_report_scope` (8512).

## O que se reaproveita — nada disto se reescreve

Backend: `GET /fin/movements` (4652), `PUT /fin/movements/{id}/link|unlink`
(4761-4811, com integridade 1↔1 e aprendizagem de carimbo de graça),
`POST /fin/movements/{id}/attach` + `GET .../attachment` (4813-4844),
`GET /fin/reconcile/suggestions` (5031), `POST /fin/reconcile/dismiss` (5121),
`GET /fin/reconcile/pending` (5222), `POST /fin/reconcile/auto` (5301).

Frontend: todos os *wrappers* HTTP já existem em `lib/api.js:209-245`.
`PageHeader`, `MonthPicker`, `eur`, `fmtDate`, `kpiTone` de `lib/finance.js`.
O `zipFromMovements()` do Extrato (441-520) já exporta Excel + PDFs do mês —
acrescentar a coluna Categoria é uma linha no `data.map`.

## A aba que muda de casa

O Pagamentos tem hoje duas abas — "Conciliação" (1030-1108) e "Por conciliar"
(1110-1215). **Mudam-se para a secção nova**, e o Pagamentos volta a ser só
faturas. A secção fica com três separadores:

**Mapa do mês** · **Sugestões** · **Por ligar**

Assim a palavra "Conciliação" aponta para um sítio só.

## Fora de âmbito

- **Extratos por email.** Dá para fazer e o caminho está mapeado — o módulo
  `plataformas` já lê caixas como deve ser (filtra remetente, `BODY.PEEK`, não
  marca como lido, dedup por Message-ID) e o importador de PDF já valida a cadeia
  de saldos. Fase seguinte, depois de ela usar o ecrã.
- **Banco contra plataforma.** Comparar o que a Glovo diz que pagou com o que
  entrou na conta é conciliação a sério, mas `plat_relatorios` não tem
  `company_id` nem `unit_id` (a loja é texto livre lido por IA) — falta o mapa
  para `fin_units`. Fase própria.
- **Guias de transporte.** Têm backend pronto (`GET /fin/estoque/guias`, 6413) e
  nenhum ecrã no portal. Ficam de fora por decisão do dono.
- **Outros bancos.** Os dois importadores estão cablados ao Millennium BCP.

## Riscos conhecidos

1. **O anexo grava sempre como `.pdf`** (server.py:4813-4832): `shutil.copyfileobj`
   cru, nome fixo `{movement_id}.pdf`, sobrescreve em silêncio. Uma foto tirada na
   loja fica servida como PDF. É **um** anexo por movimento, não uma lista.
2. **`toggle-paid` não desliga o movimento** (3938-3948). Desmarcar "pago" à mão
   deixa o `fin_movements.invoice_id` colado. A tabela mensal vai encontrar
   movimentos ligados a faturas por pagar — tem de mostrar isso, não escondê-lo.
3. **As sugestões carregam 20.000 faturas e 50.000 movimentos por chamada**, sem
   índice. Com o índice novo melhora; se pesar, pagina-se depois.
4. **`fin_supplier_rules` é global, sem `company_id`** — uma regra criada numa
   empresa aplica-se às outras. Não piorar: nada do que se acrescentar aqui deve
   copiar esse padrão.
5. **O Extrato e a Conciliação mostram os mesmos movimentos** em ecrãs
   diferentes. É deliberado (porta ≠ mesa de trabalho), mas é preciso que
   ninguém tenha de adivinhar qual é qual — daí o subtítulo de cada página dizê-lo.
6. **A migração das categorias reescreve faturas gravadas.** Corre uma vez, com
   cópia de segurança antes, e mantém os valores antigos a resolver para os novos
   durante uma versão.

## Testes

`backend/tests/fin/`, no estilo da casa: nome em português a dizer a promessa
defendida, `BaseFalsa` própria no ficheiro, `MONGO_URL`/`DB_NAME` antes do
`import server`, `monkeypatch` a `server.db` e a `fin_require_editor`.

- `test_o_saldo_por_conta_desempata_pelo_id.py` — dois movimentos no mesmo dia na
  mesma conta devolvem o saldo do último inserido, não um qualquer.
- `test_a_linha_manual_nao_entra_no_saldo.py` — linha `manual` não mexe no saldo
  do banco nem finge ter `balance`.
- `test_so_se_apaga_uma_linha_manual.py` — `DELETE` num movimento do banco é 4xx.
- `test_a_categoria_do_movimento_e_da_empresa.py` — categoria fora da lista da
  empresa é recusada.
- `test_anexar_num_movimento_de_entrada.py` — a tranca do `amount < 0` caiu.
- `test_a_migracao_de_categorias_nao_perde_faturas.py` — nenhuma fatura fica com
  categoria órfã.

E, já que se lhe toca, o primeiro teste do motor que existe há meses sem rede:
- `test_a_conciliacao_nao_liga_pagamento_anterior_a_emissao.py`.

Correr: `cd backend && ./.venv/bin/python -m pytest -q` (2820 testes, ~67 s).
