# Taxa de depósito (SDR) — desenho

**3 de setembro de 2026.** As cinco lojas facturam pelo nosso POS desde 18 de
agosto. Falta cobrar o depósito de embalagem que a lei obriga desde 10 de abril.

---

## 1. A obrigação, em três linhas

O **Sistema de Depósito e Reembolso** (SDR, marca «Volta») aplica-se às
embalagens primárias **não reutilizáveis** de bebidas, em **plástico, metais
ferrosos e alumínio**, com **menos de 3 litros**
([FAQ da APA, A5](https://apambiente.pt/sites/default/files/_Residuos/FluxosEspecificosResiduos/ERE/SDR/perguntas-frequentes-sdr.pdf)).

- **0,10 € por embalagem**, valor **não sujeito a tributação** (B17).
- A fatura **deve obrigatoriamente discriminar** o valor cobrado, em linha
  separada do preço do produto — **artigo 30.º-E do Decreto-Lei n.º
  152-D/2017** (B18).
- **Não há obrigação de reembolso** para estabelecimentos com área de
  exposição e venda **igual ou inferior a 50 m²** (artigo 30.º-H, alínea c), e
  um estabelecimento HORECA não é automaticamente ponto de recolha (artigo
  30.º-G). **As cinco lojas têm menos de 50 m².**

Ficam de fora: o **vidro**, as **embalagens de serviço** (os copos do açaí) e
as bebidas com **mais de 25% de ingredientes lácteos** (A6).

## 2. O que está apurado (e não é suposição)

Cada um destes foi medido contra a produção ou contra a conta Vendus real.

| Facto | Como se soube |
|---|---|
| O Vendus **não** acrescenta o depósito às faturas que emitimos pela API | 12 faturas reais com bebida: diferença entre o total do documento e a soma das nossas linhas = **+0,00 €** em todas |
| O artigo de depósito **já existe** no catálogo do Vendus | `id 345983786`, `reference VDEP63-26061226`, `title "Déposito"`, `gross_price 0.10`, **`tax_id NS`**, `type_id I`, `stock_control 0`, `status on` |
| Os oito produtos abrangidos já estão associados **no Vendus** | Ecrã «Produtos com Depósito» da conta: as 2 águas e os 6 refrigerantes (Público + App) |
| As embalagens são **lata e plástico** | Fotos do POS do Vendus: refrigerantes em lata, água em garrafa PET |
| **51 embalagens** já saíram sem depósito | Vendas emitidas em modo `normal` desde 18/08: 27 águas + 24 refrigerantes = **5,10 €** |

**A regressão é nossa.** A referência `VDEP63-26061226` indica configuração a
26 de junho; o POS do Vendus aplicava o depósito e o nosso deixou de o aplicar
quando entrou. Os 51 documentos já emitidos são assunto da contabilista, não
deste desenho.

## 3. Como o Vendus faz (a referência a copiar)

Do ecrã de configuração e do POS deles:

- O **Depósito** é uma entidade com nome fixo, referência, descrição e preço
  (`0.1000`, quatro casas). É **um só** na conta.
- A associação a produtos é uma lista à parte, que aceita **produtos** ou
  **categorias** inteiras.
- No balcão, o depósito **não é uma linha de produto**: é uma faixa própria
  entre a lista e o total, com `›` para ajustar a quantidade, e **não conta no
  contador de artigos** (a conta com uma Coca-Cola diz «1 Produtos / 1 Uni.»
  com o depósito à vista).
- O artigo é configurado sem stock e **sem sujeição a descontos**.

Copiamos o comportamento, não o modelo de dados: eles generalizam para vários
depósitos; nós temos um, com valor fixado por lei.

---

## 4. As quatro peças

### Fase 1 — O código de imposto «Não Sujeito»

`precos._TAXAS` mapeia percentagem → código (`23:NOR, 13:INT, 6:RED, 0:ISE`) e
`_CODIGOS_IVA_VALIDOS` deriva daí. O `NS` **não tem percentagem**: não é 0%, é
fora do imposto, e a distinção é o que o SAF-T lê.

- `NS` passa a ser aceite numa **linha de venda**, mas `tax_id_de_taxa()`
  nunca o devolve — nenhuma percentagem lhe corresponde.
- `mapa_imposto` ganha uma **linha própria** para o não sujeito: base igual ao
  valor, imposto zero, e **fora da base tributável**.
- Guarda no catálogo: um produto normal **não pode** ser gravado com `NS` no
  backoffice. Só o depósito o usa.

> **É a peça mais delicada do desenho.** Se o depósito entrar na base
> tributável, o Z que a operadora assina e o SAF-T que vai para a AT passam a
> declarar imposto sobre uma caução.

### Fase 2 — O depósito na nossa configuração

Uma definição única em `fat_definicoes`:

```
{ ativo: bool, valor: 0.10, vendus_ref: "345983786", nome: "Depósito" }
```

e uma marca por produto (`tem_deposito: bool`), com um botão **«aplicar à
categoria»** no ecrã — a conveniência que o Vendus dá pela associação por
categoria, sem uma tabela de ligações que teríamos de manter.

Os oito produtos ficam marcados à partida, porque já sabemos quais são.

**Aviso escrito no próprio ecrã:** esta lista tem de bater certo com a do
Vendus, porque a app L'Açaí factura pela mesma conta e usa a lista de lá. Duas
listas para a mesma pergunta é como nasce uma divergência silenciosa.

**O carimbo.** Quando a linha nasce, guarda `deposito_unitario` (0,10 ou
`None`), pela mesma razão que já guarda `produto_preco`, `sai_na_fatura` e
`vendus_ref`: o que já foi vendido não muda porque amanhã se mexeu na
configuração. `venda._carimbar_sai_na_fatura` é o sítio, e — como o
`vendus_ref` da variante — lê-se **sempre da configuração**, nunca do pedido:
quem factura em nome de que artigo não se aceita de fora.

### Fase 3 — A venda

A linha do depósito é **derivada, nunca gravada**: uma função pura que, dadas
as linhas da conta, devolve quantas embalagens e quanto. Uma fonte só, nada
para sincronizar, nada que possa divergir do resto da conta.

- **No POS:** faixa própria acima do total, com `+`/`−` e «retirar», **fora do
  contador de artigos** — igual ao Vendus.
- **Na emissão** (`_itens_vendus`), uma linha a mais:
  `{id: 345983786, title: "Depósito", qty: N, gross_price: 0.10, tax_id: "NS"}`.
- **No talão**, sai no certificado que o Vendus devolve — automático.

**O desconto global não lhe toca.** O desconto distribui-se pelas linhas, e o
depósito não é preço: é uma caução. É a armadilha óbvia deste desenho e fecha-se
com um teste.

### Fase 4 — O dinheiro dizer a verdade

**Vai no mesmo deploy que a fase 3.** Se não for, o depósito inflaciona a
facturação desde o primeiro dia — que é exactamente o defeito das faturas de
treino apanhado na auditoria de 31/08.

| Onde | Conta? | Porquê |
|---|---|---|
| Gaveta (`esperado`, `vendas_dinheiro`) | **Sim** | O dinheiro entrou mesmo |
| Facturação (painel, relatórios, email, ficha do cliente) | **Não** | É caução, não é receita |
| Mapa de imposto do Z | Linha própria, fora da base tributável | Não sujeito |

E **dito no ecrã**: uma linha «Depósitos cobrados: X €» no Z e no email
diário. Dois números certos lado a lado sem legenda produzem uma leitura
falsa — foi o erro que se repetiu três vezes nesta base de código, e não se
repete aqui.

---

## 5. O que fica deliberadamente de fora

- **O reembolso ao balcão.** Isento por área (<50 m²). Construir um fluxo de
  devolução que ninguém vai usar é código para manter sem razão. Se um dia
  houver adesão como ponto de recolha, é um desenho novo — e a lei diz que aí
  só se aceitariam embalagens compradas e consumidas na própria loja (artigo
  30.º-I).
- **A app L'Açaí.** Os produtos «App» facturam pela mesma conta Vendus mas por
  outro sistema. A obrigação é a mesma e tem de ser tratada lá.
- **Os 51 documentos já emitidos** sem depósito. Assunto da contabilista.

## 6. Testes

Um por cada coisa que pode partir sem se ver:

1. `tax_id_de_taxa()` nunca devolve `NS`, para percentagem nenhuma.
2. A base tributável do mapa de imposto **não inclui** o depósito.
3. O não sujeito aparece no mapa como linha própria, distinta do isento.
4. Um produto do catálogo é recusado com `tax_id: NS`.
5. A linha derivada = soma das quantidades das linhas com carimbo.
6. Uma conta sem bebidas não gera linha de depósito nenhuma.
7. O carimbo: mudar a configuração não muda uma conta já aberta.
8. O `deposito_unitario` vem da configuração, nunca do pedido.
9. O desconto global não altera o valor do depósito.
10. A linha que vai ao Vendus leva `id 345983786` e `tax_id NS`.
11. O Z: o dinheiro do depósito está no `esperado`.
12. O painel e o email: o depósito **não** é facturação.
13. O contador de artigos do POS não conta o depósito.

Mutação em cada um antes de fechar, como é regra da casa.

## 7. Ordem

Fases 1 a 4 num só deploy — a 3 sem a 4 mente nos números, e a 1 sem a 2 não
serve para nada. A configuração (fase 2) fica ligada **desligada** por
omissão, e o dono liga-a quando quiser começar a cobrar.
