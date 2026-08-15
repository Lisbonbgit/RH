# "Em falta" no Dashboard — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O cartão "Quem está hoje" do dashboard do gestor passa a mostrar quem devia estar a trabalhar segundo a escala e ainda não deu entrada — em dois estados: "Em falta" (passou a hora de início + 15 min) e "Ainda não deu entrada" (antes disso, ou escala sem hora).

**Architecture:** Tudo se calcula no endpoint `GET /dashboard/admin` (`get_admin_dashboard`), que já resolve escala ativa, ausências aprovadas e primeira entrada de hoje por colaborador — só falta trazer `start_time` das templates e derivar os dois grupos. O frontend acrescenta dois `AvatarGroup` e uma métrica, seguindo os padrões existentes do `AdminDashboard.js`.

**Tech Stack:** FastAPI + Motor/MongoDB (backend/server.py), React CRA + Tailwind/shadcn + lucide-react.

**Spec:** `docs/superpowers/specs/2026-08-13-em-falta-dashboard-design.md`

## Global Constraints

- Trabalhar SEMPRE em `~/Developer/RH`, ramo `matheus-em-falta` (nunca OneDrive).
- Ambiente node/yarn: `export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH"`.
- Sem suite de testes no repo: verificação = `python3 -m py_compile backend/server.py` e `CI=false yarn build` em `frontend/`; validação funcional no site após deploy (Task 3).
- Textos de UI em PT-PT.
- **Elegível** = escala ativa hoje com dias definidos **e** hoje ∈ dias de trabalho **e** não está em `on_leave_ids` **e** não tem entrada hoje (`eid not in first_entry_by_emp`).
- **`missing`** = elegível **e** a escala tem `start_time` **e** `agora (Lisboa) ≥ start_time + 15 min`. **`not_in_yet`** = elegível e não `missing`.
- Comparação de horas SEMPRE à hora de Lisboa (`now_lis`, já existente no endpoint).
- `LATE_TOLERANCE_MINUTES = 15` num único sítio.
- Commits com mensagens em PT.

---

### Task 1: Backend — grupos `missing` / `not_in_yet` + métrica `missing_now`

**Files:**
- Modify: `backend/server.py` — função `get_admin_dashboard` (~linhas 2803-3060): query de templates (~2922), `_schedule_today` (~2927), `_mini` (~2938), chamadores de `_schedule_today` (~2940 e ~2969), `whos_in` (~2981), return final (~3050)

**Interfaces:**
- Consumes: `now_lis`, `today_date`, `on_leave_ids`, `first_entry_by_emp`, `emp_id_set`, `find_schedule_assignment`, `templates_by_id`, `assignments_by_emp` — todos já existentes na função.
- Produces (para a Task 2): em `whos_in`, `"missing": [...]` e `"not_in_yet": [...]` (mesmo formato de item que `working`, mais `"expected_start": "HH:MM"|None`); no topo da resposta `"missing_now": int`.

- [ ] **Step 1: Constante de tolerância**

Imediatamente ANTES da linha `@api_router.get("/dashboard/admin")` (o decorador de `get_admin_dashboard`), adicionar:

```python
# Minutos após a hora de início da escala a partir dos quais quem não deu
# entrada passa a "Em falta" (antes disso é só "Ainda não deu entrada").
LATE_TOLERANCE_MINUTES = 15

```

- [ ] **Step 2: Trazer `start_time` das templates**

Substituir:

```python
        templates = await db.work_schedule_templates.find(
            {"id": {"$in": list(template_ids)}}, {"_id": 0, "id": 1, "name": 1, "work_days": 1}
        ).to_list(500)
```

por:

```python
        templates = await db.work_schedule_templates.find(
            {"id": {"$in": list(template_ids)}}, {"_id": 0, "id": 1, "name": 1, "work_days": 1, "start_time": 1}
        ).to_list(500)
```

- [ ] **Step 3: `_schedule_today` devolve também `start_time`**

Substituir a função inteira:

```python
    def _schedule_today(eid):
        """Escala ativa hoje. Devolve (work_days, name) com a atribuição ativa,
        ou (None, None) se não houver atribuição a cobrir hoje. work_days pode ser
        lista vazia se a atribuição não definir dias."""
        assignment = find_schedule_assignment(assignments_by_emp.get(eid, []), today_date)
        if not assignment:
            return None, None
        tpl = templates_by_id.get(assignment.get("template_id"), {})
        work_days = assignment.get("work_days") or tpl.get("work_days") or []
        return list(work_days), tpl.get("name")
```

por:

```python
    def _schedule_today(eid):
        """Escala ativa hoje. Devolve (work_days, name, start_time) com a
        atribuição ativa, ou (None, None, None) se não houver atribuição a
        cobrir hoje. work_days pode ser lista vazia se a atribuição não definir
        dias; start_time é "HH:MM" ou None."""
        assignment = find_schedule_assignment(assignments_by_emp.get(eid, []), today_date)
        if not assignment:
            return None, None, None
        tpl = templates_by_id.get(assignment.get("template_id"), {})
        work_days = assignment.get("work_days") or tpl.get("work_days") or []
        return list(work_days), tpl.get("name"), tpl.get("start_time")
```

- [ ] **Step 4: Ajustar os chamadores existentes de `_schedule_today`**

(a) Em `_mini`, substituir:

```python
        sched_days, sched_name = _schedule_today(eid)
```

por:

```python
        sched_days, sched_name, sched_start = _schedule_today(eid)
```

e no dict `item` de `_mini`, a seguir a `"schedule_name": sched_name if sched_days else None,`, adicionar:

```python
            "expected_start": sched_start if sched_days else None,
```

(b) No bloco "Folga pela escala", substituir:

```python
        sched_days, _ = _schedule_today(eid)
```

por:

```python
        sched_days, _, _ = _schedule_today(eid)
```

- [ ] **Step 5: Calcular `missing` e `not_in_yet`**

Imediatamente ANTES de `whos_in = {` (depois do bloco que constrói `dayoff_all`), inserir:

```python
    # Devia estar a trabalhar (escala diz que hoje é dia de trabalho) e ainda
    # não deu NENHUMA entrada hoje. Quem já entrou (mesmo que já tenha saído)
    # não conta. Ausência aprovada tem prioridade.
    #   missing    -> escala com hora de início e já passou hora + tolerância
    #   not_in_yet -> ainda dentro da tolerância, ou escala sem hora definida
    now_minutes = now_lis.hour * 60 + now_lis.minute
    missing_items = []      # (minutos_previstos, eid)
    not_in_yet_items = []   # (minutos_previstos ou 10**6 se sem hora, eid)
    for eid in emp_id_set:
        if eid in on_leave_ids or eid in first_entry_by_emp:
            continue
        sched_days, _, sched_start = _schedule_today(eid)
        if not sched_days or today_weekday not in sched_days:
            continue
        start_minutes = None
        if sched_start:
            try:
                h, m = str(sched_start).split(":")
                start_minutes = int(h) * 60 + int(m)
            except (ValueError, AttributeError):
                start_minutes = None
        if start_minutes is not None and now_minutes >= start_minutes + LATE_TOLERANCE_MINUTES:
            missing_items.append((start_minutes, eid))
        else:
            not_in_yet_items.append((start_minutes if start_minutes is not None else 10**6, eid))
    missing_items.sort(key=lambda x: x[0])
    not_in_yet_items.sort(key=lambda x: x[0])
    missing_ids = [eid for _, eid in missing_items]
    not_in_yet_ids = [eid for _, eid in not_in_yet_items]

```

Nota: `today_weekday` já está definido acima (bloco "Folga pela escala"); `now_lis` está definido no início da função.

- [ ] **Step 6: Expor nos grupos e na métrica**

(a) Em `whos_in = {`, a seguir a `"working": [_mini(eid) for eid in working_ids[:18]],`, adicionar:

```python
        "missing": [_mini(eid) for eid in missing_ids[:18]],
        "not_in_yet": [_mini(eid) for eid in not_in_yet_ids[:18]],
```

(b) No `return {` final da função, a seguir a `"working_now": len(working_ids),`, adicionar:

```python
        "missing_now": len(missing_ids),
```

- [ ] **Step 7: Verificar sintaxe**

Run: `cd ~/Developer/RH && python3 -m py_compile backend/server.py`
Expected: sem output (sucesso).

- [ ] **Step 8: Commit**

```bash
cd ~/Developer/RH && git add backend/server.py && git commit -m "Dashboard: grupos 'Em falta' e 'Ainda não deu entrada' + métrica missing_now"
```

---

### Task 2: Frontend — grupos e métrica no dashboard

**Files:**
- Modify: `frontend/src/pages/admin/AdminDashboard.js` — import lucide (linha 10), `statusFor` (~linhas 45-68), `metrics` (~200-205), grupos do cartão "Quem está hoje" (~248-251)

**Interfaces:**
- Consumes: `stats.whos_in.missing`, `stats.whos_in.not_in_yet` (itens com `expected_start`), `stats.missing_now` — Task 1.
- Produces: nada.

- [ ] **Step 1: Ícones**

Substituir a linha de import do lucide-react:

```jsx
import { Users, Clock, CalendarDays, Palmtree, Cake, Check, X, PartyPopper, Briefcase, Coffee, UserMinus, Plane, MapPin, CalendarClock } from 'lucide-react';
```

por:

```jsx
import { Users, Clock, CalendarDays, Palmtree, Cake, Check, X, PartyPopper, Briefcase, Coffee, UserMinus, Plane, MapPin, CalendarClock, UserX, Hourglass } from 'lucide-react';
```

- [ ] **Step 2: Estados no `statusFor`**

No `switch (status)` de `statusFor`, ANTES de `default:`, adicionar:

```jsx
    case 'missing':
      return { className: 'text-red-600', text: person?.expected_start ? `Em falta · previsto ${person.expected_start}` : 'Em falta' };
    case 'not_in_yet':
      return { className: 'text-amber-600', text: person?.expected_start ? `Ainda não deu entrada · previsto ${person.expected_start}` : 'Ainda não deu entrada · sem hora na escala' };
```

- [ ] **Step 3: Métrica "Em falta"**

No array `metrics`, substituir:

```jsx
    { label: 'A trabalhar agora', value: stats?.working_now || 0, icon: Clock, color: 'text-teal-600', bg: 'bg-teal-50' },
```

por:

```jsx
    { label: 'A trabalhar agora', value: stats?.working_now || 0, icon: Clock, color: 'text-teal-600', bg: 'bg-teal-50' },
    { label: 'Em falta', value: stats?.missing_now || 0, icon: UserX, color: 'text-red-600', bg: 'bg-red-50' },
```

e, para as 5 métricas caberem, mudar a grelha:

```jsx
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
```

para:

```jsx
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
```

- [ ] **Step 4: Grupos no cartão "Quem está hoje"**

Substituir:

```jsx
              <AvatarGroup people={stats?.whos_in?.working || []} icon={Clock} label="A trabalhar" accent="text-teal-600" status="working" />
```

por:

```jsx
              <AvatarGroup people={stats?.whos_in?.working || []} icon={Clock} label="A trabalhar" accent="text-teal-600" status="working" />
              <AvatarGroup people={stats?.whos_in?.missing || []} icon={UserX} label="Em falta" accent="text-red-600" status="missing" />
              <AvatarGroup people={stats?.whos_in?.not_in_yet || []} icon={Hourglass} label="Ainda não deu entrada" accent="text-amber-600" status="not_in_yet" />
```

- [ ] **Step 5: Build**

Run: `cd ~/Developer/RH/frontend && export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH" && CI=false yarn build`
Expected: `Compiled successfully` (warnings pré-existentes OK, zero erros novos).

- [ ] **Step 6: Commit**

```bash
cd ~/Developer/RH && git add frontend/src/pages/admin/AdminDashboard.js && git commit -m "Dashboard: mostrar 'Em falta' e 'Ainda não deu entrada' em Quem está hoje"
```

---

### Task 3: Subir, deploy e validação (fluxo B)

**Files:** nenhum.

⚠️ Publica no GitHub e no servidor — **confirmar com o Matheus antes**.

- [ ] **Step 1: Push + merge ao main + push**

```bash
cd ~/Developer/RH && git push -u origin matheus-em-falta
git checkout main && git pull && git merge matheus-em-falta
python3 -m py_compile backend/server.py
git push origin main
```

Conflitos → PARAR e resolver com o utilizador.

- [ ] **Step 2: Deploy — só o main**

```bash
ssh root@187.124.4.163 'cd ~/RH && git checkout main && git pull && docker compose up -d --build'
```

- [ ] **Step 3: Saúde**

Run: `curl -s https://rh.lisbonb.com/api/health` → `healthy`.

- [ ] **Step 4: Validação no site (com o Matheus)**

1. Dashboard: colaboradores com escala hoje e sem entrada aparecem em "Ainda não deu entrada" (âmbar), com "previsto HH:MM" ou "sem hora na escala" no hover.
2. Alguém cuja hora de início + 15 min já passou e não deu entrada → "Em falta" (vermelho) e a métrica "Em falta" conta-o.
3. Esse colaborador dá entrada → sai dos dois grupos, aparece em "A trabalhar".
4. Folga/férias aprovadas ou dia da semana fora da escala → não aparece em nenhum dos dois.
5. Filtro de empresa no topo restringe os grupos.

Nota: enquanto as escalas de produção não tiverem hora de início, toda a gente elegível fica em âmbar "sem hora na escala" — é o comportamento esperado; o vermelho só aparece depois de o gestor preencher as horas.
