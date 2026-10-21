# Calendário: vista Semana e filtro de loja — Plano de execução

> **Para agentes:** SUB-SKILL OBRIGATÓRIO: usar superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para executar este plano tarefa a tarefa. Os passos usam caixas (- [ ]).

**Objetivo:** juntar ao calendário da app Gestão Lisbonb a vista **Semana** (lojas × 7 dias) e um **filtro de loja**, como na adenda de 2026-10-15 do desenho.

**Arquitectura:** as contas novas vivem no módulo puro `frontend/src/lib/calendario.js` (testado em Node pelo pytest, como as outras); o ecrã `BolsoCalendario.js` só desenha. O servidor só ganha um campo (`location_id` da ficha em cada ausência). Uma semana que atravessa dois meses pede os dois ao servidor (o GET do mês fica igual).

**Tecnologia:** React 19 + Tailwind (frontend), FastAPI (backend), pytest + Node/babel/jsdom (`backend/tests/bolso_js.py`).

## Restrições globais

- As do ficheiro `.superpowers/sdd/f2b-constraints.md` (as da Fase 2 mais a adenda).
- Fonte de verdade: a «Adenda de 2026-10-15 — vista Semana e filtro de loja» em `docs/superpowers/specs/2026-10-14-calendario-gestao-design.md`.
- Alvos de toque de 44 px; o ecrã cabe em 375 px sem deslizar para o lado (a grelha da Semana incluída: coluna dos nomes ~62 px + 7 colunas).
- Cores dos estados com os pares já medidos do calendário (o «—» como o selo «ninguém», a falta como o selo «falta»; nada de `text-*-strong` como texto no escuro).
- Datas sempre em texto «AAAA-MM-DD» e dia da semana com `diaDaSemana` (já existe; 0 = segunda); nunca `toISOString()`.

---

## Mapa de ficheiros

| Ficheiro | Responsabilidade |
|---|---|
| `frontend/src/lib/calendario.js` | `VISTAS` passa a `['semana','mes','lista','contagem']`; funções novas da semana e do filtro de loja |
| `backend/tests/test_calendario_no_ecra.py` (ou o ficheiro de testes de `lib/calendario.js` que já exista) | testes das funções novas em Node |
| `backend/calendario.py` | `ausencias[].location_id` (a loja da ficha) na resposta do mês |
| `backend/tests/calendario/…` (o ficheiro que já testa `resposta_do_mes`) | teste do campo novo |
| `frontend/src/pages/bolso/BolsoCalendario.js` | vista Semana, navegação por semana, pedidos de dois meses, filtro de loja, «Marcar ida» com a loja |
| `backend/tests/…` (o ficheiro de testes de ecrã do calendário que já exista) | testes de ecrã |

---

### Tarefa 1: As contas da semana e do filtro de loja (puras) + `location_id` nas ausências

**Ficheiros:** `frontend/src/lib/calendario.js`; o teste em Node das funções de `lib/calendario.js` que já existe (procura `lib/calendario.js` em `backend/tests`); `backend/calendario.py` (`resposta_do_mes`) e o teste que já prende a forma de `ausencias[]`.

**Interfaces (Produz — nomes exactos):**
- `VISTAS = ['semana', 'mes', 'lista', 'contagem']`.
- `semanaDe(iso) -> string[7]`: os 7 dias ISO de segunda a domingo da semana que contém `iso`.
- `diaAoLado(iso, passo) -> string`: `iso` + `passo` dias (passo pode ser ±7), sem `Date` em UTC a mudar o dia.
- `mesesDaSemana(iso) -> [{ano, mes}, …]`: 1 ou 2 meses, por ordem.
- `tituloDaSemana(iso) -> string`: «26 out – 1 nov»; no mesmo mês «5 – 11 out»; atravessando o ano «29 dez – 4 jan» (meses abreviados em minúsculas: jan, fev, mar, abr, mai, jun, jul, ago, set, out, nov, dez).
- `nomeCurtoDaLoja(nome) -> string`: tira um «Loja » do início (sem mexer no resto).
- `celulaDaSemana(lojaDoDia, filtro, eu) -> {estado, texto}` com `lojaDoDia` = o objecto de `dias[].lojas[]` do servidor (ou `undefined`):
  - `filtro === 'geral'`: `estado` ∈ `'ok' | 'falta' | 'ninguem' | 'fechada' | 'vazia'`; `texto` = «ok», a primeira falta como `intervaloCurto` («10–14») ou «2 faltas» se houver mais de um buraco, «—», «fech.», «» (por abrir ou loja sem dados nesse dia → `'vazia'`). «ninguem» = um buraco igual a abre–fecha.
  - `filtro === 'pessoal'`: `estado` `'minha'` com `texto` = as horas das minhas idas nessa loja nesse dia (`pessoas` com `origem === 'ida'` e `user_id === eu`; várias juntas por « · »), senão `'vazia'`.
- `juntarMeses(respostas) -> dados`: junta 1 ou 2 respostas do GET do mês numa só forma que as funções existentes aceitem para os dias pedidos (`dias`, `idas`, `ausencias` sem repetidos, `lojas`, `pessoas`, `eu`, `pode_marcar` da primeira).
- `filtrarPorLoja(dados, locationId) -> dados`: com `locationId` vazio devolve `dados`; senão só essa loja em `dias[].lojas`, em `idas` e em `lojas`, e as `ausencias` com esse `location_id`.
- `diasComPonto`, `lista` e as outras funções existentes continuam a funcionar sobre o resultado de `filtrarPorLoja` (não lhes mudes a assinatura se não for preciso).
- Backend: cada `ausencias[]` ganha `location_id` = a loja da ficha do empregado (ou `null`).

- [ ] Testes primeiro (vermelhos pela razão certa): `semanaDe('2026-10-29')` = 26/10…01/11; `semanaDe` num domingo e numa segunda; `diaAoLado` a atravessar o mês e o ano e a mudança de hora de 25/10; `mesesDaSemana` com 1 e 2 meses; os três formatos do título; `nomeCurtoDaLoja('Loja Alfragide')` = «Alfragide» e `('Escritório')` igual; `celulaDaSemana` para cada estado (usa os dados da semana normal que os testes já têm, ex. 27/10: Alfragide falta 10–14, Belém fechada, Oeiras ninguém, Benfica por abrir antes de 24/10 → vazia) e o Pessoal; `juntarMeses` sem repetidos; `filtrarPorLoja`; e o `location_id` nas ausências (backend).
- [ ] Implementar o mínimo; verdes; prova por mutação (uma por regra que importa: o domingo como fim da semana, o «ninguém» vs «falta», o filtro das ausências por loja).
- [ ] Suite completa (só as 27 falhas de tests/crm); commit.

### Tarefa 2: A vista Semana no ecrã

**Ficheiros:** `frontend/src/pages/bolso/BolsoCalendario.js`; os testes de ecrã do calendário.

**Comportamento:**
- O botão do topo passa a **Semana | Mês | Lista | Contagem**; a vista por omissão (sem nada guardado) é `'semana'`; uma vista guardada que seja válida mantém-se.
- Há **um só dia escolhido** (`escolhido`). Na Semana, o título do cabeçalho é `tituloDaSemana(escolhido)` e as setas (`aria-label` «Semana anterior»/«Semana seguinte») mudam `escolhido` ±7 dias e o mês à vista para o mês do novo `escolhido`. No Mês e na Lista as setas continuam a mudar de mês, como hoje.
- **Pedidos:** na Semana pede-se cada mês de `mesesDaSemana(escolhido)` (`getCalendario`), guardando as respostas por mês, e junta-se com `juntarMeses`; a guarda de pedidos atrasados continua (uma resposta antiga nunca pisa a mais recente); enquanto faltar um dos meses, esqueleto. Nas outras vistas, o mês como hoje.
- **A grelha:** cabeçalho com «S 26 / T 27 / …» (inicial do dia + número); uma linha por loja de `dados.lojas` (nome curto), uma célula por dia com `celulaDaSemana`; o dia escolhido com aro; cada célula é um botão de 44 px de alto que escolhe esse dia. Por baixo, a agenda desse dia (o mesmo componente `Dia` do Mês, com Tapar e as idas).
- **Filtros:** Geral e Pessoal desenham a grelha; Férias mostra a lista das ausências que tocam a semana (o mesmo `AusenciaLinha`), sem grelha.
- «Marcar ida» também aparece na Semana (como no Mês).
- Cabe em 375 px sem deslizar; células legíveis em claro e escuro.

- [ ] Testes de ecrã primeiro: a Semana abre por omissão; a grelha de 26/10–01/11 com a semana normal mostra os estados certos em pelo menos 4 células (incl. «fech.», «—», «10–14» e «ok»); ‹ › a atravessar outubro/novembro pede os dois meses e mostra «26 out – 1 nov»; tocar numa célula mostra esse dia por baixo; Pessoal mostra as horas das minhas idas; Férias mostra a lista da semana; uma resposta atrasada de outra semana não pisa a actual.
- [ ] Implementar; verdes; prova por mutação (ex.: tirar o pedido do segundo mês; a seta a andar 1 dia em vez de 7).
- [ ] Suite completa; commit.

### Tarefa 3: O filtro de loja

**Ficheiros:** `frontend/src/pages/bolso/BolsoCalendario.js` (e `PainelIda.js` só se for preciso para a loja inicial); os testes de ecrã.

**Comportamento:**
- Uma fila de pastilhas por baixo do botão das vistas, só nas vistas Semana, Mês e Lista: «Todas» + uma por loja de `dados.lojas`, com `nomeCurtoDaLoja`; deslizável na horizontal dentro da própria fila (a página não desliza); 44 px de alto; a escolhida destacada; `aria-pressed`.
- Guardada no `localStorage` (`bolso_cal_loja`, com try/catch); se a loja guardada não existir em `dados.lojas`, conta como «Todas».
- Aplica-se com `filtrarPorLoja` antes de desenhar a Semana, o Mês (pontos e agenda), a Lista e as Férias. A Contagem não muda.
- Com uma loja escolhida, «Marcar ida» abre o painel com `location_id` dessa loja (e as horas, como já acontece ao escolher a loja no painel).
- Tapar e editar continuam a funcionar com o filtro ligado.

- [ ] Testes de ecrã primeiro: escolher «Oeiras» deixa na Semana só a linha de Oeiras, no Mês só os pontos dos dias em que Oeiras tem buraco, na Lista só Oeiras, e nas Férias só as ausências de quem tem Oeiras na ficha; recarregar mantém «Oeiras»; uma loja guardada que não existe volta a «Todas»; «Marcar ida» com «Oeiras» abre com Oeiras e as horas 13:00–22:00.
- [ ] Implementar; verdes; prova por mutação (ex.: não aplicar o filtro na Lista; não validar a loja guardada).
- [ ] Suite completa; commit.

---

## Auto-revisão

- Cobertura da adenda: Semana (T2), primeira vista e omissão (T1 `VISTAS` + T2), células e estados (T1+T2), 7 dias e dois meses (T1 `diaAoLado`/`mesesDaSemana`/`juntarMeses` + T2), Pessoal/Férias na Semana (T1+T2), filtro de loja e memória (T3), Férias por loja (T1 `location_id` + T3), «Marcar ida» com a loja (T3).
- Nomes usados em várias tarefas: `VISTAS`, `semanaDe`, `diaAoLado`, `mesesDaSemana`, `tituloDaSemana`, `nomeCurtoDaLoja`, `celulaDaSemana`, `juntarMeses`, `filtrarPorLoja`, `ausencias[].location_id`.
