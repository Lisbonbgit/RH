# Saída fora da cerca + lembrete de entrada fiável — desenho

**Data:** 2026-07-15
**Estado:** aprovado pelo Matheus (chat)
**Ramo:** `matheus-saida-fora-lembrete`

## Problemas

1. Quem sai do trabalho e se esquece de dar saída não consegue registá-la
   depois: a cerca geográfica bloqueia com 403 fora do raio.
2. O lembrete "o teu turno começa daqui a 5 min" nunca dispara. Causa raiz
   confirmada na BD de produção: **as 6 escalas têm `start_time: None`** —
   sem hora de início, nada é agendado. Agravantes: a app falha em silêncio
   (não mostra o estado do lembrete), só agenda ao abrir a app, e no
   Android 12+ os alarmes podem ser adiados (sem permissão de alarme exato).

## Decisões (respostas do Matheus)

- Saída fora da cerca: **permitida e marcada** para o gestor ver.
- Hora do registo: **hora do clique**; o gestor corrige depois se necessário
  (a correção de registos já existe).
- Entrada: **continua** a exigir estar dentro da cerca.

## Parte A — Saída fora da cerca

### Backend (`backend/server.py`, `create_time_record`)

Hoje o bloco da cerca trata entrada e saída por igual: sem coordenadas → 400;
fora do raio → 403. Passa a distinguir o tipo:

- **entrada**: comportamento atual inalterado (400 sem coords, 403 fora).
- **saida**:
  - dentro do raio → como hoje, sem marca;
  - fora do raio → **aceite**, com `out_of_fence: True` e
    `out_of_fence_distance: int(distance)` gravados no registo;
  - sem coordenadas (GPS desligado — comum quando a pessoa já está em casa)
    → **aceite**, com `out_of_fence: True` e `out_of_fence_distance: None`.
- Colaboradores `geofence_exempt` e locais sem cerca: sem validação e sem
  marca (como hoje).
- `TimeRecordResponse` ganha `out_of_fence: bool = False` e
  `out_of_fence_distance: Optional[int] = None`. Registos antigos (sem o
  campo no Mongo) devolvem os defaults.

Como a validação é no servidor, **as apps v11/v12 já instaladas passam a
conseguir dar saída fora do local logo após o deploy do site** — sem build.

### Frontend — admin (`AdminTimeRecords.js`)

Na listagem de registos, badge âmbar junto ao registo de saída marcado:
"Fora do local (X m)" ou "Fora do local (sem localização)". Nada mais muda
(o link para o mapa e a correção de hora já existem).

### Frontend — colaborador (`EmployeeTimeRecord.js`)

Quando a resposta do registo vem com `out_of_fence`, o aviso de sucesso passa
a âmbar: "Saída registada fora do local de trabalho. O gestor será informado."
(No site é imediato; na app entra no próximo build.)

## Parte B — Lembrete de entrada fiável

### Dados (ação manual + verificação)

O gestor preenche a **hora de início** nas escalas (Admin → Escalas → editar).
Verificamos na BD que gravou (isto valida o caminho de gravação de ponta a
ponta; o código está correto, as escalas é que nunca foram editadas depois de
o campo existir).

### App — estado visível (`EmployeeTimeRecord.js`)

A página do Ponto (só na app nativa) mostra uma linha de estado do lembrete,
alimentada por `getMySchedule()` + `syncShiftReminders(...)` (idempotente —
cancela e re-agenda):

- ✓ "Lembrete agendado para HH:MM" (verde/neutro) — `{ok: true, at}`;
- "Sem escala com hora de início — fala com o teu gestor" — `reason: 'no-schedule'`;
- "Notificações desativadas — ativa-as nas definições do telemóvel" — `reason: 'denied'`;
- no browser (web): não aparece nada.

### App — re-agendar ao voltar ao primeiro plano (`EmployeeLayout.js`)

Listener `appStateChange` do `@capacitor/app` (já instalado): quando a app
volta a `active`, repete `getMySchedule()` + `syncShiftReminders(...)`.
Apanha mudanças de escala sem esperar por um arranque a frio. Remover o
listener no unmount do layout.

### Android — alarme exato (`AndroidManifest.xml`)

Adicionar `<uses-permission android:name="android.permission.SCHEDULE_EXACT_ALARM"/>`.
No Android 12–13 é concedida automaticamente; no 14+ pode exigir toggle nas
definições — sem ela o lembrete ainda dispara, mas pode atrasar; com ela fica
pontual onde o sistema permitir. iOS não precisa de nada (permissão já é
pedida em runtime).

## Fora de âmbito

- Push notifications do servidor (FCM) — só se o lembrete local se mostrar
  insuficiente na prática.
- Justificação escrita do colaborador ao sair fora do local.
- Marca "fora do local" nos relatórios de horas/exportações (fica na listagem
  de registos).

## Verificação

Backend/site (imediato após deploy):
1. Colaborador de teste **não isento**: dar **entrada** longe → continua 403;
   dar **saída** longe → aceite e o registo aparece ao gestor com a marca
   "Fora do local (X m)".
2. Saída com localização desligada → aceite com "sem localização".
3. Saída dentro da cerca → sem marca (comportamento igual ao de hoje).

Lembrete (parte manual + app v13):
4. Gestor preenche hora de início → confirmar na BD (`start_time` != None).
5. Na app: página do Ponto mostra "Lembrete agendado para HH:MM".
6. Prova real: à hora certa (5 min antes do turno) a notificação dispara no
   telemóvel — validação do dono no dia seguinte.

## Entrega

- **Deploy do site**: Parte A backend+admin+aviso web — efeito imediato,
  incluindo nas apps já instaladas (menos o aviso âmbar, que é UI).
- **App v13 Android** (versionCode 13 / 1.0.12) + **iOS** (1.0.11 build 12 se
  ainda não foi enviado ao TestFlight; senão build 13): estado do lembrete,
  re-sync no resume, aviso âmbar da saída, SCHEDULE_EXACT_ALARM.
- Fluxo git: ramo `matheus-saida-fora-lembrete` → main → deploy do main.
