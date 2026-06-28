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
