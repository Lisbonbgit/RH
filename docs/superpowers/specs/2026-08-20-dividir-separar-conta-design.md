# Dividir e separar a conta — design

**Data:** 2026-08-20 · **Módulo:** Faturação L'Açaí · **Ecrã:** finalizar (`PosFinalizar.js`)

## O problema

Três amigos chegam ao balcão e levam dois açaís e uma Coca-Cola. No fim, ou dividem a conta
por igual, ou cada um paga o que consumiu — e **cada um quer a sua fatura**. Hoje o POS só
sabe emitir um documento por conta.

## As duas operações

| | o que faz | como se reparte |
|---|---|---|
| **Dividir** | a conta a dividir por N pessoas | cada linha vai a `1/N` da quantidade |
| **Separar** | cada pessoa paga o que consumiu | o staff atribui os artigos, em unidades inteiras |

São **exclusivas**: uma conta ou se divide ou se separa, nunca as duas. Misturá-las produz
frações de frações e uma conversa que ninguém sabe ter ao balcão.

## A decisão que mantém o núcleo fiscal intacto

**Cada parte é uma venda normal.** Dividir ou separar cria N contas-filhas a partir da
conta-mãe, e daí em diante cada uma é exactamente como qualquer outra venda: a sua
referência determinística, a sua reserva atómica, a sua idempotência, o seu documento.

Isto não é um detalhe de arrumação — é o que **evita mexer no núcleo fiscal**, que é onde
esta semana se encontraram os defeitos mais caros (uma reserva apagada por baixo de uma
emissão em voo, um cancelamento a passar por cima de uma fatura que já tinha saído). Tudo o
que lá está endurecido aplica-se às partes sem uma linha nova.

A conta-mãe passa a `separada` e deixa de ser finalizável: quem emite são as filhas.

## O cêntimo — a parte difícil

Medido contra a conta Vendus real, com um Açaí Regular de 8,99 € dividido por três:

| quantidade enviada | o Vendus factura | três somam |
|---|---|---|
| `0.333` | 2,99 € | 8,97 € |
| `0.3333` | 3,00 € | **9,00 €** |
| `0.33333` | 3,00 € | **9,00 €** |

Nenhuma dá 8,99. Mandar a mesma fracção a toda a gente **declara à AT um valor diferente do
que entrou na gaveta**, e num dia com muitas divisões acumula.

**A regra, decidida com o dono:** as partes somam **sempre e exactamente** o total da conta.

O algoritmo, em cêntimos e nunca em vírgula flutuante:

1. O total da linha em cêntimos: `c = round(qty × preço × 100)`.
2. Cada parte leva `c // N`; as primeiras `c % N` partes levam **mais um cêntimo**.
   Para 8,99 € por três: `300, 300, 299`. A diferença entre duas pessoas nunca passa de um
   cêntimo.
3. A quantidade a enviar por parte: `q = valor_da_parte / preço`, a 5 casas decimais (o
   Vendus aceita-as — medido).
4. **Verificar antes de emitir:** recalcular `round(q × preço, 2)` e confirmar que dá o
   valor da parte. Se não der, ajustar o `q` até dar. O Vendus arredonda de forma
   previsível, mas a defesa não é acreditar nisso — é confirmar.

O mesmo se aplica ao desconto global da conta-mãe, repartido pelas partes pela mesma regra.

## O ecrã

No finalizar, ao lado do que já existe, dois botões: **Dividir Conta** e **Separar Conta**.
Escolhido um, o outro desliga-se.

**Dividir:** um contador de pessoas (`−` `2` `+`). Escolhido o número, aparece um cartão:

> **Divisão de Conta** · 1/3 Pessoas · Falta Receber: 5,99 €
> **2,99 € / Pessoa** · Total: 8,99 €

Emite-se a fatura da pessoa 1, o *Falta Receber* desce, passa-se à seguinte.

**Separar:** o staff toca nos artigos que são desta pessoa. A conta mostra o que está
atribuído e o que falta. Emite-se, e os artigos que sobram ficam para a pessoa seguinte.

Em ambos, a conta da direita mostra por linha a **fatia desta pessoa** — a coluna que o POS
do Vendus tem à esquerda de cada artigo (`1`, `0.5`).

## Quando alguém não paga

Foi a pergunta que o dono respondeu, e é o que fecha o desenho: *"o cliente tem que pagar e
tem que emitir uma fatura; mas também tem a opção de só cancelar e deixar de cobrar"*.

Uma parte que não é paga **cancela-se** — e isso é o `cancelar_venda` que já existe, com
tudo o que ganhou esta semana: recusa cancelar se houver uma emissão em curso ou por
confirmar, escreve condicionalmente e decide pelo `matched_count`, e regista **quem**
cancelou. Não é código novo: é a saída de emergência a funcionar de graça, porque a parte é
uma venda como as outras.

O que isso significa nas contas: os artigos dessa parte saíram sem fatura e sem dinheiro. É
uma perda da loja, não um problema fiscal — não houve venda. O `cancelada_por` fica
registado, que é o que a gestão precisa para perceber com que frequência acontece e com
quem.

## O que muda no modelo

- **`quantidade` passa a aceitar fracções.** Hoje é `int = Field(ge=1)` em
  `PedidoJuntarLinha`. Passa a decimal, com **5 casas** — mais do que as 2 dos preços, e por
  uma razão diferente: uma quantidade não é dinheiro, é o que **produz** o dinheiro, e é
  preciso resolução para o valor final cair no cêntimo certo. O crivo das 2 casas continua
  a valer, intocado, para tudo o que é preço.
- **A venda ganha `conta_mae_id`** (nas filhas) e **`estado: "separada"`** (na mãe).
- Nada muda em `precos.linha_de_venda`, `fiscal.py` ou `caixa_math`.

## Fora de âmbito

- Misturar dividir e separar na mesma conta.
- Separar em fracções (o separar atribui unidades inteiras; quem quiser meio açaí divide).
- Transferir uma parte para outra caixa ou outra mesa.

## Pré-requisito

Nenhum. O pedido guiado já está no ar e não colide: mexe no toque do produto, isto mexe no
finalizar.
