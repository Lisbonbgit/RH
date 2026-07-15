# Saldo de Férias para Admins — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gestores veem, por colaborador, o direito anual de férias, dias tirados, pendentes e restantes — no Mapa de Férias (por ano navegável) e na Lista de Colaboradores.

**Architecture:** Estende `calculate_vacation_days_used` (backend) com parâmetros `year`/`status`, expõe `vacation_days_pending` no `EmployeeResponse`, e cria um endpoint agregado `GET /api/reports/vacation-balance`. O frontend consome: o Mapa de Férias ganha 4 colunas anuais (do endpoint novo, pedidas com o ano do mês visível) e a Lista de Colaboradores usa os campos que já vêm no `GET /employees`.

**Tech Stack:** FastAPI + Motor/MongoDB (backend/server.py monolítico), React CRA + Tailwind/shadcn, jsPDF/autotable.

**Spec:** `docs/superpowers/specs/2026-07-14-saldo-ferias-design.md`

## Global Constraints

- Trabalhar SEMPRE em `~/Developer/RH`, ramo `matheus-saldo-ferias` (nunca na pasta OneDrive).
- Ambiente: `export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH"` antes de usar node/yarn.
- Sem suite de testes no repo (tests/ é vestígio do Emergent): verificação por tarefa = `python3 -m py_compile backend/server.py` (sintaxe) e `CI=false yarn build` (frontend); validação funcional final no site após deploy do main (Task 6).
- Textos de UI em PT-PT.
- Estados de pedidos: `pendente` / `aprovado` / `recusado`; tipo férias = `ferias`.
- Pedidos `recusado` nunca contam; "restantes" pode ser negativo → mostrar a vermelho, nunca esconder.
- Commits frequentes com mensagens em PT.

---

### Task 1: Backend — `calculate_vacation_days_used` com `year` e `status`

**Files:**
- Modify: `backend/server.py` (função `calculate_vacation_days_used`, ~linha 867)

**Interfaces:**
- Consumes: `calculate_leave_counted_days(employee_id, start_date, end_date)` (já existe, não mexer).
- Produces: `async def calculate_vacation_days_used(employee_id: str, year: Optional[int] = None, status: str = "aprovado") -> int` — Tasks 2 e 3 chamam com `year=` e `status="pendente"`. Os 4 chamadores existentes (linhas ~1647, 1667, 1682, 3016) continuam válidos sem alteração (defaults preservam o comportamento atual).

- [ ] **Step 1: Substituir a função**

Localizar `async def calculate_vacation_days_used` em `backend/server.py` e substituir a função inteira (assinatura + corpo, até ao `return total_days`) por:

```python
async def calculate_vacation_days_used(employee_id: str, year: Optional[int] = None, status: str = "aprovado") -> int:
    """Vacation days counted for an employee in a given year (default: current year).

    status selects which requests count: "aprovado" (default) or "pendente".
    """
    if year is None:
        year = datetime.now(timezone.utc).year
    year_start = f"{year}-01-01"
    year_end = f"{year}-12-31"

    vacation_requests = await db.leave_requests.find({
        "employee_id": employee_id,
        "leave_type": "ferias",
        "status": status,
        "$or": [
            {"start_date": {"$gte": year_start, "$lte": year_end}},
            {"end_date": {"$gte": year_start, "$lte": year_end}},
            {"$and": [{"start_date": {"$lte": year_start}}, {"end_date": {"$gte": year_end}}]}
        ]
    }, {"_id": 0}).to_list(1000)

    total_days = 0
    for request in vacation_requests:
        start = datetime.fromisoformat(request["start_date"])
        end = datetime.fromisoformat(request["end_date"])

        # Adjust dates to the requested year boundaries
        year_start_date = datetime(year, 1, 1)
        year_end_date = datetime(year, 12, 31)

        effective_start = max(start, year_start_date)
        effective_end = min(end, year_end_date)

        if effective_start <= effective_end:
            counted = await calculate_leave_counted_days(
                employee_id,
                effective_start.date().isoformat(),
                effective_end.date().isoformat()
            )
            total_days += counted

    return total_days
```

Nota: é a função atual com 3 mudanças — parâmetros novos, `current_year` → `year`, e `"status": "aprovado"` → `"status": status`. Nada mais muda.

- [ ] **Step 2: Verificar sintaxe e chamadores**

Run: `cd ~/Developer/RH && python3 -m py_compile backend/server.py && grep -n "calculate_vacation_days_used(" backend/server.py`
Expected: py_compile sem output (sucesso); grep mostra a definição + 4 chamadas de 1 argumento (compatíveis com os defaults).

- [ ] **Step 3: Commit**

```bash
cd ~/Developer/RH && git add backend/server.py && git commit -m "Férias: calculate_vacation_days_used aceita ano e estado (aprovado/pendente)"
```

---

### Task 2: Backend — `vacation_days_pending` no `EmployeeResponse`

**Files:**
- Modify: `backend/server.py` — classe `EmployeeResponse` (~linha 533), `get_employees` (~1622), `get_employee` (~1654), `_build_employee_response` (~1677)

**Interfaces:**
- Consumes: `calculate_vacation_days_used(employee_id, status="pendente")` (Task 1).
- Produces: campo `vacation_days_pending: int` em todas as respostas de colaborador (`GET /employees`, `GET /employees/{id}`, `GET /me/profile`, create/update). Task 5 lê `employee.vacation_days_pending` no frontend.

- [ ] **Step 1: Adicionar o campo ao modelo**

Na classe `EmployeeResponse`, logo a seguir a `vacation_days_available: int = 0`, adicionar:

```python
    vacation_days_pending: int = 0
```

- [ ] **Step 2: Calcular na lista de colaboradores**

Em `get_employees`, o loop tem:

```python
        # Calculate vacation days used and available
        vacation_used = await calculate_vacation_days_used(emp["id"])
        emp["vacation_days_used"] = vacation_used
        emp["vacation_days_available"] = emp["vacation_days"] - vacation_used
```

Acrescentar uma linha no fim do bloco:

```python
        emp["vacation_days_pending"] = await calculate_vacation_days_used(emp["id"], status="pendente")
```

- [ ] **Step 3: Calcular na ficha individual**

Em `get_employee`, substituir:

```python
    # Calculate vacation days used and available
    vacation_used = await calculate_vacation_days_used(employee_id)
```

por:

```python
    # Calculate vacation days used and available
    vacation_used = await calculate_vacation_days_used(employee_id)
    vacation_pending = await calculate_vacation_days_used(employee_id, status="pendente")
```

e no `return EmployeeResponse(...)` dessa função, a seguir a `vacation_days_available=employee["vacation_days"] - vacation_used`, acrescentar:

```python
        vacation_days_pending=vacation_pending,
```

- [ ] **Step 4: Calcular no `_build_employee_response`**

Na função `_build_employee_response`, substituir:

```python
    vacation_used = await calculate_vacation_days_used(employee["id"])
```

por:

```python
    vacation_used = await calculate_vacation_days_used(employee["id"])
    vacation_pending = await calculate_vacation_days_used(employee["id"], status="pendente")
```

e no `return EmployeeResponse(...)`, a seguir a `vacation_days_available=employee["vacation_days"] - vacation_used`, acrescentar:

```python
        vacation_days_pending=vacation_pending,
```

- [ ] **Step 5: Verificar sintaxe**

Run: `cd ~/Developer/RH && python3 -m py_compile backend/server.py`
Expected: sem output (sucesso).

- [ ] **Step 6: Commit**

```bash
cd ~/Developer/RH && git add backend/server.py && git commit -m "Férias: vacation_days_pending nas respostas de colaborador"
```

---

### Task 3: Backend — endpoint `GET /api/reports/vacation-balance` + helper API

**Files:**
- Modify: `backend/server.py` (novo endpoint a seguir a `worked_hours_report`)
- Modify: `frontend/src/lib/api.js` (novo helper, junto a `getWorkedHoursReport`, ~linha 33)

**Interfaces:**
- Consumes: `calculate_vacation_days_used(employee_id, year=..., status=...)` (Task 1); guard `admin_manager_required` (já existe).
- Produces: `GET /api/reports/vacation-balance?year=YYYY&company_id=...` → lista JSON `[{employee_id, name, vacation_days, used, pending, available}]` ordenada por nome; helper `getVacationBalance(params)` em api.js. Task 4 consome ambos.

- [ ] **Step 1: Adicionar o endpoint**

Em `backend/server.py`, localizar `@api_router.get("/reports/worked-hours")` e, DEPOIS do fim dessa função (antes do endpoint seguinte), inserir:

```python
@api_router.get("/reports/vacation-balance")
async def vacation_balance_report(
    year: Optional[int] = None,
    company_id: Optional[str] = None,
    current_user: dict = Depends(admin_manager_required)
):
    """Saldo de férias por colaborador num ano: direito, tirados, pendentes, restantes."""
    if year is None:
        year = datetime.now(timezone.utc).year

    emp_query = {}
    if company_id:
        emp_query["company_id"] = company_id
    employees = await db.employees.find(emp_query, {"_id": 0}).to_list(1000)

    results = []
    for emp in employees:
        used = await calculate_vacation_days_used(emp["id"], year=year)
        pending = await calculate_vacation_days_used(emp["id"], year=year, status="pendente")
        entitled = emp.get("vacation_days", 0)
        results.append({
            "employee_id": emp["id"],
            "name": emp["name"],
            "vacation_days": entitled,
            "used": used,
            "pending": pending,
            "available": entitled - used,
        })

    results.sort(key=lambda r: (r["name"] or "").lower())
    return results
```

- [ ] **Step 2: Verificar sintaxe**

Run: `cd ~/Developer/RH && python3 -m py_compile backend/server.py`
Expected: sem output (sucesso).

- [ ] **Step 3: Adicionar o helper no frontend**

Em `frontend/src/lib/api.js`, a seguir à linha `export const getWorkedHoursReport = ...`, adicionar:

```javascript
export const getVacationBalance = (params) => axios.get(`${API_URL}/reports/vacation-balance`, { params });
```

- [ ] **Step 4: Commit**

```bash
cd ~/Developer/RH && git add backend/server.py frontend/src/lib/api.js && git commit -m "Férias: endpoint /reports/vacation-balance (saldo anual por colaborador)"
```

---

### Task 4: Mapa de Férias — colunas anuais Direito/Tirados/Pendentes/Restantes + PDF

**Files:**
- Modify: `frontend/src/pages/admin/AdminVacationMap.js`
- Modify: `frontend/src/lib/pdf.js` (suporte opcional a 2.ª tabela, retrocompatível)

**Interfaces:**
- Consumes: `getVacationBalance({ company_id, year })` (Task 3) → `[{employee_id, name, vacation_days, used, pending, available}]`; `downloadTablePDF` (pdf.js).
- Produces: nada para outras tasks.

- [ ] **Step 1: Suporte a 2.ª tabela no pdf.js**

Em `frontend/src/lib/pdf.js`:

(a) na assinatura de `downloadTablePDF`, acrescentar `extraTable = null` ao destructuring:

```javascript
export function downloadTablePDF({
  filename, title, meta = [], headers, rows, foot = null,
  orientation = 'portrait', footerNote = '', extraTable = null,
}) {
```

(b) na doc (JSDoc) acima, acrescentar a linha:

```javascript
 * @param {Object} [opts.extraTable] segunda tabela {title, headers, rows} (opcional)
```

(c) imediatamente ANTES de `doc.save(filename);` (última linha da função), inserir:

```javascript
  // ----- Segunda tabela (opcional) -----
  if (extraTable) {
    const startY = (doc.lastAutoTable?.finalY || 40) + 10;
    doc.setTextColor(...INK);
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(11);
    doc.text(extraTable.title, marginX, startY);
    autoTable(doc, {
      head: [extraTable.headers],
      body: extraTable.rows,
      startY: startY + 3,
      theme: 'striped',
      styles: { font: 'helvetica', fontSize: 9, cellPadding: 2.6, textColor: INK, lineColor: [229, 231, 235], lineWidth: 0.1 },
      headStyles: { fillColor: BRAND, textColor: 255, fontStyle: 'bold' },
      alternateRowStyles: { fillColor: ZEBRA },
      margin: { left: marginX, right: marginX },
    });
  }
```

- [ ] **Step 2: Carregar o saldo no AdminVacationMap**

Em `frontend/src/pages/admin/AdminVacationMap.js`:

(a) import: mudar a linha 3 para:

```javascript
import { getCalendarLeaves, getEmployees, getVacationBalance } from '../../lib/api';
```

(b) estado: a seguir a `const [leaves, setLeaves] = useState([]);` adicionar:

```javascript
  const [balance, setBalance] = useState({});
```

(c) em `fetchData`, substituir o bloco `Promise.all` e os dois `set...` por:

```javascript
      const [leavesRes, employeesRes, balanceRes] = await Promise.all([
        getCalendarLeaves({ company_id: selectedCompany?.id, month, year }),
        getEmployees({ company_id: selectedCompany?.id }),
        getVacationBalance({ company_id: selectedCompany?.id, year }),
      ]);
      setLeaves(leavesRes.data || []);
      setEmployees(employeesRes.data || []);
      const balMap = {};
      for (const b of balanceRes.data || []) balMap[b.employee_id] = b;
      setBalance(balMap);
```

Nota: `year` já existe no componente (`refDate.getFullYear()`) — navegar de mês muda o ano quando cruza dezembro/janeiro e o `useEffect` já re-executa `fetchData` (depende de `month`/`year`).

- [ ] **Step 3: Colunas novas na tabela**

(a) no `<thead>`, substituir `<th className="p-2 text-center border-b border-l min-w-[56px]">Dias</th>` por:

```jsx
                    <th className="p-2 text-center border-b border-l min-w-[56px]">Dias (mês)</th>
                    <th className="p-2 text-center border-b border-l min-w-[60px]">Direito</th>
                    <th className="p-2 text-center border-b min-w-[72px]">Tirados {year}</th>
                    <th className="p-2 text-center border-b min-w-[76px]">Pendentes</th>
                    <th className="p-2 text-center border-b min-w-[76px]">Restantes</th>
```

(b) no `<tbody>`, dentro de `employees.map((emp) => {`, a seguir a `const total = countDays(emp.id);` adicionar:

```javascript
                    const bal = balance[emp.id];
```

(c) substituir `<td className="p-2 text-center border-b border-l font-medium">{total || '—'}</td>` por:

```jsx
                        <td className="p-2 text-center border-b border-l font-medium">{total || '—'}</td>
                        <td className="p-2 text-center border-b border-l">{bal ? bal.vacation_days : '—'}</td>
                        <td className="p-2 text-center border-b font-medium">{bal ? bal.used : '—'}</td>
                        <td className={`p-2 text-center border-b ${bal && bal.pending > 0 ? 'text-amber-600 font-medium' : 'text-muted-foreground'}`}>
                          {bal && bal.pending > 0 ? bal.pending : '—'}
                        </td>
                        <td className={`p-2 text-center border-b font-semibold ${bal && bal.available < 0 ? 'text-red-600' : 'text-emerald-600'}`}>
                          {bal ? bal.available : '—'}
                        </td>
```

- [ ] **Step 4: Saldo anual no PDF exportado**

Em `handleExportPDF`, a seguir ao array `rows` (antes do `downloadTablePDF({`), adicionar:

```javascript
    const balanceRows = employees.map((e) => {
      const b = balance[e.id];
      return b ? [e.name, b.vacation_days, b.used, b.pending, b.available] : [e.name, '—', '—', '—', '—'];
    });
```

e na chamada `downloadTablePDF({ ... })`, a seguir a `rows,`, acrescentar:

```javascript
      extraTable: {
        title: `Saldo anual de férias — ${year}`,
        headers: ['Colaborador', 'Direito', 'Tirados', 'Pendentes', 'Restantes'],
        rows: balanceRows,
      },
```

- [ ] **Step 5: Build do frontend**

Run: `cd ~/Developer/RH/frontend && export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH" && CI=false yarn build`
(Se `node_modules` não existir: `yarn install` primeiro.)
Expected: `Compiled successfully` (ou só warnings pré-existentes; ZERO erros novos).

- [ ] **Step 6: Commit**

```bash
cd ~/Developer/RH && git add frontend/src/pages/admin/AdminVacationMap.js frontend/src/lib/pdf.js && git commit -m "Mapa de Férias: colunas anuais direito/tirados/pendentes/restantes + saldo no PDF"
```

---

### Task 5: Lista de Colaboradores — coluna Férias + saldo na ficha

**Files:**
- Modify: `frontend/src/pages/admin/AdminEmployees.js` (tabela ~linha 388; diálogo "Detalhes do Colaborador" ~linha 694)

**Interfaces:**
- Consumes: `employee.vacation_days`, `.vacation_days_used`, `.vacation_days_available`, `.vacation_days_pending` — já presentes na resposta de `GET /employees` (Task 2). Sem pedidos novos à API.
- Produces: nada para outras tasks.

- [ ] **Step 1: Coluna na tabela**

(a) no `<TableHeader>`, a seguir a `<TableHead className="hidden xl:table-cell">Contrato</TableHead>`, adicionar:

```jsx
                    <TableHead className="hidden md:table-cell">Férias</TableHead>
```

(b) no `<TableBody>`, a seguir ao `<TableCell className="hidden xl:table-cell">` do contrato (fecha com `</TableCell>`), adicionar:

```jsx
                      <TableCell className="hidden md:table-cell">
                        <span className="font-medium">{employee.vacation_days_used}/{employee.vacation_days}</span>
                        <span className={`ml-2 text-xs ${employee.vacation_days_available < 0 ? 'text-red-600' : 'text-emerald-600'}`}>
                          {employee.vacation_days_available} livres
                        </span>
                      </TableCell>
```

- [ ] **Step 2: Saldo na ficha (diálogo "Detalhes do Colaborador")**

Substituir o bloco:

```jsx
                <div>
                  <p className="text-sm text-muted-foreground">Dias de Férias</p>
                  <p className="font-medium">{selectedEmployee.vacation_days} dias</p>
                </div>
```

por:

```jsx
                <div>
                  <p className="text-sm text-muted-foreground">Direito de férias</p>
                  <p className="font-medium">{selectedEmployee.vacation_days} dias</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Tiradas ({new Date().getFullYear()})</p>
                  <p className="font-medium">{selectedEmployee.vacation_days_used} dias</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Pendentes de aprovação</p>
                  <p className="font-medium">
                    {selectedEmployee.vacation_days_pending > 0 ? `${selectedEmployee.vacation_days_pending} dias` : '—'}
                  </p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Por tirar</p>
                  <p className={`font-medium ${selectedEmployee.vacation_days_available < 0 ? 'text-red-600' : 'text-emerald-600'}`}>
                    {selectedEmployee.vacation_days_available} dias
                  </p>
                </div>
```

- [ ] **Step 3: Build do frontend**

Run: `cd ~/Developer/RH/frontend && export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH" && CI=false yarn build`
Expected: `Compiled successfully`, zero erros novos.

- [ ] **Step 4: Commit**

```bash
cd ~/Developer/RH && git add frontend/src/pages/admin/AdminEmployees.js && git commit -m "Colaboradores: coluna de férias na lista + saldo completo na ficha"
```

---

### Task 6: Subir e validar no site (skill /fluxo, parte B)

**Files:** nenhum (git + deploy + verificação ao vivo)

**Interfaces:**
- Consumes: tudo o que foi commitado nas Tasks 1–5 no ramo `matheus-saldo-ferias`.

⚠️ Esta task publica no GitHub e no servidor — **confirmar com o Matheus antes de executar** (mostrar resumo do que vai subir).

- [ ] **Step 1: Push do ramo + merge ao main atualizado**

```bash
cd ~/Developer/RH && git push -u origin matheus-saldo-ferias
git checkout main && git pull && git merge matheus-saldo-ferias
git push origin main
```

Se houver conflitos no merge: PARAR e resolver com o utilizador (não forçar).

- [ ] **Step 2: Deploy — só o main**

```bash
ssh root@187.124.4.163 'cd ~/RH && git checkout main && git pull && docker compose up -d --build'
```

- [ ] **Step 3: Saúde**

Run: `curl -s https://rh.lisbonb.com/api/health`
Expected: resposta com `healthy`.

- [ ] **Step 4: Validação funcional (com o Matheus, no site)**

1. Mapa de Férias: 2–3 colaboradores com férias gozadas em 2026 — Tirados/Restantes batem certo com os pedidos aprovados.
2. Recuar o mapa para dezembro de 2025 → colunas passam a mostrar o saldo de 2025 (cabeçalho "Tirados 2025").
3. Lista de Colaboradores: coluna "Férias" coerente com o mapa; ficha mostra as 4 linhas.
4. Criar pedido de férias pendente de teste → aparece em "Pendentes" (âmbar); recusá-lo → desaparece.
5. Exportar PDF do mapa → segunda tabela "Saldo anual de férias" presente.

- [ ] **Step 5: Voltar (ou não) ao ramo**

Perguntar ao Matheus se quer continuar no ramo `matheus-saldo-ferias` ou ficar no `main`.
