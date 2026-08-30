# Ecrã «Resumo» do gestor — plano de implementação

> **Para quem executa:** SUB-SKILL OBRIGATÓRIA — usar `superpowers:subagent-driven-development`
> (recomendado) ou `superpowers:executing-plans`, tarefa a tarefa. Os passos usam
> caixas (`- [ ]`) para acompanhamento.

**Objetivo:** dar aos três administradores um ecrã de telemóvel, só-leitura, com
os números de Faturação, Financeiro, RH e Estoque, distribuído por TestFlight.

**Arquitetura:** as decisões do ecrã vivem num módulo puro (`lib/resumo.js`) que
transforma cada resposta — ou cada falha — no modelo de um cartão; o JSX
(`pages/admin/Resumo.js`) só desenha esse modelo. É a regra desta casa e está
escrita em `src/lib/pos.impressao.test.js`: um guarda que se leia num ficheiro
fica verde com a condição desligada por trás dele, por isso as decisões saem do
JSX e são **executadas** por um teste. Nenhum backend novo.

**Stack:** React 19 + CRA/craco, axios, Tailwind, componentes `ui/` já existentes,
Capacitor 6. Testes com o jest que vem no `react-scripts` — **sem
`@testing-library`**, que não está instalado e não vai ser instalado.

## Restrições globais

- Ramo de trabalho: `matheus-resumo-do-gestor`. **Nunca `git add -A`** — há
  trabalho de outra pessoa por guardar em `frontend/src/pages/admin/faturacao/`
  e em `backend/tests/faturacao/`. Adicionar sempre os ficheiros por nome.
- `node` não está no PATH. Todo o comando de frontend precisa de
  `export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH"` antes.
- Zero alterações ao backend. Zero dependências novas.
- Zero funções de escrita importadas em `Resumo.js`.
- **`eur(null)` devolve `0,00 €`** (`lib/finance.js:5`). Um valor em falta nunca
  pode passar por `eur` — omite-se a linha.
- Papéis de gestão: `['admin', 'gerente', 'contabilista']`.
- Textos em pt-PT, como o resto da app.

## Ficheiros

| Ficheiro | Responsabilidade |
|---|---|
| `frontend/src/lib/resumo.js` (novo) | Decisões puras: estado de cada bloco e modelo de cada cartão. Sem JSX, sem rede. |
| `frontend/src/lib/resumo.test.js` (novo) | Executa essas decisões. |
| `frontend/src/pages/admin/Resumo.js` (novo) | O ecrã. Só desenha o modelo. |
| `frontend/src/App.js` (modificar) | Rota `/admin/resumo` e aterragem na app. |

---

### Tarefa 1: as decisões (`lib/resumo.js`)

**Ficheiros:**
- Criar: `frontend/src/lib/resumo.js`
- Teste: `frontend/src/lib/resumo.test.js`

**Interfaces:**
- Consome: `eur` de `./finance`.
- Produz: `OK`, `SEM_ACESSO`, `INDISPONIVEL`, `MSG_SEM_ACESSO`,
  `MSG_INDISPONIVEL`, `pede(fn)`, `estadoDoBloco(res)`, `rotaDeAterragem({nativo, papel})`,
  `cartaoVendas(res)`, `cartaoFinanceiro(res)`, `cartaoRh(res)`, `cartaoEstoque(res)`.
  Todos os `cartaoX` devolvem `{ estado, mensagem, linhas: [{rotulo, valor, alerta?}] }`.

- [ ] **Passo 1: escrever o teste que falha**

Criar `frontend/src/lib/resumo.test.js`:

```js
/**
 * AS DECISÕES DO ECRÃ RESUMO — corridas de verdade, não lidas.
 *
 * A promessa que este ficheiro guarda é uma só: quando um bloco não tem dados,
 * o cartão NÃO produz números. `eur(null)` devolve «0,00 €», e um «0,00 €» num
 * telemóvel lê-se como «a empresa não vendeu nada», não como «não tens acesso».
 *
 * O que isto NÃO prova: que o JSX desenha só `linhas`. Isso vê-se com a app
 * aberta contra o servidor a sério.
 */
import { eur } from './finance';
import {
  pede, estadoDoBloco, rotaDeAterragem,
  cartaoVendas, cartaoFinanceiro, cartaoRh, cartaoEstoque,
  OK, SEM_ACESSO, INDISPONIVEL, MSG_SEM_ACESSO, MSG_INDISPONIVEL,
} from './resumo';

const negado = { ok: false, status: 403 };
const rebentou = { ok: false, status: 500 };

describe('estadoDoBloco', () => {
  test('403 é falta de acesso, não avaria', () => {
    expect(estadoDoBloco(negado)).toBe(SEM_ACESSO);
  });
  test('qualquer outra falha é avaria', () => {
    expect(estadoDoBloco(rebentou)).toBe(INDISPONIVEL);
    expect(estadoDoBloco({ ok: false, status: null })).toBe(INDISPONIVEL);
  });
  test('com dados, está ok', () => {
    expect(estadoDoBloco({ ok: true, data: {} })).toBe(OK);
  });
});

describe('pede', () => {
  test('embrulha a resposta', async () => {
    expect(await pede(async () => ({ data: { a: 1 } }))).toEqual({ ok: true, data: { a: 1 } });
  });
  test('apanha o 403 do axios sem deixar rebentar o ecrã', async () => {
    const erro = Object.assign(new Error('nope'), { response: { status: 403 } });
    expect(await pede(async () => { throw erro; })).toEqual({ ok: false, status: 403 });
  });
  test('um erro sem resposta (rede em baixo) não tem estado', async () => {
    expect(await pede(async () => { throw new Error('offline'); })).toEqual({ ok: false, status: null });
  });
});

describe('cartões sem acesso', () => {
  // A razão de existir de tudo isto.
  test.each([
    ['vendas', cartaoVendas], ['financeiro', cartaoFinanceiro],
    ['rh', cartaoRh], ['estoque', cartaoEstoque],
  ])('%s com 403 diz «Sem acesso» e NÃO traz linhas', (_nome, cartao) => {
    const c = cartao(negado);
    expect(c.estado).toBe(SEM_ACESSO);
    expect(c.mensagem).toBe(MSG_SEM_ACESSO);
    expect(c.linhas).toEqual([]);
  });

  test.each([
    ['vendas', cartaoVendas], ['financeiro', cartaoFinanceiro],
    ['rh', cartaoRh], ['estoque', cartaoEstoque],
  ])('%s avariado diz «Indisponível» e NÃO traz linhas', (_nome, cartao) => {
    const c = cartao(rebentou);
    expect(c.estado).toBe(INDISPONIVEL);
    expect(c.mensagem).toBe(MSG_INDISPONIVEL);
    expect(c.linhas).toEqual([]);
  });
});

describe('cartaoFinanceiro', () => {
  const resposta = { ok: true, data: { financeiro: {
    a_pagar: 1234.5, vencidas: 2, pago: 800, saldo_banco: 5000,
  } } };

  test('mostra os quatro números em euros', () => {
    const c = cartaoFinanceiro(resposta);
    expect(c.estado).toBe(OK);
    expect(c.linhas.map((l) => l.rotulo)).toEqual(['A pagar', 'Vencidas', 'Pago no mês', 'Saldo do banco']);
    // Comparar com `eur` e nunca com um literal: em pt-PT o separador de
    // milhares é um espaço INSEPARÁVEL (U+00A0). Um literal escrito à mão com
    // um espaço normal nunca casa — e um `expect(...).not` sobre ele fica
    // verde por engano, que é a pior espécie de teste.
    expect(c.linhas[0].valor).toBe(eur(1234.5));
  });

  test('faturas vencidas acendem o alerta; zero vencidas não', () => {
    expect(cartaoFinanceiro(resposta).linhas[1].alerta).toBe(true);
    const zero = { ok: true, data: { financeiro: { ...resposta.data.financeiro, vencidas: 0 } } };
    expect(cartaoFinanceiro(zero).linhas[1].alerta).toBe(false);
  });

  test('um campo em falta some do cartão — não vira «0,00 €»', () => {
    const semSaldo = { ok: true, data: { financeiro: { a_pagar: 10, vencidas: 0, pago: 5 } } };
    const rotulos = cartaoFinanceiro(semSaldo).linhas.map((l) => l.rotulo);
    expect(rotulos).not.toContain('Saldo do banco');
    expect(cartaoFinanceiro(semSaldo).linhas.some((l) => l.valor === eur(0))).toBe(false);
  });
});

describe('cartaoVendas', () => {
  const resposta = { ok: true, data: { ha_vendas: true, cartoes: {
    hoje: { valor: 300, valor_comparado: 200, variacao: 50 },
    mensal: { valor: 9000, valor_comparado: 8000, variacao: 12.5 },
  } } };

  test('traz hoje e o mês, cada um com a sua variação', () => {
    const c = cartaoVendas(resposta);
    expect(c.linhas.map((l) => l.rotulo)).toEqual(['Hoje', 'Este mês']);
    expect(c.linhas[0].variacao).toBe(50);
  });

  test('sem variação comparável, não inventa uma seta', () => {
    const sem = { ok: true, data: { ha_vendas: true, cartoes: {
      hoje: { valor: 300, valor_comparado: 0, variacao: null },
    } } };
    expect(cartaoVendas(sem).linhas[0].variacao).toBeNull();
  });

  test('um negócio que nunca vendeu diz isso, em vez de mostrar zeros', () => {
    const nunca = { ok: true, data: { ha_vendas: false, cartoes: {} } };
    const c = cartaoVendas(nunca);
    expect(c.linhas).toEqual([]);
    expect(c.mensagem).toBe('Ainda não há vendas');
  });
});

describe('cartaoRh', () => {
  // O RH vem de /dashboard/admin, que é guardado por PAPEL
  // (admin_manager_required). Não vem do painel do Financeiro, que é guardado
  // por PERTENÇA à empresa. É essa separação que faz o RH sobreviver a um 403
  // no Financeiro — o caso de um administrador que não é membro de empresa
  // nenhuma lá dentro.
  test('lê os quatro números do painel de RH', () => {
    const r = { ok: true, data: {
      total_employees: 12, working_now: 2, on_leave_today: 1, pending_requests: 3,
    } };
    const c = cartaoRh(r);
    expect(c.linhas.map((l) => [l.rotulo, l.valor])).toEqual([
      ['Colaboradores', '12'], ['Ao serviço agora', '2'],
      ['De férias hoje', '1'], ['Ausências por aprovar', '3'],
    ]);
    expect(c.linhas[3].alerta).toBe(true);
  });

  test('um ZERO verdadeiro desenha-se; só o que falta é que desaparece', () => {
    const c = cartaoRh({ ok: true, data: {
      total_employees: 12, working_now: 0, on_leave_today: 0, pending_requests: 0,
    } });
    expect(c.linhas[1].valor).toBe('0');
    expect(c.linhas[3].alerta).toBe(false);
    // `total_employees` em falta é outra coisa: some.
    const semTotal = cartaoRh({ ok: true, data: { working_now: 0 } });
    expect(semTotal.linhas.map((l) => l.rotulo)).toEqual(['Ao serviço agora']);
  });
});

describe('cartaoEstoque', () => {
  test('soma o que falta e nomeia só as lojas com falta', () => {
    const r = { ok: true, data: [
      { unidade_id: '1', nome: 'Belém', abaixo_minimo: 4 },
      { unidade_id: '2', nome: 'Oeiras', abaixo_minimo: 0 },
    ] };
    const c = cartaoEstoque(r);
    expect(c.linhas[0]).toMatchObject({ rotulo: 'Artigos abaixo do mínimo', valor: '4', alerta: true });
    expect(c.linhas.slice(1).map((l) => l.rotulo)).toEqual(['Belém']);
  });

  test('com tudo em ordem, diz que está tudo em ordem', () => {
    const r = { ok: true, data: [{ unidade_id: '1', nome: 'Belém', abaixo_minimo: 0 }] };
    const c = cartaoEstoque(r);
    expect(c.linhas[0].alerta).toBe(false);
    expect(c.linhas).toHaveLength(1);
  });
});

describe('rotaDeAterragem', () => {
  test('na APP, um gestor aterra no Resumo', () => {
    expect(rotaDeAterragem({ nativo: true, papel: 'admin' })).toBe('/admin/resumo');
  });
  test('no browser, um gestor aterra onde sempre aterrou', () => {
    expect(rotaDeAterragem({ nativo: false, papel: 'admin' })).toBe('/admin');
  });
  test('um colaborador vai para o lado dele, app ou não', () => {
    expect(rotaDeAterragem({ nativo: true, papel: 'colaborador' })).toBe('/colaborador');
    expect(rotaDeAterragem({ nativo: false, papel: 'colaborador' })).toBe('/colaborador');
  });
});
```

- [ ] **Passo 2: correr o teste e confirmar que FALHA**

```bash
cd ~/Developer/RH/frontend && export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH" && CI=true npx craco test --watchAll=false --testPathPattern="resumo"
```

Esperado: FAIL — `Cannot find module './resumo'`.

- [ ] **Passo 3: escrever `lib/resumo.js`**

```js
// As decisões do ecrã Resumo, fora do JSX de propósito — ver resumo.test.js.
//
// Todo o `cartaoX` devolve a MESMA forma: { estado, mensagem, linhas }. Quando
// não há dados, `linhas` fica VAZIA. É essa a garantia: o ecrã desenha linhas,
// logo um bloco sem dados não consegue produzir um número. `eur(null)` dá
// «0,00 €» e num telemóvel isso lê-se como «não vendeu nada» — nunca como
// «não tens acesso».
import { eur } from './finance';

export const OK = 'ok';
export const SEM_ACESSO = 'sem-acesso';
export const INDISPONIVEL = 'indisponivel';

export const MSG_SEM_ACESSO = 'Sem acesso';
export const MSG_INDISPONIVEL = 'Indisponível';
export const MSG_SEM_VENDAS = 'Ainda não há vendas';

const PAPEIS_DE_GESTAO = ['admin', 'gerente', 'contabilista'];

/** Corre uma chamada e devolve { ok, data } ou { ok:false, status }.
 *  Nunca lança: um bloco em baixo não pode derrubar os outros três. */
export async function pede(fn) {
  try {
    const r = await fn();
    return { ok: true, data: r?.data };
  } catch (e) {
    return { ok: false, status: e?.response?.status ?? null };
  }
}

export function estadoDoBloco(res) {
  if (!res || res.ok !== true) {
    return res && res.status === 403 ? SEM_ACESSO : INDISPONIVEL;
  }
  return OK;
}

/** Cartão vazio com a razão. Todos os cartões começam por aqui. */
function semDados(estado) {
  return {
    estado,
    mensagem: estado === SEM_ACESSO ? MSG_SEM_ACESSO : MSG_INDISPONIVEL,
    linhas: [],
  };
}

/** Um número que veio mesmo do servidor (0 conta; ausente e NaN não). */
const veioNumero = (v) => v != null && Number.isFinite(Number(v));

/** Linha de dinheiro — só existe se o número existir. */
const linhaEur = (rotulo, valor, alerta = false) =>
  (veioNumero(valor) ? [{ rotulo, valor: eur(valor), alerta }] : []);

/** Linha de contagem — idem. */
const linhaNum = (rotulo, valor, alerta = false) =>
  (veioNumero(valor) ? [{ rotulo, valor: String(Number(valor)), alerta }] : []);

export function cartaoVendas(res) {
  const estado = estadoDoBloco(res);
  if (estado !== OK) return semDados(estado);
  const d = res.data || {};
  if (d.ha_vendas === false) {
    return { estado, mensagem: MSG_SEM_VENDAS, linhas: [] };
  }
  const c = d.cartoes || {};
  const linhaCartao = (rotulo, cartao) => (
    cartao && veioNumero(cartao.valor)
      ? [{
          rotulo,
          valor: eur(cartao.valor),
          // `variacao` vem null do backend quando não há período comparável
          // (`_arredonda_opcional`). Nesse caso não se desenha seta nenhuma.
          variacao: veioNumero(cartao.variacao) ? Number(cartao.variacao) : null,
          alerta: false,
        }]
      : []);
  return {
    estado,
    mensagem: null,
    linhas: [...linhaCartao('Hoje', c.hoje), ...linhaCartao('Este mês', c.mensal)],
  };
}

export function cartaoFinanceiro(res) {
  const estado = estadoDoBloco(res);
  if (estado !== OK) return semDados(estado);
  const f = (res.data || {}).financeiro || {};
  return {
    estado,
    mensagem: null,
    linhas: [
      ...linhaEur('A pagar', f.a_pagar),
      ...linhaNum('Vencidas', f.vencidas, Number(f.vencidas) > 0),
      ...linhaEur('Pago no mês', f.pago),
      ...linhaEur('Saldo do banco', f.saldo_banco),
    ],
  };
}

// Lê /dashboard/admin (getAdminDashboard), NÃO o painel do Financeiro.
// Os dois trazem números de RH, mas com guardas diferentes: este é por papel
// (admin/gerente/contabilista) e o outro é por pertença à empresa. Tirar o RH
// daqui é o que o deixa vivo quando o Financeiro responde 403.
export function cartaoRh(res) {
  const estado = estadoDoBloco(res);
  if (estado !== OK) return semDados(estado);
  const d = res.data || {};
  return {
    estado,
    mensagem: null,
    linhas: [
      ...linhaNum('Colaboradores', d.total_employees),
      ...linhaNum('Ao serviço agora', d.working_now),
      ...linhaNum('De férias hoje', d.on_leave_today),
      ...linhaNum('Ausências por aprovar', d.pending_requests,
        Number(d.pending_requests) > 0),
    ],
  };
}

export function cartaoEstoque(res) {
  const estado = estadoDoBloco(res);
  if (estado !== OK) return semDados(estado);
  // Este endpoint devolve um ARRAY de lojas (ver EstoqueVisaoGeral.js).
  const lojas = Array.isArray(res.data) ? res.data : [];
  const total = lojas.reduce((a, l) => a + (Number(l.abaixo_minimo) || 0), 0);
  const comFalta = lojas.filter((l) => Number(l.abaixo_minimo) > 0);
  return {
    estado,
    mensagem: null,
    linhas: [
      { rotulo: 'Artigos abaixo do mínimo', valor: String(total), alerta: total > 0 },
      ...comFalta.map((l) => ({
        rotulo: l.nome || '—',
        valor: String(Number(l.abaixo_minimo)),
        alerta: true,
      })),
    ],
  };
}

/** Para onde vai quem acaba de entrar. Só muda DENTRO da app. */
export function rotaDeAterragem({ nativo, papel }) {
  if (!PAPEIS_DE_GESTAO.includes(papel)) return '/colaborador';
  return nativo ? '/admin/resumo' : '/admin';
}
```

- [ ] **Passo 4: correr o teste e confirmar que PASSA**

```bash
cd ~/Developer/RH/frontend && export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH" && CI=true npx craco test --watchAll=false --testPathPattern="resumo"
```

Esperado: `Tests: 27 passed`.

- [ ] **Passo 5: validar por mutação (obrigatório — um teste verde não vale nada até se o ver vermelho pela razão certa)**

Em `lib/resumo.js`, trocar `linhaEur` por uma versão que nunca omite:

```js
const linhaEur = (rotulo, valor, alerta = false) => [{ rotulo, valor: eur(valor), alerta }];
```

Correr o teste outra vez. **Tem de falhar** em «um campo em falta some do cartão»,
a dizer que encontrou `eur(0)`. Se passar, o teste não está a guardar nada —
parar e corrigir o teste antes de seguir. Depois desfazer a mutação e voltar a
correr até ficar verde.

- [ ] **Passo 6: commit** (por nome — há trabalho de outra pessoa na árvore)

```bash
cd ~/Developer/RH && git add frontend/src/lib/resumo.js frontend/src/lib/resumo.test.js && git commit -m "As decisões do ecrã Resumo, fora do JSX e corridas por testes"
```

---

### Tarefa 2: o ecrã (`pages/admin/Resumo.js`)

**Ficheiros:**
- Criar: `frontend/src/pages/admin/Resumo.js`
- Modificar: `frontend/src/App.js` (registar a rota)

**Interfaces:**
- Consome da Tarefa 1: `pede`, `cartaoVendas`, `cartaoFinanceiro`, `cartaoRh`,
  `cartaoEstoque`, `OK`.
- Consome do que já existe: `getFinCompanies` (`lib/api.js:109`),
  `getFinGlobalDashboard` (`lib/api.js:263`), `getAdminDashboard` (`lib/api.js:79`),
  `getEstoqueOverview` (`lib/api.js:162`),
  `getFatDashboard` (`lib/faturacao.js:94`), `Card`/`CardContent`, `MonthPicker`,
  `Select…`, `PageHeader`.
- Produz: o componente por omissão `Resumo`.

- [ ] **Passo 1: escrever `pages/admin/Resumo.js`**

```jsx
// O Resumo do gestor: quatro cartões, só leitura, feito para um telemóvel.
//
// Este ficheiro NÃO importa nenhuma função de escrita, e é de propósito: o
// PainelGlobal (o irmão deste, no computador) tem lá dentro sincronizações e o
// «Ligar ao RH», e nada disso pode existir num ecrã que se abre com o polegar
// dentro do autocarro. Todas as decisões estão em lib/resumo.js, corridas por
// lib/resumo.test.js. Aqui só se desenha o que elas decidiram.
import React, { useState, useEffect, useCallback } from 'react';
import {
  getFinCompanies, getFinGlobalDashboard, getEstoqueOverview, getAdminDashboard,
} from '../../lib/api';
import { getFatDashboard } from '../../lib/faturacao';
import {
  pede, cartaoVendas, cartaoFinanceiro, cartaoRh, cartaoEstoque, OK,
} from '../../lib/resumo';
import { Card, CardContent } from '../../components/ui/card';
import MonthPicker from '../../components/MonthPicker';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '../../components/ui/select';
import {
  TrendingUp, CircleDollarSign, Users, Package, ArrowUp, ArrowDown, RefreshCw,
} from 'lucide-react';

const LS_KEY = 'fin_selected_company';
const mesActual = () => new Date().toISOString().slice(0, 7);

function Variacao({ valor }) {
  if (valor == null) return null;
  const sobe = valor >= 0;
  const Seta = sobe ? ArrowUp : ArrowDown;
  return (
    <span className={`inline-flex items-center gap-0.5 text-xs font-medium ${sobe ? 'text-emerald-600' : 'text-red-600'}`}>
      <Seta className="h-3 w-3" />
      {Math.abs(valor).toLocaleString('pt-PT', { maximumFractionDigits: 1 })}%
    </span>
  );
}

function Bloco({ titulo, icone: Icone, cartao, destaque = false }) {
  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex items-center gap-2 mb-3">
          <Icone className="h-4 w-4 text-muted-foreground shrink-0" />
          <h2 className="text-sm font-medium text-muted-foreground">{titulo}</h2>
        </div>

        {cartao.estado !== OK || cartao.linhas.length === 0 ? (
          <p className="text-sm text-muted-foreground">{cartao.mensagem}</p>
        ) : (
          <div className="space-y-3">
            {cartao.linhas.map((l) => (
              <div key={l.rotulo} className="flex items-baseline justify-between gap-3">
                <span className="text-sm text-muted-foreground truncate">{l.rotulo}</span>
                <span className="flex items-baseline gap-2 shrink-0">
                  <span className={`${destaque ? 'text-2xl' : 'text-base'} font-heading font-bold ${l.alerta ? 'text-red-600' : ''}`}>
                    {l.valor}
                  </span>
                  <Variacao valor={l.variacao} />
                </span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function Resumo() {
  const [empresas, setEmpresas] = useState([]);
  const [empresaId, setEmpresaId] = useState(localStorage.getItem(LS_KEY) || '');
  const [mes, setMes] = useState(mesActual());
  const [cartoes, setCartoes] = useState(null);
  const [aCarregar, setACarregar] = useState(false);

  useEffect(() => {
    pede(getFinCompanies).then((r) => {
      const lista = r.ok && Array.isArray(r.data) ? r.data : [];
      setEmpresas(lista);
      if (!empresaId && lista.length) setEmpresaId(lista[0].id);
    });
    // só à entrada: a lista de empresas não muda com o mês
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const carregar = useCallback(async () => {
    setACarregar(true);
    if (empresaId) localStorage.setItem(LS_KEY, empresaId);
    // Os quatro em paralelo e cada um por sua conta: `pede` não deixa nenhum
    // lançar, por isso um 403 no Financeiro não apaga os outros três.
    //
    // SEM empresa não se chama o Financeiro — e trata-se isso como o 403 que
    // é. Quem não é membro de empresa nenhuma (o Financeiro é por pertença,
    // não por papel: `fin_role_of` não tem atalho para admin) recebia uma
    // lista vazia, e um `return` aqui deixava o ecrã presos em «A carregar…»
    // para sempre. Vendas, RH e Estoque não dependem da empresa escolhida.
    const [fin, fat, est, rh] = await Promise.all([
      empresaId
        ? pede(() => getFinGlobalDashboard({ company_id: empresaId, month: mes }))
        : Promise.resolve({ ok: false, status: 403 }),
      pede(() => getFatDashboard(true)),
      pede(getEstoqueOverview),
      pede(getAdminDashboard),
    ]);
    setCartoes({
      vendas: cartaoVendas(fat),
      financeiro: cartaoFinanceiro(fin),
      rh: cartaoRh(rh),
      estoque: cartaoEstoque(est),
    });
    setACarregar(false);
  }, [empresaId, mes]);

  useEffect(() => { carregar(); }, [carregar]);

  return (
    <div className="space-y-4 pb-8">
      <div className="flex items-center gap-2">
        <Select value={empresaId} onValueChange={setEmpresaId}>
          <SelectTrigger className="flex-1"><SelectValue placeholder="Empresa" /></SelectTrigger>
          <SelectContent>
            {empresas.map((e) => (
              <SelectItem key={e.id} value={e.id}>{e.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <MonthPicker value={mes} onChange={setMes} />
        <button
          type="button"
          onClick={carregar}
          aria-label="Atualizar"
          className="h-10 w-10 flex items-center justify-center rounded-md border shrink-0"
        >
          <RefreshCw className={`h-4 w-4 ${aCarregar ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {!cartoes ? (
        <p className="text-sm text-muted-foreground px-1">A carregar…</p>
      ) : (
        <div className="space-y-4">
          <Bloco titulo="Vendas" icone={TrendingUp} cartao={cartoes.vendas} destaque />
          <Bloco titulo="Financeiro" icone={CircleDollarSign} cartao={cartoes.financeiro} />
          <Bloco titulo="RH" icone={Users} cartao={cartoes.rh} />
          <Bloco titulo="Estoque" icone={Package} cartao={cartoes.estoque} />
        </div>
      )}
    </div>
  );
}
```

- [ ] **Passo 2: registar a rota no `App.js`**

Junto aos outros `import` de páginas de admin:

```js
import Resumo from './pages/admin/Resumo';
```

E logo a seguir a `<Route index element={<AdminDashboard />} />`:

```jsx
        <Route path="resumo" element={<Resumo />} />
```

- [ ] **Passo 3: confirmar que compila**

```bash
cd ~/Developer/RH/frontend && export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH" && CI=false npx craco build 2>&1 | tail -20
```

Esperado: `Compiled successfully` (ou só avisos). Se falhar, ler o erro e corrigir
antes de commitar.

- [ ] **Passo 4: commit**

```bash
cd ~/Developer/RH && git add frontend/src/pages/admin/Resumo.js frontend/src/App.js && git commit -m "O ecrã Resumo do gestor, só-leitura, na rota /admin/resumo"
```

---

### Tarefa 3: a aterragem na app

**Ficheiros:**
- Modificar: `frontend/src/App.js` (o `RoleRedirect`, por volta da linha 137)

**Interfaces:**
- Consome da Tarefa 1: `rotaDeAterragem`.
- Consome do que já existe: `Capacitor` de `@capacitor/core` (padrão já usado em
  `lib/geo.js`, `lib/statusbar.js`, `EmployeeLayout.js:65`).

- [ ] **Passo 1: os testes já existem**

`rotaDeAterragem` já está coberta pela Tarefa 1 (bloco `describe('rotaDeAterragem')`).
Esta tarefa só a liga ao `App.js`. Confirmar que continua verde:

```bash
cd ~/Developer/RH/frontend && export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH" && CI=true npx craco test --watchAll=false --testPathPattern="resumo"
```

- [ ] **Passo 2: usar a função no `RoleRedirect`**

No topo do `App.js`, com os outros imports:

```js
import { Capacitor } from '@capacitor/core';
import { rotaDeAterragem } from './lib/resumo';
```

No fim do `RoleRedirect`, substituir

```jsx
  return <Navigate to={['admin', 'gerente', 'contabilista'].includes(user.role) ? '/admin' : '/colaborador'} replace />;
```

por

```jsx
  // Dentro da APP, um gestor aterra no Resumo; no browser, onde sempre aterrou.
  return <Navigate to={rotaDeAterragem({
    nativo: Capacitor.isNativePlatform(), papel: user.role,
  })} replace />;
```

**Só no `RoleRedirect`.** O `ProtectedRoute` e o `ChangePasswordRoute` têm a mesma
linha e ficam como estão: quem lá cai já está a pedir uma página concreta, e
mandá-lo para o Resumo tirava-lhe o ecrã que pediu.

- [ ] **Passo 3: confirmar que compila**

```bash
cd ~/Developer/RH/frontend && export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH" && CI=false npx craco build 2>&1 | tail -20
```

Esperado: `Compiled successfully`.

- [ ] **Passo 4: ver no browser antes de embrulhar em app nenhuma**

```bash
cd ~/Developer/RH/frontend && export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH" && npx craco start
```

Abrir `http://localhost:3000/admin/resumo`, entrar como admin, e reduzir a janela
para largura de telemóvel (~390px). Confirmar, com os olhos: os quatro cartões
empilham-se numa coluna; o ecrã não anda de lado; nenhum cartão mostra `0,00 €`
quando diz «Sem acesso». **Um ecrã que compila não é um ecrã que funciona** — dois
defeitos deste projeto foram para produção assim.

- [ ] **Passo 5: commit**

```bash
cd ~/Developer/RH && git add frontend/src/App.js && git commit -m "Na app, o gestor aterra no Resumo em vez do painel de admin"
```

---

### Tarefa 4: pôr no TestFlight

**Ficheiros:** nenhum de código. `frontend/ios/App/App.xcodeproj` (versão).

> **A app NÃO existe na App Store Connect.** Confirmado pelo dono a 2026-08-30:
> a conta só tem a app L'Açaí. O `com.lisbonb.rh` nunca foi registado, e não há
> um único perfil de aprovisionamento neste Mac — este projeto iOS nunca foi
> assinado. Os passos 1 a 3 abaixo criam a ficha; sem eles, o *Archive* falha.

- [ ] **Passo 1: registar o App ID (no Xcode, deixa-o fazer sozinho)**

```bash
cd ~/Developer/RH/frontend && npx cap open ios
```

No Xcode, separador **App → Signing & Capabilities**:
- **Automatically manage signing** ligado;
- **Team**: escolher o team. O projeto traz `P58HVPWKS8` gravado — é a conta onde
  vive a app L'Açaí. Para TestFlight interno serve; se quiser a Lisbonb numa
  conta própria, é outra subscrição de programador (99 €/ano) e o team muda aqui.

O Xcode regista o identificador `com.lisbonb.rh` no portal Apple sozinho. Se
aparecer um erro a vermelho nesse painel, **parar** e resolvê-lo — é o único
sítio onde este problema se vê antes de custar tempo.

- [ ] **Passo 2: criar a ficha da app na App Store Connect**

Em appstoreconnect.apple.com → **Apps → + → Nova app**:
- Plataforma **iOS**; Nome: `Gestão Lisbonb`; Idioma principal: Português;
- **Bundle ID**: `com.lisbonb.rh` (só aparece na lista depois do Passo 1);
- SKU: `lisbonb-rh`.

Não é preciso preencher preço, capturas de ecrã nem descrição: nada disso é
exigido para **TestFlight interno**.

- [ ] **Passo 3: dar acesso ao Bruce e à Débora**

Testador **interno** de TestFlight é um **utilizador da App Store Connect** — não
basta ter o email. Em **Utilizadores e Acesso**, convidar o Apple ID de cada um
(função *Developer* ou *Marketing* chega) e garantir o acesso a TestFlight.
Cada um aceita o convite no email antes de conseguir instalar.

Testadores internos não passam por revisão da Apple. (A alternativa, testadores
externos, exigiria *Beta App Review* — não é preciso para três pessoas.)

- [ ] **Passo 4: build da web a apontar para produção**

```bash
cd ~/Developer/RH/frontend && export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH" && yarn build:mobile
```

- [ ] **Passo 5: confirmar a trava do backend (a mesma que o script do Android faz)**

```bash
cd ~/Developer/RH/frontend && grep -rq "https://rh.lisbonb.com" build/static/js/*.js && echo "OK: backend no bundle" || echo "ABORTAR: falta o backend no bundle"
```

Esperado: `OK: backend no bundle`. Se disser ABORTAR, **parar** — a app não
falaria com o servidor.

- [ ] **Passo 6: sincronizar o iOS**

```bash
cd ~/Developer/RH/frontend && export PATH="$HOME/.local/node/bin:$HOME/Library/pnpm:$PATH" && npx cap sync ios
```

- [ ] **Passo 7: subir a versão e arquivar (Xcode, à mão)**

```bash
cd ~/Developer/RH/frontend && npx cap open ios
```

No Xcode: em *App → General*, pôr **Build 13** (está em 12) e deixar a versão em
1.0.11 — ou 1.0.12 se preferir marcar a novidade. Depois *Product → Archive* →
*Distribute App* → **TestFlight**. À primeira subida, a Apple pergunta pela
*Export Compliance*: a app só usa HTTPS, o que conta como criptografia isenta.

- [ ] **Passo 8: distribuir a build aos três**

Em App Store Connect → TestFlight → **Testes internos** → criar o grupo e juntar
os três utilizadores convidados no Passo 3. Cada um instala pela app TestFlight.
Nota: uma build de TestFlight caduca ao fim de **90 dias** — passado esse prazo é
preciso subir outra.

- [ ] **Passo 9: exercitar o caminho a sério, no iPhone**

Entrar na app com cada uma das três contas e confirmar que o Resumo aparece com
números reais. **É aqui que se descobre se o Bruce e a Débora são membros da
empresa no Financeiro**: se não forem, o cartão Financeiro diz «Sem acesso» e
adicionam-se em Financeiro → equipa. Ver a app instalada é a única prova que
conta; nada até aqui a deu.

- [ ] **Passo 10: publicar pelo fluxo da casa**

Usar a skill `fluxo` (parte B): juntar `matheus-resumo-do-gestor` ao `main`,
empurrar, e publicar o `main` no servidor. O site ganha a rota `/admin/resumo`
mas nada muda para quem usa o browser.

---

## Fora deste plano

Notificações push, gráficos, exportar, filtro por loja nas vendas, modo offline,
automatizar o build de iOS no `scripts/build-app-release.sh`, e qualquer ecrã de
edição. Nada disto foi pedido.
