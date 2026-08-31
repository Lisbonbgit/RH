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

/** Um número que veio mesmo do servidor.
 *  O zero VERDADEIRO conta; o que falta não. Uma string vazia não é zero —
 *  `Number("")` é 0 e é finito, e era por aí que um campo em falta se
 *  transformava num «0,00 €» com ar de dado real. */
const veioNumero = (v) => {
  if (typeof v === 'number') return Number.isFinite(v);
  if (typeof v === 'string') return v.trim() !== '' && Number.isFinite(Number(v));
  return false;
};

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
