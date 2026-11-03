/**
 * A LINHA DA ROTA — a polyline codificada do Directions (precisão 5), F3 / T3.26.
 *
 * O servidor guarda a linha tal como o openrouteservice a devolve (`calculo.geometria`) e manda-a na
 * API; o `descodificarPolilinha` desfá-la em pares `[lat, lng]`, que o `mapa.js` converte para os
 * literais `{lat, lng}` do `Polyline` da Google (correções do mapa Google, T3.26 e T3.33).
 *
 * É a mesma regra do `descodificar` de `backend/crm/dominio/polilinha.py` (o exemplo da Google lê-se
 * do próprio teste do Python), com uma diferença de propósito: o Python levanta erros, o ecrã nunca
 * rebenta. Um texto estragado (um carácter fora de '?'..'~', um valor cortado a meio, uma latitude sem
 * longitude, um valor grande demais, um ponto fora do mundo) ou o que não é texto dá `[]`: sem linha.
 */
import fs from 'fs';
import path from 'path';

import { descodificarPolilinha } from './polilinha';

const TESTE_PY = path.join(__dirname, '..', '..', '..', '..', 'backend', 'tests', 'crm', 'test_dominio_polilinha.py');

// O exemplo da documentação da Google ("Encoded Polyline Algorithm Format").
const EXEMPLO_GOOGLE = '_p~iF~ps|U_ulLnnqC_mqNvxq`@';
const PONTOS_GOOGLE = [[38.5, -120.2], [40.7, -120.95], [43.252, -126.453]];

// Um codificador só dos testes (o frontend não codifica), para as idas e voltas.
function codificar(pontos, precisao = 5) {
  const escala = 10 ** precisao;
  let anteriores = [0, 0];
  let texto = '';
  for (const ponto of pontos) {
    const inteiros = ponto.map((graus) => Math.round(graus * escala));
    for (let i = 0; i < 2; i += 1) {
      let valor = inteiros[i] - anteriores[i];
      valor = valor < 0 ? -2 * valor - 1 : 2 * valor;
      while (valor >= 0x20) {
        texto += String.fromCharCode((0x20 | (valor % 0x20)) + 63);
        valor = Math.floor(valor / 0x20);
      }
      texto += String.fromCharCode(valor + 63);
    }
    anteriores = inteiros;
  }
  return texto;
}

test('descodifica o exemplo da Google em pares [lat, lng]', () => {
  expect(descodificarPolilinha(EXEMPLO_GOOGLE)).toEqual(PONTOS_GOOGLE);
});

test('é o mesmo exemplo do teste do Python, com os mesmos pontos', () => {
  const texto = fs.readFileSync(TESTE_PY, 'utf8');
  const exemplo = /^EXEMPLO_GOOGLE = "(.*)"$/m.exec(texto);
  const pontos = /^PONTOS_GOOGLE = (\[.*\])$/m.exec(texto);
  expect(exemplo).not.toBe(null);
  expect(pontos).not.toBe(null);
  expect(exemplo[1]).toBe(EXEMPLO_GOOGLE);
  expect(JSON.parse(pontos[1].replace(/\(/g, '[').replace(/\)/g, ']'))).toEqual(PONTOS_GOOGLE);
});

test('os pontos são pares de números, em listas novas a cada chamada', () => {
  const pontos = descodificarPolilinha(EXEMPLO_GOOGLE);
  expect(Array.isArray(pontos)).toBe(true);
  for (const ponto of pontos) {
    expect(Array.isArray(ponto)).toBe(true);
    expect(ponto).toHaveLength(2);
    expect(ponto.every((n) => typeof n === 'number' && Number.isFinite(n))).toBe(true);
  }
  pontos[0][0] = 0;
  pontos.pop();
  expect(descodificarPolilinha(EXEMPLO_GOOGLE)).toEqual(PONTOS_GOOGLE);
});

test('o texto vazio não tem pontos', () => {
  expect(descodificarPolilinha('')).toEqual([]);
});

test('um só ponto', () => {
  expect(descodificarPolilinha('_p~iF~ps|U')).toEqual([[38.5, -120.2]]);
});

test('a linha de uma rota curta em Lisboa (fábrica → Marquês → Comércio), a do teste do Python', () => {
  expect(descodificarPolilinha('k}ikFr_xv@sDvVwGj\\kCvL')).toEqual([
    [38.7223, -9.1393],
    [38.7232, -9.1431],
    [38.7246, -9.1478],
    [38.7253, -9.15],
  ]);
});

test('o zero fica zero (nunca -0)', () => {
  const [[lat, lng]] = descodificarPolilinha('??');
  expect(Object.is(lat, 0)).toBe(true);
  expect(Object.is(lng, 0)).toBe(true);
});

test('a precisão por omissão é 5; com 6, os mesmos inteiros a dividir por 10⁶', () => {
  expect(descodificarPolilinha(EXEMPLO_GOOGLE, 5)).toEqual(PONTOS_GOOGLE);
  expect(descodificarPolilinha(EXEMPLO_GOOGLE, 6)).toEqual([[3.85, -12.02], [4.07, -12.095], [4.3252, -12.6453]]);
});

test.each([['5'], [-1], [11], [2.5], [NaN], [null]])('uma precisão inválida (%p) → []', (precisao) => {
  expect(descodificarPolilinha(EXEMPLO_GOOGLE, precisao)).toEqual([]);
});

test('ida e volta: 200 linhas ao acaso em Portugal continental, a 1e-5', () => {
  // Um gerador fixo (o resultado não muda de uma corrida para a outra).
  let semente = 20261012;
  const aoAcaso = () => {
    semente = (semente * 1103515245 + 12345) % 2147483648;
    return semente / 2147483648;
  };
  for (let n = 0; n < 200; n += 1) {
    const pontos = [];
    const quantos = 1 + Math.floor(aoAcaso() * 50);
    for (let i = 0; i < quantos; i += 1) {
      pontos.push([36.9 + aoAcaso() * 5.3, -9.6 + aoAcaso() * 3.4]);
    }
    const lidos = descodificarPolilinha(codificar(pontos));
    expect(lidos).toHaveLength(pontos.length);
    lidos.forEach(([lat, lng], i) => {
      expect(Math.abs(lat - pontos[i][0])).toBeLessThanOrEqual(0.5e-5 + 1e-12);
      expect(Math.abs(lng - pontos[i][1])).toBeLessThanOrEqual(0.5e-5 + 1e-12);
    });
  }
});

test('ida e volta: os extremos do mundo e os saltos grandes', () => {
  const pontos = [[90, 180], [-90, -180], [0, 0], [-89.99999, 179.99999], [38.7, -9.1]];
  expect(descodificarPolilinha(codificar(pontos))).toEqual(pontos);
});

test.each([
  ['um espaço', '_p~iF ~ps|U'],
  // Os caracteres errados ficam no lugar de um valor (o ">" fecha-o, o DEL e o "ç" pedem mais um bloco),
  // e a contagem dos valores fica par: sem a verificação, lia-se um segundo ponto.
  ['um carácter abaixo de "?"', '_p~iF~ps|U>?'],
  ['um carácter acima de "~"', '_p~iF~ps|U\u007f??'],
  ['um carácter fora do ASCII', '_p~iF~ps|Uç??'],
  ['um NUL', '_p~iF\u0000~ps|U'],
  ['um valor cortado a meio', '_p~iF~ps|'],
  ['um valor cortado a meio depois de um ponto inteiro', '_p~iF~ps|U_'],
  ['uma latitude sem longitude', '_p~iF'],
  ['o exemplo com uma latitude a mais', `${EXEMPLO_GOOGLE}_p~iF`],
  ['um valor grande demais (11 blocos)', '~~~~~~~~~~??'],
  ['um zero escrito em 11 blocos', '__________??'],
  ['uma latitude fora do mundo (100°)', '_gjaR?'],
  ['uma longitude fora do mundo (181°)', '?_qvoa@'],
])('um texto estragado — %s — dá []', (_, texto) => {
  expect(descodificarPolilinha(texto)).toEqual([]);
});

test.each([[null], [undefined], [42], [['_p~iF~ps|U']], [{}], [true]])('o que não é texto (%p) dá []', (valor) => {
  expect(descodificarPolilinha(valor)).toEqual([]);
});

test('um valor tem no máximo 10 blocos (50 bits, que um double guarda sem perder nenhum)', () => {
  // O zero escrito em 10 blocos ("_" é o bloco 0 com o sinal de continuar) ainda se lê; em 11, não.
  expect(descodificarPolilinha('_________?_________?')).toEqual([[0, 0]]);
  expect(descodificarPolilinha('__________?_________?')).toEqual([]);
  // Às 10 casas, os extremos do mundo precisam de 9 blocos e leem-se exatos.
  const texto = codificar([[89.5, 179.5], [-89.5, -179.5]], 10);
  expect(descodificarPolilinha(texto, 10)).toEqual([[89.5, 179.5], [-89.5, -179.5]]);
});
