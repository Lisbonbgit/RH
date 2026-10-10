/**
 * VARRIMENTO DE SEGURANÇA DO DOM — nenhum dado do CRM entra no DOM como HTML.
 *
 * Regra 9 do §0 do plano (dossiê §0, regra 9), com as correções
 * "T2.23 (seguranca.test.js)" e "T2.23 (porta do mapa.test.js e
 * seguranca.test.js)". O React escapa o texto por omissão; o perigo são as vias
 * que tratam um texto como HTML:
 *   - em todo o lado: `dangerouslySetInnerHTML`, `innerHTML`, `outerHTML`,
 *     `insertAdjacentHTML` e `document.write`, nem em comentários (o `dom.js` e o
 *     `mapa.js` falam de "HTML" sem os nomear);
 *   - o Leaflet põe como HTML o conteúdo das etiquetas e balões (`bindTooltip`,
 *     `bindPopup`, `setContent`, `setTooltipContent`, `setPopupContent`), o
 *     `html` de um `divIcon` e a atribuição (`attribution:`, o `prefix` do
 *     controlo, `addAttribution`, `setPrefix`). Só o `lib/crm/mapa.js` usa o
 *     conteúdo e a atribuição, e lá o conteúdo é sempre um nó do `el(...)` e a
 *     atribuição é sempre `ATRIBUICOES[...].html`. Um `divIcon` nunca leva `html`
 *     (o pino do seletor tem a forma no CSS, `.pino-seletor`, como no autónomo);
 *   - a mais: um `tel:` só se monta no `hrefTelefone` do `dom.js` (só dígitos e
 *     `+`).
 *
 * Varre os `.js` e `.jsx` de `lib/crm`, `components/crm` e `pages/crm`, mais o
 * `components/layouts/CrmLayout.js` e o `hooks/useEstadoCrm.js`. Ficam de fora
 * os testes (`*.test.js`) e a pasta `testes/` (os falsos rebentam de propósito
 * com estas vias, por isso nomeiam-nas).
 *
 * O `procurarHtmlPerigoso` é provado primeiro com amostras (cada regra apanha a
 * sua e o código seguro passa), e a lista dos ficheiros também: um varrimento
 * que não lê nada, ou que não sabe ler, passava sempre.
 */
/* eslint-disable no-template-curly-in-string -- as amostras são código-fonte com `${…}`, em texto de propósito */
import fs from 'fs';
import path from 'path';

// frontend/src/lib/crm → frontend/src
const SRC = path.join(__dirname, '..', '..');
const PASTAS = ['lib/crm', 'components/crm', 'pages/crm'];
const FICHEIROS_SOLTOS = ['components/layouts/CrmLayout.js', 'hooks/useEstadoCrm.js'];

const MAPA = 'lib/crm/mapa.js';
const DOM = 'lib/crm/dom.js';

// As chamadas do Leaflet que põem o conteúdo de uma etiqueta ou de um balão como HTML (se for texto).
const CONTEUDO_LEAFLET = /\b(?:bindTooltip|bindPopup|setContent|setTooltipContent|setPopupContent)\s*\(/g;

// [regra, padrão, onde]: onde = 'sempre' | 'fora do mapa' | 'no mapa' | 'fora do dom'.
const REGRAS = [
  ['dangerouslySetInnerHTML', /dangerouslySetInnerHTML/g, 'sempre'],
  ['innerHTML', /\binnerHTML\b/g, 'sempre'],
  ['outerHTML', /\bouterHTML\b/g, 'sempre'],
  ['insertAdjacentHTML', /\binsertAdjacentHTML\b/g, 'sempre'],
  // document.write e writeln, também num documento recebido por parâmetro (documento.write).
  ['document.write', /\.\s*write(?:ln)?\b/g, 'sempre'],
  ['addAttribution/setPrefix', /\b(?:addAttribution|setPrefix)\s*\(/g, 'sempre'],
  ['conteúdo do Leaflet fora do mapa.js', CONTEUDO_LEAFLET, 'fora do mapa'],
  ['attribution fora do mapa.js', /\battribution['"]?\s*:/g, 'fora do mapa'],
  // No mapa.js: o conteúdo é sempre um nó do el(...), e a atribuição sempre uma constante.
  [
    'conteúdo do Leaflet sem el()',
    // Os espaços ficam dentro do (?!…): fora, o \s* recuava um espaço e o "( el(" passava por perigoso.
    /\b(?:bindTooltip|bindPopup|setContent|setTooltipContent|setPopupContent)\s*\((?!\s*el\()/g,
    'no mapa',
  ],
  ['attribution sem ATRIBUICOES[…].html', /\battribution['"]?\s*:(?!\s*ATRIBUICOES\[[^\]\n]+\]\.html\b)/g, 'no mapa'],
  // Um texto que começa por tel: ('tel:…', "tel:…" ou `tel:…${…}`); um `tel:` num comentário passa.
  ['tel: fora do dom.js', /['"]tel:|`tel:(?!`)/g, 'fora do dom'],
];

// O texto entre os parênteses de uma chamada, a partir do que abre (sem contar os de dentro de textos:
// basta para objetos de opções).
function argumentos(texto, abre) {
  let nivel = 0;
  for (let i = abre; i < texto.length; i += 1) {
    if (texto[i] === '(') nivel += 1;
    else if (texto[i] === ')') {
      nivel -= 1;
      if (nivel === 0) return texto.slice(abre + 1, i);
    }
  }
  return texto.slice(abre + 1);
}

// Chamadas cujos argumentos são perigosos: um divIcon com html; o controlo de atribuição com um prefixo
// que não seja false.
const CHAMADAS = [
  ['divIcon com html', /\b[dD]ivIcon\s*\(/g, (args) => /\bhtml\b/.test(args)],
  [
    'prefixo da atribuição',
    /\b[aA]ttribution\s*\(/g,
    (args) => [...args.matchAll(/\bprefix\b(\s*:\s*([^\s,}]+))?/g)].some((m) => m[2] !== 'false'),
  ],
];

const linhaDe = (texto, indice) => texto.slice(0, indice).split('\n').length;

// procurarHtmlPerigoso(texto, {ficheiro}) → [{regra, linha}], pela ordem do texto. `ficheiro` é o caminho
// a partir de frontend/src (ex.: 'lib/crm/mapa.js'), para as exceções do mapa.js e do dom.js.
function procurarHtmlPerigoso(texto, { ficheiro = '' } = {}) {
  const eMapa = ficheiro === MAPA;
  const aplica = {
    sempre: true,
    'fora do mapa': !eMapa,
    'no mapa': eMapa,
    'fora do dom': ficheiro !== DOM,
  };
  const achados = [];
  for (const [regra, padrao, onde] of REGRAS) {
    if (!aplica[onde]) continue;
    for (const m of texto.matchAll(padrao)) achados.push({ regra, indice: m.index });
  }
  for (const [regra, padrao, perigosa] of CHAMADAS) {
    for (const m of texto.matchAll(padrao)) {
      const abre = m.index + m[0].length - 1;
      if (perigosa(argumentos(texto, abre))) achados.push({ regra, indice: m.index });
    }
  }
  return achados
    .sort((a, b) => a.indice - b.indice)
    .map(({ regra, indice }) => ({ regra, linha: linhaDe(texto, indice) }));
}

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

const regras = (texto, ficheiro = 'components/crm/Exemplo.js') =>
  procurarHtmlPerigoso(texto, { ficheiro }).map((v) => v.regra);

// --- O detetor, provado primeiro -----------------------------------------------------------------

describe('procurarHtmlPerigoso apanha cada via de HTML', () => {
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
    expect(regras(amostra)).toContain(regra);
    // Também no mapa.js: estas não têm exceção nenhuma.
    expect(regras(amostra, 'lib/crm/mapa.js')).toContain(regra);
  });

  test.each([
    ['marcador.bindTooltip(loja.nome);'],
    ['marcador.bindPopup(`<b>${loja.nome}</b>`);'],
    ['etiqueta.setContent(loja.nome);'],
    ['marcador.setTooltipContent(loja.nome);'],
    ['marcador.setPopupContent(loja.nome);'],
    ['marcador.bindTooltip(el(document, "span", { texto: loja.nome }));'],
  ])('fora do mapa.js, o Leaflet não recebe conteúdo: %s', (amostra) => {
    expect(regras(amostra, 'components/crm/SeletorLocalizacao.js')).toContain('conteúdo do Leaflet fora do mapa.js');
  });

  test.each([
    ['marcador.bindTooltip(loja.nome, { permanent: true });'],
    ['marcador.bindTooltip( `${loja.nome}` );'],
    ['marcador.bindPopup(texto);'],
  ])('no mapa.js, o conteúdo do Leaflet é sempre um nó do el(): %s', (amostra) => {
    expect(regras(amostra, 'lib/crm/mapa.js')).toContain('conteúdo do Leaflet sem el()');
  });

  test.each([
    ["L.divIcon({ className: 'pino-seletor', html: loja.nome });"],
    ["L.divIcon({ html });"],
    ["new L.DivIcon({ 'html': nome });"],
    ["L.divIcon({\n  className: 'pino',\n  iconSize: [44, 44],\n  html: `<b>${loja.nome}</b>`,\n});"],
  ])('um divIcon nunca leva html: %s', (amostra) => {
    expect(regras(amostra)).toContain('divIcon com html');
    expect(regras(amostra, 'lib/crm/mapa.js')).toContain('divIcon com html');
  });

  test.each([
    ["L.tileLayer(url, { attribution: '© ' + loja.nome });"],
    ['const opcoes = { attribution: ATRIBUICOES.osm.html };'],
    ["const opcoes = { 'attribution': texto };"],
  ])('fora do mapa.js não há attribution: %s', (amostra) => {
    expect(regras(amostra, 'components/crm/MapaLojas.js')).toContain('attribution fora do mapa.js');
  });

  test.each([
    ['L.tileLayer(url, { attribution: configuracao.atribuicao });'],
    ["L.tileLayer(url, { attribution: ATRIBUICOES[chave].texto });"],
    ["L.tileLayer(url, { attribution: '<a href=x>x</a>' });"],
  ])('no mapa.js, a attribution é sempre ATRIBUICOES[...].html: %s', (amostra) => {
    expect(regras(amostra, 'lib/crm/mapa.js')).toContain('attribution sem ATRIBUICOES[…].html');
  });

  test.each([
    ['L.control.attribution({ prefix: loja.nome }).addTo(mapa);'],
    ["L.control.attribution({ prefix: '<b>x</b>' });"],
    ['L.control.attribution({ prefix });'],
  ])('o prefixo do controlo de atribuição só pode ser false: %s', (amostra) => {
    expect(regras(amostra, 'lib/crm/mapa.js')).toContain('prefixo da atribuição');
  });

  test.each([
    ['mapa.attributionControl.addAttribution(texto);'],
    ['controlo.setPrefix(texto);'],
  ])('a atribuição não se muda por métodos: %s', (amostra) => {
    expect(regras(amostra)).toContain('addAttribution/setPrefix');
    expect(regras(amostra, 'lib/crm/mapa.js')).toContain('addAttribution/setPrefix');
  });

  test.each([
    ['<a href={`tel:${loja.telefone}`}>Ligar</a>'],
    ["const href = 'tel:' + loja.telefone;"],
    ['<a href="tel:+351912345678">Ligar</a>'],
  ])('um tel: só se monta no hrefTelefone do dom.js: %s', (amostra) => {
    expect(regras(amostra, 'components/crm/CartaoLoja.js')).toContain('tel: fora do dom.js');
  });
});

describe('procurarHtmlPerigoso deixa passar o código seguro', () => {
  test('fora do mapa.js', () => {
    const seguro = [
      'no.textContent = loja.nome;',
      "const etiqueta = el(documento, 'span', { texto: loja.nome });",
      '<span>{loja.nome}</span>',
      "const atribuicao = 'osm';",
      'const { partes } = ATRIBUICOES.pesquisa;',
      "const html = partes.map(ancora).join('');",
      "export const X = Object.freeze({ html: partes.map(ancora).join('') });",
      '<a href={hrefTelefone(loja.telefone)}>Ligar</a>',
      '// o "Ligar" leva o `tel:` do hrefTelefone',
      'navigator.clipboard.writeText(texto);',
      '// o pino do seletor é um divIcon sem html',
      "L.divIcon({ className: 'pino-seletor', iconSize: [44, 44], iconAnchor: [22, 38] });",
      'const mapa = L.map(elemento, { attributionControl: false });',
    ].join('\n');
    expect(procurarHtmlPerigoso(seguro, { ficheiro: 'components/crm/SeletorLocalizacao.js' })).toEqual([]);
  });

  test('no mapa.js, as exceções certas', () => {
    const seguro = [
      'const mapa = L.map(elemento, { minZoom: 6, maxZoom: 19, attributionControl: false });',
      'L.control.attribution({ prefix: false }).addTo(mapa);',
      'const camada = L.tileLayer(url, {',
      '  attribution: ATRIBUICOES[chave].html,',
      '});',
      "const outra = L.tileLayer(url, { attribution: ATRIBUICOES['osm'].html });",
      "L.divIcon({ className: classePino(loja.fase), iconSize: [44, 44], tooltipAnchor: [14, 0] });",
      "marcador.bindTooltip(el(documento, 'span', { texto: loja.nome }), {",
      "  permanent: true, direction: 'right', className: 'etiqueta-loja',",
      '});',
      "marcador.bindTooltip( el(documento, 'span', { texto: loja.nome }) );",
    ].join('\n');
    expect(procurarHtmlPerigoso(seguro, { ficheiro: 'lib/crm/mapa.js' })).toEqual([]);
  });

  test('no dom.js, o tel: do hrefTelefone', () => {
    expect(procurarHtmlPerigoso('return `tel:${mais}${digitos}`;', { ficheiro: 'lib/crm/dom.js' })).toEqual([]);
  });
});

test('procurarHtmlPerigoso diz a regra e a linha de cada uma', () => {
  const texto = "const a = 1;\nno.innerHTML = loja.nome;\n\nL.divIcon({\n  html: x,\n});\n";
  expect(procurarHtmlPerigoso(texto, { ficheiro: 'components/crm/Exemplo.js' })).toEqual([
    { regra: 'innerHTML', linha: 2 },
    { regra: 'divIcon com html', linha: 4 },
  ]);
});

// --- Que ficheiros se varrem ---------------------------------------------------------------------

test.each([
  ['lib/crm/mapa.js', true],
  ['components/crm/MapaLojas.js', true],
  ['pages/crm/CrmMapa.jsx', true],
  ['components/crm/sub/Pasta.jsx', true],
  ['lib/crm/mapa.test.js', false],
  ['pages/crm/CrmMapa.test.jsx', false],
  ['lib/crm/testes/leafletFalso.js', false],
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
    'lib/crm/dom.js',
    'lib/crm/atribuicoes.js',
    'lib/crm/api.js',
    'lib/crm/ecraMapa.js',
    'lib/crm/seletor.js',
    'lib/crm/pesquisaMorada.js',
    'components/crm/GuardaCrm.js',
    'components/crm/seccaoCrm.js',
    'components/crm/MapaLojas.js',
    'components/crm/FiltrosMapa.js',
    'components/crm/CartaoLoja.js',
    'components/crm/SeletorLocalizacao.js',
    'components/crm/PesquisaMorada.js',
    'pages/crm/CrmMapa.js',
    'pages/crm/rotasCrm.js',
    ...FICHEIROS_SOLTOS,
  ]) {
    expect(lista).toContain(relativo);
  }
  for (const relativo of [
    'lib/crm/seguranca.test.js',
    'lib/crm/dom.test.js',
    'lib/crm/mapa.test.js',
    'lib/crm/css.test.js',
    'lib/crm/ecraMapa.test.js',
    'lib/crm/seletor.test.js',
    'lib/crm/pesquisaMorada.test.js',
    'lib/crm/testes/domFalso.js',
    'lib/crm/testes/leafletFalso.js',
  ]) {
    expect(lista).not.toContain(relativo);
  }
});

// --- O varrimento --------------------------------------------------------------------------------

test('nenhum ficheiro do CRM põe dados no DOM como HTML', () => {
  // Falha, e não salta, se um dos ficheiros soltos desaparecer.
  for (const relativo of FICHEIROS_SOLTOS) {
    expect(fs.existsSync(path.join(SRC, relativo))).toBe(true);
  }
  const violacoes = [];
  for (const relativo of listarFicheiros()) {
    const texto = fs.readFileSync(path.join(SRC, relativo), 'utf8');
    for (const { regra, linha } of procurarHtmlPerigoso(texto, { ficheiro: relativo })) {
      violacoes.push(`${relativo}:${linha} ${regra}`);
    }
  }
  expect(violacoes).toEqual([]);
});

test('as exceções do mapa.js são precisas: o mesmo código noutro ficheiro seria recusado', () => {
  const mapa = fs.readFileSync(path.join(SRC, 'lib/crm/mapa.js'), 'utf8');
  const noutroSitio = regras(mapa, 'components/crm/MapaLojas.js');
  expect(noutroSitio).toContain('conteúdo do Leaflet fora do mapa.js');
  expect(noutroSitio).toContain('attribution fora do mapa.js');
});
