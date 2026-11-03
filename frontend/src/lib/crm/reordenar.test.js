/**
 * REORDENAR AS PARAGENS — arrastar com o rato, o dedo e o teclado (F3 / T3.28).
 *
 * As regras são puras (o jsdom não faz layout: plano F3 §10): a `ListaParagens` (T3.36) mede as linhas,
 * lê as teclas e desenha; o `reordenar.js` decide.
 *   - `mover(lista, de, para)`: a lista nova, com o destino limitado às pontas;
 *   - `indiceDestino(y, caixas, de)`: as linhas (sem a arrastada) com o meio acima de `y`;
 *   - `deveIniciarArrasto(dx, dy)`: só depois de 4 px;
 *   - `teclaNaLista(estado, {tecla, indice, total, nome, repetida})` → `{estado, acao, anuncio, tratada}`:
 *     Espaço/Enter pegam e largam, as setas movem, o Escape, o Tab e a perda do foco cancelam;
 *   - a mais do plano, para a T3.36: `cancelarMovimento` (a perda do foco), `desvioDaLinha` (as outras
 *     linhas abrem lugar) e `deslocamentoAutomatico` (deslocar a lista perto das pontas).
 */
import fs from 'fs';
import path from 'path';

import {
  INSTRUCOES_ARRASTAR,
  LIMIAR_ARRASTO_PX,
  PASSO_DESLOCAR_PX,
  ZONA_DESLOCAR_PX,
  cancelarMovimento,
  deslocamentoAutomatico,
  desvioDaLinha,
  deveIniciarArrasto,
  indiceDestino,
  mover,
  teclaNaLista,
} from './reordenar';

const REORDENAR_JS = path.join(__dirname, 'reordenar.js');

function congelarAFundo(valor) {
  if (valor && typeof valor === 'object' && !Object.isFrozen(valor)) {
    Object.values(valor).forEach(congelarAFundo);
    Object.freeze(valor);
  }
  return valor;
}

const NAO_INTEIROS = [1.5, NaN, Infinity, -Infinity, '1', null, undefined, true, {}, []];

// --- mover ---------------------------------------------------------------------------------------

describe('mover', () => {
  const LISTA = Object.freeze(['a', 'b', 'c', 'd']);

  test.each([
    ['para baixo', 0, 2, ['b', 'c', 'a', 'd']],
    ['para baixo, até ao fim', 1, 3, ['a', 'c', 'd', 'b']],
    ['para cima', 3, 1, ['a', 'd', 'b', 'c']],
    ['para cima, até ao início', 2, 0, ['c', 'a', 'b', 'd']],
    ['uma posição para baixo', 1, 2, ['a', 'c', 'b', 'd']],
    ['uma posição para cima', 2, 1, ['a', 'c', 'b', 'd']],
    ['no mesmo sítio', 1, 1, ['a', 'b', 'c', 'd']],
    ['para lá do fim → o fim', 1, 99, ['a', 'c', 'd', 'b']],
    ['logo a seguir ao fim → o fim', 0, 4, ['b', 'c', 'd', 'a']],
    ['para lá do início → o início', 2, -5, ['c', 'a', 'b', 'd']],
    ['logo antes do início → o início', 3, -1, ['d', 'a', 'b', 'c']],
  ])('%s', (_caso, de, para, esperado) => {
    expect(mover(LISTA, de, para)).toEqual(esperado);
  });

  test('devolve sempre uma lista nova e não mexe na recebida', () => {
    const objetos = congelarAFundo([{ id: 'a' }, { id: 'b' }, { id: 'c' }]);
    const movida = mover(objetos, 0, 2);
    expect(movida).toEqual([{ id: 'b' }, { id: 'c' }, { id: 'a' }]);
    expect(objetos).toEqual([{ id: 'a' }, { id: 'b' }, { id: 'c' }]);
    // Os mesmos elementos, noutra ordem.
    expect(movida[2]).toBe(objetos[0]);
    expect(movida[0]).toBe(objetos[1]);
    const igual = mover(objetos, 1, 1);
    expect(igual).toEqual(objetos);
    expect(igual).not.toBe(objetos);
    expect(Array.isArray(igual)).toBe(true);
  });

  test('uma lista de um só elemento fica igual; uma vazia fica vazia', () => {
    expect(mover(['a'], 0, 5)).toEqual(['a']);
    expect(mover(['a'], 0, -5)).toEqual(['a']);
    expect(mover([], 0, 0)).toEqual([]);
  });

  test('os repetidos movem-se pela posição, não pelo valor', () => {
    expect(mover(['x', 'y', 'x'], 2, 0)).toEqual(['x', 'x', 'y']);
    expect(mover(['x', 'y', 'x'], 0, 2)).toEqual(['y', 'x', 'x']);
  });

  test.each([-1, 4, 99, ...NAO_INTEIROS])('uma origem fora da lista (%p) não muda nada', (de) => {
    const movida = mover(LISTA, de, 2);
    expect(movida).toEqual(['a', 'b', 'c', 'd']);
    expect(movida).not.toBe(LISTA);
  });

  test.each(NAO_INTEIROS)('um destino que não é um inteiro (%p) não muda nada', (para) => {
    const movida = mover(LISTA, 0, para);
    expect(movida).toEqual(['a', 'b', 'c', 'd']);
    expect(movida).not.toBe(LISTA);
  });

  test.each([null, undefined, 'abcd', { length: 2, 0: 'a', 1: 'b' }, 42])('o que não é uma lista (%p) dá []', (lista) => {
    expect(mover(lista, 0, 1)).toEqual([]);
  });
});

// --- indiceDestino -------------------------------------------------------------------------------

// Linhas empilhadas a partir de `inicio`, com as alturas dadas (como o getBoundingClientRect).
function caixas(alturas, inicio = 100) {
  let top = inicio;
  return alturas.map((altura) => {
    const caixa = { top, bottom: top + altura, height: altura };
    top += altura;
    return caixa;
  });
}

describe('indiceDestino', () => {
  // Quatro linhas de 50 px a partir dos 100: os meios estão nos 125, 175, 225 e 275.
  const QUATRO = Object.freeze(caixas([50, 50, 50, 50]).map(Object.freeze));

  test.each([
    // Para baixo (a primeira linha arrastada).
    ['para baixo, ainda antes do meio da seguinte', 174, 0, 0],
    ['para baixo, passou o meio da seguinte', 176, 0, 1],
    ['para baixo, passou dois meios', 226, 0, 2],
    ['para baixo, para lá do fim', 1000, 0, 3],
    // Para cima (a última linha arrastada).
    ['para cima, ainda abaixo do meio da anterior', 226, 3, 3],
    ['para cima, passou o meio da anterior', 224, 3, 2],
    ['para cima, passou dois meios', 174, 3, 1],
    ['para cima, até ao início', 124, 3, 0],
    ['para cima, para lá do início', -500, 3, 0],
    // No mesmo sítio.
    ['no mesmo sítio, no meio da própria linha', 175, 1, 1],
    ['no mesmo sítio, um pouco acima', 150, 1, 1],
    ['no mesmo sítio, um pouco abaixo', 224, 1, 1],
    ['a linha arrastada não conta, mesmo com o meio acima', 130, 0, 0],
    ['a linha arrastada não conta para lá do fim', 1000, 1, 3],
  ])('%s', (_caso, y, de, esperado) => {
    expect(indiceDestino(y, QUATRO, de)).toBe(esperado);
  });

  test('o meio conta só quando fica estritamente acima de y', () => {
    expect(indiceDestino(175, QUATRO, 0)).toBe(0);
    expect(indiceDestino(175.5, QUATRO, 0)).toBe(1);
    expect(indiceDestino(225, QUATRO, 3)).toBe(2);
    expect(indiceDestino(225.01, QUATRO, 3)).toBe(3);
  });

  test('o meio é o de cada caixa, com alturas diferentes', () => {
    // Linhas de 40, 80 e 60 px a partir dos 0: os meios estão nos 20, 80 e 150.
    const tres = caixas([40, 80, 60], 0);
    expect(indiceDestino(79, tres, 0)).toBe(0);
    expect(indiceDestino(81, tres, 0)).toBe(1);
    expect(indiceDestino(149, tres, 0)).toBe(1);
    expect(indiceDestino(151, tres, 0)).toBe(2);
    expect(indiceDestino(21, tres, 2)).toBe(1);
    expect(indiceDestino(19, tres, 2)).toBe(0);
  });

  test('o meio vem do top e do bottom (sem precisar do height)', () => {
    const semAltura = [{ top: 0, bottom: 10 }, { top: 10, bottom: 110 }, { top: 110, bottom: 120 }];
    expect(indiceDestino(59, semAltura, 0)).toBe(0);
    expect(indiceDestino(61, semAltura, 0)).toBe(1);
  });

  test('uma caixa sem top/bottom numéricos e finitos não conta', () => {
    const estragadas = [
      { top: 0, bottom: 50 },
      null,
      { top: NaN, bottom: 50 },
      { top: '100', bottom: '150' },
      { top: 150, bottom: Infinity },
      { top: 200, bottom: 250 },
      // Com as contas do JavaScript, estas davam um meio de 5 (ou −∞), acima de qualquer y.
      { top: null, bottom: 10 },
      { top: 10, bottom: null },
      { top: -Infinity, bottom: 50 },
      { top: '1', bottom: '1' },
    ];
    // Só a primeira (meio 25) e a sexta (meio 225) contam.
    expect(indiceDestino(1000, estragadas, 0)).toBe(1);
    expect(indiceDestino(1000, estragadas, 5)).toBe(1);
    expect(indiceDestino(100, estragadas, 5)).toBe(1);
    expect(indiceDestino(10, estragadas, 5)).toBe(0);
  });

  test.each([NaN, Infinity, -Infinity, '200', null, undefined])('um y que não é um número finito (%p) fica na origem', (y) => {
    expect(indiceDestino(y, QUATRO, 2)).toBe(2);
  });

  test.each([null, undefined, 'caixas', { length: 4 }])('sem lista de caixas (%p) fica na origem', (lista) => {
    expect(indiceDestino(1000, lista, 1)).toBe(1);
  });

  test.each([-1, 4, 1.5, NaN, '1', null])('uma origem fora da lista (%p) fica como está', (de) => {
    expect(indiceDestino(1000, QUATRO, de)).toBe(de);
  });

  test('não mexe nas caixas', () => {
    const medidas = congelarAFundo(caixas([50, 50, 50]));
    expect(indiceDestino(1000, medidas, 0)).toBe(2);
    expect(medidas).toEqual(caixas([50, 50, 50]));
  });

  test('o destino serve tal e qual ao mover', () => {
    const lista = ['a', 'b', 'c', 'd'];
    expect(mover(lista, 0, indiceDestino(226, QUATRO, 0))).toEqual(['b', 'c', 'a', 'd']);
    expect(mover(lista, 3, indiceDestino(174, QUATRO, 3))).toEqual(['a', 'd', 'b', 'c']);
    expect(mover(lista, 1, indiceDestino(200, QUATRO, 1))).toEqual(lista);
  });
});

// --- deveIniciarArrasto --------------------------------------------------------------------------

describe('deveIniciarArrasto', () => {
  test('o limiar é de 4 px', () => {
    expect(LIMIAR_ARRASTO_PX).toBe(4);
  });

  test.each([
    [0, 0, false],
    [3, 0, false],
    [0, 3, false],
    [-3, 0, false],
    [0, -3.99, false],
    [2, 3, false], // 3,6 px
    [-2.8, 2.8, false], // 3,96 px
    [4, 0, true],
    [0, 4, true],
    [-4, 0, true],
    [0, -4, true],
    [3, 3, true], // 4,24 px
    [-2.83, -2.83, true], // 4,002 px
    [0, 40, true],
  ])('(%p, %p) → %p', (dx, dy, esperado) => {
    expect(deveIniciarArrasto(dx, dy)).toBe(esperado);
  });

  test.each([
    [NaN, 10],
    [10, NaN],
    [Infinity, 0],
    [0, -Infinity],
    ['10', 0],
    [0, '10'],
    [null, 10],
    [10, undefined],
  ])('um deslocamento que não é um número finito (%p, %p) não inicia', (dx, dy) => {
    expect(deveIniciarArrasto(dx, dy)).toBe(false);
  });
});

// --- teclaNaLista --------------------------------------------------------------------------------

describe('teclaNaLista', () => {
  const NA_LINHA_3 = Object.freeze({ indice: 2, total: 10, nome: 'Café X' });
  const PEGAR =
    'Paragem 3, Café X, pegada. Posição 3 de 10. Use as setas para mover, Espaço para largar ou Escape para cancelar.';
  const CANCELADO = 'Movimento cancelado. Café X voltou à posição 3.';

  const tecla = (estado, nome, extra = {}) => teclaNaLista(estado, { ...NA_LINHA_3, tecla: nome, ...extra });
  const pegada = () => tecla(null, ' ').estado;

  test.each([' ', 'Enter'])('%p pega a paragem', (nome) => {
    expect(tecla(null, nome)).toEqual({
      estado: { de: 2, para: 2, nome: 'Café X' },
      acao: null,
      anuncio: PEGAR,
      tratada: true,
    });
  });

  test('as setas movem uma posição de cada vez', () => {
    let r = tecla(pegada(), 'ArrowDown');
    expect(r).toEqual({ estado: { de: 2, para: 3, nome: 'Café X' }, acao: null, anuncio: 'Posição 4 de 10.', tratada: true });
    r = tecla(r.estado, 'ArrowDown');
    expect(r).toEqual({ estado: { de: 2, para: 4, nome: 'Café X' }, acao: null, anuncio: 'Posição 5 de 10.', tratada: true });
    r = tecla(r.estado, 'ArrowUp');
    expect(r).toEqual({ estado: { de: 2, para: 3, nome: 'Café X' }, acao: null, anuncio: 'Posição 4 de 10.', tratada: true });
    r = tecla(r.estado, 'ArrowUp');
    r = tecla(r.estado, 'ArrowUp');
    expect(r).toEqual({ estado: { de: 2, para: 1, nome: 'Café X' }, acao: null, anuncio: 'Posição 2 de 10.', tratada: true });
  });

  test('as setas param nas pontas e repetem a posição', () => {
    let r = teclaNaLista(null, { tecla: 'Enter', indice: 0, total: 3, nome: 'Café X' });
    r = teclaNaLista(r.estado, { tecla: 'ArrowUp', indice: 0, total: 3, nome: 'Café X' });
    expect(r).toEqual({ estado: { de: 0, para: 0, nome: 'Café X' }, acao: null, anuncio: 'Posição 1 de 3.', tratada: true });
    r = teclaNaLista(null, { tecla: 'Enter', indice: 2, total: 3, nome: 'Café X' });
    r = teclaNaLista(r.estado, { tecla: 'ArrowDown', indice: 2, total: 3, nome: 'Café X' });
    expect(r).toEqual({ estado: { de: 2, para: 2, nome: 'Café X' }, acao: null, anuncio: 'Posição 3 de 3.', tratada: true });
  });

  test.each([' ', 'Enter'])('%p larga a paragem, com a ação de mover', (nome) => {
    const movida = tecla(pegada(), 'ArrowDown').estado;
    expect(tecla(movida, nome)).toEqual({
      estado: null,
      acao: { tipo: 'largar', de: 2, para: 3 },
      anuncio: 'Café X largada na posição 4 de 10.',
      tratada: true,
    });
  });

  test('largar para cima e até às pontas', () => {
    let estado = pegada();
    for (let i = 0; i < 5; i += 1) estado = tecla(estado, 'ArrowUp').estado;
    expect(tecla(estado, 'Enter')).toEqual({
      estado: null,
      acao: { tipo: 'largar', de: 2, para: 0 },
      anuncio: 'Café X largada na posição 1 de 10.',
      tratada: true,
    });
    for (let i = 0; i < 12; i += 1) estado = tecla(estado, 'ArrowDown').estado;
    expect(tecla(estado, ' ').acao).toEqual({ tipo: 'largar', de: 2, para: 9 });
  });

  test('largar no sítio de onde saiu não pede nada ao servidor', () => {
    const voltou = tecla(tecla(pegada(), 'ArrowDown').estado, 'ArrowUp').estado;
    expect(tecla(voltou, ' ')).toEqual({
      estado: null,
      acao: null,
      anuncio: 'Café X largada na posição 3 de 10.',
      tratada: true,
    });
    expect(tecla(pegada(), 'Enter').acao).toBeNull();
  });

  test('o Escape cancela e diz para onde voltou', () => {
    const movida = tecla(tecla(pegada(), 'ArrowDown').estado, 'ArrowDown').estado;
    expect(tecla(movida, 'Escape')).toEqual({ estado: null, acao: null, anuncio: CANCELADO, tratada: true });
    expect(tecla(pegada(), 'Escape')).toEqual({ estado: null, acao: null, anuncio: CANCELADO, tratada: true });
  });

  test('o Tab cancela, mas deixa o foco sair (não é tratada)', () => {
    const movida = tecla(pegada(), 'ArrowUp').estado;
    expect(tecla(movida, 'Tab')).toEqual({ estado: null, acao: null, anuncio: CANCELADO, tratada: false });
  });

  test('a perda do foco com a paragem pegada cancela', () => {
    const movida = tecla(pegada(), 'ArrowDown').estado;
    expect(cancelarMovimento(movida)).toEqual({ estado: null, acao: null, anuncio: CANCELADO, tratada: false });
    expect(cancelarMovimento(pegada())).toEqual({ estado: null, acao: null, anuncio: CANCELADO, tratada: false });
  });

  test.each([null, undefined, {}, { de: 'x', para: 1 }, { de: 1, para: -1 }, 'pegada'])(
    'a perda do foco sem nada pegado (%p) não diz nada',
    (estado) => {
      expect(cancelarMovimento(estado)).toEqual({ estado: null, acao: null, anuncio: null, tratada: false });
    },
  );

  test.each(['ArrowUp', 'ArrowDown', 'Escape', 'Tab'])('%p sem nada pegado não faz nada', (nome) => {
    expect(tecla(null, nome)).toEqual({ estado: null, acao: null, anuncio: null, tratada: false });
  });

  test.each(['a', 'Home', 'End', 'PageDown', 'ArrowLeft', 'ArrowRight', 'Shift', 'Spacebar', 'Esc', '', undefined])(
    'outra tecla (%p) não faz nada, com ou sem paragem pegada',
    (nome) => {
      expect(tecla(null, nome)).toEqual({ estado: null, acao: null, anuncio: null, tratada: false });
      const estado = tecla(pegada(), 'ArrowDown').estado;
      const r = tecla(estado, nome);
      expect(r).toEqual({ estado: { de: 2, para: 3, nome: 'Café X' }, acao: null, anuncio: null, tratada: false });
      expect(r.estado).toBe(estado);
    },
  );

  test('com a paragem pegada, a linha e o nome do evento não contam: valem os da paragem pegada', () => {
    let r = tecla(pegada(), 'ArrowDown', { indice: 7, nome: 'Outra' });
    expect(r.estado).toEqual({ de: 2, para: 3, nome: 'Café X' });
    r = tecla(r.estado, 'Enter', { indice: 0, nome: 'Outra' });
    expect(r.acao).toEqual({ tipo: 'largar', de: 2, para: 3 });
    expect(r.anuncio).toBe('Café X largada na posição 4 de 10.');
    expect(tecla(pegada(), 'Escape', { indice: 9, nome: 'Outra' }).anuncio).toBe(CANCELADO);
  });

  test('o total vem de cada tecla: uma lista mais curta encosta o destino ao fim', () => {
    let estado = pegada();
    for (let i = 0; i < 6; i += 1) estado = tecla(estado, 'ArrowDown').estado; // posição 9 de 10
    expect(estado.para).toBe(8);
    let r = tecla(estado, 'ArrowUp', { total: 5 });
    expect(r).toEqual({ estado: { de: 2, para: 3, nome: 'Café X' }, acao: null, anuncio: 'Posição 4 de 5.', tratada: true });
    r = tecla(estado, 'ArrowDown', { total: 5 });
    expect(r.anuncio).toBe('Posição 5 de 5.');
    r = tecla(estado, ' ', { total: 5 });
    expect(r.acao).toEqual({ tipo: 'largar', de: 2, para: 4 });
    expect(r.anuncio).toBe('Café X largada na posição 5 de 5.');
  });

  test.each([
    ['a lista ficou sem a paragem pegada', 2],
    ['a lista ficou vazia', 0],
    ['um total que não é inteiro', 2.5],
    ['sem total', undefined],
  ])('%s: qualquer das teclas cancela, sem dizer uma posição que já não existe', (_caso, total) => {
    const estado = pegada();
    for (const [nome, tratada] of [[' ', true], ['Enter', true], ['ArrowUp', true], ['ArrowDown', true], ['Escape', true], ['Tab', false]]) {
      expect(tecla(estado, nome, { total })).toEqual({ estado: null, acao: null, anuncio: 'Movimento cancelado.', tratada });
    }
    // As outras teclas continuam a não fazer nada.
    expect(tecla(estado, 'a', { total }).estado).toBe(estado);
  });

  test('uma tecla repetida (a carregar sem largar) não pega nem larga, mas é tratada', () => {
    expect(tecla(null, ' ', { repetida: true })).toEqual({ estado: null, acao: null, anuncio: null, tratada: true });
    expect(tecla(null, 'Enter', { repetida: true })).toEqual({ estado: null, acao: null, anuncio: null, tratada: true });
    const estado = tecla(pegada(), 'ArrowDown').estado;
    const r = tecla(estado, 'Enter', { repetida: true });
    expect(r).toEqual({ estado: { de: 2, para: 3, nome: 'Café X' }, acao: null, anuncio: null, tratada: true });
    expect(r.estado).toBe(estado);
    // As setas repetidas continuam a mover.
    expect(tecla(estado, 'ArrowDown', { repetida: true }).estado).toEqual({ de: 2, para: 4, nome: 'Café X' });
    // Só o `true` conta como repetida.
    expect(tecla(null, ' ', { repetida: 1 }).estado).toEqual({ de: 2, para: 2, nome: 'Café X' });
    expect(tecla(null, ' ', { repetida: 'sim' }).estado).toEqual({ de: 2, para: 2, nome: 'Café X' });
  });

  test.each([
    ['uma linha fora da lista', { indice: 10 }],
    ['uma linha negativa', { indice: -1 }],
    ['uma linha que não é inteira', { indice: 1.5 }],
    ['uma linha em texto', { indice: '2' }],
    ['uma lista vazia', { indice: 0, total: 0 }],
    ['um total que não é inteiro', { total: 10.5 }],
    ['um total em texto', { total: '10' }],
  ])('%s não pega nada', (_caso, extra) => {
    expect(tecla(null, ' ', extra)).toEqual({ estado: null, acao: null, anuncio: null, tratada: false });
  });

  test('uma lista de uma só paragem também se pega (e fica no sítio)', () => {
    const r = teclaNaLista(null, { tecla: 'Enter', indice: 0, total: 1, nome: 'Café X' });
    expect(r.anuncio).toBe(
      'Paragem 1, Café X, pegada. Posição 1 de 1. Use as setas para mover, Espaço para largar ou Escape para cancelar.',
    );
    const r2 = teclaNaLista(r.estado, { tecla: 'ArrowDown', indice: 0, total: 1, nome: 'Café X' });
    expect(r2.anuncio).toBe('Posição 1 de 1.');
    expect(teclaNaLista(r2.estado, { tecla: ' ', indice: 0, total: 1, nome: 'Café X' }).acao).toBeNull();
  });

  test('o nome aparado; sem nome, a paragem diz-se pelo número', () => {
    expect(tecla(null, ' ', { nome: '  Café X  ' }).estado.nome).toBe('Café X');
    for (const nome of ['', '   ', null, undefined, 42, { nome: 'x' }]) {
      const r = tecla(null, 'Enter', { nome });
      expect(r.anuncio).toBe(
        'Paragem 3, pegada. Posição 3 de 10. Use as setas para mover, Espaço para largar ou Escape para cancelar.',
      );
      const movida = tecla(r.estado, 'ArrowDown').estado;
      expect(tecla(movida, ' ').anuncio).toBe('Paragem 3 largada na posição 4 de 10.');
      expect(tecla(movida, 'Escape').anuncio).toBe('Movimento cancelado. Paragem 3 voltou à posição 3.');
    }
  });

  test('um estado vindo de fora com um nome estragado diz a paragem pelo número', () => {
    for (const nome of [42, '   ', null, { nome: 'x' }]) {
      const estado = { de: 2, para: 3, nome };
      expect(tecla(estado, 'Escape').anuncio).toBe('Movimento cancelado. Paragem 3 voltou à posição 3.');
      expect(tecla(estado, ' ').anuncio).toBe('Paragem 3 largada na posição 4 de 10.');
      expect(cancelarMovimento(estado).anuncio).toBe('Movimento cancelado. Paragem 3 voltou à posição 3.');
    }
    expect(tecla({ de: 2, para: 3, nome: '  Café X ' }, 'Tab').anuncio).toBe(CANCELADO);
  });

  test.each([{}, { de: 'x', para: 1 }, { de: 1 }, { de: 1, para: 1.5 }, { de: -1, para: 0 }, 'pegada', 7])(
    'um estado estragado (%p) conta como nada pegado',
    (estado) => {
      expect(tecla(estado, 'ArrowDown')).toEqual({ estado: null, acao: null, anuncio: null, tratada: false });
      expect(tecla(estado, ' ').estado).toEqual({ de: 2, para: 2, nome: 'Café X' });
    },
  );

  test('o estado, a ação e a resposta saem congelados, e o estado recebido não muda', () => {
    const r = tecla(null, ' ');
    expect(Object.isFrozen(r)).toBe(true);
    expect(Object.isFrozen(r.estado)).toBe(true);
    const estado = congelarAFundo({ de: 2, para: 3, nome: 'Café X' });
    const largada = tecla(estado, 'Enter');
    expect(Object.isFrozen(largada)).toBe(true);
    expect(Object.isFrozen(largada.acao)).toBe(true);
    expect(estado).toEqual({ de: 2, para: 3, nome: 'Café X' });
    const movida = tecla(estado, 'ArrowDown');
    expect(Object.isFrozen(movida.estado)).toBe(true);
    expect(estado).toEqual({ de: 2, para: 3, nome: 'Café X' });
    expect(Object.isFrozen(cancelarMovimento(estado))).toBe(true);
    expect(Object.isFrozen(cancelarMovimento(null))).toBe(true);
  });

  test('sem evento não rebenta e não faz nada', () => {
    expect(teclaNaLista(null)).toEqual({ estado: null, acao: null, anuncio: null, tratada: false });
    expect(teclaNaLista(null, null)).toEqual({ estado: null, acao: null, anuncio: null, tratada: false });
  });
});

// --- As instruções -------------------------------------------------------------------------------

test('INSTRUCOES_ARRASTAR', () => {
  expect(INSTRUCOES_ARRASTAR).toBe(
    'Para reordenar: Espaço ou Enter para pegar, setas para mover, Espaço para largar, Escape para cancelar. Também pode arrastar a pega com o rato ou o dedo.',
  );
});

// --- desvioDaLinha (as outras linhas abrem lugar à arrastada) ------------------------------------

describe('desvioDaLinha', () => {
  test('para baixo, as linhas entre a origem e o destino sobem uma', () => {
    // A linha 1 arrastada para a posição 3, numa lista de 5.
    expect([0, 1, 2, 3, 4].map((i) => desvioDaLinha(i, 1, 3))).toEqual([0, 0, -1, -1, 0]);
  });

  test('para cima, as linhas entre o destino e a origem descem uma', () => {
    // A linha 3 arrastada para a posição 1, numa lista de 5.
    expect([0, 1, 2, 3, 4].map((i) => desvioDaLinha(i, 3, 1))).toEqual([0, 1, 1, 0, 0]);
  });

  test('no mesmo sítio, nada se mexe; a arrastada nunca (segue o dedo à parte)', () => {
    expect([0, 1, 2, 3].map((i) => desvioDaLinha(i, 2, 2))).toEqual([0, 0, 0, 0]);
    expect(desvioDaLinha(0, 0, 3)).toBe(0);
    expect(desvioDaLinha(3, 3, 0)).toBe(0);
  });

  test('é a mesma ordem que o mover dá', () => {
    const lista = ['a', 'b', 'c', 'd', 'e'];
    for (let de = 0; de < lista.length; de += 1) {
      for (let para = 0; para < lista.length; para += 1) {
        const movida = mover(lista, de, para);
        lista.forEach((letra, i) => {
          const destino = i === de ? para : i + desvioDaLinha(i, de, para);
          expect(movida[destino]).toBe(letra);
        });
      }
    }
  });

  test.each([
    [1.5, 1, 3],
    [2, '1', 3],
    [2, 1, NaN],
    [null, 1, 3],
    [2, undefined, 3],
  ])('com números que não são inteiros (%p, %p, %p) nada se mexe', (indice, de, para) => {
    expect(Object.is(desvioDaLinha(indice, de, para), 0)).toBe(true);
  });

  test('nunca dá -0', () => {
    for (const [i, de, para] of [[0, 1, 3], [4, 1, 3], [0, 3, 1], [2, 2, 2]]) {
      expect(Object.is(desvioDaLinha(i, de, para), 0)).toBe(true);
    }
  });
});

// --- deslocamentoAutomatico (deslocar a lista perto das pontas) ----------------------------------

describe('deslocamentoAutomatico', () => {
  const CAIXA = Object.freeze({ top: 100, bottom: 500 });

  test('as constantes', () => {
    expect(ZONA_DESLOCAR_PX).toBe(48);
    expect(PASSO_DESLOCAR_PX).toBe(12);
  });

  test.each([
    ['no meio', 300, 0],
    ['logo à entrada da zona de cima', 148, 0],
    ['1 px dentro da zona de cima', 147, -1],
    ['a meio da zona de cima', 124, -6],
    ['na ponta de cima', 100, -12],
    ['acima da lista', 50, -12],
    ['muito acima da lista', -1000, -12],
    ['logo à entrada da zona de baixo', 452, 0],
    ['1 px dentro da zona de baixo', 453, 1],
    ['a meio da zona de baixo', 476, 6],
    ['na ponta de baixo', 500, 12],
    ['abaixo da lista', 900, 12],
  ])('%s (y = %p) → %p px', (_caso, y, esperado) => {
    expect(Object.is(deslocamentoAutomatico(y, CAIXA), esperado)).toBe(true);
  });

  test('numa lista baixa, a zona é metade da altura e o meio fica parado', () => {
    const baixa = { top: 0, bottom: 60 };
    expect(Object.is(deslocamentoAutomatico(30, baixa), 0)).toBe(true);
    expect(deslocamentoAutomatico(29, baixa)).toBe(-1);
    expect(deslocamentoAutomatico(31, baixa)).toBe(1);
    expect(deslocamentoAutomatico(0, baixa)).toBe(-12);
    expect(deslocamentoAutomatico(60, baixa)).toBe(12);
  });

  test.each([
    ['um y que não é número', '300', CAIXA],
    ['um y infinito', Infinity, CAIXA],
    ['um y NaN', NaN, CAIXA],
    ['sem caixa', 300, null],
    ['uma caixa sem top', 300, { bottom: 500 }],
    ['uma caixa com bottom infinito', 120, { top: 100, bottom: Infinity }],
    ['uma caixa em texto', 120, { top: '100', bottom: '500' }],
    ['uma caixa sem altura', 50, { top: 100, bottom: 100 }],
    ['uma caixa virada', 100, { top: 500, bottom: 100 }],
  ])('%s → 0', (_caso, y, caixa) => {
    expect(Object.is(deslocamentoAutomatico(y, caixa), 0)).toBe(true);
  });
});

// --- Módulo puro ---------------------------------------------------------------------------------

test('o reordenar.js é puro: sem imports, sem DOM, sem relógio nem temporizadores', () => {
  const texto = fs.readFileSync(REORDENAR_JS, 'utf8');
  expect(texto).not.toMatch(/^\s*import\b/m);
  expect(texto).not.toMatch(/\brequire\(/);
  expect(texto).not.toMatch(
    /\b(document|window|navigator|globalThis|setTimeout|setInterval|requestAnimationFrame|Date|performance|addEventListener)\b/,
  );
});
