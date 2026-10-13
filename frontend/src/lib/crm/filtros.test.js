/**
 * OS FILTROS DO MAPA — fases e região, guardados no localStorage.
 *
 * Porta de tests/js/filtros.test.js do CRM autónomo (etiqueta
 * `referencia-standalone`), com o `node:assert` passado a `expect` e duas
 * adaptações (plano T2.21):
 *   - **ids:** no portal os ids são uuid4 em texto (`ids.js`), por isso a
 *     região é `'todas' | 'sem' | uuid`. O id numérico do autónomo (`1`, `'7'`)
 *     volta a `'todas'`, e o `regiao_id` da loja compara-se tal e qual (o
 *     autónomo convertia com `Number`);
 *   - **chave:** `crm.filtros` em vez de `phc.filtros`.
 *
 * Por omissão vêem-se as 5 fases, incluindo as perdidas (desenho original
 * §4.1/§6.1). As fases guardam-se pela `ORDEM`; o ecrã mostra as caixas pela
 * ordem do `FUNIL` (fases.js).
 *
 * Os últimos testes são extra: as regras puras do componente dos filtros do
 * autónomo (`componentes/filtros-mapa.js`, testes de região e de "filtros
 * ativos" do `tests/js/filtros-mapa.test.js`), aqui fora do componente para o
 * `FiltrosMapa` da T2.25, que não tem Jest, só as chamar.
 */
import {
  CHAVE_FILTROS,
  TEXTO_REGIAO_GUARDADA,
  filtrosPadrao,
  normalizarFiltros,
  aplicarFiltros,
  carregarFiltros,
  guardarFiltros,
  textoNumeroLojas,
  regioesValidas,
  opcoesRegiao,
  ajustarARegioes,
  filtrosAtivos,
} from './filtros';

const TODAS_AS_FASES = ['perdida', 'potencial', 'contactada', 'amostra', 'cliente'];

// uuid4 em texto, como o `str(uuid.uuid4())` do servidor.
const LISBOA = '3f1c2d4e-5a6b-4c7d-8e9f-0a1b2c3d4e5f';
const PORTO = '7a8b9c0d-1e2f-4a3b-9c4d-5e6f7a8b9c0d';
const APAGADA = 'c0ffee00-0000-4000-a000-000000000099'; // uma região que já não existe
const ALGARVE = 'b2c3d4e5-f6a7-4b8c-bd9e-0f1a2b3c4d5e';

const LOJAS = Object.freeze([
  { id: 'l1', nome: 'Cliente Lisboa', fase: 'cliente', regiao_id: LISBOA },
  { id: 'l2', nome: 'Perdida Lisboa', fase: 'perdida', regiao_id: LISBOA },
  { id: 'l3', nome: 'Potencial sem região', fase: 'potencial', regiao_id: null },
  { id: 'l4', nome: 'Contactada Porto', fase: 'contactada', regiao_id: PORTO },
  { id: 'l5', nome: 'Amostra Porto', fase: 'amostra', regiao_id: PORTO },
]);

const TODAS_AS_LOJAS = ['l1', 'l2', 'l3', 'l4', 'l5'];

const ids = (lojas) => lojas.map((l) => l.id);

function criarArmazenamento(inicial = {}) {
  const dados = new Map(Object.entries(inicial));
  return {
    dados,
    getItem: (k) => (dados.has(k) ? dados.get(k) : null),
    setItem: (k, v) => {
      dados.set(k, String(v));
    },
  };
}

const armazenamentoCom = (valor) => criarArmazenamento({ 'crm.filtros': valor });

const comoSimples = (f) => ({ fases: [...f.fases].sort(), regiao: f.regiao });

test('a chave do localStorage é crm.filtros', () => {
  expect(CHAVE_FILTROS).toBe('crm.filtros');
});

test('filtrosPadrao: todas as 5 fases (incluindo perdida) e todas as regiões', () => {
  const f = filtrosPadrao();
  expect(f.fases).toBeInstanceOf(Set);
  expect([...f.fases]).toEqual(TODAS_AS_FASES);
  expect(f.regiao).toBe('todas');
});

test('filtrosPadrao devolve um objeto novo de cada vez', () => {
  const a = filtrosPadrao();
  a.fases.delete('perdida');
  expect(filtrosPadrao().fases.has('perdida')).toBe(true);
});

test('aplicarFiltros: por defeito mostra tudo, incluindo as perdidas', () => {
  expect(ids(aplicarFiltros(LOJAS))).toEqual(TODAS_AS_LOJAS);
  expect(ids(aplicarFiltros(LOJAS, filtrosPadrao()))).toEqual(TODAS_AS_LOJAS);
  expect(ids(aplicarFiltros(LOJAS, {}))).toEqual(TODAS_AS_LOJAS);
  expect(ids(aplicarFiltros(LOJAS, null))).toEqual(TODAS_AS_LOJAS);
});

test('aplicarFiltros: só as fases escolhidas', () => {
  const semPerdida = new Set(['potencial', 'contactada', 'amostra', 'cliente']);
  expect(ids(aplicarFiltros(LOJAS, { fases: semPerdida, regiao: 'todas' }))).toEqual(['l1', 'l3', 'l4', 'l5']);
  expect(ids(aplicarFiltros(LOJAS, { fases: new Set(), regiao: 'todas' }))).toEqual([]);
});

test("aplicarFiltros: 'sem' mostra só as lojas com regiao_id null", () => {
  expect(ids(aplicarFiltros(LOJAS, { fases: new Set(TODAS_AS_FASES), regiao: 'sem' }))).toEqual(['l3']);
});

test('aplicarFiltros: por uuid de região (o texto do value de um <select>)', () => {
  const fases = new Set(TODAS_AS_FASES);
  expect(ids(aplicarFiltros(LOJAS, { fases, regiao: LISBOA }))).toEqual(['l1', 'l2']);
  expect(ids(aplicarFiltros(LOJAS, { fases, regiao: PORTO }))).toEqual(['l4', 'l5']);
  expect(ids(aplicarFiltros(LOJAS, { fases, regiao: APAGADA }))).toEqual([]);
});

test('aplicarFiltros: região inválida conta como todas', () => {
  const fases = new Set(TODAS_AS_FASES);
  expect(ids(aplicarFiltros(LOJAS, { fases, regiao: 'xpto' }))).toEqual(TODAS_AS_LOJAS);
});

test('aplicarFiltros: fase e região combinam-se', () => {
  const fases = new Set(['cliente', 'potencial']);
  expect(ids(aplicarFiltros(LOJAS, { fases, regiao: LISBOA }))).toEqual(['l1']);
  expect(ids(aplicarFiltros(LOJAS, { fases, regiao: 'sem' }))).toEqual(['l3']);
  expect(ids(aplicarFiltros(LOJAS, { fases, regiao: PORTO }))).toEqual([]);
});

test('aplicarFiltros: os ids numéricos do autónomo já não contam (o filtro volta a todas)', () => {
  // Adaptação dos ids: no autónomo, `regiao: 1` e `regiao: '2'` escolhiam uma região.
  const lojas = [
    { id: 'a', fase: 'cliente', regiao_id: 1 },
    { id: 'b', fase: 'cliente', regiao_id: '2' },
    { id: 'c', fase: 'cliente', regiao_id: null },
    { id: 'd', fase: 'cliente', regiao_id: LISBOA },
  ];
  expect(ids(aplicarFiltros(lojas, { regiao: 1 }))).toEqual(['a', 'b', 'c', 'd']);
  expect(ids(aplicarFiltros(lojas, { regiao: '2' }))).toEqual(['a', 'b', 'c', 'd']);
  expect(ids(aplicarFiltros(lojas, { regiao: 'sem' }))).toEqual(['c']);
  expect(ids(aplicarFiltros(lojas, { regiao: LISBOA }))).toEqual(['d']);
});

test('aplicarFiltros: o regiao_id da loja compara-se tal e qual (sem maiúsculas nem espaços)', () => {
  const lojas = [
    { id: 'a', fase: 'cliente', regiao_id: LISBOA.toUpperCase() },
    { id: 'b', fase: 'cliente', regiao_id: ` ${LISBOA}` },
    { id: 'c', fase: 'cliente', regiao_id: LISBOA },
  ];
  expect(ids(aplicarFiltros(lojas, { regiao: LISBOA }))).toEqual(['c']);
});

test("aplicarFiltros: loja sem o campo regiao_id conta como 'sem região'", () => {
  const lojas = [{ id: 'a', fase: 'cliente' }, { id: 'b', fase: 'cliente', regiao_id: LISBOA }];
  expect(ids(aplicarFiltros(lojas, { regiao: 'sem' }))).toEqual(['a']);
  expect(ids(aplicarFiltros(lojas, { regiao: LISBOA }))).toEqual(['b']);
});

test('aplicarFiltros: uma loja com um regiao_id que já não existe aparece em Todas e não rebenta', () => {
  // Corrida aceite na T2.9: uma região apagada enquanto se grava uma loja deixa
  // um regiao_id órfão (plano, notas da T2.9 para a T2.25).
  const lojas = [
    { id: 'orfa', fase: 'cliente', regiao_id: APAGADA },
    { id: 'sem', fase: 'cliente', regiao_id: null },
  ];
  expect(ids(aplicarFiltros(lojas, { regiao: 'todas' }))).toEqual(['orfa', 'sem']);
  expect(ids(aplicarFiltros(lojas, { regiao: 'sem' }))).toEqual(['sem']);
  expect(ids(aplicarFiltros(lojas, { regiao: LISBOA }))).toEqual([]);
  expect(ids(aplicarFiltros(lojas, { regiao: APAGADA }))).toEqual(['orfa']);
});

test('aplicarFiltros aceita as fases como lista', () => {
  expect(ids(aplicarFiltros(LOJAS, { fases: ['cliente', 'amostra'], regiao: 'todas' }))).toEqual(['l1', 'l5']);
});

test('aplicarFiltros: o mapa mostra o mesmo antes e depois de guardar e recarregar', () => {
  const casos = [
    { fases: new Set(['cliente']), regiao: LISBOA },
    { fases: new Set(), regiao: 'sem' },
    { fases: 'cliente', regiao: 'todas' },
    { fases: 42, regiao: PORTO },
    { fases: {}, regiao: 'todas' },
    { fases: new Set(['xpto']), regiao: 'todas' },
    { fases: [null, 'perdida'], regiao: 'xpto' },
    { fases: ['amostra'], regiao: 2 },
    { fases: ['cliente'], regiao: LISBOA.toUpperCase() },
  ];
  for (const filtros of casos) {
    const s = criarArmazenamento();
    guardarFiltros(s, filtros);
    const antes = ids(aplicarFiltros(LOJAS, filtros));
    const depois = ids(aplicarFiltros(LOJAS, carregarFiltros(s)));
    expect([String(filtros.fases), filtros.regiao, depois]).toEqual([String(filtros.fases), filtros.regiao, antes]);
  }
});

test('aplicarFiltros devolve uma lista nova e não altera a original', () => {
  const lojas = [...LOJAS];
  const resultado = aplicarFiltros(lojas);
  expect(resultado).not.toBe(lojas);
  expect(ids(lojas)).toEqual(TODAS_AS_LOJAS);
});

test('normalizarFiltros aceita Set ou lista e descarta valores desconhecidos', () => {
  // Uma região com o formato certo mantém-se, exista ou não (quem sabe da lista é o ajustarARegioes).
  expect(comoSimples(normalizarFiltros({ fases: new Set(['cliente']), regiao: APAGADA }))).toEqual({
    fases: ['cliente'],
    regiao: APAGADA,
  });
  expect(comoSimples(normalizarFiltros({ fases: ['cliente', 'xpto', 'cliente'], regiao: PORTO }))).toEqual({
    fases: ['cliente'],
    regiao: PORTO,
  });
});

test('normalizarFiltros: lista de fases vazia é uma escolha válida (nenhuma fase)', () => {
  expect(normalizarFiltros({ fases: [], regiao: 'todas' }).fases.size).toBe(0);
});

test('normalizarFiltros: fases sem nenhum valor válido voltam ao padrão', () => {
  for (const fases of [['xpto'], [1, null], 'cliente', {}, 42, null, undefined]) {
    expect([String(fases), [...normalizarFiltros({ fases, regiao: 'sem' }).fases]]).toEqual([
      String(fases),
      TODAS_AS_FASES,
    ]);
  }
});

test('normalizarFiltros: região inválida volta a todas', () => {
  const enorme = '99999999999999999999';
  const invalidas = [
    'xpto', '', 0, '0', -1, '-1', 1.5, '1.5', '01', ' 1', enorme, true, null, {}, [], Infinity, NaN,
    // Adaptação dos ids: os ids numéricos do autónomo e um uuid fora do formato do servidor.
    1, 7, '1', '7', Number.MAX_SAFE_INTEGER,
    LISBOA.toUpperCase(), ` ${LISBOA}`, `${LISBOA}\n`, [LISBOA], { id: LISBOA },
    '3f1c2d4e-5a6b-1c7d-8e9f-0a1b2c3d4e5f', // versão 1
    'Todas', 'SEM', 'sem ', 'nenhuma',
  ];
  for (const regiao of invalidas) {
    expect([String(regiao), normalizarFiltros({ fases: ['cliente'], regiao }).regiao]).toEqual([
      String(regiao),
      'todas',
    ]);
  }
  expect(normalizarFiltros({ fases: ['cliente'], regiao: 'sem' }).regiao).toBe('sem');
  expect(normalizarFiltros({ fases: ['cliente'], regiao: 'todas' }).regiao).toBe('todas');
  expect(normalizarFiltros({ fases: ['cliente'], regiao: LISBOA }).regiao).toBe(LISBOA);
});

test('normalizarFiltros: algo que não é objeto devolve o padrão', () => {
  for (const dados of [null, undefined, 42, 'x', [], true]) {
    expect(comoSimples(normalizarFiltros(dados))).toEqual(comoSimples(filtrosPadrao()));
  }
});

test('carregarFiltros: sem nada guardado devolve o padrão', () => {
  expect(comoSimples(carregarFiltros(criarArmazenamento()))).toEqual(comoSimples(filtrosPadrao()));
});

test('carregarFiltros: lê o que está em crm.filtros', () => {
  const s = armazenamentoCom(JSON.stringify({ fases: ['cliente', 'perdida'], regiao: LISBOA }));
  const f = carregarFiltros(s);
  expect(f.fases).toBeInstanceOf(Set);
  expect(comoSimples(f)).toEqual({ fases: ['cliente', 'perdida'], regiao: LISBOA });
  expect(carregarFiltros(armazenamentoCom(JSON.stringify({ fases: [], regiao: 'sem' }))).regiao).toBe('sem');
});

test('carregarFiltros: o phc.filtros do autónomo não é lido', () => {
  const s = criarArmazenamento({ 'phc.filtros': JSON.stringify({ fases: ['cliente'], regiao: 'sem' }) });
  expect(comoSimples(carregarFiltros(s))).toEqual(comoSimples(filtrosPadrao()));
});

test('carregarFiltros: dados corrompidos ou inválidos devolvem o padrão', () => {
  for (const valor of ['{', 'undefined', '', '42', 'null', '[]', '"x"', 'true']) {
    expect([valor, comoSimples(carregarFiltros(armazenamentoCom(valor)))]).toEqual([
      valor,
      comoSimples(filtrosPadrao()),
    ]);
  }
});

test('carregarFiltros: campos inválidos são corrigidos um a um', () => {
  const s = armazenamentoCom(JSON.stringify({ fases: ['amostra', 'xpto'], regiao: 'qualquer' }));
  expect(comoSimples(carregarFiltros(s))).toEqual({ fases: ['amostra'], regiao: 'todas' });
  const numerica = armazenamentoCom(JSON.stringify({ fases: ['amostra'], regiao: 3 }));
  expect(comoSimples(carregarFiltros(numerica))).toEqual({ fases: ['amostra'], regiao: 'todas' });
});

test('carregarFiltros: armazenamento ausente ou que lança erro devolve o padrão', () => {
  const lanca = {
    getItem() {
      throw new Error('SecurityError');
    },
    setItem() {},
  };
  for (const s of [lanca, null, undefined, {}]) {
    expect(comoSimples(carregarFiltros(s))).toEqual(comoSimples(filtrosPadrao()));
  }
});

test('guardarFiltros grava JSON em crm.filtros, com as fases pela ORDEM', () => {
  const s = criarArmazenamento();
  const ok = guardarFiltros(s, { fases: new Set(['cliente', 'perdida', 'xpto']), regiao: PORTO });
  expect(ok).toBe(true);
  expect([...s.dados.keys()]).toEqual(['crm.filtros']);
  expect(JSON.parse(s.dados.get('crm.filtros'))).toEqual({ fases: ['perdida', 'cliente'], regiao: PORTO });
});

test('guardarFiltros: um id numérico do autónomo grava-se como todas', () => {
  const s = criarArmazenamento();
  expect(guardarFiltros(s, { fases: ['cliente'], regiao: '7' })).toBe(true);
  expect(JSON.parse(s.dados.get('crm.filtros'))).toEqual({ fases: ['cliente'], regiao: 'todas' });
});

test('guardarFiltros e carregarFiltros fazem ida e volta', () => {
  const s = criarArmazenamento();
  const filtros = { fases: new Set(['potencial', 'amostra']), regiao: 'sem' };
  guardarFiltros(s, filtros);
  expect(comoSimples(carregarFiltros(s))).toEqual(comoSimples(filtros));
  guardarFiltros(s, { fases: new Set(), regiao: PORTO });
  expect(comoSimples(carregarFiltros(s))).toEqual({ fases: [], regiao: PORTO });
});

test('guardarFiltros não lança erro se o armazenamento falhar e devolve false', () => {
  const lanca = {
    getItem: () => null,
    setItem() {
      throw new Error('QuotaExceededError');
    },
  };
  for (const s of [lanca, null, undefined, {}]) {
    expect(guardarFiltros(s, filtrosPadrao())).toBe(false);
  }
});

test('textoNumeroLojas: "N lojas" com singular para 1', () => {
  expect(textoNumeroLojas(0)).toBe('0 lojas');
  expect(textoNumeroLojas(1)).toBe('1 loja');
  expect(textoNumeroLojas(2)).toBe('2 lojas');
  expect(textoNumeroLojas(137)).toBe('137 lojas');
});

// --- Extra: as regras puras do componente dos filtros (filtros-mapa.js do autónomo) ---

const REGIOES = [
  { id: PORTO, nome: 'Porto', ordem: 0 },
  { id: LISBOA, nome: 'Lisboa', ordem: 1 },
];

test('regioesValidas: só as regiões com um uuid e um nome em texto, pela ordem da API', () => {
  const lista = [
    { id: ALGARVE, nome: '<b>Sul</b>', ordem: 0 },
    null,
    { id: 'x', nome: 'Má' },
    { id: 3, nome: 'Número do autónomo' },
    { id: LISBOA.toUpperCase(), nome: 'Maiúsculas' },
    { id: PORTO },
    { id: PORTO, nome: 42 },
    'Lisboa',
    { id: LISBOA, nome: 'Lisboa', ordem: 1 },
  ];
  // O nome com HTML fica como está: o React escreve-o como texto.
  expect(regioesValidas(lista)).toEqual([
    { id: ALGARVE, nome: '<b>Sul</b>', ordem: 0 },
    { id: LISBOA, nome: 'Lisboa', ordem: 1 },
  ]);
  for (const naoLista of ['não é uma lista', null, undefined, 42, { id: LISBOA, nome: 'Lisboa' }]) {
    expect(regioesValidas(naoLista)).toEqual([]);
  }
});

test('opcoesRegiao: Todas, Sem região e as regiões pela ordem da API', () => {
  expect(TEXTO_REGIAO_GUARDADA).toBe('Região guardada');
  // Antes de as regiões chegarem (null): só as duas primeiras.
  expect(opcoesRegiao(filtrosPadrao(), null)).toEqual([
    { valor: 'todas', texto: 'Todas' },
    { valor: 'sem', texto: 'Sem região' },
  ]);
  expect(opcoesRegiao(filtrosPadrao(), REGIOES)).toEqual([
    { valor: 'todas', texto: 'Todas' },
    { valor: 'sem', texto: 'Sem região' },
    { valor: PORTO, texto: 'Porto' },
    { valor: LISBOA, texto: 'Lisboa' },
  ]);
});

test('opcoesRegiao: antes de as regiões chegarem, a região guardada aparece como "Região guardada"', () => {
  const filtros = { fases: new Set(['cliente']), regiao: LISBOA };
  for (const ainda of [null, undefined]) {
    expect(opcoesRegiao(filtros, ainda)).toEqual([
      { valor: 'todas', texto: 'Todas' },
      { valor: 'sem', texto: 'Sem região' },
      { valor: LISBOA, texto: 'Região guardada' },
    ]);
  }
  // Depois de chegarem, a guardada aparece com o seu nome, no seu lugar.
  expect(opcoesRegiao(filtros, REGIOES).map((o) => o.valor)).toEqual(['todas', 'sem', PORTO, LISBOA]);
  // Com Todas ou Sem região guardada não há opção a mais.
  expect(opcoesRegiao({ regiao: 'sem' }, null)).toHaveLength(2);
});

test('opcoesRegiao: entradas inválidas ficam de fora; uma resposta que não é lista só deixa Todas e Sem região', () => {
  expect(opcoesRegiao(filtrosPadrao(), [{ id: ALGARVE, nome: '<b>Sul</b>' }, null, { id: 'x', nome: 'Má' }])).toEqual([
    { valor: 'todas', texto: 'Todas' },
    { valor: 'sem', texto: 'Sem região' },
    { valor: ALGARVE, texto: '<b>Sul</b>' },
  ]);
  expect(opcoesRegiao({ regiao: LISBOA }, 'não é uma lista')).toEqual([
    { valor: 'todas', texto: 'Todas' },
    { valor: 'sem', texto: 'Sem região' },
  ]);
});

test('ajustarARegioes: a região guardada existe — nada muda', () => {
  const filtros = { fases: new Set(['cliente']), regiao: LISBOA };
  const { filtros: novos, mudou } = ajustarARegioes(filtros, REGIOES);
  expect(mudou).toBe(false);
  expect(comoSimples(novos)).toEqual({ fases: ['cliente'], regiao: LISBOA });
  for (const regiao of ['todas', 'sem']) {
    expect(ajustarARegioes({ fases: ['cliente'], regiao }, REGIOES).mudou).toBe(false);
    expect(ajustarARegioes({ fases: ['cliente'], regiao }, []).mudou).toBe(false);
  }
});

test('ajustarARegioes: uma região guardada que já não existe volta a Todas (mudou: true, para se guardar)', () => {
  const { filtros: novos, mudou } = ajustarARegioes({ fases: new Set(['cliente']), regiao: APAGADA }, REGIOES);
  expect(mudou).toBe(true);
  expect(comoSimples(novos)).toEqual({ fases: ['cliente'], regiao: 'todas' });
  expect(novos.fases).toBeInstanceOf(Set);
  // Uma resposta que não é lista conta como lista vazia (como o definirRegioes do autónomo).
  expect(ajustarARegioes({ fases: ['cliente'], regiao: LISBOA }, 'não é uma lista').mudou).toBe(true);
  // Só conta uma região válida da lista: um id em maiúsculas não é o mesmo.
  expect(ajustarARegioes({ regiao: LISBOA }, [{ id: LISBOA.toUpperCase(), nome: 'Lisboa' }]).mudou).toBe(true);
});

test('ajustarARegioes devolve os filtros normalizados (ex.: fases inválidas voltam ao padrão)', () => {
  const { filtros: novos, mudou } = ajustarARegioes({ fases: ['xpto'], regiao: 3 }, REGIOES);
  expect(mudou).toBe(false);
  expect(comoSimples(novos)).toEqual(comoSimples(filtrosPadrao()));
});

test('filtrosAtivos: true quando o mapa não está a mostrar todas as lojas', () => {
  expect(filtrosAtivos(filtrosPadrao())).toBe(false);
  expect(filtrosAtivos({ fases: TODAS_AS_FASES, regiao: 'todas' })).toBe(false);
  expect(filtrosAtivos(null)).toBe(false);
  expect(filtrosAtivos({ fases: ['potencial', 'contactada', 'amostra', 'cliente'], regiao: 'todas' })).toBe(true);
  expect(filtrosAtivos({ fases: [], regiao: 'todas' })).toBe(true);
  expect(filtrosAtivos({ fases: new Set(['cliente']), regiao: 'todas' })).toBe(true);
  expect(filtrosAtivos({ fases: TODAS_AS_FASES, regiao: 'sem' })).toBe(true);
  expect(filtrosAtivos({ fases: TODAS_AS_FASES, regiao: LISBOA })).toBe(true);
  // Uma região inválida conta como todas (a mesma normalização do aplicarFiltros).
  expect(filtrosAtivos({ fases: TODAS_AS_FASES, regiao: 7 })).toBe(false);
});
