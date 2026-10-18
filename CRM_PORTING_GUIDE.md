# CRM Purple House · Dossiê de portagem para o portal Gestão Lisbonb

> **Para o Claude (ou outro programador) que vai construir o CRM dentro do portal:** este documento descreve
> o CRM da fábrica **Purple House** e o caminho para o reescrever como **módulo nativo do portal Gestão Lisbonb**
> (FastAPI + MongoDB + React, este repositório). O CRM autónomo (PHP + MariaDB) está congelado em
> `/Users/brucesilva/purple-house-crm` (etiqueta `referencia-standalone`, commit `0bda625`) como **referência de
> comportamento**: não se copia tal e qual; portam-se as regras e os cenários de teste. Molde deste dossiê:
> `/Users/brucesilva/pasta sem título/gestao-lisbonb-financeiro/PORTING_GUIDE.md`.

- **Data:** 2026-10-10 · **Ramo:** `crm-purple-house` (só local; nada foi enviado ao GitHub, ao VPS nem ao Atlas) · **Alterações do dono (2026-10-13):** no ramo local `crm-publicacao-1`, criado a partir de `d195610` (fim da F2); ver §13.
- **Fontes, por ordem de prevalência:**
  1. Plano `docs/superpowers/plans/2026-10-10-crm-f0-f1-f2.md`, **incluindo a tabela "Correções obrigatórias"** no fim (prevalece sobre o texto das tarefas);
  2. Desenho aprovado `docs/superpowers/specs/2026-10-09-crm-purple-house-no-portal-design.md`;
  3. Regras de negócio `docs/superpowers/specs/2026-10-02-crm-purple-house-desenho-original.md` (§4, §6–§9);
  4. CRM autónomo `/Users/brucesilva/purple-house-crm` (código e testes).
- Este dossiê é o **mapa**. Quanto à ordem e à forma das tarefas manda o plano (com as correções); quanto ao comportamento, o desenho e o código de referência.

---

## 0. Como usar este dossiê

1. Ler a **§1** (o que é) e a **§3** (modelo de dados): é o esqueleto.
2. A **§5** (regras de negócio) é o **coração**: portar fielmente, com os cenários do PHPUnit e do `node:test` do CRM autónomo.
3. **§4** e **§6**: quem entra e por que rotas. **§7** e **§8**: ecrãs e serviços externos.
4. **§12** antes de correr seja o que for em local; **§13** para saber o que é "nenhuma falha nova".
5. **§14**: o que só o dono decide. Os agentes registam lá e continuam; nunca o simulam.

**Regras para os agentes** (resumo do §0 do plano, com as correções):

1. **Nada sai do Mac:** proibido `git push`, `git merge` para `main`, `deploy.sh`, `ssh` ao VPS, qualquer ligação ao MongoDB Atlas, enviar emails ou mensagens.
2. **TDD estrito** em domínio, API e módulos puros: teste → ver falhar **pelo motivo esperado** → mínimo → verde → bateria do CRM.
3. **Testes nunca em paralelo**, uma suite de cada vez; os revisores leem código, não correm suites.
4. **Anti-encalhe:** servidores (`uvicorn`, `craco start`, `mongod`), instalações, a suite completa e o `craco build` correm **em segundo plano** com registo em `$HOME/.cache/lisbonb-crm-local/`; esperas sempre limitadas. O macOS não tem `timeout`: usar `perl -e 'alarm 120; exec @ARGV' <comando>`.
5. **Caminhos absolutos literais** em cada comando, porque o estado da shell não passa de uma chamada para a seguinte. Começar cada bloco por `RAIZ="/Users/brucesilva/pasta sem título/RH"; LOGS="$HOME/.cache/lisbonb-crm-local";` e citar sempre os caminhos (espaços e acentos).
6. **Ficheiros partilhados com o Matheus** (`backend/server.py`, `frontend/src/App.js`, `components/layouts/AdminLayout.js`, `components/layouts/EmployeeLayout.js`, `pages/PrivacyPolicy.js`, `backend/.env.example`, `frontend/package.json`, `frontend/yarn.lock`): alterações mínimas e localizadas, sem reformatar, cada uma no seu commit, com `git diff --stat` conferido.
7. **Commits:** um por tarefa, prefixo `CRM:`, ficheiros explícitos (nunca `git add -A` nem `git add .`; a pasta `HANDOFF/` não está versionada e não se toca), rodapé `Co-Authored-By` em segundo `-m`.
8. **Segredos:** nunca valores no chat, em registos ou em ficheiros versionados, só nomes. Neste dossiê os valores aparecem sempre como `<…>`.
9. **DOM:** o React escapa por omissão. Nunca `dangerouslySetInnerHTML`, `.innerHTML =`, `outerHTML`, `insertAdjacentHTML` nem `document.write`. No Leaflet, `bindTooltip`, `bindPopup`, `setContent`, `setTooltipContent` e `setPopupContent` só dentro de `lib/crm/mapa.js` e com nós DOM criados com `textContent` (`el(...)`). `divIcon` nunca leva `html` e a atribuição vem só das constantes de `lib/crm/atribuicoes.js` (o `prefix` do controlo é `false`; nunca `addAttribution` nem `setPrefix`). `href="tel:"` só com dígitos e `+`, sempre pelo `hrefTelefone` do `dom.js`. O `seguranca.test.js` (T2.23) verifica tudo isto no código do CRM, comentários incluídos: um comentário não pode nomear estas vias (escrever "como HTML").
10. **Proibições herdadas do desenho (§4.4) e do CRM autónomo (§6.2 e §9 do original):**
    - nunca reutilizar a chave Google Places do portal (`GOOGLE_PLACES_API_KEY`) nem guardar dados vindos da Google;
    - o **nome e o telefone** de uma loja são sempre **escritos pela pessoa**; a Geoapify só sugere morada, código postal e localidade;
    - nunca endurecer a `Referrer-Policy` (`no-referrer` ou `same-origin`) no nginx, no Caddy ou no HTML: a chave dos mosaicos é restrita por Referer e o OSM também recusa pedidos sem ele.
11. **[DONO]** marca o que só o Bruce faz (§14).

---

## 1. O que é o CRM

CRM da fábrica de sorbet de açaí **Purple House** (empresa do grupo Lisbonb). O ecrã principal é um **mapa**:
cada loja (revendedor atual ou potencial) é um pino com a cor da fase comercial e o **nome sempre visível**, em
qualquer zoom e sem agrupamento. O CRM serve também para **planear o dia da carrinha** (1 carrinha, 1 rota por dia,
várias regiões de Portugal continental): entregas marcadas mais visitas a lojas próximas, pela melhor ordem e
dentro dos horários de cada loja.

**Sucesso na v1** (original §1): todas as lojas no mapa com fase, contacto e histórico; o escritório planeia a
rota de um dia em menos de 10 minutos; o motorista regista cada paragem com um toque, mesmo com falhas de rede.

**Quem usa:** só os **membros do CRM**, que o Bruce escolhe. São o escritório (gestores ou colaboradores do
portal) e o motorista (colaborador do portal, entra com o seu email e palavra-passe). Um colaborador que seja
membro usa o CRM sem ver o resto do portal.

**Decisões do Bruce (2026-10-09, desenho §1):** reescrever no portal; só a equipa Purple House vê o CRM; cada fase
vai para o portal verdadeiro **escondida** (no início só o Bruce a vê); **rota primeiro** (base → planear rota →
rota do dia → encomendas e alertas); o motorista também regista lojas novas e corrige localizações no terreno; o
Matheus trabalha no mesmo portal, com ramos próprios e alterações pequenas nos ficheiros partilhados.

**Fora da v1** (original §3): faturação, preços, stock, relatórios, várias carrinhas no mesmo dia, feriados como
datas (vão nas notas) e seguimento GPS contínuo (**nunca**).

---

## 2. Stack atual vs alvo

| | CRM autónomo (referência) | No portal (alvo) |
|---|---|---|
| Backend | PHP 8.4 sem framework, PDO, router próprio | Pacote `backend/crm/` no FastAPI 0.110, Python 3.11 (molde `backend/faturacao/`) |
| Base de dados | MariaDB, migrações SQL numeradas, transações | MongoDB (Atlas em produção, 8.0 em local), coleções `crm_*`, índices declarados no código, **sem transações** |
| Frontend | JavaScript puro (módulos ES), PWA própria | React 19 do portal (CRA 5 + craco), shadcn/ui + Tailwind, Leaflet 1.9.4 do npm, páginas do CRM com `React.lazy` |
| Autenticação | Login próprio de 30 dias, CSRF, utilizadores próprios (`admin`/`utilizador`) | Login do portal (JWT de 24 h no cabeçalho), sem CSRF; `crm_membros` com `admin`/`utilizador`/`motorista` |
| Testes | PHPUnit, `node:test`, Playwright | pytest (`backend/tests/crm`), Jest (`frontend/src/lib/crm`), duplos do Mongo, ensaio opcional no Mongo local |
| Publicação | GitHub Actions e Hostinger | `deploy.sh` do portal no VPS (fora deste plano; só com o dono) |
| Endereço | `crm.purplehouseacai.com` | Dentro de `lisbonb.com`: `/crm/*`, `/admin/crm/*`, `/rota` (F4) |

### 2.1 Armadilhas de portagem (PHP/`node:test` → Python/Jest)

- **Arredondar:** o `round()` do PHP é meio-para-longe-do-zero; o do Python arredonda para o par (50,5 → 50 aceitaria um GPS a 51 m). Usar `dominio.numeros.arredondar` (`Decimal(repr(x)).quantize(…, ROUND_HALF_UP)`), que devolve sempre `float`, como o PHP (quem precisa de um `int` converte, como o `(int) round(…)`). Na T2.1 foi conferido com o `round()` do PHP 8.4.26 em 57 999 valores (coordenadas, metros e floats de todas as grandezas, às 0, 2 e 6 casas): todos iguais, exceto um à volta de 4,4×10¹³ com 2 casas, em que o PHP perde precisão (fora de qualquer valor do CRM).
- **Tipos JSON:** `True` é `int` em Python e o `json` aceita `NaN` e `1e400`. Usar `e_inteiro_json`/`e_numero_json` (`type(x) is int`, `math.isfinite`); `bool` nunca conta como número. O Python lê inteiros de qualquer tamanho e o PHP lia como `float` os que passam dos 64 bits: estes não são `e_inteiro_json` (o MongoDB também só guarda 8 bytes) e só são `e_numero_json` se couberem num float (maiores, o PHP lia INF).
- **Graus para radianos:** o `deg2rad()` do PHP faz `(graus / 180) * M_PI` e o `math.radians()` do Python multiplica por `pi / 180`, o que muda a última casa binária (nas antípodas, até 0,19 m). `geo.py` usa `_radianos` com a ordem do PHP: na T2.2, 60 000 pares deram a mesma distância ao bit que o `Distancia::metros` do PHP 8.4.26. O `math.sin`/`math.asin` do Python rebentam com `ValueError` onde o PHP dava NAN (inf, ou acima de 1); a distância recebe só coordenadas finitas já validadas.
- **Texto:** `str.strip()` não tira U+FEFF; `\d` aceita algarismos árabes e `$` aceita `\n` final. Usar `aparar` com `[\s\u180e\ufeff]` e `\Z`, `[0-9]` e `re.fullmatch` em todas as regras.
  - **U+180E (revisão da F2):** o `\s` do PCRE2 com `/u` ainda conta o separador de vogais mongol (deixou de ser espaço no Unicode 6.3) e o `Texto::aparar` tira-o; o `\s` do Python não. Sem ele na classe, um nome só com U+180E gravava-se (invisível no mapa) e "\u180eLisboa" passava por outra região que não "Lisboa". Conferido no PHP 8.4.26 em todos os pontos de código: com o U+180E na classe, a **única diferença assumida** do `aparar` é U+001C–U+001F (o Python tira, o PHP não). O teste `test_os_caracteres_aparados_sao_os_do_php_mais_os_separadores_de_controlo` fixa o conjunto inteiro.
  - **Surrogates sozinhos:** o `json.loads` aceita um `"\ud800"` sozinho, que o `json_decode` do PHP recusava ("Single unpaired UTF-16 surrogate", conferido no PHP 8.4.26), e o `corpo_json` ainda não o recusa. Esse texto rebenta com `UnicodeEncodeError` no `str.encode("utf-8")` e no BSON do Mongo, o que dá 500 numa escrita. Na T2.4, `campos_loja.notas` conta os bytes com `surrogatepass` para não rebentar. **Corrigido na T2.10:** o `corpo_json` recusa-os com 400 `json_invalido`, como o PHP, em valores e chaves, a qualquer profundidade e também quando uma chave repetida tapa o valor (o `json_decode` recusa o corpo inteiro ao ler o primeiro; o dict do Python ficava só com o último). Por isso a verificação está no `object_pairs_hook` do `json.loads`, que vê todos os pares, e não no dicionário já feito; percorre as listas sem recursão. Um par certo em escape (alto e depois baixo) é um só carácter e passa. Conferido com o `json_decode` do PHP 8.4.26 em 30 018 corpos (as 18 entradas das tabelas e 30 000 aleatórios com escapes, pares certos e trocados, barras escapadas e chaves repetidas; 23 715 recusados): a mesma decisão em todos (`t2.10-conferencia-php.log`). A primeira versão, que percorria o dicionário já feito, deixava passar as chaves repetidas; foi a conferência que as apanhou.
- **Equivalências:** `mb_strlen` → `len`; `strlen` → `len(s.encode("utf-8"))`; `in_array(…, true)` → `isinstance(x, str) and x in ORDEM`; `sprintf('%.6F')` → `"%.6f" % (x + 0.0)` depois de `arredondar` (com `-0.0` o PHP escreve `0.000000` e o Python `-0.000000`; somar 0,0 tira o sinal, como em `definicoes._seis_casas`, T2.7); `(float) $texto` → nunca `float(texto)`, que rebenta com "abc" e lê "inf", "nan", "1_000" e algarismos Unicode: o PHP lê só o número do início do texto (espaços `" \t\n\r\v\f"` antes, algarismos ASCII, ponto, expoente) e dá 0,0 sem número (`definicoes._float_do_php`, T2.7); `rawurlencode` → `urllib.parse.quote(chave, safe="")`; `http_build_query(…, RFC3986)` → `urlencode(…, quote_via=quote)` (na T2.14, `&`.join de `nome=valor`, cada um pelo `quote(bytes surrogateescape, safe="")`); `trim($s)` sem segundo argumento → `s.strip(" \t\n\r\x00\x0b")`, que **não é** o `aparar` (não tira os espaços Unicode, o U+FEFF nem o `\f`; `geoapify._texto`, T2.14); `strtolower` → só ASCII (`s.isascii() and s.lower() == "pt"`); `number_format($v, 6, '.', '')` → `"%.6f" % (arredondar(v, 6) + 0.0)` (o PHP 8 nunca escreve "-0"; `geoapify._coordenada`, T2.14); `json_decode($corpo, true, 512, JSON_THROW_ON_ERROR)` + `is_array` sobre uma resposta externa → `geoapify.ler_json` (UTF-8 estrito, sem NaN/Infinity, até 511 níveis, sem surrogates sozinhos, só objeto ou lista; T2.15); `$_GET['x']` repetido → o último, como o FastAPI com `Optional[str]`, e `x[]=…` é outro nome.
- **Corrotinas nos testes:** **proibido `asyncio.run`** em `tests/crm`, porque deixa o ciclo de eventos a `None` e parte dezenas de testes antigos que usam `get_event_loop()`. Usar `correr(coro)` de `tests/crm/duplos.py` (um ciclo novo, sem `set_event_loop`). `grep -rn "asyncio.run(" backend/tests/crm` tem de dar vazio.
- **`tests/crm/conftest.py`:** faz `setdefault` de `POS_JWT_SECRET`, `JWT_SECRET`, `MONGO_URL` e `DB_NAME` com os valores de teste já usados no repositório, porque `tests/crm` é recolhida antes de `tests/faturacao`. Nos testes, importar os auxiliares de forma relativa (`from .duplos import BaseFalsa`).
- **Duplo do Mongo:** `BaseFalsa.__getattr__` levanta `AttributeError` para nomes começados por `_`, como o Motor.
- **FastAPI:** parâmetros de query do CRM declarados como `Optional[str] = None` e validados no domínio, senão sai o 422 do Pydantic (lista, em inglês). A dependência de perfil vem **antes** de `corpo_json`: um pedido sem sessão e com JSON inválido dá 403/401, nunca 400.
- **Jest (CRA 5):** `resetMocks: true` apaga as implementações dos `jest.fn` criados ao nível do módulo, por isso criá-los dentro de cada teste ou em `beforeEach`. Imports relativos (o Jest não conhece o alias `@/`). `import.meta` não funciona. `assert.equal` → `toBe`, `deepEqual` → `toEqual`, `throws` → `toThrow`, `mock.timers` → `jest.useFakeTimers()`. Para formas exatas usar `toEqual`, nunca `toMatchObject`: neste, `campos: {}` aceita qualquer valor, até `null` ou uma lista (T1.10).
- **`toEqual`, `toStrictEqual` e o `mock.calls` (T2.24):** o `toEqual` ignora as chaves com `undefined`, por isso `{texto: 'rua', lat: undefined}` passa por `{texto: 'rua'}`. Para provar que uma chave não existe, usar `toStrictEqual`. Mas o `mock.calls` de um `jest.fn` nasce noutro «realm»: um `.map` sobre ele dá um `Array` de outro construtor, e o `toStrictEqual` falha com "serializes to the same string". Montar a lista no próprio teste: `Array.from(fn.mock.calls, ([c]) => …)`.
- **Temporizadores falsos (T2.22):** o `mock.timers.enable({ apis: ['setTimeout'] })` do `node:test` passa a `jest.useFakeTimers()` no `beforeEach` (com `jest.useRealTimers()` no `afterEach`) e o `mock.timers.tick(n)` a `jest.advanceTimersByTime(n)`. As promessas continuam nativas, por isso o `await Promise.resolve()` (o `esvaziar()` dos testes da morada) deixa correr as respostas como no autónomo.
- **APIs recentes sem polyfill (T2.22):** o CRA transpila a sintaxe, mas não junta polyfills. O `Object.hasOwn` do `gps.js` do autónomo passou a `Object.prototype.hasOwnProperty.call` (o mesmo resultado), porque falta nos Safari anteriores ao 15.4: aí o erro rebentava dentro da resposta do browser e a promessa do `obterPosicao` nunca acabava ("A obter a localização…" para sempre). O mesmo cuidado com `Array.prototype.at`, `structuredClone` e afins no código de produção (nos testes não importa: correm no Node).
- **Ids (T2.21):** onde o autónomo pedia um inteiro positivo (`Number.isSafeInteger(id) && id > 0`, ou `/^[1-9]\d*$/` num texto), o portal pede um uuid4 em texto: `eUuid` de `lib/crm/ids.js`. O `PADRAO_UUID4` é o `_UUID4` do `validador_loja.py`, e o `ids.test.js` lê esse ficheiro. Minúsculas, tal e qual, sem `Number()`: o `regiao_id` da loja compara-se com `===`. Sem a flag `m`, o `$` do JavaScript não aceita um `\n` final, ao contrário do `$` do Python.
- **ESLint do CRA:** `no-script-url` avisa de qualquer texto `'javascript:'` e `no-control-regex` avisa de um `\u0000` num regex. No `dom.js` os dois aparecem só para recusar, com `eslint-disable-next-line` justificado (T2.20). Nos testes, um `/* eslint-disable no-script-url -- … */` no topo.
- **Leaflet:** `import * as L from 'leaflet'` (o build ESM não tem export por omissão; o webpack usa o UMD do `main`, e assim funciona nos dois casos). `leaflet.css` importado depois do `index.css`. O mapa é destruído no cleanup do `useEffect`, porque o `StrictMode` monta duas vezes.
- **Leaflet no Jest (T2.23):** o Leaflet 1.9.4 verdadeiro corre no jsdom do CRA (`import * as L from 'leaflet'` num teste), sem imagens nem medidas: o `mapa.test.js` usa-o para ver o DOM da etiqueta, do ícone e da atribuição, o teclado e o `destruir()`. Para ter pinos e etiquetas é preciso uma vista primeiro (`enquadrar`). O `map.remove()` tira os painéis e os controlos, mas deixa as classes `leaflet-container` no elemento, e um mapa novo no mesmo elemento já não rebenta. O resto dos testes usa o `testes/leafletFalso.js`.
- **Regex com `(?!…)` (T2.23):** um `\s*` antes de um lookahead negativo recua e deixa-o passar num espaço (`attribution: ATRIBUICOES[…]` com um espaço dava violação). Os espaços vão dentro: `:(?!\s*ATRIBUICOES…)`, `\((?!\s*el\()`.
- **Ícones:** importar `Map as IconeMapa` do lucide; um `Map` importado tapa o `Map` do JavaScript.
- **Componentes do mapa no Jest (T2.25, verificação temporária):** o Leaflet verdadeiro no jsdom precisa de `clientWidth`/`clientHeight` (o jsdom dá 0, e o `fitBounds` fica sem zoom): definir os dois no `HTMLElement.prototype` só no teste. O Radix (`Popover`, `Select`) pede `ResizeObserver`, `PointerEvent`, `scrollIntoView` e `hasPointerCapture`, que o jsdom do Jest 27 não tem. Dentro do `StrictMode`, cada pedido ao montar sai duas vezes: a API falsa responde a todos os pendentes.
- **Leaflet no browser (T2.25):** as etiquetas (tooltips) têm `opacity: 0.9` por omissão, e os mosaicos acabam de aparecer com uma transição de 0,2 s (até lá vê-se o fundo `#ddd`): para medir, esperar por todos os `img.leaflet-tile-loaded`. O `Popover` do shadcn abre com uma animação de 0,15 s: as capturas esperam ~400 ms.
- **`L.circle` no jsdom (T2.26):** o Leaflet decide ao importar se há SVG (`createSVGRect`), que o jsdom não tem, e sem renderizador o `L.circle(...).addTo(mapa)` rebenta ("Cannot use 'in' operator … in null"), e depois o `map.remove()` também. No browser há sempre SVG. Nos testes, o círculo fica no `testes/leafletFalso.js`; a verificação temporária dos componentes dá ao jsdom um `SVGSVGElement.prototype.createSVGRect` antes de importar o Leaflet (`t226-verificacao/zz_polyfill_t226.js`).
- **Respostas 503 na consola (T2.26):** o Chrome escreve "Failed to load resource: the server responded with a status of 503" por cada resposta 5xx, também as previstas (a morada sem chave). Nas verificações no browser, contá-las à parte (uma por pedido à morada) e exigir zero erros do resto.
- **`AlertDialog` do Radix (T2.27):** ao abrir, o `AlertDialogContent` faz `preventDefault` e põe o foco no `AlertDialogCancel`; sem ele, o foco não vai para lado nenhum. Ao fechar, devolve-o ao `Trigger`, que um diálogo aberto pelo ecrã não tem. O `DialogoDuplicado` passa `onOpenAutoFocus` (o foco na primeira escolha, como no autónomo) e `onCloseAutoFocus` (o Guardar). Precisa de um `AlertDialogTitle` (aqui é a própria pergunta) e de `aria-describedby={undefined}` para o Radix não avisar da falta da descrição. O Escape chega como `onOpenChange(false)`.
- **Jest: `expect(x).toBe(y, 'mensagem')` (T2.27):** o Jest ignora o segundo argumento (não há mensagens nos *matchers*, ao contrário do `assert` do `node:test`). Ao portar, a mensagem passa a comentário.
- **Verificações no jsdom (T2.27):** o jsdom do Jest 27 não tem `CSS.escape`; para achar o rótulo de um campo, comparar `label.htmlFor` com o `id` (os ids do `useId` trazem `:`). No `StrictMode`, o mapa do seletor só se cria quando a configuração chega, depois da montagem dupla: um só mapa, nenhum destruído.
- **Medir cores no browser (T2.27):** o `Input` do shadcn tem `transition-colors` (150 ms): a borda vermelha de um campo com erro (`aria-[invalid=true]:border-destructive`) só se lê certa depois da transição.
- **`structuredClone` no Jest (T2.28):** o jsdom do Jest 27 não o tem (`ReferenceError`). Os testes portados do autónomo (que o usam para copiar a loja) fazem `JSON.parse(JSON.stringify(loja))`.
- **Foco que o Radix devolve (T2.28):** ao fechar um `AlertDialog`, o `onCloseAutoFocus` corre num `setTimeout` do `FocusScope`: nas verificações no jsdom, esperar um *macrotask* (ex.: 20 ms) antes de ler o `document.activeElement`. Com `onOpenAutoFocus` + `preventDefault`, o foco só vai para onde o código o põe (sem a linha, perde-se).
- **`StrictMode` e pedidos duplicados (T2.28):** em desenvolvimento, a página cria o ecrã, destrói-o e cria outro: cada pedido do `iniciar` sai duas vezes, e o primeiro ecrã já não ouve a resposta. Nas verificações, responder (ou falhar) **todos** os pedidos pendentes, não só o primeiro.
- **Verificações no browser com toasts (T2.28):** o sonner mantém um toast à vista uns segundos; esperar pelo texto "Alterações guardadas" logo depois de outro igual passa à primeira. Esperar pela resposta do pedido (contar os PATCH intercetados) e só depois pelo toast.
- **Pinos sobrepostos (T2.27):** duas lojas a poucos metros (ex.: a "outra loja" do duplicado, a 8 m) têm os pinos um em cima do outro, porque não há agrupamento (decisão do desenho). Nas verificações no browser, o pino de baixo abre-se com o teclado (foco no pino e Enter, do `mapa.js`) ou aproximando o mapa.
- **`SelectItem` do shadcn com duas linhas (T2.29):** põe todos os filhos dentro do `ItemText`, e o campo fechado (`SelectValue`) mostra o `ItemText` inteiro: o detalhe (email e tipo de conta) aparecia cortado com reticências ("Gestor (demo)…"). Para um detalhe só na lista, compor o `SelectPrimitive.Item` do `@radix-ui/react-select` com só o nome no `ItemText` (é também o que a escrita rápida procura), como o `OpcaoConta` do `DefinicoesMembros.js`. O `textContent` do campo inclui o texto cortado por `line-clamp`: medir com o texto do `ItemText`, não com o que se vê.
- **Tabelas no telemóvel (T2.29):** cada linha é um cartão (`block` até ao `md`), com o rótulo de cada célula num `before:content-[attr(data-rotulo)]` e os `role` explícitos (`table`, `rowgroup`, `row`, `columnheader`, `cell`), como no autónomo (o Safari tira a tabela aos leitores de ecrã quando o `display` das células muda). O `TableBody` do shadcn tira a borda à última linha (`[&_tr:last-child]:border-0`): no telemóvel o último cartão ficava sem borda (`[&_tr:last-child]:border md:[&_tr:last-child]:border-0`). Os emails partem-se antes do "@" (`<wbr>` + `break-words`); o `[overflow-wrap:anywhere]` numa tabela automática deixa a coluna encolher até uma letra e parte o email a meio ("admin.local@example.co / m").
- **Mutações com `key={null}` (T2.29):** no JSX de agora (`react/jsx-runtime`) uma `key` `null` passa a texto, `"null"`, sem aviso: trocar a `key` do admin principal (`'admin-principal'`) pelo `id` (`null`) é equivalente, desde que só uma linha o tenha.
- **Uma página do portal como texto no Jest (T2.31):** o `privacidade.test.js` desenha a `PrivacyPolicy` com o `renderToStaticMarkup` do `react-dom/server`, num ficheiro com `/** @jest-environment node */` no topo (o jsdom do Jest 27 não tem o `TextEncoder` de que o servidor do React 19 precisa; no ambiente node tem). Não é um teste de componente: a página não tem estado, e o teste só lê o texto. O Jest do CRA acrescenta a cada elemento atributos `x-file-name`/`x-line-number`/`x-id` (o plugin de edição visual do `craco.config`), por isso compara-se o texto sem as etiquetas e nunca o HTML. O JSX junta as linhas de texto com um espaço, mas cola um texto a um `<strong>` que comece noutra linha (é por isso que o original tem `<strong> Grupo Lisbonb</strong>`). Um espaço em falta à volta de um `<strong>` só se apanha comparando a frase inteira que o atravessa: foi a única mutação que sobreviveu à primeira versão do teste.
- **`Tabs` do Radix (T2.29):** os separadores fechados deixam o painel vazio e `hidden` (o conteúdo desmonta-se: voltar a um separador volta a pedir o que ele mostra). No jsdom, o separador muda no `mousedown` (não no `click`); nas contas, contar só os `[role="tabpanel"]:not([hidden])`. Um `Select` do Radix abre-se no jsdom pelo teclado (Enter no gatilho) e escolhe-se com um `click` na opção.

---

## 3. Modelo de dados (MongoDB, coleções `crm_*`)

Regras gerais: `id` uuid4 em texto em todos os documentos; as respostas nunca expõem `_id` (projeção `{"_id": 0}`);
`regiao_id`, `criado_por`, `user_id` e `utilizador_id` são ids do portal em texto. Leituras de listas com
`to_list(5000)` (volume esperado: centenas). Ordenação por nome em Python com `dominio.texto.chave_comparacao`
(sem acentos nem maiúsculas).

**Tempo:**
- Todos os instantes `*_em` e `fase_desde` (exceto `atualizado_em`) têm **largura fixa** `AAAA-MM-DDTHH:MM:SSZ`, escritos só por `relogio.instante()`.
- `atualizado_em` tem **sempre 6 casas** (`2026-10-10T09:00:00.123456Z`) e é estritamente crescente (`relogio.proximo_carimbo`). As 6 casas valem também para as definições (o autónomo gravava ali um `DATETIME` sem casas), mas lá é só `relogio.carimbo(agora)`: as definições não têm bloqueio otimista e o carimbo só diz quando mudou (T2.13, §5.9).
- **Carimbos (T2.8, `crm/relogio.py`):**
  - `carimbo(momento=None)` → o `atualizado_em` de um documento novo (o `Formatar::instanteMicro`). Uma `datetime` sem fuso → `ValueError`, como no `instante`.
  - `ler_carimbo(valor)` → o próprio texto, se for um carimbo exato (6 casas, `Z`, só algarismos ASCII, nada antes nem depois) com uma data e uma hora que existam; senão `None` (o `Formatar::lerInstanteMicro`, com os casos do `FormatarTest.php`). O texto vai direto para o filtro `{"id", "atualizado_em": versao}` e nunca é um operador do Mongo.
  - `proximo_carimbo(agora, anterior)` → `max(agora, anterior + 1 µs)` (o `GREATEST(?, atualizado_em + INTERVAL 1 MICROSECOND)` do `LojasRepositorio::atualizar`): muda sempre e é sempre maior, também com o relógio atrasado. Um `anterior` que não é carimbo → `ValueError`; depois de `9999-12-31T23:59:59.999999Z` → `OverflowError`.
  - Conferido com o `Formatar` do PHP 8.4.26 em 156 048 casos (`t2.8-conferencia-php.log`): 90 048 leituras (32 591 válidas) e 33 000 formatações de cada tipo, sem diferenças, exceto duas assumidas. O ano `0000`, que o PHP aceita e a `datetime` do Python não representa, dá aqui `None`; nunca sai do `carimbo()`. Um NUL no texto fazia o `createFromFormat` do PHP lançar `ValueError` (um 500); aqui dá `None` (um 422).
- Nunca `.isoformat()` no pacote `crm`, porque dá `+00:00` e parte a ordenação por texto e o `$max`. Garantido por `tests/crm/test_instantes_gravados.py`, que varre o AST de todos os módulos: nunca `isoformat`; fora do `relogio.py`, também nem `strftime` nem leituras do relógio (`now`, `utcnow`, `today`, `fromtimestamp`, `utcfromtimestamp`, `time.time`, `time.time_ns`).
- **Verificador para os testes das escritas:** `tests/crm/formatos.instantes_fora_do_formato(documento)` aponta os `*_em`/`*_desde` que não são `AAAA-MM-DDTHH:MM:SSZ` (ou null) e o `atualizado_em` que não é carimbo, também em subdocumentos e listas. Aplica-se ao membro do `POST /membros` e, desde a T2.10, ao `documento_loja` e à loja gravada pelo `POST /lojas` (também no MongoDB 8 local). Desde a T2.11, também à interação `mudanca_fase` e ao `$set` do `PATCH /lojas/{id}` (no duplo e no MongoDB 8 local). Desde a T2.13, também às definições gravadas pelo `PATCH /definicoes`.
- Datas e horas de Lisboa como texto (`AAAA-MM-DD`, `HH:MM`); "hoje" em `Europe/Lisbon`.

| Coleção (fase) | Documento | Índices (`crm/db.py::INDICES`) |
|---|---|---|
| `crm_membros` (F1) | `{id, user_id, perfil: admin\|utilizador\|motorista, criado_em, criado_por, atualizado_em?}` | `id` único; `user_id` único |
| `crm_regioes` (F2) | `{id, nome, nome_chave, ordem: int}` | `id` único; `nome_chave` único |
| `crm_lojas` (F2) | `{id, nome, fase, fase_desde, regiao_id\|null, morada, codigo_postal, localidade, lat, lng, loc: {type: "Point", coordinates: [lng, lat]}, origem_coords: pin_manual\|gps\|geocoder, precisao_m\|null, telefone, pessoa_contacto, instagram, site, notas, janelas: [{inicio, fim}], dias_fechada: [seg…dom], visita_pendente_motivo, visita_pendente_desde, ultima_interacao_em, ultima_visita_ou_entrega_em, criado_por, criado_em, atualizado_em}` | `id` único; `loc` `2dsphere`; `regiao_id` |
| `crm_interacoes` (F2: só `mudanca_fase`) | `{id, loja_id, tipo, resultado: "<antiga>→<nova>", notas: null, paragem_id: null, utilizador_id, ocorrida_em}` (sem `client_uuid` na F2) | `id` único; `(loja_id, ocorrida_em)`; `client_uuid` único **parcial** com `{"partialFilterExpression": {"client_uuid": {"$type": "string"}}}` |
| `crm_definicoes` (F2) | `{chave, valor (texto), atualizado_em, atualizado_por}`; só o que o admin alterou, padrões no código | `chave` único e **nenhum** índice em `id` |
| `crm_rotas` (F3) | `{id, data (única), estado, versao, …, paragens: [...]}` | a definir na F3 |
| `crm_produtos`, `crm_encomendas` (F5) | encomendas com as linhas dentro do documento | a definir na F5 |

- **`COLECOES` cresce por tarefa:** a T1.2 só tinha `{"membros": "crm_membros"}`; a T2.8 juntou as quatro da F2 com os índices da tabela. `test_indices.py` fixa a lista **exata** de cada coleção, porque um índice a mais também é um erro (`regiao_id` único deixava uma loja por região; `client_uuid` único sem ser parcial, ou `sparse`, que indexa o null, fazia colidir todas as interações da F2). `crm_definicoes` não tem `id`: um índice único em `id` faria o segundo upsert dar E11000 em produção. O teste dos índices verifica isto de forma explícita.
  - **Conferido no MongoDB 8.0.32 local (T2.8, `t2.8-conferencia-mongo.log`, base `lisbonb_crm_teste` apagada no fim):**
    - o `criar_indices` verdadeiro, corrido duas vezes, não regista erros e cria exatamente os índices declarados;
    - `nome_chave` repetido e `client_uuid` de texto repetido dão `DuplicateKeyError`; interações sem `client_uuid` ou com null não colidem; dois upserts seguidos das definições também não;
    - um `loc` fora do mundo é recusado (`WriteError`): o `loc` tem de ser sempre um Point válido;
    - o `$geoWithin` de 60 m usa o `loc_2dsphere`, o filtro por região usa o `regiao_id_1` e a linha do tempo (`loja_id` + ordenação por `ocorrida_em`) usa o `loja_id_1_ocorrida_em_1`;
    - a atualização condicional com carimbos só grava com a versão certa.
  - **Ensaio versionado (T2.17, `backend/tests/crm/test_mongo_local.py`):** repete estas conferências e as das T2.9–T2.13 como testes, contra o MongoDB 8 local. Como correr: §12.7. O que prova:
    - o `criar_indices` verdadeiro, duas vezes, sem nenhum erro registado, deixa em cada coleção exatamente os índices de `INDICES`; `crm_definicoes` fica só com `_id_` e `chave_1`;
    - o `filtro_candidatos` pelo `loc_2dsphere`: o círculo de 60 m traz as lojas a 30 m e a 55 m, e não as de 65 m e 80 m; a regra exata deixa só a de 30 m (`distancia_m` 30); o `$ne` da edição tira só a própria, nos dois sentidos; um `loc` fora do mundo é recusado (`WriteError`);
    - a atualização condicional com a versão velha dá `matched_count 0` e não muda nada; o carimbo seguinte é `$gt` o anterior também como texto; o filtro usa o `id_1`;
    - `DuplicateKeyError` com `nome_chave`, `user_id`, `id` (membros, regiões, lojas, interações) e `client_uuid` de texto repetidos; as interações sem `client_uuid` ou com null não colidem (índice parcial);
    - o histórico do DELETE e a linha do tempo vão pelo `loja_id_1_ocorrida_em_1`, e a ordem por `ocorrida_em` é a do tempo;
    - dois upserts seguidos das definições (latitude e longitude) sem `DuplicateKeyError` (correções do plano, linha "T1.2 / T2.8"); o `PATCH /definicoes` grava uma linha por chave e o seguinte substitui; 20 `PATCH` ao mesmo tempo sobre a coleção vazia não dão erro e deixam uma linha por chave (o Mongo refaz o upsert que perde a corrida pelo `chave_1`);
    - as corridas com o Motor nas rotas (`PATCH` e `DELETE /lojas`, `POST /regioes` e `POST /membros`): uma **barreira** segura as duas primeiras leituras até ambos os pedidos terem lido, para a corrida acontecer sempre. Uma alteração grava e a outra dá 409 `conflito`, com uma só interação; um apaga e o outro dá 404; a segunda região ou o segundo membro dá 409, travado só pelo índice único.
    - **o seed das lojas de demonstração (T2.18):** as 24 lojas e as 4 regiões gravam-se com os índices verdadeiros e as rotas leem-nas (`GET /lojas`, `GET /lojas/{id}`, `GET /regioes`); pelo `loc_2dsphere`, nenhuma loja tem outra a menos de 210 m; o `nome_chave` das regiões trava um `POST /regioes` "lisboa" (409); a segunda vez sem `--repor` recusa e com `--repor` não colide. Com um validador do Mongo que recusa as lojas de demonstração (o papel do gatilho "falha simulada" do autónomo), o seed numa base vazia deixa-a vazia e o `--repor` deixa as três coleções exatamente como estavam, com os mesmos `_id`.
- `lat`/`lng` e `loc` escrevem-se sempre juntos (`formatar.documento_localizacao(lat, lng)` → `{lat, lng, loc}`, as coordenadas em `float`; T2.10). Na API as janelas são planas (`janela1_inicio`, `janela1_fim`, `janela2_inicio`, `janela2_fim`); na base ficam em lista (0 a 2, por ordem).
- **Contas do portal (`users`, já existe):** o CRM lê `id`, `email`, `name` e `role`. A projeção **nunca** pede `password`.
- **Sem transações:** a ordem das escritas é definida e testada. Exemplos: atualizar a loja e depois registar a `mudanca_fase`; se o registo falhar, fica uma linha `[crm]` no log e a loja não é desfeita. Apagar a loja e só depois as `mudanca_fase` dela (T2.12, §5.12); se estas falharem, ficam órfãs e uma linha `[crm]` no log. Corridas residuais aceites, como apagar uma região enquanto se cria uma loja nela. O seed local (T2.18, §12.4) faz o papel da transação do autónomo com uma cópia: constrói e valida tudo antes da primeira escrita e, se uma escrita falhar, repõe nas coleções que mexeu a cópia do que tinham.
- **Migração de dados:** nenhuma. Os dados reais entram diretamente em produção a partir da F2; os de demonstração só existem em local.

| Desenho original (MariaDB, §5) | No portal |
|---|---|
| `utilizadores`, `sessoes`, `tentativas_login` | Não existem: `users` do portal + `crm_membros` |
| `regioes`, `lojas`, `interacoes`, `definicoes` | `crm_regioes`, `crm_lojas`, `crm_interacoes`, `crm_definicoes` |
| `produtos`, `encomendas`, `encomenda_linhas` | `crm_produtos`, `crm_encomendas` (linhas dentro), F5 |
| `rotas`, `paragens` | `crm_rotas` com `paragens` dentro, F3 |
| `schema_migrations` | Não existe: índices declarados e criados no arranque |

---

## 4. Autenticação e membros

- **Base:** `crm.auth.membro_crm_atual` assenta em `faturacao.auth.utilizador_atual`, como o pacote `plataformas`. Herda o papel lido da base em cada pedido, a recusa de contas apagadas (401 `"Sessão terminada"`) e a recusa de sessões anteriores a uma troca de palavra-passe. Desativar ou apagar a conta corta o CRM de imediato.
- **Membros:** `crm_membros`, um perfil por pessoa, e qualquer conta do portal (gestor ou colaborador) pode ser membro. O papel no portal não conta para o CRM.
  - `admin`: tudo, incluindo membros, regiões, produtos e definições do CRM.
  - `utilizador`: lojas, mapa, planear rotas e encomendas.
  - `motorista`: rota do dia e, no terreno, "Estou nesta loja" (loja nova) e corrigir a localização (F4). **Na F1 e na F2 o motorista não entra no `/crm` nem usa rotas da F2**; não antecipar as permissões da F4.
  - **Nomes nos ecrãs (T2.21, `lib/crm/perfis.js`):** "Utilizador", "Administrador" e "Motorista", por esta ordem. É a regra do autónomo: o mais comum primeiro, porque o primeiro é o que o "Adicionar" dos membros escolhe por omissão, e nunca o admin. A ordem do servidor (`membros.PERFIS`, admin primeiro) não é a dos ecrãs. `rotuloPerfil` deixa um valor desconhecido como está e dá `''` ao que não é texto. O `perfis.test.js` lê os `PERFIS` do `membros.py`, que por isso ficam numa só linha.
- **Admin master:** a conta cujo email (lido da base) é igual a `ADMIN_EMAIL`. Por omissão é `geral@olacai.com`, em paridade com `server.py:61`. É sempre `admin` do CRM, não tem linha em `crm_membros` e não se pode adicionar como membro (409 `admin_master`), por isso não há regra do "último admin".
  - O email compara-se tal e qual, como no `server.py` (`user["email"] == MASTER_ADMIN_EMAIL`), e um email vazio nunca conta. O teste `test_auth.py` lê o `server.py` como texto e falha se o valor por omissão se separar de `crm.auth.ADMIN_EMAIL_POR_OMISSAO`.
  - Para o admin master, `crm_membros` nem se lê. Para os outros, uma linha com um perfil fora dos três, ou uma sessão sem `user_id` de texto, conta como não-membro (fechado por omissão). Lê-se a cada pedido: retirar um membro corta-lhe o acesso no pedido seguinte.
- **Tipo de conta:** os papéis de `PERFIS_GESTAO` (`admin`, `gerente`, `contabilista`) contam como `gestor` e `colaborador` como `colaborador`.
- **Só um admin do CRM** adiciona, muda ou retira membros, escolhendo de `GET /membros/candidatos` (contas que ainda não são membros nem são o admin master).
  - **Listas (T1.6, `crm/membros.py`):** das contas do portal pede-se só `{"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1}`, nunca a `password`. Ordem por nome sem acentos nem maiúsculas e, a seguir, pelo `id` (como o `ORDER BY nome, id` do autónomo). Em `/membros`, o admin master vem sempre primeiro (`id: null`; sem conta → `conta_existe: false`), uma linha antiga dele em `crm_membros` não o repete, os membros com a conta apagada vão para o fim (nome, email e tipo de conta a `null`) e um perfil desconhecido sai como `null`. Nos candidatos, qualquer linha de `crm_membros` exclui a conta (o índice único de `user_id` recusava outra).
  - **Escritas (T1.7, `crm/membros.py`):** a guarda `SO_ADMIN` vem antes de `corpo_json` (sem sessão e com JSON partido → 403, nunca 400). O `POST` valida os campos no domínio (422 sem ler a base), depois a conta (422 "A conta não existe."), o admin master (409 `admin_master`) e só então o "já é membro" (409 `ja_membro`). Esta última verificação faz-se antes de gravar, para valer mesmo se o arranque não criou o índice único, e também pelo `DuplicateKeyError` na corrida. Grava `{id (uuid4), user_id, perfil, criado_em, criado_por}` e responde com a forma de uma linha do `GET /membros`. O `PATCH` só muda o `perfil` (422 antes do 404; 409 `admin_master` numa linha antiga dele) e não grava `atualizado_em`, porque os membros não têm bloqueio otimista. O `DELETE` devolve `{retirado: true}`, e da segunda vez 404. Um admin pode despromover-se ou retirar-se, porque o admin master fica sempre admin.
  - **Ecrã (T2.29, `lib/crm/membros.js` + `pages/crm/DefinicoesMembros.js`):** a linha do admin principal é fixa ("É sempre administrador do CRM."); a conta da própria sessão também fica sem ações ("A sua conta: só outro administrador a pode mudar."), como no autónomo: a API deixa um admin despromover-se ou retirar-se, mas o ecrã não o faz por engano (e o `/eu` em cache da sessão ficava desatualizado). O perfil muda num `Select` e grava logo; Retirar pergunta antes. Quem é retirado perde o acesso no pedido seguinte (verificado no browser com o gestor.demo: secção CRM no `/admin` enquanto membro; sem ela, com o `/eu` a `{membro: false}` e o `/lojas` a 403, depois de retirado).

**Famílias de rotas** (teste `tests/crm/test_protecao_rotas.py` com listas explícitas):

| Família | Rotas | Guarda |
|---|---|---|
| Pública | `GET /api/crm/saude` (não toca na base) | Nenhuma |
| Qualquer sessão válida | `GET /api/crm/eu` (devolve `membro: false`, nunca 403) | `utilizador_atual` |
| Tarefas agendadas (F5) | `/api/crm/cron/*` | `crm.auth.exigir_cron_key`: `CRON_KEY` no parâmetro `key`, comparada com `compare_digest` (bytes UTF-8), fechada se a variável faltar ou estiver vazia; sem sessão |
| Membro com perfil | Todas as outras | `membro_crm_atual` + exatamente uma `exigir_perfil(...)` com `perfis_crm` igual a `PERFIS_POR_ROTA` |

- Na F1 e na F2 há dois perfis de rota: `SO_ADMIN = exigir_perfil("admin")` e `ESCRITORIO = exigir_perfil("admin", "utilizador")`.
- O conjunto de rotas do router tem de ser **exatamente** a união das listas: uma rota nova falha até ser classificada.
- A lógica fica em `_classificar(router)`, com um meta-teste (rota sem guarda e rota com o perfil errado) que falha primeiro.
  - Também aponta, em qualquer rota (T1.8):
    - `corpo_json` lido antes da guarda: sem sessão e com JSON partido daria 400 em vez de 401/403;
    - um corpo declarado por modelo Pydantic, que o FastAPI lê antes das dependências (usar sempre `corpo_json`);
    - duas guardas de perfil, ou uma guarda que não assenta em `membro_crm_atual`;
    - a mesma rota declarada duas vezes, ou a mesma rota em duas famílias.
  - Cada método conta como uma rota (`GET` e `POST /membros` classificam-se à parte). Na F1–F2, os perfis da tabela são só `{"admin"}` e `{"admin","utilizador"}`.
- **Cada tarefa que cria rotas** classifica-as em `PERFIS_POR_ROTA` no passo "teste primeiro".
- **Revisão da tabela contra a §4 do plano (T2.16):** as 21 rotas da F1–F2 conferidas uma a uma com a guarda real (`/saude` pública, `/eu` de sessão, membros e definições só admin, regiões lidas pelo escritório e escritas só pelo admin, lojas, `/config` e morada para o escritório). O teste `test_a_tabela_segue_a_regra_da_api_do_plano` diz a §4 como regra por recurso (`_perfis_pela_regra_da_api`), escrita de outra forma que a tabela: se o código e a tabela mudassem juntos (abrir o `POST /regioes` ao escritório nos dois sítios), só ela dava pela diferença. Um recurso novo (F3+: rotas, encomendas; F4: o motorista) falha esse teste até ter a sua regra.
- **Cron (revisão da F0/F1, AC-1):** "sem sessão" não chega. O teste exige a própria função `crm.auth.exigir_cron_key` em cada rota de `ROTAS_DE_CRON`, por identidade e não pelo nome, e aponta o corpo lido antes dela. A guarda já existe, com testes próprios em `test_cron_key.py`: chave certa, errada, vazia ou em falta, variável em falta ou vazia, lida a cada pedido, chave fora do ASCII → 403 e nunca 500, e `compare_digest` com bytes. Na F5 basta `Depends(exigir_cron_key)` e a classificação.
- **Montagem (T1.9, `tests/crm/test_montagem.py`):** o `server.py` inclui o `crm.router` a seguir às Plataformas e chama `crm.arrancar()` a seguir a `faturacao.arrancar()`. As rotas `/api/crm/*` da app do portal têm de ser exatamente as do `crm.router`, com a mesma função, por isso uma rota do CRM escrita direto no `server.py` não escapa ao teste de proteção.
- **IDOR:** cada pedido verifica a loja, a região ou a rota pelo `id`. Na F4, o motorista só escreve em paragens das suas rotas.

**No frontend:**
- O estado de membro vem de `GET /api/crm/eu`, pedido **uma vez por token** (`lib/crm/eu.js` + `hooks/useEstadoCrm.js`); se falhar, o CRM fica escondido.
  - Com a base em baixo, o `/eu` responde 500 e nunca `membro: false`: um "não" guardava-se para o token inteiro, enquanto uma falha volta a ser perguntada no pedido seguinte (teste `test_eu.py`).
  - A cache (`criarCacheEu`, T1.11) guarda só o token atual: o mesmo token dá um só pedido, também com vários componentes ao mesmo tempo; outro token dá um pedido novo, e a resposta atrasada do antigo não fica; sem token, `EU_NINGUEM` sem pedido (e esquece a resposta anterior).
  - Uma falha, incluindo um 200 sem a forma do `/eu` (o `index.html` de um proxy), dá `EU_NINGUEM` e não se guarda. O próximo componente que montar fica "a carregar" (a guarda espera, não recambia) e volta a perguntar; quando a resposta chega, todos os componentes montados a recebem.
  - **Uma falha não é um "não"** (revisão da F0/F1). O estado de `useEstadoCrm()` é `{carregando, eu, falhou, tentarDeNovo}`.
    - Depois de uma falha, os menus escondem o CRM.
    - A guarda (`decisaoGuardaCrm` / `decisaoSoAdminCrm` em `acesso.js`) não recambia: mostra "Não foi possível confirmar o acesso ao CRM. Verifique a ligação e tente de novo." com os botões "Tentar de novo" (volta a perguntar) e "Voltar ao portal".
    - Na app nativa, ou sem `nativo: false` explícito, recambia como antes.
  - `normalizarEu` segue o backend: um perfil fora da lista não é membro (`EU_NINGUEM`); `admin_master` só com `true` e num admin.
- Nas apps nativas (`Capacitor.isNativePlatform()`), o CRM fica escondido na v1. `podeAbrirAreaCrm` só abre com `nativo: false` explícito: sem a opção, fica escondido.
- As regras de caminho (`lib/crm/acesso.js`) seguem o React Router, que não distingue maiúsculas e aceita barras no fim: `/admin/CRM/mapa/` é do CRM e abre em ecrã cheio. Uma regra `visivel` que rebenta esconde a secção sem deitar abaixo o menu da gestão.
- Quem não é membro e escreve o endereço à mão volta ao início (`/rota` mostra "Sem acesso").
- A interface só esconde; **é o servidor que protege**.

| Conta (local) | Papel no portal | Membro do CRM | O que deve ver (aceitação F1) |
|---|---|---|---|
| Admin local (admin master) | `admin` | `admin` (implícito) | Secção CRM em `/admin`, `/admin/crm/*` e `/crm/*`, com Definições |
| `escritorio.demo` | `gerente` | `utilizador` | Secção CRM sem Definições |
| `gestor.demo` | `gerente` | não | Não vê a secção; ao escrever `/admin/crm/…` volta a `/admin` |
| `colaborador.demo` | `colaborador` | `utilizador` | Item "CRM" na área do colaborador; só a área `/crm` |
| `motorista.demo` | `colaborador` | `motorista` | Nada do CRM na F1–F2 ("Rota do dia" chega na F4) |

---

## 5. Regras de negócio (o coração: reimplementar com fidelidade)

### 5.1 Fases e funil
- `ORDEM = ("perdida", "potencial", "contactada", "amostra", "cliente")`: é a ordem das regras automáticas. O `FUNIL` (ordem para mostrar e filtrar) é `potencial, contactada, amostra, cliente, perdida`.
- Cores exatas do pino e nomes no ecrã (o `rotulo` de `lib/crm/fases.js` é a única fonte: filtros, formulário, cartão, ficha e título do pino leem-no daí; o servidor só conhece as chaves). "Contactada" e "Amostra" passaram a "A aguardar amostra" e "Amostra recebida" em 2026-10-13, a pedido do Bruce, sem mudar chaves, cores, `ORDEM`/`FUNIL` nem regras:

  | Fase | Nome no ecrã | Cor | Contorno |
  |---|---|---|---|
  | `potencial` | Potencial | `#cfcfcf` | `#888` |
  | `contactada` | A aguardar amostra | `#f4c20d` | — |
  | `amostra` | Amostra recebida | `#f08a24` | — |
  | `cliente` | Cliente | `#6b2fa3` | — |
  | `perdida` | Perdida | `#1a1a1a` | — |

- `perdida` fica visível no mapa (para se saber que não vale a pena visitar) e pode ser escondida pelo filtro. Só valem os nomes exatos: `"Cliente"` e `" cliente "` são recusados.
- **Só sobe:** as mudanças automáticas só sobem na `ORDEM`. A exceção é "Não interessado", que passa a loja a `perdida` exceto se for `cliente`. **À mão** a fase muda sempre, com um toque na ficha.
- **Cada mudança de fase** atualiza `fase_desde` e cria uma interação `mudanca_fase` com `resultado` `"<antiga>→<nova>"` e o `utilizador_id`. Não mudar a fase não escreve nada no histórico.
- Efeitos automáticos de um resultado (F4/F5, iguais na rota e na ficha):

  | Resultado | Fase (se subir) |
  |---|---|
  | Interessado ou Voltar depois | `contactada` |
  | Amostra deixada | `amostra` |
  | Entregue | `cliente` |
  | Não interessado | `perdida` (exceto `cliente`) |

- **Consistência:** `ORDEM` está numa só linha em `crm/dominio/fases.py` e em `lib/crm/fases.js`. Os dois lados vigiam-se:
  - `backend/tests/crm/test_consistencia_frontend.py` (T2.20) lê o `fases.js` como texto e compara a `ORDEM` e as chaves de `FASES`, cada uma com rótulo e cor `#rrggbb`. Desde a T2.22 lê também o `gps.js` (`LIMITE_PRECISAO_M` e `MENSAGEM_LOCALIZACAO_IMPRECISA`, contra `geo.LIMITE_PRECISAO_M` e `geo.MENSAGEM_GPS`) e o `morada.js` (`MENSAGEM_MORADA_INDISPONIVEL` e `MENSAGEM_MORADA_SUGERIDA_INDISPONIVEL`, contra `morada.PESQUISA_INDISPONIVEL` e `INVERSA_INDISPONIVEL`, as mensagens do 503). Cada constante fica numa só linha `export const <nome> = <valor>;` (um inteiro, ou um texto entre plicas ou aspas, sem escapes); o leitor é provado primeiro com amostras boas e más;
  - o último teste do `fases.test.js` lê o `fases.py`.
  - Os dois falham, e não saltam, se o ficheiro do outro lado faltar. Nunca se copia a lista para dentro de um teste.

### 5.2 Campos de uma loja
Os campos aceites, pela ordem dos erros, são: `nome, fase, regiao_id, morada, codigo_postal, localidade, lat, lng,
origem_coords, precisao_m, telefone, pessoa_contacto, instagram, site, notas, janela1_inicio, janela1_fim,
janela2_inicio, janela2_fim, dias_fechada` (20: os 18 do autónomo mais `instagram` e `site`, acrescentados em
2026-10-13 a pedido do Bruce). Os campos que o servidor decide (`id`, `criado_por`, `fase_desde`, …) ignoram-se.

| Campo | Regra | Mensagem |
|---|---|---|
| `nome` | Obrigatório, aparado, até 150 caracteres | "Indique o nome." |
| `fase` | Obrigatória, um nome exato da `ORDEM` | "Indique a fase." / "A fase não é válida." |
| Pino (`lat`, `lng`, `origem_coords`) | Obrigatório; `origem_coords` é `pin_manual`, `gps` ou `geocoder`; coordenadas arredondadas a 6 casas | "Coloque o pino no mapa." / "Indique a origem das coordenadas." / "A origem das coordenadas não é válida." |
| `regiao_id` | Opcional: `None` ou uuid4 em texto; tem de existir | "A região não é válida." / "A região não existe." (verificado **antes** dos duplicados) |
| `morada` | Opcional, até 255 caracteres | — |
| `localidade`, `pessoa_contacto` | Opcionais, até 100 caracteres | — |
| `instagram` (2026-10-13) | Opcional. Aceita um perfil (`@nome` ou `nome`: letras ASCII, algarismos, ponto e sublinhado, 1 a 30, sem acabar em ponto nem ter dois pontos seguidos — revisão de 2026-10-13: um "@perfil." colado ao ponto final de uma frase dava um endereço que não existe) ou um endereço do perfil (`instagram.com/nome`, com ou sem `https://`, `www.` ou `m.`, com ou sem barra final; a query e o fragmento de um link de partilha ignoram-se). Guarda-se sempre `https://www.instagram.com/<nome>/`, com as maiúsculas como escritas. Uma publicação (`/p/…`), outro sítio, espaços, hífens ou acentos são erro; o que não for texto também | "O Instagram tem de ser um perfil válido (ex.: @purplehouse)." |
| `site` (2026-10-13) | Opcional, URL `http(s)` até `SITE_MAXIMO` = 255 caracteres **depois** de normalizar. Um domínio sem esquema (`exemplo.pt/loja`) ganha `https://`; o esquema e a máquina ficam em minúsculas, o caminho não. A máquina tem de ter um domínio de topo só com letras (≥ 2) e etiquetas de letras (também acentuadas), algarismos e hífens (≤ 63, sem hífen nas pontas); um porto é aceite. Espaços (também Unicode), caracteres de controlo, outro esquema (`ftp:`, `mailto:`, `javascript:`), utilizador/senha, IP, ponto final na máquina ou porto inválido são erro; o que não for texto também. Um endereço válido com mais de 255 depois de normalizar diz o limite (revisão de 2026-10-13: o campo da ficha deixa escrever 255 e o `https://` que se junta pode passá-lo; antes dizia "não é válido") | "O site tem de ser um endereço válido (ex.: https://exemplo.pt)." / "O site tem no máximo 255 caracteres." |
| `notas` | Opcional, até 65 535 **bytes** UTF-8 | "As notas são demasiado compridas." |
| `codigo_postal` | Formato `0000-000` só com `[0-9]` | "O código postal tem de ter o formato 0000-000." |
| `telefone` | 9 a 15 algarismos, aceita `+` e espaços; normaliza `" {2,}"`→`" "` e `"^\+ "`→`"+"`; tabulação, hífens, parênteses, `++` e números JSON são erro | "O telefone tem de ter 9 a 15 algarismos (aceita + e espaços)." |
| Textos com tipo errado | — | "Tem de ser texto." |

- **Alteração (PATCH):** só se validam as chaves enviadas, e limpar um opcional grava `None`.
  - A localização vem completa: `lat`, `lng` e `origem_coords` obrigatórios e `precisao_m` opcional. Se faltar alguma, "A localização tem de vir completa (lat, lng e origem_coords)." aparece nas chaves em falta.
  - Uma hora sozinha não se compara.
- **Nome e telefone são sempre escritos pela pessoa** (nunca copiados de serviços de terceiros). A Geoapify só sugere morada, código postal e localidade, e só preenche campos vazios.
- **Em `crm/dominio/campos_loja.py` (T2.4, porta do `CamposLoja.php`).** Cada função devolve `(valor normalizado, erro)`. Vazio (`""` ou só espaços, também os Unicode) ou `None` fica `None`.
  - `texto(valor, rotulo, maximo)` conta caracteres (`len`): 255 "é" cabem na morada. A mensagem é "{rótulo} tem no máximo {máximo} caracteres.". Os rótulos e tamanhos (`TEXTOS` do `ValidadorLoja`) ficam no `validador_loja` (T2.5).
  - `notas` conta bytes UTF-8 (até 65 535).
  - `codigo_postal` usa `[0-9]{4}-[0-9]{3}` com `fullmatch`. O que não for texto dá a mensagem do formato, e não "Tem de ser texto.".
  - `telefone`:
    - primeiro junta os espaços seguidos (só o U+0020) e depois tira o espaço a seguir ao `+`, por esta ordem: `"+  351"` fica `"+351"`;
    - conta os algarismos ASCII e valida com `\+?[0-9]+( [0-9]+)*`;
    - o que não for texto dá a mensagem do telefone.
  - `dias_fechada` devolve uma lista nova pela ordem de `DIAS` (o `ValidadorLoja::DIAS` do PHP passou para aqui). Os desconhecidos são verificados antes dos repetidos.
  - `site` e `instagram` (2026-10-13, sem par no PHP): as regras da tabela acima. O `site` apara, recusa espaços e controlo, junta `https://` quando não há `esquema://`, lê com `urllib.parse.urlsplit` (esquema `http`/`https`, sem utilizador nem senha, porto válido, máquina pelo `_MAQUINA` com `fullmatch`) e devolve o `urlunsplit` com o esquema e a máquina em minúsculas, até `SITE_MAXIMO` (acima disso, `_SITE_COMPRIDO`, "O site tem no máximo 255 caracteres."). O `instagram` apara, recusa espaços e controlo, tira o endereço do perfil quando é um (`_INSTAGRAM_URL`), tira um `@` inicial e exige `(?!.*\.\.)[A-Za-z0-9._]{0,29}[A-Za-z0-9_]` (`fullmatch`: 1 a 30, sem acabar em ponto nem `..`); só o domínio sem perfil é erro. Nos dois, o que não é texto dá a mensagem do campo (como no telefone), e não "Tem de ser texto.".
  - Conferido com o `CamposLoja` do PHP 8.4.26 em 116 106 entradas aleatórias, mais todas as entradas das tabelas dos testes: tudo igual.
- **Em `crm/dominio/validador_loja.py` (T2.5, porta do `ValidadorLoja::criacao`).**
  - Nomes: `CAMPOS` (tuplo, a ordem da tabela acima), `ORIGENS`, `NOME_MAXIMO = 150`, `TEXTOS` (`morada` 255, `localidade` e `pessoa_contacto` 100, com os rótulos das mensagens) e `criacao(corpo)` → `(dados, erros)`. Os auxiliares (`_validar`, `_campo`, `_localizacao`, `_coordenada`, `_ordenar`…) são internos; a T2.6 junta-lhes o `alteracao`.
  - Os dados têm sempre os 20 campos de `CAMPOS`, por essa ordem; os erros vêm também pela ordem de `CAMPOS`, incluindo os das janelas (o `Janelas::erros` dá o fim da janela 2 antes do "Preencha primeiro a janela 1."; o validador volta a ordenar). As chaves que não são de `CAMPOS` ignoram-se, também as parecidas (`"Nome"`, `" nome"`).
  - Com erro, os dados ficam como no PHP (e não se usam): o nome que não é texto fica `""`, o nome comprido fica aparado, a coordenada fora de Portugal fica arredondada; a fase, a região e a origem inválidas ficam `None`.
  - Coordenadas: `None` → "Coloque o pino no mapa."; o que não for `e_numero_json` (bool, texto, lista, objeto, nan, inf, inteiro que nem num float cabe) → "A latitude/longitude tem de ser um número."; depois `arredondar(valor, 6)` e só então `contem_*` (42,1999995 → 42,2 dentro; 42,2000005 → 42,200001 fora; o `round` do Python dava 42,199999).
  - Origem: só `pin_manual`, `gps` ou `geocoder` tal e qual (`" gps"`, `"GPS"`, `True`, `["gps"]` → "não é válida"; `None` e `""` → "Indique a origem das coordenadas."). A precisão só se lê com a origem exatamente `"gps"`: aceite (`geo.precisao_aceitavel`) guarda-se `int(arredondar(p))` (12,5 → 13, −0,0 → 0); senão "Localização imprecisa — ajuste o pino". Com outra origem, ou com uma origem inválida, `precisao_m` fica `None` e não dá erro, seja o que for que venha.
  - Janelas: só se comparam (`janelas.erros`) se nenhuma das quatro horas tiver erro; as horas que não são texto dão o erro do formato e nunca chegam ao `TypeError` do `janelas.erros`.
  - **Adaptação do portal:** `regiao_id` é `None` ou um uuid4 em texto, tal e qual (`re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")`, o `str(uuid.uuid4())`). O inteiro do autónomo (`1`), `0`, `True`, `"3"`, `""`, maiúsculas, espaços, uuid de outra versão ou variante, listas e objetos (incluindo operadores do Mongo como `{"$ne": None}`) dão "A região não é válida.". Por isso o `regiao_id` validado pode ir direto ao `find_one({"id": regiao_id})` da T2.10, e as regiões (T2.9) e o seed (T2.18) têm de gravar ids com `str(uuid.uuid4())`.
  - Conferido com o `ValidadorLoja::criacao` do PHP 8.4.26 em 80 298 lojas (as 309 entradas das tabelas dos testes, 40 000 aleatórias e 40 000 quase válidas; 20 074 sem erros), comparando os dados e os erros pela ordem e com os tipos: tudo igual. As únicas diferenças são as assumidas: o `regiao_id` inteiro ≥ 1 (3919 casos, só nessa chave) e os dias num objeto (T2.4). Ficaram de fora as entradas que o PHP não recebe (NaN, Infinity).
- **Em `crm/dominio/validador_loja.py` (T2.6, porta do `ValidadorLoja::alteracao`).**
  - `alteracao(corpo)` → `(dados, erros)` só com as chaves de `CAMPOS` que vieram, pela ordem de `CAMPOS`, com as regras da criação (o mesmo `_validar`). Limpar um opcional (`None` ou `""`) dá `None`; os dias, `[]`. `alteracao({})` dá `({}, {})`.
  - Localização: conta a **chave**, mesmo com `None` (o `array_intersect_key` do PHP). Se vier uma das quatro (`lat`, `lng`, `origem_coords`, `precisao_m`), têm de vir `lat`, `lng` e `origem_coords`; a precisão é opcional (sem ela, com `gps`, dá a mensagem do GPS). Se faltar alguma, as que faltam levam `MENSAGEM_LOCALIZACAO_INCOMPLETA` ("A localização tem de vir completa (lat, lng e origem_coords)."), os valores que vieram nem se validam e nenhuma das quatro entra nos dados. Com as três chaves, os dados levam as quatro.
  - As janelas **não se comparam** na alteração, nem com as quatro horas no pedido: a rota (T2.11) junta as horas enviadas às guardadas (`campos_de_janelas`) e só então chama `janelas.erros`, e só se o pedido mexer numa hora. Uma hora que não seja texto dá o erro do formato (nunca `TypeError`).
  - Com os 20 campos no pedido, os dados são iguais aos da criação; os erros também, menos os da comparação das janelas.
  - Conferido com o `ValidadorLoja::alteracao` do PHP 8.4.26 em 80 086 alterações (as 90 entradas das tabelas dos testes e 80 000 aleatórias, com a localização completa, incompleta ou ausente, chaves nulas, estranhas e parecidas; 26 418 sem erros, 20 554 com a localização incompleta): tudo igual, pela ordem e com os tipos. Só difere o `regiao_id` inteiro ≥ 1 (1896 casos, só nessa chave), como na criação.
- **Janelas em lista (T2.6, só do portal):** `janelas_para_lista(loja)` lê as quatro horas (as que faltam contam como `None`) e devolve `[{"inicio", "fim"}]`, 0 a 2, por ordem; `campos_de_janelas(lista)` devolve as quatro horas pela ordem de `janelas.CAMPOS` (`[]` → quatro `None`). Ida e volta sem perda. Só convertem horas já validadas ("HH:MM" ou `None`) e coerentes (`janelas.erros` vazio); `""`, horas por validar, uma janela a meio, a janela 2 sem a 1, mais de 2 janelas, um tuplo, `None`, chaves a mais ou janelas vazias na lista dão `ValueError` (erro de programação: nunca se grava uma janela a meio nem se perde a janela 2 na volta).

- **Rotas e documento das lojas (T2.10, `crm/lojas.py` e `crm/formatar.py`; porta do `LojasControlador` (`listar`, `ver`, `criar`), do `LojasRepositorio::criar` e do `Formatar::loja`/`resumoLoja`; testes em `test_lojas_criar.py`, com todos os casos do `LojasCriarTest.php`, e `test_formatar.py`, com os do `FormatarTest.php`):**
  - **Perfis:** `GET /lojas`, `GET /lojas/{loja_id}` e `POST /lojas` são do escritório (admin e utilizador do CRM). O motorista recebe 403 `sem_permissao` (ganha o POST na F4) e quem não é membro 403 `sem_acesso_crm`.
  - **Ordem do POST** (a do autónomo): o corpo (422 com os campos, sem ler a base) → a região existe (`find_one({"id": regiao_id}, {"_id": 0, "id": 1})` em `crm_regioes`; senão 422 `{"regiao_id": "A região não existe."}`, também com o duplicado confirmado) → duplicados (`find(filtro_candidatos(lat, lng), {"_id": 0, "id": 1, "nome": 1, "lat": 1, "lng": 1})` e a regra exata do `encontrar_duplicados`; 409 `duplicado` "Já existe {nome da mais perto} aqui — é a mesma?" com `lojas`, e nada se grava) → `insert_one`. Só `"confirmar_duplicado": true` confirma (`is True`: `"true"`, `1`, `1.0`, `null`, `[true]` não), e com ele nem se procuram os duplicados.
  - **O que se grava** (`documento_loja(dados, criado_por, agora)`, pela ordem do §3): `id` uuid4 novo; os 20 campos do validador; `lat`/`lng` em `float` com o `loc` `{"type": "Point", "coordinates": [lng, lat]}`; `janelas` com `janelas_para_lista`; os dias pela ordem da semana; os quatro temporizadores a `null`; `criado_por` = o `user_id` da sessão; `fase_desde` = `criado_em` = `relogio.instante(agora)` e `atualizado_em` = `relogio.carimbo(agora)`, do mesmo `agora = relogio.agora()`. As chaves do corpo que o servidor decide (`id`, `_id`, `criado_por`, `criado_em`, `fase_desde`, `atualizado_em`, temporizadores, `loc`, `janelas`, `confirmar_duplicado`) ignoram-se. O 201 é o `loja_api` do documento gravado (sem reler a base); o `GET /lojas/{id}` devolve o mesmo, chave a chave.
  - **Resposta** (`loja_api`, pela ordem de `CAMPOS_API`, a "Loja completa" do §6): sem `_id`, `loc` nem a lista das janelas; janelas planas (`campos_de_janelas`); `lat`/`lng` em `float` (um 39 escrito à mão sai 39.0, o `(float)` do PHP); `precisao_m` em `int` (o `Int64` do Mongo e o double inteiro do mongosh leem-se); os dias pela ordem da semana e sem repetidos (o que o SET do MariaDB fazia). Um documento estragado (janela a meio, dia desconhecido, coordenada em texto, precisão com casas) é `ValueError` (500), nunca uma resposta com outra forma; um campo em falta é `KeyError` — **exceto** `instagram` e `site` (2026-10-13), lidos com `.get`: as lojas gravadas antes não os têm, vêm a `null` e não houve migração (um PATCH noutro campo não os inventa no `$set`).
  - **Lista** (`resumo_loja_api`, pela ordem de `CAMPOS_RESUMO`): projeção `{"_id": 0, "id": 1, "nome": 1, "fase": 1, "regiao_id": 1, "lat": 1, "lng": 1, "telefone": 1, "pessoa_contacto": 1}` (a `pessoa_contacto` desde a revisão de 2026-10-13: o cartão do mapa recebe a loja desta lista, não a ficha, e a linha "Contacto: pessoa · telefone" lê-a daqui; o `ecraMapa.test.js` lê a linha `CAMPOS_RESUMO` do `formatar.py` para o garantir), ordenada em Python por `(chave_comparacao(nome), id)` (o `ORDER BY nome, id` com a collation).
  - **Sem transações:** corridas aceites. Uma região apagada entre a verificação e o `insert_one` deixa um `regiao_id` órfão. Dois pedidos no mesmo sítio ao mesmo tempo gravam-se os dois, porque o duplicado é um aviso e não uma regra da base (também no autónomo); provado no duplo com duas corrotinas.
  - **Conferido no MongoDB 8.0.32 local** (não versionado, `t2.10-conferencia-mongo.log`; base `lisbonb_crm_teste`, apagada no início e no fim), com o Motor e os índices verdadeiros: 18 verificações, todas OK. Entre elas: o documento gravado (tipos, `loc`, janelas, dias, ordem das chaves, instantes), o GET igual ao 201, o `$geoWithin` verdadeiro (10, 30 e 51 m dentro do círculo; longe fora; plano pelo `loc_2dsphere`), o 409 com as lojas a 10 e 30 m sem gravar, a região inexistente, o confirmado, a lista por nome, e o `bson.encode` a rebentar com um surrogate sozinho (`UnicodeEncodeError`, o 500 que o `corpo_json` agora evita com 400).
  - **Diferença assumida:** sem o `Cache-Control: no-store, private` do `aListaEOResumoDeTodasAsLojasPorNome`, como nas regiões (§5.8).

### 5.3 Portugal continental
- Aceita-se `36.8 ≤ lat ≤ 42.2` e `−9.6 ≤ lng ≤ −6.1`, com os limites incluídos. Recusa-se `36.799999`, `42.200001`, a Madeira, os Açores, Madrid, `0` e o sinal trocado.
- Em `crm/dominio/geo.py`: `contem_latitude`, `contem_longitude` e `MENSAGEM_PORTUGAL`. Quem chama valida o número e arredonda às 6 casas antes de perguntar (36.7999996 → 36.8 está dentro; 42.2000005 → 42.200001 está fora). O que não for número JSON (bool, texto, `None`, nan, inf) nunca está em Portugal, em vez de rebentar com `TypeError`.
- A mensagem é exatamente "Fora de Portugal". A pesquisa de morada filtra também `country_code` ≠ `pt` e pontos fora do continente.

### 5.4 GPS ("Estou nesta loja")
- Só se pede a posição **quando a pessoa toca** em "Estou nesta loja": na criação, na ficha e, na F4, no terreno. Opções: `{enableHighAccuracy: true, timeout: 15000, maximumAge: 0}`. **Nunca há seguimento contínuo** e guarda-se só o ponto da loja (Código do Trabalho, RGPD, CNPD).
- A precisão é aceitável se for **≤ 50 m depois de arredondar** meio-para-longe-do-zero: 50, 12, 0 e 50.4 passam; 51, **50.5**, 80, −1, `None`, `"10"`, `True`, inf e nan não. Aceite, a origem fica `gps` e `precisao_m` é inteiro; nas outras origens, `precisao_m` é `None`.
- Em `geo.py`: `precisao_aceitavel`, `LIMITE_PRECISAO_M = 50` e `MENSAGEM_GPS`. `False` também não passa (em Python seria um GPS de 0 m); `-0.0` passa, como no PHP. O valor guardado é `int(arredondar(precisao_m))`.
- Acima de 50 m aparece "Localização imprecisa — ajuste o pino", com o círculo da precisão. O Confirmar fica desativado até a pessoa arrastar o pino, e a origem passa a `pin_manual`.
- Regras do seletor (portadas de `seletor-localizacao.test.js` para `lib/crm/seletor.js`, T2.26):
  - uma posição GPS que chegue depois de o pino mudar é ignorada;
  - a morada sugerida sai quando o pino muda;
  - "A obter a localização…" não volta a pedir;
  - textos "Toque no mapa no sítio da loja." e "Arraste o pino para o sítio exato e confirme.".
- No telemóvel, adicionar uma loja exige rede (botão desativado com "sem rede").

### 5.5 Duplicados a menos de 50 m
- Distância **haversine** com `R = 6 371 000 m`. Por exemplo, Praça do Comércio (38.707500, −9.136400) ↔ Rossio (38.713900, −9.139100) ≈ 750 m (749,216 m). Em `geo.py`: `distancia_metros`, `RAIO_TERRA_M` e `METROS_POR_GRAU` (`RAIO_TERRA_M * pi / 180`, ≈ 111 194,93 m).
- **Duplicado** se a distância exata for **< 50 m** (tolerância 1e-6): 50 m exatos não são.
- `distancia_m` é a distância arredondada, mas **nunca ≥ 50**: 49,6 dá 49, 30,6 dá 31 e 0,4 dá 0. As lojas vêm ordenadas por distância e depois por `id`.
- **Pré-filtro no Mongo:** `{"loc": {"$geoWithin": {"$centerSphere": [[lng, lat], 60 / 6371000]}}}` (60 m, índice `2dsphere`). Na edição junta-se `"id": {"$ne": <própria>}`. A regra exata dos 50 m é aplicada em Python.
- **Em `geo.py` (T2.3):** `RAIO_DUPLICADOS_M` (int 50), `TOLERANCIA_M` (1e-6), `FOLGA_PREFILTRO_M` (10: o círculo do pré-filtro tem `raio + 10` m, no lugar da caixa em graus com 1 m de folga do autónomo); `encontrar_duplicados(candidatos, lat, lng, excluir_id=None, raio=50)` → `[{"id", "nome", "distancia_m"}]`, com `distancia_m` `int` (`int(arredondar(m))`, meio-para-longe-do-zero: 30,5 m mostra-se 31) e as lojas por distância **exata** e depois pelo `id` em texto (duas a 10,4 e 9,6 m mostram-se ambas a 10 m, mas a de 9,6 vem primeiro); `filtro_candidatos(lat, lng, excluir_id=None, raio=50)` devolve um dicionário novo em cada chamada. Os candidatos são os documentos do `find` com `id`, `nome`, `lat` e `lng` (números; outros campos não passam para a resposta), por exemplo com a projeção `{"_id": 0, "id": 1, "nome": 1, "lat": 1, "lng": 1}`. Conferido na T2.3 com o `Duplicados::encontrar` do PHP 8.4.26 (6000 cenários, 22 033 duplicados, empates e casos junto ao raio: iguais) e com o MongoDB 8 local (os mesmos cenários dão o mesmo resultado com e sem o pré-filtro; pontos até 59 m sempre dentro, a 61 m sempre fora; o plano usa o índice `loc_2dsphere`).
- Na edição, só se procuram duplicados se as coordenadas mudarem nas 6 casas.
- A resposta é 409 `duplicado`: "Já existe {nome} aqui — é a mesma?" com `lojas: [{id, nome, distancia_m}]`. Só `confirmar_duplicado: true` (o booleano JSON) grava; `"true"`, `1` e `None` não confirmam.
- O diálogo tem **3 botões**: "Sim, abrir X", "Não, é outra loja" (reenvia com `confirmar_duplicado: true`) e "Cancelar".

### 5.6 Horário de receção (janelas)
- Até 2 janelas, por exemplo 10:00–13:00 e 15:00–19:00. Sem janelas, a loja recebe a qualquer hora do dia de trabalho.
- As horas validam-se com `re.fullmatch(r"([01][0-9]|2[0-3]):[0-5][0-9]")`: `"10:00\n"`, `1000`, `True` e `["10:00"]` são recusados.
- Mensagens exatas:
  - "A hora tem de estar no formato HH:MM."
  - "Indique também o fim." / "Indique também o início."
  - "O fim tem de ser depois do início."
  - "Preencha primeiro a janela 1."
  - "A janela 2 tem de começar depois do fim da janela 1."
- As janelas só se comparam quando as 4 horas são válidas. No PATCH, as horas guardadas só se verificam se o pedido mexer numa hora.
- **Em `crm/dominio/janelas.py` (T2.4, porta do `Janelas.php`):**
  - `CAMPOS` são as 4 horas, por ordem, e `MENSAGEM_FORMATO` é a mensagem do formato.
  - `hora(valor)` devolve `(hora, erro)`. Só `""` e `None` contam como "sem hora". A hora não se apara: `" 10:00"` é um erro.
  - `erros(loja)` devolve `{campo: erro}`, vazio se tudo estiver bem.
    - As chaves em falta contam como `None`.
    - Os erros vêm pela ordem em que o PHP os junta. O `+=` do PHP não substitui um erro que já existe, por isso usa-se `setdefault`: uma janela 2 só com o fim dá "Indique também o início.", e não "Preencha primeiro a janela 1.".
    - As horas têm de vir validadas. Uma que não seja texto nem `None` levanta `TypeError`, como o `?string` do PHP em modo estrito.
    - Compara-se o texto, porque "HH:MM" tem largura fixa.
  - Conferido com o `Janelas` do PHP 8.4.26 em 90 026 entradas: todas as 10 000 combinações "NN:NN", 20 000 horas aleatórias e 60 000 lojas com horas e chaves em falta. Tudo igual, incluindo os `TypeError`.
- **Na base** as janelas ficam em lista: a conversão é `validador_loja.janelas_para_lista` / `campos_de_janelas` (T2.6, §5.2). Verificado em 300 000 combinações aleatórias e 100 000 coerentes de propósito: as coerentes dão ida e volta igual, as outras são recusadas.

### 5.7 Dias fechada
- Lista de `seg, ter, qua, qui, sex, sab, dom`, guardada pela ordem da semana; `None` dá `[]`.
- Mensagens: "Os dias têm de ser seg, ter, qua, qui, sex, sab ou dom." e "Há dias repetidos.".
- **Diferença assumida (T2.4):** só uma lista JSON conta (`array_is_list` → `isinstance(x, list)`, plano §10). O `json_decode` associativo do PHP transformava `{}` em `[]` e `{"0": "sab"}` em `["sab"]`, e o autónomo aceitava-os. Aqui qualquer objeto é sempre a mensagem dos dias. O browser envia sempre uma lista.
- Na F3, uma paragem numa loja fechada nesse dia fica com o aviso "Fechada neste dia" e não entra no cálculo até o escritório decidir.

### 5.8 Regiões
- `nome` com 1 a 100 caracteres ("Indique o nome."), **único sem maiúsculas nem acentos** (índice único em `nome_chave`; repetida → 409 "Já existe uma região com este nome.").
  - No PATCH, procura-se com `{"nome_chave": k, "id": {"$ne": regiao_id}}`: corrigir as maiúsculas do próprio nome ("setubal" → "Setúbal") não é repetição.
- `ordem`: inteiro JSON em `[-2147483648, 2147483647]`, 0 por omissão. `"1"`, `1.5`, `1.0`, `None`, `True` e `[1]` dão "A ordem tem de ser um número inteiro.".
- `GET /regioes` ordena por `(ordem, chave_comparacao(nome), id)`.
- **Em `crm/dominio/regioes.py` (T2.7, porta do `RegrasRegioes` e do `RegioesControlador::validar`):**
  - Nomes: `NOME_MAXIMO = 100`, `ORDEM_MINIMA`/`ORDEM_MAXIMA` (os limites de um INT), `ORDEM_POR_OMISSAO = 0`, `MENSAGEM_NOME`, `MENSAGEM_ORDEM`, `erro_nome`, `erro_ordem`, `nome_chave`, `criacao` e `alteracao`.
  - `erro_nome(nome)` recebe o nome já aparado ("   " não é vazio aqui) e conta caracteres (`len`, o `mb_strlen`); um nome que não seja texto é `TypeError`, como o `string` do PHP em modo estrito.
  - `erro_ordem(ordem)`: `e_inteiro_json` e os limites; `True`, `False`, `1.0`, `-0.0`, `"1"`, `2**31`, `2**63` e o NaN/Infinity do `json.loads` são recusados.
  - `nome_chave(nome)` é a `texto.chave_comparacao` (a mesma que ordena): "Setúbal", " SETUBAL" e o "Setúbal" com o acento à parte (NFD) dão "setubal"; os espaços do meio contam ("Vila  Real" ≠ "Vila Real"). Grava-se com a região, a partir do nome validado.
  - `criacao(corpo)` (POST) e `alteracao(corpo)` (PATCH) → `(campos, erros)`, as duas pela ordem nome, ordem. Só contam as chaves enviadas, mesmo com null (`{"nome": None}` dá "Indique o nome."). O nome é aparado (também U+FEFF e os espaços Unicode) e o que não é texto fica `""` ("Indique o nome."). As outras chaves (`id`, `nome_chave`, `"Nome"`…) ignoram-se. Na criação, a ordem é 0 por omissão e o que vem no corpo ganha, mesmo um null. Os campos só se usam sem erros.
  - **Para a T2.9:** `campos, erros = regioes.criacao(corpo)` → 422 com `erros`; senão gravar `{"id": str(uuid4()), **campos, "nome_chave": nome_chave(campos["nome"])}`. No PATCH, `nome_chave` só se recalcula quando `"nome"` vem nos campos.
  - Conferido com o PHP 8.4.26 (`RegrasRegioes` e `RegioesControlador::validar` por reflexão): 20 017 nomes, 20 026 ordens e 40 090 corpos (criação e alteração), com as entradas das tabelas dos testes, sem diferenças. As únicas diferenças são as já assumidas na T1.3 (U+001C–U+001F nas pontas: o Python também os apara; 125 casos).
- **Apagar só sem lojas.** Com lojas: 409 `regiao_com_lojas` "Esta região tem lojas — mude-lhe o nome em vez de a apagar.". As lojas sem região aparecem como "Sem região" nos filtros.
  - **Nos filtros do mapa (T2.21, `lib/crm/filtros.js`):** "Sem região" mostra só as lojas com `regiao_id` nulo ou sem o campo. Uma loja com um `regiao_id` órfão (a corrida aceite na T2.9) só aparece em "Todas". Quando a lista das regiões chega, uma região guardada que já não existe volta a "Todas" (`ajustarARegioes`, com `mudou: true` para se guardar). Até lá, essa região aparece como "Região guardada" (`opcoesRegiao`).
- **Rotas (T2.9, `crm/regioes.py`, porta do `RegioesControlador` e do `RegioesRepositorio`; testes em `test_regioes.py` com todos os casos do `RegioesTest.php`):**
  - **Ordem das verificações** (a do autónomo): o corpo (422, sem ler a base) → a região existe (404; lá era o `bloquear`) → o nome é de outra região (409) ou a região tem lojas (409) → a escrita. Uma região que não existe dá 404 mesmo com o nome de outra ou com lojas que ainda a apontem.
  - **O que se grava:** `{id: str(uuid.uuid4()), nome, nome_chave, ordem}`. A `nome_chave` vem sempre do nome; a do corpo ignora-se, tal como `id`, `_id` e chaves parecidas. O `$set` do PATCH leva só o que veio (`{"ordem": 0}` não toca no nome), e a `nome_chave` só se recalcula quando vem o nome. Um PATCH sem `nome` nem `ordem` (`{}` ou só chaves desconhecidas) devolve a região tal como está e não escreve, porque o Mongo recusa um `$set` vazio.
  - **Resposta do PATCH (revisão da F2):** grava e lê numa só operação, `find_one_and_update({"id"}, {"$set"}, projection=PROJECAO_REGIAO, return_document=ReturnDocument.AFTER)` (`None` → 404), e responde com a região como ficou logo a seguir à escrita. O autónomo respondia com `array_replace($antes, $alteracoes)`, mas com a linha bloqueada (`FOR UPDATE`); aqui, sem bloqueio, o `{**antes, **campos}` podia trazer o valor velho do campo que outro admin mudou entretanto (ex.: um muda a ordem, outro o nome, e a resposta da ordem trazia o nome antigo). Provado no duplo (`test_o_patch_responde_com_a_regiao_como_ficou_gravada`, `test_dois_admins_a_mudar_campos_diferentes_da_mesma_regiao_ao_mesmo_tempo`) e no MongoDB local com a barreira da T2.17 (`test_dois_patch_a_campos_diferentes_da_mesma_regiao_respondem_com_o_que_ficou_gravado`). O duplo ganhou `find_one_and_update` (sem upsert). O seed (T2.18) tem de gravar a mesma forma: sem `nome_chave`, a segunda região colide no índice único (dois null).
  - **Nomes repetidos:** verificam-se antes de gravar (`find_one({"nome_chave": k})`; no PATCH com `"id": {"$ne": regiao_id}`), para valerem também sem o índice único (o CRM arranca sem índices se o Mongo falhar). Na corrida, o `DuplicateKeyError` do `insert_one`/`find_one_and_update` só dá 409 quando uma nova procura encontra **outra** região com a chave; senão sobe (500) em vez de se disfarçar de repetido (correções, linha "T2.9"). Provado no duplo com duas corrotinas ao mesmo tempo (criar e mudar o nome) e no MongoDB 8.0.32 local (abaixo).
  - **Sem transações:** uma região apagada entre a leitura e a escrita dá 404 (o `find_one_and_update` nunca tem upsert, por isso não a ressuscita). Apagar faz: existe (404) → `count_documents({"regiao_id": id})` em `crm_lojas`, pelo índice `regiao_id_1` (409) → `delete_one` (`deleted_count 0` → 404). **Corrida residual aceite:** uma loja gravada nessa região entre a contagem e o `delete_one` fica com um `regiao_id` que já não existe. As lojas (T2.10/T2.11) verificam a região ao gravar, e os filtros do mapa (T2.25) têm de tolerar um `regiao_id` órfão.
  - **`GET`:** projeção `{"_id": 0, "id": 1, "nome": 1, "ordem": 1}` (nunca a `nome_chave`), ordenado em Python por `(ordem, chave_comparacao(nome), id)`. O desempate pelo `id` (texto) só se vê sem o índice único. O motorista não lista regiões na F2 (403 `sem_permissao`).
  - **Conferido no MongoDB 8.0.32 local** (não versionado, `t2.9-conferencia-mongo.log`; base `lisbonb_crm_teste`, apagada no início e no fim), com as funções das rotas e o Motor: 19 verificações, todas OK. Entre elas:
    - os índices verdadeiros;
    - o `DuplicateKeyError` verdadeiro do insert e do update (`keyPattern {"nome_chave": 1}`) tratado como 409 sem mudar nada;
    - duas criações e dois nomes iguais ao mesmo tempo (uma grava);
    - corrigir o próprio nome e o PATCH vazio;
    - a lista;
    - a contagem das lojas pelo `regiao_id_1` e a procura de repetidos pelo `nome_chave_1`.
  - **Diferença assumida:** o autónomo mandava `Cache-Control: no-store, private` em todas as respostas da API (`Resposta.php`; o `RegioesTest` verificava-o na lista). O portal não manda esse cabeçalho em nenhuma rota da API, e o CRM segue o portal por agora (as respostas não têm `Last-Modified`, por isso o browser não as reaproveita). Fica para decidir na revisão da F2 se o CRM o acrescenta a todas as suas respostas (sucesso e erro) num só sítio do pacote, sem tocar no `server.py`.
- **Ecrã:**
  - "Adicionar" envia `{nome, ordem: proximaOrdem(lista)}`.
  - "Subir"/"Descer" troca com a vizinha, **renumera a lista toda 0..n−1** (`reordenarRegioes`) e envia só as que mudaram, um pedido de cada vez; se falhar, volta a pedir a lista.
  - O desempate no ecrã é ordem → nome (`Intl.Collator('pt', {sensitivity: 'base'})`) → id.

### 5.9 Definições (F2: a fábrica; F3: as rotas)
- **F3 (T3.5, T3.15):** mais 6 chaves, guardadas em texto como as da fábrica: `rota_hora_saida '08:00'`, `rota_hora_regresso '19:00'` ("HH:MM", hora de Lisboa; vazia ou mal escrita dá "Indique a hora no formato HH:MM.") e `servico_{entrega,amostra,acompanhamento,angariacao}_min` ('10', '10', '15', '15'; no PATCH um inteiro do JSON de 1 a 240, "O tempo de serviço é um número inteiro de minutos, de 1 a 240."). O `combinar` devolve os minutos como `int` e, se um valor guardado estiver estragado, o padrão dessa chave. **Coerência (T3.15, `dominio.definicoes.coerencia`):** só quando o PATCH traz `rota_hora_saida` ou `rota_hora_regresso`, a rota junta as definições em vigor (`em_vigor`) com as horas do pedido e, se o regresso não for depois da saída (a mesma hora também), responde 422 `{"rota_hora_regresso": "A hora de regresso tem de ser depois da hora de saída."}` antes da primeira escrita (nem o relógio se lê). Os erros dos campos vêm antes e, com eles, a base nem se lê. Um PATCH só da fábrica ou dos minutos nunca recebe 422 por causa das horas guardadas (como as janelas da loja, `semMexerNasJanelasNaoSeVerificamAsGuardadas`).
- Padrões no código: `fabrica_morada ''` (até 255 caracteres), `fabrica_lat '38.722300'`, `fabrica_lng '-9.139300'`. Guardam-se em texto, com as coordenadas a 6 casas (`'%.6f'`), e só o que o admin alterou (upsert por `chave`).
- `lat` e `lng` vão sempre juntas: "Indique também a longitude." / "Indique também a latitude.".
- Uma chave desconhecida dá "Esta definição não existe.". As chaves guardadas que a versão não conhece ignoram-se ao ler.
- **Em `crm/dominio/definicoes.py` (T2.7, porta do `Definicoes`):**
  - Nomes: `PADROES` (um `MappingProxyType` só de leitura, pela ordem morada, lat, lng), `MORADA_MAXIMO = 255`, `MENSAGEM_DESCONHECIDA`, `combinar` e `alteracao`.
  - `combinar(guardadas)` → `{"fabrica_morada", "fabrica_lat", "fabrica_lng"}`, com as coordenadas em `float` e sempre por esta ordem. A morada sai tal e qual. As coordenadas guardadas leem-se como o `(float)` do PHP: o número do início do texto, ou 0,0 se não houver (" 38.7" e "38.7abc" → 38,7; "abc", "inf", "nan", "١٢" → 0,0; "1_000" → 1,0; "1e400" → infinito). Nunca rebenta com um texto. Um número escrito à mão na base lê-se como número; `None`, um bool, uma lista ou um objeto dão `TypeError` (o CRM só grava texto).
  - `alteracao(pedido)` → `(valores para gravar, erros)`, os dois pela ordem dos `PADROES` e depois as chaves desconhecidas, pela ordem em que chegaram.
    - A morada é aparada; vazia ou null fica `""`; o que não é texto dá "Tem de ser texto."; mais de 255 caracteres dá "A morada tem no máximo 255 caracteres.".
    - Uma coordenada tem de ser um número do JSON. Bool, texto, null, NaN, inf, `1e400` e um inteiro sem fim dão "A latitude/longitude tem de ser um número." (valor `""`). É arredondada meio-para-longe-do-zero às 6 casas (38,7223445 → "38.722345"), só depois vista contra Portugal, e escrita com 6 casas; o −0,0 sai "0.000000", como no `sprintf` do PHP.
    - O par conta a chave, mesmo com null: `{"fabrica_lat": None}` dá o erro do número na latitude e "Indique também a longitude.". Chaves parecidas (`"Fabrica_lat"`, `"fabrica_lat "`) são desconhecidas e não fazem o par.
    - Com erros, os valores ficam como no PHP (`""` ou o texto arredondado), mas não se gravam.
  - **Diferença assumida:** o PHP convertia a chave `"0"` num inteiro; se fosse o único erro, o `campos` saía como lista JSON (`["Esta definição não existe."]`). Aqui sai sempre um objeto (`{"0": …}`).
  - **Usado pela T2.13** (rotas abaixo): `guardadas = {d["chave"]: d["valor"] …}` com a projeção `{"_id": 0, "chave": 1, "valor": 1}`; sem erros, cada par de `valores` grava-se com `update_one({"chave": c}, {"$set": {"valor": v, "atualizado_em": …, "atualizado_por": …}}, upsert=True)`; a resposta é o `combinar` relido. O centro do mapa (`/config`) é `[fabrica_lat, fabrica_lng]` do `combinar`.
  - Conferido com o PHP 8.4.26: 20 071 pedidos de alteração (16 448 com erros, 3623 sem) e 20 051 conjuntos guardados para o `combinar`, com as entradas das tabelas dos testes, comparando valores, tipos (os `float` ao bit) e a ordem das chaves, sem diferenças. As únicas diferenças são as da T1.3 (U+001C–U+001F nas pontas da morada; 73 casos).
- **Rotas (T2.13, `crm/definicoes.py`, porta do `DefinicoesControlador` e do `DefinicoesRepositorio`; testes em `test_definicoes.py` com todos os casos do `DefinicoesTest.php`):**
  - **`GET /definicoes`** e **`PATCH /definicoes`**, só para o admin do CRM (admin master e membros admin). O utilizador e o motorista recebem 403 `sem_permissao`, sem se ler a coleção.
  - **Ordem do PATCH:** a guarda → o corpo (400 `json_invalido`) → `dominio.definicoes.alteracao` (422 com os erros, sem tocar na base nem no relógio) → uma escrita por chave → reler e responder com o `combinar`. Um PATCH vazio (`{}` ou sem corpo) não escreve nada e devolve as definições em vigor (200).
  - **O que se grava:** `{chave, valor (texto), atualizado_em, atualizado_por}`, com `update_one({"chave": c}, {"$set": {"valor", "atualizado_em", "atualizado_por"}}, upsert=True)`. Uma linha por chave (índice único em `chave`; nunca `id`). O `atualizado_em` é `relogio.carimbo(agora)`, com um só `relogio.agora()` por pedido, por isso as chaves do mesmo pedido ficam com a mesma hora (o `$quando` do repositório). O `atualizado_por` é o `user_id` da conta do portal. Gravar o mesmo valor outra vez dá 200 e muda a hora.
  - **Sem transações (o autónomo gravava tudo numa):** as chaves gravam-se pela ordem dos `PADROES` (morada, lat, lng).
    - Uma falha a meio dá 500 e deixa gravadas as anteriores. Repetir o mesmo pedido acerta, porque os upserts são idempotentes. Testado no duplo.
    - **Diferença assumida:** dois admins a mudar o ponto ao mesmo tempo podem deixar a latitude de um e a longitude do outro. Cada coordenada foi vista contra Portugal continental (a caixa é por coordenada), por isso o ponto fica sempre lá dentro. Testado no duplo com duas corrotinas. Um admin só, que é o caso real, nunca o vê.
  - **Leitura única, `em_vigor(base)`:** `find({}, {"_id": 0, "chave": 1, "valor": 1})` e o `combinar`. Partilhada com o `GET /config`. Uma linha estragada à mão (sem `chave` de texto, ou com um `valor` null, bool, lista ou objeto) ignora-se, com uma linha `[crm]` no registo só com a contagem ("definições guardadas ignoradas por estarem estragadas: N"). Sem isto, o `combinar` dava `TypeError` (500), e todo o escritório ficava sem mapa por causa de uma linha. Um número escrito à mão continua a ler-se como número (T2.7). Fica de fora um texto como "1e400", que o `combinar` lê como infinito e o JSON recusa (500); só pode lá estar escrito à mão.
  - **Conferido no MongoDB 8.0.32 local** (não versionado, `t2.13-conferencia-mongo.log`; base `lisbonb_crm_teste`, apagada no início e no fim), com as funções das rotas e o Motor: 14 verificações, todas OK. Entre elas:
    - os índices verdadeiros (`_id_` e `chave_1` único);
    - os documentos gravados, com o carimbo de 6 casas, igual nas três chaves;
    - um segundo PATCH substitui, com uma linha por chave;
    - 20 PATCH ao mesmo tempo sobre a coleção vazia não dão `DuplicateKeyError` (o Mongo repete sozinho o upsert que colide no índice único) e deixam uma linha por chave;
    - o upsert pela chave usa o `chave_1`;
    - uma linha estragada é ignorada;
    - o `/config` com e sem chave.
  - **Diferença assumida:** sem o `Cache-Control: no-store, private` do autónomo (a mesma da T2.9, §5.8).
- **Ecrã:** só muda o ponto se mudar nas 6 casas, com lat e lng juntas (`corpoFabrica`, `estadoGuardarFabrica`, `textoPonto`). O seletor da fábrica não tem GPS.
- **Futuras (F3–F5, original §5):**

  | Definição | Padrão |
  |---|---|
  | Hora de saída / regresso | 08:00 / 19:00 |
  | Raio das sugestões | 5 km |
  | Distância ao percurso | 3 km |
  | Dias sem repetir uma sugestão | 7 |
  | Alerta de amostra / de cliente | 7 / 30 dias |
  | Tempo de serviço: entrega / amostra / acompanhamento / angariação | 10 / 10 / 15 / 15 min |
  | Bloco de paragens no Google Maps | 9 |

### 5.10 Edições simultâneas (bloqueio otimista)
- `update_one({"id": id, "atualizado_em": versao}, {"$set": …})`. Se `matched_count == 0`, relê-se: inexistente → 404; existente → 409 `conflito` "Alterado por outra pessoa — recarregar". Só se enviam os campos alterados.
- A versão é `relogio.ler_carimbo(corpo.get("atualizado_em"))`: `None` dá 422 em `atualizado_em` com "Indique o atualizado_em que recebeu com a loja." (`LojasControlador::alterar`), junto com os erros dos campos. A versão nova é `relogio.proximo_carimbo(relogio.agora(), versao)`, calculada só depois de a versão lida ser igual à guardada (§3, carimbos).
- **Ordem das verificações no PATCH de uma loja** (como `LojasControlador::alterar`):
  1. 422 dos campos, junto com o do `atualizado_em`;
  2. ler a loja (404);
  3. versão diferente → 409 `conflito`;
  4. janelas contra as horas guardadas, só se o pedido mexer numa hora;
  5. a região existe;
  6. duplicados, só se as coordenadas mudarem nas 6 casas;
  7. atualização condicional (rede para corridas).

  Uma versão velha com coordenadas junto de outra loja dá **409 `conflito`**, sem procurar duplicados.
- **Fase num toque** (`lib/crm/ficha.js`, portado de `loja.test.js`):
  - um pedido de cada vez, e dois toques seguidos gravam o último já com a versão nova;
  - a resposta só atualiza `fase` e `atualizado_em`, e o que se escreveu noutros campos continua por guardar;
  - sem rede, a fase fica escolhida e segue no Guardar; um 409 mostra a faixa de conflito;
  - voltar a escolher a fase guardada não grava nada;
  - textos: "Fase guardada", "Alterações guardadas", "Loja apagada", "Guardar — sem rede".
- **Rotas (T2.11, `crm/lojas.py::alterar_loja`; porta do `LojasControlador::alterar` e do `LojasRepositorio::atualizar`; testes em `test_lojas_editar.py`, com todos os casos de edição do `LojasEditarTest.php` e os do `atualizar` do `LojasRepositorioTest.php`, com os nomes de lá):**
  - **Perfis:** `PATCH /lojas/{loja_id}` é do escritório (admin e utilizador do CRM; classificada em `PERFIS_POR_ROTA`). O motorista recebe 403 `sem_permissao` (as correções do terreno chegam na F4) e quem não é membro 403 `sem_acesso_crm`. A guarda vem antes do `corpo_json`: sem sessão e com JSON partido dá 403/401, nunca 400.
  - **Comparação antecipada:** a versão lida (`find_one({"id"}, {"_id": 0})`) compara-se com a do pedido logo a seguir à leitura, antes das janelas, da região e dos duplicados (o autónomo bloqueava a linha com `FOR UPDATE`). Assim, com uma versão velha, nunca se calcula um 422 de janelas ou um 409 duplicado sobre as horas ou o sítio de outra versão.
  - **Janelas:** só se o pedido trouxer alguma das quatro horas. Juntam-se as enviadas às guardadas (`campos_de_janelas(loja["janelas"])`), verifica-se com `janelas.erros` (422 nas horas, pela ordem do `Janelas::erros`, como o `exigirJanelas` do autónomo, que não as reordenava) e grava-se `janelas: janelas_para_lista(juntas)`. As horas planas nunca vão para a base. Sem horas no pedido, as guardadas nem se leem (`semMexerNasJanelasNaoSeVerificamAsGuardadas`; no portal uma janela a meio nem chega à base, por isso o teste prova que não se leem).
  - **Região:** só se o pedido trouxer `regiao_id` não nulo (`null` = sem região), com a mesma verificação do POST.
  - **Duplicados:** só se as coordenadas mudarem nas 6 casas que a base guarda (`"%.6f"` dos dois lados, o `sprintf('%.6F')` do `mudouDeSitio`; lê também um inteiro ou um valor com mais casas escrito à mão), com `filtro_candidatos(lat, lng, excluir_id=loja_id)` e a regra exata sem a própria loja; `"confirmar_duplicado": true` (só o booleano) salta-os.
  - **O `$set`:** só os campos que vieram, como a base os guarda: as coordenadas SEMPRE com o `loc` (`documento_localizacao`) mais `origem_coords` e `precisao_m`; as janelas em lista; os dias pela ordem da semana; limpar um opcional grava null (os dias, `[]`). Com a fase nova, `fase_desde = relogio.instante(agora)`. Sempre `atualizado_em = relogio.proximo_carimbo(agora, versao)`, por isso um PATCH só com o `atualizado_em` grava só a versão nova e o `$set` nunca vem vazio. O relógio lê-se uma só vez por pedido (o mesmo `agora` no `fase_desde`, na `ocorrida_em` e na versão). As chaves que o servidor decide (`id`, `_id`, `criado_*`, `fase_desde`, temporizadores, `loc`, `janelas`) ignoram-se.
  - **Atualização condicional:** `update_one({"id": loja_id, "atualizado_em": versao}, {"$set": …})`, sem upsert. Com `matched_count == 0` relê-se com `{"_id": 0, "id": 1}`: inexistente → 404 (a loja apagada entretanto não ressuscita), existente → 409 `conflito`. Provado no duplo com uma loja alterada e outra apagada entre a leitura e o `update_one`, e com duas alterações a sério ao mesmo tempo (uma grava, a outra 409, uma só interação).
  - **Resposta:** o `loja_api` da loja lida com o `$set` aplicado (sem reler a base: é exatamente a versão que a atualização condicional gravou); igual ao `GET /lojas/{id}` seguinte, chave a chave.
  - **Conferido com o PHP 8.4.26** (não versionado, `t2.11-conferencia-php.log`): 30 010 casos (as entradas das tabelas e 30 000 aleatórios) passados pelo `ValidadorLoja::alteracao` + `Formatar::lerInstanteMicro` e, por reflexão, pelo `exigirJanelas` e pelo `mudouDeSitio` do `LojasControlador`, sobre a linha da base: o 422 do corpo (com o do `atualizado_em` no fim), as janelas (não verificadas / erros pela ordem / as quatro horas que ficam) e o "mudou de sítio" iguais em todos.
  - **Conferido no MongoDB 8.0.32 local** (não versionado, `t2.11-conferencia-mongo.log`; base `lisbonb_crm_teste`, apagada no início e no fim), com o Motor e os índices verdadeiros: 21 verificações, todas OK. Entre elas: a versão nova gravada igual à resposta e ao GET, a ordem das chaves que o `$set` não muda, o 409 com a versão velha sem mudar nada, o `$geoWithin` com o `$ne` verdadeiro (só a vizinha, pelo `loc_2dsphere`), `lat`/`lng`/`loc` gravados juntos e encontrados no sítio novo, as janelas, duas interações sem `client_uuid` que não colidem no índice parcial, a linha do tempo pelo `loja_id_1_ocorrida_em_1`, o filtro condicional pelo `id_1`, a corrida com o Motor (200 e 409, uma só interação nova), o relógio atrasado (+1 µs) e a loja apagada (404, sem ressuscitar).
  - **Diferenças assumidas:** sem transações, a interação grava-se depois da loja e uma falha nela não desfaz a loja (§5.11); o `Cache-Control: no-store, private` não se porta (como na T2.9, §5.8).
- **Rotas (F3):** o mesmo controlo, com `versao` inteiro.

### 5.11 Histórico e temporizadores
- **F2:** só `mudanca_fase`. Os 4 campos de temporizadores já existem no documento (a `null`).
- **A interação `mudanca_fase` (T2.11):** `{id: uuid4, loja_id, tipo: "mudanca_fase", resultado: "<antiga>→<nova>", notas: null, paragem_id: null, utilizador_id: <user_id de quem a mudou>, ocorrida_em: relogio.instante(agora)}`, pela ordem do §3 e sem `client_uuid` (o índice único parcial só vê textos). A `ocorrida_em` é o mesmo instante do `fase_desde` novo. As mudanças de fase não mexem em `ultima_interacao_em` (não silenciam alertas).
  - **Um só sítio decide que a fase muda:** `lojas._fase_nova` (com a mesma fase, ou sem ela, não há `fase_desde` novo nem histórico). Gancho no código: "F4/F5: efeitos de resultados aqui".
  - **Sem transações:** primeiro o `update_one` condicional da loja; só se gravou, o `insert_one` da interação. Se este falhar, responde-se 200 na mesma e fica uma linha de erro `[crm] loja <id>: a mudança de fase <antiga>→<nova> ficou gravada, mas não entrou no histórico (<tipo da exceção>)`, sem dados pessoais: nunca a mensagem da exceção (pode trazer o documento), nem quem a mudou, nem o nome da loja, nem o traceback. Testado com `RuntimeError`, `DuplicateKeyError` e `ServerSelectionTimeoutError` cujas mensagens trazem dados pessoais.
- **F4/F5:**
  - Só `visita`, `chamada`, `amostra` e `entrega` atualizam `ultima_interacao_em`; notas e mudanças de fase não silenciam alertas.
  - Só visitas, amostras e entregas **com sucesso** atualizam `ultima_visita_ou_entrega_em`.
  - Atualiza-se sempre com `$max`, para que registos atrasados nunca andem para trás. Com o valor a `null`, conta-se desde `fase_desde`.
- **Alertas (F5):**
  - 📦 Entrega pendente: a loja tem uma encomenda `pendente`.
  - 🔁 Visita pendente: uma visita que não era de entrega ficou por fazer ou terminou com "Voltar depois".
  - ⏰ Seguimento em atraso: `amostra` há mais de 7 dias ou `cliente` há mais de 30 (configuráveis).

### 5.12 Apagar só enganos
- Uma loja **só se apaga** se não tiver interações além de `mudanca_fase`. Na F5 passam a contar também as encomendas e as paragens (gancho em `pode_apagar`). As `mudanca_fase` vão com ela (`delete_many({"loja_id", "tipo": "mudanca_fase"})`).
- Se tiver histórico: 409 `loja_com_historico` "Esta loja tem histórico — mude a fase para perdida em vez de a apagar.".
- Confirmação no ecrã: "Apagar esta loja? Use só para enganos — se a loja não está interessada, mude a fase para Perdida.".
- **Rotas (T2.12, `crm/lojas.py::apagar_loja`; porta do `LojasControlador::apagar` e do `LojasRepositorio::podeApagar`/`apagar`; testes em `test_lojas_apagar.py`, com os casos de apagar do `LojasEditarTest.php` e os nomes de lá):**
  - **Perfis:** `DELETE /lojas/{loja_id}` é do escritório (admin e utilizador do CRM; classificada em `PERFIS_POR_ROTA`). O motorista recebe 403 `sem_permissao` e quem não é membro 403 `sem_acesso_crm`, sem se ler a base. Não lê o corpo (a única dependência é a guarda): um corpo, mesmo JSON partido, ignora-se.
  - **Ordem, sem transações** (o autónomo bloqueava a linha com `FOR UPDATE` e as interações iam com a loja pelo `ON DELETE CASCADE`):
    1. ler a loja com `{"_id": 0, "id": 1}` (404 "Loja não encontrada."); interações órfãs de um id que não existe nem se olham;
    2. `_pode_apagar`: `find_one({"loja_id", "tipo": {"$ne": "mudanca_fase"}}, {"_id": 0, "id": 1})` (o `SELECT 1 … LIMIT 1`), pelo índice `loja_id_1_ocorrida_em_1`. Qualquer interação que não seja exatamente `mudanca_fase` conta, também uma sem `tipo` ou com `tipo` null (o `$ne` do Mongo apanha-as; no autónomo o tipo era NOT NULL): na dúvida, não se apaga. Com histórico → 409 e nada se escreve;
    3. `delete_one({"id"})`; `deleted_count 0` (apagada por outra pessoa entre a leitura e esta escrita) → 404, e quem a apagou é que leva as mudanças de fase;
    4. só então `delete_many({"loja_id", "tipo": "mudanca_fase"})`, e só dessas.
  - **Corridas residuais aceites:** uma interação de outro tipo que chegue entre o passo 2 e o 3 (F4/F5: uma visita registada no mesmo instante) fica órfã, e nunca se apaga histórico verdadeiro; uma mudança de fase de um PATCH que corra ao mesmo tempo também pode ficar órfã. A linha do tempo é por loja, por isso as órfãs não aparecem em ecrã nenhum. **F4/F5:** quem grava interações deve tolerar que a loja já não exista.
  - **Falhas:** uma falha a ler o histórico ou no `delete_one` é um 500 e nada se apaga. Uma falha no `delete_many` não desfaz nada (a loja já foi): responde-se 200 na mesma (um 500 levava a pessoa a tentar de novo e a receber 404) e fica uma linha `[crm] loja <id>: apagada, mas as mudanças de fase ficaram no histórico (<tipo da exceção>)` no logger `crm.lojas`, sem dados pessoais nem traceback (testado com `RuntimeError`, `DuplicateKeyError` e `ServerSelectionTimeoutError` com dados pessoais na mensagem).
  - **Resposta:** 200 `{"apagada": true}` (o booleano JSON).
  - **Gancho:** a docstring do `_pode_apagar` tem "F5: bloquear se houver encomendas ou paragens" (plano §7); um teste confirma que lá está.
  - **Conferido no MongoDB 8.0.32 local** (não versionado, `t2.12-conferencia-mongo.log`; base `lisbonb_crm_teste`, apagada no início e no fim), com o Motor, os índices verdadeiros e as lojas criadas e mudadas de fase pelas rotas: 17 verificações, todas OK. Entre elas: a procura do histórico e o `delete_many` pelo `loja_id_1_ocorrida_em_1` e o `delete_one` pelo `id_1`; 409 exato com uma visita e também com uma interação sem `tipo` ou com `tipo` null; a loja e as duas mudanças de fase dela apagadas, as interações das outras lojas intactas; GET e DELETE seguintes → 404; a corrida com o Motor (200 e 404, nada fica); um id `{"$ne": null}` no caminho → 404.
  - **Diferença assumida:** o `Cache-Control: no-store, private` não se porta (como na T2.9, §5.8).

### 5.13 "O que aconteceu no terreno ganha" (F4)
- As gravações do escritório **nunca apagam nem sobrepõem** um resultado registado pelo motorista. Se a paragem foi retirada entretanto, é reposta como `feita`; se a encomenda foi cancelada, fica entregue na mesma, com um aviso ao escritório.
- **Gancho obrigatório:** na F4, todo o efeito do terreno sobre `crm_lojas` avança `atualizado_em` com `proximo_carimbo`, para que uma escrita do escritório com versão velha dê 409. Nas rotas, o escritório atualiza paragens concretas condicionado à `versao` e nunca sobrepõe resultados do motorista.
- **Paragem reposta pelo terreno (F3, T3.3):** ao repor uma paragem retirada, a F4 só grava `removida_em: null` e deixa a `ordem` a `null`. A F3 lê esse formato: `dominio.rotas.ativas` põe as paragens ativas com `ordem` nula no fim, pela posição na lista (nunca compara `None` com um inteiro), e o `bloqueio_de_escrita` dá `rota_em_curso` a partir do primeiro registo `feita`/`nao_feita`, mesmo numa paragem retirada (a rota passa a só de leitura no escritório). O escritório só escreve `paragens.<índice>.<campo do escritório>` (`dominio.rotas.caminhos_paragem`); os campos do terreno (`CAMPOS_DO_TERRENO`), o `id` e o `loja_id` ficam de fora. A `rota_api` (T3.16) lê essa rota sem erro: a paragem reposta vai para o fim da lista, com o `numero` a seguir ao das outras da secção "rota".
- **As horas só valem com `calculo.atual: true` (F3, T3.16):** as `chegada_prevista`/`espera_min`/`fora_de_horario` de cada paragem e os totais do `calculo` (`distancia_m`, `duracao_s`, `regresso_previsto`, `depois_do_limite`, `geometria`) são do último Directions e ficam na base depois de qualquer alteração. `calculo.atual` compara a assinatura gravada com a da rota como está (`horarios.entrada_calculo`: só a secção "rota", pela ordem, com o início e o fim resolvidos); com `false`, a F3 esbate-as e não dá o aviso `fora_de_horario`, e a F4 **não as mostra** (nem as horas por paragem nem os totais).
- **Registo do telemóvel sem transação de vários documentos:**
  - A inserção da interação com `client_uuid` único é o **ponto de confirmação**.
  - Os outros efeitos são idempotentes: datas com `$max`, fase "só sobe", paragem marcada com o `client_uuid`.
  - Um reenvio com o mesmo `client_uuid` volta a aplicar os efeitos que faltarem. Testa-se incluindo uma falha a meio.
- A fila fica associada ao `user_id` e nunca é enviada com outra conta. O servidor aceita itens de rotas entre hoje − 3 dias e hoje, só de quem os criou ou de um admin do CRM.

### 5.14 Planear rota e rota do dia (F3–F4, só referência)
- **Limite:** 48 paragens por rota (o Directions aceita 50 coordenadas com início e fim).
- **VROOM:**
  - prioridades: entregas 100; visita pendente e seguimentos em atraso 2; restantes 1;
  - cada janela vai como `[início, fim − tempo de serviço]`, em segundos desde a meia-noite local;
  - só se enviam **coordenadas e identificadores numéricos**. Os uuids do portal têm de ser mapeados para índices; nunca nomes, telefones nem moradas.
- **Horas:** vêm sempre de **uma** chamada Directions pela ordem fixa (com `avoid_features: ["tollways"]` se se evitam portagens).
- **Fecho simples na F3:** uma rota de um dia anterior a hoje trata-se como concluída ao ler. O fecho automático noturno chega na F5.
- **Rota do dia:**
  - sessão de 24 h com "sessão válida até HH:MM", e a página nunca salta sozinha para o ecrã de entrar;
  - arranque sem rede a partir da cópia guardada;
  - service worker e IndexedDB **só** em `/rota`;
  - "Desfazer" durante 10 s.

### 5.15 Proibições (legais e de serviço)
- **Google:** não se reutiliza a chave Google Places do portal e não se guarda nenhum dado vindo da Google (termos europeus do Google Maps Platform, original §9). Os links do Google Maps e do Waze (F4) não usam chave.
- **Nome e telefone** de uma loja são sempre escritos pela pessoa; a Geoapify só sugere morada, código postal e localidade.
- **`Referrer-Policy`:** nunca `no-referrer` nem `same-origin` (nginx, Caddy ou HTML), porque a chave dos mosaicos é restrita por Referer.
- **GPS:** só ao tocar, nunca seguimento contínuo, só o ponto da loja (§5.4).
- **openrouteservice:** nunca dados pessoais no pedido, só coordenadas e índices (§5.14).

---

## 6. Superfície de API

**Convenções:**
- Prefixo `/api/crm`, JSON. Em sucesso devolve o objeto ou a lista diretamente; criar dá **201**.
- As escritas leem o corpo com `crm.pedidos.corpo_json` (400 `json_invalido` se não for um objeto) e validam no domínio, **sem modelos Pydantic**.
- Erro do CRM: `{"detail": {"codigo", "mensagem", "campos"?: {campo: mensagem}, "lojas"?: [...]}}`.
- Erros herdados da autenticação, em texto:
  - sem cabeçalho → 403 `"Not authenticated"` (o frontend normaliza para `nao_autenticado`);
  - token inválido ou expirado → 401 `"Sessão inválida ou expirada"`;
  - conta apagada ou sessão anterior à troca de palavra-passe → 401 `"Sessão terminada"`.

| Código | HTTP | Mensagem exata |
|---|---|---|
| `json_invalido` | 400 | "O pedido não é JSON válido." |
| `sem_acesso_crm` | 403 | "Sem acesso ao CRM." |
| `sem_permissao` | 403 | "Sem permissão para esta ação." |
| `nao_encontrado` | 404 | "Loja não encontrada." / "Região não encontrada." / "Membro não encontrado." |
| `validacao` | 422 | "Verifique os campos assinalados." + `campos` |
| `duplicado` | 409 | "Já existe {nome} aqui — é a mesma?" + `lojas` |
| `conflito` | 409 | "Alterado por outra pessoa — recarregar" |
| `regiao_repetida` | 409 | "Já existe uma região com este nome." |
| `regiao_com_lojas` | 409 | "Esta região tem lojas — mude-lhe o nome em vez de a apagar." |
| `loja_com_historico` | 409 | "Esta loja tem histórico — mude a fase para perdida em vez de a apagar." |
| `ja_membro` | 409 | "Esta pessoa já é membro do CRM." |
| `admin_master` | 409 | "O administrador principal já é admin do CRM." |
| `morada_indisponivel` | 503 | Pesquisa: "Pesquisa de morada indisponível — coloque o pino no mapa ou use 'Estou nesta loja'"; inversa: "Morada sugerida indisponível — escreva a morada à mão." |
| `ja_na_rota` | 409 | "Esta loja já está na rota deste dia." (F3, T3.19) |
| `rota_cheia` | 409 | "Uma rota tem no máximo 48 paragens." (F3, T3.19) |
| `rota_fechada` | 409 | "Este dia já passou — a rota só se pode ver." (F3, T3.19: um dia anterior a hoje em Lisboa, com ou sem rota) |
| `rota_em_curso` | 409 | "A rota já tem registos do motorista — no escritório só se pode ver." (F3, T3.19: uma rota fora de `rascunho`/`planeada` ou com alguma paragem `feita`/`nao_feita`, mesmo retirada) |

| Rota | Perfis | Sucesso |
|---|---|---|
| `GET /saude` | Pública | `{estado: "ok", modulo: "crm"}` |
| `GET /eu` | Qualquer sessão | `{membro, perfil, admin_master}` (não-membro: `{false, null, false}`) |
| `GET /membros` | admin | `[{id\|null, user_id, nome, email, tipo_conta, perfil, admin_master, conta_existe, criado_em}]`, com o admin master primeiro |
| `GET /membros/candidatos` | admin | `[{id, nome, email, tipo_conta}]` (declarada antes de `/membros/{membro_id}`) |
| `POST /membros` | admin | `{user_id, perfil}` → 201 (422: "Escolha uma conta do portal.", "A conta não existe.", "Escolha um perfil: admin, utilizador ou motorista.") |
| `PATCH /membros/{membro_id}` | admin | `{perfil}` → 200 |
| `DELETE /membros/{membro_id}` | admin | `{retirado: true}` |
| `GET /regioes` | admin, utilizador | `[{id, nome, ordem}]` por ordem, nome (sem maiúsculas nem acentos) e `id` |
| `POST`, `PATCH`, `DELETE /regioes…` | admin | 201 `{id, nome, ordem}` / 200 `{id, nome, ordem}` / `{apagada: true}` (422 → 404 → 409 `regiao_repetida`/`regiao_com_lojas`; §5.8) |
| `GET /lojas` | admin, utilizador | `[{id, nome, fase, regiao_id, lat, lng, telefone, pessoa_contacto}]` por nome (a `pessoa_contacto` desde a revisão de 2026-10-13, para a linha de contacto do cartão do mapa) |
| `POST /lojas` | admin, utilizador | 201 loja completa (422 dos campos → 422 `regiao_id` "A região não existe." → 409 `duplicado`, salvo `confirmar_duplicado: true`; §5.2) |
| `GET /lojas/{loja_id}` | admin, utilizador | Loja completa (404 "Loja não encontrada.") |
| `PATCH /lojas/{loja_id}` | admin, utilizador | Campos alterados + `atualizado_em` (obrigatório) + `confirmar_duplicado?` → 200 loja completa com o `atualizado_em` novo (422 dos campos e do `atualizado_em` → 404 → 409 `conflito` → 422 das janelas → 422 `regiao_id` → 409 `duplicado`, só se mudar de sítio → atualização condicional: 404/409; §5.10) |
| `DELETE /lojas/{loja_id}` | admin, utilizador | `{apagada: true}` (404 → 409 `loja_com_historico` se houver interações além de `mudanca_fase` → `delete_one` (404 na corrida) → `delete_many` só das `mudanca_fase`; §5.12) |
| `GET`, `PATCH /definicoes` | admin | `{fabrica_morada, fabrica_lat, fabrica_lng, rota_hora_saida, rota_hora_regresso, servico_entrega_min, servico_amostra_min, servico_acompanhamento_min, servico_angariacao_min}` (F3), com as coordenadas e os minutos como números. O PATCH leva só as chaves que mudam (lat e lng juntas) e responde com as definições relidas (400 → 422 dos campos, incl. "Esta definição não existe." → 422 da coerência das horas, só quando o pedido traz uma delas, sem gravar nada → upsert por `chave`; §5.9) |
| `GET /config` | admin, utilizador | `{mosaicos: {url, atribuicao: geoapify\|osm}, alternativa: {url}, centro: {lat, lng}}`. O centro é o ponto da fábrica das definições em vigor; a chave dos mosaicos é lida a cada pedido (§8). O motorista não a recebe na F2 (403) |
| `GET /morada/pesquisa?texto=&lat=&lng=` | admin, utilizador | Até 5 `{rotulo, morada, codigo_postal, localidade, lat, lng}` (422 `texto` → 503 sem chave, sem chamar a Geoapify → Geoapify: 503 se falhar; §8) |
| `GET /morada/inversa?lat=&lng=` | admin, utilizador | Uma sugestão ou `null` (422 `lat`/`lng` → 503 sem chave → Geoapify: 503 se falhar; §8) |

**Loja completa (API):** `id, nome, fase, fase_desde, regiao_id, morada, codigo_postal, localidade, lat, lng,
origem_coords, precisao_m, telefone, pessoa_contacto, instagram, site, notas, janela1_inicio, janela1_fim,
janela2_inicio, janela2_fim, dias_fechada, visita_pendente_motivo, visita_pendente_desde, ultima_interacao_em,
ultima_visita_ou_entrega_em, criado_por, criado_em, atualizado_em` (`instagram` e `site` desde 2026-10-13; o
resumo do `GET /lojas` não os traz: o cartão do mapa não os mostra. O resumo traz a `pessoa_contacto` e o
`telefone`, que o cartão mostra).

**Morada:**
- `texto` tem 3 a 200 caracteres depois de aparar ("Escreva pelo menos 3 caracteres." / "A pesquisa tem no máximo 200 caracteres."); sem texto, dá o mesmo erro que com menos de 3.
  - **Decisão (T2.15):** apara-se com o `trim()` do PHP, como o `MoradaControlador` (`geoapify.trim_do_php`: só `" \t\n\r\0\x0B"`), e não com o `texto.aparar`. Um U+00A0, U+FEFF ou U+2003 nas pontas fica no texto que vai à Geoapify e conta para os 3 caracteres. O ecrã já apara com o `trim()` do JavaScript antes de pedir (`morada.js`), por isso na prática nunca chegam. Os caracteres contam-se, não os bytes ("Sé" tem 2).
- `lat`/`lng` validam-se com `^-?[0-9]{1,3}(\.[0-9]+)?$` (`morada.NUMERO` com `re.fullmatch`, só algarismos ASCII). Na pesquisa, valores inválidos ignoram o bias (`lat=1e2` ou `lat=abc` → 200 sem bias); na inversa, dão 422 ("A latitude tem de ser um número." / "Fora de Portugal").
  - O bias aceita qualquer ponto do mundo com `abs(lat) ≤ 90` e `abs(lng) ≤ 180` (o de Madrid serve). `0038.7` tem quatro algarismos antes do ponto e não é número, embora desse um ponto em Portugal.
  - Na inversa, os erros vêm pela ordem `lat`, `lng`, e cada um é "tem de ser um número" ou "Fora de Portugal" (§5.3).
- Os três leem-se como `Optional[str]` (nunca `float` nem `Query(min_length=…)`, que davam o 422 em lista do Pydantic e aceitavam `1e2`, `nan` e `inf`). Um parâmetro repetido vale o último, como o `$_GET` do PHP; `texto[]=…` é outro nome e conta como "sem texto".
- Ordem: a guarda de perfil (403 ao motorista e a quem não é membro, 401/403 herdados sem sessão) → o pedido (422) → a chave (503 sem ela) → a Geoapify. Nada disto chama a rede quando o pedido é inválido ou não há chave.

**Só nomeadas (F3+):** rotas (`/rotas…`: criar, calcular ordem, guardar, sugestões), rota do dia e fila do
motorista (`/motorista…` ou equivalente), interações e linha do tempo (`/lojas/{id}/interacoes`),
`/produtos`, `/encomendas`, `/cron/*` (fecho noturno, F5).

---

## 7. Frontend (ecrãs e módulos)

**Onde vive:**
- `/crm/*` usa `components/layouts/CrmLayout.js`: barra lateral só com os itens do CRM, "Voltar ao portal", tema e terminar sessão; `Sheet` no telemóvel.
- `/admin/crm/*` usa as **mesmas páginas** dentro do `AdminLayout`.
- `/rota` (F4) é uma rota de topo, como `/bolso` e `/faturacao/pos`.
- Páginas com `React.lazy` + `Suspense` (o Leaflet não entra no ficheiro principal); `pages/crm/rotasCrm.js` declara as rotas filhas.
  - **Rotas (T1.12):** `filhosCrm()` (index → `mapa`, `mapa`, `lojas/nova`, `lojas/:lojaId`, `definicoes` dentro de `SoAdminCrm`, e `*` → mapa da mesma casa) e `rotasCrmNoAdmin()` são funções que devolvem `<Route>`, porque o `<Routes>` só aceita `<Route>` e fragmentos. Um caminho do CRM que não existe abre o mapa, como no autónomo.
  - **Guardas (`components/crm/GuardaCrm.js`):** `GuardaCrm` espera enquanto `carregando` (indicador, nunca recambia), manda para `/` quem não pode abrir a área (não membro, motorista, app nativa) e desenha os `children` ou o `<Outlet/>`. Com o `/eu` sem resposta mostra `FalhaAcessoCrm` ("Tentar de novo" / "Voltar ao portal") em vez de recambiar; a decisão é `decisaoGuardaCrm` (revisão da F0/F1). O `CrmLayout` embrulha-se nela, para nem a barra do CRM aparecer a quem não entra; no `/admin`, é o elemento da rota `crm`. `SoAdminCrm` (`decisaoSoAdminCrm`) manda os não-admin para `${baseCrm}/mapa` e, com falha, mostra o mesmo aviso.
  - **Página que não carrega:** cada página tem um limite de erros com a `key` da rota. Se o *chunk* não chegar, aparece "Não foi possível abrir esta página do CRM. Verifique a ligação e recarregue." com "Recarregar", e o resto do portal continua de pé.
  - **Verificar componentes sem Jest versionado:** o Jest 27 do CRA não resolve o alias `@/`, o `react-router/dom` (campo `exports`) nem tem `TextEncoder` no jsdom. As verificações temporárias da T1.12 (`~/.cache/lisbonb-crm-local/t112-verificacao/`) mostram como contornar isto sem tocar no `package.json`. As da T1.13 (`t113-verificacao/`) montam o `AdminLayout` inteiro e trazem também o comando do ESLint do CRA (eslint 8 + `eslint-config-react-app`, com `exhaustive-deps` como erro). As da T1.14 (`t114-verificacao/`) montam o `EmployeeLayout`, com `@capacitor/app`, `lib/notifications` e `lib/geo` falsos.
  - **Secção CRM no `/admin` (T1.13):** `components/crm/seccaoCrm.js` fica no fim do array `sections` do `AdminLayout`. Os itens saem de `ITENS_MENU_CRM` na casa `/admin/crm`, e as Definições têm `crmAdmin`.
    - O match do RH (o apanha-tudo do `/admin`) exclui `/admin/crm` com `rotaDoCrmNoAdmin`, a mesma regra do `match` da secção. Sem isto, o RH acendia no CRM.
    - A grelha filtra por `seccaoVisivel(s, { podeVerCrm })`, com `podeVerCrm = podeAbrirAreaCrm(eu, { nativo: Capacitor.isNativePlatform() })`. Uma secção escondida também não mostra itens, mesmo que o endereço seja dela: quem não é membro e escreve `/admin/crm/…` não vê ligações do CRM enquanto a guarda decide.
    - Na secção `crm` não há seletor de empresa, e o `fetchCompanies` não pede nada (põe `companies = []`), para as empresas do RH não passarem às páginas do CRM pelo `Outlet`.
    - O `<main>` decide a área cheia pela rota (`ecraCheioDoCrm`), com as mesmas classes do `CrmLayout`: as mesmas páginas abrem igual nas duas casas.
  - **Item "CRM" na área do colaborador (T1.14):** o `EmployeeLayout` junta `ITEM_CRM` (`/crm/mapa`, "CRM", ícone `MapPinned`) ao fim da barra de baixo só quando `podeAbrirAreaCrm(eu, { nativo: Capacitor.isNativePlatform() })`. A lista `navItems` não muda (cópia nova `[...navItems, ITEM_CRM]`); enquanto o `/eu` responde, ficam os 4 itens de sempre. O `data-testid` sai da regra que já existe (último pedaço do caminho): `nav-mapa`.
    - O item leva à área própria (`/crm/*`, `CrmLayout`): o colaborador não vê nada do resto do portal, e "Voltar ao portal" volta a `/colaborador`.
    - **Barra de baixo com 5 itens em ecrãs estreitos** (browser do telemóvel; na app nativa o CRM não aparece): de 375 px para cima cabe numa linha; a 360 px "Registar Ponto" parte-se em 2 linhas (como já hoje a 320 px com 4 itens); a 320 px o item "CRM" passa a borda direita em ~17 px. Não se mexeu no estilo da barra, que é do Matheus. Se for preciso, a correção é no `className` dos itens da barra, para todos (ex.: `px-2`, ou `flex-1 min-w-0 text-center`).
    - Ao tocar noutro item da barra (ex.: "Registar Ponto"), o endereço muda logo mas o realce do item ativo pode atrasar-se uns segundos. Já acontece com o `EmployeeLayout` do HEAD, sem o CRM (verificado na T1.14): não é regressão do CRM. Nas verificações no browser, esperar pelo realce.

**Ficheiros partilhados (mínimo):**

| Ficheiro | Alteração |
|---|---|
| `App.js` | 2 imports + 2 blocos de rotas |
| `AdminLayout.js` | Secção `crm` só para membros (a grelha passa a filtrar por `seccaoVisivel`); match do RH com `&& !rotaDoCrmNoAdmin(p)`; no CRM não pede empresas nem mostra o seletor; o mapa ocupa a área toda (`ecraCheioDoCrm`) |
| `EmployeeLayout.js` | Item "CRM" só para quem `podeAbrirAreaCrm` ("Rota do dia" é da F4) |
| `PrivacyPolicy.js` | Secção "8. CRM Purple House (equipa comercial)" antes de "Alterações", que passa a 9 (T2.31): CRM no browser e não na app instalada; GPS só ao tocar em "Estou nesta loja", uma leitura, só o ponto da loja, nunca a posição da pessoa nem percursos, sem seguimento, e o que fazer se recusar a autorização; dados guardados; moradas da Geoapify (dados OpenStreetMap), as atribuições exatas do mapa e o Leaflet (o `mapa.js` tira o prefixo do Leaflet e diz que o crédito está aqui). Mais a frase do §3 ("No registo de ponto, a localização serve exclusivamente para validar o registo."), a do §4 (Geoapify e OpenStreetMap como prestadores, o servidor sem dados pessoais, o IP visto pelos mosaicos) e a data. Um comentário JSX marca a redação para o dono rever (§14, ponto 7). Diff: 33 linhas a mais e 3 a menos. Guardado pelo `lib/crm/privacidade.test.js` |

**Ecrãs:**

| Ecrã | Fase | Comportamento essencial |
|---|---|---|
| Páginas "Brevemente" | F1 | Componente `ComingSoon`, subtítulo "CRM Purple House" |
| Mapa | F2 (T2.25) | `pages/crm/CrmMapa.js` com `components/crm/{MapaLojas,FiltrosMapa,CartaoLoja}.js` e `crm.css`, em área cheia nas duas casas. Pinos por fase com o nome em etiqueta permanente (nó `span` com `textContent`); zoom 6–19, `ZOOM_LOJA = 17`; pede ao mesmo tempo a configuração, as lojas e as regiões, e a primeira vista só quando as lojas chegam (falha → mensagem e "Tentar novamente", só do que falhou; configuração inválida ou Leaflet que rebenta → `MENSAGEM_SEM_MAPA`); filtros de fase (pelo `FUNIL`, com a amostra da cor) e região (Todas/Sem região/…; "Região guardada" até as regiões chegarem; uma apagada volta a Todas) num `Popover`, guardados em `localStorage` (`crm.filtros`); "N lojas"; o botão "Filtros" cheio com filtros ativos; "Nova loja" na barra de cima; cartão por baixo do mapa com nome, fase, "Contacto: pessoa · telefone" em texto (só as partes que existem; sem nenhuma, a linha não aparece; `contactoDaLoja` de `ecraMapa.js` sobre a loja do resumo do `GET /lojas`, que traz a pessoa e o telefone desde a revisão de 2026-10-13 — o botão **Ligar** saiu em 2026-10-13 a pedido do Bruce), "Última ação: ainda sem histórico" e **Ver ficha**: o mapa encolhe e centra-se, o foco vai para o nome, o Escape fecha e devolve o foco ao pino, tocar no mapa fecha o cartão e os filtros; `?loja=<id>` centra essa loja (da lista, sem outro pedido); quem volta ao mapa deixa `state: {aviso}` e o mapa mostra-o num toast, com "— os filtros escondem-na do mapa." quando é o caso, uma só vez |
| Nova loja | F2 (T2.27) | `pages/crm/CrmLojaNova.js` com `components/crm/{SeletorLocalizacao,FormularioLoja,DialogoDuplicado}.js`; as regras em `lib/crm/lojaNova.js` (abaixo). Primeiro a localização (pino, pesquisa de morada ou "Estou nesta loja", e confirmar), depois nome*, fase* (pastilhas com a cor do pino, `potencial` por omissão), região (última usada, `crm.ultimaRegiao`; "Região guardada" até as regiões chegarem; sem região esquece a anterior), telefone, contacto, morada, código postal, localidade, notas; Guardar desativado sem nome e pino ("Para guardar, …"), ou sem rede ("Guardar — sem rede"); 422 → erros junto aos campos (borda vermelha, foco no primeiro) ou no seletor (o pino volta a soltar-se); 409 → "Já existe X aqui — é a mesma?" com "Sim, abrir X", "Não, é outra loja" e "Cancelar"; sucesso → `<casa>/mapa?loja=<id>` com `state: {aviso: 'Loja guardada'}` (o toast é do mapa) |
| Ficha da loja | F2 (T2.28) | `pages/crm/CrmLoja.js` com o `FormularioLoja` em modo `ficha`, o `SeletorLocalizacao` da correção e o `DialogoDuplicado`; as regras em `lib/crm/ficha.js` (abaixo). Título = nome da loja, "Ver no mapa" (`<casa>/mapa?loja=<id>`); o formulário preenchido com o horário (2 janelas `type="time"`), os dias fechada e, desde 2026-10-13, o Instagram e o site (dois campos de texto a seguir à localidade, só na ficha — a nova loja fica como no desenho §6.2 —, com os erros do 422 junto a cada um; o servidor normaliza-os ao guardar e a ficha fica com o que ele devolve); **fase num toque** (só `{fase, atualizado_em}`, um pedido de cada vez, fica a última; sem rede ou com erro fica por guardar e vai no Guardar; com o conflito não grava); Guardar só com o que mudou + `atualizado_em` (desativado: "Recarregue a ficha para ver o que a outra pessoa mudou.", "Para guardar, escreva o nome.", "Para guardar, confirme a localização no mapa ou cancele a correção.", "Sem alterações por guardar."; sem rede "Guardar — sem rede"); os campos desativados enquanto grava; toasts "Fase guardada" e "Alterações guardadas"; 409 conflito → a faixa "Alterado por outra pessoa — recarregar" com o foco no Recarregar; "Corrigir localização" (o pino no sítio guardado, o foco em Confirmar; "Cancelar correção" desfaz a morada que a pesquisa ou o GPS puseram e devolve o foco); 409 duplicado → o diálogo da nova loja; Apagar → "Apagar esta loja?" + "Use só para enganos — se a loja não está interessada, mude a fase para Perdida." (Cancelar com o foco, "Sim, apagar"), apagada → `<casa>/mapa` com `state: {aviso: 'Loja apagada'}`; 409 `loja_com_historico` → a mensagem do servidor; 404 → "Loja não encontrada." e "Voltar ao mapa" |
| Definições (admin) | F2 (T2.29; Regiões e Fábrica na T2.30) | `pages/crm/CrmDefinicoes.js`: `PageHeader` "Definições" e separadores (`Tabs`) Membros / Regiões / Fábrica (só o aberto existe; a Fábrica carrega-se à parte, com `React.lazy`, por ter o Leaflet). **Membros** (`pages/crm/DefinicoesMembros.js`, regras em `lib/crm/membros.js`): tabela Nome / Email / Tipo de conta / Perfil / Ações (cartões no telemóvel); o admin principal primeiro, com a etiqueta "Administrador principal", fixo; a própria conta sem ações; "(conta apagada)" com email e tipo "—"; o perfil num `Select` (Utilizador, Administrador, Motorista) que grava logo ("Perfil guardado"); "Retirar" → "Retirar X do CRM?" + "Deixa de ter acesso ao CRM. A conta do portal fica como está." (Cancelar com o foco, "Sim, retirar"; retirado → "Membro retirado", a conta volta ao "Adicionar", o foco no título); "Adicionar membro": conta do portal (nome; na lista também email · tipo) + perfil (Utilizador por omissão, com o que cada perfil dá) → "Membro adicionado"; 422 junto aos campos com o foco no primeiro; sem contas, "Todas as contas do portal já são membros do CRM."; 409/404/sem rede em toast de erro com a mensagem do servidor, e as listas pedem-se outra vez quando ficaram desatualizadas. **Regiões** (`pages/crm/DefinicoesRegioes.js`, regras em `lib/crm/regioes.js`, T2.30): a lista pela ordem do servidor (ordem → nome sem maiúsculas/acentos → id), cada uma com Subir, Descer, Mudar o nome e Apagar (44 px; o nome acessível diz a região); Subir/Descer mudam a lista logo e gravam a ordem toda 0..n-1, um PATCH `{ordem}` de cada vez, só das que mudaram ("Ordem guardada"; os outros Subir/Descer com `aria-disabled` enquanto grava, o foco fica no botão tocado; uma falha avisa num toast e volta a pedir a lista); Mudar o nome abre o campo na linha ("Nome guardado"; 409 `regiao_repetida`/422 junto ao campo, com o foco); Apagar → "Apagar a região X?" + "Só se apagam regiões sem lojas." (Cancelar com o foco, "Sim, apagar"; "Região apagada" e o foco no título; o 409 `regiao_com_lojas` fica na linha); "Nova região" + Adicionar envia `{nome, ordem: proximaOrdem}` ("Região adicionada", o campo vazio e com o foco). **Fábrica** (`pages/crm/DefinicoesFabrica.js`, regras em `lib/crm/fabrica.js`, T2.30): "Morada da fábrica" e "Ponto no mapa" ("Latitude … · longitude …" com 6 casas, "O mapa abre aqui enquanto não houver lojas."); "Mudar o ponto no mapa" abre o `SeletorLocalizacao` sem GPS, com os textos da fábrica e o foco em "Confirmar localização" (`focarAoIniciar`); Guardar envia só o que mudou (a morada; o ponto com lat e lng juntas) → "Dados da fábrica guardados."; o 422 do ponto solta o pino e mostra o erro no mapa; "Cancelar a mudança do ponto" desfaz o ponto e a morada que a pesquisa lá pôs |
| Planear rota | F3 | Original §7 |
| Rota do dia | F4 | Original §8 + desenho §5 |
| Linha do tempo, Encomendas, Produtos, alertas | F5 | Original §6.3, §6.4 e §4.2 |

**Módulos puros em `src/lib/crm/` (Jest, portados de `tests/js/*.test.js`):**

| Módulo | O que faz |
|---|---|
| `api.js` | Cliente HTTP (molde `lib/faturacao.js`) com erros normalizados (T1.10) e as chamadas da F1 (`/eu`, membros) e da F2 (regiões, lojas, definições, `/config`, morada; T2.24). Ver "Chamadas" abaixo |
| `acesso.js`, `eu.js` | Visibilidade e cache do `/eu` por token |
| `fases.js`, `atribuicoes.js` | Cores e textos exatos (T2.20). O `html` das atribuições é só para o controlo do Leaflet (`mapa.js`); nos ecrãs React usam-se as `partes` (texto + `url`) |
| `mosaicos.js` | Troca para a alternativa depois de pelo menos 3 erros, se forem mais do que os sucessos (uma só vez) |
| `dom.js` | `el(documento, tag, …)` recebe o documento por parâmetro e põe os dados só como texto. Serve para o DOM montado à mão para o Leaflet; o React já escapa. Recusa `on*`, `srcdoc` e `javascript:`/`vbscript:`. `hrefTelefone` dá `tel:` só com dígitos e o `+` inicial, e `null` com menos de 9 dígitos (T2.20); desde 2026-10-13 nenhum ecrã a usa (o cartão mostra o contacto em texto) — fica, com os testes, para quem vier a precisar de uma ligação para marcar |
| `ids.js` | `eUuid`: o uuid4 em texto que o servidor aceita, onde o autónomo pedia um inteiro positivo (T2.21) |
| `filtros.js` | Fases (por omissão as 5, incluindo perdida; guardadas pela `ORDEM`) e região `'todas' \| 'sem' \| uuid`; um id numérico volta a `'todas'`. Guardados em `crm.filtros`, com a mesma normalização ao guardar, carregar e aplicar. Também as regras do componente dos filtros, para o `FiltrosMapa` só as chamar: `opcoesRegiao` (Todas, Sem região, as regiões ou "Região guardada"), `ajustarARegioes`, `filtrosAtivos` e `textoNumeroLojas` ("1 loja", "N lojas") (T2.21) |
| `diferencas.js` | `camposAlterados(original, atual)` para o PATCH da ficha: a localização vai em bloco (lat, lng, origem_coords e precisao_m); `''` equivale a `null` e vai como `null`; as listas (`dias_fechada`) são conjuntos (T2.21); o Instagram e o site são textos simples, como o telefone |
| `perfis.js` | `PERFIS` (Utilizador, Administrador, Motorista, o mais comum primeiro) e `rotuloPerfil` (T2.21; §4) |
| `rede.js` | `criarEstadoRede(window, navigator)`: `online()` (sem `onLine`, assume que há rede) e `aoMudar(fn)` → cancelar (T2.21) |
| `gps.js` | `obterPosicao(navigator.geolocation)`: um só `getCurrentPosition` com `OPCOES_GPS` (`{enableHighAccuracy: true, timeout: 15000, maximumAge: 0}`), nunca `watchPosition`; resolve com `{lat, lng, precisao_m}` (arredondada ao metro, ou `null`) e rejeita com um `Error` com `{codigo, mensagem}` em pt-PT (`permissao_negada`, `posicao_indisponivel`, `tempo_esgotado`, `sem_gps`). `avaliarPrecisao` (≤ `LIMITE_PRECISAO_M` = 50 → `'ok'`), `MENSAGEM_LOCALIZACAO_IMPRECISA` e `limitesDoCirculo(centro, raio)` para o `fitBounds` do círculo da precisão (T2.22) |
| `localizacao.js` | `origemFinal` (arrastado → `pin_manual`), `podeConfirmar` (GPS pior do que 50 m, ou sem precisão, só depois de arrastar) e `localizacaoFinal` → `{lat, lng, origem_coords, precisao_m}` para a API, com a precisão só na origem `gps` (T2.22) |
| `morada.js` | `criarPesquisaMorada({api, aoMudarEstado, atrasoMs = 300, minimo = 3})` → `{escrever(texto, extra), cancelar()}`: espera 300 ms depois da última tecla, apara o texto, só a resposta do pedido mais recente conta, e `sem_rede`/qualquer outra falha dão o estado `erro` com `MENSAGEM_MORADA_INDISPONIVEL`. `api(texto, extra)` recebe o `extra` do `pontoDeBias` (6 casas, nunca com expoente, ou `null`). `camposDaMorada` (sugestão escolhida) e `camposSugeridos` (morada do GPS: nunca toca no que a pessoa escreveu) (T2.22) |
| `mapa.js` | `criarMapa({L, documento, elemento, configuracao, aoEscolherLoja?, aoTocarNoMapa?})` → `{mapa, atribuicao, mostrarLojas, enquadrar, redimensionar, centrarEm, destruir}`. Zoom 6–19 (`zoomControl: false` e um `L.control.zoom` com `TITULO_APROXIMAR` "Aproximar" e `TITULO_AFASTAR` "Afastar" no `title` e no `aria-label`; revisão dos ecrãs da F2: os do Leaflet, e os do autónomo, diziam "Zoom in"/"Zoom out"), `prefix: false`, uma camada com a URL do `/config` e a atribuição de `ATRIBUICOES[chave].html` (chave desconhecida → `osm`); troca para a alternativa com o `criarControloAlternativa`, uma só vez. Um pino por loja (sem agrupamento): `divIcon` sem `html`, classe `classePino(fase)`, 44 px centrados, título "Nome (Fase)", teclado (Enter/Espaço escolhem); o nome numa etiqueta permanente à direita (`className: 'etiqueta-loja'`, `tooltipAnchor [14, 0]`), que recebe um `span` do `el()` com o nome em `textContent`. `enquadrar` (fitBounds até 16, ou o centro do `/config` no zoom 12, ou `CENTRO_PADRAO`, que é o dos `PADROES` do servidor), `centrarEm(loja, ZOOM_LOJA = 17)`, `configuracaoValida`, `MENSAGEM_SEM_MAPA`. Testes com `testes/leafletFalso.js` e `testes/domFalso.js` (portados do autónomo) e mais 5 sobre o Leaflet 1.9.4 verdadeiro no jsdom (T2.23) |
| `seletor.js` | O seletor da localização sem DOM, porta de `componentes/seletor-localizacao.js` (T2.26; a parte do seletor da T2.24a): `criarSeletor({L, documento, configuracao, textos?, api?, geolocation?, aoMudar?, aoEscolherMorada?, aoSugerirMorada?, aoMudarVista?, aoFocar?})` → `{vista, localizacao, mapa, pesquisa, iniciar(elemento, {inicial}), colocar, confirmar, alterar, estouNestaLoja, desconfirmar, mostrarErro, limparErro, focar, redimensionar, destruir}`. Estados `vazio` → `por_confirmar` → `confirmado`; tocar no mapa põe o pino (`pin_manual`; confirmado, não mexe), arrastar passa a `pin_manual`, a sugestão escolhida põe-no com `geocoder` e zoom 18. Com a `api` (`{pesquisarMorada, moradaInversa}` do `api.js`) a pesquisa (`pesquisaMorada.js`, com o centro do mapa como bias) e, depois do GPS, a morada sugerida (`moradaInversa(pontoDeBias(ponto))`; 422 → nada; outra falha → `MENSAGEM_MORADA_SUGERIDA_INDISPONIVEL`). Com a `geolocation`, "Estou nesta loja": um toque, um pedido (`obterPosicao`), "A obter a localização…" não volta a pedir, círculo `circulo-precisao` (roxo `#6b2fa3`, sem toques) e `fitBounds` até 18; > 50 m ou sem precisão → "Localização imprecisa — ajuste o pino" e Confirmar só depois de arrastar; uma posição (ou erro) que chegue depois de o pino mudar é ignorada; a morada sugerida sai quando o pino muda de sítio (não ao arrastar). Pino: `divIcon({className: 'pino-seletor', iconSize: [44, 44], iconAnchor: [22, 38]})` sem `html`, arrastável, `zIndexOffset: 1000`, título do pino dos `textos`. A `vista` (`{estado, dica, aviso, erro, semMapa, confirmarAtivo, gps, moradaSugerida: {tipo, partes}, pesquisa}`, nova a cada mudança e congelada) é o que o componente desenha; o `aoFocar('confirmar'\|'alterar')` diz para onde vai o foco. Sem mapa (Leaflet que falta ou rebenta, configuração inválida): `MENSAGEM_SEM_MAPA`, sem pesquisa nem GPS, para sempre (o `limparErro` não a tira). Textos: `TEXTOS_LOJA`/`textosSeletor`, `TEXTO_TOCAR_NO_MAPA`, `TEXTO_ARRASTAR`, `TEXTO_CONFIRMADA`, `TEXTO_CONFIRMAR`, `TEXTO_ALTERAR`, `TEXTO_ESTOU_NESTA_LOJA`, `TEXTO_A_OBTER_LOCALIZACAO`, `TEXTO_A_PROCURAR_MORADA`, `partesMoradaSugerida` |
| `pesquisaMorada.js` | O campo "Pesquisar morada" sem DOM, porta de `componentes/pesquisa-morada.js` (T2.26): `criarCampoPesquisaMorada({pesquisar, obterPerto?, aoEscolher?, aoMudarVista?})` → `{vista, escrever, tecla, escolher, fechar, cancelar}` sobre o `criarPesquisaMorada` do `morada.js`. `vista`: `{texto, estado: vazio\|a_pesquisar\|resultados\|erro\|escolhida, mensagem, sugestoes, aberta, ativa}`; a lista anterior fica enquanto a nova chega; sem resultados "Nenhuma morada encontrada — escreva de outra forma ou toque no mapa."; só sugestões com rótulo e coordenadas finitas (`sugestaoValida`). `tecla(key)` → `true` quando é do campo (setas com sugestões, Enter sempre, Escape com a lista aberta). `TEXTO_MAXIMO` = 200, o do `crm/morada.py` (o teste lê o ficheiro) |
| `lojaNova.js` | O ecrã "Nova loja" sem DOM, porta do `ecras/loja-nova.js` (T2.27; a parte da T2.24a): `estadoGuardar`, `corpoLojaNova`, `carregarUltimaRegiao`/`guardarUltimaRegiao` (`crm.ultimaRegiao`, uuid; o armazenamento pode faltar ou lançar), `respostaAoErro(erro, {ficha, comSeletor = true})` (sem o seletor à vista, o erro da localização vai no alerta, a seguir à mensagem do servidor; T2.28) → `{tipo: 'duplicado', loja}` \| `{tipo: 'validacao', alerta, erros, primeiro, localizacao}` \| `{tipo: 'erro', alerta}`, `destinoDepoisDeGuardar(base, loja)`, `caminhoDaFicha(base, id)` e `criarLojaNova({api, storage, rede, base, navegar, seletor, aoMudarVista, aoFocar})` → `{vista, iniciar, mudarCampo, escolherMorada, sugerirMorada, mudarLocalizacao, guardar, responder, destruir}`. Criar não pede nada; `iniciar` pede as regiões e ouve a rede (as regiões que falharam voltam a pedir-se quando a rede volta); um toque, um pedido; `responder` só conta com o diálogo aberto e uma vez; `destruir` faz as respostas tardias, a rede e o diálogo não mexerem em nada. Textos: `TEXTO_LOJA_GUARDADA`, `TEXTO_GUARDAR`, `TEXTO_A_GUARDAR`, `TEXTO_GUARDAR_SEM_REDE` |
| `formularioLoja.js` | Os campos da loja sem DOM, porta do `componentes/formulario-loja.js` (T2.27): o estado `{valores, preenchida, erros}` e funções que devolvem o estado novo, ou o mesmo objeto se nada mudar (`estadoInicial`, `mudarCampo` — só campos deste formulário e valores aceites: fase do `FUNIL`, região uuid ou null, texto —, `alternarDia`, `escolherMorada`/`sugerirMorada` com o que a app lá pôs, `reporMorada`, `comErros`/`comErro`/`limparErros`, `ajustarRegiao`, `preencherComLoja`), `separarErros(erros, {ficha})` → `{porCampo, primeiro, restantes}`, `valoresDoFormulario` (só as chaves da API), `opcoesRegiaoLoja`/`regiaoQueFica`/`valorSeletorRegiao`/`regiaoDoSeletor` (`VALOR_SEM_REGIAO = 'sem'`: o `Select` do shadcn não aceita `''`), e as definições (`CAMPOS` com os `maxLength` do `validador_loja.py`, que o teste lê; `opcoesFase`, `camposJanelas`, `DIAS`, `TEXTO_SEM_HORARIO`). O Instagram e o site (2026-10-13) só existem com `{ficha: true}`, como as horas e os dias (`camposDoFormulario`, `estadoInicial`, `valoresDoFormulario`, `preencherComLoja`); o `maxLength` do site é o `SITE_MAXIMO` do `campos_loja.py` (o teste lê-o) |
| `dialogo.js` | O diálogo do 409 duplicado (T2.27): `lojaDuplicada` (a primeira da lista, com uuid e nome), `dialogoDuplicado(loja)` → `{mensagem: [{texto, forte}], botoes: [{texto, valor, variante}]}` e `criarEscolhaUnica` (só a primeira escolha conta) |
| `ficha.js` | O ecrã "Ficha da loja" sem DOM, porta do `ecras/loja.js` (T2.28; correção "T2.28 (Ficha da loja — fase num toque)"): `estadoGuardarFicha` (os motivos `TEXTO_FALTA_*`, pela ordem conflito → nome → correção → alterações), `corpoAlteracao(original, atual, {confirmarDuplicado})` (`camposAlterados` + o `atualizado_em` da loja em vigor), `textoLocalizacao`, `opcoesRegiaoFicha` (a região da loja que não está na lista fica como "Região guardada", para não sair da região ao guardar), `destinoDepoisDeApagar`, `caminhoNoMapa`, `PERGUNTA_APAGAR`, os textos exatos e `criarFicha({api, rede, base, id, navegar, seletor, aoMudarVista, aoFocar, aoAvisar})` → `{vista, iniciar, tentarDeNovo, mudarCampo, guardarFase, alternarDia, escolherMorada, sugerirMorada, abrirCorrecao, cancelarCorrecao, mudarLocalizacao, guardar, recarregar, responderDuplicado, pedirApagar, responderApagar, destruir}`. A fase: uma fila de 1 (um toque durante o pedido grava-se a seguir, com a versão devolvida; um só aviso, o da última), só a fase e o `atualizado_em`, a resposta atualiza só a loja em vigor (o que se escreveu noutros campos fica por guardar), sem rede ou com erro fica escolhida (o erro junto à fase) e vai no Guardar, com o conflito não grava, voltar à fase guardada não grava. A falha do `GET /regioes` fica junto à Região até as regiões chegarem, também quando a loja chega depois dela (revisão dos ecrãs da F2: o `preencherComLoja` apagava-a, e um 500 não traz o `online` que as volta a pedir; no autónomo, `preencher` não mexia nos erros). Os pedidos levam sempre o id da rota. `aoFocar`: `'recarregar'`, `'corrigir'` ou o campo do 422 |
| `membros.js` | O separador "Membros" sem DOM, porta do `componentes/definicoes-utilizadores.js` do autónomo adaptada aos membros do portal (T2.29): `membroValido` (o admin principal com `id: null`, os membros com uuid; perfil desconhecido conta), `candidatoValido`, `ordenarMembros` (admin principal, depois por nome com `Intl.Collator('pt', {sensitivity: 'base'})` e pelo id, contas apagadas no fim — a ordem do servidor), `ordenarCandidatos`, `rotuloTipoConta`, `perguntaRetirar`, `opcoesConta`, `PERFIL_INICIAL` (`PERFIS[0]`), `DESCRICOES_PERFIS`, os textos exatos e `criarMembros({api, rede, euId, aoMudarVista, aoAvisar, aoAvisarErro, aoFocar})` → `{vista, iniciar, tentarDeNovo, escolherConta, escolherPerfil, adicionar, mudarPerfil, pedirRetirar, responderRetirar, destruir}`. Um pedido de cada vez por linha (a linha ocupada mostra o perfil pedido); com a pergunta aberta nada mais muda; 409 `ja_membro`/`admin_master` e 404 → as duas listas outra vez (`Promise.allSettled`, uma falha deixa as que estavam); "Tentar novamente" e a rede pedem só o que falhou; `aoFocar`: `'user_id'`/`'perfil'` (422) ou `'titulo'` (depois de retirar) |
| `regioes.js` | O separador "Regiões" sem DOM, porta do `componentes/definicoes-regioes.js` (T2.30; correção "T2.30 (Regiões — subir/descer) e T2.9"): `ordenarRegioes` (ordem → `Intl.Collator('pt', {sensitivity: 'base'})` → id em texto), `reordenarRegioes(lista, id, ±1)` → `{lista, alteracoes}` (numera 0..n-1, só as que mudaram) ou `null`, `proximaOrdem`, `regiaoValida` (uuid), `rotulosRegiao`, `perguntaApagarRegiao`, e o ecrã `criarRegioes({api, rede, aoMudarVista, aoAvisar, aoAvisarErro, aoFocar})` → `{vista, iniciar, tentarDeNovo, mudarNova, adicionar, subir, descer, abrirEdicao, mudarNome, guardarNome, cancelarEdicao, pedirApagar, responderApagar, destruir}` (só a resposta `'apagar'` apaga) |
| `fabrica.js` | O separador "Fábrica" sem DOM, porta do `componentes/definicoes-fabrica.js` (a parte da fábrica da T2.24a, feita na T2.30): `corpoFabrica(original, {morada, ponto})` (só o que mudou; a morada aparada; lat e lng juntas, só se mudarem nas 6 casas), `estadoGuardarFabrica`, `textoPonto`, `TEXTOS_SELETOR_FABRICA`, e o ecrã `criarFabrica({api, rede, seletor, aoMudarVista, aoAvisar, aoFocar})` → `{vista, iniciar, tentarDeNovo, mudarMorada, abrirCorrecao, cancelarCorrecao, mudarPonto, escolherMorada, guardar, destruir}`; a `vista.correcao.chave` muda a cada abertura (a `key` do seletor) |
| `seguranca.test.js` | Varrimento de HTML perigoso (§0 regra 9; T2.23). Varre os `.js`/`.jsx` de `lib/crm`, `components/crm` e `pages/crm` (com subpastas), mais o `CrmLayout.js` e o `useEstadoCrm.js`; ficam de fora os `*.test.js(x)` e a pasta `testes/`. O texto inteiro conta, comentários incluídos. Recusa em todo o lado `dangerouslySetInnerHTML`, `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `.write(`/`.writeln(`, `addAttribution(`/`setPrefix(`, um `divIcon` com `html` e um `prefix` do controlo de atribuição que não seja `false`. Fora do `lib/crm/mapa.js` recusa `bindTooltip`, `bindPopup`, `setContent`, `setTooltipContent`, `setPopupContent` e `attribution:`; dentro dele, o conteúdo tem de ser um `el(...)` e a `attribution:` um `ATRIBUICOES[...].html`. Fora do `dom.js`, um texto que comece por `tel:` (só o `hrefTelefone` o monta). O detetor (`procurarHtmlPerigoso`) e a lista dos ficheiros são provados primeiro com amostras |
| `ecraMapa.js` | As decisões do ecrã do mapa, portadas do `ecras/mapa.js` do autónomo (T2.25): `vistaAoCarregar({lojas, filtros, idLoja, jaTemVista})` → `{tipo: 'centrar', loja, zoom}` \| `{tipo: 'enquadrar', lojas}` \| `null` (as lojas que se veem; todas se os filtros as escondem todas; `[]` sem lojas ou com erro; uma segunda falha não mexe; a loja do `?loja=` ao `ZOOM_LOJA`, mesmo escondida); `lojaComId`, `lerAviso`, `textoAviso` e `TEXTO_ESCONDIDA_PELOS_FILTROS` ('os filtros escondem-na do mapa.'), `textoDoErro` e `PARAMETRO_LOJA` (`loja`) |
| `css.test.js` | O `crm.css` lido do disco (T2.25): as cores e o contorno de cada `.pino--<fase>` iguais às de `FASES` (e só classes de fases que existem), a bola do pino com as variáveis, `mix-blend-mode: plus-lighter` nos mosaicos, a etiqueta inteira (`width: max-content`, `max-width: 16rem`, `white-space: normal`, sem reticências) e com cores fixas, sem regras soltas de `.etiqueta-loja`, o mapa absoluto dentro da vista (que encolhe até 8rem com o cartão) e as amostras de cor com as classes dos pinos. T2.26: a gota do `.pino-seletor` (`::before` com a cor do `ESTILO_CIRCULO` do `seletor.js`, contorno branco de 3 px, `rotate(-45deg)`; `::after` o ponto branco), roxo-escuro `#4f1f7d` com `.crm-seletor[data-estado="confirmado"]`, e a `.crm-seletor__vista` relativa com `height: clamp(16rem, 50vh, 28rem)` |

**Seletor da localização (`components/crm/SeletorLocalizacao.js`, T2.26).** Só desenha a `vista` do `criarSeletor` e liga os botões; a pesquisa é a `PesquisaMorada` (combobox, `maxLength` 200, `aria-activedescendant`, o `mousedown` das sugestões não tira o foco, "Powered by Geoapify" sempre à vista por baixo, das `partes` de `atribuicoes.js`, com `rel="noopener noreferrer"`: o ESLint do CRA exige o `noreferrer` com `target="_blank"`). Uso nos ecrãs:
- `<SeletorLocalizacao ref={…} configuracao={…} inicial={…} comGps textos={…} aoMudar={…} aoEscolherMorada={…} aoSugerirMorada={…} />`;
- `configuracao` é a do `obterConfigMapa()`: `undefined` enquanto chega (sem mapa, campo desativado, `aria-busy`), `null` ou inválida → `MENSAGEM_SEM_MAPA`. Tem de ser o mesmo objeto entre desenhos: um objeto novo cria outro mapa;
- `inicial` (`{lat, lng, origem, precisao_m?}`), `comGps`, `textos` e `focarAoIniciar` leem-se só ao criar; `comGps` lê o `navigator.geolocation` ao criar, mas a posição só se pede ao tocar; com `focarAoIniciar` (a ficha, T2.28: o "Corrigir localização" em que se tocou desaparece) o foco vai para "Confirmar localização" quando o mapa existe;
- `aoMudar(localizacao | null)`: o bloco `{lat, lng, origem_coords, precisao_m}` que a API recebe; `aoEscolherMorada`/`aoSugerirMorada` para o ecrã aplicar `camposDaMorada`/`camposSugeridos`;
- pela `ref`: `mostrarErro(texto)`, `limparErro()`, `desconfirmar()`, `focar()`, `colocar(ponto, {zoom})` e `localizacao`;
- o seletor cria-se num `useEffect` (com `destruir()` no cleanup, que cancela a pesquisa e ignora o GPS e a morada que chegarem depois) e um `ResizeObserver` volta a medir o mapa. O mapa fica num contentor relativo com altura própria (`.crm-seletor__vista`).

**Formulário e diálogo (`components/crm/{FormularioLoja,DialogoDuplicado}.js`, T2.27).** Só desenham o que recebem:
- `<FormularioLoja ref valores erros opcoesRegiao valorRegiao ficha? desativado? aoMudar(campo, valor) aoMudarFase? aoAlternarDia? />`: controlado (o estado é o do `formularioLoja.js`); a região chega a `aoMudar` já como uuid ou null; a fase vai também para `aoMudarFase` (a ficha grava-a num toque); com `ficha`, o horário (quatro `type="time"`, rótulos "Início/Fim da 1.ª janela" para os leitores de ecrã) e os dias fechada, antes das notas. Os erros ficam por baixo de cada campo, com `aria-invalid`, `aria-describedby` e a borda a vermelho; pela `ref`, `focar(campo)` (na fase, a escolhida; nos dias, o primeiro). Os campos de texto têm `autoComplete="off"` (são os dados da loja, não os de quem escreve).
- `<DialogoDuplicado duplicado={{loja, mensagem, botoes} | null} aoResponder(valor, loja) refFocoAoFechar />`: `AlertDialog` do shadcn; a pergunta é o título, com o nome em `<strong>` (texto); o foco vai para a primeira escolha e, ao fechar, para `refFocoAoFechar`; o Escape conta como "Cancelar" (`null`); uma escolha por pergunta.
- A página cria o ecrã (`criarLojaNova`) num `useEffect` com `destruir()` no cleanup, entrega-lhe o seletor por um adaptador sobre a `ref` (`limparErro`, `desconfirmar`, `mostrarErro`, `focar`) e desenha a `vista`; o estado da rede é um só `criarEstadoRede(window, navigator)` para a página.

**Ficha (`pages/crm/CrmLoja.js`, T2.28).** A rota `lojas/:lojaId` desenha `<FichaDaLoja key={lojaId}>`: outra loja na mesma rota ("Sim, abrir X") é outra ficha, criada de novo. A página cria o `criarFicha` num `useEffect` (`destruir()` no cleanup), pede o `obterConfigMapa()` uma vez (para o seletor) e desenha a `vista`: `IndicadorCrm` "A carregar a ficha…", a falha (`role="alert"`, "Tentar novamente" ou "Voltar ao mapa"), a faixa do conflito, o formulário (`noValidate`) com um `<fieldset disabled>` à volta dos campos e da localização enquanto grava, o resumo ou o `<SeletorLocalizacao key={correcao.chave} inicial comGps focarAoIniciar>`, o alerta e o porquê do Guardar (`aria-live`), "Apagar loja" (contorno vermelho) com o erro, o `DialogoDuplicado` e um `AlertDialog` para a pergunta do Apagar (o foco em Cancelar ao abrir, no "Apagar loja" ao fechar; Escape = Cancelar). Os avisos de sucesso são `toast.success`. A fase vai do `FormularioLoja` por `aoMudar('fase', …)` e logo `aoMudarFase` → `guardarFase()`.

**Definições (`pages/crm/{CrmDefinicoes,DefinicoesMembros}.js`, T2.29).** A rota `definicoes` (dentro do `SoAdminCrm`) desenha o `CrmDefinicoes`: `PageHeader` e os separadores com 44 px, cada um no seu componente (`DefinicoesMembros`, `DefinicoesRegioes` e, carregada à parte, `DefinicoesFabrica`). O `DefinicoesMembros` cria o `criarMembros` num `useEffect` (`destruir()` no cleanup), com o `euId` do `useAuth().user.id`, e desenha a `vista`: `IndicadorCrm` "A carregar os membros…", a falha com "Tentar novamente", a tabela (shadcn `Table` com `role` explícitos e `data-rotulo`), o `Select` do perfil por linha (`aria-label` "Perfil de X"), "Retirar" com `aria-label` "Retirar X do CRM" e `aria-disabled` (não `disabled`) enquanto a linha grava, o formulário `noValidate` com os dois `Select` (`aria-invalid`/`aria-describedby` no 422) e um `AlertDialog` para a pergunta (o foco na primeira escolha ao abrir e no "Retirar" em que se tocou ao fechar). Avisos: `toast.success` e `toast.error`. **Regiões e Fábrica (`pages/crm/{DefinicoesRegioes,DefinicoesFabrica}.js`, T2.30)**, no mesmo molde (`criarRegioes`/`criarFabrica` num `useEffect`, a `vista` desenhada, toasts): nas regiões, um `useLayoutEffect` põe o foco onde o ecrã pede (`aoFocar`: o título, "Nova região", ou `data-foco="<alvo>:<id>"` de um botão ou campo de uma linha) e outro devolve-o ao elemento que o tinha quando o React muda essa linha de sítio (o Chromium e o jsdom mantêm-no; fica para os browsers que o tiram, como o `desenhar()` do autónomo). A `DefinicoesFabrica` pede o `/config` uma vez (o `undefined`/`null` do seletor), entrega o seletor ao ecrã pela `ref` (`limparErro`, `desconfirmar`, `mostrarErro`, `focar`) e, sem mapa, põe o foco em "Cancelar a mudança do ponto". Importa o `crm.css` antes do `SeletorLocalizacao`, pela ordem das outras páginas: sem isso o build avisava "Conflicting order" entre o `crm.css` e o `leaflet.css` (T2.32).

Mensagens de rede: `'Sem rede — verifique a ligação e tente novamente.'` e `'Erro inesperado — tente novamente.'`.

**Erros no frontend (`lib/crm/api.js`, T1.10).** Todo o erro do cliente sai como `ErroCrm {codigo, mensagem, campos, extra, estado}`:
- `detail` objeto do CRM → tal como vem (`campos` só se for objeto simples; `extra` = as outras chaves, ex.: `lojas`);
- sessão: 401 em texto → `nao_autenticado` com o texto; `"Not authenticated"` e `"Invalid authentication credentials"` (403 do `HTTPBearer`) → `nao_autenticado` com `'Sessão terminada'`, nunca o inglês; outro 403 em texto → `sem_permissao`;
- 422 em lista (Pydantic) → `validacao` com `'Verifique os campos assinalados.'` e um campo por chave;
- sem resposta → `sem_rede` (estado 0); um erro que não veio do axios → `erro_interno`, nunca `sem_rede`; o resto → `erro_interno` com a mensagem genérica.

O interceptor lê o token do axios global a cada pedido e, sem token, **tira** o `Authorization`: o `axios.create` copia os
`defaults` ao nascer e mandaria o token de uma sessão já terminada.

**Chamadas (`lib/crm/api.js`, T1.10 e T2.24).** Cada função devolve só os `data` da resposta; os erros saem como `ErroCrm`. Em `criarClienteCrm({pedir})` (os testes passam um `pedir` falso) e já ligadas à instância do CRM como exportações do módulo:
- F1: `obterEu`, `listarMembros`, `listarCandidatos`, `adicionarMembro({user_id, perfil})` (só essas duas chaves), `mudarPerfilMembro(id, perfil)`, `retirarMembro(id)`;
- regiões: `listarRegioes()` (GET), `criarRegiao(corpo)` (POST), `alterarRegiao(id, corpo)` (PATCH), `apagarRegiao(id)` (DELETE);
- lojas: `listarLojas()`, `obterLoja(id)`, `criarLoja(corpo)`, `alterarLoja(id, corpo)`, `apagarLoja(id)`. O 409 `duplicado` traz `extra.lojas` (`[{id, nome, distancia_m}]`) e reenvia-se com `confirmar_duplicado: true` no corpo; o 409 `conflito` só traz código e mensagem;
- `obterDefinicoes()`, `alterarDefinicoes(corpo)` (PATCH) e `obterConfigMapa()` (`GET /config`);
- morada: `pesquisarMorada({texto, lat, lng})` e `moradaInversa({lat, lng})`, com os valores em query. No seletor, `criarPesquisaMorada({ api: (texto, extra) => pesquisarMorada({ texto, ...(extra ?? {}) }), … })`, com o `extra` do `pontoDeBias(centro)`; a inversa recebe o `pontoDeBias(ponto)` (6 casas: o servidor recusa números com expoente). A rede em baixo continua `sem_rede` no estado de erro da pesquisa.

Regras fixadas pelos testes:
- **Corpos tal e qual.** Os corpos vão como o ecrã os montou nas regras puras (`corpoLojaNova`, `corpoFabrica`, `camposAlterados` + `atualizado_em`); o servidor valida e ignora as chaves que não conhece (regiões).
- **Query sem nulos.** `null` e `undefined` não saem (nunca o texto "null"), e o zero fica (`lat: 0` é um número). Só `texto`, `lat` e `lng` (pesquisa) ou `lat` e `lng` (inversa) saem. Sem ponto, a inversa vai sem parâmetros e o servidor responde 422. O axios codifica a query como formulário (espaço → `+`), e o Starlette lê-a igual: acentos, vírgulas, `&`, `#` e `+` chegam tal como foram escritos.
- **Ids num só pedaço do caminho.** O id vai com `encodeURIComponent` (`a/b` → `a%2Fb`). Um id `''`, `'.'` ou `'..'` **nunca sai**: rejeita com `erro_interno` e a mensagem genérica, sem pedido. O URL do browser resolve esses pedaços antes de enviar (`/lojas/..` → `/api/crm/`, `/lojas/.` → a lista; `%2e%2e` também conta como `..`), e `/lojas/` vazio leva à lista pelo redirecionamento do FastAPI. As funções com id são `async`, por isso a recusa rejeita a promessa e não lança fora dela.

**Botões de zoom em pt-PT (revisão dos ecrãs da F2):** o `criarMapa` (mapa das lojas e seletor: Nova loja, Corrigir localização, Fábrica) cria o mapa com `zoomControl: false` e junta `L.control.zoom({zoomInTitle: 'Aproximar', zoomOutTitle: 'Afastar'})`; a posição e as classes são as mesmas, por isso a regra dos 44 px e o `left: 66px` da barra não mudam. Provado no `mapa.test.js` e no `seletor.test.js` com o Leaflet 1.9.4 verdadeiro (o `title` e o `aria-label` dos dois botões).

**Botões de zoom com 44 px (T2.32):** a regra é `.crm-mapa.leaflet-container .leaflet-bar a` e ganha pela especificidade. O Leaflet põe `leaflet-touch` em todos os browsers com `PointerEvent` (o Chrome do computador também), e o `.leaflet-touch .leaflet-bar a` do `leaflet.css` (30 px) vem **depois** do `crm.css` no build e no `craco start`, porque o cartão, os filtros e o formulário importam o `crm.css` antes do mapa e do seletor. Com a regra antiga (`.crm-mapa .leaflet-bar a`, a mesma especificidade) os botões ficavam com 30×30 (medido no browser na aceitação da F2); o `css.test.js` compara agora a especificidade com a do Leaflet. Uma regra nova do `crm.css` que queira mudar o `leaflet.css` tem de ganhar pela especificidade, nunca pela ordem.

**Mapa sem juntas:** `.crm-mapa img.leaflet-tile { mix-blend-mode: plus-lighter; }`, a etiqueta com cores fixas
(legível no tema escuro) e o contentor com altura explícita.
- **O `leaflet.css` 1.9.4 já traz esta regra** (`.leaflet-container img.leaflet-tile { mix-blend-mode: plus-lighter; }`, também no `vendor/leaflet/leaflet.css` do autónomo): a do `crm.css` repete-a, e tirá-la não mudava nada. Para a desligar seria preciso `mix-blend-mode: normal`.
- **Medido na T2.25** (Chrome 154 instalado, headless com ANGLE Metal; 12 deslocamentos do mapa sobre o mar às escalas 1,25, 1,5, 1,75 e 2,5; `t2.25-juntas-amostra.log`): em cerca de metade das vistas há uma linha de junta. Com o plus-lighter a linha é quase branca (desvio da cor do mar ~100); sem ele, quase invisível (~15). Na vista inicial do seed não há linhas. Fica por ver nos ecrãs do dono (§14, ponto 12).

---

## 8. Integrações externas

**Geoapify** (dados OpenStreetMap; plano gratuito de 3 000 créditos/dia com uso comercial; os resultados podem ser guardados). Usa duas chaves:

- **Mosaicos** (vai para o browser só por `GET /api/crm/config`, para membros):
  - o modelo é `https://maps.geoapify.com/v1/tile/osm-bright/{z}/{x}/{y}.png?apiKey=<chave codificada>`;
  - a chave é lida a cada pedido (`crm/config_mapa.py`, `chave_mosaicos()`; T2.13), e só a chave vazia ou a variável em falta contam como "sem chave" (como o `$chave === ''` do autónomo; uma chave só com espaços vai codificada e a Geoapify recusa-a, e o mapa muda sozinho para a alternativa);
  - codifica-se como o `rawurlencode` do PHP: `urllib.parse.quote(…, safe="")` sobre os bytes (`surrogateescape`), por isso só `A-Za-z0-9-_.~` ficam e a barra também se codifica. Um modelo que já tenha `?` recebe a chave com `&` (caso do `ConfigMapaTest` mantido na função pura `config_mapa`);
  - a rota é só para membros do escritório (admin e utilizador), nunca pública, e a chave nunca se escreve nos registos (teste com chave canária e `caplog`);
  - no painel da Geoapify fica **restrita por Referer** a `https://lisbonb.com`.
  - Sem chave, `url` é a alternativa `https://tile.openstreetmap.org/{z}/{x}/{y}.png` com `atribuicao: "osm"`. É o normal em local.
  - O `rh.lisbonb.com` é sinónimo **permanente** no Caddyfile (as apps instaladas trazem esse endereço). Com a restrição planeada, quem entra por `rh.lisbonb.com` fica sempre nos mosaicos OSM (decisão do dono, §14).
- **Servidor** (pesquisa de morada e morada sugerida; nunca vai para o browser):
  - Pesquisa: `<CRM_GEOAPIFY_URL>/v1/geocode/autocomplete` com `text`, `filter=countrycode:pt`, `bias=proximity:<lng>,<lat>` (só com ponto válido; coordenadas até 6 casas sem zeros no fim), `lang=pt`, `limit=5`, `format=json` e `apiKey`.
  - Inversa: `<CRM_GEOAPIFY_URL>/v1/geocode/reverse` com `lat`, `lon`, `lang=pt`, `format=json` e `apiKey`.
  - Normalização: `{rotulo, morada ("Rua Augusta 24"), codigo_postal (só 0000-000), localidade (city → town → village → county), lat, lng}`. Ignoram-se resultados sem coordenadas, sem `formatted`, fora de `pt` ou fora do continente.
  - **Pedidos e respostas (T2.14):** `crm/servicos/geoapify.py`, funções puras sem rede, porta do `Geoapify.php`:
    - `url_pesquisa(url_base, chave, texto, perto=None)` e `url_inversa(url_base, chave, lat, lng)`; `perto` é `{"lat", "lng"}`. O URL base perde todas as barras do fim (`rtrim`). O texto vai tal e qual: quem o apara e valida é a rota (T2.15). Os parâmetros vão por esta ordem: `text, filter, [bias], lang, limit, format, apiKey` e `lat, lon, lang, format, apiKey`.
    - As coordenadas seguem o `number_format($v, 6)` do PHP, sem zeros no fim: meio-para-longe-do-zero (1.0000005 → `1.000001`), e um negativo que arredonda a zero sai `0`, nunca `-0`. Recebem números já validados; um bool, NaN ou infinito dá `ValueError`.
    - `normalizar_autocomplete(resposta)` → lista pela ordem da Geoapify, sem cortar (o limite vai no pedido). `normalizar_inversa(resposta)` → o primeiro válido ou `None`. As chaves vêm sempre por esta ordem e `lat`/`lng` são sempre `float`.
    - **Fidelidade ao PHP:**
      - os textos aparam-se com o `trim()` do PHP (`" \t\n\r\0\x0B"`), não com o `aparar`. Um rótulo com um espaço sem quebra nas pontas fica com ele, uma `city` só com U+00A0 conta como localidade e um `postcode` com U+00A0 ou U+2028 no fim não passa. A pessoa revê a sugestão, e a loja, ao gravar, é aparada pelo validador;
      - o país compara-se só em ASCII (`" PT "` e `"pT"` passam; `"pt "` e `"ＰＴ"` não);
      - a coordenada tem de ser um número do JSON dentro da caixa do §5.3 (`contem_latitude`/`contem_longitude`): nunca um bool, um texto, NaN, infinito ou um inteiro maior do que um float;
      - um `results` que seja um objeto JSON percorre-se pelos valores, como o `foreach` do PHP; uma resposta que não seja um objeto (lista, texto, número, `null`) dá `[]`/`None`;
      - o `name`, o `address_line1` e o resto não passam (nome e telefone são sempre escritos pela pessoa).
    - **Conferido com o PHP 8.4.26** (não versionado, `t2.14-conferencia-php.log`): a própria classe do autónomo e a porta deram o mesmo resultado em 20 045 URLs e 20 079 respostas, sem diferenças. Os URLs incluíam bases com e sem barras, textos e chaves com espaços Unicode, reservados e emojis, e coordenadas com empates às 6 casas, inteiros, `-0.0` e valores até 10⁶. As respostas incluíam as entradas das tabelas dos testes, as duas gravadas e 20 000 aleatórias, com `1e400`, inteiros enormes, bools, objetos no lugar de listas e resultados que são listas. Ao todo, 14 749 sugestões aceites e 10 547 respostas sem nenhuma; tipos e ordem das chaves comparados.
  - Cliente `httpx` assíncrono com `Timeout(5.0, connect=3.0)`. `CRM_GEOAPIFY_URL` (por omissão `https://api.geoapify.com`) é lido a cada pedido.
  - **Rotas e cliente (T2.15):** `crm/morada.py` (porta do `MoradaControlador`, regras do pedido no §6, "Morada") e o fim de `crm/servicos/geoapify.py` (porta do `ClienteHttpCurl`). Testes em `test_morada.py`, com todos os casos do `MoradaControladorTest.php`, do `MoradaTest.php` e do `ClienteHttpCurlTest.php`, com os nomes de lá:
    - `chave_servidor()` e `url_base()` leem `CRM_GEOAPIFY_CHAVE_SERVIDOR` e `CRM_GEOAPIFY_URL` a cada pedido (nomes em `geoapify.VARIAVEL_CHAVE_SERVIDOR` e `VARIAVEL_URL`). Só a chave vazia ou em falta conta como "sem chave": 503 sem chamar a Geoapify nem escrever registo (é o normal em local). Uma chave só com espaços vai codificada (`%20`) e a Geoapify recusa-a. Um URL vazio ou em falta dá a Geoapify.
    - `obter_json(url)`: GET com `Accept: application/json`, sem `Referer`, sem seguir redireções (`follow_redirects=False`), `TEMPO_LIMITE = httpx.Timeout(5.0, connect=3.0)` e ainda `TEMPO_TOTAL_SEGUNDOS = 5.0` para o pedido inteiro (`asyncio.wait_for`): o `CURLOPT_TIMEOUT_MS` do autónomo era o total, e os tempos do httpx são por fase. O URL vai tal e qual (o httpx não o volta a codificar; conferido nos testes).
    - Qualquer estado fora de 200–299 (incluindo 3xx), exceção do pedido ou corpo que o `json_decode` do PHP recusaria → `FalhaServicoExterno(motivo)` → 503 `morada_indisponivel` com a mensagem da rota (§6). O cliente é assíncrono: enquanto espera pela Geoapify, o portal continua a responder (no autónomo, a sessão PHP libertava-se antes; testado com dois pedidos no mesmo ciclo de eventos).
    - **O corpo lê-se como o `json_decode($corpo, true, 512, JSON_THROW_ON_ERROR)` + `is_array`** (`geoapify.ler_json`): UTF-8 estrito (o `json.loads` aceitava UTF-16 em bytes), sem `NaN`/`Infinity`/`-Infinity` (`parse_constant`), até 511 níveis (o PHP 8.4 recusa 512; com muitos mais, o `RecursionError` do Python passa a `ValueError`), sem surrogates sozinhos em valores ou chaves (deixados passar, a resposta da rota rebentava com 500 no `encode`), e só objeto ou lista.
    - Uma resposta que seja uma lista JSON passa e dá `[]`/`null` (o `is_array` do PHP aceitava-a).
    - **Conferido com o PHP 8.4.26** (não versionado, `t2.15-conferencia-php.log`): 20 000 pedidos às rotas (o `MoradaControlador` do autónomo, com um cliente que só regista o URL, contra `morada.pesquisa`/`morada.inversa`: estado, corpo, ordem dos campos e URL pedido; 4000 deles também pelo `TestClient`, com o FastAPI a ler a query) e 20 000 corpos JSON (aceitação + normalização, com NaN, BOM, surrogates, bytes que não são UTF-8, UTF-16/32, caracteres de controlo e 509 a 2000 níveis). 0 diferenças: 8 558 pesquisas e inversas com 200, 10 487 com 422, 955 com 503; 10 340 corpos aceites e 9 660 recusados.
    - **Ensaio no portal local** (não versionado, `t2.15-ponta-a-ponta.log`): o uvicorn verdadeiro com o `server.py` (`basicConfig(INFO)`), a chave canária e uma Geoapify falsa em 127.0.0.1, com as contas de demonstração. Os 14 pontos passaram: pesquisa e inversa 200, 503 com a mensagem exata, 422, 403 sem sessão e ao motorista, e um registo sem a chave, sem `HTTP Request` do httpx e com a linha `[crm]` da falha.
- **Chave fora dos registos:**
  - os loggers `httpx` e `httpcore` ficam em `WARNING` à importação do `crm` (num processo novo, testado com `basicConfig(INFO)`) e outra vez antes de cada pedido, se alguém os tiver baixado. Vale para todo o processo do portal: os outros módulos que usam o httpx também deixam de registar cada pedido em INFO;
  - **apanha-se `Exception`, e não só a base `httpx.HTTPError`** (desvio da correção "T2.15", mais largo): no httpx 0.28, o `httpx.InvalidURL` (ex.: uma porta com letras no `CRM_GEOAPIFY_URL`) herda diretamente de `Exception`, e a mensagem do httpx traz o URL com a chave. É o molde de `faturacao/pontos_app.py`. O `ValueError` do JSON também dá 503;
  - regista-se só o motivo: `[crm] morada: a Geoapify falhou na <pesquisa|inversa> — <estado HTTP 500 | sem resposta (ReadTimeout) | resposta que não é JSON (JSONDecodeError)>`, em WARNING. **Nunca `str(exc)`**, o URL, a chave, o corpo da resposta nem o texto pesquisado (o `RegistoErros` do autónomo também nunca registava a query). A `FalhaServicoExterno` lança-se fora do `except`, sem a exceção do httpx como causa nem contexto, por isso um `logger.exception` mais acima também não a escreveria;
  - os testes usam uma chave canária e `caplog` em DEBUG: o sucesso; o 500, o 401, o 301, um corpo que não é JSON e o NaN; e as exceções `ReadTimeout`, `ConnectTimeout`, `ConnectError`, `ReadError`, `RemoteProtocolError`, `TooManyRedirects`, `DecodingError`, `UnsupportedProtocol`, `InvalidURL` e `RuntimeError`, com a mensagem a trazer o URL. Também cobrem um `CRM_GEOAPIFY_URL` mal escrito, com o transporte verdadeiro, e a rede verdadeira em 127.0.0.1, com o httpcore em DEBUG;
  - **diferença assumida:** o registo de acessos do uvicorn, que é do portal e vale para todas as rotas, escreve o caminho com a query. O texto pesquisado aparece lá codificado (`texto=Rua%20Augusta`); a chave nunca, porque não vai no URL das nossas rotas. O autónomo não registava a query. O texto é uma morada de loja, escrita pela pessoa.
- Respostas gravadas em `backend/tests/crm/fixtures/geoapify/` (`autocomplete-rua-augusta.json` e `reverse-praca-comercio.json`, copiadas do autónomo e marcadas para regravar com a chave de desenvolvimento do dono, §14). São iguais às do autónomo exceto o `_origem`, que passou de "manual — regravar na H6" para "manual — regravar": a H6 era um passo do plano do autónomo. Ao regravar, retirar o `apiKey` (um teste confere que nenhuma o traz) e manter os campos que os testes de `test_geoapify.py` esperam, ou atualizar esses testes.

**Atribuições** (textos exatos, de `lib/crm/atribuicoes.js`):

| Onde | Texto |
|---|---|
| Mapa com mosaicos Geoapify | `Powered by Geoapify \| © OpenMapTiles © OpenStreetMap contributors` |
| Mapa com mosaicos OSM | `© OpenStreetMap contributors` |
| Pesquisa de morada e morada sugerida | `Powered by Geoapify` (sempre visível) |
| Planear rota (F3) | `Developed by VROOM · Hosted by HeiGIT · Routing by openrouteservice · Data from OpenStreetMap` |

**`Referrer-Policy`:** hoje nem o Caddyfile nem o `frontend/nginx.conf` a definem, por isso vale o padrão do browser
(`strict-origin-when-cross-origin`, o valor exato do CRM autónomo). **Nunca** pôr `no-referrer` nem `same-origin`.

**openrouteservice (F3):** Optimization (VROOM) e Directions, só no servidor, com a chave no cabeçalho
`Authorization`. Plano Standard: 500 otimizações e 2 000 directions por dia, 40 por minuto, sem garantia de
serviço. Proibido enviar dados pessoais. Se falhar: "Cálculo automático indisponível — ordene à mão".
- **Cliente (T3.11, `crm/servicos/ors.py`; testes em `tests/crm/test_ors.py`):** `otimizar(pedido)` faz POST a `{base}/optimization` e `direcoes(pedido)` a `{base}/v2/directions/driving-car/json` (a base com ou sem barras no fim); corpo `json.dumps(pedido, allow_nan=False)` (um NaN é `ValueError`, um engano do código, nunca uma `FalhaOrs`); cabeçalhos `Authorization: <chave tal e qual, sem Bearer>`, `Content-Type` e `Accept` `application/json`; sem seguir redireções; 3 s para ligar, 15 s ao todo na otimização e 10 s no Directions (`asyncio.wait_for`). `CRM_ORS_CHAVE` e `CRM_ORS_URL` leem-se a cada chamada (ou vêm por parâmetro, `chave=`/`url=`). Sem chave → `FalhaOrs(tipo="sem_chave")` sem pedido nenhum. O `CRM_ORS_URL` só pode ser `https://…`, ou `http://` para `127.0.0.1`, `localhost` ou `[::1]` (o simulador local), sem `?`, `#`, `@`, espaços nem porta inválida: o resto é `FalhaOrs("CRM_ORS_URL recusado")` sem pedido (um `http://` para fora mandava a chave sem cifra). O módulo reutiliza o `ler_json` e o `silenciar_registos` da Geoapify.
- **Falhas (`FalhaOrs(motivo, tipo, indice=None)`; tipos `sem_chave`, `indisponivel`, `limite`, `ponto_sem_estrada`):** 429 → `limite` ("estado HTTP 429", seja qual for o corpo); `{"error": {"code": 2010, "message": "… coordinate N: …"}}` (ou o antigo "… point N: …"; o `code` tem de ser o inteiro 2010) no Directions → `ponto_sem_estrada` com `indice == N` (o ORS conta a partir de 0: o início é a coordenada 0; quem traduz para a paragem é a rota, T3.21/T3.22) e o motivo "estado HTTP N (código 2010)"; na otimização o mesmo 2010 é `indisponivel` (a mensagem geral; o "Recalcular horas" identifica a paragem). Um 2010 sem número, o erro na forma do VROOM (`{"code": 3, "error": "<texto>"}`, com coordenadas no texto, que nunca sai do cliente), 401, 403, 5xx e 3xx → `indisponivel` com "estado HTTP N"; uma falha da rede ou o tempo esgotado → "sem resposta (<Tipo>)"; um 2xx que não é um objeto JSON → "resposta que não é JSON (<Tipo>)" ou "resposta que não é um objeto JSON". **Um 403 quer dizer quota diária esgotada ou chave inválida** (§14, ponto 5). O módulo nunca regista nada (quem chama regista só o `motivo`; `str(falha) == motivo`), a falha não arrasta a exceção do httpx (`__cause__`/`__context__` nulos) e os registos `httpx`/`httpcore` voltam a WARNING antes de cada pedido. Testes com a chave e as coordenadas canárias no `caplog` em DEBUG (root, `httpx`, `httpcore`) em todos os caminhos, mais a rede verdadeira em 127.0.0.1.
- **Guarda dos testes (`tests/crm/conftest.py`):** um fixture `autouse` de todos os testes do CRM põe em `ors._transporte` um `MockTransport` que regista o pedido e responde 599 e, no fim do teste, exige a lista vazia ("pedido ao openrouteservice sem o transporte do teste"); tira também `CRM_ORS_CHAVE` e `CRM_ORS_URL` do ambiente (quem precisa de chave põe-na com `setenv`). Nenhum teste chega ao openrouteservice verdadeiro.

**Navegação (F4), links `<a href>` tocados pela pessoa e sem chave:**
- `https://www.google.com/maps/dir/?api=1&destination=LAT,LNG&travelmode=driving&dir_action=navigate[&avoid=tolls]`
- `https://waze.com/ul?ll=LAT,LNG&navigate=yes[&avoid_tolls=true]` (o `avoid_tolls` não está na documentação oficial do Waze: a confirmar no telemóvel da carrinha, §14 ponto 11)
- Blocos de 9 paragens no Google Maps, a confirmar no telemóvel da carrinha (§14 ponto 11). Tudo calculado no servidor (`crm/dominio/navegacao.py`, T3.10).

**Google Places/Routes: não se usa.** Os termos europeus do Google Maps Platform (desde 8 jul 2025) proíbem
guardar nome, morada, telefone e coordenadas vindos da Google. **Não se reutiliza a chave Google Places do
portal** (é do Marketing) e não se guarda nenhum dado da Google: todas as coordenadas guardadas são "nossas"
(pino confirmado, GPS no local ou geocoder que permite guardar).

**Leaflet 1.9.4** do npm (`yarn add leaflet@1.9.4 --exact`), sem `markercluster`, com o `leaflet.css` do pacote.
Adicionado na T2.19 (commit isolado, só `package.json` +1 e `yarn.lock` +5). O pacote só declara
`"main": "dist/leaflet-src.js"` (UMD, sem `module` nem `exports`); `import * as L from 'leaflet'` funciona.

---

## 9. Configuração e segredos (só nomes)

**Produção** (`backend/.env` no servidor, preenchido pelo dono; no repositório só os nomes, em `backend/.env.example`, T2.16):

| Variável | Para quê | Fase |
|---|---|---|
| `CRM_GEOAPIFY_CHAVE_SERVIDOR` | Pesquisa e morada sugerida (só no servidor) | F2 |
| `CRM_GEOAPIFY_CHAVE_MOSAICOS` | Mosaicos (vai para o browser, restrita por Referer) | F2 |
| `CRM_GEOAPIFY_URL` | Opcional; por omissão `https://api.geoapify.com` | F2 |
| `CRM_ORS_CHAVE`, `CRM_ORS_URL` | openrouteservice | F3 |
| `ADMIN_EMAIL` (já existe) | Admin master do portal = admin do CRM | F1 |
| `CRON_KEY` (já existe, partilhada com o Financeiro) | `/api/crm/cron/*` | F5 |
| `MONGO_URL`, `DB_NAME`, `JWT_SECRET` (já existem) | Os do portal; o CRM não cria ligações próprias (`crm.db.obter_db` → `faturacao.db.obter_db`) | — |

- **`backend/.env.example` (T2.16):** um bloco no fim ("CRM Purple House (backend/crm) — Geoapify"), com comentário pt-PT e só os nomes `CRM_GEOAPIFY_CHAVE_SERVIDOR=`, `CRM_GEOAPIFY_CHAVE_MOSAICOS=` e `CRM_GEOAPIFY_URL=`, sem valores e sem aspas. É ficheiro partilhado com o Matheus: só se acrescentaram linhas, nada do resto mudou. Vazias, as três dão o comportamento sem chaves (o `CRM_GEOAPIFY_URL` vazio vale `https://api.geoapify.com`). O docker-compose passa o `backend/.env` inteiro ao backend (`env_file`), por isso não há nada a mudar lá.
  - **Guarda (`tests/crm/test_variaveis_ambiente.py`):** procura no código do pacote `crm`, pela árvore sintática, cada leitura do ambiente (`os.environ.get/[…]/setdefault/pop`, `… in os.environ`, `os.getenv`), com o nome literal ou numa constante do módulo. Uma leitura sem nome que se resolva (nome dinâmico, `dict(os.environ)`) falha o teste. Exige: o pacote lê exatamente `ADMIN_EMAIL`, `CRON_KEY` e as três `CRM_GEOAPIFY_*`; todas têm o nome no `.env.example`; os `CRM_*` do `.env.example` são exatamente os que o pacote lê, sem repetidos e sem valor; o bloco fica depois da última variável do resto do portal, com um só cabeçalho. Na F3, ler `CRM_ORS_CHAVE`/`CRM_ORS_URL` fica vermelho até os nomes entrarem no `LIDAS_PELO_CRM` e no bloco. O `CRM_MONGO_TESTE_URL` (ensaio local) nunca entra no `.env.example`, e as mensagens de falha mostram só nomes.
- **Nunca:** valores reais no chat, no git, em registos ou neste dossiê. Sem chaves, o CRM funciona na mesma: mapa com mosaicos OSM e pesquisa de morada → 503 com a mensagem exata.
- **Só em local:** `backend/.env.local`, `frontend/.env.development.local` (§12.3) e `CRM_MONGO_TESTE_URL` (variável de shell para o ensaio da T2.17, sempre `mongodb://127.0.0.1:27017` com a base `lisbonb_crm_teste`).
- Não endurecer a `Referrer-Policy` (§8). Não usar `GOOGLE_PLACES_API_KEY` no CRM.
- A chave dos mosaicos fica restrita a `https://lisbonb.com`. Quem entra por `rh.lisbonb.com` (sinónimo permanente no Caddyfile) recebe os mosaicos OSM, salvo decisão em contrário do dono (§14, ponto 4).

---

## 10. Plano faseado F0–F6

| Fase | O que traz | Membros | Tarefas |
|---|---|---|---|
| **F0. Preparação** | Ambiente local, seed com guarda, este dossiê; [DONO]: `ADMIN_EMAIL`, cópias do Atlas, contas Geoapify/ORS, aviso ao Matheus | — | T0.1–T0.10 |
| **F1. Casca** | Pacote `crm` (`/saude`, `/eu`, membros, candidatos), teste de proteção, montagem no `server.py`, área `/crm` e secção CRM só para membros, páginas "Brevemente" | Só o Bruce | T1.1–T1.15 |
| **F2. Base** | Domínio portado, regiões, lojas (criar/editar/apagar, duplicados, GPS), definições, `/config`, morada, ensaio no Mongo local, seed de lojas, Leaflet, mapa, nova loja, ficha, definições, privacidade | O Bruce e quem ele escolher | T2.1–T2.32 |
| **F3. Planear rota** | Dia, paragens, sugestões por fase (5 km), horários e dias fechados, VROOM + Directions, arrastar, portagens, avisos, links, 48 paragens, fecho simples | + escritório | Plano próprio |
| **F4. Rota do dia** | `/rota`, registos num toque, fila sem rede, "Estou nesta loja" e corrigir no terreno, campos de visita pendente e últimas visitas | + motorista | Plano próprio |
| **F5. Resto da Etapa 2** | Linha do tempo, produtos, encomendas, alertas 📦 🔁 ⏰, sugestões por alerta, fecho noturno (cron) | | Plano próprio |
| **F6. Fecho** | Auditoria de permissões, abrir à equipa, rever as apps nativas | Toda a equipa | Plano próprio |

**Ciclo de cada fase:**
1. Ramo local;
2. `pytest tests/crm`, Jest e build local;
3. **[DONO]** aprova a subida;
4. junção ao `main` (merge, nunca rebase nem force-push);
5. `deploy.sh` no VPS;
6. o Bruce experimenta no portal verdadeiro, onde só os membros o veem, e aprova.

---

## 11. Mapa do código original (`/Users/brucesilva/purple-house-crm`)

| Original | Destino no portal |
|---|---|
| `src/Dominio/Fases.php`, `Texto.php` | `backend/crm/dominio/fases.py`, `texto.py`, `numeros.py` |
| `src/Dominio/Geo/{Portugal,Distancia,PrecisaoGps,Duplicados}.php` | `backend/crm/dominio/geo.py` (+ `filtro_candidatos` para o `$geoWithin`) |
| `src/Dominio/Lojas/{Janelas,CamposLoja,ValidadorLoja}.php` | `backend/crm/dominio/{janelas,campos_loja,validador_loja}.py` |
| `src/Dominio/Regioes/RegrasRegioes.php`, `Definicoes.php` | `backend/crm/dominio/{regioes,definicoes}.py` |
| `src/Dominio/Utilizadores/RegrasUtilizadores.php` | `backend/crm/dominio/membros.py` (perfis do CRM, sem "último admin") |
| `src/Dominio/Relogio/*` | `backend/crm/relogio.py` |
| `src/Dominio/Auth/*`, `src/Http/{Sessao,Csrf,CookieDispositivo,Autenticacao}*.php` | Não se portam: `faturacao.auth` + `crm/auth.py` |
| `src/Http/Controladores/*Controlador.php`, `Formatar.php`, `ErroApi.php`, `Pedido.php` | `backend/crm/{membros,regioes,lojas,definicoes,morada}.py`, `formatar.py`, `erros.py`, `pedidos.py` |
| `src/Http/ConfigMapa.php` | `backend/crm/config_mapa.py` (`GET /config` em vez de `/api/sessao`) |
| `src/Servicos/Geoapify.php`, `ClienteHttpCurl.php`, `FalhaServicoExterno.php` | `backend/crm/servicos/geoapify.py` (URLs e normalização; no fim, o cliente httpx `obter_json`, `ler_json` e `FalhaServicoExterno`, T2.15) |
| `src/Repositorios/*` | Acesso Motor dentro de cada módulo de rotas (`bd.obter_db()`) |
| `src/Cli/{SeedDemo,DadosDemo}.php`, `bin/seed-demo.php` | `backend/seed_crm_local.py` |
| `migrations/*.sql` | `crm/db.py::INDICES` + `arrancar()` |
| `public/assets/js/*.js` | `frontend/src/lib/crm/*.js` (módulos puros) |
| `public/assets/js/componentes/*`, `ecras/*` | `frontend/src/components/crm/*`, `frontend/src/pages/crm/*` |
| `tests/Unit/Dominio/*Test.php` | `backend/tests/crm/test_dominio_*.py` (mesmos cenários, `parametrize` com os nomes pt-PT) |
| `tests/Integration/Api/*Test.php` | `backend/tests/crm/test_{membros,regioes,lojas_*,definicoes,config_mapa,morada}.py` com `TestClient` e `BaseFalsa` |
| `tests/Unit/FasesConsistenciaTest.php` | `backend/tests/crm/test_consistencia_frontend.py` |
| `tests/js/*.test.js` (+ `apoio/leaflet-falso.js`, `apoio/dom-falso.js`) | `frontend/src/lib/crm/*.test.js` (+ `testes/leafletFalso.js`, `testes/domFalso.js`) |
| `tests/fixtures/geoapify/*.json` | `backend/tests/crm/fixtures/geoapify/*.json` |
| `docs/superpowers/plans/2026-10-02-etapa-1-base.md` (§3, §4, §9) | Pormenores da etapa 1 já resolvidos (consultar em caso de dúvida) |
| `CLAUDE.md` do autónomo | Regras herdadas (§0 regra 10 deste dossiê) |

**Não se porta:** publicação (GitHub Actions, `deploy-gate`, `.htaccess`), PWA da app inteira, login de 30 dias,
CSRF, MariaDB, cópias `mysqldump` e o email semanal.

---

## 12. Ambiente local (F0, T0.1–T0.8)

Tudo é local: MongoDB em `127.0.0.1`, backend em `127.0.0.1:8001`, frontend em `127.0.0.1:3000`. Nada liga ao
Atlas nem ao VPS. **A porta 8080 é a pré-visualização do CRM autónomo do dono: não se toca.**

### 12.1 Versões registadas (2026-10-10)

| Ferramenta | Versão / estado |
|---|---|
| macOS | arm64, Homebrew 7.0.7 em `/opt/homebrew` |
| Python do backend | 3.11.17 (`brew install python@3.11`), venv em `backend/.venv` (ignorado); `/usr/bin/python3` do sistema é 3.9 e não serve |
| Pacotes do backend | `fastapi 0.110.1`, `pydantic 2.12.5`, `httpx 0.28.1`, `motor 3.3.1`, `pymongo 4.5.0`, `pytest 8.4.2` (de `backend/requirements.txt`) |
| Node | 24.17.0 local (o Docker usa 20); `corepack 0.35.0`; **yarn 1.22.22** por `corepack yarn …`, sem `corepack enable` |
| Frontend | `node_modules` reinstalado com `yarn install --frozen-lockfile`, sem `--ignore-engines`; `yarn.lock`, `package.json` e `package-lock.json` intactos; `@craco/craco 7.1.0`, `react-scripts 5.0.1`. Na T2.19, `yarn add leaflet@1.9.4 --exact` (também sem `--ignore-engines`) mexeu só no `package.json` e no `yarn.lock`; o `package-lock.json` continua intacto (desatualizado, não se toca) |
| MongoDB | `mongodb-community@8.0` 8.0.32 (tap `mongodb/brew`), serviço `brew services`, `bindIp: 127.0.0.1, ::1`, porta 27017; sem `mongosh` |

**Notas de instalação:**
- O `brew install` do MongoDB recusou-se duas vezes ("untrusted tap"); a 3.ª tentativa instalou (`brew-mongo-tentativa{1,2}.log` e `brew-mongo.log`). Ver §12.8.
- O `brew` avisa que há Command Line Tools mais recentes; é inofensivo.
- O `node_modules` antigo, instalado pelo npm e sem o `jsqr`, foi guardado em `~/.cache/lisbonb-crm-local/node_modules-npm-antigo`.

### 12.2 Instalar de raiz (só se o ambiente se perder)

```bash
export PATH="/opt/homebrew/bin:$PATH"
RAIZ="/Users/brucesilva/pasta sem título/RH"; LOGS="$HOME/.cache/lisbonb-crm-local"
mkdir -p "$LOGS" "$HOME/.config/lisbonb-crm-local"
test ! -e "$RAIZ/backend/.env" || echo "PARAR: existe backend/.env (traria variáveis de produção)"
# Python 3.11 + venv (instalações em segundo plano, com registo)
brew install python@3.11 > "$LOGS/brew-python.log" 2>&1
/opt/homebrew/opt/python@3.11/bin/python3.11 -m venv "$RAIZ/backend/.venv"
"$RAIZ/backend/.venv/bin/python" -m pip install -r "$RAIZ/backend/requirements.txt" > "$LOGS/pip.log" 2>&1
# Frontend (se o yarn.lock não bater com o package.json: parar, nunca regenerar o lockfile)
cd "$RAIZ/frontend" && COREPACK_ENABLE_DOWNLOAD_PROMPT=0 corepack yarn install --frozen-lockfile > "$LOGS/yarn-install.log" 2>&1
# MongoDB local
brew tap mongodb/brew
brew install mongodb/brew/mongodb-community@8.0 > "$LOGS/brew-mongo.log" 2>&1
brew services start mongodb/brew/mongodb-community@8.0
grep -n bindIp /opt/homebrew/etc/mongod.conf      # 127.0.0.1 (e ::1)
"$RAIZ/backend/.venv/bin/python" -c "from pymongo import MongoClient; print(MongoClient('mongodb://127.0.0.1:27017', serverSelectionTimeoutMS=3000).admin.command('ping'))"
```

### 12.3 Ficheiros de ambiente locais (nunca versionados, modo 600)

`backend/.env.local` é criado **sem mostrar valores** e só se ainda não existir:

```bash
cd "/Users/brucesilva/pasta sem título/RH/backend" && umask 077 && test ! -e .env.local && {
  printf 'MONGO_URL=mongodb://127.0.0.1:27017\nDB_NAME=lisbonb_crm_local\n'
  printf 'JWT_SECRET=%s\n' "$(.venv/bin/python -c 'import secrets;print(secrets.token_urlsafe(48))')"
  printf 'ADMIN_EMAIL=admin.local@example.com\n'
  printf 'ADMIN_PASSWORD=%s\n' "$(.venv/bin/python -c 'import secrets,string;a=string.ascii_letters+string.digits;print("".join(secrets.choice(a) for _ in range(16)))')"
  printf 'CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000\nFRONTEND_URL=http://localhost:3000\n'
  printf 'CRM_GEOAPIFY_CHAVE_SERVIDOR=\nCRM_GEOAPIFY_CHAVE_MOSAICOS=\n'
} > .env.local
```

| Ficheiro | Nomes (valores sempre `<…>`) |
|---|---|
| `backend/.env.local` | `MONGO_URL=<…>` (local), `DB_NAME=<…>` (acaba em `_local`), `JWT_SECRET=<…>` (64 car.), `ADMIN_EMAIL=<…>`, `ADMIN_PASSWORD=<…>` (16 car.), `CORS_ORIGINS=<…>`, `FRONTEND_URL=<…>`, `CRM_GEOAPIFY_CHAVE_SERVIDOR=` (vazia), `CRM_GEOAPIFY_CHAVE_MOSAICOS=` (vazia) |
| `frontend/.env.development.local` | `REACT_APP_BACKEND_URL=<…>` (`http://127.0.0.1:8001`), `BROWSER=none`, `PORT=3000`, `HOST=127.0.0.1` |

- **Porquê `@example.com`:** o `EmailStr` do login recusa domínios reservados como `.test` e `.local`.
- **Porquê `HOST=127.0.0.1`:** o dev server do CRA escuta em `0.0.0.0` por omissão e o plugin visual-edits do craco expõe `POST /edit-file` (em local responde 401).
- O `server.py` só carrega `backend/.env`, que **não existe** em local; o único ficheiro de configuração é `--env-file .env.local`.
- **Porquê `.env.development.local` e não `.env.local`** (revisão da F0/F1, F3): o CRA lê o `.env.local` no `start` e também no `build` (produção), por cima do `.env.production` versionado. Um `yarn build` fora do Docker nesta cópia, como o `frontend/scripts/build-app-release.sh`, saía com `http://127.0.0.1:8001`.
  - O `.env.development.local` só é lido pelo `start`. O `build` fica com o `.env.production` e o Jest (`NODE_ENV=test`) não lê nenhum dos dois.
  - O Docker não é afetado: o `frontend/.dockerignore` exclui `.env.*`.
  - Verificado com `react-scripts/config/env.js` em cada `NODE_ENV` (`rev-f3-verde.log`).
  - Numa cópia antiga do ambiente: `mv frontend/.env.local frontend/.env.development.local`.
- **Verificar só nomes:**
  - `git -C "/Users/brucesilva/pasta sem título/RH" check-ignore backend/.env.local frontend/.env.development.local` mostra os dois (`.gitignore:87 .env.*` e `frontend/.gitignore:17 .env.development.local`);
  - `grep -c "mongodb+srv" backend/.env.local` dá `0`;
  - `sed -E 's/=.*/=<…>/' backend/.env.local` lista os nomes.

### 12.4 Seed local e guarda (T0.7)

```bash
cd "/Users/brucesilva/pasta sem título/RH/backend" && .venv/bin/python seed_crm_local.py --env-file .env.local          # idempotente
cd "/Users/brucesilva/pasta sem título/RH/backend" && .venv/bin/python seed_crm_local.py --env-file .env.local --repor  # novas palavras-passe
```

- **Guarda (antes de criar qualquer cliente Mongo):**
  - `uri_e_local` recusa tudo o que não comece por `mongodb://` antes de interpretar o URI (um `mongodb+srv://<…>` nunca chega a fazer DNS);
  - depois usa `pymongo.uri_parser.parse_uri` dentro de `try` e exige **uma só máquina**, em `127.0.0.1`, `localhost` ou `::1` (mais de uma, mesmo todas locais, recusa-se: revisão da F2);
  - o cliente é `MongoClient(uri, **OPCOES_CLIENTE)`, com `directConnection=True` (revisão da F2): sem isso, o PyMongo 4 descobre o conjunto de réplicas a partir do nó local e manda as escritas (e o `--repor`) para o primário que ele anunciar, mesmo noutra máquina. As opções do cliente ganham às do URI (`?directConnection=false` e `?replicaSet=…` não as desfazem; provado com `topology_type_name == "Single"`), como no ensaio da T2.17;
  - `bd_e_local` exige um nome terminado em `_local`.
  - Se falhar: "Recusado: o seed só corre num MongoDB local (mongodb://127.0.0.1) e numa base *_local." e `saida=1`. Um ficheiro de ambiente em falta também dá "Recusado…", e o MongoDB parado dá uma mensagem própria.
- **Cria (T0.7):** as 4 contas de demonstração em `users` (bcrypt, `must_change_password: False`) e 3 linhas em `crm_membros` (`criado_por: "seed-local"`). As contas que já existem ficam como estão.
- **Cria (T2.18):** as 4 regiões e as 24 lojas do `src/Cli/DadosDemo.php` do autónomo, com "(demo)" no nome.
  - **Regiões:** Lisboa, Porto, Setúbal e Algarve, ordem 1–4, com a forma do `POST /regioes`: `{id: str(uuid4()), nome, nome_chave, ordem}`.
  - **Lojas:** as 5 fases (7 potencial, 6 cliente, 5 contactada, 4 amostra, 2 perdida), 2 sem região (Coimbra e Évora), todas a mais de 200 m umas das outras (o par mais perto, em Faro, está a 447 m), 11 com telefone `+351 000 000 0NN` (em Portugal nenhum número começa por 0: quem o marcar não liga a ninguém), 2 com GPS (12 m e 25 m) e, desde 2026-10-13, 2 com Instagram de demonstração (perfis com `demo` no nome: `mercearia.da.baixa.demo`, `gelataria.da.se.demo`) e 1 com site num domínio `example.com` (reservado pela RFC 2606): nada disto aponta para ninguém. Os valores vão já na forma normalizada (como os telefones).
  - Cada loja passa pelo `validador_loja.criacao` e é construída pelo `formatar.documento_loja(dados, "seed-local", agora)`, a forma que o `POST /lojas` grava. Depois, `fase_desde` = `criado_em` = agora menos os dias na fase de cada uma (1 a 200 dias, contados em UTC), para os alertas da F5 terem fases de idades diferentes (correções do plano, linha "T2.18"); `atualizado_em` é o carimbo de agora.
  - Mensagens (as do autónomo): "Criadas: 4 regiões e 24 lojas de demonstração." e, com `--repor`, antes disso "Apagadas: N lojas e M regiões.".
- **Recusa:** se a base já tiver lojas ou regiões (que podem ser verdadeiras: o seed não as distingue), sai com "Recusado: a base de dados já tem N lojas e M regiões. Use --repor para apagar todas as lojas e regiões e criar os dados de demonstração de novo." e `saida=1`, **antes de qualquer escrita, também das contas**. Por isso, depois do primeiro seed, correr outra vez sem `--repor` recusa sem mudar nada.
- **Credenciais:** as palavras-passe geradas vão para `~/.config/lisbonb-crm-local/credenciais.txt` (modo 600, pasta 700), uma linha `email<TAB>palavra-passe` por conta, logo a seguir às contas (uma falha nas lojas não as perde). O ecrã só mostra o caminho e uma contagem. **Não se mostra o conteúdo.**
- **`--repor`:** gera palavras-passe novas para as 4 contas e acerta `password_mudada_em`, o que termina as sessões abertas antes; e apaga **todas** as lojas, interações e regiões do CRM (só essas três coleções, e só na base `*_local` que a guarda aceita) para as criar de novo, com ids novos. Membros, definições, contas e as outras coleções do portal não se tocam.
- **Sem transações (o MongoDB local não as tem):** tudo é construído e validado antes da primeira escrita. Ordem das escritas: com `--repor`, apagar lojas, interações e regiões; depois gravar as regiões e as lojas (`insert_many`). Se uma escrita falhar, as coleções que o seed mexeu voltam à cópia do que tinham e sai com "Erro: os dados de demonstração não foram criados (nada mudou): <tipo>: <mensagem>"; se nem a reposição der, diz que a base pode ter ficado a meio e manda correr de novo com `--repor`.
- **Diferenças para o autónomo:** `criado_por` é `"seed-local"` (o autónomo deixava null; aqui é a marca das escritas do seed, como nos membros); o seed também cria as contas (o autónomo não criava utilizadores); as opções são as do `argparse` da T0.7 (`-h`/`--help`), por isso não há `--ajuda` nem a mensagem "use só uma opção de cada vez".
- **Contagens esperadas:** `users` = 5 (4 de demonstração + o admin master criado no primeiro arranque do backend), `crm_membros` = 3, `crm_regioes` = 4, `crm_lojas` = 24 e `crm_interacoes` = 0. O `GET /api/crm/lojas` com o admin local devolve 24.
- **Conferido com o PHP 8.4.26 (T2.18, `t2.18-conferencia-php.log`, não versionado):** as 24 lojas do `DadosDemo::lojas()` (campos, tipos e ordem das chaves) e os inícios de fase do `modify("-N days")`, com o relógio de 2026-10-10 e mais 4 instantes (mudança da hora, 29 de fevereiro, passagem de ano): 0 diferenças.
- **Verificado na base local (T2.18, `t2.18-ponta-a-ponta.log`):** o seed criou as 4 regiões e as 24 lojas na `lisbonb_crm_local`, que **ficam lá** para as verificações no browser (T2.25–T2.32); a segunda corrida sem `--repor` recusou sem escrever nada; com o backend local, `GET /api/crm/lojas` devolve 24 ao admin local e ao `escritorio.demo`, e um `POST /lojas` a 11 m da Mercearia da Baixa dá 409 `duplicado`.

### 12.5 Contas locais

| Conta | Papel no portal | CRM | Onde aterra | Palavra-passe |
|---|---|---|---|---|
| `admin.local@example.com` (admin master) | `admin` | `admin` (implícito) | `/admin` | `ADMIN_PASSWORD` do `backend/.env.local`, **reposta a cada arranque** ("Master admin password atualizada: …"); desde a revisão dos ecrãs da F2 também em `credenciais.txt` (a mesma, copiada sem a mostrar, com o `escrever_credenciais` do seed; se o `ADMIN_PASSWORD` mudar, a linha tem de ser copiada outra vez) |
| `gestor.demo@example.com` | `gerente` | — | `/admin` | `credenciais.txt` |
| `escritorio.demo@example.com` | `gerente` | `utilizador` | `/admin` | `credenciais.txt` |
| `colaborador.demo@example.com` | `colaborador` | `utilizador` | `/colaborador` | `credenciais.txt` |
| `motorista.demo@example.com` | `colaborador` | `motorista` | `/colaborador` | `credenciais.txt` |

As contas de demonstração **não têm ficha de colaborador** (`employee_id: None`). Por isso, em `/colaborador`,
`GET /api/me/profile` dá 400 "Utilizador não associado a colaborador" e o painel aparece vazio. É esperado.

### 12.6 Arrancar e parar

```bash
# Antes: as portas têm de estar livres
lsof -nP -tiTCP:8001 -sTCP:LISTEN; lsof -nP -tiTCP:3000 -sTCP:LISTEN
# Backend (SEGUNDO PLANO)
cd "/Users/brucesilva/pasta sem título/RH/backend" && .venv/bin/uvicorn server:app --host 127.0.0.1 --port 8001 --env-file .env.local > "$HOME/.cache/lisbonb-crm-local/backend.log" 2>&1
# Frontend (SEGUNDO PLANO; HOST/PORT/BROWSER vêm do frontend/.env.development.local)
cd "/Users/brucesilva/pasta sem título/RH/frontend" && BROWSER=none PORT=3000 ./node_modules/.bin/craco start > "$HOME/.cache/lisbonb-crm-local/frontend.log" 2>&1
# Verificar (esperas limitadas)
curl -s --max-time 3 http://127.0.0.1:8001/api/health          # {"status":"healthy",…}
curl -s --max-time 3 http://127.0.0.1:8001/api/crm/saude       # a partir da T1.9
curl -s -o /dev/null -w '%{http_code}\n' --max-time 5 http://127.0.0.1:3000/login   # 200 (compila em ~8 s)
# Parar: TERM aos processos que escutam nas portas + o pai "node ./node_modules/.bin/craco start"
kill -TERM $(lsof -nP -tiTCP:8001 -sTCP:LISTEN) $(lsof -nP -tiTCP:3000 -sTCP:LISTEN)
```

- **Fim da F2 (T2.32):** a pré-visualização local ficou a correr para o dono ver a F2: backend em `127.0.0.1:8001` (com o `.env.local` e a base `lisbonb_crm_local`, registo `t2.32-backend.log`) e frontend em `127.0.0.1:3000` (`craco start`, registo `t2.32-frontend.log`), os dois em segundo plano e só em `127.0.0.1`. Entra-se em `http://127.0.0.1:3000/login` com as contas do §12.5. Para parar: o `kill -TERM` acima (as duas portas) e o pai `node … craco start` (`pkill -TERM -f 'craco start'`). Uma tarefa que precise das portas livres para-os primeiro.
- **Alterações do dono (2026-10-13, A4):** o backend foi reiniciado com o mesmo comando (o `uvicorn` não tem `--reload`, por isso não via o código novo da ficha), desligado da sessão (`nohup … &`), com registo em `a4-backend.log` e o pid em `a4-backend.pid`; o frontend `craco start` da T2.32 ficou o mesmo (recompila sozinho; registo `t2.32-frontend.log`). O seed voltou a correr com `--repor` (`a4-seed-repor.log`): regiões, lojas e interações de demonstração criadas de novo, já com Instagram e site, e **palavras-passe novas** para as 4 contas de demonstração em `credenciais.txt` (as sessões abertas antes terminaram; a do admin local continua a ser a do `.env.local`). O `a4_verificar.py` (lê as credenciais do `.env.local` sem as imprimir; só fala com `127.0.0.1:8001`) confirmou: login do admin 200, `GET /lojas` com 24 lojas (7/5/4/6/2 por fase) e os campos `instagram`/`site` na ficha das 2 lojas do seed que os têm e a `null` numa que não os tem (`a4-verificacao.log`).
- **`preview_start`** lê o `.claude/launch.json` da pasta de trabalho principal da sessão. Nas sessões do dono é `/Users/brucesilva/cleide/.claude/launch.json`, **fora do repositório**, com as entradas `portal-backend-local` e `portal-frontend-local`. Cada uma é `/bin/bash -c "cd '<caminho absoluto>' && exec …"`, testadas a arrancar e a parar com `preview_stop`. Noutra pasta de trabalho, usar os comandos acima em segundo plano.
- No primeiro arranque, o registo do backend mostra "Master admin created: …". O arranque só cria o admin master, inicia a Faturação (`faturacao.arrancar()`) e cria índices na base local.
  - A partir da T1.9 também chama `crm.arrancar()`, que cria os índices `crm_*` com um limite de 10 s. Uma falha fica no registo com `[crm]` e não impede o portal de subir.
- Sem `RESEND_API_KEY` nem `GOOGLE_PLACES_API_KEY`: não saem emails nem pedidos à Google.
- Sem `ESTOQUE_SERVICE_KEY`: em `/admin/estoque/*`, os pedidos a `/api/estoque/*` dão 503 (erro na consola do browser). O backend recusa antes de qualquer pedido ao serviço de Estoque. É esperado e não é do CRM.
- Pedidos externos do browser em local: só GET a `cdn.jsdelivr.net` (xlsx e jszip do `index.html`), `fonts.googleapis.com` e `fonts.gstatic.com`.
- Avisos `react-hooks/exhaustive-deps` do ESLint no `frontend.log` são anteriores ao CRM.
- O login no browser foi verificado com Playwright sem janela (`/usr/bin/python3`, Playwright 1.60, Chromium em cache). O script `~/.cache/lisbonb-crm-local/t08_login.py` lê os valores dos ficheiros e nunca os imprime. Para as verificações da F1, alargar a sua lista `contas`.

### 12.7 Testes

```bash
export PATH="/opt/homebrew/bin:$PATH"     # obrigatório: 7 testes de tests/test_seguranca_login.py precisam do `mongod`
RAIZ="/Users/brucesilva/pasta sem título/RH"; LOGS="$HOME/.cache/lisbonb-crm-local"
cd "$RAIZ/backend" && .venv/bin/python -m pytest -q -p no:cacheprovider tests/crm                  # primeiro plano, < 90 s
cd "$RAIZ/backend" && .venv/bin/python -m pytest -q -p no:cacheprovider -rfEs > "$LOGS/pytest-tudo.log" 2>&1; echo "saida=$?" >> "$LOGS/pytest-tudo.log"   # SEGUNDO PLANO
cd "$RAIZ/frontend" && CI=true ./node_modules/.bin/craco test --watchAll=false src/lib/crm        # primeiro plano
cd "$RAIZ/frontend" && BUILD_PATH="$LOGS/build" CI=false ./node_modules/.bin/craco build > "$LOGS/build.log" 2>&1; echo "saida=$?" >> "$LOGS/build.log"   # SEGUNDO PLANO, fora de frontend/build
```

- `-p no:cacheprovider` evita `backend/.pytest_cache`, que não está no `.gitignore`.
- O fixture `mongo_real` de `tests/test_seguranca_login.py` arranca um `mongod` temporário próprio (127.0.0.1, porta aleatória) e não toca no serviço da porta 27017. Sem `/opt/homebrew/bin` no `PATH`, esses 7 testes saltam e o `skipped` sobe para 10.
- **Ensaio no MongoDB local (T2.17):** `cd "$RAIZ/backend" && CRM_MONGO_TESTE_URL=mongodb://127.0.0.1:27017 .venv/bin/python -m pytest -q -p no:cacheprovider tests/crm/test_mongo_local.py` (primeiro plano, cerca de 5 s; o serviço `brew` do MongoDB tem de estar a correr).
  - Sem a variável, os 27 testes do Mongo (23 da T2.17, 3 do seed das lojas, T2.18, e 1 da revisão da F2) saltam com a razão "ensaio no MongoDB local: só corre com CRM_MONGO_TESTE_URL=…"; os 17 sem Mongo (a guarda e as distâncias dos pontos) correm sempre. Por isso a bateria `tests/crm` e a suite completa têm **27 saltados a mais** sem a variável (com ela, voltam aos de antes). Com a variável: 44 passed.
  - A guarda falha sem ligar (e sem mostrar a URI) se a variável não for um `mongodb://` com uma só máquina local (`seed_crm_local.uri_e_local`) ou se trouxer outra base que não a `lisbonb_crm_teste`. Cada teste apaga só essa base, no início e no fim.
  - A variável é só da shell: nunca entra no `.env.example` nem no `.env.local` (`test_variaveis_ambiente.py` falha se entrar no `.env.example`).
- O build de verificação não depende do ambiente local: lê o `.env.production`, e o *bundle* fica a apontar para `https://rh.lisbonb.com`. Só serve para compilar, nunca se publica.

### 12.8 Registos e ficheiros locais

| Caminho | Conteúdo |
|---|---|
| `~/.cache/lisbonb-crm-local/*.log` | Instalações (`brew-*.log`, `pip.log`, `yarn-install.log`), suites (`pytest-tudo*.log`, `jest-partida.log`), servidores (`backend.log`, `frontend.log`), seed (`seed-t07*.log`, `t2.18-seed*.log`) |
| `~/.cache/lisbonb-crm-local/a1-*.log`, `a2-*.log`, `a3-*.log`, `a4-*.log`, `a4-backend.pid`, `a4_verificar.py` | Alterações do dono de 2026-10-13 (§13): o vermelho e o verde de cada uma (A1 rótulos das fases, A2 contacto no cartão, A3 Instagram e site) e o fecho A4 (`a4-fecho-backend.log`, `a4-fecho-jest.log`, `a4-fecho-build.log`, `a4-fecho-eslint.log`, `a4-seed-repor.log`, `a4-verificacao.log`; o servidor em `a4-backend.log`) |
| `~/.cache/lisbonb-crm-local/rev-dono-*.log`, `rev-dono-backend.pid`, `rev_dono_verificar.py` | Revisão das alterações do dono (A5, §13): o vermelho e o verde do backend e do Jest (`rev-dono-vermelho-*.log`, `rev-dono-verde-*.log`), o Jest completo e o build (`rev-dono-jest-tudo.log`, `rev-dono-build.log`), o servidor reiniciado (`rev-dono-backend.log`) e a verificação de ponta a ponta (`rev-dono-verificacao.log`) |
| `~/.cache/lisbonb-crm-local/estado-partida-T06.txt` | Estado de partida estruturado (§13) |
| `~/.cache/lisbonb-crm-local/arranque-T08.txt`, `t08_login.py`, `t08-*.png` | Registo do arranque, script de login e capturas |
| `~/.cache/lisbonb-crm-local/build/` | Build de verificação (a partir da F1) |
| `~/.cache/lisbonb-crm-local/t232-verificacao/` (`t232_base.py`, `t232_servidor.py`), `t232_aceitacao.py`, `t232/` (configuração do ESLint, cópias), `t2.32-*.log`, `t2.32-*.png`, `pytest-tudo-T2_32.log`, `build/` | T2.32 (fecho da F2): a lista de aceitação no browser sem login. O `t232_base.py preparar` copia as contas **sem a `password`**, os membros, as regiões, as lojas e as definições para a `lisbonb_crm_t232_local` e junta uma visita na "Quiosque de Tavira (demo)"; `contar` mostra as interações; `apagar` no fim. O `t232_servidor.py` (127.0.0.1:8011) é o da T2.29 sobre essa base (a conta pelo cabeçalho `X-Verificacao-Conta`). O `t232_aceitacao.py [secções]` corre no computador (1280×800, claro) e no telemóvel (375×812, toque, escuro); responde aqui aos mosaicos (um PNG liso, ou 404 para a troca para o OSM) e aborta e conta tudo o que sai de 127.0.0.1. Configuração do ESLint 8 do `react-scripts`: `eslint --no-eslintrc -c t232/eslintrc-base.json --resolve-plugins-relative-to node_modules/react-scripts --max-warnings 0 --report-unused-disable-directives <ficheiros>`, com `ESLINT_USE_FLAT_CONFIG=false` (o `t232/eslintrc.json` junta o `react-app/jest`, mais estrito) |
| `~/.cache/lisbonb-crm-local/t230-verificacao/` (verificação temporária das Regiões e da Fábrica, com o polyfill), `t2.30-mutar.py`, `t2.30-*.log`, `t2.32-build-a.log`/`t2.32-build-b.log` | T2.30 (fechada na T2.32): os componentes no jsdom (StrictMode, Radix e Leaflet verdadeiros, API e sonner falsos; copiar para `src/pages/crm/` e correr com `t112-jest.sh src/pages/crm/zz_t230`), as mutações (três voltas) e o build com e sem o aviso "Conflicting order" |
| `~/.cache/lisbonb-crm-local/t2.31-mutar.py`, `t231_servidor.py`, `t231_browser.py`, `t2.31-*.log`, `t2.31-texto.txt`, `t2.31-*.png`, `build-t231/`, `build-t231-limpo/` | T2.31: mutações da política (19 + 2 controlos), o texto da página desenhado, e o browser sem login. O `t231_servidor.py <pasta do build>` serve um build em 127.0.0.1:8012, com as rotas do SPA a cair no `index.html`. O `t231_browser.py` corre com o `/usr/bin/python3` **sem `-I`**, porque o Playwright está nos pacotes do utilizador. Aborta e conta todos os pedidos fora de 127.0.0.1:8012 (o backend do `.env.production`, CDN, tipos de letra), para nada sair do Mac. O `build-t231-limpo/` é o build de um `git archive HEAD frontend` mais os dois ficheiros da T2.31, sem o trabalho por guardar de outras tarefas |
| `~/.cache/lisbonb-crm-local/t229-verificacao/` (verificação temporária das Definições, `t229_servidor.py`, `t229_base.py`), `t229_browser.py`, `t229_campo.py`, `t2.29-mutar.py`, `t2.29-*.log`, `t2.29-*.png` | T2.29: as Definições no jsdom (StrictMode, Radix verdadeiro, API, sonner e `AuthContext` falsos), mutações e o browser sem login. O `t229_base.py preparar` copia as contas do portal **sem a `password`** (só id, nome, email e papel), os membros, as regiões, as lojas e as definições para a `lisbonb_crm_t229_local`, e junta uma conta "<b>x</b>" e um membro sem conta; `apagar` no fim. O `t229_servidor.py` (127.0.0.1:8011) troca a sessão pela conta do cabeçalho `X-Verificacao-Conta` (admin, gestor, escritorio, colaborador, motorista), para o `/eu` e os membros correrem de verdade para cada uma |
| `~/.cache/lisbonb-crm-local/t228-verificacao/` (verificação temporária da página, `t228_servidor.py`, `t228_base.py`), `t228_browser.py`, `t2.28-mutar.py`, `t2.28-*.log`, `t2.28-*.png` | T2.28: a ficha no jsdom (StrictMode, MemoryRouter, Leaflet verdadeiro, sonner falso), mutações e o browser sem login, com o servidor de verificação da T2.27 sobre a `lisbonb_crm_t228_local` (o `t228_base.py preparar` junta uma visita à "Quiosque de Tavira (demo)", para o 409 `loja_com_historico` verdadeiro, e escreve o id em `t228_historico.json`; `apagar` no fim). As duas abas do conflito são duas páginas do mesmo contexto do Playwright |
| `~/.cache/lisbonb-crm-local/t227-verificacao/` (verificação temporária da página e dos componentes, `t227_servidor.py`, `t227_base.py`), `t227_browser.py`, `t2.27-mutar.py`, `t2.27-*.log`, `t2.27-*.png` | T2.27: a Nova loja no jsdom (StrictMode, MemoryRouter, Leaflet verdadeiro), mutações e o browser sem login. **Servidor de verificação** (para pedidos que têm de correr de verdade, sem palavras-passe nem tokens): `t227_base.py preparar` copia regiões, lojas e definições da `lisbonb_crm_local` (só leitura) para a `lisbonb_crm_t227_local` e cria os índices do CRM; `cd backend && .venv/bin/python -m uvicorn t227_servidor:app --app-dir ~/.cache/lisbonb-crm-local/t227-verificacao --host 127.0.0.1 --port 8011` (segundo plano) serve o `crm.router` verdadeiro com o `dependency_overrides[utilizador_atual]` (o admin master); no Playwright, o `/api/auth/me` e o `/api/crm/eu` intercetam-se e o resto do `/api/crm/*` vai por `route.fetch(url=… 8011 …)` + `route.fulfill(response=…)`; no fim, `t227_base.py apagar` |
| `~/.cache/lisbonb-crm-local/t226-verificacao/` (verificação temporária dos componentes, o polyfill do SVG e a página `CrmLojaNova.harness.js`), `t226_browser.py`, `t226_dados.py`, `t2.26-mutar.py`, `t2.26-*.log`, `t2.26-*.png` | T2.26: o seletor da localização com o Leaflet verdadeiro no jsdom, mutações, e o browser sem login (o `/config` da base local e os 503 da morada sem chave, tirados das próprias funções das rotas), com o GPS simulado a 20 m e a 120 m |
| `~/.cache/lisbonb-crm-local/t225-verificacao/`, `t225_browser.py`, `t225_dados.py`, `t225_juntas*.py`, `t2.25-*.log`, `t2.25-*.png` | T2.25: verificação temporária dos componentes do mapa (Jest, Leaflet verdadeiro), browser sem login (pedidos ao backend intercetados com os dados do seed, lidos da base local), amostra das juntas entre mosaicos, mutações e capturas |
| `~/.cache/lisbonb-crm-local/rev-*.log`, `rev-f1-verificacao/`, `t07-*.log`, `t11-*.log` | Revisão da F0/F1: vermelho, verde e mutações de cada achado; verificação temporária dos componentes; prova do vermelho da T0.7 e da T1.1, reconstruída |
| `frontend/.env.development.local` | Ambiente do `craco start` local (§12.3; era `frontend/.env.local`) |
| `~/.config/lisbonb-crm-local/credenciais.txt` | Palavras-passe das contas de demonstração (modo 600; não mostrar) |
| `/Users/brucesilva/cleide/.claude/launch.json` | Entradas do `preview_start` |

**Tap do MongoDB:** nas duas primeiras tentativas, o Homebrew 7 recusou as fórmulas do tap `mongodb/brew` como
"untrusted tap" (o próprio erro sugere `brew trust mongodb/brew`); a terceira tentativa instalou. Numa máquina
nova, contar com este passo.

---

## 13. Estado de partida (T0.6)

Registado a 2026-10-10 no ramo `crm-purple-house` @ `2e0dbac`, antes de qualquer código do CRM.

| Suite | Comando | passed | failed | errors | skipped | Tempo | Saída |
|---|---|---|---|---|---|---|---|
| Backend completo | `pytest -q -p no:cacheprovider -rfEs` (com `/opt/homebrew/bin` no `PATH`) | **3552** | **0** | 0 | **3** | 110,35 s | 0 |
| Jest `src/lib` | `CI=true craco test --watchAll=false src/lib` | **114** (6/6 suites) | 0 | — | 0 | 0,85 s | 0 |

- **Falhas anteriores ao CRM:** nenhuma.
- **Os 3 saltados** estão todos em `tests/faturacao/test_o_contrato_com_a_app.py:130`. A "prova de fronteira" procura o repositório da app L'Açaí em `/Users/matheus.moraes/applacai/backend`, que só existe na máquina do Matheus, por isso salta sempre neste Mac.
- **Avisos (6):** `PendingDeprecation` do multipart (starlette), `BlockingPortal` do anyio, 4× `on_event` (`server.py:9716` e `server.py:9743`).
- Nenhum teste de ecrã saltou, o que confirma que o `node_modules` do yarn está completo.
- Suites Jest: finance, conciliacao, resumo, plataformas, faturacao, pos.impressao.

**Regra para T1.2, T1.9, T1.15 e T2.32:** `failed` = 0, `skipped` ≤ 3 (não pode aumentar) e `passed` = 3552 +
testes novos do CRM. O Jest tem de continuar com as 6 suites antigas verdes.

**Desde a T2.17:** sem `CRM_MONGO_TESTE_URL`, os testes do ensaio no MongoDB local (`tests/crm/test_mongo_local.py`)
saltam de propósito, todos com a razão "ensaio no MongoDB local: só corre com CRM_MONGO_TESTE_URL=…": 23 na T2.17,
26 desde a T2.18 (os 3 do seed das lojas), 27 desde a revisão da F2. A regra passa a ser `skipped` ≤ 3 + 27 sem a variável, confirmando com
`-rs` que os saltados a mais são todos do ensaio (com a variável, `skipped` ≤ 3).

| Momento | Commit | Backend (passed / failed / skipped) | Jest `src/lib` |
|---|---|---|---|
| Partida (T0.6) | `2e0dbac` | 3552 / 0 / 3 | 114 / 0 |
| Depois da T0.7 (+50 de `tests/crm/test_seed_local.py`) | `38f40c4` | 3602 / 0 / 3 | — |
| Fecho da F1 (T1.15) | `902b4e8` | 4071 / 0 / 3 (3552 + 519 de `tests/crm`) | 354 / 0 (9 suites: as 6 antigas com 114 + 240 do CRM) |
| Revisão da F0/F1 (+22: `test_cron_key.py` e um meta-teste do cron; Jest +35) | ver `git log` ("CRM: corrige revisão da F0/F1") | 4093 / 0 / 3 (3552 + 541 de `tests/crm`) | 389 / 0 (9 suites: 114 + 275 do CRM) |
| Depois da T2.17 (sem `CRM_MONGO_TESTE_URL`; `pytest-tudo-T2_17.log`) | ver `git log` ("CRM: ensaio do comportamento real do Mongo…") | 6380 / 0 / 26 (3 de sempre + 23 do ensaio) | — |
| Depois da T2.18 (sem `CRM_MONGO_TESTE_URL`; `pytest-tudo-T2_18.log`) | ver `git log` ("CRM: dados de demonstração das regiões e lojas…") | 6420 / 0 / 29 (3 de sempre + 26 do ensaio, confirmados com `-rs`) | — |
| Revisão do servidor da F2 (+24 e +1 do ensaio; sem `CRM_MONGO_TESTE_URL`; `pytest-tudo-revisao-F2.log`) | ver `git log` ("CRM: corrige revisão do servidor da F2") | 6444 / 0 / 30 (3 de sempre + 27 do ensaio, confirmados com `-rs`) | — |
| Fecho da F2 (T2.32; sem `CRM_MONGO_TESTE_URL`; `pytest-tudo-T2_32.log`) | ver `git log` ("CRM: fecho da base (F2) verificado em local") | 6477 / 0 / 30 (3552 + 2925 de `tests/crm`; 3 de sempre + 27 do ensaio, confirmados com `-rs`) | 1143 / 0 (35 suites: as 6 antigas com 114 + 1029 do CRM) |
| Revisão dos ecrãs da F2 (Jest +4: os botões de zoom em pt-PT e o erro das regiões na ficha; `revisao-f2-ecras-*.log`) | ver `git log` ("CRM: corrige revisão dos ecrãs da F2") | `tests/crm` 2925 / 0 / 27 (sem mudanças no backend) | 1149 / 0 (35 suites: 114 + 1035 do CRM; o commit da T2.32 já tinha +2 no `css.test.js` depois do registo acima) |
| Alterações do dono (2026-10-13; ramo `crm-publicacao-1`, commits `4c46044`, `d0c891a`, `5cdcc07`; `a4-fecho-*.log`) | `5cdcc07` | `tests/crm` 3060 / 0 / 27 (2925 + 135 da A3; o `test_dominio_navegacao.py`, não versionado e de outra tarefa, ignorado) | 1162 / 0 (35 suites: 114 + 1048 do CRM; +7 da A2 e +6 da A3) |
| Revisão das alterações do dono (2026-10-13; `rev-dono-*.log`) | ver `git log` ("CRM: corrige revisão das alterações do dono") | `tests/crm` 3077 / 0 / 27 (+17: a pessoa no resumo, o limite do site e o perfil do Instagram; o `test_dominio_navegacao.py` ignorado como na A4) | 1163 / 0 (35 suites: 114 + 1049 do CRM; +1 da A5, o teste que lê o `CAMPOS_RESUMO`) |

**Alterações do dono 2026-10-13** — três pedidos do Bruce depois de ver a F2 em local, no ramo `crm-publicacao-1` (criado de `d195610`), tudo só no Mac (sem `push`, `merge`, `deploy`, `ssh` nem Atlas; publicar no portal verdadeiro continua a ser o ponto 8 do §14):

- **A1 `4c46044`** — as fases "Contactada" e "Amostra" passam a chamar-se no ecrã **"A aguardar amostra"** e **"Amostra recebida"**: só o `rotulo` em `lib/crm/fases.js` mudou (chaves, cores e ordem iguais; §5.1 e §4.1 do desenho original).
- **A2 `d0c891a`** — o cartão da loja no mapa deixa de ter o botão Ligar e mostra **"Contacto: pessoa · telefone"** em texto (`contactoDaLoja` em `lib/crm/ecraMapa.js`; §7). O `hrefTelefone` fica em `dom.js`, sem uso.
- **A3 `5cdcc07`** — a ficha ganha **Instagram** e **site** (normalizados pelo servidor em `campos_loja.py`: `@nome`/perfil → `https://www.instagram.com/<nome>/`, site → `https://…`; 20 campos; os documentos antigos leem-se com `null`, sem migração; §3, §5.2, §6, §7). A Nova loja não os pede. O seed dá Instagram a 2 lojas e site a 1.
- **A4 (fecho)** — `pytest tests/crm`: 3060 passed, 0 failed, 27 skipped em 16,6 s (`a4-fecho-backend.log`). Jest completo: 35 suites e 1162 testes (`a4-fecho-jest.log`). Build de verificação: saída 0, avisos nos mesmos 16 ficheiros do portal da T2.32 e nenhum do CRM (`a4-fecho-build.log`). ESLint 8 com a configuração CRA da T2.32 nos 14 ficheiros JS alterados: limpo (`a4-fecho-eslint.log`; a variante com `jest` repete só os 2 avisos antigos do `css.test.js`). Backend reiniciado, seed `--repor` e verificação de ponta a ponta: §12.6. O `backend/tests/crm/test_dominio_navegacao.py` (não versionado; importa `crm.dominio.navegacao`, que não existe: um vermelho da F3 de outra tarefa) foi ignorado com `--ignore`; `HANDOFF/` não se tocou.
- **A5 (revisão das alterações do dono)** — dois revisores só de leitura apontaram quatro candidatos; três eram reais (dois deles o mesmo defeito) e corrigiram-se com o teste primeiro (`rev-dono-vermelho-*.log` → `rev-dono-verde-*.log`):
  - **A pessoa de contacto nunca aparecia no cartão do mapa** (R1 = A2-contacto-sem-pessoa, o mais grave): o cartão recebe a loja da lista do `GET /lojas` (`CrmMapa.js`: `lojas={visiveis}` → `escolherLoja` → `CartaoLoja loja={escolhida.loja}`), e o resumo não trazia a `pessoa_contacto`, por isso o `contactoDaLoja` só via o telefone — com o seed, a "Mercearia da Baixa (demo)" mostrava "Contacto: +351 000 000 001" sem a Ana. Os testes não o apanhavam porque o fixture do `ecraMapa.test.js` juntava a pessoa à mão. Correção: `pessoa_contacto` em `CAMPOS_RESUMO` e no `resumo_loja_api` (`formatar.py`; a `PROJECAO_RESUMO` segue), expectativas em `test_formatar.py` e `test_lojas_criar.py`, o fixture `TRES_LOJAS` com a forma real do resumo e um teste Jest que lê a linha `CAMPOS_RESUMO` do `formatar.py` e confere que a pessoa e o telefone lá estão (como o `formularioLoja.test.js` lê o `SITE_MAXIMO`); §6 e §5.2 acima.
  - **Perfil do Instagram a acabar em ponto ou com `..`** (R2): o Instagram não os permite, e um "@purplehouse." colado ao ponto final de uma frase ficava gravado como um endereço que não existe. `_INSTAGRAM_PERFIL` passou a `(?!.*\.\.)[A-Za-z0-9._]{0,29}[A-Za-z0-9_]`; +8 casos recusados e +3 aceites (`a.b_c`, `a.b.c`, `_`) em `test_dominio_campos_loja.py`.
  - **Site válido mas comprido dizia "não é válido"** (A3): o limite de 255 conta depois de juntar o `https://`, e o campo da ficha deixa escrever 255; a mensagem genérica não dizia o que corrigir. Agora é `_SITE_COMPRIDO` = "O site tem no máximo 255 caracteres." (`campos_loja.py`); casos novos em `test_dominio_campos_loja.py` e `test_dominio_validador_criacao.py`. A ficha não mudou: mostra a mensagem do servidor junto ao campo (`ficha.test.js` já o prova com o 422), por isso não precisou de teste novo; o `maxLength` fica em 255.
  - Nenhum candidato era falso. O desenho original (§6.1 já prometia "pessoa · telefone") e o desenho no portal não mudam. Verificação: `pytest tests/crm` 3077 / 0 / 27 (`rev-dono-verde-backend.log`), Jest completo 35 suites e 1163 testes (`rev-dono-jest-tudo.log`) e build de verificação com saída 0, avisos nos mesmos 16 ficheiros do portal e nenhum do CRM (`rev-dono-build.log`). O backend da pré-visualização foi reiniciado com o mesmo comando da A4 (sem `--reload`; registo `rev-dono-backend.log`, pid em `rev-dono-backend.pid`), sem repetir o seed, e o `rev_dono_verificar.py` confirmou de ponta a ponta o resumo com a pessoa e os dois 422 novos sem gravar nada (`rev-dono-verificacao.log`); o `craco start` da T2.32 recompilou sozinho.

**Fecho da F2 (T2.32, 2026-10-10)** — tudo verificado no Mac, nada saiu dele (nenhum `push`, `merge`, `deploy`, `ssh` nem Atlas; o ramo `crm-purple-house` não tem *upstream* nem ramo no `origin`):

- `pytest tests/crm`: 2925 passed e 27 skipped em 16 s; `grep -rn "asyncio.run(" backend/tests/crm` vazio. Ensaio no MongoDB local com `CRM_MONGO_TESTE_URL`: 44 passed (sem a variável: 17 passed e 27 skipped). Suite completa em segundo plano (128 s): 6477 passed, **0 failed, 30 skipped** (os 3 de sempre e os 27 do ensaio, todos com a razão do ensaio), os mesmos 6 avisos.
- Jest `src/lib`: 35 suites e 1143 testes (`t2.32-jest-lib.log`), as 6 suites antigas incluídas.
- Build de verificação (segundo plano, `t2.32-build.log`): saída 0, avisos só nos ficheiros do portal de sempre (os mesmos da T1.15), sem "Conflicting order" e sem "was not found in 'leaflet'". O Leaflet (JS) está só no *chunk* `216.*` (`grep -l leaflet-container build/static/js/*.js`), e o `leaflet.css` no `875.*.chunk.css`; o `main` não o tem. As Definições (membros e regiões) estão no `754.*` e a Fábrica no seu `243.*` (sem Leaflet; o seletor vem do `216.*`).
- **Lista de aceitação F2 no browser** (`t232_aceitacao.py`, registo `t2.32-aceitacao.log`; 135 verificações, todas OK, no computador e na vista de telemóvel 375×812 com o tema escuro), com as contas do seed (admin local, `escritorio.demo`, `colaborador.demo`, `gestor.demo`, `motorista.demo`) escolhidas pelo servidor da aceitação, sem palavras-passe nem tokens:

  | Ponto do §8 | Verificado |
  |---|---|
  | Regiões | criar (`{nome, ordem}` no fim), renomear, Subir (4 PATCH `{ordem}`, 0..n-1, a ordem do servidor igual à do ecrã), "SETUBAL"/"região t2.32"/renomear para "lisboa" → 409 junto ao campo, apagar Lisboa (com lojas) → 409 na linha; a ordem que não grava → toast, a lista do servidor e o foco no botão tocado |
  | Lojas | 422 em pt-PT junto ao Telefone; duplicado a 7,8 m → 409 com os 3 botões; 49,6 m → 409 e 50,4 m → 201 (o "exatamente 50 m não" está provado no pytest); GPS a 20 m confirma, a 120 m "Localização imprecisa — ajuste o pino" até mexer no pino; duas abas → 409 e a faixa; a fase num toque fica no histórico (`mudanca_fase` "contactada→amostra"); apagar com visita → 409 `loja_com_historico`, só com mudanças de fase → apagada |
  | Mapa | as cores das 5 fases (as do `fases.js`), os 24 nomes permanentes nos zooms 6 e 19, sem agrupamento; filtros de fase e região guardados depois de recarregar; cartão com Ligar (`tel:+351…`) e Ver ficha, 44 px, e o pino pelo teclado (o Ligar saiu em 2026-10-13: o cartão passou a mostrar "Contacto: pessoa · telefone" em texto); atribuição exata sem chave ("© OpenStreetMap contributors") e com a Geoapify ("Powered by Geoapify \| © OpenMapTiles © OpenStreetMap contributors"); com os mosaicos da Geoapify a falhar, troca sozinho para o OSM; `plus-lighter` nos mosaicos; o mapa enche a área (fundo = altura da janela); **botões de zoom com 44 px depois da correção** (eram 30×30, ver §7) |
  | Morada | o browser pede `GET /api/crm/morada/pesquisa` (nunca a Geoapify); sem chave, 503 e "Pesquisa de morada indisponível — coloque o pino no mapa ou use 'Estou nesta loja'" no ecrã; "Powered by Geoapify". A chave fora dos registos está provada no pytest (T2.15, chave canária) |
  | Ficha | fase num toque (`{fase, atualizado_em}`, "Fase guardada"), horário e dias fechada que ficam depois de recarregar, corrigir a localização (GPS a 20 m), conflito com "Recarregar" |
  | Definições | membros (o `gestor.demo` entra e sai do CRM: `/eu` e 403 no `/lojas`), regiões (acima) e fábrica (PATCH só da morada; o ponto com lat e lng juntas e até 6 casas, que passa a ser o `centro` do `/config`; fora de Portugal → 422); `/privacidade` com a secção 8 |
  | Perfis | `escritorio.demo` com o mapa e a Nova loja, Definições → mapa; `colaborador.demo` abre `/crm/lojas/nova`; `gestor.demo` e `motorista.demo` recambiados, 403 no `/lojas` |
  | Segurança | `seguranca.test.js` verde; uma região `<b>x</b>` fica texto; consola sem erros inesperados (só os 403/404/409/422/503 provocados e os pedidos abortados) |
  | Telemóvel | sem rolo horizontal na Nova loja, na ficha e nas Definições; botões e fases com 44 px; a fase num toque grava |

  - Nada saiu do Mac: os únicos pedidos para fora (`cdn.jsdelivr.net`, `fonts.googleapis.com`) foram abortados; os mosaicos responderam-se no próprio script.
  - Fica para o dono: as linhas entre mosaicos no próprio browser (§14, ponto 12; o script usa mosaicos lisos, que não as mostram) e a redação da política de privacidade (§14, ponto 7).
  - Não verificável no Playwright: no browser de um telemóvel verdadeiro, a barra do endereço pode tapar o fundo do mapa (`100vh`, nota da T2.25) e os campos `type="time"` mostram o relógio do sistema.

**Fecho da F1 (T1.15, 2026-10-10)** — tudo verificado no Mac, nada saiu dele:

- `pytest tests/crm`: 519 passed em 7,8 s; `grep -rn "asyncio.run(" backend/tests/crm` vazio. Suite completa em 120 s
  (`pytest-tudo-T1_15.log`): os mesmos 3 saltados e os mesmos 6 avisos da partida.
- Build de verificação: saída 0, avisos iguais aos da T1.14 (nenhum em ficheiros do CRM), `main.3cf22bba.js` com
  628,56 kB; as 4 páginas do CRM em *chunks* à parte (o `CrmLayout` fica no `main`, porque não é carregado à parte).
- **Lista de aceitação F1** (`t115_aceitacao_f1.py`, registo `t115-aceitacao.log`; 66 verificações, todas OK;
  só GET ao CRM, nenhuma escrita na base local):

  | Conta | API (backend 8001) | Browser (frontend 3000) |
  |---|---|---|
  | sem sessão | `/saude` 200; `/eu`, `/membros`, `/membros/candidatos` 403 "Not authenticated"; token inválido 401 | — |
  | admin local | `/eu` `{membro: true, perfil: admin, admin_master: true}`; `/membros` 200 (admin master 1.º com `id: null`, os 3 membros, sem `password`/`_id`); `/candidatos` = só o `gestor.demo` | "CRM" no fim da grelha; tocar abre `/admin/crm/mapa` "Brevemente"; o RH não acende; sem seletor de empresa e sem pedidos de empresas; Nova loja, Definições e Ficha; `/crm`, `/crm/lojas/nova`, `/crm/definicoes` no `CrmLayout` |
  | `escritorio.demo` | `/eu` utilizador; `/membros` 403 `sem_permissao` | Secção sem Definições; `/admin/crm/definicoes` → `/admin/crm/mapa`; `/crm/definicoes` → `/crm/mapa` |
  | `gestor.demo` | `/eu` `{membro: false}` (200, nunca 403); `/membros` 403 `sem_acesso_crm` | Grelha sem CRM; `/admin/crm/*` e `/crm/*` escritos à mão → `/admin`, nada do CRM |
  | `colaborador.demo` | `/eu` utilizador; `/membros` 403 `sem_permissao` | Item "CRM" (`/crm/mapa`) na barra; o `CrmLayout` com Mapa e Nova loja; `/admin` e `/admin/crm/mapa` → `/colaborador` |
  | `motorista.demo` | `/eu` motorista; `/membros` 403 `sem_permissao` | Barra de sempre, nada do CRM; `/crm/*` e `/admin/crm/mapa` → `/colaborador` |

  - A conta apagada → 401 fica provada pelos testes de ponta a ponta do portal (`test_conta_apagada_da_401_*` em
    `test_auth.py`, `test_eu.py` e `test_membros_ler.py`), para não criar nem apagar contas na base local.
  - App nativa: 29 casos `nativ` verdes em `acesso.test.js`, e as três entradas (`GuardaCrm`, `AdminLayout`,
    `EmployeeLayout`) passam `Capacitor.isNativePlatform()`.
  - As verificações da T1.12–T1.14 (`t112_browser.py`, `t113_browser.py`, `t114_browser.py`) voltaram a correr sobre
    o HEAD: 109 + 48 + 34 OK, sem falhas (registos `t115-regressao-t11*.log`).
  - Consola e registo do backend: só os 400 conhecidos de `/api/me/profile` (§12.5), os 503 de `/api/estoque/overview`
    (§12.6) e os 401/403 pedidos de propósito pela verificação da API.
  - Fica por corrigir, sem impedir o fecho da F1 (o estilo da barra é do Matheus): a 320 px a barra do colaborador
    membro do CRM passa a borda direita (medida e correção possível no §7, T1.14).

---

## 14. Pendentes do dono

Os agentes **não fazem nem simulam** estes pontos; registam aqui e continuam.

| # | Pendente [DONO] | Quando é preciso | Estado |
|---|---|---|---|
| 1 | Confirmar que o `ADMIN_EMAIL` de produção é a conta do Bruce (o admin master é sempre admin do CRM) | Antes de publicar a F1 | Por confirmar |
| 2 | Confirmar o plano de cópias do MongoDB Atlas. Se for o M0 gratuito (sem cópias automáticas): `mongodump` noturno com teste de reposição, combinado com o Matheus (protege o portal todo) | **Condição para a F2 em produção** | Por confirmar |
| 3 | Criar a conta Geoapify: uma chave de **desenvolvimento** (para regravar as respostas gravadas da T2.14, marcadas "manual — regravar") e as **duas chaves de produção**, servidor e mosaicos, com a dos mosaicos restrita a `https://lisbonb.com`. Os valores vão diretamente para o `.env` do servidor, nunca para o chat nem para o git | Antes de publicar a F2 (sem chaves, o CRM funciona com OSM e sem pesquisa de morada) | Por fazer |
| 4 | Decidir se acrescenta `https://rh.lisbonb.com` às origens da chave dos mosaicos ou se aceita os mosaicos OSM nesse domínio. O `rh.lisbonb.com` é sinónimo permanente no Caddyfile por causa das apps instaladas | Com o ponto 3 | Por decidir |
| 5 | Criar a conta openrouteservice (chave só no servidor; uma chave de **desenvolvimento** para o gravador, ponto 13). A chave nunca vai para o chat nem para o git. Para o backend usar a chave verdadeira em vez do simulador local (depois da T3.43 o `backend/.env.local` tem `CRM_ORS_URL=http://127.0.0.1:8013` e `CRM_ORS_CHAVE=simulador-local`): **substituir o valor** da linha `CRM_ORS_CHAVE` (não acrescentar outra linha) e **apagar** a linha `CRM_ORS_URL`; conferir com `grep -c "^CRM_ORS" backend/.env.local`, que deve dar **1**. No servidor, a chave vai para o `backend/.env` (só a linha `CRM_ORS_CHAVE`). Um 403 do ORS quer dizer quota diária esgotada ou chave inválida | Antes da F3 | Por fazer |
| 6 | Avisar o Matheus antes da primeira publicação e das alterações aos ficheiros partilhados (`server.py`, `App.js`, `AdminLayout.js`, `EmployeeLayout.js`, `PrivacyPolicy.js`, `.env.example`, `package.json`, `yarn.lock`) | Antes de publicar a F1 | Por fazer |
| 7 | Rever a redação da secção do CRM na política de privacidade (GPS só ao tocar; Geoapify e OpenStreetMap como prestadores do mapa e da pesquisa de morada). O texto está em `/privacidade` desde a T2.31 (§7, "Ficheiros partilhados"). Pontos a ver: (a) além do que o plano pedia, a secção diz que o CRM é usado no browser e não na app instalada, o que fazer se recusar a localização, e os dados guardados (lojas com telefone e pessoa de contacto, perfil de cada membro, quem registou cada loja e cada mudança de fase); (b) a data do topo diz 10 de outubro de 2026: ao publicar, pôr a data do dia; (c) aprovado o texto, tirar o comentário `{/* CRM (T2.31): redação a rever pelo dono … */}` e, se mudar alguma frase, o agente atualiza o `lib/crm/privacidade.test.js` | T2.31, antes de publicar a F2 | Por rever |
| 8 | Autorizar cada subida (push, junção ao `main`, `deploy.sh`) e aprovar cada fase no portal verdadeiro | Fim de cada fase | F1 (T1.15) e F2 (T2.32) verificadas em local (§13); a pré-visualização local ficou a correr no fim da T2.32 (§12.6); a subida espera pelos pontos 1, 2, 3, 6, 7 e 10 e pela autorização |
| 9 | Escolher os membros iniciais: só o Bruce na F1; quem registar lojas na F2; escritório na F3; o motorista na F4 | Ao publicar cada fase | — |
| 10 | Decidir se o repositório do portal (hoje **público**) passa a privado, depois de falar com o Matheus (desenho §9). O código do CRM ficaria público | Antes da primeira publicação do CRM | Por decidir |
| 11 | Confirmar no telemóvel da carrinha que o link de 9 paragens abre a app Google Maps; se não abrir, o bloco passa a 4. Confirmar também se o Waze respeita o `avoid_tolls=true` do link: o `avoid=tolls` do Google Maps está documentado (Maps URLs), mas o `avoid_tolls` não aparece na documentação oficial dos deep links do Waze (lá, "evitar portagens" é uma definição da app) e pode ser ignorado sem aviso (correção "T3.10" do plano F3). O link mantém-se fiel ao §8.2 (`crm/dominio/navegacao.py`, T3.10) e, com `evitar_portagens` ligado, o detalhe da paragem diz "No Waze, confirme 'Evitar portagens' nas definições da app" (T3.27). Se o Waze não o respeitar, fica só esse aviso | F4 | — |
| 12 | Ver no próprio browser (com o zoom do browser a 110 %/125 %, ou num ecrã com escala fracionária) se aparecem linhas claras entre os mosaicos do mapa. Na T2.25, no Chrome 154 sem janela, o `plus-lighter` (do Leaflet e do `crm.css`) deixava essas linhas quase brancas em metade das vistas; sem ele ficavam quase invisíveis (§7, "Mapa sem juntas"). Se as vir, a correção é trocar a regra por `mix-blend-mode: normal` (e o `css.test.js`). Na T2.32 a aceitação no browser usou mosaicos lisos (nada sai do Mac), por isso não as podia ver: abrir `http://127.0.0.1:3000/admin/crm/mapa` (§12.6) e olhar | Na aceitação da F2 (T2.32) | Por ver (pelo dono) |
| 13 | Regravar as respostas do openrouteservice com a chave de desenvolvimento (T3.12). Pôr a chave num ficheiro **próprio**, fora do git e só legível pelo dono: `backend/.env.ors` com a linha `CRM_ORS_CHAVE=…` e `chmod 600 backend/.env.ors` (o `.gitignore` já ignora `.env.*`; **nunca** o `.env.local`, que tem a chave do simulador e é recusado). Correr `cd backend && .venv/bin/python gravar_respostas_ors.py --env-file .env.ors` (4 pedidos ao ORS verdadeiro: `otimizacao-todas`, `otimizacao-uma-nao-cabe`, `direcoes-tres-paragens` e `direcoes-erro-2010`; o `erro-429.json` fica manual). O gravador vai sempre a `https://api.openrouteservice.org`, só mostra os nomes dos ficheiros gravados e, se alguma resposta não servir (pedido falhado, forma estranha, cenário diferente do esperado, a chave na resposta), não grava nada e diz porquê: nesse caso, passar a mensagem ao agente. Depois, `.venv/bin/python -m pytest tests/crm -q -p no:cacheprovider` tem de continuar verde e o `git diff --stat` só mostra esses 4 ficheiros em `tests/crm/fixtures/ors/`. Os testes das rotas usam respostas escritas no próprio teste para os valores exatos; as gravadas só provam o formato real | Depois do ponto 5, antes de publicar a F3 | Por fazer |
