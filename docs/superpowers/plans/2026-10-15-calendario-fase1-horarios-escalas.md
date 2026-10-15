# Calendário das lojas, Fase 1: horários e escalas — Plano de execução

> **Para agentes:** SUB-SKILL OBRIGATÓRIO: usar superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para executar este plano tarefa a tarefa. Os passos usam caixas (- [ ]).

**Objetivo:** Os Locais passam a guardar o horário de cada loja e as Escalas passam a dizer, por dia, a loja e as horas de cada pessoa — sem mudar o que o saldo de férias, o «Em falta» e o lembrete do ponto já lêem —, e as 6 lojas e as 7 escalas da semana normal ficam carregadas em produção por um script que o dono corre.

**Arquitectura:** Dois campos novos em `locations` (`horario`, `aberta_desde`) e um em `work_schedule_templates` (`dias`), validados por modelos Pydantic no `backend/server.py`; os dois `PUT` só os escrevem se vierem no corpo (`model_fields_set`), e o `work_days` das escalas passa a ser derivado de `dias`. Os formulários do portal (`AdminLocations.js`, `AdminSchedules.js`) usam um módulo puro novo, `frontend/src/lib/horarios.js`, para passar entre o que o servidor guarda e o que o ecrã mostra. O arranque de produção é um script só com pymongo (`backend/arranque_calendario.py`), em ensaio por omissão, que o dono corre.

**Tecnologia:** FastAPI + Motor + Pydantic 2 (Python 3.9.6 nos testes locais, 3.11 em produção), pytest contra um `mongod` real, React 19 (CRA/craco) + Tailwind + shadcn, Node + `@babel/core` nos testes de JavaScript (corridos pelo pytest), pymongo no script.

## Restrições globais

- Fonte de verdade: `docs/superpowers/specs/2026-10-14-calendario-gestao-design.md` (secções «1. Os dados», «Entrega por fases» e «Testes» 3, 4, 11, 12 e 14). Não mudar decisões do dono.
- Trabalhar só em `/Users/matheus.moraes/Developer/RH-calendario` (ramo `matheus-calendario-gestao`). Nunca tocar em `~/Developer/RH` (outra sessão) nem em `~/Developer/RH-qr-aplicacoes` (é lá que o `main` está aberto). Excepção aceite, só de cache: o `craco` (Tarefas 8 e 9) grava a cache do webpack em `frontend/node_modules/.cache`, que pelo atalho fica em `~/Developer/RH/frontend/node_modules/.cache` (gitignored; ver a Tarefa 8, Passo 3).
- Dias da semana: `0 = segunda … 6 = domingo`, como `work_days`.
- `horario` = `{"abre": "HH:MM", "fecha": "HH:MM", "excecoes": [{"dia": 6, "abre": "11:30", "fecha": "20:00"}], "fechada": [1]}`; `aberta_desde` = `"AAAA-MM-DD"` ou `null` (opcional).
- Validação do horário: `abre` < `fecha` (HH:MM); dias de 0 a 6 sem repetidos; um dia não pode estar em `excecoes` e em `fechada`.
- `dias` da escala = `[{"dia": 0, "location_id": "…", "inicio": null, "fim": null}]`; `location_id` vazio = a loja da ficha do colaborador; `inicio`/`fim` vazios = o horário da loja nesse dia; as duas horas vêm juntas ou nenhuma, e `inicio` < `fim`.
- Quando há `dias`, o servidor deriva `work_days` deles (os `dia`, ordenados), no `POST` e no `PUT`, calcula-o UMA vez e usa o mesmo valor no modelo e na cópia das atribuições.
- O `PUT /locations/{id}` e o `PUT /schedules/{id}` só escrevem `horario`/`aberta_desde`/`dias` se vierem no corpo (`model_fields_set`): um browser com a página antiga em cache manda o formulário sem eles.
- O formulário novo carrega os campos novos ao abrir e manda-os sempre; o das Escalas continua a mandar `workDays` (obrigatório), igual aos dias de `dias`.
- O campo «Hora de início» (`start_time`) fica como está: é o que o lembrete do ponto lê, e a app do ponto tem o código congelado.
- Escalas antigas, sem `dias`, continuam a valer (loja da ficha e horário da loja); um dia de `work_days` sem entrada em `dias` também.
- Horários que passam da meia-noite: fora de âmbito.
- Python dos testes: `~/Developer/RH/backend/.venv/bin/python` (3.9.6) — nada de `X | Y` em anotações nem `match`.
- Testes sempre com `PYTHONDONTWRITEBYTECODE=1`; depois de repor uma mutação, `rm -rf ~/Library/Caches/com.apple.python` antes de voltar a correr (bytecode envenenado neste Mac).
- Ler SEMPRE `passed` E `skipped`. `frontend/node_modules` tem de ser o atalho para `~/Developer/RH/frontend/node_modules` (sem ele saltam ~259 testes de ecrã em silêncio).
- Um teste só vale depois de visto vermelho pela razão certa: cada tarefa tem a sua prova por mutação.
- Produção: o assistente não lê nem escreve a base de produção. Push, merge no `main` e deploy só depois de um «sim» do dono no chat. Os dados de produção mudam-se só pelo script, corrido pelo dono.
- Valores de teste locais (palavras-passe e segredos do `backend.env` de ensaio) nunca se escrevem no chat nem em ficheiros versionados.
- Commits: `git add` de ficheiros nomeados; mensagem em português que diz o porquê, terminada com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

## Mapa de ficheiros

| Ficheiro | Criar/Modificar | Responsabilidade |
|---|---|---|
| `backend/server.py` | Modificar | `_hora`, `_dia_da_semana`, `_Horas`, `HorarioDoDia`, `HorarioLoja` e os campos novos de `LocationCreate`/`LocationResponse` (~486-507); `DiaDaEscala` e `dias` em `WorkScheduleTemplateCreate`/`WorkScheduleTemplateResponse` (~634-667); `_horario_para_gravar` + `POST`/`PUT /locations` (~1452-1507); `_dias_de_trabalho`, `_dias_para_gravar` + `POST`/`PUT /schedules` (~2112-2249) |
| `backend/tests/calendario/__init__.py` | Criar | pacote dos testes do calendário (vazio) |
| `backend/tests/calendario/conftest.py` | Criar | ambiente antes do `import server`; `mongod_porta` (um mongod por sessão) e `base` (Motor limpo no lugar de `server.db`) |
| `backend/tests/calendario/apoio.py` | Criar | `corre(coro)` e `ADMIN` |
| `backend/tests/calendario/test_horario_das_lojas.py` | Criar | validação do horário (puro) e `POST`/`GET`/`PUT` dos Locais contra o mongod |
| `backend/tests/calendario/test_escalas_com_dias.py` | Criar | validação de `dias` (puro) e `POST`/`PUT`/`GET` das Escalas, `/me/schedule` e saldo de férias contra o mongod |
| `frontend/src/lib/horarios.js` | Criar | funções puras formulário ↔ servidor e os resumos das tabelas |
| `backend/tests/calendario/test_formularios_do_portal.py` | Criar | corre `lib/horarios.js` em Node; guardas de que os dois ecrãs o usam e compilam |
| `frontend/src/pages/admin/AdminLocations.js` | Modificar | secção «Horário da loja» no diálogo, coluna «Horário» na tabela, erros 422 legíveis |
| `frontend/src/pages/admin/AdminSchedules.js` | Modificar | «Loja e horas de cada dia» no formulário, resumo na tabela, erros 422 legíveis |
| `backend/arranque_calendario.py` | Criar | script de arranque de produção (pymongo), ensaio por omissão, `GRAVAR=1` para gravar |
| `backend/tests/calendario/test_arranque_do_calendario.py` | Criar | o script contra um mongod com a forma da produção |
| Só locais, nunca versionados | — | `frontend/node_modules` (atalho), `frontend/.env.development.local`, `$HOME/.cache/lisbonb-calendario-local/` (`backend.env`, `semear.py`, `mongo/`, `build/`, `cache/`), as entradas `calendario-*` em `/Users/matheus.moraes/Library/CloudStorage/OneDrive-Pessoal/Claude/.claude/launch.json` |

## Contexto que quem executa precisa de ter

- **O negócio.** Seis lojas de açaí com escala fixa. Quando falta alguém, vão as gestoras (Carol e Débora). A Fase 2 vai calcular sozinha os buracos de cada loja a partir de três coisas: o horário da loja, a escala de cada pessoa e as férias aprovadas. Esta Fase 1 só põe as duas primeiras no portal e carrega-as.
- **`work_days` tem três leitores sem testes** (desenho, «medido 2»): o saldo de férias (`calculate_leave_counted_days`, `server.py:839-889`, que lê a CÓPIA `work_days` guardada em cada atribuição), o «Em falta» do painel (`_schedule_today`, ~2927) e o lembrete do ponto (`GET /me/schedule`, ~2130, que lê também `start_time`). É por isso que `work_days` tem de continuar a querer dizer «os dias em que trabalha».
- **O `PUT` de hoje substitui tudo o que vem no corpo** (`server.py:1489-1503` e `:2235-2247`). Um browser com a página antiga em cache manda o formulário sem os campos novos; sem a guarda `model_fields_set`, o horário e os `dias` ficavam a `null`.
- **A página Escalas não sabe fechar uma atribuição** (só criar e apagar), e o servidor recusa atribuições sobrepostas (`:2188-2196`). É por isso que o script de arranque fecha as atribuições antigas directamente na base (`end_date` na véspera) em vez de pedir ao dono que o faça no ecrã.
- **Erros 422 do FastAPI** trazem `detail` como lista de objectos; pô-la directamente num `toast` desmonta a página. Já existe o tradutor `detalhesErro(error, fallback)` em `frontend/src/lib/faturacao.js:64` (e `pages/admin/Resumo.js` já importa dessa lib) — usa-se esse.
- **Rotas do portal:** `/admin/locais` (`AdminLocations.js`) e `/admin/escalas` (`AdminSchedules.js`), `frontend/src/App.js:231` e `:244`.

---

### Tarefa 1: Horário da loja — modelos e validação

**Ficheiros:**
- Criar: `backend/tests/calendario/__init__.py` (vazio), `backend/tests/calendario/conftest.py`
- Modificar: `backend/server.py:10` (import do Pydantic) e `backend/server.py:486-507` (antes de `class LocationCreate`, e as classes `LocationCreate`/`LocationResponse`)
- Testes: `backend/tests/calendario/test_horario_das_lojas.py`

**Interfaces:**
- Consome: nada.
- Produz:
  - `server._hora(v) -> str` (aceita `"HH:MM"` 00:00–23:59, senão `ValueError("Hora inválida. Use o formato HH:MM")`)
  - `server._dia_da_semana(v) -> int` (0..6, senão `ValueError("Dia inválido: use 0 (segunda) a 6 (domingo)")`)
  - `server.HorarioDoDia` — campos `abre: str`, `fecha: str`, `dia: int`
  - `server.HorarioLoja` — campos `abre: str`, `fecha: str`, `excecoes: List[HorarioDoDia] = []`, `fechada: List[int] = []` (devolvida ordenada)
  - `server.LocationCreate.horario: Optional[HorarioLoja] = None`, `server.LocationCreate.aberta_desde: Optional[date] = None` (`""` → `None`)
  - `server.LocationResponse.horario: Optional[dict] = None`, `server.LocationResponse.aberta_desde: Optional[str] = None`

- [ ] **Passo 1: Preparar a árvore e medir a suite de partida**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git status -s -b      # esperado: "## matheus-calendario-gestao"; no máximo os planos de docs/superpowers/plans/ por guardar
ln -sfn ~/Developer/RH/frontend/node_modules frontend/node_modules
git status -s         # igual ao de cima (frontend/.gitignore tem /node_modules)
export PATH="$HOME/.local/node/bin:$PATH"
cd backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest -q 2>&1 | tail -3
```

Anotar `N passed, M skipped` — é a partida. Até ao fim do plano o `passed` só sobe e o `skipped` não cresce.

- [ ] **Passo 2: Criar o pacote dos testes com o ambiente**

`backend/tests/calendario/__init__.py`: ficheiro vazio.

`backend/tests/calendario/conftest.py`:

```python
"""Testes do calendário das lojas.

As variáveis de ambiente têm de existir ANTES de qualquer `import server`: o pytest
colecciona `tests/calendario` antes de `tests/crm` e `tests/faturacao`, cujos conftest
as definem (ler o docstring de tests/crm/conftest.py). Os valores são exactamente os
mesmos, e `setdefault` nunca sobrepõe um valor que já lá esteja.
"""
import os

os.environ.setdefault("POS_JWT_SECRET", "segredo-de-teste-pos")
os.environ.setdefault("JWT_SECRET", "segredo-de-teste")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")
```

- [ ] **Passo 3: Escrever os testes que falham**

`backend/tests/calendario/test_horario_das_lojas.py`:

```python
"""O horário das lojas nos Locais.

Só as lojas com `horario` vão entrar no calendário (a Pizzaria e os escritórios ficam
de fora sem ninguém os esconder); `aberta_desde` esconde uma loja antes de abrir. Aqui
prende-se o que o servidor aceita e recusa; mais abaixo (Tarefa 2), o que fica gravado.
"""
from datetime import date

import pytest
from pydantic import ValidationError

import server

# Belém: 11h30–19h, ao domingo até às 20h, fechada à terça (a tabela do dono).
BELEM = {
    "abre": "11:30", "fecha": "19:00",
    "excecoes": [{"dia": 6, "abre": "11:30", "fecha": "20:00"}],
    "fechada": [1],
}


def _loja(**extra):
    corpo = {"name": "L'Açaí Belém", "company_id": "c1"}
    corpo.update(extra)
    return server.LocationCreate.model_validate(corpo)


def test_o_horario_de_belem_passa_e_fica_igual():
    assert server.HorarioLoja.model_validate(BELEM).model_dump() == BELEM


def test_os_dias_fechados_ficam_por_ordem():
    horario = server.HorarioLoja.model_validate({**BELEM, "excecoes": [], "fechada": [3, 1]})
    assert horario.fechada == [1, 3]


@pytest.mark.parametrize("mudanca, mensagem", [
    ({"abre": "19:00", "fecha": "11:30"}, "abrir antes de fechar"),
    ({"abre": "11:30", "fecha": "11:30"}, "abrir antes de fechar"),
    ({"abre": "9:00"}, "HH:MM"),
    ({"fecha": "24:00"}, "HH:MM"),
    ({"excecoes": [{"dia": 7, "abre": "11:30", "fecha": "20:00"}]}, "Dia inválido"),
    ({"excecoes": [{"dia": 6, "abre": "20:00", "fecha": "11:30"}]}, "abrir antes de fechar"),
    ({"excecoes": [{"dia": 6, "abre": "11:30", "fecha": "20:00"},
                   {"dia": 6, "abre": "12:00", "fecha": "20:00"}]}, "repetido nas exceções"),
    ({"fechada": [1, 1]}, "repetido nos dias em que fecha"),
    ({"fechada": [-1]}, "Dia inválido"),
    ({"fechada": [6]}, "outro horário e estar fechado"),
])
def test_horarios_que_o_servidor_recusa(mudanca, mensagem):
    with pytest.raises(ValidationError, match=mensagem):
        server.HorarioLoja.model_validate({**BELEM, **mudanca})


def test_a_data_de_abertura():
    assert _loja(aberta_desde="2026-10-24").aberta_desde == date(2026, 10, 24)
    assert _loja(aberta_desde="").aberta_desde is None      # o <input type="date"> vazio
    assert _loja(aberta_desde=None).aberta_desde is None
    with pytest.raises(ValidationError):
        _loja(aberta_desde="2026-02-30")


def test_a_pagina_antiga_nao_manda_os_campos_novos_e_o_servidor_sabe_disso():
    velha = _loja(address="Rua X")
    assert velha.horario is None and velha.aberta_desde is None
    assert not {"horario", "aberta_desde"} & velha.model_fields_set
    nova = _loja(horario=None, aberta_desde=None)
    assert {"horario", "aberta_desde"} <= nova.model_fields_set


def test_um_horario_invalido_nem_chega_a_rota():
    with pytest.raises(ValidationError, match="abrir antes de fechar"):
        _loja(horario={**BELEM, "fecha": "10:00"})
```

- [ ] **Passo 4: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_horario_das_lojas.py -q
```

Esperado: todos vermelhos, com `AttributeError: module 'server' has no attribute 'HorarioLoja'` e, nos de `_loja`, `AttributeError: 'LocationCreate' object has no attribute 'aberta_desde'` (o Pydantic ignora os campos que não conhece).

- [ ] **Passo 5: Implementação mínima**

Em `backend/server.py:10`, trocar

```python
from pydantic import BaseModel, Field, EmailStr, field_validator
```

por

```python
from pydantic import BaseModel, Field, EmailStr, field_validator, model_validator
```

Imediatamente antes de `class LocationCreate(BaseModel):` (~486), acrescentar:

```python
# ---- Calendário das lojas: horário de cada loja (desenho 2026-10-14, «1. Os dados») ----
# Dias: 0 = segunda … 6 = domingo, como o `work_days` das escalas.
_RE_HORA = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')


def _hora(v):
    if not isinstance(v, str) or not _RE_HORA.match(v):
        raise ValueError("Hora inválida. Use o formato HH:MM")
    return v


def _dia_da_semana(v):
    if v not in range(0, 7):
        raise ValueError("Dia inválido: use 0 (segunda) a 6 (domingo)")
    return v


class _Horas(BaseModel):
    abre: str
    fecha: str

    @field_validator('abre', 'fecha')
    @classmethod
    def _valida_hora(cls, v):
        return _hora(v)

    @model_validator(mode='after')
    def _abre_antes_de_fechar(self):
        # "HH:MM" com zeros à esquerda compara-se como texto. Horários que passam da
        # meia-noite ficam de fora de propósito (desenho, «Fora de âmbito»).
        if self.abre >= self.fecha:
            raise ValueError(f"A loja tem de abrir antes de fechar ({self.abre}–{self.fecha})")
        return self


class HorarioDoDia(_Horas):
    """Uma exceção ao horário geral (ex.: o domingo de Belém, até às 20h)."""
    dia: int

    @field_validator('dia')
    @classmethod
    def _valida_dia(cls, v):
        return _dia_da_semana(v)


class HorarioLoja(_Horas):
    """O horário de uma loja: o geral, as exceções por dia e os dias em que fecha."""
    excecoes: List[HorarioDoDia] = []
    fechada: List[int] = []

    @field_validator('fechada')
    @classmethod
    def _valida_fechada(cls, v):
        for dia in v:
            _dia_da_semana(dia)
        if len(set(v)) != len(v):
            raise ValueError("Dia repetido nos dias em que fecha")
        return sorted(v)

    @model_validator(mode='after')
    def _dias_sem_choques(self):
        dias = [e.dia for e in self.excecoes]
        if len(set(dias)) != len(dias):
            raise ValueError("Dia repetido nas exceções")
        if set(dias) & set(self.fechada):
            raise ValueError("Um dia não pode ter outro horário e estar fechado")
        return self

```

Em `class LocationCreate`, depois de `google_place_id: Optional[str] = None`, acrescentar:

```python
    # Calendário das lojas: só as lojas com horário entram no calendário;
    # `aberta_desde` esconde uma loja antes de abrir.
    horario: Optional[HorarioLoja] = None
    aberta_desde: Optional[date] = None

    @field_validator('aberta_desde', mode='before')
    @classmethod
    def _aberta_desde_vazia(cls, v):
        return None if v == "" else v
```

Em `class LocationResponse`, depois de `google_place_id: Optional[str] = None`, acrescentar:

```python
    # dict/str e não os modelos: a lista de Locais alimenta o portal inteiro, e um
    # documento estranho na base não a pode deitar abaixo com um 500.
    horario: Optional[dict] = None
    aberta_desde: Optional[str] = None
```

- [ ] **Passo 6: Correr e ver passar**

O mesmo comando do Passo 4. Esperado: `15 passed`.

- [ ] **Passo 7: Prova por mutação**

1. Em `HorarioLoja._dias_sem_choques`, trocar `if set(dias) & set(self.fechada):` por `if False:`. Correr o Passo 4: esperado **1 failed** — o último caso de `test_horarios_que_o_servidor_recusa` (`fechada: [6]`, «DID NOT RAISE»). Repor.
2. Em `_Horas._abre_antes_de_fechar`, trocar `>=` por `>`. Esperado **1 failed** — o caso `11:30–11:30`. Repor.
3. Em `_aberta_desde_vazia`, trocar `return None if v == "" else v` por `return v`. Esperado **1 failed** — `test_a_data_de_abertura`. Repor.

Depois de repor: `rm -rf ~/Library/Caches/com.apple.python`, correr outra vez (verde) e `git diff backend/server.py` só com as mudanças do Passo 5.

- [ ] **Passo 8: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add backend/server.py backend/tests/calendario/__init__.py backend/tests/calendario/conftest.py backend/tests/calendario/test_horario_das_lojas.py
git commit -m "$(cat <<'EOF'
Locais: o horário da loja e a data de abertura passam a existir nos modelos

O calendário automático das lojas precisa de saber quando cada loja abre e fecha
(geral, exceções por dia, dias fechados) e, para Benfica, desde quando abre. Os
modelos validam o que o desenho pede: HH:MM, abrir antes de fechar, dias 0-6 sem
repetidos e nenhum dia com exceção e fechado ao mesmo tempo. A resposta devolve
dict/str para que um documento estranho não deite abaixo a lista de Locais.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Tarefa 2: Locais — o POST e o PUT gravam o horário, e a página antiga não o apaga

**Ficheiros:**
- Criar: `backend/tests/calendario/apoio.py`
- Modificar: `backend/tests/calendario/conftest.py` (acrescentar o mongod); `backend/server.py:1452-1507` (`create_location`, `update_location` e um ajudante antes delas)
- Testes: `backend/tests/calendario/test_horario_das_lojas.py` (acrescentar no fim)

**Interfaces:**
- Consome: `server.LocationCreate.horario`, `server.LocationCreate.aberta_desde` (Tarefa 1).
- Produz:
  - `server._horario_para_gravar(location: LocationCreate) -> dict` — `{"horario": dict | None, "aberta_desde": "AAAA-MM-DD" | None}`
  - fixtures `mongod_porta` (sessão, `int`) e `base` (função, `AsyncIOMotorDatabase` limpa, posta em `server.db`) em `tests/calendario/conftest.py`
  - `tests/calendario/apoio.py`: `corre(coro)` e `ADMIN: dict`

- [ ] **Passo 1: O apoio e o mongod dos testes**

`backend/tests/calendario/apoio.py`:

```python
"""Ajudantes dos testes do calendário (importar com `from .apoio import ...`)."""
import asyncio

# As rotas testam-se chamando as funções directamente; quem pede é um administrador.
ADMIN = {"user_id": "u-admin", "role": "admin", "email": "admin@example.com", "employee_id": None}


def corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)
```

Substituir `backend/tests/calendario/conftest.py` inteiro por:

```python
"""Testes do calendário das lojas.

1. As variáveis de ambiente têm de existir ANTES de qualquer `import server`: o pytest
   colecciona `tests/calendario` antes de `tests/crm` e `tests/faturacao`, cujos
   conftest as definem (ler o docstring de tests/crm/conftest.py). Os valores são
   exactamente os mesmos, e `setdefault` nunca sobrepõe um valor que já lá esteja.
2. `mongod_porta` arranca UM mongod para a sessão inteira, numa porta livre e numa
   pasta temporária (molde: `mongo_real` em tests/test_seguranca_login.py). Aqui
   mede-se o que fica GRAVADO — o que um `$set` apaga não se vê num duplo.
"""
import os
import shutil
import socket
import subprocess
import tempfile
import time

import pytest

os.environ.setdefault("POS_JWT_SECRET", "segredo-de-teste-pos")
os.environ.setdefault("JWT_SECRET", "segredo-de-teste")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

import server  # noqa: E402

from .apoio import corre  # noqa: E402

BASE_DE_TESTE = "teste_calendario"


@pytest.fixture(scope="session")
def mongod_porta():
    mongod = shutil.which("mongod") or "/opt/homebrew/bin/mongod"
    if not os.path.exists(mongod):
        pytest.skip("sem mongod nesta máquina: os Locais, as Escalas e o arranque NÃO foram testados contra uma base")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    pasta = tempfile.mkdtemp(prefix="mongod-calendario-")
    proc = subprocess.Popen(
        [mongod, "--dbpath", pasta, "--port", str(porta), "--bind_ip", "127.0.0.1", "--quiet"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", porta), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        proc.terminate()
        pytest.fail("o mongod dos testes não arrancou em 10 s")
    yield porta
    proc.terminate()
    proc.wait(10)
    shutil.rmtree(pasta, ignore_errors=True)


@pytest.fixture
def base(mongod_porta, monkeypatch):
    """Uma base limpa no mongod da sessão, posta no lugar do `server.db`."""
    cliente = AsyncIOMotorClient(f"mongodb://127.0.0.1:{mongod_porta}")
    corre(cliente.drop_database(BASE_DE_TESTE))
    db = cliente[BASE_DE_TESTE]
    monkeypatch.setattr(server, "db", db)
    yield db
    cliente.close()
```

- [ ] **Passo 2: Escrever os testes que falham**

No topo de `backend/tests/calendario/test_horario_das_lojas.py`, debaixo de `import server`, acrescentar:

```python
from .apoio import ADMIN, corre
```

No fim do ficheiro, acrescentar:

```python
# ---- Tarefa 2: o que fica gravado (contra um mongod real, ver conftest) ----

ALFRAGIDE = {"abre": "10:00", "fecha": "23:00", "excecoes": [], "fechada": []}


@pytest.fixture
def empresa(base):
    corre(base.companies.insert_one({"id": "c1", "name": "L'Açaí", "created_at": "2026-01-01T00:00:00+00:00"}))
    return base


def _gravada(base, location_id):
    return corre(base.locations.find_one({"id": location_id}, {"_id": 0}))


def test_o_post_grava_o_horario_e_a_data_de_abertura_e_o_get_devolve_os(empresa):
    criada = corre(server.create_location(_loja(horario=BELEM, aberta_desde="2026-10-24"), current_user=ADMIN))
    assert criada.horario == BELEM and criada.aberta_desde == "2026-10-24"
    gravada = _gravada(empresa, criada.id)
    assert gravada["horario"] == BELEM and gravada["aberta_desde"] == "2026-10-24"
    [lida] = corre(server.get_locations(current_user=ADMIN))
    assert lida.horario == BELEM and lida.aberta_desde == "2026-10-24"


def test_um_put_da_pagina_antiga_nao_apaga_o_horario(empresa):
    criada = corre(server.create_location(_loja(horario=BELEM, aberta_desde="2026-10-24"), current_user=ADMIN))
    # A página antiga, em cache no browser, manda o formulário SEM os campos novos.
    corre(server.update_location(criada.id, _loja(name="L'Açaí Belém (renomeada)", address="Rua Nova"),
                                 current_user=ADMIN))
    gravada = _gravada(empresa, criada.id)
    assert gravada["name"] == "L'Açaí Belém (renomeada)" and gravada["address"] == "Rua Nova"
    assert gravada["horario"] == BELEM and gravada["aberta_desde"] == "2026-10-24"


def test_o_formulario_novo_muda_e_tambem_tira_o_horario(empresa):
    criada = corre(server.create_location(_loja(horario=BELEM, aberta_desde="2026-10-24"), current_user=ADMIN))
    devolvida = corre(server.update_location(criada.id, _loja(horario=ALFRAGIDE, aberta_desde=None),
                                             current_user=ADMIN))
    assert devolvida.horario == ALFRAGIDE and devolvida.aberta_desde is None
    assert _gravada(empresa, criada.id)["horario"] == ALFRAGIDE
    corre(server.update_location(criada.id, _loja(horario=None, aberta_desde=None), current_user=ADMIN))
    gravada = _gravada(empresa, criada.id)
    assert gravada["horario"] is None and gravada["aberta_desde"] is None


def test_um_local_antigo_sem_os_campos_le_se_como_sempre(empresa):
    corre(empresa.locations.insert_one({"id": "l-velho", "name": "Escritório", "company_id": "c1", "address": None}))
    [lida] = corre(server.get_locations(current_user=ADMIN))
    assert lida.name == "Escritório" and lida.horario is None and lida.aberta_desde is None
```

- [ ] **Passo 3: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_horario_das_lojas.py -q
```

Esperado: `3 failed, 16 passed` — falham o POST (`criada.horario` é `None`), o PUT da página antiga (`KeyError: 'horario'`: nada foi gravado) e o formulário novo (`devolvida.horario` é `None`); o local antigo já passa (a resposta tem o campo desde a Tarefa 1). Se aparecer `skipped`, ler o motivo (`-rs`): sem mongod estes testes não valem.

- [ ] **Passo 4: Implementação mínima**

Em `backend/server.py`, imediatamente antes de `@api_router.post("/locations", response_model=LocationResponse)` (~1452), acrescentar:

```python
def _horario_para_gravar(location: LocationCreate) -> dict:
    """Os dois campos do calendário, na forma em que ficam no Mongo."""
    return {
        "horario": location.horario.model_dump() if location.horario else None,
        "aberta_desde": location.aberta_desde.isoformat() if location.aberta_desde else None,
    }

```

Em `create_location`, dentro de `location_doc`, entre `"google_place_id": location.google_place_id,` e `"created_at": ...`, acrescentar a linha:

```python
        **_horario_para_gravar(location),
```

Substituir `update_location` inteira (~1489-1507) por:

```python
@api_router.put("/locations/{location_id}", response_model=LocationResponse)
async def update_location(location_id: str, location: LocationCreate, current_user: dict = Depends(admin_required)):
    campos = {
        "name": location.name,
        "company_id": location.company_id,
        "address": location.address,
        "latitude": location.latitude,
        "longitude": location.longitude,
        "geofence_radius": location.geofence_radius,
        "google_place_id": location.google_place_id,
    }
    # O horário e a data de abertura só se escrevem se vierem no corpo: um browser com
    # a página antiga em cache manda o formulário sem eles, e um $set com None apagava
    # o horário da loja. O formulário novo manda-os sempre (também para os tirar).
    campos.update({k: v for k, v in _horario_para_gravar(location).items() if k in location.model_fields_set})
    result = await db.locations.update_one({"id": location_id}, {"$set": campos})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Local não encontrado")
    updated = await db.locations.find_one({"id": location_id}, {"_id": 0})
    company = await db.companies.find_one({"id": updated["company_id"]}, {"_id": 0})
    return LocationResponse(**updated, company_name=company["name"] if company else None)
```

- [ ] **Passo 5: Correr e ver passar**

O comando do Passo 3. Esperado: `19 passed` (nenhum `skipped`).

- [ ] **Passo 6: Prova por mutação**

1. No `update_location`, apagar `if k in location.model_fields_set` (fica `{k: v for k, v in _horario_para_gravar(location).items()}`). Esperado **1 failed**: `test_um_put_da_pagina_antiga_nao_apaga_o_horario` (`None != BELEM`). Repor.
2. No `create_location`, apagar a linha `**_horario_para_gravar(location),`. Esperado **2 failed**: o POST e a página antiga (`KeyError: 'horario'`). Repor.

`rm -rf ~/Library/Caches/com.apple.python`, correr outra vez (verde).

- [ ] **Passo 7: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add backend/server.py backend/tests/calendario/apoio.py backend/tests/calendario/conftest.py backend/tests/calendario/test_horario_das_lojas.py
git commit -m "$(cat <<'EOF'
Locais: o POST e o PUT gravam o horário, e a página antiga não o apaga

O PUT dos Locais substituía todos os campos com o que vinha no corpo. Um browser
com a página antiga em cache manda o formulário sem o horário, e isso apagava-o.
Agora o horário e a data de abertura só se escrevem se vierem no corpo
(model_fields_set); o formulário novo manda-os sempre, também para os tirar.
Testado contra um mongod real, porque o que interessa é o que fica gravado.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Tarefa 3: Dia da escala — loja e horas, com validação

**Ficheiros:**
- Modificar: `backend/server.py:634-660` (antes de `class WorkScheduleTemplateCreate`, e o próprio modelo)
- Testes: `backend/tests/calendario/test_escalas_com_dias.py` (criar)

**Interfaces:**
- Consome: `server._hora`, `server._dia_da_semana` (Tarefa 1).
- Produz:
  - `server.DiaDaEscala` — `dia: int`, `location_id: Optional[str] = None`, `inicio: Optional[str] = None`, `fim: Optional[str] = None` (`""` → `None` nos três)
  - `server.WorkScheduleTemplateCreate.dias: Optional[List[DiaDaEscala]] = None` (sem dias repetidos)

- [ ] **Passo 1: Escrever os testes que falham**

`backend/tests/calendario/test_escalas_com_dias.py`:

```python
"""As Escalas ganham loja e horas por dia — e o que já existia não muda.

Cada dia de uma escala diz a loja (vazia = a loja da ficha do colaborador) e,
opcionalmente, as horas (vazias = o horário da loja nesse dia). O `work_days` tem
três leitores sem testes (o saldo de férias, o «Em falta» do painel e o lembrete do
ponto — desenho, «medido 2»); por isso, com `dias`, o servidor deriva `work_days`
deles e põe o MESMO valor no modelo e nas atribuições, o `start_time` fica, e um PUT
da página antiga não apaga os `dias`.
"""
import pytest
from pydantic import ValidationError

import server

# A Joana: Amadora seg/ter, Oeiras qua, Algueirão qui/sex (com horas à quinta, para
# haver um dia com horas). É a forma exacta que o formulário manda.
JOANA = [
    {"dia": 0, "location_id": "amadora", "inicio": None, "fim": None},
    {"dia": 1, "location_id": "amadora", "inicio": None, "fim": None},
    {"dia": 2, "location_id": "oeiras", "inicio": None, "fim": None},
    {"dia": 3, "location_id": "algueirao", "inicio": "13:00", "fim": "22:00"},
    {"dia": 4, "location_id": "algueirao", "inicio": None, "fim": None},
]


def _escala(**extra):
    corpo = {"name": "Escala Joana", "workDays": [0, 1, 2, 3, 4], "startTime": "13:00"}
    corpo.update(extra)
    return server.WorkScheduleTemplateCreate.model_validate(corpo)


def test_um_dia_com_loja_e_horas():
    dia = server.DiaDaEscala.model_validate(JOANA[3])
    assert dia.model_dump() == JOANA[3]


def test_vazio_quer_dizer_loja_da_ficha_e_horario_da_loja():
    dia = server.DiaDaEscala.model_validate({"dia": 0, "location_id": "", "inicio": "", "fim": ""})
    assert dia.model_dump() == {"dia": 0, "location_id": None, "inicio": None, "fim": None}


@pytest.mark.parametrize("dia, mensagem", [
    ({"dia": 7}, "Dia inválido"),
    ({"dia": 0, "inicio": "13:00"}, "as duas"),
    ({"dia": 0, "fim": "22:00"}, "as duas"),
    ({"dia": 0, "inicio": "22:00", "fim": "13:00"}, "antes da saída"),
    ({"dia": 0, "inicio": "13:00", "fim": "13:00"}, "antes da saída"),
    ({"dia": 0, "inicio": "9:00", "fim": "13:00"}, "HH:MM"),
])
def test_dias_que_o_servidor_recusa(dia, mensagem):
    with pytest.raises(ValidationError, match=mensagem):
        server.DiaDaEscala.model_validate(dia)


def test_o_mesmo_dia_duas_vezes_e_recusado():
    with pytest.raises(ValidationError, match="Dia repetido"):
        _escala(dias=[{"dia": 2}, {"dia": 2, "location_id": "oeiras"}])


def test_com_dias_a_escala_traz_os():
    escala = _escala(dias=JOANA)
    assert [d.model_dump() for d in escala.dias] == JOANA
    assert "dias" in escala.model_fields_set


def test_sem_dias_a_escala_fica_como_sempre():
    escala = _escala()
    assert escala.dias is None
    assert "dias" not in escala.model_fields_set
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_escalas_com_dias.py -q
```

Esperado: `AttributeError: module 'server' has no attribute 'DiaDaEscala'` nos testes do dia; `test_o_mesmo_dia_duas_vezes_e_recusado` com «DID NOT RAISE» e `test_com_dias_a_escala_traz_os` com `AttributeError: ... 'dias'`; `test_sem_dias_a_escala_fica_como_sempre` falha também (`escala.dias` não existe).

- [ ] **Passo 3: Implementação mínima**

Em `backend/server.py`, imediatamente antes de `class WorkScheduleTemplateCreate(BaseModel):` (~634), acrescentar:

```python
class DiaDaEscala(BaseModel):
    """Onde e a que horas a pessoa trabalha num dia da semana.

    `location_id` vazio = a loja da ficha do colaborador; `inicio`/`fim` vazios = o
    horário da loja nesse dia. As duas horas vêm juntas ou nenhuma."""
    dia: int
    location_id: Optional[str] = None
    inicio: Optional[str] = None
    fim: Optional[str] = None

    @field_validator('location_id', 'inicio', 'fim', mode='before')
    @classmethod
    def _vazio_e_nada(cls, v):
        return None if v == "" else v

    @field_validator('dia')
    @classmethod
    def _valida_dia(cls, v):
        return _dia_da_semana(v)

    @field_validator('inicio', 'fim')
    @classmethod
    def _valida_hora(cls, v):
        return v if v is None else _hora(v)

    @model_validator(mode='after')
    def _horas_juntas(self):
        if (self.inicio is None) != (self.fim is None):
            raise ValueError("As horas de um dia escrevem-se as duas (entrada e saída) ou nenhuma")
        if self.inicio is not None and self.inicio >= self.fim:
            raise ValueError(f"A entrada tem de ser antes da saída ({self.inicio}–{self.fim})")
        return self

```

Em `class WorkScheduleTemplateCreate`, depois de `start_time: Optional[str] = Field(default=None, alias="startTime")`, acrescentar:

```python
    # Loja e horas por dia (calendário das lojas). Quando vem, o servidor deriva o
    # work_days daqui — ver _dias_de_trabalho.
    dias: Optional[List[DiaDaEscala]] = None
```

E, no mesmo modelo, depois do `validate_start_time`, acrescentar:

```python
    @field_validator('dias')
    @classmethod
    def validate_dias(cls, v):
        if v is not None and len({d.dia for d in v}) != len(v):
            raise ValueError("Dia repetido na escala")
        return v
```

- [ ] **Passo 4: Correr e ver passar**

O comando do Passo 2. Esperado: `11 passed`.

- [ ] **Passo 5: Prova por mutação**

1. Em `DiaDaEscala._horas_juntas`, trocar `if (self.inicio is None) != (self.fim is None):` por `if False:`. Esperado **2 failed**: o caso só com `fim` («DID NOT RAISE») e o caso só com `inicio` (rebenta com `TypeError` ao comparar `"13:00" >= None` — é por isso que esta regra vem antes da comparação). Repor.
2. Em `validate_dias`, trocar `!= len(v)` por `> len(v)`. Esperado **1 failed**: `test_o_mesmo_dia_duas_vezes_e_recusado`. Repor.

`rm -rf ~/Library/Caches/com.apple.python`, correr outra vez (verde).

- [ ] **Passo 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add backend/server.py backend/tests/calendario/test_escalas_com_dias.py
git commit -m "$(cat <<'EOF'
Escalas: cada dia passa a poder dizer a loja e as horas

A escala do RH era semanal e sem loja, e o calendário das lojas precisa de saber
onde cada pessoa está em cada dia (a Joana está em três lojas por semana) e, para
quem faz meio turno, a que horas. Vazio quer dizer o que já valia: a loja da ficha
e o horário da loja. As horas vêm as duas ou nenhuma, e a entrada antes da saída.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Tarefa 4: Escalas — `work_days` derivado de `dias` no POST e no PUT, sem mudar o que já existe

**Ficheiros:**
- Modificar: `backend/server.py:662-667` (`WorkScheduleTemplateResponse`), `backend/server.py:2112-2123` (`create_schedule_template` e dois ajudantes antes dela), `backend/server.py:2235-2249` (`update_schedule_template`)
- Testes: `backend/tests/calendario/test_escalas_com_dias.py` (acrescentar no fim)

**Interfaces:**
- Consome: `server.DiaDaEscala`, `server.WorkScheduleTemplateCreate.dias` (Tarefa 3); fixtures `base`, `corre`, `ADMIN` (Tarefa 2).
- Produz:
  - `server._dias_de_trabalho(template: WorkScheduleTemplateCreate) -> List[int]` — os `dia` de `dias` ordenados, ou `template.work_days` quando não há `dias`
  - `server._dias_para_gravar(template: WorkScheduleTemplateCreate) -> Optional[List[dict]]` — `dias` ordenados por `dia` em dicts, ou `None`
  - `server.WorkScheduleTemplateResponse.dias: Optional[List[dict]] = None`
  - documentos de `work_schedule_templates` com a chave `dias` (lista de `{"dia", "location_id", "inicio", "fim"}` ou `null`)

**Risco aceite (só documentar):** um `PUT` da página antiga, em cache, não manda `dias`: grava o `workDays` do corpo e deixa os `dias` que lá estavam. Se nessa página se marcar ou desmarcar um dia, `work_days` e `dias` deixam de bater. A Fase 2 já lida com isso, porque quem manda é o `work_days`: um dia de `work_days` sem entrada em `dias` vai para a loja da ficha com o horário da loja, e uma entrada de `dias` para um dia que não está em `work_days` não conta. Não há nada a corrigir aqui.

- [ ] **Passo 1: Escrever os testes que falham**

No topo de `backend/tests/calendario/test_escalas_com_dias.py`, debaixo de `import server`, acrescentar:

```python
from .apoio import ADMIN, corre
```

No fim do ficheiro, acrescentar:

```python
# ---- Tarefa 4: o que fica gravado e quem o lê (contra um mongod real) ----

def _cria(**extra):
    return corre(server.create_schedule_template(_escala(**extra), current_user=ADMIN))


def _muda(template_id, **extra):
    return corre(server.update_schedule_template(template_id, _escala(**extra), current_user=ADMIN))


def _atribui(base, employee_id, template_id, inicio="2026-01-01"):
    corre(base.employees.update_one(
        {"id": employee_id},
        {"$setOnInsert": {"name": "Pessoa " + employee_id, "company_id": "c1", "location_id": "oeiras"}},
        upsert=True))
    pedido = server.WorkScheduleAssignmentCreate.model_validate(
        {"employeeId": employee_id, "templateId": template_id, "startDate": inicio})
    return corre(server.assign_schedule(pedido, current_user=ADMIN))


def _gravado(base, colecao, doc_id):
    return corre(base[colecao].find_one({"id": doc_id}, {"_id": 0}))


def test_o_post_deriva_os_dias_de_trabalho_dos_dias(base):
    # O formulário manda workDays igual aos dias; mesmo que não mande, valem os `dias`.
    criada = _cria(workDays=[0, 1, 2, 3, 4, 5, 6], dias=JOANA)
    assert criada.work_days == [0, 1, 2, 3, 4]
    assert criada.dias == JOANA
    gravada = _gravado(base, "work_schedule_templates", criada.id)
    assert gravada["work_days"] == [0, 1, 2, 3, 4]
    assert gravada["dias"] == JOANA


def test_o_put_deriva_e_poe_o_mesmo_valor_no_modelo_e_nas_atribuicoes(base):
    criada = _cria()                                   # 5x2 sem dias, como as de hoje
    atribuicao = _atribui(base, "emp-j", criada.id)
    _muda(criada.id, workDays=[6], dias=JOANA[:3])     # workDays de propósito diferente
    assert _gravado(base, "work_schedule_templates", criada.id)["work_days"] == [0, 1, 2]
    assert _gravado(base, "work_schedule_assignments", atribuicao.id)["work_days"] == [0, 1, 2]


def test_o_start_time_fica_e_o_lembrete_do_ponto_le_o_mesmo(base):
    criada = _cria(dias=JOANA)
    _atribui(base, "emp-j", criada.id)
    joana = {"user_id": "u-j", "role": "colaborador", "employee_id": "emp-j"}
    assert corre(server.get_my_schedule(current_user=joana)) == {
        "work_days": [0, 1, 2, 3, 4], "start_time": "13:00", "template_name": "Escala Joana"}
    _muda(criada.id, workDays=[0, 1, 2, 3], dias=JOANA[:4])
    assert corre(server.get_my_schedule(current_user=joana)) == {
        "work_days": [0, 1, 2, 3], "start_time": "13:00", "template_name": "Escala Joana"}


def test_um_put_da_pagina_antiga_nao_apaga_os_dias(base):
    criada = _cria(dias=JOANA)
    _muda(criada.id, name="Escala Joana (renomeada)")   # sem a chave `dias`, como a página antiga
    gravada = _gravado(base, "work_schedule_templates", criada.id)
    assert gravada["name"] == "Escala Joana (renomeada)"
    assert gravada["dias"] == JOANA


def test_uma_escala_antiga_sem_dias_continua_a_ler_se_e_a_gravar_se(base):
    corre(base.work_schedule_templates.insert_one({
        "id": "t-velha", "name": "5x2", "work_days": [0, 1, 2, 3, 4], "start_time": None,
        "created_at": "2026-01-01T00:00:00+00:00"}))
    [lida] = corre(server.get_schedule_templates(current_user=ADMIN))
    assert lida.dias is None and lida.work_days == [0, 1, 2, 3, 4]
    _muda("t-velha", name="5x2", workDays=[0, 1, 2, 3, 4, 5], startTime=None)
    gravada = _gravado(base, "work_schedule_templates", "t-velha")
    assert gravada["work_days"] == [0, 1, 2, 3, 4, 5]
    assert "dias" not in gravada


def test_o_saldo_de_ferias_de_quem_passa_a_ter_dias_da_o_mesmo(base):
    """A Rafaela: Belém fecha à terça. Outubro de 2026 tem 31 dias, 4 terças
    (6, 13, 20, 27) e o feriado de 5/10: 31 - 4 - 1 = 26 dias contados."""
    rafaela = [0, 2, 3, 4, 5, 6]
    criada = _cria(name="6x1", workDays=rafaela, startTime="11:30")
    _atribui(base, "emp-r", criada.id)
    antes = corre(server.calculate_leave_counted_days("emp-r", "2026-10-01", "2026-10-31"))
    _muda(criada.id, name="Escala Rafaela", workDays=rafaela, startTime="11:30",
          dias=[{"dia": d, "location_id": "belem", "inicio": None, "fim": None} for d in rafaela])
    depois = corre(server.calculate_leave_counted_days("emp-r", "2026-10-01", "2026-10-31"))
    assert antes == 26
    assert depois == antes
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_escalas_com_dias.py -q
```

Esperado: `4 failed, 13 passed` — falham o POST (`work_days` fica `[0, 1, 2, 3, 4, 5, 6]`), o PUT (`[6]`), a página antiga (`KeyError: 'dias'`: o POST de hoje não o grava) e a escala antiga (`lida.dias` não existe na resposta). O lembrete e o saldo já passam, porque o corpo manda os mesmos dias que os `dias`: são os guardas de que o que já existe não muda, e as mutações 2 e 4 do Passo 5 mostram-nos vermelhos.

- [ ] **Passo 3: Implementação mínima**

Em `class WorkScheduleTemplateResponse` (~662), depois de `start_time: Optional[str] = None`, acrescentar:

```python
    # dict e não DiaDaEscala, pela mesma razão do LocationResponse.horario.
    dias: Optional[List[dict]] = None
```

Imediatamente antes de `@api_router.post("/schedules", response_model=WorkScheduleTemplateResponse)` (~2112), acrescentar:

```python
def _dias_de_trabalho(template: WorkScheduleTemplateCreate) -> List[int]:
    """Os dias em que a pessoa trabalha. Com `dias`, saem deles (ordenados): é isto
    que mantém o saldo de férias, o «Em falta» do painel e o lembrete do ponto a ler
    um `work_days` que continua a querer dizer o mesmo."""
    if template.dias:
        return sorted(d.dia for d in template.dias)
    return template.work_days


def _dias_para_gravar(template: WorkScheduleTemplateCreate) -> Optional[List[dict]]:
    if template.dias is None:
        return None
    return [d.model_dump() for d in sorted(template.dias, key=lambda d: d.dia)]

```

Em `create_schedule_template`, substituir o `template_doc` por:

```python
    template_doc = {
        "id": template_id,
        "name": template.name,
        "work_days": _dias_de_trabalho(template),
        "start_time": template.start_time,
        "dias": _dias_para_gravar(template),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
```

Substituir `update_schedule_template` inteira (~2235-2249) por:

```python
@api_router.put("/schedules/{template_id}", response_model=WorkScheduleTemplateResponse)
async def update_schedule_template(template_id: str, template: WorkScheduleTemplateCreate, current_user: dict = Depends(admin_manager_required)):
    # Calculado UMA vez: o mesmo valor vai para o modelo e para a cópia das atribuições.
    work_days = _dias_de_trabalho(template)
    campos = {"name": template.name, "work_days": work_days, "start_time": template.start_time}
    # A página antiga (em cache no browser) não manda `dias`; sem esta guarda, apagava-os.
    if "dias" in template.model_fields_set:
        campos["dias"] = _dias_para_gravar(template)
    result = await db.work_schedule_templates.update_one({"id": template_id}, {"$set": campos})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Escala não encontrada")
    # Manter os dias coerentes nas atribuições que usam esta escala
    await db.work_schedule_assignments.update_many(
        {"template_id": template_id},
        {"$set": {"work_days": work_days}}
    )
    updated = await db.work_schedule_templates.find_one({"id": template_id}, {"_id": 0})
    return WorkScheduleTemplateResponse(**updated)
```

- [ ] **Passo 4: Correr e ver passar**

O comando do Passo 2. Esperado: `17 passed`, nenhum `skipped`.

- [ ] **Passo 5: Prova por mutação**

1. No `update_schedule_template`, trocar `{"$set": {"work_days": work_days}}` por `{"$set": {"work_days": template.work_days}}`. Esperado **1 failed**: `test_o_put_deriva_e_poe_o_mesmo_valor_no_modelo_e_nas_atribuicoes` (`[6] != [0, 1, 2]` na atribuição). Repor.
2. Em `_dias_de_trabalho`, trocar `return sorted(d.dia for d in template.dias)` por `return sorted(d.dia for d in template.dias)[1:]` (um `work_days` que perde um dia e deixa de querer dizer o mesmo). Esperado vermelho em `test_o_saldo_de_ferias_de_quem_passa_a_ter_dias_da_o_mesmo` (`23 != 26`: saem as segundas), e também no POST, no PUT e no lembrete. Repor. (Não usar `(d.dia + 1) % 7` como mutação: na Rafaela troca a quarta pela terça, e outubro de 2026 tem quatro de cada — o saldo dava igual por coincidência.)
3. No `update_schedule_template`, trocar `if "dias" in template.model_fields_set:` por `if True:`. Esperado **2 failed**: `test_um_put_da_pagina_antiga_nao_apaga_os_dias` (`None != JOANA`) e `test_uma_escala_antiga_sem_dias_continua_a_ler_se_e_a_gravar_se` (ganhava `dias: null`). Repor.
4. No `create_schedule_template`, trocar `"start_time": template.start_time,` por `"start_time": None if template.dias else template.start_time,`. Esperado **1 failed**: `test_o_start_time_fica_e_o_lembrete_do_ponto_le_o_mesmo`. Repor.

`rm -rf ~/Library/Caches/com.apple.python`, correr outra vez (verde). Depois a suite inteira — esperado `passed` = partida + 36, `skipped` igual à partida:

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
export PATH="$HOME/.local/node/bin:$PATH"
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest -q 2>&1 | tail -3
```


- [ ] **Passo 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add backend/server.py backend/tests/calendario/test_escalas_com_dias.py
git commit -m "$(cat <<'EOF'
Escalas: o work_days passa a sair dos dias, no POST e no PUT, sem mudar quem o lê

O work_days tem três leitores sem testes: o saldo de férias, o «Em falta» do
painel e o lembrete do ponto. Com loja e horas por dia, o servidor deriva-o dos
dias, calcula-o uma vez e põe o mesmo valor no modelo e nas atribuições; o
start_time fica; e um PUT da página antiga, em cache, já não apaga os dias. O
saldo de férias de quem passa a ter dias dá o mesmo — testado contra um mongod.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Tarefa 5: `lib/horarios.js` — a passagem entre o formulário e o servidor

**Ficheiros:**
- Criar: `frontend/src/lib/horarios.js`
- Testes: `backend/tests/calendario/test_formularios_do_portal.py` (criar)

**Interfaces:**
- Consome: a forma de `horario`/`aberta_desde` (Tarefas 1-2) e de `dias` (Tarefas 3-4) que o servidor devolve.
- Produz (exports de `frontend/src/lib/horarios.js`):
  - `DIAS_DA_SEMANA: string[]` — `['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']`
  - `horarioParaFormulario(horario, abertaDesde) -> { tem: boolean, abre: string, fecha: string, dias: Array<{ modo: 'geral'|'outro'|'fechada', abre: string, fecha: string }> (7), abertaDesde: string }`
  - `formularioParaHorario(form) -> { horario: object|null, aberta_desde: string|null }` (as duas chaves sempre)
  - `resumoDoHorario(horario) -> string` (`''` sem horário)
  - `diasParaFormulario(dias) -> { [dia]: { location_id: string, inicio: string, fim: string } }`
  - `formularioParaDias(workDays, porDia) -> Array<{ dia, location_id|null, inicio|null, fim|null }>` (uma por dia marcado, por ordem)
  - `resumoDosDias(dias, nomeDaLoja: (id) => string|undefined) -> string`
- Produz (no ficheiro de teste, para as Tarefas 6 e 7): `_no_node(guiao) -> json`, `_corre(expressao) -> json`, constantes `_LOCAIS`, `_ESCALAS`.

- [ ] **Passo 1: Escrever os testes que falham**

`backend/tests/calendario/test_formularios_do_portal.py`:

```python
"""O que os formulários dos Locais e das Escalas mandam ao servidor.

A passagem entre o que o servidor guarda (`horario`, `aberta_desde`, `dias`) e o que o
ecrã mostra vive em `frontend/src/lib/horarios.js`. Aqui corre-se o ficheiro VERDADEIRO
em Node (o Babel só troca `export` por CommonJS) — nunca uma cópia, que ficaria verde
com o ecrã errado. Mais abaixo (Tarefas 6 e 7), os guardas de que os dois ecrãs o usam
mesmo: uma função pura testada não prova nada se a linha que a chama desaparecer.

Precisa de `frontend/node_modules` (o atalho para ~/Developer/RH/frontend/node_modules)
e de `node` (no PATH ou em ~/.local/node/bin); sem eles SALTA e diz porquê.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parents[3]
_FRONTEND = _RAIZ / "frontend"
_HORARIOS = _FRONTEND / "src" / "lib" / "horarios.js"
_LOCAIS = _FRONTEND / "src" / "pages" / "admin" / "AdminLocations.js"
_ESCALAS = _FRONTEND / "src" / "pages" / "admin" / "AdminSchedules.js"

BELEM = {
    "abre": "11:30", "fecha": "19:00",
    "excecoes": [{"dia": 6, "abre": "11:30", "fecha": "20:00"}],
    "fechada": [1],
}


def _node():
    caminho = shutil.which("node")
    if caminho:
        return caminho
    candidato = Path.home() / ".local" / "node" / "bin" / "node"
    if candidato.exists():
        return str(candidato)
    pytest.skip("Sem `node` (nem no PATH nem em ~/.local/node/bin): o JavaScript dos formulários NÃO foi testado.")


def _no_node(guiao):
    if not (_FRONTEND / "node_modules" / "@babel" / "core").exists():
        pytest.skip("Sem frontend/node_modules: ln -sfn ~/Developer/RH/frontend/node_modules frontend/node_modules")
    resultado = subprocess.run(
        [_node(), "-e", guiao],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=str(_FRONTEND),
        env={"NODE_PATH": str(_FRONTEND / "node_modules"), "PATH": "/usr/bin:/bin"},
    )
    if resultado.returncode != 0:
        pytest.fail("O JavaScript não correu:\n" + resultado.stderr.decode("utf-8", "replace"))
    return json.loads(resultado.stdout.decode("utf-8"))


def _corre(expressao):
    """Avalia `expressao` (JavaScript, com `h` = o módulo lib/horarios.js) e devolve o JSON."""
    return _no_node("\n".join([
        "const fs = require('fs');",
        "const babel = require('@babel/core');",
        "const Module = require('module');",
        "const ficheiro = %s;" % json.dumps(str(_HORARIOS)),
        "const codigo = babel.transformSync(fs.readFileSync(ficheiro, 'utf-8'), {",
        "  plugins: [require.resolve('@babel/plugin-transform-modules-commonjs')],",
        "  filename: ficheiro, babelrc: false, configFile: false,",
        "}).code;",
        "const m = new Module(ficheiro, null);",
        "m._compile(codigo, ficheiro);",
        "const h = m.exports;",
        "process.stdout.write(JSON.stringify(%s));" % expressao,
    ]))


# ---- Locais ----

def test_o_horario_de_belem_vai_ao_formulario_e_volta_igual():
    volta = _corre("h.formularioParaHorario(h.horarioParaFormulario(%s, '2026-10-24'))" % json.dumps(BELEM))
    assert volta == {"horario": BELEM, "aberta_desde": "2026-10-24"}


def test_o_formulario_mostra_o_domingo_com_outro_horario_e_a_terca_fechada():
    form = _corre("h.horarioParaFormulario(%s, null)" % json.dumps(BELEM))
    assert (form["tem"], form["abre"], form["fecha"], form["abertaDesde"]) == (True, "11:30", "19:00", "")
    assert [d["modo"] for d in form["dias"]] == ["geral", "fechada", "geral", "geral", "geral", "geral", "outro"]
    assert form["dias"][6] == {"modo": "outro", "abre": "11:30", "fecha": "20:00"}


def test_sem_horario_manda_as_duas_chaves_a_null():
    # O PUT só escreve o que vem no corpo: o formulário novo manda SEMPRE as duas chaves.
    assert _corre("h.formularioParaHorario(h.horarioParaFormulario(null, null))") == {
        "horario": None, "aberta_desde": None}


def test_desligar_o_horario_tira_o_e_marcar_dias_poe_os():
    form = _corre("h.horarioParaFormulario(null, null)")
    form.update({"tem": True, "abre": "13:00", "fecha": "22:00"})
    form["dias"][1] = {"modo": "fechada", "abre": "", "fecha": ""}
    form["dias"][6] = {"modo": "outro", "abre": "13:00", "fecha": "20:00"}
    assert _corre("h.formularioParaHorario(%s)" % json.dumps(form)) == {
        "horario": {"abre": "13:00", "fecha": "22:00",
                    "excecoes": [{"dia": 6, "abre": "13:00", "fecha": "20:00"}], "fechada": [1]},
        "aberta_desde": None}
    # A data só se vê com o horário ligado, mas o valor fica no formulário: desligar
    # o horário tem de a tirar também.
    form["abertaDesde"] = "2026-10-24"
    form["tem"] = False
    assert _corre("h.formularioParaHorario(%s)" % json.dumps(form)) == {"horario": None, "aberta_desde": None}


def test_o_resumo_do_horario_na_tabela():
    assert _corre("h.resumoDoHorario(%s)" % json.dumps(BELEM)) == "11:30–19:00 · Dom 11:30–20:00 · fecha Ter"
    assert _corre("h.resumoDoHorario(null)") == ""


# ---- Escalas ----

DIAS = [
    {"dia": 0, "location_id": "amadora", "inicio": None, "fim": None},
    {"dia": 3, "location_id": None, "inicio": "13:00", "fim": "22:00"},
]


def test_os_dias_da_escala_seguem_os_dias_marcados_e_por_ordem():
    por_dia = {
        "0": {"location_id": "amadora", "inicio": "", "fim": ""},
        "3": {"location_id": "", "inicio": "13:00", "fim": "22:00"},
        "5": {"location_id": "oeiras", "inicio": "", "fim": ""},   # dia desmarcado: não vai
    }
    assert _corre("h.formularioParaDias([3, 0, 2], %s)" % json.dumps(por_dia)) == [
        {"dia": 0, "location_id": "amadora", "inicio": None, "fim": None},
        {"dia": 2, "location_id": None, "inicio": None, "fim": None},
        {"dia": 3, "location_id": None, "inicio": "13:00", "fim": "22:00"},
    ]


def test_os_dias_gravados_voltam_ao_formulario_e_saem_iguais():
    assert _corre("h.formularioParaDias([0, 3], h.diasParaFormulario(%s))" % json.dumps(DIAS)) == DIAS
    assert _corre("h.diasParaFormulario(null)") == {}
    assert _corre("h.diasParaFormulario(%s)" % json.dumps(DIAS))["3"] == {
        "location_id": "", "inicio": "13:00", "fim": "22:00"}


def test_o_resumo_dos_dias_na_tabela():
    lojas = json.dumps({"amadora": "Amadora"})
    assert _corre("h.resumoDosDias(%s, (id) => (%s)[id])" % (json.dumps(DIAS), lojas)) == \
        "Seg Amadora · Qui loja da ficha 13:00–22:00"
    perdida = json.dumps([{"dia": 2, "location_id": "x", "inicio": None, "fim": None}])
    assert _corre("h.resumoDosDias(%s, () => undefined)" % perdida) == "Qua (loja removida)"
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_formularios_do_portal.py -q -rs
```

Esperado: `8 failed`, todos com «O JavaScript não correu: … ENOENT … horarios.js». Se vier `skipped`, o atalho de `frontend/node_modules` ou o `node` faltam — corrigir antes de seguir.

- [ ] **Passo 3: Implementação mínima**

`frontend/src/lib/horarios.js`:

```js
// Horário das lojas e dias das escalas — a passagem entre o que o servidor guarda e
// o que os formulários dos Locais e das Escalas mostram.
//
// Funções puras, sem imports: correm em Node nos testes
// (backend/tests/calendario/test_formularios_do_portal.py).
//
// Dias: 0 = segunda … 6 = domingo, como o `work_days` das escalas.

export const DIAS_DA_SEMANA = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'];

// ---------- Locais ----------

// O formulário do horário: `tem` (a loja entra no calendário), o horário geral, e por
// cada dia um `modo` — 'geral', 'outro' (uma exceção, com horas) ou 'fechada'.
export function horarioParaFormulario(horario, abertaDesde) {
  const excecoes = new Map(((horario && horario.excecoes) || []).map((e) => [e.dia, e]));
  const fechada = new Set((horario && horario.fechada) || []);
  return {
    tem: Boolean(horario),
    abre: (horario && horario.abre) || '',
    fecha: (horario && horario.fecha) || '',
    dias: DIAS_DA_SEMANA.map((_, dia) => {
      if (fechada.has(dia)) return { modo: 'fechada', abre: '', fecha: '' };
      const e = excecoes.get(dia);
      return e ? { modo: 'outro', abre: e.abre, fecha: e.fecha } : { modo: 'geral', abre: '', fecha: '' };
    }),
    abertaDesde: abertaDesde || '',
  };
}

// O que vai no corpo do POST/PUT dos Locais. Manda SEMPRE as duas chaves: o PUT só
// escreve os campos que vêm no corpo, e é assim que tirar o horário funciona.
// Sem horário, sem data: o campo da data só se vê com o horário ligado, mas o valor
// continua guardado no formulário.
export function formularioParaHorario(form) {
  const comModo = (modo) => form.dias.map((d, dia) => ({ ...d, dia })).filter((d) => d.modo === modo);
  return {
    horario: form.tem
      ? {
          abre: form.abre,
          fecha: form.fecha,
          excecoes: comModo('outro').map(({ dia, abre, fecha }) => ({ dia, abre, fecha })),
          fechada: comModo('fechada').map(({ dia }) => dia),
        }
      : null,
    aberta_desde: form.tem && form.abertaDesde ? form.abertaDesde : null,
  };
}

// «11:30–19:00 · Dom 11:30–20:00 · fecha Ter» — para a tabela dos Locais.
export function resumoDoHorario(horario) {
  if (!horario) return '';
  const partes = [`${horario.abre}–${horario.fecha}`];
  (horario.excecoes || []).forEach((e) => partes.push(`${DIAS_DA_SEMANA[e.dia]} ${e.abre}–${e.fecha}`));
  if ((horario.fechada || []).length) {
    partes.push(`fecha ${horario.fechada.map((d) => DIAS_DA_SEMANA[d]).join(', ')}`);
  }
  return partes.join(' · ');
}

// ---------- Escalas ----------

// `dias` gravados → { [dia]: { location_id, inicio, fim } }, com '' no lugar de null
// (os <select> e <input> do formulário não aceitam null).
export function diasParaFormulario(dias) {
  const porDia = {};
  (dias || []).forEach((d) => {
    porDia[d.dia] = { location_id: d.location_id || '', inicio: d.inicio || '', fim: d.fim || '' };
  });
  return porDia;
}

// O `dias` do corpo do POST/PUT: uma entrada por dia MARCADO, por ordem. O `workDays`
// vai igual a estes dias (o servidor deriva-o daqui). Vazio = null: loja da ficha,
// horário da loja.
export function formularioParaDias(workDays, porDia) {
  return [...workDays]
    .sort((a, b) => a - b)
    .map((dia) => {
      const d = porDia[dia] || {};
      return { dia, location_id: d.location_id || null, inicio: d.inicio || null, fim: d.fim || null };
    });
}

// «Seg Amadora · Qui loja da ficha 13:00–22:00» — para a tabela das Escalas.
export function resumoDosDias(dias, nomeDaLoja) {
  return (dias || [])
    .map((d) => {
      const loja = d.location_id ? nomeDaLoja(d.location_id) || '(loja removida)' : 'loja da ficha';
      const horas = d.inicio ? ` ${d.inicio}–${d.fim}` : '';
      return `${DIAS_DA_SEMANA[d.dia]} ${loja}${horas}`;
    })
    .join(' · ');
}
```

- [ ] **Passo 4: Correr e ver passar**

O comando do Passo 2. Esperado: `8 passed`, nenhum `skipped`.

- [ ] **Passo 5: Prova por mutação**

1. Em `formularioParaHorario`, trocar `aberta_desde: form.tem && form.abertaDesde ? form.abertaDesde : null,` por `aberta_desde: form.abertaDesde,`. Esperado **2 failed**: `test_sem_horario_manda_as_duas_chaves_a_null` e `test_desligar_o_horario_tira_o_e_marcar_dias_poe_os` (`'' != None`). Repor.
2. Em `formularioParaDias`, apagar a linha `.sort((a, b) => a - b)`. Esperado **1 failed**: `test_os_dias_da_escala_seguem_os_dias_marcados_e_por_ordem`. Repor.
3. Em `formularioParaHorario`, voltar a `aberta_desde: form.abertaDesde || null,` (a data sem olhar para `tem`). Esperado **1 failed**: `test_desligar_o_horario_tira_o_e_marcar_dias_poe_os` (`'2026-10-24' != None`: desligar o horário deixava a data gravada). Repor.

(JavaScript corre de fresco em cada teste: não há cache a limpar.)

- [ ] **Passo 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add frontend/src/lib/horarios.js backend/tests/calendario/test_formularios_do_portal.py
git commit -m "$(cat <<'EOF'
Portal: lib/horarios.js passa o horário e os dias entre o servidor e os formulários

Os formulários dos Locais e das Escalas vão mostrar o horário por dia (geral,
outro horário, fechada) e a loja e as horas de cada dia da escala. A conversão
vive num módulo puro, testado em Node a correr o ficheiro verdadeiro: o horário
de Belém vai e volta igual, e o corpo leva sempre as chaves novas, porque o PUT
só escreve o que vem nele.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Tarefa 6: Formulário dos Locais — horário geral, exceções, dias fechados e data de abertura

**Ficheiros:**
- Modificar: `frontend/src/pages/admin/AdminLocations.js` (imports 1-39, `handleOpenDialog` 77-96, antes de `handleSubmit` 141, `handleSubmit` 141-172, tabela 218-250, diálogo 323-334)
- Testes: `backend/tests/calendario/test_formularios_do_portal.py` (acrescentar no fim)

**Interfaces:**
- Consome: `DIAS_DA_SEMANA`, `horarioParaFormulario`, `formularioParaHorario`, `resumoDoHorario` (Tarefa 5); `detalhesErro(error, fallback) -> { campo, mensagem }` de `frontend/src/lib/faturacao.js:64`; `PUT`/`POST /api/locations` com `horario` e `aberta_desde` (Tarefa 2).
- Produz: `formData.horario` (a forma de `horarioParaFormulario`); `data-testid`s `location-horario`, `location-horario-tem`, `location-horario-abre`, `location-horario-fecha`, `location-horario-modo-<dia>`, `location-aberta-desde`, `location-horario-<id>` (usados no ensaio e na verificação do bundle).

- [ ] **Passo 1: Escrever os testes que falham**

No fim de `backend/tests/calendario/test_formularios_do_portal.py`, acrescentar:

```python
# ---- Os ecrãs usam mesmo o lib/horarios.js, e compilam ----

def _compila(ficheiro):
    """O ecrã passa pelo Babel com o preset de React: apanha um JSX partido sem
    esperar pelo build de produção."""
    _no_node("\n".join([
        "const fs = require('fs');",
        "const babel = require('@babel/core');",
        "const ficheiro = %s;" % json.dumps(str(ficheiro)),
        "babel.transformSync(fs.readFileSync(ficheiro, 'utf-8'), {",
        "  presets: [[require.resolve('@babel/preset-react'), { runtime: 'classic' }]],",
        "  filename: ficheiro, babelrc: false, configFile: false,",
        "});",
        "process.stdout.write('null');",
    ]))


def test_o_formulario_dos_locais_carrega_e_manda_o_horario():
    texto = _LOCAIS.read_text(encoding="utf-8")
    # Ao abrir uma loja, o horário gravado vai para o formulário…
    assert "horario: horarioParaFormulario(location.horario, location.aberta_desde)," in texto
    # …uma loja nova começa sem horário…
    assert "horario: horarioParaFormulario(null, null)," in texto
    # …e o corpo do POST/PUT leva SEMPRE as duas chaves.
    assert "...formularioParaHorario(formData.horario)," in texto
    # 422 legível: nunca o array do Pydantic directo no toast.
    assert "toast.error(detalhesErro(error, 'Erro ao guardar local').mensagem);" in texto


def test_o_ecra_dos_locais_compila():
    _compila(_LOCAIS)
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_formularios_do_portal.py -q -rs
```

Esperado: `1 failed, 9 passed` — `test_o_formulario_dos_locais_carrega_e_manda_o_horario` (`assert ... in texto`). O de compilar passa já: é o guarda das edições seguintes.

- [ ] **Passo 3: Implementação — imports e estado**

Em `frontend/src/pages/admin/AdminLocations.js`, trocar

```js
import { Badge } from '../../components/ui/badge';
```

por

```js
import { Badge } from '../../components/ui/badge';
import { Checkbox } from '../../components/ui/checkbox';
```

Trocar

```js
import { MapPin, Plus, Pencil, Trash2, LocateFixed, Loader2, Star, Search } from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import { toast } from 'sonner';

const emptyForm = { name: '', company_id: '', address: '', latitude: '', longitude: '', geofence_radius: '', google_place_id: '' };
```

por

```js
import { MapPin, Plus, Pencil, Trash2, LocateFixed, Loader2, Star, Search, Clock } from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import { toast } from 'sonner';
import { DIAS_DA_SEMANA, horarioParaFormulario, formularioParaHorario, resumoDoHorario } from '../../lib/horarios';
import { detalhesErro } from '../../lib/faturacao';

const emptyForm = {
  name: '', company_id: '', address: '', latitude: '', longitude: '', geofence_radius: '', google_place_id: '',
  horario: horarioParaFormulario(null, null),
};
```

Em `handleOpenDialog`, trocar

```js
        google_place_id: location.google_place_id || '',
      });
```

por

```js
        google_place_id: location.google_place_id || '',
        horario: horarioParaFormulario(location.horario, location.aberta_desde),
      });
```

Imediatamente antes de `  const handleSubmit = async (e) => {`, acrescentar:

```js
  // O horário vive dentro do formData; estas duas mudam-no sem tocar no resto.
  const mudarHorario = (mudanca) =>
    setFormData((prev) => ({ ...prev, horario: { ...prev.horario, ...mudanca } }));
  const mudarDia = (dia, mudanca) =>
    setFormData((prev) => ({
      ...prev,
      horario: {
        ...prev.horario,
        dias: prev.horario.dias.map((d, i) => (i === dia ? { ...d, ...mudanca } : d)),
      },
    }));

```

- [ ] **Passo 4: Implementação — o corpo e o erro**

Em `handleSubmit`, trocar

```js
      google_place_id: formData.google_place_id.trim() || null,
    };
```

por

```js
      google_place_id: formData.google_place_id.trim() || null,
      // Vai SEMPRE (horario + aberta_desde): o PUT só os escreve se vierem no corpo.
      ...formularioParaHorario(formData.horario),
    };
```

e trocar

```js
      toast.error(error.response?.data?.detail || 'Erro ao guardar local');
```

por

```js
      toast.error(detalhesErro(error, 'Erro ao guardar local').mensagem);
```

- [ ] **Passo 5: Implementação — a coluna «Horário» na tabela**

Trocar

```js
                    <TableHead className="hidden sm:table-cell">Cerca</TableHead>
```

por

```js
                    <TableHead className="hidden sm:table-cell">Cerca</TableHead>
                    <TableHead className="hidden lg:table-cell">Horário</TableHead>
```

e trocar

```js
                          <span className="text-xs text-muted-foreground">Desligada</span>
                        )}
                      </TableCell>
```

por

```js
                          <span className="text-xs text-muted-foreground">Desligada</span>
                        )}
                      </TableCell>
                      <TableCell
                        className="hidden lg:table-cell text-xs text-muted-foreground"
                        data-testid={`location-horario-${location.id}`}
                      >
                        {resumoDoHorario(location.horario) || '—'}
                        {location.aberta_desde ? ` · abre a ${location.aberta_desde}` : ''}
                      </TableCell>
```

- [ ] **Passo 6: Implementação — a secção «Horário da loja» no diálogo**

Trocar

```js
              {/* Cerca geográfica */}
```

por

```js
              {/* Horário — só as lojas com horário entram no calendário das lojas */}
              <div className="rounded-lg border p-3 space-y-3 bg-muted/30" data-testid="location-horario">
                <div className="flex items-center gap-2">
                  <Clock className="h-4 w-4 text-primary" />
                  <span className="font-medium text-sm">Horário da loja (opcional)</span>
                </div>
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={formData.horario.tem}
                    onCheckedChange={(v) => mudarHorario({ tem: v === true })}
                    data-testid="location-horario-tem"
                  />
                  Esta loja tem horário (entra no calendário das lojas)
                </label>
                <p className="text-xs text-muted-foreground">
                  Escritórios e locais fora do calendário ficam sem horário.
                </p>
                {formData.horario.tem && (
                  <>
                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-1">
                        <Label htmlFor="horario-abre" className="text-xs">Abre</Label>
                        <Input
                          id="horario-abre"
                          type="time"
                          required
                          value={formData.horario.abre}
                          onChange={(e) => mudarHorario({ abre: e.target.value })}
                          data-testid="location-horario-abre"
                        />
                      </div>
                      <div className="space-y-1">
                        <Label htmlFor="horario-fecha" className="text-xs">Fecha</Label>
                        <Input
                          id="horario-fecha"
                          type="time"
                          required
                          value={formData.horario.fecha}
                          onChange={(e) => mudarHorario({ fecha: e.target.value })}
                          data-testid="location-horario-fecha"
                        />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <p className="text-xs text-muted-foreground">
                        Por dia: o horário geral, outro horário (ex.: domingo até mais tarde) ou fechada.
                      </p>
                      {DIAS_DA_SEMANA.map((nome, dia) => {
                        const d = formData.horario.dias[dia];
                        return (
                          <div key={dia} className="flex flex-wrap items-center gap-2" data-testid={`location-horario-dia-${dia}`}>
                            <span className="w-10 text-sm">{nome}</span>
                            <select
                              value={d.modo}
                              onChange={(e) => mudarDia(dia, { modo: e.target.value })}
                              className="h-9 rounded-md border border-input bg-background px-2 text-sm"
                              aria-label={`Horário de ${nome}`}
                              data-testid={`location-horario-modo-${dia}`}
                            >
                              <option value="geral">Horário geral</option>
                              <option value="outro">Outro horário</option>
                              <option value="fechada">Fechada</option>
                            </select>
                            {d.modo === 'outro' && (
                              <>
                                <Input
                                  type="time"
                                  required
                                  className="w-28"
                                  value={d.abre}
                                  onChange={(e) => mudarDia(dia, { abre: e.target.value })}
                                  aria-label={`${nome}: abre`}
                                />
                                <Input
                                  type="time"
                                  required
                                  className="w-28"
                                  value={d.fecha}
                                  onChange={(e) => mudarDia(dia, { fecha: e.target.value })}
                                  aria-label={`${nome}: fecha`}
                                />
                              </>
                            )}
                          </div>
                        );
                      })}
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor="aberta-desde" className="text-xs">Aberta desde (opcional — só para uma loja a abrir)</Label>
                      <Input
                        id="aberta-desde"
                        type="date"
                        className="w-44"
                        value={formData.horario.abertaDesde}
                        onChange={(e) => mudarHorario({ abertaDesde: e.target.value })}
                        data-testid="location-aberta-desde"
                      />
                    </div>
                  </>
                )}
              </div>

              {/* Cerca geográfica */}
```

- [ ] **Passo 7: Correr e ver passar**

O comando do Passo 2. Esperado: `10 passed`. (O ecrã a funcionar no browser vê-se na Tarefa 8.)

- [ ] **Passo 8: Prova por mutação**

1. Em `handleSubmit`, apagar a linha `...formularioParaHorario(formData.horario),`. Esperado **1 failed**: `test_o_formulario_dos_locais_carrega_e_manda_o_horario`. Repor.
2. Na secção nova, apagar o `</>` que fecha o fragmento depois do «Aberta desde». Esperado **1 failed**: `test_o_ecra_dos_locais_compila` (o Babel acusa o JSX). Repor.

`git diff --stat` mostra só `AdminLocations.js` e o ficheiro de teste.

- [ ] **Passo 9: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add frontend/src/pages/admin/AdminLocations.js backend/tests/calendario/test_formularios_do_portal.py
git commit -m "$(cat <<'EOF'
Locais: o formulário ganha o horário da loja, os dias diferentes e a data de abertura

O dono decidiu que o horário vive nos Locais: um horário para todos os dias, um
horário diferente em certos dias (o domingo de Belém), os dias em que fecha e,
para uma loja a abrir, desde quando abre. O formulário carrega o que está gravado
e manda sempre os dois campos; a tabela mostra o resumo; um 422 aparece como
texto em vez de desmontar a página.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Tarefa 7: Formulário das Escalas — loja e horas de cada dia marcado

**Ficheiros:**
- Modificar: `frontend/src/pages/admin/AdminSchedules.js` (imports 3 e 19, estado 41-52, `fetchData` 66-82, `handleEditTemplate`/`handleCancelEdit` 94-102, `handleSubmitTemplate` 104-140, formulário 224-267, tabela 203-207 e 388-392)
- Testes: `backend/tests/calendario/test_formularios_do_portal.py` (acrescentar no fim)

**Interfaces:**
- Consome: `formularioParaDias`, `diasParaFormulario`, `resumoDosDias` (Tarefa 5); `getLocations` de `frontend/src/lib/api.js:13`; `detalhesErro` de `frontend/src/lib/faturacao.js`; `POST`/`PUT /api/schedules` com `dias` (Tarefa 4).
- Produz: `templateForm.porDia` (`{ [dia]: { location_id, inicio, fim } }`); o corpo `{ name, workDays, startTime, dias }` igual no criar e no editar; `data-testid`s `schedule-days-detail`, `schedule-day-loja-<dia>`, `schedule-day-inicio-<dia>`, `schedule-day-fim-<dia>`, `schedule-dias-<id>`.

- [ ] **Passo 1: Escrever os testes que falham**

No fim de `backend/tests/calendario/test_formularios_do_portal.py`, acrescentar:

```python
def test_o_formulario_das_escalas_carrega_e_manda_os_dias():
    texto = _ESCALAS.read_text(encoding="utf-8")
    # Ao editar, a loja e as horas de cada dia vão para o formulário…
    assert "porDia: diasParaFormulario(template.dias)," in texto
    # …e o MESMO corpo, com `dias` dos dias marcados, vai no criar e no editar.
    assert "dias: formularioParaDias(templateForm.workDays, templateForm.porDia)," in texto
    assert "await updateSchedule(editingTemplate.id, corpo);" in texto
    assert "await createSchedule(corpo);" in texto
    # A «Hora de início» continua lá: é o que o lembrete do ponto lê.
    assert "startTime: templateForm.startTime || null," in texto
    assert "toast.error(detalhesErro(error, 'Erro ao guardar escala').mensagem);" in texto
    # O seletor da loja só oferece lojas com horário (uma entrada noutra loja não conta
    # no calendário), mas não esconde a que já está escolhida.
    assert "locations.filter((loc) => loc.horario || loc.id === d.location_id).map((loc) => (" in texto


def test_o_ecra_das_escalas_compila():
    _compila(_ESCALAS)
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_formularios_do_portal.py -q -rs
```

Esperado: `1 failed, 11 passed` — `test_o_formulario_das_escalas_carrega_e_manda_os_dias`.

- [ ] **Passo 3: Implementação — imports, estado e leitura**

Em `frontend/src/pages/admin/AdminSchedules.js`, trocar

```js
import { getEmployees, getSchedules, createSchedule, updateSchedule, deleteSchedule, getScheduleAssignments, assignSchedule, deleteScheduleAssignment } from '../../lib/api';
```

por

```js
import { getEmployees, getLocations, getSchedules, createSchedule, updateSchedule, deleteSchedule, getScheduleAssignments, assignSchedule, deleteScheduleAssignment } from '../../lib/api';
```

Trocar

```js
import { toast } from 'sonner';
```

por

```js
import { toast } from 'sonner';
import { formularioParaDias, diasParaFormulario, resumoDosDias } from '../../lib/horarios';
import { detalhesErro } from '../../lib/faturacao';
```

Trocar

```js
  const [employees, setEmployees] = useState([]);
```

por

```js
  const [employees, setEmployees] = useState([]);
  const [locations, setLocations] = useState([]);
```

Trocar

```js
  const [templateForm, setTemplateForm] = useState({
    name: '',
    workDays: [0, 1, 2, 3, 4],
    startTime: ''
  });
```

por

```js
  const [templateForm, setTemplateForm] = useState({
    name: '',
    workDays: [0, 1, 2, 3, 4],
    startTime: '',
    porDia: {},
  });
```

Trocar

```js
      const [templatesRes, assignmentsRes, employeesRes] = await Promise.all([
        getSchedules(),
        getScheduleAssignments(),
        getEmployees({ company_id: selectedCompany?.id })
      ]);
      setTemplates(templatesRes.data);
      setAssignments(assignmentsRes.data);
      setEmployees(employeesRes.data);
```

por

```js
      const [templatesRes, assignmentsRes, employeesRes, locationsRes] = await Promise.all([
        getSchedules(),
        getScheduleAssignments(),
        getEmployees({ company_id: selectedCompany?.id }),
        // Todas as lojas, de todas as empresas: a mesma pessoa pode estar em lojas de empresas diferentes.
        getLocations()
      ]);
      setTemplates(templatesRes.data);
      setAssignments(assignmentsRes.data);
      setEmployees(employeesRes.data);
      setLocations(locationsRes.data);
```

- [ ] **Passo 4: Implementação — editar, cancelar e mudar um dia**

Trocar

```js
    setTemplateForm({ name: template.name, workDays: [...(template.work_days || [])], startTime: template.start_time || '' });
  };

  const handleCancelEdit = () => {
    setEditingTemplate(null);
    setTemplateForm({ name: '', workDays: [0, 1, 2, 3, 4], startTime: '' });
  };
```

por

```js
    setTemplateForm({
      name: template.name,
      workDays: [...(template.work_days || [])],
      startTime: template.start_time || '',
      porDia: diasParaFormulario(template.dias),
    });
  };

  const handleCancelEdit = () => {
    setEditingTemplate(null);
    setTemplateForm({ name: '', workDays: [0, 1, 2, 3, 4], startTime: '', porDia: {} });
  };

  // Loja e horas de um dia da escala; o que esse dia ainda não tinha começa vazio.
  const handleChangeDia = (dia, mudanca) =>
    setTemplateForm((prev) => ({
      ...prev,
      porDia: {
        ...prev.porDia,
        [dia]: { location_id: '', inicio: '', fim: '', ...prev.porDia[dia], ...mudanca },
      },
    }));
```

- [ ] **Passo 5: Implementação — o mesmo corpo no criar e no editar**

Em `handleSubmitTemplate`, trocar

```js
    setSavingTemplate(true);
    try {
      if (editingTemplate) {
        await updateSchedule(editingTemplate.id, {
          name: templateForm.name,
          workDays: templateForm.workDays,
          startTime: templateForm.startTime || null
        });
        toast.success('Escala atualizada com sucesso');
        handleCancelEdit();
      } else {
        const response = await createSchedule({
          name: templateForm.name,
          workDays: templateForm.workDays,
          startTime: templateForm.startTime || null
        });
        toast.success('Escala criada com sucesso');
        setTemplates((prev) => [response.data, ...prev]);
        setTemplateForm({ name: '', workDays: templateForm.workDays, startTime: templateForm.startTime });
      }
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao guardar escala');
    } finally {
```

por

```js
    // O mesmo corpo no criar e no editar. `dias` leva uma entrada por dia marcado
    // (loja e horas); o servidor deriva o work_days daqui, e o workDays vai igual.
    const corpo = {
      name: templateForm.name,
      workDays: templateForm.workDays,
      startTime: templateForm.startTime || null,
      dias: formularioParaDias(templateForm.workDays, templateForm.porDia),
    };
    setSavingTemplate(true);
    try {
      if (editingTemplate) {
        await updateSchedule(editingTemplate.id, corpo);
        toast.success('Escala atualizada com sucesso');
        handleCancelEdit();
      } else {
        const response = await createSchedule(corpo);
        toast.success('Escala criada com sucesso');
        setTemplates((prev) => [response.data, ...prev]);
        setTemplateForm({ ...templateForm, name: '' });
      }
      fetchData();
    } catch (error) {
      toast.error(detalhesErro(error, 'Erro ao guardar escala').mensagem);
    } finally {
```

- [ ] **Passo 6: Implementação — o formulário e a tabela**

Trocar

```js
            <CardDescription>Defina os dias trabalhados no ciclo semanal.</CardDescription>
```

por

```js
            <CardDescription>Defina os dias trabalhados no ciclo semanal e, em cada dia, a loja e as horas.</CardDescription>
```

Trocar

```js
              <div className="space-y-2">
                <Label htmlFor="schedule-start-time">Hora de início (opcional)</Label>
```

por

```js
              {templateForm.workDays.length > 0 && (
                <div className="space-y-2" data-testid="schedule-days-detail">
                  <Label>Loja e horas de cada dia</Label>
                  <p className="text-xs text-muted-foreground">
                    Loja da ficha = a loja da ficha do colaborador. Horas vazias = o horário da loja nesse dia.
                  </p>
                  {[...templateForm.workDays].sort((a, b) => a - b).map((dia) => {
                    const d = templateForm.porDia[dia] || { location_id: '', inicio: '', fim: '' };
                    const nome = weekDays[dia].label;
                    return (
                      <div key={dia} className="flex flex-wrap items-center gap-2" data-testid={`schedule-day-detail-${dia}`}>
                        <span className="w-10 text-sm font-medium">{nome}</span>
                        <select
                          value={d.location_id}
                          onChange={(e) => handleChangeDia(dia, { location_id: e.target.value })}
                          className="h-9 min-w-[10rem] flex-1 rounded-md border border-input bg-background px-2 text-sm"
                          aria-label={`Loja de ${nome}`}
                          data-testid={`schedule-day-loja-${dia}`}
                        >
                          <option value="">Loja da ficha</option>
                          {/* Só lojas com horário: numa loja sem horário (Pizzaria, escritórios) a
                              entrada não conta no calendário. A já escolhida fica, para não se perder. */}
                          {locations.filter((loc) => loc.horario || loc.id === d.location_id).map((loc) => (
                            <option key={loc.id} value={loc.id}>{loc.name}</option>
                          ))}
                        </select>
                        <Input
                          type="time"
                          value={d.inicio}
                          onChange={(e) => handleChangeDia(dia, { inicio: e.target.value })}
                          className="w-28"
                          aria-label={`${nome}: entra`}
                          data-testid={`schedule-day-inicio-${dia}`}
                        />
                        <Input
                          type="time"
                          value={d.fim}
                          onChange={(e) => handleChangeDia(dia, { fim: e.target.value })}
                          className="w-28"
                          aria-label={`${nome}: sai`}
                          data-testid={`schedule-day-fim-${dia}`}
                        />
                      </div>
                    );
                  })}
                </div>
              )}
              <div className="space-y-2">
                <Label htmlFor="schedule-start-time">Hora de início (opcional)</Label>
```

Trocar

```js
  const assignmentRows = useMemo(() => {
```

por

```js
  const nomeDaLoja = (id) => locations.find((loc) => loc.id === id)?.name;

  const assignmentRows = useMemo(() => {
```

Trocar

```js
                        {formatWorkDays(template.work_days)}
                        {template.start_time ? ` · início ${template.start_time}` : ''}
```

por

```js
                        {formatWorkDays(template.work_days)}
                        {template.start_time ? ` · início ${template.start_time}` : ''}
                        {template.dias?.length > 0 && (
                          <div className="text-xs text-muted-foreground" data-testid={`schedule-dias-${template.id}`}>
                            {resumoDosDias(template.dias, nomeDaLoja)}
                          </div>
                        )}
```

- [ ] **Passo 7: Correr e ver passar**

O comando do Passo 2. Esperado: `12 passed`.

- [ ] **Passo 8: Prova por mutação**

1. No `corpo`, apagar a linha `dias: formularioParaDias(templateForm.workDays, templateForm.porDia),`. Esperado **1 failed**: `test_o_formulario_das_escalas_carrega_e_manda_os_dias`. Repor.
2. Trocar `await updateSchedule(editingTemplate.id, corpo);` por `await updateSchedule(editingTemplate.id, { name: templateForm.name, workDays: templateForm.workDays });` (a forma antiga, que perde os dias). Esperado **1 failed**, o mesmo teste. Repor.
3. Apagar o `)}` que fecha o bloco `templateForm.workDays.length > 0 && (`. Esperado **1 failed**: `test_o_ecra_das_escalas_compila`. Repor.
4. Trocar `locations.filter((loc) => loc.horario || loc.id === d.location_id).map((loc) => (` por `locations.map((loc) => (` (o seletor volta a mostrar a Pizzaria e os escritórios). Esperado **1 failed**: `test_o_formulario_das_escalas_carrega_e_manda_os_dias`. Repor. (O comportamento no browser vê-se na Tarefa 8, Passo 7.)

Depois, a suite inteira — esperado `passed` = partida + 48, `skipped` igual à partida:

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
export PATH="$HOME/.local/node/bin:$PATH"
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest -q 2>&1 | tail -3
```


- [ ] **Passo 9: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add frontend/src/pages/admin/AdminSchedules.js backend/tests/calendario/test_formularios_do_portal.py
git commit -m "$(cat <<'EOF'
Escalas: cada dia marcado ganha a loja (por omissão a da ficha) e horas opcionais

A escala fixa de cada pessoa passa a viver nas Escalas do RH, com a loja e as
horas de cada dia (decisão do dono: uma escala só). O formulário manda o mesmo
corpo no criar e no editar, com workDays igual aos dias marcados; a «Hora de
início» fica, porque é o que o lembrete do ponto lê; e a tabela mostra o resumo
dos dias.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Tarefa 8: Ensaio local no browser dos dois formulários

Nada versionado muda nesta tarefa. Se algo falhar, a correcção volta à Tarefa 6 ou 7 (teste primeiro) e o ensaio repete-se.

**Ficheiros (só locais, nunca versionados):**
- Criar: `$HOME/.cache/lisbonb-calendario-local/backend.env`, `$HOME/.cache/lisbonb-calendario-local/semear.py`, `frontend/.env.development.local`
- Modificar: `/Users/matheus.moraes/Library/CloudStorage/OneDrive-Pessoal/Claude/.claude/launch.json` (duas entradas novas)

**Interfaces:**
- Consome: as Tarefas 1-7.
- Produz: a base local `rh_calendario_local` (mongod em `127.0.0.1:27031`) com 7 locais, 7 colaboradores, a escala «5x2 (antiga)» da Joana e o que o ensaio gravar — a Tarefa 12 volta a usá-la. Backend local em `127.0.0.1:8031`, frontend em `127.0.0.1:3031`.

- [ ] **Passo 1: O ambiente de ensaio (segredos gerados, nunca mostrados)**

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
sed -E 's/=.*/=<…>/' backend.env     # só os nomes, nunca os valores
```

`frontend/.env.development.local` (o `craco start` lê-o; o `build` não — nunca usar `frontend/.env.local`, que o build também lê):

```
REACT_APP_BACKEND_URL=http://127.0.0.1:8031
BROWSER=none
PORT=3031
HOST=127.0.0.1
```

Confirmar: `cd /Users/matheus.moraes/Developer/RH-calendario && git check-ignore frontend/.env.development.local` (imprime o caminho) e `git status -s` (nada de novo: só, quando muito, os planos por guardar).

- [ ] **Passo 2: O seed do ensaio**

`$HOME/.cache/lisbonb-calendario-local/semear.py`:

```python
"""Dados do ensaio local do calendário (fase 1). SÓ na base local do ensaio.

Lojas sem horário (o horário mete-se pelo formulário, que é o que se ensaia), as 7
pessoas da semana normal e uma escala antiga, sem `dias`, atribuída à Joana desde
1/1 — a forma da produção de hoje."""
import os
import sys
from datetime import datetime, timezone

from pymongo import MongoClient

URL, BASE = os.environ["MONGO_URL"], os.environ["DB_NAME"]
if URL != "mongodb://127.0.0.1:27031" or BASE != "rh_calendario_local":
    sys.exit("Recuso: isto só corre na base local do ensaio (127.0.0.1:27031/rh_calendario_local).")
db = MongoClient(URL, serverSelectionTimeoutMS=3000)[BASE]
if db.companies.find_one({"id": "c-ensaio"}):
    sys.exit("Já estava semeado — nada feito.")
agora = datetime.now(timezone.utc).isoformat()
db.companies.insert_one({"id": "c-ensaio", "name": "L'Açaí (ensaio)", "description": None, "created_at": agora})
LOJAS = {
    "l-alfragide": "L'Açaí Alfragide", "l-algueirao": "L'Açaí Algueirão", "l-amadora": "L'Açaí Amadora",
    "l-belem": "L'Açaí Belém", "l-benfica": "L'Açaí Benfica", "l-oeiras": "L'Açaí Oeiras",
    "l-escritorio": "Escritório (ensaio)",
}
db.locations.insert_many([
    {"id": i, "name": n, "company_id": "c-ensaio", "address": None, "latitude": None, "longitude": None,
     "geofence_radius": None, "google_place_id": None, "created_at": agora}
    for i, n in LOJAS.items()])
PESSOAS = {
    "e-emily": ("Emily Ensaio", "l-alfragide"), "e-beatrice": ("Beatrice Ensaio", "l-alfragide"),
    "e-walisson": ("Walisson Ensaio", "l-algueirao"), "e-joana": ("Joana Ensaio", "l-oeiras"),
    "e-weber": ("Weber Ensaio", "l-amadora"), "e-emanuela": ("Emanuela Ensaio", "l-oeiras"),
    "e-rafaela": ("Rafaela Ensaio", "l-belem"),
}
db.employees.insert_many([
    {"id": i, "user_id": "u-" + i, "name": n, "email": i[2:] + "@example.com", "company_id": "c-ensaio",
     "location_id": loja, "position": "Operadora", "contract_type": "efetivo", "start_date": "2026-01-01",
     "vacation_days": 22, "geofence_exempt": False, "created_at": agora}
    for i, (n, loja) in PESSOAS.items()])
db.work_schedule_templates.insert_one({
    "id": "t-5x2", "name": "5x2 (antiga)", "work_days": [0, 1, 2, 3, 4], "start_time": "13:00", "created_at": agora})
db.work_schedule_assignments.insert_one({
    "id": "a-joana", "employee_id": "e-joana", "template_id": "t-5x2", "work_days": [0, 1, 2, 3, 4],
    "start_date": "2026-01-01", "end_date": None, "created_at": agora})
print("Semeado: 7 locais sem horário, 7 colaboradores, a escala «5x2 (antiga)» atribuída à Joana.")
```

Para ler a base local nos passos seguintes (o mesmo prefixo em todos; mostra só o que se pede):

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend && set -a && . "$HOME/.cache/lisbonb-calendario-local/backend.env" && set +a && ~/Developer/RH/backend/.venv/bin/python - <<'PY'
import os, pprint
from pymongo import MongoClient
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
pprint.pprint(list(db.locations.find({"horario": {"$ne": None}}, {"_id": 0, "name": 1, "horario": 1, "aberta_desde": 1})))
pprint.pprint(list(db.work_schedule_templates.find({}, {"_id": 0, "name": 1, "work_days": 1, "start_time": 1, "dias": 1})))
pprint.pprint(list(db.work_schedule_assignments.find({}, {"_id": 0, "employee_id": 1, "template_id": 1, "work_days": 1, "start_date": 1, "end_date": 1})))
PY
```

- [ ] **Passo 3: As entradas do `launch.json`**

Ler `/Users/matheus.moraes/Library/CloudStorage/OneDrive-Pessoal/Claude/.claude/launch.json` e acrescentar ao array `configurations` (sem mexer nas outras):

```json
    {
      "name": "calendario-backend",
      "runtimeExecutable": "bash",
      "runtimeArgs": ["-c", "cd $HOME/Developer/RH-calendario/backend && exec $HOME/Developer/RH/backend/.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8031 --env-file $HOME/.cache/lisbonb-calendario-local/backend.env"],
      "port": 8031
    },
    {
      "name": "calendario-frontend",
      "runtimeExecutable": "bash",
      "runtimeArgs": ["-c", "export PATH=$HOME/.local/node/bin:$PATH CACHE_DIR=$HOME/.cache/lisbonb-calendario-local/cache DISABLE_ESLINT_PLUGIN=true; cd $HOME/Developer/RH-calendario/frontend && exec ./node_modules/.bin/craco start"],
      "port": 3031,
      "url": "http://127.0.0.1:3031"
    }
```

Validar o JSON: `python3 -m json.tool < /Users/matheus.moraes/Library/CloudStorage/OneDrive-Pessoal/Claude/.claude/launch.json > /dev/null && echo ok`.

Porquê o `CACHE_DIR` e o `DISABLE_ESLINT_PLUGIN`: `frontend/node_modules` é um atalho para `~/Developer/RH/frontend/node_modules`, e o craco grava as caches em `node_modules/.cache`, ou seja, dentro de `~/Developer/RH`. O `CACHE_DIR` tira de lá a cache do Babel, e o `DISABLE_ESLINT_PLUGIN` tira a do ESLint (no ensaio o ESLint não faz falta; o craco escreve então «Cannot find ESLint plugin (ESLintWebpackPlugin).», que é esperado e inofensivo). **Risco aceite:** a cache do webpack do CRA 5 (`node_modules/.cache/default-development`) fica sempre lá, porque o caminho está fixo no `react-scripts`. Está no `.gitignore` e não muda código nenhum; no pior caso a outra sessão perde a cache e o próximo arranque dela demora mais.

- [ ] **Passo 4: Arrancar e semear**

1. O mongod (não é HTTP, por isso vai pela Bash em segundo plano, `run_in_background: true`):
   `/opt/homebrew/bin/mongod --dbpath "$HOME/.cache/lisbonb-calendario-local/mongo" --port 27031 --bind_ip 127.0.0.1 --quiet`
2. O seed: `cd /Users/matheus.moraes/Developer/RH-calendario/backend && set -a && . "$HOME/.cache/lisbonb-calendario-local/backend.env" && set +a && ~/Developer/RH/backend/.venv/bin/python "$HOME/.cache/lisbonb-calendario-local/semear.py"` → «Semeado: …».
3. `preview_start` com `name: "calendario-backend"`; depois `curl -s http://127.0.0.1:8031/api/health` → `healthy`.
4. `preview_start` com `name: "calendario-frontend"` (o primeiro arranque do craco demora 1-2 min; ver `preview_logs` até «Compiled»).
5. No browser: `http://127.0.0.1:3031/login`, entrar com o `ADMIN_EMAIL` e o `ADMIN_PASSWORD` do `backend.env` (valores de teste deste ensaio, lidos do ficheiro — não os escrever no chat). Aterra em `/admin`.

- [ ] **Passo 5: Locais — o caminho feliz**

Em `http://127.0.0.1:3031/admin/locais`:
1. Editar «L'Açaí Belém»: marcar «Esta loja tem horário», Abre 11:30, Fecha 19:00, Ter → «Fechada», Dom → «Outro horário» 11:30–20:00. Guardar → toast «Local atualizado com sucesso».
2. Editar «L'Açaí Benfica»: horário 13:00–22:00 e «Aberta desde» 2026-10-24. Guardar.
3. Reabrir Belém: o formulário mostra exactamente o que se gravou (Ter fechada, Dom 11:30–20:00).
4. Dar horário, só com o horário geral, às outras quatro: Alfragide 10:00–23:00, Algueirão 13:00–22:00, Amadora 14:00–23:00, Oeiras 13:00–22:00 (os do desenho). Sem isto não aparecem no seletor das Escalas (Passo 7).
5. A tabela (largura ≥ 1024 px) mostra na coluna «Horário»: `11:30–19:00 · Dom 11:30–20:00 · fecha Ter`, `13:00–22:00 · abre a 2026-10-24` e as quatro só com as horas; «Escritório (ensaio)» mostra `—`.
6. Ler a base (comando do Passo 2): Belém tem `horario` igual a `{"abre": "11:30", "fecha": "19:00", "excecoes": [{"dia": 6, "abre": "11:30", "fecha": "20:00"}], "fechada": [1]}` e `aberta_desde: None`; Benfica `aberta_desde: '2026-10-24'`; Alfragide `{"abre": "10:00", "fecha": "23:00", "excecoes": [], "fechada": []}`. «Escritório (ensaio)» não aparece (não tem horário).

- [ ] **Passo 6: Locais — erros e a página antiga**

1. Abrir Belém, pôr Abre 19:00 e Fecha 10:00, Guardar → toast «A loja tem de abrir antes de fechar (19:00–10:00)»; o diálogo fica aberto e a página não desmonta. Cancelar.
2. A página antiga, a sério: na consola do browser (`javascript_tool`), um PUT sem os campos novos, com o token da sessão do ensaio:

```js
await fetch('http://127.0.0.1:8031/api/locations/l-belem', {
  method: 'PUT',
  headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + localStorage.getItem('token') },
  body: JSON.stringify({ name: "L'Açaí Belém", company_id: 'c-ensaio' }),
}).then((r) => r.status)
```

   → `200`. Ler a base: o `horario` de Belém continua igual ao do Passo 5.
3. Desmarcar «Esta loja tem horário» no Benfica e Guardar → na base, `horario: None` e `aberta_desde: None` (tirar funciona). Voltar a pôr 13:00–22:00 e 2026-10-24.

- [ ] **Passo 7: Escalas**

Em `http://127.0.0.1:3031/admin/escalas`:
0. Abrir o seletor da loja de um dia: tem «Loja da ficha» e as 6 lojas com horário, e **não** tem «Escritório (ensaio)».
1. Criar «Escala Emily»: dias Seg, Ter, Sex, Sáb, Dom; em cada dia a loja «L'Açaí Alfragide» e 14:00–23:00; «Hora de início» vazia. Guardar → «Escala criada com sucesso»; a tabela mostra por baixo dos dias `Seg L'Açaí Alfragide 14:00–23:00 · Ter …`.
2. Atribuir «Escala Emily» à «Emily Ensaio» desde 2026-10-01 → no Histórico, «Seg, Ter, Sex, Sáb, Dom».
3. Criar «Escala Joana»: Seg a Sex; Seg e Ter «L'Açaí Amadora», Qua «L'Açaí Oeiras», Qui e Sex «L'Açaí Algueirão», sem horas; «Hora de início» 13:00. Guardar. Depois editar: os dias vêm com as lojas certas; desmarcar Sex e Guardar.
4. Ler a base: «Escala Emily» tem `work_days [0, 1, 4, 5, 6]` e 5 entradas em `dias` com `inicio '14:00'`/`fim '23:00'`; a atribuição dela tem `work_days [0, 1, 4, 5, 6]`; «Escala Joana» tem `work_days [0, 1, 2, 3]`, `start_time '13:00'` e 4 entradas em `dias`.
5. Erro: editar «Escala Joana», pôr só a hora de entrada de Seg (08:00) e Guardar → toast «As horas de um dia escrevem-se as duas (entrada e saída) ou nenhuma». Cancelar.
6. A escala antiga: editar «5x2 (antiga)» → os 5 dias aparecem todos com «Loja da ficha» e sem horas. Cancelar (não gravar).

- [ ] **Passo 8: Telemóvel (375 px), claro e escuro**

1. `resize_window` com `preset: "mobile"`, recarregar; abrir `/admin/locais`, editar Belém. No `javascript_tool`: `document.documentElement.scrollWidth <= window.innerWidth` → `true` (sem deslocamento para o lado); os dias com «Outro horário» passam as horas para a linha de baixo sem sair do diálogo. Captura de ecrã.
2. O mesmo em `/admin/escalas` com «Escala Joana» em edição. Captura.
3. `resize_window` com `colorScheme: "dark"`; repetir 1 e 2: os `<select>` nativos legíveis (fundo `bg-background`), nada branco sobre branco. Capturas.
4. `resize_window` com `preset: "desktop"` e `colorScheme: "light"` no fim.

- [ ] **Passo 9: Consola e arrumar**

1. `read_console_messages` com `onlyErrors: true` → nenhum erro (os 422 do Passo 6.1 e 7.5 aparecem só como pedidos de rede falhados, previstos).
2. `preview_stop` dos dois servidores; parar o mongod: `pkill -f "mongod --dbpath $HOME/.cache/lisbonb-calendario-local/mongo"`. A pasta `mongo/` fica (a Tarefa 12 usa-a).
3. `cd /Users/matheus.moraes/Developer/RH-calendario && git status -s` → nada de novo (o ensaio não deixa ficheiros na árvore).

---

### Tarefa 9: Publicar (fluxo B, com o «sim» do dono) e confirmar o que ficou no ar

Acções externas: push para o GitHub, merge no `main` e deploy. **Nenhum destes passos corre sem um «sim» claro do dono no chat.** O `main` está aberto noutro worktree (`~/Developer/RH-qr-aplicacoes`), por isso o merge faz-se num worktree temporário, desligado, a partir de `origin/main` — sem tocar em `~/Developer/RH` nem nesse worktree.

**Ficheiros:** nenhum versionado. Temporários: `/private/tmp/rh-publicar-calendario` (worktree, removido no fim), `$HOME/.cache/lisbonb-calendario-local/build` (build local).

**Interfaces:**
- Consome: os commits das Tarefas 1-7.
- Produz: `main` no GitHub com o ramo juntado; produção a servir o bundle novo (marcadores `location-horario-tem` e `schedule-day-loja-`) e o `server.py` novo (`_horario_para_gravar`).

- [ ] **Passo 1: Suite inteira e build local**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
export PATH="$HOME/.local/node/bin:$PATH"
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest -q 2>&1 | tail -3
```

Esperado: `passed` = partida + 48, `skipped` = partida, `0 failed`.

```bash
export PATH="$HOME/.local/node/bin:$PATH"
cd /Users/matheus.moraes/Developer/RH-calendario/frontend
CI=false REACT_APP_BACKEND_URL="" BUILD_PATH="$HOME/.cache/lisbonb-calendario-local/build" CACHE_DIR="$HOME/.cache/lisbonb-calendario-local/cache" ./node_modules/.bin/craco build 2>&1 | tail -5
grep -l "location-horario-tem" "$HOME/.cache/lisbonb-calendario-local/build/static/js/"main.*.js
grep -l "schedule-day-loja-" "$HOME/.cache/lisbonb-calendario-local/build/static/js/"main.*.js
```

Esperado: «Compiled successfully» (ou «Compiled with warnings» sem erros) e os dois `grep` a mostrar o `main.*.js`. Marcadores sem acentos de propósito: o build escreve os acentos noutra codificação e um `grep` por «Horário» dá falso negativo.

Sem o `export PATH`, o `craco` (`#!/usr/bin/env node`) falha com «env: node: No such file or directory». O `CACHE_DIR` tira a cache do Babel de `~/Developer/RH` (o atalho de `node_modules`). Aqui o ESLint fica **ligado** de propósito (sem `DISABLE_ESLINT_PLUGIN`, ao contrário do ensaio): o `yarn build` do servidor corre-o e falha com um erro dele, por isso este build é a mesma porta, antes do deploy. Os dois ficheiros de cache que ficam em `node_modules/.cache` (o do webpack e o `.eslintcache`) são o risco aceite da Tarefa 8, Passo 3.

- [ ] **Passo 2: Pedir o «sim» ao dono**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git fetch origin
git log --oneline origin/main..HEAD
git diff --stat origin/main...HEAD
ANTES=$(curl -s https://lisbonb.com/admin/locais | grep -oE '/static/js/main\.[a-z0-9]+\.js' | head -1); echo "$ANTES"
```

Mostrar ao dono, em linguagem simples: o ramo, os commits, os ficheiros, o que muda para quem usa (Locais com horário; Escalas com loja e horas por dia; nada muda no ponto, no saldo de férias nem no painel) e que se segue o script de arranque (Tarefas 10-12). Anotar o `$ANTES`.

No mesmo pedido, as duas datas que o script precisa (para ele correr uma só vez na Tarefa 12):

1. **`DESDE`, o primeiro dia das escalas novas.** O saldo de férias não fica guardado: é recalculado a cada leitura (`calculate_leave_counted_days`, chamada em `server.py:927`, `:2426`, `:3135`, `:3190`), a partir do `work_days` da atribuição que cobre cada dia. Por isso:
   - **01/10/2026** (o valor por omissão do script): é retroactivo. As férias destas pessoas de 01/10 em diante, incluindo as já gozadas, passam logo a contar pelos dias novos, e o saldo muda no dia em que o script corre. Exemplo: a Rafaela deixa de gastar dias de férias às terças. O mesmo vale para qualquer pessoa cuja escala antiga tenha outros dias.
   - **A próxima segunda-feira**: nada muda para trás. O que já passou continua a contar pela escala antiga, e no calendário da Fase 2 os dias antes dessa data aparecem com a escala antiga (loja da ficha e horário da loja).
   - Ou outra data que o dono escolha.
2. **`BENFICA_DESDE`, o dia em que Benfica abre** (o desenho dá o exemplo de `2026-10-24` e põe Benfica aberta na semana de 26/10). Se o dono ainda não souber, Benfica fica de fora e entra mais tarde (Tarefa 12, Passo 5).

Anotar as duas respostas: entram como `-e DESDE=…` e `-e BENFICA_DESDE=…` nos comandos da Tarefa 12. **Parar aqui até haver um «sim».**

- [ ] **Passo 3: Enviar o ramo e juntar ao `main`**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git push -u origin matheus-calendario-gestao
git fetch origin
git log --oneline 57d5f6f..origin/main     # vazio = ninguém juntou nada desde que o ramo saiu
git worktree add --detach /private/tmp/rh-publicar-calendario origin/main
cd /private/tmp/rh-publicar-calendario
git merge --no-ff matheus-calendario-gestao \
  -m "merge: Locais com horário e Escalas com loja e horas por dia (calendário das lojas, fase 1)" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- Se o merge tiver **conflitos**: parar, `git merge --abort`, explicar ao dono que ficheiros chocam e resolver com ele. Nunca forçar.
- Se o `git log 57d5f6f..origin/main` **não** vier vazio, correr a suite no worktree temporário antes do push: `export PATH="$HOME/.local/node/bin:$PATH" && ln -sfn ~/Developer/RH/frontend/node_modules frontend/node_modules && cd backend && PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest -q 2>&1 | tail -3` (0 failed; o `skipped` igual) e depois `rm /private/tmp/rh-publicar-calendario/frontend/node_modules`.

```bash
cd /private/tmp/rh-publicar-calendario
git push origin HEAD:main
cd /Users/matheus.moraes/Developer/RH-calendario
git worktree remove /private/tmp/rh-publicar-calendario
```

Se o push for recusado (alguém juntou entretanto): `git worktree remove --force /private/tmp/rh-publicar-calendario` e repetir este passo desde o `git fetch origin`.

- [ ] **Passo 4: Deploy (só o `main`)**

```bash
ssh root@187.124.4.163 'cd ~/RH && git checkout main && git pull && docker compose up -d --build'
curl -s https://lisbonb.com/api/health
```

Esperado: `healthy`.

- [ ] **Passo 5: Confirmar o ficheiro servido (o deploy já entregou código antigo a dizer «concluído»)**

```bash
JS=$(curl -s https://lisbonb.com/admin/locais | grep -oE '/static/js/main\.[a-z0-9]+\.js' | head -1); echo "$JS"
curl -s "https://lisbonb.com$JS" | grep -c "location-horario-tem"
curl -s "https://lisbonb.com$JS" | grep -c "schedule-day-loja-"
ssh root@187.124.4.163 'cd ~/RH && git log --oneline -1 && docker compose exec -T backend grep -c "_horario_para_gravar" server.py'
```

Esperado: `$JS` diferente do `$ANTES`; os dois `grep -c` ≥ 1; o `git log` no commit de merge; o `grep` do backend ≥ 2.

Se o nome do bundle não mudou ou os dois `grep -c` do bundle dão 0:

```bash
ssh root@187.124.4.163 'cd ~/RH && docker compose build --no-cache frontend && docker compose up -d frontend'
```

e repetir este passo.

Se o `grep -c "_horario_para_gravar"` no contentor dá 0 (o backend antigo, servido pela cache do `COPY` do Docker; já aconteceu com os pontos no POS a 23/09):

```bash
ssh root@187.124.4.163 'cd ~/RH && docker compose build --no-cache backend && docker compose up -d backend'
curl -s https://lisbonb.com/api/health
```

e repetir este passo.

- [ ] **Passo 6: Dizer ao dono o que verificar já (sem gravar nada)**

No portal (`https://lisbonb.com/admin/locais` e `/admin/escalas`), com o browser recarregado: abrir uma loja → aparece a secção «Horário da loja» → Cancelar; editar uma escala → aparece «Loja e horas de cada dia» com «Loja da ficha» em todos os dias → Cancelar. Até o script correr, nenhuma loja tem horário, por isso o seletor da loja só tem «Loja da ficha»: é o esperado. O horário e as escalas a sério entram pelo script (Tarefas 10-12), e o caminho feliz com gravação faz-se no fim da Tarefa 12, sobre esses dados.

---

### Tarefa 10: Script de arranque — o horário das 6 lojas

O script corre **dentro do contentor do backend em produção, lido do stdin**, pela mão do dono (o assistente não chega à base de produção). Por isso: só pymongo e a biblioteca padrão; ensaio por omissão; lê tudo e decide tudo antes da primeira escrita; pára em qualquer ambiguidade; nunca apaga. Esta tarefa faz as lojas; a Tarefa 11 acrescenta as escalas.

**Ficheiros:**
- Criar: `backend/arranque_calendario.py`
- Testes: `backend/tests/calendario/test_arranque_do_calendario.py` (criar)

**Interfaces:**
- Consome: a forma de `horario`/`aberta_desde` validada por `server.HorarioLoja` (Tarefa 1); fixture `mongod_porta` (Tarefa 2).
- Produz (em `arranque_calendario`):
  - `HORARIOS: dict` (chave = nome a procurar nos Locais → horário)
  - `PROCURAR: dict` (chave curta → nome mais comprido a procurar quando a chave é ambígua em produção; vazio por omissão; o `main()` junta-lhe o `PROCURAR_JSON`)
  - `class Paragem(Exception)`
  - `_normal(texto) -> str`, `_um(docs, chave, o_que) -> dict`, `_resumo_horario(h) -> str`
  - `_planear_lojas(lojas, benfica_desde, linhas, ops) -> dict` (`{chave: location_id}` das lojas tratadas)
  - `planear(db, desde: date, benfica_desde: Optional[date]) -> (linhas: list[str], ops: list[tuple])` — cada op é `(colecao, "insert_one"|"update_one"|"update_many", *argumentos)`
  - `aplicar(db, ops) -> None`, `main() -> int` (0 = feito/ensaio, 1 = parado)
  - variáveis de ambiente lidas: `MONGO_URL`, `DB_NAME`, `GRAVAR` (`"1"` grava), `DESDE` (`AAAA-MM-DD`, por omissão `2026-10-01`), `BENFICA_DESDE` (`AAAA-MM-DD`, sem ela Benfica salta), `PROCURAR_JSON` (um objecto JSON que se junta ao `PROCURAR`, para desfazer uma ambiguidade de produção sem mudar o ficheiro)

- [ ] **Passo 1: Escrever os testes que falham**

`backend/tests/calendario/test_arranque_do_calendario.py`:

```python
"""O script de arranque do calendário (backend/arranque_calendario.py), contra um mongod
real com a forma da produção: lojas com o nome da marca à frente, uma pizzaria e um
escritório que não entram, e uma escala antiga atribuída à Joana.

O que se prende: o ensaio não escreve nada; GRAVAR=1 escreve o que o ensaio mostrou;
uma ambiguidade pára tudo ANTES da primeira escrita; nunca se apaga; correr outra vez
não reescreve; e o que o script escreve passa na validação do servidor.
"""
import json
from datetime import date

import pytest
from pymongo import MongoClient

import arranque_calendario as arranque
import server

BASE = "teste_arranque"
COLECOES = ("locations", "employees", "work_schedule_templates", "work_schedule_assignments")
LOJAS = {
    "l-alf": "L'Açaí Alfragide", "l-alg": "L'Açaí Algueirão", "l-ama": "L'Açaí Amadora",
    "l-bel": "L'Açaí Belém", "l-ben": "L'Açaí Benfica", "l-oei": "L'Açaí Oeiras",
    "l-piz": "Pizzaria Lenha e Brasa", "l-esc": "Escritório Central",
}
PESSOAS = {
    "e-emi": ("Emily Santos", "l-alf"), "e-bea": ("Beatrice Lima", "l-alf"),
    "e-wal": ("Walisson Costa", "l-alg"), "e-joa": ("Joana Pereira", "l-oei"),
    "e-web": ("Weber Souza", "l-ama"), "e-ema": ("Emanuela Rocha", "l-oei"),
    "e-raf": ("Rafaela Dias", "l-bel"), "e-car": ("Carolina Mendes", None),
}


@pytest.fixture
def prod(mongod_porta, monkeypatch):
    """Uma base com a forma da produção, e o ambiente do contentor a apontar para ela."""
    url = "mongodb://127.0.0.1:%d" % mongod_porta
    cliente = MongoClient(url)
    cliente.drop_database(BASE)
    db = cliente[BASE]
    db.locations.insert_many([{"id": i, "name": n, "company_id": "c1"} for i, n in LOJAS.items()])
    db.employees.insert_many([{"id": i, "name": n, "location_id": loja} for i, (n, loja) in PESSOAS.items()])
    db.work_schedule_templates.insert_one({
        "id": "t-5x2", "name": "5x2", "work_days": [0, 1, 2, 3, 4], "start_time": "13:00",
        "created_at": "2026-01-01T00:00:00+00:00"})
    db.work_schedule_assignments.insert_one({
        "id": "a-joa", "employee_id": "e-joa", "template_id": "t-5x2", "work_days": [0, 1, 2, 3, 4],
        "start_date": "2026-01-01", "end_date": None, "created_at": "2026-01-01T00:00:00+00:00"})
    monkeypatch.setenv("MONGO_URL", url)
    monkeypatch.setenv("DB_NAME", BASE)
    for nome in ("GRAVAR", "DESDE", "BENFICA_DESDE", "PROCURAR_JSON"):
        monkeypatch.delenv(nome, raising=False)
    # Os nomes desta base são os do teste: o PROCURAR real (nomes de produção) fica de fora.
    monkeypatch.setattr(arranque, "PROCURAR", {})
    yield db
    cliente.close()


def _tudo(db):
    return {c: sorted(db[c].find({}, {"_id": 0}), key=lambda d: d["id"]) for c in COLECOES}


def test_o_ensaio_mostra_tudo_e_nao_escreve_nada(prod, capsys):
    antes = _tudo(prod)
    assert arranque.main() == 0
    saida = capsys.readouterr().out
    assert "Loja L'Açaí Belém: sem horário → 11:30–19:00 · Dom 11:30–20:00 · fecha Ter" in saida
    assert "Loja L'Açaí Alfragide: sem horário → 10:00–23:00" in saida
    assert "Loja Benfica: SALTADA — falta BENFICA_DESDE" in saida
    assert "ENSAIO:" in saida and "nada foi escrito" in saida
    assert _tudo(prod) == antes


def test_com_gravar_as_cinco_lojas_ficam_com_horario_e_o_resto_como_estava(prod, monkeypatch):
    monkeypatch.setenv("GRAVAR", "1")
    assert arranque.main() == 0
    horario = {d["id"]: d.get("horario") for d in prod.locations.find({}, {"_id": 0})}
    assert horario["l-bel"] == arranque.HORARIOS["Belém"]
    assert horario["l-alf"] == {"abre": "10:00", "fecha": "23:00", "excecoes": [], "fechada": []}
    assert horario["l-ama"]["abre"] == "14:00" and horario["l-oei"]["abre"] == "13:00"
    assert horario["l-ben"] is None                      # sem BENFICA_DESDE
    assert horario["l-piz"] is None and horario["l-esc"] is None


def test_benfica_entra_com_o_dia_em_que_abre(prod, monkeypatch):
    monkeypatch.setenv("GRAVAR", "1")
    monkeypatch.setenv("BENFICA_DESDE", "2026-10-24")
    assert arranque.main() == 0
    benfica = prod.locations.find_one({"id": "l-ben"}, {"_id": 0})
    assert benfica["horario"] == arranque.HORARIOS["Benfica"]
    assert benfica["aberta_desde"] == "2026-10-24"


def test_um_nome_que_casa_com_duas_lojas_para_tudo_antes_de_escrever(prod, monkeypatch, capsys):
    prod.locations.insert_one({"id": "l-oei2", "name": "Oeiras Parque (quiosque)", "company_id": "c1"})
    antes = _tudo(prod)
    monkeypatch.setenv("GRAVAR", "1")
    assert arranque.main() == 1
    assert "PARADO, nada foi escrito: A loja «Oeiras» casa com 2" in capsys.readouterr().out
    assert _tudo(prod) == antes        # nem Alfragide, que vem antes de Oeiras, foi escrita


def test_procurar_desfaz_a_ambiguidade_de_uma_loja(prod, monkeypatch):
    prod.locations.insert_one({"id": "l-oei2", "name": "Oeiras Parque (quiosque)", "company_id": "c1"})
    # Como o dono o faz em produção, sem mudar o ficheiro: -e PROCURAR_JSON='{"Oeiras": "Acai Oeiras"}'
    monkeypatch.setenv("PROCURAR_JSON", json.dumps({"Oeiras": "Acai Oeiras"}))
    monkeypatch.setenv("GRAVAR", "1")
    assert arranque.main() == 0
    assert prod.locations.find_one({"id": "l-oei"})["horario"]["abre"] == "13:00"
    assert prod.locations.find_one({"id": "l-oei2"}).get("horario") is None


def test_uma_data_invalida_para(prod, monkeypatch, capsys):
    monkeypatch.setenv("BENFICA_DESDE", "2026-02-30")
    assert arranque.main() == 1
    assert "data inválida" in capsys.readouterr().out


def test_correr_outra_vez_nao_reescreve_nada(prod, monkeypatch, capsys):
    monkeypatch.setenv("GRAVAR", "1")
    assert arranque.main() == 0
    depois_da_primeira = _tudo(prod)
    capsys.readouterr()
    assert arranque.main() == 0
    assert "GRAVADO: 0 escritas." in capsys.readouterr().out
    assert _tudo(prod) == depois_da_primeira


def test_o_script_nunca_apaga(prod):
    _, ops = arranque.planear(prod, date(2026, 10, 1), date(2026, 10, 24))
    assert ops
    assert {op[1] for op in ops} <= {"insert_one", "update_one", "update_many"}


def test_os_horarios_do_script_passam_na_validacao_do_servidor():
    for horario in arranque.HORARIOS.values():
        assert server.HorarioLoja.model_validate(horario).model_dump() == horario
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_arranque_do_calendario.py -q
```

Esperado: erro de colecção, `ModuleNotFoundError: No module named 'arranque_calendario'`.

- [ ] **Passo 3: Implementação mínima**

`backend/arranque_calendario.py`:

```python
"""Arranque do calendário das lojas, fase 1 — corre UMA vez, pelo dono, em produção.

Põe o horário nas 6 lojas e uma escala por pessoa às 7 da semana normal, tal como o
dono as descreveu (docs/superpowers/specs/2026-10-14-calendario-gestao-design.md,
«A semana normal» e «Entrega por fases»).

- Por omissão é um ENSAIO: mostra tudo o que faria e não escreve nada. Só grava com
  GRAVAR=1.
- Lê tudo e decide tudo ANTES da primeira escrita: se um nome casar com mais de uma
  loja/pessoa (ou com nenhuma), PÁRA sem ter escrito nada.
- Nunca apaga. Uma escala antiga fecha-se (end_date na véspera de DESDE) e cria-se
  uma nova a partir de DESDE.
- Pode correr-se outra vez: o que já está como devia não se reescreve.

Só usa pymongo e a biblioteca padrão; corre dentro do contentor do backend, lido do
stdin, com o MONGO_URL e o DB_NAME do próprio contentor:

    ssh root@187.124.4.163 "cd ~/RH && docker compose exec -T backend python -" < backend/arranque_calendario.py
    ssh root@187.124.4.163 "cd ~/RH && docker compose exec -T -e GRAVAR=1 backend python -" < backend/arranque_calendario.py

Variáveis opcionais: DESDE=AAAA-MM-DD (por omissão 2026-10-01), o primeiro dia das
escalas novas; BENFICA_DESDE=AAAA-MM-DD, o dia em que Benfica abre — sem ela, Benfica
fica de fora e o script di-lo; PROCURAR_JSON='{"Joana": "Joana Pereira"}', quando um
nome casa com mais de um registo (junta-se ao PROCURAR, sem mudar este ficheiro).
"""
import json
import os
import re
import sys
import unicodedata
from datetime import date

from pymongo import MongoClient

DESDE_POR_OMISSAO = "2026-10-01"
DIAS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

# O horário de cada loja (0 = segunda … 6 = domingo), na forma que o servidor valida
# (server.HorarioLoja). A chave é o nome a procurar nos Locais.
HORARIOS = {
    "Alfragide": {"abre": "10:00", "fecha": "23:00", "excecoes": [], "fechada": []},
    "Algueirão": {"abre": "13:00", "fecha": "22:00", "excecoes": [], "fechada": []},
    "Amadora": {"abre": "14:00", "fecha": "23:00", "excecoes": [], "fechada": []},
    "Belém": {"abre": "11:30", "fecha": "19:00",
              "excecoes": [{"dia": 6, "abre": "11:30", "fecha": "20:00"}], "fechada": [1]},
    "Benfica": {"abre": "13:00", "fecha": "22:00", "excecoes": [], "fechada": []},
    "Oeiras": {"abre": "13:00", "fecha": "22:00", "excecoes": [], "fechada": []},
}

# Quando um nome curto casa com mais de um registo em produção: o nome mais comprido a
# procurar em vez dele (ex.: {"Joana": "Joana Pereira"}). Vazio = procura-se a chave.
PROCURAR = {}


class Paragem(Exception):
    """Obriga a parar ANTES de escrever: um nome ambíguo, dados que pedem uma decisão."""


def _normal(texto):
    """Minúsculas, sem acentos, só letras e algarismos separados por um espaço."""
    sem_acentos = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", sem_acentos.lower()).split())


def _um(docs, chave, o_que):
    """O único documento cujo nome contém `chave` como palavra(s) inteira(s)."""
    alvo = " %s " % _normal(chave)
    achados = [d for d in docs if alvo in " %s " % _normal(d.get("name"))]
    if len(achados) != 1:
        nomes = ", ".join("«%s» (%s)" % (d.get("name"), d.get("id")) for d in achados) or "nenhum"
        raise Paragem("%s «%s» casa com %d: %s" % (o_que, chave, len(achados), nomes))
    return achados[0]


def _resumo_horario(h):
    if not h:
        return "sem horário"
    partes = ["%s–%s" % (h["abre"], h["fecha"])]
    partes += ["%s %s–%s" % (DIAS[e["dia"]], e["abre"], e["fecha"]) for e in h.get("excecoes") or []]
    if h.get("fechada"):
        partes.append("fecha " + ", ".join(DIAS[d] for d in h["fechada"]))
    return " · ".join(partes)


def _planear_lojas(lojas, benfica_desde, linhas, ops):
    """Junta às `linhas` e às `ops` o horário de cada loja; devolve {chave: id}."""
    ids = {}
    for chave, horario in HORARIOS.items():
        if chave == "Benfica" and benfica_desde is None:
            linhas.append("Loja Benfica: SALTADA — falta BENFICA_DESDE=AAAA-MM-DD (o dia em que abre).")
            continue
        loja = _um(lojas, PROCURAR.get(chave, chave), "A loja")
        ids[chave] = loja["id"]
        campos = {"horario": horario}
        if chave == "Benfica":
            campos["aberta_desde"] = benfica_desde.isoformat()
        abre = ", abre a %s" % campos["aberta_desde"] if "aberta_desde" in campos else ""
        if all(loja.get(k) == v for k, v in campos.items()):
            linhas.append("Loja %s: já está (%s%s)." % (loja["name"], _resumo_horario(horario), abre))
            continue
        linhas.append("Loja %s: %s → %s%s" % (
            loja["name"], _resumo_horario(loja.get("horario")), _resumo_horario(horario), abre))
        ops.append(("locations", "update_one", {"id": loja["id"]}, {"$set": campos}))
    return ids


def planear(db, desde, benfica_desde):
    """(linhas para mostrar, operações para gravar) — sem escrever nada."""
    lojas = list(db.locations.find({}, {"_id": 0}))
    linhas, ops = [], []
    _planear_lojas(lojas, benfica_desde, linhas, ops)
    return linhas, ops


def aplicar(db, ops):
    for colecao, operacao, *argumentos in ops:
        getattr(db[colecao], operacao)(*argumentos)


def main():
    gravar = os.environ.get("GRAVAR") == "1"
    try:
        desde = date.fromisoformat(os.environ.get("DESDE") or DESDE_POR_OMISSAO)
        benfica = os.environ.get("BENFICA_DESDE")
        benfica_desde = date.fromisoformat(benfica) if benfica else None
    except ValueError as erro:
        print("PARADO, nada foi escrito: data inválida (%s). Use AAAA-MM-DD." % erro)
        return 1
    # Uma ambiguidade de produção desfaz-se sem commit nem merge:
    # -e PROCURAR_JSON='{"Joana": "Joana Pereira"}'. Um JSON partido rebenta aqui,
    # antes de qualquer leitura ou escrita na base.
    PROCURAR.update(json.loads(os.environ.get("PROCURAR_JSON") or "{}"))
    cliente = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=10000)
    try:
        db = cliente[os.environ["DB_NAME"]]
        try:
            linhas, ops = planear(db, desde, benfica_desde)
        except Paragem as erro:
            print("PARADO, nada foi escrito: %s" % erro)
            return 1
        print("Base %s · escalas novas desde %s" % (os.environ["DB_NAME"], desde.isoformat()))
        print("\n".join(linhas))
        if not gravar:
            print("ENSAIO: %d escritas por fazer; nada foi escrito. "
                  "Para gravar, o mesmo comando com -e GRAVAR=1." % len(ops))
            return 0
        aplicar(db, ops)
        print("GRAVADO: %d escritas." % len(ops))
        return 0
    finally:
        cliente.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Passo 4: Correr e ver passar**

O comando do Passo 2. Esperado: `9 passed`, nenhum `skipped`.

- [ ] **Passo 5: Prova por mutação**

1. No `main`, trocar `if not gravar:` por `if False:` (grava sempre). Esperado **1 failed**: `test_o_ensaio_mostra_tudo_e_nao_escreve_nada`. Repor.
2. Em `_um`, trocar `if len(achados) != 1:` por `if not achados:` (fica com o primeiro). Esperado **1 failed**: `test_um_nome_que_casa_com_duas_lojas_para_tudo_antes_de_escrever`. Repor.
3. Em `_planear_lojas`, apagar o bloco `if all(loja.get(k) == v ...): ... continue`. Esperado **1 failed**: `test_correr_outra_vez_nao_reescreve_nada` («GRAVADO: 5 escritas.»). Repor.
4. Em `_planear_lojas`, trocar `_um(lojas, PROCURAR.get(chave, chave), "A loja")` por `_um(lojas, chave, "A loja")`. Esperado **1 failed**: `test_procurar_desfaz_a_ambiguidade_de_uma_loja`. Repor.
5. No `main`, apagar a linha `PROCURAR.update(json.loads(os.environ.get("PROCURAR_JSON") or "{}"))`. Esperado **1 failed**: `test_procurar_desfaz_a_ambiguidade_de_uma_loja` (`PARADO … A loja «Oeiras» casa com 2`, `main()` devolve 1). Repor.

`rm -rf ~/Library/Caches/com.apple.python`, correr outra vez (verde).

- [ ] **Passo 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add backend/arranque_calendario.py backend/tests/calendario/test_arranque_do_calendario.py
git commit -m "$(cat <<'EOF'
Arranque do calendário: o script que põe o horário das 6 lojas em produção

O assistente não escreve na base de produção; quem corre o arranque é o dono, no
contentor do backend. Por isso o script é só pymongo, mostra tudo em ensaio por
omissão, lê e decide tudo antes da primeira escrita, pára se um nome casar com
mais de uma loja, nunca apaga e pode correr-se outra vez sem reescrever nada.
Benfica só entra com a data de abertura (BENFICA_DESDE). Uma ambiguidade de
produção desfaz-se com PROCURAR_JSON, sem novo commit nem merge.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Tarefa 11: Script de arranque — as escalas das 7 pessoas

Para a grelha da Fase 2 bater com a semana normal (desenho, «Entrega por fases»): a Emily (14–23) e a Beatrice (10–19) levam horas explícitas; a Joana leva loja por dia (Amadora seg/ter, Oeiras qua, Algueirão qui/sex); a Rafaela não trabalha à terça (Belém fecha — e assim a terça também não conta nas férias dela). Cada pessoa fica com uma escala «Escala <Nome>»; se já tinha uma atribuição activa, essa fecha na véspera de `DESDE` e a nova começa em `DESDE`. A loja vai explícita em todos os dias (não «loja da ficha»), para a escala não depender de a ficha estar certa; quando a ficha diz outra loja, o script avisa.

**Ficheiros:**
- Modificar: `backend/arranque_calendario.py` (imports, `ESCALAS`, `_dia`, `_planear_escalas`, `planear`)
- Testes: `backend/tests/calendario/test_arranque_do_calendario.py` (acrescentar no fim)

**Interfaces:**
- Consome: `HORARIOS`, `PROCURAR`, `Paragem`, `_um`, `_planear_lojas`, `aplicar`, `main` (Tarefa 10); `server._dias_de_trabalho`, `server._dias_para_gravar`, `server.WorkScheduleTemplateCreate` (Tarefa 4) no teste de validação.
- Produz:
  - `ESCALAS: dict` — `{nome: [(loja, dias, inicio, fim), …]}`
  - `_dia(texto) -> date`
  - `_planear_escalas(lojas, pessoas, escalas, atribuicoes, ids, desde, linhas, ops) -> None`
  - `planear(db, desde, benfica_desde)` passa a planear lojas E escalas
  - documentos novos: `work_schedule_templates` `{"id", "name": "Escala <Nome>", "work_days", "start_time", "dias", "created_at"}` e `work_schedule_assignments` `{"id", "employee_id", "template_id", "work_days", "start_date": DESDE, "end_date": None, "created_at"}`

- [ ] **Passo 1: Escrever os testes que falham**

No fim de `backend/tests/calendario/test_arranque_do_calendario.py`, acrescentar:

```python
# ---- Tarefa 11: as escalas ----

def _escala(db, nome):
    return db.work_schedule_templates.find_one({"name": nome}, {"_id": 0})


def _atribuicoes(db, employee_id):
    return list(db.work_schedule_assignments.find({"employee_id": employee_id}, {"_id": 0}).sort("start_date", 1))


def test_a_joana_fica_com_uma_loja_por_dia_e_a_escala_antiga_fecha_na_vespera(prod, monkeypatch):
    monkeypatch.setenv("GRAVAR", "1")
    assert arranque.main() == 0
    joana = _escala(prod, "Escala Joana")
    assert joana["dias"] == [
        {"dia": 0, "location_id": "l-ama", "inicio": None, "fim": None},
        {"dia": 1, "location_id": "l-ama", "inicio": None, "fim": None},
        {"dia": 2, "location_id": "l-oei", "inicio": None, "fim": None},
        {"dia": 3, "location_id": "l-alg", "inicio": None, "fim": None},
        {"dia": 4, "location_id": "l-alg", "inicio": None, "fim": None},
    ]
    assert joana["work_days"] == [0, 1, 2, 3, 4]
    assert joana["start_time"] == "13:00"          # vem da 5x2: o lembrete do ponto não muda
    antiga, nova = _atribuicoes(prod, "e-joa")
    assert (antiga["id"], antiga["start_date"], antiga["end_date"]) == ("a-joa", "2026-01-01", "2026-09-30")
    assert (nova["template_id"], nova["start_date"], nova["end_date"]) == (joana["id"], "2026-10-01", None)
    assert nova["work_days"] == [0, 1, 2, 3, 4]


def test_as_outras_seis_escalas_batem_com_a_semana_normal(prod, monkeypatch):
    monkeypatch.setenv("GRAVAR", "1")
    assert arranque.main() == 0
    esperado = {
        "Emily": ("e-emi", [0, 1, 4, 5, 6], "l-alf", "14:00", "23:00"),
        "Beatrice": ("e-bea", [2, 3, 4, 5, 6], "l-alf", "10:00", "19:00"),
        "Walisson": ("e-wal", [0, 1, 2, 5, 6], "l-alg", None, None),
        "Weber": ("e-web", [2, 3, 4, 5, 6], "l-ama", None, None),
        "Emanuela": ("e-ema", [0, 3, 4, 5, 6], "l-oei", None, None),
        "Rafaela": ("e-raf", [0, 2, 3, 4, 5, 6], "l-bel", None, None),   # Belém fecha à terça
    }
    for nome, (pessoa, dias, loja, inicio, fim) in esperado.items():
        escala = _escala(prod, "Escala " + nome)
        assert escala["work_days"] == dias, nome
        assert escala["dias"] == [{"dia": d, "location_id": loja, "inicio": inicio, "fim": fim} for d in dias], nome
        assert escala["start_time"] is None, nome
        [atribuicao] = _atribuicoes(prod, pessoa)
        assert (atribuicao["template_id"], atribuicao["start_date"], atribuicao["end_date"]) == \
            (escala["id"], "2026-10-01", None), nome
        assert atribuicao["work_days"] == dias, nome
    assert _atribuicoes(prod, "e-car") == []           # a Carolina não está na tabela


def test_desde_muda_o_dia_de_inicio_e_a_vespera(prod, monkeypatch):
    monkeypatch.setenv("GRAVAR", "1")
    monkeypatch.setenv("DESDE", "2026-11-01")
    assert arranque.main() == 0
    antiga, nova = _atribuicoes(prod, "e-joa")
    assert antiga["end_date"] == "2026-10-31" and nova["start_date"] == "2026-11-01"


def test_o_ensaio_diz_o_que_cria_o_que_fecha_e_de_onde_vem_a_hora_de_inicio(prod, capsys):
    assert arranque.main() == 0
    saida = capsys.readouterr().out
    assert "criar «Escala Joana» (hora de início: 13:00, da escala «5x2»)" in saida
    assert "fechar «5x2» (2026-01-01 → em aberto; dias Seg, Ter, Qua, Qui, Sex) a 2026-09-30" in saida
    assert "nova atribuição desde 2026-10-01 (dias Seg, Qua, Qui, Sex, Sáb, Dom)" in saida      # a Rafaela
    assert "Emily Santos: Seg L'Açaí Alfragide 14:00–23:00" in saida


def test_a_ficha_noutra_loja_da_um_aviso_e_nao_para(prod, capsys):
    prod.employees.update_one({"id": "e-web"}, {"$set": {"location_id": "l-oei"}})
    assert arranque.main() == 0
    assert "aviso: a ficha diz «L'Açaí Oeiras»" in capsys.readouterr().out


@pytest.mark.parametrize("estrago, motivo", [
    (lambda db: db.employees.insert_one({"id": "e-joa2", "name": "Joana Martins", "location_id": None}),
     "A pessoa «Joana» casa com 2"),
    (lambda db: db.employees.delete_one({"id": "e-web"}),
     "A pessoa «Weber» casa com 0: nenhum"),
    (lambda db: db.work_schedule_assignments.insert_one({
        "id": "a-web", "employee_id": "e-web", "template_id": "t-5x2", "work_days": [0, 1, 2, 3, 4],
        "start_date": "2026-11-01", "end_date": None}),
     "depois de 2026-10-01"),
    (lambda db: db.work_schedule_assignments.insert_one({
        "id": "a-web", "employee_id": "e-web", "template_id": "t-5x2", "work_days": [0, 1, 2, 3, 4],
        "start_date": "2026-10-01", "end_date": None}),
     "não se pode fechar na véspera"),
    (lambda db: db.work_schedule_templates.insert_many([
        {"id": "t-x1", "name": "Escala Weber"}, {"id": "t-x2", "name": "Escala Weber"}]),
     "Há 2 escalas chamadas «Escala Weber»"),
])
def test_o_que_pede_uma_decisao_para_tudo_antes_de_escrever(prod, monkeypatch, capsys, estrago, motivo):
    estrago(prod)
    antes = _tudo(prod)
    monkeypatch.setenv("GRAVAR", "1")
    assert arranque.main() == 1
    saida = capsys.readouterr().out
    assert "PARADO, nada foi escrito" in saida and motivo in saida
    assert _tudo(prod) == antes


def test_procurar_desfaz_a_ambiguidade_de_uma_pessoa(prod, monkeypatch):
    prod.employees.insert_one({"id": "e-joa2", "name": "Joana Martins", "location_id": None})
    monkeypatch.setitem(arranque.PROCURAR, "Joana", "Joana Pereira")
    monkeypatch.setenv("GRAVAR", "1")
    assert arranque.main() == 0
    assert _atribuicoes(prod, "e-joa2") == []
    assert [a["start_date"] for a in _atribuicoes(prod, "e-joa")] == ["2026-01-01", "2026-10-01"]


def test_as_escalas_do_script_passam_na_validacao_do_servidor(prod, monkeypatch):
    monkeypatch.setenv("GRAVAR", "1")
    assert arranque.main() == 0
    escritas = list(prod.work_schedule_templates.find({"name": {"$regex": "^Escala "}}, {"_id": 0}))
    assert len(escritas) == 7
    for doc in escritas:
        corpo = server.WorkScheduleTemplateCreate.model_validate(
            {"name": doc["name"], "workDays": doc["work_days"], "dias": doc["dias"]})
        assert server._dias_de_trabalho(corpo) == doc["work_days"]
        assert server._dias_para_gravar(corpo) == doc["dias"]
```

- [ ] **Passo 2: Correr e ver falhar**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest tests/calendario/test_arranque_do_calendario.py -q
```

Esperado: `12 failed, 9 passed` — os 12 novos (8 funções, uma delas com 5 casos; o script ainda não escreve escalas: `TypeError: 'NoneType' object is not subscriptable`, `ValueError: not enough values to unpack`, linhas que faltam, ou `main()` a devolver 0 onde se espera 1); os 9 da Tarefa 10 continuam verdes.

- [ ] **Passo 3: Implementação mínima**

Em `backend/arranque_calendario.py`, trocar

```python
import unicodedata
from datetime import date
```

por

```python
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone
```

Depois do dicionário `HORARIOS`, acrescentar:

```python
# A escala de cada pessoa: (loja, dias, entrada, saída). Horas None = o horário da loja.
# A loja vai explícita em todos os dias, para não depender de a ficha estar certa.
ESCALAS = {
    "Emily": [("Alfragide", (0, 1, 4, 5, 6), "14:00", "23:00")],
    "Beatrice": [("Alfragide", (2, 3, 4, 5, 6), "10:00", "19:00")],
    "Walisson": [("Algueirão", (0, 1, 2, 5, 6), None, None)],
    "Joana": [("Amadora", (0, 1), None, None), ("Oeiras", (2,), None, None),
              ("Algueirão", (3, 4), None, None)],
    "Weber": [("Amadora", (2, 3, 4, 5, 6), None, None)],
    "Emanuela": [("Oeiras", (0, 3, 4, 5, 6), None, None)],
    # Belém fecha à terça: a Rafaela não trabalha à terça (nem lhe conta nas férias).
    "Rafaela": [("Belém", (0, 2, 3, 4, 5, 6), None, None)],
}
```

Depois de `_resumo_horario`, acrescentar:

```python
def _dia(texto):
    return date.fromisoformat(str(texto)[:10])
```

Depois de `_planear_lojas`, acrescentar:

```python
def _planear_escalas(lojas, pessoas, escalas, atribuicoes, ids, desde, linhas, ops):
    """Uma «Escala <Nome>» por pessoa; a atribuição activa fecha na véspera de `desde`
    e uma nova começa em `desde`. Junta tudo às `linhas` e às `ops`."""
    nome_da_loja = {loja["id"]: loja.get("name") for loja in lojas}
    agora = datetime.now(timezone.utc).isoformat()
    vespera = (desde - timedelta(days=1)).isoformat()
    for chave, blocos in ESCALAS.items():
        pessoa = _um(pessoas, PROCURAR.get(chave, chave), "A pessoa")
        fora = sorted({loja for loja, _, _, _ in blocos if loja not in ids})
        if fora:
            raise Paragem("A escala de %s usa %s, que ficou de fora." % (chave, ", ".join(fora)))
        dias = sorted(
            ({"dia": d, "location_id": ids[loja], "inicio": inicio, "fim": fim}
             for loja, ds, inicio, fim in blocos for d in ds),
            key=lambda x: x["dia"])
        work_days = [d["dia"] for d in dias]
        nome = "Escala %s" % chave

        minhas = sorted((a for a in atribuicoes if a.get("employee_id") == pessoa["id"]),
                        key=lambda a: a["start_date"])
        futuras = [a for a in minhas if _dia(a["start_date"]) > desde]
        if futuras:
            raise Paragem("%s já tem uma escala a começar a %s, depois de %s: decidir à mão."
                          % (pessoa["name"], futuras[0]["start_date"], desde.isoformat()))
        # Sem futuras, a que cobre `desde` é a que não acabou antes dele.
        activa = next((a for a in minhas if not a.get("end_date") or _dia(a["end_date"]) >= desde), None)
        com_o_nome = [e for e in escalas if e.get("name") == nome]
        if len(com_o_nome) > 1:
            raise Paragem("Há %d escalas chamadas «%s»: decidir à mão qual fica." % (len(com_o_nome), nome))
        escala = com_o_nome[0] if com_o_nome else None
        antiga = next((e for e in escalas if activa and e.get("id") == activa.get("template_id")), None)

        linhas.append("%s: %s" % (pessoa["name"], " · ".join(
            "%s %s%s" % (DIAS[d["dia"]], nome_da_loja[d["location_id"]],
                         " %s–%s" % (d["inicio"], d["fim"]) if d["inicio"] else "")
            for d in dias)))
        if pessoa.get("location_id") not in {d["location_id"] for d in dias}:
            linhas.append("  aviso: a ficha diz «%s»; o «Em falta» do painel continua a usar a ficha."
                          % nome_da_loja.get(pessoa.get("location_id"), "sem loja"))

        if escala is None:
            # A hora de início vem da escala antiga: é o que o lembrete do ponto lê.
            start_time = antiga.get("start_time") if antiga else None
            escala = {"id": str(uuid.uuid4()), "name": nome, "work_days": work_days,
                      "start_time": start_time, "dias": dias, "created_at": agora}
            ops.append(("work_schedule_templates", "insert_one", escala))
            linhas.append("  criar «%s» (hora de início: %s%s)" % (
                nome, start_time or "nenhuma", ", da escala «%s»" % antiga["name"] if antiga else ""))
        elif escala.get("dias") != dias or escala.get("work_days") != work_days:
            # O mesmo que o PUT /schedules: o modelo e a cópia das atribuições com o mesmo valor.
            ops.append(("work_schedule_templates", "update_one", {"id": escala["id"]},
                        {"$set": {"dias": dias, "work_days": work_days}}))
            ops.append(("work_schedule_assignments", "update_many", {"template_id": escala["id"]},
                        {"$set": {"work_days": work_days}}))
            linhas.append("  «%s» já existe: passa a ter estes dias" % nome)
        else:
            linhas.append("  «%s» já está assim" % nome)

        if activa and activa.get("template_id") == escala["id"]:
            linhas.append("  atribuição desde %s: já é esta" % activa["start_date"])
            continue
        if activa:
            if _dia(activa["start_date"]) >= desde:
                raise Paragem("A escala actual de %s começa a %s: não se pode fechar na véspera de %s."
                              % (pessoa["name"], activa["start_date"], desde.isoformat()))
            dias_antes = activa.get("work_days") or (antiga or {}).get("work_days") or []
            ops.append(("work_schedule_assignments", "update_one", {"id": activa["id"]},
                        {"$set": {"end_date": vespera}}))
            linhas.append("  fechar «%s» (%s → %s; dias %s) a %s" % (
                antiga["name"] if antiga else "(escala removida)", activa["start_date"],
                activa.get("end_date") or "em aberto", ", ".join(DIAS[d] for d in dias_antes), vespera))
        ops.append(("work_schedule_assignments", "insert_one", {
            "id": str(uuid.uuid4()), "employee_id": pessoa["id"], "template_id": escala["id"],
            "work_days": work_days, "start_date": desde.isoformat(), "end_date": None,
            "created_at": agora}))
        linhas.append("  nova atribuição desde %s (dias %s)" % (
            desde.isoformat(), ", ".join(DIAS[d] for d in work_days)))
```

Substituir `planear` por:

```python
def planear(db, desde, benfica_desde):
    """(linhas para mostrar, operações para gravar) — sem escrever nada."""
    lojas = list(db.locations.find({}, {"_id": 0}))
    pessoas = list(db.employees.find({}, {"_id": 0, "id": 1, "name": 1, "location_id": 1}))
    escalas = list(db.work_schedule_templates.find({}, {"_id": 0}))
    atribuicoes = list(db.work_schedule_assignments.find({}, {"_id": 0}))
    linhas, ops = [], []
    ids = _planear_lojas(lojas, benfica_desde, linhas, ops)
    _planear_escalas(lojas, pessoas, escalas, atribuicoes, ids, desde, linhas, ops)
    return linhas, ops
```

- [ ] **Passo 4: Correr e ver passar**

O comando do Passo 2. Esperado: `21 passed` (os 9 da Tarefa 10 e os 12 novos). Se o número não bater, ler a lista com `-v` antes de seguir.

- [ ] **Passo 5: Prova por mutação**

1. Trocar `vespera = (desde - timedelta(days=1)).isoformat()` por `vespera = desde.isoformat()`. Esperado **4 failed**: `test_a_joana_…` (`2026-10-01 != 2026-09-30`), `test_desde_muda_…`, `test_o_ensaio_diz_…` e `test_correr_outra_vez_nao_reescreve_nada` (a antiga fica a cobrir o próprio `DESDE` e o script volta a fechá-la a cada corrida). Repor.
2. Trocar `start_time = antiga.get("start_time") if antiga else None` por `start_time = None`. Esperado **2 failed**: `test_a_joana_…` e `test_o_ensaio_diz_…`. Repor.
3. Apagar as duas linhas `if futuras:` / `raise Paragem(...)`. Esperado **1 failed**: o caso «depois de 2026-10-01» do parametrizado (o script escrevia). Repor.
4. Em `ESCALAS`, trocar a Rafaela para `(0, 1, 2, 3, 4, 5, 6)`. Esperado **2 failed**: `test_as_outras_seis_…` e `test_o_ensaio_diz_…`. Repor.

`rm -rf ~/Library/Caches/com.apple.python`, correr outra vez (verde). Depois a suite inteira — esperado `passed` = partida + 69, `skipped` = partida:

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
export PATH="$HOME/.local/node/bin:$PATH"
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest -q 2>&1 | tail -3
```


- [ ] **Passo 6: Commit**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git add backend/arranque_calendario.py backend/tests/calendario/test_arranque_do_calendario.py
git commit -m "$(cat <<'EOF'
Arranque do calendário: as escalas das 7 pessoas da semana normal

Para a grelha dos buracos bater com a semana que o dono descreveu, cada pessoa
fica com uma «Escala <Nome>» com a loja de cada dia (a Joana em três lojas), as
horas da Emily e da Beatrice, e a Rafaela sem a terça. A atribuição activa fecha
na véspera de DESDE e a nova começa em DESDE, com a hora de início da escala
antiga para o lembrete do ponto não mudar. Pára antes de escrever quando um nome
é ambíguo ou já há uma escala marcada para depois.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Tarefa 12: Ensaiar o script na base local, juntá-lo ao `main` e entregá-lo ao dono

**Ficheiros:** nenhum novo. Usa a base local da Tarefa 8 e o `backend/arranque_calendario.py` das Tarefas 10-11.

**Interfaces:**
- Consome: `backend/arranque_calendario.py`; a base local `rh_calendario_local` com o que a Tarefa 8 gravou («Escala Emily» atribuída à Emily desde 2026-10-01, «Escala Joana» de seg a qui, as 6 lojas com horário e Benfica com `aberta_desde` 2026-10-24); o fluxo de publicação da Tarefa 9; as datas `DESDE` e `BENFICA_DESDE` que o dono deu na Tarefa 9, Passo 2.
- Produz: o script no `main`; em produção (pelo dono) o horário das 6 lojas (Benfica só com `BENFICA_DESDE`) e as 7 escalas da semana normal.

- [ ] **Passo 1: Ensaio do script na base local**

1. Arrancar o mongod local pela Bash em segundo plano (`run_in_background: true`):
   `/opt/homebrew/bin/mongod --dbpath "$HOME/.cache/lisbonb-calendario-local/mongo" --port 27031 --bind_ip 127.0.0.1 --quiet`
2. Ensaio:

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend && set -a && . "$HOME/.cache/lisbonb-calendario-local/backend.env" && set +a && ~/Developer/RH/backend/.venv/bin/python arranque_calendario.py
```

Esperado (ler linha a linha):
- `Loja L'Açaí Belém: já está (11:30–19:00 · Dom 11:30–20:00 · fecha Ter).` — o formulário e o script escrevem a mesma coisa;
- as outras 4 lojas também `já está (…)` (a Tarefa 8, Passo 5.4, deu-lhes o horário pelo formulário: as 5 lojas provam o mesmo); `Loja Benfica: SALTADA …`;
- Emily: `«Escala Emily» já está assim` e `atribuição desde 2026-10-01: já é esta` — prova de que o formulário e o script gravam os `dias` iguais;
- Joana: `«Escala Joana» já existe: passa a ter estes dias`, `fechar «5x2 (antiga)» (2026-01-01 → em aberto; dias Seg, Ter, Qua, Qui, Sex) a 2026-09-30`, `nova atribuição desde 2026-10-01 (dias Seg, Ter, Qua, Qui, Sex)`;
- as outras 5 pessoas: `criar «Escala …» (hora de início: nenhuma)` e `nova atribuição desde 2026-10-01`;
- `ENSAIO: N escritas por fazer; nada foi escrito.`

3. Gravar: o mesmo comando com `GRAVAR=1` à frente do `~/Developer/RH/backend/.venv/bin/python` → `GRAVADO: N escritas.`; correr outra vez sem `GRAVAR` → `ENSAIO: 0 escritas por fazer`.
4. Com `BENFICA_DESDE=2026-10-24 GRAVAR=1` → `Loja L'Açaí Benfica: já está (13:00–22:00, abre a 2026-10-24).` e `GRAVADO: 0 escritas.` (a Tarefa 8 já a deixou assim).
5. Opcional, mas recomendado: `preview_start` do `calendario-backend` e do `calendario-frontend`, abrir `/admin/escalas` e editar «Escala Joana» → seg/ter «L'Açaí Amadora», qua «L'Açaí Oeiras», qui/sex «L'Açaí Algueirão»; o Histórico mostra «5x2 (antiga)» até 2026-09-30 e «Escala Joana» desde 2026-10-01. Cancelar, `preview_stop` dos dois.
6. Parar o mongod: `pkill -f "mongod --dbpath $HOME/.cache/lisbonb-calendario-local/mongo"`.

- [ ] **Passo 2: Suite inteira**

```bash
cd /Users/matheus.moraes/Developer/RH-calendario/backend
export PATH="$HOME/.local/node/bin:$PATH"
PYTHONDONTWRITEBYTECODE=1 ~/Developer/RH/backend/.venv/bin/python -m pytest -q 2>&1 | tail -3
```

Esperado: `passed` = partida + 69, `skipped` = partida, `0 failed`. (O `export PATH` é o mesmo das outras corridas da suite: a partida foi medida com ele, na Tarefa 1. Hoje todos os testes que usam `node` também o procuram em `~/.local/node/bin`, mas um teste que não o faça salta sem ele, e o `skipped` deixa de bater.)

- [ ] **Passo 3: Juntar o script ao `main` (com o «sim» do dono)**

Mostrar ao dono `git log --oneline origin/main..HEAD` (os dois commits do script) e pedir o «sim». **Parar aqui até haver um «sim».** Depois:

```bash
cd /Users/matheus.moraes/Developer/RH-calendario
git push origin matheus-calendario-gestao
git fetch origin
git worktree add --detach /private/tmp/rh-publicar-calendario origin/main
cd /private/tmp/rh-publicar-calendario
git merge --no-ff matheus-calendario-gestao \
  -m "merge: script de arranque do calendário das lojas (fase 1)" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push origin HEAD:main
cd /Users/matheus.moraes/Developer/RH-calendario
git worktree remove /private/tmp/rh-publicar-calendario
```

Conflitos no merge: `git merge --abort`, parar e resolver com o dono. Push recusado (alguém juntou entretanto): `git worktree remove --force /private/tmp/rh-publicar-calendario` e repetir desde o `git fetch origin`. **Não é preciso deploy:** o servidor não importa este ficheiro (o dono corre-o a partir do Mac, pelo stdin) e o próximo deploy leva-o.

- [ ] **Passo 4: O dono corre o ENSAIO em produção**

Pedir ao dono que corra, no terminal dele (de preferência no painel Terminal desta app, para se poder ler o resultado com `read_terminal`; senão, que cole a saída):

```bash
ssh root@187.124.4.163 "cd ~/RH && docker compose exec -T -e DESDE=AAAA-MM-DD -e BENFICA_DESDE=AAAA-MM-DD backend python -" < ~/Developer/RH-calendario/backend/arranque_calendario.py
```

Antes de lho dar, trocar os dois `AAAA-MM-DD` pelas datas que o dono escolheu na Tarefa 9, Passo 2. Se ele ficou com 01/10, tirar o `-e DESDE=…`, que é o valor por omissão. Se ainda não sabe o dia de Benfica, tirar o `-e BENFICA_DESDE=…`. Usar as **mesmas** opções `-e` em todas as corridas deste passo e do seguinte.

Ler a saída com ele, linha a linha, contra a tabela do desenho («A semana normal»):
- 5 ou 6 lojas com o horário certo (Alfragide 10–23, Algueirão 13–22, Amadora 14–23, Belém 11:30–19 + Dom 11:30–20 + fecha Ter, Oeiras 13–22; Benfica 13–22 só com a data);
- 7 pessoas com as lojas e os dias certos; a Emily 14–23 e a Beatrice 10–19; a Rafaela sem Ter;
- que escala antiga fecha na véspera de `DESDE` para cada uma e com que dias, e de onde vem a hora de início;
- **a hora de início da Emily e da Beatrice**, nas linhas `criar «Escala Emily» (hora de início: …)` e `criar «Escala Beatrice» (…)`. O script copia-a da escala antiga, porque é a que o lembrete do ponto lê, e o desenho manda mantê-la. Deve ser 14:00 para a Emily e 10:00 para a Beatrice. Se não for (ex.: «10:00» na Emily, que entra às 14:00, faz o lembrete tocar 4 horas cedo), o dono grava na mesma e depois corrige-a no portal: Escalas → editar «Escala Emily» → «Hora de início» → Guardar;
- **o saldo de férias**: com `DESDE` no passado (ex.: 01/10), o saldo destas pessoas é recalculado logo a partir de `DESDE`. As férias de outubro (e seguintes) passam a contar pelos dias novos. Lembrar o dono de que foi isto que escolheu na Tarefa 9, Passo 2;
- os avisos de «a ficha diz …» (não param nada; dizer ao dono que o «Em falta» do painel continua a usar a ficha).

Se vier `PARADO, nada foi escrito: …`:
- nome que casa com mais de um (ou com nenhum): perguntar ao dono qual é o registo certo e juntar ao comando `-e PROCURAR_JSON=…` com a chave curta (a de `HORARIOS`/`ESCALAS`) e um nome mais comprido que só case com esse registo. Casa por palavras inteiras, sem acentos nem maiúsculas, por isso escrevê-lo sem acentos nem apóstrofos (ex.: `Acai Oeiras` para «L'Açaí Oeiras»). O nome da escala continua «Escala Joana». Exemplo, dentro das aspas do `ssh`:

  ```bash
  ssh root@187.124.4.163 "cd ~/RH && docker compose exec -T -e DESDE=AAAA-MM-DD -e PROCURAR_JSON='{\"Joana\": \"Joana Pereira\"}' backend python -" < ~/Developer/RH-calendario/backend/arranque_calendario.py
  ```

  Não é preciso mudar o ficheiro, fazer commit nem merge. Repete-se o ensaio com o `PROCURAR_JSON`, e o Passo 5 leva o mesmo `-e PROCURAR_JSON=…`;
- escala marcada para depois de `DESDE`, ou que começa no próprio `DESDE`: o dono decide (apagar essa atribuição no portal, ou correr com outro `-e DESDE=AAAA-MM-DD`), e repete-se o ensaio.

- [ ] **Passo 5: O dono grava**

Com o «sim» do dono à saída do ensaio, o comando do ensaio, com as mesmas opções `-e`, mais `-e GRAVAR=1`:

```bash
ssh root@187.124.4.163 "cd ~/RH && docker compose exec -T -e GRAVAR=1 -e DESDE=AAAA-MM-DD -e BENFICA_DESDE=AAAA-MM-DD backend python -" < ~/Developer/RH-calendario/backend/arranque_calendario.py
```

Esperado: `GRAVADO: N escritas.`, com o mesmo N do ensaio. Depois, o ensaio outra vez (sem `GRAVAR`) → `ENSAIO: 0 escritas por fazer`.

Se Benfica ficou de fora: quando o dono souber a data, corre o mesmo, com o mesmo `-e DESDE=…` e mais `-e BENFICA_DESDE=AAAA-MM-DD` (só Benfica muda; o resto diz «já está»).

- [ ] **Passo 6: O caminho feliz no portal, a sério (o dono)**

1. `https://lisbonb.com/admin/locais` (recarregado): a coluna «Horário» (ecrã largo) mostra as lojas; abrir Belém → Ter «Fechada», Dom «Outro horário» 11:30–20:00 → **Guardar sem mudar nada** → reabrir: igual. É a prova de que o GET e o PUT novos funcionam em produção sobre os dados do script.
2. `https://lisbonb.com/admin/escalas`: «Escala Joana» com o resumo `Seg L'Açaí Amadora · …`; editar → os dias vêm com as lojas; Cancelar. No Histórico de Atribuições, para cada uma das 7: a antiga até à véspera de `DESDE` e a nova desde `DESDE`.
3. Se alguma coisa não bater, não corrigir à mão na base: voltar ao Passo 4 com o dono.

- [ ] **Passo 7: Anotar na memória do projecto**

Actualizar `/Users/matheus.moraes/.claude/projects/-Users-matheus-moraes-Library-CloudStorage-OneDrive-Pessoal-Claude/memory/calendario-gestao.md` (e a linha do `MEMORY.md`): Fase 1 no ar (data, commit de merge), script corrido (N escritas), Benfica com ou sem data, e o que fica para a Fase 2.

---

## Auto-revisão

### Cobertura do desenho

| Requisito do desenho | Onde |
|---|---|
| «1. Os dados» — `horario` (`abre`, `fecha`, `excecoes`, `fechada`) e `aberta_desde` em `locations` | T1 (modelos), T2 (gravação), T6 (formulário) |
| Validação do horário: `abre` < `fecha` (HH:MM); dias 0-6 sem repetidos; um dia não pode estar em `excecoes` e em `fechada` | T1 (`test_horarios_que_o_servidor_recusa`) |
| Os dois campos em `LocationCreate`, `LocationResponse`, no `POST` e no `$set` do `PUT` | T1, T2 |
| O `PUT` só os escreve se vierem no corpo (`model_fields_set`) — página antiga em cache | T2 (`test_um_put_da_pagina_antiga_nao_apaga_o_horario`) e T8 Passo 6.2 (um PUT a sério sem os campos) |
| O formulário novo carrega-os ao abrir e manda-os sempre | T5 (`formularioParaHorario` manda sempre as duas chaves, e sem horário a data vai `null`: mutação 3), T6 (guarda de texto), T8 Passos 5-6 |
| Só as lojas com `horario` entram no calendário; `aberta_desde` esconde a loja antes de abrir | Guardado aqui (T2, T6); o seletor das Escalas só oferece lojas com horário (T7, mutação 4; T8 Passo 7.0); o efeito no cálculo é da Fase 2 |
| `dias` em `work_schedule_templates`: `location_id` vazio = ficha; horas vazias = horário da loja; as duas horas juntas; `inicio` < `fim` | T3 |
| `work_days` derivado de `dias` no `POST` e no `PUT`, calculado uma vez, o mesmo valor no modelo e nas atribuições | T4 (`test_o_post_deriva…`, `test_o_put_deriva…`, mutação 1) |
| O formulário continua a mandar `workDays`, igual aos dias de `dias` | T5 (`formularioParaDias`), T7 (guarda de texto), T8 Passo 7 |
| `dias` em `WorkScheduleTemplateCreate` e `WorkScheduleTemplateResponse`; o `PUT` só o escreve se vier no corpo | T3, T4 (`test_um_put_da_pagina_antiga_nao_apaga_os_dias`) |
| `start_time` («Hora de início») fica | T4 (`test_o_start_time_fica…`, com o `/me/schedule`), T7 (guarda), T11 (o script copia-o da escala antiga) |
| Escalas antigas, sem `dias`, continuam a valer | T4 (`test_uma_escala_antiga_sem_dias…`), T8 Passo 7.6 |
| Formulário das Escalas: por cada dia marcado, loja (por omissão «loja da ficha») e horas opcionais | T7, T8 Passo 7 |
| Teste 3 do desenho — escalas antigas; `dias` com loja e horas; `work_days` derivado no POST e no PUT, igual no modelo e nas atribuições; `start_time` intacto; saldo de férias igual; PUT sem `dias`/`horario` não apaga | T2, T4 |
| Teste 3 — entrada numa loja fechada ignorada, duas atribuições no mês, atribuição órfã, ausência pendente | Fase 2 (são regras do cálculo, `backend/calendario.py`) |
| Teste 4 — validações do horário | T1 |
| Teste 4 — exceção de domingo, dia fechado e antes de `aberta_desde` **no cálculo** | Fase 2 (aqui só se garante que ficam gravados e se lêem: T2, T5, T8) |
| Teste 11 — cada teste visto vermelho primeiro | Passo «Prova por mutação» em T1-T7, T10, T11 |
| Teste 12 — ecrãs a 375 px, claro e escuro | T8 Passo 8 (os formulários do portal; os ecrãs da app são da Fase 2) |
| Teste 14 — depois do deploy, confirmar o ficheiro servido e exercitar o caminho feliz | T9 Passo 5, T12 Passo 6 |
| «Entrega por fases», Fase 1 — portal com deploy | T9 |
| Script de arranque corrido pelo dono, com dry-run primeiro: 6 lojas e 7 escalas; Emily e Beatrice com horas; Joana com loja por dia; Rafaela sem terça | T10, T11, T12 |
| Benfica só com `BENFICA_DESDE`; senão salta e diz | T10 (`test_com_gravar…`, `test_benfica_entra…`) |
| Escala «Escala <Nome>» por pessoa; atribuição activa fecha na véspera de `DESDE` (por omissão 2026-10-01) e cria-se a nova | T11; o dono decide `DESDE` e `BENFICA_DESDE` antes (T9 Passo 2: com `DESDE` no passado o saldo de férias é recalculado já), e o script corre uma vez com as duas (T12 Passos 4-5) |
| O script pára em ambiguidades, nunca apaga, ensaio por omissão | T10, T11 (parametrizado), `test_o_script_nunca_apaga`; a ambiguidade desfaz-se com `PROCURAR_JSON`, sem commit (T10 mutação 5, T12 Passo 4) |
| `start_time` da Emily e da Beatrice copiado da escala antiga (o desenho manda mantê-lo) | T12 Passo 4: o dono confirma a linha «hora de início» e corrige-a no portal se não bater |
| Riscos aceites: editar os dias de uma escala reescreve as atribuições antigas (comportamento de sempre) | Mantido de propósito em T4 (`update_many` em todas as atribuições da escala); o script faz o mesmo quando uma «Escala <Nome>» já existe |
| Riscos aceites (do plano): a página antiga em cache desencontra `work_days` e `dias`; a cache do webpack do craco fica em `~/Developer/RH/frontend/node_modules/.cache` | T4 («Risco aceite»; quem manda é `work_days`, Fase 2); T8 Passo 3 e T9 Passo 1 (`CACHE_DIR`; no build o ESLint fica ligado, como no servidor) |

### Nomes que atravessam tarefas (verificados)

- `server._hora`, `server._dia_da_semana` — definidos em T1, usados em T1 e T3.
- `server.HorarioDoDia`, `server.HorarioLoja` — T1; usados em T2 (via `LocationCreate`) e em T10 (`test_os_horarios_do_script_passam_na_validacao_do_servidor`).
- `server._horario_para_gravar` — T2; procurado no contentor em T9 Passo 5 (se der 0: `build --no-cache backend`).
- `server.DiaDaEscala`, `WorkScheduleTemplateCreate.dias` — T3; usados em T4.
- `server._dias_de_trabalho`, `server._dias_para_gravar`, `WorkScheduleTemplateResponse.dias` — T4; usados em T11 (`test_as_escalas_do_script_passam_na_validacao_do_servidor`).
- Fixtures `mongod_porta`, `base` (conftest) e `corre`, `ADMIN` (`apoio.py`) — T2; usados em T2, T4, T10, T11.
- `DIAS_DA_SEMANA`, `horarioParaFormulario`, `formularioParaHorario`, `resumoDoHorario`, `diasParaFormulario`, `formularioParaDias`, `resumoDosDias` — T5; usados em T6 e T7 e nas guardas de texto.
- `_no_node`, `_corre`, `_compila`, `_LOCAIS`, `_ESCALAS` — T5/T6 no ficheiro de teste; usados em T6 e T7.
- `templateForm.porDia`, `handleChangeDia`, `corpo`, `nomeDaLoja` — T7.
- `formData.horario`, `mudarHorario`, `mudarDia` — T6.
- `arranque_calendario.HORARIOS`, `PROCURAR`, `Paragem`, `_normal`, `_um`, `_resumo_horario`, `_planear_lojas`, `planear`, `aplicar`, `main` e a variável `PROCURAR_JSON` — T10 (usada em T12 Passo 4); `ESCALAS`, `_dia`, `_planear_escalas` — T11.
- Marcadores do bundle `location-horario-tem` (T6) e `schedule-day-loja-` (T7) — verificados em T9 Passos 1 e 5.
- Contas da suite: partida + 15 (T1) + 4 (T2) + 11 (T3) + 6 (T4) + 8 (T5) + 2 (T6) + 2 (T7) = partida + 48 (T7, T9); + 9 (T10) + 12 (T11) = partida + 69 (T11, T12).
