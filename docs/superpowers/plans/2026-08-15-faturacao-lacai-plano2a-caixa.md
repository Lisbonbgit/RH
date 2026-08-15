# Faturação L'Açaí — Plano 2A: entrada no POS e sessão de caixa

> **Para trabalhadores agênticos:** SUB-SKILL OBRIGATÓRIA: usar
> `superpowers:subagent-driven-development`. Os passos usam caixas (`- [ ]`).

**Spec:** `docs/superpowers/specs/2026-08-13-faturacao-lacai-design.md` (§7 e §12)

**Goal:** uma funcionária entra no POS com o PIN, abre a caixa com o fundo de maneio, regista
entradas e saídas de dinheiro ao longo do dia, e fecha com a contagem e o relatório Z. Ainda **não
vende** — isso é o Plano 2B.

**Architecture:** continua no pacote `backend/faturacao/`. Autenticação do POS **separada** da do
backoffice: o browser da loja guarda um token de dispositivo e um token de sessão de operador, e
**nunca** usa o JWT de gestão. A lógica de dinheiro vive em módulos puros, testáveis sem Mongo.

**Tech Stack:** FastAPI · Motor/MongoDB Atlas · Pydantic 2 · PyJWT · bcrypt · pytest 8

---

## Global Constraints

- **Python 3.9.6.** Sem `X | Y`, sem `match`, sem `list[str]` — `Optional[X]`, `Dict`, `List[X]`.
- **Nada acrescentado ao `backend/server.py`.**
- Prefixo `fat_` nas colecções; rotas do POS em `/api/faturacao/pos/`.
- **Nenhum teste liga a base de dados nem à rede.** Não há MongoDB nem Docker nesta máquina.
- O `.venv` já existe: `backend/.venv/bin/pytest`. **Não** correr `pip install`, **não** mexer nos pins.
- **PT-PT** em texto visível e comentários.
- Cada tarefa acaba com um commit no ramo de trabalho.

---

## Task 1: Fechar o IVA forçado à mão

**Porquê primeiro:** no POS, o diálogo do produto deixa a operadora mudar o IVA de uma linha. Esse
valor chega ao `linha_de_venda` como `tax_override` e **hoje passa sem validação nenhuma** —
confirmado no interpretador: `linha_de_venda(p, 1, tax_override="XPTO")` devolve uma linha com
`tax_id: "XPTO"`. O `erros_do_produto` já valida o código; o caminho do override não. Ou o Vendus
recusa o documento à frente do cliente, ou aceita-o e sai uma fatura com o imposto errado.

**Files:** Modify `backend/faturacao/precos.py` e `backend/tests/faturacao/test_precos.py`

- [ ] Teste: `linha_de_venda(produto, 1, tax_override="XPTO")` levanta `ValueError` com mensagem em
      português; `tax_override="NOR"` continua a passar; `tax_override=None` usa o IVA do produto.
- [ ] Vê-o falhar. Implementa validando contra os códigos conhecidos (o módulo já os tem). Vê passar.
- [ ] Mutação: remove a validação, confirma o vermelho, repõe.
- [ ] Commit: `Faturação: o IVA forçado à mão passa pelo mesmo crivo do IVA do produto`

---

## Task 2: Autenticação do POS

**O modelo, e a razão de cada peça:**
- **Token de dispositivo** — o PC da loja é autorizado uma vez, no backoffice, colando um código de
  emparelhamento. Fica em `localStorage`. Sem ele, o `/pos` nem carrega. É o que impede alguém de
  abrir o POS de casa.
- **Token de operador** — sai da entrada por PIN, dura o turno, e é o que identifica **quem fez cada
  venda**. Vai num cabeçalho próprio, nunca no `Authorization`.
- Os endpoints do POS aceitam **estes** tokens; **nunca** o JWT de gestão. Um administrador que
  esteja com sessão aberta no backoffice não pode, por isso, vender sem se identificar — senão a
  venda entra na caixa sem dono e o fecho deixa de responsabilizar ninguém.

**Files:** Create `backend/faturacao/pos_auth.py`, `backend/tests/faturacao/test_pos_auth.py` ·
Modify `db.py`, `__init__.py`

**A guarda que a spec §7.1 torna obrigatória:** a unicidade do PIN **não pode ser garantida por um
índice** (o sal do `bcrypt` faz cada hash diferente) e a verificação no servidor não cobre o caso de
alguém ser movido de loja. Portanto, a entrada no POS tem de tratar **mais do que uma
correspondência** como erro explícito — *"PIN em conflito, contacte o gestor"* — e **nunca escolher
a primeira**. Escolher a primeira atribuiria as vendas à pessoa errada.

**A armadilha de desempenho (achado de uma revisão anterior):** o `bcrypt` custa ~166 ms por
verificação e é síncrono. A entrada no POS compara o PIN contra todos os operadores activos da
loja — com 20 pessoas são ~3,3 s a **bloquear o event loop do portal inteiro**, picagem de ponto
incluída. Corre-o fora do loop (`asyncio.to_thread`).

- [ ] Testes: emparelhar dispositivo; token de dispositivo inválido → 401; PIN certo devolve token
      de operador; PIN errado → 401 **sem dizer se o PIN existe**; **duas correspondências → 409 com
      a mensagem de conflito**; operador inactivo não entra; operador de outra loja não entra.
- [ ] Teste de que a verificação não corre no event loop (o duplo do `to_thread` é chamado).
- [ ] Mutação: fazer o login escolher a primeira correspondência — o teste do conflito fica vermelho.
- [ ] Commit: `Faturação: entrada no POS por dispositivo e PIN`

---

## Task 3: Abrir a caixa e registar movimentos

**Files:** Create `backend/faturacao/caixa.py`, `caixa_math.py` (**puro**) e os testes ·
Modify `db.py` (colecções e índices)

**Colecções:** `fat_sessoes_caixa` (`caixa_id`, `loja_id`, `aberta_por`, `aberta_em`, `fundo`,
`estado`, `fechada_por`, `fechada_em`, `contado`, `esperado`, `diferenca`) e `fat_movimentos_caixa`
(`sessao_id`, `tipo` `entrada`|`saida`, `valor`, `motivo`, `por`, `em`).

**Índice que é a própria garantia:** único **parcial** em `{caixa_id, estado: "aberta"}` — é
impossível haver duas sessões abertas na mesma caixa, mesmo com dois PCs a tentar ao mesmo tempo.
Sem ele, duas sessões paralelas partem o fecho e o Z.

**`caixa_math.py` (puro):** `esperado(fundo, vendas_dinheiro, movimentos)` — soma o fundo e as
vendas em dinheiro, soma as entradas, subtrai as saídas. Nada de I/O.

**Regras:** a sessão é **resolvida no servidor** a partir do token do operador — nunca vem no corpo
do pedido; um valor de movimento é sempre positivo (o sinal vem do tipo); um motivo é obrigatório
nas saídas.

- [ ] Testes do `caixa_math` com fundo, vendas, entradas e saídas, e com listas vazias.
- [ ] Testes dos endpoints com duplos: abrir com caixa já aberta → 409; movimento sem sessão aberta
      → 409; valor negativo → 422; `sessao_id` vindo do corpo é **ignorado**.
- [ ] Mutação: aceitar o `sessao_id` do corpo — o teste fica vermelho.
- [ ] Commit: `Faturação: sessão de caixa e movimentos`

---

## Task 4: Fechar a caixa e o relatório Z

**Files:** Modify `caixa.py`, `caixa_math.py` e os testes

O fecho conta o dinheiro, mostra **esperado vs contado**, a diferença, e produz o Z.

**Três regras que vêm de erros já cometidos noutro projecto do mesmo dono:**
1. O esperado calcula-se **das nossas vendas**, não do Vendus.
2. A verificação contra o Vendus é **só de leitura** e **nunca bloqueia o fecho** — a funcionária tem
   de poder ir para casa. Se não bater, avisa e regista; o aviso aparece no backoffice no dia
   seguinte.
3. Se a leitura do Vendus **não conseguir ler tudo** (paginação truncada), **não afirma que bate nem
   que não bate** — diz que não conseguiu verificar. Nunca inventar um número que a operadora vai
   usar para justificar dinheiro.

*(A ligação ao Vendus entra no Plano 2B, com o cliente de leitura. Aqui o fecho já é completo do
nosso lado e deixa o sítio feito.)*

- [ ] Testes: fecho com diferença positiva, negativa e a zero; fechar uma sessão já fechada → 409;
      o Z inclui aberturas, vendas em dinheiro, entradas, saídas, esperado, contado e diferença.
- [ ] Commit: `Faturação: fecho de caixa e relatório Z`

---

## Verificação final do Plano 2A

- [ ] `backend/.venv/bin/pytest tests/faturacao/ -v` — tudo verde
- [ ] Nenhum endpoint do POS aceita o JWT de gestão
- [ ] O índice único parcial existe e impede a segunda sessão aberta
- [ ] Uma entrada com PIN em conflito devolve 409 e não escolhe ninguém
