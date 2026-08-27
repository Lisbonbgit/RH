# Movimentos de Caixa no backoffice

**Data:** 2026-08-27 · **Estado:** aprovado pelo dono

## O problema

O ecrã «Movimentos de Caixa» (Faturação · POS) está em ComingSoon. O dono quer
ver, do backoffice, como correu a gaveta de cada loja: aberturas, entradas,
saídas e fechos. Mostrou os três ecrãs do Vendus como referência.

## O que o Vendus faz, e o que fazemos diferente

| Vendus | Nós | Porquê |
|---|---|---|
| Três níveis: lojas → caixas → dias → detalhe | **Dois**: filtro (loja + período) → dias → detalhe | Cada loja tem UMA caixa. O índice de lojas seria um clique a mais para escolher a única opção. |
| «Fecho de Caixa» = abertura + entradas em numerário | **Esperado E contado, com a diferença** | O número do Vendus é calculado; ele não sabe quanto a funcionária contou. Nós sabemos, e é a informação mais valiosa do ecrã. |
| Botões «Alterar» na abertura e no fecho | **Não há** | Um Z assinado é o retrato de um instante. Reescrevê-lo depois destrói a única prova de que a gaveta bateu certo nesse dia. Corrige-se com um movimento, que fica com o nome de quem o fez. |
| Autoconsumo · Faturação a Prazo · Vendus Pay | Não existem | Não são conceitos deste sistema. Um ecrã com secções vazias ensina a ignorá-las. |

## Os dois ecrãs

**Lista.** Filtro de loja e de período em cima. Um cartão por turno: dia da
semana e data, a faturação desse turno em destaque, e ao lado a Abertura
(hora · fundo · quem) e o Fecho (hora · esperado · contado · quem). A
diferença aparece como pastilha quando há falta ou sobra. Um turno por fechar
aparece marcado, sem contado inventado.

**Detalhe.** Abertura e Fecho em cima; por baixo, secções:
Resumo dos movimentos · Lista dos movimentos (com motivo e autor) · Tipos de
pagamento · Produtos vendidos · Mapa de impostos · Tipos de documentos.

## Arquitectura

`faturacao/historico_caixa.py` — as rotas de leitura, de gestor:

- `GET /caixa/historico?loja_id=&de=&ate=` → os turnos do período
- `GET /caixa/historico/{sessao_id}` → o detalhe de um turno

**Nenhuma soma nova.** Tudo sai de `caixa._resumo_do_turno` — a mesma função
do Ponto de Caixa, do Z e do relatório diário — e os produtos vendidos de
`relatorio_diario._artigos_vendidos`. Uma quarta contabilidade sobre a mesma
gaveta era a maneira certa de um dia discordarem.

## Testes

- os números do turno batem com os do Z do mesmo turno;
- um turno aberto não inventa contado nem diferença;
- o filtro de loja não deixa passar turnos de outra;
- as rotas exigem gestor;
- os ecrãs desenhados e vistos, não só afirmados.
