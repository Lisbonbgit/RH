# Calendário: trocas de pessoas e histórico — Plano de execução

> **Para agentes:** SUB-SKILL OBRIGATÓRIO: usar superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para executar este plano tarefa a tarefa. Os passos usam caixas (- [ ]).

**Objetivo:** os administradores trocam pessoas no calendário da app Gestão Lisbonb (num dia da escala, ou duas entre si) e toda a gente que vê o calendário vê o histórico de quem mudou o quê.

**Arquitectura:** uma troca é uma ida (`bolso_idas`) com `troca_id` e `no_lugar_de_emp`; o cálculo puro (`backend/calendario.py`) tira à escala de quem sai as horas da troca. O servidor ganha três rotas `/trocas` (só admin), uma `/historico` e uma colecção `bolso_historico` escrita pelas seis rotas de escrita. O ecrã ganha o `PainelTroca`, a linha «no lugar de» e o painel do histórico; as contas novas do ecrã vivem em `frontend/src/lib/calendario.js` (puro, testado em Node).

**Tecnologia:** FastAPI + Motor/Mongo (backend), React 19 + Tailwind + shadcn (frontend), pytest + mongod real (`backend/tests/calendario/conftest.py`) + Node/babel/jsdom (`backend/tests/bolso_js.py`).

## Restrições globais

- Fonte de verdade: `docs/superpowers/specs/2026-10-20-calendario-trocas-historico-design.md` (as «Decisões do dono» não se discutem). Lê também o mapa do código já feito: `.superpowers/sdd/trocas-mapa.md` (confirma no código o que usares).
- Trabalhar só em `/Users/matheus.moraes/Developer/RH-calendario-trocas` (ramo `matheus-calendario-trocas`). Nunca tocar em `~/Developer/RH`, `~/Developer/RH-calendario` nem `~/Developer/RH-qr-aplicacoes`.
- `frontend/node_modules` é um atalho para `~/Developer/RH-calendario/frontend/node_modules` (instalação completa, com o `leaflet`): não se mexe nele nem se instala nada.
- Python dos testes: `~/Developer/RH/backend/.venv/bin/python` (3.9.6 — nada de `X | Y` em anotações nem `match`), sempre com `PYTHONDONTWRITEBYTECODE=1` e `-p no:cacheprovider`, a partir de `backend/`. `export PATH="$HOME/.local/node/bin:$PATH"` para os testes de Node. Ler SEMPRE `passed` E `skipped`.
- Mutações com `backend/tests/mutar.py` (repõe o ficheiro e limpa `~/Library/Caches/com.apple.python`). Um teste só vale depois de visto vermelho pela razão certa.
- Na fase vermelha, testes de Node com `-x` e `-k` só nos novos: um teste à espera de uma promessa que nunca chega só sai pelo `timeout`.
- Mensagens ao utilizador sem artigo nem género (o RH não guarda o género): «Emily não está na escala a 27/10.».
- Datas em texto «AAAA-MM-DD»; no ecrã nunca `toISOString()`. Alvos de toque de 44 px; tudo cabe a 375 px sem deslizar para o lado; claro e escuro.
- Pedidos do ecrã só por `frontend/src/lib/bolso.js`, com caminhos literais (o guarda `tests/fin/test_caminhos_do_bolso.py` lê-os); um 401 faz `logout()` (do `useAuth`), nunca `navigate('/login')`.
- Commits: `git add` de ficheiros nomeados; mensagem em português que diz o porquê, terminada com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Nunca `git clean` nem `git stash -u`.
- Sem push, merge, deploy nem produção (o controlador publica com o «sim» do dono).

---

## Mapa de ficheiros

| Ficheiro | Responsabilidade |
|---|---|
| `backend/calendario.py` | ajudante do feriado; `escala_de`; troca no `dia_do_calendario`; campos novos em `_pessoa` e `idas[]`; `pode_trocar`; `contagem(papeis)`; regras puras da troca |
| `backend/server.py` | rotas `/bolso/calendario/trocas`, `/trocas/entre-si`, `/trocas/{id}`, `/historico`; guarda das idas de troca no PUT/DELETE; `bolso_historico` e índices |
| `frontend/src/lib/bolso.js` | `trocar`, `trocarEntreSi`, `desfazerTroca`, `getHistorico` |
| `frontend/src/lib/calendario.js` | `escaladosDoDia`, `linhaDoHistorico` |
| `frontend/src/pages/bolso/PainelTroca.js` (novo) | trocar (Outra pessoa / Trocar turnos) e desfazer |
| `frontend/src/pages/bolso/BolsoCalendario.js` | linha da escala tocável, «no lugar de», encaminhamento das trocas, botão e painel do histórico |
| `backend/tests/calendario/…` | testes puros, de rotas (mongod) e de ecrã (Node) |

---

### Tarefa 1: O cálculo puro da troca

**Ficheiros:** `backend/calendario.py`; testes puros em `backend/tests/calendario/` (um ficheiro novo `test_trocas.py`, e actualizar `test_outubro.py` e `test_resposta_do_mes.py` onde comparam formas exactas).

**Interfaces (Produz — nomes exactos):**
- `escala_vazia_no_feriado(dia, personalizados, loja) -> bool` (o ajudante único: `do_dia or feriados_da_loja(...)`), usado pelo `dia_do_calendario` e pelo `escala_de`.
- `escala_de(dia: date, dados: Dict, emp_id: str, p=None) -> Optional[Tuple[str, Intervalo]]`: `(location_id, (ini, fim))` da escala dessa ficha nesse dia, depois das ausências aprovadas e do feriado; `None` se não está na escala.
- No `dia_do_calendario`: uma ida com `no_lugar_de_emp` acrescenta as horas ao `tirado[no_lugar_de_emp]` **só se** a escala de quem sai nesse dia é na `location_id` da ida; `extra` de uma ida com `troca_id` = quem entra tem ausência aprovada nesse dia.
- `_pessoa(...)` ganha `troca_id` e `no_lugar_de` (o NOME de quem sai, de `nome_do_emp`), sempre presentes (`None` fora das trocas). `idas[]` da `resposta_do_mes` ganha os mesmos dois campos.
- `resposta_do_mes(ano, mes, dados, eu, pode_marcar, pode_trocar=False)` devolve também `pode_trocar`.
- `contagem(idas, lojas, nomes, papeis=None)`: com `papeis` (`{user_id: role}`), salta as idas com `troca_id` cujo papel não está em `GESTORES`.
- Regras puras (devolvem a mensagem ou `None`; o servidor transforma em 400/409):
  - `recusa_da_troca(dia, dados, sai_emp, sai_nome, entra_user, inicio, fim, idas_do_dia) -> Optional[Tuple[int, str]]` com os casos da tabela «Recusas» do desenho que não dependem de papel nem de ausência de quem entra (não está na escala; horas fora das de quem sai; `sai` = `entra`; já há troca para quem sai com horas que se sobrepõem). Frases exactas do desenho.
  - `turnos_da_troca_entre_si(dia, dados, emp_a, emp_b) -> (ida_a, ida_b)` ou a recusa (`(400|409, frase)`): cada um vai para a loja e as horas do outro; recusa se algum não está na escala, se loja e horas são iguais, ou se algum já tem troca nesse dia.

- [ ] Testes primeiro, com os dados de `dados_semana_normal.py` (a 27/10: Emily em Alfragide 14–23, Joana na Amadora 14–23, Beatrice e Weber de folga; a 30/10: Emily 14–23 e Beatrice 10–19 em Alfragide): os casos da secção 5, ponto 1, 2 e 3 do desenho, mais cada recusa pura. Ver vermelho pela razão certa.
- [ ] Implementar o mínimo; verdes; actualizar de propósito `test_outubro.py` e `test_resposta_do_mes.py` (campos novos).
- [ ] Mutações (uma por regra): tirar a condição «na loja da troca»; `extra` sempre `False`; a contagem sem o salto; `escala_de` sem o feriado.
- [ ] Correr `tests/calendario` inteiro; commit.

### Tarefa 2: As rotas das trocas

**Ficheiros:** `backend/server.py`; `backend/tests/calendario/test_rotas_das_trocas.py` (novo) e os testes de rotas que já existem.

**Interfaces:**
- Consome: Tarefa 1.
- `bolso_quem_troca` (dependência): `admin_manager_required` + `role == "admin"`, senão **403** «Só os administradores trocam pessoas.».
- `POST /api/bolso/calendario/trocas` corpo `BolsoTrocaIn{data: date, sai: str, entra: str, inicio: str, fim: str}` → grava 1 ida `{id, data, location_id (da escala de quem sai), user_id: entra, inicio, fim, troca_id, no_lugar_de_emp, criado_por, criado_em, alterado_por: None, alterado_em: None}`; devolve `{"troca_id", "ids": [...]}`.
- `POST /api/bolso/calendario/trocas/entre-si` corpo `BolsoTrocaEntreSiIn{data: date, uma: str, outra: str}` → grava 2 idas com o mesmo `troca_id`, tudo ou nada pela compensação que já existe.
- `DELETE /api/bolso/calendario/trocas/{troca_id}` → apaga todas as idas com esse `troca_id`; 404 se nenhuma; devolve `{"desfeita": troca_id, "apagadas": n}`.
- `PUT` e `DELETE /api/bolso/calendario/idas/{id}`: lêem a ida; com `troca_id` → **409** «Isto é uma troca: desfaça-a e faça outra.» (404 primeiro).
- Validações de quem entra reutilizam `_bolso_validar_idas` (horas, papel escalável, ausência 409, choque 409). `sai`/`uma`/`outra` sem `employee_id` → 400.
- GET do mês passa `pode_trocar=role=="admin"`; a GET da contagem projecta `troca_id` e `role` e chama `contagem(..., papeis)`.

- [ ] Testes primeiro: cada linha da tabela «Recusas»; o gerente leva 403 nas três rotas; tudo-ou-nada na troca entre si (monkeypatch como o teste de compensação que existe); PUT/DELETE de uma ida de troca → 409; desfazer apaga as duas; `pode_trocar` admin sim, gerente não; a contagem com troca de colaboradores não conta.
- [ ] Implementar; verdes; mutações (tirar o `role == "admin"`; tirar o 409 do PUT; desfazer só uma ida).
- [ ] `tests/calendario` inteiro; commit.

### Tarefa 3: O histórico no servidor

**Ficheiros:** `backend/server.py`; `backend/tests/calendario/test_historico.py` (novo).

**Interfaces:**
- Colecção `bolso_historico` com índices em `datas` e `quando` (criados no arranque, ao lado dos de `bolso_idas`; o `test_os_indices_das_idas` que exige UM índice único em `bolso_idas` continua verde).
- `_bolso_registar(current_user, acao, antes: List[dict], depois: List[dict])`: escreve `{id, quando, quem_id, quem_nome, acao, datas, antes, depois}` com os retratos `{data, loja, nome, inicio, fim, no_lugar_de}` (nomes resolvidos no momento); `datas` = união das datas de `antes` e `depois`. Uma falha só vai para o log (`logger.exception`), nunca rebenta a rota.
- As seis rotas chamam-no depois de gravar: POST idas (`marcou`), PUT (`alterou`, só se algum dos cinco campos mudou), DELETE idas (`apagou`, lê a ida antes de apagar), POST trocas (`trocou`), POST entre-si (`trocou entre si`), DELETE troca (`desfez a troca`, lê as idas antes).
- `GET /api/bolso/calendario/historico?ano&mes` (`admin_manager_required`): `{"datas": {"$elemMatch": {"$gte": inicio, "$lte": fim}}}`, `quando` descendente, máx. 300; devolve `{"entradas": [...]}` sem `_id`.

- [ ] Testes primeiro: cada rota deixa a entrada certa (antes/depois); PUT sem diferenças não deixa; falha do histórico (monkeypatch do `insert_one` a rebentar) não desfaz a ida e a rota devolve 200; o GET do mês com o PUT de 30/09 → 02/11 (aparece em setembro e novembro, não em outubro); ordem e limite.
- [ ] Implementar; verdes; mutações (o `$elemMatch` trocado por `$gte`/`$lte` soltos; o registo do PUT sem a comparação).
- [ ] `tests/calendario` inteiro; commit.

### Tarefa 4: As chamadas e as contas do ecrã (puras)

**Ficheiros:** `frontend/src/lib/bolso.js`, `frontend/src/lib/calendario.js`; `backend/tests/fin/test_caminhos_do_bolso.py` e `backend/tests/calendario/test_chamadas_do_calendario.py` (acrescentar as quatro chamadas); o teste em Node das funções de `lib/calendario.js` que já existe.

**Interfaces (Produz):**
- `trocar(corpo)` POST `/calendario/trocas`; `trocarEntreSi(corpo)` POST `/calendario/trocas/entre-si`; `desfazerTroca(trocaId)` DELETE `` `/calendario/trocas/${trocaId}` ``; `getHistorico(ano, mes)` GET `/calendario/historico` com `{ano, mes}`.
- `escaladosDoDia(dados, iso, saiUserId) -> [{user_id, nome, location_id, loja, inicio, fim}]`: das `dias[].lojas[].pessoas[]` desse dia, só `origem === 'escala'` com `user_id`, sem quem sai, uma por `user_id` (a primeira), ordenadas por nome.
- `linhaDoHistorico(entrada) -> string`: os seis textos da tabela do desenho (com `quandoFoi` de `lib/bolso.js` para «20/10 às 14:32»); lote grande: os 3 primeiros dias e «e mais N».

- [ ] Testes primeiro (guarda de caminhos com as quatro chamadas; corpos em `test_chamadas_do_calendario.py`; `escaladosDoDia` com filtro ausente, sem quem sai, sem repetidos e sem quem não tem conta; `linhaDoHistorico` para as seis acções e o lote).
- [ ] Implementar; verdes; mutações; commit.

### Tarefa 5: O ecrã das trocas

**Ficheiros:** `frontend/src/pages/bolso/PainelTroca.js` (novo), `frontend/src/pages/bolso/BolsoCalendario.js`; testes de ecrã (`backend/tests/calendario/test_ecra_do_calendario.py` ou um ficheiro novo `test_ecra_das_trocas.py`, com `tests/bolso_js.py`).

**Comportamento:**
- No `LojaDoDia`, a linha de uma pessoa com `origem === 'escala'`, `user_id` e `dados.pode_trocar` é um botão (pela própria `Linha`), `aria-label` «Trocar <nome>, <início>–<fim>», que abre o `PainelTroca` com `{modo: 'trocar', data, location_id, nome da loja, sai: {user_id, nome, inicio, fim}, turnoInteiro}` (`turnoInteiro` = a linha é a única dessa pessoa nesse dia).
- `PainelTroca` (Sheet em baixo, como o `PainelIda`): título «Trocar <nome>», dia e loja; `Segmento` «Outra pessoa» | «Trocar turnos» (o segundo só com `turnoInteiro`):
  - Outra pessoa: pessoas de `dados.pessoas` sem quem sai, agrupadas Gestores/Colaboradores; ao lado de quem está em `escaladosDoDia` noutra loja, «na escala em <loja curta> <horas>»; horas preenchidas com as de quem sai; botão «Trocar» → `trocar({data, sai, entra, inicio, fim})`.
  - Trocar turnos: lista de `escaladosDoDia(desteMes, data, sai)` (cada um com loja e horas); botão «Trocar turnos» → `trocarEntreSi({data, uma: sai, outra})`.
  - Modo `desfazer` (aberto a partir de uma ida com `troca_id`): mostra a troca (as duas idas na troca entre si, «Desfazer apaga as duas») e «Desfazer a troca» com dois toques → `desfazerTroca(troca_id)`.
  - Erros por `mensagemDeErro` dentro do painel; 401 → `logout()`; sucesso → fecha e recarrega como o `guardado` do `PainelIda`.
- Pessoas com `troca_id` (no Dia, na Lista e no Pessoal): segunda linha pequena «no lugar de <primeiro nome>» por baixo do nome e etiqueta «troca».
- O `editar(idaId)` encaminha: `troca_id` + `pode_trocar` → `PainelTroca` em `desfazer`; `troca_id` sem `pode_trocar` → nada (a linha nem é tocável); sem `troca_id` → como hoje.

- [ ] Testes de ecrã primeiro: o botão da linha da escala só para admin; «Outra pessoa» envia o corpo certo e mostra «na escala em…»; «Trocar turnos» só no turno inteiro e envia o corpo certo; a troca aparece com «no lugar de» no Dia, na Lista e no Pessoal; o gerente vê-a como texto (não é botão); Desfazer com dois toques; 409 mostra a frase do servidor; 401 → logout.
- [ ] Implementar; verdes; mutações (tirar a condição `pode_trocar` da linha; o encaminhamento do `editar`); commit.

### Tarefa 6: O ecrã do histórico

**Ficheiros:** `frontend/src/pages/bolso/BolsoCalendario.js` (e um componente pequeno no mesmo ficheiro ou em `PainelHistorico.js`); testes de ecrã.

**Comportamento:**
- Botão de 44 px com o ícone `History` (lucide), `aria-label` «Histórico», no cabeçalho entre o título e as setas (cabe a 375 px).
- Abre um Sheet em baixo «Histórico de <mês>» (o mês do dia escolhido); o `getHistorico(ano, mes)` sai **só ao abrir** (o teste que exige exactamente um GET ao abrir o ecrã continua verde); lista com `linhaDoHistorico`; vazio: «Sem alterações registadas neste mês. O histórico começou em outubro de 2026.»; erros dentro do painel; 401 → `logout()`.

- [ ] Testes de ecrã primeiro (abrir pede uma vez o mês certo, também numa Semana que atravessa dois meses; a lista; o vazio; o erro; o 401).
- [ ] Implementar; verdes; mutações; commit.

### Tarefa 7 (controlador): ensaio no browser e publicar

- Ensaio local a 375 px em claro e escuro, com uma base de ensaio com lojas, escalas e pessoas (`$HOME/.cache/lisbonb-calendario-local/` tem o padrão dos semeadores da Fase 2): trocar, trocar turnos, desfazer, o gerente a ver sem tocar, o histórico.
- Suite completa (só as falhas da linha de base); publicar com o «sim» do dono (cópia limpa do `origin/main`, merge, suite, push, deploy, verificar o ficheiro servido).

---

## Auto-revisão

- Cobertura do desenho: §1 cálculo/forma (T1), recusas e rotas (T1 regras puras + T2), mudar/desfazer (T2), contagem (T1+T2), §2 histórico (T3 servidor, T4 textos, T6 ecrã), §3 ecrã (T4 contas, T5 trocas, T6 histórico), §5 testes 1–7 (T1–T7).
- Nomes usados em várias tarefas: `escala_de`, `escala_vazia_no_feriado`, `troca_id`, `no_lugar_de_emp`, `no_lugar_de`, `pode_trocar`, `contagem(papeis)`, `recusa_da_troca`, `turnos_da_troca_entre_si`, `bolso_quem_troca`, `_bolso_registar`, `trocar`, `trocarEntreSi`, `desfazerTroca`, `getHistorico`, `escaladosDoDia`, `linhaDoHistorico`, `PainelTroca`.
