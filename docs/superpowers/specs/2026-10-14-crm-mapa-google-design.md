# Adenda ao desenho do CRM Purple House — o mapa passa a Google (v2, sem Places UI Kit)

- **Data:** 2026-10-14 · **Revisão v2:** 2026-10-18 · **Ficheiro:** `docs/superpowers/specs/2026-10-14-crm-mapa-google-design.md`
- **Autor:** Bruce Silva (com Claude Code)
- **Estado:** decisão do dono (2026-10-14: "o mapa passa a Google"); v2 reescrita a 2026-10-18 depois da revisão por 2 críticos só de leitura e das decisões do orquestrador (sem Places UI Kit; "Confirmar" só depois de arrastar; nada nosso sobre a atribuição da Google; consola já feita). Abordagem aprovada pelo Bruce em conversa a 2026-10-18 (balão da própria Google + "Confirmar" só depois de arrastar o pino); não há revisão por escrito pendente antes da G2 — ficam por fechar só os pontos do §5, pelo dono, ao longo do plano. Plano de execução: `docs/superpowers/plans/2026-10-14-crm-mapa-google.md`.
- **Base:** [desenho no portal](2026-10-09-crm-purple-house-no-portal-design.md) e [desenho original](2026-10-02-crm-purple-house-desenho-original.md). Esta adenda **substitui**: no original, a linha "Porque não a Google Places/Routes" do §9 (reavaliada com os Termos EEA em vigor) e a parte dos mapas do §6.2 e §6.8; no desenho do portal, a linha "Leaflet 1.9.4" do §2 e §4.2 e as chaves do §4.4. **Tudo o resto fica**: fases, GPS só ao tocar, nomes sempre visíveis sem agrupamento, openrouteservice para as rotas.
- **O que a v2 muda em relação à v1 (resumo):** sai o Places UI Kit (a página *overview* da Google diz "Experimental (pre-GA)", e a regra do próprio desenho é não publicar nada pré-GA); entra só o que é GA no Maps JavaScript API: o balão **da própria Google** ao tocar num negócio, a classe `Place` com `fetchFields` restrito a `location` (e, na pesquisa de moradas, `formattedAddress` + `addressComponents`), e o `PlaceAutocompleteElement`. "Confirmar localização" passa a exigir que a pessoa **arraste o pino** quando ele veio da Google, por isso nenhuma coordenada da Google fica guardada e a "questão dos 30 dias" desaparece. A secção da consola passa a "já feito / falta". O §6.8 lista as diferenças uma a uma.
- **Pesquisa verificada:** Termos EEA do Google Maps Platform (`cloud.google.com/terms/maps-platform/eea`: Termos Específicos EEA §3.2.2, §3.3.2, §4.3.2, §6.1, §6.5, §15, §16, §A.2–A.4), lista de usos permitidos da Places API para faturação EEA (inclui "address autocompletion"), documentação do Maps JavaScript API (loader, Advanced Markers, Map ID, `click` com `placeId`, `Place.fetchFields`, `PlaceAutocompleteElement` e o evento `gmp-select` com `placePrediction`), preços por SKU (Essentials/Pro/Enterprise, lista de março de 2025) — v1 a 2026-10-14; a crítica de 2026-10-18 confirmou o estado "Experimental (pre-GA)" do Places UI Kit e o estado real da consola (§3.1).

---

## 0. Em poucas frases, para o Bruce

1. **O mapa do CRM passa a ser o da Google**, com as ruas, os nomes e os negócios à vista, como na app Google Maps. Fica a **0 €** dentro das quotas gratuitas mensais (ver §3.3), e tu já fizeste a parte da consola (§3.1).
2. **O balão do negócio é o da própria Google.** Quando tocas num negócio no mapa, abre o balão normal da Google (o mesmo de qualquer site que use o Google Maps), com o nome e o resto. Nós **não mostramos nem copiamos** nada disso: ao lado do mapa aparece só um pequeno painel "Negócio selecionado" com o botão **"Adicionar como loja"**. O nome e o telefone da loja escrevem-se à mão: no ecrã "Nova loja", tocar no ícone do negócio no mapa pequeno volta a abrir o balão da Google, para os leres enquanto escreves (nada se copia).
3. **Para confirmar uma loja, arrastas o pino até à porta.** Quando o pino vem da Google (de um negócio ou de uma morada pesquisada), o botão "Confirmar localização" só liga **depois de arrastares o pino**, com a dica "Arraste o pino até à porta da loja para confirmar". É o mesmo mecanismo do GPS impreciso. Assim, a localização guardada é sempre posta por ti, não pela Google — e por isso não há prazos nem tarefas de "30 dias" com a Google.
4. **De onde vem a morada escrita na ficha:**
   - depois de **pesquisares uma morada** na caixa de pesquisa (que é da Google), a morada, o código postal e a localidade vêm **da Google** — a morada que escolheste — e ficam na ficha da loja, onde os podes corrigir;
   - nos pinos do **GPS** ("Estou nesta loja"), a morada sugerida continua a vir do **OpenStreetMap** (pela Geoapify, dados abertos) e pode diferir um pouco da Google (número de porta, grafia);
   - num **negócio tocado no mapa** ou num **pino posto à mão**, a morada escreve-se à mão (podes lê-la no balão da Google).
   Em todos os casos, **revê a morada antes de guardar**.
5. **O que é teu continua a ser escrito por ti:** nome, telefone, pessoa de contacto, notas; a região escolhe-se à mão. Guardamos só o pino que confirmaste e o identificador do lugar na Google (o *place ID*), que a Google deixa guardar sem prazo.
6. **O que falta de ti** (§3.1 "falta" e §5): pôr os tetos diários na consola, aceitar os Termos EEA se a consola o pedir, decidir se o mapa também abre em `rh.lisbonb.com` e na app instalada, aprovar o texto da privacidade e, depois de publicado, fazer tu a **prova em produção** (tocar num negócio, adicioná-lo, pesquisar uma morada) antes de anunciares à equipa.

---

## 1. O que muda para quem usa

### 1.1 Mapa (ecrã principal)
- O fundo passa a ser o **Google Maps**, com as ruas, os nomes e os **negócios (POI) com ícone**. Os pinos das nossas lojas ficam por cima, com a **cor da fase e o nome sempre à vista**, em qualquer zoom, sem agrupamento (como hoje).
- **Tocar num negócio da Google** (o ícone dele no mapa) abre o **balão por omissão da Google** nesse sítio (nós não o alteramos nem o escondemos) e, **ao lado do mapa** — no sítio onde hoje abre o cartão da loja, nunca por cima do mapa —, o painel **"Negócio selecionado"**, com o texto fixo "Negócio selecionado no mapa.", os botões "Adicionar como loja" e "Fechar" e, por baixo da ação, a dica de que o nome da loja se escreve à mão (lendo-o no balão da Google). O painel não mostra nome nem morada.
- **"Adicionar como loja"** leva ao ecrã "Nova loja" com o pino **solto** no sítio desse negócio (pedido à Google só nesse momento, e só a posição), a dica "Arraste o pino até à porta da loja para confirmar" e **"Confirmar localização" desligado até se arrastar**. **O campo "Nome" fica vazio, para a pessoa o escrever** (a dica diz-lhe que, tocando no ícone do negócio no mapa pequeno, o balão da Google volta a abrir para o ler); a morada também se escreve à mão.
- Tocar num pino nosso abre o cartão da loja, como hoje. Filtros, "N lojas", "Nova loja", `?loja=<id>` e o aviso "Loja guardada" não mudam.
- Os botões de zoom passam a ser os da Google (em português, porque o mapa carrega com `language=pt-PT`). O logótipo "Google", "Dados do mapa ©", "Termos" e os atalhos de teclado ficam no fundo do mapa, postos pela Google, e **nada nosso fica por cima deles** (§2.2).

### 1.2 Adicionar loja / corrigir localização (seletor)
- O campo "Pesquisar morada" (Geoapify) dá lugar a **"Pesquisar morada ou lugar (Google)"**: é o elemento de pesquisa da própria Google (moradas e negócios, só Portugal, com preferência pela zona que o mapa mostra). Escolher uma sugestão **põe o pino nesse sítio** (solto, zoom de rua), **preenche a morada, o código postal e a localidade com o que a Google devolveu para essa escolha** (mostrado como "Morada sugerida: …"), e pede para **arrastar e confirmar**.
- **Tocar num negócio no mapa pequeno do seletor** abre o balão da Google e o painel "Negócio selecionado" com "Pôr o pino neste negócio": o pino vai para lá, solto, e é preciso arrastar para confirmar. A morada não se preenche (é um negócio, não uma morada pesquisada).
- **"Estou nesta loja" não muda:** GPS só ao tocar, uma leitura, círculo da precisão, "Localização imprecisa — ajuste o pino" acima de 50 m, morada sugerida pela Geoapify ("Morada sugerida: … · Powered by Geoapify").
- Tocar no mapa (fora dos negócios) continua a pôr o pino à mão; arrastar e confirmar, como hoje (o pino à mão confirma-se sem arrastar, como hoje).
- Na ficha da loja, "Corrigir localização" usa o mesmo seletor; o pino guardado é nosso, por isso confirma-se sem arrastar, a não ser que se escolha outro negócio ou outra morada. Nas Definições, o ponto da fábrica também (sem GPS; aí a pesquisa serve só para pôr o pino e a fábrica não guarda *place ID*).

### 1.3 Rotas (F3, por fazer)
- O planeador desenha a **linha da rota (openrouteservice) sobre o mapa Google**, com os pinos numerados. Antes da linha aparece a frase obrigatória **"Routing provided by openrouteservice"** e, no painel (nunca sobre o mapa), a atribuição "Developed by VROOM · Hosted by HeiGIT · Routing by openrouteservice · Data from OpenStreetMap", **separada** da atribuição da Google.
- No planeador os negócios da Google não são clicáveis (não fazem falta e o balão taparia o mapa): tocar num ícone conta como tocar no mapa.
- A ordem (VROOM) e as horas (Directions) continuam no openrouteservice; a Google não calcula rotas no CRM.

### 1.4 O que não muda
Fases e cores; nomes sempre visíveis sem agrupamento; GPS só ao tocar e nunca seguimento; duplicados a 50 m; nome e telefone escritos pela pessoa; a região escolhida à mão; o openrouteservice nas rotas; as regras de quem vê o CRM.

---

## 2. As regras da Google que seguimos (faturação em Portugal = Termos EEA)

### 2.1 O que guardamos, o que nunca guardamos, o que só se mostra

| | O quê | Porquê é permitido |
|---|---|---|
| **Guardamos** | O **pino confirmado** pela pessoa (lat/lng), com a origem `pin_manual`, `gps` ou `geocoder` (fluxo antigo). Quando o pino veio da Google, só se guarda **depois de arrastado**, logo como `pin_manual` | É a localização do nosso cliente, posta e confirmada por nós; lat/lng não são "Google Maps Content" protegido quando os põe a pessoa (§15.1) |
| **Guardamos** | O **`google_place_id`** do negócio ou da morada escolhida (sem prazo) | Termos Específicos EEA §A.3: o `place_id` pode ficar em cache indefinidamente |
| **Guardamos** | **Nome, telefone, pessoa de contacto, notas** escritos pela pessoa | Não vêm da Google |
| **Guardamos** | **Morada, código postal e localidade** (a) da **pesquisa de moradas da Google**, quando a pessoa escolhe uma morada e a revê; (b) da **Geoapify** (OpenStreetMap) para os pinos do GPS; (c) escritos à mão | (a) "address autocompletion" para preencher um formulário é um uso permitido da lista EEA; a morada fica na ficha da loja, não se mostra sobre outro mapa (§6.1); (b) dados OSM podem guardar-se; (c) não vêm da Google |
| **Nunca guardamos** | Nome, morada, telefone, site, horário, fotos, avaliações **de um negócio** vindos da Google — nem por "copiar" automático, nem por botão "copiar"; e **nunca uma coordenada da Google tal e qual** (a regra do arrasto garante-o) | §3.3.2(a) "No Scraping… copy and save business names, addresses"; §15.4 (coordenadas da Places só 30 dias) |
| **Nunca fazemos** | Atribuir região por "ponto dentro de polígono" com coordenadas da Google; criar o nosso próprio balão (`InfoWindow`); esconder ou tapar a atribuição | §3.3.2(c)(iv); §16.1 |
| **Só se mostra, pela própria Google** | O balão por omissão do negócio (`InfoWindow` da Google ao tocar num POI) e a lista de sugestões da pesquisa (`PlaceAutocompleteElement`) | São elementos da Google, com a atribuição dela, dentro do mapa dela |
| **Só lemos do objeto `Place`** | `id` e `location` (sempre); `formattedAddress` e `addressComponents` **só** na pesquisa de moradas | Essentials; tudo o resto é um canário recusado pelo `seguranca.test.js` |

**Os dois testes espaciais do servidor não são atribuição de território.** O servidor já corre, sobre toda a coordenada que recebe, a caixa de Portugal continental ("Fora de Portugal", `dominio/geo.py`) e o pré-filtro dos duplicados a 50 m (`$geoWithin $centerSphere` sobre o índice `loc`, `crm/db.py`). São regras de validade e de duplicados sobre o **pino posto pela pessoa** (garantido pela regra do arrasto), não "geofencing" com coordenadas da Google; a região continua a escolher-se à mão. Sem alteração de código.

### 2.2 Obrigações na app
- **Página de privacidade** (§6.8 do original; hoje a secção 8 de `/privacidade`, mais o §4 "Partilha de dados"): diz que o mapa do CRM é o Google Maps (Google Ireland Limited), que **"ao usar o mapa do CRM, o membro fica sujeito aos [Termos adicionais do Google Maps/Google Earth](https://maps.google.com/help/terms_maps/) e à [Política de Privacidade da Google](https://policies.google.com/privacy)"** (Termos EEA §3.2.2 exige dizê-lo às pessoas, não só descrever o conteúdo); que o nome e o telefone nunca se copiam da Google e só se guardam o identificador do lugar e o pino confirmado; que a morada sugerida vem da Google (pesquisa) ou da Geoapify/OpenStreetMap (GPS). Sai a frase do Leaflet e do OpenMapTiles. Redação a aprovar pelo Bruce (dossiê §14, ponto 7).
- **GPS:** consentimento expresso e revogável (§4.3.2) — já cumprido: só ao tocar em "Estou nesta loja".
- **Atribuições e disposição:** a da Google é posta pela própria API e **nunca se esconde com CSS nem se tapa com elementos nossos**. Regra de disposição: **o elemento do mapa da Google não tem nenhum filho nosso**; cartões, painéis ("Negócio selecionado", cartão da loja, painel do planeador), pegas de arrasto e rodapés (o do ORS) vivem **fora da caixa do mapa e redimensionam-no** (nunca `position: absolute` com `bottom`/`inset` sobre o mapa). A única sobreposição que existe hoje — a barra de cima com "N lojas", Filtros e "Nova loja" (`.crm-mapa__barra`, ancorada por `top`, que deixa passar os toques) — fica, porque não toca no fundo do mapa, onde está a atribuição. O `css.test.js` garante a regra; o Playwright (G21) confere a 375 × 812 e a 1280 × 800, com o cartão da loja e o painel abertos, que a caixa do logótipo e da atribuição da Google não é intersetada por nada nosso. A Geoapify fica junto à morada sugerida do GPS; a do openrouteservice no painel do planeador, separada da Google (§A.2), com "Routing provided by openrouteservice" (§A.4.3).
- **Só GA.** Maps JavaScript API no canal `weekly`; `AdvancedMarkerElement`; `google.maps.places.Place` + `fetchFields`; `google.maps.places.PlaceAutocompleteElement`. **Nada** marcado *Experimental*, *pre-GA*, *beta* ou *preview* (Termos EEA §6.5): **nenhum elemento do Places UI Kit** (`gmp-place-details-*`, `gmp-basic-place-autocomplete`, …), nenhum "Advanced…".

### 2.3 Porque não há "questão dos 30 dias"
O §15.4 limita a 30 dias a cache de coordenadas vindas da Places API. Na v1 havia uma opção em que o pino confirmado sem arrastar coincidia com a coordenada da Google. Na v2 isso não pode acontecer: para um pino que veio da Google, "Confirmar localização" **só liga depois de arrastar**. A coordenada guardada é sempre a que a pessoa pôs (`origem_coords: pin_manual`), acompanhada do `google_place_id` (cache indefinida permitida). Não há tarefa de refrescamento, não há proxy no servidor e a origem `google` existe **só como estado passageiro do seletor** (nunca é gravada; o servidor recusa-a com 422).

---

## 3. Consola, chaves e custos

### 3.1 Consola Google Cloud — já feito / falta (só o dono; nada passa pelo chat nem pelo git)

**Já feito (confirmado a 2026-10-18):**
- Projeto **471320735027**, com faturação ligada (Termos EEA por ser faturação em Portugal).
- APIs ativadas: **Maps JavaScript API** e **Places API (New)**. As duas ficam: a Places API (New) é a que a biblioteca `places` do Maps JS usa para o `fetchFields` e para o `PlaceAutocompleteElement`. Não se ativa mais nenhuma (nem Geocoding, nem Routes, nem Places UI Kit).
- **Chave do navegador** restrita a **Websites** `https://lisbonb.com/*` e às **duas APIs** acima.
- **Map ID** criado (tipo JavaScript). O existente serve: **raster, sem estilo** (os negócios ficam visíveis e clicáveis por omissão). Os agentes nunca pedem o valor.
- No servidor, `backend/.env` já tem `CRM_GOOGLE_CHAVE_NAVEGADOR` e `CRM_GOOGLE_MAP_ID` (sem aspas).

**Falta (pelo Bruce):**
1. **Termos EEA:** se a consola (Google Maps Platform → Support, ou um aviso no topo) pedir para aceitar os Termos EEA, aceitar (só um Owner/Editor do projeto o pode fazer). Se não pedir, não há nada a fazer.
2. **Tetos diários** (o travão que impede cobranças; os valores do §3.3): Maps JavaScript API → quota de carregamentos do mapa **por dia** (ex.: **300**); Places API (New) → quotas por dia dos métodos de **Autocomplete** (ex.: **100**) e de **Place Details** (ex.: **200**); se algum método não tiver teto diário editável, fica o teto por minuto. **Orçamento de 1 €** com alerta a 50/90/100 %. Subir um teto é imediato.
3. **Referrers (decisão, §5):** acrescentar `https://rh.lisbonb.com/*` (recomendado: custo zero; o `rh.lisbonb.com` é sinónimo permanente no Caddyfile) e decidir a **app instalada** (Lisbonb RH, Capacitor): dentro dela o Referer nunca é `lisbonb.com`, por isso, sem mais nada, o mapa do CRM **só abre no browser** (a mensagem é "Não foi possível carregar o mapa"). Opção (a), por omissão: aceitar "o mapa do CRM só no browser" (a privacidade já diz que o CRM se usa no browser). Opção (b): acrescentar aos referrers `https://localhost/*` (Android) e o esquema do iOS (`capacitor://localhost/*`, se a consola o aceitar; senão `iosScheme: 'https'` no `capacitor.config.json`, ficheiro partilhado → Matheus).
4. **Em local** (para a verificação G21): a **Maps Demo Key** da Google (`developers.google.com/maps/demo-key`, sem faturação, com limite diário) em `backend/.env.local`: `CRM_GOOGLE_CHAVE_NAVEGADOR=<demo key>` e `CRM_GOOGLE_MAP_ID=DEMO_MAP_ID`. Sem nenhuma chave, o CRM mostra "Mapa não configurado" e o resto funciona.
5. **Ao publicar (G23):** se o `.env` do servidor ainda tiver `CRM_GEOAPIFY_CHAVE_MOSAICOS`, apagar a linha (a `CRM_GEOAPIFY_CHAVE_SERVIDOR` fica: morada sugerida do GPS); reiniciar o backend; aprovar a redação da privacidade.
6. **Prova de fumo em produção (G24), feita por ti, antes de anunciar:** em `lisbonb.com`, no telemóvel e no computador: abrir o Mapa; tocar num negócio (balão da Google + "Negócio selecionado"); "Adicionar como loja" (pino solto, Confirmar desligado, arrastar liga-o); pesquisar uma morada (pino + morada preenchida); "Estou nesta loja"; ver o logótipo da Google visível no fundo do mapa com o cartão aberto. Uma semana depois, ver o uso na consola e ajustar os tetos.

### 3.2 Como as chaves circulam no portal
- A **chave do navegador** é pública por natureza (qualquer membro a vê nas ferramentas do browser), como era a dos mosaicos da Geoapify: o que a protege é a restrição por referrer + por API + as quotas. Vai ao browser **só** por `GET /api/crm/config` (membros do escritório), com o Map ID.
- **Não há chave Google no servidor** (não há proxy nem tarefas agendadas).
- A regra "nunca endurecer a `Referrer-Policy`" **mantém-se**: a restrição por referrer depende do Referer.
- A `GOOGLE_PLACES_API_KEY` do portal (Marketing) **não se reutiliza**.

### 3.3 Custos e quotas (lista de preços de março de 2025, em vigor; confirmar na consola no dia)

| O quê (SKU) | Quando conta | Grátis/mês | Uso previsto (2–5 pessoas) | Teto diário a pôr |
|---|---|---|---|---|
| Dynamic Maps (Maps JavaScript API) | cada abertura de um ecrã com mapa: Mapa, Nova loja, Corrigir localização, Fábrica e, com a F3b, cada abertura do planeador | 10 000 | ≈ 1 500 | 300 |
| Place Details Essentials (Places API (New)) | cada "Adicionar como loja"/"Pôr o pino neste negócio" (só `location`) e cada morada escolhida na pesquisa (`location`, `formattedAddress`, `addressComponents`). **Tocar num negócio não conta** (o balão é da Google) | 10 000 | ≈ 200 | 200 |
| Autocomplete (Places API (New), por sessão) | cada pesquisa de morada: o elemento gere a sessão; a sessão que acaba numa escolha é cobrada pelo Place Details acima, uma sessão abandonada conta por pedido | 10 000 | ≈ 150 | 100 |
| Map ID | — | sem custo próprio | — | — |
| Geoapify (morada sugerida, servidor) | cada "Estou nesta loja" | 3 000 créditos/dia | dezenas/dia | já existe |
| openrouteservice | F3 | 500 + 2 000/dia | — | já existe |

**Custo esperado: 0 €.** Em linguagem simples:
- **O que conta como "um carregamento":** cada vez que um ecrã com mapa abre. 300 por dia são ≈ 60 aberturas por pessoa para 5 pessoas; 320/dia é o máximo que mantém o mês grátis (10 000 ÷ 31). Os 300 estão certos.
- **Se um teto se esgotar,** o mapa deixa de abrir nesse dia ("Não foi possível carregar o mapa — recarregue a página"); o resto do CRM funciona. As quotas diárias da Google renovam-se à meia-noite do Pacífico, **por volta das 8 h da manhã em Lisboa** — um dia esgotado deixa o mapa parado a tarde e a noite. Subir o teto na consola é imediato. O orçamento de 1 € é o travão real contra cobranças.

---

## 4. Riscos e pontos a confirmar

| Risco / dúvida | O que se faz |
|---|---|
| Quota diária esgotada → mapa não abre nesse dia | Tetos folgados (≈ 3× o uso previsto); mensagem clara; o resto do CRM funciona; o mapa volta ≈ 08:00 de Lisboa; subir o teto é imediato |
| Existência da quota diária editável para os carregamentos do Maps JS e para os métodos da Places (New) | Confirmar na consola (§3.1, falta 2); se não existir, orçamento + quota por minuto |
| App instalada (Capacitor) sem Referer `lisbonb.com` → `RefererNotAllowedMapError` | Decisão (a)/(b) do §3.1, falta 3; a G21 e a G24 distinguem "browser em lisbonb.com" de "app instalada" |
| `rh.lisbonb.com` sem referrer na chave → o mapa não abre lá | Decisão do dono (§5); recomendado acrescentar |
| Negócios sem ícone no mapa (não são clicáveis) | Encontram-se pela pesquisa; o toque à mão continua a existir |
| A pessoa não quer arrastar o pino | É o único gesto que torna a coordenada nossa; a dica explica-o; em "Corrigir localização" o pino guardado já é nosso e confirma-se sem arrastar |
| A Google muda a API (deprecações) | Só peças GA: `AdvancedMarkerElement` (o `google.maps.Marker` antigo não se usa), `importLibrary`, `Place.fetchFields`, `PlaceAutocompleteElement`; canal `weekly`; confirmar na G9 que o `gmp-select` continua a trazer `placePrediction` |
| Mapa vetorial vs. raster | Raster (por omissão, sem WebGL, nomes sempre visíveis); o Bruce pode mudar o Map ID para vetorial na consola sem mexer no código; `collisionBehavior: REQUIRED` garante os nomes nos dois casos |
| Sem mapa em local sem chave (antes havia OSM) | Demo Key do dono em `backend/.env.local`; os testes Jest usam um Google falso; sem Demo Key a G21 verifica só o que não precisa da Google e regista o resto como "não verificado em local" |
| A Demo Key não responder à Places (New) | Os passos da pesquisa e do "Adicionar como loja" ficam para a prova de fumo em produção do dono (G24) |
| O elemento de pesquisa da Google no React 19 | Cria-se por `new PlaceAutocompleteElement(opções)` em `lib/crm/lugarGoogle.js` e junta-se a um contentor por `ref`; as opções vão no construtor, os eventos por `addEventListener` |
| O balão da Google tapa parte do mapa pequeno do seletor | É o comportamento normal da Google; fecha-se no × do balão ou tocando noutro sítio |
| Uma CSP futura no portal (hoje não há) | Teria de permitir `maps.googleapis.com`, `maps.gstatic.com`, `*.googleapis.com`, `*.ggpht.com`, `*.gstatic.com`; o carregador copia o `nonce` de um `<script>` existente |
| A morada da Google (pesquisa) com número de porta ou grafia diferente do que a pessoa esperava | A pessoa revê antes de guardar (§0, ponto 4); os campos ficam editáveis |

---

## 5. Decisões a fechar pelo dono
1. **Referrers da chave:** acrescentar `https://rh.lisbonb.com/*` (recomendado) e a app instalada, opção (a) "mapa só no browser" (por omissão) ou (b) referrers da app (§3.1, falta 3).
2. **Tetos diários** (§3.1, falta 2) com os valores do §3.3, ou outros.
3. **Map ID raster (por omissão) ou vetorial.**
4. **Redação** da política de privacidade (secções 4 e 8).
5. **Prova de fumo em produção** (§3.1, falta 6) antes de anunciar à equipa.

As decisões "30 dias (opção A/B)" e "ver o banner do UI Kit no dia" da v1 **deixaram de existir** (§2.3 e §6.8).

---

## 6. Anexo técnico

### 6.1 Arquitetura no frontend
- **Carregamento:** `lib/crm/carregadorGoogle.js` (porta legível do *inline bootstrap loader* oficial, sem dependência npm): `prepararGoogleMaps({janela, documento, chave, versao: 'weekly', idioma: 'pt-PT', regiao: 'PT'})` → `{importar(nome)}`. Mete **um** `<script src="https://maps.googleapis.com/maps/api/js?key=…&v=weekly&language=pt-PT&region=PT&libraries=…&callback=google.maps.__ib__">` por página (copia o `nonce` se houver; `loading=async` é permitido, não exigido) e depois delega em `google.maps.importLibrary`. Só corre nas páginas do CRM (já carregadas com `React.lazy`): a Google **não entra** no ficheiro principal do portal. A chave e o Map ID chegam por `GET /api/crm/config`.
- **Mapa (`lib/crm/mapa.js`, com Jest):** `criarMapa({google, documento, elemento, configuracao, negociosClicaveis = true, aoEscolherLoja?, aoTocarNoMapa?, aoTocarNumLugar?})` → `{mapa, mostrarLojas, enquadrar, redimensionar, centrarEm, focar, destruir}`. `new google.maps.Map(elemento, {mapId, center, zoom, minZoom: 6, maxZoom: 19, clickableIcons: negociosClicaveis, disableDefaultUI: true, zoomControl: true, gestureHandling: 'greedy', mapTypeId: 'roadmap'})`; o elemento recebe `tabIndex = -1` (para `focar()`).
  - **Pinos:** `new google.maps.marker.AdvancedMarkerElement({map, position, content, title: 'Nome (Fase)', gmpClickable: true, collisionBehavior: REQUIRED})`. O `content` é um nó DOM montado com o `el()` de `dom.js` (`div.pino.pino--<fase>` com `span.pino__bola` e `span.etiqueta-loja` com o nome em `textContent`): nunca HTML de dados. **Sem agrupamento.** Tocar (ou Enter/Espaço) → `gmp-click` → `aoEscolherLoja(loja, marcador)`.
  - **Toque no mapa:** `mapa.addListener('click', e)`: com `e.placeId` → **não se chama `e.stop()`** (o balão da Google abre, como em qualquer site) e `aoTocarNumLugar({placeId, lat, lng})` (lat/lng do toque, só como `reserva`); sem `placeId` → `aoTocarNoMapa({lat, lng})`. Com `negociosClicaveis: false` (planeador) a Google não emite `placeId` e tudo é toque no mapa.
  - `enquadrar`: `LatLngBounds` + `fitBounds` com margem, e `limitarZoomDepoisDeEnquadrar` (um `idle` único que limita o zoom a 16; o ouvinte guarda-se e remove-se na chamada seguinte e no `destruir`, para não disparar num `idle` tardio); `centrarEm(loja, zoom?)`; `focar()`; `destruir`: tira os marcadores (`map = null`), remove ouvintes, `clearInstanceListeners`, esvazia o elemento (o `StrictMode` monta duas vezes).
  - **F3b:** `mostrarRota` acrescenta pinos numerados (o mesmo `AdvancedMarkerElement`, `content` com o número via `el()`) e a linha `new google.maps.Polyline({path, strokeColor: '#6b2fa3', strokeWeight: 4, clickable: false})`. A geometria vem do openrouteservice (`polilinha.js`), nunca da Google.
- **Lugares (`lib/crm/lugarGoogle.js`, com Jest) — o único ficheiro que nomeia `Place`, `fetchFields`, `formattedAddress`, `addressComponents`:**
  - `CAMPOS_POSICAO = ['location']`, `CAMPOS_MORADA_GOOGLE = ['location', 'formattedAddress', 'addressComponents']`, `CAMPOS_PERMITIDOS = ['id', 'location', 'formattedAddress', 'addressComponents']`;
  - `pontoDoLugar(place)` → `{id, lat, lng}` ou `null`; `moradaDoLugar(place)` → `{rotulo, morada, codigo_postal, localidade}` (a mesma forma da sugestão Geoapify: `rotulo` = `formattedAddress`; `morada` = `route` + `street_number`, `null` sem rua; `codigo_postal` só no formato 0000-000; `localidade` = `locality` → `postal_town` → `administrative_area_level_3` → `administrative_area_level_2`); os dois leem **só** essas chaves e devolvem objetos com as chaves exatas (canário com dez chaves a mais);
  - `posicaoDoLugar(google, placeId)` (async): `new google.maps.places.Place({id})` + `fetchFields({fields: CAMPOS_POSICAO})` → `pontoDoLugar`; `lugarDaPesquisa(google, previsao)` (async): `previsao.toPlace()` + `fetchFields({fields: CAMPOS_MORADA_GOOGLE})` → `{id, lat, lng, morada}`;
  - `criarPesquisaLugar({google, documento, aoEscolher, aoFalhar, obterLimites})` → `{elemento, destruir}`: `new google.maps.places.PlaceAutocompleteElement({includedRegionCodes: ['pt']})`, `locationBias` = `obterLimites()` ao focar, `gmp-select` → `lugarDaPesquisa` → `aoEscolher({id, lat, lng, morada})`; falhas → `aoFalhar()`;
  - `criarNegocioSelecionado({aoMudarVista})` → o controlador puro do painel: `vista` `{placeId, reserva, estado: 'fechado' | 'aberto' | 'a_posicionar' | 'erro', mensagem}`, `abrir(placeId, {reserva})`, `aPosicionar()`, `falhou()`, `fechar()`, `destruir()`;
  - textos: `TEXTO_NEGOCIO_SELECIONADO`, `TEXTO_ADICIONAR_COMO_LOJA`, `TEXTO_USAR_ESTE_NEGOCIO`, `TEXTO_FECHAR_NEGOCIO`, `TEXTO_A_POSICIONAR`, `TEXTO_LUGAR_INDISPONIVEL`, `TEXTO_ESCREVA_O_NOME`, `TEXTO_PESQUISAR_LUGAR`, `ROTULO_NEGOCIO` (valores exatos no plano, G9).
- **Seletor (`lib/crm/seletor.js`, com Jest):** o mesmo controlador (`criarSeletor` → estados `vazio` → `por_confirmar` → `confirmado`), sobre o `criarMapa`. O pino é um `AdvancedMarkerElement` com `gmpDraggable: true` (a gota do CSS como `content`) e `dragend`; o círculo da precisão é um `google.maps.Circle` (`clickable: false`). **Novo:** `escolherNegocio(placeId, {reserva})` (toque num POI do mapa pequeno → painel), `usarNegocio(placeId?, {reserva?})` (→ `posicaoDoLugar` → `colocar({lat, lng, origem: 'google', google_place_id}, {zoom: 18})`; se falhar com `reserva`, o pino vai para o ponto do toque, com a mesma origem e id), `fecharNegocio()`, a pesquisa (`criarPesquisaLugar`; `vista.pesquisa = {ativa, elemento}`; escolher → `colocar({…, origem: 'google', google_place_id})` + "Morada sugerida: <rotulo>" + `aoEscolherMorada(morada)`), `limitesDoMapa()`. **Regra do arrasto:** `podeConfirmar({origem: 'google', arrastado: false}) === false`, dica `TEXTO_ARRASTAR_LUGAR = 'Arraste o pino até à porta da loja para confirmar'`, `aviso: 'arrastar'`; depois de `dragend`, `origemFinal` dá `pin_manual` e o `google_place_id` fica. Tocar no mapa à mão limpa o `google_place_id` e fecha o painel. `localizacaoFinal` → `{lat, lng, origem_coords, precisao_m, google_place_id}` e nunca `origem_coords: 'google'`. A morada inversa da Geoapify pede-se **só** no GPS.
- **Componentes:** `NegocioSelecionado` (`{estado, mensagem, acao: {texto, aoTocar}, aoFechar, refTitulo}`: `<section class="crm-negocio" role="region" aria-label="Negócio selecionado">` com o texto fixo `TEXTO_NEGOCIO_SELECIONADO` ("Negócio selecionado no mapa."), o botão da `acao` ("Adicionar como loja" no mapa; "Pôr o pino neste negócio" no seletor), o botão "Fechar" e a dica `TEXTO_ESCREVA_O_NOME` por baixo da ação; **nenhum dado da Google**), `PesquisaLugar` (um rótulo visível + o contentor onde entra o `elemento` do `criarPesquisaLugar`), `Partes` (texto + ligação, hoje em `PesquisaMorada.js`, passa para `components/crm/Partes.js`). `MapaLojas` recebe `aoTocarNumLugar` e `negociosClicaveis`; `SeletorLocalizacao` ganha `aoPronto(seletor | null)` e expõe pela `ref` `escolherNegocio`, `usarNegocio`, `fecharNegocio`, `limitesDoMapa`.
- **Páginas:** `CrmMapa` recebe `aoTocarNumLugar` → `negocio.abrir(id, {reserva})` e mostra o `NegocioSelecionado` no lugar do cartão da loja (os dois exclusivos); "Adicionar como loja" navega para `lojas/nova` com `state: {negocio: {id, lat, lng}}` (**sem pedir nada à Google** no mapa principal). Ao fechar o cartão/painel, o foco volta ao pino (`marcador.element`) ou ao mapa (`mapa.focar()`). `CrmLojaNova` lê o `state`, chama `usarNegocio(id, {reserva})` quando o seletor está pronto (uma só vez), e mostra sob o campo "Nome" a dica `TEXTO_ESCREVA_O_NOME`. `CrmLoja` ("Corrigir localização", com `inicial` a levar o `google_place_id`) e `DefinicoesFabrica` usam o seletor novo (a fábrica ignora o *place ID*).
- **CSS (`crm.css`):** saem as regras `.leaflet-*`; `.pino` passa a um bloco de 44 × 44 px com `transform: translateY(50%)` (o marcador avançado ancora o fundo-centro do conteúdo no ponto) e a etiqueta absoluta à direita com `pointer-events: none`; a gota `.pino-seletor` com a ponta no fundo ao centro; `.crm-negocio` (sem `position: absolute`). **Regra de disposição no `css.test.js`:** nenhum seletor é descendente de `.crm-mapa`; nenhuma regra com `position: absolute` cujo seletor contenha `crm-mapa` ou `crm-seletor__vista` (exceto o próprio `.crm-mapa`) tem `bottom` nem `inset`; `.crm-mapa__barra` tem `top` e `pointer-events: none`; nenhum seletor `.gm-`/`gmp-`.
- **Segurança (`seguranca.test.js`):** `google.maps`/`importLibrary` só em `lib/crm/{carregadorGoogle,mapa,seletor,lugarGoogle}.js`; `content:` só em `mapa.js`/`seletor.js`; `fetchFields`, `formattedAddress`, `addressComponents`, `toPlace(`, `places.Place`, `PlaceAutocompleteElement` **só** em `lugarGoogle.js`, e nesse ficheiro todo o `fetchFields(` tem a forma `fetchFields({ fields: CAMPOS_POSICAO | CAMPOS_MORADA_GOOGLE })` e todas as listas `CAMPOS_*`/`fields:` ⊆ `{id, location, formattedAddress, addressComponents}`; recusados em todo o lado: `InfoWindow`, `setContent(`, `PlacesService`, `Geocoder(`, `places.Autocomplete`, `AutocompleteSuggestion`, e os **canários de dados de negócio** `displayName` (acesso a propriedade ou texto; a atribuição `X.displayName = '…'` do React passa), `nationalPhoneNumber`, `internationalPhoneNumber`, `websiteUri`, `shortFormattedAddress`, `regularOpeningHours`, `currentOpeningHours`, `businessStatus`, `rating`, `reviews`, `photos`, `editorialSummary`, `priceLevel`, `googleMapsURI`. Canários em tempo de execução (Jest): o `googleFalso` regista os campos pedidos (`registo.camposPedidos` ⊆ permitidos em todos os fluxos); um lugar falso com sentinelas (`'CANÁRIO-NOME'`, `'CANÁRIO-TELEFONE'`, `'CANÁRIO-SITE'`) em chaves a mais nunca aparece em nenhuma `vista` nem em nenhum corpo enviado à API falsa.

### 6.2 Backend e dados
- **`GET /api/crm/config`** (escritório) → `{google: {chave, map_id} | null, centro: {lat, lng}}`. Lê `CRM_GOOGLE_CHAVE_NAVEGADOR` e `CRM_GOOGLE_MAP_ID` a cada pedido; `null` se faltar uma das duas; nunca nos registos. Sai `CRM_GEOAPIFY_CHAVE_MOSAICOS`.
- **`crm_lojas`:** novo campo **`google_place_id`** (texto ASCII imprimível sem espaços nem `<>"'&`, 1–255 caracteres, ou `null`; a Google não documenta o formato dos *place IDs*, por isso não se restringe mais; documentos antigos sem a chave leem-se como `null`). Vai no **bloco da localização** (`lat`, `lng`, `origem_coords`, `precisao_m`, `google_place_id`) no POST e no PATCH; sai no GET da loja (não na lista). **`ORIGENS` não muda** (`pin_manual`, `gps`, `geocoder`): `origem_coords: "google"` é recusada com 422. Sem índice (gancho para "esta loja já existe com este negócio").
- **Morada:** fica **só** `GET /api/crm/morada/inversa` (Geoapify, chave do servidor, para o GPS); `GET /api/crm/morada/pesquisa` e `geoapify.url_pesquisa` saem. A normalização e o cliente ficam como estão.
- **`.env.example`:** o bloco do CRM passa a nomear `CRM_GOOGLE_CHAVE_NAVEGADOR`, `CRM_GOOGLE_MAP_ID`, `CRM_GEOAPIFY_CHAVE_SERVIDOR`, `CRM_GEOAPIFY_URL` (só nomes).

### 6.3 Fluxos
1. **Negócio → loja (mapa):** toque no ícone → `click` com `placeId` (sem `stop()`: o balão da Google abre) → `aoTocarNumLugar({placeId, lat, lng})` → painel "Negócio selecionado" → "Adicionar como loja" → `lojas/nova` com `state.negocio` → `usarNegocio(id, {reserva})` → `Place.fetchFields(['location'])` → pino solto em `location` (ou na `reserva` se falhar), origem passageira `google`, dica "Arraste o pino até à porta…", Confirmar desligado → arrastar → Confirmar → escrever o nome e a morada → Guardar (`origem_coords: 'pin_manual'`, `google_place_id`).
2. **Pesquisa de morada:** `PlaceAutocompleteElement` → `gmp-select` → `placePrediction.toPlace()` → `fetchFields(['location', 'formattedAddress', 'addressComponents'])` → pino solto + "Morada sugerida: <formattedAddress>" + campos preenchidos (`aoEscolherMorada`) → arrastar → Confirmar → Guardar (`pin_manual`, `google_place_id`).
3. **GPS:** igual a hoje (Geoapify inversa; "Powered by Geoapify").
4. **Pino à mão:** igual a hoje (sem `google_place_id`; confirma sem arrastar).
5. **Rota (F3b):** ORS → `calculo.geometria` → `descodificarPolilinha` → `Polyline` sobre o mapa; "Routing provided by openrouteservice" + atribuição ORS no painel.
6. **Falhas:** sem chave → "Mapa não configurado — peça ao administrador para configurar a chave Google."; a Google não carrega / quota / referrer → "Não foi possível carregar o mapa — recarregue a página." (sem mapa não há pino, pesquisa nem GPS, como hoje); `fetchFields` falha → "Não foi possível obter a posição deste lugar — toque no mapa no sítio da loja." (com `reserva`, o pino é posto na mesma no ponto do toque).

### 6.4 Geoapify: o que fica
Fica **só a geocodificação inversa** para o GPS ("Morada sugerida: … · Powered by Geoapify"): os dados OSM podem ser guardados. Saem: os mosaicos, a chave dos mosaicos, a pesquisa (autocomplete), o controlo de alternativa (`mosaicos.js`) e as atribuições do mapa. Para os pinos vindos da Google não se pede a inversa (a morada vem da Google na pesquisa; num negócio escreve-se à mão).

### 6.5 Testes
- **Jest (módulos puros):** `testes/googleFalso.js` substitui o `leafletFalso.js` (Map com `getDiv` e a contagem dos balões da Google, AdvancedMarkerElement com `element` e `arrastarPara`, Circle, Polyline, LatLngBounds, CollisionBehavior, `event`, `importLibrary`, `InfoWindow` que conta as criações — tem de ficar a 0 —, `places.Place` com `fetchFields` que regista os campos pedidos e só copia esses, `places.PlaceAutocompleteElement` com `escolher(id)` que dispara `gmp-select`, `eventoDeToque` com `stop()`); `carregadorGoogle.test.js`; `mapa.test.js`, `seletor.test.js`, `lugarGoogle.test.js`, `localizacao.test.js`, `diferencas.test.js`, `ecraMapa.test.js`, `lojaNova.test.js`, `ficha.test.js`, `fabrica.test.js`, `css.test.js`, `seguranca.test.js`, `privacidade.test.js`, `atribuicoes.test.js` (reescrito) adaptados. Os testes sobre o "Leaflet verdadeiro no jsdom" desaparecem (o Google não corre no jsdom).
- **Backend:** `test_config_mapa.py` reescrito; `google_place_id` nos testes do domínio, do formatador e das rotas das lojas (e `"google"` recusada); `test_morada.py`/`test_geoapify.py`/`test_protecao_rotas.py` sem a pesquisa; `test_variaveis_ambiente.py` com as variáveis novas (as do ORS ficam).
- **No browser (local, G21):** Playwright sem janela com a **Demo Key** do dono em `backend/.env.local`, contra a Google verdadeira (poucos carregamentos). Sem Demo Key, ou se ela não responder à Places (New), os passos que dependem da Google registam-se como "não verificado em local" e passam para a prova de fumo em produção do dono (G24). Não há um "Google falso de browser" a manter. Nada sai do Mac.

### 6.6 Como a F3b assenta no mapa novo
As tarefas T3.26–T3.43 do plano da F3 fazem-se **depois** deste plano, sobre o `MapaLojas` novo: pinos numerados com `AdvancedMarkerElement` e `el()`, linha com `google.maps.Polyline`, extremos iguais; o `googleFalso` já tem `Polyline`; o planeador cria o mapa com `negociosClicaveis: false`; **o painel do planeador, a pega (`.crm-pega`) e o rodapé do ORS vivem fora da caixa do mapa** (abaixo de 1024 px o mapa tem altura fixa e o painel fica por baixo; a partir de 1024 px, ao lado), nunca sobre o fundo do mapa; o planeador mostra "Routing provided by openrouteservice" antes da linha e a atribuição do ORS num bloco próprio do painel. Arrastar paragens, sugestões, calcular e guardar **não mudam**. A lista exata das substituições está no §7 do plano.

### 6.7 Ficheiros (resumo)
- **Novos:** `frontend/src/lib/crm/{carregadorGoogle,lugarGoogle}.js` (+ testes), `frontend/src/lib/crm/testes/googleFalso.js`, `frontend/src/components/crm/{NegocioSelecionado,PesquisaLugar,Partes}.js`.
- **Alterados:** `lib/crm/{mapa,seletor,localizacao,diferencas,morada,atribuicoes,api,lojaNova,ficha,ecraMapa,gps}.js` (+ testes, mais `fabrica.test.js`), `seguranca.test.js`, `css.test.js`, `privacidade.test.js`, `atribuicoes.test.js`, `components/crm/{MapaLojas,SeletorLocalizacao}.js`, `crm.css`, `pages/crm/{CrmMapa,CrmLojaNova,CrmLoja,DefinicoesFabrica,rotasCrm}.js`; `backend/crm/{config_mapa,morada,formatar}.py`, `backend/crm/dominio/{campos_loja,validador_loja}.py`, `backend/crm/servicos/geoapify.py` e os testes; partilhados: `pages/PrivacyPolicy.js`, `backend/.env.example`, `frontend/package.json` + `yarn.lock` (sai o Leaflet).
- **Apagados:** `lib/crm/{mosaicos,pesquisaMorada}.js` (+ testes), `lib/crm/testes/leafletFalso.js`, `components/crm/PesquisaMorada.js`.

### 6.8 O que mudou da v1 (2026-10-14) para a v2 (2026-10-18)

| v1 | v2 | Porquê |
|---|---|---|
| Places UI Kit (`gmp-place-details-compact`, `gmp-basic-place-autocomplete`) | Sem UI Kit: balão da própria Google (sem `stop()`), `Place.fetchFields` restrito, `PlaceAutocompleteElement` | O UI Kit está "Experimental (pre-GA)"; a regra do desenho e os Termos EEA §6.5 não deixam publicar pré-GA |
| Ficha do negócio ao lado do mapa, com nome, morada e foto | Painel "Negócio selecionado" só com o texto fixo, a ação, "Fechar" e a dica do nome | Não renderizamos dados de negócio da Google; o balão da Google já os mostra |
| Confirmar sem arrastar gravava `origem_coords: google`; opção A/B dos 30 dias | Confirmar só depois de arrastar; `google` só como estado do seletor; `ORIGENS` do servidor inalterado | Nenhuma coordenada da Google fica guardada; §15.4 deixa de se aplicar |
| Morada sempre pela Geoapify inversa (também para lugares Google) | Google na pesquisa de moradas (`formattedAddress`/`addressComponents`); Geoapify só no GPS; à mão nos negócios | "Address autocompletion" é uso permitido; a morada vive na ficha; a Geoapify deixa de receber coordenadas da Google |
| Consola: criar projeto, ativar Maps JS + UI Kit, não ativar Places (New) | Consola já feita (Maps JS + Places (New), chave restrita, Map ID, variáveis); falta: Termos EEA se pedido, tetos, referrers, prova de fumo | Estado real a 2026-10-18 |
| `maps-teste.js` (Google falso de browser) para o Playwright | Só a Demo Key; o que ela não cobrir vai para a prova de fumo em produção | Menos código a manter |
| Guarda da atribuição só por CSS (`.gm-*`, `gmp-*`) | Regra de disposição: nada nosso dentro ou sobre o fundo do mapa; `css.test.js` + Playwright a 375 × 812 e 1280 × 800; a mesma regra na F3b (T3.36/T3.38) | A F3b põe painel, pega e rodapé do ORS à volta do mapa |
| `rh.lisbonb.com` por decidir; app instalada não considerada | As duas em §3.1 (falta 3) e §5 | O Capacitor nunca envia o Referer `lisbonb.com` |
| Quotas: "0 € até ao dia seguinte" | O que conta como carregamento e a renovação ≈ 08:00 de Lisboa | Para o dono saber o que esperar |
| Privacidade: "inclui funcionalidades… sujeitas aos…" | "Ao usar o mapa do CRM, o membro fica sujeito aos Termos adicionais do Google Maps/Google Earth e à Política de Privacidade da Google" + Google Ireland Limited | Termos EEA §3.2.2 |

> Estado: v2 de 2026-10-18, escrita a partir da v1, da revisão por 2 críticos só de leitura (`Correções obrigatórias` do plano) e das decisões do orquestrador do mesmo dia. Abordagem aprovada pelo Bruce em conversa a 2026-10-18 (balão da Google + arrastar para confirmar): a execução segue sem mais revisão prévia; as decisões do §5 fecham-se pelo dono ao longo do plano (G1, G23, G24).
