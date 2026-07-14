// Helpers partilhados do módulo Financeiro.
// A chave de fornecedor TEM de coincidir com a do backend (_fin_norm_sup / fin_supplier_key_of)
// para que as regras criadas no servidor sejam encontradas no frontend.

export const eur = (n) =>
  (Number(n) || 0).toLocaleString('pt-PT', { style: 'currency', currency: 'EUR' });

export const normSup = (s) =>
  (s || '')
    .toLowerCase()
    .normalize('NFD').replace(/[̀-ͯ]/g, '') // tira acentos (á->a, ç->c, ñ->n)
    .replace(/\b(lda|ld|limitada|unipessoal|s\.?a|sa|sociedade)\b/g, ' ')
    .replace(/[^a-z0-9 ]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

export const supplierKeyOf = (nif, supplier) => {
  const d = String(nif || '').replace(/\D+/g, '');
  return d ? `n:${d}` : `t:${normSup(supplier)}`;
};

export const todayISO = () => new Date().toISOString().slice(0, 10);

// Vencimento efetivo: se a regra tiver prazo, usa emissão + N dias (ignora o vencimento da fatura).
export const effectiveDue = (inv, rule) => {
  if (rule && rule.pay_term_days != null && inv.issue_date) {
    const d = new Date(inv.issue_date + 'T00:00:00');
    d.setDate(d.getDate() + Number(rule.pay_term_days));
    return d.toISOString().slice(0, 10);
  }
  return inv.due_date || inv.issue_date || null;
};

// Formata 'YYYY-MM-DD' para 'dd/mm/aaaa' (sem dependências de fuso).
export const fmtDate = (iso) => {
  if (!iso) return '-';
  const [y, m, d] = String(iso).slice(0, 10).split('-');
  return d && m && y ? `${d}/${m}/${y}` : iso;
};

// Paleta dos cartões KPI, igual à secção RH (cada indicador uma cor). Índice
// ciclico para linhas de vários cartões.
export const KPI_TONES = [
  { icon: 'text-blue-600 dark:text-blue-400', bg: 'bg-blue-50 dark:bg-blue-500/10' },
  { icon: 'text-teal-600 dark:text-teal-400', bg: 'bg-teal-50 dark:bg-teal-500/10' },
  { icon: 'text-amber-600 dark:text-amber-400', bg: 'bg-amber-50 dark:bg-amber-500/10' },
  { icon: 'text-rose-600 dark:text-rose-400', bg: 'bg-rose-50 dark:bg-rose-500/10' },
  { icon: 'text-violet-600 dark:text-violet-400', bg: 'bg-violet-50 dark:bg-violet-500/10' },
  { icon: 'text-cyan-600 dark:text-cyan-400', bg: 'bg-cyan-50 dark:bg-cyan-500/10' },
  { icon: 'text-emerald-600 dark:text-emerald-400', bg: 'bg-emerald-50 dark:bg-emerald-500/10' },
  { icon: 'text-indigo-600 dark:text-indigo-400', bg: 'bg-indigo-50 dark:bg-indigo-500/10' },
];
export const kpiTone = (i) => KPI_TONES[((i % KPI_TONES.length) + KPI_TONES.length) % KPI_TONES.length];
