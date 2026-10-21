# Calendário das lojas, Fase 2: o calendário automático na app — Plano de execução

> **Para agentes:** SUB-SKILL OBRIGATÓRIO: usar superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para executar este plano tarefa a tarefa. Os passos usam caixas (- [ ]).

**Objetivo:** A app Gestão Lisbonb (`/bolso`) ganha um menu lateral e um Calendário que calcula sozinho, a cada pedido, onde falta gente em cada loja (horário da loja + escala de cada pessoa + ausências aprovadas + idas marcadas), deixa as gestoras tapar esses buracos com idas e conta quantos dias cada uma fez — e as idas de outubro a dezembro da mensagem de WhatsApp ficam carregadas por um script que o dono corre.

**Arquitectura:** Um módulo Python puro novo, `backend/calendario.py` (sem Mongo nem FastAPI, como o `bolso.py`), faz toda a conta; cinco rotas novas no `api_router` do `server.py` (`/api/bolso/calendario…`) só lêem/gravam e chamam-no, com a colecção nova `bolso_idas`. No ecrã, um módulo puro `frontend/src/lib/calendario.js` faz as contas da grelha e da lista, `pages/bolso/partilhado.js` junta o que os dois ecrãs do bolso partilham (menu ☰ incluído), e `BolsoCalendario.js` + `PainelIda.js` desenham. Todo o JavaScript é testado pelo pytest a correr Node (ajudante novo `backend/tests/bolso_js.py`, que a Fase 3 reusa).

**Tecnologia:** FastAPI 0.110 + Motor + Pydantic 2 (Python 3.9.6 nos testes locais, 3.11 em produção), pytest contra um `mongod` real, React 19 (CRA/craco) + Tailwind + shadcn (`ui/sheet.jsx` do Radix), lucide-react, axios; Node 20 + `@babel/core` + `jsdom` nos testes de JavaScript; pymongo no script do dono.

## Restrições globais

- Fonte de verdade: `docs/superpowers/specs/2026-10-14-calendario-gestao-design.md`, secções «1. Os dados» (só as **Idas**), «2. O cálculo», «3. O servidor», «4. O ecrã» e «Testes» 1, 2, 5, 6, 7, 8, 9, 11, 12 e 14. Não mudar decisões do dono.
- A **Fase 1 está feita** (`docs/superpowers/plans/2026-10-15-calendario-fase1-horarios-escalas.md`): `locations.horario = {"abre": "HH:MM", "fecha": "HH:MM", "excecoes": [{"dia", "abre", "fecha"}], "fechada": [dias]}`, `locations.aberta_desde = "AAAA-MM-DD" | null`, `work_schedule_templates.dias = [{"dia", "location_id", "inicio", "fim"}]`; existem `backend/tests/calendario/{__init__,conftest,apoio}.py` (fixtures `mongod_porta` e `base`; `corre`, `ADMIN`) e `backend/arranque_calendario.py` (`HORARIOS`, `Paragem`, `_normal`, `_um`). Não se recriam.
- Trabalhar só em `/Users/matheus.moraes/Developer/RH-calendario` (ramo `matheus-calendario-gestao`). Nunca tocar em `~/Developer/RH` (outra sessão) nem em `~/Developer/RH-qr-aplicacoes` (é lá que o `main` está aberto).
- Dias da semana: `0 = segunda … 6 = domingo`, como `work_days`. Horários que passam da meia-noite: fora de âmbito.
- Idas: colecção `bolso_idas`, uma por pessoa, dia e loja: `{"id", "data": "AAAA-MM-DD", "location_id", "user_id", "inicio": "HH:MM", "fim": "HH:MM", "criado_por", "criado_em", "alterado_por", "alterado_em"}`. Índice único em `(data, user_id, location_id, inicio)` e índice em `data`.
- `user_id` é a conta da pessoa (`admin`/`gerente`/`colaborador`); o contabilista não pode ser escalado. Escala e ausências cruzam-se por `users.employee_id`.
- Uma ida só em lojas com horário e abertas nesse dia (senão **400**); as horas têm de **tocar** no horário (senão 400); horas fora do horário aceitam-se e **recortam-se** no cálculo e na contagem.
- A mesma pessoa não tem duas idas com horas sobrepostas no mesmo dia → **409** a dizer qual. Um colaborador com ausência aprovada nesse dia → **409**.
- **Ler** usa `admin_manager_required` (inclui o contabilista, que recebe `pode_marcar: false`); **escrever** exige `admin` ou `gerente` (403 aos outros).
- `POST` = `{datas: [≤31], location_id, user_ids: [1..2], inicio, fim}`, uma ida por data e por pessoa, **tudo ou nada sem transacções** (compensa apagando o que o próprio pedido gravou; a janela entre verificar e gravar fica aceite com um comentário `ponytail:`). Datas e pessoas repetidas no pedido → 400.
- Cálculo: só lojas com `horario`; `aberta_desde` esconde a loja antes de abrir; parte de `employees` (atribuições órfãs não contam); dias = `atribuição.work_days or modelo.work_days`; entradas de `dias` numa loja fechada/sem horário/por abrir ignoram-se; sai quem tem ausência **aprovada** (qualquer tipo); a ida de um gestor soma-se; a de um colaborador tira à escala dele as horas da ida e o que não estava na escala é «extra»; buracos = horário menos a união. Os buracos **não se guardam**.
- Contagem: uma ida vale **1** se as horas dentro do horário forem ≥ metade das horas de abertura, **0,5** se menos; numa loja sem horário vale 1; por pessoa e dia soma-se e corta-se em 1; conta as futuras; 12 meses + total, ordenada pelo total.
- Feriados só como aviso, nunca fecham lojas. `get_pt_holidays` continua a devolver o mesmo `set` e a cache dele (`_pt_holiday_cache`) não é tocada.
- Ecrã: o «hoje» é o do telemóvel em hora local (`getFullYear`/`getMonth`/`getDate`), nunca `toISOString()`. Grelha própria com dias de **44 px** (não o `ui/calendar.jsx`). Vista e filtro lembram-se no `localStorage` com try/catch; sem ele abre em Mês/Geral. Menu ☰ em `Sheet side="left"` com Faturação, Calendário e Terminar sessão (o «Usar Face ID» é da Fase 3), fecho de 44 px, `SheetContent` com a opção de não desenhar o fecho de 16 px (por omissão fica igual). Pedidos só por `lib/bolso.js`, com caminhos por extenso.
- Python dos testes: `~/Developer/RH/backend/.venv/bin/python` (3.9.6) — nada de `X | Y` em anotações nem `match`. Testes sempre com `PYTHONDONTWRITEBYTECODE=1`; as mutações fazem-se com `backend/tests/mutar.py` (Tarefa 1), que repõe o ficheiro e limpa `~/Library/Caches/com.apple.python`.
- Ler SEMPRE `passed` E `skipped`. `frontend/node_modules` começa como o atalho para `~/Developer/RH/frontend/node_modules` (chega para os testes) e passa a uma instalação própria na Tarefa 13 (o atalho não tem o `leaflet` e não compila); node e yarn em `~/.local/node/bin`.
- Um teste só vale depois de visto vermelho pela razão certa: cada tarefa tem a sua prova por mutação.
- **Uma tarefa de cada vez nesta árvore**, e nunca duas suites, nem uma suite e uma mutação, ao mesmo tempo (subagentes incluídos): o `mutar.py` estraga ficheiros partilhados da própria árvore e a outra corrida lê-os estragados (memória `workflows-paralelos-contaminam-a-arvore`: 8/20/0/25/4 falhas no MESMO commit).
- Nunca `git clean` nem `git stash -u`: apagam ou escondem ficheiros por gravar. Os três planos do calendário (`docs/superpowers/plans/2026-10-15-calendario-fase{1,2,3}-*.md`), que chegam por gravar (`??`), gravam-se no Passo 1 da Tarefa 1; daí em diante «`git status -s` vazio» quer mesmo dizer vazio.
- Produção: o assistente não lê nem escreve a base de produção; os dados mudam-se só pelo script, corrido pelo dono. Push, merge no `main` e deploy só depois de um «sim» do dono no chat. Deploy do site apenas — **sem build nova da casca** (a build 2 carrega o site).
- Valores de teste locais (palavras-passe, segredos) nunca se escrevem no chat nem em ficheiros versionados.
- Commits: `git add` de ficheiros nomeados; mensagem em português que diz o porquê, terminada com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

## Mapa de ficheiros

| Ficheiro | Criar/Modificar | Responsabilidade |
|---|---|---|
| `backend/calendario.py` | Criar | o cálculo inteiro, puro: horas e intervalos, horário do dia, feriados com nome, escala do dia, buracos, idas, contagem, regras das idas e a resposta do mês |
| `backend/tests/mutar.py` | Criar | ferramenta da prova por mutação (estraga, corre, exige vermelho, repõe sempre) |
| `backend/tests/test_mutar.py` | Criar | prende a ferramenta (repõe o ficheiro nos três desfechos) |
| `backend/tests/calendario/dados_semana_normal.py` | Criar | os dados da tabela do dono (lojas, 7 colaboradores com escalas, 3 gestores e o contabilista) e ajudantes `ida`, `ausencia`, `gravar` — uma fonte para os testes e o seed do ensaio |
| `backend/tests/calendario/test_intervalos_e_horario.py` | Criar | horas, intervalos, horário do dia (excepção de domingo, fechada, por abrir, sem horário) |
| `backend/tests/calendario/test_feriados.py` | Criar | nacionais com nome = `get_pt_holidays`, cache intacta, personalizados por âmbito, 30/02 sem erro |
| `backend/tests/calendario/test_a_semana_normal.py` | Criar | **o teste da semana normal** e os casos da escala |
| `backend/tests/calendario/test_outubro.py` | Criar | férias do Weber, Carol na Amadora, Joana em Benfica (dia, 2 horas, folga = extra, 12h30 recortado não é extra), ida de quem ficou de férias não tapa, ida de gestor, feriado |
| `backend/tests/calendario/test_contagem.py` | Criar | 0,5/1 pela metade do horário, recorte, corte em 1, meses e total |
| `backend/tests/calendario/test_regras_das_idas.py` | Criar | validações, choques, mensagens, ausências que impedem |
| `backend/tests/calendario/test_resposta_do_mes.py` | Criar | a forma do `GET` do mês (idas com nomes, ausências, lojas, pessoas) |
| `backend/server.py` | Modificar | `import calendario` (~44), `DuplicateKeyError` (~6); bloco «CALENDÁRIO DAS LOJAS» antes de `@api_router.post("/fin/cron/faturacao")` (~8657): `_BOLSO_CAMPOS_DA_LOJA`, `_bolso_criar_indices`, `GET /bolso/calendario`, `GET /bolso/calendario/contagem`, `BolsoIdasIn`, `BolsoIdaIn`, `bolso_quem_marca`, `_bolso_validar_idas`, `POST`/`PUT`/`DELETE /bolso/calendario/idas…`; um `try` novo no `startup_event` (~9749) |
| `backend/tests/calendario/test_rotas_de_leitura.py` | Criar | os dois `GET` e os índices contra o mongod |
| `backend/tests/calendario/test_rotas_de_escrita.py` | Criar | `POST`/`PUT`/`DELETE`, tudo ou nada, 400/409, e a porta (dependências e 403) |
| `backend/tests/bolso_js.py` | Criar | `correr_js(guiao, tmp_path, simulados=None, dom=False)`, `AXIOS_FABRICADO`, `SESSAO_SIMULADA` |
| `backend/tests/test_bolso_js.py` | Criar | prende o ajudante |
| `frontend/src/lib/calendario.js` | Criar | contas puras do ecrã (semanas, hoje local, títulos, pontos, lista, atalho, contagem, erros) |
| `backend/tests/calendario/test_lib_calendario.py` | Criar | corre `lib/calendario.js` em Node contra a resposta real do mês |
| `frontend/src/lib/bolso.js` | Modificar | `getCalendario`, `getContagem`, `criarIdas`, `mudarIda`, `apagarIda` (fim do ficheiro) |
| `backend/tests/fin/test_caminhos_do_bolso.py` | Modificar | prova que o guarda VÊ as cinco chamadas novas |
| `backend/tests/calendario/test_chamadas_do_calendario.py` | Criar | os parâmetros e corpos que as chamadas levam |
| `frontend/src/components/ui/sheet.jsx` | Modificar | `SheetContent` com `hideClose` (por omissão `false`) |
| `frontend/src/pages/bolso/partilhado.js` | Criar | `ler`, `guardar`, `useManifestoDoBolso`, `Calha`, `Segmento`, `DESTINOS`, `BotaoMenu`, `MenuLateral`, `GrelhaDoMes` |
| `frontend/src/pages/bolso/BolsoApp.js` | Modificar | usa o `partilhado.js`; ☰ no cabeçalho; «Terminar sessão» passa para o menu |
| `backend/tests/calendario/test_menu_do_bolso.py` | Criar | o menu montado (jsdom) na Faturação; `hideClose`; `ler`/`guardar` sem `localStorage` |
| `frontend/src/pages/bolso/PainelIda.js` | Criar | o painel de baixo: tapar, marcar, editar, apagar |
| `backend/tests/calendario/test_painel_da_ida.py` | Criar | o painel montado com o servidor fabricado |
| `frontend/src/pages/bolso/BolsoCalendario.js` | Criar | o ecrã: Mês/Lista/Contagem, Pessoal/Geral/Férias, dia com buracos e Tapar |
| `frontend/src/App.js` | Modificar | rota `/bolso/calendario` (~211) e o import (~82) |
| `backend/tests/calendario/test_ecra_do_calendario.py` | Criar | o ecrã montado com a resposta real do servidor; rotas do menu no `App.js` |
| `backend/carregar_idas_whatsapp.py` | Criar | o script do dono: idas de out–dez da mensagem, ensaio por omissão, `GRAVAR=1` |
| `backend/tests/calendario/test_carregar_idas_whatsapp.py` | Criar | o plano do script (puro) e a gravação contra o mongod |
| Só locais, nunca versionados | — | `frontend/node_modules` (instalação própria a partir da Tarefa 13), `$HOME/.cache/lisbonb-calendario-local/{backend-fase2.env,semear_fase2.py,contas-fase2.txt,build}`, a entrada `calendario-backend-fase2` em `/Users/matheus.moraes/Library/CloudStorage/OneDrive-Pessoal/Claude/.claude/launch.json` |

## Contexto que quem executa precisa de ter

- **O negócio.** Seis lojas de açaí (Alfragide, Algueirão, Amadora, Belém, Benfica — a abrir a 24/10 —, Oeiras) com escala fixa. Quando falta alguém, vão as gestoras **Carol** e **Débora** (contas `admin`, sem ficha de colaborador). Hoje organizam-se por WhatsApp; o calendário passa a mostrar os buracos sozinho e elas «tapam» com uma **ida** (pessoa, dia, loja, horas).
- **A semana normal** (tabela do dono, desenho): Alfragide 10–23 (Emily 14–23 menos qua/qui; Beatrice 10–19 menos seg/ter) · Algueirão 13–22 (Walisson menos qui/sex; Joana qui/sex) · Amadora 14–23 (Weber menos seg/ter; Joana seg/ter) · Belém 11h30–19, dom 11h30–20, **fecha à terça** (Rafaela) · Benfica 13–22, ninguém · Oeiras 13–22 (Emanuela menos ter/qua; Joana qua). Daqui sai a grelha: Oeiras sem ninguém à terça; Alfragide 10–14 seg/ter e 19–23 qua/qui; Benfica sempre.
- **O bolso** é a app dos gestores: `frontend/src/pages/bolso/BolsoApp.js` em `/bolso`, carregado pela casca iOS (Capacitor) que pinta até às bordas — daí os `safe-area-inset-top/bottom` (`frontend/src/index.css:9-14`). Cliente HTTP próprio: `frontend/src/lib/bolso.js` (axios com `baseURL` `/api/bolso`). O `tests/fin/test_caminhos_do_bolso.py` lê as chamadas `api.<verbo>('…')` desse ficheiro e confronta-as com as rotas reais — o POS já esteve morto em produção com a suite verde por um prefixo errado.
- **As rotas novas têm de ficar ANTES de `app.include_router(api_router)`** (`server.py` ~9698): o `include_router` copia as rotas no momento em que corre. O sítio escolhido (antes de `@api_router.post("/fin/cron/faturacao")`, logo a seguir ao `bolso_painel`) já está antes.
- **As rotas testam-se chamando as funções** com `current_user={"user_id": …, "role": …}`; as dependências verificam-se percorrendo `server.app.routes` → `rota.dependant.dependencies` (molde: `_dependencias` em `backend/tests/crm/test_lojas_criar.py:201`).
- **Não há jest a correr**: o JavaScript testa-se pelo pytest, em Node, com o código verdadeiro dos ficheiros transformado pelo babel (molde: `backend/tests/faturacao/test_a_faixa_do_modo_no_ecra.py:355-390`). Esta fase põe isso num ajudante (`tests/bolso_js.py`). Medido ao preparar este plano: o `Sheet` do Radix monta-se no jsdom se o `Event`/`CustomEvent`/`EventTarget` forem os do jsdom (os do Node dão «parameter 1 is not of type 'Event'»), e o `localStorage` do Node 20 é um getter que devolve `undefined` — o do jsdom tem de o substituir.
- **O deploy pode servir o bundle antigo** a dizer «concluído» (cache do Docker). Confirma-se sempre o `main.*.js` servido com um marcador só-ASCII do código novo; se vier o antigo, `docker compose build --no-cache frontend`.

---
### Tarefa 1: O cálculo, parte 1 — horas, intervalos, horário do dia e feriados com nome

**Ficheiros:**
- Criar: `backend/tests/mutar.py`, `backend/calendario.py`, `backend/tests/calendario/dados_semana_normal.py`
- Testes: `backend/tests/test_mutar.py`, `backend/tests/calendario/test_intervalos_e_horario.py`, `backend/tests/calendario/test_feriados.py` (criar)

**Interfaces:**
- Consome: `server.get_pt_holidays(ano) -> set` e `server._pt_holiday_cache` (só nos testes, para provar que ficam iguais).
- Produz:
  - `tests/mutar.py`: `main(argv: list) -> int` (0 = mutação apanhada, 1 = ficou verde, 2 = texto não aparece uma vez); uso `python tests/mutar.py <ficheiro> <original> <estragado> -- <comando…>`
  - `calendario.Intervalo = Tuple[int, int]` (minutos desde a meia-noite, semiaberto)
  - constantes `calendario.GESTORES = ("admin", "gerente")`, `ESCALAVEIS = ("admin", "gerente", "colaborador")`, `NOME_SEM_CONTA = "(conta removida)"`, `NOME_SEM_LOJA = "(loja removida)"`
  - `minutos(hhmm: str) -> int`, `hhmm(total: int) -> str`, `hora_curta(hhmm: str) -> str` («10h», «11h30»), `data_curta(iso: str) -> str` («21/10»), `primeiro_nome(nome: Optional[str]) -> str`
  - `unir(intervalos: List[Intervalo]) -> List[Intervalo]`, `subtrair(base, tirar) -> List[Intervalo]`, `recortar(intervalo, janela) -> Optional[Intervalo]`
  - `horario_do_dia(loja: Optional[dict], dia: date) -> Tuple[str, Optional[Intervalo]]` — estados `"sem_horario"`, `"por_abrir"`, `"fechada"`, `"aberta"`
  - `pascoa(ano) -> date`, `feriados_nacionais(ano) -> Dict[date, str]`, `feriados_do_dia(dia, personalizados) -> List[str]`, `feriados_da_loja(dia, personalizados, loja) -> List[str]`
  - `tests/calendario/dados_semana_normal.py`: constantes `FORDAIMON`, `LENHA`, `ALFRAGIDE`, `ALGUEIRAO`, `AMADORA`, `BELEM`, `BENFICA`, `OEIRAS`, `PIZZARIA`, `DEBORA`, `CAROL`, `GERENTE`, `CONTABILISTA`, `LOJAS`, `COLECOES`; funções `semana_normal() -> dict` (chaves `lojas`, `empregados`, `utilizadores`, `modelos`, `atribuicoes`, `ausencias`, `idas`, `feriados`), `emp(nome) -> str`, `user(nome) -> str`, `ida(data, loja, user_id, inicio, fim) -> dict`, `ausencia(nome, inicio, fim, status="aprovado", tipo="ferias") -> dict`, `async gravar(db, dados) -> None`

- [ ] **Passo 1: Preparar a árvore e medir a suite de partida**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git status -s -b            # esperado: "## matheus-calendario-gestao" e, quando muito, os planos do calendário por gravar (??)
for f in docs/superpowers/plans/2026-10-15-calendario-fase1-horarios-escalas.md \
         docs/superpowers/plans/2026-10-15-calendario-fase2-calendario.md \
         docs/superpowers/plans/2026-10-15-calendario-fase3-faceid.md; do
  git ls-files --error-unmatch "$f" >/dev/null 2>&1 || git add "$f"
done
git diff --cached --quiet || git commit -m "Planos do calendário das lojas (fases 1 a 3)

Os planos de execução ficam no ramo ao lado do desenho, para quem executa e quem revê
lerem a mesma coisa, e para a árvore começar limpa: daqui em diante um ficheiro por
gravar é trabalho desta fase, nunca um plano esquecido.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git status -s               # esperado: vazio. Se aparecer outra coisa, PARAR e perguntar de quem é (nunca git clean nem git stash -u)
ls backend/tests/calendario/conftest.py backend/tests/calendario/apoio.py backend/arranque_calendario.py   # da Fase 1
ln -sfn ~/Developer/RH/frontend/node_modules frontend/node_modules
export PATH="$HOME/.local/node/bin:$PATH"
cd backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest -q 2>&1 | tail -3
```

Anotar `N passed, M skipped` — é a partida. Até ao fim do plano o `passed` só sobe e o `skipped` não cresce. Se os três ficheiros da Fase 1 não existirem, PARAR: a Fase 1 não está feita.

- [ ] **Passo 2: O teste da ferramenta de mutação (falha: o módulo ainda não existe)**

`backend/tests/test_mutar.py`:

```python
"""A ferramenta da prova por mutação repõe SEMPRE o ficheiro — apanhe ou não apanhe."""
import sys

from tests import mutar

FALHA = [sys.executable, "-c", "import sys; sys.exit(1)"]
PASSA = [sys.executable, "-c", "import sys; sys.exit(0)"]


def test_mutacao_apanhada_devolve_0_e_repoe(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("A = 1\n", encoding="utf-8")
    assert mutar.main([str(f), "A = 1", "A = 2", "--"] + FALHA) == 0
    assert f.read_text(encoding="utf-8") == "A = 1\n"


def test_mutacao_nao_apanhada_devolve_1_e_repoe(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("A = 1\n", encoding="utf-8")
    assert mutar.main([str(f), "A = 1", "A = 2", "--"] + PASSA) == 1
    assert f.read_text(encoding="utf-8") == "A = 1\n"


def test_o_texto_tem_de_aparecer_exactamente_uma_vez(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("A = 1\nA = 1\n", encoding="utf-8")
    assert mutar.main([str(f), "A = 1", "A = 2", "--"] + FALHA) == 2
    assert mutar.main([str(f), "B = 1", "A = 2", "--"] + FALHA) == 2
    assert f.read_text(encoding="utf-8") == "A = 1\nA = 1\n"
```

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/test_mutar.py -q
```

Esperado: erro de colecção `ImportError: cannot import name 'mutar' from 'tests'`.

- [ ] **Passo 3: A ferramenta**

`backend/tests/mutar.py`:

```python
"""Prova por mutação: estraga UM pedaço de um ficheiro, corre o comando de teste, exige que
fique VERMELHO, e repõe SEMPRE o ficheiro (mesmo com Ctrl-C).

Regra da casa: um teste verde não vale nada até se o ver vermelho pela razão certa. Esta
ferramenta faz a parte mecânica; a razão certa lê-se na saída do pytest, que passa por aqui.

Uso (a partir de backend/):
    python tests/mutar.py <ficheiro> <texto-original> <texto-estragado> -- <comando de teste…>

Sai com 0 se o teste ficou vermelho (mutação apanhada), 1 se ficou verde, 2 se o texto a
estragar não aparece exactamente uma vez no ficheiro.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Neste Mac o bytecode vai para aqui; um .pyc do ficheiro estragado deixado lá envenena a
# corrida seguinte (já aconteceu). Limpa-se depois de repor.
_CACHE = Path.home() / "Library" / "Caches" / "com.apple.python"


def main(argv):
    if len(argv) < 5 or argv[3] != "--":
        print(__doc__)
        return 2
    caminho, original, estragado = argv[:3]
    comando = argv[4:]
    ficheiro = Path(caminho)
    antes = ficheiro.read_bytes()
    texto = antes.decode("utf-8")
    if texto.count(original) != 1:
        print("O texto a estragar aparece %d vezes em %s (tem de ser 1)." % (texto.count(original), caminho))
        return 2
    try:
        ficheiro.write_text(texto.replace(original, estragado), encoding="utf-8")
        resultado = subprocess.run(comando, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    finally:
        ficheiro.write_bytes(antes)
        shutil.rmtree(_CACHE, ignore_errors=True)
    if resultado.returncode == 0:
        print("\nMUTAÇÃO NÃO APANHADA: o teste ficou VERDE com o código estragado.")
        return 1
    print("\nMutação apanhada (o teste ficou vermelho). %s reposto." % caminho)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/test_mutar.py -q
```

Esperado: `3 passed`.

- [ ] **Passo 4: Os dados da semana normal**

`backend/tests/calendario/dados_semana_normal.py`:

```python
"""Os dados da semana normal, como o dono os descreveu (desenho, «A semana normal»).

Uma fonte só para os testes do cálculo, os das rotas (contra o mongod) e o seed do ensaio
local. Os documentos têm a forma das colecções de produção (`COLECOES` diz qual é qual):
lojas com `horario`/`aberta_desde` (Fase 1), uma escala por pessoa (`dias` com a loja e as
horas de cada dia; três delas SEM `dias`, como as escalas antigas) e uma atribuição desde
1/1/2026. As gestoras não têm ficha de colaborador (`employee_id: None`).

`semana_normal()` devolve dados NOVOS a cada chamada: os testes mexem-lhes à vontade.
"""
import copy

FORDAIMON, LENHA = "emp-fordaimon", "emp-lenha"
ALFRAGIDE, ALGUEIRAO, AMADORA = "loja-alfragide", "loja-algueirao", "loja-amadora"
BELEM, BENFICA, OEIRAS, PIZZARIA = "loja-belem", "loja-benfica", "loja-oeiras", "loja-pizzaria"
DEBORA, CAROL, GERENTE, CONTABILISTA = "u-debora", "u-carol", "u-gerente", "u-contabilista"


def _loja(id_, nome, abre, fecha, excecoes=(), fechada=(), desde=None):
    return {"id": id_, "name": nome, "company_id": FORDAIMON,
            "horario": {"abre": abre, "fecha": fecha, "excecoes": list(excecoes), "fechada": list(fechada)},
            "aberta_desde": desde}


LOJAS = [
    _loja(ALFRAGIDE, "Alfragide", "10:00", "23:00"),
    _loja(ALGUEIRAO, "Algueirão", "13:00", "22:00"),
    _loja(AMADORA, "Amadora", "14:00", "23:00"),
    _loja(BELEM, "Belém", "11:30", "19:00", excecoes=[{"dia": 6, "abre": "11:30", "fecha": "20:00"}], fechada=[1]),
    _loja(BENFICA, "Benfica", "13:00", "22:00", desde="2026-10-24"),
    _loja(OEIRAS, "Oeiras", "13:00", "22:00"),
    # Sem horário: não entra no calendário sem ninguém a esconder.
    {"id": PIZZARIA, "name": "Pizzaria", "company_id": LENHA, "horario": None, "aberta_desde": None},
]

# (nome, loja da ficha, dias de trabalho, `dias` por dia da semana -> (loja, início, fim), ou
# None para uma escala antiga). Loja None = a da ficha; horas None = o horário da loja.
_ESCALAS = [
    ("Emily", ALFRAGIDE, [0, 1, 4, 5, 6], {d: (None, "14:00", "23:00") for d in (0, 1, 4, 5, 6)}),
    ("Beatrice", ALFRAGIDE, [2, 3, 4, 5, 6], {d: (None, "10:00", "19:00") for d in (2, 3, 4, 5, 6)}),
    ("Walisson", ALGUEIRAO, [0, 1, 2, 5, 6], None),
    ("Joana", ALGUEIRAO, [0, 1, 2, 3, 4], {0: (AMADORA, None, None), 1: (AMADORA, None, None),
                                           2: (OEIRAS, None, None), 3: (ALGUEIRAO, None, None),
                                           4: (ALGUEIRAO, None, None)}),
    ("Weber", AMADORA, [2, 3, 4, 5, 6], None),
    ("Rafaela", BELEM, [0, 2, 3, 4, 5, 6], None),
    ("Emanuela", OEIRAS, [0, 3, 4, 5, 6], {d: (None, None, None) for d in (0, 3, 4, 5, 6)}),
]

COLECOES = {
    "lojas": "locations", "empregados": "employees", "utilizadores": "users",
    "modelos": "work_schedule_templates", "atribuicoes": "work_schedule_assignments",
    "ausencias": "leave_requests", "idas": "bolso_idas", "feriados": "holidays",
}


def emp(nome):
    return "e-" + nome.lower()


def user(nome):
    return "u-" + nome.lower()


def semana_normal():
    empregados, utilizadores, modelos, atribuicoes = [], [], [], []
    for nome, loja, dias_de_trabalho, dias in _ESCALAS:
        empregados.append({"id": emp(nome), "name": nome, "location_id": loja, "company_id": FORDAIMON})
        utilizadores.append({"id": user(nome), "name": nome, "role": "colaborador", "employee_id": emp(nome)})
        modelo = {"id": "m-" + nome.lower(), "name": "Escala " + nome,
                  "work_days": list(dias_de_trabalho), "start_time": None}
        if dias is not None:
            modelo["dias"] = [{"dia": d, "location_id": l, "inicio": i, "fim": f}
                              for d, (l, i, f) in sorted(dias.items())]
        modelos.append(modelo)
        atribuicoes.append({"id": "a-" + nome.lower(), "employee_id": emp(nome), "template_id": modelo["id"],
                            "work_days": list(dias_de_trabalho), "start_date": "2026-01-01", "end_date": None})
    utilizadores += [
        {"id": DEBORA, "name": "Débora Ferreira", "role": "admin", "employee_id": None},
        {"id": CAROL, "name": "Carol Santos", "role": "admin", "employee_id": None},
        {"id": GERENTE, "name": "Guilherme Gestor", "role": "gerente", "employee_id": None},
        {"id": CONTABILISTA, "name": "Rita Contas", "role": "contabilista", "employee_id": None},
    ]
    return {"lojas": copy.deepcopy(LOJAS), "empregados": empregados, "utilizadores": utilizadores,
            "modelos": modelos, "atribuicoes": atribuicoes, "ausencias": [], "idas": [], "feriados": []}


def ida(data, loja, user_id, inicio, fim):
    return {"id": "i-%s-%s-%s-%s" % (data, loja, user_id, inicio.replace(":", "")), "data": data,
            "location_id": loja, "user_id": user_id, "inicio": inicio, "fim": fim}


def ausencia(nome, inicio, fim, status="aprovado", tipo="ferias"):
    return {"id": "f-%s-%s" % (nome.lower(), inicio), "employee_id": emp(nome), "leave_type": tipo,
            "start_date": inicio, "end_date": fim, "status": status}


async def gravar(db, dados):
    """Grava `dados` numa base Motor (cópias: o insert acrescenta o `_id` aos dicionários)."""
    for chave, colecao in COLECOES.items():
        if dados[chave]:
            await db[colecao].insert_many([dict(d) for d in dados[chave]])
```

(A Emanuela leva `dias` sem loja nem horas de propósito: é o caminho «loja da ficha + horário da loja» com `dias`, ao lado das três escalas antigas.)

- [ ] **Passo 5: Escrever os testes que falham**

`backend/tests/calendario/test_intervalos_e_horario.py`:

```python
"""Horas, intervalos e o horário de cada loja num dia (desenho, secção 2, passo 1)."""
from datetime import date

import calendario

from . import dados_semana_normal as sn


def _loja(nome):
    return next(l for l in sn.semana_normal()["lojas"] if l["name"] == nome)


def test_horas_em_minutos_e_de_volta():
    assert calendario.minutos("11:30") == 690
    assert calendario.hhmm(690) == "11:30"
    assert calendario.hhmm(calendario.minutos("09:05")) == "09:05"


def test_horas_e_datas_como_se_escrevem_numa_mensagem():
    assert calendario.hora_curta("10:00") == "10h"
    assert calendario.hora_curta("11:30") == "11h30"
    assert calendario.data_curta("2026-10-21") == "21/10"
    assert calendario.primeiro_nome("Débora Ferreira") == "Débora"
    assert calendario.primeiro_nome("  ") == ""
    assert calendario.primeiro_nome(None) == ""


def test_unir_junta_sobrepostos_e_encostados_e_deita_fora_os_vazios():
    assert calendario.unir([(1000, 1100), (600, 840), (840, 900), (1050, 1200), (5, 5)]) == [(600, 900), (1000, 1200)]


def test_subtrair_da_os_buracos():
    alfragide = [(600, 1380)]
    assert calendario.subtrair(alfragide, [(840, 1380)]) == [(600, 840)]          # só a Emily
    assert calendario.subtrair(alfragide, [(600, 1140), (840, 1380)]) == []       # as duas
    assert calendario.subtrair([(780, 1320)], [(900, 1000)]) == [(780, 900), (1000, 1320)]
    assert calendario.subtrair([(780, 1320)], []) == [(780, 1320)]
    assert calendario.subtrair([(780, 1320)], [(0, 1439)]) == []


def test_recortar_ao_horario_e_encostar_nao_e_tocar():
    assert calendario.recortar((750, 1320), (780, 1320)) == (780, 1320)
    assert calendario.recortar((720, 780), (780, 1320)) is None
    assert calendario.recortar((480, 720), (780, 1320)) is None


def test_o_horario_geral():
    assert calendario.horario_do_dia(_loja("Oeiras"), date(2026, 10, 27)) == ("aberta", (780, 1320))
    assert calendario.horario_do_dia(_loja("Belém"), date(2026, 10, 31)) == ("aberta", (690, 1140))  # sábado


def test_a_excecao_de_domingo_de_belem():
    assert calendario.horario_do_dia(_loja("Belém"), date(2026, 11, 1)) == ("aberta", (690, 1200))


def test_belem_fecha_a_terca():
    assert calendario.horario_do_dia(_loja("Belém"), date(2026, 10, 27)) == ("fechada", None)


def test_benfica_antes_e_depois_de_abrir():
    assert calendario.horario_do_dia(_loja("Benfica"), date(2026, 10, 23)) == ("por_abrir", None)
    assert calendario.horario_do_dia(_loja("Benfica"), date(2026, 10, 24)) == ("aberta", (780, 1320))


def test_sem_horario_nao_entra_no_calendario():
    assert calendario.horario_do_dia(_loja("Pizzaria"), date(2026, 10, 27)) == ("sem_horario", None)
    assert calendario.horario_do_dia(None, date(2026, 10, 27)) == ("sem_horario", None)


def test_feriado_nao_fecha_a_loja():
    # 05/10 é feriado nacional e há lojas abertas (desenho, medido 5).
    assert calendario.horario_do_dia(_loja("Alfragide"), date(2026, 10, 5)) == ("aberta", (600, 1380))
```

`backend/tests/calendario/test_feriados.py`:

```python
"""Feriados com nome (desenho, secção 2, «Feriados do dia», e Testes 5).

Os nacionais vêm de um dicionário construído à parte; o `server.get_pt_holidays`, que o
saldo de férias usa, continua a dar o mesmo `set` e a cache dele não é tocada.
"""
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")
os.environ.setdefault("JWT_SECRET", "segredo-de-teste")
os.environ.setdefault("POS_JWT_SECRET", "segredo-de-teste-pos")

from datetime import date, timedelta  # noqa: E402

import calendario  # noqa: E402
import server  # noqa: E402

from . import dados_semana_normal as sn  # noqa: E402

PERSONALIZADOS = [
    {"name": "Santo António", "month": 6, "day": 13, "company_id": None, "location_id": None},
    {"name": "Dia da Fordaimon", "month": 10, "day": 7, "company_id": sn.FORDAIMON, "location_id": None},
    {"name": "Feriado de Oeiras", "month": 6, "day": 7, "company_id": None, "location_id": sn.OEIRAS},
    {"name": "Impossível", "month": 2, "day": 30, "company_id": None, "location_id": None},
    {"name": "Lixo", "month": "x", "day": None},
]


def _loja(nome):
    return next(l for l in sn.semana_normal()["lojas"] if l["name"] == nome)


def test_os_nacionais_tem_nome():
    nacionais = calendario.feriados_nacionais(2026)
    assert nacionais[date(2026, 10, 5)] == "Implantação da República"
    assert nacionais[date(2026, 11, 1)] == "Todos os Santos"
    assert nacionais[date(2026, 4, 3)] == "Sexta-feira Santa"   # Páscoa de 2026: 5 de abril
    assert nacionais[date(2026, 6, 4)] == "Corpo de Deus"


def test_os_nacionais_sao_as_mesmas_datas_do_saldo_de_ferias():
    for ano in range(2024, 2032):
        assert set(calendario.feriados_nacionais(ano)) == server.get_pt_holidays(ano), ano


def test_os_feriados_com_nome_nao_mexem_na_cache_do_saldo_de_ferias():
    server.get_pt_holidays(2026)
    antes = dict(server._pt_holiday_cache)
    for ano in range(2024, 2032):
        calendario.feriados_nacionais(ano)
    assert server._pt_holiday_cache == antes
    assert all(server._pt_holiday_cache[ano] is antes[ano] for ano in antes)


def test_do_dia_sao_os_nacionais_e_os_do_grupo():
    assert calendario.feriados_do_dia(date(2026, 10, 5), PERSONALIZADOS) == ["Implantação da República"]
    assert calendario.feriados_do_dia(date(2026, 6, 13), PERSONALIZADOS) == ["Santo António"]
    assert calendario.feriados_do_dia(date(2026, 10, 7), PERSONALIZADOS) == []   # é da empresa, não do grupo


def test_da_loja_sao_os_da_empresa_dela_e_os_dela():
    assert calendario.feriados_da_loja(date(2026, 10, 7), PERSONALIZADOS, _loja("Alfragide")) == ["Dia da Fordaimon"]
    assert calendario.feriados_da_loja(date(2026, 10, 7), PERSONALIZADOS, _loja("Pizzaria")) == []
    assert calendario.feriados_da_loja(date(2026, 6, 7), PERSONALIZADOS, _loja("Oeiras")) == ["Feriado de Oeiras"]
    assert calendario.feriados_da_loja(date(2026, 6, 7), PERSONALIZADOS, _loja("Alfragide")) == []
    assert calendario.feriados_da_loja(date(2026, 6, 13), PERSONALIZADOS, _loja("Oeiras")) == []  # o do grupo vai no dia


def test_um_dia_impossivel_ou_lixo_nao_rebenta():
    dia = date(2028, 2, 1)
    while dia.month in (2, 3):
        assert "Impossível" not in calendario.feriados_do_dia(dia, PERSONALIZADOS)
        dia += timedelta(days=1)
```

- [ ] **Passo 6: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_intervalos_e_horario.py tests/calendario/test_feriados.py -q
```

Esperado: erros de colecção `ModuleNotFoundError: No module named 'calendario'`.

- [ ] **Passo 7: Implementação**

`backend/calendario.py`:

```python
"""**Calendário das lojas** — onde falta gente, calculado (nunca guardado).

O dono quer que o calendário faça sozinho a conta que a Carol e a Débora faziam de cabeça
(desenho `docs/superpowers/specs/2026-10-14-calendario-gestao-design.md`, secção 2): com o
horário de cada loja, a escala de cada pessoa, as ausências aprovadas no RH e as idas
marcadas, diz onde falta gente.

**Este módulo não fala com o Mongo nem com o FastAPI, e é de propósito** (o mesmo princípio
do `bolso.py`): as rotas vivem no `server.py` e trazem para aqui listas de dicionários; aqui
fica só a matemática, que assim se testa com listas em memória.

Horas em minutos desde a meia-noite; intervalos `(inicio, fim)` semiabertos. Dias da semana
0 = segunda … 6 = domingo, como o `work_days` do RH. Horários que passam da meia-noite estão
fora do âmbito (nenhuma loja passa hoje).
"""
import re
from calendar import monthrange
from datetime import date, timedelta
from typing import Dict, List, Optional, Set, Tuple

Intervalo = Tuple[int, int]

GESTORES = ("admin", "gerente")
ESCALAVEIS = ("admin", "gerente", "colaborador")
NOME_SEM_CONTA = "(conta removida)"
NOME_SEM_LOJA = "(loja removida)"
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def minutos(hhmm_: str) -> int:
    horas, mins = hhmm_.split(":")
    return int(horas) * 60 + int(mins)


def hhmm(total: int) -> str:
    return "%02d:%02d" % (total // 60, total % 60)


def hora_curta(hhmm_: str) -> str:
    """«10:00» -> «10h», «11:30» -> «11h30» — como se escreve numa mensagem."""
    horas, mins = hhmm_.split(":")
    return "%dh" % int(horas) if mins == "00" else "%dh%s" % (int(horas), mins)


def data_curta(iso: str) -> str:
    return "%s/%s" % (iso[8:10], iso[5:7])


def primeiro_nome(nome: Optional[str]) -> str:
    partes = (nome or "").split()
    return partes[0] if partes else ""


def unir(intervalos: List[Intervalo]) -> List[Intervalo]:
    """A união, ordenada; intervalos encostados juntam-se e os vazios desaparecem."""
    fora = []  # type: List[Intervalo]
    for inicio, fim in sorted(i for i in intervalos if i[0] < i[1]):
        if fora and inicio <= fora[-1][1]:
            fora[-1] = (fora[-1][0], max(fora[-1][1], fim))
        else:
            fora.append((inicio, fim))
    return fora


def subtrair(base: List[Intervalo], tirar: List[Intervalo]) -> List[Intervalo]:
    """`base` menos `tirar`, em intervalos. É daqui que saem os buracos."""
    resto = unir(base)
    for t_inicio, t_fim in unir(tirar):
        novo = []
        for inicio, fim in resto:
            if t_fim <= inicio or t_inicio >= fim:
                novo.append((inicio, fim))
                continue
            if inicio < t_inicio:
                novo.append((inicio, t_inicio))
            if t_fim < fim:
                novo.append((t_fim, fim))
        resto = novo
    return resto


def recortar(intervalo: Intervalo, janela: Intervalo) -> Optional[Intervalo]:
    """A parte de `intervalo` dentro de `janela`; `None` se não se tocarem (encostar não é tocar)."""
    inicio, fim = max(intervalo[0], janela[0]), min(intervalo[1], janela[1])
    return (inicio, fim) if inicio < fim else None


def horario_do_dia(loja: Optional[Dict], dia: date) -> Tuple[str, Optional[Intervalo]]:
    """O estado da loja nesse dia e, se abre, as horas.

    Estados: `sem_horario` (a loja não entra no calendário: Pizzaria, escritórios, loja
    apagada), `por_abrir` (antes de `aberta_desde`), `fechada` (o dia da semana está em
    `fechada`) e `aberta` (com a excepção desse dia da semana, ou o horário geral).
    Feriado NÃO fecha a loja — decisão do dono.
    """
    horario = (loja or {}).get("horario")
    if not horario:
        return "sem_horario", None
    desde = loja.get("aberta_desde")
    if desde and dia.isoformat() < desde:
        return "por_abrir", None
    semana = dia.weekday()
    if semana in (horario.get("fechada") or []):
        return "fechada", None
    excecao = next((e for e in horario.get("excecoes") or [] if e.get("dia") == semana), None)
    fonte = excecao or horario
    return "aberta", (minutos(fonte["abre"]), minutos(fonte["fecha"]))


def pascoa(ano: int) -> date:
    """Domingo de Páscoa (algoritmo anónimo gregoriano — o mesmo do `server._easter_sunday`)."""
    a = ano % 19
    b = ano // 100
    c = ano % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(ano, mes, dia)


def feriados_nacionais(ano: int) -> Dict[date, str]:
    """Os feriados nacionais COM NOME.

    O `server.get_pt_holidays` devolve as mesmas datas num `set` (os nomes estão lá em
    comentários) e guarda-as numa cache que o saldo de férias usa; este dicionário é
    construído à parte para não lhe tocar. Um teste confere que as datas são as mesmas.
    """
    p = pascoa(ano)
    return {
        date(ano, 1, 1): "Ano Novo",
        p - timedelta(days=2): "Sexta-feira Santa",
        p: "Páscoa",
        date(ano, 4, 25): "Dia da Liberdade",
        date(ano, 5, 1): "Dia do Trabalhador",
        p + timedelta(days=60): "Corpo de Deus",
        date(ano, 6, 10): "Dia de Portugal",
        date(ano, 8, 15): "Assunção de Nossa Senhora",
        date(ano, 10, 5): "Implantação da República",
        date(ano, 11, 1): "Todos os Santos",
        date(ano, 12, 1): "Restauração da Independência",
        date(ano, 12, 8): "Imaculada Conceição",
        date(ano, 12, 25): "Natal",
    }


def _cai_no_dia(feriado: Dict, dia: date) -> bool:
    # Compara números e nunca constrói a data: um personalizado de 30/02 (o formulário
    # aceita-o) simplesmente nunca cai em dia nenhum, em vez de dar um 500.
    try:
        return (int(feriado["month"]), int(feriado["day"])) == (dia.month, dia.day)
    except (KeyError, TypeError, ValueError):
        return False


def feriados_do_dia(dia: date, personalizados: List[Dict]) -> List[str]:
    """Os do dia inteiro: o nacional (se houver) e os personalizados de âmbito grupo."""
    nomes = []
    nacional = feriados_nacionais(dia.year).get(dia)
    if nacional:
        nomes.append(nacional)
    nomes += [h.get("name") or "Feriado" for h in personalizados
              if not h.get("company_id") and not h.get("location_id") and _cai_no_dia(h, dia)]
    return nomes


def feriados_da_loja(dia: date, personalizados: List[Dict], loja: Dict) -> List[str]:
    """Os personalizados da empresa da loja ou da própria loja (a regra «OU» do saldo de férias)."""
    return [h.get("name") or "Feriado" for h in personalizados
            if _cai_no_dia(h, dia) and (
                (h.get("company_id") and h.get("company_id") == loja.get("company_id"))
                or (h.get("location_id") and h.get("location_id") == loja.get("id")))]
```

(`monthrange` e `Set` só passam a ser usados na Tarefa 2; ficam já no cabeçalho.)

- [ ] **Passo 8: Correr e ver passar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_intervalos_e_horario.py tests/calendario/test_feriados.py tests/test_mutar.py -q
```

Esperado: `20 passed`.

- [ ] **Passo 9: Prova por mutação (três regras, cada uma vista vermelha)**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PY=~/Developer/RH/backend/.venv/bin/python
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py calendario.py 'fonte = excecao or horario' 'fonte = horario' -- $PY -m pytest tests/calendario/test_intervalos_e_horario.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py calendario.py 'p + timedelta(days=60)' 'p + timedelta(days=61)' -- $PY -m pytest tests/calendario/test_feriados.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py calendario.py 'except (KeyError, TypeError, ValueError):' 'except (KeyError, TypeError):' -- $PY -m pytest tests/calendario/test_feriados.py -q
```

Esperado, por esta ordem: `FAILED …test_a_excecao_de_domingo_de_belem` (19:00 em vez de 20:00); `FAILED …test_os_nacionais_tem_nome` e `…test_os_nacionais_sao_as_mesmas_datas_do_saldo_de_ferias`; `FAILED` nos três testes que percorrem os personalizados (`…test_do_dia…`, `…test_da_loja…`, `…test_um_dia_impossivel_ou_lixo_nao_rebenta`) com `ValueError: invalid literal for int() with base 10: 'x'`. As três terminam em «Mutação apanhada». `git diff --stat` não mostra `calendario.py` alterado (ainda não está no git; `git status -s` mostra-o como novo).

- [ ] **Passo 10: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add backend/calendario.py backend/tests/mutar.py backend/tests/test_mutar.py backend/tests/calendario/dados_semana_normal.py backend/tests/calendario/test_intervalos_e_horario.py backend/tests/calendario/test_feriados.py
git commit -m "Calendário: horário de cada loja num dia e feriados com nome, num módulo puro

O calendário vai calcular os buracos das lojas a cada pedido; a conta vive em
backend/calendario.py, sem Mongo, para se provar com listas em memória. Os feriados
nacionais ganham nome num dicionário à parte, para o saldo de férias continuar a ler o
mesmo set e a mesma cache. Junta a ferramenta da prova por mutação, que repõe sempre o
ficheiro estragado.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Tarefa 2: O cálculo, parte 2 — a escala do dia, os buracos e o teste da semana normal

**Ficheiros:**
- Modificar: `backend/calendario.py` (acrescentar no fim)
- Testes: `backend/tests/calendario/test_a_semana_normal.py` (criar)

**Interfaces:**
- Consome: `horario_do_dia`, `recortar`, `subtrair`, `minutos`, `hhmm`, `feriados_do_dia`, `feriados_da_loja` (Tarefa 1); `dados_semana_normal` (Tarefa 1); `arranque_calendario.HORARIOS` (Fase 1, só no teste).
- Produz:
  - `calendario.atribuicao_do_dia(atribuicoes: List[dict], dia: date) -> Optional[dict]`
  - `calendario.ausentes(dia: date, ausencias: List[dict]) -> Set[str]` (`employee_id` com ausência APROVADA)
  - `calendario.dia_do_calendario(dia: date, dados: dict, p: Optional[dict] = None) -> dict` → `{"data", "feriados": [str], "lojas": [{"location_id", "nome", "estado", "abre", "fecha", "feriados", "pessoas": [{"user_id", "nome", "inicio", "fim", "origem", "extra", "ida_id"}], "buracos": [{"inicio", "fim"}]}]}` (lojas `aberta`/`fechada`, por nome; sem as `sem_horario` nem as `por_abrir`)
  - `calendario.calendario_do_mes(ano: int, mes: int, dados: dict) -> List[dict]` (um `dia_do_calendario` por dia)
  - internos: `_preparar(dados) -> dict`, `_escala(dia, p) -> Dict[str, Tuple[str, Intervalo]]`, `_pessoa(...)`, `_loja_do_dia(...)`
  - `dados` tem sempre as chaves de `dados_semana_normal.semana_normal()`: `lojas`, `empregados`, `utilizadores`, `modelos`, `atribuicoes`, `ausencias`, `idas`, `feriados`

- [ ] **Passo 1: Escrever os testes que falham**

`backend/tests/calendario/test_a_semana_normal.py`:

```python
"""A semana normal — o teste que dá nome ao trabalho (desenho, «Testes» 1) — e a escala.

Com os dados da tabela do dono, numa semana DEPOIS da abertura de Benfica (26/10–01/11), o
cálculo dá EXACTAMENTE a grelha dos buracos: Oeiras sem ninguém à terça; Alfragide 10–14 à
segunda e terça e 19–23 à quarta e quinta; Benfica todos os dias; Belém fechada à terça; o
resto coberto. Os outros testes prendem as regras da escala (desenho, secção 2, passo 2).
"""
import calendario

from . import dados_semana_normal as sn


def _mes(dados, ano=2026, mes=10):
    return calendario.calendario_do_mes(ano, mes, dados)


def _grelha(dias, de, ate):
    """{data: {loja: estado ou ["HH:MM-HH:MM", …]}} entre `de` e `ate`."""
    return {
        d["data"]: {l["nome"]: (l["estado"] if l["estado"] != "aberta"
                                else ["%s-%s" % (b["inicio"], b["fim"]) for b in l["buracos"]])
                    for l in d["lojas"]}
        for d in dias if de <= d["data"] <= ate
    }


def _loja(dias, data, nome):
    dia = next(d for d in dias if d["data"] == data)
    return next(l for l in dia["lojas"] if l["nome"] == nome)


def _quem(dias, data, nome):
    return [(p["nome"], p["inicio"], p["fim"], p["origem"]) for p in _loja(dias, data, nome)["pessoas"]]


def _semana(mudancas=None):
    linha = {"Alfragide": [], "Algueirão": [], "Amadora": [], "Belém": [], "Benfica": ["13:00-22:00"], "Oeiras": []}
    linha.update(mudancas or {})
    return linha


def test_a_semana_normal_da_exactamente_a_grelha_dos_buracos():
    dados = sn.semana_normal()
    dias = _mes(dados, 2026, 10) + _mes(dados, 2026, 11)
    assert _grelha(dias, "2026-10-26", "2026-11-01") == {
        "2026-10-26": _semana({"Alfragide": ["10:00-14:00"]}),
        "2026-10-27": _semana({"Alfragide": ["10:00-14:00"], "Belém": "fechada", "Oeiras": ["13:00-22:00"]}),
        "2026-10-28": _semana({"Alfragide": ["19:00-23:00"]}),
        "2026-10-29": _semana({"Alfragide": ["19:00-23:00"]}),
        "2026-10-30": _semana(),
        "2026-10-31": _semana(),
        "2026-11-01": _semana(),
    }


def test_os_horarios_destes_testes_sao_os_que_o_arranque_da_fase_1_carrega():
    import arranque_calendario
    assert {l["name"]: l["horario"] for l in sn.LOJAS if l["horario"]} == arranque_calendario.HORARIOS


def test_antes_de_abrir_benfica_nao_aparece_e_a_pizzaria_nunca():
    dia = _grelha(_mes(sn.semana_normal()), "2026-10-23", "2026-10-23")["2026-10-23"]
    assert sorted(dia) == ["Alfragide", "Algueirão", "Amadora", "Belém", "Oeiras"]


def test_quem_esta_em_cada_loja_e_com_que_horas():
    dias = _mes(sn.semana_normal())
    assert _quem(dias, "2026-10-26", "Alfragide") == [("Emily", "14:00", "23:00", "escala")]      # horas da escala
    assert _quem(dias, "2026-10-26", "Amadora") == [("Joana", "14:00", "23:00", "escala")]       # loja do dia
    assert _quem(dias, "2026-10-26", "Algueirão") == [("Walisson", "13:00", "22:00", "escala")]  # escala antiga
    assert _quem(dias, "2026-10-26", "Oeiras") == [("Emanuela", "13:00", "22:00", "escala")]     # `dias` sem loja/horas
    assert _quem(dias, "2026-10-28", "Alfragide") == [("Beatrice", "10:00", "19:00", "escala")]
    assert _loja(dias, "2026-10-26", "Alfragide")["pessoas"][0]["user_id"] == sn.user("Emily")


def test_duas_atribuicoes_no_mes():
    dados = sn.semana_normal()
    weber = next(a for a in dados["atribuicoes"] if a["employee_id"] == sn.emp("Weber"))
    weber["end_date"] = "2026-10-15"
    dados["modelos"].append({"id": "m-weber-2", "name": "Escala Weber (nova)", "work_days": [0, 1, 2, 3, 4]})
    dados["atribuicoes"].append({"id": "a-weber-2", "employee_id": sn.emp("Weber"), "template_id": "m-weber-2",
                                 "work_days": [0, 1, 2, 3, 4], "start_date": "2026-10-16", "end_date": None})
    grelha = _grelha(_mes(dados), "2026-10-10", "2026-10-19")
    assert grelha["2026-10-10"]["Amadora"] == []                 # sábado, ainda a primeira
    assert grelha["2026-10-17"]["Amadora"] == ["14:00-23:00"]    # sábado, já a segunda (folga)
    assert grelha["2026-10-19"]["Amadora"] == []                 # segunda: Weber e Joana


def test_uma_atribuicao_orfa_nao_aparece():
    dados = sn.semana_normal()
    dados["modelos"].append({"id": "m-fantasma", "work_days": [0, 1, 2, 3, 4, 5, 6],
                             "dias": [{"dia": d, "location_id": sn.BENFICA, "inicio": None, "fim": None}
                                      for d in range(7)]})
    dados["atribuicoes"].append({"id": "a-fantasma", "employee_id": "e-apagada", "template_id": "m-fantasma",
                                 "work_days": [0, 1, 2, 3, 4, 5, 6], "start_date": "2026-01-01", "end_date": None})
    assert _grelha(_mes(dados), "2026-10-26", "2026-10-26")["2026-10-26"]["Benfica"] == ["13:00-22:00"]


def test_so_a_ausencia_aprovada_tira_alguem():
    dados = sn.semana_normal()
    dados["ausencias"].append(sn.ausencia("Emanuela", "2026-10-26", "2026-10-30", status="pendente"))
    assert _grelha(_mes(dados), "2026-10-26", "2026-10-26")["2026-10-26"]["Oeiras"] == []
    dados["ausencias"].append(sn.ausencia("Emanuela", "2026-10-26", "2026-10-26", tipo="doenca"))
    assert _grelha(_mes(dados), "2026-10-26", "2026-10-26")["2026-10-26"]["Oeiras"] == ["13:00-22:00"]


def test_uma_entrada_numa_loja_fechada_ignora_se():
    dados = sn.semana_normal()
    joana = next(m for m in dados["modelos"] if m["id"] == "m-joana")
    next(d for d in joana["dias"] if d["dia"] == 1)["location_id"] = sn.BELEM   # terça em Belém, que fecha à terça
    dias = _mes(dados)
    assert _grelha(dias, "2026-10-27", "2026-10-27")["2026-10-27"]["Amadora"] == ["14:00-23:00"]
    assert _loja(dias, "2026-10-27", "Belém") == {
        "location_id": sn.BELEM, "nome": "Belém", "estado": "fechada", "abre": None, "fecha": None,
        "feriados": [], "pessoas": [], "buracos": []}


def test_as_horas_da_escala_recortam_se_ao_horario_da_loja():
    dados = sn.semana_normal()
    for d in next(m for m in dados["modelos"] if m["id"] == "m-emily")["dias"]:
        d["inicio"], d["fim"] = "09:00", "23:30"
    dias = _mes(dados)
    assert _quem(dias, "2026-10-26", "Alfragide") == [("Emily", "10:00", "23:00", "escala")]
    assert _loja(dias, "2026-10-26", "Alfragide")["buracos"] == []


def test_sem_copia_dos_dias_na_atribuicao_vale_a_do_modelo():
    dados = sn.semana_normal()
    next(a for a in dados["atribuicoes"] if a["employee_id"] == sn.emp("Rafaela"))["work_days"] = []
    assert _grelha(_mes(dados), "2026-10-26", "2026-10-26")["2026-10-26"]["Belém"] == []
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_a_semana_normal.py -q
```

Esperado: `9 failed, 1 passed` — os nove com `AttributeError: module 'calendario' has no attribute 'calendario_do_mes'`; passa só o dos horários do arranque (não usa o cálculo). Se esse também falhar, os horários da tabela e os do `arranque_calendario.HORARIOS` divergem: PARAR e ver qual está errado contra o desenho.

- [ ] **Passo 3: Implementação**

Acrescentar no fim de `backend/calendario.py`:

```python


# --- A escala: quem está em cada loja, num dia, pela escala fixa do RH ----------------------


def atribuicao_do_dia(atribuicoes: List[Dict], dia: date) -> Optional[Dict]:
    """A regra do `find_schedule_assignment` do `server.py`: a primeira, por data de início,
    que cobre o dia (`end_date` vazio = sem fim)."""
    iso = dia.isoformat()
    for a in sorted(atribuicoes, key=lambda a: a.get("start_date") or ""):
        inicio = (a.get("start_date") or "")[:10]
        fim = (a.get("end_date") or "")[:10]
        if inicio and inicio <= iso and (not fim or iso <= fim):
            return a
    return None


def _preparar(dados: Dict) -> Dict:
    """Os índices que cada dia consulta, construídos uma vez por pedido."""
    atribuicoes = {}  # type: Dict[str, List[Dict]]
    for a in dados.get("atribuicoes", []):
        atribuicoes.setdefault(a.get("employee_id"), []).append(a)
    utilizadores = {u["id"]: u for u in dados.get("utilizadores", [])}
    lojas = {l["id"]: l for l in dados.get("lojas", [])}
    empregados = dados.get("empregados", [])
    return {
        "lojas": lojas,
        "lojas_ordenadas": sorted(lojas.values(), key=lambda l: (l.get("name") or "").lower()),
        "empregados": empregados,
        "nome_do_emp": {e["id"]: e.get("name") for e in empregados},
        "atribuicoes": atribuicoes,
        "modelos": {m["id"]: m for m in dados.get("modelos", [])},
        "utilizadores": utilizadores,
        "user_do_emp": {u["employee_id"]: u["id"] for u in utilizadores.values() if u.get("employee_id")},
    }


def _escala(dia: date, p: Dict) -> Dict[str, Tuple[str, Intervalo]]:
    """`{employee_id: (location_id, horas)}` de quem trabalha neste dia pela escala.

    Parte de `employees` e não das atribuições: quem sai é apagado e as atribuições dele
    ficam órfãs (desenho, medido 6). Dias = `atribuição.work_days or modelo.work_days` (o
    recurso do «Em falta»). A entrada de `dias` desse dia diz a loja (vazia = a da ficha) e
    as horas (vazias = o horário da loja). Uma entrada para uma loja fechada, sem horário ou
    por abrir ignora-se; as horas recortam-se ao horário.
    """
    semana = dia.weekday()
    fora = {}
    for emp in p["empregados"]:
        atribuicao = atribuicao_do_dia(p["atribuicoes"].get(emp["id"], []), dia)
        if not atribuicao:
            continue
        modelo = p["modelos"].get(atribuicao.get("template_id")) or {}
        if semana not in (atribuicao.get("work_days") or modelo.get("work_days") or []):
            continue
        entrada = next((d for d in modelo.get("dias") or [] if d.get("dia") == semana), {})
        loja_id = entrada.get("location_id") or emp.get("location_id")
        estado, janela = horario_do_dia(p["lojas"].get(loja_id), dia)
        if estado != "aberta":
            continue
        if entrada.get("inicio") and entrada.get("fim"):
            pedido = (minutos(entrada["inicio"]), minutos(entrada["fim"]))
        else:
            pedido = janela
        horas = recortar(pedido, janela)
        if horas:
            fora[emp["id"]] = (loja_id, horas)
    return fora


def ausentes(dia: date, ausencias: List[Dict]) -> Set[str]:
    """Os `employee_id` com ausência APROVADA (de qualquer tipo) que inclui o dia."""
    iso = dia.isoformat()
    return {a.get("employee_id") for a in ausencias
            if a.get("status") == "aprovado"
            and (a.get("start_date") or "")[:10] <= iso <= (a.get("end_date") or "")[:10]}


def _pessoa(user_id, nome, horas: Intervalo, origem: str, extra: bool = False, ida_id=None) -> Dict:
    return {"user_id": user_id, "nome": nome, "inicio": hhmm(horas[0]), "fim": hhmm(horas[1]),
            "origem": origem, "extra": extra, "ida_id": ida_id}


def _loja_do_dia(loja: Dict, dia: date, pessoas: List[Dict], personalizados: List[Dict]) -> Dict:
    estado, janela = horario_do_dia(loja, dia)
    pessoas = sorted(pessoas, key=lambda x: (x["inicio"], x["nome"] or ""))
    buracos = []
    if janela:
        ocupado = [(minutos(x["inicio"]), minutos(x["fim"])) for x in pessoas]
        buracos = [{"inicio": hhmm(a), "fim": hhmm(b)} for a, b in subtrair([janela], ocupado)]
    return {
        "location_id": loja["id"], "nome": loja.get("name"), "estado": estado,
        "abre": hhmm(janela[0]) if janela else None, "fecha": hhmm(janela[1]) if janela else None,
        "feriados": feriados_da_loja(dia, personalizados, loja),
        "pessoas": pessoas, "buracos": buracos,
    }


def dia_do_calendario(dia: date, dados: Dict, p: Optional[Dict] = None) -> Dict:
    """Um dia: para cada loja com horário (as por abrir não aparecem), quem lá está e os buracos.

    1. a escala (`_escala`); 2. sai quem tem ausência aprovada; 3. buracos = horário menos a
    união das horas de quem lá está («ninguém» é um buraco único igual a abre–fecha).
    """
    p = p or _preparar(dados)
    escala = _escala(dia, p)
    for emp_id in ausentes(dia, dados.get("ausencias", [])):
        escala.pop(emp_id, None)
    presentes = {}  # type: Dict[str, List[Dict]]
    for emp_id, (loja_id, horas) in escala.items():
        presentes.setdefault(loja_id, []).append(_pessoa(
            p["user_do_emp"].get(emp_id), p["nome_do_emp"].get(emp_id), horas, "escala"))
    personalizados = dados.get("feriados", [])
    return {
        "data": dia.isoformat(),
        "feriados": feriados_do_dia(dia, personalizados),
        "lojas": [_loja_do_dia(loja, dia, presentes.get(loja["id"], []), personalizados)
                  for loja in p["lojas_ordenadas"]
                  if horario_do_dia(loja, dia)[0] in ("aberta", "fechada")],
    }


def calendario_do_mes(ano: int, mes: int, dados: Dict) -> List[Dict]:
    p = _preparar(dados)
    return [dia_do_calendario(date(ano, mes, d), dados, p) for d in range(1, monthrange(ano, mes)[1] + 1)]
```

- [ ] **Passo 4: Correr e ver passar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_a_semana_normal.py tests/calendario/test_intervalos_e_horario.py tests/calendario/test_feriados.py -q
```

Esperado: `27 passed`.

- [ ] **Passo 5: Prova por mutação**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PY=~/Developer/RH/backend/.venv/bin/python
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py calendario.py 'loja_id = entrada.get("location_id") or emp.get("location_id")' 'loja_id = emp.get("location_id")' -- $PY -m pytest tests/calendario/test_a_semana_normal.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py calendario.py 'atribuicao.get("work_days") or modelo.get("work_days") or []' 'atribuicao.get("work_days") or []' -- $PY -m pytest tests/calendario/test_a_semana_normal.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py calendario.py 'if a.get("status") == "aprovado"' 'if a.get("status") in ("aprovado", "pendente")' -- $PY -m pytest tests/calendario/test_a_semana_normal.py -q
```

Esperado: (1) `FAILED …test_a_semana_normal_da_exactamente_a_grelha_dos_buracos` — a Joana fica sempre em Algueirão e aparecem a Amadora à segunda/terça e Oeiras à quarta com buraco; (2) `FAILED …test_sem_copia_dos_dias_na_atribuicao_vale_a_do_modelo`; (3) `FAILED …test_so_a_ausencia_aprovada_tira_alguem`. As três terminam em «Mutação apanhada».

- [ ] **Passo 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add backend/calendario.py backend/tests/calendario/test_a_semana_normal.py
git commit -m "Calendário: a escala de cada pessoa dá os buracos de cada loja

A partir dos colaboradores (não das atribuições, que ficam órfãs quando alguém sai),
da escala de cada um com loja e horas por dia e das ausências aprovadas, o cálculo
devolve quem está em cada loja e o que falta. O teste da semana normal prende a grelha
exacta que o dono descreveu (Oeiras à terça, Alfragide de manhã seg/ter e à noite
qua/qui, Benfica sempre).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Tarefa 3: O cálculo, parte 3 — as idas (de gestor e de colaborador) e o teste de Outubro

**Ficheiros:**
- Modificar: `backend/calendario.py` (substituir a função `dia_do_calendario` inteira)
- Testes: `backend/tests/calendario/test_outubro.py` (criar)

**Interfaces:**
- Consome: `_preparar`, `_escala`, `ausentes`, `_pessoa`, `_loja_do_dia` (Tarefa 2); `dados_semana_normal.ida`, `.ausencia` (Tarefa 1).
- Produz: `calendario.dia_do_calendario(dia, dados, p=None)` com a mesma assinatura e forma, agora a ler `dados["idas"]` (`[{"id", "data", "location_id", "user_id", "inicio", "fim"}]`): pessoas com `origem: "ida"`, `ida_id` e `extra` (calculado com as horas JÁ recortadas ao horário); a escala de um colaborador perde as horas das idas dele nesse dia; a ida de um colaborador com ausência aprovada nesse dia (aprovada depois de a ida existir — marcá-la já dava 409) **não tapa nada** e a loja volta a mostrar o buraco (a ida continua em `idas[]` da resposta do mês, Tarefa 5, para as vistas Pessoal e Lista).

> **Decisão por omissão, a confirmar com o dono na Tarefa 16 (Passo 2):** o desenho manda sair quem tem ausência aprovada (secção 2, passo 3) e proíbe marcar alguém de férias (409); contar a ida de quem entretanto ficou de férias punha o ecrã a dizer «coberta» numa loja vazia — o pior erro possível aqui. Se o dono preferir outra coisa, muda-se só o `continue` marcado abaixo.

- [ ] **Passo 1: Escrever os testes que falham**

`backend/tests/calendario/test_outubro.py`:

```python
"""Outubro (desenho, «Testes» 2): as férias abrem buracos e as idas tapam-nos.

O Weber está de férias de 21 a 25/10 e a Carol cobre a Amadora a 22, 23 e 25 (é o que a
mensagem de WhatsApp diz). A ida de um colaborador TIRA à escala dele as horas da ida: a
Joana em Benfica numa quarta abre Oeiras; 2 horas dela abrem só essas 2 horas; numa folga
dela a ida é «extra». (O 409 de a marcar num dia de férias prova-se nas rotas.)
"""
import calendario

from . import dados_semana_normal as sn

JOANA = sn.user("Joana")


def _dias(dados):
    return calendario.calendario_do_mes(2026, 10, dados)


def _loja(dias, data, nome):
    dia = next(d for d in dias if d["data"] == data)
    return next(l for l in dia["lojas"] if l["nome"] == nome)


def _buracos(dias, data, nome):
    return ["%s-%s" % (b["inicio"], b["fim"]) for b in _loja(dias, data, nome)["buracos"]]


def _com_ida(*idas):
    dados = sn.semana_normal()
    dados["idas"] = list(idas)
    return _dias(dados)


def test_as_ferias_do_weber_abrem_a_amadora_de_21_a_25():
    dados = sn.semana_normal()
    dados["ausencias"].append(sn.ausencia("Weber", "2026-10-21", "2026-10-25"))
    dias = _dias(dados)
    assert {d: _buracos(dias, d, "Amadora") for d in
            ("2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25", "2026-10-26")} == {
        "2026-10-20": [], "2026-10-21": ["14:00-23:00"], "2026-10-22": ["14:00-23:00"],
        "2026-10-23": ["14:00-23:00"], "2026-10-24": ["14:00-23:00"], "2026-10-25": ["14:00-23:00"],
        "2026-10-26": []}


def test_a_carol_tapa_a_amadora_a_22_23_e_25():
    dados = sn.semana_normal()
    dados["ausencias"].append(sn.ausencia("Weber", "2026-10-21", "2026-10-25"))
    dados["idas"] = [sn.ida(d, sn.AMADORA, sn.CAROL, "14:00", "23:00") for d in ("2026-10-22", "2026-10-23", "2026-10-25")]
    dias = _dias(dados)
    assert [_buracos(dias, d, "Amadora") for d in ("2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25")] == [
        ["14:00-23:00"], [], [], ["14:00-23:00"], []]
    assert _loja(dias, "2026-10-22", "Amadora")["pessoas"] == [{
        "user_id": sn.CAROL, "nome": "Carol Santos", "inicio": "14:00", "fim": "23:00",
        "origem": "ida", "extra": False, "ida_id": dados["idas"][0]["id"]}]


def test_a_joana_em_benfica_numa_quarta_abre_oeiras():
    dias = _com_ida(sn.ida("2026-10-28", sn.BENFICA, JOANA, "13:00", "22:00"))
    assert _buracos(dias, "2026-10-28", "Oeiras") == ["13:00-22:00"]
    assert _buracos(dias, "2026-10-28", "Benfica") == []
    [joana] = _loja(dias, "2026-10-28", "Benfica")["pessoas"]
    assert (joana["nome"], joana["origem"], joana["extra"]) == ("Joana", "ida", False)


def test_duas_horas_dela_em_benfica_abrem_so_essas_duas_horas():
    dias = _com_ida(sn.ida("2026-10-28", sn.BENFICA, JOANA, "13:00", "15:00"))
    assert _buracos(dias, "2026-10-28", "Oeiras") == ["13:00-15:00"]
    assert [(p["nome"], p["inicio"], p["fim"], p["origem"]) for p in _loja(dias, "2026-10-28", "Oeiras")["pessoas"]] == [
        ("Joana", "15:00", "22:00", "escala")]
    assert _buracos(dias, "2026-10-28", "Benfica") == ["15:00-22:00"]


def test_numa_folga_dela_a_ida_e_extra():
    dias = _com_ida(sn.ida("2026-10-31", sn.BENFICA, JOANA, "13:00", "22:00"))   # sábado
    [joana] = _loja(dias, "2026-10-31", "Benfica")["pessoas"]
    assert (joana["origem"], joana["extra"]) == ("ida", True)


def test_chegar_antes_de_abrir_nao_faz_a_ida_extra():
    # Quarta: a escala dela é Oeiras 13h–22h. A ida a Benfica das 12h30 mostra-se 13h–22h
    # (recortada ao horário) e cabe toda na escala dela — não é «extra».
    dias = _com_ida(sn.ida("2026-10-28", sn.BENFICA, JOANA, "12:30", "22:00"))
    [joana] = _loja(dias, "2026-10-28", "Benfica")["pessoas"]
    assert (joana["inicio"], joana["fim"], joana["extra"]) == ("13:00", "22:00", False)


def test_a_ida_de_quem_ficou_de_ferias_depois_nao_tapa_o_buraco():
    # A ida foi marcada e as férias aprovadas depois (marcá-la já de férias dava 409). Ela não
    # está lá: Benfica e Oeiras ficam sem ninguém — nunca «coberta» numa loja vazia.
    dados = sn.semana_normal()
    dados["idas"] = [sn.ida("2026-10-28", sn.BENFICA, JOANA, "13:00", "22:00")]
    dados["ausencias"].append(sn.ausencia("Joana", "2026-10-28", "2026-10-28"))
    dias = _dias(dados)
    assert _buracos(dias, "2026-10-28", "Benfica") == ["13:00-22:00"]
    assert _buracos(dias, "2026-10-28", "Oeiras") == ["13:00-22:00"]


def test_a_ida_de_uma_gestora_soma_se_e_recorta_se_ao_horario():
    dias = _com_ida(sn.ida("2026-10-27", sn.OEIRAS, sn.DEBORA, "12:30", "22:00"))
    assert _buracos(dias, "2026-10-27", "Oeiras") == []
    [debora] = _loja(dias, "2026-10-27", "Oeiras")["pessoas"]
    assert (debora["nome"], debora["inicio"], debora["fim"], debora["extra"]) == ("Débora Ferreira", "13:00", "22:00", False)


def test_uma_ida_numa_loja_sem_horario_ou_fechada_nao_entra_nos_dias():
    dias = _com_ida(sn.ida("2026-10-27", sn.PIZZARIA, sn.DEBORA, "13:00", "22:00"),
                    sn.ida("2026-10-27", sn.BELEM, sn.CAROL, "11:30", "19:00"))
    dia = next(d for d in dias if d["data"] == "2026-10-27")
    assert [p["nome"] for l in dia["lojas"] for p in l["pessoas"] if p["origem"] == "ida"] == []


def test_uma_conta_apagada_aparece_com_recurso():
    dias = _com_ida(sn.ida("2026-10-27", sn.OEIRAS, "u-apagada", "13:00", "22:00"))
    assert _loja(dias, "2026-10-27", "Oeiras")["pessoas"][0]["nome"] == calendario.NOME_SEM_CONTA


def test_o_feriado_aparece_e_as_lojas_continuam_abertas():
    dia = next(d for d in _dias(sn.semana_normal()) if d["data"] == "2026-10-05")
    assert dia["feriados"] == ["Implantação da República"]
    assert {l["nome"]: l["estado"] for l in dia["lojas"]}["Alfragide"] == "aberta"
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_outubro.py -q
```

Esperado: `7 failed, 4 passed` — falham os sete com idas que tapam (a Carol não aparece, Oeiras não abre buraco, `ValueError: not enough values to unpack` nos `[joana] = …`, incluindo o das 12h30, `IndexError` no da conta apagada); passam as férias do Weber, o da loja sem horário (ainda ninguém entra), o do feriado e o da ida de quem ficou de férias (ainda nenhuma ida entra — quem o prende é a mutação 4 do Passo 5).

- [ ] **Passo 3: Implementação**

Em `backend/calendario.py`, substituir a função `dia_do_calendario` inteira (da linha `def dia_do_calendario(` até ao `}` que fecha o `return`, antes de `def calendario_do_mes(`) por:

```python
def dia_do_calendario(dia: date, dados: Dict, p: Optional[Dict] = None) -> Dict:
    """Um dia: para cada loja com horário (as por abrir não aparecem), quem lá está e os buracos.

    1. a escala (`_escala`); 2. sai quem tem ausência aprovada; 3. entram as idas — a de um
    gestor soma-se à loja; a de um colaborador TIRA à escala dele as horas da ida (a Joana
    13h–15h em Benfica numa quarta deixa Oeiras com buraco só das 13h às 15h), e as horas da
    ida (recortadas ao horário) que não estavam na escala dele são «extra» (numa folga, a ida
    toda); 4. buracos = horário menos a união das horas de quem lá está («ninguém» = um
    buraco igual a abre–fecha).
    Uma ida numa loja sem horário, fechada ou por abrir não entra aqui (continua na lista das
    idas do mês). A de um colaborador com ausência aprovada nesse dia também não.
    """
    p = p or _preparar(dados)
    escala = _escala(dia, p)
    fora = ausentes(dia, dados.get("ausencias", []))
    for emp_id in fora:
        escala.pop(emp_id, None)
    iso = dia.isoformat()
    presentes = {}  # type: Dict[str, List[Dict]]
    tirado = {}  # type: Dict[str, List[Intervalo]]
    for ida in (i for i in dados.get("idas", []) if i.get("data") == iso):
        user = p["utilizadores"].get(ida.get("user_id")) or {}
        emp_id = user.get("employee_id") if user.get("role") == "colaborador" else None
        if emp_id and emp_id in fora:
            # Férias aprovadas DEPOIS de a ida existir (marcá-la já de férias dá 409): não está
            # lá, por isso não tapa — nunca «coberta» numa loja vazia. A ida continua em
            # `idas[]` (vistas Pessoal e Lista). Decisão por omissão, confirmada com o dono.
            continue
        horas = (minutos(ida["inicio"]), minutos(ida["fim"]))
        estado, janela = horario_do_dia(p["lojas"].get(ida.get("location_id")), dia)
        dentro = recortar(horas, janela) if estado == "aberta" else None
        extra = False
        if emp_id:
            tirado.setdefault(emp_id, []).append(horas)
            minha = escala.get(emp_id)
            # Com as horas recortadas: chegar meia hora antes de abrir não é «extra».
            extra = bool(subtrair([dentro or horas], [minha[1]] if minha else []))
        if dentro:
            presentes.setdefault(ida["location_id"], []).append(_pessoa(
                ida.get("user_id"), user.get("name") or NOME_SEM_CONTA, dentro, "ida", extra, ida.get("id")))
    for emp_id, (loja_id, horas) in escala.items():
        for pedaco in subtrair([horas], tirado.get(emp_id, [])):
            presentes.setdefault(loja_id, []).append(_pessoa(
                p["user_do_emp"].get(emp_id), p["nome_do_emp"].get(emp_id), pedaco, "escala"))
    personalizados = dados.get("feriados", [])
    return {
        "data": iso,
        "feriados": feriados_do_dia(dia, personalizados),
        "lojas": [_loja_do_dia(loja, dia, presentes.get(loja["id"], []), personalizados)
                  for loja in p["lojas_ordenadas"]
                  if horario_do_dia(loja, dia)[0] in ("aberta", "fechada")],
    }
```

- [ ] **Passo 4: Correr e ver passar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_outubro.py tests/calendario/test_a_semana_normal.py tests/calendario/test_intervalos_e_horario.py tests/calendario/test_feriados.py -q
```

Esperado: `38 passed` (os 27 de antes + 11).

- [ ] **Passo 5: Prova por mutação**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PY=~/Developer/RH/backend/.venv/bin/python
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py calendario.py 'for pedaco in subtrair([horas], tirado.get(emp_id, [])):' 'for pedaco in [horas]:' -- $PY -m pytest tests/calendario/test_outubro.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py calendario.py 'extra = bool(subtrair([dentro or horas], [minha[1]] if minha else []))' 'extra = False' -- $PY -m pytest tests/calendario/test_outubro.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py calendario.py 'dentro = recortar(horas, janela) if estado == "aberta" else None' 'dentro = horas' -- $PY -m pytest tests/calendario/test_outubro.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py calendario.py '        if emp_id and emp_id in fora:' '        if False:' -- $PY -m pytest tests/calendario/test_outubro.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py calendario.py 'extra = bool(subtrair([dentro or horas],' 'extra = bool(subtrair([horas],' -- $PY -m pytest tests/calendario/test_outubro.py -q
```

Esperado: (1) `FAILED …test_a_joana_em_benfica_numa_quarta_abre_oeiras` e `…test_duas_horas_dela…` (Oeiras continua coberta pela escala dela); (2) `FAILED …test_numa_folga_dela_a_ida_e_extra`; (3) `FAILED …test_a_ida_de_uma_gestora_soma_se_e_recorta_se_ao_horario` (12:30 em vez de 13:00), `…test_uma_ida_numa_loja_sem_horario_ou_fechada…` e `…test_chegar_antes_de_abrir…` (12:30); (4) `FAILED …test_a_ida_de_quem_ficou_de_ferias_depois_nao_tapa_o_buraco` (`[] != ['13:00-22:00']` em Benfica: a ida de quem está de férias tapava a loja); (5) `FAILED …test_chegar_antes_de_abrir_nao_faz_a_ida_extra` (`extra` True pela meia hora antes de abrir). Todas com «Mutação apanhada».

- [ ] **Passo 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add backend/calendario.py backend/tests/calendario/test_outubro.py
git commit -m "Calendário: as idas tapam buracos e a de um colaborador destapa a loja dele

A ida de uma gestora soma-se à loja; a de um colaborador tira à escala dele as horas da
ida (a Joana duas horas em Benfica deixa Oeiras sem ninguém só essas duas horas) e o que
não estava na escala dele fica marcado como extra. As horas recortam-se ao horário da
loja antes de decidir o extra. A ida de quem entretanto ficou de férias não tapa nada:
o ecrã nunca diz coberta numa loja vazia. O teste de outubro prende o caso real das
férias do Weber e da Carol na Amadora.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Tarefa 4: O cálculo, parte 4 — a contagem dos dias

**Ficheiros:**
- Modificar: `backend/calendario.py` (acrescentar no fim)
- Testes: `backend/tests/calendario/test_contagem.py` (criar)

**Interfaces:**
- Consome: `horario_do_dia`, `recortar`, `minutos`, `NOME_SEM_CONTA` (Tarefa 1).
- Produz:
  - `calendario.valor_da_ida(ida: dict, loja: Optional[dict]) -> float` (1.0 ou 0.5)
  - `calendario.contagem(idas: List[dict], lojas: Dict[str, dict], nomes: Dict[str, str]) -> List[dict]` → `[{"user_id", "nome", "meses": [12 floats], "total": float}]`, do total maior para o menor (empate: nome)

- [ ] **Passo 1: Escrever os testes que falham**

`backend/tests/calendario/test_contagem.py`:

```python
"""A contagem (desenho, «Contagem» e Testes 6): quantos dias cada pessoa fez no ano.

Uma ida vale 1 dia se as horas DENTRO do horário da loja nesse dia forem pelo menos metade
das horas de abertura, e 0,5 se forem menos; por pessoa e dia soma-se e corta-se em 1. Conta
as idas marcadas, futuras incluídas — é o que as gestoras usam para se equilibrarem.
"""
import calendario

from . import dados_semana_normal as sn

LOJAS = {l["id"]: l for l in sn.LOJAS}
NOMES = {sn.DEBORA: "Débora Ferreira", sn.CAROL: "Carol Santos"}


def _valor(loja, inicio, fim, data="2026-10-27"):
    return calendario.valor_da_ida(sn.ida(data, loja, sn.DEBORA, inicio, fim), LOJAS.get(loja))


def test_metade_ou_mais_do_horario_vale_um_dia():
    assert _valor(sn.OEIRAS, "13:00", "22:00") == 1.0
    assert _valor(sn.OEIRAS, "13:00", "17:30") == 1.0      # 4h30 de 9h: exactamente metade
    assert _valor(sn.OEIRAS, "13:00", "17:29") == 0.5
    assert _valor(sn.ALFRAGIDE, "10:00", "14:00") == 0.5   # 4h de 13h


def test_so_contam_as_horas_dentro_do_horario():
    assert _valor(sn.OEIRAS, "08:00", "17:00") == 0.5       # 9h de ida, só 4h dentro


def test_a_metade_e_a_do_horario_desse_dia():
    assert _valor(sn.BELEM, "11:30", "15:30", data="2026-10-31") == 1.0   # sábado: 4h de 7h30
    assert _valor(sn.BELEM, "11:30", "15:30", data="2026-11-01") == 0.5   # domingo: 4h de 8h30


def test_numa_loja_sem_horario_fechada_ou_apagada_vale_um_dia():
    assert _valor(sn.PIZZARIA, "10:00", "11:00") == 1.0
    assert _valor(sn.BELEM, "11:30", "12:00", data="2026-10-27") == 1.0   # terça: fechada
    assert calendario.valor_da_ida(sn.ida("2026-10-27", "loja-apagada", sn.DEBORA, "10:00", "11:00"), None) == 1.0


def test_duas_meias_no_mesmo_dia_sao_um_dia_e_nunca_mais_de_um():
    idas = [sn.ida("2026-10-27", sn.ALFRAGIDE, sn.DEBORA, "10:00", "14:00"),   # 0,5
            sn.ida("2026-10-27", sn.OEIRAS, sn.DEBORA, "18:00", "22:00"),      # 0,5
            sn.ida("2026-10-28", sn.ALFRAGIDE, sn.DEBORA, "10:00", "17:00"),   # 1
            sn.ida("2026-10-28", sn.OEIRAS, sn.DEBORA, "17:00", "22:00")]      # 1, mas o dia corta em 1
    [linha] = calendario.contagem(idas, LOJAS, NOMES)
    assert (linha["meses"][9], linha["total"]) == (2.0, 2.0)


def test_os_meses_o_total_o_nome_e_a_ordem():
    idas = [sn.ida("2026-10-06", sn.OEIRAS, sn.DEBORA, "13:00", "22:00"),
            sn.ida("2026-11-03", sn.ALFRAGIDE, sn.DEBORA, "10:00", "14:00"),
            sn.ida("2026-12-08", sn.ALFRAGIDE, sn.CAROL, "10:00", "23:00"),
            sn.ida("2026-12-09", sn.ALFRAGIDE, sn.CAROL, "10:00", "23:00"),
            sn.ida("2026-12-10", sn.ALFRAGIDE, "u-apagada", "10:00", "23:00")]
    linhas = calendario.contagem(idas, LOJAS, NOMES)
    assert [(l["user_id"], l["nome"], l["total"]) for l in linhas] == [
        (sn.CAROL, "Carol Santos", 2.0), (sn.DEBORA, "Débora Ferreira", 1.5), ("u-apagada", "(conta removida)", 1.0)]
    assert linhas[1]["meses"] == [0.0] * 9 + [1.0, 0.5, 0.0]
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_contagem.py -q
```

Esperado: `6 failed` com `AttributeError: module 'calendario' has no attribute 'valor_da_ida'` (ou `'contagem'`).

- [ ] **Passo 3: Implementação**

Acrescentar no fim de `backend/calendario.py`:

```python


# --- A contagem: quantos dias cada pessoa fez (e vai fazer) no ano --------------------------


def valor_da_ida(ida: Dict, loja: Optional[Dict]) -> float:
    """1 dia se as horas DENTRO do horário da loja nesse dia forem pelo menos metade das horas
    de abertura; 0,5 se forem menos. Uma ida numa loja que entretanto ficou sem horário (ou
    fechada nesse dia, ou apagada) vale 1 — não há com que comparar e a ida aconteceu."""
    _estado, janela = horario_do_dia(loja, date.fromisoformat(ida["data"]))
    if not janela:
        return 1.0
    dentro = recortar((minutos(ida["inicio"]), minutos(ida["fim"])), janela)
    feitas = dentro[1] - dentro[0] if dentro else 0
    return 1.0 if feitas * 2 >= janela[1] - janela[0] else 0.5


def contagem(idas: List[Dict], lojas: Dict[str, Dict], nomes: Dict[str, str]) -> List[Dict]:
    """`[{user_id, nome, meses: [12], total}]`, do total maior para o menor. Por pessoa e por
    dia soma-se e corta-se em 1 (duas meias no mesmo dia = 1; nunca mais de 1)."""
    por_dia = {}  # type: Dict[Tuple[str, str], float]
    for ida in idas:
        chave = (ida["user_id"], ida["data"])
        por_dia[chave] = min(1.0, por_dia.get(chave, 0.0) + valor_da_ida(ida, lojas.get(ida.get("location_id"))))
    meses = {}  # type: Dict[str, List[float]]
    for (user_id, data), valor in por_dia.items():
        meses.setdefault(user_id, [0.0] * 12)[int(data[5:7]) - 1] += valor
    linhas = [{"user_id": u, "nome": nomes.get(u) or NOME_SEM_CONTA, "meses": m, "total": sum(m)}
              for u, m in meses.items()]
    return sorted(linhas, key=lambda l: (-l["total"], l["nome"].lower()))
```

- [ ] **Passo 4: Correr e ver passar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_contagem.py -q
```

Esperado: `6 passed`.

- [ ] **Passo 5: Prova por mutação**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PY=~/Developer/RH/backend/.venv/bin/python
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py calendario.py 'return 1.0 if feitas * 2 >= janela[1] - janela[0] else 0.5' 'return 1.0 if feitas * 2 > janela[1] - janela[0] else 0.5' -- $PY -m pytest tests/calendario/test_contagem.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py calendario.py 'por_dia[chave] = min(1.0, por_dia.get(chave, 0.0) + valor_da_ida(' 'por_dia[chave] = (por_dia.get(chave, 0.0) + valor_da_ida(' -- $PY -m pytest tests/calendario/test_contagem.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py calendario.py 'dentro = recortar((minutos(ida["inicio"]), minutos(ida["fim"])), janela)' 'dentro = (minutos(ida["inicio"]), minutos(ida["fim"]))' -- $PY -m pytest tests/calendario/test_contagem.py -q
```

Esperado: (1) `FAILED …test_metade_ou_mais_do_horario_vale_um_dia` (a metade exacta passa a 0,5); (2) `FAILED …test_duas_meias_no_mesmo_dia…` (3,0 em vez de 2,0); (3) `FAILED …test_so_contam_as_horas_dentro_do_horario`. Todas com «Mutação apanhada».

- [ ] **Passo 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add backend/calendario.py backend/tests/calendario/test_contagem.py
git commit -m "Calendário: contagem dos dias de cada pessoa pela metade do horário da loja

O dono quer ver quantos dias cada gestora fez para se equilibrarem: uma ida vale um dia
se cobrir pelo menos metade do horário da loja nesse dia (só as horas dentro do horário)
e meio dia se cobrir menos, nunca mais de um dia por pessoa por dia.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Tarefa 5: O cálculo, parte 5 — as regras de uma ida e a resposta do mês

**Ficheiros:**
- Modificar: `backend/calendario.py` (acrescentar no fim)
- Testes: `backend/tests/calendario/test_regras_das_idas.py`, `backend/tests/calendario/test_resposta_do_mes.py` (criar)

**Interfaces:**
- Consome: `horario_do_dia`, `recortar`, `minutos`, `hhmm`, `hora_curta`, `data_curta`, `primeiro_nome`, `_HHMM`, `GESTORES`, `ESCALAVEIS`, `NOME_SEM_*` (Tarefa 1); `calendario_do_mes` (Tarefas 2-3).
- Produz (usado pelas rotas, Tarefas 6-7, e pelo script, Tarefa 14):
  - `calendario.AUSENCIAS: Dict[str, str]` (`"ferias"` → `"de férias"`, …)
  - `calendario.limites_do_mes(ano, mes) -> Tuple[str, str]` (`("2026-10-01", "2026-10-31")`)
  - `calendario.validar_pedido(datas: List[str], user_ids: List[str]) -> Optional[str]`
  - `calendario.validar_horas(inicio, fim) -> Optional[str]`
  - `calendario.validar_ida(dia: date, loja: Optional[dict], inicio, fim) -> Optional[str]`
  - `calendario.choques(novas: List[dict], existentes: List[dict], ignorar_id: Optional[str] = None) -> List[Tuple[dict, dict]]`
  - `calendario.mensagem_de_choque(nova: dict, outra: dict, utilizadores: Dict[str, dict], nomes_lojas: Dict[str, str]) -> str`
  - `calendario.ausencias_que_impedem(novas: List[dict], utilizadores: Dict[str, dict], ausencias: List[dict]) -> List[str]`
  - `calendario.pessoas_escalaveis(utilizadores: List[dict]) -> List[dict]` → `[{"id", "nome", "tipo": "gestor"|"colaborador"}]`
  - `calendario.resposta_do_mes(ano, mes, dados, eu: Optional[str], pode_marcar: bool) -> dict` → `{"ano", "mes", "eu", "pode_marcar", "dias", "idas": [{"id", "data", "location_id", "user_id", "inicio", "fim", "nome", "loja"}], "ausencias": [{"nome", "tipo", "inicio", "fim", "loja"}], "lojas": [{"id", "nome"}], "pessoas": [...]}`

- [ ] **Passo 1: Escrever os testes que falham**

`backend/tests/calendario/test_regras_das_idas.py`:

```python
"""As regras de uma ida (desenho, secção 1 «Idas» e secção 3): o que o servidor recusa e com
que palavras. As rotas (Tarefa 7) só juntam estas respostas às consultas."""
from datetime import date

import calendario

from . import dados_semana_normal as sn

LOJAS = {l["id"]: l for l in sn.LOJAS}
UTILIZADORES = {u["id"]: u for u in sn.semana_normal()["utilizadores"]}
HH_MM = "As horas escrevem-se HH:MM (por exemplo 13:00)."
FIM_ANTES = "A hora de fim tem de ser depois da hora de início."


def _ida(data, loja, inicio, fim):
    return calendario.validar_ida(date.fromisoformat(data), LOJAS.get(loja), inicio, fim)


def test_horas_validas():
    assert calendario.validar_horas("13:00", "22:00") is None
    assert calendario.validar_horas("9:00", "22:00") == HH_MM
    assert calendario.validar_horas("13:00", "24:00") == HH_MM
    assert calendario.validar_horas(None, "22:00") == HH_MM
    assert calendario.validar_horas("22:00", "13:00") == FIM_ANTES
    assert calendario.validar_horas("13:00", "13:00") == FIM_ANTES


def test_so_em_lojas_com_horario_e_abertas_nesse_dia():
    assert _ida("2026-10-27", sn.OEIRAS, "13:00", "22:00") is None
    assert _ida("2026-10-27", sn.BELEM, "11:30", "19:00") == "Belém está fechada a 27/10. Escolha outro dia."
    assert _ida("2026-10-21", sn.BENFICA, "13:00", "22:00") == "Benfica só abre a 24/10."
    assert _ida("2026-10-27", sn.PIZZARIA, "13:00", "22:00") == "Pizzaria não tem horário e não entra no calendário."
    assert _ida("2026-10-27", "loja-apagada", "13:00", "22:00") == "Essa loja não existe."
    assert _ida("2026-10-27", sn.OEIRAS, "22:00", "13:00") == FIM_ANTES


def test_as_horas_tem_de_tocar_no_horario_e_as_que_saem_aceitam_se():
    fora = "Oeiras abre das 13h às 22h a 27/10: as horas da ida têm de tocar nesse horário."
    assert _ida("2026-10-27", sn.OEIRAS, "08:00", "12:00") == fora
    assert _ida("2026-10-27", sn.OEIRAS, "12:00", "13:00") == fora        # encostar não é tocar
    assert _ida("2026-10-27", sn.OEIRAS, "12:30", "14:00") is None        # recorta-se no cálculo


def test_o_pedido_sem_repetidos_e_com_limites():
    assert calendario.validar_pedido(["2026-10-06", "2026-10-13"], [sn.DEBORA, sn.CAROL]) is None
    trinta_e_dois = ["2026-10-%02d" % d for d in range(1, 32)] + ["2026-11-01"]
    assert calendario.validar_pedido([], [sn.DEBORA]) == "Escolha entre 1 e 31 dias."
    assert calendario.validar_pedido(trinta_e_dois, [sn.DEBORA]) == "Escolha entre 1 e 31 dias."
    assert calendario.validar_pedido(["2026-10-06"], []) == "Escolha uma ou duas pessoas."
    assert calendario.validar_pedido(["2026-10-06"], [sn.DEBORA, sn.CAROL, sn.GERENTE]) == "Escolha uma ou duas pessoas."
    assert calendario.validar_pedido(["2026-10-06", "2026-10-06"], [sn.DEBORA]) == "Há dias repetidos no pedido."
    assert calendario.validar_pedido(["2026-10-06"], [sn.DEBORA, sn.DEBORA]) == "Há pessoas repetidas no pedido."


def test_a_mesma_pessoa_nao_esta_em_dois_sitios_ao_mesmo_tempo():
    alfragide = dict(sn.ida("2026-10-27", sn.ALFRAGIDE, sn.DEBORA, "10:00", "14:00"), id="a")
    nova = sn.ida("2026-10-27", sn.OEIRAS, sn.DEBORA, "13:00", "22:00")
    assert calendario.choques([nova], [alfragide]) == [(nova, alfragide)]
    assert calendario.choques([dict(nova, inicio="14:00")], [alfragide]) == []        # encostadas
    assert calendario.choques([dict(nova, user_id=sn.CAROL)], [alfragide]) == []      # outra pessoa
    assert calendario.choques([dict(nova, data="2026-10-28")], [alfragide]) == []     # outro dia
    assert calendario.choques([dict(alfragide, inicio="11:00")], [alfragide], ignorar_id="a") == []   # o PUT


def test_a_mensagem_do_choque_diz_quem_onde_e_quando():
    alfragide = sn.ida("2026-10-21", sn.ALFRAGIDE, sn.DEBORA, "10:00", "14:00")
    nova = sn.ida("2026-10-21", sn.OEIRAS, sn.DEBORA, "13:00", "22:00")
    assert calendario.mensagem_de_choque(nova, alfragide, UTILIZADORES, {sn.ALFRAGIDE: "Alfragide"}) == \
        "Débora já está em Alfragide das 10h às 14h a 21/10."
    assert calendario.mensagem_de_choque(nova, alfragide, UTILIZADORES, {}) == \
        "Débora já está em (loja removida) das 10h às 14h a 21/10."


def test_um_colaborador_com_ausencia_aprovada_nao_se_marca():
    ausencias = [sn.ausencia("Weber", "2026-10-21", "2026-10-25"),
                 sn.ausencia("Joana", "2026-10-27", "2026-10-27", status="pendente"),
                 sn.ausencia("Emily", "2026-10-26", "2026-10-26", tipo="folga")]
    novas = [sn.ida(d, sn.AMADORA, sn.user("Weber"), "14:00", "23:00") for d in ("2026-10-20", "2026-10-22", "2026-10-23")]
    novas += [sn.ida("2026-10-27", sn.OEIRAS, sn.user("Joana"), "13:00", "22:00"),
              sn.ida("2026-10-26", sn.OEIRAS, sn.user("Emily"), "13:00", "22:00"),
              sn.ida("2026-10-22", sn.AMADORA, sn.DEBORA, "14:00", "23:00")]
    assert calendario.ausencias_que_impedem(novas, UTILIZADORES, ausencias) == [
        "Weber está de férias a 22/10.", "Weber está de férias a 23/10.", "Emily está de folga a 26/10."]
```

`backend/tests/calendario/test_resposta_do_mes.py`:

```python
"""A resposta do `GET /api/bolso/calendario` (desenho, secção 3): o mês inteiro num pedido.

`idas[]` é de onde o ecrã monta a vista Pessoal e as idas da Lista (não de `dias`): uma ida
numa loja que entretanto perdeu o horário continua a aparecer aqui. Os nomes têm recurso.
"""
import calendario

from . import dados_semana_normal as sn


def _resposta(eu=sn.DEBORA, pode_marcar=True):
    dados = sn.semana_normal()
    dados["ausencias"] += [sn.ausencia("Weber", "2026-10-21", "2026-10-25"),
                           sn.ausencia("Joana", "2026-10-28", "2026-10-28", status="pendente"),
                           sn.ausencia("Rafaela", "2026-09-01", "2026-09-30")]
    dados["idas"] += [sn.ida("2026-10-27", sn.OEIRAS, sn.DEBORA, "13:00", "22:00"),
                      sn.ida("2026-10-06", sn.PIZZARIA, "u-apagada", "10:00", "12:00"),
                      dict(sn.ida("2026-10-06", "loja-apagada", sn.CAROL, "10:00", "12:00"), id="i-orfa"),
                      sn.ida("2026-11-03", sn.OEIRAS, sn.DEBORA, "13:00", "22:00")]
    return calendario.resposta_do_mes(2026, 10, dados, eu, pode_marcar)


def test_o_cabecalho_e_os_dias_do_mes():
    r = _resposta()
    assert (r["ano"], r["mes"], r["eu"], r["pode_marcar"]) == (2026, 10, sn.DEBORA, True)
    assert len(r["dias"]) == 31 and r["dias"][0]["data"] == "2026-10-01"
    assert calendario.limites_do_mes(2026, 2) == ("2026-02-01", "2026-02-28")


def test_as_idas_do_mes_com_os_nomes_e_o_recurso_para_o_que_foi_apagado():
    idas = _resposta()["idas"]
    assert [(i["data"], i["nome"], i["loja"]) for i in idas] == [
        ("2026-10-06", "(conta removida)", "Pizzaria"),
        ("2026-10-06", "Carol Santos", "(loja removida)"),
        ("2026-10-27", "Débora Ferreira", "Oeiras"),
    ]
    assert set(idas[2]) == {"id", "data", "location_id", "user_id", "inicio", "fim", "nome", "loja"}


def test_as_ausencias_sao_so_as_aprovadas_que_tocam_o_mes():
    assert _resposta()["ausencias"] == [
        {"nome": "Weber", "tipo": "ferias", "inicio": "2026-10-21", "fim": "2026-10-25", "loja": "Amadora"}]


def test_as_lojas_sao_so_as_com_horario_por_nome():
    assert _resposta()["lojas"] == [
        {"id": sn.ALFRAGIDE, "nome": "Alfragide"}, {"id": sn.ALGUEIRAO, "nome": "Algueirão"},
        {"id": sn.AMADORA, "nome": "Amadora"}, {"id": sn.BELEM, "nome": "Belém"},
        {"id": sn.BENFICA, "nome": "Benfica"}, {"id": sn.OEIRAS, "nome": "Oeiras"}]


def test_as_pessoas_gestores_primeiro_depois_colaboradores_sem_o_contabilista():
    assert [(p["nome"], p["tipo"]) for p in _resposta()["pessoas"]] == [
        ("Carol Santos", "gestor"), ("Débora Ferreira", "gestor"), ("Guilherme Gestor", "gestor"),
        ("Beatrice", "colaborador"), ("Emanuela", "colaborador"), ("Emily", "colaborador"),
        ("Joana", "colaborador"), ("Rafaela", "colaborador"), ("Walisson", "colaborador"), ("Weber", "colaborador")]


def test_o_contabilista_le_sem_poder_marcar():
    r = _resposta(eu=sn.CONTABILISTA, pode_marcar=False)
    assert (r["eu"], r["pode_marcar"]) == (sn.CONTABILISTA, False)
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_regras_das_idas.py tests/calendario/test_resposta_do_mes.py -q
```

Esperado: `13 failed` com `AttributeError: module 'calendario' has no attribute 'validar_horas'` (e os outros nomes desta tarefa).

- [ ] **Passo 3: Implementação**

Acrescentar no fim de `backend/calendario.py`:

```python


# --- As regras de uma ida (as rotas levantam 400/409 com estes textos) ---------------------

AUSENCIAS = {"ferias": "de férias", "folga": "de folga", "doenca": "de baixa",
             "falta": "com falta marcada", "ausencia": "ausente"}


def limites_do_mes(ano: int, mes: int) -> Tuple[str, str]:
    return date(ano, mes, 1).isoformat(), date(ano, mes, monthrange(ano, mes)[1]).isoformat()


def validar_pedido(datas: List[str], user_ids: List[str]) -> Optional[str]:
    if not 1 <= len(datas) <= 31:
        return "Escolha entre 1 e 31 dias."
    if not 1 <= len(user_ids) <= 2:
        return "Escolha uma ou duas pessoas."
    if len(set(datas)) != len(datas):
        return "Há dias repetidos no pedido."
    if len(set(user_ids)) != len(user_ids):
        return "Há pessoas repetidas no pedido."
    return None


def validar_horas(inicio, fim) -> Optional[str]:
    if not all(isinstance(h, str) and _HHMM.match(h) for h in (inicio, fim)):
        return "As horas escrevem-se HH:MM (por exemplo 13:00)."
    if minutos(inicio) >= minutos(fim):
        return "A hora de fim tem de ser depois da hora de início."
    return None


def validar_ida(dia: date, loja: Optional[Dict], inicio, fim) -> Optional[str]:
    """Horas válidas; loja com horário e aberta nesse dia; horas a TOCAR no horário (as que
    saem dele aceitam-se e recortam-se no cálculo e na contagem)."""
    erro = validar_horas(inicio, fim)
    if erro:
        return erro
    if not loja:
        return "Essa loja não existe."
    nome = loja.get("name") or "A loja"
    estado, janela = horario_do_dia(loja, dia)
    quando = data_curta(dia.isoformat())
    if estado == "sem_horario":
        return "%s não tem horário e não entra no calendário." % nome
    if estado == "por_abrir":
        return "%s só abre a %s." % (nome, data_curta(loja["aberta_desde"]))
    if estado == "fechada":
        return "%s está fechada a %s. Escolha outro dia." % (nome, quando)
    if not recortar((minutos(inicio), minutos(fim)), janela):
        return "%s abre das %s às %s a %s: as horas da ida têm de tocar nesse horário." % (
            nome, hora_curta(hhmm(janela[0])), hora_curta(hhmm(janela[1])), quando)
    return None


def choques(novas: List[Dict], existentes: List[Dict], ignorar_id: Optional[str] = None) -> List[Tuple[Dict, Dict]]:
    """Pares (nova, existente) da MESMA pessoa no MESMO dia com horas sobrepostas — ninguém
    está em dois sítios ao mesmo tempo. Horas encostadas (13h–17h e 17h–22h) não chocam."""
    pares = []
    for nova in novas:
        horas = (minutos(nova["inicio"]), minutos(nova["fim"]))
        for outra in existentes:
            if ignorar_id and outra.get("id") == ignorar_id:
                continue
            if (outra["user_id"] == nova["user_id"] and outra["data"] == nova["data"]
                    and recortar(horas, (minutos(outra["inicio"]), minutos(outra["fim"])))):
                pares.append((nova, outra))
    return pares


def mensagem_de_choque(nova: Dict, outra: Dict, utilizadores: Dict[str, Dict], nomes_lojas: Dict[str, str]) -> str:
    # Sem artigo («Débora já está…», não «A Débora…»): o RH não guarda o género.
    return "%s já está em %s das %s às %s a %s." % (
        primeiro_nome((utilizadores.get(nova["user_id"]) or {}).get("name")) or "Esta pessoa",
        nomes_lojas.get(outra["location_id"]) or NOME_SEM_LOJA,
        hora_curta(outra["inicio"]), hora_curta(outra["fim"]), data_curta(outra["data"]))


def ausencias_que_impedem(novas: List[Dict], utilizadores: Dict[str, Dict], ausencias: List[Dict]) -> List[str]:
    """Um colaborador não se marca num dia em que tem ausência APROVADA (os gestores não têm
    ficha nem ausências no RH)."""
    linhas = []
    for nova in novas:
        user = utilizadores.get(nova["user_id"]) or {}
        if user.get("role") != "colaborador":
            continue
        for a in ausencias:
            if (a.get("employee_id") == user.get("employee_id") and a.get("status") == "aprovado"
                    and (a.get("start_date") or "")[:10] <= nova["data"] <= (a.get("end_date") or "")[:10]):
                linha = "%s está %s a %s." % (primeiro_nome(user.get("name")),
                                              AUSENCIAS.get(a.get("leave_type"), "ausente"), data_curta(nova["data"]))
                if linha not in linhas:
                    linhas.append(linha)
                break
    return linhas


# --- A resposta do mês (GET /api/bolso/calendario) -----------------------------------------


def pessoas_escalaveis(utilizadores: List[Dict]) -> List[Dict]:
    """Quem pode ser escalado numa ida: gestores primeiro, depois colaboradores, por nome.
    O contabilista lê o calendário mas não pode ser escalado."""
    escolhidas = [u for u in utilizadores if u.get("role") in ESCALAVEIS]
    escolhidas.sort(key=lambda u: (u.get("role") not in GESTORES, (u.get("name") or "").lower()))
    return [{"id": u["id"], "nome": u.get("name") or NOME_SEM_CONTA,
             "tipo": "gestor" if u.get("role") in GESTORES else "colaborador"} for u in escolhidas]


def resposta_do_mes(ano: int, mes: int, dados: Dict, eu: Optional[str], pode_marcar: bool) -> Dict:
    """O mês inteiro, como o ecrã o lê. `idas[]` leva as idas do mês com os nomes — é daqui
    que se montam a vista Pessoal e as idas da Lista (uma ida numa loja que entretanto perdeu
    o horário continua a aparecer aqui, e não em `dias`)."""
    inicio, fim = limites_do_mes(ano, mes)
    lojas = {l["id"]: l for l in dados.get("lojas", [])}
    utilizadores = {u["id"]: u for u in dados.get("utilizadores", [])}
    empregados = {e["id"]: e for e in dados.get("empregados", [])}
    idas = sorted((i for i in dados.get("idas", []) if inicio <= i["data"] <= fim),
                  key=lambda i: (i["data"], i["inicio"]))
    ausencias = sorted((a for a in dados.get("ausencias", [])
                        if a.get("status") == "aprovado"
                        and (a.get("start_date") or "")[:10] <= fim and (a.get("end_date") or "")[:10] >= inicio),
                       key=lambda a: a.get("start_date") or "")

    def _ficha(a):
        return empregados.get(a.get("employee_id")) or {}

    return {
        "ano": ano, "mes": mes, "eu": eu, "pode_marcar": pode_marcar,
        "dias": calendario_do_mes(ano, mes, dados),
        "idas": [{"id": i.get("id"), "data": i["data"], "location_id": i.get("location_id"),
                  "user_id": i.get("user_id"), "inicio": i["inicio"], "fim": i["fim"],
                  "nome": (utilizadores.get(i.get("user_id")) or {}).get("name") or NOME_SEM_CONTA,
                  "loja": (lojas.get(i.get("location_id")) or {}).get("name") or NOME_SEM_LOJA}
                 for i in idas],
        "ausencias": [{"nome": _ficha(a).get("name") or NOME_SEM_CONTA, "tipo": a.get("leave_type"),
                       "inicio": (a.get("start_date") or "")[:10], "fim": (a.get("end_date") or "")[:10],
                       "loja": (lojas.get(_ficha(a).get("location_id")) or {}).get("name")}
                      for a in ausencias],
        "lojas": [{"id": l["id"], "nome": l.get("name")}
                  for l in sorted(lojas.values(), key=lambda l: (l.get("name") or "").lower()) if l.get("horario")],
        "pessoas": pessoas_escalaveis(dados.get("utilizadores", [])),
    }
```

- [ ] **Passo 4: Correr e ver passar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_regras_das_idas.py tests/calendario/test_resposta_do_mes.py tests/calendario/test_contagem.py tests/calendario/test_outubro.py tests/calendario/test_a_semana_normal.py tests/calendario/test_intervalos_e_horario.py tests/calendario/test_feriados.py -q
```

Esperado: `57 passed`.

- [ ] **Passo 5: Prova por mutação**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PY=~/Developer/RH/backend/.venv/bin/python
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py calendario.py 'if not recortar((minutos(inicio), minutos(fim)), janela):' 'if False:' -- $PY -m pytest tests/calendario/test_regras_das_idas.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py calendario.py 'if ignorar_id and outra.get("id") == ignorar_id:' 'if False:' -- $PY -m pytest tests/calendario/test_regras_das_idas.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py calendario.py '(a.get("start_date") or "")[:10] <= fim and (a.get("end_date") or "")[:10] >= inicio' 'True' -- $PY -m pytest tests/calendario/test_resposta_do_mes.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py calendario.py 'key=lambda u: (u.get("role") not in GESTORES, (u.get("name") or "").lower())' 'key=lambda u: (u.get("name") or "").lower()' -- $PY -m pytest tests/calendario/test_resposta_do_mes.py -q
```

Esperado: (1) `FAILED …test_as_horas_tem_de_tocar_no_horario…`; (2) `FAILED …test_a_mesma_pessoa_nao_esta_em_dois_sitios…`; (3) `FAILED …test_as_ausencias_sao_so_as_aprovadas_que_tocam_o_mes` (a Rafaela de setembro aparece); (4) `FAILED …test_as_pessoas_gestores_primeiro…`. Todas com «Mutação apanhada».

- [ ] **Passo 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add backend/calendario.py backend/tests/calendario/test_regras_das_idas.py backend/tests/calendario/test_resposta_do_mes.py
git commit -m "Calendário: as regras de uma ida e a resposta do mês, ainda sem rotas

Uma ida só se marca numa loja aberta nesse dia e com horas que toquem no horário, a
mesma pessoa não fica em dois sítios ao mesmo tempo e um colaborador de férias não se
marca; os textos dizem o que aconteceu («Débora já está em Alfragide das 10h às 14h a
21/10.»). A resposta do mês junta os dias, as idas com nomes, as ausências aprovadas, as
lojas e as pessoas que se podem escalar.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Tarefa 6: As rotas de leitura — o mês e a contagem, e os índices das idas

**Ficheiros:**
- Modificar: `backend/server.py` — linha `import bolso` (~44); bloco novo imediatamente antes de `@api_router.post("/fin/cron/faturacao")` (~8657, logo a seguir ao `return` do `bolso_painel`); `startup_event` (~9747-9748, a seguir ao `except` dos índices do Financeiro)
- Testes: `backend/tests/calendario/test_rotas_de_leitura.py` (criar)

**Interfaces:**
- Consome: `calendario.limites_do_mes`, `calendario.resposta_do_mes`, `calendario.contagem`, `calendario.GESTORES` (Tarefas 4-5); `server.admin_manager_required`; fixtures `base` (Fase 1, base Motor limpa posta em `server.db`) e `corre` (`tests/calendario/apoio.py`); `dados_semana_normal.gravar`.
- Produz:
  - `server._BOLSO_CAMPOS_DA_LOJA: dict` (projecção `id, name, company_id, horario, aberta_desde`)
  - `async server._bolso_criar_indices() -> None` (índice único `(data, user_id, location_id, inicio)` e índice `data` em `bolso_idas`)
  - `GET /api/bolso/calendario?ano=&mes=` → `server.bolso_calendario(ano: int, mes: int, current_user) -> dict` (a forma de `resposta_do_mes`)
  - `GET /api/bolso/calendario/contagem?ano=` → `server.bolso_calendario_contagem(ano: int, current_user) -> list` (a forma de `contagem`)

- [ ] **Passo 1: Escrever os testes que falham**

`backend/tests/calendario/test_rotas_de_leitura.py`:

```python
"""`GET /api/bolso/calendario` e `/contagem` contra um mongod REAL, com os dados da semana
normal (desenho, secção 3). As rotas chamam-se directamente, como no resto da casa."""
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")
os.environ.setdefault("JWT_SECRET", "segredo-de-teste")
os.environ.setdefault("POS_JWT_SECRET", "segredo-de-teste-pos")

import pytest  # noqa: E402

import server  # noqa: E402

from . import dados_semana_normal as sn  # noqa: E402
from .apoio import corre  # noqa: E402

DEBORA = {"user_id": sn.DEBORA, "role": "admin"}
CONTABILISTA = {"user_id": sn.CONTABILISTA, "role": "contabilista"}


@pytest.fixture
def semana(base):
    dados = sn.semana_normal()
    dados["ausencias"].append(sn.ausencia("Weber", "2026-10-21", "2026-10-25"))
    dados["idas"].append(sn.ida("2026-10-27", sn.OEIRAS, sn.DEBORA, "13:00", "22:00"))
    corre(sn.gravar(base, dados))
    corre(server._bolso_criar_indices())
    return base


def _loja(resposta, data, nome):
    dia = next(d for d in resposta["dias"] if d["data"] == data)
    return next(l for l in dia["lojas"] if l["nome"] == nome)


def test_o_mes_no_servidor_tem_os_buracos_as_ferias_e_as_idas(semana):
    r = corre(server.bolso_calendario(ano=2026, mes=10, current_user=DEBORA))
    assert (r["ano"], r["mes"], r["eu"], r["pode_marcar"]) == (2026, 10, sn.DEBORA, True)
    assert _loja(r, "2026-10-20", "Oeiras")["buracos"] == [{"inicio": "13:00", "fim": "22:00"}]
    assert _loja(r, "2026-10-27", "Oeiras")["buracos"] == []
    assert _loja(r, "2026-10-22", "Amadora")["buracos"] == [{"inicio": "14:00", "fim": "23:00"}]
    assert r["ausencias"] == [{"nome": "Weber", "tipo": "ferias", "inicio": "2026-10-21",
                               "fim": "2026-10-25", "loja": "Amadora"}]
    assert [(i["data"], i["nome"], i["loja"]) for i in r["idas"]] == [("2026-10-27", "Débora Ferreira", "Oeiras")]
    assert [l["nome"] for l in r["lojas"]] == ["Alfragide", "Algueirão", "Amadora", "Belém", "Benfica", "Oeiras"]


def test_o_contabilista_le_o_mes_mas_nao_pode_marcar(semana):
    r = corre(server.bolso_calendario(ano=2026, mes=10, current_user=CONTABILISTA))
    assert r["pode_marcar"] is False
    assert sn.CONTABILISTA not in [p["id"] for p in r["pessoas"]]


def test_a_contagem_e_do_ano_pedido(semana):
    corre(semana.bolso_idas.insert_one(sn.ida("2026-11-03", sn.ALFRAGIDE, sn.DEBORA, "10:00", "14:00")))
    corre(semana.bolso_idas.insert_one(sn.ida("2025-12-30", sn.OEIRAS, sn.DEBORA, "13:00", "22:00")))
    [linha] = corre(server.bolso_calendario_contagem(ano=2026, current_user=CONTABILISTA))
    assert linha["nome"] == "Débora Ferreira"
    assert linha["meses"][9:] == [1.0, 0.5, 0.0]
    assert linha["total"] == 1.5


def test_os_indices_das_idas(semana):
    indices = corre(semana.bolso_idas.index_information())
    assert [i["key"] for i in indices.values() if i.get("unique")] == [
        [("data", 1), ("user_id", 1), ("location_id", 1), ("inicio", 1)]]
    assert [("data", 1)] in [i["key"] for i in indices.values()]
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_rotas_de_leitura.py -q
```

Esperado: `4 errors` na fixture com `AttributeError: module 'server' has no attribute '_bolso_criar_indices'`. Se vier `4 skipped` («sem mongod nesta máquina»), PARAR: estes testes têm de correr (`/opt/homebrew/bin/mongod` existe neste Mac).

- [ ] **Passo 3: Implementação**

Em `backend/server.py`, a seguir à linha `import bolso` (~44), acrescentar:

```python
import calendario
```

Imediatamente antes da linha `@api_router.post("/fin/cron/faturacao")` (~8657), acrescentar:

```python
# ====================================================================
# ===== CALENDÁRIO DAS LOJAS — onde falta gente, no telemóvel =====
# ====================================================================
# O cálculo é todo do módulo `calendario` (puro, testável sem Mongo); aqui ficam as
# leituras e as guardas. Os buracos NÃO se guardam: calculam-se a cada pedido, a partir
# do horário das lojas, da escala de cada pessoa, das ausências aprovadas e das idas
# (`bolso_idas`) — por isso nunca ficam desactualizados.
# Desenho: docs/superpowers/specs/2026-10-14-calendario-gestao-design.md, secção 3.

_BOLSO_CAMPOS_DA_LOJA = {"_id": 0, "id": 1, "name": 1, "company_id": 1, "horario": 1, "aberta_desde": 1}


async def _bolso_criar_indices():
    """O índice único apanha a MESMA ida gravada duas vezes (duas gestoras no mesmo
    segundo) — é com ele que o «tudo ou nada» do POST se compensa; o de `data` serve a
    leitura do mês. `create_index` é idempotente."""
    await db.bolso_idas.create_index(
        [("data", 1), ("user_id", 1), ("location_id", 1), ("inicio", 1)], unique=True)
    await db.bolso_idas.create_index([("data", 1)])


@api_router.get("/bolso/calendario")
async def bolso_calendario(
    ano: int = Query(..., ge=2020, le=2100),
    mes: int = Query(..., ge=1, le=12),
    current_user: dict = Depends(admin_manager_required),
):
    """O mês inteiro num pedido (forma em `calendario.resposta_do_mes`).

    Consultas fixas e sem ciclos — o `GET /calendar/leaves` faz uma consulta por ausência e
    é exactamente o que aqui não se copia. O contabilista lê (`pode_marcar: false`)."""
    inicio, fim = calendario.limites_do_mes(ano, mes)
    dados = {
        "lojas": await db.locations.find({}, _BOLSO_CAMPOS_DA_LOJA).to_list(1000),
        "empregados": await db.employees.find(
            {}, {"_id": 0, "id": 1, "name": 1, "location_id": 1, "company_id": 1}).to_list(5000),
        "atribuicoes": await db.work_schedule_assignments.find(
            {"start_date": {"$lte": fim}}, {"_id": 0}).to_list(20000),
        "modelos": await db.work_schedule_templates.find(
            {}, {"_id": 0, "id": 1, "work_days": 1, "dias": 1}).to_list(5000),
        "ausencias": await db.leave_requests.find(
            {"status": "aprovado", "start_date": {"$lte": fim}, "end_date": {"$gte": inicio}},
            {"_id": 0, "employee_id": 1, "leave_type": 1, "start_date": 1, "end_date": 1, "status": 1},
        ).to_list(5000),
        "idas": await db.bolso_idas.find({"data": {"$gte": inicio, "$lte": fim}}, {"_id": 0}).to_list(20000),
        "utilizadores": await db.users.find(
            {}, {"_id": 0, "id": 1, "name": 1, "role": 1, "employee_id": 1}).to_list(5000),
        "feriados": await db.holidays.find(
            {}, {"_id": 0, "name": 1, "month": 1, "day": 1, "company_id": 1, "location_id": 1}).to_list(500),
    }
    return calendario.resposta_do_mes(
        ano, mes, dados, current_user.get("user_id"), current_user.get("role") in calendario.GESTORES)


@api_router.get("/bolso/calendario/contagem")
async def bolso_calendario_contagem(
    ano: int = Query(..., ge=2020, le=2100),
    current_user: dict = Depends(admin_manager_required),
):
    """Quantos dias cada pessoa fez no ano — as idas marcadas, futuras incluídas (é o que
    as gestoras usam para se equilibrarem)."""
    idas = await db.bolso_idas.find(
        {"data": {"$gte": "%d-01-01" % ano, "$lte": "%d-12-31" % ano}},
        {"_id": 0, "data": 1, "user_id": 1, "location_id": 1, "inicio": 1, "fim": 1},
    ).to_list(50000)
    lojas = {l["id"]: l for l in await db.locations.find({}, _BOLSO_CAMPOS_DA_LOJA).to_list(1000)}
    utilizadores = await db.users.find(
        {"id": {"$in": sorted({i["user_id"] for i in idas})}}, {"_id": 0, "id": 1, "name": 1}
    ).to_list(5000)
    return calendario.contagem(idas, lojas, {u["id"]: u.get("name") for u in utilizadores})


```

No `startup_event`, a seguir a

```python
    except Exception:  # noqa: BLE001
        logger.warning("[fin] não foi possível criar os índices de fin_sales/bol_leituras")
```

acrescentar:

```python

    # O índice único das idas é o que torna o «tudo ou nada» do calendário possível sem
    # transacções. À parte do de cima: uma falha num não pode deixar o outro por criar.
    try:
        await _bolso_criar_indices()
    except Exception:  # noqa: BLE001
        logger.warning("[bolso] não foi possível criar os índices de bolso_idas")
```

- [ ] **Passo 4: Correr e ver passar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_rotas_de_leitura.py tests/fin/test_caminhos_do_bolso.py -q
```

Esperado: `7 passed` (4 novos + os 3 do guarda de caminhos, que continua verde).

- [ ] **Passo 5: Prova por mutação**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PY=~/Developer/RH/backend/.venv/bin/python
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py server.py 'ano, mes, dados, current_user.get("user_id"), current_user.get("role") in calendario.GESTORES)' 'ano, mes, dados, current_user.get("user_id"), True)' -- $PY -m pytest tests/calendario/test_rotas_de_leitura.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py server.py '{"data": {"$gte": "%d-01-01" % ano, "$lte": "%d-12-31" % ano}},' '{},' -- $PY -m pytest tests/calendario/test_rotas_de_leitura.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py server.py '[("data", 1), ("user_id", 1), ("location_id", 1), ("inicio", 1)], unique=True)' '[("data", 1), ("user_id", 1), ("location_id", 1), ("inicio", 1)])' -- $PY -m pytest tests/calendario/test_rotas_de_leitura.py -q
```

Esperado: (1) `FAILED …test_o_contabilista_le_o_mes_mas_nao_pode_marcar`; (2) `FAILED …test_a_contagem_e_do_ano_pedido` (a ida de 30/12/2025 entra em dezembro); (3) `FAILED …test_os_indices_das_idas`. Todas com «Mutação apanhada».

- [ ] **Passo 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add backend/server.py backend/tests/calendario/test_rotas_de_leitura.py
git commit -m "Calendário: rotas do mês e da contagem no bolso, com os índices das idas

O ecrã pede o mês inteiro num pedido, com consultas fixas e sem ciclos, e o servidor
calcula os buracos nesse momento a partir das lojas, escalas, ausências aprovadas e
idas. O contabilista lê mas não marca. O índice único das idas prepara o tudo-ou-nada
de quem marca ao mesmo tempo.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Tarefa 7: As rotas de escrita — marcar, mudar e apagar idas, tudo ou nada, e a porta

**Ficheiros:**
- Modificar: `backend/server.py` — imports (~6, a seguir a `from motor.motor_asyncio import AsyncIOMotorClient`); bloco novo imediatamente antes de `@api_router.post("/fin/cron/faturacao")` (fica a seguir ao `bolso_calendario_contagem` da Tarefa 6)
- Testes: `backend/tests/calendario/test_rotas_de_escrita.py` (criar)

**Interfaces:**
- Consome: `calendario.validar_pedido`, `validar_ida`, `ausencias_que_impedem`, `choques`, `mensagem_de_choque`, `GESTORES`, `ESCALAVEIS` (Tarefa 5); `server._BOLSO_CAMPOS_DA_LOJA`, `server._bolso_criar_indices` (Tarefa 6); `server.admin_manager_required`; fixtures `base`/`corre` (Fase 1).
- Produz:
  - `server.BolsoIdasIn` (`datas: List[date]`, `location_id: str`, `user_ids: List[str]`, `inicio: str`, `fim: str`) e `server.BolsoIdaIn` (`data: date`, `location_id`, `user_id`, `inicio`, `fim`)
  - `async server.bolso_quem_marca(current_user=Depends(admin_manager_required)) -> dict` (403 «Só os gestores marcam idas.» a quem não é `admin`/`gerente`)
  - `async server._bolso_validar_idas(novas: List[dict], ignorar_id: Optional[str] = None) -> None` (levanta 400/409; `detail` = linhas separadas por `\n`)
  - `POST /api/bolso/calendario/idas` → `server.bolso_criar_idas(corpo, current_user) -> {"criadas": int, "ids": [str]}`
  - `PUT /api/bolso/calendario/idas/{ida_id}` → `server.bolso_mudar_ida(ida_id, corpo, current_user) -> dict` (a ida mudada)
  - `DELETE /api/bolso/calendario/idas/{ida_id}` → `server.bolso_apagar_ida(ida_id, current_user) -> {"apagada": ida_id}`

- [ ] **Passo 1: Escrever os testes que falham**

`backend/tests/calendario/test_rotas_de_escrita.py`:

```python
"""Marcar, mudar e apagar idas contra um mongod REAL (desenho, secção 3, e Testes 7 e 8):
as regras, o «tudo ou nada» e a porta. O índice único e a compensação só se medem aqui."""
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")
os.environ.setdefault("JWT_SECRET", "segredo-de-teste")
os.environ.setdefault("POS_JWT_SECRET", "segredo-de-teste-pos")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import calendario  # noqa: E402
import server  # noqa: E402

from . import dados_semana_normal as sn  # noqa: E402
from .apoio import corre  # noqa: E402

DEBORA = {"user_id": sn.DEBORA, "role": "admin"}
GERENTE = {"user_id": sn.GERENTE, "role": "gerente"}
CONTABILISTA = {"user_id": sn.CONTABILISTA, "role": "contabilista"}
COLABORADORA = {"user_id": sn.user("Joana"), "role": "colaborador"}


@pytest.fixture
def semana(base):
    dados = sn.semana_normal()
    dados["ausencias"].append(sn.ausencia("Weber", "2026-10-21", "2026-10-25"))
    corre(sn.gravar(base, dados))
    corre(server._bolso_criar_indices())
    return base


def _criar(quem=DEBORA, **corpo):
    return corre(server.bolso_criar_idas(server.BolsoIdasIn(**corpo), current_user=quem))


def _recusa(coro):
    with pytest.raises(HTTPException) as erro:
        corre(coro)
    return erro.value.status_code, erro.value.detail


def _idas(db):
    return corre(db.bolso_idas.find({}, {"_id": 0}).sort([("data", 1), ("user_id", 1)]).to_list(100))


def test_varias_datas_e_duas_pessoas_criam_uma_ida_por_data_e_por_pessoa(semana):
    r = _criar(datas=["2026-10-13", "2026-10-06", "2026-10-20"], location_id=sn.OEIRAS,
               user_ids=[sn.DEBORA, sn.CAROL], inicio="13:00", fim="22:00")
    assert r["criadas"] == 6
    idas = _idas(semana)
    assert [(i["data"], i["user_id"]) for i in idas] == [
        (d, u) for d in ("2026-10-06", "2026-10-13", "2026-10-20") for u in (sn.CAROL, sn.DEBORA)]
    assert {(i["location_id"], i["inicio"], i["fim"], i["criado_por"]) for i in idas} == {
        (sn.OEIRAS, "13:00", "22:00", sn.DEBORA)}
    assert sorted(r["ids"]) == sorted(i["id"] for i in idas)


def test_o_gerente_tambem_marca_e_pode_escalar_um_colaborador(semana):
    assert _criar(GERENTE, datas=["2026-10-31"], location_id=sn.BENFICA, user_ids=[sn.user("Joana")],
                  inicio="13:00", fim="22:00")["criadas"] == 1


def test_um_choque_so_na_ultima_data_nao_grava_nenhuma(semana):
    _criar(datas=["2026-10-27"], location_id=sn.ALFRAGIDE, user_ids=[sn.DEBORA], inicio="10:00", fim="14:00")
    estado, texto = _recusa(server.bolso_criar_idas(server.BolsoIdasIn(
        datas=["2026-10-06", "2026-10-13", "2026-10-20", "2026-10-27"], location_id=sn.OEIRAS,
        user_ids=[sn.DEBORA], inicio="13:00", fim="22:00"), current_user=DEBORA))
    assert estado == 409
    assert texto.splitlines() == ["Débora já está em Alfragide das 10h às 14h a 27/10.",
                                  "Mude as horas ou apague primeiro a outra ida."]
    assert len(_idas(semana)) == 1


def test_horas_encostadas_nao_chocam(semana):
    _criar(datas=["2026-10-27"], location_id=sn.ALFRAGIDE, user_ids=[sn.DEBORA], inicio="10:00", fim="14:00")
    assert _criar(datas=["2026-10-27"], location_id=sn.OEIRAS, user_ids=[sn.DEBORA],
                  inicio="14:00", fim="22:00")["criadas"] == 1


def test_um_colaborador_de_ferias_nao_se_marca(semana):
    estado, texto = _recusa(server.bolso_criar_idas(server.BolsoIdasIn(
        datas=["2026-10-20", "2026-10-22"], location_id=sn.AMADORA, user_ids=[sn.user("Weber")],
        inicio="14:00", fim="23:00"), current_user=DEBORA))
    assert estado == 409
    assert texto.splitlines()[0] == "Weber está de férias a 22/10."
    assert _idas(semana) == []


@pytest.mark.parametrize("corpo, pedaco", [
    ({"user_ids": [sn.CONTABILISTA]}, "podem ser escalados"),
    ({"user_ids": ["nao-existe"]}, "podem ser escalados"),
    ({"location_id": "loja-que-nao-existe"}, "Essa loja não existe."),
    ({"location_id": sn.PIZZARIA}, "não tem horário"),
    ({"location_id": sn.BELEM}, "Belém está fechada a 27/10."),
    ({"datas": ["2026-10-21"], "location_id": sn.BENFICA}, "Benfica só abre a 24/10."),
    ({"inicio": "08:00", "fim": "12:00"}, "têm de tocar nesse horário"),
    ({"inicio": "9:00"}, "HH:MM"),
    ({"inicio": "22:00", "fim": "13:00"}, "depois da hora de início"),
    ({"datas": ["2026-10-27", "2026-10-27"]}, "dias repetidos"),
    ({"user_ids": [sn.DEBORA, sn.DEBORA]}, "pessoas repetidas"),
    ({"user_ids": [sn.DEBORA, sn.CAROL, sn.GERENTE]}, "uma ou duas pessoas"),
    ({"datas": []}, "entre 1 e 31 dias"),
])
def test_pedidos_errados_dao_400_e_nao_gravam(semana, corpo, pedaco):
    pedido = dict(datas=["2026-10-27"], location_id=sn.OEIRAS, user_ids=[sn.DEBORA], inicio="13:00", fim="22:00")
    pedido.update(corpo)
    estado, texto = _recusa(server.bolso_criar_idas(server.BolsoIdasIn(**pedido), current_user=DEBORA))
    assert estado == 400
    assert pedaco in texto
    assert _idas(semana) == []


def test_o_tudo_ou_nada_compensa_quando_o_indice_unico_dispara(semana, monkeypatch):
    """A janela entre verificar e gravar: outra gestora grava a MESMA ida no mesmo segundo.
    Simula-se desligando a verificação; quem apanha é o índice único, e o pedido tem de
    apagar o que já tinha gravado."""
    corre(semana.bolso_idas.insert_one(
        dict(sn.ida("2026-10-20", sn.OEIRAS, sn.DEBORA, "13:00", "22:00"), id="da-outra-gestora")))
    monkeypatch.setattr(calendario, "choques", lambda *a, **k: [])
    estado, texto = _recusa(server.bolso_criar_idas(server.BolsoIdasIn(
        datas=["2026-10-06", "2026-10-13", "2026-10-20"], location_id=sn.OEIRAS,
        user_ids=[sn.DEBORA], inicio="13:00", fim="22:00"), current_user=DEBORA))
    assert estado == 409
    assert "Nada foi gravado" in texto
    assert [i["id"] for i in _idas(semana)] == ["da-outra-gestora"]


def test_mudar_uma_ida_que_choca_da_409_mas_nao_choca_consigo(semana):
    _criar(datas=["2026-10-27"], location_id=sn.ALFRAGIDE, user_ids=[sn.DEBORA], inicio="10:00", fim="14:00")
    [oeiras] = _criar(datas=["2026-10-27"], location_id=sn.OEIRAS, user_ids=[sn.DEBORA],
                      inicio="14:00", fim="22:00")["ids"]
    estado, texto = _recusa(server.bolso_mudar_ida(oeiras, server.BolsoIdaIn(
        data="2026-10-27", location_id=sn.OEIRAS, user_id=sn.DEBORA, inicio="13:00", fim="22:00"),
        current_user=DEBORA))
    assert (estado, texto.splitlines()[0]) == (409, "Débora já está em Alfragide das 10h às 14h a 27/10.")
    r = corre(server.bolso_mudar_ida(oeiras, server.BolsoIdaIn(
        data="2026-10-27", location_id=sn.OEIRAS, user_id=sn.DEBORA, inicio="15:00", fim="22:00"),
        current_user=GERENTE))
    assert (r["inicio"], r["alterado_por"]) == ("15:00", sn.GERENTE)


def test_mudar_e_apagar_mexem_so_na_ida_certa(semana):
    ids = _criar(datas=["2026-10-06", "2026-10-13"], location_id=sn.OEIRAS, user_ids=[sn.DEBORA],
                 inicio="13:00", fim="22:00")["ids"]
    corre(server.bolso_mudar_ida(ids[0], server.BolsoIdaIn(
        data="2026-10-07", location_id=sn.ALFRAGIDE, user_id=sn.CAROL, inicio="19:00", fim="23:00"),
        current_user=DEBORA))
    corre(server.bolso_apagar_ida(ids[1], current_user=DEBORA))
    assert [(i["id"], i["data"], i["location_id"], i["user_id"], i["inicio"]) for i in _idas(semana)] == [
        (ids[0], "2026-10-07", sn.ALFRAGIDE, sn.CAROL, "19:00")]


def test_mudar_ou_apagar_uma_ida_que_ja_nao_existe_da_404(semana):
    corpo = server.BolsoIdaIn(data="2026-10-27", location_id=sn.OEIRAS, user_id=sn.DEBORA, inicio="13:00", fim="22:00")
    assert _recusa(server.bolso_mudar_ida("nao-existe", corpo, current_user=DEBORA))[0] == 404
    assert _recusa(server.bolso_apagar_ida("nao-existe", current_user=DEBORA))[0] == 404


# --- A porta (Testes 8) --------------------------------------------------------------------


def _rota(caminho, metodo):
    achadas = [r for r in server.app.routes
               if getattr(r, "path", None) == caminho and metodo in getattr(r, "methods", ())]
    assert len(achadas) == 1, "%s %s: %d rotas" % (metodo, caminho, len(achadas))
    return achadas[0]


def _dependencias(rota):
    encontradas = []

    def _procura(dependente):
        for d in dependente.dependencies:
            encontradas.append(d.call)
            _procura(d)

    _procura(rota.dependant)
    return encontradas


@pytest.mark.parametrize("metodo, caminho", [
    ("GET", "/api/bolso/calendario"), ("GET", "/api/bolso/calendario/contagem")])
def test_ler_e_para_gestores_e_contabilista(metodo, caminho):
    deps = _dependencias(_rota(caminho, metodo))
    assert server.admin_manager_required in deps
    assert server.bolso_quem_marca not in deps


@pytest.mark.parametrize("metodo, caminho", [
    ("POST", "/api/bolso/calendario/idas"), ("PUT", "/api/bolso/calendario/idas/{ida_id}"),
    ("DELETE", "/api/bolso/calendario/idas/{ida_id}")])
def test_escrever_e_so_para_admin_e_gerente(metodo, caminho):
    deps = _dependencias(_rota(caminho, metodo))
    assert server.bolso_quem_marca in deps
    assert server.admin_manager_required in deps


def test_o_contabilista_leva_403_a_escrever_e_o_colaborador_a_tudo(semana):
    assert _recusa(server.bolso_quem_marca(current_user=dict(CONTABILISTA)))[0] == 403
    assert _recusa(server.admin_manager_required(current_user=dict(COLABORADORA)))[0] == 403
    assert corre(server.bolso_quem_marca(current_user=dict(DEBORA)))["role"] == "admin"
    assert corre(server.bolso_quem_marca(current_user=dict(GERENTE)))["role"] == "gerente"
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_rotas_de_escrita.py -q
```

Esperado: todos vermelhos — `AttributeError: module 'server' has no attribute 'BolsoIdasIn'` / `'bolso_quem_marca'`, e `AssertionError: POST /api/bolso/calendario/idas: 0 rotas` nos da porta; só os dois `test_ler_e_para_gestores_e_contabilista` falham em `server.bolso_quem_marca` (o atributo ainda não existe).

- [ ] **Passo 3: Implementação**

Em `backend/server.py`, a seguir a `from motor.motor_asyncio import AsyncIOMotorClient` (~6), acrescentar:

```python
from pymongo.errors import DuplicateKeyError
```

Imediatamente antes da linha `@api_router.post("/fin/cron/faturacao")` (agora a seguir ao `bolso_calendario_contagem`), acrescentar:

```python
class BolsoIdasIn(BaseModel):
    datas: List[date]
    location_id: str
    user_ids: List[str]
    inicio: str
    fim: str


class BolsoIdaIn(BaseModel):
    data: date
    location_id: str
    user_id: str
    inicio: str
    fim: str


async def bolso_quem_marca(current_user: dict = Depends(admin_manager_required)):
    """Escrever no calendário: administradores e gestores. O contabilista lê e não marca."""
    if current_user.get("role") not in calendario.GESTORES:
        raise HTTPException(status_code=403, detail="Só os gestores marcam idas.")
    return current_user


async def _bolso_validar_idas(novas: List[dict], ignorar_id: Optional[str] = None) -> None:
    """As regras de uma ida, para todas as do pedido de uma vez: levanta 400/409 com a
    lista dos problemas, ou não levanta nada. Não grava."""
    lojas = {l["id"]: l for l in await db.locations.find(
        {"id": {"$in": sorted({n["location_id"] for n in novas})}}, _BOLSO_CAMPOS_DA_LOJA).to_list(100)}
    erros = []
    for nova in novas:
        erro = calendario.validar_ida(
            date.fromisoformat(nova["data"]), lojas.get(nova["location_id"]), nova["inicio"], nova["fim"])
        if erro and erro not in erros:
            erros.append(erro)
    if erros:
        raise HTTPException(status_code=400, detail="\n".join(erros))

    ids = sorted({n["user_id"] for n in novas})
    pessoas = {u["id"]: u for u in await db.users.find(
        {"id": {"$in": ids}}, {"_id": 0, "id": 1, "name": 1, "role": 1, "employee_id": 1}).to_list(100)}
    if any((pessoas.get(i) or {}).get("role") not in calendario.ESCALAVEIS for i in ids):
        raise HTTPException(
            status_code=400, detail="Só administradores, gestores e colaboradores podem ser escalados.")

    datas = sorted({n["data"] for n in novas})
    fichas = [u["employee_id"] for u in pessoas.values() if u.get("role") == "colaborador" and u.get("employee_id")]
    if fichas:
        ausencias = await db.leave_requests.find(
            {"employee_id": {"$in": fichas}, "status": "aprovado",
             "start_date": {"$lte": datas[-1]}, "end_date": {"$gte": datas[0]}},
            {"_id": 0, "employee_id": 1, "leave_type": 1, "start_date": 1, "end_date": 1, "status": 1},
        ).to_list(1000)
        impedidas = calendario.ausencias_que_impedem(novas, pessoas, ausencias)
        if impedidas:
            raise HTTPException(status_code=409, detail="\n".join(impedidas + ["Escolha outra pessoa ou outro dia."]))

    # A sobreposição verifica-se com UMA consulta e compara-se em memória.
    existentes = await db.bolso_idas.find({"user_id": {"$in": ids}, "data": {"$in": datas}}, {"_id": 0}).to_list(1000)
    pares = calendario.choques(novas, existentes, ignorar_id)
    if pares:
        nomes = {l["id"]: l.get("name") for l in await db.locations.find(
            {"id": {"$in": sorted({outra["location_id"] for _, outra in pares})}},
            {"_id": 0, "id": 1, "name": 1}).to_list(100)}
        linhas = []
        for nova, outra in pares:
            linha = calendario.mensagem_de_choque(nova, outra, pessoas, nomes)
            if linha not in linhas:
                linhas.append(linha)
        raise HTTPException(status_code=409, detail="\n".join(linhas + ["Mude as horas ou apague primeiro a outra ida."]))


@api_router.post("/bolso/calendario/idas")
async def bolso_criar_idas(corpo: BolsoIdasIn, current_user: dict = Depends(bolso_quem_marca)):
    """Uma ida por data e por pessoa — tudo ou nada."""
    datas = [d.isoformat() for d in corpo.datas]
    erro = calendario.validar_pedido(datas, corpo.user_ids)
    if erro:
        raise HTTPException(status_code=400, detail=erro)
    agora = datetime.now(timezone.utc).isoformat()
    novas = [
        {"id": str(uuid.uuid4()), "data": d, "location_id": corpo.location_id, "user_id": u,
         "inicio": corpo.inicio, "fim": corpo.fim,
         "criado_por": current_user.get("user_id"), "criado_em": agora,
         "alterado_por": None, "alterado_em": None}
        for d in sorted(datas) for u in corpo.user_ids
    ]
    await _bolso_validar_idas(novas)
    gravadas = []
    try:
        for nova in novas:
            await db.bolso_idas.insert_one(dict(nova))  # cópia: o insert_one mete o _id no dicionário
            gravadas.append(nova["id"])
    except DuplicateKeyError:
        # Tudo ou nada SEM transacções (o Atlas tem, o mongod dos testes não): apaga-se o
        # que ESTE pedido já gravou.
        # ponytail: entre verificar e gravar fica uma janela para idas sobrepostas mas não
        # iguais, marcadas por duas gestoras no mesmo segundo — o índice único só apanha a
        # igual. Aceite no desenho; uma transacção fecha-a se algum dia acontecer.
        if gravadas:
            await db.bolso_idas.delete_many({"id": {"$in": gravadas}})
        raise HTTPException(
            status_code=409,
            detail="Alguém marcou uma destas idas ao mesmo tempo. Nada foi gravado — volte a abrir o dia.")
    return {"criadas": len(gravadas), "ids": gravadas}


@api_router.put("/bolso/calendario/idas/{ida_id}")
async def bolso_mudar_ida(ida_id: str, corpo: BolsoIdaIn, current_user: dict = Depends(bolso_quem_marca)):
    """Muda dia, loja, pessoa ou horas de UMA ida; 409 se chocar (consigo própria não choca)."""
    actual = await db.bolso_idas.find_one({"id": ida_id}, {"_id": 0})
    if not actual:
        raise HTTPException(status_code=404, detail="Esta ida já não existe — volte a abrir o dia.")
    mudancas = {"data": corpo.data.isoformat(), "location_id": corpo.location_id,
                "user_id": corpo.user_id, "inicio": corpo.inicio, "fim": corpo.fim}
    await _bolso_validar_idas([dict(actual, **mudancas)], ignorar_id=ida_id)
    mudancas.update(alterado_por=current_user.get("user_id"), alterado_em=datetime.now(timezone.utc).isoformat())
    try:
        await db.bolso_idas.update_one({"id": ida_id}, {"$set": mudancas})
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409, detail="Alguém marcou esta mesma ida ao mesmo tempo — volte a abrir o dia.")
    return dict(actual, **mudancas)


@api_router.delete("/bolso/calendario/idas/{ida_id}")
async def bolso_apagar_ida(ida_id: str, current_user: dict = Depends(bolso_quem_marca)):
    resultado = await db.bolso_idas.delete_one({"id": ida_id})
    if resultado.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Esta ida já não existe — volte a abrir o dia.")
    return {"apagada": ida_id}


```

(`date`, `datetime`, `timezone`, `uuid`, `List`, `Optional`, `BaseModel`, `Depends`, `HTTPException` já estão importados no topo do `server.py`.)

- [ ] **Passo 4: Correr e ver passar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_rotas_de_escrita.py tests/calendario/test_rotas_de_leitura.py tests/fin/test_caminhos_do_bolso.py -q
```

Esperado: `35 passed` (28 + 4 + 3).

- [ ] **Passo 5: Prova por mutação**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PY=~/Developer/RH/backend/.venv/bin/python
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py server.py 'await db.bolso_idas.delete_many({"id": {"$in": gravadas}})' 'pass' -- $PY -m pytest tests/calendario/test_rotas_de_escrita.py -q -k tudo_ou_nada
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py server.py 'if current_user.get("role") not in calendario.GESTORES:' 'if False:' -- $PY -m pytest tests/calendario/test_rotas_de_escrita.py -q -k 403
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py server.py 'async def bolso_criar_idas(corpo: BolsoIdasIn, current_user: dict = Depends(bolso_quem_marca)):' 'async def bolso_criar_idas(corpo: BolsoIdasIn, current_user: dict = Depends(admin_manager_required)):' -- $PY -m pytest tests/calendario/test_rotas_de_escrita.py -q -k escrever
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py server.py 'pares = calendario.choques(novas, existentes, ignorar_id)' 'pares = []' -- $PY -m pytest tests/calendario/test_rotas_de_escrita.py -q -k "choque or choca"
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py server.py 'impedidas = calendario.ausencias_que_impedem(novas, pessoas, ausencias)' 'impedidas = []' -- $PY -m pytest tests/calendario/test_rotas_de_escrita.py -q -k ferias
```

Esperado: (1) `FAILED …test_o_tudo_ou_nada_compensa…` (ficam as duas idas que o pedido gravou antes do choque); (2) `FAILED …test_o_contabilista_leva_403…`; (3) `FAILED …test_escrever_e_so_para_admin_e_gerente[POST-…]`; (4) `FAILED …test_um_choque_so_na_ultima_data…` e `…test_mudar_uma_ida_que_choca…`; (5) `FAILED …test_um_colaborador_de_ferias_nao_se_marca`. Todas com «Mutação apanhada».

- [ ] **Passo 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add backend/server.py backend/tests/calendario/test_rotas_de_escrita.py
git commit -m "Calendário: marcar, mudar e apagar idas no bolso, tudo ou nada

Só administradores e gestores marcam (o contabilista lê). Um pedido com várias datas e
duas pessoas cria uma ida por cada, e se uma falhar as regras (sobreposição, férias, loja
fechada) não grava nenhuma; sem transacções, compensa-se apagando o que o próprio pedido
gravou quando o índice único apanha quem marcou ao mesmo tempo.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Tarefa 8: O ajudante que corre JavaScript do frontend em Node

**Ficheiros:**
- Criar: `backend/tests/bolso_js.py`
- Testes: `backend/tests/test_bolso_js.py` (criar)

**Interfaces:**
- Consome: `frontend/node_modules` (atalho): `@babel/core`, `@babel/preset-react`, `@babel/plugin-transform-modules-commonjs`, `react`, `react-dom/client`, `jsdom`; `frontend/src/lib/utils.js`, `frontend/src/lib/bolso.js` (`getPainel`), `frontend/src/components/ui/sheet.jsx` (só nos testes do ajudante).
- Produz (em `tests.bolso_js`, usado pelas Tarefas 9-13 e pela Fase 3):
  - `correr_js(guiao: str, tmp_path: Path, simulados: Optional[Dict[str, str]] = None, dom: bool = False) -> object` — devolve o JSON passado a `devolve()`; falha o teste (`pytest.fail`) se o Node sair com erro; salta (com a razão) sem `node` ou sem `frontend/node_modules`
  - `AXIOS_FABRICADO: str` (expressão JS; o guião define `global.SERVIDOR(metodo, url, corpo, params)`; cada pedido fica em `REGISTO` como `[verbo, url, corpo, params]`)
  - `SESSAO_SIMULADA: Dict[str, str]` (`react-router-dom` com `useNavigate` estável que regista `['navigate', para]`; `@/contexts/AuthContext` com `useAuth()` → `{logout (regista ['logout']), user: {name: 'Débora Ferreira'}}`)
  - `RAIZ`, `FRONTEND`, `SRC: Path`
  - no guião: `importar(relativo)`, `devolve(valor)`, `React`, `REGISTO`, `SIMULADOS`; com `dom=True` também `montar(elemento)`, `esperar()`, `clicar(el)`, `escrever(el, valor)`, `botao(rotulo, dentro=document)`, `texto()`, `pararRelogio(ano, mes, dia, hora=12, minuto=0)`

- [ ] **Passo 1: Escrever os testes que falham**

`backend/tests/test_bolso_js.py`:

```python
"""O ajudante que corre JavaScript do frontend em Node (`tests/bolso_js.py`)."""
import pytest

from tests.bolso_js import AXIOS_FABRICADO, correr_js


def test_corre_um_modulo_verdadeiro_do_frontend(tmp_path):
    # `cn` é o twMerge(clsx(...)) de lib/utils.js: o px-4 ganha ao px-2.
    assert correr_js("devolve(importar('lib/utils').cn('px-2 text-sm', 'px-4'));", tmp_path) == "text-sm px-4"


def test_um_modulo_simulado_chega_aos_modulos_do_frontend(tmp_path):
    r = correr_js("devolve(importar('lib/utils').cn('a', 'b'));", tmp_path,
                  simulados={"tailwind-merge": "({ twMerge: (s) => 'simulado:' + s })"})
    assert r == "simulado:a b"


def test_o_axios_fabricado_regista_o_pedido_e_devolve_a_resposta(tmp_path):
    r = correr_js(
        "global.SERVIDOR = (metodo, url, corpo, params) => ({ eco: [metodo, url, params] });\n"
        "const { getPainel } = importar('lib/bolso');\n"
        "const { data } = await getPainel('c1', 'u1');\n"
        "devolve({ data, registo: REGISTO });",
        tmp_path, simulados={"axios": AXIOS_FABRICADO})
    params = {"empresa": "c1", "unidade": "u1"}
    assert r == {"data": {"eco": ["GET", "/painel", params]}, "registo": [["GET", "/painel", None, params]]}


def test_com_dom_monta_o_sheet_do_radix_e_clica(tmp_path):
    """O Sheet é o caso que obrigou a trocar o `Event` do Node pelo do jsdom."""
    r = correr_js(
        "const S = importar('components/ui/sheet');\n"
        "let fechou = 0;\n"
        "await montar(React.createElement(S.Sheet, { open: true, onOpenChange: () => { fechou += 1; } },\n"
        "  React.createElement(S.SheetContent, null, React.createElement(S.SheetTitle, null, 'Olá'))));\n"
        "const dialogo = document.querySelector('[role=\"dialog\"]');\n"
        "await clicar(botao('Close', dialogo) || dialogo.querySelector('button'));\n"
        "devolve({ titulo: dialogo.querySelector('h2').textContent, fechou });",
        tmp_path, dom=True)
    assert r == {"titulo": "Olá", "fechou": 1}


def test_o_relogio_parado_e_o_localstorage_do_jsdom(tmp_path):
    r = correr_js(
        "pararRelogio(2026, 10, 16, 0, 30);\n"
        "localStorage.setItem('x', '1');\n"
        "devolve({ dia: new Date().getDate(), hora: new Date().getHours(), x: localStorage.getItem('x') });",
        tmp_path, dom=True)
    assert r == {"dia": 16, "hora": 0, "x": "1"}


def test_um_erro_no_javascript_falha_o_teste_com_a_mensagem(tmp_path):
    with pytest.raises(pytest.fail.Exception, match="rebentou de propósito"):
        correr_js("throw new Error('rebentou de propósito');", tmp_path)
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/test_bolso_js.py -q
```

Esperado: erro de colecção `ModuleNotFoundError: No module named 'tests.bolso_js'`.

- [ ] **Passo 3: Implementação**

`backend/tests/bolso_js.py`:

```python
"""Correr JavaScript do frontend em Node, a partir do pytest.

Não há jest a correr neste repositório: o JavaScript do ecrã testa-se a partir da suite do
backend, em Node, com o código VERDADEIRO dos ficheiros (nunca uma cópia escrita no teste —
uma cópia ficava verde com o ecrã errado). É a técnica de
`tests/faturacao/test_a_faixa_do_modo_no_ecra.py`, posta num sítio só para o calendário e
para a Fase 3 (Face ID) a reusarem.

O guião corre dentro de uma função `async` e tem à mão:

- `importar('lib/calendario')` — um módulo de `frontend/src`, transformado pelo babel (JSX
  e `import`), com o alias `@/` resolvido como no build;
- `devolve(valor)` — o que o Python recebe (JSON; chamar UMA vez);
- `React` e `REGISTO` (uma lista onde os módulos simulados apontam o que lhes pedem);
- com `dom=True`: um DOM (jsdom) e `montar(elemento)`, `esperar()`, `clicar(el)`,
  `escrever(el, valor)`, `botao(rotulo)`, `texto()` e `pararRelogio(ano, mes, dia, h, m)`.

`simulados` troca módulos inteiros, pelo nome com que são importados, por uma expressão
JavaScript. O `lucide-react` vem sempre simulado (cada ícone é um `<i data-icone>`).
"""
import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional

import pytest

RAIZ = Path(__file__).resolve().parents[2]
FRONTEND = RAIZ / "frontend"
SRC = FRONTEND / "src"

# O axios trocado por um servidor fabricado: cada pedido fica em `REGISTO` como
# [verbo, url, corpo, params] e a resposta vem de `global.SERVIDOR(método, url, corpo, params)`,
# que o guião define. Se a resposta trouxer `erro`, o pedido falha com esse objecto (ex.:
# `{ erro: { response: { status: 409, data: { detail: '…' } } } }`). As instâncias de
# `axios.create()` — a do `lib/bolso.js` — passam por aqui com o código delas intacto.
AXIOS_FABRICADO = r"""(() => {
  const instancia = () => {
    const inst = { interceptors: { request: { use: () => {} }, response: { use: () => {} } } };
    for (const metodo of ['get', 'post', 'put', 'delete', 'patch']) {
      inst[metodo] = async (url, a, b) => {
        const semCorpo = metodo === 'get' || metodo === 'delete';
        const corpo = semCorpo ? null : (a === undefined ? null : a);
        const params = ((semCorpo ? a : b) || {}).params || null;
        REGISTO.push([metodo.toUpperCase(), url, corpo, params]);
        const resposta = global.SERVIDOR(metodo.toUpperCase(), url, corpo, params || {});
        if (resposta && resposta.erro) throw resposta.erro;
        return { data: resposta };
      };
    }
    return inst;
  };
  return Object.assign(instancia(), { create: instancia, defaults: { headers: { common: {} } } });
})()"""

# A sessão e a navegação, ESTÁVEIS entre renders (um `useNavigate` que devolvesse uma função
# nova a cada render punha os `useEffect` que dependem dele a correr sem fim).
SESSAO_SIMULADA = {
    "react-router-dom": "(() => { const navegar = (para) => REGISTO.push(['navigate', para]);"
                        " return { useNavigate: () => navegar }; })()",
    "@/contexts/AuthContext": "(() => { const sessao = { logout: () => REGISTO.push(['logout']),"
                              " user: { name: 'Débora Ferreira' } }; return { useAuth: () => sessao }; })()",
}


def _node() -> str:
    caminho = shutil.which("node")
    if caminho:
        return caminho
    candidato = Path.home() / ".local" / "node" / "bin" / "node"
    if candidato.exists():
        return str(candidato)
    pytest.skip("Sem `node` (nem no PATH nem em ~/.local/node/bin): este JavaScript NÃO foi testado.")


_DOM = r"""
const { JSDOM } = require('jsdom');
const dom = new JSDOM('<!doctype html><html><head></head><body></body></html>',
  { url: 'http://localhost/', pretendToBeVisual: true });
global.window = dom.window;
global.document = dom.window.document;
for (const chave of Object.getOwnPropertyNames(dom.window)) {
  if (!(chave in global)) { try { global[chave] = dom.window[chave]; } catch (e) { /* só de leitura */ } }
}
// O Node já traz alguns destes, e os dele não servem: o jsdom recusa o `Event` do Node
// («parameter 1 is not of type 'Event'» — medido com o Sheet do Radix), o `localStorage` do
// Node é um getter experimental que devolve `undefined` sem `--localstorage-file`, e
// `global.navigator = …` não pega a partir do Node 21. Ficam os do jsdom, por definição.
for (const chave of ['Event', 'CustomEvent', 'EventTarget', 'navigator', 'localStorage', 'sessionStorage']) {
  Object.defineProperty(global, chave, { value: dom.window[chave], configurable: true, writable: true });
}
global.IS_REACT_ACT_ENVIRONMENT = true;
"""

_CARREGADOR = r"""
const fs = require('fs');
const path = require('path');
const Module = require('module');
const babel = require('@babel/core');
const React = require('react');
const SRC = %(src)s;
const REGISTO = [];
const SIMULADOS = {
  'lucide-react': new Proxy({}, { get: (_, nome) => (
    typeof nome === 'string' && nome !== '__esModule'
      ? (props) => React.createElement('i', { 'data-icone': nome, className: props && props.className })
      : undefined) }),
};
function resolver(base) {
  for (const fim of ['', '.js', '.jsx', '/index.js']) {
    const f = base + fim;
    if (fs.existsSync(f) && fs.statSync(f).isFile()) return f;
  }
  throw new Error('Não encontrei ' + base);
}
const cache = new Map();
function carregar(ficheiro) {
  if (cache.has(ficheiro)) return cache.get(ficheiro).exports;
  const codigo = babel.transformSync(fs.readFileSync(ficheiro, 'utf-8'), {
    presets: [[require.resolve('@babel/preset-react'), { runtime: 'classic' }]],
    plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],
    filename: ficheiro, babelrc: false, configFile: false,
  }).code;
  const m = new Module(ficheiro, null);
  m.filename = ficheiro;
  m.paths = Module._nodeModulePaths(path.dirname(ficheiro));
  cache.set(ficheiro, m);
  const original = m.require.bind(m);
  m.require = (pedido) => {
    if (Object.prototype.hasOwnProperty.call(SIMULADOS, pedido)) return SIMULADOS[pedido];
    if (pedido.startsWith('@/')) return carregar(resolver(path.join(SRC, pedido.slice(2))));
    if (pedido.startsWith('.')) return carregar(resolver(path.join(path.dirname(ficheiro), pedido)));
    return original(pedido);
  };
  m._compile(codigo, ficheiro);
  return m.exports;
}
const importar = (relativo) => carregar(resolver(path.join(SRC, relativo)));
const devolve = (valor) => process.stdout.write(JSON.stringify(valor === undefined ? null : valor));
"""

_MONTAGEM = r"""
const { act } = require('react');
const { createRoot } = require('react-dom/client');
async function montar(elemento) {
  const caixa = document.createElement('div');
  document.body.appendChild(caixa);
  const raiz = createRoot(caixa);
  await act(async () => { raiz.render(elemento); });
  return raiz;
}
async function esperar() {
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}
async function clicar(el) {
  if (!el) throw new Error('clicar: não encontrei o elemento');
  await act(async () => { el.dispatchEvent(new window.MouseEvent('click', { bubbles: true })); });
}
async function escrever(el, valor) {
  if (!el) throw new Error('escrever: não encontrei o elemento');
  const proto = el.tagName === 'SELECT' ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, valor);
  await act(async () => {
    el.dispatchEvent(new window.Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }));
  });
}
const texto = () => document.body.textContent;
// O botão pelo texto (exacto, sem espaços à volta) ou pelo aria-label.
const botao = (rotulo, dentro = document) => [...dentro.querySelectorAll('button')].find(
  (b) => b.textContent.trim() === rotulo || b.getAttribute('aria-label') === rotulo);
const DataReal = Date;
function pararRelogio(ano, mes, dia, hora = 12, minuto = 0) {
  const fixo = new DataReal(ano, mes - 1, dia, hora, minuto).getTime();
  class DataParada extends DataReal {
    constructor(...a) { if (a.length) super(...a); else super(fixo); }
    static now() { return fixo; }
  }
  global.Date = DataParada;
  window.Date = DataParada;
}
"""


def correr_js(guiao: str, tmp_path: Path, simulados: Optional[Dict[str, str]] = None, dom: bool = False):
    """Corre `guiao` em Node e devolve o que ele passou a `devolve()`. Um erro no JavaScript
    falha o teste com a mensagem do Node."""
    if not (FRONTEND / "node_modules" / "@babel" / "core").exists():
        pytest.skip("Sem frontend/node_modules (ln -sfn ~/Developer/RH/frontend/node_modules "
                    "frontend/node_modules): este JavaScript NÃO foi testado.")
    partes = [_DOM if dom else "", _CARREGADOR % {"src": json.dumps(str(SRC))}, _MONTAGEM if dom else ""]
    partes += ["SIMULADOS[%s] = %s;" % (json.dumps(nome), expressao) for nome, expressao in (simulados or {}).items()]
    partes.append(
        "(async () => {\n%s\n})().catch((e) => {\n"
        "  console.error((e && e.stack) || e);\n"
        "  if (e && e.errors) e.errors.forEach((x) => console.error((x && x.stack) || x));\n"
        "  process.exit(1);\n});" % guiao)
    ficheiro = tmp_path / "guiao.js"
    ficheiro.write_text("\n".join(partes), encoding="utf-8")
    resultado = subprocess.run(
        [_node(), str(ficheiro)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(FRONTEND),
        env={"NODE_PATH": str(FRONTEND / "node_modules"), "PATH": "/usr/bin:/bin", "TZ": "Europe/Lisbon"},
        timeout=180)
    if resultado.returncode != 0:
        pytest.fail("O JavaScript não correu:\n%s" % resultado.stderr.decode("utf-8", "replace"))
    saida = resultado.stdout.decode("utf-8")
    return json.loads(saida) if saida else None
```

- [ ] **Passo 4: Correr e ver passar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/test_bolso_js.py -q -rs
```

Esperado: `6 passed` e **nenhum** `skipped` (um `SKIPPED … Sem frontend/node_modules` quer dizer que falta o atalho do Passo 1 da Tarefa 1).

- [ ] **Passo 5: Prova por mutação**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PY=~/Developer/RH/backend/.venv/bin/python
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py tests/bolso_js.py "for (const chave of ['Event', 'CustomEvent', 'EventTarget', 'navigator', 'localStorage', 'sessionStorage'])" "for (const chave of ['navigator', 'sessionStorage'])" -- $PY -m pytest tests/test_bolso_js.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py tests/bolso_js.py 'for nome, expressao in (simulados or {}).items()]' 'for nome, expressao in {}.items()]' -- $PY -m pytest tests/test_bolso_js.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py tests/bolso_js.py 'if resultado.returncode != 0:' 'if False:' -- $PY -m pytest tests/test_bolso_js.py -q
```

Esperado: (1) `FAILED …test_com_dom_monta_o_sheet_do_radix_e_clica` («parameter 1 is not of type 'Event'») e `…test_o_relogio_parado_e_o_localstorage_do_jsdom`; (2) `FAILED …test_um_modulo_simulado…` e `…test_o_axios_fabricado…`; (3) `FAILED …test_um_erro_no_javascript_falha_o_teste_com_a_mensagem`. Todas com «Mutação apanhada».

- [ ] **Passo 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add backend/tests/bolso_js.py backend/tests/test_bolso_js.py
git commit -m "Testes: ajudante que corre o JavaScript do bolso em Node, com DOM e servidor fabricado

O calendário e o Face ID vão ter ecrãs com lógica que só se prova a correr. O ajudante
transforma com o babel os ficheiros verdadeiros de frontend/src, troca módulos inteiros
por simulados (o axios por um servidor fabricado) e monta componentes num jsdom onde o
Sheet do Radix funciona e o localStorage existe.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Tarefa 9: `lib/calendario.js` — as contas do ecrã, puras

**Ficheiros:**
- Criar: `frontend/src/lib/calendario.js`
- Testes: `backend/tests/calendario/test_lib_calendario.py` (criar)

**Interfaces:**
- Consome: a forma de `calendario.resposta_do_mes` (Tarefa 5); `tests.bolso_js.correr_js` (Tarefa 8).
- Produz (exports de `@/lib/calendario`, usados nas Tarefas 11-13):
  - constantes `MESES` (12, minúsculas), `DIAS_DA_SEMANA` (0 = segunda), `VISTAS = ['mes', 'lista', 'contagem']`, `FILTROS = ['pessoal', 'geral', 'ferias']`, `NOMES_DAS_AUSENCIAS` (`ferias` → `'Férias'`, …)
  - `isoDe(ano, mes, dia) -> 'AAAA-MM-DD'`, `hojeIso(agora = new Date())`, `diaDaSemana(iso) -> 0..6`, `semanasDoMes(ano, mes) -> (string|null)[7][]`, `mesAoLado(ano, mes, passo) -> {ano, mes}`
  - `tituloDoMes(ano, mes)` («outubro 2026»), `tituloDoDia(iso)` («terça, 27 de outubro»), `dataCurta(iso)` («27/10»), `horaCurta(hhmm)` («10h», «11h30»), `intervaloCurto(inicio, fim)` («10h–14h»), `primeiroNome(nome)`, `quantosDias(n)` («1 dia», «0,5 dias»)
  - `minhasIdas(dados)`, `ausenciasDoDia(dados, iso)`, `diasComPonto(dados, filtro) -> iso[]`, `feriadosDoMes(dados) -> iso[]`
  - `lista(dados, filtro, hoje) -> [{data, buracos: [loja do dia], idas: [ida], ausencias: [ausência]}]`
  - `outrosDiasComBuraco(dados, iso, locationId, inicio, fim) -> iso[]`, `textoDoAtalho(iso, nomeDaLoja)`
  - `pessoasIniciais(dados) -> [user_id]`, `linhaDaContagem(linha, ano, mes)`, `mensagemDeErro(e) -> string`

- [ ] **Passo 1: Escrever os testes que falham**

`backend/tests/calendario/test_lib_calendario.py`:

```python
"""As contas do ecrã do calendário (`frontend/src/lib/calendario.js`), corridas em Node
contra a resposta REAL do mês (`calendario.resposta_do_mes` sobre a semana normal) — se o
servidor mudar a forma da resposta, é aqui que se vê, e não no telemóvel do dono."""
import json

import calendario
from tests.bolso_js import correr_js

from . import dados_semana_normal as sn


def _outubro(idas=(), ausencias=(), eu=sn.DEBORA):
    dados = sn.semana_normal()
    dados["idas"] = list(idas)
    dados["ausencias"] = list(ausencias)
    return calendario.resposta_do_mes(2026, 10, dados, eu, eu != sn.CONTABILISTA)


def _cal(tmp_path, expressao, dados=None):
    """Corre `expressao` com `cal` = lib/calendario.js e `D` = a resposta do mês."""
    return correr_js("const cal = importar('lib/calendario');\nconst D = %s;\ndevolve(%s);"
                     % (json.dumps(dados, ensure_ascii=False), expressao), tmp_path)


def test_o_hoje_e_o_dia_do_telemovel_e_nao_o_de_utc(tmp_path):
    # 16/10 às 00:30 em Lisboa (o TZ do Node é Europe/Lisbon) ainda é 15/10 em UTC.
    r = _cal(tmp_path, "[cal.hojeIso(new Date(2026, 9, 16, 0, 30)), "
                       "new Date(2026, 9, 16, 0, 30).toISOString().slice(0, 10)]")
    assert r == ["2026-10-16", "2026-10-15"]


def test_as_semanas_do_mes_comecam_a_segunda(tmp_path):
    outubro, novembro, fevereiro = _cal(
        tmp_path, "[cal.semanasDoMes(2026, 10), cal.semanasDoMes(2026, 11).length, cal.semanasDoMes(2027, 2).length]")
    assert outubro[0] == [None, None, None, "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]
    assert outubro[-1] == ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31", None]
    assert (len(outubro), novembro, fevereiro) == (5, 6, 4)


def test_mes_ao_lado_e_titulos(tmp_path):
    r = _cal(tmp_path, "[cal.mesAoLado(2026, 12, 1), cal.mesAoLado(2026, 1, -1), cal.tituloDoMes(2026, 10), "
                       "cal.tituloDoDia('2026-10-27'), cal.dataCurta('2026-10-27'), cal.intervaloCurto('11:30', '19:00'), "
                       "cal.quantosDias(1), cal.quantosDias(0.5), cal.quantosDias(17.5)]")
    assert r == [{"ano": 2027, "mes": 1}, {"ano": 2025, "mes": 12}, "outubro 2026", "terça, 27 de outubro",
                 "27/10", "11h30–19h", "1 dia", "0,5 dias", "17,5 dias"]


def test_os_pontos_de_cada_filtro_e_os_feriados(tmp_path):
    dados = _outubro(idas=[sn.ida("2026-10-06", sn.OEIRAS, sn.DEBORA, "13:00", "22:00"),
                           sn.ida("2026-10-20", sn.OEIRAS, sn.CAROL, "13:00", "22:00")],
                     ausencias=[sn.ausencia("Weber", "2026-10-21", "2026-10-25")])
    geral, pessoal, ferias, feriados = _cal(
        tmp_path, "['geral', 'pessoal', 'ferias'].map((f) => cal.diasComPonto(D, f)).concat([cal.feriadosDoMes(D)])", dados)
    assert geral == [d["data"] for d in dados["dias"] if any(l["buracos"] for l in d["lojas"])]
    assert "2026-10-05" in geral and "2026-10-02" not in geral and "2026-10-31" in geral
    assert pessoal == ["2026-10-06"]
    assert ferias == ["2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25"]
    assert feriados == ["2026-10-05"]


def test_a_lista_comeca_hoje_no_mes_corrente_e_salta_os_dias_vazios(tmp_path):
    dados = _outubro(idas=[sn.ida("2026-10-27", sn.ALFRAGIDE, sn.DEBORA, "10:00", "14:00")],
                     ausencias=[sn.ausencia("Weber", "2026-10-21", "2026-10-25")])
    r = _cal(tmp_path, "{ hoje: cal.lista(D, 'geral', '2026-10-27'), "
                       "outro: cal.lista(D, 'geral', '2026-11-15').map((d) => d.data), "
                       "pessoal: cal.lista(D, 'pessoal', '2026-10-01'), ferias: cal.lista(D, 'ferias', '2026-10-23') }", dados)
    assert r["hoje"][0]["data"] == "2026-10-27"
    assert [l["nome"] for l in r["hoje"][0]["buracos"]] == ["Benfica", "Oeiras"]
    assert [i["nome"] for i in r["hoje"][0]["idas"]] == ["Débora Ferreira"]
    assert r["outro"][:3] == ["2026-10-01", "2026-10-05", "2026-10-06"]        # 02, 03 e 04/10 sem nada
    assert [(d["data"], len(d["idas"])) for d in r["pessoal"]] == [("2026-10-27", 1)]
    assert [(d["data"], [a["nome"] for a in d["ausencias"]]) for d in r["ferias"]] == [("2026-10-23", ["Weber"])]


def test_o_atalho_marca_as_outras_tercas_cujo_buraco_contem_as_horas(tmp_path):
    dados = _outubro(idas=[sn.ida("2026-10-20", sn.OEIRAS, sn.DEBORA, "13:00", "17:00")])
    r = _cal(tmp_path, "[cal.outrosDiasComBuraco(D, '2026-10-06', 'loja-oeiras', '13:00', '22:00'), "
                       "cal.outrosDiasComBuraco(D, '2026-10-06', 'loja-oeiras', '18:00', '22:00'), "
                       "cal.outrosDiasComBuraco(D, '2026-10-05', 'loja-alfragide', '10:00', '14:00'), "
                       "cal.outrosDiasComBuraco(D, '2026-10-06', '', '13:00', '22:00'), "
                       "cal.textoDoAtalho('2026-10-06', 'Oeiras'), cal.textoDoAtalho('2026-10-03', 'Belém')]", dados)
    assert r == [["2026-10-13", "2026-10-27"],                 # a 20/10 o buraco é só 17–22
                 ["2026-10-13", "2026-10-20", "2026-10-27"],
                 ["2026-10-12", "2026-10-19", "2026-10-26"], [],
                 "Também nas outras terças deste mês com buraco em Oeiras",
                 "Também nos outros sábados deste mês com buraco em Belém"]


def test_o_painel_comeca_em_mim_se_eu_puder_ser_escalado(tmp_path):
    assert _cal(tmp_path, "cal.pessoasIniciais(D)", _outubro()) == [sn.DEBORA]
    assert _cal(tmp_path, "cal.pessoasIniciais(D)", _outubro(eu=sn.CONTABILISTA)) == []


def test_a_linha_da_contagem_e_os_erros_do_servidor(tmp_path):
    r = _cal(tmp_path, "[cal.linhaDaContagem({ nome: 'Débora Ferreira', meses: [0,0,0,0,0,0,0,0,0,18,0,0], total: 60 }, 2026, 10), "
                       "cal.mensagemDeErro({ response: { status: 409, data: { detail: 'Débora já está em Alfragide.' } } }), "
                       "cal.mensagemDeErro({ response: { status: 422, data: { detail: [{ msg: 'Field required' }, { msg: 'Outro' }] } } }), "
                       "cal.mensagemDeErro({ response: { status: 500, data: {} } }), "
                       "cal.mensagemDeErro(new Error('Network Error'))]")
    assert r == ["Débora · outubro 18 dias · 2026 60 dias", "Débora já está em Alfragide.", "Field required\nOutro",
                 "O servidor recusou este pedido.", "Sem resposta do servidor. Verifique a rede e tente outra vez."]
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_lib_calendario.py -q
```

Esperado: `8 failed`, cada um com «O JavaScript não correu: … Error: Não encontrei …/frontend/src/lib/calendario».

- [ ] **Passo 3: Implementação**

`frontend/src/lib/calendario.js`:

```js
// Calendário das lojas na Gestão Lisbonb — as contas do ecrã, sem React e sem rede.
//
// O servidor manda o mês inteiro num pedido (`GET /api/bolso/calendario`, montado por
// `backend/calendario.py::resposta_do_mes`); daqui sai o que o ecrã desenha: a grelha, os
// pontos, a Lista, a Contagem e o atalho das outras terças. Tudo puro, corrido em Node a
// partir da suite do backend (`backend/tests/calendario/test_lib_calendario.py`).

export const MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
  'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];
// 0 = segunda … 6 = domingo, como o `work_days` do servidor.
export const DIAS_DA_SEMANA = ['segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado', 'domingo'];
const NO_PLURAL = ['segundas', 'terças', 'quartas', 'quintas', 'sextas', 'sábados', 'domingos'];
export const VISTAS = ['mes', 'lista', 'contagem'];
export const FILTROS = ['pessoal', 'geral', 'ferias'];
export const NOMES_DAS_AUSENCIAS = {
  ferias: 'Férias', folga: 'Folga', doenca: 'Doença', falta: 'Falta', ausencia: 'Ausência',
};

const dois = (n) => String(n).padStart(2, '0');
export const isoDe = (ano, mes, dia) => `${ano}-${dois(mes)}-${dois(dia)}`;

// O «hoje» é o do telemóvel, em hora LOCAL. Nunca `toISOString()`: entre a meia-noite e a
// uma da manhã de Lisboa (duas, no verão) dava o dia anterior.
export const hojeIso = (agora = new Date()) => isoDe(agora.getFullYear(), agora.getMonth() + 1, agora.getDate());

// Ao meio-dia UTC nenhum fuso muda o dia.
export const diaDaSemana = (iso) => (new Date(`${iso}T12:00:00Z`).getUTCDay() + 6) % 7;
const diasNoMes = (ano, mes) => new Date(Date.UTC(ano, mes, 0)).getUTCDate();

// As semanas do mês, de segunda a domingo, com `null` nos lugares fora do mês.
export function semanasDoMes(ano, mes) {
  const semanas = [];
  let semana = Array(diaDaSemana(isoDe(ano, mes, 1))).fill(null);
  for (let d = 1; d <= diasNoMes(ano, mes); d += 1) {
    semana.push(isoDe(ano, mes, d));
    if (semana.length === 7) { semanas.push(semana); semana = []; }
  }
  if (semana.length) semanas.push([...semana, ...Array(7 - semana.length).fill(null)]);
  return semanas;
}

export const mesAoLado = (ano, mes, passo) => {
  const n = ano * 12 + (mes - 1) + passo;
  return { ano: Math.floor(n / 12), mes: (n % 12) + 1 };
};

export const tituloDoMes = (ano, mes) => `${MESES[mes - 1]} ${ano}`;
export const tituloDoDia = (iso) => (
  `${DIAS_DA_SEMANA[diaDaSemana(iso)]}, ${Number(iso.slice(8))} de ${MESES[Number(iso.slice(5, 7)) - 1]}`);
export const dataCurta = (iso) => `${iso.slice(8)}/${iso.slice(5, 7)}`;
export const horaCurta = (hhmm) => {
  const [h, m] = String(hhmm).split(':');
  return m === '00' ? `${Number(h)}h` : `${Number(h)}h${m}`;
};
export const intervaloCurto = (inicio, fim) => `${horaCurta(inicio)}–${horaCurta(fim)}`;
export const primeiroNome = (nome) => String(nome || '').trim().split(/\s+/)[0] || '';
export const quantosDias = (n) => `${String(n).replace('.', ',')} ${n === 1 ? 'dia' : 'dias'}`;

export const minhasIdas = (dados) => (dados?.idas || []).filter((i) => i.user_id === dados.eu);
export const ausenciasDoDia = (dados, iso) => (
  (dados?.ausencias || []).filter((a) => a.inicio <= iso && iso <= a.fim));
const temBuraco = (dia) => (dia?.lojas || []).some((l) => (l.buracos || []).length > 0);

// Os dias com ponto na grelha: Geral = com buraco por tapar; Pessoal = com idas minhas;
// Férias = com ausências.
export function diasComPonto(dados, filtro) {
  const dias = dados?.dias || [];
  if (filtro === 'pessoal') {
    const meus = new Set(minhasIdas(dados).map((i) => i.data));
    return dias.map((d) => d.data).filter((d) => meus.has(d));
  }
  if (filtro === 'ferias') return dias.map((d) => d.data).filter((d) => ausenciasDoDia(dados, d).length > 0);
  return dias.filter(temBuraco).map((d) => d.data);
}

export const feriadosDoMes = (dados) => (
  (dados?.dias || []).filter((d) => (d.feriados || []).length > 0).map((d) => d.data));

// A Lista: os dias do mês com alguma coisa, a partir de hoje no mês corrente (o mês inteiro
// nos outros). Geral = buracos e idas; Pessoal = as minhas idas; Férias = cada ausência uma
// vez, no primeiro dia visível dela.
export function lista(dados, filtro, hoje) {
  const dias = dados?.dias || [];
  if (!dias.length) return [];
  const primeiro = dias.some((d) => d.data === hoje) ? hoje : dias[0].data;
  const idas = filtro === 'pessoal' ? minhasIdas(dados) : filtro === 'geral' ? (dados.idas || []) : [];
  return dias
    .filter((d) => d.data >= primeiro)
    .map((d) => ({
      data: d.data,
      buracos: filtro === 'geral' ? (d.lojas || []).filter((l) => (l.buracos || []).length > 0) : [],
      idas: idas.filter((i) => i.data === d.data),
      ausencias: filtro === 'ferias'
        ? (dados.ausencias || []).filter((a) => a.fim >= primeiro && (a.inicio > primeiro ? a.inicio : primeiro) === d.data)
        : [],
    }))
    .filter((x) => x.buracos.length || x.idas.length || x.ausencias.length);
}

// O atalho «Também nas outras terças deste mês com buraco em Oeiras»: os dias SEGUINTES do
// mesmo dia da semana em que essa loja tem um buraco que CONTÉM as horas escolhidas.
// Calculado só com a resposta do mês — sem pedidos.
export function outrosDiasComBuraco(dados, iso, locationId, inicio, fim) {
  if (!iso || !locationId || !inicio || !fim) return [];
  const semana = diaDaSemana(iso);
  return (dados?.dias || [])
    .filter((d) => d.data > iso && diaDaSemana(d.data) === semana)
    .filter((d) => (d.lojas || []).some((l) => l.location_id === locationId
      && (l.buracos || []).some((b) => b.inicio <= inicio && fim <= b.fim)))
    .map((d) => d.data);
}

export const textoDoAtalho = (iso, nomeDaLoja) => {
  const s = diaDaSemana(iso);
  return `Também ${s >= 5 ? 'nos outros' : 'nas outras'} ${NO_PLURAL[s]} deste mês com buraco em ${nomeDaLoja}`;
};

// O painel começa em mim, se eu puder ser escalado (o contabilista não pode).
export const pessoasIniciais = (dados) => (
  (dados?.pessoas || []).some((p) => p.id === dados.eu) ? [dados.eu] : []);

// «Débora · outubro 18 dias · 2026 60 dias»
export const linhaDaContagem = (linha, ano, mes) => (
  `${primeiroNome(linha.nome)} · ${MESES[mes - 1]} ${quantosDias(linha.meses[mes - 1])} · ${ano} ${quantosDias(linha.total)}`);

// O texto de um erro do servidor tal como ele o escreveu (as regras do calendário já dizem o
// que aconteceu e o que fazer). Sem resposta não se sabe nada — e diz-se isso.
export function mensagemDeErro(e) {
  if (!e?.response) return 'Sem resposta do servidor. Verifique a rede e tente outra vez.';
  const detalhe = e.response.data?.detail;
  if (typeof detalhe === 'string') return detalhe;
  if (Array.isArray(detalhe)) return detalhe.map((d) => d?.msg || String(d)).join('\n');
  return 'O servidor recusou este pedido.';
}
```

- [ ] **Passo 4: Correr e ver passar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_lib_calendario.py -q -rs
```

Esperado: `8 passed`, sem `skipped`.

- [ ] **Passo 5: Prova por mutação**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PY=~/Developer/RH/backend/.venv/bin/python
JS=../frontend/src/lib/calendario.js
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py $JS 'isoDe(agora.getFullYear(), agora.getMonth() + 1, agora.getDate())' 'agora.toISOString().slice(0, 10)' -- $PY -m pytest tests/calendario/test_lib_calendario.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py $JS 'b.inicio <= inicio && fim <= b.fim' 'b.inicio < fim && inicio < b.fim' -- $PY -m pytest tests/calendario/test_lib_calendario.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py $JS 'const primeiro = dias.some((d) => d.data === hoje) ? hoje : dias[0].data;' 'const primeiro = dias[0].data;' -- $PY -m pytest tests/calendario/test_lib_calendario.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py $JS '.getUTCDay() + 6) % 7' '.getUTCDay()) % 7' -- $PY -m pytest tests/calendario/test_lib_calendario.py -q
```

Esperado: (1) `FAILED …test_o_hoje_e_o_dia_do_telemovel…` (dá 15/10); (2) `FAILED …test_o_atalho_marca…` (a 20/10 entra com buraco só 17–22); (3) `FAILED …test_a_lista_comeca_hoje…`; (4) `FAILED …test_as_semanas_do_mes_comecam_a_segunda` (e os que dependem do dia da semana). Todas com «Mutação apanhada».

- [ ] **Passo 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add frontend/src/lib/calendario.js backend/tests/calendario/test_lib_calendario.py
git commit -m "Calendário: as contas do ecrã num módulo puro, provadas contra a resposta real

A grelha de segunda a domingo, o dia de hoje em hora local (o toISOString dava o dia
anterior entre a meia-noite e a uma), os pontos de cada filtro, a Lista a partir de hoje
e o atalho das outras terças com buraco vivem em lib/calendario.js e correm em Node sobre
a resposta que o servidor calcula para a semana normal.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Tarefa 10: `lib/bolso.js` — as chamadas do calendário, confrontadas com o router

**Ficheiros:**
- Modificar: `frontend/src/lib/bolso.js` (acrescentar a seguir a `export const getPainel = …`, ~49-50)
- Modificar: `backend/tests/fin/test_caminhos_do_bolso.py` (acrescentar um teste no fim)
- Testes: `backend/tests/calendario/test_chamadas_do_calendario.py` (criar)

**Interfaces:**
- Consome: as rotas das Tarefas 6-7; `tests.bolso_js.correr_js`, `AXIOS_FABRICADO` (Tarefa 8).
- Produz (exports de `@/lib/bolso`):
  - `getCalendario(ano, mes)` → `GET /calendario` com `params: {ano, mes}`
  - `getContagem(ano)` → `GET /calendario/contagem` com `params: {ano}`
  - `criarIdas(corpo)` → `POST /calendario/idas` (`{datas, location_id, user_ids, inicio, fim}`)
  - `mudarIda(id, corpo)` → `PUT /calendario/idas/${id}` (`{data, location_id, user_id, inicio, fim}`)
  - `apagarIda(id)` → `DELETE /calendario/idas/${id}`
  - todas devolvem a promessa do axios (`{data}`)

- [ ] **Passo 1: Escrever os testes que falham**

No fim de `backend/tests/fin/test_caminhos_do_bolso.py`, acrescentar:

```python


def test_o_guarda_ve_as_chamadas_do_calendario():
    """O calendário (2026-10-15) acrescentou cinco chamadas. Se a expressão regular deixar de
    as VER (um caminho montado por concatenação, por exemplo), o teste de cima fica verde com
    elas erradas — por isso pergunta-se por cada uma. Quem as confronta com o servidor é o
    teste de cima; este só garante que ele as está a ver."""
    conteudo = _ler()
    prefixo = _RE_BASE_URL.search(conteudo).group(1)
    vistas = {(v.upper(), _normaliza(prefixo + c)) for v, _aspas, c in _RE_CHAMADA.findall(conteudo)}
    for esperada in [("GET", "/api/bolso/calendario"), ("GET", "/api/bolso/calendario/contagem"),
                     ("POST", "/api/bolso/calendario/idas"), ("PUT", "/api/bolso/calendario/idas/{}"),
                     ("DELETE", "/api/bolso/calendario/idas/{}")]:
        assert esperada in vistas, "%s %s não aparece em lib/bolso.js" % esperada
```

`backend/tests/calendario/test_chamadas_do_calendario.py`:

```python
"""O que as chamadas do calendário em `lib/bolso.js` levam: parâmetros e corpos. (O caminho
confronta-se com o servidor em `tests/fin/test_caminhos_do_bolso.py`.)"""
from tests.bolso_js import AXIOS_FABRICADO, correr_js


def test_as_chamadas_do_calendario_levam_o_que_o_servidor_espera(tmp_path):
    r = correr_js(
        "global.SERVIDOR = () => ({});\n"
        "const b = importar('lib/bolso');\n"
        "await b.getCalendario(2026, 10);\n"
        "await b.getContagem(2026);\n"
        "await b.criarIdas({ datas: ['2026-10-06'], location_id: 'l1', user_ids: ['u1'], inicio: '13:00', fim: '22:00' });\n"
        "await b.mudarIda('i1', { data: '2026-10-07', location_id: 'l1', user_id: 'u1', inicio: '13:00', fim: '22:00' });\n"
        "await b.apagarIda('i1');\n"
        "devolve(REGISTO);",
        tmp_path, simulados={"axios": AXIOS_FABRICADO})
    assert r == [
        ["GET", "/calendario", None, {"ano": 2026, "mes": 10}],
        ["GET", "/calendario/contagem", None, {"ano": 2026}],
        ["POST", "/calendario/idas",
         {"datas": ["2026-10-06"], "location_id": "l1", "user_ids": ["u1"], "inicio": "13:00", "fim": "22:00"}, None],
        ["PUT", "/calendario/idas/i1",
         {"data": "2026-10-07", "location_id": "l1", "user_id": "u1", "inicio": "13:00", "fim": "22:00"}, None],
        ["DELETE", "/calendario/idas/i1", None, None],
    ]
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/fin/test_caminhos_do_bolso.py tests/calendario/test_chamadas_do_calendario.py -q
```

Esperado: `2 failed, 3 passed` — `AssertionError: GET /api/bolso/calendario não aparece em lib/bolso.js` e «TypeError: b.getCalendario is not a function».

- [ ] **Passo 3: Implementação**

Em `frontend/src/lib/bolso.js`, logo a seguir ao bloco do `getPainel` (a linha `  api.get('/painel', { params: unidade ? { empresa, unidade } : { empresa } });`), acrescentar:

```js

// --- Calendário das lojas (`/api/bolso/calendario`) --------------------------------------
// Caminhos por extenso, sempre: o `tests/fin/test_caminhos_do_bolso.py` lê-os daqui e
// confronta-os com as rotas do servidor (o POS já esteve morto em produção com a suite
// verde por um prefixo errado).
export const getCalendario = (ano, mes) => api.get('/calendario', { params: { ano, mes } });
export const getContagem = (ano) => api.get('/calendario/contagem', { params: { ano } });
// corpo: { datas: ['AAAA-MM-DD', …], location_id, user_ids: [uma ou duas], inicio: 'HH:MM', fim: 'HH:MM' }
export const criarIdas = (corpo) => api.post('/calendario/idas', corpo);
// corpo: { data, location_id, user_id, inicio, fim }
export const mudarIda = (id, corpo) => api.put(`/calendario/idas/${id}`, corpo);
export const apagarIda = (id) => api.delete(`/calendario/idas/${id}`);
```

- [ ] **Passo 4: Correr e ver passar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/fin/test_caminhos_do_bolso.py tests/calendario/test_chamadas_do_calendario.py tests/test_bolso_js.py -q
```

Esperado: `11 passed`.

- [ ] **Passo 5: Prova por mutação**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PY=~/Developer/RH/backend/.venv/bin/python
JS=../frontend/src/lib/bolso.js
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py $JS "api.post('/calendario/idas', corpo)" "api.post('/calendario/ida', corpo)" -- $PY -m pytest tests/fin/test_caminhos_do_bolso.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py $JS "{ params: { ano, mes } }" "{ params: { ano } }" -- $PY -m pytest tests/calendario/test_chamadas_do_calendario.py -q
```

Esperado: (1) `FAILED …test_todas_as_chamadas_do_bolso_apontam_para_rotas_que_existem` com «POST /api/bolso/calendario/ida» na lista dos órfãos (e o novo teste do guarda); (2) `FAILED …test_as_chamadas_do_calendario_levam_o_que_o_servidor_espera`. As duas com «Mutação apanhada».

- [ ] **Passo 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add frontend/src/lib/bolso.js backend/tests/fin/test_caminhos_do_bolso.py backend/tests/calendario/test_chamadas_do_calendario.py
git commit -m "Calendário: chamadas do bolso para o mês, a contagem e as idas

As cinco chamadas novas vivem no lib/bolso.js com o caminho por extenso, e o guarda de
caminhos passa a provar que as vê e que cada uma tem rota no servidor.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Tarefa 11: O menu lateral (☰) e o que os ecrãs do bolso partilham

**Ficheiros:**
- Modificar: `frontend/src/components/ui/sheet.jsx` (`SheetContent`, ~46-58)
- Criar: `frontend/src/pages/bolso/partilhado.js`
- Modificar: `frontend/src/pages/bolso/BolsoApp.js` — imports (~1-6), `ler`/`guardar` (~65-73), `useManifestoDoBolso` (~100-124), `Segmento` dentro de `BarraDeAmbito` (~373-384) e a calha (~415-428), `useAuth` (~436), cabeçalho (~545-549), botão «Terminar sessão» do fundo (~705-719), fim do JSX (~721-731) — números medidos no `main` 57d5f6f; o guião troca por texto exacto, por isso valem só para orientar
- Testes: `backend/tests/calendario/test_menu_do_bolso.py` (criar)

**Interfaces:**
- Consome: `semanasDoMes`, `tituloDoDia` de `@/lib/calendario` (Tarefa 9); `correr_js`, `AXIOS_FABRICADO`, `SESSAO_SIMULADA` (Tarefa 8).
- Produz:
  - `SheetContent` aceita `hideClose` (boolean, por omissão `false` = desenha o fecho de 16 px como sempre)
  - de `pages/bolso/partilhado.js`: `ler(chave, omissao)`, `guardar(chave, valor|null)`, `useManifestoDoBolso()`, `Calha({children})`, `Segmento({activo, onClick, children})`, `DESTINOS = [{caminho: '/bolso', rotulo: 'Faturação', Icone}, {caminho: '/bolso/calendario', rotulo: 'Calendário', Icone}]`, `BotaoMenu({onClick})` (aria-label «Abrir menu»), `MenuLateral({aberto, onFechar, actual})` (fecho com aria-label «Fechar menu»), `GrelhaDoMes({ano, mes, hoje, escolhidos = [], onTocar, pontos = [], corDoPonto = 'bg-destructive', feriados = []})` (cada dia é um `<button data-dia="AAAA-MM-DD" aria-pressed>` de `h-11`; o ponto é um `<span data-ponto>`)

- [ ] **Passo 1: Escrever os testes que falham**

`backend/tests/calendario/test_menu_do_bolso.py`:

```python
"""O menu lateral (☰) da Gestão Lisbonb, montado a sério (jsdom) dentro da Faturação, e as
peças que os dois ecrãs do bolso passam a partilhar (desenho, secção 4)."""
import json

from tests.bolso_js import AXIOS_FABRICADO, SESSAO_SIMULADA, correr_js

PAINEL = {"hoje": "2026-10-27",
          "ambito": {"pedido": "all", "unidade": None, "somadas": [{"id": "c1", "nome": "Fordaimon Foods"}],
                     "sem_acesso": [], "unidades": []},
          "cartoes": {}, "serie_dias": [], "serie_meses": [], "reparticao": [], "reparticao_por": "empresa",
          "dias_sem_vendas": [], "leituras": []}


def _faturacao(tmp_path, cenario):
    """Monta o `BolsoApp` com o servidor fabricado a responder ao painel e corre `cenario`."""
    return correr_js("\n".join([
        "const PAINEL = %s;" % json.dumps(PAINEL),
        "global.SERVIDOR = (metodo, url) => (url === '/painel' ? PAINEL : {});",
        "const BolsoApp = importar('pages/bolso/BolsoApp').default;",
        "await montar(React.createElement(BolsoApp));",
        "await esperar();",
        cenario,
    ]), tmp_path, simulados=dict(SESSAO_SIMULADA, axios=AXIOS_FABRICADO), dom=True)


def test_o_menu_abre_com_faturacao_calendario_e_terminar_sessao(tmp_path):
    r = _faturacao(tmp_path, """
const antes = !!document.querySelector('[role="dialog"]');
await clicar(botao('Abrir menu'));
const menu = document.querySelector('[role="dialog"]');
devolve({
  antes,
  titulo: menu.querySelector('h2').textContent,
  itens: [...menu.querySelectorAll('nav button')].map((b) => b.textContent.trim()),
  actual: menu.querySelector('[aria-current="page"]').textContent.trim(),
  sair: [...menu.querySelectorAll('button')].some((b) => b.textContent.includes('Terminar sessão')),
  fechoGrande: botao('Fechar menu', menu).className.includes('h-11 w-11'),
  fechoPequeno: [...menu.querySelectorAll('.sr-only')].some((s) => s.textContent === 'Close'),
});
""")
    assert r == {"antes": False, "titulo": "Gestão Lisbonb", "itens": ["Faturação", "Calendário"],
                 "actual": "Faturação", "sair": True, "fechoGrande": True, "fechoPequeno": False}


def test_tocar_no_calendario_fecha_o_menu_e_navega(tmp_path):
    r = _faturacao(tmp_path, """
await clicar(botao('Abrir menu'));
await clicar(botao('Calendário', document.querySelector('[role="dialog"]')));
devolve({ aberto: !!document.querySelector('[role="dialog"]'), registo: REGISTO.filter((x) => x[0] === 'navigate') });
""")
    assert r == {"aberto": False, "registo": [["navigate", "/bolso/calendario"]]}


def test_terminar_sessao_sai_e_vai_para_o_login(tmp_path):
    r = _faturacao(tmp_path, """
await clicar(botao('Abrir menu'));
await clicar([...document.querySelectorAll('[role="dialog"] button')].find((b) => b.textContent.includes('Terminar sessão')));
devolve(REGISTO.filter((x) => x[0] !== 'GET'));
""")
    assert r == [["logout"], ["navigate", "/login"]]


def test_a_faturacao_continua_igual_por_baixo(tmp_path):
    """O que saiu do BolsoApp para o partilhado.js (o Segmento e a calha) continua a desenhar
    a barra das empresas; e o «Terminar sessão» do fundo passou para o menu (um sítio só)."""
    r = _faturacao(tmp_path, """
devolve({
  grupo: botao('Grupo').getAttribute('aria-pressed'),
  empresa: botao('Fordaimon').getAttribute('aria-pressed'),
  sairNoFundo: [...document.querySelectorAll('main button')].some((b) => b.textContent.includes('Terminar sessão')),
  titulo: document.title,
});
""")
    assert r == {"grupo": "true", "empresa": "false", "sairNoFundo": False, "titulo": "Gestão Lisbonb"}


def test_o_sheet_por_omissao_continua_a_desenhar_o_seu_fecho(tmp_path):
    r = correr_js("""
const S = importar('components/ui/sheet');
await montar(React.createElement(S.Sheet, { open: true },
  React.createElement(S.SheetContent, null, React.createElement(S.SheetTitle, null, 'Outro ecrã'))));
devolve([...document.querySelectorAll('[role="dialog"] .sr-only')].map((s) => s.textContent));
""", tmp_path, dom=True)
    assert r == ["Close"]


def test_ler_e_guardar_aguentam_um_localstorage_que_rebenta(tmp_path):
    r = correr_js("""
Object.defineProperty(global, 'localStorage', { get() { throw new Error('modo privado'); }, configurable: true });
const { ler, guardar } = importar('pages/bolso/partilhado');
guardar('x', '1');
devolve(ler('x', 'por omissão'));
""", tmp_path, simulados=SESSAO_SIMULADA, dom=True)
    assert r == "por omissão"
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_menu_do_bolso.py -q
```

Esperado: `5 failed, 1 passed` — «clicar: não encontrei o elemento» (não há ☰), `sairNoFundo: True`, «Não encontrei …/pages/bolso/partilhado»; passa só o do `Sheet` por omissão (que já desenha o fecho).

- [ ] **Passo 3: O `SheetContent` com `hideClose`**

Em `frontend/src/components/ui/sheet.jsx`, substituir:

```jsx
const SheetContent = React.forwardRef(({ side = "right", className, children, ...props }, ref) => (
  <SheetPortal>
    <SheetOverlay />
    <SheetPrimitive.Content ref={ref} className={cn(sheetVariants({ side }), className)} {...props}>
      <SheetPrimitive.Close
        className="absolute right-4 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:pointer-events-none data-[state=open]:bg-secondary">
        <X className="h-4 w-4" />
        <span className="sr-only">Close</span>
      </SheetPrimitive.Close>
      {children}
```

por:

```jsx
// `hideClose`: quem desenha o seu próprio botão de fechar (o bolso, com 44 px para o polegar)
// dispensa o de 16 px. Por omissão fica tudo como era.
const SheetContent = React.forwardRef(({ side = "right", className, children, hideClose = false, ...props }, ref) => (
  <SheetPortal>
    <SheetOverlay />
    <SheetPrimitive.Content ref={ref} className={cn(sheetVariants({ side }), className)} {...props}>
      {!hideClose && (
        <SheetPrimitive.Close
          className="absolute right-4 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:pointer-events-none data-[state=open]:bg-secondary">
          <X className="h-4 w-4" />
          <span className="sr-only">Close</span>
        </SheetPrimitive.Close>
      )}
      {children}
```

- [ ] **Passo 4: O `partilhado.js`**

`frontend/src/pages/bolso/partilhado.js`:

```js
import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { CalendarDays, Menu, Receipt, X } from 'lucide-react';
import { Sheet, SheetClose, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { useAuth } from '@/contexts/AuthContext';
import { semanasDoMes, tituloDoDia } from '@/lib/calendario';

// O que os ecrãs da Gestão Lisbonb (`/bolso` e `/bolso/calendario`) partilham: o manifesto,
// a memória do `localStorage`, o segmento das calhas, o menu lateral e a grelha do mês.

// O `localStorage` pode não existir ou rebentar (modo privado, dados bloqueados): lê-se e
// grava-se sempre dentro de try/catch, e o ecrã funciona sem ele.
export const ler = (chave, omissao) => {
  try { return localStorage.getItem(chave) ?? omissao; } catch (e) { return omissao; }
};
export const guardar = (chave, valor) => {
  try {
    if (valor === null) localStorage.removeItem(chave);
    else localStorage.setItem(chave, valor);
  } catch (e) { /* modo privado */ }
};

// O manifesto do portal aponta para o POS (`start_url: /faturacao/pos`). Sem esta troca,
// "Adicionar ao Ecrã Principal" a partir daqui instalava um ícone que **abre o balcão da
// loja** — o manifesto é que manda, não o endereço que está à frente.
export function useManifestoDoBolso() {
  useEffect(() => {
    const link = document.querySelector('link[rel="manifest"]');
    const anterior = link ? link.getAttribute('href') : null;
    if (link) link.setAttribute('href', '/bolso-manifest.json');

    // O iPhone ignora o `icons` do manifesto e usa o `apple-touch-icon`.
    const apple = document.createElement('link');
    apple.rel = 'apple-touch-icon';
    apple.href = '/icones/bolso-180.png';
    document.head.appendChild(apple);

    const titulo = document.title;
    document.title = 'Gestão Lisbonb';
    return () => {
      if (link && anterior) link.setAttribute('href', anterior);
      apple.remove();
      document.title = titulo;
    };
  }, []);
}

// A calha dos segmentos: `h-12` com `p-0.5` deixa cada segmento com 44px — o mínimo do iOS,
// medido no ecrã. Com `h-11 p-[3px]` ficavam em 38 e nenhum teste apanhava isso.
export function Calha({ children }) {
  return <div className="flex bg-muted rounded-xl p-0.5 h-12">{children}</div>;
}

// Uma só língua de selecção: `bg-primary` com o texto do portal — excepto no tema escuro,
// onde o `--primary` é um azul claro e branco por cima dá 3,4:1; aí o texto passa a ser o
// fundo da página (5,6:1, medido). O que NÃO está escolhido fica em `text-foreground`: sobre
// `bg-muted` no escuro o `text-muted-foreground` dava 3,4:1.
export function Segmento({ activo, onClick, children }) {
  return (
    <button
      type="button" onClick={onClick} aria-pressed={activo}
      className={`flex-1 min-w-0 h-full rounded-lg px-1 text-[13px] font-semibold truncate
                  transition-colors duration-150
                  focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset ${
        activo ? 'bg-primary text-primary-foreground dark:text-background' : 'text-foreground'
      }`}
    >
      {children}
    </button>
  );
}

// As secções da app. O teste `test_ecra_do_calendario.py` confronta cada caminho com o
// `App.js`: um destino sem rota abria um ecrã em branco sem nada partir.
export const DESTINOS = [
  { caminho: '/bolso', rotulo: 'Faturação', Icone: Receipt },
  { caminho: '/bolso/calendario', rotulo: 'Calendário', Icone: CalendarDays },
];

export function BotaoMenu({ onClick }) {
  return (
    <button
      type="button" onClick={onClick} aria-label="Abrir menu"
      className="h-11 w-11 shrink-0 inline-flex items-center justify-center rounded-lg active:bg-accent/60
                 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <Menu className="h-5 w-5" />
    </button>
  );
}

// O menu lateral (☰). O `SheetContent` não desenha o fecho de 16px (`hideClose`): o daqui
// tem 44px, e o conteúdo respeita a zona da notch (a casca pinta até às bordas).
export function MenuLateral({ aberto, onFechar, actual }) {
  const navigate = useNavigate();
  const { logout, user } = useAuth();
  const ir = (caminho) => {
    onFechar();
    if (caminho !== actual) navigate(caminho);
  };
  return (
    <Sheet open={aberto} onOpenChange={(v) => { if (!v) onFechar(); }}>
      <SheetContent side="left" hideClose aria-describedby={undefined} className="p-0 w-[80%] max-w-xs">
        <div className="flex h-full flex-col safe-area-inset-top safe-area-inset-bottom">
          <div className="flex items-center gap-2 pl-4 pr-1 h-14 border-b shrink-0">
            <SheetTitle className="flex-1 min-w-0 truncate text-base">Gestão Lisbonb</SheetTitle>
            <SheetClose
              aria-label="Fechar menu"
              className="h-11 w-11 inline-flex items-center justify-center rounded-lg
                         focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <X className="h-5 w-5" />
            </SheetClose>
          </div>
          <nav className="flex-1 py-2">
            {DESTINOS.map(({ caminho, rotulo, Icone }) => (
              <button
                key={caminho} type="button" onClick={() => ir(caminho)}
                aria-current={caminho === actual ? 'page' : undefined}
                className={`w-full h-12 px-4 flex items-center gap-3 text-left text-[15px] font-semibold
                            active:bg-accent/60 focus-visible:outline-none focus-visible:ring-2
                            focus-visible:ring-ring focus-visible:ring-inset ${caminho === actual ? 'bg-accent' : ''}`}
              >
                <Icone className="h-5 w-5 text-muted-foreground" />
                {rotulo}
              </button>
            ))}
          </nav>
          {/* Sair é raro e irreversível: fica no fundo, e sem vermelho (no bolso o vermelho
              quer dizer outra coisa — faturação a descer, buraco por tapar). */}
          <button
            type="button" onClick={() => { onFechar(); logout(); navigate('/login'); }}
            className="h-14 shrink-0 border-t px-4 flex items-center justify-between gap-3 text-left
                       active:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span className="text-[13px] text-muted-foreground truncate">{user?.name || ''}</span>
            <span className="text-[15px] font-semibold shrink-0">Terminar sessão</span>
          </button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

const LETRAS = ['S', 'T', 'Q', 'Q', 'S', 'S', 'D'];

// A grelha do mês, própria (não o `ui/calendar.jsx`: o react-day-picker 8 declara o date-fns
// 2/3 e o instalado é o 4). Dias de 44px; feriados noutra cor; `pontos` com a cor do filtro.
// Serve o ecrã (um dia escolhido) e o painel da ida (vários).
export function GrelhaDoMes({
  ano, mes, hoje, escolhidos = [], onTocar, pontos = [], corDoPonto = 'bg-destructive', feriados = [],
}) {
  return (
    <div>
      <div className="grid grid-cols-7 pb-1 text-center text-[11px] font-semibold text-muted-foreground" aria-hidden="true">
        {LETRAS.map((letra, i) => <span key={i}>{letra}</span>)}
      </div>
      {semanasDoMes(ano, mes).map((semana) => (
        <div key={semana.find(Boolean)} className="grid grid-cols-7 gap-0.5">
          {semana.map((iso, i) => {
            if (!iso) return <span key={`vazio-${i}`} />;
            const escolhido = escolhidos.includes(iso);
            const feriado = feriados.includes(iso);
            const ponto = pontos.includes(iso);
            return (
              <button
                key={iso} type="button" data-dia={iso} aria-pressed={escolhido} onClick={() => onTocar(iso)}
                aria-label={`${tituloDoDia(iso)}${feriado ? ', feriado' : ''}${ponto ? ', com marcação' : ''}`}
                className={`relative h-11 w-full rounded-lg text-[15px] tabular-nums transition-colors duration-150
                            focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                  escolhido ? 'bg-primary text-primary-foreground dark:text-background font-bold'
                    : feriado ? 'text-warning-strong font-semibold' : 'text-foreground'
                } ${iso === hoje && !escolhido ? 'ring-1 ring-inset ring-primary font-bold' : ''}`}
              >
                {Number(iso.slice(8))}
                {ponto && (
                  <span
                    data-ponto="" aria-hidden="true"
                    className={`absolute bottom-1 left-1/2 h-1.5 w-1.5 -translate-x-1/2 rounded-full ${
                      escolhido ? 'bg-current' : corDoPonto}`}
                  />
                )}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Passo 5: O `BolsoApp.js` passa a usar o `partilhado.js` e ganha o ☰**

São oito trocas exactas; o guião pára se alguma não casar uma e uma só vez (nesse caso, abrir o ficheiro e fazer a troca à mão com o mesmo resultado):

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/frontend/src/pages/bolso && python3 - <<'PY'
from pathlib import Path
p = Path("BolsoApp.js"); t = p.read_text(encoding="utf-8")
def troca(velho, novo):
    global t
    assert t.count(velho) == 1, velho[:80]
    t = t.replace(velho, novo)
# 1. importa as peças partilhadas
troca("import { euros, getPainel, percentagem, quandoFoi, TIMEOUT_MS } from '@/lib/bolso';\n",
      "import { euros, getPainel, percentagem, quandoFoi, TIMEOUT_MS } from '@/lib/bolso';\n"
      "import { BotaoMenu, Calha, MenuLateral, Segmento, guardar, ler, useManifestoDoBolso } from './partilhado';\n")
# 2. ler/guardar saem (vivem no partilhado.js)
troca("""const ler = (chave, omissao) => {
  try { return localStorage.getItem(chave) ?? omissao; } catch (e) { return omissao; }
};
const guardar = (chave, valor) => {
  try {
    if (valor === null) localStorage.removeItem(chave);
    else localStorage.setItem(chave, valor);
  } catch (e) { /* modo privado */ }
};

""", "")
# 3. useManifestoDoBolso sai (com o comentário dele)
i = t.index("// O manifesto do portal aponta para o POS")
j = t.index("// --- Peças ---")
t = t[:i] + t[j:]
# 4. o Segmento de dentro da BarraDeAmbito sai (é o do partilhado.js)
troca("""  const Segmento = ({ activo, onClick, children }) => (
    <button
      type="button" onClick={onClick} aria-pressed={activo}
      className={`flex-1 min-w-0 h-full rounded-lg px-1 text-[13px] font-semibold truncate
                  transition-colors duration-150
                  focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset ${
        activo ? 'bg-primary text-primary-foreground dark:text-background' : 'text-foreground'
      }`}
    >
      {children}
    </button>
  );

""", "")
# 5. a calha passa a ser a Calha partilhada (o comentário dos 44px foi com ela)
troca("""        {/* `h-12` com `p-0.5`: a calha tem 48px e o enchimento come 4, o que
            deixa cada segmento com 44 — o mínimo do iOS, medido no ecrã. Com
            `h-11 p-[3px]` ficavam em 38 e nenhum teste apanhava isso. */}
        <div className="flex bg-muted rounded-xl p-0.5 h-12">""", "        <Calha>")
troca("""            </Segmento>
          ))}
        </div>
      </div>
    </nav>""", """            </Segmento>
          ))}
        </Calha>
      </div>
    </nav>""")
# 6. o estado do menu (o `user` deixa de ser preciso aqui: o nome vai no menu)
troca("  const { logout, user } = useAuth();\n", "  const { logout } = useAuth();\n  const [menu, setMenu] = useState(false);\n")
# 7. o ☰ no cabeçalho, à esquerda do nome do âmbito
troca("""        <div className="flex items-center gap-1 px-3 h-14">
          <div className="min-w-0 flex-1">
            <h1 className="font-heading font-bold text-base leading-tight truncate">{nomeDoAmbito}</h1>""",
"""        <div className="flex items-center gap-1 pl-1 pr-3 h-14">
          <BotaoMenu onClick={() => setMenu(true)} />
          <div className="min-w-0 flex-1">
            <h1 className="font-heading font-bold text-base leading-tight truncate">{nomeDoAmbito}</h1>""")
# 8. o «Terminar sessão» do fundo sai (passa para o menu) e o menu entra no fim
i = t.index("        {/* Sair é raro e é irreversível.")
j = t.index("      </main>")
t = t[:i] + t[j:]
troca("""        onLoja={escolherUnidade}
      />
    </div>
  );
}""", """        onLoja={escolherUnidade}
      />

      <MenuLateral aberto={menu} onFechar={() => setMenu(false)} actual="/bolso" />
    </div>
  );
}""")
p.write_text(t, encoding="utf-8")
print("BolsoApp.js: 8 trocas feitas")
PY
grep -n "partilhado\|BotaoMenu\|MenuLateral\|<Calha>\|const Segmento\|Terminar sessão\|useManifestoDoBolso" BolsoApp.js
```

Esperado no `grep`: o import do `./partilhado` (~7), `useManifestoDoBolso();` (só a chamada, dentro de `BolsoApp`), `<Calha>` uma vez, `<BotaoMenu …>` no cabeçalho e `<MenuLateral …>` no fim; nenhuma `const Segmento` e nenhum «Terminar sessão».

- [ ] **Passo 6: Correr e ver passar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_menu_do_bolso.py tests/fin/test_caminhos_do_bolso.py -q -rs
```

Esperado: `10 passed`, sem `skipped`.

- [ ] **Passo 7: Prova por mutação**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PY=~/Developer/RH/backend/.venv/bin/python
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py ../frontend/src/components/ui/sheet.jsx '{!hideClose && (' '{true && (' -- $PY -m pytest tests/calendario/test_menu_do_bolso.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py ../frontend/src/pages/bolso/partilhado.js 'if (caminho !== actual) navigate(caminho);' 'if (caminho === actual) navigate(caminho);' -- $PY -m pytest tests/calendario/test_menu_do_bolso.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py ../frontend/src/pages/bolso/partilhado.js "onFechar(); logout(); navigate('/login');" "onFechar(); navigate('/login');" -- $PY -m pytest tests/calendario/test_menu_do_bolso.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py ../frontend/src/pages/bolso/partilhado.js 'try { return localStorage.getItem(chave) ?? omissao; } catch (e) { return omissao; }' 'return localStorage.getItem(chave) ?? omissao;' -- $PY -m pytest tests/calendario/test_menu_do_bolso.py -q
```

Esperado: (1) `FAILED …test_o_menu_abre…` (`fechoPequeno: True`); (2) `FAILED …test_tocar_no_calendario…`; (3) `FAILED …test_terminar_sessao…`; (4) `FAILED …test_ler_e_guardar_aguentam…`. Todas com «Mutação apanhada».

- [ ] **Passo 8: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add frontend/src/components/ui/sheet.jsx frontend/src/pages/bolso/partilhado.js frontend/src/pages/bolso/BolsoApp.js backend/tests/calendario/test_menu_do_bolso.py
git commit -m "Bolso: menu lateral com Faturação, Calendário e Terminar sessão

A app dos gestores passa a ter mais do que um ecrã. O que os dois partilham (manifesto,
memória do localStorage, segmentos, grelha do mês e o menu) sai do BolsoApp para um
partilhado.js; o menu abre à esquerda com fecho de 44 px e respeita a zona da notch, e
o Sheet ganha a opção de não desenhar o seu fecho de 16 px (por omissão fica igual).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Tarefa 12: O painel da ida — tapar, marcar, editar e apagar

**Ficheiros:**
- Criar: `frontend/src/pages/bolso/PainelIda.js`
- Testes: `backend/tests/calendario/test_painel_da_ida.py` (criar)

**Interfaces:**
- Consome: `criarIdas`, `mudarIda`, `apagarIda` de `@/lib/bolso` (Tarefa 10); `feriadosDoMes`, `mensagemDeErro`, `outrosDiasComBuraco`, `pessoasIniciais`, `textoDoAtalho`, `tituloDoDia` de `@/lib/calendario` (Tarefa 9); `GrelhaDoMes` de `./partilhado` e `SheetContent hideClose` (Tarefa 11).
- Produz: `export default function PainelIda({ painel, dados, hoje, onFechar, onGuardado, onSemSessao })`
  - `painel = { modo: 'tapar' | 'marcar' | 'editar', nomeDaLoja?: string, inicial: { datas: [iso], location_id, inicio, fim, user_ids?: [id], ida_id?: string, nome?: string } }` — no modo `marcar`, `location_id`, `inicio` e `fim` chegam vazios (`''`): escolher a loja enche as horas com o horário dela no `datas[0]` (tirado de `dados.dias`), e trocar de loja volta a enchê-las enquanto ninguém lhes mexeu
  - `dados` = a resposta do mês (`resposta_do_mes`); `onGuardado()` chamado depois de o servidor aceitar; `onFechar()` ao fechar sem gravar; `onSemSessao()` quando o servidor responde 401 (sessão expirada — não é um erro do formulário)
  - cores: o erro e o «Apagar» em `text-destructive-strong dark:text-destructive` (sobre o fundo do painel, `bg-background`: 6,2:1 no claro e 4,7:1 no escuro; o `text-destructive` sozinho dá 3,8:1 no claro, e o `-strong` sozinho 3,0:1 no escuro)
  - controlos com nomes acessíveis estáveis (usados nos testes e no ensaio): `select[aria-label="Loja"]`, `input[aria-label="Hora de início"]`, `input[aria-label="Hora de fim"]`, botões das pessoas pelo nome, dias `[data-dia]`, botão do atalho pelo texto de `textoDoAtalho`, «Marcar N idas»/«Marcar 1 ida», «Guardar», «Apagar» → «Tocar de novo para apagar», «Fechar», erro em `[role="alert"]`

- [ ] **Passo 1: Escrever os testes que falham**

`backend/tests/calendario/test_painel_da_ida.py`:

```python
"""O painel de uma ida (`pages/bolso/PainelIda.js`) montado num DOM, com o servidor fabricado
à frente do axios do `lib/bolso.js` e o mês tal como o servidor o calcula (desenho, secção 4,
«Tapar um buraco»)."""
import json

import calendario
from tests.bolso_js import AXIOS_FABRICADO, correr_js

from . import dados_semana_normal as sn

ATALHO = "Também nas outras terças deste mês com buraco em Oeiras"
TAPAR_OEIRAS = {"modo": "tapar", "nomeDaLoja": "Oeiras",
                "inicial": {"datas": ["2026-10-06"], "location_id": sn.OEIRAS, "inicio": "13:00", "fim": "22:00"}}
IDA = {"modo": "editar", "inicial": {"ida_id": "i-1", "datas": ["2026-10-06"], "location_id": sn.OEIRAS,
                                     "user_ids": [sn.DEBORA], "inicio": "13:00", "fim": "22:00",
                                     "nome": "Débora Ferreira"}}


def _mes(idas=()):
    dados = sn.semana_normal()
    dados["idas"] = list(idas)
    return calendario.resposta_do_mes(2026, 10, dados, sn.DEBORA, True)


def _painel(tmp_path, painel, cenario, resposta=None, idas=()):
    """Monta o PainelIda com `painel` e corre `cenario` (que tem `dlg`, o diálogo); o servidor
    fabricado responde `resposta` a todos os pedidos."""
    return correr_js("\n".join([
        "const DADOS = %s;" % json.dumps(_mes(idas), ensure_ascii=False),
        "const PAINEL = %s;" % json.dumps(painel, ensure_ascii=False),
        "const RESPOSTA = %s;" % json.dumps({} if resposta is None else resposta, ensure_ascii=False),
        "global.SERVIDOR = () => RESPOSTA;",
        "const PainelIda = importar('pages/bolso/PainelIda').default;",
        "await montar(React.createElement(PainelIda, { painel: PAINEL, dados: DADOS, hoje: '2026-10-27',",
        "  onFechar: () => REGISTO.push(['fechar']), onGuardado: () => REGISTO.push(['guardado']),",
        "  onSemSessao: () => REGISTO.push(['sem-sessao']) }));",
        "const dlg = document.querySelector('[role=\"dialog\"]');",
        cenario,
    ]), tmp_path, simulados={"axios": AXIOS_FABRICADO}, dom=True)


def test_tapar_comeca_no_buraco_e_em_mim(tmp_path):
    r = _painel(tmp_path, TAPAR_OEIRAS, """
devolve({
  titulo: dlg.querySelector('h2').textContent,
  loja: dlg.querySelector('[aria-label="Loja"]').value,
  inicio: dlg.querySelector('[aria-label="Hora de início"]').value,
  fim: dlg.querySelector('[aria-label="Hora de fim"]').value,
  escolhidas: [...dlg.querySelectorAll('fieldset button[aria-pressed="true"]')].map((b) => b.textContent),
  grupos: [...dlg.querySelectorAll('fieldset p')].map((p) => p.textContent),
  primeiraPessoa: dlg.querySelector('fieldset button').textContent,
  dias: [...dlg.querySelectorAll('[data-dia][aria-pressed="true"]')].map((b) => b.getAttribute('data-dia')),
  fechoGrande: !!botao('Fechar', dlg),
  fechoPequeno: [...dlg.querySelectorAll('.sr-only')].some((s) => s.textContent === 'Close'),
});
""")
    assert r == {"titulo": "Tapar Oeiras", "loja": sn.OEIRAS, "inicio": "13:00", "fim": "22:00",
                 "escolhidas": ["Débora Ferreira"], "grupos": ["Gestores", "Colaboradores"],
                 "primeiraPessoa": "Carol Santos", "dias": ["2026-10-06"],
                 "fechoGrande": True, "fechoPequeno": False}


def test_o_atalho_marca_as_outras_tercas_e_marcar_manda_uma_ida_por_dia(tmp_path):
    r = _painel(tmp_path, TAPAR_OEIRAS, """
await clicar(botao('%s', dlg));
const dias = [...dlg.querySelectorAll('[data-dia][aria-pressed="true"]')].map((b) => b.getAttribute('data-dia'));
const atalhoDepois = !!botao('%s', dlg);
await clicar(botao('Marcar 4 idas', dlg));
await esperar();
devolve({ dias, atalhoDepois, registo: REGISTO });
""" % (ATALHO, ATALHO), resposta={"criadas": 4})
    assert r["dias"] == ["2026-10-06", "2026-10-13", "2026-10-20", "2026-10-27"]
    assert r["atalhoDepois"] is False
    assert r["registo"] == [
        ["POST", "/calendario/idas", {"datas": ["2026-10-06", "2026-10-13", "2026-10-20", "2026-10-27"],
                                      "location_id": sn.OEIRAS, "user_ids": [sn.DEBORA],
                                      "inicio": "13:00", "fim": "22:00"}, None],
        ["guardado"]]


def test_o_atalho_so_conta_as_tercas_cujo_buraco_contem_as_horas(tmp_path):
    r = _painel(tmp_path, TAPAR_OEIRAS, """
await clicar(botao('%s', dlg));
devolve([...dlg.querySelectorAll('[data-dia][aria-pressed="true"]')].map((b) => b.getAttribute('data-dia')));
""" % ATALHO, idas=[sn.ida("2026-10-20", sn.OEIRAS, sn.CAROL, "13:00", "17:00")])
    assert r == ["2026-10-06", "2026-10-13", "2026-10-27"]


def test_o_erro_do_servidor_aparece_em_texto_e_o_painel_fica_aberto(tmp_path):
    texto = "Débora já está em Alfragide das 10h às 14h a 06/10.\nMude as horas ou apague primeiro a outra ida."
    r = _painel(tmp_path, TAPAR_OEIRAS, """
await clicar(botao('Marcar 1 ida', dlg));
await esperar();
const alerta = dlg.querySelector('[role="alert"]');
devolve({ alerta: alerta.textContent, aberto: !!document.querySelector('[role="dialog"]'),
          activo: !botao('Marcar 1 ida', dlg).disabled, registo: REGISTO.map((x) => x[0]),
          cor: [...alerta.classList].filter((c) => c.includes('destructive')) });
""", resposta={"erro": {"response": {"status": 409, "data": {"detail": texto}}}})
    # A cor é o par medido (6,2:1 no claro, 4,7:1 no escuro); o `text-destructive` sozinho dá
    # 3,8:1 no claro e o `-strong` sozinho 3,0:1 no escuro.
    assert r == {"alerta": texto, "aberto": True, "activo": True, "registo": ["POST"],
                 "cor": ["text-destructive-strong", "dark:text-destructive"]}


def test_sessao_expirada_ao_gravar_sai_pela_porta_da_sessao_e_nao_e_erro_do_formulario(tmp_path):
    r = _painel(tmp_path, TAPAR_OEIRAS, """
await clicar(botao('Marcar 1 ida', dlg));
await esperar();
devolve({ alerta: !!dlg.querySelector('[role="alert"]'), registo: REGISTO.map((x) => x[0]) });
""", resposta={"erro": {"response": {"status": 401, "data": {"detail": "Token expirado"}}}})
    assert r == {"alerta": False, "registo": ["POST", "sem-sessao"]}


def test_sem_rede_diz_que_nao_houve_resposta(tmp_path):
    r = _painel(tmp_path, TAPAR_OEIRAS, """
await clicar(botao('Marcar 1 ida', dlg));
await esperar();
devolve(dlg.querySelector('[role="alert"]').textContent);
""", resposta={"erro": {"message": "Network Error"}})
    assert r == "Sem resposta do servidor. Verifique a rede e tente outra vez."


def test_no_maximo_duas_pessoas(tmp_path):
    r = _painel(tmp_path, TAPAR_OEIRAS, """
await clicar(botao('Carol Santos', dlg));
await clicar(botao('Guilherme Gestor', dlg));
devolve({ escolhidas: [...dlg.querySelectorAll('fieldset button[aria-pressed="true"]')].map((b) => b.textContent),
          aviso: texto().includes('No máximo duas pessoas de cada vez.'), marcar: !!botao('Marcar 2 idas', dlg) });
""")
    assert r == {"escolhidas": ["Carol Santos", "Débora Ferreira"], "aviso": True, "marcar": True}


def test_editar_guarda_uma_ida_com_o_que_mudou(tmp_path):
    r = _painel(tmp_path, IDA, """
await escrever(dlg.querySelector('[aria-label="Hora de início"]'), '15:00');
await clicar(botao('Carol Santos', dlg));
await clicar(dlg.querySelector('[data-dia="2026-10-13"]'));
const titulo = dlg.querySelector('h2').textContent;
await clicar(botao('Guardar', dlg));
await esperar();
devolve({ titulo, registo: REGISTO });
""")
    assert r == {"titulo": "Ida de Débora Ferreira", "registo": [
        ["PUT", "/calendario/idas/i-1", {"data": "2026-10-13", "location_id": sn.OEIRAS, "user_id": sn.CAROL,
                                         "inicio": "15:00", "fim": "22:00"}, None],
        ["guardado"]]}


def test_apagar_pede_dois_toques(tmp_path):
    r = _painel(tmp_path, IDA, """
const cor = [...botao('Apagar', dlg).classList].filter((c) => c.includes('destructive'));
await clicar(botao('Apagar', dlg));
const depoisDeUm = REGISTO.length;
await clicar(botao('Tocar de novo para apagar', dlg));
await esperar();
devolve({ cor, depoisDeUm, registo: REGISTO });
""")
    assert r == {"cor": ["text-destructive-strong", "dark:text-destructive"], "depoisDeUm": 0,
                 "registo": [["DELETE", "/calendario/idas/i-1", None, None], ["guardado"]]}


def test_marcar_de_raiz_comeca_sem_loja_e_as_horas_vem_da_loja_escolhida(tmp_path):
    # Desenho, secção 4: «+ Marcar ida abre o mesmo painel vazio, com a loja a escolher».
    painel = {"modo": "marcar", "inicial": {"datas": ["2026-10-27"], "location_id": "", "inicio": "", "fim": ""}}
    r = _painel(tmp_path, painel, """
const campo = (rotulo) => dlg.querySelector('[aria-label="' + rotulo + '"]');
const horas = () => [campo('Hora de início').value, campo('Hora de fim').value];
const vazio = { loja: campo('Loja').value, horas: horas(), bloqueado: botao('Marcar 1 ida', dlg).disabled };
await escrever(campo('Loja'), '%s');
const benfica = horas();
await escrever(campo('Loja'), '%s');
const alfragide = horas();
await escrever(campo('Hora de início'), '15:00');
await escrever(campo('Loja'), '%s');
const mexidas = horas();
await clicar(botao('Marcar 1 ida', dlg));
await esperar();
devolve({ titulo: dlg.querySelector('h2').textContent, vazio, benfica, alfragide, mexidas, corpo: REGISTO[0][2] });
""" % (sn.BENFICA, sn.ALFRAGIDE, sn.OEIRAS))
    assert r["titulo"] == "Marcar ida"
    assert r["vazio"] == {"loja": "", "horas": ["", ""], "bloqueado": True}
    # Benfica e Alfragide a 27/10: o horário de cada uma. Depois de mexer nas horas, trocar
    # de loja já não as apaga.
    assert (r["benfica"], r["alfragide"], r["mexidas"]) == (
        ["13:00", "22:00"], ["10:00", "23:00"], ["15:00", "23:00"])
    assert r["corpo"] == {"datas": ["2026-10-27"], "location_id": sn.OEIRAS, "user_ids": [sn.DEBORA],
                          "inicio": "15:00", "fim": "23:00"}
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_painel_da_ida.py -q
```

Esperado: `10 failed`, cada um com «Não encontrei …/pages/bolso/PainelIda».

- [ ] **Passo 3: Implementação**

`frontend/src/pages/bolso/PainelIda.js`:

```js
import React, { useState } from 'react';
import { Loader2, X } from 'lucide-react';
import { Sheet, SheetClose, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { apagarIda, criarIdas, mudarIda } from '@/lib/bolso';
import {
  feriadosDoMes, mensagemDeErro, outrosDiasComBuraco, pessoasIniciais, textoDoAtalho, tituloDoDia,
} from '@/lib/calendario';
import { GrelhaDoMes } from './partilhado';

// O painel de uma ida: **tapar** um buraco (a loja e as horas vêm do buraco), **marcar** uma
// ida de raiz, ou **editar** uma que já existe (Guardar e Apagar; um dia, uma pessoa).
//
// O servidor é que decide se a ida é possível (sobreposição, férias, loja fechada) e diz
// porquê; o painel mostra esse texto tal como vem e fica aberto para se corrigir.
//
// `painel`: { modo: 'tapar' | 'marcar' | 'editar', nomeDaLoja?, inicial: { datas, location_id,
// inicio, fim, user_ids?, ida_id?, nome? } }. Monta-se de novo a cada abertura (o ecrã dá-lhe
// uma `key`), por isso o estado começa sempre no `inicial`. No `marcar` a loja e as horas
// chegam vazias (desenho, secção 4: «o mesmo painel vazio, com a loja a escolher»).
//
// Vermelho de texto: `text-destructive-strong dark:text-destructive`, o par que passa sobre o
// fundo do painel nos dois temas (6,2:1 e 4,7:1). O `text-destructive` sozinho dá 3,8:1 no
// claro; o `-strong` do escuro foi afinado para texto BRANCO sobre pastilha e dá 3,0:1 como
// texto (index.css, `--destructive-strong`).

const MAXIMO_DE_PESSOAS = 2; // o servidor recusa mais (POST /api/bolso/calendario/idas)

export default function PainelIda({ painel, dados, hoje, onFechar, onGuardado, onSemSessao }) {
  const { modo, inicial } = painel;
  const editar = modo === 'editar';
  const [loja, setLoja] = useState(inicial.location_id || '');
  const [pessoas, setPessoas] = useState(() => inicial.user_ids || pessoasIniciais(dados));
  const [inicio, setInicio] = useState(inicial.inicio || '');
  const [fim, setFim] = useState(inicial.fim || '');
  const [datas, setDatas] = useState(inicial.datas || []);
  const [aGravar, setAGravar] = useState(false);
  const [erro, setErro] = useState(null);
  const [aviso, setAviso] = useState(null);
  const [confirmarApagar, setConfirmarApagar] = useState(false);

  const nomeDaLoja = (dados.lojas || []).find((l) => l.id === loja)?.nome || '';
  const base = (inicial.datas || [])[0];
  const outros = editar ? [] : outrosDiasComBuraco(dados, base, loja, inicio, fim).filter((d) => !datas.includes(d));
  const quantas = datas.length * pessoas.length;
  const pronto = Boolean(loja && inicio && fim && quantas > 0 && !aGravar);
  const gestores = (dados.pessoas || []).filter((p) => p.tipo === 'gestor');
  const colaboradores = (dados.pessoas || []).filter((p) => p.tipo !== 'gestor');

  const tocarPessoa = (id) => {
    setAviso(null);
    if (editar) { setPessoas([id]); return; }
    if (pessoas.includes(id)) { setPessoas(pessoas.filter((p) => p !== id)); return; }
    if (pessoas.length >= MAXIMO_DE_PESSOAS) { setAviso('No máximo duas pessoas de cada vez.'); return; }
    setPessoas([...pessoas, id]);
  };
  const tocarDia = (iso) => {
    if (editar) { setDatas([iso]); return; }
    setDatas(datas.includes(iso) ? datas.filter((d) => d !== iso) : [...datas, iso].sort());
  };

  // No `marcar`, escolher a loja enche as horas com o horário dela no dia (o primeiro
  // escolhido); trocar de loja volta a enchê-las enquanto forem as da loja anterior. Horas
  // mexidas à mão ficam.
  const horarioDe = (id) => (dados.dias || []).find((d) => d.data === datas[0])
    ?.lojas.find((l) => l.location_id === id && l.estado === 'aberta');
  const escolherLoja = (id) => {
    const antes = horarioDe(loja);
    const nova = horarioDe(id);
    const porMexer = (!inicio && !fim) || (antes && inicio === antes.abre && fim === antes.fecha);
    setLoja(id);
    if (modo === 'marcar' && nova && porMexer) { setInicio(nova.abre); setFim(nova.fecha); }
  };

  // Uma sessão expirada não é um erro do formulário: sai pela mesma porta do ecrã (login).
  const falhou = (e) => {
    if (e?.response?.status === 401) { onSemSessao(); return; }
    setErro(mensagemDeErro(e));
    setAGravar(false);
    setConfirmarApagar(false);
  };

  const gravar = async () => {
    setAGravar(true);
    setErro(null);
    try {
      if (editar) {
        await mudarIda(inicial.ida_id, { data: datas[0], location_id: loja, user_id: pessoas[0], inicio, fim });
      } else {
        await criarIdas({ datas, location_id: loja, user_ids: pessoas, inicio, fim });
      }
      onGuardado();
    } catch (e) {
      falhou(e);
    }
  };

  // Apagar pede dois toques: é irreversível e o botão fica ao lado do Guardar.
  const apagar = async () => {
    if (!confirmarApagar) { setConfirmarApagar(true); return; }
    setAGravar(true);
    setErro(null);
    try {
      await apagarIda(inicial.ida_id);
      onGuardado();
    } catch (e) {
      falhou(e);
    }
  };

  const titulo = editar
    ? `Ida de ${inicial.nome || ''}`.trim()
    : modo === 'tapar' ? `Tapar ${painel.nomeDaLoja || nomeDaLoja}` : 'Marcar ida';
  const rotulo = 'text-[13px] font-semibold text-muted-foreground';
  const campo = 'mt-1 h-11 w-full rounded-lg border bg-background px-3 text-[15px] tabular-nums';

  return (
    <Sheet open onOpenChange={(aberto) => { if (!aberto) onFechar(); }}>
      <SheetContent
        side="bottom" hideClose aria-describedby={undefined}
        className="p-0 gap-0 rounded-t-2xl max-h-[92dvh] flex flex-col"
      >
        <div className="flex items-center gap-2 pl-4 pr-1 h-14 border-b shrink-0">
          <div className="min-w-0 flex-1">
            <SheetTitle className="text-base truncate">{titulo}</SheetTitle>
            {base && <p className="text-[12px] text-muted-foreground truncate first-letter:uppercase">{tituloDoDia(base)}</p>}
          </div>
          <SheetClose
            aria-label="Fechar"
            className="h-11 w-11 inline-flex items-center justify-center rounded-lg
                       focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X className="h-5 w-5" />
          </SheetClose>
        </div>

        <div className="overflow-y-auto px-4 pt-3 pb-4 space-y-4 safe-area-inset-bottom">
          <label className="block">
            <span className={rotulo}>Loja</span>
            <select aria-label="Loja" value={loja} onChange={(e) => escolherLoja(e.target.value)} className={campo}>
              {!loja && <option value="">Escolher…</option>}
              {(dados.lojas || []).map((l) => <option key={l.id} value={l.id}>{l.nome}</option>)}
            </select>
          </label>

          <fieldset>
            <legend className={rotulo}>{editar ? 'Pessoa' : 'Pessoas'}</legend>
            {[['Gestores', gestores], ['Colaboradores', colaboradores]].map(([grupo, lista]) => (
              lista.length > 0 && (
                <div key={grupo} className="mt-1">
                  <p className="text-[11px] text-muted-foreground">{grupo}</p>
                  <div className="mt-1 flex flex-wrap gap-2">
                    {lista.map((p) => (
                      <button
                        key={p.id} type="button" aria-pressed={pessoas.includes(p.id)} onClick={() => tocarPessoa(p.id)}
                        className={`h-11 px-4 rounded-full text-sm font-semibold focus-visible:outline-none
                                    focus-visible:ring-2 focus-visible:ring-ring ${pessoas.includes(p.id)
                          ? 'bg-primary text-primary-foreground dark:text-background' : 'bg-muted text-foreground'}`}
                      >
                        {p.nome}
                      </button>
                    ))}
                  </div>
                </div>
              )
            ))}
            {aviso && <p className="mt-1 text-[12px] text-warning-strong">{aviso}</p>}
          </fieldset>

          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className={rotulo}>Das</span>
              <input type="time" aria-label="Hora de início" value={inicio} onChange={(e) => setInicio(e.target.value)} className={campo} />
            </label>
            <label className="block">
              <span className={rotulo}>Às</span>
              <input type="time" aria-label="Hora de fim" value={fim} onChange={(e) => setFim(e.target.value)} className={campo} />
            </label>
          </div>

          <div>
            <p className={rotulo}>{editar ? 'Dia' : 'Dias'}</p>
            <div className="mt-1 rounded-xl border p-1">
              <GrelhaDoMes
                ano={dados.ano} mes={dados.mes} hoje={hoje} escolhidos={datas} onTocar={tocarDia}
                feriados={feriadosDoMes(dados)}
              />
            </div>
            {outros.length > 0 && (
              <button
                type="button" onClick={() => setDatas([...new Set([...datas, ...outros])].sort())}
                className="mt-2 w-full min-h-11 rounded-lg border px-3 py-2 text-left text-[14px] font-semibold
                           active:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {textoDoAtalho(base, nomeDaLoja)}
              </button>
            )}
          </div>

          {erro && <p role="alert" className="text-[14px] text-destructive-strong dark:text-destructive whitespace-pre-line">{erro}</p>}

          <div className="flex gap-2">
            {editar && (
              <button
                type="button" onClick={apagar} disabled={aGravar}
                className="h-12 px-4 rounded-xl border font-semibold text-destructive-strong dark:text-destructive disabled:opacity-50
                           focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {confirmarApagar ? 'Tocar de novo para apagar' : 'Apagar'}
              </button>
            )}
            <button
              type="button" onClick={gravar} disabled={!pronto}
              className="flex-1 h-12 rounded-xl bg-primary text-primary-foreground dark:text-background font-semibold
                         inline-flex items-center justify-center gap-2 disabled:opacity-50
                         focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {aGravar && <Loader2 className="h-4 w-4 animate-spin" />}
              {editar ? 'Guardar' : `Marcar ${quantas} ${quantas === 1 ? 'ida' : 'idas'}`}
            </button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
```

- [ ] **Passo 4: Correr e ver passar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_painel_da_ida.py -q -rs
```

Esperado: `10 passed`, sem `skipped`.

- [ ] **Passo 5: Prova por mutação**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PY=~/Developer/RH/backend/.venv/bin/python
JS=../frontend/src/pages/bolso/PainelIda.js
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py $JS 'if (pessoas.length >= MAXIMO_DE_PESSOAS)' 'if (false)' -- $PY -m pytest tests/calendario/test_painel_da_ida.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py $JS 'if (!confirmarApagar) { setConfirmarApagar(true); return; }' 'if (false) { setConfirmarApagar(true); return; }' -- $PY -m pytest tests/calendario/test_painel_da_ida.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py $JS '{erro && <p role="alert"' '{false && <p role="alert"' -- $PY -m pytest tests/calendario/test_painel_da_ida.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py $JS 'const outros = editar ? [] : outrosDiasComBuraco(dados, base, loja, inicio, fim)' 'const outros = [].concat([])' -- $PY -m pytest tests/calendario/test_painel_da_ida.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py $JS "if (e?.response?.status === 401) { onSemSessao(); return; }" "if (false) { onSemSessao(); return; }" -- $PY -m pytest tests/calendario/test_painel_da_ida.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py $JS "if (modo === 'marcar' && nova && porMexer)" "if (false)" -- $PY -m pytest tests/calendario/test_painel_da_ida.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py $JS '|| (antes && inicio === antes.abre && fim === antes.fecha)' '|| false' -- $PY -m pytest tests/calendario/test_painel_da_ida.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py $JS 'text-[14px] text-destructive-strong dark:text-destructive whitespace-pre-line' 'text-[14px] text-destructive whitespace-pre-line' -- $PY -m pytest tests/calendario/test_painel_da_ida.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py $JS 'font-semibold text-destructive-strong dark:text-destructive disabled:opacity-50' 'font-semibold text-destructive disabled:opacity-50' -- $PY -m pytest tests/calendario/test_painel_da_ida.py -q
```

Esperado: (1) `FAILED …test_no_maximo_duas_pessoas`; (2) `FAILED …test_apagar_pede_dois_toques` (o DELETE sai ao primeiro toque); (3) `FAILED …test_o_erro_do_servidor…` e `…test_sem_rede…`; (4) `FAILED` nos dois testes do atalho; (5) `FAILED …test_sessao_expirada_ao_gravar…` (aparece «Token expirado» no `[role="alert"]` e nada de `sem-sessao`); (6) `FAILED …test_marcar_de_raiz_comeca_sem_loja…` (as horas ficam `['', '']` depois de escolher Benfica); (7) `FAILED …test_marcar_de_raiz_comeca_sem_loja…` (trocar para Alfragide deixa `['13:00', '22:00']`); (8) `FAILED …test_o_erro_do_servidor…` (`cor` só com `text-destructive`); (9) `FAILED …test_apagar_pede_dois_toques` (idem). Todas com «Mutação apanhada».

- [ ] **Passo 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add frontend/src/pages/bolso/PainelIda.js backend/tests/calendario/test_painel_da_ida.py
git commit -m "Calendário: painel para tapar um buraco, marcar, mudar ou apagar uma ida

Tapar começa nas horas do buraco e na própria gestora; escolhem-se uma ou duas pessoas
(gestores primeiro) e vários dias, com o atalho das outras terças do mês cujo buraco
contém as horas escolhidas. Marcar de raiz abre sem loja e as horas vêm do horário da
loja escolhida. O que o servidor recusa aparece em texto, num vermelho que passa os
4,5:1 nos dois temas, e o painel fica aberto para corrigir; uma sessão expirada leva ao
login em vez de aparecer como erro; apagar pede dois toques.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Tarefa 13: O ecrã do Calendário e a rota `/bolso/calendario`

**Ficheiros:**
- Criar: `frontend/src/pages/bolso/BolsoCalendario.js`
- Modificar: `frontend/src/App.js` — import (~82, a seguir a `import BolsoApp …`) e rota (~211, a seguir ao `<Route path="/bolso" …/>`)
- Testes: `backend/tests/calendario/test_ecra_do_calendario.py` (criar)

**Interfaces:**
- Consome: `getCalendario`, `getContagem` (Tarefa 10); de `@/lib/calendario` (Tarefa 9) `FILTROS`, `MESES`, `NOMES_DAS_AUSENCIAS`, `VISTAS`, `ausenciasDoDia`, `dataCurta`, `diasComPonto`, `feriadosDoMes`, `hojeIso`, `intervaloCurto`, `isoDe`, `linhaDaContagem`, `lista`, `mensagemDeErro`, `mesAoLado`, `minhasIdas`, `quantosDias`, `tituloDoDia`, `tituloDoMes`; de `./partilhado` (Tarefa 11) `BotaoMenu`, `Calha`, `GrelhaDoMes`, `MenuLateral`, `Segmento`, `guardar`, `ler`, `useManifestoDoBolso`; `PainelIda` com `onSemSessao` (Tarefa 12).
- Produz: `export default function BolsoCalendario()` em `/bolso/calendario` (papéis `admin`/`gerente`/`contabilista`). Chaves do `localStorage`: `bolso_cal_vista` (`mes`/`lista`/`contagem`) e `bolso_cal_filtro` (`pessoal`/`geral`/`ferias`). Cada buraco desenhado é um `[data-buraco="ninguem"|"falta"]` dentro do `<li>` da loja: o «ninguém» é uma pastilha cheia `bg-destructive-strong text-white` (6,5:1 no claro, 6,0:1 no escuro; o `text-destructive` sobre `bg-destructive/10` dava ≈3,5:1 e 4,0:1), o «falta» fica `bg-warning/15 text-warning-strong` (4,5:1 e 7,2:1). «+ Marcar ida» abre o `PainelIda` com a loja e as horas vazias (`location_id: ''`, `inicio: ''`, `fim: ''`), o dia tocado e a pessoa por omissão.

- [ ] **Passo 1: Escrever os testes que falham**

`backend/tests/calendario/test_ecra_do_calendario.py`:

```python
"""O ecrã do Calendário (`pages/bolso/BolsoCalendario.js`) MONTADO num DOM, com o servidor
fabricado à frente do axios e o relógio parado na terça, 27/10/2026, às 10:00 de Lisboa.

A resposta fabricada não é escrita à mão: sai do `calendario.resposta_do_mes` — o mesmo
código que o servidor corre — sobre a semana normal. Se o servidor mudar a forma da
resposta, é aqui que o ecrã fica vermelho (a lição do voucher ao balcão: duas suites verdes
por cima de um contrato partido).
"""
import json
import re

import calendario
from tests.bolso_js import AXIOS_FABRICADO, SESSAO_SIMULADA, SRC, correr_js

from . import dados_semana_normal as sn

IDAS_DA_DEBORA = [sn.ida("2026-10-06", sn.OEIRAS, sn.DEBORA, "13:00", "22:00"),
                  sn.ida("2026-10-13", sn.OEIRAS, sn.DEBORA, "13:00", "22:00")]


def _servidor(eu=sn.DEBORA, pode_marcar=True):
    dados = sn.semana_normal()
    dados["idas"] = list(IDAS_DA_DEBORA)
    mes = calendario.resposta_do_mes(2026, 10, dados, eu, pode_marcar)
    contagem = calendario.contagem(dados["idas"], {l["id"]: l for l in dados["lojas"]},
                                   {u["id"]: u["name"] for u in dados["utilizadores"]})
    return mes, contagem


def _ecra(tmp_path, cenario, mes, contagem=(), falha=None, antes=""):
    return correr_js("\n".join([
        "pararRelogio(2026, 10, 27, 10, 0);",
        antes,
        "const MES = %s;" % json.dumps(mes, ensure_ascii=False),
        "const CONTAGEM = %s;" % json.dumps(list(contagem), ensure_ascii=False),
        "const FALHA = %s;" % json.dumps(falha),
        "global.SERVIDOR = (metodo, url) => {",
        "  if (metodo === 'GET' && url === '/calendario') return FALHA ? { erro: FALHA } : MES;",
        "  if (metodo === 'GET' && url === '/calendario/contagem') return CONTAGEM;",
        "  return {};",
        "};",
        "const BolsoCalendario = importar('pages/bolso/BolsoCalendario').default;",
        "await montar(React.createElement(BolsoCalendario));",
        "await esperar();",
        cenario,
    ]), tmp_path, simulados=dict(SESSAO_SIMULADA, axios=AXIOS_FABRICADO), dom=True)


BURACOS_DO_DIA = """
const buracos = [...document.querySelectorAll('main [data-buraco]')].map((b) => ({
  loja: b.closest('li').querySelector('span').textContent,
  tipo: b.getAttribute('data-buraco'),
  texto: b.querySelector('span').textContent,
  vermelho: b.classList.contains('bg-destructive-strong') && b.classList.contains('text-white'),
  amarelo: b.classList.contains('bg-warning/15') && b.classList.contains('text-warning-strong'),
}));
const tapar = [...document.querySelectorAll('main button')].filter((b) => b.textContent.trim() === 'Tapar').length;
"""


def test_abre_no_dia_de_hoje_com_os_buracos_a_vermelho_e_a_amarelo(tmp_path):
    mes, _ = _servidor()
    r = _ecra(tmp_path, BURACOS_DO_DIA + """
devolve({
  mes: document.querySelector('h1').textContent,
  dia: document.querySelector('main h2').textContent,
  hoje: document.querySelector('[data-dia="2026-10-27"]').getAttribute('aria-pressed'),
  buracos, tapar,
  belem: [...document.querySelectorAll('main li')].some((li) => li.textContent === 'Belémfechada'),
  marcar: !!botao('Marcar ida'),
  pedidos: REGISTO,
});
""", mes)
    assert (r["mes"], r["dia"], r["hoje"]) == ("outubro 2026", "terça, 27 de outubro", "true")
    assert r["buracos"] == [
        {"loja": "Alfragide", "tipo": "falta", "texto": "falta 10h–14h", "vermelho": False, "amarelo": True},
        {"loja": "Benfica", "tipo": "ninguem", "texto": "ninguém", "vermelho": True, "amarelo": False},
        {"loja": "Oeiras", "tipo": "ninguem", "texto": "ninguém", "vermelho": True, "amarelo": False}]
    assert (r["tapar"], r["belem"], r["marcar"]) == (3, True, True)
    assert r["pedidos"] == [["GET", "/calendario", None, {"ano": 2026, "mes": 10}]]


def test_quem_le_sem_poder_marcar_nao_ve_tapar_nem_marcar(tmp_path):
    mes, _ = _servidor(eu=sn.CONTABILISTA, pode_marcar=False)
    r = _ecra(tmp_path, BURACOS_DO_DIA + "devolve({ tapar, buracos: buracos.length, marcar: !!botao('Marcar ida') });", mes)
    assert r == {"tapar": 0, "buracos": 3, "marcar": False}


def test_os_pontos_da_grelha_e_os_feriados(tmp_path):
    mes, _ = _servidor()
    r = _ecra(tmp_path, """
const ponto = (d) => !!document.querySelector('[data-dia="' + d + '"] [data-ponto]');
const dia = (d) => document.querySelector('[data-dia="' + d + '"]');
const geral = { d05: ponto('2026-10-05'), d02: ponto('2026-10-02') };
await clicar(botao('Pessoal'));
const pessoal = { d06: ponto('2026-10-06'), d05: ponto('2026-10-05') };
devolve({ geral, pessoal, feriado: /warning-strong/.test(dia('2026-10-05').className),
          altura: dia('2026-10-05').className.includes('h-11'), celulas: document.querySelectorAll('[data-dia]').length });
""", mes)
    assert r == {"geral": {"d05": True, "d02": False}, "pessoal": {"d06": True, "d05": False},
                 "feriado": True, "altura": True, "celulas": 31}


def test_tocar_num_dia_mostra_o_e_o_pessoal_mostra_as_minhas_idas(tmp_path):
    mes, _ = _servidor()
    r = _ecra(tmp_path, """
await clicar(document.querySelector('[data-dia="2026-10-06"]'));
await clicar(botao('Pessoal'));
const cartao = [...document.querySelectorAll('main section')].pop();
devolve({ dia: cartao.querySelector('h2').textContent,
          linhas: [...cartao.querySelectorAll('button')].map((b) => b.textContent) });
""", mes)
    assert r == {"dia": "terça, 6 de outubro", "linhas": ["Oeiras13h–22h"]}


def test_a_lista_comeca_hoje(tmp_path):
    mes, _ = _servidor()
    r = _ecra(tmp_path, """
await clicar(botao('Lista'));
devolve([...document.querySelectorAll('main h2')].map((h) => h.textContent).slice(0, 2));
""", mes)
    assert r == ["terça, 27 de outubro", "quarta, 28 de outubro"]


def test_a_contagem_mostra_o_mes_e_o_ano_e_abre_os_meses(tmp_path):
    mes, contagem = _servidor()
    r = _ecra(tmp_path, """
await clicar(botao('Contagem'));
await esperar();
const linha = document.querySelector('main li button');
const primeira = linha.textContent.trim();
await clicar(linha);
devolve({ primeira, meses: document.querySelectorAll('main ol li').length, filtros: !!botao('Geral'),
          pedidos: REGISTO.map((x) => x[1]) });
""", mes, contagem)
    assert r == {"primeira": "Débora · outubro 2 dias · 2026 2 dias", "meses": 12, "filtros": False,
                 "pedidos": ["/calendario", "/calendario/contagem"]}


def test_a_vista_e_o_filtro_lembram_se_e_sem_localstorage_abre_em_mes_geral(tmp_path):
    mes, _ = _servidor()
    lembrado = _ecra(
        tmp_path, "devolve([botao('Lista').getAttribute('aria-pressed'), botao('Férias').getAttribute('aria-pressed')]);",
        mes, antes="localStorage.setItem('bolso_cal_vista', 'lista'); localStorage.setItem('bolso_cal_filtro', 'ferias');")
    assert lembrado == ["true", "true"]
    sem = _ecra(
        tmp_path, "devolve([botao('Mês').getAttribute('aria-pressed'), botao('Geral').getAttribute('aria-pressed')]);",
        mes, antes="Object.defineProperty(global, 'localStorage', { get() { throw new Error('modo privado'); }, configurable: true });")
    assert sem == ["true", "true"]


def test_sessao_expirada_sai_para_o_login(tmp_path):
    mes, _ = _servidor()
    r = _ecra(tmp_path, "devolve(REGISTO.filter((x) => x[0] !== 'GET'));", mes, falha={"response": {"status": 401}})
    assert r == [["logout"], ["navigate", "/login"]]


def test_tapar_abre_com_as_horas_do_buraco_e_marcar_abre_vazio(tmp_path):
    mes, _ = _servidor()
    r = _ecra(tmp_path, """
const lerPainel = () => {
  const dlg = document.querySelector('[role="dialog"]');
  return { titulo: dlg.querySelector('h2').textContent, loja: dlg.querySelector('[aria-label="Loja"]').value,
           inicio: dlg.querySelector('[aria-label="Hora de início"]').value,
           fim: dlg.querySelector('[aria-label="Hora de fim"]').value,
           dias: [...dlg.querySelectorAll('[data-dia][aria-pressed="true"]')].map((b) => b.getAttribute('data-dia')) };
};
const alfragide = [...document.querySelectorAll('main [data-buraco]')]
  .find((b) => b.closest('li').querySelector('span').textContent === 'Alfragide');
await clicar(botao('Tapar', alfragide));
const tapar = lerPainel();
await clicar(botao('Fechar', document.querySelector('[role="dialog"]')));
await clicar(botao('Marcar ida'));
devolve({ tapar, marcar: lerPainel() });
""", mes)
    assert r == {
        "tapar": {"titulo": "Tapar Alfragide", "loja": sn.ALFRAGIDE, "inicio": "10:00", "fim": "14:00",
                  "dias": ["2026-10-27"]},
        # Desenho, secção 4: «o mesmo painel vazio, com a loja a escolher» (as horas vêm da
        # loja que se escolher — prova-se no painel, Tarefa 12).
        "marcar": {"titulo": "Marcar ida", "loja": "", "inicio": "", "fim": "", "dias": ["2026-10-27"]}}


def test_sessao_expirada_ao_gravar_no_painel_sai_para_o_login(tmp_path):
    mes, _ = _servidor()
    r = _ecra(tmp_path, """
const oeiras = [...document.querySelectorAll('main [data-buraco]')]
  .find((b) => b.closest('li').querySelector('span').textContent === 'Oeiras');
await clicar(botao('Tapar', oeiras));
global.SERVIDOR = () => ({ erro: { response: { status: 401, data: { detail: 'Token expirado' } } } });
await clicar(botao('Marcar 1 ida', document.querySelector('[role="dialog"]')));
await esperar();
devolve(REGISTO.filter((x) => x[0] === 'logout' || x[0] === 'navigate'));
""", mes)
    assert r == [["logout"], ["navigate", "/login"]]


def test_depois_de_gravar_o_painel_fecha_e_o_mes_volta_a_ler_se(tmp_path):
    mes, _ = _servidor()
    r = _ecra(tmp_path, """
const oeiras = [...document.querySelectorAll('main [data-buraco]')]
  .find((b) => b.closest('li').querySelector('span').textContent === 'Oeiras');
await clicar(botao('Tapar', oeiras));
await clicar(botao('Marcar 1 ida', document.querySelector('[role="dialog"]')));
await esperar();
devolve({ aberto: !!document.querySelector('[role="dialog"]'), pedidos: REGISTO.map((x) => x[0] + ' ' + x[1]) });
""", mes)
    assert r == {"aberto": False, "pedidos": ["GET /calendario", "POST /calendario/idas", "GET /calendario"]}


def test_cada_destino_do_menu_e_uma_rota_do_app_com_os_papeis_do_bolso(tmp_path):
    destinos = correr_js("devolve(importar('pages/bolso/partilhado').DESTINOS.map((d) => d.caminho));",
                         tmp_path, simulados=SESSAO_SIMULADA, dom=True)
    assert destinos == ["/bolso", "/bolso/calendario"]
    app = (SRC / "App.js").read_text(encoding="utf-8")
    for caminho in destinos:
        rota = re.compile(r'<Route path="%s" element=\{\s*<ProtectedRoute allowedRoles=\{\[\'admin\', '
                          r'\'gerente\', \'contabilista\'\]\}>' % re.escape(caminho))
        assert rota.search(app), "O App.js não tem a rota %s com os papéis do bolso." % caminho
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_ecra_do_calendario.py -q
```

Esperado: `12 failed` — onze com «Não encontrei …/pages/bolso/BolsoCalendario» e o das rotas com «O App.js não tem a rota /bolso/calendario».

- [ ] **Passo 3: O ecrã**

`frontend/src/pages/bolso/BolsoCalendario.js`:

```js
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, ChevronLeft, ChevronRight, Plus } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { getCalendario, getContagem } from '@/lib/bolso';
import {
  FILTROS, MESES, NOMES_DAS_AUSENCIAS, VISTAS, ausenciasDoDia, dataCurta, diasComPonto, feriadosDoMes,
  hojeIso, intervaloCurto, isoDe, linhaDaContagem, lista, mensagemDeErro, mesAoLado, minhasIdas,
  quantosDias, tituloDoDia, tituloDoMes,
} from '@/lib/calendario';
import {
  BotaoMenu, Calha, GrelhaDoMes, MenuLateral, Segmento, guardar, ler, useManifestoDoBolso,
} from './partilhado';
import PainelIda from './PainelIda';

// **Calendário das lojas** — onde falta gente, para a Carol e a Débora taparem.
//
// O servidor calcula os buracos a cada pedido (horário das lojas + escala de cada pessoa +
// ausências aprovadas + idas) e manda o mês inteiro num pedido; este ecrã só desenha. As
// contas do ecrã vivem em `lib/calendario.js` (puras, testadas em Node).
//
// Em cima: ☰, o mês, ‹ › e Mês | Lista | Contagem. Em baixo: Pessoal | Geral | Férias. Vista
// e filtro lembram-se no `localStorage` (sem ele, abre em Mês/Geral). «Tapar» e «Marcar ida»
// só existem para quem pode marcar (o servidor diz `pode_marcar`; o contabilista só lê).

const CHAVE_VISTA = 'bolso_cal_vista';
const CHAVE_FILTRO = 'bolso_cal_filtro';
const COR_DO_PONTO = { geral: 'bg-destructive', pessoal: 'bg-primary', ferias: 'bg-warning' };
const lerOpcao = (chave, opcoes, omissao) => {
  const v = ler(chave, omissao);
  return opcoes.includes(v) ? v : omissao;
};
const etiqueta = (p) => (p.origem === 'escala' ? 'escala' : p.extra ? 'extra' : 'ida');

const Esqueleto = () => (
  <div aria-hidden="true" className="mt-3 h-40 rounded-2xl bg-muted-foreground/15 motion-safe:animate-pulse" />
);

function Cartao({ titulo, subtitulo, children }) {
  return (
    <section className="mt-3 rounded-2xl border bg-card overflow-hidden">
      <header className="px-4 pt-3 pb-2">
        <h2 className="text-[15px] font-semibold first-letter:uppercase">{titulo}</h2>
        {subtitulo && <p className="text-[12px] text-warning-strong">{subtitulo}</p>}
      </header>
      {children}
    </section>
  );
}

// Uma linha que é botão quando se pode tocar (abrir a ida) e texto quando não.
function Linha({ onClick, children }) {
  const forma = 'w-full min-h-11 flex items-center gap-2 text-left text-[14px]';
  return onClick ? (
    <button
      type="button" onClick={onClick}
      className={`${forma} rounded-lg active:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring`}
    >
      {children}
    </button>
  ) : <div className={forma}>{children}</div>;
}

function LojaDoDia({ loja, data, podeMarcar, onTapar, onIda, soBuracos = false }) {
  if (loja.estado === 'fechada') {
    return (
      <li className="px-4 py-3 flex items-baseline justify-between gap-2 text-muted-foreground">
        <span className="font-semibold">{loja.nome}</span>
        <span className="text-[13px]">fechada</span>
      </li>
    );
  }
  const ninguem = loja.pessoas.length === 0;
  return (
    <li className="px-4 py-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-semibold">{loja.nome}</span>
        <span className="text-[12px] text-muted-foreground tabular-nums">{intervaloCurto(loja.abre, loja.fecha)}</span>
      </div>
      {loja.feriados.length > 0 && <p className="text-[12px] text-warning-strong">{loja.feriados.join(' · ')}</p>}
      {!soBuracos && loja.pessoas.map((p) => (
        <Linha key={`${p.user_id}-${p.inicio}`} onClick={p.ida_id && podeMarcar ? () => onIda(p.ida_id) : null}>
          <span className="min-w-0 flex-1 truncate">{p.nome}</span>
          <span className="tabular-nums text-muted-foreground">{intervaloCurto(p.inicio, p.fim)}</span>
          <span className={`text-[12px] font-semibold ${p.origem === 'escala' ? 'text-muted-foreground' : 'text-primary'}`}>
            {etiqueta(p)}
          </span>
        </Linha>
      ))}
      {loja.buracos.map((b) => (
        <div
          key={b.inicio} data-buraco={ninguem ? 'ninguem' : 'falta'}
          className={`mt-2 flex items-center gap-2 rounded-xl py-1 pl-3 pr-1 ${
            ninguem ? 'bg-destructive-strong text-white' : 'bg-warning/15 text-warning-strong'}`}
        >
          {/* «ninguém» em pastilha cheia: branco sobre `destructive-strong` dá 6,5:1 (claro) e
              6,0:1 (escuro). O `text-destructive` sobre `bg-destructive/10` dava ≈3,5:1 e 4,0:1
              — e `text-destructive-strong` no escuro dá 3,0:1 (o token foi feito para fundo). */}
          <span className="flex-1 text-[14px] font-semibold">
            {ninguem ? 'ninguém' : `falta ${intervaloCurto(b.inicio, b.fim)}`}
          </span>
          {podeMarcar && (
            <button
              type="button"
              onClick={() => onTapar({ data, location_id: loja.location_id, nome: loja.nome, inicio: b.inicio, fim: b.fim })}
              className="h-11 px-4 rounded-lg border bg-card font-semibold text-foreground
                         focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              Tapar
            </button>
          )}
        </div>
      ))}
    </li>
  );
}

function IdaLinha({ ida, comNome, onIda }) {
  return (
    <Linha onClick={onIda ? () => onIda(ida.id) : null}>
      <span className="min-w-0 flex-1 truncate">{comNome ? `${ida.nome} · ${ida.loja}` : ida.loja}</span>
      <span className="tabular-nums text-muted-foreground">{intervaloCurto(ida.inicio, ida.fim)}</span>
    </Linha>
  );
}

function AusenciaLinha({ ausencia }) {
  return (
    <div className="py-2 text-[14px]">
      <p className="font-semibold">{ausencia.nome} · {NOMES_DAS_AUSENCIAS[ausencia.tipo] || ausencia.tipo}</p>
      <p className="text-[12px] text-muted-foreground">
        {dataCurta(ausencia.inicio)}–{dataCurta(ausencia.fim)}{ausencia.loja ? ` · ${ausencia.loja}` : ''}
      </p>
    </div>
  );
}

// O dia escolhido, por baixo da grelha, conforme o filtro.
function Dia({ dados, iso, filtro, onTapar, onIda }) {
  const dia = (dados.dias || []).find((d) => d.data === iso);
  if (!dia) return null;
  const feriados = dia.feriados.length ? dia.feriados.join(' · ') : null;
  const abrirIda = dados.pode_marcar ? onIda : null;
  if (filtro === 'pessoal') {
    const idas = minhasIdas(dados).filter((i) => i.data === iso);
    return (
      <Cartao titulo={tituloDoDia(iso)} subtitulo={feriados}>
        <div className="px-4 pb-3">
          {idas.length === 0 && <p className="py-2 text-[14px] text-muted-foreground">Sem idas tuas neste dia.</p>}
          {idas.map((i) => <IdaLinha key={i.id} ida={i} onIda={abrirIda} />)}
        </div>
      </Cartao>
    );
  }
  if (filtro === 'ferias') {
    const ausencias = ausenciasDoDia(dados, iso);
    return (
      <Cartao titulo={tituloDoDia(iso)} subtitulo={feriados}>
        <div className="px-4 pb-2 divide-y">
          {ausencias.length === 0 && <p className="py-2 text-[14px] text-muted-foreground">Ninguém ausente neste dia.</p>}
          {ausencias.map((a) => <AusenciaLinha key={`${a.nome}-${a.inicio}`} ausencia={a} />)}
        </div>
      </Cartao>
    );
  }
  return (
    <Cartao titulo={tituloDoDia(iso)} subtitulo={feriados}>
      <ul className="divide-y border-t">
        {dia.lojas.map((l) => (
          <LojaDoDia key={l.location_id} loja={l} data={iso} podeMarcar={dados.pode_marcar} onTapar={onTapar} onIda={onIda} />
        ))}
      </ul>
    </Cartao>
  );
}

function Lista({ dados, filtro, hoje, onTapar, onIda }) {
  const dias = lista(dados, filtro, hoje);
  if (!dias.length) {
    const nada = { geral: 'Sem buracos nem idas', pessoal: 'Sem idas tuas', ferias: 'Ninguém ausente' }[filtro];
    return <p className="mt-6 text-center text-[14px] text-muted-foreground">{nada} neste mês.</p>;
  }
  const abrirIda = dados.pode_marcar ? onIda : null;
  return dias.map((d) => (
    <Cartao key={d.data} titulo={tituloDoDia(d.data)}>
      {d.buracos.length > 0 && (
        <ul className="divide-y border-t">
          {d.buracos.map((l) => (
            <LojaDoDia key={l.location_id} loja={l} data={d.data} podeMarcar={dados.pode_marcar} onTapar={onTapar} onIda={onIda} soBuracos />
          ))}
        </ul>
      )}
      {d.idas.length > 0 && (
        <div className="px-4 pb-2 border-t">
          {d.idas.map((i) => <IdaLinha key={i.id} ida={i} comNome={filtro === 'geral'} onIda={abrirIda} />)}
        </div>
      )}
      {d.ausencias.length > 0 && (
        <div className="px-4 pb-2 divide-y border-t">
          {d.ausencias.map((a) => <AusenciaLinha key={`${a.nome}-${a.inicio}`} ausencia={a} />)}
        </div>
      )}
    </Cartao>
  ));
}

// «Débora · outubro 18 dias · 2026 60 dias»; tocar abre os meses um a um.
function Contagem({ linhas, ano, mes }) {
  const [aberta, setAberta] = useState(null);
  if (!linhas) return <Esqueleto />;
  if (!linhas.length) return <p className="mt-6 text-center text-[14px] text-muted-foreground">Ainda não há idas em {ano}.</p>;
  return (
    <section className="mt-3 rounded-2xl border bg-card overflow-hidden">
      <ul className="divide-y">
        {linhas.map((l) => (
          <li key={l.user_id}>
            <button
              type="button" aria-expanded={aberta === l.user_id}
              onClick={() => setAberta(aberta === l.user_id ? null : l.user_id)}
              className="w-full min-h-12 px-4 py-3 flex items-center gap-2 text-left text-[15px]
                         active:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
            >
              <span className="min-w-0 flex-1">{linhaDaContagem(l, ano, mes)}</span>
              <ChevronRight className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${aberta === l.user_id ? 'rotate-90' : ''}`} />
            </button>
            {aberta === l.user_id && (
              <ol className="grid grid-cols-2 gap-x-4 px-4 pb-3 text-[13px] tabular-nums">
                {MESES.map((nome, i) => (
                  <li key={nome} className={`flex justify-between py-0.5 ${i + 1 === mes ? 'font-semibold' : 'text-muted-foreground'}`}>
                    <span>{nome}</span>
                    <span>{quantosDias(l.meses[i])}</span>
                  </li>
                ))}
              </ol>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function BolsoCalendario() {
  useManifestoDoBolso();
  const navigate = useNavigate();
  const { logout } = useAuth();
  const hoje = hojeIso();
  const [{ ano, mes }, setMes] = useState(() => ({ ano: Number(hoje.slice(0, 4)), mes: Number(hoje.slice(5, 7)) }));
  const [vista, setVista] = useState(() => lerOpcao(CHAVE_VISTA, VISTAS, 'mes'));
  const [filtro, setFiltro] = useState(() => lerOpcao(CHAVE_FILTRO, FILTROS, 'geral'));
  const [escolhido, setEscolhido] = useState(hoje);
  const [dados, setDados] = useState(null);
  const [contagem, setContagem] = useState(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState(null);
  const [menu, setMenu] = useState(false);
  const [painel, setPainel] = useState(null);
  // Cada pedido leva um número; só o último escreve no ecrã. Sem isto, tocar ‹ › depressa
  // deixava a resposta de um mês antigo chegar por último e ficar.
  const pedido = useRef(0);
  // Cada abertura do painel é uma montagem nova (a `key`), para o formulário começar sempre
  // no que se tocou e não no que ficou da vez anterior.
  const aberturas = useRef(0);

  const semSessao = useCallback(() => { logout(); navigate('/login'); }, [logout, navigate]);

  const carregar = useCallback(async () => {
    pedido.current += 1;
    const meu = pedido.current;
    setCarregando(true);
    setErro(null);
    try {
      const { data } = await getCalendario(ano, mes);
      if (meu === pedido.current) setDados(data);
    } catch (e) {
      if (e?.response?.status === 401) { semSessao(); return; }
      if (meu === pedido.current) setErro(mensagemDeErro(e));
    } finally {
      if (meu === pedido.current) setCarregando(false);
    }
  }, [ano, mes, semSessao]);

  const carregarContagem = useCallback(async () => {
    try {
      const { data } = await getContagem(ano);
      setContagem({ ano, linhas: data });
    } catch (e) {
      if (e?.response?.status === 401) { semSessao(); return; }
      setErro(mensagemDeErro(e));
    }
  }, [ano, semSessao]);

  useEffect(() => { carregar(); }, [carregar]);
  useEffect(() => { if (vista === 'contagem') carregarContagem(); }, [vista, carregarContagem]);

  // Numa app instalada, voltar ao ecrã não remonta a página: relê-se ao voltar.
  useEffect(() => {
    const aoVoltar = () => {
      if (document.hidden) return;
      carregar();
      if (vista === 'contagem') carregarContagem();
    };
    document.addEventListener('visibilitychange', aoVoltar);
    return () => document.removeEventListener('visibilitychange', aoVoltar);
  }, [carregar, carregarContagem, vista]);

  const irPara = (passo) => {
    const novo = mesAoLado(ano, mes, passo);
    setMes(novo);
    setEscolhido(hoje.slice(0, 7) === isoDe(novo.ano, novo.mes, 1).slice(0, 7) ? hoje : isoDe(novo.ano, novo.mes, 1));
  };
  const escolherVista = (v) => { setVista(v); guardar(CHAVE_VISTA, v); };
  const escolherFiltro = (f) => { setFiltro(f); guardar(CHAVE_FILTRO, f); };

  // Os números no ecrã são DESTE mês? Enquanto não forem, esqueletos.
  const desteMes = dados && dados.ano === ano && dados.mes === mes ? dados : null;

  const abrirPainel = (p) => {
    aberturas.current += 1;
    setPainel({ ...p, chave: aberturas.current });
  };
  const tapar = (b) => abrirPainel({
    modo: 'tapar', nomeDaLoja: b.nome,
    inicial: { datas: [b.data], location_id: b.location_id, inicio: b.inicio, fim: b.fim },
  });
  const editar = (idaId) => {
    const ida = (desteMes?.idas || []).find((i) => i.id === idaId);
    if (!ida) return;
    abrirPainel({
      modo: 'editar',
      inicial: {
        ida_id: ida.id, datas: [ida.data], location_id: ida.location_id, user_ids: [ida.user_id],
        inicio: ida.inicio, fim: ida.fim, nome: ida.nome,
      },
    });
  };
  // «+ Marcar ida» abre o painel vazio, com a loja a escolher (desenho, secção 4); as horas
  // vêm do horário da loja que se escolher (PainelIda). Fica o dia tocado e a pessoa por
  // omissão, como no Tapar.
  const marcar = () => abrirPainel({
    modo: 'marcar',
    inicial: { datas: escolhido ? [escolhido] : [], location_id: '', inicio: '', fim: '' },
  });
  const guardado = () => {
    setPainel(null);
    carregar();
    if (vista === 'contagem') carregarContagem();
  };

  const seta = 'h-11 w-11 shrink-0 inline-flex items-center justify-center rounded-lg active:bg-accent/60 '
    + 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

  return (
    <div className="min-h-[100dvh] bg-muted/30 pb-32">
      <header className="sticky top-0 z-20 bg-card border-b safe-area-inset-top">
        <div className="flex items-center gap-1 pl-1 pr-1 h-14">
          <BotaoMenu onClick={() => setMenu(true)} />
          <div className="min-w-0 flex-1">
            <h1 className="font-heading font-bold text-base leading-tight truncate first-letter:uppercase">
              {tituloDoMes(ano, mes)}
            </h1>
            <p className="text-[11px] text-muted-foreground leading-tight truncate">
              {carregando ? 'A ler…' : 'Calendário das lojas'}
              {erro && <span className="text-destructive"> · falhou</span>}
            </p>
          </div>
          <button type="button" aria-label="Mês anterior" onClick={() => irPara(-1)} className={seta}>
            <ChevronLeft className="h-5 w-5" />
          </button>
          <button type="button" aria-label="Mês seguinte" onClick={() => irPara(1)} className={seta}>
            <ChevronRight className="h-5 w-5" />
          </button>
        </div>
        <div className="px-3 pb-2">
          <Calha>
            <Segmento activo={vista === 'mes'} onClick={() => escolherVista('mes')}>Mês</Segmento>
            <Segmento activo={vista === 'lista'} onClick={() => escolherVista('lista')}>Lista</Segmento>
            <Segmento activo={vista === 'contagem'} onClick={() => escolherVista('contagem')}>Contagem</Segmento>
          </Calha>
        </div>
      </header>

      <main className="px-3 pt-3 pb-6 max-w-2xl mx-auto">
        {erro && (
          <section role="alert" className="mb-3 rounded-2xl border border-destructive/40 bg-destructive/10 p-3 flex items-start gap-2.5">
            <AlertTriangle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
            <div className="min-w-0">
              <p className="font-medium">Não foi possível ler agora.</p>
              <p className="text-sm text-muted-foreground mt-0.5 whitespace-pre-line break-words">{erro}</p>
            </div>
          </section>
        )}

        {vista === 'mes' && (
          <>
            <section className="rounded-2xl border bg-card p-2">
              <GrelhaDoMes
                ano={ano} mes={mes} hoje={hoje} escolhidos={escolhido ? [escolhido] : []} onTocar={setEscolhido}
                pontos={desteMes ? diasComPonto(desteMes, filtro) : []} corDoPonto={COR_DO_PONTO[filtro]}
                feriados={desteMes ? feriadosDoMes(desteMes) : []}
              />
            </section>
            {desteMes
              ? <Dia dados={desteMes} iso={escolhido} filtro={filtro} onTapar={tapar} onIda={editar} />
              : <Esqueleto />}
          </>
        )}
        {vista === 'lista' && (desteMes
          ? <Lista dados={desteMes} filtro={filtro} hoje={hoje} onTapar={tapar} onIda={editar} />
          : <Esqueleto />)}
        {vista === 'contagem' && (
          <Contagem linhas={contagem && contagem.ano === ano ? contagem.linhas : null} ano={ano} mes={mes} />
        )}

        {desteMes?.pode_marcar && vista !== 'contagem' && (
          <button
            type="button" onClick={marcar}
            className="mt-4 w-full h-12 rounded-2xl border bg-card px-4 flex items-center justify-center gap-2 font-semibold
                       active:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Plus className="h-5 w-5" />
            Marcar ida
          </button>
        )}
      </main>

      {vista !== 'contagem' && (
        <nav aria-label="Filtro" className="fixed bottom-0 left-0 right-0 z-30 bg-card border-t safe-area-inset-bottom">
          <div className="px-3 py-1.5 max-w-2xl mx-auto">
            <Calha>
              <Segmento activo={filtro === 'pessoal'} onClick={() => escolherFiltro('pessoal')}>Pessoal</Segmento>
              <Segmento activo={filtro === 'geral'} onClick={() => escolherFiltro('geral')}>Geral</Segmento>
              <Segmento activo={filtro === 'ferias'} onClick={() => escolherFiltro('ferias')}>Férias</Segmento>
            </Calha>
          </div>
        </nav>
      )}

      <MenuLateral aberto={menu} onFechar={() => setMenu(false)} actual="/bolso/calendario" />
      {painel && desteMes && (
        <PainelIda
          key={painel.chave} painel={painel} dados={desteMes} hoje={hoje}
          onFechar={() => setPainel(null)} onGuardado={guardado} onSemSessao={semSessao}
        />
      )}
    </div>
  );
}
```

- [ ] **Passo 4: A rota**

Em `frontend/src/App.js`, a seguir a `import BolsoApp from './pages/bolso/BolsoApp';` (~82), acrescentar:

```jsx
import BolsoCalendario from './pages/bolso/BolsoCalendario';
```

e a seguir ao bloco

```jsx
      <Route path="/bolso" element={
        <ProtectedRoute allowedRoles={['admin', 'gerente', 'contabilista']}>
          <BolsoApp />
        </ProtectedRoute>
      } />
```

acrescentar:

```jsx
      {/* O calendário das lojas (onde falta gente), irmão do /bolso: mesmos papéis, mesma
          casca. O contabilista lê; quem marca é decidido pelo servidor (`pode_marcar`). */}
      <Route path="/bolso/calendario" element={
        <ProtectedRoute allowedRoles={['admin', 'gerente', 'contabilista']}>
          <BolsoCalendario />
        </ProtectedRoute>
      } />
```

- [ ] **Passo 5: Correr e ver passar (e a compilação a sério)**

Primeiro, uma vez: o atalho `frontend/node_modules` → `~/Developer/RH/frontend/node_modules` chega para os testes de JavaScript mas **não para compilar** — esse ramo (`matheus-niveis-de-conta`) não tem o `leaflet` do CRM e o `craco build`/`craco start` param com «Module not found: Can't resolve 'leaflet'» (medido a 2026-10-15). A árvore passa a ter os seus próprios `node_modules` (≈ 11 s com a cache do yarn quente; os testes desta fase passam igual com eles):

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/frontend
export PATH="$HOME/.local/node/bin:$PATH"
test -L node_modules && rm node_modules        # apaga só o atalho, nunca a pasta do ~/Developer/RH
test -d node_modules/leaflet || yarn install --frozen-lockfile --network-timeout 600000
ls -d node_modules/leaflet node_modules/jsdom node_modules/@babel/core
git -C .. status -s                            # vazio: o frontend/.gitignore tem /node_modules
```

Depois:

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_ecra_do_calendario.py tests/calendario/test_painel_da_ida.py tests/calendario/test_menu_do_bolso.py -q -rs
cd /Users/matheus.moraes/Developer/RH-calendario/frontend
export PATH="$HOME/.local/node/bin:$PATH"
mkdir -p "$HOME/.cache/lisbonb-calendario-local"
CI=false REACT_APP_BACKEND_URL="" BUILD_PATH="$HOME/.cache/lisbonb-calendario-local/build" ./node_modules/.bin/craco build 2>&1 | tail -5
grep -l "bolso_cal_vista" "$HOME/.cache/lisbonb-calendario-local/build/static/js/"main.*.js
```

Esperado: `28 passed` sem `skipped` (12 do ecrã + 10 do painel + 6 do menu); o build «Compiled successfully» (ou «Compiled with warnings» sem erros) e o `grep` a mostrar o `main.*.js` (marcador só-ASCII de propósito).

- [ ] **Passo 6: Prova por mutação**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PY=~/Developer/RH/backend/.venv/bin/python
JS=../frontend/src/pages/bolso/BolsoCalendario.js
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py $JS "const semSessao = useCallback(() => { logout(); navigate('/login'); }, [logout, navigate]);" "const semSessao = useCallback(() => {}, []);" -- $PY -m pytest tests/calendario/test_ecra_do_calendario.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py $JS '{podeMarcar && (' '{true && (' -- $PY -m pytest tests/calendario/test_ecra_do_calendario.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py $JS "useState(() => lerOpcao(CHAVE_VISTA, VISTAS, 'mes'))" "useState('mes')" -- $PY -m pytest tests/calendario/test_ecra_do_calendario.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py $JS "ninguem ? 'bg-destructive-strong text-white' : 'bg-warning/15 text-warning-strong'" "ninguem ? 'bg-warning/15 text-warning-strong' : 'bg-destructive-strong text-white'" -- $PY -m pytest tests/calendario/test_ecra_do_calendario.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py ../frontend/src/App.js '<Route path="/bolso/calendario" element={' '<Route path="/bolso/calendario-x" element={' -- $PY -m pytest tests/calendario/test_ecra_do_calendario.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py $JS "ninguem ? 'bg-destructive-strong text-white'" "ninguem ? 'bg-destructive/10 text-destructive'" -- $PY -m pytest tests/calendario/test_ecra_do_calendario.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py $JS "location_id: '', inicio: '', fim: ''" "location_id: desteMes.lojas[0].id, inicio: '', fim: ''" -- $PY -m pytest tests/calendario/test_ecra_do_calendario.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py $JS "onGuardado={guardado} onSemSessao={semSessao}" "onGuardado={guardado}" -- $PY -m pytest tests/calendario/test_ecra_do_calendario.py -q
```

Esperado: (1) `FAILED …test_sessao_expirada_sai_para_o_login` e `…test_sessao_expirada_ao_gravar_no_painel…`; (2) `FAILED …test_quem_le_sem_poder_marcar…`; (3) `FAILED …test_a_vista_e_o_filtro_lembram_se…`; (4) `FAILED …test_abre_no_dia_de_hoje_com_os_buracos_a_vermelho_e_a_amarelo`; (5) `FAILED …test_cada_destino_do_menu_e_uma_rota_do_app…`; (6) `FAILED …test_abre_no_dia_de_hoje…` (`vermelho: False` no «ninguém» com as classes antigas, as do contraste abaixo de 4,5:1); (7) `FAILED …test_tapar_abre_com_as_horas_do_buraco_e_marcar_abre_vazio` (o Marcar abre já em Alfragide); (8) `FAILED …test_sessao_expirada_ao_gravar_no_painel…` (sem a prop, o painel não sai para o login — `[]` em vez de logout e navigate). Todas com «Mutação apanhada».

- [ ] **Passo 7: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add frontend/src/pages/bolso/BolsoCalendario.js frontend/src/App.js backend/tests/calendario/test_ecra_do_calendario.py
git commit -m "Calendário: o ecrã na Gestão Lisbonb, com Mês, Lista e Contagem

Abre no dia de hoje com a grelha do mês (dias de 44 px, ponto vermelho onde há buraco,
feriados noutra cor) e, por baixo, cada loja com quem lá está e o que falta, a vermelho
quando não está ninguém (pastilha cheia, para o texto passar os 4,5:1 nos dois temas) e a
amarelo quando falta parte; Tapar e Marcar só para quem pode marcar, e Marcar abre vazio,
com a loja a escolher. Uma sessão expirada dentro do painel leva ao login. Os filtros
Pessoal, Geral e Férias e a vista ficam lembrados no telemóvel.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Tarefa 14: O script do dono — as idas de outubro a dezembro da mensagem de WhatsApp

O script corre **dentro do contentor do backend em produção, lido do stdin**, pela mão do dono, depois de a Fase 2 estar no ar (Tarefa 16). Escreve-se e prova-se aqui; corre-se na Tarefa 17. Regras da casa para scripts de produção: ensaio por omissão, `GRAVAR=1` para gravar, decide tudo antes da primeira escrita, pára em qualquer ambiguidade, nunca apaga.

**Ficheiros:**
- Criar: `backend/carregar_idas_whatsapp.py`
- Testes: `backend/tests/calendario/test_carregar_idas_whatsapp.py` (criar)

**Interfaces:**
- Consome: `calendario.horario_do_dia`, `choques`, `hhmm`, `hora_curta`, `data_curta`, `GESTORES` (Tarefas 1-5); `arranque_calendario.Paragem`, `_normal`, `_um` (Fase 1); fixture `mongod_porta` (Fase 1).
- Produz (em `carregar_idas_whatsapp`):
  - `IDAS: Dict[str, List[Tuple[str, List[str]]]]` — por gestor (primeiro nome), `(loja, [datas])` pela ordem da mensagem (96 idas)
  - `OPCIONAL = "Benfica"`, `CRIADO_POR = "whatsapp-out-dez-2026"`
  - `planear(idas, utilizadores, lojas, existentes, procurar=None) -> {"gravar": [ida sem id], "divididas": [str], "divididas_em": [(iso, (location_id, location_id))], "saltadas": [str]}` (levanta `Paragem`). As lojas procuram-se **só entre as que têm `horario`** — em produção há duas «Loja Alfragide» (a da Pizzaria e a da Fordaimon, memória `rh-lisbonb-project`) e só a da Fordaimon recebeu horário no arranque da Fase 1. `procurar` = `{nome curto: nome mais comprido}` para desfazer uma ambiguidade (pessoas e lojas), como o `PROCURAR` da Fase 1
  - `executar(db, gravar: bool, escrever=print) -> int` (0 = feito/ensaio; 1 = parado, nada gravado); lê `PROCURAR_JSON` do ambiente; no ensaio, cada linha `DIVIDIDO AO MEIO: …` diz também os buracos que ficam nas duas lojas (calculados pelo `calendario.dia_do_calendario` com a escala real e as idas já gravadas + as do plano)
  - variáveis de ambiente: `MONGO_URL`, `DB_NAME`, `GRAVAR` (`"1"` grava) no `__main__`; `PROCURAR_JSON` (opcional, ex.: `{"Carol": "Carol Santos"}`) no `executar`

Os dados (gestores; tudo dia inteiro), copiados da mensagem para o `IDAS`:

- Débora: Benfica 24, 25, 31/10 · Algueirão 24/10 e 08/12 · Alfragide 1, 2, 5, 6, 7, 8, 12, 13, 14, 15, 19, 20, 21, 22, 26, 27, 28, 29/10, 02/11, 8, 9, 10, 15, 16, 22, 30/12 · Oeiras 6, 13, 20, 21, 27, 29, 30/10, 01/11, 10, 11, 14, 29/12
- Carol: Alfragide 05/10, 1, 3, 4, 5, 9, 10, 11, 12, 16, 17, 18, 19, 23, 24, 25, 26, 30/11, 1, 2, 3, 7, 14, 17, 21, 23, 28, 29/12 · Oeiras 31/10, 2, 3, 10, 17, 24/11, 1, 8, 12, 13, 15, 22/12 · Amadora 22, 23, 25/10
- Matheus: Benfica 24, 25, 26, 28, 29, 30, 31/10 e 02/11 · Algueirão 01/11
- Bruce: Alfragide 01/11

Com as regras novas há **14 dias** em que a mesma pessoa está em duas lojas com o dia inteiro (Débora: 6, 13, 20, 21, 24, 27, 29/10, 8 e 10/12; Carol: 3, 10, 17, 24/11 e 1/12) — o script propõe dividir o dia ao meio e o dono aprova no ensaio. Nenhuma regra simples serve os 14 casos (às terças a divisão deixa Oeiras sem ninguém das 13h às 16h30 e Alfragide com duas pessoas das 14h às 16h30; a 21 e a 29/10 o buraco de Alfragide é à noite), por isso a regra fica e **o ensaio mostra, em cada divisão, os buracos que ficam**, para o dono decidir antes do `GRAVAR=1`.

- [ ] **Passo 1: Escrever os testes que falham**

`backend/tests/calendario/test_carregar_idas_whatsapp.py`:

```python
"""O script do dono que carrega as idas de outubro a dezembro da mensagem de WhatsApp
(`backend/carregar_idas_whatsapp.py`): o plano (puro) e a gravação contra o mongod."""
import json
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")
os.environ.setdefault("JWT_SECRET", "segredo-de-teste")
os.environ.setdefault("POS_JWT_SECRET", "segredo-de-teste-pos")

import pytest  # noqa: E402
from pymongo import MongoClient  # noqa: E402

import calendario  # noqa: E402
import carregar_idas_whatsapp as script  # noqa: E402
from arranque_calendario import Paragem  # noqa: E402

from . import dados_semana_normal as sn  # noqa: E402

CONTAS = [{"id": "u-deb", "name": "Débora Ferreira", "role": "admin"},
          {"id": "u-car", "name": "Carol Santos", "role": "admin"},
          {"id": "u-mat", "name": "Matheus Moraes", "role": "admin"},
          {"id": "u-bru", "name": "Bruce Lima", "role": "gerente"},
          {"id": "u-deb2", "name": "Débora Colaboradora", "role": "colaborador"},
          {"id": "u-rita", "name": "Rita Contas", "role": "contabilista"}]


def _lojas(**mudar):
    lojas = sn.semana_normal()["lojas"]
    for loja in lojas:
        loja.update(mudar.get(loja["name"], {}))
    # Como em produção: há outra «Loja Alfragide», a da Pizzaria, SEM horário. Só a da
    # Fordaimon (com horário, posto pelo arranque da Fase 1) pode receber idas.
    lojas.append({"id": "loja-pizzaria-alfragide", "name": "Loja Alfragide", "company_id": sn.LENHA,
                  "horario": None})
    return lojas


def test_planeia_as_96_idas_da_mensagem_com_o_horario_de_cada_loja():
    plano = script.planear(script.IDAS, CONTAS, _lojas(), [])
    assert (len(plano["gravar"]), plano["saltadas"]) == (96, [])
    assert [i for i in plano["gravar"] if i["user_id"] == "u-bru"] == [
        {"data": "2026-11-01", "location_id": sn.ALFRAGIDE, "user_id": "u-bru", "inicio": "10:00", "fim": "23:00"}]
    com_id = [dict(i, id=str(n)) for n, i in enumerate(plano["gravar"])]
    assert not [i for i in com_id if calendario.choques([i], com_id, ignorar_id=i["id"])]


def test_a_mesma_pessoa_em_duas_lojas_no_mesmo_dia_divide_o_dia_ao_meio():
    plano = script.planear(script.IDAS, CONTAS, _lojas(), [])
    assert len(plano["divididas"]) == 14
    assert plano["divididas"][0] == "Débora 06/10: Alfragide 10h–16h30 + Oeiras 16h30–22h"
    assert "Débora 24/10: Benfica 13h–17h30 + Algueirão 17h30–22h" in plano["divididas"]
    assert sorted((i["location_id"], i["inicio"], i["fim"]) for i in plano["gravar"]
                  if i["user_id"] == "u-deb" and i["data"] == "2026-10-06") == [
        (sn.ALFRAGIDE, "10:00", "16:30"), (sn.OEIRAS, "16:30", "22:00")]


def test_um_nome_que_casa_com_duas_contas_de_gestor_para_tudo():
    with pytest.raises(Paragem, match="Débora"):
        script.planear(script.IDAS, CONTAS + [{"id": "u-x", "name": "Débora Silva", "role": "gerente"}], _lojas(), [])


def test_uma_pessoa_que_nao_existe_para_tudo():
    with pytest.raises(Paragem, match="Bruce"):
        script.planear(script.IDAS, [c for c in CONTAS if c["id"] != "u-bru"], _lojas(), [])


def test_uma_loja_sem_horario_para_tudo_excepto_benfica():
    with pytest.raises(Paragem, match="Oeiras"):
        script.planear(script.IDAS, CONTAS, _lojas(Oeiras={"horario": None}), [])
    plano = script.planear(script.IDAS, CONTAS, _lojas(Benfica={"horario": None}), [])
    assert plano["saltadas"] == ["Benfica ainda não tem horário: as idas de Benfica ficam de fora."]
    assert len(plano["gravar"]) == 96 - 11 and not [i for i in plano["gravar"] if i["location_id"] == sn.BENFICA]
    sem_benfica = [l for l in _lojas() if l["name"] != "Benfica"]
    assert script.planear(script.IDAS, CONTAS, sem_benfica, [])["saltadas"] == [
        "Benfica não existe: as idas de Benfica ficam de fora."]


def test_um_dia_em_que_a_loja_esta_fechada_fica_de_fora():
    oeiras = {"horario": {"abre": "13:00", "fecha": "22:00", "excecoes": [], "fechada": [1]}}
    plano = script.planear(script.IDAS, CONTAS, _lojas(Oeiras=oeiras), [])
    assert "Débora 06/10 em Oeiras: a loja está fechada nesse dia." in plano["saltadas"]


def test_uma_ida_ja_gravada_fica_de_fora_e_uma_que_choca_fica_a_que_la_esta():
    existentes = [dict(sn.ida("2026-11-01", sn.ALFRAGIDE, "u-bru", "10:00", "23:00"), id="x1"),
                  dict(sn.ida("2026-11-01", sn.OEIRAS, "u-mat", "12:00", "14:00"), id="x2")]
    plano = script.planear(script.IDAS, CONTAS, _lojas(), existentes)
    assert len(plano["gravar"]) == 94
    assert plano["saltadas"] == [
        "Bruce 01/11 Alfragide 10h–23h: já estava gravada.",
        "Matheus 01/11 Algueirão 13h–22h: choca com a ida já gravada das 12h às 14h — fica a que lá está."]


@pytest.fixture
def prod(mongod_porta):
    """Uma base pymongo com a forma da produção: contas, lojas com horário, o índice único e
    uma ida que não é da mensagem."""
    cliente = MongoClient("mongodb://127.0.0.1:%d" % mongod_porta)
    cliente.drop_database("teste_whatsapp")
    db = cliente["teste_whatsapp"]
    db.users.insert_many([dict(c) for c in CONTAS])
    db.locations.insert_many([dict(l) for l in _lojas()])
    semana = sn.semana_normal()
    for chave in ("empregados", "modelos", "atribuicoes"):   # a escala: o ensaio mostra os buracos que ficam
        db[sn.COLECOES[chave]].insert_many([dict(d) for d in semana[chave]])
    db.bolso_idas.create_index([("data", 1), ("user_id", 1), ("location_id", 1), ("inicio", 1)], unique=True)
    db.bolso_idas.insert_one(dict(sn.ida("2026-10-02", sn.AMADORA, "u-car", "14:00", "23:00"), id="de-antes"))
    yield db
    cliente.close()


def test_o_ensaio_nao_grava_nada(prod):
    linhas = []
    assert script.executar(prod, gravar=False, escrever=linhas.append) == 0
    assert prod.bolso_idas.count_documents({}) == 1
    assert "Total: 96 idas a gravar." in linhas
    assert linhas[-1].startswith("ENSAIO")
    assert sum(1 for l in linhas if l.startswith("DIVIDIDO AO MEIO: ")) == 14
    # Terça, 06/10: Alfragide fica coberta (Emily 14h–23h + Débora 10h–16h30), Oeiras fica
    # sem ninguém das 13h às 16h30 — o dono vê-o ANTES de gravar.
    assert ("DIVIDIDO AO MEIO: Débora 06/10: Alfragide 10h–16h30 + Oeiras 16h30–22h"
            " · ficam buracos: Oeiras 13h–16h30") in linhas


def test_gravar_grava_e_correr_outra_vez_nao_duplica_nem_apaga(prod):
    assert script.executar(prod, gravar=True, escrever=lambda _linha: None) == 0
    assert prod.bolso_idas.count_documents({}) == 97
    bruce = prod.bolso_idas.find_one({"user_id": "u-bru"}, {"_id": 0})
    assert (bruce["criado_por"], bruce["inicio"], bruce["fim"]) == ("whatsapp-out-dez-2026", "10:00", "23:00")
    linhas = []
    assert script.executar(prod, gravar=True, escrever=linhas.append) == 0
    assert prod.bolso_idas.count_documents({}) == 97
    assert "Total: 0 idas a gravar." in linhas
    assert prod.bolso_idas.find_one({"id": "de-antes"}) is not None


def test_parado_nao_grava_nada(prod):
    prod.users.insert_one({"id": "u-y", "name": "Carol Lopes", "role": "gerente"})
    linhas = []
    assert script.executar(prod, gravar=True, escrever=linhas.append) == 1
    assert prod.bolso_idas.count_documents({}) == 1
    assert linhas[-1] == "Nada foi gravado."


def test_procurar_json_desfaz_o_nome_ambiguo_sem_mudar_o_ficheiro(prod, monkeypatch):
    # Como o dono o faz em produção: -e PROCURAR_JSON='{"Carol": "Carol Santos"}'.
    prod.users.insert_one({"id": "u-y", "name": "Carol Lopes", "role": "gerente"})
    monkeypatch.setenv("PROCURAR_JSON", json.dumps({"Carol": "Carol Santos"}))
    linhas = []
    assert script.executar(prod, gravar=False, escrever=linhas.append) == 0
    assert "Total: 96 idas a gravar." in linhas
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_carregar_idas_whatsapp.py -q
```

Esperado: erro de colecção `ModuleNotFoundError: No module named 'carregar_idas_whatsapp'`.

- [ ] **Passo 3: Implementação**

`backend/carregar_idas_whatsapp.py`:

```python
"""Carrega no calendário as idas de outubro a dezembro de 2026 da mensagem de WhatsApp
(«Escala Outubro / Alfragide: 01- Deb …»). É para o DONO correr em produção — o assistente
não chega à base de produção.

    # 1) ver o que faria (ensaio; não grava nada):
    ssh root@187.124.4.163 "cd ~/RH && docker compose exec -T backend python -" < backend/carregar_idas_whatsapp.py
    # 2) só depois de ler e aprovar o que o ensaio mostrou:
    ssh root@187.124.4.163 "cd ~/RH && docker compose exec -T -e GRAVAR=1 backend python -" < backend/carregar_idas_whatsapp.py
    # um nome que casa com dois registos (ou com nenhum) desfaz-se sem mudar este ficheiro:
    ssh root@187.124.4.163 "cd ~/RH && docker compose exec -T -e PROCURAR_JSON='{\"Carol\": \"Carol Santos\"}' backend python -" < backend/carregar_idas_whatsapp.py

Corre dentro do contentor do backend (lido do stdin, na pasta /app), por isso importa o
`calendario` (Fase 2) e os ajudantes do `arranque_calendario` (Fase 1) que lá estão.

As regras:
- as pessoas encontram-se pelo nome entre as contas `admin`/`gerente` (o `_um` do arranque:
  palavra inteira, sem acentos); nenhuma ou mais de uma → PÁRA sem gravar nada;
- as lojas encontram-se da mesma maneira, mas SÓ entre as que têm horário: em produção há
  duas «Loja Alfragide» (a da Pizzaria e a da Fordaimon) e só a da Fordaimon recebeu horário
  no arranque da Fase 1. Nenhuma com horário, ou mais de uma → PÁRA. Excepto Benfica: sem
  horário (ou sem loja), as idas de Benfica ficam de fora e diz-se;
- PROCURAR_JSON='{"Carol": "Carol Santos"}' troca o nome a procurar (pessoa ou loja) por um
  mais comprido, para desfazer uma ambiguidade sem mudar este ficheiro;
- cada ida é o dia inteiro: o horário da loja nesse dia. Loja fechada ou por abrir nesse
  dia → essa ida fica de fora e diz-se;
- datas passadas entram (são o histórico da contagem);
- a mesma pessoa em duas lojas no mesmo dia choca (o dia inteiro nas duas). PROPOSTA: dividir
  ao meio — a primeira loja (pela ordem da mensagem) do abrir até ao meio do SEU horário, a
  segunda desde aí (ou desde que abre, se for mais tarde) até fechar. O ensaio mostra cada
  divisão E os buracos que ela deixa nas duas lojas (com a escala real); correr com GRAVAR=1
  é aprová-las. Três lojas no mesmo dia → PÁRA;
- uma ida igual a uma já gravada fica de fora; uma que choque com outra já gravada fica de fora
  e diz-se qual (nada se apaga nem se muda);
- nunca apaga nada.
"""
import json
import os
import sys
import uuid
from datetime import date, datetime, timezone

from pymongo.errors import DuplicateKeyError

import calendario
from arranque_calendario import Paragem, _normal, _um


def _dias(mes, *dias):
    return ["2026-%02d-%02d" % (mes, d) for d in dias]


# A mensagem, tal como o dono a mandou (gestores; tudo dia inteiro), pela ordem dela.
IDAS = {
    "Débora": [
        ("Benfica", _dias(10, 24, 25, 31)),
        ("Algueirão", _dias(10, 24) + _dias(12, 8)),
        ("Alfragide", _dias(10, 1, 2, 5, 6, 7, 8, 12, 13, 14, 15, 19, 20, 21, 22, 26, 27, 28, 29)
         + _dias(11, 2) + _dias(12, 8, 9, 10, 15, 16, 22, 30)),
        ("Oeiras", _dias(10, 6, 13, 20, 21, 27, 29, 30) + _dias(11, 1) + _dias(12, 10, 11, 14, 29)),
    ],
    "Carol": [
        ("Alfragide", _dias(10, 5) + _dias(11, 1, 3, 4, 5, 9, 10, 11, 12, 16, 17, 18, 19, 23, 24, 25, 26, 30)
         + _dias(12, 1, 2, 3, 7, 14, 17, 21, 23, 28, 29)),
        ("Oeiras", _dias(10, 31) + _dias(11, 2, 3, 10, 17, 24) + _dias(12, 1, 8, 12, 13, 15, 22)),
        ("Amadora", _dias(10, 22, 23, 25)),
    ],
    "Matheus": [
        ("Benfica", _dias(10, 24, 25, 26, 28, 29, 30, 31) + _dias(11, 2)),
        ("Algueirão", _dias(11, 1)),
    ],
    "Bruce": [
        ("Alfragide", _dias(11, 1)),
    ],
}
OPCIONAL = "Benfica"
CRIADO_POR = "whatsapp-out-dez-2026"


def _horas(horas):
    return "%s–%s" % (calendario.hora_curta(calendario.hhmm(horas[0])), calendario.hora_curta(calendario.hhmm(horas[1])))


def planear(idas, utilizadores, lojas, existentes, procurar=None):
    """Decide tudo sem tocar na base. Devolve {gravar, divididas, divididas_em, saltadas};
    levanta `Paragem` antes de qualquer escrita se um nome ou uma loja não forem inequívocos.
    `procurar` troca um nome curto por um mais comprido (o PROCURAR_JSON)."""
    procurar = procurar or {}
    gestores = [u for u in utilizadores if u.get("role") in calendario.GESTORES]
    pessoas = {nome: _um(gestores, procurar.get(nome, nome), "A pessoa") for nome in idas}
    saltadas, divididas, divididas_em, gravar = [], [], [], []
    # Só as lojas com horário recebem idas — e é isso que desfaz as duas «Loja Alfragide»
    # de produção (a da Pizzaria não tem horário).
    com_horario = [l for l in lojas if l.get("horario")]
    por_loja = {}
    for nome in sorted({loja for pares in idas.values() for loja, _datas in pares}):
        alvo = " %s " % _normal(procurar.get(nome, nome))
        if not [l for l in com_horario if alvo in " %s " % _normal(l.get("name"))]:
            existe = [l for l in lojas if alvo in " %s " % _normal(l.get("name"))]
            motivo = "ainda não tem horário" if existe else "não existe"
            if nome == OPCIONAL:
                saltadas.append("%s %s: as idas de %s ficam de fora." % (nome, motivo, nome))
                continue
            raise Paragem("A loja «%s» %s — correr primeiro o arranque da Fase 1." % (nome, motivo))
        por_loja[nome] = _um(com_horario, procurar.get(nome, nome), "A loja")

    # Por pessoa e dia, as lojas abertas nesse dia, pela ordem da mensagem.
    dias = {}
    for nome, pares in idas.items():
        for nome_loja, datas in pares:
            loja = por_loja.get(nome_loja)
            if not loja:
                continue
            for iso in datas:
                estado, janela = calendario.horario_do_dia(loja, date.fromisoformat(iso))
                if estado != "aberta":
                    saltadas.append("%s %s em %s: a loja está %s nesse dia." % (
                        nome, calendario.data_curta(iso), loja["name"], estado.replace("_", " ")))
                    continue
                dias.setdefault((nome, iso), []).append((loja, janela))

    for (nome, iso), lista in sorted(dias.items(), key=lambda par: (par[0][1], par[0][0])):
        if len(lista) > 2:
            raise Paragem("%s está em %d lojas a %s — dividir à mão." % (nome, len(lista), calendario.data_curta(iso)))
        partes = lista
        if len(lista) == 2:
            (loja1, j1), (loja2, j2) = lista
            meio = (j1[0] + j1[1]) // 2
            partes = [(loja1, (j1[0], meio)), (loja2, (max(meio, j2[0]), j2[1]))]
            if partes[1][1][0] >= partes[1][1][1]:
                raise Paragem("%s a %s: %s fecha antes do meio do horário de %s — dividir à mão." % (
                    nome, calendario.data_curta(iso), loja2["name"], loja1["name"]))
            divididas.append("%s %s: %s %s + %s %s" % (nome, calendario.data_curta(iso), loja1["name"],
                                                       _horas(partes[0][1]), loja2["name"], _horas(partes[1][1])))
            divididas_em.append((iso, (loja1["id"], loja2["id"])))
        for loja, horas in partes:
            nova = {"data": iso, "location_id": loja["id"], "user_id": pessoas[nome]["id"],
                    "inicio": calendario.hhmm(horas[0]), "fim": calendario.hhmm(horas[1])}
            resumo = "%s %s %s %s" % (nome, calendario.data_curta(iso), loja["name"], _horas(horas))
            if [e for e in existentes if all(e.get(k) == nova[k] for k in ("data", "location_id", "user_id", "inicio"))]:
                saltadas.append("%s: já estava gravada." % resumo)
                continue
            choque = calendario.choques([nova], existentes)
            if choque:
                outra = choque[0][1]
                saltadas.append("%s: choca com a ida já gravada das %s às %s — fica a que lá está." % (
                    resumo, calendario.hora_curta(outra["inicio"]), calendario.hora_curta(outra["fim"])))
                continue
            gravar.append(nova)
    return {"gravar": gravar, "divididas": divididas, "divididas_em": divididas_em, "saltadas": saltadas}


def _buracos_que_ficam(plano, dados):
    """Para cada divisão, os buracos que ficam nas duas lojas nesse dia — com a escala real,
    as ausências aprovadas, as idas já gravadas e as do plano (o mesmo cálculo do ecrã)."""
    textos = []
    for iso, ids in plano["divididas_em"]:
        lojas_do_dia = calendario.dia_do_calendario(date.fromisoformat(iso), dados)["lojas"]
        ficam = ["%s %s" % (l["nome"], ", ".join("%s–%s" % (calendario.hora_curta(b["inicio"]), calendario.hora_curta(b["fim"]))
                                                  for b in l["buracos"]))
                 for l in lojas_do_dia if l["location_id"] in ids and l["buracos"]]
        textos.append("; ".join(ficam) or "nenhum nestas duas lojas")
    return textos


def executar(db, gravar, escrever=print):
    """0 = feito (ou ensaio feito); 1 = parado sem gravar nada."""
    # Um JSON partido rebenta aqui, antes de qualquer leitura ou escrita na base.
    procurar = json.loads(os.environ.get("PROCURAR_JSON") or "{}")
    utilizadores = list(db.users.find({}, {"_id": 0, "id": 1, "name": 1, "role": 1, "employee_id": 1}))
    lojas = list(db.locations.find(
        {}, {"_id": 0, "id": 1, "name": 1, "company_id": 1, "horario": 1, "aberta_desde": 1}))
    existentes = list(db.bolso_idas.find({"data": {"$gte": "2026-10-01", "$lte": "2026-12-31"}}, {"_id": 0}))
    try:
        plano = planear(IDAS, utilizadores, lojas, existentes, procurar)
    except Paragem as e:
        escrever("PARADO: %s" % e)
        escrever("Nada foi gravado.")
        return 1
    for linha in plano["saltadas"]:
        escrever("fica de fora: " + linha)
    novas = [dict(i, id="plano-%d" % n) for n, i in enumerate(plano["gravar"])]
    dados = {
        "lojas": lojas, "utilizadores": utilizadores, "idas": existentes + novas,
        "empregados": list(db.employees.find({}, {"_id": 0, "id": 1, "name": 1, "location_id": 1})),
        "atribuicoes": list(db.work_schedule_assignments.find({}, {"_id": 0})),
        "modelos": list(db.work_schedule_templates.find({}, {"_id": 0, "id": 1, "work_days": 1, "dias": 1})),
        "ausencias": list(db.leave_requests.find(
            {"status": "aprovado"}, {"_id": 0, "employee_id": 1, "start_date": 1, "end_date": 1, "status": 1})),
    }
    for linha, ficam in zip(plano["divididas"], _buracos_que_ficam(plano, dados)):
        escrever("DIVIDIDO AO MEIO: %s · ficam buracos: %s" % (linha, ficam))
    nomes = {u["id"]: u.get("name") for u in utilizadores}
    for user_id in sorted({i["user_id"] for i in plano["gravar"]}, key=lambda u: nomes.get(u) or ""):
        escrever("%s: %d idas" % (nomes.get(user_id), sum(1 for i in plano["gravar"] if i["user_id"] == user_id)))
    escrever("Total: %d idas a gravar." % len(plano["gravar"]))
    if not gravar:
        escrever("ENSAIO — nada foi gravado. Para gravar, correr de novo com GRAVAR=1.")
        return 0
    agora = datetime.now(timezone.utc).isoformat()
    feitas = 0
    for ida in plano["gravar"]:
        doc = dict(ida, id=str(uuid.uuid4()), criado_por=CRIADO_POR, criado_em=agora,
                   alterado_por=None, alterado_em=None)
        try:
            db.bolso_idas.insert_one(doc)
            feitas += 1
        except DuplicateKeyError:
            escrever("não gravada (alguém a marcou entretanto): %s %s" % (ida["data"], ida["user_id"]))
    escrever("Gravadas %d idas." % feitas)
    return 0


if __name__ == "__main__":
    from pymongo import MongoClient

    cliente = MongoClient(os.environ["MONGO_URL"])
    sys.exit(executar(cliente[os.environ["DB_NAME"]], os.environ.get("GRAVAR") == "1"))
```

- [ ] **Passo 4: Correr e ver passar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_carregar_idas_whatsapp.py -q -rs
```

Esperado: `11 passed`, sem `skipped`.

- [ ] **Passo 5: Prova por mutação**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PY=~/Developer/RH/backend/.venv/bin/python
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py carregar_idas_whatsapp.py 'meio = (j1[0] + j1[1]) // 2' 'meio = j1[1]' -- $PY -m pytest tests/calendario/test_carregar_idas_whatsapp.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py carregar_idas_whatsapp.py '    if not gravar:' '    if False:' -- $PY -m pytest tests/calendario/test_carregar_idas_whatsapp.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py carregar_idas_whatsapp.py 'OPCIONAL = "Benfica"' 'OPCIONAL = "Nenhuma"' -- $PY -m pytest tests/calendario/test_carregar_idas_whatsapp.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py carregar_idas_whatsapp.py 'for k in ("data", "location_id", "user_id", "inicio"))]:' 'for k in ("data", "location_id", "user_id", "inicio")) and False]:' -- $PY -m pytest tests/calendario/test_carregar_idas_whatsapp.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py carregar_idas_whatsapp.py 'com_horario = [l for l in lojas if l.get("horario")]' 'com_horario = lojas' -- $PY -m pytest tests/calendario/test_carregar_idas_whatsapp.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py carregar_idas_whatsapp.py '_um(gestores, procurar.get(nome, nome), "A pessoa")' '_um(gestores, nome, "A pessoa")' -- $PY -m pytest tests/calendario/test_carregar_idas_whatsapp.py -q
PYTHONDONTWRITEBYTECODE=1 $PY tests/mutar.py carregar_idas_whatsapp.py '"idas": existentes + novas,' '"idas": existentes,' -- $PY -m pytest tests/calendario/test_carregar_idas_whatsapp.py -q
```

Esperado: (1) `FAILED` nos testes que planeiam a mensagem inteira (Alfragide 10–23 e Oeiras desde as 23h: `Paragem … dividir à mão`); (2) `FAILED …test_o_ensaio_nao_grava_nada`; (3) `FAILED …test_uma_loja_sem_horario_para_tudo_excepto_benfica`; (4) `FAILED …test_uma_ida_ja_gravada_fica_de_fora…` (a repetida passa a «choca com»); (5) `FAILED` em todos os que planeiam a mensagem (`Paragem: A loja «Alfragide» casa com 2: «Alfragide» (loja-alfragide), «Loja Alfragide» (loja-pizzaria-alfragide)` — é o que acontecia em produção); (6) `FAILED …test_procurar_json_desfaz_o_nome_ambiguo…` (`PARADO: A pessoa «Carol» casa com 2`); (7) `FAILED …test_o_ensaio_nao_grava_nada` (sem as idas do plano, a linha de 06/10 diz `Alfragide 10h–14h; Oeiras 13h–22h`). Todas com «Mutação apanhada».

- [ ] **Passo 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add backend/carregar_idas_whatsapp.py backend/tests/calendario/test_carregar_idas_whatsapp.py
git commit -m "Calendário: script para o dono carregar as idas de outubro a dezembro

As idas que as gestoras combinaram por WhatsApp entram no calendário pelo script que o
dono corre em produção (ensaio primeiro, GRAVAR=1 para gravar). Os dias em que a mesma
pessoa estava em duas lojas com o dia inteiro passam a chocar; o ensaio mostra a proposta
de dividir o dia ao meio, com os buracos que cada divisão deixa, para o dono decidir.
As lojas procuram-se só entre as que têm horário (há duas Loja Alfragide em produção, e
só a da Fordaimon tem horário); um nome ambíguo desfaz-se com PROCURAR_JSON, sem mudar o
ficheiro. Pára em nomes ambíguos e nunca apaga nada.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Tarefa 15: Ensaio local no browser — 375 px, claro e escuro, com os dados da semana normal

Nada versionado muda nesta tarefa. Se algo falhar, a correcção volta à tarefa do ecrã (11, 12 ou 13) com um teste primeiro, e o ensaio repete-se. Reusa a infra-estrutura do ensaio da Fase 1 (mongod em `127.0.0.1:27031`, frontend em `127.0.0.1:3031` com `frontend/.env.development.local`), numa **base à parte** (`rh_calendario_fase2_local`) para não misturar com os dados do ensaio da Fase 1.

**Ficheiros (só locais, nunca versionados):**
- Criar: `$HOME/.cache/lisbonb-calendario-local/backend-fase2.env`, `$HOME/.cache/lisbonb-calendario-local/semear_fase2.py`, `$HOME/.cache/lisbonb-calendario-local/contas-fase2.txt` (escrito pelo seed, modo 600)
- Modificar: `/Users/matheus.moraes/Library/CloudStorage/OneDrive-Pessoal/Claude/.claude/launch.json` (uma entrada nova)

**Interfaces:**
- Consome: as Tarefas 1-13; `tests/calendario/dados_semana_normal.py`; a entrada `calendario-frontend` e o `frontend/.env.development.local` da Fase 1 (Tarefa 8 de lá).
- Produz: a base local `rh_calendario_fase2_local` com a semana normal, as férias do Weber (21–25/10), a Carol na Amadora a 22, 23 e 25/10 e a Débora em Oeiras a 6, 13 e 20/10; backend de ensaio em `127.0.0.1:8031` (entrada `calendario-backend-fase2`).

- [ ] **Passo 1: O ambiente (segredos gerados, nunca mostrados)**

```bash
mkdir -p "$HOME/.cache/lisbonb-calendario-local/mongo"
cd "$HOME/.cache/lisbonb-calendario-local"
test -e backend.env || ( umask 077 && ~/Developer/RH/backend/.venv/bin/python - > backend.env <<'PY'
import secrets
print("MONGO_URL=mongodb://127.0.0.1:27031")
print("DB_NAME=rh_calendario_local")
print("JWT_SECRET=" + secrets.token_urlsafe(32))
print("POS_JWT_SECRET=" + secrets.token_urlsafe(32))
print("ADMIN_EMAIL=admin.calendario@example.com")
print("ADMIN_PASSWORD=" + secrets.token_urlsafe(18))
print("CORS_ORIGINS=*")
PY
)
( umask 077 && sed 's/^DB_NAME=.*/DB_NAME=rh_calendario_fase2_local/' backend.env > backend-fase2.env )
sed -E 's/=.*/=<…>/' backend-fase2.env      # só os nomes, nunca os valores
cd /Users/matheus.moraes/Developer/RH-calendario
test -e frontend/.env.development.local || printf 'REACT_APP_BACKEND_URL=http://127.0.0.1:8031\nBROWSER=none\nPORT=3031\nHOST=127.0.0.1\n' > frontend/.env.development.local
git check-ignore frontend/.env.development.local && git status -s
```

Esperado: os nomes das 7 variáveis; o `check-ignore` imprime o caminho; `git status -s` vazio.

- [ ] **Passo 2: O seed do ensaio**

`$HOME/.cache/lisbonb-calendario-local/semear_fase2.py`:

```python
"""Dados do ensaio local do calendário (fase 2). SÓ na base local `rh_calendario_fase2_local`.

A semana normal (backend/tests/calendario/dados_semana_normal.py), as férias do Weber
(21–25/10), a Carol na Amadora a 22, 23 e 25/10 e a Débora em Oeiras a 6, 13 e 20/10. As
contas da Débora, da Carol, do Guilherme (gerente) e da Rita (contabilista) levam palavras-
-passe geradas, escritas em contas-fase2.txt (modo 600) — nunca no ecrã."""
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

import bcrypt
from pymongo import MongoClient

sys.path.insert(0, os.path.expanduser("~/Developer/RH-calendario/backend"))
from tests.calendario import dados_semana_normal as sn  # noqa: E402

URL, BASE = os.environ["MONGO_URL"], os.environ["DB_NAME"]
if URL != "mongodb://127.0.0.1:27031" or BASE != "rh_calendario_fase2_local":
    sys.exit("Recuso: isto só corre na base local do ensaio (127.0.0.1:27031/rh_calendario_fase2_local).")
db = MongoClient(URL, serverSelectionTimeoutMS=3000)[BASE]
if db.users.count_documents({"email": {"$regex": "@example.com$"}, "role": {"$ne": "admin"}}) or db.locations.count_documents({}):
    sys.exit("Já estava semeado — nada feito.")
dados = sn.semana_normal()
dados["ausencias"].append(sn.ausencia("Weber", "2026-10-21", "2026-10-25"))
dados["idas"] += [sn.ida(d, sn.AMADORA, sn.CAROL, "14:00", "23:00") for d in ("2026-10-22", "2026-10-23", "2026-10-25")]
dados["idas"] += [sn.ida(d, sn.OEIRAS, sn.DEBORA, "13:00", "22:00") for d in ("2026-10-06", "2026-10-13", "2026-10-20")]
agora = datetime.now(timezone.utc).isoformat()
linhas = []
for u in dados["utilizadores"]:
    senha = secrets.token_urlsafe(12)
    u.update(email="%s@example.com" % u["id"], must_change_password=False, created_at=agora,
             password=bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode())
    if u["role"] != "colaborador":
        linhas.append("%s (%s): %s %s" % (u["name"], u["role"], u["email"], senha))
for e in dados["empregados"]:
    e.update(user_id=sn.user(e["name"]), email="%s@example.com" % sn.user(e["name"]), created_at=agora)
db.companies.insert_one({"id": sn.FORDAIMON, "name": "Fordaimon Foods (ensaio)", "created_at": agora})
db.companies.insert_one({"id": sn.LENHA, "name": "Lenha e Brasa (ensaio)", "created_at": agora})
for chave, colecao in sn.COLECOES.items():
    if dados[chave]:
        db[colecao].insert_many([dict(d) for d in dados[chave]])
ficheiro = Path(os.path.expanduser("~/.cache/lisbonb-calendario-local/contas-fase2.txt"))
ficheiro.write_text("\n".join(linhas) + "\n", encoding="utf-8")
ficheiro.chmod(0o600)
print("Semeado. Contas de ensaio em %s" % ficheiro)
```

Para ler a base local nos passos seguintes (mostra só o que se pede):

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend && set -a && . "$HOME/.cache/lisbonb-calendario-local/backend-fase2.env" && set +a && ~/Developer/RH/backend/.venv/bin/python - <<'PY'
import os, pprint
from pymongo import MongoClient
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
pprint.pprint(list(db.bolso_idas.find({}, {"_id": 0, "data": 1, "user_id": 1, "location_id": 1, "inicio": 1, "fim": 1}).sort("data", 1)))
pprint.pprint({k: v.get("unique", False) for k, v in db.bolso_idas.index_information().items()})
PY
```

- [ ] **Passo 3: A entrada do `launch.json`**

Ler `/Users/matheus.moraes/Library/CloudStorage/OneDrive-Pessoal/Claude/.claude/launch.json` e acrescentar ao array `configurations` (sem mexer nas outras):

```json
    {
      "name": "calendario-backend-fase2",
      "runtimeExecutable": "bash",
      "runtimeArgs": ["-c", "cd $HOME/Developer/RH-calendario/backend && exec $HOME/Developer/RH/backend/.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8031 --env-file $HOME/.cache/lisbonb-calendario-local/backend-fase2.env"],
      "port": 8031
    }
```

Se a entrada `calendario-frontend` (Fase 1) não existir, acrescentar também:

```json
    {
      "name": "calendario-frontend",
      "runtimeExecutable": "bash",
      "runtimeArgs": ["-c", "export PATH=$HOME/.local/node/bin:$PATH; cd $HOME/Developer/RH-calendario/frontend && exec ./node_modules/.bin/craco start"],
      "port": 3031,
      "url": "http://127.0.0.1:3031"
    }
```

Validar: `python3 -m json.tool < /Users/matheus.moraes/Library/CloudStorage/OneDrive-Pessoal/Claude/.claude/launch.json > /dev/null && echo ok`.

- [ ] **Passo 4: Arrancar e semear**

1. O mongod (pela Bash com `run_in_background: true`; se o da Fase 1 já estiver a correr na 27031, usa-se esse): `/opt/homebrew/bin/mongod --dbpath "$HOME/.cache/lisbonb-calendario-local/mongo" --port 27031 --bind_ip 127.0.0.1 --quiet`
2. O seed: `cd /Users/matheus.moraes/Developer/RH-calendario/backend && set -a && . "$HOME/.cache/lisbonb-calendario-local/backend-fase2.env" && set +a && ~/Developer/RH/backend/.venv/bin/python "$HOME/.cache/lisbonb-calendario-local/semear_fase2.py"` → «Semeado. Contas de ensaio em …».
3. Se o `calendario-backend` da Fase 1 estiver a correr, `preview_stop` nele (mesma porta). `preview_start` com `name: "calendario-backend-fase2"`; `curl -s http://127.0.0.1:8031/api/health` → `healthy`.
4. Ler a base (comando do Passo 2): as 6 idas semeadas e, nos índices, um com `True` — **é a prova de que o `startup_event` cria o índice único** (o seed não o cria).
5. `preview_start` com `name: "calendario-frontend"` (ver `preview_logs` até «Compiled»).
6. `resize_window` com `preset: "mobile"` e `colorScheme: "light"`. No browser: `http://127.0.0.1:3031/login`, entrar como a Débora com o email e a palavra-passe de `contas-fase2.txt` (valores de teste deste ensaio, lidos do ficheiro — não os escrever no chat). Depois abrir `http://127.0.0.1:3031/bolso`.

- [ ] **Passo 5: O menu na Faturação**

1. O ☰ está à esquerda do nome do âmbito; a barra das empresas continua no fundo; o «Terminar sessão» já não está no fundo da página. Captura.
2. Tocar no ☰: abre à esquerda com «Gestão Lisbonb», Faturação (marcada), Calendário e, no fundo, «Débora Ferreira · Terminar sessão»; o X tem 44 px (`javascript_tool`: `document.querySelector('[aria-label="Fechar menu"]').getBoundingClientRect().height` → `44`) e não há outro X pequeno. Captura.
3. Tocar em «Calendário» → `/bolso/calendario`.

- [ ] **Passo 6: O calendário — Mês e Geral**

O «hoje» é o do relógio desta máquina. Ir com ‹ › a outubro de 2026 se for preciso.

1. O título diz o mês; Mês/Lista/Contagem em cima, Pessoal/Geral/Férias em baixo; o dia de hoje (se for de outubro) vem escolhido e com o aro.
2. Pontos vermelhos: há em 05/10 (feriado, também noutra cor) e 06/10, não há em 02, 03 e 04/10; de 24/10 em diante todos têm (Benfica). Todas as células têm 44 px: `[...document.querySelectorAll('[data-dia]')].every((b) => b.getBoundingClientRect().height >= 44)` → `true`.
3. Tocar em 27/10: Alfragide «falta 10h–14h» (amarelo), Benfica «ninguém» e Oeiras «ninguém» (vermelho), Belém «fechada» (cinzento), as outras com quem lá está e «escala». Tocar em 22/10: Amadora com «Carol Santos 14h–23h ida». Tocar em 21/10: Amadora «ninguém» (Weber de férias). Capturas.

- [ ] **Passo 7: Tapar, o atalho e os erros**

1. 05/10 → «Tapar» em Alfragide: painel de baixo «Tapar Alfragide», Das 10:00 Às 14:00, «Débora Ferreira» marcada, 05/10 marcado, o botão «Também nas outras segundas deste mês com buraco em Alfragide». Tocar no atalho → 12, 19 e 26/10 marcados → «Marcar 4 idas». O painel fecha, o dia mostra a Débora 10h–14h «ida» e Alfragide deixa de ter buraco de manhã. Ler a base: +4 idas.
2. «Marcar ida» (fundo da página): o painel abre **sem loja e sem horas** («Escolher…», campos de hora vazios, «Marcar 1 ida» desligado). Escolher a loja Amadora → as horas passam sozinhas a 14:00–23:00. Nas pessoas, tocar na Débora (desmarca) e no Weber; na grelha do painel deixar só o 21/10 → «Marcar 1 ida» → texto vermelho «Weber está de férias a 21/10.» e «Escolha outra pessoa ou outro dia.»; o painel fica aberto. Fechar.
3. «Marcar ida»: loja Oeiras, só a Débora, só o 05/10, 13:00–22:00 → «Débora já está em Alfragide das 10h às 14h a 05/10.» e «Mude as horas ou apague primeiro a outra ida.». Fechar.
4. «Marcar ida»: loja Belém, só o 27/10, 11:30–19:00 → «Belém está fechada a 27/10. Escolha outro dia.» Fechar.
5. Ler a base: continua com as 10 idas (6 do seed + 4) — nenhum dos erros gravou nada.

- [ ] **Passo 8: Editar, apagar, Lista, Contagem, Férias e a memória**

1. Pessoal → 05/10 → tocar na ida → «Ida de Débora Ferreira» com «Guardar» e «Apagar». Das 11:00 → Guardar → a ida passa a 11h–14h. Abrir de novo → «Apagar» → «Tocar de novo para apagar» → tocar → desaparece. Ler a base: 9 idas.
2. Lista (Geral): começa no dia de hoje se hoje for de outubro (senão no 1.º); só dias com buracos ou idas.
3. Contagem: «Débora · outubro … · 2026 …» e «Carol · outubro 3 dias · 2026 3 dias»; tocar abre os 12 meses; os filtros de baixo desaparecem.
4. Férias → 21/10: «Weber · Férias · 21/10–25/10 · Amadora».
5. Deixar em Lista + Férias, recarregar a página → volta em Lista + Férias.

- [ ] **Passo 9: Quem só lê**

☰ → Terminar sessão → entrar como a Rita (contabilista, `contas-fase2.txt`) → `/bolso/calendario`: os buracos aparecem, mas sem «Tapar» nem «Marcar ida»; tocar numa ida não abre nada.

- [ ] **Passo 10: 375 px, claro e escuro, com a zona da notch**

1. Simular a notch só para olhar (não é código): no `javascript_tool`, `document.head.insertAdjacentHTML('beforeend', '<style>.safe-area-inset-top{padding-top:47px!important}.safe-area-inset-bottom{padding-bottom:34px!important}</style>')`. O cabeçalho e o menu descem para baixo da notch; a barra dos filtros e o fundo do painel sobem acima da barra de casa. Capturas: Mês com um dia aberto, painel aberto, menu aberto, Lista, Contagem.
2. Sem deslocamento para o lado: `document.documentElement.scrollWidth <= window.innerWidth` → `true` em Mês, Lista, Contagem e com o painel aberto.
3. Contraste dos buracos (texto sobre o fundo translúcido do cartão), no claro:

```js
const lum = (c) => c.match(/[\d.]+/g).slice(0, 3).map(Number).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }).reduce((s, v, i) => s + v * [0.2126, 0.7152, 0.0722][i], 0);
const mistura = (fg, bg) => { const f = fg.match(/[\d.]+/g).map(Number); const b = bg.match(/[\d.]+/g).map(Number); const a = f.length > 3 ? f[3] : 1; return 'rgb(' + [0, 1, 2].map((i) => f[i] * a + b[i] * (1 - a)).join(',') + ')'; };
const contraste = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
[...document.querySelectorAll('[data-buraco]')].map((el) => [el.dataset.buraco, contraste(getComputedStyle(el.querySelector('span')).color, mistura(getComputedStyle(el).backgroundColor, getComputedStyle(el.closest('section')).backgroundColor)).toFixed(2)])
```

   Esperado: todos ≥ 4,5 — o «ninguém» é branco sobre `bg-destructive-strong` (6,5:1 no claro, 6,0:1 no escuro) e o «falta» `text-warning-strong` sobre `bg-warning/15` (4,5:1 no claro, o mais justo; 7,2:1 no escuro). Se algum ficar abaixo, a correcção volta à Tarefa 13 e passa esse selo a pastilha cheia, `bg-<cor>-strong text-white` (os pares medidos em `frontend/src/index.css`, `--*-strong`), com o `BURACOS_DO_DIA` a prender as classes novas, ver vermelho, corrigir, e repetir esta medição. **Nunca** `text-*-strong` como texto no escuro: esses tokens foram afinados para fundo de pastilha com texto branco e dão ≈3,0:1 sobre o cartão escuro.
4. `resize_window` com `colorScheme: "dark"`, recarregar e repetir 1-3. Os `<select>` e os campos de hora legíveis; nada branco sobre branco.
5. No fim: `resize_window` com `preset: "desktop"` e `colorScheme: "light"`.

- [ ] **Passo 11: Consola e arrumar**

1. `read_console_messages` com `onlyErrors: true` → nenhum erro além dos pedidos 400/409 previstos do Passo 7.
2. `preview_stop` dos dois servidores; parar o mongod: `pkill -f "mongod --dbpath $HOME/.cache/lisbonb-calendario-local/mongo"`.
3. `cd /Users/matheus.moraes/Developer/RH-calendario && git status -s` → vazio.

---

### Tarefa 16: Publicar (fluxo B, com o «sim» do dono) e confirmar o que ficou no ar

Acções externas: push para o GitHub, merge no `main` e deploy. **Nenhum destes passos corre sem um «sim» claro do dono no chat.** O `main` está aberto noutro worktree (`~/Developer/RH-qr-aplicacoes`), por isso o merge faz-se num worktree temporário, desligado, a partir de `origin/main` — sem tocar em `~/Developer/RH` nem nesse worktree. Deploy só do site: **a casca (build 2) carrega `https://rh.lisbonb.com/bolso` e recebe o ecrã novo sem build nova.**

**Ficheiros:** nenhum versionado. Temporários: `/private/tmp/rh-publicar-calendario-2` (worktree, removido no fim), `$HOME/.cache/lisbonb-calendario-local/build`.

**Interfaces:**
- Consome: os commits das Tarefas 1-14.
- Produz: `main` no GitHub com o ramo juntado; produção a servir o bundle novo (marcadores `bolso_cal_vista` e `calendario/contagem`) e o `server.py` novo (`_bolso_criar_indices`).

- [ ] **Passo 1: Pré-condições, suite inteira e build local**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git fetch origin
git log --oneline origin/main | grep -i "fase 1\|horário\|horario" | head -3     # a Fase 1 já está no main?
git log --oneline origin/main | grep -i "niveis\|níveis" | head -3                 # os níveis de conta já entraram?
cd backend
export PATH="$HOME/.local/node/bin:$PATH"
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest -q 2>&1 | tail -3
cd ../frontend
CI=false REACT_APP_BACKEND_URL="" BUILD_PATH="$HOME/.cache/lisbonb-calendario-local/build" ./node_modules/.bin/craco build 2>&1 | tail -5
grep -l "bolso_cal_vista" "$HOME/.cache/lisbonb-calendario-local/build/static/js/"main.*.js
grep -l "calendario/contagem" "$HOME/.cache/lisbonb-calendario-local/build/static/js/"main.*.js
```

Esperado: a Fase 1 no `main` (se não estiver, PARAR — esta fase lê `horario` e `dias`, que a Fase 1 grava, e as lojas de produção só os têm depois do script de arranque dela, que o dono corre); suite com `passed` = partida + 147 (os testes desta fase), `skipped` = partida, `0 failed`; build sem erros e os dois `grep` a mostrar o `main.*.js`.

- [ ] **Passo 2: Pedir o «sim» ao dono**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git log --oneline origin/main..HEAD
git diff --stat origin/main...HEAD
ANTES=$(curl -s https://lisbonb.com/bolso | grep -oE '/static/js/main\.[a-z0-9]+\.js' | head -1); echo "$ANTES"
```

Mostrar ao dono, em linguagem simples: o ramo, os commits, os ficheiros; o que muda para quem usa (na Gestão Lisbonb: o ☰ com Faturação, Calendário e Terminar sessão; o Calendário com os buracos de cada loja, Tapar, Marcar, Lista, Contagem e os filtros; o contabilista só vê); que **não muda nada no portal, no ponto, no saldo de férias nem no painel**; que não precisa de build nova da app; e que depois se segue o script das idas de WhatsApp (Tarefa 17). Anotar o `$ANTES`.

Perguntar-lhe também, e esperar pelas respostas:

1. **«O script de arranque da Fase 1 (`arranque_calendario.py`, com `GRAVAR=1`) já correu em produção?»** Sem ele as lojas não têm `horario` e o Calendário abre sem lojas nenhumas (só as lojas com horário entram). Se não correu, publicar continua a ser seguro (não estraga nada), mas o caminho feliz do Passo 6 e a Tarefa 17 ficam à espera dele — dizê-lo.
2. **A decisão por omissão da Tarefa 3:** «Se uma colaboradora tiver uma ida marcada e as férias dela forem aprovadas depois, a ida deixa de tapar a loja (o calendário volta a mostrar o buraco) e continua na vista Pessoal e na Lista, para alguém a mudar ou apagar. Concorda?» Se não concordar, PARAR: muda-se o `continue` assinalado em `dia_do_calendario` com um teste primeiro, antes de publicar.

**Parar aqui até haver um «sim».**

- [ ] **Passo 3: Enviar o ramo e juntar ao `main`**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git push -u origin matheus-calendario-gestao
git fetch origin
BASE=$(git merge-base HEAD origin/main); git log --oneline "$BASE"..origin/main   # vazio = ninguém juntou nada desde a última vez
git worktree add --detach /private/tmp/rh-publicar-calendario-2 origin/main
cd /private/tmp/rh-publicar-calendario-2
git merge --no-ff matheus-calendario-gestao \
  -m "merge: calendário automático das lojas na Gestão Lisbonb (fase 2)" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- Se o merge tiver **conflitos**: parar, `git merge --abort`, explicar ao dono que ficheiros chocam e resolver com ele. Nunca forçar.
- Se o `git log "$BASE"..origin/main` **não** vier vazio (por exemplo, entraram os níveis de conta do ramo `matheus-niveis-de-conta`), correr a suite no worktree temporário antes do push: `ln -sfn ~/Developer/RH/frontend/node_modules frontend/node_modules && cd backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest -q 2>&1 | tail -3` (0 failed; o `skipped` igual) e depois `rm /private/tmp/rh-publicar-calendario-2/frontend/node_modules`. **Se o teste de cobertura dos níveis de conta ficar vermelho por causa das rotas `/api/bolso/calendario…`**, acrescentar ao mapa desse trabalho a linha que ele pedir, pondo-as na mesma gaveta do `/api/bolso/painel` (`painel`, desenho, «Níveis de conta»), commit no worktree temporário com a mesma regra das mensagens, e voltar a correr a suite.

```bash
cd /private/tmp/rh-publicar-calendario-2
git push origin HEAD:main
cd /Users/matheus.moraes/Developer/RH-calendario
git worktree remove /private/tmp/rh-publicar-calendario-2
```

Se o push for recusado (alguém juntou entretanto): `git worktree remove --force /private/tmp/rh-publicar-calendario-2` e repetir este passo desde o `git fetch origin`.

- [ ] **Passo 4: Deploy (só o `main`)**

```bash
ssh root@187.124.4.163 'cd ~/RH && git checkout main && git pull && docker compose up -d --build'
curl -s https://lisbonb.com/api/health
```

Esperado: `healthy`. A saída do deploy não decide nada (já disse «concluído» com o código antigo e «Error» com tudo bem): decidem os passos seguintes.

- [ ] **Passo 5: Confirmar o que está a ser servido**

```bash
JS=$(curl -s https://lisbonb.com/bolso | grep -oE '/static/js/main\.[a-z0-9]+\.js' | head -1); echo "$JS"
curl -s "https://lisbonb.com$JS" | grep -c "bolso_cal_vista"
curl -s "https://lisbonb.com$JS" | grep -c "calendario/contagem"
curl -s -o /dev/null -w '%{http_code}\n' 'https://lisbonb.com/api/bolso/calendario?ano=2026&mes=10'
ssh root@187.124.4.163 'cd ~/RH && git log --oneline -1 && docker compose exec -T backend grep -c "_bolso_criar_indices" server.py && docker compose logs --since 15m backend | grep -c "índices de bolso_idas"'
# A casca (build 2) carrega https://rh.lisbonb.com/bolso, não lisbonb.com: confirmar esse endereço também.
JS_RH=$(curl -s https://rh.lisbonb.com/bolso | grep -oE '/static/js/main\.[a-z0-9]+\.js' | head -1); echo "$JS_RH"
curl -s "https://rh.lisbonb.com$JS_RH" | grep -c "bolso_cal_vista"
```

Esperado: `$JS` diferente do `$ANTES`; `$JS_RH` igual ao `$JS`; os três `grep -c` dos bundles ≥ 1; o `curl` à rota nova dá `403` (sem sessão; um `404` quer dizer que o backend novo não está a correr); o `git log` no commit de merge; o `grep` do backend ≥ 2; e `0` avisos de índices por criar.

Se o nome do bundle não mudou ou os `grep -c` dão 0:

```bash
ssh root@187.124.4.163 'cd ~/RH && docker compose build --no-cache frontend && docker compose up -d frontend'
```

e repetir este passo.

- [ ] **Passo 6: O caminho feliz, a sério (com o dono)**

Os dados de produção não se escrevem pelo assistente, por isso o caminho feliz com gravação faz-o o dono, guiado passo a passo; se o painel do browser já tiver sessão em `https://lisbonb.com`, o assistente pode acompanhar a ler (sem escrever palavras-passe):

1. Na app «Gestão Lisbonb» do iPhone (build 2, sem actualizar nada): o ☰ aparece no cabeçalho, **abaixo da notch**; abre o menu; «Calendário».
2. O mês abre no dia de hoje; as lojas que tiverem horário (as da Fase 1) aparecem com quem lá está; os buracos a vermelho/amarelo batem com a escala real.
3. Num dia futuro com buraco, «Tapar» com ele próprio → a ida aparece no dia e na Contagem; depois abri-la e «Apagar» com dois toques → desaparece.
4. ☰ → Faturação continua a abrir os números de sempre; ☰ → Terminar sessão leva ao login.

Se algo falhar: reproduzir em local (Tarefa 15), corrigir com teste primeiro, e repetir desta tarefa o que for preciso.

---

### Tarefa 17: Carregar as idas de outubro a dezembro (o dono corre o script, com confirmação)

Só depois da Tarefa 16 no ar **e** do script de arranque da Fase 1 corrido pelo dono (as lojas têm de ter `horario`). Ninguém além do dono escreve na base de produção.

**Ficheiros:** nenhum novo, e nenhum muda. Se o ensaio parar por um nome que casa com dois registos ou com nenhum (ex.: há uma «Carol Lopes» gerente, ou a conta da Carol chama-se «Carolina …»), perguntar ao dono qual é o registo certo e juntar ao comando `-e PROCURAR_JSON=…` com a chave curta (a do `IDAS`, ou o nome da loja) e um nome mais comprido que só case com esse registo — sem mudar o ficheiro, sem commit e sem deploy. Casa por palavras inteiras, sem acentos nem maiúsculas, por isso escreve-se sem acentos nem apóstrofos. Exemplo, dentro das aspas do `ssh`:

```bash
ssh root@187.124.4.163 "cd ~/RH && docker compose exec -T -e PROCURAR_JSON='{\"Carol\": \"Carol Santos\"}' backend python -" < backend/carregar_idas_whatsapp.py
```

O mesmo `-e PROCURAR_JSON=…` vai depois no comando do Passo 3. As duas «Loja Alfragide» de produção (Pizzaria e Fordaimon) não precisam disto: o script só procura entre as lojas com horário, e só a da Fordaimon o tem.

**Interfaces:**
- Consome: `backend/carregar_idas_whatsapp.py` (Tarefa 14) e o `calendario.py` e o `arranque_calendario.py` que estão no contentor de produção.
- Produz: as idas da mensagem em `bolso_idas` de produção, com `criado_por = "whatsapp-out-dez-2026"`.

- [ ] **Passo 1: O ensaio (o dono corre)**

Pedir ao dono que corra, no terminal dele, a partir de `/Users/matheus.moraes/Developer/RH-calendario`:

```bash
ssh root@187.124.4.163 "cd ~/RH && docker compose exec -T backend python -" < backend/carregar_idas_whatsapp.py
```

e que cole a saída.

- [ ] **Passo 2: Ler o ensaio com o dono**

- `PARADO: …` → explicar o que pára (nome ambíguo, loja sem horário — se for «correr primeiro o arranque da Fase 1», é isso mesmo: o dono corre-o antes) e resolver como diz o cabeçalho desta tarefa; repetir o Passo 1.
- `fica de fora: …` → ler cada linha com ele (Benfica sem horário, dias de loja fechada, idas que já lá estavam ou que chocam com outras já marcadas na app).
- `DIVIDIDO AO MEIO: … · ficam buracos: …` → as 14 propostas, cada uma com os buracos que deixa nas duas lojas, calculados com a escala real (ex.: «Débora 06/10: Alfragide 10h–16h30 + Oeiras 16h30–22h · ficam buracos: Oeiras 13h–16h30»). Nenhuma regra simples serve os 14 dias: às terças a divisão deixa Oeiras sem ninguém das 13h às 16h30 (e Alfragide com duas pessoas das 14h às 16h30, porque a Emily entra às 14h); a 21 e a 29/10 e a 10/12 o buraco que fica é o da noite em Alfragide. Mostrar-lhe as linhas uma a uma e perguntar se grava assim e acerta depois na app (tocar na ida → mudar as horas → Guardar — por exemplo, às terças, Alfragide 10h–14h e Oeiras 14h–22h), ou se prefere outra divisão antes de gravar. Uma divisão diferente para todos os dias muda a regra do `planear` (com teste primeiro, Tarefa 14) — não se edita à mão em produção.
- As linhas por pessoa e o `Total: N idas a gravar.` (96 se nada ficar de fora).

**Pedir o «sim» explícito do dono para gravar, com o total à vista. Sem «sim», parar aqui.**

- [ ] **Passo 3: Gravar (o dono corre)**

```bash
ssh root@187.124.4.163 "cd ~/RH && docker compose exec -T -e GRAVAR=1 backend python -" < backend/carregar_idas_whatsapp.py
```

Esperado: `Gravadas N idas.` com o N do ensaio.

- [ ] **Passo 4: Conferir**

1. O dono volta a correr o ensaio do Passo 1 → `Total: 0 idas a gravar.` e cada ida em «já estava gravada» (o script é repetível e não duplica).
2. Na app: Contagem de 2026 com a Débora, a Carol, o Matheus e o Bruce; outubro com as terças de Oeiras e a Amadora de 22, 23 e 25/10 tapadas; os dias divididos com as duas idas.
3. Registar na memória do projecto (`calendario-gestao.md`) o que ficou no ar, o commit do merge e o total de idas gravadas.

---

## Auto-revisão

### Cobertura do desenho

| Requisito (desenho) | Tarefa |
|---|---|
| §1 Idas: colecção `bolso_idas` e os seus campos; `data` como `date` gravada com `isoformat()`; HH:MM e `inicio` < `fim` | 5 (`validar_horas`), 7 (`BolsoIdasIn`/`BolsoIdaIn`, `bolso_criar_idas`) |
| §1 Idas: só em lojas com horário e abertas nesse dia (400); horas a tocar no horário (400); recorte no cálculo e na contagem | 5 (`validar_ida`), 3 (recorte no dia), 4 (recorte na contagem), 7 (400 nas rotas) |
| §1 Idas: a mesma pessoa sem horas sobrepostas no mesmo dia (409 a dizer qual); colaborador com ausência aprovada (409) | 5 (`choques`, `mensagem_de_choque`, `ausencias_que_impedem`), 7 |
| §1 Idas: qualquer pessoa admin/gerente/colaborador; o contabilista não; cruzamento por `users.employee_id` | 5 (`pessoas_escalaveis`), 3 (`_preparar.user_do_emp`), 7 (400) |
| §1 Idas: índice único `(data, user_id, location_id, inicio)` e índice em `data` | 6 (`_bolso_criar_indices` + `startup_event`), 15 (passo 4: provado no arranque) |
| §2.1 Estado da loja: `por_abrir`, `fechada`, `aberta` com a excepção do dia; só lojas com horário | 1 (`horario_do_dia`), 2 (as por abrir e sem horário não aparecem) |
| §2.2 Escala a partir de `employees`; regra do `find_schedule_assignment`; `work_days` com recurso; `dias` com loja/horas; entrada em loja fechada ignorada; recorte | 2 |
| §2.3 Sai quem tem ausência aprovada (qualquer tipo) | 2 (`ausentes`); 3 (a ida de quem ficou de férias depois de marcada não tapa — decisão por omissão, confirmada com o dono na 16, Passo 2) |
| §2.4 Idas de gestor somam-se; de colaborador tiram à escala as horas da ida; «extra» (com as horas já recortadas ao horário) | 3 |
| §2.5 Buracos = horário menos a união; «ninguém» = abre–fecha; não se guardam | 2 (`_loja_do_dia`), 6 (calculados a cada pedido) |
| §2 Feriados do dia (nacionais com nome + grupo) e da loja (empresa/loja, regra «OU»); dia impossível salta; `get_pt_holidays` e a cache intactos | 1 |
| §2 Contagem 0,5/1 pela metade, só horas dentro do horário, loja sem horário vale 1, corte em 1, 12 meses + total, futuras incluídas | 4, 6 (rota) |
| §3 Rotas `GET` mês e contagem (`admin_manager_required`); `POST`/`PUT`/`DELETE` (admin/gerente, 403 aos outros) | 6, 7 |
| §3 POST tudo ou nada sem transacções, compensação, `ponytail:` da janela; validações e repetidos → 400; uma consulta para a sobreposição; o PUT exclui-se a si | 7 |
| §3 Forma do GET do mês (`eu`, `pode_marcar`, `dias`, `idas` com nomes, `ausencias` aprovadas, `lojas`, `pessoas` ordenadas); recursos «(conta removida)»/«(loja removida)» | 5 (`resposta_do_mes`), 6 |
| §3 Níveis de conta (rotas novas na gaveta do `bolso`) | 16 (passo 3) |
| §4 Menu lateral ☰ (`Sheet side="left"`): Faturação, Calendário, Terminar sessão; fecho de 44 px; `SheetContent` sem o fecho de 16 px por opção; `safe-area-inset-top`; `partilhado.js` com `useManifestoDoBolso`, `Segmento`, `ler`/`guardar`; `BarraDeAmbito` só na Faturação | 11 |
| §4 Rota `/bolso/calendario` com os mesmos papéis | 13 |
| §4 Mês com grelha própria (`semanasDoMes`, 44 px, feriados noutra cor, abre no dia de hoje); Geral com ponto vermelho, lojas com pessoas e «escala»/«extra», buracos vermelho/amarelo com Tapar, fechadas a cinzento; Pessoal; Férias | 9, 11 (`GrelhaDoMes`), 13 |
| §4 Lista (a partir de hoje no mês corrente, só dias com alguma coisa) e Contagem (mês e ano, tocar abre os meses) | 9 (`lista`, `linhaDaContagem`), 13 |
| §4 Filtros em baixo e vista lembrados no `localStorage` com try/catch; sem ele Mês/Geral | 11 (`ler`/`guardar`), 13 |
| §4 Painel de tapar/marcar/editar/apagar: pessoas (uma ou mais, gestores primeiro, começa em mim), horas do buraco, dias com o atalho «outras terças … que contém as horas»; Tapar/Marcar só com `pode_marcar` | 9 (`outrosDiasComBuraco`, `textoDoAtalho`, `pessoasIniciais`), 12, 13 |
| §4 «+ Marcar ida abre o mesmo painel vazio, com a loja a escolher» (as horas vêm da loja escolhida) | 12 (`escolherLoja`), 13 (`marcar`) |
| §4/§5 sessão expirada: o 401 sai para o login, também dentro do painel (não aparece como erro do formulário) | 12 (`onSemSessao`), 13 (`semSessao`) |
| §4 «Hoje» local, nunca `toISOString()` | 9 |
| §4 Pedidos por `lib/bolso.js` com caminhos por extenso, confrontados com o router | 10 |
| §4 Erros dizem o que aconteceu e o que fazer | 5 (textos), 7 (linha do «o que fazer»), 12 (mostrados tal como vêm) |
| Testes 1 (semana normal, 26/10–01/11, grelha exacta) | 2 |
| Testes 2 (Outubro: férias do Weber, Joana em Benfica, 2 horas, extra; 409 de férias) | 3, 5, 7 |
| Testes 5 (feriados) | 1 |
| Testes 6 (contagem) | 4 |
| Testes 7 (marcar, sobreposição na última data, PUT, 400s, mudar/apagar) | 7 |
| Testes 8 (porta, contra mongod real) | 6, 7 |
| Testes 9 (caminho) | 10 |
| Testes 11 (cada teste visto vermelho) | todas (passo «Prova por mutação», com `tests/mutar.py`) |
| Testes 12 (375 px, claro e escuro, notch, servidor local com a semana normal); contraste ≥ 4,5:1 do vermelho e do amarelo nos dois temas | 15; classes presas nos testes da 12 (erro e «Apagar») e da 13 (selo «ninguém» em pastilha cheia) |
| Testes 14 (depois do deploy: ficheiro servido e caminho feliz) | 16 |
| Entrega: carregar as idas de out–dez da mensagem, com confirmação do dono | 14 (lojas só entre as que têm horário — as duas «Loja Alfragide» de produção; `PROCURAR_JSON`; o ensaio mostra os buracos que cada divisão deixa), 17 |
| Fora de âmbito respeitado: sem fecho por data, sem pendentes a abrir buracos, sem férias de gestores, sem avisos, sem mexer no «Em falta» nem nas 24 h; Face ID e as duas correcções da sessão ficam para a Fase 3 | — |

### Nomes consistentes (definido → usado)

- `calendario.py`: `minutos`, `hhmm`, `hora_curta`, `data_curta`, `primeiro_nome`, `unir`, `subtrair`, `recortar`, `horario_do_dia`, `feriados_nacionais`, `feriados_do_dia`, `feriados_da_loja` (T1) → T2-T5, T14; `atribuicao_do_dia`, `ausentes`, `_preparar`, `_escala`, `_pessoa`, `_loja_do_dia`, `dia_do_calendario`, `calendario_do_mes` (T2/T3) → T5; `valor_da_ida`, `contagem` (T4) → T6, T13; `AUSENCIAS`, `limites_do_mes`, `validar_pedido`, `validar_horas`, `validar_ida`, `choques`, `mensagem_de_choque`, `ausencias_que_impedem`, `pessoas_escalaveis`, `resposta_do_mes` (T5) → T6, T7, T9, T12, T13, T14; `GESTORES`, `ESCALAVEIS`, `NOME_SEM_CONTA`, `NOME_SEM_LOJA` (T1) → T3-T7.
- `server.py`: `_BOLSO_CAMPOS_DA_LOJA`, `_bolso_criar_indices`, `bolso_calendario`, `bolso_calendario_contagem` (T6) → T7, T15; `BolsoIdasIn`, `BolsoIdaIn`, `bolso_quem_marca`, `_bolso_validar_idas`, `bolso_criar_idas`, `bolso_mudar_ida`, `bolso_apagar_ida` (T7).
- `tests/calendario/dados_semana_normal.py`: `semana_normal`, `ida`, `ausencia`, `emp`, `user`, `gravar`, `LOJAS`, `COLECOES` e as constantes (T1) → T2-T15 (o seed do ensaio também).
- `tests/bolso_js.py`: `correr_js`, `AXIOS_FABRICADO`, `SESSAO_SIMULADA`, `SRC` (T8) → T9-T13; no guião `importar`, `devolve`, `REGISTO`, `montar`, `esperar`, `clicar`, `escrever`, `botao`, `texto`, `pararRelogio`.
- `@/lib/bolso`: `getCalendario`, `getContagem`, `criarIdas`, `mudarIda`, `apagarIda` (T10) → T12, T13.
- `@/lib/calendario` (T9) → T11 (`semanasDoMes`, `tituloDoDia`), T12, T13 — os nomes da lista de «Interfaces» da T9 são os mesmos dos `import` da T12 e da T13.
- `pages/bolso/partilhado.js`: `ler`, `guardar`, `useManifestoDoBolso`, `Calha`, `Segmento`, `DESTINOS`, `BotaoMenu`, `MenuLateral`, `GrelhaDoMes` (T11) → T12, T13, BolsoApp.
- `PainelIda` (default, T12; props `painel`, `dados`, `hoje`, `onFechar`, `onGuardado`, `onSemSessao`) → T13 (passa `onSemSessao={semSessao}`). `BolsoCalendario` (default, T13) → `App.js`.
- `carregar_idas_whatsapp`: `IDAS`, `OPCIONAL`, `CRIADO_POR`, `planear(…, procurar=None)` (devolve `gravar`, `divididas`, `divididas_em`, `saltadas`), `_buracos_que_ficam`, `executar` e a variável `PROCURAR_JSON` (T14) → T17.
- Da Fase 1, só consumidos: `tests/calendario/conftest.py` (`mongod_porta`, `base`), `tests/calendario/apoio.py` (`corre`), `arranque_calendario` (`HORARIOS`, `Paragem`, `_normal`, `_um`).
