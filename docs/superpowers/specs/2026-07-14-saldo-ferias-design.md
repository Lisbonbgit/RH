# Saldo de férias para admins — desenho

**Data:** 2026-07-14
**Estado:** aprovado pelo Matheus (chat)
**Ramo:** `matheus-saldo-ferias`

## Objetivo

Os gestores (admin/gerente/contabilista) devem ver, por colaborador, quantos
dias de férias já foram tirados no ano e quantos faltam tirar — hoje só o
próprio colaborador vê o seu saldo (dashboard e perfil).

## O que já existe (reutilizar)

- `Employee.vacation_days` — direito anual, default 22, editável na ficha.
- `calculate_vacation_days_used(employee_id)` em `backend/server.py` — soma os
  dias de férias **aprovadas** do ano corrente, com recorte ao ano e contagem
  via `calculate_leave_counted_days` (respeita escalas, feriados nacionais +
  personalizados e folgas).
- `GET /api/employees` (lista e ficha) já devolve `vacation_days_used` e
  `vacation_days_available`.
- Estados dos pedidos: `pendente` / `aprovado` / `recusado`.

## Alterações

### 1. Backend (`backend/server.py`)

- `calculate_vacation_days_used(employee_id, year=None, status="aprovado")`:
  - `year` default = ano corrente (comportamento atual mantém-se);
  - `status` permite calcular também os dias **pendentes**
    (`status="pendente"`);
  - o recorte ao ano já existe na função — passa a usar o `year` recebido.
- `EmployeeResponse` ganha `vacation_days_pending: int = 0`; a lista de
  colaboradores, a ficha individual e o `/me/profile`
  (`_build_employee_response`) calculam-no com o mesmo padrão do
  `vacation_days_used`.
- **Endpoint novo** `GET /api/reports/vacation-balance?year=YYYY&company_id=...`
  (guard `admin_manager_required`):
  - `year` opcional, default ano corrente; `company_id` opcional (filtra como
    nos outros endpoints);
  - devolve, por colaborador:
    `{employee_id, name, vacation_days, used, pending, available}`
    calculado para esse ano (`available = vacation_days - used`).

### 2. Mapa de Férias (`frontend/src/pages/admin/AdminVacationMap.js`)

- Além da coluna "Total" (dias de ausência do mês visível), 4 colunas anuais
  com o ano no cabeçalho (ex.: "Tirados 2026"): **Direito · Tirados ·
  Pendentes · Restantes**.
- Dados do endpoint novo, pedido com o **ano do mês visível** (navegar para
  dezembro de 2025 mostra o saldo de 2025).
- Pendentes a âmbar quando > 0, senão "—"; Restantes a verde, **vermelho se
  negativo** (ex.: direito reduzido a meio do ano) — nunca esconder.
- As colunas novas entram no PDF exportado (`downloadTablePDF`).

### 3. Lista de Colaboradores (`frontend/src/pages/admin/AdminEmployees.js`)

- Coluna nova "Férias" na tabela (escondida em ecrãs pequenos, como as
  restantes): `tirados/direito` + restantes a verde — ex.: **8/22 · 14 livres**.
  Sem pedido extra à API (dados já vêm no `GET /employees`).
- Ficha do colaborador (janela de detalhes): em vez de só "22 dias", as 4
  linhas — direito, tirados, pendentes, restantes (ano corrente).

## Casos limite

- Férias que atravessam a passagem de ano: cada ano conta só os dias que lhe
  pertencem (recorte já existente).
- Colaborador sem escala definida: contam-se dias úteis Seg–Sex (comportamento
  atual de `calculate_leave_counted_days`).
- Restantes negativos: mostrar a vermelho, não ocultar.
- Pedidos `recusado` nunca contam.

## Fora de âmbito

- Transporte de dias entre anos (carry-over) e direito proporcional à data de
  admissão — o direito é o valor simples definido na ficha.
- Alterar a app móvel (é a mesma app web empacotada; apanha isto no próximo
  release normal).

## Verificação

Sem Mongo local, a validação final é no site após deploy do `main`:
1. `curl https://rh.lisbonb.com/api/health` → healthy;
2. Mapa de Férias: conferir 2–3 colaboradores com férias já gozadas em 2026
   (tirados/restantes batem certo com os pedidos aprovados);
3. Recuar o mapa para dezembro de 2025 → saldo muda para 2025;
4. Lista de Colaboradores: coluna "Férias" coerente com o mapa; ficha mostra
   as 4 linhas;
5. Criar um pedido pendente de teste → aparece em "Pendentes"; recusá-lo →
   desaparece.

## Fluxo git

Ramo `matheus-saldo-ferias` a partir do `main` atualizado; merge ao `main` e
deploy só do `main` (skill /fluxo).
