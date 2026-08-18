# Faturação L'Açaí — Plano 2C: o ecrã do POS

> **Para trabalhadores agênticos:** SUB-SKILL OBRIGATÓRIA: `superpowers:subagent-driven-development`.

**Spec:** `docs/superpowers/specs/2026-08-13-faturacao-lacai-design.md` §7
**Depende de:** Planos 2A e 2B (já no `main`) — entrada por PIN, caixa, venda e emissão fiscal.

**Goal:** a funcionária abre `rh.lisbonb.com/faturacao/pos` no PC da loja, entra com o PIN, abre a
caixa, vende, e emite a fatura. Sem passar pelo backoffice.

**Onde vive:** `frontend/src/pages/pos/` — **fora** do `AdminLayout`. A rota `/faturacao/pos` já
existe e já é de topo; hoje mostra um marcador de lugar (`PosStandalone.js`), que esta fase
substitui.

---

## Global Constraints

- **Sem dependências novas.** Build: `export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH"`
  e `cd frontend && CI=false yarn build`.
- **Nunca o JWT de gestão.** O POS usa dois tokens próprios em `localStorage`: o do **dispositivo**
  (do emparelhamento) e o do **operador** (da entrada por PIN). Vão em cabeçalhos próprios, nunca
  no `Authorization`. Um wrapper de API separado, à parte do `lib/faturacao.js` do backoffice.
- **Ecrã cheio, tocável.** É um PC com rato, mas os alvos são grandes: há fila à frente.
- Tokens de design do portal (`--primary` azul, `--card`, `--border`, `--muted-foreground`),
  **nunca cores fixas**. Nos prints o Vendus é turquesa; aqui é o azul do Gestão — foi o que o dono
  pediu logo no início ("pode ter as cores do gestão mesmo").
- **PT-PT** em tudo.
- O erro 422 do servidor vem como **lista** — usa o `detalhesErro`; entregue cru ao componente de
  notificação, deita a página abaixo.

---

## Task 1: A porta de entrada

**Files:** `frontend/src/pages/pos/PosApp.js` (o shell), `PosEmparelhar.js`, `PosEntrar.js`,
`PosBloqueado.js`, `frontend/src/lib/pos.js` (wrappers) · Modify `App.js`

**A máquina de estados do shell**, por esta ordem:
1. **Sem token de dispositivo** → ecrã de emparelhamento: um campo grande para colar o código que o
   gestor gerou no backoffice, e o nome da loja a aparecer quando o código é aceite.
2. **Com dispositivo, sem operador** → ecrã de entrada.
3. **Com operador** → a aplicação.

**O ecrã de entrada e a tela de descanso são o mesmo ecrã** (é assim no print): **relógio grande no
topo, ao centro**, e por baixo uma grelha de **círculos com a cara de cada operador** e o nome por
baixo. Toca-se na própria cara → aparece um **teclado numérico grande** e quatro casas para o PIN.

- As fotos vêm do colaborador do RH quando o utilizador do POS está ligado a um (`employee_id`);
  quem não tiver, mostra as iniciais num círculo da cor da marca.
- **PIN em conflito (409):** *"PIN em conflito, contacte o gestor."* Nunca deixar entrar.
- **Zeros à esquerda** contam: `0007` é `0007`. O PIN viaja sempre como texto.

**A tela de descanso** aparece ao fim de **5 minutos** sem toques, **sobreposta** ao que estiver por
baixo — não desmonta nada, para a venda em curso não se perder. Volta-se com a cara e o PIN.

- [ ] Commit: `POS: emparelhamento, entrada por PIN e tela de descanso`

---

## Task 2: A caixa

**Files:** `frontend/src/pages/pos/PosCaixaFechada.js`, `PosMenuCaixa.js`, `PosFecharCaixa.js`

**Caixa fechada** (do print): o painel da direita mostra um ícone grande de caixa fechada, o título
**Caixa Fechada**, e por baixo, num bloco cinzento: *"Em 12/08/2026 às 18:56 · Por Rafaela Prates ·
Montante: € 87,58"* — quem fechou, quando e com quanto. Depois **Montante**, com a explicação
*"Introduza o montante disponível em caixa no momento da abertura (pode ser zero)"*, um campo
numérico grande com um botão de calculadora ao lado, e o botão **Abrir Caixa**.

**O menu Caixa**, na barra de cima (do print): Estado da Caixa · Entrada de Dinheiro · Saída de
Dinheiro · Ponto de Caixa · Abrir Gaveta · Fechar Caixa. *(O Modo de Formação e a gaveta ficam
visíveis mas desligados até existirem — com uma explicação, não um botão morto sem dizer porquê.)*

**Fechar caixa:** conta-se o dinheiro, mostra-se **esperado vs contado**, a diferença, e o Z. Se a
verificação contra o Vendus não bater, **avisa mas deixa fechar** — a funcionária tem de poder ir
para casa. Se a leitura não tiver corrido bem, diz **"não foi possível verificar"** e nunca um
número a fingir que é certo.

- [ ] Commit: `POS: abrir caixa, movimentos e fecho com Z`

---

## Task 3: A venda

**Files:** `frontend/src/pages/pos/PosVenda.js`, `PosDialogoProduto.js`, `PosPersonalizacoes.js`

**O ecrã** (do print), em duas colunas:

**Esquerda** — separadores **Venda ao Público | Vendas Aplicações** no topo, com uma lupa de
pesquisa. Por baixo, a grelha de produtos: **5 por linha**, cada um um cartão branco com **foto
quadrada**, nome por baixo, e o **preço a negrito**. Paginação com duas setas circulares ao centro,
em baixo.

**Direita** — a conta. Cabeçalho com três colunas: **Produto · Qtd · Preço**. Vazia, diz ao centro
*"Não existem produtos associados."*. Em baixo: o botão **Imprimir Pedido** (com ícone de
impressora), uma faixa escura com **TOTAL** grande e, por baixo em pequeno, *"N Produtos / N Uni."*,
e por fim **Opções** e o botão **FINALIZAR**.

**Tocar num produto** junta-o à conta. Se tiver personalizações obrigatórias, abre logo o painel
dos toppings.

**Tocar numa linha da conta** abre o **diálogo do produto**, que substitui o painel direito (do
print): seta de voltar e o nome do produto no topo; **Quantidade** com campo e botões − e +;
**Preço Unitário** com o símbolo € e, ao lado, **IVA** numa lista; **Desconto a aplicar** com dois
campos, % e €; **Personalizações** com um botão largo *Editar Personalizações*; **Texto Opcional**;
e em baixo o **total da linha** à esquerda e o botão **Gravar** à direita.

*(O campo "Número(s) de Série" do print não se aplica a açaí — fica de fora.)*

**Cuidados:** o preço e o desconto aceitam no máximo **2 casas decimais** (o servidor recusa mais);
o IVA só se envia se o staff **o mudar**; um produto sem IVA definido não entra na conta, com
mensagem clara.

- [ ] Commit: `POS: grelha de produtos, conta e diálogo do produto`

---

## Task 4: Finalizar

**Files:** `frontend/src/pages/pos/PosFinalizar.js`

Do print: três cartões brancos empilhados, cada um com um lápis à direita —
**Total** (editável: é aqui que se dá desconto na conta toda) · **Cliente** (*Consumidor Final*, e o
lápis abre o NIF) · **Pagamento**. Por baixo, **Mais Opções**, recolhido.

Em baixo, lado a lado: um campo do **valor recebido** com calculadora, o **TROCO** calculado, e o
botão largo **EMITIR DOCUMENTO**.

- O pagamento mostra os tipos activos como botões (Dinheiro, Multibanco, Bolt, Glovo, Uber Eats,
  To Good To Go…) e permite **misto**. O campo do recebido e o troco só aparecem nos tipos que
  **dão troco** — é um sinalizador que vem do servidor.
- **Depois de emitir, o talão sai automaticamente** (quando o agente de impressão existir; por
  agora, mostra o documento emitido com o número e o ATCUD).
- **Um erro do Vendus não pode parecer um erro de internet.** Se o servidor disser que não consegue
  confirmar se a fatura saiu, o ecrã diz **isso** — e não convida a tentar outra vez às cegas.

- [ ] Commit: `POS: ecrã de finalizar e emissão`

---

## Verificação final

- [ ] `CI=false yarn build` limpo
- [ ] Nenhuma chamada do POS usa o `Authorization` do backoffice
- [ ] A tela de descanso não perde a venda em curso
- [ ] Um PIN em conflito não deixa entrar
