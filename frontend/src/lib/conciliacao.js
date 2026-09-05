// Aritmética dos cartões da Conciliação. Sem React e sem HTTP de propósito:
// é a parte que tem de estar certa ao cêntimo, e assim tem teste.

export const descricaoDoMovimento = (mv) =>
  (mv && (mv.title || mv.description)) || '(sem descrição)';

// Soma por categoria, na ordem da lista da empresa. O total mantém o SINAL
// (entradas positivas, despesas negativas): quem mostra é que decide se põe o
// valor absoluto, como no Excel.
export const resumoPorCategoria = (movimentos, categorias) => {
  const somas = new Map();
  for (const mv of movimentos || []) {
    const id = mv.category || 'sem_categoria';
    somas.set(id, (somas.get(id) || 0) + (Number(mv.amount) || 0));
  }
  const conhecidas = new Set((categorias || []).map((c) => c.id));
  const linhas = (categorias || []).map((c) => ({
    id: c.id, label: c.label, total: somas.get(c.id) || 0,
  }));
  // Categorias legadas e o que está por classificar entram no fim. Não se
  // escondem: são exatamente o trabalho que falta fazer.
  for (const [id, total] of somas) {
    if (conhecidas.has(id)) continue;
    linhas.push({ id, label: id === 'sem_categoria' ? 'Sem categoria' : id, total });
  }
  return linhas;
};

// Cada categoria em % das Entradas. `pct` é null quando não há entradas —
// desconhecido não é zero.
export const percentagensSobreEntradas = (linhas) => {
  const entradas = (linhas || []).find((l) => l.id === 'entradas');
  const base = Math.abs((entradas && entradas.total) || 0);
  return (linhas || [])
    .filter((l) => l.id !== 'entradas')
    .map((l) => ({
      id: l.id, label: l.label,
      pct: base ? (Math.abs(l.total) / base) * 100 : null,
    }));
};

// O cartão "Plataformas" do Excel: as entradas agrupadas pela descrição que
// ela própria escreveu ("Glovo", "Fecho TPA Teya"). Sem campo novo nenhum.
export const plataformasDasEntradas = (movimentos) => {
  const somas = new Map();
  for (const mv of movimentos || []) {
    if (mv.category !== 'entradas') continue;
    const nome = descricaoDoMovimento(mv);
    somas.set(nome, (somas.get(nome) || 0) + (Number(mv.amount) || 0));
  }
  return [...somas.entries()]
    .map(([nome, total]) => ({ nome, total: Math.round(total * 100) / 100 }))
    .sort((a, b) => b.total - a.total);
};
