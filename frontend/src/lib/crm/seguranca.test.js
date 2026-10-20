/**
 * VARRIMENTO DE SEGURANÇA DO CRM — nenhum dado entra no DOM como HTML, e o Google Maps só se usa onde e
 * como o plano diz.
 *
 * Regra 9 do §0 do plano do mapa Google (`docs/superpowers/plans/2026-10-14-crm-mapa-google.md`, G8),
 * que adapta a regra 9 da F2 (dossiê §0). O React escapa o texto por omissão; o perigo são as vias que
 * tratam um texto como HTML e as peças da Google que trazem dados de negócio ou mudam o que se paga:
 *   - em todo o lado: `dangerouslySetInnerHTML`, `innerHTML`, `outerHTML`, `insertAdjacentHTML` e
 *     `document.write`, nem em comentários (o `dom.js` e o `mapa.js` falam de "HTML" sem os nomear);
 *   - nunca um balão nosso: `InfoWindow` e `setContent` (o balão que abre ao tocar num negócio é o da
 *     própria Google, que o código nunca cria nem trava);
 *   - nunca `PlacesService`, `Geocoder`, o `places.Autocomplete` legado nem `AutocompleteSuggestion`; e
 *     nunca os nomes dos dados de negócio da Google (canários: telefones, site, morada curta, horários,
 *     estado, classificação, opiniões, fotos, resumo, preço, ligação da Google e o nome), também em
 *     comentários — nos comentários escreve-se "nome do negócio", "morada da Google". O nome
 *     (`displayName`) só conta como leitura ou texto: a atribuição do React
 *     `OpcaoConta.displayName = 'OpcaoConta';` (`pages/crm/DefinicoesMembros.js`) passa;
 *   - o lugar da Google só no `lib/crm/lugarGoogle.js` (`fetchFields`, `formattedAddress`,
 *     `addressComponents`, `toPlace`, `Place`, `PlaceAutocompleteElement`); lá, cada `fetchFields` é
 *     exatamente `fetchFields({ fields: CAMPOS_POSICAO })` ou `fetchFields({ fields: CAMPOS_MORADA_GOOGLE })`
 *     (nem em comentários com outra forma), e cada lista `CAMPOS_… = Object.freeze([...])` ou
 *     `fields: [...]` só tem `id`, `location`, `formattedAddress` e `addressComponents` (outro campo
 *     traz dados do negócio ou muda o SKU cobrado);
 *   - `google.maps` e `importLibrary` só em `lib/crm/{carregadorGoogle,mapa,seletor,lugarGoogle}.js` (um
 *     componente só passa o `window.google`); o `__crmMapa` (o gancho da verificação no browser, regra 16)
 *     só no `mapa.js`; o `content` de um marcador avançado só no `mapa.js` e no `seletor.js`, e lá é
 *     sempre um nó do `el(...)`;
 *   - um `tel:` só se monta no `hrefTelefone` do `dom.js` (só dígitos e `+`).
 * As regras da biblioteca do mapa antigo (etiquetas, ícones com `html`, `attribution:` e o prefixo)
 * saíram com ela: a atribuição do mapa é a da própria Google, que o CRM não escreve.
 *
 * Varre os `.js` e `.jsx` de `lib/crm`, `components/crm` e `pages/crm`, mais o
 * `components/layouts/CrmLayout.js` e o `hooks/useEstadoCrm.js`. Ficam de fora os testes (`*.test.js`) e a
 * pasta `testes/` (o `googleFalso.js` imita a Google, por isso nomeia o que aqui se recusa).
 *
 * O `procurarViolacoes` é provado primeiro com amostras (cada regra apanha a sua e o código seguro passa),
 * e a lista dos ficheiros também: um varrimento que não lê nada, ou que não sabe ler, passava sempre.
 */
/* eslint-disable no-template-curly-in-string -- as amostras são código-fonte com `${…}`, em texto de propósito */
import fs from 'fs';
import path from 'path';

// frontend/src/lib/crm → frontend/src
const SRC = path.join(__dirname, '..', '..');
const PASTAS = ['lib/crm', 'components/crm', 'pages/crm'];
const FICHEIROS_SOLTOS = ['components/layouts/CrmLayout.js', 'hooks/useEstadoCrm.js'];

const CARREGADOR = 'lib/crm/carregadorGoogle.js';
const MAPA = 'lib/crm/mapa.js';
const SELETOR = 'lib/crm/seletor.js';
const LUGAR = 'lib/crm/lugarGoogle.js';
const DOM = 'lib/crm/dom.js';
// Os únicos ficheiros que falam com o `google.maps`.
const MODULOS_GOOGLE = [CARREGADOR, MAPA, SELETOR, LUGAR];
const COMPONENTE = 'components/crm/Exemplo.js';

// --- O detetor ----------------------------------------------------------------------------------

const sempre = () => true;
const so = (...ficheiros) => (ficheiro) => ficheiros.includes(ficheiro);
const foraDe = (...ficheiros) => (ficheiro) => !ficheiros.includes(ficheiro);
const palavra = (nome) => new RegExp(`\\b${nome}\\b`, 'g');

// Os únicos campos de um lugar da Google que o CRM pede (o `CAMPOS_PERMITIDOS` do `lugarGoogle.js`).
const CAMPOS_PERMITIDOS = ['id', 'location', 'formattedAddress', 'addressComponents'];
// Os dados de negócio que a Google tem e o CRM nunca lê nem nomeia (o nome tem regra própria, em baixo).
const CANARIOS = [
  'nationalPhoneNumber',
  'internationalPhoneNumber',
  'websiteUri',
  'shortFormattedAddress',
  'regularOpeningHours',
  'currentOpeningHours',
  'businessStatus',
  'rating',
  'reviews',
  'photos',
  'editorialSummary',
  'priceLevel',
  'googleMapsURI',
];
// O que só o `lugarGoogle.js` pode nomear.
const SO_NO_LUGAR = ['fetchFields', 'formattedAddress', 'addressComponents', 'toPlace', 'Place', 'PlaceAutocompleteElement'];

// [regra, padrão, aplica(ficheiro)]: `ficheiro` é o caminho a partir de frontend/src (ex.: 'lib/crm/mapa.js').
const REGRAS = [
  ['dangerouslySetInnerHTML', /dangerouslySetInnerHTML/g, sempre],
  ['innerHTML', /\binnerHTML\b/g, sempre],
  ['outerHTML', /\bouterHTML\b/g, sempre],
  ['insertAdjacentHTML', /\binsertAdjacentHTML\b/g, sempre],
  // document.write e writeln, também num documento recebido por parâmetro (documento.write).
  ['document.write', /\.\s*write(?:ln)?\b/g, sempre],
  ['InfoWindow', /\bInfoWindow\b/g, sempre],
  ['setContent', /\bsetContent\b/g, sempre],
  ['PlacesService', /\bPlacesService\b/g, sempre],
  ['Geocoder', /\bGeocoder\b/g, sempre],
  // O legado, também tirado da biblioteca por desestruturação (`const { Autocomplete } = …`).
  ['places.Autocomplete', /\bAutocomplete\b/g, sempre],
  ['AutocompleteSuggestion', /\bAutocompleteSuggestion\b/g, sempre],
  // Só a leitura ou o texto: uma atribuição (`X.displayName = 'X';`) passa; uma comparação (`===`) não.
  ['canário displayName', /\bdisplayName\b(?!\s*=[^=])/g, sempre],
  ...CANARIOS.map((nome) => [`canário ${nome}`, palavra(nome), sempre]),
  ...SO_NO_LUGAR.map((nome) => [`${nome} fora do lugarGoogle.js`, palavra(nome), foraDe(LUGAR)]),
  [
    'fetchFields sem CAMPOS_POSICAO nem CAMPOS_MORADA_GOOGLE',
    /\bfetchFields\b(?!\s*\(\s*\{\s*fields\s*:\s*CAMPOS_(?:POSICAO|MORADA_GOOGLE)\s*,?\s*\}\s*\))/g,
    so(LUGAR),
  ],
  [
    'google.maps fora dos módulos do Google',
    /\bgoogle\s*(?:\?\.|\.)\s*maps\b|\bgoogle\s*(?:\?\.)?\s*\[\s*['"`]maps['"`]\s*\]/g,
    foraDe(...MODULOS_GOOGLE),
  ],
  ['importLibrary fora dos módulos do Google', /\bimportLibrary\b/g, foraDe(...MODULOS_GOOGLE)],
  ['__crmMapa fora do mapa.js', /__crmMapa/g, foraDe(MAPA)],
  // `content: …` (também entre aspas) e `x.content = …` (uma comparação, `===`, não conta).
  ['content fora do mapa.js e do seletor.js', /\bcontent['"]?\s*:|\.\s*content\s*=(?!=)/g, foraDe(MAPA, SELETOR)],
  // Os espaços ficam dentro do (?!…): fora, o \s* recuava um espaço e o ": el(" passava por perigoso.
  ['content sem el()', /\bcontent['"]?\s*:(?!\s*el\()|\.\s*content\s*=(?!=)(?!\s*el\()/g, so(MAPA, SELETOR)],
  // Um texto que começa por tel: ('tel:…', "tel:…" ou `tel:…${…}`); um `tel:` num comentário passa.
  ['tel: fora do dom.js', /['"]tel:|`tel:(?!`)/g, foraDe(DOM)],
];

// No lugarGoogle.js, as listas de campos: `CAMPOS_… = Object.freeze([` (ou sem o freeze) e `fields: [`.
const REGRA_CAMPOS = 'campos fora de id, location, formattedAddress e addressComponents';
const LISTA_DE_CAMPOS = /\b(?:CAMPOS_\w+\s*=\s*(?:Object\.freeze\(\s*)?|fields['"]?\s*:\s*)\[/g;

// Só textos ('…' ou "…") com um dos campos permitidos; um nome, um `...`, um comentário ou outra lista lá
// dentro já recusam (a lista lê-se até ao primeiro `]`).
function soCamposPermitidos(texto, depoisDoColchete) {
  const fim = texto.indexOf(']', depoisDoColchete);
  const conteudo = texto.slice(depoisDoColchete, fim === -1 ? texto.length : fim);
  return conteudo
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item !== '')
    .every((item) => {
      const m = /^(['"])([A-Za-z]+)\1$/.exec(item);
      return m !== null && CAMPOS_PERMITIDOS.includes(m[2]);
    });
}

const linhaDe = (texto, indice) => texto.slice(0, indice).split('\n').length;

// procurarViolacoes(texto, {ficheiro}) → [{regra, linha}], pela ordem do texto.
function procurarViolacoes(texto, { ficheiro = '' } = {}) {
  const achados = [];
  for (const [regra, padrao, aplica] of REGRAS) {
    if (!aplica(ficheiro)) continue;
    for (const m of texto.matchAll(padrao)) achados.push({ regra, indice: m.index });
  }
  if (ficheiro === LUGAR) {
    for (const m of texto.matchAll(LISTA_DE_CAMPOS)) {
      if (!soCamposPermitidos(texto, m.index + m[0].length)) achados.push({ regra: REGRA_CAMPOS, indice: m.index });
    }
  }
  return achados
    .sort((a, b) => a.indice - b.indice)
    .map(({ regra, indice }) => ({ regra, linha: linhaDe(texto, indice) }));
}

// --- Os ficheiros -------------------------------------------------------------------------------

// Os .js e .jsx, menos os testes e a pasta testes/ (caminho a partir de frontend/src, com '/').
const deveVarrer = (relativo) =>
  /\.jsx?$/.test(relativo) && !/\.test\.jsx?$/.test(relativo) && !relativo.split('/').includes('testes');

function listarFicheiros() {
  const lista = [];
  const visitar = (relativo) => {
    for (const entrada of fs.readdirSync(path.join(SRC, relativo), { withFileTypes: true })) {
      const filho = `${relativo}/${entrada.name}`;
      if (entrada.isDirectory()) visitar(filho);
      else if (deveVarrer(filho)) lista.push(filho);
    }
  };
  PASTAS.forEach(visitar);
  return [...lista, ...FICHEIROS_SOLTOS].sort();
}

const regras = (texto, ficheiro = COMPONENTE) => procurarViolacoes(texto, { ficheiro }).map((v) => v.regra);

// Um componente, uma página, um módulo do CRM sem Google e cada um dos módulos do Google.
const TODOS = [COMPONENTE, 'pages/crm/CrmMapa.js', 'lib/crm/ecraMapa.js', ...MODULOS_GOOGLE];

// --- O detetor, provado primeiro -----------------------------------------------------------------

describe('procurarViolacoes apanha cada via de HTML, em qualquer ficheiro', () => {
  test.each([
    ['<div dangerouslySetInnerHTML={{ __html: loja.nome }} />', 'dangerouslySetInnerHTML'],
    ['no.innerHTML = loja.nome;', 'innerHTML'],
    ['no.innerHTML += loja.nome;', 'innerHTML'],
    ["no['innerHTML'] = loja.nome;", 'innerHTML'],
    ['no.outerHTML = loja.nome;', 'outerHTML'],
    ["no.insertAdjacentHTML('beforeend', loja.nome);", 'insertAdjacentHTML'],
    ['document.write(loja.nome);', 'document.write'],
    ['documento.writeln(loja.nome);', 'document.write'],
  ])('%s → %s', (amostra, regra) => {
    // Também nos módulos do Google: estas não têm exceção nenhuma.
    for (const ficheiro of TODOS) expect(regras(amostra, ficheiro)).toContain(regra);
  });
});

describe('nunca um balão nosso nem as peças da Google que trazem dados de negócio', () => {
  test.each([
    ['const balao = new google.maps.InfoWindow({ content: no });', 'InfoWindow'],
    ['const balao = new InfoWindow();', 'InfoWindow'],
    ["const { InfoWindow } = await google.maps.importLibrary('maps');", 'InfoWindow'],
    ['balao.setContent(no);', 'setContent'],
    ['balao.setContent ( `<b>${loja.nome}</b>` );', 'setContent'],
    ['const servico = new google.maps.places.PlacesService(mapa);', 'PlacesService'],
    ['const geocoder = new google.maps.Geocoder();', 'Geocoder'],
    ['new Geocoder().geocode({ location });', 'Geocoder'],
    ['const campo = new google.maps.places.Autocomplete(entrada);', 'places.Autocomplete'],
    ["const { Autocomplete } = await importLibrary('places');", 'places.Autocomplete'],
    ['const lista = await AutocompleteSuggestion.fetchAutocompleteSuggestions(pedido);', 'AutocompleteSuggestion'],
  ])('%s → %s', (amostra, regra) => {
    for (const ficheiro of TODOS) expect(regras(amostra, ficheiro)).toContain(regra);
  });

  // Os nomes escritos por extenso só aqui (os testes não se varrem).
  test.each([
    'nationalPhoneNumber',
    'internationalPhoneNumber',
    'websiteUri',
    'shortFormattedAddress',
    'regularOpeningHours',
    'currentOpeningHours',
    'businessStatus',
    'rating',
    'reviews',
    'photos',
    'editorialSummary',
    'priceLevel',
    'googleMapsURI',
  ])('o canário %s é recusado em todo o lado, comentários incluídos', (nome) => {
    for (const amostra of [
      `const valor = lugar.${nome};`,
      `const valor = lugar['${nome}'];`,
      `const { ${nome} } = lugar;`,
      `const campos = ['location', '${nome}'];`,
      `// o ${nome} do negócio não se guarda`,
    ]) {
      for (const ficheiro of TODOS) expect(regras(amostra, ficheiro)).toContain(`canário ${nome}`);
    }
  });

  test.each([
    ['const nome = lugar.displayName;'],
    ["const nome = lugar['displayName'];"],
    ["const campo = 'displayName';"],
    ["await lugar.fetchFields({ fields: ['displayName'] });"],
    ['if (lugar.displayName === nome) {}'],
    ['if (lugar.displayName==nome) {}'],
    ['const { displayName } = lugar;'],
    ['// o displayName do negócio não se lê'],
  ])('o nome do negócio (displayName) é recusado como leitura ou texto: %s', (amostra) => {
    for (const ficheiro of TODOS) expect(regras(amostra, ficheiro)).toContain('canário displayName');
  });

  test.each([
    ["OpcaoConta.displayName = 'OpcaoConta';"],
    ["Componente.displayName='Componente';"],
  ])('a atribuição do React passa (pages/crm/DefinicoesMembros.js): %s', (amostra) => {
    expect(regras(amostra, 'pages/crm/DefinicoesMembros.js')).toEqual([]);
  });
});

describe('o lugar da Google só no lugarGoogle.js', () => {
  test.each([
    ['await lugar.fetchFields({ fields: CAMPOS_POSICAO });', 'fetchFields'],
    ['const rotulo = lugar.formattedAddress;', 'formattedAddress'],
    ['for (const parte of lugar.addressComponents) {}', 'addressComponents'],
    ['const lugar = evento.placePrediction.toPlace();', 'toPlace'],
    ['const lugar = new google.maps.places.Place({ id: placeId });', 'Place'],
    ["const { Place } = await importLibrary('places');", 'Place'],
    ['const campo = new google.maps.places.PlaceAutocompleteElement({});', 'PlaceAutocompleteElement'],
  ])('%s → %s fora do lugarGoogle.js', (amostra, nome) => {
    for (const ficheiro of TODOS.filter((f) => f !== LUGAR)) {
      expect(regras(amostra, ficheiro)).toContain(`${nome} fora do lugarGoogle.js`);
    }
    expect(regras(amostra, LUGAR)).not.toContain(`${nome} fora do lugarGoogle.js`);
  });

  test.each([
    ["await lugar.fetchFields({ fields: ['location'] });"],
    ['await lugar.fetchFields({ fields: CAMPOS });'],
    ['await lugar.fetchFields({ fields: CAMPOS_PERMITIDOS });'],
    ["await lugar.fetchFields({ fields: [...CAMPOS_POSICAO, 'id'] });"],
    ['await lugar.fetchFields({ fields: CAMPOS_POSICAO, outro: 1 });'],
    ['await lugar.fetchFields(pedido);'],
    ["await lugar['fetchFields']({ fields: CAMPOS_POSICAO });"],
    ['const pedir = lugar.fetchFields.bind(lugar);'],
    ['// o fetchFields pede só a posição'],
  ])('no lugarGoogle.js, cada fetchFields é fetchFields({ fields: CAMPOS_POSICAO | CAMPOS_MORADA_GOOGLE }): %s', (amostra) => {
    expect(regras(amostra, LUGAR)).toContain('fetchFields sem CAMPOS_POSICAO nem CAMPOS_MORADA_GOOGLE');
  });

  test.each([
    ["export const CAMPOS_POSICAO = Object.freeze(['location', 'types']);"],
    ['export const CAMPOS_POSICAO = Object.freeze([\n  "location",\n  "viewport",\n]);'],
    ["const CAMPOS_EXTRA = ['location', 'plusCode'];"],
    ['const CAMPOS_EXTRA = Object.freeze([...CAMPOS_POSICAO]);'],
    ['const CAMPOS_EXTRA = Object.freeze([nome]);'],
    ["const CAMPOS_EXTRA = Object.freeze([location, 'id']);"],
    ["const CAMPOS_EXTRA = Object.freeze(['location' /* e mais */]);"],
    ["const CAMPOS_EXTRA = Object.freeze([`location`]);"],
    ["const pedido = { fields: ['id', 'utcOffsetMinutes'] };"],
    ["const pedido = { 'fields': ['location', ['id']] };"],
  ])('no lugarGoogle.js, as listas de campos só têm id, location, formattedAddress e addressComponents: %s', (amostra) => {
    expect(regras(amostra, LUGAR)).toContain('campos fora de id, location, formattedAddress e addressComponents');
  });

  test('o nome do negócio numa lista de campos é recusado pelas três regras', () => {
    const recusadas = regras("await lugar.fetchFields({ fields: ['location', 'displayName'] });", LUGAR);
    expect(recusadas).toContain('fetchFields sem CAMPOS_POSICAO nem CAMPOS_MORADA_GOOGLE');
    expect(recusadas).toContain('campos fora de id, location, formattedAddress e addressComponents');
    expect(recusadas).toContain('canário displayName');
    expect(regras("export const CAMPOS_POSICAO = Object.freeze(['location', 'displayName']);", LUGAR)).toEqual([
      'campos fora de id, location, formattedAddress e addressComponents',
      'canário displayName',
    ]);
  });

  test('fora do lugarGoogle.js, uma lista de campos não é da Google (a do formulário passa)', () => {
    expect(regras("export const CAMPOS_MORADA = Object.freeze(['morada', 'codigo_postal']);", 'lib/crm/morada.js')).toEqual([]);
    expect(regras("const opcoes = { fields: ['nome', 'telefone'] };", COMPONENTE)).toEqual([]);
  });
});

describe('google.maps, importLibrary, __crmMapa e content só onde o plano diz', () => {
  test.each([
    ['const mapa = new google.maps.Map(elemento, opcoes);', 'google.maps fora dos módulos do Google'],
    ["window.google.maps.event.trigger(mapa, 'resize');", 'google.maps fora dos módulos do Google'],
    ['const ha = Boolean(window.google?.maps);', 'google.maps fora dos módulos do Google'],
    ["const maps = window.google['maps'];", 'google.maps fora dos módulos do Google'],
    ['// o google . maps carrega-se no carregador', 'google.maps fora dos módulos do Google'],
    ["await janela.google.maps.importLibrary('places');", 'importLibrary fora dos módulos do Google'],
    ["const { importLibrary } = maps;", 'importLibrary fora dos módulos do Google'],
  ])('%s → %s', (amostra, regra) => {
    for (const ficheiro of [COMPONENTE, 'pages/crm/CrmMapa.js', 'lib/crm/ecraMapa.js', 'hooks/useEstadoCrm.js']) {
      expect(regras(amostra, ficheiro)).toContain(regra);
    }
    for (const ficheiro of MODULOS_GOOGLE) expect(regras(amostra, ficheiro)).not.toContain(regra);
  });

  test('o __crmMapa só no mapa.js', () => {
    const amostra = 'const mapa = elemento.__crmMapa;';
    for (const ficheiro of TODOS.filter((f) => f !== MAPA)) {
      expect(regras(amostra, ficheiro)).toContain('__crmMapa fora do mapa.js');
    }
    expect(regras(amostra, MAPA)).toEqual([]);
  });

  test.each([
    ['new google.maps.marker.AdvancedMarkerElement({ map, content: no });'],
    ["const pino = new AdvancedMarkerElement({ content: el(documento, 'div', {}) });"],
    ["const opcoes = { 'content': texto };"],
    ['marcador.content = loja.nome;'],
  ])('o content de um marcador só no mapa.js e no seletor.js: %s', (amostra) => {
    for (const ficheiro of [COMPONENTE, 'pages/crm/CrmMapa.js', 'lib/crm/ecraMapa.js', CARREGADOR, LUGAR]) {
      expect(regras(amostra, ficheiro)).toContain('content fora do mapa.js e do seletor.js');
    }
  });

  test.each([
    ['new AdvancedMarkerElement({ map, content: loja.nome });'],
    ['new AdvancedMarkerElement({ content: `<b>${loja.nome}</b>` });'],
    ['new AdvancedMarkerElement({ content: pino });'],
    ["new AdvancedMarkerElement({ content: documento.createElement('div') });"],
    ["const opcoes = { 'content': texto };"],
    ['marcador.content = loja.nome;'],
  ])('no mapa.js e no seletor.js, o content é sempre um nó do el(): %s', (amostra) => {
    for (const ficheiro of [MAPA, SELETOR]) expect(regras(amostra, ficheiro)).toContain('content sem el()');
  });

  test.each([
    ['<a href={`tel:${loja.telefone}`}>Ligar</a>'],
    ["const href = 'tel:' + loja.telefone;"],
    ['<a href="tel:+351912345678">Ligar</a>'],
  ])('um tel: só se monta no hrefTelefone do dom.js: %s', (amostra) => {
    expect(regras(amostra, 'components/crm/CartaoLoja.js')).toContain('tel: fora do dom.js');
  });
});

describe('procurarViolacoes deixa passar o código seguro', () => {
  test('fora dos módulos do Google', () => {
    const seguro = [
      'no.textContent = loja.nome;',
      "const etiqueta = el(documento, 'span', { texto: loja.nome });",
      '<span>{loja.nome}</span>',
      "const atribuicao = 'geoapify';",
      'const { partes } = ATRIBUICOES.geoapify;',
      '<a href={hrefTelefone(loja.telefone)}>Ligar</a>',
      '// o "Ligar" leva o `tel:` do hrefTelefone',
      'navigator.clipboard.writeText(texto);',
      "const { importar } = prepararGoogleMaps({ janela: window, documento: document, chave, versao: 'weekly' });",
      "await importar('maps');",
      "await importar('marker');",
      'const criado = criarMapa({ google: window.google, documento: document, elemento, configuracao });',
      "OpcaoConta.displayName = 'OpcaoConta';",
      '// o nome do negócio e a morada da Google nunca se guardam: só o google_place_id e o pino',
      'const dados = { google_place_id: negocio.placeId, origem_coords: "geocoder" };',
      '<input autoComplete="off" />',
      '<td className="md:before:content-none" />',
      "const campos = { fields: ['nome'] };",
      'if (marcador.content === no) {}',
    ].join('\n');
    for (const ficheiro of [COMPONENTE, 'pages/crm/CrmMapa.js', 'lib/crm/ecraMapa.js', 'hooks/useEstadoCrm.js']) {
      expect(procurarViolacoes(seguro, { ficheiro })).toEqual([]);
    }
  });

  // Os caminhos por extenso: as exceções são destes quatro ficheiros (regra 9), não de uma constante.
  test('nos módulos do Google, as exceções certas', () => {
    const doMapa = [
      'const mapa = new google.maps.Map(elemento, { mapId, clickableIcons: negociosClicaveis });',
      'elemento.__crmMapa = mapa;',
      'const marcador = new google.maps.marker.AdvancedMarkerElement({',
      "  content: el(documento, 'div', {",
      '    classe: classePino(loja.fase),',
      '  }),',
      '  collisionBehavior: google.maps.CollisionBehavior.REQUIRED,',
      '});',
      "google.maps.event.addListenerOnce(mapa, 'idle', () => {});",
      'if (elemento.__crmMapa === mapa) delete elemento.__crmMapa;',
    ].join('\n');
    expect(procurarViolacoes(doMapa, { ficheiro: 'lib/crm/mapa.js' })).toEqual([]);

    const doSeletor = [
      "const pino = new google.maps.marker.AdvancedMarkerElement({ map, content: el(documento, 'div', { classe: 'pino-seletor' }), gmpDraggable: true });",
      "pino.content = el(documento, 'div', { classe: 'pino-seletor' });",
      'const circulo = new google.maps.Circle({ ...ESTILO_CIRCULO, center, radius: precisao, map });',
    ].join('\n');
    expect(procurarViolacoes(doSeletor, { ficheiro: 'lib/crm/seletor.js' })).toEqual([]);

    const doCarregador = [
      "const importar = (nome) => janela.google.maps.importLibrary(nome);",
      "if (typeof janela.google?.maps?.importLibrary === 'function') return { importar };",
      'maps.importLibrary = arranque;',
    ].join('\n');
    expect(procurarViolacoes(doCarregador, { ficheiro: 'lib/crm/carregadorGoogle.js' })).toEqual([]);

    const doLugar = [
      "export const CAMPOS_POSICAO = Object.freeze(['location']);",
      "export const CAMPOS_MORADA_GOOGLE = Object.freeze(['location', 'formattedAddress', 'addressComponents']);",
      'export const CAMPOS_PERMITIDOS = Object.freeze([',
      "  'id',",
      '  "location",',
      "  'formattedAddress',",
      "  'addressComponents',",
      ']);',
      'const lugar = new google.maps.places.Place({ id: placeId });',
      'await lugar.fetchFields({ fields: CAMPOS_POSICAO });',
      'const escolhido = evento.placePrediction.toPlace();',
      'await escolhido.fetchFields({fields:CAMPOS_MORADA_GOOGLE});',
      'await escolhido.fetchFields({\n  fields: CAMPOS_MORADA_GOOGLE,\n});',
      'const rotulo = escolhido.formattedAddress;',
      'const partes = escolhido.addressComponents;',
      "const campo = new google.maps.places.PlaceAutocompleteElement({ includedRegionCodes: ['pt'] });",
      "const { Place } = await google.maps.importLibrary('places');",
    ].join('\n');
    expect(procurarViolacoes(doLugar, { ficheiro: 'lib/crm/lugarGoogle.js' })).toEqual([]);
  });

  test('no dom.js, o tel: do hrefTelefone', () => {
    expect(procurarViolacoes('return `tel:${mais}${digitos}`;', { ficheiro: DOM })).toEqual([]);
  });
});

test('procurarViolacoes diz a regra e a linha de cada uma, pela ordem do texto', () => {
  const texto = 'const a = 1;\nno.innerHTML = loja.nome;\n\nconst b = new google.maps.InfoWindow({\n  content: x,\n});\n';
  expect(procurarViolacoes(texto, { ficheiro: COMPONENTE })).toEqual([
    { regra: 'innerHTML', linha: 2 },
    { regra: 'google.maps fora dos módulos do Google', linha: 4 },
    { regra: 'InfoWindow', linha: 4 },
    { regra: 'content fora do mapa.js e do seletor.js', linha: 5 },
  ]);
});

// --- Que ficheiros se varrem ---------------------------------------------------------------------

test.each([
  ['lib/crm/mapa.js', true],
  ['lib/crm/carregadorGoogle.js', true],
  ['components/crm/MapaLojas.js', true],
  ['pages/crm/CrmMapa.jsx', true],
  ['components/crm/sub/Pasta.jsx', true],
  ['lib/crm/mapa.test.js', false],
  ['pages/crm/CrmMapa.test.jsx', false],
  ['lib/crm/testes/googleFalso.js', false],
  ['components/crm/testes/x.jsx', false],
  ['components/crm/crm.css', false],
  ['lib/crm/notas.md', false],
])('deveVarrer(%s) → %s', (relativo, esperado) => {
  expect(deveVarrer(relativo)).toBe(esperado);
});

test('a lista dos ficheiros tem o código do CRM e deixa de fora os testes e os falsos', () => {
  const lista = listarFicheiros();
  for (const relativo of [
    'lib/crm/mapa.js',
    'lib/crm/carregadorGoogle.js',
    'lib/crm/lugarGoogle.js',
    'lib/crm/dom.js',
    'lib/crm/atribuicoes.js',
    'lib/crm/api.js',
    'lib/crm/ecraMapa.js',
    'lib/crm/seletor.js',
    'lib/crm/lojaNova.js',
    'lib/crm/formularioLoja.js',
    'lib/crm/dialogo.js',
    'lib/crm/ficha.js',
    'lib/crm/membros.js',
    'lib/crm/regioes.js',
    'lib/crm/fabrica.js',
    'components/crm/GuardaCrm.js',
    'components/crm/seccaoCrm.js',
    'components/crm/MapaLojas.js',
    'components/crm/NegocioSelecionado.js',
    'components/crm/FiltrosMapa.js',
    'components/crm/CartaoLoja.js',
    'components/crm/SeletorLocalizacao.js',
    'components/crm/PesquisaMorada.js',
    'components/crm/FormularioLoja.js',
    'components/crm/DialogoDuplicado.js',
    'pages/crm/CrmMapa.js',
    'pages/crm/CrmLojaNova.js',
    'pages/crm/CrmLoja.js',
    'pages/crm/CrmDefinicoes.js',
    'pages/crm/DefinicoesMembros.js',
    'pages/crm/DefinicoesRegioes.js',
    'pages/crm/DefinicoesFabrica.js',
    'pages/crm/rotasCrm.js',
    ...FICHEIROS_SOLTOS,
  ]) {
    expect(lista).toContain(relativo);
  }
  for (const relativo of [
    'lib/crm/seguranca.test.js',
    'lib/crm/dom.test.js',
    'lib/crm/mapa.test.js',
    'lib/crm/carregadorGoogle.test.js',
    'lib/crm/lugarGoogle.test.js',
    'lib/crm/atribuicoes.test.js',
    'lib/crm/css.test.js',
    'lib/crm/ecraMapa.test.js',
    'lib/crm/seletor.test.js',
    'lib/crm/lojaNova.test.js',
    'lib/crm/formularioLoja.test.js',
    'lib/crm/dialogo.test.js',
    'lib/crm/ficha.test.js',
    'lib/crm/membros.test.js',
    'lib/crm/regioes.test.js',
    'lib/crm/fabrica.test.js',
    'lib/crm/testes/domFalso.js',
    'lib/crm/testes/googleFalso.js',
  ]) {
    expect(lista).not.toContain(relativo);
  }
});

// --- O varrimento --------------------------------------------------------------------------------

test('nenhum ficheiro do CRM põe dados no DOM como HTML nem usa a Google fora do sítio', () => {
  // Falha, e não salta, se um dos ficheiros soltos desaparecer.
  for (const relativo of FICHEIROS_SOLTOS) {
    expect(fs.existsSync(path.join(SRC, relativo))).toBe(true);
  }
  const violacoes = [];
  for (const relativo of listarFicheiros()) {
    const texto = fs.readFileSync(path.join(SRC, relativo), 'utf8');
    for (const { regra, linha } of procurarViolacoes(texto, { ficheiro: relativo })) {
      violacoes.push(`${relativo}:${linha} ${regra}`);
    }
  }
  expect(violacoes).toEqual([]);
});

// As exceções são precisas: o código verdadeiro de cada módulo do Google, posto noutro ficheiro, seria
// recusado pelas regras de que só ele está isento.
test('o mapa.js verdadeiro só passa por ser o mapa.js', () => {
  const texto = fs.readFileSync(path.join(SRC, MAPA), 'utf8');
  expect(regras(texto, MAPA)).toEqual([]);
  const numComponente = regras(texto, COMPONENTE);
  expect(numComponente).toContain('google.maps fora dos módulos do Google');
  expect(numComponente).toContain('content fora do mapa.js e do seletor.js');
  expect(numComponente).toContain('__crmMapa fora do mapa.js');
  // No seletor.js, o google.maps e o content (sempre do el()) são permitidos; o gancho do browser não.
  expect([...new Set(regras(texto, SELETOR))]).toEqual(['__crmMapa fora do mapa.js']);
  // No lugarGoogle.js, o google.maps é permitido; o content dos marcadores e o gancho não.
  expect([...new Set(regras(texto, LUGAR))].sort()).toEqual([
    '__crmMapa fora do mapa.js',
    'content fora do mapa.js e do seletor.js',
  ]);
});

test('o carregadorGoogle.js verdadeiro só passa por ser um módulo do Google', () => {
  const texto = fs.readFileSync(path.join(SRC, CARREGADOR), 'utf8');
  for (const ficheiro of MODULOS_GOOGLE) expect(regras(texto, ficheiro)).toEqual([]);
  const numComponente = regras(texto, COMPONENTE);
  expect(numComponente).toContain('google.maps fora dos módulos do Google');
  expect(numComponente).toContain('importLibrary fora dos módulos do Google');
});

test('o lugarGoogle.js verdadeiro só passa por ser o lugarGoogle.js', () => {
  const texto = fs.readFileSync(path.join(SRC, 'lib/crm/lugarGoogle.js'), 'utf8');
  expect(regras(texto, 'lib/crm/lugarGoogle.js')).toEqual([]);
  // Num componente: o google.maps e todo o lugar da Google.
  const numComponente = new Set(regras(texto, COMPONENTE));
  expect(numComponente).toContain('google.maps fora dos módulos do Google');
  for (const nome of ['fetchFields', 'formattedAddress', 'addressComponents', 'toPlace', 'Place', 'PlaceAutocompleteElement']) {
    expect(numComponente).toContain(`${nome} fora do lugarGoogle.js`);
  }
  // No mapa.js e no seletor.js (o google.maps é deles também): só o lugar da Google.
  for (const ficheiro of ['lib/crm/mapa.js', 'lib/crm/seletor.js']) {
    expect([...new Set(regras(texto, ficheiro))].sort()).toEqual([
      'Place fora do lugarGoogle.js',
      'PlaceAutocompleteElement fora do lugarGoogle.js',
      'addressComponents fora do lugarGoogle.js',
      'fetchFields fora do lugarGoogle.js',
      'formattedAddress fora do lugarGoogle.js',
      'toPlace fora do lugarGoogle.js',
    ]);
  }
});
