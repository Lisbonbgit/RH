# Ecrã «Resumo» do gestor — app iOS (TestFlight)

Data: 2026-08-30 · Ramo: `matheus-resumo-do-gestor`

## O que se quer

Os três administradores do Gestão Lisbonb (Bruce Silva, Débora Ferreira,
Matheus Moraes) querem ver no telemóvel os números mais importantes das quatro
áreas — **Faturação, Financeiro, RH e Estoque** — sem poderem editar nada.
Distribuição por **TestFlight**, sem submissão à App Store.

## O que NÃO se faz, e porquê

**Não se cria uma app nova.** A app `Lisbonb RH` já existe e já é Capacitor:
o projeto iOS está em `frontend/ios`, com Pods instalados, `com.lisbonb.rh`,
assinado com o Team `P58HVPWKS8`, na versão 1.0.11 (build 12). Uma app separada
seria um segundo bundle id, uma segunda ficha na App Store Connect e um segundo
build a manter para sempre — a trocar por um ecrã.

**Não se toca no `PainelGlobal`** (`pages/admin/financeiro/PainelGlobal.js`).
É o painel do computador, é grande, e tem ações de escrita lá dentro
(`syncNowVendus`, `syncNowMoloni`, «Ligar ao RH») — exatamente o que não pode
existir neste ecrã. Fica intacto.

**Não se escreve backend.** Os quatro números já têm endpoint e já têm função
de cliente.

## Permissões — as duas metades do sistema

Isto não é detalhe: decide o que cada um dos três vê.

**Por papel.** `MANAGER_ROLES = ["admin", "gerente", "contabilista"]`; o staff é
`"colaborador"`. Cobre RH (`admin_manager_required`), Faturação (`gestor_atual`
→ `PERFIS_GESTAO`, os mesmos três) e Estoque (`admin_required`, que apesar do
nome aceita os três). **Os três administradores têm estes de imediato.**

**Por pertença à empresa.** O Financeiro é outra coisa:
`/fin/global/dashboard` deixa entrar qualquer sessão autenticada, mas a primeira
linha é `fin_require_member(company_id, ...)` → 403 a quem não seja membro em
`fin_company_members` (o código chama-lhe *anti-IDOR*). E
`fin_role_of` **só** consulta essa coleção: **não há atalho para `admin`**.
Ser administrador no RH não dá acesso ao Financeiro.

Consequência aceite: se o Bruce ou a Débora não forem membros da empresa em
Financeiro, o cartão Financeiro diz-lhes «Sem acesso». Resolve-se adicionando-os
em Financeiro → equipa; é decisão do dono, não do código.

Um `colaborador` continua sem ver nada disto: 403 por papel nos três primeiros,
e zero empresas onde seja membro no quarto.

## Origem dos dados

| Bloco | Cliente | Endpoint |
|---|---|---|
| Financeiro + RH | `getFinGlobalDashboard` (`lib/api.js:263`) | `GET /api/fin/global/dashboard?company_id&month&unit_id` |
| RH detalhado | `getAdminDashboard` (`lib/api.js:79`) | `GET /api/dashboard/admin` |
| Estoque | `getEstoqueOverview` (`lib/api.js:162`) | `GET /api/estoque/overview` |
| Faturação | `lib/faturacao.js:96` | `GET /api/faturacao/dashboard?com_iva` |

Campos usados, tal como o backend os devolve hoje:

- `fin/global/dashboard` → `financeiro{vendas_mes, a_pagar, pago, pendentes,
  vencidas, saldo_banco}`, `rh{linked, colaboradores, ausencias_pendentes,
  a_trabalhar[]}`, `company{id,name}`, `month`.
- `faturacao/dashboard` → `cartoes{hoje, mensal, anual}`, cada um
  `{valor, valor_comparado, variacao, comparacao}`; mais `ha_vendas` e `por_loja`.
- `estoque/overview` → **array** de lojas, cada uma
  `{unidade_id, nome, ativo, marca, total_produtos, abaixo_minimo, sem_maximo}`.

## O ecrã

**Ficheiro novo:** `frontend/src/pages/admin/Resumo.js`.
**Rota:** `/admin/resumo`, dentro do `ProtectedRoute` que já existe
(`allowedRoles={['admin','gerente','contabilista']}`).

**Aterragem.** No `RoleRedirect` do `App.js`: se `Capacitor.isNativePlatform()`
e o papel for de gestão → `/admin/resumo`; caso contrário, o comportamento atual
(`/admin`). No browser não muda absolutamente nada. O `isNativePlatform()` já é
o padrão da casa (`lib/geo.js`, `lib/statusbar.js`, `EmployeeLayout.js:65`).

**Forma.** Uma coluna, cartões empilhados, alvos grandes para o polegar. No topo,
seletor de empresa e de mês. Puxar para baixo recarrega.

1. **Vendas** — cartão principal: hoje (com a variação face a ontem) e o mês
   face ao mês anterior. Vem de `cartoes.hoje` e `cartoes.mensal`.
2. **Financeiro** — a pagar, vencidas (a vermelho quando > 0), pago no mês,
   saldo do banco.
3. **RH** — colaboradores, quantos estão ao serviço agora (`a_trabalhar.length`),
   ausências por aprovar.
4. **Estoque** — total de artigos abaixo do mínimo e, por baixo, a lista das
   lojas que têm algum.

Tocar num cartão não navega para lado nenhum. Não há caminho daqui para um ecrã
de edição.

**Falha por bloco, nunca do ecrã.** Cada cartão pede o seu endpoint
independentemente. Um 403 desenha «Sem acesso»; outro erro desenha
«Indisponível»; os restantes cartões aparecem na mesma. **Nunca se desenha `0 €`
por falta de dados** — a diferença entre «não tens acesso ao Financeiro» e «a
empresa não vendeu nada» é dinheiro, e no telemóvel essa confusão custa caro.
É a mesma postura que o backend já toma («cada setor é lido de forma defensiva»).

**Só-leitura a sério.** O ficheiro não importa nenhuma função de escrita.

## Teste

Um teste, o do caso que vai mesmo acontecer: monta o `Resumo` com o Financeiro a
responder 403 e os outros três a responder dados válidos, e verifica que

1. os cartões de Vendas, RH e Estoque mostram os seus números;
2. o cartão Financeiro diz «Sem acesso»;
3. não aparece `0 €` em parte nenhuma do ecrã.

Validar por mutação: partir a condição do 403 e ver o teste ficar vermelho pela
razão certa antes de o dar por bom.

## Envio

```
cd frontend
yarn build:mobile          # trava: exige https://rh.lisbonb.com no bundle
npx cap sync ios
```
Subir `CURRENT_PROJECT_VERSION` para 13 no Xcode, arquivar, enviar para o
TestFlight e convidar `bruce.silva@`, `debora.ferreira@` e `matheus.moraes@lisbonb.com`.
O Team de assinatura já está configurado; não há nada a criar.

Nota: `scripts/build-app-release.sh` só trata do Android. O iOS fica manual pelo
Xcode nesta primeira volta — automatiza-se se e quando doer.

## Fora de âmbito

Notificações push, gráficos, exportar PDF, filtro por loja no cartão de vendas,
modo offline, e qualquer ecrã de edição. Nada disto foi pedido.
