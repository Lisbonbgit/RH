/**
 * OS LUGARES DA GOOGLE — só a posição e a morada (plano do mapa Google, G9;
 * adenda §6.3; regra 9 do §0).
 *
 * O `lugarGoogle.js` é o único ficheiro do CRM que fala com a biblioteca
 * `places` da Google. Fixa-se aqui:
 *   - as duas listas de campos que se pedem (a posição de um negócio; a
 *     posição e a morada de uma pesquisa) e a dos permitidos;
 *   - `pontoDoLugar` e `moradaDoLugar` leem SÓ as suas chaves e devolvem
 *     objetos com as chaves exatas: um lugar com dez dados de negócio a mais
 *     (os canários, escritos por extenso só neste ficheiro de testes, que o
 *     varrimento não lê) nunca os deixa passar;
 *   - `posicaoDoLugar`/`lugarDaPesquisa` pedem exatamente uma das listas
 *     (provado pelo `registo.camposPedidos` do Google falso);
 *   - a pesquisa da Google (`criarPesquisaLugar`): região `pt`, o enviesamento
 *     pelos limites do mapa ao focar, só a última escolha conta, as falhas,
 *     e nada depois de destruir;
 *   - o painel do negócio selecionado (`criarNegocioSelecionado`): a vista
 *     congelada com quatro chaves, sem nenhum dado da Google;
 *   - os textos, cada um numa só linha.
 */
import fs from 'fs';
import path from 'path';
import { LatLngBoundsFalsos, LatLngFalso, googleFalso } from './testes/googleFalso';
import { documentoFalso } from './testes/domFalso';
import {
  CAMPOS_MORADA_GOOGLE,
  CAMPOS_PERMITIDOS,
  CAMPOS_POSICAO,
  ROTULO_NEGOCIO,
  TEXTO_ADICIONAR_COMO_LOJA,
  TEXTO_A_POSICIONAR,
  TEXTO_ESCREVA_O_NOME,
  TEXTO_FECHAR_NEGOCIO,
  TEXTO_LUGAR_INDISPONIVEL,
  TEXTO_NEGOCIO_SELECIONADO,
  TEXTO_PESQUISAR_LUGAR,
  TEXTO_USAR_ESTE_NEGOCIO,
  criarNegocioSelecionado,
  criarPesquisaLugar,
  lugarDaPesquisa,
  moradaDoLugar,
  pontoDoLugar,
  posicaoDoLugar,
} from './lugarGoogle';

// --- Apoio ------------------------------------------------------------------------------------------

// Dez dados de negócio que a Google tem e o CRM nunca lê (os valores são sentinelas).
const CANARIOS = Object.freeze({
  displayName: 'CANÁRIO-NOME',
  shortFormattedAddress: 'CANÁRIO-MORADA-CURTA',
  nationalPhoneNumber: 'CANÁRIO-TELEFONE',
  internationalPhoneNumber: 'CANÁRIO-TELEFONE',
  websiteUri: 'CANÁRIO-SITE',
  googleMapsURI: 'CANÁRIO-SITE',
  regularOpeningHours: { weekdayDescriptions: ['CANÁRIO-HORÁRIO'] },
  businessStatus: 'CANÁRIO-ESTADO',
  rating: 4.9,
  photos: ['CANÁRIO-FOTO'],
});

// Nem os valores (as sentinelas) nem os nomes dos canários aparecem (o `rating` é um número).
const semCanarios = (valor) => {
  const texto = JSON.stringify(valor) ?? '';
  return !texto.includes('CANÁRIO') && Object.keys(CANARIOS).every((nome) => !texto.includes(nome));
};

// Um lugar que regista as chaves lidas (uma cópia inteira, `{...lugar}`, pede todas as chaves).
function vigiado(objeto) {
  const lidas = [];
  const proxy = new Proxy(objeto, {
    get(alvo, chave, recetor) {
      if (typeof chave === 'string') lidas.push(chave);
      return Reflect.get(alvo, chave, recetor);
    },
    ownKeys(alvo) {
      lidas.push('(todas as chaves)');
      return Reflect.ownKeys(alvo);
    },
  });
  return { proxy, lidas };
}

const fora = (lidas, permitidas) => lidas.filter((chave) => !permitidas.includes(chave));

// Os componentes de uma morada como a Google os dá (types + longText + shortText).
const COMPONENTES_AUGUSTA = Object.freeze([
  { types: ['street_number'], longText: '24', shortText: '24' },
  { types: ['route'], longText: 'Rua Augusta', shortText: 'R. Augusta' },
  { types: ['locality', 'political'], longText: 'Lisboa', shortText: 'Lisboa' },
  { types: ['administrative_area_level_2', 'political'], longText: 'Lisboa', shortText: 'Lisboa' },
  { types: ['administrative_area_level_1', 'political'], longText: 'Lisboa', shortText: 'Lisboa' },
  { types: ['country', 'political'], longText: 'Portugal', shortText: 'PT' },
  { types: ['postal_code'], longText: '1100-048', shortText: '1100-048' },
]);
const ROTULO_AUGUSTA = 'R. Augusta 24, 1100-048 Lisboa, Portugal';
const MORADA_AUGUSTA = Object.freeze({
  rotulo: ROTULO_AUGUSTA,
  morada: 'Rua Augusta 24',
  codigo_postal: '1100-048',
  localidade: 'Lisboa',
});

const so = (...componentes) => ({ formattedAddress: 'X', addressComponents: componentes });
const comp = (tipo, longText) => ({ types: [tipo, 'political'], longText, shortText: 'curto' });

// Deixa correr os .then pendentes (o Google falso responde de forma assíncrona).
const esperar = () => new Promise((resolver) => {
  setTimeout(resolver, 0);
});

// Atrasa o pedido dos campos do lugar `id` até se chamar a função devolvida.
function atrasar(google, id) {
  const original = google.maps.places.Place.prototype.fetchFields;
  let soltar;
  const porta = new Promise((resolver) => {
    soltar = resolver;
  });
  google.maps.places.Place.prototype.fetchFields = async function atrasado(pedido) {
    if (this.id === id) await porta;
    return original.call(this, pedido);
  };
  return () => soltar();
}

// --- As listas de campos -----------------------------------------------------------------------------

test('as listas de campos são as fixadas, congeladas, e cabem nas permitidas', () => {
  expect(CAMPOS_POSICAO).toEqual(['location']);
  expect(CAMPOS_MORADA_GOOGLE).toEqual(['location', 'formattedAddress', 'addressComponents']);
  expect(CAMPOS_PERMITIDOS).toEqual(['id', 'location', 'formattedAddress', 'addressComponents']);
  for (const lista of [CAMPOS_POSICAO, CAMPOS_MORADA_GOOGLE, CAMPOS_PERMITIDOS]) {
    expect(Object.isFrozen(lista)).toBe(true);
  }
  for (const campo of [...CAMPOS_POSICAO, ...CAMPOS_MORADA_GOOGLE]) expect(CAMPOS_PERMITIDOS).toContain(campo);
});

// --- pontoDoLugar -----------------------------------------------------------------------------------

describe('pontoDoLugar', () => {
  test('location literal {lat, lng} → {id, lat, lng}', () => {
    expect(pontoDoLugar({ id: 'ChIJa', location: { lat: 38.7075, lng: -9.1364 } })).toStrictEqual({
      id: 'ChIJa', lat: 38.7075, lng: -9.1364,
    });
  });

  test('location LatLng (lat() e lng() em função) → {id, lat, lng}', () => {
    expect(pontoDoLugar({ id: 'ChIJa', location: new LatLngFalso(38.7075, -9.1364) })).toStrictEqual({
      id: 'ChIJa', lat: 38.7075, lng: -9.1364,
    });
  });

  test.each([
    ['sem lugar', null],
    ['indefinido', undefined],
    ['um texto', 'ChIJa'],
    ['sem id', { location: { lat: 38.7, lng: -9.1 } }],
    ['id vazio', { id: '', location: { lat: 38.7, lng: -9.1 } }],
    ['id só com espaços', { id: '   ', location: { lat: 38.7, lng: -9.1 } }],
    ['id que não é texto', { id: 7, location: { lat: 38.7, lng: -9.1 } }],
    ['sem location', { id: 'ChIJa' }],
    ['location null', { id: 'ChIJa', location: null }],
    ['lat NaN', { id: 'ChIJa', location: { lat: Number.NaN, lng: -9.1 } }],
    ['lng infinito', { id: 'ChIJa', location: { lat: 38.7, lng: Number.POSITIVE_INFINITY } }],
    ['lat em texto', { id: 'ChIJa', location: { lat: '38.7', lng: -9.1 } }],
    ['LatLng com NaN', { id: 'ChIJa', location: { lat: () => Number.NaN, lng: () => -9.1 } }],
    ['par do mapa antigo', { id: 'ChIJa', location: [38.7, -9.1] }],
  ])('%s → null', (_caso, lugar) => {
    expect(pontoDoLugar(lugar)).toBeNull();
  });

  test('canário: com dez dados de negócio a mais, devolve exatamente id, lat e lng', () => {
    const ponto = pontoDoLugar({ id: 'ChIJa', location: { lat: 38.7, lng: -9.1 }, ...CANARIOS });
    expect(Object.keys(ponto)).toEqual(['id', 'lat', 'lng']);
    expect(semCanarios(ponto)).toBe(true);
  });

  test('só lê o id e a location do lugar (nunca o copia inteiro)', () => {
    const { proxy, lidas } = vigiado({ id: 'ChIJa', location: { lat: 38.7, lng: -9.1 }, ...CANARIOS });
    pontoDoLugar(proxy);
    expect(lidas.length).toBeGreaterThan(0);
    expect(fora(lidas, ['id', 'location'])).toEqual([]);
  });
});

// --- moradaDoLugar ----------------------------------------------------------------------------------

describe('moradaDoLugar', () => {
  test('a morada completa, na forma da sugestão da Geoapify (as chaves por esta ordem)', () => {
    const morada = moradaDoLugar({ formattedAddress: ROTULO_AUGUSTA, addressComponents: COMPONENTES_AUGUSTA });
    expect(morada).toStrictEqual(MORADA_AUGUSTA);
    expect(Object.keys(morada)).toEqual(['rotulo', 'morada', 'codigo_postal', 'localidade']);
  });

  test('o rótulo é a formattedAddress aparada; sem ela, null e o resto na mesma', () => {
    expect(moradaDoLugar({ formattedAddress: `  ${ROTULO_AUGUSTA}\n`, addressComponents: COMPONENTES_AUGUSTA }).rotulo)
      .toBe(ROTULO_AUGUSTA);
    for (const formattedAddress of [undefined, null, '', '   ', 42, ['Rua Augusta']]) {
      expect(moradaDoLugar({ formattedAddress, addressComponents: COMPONENTES_AUGUSTA })).toStrictEqual({
        ...MORADA_AUGUSTA, rotulo: null,
      });
    }
  });

  test('a morada é a rua com o número de polícia; só a rua sem número; null sem rua', () => {
    expect(moradaDoLugar(so(comp('route', 'Rua Augusta'))).morada).toBe('Rua Augusta');
    expect(moradaDoLugar(so(comp('street_number', '24'))).morada).toBeNull();
    expect(moradaDoLugar(so(comp('route', '   '), comp('street_number', '24'))).morada).toBeNull();
    expect(moradaDoLugar(so(comp('street_number', ' 24 '), comp('route', ' Rua Augusta '))).morada).toBe('Rua Augusta 24');
    expect(moradaDoLugar(so(comp('route', 'Rua Augusta'), comp('street_number', ''))).morada).toBe('Rua Augusta');
  });

  test('o código postal só no formato 0000-000', () => {
    expect(moradaDoLugar(so(comp('postal_code', '1100-048'))).codigo_postal).toBe('1100-048');
    expect(moradaDoLugar(so(comp('postal_code', ' 1100-048 '))).codigo_postal).toBe('1100-048');
    for (const codigo of ['1100', '1100-04', '1100-0481', '11000-048', 'AB12-345', '1100 048', '', '١١٠٠-٠٤٨']) {
      expect(moradaDoLugar(so(comp('postal_code', codigo))).codigo_postal).toBeNull();
    }
  });

  test('a localidade: locality, senão postal_town, senão administrative_area_level_3, senão _level_2', () => {
    const localidade = (...componentes) => moradaDoLugar(so(...componentes)).localidade;
    const todos = [
      comp('administrative_area_level_2', 'Distrito'),
      comp('administrative_area_level_3', 'Freguesia'),
      comp('postal_town', 'Correio'),
      comp('locality', 'Lisboa'),
    ];
    expect(localidade(...todos)).toBe('Lisboa');
    expect(localidade(...todos.slice(0, 3))).toBe('Correio');
    expect(localidade(...todos.slice(0, 2))).toBe('Freguesia');
    expect(localidade(...todos.slice(0, 1))).toBe('Distrito');
    expect(localidade()).toBeNull();
    // Um texto vazio não conta: passa à seguinte.
    expect(localidade(comp('locality', '  '), comp('administrative_area_level_2', 'Distrito'))).toBe('Distrito');
    // Outros tipos (a freguesia urbana, o distrito, o país) não são a localidade.
    expect(localidade(comp('sublocality', 'Baixa'), comp('administrative_area_level_1', 'Lisboa'), comp('country', 'Portugal')))
      .toBeNull();
  });

  test('os componentes leem-se pelos types e pelo longText (o shortText nunca)', () => {
    const soCurto = { types: ['route'], shortText: 'R. Augusta' };
    expect(moradaDoLugar(so(soCurto)).morada).toBeNull();
    const morada = moradaDoLugar(so({ types: ['route'], longText: 'Rua Augusta', shortText: 'R. Augusta' }));
    expect(morada.morada).toBe('Rua Augusta');
  });

  test('sem addressComponents (ou estragados), tudo null menos o rótulo; nunca rebenta', () => {
    const vazia = { rotulo: ROTULO_AUGUSTA, morada: null, codigo_postal: null, localidade: null };
    for (const addressComponents of [undefined, null, {}, 'Rua Augusta', 7]) {
      expect(moradaDoLugar({ formattedAddress: ROTULO_AUGUSTA, addressComponents })).toStrictEqual(vazia);
    }
    const estragados = [null, 7, 'route', { types: 'route', longText: 'Rua A' }, { types: ['route'], longText: 7 }, { types: null }];
    expect(moradaDoLugar({ formattedAddress: ROTULO_AUGUSTA, addressComponents: estragados })).toStrictEqual(vazia);
    for (const lugar of [null, undefined, 'Rua Augusta']) {
      expect(moradaDoLugar(lugar)).toStrictEqual({ rotulo: null, morada: null, codigo_postal: null, localidade: null });
    }
  });

  test('canário: com dez dados de negócio a mais, devolve exatamente as quatro chaves', () => {
    const morada = moradaDoLugar({
      formattedAddress: ROTULO_AUGUSTA, addressComponents: COMPONENTES_AUGUSTA, location: { lat: 1, lng: 2 }, ...CANARIOS,
    });
    expect(morada).toStrictEqual(MORADA_AUGUSTA);
    expect(semCanarios(morada)).toBe(true);
  });

  test('só lê a formattedAddress e os addressComponents do lugar', () => {
    const { proxy, lidas } = vigiado({ formattedAddress: ROTULO_AUGUSTA, addressComponents: COMPONENTES_AUGUSTA, ...CANARIOS });
    moradaDoLugar(proxy);
    expect(lidas.length).toBeGreaterThan(0);
    expect(fora(lidas, ['formattedAddress', 'addressComponents'])).toEqual([]);
  });
});

// --- posicaoDoLugar e lugarDaPesquisa ---------------------------------------------------------------

describe('posicaoDoLugar (o negócio tocado no mapa: só a location)', () => {
  test('pede só a location e devolve {id, lat, lng}', async () => {
    const { google, registo } = googleFalso();
    registo.lugares.ChIJa = { lat: 38.7075, lng: -9.1364, formattedAddress: ROTULO_AUGUSTA, ...CANARIOS };
    const ponto = await posicaoDoLugar(google, 'ChIJa');
    expect(ponto).toStrictEqual({ id: 'ChIJa', lat: 38.7075, lng: -9.1364 });
    expect(registo.camposPedidos).toEqual([{ id: 'ChIJa', fields: ['location'] }]);
    expect(semCanarios(ponto)).toBe(true);
    // A location chega ora como LatLng ora como literal: as duas servem.
    await expect(posicaoDoLugar(google, 'ChIJa')).resolves.toStrictEqual(ponto);
    expect(registo.camposPedidos).toEqual([{ id: 'ChIJa', fields: ['location'] }, { id: 'ChIJa', fields: ['location'] }]);
    expect(registo.infoWindowsNossas).toBe(0);
  });

  test('a Google não encontra o lugar (NOT_FOUND) → rejeita', async () => {
    const { google, registo } = googleFalso();
    await expect(posicaoDoLugar(google, 'ChIJnada')).rejects.toThrow('NOT_FOUND');
    registo.lugares.ChIJfalha = { lat: 38.7, lng: -9.1, falha: true };
    await expect(posicaoDoLugar(google, 'ChIJfalha')).rejects.toThrow('NOT_FOUND');
  });

  test('um lugar sem posição → rejeita "lugar sem posição"', async () => {
    const { google, registo } = googleFalso();
    registo.lugares.ChIJa = { formattedAddress: ROTULO_AUGUSTA };
    await expect(posicaoDoLugar(google, 'ChIJa')).rejects.toThrow('lugar sem posição');
  });

  test('um identificador que não é texto não vazio → rejeita antes de criar o lugar (nada se pede)', async () => {
    const { google, registo } = googleFalso();
    for (const id of [undefined, null, '', '   ', 7, { id: 'ChIJa' }]) {
      await expect(posicaoDoLugar(google, id)).rejects.toThrow('lugar sem identificador');
    }
    expect(registo.camposPedidos).toEqual([]);
  });

  test('sem a biblioteca places → rejeita (não rebenta fora da promessa)', async () => {
    const { google } = googleFalso();
    delete google.maps.places;
    const promessa = posicaoDoLugar(google, 'ChIJa');
    await expect(promessa).rejects.toThrow();
  });
});

describe('lugarDaPesquisa (a morada escolhida na pesquisa: location, formattedAddress, addressComponents)', () => {
  const previsaoDe = (google, id) => ({ placeId: id, toPlace: () => new google.maps.places.Place({ id }) });

  test('pede exatamente os três campos e devolve {id, lat, lng, morada}', async () => {
    const { google, registo } = googleFalso();
    registo.lugares.EiJa = {
      lat: 38.70921, lng: -9.13712, formattedAddress: ROTULO_AUGUSTA, addressComponents: COMPONENTES_AUGUSTA, ...CANARIOS,
    };
    const lugar = await lugarDaPesquisa(google, previsaoDe(google, 'EiJa'));
    expect(lugar).toStrictEqual({ id: 'EiJa', lat: 38.70921, lng: -9.13712, morada: MORADA_AUGUSTA });
    expect(Object.keys(lugar)).toEqual(['id', 'lat', 'lng', 'morada']);
    expect(registo.camposPedidos).toEqual([{ id: 'EiJa', fields: ['location', 'formattedAddress', 'addressComponents'] }]);
    expect(semCanarios(lugar)).toBe(true);
  });

  test('a falha da Google, um lugar sem posição ou uma previsão estragada → rejeita', async () => {
    const { google, registo } = googleFalso();
    await expect(lugarDaPesquisa(google, previsaoDe(google, 'EiJnada'))).rejects.toThrow('NOT_FOUND');
    registo.lugares.EiJsem = { formattedAddress: ROTULO_AUGUSTA };
    await expect(lugarDaPesquisa(google, previsaoDe(google, 'EiJsem'))).rejects.toThrow('lugar sem posição');
    await expect(lugarDaPesquisa(google, undefined)).rejects.toThrow();
    await expect(lugarDaPesquisa(google, { placeId: 'EiJa' })).rejects.toThrow();
  });
});

// --- criarPesquisaLugar -----------------------------------------------------------------------------

describe.each([
  ['o documento do jsdom', () => document],
  ['o documentoFalso', () => documentoFalso()],
])('criarPesquisaLugar, com %s', (_nome, fazerDocumento) => {
  function montar({ obterLimites = () => null } = {}) {
    const documento = fazerDocumento();
    const { google, registo } = googleFalso({ documento });
    registo.lugares.EiJa = {
      lat: 38.70921, lng: -9.13712, formattedAddress: ROTULO_AUGUSTA, addressComponents: COMPONENTES_AUGUSTA, ...CANARIOS,
    };
    registo.lugares.EiJb = { lat: 41.1496, lng: -8.6109, formattedAddress: 'Avenida dos Aliados, Porto', addressComponents: [] };
    const aoEscolher = jest.fn();
    const aoFalhar = jest.fn();
    const pesquisa = criarPesquisaLugar({ google, documento, aoEscolher, aoFalhar, obterLimites });
    return { documento, google, registo, aoEscolher, aoFalhar, pesquisa };
  }

  test('o elemento é o da Google, só com a região pt', () => {
    const { registo, pesquisa } = montar();
    expect(registo.pesquisas).toHaveLength(1);
    expect(pesquisa.elemento).toBe(registo.pesquisas[0]);
    expect(pesquisa.elemento.opcoes).toEqual({ includedRegionCodes: ['pt'] });
    expect(pesquisa.elemento.includedRegionCodes).toEqual(['pt']);
    expect(Object.keys(pesquisa)).toEqual(['elemento', 'destruir']);
  });

  test('ao focar, o enviesamento passa a ser os limites do mapa nesse momento', () => {
    let limites = new LatLngBoundsFalsos();
    limites.extend({ lat: 38.7, lng: -9.2 });
    limites.extend({ lat: 38.8, lng: -9.1 });
    const obterLimites = jest.fn(() => limites);
    const { pesquisa } = montar({ obterLimites });
    expect(obterLimites).not.toHaveBeenCalled();
    pesquisa.elemento.dispatchEvent(new Event('focus'));
    expect(pesquisa.elemento.locationBias).toBe(limites);
    const primeiros = limites;
    limites = new LatLngBoundsFalsos();
    limites.extend({ lat: 41.1, lng: -8.7 });
    pesquisa.elemento.dispatchEvent(new Event('focus'));
    expect(pesquisa.elemento.locationBias).toBe(limites);
    expect(pesquisa.elemento.locationBias).not.toBe(primeiros);
    expect(obterLimites).toHaveBeenCalledTimes(2);
  });

  test('ao focar sem mapa (limites null), sem enviesamento', () => {
    const { pesquisa } = montar({ obterLimites: () => null });
    pesquisa.elemento.locationBias = 'antigo';
    pesquisa.elemento.dispatchEvent(new Event('focus'));
    expect(pesquisa.elemento.locationBias).toBeUndefined();
  });

  test('escolher uma sugestão → aoEscolher({id, lat, lng, morada}), com só os três campos pedidos', async () => {
    const { registo, aoEscolher, aoFalhar, pesquisa } = montar();
    pesquisa.elemento.escolher('EiJa');
    await esperar();
    expect(aoEscolher).toHaveBeenCalledTimes(1);
    expect(aoEscolher.mock.calls[0]).toHaveLength(1);
    expect(aoEscolher.mock.calls[0][0]).toStrictEqual({ id: 'EiJa', lat: 38.70921, lng: -9.13712, morada: MORADA_AUGUSTA });
    expect(aoFalhar).not.toHaveBeenCalled();
    expect(registo.camposPedidos).toEqual([{ id: 'EiJa', fields: ['location', 'formattedAddress', 'addressComponents'] }]);
    expect(semCanarios(aoEscolher.mock.calls)).toBe(true);
    expect(registo.infoWindowsNossas).toBe(0);
  });

  test('uma escolha enquanto outra carrega: só a última conta (a primeira, tardia, é ignorada)', async () => {
    const { google, aoEscolher, aoFalhar, pesquisa } = montar();
    const soltarA = atrasar(google, 'EiJa');
    pesquisa.elemento.escolher('EiJa');
    pesquisa.elemento.escolher('EiJb');
    await esperar();
    expect(aoEscolher).toHaveBeenCalledTimes(1);
    expect(aoEscolher.mock.calls[0][0].id).toBe('EiJb');
    soltarA();
    await esperar();
    expect(aoEscolher).toHaveBeenCalledTimes(1);
    expect(aoFalhar).not.toHaveBeenCalled();
  });

  test('uma escolha anterior que falha tarde não mostra erro sobre a última', async () => {
    const { google, registo, aoEscolher, aoFalhar, pesquisa } = montar();
    registo.lugares.EiJa.falha = true;
    const soltarA = atrasar(google, 'EiJa');
    pesquisa.elemento.escolher('EiJa');
    pesquisa.elemento.escolher('EiJb');
    await esperar();
    soltarA();
    await esperar();
    expect(aoEscolher).toHaveBeenCalledTimes(1);
    expect(aoFalhar).not.toHaveBeenCalled();
  });

  test('o pedido dos campos falha → aoFalhar() e nada mais', async () => {
    const { aoEscolher, aoFalhar, pesquisa } = montar();
    pesquisa.elemento.escolher('EiJnada');
    await esperar();
    expect(aoFalhar).toHaveBeenCalledTimes(1);
    expect(aoFalhar.mock.calls[0]).toEqual([]);
    expect(aoEscolher).not.toHaveBeenCalled();
  });

  test('um lugar sem posição → aoFalhar()', async () => {
    const { registo, aoEscolher, aoFalhar, pesquisa } = montar();
    registo.lugares.EiJsem = { formattedAddress: ROTULO_AUGUSTA };
    pesquisa.elemento.escolher('EiJsem');
    await esperar();
    expect(aoFalhar).toHaveBeenCalledTimes(1);
    expect(aoEscolher).not.toHaveBeenCalled();
  });

  test('gmp-error → aoFalhar()', () => {
    const { aoEscolher, aoFalhar, pesquisa } = montar();
    pesquisa.elemento.falhar();
    expect(aoFalhar).toHaveBeenCalledTimes(1);
    expect(aoEscolher).not.toHaveBeenCalled();
  });

  test('depois de destruir, os eventos são ignorados, uma escolha a meio também, e o elemento sai do contentor', async () => {
    const { documento, google, registo, aoEscolher, aoFalhar, pesquisa } = montar({ obterLimites: () => 'limites' });
    const contentor = documento.createElement('div');
    contentor.appendChild(pesquisa.elemento);
    const soltarA = atrasar(google, 'EiJa');
    pesquisa.elemento.escolher('EiJa');
    pesquisa.destruir();
    expect(pesquisa.elemento.parentNode).toBeNull();
    expect(contentor.childNodes).toHaveLength(0);
    soltarA();
    pesquisa.elemento.escolher('EiJb');
    pesquisa.elemento.falhar();
    pesquisa.elemento.dispatchEvent(new Event('focus'));
    await esperar();
    expect(aoEscolher).not.toHaveBeenCalled();
    expect(aoFalhar).not.toHaveBeenCalled();
    expect(pesquisa.elemento.locationBias).toBeNull();
    // Só a escolha feita antes de destruir chegou a pedir os campos.
    expect(registo.camposPedidos.map((pedido) => pedido.id)).toEqual(['EiJa']);
    expect(() => pesquisa.destruir()).not.toThrow();
  });
});

test('criarPesquisaLugar sem a biblioteca places (ou sem Google) → elemento null e destruir inofensivo', () => {
  const semPlaces = googleFalso();
  delete semPlaces.google.maps.places;
  for (const google of [semPlaces.google, { maps: {} }, null, undefined]) {
    const pesquisa = criarPesquisaLugar({ google, documento: document, aoEscolher: jest.fn(), aoFalhar: jest.fn() });
    expect(pesquisa.elemento).toBeNull();
    expect(() => pesquisa.destruir()).not.toThrow();
  }
});

test('criarPesquisaLugar sem obterLimites nem chamadas de volta não rebenta', async () => {
  const { google, registo } = googleFalso();
  registo.lugares.EiJa = { lat: 38.7, lng: -9.1, formattedAddress: 'X', addressComponents: [] };
  const pesquisa = criarPesquisaLugar({ google, documento: document });
  pesquisa.elemento.dispatchEvent(new Event('focus'));
  expect(pesquisa.elemento.locationBias).toBeUndefined();
  pesquisa.elemento.escolher('EiJa');
  pesquisa.elemento.escolher('EiJnada');
  pesquisa.elemento.falhar();
  await esperar();
  pesquisa.destruir();
});

// --- criarNegocioSelecionado ------------------------------------------------------------------------

describe('criarNegocioSelecionado (o painel ao lado do mapa: nenhum dado da Google)', () => {
  const CHAVES = ['placeId', 'reserva', 'estado', 'mensagem'];
  const FECHADO = { placeId: null, reserva: null, estado: 'fechado', mensagem: null };

  function montar() {
    const vistas = [];
    const aoMudarVista = jest.fn((vista) => vistas.push(vista));
    const negocio = criarNegocioSelecionado({ aoMudarVista });
    return { negocio, aoMudarVista, vistas };
  }

  const confere = (vista) => {
    expect(Object.keys(vista)).toEqual(CHAVES);
    expect(Object.isFrozen(vista)).toBe(true);
    if (vista.reserva !== null) {
      expect(Object.keys(vista.reserva)).toEqual(['lat', 'lng']);
      expect(Object.isFrozen(vista.reserva)).toBe(true);
    }
  };

  test('começa fechado, sem avisar ninguém', () => {
    const { negocio, aoMudarVista } = montar();
    expect(negocio.vista).toStrictEqual(FECHADO);
    confere(negocio.vista);
    expect(aoMudarVista).not.toHaveBeenCalled();
  });

  test('abrir(placeId, {reserva}) → aberto, com a reserva só {lat, lng}', () => {
    const { negocio, aoMudarVista, vistas } = montar();
    negocio.abrir('ChIJa', { reserva: { lat: 38.7, lng: -9.1, placeId: 'ChIJa', nome: 'CANÁRIO-NOME' } });
    expect(negocio.vista).toStrictEqual({ placeId: 'ChIJa', reserva: { lat: 38.7, lng: -9.1 }, estado: 'aberto', mensagem: null });
    expect(aoMudarVista).toHaveBeenCalledTimes(1);
    expect(vistas[0]).toBe(negocio.vista);
    confere(negocio.vista);
    expect(semCanarios(negocio.vista)).toBe(true);
  });

  test('a reserva aceita um LatLng; sem reserva válida fica null', () => {
    const { negocio } = montar();
    negocio.abrir('ChIJa', { reserva: new LatLngFalso(38.7, -9.1) });
    expect(negocio.vista.reserva).toStrictEqual({ lat: 38.7, lng: -9.1 });
    for (const opcoes of [undefined, null, {}, { reserva: null }, { reserva: { lat: Number.NaN, lng: 1 } }, { reserva: [38.7, -9.1] }]) {
      negocio.abrir('ChIJb', opcoes);
      expect(negocio.vista).toStrictEqual({ placeId: 'ChIJb', reserva: null, estado: 'aberto', mensagem: null });
      confere(negocio.vista);
    }
  });

  test('abrir outro negócio substitui o anterior (vista nova)', () => {
    const { negocio, vistas } = montar();
    negocio.abrir('ChIJa', { reserva: { lat: 38.7, lng: -9.1 } });
    negocio.abrir('ChIJb');
    expect(negocio.vista).toStrictEqual({ placeId: 'ChIJb', reserva: null, estado: 'aberto', mensagem: null });
    expect(vistas).toHaveLength(2);
    expect(vistas[1]).not.toBe(vistas[0]);
    expect(vistas[0].placeId).toBe('ChIJa');
  });

  test('um identificador que não é texto não vazio é ignorado', () => {
    const { negocio, aoMudarVista } = montar();
    for (const id of [undefined, null, '', '   ', 7, { id: 'ChIJa' }]) negocio.abrir(id, { reserva: { lat: 38.7, lng: -9.1 } });
    expect(negocio.vista).toStrictEqual(FECHADO);
    expect(aoMudarVista).not.toHaveBeenCalled();
    negocio.abrir('ChIJa');
    negocio.abrir('');
    expect(negocio.vista.placeId).toBe('ChIJa');
  });

  test('aPosicionar() → a_posicionar com "A posicionar o pino…"; falhou() → erro com a mensagem do lugar indisponível', () => {
    const { negocio, vistas } = montar();
    negocio.abrir('ChIJa', { reserva: { lat: 38.7, lng: -9.1 } });
    negocio.aPosicionar();
    expect(negocio.vista).toStrictEqual({
      placeId: 'ChIJa', reserva: { lat: 38.7, lng: -9.1 }, estado: 'a_posicionar', mensagem: TEXTO_A_POSICIONAR,
    });
    negocio.falhou();
    expect(negocio.vista).toStrictEqual({
      placeId: 'ChIJa', reserva: { lat: 38.7, lng: -9.1 }, estado: 'erro', mensagem: TEXTO_LUGAR_INDISPONIVEL,
    });
    negocio.falhou('Sem rede.');
    expect(negocio.vista.mensagem).toBe('Sem rede.');
    // Tentar outra vez depois do erro.
    negocio.aPosicionar();
    expect(negocio.vista.estado).toBe('a_posicionar');
    expect(vistas).toHaveLength(5);
    vistas.forEach(confere);
  });

  test('fechar() → fechado, sem placeId nem reserva; fechar o que já está fechado não avisa', () => {
    const { negocio, aoMudarVista } = montar();
    negocio.abrir('ChIJa', { reserva: { lat: 38.7, lng: -9.1 } });
    negocio.aPosicionar();
    negocio.fechar();
    expect(negocio.vista).toStrictEqual(FECHADO);
    confere(negocio.vista);
    expect(aoMudarVista).toHaveBeenCalledTimes(3);
    negocio.fechar();
    expect(aoMudarVista).toHaveBeenCalledTimes(3);
  });

  test('fechado, aPosicionar() e falhou() não fazem nada', () => {
    const { negocio, aoMudarVista } = montar();
    negocio.aPosicionar();
    negocio.falhou();
    expect(negocio.vista).toStrictEqual(FECHADO);
    expect(aoMudarVista).not.toHaveBeenCalled();
  });

  test('depois de destruir() nada muda nem avisa', () => {
    const { negocio, aoMudarVista } = montar();
    negocio.abrir('ChIJa');
    negocio.destruir();
    const antes = negocio.vista;
    negocio.abrir('ChIJb');
    negocio.aPosicionar();
    negocio.falhou();
    negocio.fechar();
    negocio.destruir();
    expect(negocio.vista).toBe(antes);
    expect(aoMudarVista).toHaveBeenCalledTimes(1);
  });

  test('sem aoMudarVista também funciona', () => {
    const negocio = criarNegocioSelecionado();
    negocio.abrir('ChIJa');
    negocio.aPosicionar();
    expect(negocio.vista.estado).toBe('a_posicionar');
  });
});

// --- Os textos --------------------------------------------------------------------------------------

test('os textos são estes, cada um numa só linha do lugarGoogle.js', () => {
  const textos = {
    ROTULO_NEGOCIO: [ROTULO_NEGOCIO, 'Negócio selecionado'],
    TEXTO_NEGOCIO_SELECIONADO: [TEXTO_NEGOCIO_SELECIONADO, 'Negócio selecionado no mapa.'],
    TEXTO_ADICIONAR_COMO_LOJA: [TEXTO_ADICIONAR_COMO_LOJA, 'Adicionar como loja'],
    TEXTO_USAR_ESTE_NEGOCIO: [TEXTO_USAR_ESTE_NEGOCIO, 'Pôr o pino neste negócio'],
    TEXTO_FECHAR_NEGOCIO: [TEXTO_FECHAR_NEGOCIO, 'Fechar'],
    TEXTO_A_POSICIONAR: [TEXTO_A_POSICIONAR, 'A posicionar o pino…'],
    TEXTO_LUGAR_INDISPONIVEL: [
      TEXTO_LUGAR_INDISPONIVEL, 'Não foi possível obter a posição deste lugar — toque no mapa no sítio da loja.',
    ],
    TEXTO_ESCREVA_O_NOME: [
      TEXTO_ESCREVA_O_NOME,
      'Escreva o nome da loja como quer que apareça no mapa — para o ler, toque no ícone do negócio no mapa: '
        + 'abre o balão da Google (nada se copia).',
    ],
    TEXTO_PESQUISAR_LUGAR: [TEXTO_PESQUISAR_LUGAR, 'Pesquisar morada ou lugar (Google)'],
  };
  const fonte = fs.readFileSync(path.join(__dirname, 'lugarGoogle.js'), 'utf8');
  for (const [nome, [valor, esperado]] of Object.entries(textos)) {
    expect(valor).toBe(esperado);
    const linhas = fonte.split('\n').filter((linha) => linha === `export const ${nome} = '${esperado}';`);
    expect(linhas).toHaveLength(1);
  }
});
