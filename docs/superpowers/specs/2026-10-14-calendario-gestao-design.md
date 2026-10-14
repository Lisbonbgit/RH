# Calendário das idas às lojas e Face ID na app Gestão Lisbonb — desenho

**Data:** 2026-10-14 · **Ramo:** `matheus-calendario-gestao`

## Porquê

A Carol e a Débora (gestoras) vão às lojas em certos dias: revezam-se, às vezes trabalham em
lojas diferentes no mesmo dia, ou fazem meio dia cada na mesma loja. Hoje organizam-se por uma
mensagem de WhatsApp («Escala Outubro / Alfragide: 01- Deb …»), com as férias do pessoal no
fim. O dono quer isto **dentro da app Gestão Lisbonb**, com três vistas: pessoal, geral e
férias. Pediu também que a app deixe de pedir a senha a toda a hora, e um menu lateral com
Faturação e Calendário.

## O que foi medido antes de desenhar (main `57d5f6f`)

1. **A escala do RH não serve para isto.** `work_schedule_templates` guarda só dias da semana
   e hora de início (`server.py:634-667`); a atribuição liga pessoa↔modelo por intervalo de
   datas (`:669-697`). **Não tem loja, nem data concreta, nem meio dia**, e proíbe duas
   atribuições sobrepostas para a mesma pessoa (`:2195`). A loja do colaborador é uma só,
   `employees.location_id` (`:514`).
2. **A escala tem três consumidores e zero testes:** o saldo de férias
   (`calculate_leave_counted_days`, `:839-889`), o «Em falta» do painel (`_schedule_today`,
   `:2927`) e o lembrete do ponto (`/me/schedule`, `:2130`). Mexer-lhe é arriscar o saldo de
   férias sem nada que o apanhe.
3. **Na mensagem, a mesma pessoa em duas lojas no mesmo dia é frequente:** a Débora a 06, 13,
   21 e 29/10 (Alfragide + Oeiras), a 24/10 (Benfica + Algueirão); a Carol a 03, 10, 17 e 24/11.
4. **As ausências já existem:** `GET /calendar/leaves` (`:3154-3194`) devolve as aprovadas que
   tocam um mês, de todos os tipos, com `employee_name`. Faz uma consulta e um
   `calculate_leave_counted_days` **por ausência** (`:3184-3192`) — não se copia isso, só o
   filtro de sobreposição (`:3172-3181`).
5. **Os feriados existem, mas sem nome:** `get_pt_holidays` (`:792`) devolve um `set` de
   datas — os nomes estão em comentários — e é chamado **num sítio só** (`:874`). O `set` vive
   numa cache (`_pt_holiday_cache`, `:790`, `:812`) que não se pode mexer. Os personalizados
   (`holidays`) **têm `name`** (`HolidayCreate`, `:4536`) e âmbito grupo/empresa/loja
   (`get_custom_holiday_monthdays`, `:815-828`, regra «OU» em `:823`); aceitam dias impossíveis
   como 30/02 (`:4549-4554`). **Feriado não é loja fechada:** há lojas abertas a 05/10, 01/12 e
   08/12.
6. **Os gestores não têm ficha de colaborador:** quem é criado pela área de administradores
   fica com `employee_id: None` (`:1294-1303`). Não tem escala nem ausências no RH.
7. **Não há colaboradores «inactivos»:** quem sai é apagado (`delete_employee`, `:1760-1792`),
   mas as atribuições de escala dele **ficam órfãs** — o apagar não lhes toca.
8. **O `/bolso` é um ecrã só** (`pages/bolso/BolsoApp.js`, 732 linhas), rota exata `/bolso`
   (`App.js:206-210`), só para `admin`/`gerente`/`contabilista`. Já existem `ui/sheet.jsx`
   (com `side` left/bottom; usado como menu móvel em `components/layouts/AdminLayout.js:654-663`),
   `ui/calendar.jsx` (react-day-picker 8.10.1, que passa `mode="multiple"` ao DayPicker) e
   `date-fns` 4. O `Segmento` do bolso é uma constante **dentro** de `BarraDeAmbito`
   (`BolsoApp.js:372-373`) — tem de sair cá para fora para ser reaproveitado.
9. **Porque pede a senha:** o token vale **24 h fixas**, sem renovação
   (`JWT_EXPIRATION_HOURS = 24`, `server.py:58`, desde o primeiro commit). O 401/403 faz
   `logout()` (`contexts/AuthContext.js:41-44`, `BolsoApp.js:468`) e o painel volta a pedir dados
   a cada regresso ao ecrã (`BolsoApp.js:486-489`). Há uma **segunda causa**: se o `/auth/me` do
   arranque falhar por outra razão que não 401/403 (rede, 500, 502), o token fica mas o `user`
   não (`AuthContext.js:45-49`), e o `ProtectedRoute` manda para o login (`App.js:116-117`).
   E um defeito ao lado: o `navigate('/login')` do `BolsoApp.js:468` não leva `state.from`,
   e depois de entrar a app aterra no `/admin/resumo` (`LoginPage.js:38-41`, `lib/resumo.js:173-176`).
10. **O login** (`server.py:1024-1036`) devolve 401 a credenciais erradas e **429** quando o
    limite por IP (30 em 15 min, `:71-72`) dispara; procura o email tal como foi escrito.
11. **A casca** (`app-bolso/`, Capacitor 6, só iOS, build 2) carrega
    `https://rh.lisbonb.com/bolso` — o site chega sem build nova; só a casca exige TestFlight.
12. **A Carol e a Débora já têm a app instalada e entram como gestoras** (dito pelo dono).

## Decisões do dono

1. **Só gestores marcam** as idas — e **só gestores podem ser marcados**. Os extras dos
   colaboradores («Joana (Extra)») ficam fora do calendário.
2. **Período: Dia, Manhã ou Tarde.** Sem horas.
3. **Não há «loja fechada».** Os feriados aparecem como aviso no dia.
4. **Duas vistas, Mês e Lista**, com um botão para escolher.
5. **Filtros Pessoal / Geral / Férias.** O Geral inclui os colaboradores pela escala do RH.
6. **Face ID** para acabar com a senha diária — aceitando que exige a build 3 da casca.
7. **Uma colecção nova** para as idas, ao lado da escala do RH, que não é tocada.

## Fora de âmbito (de propósito)

- Mexer na escala do RH, nas ausências, no saldo de férias, no «Em falta» ou na app do ponto.
- Marcar colaboradores, notas por ida («Extra», «cobre o Weber»), loja fechada.
- Avisos no telemóvel («amanhã vais a Oeiras») — exigiriam outra peça nativa.
- Férias dos gestores (não têm ficha de colaborador).
- Uma página do calendário no portal: a mesma página do bolso abre no browser.
- Sessões mais longas no servidor: as 24 h ficam.

## O desenho

### Ecrã

- **Menu lateral (☰)** no cabeçalho do bolso, num `Sheet side="left"`, com **Faturação**,
  **Calendário**, **Usar Face ID** (só quando a casca o tem e a pessoa ainda não o ligou) e
  **Terminar sessão**. O conteúdo respeita `safe-area-inset-top` e o botão de fechar tem 44 px
  (o do `sheet.jsx` tem 16 px e fica debaixo da notch). Um componente pequeno em
  `pages/bolso/`, usado pelos dois ecrãs. Saem do `BolsoApp.js` para serem partilhados: o
  `useManifestoDoBolso` (o calendário mantém o título e o manifesto) e o `Segmento` (hoje
  constante dentro de `BarraDeAmbito`). A `BarraDeAmbito` fica só na Faturação.
- **Rota nova** `/bolso/calendario`, irmã de `/bolso` em `App.js`, com os mesmos papéis. O
  nginx já devolve o `index.html` a qualquer caminho, por isso o refresh funciona.
- **Calendário** (`pages/bolso/BolsoCalendario.js`):
  - Cabeçalho: ☰, mês e ano, setas ‹ ›, e o botão **Mês | Lista**.
  - **Mês:** `ui/calendar.jsx` com dias de **44 px** (7 × 44 = 308 px cabe em 375), um ponto
    nos dias com gente; tocar num dia mostra por baixo a agenda desse dia, agrupada por loja
    («Alfragide — Débora · manhã»). Abre no dia de hoje.
  - **Lista:** o mês dia a dia, agrupado por loja, a abrir no dia de hoje; dias sem nada não
    aparecem.
  - **Filtros em baixo** (o `Segmento`): **Pessoal** (as minhas idas), **Geral** (as idas de
    todos + os colaboradores pela escala), **Férias** (ausências aprovadas, com o tipo e as
    datas). O filtro e a vista lembram-se no `localStorage`, com try/catch; sem ele abre em
    Mês/Geral.
  - **Feriados** em todos os filtros, como aviso no dia: «Feriado: Implantação da
    República». Um feriado de empresa ou de loja só aparece nas lojas a que se aplica.
  - Linhas da escala do RH levam a marca «escala», para se distinguirem das idas.
  - **O «hoje» é sempre o do telemóvel**; o servidor não decide que mês se vê.
  - Os pedidos vão pelo cliente de `lib/bolso.js`, com caminhos escritos por extenso — é o que o
    teste `tests/fin/test_caminhos_do_bolso.py` lê e confronta com o router.

### Marcar idas (só administradores e gestores)

- Na agenda do dia, **+ Marcar ida** abre um painel por baixo (`Sheet side="bottom"`) com:
  **Loja** (os `locations` do RH), **Pessoa** (as contas `admin`/`gerente`; começa em mim se eu
  estiver na lista, senão vazia), **Período** (Dia | Manhã | Tarde) e **Dias** (um
  mini-calendário do mês em modo múltiplo, com o dia tocado já marcado; no máximo 31).
- Tocar numa ida abre o mesmo painel com **Guardar** e **Apagar**. Mudar uma ida é sobre essa
  ida só (um dia).
- O botão **+ Marcar ida** e o toque nas idas só existem quando o servidor diz `pode_marcar`.
  O contabilista vê o calendário mas não marca.
- Erros dizem o que aconteceu e o que fazer, sem texto cru de excepção: «Já existe essa ida»,
  «Essa pessoa já não é gestora», «Essa loja já não existe».

### Dados

**Colecção nova `bolso_idas`**, um documento por pessoa, dia, loja e período:

```json
{ "id": "uuid", "data": "2026-10-21", "location_id": "...", "user_id": "...",
  "periodo": "manha", "criado_por": "...", "criado_em": "...",
  "alterado_por": "...", "alterado_em": "..." }
```

- `periodo` ∈ `dia` | `manha` | `tarde`.
- `data` entra como `date` no Pydantic e grava-se com `isoformat()` — nunca o texto tal como
  chega (o Python 3.11 aceita «20261021», que depois escapava ao filtro do mês e ao índice).
- **Índice único** em `(data, location_id, user_id, periodo)` — a base recusa o duplicado.
  O código não depende só dele: o POST grava com `update_one(..., upsert=True)` por essas
  quatro chaves, e o PUT procura antes a mesma combinação noutra ida (`id ≠`) e devolve **409**;
  um `DuplicateKeyError` que ainda escape também vira 409. Assim os testes (sem índices) medem o
  mesmo comportamento que a produção.
- Índice em `data` para o pedido do mês.
- Duas lojas no mesmo dia são permitidas. Não há validação de sobreposição (Dia + Manhã).

**A pessoa é `users.id`.** Só se podem marcar `users` com papel `admin` ou `gerente`. Duplicados
por nome (o `geral@` está duas vezes na base) aparecem uma vez por `id`; arrumá-los é do
trabalho dos níveis de conta. Uma ida de alguém que entretanto foi apagado ou deixou de ser
gestor continua a aparecer, com «(conta removida)» — não se apaga dados por arrasto.

### Servidor

Tudo debaixo de `/api/bolso/calendario`. **Ler** usa `admin_manager_required` (a porta da
gestão; inclui o contabilista). **Escrever** exige papel `admin` ou `gerente` — 403 para os
outros. Um colaborador leva 403 em tudo.

| Método | Caminho | O quê |
|---|---|---|
| GET | `/bolso/calendario?ano=&mes=` | tudo o que o mês precisa (abaixo); `ano` e `mes` obrigatórios |
| POST | `/bolso/calendario/idas` | `{datas: [date, …≤31], location_id, user_id, periodo}` → cria N, ignora as que já existem |
| PUT | `/bolso/calendario/idas/{id}` | muda loja, pessoa, período ou dia de uma ida; 409 se já existir |
| DELETE | `/bolso/calendario/idas/{id}` | apaga uma ida |

POST e PUT validam que o `user_id` é um `users` `admin`/`gerente` e que o `location_id` existe;
senão **400** com texto claro.

O GET devolve, num só pedido:

- `idas` do mês, com nome da pessoa e da loja (com recurso «(conta removida)» / «(loja
  removida)»).
- `escala`: a escala do RH **calculada dia a dia** para o mês. Parte de **`employees`** (não das
  atribuições, que podem estar órfãs) e junta as atribuições por `employee_id`. Para cada dia,
  a atribuição que o cobre (a mesma regra de `find_schedule_assignment`; a criação já proíbe
  sobreposições) e os dias de trabalho `atribuição.work_days or modelo.work_days` (o mesmo
  recurso do `_schedule_today`, `:2935`; 0 = segunda, como `weekday()`). Cada linha é
  `{data, nome, loja}` na loja da ficha (`employees.location_id`; sem loja → «Sem loja»).
  **Sai o dia em que o colaborador tem uma ausência aprovada.** Lê sem os `to_list(200)` que a
  escala usa noutros sítios.
- `ausencias`: as aprovadas que tocam o mês, com o filtro de sobreposição do `/calendar/leaves`
  (`:3172-3181`), nomes resolvidos **numa só** consulta `$in` e sem calcular dias contados.
- `feriados`: nacionais e personalizados do mês, **com nome**, e com o âmbito (`company_id` /
  `location_id`) para o ecrã aplicar a mesma regra «OU» do `:823`. Um personalizado com dia
  impossível (30/02) salta-se.
- `lojas` (com `company_id`, para o âmbito dos feriados) e `pessoas` para o painel de marcar.
- `pode_marcar`: verdadeiro para `admin`/`gerente`.

O filtro Pessoal é feito no telemóvel sobre a mesma resposta.

**Feriados com nome:** um dicionário `{data: nome}` para os nacionais, construído à parte; a
função `get_pt_holidays` continua a devolver o mesmo `set` (o único sítio que a usa, `:874`,
não muda) e a cache dela não é tocada.

**Níveis de conta:** o trabalho do ramo `matheus-niveis-de-conta` (ainda fora do main) põe
`bolso` na gaveta `painel`. As rotas novas ficam debaixo de `/api/bolso/`, por isso caem na
mesma gaveta. Quem entrar no main em segundo acrescenta a linha ao mapa; o teste de cobertura
desse trabalho fica vermelho se alguém se esquecer.

### Login com Face ID

**Peça nativa:** `@capgo/capacitor-native-biometric@6.0.4`, versão fixa — a única que aceita
Capacitor 6 e traz numa só peça `isAvailable`, `verifyIdentity`, `setCredentials`,
`getCredentials` e `deleteCredentials` (MIT; regista-se como `NativeBiometric`). Mais
`NSFaceIDUsageDescription` no `Info.plist` («Usamos o Face ID para entrar na Gestão Lisbonb sem
escrever a senha.») e build 3 da casca (`CURRENT_PROJECT_VERSION = 3`).

**O que esta versão faz e não faz** (lido no Swift do pacote): guarda email e senha no
**Keychain** do iOS (`kSecClassInternetPassword`, por `server`), mas **sem os prender ao Face
ID** — o `getCredentials` devolve-os sem pedir nada. Quem garante o Face ID é o nosso código, que
chama `verifyIdentity` **antes** de ler. Fica com `useFallback: false` (só biometria, sem o código
do iPhone). Prender a senha ao Face ID no próprio Keychain só existe na série 8 do plugin, que
exige Capacitor 8 — não compensa migrar a casca agora.

**No site** fica tudo num módulo `lib/faceid.js`, que só faz alguma coisa quando
`Capacitor.isPluginAvailable('NativeBiometric')` — com a build 2, ou no browser, tudo fica como
hoje e nada rebenta. O `@capacitor/core` 6 já está no `frontend`; usa-se `registerPlugin`, sem
instalar o plugin no site.

1. **Primeiro login com senha** → «Usar Face ID para entrar?».
   - Sim → guarda o email **devolvido pelo servidor** e a senha no Keychain.
   - Não → guarda `faceid_recusado:<email>` no `localStorage` e não volta a perguntar. Quem
     mudar de ideias usa **Usar Face ID** no menu lateral.
2. **Barreira.** Ao abrir a app, e ao voltar a ela depois de **mais de 5 minutos fora**, um ecrã
   opaco tapa tudo até o Face ID passar («Entrar como <email>»). A hora de saída grava-se no
   `localStorage` ao ficar escondida (`saiuAs`), para sobreviver ao iOS matar a app; sem
   `saiuAs`, conta como arranque. Os dados não se pedem enquanto a barreira estiver fechada (o
   `visibilitychange` do bolso espera por ela), e a barreira fecha-se logo ao esconder, para a
   miniatura do selector de apps não mostrar a faturação.
3. **Face ID falhou ou foi cancelado** → `logout()` (apaga o token, **não** o Keychain) e o
   login normal. Sem isto, o ecrã de login devolvia a pessoa para dentro, porque o token ainda
   era válido.
4. **Sessão expirada** (no arranque, ou um 401 a meio) → **uma só re-entrada partilhada**: a
   primeira resposta 401 lança-a e as outras esperam por ela (`reentrar = emCurso ??= …`). Faz
   Face ID (se a barreira não acabou de o fazer), lê o Keychain e `POST /auth/login`; grava o
   token e repete o pedido uma vez. Se falhar, login normal.
5. **Só um 401 do login apaga o Keychain** (a senha foi trocada noutro sítio). Um 429 (limite
   por IP — numa rede partilhada as falhas dos outros contam) ou a rede em baixo mostram o login
   e **mantêm** o Keychain.
6. **Terminar sessão** é uma função à parte, `terminarSessao()` = `logout()` + apagar o
   Keychain. O `logout()` dos 401 não apaga o Keychain.
7. **Dois gestores no mesmo iPhone:** o Keychain guarda uma conta por app; quem activar o Face
   ID por último fica com ele. A barreira diz sempre «Entrar como <email>».

**No servidor não muda nada.** As 24 h ficam, trocar a senha continua a cortar as sessões, e
o formato do token não muda (a app do ponto leva o código congelado no bundle).

**Duas correcções que vão junto (só site):**

- **Sem ligação:** se o `/auth/me` do arranque falhar por outra razão que não 401/403, o
  `AuthContext` guarda `semLigacao` e mantém o token; o `ProtectedRoute` mostra «Sem ligação —
  tentar de novo» em vez de mandar para o login. **Isto muda também o portal no browser** (é a
  mesma peça): passa a mostrar «Sem ligação» em vez do login quando o servidor não responde —
  é uma melhoria e fica dito. A app do ponto só a recebe na próxima build dela.
- O 401 do bolso leva `state.from`, e depois de entrar volta ao ecrã onde se estava
  (Faturação ou Calendário).

## Entrega por fases

**Fase 1 — menu lateral e calendário** (deploy, sem build). Servidor, ecrã, marcar idas.
Depois de estar no ar, e com confirmação do dono antes de escrever, carregar as idas de
outubro a dezembro da mensagem (só gestores; Deb/Débora são a mesma pessoa, Car é a Carol).

**Fase 2 — login.** Primeiro o código do site (`lib/faceid.js`, barreira, re-entrada, as duas
correcções), em deploy — com a build 2 instalada nada muda, excepto as duas correcções. Depois a
build 3 da casca, no TestFlight; o dono, o Bruce, a Carol e a Débora actualizam lá.

## Testes

Antes de correr a suite na worktree, `yarn install` no `frontend` — sem `node_modules` a suite
salta os testes do frontend em silêncio. Ler sempre `passed` **e** `skipped`.

1. **Escala calculada:** dia da semana dentro e fora do `work_days`; `work_days` da atribuição
   vs do modelo; duas atribuições no mês (uma acaba a 10, outra começa a 11); atribuição sem
   fim; atribuição órfã (colaborador apagado) não aparece; ausência aprovada tira o dia;
   pendente não tira.
2. **Feriados:** nacionais com nome; personalizado de loja só nessa loja; de empresa em todas as
   lojas dela; dia impossível salta-se sem 500; a cache de `get_pt_holidays` fica igual.
3. **Marcar:** vários dias de uma vez criam N idas; repetir o pedido não duplica; PUT para uma
   combinação existente dá 409; data em formato estranho é recusada; pessoa que não é gestora ou
   loja inexistente dão 400; mudar e apagar mexem só na ida certa.
4. **Porta:** um colaborador leva 403 nas 4 rotas; o contabilista lê (200, `pode_marcar` falso)
   e leva 403 a escrever; administrador e gestor escrevem.
5. **Caminho:** as chamadas novas em `lib/bolso.js` são apanhadas pelo
   `tests/fin/test_caminhos_do_bolso.py`, que as confronta com `server.app.routes`.
6. **Face ID e sessão (no site, com o plugin simulado):** cancelar fecha a porta; dois 401 ao
   mesmo tempo dão uma só re-entrada; 401 do login apaga o Keychain, 429 e sem rede não; o «não»
   fica lembrado; Terminar sessão apaga o Keychain e o 401 não; sem plugin nada muda.
7. **Cada teste é visto vermelho primeiro** (mutação da regra que prende).
8. **Ecrãs:** num browser a 375 px, claro e escuro, com a zona da notch; os dias com 44 px; o
   `mode="multiple"` do react-day-picker 8 com o date-fns 4 instalado, a sério.
9. **Face ID na casca:** no simulador do iPhone (rosto certo, rosto errado, cancelar, sessão
   expirada, senha trocada, app morta e reaberta), depois no telemóvel do dono.
10. **Depois do deploy:** confirmar que o ficheiro servido é o novo (o `deploy.sh` já entregou
    código antigo) e fazer uma marcação real, que depois se apaga.

## Riscos aceites

- As férias dos gestores não aparecem (não têm ficha de colaborador).
- Os extras dos colaboradores ficam fora (decisão 1).
- Um colaborador aparece sempre na loja da ficha, mesmo que nesse dia cubra outra.
- A senha fica no Keychain do iPhone e o Face ID é pedido pelo nosso código antes de a ler, não
  pelo Keychain (limite da versão 6 do plugin). Só esta app lê o seu Keychain, e dentro dela a
  senha só é lida depois do Face ID.
- O portal no browser passa a mostrar «Sem ligação» em vez do login quando o servidor não
  responde ao arranque.
- A Carol e a Débora, como gestoras, vêem o portal inteiro até os níveis de conta entrarem.
  Já é assim hoje; o calendário não muda nada.
