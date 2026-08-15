# Faturação L'Açaí — Plano 2B: a venda e a emissão fiscal

> **Para trabalhadores agênticos:** SUB-SKILL OBRIGATÓRIA: `superpowers:subagent-driven-development`.

**Spec:** `docs/superpowers/specs/2026-08-13-faturacao-lacai-design.md` (§5, §6, §12)
**Depende de:** Plano 2A (entrada no POS e sessão de caixa) — já feito.

**Goal:** a operadora monta uma conta no balcão, escolhe o pagamento, e sai uma **Fatura Simplificada
real** emitida pelo Vendus, com o talão já pronto a imprimir. A venda entra na sessão de caixa e
conta para o esperado do fecho.

**Onde os erros custam dinheiro:** uma fatura emitida duas vezes é uma cobrança a dobrar à AT, que
só se corrige com uma nota de crédito. Metade deste plano é sobre isso.

---

## Global Constraints

- **Python 3.9.6.** Sem `X | Y`, sem `match`, sem `list[str]` — `Optional[X]`, `Dict`, `List[X]`.
- **Nada acrescentado ao `backend/server.py`.**
- Prefixo `fat_` nas colecções; rotas em `/api/faturacao/pos/`.
- **Nenhum teste liga a base de dados nem à rede.** Emissão testada com `httpx.MockTransport`.
- `backend/.venv/bin/pytest`. Não correr `pip install`, não mexer nos pins.
- **PT-PT** em texto visível e comentários.
- **Uma só caixa API no Vendus**, cujo `register_id` vem de variável de ambiente. **Não existe
  selector em lado nenhum** e qualquer emissão com outro `register_id` é recusada antes de sair.
- **Nunca chamar `registers/{id}/movements`** — nem para abrir, nem para fechar. A caixa do Vendus
  é partilhada com a app L'Açaí, que está em produção; fechá-la deixava a app a cobrar no Stripe
  sem emitir fatura.
- **O POS nunca lê contas em aberto do Vendus.** Um pedido da app já pago pelo cliente apareceria
  como conta por cobrar, e sairia uma segunda fatura de uma venda já paga.

---

## Task 1: Emitir documentos no Vendus

**Files:** Create `backend/faturacao/vendus/emissao.py` e `backend/tests/faturacao/test_emissao.py`

O cliente que já existe (`vendus/cliente.py`) é **só de leitura**, e assim fica — foi revisto com
esse critério. A emissão vive num módulo próprio, para ser óbvio quem pode escrever.

`criar_fatura_simplificada(linhas, pagamentos, cliente, external_reference, register_id)` faz
`POST documents/` com `type="FS"`, `output="escpos"` (o Vendus devolve **o talão já em ESC/POS**, por
isso não desenhamos o layout da fatura — vem certificado de lá) e devolve id, número, ATCUD, total
e os bytes do talão.

**Gotchas conhecidos, documentados no código de produção do mesmo dono** (`~/dev/pizzaria/backend/vendus/`):
o campo `mode` rebenta certos pedidos com 403; o `view` dá 403 no GET de um documento; o 404 com
código `A001` significa "sem resultados" e não avaria. Lê esse ficheiro antes de escrever.

- [ ] Testes com `MockTransport`: emissão feliz; 429 lê `Rate-Limit-Reset` e repete; 5xx repete e
      desiste com erro tipado; `register_id` fora do configurado → recusa **antes** de sair para a rede.
- [ ] Commit: `Faturação: emissão de documentos no Vendus`

---

## Task 2: A conta do balcão

**Files:** Create `backend/faturacao/venda.py` e os testes · Modify `db.py`

`fat_vendas`: `loja_id`, `caixa_id`, `sessao_id`, `operador_id`, `linhas`, `estado`
(`aberta`|`emitida`|`cancelada`), `criada_em`.

Cada linha guarda o produto, a quantidade, as personalizações escolhidas, e os *overrides* que a
operadora tenha feito (preço, IVA, desconto). Os totais **derivam sempre** do `linha_de_venda` do
`precos.py` — a mesma função que constrói as linhas que vão para a fatura. **Uma só fonte de
verdade**, senão o que está no ecrã e o que sai no papel divergem ao cêntimo.

**Regras:** a sessão e o operador vêm do token, nunca do corpo; não se acrescenta a uma venda já
emitida; um produto sem IVA definido **não entra** na conta (erro claro, não um valor assumido).

- [ ] Testes: juntar, alterar quantidade, remover, aplicar desconto por linha e global; totais
      conferidos ao cêntimo contra o `linha_de_venda`; venda emitida recusa alterações.
- [ ] Commit: `Faturação: a conta do balcão`

---

## Task 3: Finalizar — a emissão, com as três defesas

**Files:** Create `backend/faturacao/fiscal.py` e os testes · Modify `db.py`

É o coração. A sequência:

1. **Referência determinística:** `pos-{loja}-{sessao}-{venda_id}`. Depende só da identidade da
   venda — **nunca de um relógio**. Duas tentativas da mesma venda produzem a mesma referência.
2. **Reserva atómica, antes de tocar no Vendus:** inserir em `fat_refs_fiscais` com índice **único**
   em `ext_ref`. Quem perde a corrida apanha `DuplicateKeyError` e **nunca emite** — devolve o
   documento do vencedor ou espera por ele. Se algo falhar a seguir, a reserva é removida.
3. **Emitir** e gravar em `fat_documentos` (único em `vendus_document_id` **e** em `atcud`).
4. **Se a emissão falhar por timeout:** `GET documents/?external_reference={ref}` — **uma** chamada,
   exacta. Se o documento existe, foi emitido: usa-se esse. Se não, repete-se.

**O que NÃO se copia do código da Pizzaria**, porque uma revisão o apanhou lá: o dedup que varre os
documentos do dia com `per_page=200` **sem paginar** — numa loja com 240 talões, a fatura original
nem entra na lista lida e sai uma segunda fatura real. E a decisão de "emitir à mesma se a consulta
de verificação rebentar".

**A investigar antes de dar por concluída:** o Vendus documenta um campo `tx_id` que dá idempotência
**nativa** no POST, e nenhum dos nossos projectos a usa. Se funcionar, é uma quarta defesa de graça.
Testa-a em modo de testes e regista o resultado — se não der para confirmar sem chave, di-lo.

- [ ] Testes: duplo-toque emite **uma** fatura; timeout seguido de repetição não duplica; falha
      depois da reserva liberta-a; `atcud` repetido é recusado pelo índice.
- [ ] Mutação: tirar a reserva atómica — o teste do duplo-toque fica vermelho.
- [ ] Commit: `Faturação: emissão da Fatura Simplificada com idempotência`

---

## Task 4: A venda entra na caixa

**Files:** Modify `caixa.py`, `caixa_math.py`, `fiscal.py` e os testes

Uma venda paga em dinheiro tem de contar para o **esperado** do fecho; uma venda em multibanco não.
É o que faz a gaveta bater certo.

E o fecho ganha a **verificação de leitura** contra o Vendus que ficou prometida no Plano 2A:
`GET documents/` da janela da sessão, filtrado pelo nosso prefixo `pos-`, **paginado até esgotar**,
descartando anulados. Bate certo → não diz nada. Não bate → **avisa, mas deixa fechar**. Não
conseguiu ler tudo → **diz que não conseguiu verificar**, e nunca inventa um número que a operadora
vá usar para justificar dinheiro.

- [ ] Testes: esperado com vendas em dinheiro e cartão misturadas; pagamento misto conta só a parte
      em dinheiro; leitura truncada não afirma nada.
- [ ] Commit: `Faturação: as vendas contam para o fecho de caixa`

---

## Verificação final do Plano 2B

- [ ] Suite verde
- [ ] Nenhuma chamada a `registers/{id}/movements` em todo o módulo
- [ ] O `register_id` não aparece em nenhum modelo de entrada nem em nenhuma rota
- [ ] O duplo-toque, testado, produz uma só fatura
