// Horário das lojas e dias das escalas — a passagem entre o que o servidor guarda e
// o que os formulários dos Locais e das Escalas mostram.
//
// Funções puras, sem imports: correm em Node nos testes
// (backend/tests/calendario/test_formularios_do_portal.py).
//
// Dias: 0 = segunda … 6 = domingo, como o `work_days` das escalas.

export const DIAS_DA_SEMANA = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'];

// ---------- Locais ----------

// O formulário do horário: `tem` (a loja entra no calendário), o horário geral, e por
// cada dia um `modo` — 'geral', 'outro' (uma exceção, com horas) ou 'fechada'.
export function horarioParaFormulario(horario, abertaDesde) {
  const excecoes = new Map(((horario && horario.excecoes) || []).map((e) => [e.dia, e]));
  const fechada = new Set((horario && horario.fechada) || []);
  return {
    tem: Boolean(horario),
    abre: (horario && horario.abre) || '',
    fecha: (horario && horario.fecha) || '',
    dias: DIAS_DA_SEMANA.map((_, dia) => {
      if (fechada.has(dia)) return { modo: 'fechada', abre: '', fecha: '' };
      const e = excecoes.get(dia);
      return e ? { modo: 'outro', abre: e.abre, fecha: e.fecha } : { modo: 'geral', abre: '', fecha: '' };
    }),
    abertaDesde: abertaDesde || '',
  };
}

// O que vai no corpo do POST/PUT dos Locais. Manda SEMPRE as duas chaves: o PUT só
// escreve os campos que vêm no corpo, e é assim que tirar o horário funciona.
// Sem horário, sem data: o campo da data só se vê com o horário ligado, mas o valor
// continua guardado no formulário.
export function formularioParaHorario(form) {
  const comModo = (modo) => form.dias.map((d, dia) => ({ ...d, dia })).filter((d) => d.modo === modo);
  return {
    horario: form.tem
      ? {
          abre: form.abre,
          fecha: form.fecha,
          excecoes: comModo('outro').map(({ dia, abre, fecha }) => ({ dia, abre, fecha })),
          fechada: comModo('fechada').map(({ dia }) => dia),
        }
      : null,
    aberta_desde: form.tem && form.abertaDesde ? form.abertaDesde : null,
  };
}

// «11:30–19:00 · Dom 11:30–20:00 · fecha Ter» — para a tabela dos Locais.
export function resumoDoHorario(horario) {
  if (!horario) return '';
  const partes = [`${horario.abre}–${horario.fecha}`];
  (horario.excecoes || []).forEach((e) => partes.push(`${DIAS_DA_SEMANA[e.dia]} ${e.abre}–${e.fecha}`));
  if ((horario.fechada || []).length) {
    partes.push(`fecha ${horario.fechada.map((d) => DIAS_DA_SEMANA[d]).join(', ')}`);
  }
  return partes.join(' · ');
}

// ---------- Escalas ----------

// `dias` gravados → { [dia]: { location_id, inicio, fim } }, com '' no lugar de null
// (os <select> e <input> do formulário não aceitam null).
export function diasParaFormulario(dias) {
  const porDia = {};
  (dias || []).forEach((d) => {
    porDia[d.dia] = { location_id: d.location_id || '', inicio: d.inicio || '', fim: d.fim || '' };
  });
  return porDia;
}

// O `dias` do corpo do POST/PUT: uma entrada por dia MARCADO, por ordem. O `workDays`
// vai igual a estes dias (o servidor deriva-o daqui). Vazio = null: loja da ficha,
// horário da loja.
export function formularioParaDias(workDays, porDia) {
  return [...workDays]
    .sort((a, b) => a - b)
    .map((dia) => {
      const d = porDia[dia] || {};
      return { dia, location_id: d.location_id || null, inicio: d.inicio || null, fim: d.fim || null };
    });
}

// «Seg Amadora · Qui loja da ficha 13:00–22:00» — para a tabela das Escalas.
export function resumoDosDias(dias, nomeDaLoja) {
  return (dias || [])
    .map((d) => {
      const loja = d.location_id ? nomeDaLoja(d.location_id) || '(loja removida)' : 'loja da ficha';
      const horas = d.inicio ? ` ${d.inicio}–${d.fim}` : '';
      return `${DIAS_DA_SEMANA[d.dia]} ${loja}${horas}`;
    })
    .join(' · ');
}
