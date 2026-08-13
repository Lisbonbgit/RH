# Módulo "Faturação L'Açaí" — Desenho

**Data:** 2026-08-13
**Empresa:** Fordaimon Foods, Lda (NIF 517542510) — marca L'Açaí
**Onde vive:** Gestão Lisbonb (`~/Developer/RH`), como quarta secção ao lado de RH · Financeiro · Marketing

---

## 1. Porquê

Hoje as 5 lojas físicas do L'Açaí usam o **POS web do Vendus** num PC Windows, mais um programa
instalado que trata da impressão. O backoffice do Vendus é o cérebro: catálogo, preços, IVA,
utilizadores, relatórios.

Dois problemas:

1. **Custo.** O Vendus cobra por posto — cada POS é uma subscrição adicional (25% de desconto a
   partir do segundo, 30% a partir do terceiro). São 5 postos hoje, e há mais lojas a abrir.
2. **Encaixe.** O Vendus é genérico. As lojas usam o modo "Restaurante" com salas e mesas para
   vender ao balcão, porque não há outra forma. Metade das funções não servem e as que servem
   não fazem exactamente o que se quer.

**Objectivo:** POS e backoffice próprios, **uma só subscrição Vendus**, e o Vendus reduzido ao
papel de **motor fiscal** — emite os documentos, nada mais.

**Não-objectivo:** certificação própria de software de faturação. Fica para um dia, se compensar.

---

## 2. Decisões fechadas

Estas foram todas validadas com o dono e não se rediscutem sem razão nova.

| # | Decisão |
|---|---|
| D1 | O Vendus continua a emitir todos os documentos fiscais. Sem certificação própria. |
| D2 | Módulo novo dentro do Gestão Lisbonb, com duas secções: **Gestão** e **POS**. |
| D3 | Menu Gestão: Dashboard · Produtos · Documentos · Talões de Desconto · Clientes · Relatórios · Compras. Fora: Contabilidade, Autoridade Tributária, Recomendar. |
| D4 | Menu POS: Iniciar Ponto de Venda · Movimentos de Caixa · Lojas. |
| D5 | Configuração, à parte: Lojas e Caixas · Tipos de Pagamento · Utilizadores · Motivos de Notas de Crédito. |
| D6 | Produtos tem três sub-ecrãs: Produtos · Categorias · Personalizações. |
| D7 | O módulo é dono do catálogo. **As categorias são as do Vendus** — Venda ao Público e Vendas Aplicações — e cada produto pertence a uma, com **um preço e um IVA**. Decidido pelo dono em 2026-08-13, mantendo a gestão igual à de hoje; consequência aceite em §9.1. |
| D8 | **Sem salas nem mesas.** Venda ao balcão directa. |
| D9 | **Sem contas em espera.** Cada venda começa do zero e fecha logo. |
| D10 | POS = página web no PC Windows + **agente de impressão instalado** (talão, cozinha, gaveta; IP e USB). |
| D11 | Entrada no POS por **PIN de 4 dígitos**. Backoffice pelo login normal do Lisbonb. |
| D12 | Tela de descanso ao fim de **5 minutos**: relógio grande + fotos da equipa. A venda em curso não se perde. |
| D13 | **Talão do cliente: automático** ao emitir. **Pedido da cozinha: manual**, no botão. |
| D14 | Sessão de caixa **só do nosso lado**. Nunca abrir nem fechar caixas no Vendus. |
| D15 | **Uma só caixa API no Vendus**, partilhada pela app e pelas 5 lojas. Uma subscrição. |
| D16 | Três perfis: Administrador · Operador de Caixa · Contabilista. Sem "Encarregada de Loja". |
| D17 | A app Android/iOS **não se toca**. Só uma alteração no servidor dela (ver §11). |
| D18 | Identidade visual do Gestão Lisbonb (azul #1366F0 + turquesa; Bricolage Grotesque + Hanken Grotesk). |
| D19 | Compras não se reconstrói — aproveita-se o Financeiro que já existe. |
| D20 | Loja piloto: **Belém** (a de menor faturação, €874/mês — onde um erro custa menos). |

---

## 3. Fases

Cada fase termina no ar e a funcionar antes de começar a seguinte.

| Fase | O que entrega | Fim |
|---|---|---|
| **1** | Cérebro mínimo + POS + caixa + impressão | **Uma loja vende um dia inteiro sem o POS do Vendus** |
| **2** | Documentos, notas de crédito, clientes, talões de desconto, modo de formação | **As 5 lojas fora do POS do Vendus** |
| **3** | Dashboard e relatórios (incluindo as vendas da app) | **Deixa-se de abrir o backoffice do Vendus** |
| **4** | Stock ao ingrediente, fichas técnicas, inventário, custo real | **Saber o que há em cada loja e a margem de cada produto** |
| **5** | O backoffice da app L'Açaí passa para aqui | **Um backoffice só** |

**Este documento especifica a Fase 1.** As outras ficam descritas em §14 apenas para garantir que
o desenho de agora não lhes fecha a porta.

---

## 4. Arquitectura

### 4.1 Onde o código vive

O backend do Gestão Lisbonb é **um único `server.py` com 8.150 linhas e 140 endpoints**, todos no
mesmo `api_router`. Não há pacotes, não há routers separados, e **não existe um único índice
criado no Mongo**.

Acrescentar mais 2.000 linhas a esse ficheiro é insustentável. O módulo nasce como **pacote
próprio**:

```
backend/
  server.py            (inalterado, excepto 2 linhas)
  faturacao/
    __init__.py        router principal
    db.py              cliente Motor próprio (mesmas env vars) + criação de índices
    auth.py            JWT do backoffice + token de POS + token de agente
    lojas.py  caixas.py  utilizadores.py  pagamentos.py
    catalogo.py        produtos, categorias, personalizações
    pos.py             venda, finalizar, emitir
    caixa.py           sessão, movimentos, fecho, Z
    fiscal.py          idempotência + emissão no Vendus + reconciliação
    impressao.py       fila de trabalhos + endpoints do agente
    vendus/            cliente HTTP (levantado da Pizzaria)
```

**Porque um pacote com base de dados própria e não `from server import db`:** o `server.py` teria
de importar o pacote para o incluir, e o pacote importaria o `server.py` — import circular. O
pacote cria o seu próprio cliente Motor a partir das mesmas variáveis de ambiente e faz a sua
própria descodificação de JWT (15 linhas, mesmo `JWT_SECRET`). O `server.py` muda em duas linhas:

```python
from faturacao import router as faturacao_router
app.include_router(faturacao_router)
```

Blast radius: praticamente zero. Se o módulo rebentar, o RH, o Financeiro e o Marketing continuam
a funcionar.

**Índices:** o pacote cria os seus no arranque. É a primeira parte do sistema a ter índices — e
não pode ser de outra maneira, porque há índices únicos que são a própria garantia fiscal.

### 4.2 Frontend

Três pontos de alteração, todos aditivos:

1. `frontend/src/components/layouts/AdminLayout.js` — acrescentar a secção `faturacao` ao array
   `sections`. **Armadilha conhecida:** a secção `rh` é um apanha-tudo negativo
   (`!p.startsWith('/admin/financeiro') && ...`). Sem acrescentar `&& !p.startsWith('/admin/faturacao')`,
   o RH engole a secção nova.
2. `frontend/src/App.js` — bloco de rotas `/admin/faturacao/*` dentro do `AdminLayout`.
3. `frontend/src/lib/api.js` — wrappers das chamadas.

O POS é a excepção: vive **fora** do `AdminLayout`, em ecrã cheio, na rota `/faturacao/pos`, com
o seu próprio contexto de autenticação (token de POS, nunca o JWT de admin).

### 4.3 Colecções (prefixo `fat_`)

Segue a convenção que o Financeiro já usa (`fin_`) e o Marketing (`mkt_`).

| Colecção | Guarda | Índices |
|---|---|---|
| `fat_lojas` | nome, morada, CP, localidade, email, telefone, CAE, `rh_location_id` | |
| `fat_caixas` | nome, `loja_id`, `vendus_register_id`, activa | |
| `fat_utilizadores` | nome, `pin_hash`, perfil, lojas[], activo, `employee_id`, foto | único (`loja_id`,`pin_hash`) |
| `fat_tipos_pagamento` | nome, tipo fiscal Vendus, dá troco, ordem, activo, `vendus_payment_method_id`, **protegido** | |
| `fat_motivos_nc` | texto, predefinido | |
| `fat_categorias` | nome, grupo de preços, ordem, activa | |
| `fat_grupos_personalizacao` | nome, `min_select`, `max_select`, opções[{nome, preço por grupo, `tax_id`}] | |
| `fat_produtos` | nome, categoria, **preço por grupo**, **`tax_id` por grupo**, foto, grupos de personalização[], activo | |
| `fat_sessoes_caixa` | `caixa_id`, aberta por/em, fundo, fechada por/em, contado, esperado | **único parcial** em `{estado:'aberta'}` por caixa |
| `fat_movimentos_caixa` | `sessao_id`, tipo (entrada/saída), valor, motivo, quem | |
| `fat_vendas` | linhas, totais, pagamentos, cliente/NIF, `sessao_id`, operador, loja, estado | (`sessao_id`), (`loja_id`,`criada_em`) |
| `fat_documentos` | `vendus_document_id`, ATCUD, número, tipo, total, `ext_ref`, `venda_id` | **único** `vendus_document_id`; **único** `atcud`; (`ext_ref`) |
| `fat_refs_fiscais` | `ext_ref`, estado, `venda_id` | **único** `ext_ref` |
| `fat_trabalhos_impressao` | `loja_id`, destino, bytes, estado, tentativas | (`loja_id`,`estado`), **TTL** 7 dias |
| `fat_agentes` | `loja_id`, token, impressoras, último contacto | |

---

## 5. O papel do Vendus

### 5.1 O que fazemos

| Fazemos | Não fazemos |
|---|---|
| `POST documents/` — emitir FS e NC | `POST registers/{id}/movements` — **nunca**. Sem abrir/fechar caixa. |
| `GET documents/?external_reference=` — confirmar que uma emissão passou | Escrever no catálogo do Vendus |
| `GET documents/` — reconciliar no fecho (leitura) | Criar, alterar ou desactivar tipos de pagamento |
| `GET documents/paymentmethods/` — ler os métodos | Tocar em nada da caixa que a app usa, além de emitir |

### 5.2 Uma caixa para tudo

Todos os documentos — os das 5 lojas e os da app — saem da **mesma caixa API**. Está provado: é o
que a app já faz hoje em produção, para pedidos de todas as lojas
(`applacai/backend/services_vendus.py:371`), porque o Vendus **rejeita o campo `store_id` no
documento** (erro P001). A loja do documento vem sempre da caixa.

**Qual caixa:** a que a app já usa (`VENDUS_REGISTER_ID`, hoje "Caixa Online" na loja Vendus
"App-Online"). Reutiliza-se essa — assim a app não precisa de alteração nenhuma e não se acrescenta
subscrição.

**Uma acção manual no Vendus antes do arranque:** reconfigurar a loja "App-Online" com o **nome e a
morada da sede da Fordaimon Foods**, porque passa a ser ela a aparecer no talão de todas as lojas.
É só editar a ficha da loja no backoffice do Vendus — não mexe em nada do código.

**Consequências, aceites:**

- O talão leva a morada da sede, não a da loja onde se comprou. A fatura simplificada identifica o
  fornecedor pela **sede**, não pelo estabelecimento. *A confirmar com a contabilista antes do
  arranque.* O nome da loja vai impresso no talão como texto e no campo `notes` do documento.
- Os relatórios do Vendus deixam de separar por loja. Irrelevante: os nossos separam.
- A loja real vai no campo `notes` de cada documento, como a app já faz.

**Protecções obrigatórias** (porque partilhamos a caixa com a app):

1. Todo o documento nosso leva `external_reference` com prefixo `pos-`. Os da app têm outro. É
   assim que a reconciliação os separa sem ambiguidade.
2. Os tipos de pagamento do Vendus são **só de leitura** no módulo. A nossa configuração é um
   mapeamento local (nome no POS → id do Vendus). O id que a app usa fica marcado `protegido` e
   não é editável no ecrã.
3. Nenhum código do módulo chama `registers/{id}/movements`. Nem para abrir, nem para fechar.

### 5.3 Volume

Do dashboard do dono: ~€1.500/dia no grupo, ticket médio €12,98 → **~116 vendas/dia** nas 5 lojas
e app juntas. Menos de uma venda por minuto no pico. O limite do Vendus é por créditos na chave
(headers `Rate-Limit-*`; o exemplo oficial é 100 créditos / 20s). Folga de mais de uma ordem de
grandeza.

O que gasta créditos a sério é o cron nocturno do Financeiro, que lê documento a documento para o
CMV. **Regra:** leituras pesadas fora do horário das lojas; a emissão tem sempre prioridade; num
429, esperar o `Rate-Limit-Reset` e repetir.

---

## 6. Emissão fiscal — o coração

É aqui que os erros custam dinheiro real. O desenho corrige os três buracos que a revisão
encontrou no código da Pizzaria.

### 6.1 Sequência

1. **Referência determinística.** `ext_ref = pos-{loja}-{sessao}-{venda_id}`. Depende só da
   identidade da venda — nunca de um relógio, nunca do conteúdo das linhas. Duas tentativas da
   mesma venda produzem a mesma referência.
2. **Reserva atómica, antes de tocar no Vendus.** `insert` em `fat_refs_fiscais` com índice único
   em `ext_ref`. Quem perder a corrida apanha `DuplicateKeyError` e **nunca emite** — devolve o
   documento do vencedor ou espera por ele. É o padrão que a Pizzaria já usa nas notas de crédito.
3. **Emitir** `POST documents/` com `type=FS`, `register_id`, `external_reference`, `notes` com a
   loja, `items` com preço, IVA e desconto por linha, `payments`, e **`output=escpos`**.
4. **Gravar** em `fat_documentos` (único em `vendus_document_id` e em `atcud`).
5. **Imprimir** — o talão fiscal vem já em ESC/POS na resposta do Vendus. Não desenhamos o layout
   da fatura: vem certificado de lá.
6. **Se o passo 3 falhar por timeout:** `GET documents/?external_reference={ref}` — **uma** chamada,
   exacta. Se o documento existe, foi emitido: usa-se esse. Se não, repete-se.

### 6.2 O que NÃO se copia da Pizzaria

- O dedup que varre os documentos do dia com `per_page=200` sem paginar. Numa loja com 240 talões,
  a fatura original nem entra na lista lida e sai uma segunda fatura real.
- A decisão de "emitir à mesma se a consulta de verificação rebentar".
- `list_open_table_docs` — **o POS nunca lê contas do Vendus.** Um pedido da app já pago pelo
  cliente apareceria como conta por cobrar, e sairia uma segunda fatura de uma venda já paga.

### 6.3 A investigar antes de implementar

- **`tx_id`**: o Vendus documenta idempotência nativa no POST. Nenhum dos nossos repos a usa.
  Testar em `mode=tests` o que devolve num retry. Se funcionar, é uma quarta camada de graça.
- **Linha sem `id` nem `reference`**, só com `title`: a Pizzaria fatura assim há meses sem erro,
  mas a documentação diz que produto novo "será criado". Confirmar se cria produtos fantasma no
  catálogo do Vendus — decide se sincronizamos catálogo ou faturamos por descrição livre.

---

## 7. O POS

### 7.1 Entrar

`/faturacao/pos`, ecrã cheio. Na primeira vez naquele PC pede a **loja e a caixa** — fica guardado
no browser, só se muda pelo menu. Depois disso, **teclado numérico e PIN de 4 dígitos**.

A tela de descanso aparece aos **5 minutos** de inactividade: relógio grande e as **fotos da
equipa** (as que já existem no perfil do RH). Toca-se na própria cara, mete-se o PIN. É uma camada
**sobreposta** — não desmonta nada por baixo, portanto a venda em curso mantém-se intacta.

### 7.2 Abrir caixa

Se a caixa estiver fechada, mostra quem a fechou, quando e com que montante. Campo do fundo de
maneio com calculadora, botão **Abrir Caixa**. Fica registado quem abriu.

Índice **único parcial** em `{estado:'aberta'}` por caixa: é impossível haver duas sessões abertas
na mesma caixa, mesmo com dois PCs a tentar ao mesmo tempo.

### 7.3 Vender

**Esquerda:** grelha de produtos com foto, nome e preço. Separadores por categoria (Venda ao
Público · Vendas Aplicações · …), pesquisa, paginação.

**Direita:** a conta (Produto · Qtd · Preço).

- Tocar num produto junta-o num clique. Se tiver personalizações **obrigatórias**
  (`min_select ≥ 1`), abre logo o painel dos toppings.
- Tocar numa linha da conta abre o **diálogo do produto**: Quantidade · Preço Unitário · IVA ·
  Desconto (% ou €) · Editar Personalizações · Texto Opcional. Modelo levantado da Pizzaria, já
  validado em produção.

**Rodapé:** TOTAL com contagem de produtos/unidades · **Imprimir Pedido** (cozinha, manual, sai o
pedido todo) · **FINALIZAR**.

### 7.4 Finalizar

Três cartões, cada um com o seu lápis:

- **Total** — editável; é aqui que se dá desconto na conta toda
- **Cliente** — "Consumidor Final" por omissão; o lápis abre o campo do NIF
- **Pagamento** — botões dos tipos activos (Dinheiro, Multibanco, Bolt, Glovo, Uber Eats,
  To Good To Go, …), com **pagamento misto** suportado

Se o tipo escolhido der troco, aparece o campo do **valor recebido** e o **troco** calculado.

**EMITIR DOCUMENTO** → §6 → o **talão sai automaticamente**.

### 7.5 Menu de cima

- **Caixa:** Estado · Entrada de Dinheiro · Saída de Dinheiro · Ponto de Caixa · Abrir Gaveta ·
  Fechar Caixa *(Modo de Formação fica para a Fase 2)*
- **Documentos:** pesquisar e reimprimir
- **Utilizador:** bloquear ecrã · trocar de utilizador · alterar loja/caixa · sair

### 7.6 Fechar caixa

Conta-se o dinheiro → **esperado vs contado** → diferença → **Z impresso**.

O esperado calcula-se **das nossas vendas**, não do Vendus. Mas o fecho faz uma **verificação de
leitura**: `GET documents/` da janela da sessão, filtrado pelo nosso prefixo `pos-`, **paginado
até esgotar**, descartando anulados (`status='A'`) e ignorando tudo o que não seja FS/FR/FT/NC.

- Bate certo → não diz nada.
- Não bate → **avisa, mas deixa fechar**. A funcionária tem de poder ir para casa. O aviso fica
  registado e aparece no backoffice no dia seguinte.
- **A leitura não conseguiu ler tudo** (paginação bateu no tecto) → não afirma que bate nem que
  não bate. Diz que não conseguiu verificar. Nunca inventar um número que a operadora vai usar
  para justificar dinheiro.

---

## 8. Agente de impressão (Windows)

### 8.1 Arquitectura

**Programa instalado que liga para nós** — long-polling HTTPS (`GET` pendurado de 60s, com
fallback para polling de 3s).

**Porque não um servidor local em `localhost`**, que é o que o "Vendus Dispositivos" faz: o Chrome
bloqueou os pedidos de páginas HTTPS públicas para `localhost` (e estendeu-o aos WebSockets em
2026), com pedido de permissão em cada PC. Foi assim que sistemas de impressão equivalentes
rebentaram em campo. A única saída seria forçar política de empresa por GPO nos 5 PCs.

**Porque long-polling e não WebSocket:** atravessa a cadeia Caddy → nginx do Lisbonb sem
configuração nova (`proxy_read_timeout` já é 120s), não precisa de portas abertas no router da
loja, e o backend corre com 2 workers asyncio — 5 ligações penduradas é irrelevante.

### 8.2 Como funciona

- **Stack:** Python (o backend já é Python), empacotado com PyInstaller num `.exe` único, instalado
  por Inno Setup, registado como serviço com WinSW (arranca com o Windows, antes do login).
- **Emparelhamento:** cola-se **um código** gerado no backoffice; o agente recebe um token que já
  traz a loja lá dentro.
- **Impressoras:** rede por **socket TCP porta 9100**; USB pelo **spooler do Windows em modo RAW**
  (`pywin32`/`win32print`). Nunca libusb/Zadig — destrói a impressora no Windows.
- **Mapeamento "que impressora para que papel" vive no nosso backoffice**, não no PC. Assim
  arranja-se uma loja sem lá ir.
- **Os bytes ESC/POS são gerados no servidor.** O agente é burro: recebe bytes, escolhe o canal,
  imprime. O talão fiscal nem sequer é gerado por nós — vem do Vendus.
- **Gaveta:** o agente expõe um atalho local que dispara o pulso `\x1b\x70\x00\x19\xfa`
  **directamente na impressora, sem passar pela nossa API**. É a única coisa que a loja tem
  mesmo de conseguir fazer sem internet.

### 8.3 Defeitos do agente da Pizzaria que NÃO se repetem

- Marcava o trabalho como impresso **sem verificar** se o servidor recebeu a confirmação. Numa
  rede a oscilar, o trabalho ficava pendente e era reimpresso indefinidamente. Aqui: só sai da
  fila com confirmação verificada, com contador de tentativas e limite.
- A colecção de trabalhos não tinha índice nem limpeza. Aqui: índice + TTL de 7 dias.

---

## 9. Catálogo

### 9.1 Modelo

Levantado do que a app já tem (`products`, `categories`, `modifier_groups`), que por sorte tem
**exactamente a forma que o Vendus usa**: grupo com `min_select`/`max_select` e opções com preço.

Semântica derivada, sem campos redundantes:
- obrigatório = `min_select ≥ 1`
- escolha única (radio) = `max_select == 1`
- `max_select == 0` = ilimitado

**O modelo espelha o Vendus** (decisão do dono, D7): a **categoria** é "Venda ao Público" ou
"Vendas Aplicações", o produto pertence a **uma** e tem **um** preço e **um** IVA. No POS, os
separadores de cima são as categorias — exactamente como hoje.

**Consequência aceite:** os artigos continuam duplicados. "Açaí Regular" (€8,99, Venda ao Público)
e "Açaí Regular App" (€10,99, Vendas Aplicações) são dois produtos, e mudar o nome ou a foto
obriga a fazê-lo duas vezes. O mesmo se aplica aos toppings: "Nutella" como personalização a €0,95
no balcão e "Extra Nutella" como produto a €1,00 na app continuam separados, porque uma opção de
personalização também só tem um preço.

Foi apresentada a alternativa (um produto com dois preços, categorias por família) e o dono
escolheu manter a gestão igual à de hoje. Se um dia isso pesar — sobretudo na Fase 5, quando o
backoffice da app vier para cá — a mudança é de modelo de dados e de migração, não de arquitectura.

**Uma diferença em relação ao modelo da app, obrigatória aqui:** o **IVA por artigo**, sem valor
por omissão (§9.2).

### 9.2 IVA — sem valores por omissão

Hoje a app resolve com `vat_rate = prod.get('vat_rate', 13)`: um produto sem IVA definido sai a
13% **sem erro nenhum**. Bastaria criar "Coca-Cola 33cl" sem preencher o IVA para faturar
refrigerantes a 13% durante meses.

**Regra dura:** `tax_id` obrigatório. Um produto sem IVA definido **não pode ser vendido** — o POS
recusa a linha com mensagem clara, em vez de emitir a 13%. Ecrã em Configuração com a lista
"Produtos sem IVA definido", e o catálogo não se publica enquanto ela não estiver vazia.

**A confirmar com a contabilista, por escrito, antes de carregar o catálogo:** a taxa de cada
família — açaí consumido no local, açaí para levar, refrigerantes, águas, salgados, saco de
transporte, e a caução do copo reutilizável (isenta, com motivo). Não se inventa a partir do que
está hoje no Vendus.

### 9.3 Importação inicial

Importa-se do Vendus (produtos, categorias, preços, IVA, referências) para não se escrever nada à
mão. Duas notas:

- Marcar os produtos que vierem com categoria "Não Definido" (o dashboard mostra 0,04% das vendas
  assim) para arrumar.
- A importação traz o catálogo **tal como está**, incluindo os artigos duplicados entre as duas
  categorias — é o que a decisão D7 implica. Nada é fundido automaticamente.

### 9.4 Não escrevemos no catálogo do Vendus

O módulo é dono do catálogo **do nosso lado**. As linhas da fatura vão para o Vendus com título,
preço, IVA e desconto — como a app já faz. Isto evita partir referências que a app usa.

*(Pendente de §6.3: confirmar que faturar por título não cria produtos fantasma no Vendus.)*

---

## 10. Configuração

- **Lojas e Caixas** — ficha de cada uma das 5 lojas (nome, morada, CP, localidade, email,
  telefone, CAE) e a caixa que lhe está atribuída no POS. **Nota importante:** as "caixas" deste
  ecrã são as nossas — a de Belém, a de Oeiras, etc. — cada uma com a sua sessão, o seu fundo de
  maneio e o seu Z. Do lado do Vendus **existe uma só**, partilhada, e o seu `register_id` é
  configuração do sistema, não algo que se escolha por loja.
  Guarda no backend: qualquer emissão com um `register_id` diferente do único configurado é
  recusada **antes** de sair para o Vendus. Não há selector de `register_id` em lado nenhum da
  interface — assim é impossível apontar por engano para outro sítio.
- **Tipos de Pagamento** — nome livre + tipo fiscal do Vendus (NU, CD, CC, TB, …) + dá troco + ordem
  + activo. **Só de leitura sobre o Vendus**: a nossa configuração é um mapeamento local. O método
  que a app usa fica `protegido` e não é editável.
- **Utilizadores** — nome, PIN, perfil, lojas onde entra. Liga-se opcionalmente ao colaborador do
  RH para herdar nome e foto. Quem sai fica **inactivo**, nunca apagado.
- **Motivos – Notas de Crédito** — lista com um predefinido. *(Usado na Fase 2.)*

---

## 11. A alteração no servidor da app

**Autorizada pelo dono.** Só no `api.olacai.com`. Não mexe na app do telemóvel, não precisa de
build, não vai à Apple nem ao Google.

**O problema:** o resgate de pontos por QR
(`applacai/backend/services_vendus.py:216-294`) procura a fatura no Vendus pelo **sufixo** do
ATCUD, pede 20 resultados e compara só os **10 primeiros**. Funciona hoje porque as séries já vão
em 5 dígitos. Com a caixa nova a numerar do 1, "7" e "13" casam com centenas de documentos, a
fatura verdadeira fica fora da lista e o cliente leva *"não conseguimos confirmar esta fatura"* —
com 48 horas para resgatar.

**A correcção, melhor do que a original:** a partir do momento em que somos nós a emitir, **temos
todas as faturas**. A app passa a perguntar **ao nosso módulo** — "este ATCUD, nesta data, com este
total, é vosso?" — e a resposta é uma consulta directa e exacta na nossa base de dados. Sem listas,
sem limites, instantânea.

O Vendus fica como recurso secundário, para as faturas antigas e as da própria app.

---

## 12. Riscos e o que os trava

| Risco | Mitigação | Onde |
|---|---|---|
| Fatura duplicada por duplo-toque ou timeout | Referência determinística + reserva atómica + confirmação por `external_reference` | §6.1 |
| Pedido da app já pago cobrado outra vez ao balcão | O POS nunca lê contas do Vendus. Pedidos da app marcados "JÁ PAGO — só preparar" | §6.2 |
| Fechar a caixa partilhada e deixar a app sem faturar | Nunca chamamos `registers/{id}/movements`. `register_id` é único e fixo em configuração, sem selector na interface | §5.1, §10 |
| Desactivar o método de pagamento que a app usa | Tipos de pagamento só de leitura; id da app protegido | §10 |
| Resgate de pontos por QR partido | Alteração do §11, antes do arranque da 1.ª loja | §11 |
| IVA errado por omissão silenciosa | `tax_id` obrigatório; sem IVA não se vende | §9.2 |
| Z calculado sobre leitura truncada | Paginar até esgotar; se não conseguir ler tudo, dizer que não verificou | §7.6 |
| Loja parada sem internet | Gaveta abre localmente; UPS + failover 4G recomendados; procedimento de contingência escrito | §8.2, §13 |
| Migração a meio: metade das vendas em cada sistema | Numa loja, num dia: **ou é tudo o novo ou é tudo o Vendus**. Nunca metade | §13 |
| Talão reimpresso indefinidamente | Confirmação verificada + limite de tentativas + TTL | §8.3 |

---

## 13. Arranque da loja piloto

1. As caixas do POS Vendus **ficam instaladas e activas** durante todo o piloto. É o caminho de
   volta: reabre-se e vende-se.
2. **Uma loja de cada vez**, em dia fraco, com o dono ou alguém nosso presente do abrir ao fechar.
3. **Regra não negociável:** numa loja, num dia de trabalho, ou é tudo o sistema novo ou é tudo o
   Vendus.
4. **Nada de `mode=tests` com clientes reais.** A formação faz-se numa caixa de testes descartável,
   com produtos de brincar. A loja em produção emite em `normal` desde a primeira venda.
5. **Teste de aceitação antes de abrir a porta:** uma venda de 1€, ler o QR do papel com a app e
   **ver os pontos entrarem**. É o único ensaio que prova a coexistência.
6. Recomendado por loja: UPS pequeno (PC + router + impressora do caixa) e router com failover 4G.
   ~100-150€ contra horas de venda perdidas.

---

## 14. Portas que ficam abertas (fases seguintes)

- **Stock (Fase 4):** o catálogo já nasce com o sítio para a ficha técnica — por produto **e por
  opção de personalização** ("Leite em Pó" = 20g). As compras vêm do Financeiro, mas
  **`fin_invoices` só guarda cabeçalho e totais, sem linhas** — falta um passo de extracção de
  artigos e quantidades. Existe já no `server.py` uma extracção multi-linha por IA provada (a dos
  extratos bancários) que serve de molde.
- **Backoffice da app (Fase 5):** o catálogo já prevê foto, descrição e disponibilidade por loja.
- **Certificação própria:** toda a emissão está isolada em `fiscal.py`. Trocar o motor é trocar um
  ficheiro.

---

## 15. Fora do âmbito da Fase 1

Notas de crédito · Talões de desconto · Clientes · Dashboard · Relatórios · Modo de Formação ·
Stock · Compras · Migração das outras 4 lojas.

---

## 16. Por confirmar antes de implementar

| # | O quê | Com quem |
|---|---|---|
| Q1 | Quanto custa uma caixa API e qual o limite de créditos do plano | Vendus (uma chamada) |
| Q2 | IVA por família, e consumo no local vs para levar | Contabilista, por escrito |
| Q3 | Reconfigurar a loja Vendus "App-Online" com o nome e a morada da **sede** da Fordaimon Foods (passa a ser o cabeçalho de todos os talões) | Contabilista + acção manual no Vendus |
| Q4 | `tx_id` dá mesmo idempotência nativa? | Teste em `mode=tests` |
| Q5 | Faturar linha só com `title` cria produtos fantasma no Vendus? | Teste em `mode=tests` |
| Q6 | ~~Fundir os toppings duplicados~~ — **decidido 2026-08-13: não se funde nada**, o catálogo espelha o Vendus (D7) | ✅ |
