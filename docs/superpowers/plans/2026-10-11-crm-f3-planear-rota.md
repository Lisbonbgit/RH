# CRM Purple House no portal: plano de implementação F3 (Planear rota, versão simples)

- **Data:** 2026-10-11 · **Ramo:** `crm-purple-house` (local; o topo é `d195610`, "CRM: isola os mosaicos do mapa…")
- **Ficheiro sugerido:** `docs/superpowers/plans/2026-10-11-crm-f3-planear-rota.md`
- **Fontes (ler antes de começar):**
  - Desenho aprovado: `docs/superpowers/specs/2026-10-09-crm-purple-house-no-portal-design.md`. Prevalece. Ver §4.1 (`dominio/`, `servicos/ors.py`), §4.3 (`crm_rotas` com `paragens` embutidas; o escritório nunca sobrepõe o terreno), §4.4 e a linha F3 do §6.
  - Regras de negócio: `docs/superpowers/specs/2026-10-02-crm-purple-house-desenho-original.md`, §4.3 (motivos), §7 (planeamento), §8.2 (links de navegação) e §9 (openrouteservice: chave só no servidor, sem dados pessoais, atribuição).
  - Âmbito simples decidido a 2026-10-08 (resumido no §1 deste plano).
  - Plano anterior: `docs/superpowers/plans/2026-10-10-crm-f0-f1-f2.md`, com as **Correções obrigatórias** e as notas "Feito", que continuam a valer como receitas, e o dossiê `CRM_PORTING_GUIDE.md` (§3, §5.13, §5.14, §5.15, §6, §8, §12, §14).
  - Código real em que este plano assenta:
    - backend: `backend/crm/{__init__,auth,db,erros,pedidos,relogio,lojas,definicoes,config_mapa,morada,formatar}.py`, `backend/crm/dominio/*.py` e `backend/crm/servicos/geoapify.py`;
    - testes do backend: `backend/tests/crm/{conftest,duplos,formatos}.py`, `test_protecao_rotas.py`, `test_variaveis_ambiente.py`, `test_consistencia_frontend.py`, `test_mongo_local.py` e `test_morada.py` (o molde das falhas de rede);
    - frontend: `frontend/src/lib/crm/{api,mapa,atribuicoes,acesso,dom,fases,ids,rede,ecraMapa,ficha}.js`, `testes/leafletFalso.js`, `seguranca.test.js` e `css.test.js`; `components/crm/{MapaLojas,CartaoLoja,seccaoCrm}.js`, `crm.css`, `components/layouts/CrmLayout.js`; `pages/crm/{rotasCrm,CrmMapa,CrmDefinicoes}.js`.
  - O CRM autónomo (`/Users/brucesilva/purple-house-crm`) **não tem código de rotas**. Serve só de referência para o gravador de respostas (`src/Cli/GravarFixtures.php`: nunca grava a chave, grava tudo ou nada).
- **Âmbito:** só a F3 (versão simples), mais o fecho simples à leitura.
- **Fora (YAGNI):**
  - encomendas e entregas automáticas, alertas 📦 🔁 ⏰ e as sugestões por alerta (F5);
  - o ecrã `/rota` do motorista e a fila sem rede (F4);
  - o cron do fecho noturno (F5);
  - apagar uma rota inteira e as notas do escritório;
  - publicar, juntar ao `main`, ligar ao Atlas e chamar o openrouteservice verdadeiro.

> ⚠️ Antes de cada tarefa, ver a secção **Correções obrigatórias** no fim (vazia até à revisão por críticos). Quando tiver linhas, prevalecem sobre o texto da tarefa.

---

## 0. Como usar este plano (regras para os agentes — obrigatórias)

1. **Ordem estrita.** Fazer as tarefas pela ordem; cada tarefa assume só as anteriores. Marcar `[x]` no fim e acrescentar uma nota **Feito**, no molde da F2: vermelho, verde, contagens da bateria, decisões fixadas pelos testes e desvios. Cada tarefa leva 15–60 min.
2. **Nada sai do Mac.** É proibido:
   - `git push`, `git merge` para o `main`, o `deploy.sh` e o `ssh` ao VPS;
   - qualquer ligação ao MongoDB Atlas;
   - enviar emails ou mensagens;
   - **qualquer pedido ao openrouteservice verdadeiro** (`api.openrouteservice.org`). Isto vale também quando aparecer uma chave: só o [DONO] corre o gravador da T3.12.
3. **TDD em todas as tarefas de domínio, de API e de módulos puros:**
   - escrever o teste;
   - correr e ver falhar **pelo motivo indicado na tarefa**;
   - implementar o mínimo e ver passar;
   - correr a bateria do CRM (`tests/crm` e/ou `src/lib/crm`).

   Guardar o vermelho e o verde em `$HOME/.cache/lisbonb-crm-local/t3.N-{vermelho,verde}.log`. As **mutações mínimas** listadas em cada tarefa têm todas de ser apanhadas. O registo vai para `t3.N-mutacoes.log` e o ficheiro reposto confere-se com `cmp`.
4. **Testes nunca em paralelo.** Só o agente que executa a tarefa corre testes, e uma suite de cada vez. Os revisores leem código e não correm suites.
5. **Anti-encalhe** (igual à F2):
   - nunca servidores em primeiro plano;
   - instalações, a suite completa do backend e o `craco build` correm em segundo plano, com o registo em `$HOME/.cache/lisbonb-crm-local/*.log`;
   - esperas sempre limitadas (`curl --max-time 3`);
   - `pytest tests/crm` e o Jest de `src/lib/crm` em primeiro plano, abaixo de 90 s.
6. **Ficheiros partilhados com o Matheus.** Na F3 só se tocam dois:
   - `backend/.env.example` (T3.11, um bloco no fim);
   - `frontend/src/pages/PrivacyPolicy.js` (T3.42, uma frase).

   **Não se tocam** `backend/server.py`, `frontend/src/App.js`, `AdminLayout.js`, `EmployeeLayout.js`, `frontend/package.json` nem `yarn.lock`: nenhuma dependência nova, e o arrastar é feito sem biblioteca. Se uma tarefa parecer precisar de um destes ficheiros, **parar e perguntar**. Antes de cada commit, `git diff --stat` tem de mostrar só as linhas previstas.
7. **Commits:** um por tarefa (as tarefas sem commit estão indicadas), em pt-PT e com o prefixo `CRM:`. Adicionar **ficheiros explícitos**, nunca `git add -A` nem `git add .`. A pasta `HANDOFF/` não está versionada e não se toca. Formato:
   `git -C "/Users/brucesilva/pasta sem título/RH" commit -m "CRM: <frase>" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`
8. **Segredos:** nunca mostrar valores de `.env*`, palavras-passe, tokens ou chaves, nem no chat nem em ficheiros versionados (só os nomes).
   - A `CRM_ORS_CHAVE` verdadeira **nunca** é escrita pelos agentes.
   - No `backend/.env.local` só entra o valor do simulador (`simulador-local`, na T3.43), sem o imprimir.
9. **Segurança do DOM** (regra 9 da F2):
   - nunca `dangerouslySetInnerHTML` nem `.innerHTML`;
   - o Leaflet só recebe conteúdo e atribuição no `lib/crm/mapa.js`, com nós `el(...)` e `ATRIBUICOES[...].html`;
   - um `divIcon` nunca leva `html`;
   - os `href` de navegação só passam pelo `hrefNavegacao` (`lib/crm/dom.js`).

   Cada ficheiro novo do CRM entra na lista do `seguranca.test.js`.
10. **Caminhos com espaços e acentos:** citar sempre. Cada bloco de comandos começa por `RAIZ="/Users/brucesilva/pasta sem título/RH"; LOGS="$HOME/.cache/lisbonb-crm-local";`, porque o estado da shell não passa de uma chamada para a seguinte.
11. **[DONO]** marca o que só o Bruce faz. Os agentes não o fazem nem o simulam.
12. **Proibições herdadas e novas:**
    - não reutilizar a chave Google Places nem guardar dados da Google;
    - não endurecer a `Referrer-Policy`;
    - **ao openrouteservice só vão coordenadas, segundos, prioridades, índices numéricos 1..n e as constantes `"driving-car"`/`"tollways"`**, nunca nomes, telefones, moradas ou uuids. Um teste com canários prova-o (T3.6, T3.7 e T3.22);
    - a chave do ORS vai **só** no cabeçalho `Authorization`, nunca no URL;
    - **o simulador local do ORS só escuta em 127.0.0.1.**
13. **Corrotinas nos testes:** `correr(coro)` de `tests/crm/duplos.py`, nunca `asyncio.run`. Na T3.43, `grep -rn "asyncio.run(" backend/tests/crm` tem de dar vazio.
14. **Rotas novas classificadas no passo "teste primeiro".** Cada tarefa que cria uma rota HTTP a classifica em `PERFIS_POR_ROTA` (`tests/crm/test_protecao_rotas.py`) e acrescenta o recurso `rotas` ao `_perfis_pela_regra_da_api` (correção "T2.9–T2.15 vs T2.16" da F2). Cada código de erro novo entra em `crm/erros.py::ESTADOS` e na tabela de `test_erros.py` na mesma tarefa.

---

## 1. Decisões técnicas fixadas (não rediscutir)

| Tema | Decisão |
|---|---|
| Âmbito simples (2026-10-08) | As paragens escolhem-se à mão: no cartão do mapa ("Adicionar à rota", escolhendo o dia) e no planeador (sugestões e toque num pino). O motivo vem pré-escolhido pela fase: potencial/perdida → `angariacao`, contactada → `amostra`, amostra/cliente → `acompanhamento`. Ainda não há encomendas nem 🔁. |
| Gravação | **Cada ação grava logo**, como a fase num toque da ficha: adicionar, retirar, arrastar, definições do dia, motivo, tempo e "Manter". Leva sempre a `versao` em vigor (409 `conflito` se outra pessoa gravou). O botão **"Guardar rota"** passa `rascunho → planeada`, com a pergunta "N paragens não cabem — guardar mesmo assim?". Não há rascunho guardado no browser. |
| Uma rota por dia | `crm_rotas.data` (`AAAA-MM-DD`, hora de Lisboa) com índice **único**. Uma rota cria-se com a primeira paragem (`POST /rotas/{data}/paragens`). A `GET /rotas/{data}` de um dia sem rota devolve uma **rota virtual** (`existe: false`), com os valores por omissão. |
| Datas e fecho simples | "Hoje" vem de `relogio.hoje()` (Europe/Lisbon). Uma data anterior a hoje tem `estado_efetivo: "concluida"` ao ler, só de leitura; todas as escritas dão 409 `rota_fechada`. Não se criam rotas a mais de 365 dias (422). Na F3 nada grava `concluida`: o fecho noturno é da F5. |
| Estados | Gravados: `rascunho` e `planeada` (a F4 grava `em_curso`, a F5 `concluida`). A F3 só escreve em `rascunho`/`planeada`, numa rota **sem nenhum registo do terreno**. Se alguma paragem tiver `estado` `feita` ou `nao_feita`, a rota dá 409 `rota_em_curso`. |
| Paragens embutidas | A lista `paragens` é **só de acrescentar**: nunca há `$pull`, `$pop`, `$unset` nem substituição da lista. Retirar é suave (`removida_em`). Voltar a adicionar a mesma loja **reativa** a mesma paragem (o mesmo `id`, bom para a fila da F4). |
| O terreno ganha (desenho §4.3) | O escritório escreve **só** pelos caminhos `paragens.<índice>.<campo do escritório>` (`dominio.rotas.caminhos_paragem`, que recusa os campos do terreno) e por `$push` de paragens novas. Cada escrita é condicional: `{id, versao, estado ∈ editáveis, "paragens.estado": {"$nin": ["feita", "nao_feita"]}}`. Os campos do terreno (`estado`, `resultado`, `concluida_em`) só se escrevem ao criar a paragem (`pendente`/`null`/`null`). Um verificador dos testes (`formatos.escritas_no_terreno`) varre todas as atualizações. |
| `versao` | Inteiro ≥ 1; `$inc` em cada gravação do escritório que muda o plano (paragens, ordem, definições, estado, ordem do otimizador). **O recálculo das horas não muda a versão**: são dados derivados, gravados com o filtro da versão lida. |
| Adicionar sem versão | O cartão do mapa não conhece a versão. O servidor lê, verifica e grava condicionado à versão lida e, se falhar, volta a ler e tenta de novo, até 3 vezes. Com `versao` no corpo (o planeador): 409 se não bater. `versao: null` quer dizer "julgo que ainda não há rota". |
| Horas | **Só do Directions.** As horas contam-se em segundos desde a meia-noite local, a partir do texto "HH:MM" (`h*3600 + m*60`), nunca a partir de instantes UTC, e por isso não mudam nos dias de mudança de hora. `calculo.assinatura` é o sha256 da entrada do cálculo e diz se as horas guardadas ainda servem (`calculo.atual`). Uma loja que mudou de sítio, uma janela, a fábrica ou a ordem tornam-nas velhas. |
| Recálculo | Depois de cada alteração, quando a fila do browser fica vazia, o planeador pede `POST /rotas/{data}/recalcular` sozinho, se houver chave, se `calculo.atual` for falso e se o último recálculo não tiver falhado. Há também um botão "Recalcular horas". |
| Melhor ordem | `POST /rotas/{data}/otimizar` faz o VROOM e **depois sempre** o Directions pela ordem escolhida. É **atómico**: se uma das chamadas falhar, nada muda (503). |
| Fechadas neste dia | A paragem cuja loja fecha nesse dia da semana (`dias_fechada`) fica com `⚠️ Fechada neste dia` e **não entra** no VROOM nem no Directions até "Manter" (`manter_fechada: true`). |
| Não cabem | Os *jobs* não atribuídos pelo VROOM (e as janelas onde o serviço nunca cabe) ficam `nao_cabe: true`, no fim da lista e sem hora. Formam a secção "⚠️ Não cabe no horário"; "Pôr na rota" limpa o sinal (`nao_cabe: false`). |
| Pedido VROOM | Um veículo `driving-car`, `start`/`end` = início/fim, `time_window` = [saída, regresso limite]. Por cada paragem incluída, um *job* `{id: 1..n, location: [lng, lat], service: s, priority, time_windows: [[início, fim − serviço]…]}`, só com as janelas onde o serviço cabe. Prioridades: entrega = **100**, as outras = **1** (48 × 1 < 100). |
| Directions | `POST /v2/directions/driving-car/json` com `{coordinates, instructions: true, geometry: true, elevation: false, units: "m"}` e `options.avoid_features: ["tollways"]` quando se evitam portagens. O `instructions: true` é preciso para os `segments` (risco R2). A geometria é a polyline codificada (precisão 5), guardada em `calculo.geometria`. |
| Chegadas | chegada = partida anterior + duração do troço. Se chegar antes da janela, espera pela abertura (também pela 2.ª janela, sem aviso). `fora_de_horario` só quando nenhuma janela do dia leva o serviço (nesse caso serve-se à chegada, sem espera). O regresso previsto vem no fim, com aviso se passar do limite. Uma hora a partir das 24:00 fica `null`, com o aviso. |
| Sugestões | Calculadas no servidor (`GET /rotas/{data}/sugestoes`), em dois grupos: **contactada** e depois **potencial**. Entram as lojas a ≤ 5 km em linha reta de qualquer paragem ativa e, com `calculo.atual`, também as que estão a ≤ 3 km da linha desenhada (o **corredor**: barato, porque é O(lojas × troços) com rejeição por caixa; ver a T3.9). Ficam de fora a perdida (e a amostra/cliente sem alertas), as lojas fechadas nesse dia, as que já estão na rota e as que não têm coordenadas. Cada grupo mostra no máximo 30, com "e mais N". |
| Limite | **48 paragens ativas** (o Directions aceita 50 coordenadas, com o início e o fim). |
| Definições do dia | `hora_saida` e `hora_regresso_limite`, por omissão as das definições (08:00/19:00). `inicio`/`fim`: `null` = a fábrica (lida das definições ao calcular) ou `{lat, lng}` em Portugal continental. `evitar_portagens` é booleano. |
| Definições do CRM | Entram em `dominio/definicoes.PADROES`: `rota_hora_saida` "08:00", `rota_hora_regresso` "19:00", `servico_entrega_min` "10", `servico_amostra_min` "10", `servico_acompanhamento_min` "15", `servico_angariacao_min` "15". O admin muda-as em Definições → Rotas. O raio (5 km), o corredor (3 km) e o bloco do Google (9) ficam como constantes do código na F3. |
| Tempo de serviço | Por paragem, de 1 a 240 min (inteiro). Mudar o motivo sem enviar o tempo põe o padrão do motivo novo. |
| openrouteservice | `crm/servicos/ora.py` **não**: `crm/servicos/ors.py`, no molde do `geoapify.py` (reutiliza `geoapify.ler_json` e `geoapify.silenciar_registos`). POST JSON com a chave em `Authorization`, sem seguir redireções. Tempos: 3 s para ligar; 15 s ao todo na otimização e 10 s no Directions (o `otimizar` fica abaixo dos 25 s, contra os 35 s do cliente). `CRM_ORS_URL` por omissão é `https://api.openrouteservice.org`. Sem chave → 503 sem chamar nada. |
| Testes do ORS | Respostas escritas à mão em `backend/tests/crm/fixtures/ors/` (marcadas `"_origem": "manual — regravar"`), servidas por `httpx.MockTransport`. O `conftest.py` instala por omissão um transporte que **rebenta** se um teste tentar a rede. O gravador (T3.12) só corre pelas mãos do dono. O simulador local (T3.13) serve a pré-visualização. |
| Links de navegação | Calculados no servidor (`dominio/navegacao.py`, como o desenho §4.1 lista) e devolvidos na API (`paragem.links`, `rota.blocos_google`). O frontend só os desenha como `<a href>` tocados pela pessoa, depois de `hrefNavegacao`. Os blocos do Google têm 9 paragens: 8 `waypoints` e o destino. |
| Frontend | Módulos puros em `lib/crm` com Jest (molde `criarFicha`: o controlador produz uma `vista` congelada e o React só a desenha). Páginas `CrmRotas` (lista e escolha do dia) e `CrmRota` (planeador, ou leitura só). Item de menu "Rotas" depois de "Mapa". `ecraCheioDoCrm` também em `/crm/rotas/AAAA-MM-DD`. |
| Arrastar | Sem bibliotecas: uma pega com Pointer Events (rato e dedo, `touch-action: none`) e teclado (Espaço/Enter pegam e largam, as setas movem, o Escape cancela), com anúncios `aria-live`. "Subir/Descer" ficam no detalhe de cada paragem. As regras estão em `lib/crm/reordenar.js`. |
| Mapa do planeador | Usa o `MapaLojas` com o `prop` `rota`. As lojas fora da rota aparecem esbatidas. Pinos numerados: um `divIcon` sem `html` e o número acrescentado com `el()` ao elemento do marcador no `add`. Os pinos de início e fim e a linha (`L.polyline`) também. |
| Atribuição do ORS | `ATRIBUICOES.ors`, com o texto exato "Developed by VROOM · Hosted by HeiGIT · Routing by openrouteservice · Data from OpenStreetMap", sempre visível no ecrã do planeador. |
| Apagar uma loja | Bloqueado (409 `loja_em_rota`) se estiver numa paragem ativa ou numa paragem com registo do terreno. Uma paragem retirada e ainda `pendente` não bloqueia. |
| Mensagens das falhas do ORS | Sem chave, falha ou resposta inválida: "Cálculo automático indisponível — ordene à mão". Limite (429): "Cálculo automático indisponível por agora (limite de pedidos) — espere um minuto ou ordene à mão". Ponto longe da estrada (ORS 2010): "A paragem N não fica perto de uma estrada — corrija a localização da loja" (ou "O ponto de início/fim…"). |

---

## 2. Ficheiros

**Criar (backend)**
```
backend/crm/dominio/datas.py        ler_data, texto_data, dia_da_semana, somar_dias, MAXIMO_DIAS_FUTURO
backend/crm/dominio/horas.py        segundos, hora_de_segundos, minutos_de_segundos, janelas_em_segundos, janelas_vroom
backend/crm/dominio/ids.py          e_uuid4 (o mesmo padrão do validador_loja._UUID4)
backend/crm/dominio/rotas.py        MOTIVOS, MOTIVO_POR_FASE, prioridade, LIMITE_PARAGENS, estado_efetivo, bloqueio_de_escrita,
                                    ativas, seccoes, nova_ordem, servico_padrao, CAMPOS_DO_TERRENO/ESCRITORIO, caminhos_paragem
backend/crm/dominio/validador_rota.py  data_do_caminho, intervalo, adicao, alteracao, so_versao, coerencia_horas
backend/crm/dominio/vroom.py        ParagemCalculo, paragem_calculo, pedido_otimizacao, interpretar_otimizacao, RespostaInvalida
backend/crm/dominio/directions.py   pedido_direcoes, Trocos, interpretar_direcoes
backend/crm/dominio/polilinha.py    descodificar
backend/crm/dominio/horarios.py     calcular_horarios, entrada_calculo, assinatura
backend/crm/dominio/sugestoes.py    sugerir, distancia_a_linha, RAIO_SUGESTOES_M, CORREDOR_M, LIMITE_POR_GRUPO
backend/crm/dominio/navegacao.py    link_google, link_waze, blocos_google, TAMANHO_BLOCO_GOOGLE
backend/crm/servicos/ors.py         cliente do openrouteservice
backend/crm/formatar_rota.py        documento_rota, documento_paragem, rota_api, resumo_rota_api, PROJECAO_LOJA_ROTA
backend/crm/rotas_bd.py             ler, criar, alterar, acrescentar_paragem, porque_falhou, lojas_da_rota, rotas_entre, rotas_com_loja
backend/crm/rotas.py                /api/crm/rotas… (7 rotas)
backend/gravar_respostas_ors.py     CLI do dono (T3.12)
backend/ors_simulado_local.py       simulador só local (T3.13)
backend/tests/crm/fixtures/ors/     cenarios.json, otimizacao-todas.json, otimizacao-uma-nao-cabe.json,
                                    direcoes-tres-paragens.json, direcoes-erro-2010.json, erro-429.json
backend/tests/crm/test_dominio_{datas,horas,rotas,validador_rota,vroom,directions,polilinha,horarios,sugestoes,navegacao}.py
backend/tests/crm/test_{ors,gravar_respostas_ors,ors_simulado_local,formatar_rota,rotas_bd,rotas_ler,rotas_adicionar,
                        rotas_alterar,rotas_recalcular,rotas_otimizar,rotas_sugestoes,rotas_terreno}.py
```
**Modificar (backend, do CRM):**
- `crm/relogio.py` (`hoje`, `FUSO_LISBOA`);
- `crm/dominio/definicoes.py`, `crm/definicoes.py`;
- `crm/db.py` (`rotas` e índices);
- `crm/erros.py` (códigos novos);
- `crm/lojas.py` (apagar bloqueado);
- `crm/__init__.py` (incluir o router);
- `crm/servicos/__init__.py` (docstring);
- testes: `tests/crm/{conftest,duplos,formatos}.py` e `test_{duplos,indices,erros,protecao_rotas,variaveis_ambiente,consistencia_frontend,definicoes,dominio_definicoes,relogio,lojas_apagar,mongo_local}.py`.

**Criar (frontend)**
```
frontend/src/lib/crm/  datas.js polilinha.js rota.js reordenar.js filaRota.js planeador.js adicionarARota.js definicoesRotas.js
                       (+ *.test.js de cada um)
frontend/src/components/crm/  ListaParagens.js DefinicoesDoDia.js SugestoesRota.js ResumoRota.js DialogoAdicionarARota.js
frontend/src/pages/crm/  CrmRotas.js CrmRota.js DefinicoesRotas.js
```
**Modificar (frontend, do CRM):**
- `lib/crm/{api,mapa,atribuicoes,acesso,dom}.js` e os seus testes, mais `css.test.js`, `seguranca.test.js` e `testes/leafletFalso.js` (`polyline`);
- `components/crm/{MapaLojas,CartaoLoja,seccaoCrm}.js` e `crm.css`;
- `components/layouts/CrmLayout.js` (o ícone de "Rotas");
- `pages/crm/{rotasCrm,CrmMapa,CrmDefinicoes}.js`.

**Partilhados (mínimo):**
- `backend/.env.example`: bloco ORS, cerca de 12 linhas;
- `frontend/src/pages/PrivacyPolicy.js`: uma frase.

**Só locais (nunca versionados):** `backend/.env.local` (+2 linhas do simulador na T3.43) e `$HOME/.cache/lisbonb-crm-local/t3*` (registos, verificações temporárias, scripts do browser).

---

## 3. Modelo de dados — `crm_rotas` (MongoDB)

Cada documento é uma rota e há uma por dia.
```
{
  id: uuid4, data: "AAAA-MM-DD" (Lisboa, ÚNICA),
  estado: "rascunho" | "planeada"            (F4: "em_curso"; F5: "concluida"),
  versao: int ≥ 1,
  hora_saida: "HH:MM", hora_regresso_limite: "HH:MM",
  inicio: null | {lat, lng},  fim: null | {lat, lng},      null = a fábrica das definições em vigor
  evitar_portagens: bool,
  paragens: [ PARAGEM, … ]                   só se acrescenta; nunca se apaga nem se substitui
  calculo: null | {assinatura: "sha256:<64 hex>", distancia_m: int, duracao_s: int,
                   regresso_previsto: "HH:MM"|null, depois_do_limite: bool,
                   geometria: "<polyline codificada, precisão 5>", calculado_em: instante},
  criado_em: instante, criado_por: user_id, atualizado_em: carimbo (6 casas), atualizado_por: user_id
}
PARAGEM = {
  id: uuid4, loja_id: uuid4, ordem: int|null (0..n-1 entre as ativas; null se retirada),
  motivo: "entrega"|"amostra"|"acompanhamento"|"angariacao", tempo_servico_min: int 1..240,
  manter_fechada: bool, nao_cabe: bool,
  chegada_prevista: "HH:MM"|null, espera_min: int|null, fora_de_horario: bool,     ← do último Directions
  adicionada_em: instante, adicionada_por: user_id, removida_em: instante|null,
  estado: "pendente", resultado: null, concluida_em: null                          ← CAMPOS DO TERRENO (F4)
}
```
- **Campos do escritório** (`dominio.rotas.CAMPOS_DO_ESCRITORIO`): `ordem`, `motivo`, `tempo_servico_min`, `manter_fechada`, `nao_cabe`, `chegada_prevista`, `espera_min`, `fora_de_horario`, `removida_em`, `adicionada_em`, `adicionada_por`. São os únicos que `caminhos_paragem` aceita.
- **Campos do terreno** (`CAMPOS_DO_TERRENO = ("estado", "resultado", "concluida_em")`, alargados na F4): o escritório só os escreve ao criar a paragem.
- **Instantes:** `*_em` por `relogio.instante()`; `atualizado_em` por `relogio.carimbo()`/`proximo_carimbo()`. Tudo verificado com `formatos.instantes_fora_do_formato`.
- **O contrato com a F4, escrito já no dossiê §5.13:** uma escrita do terreno nunca muda a `versao` nem a ordem da lista. Só faz `$set` em `paragens.<i>.<campos do terreno>` e, ao repor uma paragem retirada, `removida_em: null`. A partir do primeiro registo, a F3 trata a rota como só de leitura.

| Coleção | Índices (`crm/db.py::INDICES`) |
|---|---|
| `crm_rotas` | `id` único; `data` único; `paragens.loja_id` (multikey, **não** único: serve o `DELETE /lojas` e a pergunta "esta loja está numa rota?") |

As outras coleções não mudam. Em `crm_definicoes` entram as 6 chaves novas, guardadas em texto como as da fábrica.

---

## 4. API (F3)

**Convenções:** as de F1–F2 (prefixo `/api/crm`, erros `{detail: {codigo, mensagem, campos?, …}}`, corpo por `corpo_json`, guarda de perfil antes do corpo, sem Pydantic). Os parâmetros (`data`, `de`, `ate`) leem-se como texto e validam-se no domínio. Todas as rotas novas são para o **escritório** (`ESCRITORIO = exigir_perfil("admin", "utilizador")`). O motorista dá 403 `sem_permissao`, quem não é membro 403 `sem_acesso_crm`, e sem sessão ficam os 401/403 herdados.

**Códigos de erro novos** (em `crm/erros.py::ESTADOS` e no dossiê §6):

| Código | HTTP | Mensagem exata | Tarefa |
|---|---|---|---|
| `ja_na_rota` | 409 | "Esta loja já está na rota deste dia." | T3.19 |
| `rota_cheia` | 409 | "Uma rota tem no máximo 48 paragens." | T3.19 |
| `rota_fechada` | 409 | "Este dia já passou — a rota só se pode ver." | T3.19 |
| `rota_em_curso` | 409 | "A rota já tem registos do motorista — no escritório só se pode ver." | T3.20 |
| `calculo_indisponivel` | 503 | Por `extra.tipo`: `sem_chave`/`indisponivel` → "Cálculo automático indisponível — ordene à mão"; `limite` → "Cálculo automático indisponível por agora (limite de pedidos) — espere um minuto ou ordene à mão"; `ponto_sem_estrada` → "A paragem {n} não fica perto de uma estrada — corrija a localização da loja" / "O ponto de início não fica perto de uma estrada — escolha outro ponto" / "O ponto de fim não fica perto de uma estrada — escolha outro ponto" | T3.21 |
| `loja_em_rota` | 409 | "Esta loja está numa rota — retire-a da rota ou mude a fase para perdida." | T3.24 |
| `nao_encontrado` | 404 | + "Ainda não há rota para este dia." | T3.20 |

**Mensagens de validação** (422 `validacao`, em `campos`):

- **`data`:** "Indique o dia no formato AAAA-MM-DD." · "Escolha um dia até um ano a partir de hoje."
- **`de`/`ate`:** "Indique o dia no formato AAAA-MM-DD." · `ate`: "O fim do intervalo tem de ser depois do início." · "O intervalo tem no máximo 120 dias."
- **`loja_id`:** "Escolha uma loja."
- **`motivo`** (e `paragens.<id>.motivo`): "Escolha um motivo: entrega, amostra, acompanhamento ou angariação."
- **`versao`:**
  - obrigatória (PATCH, recalcular, otimizar): "Indique a versão da rota que recebeu.";
  - no POST de paragens, presente mas inválida: "A versão da rota não é válida.".
- **`hora_saida`/`hora_regresso_limite`:**
  - vazia: "Indique a hora.";
  - formato: `janelas.MENSAGEM_FORMATO` ("A hora tem de estar no formato HH:MM.");
  - coerência (sobre os valores juntos com os guardados), em `hora_regresso_limite`: "A hora limite de regresso tem de ser depois da hora de saída.".
- **`evitar_portagens`** e **`paragens.<id>.manter_fechada`:** "Escolha sim ou não."
- **`inicio`/`fim`:**
  - não é `null` nem um objeto `{lat, lng}`: "Escolha a fábrica ou um ponto no mapa.";
  - lat/lng que não são números: "A latitude tem de ser um número." / "A longitude tem de ser um número.";
  - fora de Portugal continental: "Fora de Portugal".
- **`ordem`:** "A ordem tem de ser uma lista de paragens, sem repetidas." · contra a rota: "Esta paragem não está na rota."
- **`paragens`:**
  - não é um objeto: "Indique as alterações de cada paragem.";
  - `paragens.<id>` desconhecida: "Esta paragem não está na rota.";
  - `paragens.<id>` também em `retirar`: "Esta paragem vai ser retirada.";
  - `paragens.<id>.tempo_servico_min`: "O tempo de serviço é um número inteiro de minutos, de 1 a 240.";
  - `paragens.<id>.nao_cabe`: "Só se pode pôr de volta na rota."
- **`retirar`:** "Indique as paragens a retirar, sem repetidas." · contra a rota: "Esta paragem não está na rota."
- **`estado`:** "Só se pode marcar a rota como planeada."
- **Definições:**
  - `rota_hora_saida`/`rota_hora_regresso`: "Indique a hora no formato HH:MM.";
  - `rota_hora_regresso` (coerência): "A hora de regresso tem de ser depois da hora de saída.";
  - `servico_*_min`: "O tempo de serviço é um número inteiro de minutos, de 1 a 240."

**Rotas**

| Método e caminho | Corpo / parâmetros | Sucesso | Erros (pela ordem das verificações) |
|---|---|---|---|
| `GET /rotas` | `?de=&ate=` (por omissão hoje − 14 e hoje + 60) | 200 `{hoje, de, ate, rotas: [{id, data, estado, estado_efetivo, paragens}]}`, por `data` (`paragens` conta as ativas) | 422 (`de`, `ate`) |
| `GET /rotas/{data}` | — | 200 **Rota** (sem rota: virtual, `existe: false`) | 422 `data` |
| `GET /rotas/{data}/sugestoes` | — | 200 `{sem_paragens, no_caminho, grupos: [{fase, lojas: [{id, nome, fase, lat, lng, distancia_m, no_caminho}], mais}]}` | 422 `data` |
| `POST /rotas/{data}/paragens` | `{loja_id, motivo?, versao?}` | **201** Rota (cria a rota em `rascunho` se não existir; reativa uma paragem retirada) | 400 → 422 (`data`, corpo) → 404 "Loja não encontrada." → 409 `rota_fechada` → 409 `rota_em_curso` → 409 `conflito` (só com versão) → 409 `ja_na_rota` → 409 `rota_cheia` → escrita (sem versão: até 3 tentativas, depois 409 `conflito`) |
| `PATCH /rotas/{data}` | `{versao, hora_saida?, hora_regresso_limite?, inicio?, fim?, evitar_portagens?, ordem?: [ids], paragens?: {id: {motivo?, tempo_servico_min?, manter_fechada?, nao_cabe?: false}}, retirar?: [ids], estado?: "planeada"}` | 200 Rota (sem nada a mudar: 200 sem escrever) | 400 → 422 (`data`, corpo) → 404 "Ainda não há rota para este dia." → 409 `rota_fechada` → 409 `rota_em_curso` → 409 `conflito` → 422 contra a rota (ids, coerência das horas) → escrita condicional → falha: 404 / 409 `conflito` / 409 `rota_em_curso` |
| `POST /rotas/{data}/recalcular` | `{versao}` | 200 Rota com as horas (`calculo.atual: true`); a versão **não** muda; sem paragens incluídas: `calculo: null`, sem chamar o ORS | 400 → 422 → 404 → 409 `rota_fechada`/`rota_em_curso`/`conflito` → 503 `calculo_indisponivel` (nada muda) → falha da escrita: 404/409 |
| `POST /rotas/{data}/otimizar` | `{versao}` | 200 Rota com a ordem do VROOM, os `nao_cabe` e as horas; `versao + 1` | iguais ao recalcular; o VROOM e o Directions são tudo ou nada |
| `DELETE /lojas/{loja_id}` (alterada) | — | igual | + 409 `loja_em_rota`, depois do `loja_com_historico` |
| `GET`/`PATCH /definicoes` (alteradas) | + as 6 chaves das rotas | `{fabrica_morada, fabrica_lat, fabrica_lng, rota_hora_saida, rota_hora_regresso, servico_entrega_min, servico_amostra_min, servico_acompanhamento_min, servico_angariacao_min}`; os minutos como inteiros | + 422 da coerência das horas |

**Rota (API), por esta ordem de chaves:**
```
{id|null, data, existe, estado|null, estado_efetivo|null, editavel, versao|null, hoje,
 hora_saida, hora_regresso_limite, evitar_portagens,
 inicio: {lat, lng, fabrica: bool}, fim: {lat, lng, fabrica: bool},
 limite_paragens: 48, calculo_disponivel: bool (há CRM_ORS_CHAVE),
 calculo: null | {atual, distancia_m, duracao_s, regresso_previsto, depois_do_limite, geometria, calculado_em},
 paragens: [Paragem, …],        só as ativas, por `ordem`
 blocos_google: [{de, ate, quantas, rotulo, href}]}
Paragem = {id, loja_id, numero (1..k na secção "rota"; null nas outras), seccao: "rota"|"fechada"|"nao_cabe"|"sem_loja",
 ordem, motivo, tempo_servico_min, manter_fechada, nao_cabe, chegada_prevista, espera_min, fora_de_horario,
 aviso: "nenhum"|"fechada_neste_dia"|"nao_cabe"|"fora_de_horario", estado, resultado,
 links: null | {google, waze},
 loja: null | {nome, fase, lat, lng, telefone, janela1_inicio, janela1_fim, janela2_inicio, janela2_fim, dias_fechada}}
```
As horas guardadas só são as certas com `calculo.atual: true`; com `false` o ecrã mostra-as esbatidas, com "a recalcular".

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
cd "$RAIZ/backend" && .venv/bin/python -m pytest -q -p no:cacheprovider -rfEs > "$LOGS/pytest-tudo-F3.log" 2>&1; echo "saida=$?" >> "$LOGS/pytest-tudo-F3.log"
# Frontend: Jest (primeiro plano) e build (SEGUNDO PLANO, fora de frontend/build)
cd "$RAIZ/frontend" && CI=true ./node_modules/.bin/craco test --watchAll=false src/lib/crm
cd "$RAIZ/frontend" && BUILD_PATH="$LOGS/build" CI=false ./node_modules/.bin/craco build > "$LOGS/build-F3.log" 2>&1; echo "saida=$?" >> "$LOGS/build-F3.log"
# Simulador local do ORS (a partir da T3.13; SEGUNDO PLANO)
cd "$RAIZ/backend" && .venv/bin/python ors_simulado_local.py --porta 8013 > "$LOGS/ors-simulado.log" 2>&1
curl -s --max-time 3 http://127.0.0.1:8013/saude
```
Servidores locais, `preview_start` e como parar: dossiê §12.6. A pré-visualização da F2 pode estar a correr (8001/3000) com código velho; só se para na T3.43.

---

## 6. Tarefas

### Bloco F3.0 — Partida

#### [x] T3.0 Verificação de partida (15 min, sem commit)
- **Repositório:** `git -C "$RAIZ" status --porcelain` só mostra `?? HANDOFF/`; `branch --show-current` = `crm-purple-house`; `log --oneline -1` mostra `d195610` (ou o commit deste plano). `test ! -e "$RAIZ/backend/.env"`.
- **Contagens de partida** para comparar no fecho:
  - `pytest tests/crm`: na F2 deu 2925 passed e 27 skipped;
  - Jest `src/lib/crm`: 29 suites e 1035 testes;
  - registar os números de hoje em `$LOGS/t3.0-partida.txt`.
- **Ambiente:**
  - `grep -c "^CRM_ORS" "$RAIZ/backend/.env.local"` → `0` (só a contagem);
  - `grep -rn "openrouteservice" "$RAIZ/backend/crm"` → só docstrings;
  - `lsof -ti tcp:8001`, `tcp:3000` e `tcp:8013`: registar, sem parar nada.
- **Feito (2026-10-11, sem commit; registo em `$LOGS/t3.0-partida.txt`):**
  - **Repositório:** `status --porcelain` só `?? HANDOFF/`; ramo `crm-purple-house`; topo `97a4f05` (o commit deste plano); `backend/.env` não existe.
  - **Contagens de partida:** `pytest tests/crm` **2925 passed, 27 skipped** em 16 s (`t3.0-pytest-crm.log`), igual à F2. Jest `src/lib/crm` **29 suites, 1035 testes** (`t3.0-jest-crm.log`), igual. Suite completa do backend em segundo plano (`pytest-tudo-T3_0.log`, 153 s), porque a T3.14 compara com ela: **6477 passed, 0 failed, 30 skipped** (27 do `test_mongo_local.py` sem `CRM_MONGO_TESTE_URL` + os 3 de sempre do `test_o_contrato_com_a_app.py:130`), com os 6 avisos de sempre. É este o "skipped da T3.0" (30) e o "hoje 30/27" das correções T3.25/T3.43.
  - **Ambiente:** `grep -c "^CRM_ORS" backend/.env.local` → 0; `openrouteservice` em `backend/crm` só na docstring de `crm/servicos/__init__.py:5`; `CRM_ORS` no `.env.example` → 0; `asyncio.run(` em `tests/crm` → 0.
  - **Portas** (só registadas): 8001 a escutar pelo `Python` da pré-visualização do backend e 3000 pelo `node` do frontend (ambos deixados a correr); 8013 livre para o simulador da T3.13. O `lsof -ti` sem `-sTCP:LISTEN` também mostra o processo do Claude (ligações do painel do browser): não é um servidor e não se para.
  - **Desvios:** nenhum. Esta nota e o `[x]` ficam por guardar até ao commit da T3.1, que os leva junto (a T3.0 não tem commit).

### Bloco F3a — Domínio puro (backend)

#### [x] T3.1 Relógio: "hoje" em Lisboa e datas `AAAA-MM-DD` (30 min)
- **Ficheiros:** `backend/crm/relogio.py`, `backend/crm/dominio/datas.py`, `backend/tests/crm/test_relogio.py`, `backend/tests/crm/test_dominio_datas.py`.
- **Teste primeiro.** Falha por `ImportError: cannot import name 'hoje' from 'crm.relogio'` e por `ModuleNotFoundError: crm.dominio.datas`.
  - `relogio.hoje()`, com `relogio.agora` parado:
    - 2026-10-10T22:59:59Z → `date(2026,10,10)`; 23:00:00Z → 2026-10-11 (WEST);
    - 2026-10-25T00:59:59Z → 2026-10-25; 2026-10-25T23:30:00Z → 2026-10-25 (WET);
    - 2026-03-29T23:30:00Z → 2026-03-30; 2026-12-31T23:59:59Z → 2026-12-31;
    - o mesmo com outro `TZ` no processo (`monkeypatch.setenv("TZ", "Asia/Tokyo")` + `time.tzset()`).
  - `ler_data`:
    - aceita `"2026-10-12"` e `"2028-02-29"`;
    - devolve `None` para `"2026-02-29"`, `"2026-13-01"`, `"2026-1-5"`, `"20261012"`, `" 2026-10-12"`, `"2026-10-12\n"`, `"２０２６-10-12"`, `"٢٠٢٦-10-12"`, `"0000-01-01"`, `None`, `20261012`, `True` e `["2026-10-12"]`.
  - `texto_data(date(2026,1,5)) == "2026-01-05"` e a ida e volta é sem perda.
  - `dia_da_semana(date(2026,10,12)) == "seg"` … `date(2026,10,18)` → `"dom"` (usa `campos_loja.DIAS`).
  - `somar_dias(date(2026,10,30), 3) == date(2026,11,2)`.
  - `MAXIMO_DIAS_FUTURO == 365`.
- **Implementação:**
  - `relogio.FUSO_LISBOA = ZoneInfo("Europe/Lisbon")`; `hoje()` = `agora().astimezone(FUSO_LISBOA).date()`;
  - `datas.py` usa `re.fullmatch(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")` + `date(...)` dentro de `try`;
  - nunca `isoformat`, `strftime` nem `today` (o `test_instantes_gravados.py` varre o AST).
- **Mutações mínimas (5):** a data em UTC em vez de Lisboa; `\d`; `match` em vez de `fullmatch`; `weekday()` desfasado de 1; aceitar o ano 0.
- **Verificar:** os 2 ficheiros, depois a bateria `tests/crm` (inclui o `test_instantes_gravados.py`).
- **Commit:** `CRM: dia de hoje em Lisboa e datas das rotas`
- **Feito (2026-10-11):** aplicada a correção "T3.1": os 10 casos de `hoje()` correm também com o fixture `fuso_de_toquio` já existente no `test_relogio.py` (fica lá; nenhum `monkeypatch.setenv("TZ", …)` em `tests/crm`). Vermelho por `ImportError: cannot import name 'FUSO_LISBOA' from 'crm.relogio'` (o primeiro nome do import; `hoje` falta pelo mesmo motivo) e `ModuleNotFoundError: No module named 'crm.dominio.datas'` (`t3.1-vermelho.log`). Verde com 96 testes novos: 25 no `test_relogio.py` e 71 no `test_dominio_datas.py` (`t3.1-verde.log`, 194 nos 2 ficheiros). Bateria `tests/crm`: **3021 passed, 27 skipped** (2925 + 96), 18 s, os 6 avisos de sempre (`t3.1-bateria-crm.log`).
  - **Decisões fixadas pelos testes:**
    - `hoje()` = `_em_utc(None).astimezone(FUSO_LISBOA).date()`: um `agora()` sem fuso dá `ValueError`, como no `instante()`; devolve `date` (nunca `datetime`). Casos extra: o último microssegundo do ano, a meia-noite do ano novo, 00:59:59Z a 29 de março (ainda WET), um `agora` com outro desvio, e uma propriedade independente do `ZoneInfo` (nov.–fev. = dia UTC; abr.–set. = dia de UTC + 1 h; 4000 instantes de 2000 a 2040).
    - `ler_data` só aceita `str` (uma `date` do Python, bytes, `False`, `2026.10` e `{"$gt": ""}` → `None`); recusa também 1900-02-29, 31 de abril, dia 0/32, mês 0, sinais, 5 algarismos no ano, um instante, barras, semana ISO, NUL e espaço no fim. Aceita de `0001-01-01` a `9999-12-31`.
    - `texto_data` por f-string com largura fixa (`0999-01-02`); ida e volta e "o texto ordena como as datas" em 3000 dias aleatórios (o `$gte`/`$lte` do `GET /rotas`).
    - `dia_da_semana` = `campos_loja.DIAS[weekday()]`, com a semana inteira, a propriedade "+1 dia = dia seguinte de `DIAS`" e os domingos das mudanças de hora. `somar_dias` com 0, negativos, mudança de ano, 29 de fevereiro e 365 dias.
    - Varrimento AST do `datas.py`: nem `fromisoformat` (no Python 3.11 aceita "20261012"), `strptime`, `strftime`, `isoformat`, `today` nem `now`.
  - **Mutações (8):** as 5 mínimas (UTC em vez de Lisboa; `\d`; `match`; `weekday()` + 1; ano 0 aceite com `max(ano, 1)`) e 3 extra (o fuso do processo com `astimezone()`, apanhada só pelos casos de Tóquio; `date.fromisoformat`; `agora()` sem verificar o fuso). Todas apanhadas, ficheiros repostos conferidos com `cmp` (`t3.1-mutacoes.log`, script `t3.1-mutacoes.py`).
  - **Desvios:** nenhum além da correção aplicada. O commit leva também o `[x]` e a nota "Feito" da T3.0.

#### [x] T3.2 Domínio: horas em segundos e janelas para o otimizador (40 min)
- **Ficheiros:** `backend/crm/dominio/horas.py`, `backend/tests/crm/test_dominio_horas.py`.
- **Teste primeiro.** Falha por `ModuleNotFoundError: crm.dominio.horas`.
  - `segundos`: `"08:00"` → 28800, `"00:00"` → 0, `"23:59"` → 86340. `"02:30"` → 9000: uma hora que não existe a 2026-03-29 em Lisboa conta pelo texto do relógio. `"8:00"`, `""`, `None` e `"24:00"` → `ValueError` (validação por `janelas.hora`).
  - `hora_de_segundos`: arredonda o minuto meio-para-longe-do-zero (`arredondar`), por isso 30 600 → "08:30", 1770 → "00:30" (29,5 min) e 1769 → "00:29". Dá `None` para ≥ 86 370 (≥ 24:00 depois de arredondar), negativos, NaN, inf e bool.
  - `minutos_de_segundos(89.9) == 1` e `minutos_de_segundos(0) == 0`.
  - `janelas_em_segundos([])` → `None` (sem restrição); `[{inicio:"10:00",fim:"13:00"},{inicio:"15:00",fim:"19:00"}]` → `[(36000,46800),(54000,68400)]`.
  - `janelas_vroom`:
    - `None, 600` → `None`;
    - `[(36000,46800)], 600` → `[[36000, 46200]]`;
    - uma janela mais curta do que o serviço sai;
    - todas fora → `[]`;
    - `b − s == a` fica (`[[a, a]]`);
    - devolve listas novas.
  - Varrimento AST: `horas.py` não importa `datetime` nem `zoneinfo` (as horas nunca passam por instantes).
- **Mutações (5):** `h*60`; `>` em vez de `>=` no `b − s`; o `round` do Python (1770 → "00:30" passa a "00:30", mas 1830 → "00:30" em vez de "00:31"; o caso 1830 é obrigatório); o limite em 1440 minutos antes de arredondar; `[]` confundido com `None`.
- **Commit:** `CRM: horas da rota em segundos desde a meia-noite local`
- **Feito (2026-10-11, pelo agente da T3.6):** o agente da T3.2 falhou sem deixar ficheiros nem commit; a T3.6 precisa do `janelas_em_segundos` e do `janelas_vroom` (regra 1: cada tarefa assume as anteriores), por isso a T3.2 fez-se primeiro, com o seu próprio commit. Vermelho por `ModuleNotFoundError: No module named 'crm.dominio.horas'` (`t3.2-vermelho.log`). Verde com **135 testes** no `test_dominio_horas.py` (`t3.2-verde.log`). Bateria `tests/crm`: **4191 passed, 27 skipped** (4056 + 135), 17 s, os 6 avisos de sempre (`t3.2-bateria-crm.log`).
  - **Decisões fixadas pelos testes:**
    - `segundos` aceita exatamente o que o `janelas.hora` aceita (a propriedade corre as 1440 horas do dia e os casos estragados): `""`/`None` (que o `janelas.hora` deixa passar como "vazia") dão `ValueError`, como "8:00", "24:00", " 08:00", algarismos árabes/largos, números, bool, listas e bytes. Devolve `int`.
    - `hora_de_segundos`: `int(arredondar(s / 60))` e só depois o limite (`≥ 1440` → `None`); 86 369 → "23:59", 86 370 → `None`; o meio minuto vai sempre para cima (todos os minutos pares + 30 s); ida e volta sem perda nas 1440 horas; propriedade com 3000 segundos ao acaso (semente fixa) contra a conta só com inteiros `(s + 30) // 60`. `None` também para negativos (−0,5, −29…), NaN, ±inf, bool, texto, `None` e listas (é `e_numero_json`): nunca rebenta, porque uma chegada depois da meia-noite é um caso normal.
    - `minutos_de_segundos`: o mesmo arredondamento (150 s → 3; o `round` dava 2), sem limite superior; um negativo, NaN, inf, bool ou não-número é `ValueError` (uma espera negativa é um erro de programação).
    - `janelas_em_segundos(lista)` valida pelo `validador_loja.campos_de_janelas` (só o que o `janelas_para_lista` grava: `None`, texto, janelas a meio, sobrepostas, fora de ordem, com chaves a mais ou 3 janelas → `ValueError`); `[]` → `None`; devolve `[(início_s, fim_s)]` numa lista nova e não muda a da base.
    - `janelas_vroom(janelas_s, servico_s)`: o serviço é um inteiro ≥ 0 (vê-se antes do `None`: `True`, `600.0`, NaN e texto → `ValueError`); as janelas, pares de inteiros (tuplos ou listas; floats, bool, texto e outros tamanhos → `ValueError`); devolve listas novas `[[a, b − s]]` (`list`, não `tuple`), só com `b − s ≥ a`; `[]` fica `[]` (nunca `None`).
    - Varrimento AST: o `horas.py` não importa `datetime`, `zoneinfo`, `time` nem `pytz`, e nunca chama o `round`.
  - **Mutações (15):** as 5 mínimas (`h*60`; `>` no `b − s`; o `round` na hora, apanhado pelo 1830; o limite das 1440 antes de arredondar, apanhado pelo 86 370; `[]` → `[]` no `janelas_em_segundos`) e 10 extra (o `janelas_vroom` a trocar `[]` por `None`; o `round` nas esperas; negativos aceites na hora; bool aceite na hora; a janela do VROOM sem subtrair o serviço; janelas em tuplos; as janelas da base sem validação; bool no tempo de serviço; espera negativa aceite; hora vazia como meia-noite). Todas apanhadas à 1.ª, o ficheiro reposto conferido com `cmp` e `shasum` (`t3.2-mutacoes.log`, script `t3.2-mutacoes.py`, com `PYTHONDONTWRITEBYTECODE=1`).
  - **Desvios:** feita fora da ordem (depois da T3.5), pela razão acima. Nenhum outro.

#### [x] T3.3 Domínio: regras da rota — motivos, prioridades, secções, estado ao ler e caminhos de escrita (55 min)
- **Ficheiros:** `backend/crm/dominio/rotas.py`, `backend/crm/dominio/ids.py`, `backend/tests/crm/test_dominio_rotas.py`.
- **Teste primeiro.** Falha por `ModuleNotFoundError`.
  - **Constantes:** `MOTIVOS == ("entrega", "amostra", "acompanhamento", "angariacao")`, numa só linha (consistência na T3.27). `MOTIVO_POR_FASE` cobre as 5 fases da T2.1 (`motivo_por_fase` de uma desconhecida → `"angariacao"`).
  - **Prioridades:** `prioridade("entrega") == 100`; as outras dão 1; `LIMITE_PARAGENS * PRIORIDADE_OUTRAS < PRIORIDADE_ENTREGA`.
  - **`estado_efetivo(estado, data, hoje)`:** um dia anterior a hoje dá sempre `"concluida"` (também com `None` e `"em_curso"`); hoje e o futuro devolvem o `estado`.
  - **`bloqueio_de_escrita(rota|None, data, hoje)`:**
    - passado → `"rota_fechada"`;
    - `estado` fora de `ESTADOS_EDITAVEIS` ou alguma paragem (mesmo retirada) com `estado ∈ ("feita","nao_feita")` → `"rota_em_curso"`;
    - senão `None`.
  - **`ativas(paragens)`:** sem as retiradas, por `ordem`, e no empate pela posição na lista.
  - **`fechada_neste_dia(loja, data)`:** `["seg"]` a 2026-10-12 dá `True`, a 2026-10-13 dá `False`; uma loja sem dias dá `False`.
  - **`seccoes(ativas, lojas_por_id, data)` → `[(paragem, loja, seccao, numero)]`:**
    - `"sem_loja"` (loja `None`) → `"fechada"` (fechada e sem `manter_fechada`) → `"nao_cabe"` → `"rota"`;
    - a numeração 1..k só na secção `"rota"`, pela `ordem`.
  - **`nova_ordem(ativas, ids)`:** as listadas primeiro; as ativas em falta a seguir, pela ordem relativa delas (leniente). Um id desconhecido → `ValueError`.
  - **`aviso`:** fechada → `fechada_neste_dia`; `nao_cabe`; `fora_de_horario` (só com o cálculo atual); senão `nenhum`.
  - **`servico_padrao(motivo, definicoes)`:** lê `definicoes[f"servico_{motivo}_min"]`.
  - **`caminhos_paragem(3, {"ordem": 0, "motivo": "amostra"})`** → `{"paragens.3.ordem": 0, "paragens.3.motivo": "amostra"}`. `ValueError` com um campo do terreno (`estado`, `resultado`, `concluida_em`), com um campo desconhecido, com um índice negativo ou `bool`, e com o campo `"id"` ou `"loja_id"` (imutáveis).
  - **Os dois conjuntos de campos** (`CAMPOS_DO_TERRENO` e `CAMPOS_DO_ESCRITORIO`) são disjuntos.
  - **`ids.e_uuid4`:** usa o mesmo objeto de padrão que `validador_loja._UUID4` (`is`).
- **Mutações (7):** a prioridade 2 nas visitas; `<=` no passado; uma retirada com registo a não bloquear; a numeração a contar as fechadas; `caminhos_paragem` a aceitar `estado`; `nova_ordem` estrita; um motivo errado para `contactada`.
- **Commit:** `CRM: regras das rotas — motivos, prioridades e secções`
- **Feito (2026-10-11):** aplicadas as correções "T3.3 / T3.16" e "T3.3 (ativas com ordem nula)": `ativas` ordena pela chave `(ordem is None, ordem if ordem is not None else 0, posição)`, testada com uma paragem retirada e reposta pelo motorista (`removida_em None`, `ordem None`, `estado "feita"`); a frase "a F3 lê esse formato" entrou já no dossiê §5.13 (a T3.43 junta-a ao contrato completo). Vermelho por `ModuleNotFoundError: No module named 'crm.dominio.rotas'` (`t3.3-vermelho.log`). Verde com **222 testes** no `test_dominio_rotas.py` (`t3.3-verde.log`). Bateria `tests/crm`: **3243 passed, 27 skipped** (3021 + 222), 17 s, os 6 avisos de sempre (`t3.3-bateria-crm.log`).
  - **Decisões fixadas pelos testes:**
    - `MOTIVOS` num tuplo, numa só linha do código (o teste lê o ficheiro); `MOTIVO_POR_FASE` é um `MappingProxyType` com as chaves pela `fases.ORDEM`; `motivo_por_fase` de uma fase desconhecida, ou que nem é texto (lista, objeto, número, bool), dá `"angariacao"` sem rebentar.
    - `PRIORIDADE_ENTREGA = 100`, `PRIORIDADE_OUTRAS = 1`, `LIMITE_PARAGENS = 48`; `prioridade` e `servico_padrao` de um motivo fora dos `MOTIVOS` dão `ValueError` (erro de programação: os motivos gravados passaram pelo validador).
    - `ESTADOS = ("rascunho", "planeada", "em_curso", "concluida")`, `ESTADOS_EDITAVEIS = ("rascunho", "planeada")` e `ESTADOS_COM_REGISTO = ("feita", "nao_feita")` (o `$nin` do `rotas_bd`). `estado_efetivo` e `bloqueio_de_escrita` só aceitam `datetime.date` nos dois dias (`type(x) is date`): texto, `datetime` ou `None` → `TypeError`, mesmo quando os dois se deixavam comparar. `bloqueio_de_escrita`: passado → `rota_fechada` (antes de tudo, com ou sem rota); sem rota → `None`; estado fora dos editáveis (também `None`/desconhecido) ou um registo em qualquer paragem, mesmo retirada → `rota_em_curso`.
    - `ativas` devolve uma lista nova com as mesmas paragens (sem cópia); `seccoes` e `nova_ordem` passam a lista por `ativas` (as retiradas saem, a ordem é a das ativas, idempotente), por isso aceitam também a lista inteira. `seccoes` → `[(paragem, loja, seccao, numero)]`, com a loja de `lojas_por_id` (o mesmo objeto) e a precedência `sem_loja` → `fechada` (sem `manter_fechada`) → `nao_cabe` → `rota`; uma fechada com "Manter" e `nao_cabe` fica `nao_cabe`.
    - `aviso(paragem, seccao, calculo_atual)` decide pela secção: `fechada` → `fechada_neste_dia` (com "Manter" a paragem está na secção `rota` e o aviso sai), `nao_cabe` → `nao_cabe`, `fora_de_horario` só na secção `rota` e com o cálculo atual; `sem_loja` → `nenhum`; uma secção desconhecida → `ValueError`. Constantes `SECCOES` e `AVISOS`.
    - `nova_ordem(paragens, ids)` devolve **ids** (lista nova): os pedidos e depois as ativas em falta pela ordem delas; um id desconhecido, de uma retirada ou repetido → `ValueError`.
    - `CAMPOS_IMUTAVEIS = ("id", "loja_id")`; os três conjuntos são disjuntos e juntos dão as 16 chaves da paragem do §3. `caminhos_paragem` recusa (sem escrever nada) os campos do terreno, os imutáveis, os desconhecidos (subcampos, operadores, `client_uuid`), um índice negativo, `bool`, texto, decimal, `None` ou posicional (`"$"`, `"$[]"`) e `campos` que não é um `dict`; `{}` → `{}`; guarda a ordem das chaves e os próprios valores.
    - `ids.PADRAO_UUID4` é o `validador_loja._UUID4` importado (o `_UUID4` fica no sítio, numa linha, porque o `ids.test.js` o lê do ficheiro). Como o `re.compile` guarda os padrões em cache, uma cópia com o mesmo texto passava no `is`: um varrimento AST garante que o `ids.py` não importa `re` nem compila nada.
  - **Mutações (20):** as 7 mínimas e 13 extra (comparar `None` com `int` no `ativas`; as nulas no início; sem desempate pela posição; `fora_de_horario` sem o cálculo atual; `nao_cabe` antes de `fechada`; fechada mesmo com "Manter"; índice `bool` aceite; dias em texto aceites; `servico_padrao` sem validar o motivo; `motivo_por_fase` a rebentar com uma lista; uma cópia do padrão uuid4 no `ids.py`; `match` em vez de `fullmatch`; o bloqueio a ignorar o estado da rota). Todas apanhadas, ficheiros repostos conferidos com `cmp` (`t3.3-mutacoes.log`, script `t3.3-mutacoes.py`). Na 1.ª passagem sobreviveram 2 extra (dias em texto dos dois lados; a cópia do padrão, pela cache do `re`), que levaram os testes "os dois em texto"/"os dois com hora" e o varrimento do `ids.py`.
  - **Desvios:** a T3.2 (horas) ficou por fazer (o agente falhou sem deixar ficheiros nem commit); a T3.3 não usa o `horas.py`, por isso seguiu. Nenhum outro além das correções aplicadas.

#### [x] T3.4 Domínio: validação dos pedidos às rotas (60 min)
- **Ficheiros:** `backend/crm/dominio/validador_rota.py`, `backend/tests/crm/test_dominio_validador_rota.py`.
- **Teste primeiro** (falha por `ModuleNotFoundError`). As mensagens são as do §4.
  - **`data_do_caminho(texto, hoje)`** → `(date|None, erros)`: o formato e o horizonte de 365 dias (o passado é válido aqui; o 409 vem depois).
  - **`intervalo(de, ate, hoje)`:** por omissão −14/+60; `ate < de`; mais de 120 dias.
  - **`adicao(corpo)`** → `({loja_id, motivo|None, versao|None, com_versao}, erros)`:
    - `versao` em falta → `com_versao: False`;
    - `versao` `null` → `(None, True)`;
    - `versao` inteiro ≥ 1 → `(n, True)`;
    - `0`, `-1`, `1.0`, `True`, `"1"` e `2**63` → erro.
  - **`alteracao(corpo)`** → `(dados, erros)`:
    - erros pela ordem `versao, hora_saida, hora_regresso_limite, inicio, fim, evitar_portagens, ordem, paragens…, retirar, estado`; as chaves desconhecidas ignoram-se;
    - `inicio {lat: 38.7223445, lng: -9.1393}` arredonda meio-para-longe-do-zero às 6 casas e só depois vê Portugal; `{lat: True}` é recusado; chaves a mais no ponto ignoram-se;
    - a `ordem` aceita uuid4 sem repetidos; maiúsculas, repetidos, não-lista e não-uuid → erro;
    - `paragens` com chaves não-uuid → erro;
    - o tempo de serviço `0`, `241`, `10.0`, `True` e `"10"` → erro, e `1` e `240` passam;
    - `manter_fechada "true"` → erro; `nao_cabe: true` → erro;
    - `estado "rascunho"` → erro;
    - um id em `paragens` e em `retirar` → erro em `paragens.<id>`;
    - o corpo não muda e cada chamada devolve estruturas novas.
  - **`so_versao(corpo)`** (recalcular/otimizar): a versão é obrigatória.
  - **`coerencia_horas("08:00", "08:00")`** → erro em `hora_regresso_limite`; `"08:00"/"08:01"` passa.
- **Mutações (6):** `bool` aceite como inteiro; a ordem dos erros trocada; a coerência com `<=`; repetidos aceites na ordem; o arredondamento do Python; Portugal antes de arredondar.
- **Commit:** `CRM: validação dos pedidos às rotas`
- **Feito (2026-10-11):** aplicada a correção "T3.4 / T3.20 (retirar e ordem no mesmo PATCH)": no `alteracao`, os ids de `retirar` saem da `ordem` (`{ordem: [a, b, c], retirar: [b]}` → `ordem [a, c]`, `retirar [b]`, sem erro); a parte da T3.20 (`b` com `ordem: None` e `removida_em`, `a`/`c` com 0 e 1) fica para lá. Vermelho por `ModuleNotFoundError: No module named 'crm.dominio.validador_rota'` (`t3.4-vermelho.log`). Verde com **358 testes** no `test_dominio_validador_rota.py` (`t3.4-verde.log`); a 1.ª passagem do verde teve 4 falhas do próprio teste (`A.upper()` de um uuid só com algarismos é igual a `A`), trocado por `C.upper()`. Bateria `tests/crm`: **3601 passed, 27 skipped** (3243 + 358), 17 s, os 6 avisos de sempre (`t3.4-bateria-crm.log`).
  - **Decisões fixadas pelos testes:**
    - Todas devolvem `(dados, erros)` com `{campo: mensagem}` do §4 (constantes `MENSAGEM_*` no módulo, testadas contra o texto escrito à mão no teste) e estruturas novas; o corpo nunca muda. Um corpo que não é `dict` (o `corpo_json` já o garante) ou um `hoje` que não é `datetime.date` (`type(x) is date`: `datetime`, texto ou `None`) → `TypeError`.
    - `data_do_caminho(texto, hoje)` → `(date, {})` ou `(None, {"data": …})`: formato por `datas.ler_data`; o último dia aceite é hoje + 365 (2027-03-01 + 365 = 2028-02-29); o passado lê-se.
    - `intervalo(de, ate, hoje)` → `((de, ate), {})` ou `(None, erros)`. Só `None` (o parâmetro em falta) é a omissão, cada um por si (−14/+60); `?de=` vazio é erro de formato. `ate == de` é válido (um dia); `ate < de` → `ate` "O fim do intervalo…"; o máximo conta **os dois extremos** (`(ate − de).days + 1 > 120` → `ate` "O intervalo tem no máximo 120 dias."): de 2026-10-01 a 2027-01-28 (120 dias) passa e até 2027-01-29 (121) não, por isso o "121 dias" da T3.18 dá 422 nas duas leituras. Os dois mal escritos → `de` e depois `ate`; com um mal escrito não se comparam. Sem horizonte nos dias do intervalo.
    - `adicao(corpo)` → sempre as 4 chaves `loja_id, motivo, versao, com_versao` (um valor com erro fica `None`); erros pela ordem `loja_id, motivo, versao`. `loja_id` por `ids.e_uuid4` ("Escolha uma loja."); `motivo` em falta ou `null` → `None`, `""` e o resto fora dos `MOTIVOS` → erro; `versao` em falta → `(None, False)`, `null` → `(None, True)`, inteiro de 1 a 2⁶³−1 → `(n, True)`; `0`, `-1`, `1.0`, `True`, `False`, `"1"`, `2**63`, `[1]`, `{"$gt": 0}`, NaN e inf → "A versão da rota não é válida." com `com_versao: True`.
    - `so_versao(corpo)` → `({"versao": n}, {})` ou `({}, {"versao": "Indique a versão da rota que recebeu."})` (também com `null` e qualquer valor inválido: uma só mensagem no PATCH/recalcular/otimizar, como no §4). O `alteracao` usa-a.
    - `alteracao(corpo)`: dados e erros pela ordem `CHAVES_ALTERACAO` (`versao, hora_saida, hora_regresso_limite, inicio, fim, evitar_portagens, ordem, paragens, retirar, estado`), com os `paragens.<id>…` no lugar de `paragens` e pela ordem do corpo; seja qual for a ordem do corpo, a mesma ordem. Um valor com erro não entra nos dados; as chaves desconhecidas ignoram-se.
      - horas: `""`/`null` → "Indique a hora."; o resto por `janelas.hora`. O `alteracao` **não** compara as horas entre si: a rota junta-as com as guardadas e chama `coerencia_horas` (422 "contra a rota").
      - `inicio`/`fim`: `null` → `None`; um não-objeto (lista, texto, número, bool) → "Escolha a fábrica ou um ponto no mapa."; a latitude vê-se primeiro (`True`, texto, `null`, em falta, NaN, inf → "A latitude…"), depois a longitude; arredondadas às 6 casas por `numeros.arredondar` (38.7223445/−9.1393005 → 38.722345/−9.139301; o `round` daria 38.722344/−9.1393) e só depois Portugal (42.2000004/−9.6000004 passa como 42.2/−9.6; 42.2000005 → 42.200001 → "Fora de Portugal"); devolve um `{lat, lng}` novo, só com essas duas chaves e em `float`.
      - `evitar_portagens` e `paragens.<id>.manter_fechada`: só `bool` ("Escolha sim ou não.").
      - `ordem`/`retirar`: listas novas de uuid4 sem repetidos; os uuid4 veem-se antes dos repetidos (um `[[a]]` nunca chega ao `set`: erro e não `TypeError`); `[]` é válido.
      - `paragens`: um não-objeto ou **uma** chave que não é uuid4 → erro só em `paragens` (sem repetir a chave no erro) e nada nos dados; as alterações de uma paragem que não são objeto → `paragens.<id>` "Indique as alterações de cada paragem."; um id que também vem em `retirar` (contado mesmo com o `retirar` mal feito, pelos uuid4 da lista) → `paragens.<id>` "Esta paragem vai ser retirada." e fica de fora; por paragem só `motivo, tempo_servico_min, manter_fechada, nao_cabe`, por esta ordem (os campos do terreno, `ordem`, `id`, `loja_id`, as horas… ignoram-se); `{id: {}}` fica `{id: {}}`. Tempo por `e_inteiro_json` de 1 a 240 (`0`, `241`, `10.0`, `True`, `"10"`, `null`, `2**63` → erro); `nao_cabe` só `False`.
      - `estado`: só `"planeada"`.
    - `coerencia_horas(saida, regresso)` → `{"hora_regresso_limite": …}` quando `regresso <= saida` (a mesma hora é erro), senão `{}`; horas que não são "HH:MM" válidas → `ValueError`.
    - Constantes para as tarefas seguintes: `MENSAGEM_NAO_ESTA_NA_ROTA` (T3.20), `TEMPO_SERVICO_MINIMO/MAXIMO` e `MENSAGEM_TEMPO_SERVICO` (iguais ao texto do §4 para as definições da T3.5), `INTERVALO_DIAS_ANTES/DEPOIS`, `INTERVALO_MAXIMO_DIAS`. Um varrimento AST garante que o módulo nunca chama `round`; 3000 corpos ao acaso (semente fixa) dão só mensagens conhecidas, nunca exceções, e não mudam o corpo.
  - **Mutações (24):** as 6 mínimas (`bool` aceite na versão; `fim` antes de `inicio` nos erros; a coerência com `<`; repetidos aceites na ordem; o `round` do Python; Portugal antes de arredondar) e 18 extra (o retirar a não sair da ordem; `nao_cabe: true` aceite; tempo 241; `bool` no tempo; o horizonte com `>=`; o intervalo sem contar os dois extremos; o intervalo de um dia recusado; `?de=` vazio como omissão; `versao: null` igual a sem versão; motivo `""` aceite; uma paragem em `retirar` alterada na mesma; campos do terreno a passar; a lista do corpo devolvida tal e qual; o ponto com as chaves a mais; `hoje` `datetime` aceite; uuid em maiúsculas; `so_versao` a aceitar `null`; a coerência sem validar as horas). Todas apanhadas à 1.ª, o ficheiro reposto conferido com `cmp` e `shasum` (`t3.4-mutacoes.log`, script `t3.4-mutacoes.py`, que corre com `PYTHONDONTWRITEBYTECODE=1`).
  - **Desvios:** nenhum além da correção aplicada. A T3.2 (horas) continua por fazer; a T3.4 não precisa dela (a coerência compara o texto "HH:MM", de largura fixa).

#### [x] T3.5 Domínio: definições das rotas (45 min)
- **Ficheiros:** `backend/crm/dominio/definicoes.py`, `backend/tests/crm/test_dominio_definicoes.py`.
- **Teste primeiro.** Falha porque `PADROES` só tem 3 chaves (o teste que fixa os `PADROES` exatos passa a ter 9).
  - **`PADROES`, por esta ordem:** `fabrica_morada, fabrica_lat, fabrica_lng, rota_hora_saida "08:00", rota_hora_regresso "19:00", servico_entrega_min "10", servico_amostra_min "10", servico_acompanhamento_min "15", servico_angariacao_min "15"`.
  - **`combinar`:** devolve as horas em texto e os minutos como `int`. Um valor guardado estragado volta ao padrão, sem rebentar: `"8:00"`, `""`, `"abc"`, `"0"`, `"241"`, `"10.5"`, `" 10"`, `"٣"`.
  - **`alteracao`:**
    - horas por `janelas.hora`, não vazias;
    - minutos por `e_inteiro_json`, de 1 a 240, guardados como `str(n)`;
    - as mensagens do §4;
    - os 33 casos do `DefinicoesTest` continuam verdes (só a tabela dos padrões muda).
  - **`coerencia(valores_em_vigor)`** → `{"rota_hora_regresso": "A hora de regresso tem de ser depois da hora de saída."}` quando saída ≥ regresso.
- **Mutações (4):** os minutos devolvidos em texto; aceitar 0; o padrão a não repor um valor estragado; a coerência com `<`.
- **Commit:** `CRM: horas e tempos de serviço das rotas nas definições`
- **Feito (2026-10-11):** aplicada a correção "T3.5 / T3.15": além do domínio, o `test_definicoes.py` (`PADROES`/`PADROES_TEXTO` com as 9 chaves e os minutos em `int`; os dicionários exatos passam a `{**PADROES, …}` e as listas de chaves a `CHAVES`) e as linhas 798–799 do `test_mongo_local.py`. O `crm/definicoes.py` não muda de código (o `em_vigor` usa o `combinar` tal e qual): só os docstrings, que diziam 3 chaves. Vermelho com os `PADROES` de 3 chaves (`test_os_padroes_sao_as_nove_chaves_pela_ordem_do_ecra`: "Right contains 6 more items, first extra item: ('rota_hora_saida', '08:00')"), mais os `KeyError`/"Esta definição não existe." das chaves novas e os 422/GET da API: 473 failed, 194 passed nos 2 ficheiros (`t3.5-vermelho.log`; o `coerencia` lê-se do módulo dentro de cada teste para o vermelho não ser um ImportError). Verde: **667 passed** nos 2 ficheiros (`t3.5-verde.log`; o domínio passou de 137 para 571 testes e a API de 75 para 96). Bateria `tests/crm`: **4056 passed, 27 skipped** (3601 + 455), 17 s, os 6 avisos de sempre (`t3.5-bateria-crm.log`). Ensaio no MongoDB local com `CRM_MONGO_TESTE_URL`: **44 passed** (`t3.5-mongo-local.log`). O GET com 9 chaves e o PATCH das chaves novas (`{"rota_hora_saida": "07:30"}` grava e devolve; `{"servico_entrega_min": 0}` → 422; `instantes_fora_do_formato` vazio) ficam verdes aqui; a **T3.15 fica só com a coerência no PATCH**, com o vermelho da correção (não há nenhum teste que fixe o "grava sem coerência").
  - **Decisões fixadas pelos testes:**
    - `PADROES` com as 9 chaves pela ordem da tarefa, todas em texto; `HORAS` e `MINUTOS` com as chaves das rotas. `[f"servico_{m}_min" for m in rotas.MOTIVOS] == MINUTOS` e `rotas.servico_padrao` dá `int` com `combinar({})`.
    - `combinar`: as horas em texto e os minutos como `int`; cada valor das rotas estragado volta ao **seu** padrão, sem rebentar. Só se lê de volta o texto que a `alteracao` grava: horas por `janelas.hora` (não vazias) e minutos por `fullmatch([1-9][0-9]{0,2})` de 1 a 240. Voltam ao padrão `"8:00"`, `""`, `"abc"`, `"0"`, `"241"`, `"10.5"`, `" 10"`, `"٣"`, `"+10"`, `"010"`, `"1_0"`, `"１０"`, `"10\n"`, `"24:00"`, `" 08:00"`… e também os valores que não são texto (`None`, bool, `20`, `20.0`, listas): ao contrário das coordenadas (o `(float)` do PHP, que lê um número escrito à mão e dá `TypeError` com o resto), as chaves das rotas não vêm do autónomo e um número à mão (o mongosh grava double) conta como estragado. Uma propriedade com 3000 textos ao acaso (semente fixa) confirma: aceite ⇔ canónico.
    - `alteracao`: horas "HH:MM" tal e qual; vazia, `null` e mal escrita dão a mesma mensagem "Indique a hora no formato HH:MM." (§4); minutos por `e_inteiro_json` de 1 a 240, guardados como `str(n)` (`0`, `241`, `10.0`, `True`, `"10"`, `null`, `2**63`, NaN, inf → "O tempo de serviço é um número inteiro de minutos, de 1 a 240."). Com erro, o valor é `""` (como as coordenadas), por isso os valores são sempre texto. A `alteracao` **não** compara as horas entre si. Erros pela ordem dos `PADROES` e depois as desconhecidas; os 33 casos do `DefinicoesTest` continuam verdes. Ida e volta: os minutos 1..240 e as 1440 horas do dia.
    - `MENSAGEM_TEMPO_SERVICO` é o próprio objeto do `validador_rota` (importado, testado com `is`), com os mesmos `TEMPO_SERVICO_MINIMO/MAXIMO`; `MENSAGEM_HORA` e `MENSAGEM_COERENCIA` são as do §4.
    - `coerencia(valores)` só lê `rota_hora_saida` e `rota_hora_regresso` (as definições em vigor juntas com o pedido) → `{"rota_hora_regresso": "A hora de regresso tem de ser depois da hora de saída."}` com saída ≥ regresso (a mesma hora é erro; 23:59 → 00:00 também), senão `{}`; uma hora em falta ou que não é "HH:MM" válida → `ValueError`. Devolve sempre um dicionário novo e não muda o que recebe.
  - **Mutações (16):** as 4 mínimas (os minutos em texto no `combinar`; aceitar 0; a hora estragada sem voltar ao padrão; a coerência com `<`) e 12 extra (o `int()` do Python nos minutos guardados; `bool` aceite; 241 aceite; hora vazia aceite; minutos gravados como `int`; a coerência sem validar as horas; uma cópia da mensagem do tempo de serviço; a ordem dos `PADROES` trocada; todos os minutos estragados a voltar a 10; a hora guardada aparada; um valor das rotas que não é texto a rebentar; a `alteracao` a comparar as horas). Todas apanhadas à 1.ª, o ficheiro reposto conferido com `cmp` e `shasum` (`t3.5-mutacoes.log`, script `t3.5-mutacoes.py`, com `PYTHONDONTWRITEBYTECODE=1`).
  - **Desvios:** os docstrings do `crm/definicoes.py` (ficheiro da T3.15) atualizados já aqui, porque o GET passa a devolver as 9 chaves neste commit; nenhum código mudou lá. O dossiê §5.9/§6 ainda descreve só a fábrica: fica para a T3.15/T3.43. A T3.2 (horas) continua por fazer.

#### [x] T3.6 Domínio: pedido ao otimizador (VROOM) sem dados pessoais e leitura da resposta (60 min)
- **Ficheiros:** `backend/crm/dominio/vroom.py`, `backend/tests/crm/test_dominio_vroom.py`, `backend/tests/crm/fixtures/ors/{cenarios.json, otimizacao-todas.json, otimizacao-uma-nao-cabe.json}`.
- **Fixtures escritas à mão** (`"_origem": "manual — regravar"`):
  - `cenarios.json`, só com pontos públicos de Lisboa:
    - fábrica 38.722300, −9.139300;
    - Praça do Comércio 38.707500, −9.136400;
    - Marquês de Pombal 38.725300, −9.150000;
    - Torre de Belém 38.691600, −9.216000;
    - mais as janelas, os serviços, a saída e o limite.
  - `otimizacao-todas.json`: `code: 0`, uma rota com `steps` `start`, `job 2`, `job 1`, `job 3`, `end`.
  - `otimizacao-uma-nao-cabe.json`: `unassigned: [{id: 3, location: […]}]`.
- **Teste primeiro.** Falha por `ModuleNotFoundError`.
  - **`paragem_calculo(paragem, loja)`** → `ParagemCalculo(id, lat, lng, servico_s, janelas_s, motivo)`. Só lê `lat`, `lng`, `janelas`, `tempo_servico_min` e `motivo`.
  - **`pedido_otimizacao(paragens, inicio, fim, saida_s, limite_s)`** → `PedidoOtimizacao(corpo, por_job, impossiveis)`:
    - `corpo == {"jobs": [...], "vehicles": [{"id": 1, "profile": "driving-car", "start": [lng, lat], "end": [lng, lat], "time_window": [saida_s, limite_s]}]}`;
    - os ids dos *jobs* são `int` de 1 a n, pela ordem recebida;
    - `location` é `[lng, lat]` às 6 casas;
    - `service` em segundos (`int`);
    - `priority` 100/1;
    - `time_windows` só quando há janelas;
    - uma paragem com `janelas_vroom == []` vai para `impossiveis` e **não** é enviada;
    - sem *jobs* → `corpo is None`.
  - **Sem dados pessoais** (o teste de canários):
    - a partir de lojas completas com `nome "CANARIO-NOME"`, `telefone "+351912345678"`, `morada "Rua CANARIO"`, `pessoa_contacto`, `notas`, uuids da loja, da paragem e do membro, `json.dumps(corpo)` não contém nenhum deles;
    - lista branca recursiva das chaves: topo `{jobs, vehicles}`, job `{id, location, service, time_windows, priority}`, veículo `{id, profile, start, end, time_window}`;
    - o único texto é `"driving-car"`;
    - todos os outros valores são números.
  - **`interpretar_otimizacao(resposta, por_job)`** → `(ordem: [paragem ids], nao_atribuidas: [paragem ids])`:
    - lê as duas fixtures;
    - levanta `RespostaInvalida(motivo)` com: não ser objeto; `code` ≠ 0; `routes` que não é lista; mais de 1 rota; `vehicle` ≠ 1; `steps` que não é lista; um *job* desconhecido, repetido ou com id `bool`; atribuídos ∪ não atribuídos ≠ enviados.
- **Mutações (6):** `[lat, lng]`; o uuid como id do *job*; mandar as impossíveis; a janela sem subtrair o serviço; a prioridade 1 na entrega; aceitar um *job* em falta.
- **Commit:** `CRM: pedido ao otimizador só com coordenadas e números`
- **Feito (2026-10-11):** feita depois da T3.2 (commit próprio, `horas.py`), de que depende. Aplicadas as correções "T3.6 / T3.22", "T3.6" e "T3.6 / T3.22 (VROOM sem rotas e zero jobs)" (a parte da T3.6: `routes: []` com todos em `unassigned` → `([], todos)`; os passos com `id` e `job`) e a parte da "T3.12 / T3.43" que toca nas fixtures desta tarefa (os testes sobre as fixtures só veem a forma e os conjuntos; a ordem 2, 1, 3 vem de respostas escritas no próprio teste). Vermelho por `ModuleNotFoundError: No module named 'crm.dominio.vroom'` (`t3.6-vermelho.log`). Verde com **189 testes** no `test_dominio_vroom.py` (`t3.6-verde.log`). Bateria `tests/crm`: **4380 passed, 27 skipped** (4191 + 189), 17 s, os 6 avisos de sempre (`t3.6-bateria-crm.log`).
  - **Fixtures** (`tests/crm/fixtures/ors/`): `cenarios.json` com os 4 pontos públicos da tarefa (`pontos`) e a secção `otimizacao` com os 2 cenários (início/fim pelo nome do ponto, saída, limite e paragens `{ponto, motivo, tempo_servico_min, janelas}` no formato da base); o `_origem` diz "manual — cenários do gravador (T3.12); …, nunca se regravam" (é a entrada do gravador, não uma resposta). No "todas", a entrega na Praça do Comércio só recebe a partir das 09:00 (daí a ordem Marquês → Comércio → Belém); no "uma-nao-cabe", a Torre de Belém só recebe das 08:00 às 08:20 com 15 min de serviço (janela do VROOM 08:00–08:05, que cabe mas é inalcançável a ~8 km). As respostas (`otimizacao-todas.json`, `otimizacao-uma-nao-cabe.json`, `"_origem": "manual — regravar"`) têm a forma do ORS (`code`, `summary`, `unassigned`, `routes[0].steps`), com os passos de job `{"type": "job", "id": n, "job": n, location, setup, service, waiting_time, arrival, duration, violations}`, os de início/fim sem `id`/`job`, e o não atribuído `{"id": 3, "type": "job", "location": […]}`. Os testes montam o pedido de cada cenário como o gravador o fará (o id da paragem é o nome do ponto) e verificam: lista branca do pedido, `_origem` "manual — regravar" ou "gravado em ", atribuídos ∪ não atribuídos = enviados e disjuntos, nenhum de fora no "todas" e só a Torre de Belém no "uma-nao-cabe" (conjuntos, não a ordem).
  - **Decisões fixadas pelos testes:**
    - `ParagemCalculo(id, lat, lng, servico_s, janelas_s, motivo)` e `PedidoOtimizacao(corpo, por_job, impossiveis)` são `NamedTuple`. `paragem_calculo` lê só `id`, `tempo_servico_min` e `motivo` da paragem e `lat`, `lng` e `janelas` da loja (provado com um dicionário que regista as chaves lidas e rebenta se for percorrido); `servico_s = min × 60` (`int`), coordenadas em `float`, `janelas_s` por `horas.janelas_em_segundos` (`[]` → `None`). Um id que não é texto, um tempo fora de 1..240 (`bool`, `10.0`, `"10"`), um motivo fora dos `MOTIVOS`, coordenadas que não são números do JSON ou janelas estragadas → `ValueError`.
    - `pedido_otimizacao(paragens, inicio, fim, saida_s, limite_s)`: `inicio`/`fim` são pares `(lat, lng)` (tuplo ou lista; um `{lat, lng}`, texto, NaN, inf ou bool → `ValueError`), como o `pedido_direcoes` da T3.7; `saida_s`/`limite_s` inteiros de 0 a 86 399 com a saída antes do limite (senão `ValueError`). Os *jobs* pela ordem recebida, com ids **contíguos 1..n só sobre os enviados** (as impossíveis saltam-se e não gastam número); chaves `id, location, service, priority` e `time_windows` só com janelas; `location`/`start`/`end` em `[lng, lat]` por `numeros.arredondar` às 6 casas (38,7223445/−9,1393005 → 38,722345/−9,139301; o `round` dava 38,722344/−9,1393). Uma paragem repetida → `ValueError`; o que não é `ParagemCalculo` → `TypeError`. Sem *jobs* (nenhuma, ou só impossíveis) → `PedidoOtimizacao(None, {}, impossíveis)`. Estruturas novas a cada chamada; as paragens não mudam.
    - **Canários:** lojas completas feitas pelo `validador_loja.criacao` + `formatar.documento_loja` (nome, telefone, morada, código postal, localidade, pessoa de contacto, notas, região) e paragens completas do §3 (uuids da paragem, da loja e do membro, `adicionada_em`): o `json.dumps` do corpo não tem nenhum (nem em minúsculas); lista branca recursiva (topo `{jobs, vehicles}`, job ⊆ `{id, location, service, time_windows, priority}` com os 4 obrigatórios, veículo = `{id, profile, start, end, time_window}`), o único texto é `"driving-car"` e o resto são números finitos (nunca `bool`). Um meta-teste prova que a lista branca apanha uma chave ou um texto a mais, um id em texto, uma prioridade `bool` e um NaN.
    - `interpretar_otimizacao(resposta, por_job)` → `(ordem, nao_atribuidas)`, listas novas; os não atribuídos **pela ordem do pedido** (número do job), não pela da resposta. Estrito: `code` tem de ser o `int` 0 (`False`, `0.0`, `"0"` e em falta → inválido); `routes` lista com 0 ou 1 rota; a rota um objeto com `vehicle` o `int` 1 (`True`, `1.0` → inválido); `steps` lista de objetos; `start`/`end` ignoram-se (mesmo com ids); `job` lê o `id` e só sem ele o `job`, os dois têm de ser `int` e iguais (também quando, trocados entre passos, cada um dava uma ordem válida); outro tipo (`break`, `pickup`, `delivery`, `""`, em falta) → inválido; `unassigned` obrigatório e lista de objetos com `id` inteiro e, se vier, `type` `"job"`; um job desconhecido, repetido (nos passos, nos não atribuídos ou nos dois) ou em falta → inválido. Ids `bool`/`float` recusados (têm o mesmo hash do inteiro e apanhavam um job do `por_job`). As chaves desconhecidas (`_origem`, `summary`, `geometry`…) ignoram-se.
    - `RespostaInvalida(motivo)` (subclasse de `Exception`, `str(e) == e.motivo`) fica no `vroom.py`; o motivo é sempre um texto fixo do módulo, sem nada da resposta (canários de texto e coordenadas nas respostas estragadas), e é lançada sem `__cause__`. A T3.7 importa-a daqui.
    - Varrimento AST: o `vroom.py` nunca chama o `round`.
  - **Mutações (28):** as 6 mínimas (`[lat, lng]`; o uuid da paragem como id do job; mandar as impossíveis; a janela sem subtrair o serviço; a prioridade 1 na entrega; aceitar um job em falta) e 22 extra (ler `routes[0]`; o `job` antes do `id`; o `id` e o `job` sem comparar; o `break` ignorado; o veículo `True`; o `code` `False`/`0.0`; ids `bool`/`float`; os não atribuídos pela ordem da resposta; o `round` nas coordenadas; `time_windows: None`; paragens repetidas; ids a contar as impossíveis; início e fim trocados; o tipo dos não atribuídos sem verificar; `unassigned` em falta como `[]`; mais de uma rota; a saída depois do limite; o motivo sem validar; `bool` no tempo; o id da paragem como `description`; a loja sem janelas; um job desconhecido ignorado). Todas apanhadas, o ficheiro reposto conferido com `cmp` e `shasum` (`t3.6-mutacoes.log`, script `t3.6-mutacoes.py`, com `PYTHONDONTWRITEBYTECODE=1`). Antes da passagem juntou-se o teste "o `id` e o `job` trocados entre passos", porque com um só passo diferente a mutação "o `job` antes do `id`" caía na regra dos repetidos.
  - **Desvios:** a T3.2 feita primeiro, num commit próprio (ver a nota dela). O ponto no rio do `direcoes-erro-2010` (correção "T3.12 / T3.43") fica para a T3.7, que cria os cenários do Directions no mesmo `cenarios.json` (uma secção `direcoes` ao lado de `otimizacao`). Nenhuma rota nem código de erro novos (o meta-teste da proteção e o `erros.py` não mudam); nada para o [DONO].

#### [x] T3.7 Domínio: pedido ao Directions, troços e polyline (50 min)
- **Ficheiros:** `backend/crm/dominio/{directions,polilinha}.py`, `backend/tests/crm/test_dominio_{directions,polilinha}.py`, `fixtures/ors/{direcoes-tres-paragens.json, direcoes-erro-2010.json}`.
- **Teste primeiro.** Falha por `ModuleNotFoundError`.
  - **`pedido_direcoes([(lat,lng)…], evitar_portagens)`**:
    - sem portagens a evitar: `{"coordinates": [[lng,lat]…], "instructions": True, "geometry": True, "elevation": False, "units": "m"}`, sem `options`;
    - com elas: mais `"options": {"avoid_features": ["tollways"]}`;
    - menos de 2 pontos → `ValueError`;
    - canários e lista branca, como na T3.6 (textos permitidos: `"m"` e `"tollways"`).
  - **`interpretar_direcoes(resposta, n_pontos)`** → `Trocos(duracoes, distancias, distancia_m: int, duracao_s: int, geometria)`:
    - lê `routes[0].segments[i].duration/distance` e `routes[0].summary`;
    - `RespostaInvalida` com: `segments` ≠ `n_pontos − 1`; números negativos, não finitos ou `bool`; `geometria` que não é texto ou não se descodifica em ≥ 2 pontos; sem `routes`.
  - **`polilinha.descodificar`**:
    - o exemplo da Google `"_p~iF~ps|U_ulLnnqC_mqNvxq`@"` → `[(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]`;
    - `""` → `[]`;
    - um pedaço cortado ou um carácter fora de 63..126 → `ValueError`;
    - `precisao=6`.
- **Mutações (4):** `[lat,lng]` nas coordenadas; `avoid_features` sempre; aceitar `segments` a menos; a polyline sem o sinal (`~(v>>1)`).
- **Commit:** `CRM: pedido ao Directions e leitura dos troços da rota`
- **Feito (2026-10-11):** aplicadas as correções "T3.7 (+ T3.13, T3.21)" (a parte da T3.7: as chaves `distance`/`duration` em falta contam 0, presentes têm de ser números ≥ 0, sem `summary` os totais são a soma; a fixture `direcoes-ponto-repetido.json`), "T3.7 / T3.9 / T3.13 / T3.21" (o `polilinha.codificar` nasce aqui) e a parte da "T3.12 / T3.43" que toca nesta tarefa (o `rio_tejo` no `cenarios.json`; os testes sobre as fixtures só veem a forma). Vermelho por `ModuleNotFoundError: No module named 'crm.dominio.polilinha'` e `'crm.dominio.directions'` (`t3.7-vermelho.log`). Verde com **85 testes** no `test_dominio_polilinha.py` e **161** no `test_dominio_directions.py` (+ os 189 do `test_dominio_vroom.py`, 435 ao todo, `t3.7-verde.log`). Bateria `tests/crm`: **4626 passed, 27 skipped** (4380 + 246), 17 s, os 6 avisos de sempre (`t3.7-bateria-crm.log`).
  - **Fixtures** (`tests/crm/fixtures/ors/`): `cenarios.json` ganha o ponto `rio_tejo` (38,72, −9,035, no Mar da Palha, a mais de 1,5 km de estradas, pontes e cais; o teste da T3.6 que fixa os pontos passou a incluí-lo) e a secção `direcoes` com `direcoes-tres-paragens` (fábrica → Marquês → Comércio → Belém → fábrica, a ordem do VROOM no `otimizacao-todas`) e `direcoes-erro-2010` (fábrica → Marquês → `rio_tejo` → fábrica), cada um com os nomes dos pontos pela ordem e `evitar_portagens`. As respostas `direcoes-tres-paragens.json` e `direcoes-erro-2010.json` (`"_origem": "manual — regravar"`) têm a forma do ORS v2 (`routes[0]` com `summary`, `segments` com `steps`, `bbox`, `geometry`, `way_points`; `metadata.query`; o erro `{"error": {"code": 2010, "message": "…specified coordinate 2: …"}, "info": …}`); os `steps` de chegada já vêm sem distance/duration, como o ORS faz com os zeros. `direcoes-ponto-repetido.json` (fábrica → Comércio → Comércio → fábrica) é manual para sempre (`_origem` "manual — não se regrava…"): o 2.º troço só traz os `steps`. As geometrias foram codificadas com um codificador independente (rascunho fora do repositório) e conferem com o `polilinha`.
  - **Decisões fixadas pelos testes:**
    - `vroom._ponto` passou a público, `vroom.ponto_ors` (o mesmo código; os testes da T3.6 não mudam): o `pedido_direcoes` usa-o, por isso as coordenadas vão às 6 casas por `numeros.arredondar`, como no VROOM.
    - `pedido_direcoes(pontos, evitar_portagens)`: `pontos` lista ou tuplo de pares `(lat, lng)` (outra coisa, incluindo um gerador ou um texto → `TypeError`); `evitar_portagens` só `bool` (`1`, `None`, `"true"` → `ValueError`); de 2 a 50 pontos (`directions.MAXIMO_PONTOS == rotas.LIMITE_PARAGENS + 2`), senão `ValueError`; chaves pela ordem `coordinates, instructions, geometry, elevation, units` e `options` só a evitar portagens; estruturas novas a cada chamada. Canários com as lojas e paragens completas do teste da T3.6 (importadas de `test_dominio_vroom.py`) e lista branca recursiva: só os textos `"m"` e `"tollways"`, exatamente 3 booleanos (`instructions`, `geometry`, `elevation`) e 2 números finitos por coordenada; um meta-teste prova que a lista branca apanha 12 estragos (chave, `language`, `units` "km", `instructions: 1`, opção a mais, texto nas opções ou nas coordenadas, NaN, bool, uma só coordenada, um uuid).
    - `interpretar_direcoes(resposta, n_pontos)` → `Trocos(duracoes, distancias, distancia_m, duracao_s, geometria)` (`NamedTuple`): por troço `float` (0.0 quando a chave falta; `-0.0` conta 0), totais `int` por `numeros.arredondar` (7000,5 → 7001; o `round` dava 7000), do `summary` quando existe (mesmo diferente da soma) e senão `math.fsum` dos troços; a geometria volta tal como veio. Estrito: `routes` lista com **exatamente uma** rota; `segments` lista de `n_pontos − 1` objetos (a menos ou a mais → inválido); um número presente tem de passar o `e_numero_json` e ser ≥ 0 (bool, NaN, ±inf, texto, `null`, lista, 2**1100 → inválido), no troço e no resumo; `summary: null` ou que não é objeto → inválido (só a chave em falta conta 0); a geometria tem de ser texto e descodificar-se em ≥ 2 pontos. `n_pontos` fora de 2..50 (ou `bool`, `4.0`, `"4"`) → `ValueError`. A `RespostaInvalida` é a do `vroom.py` (o mesmo objeto), com motivos fixos do módulo e lançada fora de qualquer `except` (`__cause__` e `__context__` `None`; canários de texto e coordenadas nas respostas estragadas). O corpo de um erro do ORS (`{"error": …}`) é "sem rota" → inválido.
    - `polilinha.descodificar(texto, precisao=5)` → lista nova de tuplos `(lat, lng)` em `float` (inteiro ÷ 10^precisão, exato para o exemplo da Google). Estrito: um carácter fora de 63..126 (também os que, sem a verificação, davam um par completo, como `"\x7f\x7f"`), um valor cortado a meio, uma latitude sem longitude e um valor com mais de 12 blocos (60 bits; sem limite, um texto só de continuações crescia ao quadrado) → `ValueError`; o que não é texto → `TypeError`; `precisao` inteiro de 0 a 10 (`bool`, `5.0` → `ValueError`).
    - `polilinha.codificar(pontos, precisao=5)`: pares em tuplos ou listas (outra coisa → `TypeError`), números do JSON dentro de ±90/±180 (senão `ValueError`), arredondados meio-para-longe-do-zero pelo texto do número, como o `numeros.arredondar` (38,7223445 às 6 casas → 38,722345; o `round` dava 38,722344 e o `int` cortava). Ida e volta: 1000 pontos ao acaso no mundo a 1e-5, e exata para pontos a 5 casas (Portugal) e a 6 casas (`precisao=6`), também com pontos repetidos.
    - Varrimento AST: nem o `directions.py` nem o `polilinha.py` chamam o `round`.
  - **Mutações (37):** as 4 mínimas (`[lat, lng]` nas coordenadas; `avoid_features` sempre; aceitar `segments` a menos; a polyline sem o sinal ao descodificar), as 2 das correções ("exigir as chaves" nos troços e no resumo; o `~` dos negativos esquecido ao codificar) e 31 extra (o resumo sem `_medida`; sem `summary` a 0; ignorar o `summary`; negativos; bool/NaN/inf; `segments` a mais; duração e distância trocadas; mais de uma rota; geometria de 1 ponto; geometria sem descodificar; a falha dentro do `except`; o `round` nos totais; `evitar_portagens` "verdadeiro"; 1 ponto; 51 pontos; pontos num texto; um troço que não é objeto ignorado; `summary: null` como em falta; `instructions: false`; a precisão ignorada; carácter fora de 63..126; valor cortado; latitude sem longitude; sem limite de blocos; limite desfasado; o corte e o `round` ao codificar; sem as diferenças; sem verificar o mundo; bool nas coordenadas; `precisao` bool). Todas apanhadas, os ficheiros repostos conferidos com `cmp` e `shasum` (`t3.7-mutacoes.log`, script `t3.7-mutacoes.py`, com `PYTHONDONTWRITEBYTECODE=1`). A do `~` ao codificar foi apanhada também só pelos testes da polyline, por 8 asserções (`t3.7-mutacao6-so-polilinha.log`), e não só pelo `GEOMETRIA` do teste do Directions, que rebenta ao importar. Antes da passagem juntaram-se 4 amostras de carácter fora de 63..126 que dão um par completo, porque as primeiras falhavam todas também por outro motivo (cortadas ou com um número ímpar de valores).
  - **Desvios:** o `vroom.py` (T3.6) só mudou o nome do `_ponto` para `ponto_ors`, com docstring; o `test_dominio_vroom.py` só ganhou o `rio_tejo` no teste que fixa os pontos dos cenários. O limite de 50 pontos e o de 12 blocos não estavam no texto da tarefa. Nenhuma rota nem código de erro novos (o meta-teste da proteção e o `erros.py` não mudam); nada para o [DONO].

#### [x] T3.8 Domínio: chegadas, esperas, avisos e assinatura do cálculo (60 min)
- **Ficheiros:** `backend/crm/dominio/horarios.py`, `backend/tests/crm/test_dominio_horarios.py`.
- **Teste primeiro.** Falha por `ModuleNotFoundError`. `calcular_horarios(saida_s, limite_s, paragens, duracoes)` → `Horarios(por_paragem={id: {chegada_prevista, espera_min, fora_de_horario}}, regresso_s, regresso_previsto, depois_do_limite)`. Cenários com saída às 08:00:
  1. Sem janelas, troços [1800, 900, 1200] e serviços [600, 600] → 08:30 e 08:55, regresso 09:25, sem espera.
  2. Janela 10:00–13:00 e chegada às 09:10 → espera 50.
  3. Duas janelas (10–13, 15–19) e chegada às 13:10 → espera 110, sem aviso.
  4. Chegada às 12:55 com 10 min de serviço: não cabe na 1.ª (13:05 > 13:00) → espera pela 2.ª (125 min).
  5. Chegada às 12:50 com 10 min → cabe (13:00 ≤ 13:00).
  6. Chegada às 19:00 com as janelas a acabar às 19:00 → `fora_de_horario`, espera 0, serve-se à chegada.
  7. Regresso às 19:40 com limite 19:00 → `depois_do_limite`, `regresso_previsto "19:40"`.
  8. Chegada depois das 24:00 → `chegada_prevista None`, `fora_de_horario True`, `regresso_previsto None`, `depois_do_limite True`.
  9. Arredondamento: 30,5 min depois das 08:00 → "08:31"; 29,4 → "08:29".
  10. `len(duracoes) != len(paragens) + 1` → `ValueError`.
  11. Mudança de hora: `entrada_calculo` e `calcular_horarios` dão o mesmo para rotas a 2026-03-29, 2026-10-25 e 2026-10-24 (a data não entra nas horas).
- **`entrada_calculo(rota, incluidas_com_lojas, inicio, fim)`** → `{"v": 1, "saida", "limite", "inicio": ["%.6f","%.6f"], "fim": […], "evitar_portagens", "paragens": [[id, "%.6f" lat, "%.6f" lng, servico_min, [[ini,fim]…]]]}`.
- **`assinatura(entrada)`** = `"sha256:" + sha256(json.dumps(entrada, sort_keys=True, separators=(",",":"), ensure_ascii=False))`:
  - muda com a ordem, uma coordenada na 6.ª casa, o serviço, uma janela, a saída, o limite, o início, o fim e as portagens;
  - **não** muda com o nome, o telefone, as notas, nem com o motivo quando o serviço é igual.
- **Mutações (7):** `<` em vez de `<=` no "cabe"; janelas reduzidas (fim − serviço) usadas nas horas; não esperar pela 2.ª janela; `fora_de_horario` com espera; `>=` no limite; a assinatura sem a ordem; o `round` do Python.
- **Commit:** `CRM: horas de chegada, esperas e avisos a partir dos troços`
- **Feito (2026-10-11):** nenhuma linha das correções refere a T3.8. Vermelho por `ModuleNotFoundError: No module named 'crm.dominio.horarios'` (`t3.8-vermelho.log`). Verde com **131 testes** no `test_dominio_horarios.py` (`t3.8-verde.log`; a 1.ª passagem teve 1 falha do próprio teste, uma chegada às 06:00 com a saída às 08:00, trocada por 08:10). Bateria `tests/crm`: **4757 passed, 27 skipped** (4626 + 131), 18 s, os 6 avisos de sempre (`t3.8-bateria-crm.log`); `asyncio.run(` em `tests/crm` → 0.
  - **Decisões fixadas pelos testes:**
    - `Horarios(por_paragem, regresso_s, regresso_previsto, depois_do_limite)` (`NamedTuple`); `por_paragem` pelo id da paragem, pela ordem recebida, cada uma `{chegada_prevista: "HH:MM"|None, espera_min: int, fora_de_horario: bool}` por esta ordem; `regresso_s` em `float` (pode passar de 86 400).
    - `calcular_horarios(saida_s, limite_s, paragens, duracoes)`: `paragens` são `vroom.ParagemCalculo` (outra coisa → `TypeError`), `duracoes` as do `Trocos.duracoes` (uma a mais do que as paragens, senão `ValueError`; listas ou tuplos, senão `TypeError`; cada uma um número do JSON ≥ 0). `saida_s`/`limite_s` inteiros de 0 a 86 399; **não** se exige saída < limite (o limite só decide o aviso; quem o garante é o validador, e o VROOM é que rebenta). Paragem repetida, serviço que não é inteiro ≥ 0 e janelas que não são pares de inteiros → `ValueError` (pelo `horas.janelas_vroom`). Sem paragens (`[d]`) é só a ida e volta.
    - **O "cabe"** é a regra do VROOM: `horas.janelas_vroom` dá `[abertura, último início]` e o serviço começa no momento mais cedo possível (`min` sobre as janelas, por isso não depende da ordem da lista); `início + serviço ≤ fim` cabe (12:50 + 10 min numa janela até às 13:00), um segundo depois já não (espera pela 2.ª, 130 min).
    - **`fora_de_horario`** quando nenhuma janela leva o serviço **ou** a chegada é a partir das 24:00 (também sem janelas, "com o aviso" do §1); serve-se à chegada, `espera_min` 0, mesmo antes da abertura de uma janela mais curta do que o serviço. As 24:00 contam depois de arredondar (86 369 s → "23:59"; 86 370 s → `None`).
    - **A espera** é a diferença entre os minutos mostrados (`minutos_de_segundos(início) − minutos_de_segundos(chegada)`), e não a espera em bruto arredondada: 09:56:30 → "09:57" e espera 3 (em bruto, 3,5 → 4), por isso a chegada mostrada mais a espera dá sempre a abertura (propriedade com 2000 chegadas ao acaso, semente fixa).
    - **`depois_do_limite`** pelo minuto mostrado: `regresso_previsto is None or segundos(regresso_previsto) > limite_s` (19:00:20 → "19:00" e não passa das 19:00; 19:00:30 → "19:01" e passa; às 19:00 certas não passa).
    - **Contas exatas:** os troços somam-se como `Fraction(repr(d))` (o número tal como se escreve, como o `numeros.arredondar`) e só se passa a `float` para mostrar. Dois testes com a armadilha verificada no próprio teste: 982,3 + 600 + 814,1 + 600 + 93,6 depois das 08:00 dá 08:51:30 → "08:52" (em float, 31 889,999… → "08:51"); uma 3.ª paragem a chegar às 09:40 certas (em float, 09:40:00,000…01) com 10 min numa janela até às 09:50 cabe.
    - A fixture `direcoes-ponto-repetido.json` (troço sem duração entre duas lojas nas mesmas coordenadas) lida pelo `interpretar_direcoes` dá chegadas seguidas ("08:06", "08:16"), sem espera.
    - **`entrada_calculo(rota, incluidas_com_lojas, inicio, fim)`** → `{"v": 1, "saida": s, "limite": s, "inicio": [lat, lng], "fim": [lat, lng], "evitar_portagens": bool, "paragens": [[id, lat, lng, serviço_min, [[início_s, fim_s]…]]…]}`: as horas em segundos (`horas.segundos`); as coordenadas em texto com 6 casas **depois do `numeros.arredondar`** (38,7223445 → "38.722345" e −9,1393005 → "-9.139301"; o "%.6f" sozinho e o `round` davam 38.722344 e -9.139300); as janelas de receção em segundos (`[]` = sem restrição). `incluidas_com_lojas` são pares `(paragem, loja)` (listas/tuplos; outra coisa → `TypeError`), lidos pelo `vroom.paragem_calculo` (que valida o tempo, o motivo, as coordenadas e as janelas). Da rota só lê `hora_saida`, `hora_regresso_limite` e `evitar_portagens` (provado com o `_Lido`): nunca a data. `evitar_portagens` só `bool`; uma hora ou um ponto estragado → `ValueError`. Sem canários no JSON (nomes, telefones, notas, membro, região, ids das lojas, datas, motivos); os ids das paragens entram (a assinatura nunca sai do servidor).
    - **`assinatura(entrada)`** = `"sha256:" + sha256(json.dumps(…, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False))` em UTF-8; fixada pelo JSON canónico escrito à mão e por uma assinatura literal (`ASSINATURA_FIXA`); NaN → `ValueError`, o que não é `dict` → `TypeError`. Muda com a ordem, a 6.ª casa da latitude e da longitude, o serviço, uma janela (a mais, a menos ou mudada), a saída, o limite, o início, o fim, o início e o fim trocados, as portagens, o id e uma paragem a menos; não muda com o nome, o telefone, as notas, a fase, os dias fechada, o motivo com o mesmo serviço, os outros campos da paragem, a data e o resto da rota, a 7.ª casa, pontos em lista ou tuplo.
    - **Cenário 11:** a 2026-03-29, 2026-10-25 e 2026-10-24, com saídas 00:30, 01:30 e 08:00, a entrada, a assinatura e as horas são iguais; 00:30 + 30 min = "01:00" e + 10 + 30 min = "01:40" (pelo texto do relógio). Varrimento AST: o `horarios.py` não importa `datetime`, `zoneinfo`, `time`, `pytz` nem o `relogio`, e nunca chama o `round`.
  - **Mutações (32):** as 7 mínimas (`<` no "cabe"; as janelas reduzidas usadas como de receção; não esperar pela 2.ª janela; `fora_de_horario` a esperar pela abertura; `>=` no limite; a assinatura sem a ordem; o `round` do Python, em duas: nos minutos da espera e nas coordenadas, corridas **sem** o varrimento AST, apanhadas pelos testes de comportamento) e 24 extra (a soma em float; a chegada como o início do serviço; a espera em bruto; a 1.ª janela da lista em vez da mais cedo; depois das 24:00 sem aviso; o limite pelos segundos em bruto; o regresso sem o último troço; sem verificar o número de troços; o motivo, a data, sem as portagens, sem o id, sem as janelas e o início/fim trocados na entrada; `sort_keys`, escapes e espaços na assinatura; o "%.6f" sem arredondar; paragens repetidas; durações negativas; portagens 0/1; servir sempre à chegada; a saída sem validar; o serviço fora da partida). Todas apanhadas à 1.ª, o ficheiro reposto conferido com `cmp` e `sha256` (`t3.8-mutacoes.log`, script `t3.8-mutacoes.py`, com `PYTHONDONTWRITEBYTECODE=1`).
  - **Desvios:** nenhum além das decisões acima (a espera pelos minutos mostrados, o limite pelo minuto mostrado, a soma exata e a saída depois do limite aceite não estavam no texto da tarefa). Nenhuma rota nem código de erro novos (o meta-teste da proteção e o `erros.py` não mudam); nada para o [DONO].

#### [ ] T3.9 Domínio: sugestões perto (5 km) e no caminho (3 km) (50 min)
- **Ficheiros:** `backend/crm/dominio/sugestoes.py`, `backend/tests/crm/test_dominio_sugestoes.py`.
- **Teste primeiro.** Falha por `ModuleNotFoundError`. `sugerir(lojas, lojas_das_paragens, ids_na_rota, data, linha=None)`:
  - **Sem paragens:** `{"sem_paragens": True, "no_caminho": False, "grupos": []}`.
  - **Grupos e ordenação:**
    - só `contactada`, depois `potencial`; cada grupo pela distância, depois `chave_comparacao(nome)`, depois `id`;
    - a 5000 m exatos entra (`≤`) e a 5000,5 m não;
    - a distância é a mínima a qualquer paragem ativa (`geo.distancia_metros`), em `distancia_m` `int` (meio-para-longe-do-zero).
  - **Excluídas:** perdida, amostra, cliente, fechada nesse dia da semana, já na rota (ativas), sem coordenadas.
  - **Corredor** (`linha` = a polyline descodificada, só com `calculo.atual`):
    - entra uma loja a 8 km das paragens e a 2,9 km da linha (`no_caminho: True`, `distancia_m` = a distância à linha);
    - a 3,1 km não entra;
    - uma loja perto pelos dois lados fica com a menor distância e `no_caminho False`;
    - o resultado leva `no_caminho: True`.
  - **Limite:** 30 por grupo, com `mais = N − 30`.
  - **`distancia_a_linha`:** perpendicular a um troço (a projeção equirretangular local dá ±1 % contra a haversine até 5 km); a ponta de um troço; um troço degenerado (dois pontos iguais); a rejeição por caixa nunca deixa de fora um ponto dentro de 3 km (100 pontos aleatórios contra a força bruta).
- **Medição (não versionada, `t3.9-medicao.log`):** 1000 lojas contra uma linha de 5000 pontos em < 1 s no Mac. Se passar, simplificar a linha antes (Douglas–Peucker a 50 m) e registar.
- **Mutações (5):** `<` no raio; incluir as amostras; esquecer os dias fechados; o corredor sem `calculo.atual`; a ordem dos grupos trocada.
- **Commit:** `CRM: sugestões de lojas perto das paragens e no caminho`

#### [ ] T3.10 Domínio: links do Google Maps e do Waze e blocos de 9 (30 min)
- **Ficheiros:** `backend/crm/dominio/navegacao.py`, `backend/tests/crm/test_dominio_navegacao.py`.
- **Teste primeiro.** Falha por `ModuleNotFoundError`. Textos exatos:
  - `link_google(38.7108, -9.1369, False) == "https://www.google.com/maps/dir/?api=1&destination=38.710800,-9.136900&travelmode=driving&dir_action=navigate"`, e com portagens a evitar acaba em `&avoid=tolls`;
  - `link_waze(38.7108, -9.1369, False) == "https://waze.com/ul?ll=38.710800,-9.136900&navigate=yes"`, mais `&avoid_tolls=true`;
  - NaN, `None` ou `bool` → `None`.
- **`blocos_google(paragens_numeradas, evitar, tamanho=9)`:**
  - 1 paragem → um bloco sem `waypoints`, com o rótulo "Abrir paragem 1 no Google Maps (1 paragem)";
  - 9 → um bloco com `waypoints=` dos 8 primeiros separados por `%7C` e o destino no 9.º, com o rótulo "Abrir paragens 1–9 no Google Maps (9 paragens)";
  - 10, 18, 19 e 48 → blocos de 9 e o resto;
  - sem origem; só as paragens com coordenadas.
- **Mutações (4):** a origem incluída; `|` sem codificar; o bloco de 10; o `avoid` no Waze com o nome do Google.
- **Commit:** `CRM: links de navegação Google Maps e Waze, com blocos de 9`

### Bloco F3b — Serviço openrouteservice

#### [ ] T3.11 `servicos/ors.py`: a chave só no cabeçalho e os registos sem segredos (60 min)
- **Ficheiros:** `backend/crm/servicos/ors.py`, `backend/crm/servicos/__init__.py` (docstring), `backend/tests/crm/test_ors.py`, `backend/tests/crm/conftest.py`, `backend/.env.example` (**partilhado**), `backend/tests/crm/test_variaveis_ambiente.py`, `fixtures/ors/erro-429.json`.
- **Teste primeiro.** Falha por `ModuleNotFoundError: crm.servicos.ors`. Depois de o código existir, o `test_variaveis_ambiente` falha até `CRM_ORS_CHAVE` e `CRM_ORS_URL` entrarem no `.env.example` e em `LIDAS_PELO_CRM`.
  - **O pedido:**
    - `otimizar(pedido)` faz um POST a `{base}/optimization` e `direcoes(pedido)` a `{base}/v2/directions/driving-car/json` (a base com ou sem barra no fim);
    - o corpo é `json.dumps(pedido, allow_nan=False)` (NaN → `ValueError`: é um engano do código, não uma `FalhaOrs`);
    - cabeçalhos `Authorization: <chave>` exato, `Content-Type: application/json`, `Accept: application/json`;
    - **a chave nunca aparece no URL**;
    - não segue redireções.
  - **A chave e o URL:** lidos do ambiente a cada chamada (`chave()`, `url_base()`), ou recebidos por parâmetro (`chave=`, `url=`, que o gravador usa). Sem chave → `FalhaOrs(tipo="sem_chave")` **sem pedido nenhum**.
  - **As respostas:**
    - 2xx com um objeto JSON → `dict`;
    - lista, não-JSON ou NaN → `indisponivel`;
    - 429 → `limite`;
    - 400/404/500 com `{"error": {"code": 2010, "message": "…coordinate 3: …"}}` → `ponto_sem_estrada` com `indice == 3`; um 2010 sem número → `indisponivel`;
    - 401/403/500 → `indisponivel` com `motivo "estado HTTP N"`.
  - **As falhas da rede:** a lista `FALHAS_DA_REDE` (molde de `test_morada.py`: ReadTimeout, ConnectTimeout, ConnectError, ReadError, RemoteProtocolError, TooManyRedirects, DecodingError, UnsupportedProtocol, InvalidURL e RuntimeError) → `motivo "sem resposta (<Tipo>)"`. `__cause__` e `__context__` ficam `None`.
  - **Tempo esgotado:** um transporte pendurado, com o total posto a 0,05 s → `"sem resposta (TimeoutError)"`.
  - **Chave canária:** com o `caplog` em DEBUG no root, no `httpx` e no `httpcore`, em todos os caminhos acima, a chave nunca aparece no `caplog.text`, no `str()` nem no `repr()` da falha. As coordenadas do corpo também não aparecem nos registos.
  - **`interpretar_erro(estado, corpo)`:** função pura, testada à parte.
  - **`conftest.py`:** um *fixture* `autouse` instala por omissão `ors._transporte = httpx.MockTransport(…)`, que levanta `AssertionError("pedido real ao openrouteservice num teste")`, com o `import` dentro da função, depois das `setdefault`. Um meta-teste prova que um teste sem transporte próprio rebenta.
- **Implementação:**
  - molde do `obter_json` do `geoapify.py`: `httpx.AsyncClient(timeout=…, transport=_transporte, follow_redirects=False)` + `asyncio.wait_for`, sobre `geoapify.ler_json` e `geoapify.silenciar_registos()`;
  - `FalhaOrs(motivo, tipo, indice=None)`, lançada fora do `except`;
  - `TEMPO_OTIMIZACAO = httpx.Timeout(15.0, connect=3.0)` e `TOTAL_OTIMIZACAO_S = 15.0`;
  - `TEMPO_DIRECOES = httpx.Timeout(10.0, connect=3.0)` e `TOTAL_DIRECOES_S = 10.0`.
- **`.env.example`:** um bloco no fim, depois do da Geoapify, só com nomes: `CRM_ORS_CHAVE=` (só no servidor, vai no cabeçalho Authorization, nunca ao browser nem aos registos; sem ela o planeador ordena à mão) e `CRM_ORS_URL=` (opcional, vazio = `https://api.openrouteservice.org`). `git diff --stat backend/.env.example` dá cerca de +12.
- **Mutações (6):** a chave no URL (`?api_key=`); seguir redireções; registar o `str(exc)`; o 429 como `indisponivel`; o índice do 2010 desfasado; a falha com `from exc`.
- **Commit:** `CRM: cliente do openrouteservice com a chave só no cabeçalho`

#### [x] T3.12 Gravador das respostas do openrouteservice (o [DONO] corre) (45 min)
- **Ficheiros:** `backend/gravar_respostas_ors.py`, `backend/tests/crm/test_gravar_respostas_ors.py`.
- **Comportamento:** `cd backend && .venv/bin/python gravar_respostas_ors.py --env-file .env.local [--pasta tests/crm/fixtures/ors]`.
  - Lê o ficheiro com `dotenv_values` (não toca no `os.environ`). Exige `CRM_ORS_CHAVE` não vazia, senão sai com 1 e "Falta a CRM_ORS_CHAVE no ficheiro indicado.".
  - Usa **sempre** `https://api.openrouteservice.org` e ignora o `CRM_ORS_URL`.
  - Monta os pedidos do `cenarios.json` com `vroom.pedido_otimizacao` e `directions.pedido_direcoes`.
  - Grava **tudo ou nada**: primeiro `.<ficheiro>.tmp` e depois `os.replace`. Cada JSON começa por `"_origem": "gravado em AAAA-MM-DD (gravar_respostas_ors.py)"` (a data vem de `relogio.hoje`), com indentação 2 e `ensure_ascii=False`.
  - Se a chave aparecer em qualquer resposta, **não grava nada**.
  - Só imprime os nomes dos ficheiros.
- **Teste primeiro.** Falha por `ModuleNotFoundError: gravar_respostas_ors`. Com `MockTransport`, nunca com a rede:
  - sem chave: sai com 1 e não há ficheiros;
  - um pedido falha: nenhum ficheiro muda (`cmp` com a cópia);
  - a chave numa resposta: nada;
  - com sucesso: os ficheiros com `_origem`, lidos pelos `interpretar_*`;
  - o `capsys` nunca tem a chave;
  - o URL usado é sempre o oficial, mesmo com `CRM_ORS_URL` no ficheiro.
- **[DONO]** (dossiê §14, ponto novo): criar a conta e correr o gravador com a chave de desenvolvimento. Depois, `pytest tests/crm` tem de continuar verde. Os testes das rotas usam respostas construídas no próprio teste para os valores exatos, e as gravadas só provam o formato real (decisão desta tarefa, escrita no docstring do `test_rotas_recalcular.py`).
- **Commit:** `CRM: gravador das respostas do openrouteservice, só com a chave do dono`
- **Feito (2026-10-13):** aplicadas as correções "T3.12 / T3.43 (dossiê §14)" (recusa da chave `simulador-local` com "A CRM_ORS_CHAVE do ficheiro é a do simulador."; o §14 do dossiê, ponto 5, com o passo explícito e o `grep -c "^CRM_ORS"`) e "T3.12 / T3.43 (gravador, .env.local e fixtures)" (o ficheiro próprio `--env-file .env.ors`, fora do git e com o modo 600; a lista fechada dos 4; o `erro-429.json` sempre manual; os testes sobre as fixtures só com a forma e os conjuntos). **Feita fora da ordem:** a T3.9, a T3.10 e a T3.11 não estão feitas (agentes falhados). O gravador não depende delas (ver os desvios). **Nunca correu contra o ORS verdadeiro** (só o [DONO], §14 ponto 13). Vermelho por `ModuleNotFoundError: No module named 'gravar_respostas_ors'` (`t3.12-vermelho.log`). Verde com **111 testes** no `test_gravar_respostas_ors.py` (`t3.12-verde.log`; a 1.ª passagem teve 1 falha do próprio teste: o canário "rio" está dentro de "priority", trocado pelos nomes inteiros dos pontos). Bateria `tests/crm`: **4868 passed, 27 skipped** (4757 + 111), 17 s, os 6 avisos de sempre (`t3.12-bateria-crm.log`); `asyncio.run(` em `tests/crm` → 0.
  - **Onde correram os testes:** numa árvore limpa (`git worktree add --detach` de `75ecdcd` em `$HOME/.cache/lisbonb-crm-local/t3.12-arvore`, mais os 2 ficheiros desta tarefa, com o `.venv` do `backend`), removida no fim. A árvore de trabalho tem restos não guardados da T3.11 falhada (`tests/crm/conftest.py` modificado, `test_ors.py` e `fixtures/ors/erro-429.json` por versionar): o fixture `autouse` do `conftest.py` importa `crm.servicos.ors`, que não existe, e **todos** os testes do CRM dão ERROR nessa árvore (`pytest tests/crm/test_dominio_horas.py -x` → 1 error). Não se tocou nesses restos (são da T3.11).
  - **Decisões fixadas pelos testes:**
    - `principal(argv) -> int` (0 gravou tudo, 1 não; o argparse sai com 2 sem `--env-file`). `--pasta` por omissão é `backend/tests/crm/fixtures/ors` (pelo caminho do próprio script, não da pasta atual); os testes passam sempre uma cópia em `tmp_path`.
    - **A chave:** `dotenv_values(…, interpolate=False)` (um `${VAR}` no ficheiro não vai buscar nada à shell); nunca lê nem escreve o `os.environ` (a chave da shell não conta; o `os.environ` fica igual). Vazia, só espaços, `""`, sem `=`, comentada ou noutro nome → "Falta a CRM_ORS_CHAVE no ficheiro indicado."; `simulador-local` (também entre aspas, com `export` e ao lado do `CRM_ORS_URL` do simulador) → "A CRM_ORS_CHAVE do ficheiro é a do simulador." e uma 2.ª linha que manda usar o `backend/.env.ors` com `chmod 600`. Uma chave tem de ser `[A-Za-z0-9+/=_.-]{20,}` (as hexadecimais e as base64 do ORS): curta, com espaços, tabs, acentos, aspas, `\` ou `&` → recusada sem a mostrar (assim pode ir num cabeçalho e o JSON nunca a escreve com escapes). Ficheiro inexistente → "Não encontrei o ficheiro …". Com o modo a deixar ler grupo/outros, um aviso no stderr ("faça chmod 600") e grava na mesma.
    - **Os pedidos:** sempre `https://api.openrouteservice.org` (`/optimization` e `/v2/directions/driving-car/json`), mesmo com `CRM_ORS_URL` no ficheiro e na shell; POST com `Authorization: <chave>` exato, `Content-Type` e `Accept` `application/json`; o corpo é `json.dumps(…, allow_nan=False)` do `vroom.pedido_otimizacao`/`directions.pedido_direcoes` montados como nos testes da T3.6/T3.7 (o id é o nome do ponto, que nunca vai: os nomes inteiros dos pontos não aparecem nos corpos); a chave nunca no URL nem no corpo; `httpx.Client` síncrono, `follow_redirects=False`, `Timeout(30, connect=5)`; os registos `httpx`/`httpcore` silenciados (`geoapify.silenciar_registos`). Pela ordem fixa `otimizacao-todas`, `otimizacao-uma-nao-cabe`, `direcoes-tres-paragens`, `direcoes-erro-2010`, e **pára no primeiro que falhe** (poupa a quota).
    - **Só grava o que os testes aceitam:** otimização lida pelo `interpretar_otimizacao` e com as não atribuídas esperadas (nenhuma no "todas"; só `torre_de_belem` no "uma-nao-cabe"); Directions lido pelo `interpretar_direcoes`, com todos os troços com distância e duração > 0 e a linha com ≥ 2 pontos; o 2010 tem de vir com um estado 4xx/5xx (fora 401/403/429), `error.code` o inteiro 2010 (não texto nem `bool`), `error.message` texto, e o número de `coordinate N` ou do antigo `point N` igual à posição do `rio_tejo` contada a partir de 0 (2). Uma rota (2xx) no cenário do 2010 → "…trouxe uma rota em vez do erro 2010…". Assim o `pytest tests/crm` continua verde depois de regravar; se o ORS verdadeiro contar a partir de 1, o gravador recusa e diz-o (a T3.11 conta a partir de 0).
    - **Falhas** (todas com o nome do cenário e "não se gravou nada", sem o texto da exceção): sem resposta → "(sem resposta: <Tipo>)"; estado fora de 2xx → "(estado HTTP N)", com " — chave recusada ou quota diária esgotada" no 401/403 e " — limite de pedidos, espere um minuto" no 429; 3xx não se segue; não JSON, lista ou NaN → "não é um objeto JSON" (pelo `geoapify.ler_json`); forma errada → "não tem a forma esperada (<motivo fixo da RespostaInvalida>)"; cenário diferente → "não bate certo com o cenário (…)". Um `cenarios.json` estragado ou em falta → mensagem com "cenarios.json" e nenhum pedido.
    - **A chave numa resposta** → "A resposta para X traz a chave; não se gravou nada.", procurada no corpo tal como veio (apanha também a chave só no `_origem` da resposta, que não se gravaria) **e** no texto a gravar (apanha a chave escrita com escapes `\u` no JSON).
    - **A escrita:** `{"_origem": "gravado em AAAA-MM-DD (gravar_respostas_ors.py)", …resposta}` (o `_origem` da resposta é substituído e fica em 1.º; a data é a de Lisboa pelo `relogio.hoje`: 23:30 UTC de 15 de julho → 2026-07-16), `json.dumps(…, ensure_ascii=False, indent=2)` + `"\n"`. Primeiro todos os `.<ficheiro>.tmp` na pasta (uma falha → apaga os seus temporários, nenhum ficheiro muda; uma pasta com o nome do temporário não é dele e fica) e só depois `os.replace` (uma falha rara → diz quais já ficaram gravados, sai com 1, sem temporários). O stdout só tem "Gravado: <ficheiro>"; a chave nunca no stdout, no stderr nem no `caplog` (em DEBUG no root, `httpx` e `httpcore`). O `cenarios.json`, o `erro-429.json` e o `direcoes-ponto-repetido.json` nunca mudam.
    - **A guarda dos testes** (no próprio ficheiro, porque o `conftest.py` é da T3.11): um fixture `autouse` põe no `_transporte` do gravador um transporte que só regista e responde 599 e corta o `httpx.HTTPTransport.handle_request`, o `socket.create_connection` e o `socket.getaddrinfo`; no fim exige a lista vazia. Dois meta-testes chamam o gerador à mão (um gravador sem o transporte do teste → 599, exit 1 e a guarda rebenta no fim; o transporte verdadeiro e os sockets levantam). Assim nem uma mutação que se esqueça do transporte chega ao ORS.
  - **Mutações (30, o plano não lista nenhuma para a T3.12):** a chave no URL; o `CRM_ORS_URL` da shell e o do ficheiro a contar; a chave do simulador aceite; `load_dotenv` (o ficheiro no `os.environ`); a interpolação; seguir redireções; sem temporários; temporários por apagar; sem procurar a chave no corpo e sem a procurar no texto a gravar (cada uma com o seu teste); o texto da exceção na saída; a data de UTC e a do relógio do Mac no `_origem`; sem verificar as respostas; uma rota aceite no 2010; sem conferir as não atribuídas; sem conferir os troços; o índice do 2010 a partir de 1; só o formato novo do 2010; o código 2010 em texto; `ensure_ascii=True`; indentação a 4; o `_origem` no fim; o `_origem` da resposta a ficar; qualquer chave aceite; sem o aviso do modo; não parar na primeira falha; o 401 sem a explicação; o `erro-429` na lista fechada. Todas apanhadas, cada uma também pelo seu teste-alvo, sem erros de recolha (`t3.12-mutacoes.log`, script `t3.12-mutacoes.py`, aplicadas à cópia na árvore limpa com `PYTHONDONTWRITEBYTECODE=1`; reposto conferido com `cmp` e `sha256`). Numa 1.ª passagem a mutação da data do Mac dava erro de sintaxe (aspas dentro da f-string), corrigida e repetida.
  - **Desvios:** (1) o gravador **não usa o `crm.servicos.ors`** (T3.11, por fazer): precisa do corpo do erro 2010 tal como veio, que o cliente das rotas transforma numa `FalhaOrs`, e vai sempre ao URL oficial; é um `httpx.Client` síncrono próprio com o mesmo molde (chave só no `Authorization`, sem redireções, registos silenciados, `geoapify.ler_json`). (2) Além do texto da tarefa: a verificação de que cada resposta bate certo com o cenário antes de gravar (para o `tests/crm` continuar verde), a validação da forma da chave, o aviso do modo do ficheiro, o `interpolate=False` e a paragem no primeiro pedido que falha. (3) A frase "os testes das rotas usam respostas construídas no próprio teste para os valores exatos, e as gravadas só provam o formato real" fica no docstring deste gravador e do seu teste; a **T3.21** escreve-a no docstring do `test_rotas_recalcular.py` (o ficheiro ainda não existe). (4) Os testes correram numa árvore limpa (ver acima). Nenhuma rota nem código de erro novos (o meta-teste da proteção e o `erros.py` não mudam). [DONO]: o §14 do dossiê, pontos 5 e 13.

#### [x] T3.13 Simulador local do openrouteservice para a pré-visualização (60 min)
- **Ficheiros:** `backend/ors_simulado_local.py`, `backend/tests/crm/test_ors_simulado_local.py`.
- **Comportamento:** uma app FastAPI pequena, com `uvicorn.run(host="127.0.0.1", port=…)`. `--host` só aceita `127.0.0.1`, `localhost` e `::1`; os outros dão `SystemExit("Recusado: o simulador só escuta em 127.0.0.1.")`. Rotas:
  - `GET /saude` → `{estado: "ok", simulador: true}`;
  - `POST /optimization` e `POST /v2/directions/driving-car/json`. Exigem `Authorization` não vazio (sem ele, 401), para provar que o cliente o envia.
- **Simulação:** distância = haversine × 1,3; velocidade 11 m/s (~40 km/h); a evitar portagens, a duração × 1,15.
  - **VROOM:** vizinho mais próximo, guloso, por prioridade e depois distância. Respeita as janelas (espera pela abertura), o serviço e o fim da janela do veículo, contando o regresso; um *job* que nunca cabe vai para `unassigned`.
  - **Directions:** `segments` por troço e `geometria` em linhas retas, codificada com `codificar_polilinha` (precisão 5; os testes do domínio usam-na para a ida e volta).
  - Determinístico e sem relógio.
- **Teste primeiro.** Falha por `ModuleNotFoundError`. Com o `TestClient`:
  - as respostas leem-se com `interpretar_otimizacao` e `interpretar_direcoes`;
  - um *job* com a janela já passada vai para `unassigned`;
  - as prioridades: entrega primeiro;
  - 401 sem `Authorization`;
  - a guarda do anfitrião;
  - `descodificar(codificar_polilinha(p)) ≈ p` (1e-5).
- **Commit:** `CRM: simulador local do openrouteservice para ver rotas sem chave`
- **Feito (2026-10-13):** aplicadas as correções "T3.7 (+ T3.13, T3.21)" (a parte da T3.13: um troço de comprimento zero vem sem `distance` nem `duration`, e um resumo a zero sem elas) e "T3.7 / T3.9 / T3.13 / T3.21" (a linha é codificada pelo `polilinha.codificar` do domínio, chamado pelo módulo, provado com um `monkeypatch`). **Feita fora da ordem:** a T3.9, a T3.10 e a T3.11 continuam por fazer (agentes falhados); o simulador não depende delas. Vermelho por `ModuleNotFoundError: No module named 'ors_simulado_local'` (`t3.13-vermelho.log`). Verde com **148 testes** no `test_ors_simulado_local.py` (`t3.13-verde.log`; os 2 dos registos foram juntados depois, com o vermelho próprio contra a versão anterior: `KeyError: 'access_log'` e a lista dos registos vazia, `t3.13-vermelho-registos.log`). Bateria `tests/crm`: **5016 passed, 27 skipped** (4868 + 148), 18 s, os 6 avisos de sempre (`t3.13-bateria-crm.log`); `asyncio.run(` em `tests/crm` → 0.
  - **Onde correram os testes:** como na T3.12, numa árvore limpa (`git worktree add --detach` de `612ad64` em `$HOME/.cache/lisbonb-crm-local/t3.13-arvore`, mais os 2 ficheiros desta tarefa, com o `.venv` do `backend`; partida 4868 passed, 27 skipped, `t3.13-partida-arvore.log`), removida no fim. A árvore de trabalho continua com os restos não guardados da T3.11 (`tests/crm/conftest.py` modificado, `test_ors.py` e `fixtures/ors/erro-429.json` por versionar), em que todos os testes do CRM dão ERROR; não se tocou neles.
  - **Decisões fixadas pelos testes:**
    - `principal(argv)`: `--porta` (por omissão 8013; inteiro de 1 a 65535, senão o argparse sai com 2) e `--host` (por omissão `127.0.0.1`); só `127.0.0.1`, `localhost` e `::1`, exatamente (`0.0.0.0`, `::`, `""`, `" 127.0.0.1"`, `127.0.0.2`, `[::1]`, `LOCALHOST`, nomes de fora…) → `SystemExit("Recusado: o simulador só escuta em 127.0.0.1.")` (sai com 1) **antes** do `uvicorn.run`. O `uvicorn.run(app, host, port, log_level="info", access_log=False)`: sem o registo de acesso do uvicorn, que escrevia o URL com os parâmetros; cada pedido regista só "POST <caminho> → <estado>" no `uvicorn.error`.
    - **Rotas:** só `GET /saude` (`{"estado": "ok", "simulador": true}`, sem chave), `POST /optimization` e `POST /v2/directions/driving-car/json`; sem `/docs`, `/redoc` nem `/openapi.json`; outro perfil → 404. Pela ordem: `Authorization` vazio, só espaços ou em falta → 401 `{"error": …}` (antes de ler o corpo); qualquer parâmetro no URL (`?api_key=…`) → 400 na forma do serviço, sem ecoar o URL (a chave vai só no cabeçalho, §0 regra 12); depois o corpo (pelo `geoapify.ler_json`: NaN e o resto que o JSON não tem → 400). Qualquer chave não vazia serve (só prova que o cliente a envia); a chave nunca volta nas respostas nem nos registos (canária com o `caplog` em DEBUG).
    - **O modelo:** `distancia_m([lng, lat], [lng, lat])` = `geo.distancia_metros` × 1,3; `duracao_s(d, evitar_portagens)` = d / 11 (× 1,15). Os valores exatos dos testes são de pontos no mesmo meridiano (−8), com `R × Δφ` escrito no teste.
    - **VROOM:** a carrinha sai do `start` na abertura da `time_window` (sem ela: às 0 e sem limite); a cada passo, entre os *jobs* que cabem, o de maior `priority`, depois o mais perto de onde a carrinha está, depois a ordem do pedido. Cabe se a chegada não passar do fim de uma janela (o início do serviço, como no VROOM: `chegada ≤ fim`, espera pela abertura, também pela 2.ª, por qualquer ordem) e se `início + serviço + regresso ao end ≤ fim da janela do veículo`. Viagens em segundos inteiros (`numeros.arredondar`; 262,82 s → 263). Passos `start`/`job`/`end` como nas fixtures da T3.6 (`id` e `job` iguais nos *jobs*; `arrival`, `waiting_time`, `service`, `duration` acumulada), totais na rota e no `summary`; `unassigned` `{id, type: "job", location}` pela ordem do pedido; nada atribuído → `routes: []` (correção "T3.6 / T3.22"). Os cenários do `cenarios.json` passam as verificações do gravador (`gravar_respostas_ors.pedidos(...)[i].conferir`): no "todas" a ordem é Comércio (entrega, espera pelas 09:00) → Marquês → Belém; no "uma-nao-cabe" fica de fora só a Torre de Belém.
    - **Directions:** troços a 1 casa (`numeros.arredondar`), cada um com os passos de partida (tipo 11, `way_points [i, i+1]`) e de chegada (tipo 10); a medida que dá 0 sai (troço, passos e resumo); `summary` pela soma (`math.fsum`) antes de arredondar; `bbox`; `way_points` 0..n−1; a linha passa por todos os pontos pedidos, pela ordem (um ponto repetido fica repetido, por isso há sempre ≥ 2 pontos). Sem `instructions` não há `segments` (como o ORS, risco R2) e sem `geometry` não há linha; por omissão os dois. `options.avoid_features` só conta com `"tollways"`. O simulador não sabe onde há estradas: o ponto no rio do cenário do 2010 dá uma rota (o 2010 só se prova com o gravador).
    - **Pedidos inválidos:** só a forma que o `vroom.pedido_otimizacao` e o `directions.pedido_direcoes` mandam. VROOM → 400 `{"code": 2, "error": …}`: sem `jobs` ou vazio, *job* sem `id` inteiro (`bool`, `"1"`, `1.0`), ids repetidos, `location` que não é `[lng, lat]` de números dentro do mundo, `service` < 0 ou decimal, `priority` fora de 0..100, `time_windows` vazias ou com uma janela que não é `[a, b]` inteiros com 0 ≤ a ≤ b, mais de uma ou nenhuma carrinha, perfil que não é `driving-car`, sem `start`/`end`. Directions → 400 `{"error": {"code", "message"}}`: 2000 (não é JSON, lista, NaN), 2001 (sem `coordinates`), 2004 (mais de 50 pontos), 2003 (o resto: 1 ponto, pontos estragados, `instructions`/`geometry` que não são booleanos, `elevation: true`, `units` ≠ "m", `options` estragadas). Mensagens fixas, sem valores do pedido.
    - **Marcado como simulador** (R14): `metadata.simulador: true` e a atribuição "simulador local do openrouteservice (linhas retas) — não é o openrouteservice" nas duas respostas. Determinístico (o mesmo pedido dá os mesmos bytes). Varrimento AST: não importa `datetime`, `time`, `random`, `zoneinfo`, `uuid`, `secrets`, `os`, `httpx`, `requests`, `urllib`, `socket`, `http`, `aiohttp`, `dotenv` nem o `crm.relogio`, e nunca chama o `round`. Nem o `server.py` nem o pacote `crm` o mencionam, e o router do CRM não tem as rotas do ORS. Um fixture `autouse` do teste corta o transporte verdadeiro do httpx e os `socket` (o `TestClient` corre dentro do processo).
  - **Mutações (45, o plano não lista nenhuma para a T3.13):** a guarda do anfitrião desligada; o `0.0.0.0` aceite; o uvicorn em `0.0.0.0` depois da guarda; sem exigir o `Authorization`; só espaços aceites; parâmetros no URL aceites; o URL ecoado na mensagem; sem o 1,3; `[lat, lng]` trocado; 10 m/s; as portagens nunca contam; o Directions ignora o `tollways`; qualquer coisa a evitar conta; sem a prioridade; a distância à partida; o empate pelo id; sem esperar pela abertura; o fim da janela ignorado; `<` no fim da janela; só a 1.ª janela; o serviço não conta; o regresso não conta no limite; `>=` no limite; o regresso ao início; a saída do veículo ignorada; as viagens cortadas; a espera fora do resumo; uma rota só com início e fim quando nada cabe; os não atribuídos sem o `type`; os não atribuídos pelo id; o troço de comprimento zero com as chaves a 0; troços sem `instructions`; a linha em `[lng, lat]`; o `round` nas medidas; ids repetidos; duas carrinhas; 51 pontos; a elevação; `bool` num ponto; a prioridade sem máximo; janelas vazias; sem o `metadata.simulador`; o `/docs` ligado; o registo de acesso ligado; o URL inteiro no registo. Todas apanhadas, cada uma também pelo seu teste-alvo corrido sozinho, sem erros de recolha (`t3.13-mutacoes.log`, script `t3.13-mutacoes.py`, aplicadas à cópia na árvore limpa com `PYTHONDONTWRITEBYTECODE=1`; reposto conferido com `cmp` e `sha256`, e a passagem de controlo verde).
  - **Fumo em local** (`t3.13-fumo.log`, `t3.13-ors-simulado.log`, `t3.13-recusa.log`): `--host 0.0.0.0` sai com 1 e a mensagem, sem escutar; arrancado em segundo plano em 127.0.0.1:8013, o `curl --max-time 3` deu o `/saude`, 401 sem chave, 200 no Directions (troço repetido sem as medidas) e no VROOM (o *job* de janela passada em `unassigned`), 400 com `?api_key=` (e o registo só com "POST /optimization → 400"); parado com `kill -TERM` (8013 livre no fim; 8001 e 3000 da pré-visualização do dono intocados).
  - **Desvios:** (1) feita fora da ordem (ver acima); (2) além do texto da tarefa: os parâmetros no URL recusados, os registos só com método, caminho e estado (sem o registo de acesso do uvicorn), sem `instructions` não há `segments`, a validação dos pedidos com os códigos do ORS, `metadata.simulador` (do R14) e a `time_window` do veículo opcional; (3) o comando para arrancar fica no §5 do plano; o dossiê (§8, §12.6, §12.7) é da T3.43. Nenhuma rota do portal nem código de erro novos (o simulador é uma app à parte, fora do `crm.router`: o meta-teste da proteção e o `erros.py` não mudam); nada para o [DONO].

### Bloco F3c — Base, API e escritas seguras

#### [ ] T3.14 Infra: `crm_rotas`, índices, duplo com `$inc`/`$push`/caminhos por índice e verificador do terreno (60 min)
- **Ficheiros:** `backend/crm/db.py`, `backend/tests/crm/{duplos,formatos}.py`, `backend/tests/crm/test_duplos.py`, `backend/tests/crm/test_indices.py`, `backend/tests/crm/test_instantes_gravados.py` (os testes do verificador novo).
- **Teste primeiro.** Falha por `KeyError: 'rotas'` em `COLECOES`, pelos índices em falta e por `NotImplementedError` do duplo:
  - **Índices:** `crm_rotas` com exatamente `id` único, `data` único e `paragens.loja_id` não único. No duplo, `unicos_declarados("crm_rotas") == ("id", "data")`.
  - **Novos `$set` e `$inc` no duplo:**
    - `$set` com pontos e índices (`"paragens.1.ordem"`); um índice para lá do fim → `NotImplementedError` (nunca se estica a lista);
    - `$inc` (em falta → o valor; não-número → `OperationFailure`).
  - **`$push`** (em falta → `[v]`; não-lista → `OperationFailure`).
  - **Conflito de caminhos**: `$push paragens` + `$set paragens.0.x` → `OperationFailure(code=40)`, com a mensagem do Mongo "Updating the path … would create a conflict at …".
  - **Filtros:**
    - `$gt`/`$gte`/`$lt`/`$lte`, só entre tipos iguais;
    - caminhos com pontos através de listas (`"paragens.loja_id"`, `"paragens.estado": {"$nin": […]}` com a semântica de "algum elemento");
    - índice no filtro (`"paragens.2.estado"`).
  - **`find_one_and_update`** aplica todos os operadores.
  - **Gancho `ColeccaoFalsa.antes_de(operacao, funcao)`**: corre `funcao(docs)` antes da operação, para simular uma escrita concorrente, como a do motorista na F4.
  - **`formatos.escritas_no_terreno(atualizacao)`** → violações, provado com amostras positivas e negativas:
    - `$pull`/`$pop`/`$unset`/`$addToSet`/`$rename` em `paragens…`;
    - `$set` de `paragens` inteira;
    - `$set` em `paragens.N.<campo do terreno>`;
    - `$push` de uma paragem com os campos do terreno diferentes de `pendente`/`None`/`None`.
- **Implementação:** `COLECOES["rotas"] = "crm_rotas"` e as três entradas em `INDICES`, com comentários.
- **Verificar:** depois da bateria, a **suite completa em segundo plano** (o duplo é partilhado por todos os testes do CRM): `failed` 0 e `skipped` igual ao da T3.0.
- **Commit:** `CRM: coleção das rotas, índices e duplo com caminhos por índice`

#### [ ] T3.15 Definições das rotas na API (40 min)
- **Ficheiros:** `backend/crm/definicoes.py`, `backend/tests/crm/test_definicoes.py`.
- **Teste primeiro.** Falha porque o `GET` devolve 3 chaves em vez de 9.
  - **`GET`:** as 9 chaves, com os minutos como `int`.
  - **`PATCH`:**
    - `{"rota_hora_saida": "07:30"}` grava e devolve;
    - `{"rota_hora_regresso": "07:00"}` com a saída guardada às 08:00 → 422 de coerência, sem gravar nada (`em_vigor` + os valores, antes da primeira escrita);
    - `{"servico_entrega_min": 0}` → 422;
    - o documento gravado passa no `instantes_fora_do_formato`.
  - **Os testes antigos** com dicionários exatos passam a usar `{**PADROES_EM_VIGOR, …}`.
  - **O frontend não muda:** `fabrica.js` só lê as `fabrica_*`. O Jest de `src/lib/crm/fabrica.test.js` continua verde.
- **Commit:** `CRM: definições das rotas na API`

#### [ ] T3.16 Formatar: a rota e a paragem na base e na API (60 min)
- **Ficheiros:** `backend/crm/formatar_rota.py`, `backend/tests/crm/test_formatar_rota.py`.
- **Teste primeiro.** Falha por `ModuleNotFoundError`.
  - **`documento_rota(data, membro_id, agora, definicoes)`:** as chaves e a ordem do §3; `versao 1`; `estado "rascunho"`; as horas das definições; `inicio`/`fim`/`calculo` a `None`; `paragens []`; os instantes no formato certo.
  - **`documento_paragem(loja, motivo, servico_min, ordem, membro_id, agora)`:** os campos do terreno iniciais. Passa no `escritas_no_terreno({"$push": {"paragens": p}}) == []`.
  - **`rota_api(rota|None, data=, hoje=, lojas=, definicoes=, calculo_disponivel=)`:**
    - a ordem das chaves do §4; a rota virtual (`existe: False`, `id/versao/estado None`, `editavel` pelo `bloqueio_de_escrita`);
    - `inicio`/`fim` resolvidos com `fabrica: True`;
    - só as paragens ativas, por ordem, com `numero`, `seccao`, `aviso`, `links` (`navegacao`) e `loja` (projeção `PROJECAO_LOJA_ROTA`: `id, nome, fase, lat, lng, telefone, janelas, dias_fechada`, com as janelas planas por `campos_de_janelas`);
    - `blocos_google` só com a secção `"rota"`;
    - `calculo.atual` pela assinatura atual (fica `False` depois de mudar a loja de sítio, a janela, a fábrica com `inicio None`, ou a ordem);
    - sem `_id`; uma loja apagada → `loja: None`, `seccao "sem_loja"`, `links None`.
  - **`resumo_rota_api(rota, hoje)`:** `paragens` conta só as ativas.
- **Commit:** `CRM: forma das rotas na base e na API`

#### [ ] T3.17 Repositório das rotas (50 min)
- **Ficheiros:** `backend/crm/rotas_bd.py`, `backend/tests/crm/test_rotas_bd.py`.
- **Teste primeiro.** Falha por `ModuleNotFoundError`. Com o duplo, verificando o **filtro e a atualização exatos** no registo:
  - **`ler(base, "2026-10-12")`** → `find_one({"data": …}, {"_id": 0})`.
  - **`criar(base, doc)`** → `True`; `DuplicateKeyError` na `data` → `False`.
  - **`alterar(base, rota, set_, *, subir_versao=True, membro_id, agora)`** → `find_one_and_update` com:
    - filtro `{"id", "versao": rota["versao"], "estado": {"$in": ESTADOS_EDITAVEIS}, "paragens.estado": {"$nin": ["feita", "nao_feita"]}}`;
    - atualização `{"$set": {**set_, "atualizado_em": proximo_carimbo(agora, rota["atualizado_em"]), "atualizado_por": membro_id}, "$inc": {"versao": 1}}`;
    - `ReturnDocument.AFTER` e projeção `{"_id": 0}`;
    - `subir_versao=False` (horas) → sem `$inc` e sem `atualizado_*`;
    - devolve o documento ou `None`.
  - **`acrescentar_paragem(base, rota, paragem, …)`** → `$push` + `$inc` + `$set` só de topo (nunca `paragens.N`).
  - **`porque_falhou(base, rota_id, versao)`** → `"nao_existe"`, `"conflito"` ou `"em_curso"`.
  - **`lojas_da_rota`** → `find({"id": {"$in": ids}}, PROJECAO_LOJA_ROTA)`. **`rotas_entre`** → `{"data": {"$gte": de, "$lte": ate}}` por data. **`rotas_com_loja`** → `{"paragens.loja_id": id}`.
  - **Todas as escritas do registo** passam em `escritas_no_terreno == []` e em `instantes_fora_do_formato == []`.
- **Commit:** `CRM: leitura e escrita das rotas com versão`

#### [ ] T3.18 `GET /rotas` e `GET /rotas/{data}` (45 min)
- **Ficheiros:** `backend/crm/rotas.py`, `backend/crm/__init__.py` (`router.include_router(_rotas)`), `backend/tests/crm/test_rotas_ler.py`, `backend/tests/crm/test_protecao_rotas.py` (2 rotas + a regra `rotas` → `PERFIS_ESCRITORIO`).
- **Teste primeiro.** Falha por `ImportError: cannot import name 'rotas' from 'crm'`, e o teste de proteção pelas 2 rotas `sem_rota`.
  - **`GET /rotas`:**
    - `hoje` vem do `relogio.agora` parado, e o intervalo por omissão é −14/+60;
    - ordenado por data;
    - `estado_efetivo "concluida"` nas passadas;
    - 422 com `de=2026-1-1`, com `ate` antes de `de` e com 121 dias.
  - **`GET /rotas/{data}`:**
    - sem rota → a virtual (com as horas das definições);
    - uma passada sem rota → `estado_efetivo "concluida"`, `editavel false`;
    - com rota → completa, com as lojas juntadas;
    - `calculo_disponivel` segue o `CRM_ORS_CHAVE` (`monkeypatch.setenv` e `delenv`);
    - `data=abc` → 422; `data=2028-01-01` (mais de 365 dias) → 422.
  - **Perfis:** o motorista recebe 403 `sem_permissao`, quem não é membro 403 `sem_acesso_crm`, e sem cabeçalho 403 "Not authenticated". De ponta a ponta com a sessão verdadeira (molde de `test_lojas_editar.py`).
- **Commit:** `CRM: ler as rotas por dia`

#### [ ] T3.19 `POST /rotas/{data}/paragens` — adicionar uma loja (60 min)
- **Ficheiros:** `backend/crm/rotas.py`, `backend/crm/erros.py` (`ja_na_rota`, `rota_cheia`, `rota_fechada`), `backend/tests/crm/test_rotas_adicionar.py`, `test_erros.py`, `test_protecao_rotas.py`.
- **Teste primeiro.** Falha com 405/404 e "não está no router do CRM", e o `test_erros` pelos códigos em falta.
  - **Criar e adicionar:**
    - sem rota → 201, a rota criada em `rascunho` com uma paragem;
    - motivo por omissão pela fase (contactada → `amostra`) e tempo pelas definições (`10`);
    - com rota → `$push` no fim (`ordem = n`), com a versão +1;
    - uma loja retirada antes → **reativada** (o mesmo `id`, `removida_em None`, `ordem` no fim, motivo, tempo e sinais repostos, horas a `None`), por `caminhos_paragem` e sem `$push`.
  - **Recusas:**
    - já ativa → 409 `ja_na_rota`;
    - 48 ativas → 409 `rota_cheia`;
    - uma loja inexistente → 404 "Loja não encontrada.";
    - ontem → 409 `rota_fechada`;
    - uma rota com uma paragem `feita` → 409 `rota_em_curso`.
  - **Versão:**
    - com `versao` diferente → 409 `conflito`;
    - `versao: null` e a rota já existe → 409 `conflito`;
    - **sem `versao`**, o gancho `antes_de("find_one_and_update", …)` sobe a versão na 1.ª tentativa → a 2.ª grava (201), e com 3 falhas → 409 `conflito`.
  - **Corridas:**
    - duas corrotinas a criar a rota do mesmo dia com lojas diferentes → as duas ficam (o `DuplicateKeyError` na criação → volta a ler e acrescenta), com a versão 2;
    - uma loja fechada nesse dia entra com `seccao "fechada"` e o aviso.
  - **As escritas** passam em `escritas_no_terreno` e `instantes_fora_do_formato`.
  - **O corpo** `[` sem sessão → 403 (guarda antes do corpo).
- **Commit:** `CRM: adicionar lojas à rota de um dia`

#### [ ] T3.20 `PATCH /rotas/{data}` — definições do dia, ordem, paragens, retirar e guardar (60 min)
- **Ficheiros:** `backend/crm/rotas.py`, `backend/crm/erros.py` (`rota_em_curso`), `backend/tests/crm/test_rotas_alterar.py`, `test_erros.py`, `test_protecao_rotas.py`.
- **Teste primeiro.** Falha com 405 e o código em falta.
  - **Cada campo:**
    - horas; a coerência com o valor guardado (mudar só o limite para antes da saída guardada → 422);
    - `inicio {lat, lng}` e `null`; `evitar_portagens`;
    - `ordem` leniente (as ativas em falta vão para o fim);
    - `paragens.<id>.motivo` sem tempo → o tempo do motivo novo; o tempo explícito ganha;
    - `manter_fechada`; `nao_cabe: false`;
    - `retirar` → `removida_em` e `ordem None`, com as outras renumeradas a 0..k−1;
    - `estado: "planeada"`.
  - **Escrita e versão:**
    - uma só `find_one_and_update`, com `$inc versao` e os caminhos `paragens.N.*` certos;
    - um PATCH só com a `versao` → 200, sem escrever e sem subir a versão.
  - **Recusas:** sem rota → 404 "Ainda não há rota para este dia."; versão velha → 409 `conflito`; ontem → 409 `rota_fechada`; um id que não está na rota (na `ordem`, em `paragens` ou em `retirar`) → 422.
  - **Falha da escrita:** o gancho simula outra pessoa (sobe a versão) → 409 `conflito`, e o motorista (põe `paragens.1.estado = "feita"`) → 409 `rota_em_curso`. Nada fica escrito pelo escritório.
- **Commit:** `CRM: alterar a rota do dia com controlo de versão`

#### [ ] T3.21 `POST /rotas/{data}/recalcular` — horas pelo Directions (50 min)
- **Ficheiros:** `backend/crm/rotas.py`, `backend/crm/erros.py` (`calculo_indisponivel`), `backend/tests/crm/test_rotas_recalcular.py`.
- **Teste primeiro.** Falha com 405 e o código em falta. As respostas são construídas no teste (`ors_simulado_local` e `codificar_polilinha`), mais uma vez a fixture gravada.
  - **O pedido:** a chamada capturada pelo `MockTransport` leva as coordenadas `[início] + incluídas + [fim]`, pela ordem, sem as fechadas nem as `nao_cabe`; com `evitar_portagens` leva `avoid_features`. O `json` do pedido não tem canários.
  - **A escrita:**
    - as horas vão por `paragens.N.chegada_prevista|espera_min|fora_de_horario`; as excluídas ficam a `None`/`False`;
    - o `calculo` com a assinatura;
    - a **versão não muda**;
    - a resposta vem com `calculo.atual true`.
  - **Sem paragens incluídas:** não chama o ORS e põe `calculo None` (só se havia um).
  - **Falhas do ORS:**
    - sem chave → 503 `sem_chave` sem pedido;
    - 429 → 503 com a mensagem do limite;
    - 2010 no índice 0 → "O ponto de início…"; no índice 2 → "A paragem 2 …"; no último → "O ponto de fim…";
    - em todos estes casos **nada é escrito** (o registo do duplo não tem `find_one_and_update`).
  - **A versão muda entre a leitura e a escrita** (gancho) → 409 `conflito`.
  - **Registo:** `"[crm] rota 2026-10-12: o openrouteservice falhou (recalcular) — <motivo>"`, sem coordenadas e sem a chave (`caplog`).
- **Commit:** `CRM: horas da rota pelo Directions do openrouteservice`

#### [ ] T3.22 `POST /rotas/{data}/otimizar` — a melhor ordem pelo VROOM (60 min)
- **Ficheiros:** `backend/crm/rotas.py`, `backend/tests/crm/test_rotas_otimizar.py`.
- **Teste primeiro.** Falha com 405.
  - **O pedido ao VROOM** (capturado): sem canários (nomes, telefones e uuids), prioridades 100/1 e as janelas `[a, b − s]`.
  - **Depois, o Directions** pela ordem devolvida.
  - **A escrita** (`find_one_and_update` com `$inc versao`):
    - a `ordem` da ordem do VROOM, depois as `nao_cabe` (não atribuídas + impossíveis), depois as fechadas;
    - os sinais `nao_cabe`;
    - as horas, com `None` nas `nao_cabe`;
    - o `calculo`.
  - **As fechadas sem "Manter"** não vão ao VROOM.
  - **Falhas** (nada muda):
    - o VROOM falha → 503, sem Directions;
    - o VROOM responde bem e o Directions falha → 503 e nada muda (**atómico**);
    - uma resposta inválida do VROOM (um *job* desconhecido) → 503.
  - **Zero *jobs*** → 200 sem chamar.
  - **O cenário da prioridade:** 1 entrega + 11 visitas, com a fixture onde só a entrega é atribuída → a entrega fica na rota e as visitas em `nao_cabe`. O comportamento do VROOM verdadeiro é risco R3, a confirmar com a gravação.
- **Commit:** `CRM: calcular a melhor ordem com o VROOM e as horas com o Directions`

#### [ ] T3.23 `GET /rotas/{data}/sugestoes` (40 min)
- **Ficheiros:** `backend/crm/rotas.py`, `backend/tests/crm/test_rotas_sugestoes.py`.
- **Teste primeiro.** Falha com 404.
  - **Sem rota ou sem paragens** → `sem_paragens: true`.
  - **Com paragens:** os grupos do domínio; a projeção das lojas é exatamente `{"_id": 0, "id", "nome", "fase", "lat", "lng", "dias_fechada"}` (nunca o telefone).
  - **Corredor:** com `calculo.atual` usa a geometria; com o cálculo velho, não.
  - **Uma rota passada** também responde (leitura).
- **Commit:** `CRM: sugestões de lojas para aproveitar a viagem`

#### [ ] T3.24 O terreno ganha, e uma loja numa rota não se apaga (50 min)
- **Ficheiros:** `backend/tests/crm/test_rotas_terreno.py`, `backend/crm/lojas.py`, `backend/crm/erros.py` (`loja_em_rota`), `backend/tests/crm/test_lojas_apagar.py`.
- **Teste primeiro.** Falha pelo código em falta, pelo `DELETE` que ainda apaga e pelos testes de varrimento.
  - **Rota com registo do motorista** (uma paragem `feita`, com `resultado "interessado"`, `concluida_em` e um `client_uuid`): o `POST` de paragens, cada forma do `PATCH`, o `recalcular` e o `otimizar` → 409 `rota_em_curso`, e os campos dessa paragem ficam **iguais ao byte** (`sem_id()` antes e depois).
  - **Corrida:** o gancho `antes_de` grava `paragens.0.estado = "feita"` entre a leitura e a escrita de cada rota de escrita → 409 `rota_em_curso`, e nada do escritório fica escrito.
  - **Varrimento:** uma sequência real (adicionar 3, reordenar, mudar motivo, manter, retirar, recalcular, otimizar e guardar) → todas as atualizações registadas passam em `escritas_no_terreno == []`.
  - **`DELETE /lojas/{id}`:**
    - numa paragem ativa → 409 `loja_em_rota`;
    - só numa paragem retirada e `pendente` → apaga;
    - numa paragem retirada `feita` → 409.
  - A ordem do `DELETE` passa a ser 404 → `loja_com_historico` → `loja_em_rota` (`rotas_bd.rotas_com_loja` + uma regra pura em `dominio/rotas.loja_presa_em_rota`).
- **Commit:** `CRM: escritas do escritório nunca tocam no que o motorista registou`

#### [ ] T3.25 Ensaio no MongoDB local: rotas (45 min)
- **Ficheiros:** `backend/tests/crm/test_mongo_local.py`.
- **Testes** (correm com `CRM_MONGO_TESTE_URL`; sem ela saltam com a razão de sempre), na base `lisbonb_crm_teste`, apagada no início e no fim:
  - o `criar_indices` verdadeiro deixa em `crm_rotas` exatamente `_id_`, `id_1`, `data_1` e `paragens.loja_id_1`;
  - a mesma `data` duas vezes → `DuplicateKeyError`;
  - o `explain` de `{"paragens.loja_id": …}` usa `paragens.loja_id_1`;
  - `$push` + `$inc` condicional; `$set paragens.1.ordem` + `$inc` com o filtro de guarda: casa antes e **não** casa depois de um `$set paragens.1.estado: "feita"`;
  - `$push paragens` + `$set paragens.0.x` → `WriteError` código 40 (prova que o duplo modela o Mongo);
  - `$gte`/`$lte` em datas de texto pela ordem do tempo;
  - pelas rotas com o Motor e a **barreira** da T2.17: dois `POST /paragens` sem versão ao mesmo tempo → as duas paragens ficam, com a versão 3; dois `PATCH` com a mesma versão → um 200 e um 409;
  - a rota gravada passa em `instantes_fora_do_formato`.
- **Verificar:** o ensaio com a variável e a bateria sem ela.
- **Commit:** `CRM: ensaio das rotas no MongoDB local`

### Bloco F3d — Frontend: módulos puros (Jest)

#### [ ] T3.26 `lib/crm`: datas, polyline, atribuição do ORS e `hrefNavegacao` (45 min)
- **Ficheiros:** `frontend/src/lib/crm/{datas,polilinha}.js` (+ testes), `atribuicoes.js` (+ teste), `dom.js` (+ `dom.test.js`), `seguranca.test.js` (lista).
- **Teste primeiro.** Falha por `Cannot find module './datas'` e `'./polilinha'`, e pelo `ATRIBUICOES.ors` indefinido.
  - **`datas.js`:**
    - `eDataValida('2026-02-29') === false`;
    - `somarDias('2026-10-24', 2) === '2026-10-26'` (aritmética ao meio-dia UTC, sem efeito da mudança de hora);
    - `diaDaSemana('2026-10-12') === 'seg'`;
    - `rotuloDia('2026-10-12', '2026-10-12') === 'Hoje'`, `'Amanhã'`, `'seg 19/10'`;
    - `rotuloDataLonga('2026-10-12') === 'segunda-feira, 12 de outubro'` (listas fixas de nomes, sem `Intl`).
  - **`polilinha.js` (`descodificarPolilinha`):** o mesmo exemplo da Google do Python; `''` → `[]`; um texto estragado → `[]`.
  - **`ATRIBUICOES.ors.texto`** `=== 'Developed by VROOM · Hosted by HeiGIT · Routing by openrouteservice · Data from OpenStreetMap'`, com partes ligadas a `http://vroom-project.org/`, `https://heigit.org/`, `https://openrouteservice.org/` e ao copyright do OSM.
  - **`hrefNavegacao(url)`:** só `https://www.google.com/maps/dir/?api=1&…` e `https://waze.com/ul?…`, sem espaços, aspas nem `<`/`>`; o resto dá `null` (`javascript:`, `http:`, outro domínio, texto com `"`).
- **Commit:** `CRM: datas, linha da rota e atribuição do openrouteservice no frontend`

#### [ ] T3.27 `lib/crm/rota.js`: motivos, secções, avisos, totais e consistência com o servidor (45 min)
- **Ficheiros:** `frontend/src/lib/crm/rota.js` (+ teste), `backend/tests/crm/test_consistencia_frontend.py`.
- **Teste primeiro.** No Jest falha por `Cannot find module './rota'`. No pytest falha por não encontrar as linhas.
  - **Uma só linha cada:**
    - `export const MOTIVOS = Object.freeze(['entrega', 'amostra', 'acompanhamento', 'angariacao']);`;
    - `export const MOTIVO_POR_FASE = Object.freeze({ … });`;
    - `export const LIMITE_PARAGENS = 48;`.

    O pytest compara-as com `dominio.rotas`.
  - **Rótulos e textos:**
    - `ROTULOS_MOTIVO`: Entrega, Amostra, Acompanhamento, Angariação;
    - `ROTULOS_ESTADO`: Rascunho, Planeada, Em curso, Concluída;
    - `TEXTOS_AVISO`: `fechada_neste_dia` → '⚠️ Fechada neste dia', `nao_cabe` → '⚠️ Não cabe no horário', `fora_de_horario` → '⚠️ Fora do horário de receção';
    - `textoDistancia(123456)` → '123,5 km'; `textoDuracao(19260)` → '5 h 21 min'.
  - **`seccoesDaRota(rota)`** → `{rota, fechadas, naoCabem, semLoja}`.
  - **`avisosDaRota(rota)`:**
    - 'Regresso previsto às 19:40 — depois do limite (19:00).';
    - '2 paragens fechadas neste dia ficam fora do cálculo até escolher "Manter".';
    - '1 paragem não cabe no horário.'.
  - **`precisaDeHoras(rota, {falhou})`:** `calculo_disponivel && editavel && incluídas ≥ 1 && !calculo?.atual && !falhou`.
  - **`perguntaGuardar(rota)`** → '2 paragens não cabem — guardar mesmo assim?' ou `null`.
  - **`aplicarLocalmente(rota, corpo)`** (a visão otimista): ordem, retirar, motivo, tempo, sinais e definições. Devolve uma rota nova e deixa os números da secção `rota` coerentes.
  - **`corpoOrdem(rota, idsRota)`** → as ids da secção rota + as `nao_cabe` + as fechadas.
- **Commit:** `CRM: textos e secções da rota no frontend`

#### [ ] T3.28 `lib/crm/reordenar.js`: arrastar com rato, toque e teclado (45 min)
- **Ficheiros:** `frontend/src/lib/crm/reordenar.js` (+ teste).
- **Teste primeiro.** Falha por `Cannot find module`.
  - **`mover(lista, de, para)`:** devolve uma lista nova, limitada às pontas.
  - **`indiceDestino(y, caixas, de)`:** conta as linhas (sem a arrastada) com o meio acima de `y`. Casos: para baixo, para cima, para lá das pontas, no mesmo sítio.
  - **`deveIniciarArrasto(dx, dy)`:** só depois de 4 px.
  - **`teclaNaLista(estado, {tecla, indice, total, nome})`** → `{estado, acao, anuncio}`:
    - Espaço ou Enter pega: "Paragem 3, Café X, pegada. Posição 3 de 10. Use as setas para mover, Espaço para largar ou Escape para cancelar.";
    - as setas movem: "Posição 4 de 10.";
    - Espaço ou Enter larga (`acao {tipo:'largar', de, para}`): "Café X largada na posição 4 de 10.";
    - Escape cancela: "Movimento cancelado. Café X voltou à posição 3.";
    - o Tab ou a perda do foco com a paragem pegada cancela;
    - as setas sem nada pegado não fazem nada.
  - **`INSTRUCOES_ARRASTAR`:** "Para reordenar: Espaço ou Enter para pegar, setas para mover, Espaço para largar, Escape para cancelar. Também pode arrastar a pega com o rato ou o dedo."
- **Commit:** `CRM: regras para reordenar paragens com rato, toque e teclado`

#### [ ] T3.29 `lib/crm/api.js`: chamadas da F3 (30 min)
- **Ficheiros:** `frontend/src/lib/crm/api.js`, `api.test.js`.
- **Teste primeiro.** Falha por `… is not a function`. Com um `pedir` falso:
  - **`listarRotas({de, ate})`** → `GET /rotas`, com `semNulos`.
  - **Por dia** (`caminhoComId('/rotas', data)`):
    - `obterRota(data)` → `GET /rotas/2026-10-12`;
    - `obterSugestoes(data)` → `/sugestoes`.
  - **Escritas:**
    - `adicionarParagem(data, {loja_id, motivo, versao})` → POST `/paragens`. Sem `versao` (`undefined`) a chave **não vai**; com `null` vai `null`;
    - `alterarRota(data, corpo)` → PATCH.
  - **Cálculo:** `recalcularHoras(data, versao)` e `otimizarRota(data, versao)` → POST com `{versao}` e `timeout: TIMEOUT_CALCULO_MS` (35000).
  - **Pedaços proibidos:** uma data `'..'` → `erro_interno`.
- **Commit:** `CRM: chamadas da API das rotas no frontend`

#### [ ] T3.30 `lib/crm/filaRota.js`: um pedido de cada vez, alterações juntas e versão em vigor (50 min)
- **Ficheiros:** `frontend/src/lib/crm/filaRota.js` (+ teste).
- **Teste primeiro.** Falha por `Cannot find module`. Com promessas controladas e os `jest.fn` dentro de cada teste:
  - **`juntarAlteracoes(a, b)`:** as definições, a última vence; `ordem`, a última vence; `paragens` juntam-se por id e campo; `retirar` é a união, e tira esses ids da `ordem` e das `paragens`; `estado`.
  - **`criarFilaRota({enviar, versao})`:**
    - um só pedido em curso; os `alterar` pendentes juntam-se num;
    - `adicionar`, `otimizar` e `recalcular` não se juntam, e vários `recalcular` pendentes ficam um;
    - cada pedido sai com a versão da **última resposta**;
    - um 409 (`conflito`, `rota_em_curso`, `rota_fechada`) rejeita o pedido em curso e todos os pendentes, e a fila fica `parada` até `retomar(versao)`;
    - outro erro rejeita só esse pedido, e os seguintes continuam;
    - `vazia`, `ocupada` e `versao` são *getters*.
- **Commit:** `CRM: fila das gravações da rota com versão em vigor`

#### [ ] T3.31 `lib/crm/planeador.js` (1/2): carregar, vista, leitura só e sugestões (60 min)
- **Ficheiros:** `frontend/src/lib/crm/planeador.js` (+ teste).
- **Teste primeiro.** Falha por `Cannot find module`.
  - **`criarPlaneador({api, rede, data, base, navegar, aoMudarVista, aoAvisar})`** → `{vista, iniciar, tentarDeNovo, recarregar, destruir, …}`.
  - **`iniciar()`:** pede `obterRota` e `obterConfigMapa`/`listarLojas` ao mesmo tempo, e depois `obterSugestoes`.
  - **A `vista`, congelada:**
    ```
    {estado: 'a_carregar'|'falha'|'rota'|'data_invalida', titulo: 'Rota de segunda-feira, 12 de outubro',
     somenteLeitura, rotuloEstado, falha, conflito, semRede,
     definicoes: {hora_saida, hora_regresso_limite, inicio, fim, evitar_portagens, ativas},
     totais: null|{distancia, duracao, regresso, regressoTarde, atual}, avisos: [texto],
     seccoes: {rota: [linha], fechadas: [linha], naoCabem: [linha]},
     linha = {id, numero, nome, fase, motivo, rotuloMotivo, tempo, chegada, espera, textoAviso, google, waze, podeSubir, podeDescer},
     sugestoes: {estado, grupos, mensagem}, mapa: {paragens, inicio, fim, linha, linhaAtual, lojasForaDaRota},
     acoes: {calcular, recalcular, guardar}, calculo: {aCalcular, mensagem}, blocosGoogle, atribuicaoOrs,
     limite: {cheia, texto}, escolherPonto: null|'inicio'|'fim', lojaEscolhida}
    ```
  - **Leitura só** (dia passado, `em_curso`, `existe false` no passado: "Não houve rota neste dia.") → sem ações e `seccoes` sem `podeSubir`.
  - **Uma data inválida** → `data_invalida`.
  - **A falha** → a mensagem (`textoDoErro`) e "Tentar novamente".
  - **Sem rede** (`rede.online() false`) → `semRede` e as ações desligadas.
  - **`destruir()`** faz que as respostas que chegarem depois não façam nada.
- **Commit:** `CRM: ecrã do planeador sem DOM — carregar e mostrar`

#### [ ] T3.32 `lib/crm/planeador.js` (2/2): ações, horas automáticas, calcular, guardar e conflitos (60 min)
- **Ficheiros:** `frontend/src/lib/crm/planeador.js` (+ teste).
- **Teste primeiro.** Falha por `planeador.mover is not a function`, etc.
  - **As ações:**
    - `adicionar(lojaId, motivo?)` mostra "A adicionar…" e não é otimista;
    - `retirar(id)`, `mover(de, para)` e `subir`/`descer(id)` são otimistas, por `aplicarLocalmente`;
    - também `mudarMotivo`, `mudarTempo`, `manter(id)`, `porNaRota(id)`, `mudarDefinicao(chave, valor)`, `escolherPonto('inicio'|'fim')`, `tocarNoMapa(ponto)` (grava `{inicio: {lat, lng}}`), `usarFabrica('inicio')`, `escolherLoja(loja)` e `calcularMelhorOrdem()`;
    - `guardar()` pergunta pelo `perguntaGuardar` (`vista.acoes.guardar.pergunta` + `responderGuardar(sim)`).
  - **Horas automáticas:** com a fila vazia e `precisaDeHoras`, `recalcularHoras(versao)` corre uma só vez. Um 503 mostra a `mensagem`, deixa `falhou` e não volta a tentar sozinho até à próxima alteração ou ao botão.
  - **Sem `calculo_disponivel`:** nunca recalcula. O "Calcular melhor ordem" fica desligado com "Cálculo automático indisponível — ordene à mão".
  - **Conflitos:**
    - um 409 `conflito` → a faixa "Alterado por outra pessoa — recarregar", e o "Recarregar" pede a rota e `retomar`;
    - `rota_em_curso`/`rota_fechada` → só leitura, com a mensagem.
  - **Outros erros:** um 422 ou um `sem_rede` desfaz o otimista e mostra a mensagem.
  - **Avisos:** "Adicionada", "Retirada" e "Rota guardada como planeada" vão para o `aoAvisar`.
  - **As sugestões** voltam a pedir-se depois de a fila esvaziar e depois de cada recálculo.
- **Commit:** `CRM: ecrã do planeador sem DOM — ações, horas e conflitos`

#### [ ] T3.33 `lib/crm/mapa.js`: pinos numerados, extremos e a linha da rota (50 min)
- **Ficheiros:** `frontend/src/lib/crm/mapa.js`, `mapa.test.js`, `testes/leafletFalso.js` (`polyline` e `getElement` com `appendChild`), `seguranca.test.js`.
- **Teste primeiro.** Falha por `mostrarRota is not a function`.
  - **`mostrarRota({paragens: [{numero, lat, lng, fase, nome, aviso}], inicio, fim, linha, linhaAtual}, {aoEscolherParagem})`.**
  - **Pinos numerados:**
    - um grupo próprio por cima das lojas;
    - cada pino é um `divIcon` com `className 'pino-paragem pino--<fase>'` (+ `' pino-paragem--aviso'`) e **sem `html`**;
    - no `add`, o elemento do marcador recebe `el(documento, 'span', {texto: '3', classe: 'pino-paragem__numero'})`;
    - `title` "3. Café X"; a etiqueta permanente com `el()`; `zIndexOffset`;
    - o teclado escolhe a paragem.
  - **Extremos:** um só pino "Início e fim: fábrica" quando são iguais; senão "Início" e "Fim".
  - **Linha:** `L.polyline(linha, {className: 'crm-linha-rota' | 'crm-linha-rota crm-linha-rota--antiga', interactive: false})` só com ≥ 2 pontos; uma rota nova substitui a anterior.
  - **`enquadrarRota()`:** `fitBounds` das paragens e dos extremos.
  - **Segurança:** o `seguranca.test.js` continua verde (`bindTooltip` só no `mapa.js`, com `el(`).
- **Commit:** `CRM: pinos numerados e linha da rota no mapa`

#### [ ] T3.34 `lib/crm/adicionarARota.js` e `lib/crm/definicoesRotas.js` (50 min)
- **Ficheiros:** os dois módulos (+ testes).
- **Teste primeiro.** Falha por `Cannot find module`.
  - **`criarAdicionarARota({api, loja, base, navegar, aoMudarVista, aoAvisar})`:**
    - `iniciar()` pede `listarRotas()`;
    - `diaPorOmissao({hoje, rotas})` dá a primeira rota editável a partir de hoje, ou senão hoje;
    - a vista leva até 5 atalhos ("Hoje · 5 paragens", "ter 13/10 · 8 paragens"), a data escolhida (`min` = hoje), o motivo pré-escolhido (`motivoPorFase`) e "Adicionar";
    - com sucesso: `aoAvisar('Adicionada à rota de ter 13/10 (9 paragens).', {acao: 'Abrir rota', href})`;
    - os erros `ja_na_rota`, `rota_cheia`, `rota_fechada` e `sem_rede` com a mensagem do servidor;
    - um pedido de cada vez.
  - **`criarDefinicoesRotas({api, …})`:**
    - os 6 campos ("Hora de saída", "Hora limite de regresso" e "Tempo de serviço (min)" por motivo);
    - `corpoDefinicoesRotas(original, valores)` só com as chaves alteradas (os minutos como inteiros);
    - "Definições das rotas guardadas.";
    - o 422 junto de cada campo.
- **Commit:** `CRM: regras de "Adicionar à rota" e das definições das rotas`

#### [ ] T3.35 Menu, rotas das páginas e ecrã cheio do planeador (30 min)
- **Ficheiros:** `frontend/src/lib/crm/acesso.js` (+ teste), `pages/crm/rotasCrm.js`, `components/layouts/CrmLayout.js` (`ICONES.rotas = Route`), `components/crm/seccaoCrm.js` (o mesmo ícone).
- **Teste primeiro.** No `acesso.test.js` falha porque `itensMenuCrm` ainda tem 3 itens.
  - **Menu:** `ITENS_MENU_CRM` passa a Mapa, **Rotas** (`caminho 'rotas'`), Nova loja e Definições.
  - **`ecraCheioDoCrm`:** dá verdadeiro em `/crm/rotas/2026-10-12` e em `/admin/crm/rotas/2026-10-12/`; falso em `/crm/rotas` e `/crm/rotas/abc`.
- **Implementação:** `rotasCrm.js` ganha `rotas` → `CrmRotas` e `rotas/:data` → `CrmRota` (`React.lazy` e `pagina(...)`), antes do `*`. **Nem o `App.js` nem o `AdminLayout.js` mudam.**
- **Commit:** `CRM: item Rotas no menu e páginas do planeador`

### Bloco F3e — Componentes e páginas

> Receita de verificação dos componentes, igual à das T1.12–T2.30:
> - **Verificação temporária, não versionada**, em `$LOGS/t3.N-verificacao/` (React 19 `act` + `createRoot`, `MemoryRouter`, Leaflet verdadeiro no jsdom, API falsa, `t112-jest.sh` com o polyfill), com mutações;
> - **ESLint do CRA** (receita da T1.13, `--max-warnings 0`);
> - **browser local**, com o Playwright sem janela e o simulador do ORS (8013) e o backend (8001) em segundo plano, parados no fim; as palavras-passe nunca se imprimem;
> - cada ficheiro novo entra na lista do `seguranca.test.js`.

#### [ ] T3.36 `ListaParagens`, `MapaLojas` com a rota e o CSS do planeador (60 min)
- **Ficheiros:** `components/crm/ListaParagens.js`, `components/crm/MapaLojas.js` (os `props` `rota`, `classe` e `aoEscolherParagem`), `components/crm/crm.css`, `lib/crm/css.test.js` (escrito antes do CSS).
- **`css.test.js` primeiro.** Falha por faltarem as regras:
  - `.pino-paragem__numero` com cor fixa legível;
  - `.pino-paragem--aviso`;
  - `.crm-linha-rota` com o traço roxo `#6b2fa3` e `--antiga` tracejada;
  - `.crm-mapa--planeador .pino` esbatido;
  - `.crm-pega` com `touch-action: none` e 44 × 44 px;
  - `.crm-planeador` em grelha de 2 colunas a partir de 1024 px.
- **`ListaParagens`:**
  - `<ol>` de linhas, cada uma com uma pega `<button aria-roledescription="pega para arrastar" aria-describedby=…>`;
  - Pointer Events com `setPointerCapture`, o destino por `indiceDestino` e a linha a seguir o dedo (`translateY`);
  - deslocar a lista perto das pontas;
  - o teclado por `teclaNaLista`, numa região `aria-live="assertive"`;
  - o detalhe (Radix `Collapsible`) com o motivo, o tempo, "Subir"/"Descer", "Retirar" e os links Google Maps/Waze (`<a href={hrefNavegacao(...)} target="_blank" rel="noopener">`);
  - em leitura só, sem pega nem botões.
- **Verificar:** a verificação temporária (arrastar com eventos de ponteiro sintéticos e com o teclado) e o browser (rato e emulação de toque a 375 × 812).
- **Commit:** `CRM: lista de paragens arrastável e mapa com a rota`

#### [ ] T3.37 Página "Rotas": lista e escolha do dia (40 min)
- **Ficheiros:** `pages/crm/CrmRotas.js`.
- **Conteúdo:**
  - `PageHeader` "Rotas";
  - um campo de data e "Abrir" (`navegar(`${base}/rotas/${data}`)`);
  - "Hoje";
  - as listas "Próximas" e "Anteriores" a partir do `listarRotas()` (com `rotuloDia` e `ROTULOS_ESTADO`, por exemplo "seg 12/10 · Planeada · 9 paragens");
  - falha com "Tentar novamente".
- **Verificar:** o browser (computador e telemóvel).
- **Commit:** `CRM: página das rotas com escolha do dia`

#### [ ] T3.38 Planeador (1/2): mapa, painel e leitura só (60 min)
- **Ficheiros:** `pages/crm/CrmRota.js`, `components/crm/ResumoRota.js`.
- **Conteúdo:**
  - **Ligação ao controlador:** a página liga `criarPlaneador` (com o `useEffect` e o `destruir`).
  - **Disposição:** em computador, o painel lateral (≤ 440 px) e o mapa (`MapaLojas` com `classe 'crm-mapa--planeador'`, `lojas = vista.mapa.lojasForaDaRota` e `rota = vista.mapa`).
  - **Resumo e ações:** o `ResumoRota` tem o estado, os totais, os avisos, os botões das ações (desligados com o motivo), os blocos do Google e o rodapé com a atribuição do ORS, desenhada a partir de `ATRIBUICOES.ors.partes` (texto e `href`).
  - **Secções:** a `ListaParagens` "Rota", "⚠️ Fechadas neste dia" e "⚠️ Não cabem no horário".
  - **Leitura só:** "Concluída — só de leitura".
  - **Dias estranhos:** "Dia inválido", ligado às Rotas.
- **Verificar:** o browser com a base local + seed + o simulador:
  - os pinos numerados e a linha;
  - a atribuição exata do ORS visível em 1280 × 800;
  - a rota de ontem só de leitura.
- **Commit:** `CRM: planeador de rota — mapa, painel e leitura`

#### [ ] T3.39 Planeador (2/2): definições do dia, arrastar, sugestões, calcular e guardar (60 min)
- **Ficheiros:** `pages/crm/CrmRota.js`, `components/crm/{DefinicoesDoDia,SugestoesRota}.js`.
- **Conteúdo:**
  - **`DefinicoesDoDia`:** horas (`<input type="time">`), início e fim ("Fábrica" ou "Ponto no mapa", com a faixa "Toque no mapa no ponto de início" e "Cancelar") e "Evitar portagens" (`Switch`).
  - **`SugestoesRota`:** os grupos com a distância ("1,2 km" / "no caminho, 0,8 km") e "Adicionar".
  - **No mapa:** um toque numa loja esbatida → o cartão pequeno "Adicionar à rota".
  - **Botões:** "Calcular melhor ordem" (com "A calcular…"), "Recalcular horas" e "Guardar rota", com o `AlertDialog` "N paragens não cabem — guardar mesmo assim?".
  - **Avisos:** toasts do `sonner`.
- **Verificar no browser:**
  - adicionar 6 lojas do seed;
  - calcular (simulador) e ver a ordem, as horas e o regresso;
  - arrastar com o rato e ver as horas recalculadas sozinhas;
  - reordenar com o teclado e ouvir o anúncio (ler a região `aria-live`);
  - "Manter" uma loja fechada nesse dia;
  - o 409 com dois separadores (`tabs_create`);
  - parar o simulador e ver a mensagem "Cálculo automático indisponível — ordene à mão", e a ordem manual que se guarda;
  - Guardar → "Planeada".
- **Commit:** `CRM: planeador de rota — arrastar, sugestões, calcular e guardar`

#### [ ] T3.40 "Adicionar à rota" no cartão do mapa (45 min)
- **Ficheiros:** `components/crm/DialogoAdicionarARota.js`, `components/crm/CartaoLoja.js` (o botão "Adicionar à rota", com o ícone `Route`, e o comentário do topo atualizado), `pages/crm/CrmMapa.js` (o estado do diálogo).
- **Conteúdo:** um `Dialog` do Radix com os atalhos dos dias, a data, o motivo (`Select`), "Adicionar" e "Cancelar"; com sucesso, o toast com "Abrir rota".
- **Verificar no browser:** uma loja contactada → motivo "Amostra"; repetir → "Esta loja já está na rota deste dia."; um dia passado no campo → recusado (`min` e 409); telemóvel 375 × 812 sem deslocamento para o lado.
- **Commit:** `CRM: adicionar à rota a partir do cartão da loja`

#### [ ] T3.41 Definições → separador "Rotas" (40 min)
- **Ficheiros:** `pages/crm/DefinicoesRotas.js`, `pages/crm/CrmDefinicoes.js` (o 4.º separador, "Rotas", com o ícone `Route`).
- **Verificar no browser:** mudar a saída para 07:30 → a rota virtual de um dia sem rota mostra 07:30; o regresso antes da saída → 422 junto do campo.
- **Commit:** `CRM: definições das rotas no ecrã de definições`

#### [ ] T3.42 Política de privacidade: o openrouteservice (20 min)
- **Ficheiros:** `frontend/src/pages/PrivacyPolicy.js` (**partilhado**), `lib/crm/privacidade.test.js`.
- **Teste primeiro.** No `privacidade.test.js` falha por faltar o texto:
  - a secção 8 ganha uma frase que nomeia o openrouteservice (HeiGIT), para calcular a ordem e as horas das rotas: o servidor só lhe envia coordenadas das lojas e números, nunca dados pessoais;
  - a atribuição "Developed by VROOM · Hosted by HeiGIT · Routing by openrouteservice · Data from OpenStreetMap".
- **A redação** fica marcada para revisão pelo dono (§14, ponto 7). `git diff --stat` dá cerca de +3/−1.
- **Commit:** `CRM: política de privacidade nomeia o openrouteservice`

### Bloco F3f — Fecho

#### [ ] T3.43 Fecho da F3 com pré-visualização local (60 min)
- **Suites:**
  - `pytest tests/crm` verde;
  - `test_mongo_local.py` com a variável, verde;
  - a suite completa em segundo plano: `failed` igual ao de partida e `skipped` sem subir;
  - `grep -rn "asyncio.run(" backend/tests/crm` vazio;
  - Jest `src/lib` verde;
  - o build em segundo plano sem erros, com o planeador num *chunk* à parte e o `main` sem `leaflet-container`.
- **Pré-visualização:**
  - parar a da F2 (dossiê §12.6);
  - acrescentar ao `backend/.env.local`, **sem mostrar valores** e só se `grep -c "^CRM_ORS" .env.local` der 0: `printf 'CRM_ORS_URL=http://127.0.0.1:8013\nCRM_ORS_CHAVE=simulador-local\n' >> "$RAIZ/backend/.env.local"`;
  - arrancar em segundo plano o simulador (8013), o backend (8001) e o frontend (3000).
- **Aceitação F3 (§8) no browser local** (`$LOGS/t343_aceitacao.py`, receita da T2.32):
  - corre numa cópia `lisbonb_crm_t343_local` **sem palavras-passe**, apagada no fim, com o computador em 1280 × 800 claro e o telemóvel em 375 × 812 escuro;
  - no fim, cria na `lisbonb_crm_local` uma rota de demonstração para o próximo dia útil, com 8 lojas do seed, calculada pelo simulador, para o dono a abrir em `http://127.0.0.1:3000/crm/rotas/<data>`.
- **Dossiê `CRM_PORTING_GUIDE.md`:**
  - §3 (`crm_rotas` e os índices);
  - §5.13 (o contrato do terreno);
  - §5.14 → §5.16 "Planear rota (F3)", com as regras deste plano;
  - §6 (a API e os códigos);
  - §7 (os ecrãs);
  - §8 (o ORS: chave no cabeçalho, tempos, mensagens, atribuição, simulador e gravador);
  - §9 (`CRM_ORS_CHAVE`, `CRM_ORS_URL`);
  - §12.6/§12.7 (o simulador; a pré-visualização a correr e como parar as 3 portas);
  - §13 (as contagens);
  - §14:
    - o ponto 5 (criar a conta do ORS), agora com "correr o `gravar_respostas_ors.py`";
    - **novo:** confirmar com a gravação que o Directions devolve os `segments` com `instructions: true` e que o VROOM mantém a entrega no cenário da T3.22;
    - **novo:** a F3 em produção só depois de haver lojas reais nas regiões da primeira rota (desenho §6);
    - o ponto 6 (avisar o Matheus do `.env.example` e da `PrivacyPolicy.js`);
    - o ponto 7 (a redação nova da privacidade);
    - o ponto 11 (os blocos de 9, na F4).
- **Commit:** só se houver correções ou dossiê, `CRM: fecho do planear rota (F3) verificado em local`. **Nada sai do Mac.**

#### [ ] Revisão da F3 (3 revisores só de leitura)
- Fidelidade ao desenho, segurança (chave e dados pessoais) e o terreno. Os achados entram como correções, com vermelho, verde e mutações, no molde das revisões da F0/F1 e da F2.

---

## 7. Fora deste plano (YAGNI) e ganchos deixados
- **F5:**
  - encomendas: `motivo_por_fase` passa a dar `entrega` com uma encomenda pendente até ao dia, e as entregas entram sozinhas ao criar a rota;
  - alertas 🔁 ⏰, com a prioridade 2 em `dominio.rotas.prioridade` e os grupos 0–2 nas sugestões;
  - "sem visita com sucesso nos últimos 7 dias" nas sugestões (comentário no `sugestoes.py`);
  - o fecho noturno, que grava `concluida` e marca `nao_visitada`;
  - `ROTAS_DE_CRON`.
- **F4:**
  - o `/rota` do motorista, a fila sem rede e os registos;
  - a edição de rotas `em_curso`: recalcular a partir da última paragem concluída, à hora atual;
  - os perfis do motorista nas rotas;
  - o contrato das escritas do terreno (§3);
  - confirmar no telemóvel da carrinha os blocos de 9.
- **Depois:**
  - apagar uma rota inteira;
  - notas do escritório por paragem;
  - raio, corredor e bloco do Google configuráveis;
  - "mudar de dia" uma paragem que não cabe.
- **Ganchos:**
  - `CAMPOS_DO_TERRENO` e `caminhos_paragem`;
  - a guarda `"paragens.estado": {"$nin": […]}` em `rotas_bd.alterar`;
  - `bloqueio_de_escrita`, onde a F4 abre exceções;
  - `rota_api` com `estado` e `resultado` por paragem.

## 8. Listas de aceitação (F3, em local)
- [ ] **Domínio:**
  - janelas em segundos, iguais nos dias de mudança de hora;
  - prioridades 100/1;
  - pedidos ao VROOM e ao Directions só com números (canários);
  - leitura das respostas com validação;
  - esperas (também a 2.ª janela), `fora_de_horario` só sem janela, regresso tarde e horas depois da meia-noite;
  - assinatura;
  - sugestões (5 km, 3 km, grupos, exclusões);
  - links e blocos de 9.
- [ ] **ORS:**
  - a chave só no `Authorization`, nunca no URL, nas mensagens ou nos registos (chave canária em DEBUG);
  - sem chave → 503 sem chamar;
  - 429, 2010 e falhas da rede → mensagens pt-PT;
  - nenhum teste sai para a rede.
- [ ] **API:**
  - uma rota por dia; criar pelo cartão sem versão; 48 paragens; já na rota;
  - o passado só de leitura (409 nas escritas, `concluida` ao ler);
  - a versão → 409;
  - retirar suave;
  - a loja numa rota não se apaga;
  - as definições das rotas.
- [ ] **O terreno ganha:**
  - nenhuma escrita do escritório usa `$pull`, `$unset` nem a lista inteira, nem toca nos campos do terreno (varrimento);
  - com um registo do motorista, tudo 409 e nada muda (também na corrida).
- [ ] **Cálculo:**
  - "Calcular melhor ordem" → horas, esperas, avisos e "não cabem" no fim sem hora;
  - uma falha não muda nada e mostra a mensagem;
  - as horas recalculadas sozinhas depois de arrastar, adicionar, retirar e mudar as definições do dia;
  - sem ORS, a ordem manual guarda-se sem horas.
- [ ] **Planeador** (1280 × 800):
  - mapa e lista lateral, pinos numerados, linha, totais, hora por paragem e ⚠️;
  - a **atribuição exata do ORS**;
  - Google Maps/Waze por paragem (com o `avoid` quando se evitam portagens) e blocos de 9;
  - arrastar com o rato, o teclado (com anúncios) e o toque (375 × 812);
  - Guardar → Planeada, com a pergunta dos "não cabem".
- [ ] **Leitura:** a rota de um dia passado só de leitura; um dia passado sem rota → "Não houve rota neste dia.".
- [ ] **Cartão do mapa:** "Adicionar à rota" com o dia e o motivo pela fase, e as mensagens de já na rota, cheia e dia passado.
- [ ] **Definições:** o separador Rotas (horas e tempos por motivo).
- [ ] **Segurança e suites:**
  - o varrimento do DOM verde; os `href` de navegação só pelo `hrefNavegacao`;
  - o ensaio no MongoDB local verde;
  - as suites sem falhas novas; o build com o planeador à parte.
- [ ] **Pré-visualização:** a correr (8013, 8001 e 3000), com a rota de demonstração.
- [ ] **Nada saiu do Mac.**

## 9. Riscos e mitigação

| # | Risco | Mitigação |
|---|---|---|
| R1 | A chave do ORS nos registos ou no URL | Só no cabeçalho; os registos do `httpx`/`httpcore` em WARNING; o motivo sem `str(exc)`; teste com chave canária em DEBUG em todos os caminhos (T3.11). |
| R2 | O Directions sem `segments` com `instructions: false` (comportamento do ORS) | Pedir com `instructions: true`; `interpretar_direcoes` falha alto se faltarem; confirmar com o gravador (§14). |
| R3 | O VROOM verdadeiro difere das respostas escritas à mão (formato, prioridades) | Parser estrito com `RespostaInvalida` → 503; os testes de valores com respostas construídas no teste; regravar (§14). |
| R4 | Dados pessoais no ORS | Construção só a partir de números; lista branca de chaves; canários (T3.6, T3.7, T3.22). |
| R5 | O escritório a sobrepor o motorista (F4) | Lista só de acrescentar, caminhos por índice só de campos do escritório, guarda `paragens.estado $nin`, varrimento e corridas simuladas (T3.24), ensaio no Mongo (T3.25). |
| R6 | `$push` e `$set paragens.N` na mesma atualização (código 40) | O adicionar só faz `$push` + campos de topo; o duplo modela o conflito; o ensaio confirma. |
| R7 | O limite de 40 pedidos por minuto do plano gratuito | A fila de um pedido; recálculo só com a fila vazia; o 429 com uma mensagem própria; não tentar de novo sozinho. |
| R8 | Horas erradas nos dias de mudança de hora | Só "HH:MM" → segundos; `hoje()` em `Europe/Lisbon`; testes a 2026-03-29 e 2026-10-25. |
| R9 | Horas velhas depois de mudar uma loja ou a fábrica | `calculo.assinatura` → `atual: false` → recálculo automático. |
| R10 | A gravação imediata é diferente do "Guardar" do original | Decisão do §1; "Guardar rota" = planeada; conflitos claros (409); a registar no dossiê para o dono ver na aceitação. |
| R11 | Arrastar acessível sem biblioteca | Regras puras com Jest, teclado, "Subir/Descer" e verificação no browser com toque emulado. |
| R12 | As sugestões lentas com o corredor | Rejeição por caixa e medição (T3.9); Douglas–Peucker se for preciso. |
| R13 | A mensagem do 2010 a mudar de texto | Expressão tolerante; sem número → a mensagem geral. |
| R14 | O simulador confundido com o ORS verdadeiro | Só escuta em 127.0.0.1; `metadata.simulador`; as linhas retas são visíveis; nota no dossiê; o gravador ignora o `CRM_ORS_URL`. |
| R15 | Choques com o Matheus | Só o `.env.example` e a `PrivacyPolicy.js`, cada um no seu commit e com o diff contado. |
| R16 | Documento da rota grande (geometria) | Polyline codificada (dezenas de KB); 48 paragens; longe do limite de 16 MB. |
| R17 | Corrida residual: uma loja apagada enquanto se adiciona | Aceite: a paragem fica com `loja: null` e `seccao "sem_loja"`, fora do cálculo, com "Retirar". |

## 10. Armadilhas de portagem (referência rápida)
- **Coordenadas:** o ORS e o GeoJSON usam `[lng, lat]`; o Leaflet usa `[lat, lng]`.
- **Pedido ao VROOM:** os ids dos *jobs* têm de ser **inteiros**; `priority` de 0 a 100; `service` e `time_windows` em segundos inteiros; `json.dumps(…, allow_nan=False)`.
- **Polyline:** precisão 5 só com `elevation: false`; com elevação a codificação muda.
- **Arredondamentos:** o `round()` do Python arredonda para o par; usar sempre `numeros.arredondar`. Uma hora a partir das 24:00 → `None`.
- **Relógio e datas:** no pacote `crm`, nunca `isoformat`, `strftime`, `today` nem `now` fora do `relogio.py` (varrimento AST). Datas por f-string.
- **Parâmetros:** `data`, `de` e `ate` leem-se como texto (`Optional[str]`), nunca como `date`/`int` do FastAPI (dariam o 422 em lista).
- **Semântica do Mongo:** `"paragens.estado": {"$nin": [...]}` sobre uma lista quer dizer "nenhum elemento". Uma lista vazia ou em falta casa.
- **Jest:** o CRA corre com `resetMocks`, por isso os `jest.fn` nascem dentro de cada teste; imports relativos, sem `@/`.
- **Jest e browser:** o jsdom não faz *layout*. As regras de arrastar são puras e o resto vê-se no browser.
- **Leaflet:**
  - o `divIcon` sem `html`; o número entra por `el()` no `add`, porque o elemento só existe com o marcador no mapa;
  - a opção `className` da `polyline` aplica-se ao `path` SVG.
- **Base de dados:** a lista `paragens` nunca encolhe. Os índices `N` dos caminhos valem para sempre.

### Critical Files for Implementation
- /Users/brucesilva/pasta sem título/RH/backend/crm/lojas.py
- /Users/brucesilva/pasta sem título/RH/backend/tests/crm/duplos.py
- /Users/brucesilva/pasta sem título/RH/backend/crm/servicos/geoapify.py
- /Users/brucesilva/pasta sem título/RH/frontend/src/lib/crm/mapa.js
- /Users/brucesilva/pasta sem título/RH/frontend/src/lib/crm/ficha.js

---

## Correções obrigatórias (revisão por críticos — por fazer)

Estas correções **prevalecem** sobre o texto das tarefas. Aplicar as que referem a tarefa antes de a começar.

| Tarefa | Gravidade | Problema | Correção |
|---|---|---|---|
| — | — | (vazio até à revisão deste plano por 2 críticos só de leitura) | — |


---

## Correções obrigatórias (revisão por 2 críticos, 2026-10-11)

Prevalecem sobre o texto das tarefas. Aplicar as que referem a tarefa antes de a começar.

| Tarefa | Gravidade | Problema | Correção |
|---|---|---|---|
| T3.7 (+ T3.13, T3.21) | major | O Directions verdadeiro do ORS deixa de fora as chaves `distance`/`duration` de um segmento quando valem 0 (pontos repetidos, ou dois pontos que encaixam no mesmo sítio da estrada). Vê-se no fórum do ORS: com 25 coordenadas vieram 24 segmentos, e os dos pontos repetidos não traziam distance nem duration. O `summary` de uma rota de comprimento zero também pode vir sem elas. O `interpretar_direcoes` do plano é estrito, por isso dá `RespostaInvalida` → 503 "Cálculo automático indisponível" em casos reais: duas lojas na mesma morada geocodificada ou no mesmo centro comercial (o aviso dos 50 m só avisa) e uma paragem na própria fábrica. O simulador (T3.13) e as fixtures escritas à mão escondem o problema. | Na T3.7, uma chave `distance`/`duration` em falta num segmento (ou no `summary`) conta como 0. Se estiver presente e for negativa, não finita ou `bool`, continua a ser `RespostaInvalida`. Sem `summary`, os totais são a soma dos segmentos. Acrescentar a fixture `direcoes-ponto-repetido.json` (um segmento só com `steps`, sem distance/duration) e um teste que leia esse caso. A mutação mínima "exigir as chaves" tem de ser apanhada. Na T3.13, o simulador omite as chaves num troço de comprimento zero, como o ORS. Na T3.21, entra um caso de ponta a ponta com duas paragens nas mesmas coordenadas → 200, com chegadas seguidas e espera 0. |
| T3.6 / T3.22 | minor | Quando o VROOM não consegue atribuir nenhum job (por exemplo, uma só paragem cuja janela não cabe no horário do veículo), responde `code: 0` com `routes: []` e todos os jobs em `unassigned`. O plano só testa "mais de 1 rota" e o "zero jobs" do lado do pedido. Uma implementação que leia `routes[0]` rebenta e dá 503 em vez de pôr tudo em "Não cabe no horário". | Na T3.6, `interpretar_otimizacao` aceita `routes: []` → `([], todos os ids)`, com teste. Na T3.22, o caso "nenhum atribuído" dá 200: todas as paragens enviadas ficam `nao_cabe: true`, não se chama o Directions, o `calculo` fica `None` e a versão sobe 1. |
| T3.6 | minor | As respostas reais da otimização do ORS (exemplo de abril de 2025 no fórum) trazem em cada step de job `id` e também `job`, a chave antiga do VROOM. Os steps de início e fim não trazem nenhuma das duas. A fixture "steps start, job 2, job 1, job 3, end" não diz que chave usa, e o parser não diz qual lê. | Fixar o formato nas fixtures: `{"type": "job", "id": 2, "job": 2, "location": [...], "arrival": …, "service": …, "waiting_time": …}`. O parser lê `id`, cai para `job` só quando falta `id` e, se vierem os dois diferentes, levanta `RespostaInvalida`. Ignora os steps `start`/`end` e qualquer outro `type` (por exemplo `break`) dá `RespostaInvalida`. Acrescentar testes dos três casos. |
| T3.11 | minor | O `interpretar_erro` só modela a forma do erro do Directions (`{"error": {"code": 2010, "message": …}}`). Faltam três casos. (a) Os erros da otimização vêm na forma do VROOM, `{"code": 3, "error": "<texto>"}`, com `error` em texto, e um ponto fora da estrada cai aí, com as coordenadas no texto. (b) O texto do 2010 existe em dois formatos: "…of specified coordinate N: …" e o antigo "Could not find point N: …". (c) O ORS dá 403 tanto com a quota diária esgotada como com a chave inválida. | Acrescentar testes: corpo VROOM `{"code": 3, "error": "Unfound route(s) from location [-9.2,38.6]"}` → `indisponivel`, sem rebentar com `error` em texto, e com o texto do erro fora do `motivo` e dos registos (canário das coordenadas). Expressão do 2010 tolerante a `coordinate N` e a `point N`, testada nos dois formatos. 403 → `indisponivel` com o motivo "estado HTTP 403". No dossiê §8/§14: um 403 quer dizer quota diária esgotada ou chave inválida. Na otimização, o ponto fora da estrada dá a mensagem geral; o "Recalcular horas" identifica a paragem. |
| T3.22 | minor | No `otimizar`, o Directions corre pela ordem nova do VROOM, que ainda não está gravada. Um 2010 com o índice i corresponde à i-ésima paragem dessa ordem nova. Como a operação é atómica e nada muda, "A paragem N não fica perto de uma estrada" aponta para o número errado no ecrã. | No `otimizar`, mapear o índice do 2010 → id da paragem (pela lista enviada) → `numero` atual na rota gravada (secção "rota"). Se a paragem não tiver número atual, usar a mensagem geral. Testar com uma ordem do VROOM diferente da gravada. |
| T3.22 | minor | Não está dito que paragens vão ao VROOM numa segunda otimização. O recalcular exclui as `nao_cabe`, e o otimizar só diz que exclui "as fechadas sem Manter". Também não se diz onde ficam as `sem_loja`. Uma implementação pode deixar de fora para sempre as paragens que não couberam na otimização anterior. | Escrever na T3.22 que vão ao VROOM todas as paragens ativas com loja, exceto as fechadas sem `manter_fechada`, incluindo as que antes tinham `nao_cabe: true`. Os sinais `nao_cabe` regravam-se para todas as enviadas. A ordem final é: ordem do VROOM, não atribuídas + impossíveis, fechadas, `sem_loja` (via `nova_ordem`). Testar uma 2.ª otimização em que uma paragem antes `nao_cabe` passa a caber. |
| T3.16 / T3.21 / T3.32 (e dossiê §5.13) | minor | O desenho §7.3 diz que o servidor faz o Directions depois de cada alteração manual, e o §7.6 diz que, se o ORS falhar, a rota "pode ser guardada sem horas previstas". No plano, o novo cálculo depende de o planeador estar aberto (um "Adicionar à rota" pelo cartão não o faz). Depois de uma falha, as `chegada_prevista` antigas ficam na base e na API e o ecrã mostra-as como "a recalcular", mesmo quando nada vai recalcular (falhou, ou rota planeada). Também nada impede que uma rota `planeada` siga para a F4 com horas de outra ordem. | Na T3.31/T3.32, o rótulo "a recalcular" só aparece com um recálculo em fila ou em curso; nos outros casos fica "Horas antigas — Recalcular horas", ou "sem horas — ordene à mão" quando não há chave. Escrever no dossiê §5.13 (contrato com a F4) que as horas por paragem e os totais só valem com `calculo.atual: true` e que, sem isso, a F4 não as mostra. Na T3.40, depois de "Adicionar à rota" pelo cartão, o aviso diz "Abra a rota para recalcular as horas" quando a rota tinha cálculo. |
| T3.32 | minor | O recálculo automático dispara a cada esvaziar da fila. Uma sessão de arrastos rápidos gasta 1 pedido ao Directions por gesto, contra o limite de 40 por minuto e 2000 por dia do plano Standard. Um 429 deixa o planeador em `falhou` até à alteração seguinte. | Esperar ~1,5 s sem alterações depois de a fila esvaziar antes de chamar `recalcularHoras` (temporizador injetado, testado com o relógio falso do Jest): várias alterações seguidas dão um só recálculo. Registar a decisão na nota "Feito". |
| T3.3 / T3.16 (contrato da F4, §3) | minor | O contrato com a F4 escrito no §3 diz que o terreno, ao repor uma paragem retirada, só faz `removida_em: null`. A `ordem` fica `null` numa paragem ativa. O `ativas()` ordena "por ordem", e em Python comparar `None` com `int` dá TypeError, o que parte o `rota_api` na vista só de leitura dessas rotas. | Na T3.3, o `ativas()` aceita `ordem None` numa paragem ativa: vai para o fim, pela posição na lista. Testar com uma paragem retirada e reposta (`removida_em None`, `ordem None`, `estado "feita"`). Na T3.16, o `rota_api` com essa rota → 200, com `numero` coerente. Escrever no dossiê §5.13 que a F3 lê esse formato. |
| T3.10 | minor | O `avoid=tolls` do Google Maps está documentado (Maps URLs: avoid=ferries,highways,tolls). O `avoid_tolls=true` do Waze **não** aparece na documentação oficial dos deep links do Waze: lá, "evitar portagens" é uma definição da app. O link mantém-se fiel ao §8.2, mas pode ser ignorado sem aviso. | Manter o link e os testes como estão. Acrescentar ao §14 do dossiê, no ponto dos blocos de 9 da F4: confirmar no telemóvel da carrinha se o Waze respeita `avoid_tolls`. Quando `evitar_portagens` está ligado, o detalhe da paragem mostra "No Waze, confirme 'Evitar portagens' nas definições da app" (texto fixado no `rota.js`, T3.27). |
| T3.31 / T3.39 | minor | Numa rota virtual (`existe: false`), o PATCH dá 404 "Ainda não há rota para este dia.". O plano não diz o que o planeador faz com as Definições do dia, o "Ponto no mapa" e o "Calcular" antes da primeira paragem, e o utilizador recebe um erro ao mudar a hora de saída. | Na T3.31, com `existe: false`, `vista.definicoes` fica desligada e aparece a frase "Adicione a primeira paragem para mudar as definições do dia". Também `acoes.calcular` e `acoes.guardar` ficam desligadas. Testar no `planeador.test.js`. |
| T3.20 / T3.27 | minor | O `precisaDeHoras` exige pelo menos 1 paragem incluída. Ao retirar todas as paragens (ou a última incluída), o `calculo` antigo fica gravado: a linha esbatida e os totais continuam no mapa e nunca se limpam. | Na T3.20, um PATCH que deixa 0 paragens incluídas põe `calculo: None` na mesma escrita (campo de topo, nunca do terreno). Em alternativa, `precisaDeHoras` passa a ser verdadeiro com `calculo != null` e 0 incluídas, e o recalcular limpa-o sem chamar o ORS. Testar um dos dois. |
| T3.24 | minor | Uma loja com uma paragem ativa numa rota de um dia já passado dá 409 `loja_em_rota`, com "retire-a da rota ou mude a fase para perdida". Só que essa rota é só de leitura (`rota_fechada`), por isso retirar é impossível. | Separar as mensagens. Rota de hoje ou do futuro: a mensagem atual. Só rotas passadas: "Esta loja esteve numa rota — mude a fase para perdida." (o mesmo código, ou `loja_com_historico`). A regra pura `loja_presa_em_rota` recebe `hoje` e é testada nos dois casos. |
| T3.12 / T3.43 (dossiê §14) | minor | Depois da T3.43, o `backend/.env.local` tem `CRM_ORS_URL=http://127.0.0.1:8013` e `CRM_ORS_CHAVE=simulador-local`. Quando o dono puser a chave verdadeira, se acrescentar uma linha em vez de substituir (ou se deixar o `CRM_ORS_URL`), o backend continua a ir ao simulador. Pior: o gravador pode ler `simulador-local` e enviá-lo como chave ao ORS verdadeiro. | O gravador (T3.12) recusa a chave `simulador-local`, sai com 1 e escreve "A CRM_ORS_CHAVE do ficheiro é a do simulador.", com teste. No §14 do dossiê (ponto 5) o passo fica explícito: substituir o valor da linha `CRM_ORS_CHAVE` e apagar a linha `CRM_ORS_URL`, conferindo com `grep -c "^CRM_ORS"`, que deve dar 1. |
| T3.5 / T3.15 (definições das rotas) | major | A T3.5 muda `dominio.definicoes.combinar`/`alteracao`, que o `crm/definicoes.py::em_vigor` usa diretamente. Por isso, logo na T3.5, o `GET /definicoes` passa a devolver 9 chaves e o `PATCH` aceita as chaves novas, ainda sem a coerência das horas. Os testes de API com dicionários exatos ficam vermelhos na própria T3.5, contra a regra 3: `test_definicoes.py` (`PADROES_TEXTO`/`PADROES`, linhas 62–63, 221, 240, 288, 488, 513, 549, 558, 762) e `test_mongo_local.py` (798–799). O "teste primeiro" da T3.15 ("falha porque o GET devolve 3 chaves em vez de 9") já não consegue falhar. | Na T3.5, atualizar também `test_definicoes.py`: `PADROES` e `PADROES_TEXTO` com as 9 chaves e os minutos em `int`. Atualizar também as linhas 798–799 do `test_mongo_local.py` e correr o ensaio com a variável. O GET com 9 chaves fica registado como verde da T3.5. A T3.15 fica só com a coerência no PATCH. O vermelho passa a ser: `{"rota_hora_regresso":"07:00"}` com a saída guardada às 08:00 grava, em vez de dar 422. A coerência só corre quando o pedido traz `rota_hora_saida` ou `rota_hora_regresso`, como as janelas da loja (`semMexerNasJanelasNaoSeVerificamAsGuardadas`): um PATCH só da fábrica nunca recebe 422 por causa das horas guardadas. |
| T3.19 / T3.20 (código rota_em_curso) | major | A T3.19 testa "uma rota com uma paragem `feita` → 409 `rota_em_curso`", mas o código só entra em `erros.ESTADOS` na T3.20 (tabela do §4). Com um código desconhecido, o `erros.erro()` levanta ValueError, o que dá um 500. Se o agente o antecipar, o "teste primeiro" da T3.20 ("falha com 405 e o código em falta") deixa de poder falhar pelo motivo indicado. | Passar `rota_em_curso` para a T3.19, junto de `ja_na_rota`, `rota_cheia` e `rota_fechada`: ESTADOS, a tabela do `test_erros.py` e a coluna "Tarefa" do §4. O vermelho da T3.20 fica só no 405 do `PATCH /rotas/{data}`. |
| T3.11 (conftest: guarda contra a rede) | major | A guarda é um `MockTransport` que levanta `AssertionError`. O `ors.py`, no molde do `geoapify.obter_json` e com a lista `FALHAS_DA_REDE` que inclui RuntimeError, apanha `Exception` e transforma-a em `FalhaOrs("sem resposta (AssertionError)")`, que chega à rota como 503. Daí dois problemas: - um teste que se esqueça do transporte próprio e espere 503 (sem chave, 429, 2010) passa pelo motivo errado; - o meta-teste "um teste sem transporte próprio rebenta" não se consegue escrever como está. | - O transporte da guarda acrescenta cada pedido a uma lista do conftest e responde, por exemplo, 599. - O fixture `autouse`, no teardown, faz `assert pedidos == [], "pedido ao openrouteservice sem o transporte do teste"`. - O meta-teste prova-o com `pytester`, ou chamando o gerador do fixture à mão e verificando que o fim levanta. - O mesmo fixture faz `monkeypatch.delenv("CRM_ORS_CHAVE", raising=False)` e o mesmo para `CRM_ORS_URL`. Assim os testes não dependem da shell, e cada teste que precisa de chave põe-na com `setenv`. |
| T3.22 / §1 "Pedido VROOM" e "Não cabem" | major | "Por cada paragem incluída" é ambíguo, e a T3.21 define as incluídas como "sem as fechadas nem as nao_cabe". Se o otimizar reutilizar esse critério, uma paragem marcada `nao_cabe` num cálculo nunca mais volta ao VROOM. Depois de encurtar outras paragens (o remédio do original §7.2), "Calcular melhor ordem" não a recupera. O original §7.2 só exclui do VROOM as ⚠️ fechadas. | Fixar no §1 e na T3.22: - vão ao VROOM todas as paragens ativas com loja, incluindo as que têm `nao_cabe: true`; ficam de fora só as fechadas sem "Manter" e as `sem_loja`; - cada otimização recalcula o sinal de todas (`nao_cabe` = não atribuída ou impossível; `false` nas outras); - o Directions continua sem as `nao_cabe`.  Teste novo: uma paragem gravada com `nao_cabe: true` vai no pedido ao VROOM e, se for atribuída, volta à secção "rota" com `nao_cabe: false`, uma hora e um número. |
| T3.1 (hoje() com outro TZ no processo) | major | O texto manda usar `monkeypatch.setenv("TZ", "Asia/Tokyo")` + `time.tzset()`. O monkeypatch repõe a variável no fim, mas não volta a chamar o `tzset()`, e o processo fica com o fuso de Tóquio no resto da suite completa (os testes da Faturação e do Financeiro correm depois de tests/crm). O `test_relogio.py` já tem o fixture `fuso_de_toquio` precisamente por isto: "sem monkeypatch: o time.tzset() tem de correr DEPOIS de repor a variável TZ". | Os testes de `relogio.hoje()` com outro fuso usam o fixture `fuso_de_toquio` já existente: ficam no `test_relogio.py`, ou o fixture passa ao conftest. Proibir `monkeypatch.setenv("TZ", …)` nas regras da T3.1. |
| T3.7 / T3.9 / T3.13 / T3.21 (codificar a polyline) | minor | A T3.13 diz que "os testes do domínio usam" a `codificar_polilinha` para a ida e volta, e a T3.21 constrói respostas com ela. Mas a função só nasce no simulador (T3.13), depois da T3.7 e da T3.9: há uma dependência de uma tarefa futura, ou fica uma segunda implementação. | Criar `codificar(pontos, precisao=5)` em `crm/dominio/polilinha.py` já na T3.7, com o exemplo da Google nos dois sentidos e a ida e volta (`descodificar(codificar(p)) ≈ p` a 1e-5). Juntar uma mutação: o `~` dos negativos esquecido. O simulador, a T3.9 e os testes das rotas importam-na daí. |
| T3.36 / T3.38 / receita F3e (ESLint dos links externos) | minor | O plano manda `<a … target="_blank" rel="noopener">`. O eslint-config-react-app do CRA tem `'react/jsx-no-target-blank': 'warn'` (eslint-plugin-react 7.37.4, `allowReferrer` falso), que só aceita `noreferrer`. Com `--max-warnings 0` (receita da T1.13), o ESLint falha. | Usar `rel="noopener noreferrer"` em todos os links que abrem fora: Google Maps e Waze por paragem, blocos de 9 e atribuição do ORS. É o molde do `components/crm/PesquisaMorada.js:34`. Estes links não precisam do Referer. |
| T3.25 / T3.43 (contagem dos skipped) | minor | Os testes novos do `test_mongo_local.py` (T3.25) saltam sem `CRM_MONGO_TESTE_URL`, por isso os `skipped` da suite completa (hoje 30) e de `tests/crm` (hoje 27) sobem. O "skipped sem subir" da T3.43 não se pode cumprir: foi o que aconteceu na T2.17, que passou de 3 para 26. | Na T3.25, registar N, o número de testes novos do ensaio que saltam sem a variável. Na T3.43, exigir: - `skipped = 30 + N`, todos os novos com a razão do ensaio (confirmar com `-rs`); - com a variável, voltar aos 3 de sempre; - `failed` igual a 0.  Atualizar o dossiê §13. |
| T3.6 / T3.22 (VROOM sem rotas e zero jobs) | minor | - Quando nada cabe, o VROOM devolve `routes: []` e todos os ids em `unassigned`. A T3.6 só fixa "mais de 1 rota" como erro, e um código que leia `routes[0]` dá RespostaInvalida → 503 ("indisponível") em vez de "nenhuma cabe". - Fica por dizer o que acontece com paragens incluídas que são todas impossíveis (`corpo is None`): "Zero jobs → 200 sem chamar" pode ler-se como não gravar os `nao_cabe`. | - T3.6: um caso com `routes: []` e todos em `unassigned` → `([], [todos])`. - T3.22: com paragens incluídas mas nenhum *job* enviável, grava `nao_cabe: true` nelas (com `$inc versao`), sem chamar o ORS. - Sem nenhuma paragem atribuída, não chama o Directions e põe `calculo: null`, como o recalcular sem incluídas.  Um teste para cada caso. |
| T3.3 (ativas com ordem nula — contrato F4) | minor | O contrato da F4 (§3) deixa o motorista repor uma paragem retirada só com `removida_em: null`, sem mexer na `ordem`, que fica `None`. `dominio.rotas.ativas` ordena "por ordem", e em Python comparar `None` com `int` dá TypeError: o `GET /rotas/{data}` de uma rota em que o motorista mexeu dá 500. | Em `ativas`, ordenar pela chave `(ordem is None, ordem if ordem is not None else 0, posição)`: as paragens com `ordem` nula vão para o fim. Juntar um teste na T3.3 e um caso no `test_rotas_terreno.py` (T3.24): uma paragem `feita` com `ordem: None` e `removida_em: None` lê-se sem erro, e a rota fica só de leitura. |
| Receita F3e (T3.36, T3.38): verificação temporária no jsdom | minor | O jsdom 16 do Jest 27 do CRA não desenha vetores sem `createSVGRect` (dossiê §2.1; aconteceu com o `L.circle` na T2.26), por isso o `L.polyline` verdadeiro rebenta. Também não tem `PointerEvent` nem `setPointerCapture`, e o `ListaParagens` rebenta no primeiro `pointerdown` sintético. | - No componente: `alvo.setPointerCapture?.(e.pointerId)` e `releasePointerCapture?.`. - Na receita das T3.36 e T3.38, polyfill temporário de `SVGSVGElement.prototype.createSVGRect`. - Eventos `new MouseEvent('pointerdown'\|'pointermove'\|'pointerup', {clientY, bubbles: true})`, com `pointerId` definido à mão. - `getBoundingClientRect` falso nas linhas, para o `indiceDestino`. |
| T3.35 / T3.36 (ecrã cheio no telemóvel) | minor | Com `ecraCheioDoCrm` verdadeiro em `/crm/rotas/<data>`, o `main` do `CrmLayout` e do `AdminLayout` fica `h-[calc(100vh-4rem)] overflow-hidden`. Abaixo de 1024 px, numa só coluna, o painel e a lista ficam cortados e sem deslocamento: não se consegue fazer a verificação a 375 × 812 (arrastar com o dedo, T3.36/T3.40). | Exigir no `css.test.js`: - `.crm-planeador { height: 100% }`; - abaixo de 1024 px, `overflow-y: auto` no contentor e o mapa com uma altura fixa (por exemplo, 45vh); - a partir de 1024 px, `overflow-y: auto` só no painel lateral.  Verificar no browser que a lista desce até à última paragem a 375 × 812. |
| T3.20 / T3.31 / T3.39 (definições do dia numa rota virtual) | minor | Uma rota só nasce com a primeira paragem, e o `PATCH` de um dia sem rota dá 404 "Ainda não há rota para este dia.". O plano não diz que o planeador desliga as definições do dia numa rota virtual: mudar a hora, o início ou as portagens antes de adicionar uma loja dava um erro. | Fixar na T3.31 `vista.definicoes.ativas = rota.existe && rota.editavel`. Numa rota virtual, os campos aparecem desligados com "Adicione a primeira paragem para mudar as definições do dia." (teste no `planeador.test.js`). O `mudarDefinicao`/`tocarNoMapa` nessa situação não chama a API. |
| T3.26 / T3.14 (varrimentos que fazem cumprir as regras) | minor | - A regra 9 ("os href de navegação só passam pelo hrefNavegacao") e a aceitação do §8 não têm nenhum teste que as imponha: o `seguranca.test.js` só tem a regra do `tel:`. - O `formatos.escritas_no_terreno` não lista os operadores posicionais: um `$set` em `paragens.$.estado` ou em `paragens.$[].x` passava o varrimento. | - `seguranca.test.js`: nova regra que recusa `href={…}` com `links`, `.href` ou `blocos` sem `hrefNavegacao(`, provada com amostras positivas e negativas, como as do `tel:`. - `escritas_no_terreno`: tratar como violação qualquer caminho `paragens.$`, `paragens.$[]` ou `paragens.$[x]`, com amostras. |
| T3.12 / T3.43 (gravador, .env.local e fixtures) | minor | - A T3.43 escreve `CRM_ORS_CHAVE=simulador-local` no `backend/.env.local`. O dono, ao correr `gravar_respostas_ors.py --env-file .env.local`, mandava esse valor ao ORS verdadeiro (401 e nada gravado). Pôr lá a chave verdadeira mistura-a com a pré-visualização. - A regravação substitui fixtures onde a T3.6/T3.7 podem ter fixado valores exatos (a ordem 2,1,3), e a T3.12 exige que `tests/crm` continue verde depois. - O `erro-429` e um 2010 não se gravam de forma garantida. | - O dono usa um ficheiro próprio, por exemplo `--env-file .env.ors` (fora do git, modo 600). - O gravador recusa o valor `simulador-local`, com uma mensagem. - Grava só uma lista fechada: `otimizacao-todas`, `otimizacao-uma-nao-cabe`, `direcoes-tres-paragens` e `direcoes-erro-2010` (com um ponto fixo no rio no `cenarios.json`). O `erro-429.json` fica sempre manual. - Os testes sobre fixtures verificam só a forma e os conjuntos (atribuídos ∪ não atribuídos = enviados; `segments` = n − 1). Os valores exatos vêm sempre de respostas escritas no próprio teste. |
| T3.11 (CRM_ORS_URL e a chave em texto claro) | minor | A chave vai no cabeçalho `Authorization` para qualquer `CRM_ORS_URL`. Um `http://` para um anfitrião que não é local, por engano no `.env` do servidor, mandava a chave sem cifra. | `url_base()` só aceita `https://…` ou `http://` com o anfitrião `127.0.0.1`, `localhost` ou `[::1]` (o simulador). O resto é `FalhaOrs(tipo="indisponivel", motivo="CRM_ORS_URL recusado")`, sem pedido nenhum. Teste com `http://exemplo.invalid`, com a mutação "aceitar http". |
| T3.4 / T3.20 (retirar e ordem no mesmo PATCH) | minor | Não está dito o que fazer quando um id vem em `retirar` e também em `ordem`, o que acontece depois de a fila do browser juntar alterações. O servidor montava no mesmo dicionário dois valores para `paragens.N.ordem` (`None` e um número), e o último ganhava em silêncio. | Fixar no validador e na T3.20: os ids de `retirar` saem da `ordem` antes do `nova_ordem` (o retirar ganha, como no `juntarAlteracoes`). Teste: `{ordem: [a, b, c], retirar: [b]}` deixa `b` com `ordem: None` e `removida_em` preenchido, e `a`, `c` com 0 e 1. |
| T3.25 (código 40 no Mongo real) | minor | O plano espera `WriteError` com o código 40, mas no PyMongo 4.5 só o `update_one` dá `WriteError`. O `find_one_and_update` (o comando findAndModify, que é o que o `rotas_bd` usa) levanta `OperationFailure`, e um `pytest.raises(WriteError)` sobre essa operação falha. | No ensaio, usar `pytest.raises(OperationFailure)` com `excinfo.value.code == 40`, pela mesma operação que o código usa (`find_one_and_update`). Fica coerente com o duplo da T3.14, que já levanta `OperationFailure(code=40)`. |
| T3.17 (porque_falhou: precedência) | minor | Quando a escrita falha porque a versão mudou e, ao mesmo tempo, já há uma paragem `feita` ou `nao_feita`, a precedência entre `conflito` e `em_curso` não está fixada. Um `conflito` levava o planeador a recarregar e a tentar outra vez, em vez de passar a só leitura. | Com a rota relida, a ordem é `nao_existe` → `em_curso` (estado fora dos editáveis ou alguma paragem `feita`/`nao_feita`) → `conflito`. Teste com as duas coisas ao mesmo tempo, mais uma mutação que troca a ordem. |
| T3.32 / T3.38 (recálculo automático e pinos do mapa) | minor | - O recálculo automático só pára depois de uma falha. Uma resposta 200 que ainda traga `calculo.atual: false` (por exemplo, a fábrica mudou entre a leitura e a escrita) volta a disparar sem fim contra o ORS, que tem o limite de 40 por minuto (R7). - O `MapaLojas` faz `clearLayers` e recria todos os pinos com etiqueta sempre que a referência de `lojas` muda, e a vista congelada nova a cada ação recriava centenas de pinos. | - No máximo um recálculo automático por par (`versao`, `assinatura`/`calculado_em`), guardado no controlador, com teste. - `vista.mapa.lojasForaDaRota` mantém a mesma referência enquanto a lista de lojas e os ids na rota não mudam (memo no `planeador.js`), com teste de identidade (`toBe`). |
| T3.42 (política de privacidade, §4) | minor | A correção "T2.31" da F2 pôs na §4 (Partilha de dados, cerca da linha 60 do `PrivacyPolicy.js`) os prestadores do CRM: a Geoapify e o OpenStreetMap. A T3.42 só mexe na secção 8, e a §4 continuava a dizer que o CRM só usa esses dois. | Acrescentar o openrouteservice (HeiGIT) também à frase da §4: o servidor só lhe envia coordenadas das lojas e números. Juntar a asserção ao `privacidade.test.js` e contar o diff como cerca de +4/−2. |
| T3.17 / T3.18 (GET /rotas sem a geometria) | minor | O `GET /rotas` (até 120 dias) lê os documentos inteiros, e cada `calculo.geometria` pode ter dezenas de KB. Uma projeção por subcampos (`paragens.removida_em`) rebenta no duplo, que "não projeta subcampos". | `rotas_entre` usa a projeção de exclusão `{"_id": 0, "calculo": 0}`, que o duplo suporta. O teste da T3.17 fixa essa projeção exata no registo, e o `resumo_rota_api` conta as ativas a partir de `paragens`. |
