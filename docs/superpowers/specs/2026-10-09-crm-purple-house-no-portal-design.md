# CRM Purple House como módulo do portal Gestão Lisbonb — Desenho

- **Data:** 2026-10-09
- **Autor:** Bruce Silva (com Claude Code)
- **Estado:** decisões aprovadas em conversa; revisto por 3 revisores independentes (fidelidade, encaixe no portal, lacunas); por rever por escrito pelo Bruce
- **Base:** [desenho original do CRM](2026-10-02-crm-purple-house-desenho-original.md). As regras de negócio desse documento (§4, §6, §7, §8, §9) **continuam válidas**, com as exceções escritas aqui. Este documento substitui a arquitetura (§3 v1, §5, §10–§13, §16–§17 do original).

---

## 1. Decisão

O CRM da fábrica Purple House deixa de ser uma app autónoma (PHP + MariaDB na Hostinger) e passa a ser um **módulo nativo do portal Gestão Lisbonb** (lisbonb.com): mesmo aspeto, mesmo login, mesmo servidor e mesma base de dados. É o caminho que levou o Financeiro (app PHP reescrita dentro do portal).

Decisões do Bruce (2026-10-09):

| Tema | Decisão |
|---|---|
| Caminho | **Reescrever no portal** (FastAPI + MongoDB + React); o CRM autónomo serve de referência de comportamento |
| Quem vê o CRM | **Só a equipa Purple House**: as pessoas que o Bruce escolher (membros do CRM) |
| Escritório | Membros podem ser **gestores ou colaboradores** do portal; um colaborador membro usa o CRM **sem ver o resto do portal** |
| Motorista | **Já é colaborador** do portal; entra com o seu email e palavra-passe |
| No terreno | O motorista pode **registar lojas novas** ("Estou nesta loja") e **corrigir localizações**, como no desenho original |
| Publicação | Cada fase vai para o portal verdadeiro **escondida**: só os membros a veem; no início só o Bruce |
| Ordem | **Rota primeiro** (2026-10-08): base → planear rota → rota do dia → encomendas e alertas |
| Coordenação | O Matheus também trabalha no portal: ramos próprios, alterações pequenas nos ficheiros partilhados, aviso antes da primeira publicação |

## 2. O que se mantém, o que muda

**Mantém-se:** fases e funil (§4.1 original), alertas e temporizadores (§4.2), motivos de paragem (§4.3), ecrãs e comportamento (§6), planeamento de rota (§7), rota do dia, navegação e registos (§8), serviços externos e regras legais (§9), nome sempre visível ao lado do pino sem agrupamento, GPS só ao tocar e nunca seguimento contínuo.

**Muda:**

| Desenho original | No portal |
|---|---|
| PHP 8.4 + MariaDB na Hostinger | Pacote `crm` no backend FastAPI + coleções `crm_*` no MongoDB Atlas do portal |
| Vanilla JS + PWA própria | Páginas React do portal (shadcn/ui + Tailwind), Leaflet 1.9.4 |
| Login próprio de 30 dias, CSRF, utilizadores do CRM | Login do portal (sessão de 24 h, token no cabeçalho); sem CSRF; utilizadores são os do portal |
| Perfis `admin`/`utilizador` | **Membros do CRM** com perfis `admin`, `utilizador`, `motorista` (§3) |
| Site de teste + GitHub Actions + porta SSH na Hostinger | Publicação do portal (`deploy.sh` no VPS); o CRM fica escondido a quem não é membro; o Bruce aprova cada fase **no portal verdadeiro**, enquanto só ele a vê |
| Migrações SQL numeradas | Índices declarados no código (como a Faturação) |
| Cópias `mysqldump` + email semanal; estado das cópias nas Definições (§6.7 original) | Cópias do MongoDB Atlas (§9, condição da F0); o estado das cópias deixa de aparecer nas Definições do CRM |
| Página de termos e privacidade do CRM (§6.8) | A página de privacidade do portal ganha um parágrafo sobre o GPS do CRM (só ao tocar, só o ponto da loja) — F2 |
| `crm.purplehouseacai.com` | Dentro de `lisbonb.com` |
| App instalável do CRM | **Só web na v1.** O motorista usa o Chrome/Safari em `lisbonb.com/rota` com atalho no ecrã principal. As apps "Lisbonb RH" das lojas (que trazem a interface embutida) escondem o CRM na v1 |

## 3. Acesso e permissões

### 3.1 Membros
- `crm_membros {id, user_id (único), perfil, criado_em, criado_por}`; um só perfil por pessoa.
- Perfis:
  - `admin` — tudo, incluindo membros, regiões, produtos e definições do CRM;
  - `utilizador` — lojas, mapa, planear rotas, encomendas;
  - `motorista` — rota do dia **e**, no terreno, registar loja nova com "Estou nesta loja" e corrigir a localização de uma loja.
- Qualquer conta do portal (gestor ou colaborador) pode ser membro com qualquer perfil.
- O **admin master do portal** (conta cujo email é o `ADMIN_EMAIL` de produção — a confirmar na F0 que é a do Bruce) é sempre `admin` do CRM, sem linha em `crm_membros`. Por isso o CRM nunca fica sem admin; não é preciso a regra do "último admin".
- Só um `admin` do CRM adiciona, muda ou retira membros. Escolhe-os de uma lista mínima de contas ativas do portal (`GET /api/crm/membros/candidatos`: id, nome, email, tipo de conta).
- Se a conta do portal for desativada ou apagada, a pessoa perde o acesso ao CRM de imediato (a autenticação relê a conta em cada pedido).

### 3.2 Onde se entra
- **Área própria do CRM:** `/crm/*`, com um layout próprio no aspeto do portal (barra lateral só com os itens do CRM e "Voltar ao portal"). Entra **qualquer membro** `admin`/`utilizador`, seja gestor ou colaborador. Um colaborador membro chega lá por um item "CRM" na sua área; não vê nada do resto do portal.
- **Gestores:** o menu de gestão (`/admin`) ganha a secção **CRM**, que abre as **mesmas páginas** dentro do layout de gestão (`/admin/crm/*`).
- **Rota do dia:** `/rota`, rota de topo com guarda própria (precedentes `/bolso` e `/faturacao/pos`), aberta a **qualquer membro** (motorista, utilizador, admin) — assim o Bruce também a vê e testa.
- O item "CRM"/"Rota do dia" e a secção CRM só aparecem a membros. O estado de membro vem de `GET /api/crm/eu` → `{membro, perfil, admin_master}`, chamado uma vez por sessão e partilhado com as páginas; se a chamada falhar, o CRM fica escondido. Quem não é membro e escreve o endereço à mão é enviado para o início (ou vê "Sem acesso" em `/rota`).

### 3.3 Proteção no servidor (é o servidor que protege; a interface só esconde)
- Três famílias de rotas, verificadas por um teste automático com listas explícitas (molde `tests/faturacao/test_protecao_rotas.py`):
  - **pública:** `GET /api/crm/saude` (sem dados);
  - **qualquer sessão válida do portal:** `GET /api/crm/eu` (devolve `membro: false` a quem não é membro, nunca 403);
  - **tarefas agendadas:** `/api/crm/cron/*`, com `CRON_KEY` comparada com `compare_digest` e fechada se a variável faltar.
- Todas as outras exigem membro com o perfil certo, através de uma dependência comum fixa (`membro_crm_atual`) que o teste consegue detetar.
- A autenticação constrói-se sobre `faturacao.auth.utilizador_atual` (como o pacote `plataformas`): herda o papel lido da base de dados e a recusa de tokens anteriores a uma troca de palavra-passe.
- **Acesso indevido a registos (IDOR):** cada pedido verifica a loja/rota pelo `id`; o motorista só escreve em paragens das suas rotas (§5.3).

## 4. Arquitetura

### 4.1 Backend (`backend/crm/`, no molde de `backend/faturacao/`)
- `__init__.py`: `APIRouter(prefix="/api/crm")` montado em `server.py` junto dos outros routers; `arrancar()` cria os índices (protegido, com limite de tempo).
- `auth.py`: `membro_crm_atual` e `exigir_perfil(...)` sobre `faturacao.auth.utilizador_atual`; admin master pelo email da base comparado com `ADMIN_EMAIL`.
- `db.py`: reutiliza o acesso à base da Faturação (`faturacao.db.obter_db`) para não criar mais um conjunto de ligações ao Atlas; declara coleções e índices `crm_*`.
- `dominio/`: funções puras portadas do CRM autónomo (`purple-house-crm/src/Dominio/`): fases, validação de lojas, janelas horárias, duplicados a 50 m, distância, precisão do GPS, Portugal continental, regras de regiões, definições, membros; depois o planeamento (pedido VROOM sem dados pessoais, recálculo de chegadas, sugestões, links de navegação).
- `servicos/geoapify.py`, `servicos/ors.py`: cliente HTTP assíncrono com tempo limite e URLs configuráveis. A chave do openrouteservice vai no cabeçalho `Authorization`. A Geoapify exige a chave no endereço, por isso o pacote baixa o registo dos loggers `httpx`/`httpcore` para `WARNING` e um teste garante que nenhuma chave aparece nos registos. Testes com `httpx.MockTransport` e respostas gravadas.
- Rotas por recurso: `eu`, `membros`, `regioes`, `lojas`, `definicoes`, `morada`, `config` (chave dos mosaicos, com guarda), `rotas`, `motorista`, `cron`.

### 4.2 Frontend (`frontend/src/`)
- `lib/crm/api.js` (cliente HTTP, molde `lib/faturacao.js`) e os módulos puros copiados do CRM autónomo em `lib/crm/` (fases e cores, filtros, mosaicos e plano B, atribuições, GPS, morada, diferenças, links Google Maps/Waze), com os testes passados para Jest.
- `components/crm/MapaLojas.js`: Leaflet 1.9.4; pinos `divIcon` com o nome em etiqueta permanente; atribuições exatas (§9 original); mosaicos Geoapify com plano B OpenStreetMap; sem juntas entre mosaicos.
- `pages/crm/`: Mapa, Nova loja, Ficha da loja, Definições do CRM (membros, regiões, fábrica); depois Planear rota, Encomendas; e `RotaDoDia`.
- `components/layouts/CrmLayout.js` (área `/crm/*`); `App.js`: rotas `/crm/*`, `/admin/crm/*` (mesmas páginas) e `/rota`.
- `components/layouts/AdminLayout.js`: secção `crm` só para membros (a grelha de secções passa a filtrar por visibilidade, porque hoje o `masterOnly` só filtra itens); exclusão `/admin/crm` no `match` do RH (obrigatória); nesta secção esconde-se o seletor de empresa e não se pedem as empresas; o mapa ocupa a área toda (decidido por rota, não por secção).
- `components/layouts/EmployeeLayout.js`: itens "CRM" e/ou "Rota do dia" condicionais, conforme o perfil.
- Nas apps nativas (`Capacitor.isNativePlatform()`), o CRM fica escondido na v1.

### 4.3 Dados (MongoDB Atlas, coleções `crm_*`, `id` uuid4, sem expor `_id`)

| Desenho original (§5) | No portal |
|---|---|
| `utilizadores`, `sessoes`, `tentativas_login` | não existem — `users` do portal + `crm_membros` |
| `regioes` | `crm_regioes {id, nome, ordem}` (nome único sem distinguir maiúsculas/acentos); só se apaga sem lojas |
| `lojas` | `crm_lojas {…campos do §5 original…, loc: {type: "Point", coordinates: [lng, lat]}, janelas: [{inicio, fim}], dias_fechada: [...]}`; índice `2dsphere` em `loc`; edições simultâneas com atualização condicional em `atualizado_em` |
| `interacoes` | `crm_interacoes` — índice único parcial em `client_uuid`, índice `(loja_id, ocorrida_em)`; mudanças de fase registadas desde a F2 |
| `produtos`, `encomendas` | `crm_produtos`, `crm_encomendas` (linhas dentro da encomenda) — F5 |
| `rotas`, `paragens` | `crm_rotas {id, data (única), estado, versao, …, paragens: [...]}` |
| `definicoes` | `crm_definicoes` (valores por defeito no código) |

- **Gravações do escritório numa rota:** atualizam campos de paragens concretas (não substituem a lista inteira) e são condicionais à `versao`; **nunca apagam nem sobrepõem um resultado registado pelo motorista** ("o que aconteceu no terreno ganha", §7.4/§8.4 original).
- **Registo do telemóvel sem transação de vários documentos** (o portal não as usa): a inserção da interação com o `client_uuid` único é o **ponto de confirmação**; os outros efeitos são idempotentes (datas com `$max`, fase "só sobe", paragem marcada com o `client_uuid`). Um reenvio com o mesmo `client_uuid` volta a aplicar os efeitos que faltarem em vez de ser ignorado. Testado incluindo uma falha a meio.
- **Tempo:** instantes em ISO UTC; datas e horas de Lisboa como texto (`AAAA-MM-DD`, `HH:MM`); "hoje" em `Europe/Lisbon`.
- **Migração de dados:** nenhuma. Os dados reais entram diretamente em produção a partir da F2; os dados de demonstração só existem em local (o seed recusa correr na base de produção).

### 4.4 Serviços externos e chaves
- **Geoapify** (duas chaves): mosaicos (vai para o navegador por `GET /api/crm/config`, com guarda; restringida no painel Geoapify a `https://lisbonb.com`) e servidor (pesquisa e morada sugerida).
- **openrouteservice:** só no servidor.
- **Google:** nenhuma chave; só os links de navegação. Não se reutiliza a chave Google Places do portal (termos Google para a Europa, §9 original).
- Variáveis no `.env` do backend no servidor; no repositório só os nomes, em `backend/.env.example`: `CRM_GEOAPIFY_CHAVE_SERVIDOR`, `CRM_GEOAPIFY_CHAVE_MOSAICOS`, `CRM_ORS_CHAVE`, `CRM_GEOAPIFY_URL`, `CRM_ORS_URL`.

## 5. Motorista e rota do dia (F4)

### 5.1 Ecrã
- `/rota` segue o §8 do desenho original: cartão da próxima paragem, Google Maps/Waze, registo num toque com "Desfazer", correções.
- No terreno também tem "Estou nesta loja" (loja nova) e "Corrigir localização" (com o mesmo fluxo de confirmação e precisão do GPS do §6.2/§6.3 original). "Nova encomenda" chega na F5.

### 5.2 Sessão de 24 h e arranque sem rede
- O portal dá uma sessão de 24 h, contada a partir do momento em que se entra. O ecrã mostra "sessão válida até HH:MM". Ao abrir a rota antes de sair, se a sessão acabar antes do regresso previsto + 1 h, pede para entrar de novo **nesse momento, com o carro parado**.
- Se a sessão acabar a meio do dia, os toques continuam a ir para a fila e aparece só o aviso "Sessão terminou — os registos ficam guardados; entre quando estiver parado". A página **nunca salta sozinha** para o ecrã de entrar.
- `/rota` arranca **sem rede** a partir da cópia guardada no telemóvel (última rota, último `/api/crm/eu`, token), com "dados de HH:MM"; com rede, confirma no servidor.
- O service worker e o IndexedDB ficam **restritos a `/rota`** (o resto do portal não muda); o `sw.js` da rota do dia é servido como ficheiro real com `no-cache` (em `frontend/nginx.conf`).
- A fila fica associada ao `user_id`: nunca é enviada com outra conta no mesmo telemóvel.

### 5.3 Regras de escrita do motorista
- Leitura: só a rota de hoje.
- Escrita da fila: aceita itens de paragens de rotas com data entre **hoje − 3 dias** e hoje, em qualquer estado; o registo do terreno sobrepõe-se ao fecho automático.
- Cada item guarda o `user_id` de quem o criou; o servidor só o aceita dessa pessoa ou de um admin do CRM.

## 6. Fases

| Fase | O que traz | Quem é membro | O Bruce vê |
|---|---|---|---|
| **F0. Preparação** | Dossiê de portagem (`CRM_PORTING_GUIDE.md`, molde do Financeiro); aviso ao Matheus; confirmar `ADMIN_EMAIL` = conta do Bruce; **confirmar o plano de cópias do Atlas** (condição para entrar na F2 — se for o gratuito M0, sem cópias automáticas, acrescentar um `mongodump` noturno, com teste de reposição, combinado com o Matheus porque protege o portal todo); contas Geoapify e openrouteservice | — | — |
| **F1. Casca** | Área `/crm` e secção CRM só para membros, páginas "Brevemente", pacote `crm` com `/saude`, `/eu`, membros e candidatos, teste de proteção das rotas | Só o Bruce | A secção CRM no menu |
| **F2. Base** | Regiões, lojas (criar/editar/apagar, duplicado a 50 m, GPS com precisão), mapa com pinos por fase e nomes sempre visíveis, filtros, cartão, pesquisa de morada, ficha da loja (fase num toque, horários, dias fechada), definições da fábrica, membros, parágrafo de privacidade do GPS | O Bruce (e quem ele escolher para começar a registar lojas) | O que viu no CRM autónomo, dentro do portal |
| **F3. Planear rota (versão simples)** | Escolher o dia, paragens à mão, sugestões por fase (5 km), horários e dias fechados, ordem pelo VROOM e horas pelo Directions, arrastar, evitar portagens, ⚠️ avisos, Google Maps/Waze, limite de 48 paragens; **fecho simples**: uma rota de um dia anterior a hoje é tratada como concluída (verificado ao ler). Só arranca quando houver lojas reais nas regiões da primeira rota | + membros de escritório | A rota calculada no mapa |
| **F4. Rota do dia** | `/rota`, registos num toque, fila sem rede, "Estou nesta loja" e corrigir localização no terreno; grava desde o primeiro dia os campos de visita pendente e últimas visitas (mesmo que os ícones só apareçam na F5); "Entregue" sem encomendas é permitido | + o motorista | A rota no telemóvel (o Bruce também a abre) |
| **F5. Resto da Etapa 2** | Linha do tempo, produtos, encomendas (entregas automáticas na rota), "Nova encomenda" no terreno, alertas 📦 🔁 ⏰, sugestões por alerta, fecho automático noturno (cron) | | Encomendas e alertas |
| **F6. Fecho** | Auditoria de permissões; abrir à restante equipa; rever as apps nativas | Toda a equipa | A equipa começa a usar |

Cada fase: ramo próprio → testes → publicação no portal **escondida** → o Bruce experimenta no portal verdadeiro e aprova → a fase seguinte.

## 7. Testes
- **Backend (pytest, corrido dentro de `backend/`; `tests/crm/__init__.py`):**
  - as regras de `dominio/` primeiro, portadas dos cenários dos testes do CRM autónomo (a regra dos 50 m prova-se aqui, com a fórmula da distância);
  - a API com duplos da base de dados (molde dos testes da Faturação), verificando a forma exata dos filtros e das atualizações condicionais;
  - os índices declarados num teste próprio (molde `tests/faturacao/test_indices.py`);
  - cenários críticos: proteção de todas as rotas, membros e perfis, duplicado a 50 m, edições simultâneas, `client_uuid` (incluindo falha a meio), chaves fora dos registos.
- **Frontend (Jest):** módulos puros de `lib/crm/` com os testes trazidos do CRM autónomo.
- **Ponta a ponta:** o portal não tem Playwright; monta-se na F4 só para `/rota` (telemóvel, sem rede, sessão expirada).
- O comportamento real do MongoDB (índice único parcial, pesquisa geográfica, atualização condicional) confirma-se na validação do Bruce em cada fase.

## 8. Publicação
1. Ramo a partir do `main` atualizado. O ramo sobe ao GitHub só para a junção; se tiver de subir antes, o `main` junta-se ao ramo (*merge*) em vez de *rebase*. Nunca *force-push*.
2. `cd backend && pytest tests/crm` e os testes Jest a passar; build local do frontend.
3. Junção ao `main`.
4. Publicação com o `deploy.sh` do portal no VPS.
5. O Bruce experimenta no portal verdadeiro (só ele vê) e aprova a fase.
- **No repositório:** `no-cache` do `sw.js` da rota do dia em `frontend/nginx.conf`; nomes das variáveis em `backend/.env.example`; script do fecho noturno na raiz (molde `relatorio-diario-cron.sh`, F5).
- **No servidor:** variáveis `CRM_*` no `.env` do backend; linha no crontab (horário em UTC) na F5.
- **Não há** contentores, portas, Caddy, DNS, MariaDB ou PHP novos.

## 9. Riscos e cuidados
- **Choques com o Matheus** nos ficheiros partilhados (`App.js`, `AdminLayout.js`, `EmployeeLayout.js`, `server.py`): alterações pequenas e localizadas, ramo atualizado com frequência, aviso antes de publicar.
- **Cópias de segurança do Atlas:** condição para a F2 (ver F0).
- **Segurança do portal:** verificado a 2026-10-09 que a chave do login em produção é forte e diferente dos valores públicos. O repositório do portal é **público**; tornar privado fica à decisão do Bruce (depois de falar com o Matheus). O registo do "Esqueci a palavra-passe" escreve dados pessoais — tratado numa tarefa à parte.
- **Reescrita:** as regras correm pela primeira vez em Python; os cenários de teste do CRM autónomo são a rede de segurança; auditoria de permissões na F6.
- **Primeira secção com mapa no portal:** o Leaflet aumenta o ficheiro principal do frontend (hoje já com cerca de 2 MB).
- **Validação em produção:** sem site de teste, cada fase é experimentada no portal verdadeiro enquanto só os membros a veem; os ensaios com dados de demonstração fazem-se em local.

## 10. O CRM autónomo
- O repositório `purple-house-crm` fica **congelado** com a etiqueta `referencia-standalone`: não se publica, não se apaga, e continua a correr localmente para comparar comportamentos.
- Ficam sem efeito: a organização "Purple House" no GitHub, os sites `crm.`/`crm-teste.` na Hostinger, os workflows GitHub Actions e a porta de publicação do CRM autónomo.
