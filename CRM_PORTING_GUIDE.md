# CRM Purple House · Dossiê de portagem para o portal Gestão Lisbonb

> **Para o Claude (ou outro programador) que vai construir o CRM dentro do portal:** este documento descreve
> o CRM da fábrica **Purple House** e o caminho para o reescrever como **módulo nativo do portal Gestão Lisbonb**
> (FastAPI + MongoDB + React, este repositório). O CRM autónomo (PHP + MariaDB) está congelado em
> `/Users/brucesilva/purple-house-crm` (etiqueta `referencia-standalone`, commit `0bda625`) como **referência de
> comportamento**: não se copia tal e qual; portam-se as regras e os cenários de teste. Molde deste dossiê:
> `/Users/brucesilva/pasta sem título/gestao-lisbonb-financeiro/PORTING_GUIDE.md`.

- **Data:** 2026-10-10 · **Ramo:** `crm-purple-house` (só local; nada foi enviado ao GitHub, ao VPS nem ao Atlas)
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
9. **DOM:** o React escapa por omissão. Nunca `dangerouslySetInnerHTML`, `.innerHTML =`, `outerHTML`, `insertAdjacentHTML` nem `document.write`. No Leaflet, `bindTooltip`, `bindPopup`, `setContent` e `setTooltipContent` só dentro de `lib/crm/mapa.js` e com nós DOM criados com `textContent`. `divIcon` nunca leva `html` e a atribuição vem só das constantes de `lib/crm/atribuicoes.js`. `href="tel:"` só com dígitos e `+`.
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
- **Texto:** `str.strip()` não tira U+FEFF; `\d` aceita algarismos árabes e `$` aceita `\n` final. Usar `aparar` com `[\s﻿]` e `\Z`, `[0-9]` e `re.fullmatch` em todas as regras.
  - **Surrogates sozinhos:** o `json.loads` aceita um `"\ud800"` sozinho, que o `json_decode` do PHP recusava ("Single unpaired UTF-16 surrogate", conferido no PHP 8.4.26), e o `corpo_json` ainda não o recusa. Esse texto rebenta com `UnicodeEncodeError` no `str.encode("utf-8")` e no BSON do Mongo, o que dá 500 numa escrita. Na T2.4, `campos_loja.notas` conta os bytes com `surrogatepass` para não rebentar. **Por fazer:** o `corpo_json` deve recusar estes textos com 400 `json_invalido`, como o PHP; o melhor momento é antes da T2.10, a primeira rota que grava textos livres.
- **Equivalências:** `mb_strlen` → `len`; `strlen` → `len(s.encode("utf-8"))`; `in_array(…, true)` → `isinstance(x, str) and x in ORDEM`; `sprintf('%.6F')` → `f"{x:.6f}"` depois de `arredondar` (com `-0.0` o PHP escreve `0.000000` e o Python `-0.000000`: só acontece fora de Portugal, mas ter em conta na T2.7); `rawurlencode` → `urllib.parse.quote(chave, safe="")`; `http_build_query(…, RFC3986)` → `urlencode(…, quote_via=quote)`.
- **Corrotinas nos testes:** **proibido `asyncio.run`** em `tests/crm`, porque deixa o ciclo de eventos a `None` e parte dezenas de testes antigos que usam `get_event_loop()`. Usar `correr(coro)` de `tests/crm/duplos.py` (um ciclo novo, sem `set_event_loop`). `grep -rn "asyncio.run(" backend/tests/crm` tem de dar vazio.
- **`tests/crm/conftest.py`:** faz `setdefault` de `POS_JWT_SECRET`, `JWT_SECRET`, `MONGO_URL` e `DB_NAME` com os valores de teste já usados no repositório, porque `tests/crm` é recolhida antes de `tests/faturacao`. Nos testes, importar os auxiliares de forma relativa (`from .duplos import BaseFalsa`).
- **Duplo do Mongo:** `BaseFalsa.__getattr__` levanta `AttributeError` para nomes começados por `_`, como o Motor.
- **FastAPI:** parâmetros de query do CRM declarados como `Optional[str] = None` e validados no domínio, senão sai o 422 do Pydantic (lista, em inglês). A dependência de perfil vem **antes** de `corpo_json`: um pedido sem sessão e com JSON inválido dá 403/401, nunca 400.
- **Jest (CRA 5):** `resetMocks: true` apaga as implementações dos `jest.fn` criados ao nível do módulo, por isso criá-los dentro de cada teste ou em `beforeEach`. Imports relativos (o Jest não conhece o alias `@/`). `import.meta` não funciona. `assert.equal` → `toBe`, `deepEqual` → `toEqual`, `throws` → `toThrow`, `mock.timers` → `jest.useFakeTimers()`. Para formas exatas usar `toEqual`, nunca `toMatchObject`: neste, `campos: {}` aceita qualquer valor, até `null` ou uma lista (T1.10).
- **Leaflet:** `import * as L from 'leaflet'` (o build ESM não tem export por omissão). `leaflet.css` importado depois do `index.css`. O mapa é destruído no cleanup do `useEffect`, porque o `StrictMode` monta duas vezes.
- **Ícones:** importar `Map as IconeMapa` do lucide; um `Map` importado tapa o `Map` do JavaScript.

---

## 3. Modelo de dados (MongoDB, coleções `crm_*`)

Regras gerais: `id` uuid4 em texto em todos os documentos; as respostas nunca expõem `_id` (projeção `{"_id": 0}`);
`regiao_id`, `criado_por`, `user_id` e `utilizador_id` são ids do portal em texto. Leituras de listas com
`to_list(5000)` (volume esperado: centenas). Ordenação por nome em Python com `dominio.texto.chave_comparacao`
(sem acentos nem maiúsculas).

**Tempo:**
- Todos os instantes `*_em` e `fase_desde` (exceto `atualizado_em`) têm **largura fixa** `AAAA-MM-DDTHH:MM:SSZ`, escritos só por `relogio.instante()`.
- `atualizado_em` tem **sempre 6 casas** (`2026-10-10T09:00:00.123456Z`) e é estritamente crescente (`relogio.proximo_carimbo`).
- Nunca `.isoformat()` no pacote `crm`, porque dá `+00:00` e parte a ordenação por texto e o `$max`.
- Datas e horas de Lisboa como texto (`AAAA-MM-DD`, `HH:MM`); "hoje" em `Europe/Lisbon`.

| Coleção (fase) | Documento | Índices (`crm/db.py::INDICES`) |
|---|---|---|
| `crm_membros` (F1) | `{id, user_id, perfil: admin\|utilizador\|motorista, criado_em, criado_por, atualizado_em?}` | `id` único; `user_id` único |
| `crm_regioes` (F2) | `{id, nome, nome_chave, ordem: int}` | `id` único; `nome_chave` único |
| `crm_lojas` (F2) | `{id, nome, fase, fase_desde, regiao_id\|null, morada, codigo_postal, localidade, lat, lng, loc: {type: "Point", coordinates: [lng, lat]}, origem_coords: pin_manual\|gps\|geocoder, precisao_m\|null, telefone, pessoa_contacto, notas, janelas: [{inicio, fim}], dias_fechada: [seg…dom], visita_pendente_motivo, visita_pendente_desde, ultima_interacao_em, ultima_visita_ou_entrega_em, criado_por, criado_em, atualizado_em}` | `id` único; `loc` `2dsphere`; `regiao_id` |
| `crm_interacoes` (F2: só `mudanca_fase`) | `{id, loja_id, tipo, resultado: "<antiga>→<nova>", notas: null, paragem_id: null, utilizador_id, ocorrida_em}` (sem `client_uuid` na F2) | `id` único; `(loja_id, ocorrida_em)`; `client_uuid` único **parcial** com `{"partialFilterExpression": {"client_uuid": {"$type": "string"}}}` |
| `crm_definicoes` (F2) | `{chave, valor (texto), atualizado_em, atualizado_por}`; só o que o admin alterou, padrões no código | `chave` único e **nenhum** índice em `id` |
| `crm_rotas` (F3) | `{id, data (única), estado, versao, …, paragens: [...]}` | a definir na F3 |
| `crm_produtos`, `crm_encomendas` (F5) | encomendas com as linhas dentro do documento | a definir na F5 |

- **`COLECOES` cresce por tarefa:** a T1.2 só tem `{"membros": "crm_membros"}` e cada tarefa da F2 acrescenta a sua coleção e os seus índices. `crm_definicoes` não tem `id`: um índice único em `id` faria o segundo upsert dar E11000 em produção. O teste dos índices verifica isto de forma explícita.
- `lat`/`lng` e `loc` escrevem-se sempre juntos (`formatar.documento_localizacao`). Na API as janelas são planas (`janela1_inicio`, `janela1_fim`, `janela2_inicio`, `janela2_fim`); na base ficam em lista (0 a 2, por ordem).
- **Contas do portal (`users`, já existe):** o CRM lê `id`, `email`, `name` e `role`. A projeção **nunca** pede `password`.
- **Sem transações:** a ordem das escritas é definida e testada. Exemplo: atualizar a loja e depois registar a `mudanca_fase`; se o registo falhar, fica uma linha `[crm]` no log e a loja não é desfeita. Corridas residuais aceites, como apagar uma região enquanto se cria uma loja nela.
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
- **Admin master:** a conta cujo email (lido da base) é igual a `ADMIN_EMAIL`. Por omissão é `geral@olacai.com`, em paridade com `server.py:61`. É sempre `admin` do CRM, não tem linha em `crm_membros` e não se pode adicionar como membro (409 `admin_master`), por isso não há regra do "último admin".
  - O email compara-se tal e qual, como no `server.py` (`user["email"] == MASTER_ADMIN_EMAIL`), e um email vazio nunca conta. O teste `test_auth.py` lê o `server.py` como texto e falha se o valor por omissão se separar de `crm.auth.ADMIN_EMAIL_POR_OMISSAO`.
  - Para o admin master, `crm_membros` nem se lê. Para os outros, uma linha com um perfil fora dos três, ou uma sessão sem `user_id` de texto, conta como não-membro (fechado por omissão). Lê-se a cada pedido: retirar um membro corta-lhe o acesso no pedido seguinte.
- **Tipo de conta:** os papéis de `PERFIS_GESTAO` (`admin`, `gerente`, `contabilista`) contam como `gestor` e `colaborador` como `colaborador`.
- **Só um admin do CRM** adiciona, muda ou retira membros, escolhendo de `GET /membros/candidatos` (contas que ainda não são membros nem são o admin master).
  - **Listas (T1.6, `crm/membros.py`):** das contas do portal pede-se só `{"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1}`, nunca a `password`. Ordem por nome sem acentos nem maiúsculas e, a seguir, pelo `id` (como o `ORDER BY nome, id` do autónomo). Em `/membros`, o admin master vem sempre primeiro (`id: null`; sem conta → `conta_existe: false`), uma linha antiga dele em `crm_membros` não o repete, os membros com a conta apagada vão para o fim (nome, email e tipo de conta a `null`) e um perfil desconhecido sai como `null`. Nos candidatos, qualquer linha de `crm_membros` exclui a conta (o índice único de `user_id` recusava outra).
  - **Escritas (T1.7, `crm/membros.py`):** a guarda `SO_ADMIN` vem antes de `corpo_json` (sem sessão e com JSON partido → 403, nunca 400). O `POST` valida os campos no domínio (422 sem ler a base), depois a conta (422 "A conta não existe."), o admin master (409 `admin_master`) e só então o "já é membro" (409 `ja_membro`). Esta última verificação faz-se antes de gravar, para valer mesmo se o arranque não criou o índice único, e também pelo `DuplicateKeyError` na corrida. Grava `{id (uuid4), user_id, perfil, criado_em, criado_por}` e responde com a forma de uma linha do `GET /membros`. O `PATCH` só muda o `perfil` (422 antes do 404; 409 `admin_master` numa linha antiga dele) e não grava `atualizado_em`, porque os membros não têm bloqueio otimista. O `DELETE` devolve `{retirado: true}`, e da segunda vez 404. Um admin pode despromover-se ou retirar-se, porque o admin master fica sempre admin.

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
- Cores exatas do pino:

  | Fase | Cor | Contorno |
  |---|---|---|
  | `potencial` | `#cfcfcf` | `#888` |
  | `contactada` | `#f4c20d` | — |
  | `amostra` | `#f08a24` | — |
  | `cliente` | `#6b2fa3` | — |
  | `perdida` | `#1a1a1a` | — |

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

- **Consistência:** `ORDEM` está numa só linha em `crm/dominio/fases.py` e em `lib/crm/fases.js`. `backend/tests/crm/test_consistencia_frontend.py` compara-as, junto com `LIMITE_PRECISAO_M = 50` e a mensagem do GPS.

### 5.2 Campos de uma loja
Os campos aceites, pela ordem dos erros, são: `nome, fase, regiao_id, morada, codigo_postal, localidade, lat, lng,
origem_coords, precisao_m, telefone, pessoa_contacto, notas, janela1_inicio, janela1_fim, janela2_inicio,
janela2_fim, dias_fechada`. Os campos que o servidor decide (`id`, `criado_por`, `fase_desde`, …) ignoram-se.

| Campo | Regra | Mensagem |
|---|---|---|
| `nome` | Obrigatório, aparado, até 150 caracteres | "Indique o nome." |
| `fase` | Obrigatória, um nome exato da `ORDEM` | "Indique a fase." / "A fase não é válida." |
| Pino (`lat`, `lng`, `origem_coords`) | Obrigatório; `origem_coords` é `pin_manual`, `gps` ou `geocoder`; coordenadas arredondadas a 6 casas | "Coloque o pino no mapa." / "Indique a origem das coordenadas." / "A origem das coordenadas não é válida." |
| `regiao_id` | Opcional: `None` ou uuid4 em texto; tem de existir | "A região não é válida." / "A região não existe." (verificado **antes** dos duplicados) |
| `morada` | Opcional, até 255 caracteres | — |
| `localidade`, `pessoa_contacto` | Opcionais, até 100 caracteres | — |
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
  - Conferido com o `CamposLoja` do PHP 8.4.26 em 116 106 entradas aleatórias, mais todas as entradas das tabelas dos testes: tudo igual.
- **Em `crm/dominio/validador_loja.py` (T2.5, porta do `ValidadorLoja::criacao`).**
  - Nomes: `CAMPOS` (tuplo, a ordem da tabela acima), `ORIGENS`, `NOME_MAXIMO = 150`, `TEXTOS` (`morada` 255, `localidade` e `pessoa_contacto` 100, com os rótulos das mensagens) e `criacao(corpo)` → `(dados, erros)`. Os auxiliares (`_validar`, `_campo`, `_localizacao`, `_coordenada`, `_ordenar`…) são internos; a T2.6 junta-lhes o `alteracao`.
  - Os dados têm sempre os 18 campos de `CAMPOS`, por essa ordem; os erros vêm também pela ordem de `CAMPOS`, incluindo os das janelas (o `Janelas::erros` dá o fim da janela 2 antes do "Preencha primeiro a janela 1."; o validador volta a ordenar). As chaves que não são de `CAMPOS` ignoram-se, também as parecidas (`"Nome"`, `" nome"`).
  - Com erro, os dados ficam como no PHP (e não se usam): o nome que não é texto fica `""`, o nome comprido fica aparado, a coordenada fora de Portugal fica arredondada; a fase, a região e a origem inválidas ficam `None`.
  - Coordenadas: `None` → "Coloque o pino no mapa."; o que não for `e_numero_json` (bool, texto, lista, objeto, nan, inf, inteiro que nem num float cabe) → "A latitude/longitude tem de ser um número."; depois `arredondar(valor, 6)` e só então `contem_*` (42,1999995 → 42,2 dentro; 42,2000005 → 42,200001 fora; o `round` do Python dava 42,199999).
  - Origem: só `pin_manual`, `gps` ou `geocoder` tal e qual (`" gps"`, `"GPS"`, `True`, `["gps"]` → "não é válida"; `None` e `""` → "Indique a origem das coordenadas."). A precisão só se lê com a origem exatamente `"gps"`: aceite (`geo.precisao_aceitavel`) guarda-se `int(arredondar(p))` (12,5 → 13, −0,0 → 0); senão "Localização imprecisa — ajuste o pino". Com outra origem, ou com uma origem inválida, `precisao_m` fica `None` e não dá erro, seja o que for que venha.
  - Janelas: só se comparam (`janelas.erros`) se nenhuma das quatro horas tiver erro; as horas que não são texto dão o erro do formato e nunca chegam ao `TypeError` do `janelas.erros`.
  - **Adaptação do portal:** `regiao_id` é `None` ou um uuid4 em texto, tal e qual (`re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")`, o `str(uuid.uuid4())`). O inteiro do autónomo (`1`), `0`, `True`, `"3"`, `""`, maiúsculas, espaços, uuid de outra versão ou variante, listas e objetos (incluindo operadores do Mongo como `{"$ne": None}`) dão "A região não é válida.". Por isso o `regiao_id` validado pode ir direto ao `find_one({"id": regiao_id})` da T2.10, e as regiões (T2.9) e o seed (T2.18) têm de gravar ids com `str(uuid.uuid4())`.
  - Conferido com o `ValidadorLoja::criacao` do PHP 8.4.26 em 80 298 lojas (as 309 entradas das tabelas dos testes, 40 000 aleatórias e 40 000 quase válidas; 20 074 sem erros), comparando os dados e os erros pela ordem e com os tipos: tudo igual. As únicas diferenças são as assumidas: o `regiao_id` inteiro ≥ 1 (3919 casos, só nessa chave) e os dias num objeto (T2.4). Ficaram de fora as entradas que o PHP não recebe (NaN, Infinity).

### 5.3 Portugal continental
- Aceita-se `36.8 ≤ lat ≤ 42.2` e `−9.6 ≤ lng ≤ −6.1`, com os limites incluídos. Recusa-se `36.799999`, `42.200001`, a Madeira, os Açores, Madrid, `0` e o sinal trocado.
- Em `crm/dominio/geo.py`: `contem_latitude`, `contem_longitude` e `MENSAGEM_PORTUGAL`. Quem chama valida o número e arredonda às 6 casas antes de perguntar (36.7999996 → 36.8 está dentro; 42.2000005 → 42.200001 está fora). O que não for número JSON (bool, texto, `None`, nan, inf) nunca está em Portugal, em vez de rebentar com `TypeError`.
- A mensagem é exatamente "Fora de Portugal". A pesquisa de morada filtra também `country_code` ≠ `pt` e pontos fora do continente.

### 5.4 GPS ("Estou nesta loja")
- Só se pede a posição **quando a pessoa toca** em "Estou nesta loja": na criação, na ficha e, na F4, no terreno. Opções: `{enableHighAccuracy: true, timeout: 15000, maximumAge: 0}`. **Nunca há seguimento contínuo** e guarda-se só o ponto da loja (Código do Trabalho, RGPD, CNPD).
- A precisão é aceitável se for **≤ 50 m depois de arredondar** meio-para-longe-do-zero: 50, 12, 0 e 50.4 passam; 51, **50.5**, 80, −1, `None`, `"10"`, `True`, inf e nan não. Aceite, a origem fica `gps` e `precisao_m` é inteiro; nas outras origens, `precisao_m` é `None`.
- Em `geo.py`: `precisao_aceitavel`, `LIMITE_PRECISAO_M = 50` e `MENSAGEM_GPS`. `False` também não passa (em Python seria um GPS de 0 m); `-0.0` passa, como no PHP. O valor guardado é `int(arredondar(precisao_m))`.
- Acima de 50 m aparece "Localização imprecisa — ajuste o pino", com o círculo da precisão. O Confirmar fica desativado até a pessoa arrastar o pino, e a origem passa a `pin_manual`.
- Regras do seletor (portadas de `seletor-localizacao.test.js`):
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
- **Apagar só sem lojas.** Com lojas: 409 `regiao_com_lojas` "Esta região tem lojas — mude-lhe o nome em vez de a apagar.". As lojas sem região aparecem como "Sem região" nos filtros.
- **Ecrã:**
  - "Adicionar" envia `{nome, ordem: proximaOrdem(lista)}`.
  - "Subir"/"Descer" troca com a vizinha, **renumera a lista toda 0..n−1** (`reordenarRegioes`) e envia só as que mudaram, um pedido de cada vez; se falhar, volta a pedir a lista.
  - O desempate no ecrã é ordem → nome (`Intl.Collator('pt', {sensitivity: 'base'})`) → id.

### 5.9 Definições (F2: a fábrica)
- Padrões no código: `fabrica_morada ''` (até 255 caracteres), `fabrica_lat '38.722300'`, `fabrica_lng '-9.139300'`. Guardam-se em texto, com as coordenadas a 6 casas (`'%.6f'`), e só o que o admin alterou (upsert por `chave`).
- `lat` e `lng` vão sempre juntas: "Indique também a longitude." / "Indique também a latitude.".
- Uma chave desconhecida dá "Esta definição não existe.". As chaves guardadas que a versão não conhece ignoram-se ao ler.
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
- **Rotas (F3):** o mesmo controlo, com `versao` inteiro.

### 5.11 Histórico e temporizadores
- **F2:** só `mudanca_fase`. Os 4 campos de temporizadores já existem no documento (a `null`).
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

### 5.13 "O que aconteceu no terreno ganha" (F4)
- As gravações do escritório **nunca apagam nem sobrepõem** um resultado registado pelo motorista. Se a paragem foi retirada entretanto, é reposta como `feita`; se a encomenda foi cancelada, fica entregue na mesma, com um aviso ao escritório.
- **Gancho obrigatório:** na F4, todo o efeito do terreno sobre `crm_lojas` avança `atualizado_em` com `proximo_carimbo`, para que uma escrita do escritório com versão velha dê 409. Nas rotas, o escritório atualiza paragens concretas condicionado à `versao` e nunca sobrepõe resultados do motorista.
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

| Rota | Perfis | Sucesso |
|---|---|---|
| `GET /saude` | Pública | `{estado: "ok", modulo: "crm"}` |
| `GET /eu` | Qualquer sessão | `{membro, perfil, admin_master}` (não-membro: `{false, null, false}`) |
| `GET /membros` | admin | `[{id\|null, user_id, nome, email, tipo_conta, perfil, admin_master, conta_existe, criado_em}]`, com o admin master primeiro |
| `GET /membros/candidatos` | admin | `[{id, nome, email, tipo_conta}]` (declarada antes de `/membros/{membro_id}`) |
| `POST /membros` | admin | `{user_id, perfil}` → 201 (422: "Escolha uma conta do portal.", "A conta não existe.", "Escolha um perfil: admin, utilizador ou motorista.") |
| `PATCH /membros/{membro_id}` | admin | `{perfil}` → 200 |
| `DELETE /membros/{membro_id}` | admin | `{retirado: true}` |
| `GET /regioes` | admin, utilizador | `[{id, nome, ordem}]` |
| `POST`, `PATCH`, `DELETE /regioes…` | admin | 201 `{id, nome, ordem}` / 200 / `{apagada: true}` |
| `GET /lojas` | admin, utilizador | `[{id, nome, fase, regiao_id, lat, lng, telefone}]` por nome |
| `POST /lojas` | admin, utilizador | 201 loja completa |
| `GET /lojas/{loja_id}` | admin, utilizador | Loja completa |
| `PATCH /lojas/{loja_id}` | admin, utilizador | Campos alterados + `atualizado_em` (obrigatório) + `confirmar_duplicado?` → 200 |
| `DELETE /lojas/{loja_id}` | admin, utilizador | `{apagada: true}` |
| `GET`, `PATCH /definicoes` | admin | `{fabrica_morada, fabrica_lat, fabrica_lng}` |
| `GET /config` | admin, utilizador | `{mosaicos: {url, atribuicao: geoapify\|osm}, alternativa: {url}, centro: {lat, lng}}` |
| `GET /morada/pesquisa?texto=&lat=&lng=` | admin, utilizador | Até 5 `{rotulo, morada, codigo_postal, localidade, lat, lng}` |
| `GET /morada/inversa?lat=&lng=` | admin, utilizador | Uma sugestão ou `null` |

**Loja completa (API):** `id, nome, fase, fase_desde, regiao_id, morada, codigo_postal, localidade, lat, lng,
origem_coords, precisao_m, telefone, pessoa_contacto, notas, janela1_inicio, janela1_fim, janela2_inicio,
janela2_fim, dias_fechada, visita_pendente_motivo, visita_pendente_desde, ultima_interacao_em,
ultima_visita_ou_entrega_em, criado_por, criado_em, atualizado_em`.

**Morada:**
- `texto` tem 3 a 200 caracteres depois de aparar ("Escreva pelo menos 3 caracteres." / "A pesquisa tem no máximo 200 caracteres."); sem texto, dá o mesmo erro que com menos de 3.
- `lat`/`lng` validam-se com `^-?[0-9]{1,3}(\.[0-9]+)?$`. Na pesquisa, valores inválidos ignoram o bias (`lat=1e2` ou `lat=abc` → 200 sem bias); na inversa, dão 422 ("A latitude tem de ser um número." / "Fora de Portugal").
- Nada disto chama a rede quando o pedido é inválido.

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
| `PrivacyPolicy.js` | Secção do CRM (T2.31) |

**Ecrãs:**

| Ecrã | Fase | Comportamento essencial |
|---|---|---|
| Páginas "Brevemente" | F1 | Componente `ComingSoon`, subtítulo "CRM Purple House" |
| Mapa | F2 | Pinos por fase com o nome em etiqueta permanente (nó `span` com `textContent`); zoom 6–19, `ZOOM_LOJA = 17`; filtros de fase e região (Todas/Sem região/…) guardados em `localStorage` (`crm.filtros`); "N lojas"; cartão com nome, fase, "Última ação: ainda sem histórico", **Ligar** (`tel:`) e **Ver ficha**; "Nova loja"; `?loja=<id>` centra a loja; ao voltar, "os filtros escondem-na do mapa." quando é o caso |
| Nova loja | F2 | Primeiro a localização (pino, pesquisa de morada ou "Estou nesta loja"), depois nome*, fase* (pastilhas, `potencial` por omissão), região (última usada, `crm.ultimaRegiao`; sem região esquece a anterior), telefone, contacto, morada, código postal, localidade, notas; Guardar desativado sem nome e pino, ou sem rede; diálogo de duplicado com 3 botões; "Loja guardada" e o mapa centrado nela |
| Ficha da loja | F2 | Fase num toque (§5.10), horário (2 janelas `type="time"`), dias fechada, Guardar só com o que mudou + `atualizado_em`, faixa de conflito, "Corrigir localização", Apagar com confirmação |
| Definições (admin) | F2 | Separadores Membros / Regiões / Fábrica; membros com "(conta apagada)" e a linha do admin principal fixa |
| Planear rota | F3 | Original §7 |
| Rota do dia | F4 | Original §8 + desenho §5 |
| Linha do tempo, Encomendas, Produtos, alertas | F5 | Original §6.3, §6.4 e §4.2 |

**Módulos puros em `src/lib/crm/` (Jest, portados de `tests/js/*.test.js`):**

| Módulo | O que faz |
|---|---|
| `api.js` | Cliente HTTP (molde `lib/faturacao.js`) com erros normalizados |
| `acesso.js`, `eu.js` | Visibilidade e cache do `/eu` por token |
| `fases.js`, `atribuicoes.js` | Cores e textos exatos |
| `mosaicos.js` | Troca para a alternativa depois de pelo menos 3 erros, se forem mais do que os sucessos (uma só vez) |
| `dom.js` | Recusa `on*`, `srcdoc` e `javascript:`; `hrefTelefone` só com 9 dígitos ou mais |
| `filtros.js` | Região `'todas' \| 'sem' \| uuid` |
| `diferencas.js`, `perfis.js`, `rede.js` | Diferenças da ficha, nomes dos perfis, estado da rede |
| `gps.js`, `localizacao.js`, `morada.js` | Morada com espera de 300 ms e mínimo de 3 caracteres; uma resposta antiga não substitui a nova |
| `mapa.js` | Mapa e pinos (com `testes/leafletFalso.js` e `testes/domFalso.js`) |
| `ficha.js`, `regioes.js`, `lojaNova.js`, `fabrica.js`, `dialogo.js`, `seletor.js` | Regras dos ecrãs |
| `seguranca.test.js`, `css.test.js` | Varrimento de HTML perigoso (§0 regra 9) e cores do `crm.css` |

Mensagens de rede: `'Sem rede — verifique a ligação e tente novamente.'` e `'Erro inesperado — tente novamente.'`.

**Erros no frontend (`lib/crm/api.js`, T1.10).** Todo o erro do cliente sai como `ErroCrm {codigo, mensagem, campos, extra, estado}`:
- `detail` objeto do CRM → tal como vem (`campos` só se for objeto simples; `extra` = as outras chaves, ex.: `lojas`);
- sessão: 401 em texto → `nao_autenticado` com o texto; `"Not authenticated"` e `"Invalid authentication credentials"` (403 do `HTTPBearer`) → `nao_autenticado` com `'Sessão terminada'`, nunca o inglês; outro 403 em texto → `sem_permissao`;
- 422 em lista (Pydantic) → `validacao` com `'Verifique os campos assinalados.'` e um campo por chave;
- sem resposta → `sem_rede` (estado 0); um erro que não veio do axios → `erro_interno`, nunca `sem_rede`; o resto → `erro_interno` com a mensagem genérica.

O interceptor lê o token do axios global a cada pedido e, sem token, **tira** o `Authorization`: o `axios.create` copia os
`defaults` ao nascer e mandaria o token de uma sessão já terminada.
**Mapa sem juntas:** `.crm-mapa img.leaflet-tile { mix-blend-mode: plus-lighter; }`, a etiqueta com cores fixas
(legível no tema escuro) e o contentor com altura explícita.

---

## 8. Integrações externas

**Geoapify** (dados OpenStreetMap; plano gratuito de 3 000 créditos/dia com uso comercial; os resultados podem ser guardados). Usa duas chaves:

- **Mosaicos** (vai para o browser só por `GET /api/crm/config`, para membros):
  - o modelo é `https://maps.geoapify.com/v1/tile/osm-bright/{z}/{x}/{y}.png?apiKey=<chave codificada>`;
  - a chave é lida a cada pedido;
  - no painel da Geoapify fica **restrita por Referer** a `https://lisbonb.com`.
  - Sem chave, `url` é a alternativa `https://tile.openstreetmap.org/{z}/{x}/{y}.png` com `atribuicao: "osm"`. É o normal em local.
  - O `rh.lisbonb.com` é sinónimo **permanente** no Caddyfile (as apps instaladas trazem esse endereço). Com a restrição planeada, quem entra por `rh.lisbonb.com` fica sempre nos mosaicos OSM (decisão do dono, §14).
- **Servidor** (pesquisa de morada e morada sugerida; nunca vai para o browser):
  - Pesquisa: `<CRM_GEOAPIFY_URL>/v1/geocode/autocomplete` com `text`, `filter=countrycode:pt`, `bias=proximity:<lng>,<lat>` (só com ponto válido; coordenadas até 6 casas sem zeros no fim), `lang=pt`, `limit=5`, `format=json` e `apiKey`.
  - Inversa: `<CRM_GEOAPIFY_URL>/v1/geocode/reverse` com `lat`, `lon`, `lang=pt`, `format=json` e `apiKey`.
  - Normalização: `{rotulo, morada ("Rua Augusta 24"), codigo_postal (só 0000-000), localidade (city → town → village → county), lat, lng}`. Ignoram-se resultados sem coordenadas, sem `formatted`, fora de `pt` ou fora do continente.
  - Cliente `httpx` assíncrono com `Timeout(5.0, connect=3.0)`. `CRM_GEOAPIFY_URL` (por omissão `https://api.geoapify.com`) é lido a cada pedido.
- **Chave fora dos registos:**
  - os loggers `httpx` e `httpcore` ficam em `WARNING`;
  - apanha-se a base `httpx.HTTPError` (mais o `ValueError` do JSON) → 503 `morada_indisponivel`;
  - regista-se só o tipo da exceção e o código HTTP, **nunca `str(exc)`** (traz o URL com a chave);
  - um teste com chave canária e `caplog` em DEBUG cobre o sucesso e cada falha, incluindo `ReadError` e `RemoteProtocolError`.
- Respostas gravadas em `backend/tests/crm/fixtures/geoapify/` (copiadas do autónomo e marcadas para regravar com a chave de desenvolvimento do dono, §14).

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

**Navegação (F4), links `<a href>` tocados pela pessoa e sem chave:**
- `https://www.google.com/maps/dir/?api=1&destination=LAT,LNG&travelmode=driving&dir_action=navigate[&avoid=tolls]`
- `https://waze.com/ul?ll=LAT,LNG&navigate=yes[&avoid_tolls=true]`
- Blocos de 9 paragens no Google Maps, a confirmar no telemóvel da carrinha (§14).

**Google Places/Routes: não se usa.** Os termos europeus do Google Maps Platform (desde 8 jul 2025) proíbem
guardar nome, morada, telefone e coordenadas vindos da Google. **Não se reutiliza a chave Google Places do
portal** (é do Marketing) e não se guarda nenhum dado da Google: todas as coordenadas guardadas são "nossas"
(pino confirmado, GPS no local ou geocoder que permite guardar).

**Leaflet 1.9.4** do npm (`yarn add leaflet@1.9.4 --exact`), sem `markercluster`, com o `leaflet.css` do pacote.

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
| `src/Servicos/Geoapify.php` | `backend/crm/servicos/geoapify.py` (httpx) |
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
| Frontend | `node_modules` reinstalado com `yarn install --frozen-lockfile`, sem `--ignore-engines`; `yarn.lock`, `package.json` e `package-lock.json` intactos; `@craco/craco 7.1.0`, `react-scripts 5.0.1` |
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
  - depois usa `pymongo.uri_parser.parse_uri` dentro de `try` e exige que todos os anfitriões sejam `127.0.0.1`, `localhost` ou `::1`;
  - `bd_e_local` exige um nome terminado em `_local`.
  - Se falhar: "Recusado: o seed só corre num MongoDB local (mongodb://127.0.0.1) e numa base *_local." e `saida=1`. Um ficheiro de ambiente em falta também dá "Recusado…", e o MongoDB parado dá uma mensagem própria.
- **Cria:** as 4 contas de demonstração em `users` (bcrypt, `must_change_password: False`) e 3 linhas em `crm_membros` (`criado_por: "seed-local"`). Na T2.18 juntam-se as regiões e as lojas.
- **Credenciais:** as palavras-passe geradas vão para `~/.config/lisbonb-crm-local/credenciais.txt` (modo 600, pasta 700), uma linha `email<TAB>palavra-passe` por conta. O ecrã só mostra o caminho e uma contagem. **Não se mostra o conteúdo.**
- **`--repor`:** gera palavras-passe novas para as 4 contas e acerta `password_mudada_em`, o que termina as sessões abertas antes. As contagens não mudam.
- **Contagens esperadas:** `users` = 5 (4 de demonstração + o admin master criado no primeiro arranque do backend) e `crm_membros` = 3.

### 12.5 Contas locais

| Conta | Papel no portal | CRM | Onde aterra | Palavra-passe |
|---|---|---|---|---|
| `admin.local@example.com` (admin master) | `admin` | `admin` (implícito) | `/admin` | `ADMIN_PASSWORD` do `backend/.env.local`, **reposta a cada arranque** ("Master admin password atualizada: …") |
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
- O ensaio da T2.17 só corre com `CRM_MONGO_TESTE_URL=mongodb://127.0.0.1:27017` e na base `lisbonb_crm_teste`.
- O build de verificação não depende do ambiente local: lê o `.env.production`, e o *bundle* fica a apontar para `https://rh.lisbonb.com`. Só serve para compilar, nunca se publica.

### 12.8 Registos e ficheiros locais

| Caminho | Conteúdo |
|---|---|
| `~/.cache/lisbonb-crm-local/*.log` | Instalações (`brew-*.log`, `pip.log`, `yarn-install.log`), suites (`pytest-tudo*.log`, `jest-partida.log`), servidores (`backend.log`, `frontend.log`), seed (`seed-t07*.log`) |
| `~/.cache/lisbonb-crm-local/estado-partida-T06.txt` | Estado de partida estruturado (§13) |
| `~/.cache/lisbonb-crm-local/arranque-T08.txt`, `t08_login.py`, `t08-*.png` | Registo do arranque, script de login e capturas |
| `~/.cache/lisbonb-crm-local/build/` | Build de verificação (a partir da F1) |
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

| Momento | Commit | Backend (passed / failed / skipped) | Jest `src/lib` |
|---|---|---|---|
| Partida (T0.6) | `2e0dbac` | 3552 / 0 / 3 | 114 / 0 |
| Depois da T0.7 (+50 de `tests/crm/test_seed_local.py`) | `38f40c4` | 3602 / 0 / 3 | — |
| Fecho da F1 (T1.15) | `902b4e8` | 4071 / 0 / 3 (3552 + 519 de `tests/crm`) | 354 / 0 (9 suites: as 6 antigas com 114 + 240 do CRM) |
| Revisão da F0/F1 (+22: `test_cron_key.py` e um meta-teste do cron; Jest +35) | ver `git log` ("CRM: corrige revisão da F0/F1") | 4093 / 0 / 3 (3552 + 541 de `tests/crm`) | 389 / 0 (9 suites: 114 + 275 do CRM) |
| Fecho da F2 (T2.32) | — | *a preencher* | *a preencher* |

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
| 5 | Criar a conta openrouteservice (chave só no servidor) | Antes da F3 | Por fazer |
| 6 | Avisar o Matheus antes da primeira publicação e das alterações aos ficheiros partilhados (`server.py`, `App.js`, `AdminLayout.js`, `EmployeeLayout.js`, `PrivacyPolicy.js`, `.env.example`, `package.json`, `yarn.lock`) | Antes de publicar a F1 | Por fazer |
| 7 | Rever a redação da secção do CRM na política de privacidade (GPS só ao tocar; Geoapify e OpenStreetMap como prestadores do mapa e da pesquisa de morada) | T2.31, antes de publicar a F2 | Por rever |
| 8 | Autorizar cada subida (push, junção ao `main`, `deploy.sh`) e aprovar cada fase no portal verdadeiro | Fim de cada fase | F1 verificada em local (T1.15, §13); a subida espera pelos pontos 1, 6 e 10 e pela autorização |
| 9 | Escolher os membros iniciais: só o Bruce na F1; quem registar lojas na F2; escritório na F3; o motorista na F4 | Ao publicar cada fase | — |
| 10 | Decidir se o repositório do portal (hoje **público**) passa a privado, depois de falar com o Matheus (desenho §9). O código do CRM ficaria público | Antes da primeira publicação do CRM | Por decidir |
| 11 | Confirmar no telemóvel da carrinha que o link de 9 paragens abre a app Google Maps; se não abrir, o bloco passa a 4 | F4 | — |
