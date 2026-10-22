// Calendário das lojas na Gestão Lisbonb — as contas do ecrã, sem React e sem rede.
//
// O servidor manda o mês inteiro num pedido (`GET /api/bolso/calendario`, montado por
// `backend/calendario.py::resposta_do_mes`); daqui sai o que o ecrã desenha: a grelha, os
// pontos, a Semana, a Lista, a Contagem, o filtro de loja e o atalho das outras terças. Tudo
// puro, corrido em Node a partir da suite do backend (`backend/tests/calendario/test_lib_calendario.py`).

import { quandoFoi } from './bolso';

export const MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
  'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];
// 0 = segunda … 6 = domingo, como o `work_days` do servidor.
export const DIAS_DA_SEMANA = ['segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado', 'domingo'];
const NO_PLURAL = ['segundas', 'terças', 'quartas', 'quintas', 'sextas', 'sábados', 'domingos'];
export const VISTAS = ['semana', 'mes', 'lista', 'contagem'];
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

// --- A Semana: lojas × 7 dias, de segunda a domingo ------------------------------------------

// Em UTC não há horas de verão: somar um dia é sempre somar um dia (a 25/10, com 25 horas,
// somar 24 h à meia-noite local deixava-nos no mesmo dia).
export const diaAoLado = (iso, passo) => {
  const d = new Date(Date.UTC(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8)) + passo));
  return isoDe(d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate());
};

// O domingo FECHA a semana (0 = segunda … 6 = domingo).
export const semanaDe = (iso) => {
  const segunda = diaAoLado(iso, -diaDaSemana(iso));
  return [0, 1, 2, 3, 4, 5, 6].map((n) => diaAoLado(segunda, n));
};

// Os meses a pedir ao servidor: 1, ou 2 quando a semana atravessa o mês.
export const mesesDaSemana = (iso) => [...new Set(semanaDe(iso).map((d) => d.slice(0, 7)))]
  .map((m) => ({ ano: Number(m.slice(0, 4)), mes: Number(m.slice(5)) }));

// «5 – 11 out», «26 out – 1 nov», «29 dez – 4 jan» (jan, fev, … dez são as 3 primeiras letras).
const diaEMesCurto = (iso) => `${Number(iso.slice(8))} ${MESES[Number(iso.slice(5, 7)) - 1].slice(0, 3)}`;
export const tituloDaSemana = (iso) => {
  const [segunda, , , , , , domingo] = semanaDe(iso);
  const inicio = segunda.slice(0, 7) === domingo.slice(0, 7) ? Number(segunda.slice(8)) : diaEMesCurto(segunda);
  return `${inicio} – ${diaEMesCurto(domingo)}`;
};

export const nomeCurtoDaLoja = (nome) => String(nome || '').replace(/^Loja /, '');

// Uma célula da Semana a partir de `dias[].lojas[]` do servidor (`undefined` = a loja não está
// nesse dia: por abrir). Geral = a cobertura; Pessoal = as horas das MINHAS idas lá.
export function celulaDaSemana(loja, filtro, eu) {
  const vazia = { estado: 'vazia', texto: '' };
  if (!loja) return vazia;
  if (filtro === 'pessoal') {
    const minhas = (loja.pessoas || []).filter((p) => p.origem === 'ida' && p.user_id === eu);
    return minhas.length ? { estado: 'minha', texto: minhas.map((p) => intervaloCurto(p.inicio, p.fim)).join(' · ') } : vazia;
  }
  if (loja.estado === 'fechada') return { estado: 'fechada', texto: 'fech.' };
  const buracos = loja.buracos || [];
  if (!buracos.length) return { estado: 'ok', texto: 'ok' };
  if (buracos.length > 1) return { estado: 'falta', texto: `${buracos.length} faltas` };
  const [b] = buracos;
  if (b.inicio === loja.abre && b.fim === loja.fecha) return { estado: 'ninguem', texto: '—' };
  return { estado: 'falta', texto: intervaloCurto(b.inicio, b.fim) };
}

// Uma semana que atravessa dois meses pede os dois ao servidor e junta-os aqui. A ausência que
// toca os dois meses vem nas duas respostas (não traz id: compara-se inteira). O resto
// (lojas, pessoas, eu, pode_marcar) não depende do mês: vem da primeira.
export function juntarMeses(respostas) {
  const vistas = new Set();
  const ausencias = respostas.flatMap((r) => r.ausencias || []).filter((a) => {
    const chave = JSON.stringify(a);
    if (vistas.has(chave)) return false;
    vistas.add(chave);
    return true;
  });
  return {
    ...respostas[0],
    dias: respostas.flatMap((r) => r.dias || []),
    idas: respostas.flatMap((r) => r.idas || []),
    ausencias,
  };
}

// O filtro de loja: só essa loja nos dias, nas idas e nas lojas, e as ausências de quem tem
// essa loja na ficha. Sem loja, os dados tal como vieram. Nunca mexe nos dados recebidos.
export function filtrarPorLoja(dados, locationId) {
  if (!locationId || !dados) return dados;
  return {
    ...dados,
    dias: (dados.dias || []).map((d) => ({ ...d, lojas: (d.lojas || []).filter((l) => l.location_id === locationId) })),
    idas: (dados.idas || []).filter((i) => i.location_id === locationId),
    lojas: (dados.lojas || []).filter((l) => l.id === locationId),
    ausencias: (dados.ausencias || []).filter((a) => a.location_id === locationId),
  };
}

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

// Quem está na escala nesse dia (todas as lojas: chama-se com o mês SEM o filtro de loja),
// para o «Trocar com…»: sem quem sai, sem quem não tem conta no RH (não se troca), uma linha
// por pessoa (a primeira, se uma ida lhe partiu a escala), por nome.
export function escaladosDoDia(dados, iso, saiUserId) {
  const dia = (dados?.dias || []).find((d) => d.data === iso);
  const vistos = new Set();
  const escalados = [];
  for (const loja of dia?.lojas || []) {
    for (const p of loja.pessoas || []) {
      if (p.origem !== 'escala' || !p.user_id || p.user_id === saiUserId || vistos.has(p.user_id)) continue;
      vistos.add(p.user_id);
      escalados.push({ user_id: p.user_id, nome: p.nome, location_id: loja.location_id, loja: loja.nome,
        inicio: p.inicio, fim: p.fim });
    }
  }
  return escalados.sort((a, b) => a.nome.localeCompare(b.nome, 'pt'));
}

// Uma entrada do histórico (`GET /api/bolso/calendario/historico`, retratos com os nomes já
// escritos) numa linha: «20/10 às 14:32 · Carol · trocou Emily por Beatrice em Alfragide,
// 14h–23h · 27/10». O «(conta removida)» do servidor fica inteiro.
const diaEMes = (iso) => `${Number(iso.slice(8))}/${iso.slice(5, 7)}`;
const nomeCurto = (nome) => (String(nome || '').startsWith('(') ? nome : primeiroNome(nome));
const lojaEHoras = (r) => `${nomeCurtoDaLoja(r.loja)}, ${intervaloCurto(r.inicio, r.fim)}`;
const ondeEQuando = (r) => `${nomeCurtoDaLoja(r.loja)} ${intervaloCurto(r.inicio, r.fim)}, ${diaEMes(r.data)}`;
// Na troca entre si cada pessoa vai para a loja da outra: a loja de origem de uma é a da ida da outra.
const entreSi = ([a, b]) => (
  `${nomeCurto(a.nome)} (${nomeCurtoDaLoja(b.loja)}) com ${nomeCurto(b.nome)} (${nomeCurtoDaLoja(a.loja)})`);

function oQueFez(acao, antes, depois) {
  const [a] = antes;
  const [d] = depois;
  switch (acao) {
    case 'marcou':
      return `marcou ${[...new Set(depois.map((r) => nomeCurto(r.nome)))].join(' e ')} em ${lojaEHoras(d)}`;
    case 'alterou':
      return `alterou a ida de ${nomeCurto(a.nome)}: ${ondeEQuando(a)} → ${
        d.nome !== a.nome ? `${nomeCurto(d.nome)} em ` : ''}${ondeEQuando(d)}`;
    case 'apagou':
      return `apagou a ida de ${nomeCurto(a.nome)} em ${lojaEHoras(a)}`;
    case 'trocou':
      return `trocou ${nomeCurto(d.no_lugar_de)} por ${nomeCurto(d.nome)} em ${lojaEHoras(d)}`;
    case 'trocou entre si':
      return `trocou ${entreSi(depois)}`;
    case 'desfez a troca':
      return antes.length > 1 ? `desfez a troca de ${entreSi(antes)}`
        : `desfez a troca de ${nomeCurto(a.no_lugar_de)} por ${nomeCurto(a.nome)} em ${nomeCurtoDaLoja(a.loja)}`;
    default:
      return acao;
  }
}

export function linhaDoHistorico(entrada) {
  const { acao } = entrada;
  const datas = entrada.datas || [];
  const dias = datas.slice(0, 3).map(diaEMes).join(', ') + (datas.length > 3 ? ` e mais ${datas.length - 3}` : '');
  return [quandoFoi(entrada.quando), nomeCurto(entrada.quem_nome),
    oQueFez(acao, entrada.antes || [], entrada.depois || []),
    acao === 'alterou' ? '' : dias].filter(Boolean).join(' · ');
}

// O texto de um erro do servidor tal como ele o escreveu (as regras do calendário já dizem o
// que aconteceu e o que fazer). Sem resposta não se sabe nada — e diz-se isso.
export function mensagemDeErro(e) {
  if (!e?.response) return 'Sem resposta do servidor. Verifique a rede e tente outra vez.';
  const detalhe = e.response.data?.detail;
  if (typeof detalhe === 'string') return detalhe;
  if (Array.isArray(detalhe)) return detalhe.map((d) => d?.msg || String(d)).join('\n');
  return 'O servidor recusou este pedido.';
}
