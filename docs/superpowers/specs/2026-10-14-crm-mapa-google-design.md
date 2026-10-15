# Adenda ao desenho do CRM Purple House — o mapa passa a Google

- **Data:** 2026-10-14 · **Ficheiro:** `docs/superpowers/specs/2026-10-14-crm-mapa-google-design.md`
- **Autor:** Bruce Silva (com Claude Code)
- **Estado:** decisão do dono (2026-10-14: "o mapa passa a Google"); adenda por rever por escrito pelo Bruce. Plano de execução: `docs/superpowers/plans/2026-10-14-crm-mapa-google.md`.
- **Base:** [desenho no portal](2026-10-09-crm-purple-house-no-portal-design.md) e [desenho original](2026-10-02-crm-purple-house-desenho-original.md). Esta adenda **substitui**: no original, a linha "Porque não a Google Places/Routes" do §9 (reavaliada hoje com os Termos EEA em vigor) e a parte dos mapas do §6.2 e §6.8; no desenho do portal, a linha "Leaflet 1.9.4" do §2 e §4.2 e as chaves do §4.4. **Tudo o resto fica**: fases, GPS só ao tocar, nomes sempre visíveis sem agrupamento, openrouteservice para as rotas, Geoapify para a morada sugerida.
- **Pesquisa verificada (2026-10-14):** Termos EEA do Google Maps Platform (`cloud.google.com/terms/maps-platform/eea`, Termos Específicos EEA §6, §15, §16, §A.2–A.4), lista de usos permitidos da Places API para faturação EEA, documentação do Maps JavaScript API (loader, Advanced Markers, Map ID, evento `click` com `placeId`), Places UI Kit (Place Details Compact, Basic Place Autocomplete), preços e quotas (lista de 2026-10-08).

---

## 0. Em três frases, para o Bruce

1. **Sim, pode-se usar o mapa da Google** — com os negócios à vista, pesquisa Google, e "tocar num negócio → ficha → Adicionar como loja" — e fica a **0 €** dentro das quotas gratuitas mensais (10 000 aberturas do mapa, 10 000 fichas de lugares, 10 000 pesquisas).
2. A análise de 2026-10-02 continua certa (**não se guardam nomes, moradas nem telefones da Google**; só o identificador do lugar, o *place ID*, e o pino que nós confirmamos). O que mudou é que a Google tem agora o **Places UI Kit**, um conjunto de "cartões" prontos que **estão isentos** da regra "nada da Google ao lado de um mapa" (Termos Específicos EEA §15.3). É por aí que o CRM mostra a ficha de um negócio.
3. O que é teu continua a ser escrito por ti: **o nome e o telefone da loja escrevem-se à mão** (o cartão da Google fica ao lado para se ler), a morada é sugerida pela Geoapify (dados abertos, que podemos guardar) e a região continua a escolher-se à mão.

---

## 1. O que muda para quem usa

### 1.1 Mapa (ecrã principal)
- O fundo passa a ser o **Google Maps**, com as ruas, os nomes e os **negócios (POI) com ícone**, como na app Google Maps. Os pinos das nossas lojas ficam por cima, com a **cor da fase e o nome sempre à vista**, em qualquer zoom, sem agrupamento (como hoje).
- **Tocar num negócio da Google** (o ícone dele no mapa) abre, no mesmo sítio onde hoje abre o cartão da loja, a **ficha Google do lugar** (nome, morada, aberto/fechado, foto, com a atribuição da Google embutida) e o botão **"Adicionar como loja"**. O balão por omissão da Google nunca aparece.
- **"Adicionar como loja"** leva ao ecrã "Nova loja" com o pino já posto no lugar (solto, para arrastar até à porta) e a ficha Google visível ao lado, para se ler o nome. **O campo "Nome" fica vazio, para a pessoa o escrever**; nada se copia da Google. A morada, o código postal e a localidade são sugeridos pela Geoapify a partir do pino (como hoje no "Estou nesta loja") e preenchem só os campos vazios.
- Tocar num pino nosso abre o cartão da loja, como hoje. Filtros, "N lojas", "Nova loja", `?loja=<id>` e o aviso "Loja guardada" não mudam.
- Os botões de zoom passam a ser os da Google (em português, porque o mapa carrega com `language=pt-PT`). A atribuição "Google" e "Dados do mapa ©" e a ligação aos termos ficam no canto, postas pela Google, e **nunca se escondem**.

### 1.2 Adicionar loja / corrigir localização (seletor)
- O campo "Pesquisar morada" (Geoapify) dá lugar a **"Pesquisar lugar ou morada"**, da Google (negócios **e** moradas, só em Portugal, com preferência pela zona que o mapa mostra). Escolher uma sugestão: abre a ficha do lugar por baixo do campo, **põe o pino nesse sítio** (solto, zoom de rua), sugere a morada pela Geoapify e pede para arrastar e **confirmar**.
- **Tocar num negócio no mapa pequeno do seletor** faz o mesmo que escolher na pesquisa.
- **"Estou nesta loja" não muda:** GPS só ao tocar, uma leitura, círculo da precisão, "Localização imprecisa — ajuste o pino" acima de 50 m, morada sugerida pela Geoapify.
- Tocar no mapa (fora dos negócios) continua a pôr o pino à mão; arrastar e confirmar, como hoje.
- Na ficha da loja, "Corrigir localização" usa o mesmo seletor. Nas Definições, o ponto da fábrica também (sem GPS; aí a pesquisa serve só para pôr o pino).

### 1.3 Rotas (F3, por fazer)
- O planeador desenha a **linha da rota (openrouteservice) sobre o mapa Google**, com os pinos numerados. Antes da linha aparece a frase obrigatória **"Routing provided by openrouteservice"** e, no rodapé do painel, a atribuição "Developed by VROOM · Hosted by HeiGIT · Routing by openrouteservice · Data from OpenStreetMap", **separadas** da atribuição da Google (que fica no canto do mapa, intacta).
- A ordem (VROOM) e as horas (Directions) continuam no openrouteservice; a Google não calcula rotas no CRM (evita-se a Routes API e as suas restrições EEA).

### 1.4 O que não muda
Fases e cores; nomes sempre visíveis sem agrupamento; GPS só ao tocar e nunca seguimento; duplicados a 50 m; nome e telefone escritos pela pessoa; a região escolhida à mão; o openrouteservice nas rotas; as regras de quem vê o CRM.

---

## 2. As regras da Google que seguimos (faturação em Portugal = Termos EEA)

### 2.1 O que guardamos, o que nunca guardamos, o que só se mostra

| | O quê | Porquê é permitido |
|---|---|---|
| **Guardamos** | O **pino confirmado** pela pessoa (lat/lng), com a origem (`pin_manual`, `gps`, `geocoder`, ou **`google`** quando o pino veio de um lugar Google e não foi arrastado) | É a localização do nosso cliente, confirmada por nós; lat/lng são a exceção expressa do §15.1 |
| **Guardamos** | O **`google_place_id`** do lugar escolhido (sem prazo) | Termos Específicos EEA §A.3: o `place_id` pode ficar em cache indefinidamente |
| **Guardamos** | **Nome, telefone, pessoa de contacto, notas** escritos pela pessoa; **morada, código postal e localidade** sugeridos pela **Geoapify** (dados OpenStreetMap, que podem ser guardados) e revistos pela pessoa | Não vêm da Google |
| **Nunca guardamos** | Nome do negócio, morada, telefone, site, horário, fotos, avaliações vindos da Google — nem por "copiar" automático, nem por botão "copiar" | Termos EEA §3.3.2(a) "No Scraping… copy and save business names, addresses" e §15.1 |
| **Nunca fazemos** | Atribuir região por "ponto dentro de polígono" com coordenadas da Google | §3.3.2(c)(iv) |
| **Só se mostra, pelo Places UI Kit** | A ficha do lugar (nome, morada, aberto/fechado, foto) e a lista de sugestões da pesquisa | §15.3: o UI Kit está isento das restrições "With any Map"; §16.1: a atribuição embutida não se altera nem esconde |
| **Só lat/lng e `place_id`** | É tudo o que o código lê da ficha do lugar (`place.id`, `place.location`) | §15.1: só isto pode ir "para o mapa" |

### 2.2 Obrigações na app
- **Página de privacidade (§6.8 do original, hoje a secção 8 de `/privacidade`):** passa a dizer que o CRM inclui funcionalidades e conteúdos do Google Maps, sujeitos aos [Termos adicionais do Google Maps](https://maps.google.com/help/terms_maps/) e à [Política de Privacidade da Google](https://policies.google.com/privacy) (Termos EEA §3.2.2); que nome e telefone nunca se copiam da Google; que a morada sugerida vem da Geoapify ("Powered by Geoapify"). Sai a frase do Leaflet e do OpenMapTiles. Redação a aprovar pelo Bruce (dossiê §14, ponto 7).
- **GPS:** consentimento expresso e revogável (§4.3.2) — já cumprido: só ao tocar em "Estou nesta loja".
- **Atribuições:** a da Google é posta pela própria API e **nunca se esconde com CSS** (há um teste que o garante); a Geoapify fica junto à morada sugerida; a do openrouteservice no planeador, separada da Google (§A.2), com "Routing provided by openrouteservice" (§A.4.3).
- **Pré-GA:** só se usam os elementos base do UI Kit (Place Details Compact e Basic Place Autocomplete), no canal `weekly`; os "Advanced…" (beta) ficam de fora (Termos EEA §6.5 limita ofertas pré-GA).

### 2.3 A questão dos 30 dias (risco residual, decisão do dono — ver §5)
O §15.4 diz que coordenadas **da Places API/UI Kit** só podem ficar em cache 30 dias. O que guardamos é o pino **confirmado pela pessoa** (a dica do ecrã pede para arrastar até à porta). Se a pessoa confirmar sem mexer, a coordenada coincide com a da Google. Registamos isso (`origem_coords: "google"`, `atualizado_em`) e deixamos duas opções:
- **A (recomendada):** tratar o pino confirmado como dado nosso — é a localização do nosso cliente, confirmada por quem a registou (uso permitido "manage Places content related to a sales team's customers");
- **B:** uma tarefa mensal que, para as lojas com `origem_coords: "google"` e mais de 30 dias, refresca `location` a partir do `place_id` por um proxy no servidor (Places API (New), campos `id,location`, 10 000/mês grátis, chave própria restrita por IP). **Não se constrói agora**; fica o gancho (os campos já existem).

---

## 3. Chaves, consola e custos

### 3.1 O que o Bruce cria na consola Google Cloud (só o dono; nada passa pelo chat nem pelo git)
1. **Projeto** novo (ex.: "Purple House CRM") com a **conta de faturação portuguesa** ligada. O projeto fica logo sob os Termos EEA.
2. Google Maps Platform → **Support** → **aceitar os Termos EEA** (só um Owner/Editor do projeto o pode fazer).
3. **Ativar APIs:** **Maps JavaScript API** e **Places UI Kit** (`placewidgets.googleapis.com`). **Não** ativar a Places API (New), a Geocoding API nem a Routes API (não são precisas; assim a chave nem as pode chamar).
4. **Chave de API "CRM navegador":** restrição de aplicação = **Websites** com `https://lisbonb.com/*` (o `www.lisbonb.com` redireciona para `lisbonb.com` no Caddyfile; o `rh.lisbonb.com` é sinónimo permanente — decidir no §5 se entra); restrição de API = **só** Maps JavaScript API + Places UI Kit.
5. **Map ID:** Map Management → novo, tipo **JavaScript**, **Raster**, sem estilo (os negócios ficam visíveis por omissão). Guardar o ID.
6. **Quotas (teto rígido) e orçamento:** Maps JavaScript API → quota "per day" (ex.: **300** carregamentos/dia ≈ 9 000/mês, abaixo dos 10 000 grátis); Places UI Kit → ex.: **200** fichas/dia e **100** sessões de pesquisa/dia; Faturação → **orçamento de 1 €** com alerta a 50/90/100 %. Se alguma API não tiver quota diária editável, fica o orçamento + a quota por minuto.
7. **No servidor** (`backend/.env`, pelo método seguro de sempre, sem aspas): `CRM_GOOGLE_CHAVE_NAVEGADOR=…` e `CRM_GOOGLE_MAP_ID=…`; **apagar** a linha `CRM_GEOAPIFY_CHAVE_MOSAICOS`. A `CRM_GEOAPIFY_CHAVE_SERVIDOR` fica (morada sugerida). Reiniciar o backend.
8. **Em local** (desenvolvimento), a **Maps Demo Key** da Google (`developers.google.com/maps/demo-key`, sem faturação, com limite diário) em `backend/.env.local` com `CRM_GOOGLE_MAP_ID=DEMO_MAP_ID`. Sem nenhuma chave, o CRM mostra "Mapa não configurado" e o resto funciona.
9. **No dia da publicação:** ver a página *overview* do Places UI Kit; se ainda disser "Experimental (pre-GA)", pedir confirmação ao suporte Google antes de publicar (as *release notes* e o blogue de 2025 dizem GA).

### 3.2 Como as chaves circulam no portal
- A **chave do navegador** é pública por natureza (qualquer membro a vê nas ferramentas do browser), como era a dos mosaicos da Geoapify: o que a protege é a restrição por referrer + por API + as quotas. Vai ao browser **só** por `GET /api/crm/config` (membros do escritório), com o Map ID.
- **Não há chave Google no servidor** nesta versão (não há proxy). Só se a opção B do §2.3 avançar.
- A regra "nunca endurecer a `Referrer-Policy`" **mantém-se**: a restrição da chave Google por referrer depende do Referer, como a da Geoapify.

### 3.3 Custos e quotas (lista de preços de 2026-10-08)

| O quê | Quando conta | Grátis/mês | Uso previsto (2–5 pessoas) | Teto diário a pôr |
|---|---|---|---|---|
| Dynamic Maps (Maps JavaScript API) | cada abertura de um ecrã com mapa (Mapa, Nova loja, Corrigir localização, Fábrica) | 10 000 | ≈ 1 500 | 300 |
| Places UI Kit — Query | cada ficha de lugar aberta (toque num negócio, sugestão escolhida) | 10 000 | ≈ 300 | 200 |
| Places UI Kit — Autocomplete per Session | cada pesquisa (sessão) | 10 000 | ≈ 150 | 100 |
| Map ID | — | sem custo próprio | — | — |
| Geoapify (morada sugerida, servidor) | cada "Estou nesta loja" / lugar escolhido | 3 000 créditos/dia | dezenas/dia | já existe |
| openrouteservice | F3 | 500 + 2 000/dia | — | já existe |

**Custo esperado: 0 €.** Acima dos tetos diários o mapa deixa de abrir até ao dia seguinte (mensagem "Não foi possível carregar o mapa"), em vez de cobrar.

---

## 4. Riscos e pontos a confirmar

| Risco / dúvida | O que se faz |
|---|---|
| Banner "Experimental (pre-GA)" na *overview* do UI Kit vs. GA anunciado em 2025 | Confirmar no dia (§3.1, ponto 9); plano B abaixo |
| O UI Kit não servir (banner, indisponibilidade) | Plano B, não construído: pesquisa por Autocomplete (New) + Place Details (New) `id,location` por proxy no servidor, mostrada **fora** do mapa (diálogo próprio), com chave de servidor restrita por IP. A base de dados não muda |
| Quota diária esgotada → mapa não abre nesse dia | Tetos folgados (3 % do uso previsto); mensagem clara; o resto do CRM funciona; subir o teto na consola é imediato |
| Existência da quota "map loads per day" editável para o Maps JavaScript API | Confirmar na consola; se não existir, orçamento + quota por minuto |
| Pessoa confirma o pino sem o arrastar (coordenada igual à da Google, §2.3) | Decisão A/B do dono; a origem fica registada para se poder agir depois |
| Negócios sem ícone no mapa (não são clicáveis) | Encontram-se pela pesquisa; o toque à mão continua a existir |
| `rh.lisbonb.com` (sinónimo permanente): sem o referrer na chave, o mapa não abre lá | Decisão do dono (§5) |
| Google muda a API (deprecações) | Usam-se só as peças atuais e GA: `AdvancedMarkerElement` (o `google.maps.Marker` antigo não se usa), `importLibrary`, UI Kit base; canal `weekly` |
| Mapa vetorial vs. raster | Raster (por omissão, sem WebGL, nomes sempre visíveis); o Bruce pode mudar o Map ID para vetorial na consola sem mexer no código; o código fixa `collisionBehavior: REQUIRED` para os nomes nunca se esconderem se isso acontecer |
| Sem mapa em local sem chave (antes havia OSM) | Demo Key do dono em `backend/.env.local`; os testes Jest usam um Google falso; a verificação no browser pode servir um Maps JS de teste pelo Playwright |
| Elementos `gmp-*` (custom elements) dentro do React 19 | React 19 suporta custom elements; as propriedades complexas (`locationBias`, o `place` da ficha) põem-se por JS numa `ref`, não por atributos |
| Uma CSP futura no portal (hoje não há) | Teria de permitir `maps.googleapis.com`, `maps.gstatic.com`, `*.googleapis.com`, `*.ggpht.com`, `*.gstatic.com`; o carregador copia o `nonce` de um `<script>` existente |
| A Geoapify recebe um ponto (lat/lng) escolhido na Google para a morada inversa | lat/lng não é "Google Maps Content" protegido (§15.1) e não é ponto-em-polígono; risco baixo; registado para o suporte Google se o Bruce quiser confirmar |

---

## 5. Decisões a fechar pelo dono
1. **30 dias (§2.3):** opção A (recomendada) ou B.
2. **`rh.lisbonb.com`:** acrescentar `https://rh.lisbonb.com/*` aos referrers da chave (recomendado: custo zero, o mapa abre nos dois endereços) ou aceitar que o mapa só abre em `lisbonb.com`.
3. **Map ID raster (por omissão) ou vetorial.**
4. **Ir para produção** só depois de ver o banner do UI Kit (§3.1, ponto 9) e de aceitar os Termos EEA.
5. **Redação** da política de privacidade (secções 4 e 8).

---

## 6. Anexo técnico

### 6.1 Arquitetura no frontend
- **Carregamento:** `lib/crm/carregadorGoogle.js` (porta legível do *inline bootstrap loader* oficial, sem dependência npm): `prepararGoogleMaps({janela, documento, chave, versao: 'weekly', idioma: 'pt-PT', regiao: 'PT'})` → `{importar(nome)}`. Mete **um** `<script src="https://maps.googleapis.com/maps/api/js?key=…&v=weekly&language=pt-PT&region=PT&loading=async&libraries=…&callback=google.maps.__ib__">` por página (copia o `nonce` se houver) e depois delega em `google.maps.importLibrary`. Só corre nas páginas do CRM (já carregadas com `React.lazy`): a Google **não entra** no ficheiro principal do portal. A chave e o Map ID chegam por `GET /api/crm/config`.
- **Mapa (`lib/crm/mapa.js`, com Jest):** `criarMapa({google, documento, elemento, configuracao, aoEscolherLoja?, aoTocarNoMapa?, aoTocarNumLugar?})` → `{mapa, mostrarLojas, enquadrar, redimensionar, centrarEm, destruir}` (a mesma interface de hoje, sem `atribuicao`). `new google.maps.Map(elemento, {mapId, center, zoom, minZoom: 6, maxZoom: 19, clickableIcons: true, disableDefaultUI: true, zoomControl: true, gestureHandling: 'greedy'})`.
  - **Pinos:** `new google.maps.marker.AdvancedMarkerElement({map, position, content, title: 'Nome (Fase)', gmpClickable: true, collisionBehavior: REQUIRED})`. O `content` é um nó DOM montado com o `el()` de `dom.js` (`div.pino.pino--<fase>` com `span.pino__bola` e `span.etiqueta-loja` com o nome em `textContent`): nunca HTML de dados. **Sem agrupamento.** Tocar (ou Enter/Espaço) → `gmp-click` → `aoEscolherLoja(loja, marcador)`.
  - **Toque no mapa:** `mapa.addListener('click', e)`: com `e.placeId` → `e.stop()` (o balão da Google nunca aparece) e `aoTocarNumLugar({placeId, lat, lng})`; sem `placeId` → `aoTocarNoMapa({lat, lng})`.
  - `enquadrar`: `LatLngBounds` + `fitBounds` com margem, e um `idle` único que limita o zoom a 16; `centrarEm(loja, zoom?)`: `setCenter`/`setZoom` ou `panTo`; `destruir`: tira os marcadores (`map = null`), `clearInstanceListeners`, esvazia o elemento (o `StrictMode` monta duas vezes).
  - **F3b:** `mostrarRota` acrescenta pinos numerados (o mesmo `AdvancedMarkerElement`, `content` com o número via `el()`) e a linha `new google.maps.Polyline({path, strokeColor: '#6b2fa3', strokeWeight: 4, clickable: false})` (a "antiga" tracejada com `icons`). A geometria vem do openrouteservice (`polilinha.js`), nunca da Google.
- **Seletor (`lib/crm/seletor.js`, com Jest):** o mesmo controlador (`criarSeletor` → estados `vazio` → `por_confirmar` → `confirmado`), sobre o `criarMapa`. O pino é um `AdvancedMarkerElement` com `gmpDraggable: true` (a gota do CSS como `content`) e `dragend`; o círculo da precisão é um `google.maps.Circle` (`clickable: false`). **Novo:** `escolherLugar(placeId, {reserva?})` (da pesquisa ou do toque num negócio) → a `vista.lugar` abre a ficha (componente) → `lugarCarregado({id, lat, lng})` → `colocar({lat, lng, origem: 'google', google_place_id: id}, {zoom: 18})` + morada sugerida pela Geoapify (`GET /api/crm/morada/inversa`, como no GPS) + foco em "Confirmar". Arrastar mantém o `google_place_id` e passa a origem a `pin_manual`; tocar no mapa à mão limpa o `google_place_id` e fecha a ficha. `localizacaoFinal` → `{lat, lng, origem_coords, precisao_m, google_place_id}`.
- **Ficha do lugar (`lib/crm/lugarGoogle.js` + `components/crm/CartaoLugar.js`):** o controlador puro (`criarCartaoLugar`: só o `placeId` mais recente conta; estados `fechado`/`a_carregar`/`pronto`/`erro`; `lugarDoElemento(place)` devolve **só** `{id, lat, lng}`). O componente desenha `<gmp-place-details-compact>` com `<gmp-place-details-place-request place="…">`, ouve `gmp-load` (lê `el.place.id` e `el.place.location`) e `gmp-error`, e tem "Fechar" e, no mapa principal, "Adicionar como loja". A atribuição embutida fica como a Google a põe (o `css.test.js` recusa qualquer regra `.gm-*` e qualquer `gmp-*` escondido).
- **Pesquisa (`components/crm/PesquisaLugar.js`):** `<gmp-basic-place-autocomplete>` com `includedRegionCodes = ['pt']` e `locationBias` = os limites do mapa ao focar; `gmp-select` → `seletor.escolherLugar(evento.place.id)`. Devolve só o `place_id`; a posição vem da ficha compacta (1 UI Kit Query). Sai a `PesquisaMorada` (Geoapify).
- **Páginas:** `CrmMapa` recebe `aoTocarNumLugar` e mostra o `CartaoLugar` no lugar do cartão da loja; "Adicionar como loja" navega para `lojas/nova` com `state: {lugar: {id, lat, lng}}`. `CrmLojaNova` lê o `state`, chama `escolherLugar(id, {reserva: {lat, lng}})` quando o seletor está pronto, e mostra sob o campo "Nome" a dica "Escreva o nome da loja como quer que apareça no mapa (não se copia da Google)". `CrmLoja` ("Corrigir localização") e `DefinicoesFabrica` usam o seletor novo sem mais alterações (a fábrica ignora o `place_id`).
- **CSS (`crm.css`):** saem as regras `.leaflet-*`; `.pino` passa a um bloco de 44 × 44 px com `transform: translateY(50%)` (o marcador avançado ancora o fundo-centro do conteúdo no ponto; assim a bola fica centrada nas coordenadas) e a etiqueta absoluta à direita com `pointer-events: none`; a gota `.pino-seletor` com a ponta no fundo ao centro; `.crm-cartao-lugar`.
- **Segurança (`seguranca.test.js`):** `google.maps`/`importLibrary` só em `lib/crm/{carregadorGoogle,mapa,seletor}.js`; `content:` só em `mapa.js`/`seletor.js`; `InfoWindow` e `setContent(` recusados em todo o lado; **canários EEA** recusados em todo o código do CRM (comentários incluídos): `displayName`, `formattedAddress`, `shortFormattedAddress`, `addressComponents`, `nationalPhoneNumber`, `internationalPhoneNumber`, `websiteUri`, `fetchFields`, `PlacesService`, `Geocoder(`. As regras de sempre (`innerHTML`, `tel:`…) ficam.

### 6.2 Backend e dados
- **`GET /api/crm/config`** (escritório) → `{google: {chave, map_id} | null, centro: {lat, lng}}`. Lê `CRM_GOOGLE_CHAVE_NAVEGADOR` e `CRM_GOOGLE_MAP_ID` a cada pedido; `null` se faltar uma das duas; nunca nos registos. Sai `CRM_GEOAPIFY_CHAVE_MOSAICOS`.
- **`crm_lojas`:** novo campo **`google_place_id`** (texto `[A-Za-z0-9_-]{1,255}` ou `null`; documentos antigos sem a chave leem-se como `null`); `origem_coords` ganha o valor **`google`** (precisão sempre `null`, como `geocoder`). Vai no **bloco da localização** (`lat`, `lng`, `origem_coords`, `precisao_m`, `google_place_id`) no POST e no PATCH; sai no GET. Sem índice (ninguém procura por ele nesta versão; gancho para "esta loja já existe com este negócio").
- **Morada:** fica **só** `GET /api/crm/morada/inversa` (Geoapify, chave do servidor); `GET /api/crm/morada/pesquisa` e `geoapify.url_pesquisa` saem. A normalização e o cliente ficam como estão.
- **`.env.example`:** o bloco do CRM passa a nomear `CRM_GOOGLE_CHAVE_NAVEGADOR`, `CRM_GOOGLE_MAP_ID`, `CRM_GEOAPIFY_CHAVE_SERVIDOR`, `CRM_GEOAPIFY_URL` (só nomes).

### 6.3 Fluxos
1. **Negócio → loja (mapa):** toque no ícone → `click` com `placeId` → `stop()` → `CartaoLugar` (`gmp-place-details-compact`) → `gmp-load` → `{id, lat, lng}` → "Adicionar como loja" → `lojas/nova` com `state.lugar` → seletor `escolherLugar` → ficha outra vez (para ler o nome) + pino solto em `lat/lng` + Geoapify inversa → arrastar, **Confirmar** → escrever o nome → Guardar (`origem_coords: 'google' | 'pin_manual'`, `google_place_id`).
2. **Pesquisa:** `gmp-basic-place-autocomplete` → `gmp-select` (só `place.id`) → o mesmo que o ponto 1 a partir de `escolherLugar`.
3. **GPS:** igual a hoje.
4. **Rota (F3b):** ORS → `calculo.geometria` → `descodificarPolilinha` → `Polyline` sobre o mapa; "Routing provided by openrouteservice" + atribuição ORS no painel.
5. **Falhas:** sem chave → "Mapa não configurado — peça ao administrador"; a Google não carrega / quota → "Não foi possível carregar o mapa — recarregue a página" (sem mapa não há pino nem GPS, como hoje); ficha do lugar falha → "Não foi possível abrir a ficha deste lugar — toque no mapa no sítio da loja." (com `reserva`, o pino é posto na mesma).

### 6.4 Geoapify: o que fica
Fica **só a geocodificação inversa** ("Morada sugerida: … · Powered by Geoapify"), para o GPS e para os lugares Google: os dados OSM podem ser guardados e a Geocoding API da Google não serve aqui (§6.1 dos Termos Específicos EEA: moradas da Google não podem aparecer com um mapa nem ficar numa base partilhada). Saem: os mosaicos, a chave dos mosaicos, a pesquisa (autocomplete), o controlo de alternativa (`mosaicos.js`) e as atribuições do mapa; a atribuição "Powered by Geoapify" fica junto à morada sugerida.

### 6.5 Testes
- **Jest (módulos puros):** `testes/googleFalso.js` substitui o `leafletFalso.js` (Map, AdvancedMarkerElement com `arrastarPara`, Circle, Polyline, LatLngBounds, `event`, `IconMouseEvent` com `stop()`, `importLibrary`); `carregadorGoogle.test.js` com `janela`/`documento` falsos; `mapa.test.js`, `seletor.test.js`, `lugarGoogle.test.js`, `localizacao.test.js`, `diferencas.test.js`, `ecraMapa.test.js`, `lojaNova.test.js`, `css.test.js`, `seguranca.test.js`, `privacidade.test.js` adaptados. Os testes sobre o "Leaflet verdadeiro no jsdom" desaparecem (o Google não corre no jsdom).
- **Backend:** `test_config_mapa.py` reescrito; `google_place_id` e a origem `google` nos testes do domínio, do formatador e das rotas das lojas; `test_morada.py`/`test_geoapify.py`/`test_protecao_rotas.py` sem a pesquisa; `test_variaveis_ambiente.py` com as variáveis novas.
- **No browser (local):** Playwright sem janela com a Demo Key do dono em `backend/.env.local`, ou, sem ela, um Maps JS de teste servido pelo próprio Playwright no endereço `maps.googleapis.com` (a mesma superfície do `googleFalso` + elementos `gmp-*` que disparam `gmp-load`). Nada sai do Mac.

### 6.6 Como a F3b assenta no mapa novo
As tarefas T3.26–T3.43 do plano da F3 fazem-se **depois** deste plano, sobre o `MapaLojas` novo: pinos numerados com `AdvancedMarkerElement` e `el()`, linha com `google.maps.Polyline`, extremos iguais; o `googleFalso` ganha `Polyline`; a receita de verificação troca "Leaflet verdadeiro no jsdom" por "`googleFalso` + Maps JS de teste no Playwright"; o planeador mostra "Routing provided by openrouteservice" antes da linha e a atribuição do ORS no painel. Arrastar paragens, sugestões, calcular e guardar **não mudam**. A lista exata das substituições está no §7 do plano.

### 6.7 Ficheiros (resumo)
- **Novos:** `frontend/src/lib/crm/{carregadorGoogle,lugarGoogle}.js` (+ testes), `frontend/src/lib/crm/testes/googleFalso.js`, `frontend/src/components/crm/{CartaoLugar,PesquisaLugar}.js`.
- **Alterados:** `lib/crm/{mapa,seletor,localizacao,diferencas,morada,atribuicoes,api,lojaNova,ficha,ecraMapa}.js` (+ testes), `seguranca.test.js`, `css.test.js`, `privacidade.test.js`, `components/crm/{MapaLojas,SeletorLocalizacao}.js`, `crm.css`, `pages/crm/{CrmMapa,CrmLojaNova,CrmLoja,DefinicoesFabrica}.js`; `backend/crm/{config_mapa,morada,formatar}.py`, `backend/crm/dominio/{campos_loja,validador_loja}.py`, `backend/crm/servicos/geoapify.py` e os testes; partilhados: `pages/PrivacyPolicy.js`, `backend/.env.example`, `frontend/package.json` + `yarn.lock` (sai o Leaflet).
- **Apagados:** `lib/crm/{mosaicos,pesquisaMorada}.js` (+ testes), `lib/crm/testes/leafletFalso.js`, `components/crm/PesquisaMorada.js`.


> Estado: rascunho gerado a 2026-10-14 a partir de pesquisa verificada nos termos oficiais da Google (EEA); a revisão por críticos ficou por fazer (limite de utilização) e é feita antes da construção.
