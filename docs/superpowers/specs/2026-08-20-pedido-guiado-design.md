# Pedido guiado no POS — design

**Data:** 2026-08-20 · **Módulo:** Faturação L'Açaí (`backend/faturacao/`, `frontend/src/pages/pos/`)

## O problema

O cliente chega ao balcão e pede um açaí. Hoje, tocar no artigo mete-o na conta
imediatamente e as personalizações ficam escondidas atrás de um segundo toque na linha —
a operadora tem de saber que existem e ir buscá-las. O pedido de um açaí não é "um
artigo": é uma conversa curta (*levar ou comer aqui? que toppings? como se chama?*) que a
operadora conduz enquanto o cliente fala.

E há coisas que o sistema não sabe guardar de todo: **o nome que se escreve no copo**, e
se o pedido é **para levar**.

## A ideia central

O pedido guiado **não é um ecrã fixo que se programa**. É a sequência das
**personalizações do próprio produto**, cada uma com o seu título, mostradas uma a seguir
à outra. O dono cria os grupos que quiser no backoffice e atribui-os aos produtos que
quiser — e é isso, e só isso, que decide quais os artigos que abrem a conversa.

Um açaí leva três grupos:

| Grupo | Como é feito | O que aparece |
|---|---|---|
| **Consumir na loja** | lista, mínimo 1, máximo 1 | dois botões: Levar · Comer aqui |
| **Toppings** | lista, sem máximo, com doses | Nutella `2×`, Morango `1×`… |
| **Nome** | **texto livre** (tipo novo) | um campo para escrever |

Um café não leva nenhum e continua a ir direito para a conta com um toque.

**Quase tudo isto já existe.** O modelo de grupos tem `min_select`/`max_select` e opções
com preço próprio; "Consumir na loja" é um grupo normal com mínimo e máximo 1, e
"Toppings" é um grupo normal sem máximo. As peças novas são três: o **tipo texto**, os
**contadores de dose**, e o interruptor **sai na fatura**.

## As alterações ao modelo

### Grupo de personalização (`fat_grupos_personalizacao`)

- **`tipo`** — `"opcoes"` (o de sempre, por omissão) ou `"texto"` (campo livre).
  Um grupo `texto` não tem opções; `min_select >= 1` passa a querer dizer **resposta
  obrigatória**, reutilizando o campo que já existe com a mesma semântica ("tem de
  responder"). O Nome fica opcional (mínimo 0): há clientes que não dão nome, e um passo
  obrigatório que não se pode cumprir tranca a venda com o cliente à frente.
- **`sai_na_fatura`** — booleano, ligado por omissão. Decide se as escolhas deste grupo
  entram no título da linha da Fatura Simplificada. Liga-se nos Toppings, desliga-se no
  Nome e no Consumir na Loja.

### Doses: o máximo deixa de contar doses

Cada toque numa opção **soma uma dose**. Duas doses de Nutella custam duas vezes e o
talão diz `2x`. Carregar **2 segundos** sobre a opção apaga-a por inteiro.

O `max_select` passa a contar **opções diferentes**, não doses — o limite existe para
coisas como "escolha 1 tamanho", e duas doses do mesmo topping não são duas escolhas a
competir. Nos toppings do açaí não há máximo nenhum: o cliente pede o que quiser.

### Linha de venda (`fat_vendas.linhas[]`)

- `opcoes` — já é uma lista e **já aceita repetições**; o preço de cada entrada já soma
  (`precos.linha_de_venda`). O que muda é quem a preenche: o pop-up passa a mandar a
  mesma opção tantas vezes quantas as doses. Cada entrada leva também um retrato do
  `sai_na_fatura` do grupo no momento da escolha — pelo mesmo motivo que a linha já
  guarda `produto_preco`: o gestor pode mudar o grupo amanhã, e o que saiu no papel não
  muda.
- **`respostas_texto`** (novo) — `[{grupo_id, nome_grupo, texto}]`, para os grupos de
  tipo texto. Fica na linha, nunca no documento fiscal.

## O que sai na fatura

O título da linha passa a **agregar as repetições**: `Açaí Small (Nutella 2×, Morango)`
em vez de `(Nutella, Nutella, Morango)`. Mesma informação, legível.

Entram no título só as opções de grupos com `sai_na_fatura`. **Com uma excepção que não
se negoceia: uma opção PAGA aparece sempre**, esteja o interruptor como estiver — o
cliente está a ser cobrado por ela e a fatura tem de o dizer. O interruptor esconde o que
não custa nada; nunca esconde um euro.

As `respostas_texto` nunca vão à fatura. Uma FS com "Maria" escrita é estranha para quem
a leve à contabilidade, e não tem valor fiscal nenhum.

## O ecrã do POS

**Um pop-up flutuante**, ao centro, por cima do ecrã — não o painel direito. A grelha e a
conta ficam à vista por trás, e a operadora vê o que já picou enquanto monta o pedido.

Tocar num produto **com grupos** abre o pop-up com um passo por grupo, pela ordem em que
estão atribuídos. Tocar num produto **sem grupos** mete-o na conta com um toque, como
hoje — nada muda para o café ou para a água.

No fim, **Gravar** põe a linha na conta. Na linha, por baixo do nome do produto e em
pequeno: `Levar · Maria` e `Nutella 2× · Leite condensado 1×`, que é o que a operadora
confere com o cliente antes de finalizar.

### Corrigir uma linha já gravada

Tocar na linha abre o **diálogo do produto de sempre** (quantidade, preço, IVA,
desconto). Ganha no topo um bloco com os títulos — **Serviço**, **Nome**,
**Personalizações** — e um botão **Editar pedido** que reabre o pop-up guiado nos mesmos
passos, já preenchidos.

Porque não voltar directamente ao pop-up: corrigir "esqueci-me da Nutella" acontece
muitas vezes ao dia, mas dar um desconto naquela linha também — e se o caminho de
correcção escondesse o desconto, a operadora ficava sem saída sem apagar a linha e picar
tudo de novo.

## O talão da cozinha

Fica **guardado na linha**, no formato que o dono escreveu:

```
Pedido

1 Açaí Small — MARIA
Levar

1x Leite condensado
2x Nutella
```

A primeira resposta de texto vai na linha do produto (é o nome no copo); os grupos de
escolha única sem preço vão na linha seguinte; os toppings vêm em lista com as doses.

**O agente de impressão não existe** — é o Plano 3, e o botão *Imprimir Pedido* continua
desligado com a explicação que já lá está. Constrói-se a informação agora; no dia em que
o agente existir, sai em papel sem se mexer em mais nada.

## O backoffice

**Personalizações** ganha, em cada grupo: o **tipo** (lista de opções · texto livre) e o
interruptor **sai na fatura**, cada um com uma frase a dizer o que faz. Um grupo de texto
não mostra a lista de opções.

**Produtos** não muda nada: atribuem-se os grupos como já se atribuem hoje. É essa
atribuição, e só ela, que decide quais os artigos que abrem o pedido guiado.

## Fora de âmbito

- O agente de impressão (Plano 3).
- Alterar o IVA conforme levar/consumir. Foi decidido com o dono que é **só uma indicação
  para a cozinha** — não mexe em taxas nem em preços, e por isso não precisa do
  contabilista.

## Pré-requisito

**Corrigir a duplicação de produtos no Vendus antes de construir isto.** A emissão manda
cada linha só com o nome, e o Vendus cria um produto novo por linha (14 "Açaí Mini" na
conta, 13 deles lixo com referências `VACA…`). Os 42 produtos já têm `vendus_ref`
guardado — falta enviá-lo. Com o pedido guiado a produzir títulos mais variados
(`Açaí Small (Nutella 2×)`), o problema só piora.
