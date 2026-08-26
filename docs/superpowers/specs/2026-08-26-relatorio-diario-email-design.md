# Relatório diário de faturação por email

**Data:** 2026-08-26 · **Estado:** aprovado pelo dono

## O problema

O dono não tem como saber, ao fim do dia, quanto fez cada loja sem abrir o
portal. Quer isso no email, todos os dias, sem ter de ir buscar.

## O que o relatório diz

1. Faturação geral do dia, com a variação contra ontem
2. Faturação por loja
3. Quanto está no caixa de cada loja
4. Quanto está no caixa geral (todas as lojas somadas)
5. Artigo mais vendido — com a repartição por personalização (o "Açaí" partido
   por Mini / Small / Regular / Supreme)
6. Tipos de pagamento por loja
7. Tipos de pagamento no total

## Decisões tomadas com o dono

| Pergunta | Decisão | Porquê |
|---|---|---|
| Fonte da faturação | `fat_documentos` — o POS próprio | É onde vive o detalhe (caixa, pagamentos, linhas de artigo). O Vendus (`fin_sales`) não sabe da gaveta nem das personalizações. |
| O que é "o caixa" | Esperado **e** contado, lado a lado, com a diferença | Deixa apanhar uma falta ou sobra na manhã seguinte sem abrir o sistema. |
| Artigos | Top por produto **e** a repartição por tamanho | Responde às duas perguntas: que produto puxa a loja, e que tamanho sai mais. |
| Gráficos | Colunas em HTML/CSS puro | O Gmail apaga `<svg>` e o Outlook não faz gradientes. Colunas de `<td>` aparecem iguais em todo o lado, sem imagens para carregar e sem dependências novas. |
| Hora | 23:30, com a hora escrita no email | Pedido do dono; a essa hora as lojas estão fechadas. **Buraco conhecido e aceite:** uma venda depois das 23:30 não entra em relatório nenhum. Fica escrito no próprio email ("até às 23:30") para nunca haver dúvida. |
| Destinatários | Ecrã na Configuração da Faturação | O dono muda a lista sem tocar no servidor. |
| Sem vendas | Envia na mesma, a dizer "sem vendas registadas" | Um email que não chega é ambíguo: avariou, ou não houve movimento? |
| Âmbito | Toda a gente na lista recebe tudo | YAGNI: âmbito por loja acrescenta-se no dia em que um gerente precisar só da dele. |
| Turno por fechar | Marcado "turno ainda aberto": mostra o esperado, não inventa o contado | Nunca apresentar um número que ninguém contou. |

## Arquitectura

Três peças, cada uma testável sozinha:

| Peça | Responsabilidade | O que NÃO faz |
|---|---|---|
| `faturacao/relatorio_diario.py` | `montar_relatorio(...)` → dicionário com os números | Não lê Mongo, não envia email |
| `faturacao/relatorio_email.py` | `html_do_relatorio(dados)` → HTML | Não sabe de dinheiro nem de Mongo |
| rota `POST /faturacao/cron/relatorio-diario` | Lê o Mongo, chama as duas, envia pelo Resend | Não faz contas |

A separação não é decorativa: as contas de dinheiro têm de se poder testar sem
email nenhum, e o desenho tem de se poder ver sem inventar vendas.

### Nenhuma soma nova

O relatório **não reimplementa** aritmética nenhuma:

- **Faturação:** `dashboard._valor_documento` / `_campo_valor` — a mesma que o
  Dashboard usa (nota de crédito com sinal negativo, anulado não conta, e a
  alternativa para os documentos antigos sem `total_bruto`).
- **Caixa e pagamentos:** `caixa._resumo_do_turno` — a MESMA função que serve o
  Ponto de Caixa e o Z. Uma terceira contabilidade sobre a mesma gaveta é
  exactamente o que este módulo recusa desde o início.
- **Artigos:** as linhas das vendas emitidas. Cada opção já traz `grupo_nome`
  (ver `venda._carimbar_sai_na_fatura`), e é por aí que o "Açaí" se parte por
  tamanho — sem adivinhar qual dos grupos é o do tamanho.

### Dados

Colecção nova `fat_definicoes`, um documento por chave:

```
{"id": "relatorio_diario", "emails": ["..."], "ativo": true}
```

Uma colecção genérica em vez de uma só para isto: a próxima definição do
backoffice não precisa de uma colecção nova.

### A janela do dia

Do início do dia local até ao instante do corte (23:30). A hora vai no email.

## O email

Cabeçalho (dia + "até às 23:30") · faturação geral em número grande com a
variação · colunas dos últimos 14 dias com hoje aceso · caixa geral (esperado
vs contado, diferença destacada) · um cartão por loja com faturação, caixa e
pagamentos · pagamentos no total · top de artigos com a repartição por tamanho
· rodapé.

Tabelas HTML e estilos em linha — é o que sobrevive ao Gmail e ao Outlook.
Cores tiradas dos tokens do sistema (`--primary` #1366F0 e companhia),
convertidas para hexadecimais fixos: um email não tem CSS variables.

## Configuração

Sexto ecrã na Configuração da Faturação, ao lado de Dispositivos:
lista de emails (juntar/tirar), interruptor de ligado/desligado, e um botão
**"Enviar agora para mim"** para o dono testar sem esperar pelas 23:30.

## Como corre

Script `relatorio-diario-cron.sh` às 23:30, no mesmo padrão dos que já existem:
chama a rota dentro do contentor, protegida por `CRON_KEY` (nunca JWT).

## Testes

- `montar_relatorio`: aritmética pura — faturação, caixa, pagamentos, artigos,
  turno aberto, dia sem vendas. É dinheiro: cada número tem o seu teste.
- `html_do_relatorio`: os números aparecem no HTML, e o HTML é válido.
- A rota: recusa sem `CRON_KEY`, respeita o interruptor, não envia sem
  destinatários, e a janela do dia é a que se diz.
- O email é **desenhado e visto** antes de se dar por bom — não só afirmado.
