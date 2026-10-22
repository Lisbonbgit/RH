/**
 * AS DATAS DAS ROTAS NO FRONTEND — o dia `AAAA-MM-DD` (hora de Lisboa), F3 / T3.26.
 *
 * Uma rota por dia (`crm_rotas.data`). O dia vem no caminho (`/crm/rotas/2026-10-12`) e o "hoje" vem
 * sempre do servidor (`rota.hoje`, `GET /rotas` → `hoje`): o frontend nunca lê o relógio do browser
 * para decidir o dia. Aqui só se valida, se soma e se escreve o dia:
 *   - `eDataValida` é a regra do `ler_data` de `backend/crm/dominio/datas.py`: exatamente `AAAA-MM-DD`,
 *     só algarismos ASCII, um dia que exista (sem o ano 0, sem o 29 de fevereiro de um ano comum);
 *   - `somarDias` conta dias de calendário ao meio-dia UTC, por isso a mudança de hora nunca mexe no
 *     resultado, seja qual for o fuso do browser;
 *   - `diaDaSemana` dá os nomes dos `dias_fechada` da loja (`campos_loja.DIAS`: "seg" … "dom");
 *   - `rotuloDia` ("Hoje", "Amanhã", "seg 19/10") e `rotuloDataLonga` ("segunda-feira, 12 de outubro")
 *     escrevem-se com listas fixas de nomes, sem `Intl` nem `toLocale…` (o resultado não depende da
 *     língua nem do fuso do browser).
 *
 * Os testes do fuso correm o próprio `datas.js` num processo do Node à parte, com a variável `TZ` (no
 * Jest, o `process.env` é uma cópia e mudar o `TZ` lá dentro não muda o fuso), e provam primeiro que o
 * fuso pegou: sem isso, um teste do fuso passava sem testar nada. O `datas.js` não importa nada, por isso
 * corre tal e qual, só sem os `export`. Um varrimento do código proíbe ainda as leituras em hora local.
 */
import { execFileSync } from 'child_process';
import fs from 'fs';
import path from 'path';

import {
  DIAS_SEMANA,
  diaDaSemana,
  eDataValida,
  rotuloDataLonga,
  rotuloDia,
  somarDias,
} from './datas';

// frontend/src/lib/crm → raiz do repositório.
const RAIZ = path.join(__dirname, '..', '..', '..', '..');
const CAMPOS_LOJA_PY = path.join(RAIZ, 'backend', 'crm', 'dominio', 'campos_loja.py');
const DATAS_JS = path.join(__dirname, 'datas.js');

// O valor de `expressao`, calculado com o datas.js num Node à parte com o fuso `fuso` (até 10 s).
function noFuso(fuso, expressao) {
  const modulo = fs.readFileSync(DATAS_JS, 'utf8').replace(/^export /gm, '');
  const codigo = `${modulo}\nprocess.stdout.write(JSON.stringify(${expressao}));\n`;
  const saida = execFileSync(process.execPath, ['-e', codigo], {
    env: { PATH: process.env.PATH, TZ: fuso },
    encoding: 'utf8',
    timeout: 10000,
  });
  return JSON.parse(saida);
}

// O que se calcula em cada fuso: a hora local do meio-dia UTC (a prova de que o fuso pegou), as contas
// à volta das mudanças de hora, um ano inteiro dia a dia e os nomes.
const NO_FUSO = `(() => {
  let dia = '2026-01-01';
  let voltas = true;
  for (let i = 0; i < 365; i += 1) {
    const seguinte = somarDias(dia, 1);
    voltas = voltas && somarDias(seguinte, -1) === dia;
    dia = seguinte;
  }
  return {
    horas: [12, 24, 26].map((d) => new Date(Date.UTC(2026, 9, d, 12)).getHours()),
    somas: [
      somarDias('2026-10-24', 2),
      somarDias('2026-10-26', -2),
      somarDias('2026-03-28', 2),
      somarDias('2026-03-30', -2),
      somarDias('2026-11-01', 7),
    ],
    ano: dia,
    voltas,
    dias: [diaDaSemana('2026-10-25'), diaDaSemana('2026-10-26')],
    amanha: rotuloDia('2026-10-26', '2026-10-25'),
    longa: rotuloDataLonga('2026-10-25'),
  };
})()`;

const IGUAL_EM_TODOS = {
  somas: ['2026-10-26', '2026-10-24', '2026-03-30', '2026-03-28', '2026-11-08'],
  ano: '2027-01-01',
  voltas: true,
  dias: ['dom', 'seg'],
  amanha: 'Amanhã',
  longa: 'domingo, 25 de outubro',
};

// --- eDataValida -----------------------------------------------------------------------------------

test.each([
  '2026-10-12',
  '2026-12-31',
  '2026-01-01',
  '2028-02-29',
  '2000-02-29',
  '0001-01-01',
  '9999-12-31',
])('eDataValida(%s) → verdadeiro', (data) => {
  expect(eDataValida(data)).toBe(true);
});

test.each([
  ['29 de fevereiro de um ano comum', '2026-02-29'],
  ['29 de fevereiro de 1900 (não é bissexto)', '1900-02-29'],
  ['31 de abril', '2026-04-31'],
  ['mês 13', '2026-13-01'],
  ['mês 0', '2026-00-10'],
  ['dia 0', '2026-10-00'],
  ['dia 32', '2026-10-32'],
  ['ano 0 (o date do Python começa no ano 1)', '0000-01-01'],
  ['mês com um algarismo', '2026-1-01'],
  ['dia com um algarismo', '2026-10-1'],
  ['ano com cinco algarismos', '20260-10-12'],
  ['sem traços', '20261012'],
  ['barras', '2026/10/12'],
  ['com hora', '2026-10-12T00:00'],
  ['"\\n" no fim (o $ do Python aceitava-o)', '2026-10-12\n'],
  ['espaço antes', ' 2026-10-12'],
  ['espaço depois', '2026-10-12 '],
  ['algarismos árabes', '٢٠٢٦-١٠-١٢'],
  ['algarismos de largura total', '２０２６-１０-１２'],
  ['vazio', ''],
  ['um pedaço de caminho', '..'],
])('eDataValida recusa: %s', (_, data) => {
  expect(eDataValida(data)).toBe(false);
});

test.each([[null], [undefined], [20261012], [new Date(Date.UTC(2026, 9, 12))], [['2026-10-12']], [{}]])(
  'eDataValida recusa o que não é texto: %p',
  (valor) => {
    expect(eDataValida(valor)).toBe(false);
  },
);

// --- somarDias -------------------------------------------------------------------------------------

test.each([
  ['2026-10-24', 2, '2026-10-26'], // a hora muda a 25 de outubro de 2026 (Lisboa)
  ['2026-03-28', 2, '2026-03-30'], // e a 29 de março de 2026
  ['2026-10-25', 1, '2026-10-26'],
  ['2026-03-29', 1, '2026-03-30'],
  ['2026-10-12', 0, '2026-10-12'],
  ['2026-10-12', 1, '2026-10-13'],
  ['2026-10-12', -14, '2026-09-28'],
  ['2026-10-12', 60, '2026-12-11'],
  ['2026-10-12', 365, '2027-10-12'],
  ['2026-12-31', 1, '2027-01-01'],
  ['2027-01-01', -1, '2026-12-31'],
  ['2028-02-28', 1, '2028-02-29'],
  ['2026-02-28', 1, '2026-03-01'],
  ['2028-03-01', -1, '2028-02-29'],
  ['0050-03-01', 1, '0050-03-02'], // um ano abaixo de 100 não passa a 1950
  ['0099-12-31', 1, '0100-01-01'],
  ['9999-12-30', 1, '9999-12-31'],
])('somarDias(%s, %i) → %s', (data, n, esperado) => {
  expect(somarDias(data, n)).toBe(esperado);
});

test('somarDias fora dos anos 1 a 9999 → null', () => {
  expect(somarDias('9999-12-31', 1)).toBe(null);
  expect(somarDias('0001-01-01', -1)).toBe(null);
});

test.each([
  ['uma data inválida', '2026-02-29', 1],
  ['uma data que não é texto', null, 1],
  ['dias fracionários', '2026-10-12', 1.5],
  ['dias em texto', '2026-10-12', '2'],
  ['NaN', '2026-10-12', NaN],
  ['infinito', '2026-10-12', Infinity],
  ['sem dias', '2026-10-12', undefined],
  ['dias nulos', '2026-10-12', null],
  ['um número de dias absurdo', '2026-10-12', 1e12],
])('somarDias com %s → null', (_, data, n) => {
  expect(somarDias(data, n)).toBe(null);
});

// Fusos com mudança de hora (Lisboa a 25 de outubro, Nova Iorque a 1 de novembro), os extremos do mundo
// (+14 e −11) e o UTC. As horas locais do meio-dia UTC de 12, 24 e 26 de outubro de 2026 provam que o
// fuso pegou (Lisboa muda a hora entre 24 e 26).
test.each([
  ['Europe/Lisbon', [13, 13, 12]],
  ['America/New_York', [8, 8, 8]],
  ['Pacific/Kiritimati', [2, 2, 2]], // UTC+14
  ['Pacific/Pago_Pago', [1, 1, 1]], // UTC−11
  ['UTC', [12, 12, 12]],
])('no fuso %s, as contas e os nomes dos dias são os mesmos', (fuso, horas) => {
  expect(noFuso(fuso, NO_FUSO)).toEqual({ horas, ...IGUAL_EM_TODOS });
});

// --- diaDaSemana -----------------------------------------------------------------------------------

test('diaDaSemana dá os nomes dos dias_fechada, de segunda a domingo', () => {
  expect(diaDaSemana('2026-10-12')).toBe('seg');
  const semana = [0, 1, 2, 3, 4, 5, 6].map((n) => diaDaSemana(somarDias('2026-10-12', n)));
  expect(semana).toEqual(['seg', 'ter', 'qua', 'qui', 'sex', 'sab', 'dom']);
  expect(DIAS_SEMANA).toEqual(['seg', 'ter', 'qua', 'qui', 'sex', 'sab', 'dom']);
  expect(Object.isFrozen(DIAS_SEMANA)).toBe(true);
});

test.each([
  ['2000-01-01', 'sab'],
  ['2028-02-29', 'ter'],
  ['1900-01-01', 'seg'],
  ['0001-01-01', 'seg'],
  ['9999-12-31', 'sex'],
  ['2026-12-25', 'sex'],
])('diaDaSemana(%s) → %s', (data, dia) => {
  expect(diaDaSemana(data)).toBe(dia);
});

test.each([['2026-02-29'], [''], [null], [undefined], ['2026-10-12 ']])('diaDaSemana(%p) → null', (data) => {
  expect(diaDaSemana(data)).toBe(null);
});

test('os DIAS_SEMANA são os campos_loja.DIAS do servidor (os nomes dos dias_fechada)', () => {
  const texto = fs.readFileSync(CAMPOS_LOJA_PY, 'utf8');
  const linha = /^DIAS = \(([^)]*)\)$/m.exec(texto);
  expect(linha).not.toBe(null);
  const doServidor = [...linha[1].matchAll(/"([a-z]+)"/g)].map((m) => m[1]);
  expect(doServidor).toHaveLength(7);
  expect([...DIAS_SEMANA]).toEqual(doServidor);
});

// --- rotuloDia -------------------------------------------------------------------------------------

test.each([
  ['2026-10-12', '2026-10-12', 'Hoje'],
  ['2026-10-13', '2026-10-12', 'Amanhã'],
  ['2026-10-19', '2026-10-12', 'seg 19/10'],
  ['2026-10-14', '2026-10-12', 'qua 14/10'],
  ['2026-10-17', '2026-10-12', 'sáb 17/10'],
  ['2026-10-18', '2026-10-12', 'dom 18/10'],
  ['2026-10-11', '2026-10-12', 'dom 11/10'], // ontem não tem nome próprio
  ['2026-11-03', '2026-10-12', 'ter 03/11'],
  ['2026-11-01', '2026-10-31', 'Amanhã'],
  ['2027-01-01', '2026-12-31', 'Amanhã'],
  ['2028-02-29', '2028-02-28', 'Amanhã'],
  ['2026-10-25', '2026-10-24', 'Amanhã'],
  ['2026-10-26', '2026-10-25', 'Amanhã'],
  ['2027-10-12', '2026-10-12', 'ter 12/10'],
])('rotuloDia(%s, hoje %s) → %s', (data, hoje, rotulo) => {
  expect(rotuloDia(data, hoje)).toBe(rotulo);
});

test.each([
  ['2026-02-29', '2026-10-12'],
  ['2026-10-12', '2026-02-29'],
  ['2026-10-12', undefined],
  [null, '2026-10-12'],
  ['', ''],
])('rotuloDia(%p, %p) → null', (data, hoje) => {
  expect(rotuloDia(data, hoje)).toBe(null);
});

// --- rotuloDataLonga -------------------------------------------------------------------------------

test.each([
  ['2026-10-12', 'segunda-feira, 12 de outubro'],
  ['2026-10-13', 'terça-feira, 13 de outubro'],
  ['2026-10-14', 'quarta-feira, 14 de outubro'],
  ['2026-10-15', 'quinta-feira, 15 de outubro'],
  ['2026-10-16', 'sexta-feira, 16 de outubro'],
  ['2026-10-17', 'sábado, 17 de outubro'],
  ['2026-10-18', 'domingo, 18 de outubro'],
  ['2026-11-03', 'terça-feira, 3 de novembro'],
  ['2028-02-29', 'terça-feira, 29 de fevereiro'],
])('rotuloDataLonga(%s) → %s', (data, rotulo) => {
  expect(rotuloDataLonga(data)).toBe(rotulo);
});

test('rotuloDataLonga: os doze meses, em minúsculas', () => {
  const meses = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map((mes) =>
    rotuloDataLonga(`2026-${String(mes).padStart(2, '0')}-01`).split(' de ')[1],
  );
  expect(meses).toEqual([
    'janeiro',
    'fevereiro',
    'março',
    'abril',
    'maio',
    'junho',
    'julho',
    'agosto',
    'setembro',
    'outubro',
    'novembro',
    'dezembro',
  ]);
});

test.each([['2026-02-29'], ['2026-13-01'], [''], [null], [undefined], [42]])('rotuloDataLonga(%p) → null', (data) => {
  expect(rotuloDataLonga(data)).toBe(null);
});

// --- O código: sem Intl, sem o relógio e sem as horas locais ----------------------------------------

test('o datas.js não usa Intl, toLocale…, o relógio do browser nem as leituras em hora local', () => {
  // Os comentários saem: só o código conta.
  const codigo = fs
    .readFileSync(DATAS_JS, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/.*$/gm, '');
  for (const proibido of [
    /\bIntl\b/,
    /\btoLocale\w*/,
    /\bDate\.now\b/,
    /\bnew Date\(\s*\)/,
    /\bDate\.parse\b/,
    /\.(?:get|set)(?:FullYear|Month|Date|Day|Hours)\(/, // só as versões UTC
    /\btoISOString\b/,
  ]) {
    expect(codigo).not.toMatch(proibido);
  }
});
