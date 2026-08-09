# Saída Fora da Cerca + Lembrete Fiável — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A saída do ponto passa a ser aceite fora da cerca geográfica (marcada para o gestor); o lembrete de entrada ganha estado visível, re-agendamento ao voltar ao primeiro plano e alarme exato no Android.

**Architecture:** A cerca é validada no servidor (`create_time_record`) — distinguir aí o tipo de registo resolve a saída para todas as apps já instaladas sem build novo. As melhorias do lembrete são todas no frontend/app (a lógica `syncShiftReminders` já existe e está correta; o problema era dados + invisibilidade + timing Android).

**Tech Stack:** FastAPI + Motor/MongoDB (backend/server.py monolítico), React CRA + Tailwind/shadcn, Capacitor 6 (@capacitor/local-notifications, @capacitor/app já instalados), sonner (toasts).

**Spec:** `docs/superpowers/specs/2026-07-15-saida-fora-cerca-lembrete-design.md`

## Global Constraints

- Trabalhar SEMPRE em `~/Developer/RH`, ramo `matheus-saida-fora-lembrete` (nunca OneDrive).
- Ambiente node/yarn: `export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH"` antes de usar yarn.
- Sem suite de testes no repo: verificação = `python3 -m py_compile backend/server.py` (backend) e `CI=false yarn build` em `frontend/` (frontend); validação funcional no site/telemóvel após deploy (Task 6).
- Textos de UI em PT-PT.
- **Entrada** fora da cerca continua bloqueada (400 sem coords / 403 fora do raio) — comportamento atual intocável.
- **Saída**: aceite sempre; fora do raio → `out_of_fence: True` + distância; sem coordenadas → `out_of_fence: True` + distância `None`. Isentos (`geofence_exempt`) e locais sem cerca: sem validação nem marca (como hoje).
- Estados do lembrete vindos de `syncShiftReminders`: `{ok: true, at}` | `{ok: false, reason: 'web'|'no-schedule'|'denied'}` — na web não se mostra nada.
- Commits frequentes com mensagens em PT.

---

### Task 1: Backend — saída aceite fora da cerca, marcada

**Files:**
- Modify: `backend/server.py` — classe `TimeRecordResponse` (~linha 580) e função `create_time_record` (~linha 1849: bloco da cerca + `record_doc`)

**Interfaces:**
- Consumes: `haversine_meters(lat1, lon1, lat2, lon2)` (já existe).
- Produces: `TimeRecordResponse` com `out_of_fence: bool = False` e `out_of_fence_distance: Optional[int] = None`; documentos `time_records` novos com esses 2 campos. Tasks 2 e 3 leem `record.out_of_fence` / `record.out_of_fence_distance` no frontend.

- [ ] **Step 1: Campos novos no modelo**

Na classe `TimeRecordResponse`, a seguir a `accuracy: Optional[float] = None`, adicionar:

```python
    out_of_fence: bool = False
    out_of_fence_distance: Optional[int] = None
```

- [ ] **Step 2: Distinguir entrada/saída no bloco da cerca**

Em `create_time_record`, substituir o bloco completo da cerca (começa no comentário `# Cerca geográfica:` e termina no `raise HTTPException(status_code=403, ...)` com a mensagem "Aproxime-se para registar o ponto.") por:

```python
    # Cerca geográfica: se o local do colaborador tiver posição e raio definidos,
    # a ENTRADA só é aceite dentro do raio. A SAÍDA é sempre aceite (quem se
    # esquece de sair regista depois, de longe), mas fora do raio fica marcada
    # com out_of_fence para o gestor ver.
    # Colaboradores isentos (ex.: que rodam por várias lojas) não são validados.
    out_of_fence = False
    out_of_fence_distance = None
    employee = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    if employee and employee.get("location_id") and not employee.get("geofence_exempt"):
        location = await db.locations.find_one({"id": employee["location_id"]}, {"_id": 0})
        if location and location.get("latitude") is not None and location.get("longitude") is not None and location.get("geofence_radius"):
            radius = location["geofence_radius"]
            if record.latitude is None or record.longitude is None:
                if record.record_type == "entrada":
                    raise HTTPException(
                        status_code=400,
                        detail="Ative a localização no telemóvel para poder registar o ponto neste local."
                    )
                # Saída sem localização (ex.: GPS desligado já em casa): aceite, marcada.
                out_of_fence = True
            else:
                distance = haversine_meters(record.latitude, record.longitude, location["latitude"], location["longitude"])
                # Margem para a imprecisão do GPS (sobretudo Safari/iOS em precisão
                # normal, que pode reportar centenas de metros de erro). Aceita-se se,
                # descontando a precisão reportada (com limite), ainda estiver no raio.
                accuracy_slack = min(record.accuracy or 0, max(radius, 150))
                if distance - accuracy_slack > radius:
                    if record.record_type == "entrada":
                        raise HTTPException(
                            status_code=403,
                            detail=f"Está a {int(distance)} m do local de trabalho (limite {radius} m). Aproxime-se para registar o ponto."
                        )
                    # Saída fora do raio: aceite, marcada com a distância.
                    out_of_fence = True
                    out_of_fence_distance = int(distance)
```

- [ ] **Step 3: Gravar os campos no documento**

No `record_doc` (logo a seguir, na mesma função), depois de `"accuracy": record.accuracy`, adicionar:

```python
        "out_of_fence": out_of_fence,
        "out_of_fence_distance": out_of_fence_distance,
```

(Vírgula na linha do `accuracy` — atenção à sintaxe do dict.)

- [ ] **Step 4: Confirmar que as listagens propagam os campos**

`GET /time-records` constrói `TimeRecordResponse` a partir dos documentos. Confirmar (só leitura) que os registos antigos sem os campos novos caem nos defaults do modelo (não é preciso mexer). Se a construção usar filtragem explícita de campos, acrescentar os dois campos aí.

- [ ] **Step 5: Verificar sintaxe**

Run: `cd ~/Developer/RH && python3 -m py_compile backend/server.py`
Expected: sem output (sucesso).

- [ ] **Step 6: Commit**

```bash
cd ~/Developer/RH && git add backend/server.py && git commit -m "Ponto: saída aceite fora da cerca, marcada para o gestor"
```

---

### Task 2: Admin — marca "Fora do local" na listagem de registos

**Files:**
- Modify: `frontend/src/pages/admin/AdminTimeRecords.js` (célula "Estado" da tabela, ~linhas 263-273)

**Interfaces:**
- Consumes: `record.out_of_fence` (bool) e `record.out_of_fence_distance` (int|null) da Task 1.
- Produces: nada para outras tasks.

- [ ] **Step 1: Badge âmbar na célula Estado**

Substituir:

```jsx
                      <TableCell className="hidden sm:table-cell">
                        {record.corrected ? (
                          <Badge variant="outline" className="text-yellow-600 border-yellow-300">
                            Corrigido
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="text-green-600 border-green-300">
                            Original
                          </Badge>
                        )}
                      </TableCell>
```

por:

```jsx
                      <TableCell className="hidden sm:table-cell">
                        <div className="flex flex-wrap items-center gap-1">
                          {record.corrected ? (
                            <Badge variant="outline" className="text-yellow-600 border-yellow-300">
                              Corrigido
                            </Badge>
                          ) : (
                            <Badge variant="outline" className="text-green-600 border-green-300">
                              Original
                            </Badge>
                          )}
                          {record.out_of_fence && (
                            <Badge variant="outline" className="text-amber-600 border-amber-300">
                              {record.out_of_fence_distance != null
                                ? `Fora do local (${record.out_of_fence_distance} m)`
                                : 'Fora do local (sem localização)'}
                            </Badge>
                          )}
                        </div>
                      </TableCell>
```

- [ ] **Step 2: Build**

Run: `cd ~/Developer/RH/frontend && export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH" && CI=false yarn build`
Expected: `Compiled successfully` (warnings pré-existentes OK, zero erros novos).

- [ ] **Step 3: Commit**

```bash
cd ~/Developer/RH && git add frontend/src/pages/admin/AdminTimeRecords.js && git commit -m "Registos: marca 'Fora do local' na listagem do gestor"
```

---

### Task 3: Colaborador — aviso âmbar quando a saída fica fora do local

**Files:**
- Modify: `frontend/src/pages/employee/EmployeeTimeRecord.js` (função `handleRecord`, ~linha 53; container do `feedback`, ~linha 165)

**Interfaces:**
- Consumes: resposta de `createTimeRecord` com `out_of_fence` (Task 1). `setFeedback` aceita `kind: 'success' | 'warning' | 'error'` a partir desta task.
- Produces: nada para outras tasks.

- [ ] **Step 1: Capturar a resposta e tratar o caso fora do local**

Em `handleRecord`, substituir:

```jsx
      await createTimeRecord({ record_type: type, ...(position || {}) });

      if (position) {
        toast.success(`${label} registada com localização!`);
        setFeedback({ kind: 'success', title: `${label} registada`, description: 'Com a sua localização. ✅' });
      } else {
        toast.success(`${label} registada (sem localização)`);
        setFeedback({ kind: 'success', title: `${label} registada`, description: 'Este local não exige localização.' });
      }
```

por:

```jsx
      const res = await createTimeRecord({ record_type: type, ...(position || {}) });

      if (res.data?.out_of_fence) {
        toast.warning(`${label} registada fora do local`);
        setFeedback({
          kind: 'warning',
          title: `${label} registada fora do local`,
          description: 'O registo ficou marcado e o gestor será informado. Se a hora não corresponder à saída real, fale com o seu gestor para a corrigir.',
        });
      } else if (position) {
        toast.success(`${label} registada com localização!`);
        setFeedback({ kind: 'success', title: `${label} registada`, description: 'Com a sua localização. ✅' });
      } else {
        toast.success(`${label} registada (sem localização)`);
        setFeedback({ kind: 'success', title: `${label} registada`, description: 'Este local não exige localização.' });
      }
```

- [ ] **Step 2: Estilo âmbar no aviso**

No container do `feedback`, substituir:

```jsx
          className={`rounded-xl border p-4 flex items-start gap-3 ${
            feedback.kind === 'success'
              ? 'bg-green-50 border-green-200 text-green-800'
              : 'bg-red-50 border-red-200 text-red-800'
          }`}
```

por:

```jsx
          className={`rounded-xl border p-4 flex items-start gap-3 ${
            feedback.kind === 'success'
              ? 'bg-green-50 border-green-200 text-green-800'
              : feedback.kind === 'warning'
              ? 'bg-amber-50 border-amber-200 text-amber-800'
              : 'bg-red-50 border-red-200 text-red-800'
          }`}
```

(O ícone já está certo: só `success` mostra o check; `warning` e `error` mostram o triângulo.)

- [ ] **Step 3: Build**

Run: `cd ~/Developer/RH/frontend && export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH" && CI=false yarn build`
Expected: `Compiled successfully`, zero erros novos.

- [ ] **Step 4: Commit**

```bash
cd ~/Developer/RH && git add frontend/src/pages/employee/EmployeeTimeRecord.js && git commit -m "Ponto: aviso âmbar quando a saída é registada fora do local"
```

---

### Task 4: Colaborador — estado visível do lembrete na página do Ponto

**Files:**
- Modify: `frontend/src/pages/employee/EmployeeTimeRecord.js` (imports; estado; `useEffect` novo; UI a seguir ao parágrafo do `nextType`, ~linha 152-156)

**Interfaces:**
- Consumes: `getMySchedule()` de `../../lib/api` (devolve `{work_days, start_time}`); `syncShiftReminders(workDays, startTime)` de `../../lib/notifications` (devolve `{ok, at?, reason?}`); `Capacitor.isNativePlatform()`.
- Produces: nada para outras tasks.

- [ ] **Step 1: Imports e estado**

(a) juntar aos imports do topo:

```jsx
import { Capacitor } from '@capacitor/core';
import { getMySchedule } from '../../lib/api';
import { syncShiftReminders } from '../../lib/notifications';
```

e acrescentar `BellRing, BellOff` à lista importada de `lucide-react` (mesma linha dos outros ícones).

(b) juntar aos `useState` existentes:

```jsx
  const [reminder, setReminder] = useState(null); // estado do lembrete de entrada (só app nativa)
```

- [ ] **Step 2: Sincronizar e guardar o estado (só na app nativa)**

A seguir ao `useEffect` existente (o do relógio), adicionar:

```jsx
  // Estado do lembrete de entrada: re-agenda (idempotente) e mostra o resultado.
  useEffect(() => {
    if (!Capacitor.isNativePlatform()) return;
    (async () => {
      try {
        const res = await getMySchedule();
        const sync = await syncShiftReminders(res.data?.work_days, res.data?.start_time);
        setReminder(sync);
      } catch {
        setReminder(null);
      }
    })();
  }, []);
```

- [ ] **Step 3: Linha de estado na UI**

Logo DEPOIS do parágrafo:

```jsx
      <p className="text-center text-sm text-muted-foreground">
        {nextType === 'entrada'
          ? 'Toque em Entrada para iniciar o turno.'
          : 'Tem uma entrada em aberto — registe a Saída.'}
      </p>
```

adicionar:

```jsx
      {reminder?.ok && (
        <p className="flex items-center justify-center gap-1.5 text-xs text-muted-foreground" data-testid="reminder-status">
          <BellRing className="h-3.5 w-3.5 text-green-600" />
          Lembrete de entrada agendado para as {reminder.at}
        </p>
      )}
      {reminder && !reminder.ok && reminder.reason === 'no-schedule' && (
        <p className="flex items-center justify-center gap-1.5 text-xs text-muted-foreground" data-testid="reminder-status">
          <BellOff className="h-3.5 w-3.5" />
          Sem lembrete: a sua escala não tem hora de início — fale com o seu gestor.
        </p>
      )}
      {reminder && !reminder.ok && reminder.reason === 'denied' && (
        <p className="flex items-center justify-center gap-1.5 text-xs text-amber-600" data-testid="reminder-status">
          <BellOff className="h-3.5 w-3.5" />
          Notificações desativadas — ative-as nas definições do telemóvel para receber o lembrete.
        </p>
      )}
```

(`reason === 'web'` e `reminder === null` não mostram nada — site fica igual.)

- [ ] **Step 4: Build**

Run: `cd ~/Developer/RH/frontend && export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH" && CI=false yarn build`
Expected: `Compiled successfully`, zero erros novos.

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/RH && git add frontend/src/pages/employee/EmployeeTimeRecord.js && git commit -m "Ponto: estado visível do lembrete de entrada na app"
```

---

### Task 5: Re-agendar ao voltar ao primeiro plano + alarme exato Android

**Files:**
- Modify: `frontend/src/components/layouts/EmployeeLayout.js` (imports + `useEffect`, ~linhas 44-56)
- Modify: `frontend/android/app/src/main/AndroidManifest.xml` (permissões, ~linha 38)

**Interfaces:**
- Consumes: `App` (alias `CapApp`) de `@capacitor/app` (já em package.json); `Capacitor` de `@capacitor/core`; `getMySchedule` + `syncShiftReminders` (já importados neste ficheiro).
- Produces: nada para outras tasks.

- [ ] **Step 1: Imports no EmployeeLayout**

Juntar aos imports do topo:

```jsx
import { Capacitor } from '@capacitor/core';
import { App as CapApp } from '@capacitor/app';
```

- [ ] **Step 2: Listener de estado da app**

Substituir o `useEffect` de onboarding:

```jsx
  useEffect(() => {
    fetchNotifications();
    getMyProfile().then((res) => setPhoto(res.data?.photo || null)).catch(() => {});
    // Onboarding (app nativa): pedir permissões à entrada e agendar o lembrete
    (async () => {
      await requestLocationPermission();
      await requestNotificationPermission();
      try {
        const res = await getMySchedule();
        await syncShiftReminders(res.data?.work_days, res.data?.start_time);
      } catch { /* sem escala, tudo bem */ }
    })();
  }, []);
```

por:

```jsx
  useEffect(() => {
    fetchNotifications();
    getMyProfile().then((res) => setPhoto(res.data?.photo || null)).catch(() => {});
    const syncReminders = async () => {
      try {
        const res = await getMySchedule();
        await syncShiftReminders(res.data?.work_days, res.data?.start_time);
      } catch { /* sem escala, tudo bem */ }
    };
    // Onboarding (app nativa): pedir permissões à entrada e agendar o lembrete
    (async () => {
      await requestLocationPermission();
      await requestNotificationPermission();
      await syncReminders();
    })();
    // Re-agendar quando a app volta ao primeiro plano: apanha mudanças de
    // escala sem depender de um arranque a frio.
    let handle;
    if (Capacitor.isNativePlatform()) {
      CapApp.addListener('appStateChange', ({ isActive }) => {
        if (isActive) syncReminders();
      }).then((h) => { handle = h; });
    }
    return () => { handle?.remove(); };
  }, []);
```

- [ ] **Step 3: Permissão de alarme exato no Android**

Em `frontend/android/app/src/main/AndroidManifest.xml`, a seguir à linha
`<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />`, adicionar:

```xml
    <uses-permission android:name="android.permission.SCHEDULE_EXACT_ALARM" />
```

- [ ] **Step 4: Build**

Run: `cd ~/Developer/RH/frontend && export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH" && CI=false yarn build`
Expected: `Compiled successfully`, zero erros novos. (O manifest só é validado no build Android da Task 7.)

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/RH && git add frontend/src/components/layouts/EmployeeLayout.js frontend/android/app/src/main/AndroidManifest.xml && git commit -m "Lembrete: re-agendar ao voltar ao primeiro plano + alarme exato Android"
```

---

### Task 6: Subir, deploy do site e validação ao vivo (fluxo B)

**Files:** nenhum (git + deploy + verificação)

⚠️ Publica no GitHub e no servidor — **confirmar com o Matheus antes de executar**.

- [ ] **Step 1: Push + merge ao main atualizado + push do main**

```bash
cd ~/Developer/RH && git push -u origin matheus-saida-fora-lembrete
git checkout main && git pull && git merge matheus-saida-fora-lembrete
python3 -m py_compile backend/server.py
git push origin main
```

Se houver conflitos (o Bruce mexe no server.py com frequência): PARAR e resolver com o utilizador.

- [ ] **Step 2: Deploy — só o main**

```bash
ssh root@187.124.4.163 'cd ~/RH && git checkout main && git pull && docker compose up -d --build'
```

- [ ] **Step 3: Saúde**

Run: `curl -s https://rh.lisbonb.com/api/health`
Expected: `healthy`.

- [ ] **Step 4: Validação da saída fora da cerca (com o colaborador de teste)**

Colaborador de teste "Matheus Moraes" (id `5b00ea15-0580-4136-bda8-381c6eaea1b9`, loja Amadora, atualmente `geofence_exempt: True`). Sequência (o Matheus está fisicamente longe da loja):

1. Com isenção ativa: dar **entrada** pela app/site → aceite sem marca (como hoje).
2. Retirar a isenção via DB no servidor (`db.employees.update_one({"id": "5b00ea15-0580-4136-bda8-381c6eaea1b9"}, {"$set": {"geofence_exempt": False}})`).
3. Dar **saída** de longe → aceite; na listagem do gestor aparece "Fora do local (X m)"; o colaborador vê o aviso âmbar (no site; na app v11/v12 vê o aviso verde antigo — esperado até ao v13).
4. Tentar **entrada** de longe → 403 "Aproxime-se..." (entrada intacta).
5. Repor a isenção (`{"$set": {"geofence_exempt": True}}`).

- [ ] **Step 5: Validação do lembrete (dados)**

O gestor preenche a **hora de início** nas escalas (Admin → Escalas → editar → guardar). Depois confirmar na BD do servidor que gravou:

```bash
ssh root@187.124.4.163 "cd ~/RH && docker compose exec -T backend python -c \"
import os, asyncio
from motor.motor_asyncio import AsyncIOMotorClient
async def main():
    db = AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
    async for t in db.work_schedule_templates.find({}, {'_id':0,'name':1,'start_time':1}):
        print(t)
asyncio.run(main())
\""
```

Expected: `start_time` preenchido (HH:MM) nas escalas editadas. Se continuar `None` depois de o gestor gravar, há um bug no caminho de gravação — investigar antes de prosseguir (o código foi verificado e está correto, mas isto é o teste de ponta a ponta).

---

### Task 7: Builds da app — Android v13 + iOS

**Files:**
- Modify: `frontend/android/app/build.gradle` (versionCode/versionName, ~linhas 17-18)
- Modify (condicional): `frontend/ios/App/App.xcodeproj/project.pbxproj` (CURRENT_PROJECT_VERSION)

⚠️ Antes de começar, **perguntar ao Matheus**: "Já enviaste o build 12 do iOS ao TestFlight no Xcode?" — decide o passo 3.

- [ ] **Step 1: Bump Android**

Em `frontend/android/app/build.gradle`, substituir:

```gradle
        versionCode 12
        versionName "1.0.11"
```

por:

```gradle
        versionCode 13
        versionName "1.0.12"
```

- [ ] **Step 2: AAB de release**

```bash
cd ~/Developer/RH/frontend && ./scripts/build-app-release.sh
cp android/app/build/outputs/bundle/release/app-release.aab ~/Desktop/Lisbonb-RH-v13-1.0.12.aab
```

Expected: o script valida o backend no bundle e termina com "PRONTO"; o AAB fica na Secretária. (O script já faz `yarn build` + `cap sync android`.)

- [ ] **Step 3: iOS — versão e sync**

- Se o build 12 **ainda não foi enviado** ao TestFlight: manter `CURRENT_PROJECT_VERSION = 12` e `MARKETING_VERSION = 1.0.11`.
- Se **já foi enviado**: subir só o build em `frontend/ios/App/App.xcodeproj/project.pbxproj` (todas as ocorrências):

```
CURRENT_PROJECT_VERSION = 13;
```

Depois, em qualquer dos casos, sincronizar o bundle novo:

```bash
cd ~/Developer/RH/frontend && export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:/opt/homebrew/bin:$PATH" && export LANG=en_US.UTF-8 && npx cap sync ios
```

Expected: "Sync finished". O Matheus depois arquiva/envia no Xcode (Product → Archive → Distribute).

- [ ] **Step 4: Commit + merge ao main**

```bash
cd ~/Developer/RH && git add frontend/android/app/build.gradle frontend/ios/App/App.xcodeproj/project.pbxproj && git commit -m "App v13 (1.0.12): saída fora da cerca + lembrete visível"
git checkout main && git pull && git merge matheus-saida-fora-lembrete && git push origin main
```

(Se o passo 3 não alterou o pbxproj, o `git add` inclui só o build.gradle — ajustar em conformidade.)

- [ ] **Step 5: Entrega ao Matheus**

Informar: AAB `Lisbonb-RH-v13-1.0.12.aab` na Secretária → Play Console (Teste interno → Criar nova versão); iOS pronto no Xcode para Archive. Validações no telemóvel (v13): estado do lembrete visível na página do Ponto; notificação a disparar 5 min antes do turno (depois de a hora de início estar preenchida — Task 6 passo 5); aviso âmbar ao dar saída de longe.
