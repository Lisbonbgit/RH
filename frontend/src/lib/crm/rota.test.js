/**
 * A ROTA DE UM DIA NO FRONTEND — motivos, secções, avisos, totais e a visão otimista (F3 / T3.27).
 *
 * O servidor manda a rota já arrumada (`GET /rotas/{data}`, plano F3 §4): as paragens ativas por `ordem`,
 * cada uma com a `seccao` ("rota", "fechada", "nao_cabe", "sem_loja"), o `numero` (1..k só na secção
 * "rota"), o `aviso` e os `links`; o `calculo` com o `atual`; os `blocos_google`. O `rota.js` só lê isso:
 *   - os textos (motivos, estados, avisos, distância e duração) e os totais do cálculo;
 *   - `seccoesDaRota`, `avisosDaRota`, `precisaDeHoras` e `perguntaGuardar`;
 *   - `aplicarLocalmente(rota, corpo)`, a visão otimista de um `PATCH` (ordem, retirar, motivo, tempo,
 *     sinais, definições do dia e estado), com as mesmas regras do servidor (`dominio.rotas.seccoes`,
 *     `aviso`, `nova_ordem` e o `_alteracoes`/`_sem_horas_nem_calculo` do `crm/rotas.py`): os números da
 *     secção "rota" ficam coerentes, as horas deixam de ser atuais quando muda o que as decide, e o que
 *     só o servidor sabe montar (os links de navegação) sai até à resposta em vez de ficar errado;
 *   - `corpoOrdem(rota, idsRota)`, o corpo de um arrastar na secção "rota".
 *
 * MOTIVOS, MOTIVO_POR_FASE e LIMITE_PARAGENS ficam numa só linha cada, comparadas com o
 * `backend/crm/dominio/rotas.py` nos dois sentidos: aqui (lendo o `.py`) e no
 * `backend/tests/crm/test_consistencia_frontend.py` (lendo o `.js`).
 */
import fs from 'fs';
import path from 'path';

import { ORDEM } from './fases';
import {
  LIMITE_PARAGENS,
  MOTIVOS,
  MOTIVO_POR_FASE,
  ROTULOS_ESTADO,
  ROTULOS_MOTIVO,
  TEXTOS_AVISO,
  TEXTO_WAZE_PORTAGENS,
  aplicarLocalmente,
  avisosDaRota,
  corpoOrdem,
  motivoPorFase,
  perguntaGuardar,
  precisaDeHoras,
  rotuloEstado,
  rotuloMotivo,
  seccoesDaRota,
  textoAviso,
  textoDistancia,
  textoDuracao,
  totaisDaRota,
} from './rota';

// frontend/src/lib/crm → raiz do repositório.
const RAIZ = path.join(__dirname, '..', '..', '..', '..');
const ROTAS_PY = path.join(RAIZ, 'backend', 'crm', 'dominio', 'rotas.py');
const ROTA_JS = path.join(__dirname, 'rota.js');

// --- Uma rota da API (plano F3 §4) ----------------------------------------------------------------

// 2026-10-12 é uma segunda-feira ('seg').
const DIA = '2026-10-12';
const FABRICA = Object.freeze({ lat: 38.75, lng: -9.2 });

function loja(nome, extra = {}) {
  return {
    nome,
    fase: 'contactada',
    lat: 38.7,
    lng: -9.1,
    telefone: '',
    janela1_inicio: null,
    janela1_fim: null,
    janela2_inicio: null,
    janela2_fim: null,
    dias_fechada: [],
    ...extra,
  };
}

const linksDe = (id) => ({
  google: `https://www.google.com/maps/dir/?api=1&destination=${id}`,
  waze: `https://waze.com/ul?ll=${id}&navigate=yes`,
});

function paragem(id, ordem, { seccao = 'rota', numero = null, aviso = 'nenhum', semLoja = false, ...extra } = {}) {
  return {
    id,
    loja_id: `loja-${id}`,
    numero,
    seccao,
    ordem,
    motivo: 'amostra',
    tempo_servico_min: 10,
    manter_fechada: false,
    nao_cabe: false,
    chegada_prevista: seccao === 'rota' ? `09:${String(ordem).padStart(2, '0')}` : null,
    espera_min: seccao === 'rota' ? 0 : null,
    fora_de_horario: false,
    aviso,
    estado: 'pendente',
    resultado: null,
    links: semLoja ? null : linksDe(id),
    loja: semLoja ? null : loja(`Loja ${id}`),
    ...extra,
  };
}

// A, C e E na rota (1, 2 e 3; E fora do horário), B fechada à segunda, D não cabe, F de uma loja apagada.
function exemplo(extra = {}) {
  return {
    id: 'rota-1',
    data: DIA,
    existe: true,
    estado: 'rascunho',
    estado_efetivo: 'rascunho',
    editavel: true,
    versao: 3,
    hoje: DIA,
    hora_saida: '08:00',
    hora_regresso_limite: '19:00',
    evitar_portagens: false,
    inicio: { ...FABRICA, fabrica: true },
    fim: { ...FABRICA, fabrica: true },
    limite_paragens: 48,
    calculo_disponivel: true,
    calculo: {
      atual: true,
      distancia_m: 123456,
      duracao_s: 19260,
      regresso_previsto: '19:40',
      depois_do_limite: true,
      geometria: '_p~iF~ps|U_ulLnnqC',
      calculado_em: '2026-10-12T07:00:00.000000+00:00',
    },
    paragens: [
      paragem('A', 0, { numero: 1 }),
      paragem('B', 1, { seccao: 'fechada', aviso: 'fechada_neste_dia', loja: loja('Loja B', { dias_fechada: ['seg', 'dom'] }) }),
      paragem('C', 2, { numero: 2 }),
      paragem('D', 3, { seccao: 'nao_cabe', aviso: 'nao_cabe', nao_cabe: true }),
      paragem('E', 4, { numero: 3, aviso: 'fora_de_horario', fora_de_horario: true }),
      paragem('F', 5, { seccao: 'sem_loja', semLoja: true }),
    ],
    blocos_google: [{ de: 1, ate: 3, quantas: 3, rotulo: 'Paragens 1–3', href: 'https://www.google.com/maps/dir/?api=1&destination=E' }],
    ...extra,
  };
}

function congelar(valor) {
  if (valor !== null && typeof valor === 'object' && !Object.isFrozen(valor)) {
    Object.values(valor).forEach(congelar);
    Object.freeze(valor);
  }
  return valor;
}

const ids = (paragens) => paragens.map((p) => p.id);
const resumo = (rota) => rota.paragens.map((p) => `${p.id}:${p.seccao}:${p.numero ?? '-'}:${p.ordem}:${p.aviso}`);
const porId = (rota, id) => rota.paragens.find((p) => p.id === id);

// --- As constantes e a consistência com o servidor -------------------------------------------------

test('MOTIVOS, MOTIVO_POR_FASE e LIMITE_PARAGENS (plano F3 §1)', () => {
  expect([...MOTIVOS]).toEqual(['entrega', 'amostra', 'acompanhamento', 'angariacao']);
  expect(Object.isFrozen(MOTIVOS)).toBe(true);
  expect({ ...MOTIVO_POR_FASE }).toEqual({
    perdida: 'angariacao',
    potencial: 'angariacao',
    contactada: 'amostra',
    amostra: 'acompanhamento',
    fecho: 'acompanhamento',
    cliente: 'acompanhamento',
  });
  expect(Object.keys(MOTIVO_POR_FASE)).toEqual([...ORDEM]);
  for (const motivo of Object.values(MOTIVO_POR_FASE)) expect(MOTIVOS).toContain(motivo);
  expect(Object.isFrozen(MOTIVO_POR_FASE)).toBe(true);
  expect(LIMITE_PARAGENS).toBe(48);
});

test('as três constantes estão numa só linha cada (o test_consistencia_frontend.py lê-as assim)', () => {
  const texto = fs.readFileSync(ROTA_JS, 'utf8');
  const contar = (padrao) => [...texto.matchAll(padrao)].length;
  expect(contar(/^export const MOTIVOS = Object\.freeze\(\[[^\]\n]*\]\);$/gm)).toBe(1);
  expect(contar(/^export const MOTIVO_POR_FASE = Object\.freeze\(\{ [^{}\n]* \}\);$/gm)).toBe(1);
  expect(contar(/^export const LIMITE_PARAGENS = [0-9]+;$/gm)).toBe(1);
});

describe('igual ao backend/crm/dominio/rotas.py, lido do próprio ficheiro', () => {
  // Falha, e não salta, se o ficheiro não estiver lá: um guarda que se desliga sozinho passava sempre.
  const python = () => {
    expect(fs.existsSync(ROTAS_PY)).toBe(true);
    return fs.readFileSync(ROTAS_PY, 'utf8');
  };
  // Os textos de cada linha `NOME = ("a", "b")` do rotas.py (tem de haver exatamente uma).
  const tuplo = (nome) => {
    const linhas = [...python().matchAll(new RegExp(`^${nome} = \\(([^)\\n]*)\\)$`, 'gm'))];
    expect(linhas).toHaveLength(1);
    return [...linhas[0][1].matchAll(/"([^"]*)"/g)].map((m) => m[1]);
  };

  test('MOTIVOS', () => {
    expect([...MOTIVOS]).toEqual(tuplo('MOTIVOS'));
  });

  test('MOTIVO_POR_FASE, pela mesma ordem', () => {
    const linhas = [...python().matchAll(/^MOTIVO_POR_FASE = MappingProxyType\(\{([^}\n]*)\}\)$/gm)];
    expect(linhas).toHaveLength(1);
    const pares = [...linhas[0][1].matchAll(/"([a-z_]+)": "([a-z_]+)"/g)].map((m) => [m[1], m[2]]);
    expect(pares).toHaveLength(6);
    expect(Object.entries(MOTIVO_POR_FASE)).toEqual(pares);
  });

  test('LIMITE_PARAGENS', () => {
    const linhas = [...python().matchAll(/^LIMITE_PARAGENS = ([0-9]+)$/gm)];
    expect(linhas).toHaveLength(1);
    expect(LIMITE_PARAGENS).toBe(Number(linhas[0][1]));
  });

  test('os rótulos dos estados são os ESTADOS, pela mesma ordem', () => {
    expect(Object.keys(ROTULOS_ESTADO)).toEqual(tuplo('ESTADOS'));
  });

  test('os textos dos avisos são os AVISOS menos o "nenhum"', () => {
    const avisos = tuplo('AVISOS');
    expect(avisos[0]).toBe('nenhum');
    expect(Object.keys(TEXTOS_AVISO)).toEqual(avisos.slice(1));
  });

  test('cada uma das SECCOES cai num só grupo do seccoesDaRota', () => {
    const seccoes = tuplo('SECCOES');
    expect(seccoes).toHaveLength(4);
    const rota = { paragens: seccoes.map((seccao, i) => ({ id: `p${i}`, seccao })) };
    const grupos = seccoesDaRota(rota);
    const onde = seccoes.map((_, i) => Object.keys(grupos).filter((g) => ids(grupos[g]).includes(`p${i}`)));
    expect(onde).toEqual([['rota'], ['fechadas'], ['naoCabem'], ['semLoja']]);
  });
});

// --- Textos -----------------------------------------------------------------------------------------

test('os rótulos dos motivos e dos estados e os textos dos avisos', () => {
  expect({ ...ROTULOS_MOTIVO }).toEqual({
    entrega: 'Entrega',
    amostra: 'Amostra',
    acompanhamento: 'Acompanhamento',
    angariacao: 'Angariação',
  });
  expect(Object.keys(ROTULOS_MOTIVO)).toEqual([...MOTIVOS]);
  expect({ ...ROTULOS_ESTADO }).toEqual({
    rascunho: 'Rascunho',
    planeada: 'Planeada',
    em_curso: 'Em curso',
    concluida: 'Concluída',
  });
  expect({ ...TEXTOS_AVISO }).toEqual({
    fechada_neste_dia: '⚠️ Fechada neste dia',
    nao_cabe: '⚠️ Não cabe no horário',
    fora_de_horario: '⚠️ Fora do horário de receção',
  });
  for (const mapa of [ROTULOS_MOTIVO, ROTULOS_ESTADO, TEXTOS_AVISO]) expect(Object.isFrozen(mapa)).toBe(true);
});

// Correção "T3.10" do plano da F3: o `avoid_tolls=true` do Waze não está na documentação dos links do Waze
// (lá, evitar portagens é uma definição da app). Com "Evitar portagens" ligado, o detalhe da paragem
// (`ListaParagens`, T3.36) diz-o junto do link do Waze.
test('o aviso do Waze com as portagens evitadas é o texto fixado na correção "T3.10"', () => {
  expect(TEXTO_WAZE_PORTAGENS).toBe("No Waze, confirme 'Evitar portagens' nas definições da app");
});

test.each([
  [rotuloMotivo, 'angariacao', 'Angariação'],
  [rotuloMotivo, 'entrega', 'Entrega'],
  [rotuloMotivo, 'visita', null],
  [rotuloMotivo, 'constructor', null],
  [rotuloMotivo, '__proto__', null],
  [rotuloMotivo, null, null],
  [rotuloEstado, 'em_curso', 'Em curso'],
  [rotuloEstado, 'concluida', 'Concluída'],
  [rotuloEstado, null, null],
  [rotuloEstado, 'toString', null],
  [textoAviso, 'nao_cabe', '⚠️ Não cabe no horário'],
  [textoAviso, 'fora_de_horario', '⚠️ Fora do horário de receção'],
  [textoAviso, 'nenhum', null],
  [textoAviso, 'hasOwnProperty', null],
  [textoAviso, undefined, null],
])('%p(%p) → %p', (funcao, valor, esperado) => {
  expect(funcao(valor)).toBe(esperado);
});

test.each([
  ['perdida', 'angariacao'],
  ['potencial', 'angariacao'],
  ['contactada', 'amostra'],
  ['amostra', 'acompanhamento'],
  ['fecho', 'acompanhamento'],
  ['cliente', 'acompanhamento'],
  ['xpto', 'angariacao'],
  ['Cliente', 'angariacao'],
  ['constructor', 'angariacao'],
  ['__proto__', 'angariacao'],
  ['', 'angariacao'],
  [null, 'angariacao'],
  [undefined, 'angariacao'],
  [['cliente'], 'angariacao'],
  [3, 'angariacao'],
])('motivoPorFase(%p) → %p (uma fase desconhecida ainda está por angariar)', (fase, esperado) => {
  expect(motivoPorFase(fase)).toBe(esperado);
});

test.each([
  [123456, '123,5 km'],
  [123449, '123,4 km'],
  [800, '0,8 km'],
  [1200, '1,2 km'],
  [1950, '2,0 km'],
  [49, '0,0 km'],
  [50, '0,1 km'],
  [0, '0,0 km'],
  [1000000, '1000,0 km'],
])('textoDistancia(%p) → %p', (metros, esperado) => {
  expect(textoDistancia(metros)).toBe(esperado);
});

test.each([
  [19260, '5 h 21 min'],
  [3600, '1 h'],
  [7200, '2 h'],
  [2700, '45 min'],
  [3629, '1 h'],
  [3630, '1 h 1 min'],
  [3570, '1 h'],
  [29, '0 min'],
  [30, '1 min'],
  [0, '0 min'],
  [36000 + 59 * 60, '10 h 59 min'],
])('textoDuracao(%p) → %p', (segundos, esperado) => {
  expect(textoDuracao(segundos)).toBe(esperado);
});

test.each([[-1], [NaN], [Infinity], [null], [undefined], ['100'], [true], [{}]])(
  'textoDistancia e textoDuracao de %p → null',
  (valor) => {
    expect(textoDistancia(valor)).toBe(null);
    expect(textoDuracao(valor)).toBe(null);
  },
);

test('totaisDaRota: os totais do último cálculo, com o atual (null sem cálculo)', () => {
  expect(totaisDaRota(exemplo())).toEqual({
    distancia: '123,5 km',
    duracao: '5 h 21 min',
    regresso: '19:40',
    regressoTarde: true,
    atual: true,
  });
  const velho = exemplo();
  velho.calculo = { ...velho.calculo, atual: false, regresso_previsto: null, depois_do_limite: false };
  expect(totaisDaRota(velho)).toEqual({
    distancia: '123,5 km',
    duracao: '5 h 21 min',
    regresso: null,
    regressoTarde: false,
    atual: false,
  });
  // A tempo (com hora) e depois da meia-noite (sem hora, mas tarde).
  const aTempo = exemplo();
  aTempo.calculo = { ...aTempo.calculo, regresso_previsto: '18:10', depois_do_limite: false };
  expect(totaisDaRota(aTempo)).toMatchObject({ regresso: '18:10', regressoTarde: false });
  const meiaNoite = exemplo();
  meiaNoite.calculo = { ...meiaNoite.calculo, regresso_previsto: null, depois_do_limite: true };
  expect(totaisDaRota(meiaNoite)).toMatchObject({ regresso: null, regressoTarde: true });
  expect(totaisDaRota(exemplo({ calculo: null }))).toBe(null);
  expect(totaisDaRota(null)).toBe(null);
});

// --- Secções ----------------------------------------------------------------------------------------

test('seccoesDaRota separa as paragens pela secção do servidor, pela ordem, com os mesmos objetos', () => {
  const rota = exemplo();
  const grupos = seccoesDaRota(rota);
  expect(Object.keys(grupos)).toEqual(['rota', 'fechadas', 'naoCabem', 'semLoja']);
  expect(ids(grupos.rota)).toEqual(['A', 'C', 'E']);
  expect(ids(grupos.fechadas)).toEqual(['B']);
  expect(ids(grupos.naoCabem)).toEqual(['D']);
  expect(ids(grupos.semLoja)).toEqual(['F']);
  expect(grupos.rota[1]).toBe(rota.paragens[2]);
});

test('seccoesDaRota sem paragens, de uma rota virtual ou estragada, e com uma secção desconhecida', () => {
  const vazio = { rota: [], fechadas: [], naoCabem: [], semLoja: [] };
  expect(seccoesDaRota(exemplo({ paragens: [] }))).toEqual(vazio);
  expect(seccoesDaRota(null)).toEqual(vazio);
  expect(seccoesDaRota({})).toEqual(vazio);
  expect(seccoesDaRota({ paragens: 'x' })).toEqual(vazio);
  const estranha = seccoesDaRota({ paragens: [{ id: 'X', seccao: 'outra' }, { id: 'Y', seccao: 'constructor' }, null] });
  expect(estranha).toEqual(vazio);
});

// --- Avisos -----------------------------------------------------------------------------------------

test('avisosDaRota: o regresso tarde, as fechadas e as que não cabem, por esta ordem', () => {
  const rota = exemplo();
  rota.paragens.push(
    paragem('G', 6, { seccao: 'fechada', aviso: 'fechada_neste_dia', loja: loja('Loja G', { dias_fechada: ['seg'] }) }),
    paragem('H', 7, { seccao: 'nao_cabe', aviso: 'nao_cabe', nao_cabe: true }),
  );
  expect(avisosDaRota(rota)).toEqual([
    'Regresso previsto às 19:40 — depois do limite (19:00).',
    '2 paragens fechadas neste dia ficam fora do cálculo até escolher "Manter".',
    '2 paragens não cabem no horário.',
  ]);
});

test('avisosDaRota no singular', () => {
  expect(avisosDaRota(exemplo())).toEqual([
    'Regresso previsto às 19:40 — depois do limite (19:00).',
    '1 paragem fechada neste dia fica fora do cálculo até escolher "Manter".',
    '1 paragem não cabe no horário.',
  ]);
  const so = exemplo({ calculo: null });
  so.paragens = so.paragens.filter((p) => p.id !== 'B');
  expect(avisosDaRota(so)).toEqual(['1 paragem não cabe no horário.']);
});

test('avisosDaRota: o regresso só com horas atuais e depois do limite; sem hora, depois da meia-noite', () => {
  const semAvisos = (calculo) => {
    const rota = exemplo({ calculo });
    rota.paragens = rota.paragens.filter((p) => p.seccao === 'rota');
    return avisosDaRota(rota);
  };
  const base = exemplo().calculo;
  expect(semAvisos(base)).toEqual(['Regresso previsto às 19:40 — depois do limite (19:00).']);
  expect(semAvisos({ ...base, atual: false })).toEqual([]);
  expect(semAvisos({ ...base, depois_do_limite: false, regresso_previsto: '18:10' })).toEqual([]);
  expect(semAvisos(null)).toEqual([]);
  expect(semAvisos({ ...base, regresso_previsto: null })).toEqual([
    'Regresso previsto depois da meia-noite — depois do limite (19:00).',
  ]);
  const outroLimite = exemplo({ hora_regresso_limite: '17:30', paragens: [] });
  expect(avisosDaRota(outroLimite)).toEqual(['Regresso previsto às 19:40 — depois do limite (17:30).']);
  expect(avisosDaRota(null)).toEqual([]);
});

// --- Horas automáticas e Guardar ---------------------------------------------------------------------

describe('precisaDeHoras: há chave, a rota é editável, tem incluídas, as horas não são atuais e não falhou', () => {
  const velha = (extra = {}) => {
    const rota = exemplo(extra);
    if (rota.calculo) rota.calculo = { ...rota.calculo, atual: false };
    return rota;
  };

  test('com tudo, sim (também sem cálculo nenhum)', () => {
    expect(precisaDeHoras(velha())).toBe(true);
    expect(precisaDeHoras(velha(), { falhou: false })).toBe(true);
    expect(precisaDeHoras(velha({ calculo: null }))).toBe(true);
  });

  test.each([
    ['as horas já são atuais', () => exemplo()],
    ['sem chave do openrouteservice', () => velha({ calculo_disponivel: false })],
    ['só de leitura', () => velha({ editavel: false })],
    ['sem paragens', () => velha({ paragens: [] })],
    ['só fechadas, não cabem e sem loja', () => velha({ paragens: exemplo().paragens.filter((p) => p.seccao !== 'rota') })],
    ['uma rota virtual', () => velha({ existe: false, id: null, versao: null, calculo: null, paragens: [] })],
    ['o calculo_disponivel em texto', () => velha({ calculo_disponivel: 'true' })],
    ['o editavel em número', () => velha({ editavel: 1 })],
  ])('não: %s', (_, rota) => {
    expect(precisaDeHoras(rota())).toBe(false);
  });

  test('não depois de uma falha (até à próxima alteração ou ao botão)', () => {
    expect(precisaDeHoras(velha(), { falhou: true })).toBe(false);
  });

  test('não com uma rota que não existe', () => {
    expect(precisaDeHoras(null)).toBe(false);
    expect(precisaDeHoras(undefined, { falhou: false })).toBe(false);
  });
});

test('perguntaGuardar: só quando há paragens que não cabem', () => {
  const rota = exemplo();
  expect(perguntaGuardar(rota)).toBe('1 paragem não cabe — guardar mesmo assim?');
  rota.paragens.push(paragem('H', 6, { seccao: 'nao_cabe', aviso: 'nao_cabe', nao_cabe: true }));
  expect(perguntaGuardar(rota)).toBe('2 paragens não cabem — guardar mesmo assim?');
  // As fechadas não contam: ficam fora do cálculo, mas não são "não cabe".
  const semNaoCabe = exemplo();
  semNaoCabe.paragens = semNaoCabe.paragens.filter((p) => p.seccao !== 'nao_cabe');
  expect(perguntaGuardar(semNaoCabe)).toBe(null);
  expect(perguntaGuardar(exemplo({ paragens: [] }))).toBe(null);
  expect(perguntaGuardar(null)).toBe(null);
});

// --- corpoOrdem ----------------------------------------------------------------------------------------

describe('corpoOrdem: a secção "rota" pela ordem pedida, depois as que não cabem e as fechadas', () => {
  test('o arrastar na secção "rota"', () => {
    expect(corpoOrdem(exemplo(), ['E', 'A', 'C'])).toEqual({ ordem: ['E', 'A', 'C', 'D', 'B'] });
  });

  test('várias que não cabem e várias fechadas, cada grupo pela sua ordem', () => {
    const rota = exemplo();
    rota.paragens.splice(
      1,
      0,
      paragem('H', 9, { seccao: 'nao_cabe', aviso: 'nao_cabe', nao_cabe: true }),
      paragem('G', 8, { seccao: 'fechada', aviso: 'fechada_neste_dia', loja: loja('Loja G', { dias_fechada: ['seg'] }) }),
    );
    expect(corpoOrdem(rota, ['C', 'E', 'A'])).toEqual({ ordem: ['C', 'E', 'A', 'H', 'D', 'G', 'B'] });
  });

  test('ids de fora da secção, repetidos ou desconhecidos não entram; as da rota em falta vão no fim da secção', () => {
    expect(corpoOrdem(exemplo(), ['C', 'B', 'C', 'X', 'D', 'F'])).toEqual({ ordem: ['C', 'A', 'E', 'D', 'B'] });
    expect(corpoOrdem(exemplo(), [])).toEqual({ ordem: ['A', 'C', 'E', 'D', 'B'] });
    expect(corpoOrdem(exemplo(), null)).toEqual({ ordem: ['A', 'C', 'E', 'D', 'B'] });
  });

  test('as de uma loja apagada ficam de fora (o servidor põe-nas no fim)', () => {
    expect(corpoOrdem(exemplo(), ['A', 'C', 'E']).ordem).not.toContain('F');
  });

  test('aplicado localmente, numera a secção "rota" pela ordem nova', () => {
    const rota = exemplo();
    const depois = aplicarLocalmente(rota, corpoOrdem(rota, ['E', 'A', 'C']));
    expect(resumo(depois)).toEqual([
      'E:rota:1:0:nenhum',
      'A:rota:2:1:nenhum',
      'C:rota:3:2:nenhum',
      'D:nao_cabe:-:3:nao_cabe',
      'B:fechada:-:4:fechada_neste_dia',
      'F:sem_loja:-:5:nenhum',
    ]);
  });
});

// --- aplicarLocalmente -----------------------------------------------------------------------------

describe('aplicarLocalmente: a visão otimista de um PATCH', () => {
  test('não mexe na rota recebida e devolve uma rota nova', () => {
    const rota = congelar(exemplo());
    const depois = aplicarLocalmente(rota, {
      ordem: ['C', 'A'],
      retirar: ['E'],
      paragens: { B: { manter_fechada: true }, D: { nao_cabe: false }, A: { motivo: 'entrega', tempo_servico_min: 20 } },
      hora_saida: '07:30',
      hora_regresso_limite: '18:00',
      evitar_portagens: true,
      inicio: { lat: 38.8, lng: -9.3 },
      fim: null,
      estado: 'planeada',
    });
    expect(depois).not.toBe(rota);
    expect(depois.paragens).not.toBe(rota.paragens);
    expect(rota).toEqual(exemplo());
  });

  test('um corpo vazio (ou só com a versão) dá uma rota igual, nova', () => {
    for (const corpo of [{}, null, undefined, { versao: 9 }]) {
      const rota = exemplo();
      const depois = aplicarLocalmente(rota, corpo);
      expect(depois).toEqual(exemplo());
      expect(depois).not.toBe(rota);
    }
  });

  test('só conta o que vai no JSON do pedido: nem chaves herdadas, nem valores undefined', () => {
    const herdado = Object.create({
      evitar_portagens: true,
      estado: 'planeada',
      retirar: ['A'],
      ordem: ['E'],
      hora_saida: '07:00',
      paragens: { D: { nao_cabe: false } },
    });
    expect(aplicarLocalmente(exemplo(), herdado)).toEqual(exemplo());
    expect(aplicarLocalmente(exemplo(), { paragens: Object.create({ D: { nao_cabe: false } }) })).toEqual(exemplo());
    expect(aplicarLocalmente(exemplo(), { paragens: { D: Object.create({ nao_cabe: false }) } })).toEqual(exemplo());
    expect(aplicarLocalmente(exemplo(), { inicio: undefined, ordem: undefined, hora_saida: undefined, paragens: { A: undefined } })).toEqual(
      exemplo(),
    );
    // O que vai no JSON conta, venha de onde vier.
    expect(aplicarLocalmente(exemplo(), { ...herdado, evitar_portagens: true }).evitar_portagens).toBe(true);
  });

  test('a versão é a da rota (a do corpo é para o servidor)', () => {
    expect(aplicarLocalmente(exemplo(), { versao: 7, hora_saida: '07:00' }).versao).toBe(3);
  });

  describe('a ordem (leniente, como o nova_ordem do servidor)', () => {
    test('as pedidas primeiro, as outras ativas a seguir pela ordem delas', () => {
      const depois = aplicarLocalmente(exemplo(), { ordem: ['C', 'A'] });
      expect(resumo(depois)).toEqual([
        'C:rota:1:0:nenhum',
        'A:rota:2:1:nenhum',
        'B:fechada:-:2:fechada_neste_dia',
        'D:nao_cabe:-:3:nao_cabe',
        'E:rota:3:4:nenhum',
        'F:sem_loja:-:5:nenhum',
      ]);
    });

    test('mudar a ordem da secção "rota" torna as horas velhas: sem fora de horário e sem blocos do Google', () => {
      const rota = exemplo();
      const depois = aplicarLocalmente(rota, { ordem: ['C', 'A'] });
      expect(depois.calculo).toEqual({ ...rota.calculo, atual: false });
      expect(porId(depois, 'E').aviso).toBe('nenhum');
      expect(porId(depois, 'E').fora_de_horario).toBe(true);
      expect(porId(depois, 'A').chegada_prevista).toBe('09:00');
      expect(depois.blocos_google).toEqual([]);
      // Os links de cada paragem não dependem da ordem.
      expect(porId(depois, 'A').links).toEqual(linksDe('A'));
    });

    test('a mesma ordem da secção "rota" mantém as horas, os avisos e os blocos', () => {
      const rota = exemplo();
      for (const ordem of [['A', 'C', 'E'], ['A', 'D', 'C', 'B', 'E'], ['A', 'B', 'C', 'D', 'E', 'F'], []]) {
        const depois = aplicarLocalmente(rota, { ordem });
        expect(depois.calculo).toBe(rota.calculo);
        expect(porId(depois, 'E').aviso).toBe('fora_de_horario');
        expect(depois.blocos_google).toBe(rota.blocos_google);
      }
    });

    test('mexer só nas que não estão na rota não toca nas horas', () => {
      const depois = aplicarLocalmente(exemplo(), { ordem: ['D', 'B'] });
      expect(ids(depois.paragens)).toEqual(['D', 'B', 'A', 'C', 'E', 'F']);
      expect(depois.paragens.map((p) => p.numero)).toEqual([null, null, 1, 2, 3, null]);
      expect(depois.calculo.atual).toBe(true);
    });

    test('ids desconhecidos ou repetidos não contam (o servidor recusa-os com 422)', () => {
      const depois = aplicarLocalmente(exemplo(), { ordem: ['X', 'E', 'E', 'C', 7, null] });
      expect(ids(depois.paragens)).toEqual(['E', 'C', 'A', 'B', 'D', 'F']);
      expect(aplicarLocalmente(exemplo(), { ordem: 'E' })).toEqual(exemplo());
    });
  });

  describe('retirar', () => {
    test('a paragem sai, as outras renumeram-se e as horas ficam velhas', () => {
      const depois = aplicarLocalmente(exemplo(), { retirar: ['A'] });
      expect(resumo(depois)).toEqual([
        'B:fechada:-:0:fechada_neste_dia',
        'C:rota:1:1:nenhum',
        'D:nao_cabe:-:2:nao_cabe',
        'E:rota:2:3:nenhum',
        'F:sem_loja:-:4:nenhum',
      ]);
      expect(depois.calculo.atual).toBe(false);
      expect(depois.blocos_google).toEqual([]);
    });

    test('com a ordem no mesmo corpo: os retirados saem da ordem', () => {
      const depois = aplicarLocalmente(exemplo(), { ordem: ['E', 'A', 'C'], retirar: ['A'] });
      expect(ids(depois.paragens)).toEqual(['E', 'C', 'B', 'D', 'F']);
      expect(depois.paragens.map((p) => p.numero)).toEqual([1, 2, null, null, null]);
    });

    test('retirar uma que não está na rota não faz mal; retirar a que não cabe mantém as horas', () => {
      expect(aplicarLocalmente(exemplo(), { retirar: ['X'] })).toEqual(exemplo());
      const depois = aplicarLocalmente(exemplo(), { retirar: ['D'] });
      expect(ids(depois.paragens)).toEqual(['A', 'B', 'C', 'E', 'F']);
      expect(depois.calculo.atual).toBe(true);
      expect(porId(depois, 'E').aviso).toBe('fora_de_horario');
    });

    test('sem nenhuma na secção "rota", o cálculo e as horas limpam-se (correção "T3.20 / T3.27")', () => {
      const rota = exemplo();
      // Horas velhas numa que não está na rota: também se limpam, como no servidor ("F3-MAT-2").
      rota.paragens[1] = { ...rota.paragens[1], chegada_prevista: '10:00', espera_min: 5, fora_de_horario: true };
      const depois = aplicarLocalmente(rota, { retirar: ['A', 'C', 'E'] });
      expect(depois.calculo).toBe(null);
      expect(resumo(depois)).toEqual([
        'B:fechada:-:0:fechada_neste_dia',
        'D:nao_cabe:-:1:nao_cabe',
        'F:sem_loja:-:2:nenhum',
      ]);
      for (const p of depois.paragens) {
        expect([p.chegada_prevista, p.espera_min, p.fora_de_horario]).toEqual([null, null, false]);
      }
      expect(depois.blocos_google).toEqual([]);
      expect(totaisDaRota(depois)).toBe(null);
    });

    test('retirar todas', () => {
      const depois = aplicarLocalmente(exemplo(), { retirar: ['A', 'B', 'C', 'D', 'E', 'F'] });
      expect(depois.paragens).toEqual([]);
      expect(depois.calculo).toBe(null);
    });
  });

  describe('as alterações de cada paragem', () => {
    test('o motivo muda e o tempo fica (o padrão do motivo novo vem na resposta do servidor)', () => {
      const rota = exemplo();
      const depois = aplicarLocalmente(rota, { paragens: { A: { motivo: 'entrega' } } });
      expect(porId(depois, 'A').motivo).toBe('entrega');
      expect(porId(depois, 'A').tempo_servico_min).toBe(10);
      expect(depois.calculo).toBe(rota.calculo);
    });

    test('o tempo de uma incluída torna as horas velhas; o de uma fechada não', () => {
      const depois = aplicarLocalmente(exemplo(), { paragens: { C: { tempo_servico_min: 25 } } });
      expect(porId(depois, 'C').tempo_servico_min).toBe(25);
      expect(depois.calculo.atual).toBe(false);
      expect(depois.blocos_google).toEqual(exemplo().blocos_google);
      const fechada = aplicarLocalmente(exemplo(), { paragens: { B: { tempo_servico_min: 25 } } });
      expect(porId(fechada, 'B').tempo_servico_min).toBe(25);
      expect(fechada.calculo.atual).toBe(true);
      // O mesmo tempo que já tinha não muda nada.
      expect(aplicarLocalmente(exemplo(), { paragens: { C: { tempo_servico_min: 10 } } }).calculo.atual).toBe(true);
    });

    test.each([
      [{ motivo: 'visita' }],
      [{ motivo: 'Entrega' }],
      [{ motivo: null }],
      [{ tempo_servico_min: 0 }],
      [{ tempo_servico_min: 241 }],
      [{ tempo_servico_min: 1.5 }],
      [{ tempo_servico_min: '10' }],
      [{ tempo_servico_min: true }],
      [{ tempo_servico_min: NaN }],
      [{ manter_fechada: 'sim' }],
      [{ manter_fechada: 1 }],
      [{ nao_cabe: true }],
      [{ nao_cabe: 0 }],
      [{ estado: 'feita' }],
      [{ ordem: 0 }],
      [{ chegada_prevista: '07:00' }],
      [{ loja_id: 'outra' }],
    ])('o que o servidor recusaria não muda nada: %p', (alteracoes) => {
      for (const id of ['A', 'B', 'D']) {
        expect(aplicarLocalmente(exemplo(), { paragens: { [id]: alteracoes } })).toEqual(exemplo());
      }
    });

    test('os tempos de 1 e de 240 minutos servem', () => {
      expect(porId(aplicarLocalmente(exemplo(), { paragens: { A: { tempo_servico_min: 1 } } }), 'A').tempo_servico_min).toBe(1);
      expect(porId(aplicarLocalmente(exemplo(), { paragens: { A: { tempo_servico_min: 240 } } }), 'A').tempo_servico_min).toBe(240);
    });

    test('"Manter" põe a fechada na rota, numerada pela ordem, e torna as horas velhas', () => {
      const depois = aplicarLocalmente(exemplo(), { paragens: { B: { manter_fechada: true } } });
      expect(resumo(depois)).toEqual([
        'A:rota:1:0:nenhum',
        'B:rota:2:1:nenhum',
        'C:rota:3:2:nenhum',
        'D:nao_cabe:-:3:nao_cabe',
        'E:rota:4:4:nenhum',
        'F:sem_loja:-:5:nenhum',
      ]);
      expect(porId(depois, 'B').manter_fechada).toBe(true);
      expect(depois.calculo.atual).toBe(false);
      expect(depois.blocos_google).toEqual([]);
    });

    test('tirar o "Manter" a uma loja fechada nesse dia volta a pô-la nas fechadas', () => {
      const rota = exemplo();
      rota.paragens[1] = { ...rota.paragens[1], seccao: 'rota', numero: 2, aviso: 'nenhum', manter_fechada: true };
      rota.paragens[2] = { ...rota.paragens[2], numero: 3 };
      rota.paragens[4] = { ...rota.paragens[4], numero: 4 };
      const depois = aplicarLocalmente(rota, { paragens: { B: { manter_fechada: false } } });
      expect(resumo(depois).slice(0, 3)).toEqual(['A:rota:1:0:nenhum', 'B:fechada:-:1:fechada_neste_dia', 'C:rota:2:2:nenhum']);
      expect(depois.calculo.atual).toBe(false);
    });

    test('"Manter" numa loja aberta nesse dia não a tira da rota', () => {
      const depois = aplicarLocalmente(exemplo(), { paragens: { A: { manter_fechada: true } } });
      expect(porId(depois, 'A').manter_fechada).toBe(true);
      expect(resumo(depois)).toEqual(resumo(exemplo()));
      expect(depois.calculo.atual).toBe(true);
    });

    test('"Pôr na rota" (nao_cabe: false) volta a numerar a que não cabia', () => {
      const depois = aplicarLocalmente(exemplo(), { paragens: { D: { nao_cabe: false } } });
      expect(resumo(depois)).toEqual([
        'A:rota:1:0:nenhum',
        'B:fechada:-:1:fechada_neste_dia',
        'C:rota:2:2:nenhum',
        'D:rota:3:3:nenhum',
        'E:rota:4:4:nenhum',
        'F:sem_loja:-:5:nenhum',
      ]);
      expect(porId(depois, 'D').nao_cabe).toBe(false);
      expect(depois.calculo.atual).toBe(false);
    });

    test('a fechada que também não cabe fica fechada até ao "Manter", e depois não cabe', () => {
      const rota = exemplo();
      rota.paragens[1] = { ...rota.paragens[1], nao_cabe: true };
      expect(porId(aplicarLocalmente(rota, {}), 'B').seccao).toBe('fechada');
      const mantida = aplicarLocalmente(rota, { paragens: { B: { manter_fechada: true } } });
      expect(porId(mantida, 'B')).toMatchObject({ seccao: 'nao_cabe', numero: null, aviso: 'nao_cabe' });
    });

    test('a de uma loja apagada fica sem loja, mesmo com "Manter" ou "Pôr na rota"', () => {
      const depois = aplicarLocalmente(exemplo(), { paragens: { F: { manter_fechada: true, nao_cabe: false } } });
      expect(porId(depois, 'F')).toMatchObject({ seccao: 'sem_loja', numero: null, aviso: 'nenhum', links: null });
    });

    test('paragens que não estão na rota, ou um objeto que não é de alterações, não contam', () => {
      expect(aplicarLocalmente(exemplo(), { paragens: { X: { motivo: 'entrega' } } })).toEqual(exemplo());
      expect(aplicarLocalmente(exemplo(), { paragens: ['A'] })).toEqual(exemplo());
      expect(aplicarLocalmente(exemplo(), { paragens: { A: null, C: 'entrega' } })).toEqual(exemplo());
      expect(aplicarLocalmente(exemplo(), { paragens: { constructor: { motivo: 'entrega' } } })).toEqual(exemplo());
    });

    test('a retirada no mesmo corpo sai, e as alterações dela não contam', () => {
      const depois = aplicarLocalmente(exemplo(), { retirar: ['B'], paragens: { B: { manter_fechada: true } } });
      expect(ids(depois.paragens)).toEqual(['A', 'C', 'D', 'E', 'F']);
      expect(depois.calculo.atual).toBe(true);
    });
  });

  describe('as definições do dia', () => {
    test.each([
      [{ hora_saida: '07:30' }, 'hora_saida', '07:30'],
      [{ hora_regresso_limite: '18:00' }, 'hora_regresso_limite', '18:00'],
    ])('%p muda e torna as horas velhas', (corpo, campo, valor) => {
      const depois = aplicarLocalmente(exemplo(), corpo);
      expect(depois[campo]).toBe(valor);
      expect(depois.calculo.atual).toBe(false);
      expect(porId(depois, 'E').aviso).toBe('nenhum');
      // Os blocos do Google não dependem das horas.
      expect(depois.blocos_google).toEqual(exemplo().blocos_google);
    });

    test('os mesmos valores não mudam nada', () => {
      const rota = exemplo();
      const depois = aplicarLocalmente(rota, { hora_saida: '08:00', hora_regresso_limite: '19:00', evitar_portagens: false });
      expect(depois).toEqual(exemplo());
      expect(depois.calculo).toBe(rota.calculo);
      expect(depois.blocos_google).toBe(rota.blocos_google);
    });

    test('evitar portagens torna as horas velhas e tira os links até à resposta do servidor', () => {
      const depois = aplicarLocalmente(exemplo(), { evitar_portagens: true });
      expect(depois.evitar_portagens).toBe(true);
      expect(depois.calculo.atual).toBe(false);
      expect(depois.blocos_google).toEqual([]);
      for (const p of depois.paragens) expect(p.links).toBe(null);
    });

    test.each([
      [{ hora_saida: 730 }],
      [{ hora_saida: null }],
      [{ hora_saida: '7:30' }],
      [{ hora_saida: '24:00' }],
      [{ hora_saida: '08:60' }],
      [{ hora_saida: '08:00\n' }],
      [{ hora_regresso_limite: '' }],
      [{ hora_regresso_limite: ['18:00'] }],
      [{ evitar_portagens: 'sim' }],
      [{ evitar_portagens: null }],
      [{ estado: 'rascunho' }],
      [{ estado: 'concluida' }],
      [{ inicio: 'fabrica' }],
      [{ inicio: { lat: '38.8', lng: -9.3 } }],
      [{ fim: { lat: 38.8 } }],
      [{ fim: { lat: NaN, lng: -9.3 } }],
      [{ inicio: [38.8, -9.3] }],
      [{ ainda_nao_existe: true }],
    ])('o que o servidor recusaria não muda nada: %p', (corpo) => {
      expect(aplicarLocalmente(exemplo(), corpo)).toEqual(exemplo());
    });

    test('um ponto no mapa como início ou fim', () => {
      const depois = aplicarLocalmente(exemplo(), { inicio: { lat: 38.8, lng: -9.3 } });
      expect(depois.inicio).toEqual({ lat: 38.8, lng: -9.3, fabrica: false });
      expect(depois.fim).toEqual({ ...FABRICA, fabrica: true });
      expect(depois.calculo.atual).toBe(false);
      const fim = aplicarLocalmente(exemplo(), { fim: { lat: 39.1, lng: -8.9, outro: 1 } });
      expect(fim.fim).toEqual({ lat: 39.1, lng: -8.9, fabrica: false });
    });

    describe('a fábrica (null)', () => {
      const comPonto = () => exemplo({ inicio: { lat: 38.8, lng: -9.3, fabrica: false }, fim: { lat: 39.1, lng: -8.9, fabrica: false } });

      test('com a fábrica das definições (o centro do GET /config)', () => {
        const depois = aplicarLocalmente(comPonto(), { inicio: null }, { fabrica: { lat: 38.6, lng: -9.0 } });
        expect(depois.inicio).toEqual({ lat: 38.6, lng: -9.0, fabrica: true });
        expect(depois.fim).toEqual({ lat: 39.1, lng: -8.9, fabrica: false });
        expect(depois.calculo.atual).toBe(false);
      });

      test('sem ela, a da outra ponta, se for a fábrica', () => {
        const rota = comPonto();
        rota.fim = { ...FABRICA, fabrica: true };
        expect(aplicarLocalmente(rota, { inicio: null }).inicio).toEqual({ ...FABRICA, fabrica: true });
      });

      test('já é a fábrica: fica (e as horas também)', () => {
        const rota = exemplo();
        const depois = aplicarLocalmente(rota, { inicio: null, fim: null }, { fabrica: FABRICA });
        expect(depois.inicio).toEqual({ ...FABRICA, fabrica: true });
        expect(depois.calculo).toBe(rota.calculo);
      });

      test('sem saber onde é a fábrica, a ponta fica como estava até à resposta', () => {
        for (const opcoes of [undefined, {}, { fabrica: null }, { fabrica: { lat: 'x', lng: 1 } }]) {
          const depois = aplicarLocalmente(comPonto(), { fim: null }, opcoes);
          expect(depois.fim).toEqual({ lat: 39.1, lng: -8.9, fabrica: false });
          expect(depois.calculo.atual).toBe(true);
        }
      });
    });

    test('"Guardar rota" (estado planeada)', () => {
      const depois = aplicarLocalmente(exemplo(), { estado: 'planeada' });
      expect(depois.estado).toBe('planeada');
      expect(depois.estado_efetivo).toBe('planeada');
      expect(depois.calculo.atual).toBe(true);
      expect(depois.paragens).toEqual(exemplo().paragens);
    });
  });

  describe('as horas e os avisos', () => {
    test('horas que já eram velhas continuam velhas, mesmo a voltar ao que eram', () => {
      const rota = exemplo();
      rota.calculo = { ...rota.calculo, atual: false };
      rota.paragens[4] = { ...rota.paragens[4], aviso: 'nenhum' };
      const depois = aplicarLocalmente(rota, { ordem: ['A', 'C', 'E'] });
      expect(depois.calculo.atual).toBe(false);
      expect(porId(depois, 'E').aviso).toBe('nenhum');
    });

    test('sem cálculo, continua sem cálculo', () => {
      const depois = aplicarLocalmente(exemplo({ calculo: null }), { ordem: ['C'] });
      expect(depois.calculo).toBe(null);
      expect(porId(depois, 'E').aviso).toBe('nenhum');
    });

    test('o fora de horário só na secção "rota" e com as horas atuais', () => {
      const rota = exemplo();
      rota.paragens[3] = { ...rota.paragens[3], fora_de_horario: true };
      rota.paragens[5] = { ...rota.paragens[5], fora_de_horario: true };
      const depois = aplicarLocalmente(rota, {});
      expect(porId(depois, 'D').aviso).toBe('nao_cabe');
      expect(porId(depois, 'F').aviso).toBe('nenhum');
      expect(porId(depois, 'E').aviso).toBe('fora_de_horario');
      expect(avisosDaRota(depois)).toEqual(avisosDaRota(exemplo()));
    });

    test('as secções e os números refazem-se a partir dos sinais e das lojas, como no servidor', () => {
      const rota = exemplo();
      // Números e secções baralhados: o resultado é o da regra, não o que veio.
      rota.paragens = rota.paragens.map((p) => ({ ...p, numero: 9, seccao: 'rota', aviso: 'nenhum' }));
      expect(resumo(aplicarLocalmente(rota, {}))).toEqual(resumo(exemplo()));
    });

    test('um dia que não é válido não fecha nenhuma loja', () => {
      const depois = aplicarLocalmente(exemplo({ data: '2026-02-30' }), {});
      expect(porId(depois, 'B').seccao).toBe('rota');
    });
  });
});
