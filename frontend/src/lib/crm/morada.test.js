/**
 * A MORADA DA LOJA — os campos que a morada escolhida (na pesquisa da Google)
 * ou a morada sugerida pelo GPS preenchem, o ponto da inversa e a mensagem
 * da morada sugerida indisponível.
 *
 * Porta de tests/js/morada.test.js do CRM autónomo (etiqueta
 * `referencia-standalone`), com o `node:assert` passado a `expect`. A pesquisa
 * de moradas da Geoapify (o `criarPesquisaMorada`, a espera entre teclas e a
 * mensagem do 503 dela) saiu na G11 do plano do mapa Google: a pesquisa é o
 * elemento da própria Google, no seletor (`lugarGoogle.js`), e a morada que
 * ela dá chega na mesma forma (`{rotulo, morada, codigo_postal, localidade,
 * lat, lng}`), por isso o `camposDaMorada` serve as duas.
 *
 * A mensagem da morada sugerida tem de ser a do 503 do servidor
 * (`backend/crm/morada.py`, `INVERSA_INDISPONIVEL`), vigiada pelo
 * `backend/tests/crm/test_consistencia_frontend.py`.
 */
import * as morada from './morada';
import {
  camposDaMorada,
  camposSugeridos,
  pontoDeBias,
  CAMPOS_MORADA,
  MENSAGEM_MORADA_SUGERIDA_INDISPONIVEL,
} from './morada';

// --- O que o módulo tem (G11) -------------------------------------------------------------------

test('a pesquisa de moradas da Geoapify saiu: ficam os campos, a morada sugerida e o ponto da inversa', () => {
  expect(Object.keys(morada).sort()).toEqual([
    'CAMPOS_MORADA',
    'MENSAGEM_MORADA_SUGERIDA_INDISPONIVEL',
    'camposDaMorada',
    'camposSugeridos',
    'pontoDeBias',
  ]);
  expect(morada.criarPesquisaMorada).toBeUndefined();
  expect(morada.MENSAGEM_MORADA_INDISPONIVEL).toBeUndefined();
});

// --- Campos da loja preenchidos pela sugestão escolhida (E6) ------------------------------------

const AUGUSTA = {
  rotulo: 'Rua Augusta 24, 1100-048 Lisboa, Portugal',
  morada: 'Rua Augusta 24',
  codigo_postal: '1100-048',
  localidade: 'Lisboa',
  lat: 38.70921,
  lng: -9.13712,
};
const VAZIOS = { morada: '', codigo_postal: '', localidade: '' };

test('CAMPOS_MORADA: morada, código postal e localidade', () => {
  expect([...CAMPOS_MORADA]).toEqual(['morada', 'codigo_postal', 'localidade']);
});

test('camposDaMorada: a sugestão preenche a morada, o código postal e a localidade', () => {
  expect(camposDaMorada(AUGUSTA, VAZIOS, {})).toEqual({
    morada: 'Rua Augusta 24',
    codigo_postal: '1100-048',
    localidade: 'Lisboa',
  });
});

test('camposDaMorada: a sugestão substitui o que lá estava', () => {
  const atuais = { morada: 'Rua do Ouro', codigo_postal: '1100-060', localidade: 'Lisbo' };
  expect(camposDaMorada(AUGUSTA, atuais, {})).toEqual({
    morada: 'Rua Augusta 24',
    codigo_postal: '1100-048',
    localidade: 'Lisboa',
  });
});

test('camposDaMorada: o que a sugestão não tem fica como a pessoa o escreveu', () => {
  const semCodigo = { ...AUGUSTA, codigo_postal: null, morada: null };
  const atuais = { morada: 'Rua Augusta, loja 3', codigo_postal: '1100-048', localidade: '' };
  expect(camposDaMorada(semCodigo, atuais, {})).toEqual({ localidade: 'Lisboa' });
});

test('camposDaMorada: o que a sugestão anterior lá pôs, e a pessoa não mudou, esvazia-se', () => {
  const cascais = {
    rotulo: 'Rua Augusta, 2750 Cascais, Portugal',
    morada: 'Rua Augusta',
    codigo_postal: null,
    localidade: 'Cascais',
    lat: 38.6979,
    lng: -9.4215,
  };
  const anteriores = { morada: 'Rua Augusta 24', codigo_postal: '1100-048', localidade: 'Lisboa' };
  expect(camposDaMorada(cascais, anteriores, anteriores)).toEqual({
    morada: 'Rua Augusta',
    codigo_postal: '',
    localidade: 'Cascais',
  });
  const mudado = { ...anteriores, codigo_postal: '2750-001' };
  expect(camposDaMorada(cascais, mudado, anteriores)).toEqual({ morada: 'Rua Augusta', localidade: 'Cascais' });
});

test('camposDaMorada: valores que não são texto, ou só espaços, contam como em falta', () => {
  const estranha = { rotulo: 'x', morada: 7, codigo_postal: '   ', localidade: undefined, lat: 38.7, lng: -9.1 };
  expect(camposDaMorada(estranha, VAZIOS, {})).toEqual({});
  expect(camposDaMorada({ ...AUGUSTA, localidade: '  Lisboa ' }, VAZIOS).localidade).toBe('Lisboa');
  expect(camposDaMorada(null, VAZIOS, {})).toEqual({});
});

test('pontoDeBias: o ponto com até 6 casas decimais; sem ponto válido, null', () => {
  expect(pontoDeBias({ lat: 38.72230000123, lng: -9.13930000456 })).toEqual({ lat: 38.7223, lng: -9.1393 });
  expect(pontoDeBias({ lat: 38.7, lng: -9.1, alt: 3 })).toEqual({ lat: 38.7, lng: -9.1 });
  const invalidos = [
    null,
    undefined,
    {},
    { lat: '38.7', lng: -9.1 },
    { lat: Number.NaN, lng: -9.1 },
    { lat: 38.7, lng: Infinity },
    { lat: 91, lng: 0 },
    { lat: 0, lng: -181 },
  ];
  for (const invalido of invalidos) {
    expect(pontoDeBias(invalido)).toBeNull();
  }
});

test('pontoDeBias: nunca escreve o número com expoente (o servidor ignoraria o bias)', () => {
  const ponto = pontoDeBias({ lat: 0.0000001, lng: -0.0000001 });
  expect(String(ponto.lat)).toBe('0');
  expect(String(ponto.lng)).toBe('0');
});

// --- Morada sugerida pela geocodificação inversa do GPS (E7) --------------------------------------

const PRACA = {
  rotulo: 'Praça do Comércio, 1100-148 Lisboa, Portugal',
  morada: 'Praça do Comércio',
  codigo_postal: '1100-148',
  localidade: 'Lisboa',
  lat: 38.70749,
  lng: -9.13648,
};

test('MENSAGEM_MORADA_SUGERIDA_INDISPONIVEL é a do servidor (crm/morada.py, INVERSA_INDISPONIVEL)', () => {
  expect(MENSAGEM_MORADA_SUGERIDA_INDISPONIVEL).toBe('Morada sugerida indisponível — escreva a morada à mão.');
});

test('camposSugeridos: preenche só os campos vazios', () => {
  expect(camposSugeridos(PRACA, VAZIOS, {})).toEqual({
    morada: 'Praça do Comércio',
    codigo_postal: '1100-148',
    localidade: 'Lisboa',
  });
  // O que a pessoa escreveu fica.
  const atuais = { morada: 'Rua do Ouro 3', codigo_postal: '  ', localidade: 'Lisbo' };
  expect(camposSugeridos(PRACA, atuais, {})).toEqual({ codigo_postal: '1100-148' });
});

test('camposSugeridos: o que a app lá pôs antes (e a pessoa não mudou) pode ser substituído', () => {
  const anteriores = { morada: 'Rua Augusta 24', codigo_postal: '1100-048', localidade: 'Lisboa' };
  expect(camposSugeridos(PRACA, anteriores, anteriores)).toEqual({
    morada: 'Praça do Comércio',
    codigo_postal: '1100-148',
    localidade: 'Lisboa',
  });
  const mudado = { ...anteriores, morada: 'Rua Augusta 24, loja 2' };
  expect(camposSugeridos(PRACA, mudado, anteriores)).toEqual({ codigo_postal: '1100-148', localidade: 'Lisboa' });
});

test('camposSugeridos: sem o valor na sugestão, só se esvazia o que a app lá pôs', () => {
  const semCodigo = { ...PRACA, codigo_postal: null };
  const anteriores = { morada: 'Rua Augusta 24', codigo_postal: '1100-048', localidade: 'Lisboa' };
  expect(camposSugeridos(semCodigo, anteriores, anteriores)).toEqual({
    morada: 'Praça do Comércio',
    codigo_postal: '',
    localidade: 'Lisboa',
  });
  const escrito = { morada: '', codigo_postal: '1100-001', localidade: '' };
  expect(camposSugeridos(semCodigo, escrito, {})).toEqual({ morada: 'Praça do Comércio', localidade: 'Lisboa' });
});

test('camposSugeridos: valores que não são texto, ou só espaços, contam como em falta', () => {
  const estranha = { rotulo: 'x', morada: 7, codigo_postal: '   ', localidade: undefined, lat: 38.7, lng: -9.1 };
  expect(camposSugeridos(estranha, VAZIOS, {})).toEqual({});
  expect(camposSugeridos({ ...PRACA, localidade: '  Lisboa ' }, VAZIOS).localidade).toBe('Lisboa');
  expect(camposSugeridos(null, VAZIOS, {})).toEqual({});
  // Campos em falta contam como vazios.
  expect(camposSugeridos(PRACA, {}, undefined)).toEqual({
    morada: 'Praça do Comércio',
    codigo_postal: '1100-148',
    localidade: 'Lisboa',
  });
});

test('camposDaMorada: a morada escolhida na pesquisa da Google (a forma do moradaDoLugar) preenche os três campos', () => {
  const daGoogle = {
    rotulo: 'R. Augusta 24, 1100-048 Lisboa, Portugal',
    morada: 'Rua Augusta 24',
    codigo_postal: '1100-048',
    localidade: 'Lisboa',
    lat: 38.71021,
    lng: -9.13695,
  };
  expect(camposDaMorada(daGoogle, VAZIOS, {})).toEqual({
    morada: 'Rua Augusta 24', codigo_postal: '1100-048', localidade: 'Lisboa',
  });
  // Um lugar da Google sem rua nem código postal (só a localidade): o que a escolha anterior lá pôs sai.
  const soLocalidade = { ...daGoogle, morada: null, codigo_postal: null };
  const anteriores = { morada: 'Rua Augusta 24', codigo_postal: '1100-048', localidade: 'Lisboa' };
  expect(camposDaMorada(soLocalidade, anteriores, anteriores)).toEqual({
    morada: '', codigo_postal: '', localidade: 'Lisboa',
  });
});

// --- Extra (portal) ------------------------------------------------------------------------------

test('pontoDeBias: guarda a 6.ª casa e aceita os limites do servidor (|lat| ≤ 90, |lng| ≤ 180)', () => {
  expect(pontoDeBias({ lat: 38.7223451, lng: -9.1393449 })).toEqual({ lat: 38.722345, lng: -9.139345 });
  // crm/morada.py: o bias serve com qualquer ponto do mundo dentro destes limites (T2.15).
  expect(pontoDeBias({ lat: 90, lng: 180 })).toEqual({ lat: 90, lng: 180 });
  expect(pontoDeBias({ lat: -90, lng: -180 })).toEqual({ lat: -90, lng: -180 });
});
