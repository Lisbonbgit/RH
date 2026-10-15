# CRM Purple House no portal: plano de implementação G (o mapa passa a Google)

- **Data:** 2026-10-14 · **Ramo:** `crm-purple-house` (local). **Ficheiro:** `docs/superpowers/plans/2026-10-14-crm-mapa-google.md`
- **Fontes (ler antes de começar):**
  - Adenda aprovada pelo dono: `docs/superpowers/specs/2026-10-14-crm-mapa-google-design.md` (prevalece; §2 regras EEA, §6 anexo técnico).
  - Desenhos anteriores: `docs/superpowers/specs/2026-10-09-crm-purple-house-no-portal-design.md` e `2026-10-02-crm-purple-house-desenho-original.md` (§6 e §9, na parte que a adenda não substitui).
  - Planos anteriores: `docs/superpowers/plans/2026-10-10-crm-f0-f1-f2.md` (as **Correções obrigatórias** e as notas "Feito" continuam a valer como receitas; T2.23, T2.25, T2.26 são o molde) e `2026-10-11-crm-f3-planear-rota.md` (§0, §1, T3.26–T3.43: o que muda está no §7 deste plano). Dossiê `CRM_PORTING_GUIDE.md` (§0, §2.1, §5.15, §7, §8, §9, §12, §14).
  - Código real em que este plano assenta: `frontend/src/components/crm/{MapaLojas,SeletorLocalizacao,PesquisaMorada,crm.css}`, `frontend/src/lib/crm/{mapa,mosaicos,seletor,pesquisaMorada,morada,localizacao,diferencas,atribuicoes,api,lojaNova,ficha,ecraMapa,fabrica,dom}.js`, `lib/crm/testes/{leafletFalso,domFalso}.js`, `seguranca.test.js`, `css.test.js`, `privacidade.test.js`; `pages/crm/{CrmMapa,CrmLojaNova,CrmLoja,DefinicoesFabrica,rotasCrm}.js`; `backend/crm/{config_mapa,morada,formatar,lojas}.py`, `backend/crm/dominio/{campos_loja,validador_loja,geo}.py`, `backend/crm/servicos/geoapify.py`; `backend/tests/crm/{test_config_mapa,test_variaveis_ambiente,test_morada,test_geoapify,test_protecao_rotas,test_consistencia_frontend,test_dominio_campos_loja,test_dominio_validador_criacao,test_dominio_validador_alteracao,test_formatar,test_lojas_criar,test_lojas_editar}.py`.
- **Âmbito:** trocar o Leaflet + Geoapify (mosaicos e pesquisa) pelo Google Maps (Maps JavaScript API + Places UI Kit) em todos os ecrãs com mapa da F2, guardar o `google_place_id`, e preparar a F3b. **Fora (YAGNI):** o planeador em si (F3d–F3f, que se faz a seguir sobre o mapa novo), o proxy de Place Details (New) e a tarefa dos 30 dias (opção B da adenda §2.3), "Ver na Google" a partir do cartão da loja, índice por `google_place_id`, publicar, juntar ao `main`, ligar ao Atlas.
- **Sequência com a F3:** a F3a–F3c (backend, T3.1–T3.25) termina primeiro **ou** este plano corre num ramo `crm-mapa-google` criado do topo do `crm-purple-house` e junta-se (merge, nunca rebase) quando a T3.25 fechar. **Nunca os dois no mesmo ramo ao mesmo tempo.** A F3d–F3f só começa depois da G21.

> ⚠️ Antes de cada tarefa, ver a secção **Correções obrigatórias** no fim (vazia até à revisão por críticos). Quando tiver linhas, prevalecem sobre o texto da tarefa.

---

## 0. Como usar este plano (regras para os agentes — obrigatórias)

1. **Ordem estrita.** Fazer as tarefas pela ordem; cada tarefa assume só as anteriores. Marcar `[x]` no fim e acrescentar uma nota **Feito** no molde da F2 (vermelho, verde, contagens da bateria, decisões fixadas pelos testes, desvios, notas para as tarefas seguintes). Cada tarefa leva 15–60 min.
2. **Nada sai do Mac.** Proibido: `git push`, `git merge` para o `main`, `deploy.sh`, `ssh` ao VPS, qualquer ligação ao MongoDB Atlas, enviar emails ou mensagens, e **qualquer pedido à Google com uma chave que não seja a Demo Key que o dono pôs no `backend/.env.local`**. Os agentes nunca criam projetos, chaves nem Map IDs na consola Google (é [DONO], G1).
3. **TDD em todas as tarefas de domínio, de API e de módulos puros:** escrever o teste → correr e ver falhar **pelo motivo indicado na tarefa** → implementar o mínimo → ver passar → correr a bateria do CRM (`tests/crm` e/ou `src/lib/crm`). Guardar o vermelho e o verde em `$HOME/.cache/lisbonb-crm-local/g.N-{vermelho,verde}.log`. As **mutações mínimas** listadas em cada tarefa têm todas de ser apanhadas (registo em `g.N-mutacoes.log`, ficheiro reposto conferido com `cmp`).
4. **Testes nunca em paralelo.** Só o agente que executa a tarefa corre testes, uma suite de cada vez. Os revisores leem código e não correm suites.
5. **Anti-encalhe** (igual à F2/F3): nunca servidores em primeiro plano; instalações, a suite completa do backend e o `craco build` em segundo plano com registo em `$HOME/.cache/lisbonb-crm-local/*.log`; esperas limitadas (`curl --max-time 3`); `pytest tests/crm` e o Jest de `src/lib/crm` em primeiro plano, abaixo de 90 s.
6. **Ficheiros partilhados com o Matheus.** Neste plano tocam-se **quatro**, cada um no seu commit, com `git diff --stat` a mostrar só as linhas previstas: `backend/.env.example` (G2, o bloco do CRM), `frontend/src/pages/PrivacyPolicy.js` (G18), `frontend/package.json` + `frontend/yarn.lock` (G19, só a saída do Leaflet). **Não se tocam** `backend/server.py`, `frontend/src/App.js`, `AdminLayout.js`, `EmployeeLayout.js`, `frontend/public/index.html` (o Google carrega-se por código, só nas páginas do CRM). **Nenhuma dependência npm nova** (o carregador é nosso, `lib/crm/carregadorGoogle.js`). Se uma tarefa parecer precisar de outro ficheiro partilhado, **parar e perguntar**.
7. **Commits:** um por tarefa (as tarefas sem commit estão indicadas), em pt-PT e com o prefixo `CRM:`. Adicionar **ficheiros explícitos**, nunca `git add -A` nem `git add .`. A pasta `HANDOFF/` não está versionada e não se toca. Formato (a linha `Co-Authored-By` leva o modelo que executa a tarefa, como nas F2/F3):
   `git -C "/Users/brucesilva/pasta sem título/RH" commit -m "CRM: <frase>" -m "Co-Authored-By: <modelo que executa> <noreply@anthropic.com>"`
8. **Segredos:** nunca mostrar valores de `.env*`, chaves ou Map IDs, nem no chat nem em ficheiros versionados (só os nomes). A chave de produção e o Map ID **nunca** são escritos pelos agentes. Em local, o dono põe a Demo Key no `backend/.env.local`; os agentes só conferem com `grep -c "^CRM_GOOGLE" "$RAIZ/backend/.env.local"`.
9. **Segurança do DOM e da Google** (regra 9 da F2, adaptada): nunca `dangerouslySetInnerHTML` nem `.innerHTML`; **`google.maps` e `importLibrary` só em `lib/crm/{carregadorGoogle,mapa,seletor}.js`**; o `content` de um marcador avançado é sempre um nó do `el()` e só se monta em `mapa.js`/`seletor.js`; **nunca `InfoWindow`** (o balão da Google é HTML); **nunca ler nem nomear no código do CRM** `displayName`, `formattedAddress`, `shortFormattedAddress`, `addressComponents`, `nationalPhoneNumber`, `internationalPhoneNumber`, `websiteUri`, `fetchFields`, `PlacesService`, `Geocoder(` (canários EEA do `seguranca.test.js`; nos comentários escrever "nome do negócio", "morada da Google"); da ficha de um lugar lê-se só `place.id` e `place.location`; **nenhuma regra CSS** começa por `.gm-` nem esconde um `gmp-*`. Cada ficheiro novo do CRM entra na lista do `seguranca.test.js`.
10. **Caminhos com espaços e acentos:** citar sempre. Cada bloco de comandos começa por `RAIZ="/Users/brucesilva/pasta sem título/RH"; LOGS="$HOME/.cache/lisbonb-crm-local";` (o estado da shell não passa de uma chamada para a seguinte).
11. **[DONO]** marca o que só o Bruce faz. Os agentes não o fazem nem o simulam.
12. **Proibições herdadas e novas:** não reutilizar a `GOOGLE_PLACES_API_KEY` do portal (é do Marketing); não guardar nome, morada, telefone, horário ou fotos vindos da Google (nem por botão "copiar"); nunca ponto-em-polígono com coordenadas Google; não endurecer a `Referrer-Policy` (a chave Google também é restrita por referrer); ao openrouteservice só coordenadas e números (F3); a Geoapify fica **só** para a morada inversa.
13. **Corrotinas nos testes:** `correr(coro)` de `tests/crm/duplos.py`, nunca `asyncio.run`.
14. **Rotas que mudam** classificam-se no passo "teste primeiro": a saída de `GET /morada/pesquisa` sai de `PERFIS_POR_ROTA` (`tests/crm/test_protecao_rotas.py`) na G17; não entram rotas novas.
15. **Entre a G2 e a G14 a pré-visualização local do mapa fica partida** (o `/config` muda de forma antes de os ecrãs mudarem). É aceite: nada se publica a meio, e a G21 volta a pô-la a correr.

---

## 1. Decisões técnicas fixadas (não rediscutir)

| Tema | Decisão |
|---|---|
| Biblioteca | **Maps JavaScript API**, canal `v=weekly`, `language=pt-PT`, `region=PT`, `loading=async`, carregada por **`lib/crm/carregadorGoogle.js`** (porta do *inline bootstrap loader* oficial; sem `@googlemaps/js-api-loader`, que custava uma dependência e os ficheiros partilhados para 40 linhas). Só nas páginas do CRM (`React.lazy` já existe); `importar('maps')`, `importar('marker')`, `importar('places')`. |
| Chave e Map ID | Chegam por `GET /api/crm/config` → `{google: {chave, map_id} \| null, centro}`; variáveis `CRM_GOOGLE_CHAVE_NAVEGADOR` e `CRM_GOOGLE_MAP_ID`, lidas a cada pedido; as duas obrigatórias (o Map ID é preciso para os marcadores avançados). Sai `CRM_GEOAPIFY_CHAVE_MOSAICOS`. Sem as duas → `google: null` → `MENSAGEM_MAPA_NAO_CONFIGURADO`. **Nenhuma chave Google no servidor** (sem proxy). |
| Map ID | Tipo JavaScript, **raster**, sem estilo (POIs visíveis e clicáveis). O código fixa `collisionBehavior: REQUIRED` para o caso de o dono mudar para vetorial. Em local, `DEMO_MAP_ID` com a Demo Key. |
| Opções do mapa | `{mapId, center, zoom, minZoom: ZOOM_MINIMO (6), maxZoom: ZOOM_MAXIMO (19), clickableIcons: true, disableDefaultUI: true, zoomControl: true, gestureHandling: 'greedy', mapTypeId: 'roadmap'}`. Os títulos dos botões de zoom vêm da Google em português (saem `TITULO_APROXIMAR`/`TITULO_AFASTAR`). As constantes de zoom (6, 12, 16, 17, 18, 19) **não mudam**. |
| Pinos | `google.maps.marker.AdvancedMarkerElement` com `content` = `el(documento, 'div', {classe: classePino(fase), filhos: [span.pino__bola, span.etiqueta-loja com o nome em texto]})`, `title: 'Nome (Fase)'`, `gmpClickable: true`, `collisionBehavior: REQUIRED`; **sem agrupamento**; `gmp-click` escolhe a loja (teclado incluído). O `google.maps.Marker` antigo **não se usa**. A ancoragem do conteúdo (fundo-centro) compensa-se no CSS (`translateY(50%)`). |
| Toque no mapa | `click` do mapa: com `placeId` → `evento.stop()` sempre (o balão da Google nunca aparece) e `aoTocarNumLugar({placeId, lat, lng})` se houver; sem `placeId` → `aoTocarNoMapa({lat, lng})`. |
| Ficha do lugar | **Places UI Kit — Place Details Compact** (`<gmp-place-details-compact>` + `<gmp-place-details-place-request place>`), num componente nosso (`CartaoLugar`), no mesmo lugar do cartão da loja. O código lê **só** `place.id` e `place.location` em `gmp-load` (`lugarDoElemento` devolve exatamente `{id, lat, lng}`). Os elementos "Advanced…" (beta) não se usam. |
| Pesquisa | **Basic Place Autocomplete** do UI Kit (`<gmp-basic-place-autocomplete>`, `includedRegionCodes = ['pt']`, `locationBias` = limites do mapa ao focar). Devolve só `place.id`; a posição vem da ficha compacta. A pesquisa Geoapify (`/morada/pesquisa`, `pesquisaMorada.js`, `PesquisaMorada.js`, `criarPesquisaMorada`) **sai**. |
| Morada em texto | Só pela **Geoapify inversa** (`GET /api/crm/morada/inversa`), como no GPS, tanto para o lugar Google como para o pino à mão nunca (como hoje: só GPS e, agora, lugar). Nunca a Geocoding API da Google. "Morada sugerida: … · Powered by Geoapify" fica. |
| Dados | `crm_lojas.google_place_id`: texto `[A-Za-z0-9_-]{1,255}` ou `null` (`campos_loja.google_place_id`), no **bloco da localização** (`_LOCALIZACAO` + `CAMPOS_LOCALIZACAO`); `origem_coords` ganha `"google"` (pino de um lugar Google confirmado sem arrastar; arrastado → `pin_manual`, pela regra `origemFinal` de sempre; `precisao_m` sempre `null`). Documentos antigos sem a chave → `null` na API (`doc.get`). Sem índice. |
| Os 30 dias | Adenda §2.3: fica registado (`origem_coords: "google"` + `atualizado_em`); a opção B (refrescar por proxy) **não se constrói**. |
| Sem mapa | Sem `google` no `/config` → `MENSAGEM_MAPA_NAO_CONFIGURADO` ('Mapa não configurado — peça ao administrador para configurar a chave Google.'); a Google falha a carregar (rede, quota, referrer) → `MENSAGEM_SEM_MAPA` de sempre. Sem mapa não há pesquisa, ficha nem GPS (como hoje). **Não há** mapa alternativo (OSM/Leaflet sai). |
| Atribuições | A da Google é a da própria API: **nunca se esconde** (o `css.test.js` recusa seletores `.gm-*` e `gmp-*` escondidos). `ATRIBUICOES` fica só com `pesquisa` (Powered by Geoapify) e, na F3, `ors`; saem `geoapify`, `osm` e o `html` (não há controlo de atribuição nosso). F3b: `TEXTO_ROTA_DE_TERCEIROS = 'Routing provided by openrouteservice'`. |
| Falsos nos testes | `lib/crm/testes/googleFalso.js` (substitui o `leafletFalso.js`): `googleFalso()` → `{google, registo}` com `maps.Map`, `maps.marker.AdvancedMarkerElement`, `maps.Circle`, `maps.Polyline`, `maps.LatLngBounds`, `maps.CollisionBehavior`, `maps.event`, `maps.importLibrary`, e `eventoDeToque({lat, lng, placeId?})` com `stop()`. Os testes "sobre o Leaflet verdadeiro no jsdom" desaparecem (o Google não corre no jsdom). O `domFalso.js` fica. |
| Verificação no browser | Playwright sem janela, com a Demo Key que o dono pôs em `backend/.env.local`; **sem ela**, o Playwright interceta `https://maps.googleapis.com/maps/api/js*` e serve `$LOGS/g-verificacao/maps-teste.js` (a superfície do `googleFalso` em JS de browser + `customElements.define('gmp-place-details-compact' | 'gmp-basic-place-autocomplete', …)` que disparam `gmp-load`/`gmp-select` com um lugar fixo). Nunca com a chave de produção. |
| Leaflet | Sai por completo (código, CSS, testes, dependência) na G19, depois de todos os ecrãs estarem no Google. |
| Ordem com a F3 | Ver o cabeçalho. A F3d–F3f usa o `MapaLojas` novo (§7). |

---

## 2. Ficheiros

**Criar (frontend)**
```
frontend/src/lib/crm/carregadorGoogle.js      prepararGoogleMaps({janela, documento, chave, versao, idioma, regiao}) → {importar}
frontend/src/lib/crm/carregadorGoogle.test.js
frontend/src/lib/crm/lugarGoogle.js           lugarDoElemento, criarCartaoLugar, textos do cartão e da pesquisa
frontend/src/lib/crm/lugarGoogle.test.js
frontend/src/lib/crm/testes/googleFalso.js    o google.maps falso (só testes; fora do varrimento)
frontend/src/lib/crm/atribuicoes.test.js      (não existia; a F3 T3.26 só o acrescenta)
frontend/src/components/crm/CartaoLugar.js    <gmp-place-details-compact> + Fechar + ação opcional
frontend/src/components/crm/PesquisaLugar.js  <gmp-basic-place-autocomplete>
```
**Modificar (frontend, do CRM):** `lib/crm/{mapa,seletor,localizacao,diferencas,morada,atribuicoes,api,lojaNova,ficha,ecraMapa}.js` e os seus testes; `lib/crm/{seguranca,css,privacidade}.test.js`; `components/crm/{MapaLojas,SeletorLocalizacao}.js` e `crm.css`; `pages/crm/{CrmMapa,CrmLojaNova,CrmLoja,DefinicoesFabrica}.js` (+ o comentário do `rotasCrm.js` que fala do Leaflet).

**Apagar (frontend):** `lib/crm/{mosaicos,mosaicos.test,pesquisaMorada,pesquisaMorada.test}.js`, `lib/crm/testes/leafletFalso.js`, `components/crm/PesquisaMorada.js`.

**Modificar (backend, do CRM):** `crm/config_mapa.py`, `crm/dominio/{campos_loja,validador_loja}.py`, `crm/formatar.py`, `crm/morada.py`, `crm/servicos/geoapify.py`; testes `tests/crm/{test_config_mapa,test_variaveis_ambiente,test_dominio_campos_loja,test_dominio_validador_criacao,test_dominio_validador_alteracao,test_formatar,test_lojas_criar,test_lojas_editar,test_morada,test_geoapify,test_protecao_rotas,test_consistencia_frontend}.py` (e `test_mongo_local.py` se enumerar os campos da loja).

**Partilhados (mínimo, cada um no seu commit):** `backend/.env.example` (G2: o bloco do CRM, ≈ +10/−8), `frontend/src/pages/PrivacyPolicy.js` (G18, ≈ +9/−6), `frontend/package.json` + `frontend/yarn.lock` (G19: só a saída do `leaflet`, −1 e −5).

**Documentos:** este plano, a adenda, `docs/superpowers/plans/2026-10-11-crm-f3-planear-rota.md` (G20: um bloco "Correções obrigatórias (mapa Google)"), `CRM_PORTING_GUIDE.md` (G20).

**Só locais (nunca versionados):** `backend/.env.local` (as duas linhas `CRM_GOOGLE_*` com a Demo Key, pelo dono), `$HOME/.cache/lisbonb-crm-local/g*` (registos, verificações temporárias, o `maps-teste.js`).

---

## 3. Modelo de dados — o que muda em `crm_lojas`

| Campo | Antes | Depois |
|---|---|---|
| `origem_coords` | `pin_manual \| gps \| geocoder` | + **`google`** (pino de um lugar Google, confirmado sem arrastar) |
| `google_place_id` | — | texto `[A-Za-z0-9_-]{1,255}` ou `null`; faz parte do bloco da localização; documentos antigos sem a chave leem-se como `null` |
| `precisao_m` | só com `gps` | igual (`google` → `null`, como `geocoder`) |

Sem migração e sem índice novo. O `loc` (2dsphere) e as regras dos 50 m não mudam.

---

## 4. API — o que muda

| Rota | Antes | Depois |
|---|---|---|
| `GET /api/crm/config` (escritório) | `{mosaicos: {url, atribuicao}, alternativa: {url}, centro}` | `{google: {chave, map_id} \| null, centro: {lat, lng}}` |
| `POST /api/crm/lojas`, `PATCH /api/crm/lojas/{id}` | bloco `lat, lng, origem_coords, precisao_m` | bloco + `google_place_id` (opcional; `null` limpa); `origem_coords` aceita `google`; 422 `google_place_id`: "O identificador do lugar na Google não é válido." |
| `GET /api/crm/lojas/{id}`, o 201/200 das escritas | — | + `google_place_id` (a lista `GET /lojas` **não** o traz: `CAMPOS_RESUMO` não muda) |
| `GET /api/crm/morada/pesquisa` | Geoapify autocomplete | **sai** (404 do FastAPI) |
| `GET /api/crm/morada/inversa` | Geoapify inversa | igual |

---

## 5. Comandos de referência

```bash
RAIZ="/Users/brucesilva/pasta sem título/RH"; LOGS="$HOME/.cache/lisbonb-crm-local"; export PATH="/opt/homebrew/bin:$PATH"
# Backend: um ficheiro e a bateria do CRM (primeiro plano, < 90 s)
cd "$RAIZ/backend" && .venv/bin/python -m pytest -q -p no:cacheprovider tests/crm/test_X.py
cd "$RAIZ/backend" && .venv/bin/python -m pytest -q -p no:cacheprovider tests/crm
# Ensaio no MongoDB local (primeiro plano, ~10 s)
cd "$RAIZ/backend" && CRM_MONGO_TESTE_URL=mongodb://127.0.0.1:27017 .venv/bin/python -m pytest -q -p no:cacheprovider tests/crm/test_mongo_local.py
# Suite completa (SEGUNDO PLANO)
cd "$RAIZ/backend" && .venv/bin/python -m pytest -q -p no:cacheprovider -rfEs > "$LOGS/pytest-tudo-G.log" 2>&1; echo "saida=$?" >> "$LOGS/pytest-tudo-G.log"
# Frontend: Jest (primeiro plano) e build (SEGUNDO PLANO, fora de frontend/build)
cd "$RAIZ/frontend" && CI=true ./node_modules/.bin/craco test --watchAll=false src/lib/crm
cd "$RAIZ/frontend" && BUILD_PATH="$LOGS/build" CI=false ./node_modules/.bin/craco build > "$LOGS/build-G.log" 2>&1; echo "saida=$?" >> "$LOGS/build-G.log"
# Inventário do Leaflet e da Geoapify no frontend (tem de ficar vazio na G19)
grep -rln "leaflet\|Leaflet" "$RAIZ/frontend/src" ; grep -rn "pesquisarMorada\|mosaicos" "$RAIZ/frontend/src/lib/crm" "$RAIZ/frontend/src/components/crm" "$RAIZ/frontend/src/pages/crm"
# Só conferir que o dono pôs a Demo Key (nunca imprimir valores)
grep -c "^CRM_GOOGLE" "$RAIZ/backend/.env.local"
```
Servidores locais, `preview_start` e como parar: dossiê §12.6. A pré-visualização da F2/F3 pode estar a correr (8001/3000) com código velho; só se para na G21. ESLint do CRA: a receita da T1.13 (`--max-warnings 0 --report-unused-disable-directives`).

---

## 6. Tarefas

### Bloco G0 — Partida

#### [ ] G0 Verificação de partida (15 min, sem commit)
- `git -C "$RAIZ" status --short` limpo (o `HANDOFF/` e os ficheiros não versionados da F3 não contam); ramo `crm-purple-house` (ou `crm-mapa-google` criado do topo, se a F3 estiver a meio — ver o cabeçalho). Registar o topo.
- Suites de partida: `pytest tests/crm` e o Jest de `src/lib/crm` verdes; registar as contagens em `$LOGS/g0-partida.log`.
- Inventário: o comando do §5 lista hoje o Leaflet em `MapaLojas.js`, `SeletorLocalizacao.js`, `mapa.js`, `seletor.js`, `mapa.test.js`, `seletor.test.js`, `css.test.js`, `testes/leafletFalso.js`, `crm.css`, `rotasCrm.js` (comentário) e `DefinicoesFabrica.js` (comentário). `ls "$RAIZ/frontend/node_modules/@googlemaps"` dá "não existe" (e assim fica).
- Confirmar que o `Caddyfile` e o `frontend/nginx.conf` **não** definem `Referrer-Policy` nem `Content-Security-Policy` (vale o padrão do browser).

#### [ ] G1 [DONO] Consola Google Cloud e chaves (sem ação dos agentes)
Os passos exatos estão na adenda §3.1 (projeto com faturação PT; aceitar os Termos EEA; ativar **só** Maps JavaScript API e Places UI Kit; chave do navegador restrita a `https://lisbonb.com/*` (+ `https://rh.lisbonb.com/*` se decidir) e às duas APIs; Map ID JavaScript/raster; quotas diárias e orçamento de 1 €; a Demo Key em `backend/.env.local` com `CRM_GOOGLE_MAP_ID=DEMO_MAP_ID` para a pré-visualização local). Os agentes registam no dossiê §14 e continuam: até à G21 não precisam de nenhuma chave (o Jest usa o Google falso), e a G21 tem o caminho sem chave (Maps JS de teste no Playwright).

### Bloco G2 — Backend

#### [ ] G2 `GET /config` entrega a chave do navegador e o Map ID (45 min)
- **Ficheiros:** `backend/crm/config_mapa.py`, `backend/tests/crm/test_config_mapa.py`, `backend/tests/crm/test_variaveis_ambiente.py`, `backend/.env.example` (**partilhado**).
- **Teste primeiro.** `test_config_mapa.py` reescrito (os nomes dos casos em pt-PT, como hoje): a função pura passa a `config_mapa(chave, map_id, definicoes)` → `{"google": {"chave": …, "map_id": …}, "centro": {…}}`; chave vazia **ou** Map ID vazio → `"google": None`; a chave vai tal e qual (vai no JSON, não num URL: sai o `_codificar` e os casos do `rawurlencode`); as chaves do dicionário saem por esta ordem (`google`, `centro`); `VARIAVEL_CHAVE = "CRM_GOOGLE_CHAVE_NAVEGADOR"` e `VARIAVEL_MAP_ID = "CRM_GOOGLE_MAP_ID"`, lidas **a cada pedido** (`monkeypatch.setenv` depois da importação); a rota continua do escritório (motorista e não-membro recusados; sem sessão 401/403 herdados; conta apagada 401); o centro vem das definições em vigor e uma definição estragada não parte o mapa; **nem a chave nem o Map ID vão para os registos** (dois canários + `caplog` em DEBUG). Em `test_variaveis_ambiente.py`, `LIDAS_PELO_CRM` passa a ter `config_mapa.VARIAVEL_CHAVE`, `config_mapa.VARIAVEL_MAP_ID`, `geoapify.VARIAVEL_CHAVE_SERVIDOR`, `geoapify.VARIAVEL_URL`, `ADMIN_EMAIL`, `CRON_KEY` (a dos mosaicos sai). Falha por `ImportError: cannot import name 'VARIAVEL_MAP_ID'` e, no `.env.example`, por a variável dos mosaicos continuar lá e as novas faltarem.
- **Implementação:** `config_mapa.py` com a docstring nova (a chave do navegador é pública por natureza; restrita por referrer e APIs na consola; só a membros). `.env.example`: no bloco do CRM, o cabeçalho passa a "CRM Purple House (backend/crm) — Google Maps e Geoapify", entram `CRM_GOOGLE_CHAVE_NAVEGADOR=` e `CRM_GOOGLE_MAP_ID=` (comentário: vão para o browser por `GET /api/crm/config`; restringir na consola a `https://lisbonb.com/*` e às duas APIs; não endurecer a `Referrer-Policy`), sai `CRM_GEOAPIFY_CHAVE_MOSAICOS=` e o seu comentário, a `CRM_GEOAPIFY_CHAVE_SERVIDOR` passa a dizer "só a morada sugerida de um ponto". Nada fora do bloco muda (`git diff --stat` ≈ +10/−8 nesse ficheiro).
- **Mutações mínimas:** devolver `google` com a chave vazia; trocar `chave` e `map_id`; ler a variável à importação; escrever a chave num `logger.info`.
- **Commit:** `CRM: a configuração do mapa entrega a chave do navegador e o Map ID da Google`

#### [ ] G3 A loja guarda o `google_place_id` e a origem `google` (60 min)
- **Ficheiros:** `backend/crm/dominio/campos_loja.py`, `backend/crm/dominio/validador_loja.py`, `backend/crm/formatar.py`, testes `test_dominio_campos_loja.py`, `test_dominio_validador_criacao.py`, `test_dominio_validador_alteracao.py`, `test_formatar.py`, `test_lojas_criar.py`, `test_lojas_editar.py` (+ `test_mongo_local.py` se enumerar os campos).
- **Teste primeiro.** Falha por `ImportError: cannot import name 'google_place_id'` em `campos_loja`, por `"google" not in ORIGENS`, e pelos dicionários exatos sem a chave nova.
  - `campos_loja.google_place_id(valor)` → `(texto, None)`: `"ChIJN1t_tDeuEmsRUsoyG83frY4"` fica; `None`, `""`, `"  "` → `(None, None)`; `"abc def"`, `"<b>x</b>"`, `"ChIJ/..."`, 256 caracteres, `42`, `True` → `(None, "O identificador do lugar na Google não é válido.")`; `PLACE_ID_MAXIMO = 255` numa só linha.
  - `validador_loja`: `ORIGENS = ("pin_manual", "gps", "geocoder", "google")`; `CAMPOS` com `google_place_id` a seguir a `precisao_m` (os "20 campos" passam a **21** nas docstrings e nas asserções); `_LOCALIZACAO` inclui `google_place_id` (opcional: ausente → `None`); na **alteração**, um PATCH só com `google_place_id` dá 422 `MENSAGEM_LOCALIZACAO_INCOMPLETA` (como hoje com só `precisao_m`); `origem_coords: "google"` aceita-se e a `precisao_m` fica `None` mesmo que venha (como `geocoder`); `google_place_id` com `origem_coords: "pin_manual"` também se aceita (o pino foi arrastado).
  - `formatar`: `documento_loja` grava `google_place_id`; `loja_api` lê com `doc.get("google_place_id")` (um documento antigo sem a chave → `None`); `CAMPOS_API` com a chave a seguir a `precisao_m`; `CAMPOS_RESUMO` **não muda** (teste explícito).
  - Rotas: POST com `google_place_id` → 201 com ele; PATCH do bloco com `google_place_id: null` limpa; PATCH com o id inválido → 422 por campo; o 409 dos 50 m continua a aplicar-se.
- **Mutações mínimas:** aceitar espaços; ignorar o máximo; `doc["google_place_id"]` em vez de `doc.get` (KeyError nos documentos antigos); `"google"` com precisão guardada.
- **Commit:** `CRM: a loja guarda o identificador do lugar Google e a origem google do pino`

### Bloco G3 — Frontend: módulos puros (Jest)

#### [ ] G4 `lib/crm/carregadorGoogle.js` (45 min)
- **Ficheiros:** `frontend/src/lib/crm/carregadorGoogle.js` (+ teste), `seguranca.test.js` (a lista exige o ficheiro novo; o teste de regras muda na G7).
- **Teste primeiro.** Falha por `Cannot find module './carregadorGoogle'`. Com uma `janela` falsa (`{google: undefined}`) e um `documento` falso (`createElement('script')` devolve um objeto com `src`, `onerror`, `nonce`; `head.append` guarda; `querySelector('script[nonce]')`):
  - `prepararGoogleMaps({janela, documento, chave: 'chave-teste'})` não toca no documento; `importar('maps')` mete **um** `<script>` em `documento.head` cuja `src` é `https://maps.googleapis.com/maps/api/js?` com exatamente `key=chave-teste`, `v=weekly`, `language=pt-PT`, `region=PT`, `loading=async`, `libraries=maps`, `callback=google.maps.__ib__` (lidos com `URL`); a promessa só resolve quando o "script" instala `janela.google.maps.importLibrary = jest.fn(async (nome) => ({nome}))` e chama `janela.google.maps.__ib__()`; depois disso `importar('marker')` chama o `importLibrary` verdadeiro e devolve o que ele devolve;
  - `importar('maps')` chamado duas vezes antes de carregar → um só script; um segundo `prepararGoogleMaps` na mesma `janela` **não** mete outro script (a Google avisa "only loaded once");
  - `onerror` → a promessa rejeita com `Error('O Google Maps não carregou.')` e um `importar` seguinte tenta de novo (novo script), como o bootstrap oficial;
  - `versao`, `idioma` e `regiao` são opções com estes padrões; o `nonce` de um `script[nonce]` existente copia-se para o script novo;
  - a chave nunca aparece noutro sítio (o módulo não regista nada; teste com `console` espiado).
- **Mutações mínimas:** dois scripts; sem `loading=async`; `callback` errado; `language` em falta; resolver antes do `__ib__`.
- **Commit:** `CRM: carregador do Google Maps só nas páginas do CRM`

#### [ ] G5 `lib/crm/testes/googleFalso.js` (40 min, sem teste próprio: é apoio dos testes, como o `leafletFalso`)
- **Ficheiro:** `frontend/src/lib/crm/testes/googleFalso.js` (fora do varrimento; `deveVarrer` já exclui `testes/`).
- **Conteúdo** (imita só o que `mapa.js`, `seletor.js` e, na F3, `mostrarRota` usam; comentários a dizer o comportamento real que importa):
  - `googleFalso()` → `{google, registo}`; `registo.{mapas, marcadores, circulos, linhas}`;
  - `google.maps.Map(elemento, opcoes)`: `options`, `addListener(tipo, fn)` → `{remove}`, `fire(tipo, evento)`, `vistas` (`fitBounds(limites, margem)`, `setCenter`, `setZoom`, `panTo`), `getCenter()`/`getZoom()`/`getBounds()` (o zoom começa no `options.zoom`), `setOptions`; `getDiv()`;
  - `google.maps.marker.AdvancedMarkerElement(opcoes)`: propriedades `map`, `position`, `content`, `title`, `gmpDraggable`, `gmpClickable`, `collisionBehavior`, `zIndex`, `element` (o `content`); pôr `map = null` tira-o do `registo`; `addListener('gmp-click' | 'dragstart' | 'drag' | 'dragend', fn)`; `arrastarPara(lat, lng)` lança "o pino não se pode arrastar" sem `gmpDraggable`, senão muda a `position` e dispara os três eventos (como o `MarcadorFalso`); `posicao()` devolve sempre `{lat, lng}` (o verdadeiro pode dar `LatLng` com funções ou um literal: o falso devolve ora um ora outro, alternadamente, para o código ter de tratar os dois);
  - `google.maps.Circle(opcoes)` com `getBounds()` (dos `limitesDoCirculo`) e `setMap`; `google.maps.Polyline(opcoes)` com `setMap`/`getPath`; `google.maps.LatLngBounds` com `extend`, `getSouthWest/NorthEast`, `pontos`; `google.maps.CollisionBehavior = {REQUIRED: 'REQUIRED', OPTIONAL_AND_HIDES_LOWER_PRIORITY: …, REQUIRED_AND_HIDES_OPTIONAL: …}`; `google.maps.event.{addListenerOnce, trigger, clearInstanceListeners}` (o `idle` dispara-se com `mapa.fire('idle')`); `google.maps.importLibrary = async (nome) => google.maps`;
  - `eventoDeToque({lat, lng, placeId})` → `{latLng: {lat: () => lat, lng: () => lng}, placeId, stop() {this.parado = true}, parado: false}`.
- **Commit:** `CRM: Google Maps falso para os testes do mapa`

#### [ ] G6 `lib/crm/mapa.js` sobre o Google Maps (60 min)
- **Ficheiros:** `frontend/src/lib/crm/mapa.js`, `mapa.test.js`.
- **Teste primeiro** (`mapa.test.js` reescrito sobre o `googleFalso` + `domFalso`; dos 43 ficam os dos pinos, nomes, escolher, tocar, enquadrar, centrar, destruir e centro padrão, adaptados; saem os 12 dos mosaicos/atribuição/troca e os 6 do Leaflet verdadeiro; entram os novos). Falha por `criarMapa` ainda chamar `L.map` (`TypeError: L.map is not a function` com `google` no lugar de `L`).
  - `criarMapa({google, documento, elemento, configuracao, aoEscolherLoja?, aoTocarNoMapa?, aoTocarNumLugar?})`: um só `Map` no elemento com as opções exatas da §1 (`mapId` da configuração, `center` do `centro` ou `CENTRO_PADRAO`, `zoom: ZOOM_SEM_LOJAS`); `configuracaoValida` só com `google.chave` e `google.map_id` não vazios (`{google: null}`, `{google: {chave: ''}}`, sem `map_id` → falso); `MENSAGEM_SEM_MAPA` igual e `MENSAGEM_MAPA_NAO_CONFIGURADO` nova (texto exato da §1);
  - **pinos:** um `AdvancedMarkerElement` por loja com coordenadas (sem agrupamento), `position: {lat, lng}`, `title: 'Mercearia da Baixa (Cliente)'` (sem fase conhecida, só o nome), `gmpClickable: true`, `collisionBehavior: google.maps.CollisionBehavior.REQUIRED`, `gmpDraggable` ausente/false; o `content` é um `div` com a classe `classePino(fase)` e dois filhos `span` (`pino__bola` e `etiqueta-loja` com o nome em **texto**: `'<b>x</b>'` fica literal; com o `document` do jsdom, `querySelector('b')` é `null`); `mostrarLojas` substitui os anteriores (`map = null` nos antigos) e ignora lojas sem coordenadas válidas (os mesmos casos de hoje);
  - **escolher:** `gmp-click` no marcador → `aoEscolherLoja(loja, marcador)`; sem `aoEscolherLoja` não há ouvinte;
  - **tocar:** `mapa.fire('click', eventoDeToque({lat, lng}))` → `aoTocarNoMapa({lat, lng})`; com `placeId` → `evento.parado === true`, `aoTocarNumLugar({placeId, lat, lng})` e **`aoTocarNoMapa` não é chamado**; com `placeId` e sem `aoTocarNumLugar`, continua `parado` e `aoTocarNoMapa` recebe o ponto; sem nenhum dos dois, o mapa não fica à escuta;
  - `enquadrar(lojas)`: `fitBounds` com um `LatLngBounds` que contém os pontos e a margem `MARGEM_ENQUADRAR = 40`; depois de `mapa.fire('idle')` com zoom 18 → `setZoom(16)`; com 15 não mexe; sem lojas → `setCenter(centro)` + `setZoom(12)` (e `CENTRO_PADRAO` sem centro válido, lido dos `PADROES` do `definicoes.py` como hoje);
  - `centrarEm(loja)` → `panTo`; `centrarEm(loja, 17)` → `setCenter` + `setZoom(17)`; coordenadas inválidas não mexem;
  - `redimensionar()` → `google.maps.event.trigger(mapa, 'resize')`;
  - `destruir()` → todos os marcadores com `map === null`, `clearInstanceListeners(mapa)` chamado e o elemento sem filhos; um segundo `criarMapa` no mesmo elemento funciona (StrictMode);
  - `pontoDe(valor)` exportado: aceita `{lat, lng}` numérico ou um objeto com funções `lat()`/`lng()` → `{lat, lng}`; o resto → `null`.
- **Mutações mínimas:** `clickableIcons: false`; esquecer o `stop()`; `collisionBehavior` OPTIONAL; `title` sem a fase; limite do zoom desligado; `destruir` sem tirar os marcadores; `gmpClickable` em falta.
- **Commit:** `CRM: mapa das lojas sobre o Google Maps, pinos com nome sempre visível`

#### [ ] G7 Varrimento de segurança para o Google, atribuições sem mosaicos (45 min)
- **Ficheiros:** `frontend/src/lib/crm/seguranca.test.js`, `atribuicoes.js` (+ `atribuicoes.test.js` novo), apagar `mosaicos.js` e `mosaicos.test.js`, apagar `testes/leafletFalso.js` (o `seletor.test.js` ainda o importa: fica vermelho até à G9 — aceite e registado; em alternativa apagar o falso na G9).
- **Teste primeiro** (o detetor é provado com amostras, como hoje). Regras novas, com a amostra que cada uma apanha e o código seguro que deixa passar:
  - **sempre:** `InfoWindow` (`new google.maps.InfoWindow(` e `InfoWindow(`), `setContent(`, e os **canários EEA** da regra 9 do §0 (`displayName`, `formattedAddress`, `shortFormattedAddress`, `addressComponents`, `nationalPhoneNumber`, `internationalPhoneNumber`, `websiteUri`, `fetchFields`, `PlacesService`, `Geocoder(`), comentários incluídos;
  - **`google.maps` e `importLibrary` fora de `lib/crm/{carregadorGoogle,mapa,seletor}.js`:** recusados (um componente só pode passar `window.google`; a amostra `criarMapa({ google: window.google })` passa, `new google.maps.Map(` num componente não);
  - **`content:` fora de `mapa.js`/`seletor.js`:** recusado;
  - **saem** as regras do Leaflet (`bindTooltip`…, `attribution:`, `divIcon` com `html`, `prefix`, `addAttribution/setPrefix`) e os testes que liam o `mapa.js` copiado para outro ficheiro passam a provar o mesmo com `google.maps` e `content:`;
  - as regras de sempre ficam (`dangerouslySetInnerHTML`, `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `.write(`, `tel:` fora do `dom.js`);
  - a lista dos ficheiros exige `lib/crm/carregadorGoogle.js` e deixa de exigir `lib/crm/mosaicos.js`; `testes/googleFalso.js` fica de fora.
  - `atribuicoes.test.js`: `ATRIBUICOES.pesquisa.texto === 'Powered by Geoapify'` com a ligação `https://www.geoapify.com/`; `ATRIBUICOES` **não tem** `geoapify`, `osm` nem `html` em nenhuma entrada (só `texto` e `partes`); as `partes` são congeladas.
- **Implementação:** `atribuicoes.js` fica com `pesquisa` (a F3 junta `ors`); o comentário do topo explica que a atribuição da Google é da própria API e nunca se esconde.
- **Commit:** `CRM: varrimento de segurança para o Google Maps e atribuições sem mosaicos`

#### [ ] G8 `lib/crm/lugarGoogle.js`, o `google_place_id` na localização e nas diferenças (45 min)
- **Ficheiros:** `frontend/src/lib/crm/lugarGoogle.js` (+ teste), `localizacao.js` (+ teste), `diferencas.js` (+ teste), `ficha.js` (`textoLocalizacao`, + teste), `seguranca.test.js` (lista).
- **Teste primeiro.** Falha por `Cannot find module './lugarGoogle'`, por `localizacaoFinal` não devolver `google_place_id` e por `CAMPOS_LOCALIZACAO` ter 4 entradas.
  - **`lugarDoElemento(place)`** → `{id, lat, lng}` com `place.location` como `{lat, lng}` numérico **ou** com funções `lat()`/`lng()`; sem `id` em texto, sem `location` ou com números não finitos → `null`; **canário:** um `place` com mais dez chaves (um nome de negócio, uma morada, um telefone, em chaves que o teste escreve por extenso num objeto literal — o teste pode nomear essas chaves só dentro de `*.test.js`, que está fora do varrimento) devolve um objeto com **exatamente** as três chaves (`Object.keys(...)` igual a `['id', 'lat', 'lng']`).
  - **`criarCartaoLugar({aoMudarVista, aoCarregar})`** → `{vista, abrir(placeId, {reserva}), carregou(place), falhou(), fechar(), destruir()}`; `vista` `{placeId, estado: 'fechado' | 'a_carregar' | 'pronto' | 'erro', mensagem, lugar}` nova e congelada a cada mudança; `abrir('a')` → `a_carregar`; `carregou` com um `place` do id `a` → `pronto`, `lugar = {id, lat, lng}` e `aoCarregar(lugar)`; `abrir('b')` depois de `abrir('a')` e um `carregou` tardio de `a` → ignorado (só o mais recente conta); `falhou()` sem reserva → `erro` com `TEXTO_LUGAR_INDISPONIVEL` e sem `aoCarregar`; `falhou()` com `reserva: {lat, lng}` → `erro` **e** `aoCarregar({id: placeId, lat, lng})`; `fechar()` → `fechado`; nada depois de `destruir()`.
  - **Textos exatos** (uma só linha cada): `TEXTO_PESQUISAR_LUGAR = 'Pesquisar lugar ou morada (Google)'`, `TEXTO_ADICIONAR_COMO_LOJA = 'Adicionar como loja'`, `TEXTO_FECHAR_LUGAR = 'Fechar'`, `TEXTO_A_ABRIR_LUGAR = 'A abrir a ficha do lugar…'`, `TEXTO_LUGAR_INDISPONIVEL = 'Não foi possível abrir a ficha deste lugar — toque no mapa no sítio da loja.'`, `TEXTO_ESCREVA_O_NOME = 'Escreva o nome da loja como quer que apareça no mapa (não se copia da Google).'`, `TEXTO_LUGAR_ESCOLHIDO = 'Pino posto no lugar escolhido — arraste-o até à porta da loja e confirme.'`, `ROTULO_FICHA_LUGAR = 'Ficha do lugar (Google)'`.
  - **`localizacao.js`:** `localizacaoFinal({…, google_place_id: 'ChIJ…'}, false)` → inclui `google_place_id: 'ChIJ…'`; sem ele → `null`; `origemFinal('google', true) === 'pin_manual'`, `origemFinal('google', false) === 'google'`; `podeConfirmar({origem: 'google'})` é verdadeiro; `precisao_m` fica `null` com `google`.
  - **`diferencas.js`:** `CAMPOS_LOCALIZACAO` = `['lat', 'lng', 'origem_coords', 'precisao_m', 'google_place_id']`; mudar só o `google_place_id` manda o bloco inteiro; `''` vai como `null`.
  - **`ficha.js`:** `textoLocalizacao({origem_coords: 'google'}) === 'Pino do lugar escolhido na Google.'`.
- **Mutações mínimas:** `lugarDoElemento` a copiar o objeto inteiro (`{...place}`); um `carregou` tardio a contar; `google_place_id` fora do bloco das diferenças; `origemFinal` a manter `google` depois de arrastar.
- **Commit:** `CRM: regras do cartão do lugar Google e o identificador do lugar na localização`

#### [ ] G9 `lib/crm/seletor.js` sobre o Google (1/2): mapa, pino arrastável e círculo (60 min)
- **Ficheiros:** `frontend/src/lib/crm/seletor.js`, `seletor.test.js`, `gps.js` (só o comentário do `limitesDoCirculo`), `testes/leafletFalso.js` (apagar aqui, se ficou da G7).
- **Teste primeiro** (`seletor.test.js` reescrito sobre o `googleFalso`; dos 83 ficam ≈ 60: estados, dica, aviso, erro, Confirmar, GPS com `getCurrentPosition` falso, círculo, morada sugerida pela inversa, foco, vista nova e congelada, nada depois de destruir, `redimensionar`, textos e os da fábrica; saem os 2 do Leaflet verdadeiro e os ≈ 20 da pesquisa Geoapify, que a G10 substitui pelos do lugar). Falha por `L.map is not a function`.
  - `criarSeletor({google, documento, configuracao, textos?, api?, geolocation?, aoMudar?, aoSugerirMorada?, aoMudarVista?, aoFocar?})` (sai `L`; `aoEscolherMorada` sai na G10 com a pesquisa); `iniciar(elemento, {inicial})` cria o mapa pelo `criarMapa` (um só `Map`; `configuracaoValida` da §1; `google` sem `maps` ou uma configuração inválida → `semMapa()` com `MENSAGEM_SEM_MAPA`; `{google: null}` → `MENSAGEM_MAPA_NAO_CONFIGURADO`);
  - **pino:** um `AdvancedMarkerElement` com `content` = `el(documento, 'div', {classe: 'pino-seletor'})` (sem filhos nem texto), `gmpDraggable: true`, `title: rotulos.pino`, `zIndex: 1000`; `dragend` → a posição nova (pelo `pontoDe`), `arrastado = true`, a morada sugerida fica; `confirmar()` → `gmpDraggable === false`; `alterar()`/`desconfirmar()` → `true` outra vez; tocar no mapa (`eventoDeToque` sem `placeId`) põe/move o pino com `origem: 'pin_manual'` e `google_place_id: null` (não mexe depois de confirmado);
  - **círculo:** `google.maps.Circle` com `ESTILO_CIRCULO = {strokeColor: '#6b2fa3', strokeOpacity: 0.8, strokeWeight: 2, fillColor: '#6b2fa3', fillOpacity: 0.12, clickable: false}` + `center`, `radius: precisao_m`, `map`; sai (`setMap(null)`) quando o pino muda de sítio; `fitBounds` com os `limitesDoCirculo` num `LatLngBounds` e `MARGEM_GPS = 24`, com o limite `ZOOM_GPS` (18) pelo mesmo `idle` do `mapa.js` (função partilhada `limitarZoomDepoisDeEnquadrar(google, mapa, maximo)`, exportada do `mapa.js` e testada lá);
  - `localizacao` confirmada → `{lat, lng, origem_coords, precisao_m, google_place_id}` (`null` nos pinos à mão e no GPS); `inicial` com `google_place_id` e `origem: 'google'` fica no pino até se tocar noutro sítio;
  - `destruir()` tira o pino e o círculo do mapa e chama o `destruir` do mapa.
- **Mutações mínimas:** `gmpDraggable` nunca desligado ao confirmar; o círculo `clickable: true`; um GPS tardio a mover o pino; `google_place_id` a sobreviver a um toque no mapa.
- **Commit:** `CRM: seletor da localização sobre o Google Maps`

#### [ ] G10 `lib/crm/seletor.js` (2/2): lugares Google; sai a pesquisa Geoapify do frontend (60 min)
- **Ficheiros:** `frontend/src/lib/crm/seletor.js` (+ teste), `morada.js` (+ teste), `api.js` (+ teste), apagar `pesquisaMorada.js` e `pesquisaMorada.test.js`; `backend/tests/crm/test_consistencia_frontend.py` (deixa de procurar `MENSAGEM_MORADA_INDISPONIVEL`; continua a conferir `MENSAGEM_MORADA_SUGERIDA_INDISPONIVEL` e o GPS); `seguranca.test.js` (lista).
- **Teste primeiro.** No Jest falha por `seletor.escolherLugar is not a function`; no pytest, a consistência fica vermelha quando a constante sair do `morada.js` (atualizar o pytest na mesma tarefa, pela ordem: primeiro o Jest, depois o pytest).
  - **`escolherLugar(placeId, {reserva?})`** (da pesquisa ou do toque num negócio — o `criarMapa` recebe `aoTocarNumLugar` do seletor e passa-lhe `{placeId, lat, lng}` como `reserva`): a `vista.lugar` passa a `a_carregar` (o `criarCartaoLugar` da G8 vive dentro do seletor); a lista da pesquisa fecha; o pino **ainda não** se move;
  - **`lugarCarregado(place)`** (o componente chama-o em `gmp-load`): `colocar({lat, lng, origem: 'google', google_place_id: id}, {zoom: ZOOM_MORADA})`, a dica passa a `TEXTO_LUGAR_ESCOLHIDO`, pede a morada inversa à Geoapify (`api.moradaInversa(pontoDeBias(ponto))`, com "Morada sugerida: … · Powered by Geoapify" e `aoSugerirMorada`) e `aoFocar('confirmar')`; um `lugarCarregado` de um `placeId` que já não é o mais recente é ignorado; depois de `destruir()` nada acontece;
  - **`lugarFalhou()`**: com `reserva` o pino vai na mesma para lá (origem `google`, com o `google_place_id`) e a `vista.lugar.estado` fica `erro` com `TEXTO_LUGAR_INDISPONIVEL`; sem reserva só a mensagem;
  - **`fecharLugar()`** fecha a ficha e deixa o pino; um toque à mão no mapa fecha a ficha e limpa o `google_place_id`; arrastar mantém-no e passa a origem a `pin_manual` (a `localizacao` confirmada mostra-o);
  - **`vista.pesquisa`** passa a `{ativa: boolean}` (verdadeiro com mapa, falso sem mapa ou sem o `api`? não: a pesquisa Google não depende da `api` — é verdadeira sempre que há mapa); **`limitesDoMapa()`** devolve `mapa.getBounds()` ou `null` antes de haver mapa;
  - **`morada.js`:** saem `criarPesquisaMorada` e `MENSAGEM_MORADA_INDISPONIVEL`; ficam `MENSAGEM_MORADA_SUGERIDA_INDISPONIVEL`, `camposDaMorada`, `camposSugeridos`, `pontoDeBias` (com os testes deles); **`api.js`:** sai `pesquisarMorada` (e a exportação solta); fica `moradaInversa`; o comentário do `obterConfigMapa` descreve a forma nova.
- **Mutações mínimas:** um `lugarCarregado` tardio a mover o pino; `lugarFalhou` com reserva a não pôr o pino; a inversa pedida com o ponto por arredondar; `escolherLugar` a mover o pino antes de carregar.
- **Commit:** `CRM: escolher um lugar Google no seletor põe o pino e sugere a morada pela Geoapify`

### Bloco G4 — Componentes e páginas

> Receita de verificação dos componentes, igual à das T2.25–T2.30: **verificação temporária, não versionada**, em `$LOGS/g.N-verificacao/` (React 19 `act` + `createRoot`, `MemoryRouter`, API falsa, o `googleFalso` injetado em `window.google` e um `carregadorGoogle` trocado por `jest.mock` para não meter scripts), com mutações; **ESLint do CRA** (receita da T1.13); **browser local** só na G21; cada ficheiro novo entra na lista do `seguranca.test.js`. Para os elementos `gmp-*` na verificação temporária: `customElements.define('gmp-place-details-compact', …)` e `'gmp-basic-place-autocomplete'` falsos que disparam `gmp-load`/`gmp-error`/`gmp-select` com um `place` fixo.

#### [ ] G11 `crm.css` do mapa Google, dos pinos e do cartão do lugar (45 min)
- **Ficheiros:** `frontend/src/lib/crm/css.test.js` (escrito primeiro), `frontend/src/components/crm/crm.css`.
- **`css.test.js` primeiro.** Deixa de ler o `leaflet.css` e de exigir regras `.leaflet-*`, o `mix-blend-mode` e os 44 px dos botões de zoom (são da Google). Falha por faltarem:
  - `.pino` com `width: 44px`, `height: 44px`, `position: relative`, `transform: translateY(50%)` (o marcador avançado ancora o fundo-centro do conteúdo no ponto: assim a bola fica centrada nas coordenadas) e `--cor-pino: #cfcfcf; --contorno-pino: #fff;`;
  - `.pino__bola` absoluta, 20 × 20 px ao centro, `background: var(--cor-pino)`, `border: 3px solid var(--contorno-pino)`; as cores de `.pino--<fase>` iguais às de `FASES` (teste que fica) e só fases que existem;
  - `.etiqueta-loja` **absoluta à direita** (`left: 32px`, `top: 50%`, `transform: translateY(-50%)`), `pointer-events: none` (os toques vão para o pino ou para o mapa, como a etiqueta do Leaflet), `width: max-content`, `max-width: 16rem`, `white-space: normal`, sem reticências, cores fixas (sem `var(`/`currentcolor`/`inherit`);
  - `.pino-seletor` com `width: 44px`, `height: 38px` e a gota (`::before` com `background: ESTILO_CIRCULO.strokeColor`, `border: 3px solid #fff`, `border-radius: 50% 50% 50% 0`, `rotate(-45deg)`; `::after` o ponto branco) com a ponta no fundo ao centro; `.crm-seletor[data-estado="confirmado"] .pino-seletor::before` com `#4f1f7d`;
  - `.crm-mapa` absoluto, `inset: 0`, `isolation: isolate`; `.crm-mapa__vista` relativa com `min-height ≤ 8rem`; `.crm-seletor__vista` com `height: clamp(16rem, 50vh, 28rem)`;
  - `.crm-cartao-lugar` com `max-width` e `.crm-cartao-lugar gmp-place-details-compact { width: 100%; }`;
  - **guardas da atribuição:** nenhum seletor do ficheiro começa por `.gm-` nem contém `.gm-`; nenhuma regra cujo seletor contenha `gmp-` tem `display: none`, `visibility: hidden` ou `opacity: 0`.
- **Implementação:** reescrever o `crm.css` (o comentário do topo explica a ancoragem e a atribuição).
- **Commit:** `CRM: estilos do mapa Google, dos pinos e do cartão do lugar`

#### [ ] G12 `MapaLojas` sobre o carregador e o `CartaoLugar` (60 min)
- **Ficheiros:** `frontend/src/components/crm/MapaLojas.js`, `components/crm/CartaoLugar.js` (novo), `seguranca.test.js` (lista).
- **`MapaLojas`:** mesmas `props` + `aoTocarNumLugar`. No `useEffect`: `const { importar } = prepararGoogleMaps({ janela: window, documento: document, chave: configuracao.google.chave }); await importar('maps'); await importar('marker'); await importar('places');` (com uma `let ativo` para o cleanup); depois `criarMapa({ google: window.google, documento: document, elemento, configuracao, … })`; qualquer falha (carregador, `criarMapa`) → `console.error('[crm] o mapa não foi criado:', erro)` e `aoFalhar()`; `aoPronto(criado)`; `ResizeObserver` → `redimensionar()`; cleanup `destruir()`. Sem `import 'leaflet'` nem `leaflet.css`. A `configuracao` tem de ser válida (a página já o garante).
- **`CartaoLugar`** (`{placeId, estado, mensagem, acao?: {texto, aoTocar}, aoCarregar, aoFalhar, aoFechar, refTitulo}`): `<section className="crm-cartao-lugar" role="region" aria-label={ROTULO_FICHA_LUGAR} data-estado={estado}>`; só desenha o elemento se `window.customElements?.get('gmp-place-details-compact')` existir (senão `IndicadorCrm` com `TEXTO_A_ABRIR_LUGAR`); `<gmp-place-details-compact ref={el} orientation="horizontal" truncation-preferred key={placeId}>` com `<gmp-place-details-place-request place={placeId} />`; num `useEffect`, `addEventListener('gmp-load', () => aoCarregar(lugarDoElemento(el.current.place)))` e `'gmp-error'` → `aoFalhar()`; a mensagem de erro com `role="alert"`; os botões "Fechar" (44 px, `refTitulo` recebe o foco ao abrir) e, com `acao`, o botão com `acao.texto` e a dica `TEXTO_ESCREVA_O_NOME`. Nenhum CSS nem código toca na atribuição embutida. O componente **nunca** lê outra propriedade do `place` (o varrimento recusa os canários; a verificação temporária prova que `aoCarregar` recebe só `{id, lat, lng}`).
- **Verificar:** verificação temporária (StrictMode: um só mapa, um só script; a falha do carregador chama `aoFalhar`; o `gmp-load` falso leva a `aoCarregar` com as três chaves; mutações).
- **Commit:** `CRM: componente do mapa sobre o Google Maps e cartão do lugar`

#### [ ] G13 `SeletorLocalizacao` e `PesquisaLugar` (60 min)
- **Ficheiros:** `frontend/src/components/crm/SeletorLocalizacao.js`, `components/crm/PesquisaLugar.js` (novo), apagar `components/crm/PesquisaMorada.js`; `seguranca.test.js` (lista); `pages/crm/DefinicoesFabrica.js` só o comentário do `crm.css`/Leaflet, se preciso para o build (a página em si muda na G16).
- **`SeletorLocalizacao`:** o mesmo molde (o seletor num `useEffect` com `destruir()` no cleanup, as funções do ecrã num `ref`, `ResizeObserver`, `forwardRef`), mas o `iniciar` corre depois do carregador (`importar('maps')`, `'marker'`, `'places'`), como no `MapaLojas`; `configuracao === undefined` = a chegar; `null`/inválida ou `google: null` → o seletor diz que não há mapa (as duas mensagens); nova `prop` **`aoPronto(seletor | null)`** (a nova loja precisa de saber quando pode chamar `escolherLugar`); pela `ref` entram `escolherLugar`, `lugarCarregado`, `lugarFalhou`, `fecharLugar`, `limitesDoMapa`. Desenha: a `PesquisaLugar` (com `vista.pesquisa.ativa`), o `CartaoLugar` por baixo (sem `acao`; `aoCarregar` → `seletor.lugarCarregado`, `aoFalhar` → `lugarFalhou`, `aoFechar` → `fecharLugar`), o bloco do GPS como hoje, a dica (`TEXTO_LUGAR_ESCOLHIDO` quando o pino veio de um lugar), o mapa e os botões. A `Partes` (texto + ligação) passa para `lugarGoogle.js`? Não: para `components/crm/Partes.js` (o "Powered by Geoapify" da morada sugerida continua a precisar dela).
- **`PesquisaLugar`** (`{id, ativa, obterLimites, aoEscolher}`): `<Label htmlFor>` com `TEXTO_PESQUISAR_LUGAR`; `<gmp-basic-place-autocomplete ref id>` só se o elemento estiver definido (`customElements.get`); num `useEffect`: `el.includedRegionCodes = ['pt']`; `focus` → `el.locationBias = obterLimites() ?? undefined`; `gmp-select` → `aoEscolher(evento.place?.id)` só se for texto não vazio. Sem atribuição nossa (a do elemento é da Google). Desativado (`aria-disabled`) sem `ativa`.
- **Verificar:** verificação temporária (o `gmp-select` falso chega a `escolherLugar`; o `gmp-load` põe o pino e pede a inversa; GPS a 20 m e 120 m como na T2.26; mutações).
- **Commit:** `CRM: pesquisa de lugares Google e cartão do lugar no seletor da localização`

#### [ ] G14 Página do mapa: tocar num negócio → ficha → "Adicionar como loja" (60 min)
- **Ficheiros:** `frontend/src/pages/crm/CrmMapa.js`, `lib/crm/ecraMapa.js` (+ teste), `components/crm/CartaoLoja.js` (só se precisar de partilhar o contentor).
- **Teste primeiro** (`ecraMapa.test.js`): falha por `lugarDoToque`/`destinoNovaLojaDoLugar` não existirem.
  - `lugarDoToque({placeId, lat, lng})` → `{id, lat, lng}` ou `null` (id texto não vazio; coordenadas finitas);
  - `destinoNovaLojaDoLugar(base, lugar)` → `{caminho: `${base}/lojas/nova`, estado: {lugar: {id, lat, lng}}}`;
  - `configuracaoDoMapa(configuracao)` → `'a_chegar' | 'nao_configurado' | 'invalida' | 'ok'` (decide entre `MENSAGEM_MAPA_NAO_CONFIGURADO` e `MENSAGEM_SEM_MAPA`).
- **Página:** estado `lugar` (`{id, lat, lng, estado, mensagem}` do `criarCartaoLugar`, criado na página) exclusivo com `escolhida` (abrir um fecha o outro); `aoTocarNumLugar` → `lugar.abrir(id, {reserva})`; o `CartaoLugar` no mesmo sítio do `CartaoLoja` (o mapa encolhe, `redimensionar()`, `centrarEm({lat, lng})`, o foco no "Fechar"); `acao` = `{texto: TEXTO_ADICIONAR_COMO_LOJA, aoTocar: () => navigate(destino.caminho, {state: destino.estado})}` (fica ativa mesmo com a ficha em `erro`: a `reserva` chega); tocar no mapa ou o Escape fecham (o foco volta ao mapa); a mensagem sem mapa distingue "não configurado" de "não carregou"; `aoFalhar` do `MapaLojas` → `MENSAGEM_SEM_MAPA`.
- **Verificar:** verificação temporária (um toque com `placeId` abre o cartão do lugar e fecha o da loja; "Adicionar como loja" navega com o `state` certo; o balão da Google nunca é criado — o `googleFalso` não tem `InfoWindow`; mutações).
- **Commit:** `CRM: tocar num negócio no mapa abre a ficha Google com "Adicionar como loja"`

#### [ ] G15 Nova loja a partir de um lugar, com o nome escrito pela pessoa (50 min)
- **Ficheiros:** `frontend/src/pages/crm/CrmLojaNova.js`, `lib/crm/lojaNova.js` (+ teste).
- **Teste primeiro** (`lojaNova.test.js`): falha por `lugarDoEstado` não existir e por a `vista` não ter `dicaNome`.
  - `lugarDoEstado(state)` → `{id, lat, lng}` ou `null` (`state.lugar` com id texto e coordenadas finitas; `null`, `{}`, strings → `null`);
  - `criarLojaNova(...)`: `vista.dicaNome` = `TEXTO_ESCREVA_O_NOME` quando `localizacao?.google_place_id` é texto, senão `null`; `corpoLojaNova` já leva o bloco inteiro (`google_place_id` incluído) — teste explícito; `estadoGuardar` não muda.
- **Página:** lê `lugarDoEstado(state)` uma vez; quando o seletor fica pronto (`aoPronto`), chama `seletor.current.escolherLugar(lugar.id, {reserva: {lat, lng}})` e limpa o `state` (`navigate({pathname}, {replace: true, state: null})`); a dica `vista.dicaNome` por baixo do campo "Nome" (`aria-describedby`); o resto igual (422 da localização solta o pino; 409 duplicado; sucesso → mapa com "Loja guardada").
- **Verificar:** verificação temporária (o `state` leva ao `escolherLugar` uma só vez, também no StrictMode; sem `state` nada acontece; a dica aparece só com `google_place_id`; mutações).
- **Commit:** `CRM: nova loja a partir de um lugar Google, com o nome escrito pela pessoa`

#### [ ] G16 Ficha ("Corrigir localização") e ponto da fábrica sobre o mapa Google (40 min)
- **Ficheiros:** `frontend/src/pages/crm/CrmLoja.js`, `lib/crm/ficha.js` (+ teste), `lib/crm/fabrica.js` (+ teste), `pages/crm/DefinicoesFabrica.js`, `pages/crm/rotasCrm.js` (só o comentário "o Leaflet, na F2" → "o Google Maps").
- **Teste primeiro.** `ficha.test.js`: `correcao.inicial` leva `google_place_id: original.google_place_id` (e `origem: 'google'` quando é o caso); `corpoAlteracao` manda o bloco com o `google_place_id` quando a localização confirmada o traz ou o tira (`null`); o resumo da localização usa o `textoLocalizacao` da G8. `fabrica.test.js`: `mudarPonto` ignora `google_place_id` e `origem_coords` (o `corpoFabrica` só leva `fabrica_lat`/`fabrica_lng`) — teste explícito com uma localização vinda de um lugar.
- **Páginas:** o `SeletorLocalizacao` novo nos dois sítios, sem GPS na fábrica; na ficha, `aoSugerirMorada` como hoje (o `aoEscolherMorada` deixa de existir: a morada vem sempre pela inversa); "Cancelar correção"/"Cancelar a mudança do ponto" desfazem a morada sugerida como hoje.
- **Verificar:** verificação temporária (a correção com `inicial` de um lugar mostra o pino e, ao arrastar, manda `pin_manual` com o mesmo `google_place_id`; a fábrica não manda `google_place_id`; mutações).
- **Commit:** `CRM: corrigir a localização na ficha e o ponto da fábrica sobre o mapa Google`

#### [ ] G17 Backend: a Geoapify fica só para a morada inversa (45 min)
- **Ficheiros:** `backend/crm/morada.py`, `backend/crm/servicos/geoapify.py`, testes `test_morada.py`, `test_geoapify.py`, `test_protecao_rotas.py`.
- **Teste primeiro.** `test_protecao_rotas.py`: sai a linha `("GET", "/api/crm/morada/pesquisa")` (o teste que exige que cada rota do router esteja classificada fica vermelho enquanto a rota existir); `test_morada.py`: saem os casos da pesquisa (≈ metade) e entra um que prova que `GET /api/crm/morada/pesquisa` dá 404 (o "Not Found" do FastAPI) com sessão; `test_geoapify.py`: sai `url_pesquisa`/`LIMITE_PESQUISA` (ficam `url_inversa`, `normalizar_autocomplete` — renomear **não**: o `normalizar_inversa` usa-o e a docstring diz porquê —, `normalizar_inversa`, o cliente e os registos sem chave).
- **Implementação:** `morada.py` sem `pesquisa`, `texto_da_pesquisa`, `bias`, `TEXTO_MINIMO/MAXIMO`, `MENSAGEM_TEXTO_*` e `PESQUISA_INDISPONIVEL` (a docstring passa a descrever só a inversa); `geoapify.py` sem `url_pesquisa` e `LIMITE_PESQUISA` (a fixture `autocomplete-rua-augusta.json` fica, porque o normalizador é o mesmo). `INVERSA_INDISPONIVEL` e a consistência com o `morada.js` continuam.
- **Mutações mínimas:** deixar a rota registada; uma chamada a `url_pesquisa` esquecida.
- **Commit:** `CRM: a Geoapify fica só para a morada sugerida de um ponto`

#### [ ] G18 Política de privacidade: Google Maps e os termos da Google (30 min)
- **Ficheiros:** `frontend/src/pages/PrivacyPolicy.js` (**partilhado**), `lib/crm/privacidade.test.js`.
- **Teste primeiro.** `privacidade.test.js` falha por faltar o texto:
  - a §4 "Partilha de dados" diz que, no CRM, o mapa é o Google Maps (Google Ireland Limited): o browser pede-lhe o mapa, a pesquisa de lugares e as fichas dos lugares, dando a conhecer o endereço IP, como em qualquer site; a morada sugerida de um ponto vem da Geoapify (dados OpenStreetMap), a quem o servidor só envia pontos do mapa, sem dados pessoais;
  - a secção 8 diz que o CRM inclui funcionalidades e conteúdos do Google Maps, sujeitos aos Termos de Serviço adicionais do Google Maps e à Política de Privacidade da Google, com as duas ligações exatas (`https://maps.google.com/help/terms_maps/` e `https://policies.google.com/privacy`, lidas do `href`); que o nome e o telefone de uma loja são sempre escritos pelo membro e nunca copiados da Google, guardando-se só o identificador do lugar (place ID) e o pino confirmado; "Powered by Geoapify" junto à morada sugerida;
  - a página **não** menciona o Leaflet nem o OpenMapTiles; o GPS e a data continuam como hoje.
- **Implementação:** `git diff --stat` ≈ +9/−6, só nesse ficheiro; o comentário JSX para o dono rever fica (dossiê §14, ponto 7).
- **Commit:** `CRM: política de privacidade nomeia o Google Maps e os termos da Google`

#### [ ] G19 Sai o Leaflet (20 min)
- **Ficheiros:** `frontend/package.json`, `frontend/yarn.lock` (**partilhados**; só este commit).
- **Antes:** o inventário do §5 tem de dar vazio em `frontend/src` (código, testes, CSS e comentários). Se não der, corrigir na tarefa a que pertence, não aqui.
- **Comando:** `cd "$RAIZ/frontend" && corepack yarn remove leaflet > "$LOGS/g19-yarn.log" 2>&1` (segundo plano se demorar); `git diff --stat` tem de mostrar `package.json` −1 e `yarn.lock` ≈ −5, nada mais; se o yarn reescrever outras linhas do lockfile, **parar**, repor com `git checkout -- frontend/yarn.lock` e perguntar.
- **Verificar:** Jest de `src/lib/crm` verde (nada importa o `leaflet`); `ls "$RAIZ/frontend/node_modules/leaflet"` dá "não existe".
- **Commit:** `CRM: retira o Leaflet`

#### [ ] G20 Dossiê e plano da F3 atualizados (45 min)
- **Ficheiros:** `CRM_PORTING_GUIDE.md`, `docs/superpowers/plans/2026-10-11-crm-f3-planear-rota.md`.
- **Dossiê:** §0 regra 9 (Google em vez de Leaflet; canários EEA), §2.1 (o Google não corre no jsdom: `googleFalso`), §5.15 (as proibições da adenda §2), §7 (os ecrãs e os módulos: `carregadorGoogle`, `lugarGoogle`, `mapa`, `seletor`, `CartaoLugar`, `PesquisaLugar`; saem `mosaicos`, `pesquisaMorada`, `PesquisaMorada`; a tabela das atribuições), §8 (Google Maps Platform: chave do navegador, Map ID, quotas, UI Kit; Geoapify só inversa; a pesquisa sai), §9 (`CRM_GOOGLE_CHAVE_NAVEGADOR`, `CRM_GOOGLE_MAP_ID`; sai `CRM_GEOAPIFY_CHAVE_MOSAICOS`), §12.3 (as linhas locais com a Demo Key, só nomes), §13 (contagens), §14 (pontos novos: consola Google e Termos EEA; quotas e orçamento; `rh.lisbonb.com` nos referrers; o banner do UI Kit no dia; a decisão dos 30 dias; a redação da privacidade; apagar `CRM_GEOAPIFY_CHAVE_MOSAICOS` do `.env` do servidor; os pontos 3 e 4 antigos passam a "só a chave do servidor"/"resolvido pelo novo ponto").
- **Plano da F3:** acrescentar no fim um bloco **"Correções obrigatórias (mapa Google, 2026-10-14)"** com as linhas do §7 deste plano, uma por tarefa (T3.26, T3.33, T3.36, T3.38, T3.39, T3.43, a receita F3e e as duas correções antigas que deixam de se aplicar), e, no §0 regra 9 e no §1 "Mapa do planeador", uma nota a apontar para esse bloco. Não se reescrevem as tarefas.
- **Commit:** `CRM: dossiê e plano da F3 atualizados para o mapa Google`

### Bloco G5 — Fecho

#### [ ] G21 Fecho do mapa Google com pré-visualização local (60 min)
- **Suites:** `pytest tests/crm` verde; `test_mongo_local.py` com a variável, verde; a suite completa em segundo plano com `failed` igual ao de partida (0) e `skipped` igual ao de partida; `grep -rn "asyncio.run(" backend/tests/crm` vazio; Jest `src/lib` verde; ESLint do CRA nos ficheiros do CRM alterados: 0 problemas.
- **Build** (segundo plano): sem erros; `grep -l "maps.googleapis.com" "$LOGS/build/static/js/"*.js` mostra **só** os *chunks* das páginas do CRM (nunca o `main.*.js`); `grep -c "leaflet" "$LOGS/build/static/js/"*.js "$LOGS/build/static/css/"*.css` dá 0 em todos.
- **Pré-visualização:** parar a anterior (dossiê §12.6); conferir `grep -c "^CRM_GOOGLE" "$RAIZ/backend/.env.local"` (2 = o dono pôs a Demo Key; 0 = sem chave: usar o Maps JS de teste); arrancar o backend (8001) e o frontend (3000) em segundo plano.
- **Aceitação (§9) no browser local** (`$LOGS/g21_aceitacao.py`, Playwright sem janela, computador 1280 × 800 claro e telemóvel 375 × 812 escuro, cópia `lisbonb_crm_g21_local` sem palavras-passe apagada no fim, pedidos ao backend reais com as contas de demonstração do seed — as palavras-passe nunca se imprimem): com a Demo Key, contra a Google verdadeira (poucos carregamentos: contam na quota diária da Demo Key); sem ela, com `page.route('https://maps.googleapis.com/maps/api/js*', …)` a servir `$LOGS/g-verificacao/maps-teste.js` (a mesma superfície do `googleFalso`, mais os elementos `gmp-*` que disparam `gmp-load`/`gmp-select` com um lugar fixo em Lisboa). Nunca com a chave de produção.
- **Dossiê §13:** as contagens e os registos.
- **Commit:** só se houver correções ou dossiê, `CRM: fecho do mapa Google verificado em local`. **Nada sai do Mac.**

#### [ ] G22 [DONO] Publicação e depois (sem ação dos agentes)
Avisar o Matheus (`.env.example`, `PrivacyPolicy.js`, `package.json`/`yarn.lock`); pôr `CRM_GOOGLE_CHAVE_NAVEGADOR` e `CRM_GOOGLE_MAP_ID` no `backend/.env` do servidor e apagar a linha `CRM_GEOAPIFY_CHAVE_MOSAICOS`; aprovar a redação da privacidade; ver o banner do UI Kit; autorizar a junção ao `main` e o `deploy.sh`; experimentar no telemóvel (tocar num negócio, "Adicionar como loja", "Estou nesta loja"); uma semana depois, ver na consola o uso das três SKUs e ajustar os tetos.

#### [ ] Revisão do mapa Google (3 revisores só de leitura)
- Fidelidade à adenda (EEA: o que se guarda e o que nunca se lê), segurança (chave só por `/config`; canários; atribuição intacta) e o encaixe com a F3b (§7). Os achados entram como correções, com vermelho, verde e mutações, no molde das revisões da F2.

---

## 7. Como mudam as tarefas da F3b (T3.26–T3.43), a aplicar na G20 como correções do plano da F3

| Tarefa da F3 | O que dizia | O que passa a ser |
|---|---|---|
| §0 regra 9 e §1 "Mapa do planeador" | Leaflet, `divIcon` sem `html`, número acrescentado no `add`, `L.polyline` | `google.maps` só em `lib/crm/{carregadorGoogle,mapa,seletor}.js`; pinos numerados = `AdvancedMarkerElement` com `content` montado à partida com `el()` (`div.pino-paragem.pino--<fase>` + `span.pino-paragem__numero` com o número em texto + a etiqueta com o nome), `title` "3. Café X", `zIndex` em vez de `zIndexOffset`, `gmp-click` para escolher a paragem; linha = `new google.maps.Polyline({path: [{lat, lng}…], strokeColor: '#6b2fa3', strokeWeight: 4, strokeOpacity: 0.9, clickable: false, map})`; a "antiga" com `strokeOpacity: 0` e `icons: [{icon: {path: 'M 0,-1 0,1', strokeOpacity: 0.6, scale: 3}, offset: '0', repeat: '14px'}]`; extremos iguais aos de hoje; `enquadrarRota` com `LatLngBounds` e o mesmo limite de zoom por `idle` |
| T3.26 | `polilinha.js` devolve pares | Igual; o `mapa.js` converte para `{lat, lng}`. Entra `TEXTO_ROTA_DE_TERCEIROS = 'Routing provided by openrouteservice'` ao lado de `ATRIBUICOES.ors` |
| T3.33 | `testes/leafletFalso.js` com `polyline` e `getElement` | `testes/googleFalso.js` já tem `Polyline` e `LatLngBounds` (G5); o teste verifica as opções exatas da linha e o `content` dos pinos (o número em texto, `querySelector('b')` nulo) |
| T3.36 (`css.test.js` e `crm.css`) | `.crm-linha-rota` com traço roxo e `--antiga` tracejada | A linha não tem CSS (as opções vão no `Polyline`, provadas no `mapa.test.js`); ficam `.pino-paragem__numero` (cor fixa legível), `.pino-paragem--aviso`, `.crm-mapa--planeador .pino` esbatido, `.crm-pega` e `.crm-planeador` como estão |
| T3.38 | Rodapé com a atribuição do ORS | Antes da linha (e no resumo da rota) a frase `TEXTO_ROTA_DE_TERCEIROS` (Termos Específicos EEA §A.4.3) e a atribuição do ORS **num bloco próprio do painel**, nunca sobre o mapa nem junto da atribuição da Google (§A.2) |
| T3.39 | "um toque numa loja esbatida → cartão pequeno"; "Toque no mapa no ponto de início" | Iguais. O `MapaLojas` do planeador **não** recebe `aoTocarNumLugar`: um toque num negócio da Google conta como toque no mapa (o `stop()` continua a esconder o balão) |
| T3.43 | o `main` sem `leaflet-container` | o `main.*.js` sem `maps.googleapis.com`; o *chunk* do planeador com ele; `leaflet` em lado nenhum |
| Receita F3e (T3.36, T3.38) | Leaflet verdadeiro no jsdom; polyfill de `createSVGRect` | `googleFalso` em `window.google` + `carregadorGoogle` trocado por `jest.mock`; no browser, a Demo Key ou o `maps-teste.js` (G21). O polyfill deixa de ser preciso |
| Correção "Receita F3e… `L.polyline` verdadeiro rebenta" | — | Deixa de se aplicar |
| Correção "T3.32 / T3.38 (recálculo e pinos do mapa)" | `clearLayers` e recriar os pinos | Continua a valer: `mostrarLojas` tira os marcadores (`map = null`) e recria; a identidade de `lojasForaDaRota` mantém-se como lá está escrito |

---

## 8. Fora deste plano (YAGNI) e ganchos deixados
- **Fica para depois:** o proxy de Place Details (New) `id,location` e a tarefa dos 30 dias (adenda §2.3, opção B); "Ver na Google" no cartão da loja (reabrir a ficha pelo `google_place_id` guardado); "já existe uma loja com este negócio" (índice em `google_place_id`); o plano B sem UI Kit; um estilo próprio do Map ID; o mapa vetorial.
- **Ganchos:** `origem_coords: 'google'` + `atualizado_em` já chegam para a opção B; o `content` dos pinos tem lugar para os ícones de alerta da F5 (um terceiro `span`); `lugarDoElemento` é o único sítio que lê um `place`.

---

## 9. Listas de aceitação (em local, G21)

- [ ] Mapa: fundo Google com os negócios à vista; pinos das lojas com a cor da fase e o nome sempre visível nos zooms 6 e 19, sem agrupamento; a atribuição da Google e a ligação aos termos no canto, sem nenhuma regra nossa a tapá-las; os botões de zoom em português.
- [ ] Tocar num negócio: o balão da Google não aparece; abre a ficha compacta (UI Kit) no lugar do cartão da loja, com "Fechar" e "Adicionar como loja"; o Escape fecha; tocar no mapa fecha.
- [ ] "Adicionar como loja": o ecrã "Nova loja" abre com a ficha à vista, o pino solto no lugar, "Morada sugerida: … · Powered by Geoapify" a preencher os campos vazios, a dica por baixo do "Nome", o nome vazio; confirmar sem arrastar grava `origem_coords: google` com `google_place_id`; arrastar grava `pin_manual` com o mesmo `google_place_id`.
- [ ] Pesquisa: "Pesquisar lugar ou morada (Google)" só com resultados de Portugal; escolher põe o pino e abre a ficha; o campo não existe sem mapa.
- [ ] "Estou nesta loja": GPS a 20 m → círculo, `gps`, morada sugerida; a 120 m → "Localização imprecisa — ajuste o pino" e Confirmar só depois de arrastar; sem `google_place_id`.
- [ ] Ficha: "Corrigir localização" com o pino no sítio guardado; o texto da origem `google`; a fábrica sem GPS e sem `google_place_id`.
- [ ] Sem chave no `/config`: "Mapa não configurado — peça ao administrador para configurar a chave Google."; com a Google a falhar: "Não foi possível carregar o mapa — recarregue a página."; o resto do CRM funciona.
- [ ] `GET /api/crm/config` só para o escritório; nem a chave nem o Map ID nos registos; `GET /morada/pesquisa` dá 404; `GET /morada/inversa` igual.
- [ ] Nenhum `leaflet` no código nem no build; `maps.googleapis.com` só nos *chunks* do CRM; o `seguranca.test.js` com os canários EEA verde; o `css.test.js` sem `.gm-` e sem `gmp-*` escondidos.
- [ ] Nada foi enviado ao GitHub, ao VPS, ao Atlas nem à Google com uma chave que não a Demo Key do dono.

---

## 10. Riscos e mitigação

| Risco | Mitigação |
|---|---|
| O Google Maps não corre no jsdom (sem WebGL, sem rede) | `googleFalso` para o Jest; verificação temporária com `window.google` falso; no browser, a Demo Key ou o `maps-teste.js` |
| Elementos `gmp-*` no React 19 (propriedades vs. atributos; existem só depois de `importar('places')`) | Propriedades complexas por `ref` em `useEffect`; os componentes só os desenham quando `customElements.get(...)` existe; `key={placeId}` recria a ficha por lugar |
| Ancoragem do `content` (fundo-centro) deixa a bola 22 px acima do ponto | `transform: translateY(50%)` no `.pino` (G11), medido no browser na G21 (o pino de uma loja do seed sobre a morada conhecida) |
| `gmp-click` com o teclado | Verificar na G21 que Enter/Espaço no marcador escolhem a loja; se não, ouvir `keydown` no `content` como hoje (o `googleFalso` já dispara os dois) |
| O `click` do mapa com `placeId` só existe para negócios **com ícone** | Documentado na adenda; a pesquisa cobre os outros |
| Quota diária esgotada / referrer errado → `MENSAGEM_SEM_MAPA` | Tetos folgados; a mensagem; o `.env.example` e o dossiê §14 explicam os referrers (incluindo `rh.lisbonb.com`) |
| O `/config` muda antes dos ecrãs (regra 15 do §0) | Ordem fechada; a pré-visualização só volta na G21 |
| Dois `Map` no mesmo elemento com o `StrictMode` | `destruir()` esvazia o elemento e tira ouvintes; verificado na verificação temporária |
| Banner "Experimental" do UI Kit no dia | [DONO] G1/G22; plano B na adenda §4 (não construído) |
| A chave do navegador é pública | Restrição por referrer e API + quotas; só por `/config` a membros; teste do registo |
| `yarn remove` a reescrever o lockfile | G19 isolada, diff contado, parar se não bater |
| Uma CSP futura no portal | Hoje não há; o carregador copia o `nonce`; a lista de domínios na adenda §4 |

---

## 11. Armadilhas (Google Maps, referência rápida)
- `AdvancedMarkerElement.position` pode ser um `LatLng` (com `lat()`/`lng()` como funções) ou um literal `{lat, lng}`: usar sempre `pontoDe()` do `mapa.js`.
- Sem `mapId` os marcadores avançados não aparecem (aviso na consola, sem erro): `configuracaoValida` exige-o.
- O `click` do mapa com `placeId` chega como `IconMouseEvent`; sem `stop()` a Google abre o balão por omissão (HTML da Google ao lado do mapa — recusado pela regra 9).
- `fitBounds` não aceita `maxZoom`: limitar o zoom num `idle` único (`limitarZoomDepoisDeEnquadrar`).
- `google.maps.event.trigger(mapa, 'resize')` é inofensivo nas versões atuais (o mapa mede-se sozinho); fica pela interface.
- Os elementos do UI Kit só existem depois de `importar('places')`; o `gmp-load` dispara uma vez por `place`; `el.place.location` segue a mesma regra do `LatLng`.
- O Jest do CRA corre com `resetMocks`: criar o `googleFalso` dentro de cada teste.
- A Demo Key tem limite diário por API e **pára** o mapa quando o atinge: na G21, poucas aberturas.

### Critical Files for Implementation
- /Users/brucesilva/pasta sem título/RH/frontend/src/lib/crm/mapa.js
- /Users/brucesilva/pasta sem título/RH/frontend/src/lib/crm/seletor.js
- /Users/brucesilva/pasta sem título/RH/frontend/src/components/crm/SeletorLocalizacao.js
- /Users/brucesilva/pasta sem título/RH/backend/crm/config_mapa.py
- /Users/brucesilva/pasta sem título/RH/backend/crm/dominio/validador_loja.py

---

## Correções obrigatórias (revisão por críticos — por fazer)

Estas correções **prevalecem** sobre o texto das tarefas. Aplicar as que referem a tarefa antes de a começar.

| Tarefa | Gravidade | Problema | Correção |
|---|---|---|---|
| — | — | (vazio até à revisão deste plano por críticos só de leitura) | — |


---

## Correções obrigatórias

(por preencher: a revisão por críticos corre antes de começar a construção)
