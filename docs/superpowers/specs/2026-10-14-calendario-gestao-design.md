# Calendário automático das lojas e Face ID na app Gestão Lisbonb — desenho

**Data:** 2026-10-14 (revisto a 2026-10-15) · **Ramo:** `matheus-calendario-gestao`

## Porquê

O grupo tem seis lojas com escala fixa (a sexta, Benfica, ainda sem ninguém). Quando falta
alguém — folga, férias, loja sem equipa — vai a **Carol** ou a **Débora** (gestoras), às vezes as
duas, às vezes meio dia cada. Hoje fazem a conta de cabeça e organizam-se por uma mensagem de
WhatsApp («Escala Outubro / Alfragide: 01- Deb …»).

O dono quer que o calendário **faça essa conta sozinho**: com o horário de cada loja, a escala de
cada pessoa e as férias aprovadas no RH, mostra onde falta gente; elas só têm de tapar o buraco.
Quer também ver **quantos dias** cada uma fez (para se equilibrarem), que a app deixe de pedir a
senha todos os dias, e um menu lateral com Faturação e Calendário.

### A semana normal, como o dono a descreveu

| Loja | Horário | Quem |
|---|---|---|
| Alfragide | 10h–23h | Emily 14h–23h, menos qua e qui · Beatrice 10h–19h, menos seg e ter |
| Algueirão | 13h–22h | Walisson, menos qui e sex · Joana qui e sex |
| Amadora | 14h–23h | Weber, menos seg e ter · Joana seg e ter |
| Belém | 11h30–19h; dom 11h30–20h; **fecha à terça** | Rafaela, todos os dias em que abre |
| Benfica | 13h–22h (a abrir) | ninguém |
| Oeiras | 13h–22h | Emanuela, menos ter e qua · Joana qua |

Daqui sai, sem mais nada, **a grelha dos buracos de uma semana normal**: Oeiras sem ninguém à
terça; Alfragide sem ninguém das 10h às 14h à segunda e terça e das 19h às 23h à quarta e
quinta; Benfica sem ninguém todos os dias. Bate com a mensagem: a Débora está em Oeiras a 6, 13,
20 e 27 de outubro — as quatro terças — e a Carol cobre a Amadora a 22, 23 e 25/10, quando o
Weber está de férias de 21 a 25/10.

## O que foi medido antes de desenhar (main `57d5f6f`)

1. **A escala do RH é semanal e sem loja.** `work_schedule_templates` guarda `name`,
   `work_days` (0 = segunda … 6 = domingo) e `start_time` (`server.py:634-667`). A atribuição
   liga colaborador ↔ modelo por intervalo de datas e **guarda uma cópia de `work_days`**
   (`:669-697`, `:2201-2208`), que o `PUT /schedules/{id}` volta a sincronizar
   (`:2244-2247`). Proíbe duas atribuições sobrepostas para a mesma pessoa (`:2188-2196`).
   A loja do colaborador é uma só, `employees.location_id` (`:514`).
2. **A escala tem três consumidores e zero testes:** o saldo de férias
   (`calculate_leave_counted_days`, `:839-889`, que usa a cópia `work_days` da atribuição,
   `:882`), o «Em falta» do painel (`_schedule_today`, `:2927-2936`, com o recurso
   `atribuição.work_days or modelo.work_days`, `:2936`) e o lembrete do ponto (`/me/schedule`,
   `:2130-2153`, que lê `start_time`). Um quarto leitor, o `GET /schedules/assignments`
   (`:2223-2229`), devolve-o ao ecrã. **Desde que `work_days` continue a querer dizer o mesmo e
   `start_time` continue a existir, nenhum muda.** O `PUT /schedules/{id}` copia o `work_days`
   do corpo para **todas** as atribuições, incluindo as já fechadas (`:2242-2247`).
3. **Os locais não têm horário.** `LocationCreate` tem nome, empresa, morada, cerca e Place ID
   (`:486-496`); o `LocationResponse` (`:498-507`) só devolve esses. O `PUT /locations/{id}`
   **substitui todos os campos** com o que vem no corpo (`:1489-1503`) — um campo novo que o
   formulário não mande fica a `null`. O mesmo vale para `WorkScheduleTemplateResponse`
   (`:662-667`), que filtra o que não conhece, e para o `work_days` obrigatório do
   `WorkScheduleTemplateCreate` (`:636`, `:645`).
4. **As ausências já existem:** `leave_requests` com `employee_id`, `leave_type`
   (`ferias`/`falta`/`doenca`/`folga`/`ausencia`), `start_date`, `end_date`, `status`
   (`pendente`/`aprovado`/`recusado`). O `GET /calendar/leaves` (`:3154-3194`) tem o filtro de
   sobreposição certo, mas faz uma consulta e um `calculate_leave_counted_days` **por
   ausência** (`:3184-3192`) — não se copia isso.
5. **Os feriados existem, sem nome.** `get_pt_holidays` (`:792`) devolve um `set` de datas (os
   nomes estão em comentários), guardado numa cache (`_pt_holiday_cache`) e chamado num sítio só
   (`:874`). Os personalizados (`holidays`) **têm `name`** (`:4536`) e âmbito
   grupo/empresa/loja (regra «OU», `:823`); aceitam dias impossíveis como 30/02
   (`:4549-4554`). **Feriado não é loja fechada:** há lojas abertas a 05/10, 01/12 e 08/12.
6. **Os gestores não têm ficha de colaborador** (`employee_id: None`, `:1294-1303`): não têm
   escala nem ausências no RH. **Quem sai é apagado** (`delete_employee`, `:1760-1792`) e as
   atribuições dele **ficam órfãs**.
7. **Todo o colaborador tem conta em `users`** com `employee_id` (`:1546-1556`); os gestores
   também têm conta. `users.id` identifica qualquer pessoa.
8. **O `/bolso` é um ecrã só** (`pages/bolso/BolsoApp.js`, 732 linhas), rota exata `/bolso`
   (`App.js:206-210`), para `admin`/`gerente`/`contabilista`. O `Segmento` é uma constante
   **dentro** de `BarraDeAmbito` (`:372-373`); `useManifestoDoBolso` (`:104`) não é exportado.
   `ui/sheet.jsx` aceita `side` left/bottom, com um botão de fechar de 16 px em `top-4`.
9. **Porque pede a senha:** token de **24 h fixas** sem renovação (`server.py:58`). O 401/403
   faz `logout()` (`contexts/AuthContext.js:41-44`, `BolsoApp.js:468`); o painel relê a cada
   regresso ao ecrã (`BolsoApp.js:486-489`). **Segunda causa:** se o `/auth/me` do arranque
   falhar sem ser 401/403, o token fica mas o `user` não (`AuthContext.js:45-49`) e o
   `ProtectedRoute` manda para o login (`App.js:116-117`). O login (`server.py:1024-1036`) dá
   401 a credenciais erradas e **429** quando o limite por IP (30 em 15 min, `:71-72`) dispara.
10. **A casca** (`app-bolso/`, Capacitor 6, só iOS, build 2) carrega
    `https://rh.lisbonb.com/bolso`: o site chega sem build nova.
11. **Dito pelo dono:** a Carol e a Débora são administradoras, têm iPhone e a app instalada; os
    sete colaboradores da tabela estão no RH e as férias deles marcam-se lá.

## Decisões do dono

1. **O calendário é automático:** calcula os buracos a partir do horário das lojas, da escala de
   cada pessoa e das ausências aprovadas.
2. **A escala fixa vive na página Escalas do RH**, que passa a dizer loja e horas por dia — uma
   escala só, não duas.
3. **O horário vive nos Locais:** um horário para todos os dias, exceções por dia (domingo de
   Belém) e os dias em que fecha.
4. **As idas têm horas**, tiradas do buraco que tapam e que se podem mudar (deixa de haver
   Dia/Manhã/Tarde).
5. **Qualquer pessoa pode ser escalada** numa ida (gestor ou colaborador), mas **só os gestores
   marcam**.
6. **Vistas Mês, Lista e Contagem; filtros Pessoal, Geral e Férias.**
7. **Contagem:** uma ida vale 1 dia se cobrir pelo menos metade do horário da loja nesse dia, e
   0,5 se cobrir menos; nunca mais de 1 dia por pessoa por dia.
8. **Feriados não fecham lojas, e no feriado a escala não põe ninguém** (2026-10-16, substitui
   «Feriados só como aviso»): «no feriado não se pode pôr as pessoas automaticamente, porque não
   se sabe quem vai trabalhar; no feriado coloca-se à mão.» A loja fica com buraco até se marcarem
   idas.
9. **Face ID** para acabar com a senha diária, aceitando que exige a build 3 da casca.

## Fora de âmbito (de propósito)

- Horários que passam da meia-noite (nenhuma loja passa hoje).
- Fecho de uma loja numa **data** concreta (Natal, passagem de ano): o dono decidiu não ter —
  nesses dias a loja aparece com buraco.
- Ausências pendentes a abrir buracos — só as aprovadas.
- Férias dos gestores (não têm ficha de colaborador).
- Avisos no telemóvel («amanhã vais a Oeiras»).
- Colaboradores a verem o calendário (entram por outra porta, a do ponto).
- Mexer no «Em falta» do painel para usar a loja e as horas novas.
- Sessões mais longas no servidor: as 24 h ficam.

## O desenho

### 1. Os dados

**Horário da loja** — dois campos novos em `locations`, editados na página Locais:

```json
"horario": {
  "abre": "11:30", "fecha": "19:00",
  "excecoes": [{ "dia": 6, "abre": "11:30", "fecha": "20:00" }],
  "fechada": [1]
},
"aberta_desde": "2026-10-24"
```

- `dia`: 0 = segunda … 6 = domingo, como `work_days`.
- Validação: `abre` < `fecha` (HH:MM); dias de 0 a 6 sem repetidos; um dia não pode estar em
  `excecoes` e em `fechada`.
- **Só as lojas com `horario` entram no calendário** — a Pizzaria e os escritórios ficam de fora
  sem ninguém os esconder. `aberta_desde` (opcional) esconde a loja antes de abrir.
- Os dois campos entram em `LocationCreate`, `LocationResponse`, no `POST` e no `$set` do `PUT`.
  **O `PUT` só os escreve se vierem no corpo** (`model_fields_set`): um browser com a página
  antiga em cache (já aconteceu) manda o formulário sem eles, e sem esta guarda apagava o horário.
  O formulário novo carrega-os ao abrir e manda-os sempre.

**Escala da pessoa** — um campo novo em `work_schedule_templates`, editado na página Escalas:

```json
"dias": [
  { "dia": 0, "location_id": "amadora", "inicio": null, "fim": null },
  { "dia": 2, "location_id": "oeiras",  "inicio": null, "fim": null },
  { "dia": 3, "location_id": "algueirao", "inicio": "13:00", "fim": "22:00" }
]
```

- `location_id` vazio = a loja da ficha do colaborador; `inicio`/`fim` vazios = o horário da
  loja nesse dia. As duas horas vêm juntas ou nenhuma, e `inicio` < `fim`.
- **Quando há `dias`, o servidor deriva `work_days` deles** (os `dia`, ordenados), **no `POST` e
  no `PUT`**, calcula-o uma vez e usa o mesmo valor no modelo e na cópia das atribuições. O
  formulário continua a mandar `workDays` (é obrigatório, medido 3), mas manda o mesmo que `dias`.
  Assim `work_days` continua a querer dizer «os dias em que trabalha», e o saldo de férias, o «Em
  falta» e o lembrete não mudam (medido 2).
- `dias` entra em `WorkScheduleTemplateCreate` e `WorkScheduleTemplateResponse`; o `PUT` só o
  escreve se vier no corpo (a mesma guarda dos Locais).
- **O campo «Hora de início» (`start_time`) fica** como está: é o que o lembrete do ponto lê, e a
  app do ponto tem o código congelado.
- **Escalas antigas, sem `dias`, continuam a valer:** loja da ficha e horário da loja. Um dia de
  `work_days` sem entrada em `dias` também.
- O formulário das Escalas, por cada dia marcado, ganha uma loja (por omissão: «loja da ficha»)
  e, opcionalmente, horas. Na prática a escala passa a ser por pessoa («Escala Joana»).

**Idas** — colecção nova `bolso_idas`, uma por pessoa, dia e loja:

```json
{ "id": "uuid", "data": "2026-10-21", "location_id": "...", "user_id": "...",
  "inicio": "13:00", "fim": "22:00",
  "criado_por": "...", "criado_em": "...", "alterado_por": "...", "alterado_em": "..." }
```

- `user_id` é a conta da pessoa, gestor (`admin`/`gerente`) ou colaborador. O contabilista não
  pode ser escalado. Para cruzar com a escala e as ausências, que são por `employee_id`, usa-se
  `users.employee_id` (todo o colaborador tem conta, medido 7).
- `data` entra como `date` no Pydantic e grava-se com `isoformat()`; horas em HH:MM, `inicio` <
  `fim`.
- **Só em lojas com horário e abertas nesse dia** (senão **400** «A loja está fechada nesse
  dia»), e **as horas têm de tocar no horário** da loja (senão 400). Horas que saiam do horário
  (chegar meia hora antes de abrir) aceitam-se e **recortam-se** ao horário no cálculo e na
  contagem.
- **A mesma pessoa não pode ter duas idas com horas sobrepostas no mesmo dia** (não está em dois
  sítios ao mesmo tempo) — **409** a dizer qual.
- **Um colaborador não pode ser marcado num dia em que tem ausência aprovada** — **409** «A
  Joana está de férias nesse dia».
- Índice único em `(data, user_id, location_id, inicio)` (o duplicado exacto) e índice em `data`.

### 2. O cálculo — puro, em `backend/calendario.py`, sem Mongo nem FastAPI

Para cada loja com horário, e para cada dia do mês:

1. **Estado:** `por_abrir` antes de `aberta_desde`; `fechada` se o dia da semana estiver em
   `fechada`; senão `aberta`, com o horário do dia (a exceção desse dia, ou o geral).
2. **Quem lá está pela escala:** parte de **`employees`** (não das atribuições, que podem estar
   órfãs). Para cada colaborador, a atribuição que cobre o dia (a regra de
   `find_schedule_assignment`), os dias `atribuição.work_days or modelo.work_days`; se trabalha
   nesse dia da semana, a entrada de `dias` desse dia diz a loja e as horas (ou a ficha e o
   horário da loja). **Uma entrada para uma loja fechada nesse dia (ou sem horário, ou por
   abrir) ignora-se.** As horas recortam-se ao horário. **Num feriado da loja** (nacional, do
   grupo, da empresa dela ou dela — a regra «OU» dos feriados da loja) **a escala não põe lá
   ninguém** (decisão do dono, 2026-10-16): a loja continua aberta e fica com buraco até um gestor
   marcar idas; as idas contam como sempre e o «extra» mede-se contra a escala normal.
3. **Sai quem tem ausência aprovada** que inclua o dia, de qualquer tipo.
4. **Entram as idas:**
   - a ida de um **gestor** soma-se à loja;
   - a ida de um **colaborador** tira à escala dele, nesse dia, **as horas da ida** (subtracção de
     intervalos): a Joana 13h–15h em Benfica numa quarta deixa Oeiras com buraco só das 13h às
     15h. As horas da ida que não estavam na escala dele são **extra** (numa folga, a ida toda).
5. **Buracos** = o horário de abertura menos a união das horas de quem lá está, em intervalos
   («10:00–14:00»). Vazio = coberta.

Os buracos **não se guardam** — calculam-se a cada pedido, por isso nunca ficam desactualizados.

**Buracos:** `[{inicio, fim}]`; «ninguém» é um buraco único igual a `abre`–`fecha`.

**Feriados do dia:** os nacionais (com nome) e os personalizados de âmbito grupo; **feriados da
loja:** os personalizados da empresa dela ou dela (a regra «OU» de `:823`). Um personalizado com
dia impossível salta-se. Os nacionais vêm de um dicionário `{data: nome}` construído à parte; o
`get_pt_holidays` continua a devolver o mesmo `set` e a cache dele não é tocada.

**Contagem** (por pessoa com idas no ano):

- cada ida vale **1** se as suas horas **dentro do horário** da loja nesse dia forem ≥ metade
  das horas de abertura, e **0,5** se forem menos (uma ida que entretanto ficou numa loja sem
  horário vale 1);
- por pessoa e por dia soma-se e **corta-se em 1**;
- devolve, por pessoa, os 12 meses e o total do ano. Conta as idas marcadas, **incluindo as
  futuras** — é o que elas usam para se equilibrarem.

### 3. O servidor

Rotas novas debaixo de `/api/bolso/calendario`. **Ler** usa `admin_manager_required` (inclui o
contabilista); **escrever** exige `admin` ou `gerente` (403 aos outros).

| Método | Caminho | O quê |
|---|---|---|
| GET | `/bolso/calendario?ano=&mes=` | o mês inteiro (abaixo); `ano` e `mes` obrigatórios |
| GET | `/bolso/calendario/contagem?ano=` | a contagem do ano |
| POST | `/bolso/calendario/idas` | `{datas: [date, …≤31], location_id, user_ids: [1..2], inicio, fim}` → cria uma ida por data e por pessoa; **tudo ou nada**: se alguma falhar as regras (sobreposição, ausência, loja fechada), 409/400 com a lista e não grava nenhuma |
| PUT | `/bolso/calendario/idas/{id}` | muda dia, loja, pessoa ou horas de uma ida; 409 se chocar |
| DELETE | `/bolso/calendario/idas/{id}` | apaga uma ida |

POST e PUT validam: pessoa com papel `admin`/`gerente`/`colaborador`; loja com horário e aberta
nesse dia; horas válidas e a tocar no horário; datas e pessoas sem repetidos no pedido; senão
**400** com texto claro. A sobreposição verifica-se com **uma** consulta
(`{user_id: {$in}, data: {$in}}`) e comparação em memória; o PUT exclui a própria ida.
**Tudo ou nada sem transacções** (o Atlas tem, o `mongod` dos testes não): grava uma a uma e, se
uma falhar (`DuplicateKeyError` de quem marcou ao mesmo tempo), **apaga as que este pedido já
gravou** e devolve 409. Fica uma janela entre verificar e gravar para idas sobrepostas mas não
iguais, marcadas por duas gestoras no mesmo segundo — aceite (`ponytail:` no código).

O GET do mês devolve, num pedido:

```json
{ "ano": 2026, "mes": 10, "eu": "<user_id>", "pode_marcar": true,
  "dias": [{ "data": "2026-10-06", "feriados": [],
             "lojas": [{ "location_id": "...", "nome": "Oeiras", "estado": "aberta",
                         "abre": "13:00", "fecha": "22:00", "feriados": [],
                         "pessoas": [{ "user_id": "...", "nome": "Débora", "inicio": "13:00",
                                       "fim": "22:00", "origem": "ida", "extra": false,
                                       "ida_id": "..." }],
                         "buracos": [] }] }],
  "idas": [ … com nome da pessoa e da loja … ],
  "ausencias": [{ "nome": "Weber", "tipo": "ferias", "inicio": "2026-10-21",
                  "fim": "2026-10-25", "loja": "Amadora" }],
  "lojas": [{ "id": "...", "nome": "Oeiras" }],
  "pessoas": [{ "id": "...", "nome": "Débora Ferreira", "tipo": "gestor" }] }
```

- Os nomes resolvem-se com recurso («(conta removida)», «(loja removida)»).
- `idas[]` leva `id, data, location_id, user_id, inicio, fim` e os nomes — **é daqui que se
  montam a vista Pessoal e as idas da Lista**, não de `dias` (uma ida numa loja que entretanto
  perdeu o horário continua a aparecer).
- `pessoas[]`: só `admin`/`gerente`/`colaborador`, já ordenadas (gestores, depois nome). A mesma
  consulta a `users` dá o mapa `employee_id → user_id`.
- `ausencias[]`: só as **aprovadas** que tocam o mês (o mesmo critério dos buracos), nomes num só
  `$in`, sem dias contados; «loja» é a da ficha.
- O contabilista recebe `pode_marcar: false`.
- 9 consultas fixas por pedido, sem ciclos; a resposta de um mês ronda 100 KB em bruto e o Caddy
  já comprime (`encode gzip`).

A contagem devolve `[{user_id, nome, meses: [12], total}]`, ordenada pelo total.

Os Locais e as Escalas continuam nas rotas que já têm (`/locations`, `/schedules`), com os
campos novos nos modelos.

**Níveis de conta:** o ramo `matheus-niveis-de-conta` (fora do main) põe `bolso` na gaveta
`painel`. As rotas novas caem na mesma. Quem entrar no main em segundo acrescenta a linha ao
mapa; o teste de cobertura desse trabalho fica vermelho se alguém se esquecer.

### 4. O ecrã

**Menu lateral (☰)** no cabeçalho do bolso, num `Sheet side="left"`: **Faturação**,
**Calendário**, **Usar Face ID** (Fase 3) e **Terminar sessão**. Conteúdo com
`safe-area-inset-top` e botão de fechar de 44 px (o `SheetContent` ganha a opção de não desenhar
o seu de 16 px). Saem do `BolsoApp.js` para um `pages/bolso/partilhado.js`:
`useManifestoDoBolso`, `Segmento` e os `ler`/`guardar` do `localStorage`. A `BarraDeAmbito` fica
só na Faturação. Rota nova `/bolso/calendario`, irmã de `/bolso`, com os mesmos papéis.

**Calendário** (`pages/bolso/BolsoCalendario.js`):

- **Em cima:** ☰, mês e ano, ‹ ›, e **Mês | Lista | Contagem**.
- **Em baixo:** os filtros **Pessoal | Geral | Férias** (o `Segmento`). Vista e filtro
  lembram-se no `localStorage`, com try/catch; sem ele abre em Mês/Geral.
- **Mês** — uma grelha própria a partir de `semanasDoMes()` (função pura, testada em Node; não o
  `ui/calendar.jsx`, cujo react-day-picker 8 declara o date-fns 2/3 com o 4 instalado), dias de
  **44 px**, feriados noutra cor. Abre no dia de hoje; tocar num dia mostra-o por baixo.
  - **Geral:** ponto vermelho nos dias com buraco por tapar. O dia mostra, loja a loja, quem lá
    está (nome, horas, «escala» ou «extra»), os buracos a vermelho («ninguém») ou amarelo
    («falta 10h–14h») com o botão **Tapar**, e as lojas fechadas a cinzento.
  - **Pessoal:** pontos nos dias das minhas idas; o dia mostra só as minhas.
  - **Férias:** pontos nos dias com ausências; o dia mostra nome, tipo, datas e loja.
- **Lista** — os dias do mês à vista (a partir de hoje no mês corrente; o mês inteiro nos
  outros), só **buracos e idas** (Geral), as minhas idas (Pessoal) ou as ausências (Férias). Dias
  sem nada não aparecem. Avança-se com ‹ ›.
- **Contagem** — uma linha por pessoa com idas no ano: o mês à vista e o total do ano («Débora ·
  outubro 18 dias · 2026 60 dias»); tocar abre os meses um a um.
- **Tapar um buraco** abre um painel (`Sheet side="bottom"`) com: **Pessoas** (uma ou mais;
  gestores primeiro, depois colaboradores; começa em mim se eu puder ser escalado), **Horas**
  (as do buraco, editáveis), **Dias** (a grelha do mês a escolher vários, com o dia tocado
  marcado e o atalho **«Também nas outras terças deste mês com buraco em Oeiras»**, que marca
  as terças seguintes cujo buraco **contém** as horas escolhidas — calculado só com a resposta). **+ Marcar ida** abre o mesmo painel vazio, com a loja a escolher.
- **Tocar numa ida** abre o painel com **Guardar** e **Apagar** (um dia, uma pessoa).
- «Tapar» e «Marcar» só existem com `pode_marcar`.
- **O «hoje» é o do telemóvel em hora local** (`getFullYear`/`getMonth`/`getDate`), nunca
  `toISOString()`, que entre a meia-noite e a uma da manhã de Lisboa dá o dia anterior.
- Os pedidos vão por `lib/bolso.js`, com caminhos por extenso, para o
  `tests/fin/test_caminhos_do_bolso.py` os confrontar com o router.
- Erros dizem o que aconteceu e o que fazer: «A Débora já está em Alfragide das 10h às 14h a
  21/10.»

### 5. Login com Face ID

**Peça nativa:** `@capgo/capacitor-native-biometric@6.0.4`, versão fixa — a única que aceita
Capacitor 6 e traz numa só peça `isAvailable`, `verifyIdentity`, `setCredentials`,
`getCredentials` e `deleteCredentials` (MIT; regista-se como `NativeBiometric`). Mais
`NSFaceIDUsageDescription` («Usamos o Face ID para entrar na Gestão Lisbonb sem escrever a
senha.») e build 3 (`CURRENT_PROJECT_VERSION = 3`).

**O que esta versão faz e não faz** (lido no Swift do pacote): guarda email e senha no
**Keychain** (`kSecClassInternetPassword`, por `server`), mas **sem os prender ao Face ID** — o
`getCredentials` devolve-os sem pedir nada. Quem garante o Face ID é o nosso código, que chama
`verifyIdentity` (com `useFallback: false`, só biometria) **antes** de ler. Prender a senha ao
Face ID no Keychain só existe na série 8 do plugin, que exige Capacitor 8.

**No site**, tudo num módulo `lib/faceid.js`, que só actua com
`Capacitor.isPluginAvailable('NativeBiometric')` (build 2 e browser ficam como hoje). Usa o
`registerPlugin` do `@capacitor/core` 6 que o site já tem.

1. **Primeiro login com senha** → «Usar Face ID para entrar?». Sim → guarda o email devolvido
   pelo servidor e a senha. Não → `faceid_recusado:<email>` no `localStorage`, não volta a
   perguntar; **Usar Face ID** no menu lateral para quem mudar de ideias.
2. **Barreira:** ao abrir a app, e ao voltar depois de **mais de 5 minutos fora**, um ecrã opaco
   tapa tudo até o Face ID passar («Entrar como <email>»). A hora de saída grava-se no
   `localStorage` (`saiuAs`) ao esconder; sem ela conta como arranque. Os dados não se pedem com
   a barreira fechada, e ela fecha logo ao esconder (a miniatura do selector de apps não mostra
   números).
3. **Face ID falhou ou cancelado** → `logout()` (apaga o token, não o Keychain) e login normal.
4. **Sessão expirada** → **uma só re-entrada partilhada** (`reentrar = emCurso ??= …`): Face ID
   se a barreira não acabou de o fazer, Keychain, `POST /auth/login`, grava o token e repete o
   pedido uma vez. Falhou → login normal.
5. **Só um 401 do login apaga o Keychain.** 429 e rede em baixo mantêm-no.
6. **Terminar sessão** = `terminarSessao()` (`logout()` + apagar o Keychain). O `logout()` dos
   401 não apaga o Keychain.
7. **Dois gestores no mesmo iPhone:** fica o último que activou o Face ID; a barreira diz sempre
   «Entrar como <email>» e só aparece à conta desse email. A re-entrada só usa o Keychain da
   mesma conta cuja sessão expirou (decisão 1A, 2026-10-15). A sessão de **outra** conta volta à
   senha onde a dona do Face ID teria a barreira: ao abrir a app e ao voltar depois de mais de 5
   minutos (decisão A, 2026-10-17). O rosto de uma pessoa nunca abre a conta de outra.

**Riscos aceites (revisão final da Fase 3; aceite pelo dono a 2026-10-20).** Os 5
minutos contam-se com o relógio do iPhone (`saiuAs` e `Date.now()`, os dois do aparelho): quem
tem o iPhone desbloqueado na mão e muda a hora para trás, para dentro dos 5 minutos depois de
`saiuAs`, abre a app sem rosto. O desenho não muda por isto: esse alguém já tem o iPhone
desbloqueado (e com o código do iPhone até pode registar o próprio rosto no Face ID), e o
servidor continua a recusar o token ao fim das 24 h. O rosto, esse, já não sobrevive ao
esconder: os 60 s em que um rosto vale (`JANELA_MS`) esquecem-se quando a app vai para segundo
plano (`esquecerRosto()`, chamado pelo `fecharBarreira()`).

**No servidor não muda nada.** As 24 h ficam; o formato do token não muda (a app do ponto leva o
código congelado no bundle).

**Duas correcções que vão junto (só site):**

- **Sem ligação:** se o `/auth/me` do arranque falhar sem ser 401/403, o `AuthContext` guarda
  `semLigacao` e o `ProtectedRoute` mostra «Sem ligação — tentar de novo» em vez do login.
  **Muda também o portal no browser** (é a mesma peça) — melhoria, e fica dito.
- O 401 do bolso leva `state.from`, e depois de entrar volta-se ao ecrã de onde se veio.

## Entrega por fases

**Fase 1 — horários e escalas** (portal; deploy). Locais com horário, exceções, dias fechados e
data de abertura; Escalas com loja e horas por dia. Depois, o **script de arranque**, corrido
pelo dono (as regras desta sessão não me deixam escrever em produção): as 6 lojas com horário e
as 7 escalas da tabela de cima, com dry-run primeiro. Para a grelha bater: a Emily (14–23) e a
Beatrice (10–19) levam horas explícitas; a Joana leva loja por dia (Amadora seg/ter, Oeiras qua,
Algueirão qui/sex); a Rafaela não trabalha à terça (a loja fecha — e assim a terça também não
conta nas férias dela).

**Fase 2 — o calendário automático** (app; deploy, sem build). O cálculo, as rotas, o menu
lateral, Mês/Lista/Contagem, os filtros, tapar e marcar. Depois de estar no ar, e com
confirmação do dono, carregar as idas de outubro a dezembro da mensagem.

**Fase 3 — Face ID.** Primeiro o código do site (deploy; com a build 2 nada muda, excepto as duas
correcções), depois a build 3 no TestFlight.

Cada fase tem o seu plano.

## Testes

Antes da suite na worktree: `ln -sfn ~/Developer/RH/frontend/node_modules frontend/node_modules`
e o Python da árvore principal. Ler sempre `passed` **e** `skipped`.

1. **A semana normal** (o teste que dá nome ao trabalho): com os dados da tabela de cima, numa
   semana **depois** da abertura de Benfica (26/10–01/11), o cálculo dá **exactamente** a grelha
   dos buracos — Oeiras sem ninguém à terça,
   Alfragide 10–14 seg/ter e 19–23 qua/qui, Benfica todos os dias, Belém fechada à terça, o resto
   coberto.
2. **Outubro:** as férias do Weber (21 a 25/10) abrem a Amadora nesses dias; a Joana marcada em
   Benfica numa quarta abre Oeiras nessa quarta; 2 horas dela em Benfica abrem só essas 2 horas;
   numa folga dela a ida é «extra»; marcá-la num dia de férias dá 409.
3. **Escala:** escalas antigas sem `dias`; `dias` com loja e horas; entrada numa loja fechada
   ignorada; duas atribuições no mês; atribuição órfã não aparece; ausência pendente não tira;
   `work_days` derivado de `dias` no POST e no PUT, igual no modelo e nas atribuições;
   `start_time` intacto; o saldo de férias de quem passa a ter `dias` **dá o mesmo** que antes;
   um PUT sem `dias`/`horario` no corpo (página antiga) **não os apaga**.
4. **Horário:** exceção de domingo; dia fechado; antes de `aberta_desde`; validações.
5. **Feriados:** nacionais com nome; de empresa e de loja só onde se aplicam; dia impossível sem
   500; a cache de `get_pt_holidays` igual; no feriado da loja a escala não põe ninguém, as idas
   contam e o «extra» mede-se contra a escala normal.
6. **Contagem:** 0,5 e 1 pela metade do horário, contando só as horas dentro do horário; duas
   meias no mesmo dia = 1; nunca mais de 1; total do ano.
7. **Marcar:** várias datas e duas pessoas criam N idas; sobreposição dá 409 e **não grava
   nenhuma** (incluindo o caso de o choque ser só na última data); PUT a chocar dá 409 e não se
   choca consigo próprio; contabilista, loja inexistente, loja fechada nesse dia, horas fora do
   horário e repetidos no pedido dão 400; mudar e apagar mexem só na ida certa.
8. **Porta:** colaborador leva 403 em tudo; contabilista lê (`pode_marcar` falso) e leva 403 a
   escrever; administrador e gestor escrevem. Teste contra um `mongod` real (o índice único e o
   «tudo ou nada» medem-se aí).
9. **Caminho:** as chamadas novas em `lib/bolso.js` são apanhadas pelo
   `tests/fin/test_caminhos_do_bolso.py`.
10. **Face ID e sessão** (no site, com o plugin simulado): cancelar fecha a porta; dois 401 dão
    uma só re-entrada; 401 do login apaga o Keychain, 429 e sem rede não; o «não» fica lembrado;
    Terminar sessão apaga o Keychain e o 401 não; sem plugin nada muda.
11. **Cada teste é visto vermelho primeiro** (mutação da regra que prende).
12. **Ecrãs** num browser a 375 px, claro e escuro, com a zona da notch, contra um servidor local
    com os dados da semana normal.
13. **Face ID na casca:** no simulador (rosto certo, errado, cancelar, sessão expirada, senha
    trocada, app morta e reaberta), depois no telemóvel do dono.
14. **Depois de cada deploy:** confirmar que o ficheiro servido é o novo (o `deploy.sh` já
    entregou código antigo) e exercitar o caminho feliz.

## Riscos aceites

- Horários depois da meia-noite não são suportados.
- **Lojas fechadas numa data** (24, 25 e 31/12, 01/01) aparecem com buraco — decisão do dono.
- **Editar os dias de uma escala reescreve as atribuições antigas** (comportamento que já existia,
  `:2242-2247`) e, com isso, o saldo de férias de períodos passados. Com escalas por pessoa vai
  acontecer mais: para mudar a escala de alguém a partir de uma data, cria-se uma escala nova e
  uma atribuição nova (é o que a página já permite).
- Ausências pendentes não abrem buraco.
- As férias dos gestores não aparecem.
- O «Em falta» do painel continua a usar a loja da ficha e a hora de início antiga.
- A senha fica no Keychain e o Face ID é pedido pelo nosso código antes de a ler (limite da
  versão 6 do plugin); só esta app lê o seu Keychain.
- O portal no browser passa a mostrar «Sem ligação» em vez do login quando o servidor não
  responde ao arranque.
- A Carol e a Débora, como administradoras, vêem o portal inteiro até os níveis de conta entrarem.

## Adenda de 2026-10-15 — vista Semana e filtro de loja (pedido do dono, depois de ver a Fase 2)

- **Vista Semana**, a primeira do botão: **Semana | Mês | Lista | Contagem** (por omissão para quem ainda
  não escolheu; quem já tinha uma vista guardada mantém-na). Uma grelha com as **lojas em linhas** e os
  **7 dias (seg a dom) em colunas**. Cada célula: «ok» (coberta), a primeira falta («10–14»; «2 faltas»
  se houver mais de uma), «—» (ninguém), «fech.» (fechada); antes de `aberta_desde` a célula fica vazia.
  Tocar numa célula escolhe esse dia e mostra-o por baixo (a mesma agenda do Mês, com Tapar).
- **‹ › na Semana andam 7 dias**, também quando a semana atravessa dois meses (o ecrã pede os dois
  meses ao servidor e junta-os). O dia escolhido é um só para todas as vistas: mudar de semana muda o
  mês à vista para o mês do dia escolhido.
- **Filtros na Semana:** Geral = a grelha de cobertura; Pessoal = a grelha só com as minhas idas
  (horas nas células onde vou; o resto vazio); Férias = a lista das ausências que tocam a semana.
- **Filtro de loja**: pastilhas «Todas | Alfragide | …» por baixo das vistas (nomes sem o «Loja » à
  frente), memorizado no `localStorage` (com try/catch; uma loja que já não exista volta a «Todas»).
  Aplica-se à Semana (só essa linha), ao Mês (pontos e agenda só dessa loja), à Lista e às Férias
  (ausências de quem tem essa loja na ficha). Não se aplica à Contagem. Com uma loja escolhida,
  «Marcar ida» abre com essa loja já escolhida.
- O servidor passa a mandar o `location_id` da ficha em cada ausência (`ausencias[].location_id`).
