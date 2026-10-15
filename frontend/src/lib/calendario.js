// Calendário das lojas na Gestão Lisbonb — as contas do ecrã, sem React e sem rede.
//
// O servidor manda o mês inteiro num pedido (`GET /api/bolso/calendario`, montado por
// `backend/calendario.py::resposta_do_mes`); daqui sai o que o ecrã desenha: a grelha, os
// pontos, a Lista, a Contagem e o atalho das outras terças. Tudo puro, corrido em Node a
// partir da suite do backend (`backend/tests/calendario/test_lib_calendario.py`).

export const MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
  'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];
// 0 = segunda … 6 = domingo, como o `work_days` do servidor.
export const DIAS_DA_SEMANA = ['segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado', 'domingo'];
const NO_PLURAL = ['segundas', 'terças', 'quartas', 'quintas', 'sextas', 'sábados', 'domingos'];
export const VISTAS = ['mes', 'lista', 'contagem'];
export const FILTROS = ['pessoal', 'geral', 'ferias'];
export const NOMES_DAS_AUSENCIAS = {
  ferias: 'Férias', folga: 'Folga', doenca: 'Doença', falta: 'Falta', ausencia: 'Ausência',
};

const dois = (n) => String(n).padStart(2, '0');
export const isoDe = (ano, mes, dia) => `${ano}-${dois(mes)}-${dois(dia)}`;

// O «hoje» é o do telemóvel, em hora LOCAL. Nunca `toISOString()`: entre a meia-noite e a
// uma da manhã de Lisboa (duas, no verão) dava o dia anterior.
export const hojeIso = (agora = new Date()) => isoDe(agora.getFullYear(), agora.getMonth() + 1, agora.getDate());

// Ao meio-dia UTC nenhum fuso muda o dia.
export const diaDaSemana = (iso) => (new Date(`${iso}T12:00:00Z`).getUTCDay() + 6) % 7;
const diasNoMes = (ano, mes) => new Date(Date.UTC(ano, mes, 0)).getUTCDate();

// As semanas do mês, de segunda a domingo, com `null` nos lugares fora do mês.
export function semanasDoMes(ano, mes) {
  const semanas = [];
  let semana = Array(diaDaSemana(isoDe(ano, mes, 1))).fill(null);
  for (let d = 1; d <= diasNoMes(ano, mes); d += 1) {
    semana.push(isoDe(ano, mes, d));
    if (semana.length === 7) { semanas.push(semana); semana = []; }
  }
  if (semana.length) semanas.push([...semana, ...Array(7 - semana.length).fill(null)]);
  return semanas;
}

export const mesAoLado = (ano, mes, passo) => {
  const n = ano * 12 + (mes - 1) + passo;
  return { ano: Math.floor(n / 12), mes: (n % 12) + 1 };
};

export const tituloDoMes = (ano, mes) => `${MESES[mes - 1]} ${ano}`;
export const tituloDoDia = (iso) => (
  `${DIAS_DA_SEMANA[diaDaSemana(iso)]}, ${Number(iso.slice(8))} de ${MESES[Number(iso.slice(5, 7)) - 1]}`);
export const dataCurta = (iso) => `${iso.slice(8)}/${iso.slice(5, 7)}`;
export const horaCurta = (hhmm) => {
  const [h, m] = String(hhmm).split(':');
  return m === '00' ? `${Number(h)}h` : `${Number(h)}h${m}`;
};
export const intervaloCurto = (inicio, fim) => `${horaCurta(inicio)}–${horaCurta(fim)}`;
export const primeiroNome = (nome) => String(nome || '').trim().split(/\s+/)[0] || '';
export const quantosDias = (n) => `${String(n).replace('.', ',')} ${n === 1 ? 'dia' : 'dias'}`;

export const minhasIdas = (dados) => (dados?.idas || []).filter((i) => i.user_id === dados.eu);
export const ausenciasDoDia = (dados, iso) => (
  (dados?.ausencias || []).filter((a) => a.inicio <= iso && iso <= a.fim));
const temBuraco = (dia) => (dia?.lojas || []).some((l) => (l.buracos || []).length > 0);

// Os dias com ponto na grelha: Geral = com buraco por tapar; Pessoal = com idas minhas;
// Férias = com ausências.
export function diasComPonto(dados, filtro) {
  const dias = dados?.dias || [];
  if (filtro === 'pessoal') {
    const meus = new Set(minhasIdas(dados).map((i) => i.data));
    return dias.map((d) => d.data).filter((d) => meus.has(d));
  }
  if (filtro === 'ferias') return dias.map((d) => d.data).filter((d) => ausenciasDoDia(dados, d).length > 0);
  return dias.filter(temBuraco).map((d) => d.data);
}

export const feriadosDoMes = (dados) => (
  (dados?.dias || []).filter((d) => (d.feriados || []).length > 0).map((d) => d.data));

// A Lista: os dias do mês com alguma coisa, a partir de hoje no mês corrente (o mês inteiro
// nos outros). Geral = buracos e idas; Pessoal = as minhas idas; Férias = cada ausência uma
// vez, no primeiro dia visível dela.
export function lista(dados, filtro, hoje) {
  const dias = dados?.dias || [];
  if (!dias.length) return [];
  const primeiro = dias.some((d) => d.data === hoje) ? hoje : dias[0].data;
  const idas = filtro === 'pessoal' ? minhasIdas(dados) : filtro === 'geral' ? (dados.idas || []) : [];
  return dias
    .filter((d) => d.data >= primeiro)
    .map((d) => ({
      data: d.data,
      buracos: filtro === 'geral' ? (d.lojas || []).filter((l) => (l.buracos || []).length > 0) : [],
      idas: idas.filter((i) => i.data === d.data),
      ausencias: filtro === 'ferias'
        ? (dados.ausencias || []).filter((a) => a.fim >= primeiro && (a.inicio > primeiro ? a.inicio : primeiro) === d.data)
        : [],
    }))
    .filter((x) => x.buracos.length || x.idas.length || x.ausencias.length);
}

// O atalho «Também nas outras terças deste mês com buraco em Oeiras»: os dias SEGUINTES do
// mesmo dia da semana em que essa loja tem um buraco que CONTÉM as horas escolhidas.
// Calculado só com a resposta do mês — sem pedidos.
export function outrosDiasComBuraco(dados, iso, locationId, inicio, fim) {
  if (!iso || !locationId || !inicio || !fim) return [];
  const semana = diaDaSemana(iso);
  return (dados?.dias || [])
    .filter((d) => d.data > iso && diaDaSemana(d.data) === semana)
    .filter((d) => (d.lojas || []).some((l) => l.location_id === locationId
      && (l.buracos || []).some((b) => b.inicio <= inicio && fim <= b.fim)))
    .map((d) => d.data);
}

export const textoDoAtalho = (iso, nomeDaLoja) => {
  const s = diaDaSemana(iso);
  return `Também ${s >= 5 ? 'nos outros' : 'nas outras'} ${NO_PLURAL[s]} deste mês com buraco em ${nomeDaLoja}`;
};

// O painel começa em mim, se eu puder ser escalado (o contabilista não pode).
export const pessoasIniciais = (dados) => (
  (dados?.pessoas || []).some((p) => p.id === dados.eu) ? [dados.eu] : []);

// «Débora · outubro 18 dias · 2026 60 dias»
export const linhaDaContagem = (linha, ano, mes) => (
  `${primeiroNome(linha.nome)} · ${MESES[mes - 1]} ${quantosDias(linha.meses[mes - 1])} · ${ano} ${quantosDias(linha.total)}`);

// O texto de um erro do servidor tal como ele o escreveu (as regras do calendário já dizem o
// que aconteceu e o que fazer). Sem resposta não se sabe nada — e diz-se isso.
export function mensagemDeErro(e) {
  if (!e?.response) return 'Sem resposta do servidor. Verifique a rede e tente outra vez.';
  const detalhe = e.response.data?.detail;
  if (typeof detalhe === 'string') return detalhe;
  if (Array.isArray(detalhe)) return detalhe.map((d) => d?.msg || String(d)).join('\n');
  return 'O servidor recusou este pedido.';
}
