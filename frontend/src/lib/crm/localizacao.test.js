/**
 * A LOCALIZAÇÃO ESCOLHIDA NO SELETOR — pino manual, pesquisa de morada ou GPS.
 *
 * Porta de tests/js/localizacao.test.js do CRM autónomo (etiqueta
 * `referencia-standalone`), tal e qual, com o `node:assert` passado a
 * `expect`. As regras são as do servidor (dossiê §5.2 e §5.4): arrastar o
 * pino faz a origem passar a `pin_manual`; um GPS pior do que 50 m (ou sem
 * precisão conhecida) só confirma depois de arrastar; `precisao_m` só vai com
 * a origem `gps`, arredondada ao metro, e nunca NaN.
 *
 * Mapa Google (plano G9; adenda §2.1, decisão 2): a origem passageira
 * `google` (o negócio tocado no mapa ou a morada da pesquisa da Google) só
 * confirma depois de arrastar o pino até à porta da loja, e nunca sai do
 * seletor — vira sempre `pin_manual`, com o `google_place_id` ao lado. O bloco
 * enviado à API ganhou o `google_place_id` (texto não vazio, ou null): os
 * testes portados acima levam-no a null.
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
    google_place_id: null,
  });
});

test('localizacaoFinal: pino arrastado passa a pin_manual e precisão a null', () => {
  expect(localizacaoFinal({ lat: 38.7, lng: -9.1, origem: 'gps', precisao_m: 120 }, true)).toEqual({
    lat: 38.7,
    lng: -9.1,
    origem_coords: 'pin_manual',
    precisao_m: null,
    google_place_id: null,
  });
});

test('localizacaoFinal: geocoder sem arrastar fica geocoder com precisão null', () => {
  expect(localizacaoFinal({ lat: 38.7, lng: -9.1, origem: 'geocoder' }, false)).toEqual({
    lat: 38.7,
    lng: -9.1,
    origem_coords: 'geocoder',
    precisao_m: null,
    google_place_id: null,
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
    google_place_id: null,
  });
  expect(localizacaoFinal({ lat: 38.7, lng: -9.1, origem: 'pin_manual', precisao_m: 30 }, false)).toEqual({
    lat: 38.7,
    lng: -9.1,
    origem_coords: 'pin_manual',
    precisao_m: null,
    google_place_id: null,
  });
});

test('localizacaoFinal: GPS com precisão inválida envia null (nunca NaN)', () => {
  expect(localizacaoFinal({ lat: 38.7, lng: -9.1, origem: 'gps', precisao_m: Number.NaN }, false)).toEqual({
    lat: 38.7,
    lng: -9.1,
    origem_coords: 'gps',
    precisao_m: null,
    google_place_id: null,
  });
});

// --- Mapa Google (plano G9): a regra do arrasto e o google_place_id --------------------------------

test('podeConfirmar: um pino vindo da Google só confirma depois de arrastar', () => {
  expect(podeConfirmar({ origem: 'google', precisao_m: null, arrastado: false })).toBe(false);
  expect(podeConfirmar({ origem: 'google', precisao_m: null, arrastado: true })).toBe(true);
  // Nem uma precisão boa o dispensa (a coordenada da Google nunca se grava tal e qual).
  expect(podeConfirmar({ origem: 'google', precisao_m: 5, arrastado: false })).toBe(false);
  expect(podeConfirmar({ origem: 'google', arrastado: false })).toBe(false);
});

test('origemFinal: a origem google nunca sai do seletor (vira sempre pin_manual)', () => {
  expect(origemFinal('google', true)).toBe('pin_manual');
  expect(origemFinal('google', false)).toBe('pin_manual');
});

test('localizacaoFinal: pino da Google arrastado → pin_manual, sem precisão, com o google_place_id', () => {
  const final = localizacaoFinal(
    { lat: 38.70921, lng: -9.13712, origem: 'google', precisao_m: 7, google_place_id: 'ChIJa1b2c3' },
    true,
  );
  expect(final).toStrictEqual({
    lat: 38.70921,
    lng: -9.13712,
    origem_coords: 'pin_manual',
    precisao_m: null,
    google_place_id: 'ChIJa1b2c3',
  });
  expect(Object.keys(final)).toEqual(['lat', 'lng', 'origem_coords', 'precisao_m', 'google_place_id']);
});

test('localizacaoFinal: o pino guardado de um lugar da Google (a correção na ficha) leva o id sem arrastar', () => {
  expect(localizacaoFinal({ lat: 38.7, lng: -9.1, origem: 'pin_manual', google_place_id: 'ChIJa1b2c3' }, false)).toStrictEqual({
    lat: 38.7,
    lng: -9.1,
    origem_coords: 'pin_manual',
    precisao_m: null,
    google_place_id: 'ChIJa1b2c3',
  });
});

test('localizacaoFinal: sem google_place_id em texto não vazio → null', () => {
  for (const google_place_id of [undefined, null, '', '   ', 7, ['ChIJa'], { id: 'ChIJa' }]) {
    const final = localizacaoFinal({ lat: 38.7, lng: -9.1, origem: 'google', google_place_id }, true);
    expect(final.google_place_id).toBeNull();
    expect(Object.keys(final)).toEqual(['lat', 'lng', 'origem_coords', 'precisao_m', 'google_place_id']);
  }
});

test('localizacaoFinal: nunca devolve a origem google, em nenhum caminho', () => {
  for (const origem of ['google', 'gps', 'pin_manual', 'geocoder']) {
    for (const arrastado of [false, true]) {
      for (const precisao_m of [null, 12, 120]) {
        const final = localizacaoFinal({ lat: 38.7, lng: -9.1, origem, precisao_m, google_place_id: 'ChIJa' }, arrastado);
        expect(final.origem_coords).not.toBe('google');
        expect(Object.keys(final)).toEqual(['lat', 'lng', 'origem_coords', 'precisao_m', 'google_place_id']);
      }
    }
  }
});
