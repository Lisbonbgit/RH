# "Em falta" no dashboard do gestor — desenho

**Data:** 2026-08-13
**Estado:** aprovado pelo Matheus (chat)
**Ramo:** `matheus-em-falta`

## Objetivo

O cartão "Quem está hoje" mostra quem está a trabalhar, de férias, de folga e
ausente — mas não mostra o oposto: quem **devia** estar a trabalhar segundo a
escala e **ainda não deu entrada**. O gestor quer ver isso de relance.

## Decisões (respostas do Matheus)

- Tolerância: alguém só fica **"Em falta"** 15 minutos depois da hora de
  início da escala.
- Sem hora de início na escala: **não** é falta — aparece num estado próprio
  **"Ainda não deu entrada"**.
- Aviso: só no dashboard (sem emails nesta fase).

## Regra

Para cada colaborador do universo do dashboard (filtro de empresa respeitado):

1. **Elegível** se, e só se:
   - tem escala ativa hoje (`_schedule_today` devolve dias) **e** hoje é dia de
     trabalho nessa escala;
   - **não** está de férias/folga/ausência aprovada hoje (`on_leave_ids`);
   - **não** registou **nenhuma entrada hoje** (`first_entry_by_emp` não o
     conhece — quem já entrou e já saiu não é falta).
2. Entre os elegíveis:
   - se a escala tem `start_time` **e** `agora (Lisboa) ≥ start_time + 15 min`
     → **`missing`** ("Em falta");
   - caso contrário (ainda não passou a hora+tolerância, ou a escala não tem
     hora) → **`not_in_yet`** ("Ainda não deu entrada").

Retrato no momento do pedido (como o resto do cartão) e sempre à hora de
Lisboa (`LISBON_TZ`), incluindo a comparação com `start_time`.

## Backend (`backend/server.py`, `get_admin_dashboard`)

- A query de templates passa a trazer também `start_time`.
- `_schedule_today(eid)` passa a devolver `(work_days, name, start_time)`;
  os chamadores existentes ajustam-se (usam só o que precisam).
- `_mini(eid)` ganha `"expected_start": start_time` (string HH:MM ou None) —
  útil só para os dois grupos novos, inofensivo nos outros.
- Novos grupos em `whos_in`: `"missing": [...]` e `"not_in_yet": [...]`
  (mesmo limite de 18 dos restantes). Ordenação: `missing` por hora prevista
  crescente (mais atrasado primeiro); `not_in_yet` idem, com "sem hora" no fim.
- Nova métrica de topo: `"missing_now": len(missing_ids)`.
- Constante `LATE_TOLERANCE_MINUTES = 15` junto ao endpoint (um sítio só).

## Frontend (`frontend/src/pages/admin/AdminDashboard.js`)

- `AvatarGroup` novo **"Em falta"** (ícone `UserX`, `text-red-600`,
  `status="missing"`) e **"Ainda não deu entrada"** (ícone `Hourglass`,
  `text-amber-600`, `status="not_in_yet"`), a seguir a "A trabalhar".
- Sub-linha por pessoa (o `case` do status no helper existente):
  - `missing`: `previsto {expected_start}`;
  - `not_in_yet`: `previsto {expected_start}` ou `sem hora na escala`.
- Métrica nova nos cartões do topo: **"Em falta"** (`missing_now`, ícone
  `UserX`, `text-red-600`, `bg-red-50`), ao lado de "A trabalhar agora".
- Grupos vazios mostram "Ninguém" (comportamento atual do `AvatarGroup`).

## Fora de âmbito

- Email/notificação aos gestores; histórico/relatório de atrasos.
- Escalas com vários turnos por dia (o modelo atual é 1 hora de início).
- Alterar a app (é a mesma web; entra no build seguinte).

## Verificação

Sem suite de testes: `python3 -m py_compile` + `CI=false yarn build`; depois
no site (após deploy do main):

1. Dashboard de manhã: colaboradores com escala hoje e sem entrada aparecem
   em "Ainda não deu entrada" (âmbar) com a hora prevista.
2. Passados 15 min da hora de início de alguém sem entrada → passa para
   "Em falta" (vermelho) e a métrica "Em falta" conta-o.
3. Esse colaborador dá entrada → sai dos dois grupos, aparece em "A trabalhar".
4. Colaborador de folga/férias aprovadas ou cujo dia da semana não está na
   escala → não aparece em nenhum dos dois.
5. Escala sem `start_time` → fica em âmbar com "sem hora na escala" e nunca
   passa a vermelho.
6. Filtro de empresa no topo restringe os grupos como os restantes.

## Fluxo git

Ramo `matheus-em-falta` → merge ao `main` → deploy só do `main` (skill /fluxo).
