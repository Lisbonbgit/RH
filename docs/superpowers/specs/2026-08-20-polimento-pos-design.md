# Polimento do POS — cinco coisas que o dono apanhou a usar

**Data:** 2026-08-20 · **Origem:** o dono a percorrer o POS depois do pedido guiado ir ao ar.

Não são defeitos de correcção — o sistema faz o que deve. São cinco sítios onde **falta
informação a quem está ao balcão**, ou onde o ecrã pede o que não precisa de pedir.

## 1. O teclado do PIN está esticado

`frontend/src/pages/pos/PosEntrar.js`. As teclas do PIN ficam deformadas. **Ver no browser
antes de mexer** — o problema é visual e não se diagnostica a ler o código.

## 2. O Ponto de Caixa está quase vazio

`frontend/src/pages/pos/PosMenuCaixa.js` (o diálogo já existe, o conteúdo não). É a
conferência a meio do turno, **sem fechar nada**. Passa a mostrar:

- **O montante que devia estar na gaveta.** A matemática já existe: `caixa_math.esperado`
  (fundo + vendas em dinheiro + movimentos). É o mesmo número do fecho, sem o fecho.
- **Resumo dos movimentos:** abertura, entradas, saídas. Também já existe
  (`caixa_math.total_por_tipo`).
- **Por tipo de pagamento:** quanto entrou em dinheiro, multibanco, Uber, Glovo. Sai dos
  `pagamentos` das vendas emitidas da sessão, que já guardam o `nome` e o `tipo_fiscal` em
  retrato.
- **Mapa de imposto:** taxa · nº de documentos · base · IVA · total.

**O mapa de imposto é a parte com trabalho.** `fat_documentos` guarda o `total_bruto` e o
`total_liquido` do documento inteiro, **não a repartição por taxa** — e o catálogo tem duas
(13% nos açaís, 23% nos refrigerantes, brigadeiros, embalagem e entrega), que se misturam na
mesma conta. A repartição tem de ser calculada a partir das **linhas das vendas** da sessão,
onde cada linha tem o seu `tax_id`. Cuidado com o desconto global: ele incide sobre o
líquido depois dos descontos por linha, e tem de ser repartido pelas taxas na mesma
proporção, senão a base declarada por taxa não bate com o total do documento.

## 3. O NIF não tem teclado numérico

`PosFinalizar.js`, cartão **Cliente**. O `PosCampoValor` já existe e já dá teclado a um valor
em euros; o NIF precisa do mesmo gesto, com nove dígitos e sem vírgula.

## 4. O desconto tem teclado no €, não tem no %

`PosFinalizar.js`, cartão **Total**. Os dois campos são a mesma decisão da operadora e um
deles obriga-a a ir ao teclado do PC. Passa a ter nos dois.

## 5. O ecrã pede o valor de um pagamento que não tem dúvida

Hoje, escolher um tipo de pagamento faz aparecer logo um campo de valor. Mas **se só há um
tipo, o valor é o total** — não há nada a decidir, e é um campo a mais em todas as vendas
normais do dia.

**A regra:**

- **Um só tipo escolhido** → sem campo de valor. Uber, Glovo ou Multibanco sozinhos querem
  dizer que o valor já estava certo.
- **Dois ou mais** → aí sim, um campo por tipo, porque é a operadora que decide a
  repartição.
- **O "valor recebido" continua sempre disponível quando o tipo dá troco** (dinheiro), com
  ou sem repartição — é dele que sai o troco, e é o campo que mais dá jeito ao balcão.

## Sequenciamento

O `PosFinalizar.js` está a ser alterado pelo plano do dividir/separar (Task 5). **Isto entra
depois**, para as duas frentes não colidirem no mesmo ficheiro.
