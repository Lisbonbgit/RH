/**
 * A LOCALIZAÇÃO ESCOLHIDA NO SELETOR — pino manual, pesquisa de morada ou GPS.
 *
 * Porta de tests/js/localizacao.test.js do CRM autónomo (etiqueta
 * `referencia-standalone`), tal e qual, com o `node:assert` passado a
 * `expect`. As regras são as do servidor (dossiê §5.2 e §5.4): arrastar o
 * pino faz a origem passar a `pin_manual`; um GPS pior do que 50 m (ou sem
 * precisão conhecida) só confirma depois de arrastar; `precisao_m` só vai com
 * a origem `gps`, arredondada ao metro, e nunca NaN.
 */
import { origemFinal, podeConfirmar, localizacaoFinal } from './localizacao';

test('origemFinal: pino arrastado passa a pin_manual', () => {
  expect(origemFinal('gps', true)).toBe('pin_manual');
  expect(origemFinal('geocoder', true)).toBe('pin_manual');
  expect(origemFinal('pin_manual', true)).toBe('pin_manual');
});

test('origemFinal: sem arrastar mantém a origem inicial', () => {
  expect(origemFinal('gps', false)).toBe('gps');
  expect(origemFinal('geocoder', false)).toBe('geocoder');
  expect(origemFinal('pin_manual', false)).toBe('pin_manual');
});

test('podeConfirmar: GPS impreciso só confirma depois de arrastar o pino', () => {
  expect(podeConfirmar({ origem: 'gps', precisao_m: 51, arrastado: false })).toBe(false);
  expect(podeConfirmar({ origem: 'gps', precisao_m: 51, arrastado: true })).toBe(true);
});

test('podeConfirmar: GPS com boa precisão confirma sem arrastar', () => {
  expect(podeConfirmar({ origem: 'gps', precisao_m: 50, arrastado: false })).toBe(true);
});

test('podeConfirmar: pino manual e geocoder confirmam sempre', () => {
  expect(podeConfirmar({ origem: 'pin_manual', precisao_m: null, arrastado: false })).toBe(true);
  expect(podeConfirmar({ origem: 'geocoder', precisao_m: null, arrastado: false })).toBe(true);
});

test('localizacaoFinal: GPS sem arrastar envia origem gps e precisão arredondada', () => {
  expect(localizacaoFinal({ lat: 38.7075, lng: -9.1364, origem: 'gps', precisao_m: 12.6 }, false)).toEqual({
    lat: 38.7075,
    lng: -9.1364,
    origem_coords: 'gps',
    precisao_m: 13,
  });
});

test('localizacaoFinal: pino arrastado passa a pin_manual e precisão a null', () => {
  expect(localizacaoFinal({ lat: 38.7, lng: -9.1, origem: 'gps', precisao_m: 120 }, true)).toEqual({
    lat: 38.7,
    lng: -9.1,
    origem_coords: 'pin_manual',
    precisao_m: null,
  });
});

test('localizacaoFinal: geocoder sem arrastar fica geocoder com precisão null', () => {
  expect(localizacaoFinal({ lat: 38.7, lng: -9.1, origem: 'geocoder' }, false)).toEqual({
    lat: 38.7,
    lng: -9.1,
    origem_coords: 'geocoder',
    precisao_m: null,
  });
});

test('podeConfirmar: GPS sem precisão conhecida não confirma sem arrastar', () => {
  for (const precisao_m of [null, undefined, Number.NaN]) {
    expect(podeConfirmar({ origem: 'gps', precisao_m, arrastado: false })).toBe(false);
    expect(podeConfirmar({ origem: 'gps', precisao_m, arrastado: true })).toBe(true);
  }
});

test('localizacaoFinal: origem que não é gps nunca leva precisão, mesmo que sobre uma antiga', () => {
  expect(localizacaoFinal({ lat: 38.7, lng: -9.1, origem: 'geocoder', precisao_m: 30 }, false)).toEqual({
    lat: 38.7,
    lng: -9.1,
    origem_coords: 'geocoder',
    precisao_m: null,
  });
  expect(localizacaoFinal({ lat: 38.7, lng: -9.1, origem: 'pin_manual', precisao_m: 30 }, false)).toEqual({
    lat: 38.7,
    lng: -9.1,
    origem_coords: 'pin_manual',
    precisao_m: null,
  });
});

test('localizacaoFinal: GPS com precisão inválida envia null (nunca NaN)', () => {
  expect(localizacaoFinal({ lat: 38.7, lng: -9.1, origem: 'gps', precisao_m: Number.NaN }, false)).toEqual({
    lat: 38.7,
    lng: -9.1,
    origem_coords: 'gps',
    precisao_m: null,
  });
});
