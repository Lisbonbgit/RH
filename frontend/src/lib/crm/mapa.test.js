/**
 * O MAPA DAS LOJAS — mosaicos, atribuição, pinos por fase e nomes sempre visíveis.
 *
 * Porta de tests/js/mapa.test.js do CRM autónomo (etiqueta
 * `referencia-standalone`), com o `node:assert` passado a `expect` e o Leaflet e
 * o DOM falsos de `testes/` (portados de tests/js/apoio/). Ficam de fora, pela
 * correção "T2.23 (porta do mapa.test.js e seguranca.test.js)":
 *   - o teste das cores do app.css: no portal é o `css.test.js` da T2.25, que
 *     lê o `components/crm/crm.css` (o `import.meta` do original não funciona no
 *     Jest do CRA);
 *   - a comparação com o `MENSAGEM_SEM_MAPA` do ecrã do autónomo: no portal os
 *     ecrãs importam-na daqui. Fica só o texto exato.
 *
 * Adaptação ao portal: os ids das lojas e das regiões são uuid em texto. A
 * configuração do mapa é a do GET /api/crm/config, com a mesma forma da sessão
 * do autónomo: {mosaicos: {url, atribuicao}, alternativa: {url}, centro}.
 *
 * A mais (no fim): a etiqueta com o `document` do jsdom, o centro por omissão
 * igual ao do servidor (lido do `backend/crm/dominio/definicoes.py`) e o mesmo
 * mapa sobre o Leaflet 1.9.4 verdadeiro, para o falso não esconder uma
 * diferença da biblioteca (o DOM que o Leaflet monta no jsdom: etiqueta, ícone,
 * atribuição, teclado e destruir).
 */
import fs from 'fs';
import path from 'path';
import * as LeafletVerdadeiro from 'leaflet';

import {
  criarMapa, configuracaoValida, ZOOM_MINIMO, ZOOM_MAXIMO, ZOOM_SEM_LOJAS, ZOOM_MAXIMO_ENQUADRAR, ZOOM_LOJA, CENTRO_PADRAO,
  MENSAGEM_SEM_MAPA,
} from './mapa';
import { ATRIBUICOES } from './atribuicoes';
import { leafletFalso } from './testes/leafletFalso';
import { documentoFalso } from './testes/domFalso';

// frontend/src/lib/crm → raiz do repositório.
const DEFINICOES_PY = path.join(__dirname, '..', '..', '..', '..', 'backend', 'crm', 'dominio', 'definicoes.py');

const URL_GEOAPIFY = 'http://127.0.0.1:8099/mosaicos/{z}/{x}/{y}.png?apiKey=chave-teste-mosaicos';
const URL_OSM = 'http://127.0.0.1:8099/osm/{z}/{x}/{y}.png';
const CENTRO = { lat: 38.7223, lng: -9.1393 };
const COM_GEOAPIFY = { mosaicos: { url: URL_GEOAPIFY, atribuicao: 'geoapify' }, alternativa: { url: URL_OSM }, centro: CENTRO };
const SO_OSM = { mosaicos: { url: URL_OSM, atribuicao: 'osm' }, alternativa: { url: URL_OSM }, centro: CENTRO };

const REGIAO = 'c3d4e5f6-a7b8-4c9d-a0e1-f2a3b4c5d6e7';
const ID_1 = '0b6c3f9e-8f1a-4c2d-9e3b-1a2b3c4d5e6f';
const ID_2 = '5d2e7a10-3b4c-4d5e-8f60-718293a4b5c6';
const ID_3 = 'a1b2c3d4-e5f6-4a7b-b8c9-d0e1f2a3b4c5';

const LOJAS = [
  { id: ID_1, nome: 'Mercearia da Baixa', fase: 'cliente', regiao_id: REGIAO, lat: 38.7108, lng: -9.1369, telefone: null },
  { id: ID_2, nome: 'Café Fechado', fase: 'perdida', regiao_id: REGIAO, lat: 38.7135, lng: -9.1458, telefone: null },
  { id: ID_3, nome: 'Quiosque Novo', fase: 'potencial', regiao_id: null, lat: 38.7400, lng: -9.1600, telefone: null },
];

function preparar(configuracao = COM_GEOAPIFY, opcoes = {}) {
  const { L, registo } = leafletFalso();
  const documento = documentoFalso();
  const elemento = documento.createElement('div');
  const mapa = criarMapa({ L, documento, elemento, configuracao, ...opcoes });
  return { L, registo, documento, elemento, mapa, leaflet: registo.mapas[0] };
}

const repetir = (n, fn) => {
  for (let i = 0; i < n; i += 1) fn();
};

// --- Mapa, mosaicos e atribuição -----------------------------------------------------------------

test('cria um só mapa no elemento, do zoom 6 ao 19, sem o controlo de atribuição por defeito', () => {
  const { registo, elemento, mapa, leaflet } = preparar();
  expect(registo.mapas.length).toBe(1);
  expect(leaflet.elemento).toBe(elemento);
  expect(ZOOM_MINIMO).toBe(6);
  expect(ZOOM_MAXIMO).toBe(19);
  expect(leaflet.options.minZoom).toBe(6);
  expect(leaflet.options.maxZoom).toBe(19);
  expect(leaflet.options.attributionControl).toBe(false);
  // O mapa do Leaflet fica disponível para os ecrãs.
  expect(mapa.mapa).toBe(leaflet);
});

test('atribuição com prefix:false (sem a ligação do Leaflet, creditado na licença)', () => {
  const { leaflet } = preparar();
  expect(leaflet.controlos.length).toBe(1);
  expect(leaflet.attributionControl.options.prefix).toBe(false);
});

test('botões de zoom em pt-PT: o controlo do Leaflet sai e entra um com "Aproximar" e "Afastar"', () => {
  // Revisão da F2 ("F2-PT-1"): o zoomControl por omissão do Leaflet tem "Zoom in"/"Zoom out" no title e no
  // aria-label (o CRM autónomo tinha a mesma falha).
  const { leaflet } = preparar();
  expect(leaflet.options.zoomControl).toBe(false);
  expect(leaflet.controloZoom.options).toEqual({ zoomInTitle: 'Aproximar', zoomOutTitle: 'Afastar' });
});

test('mosaicos Geoapify: uma camada com a URL da configuração, até ao zoom 19, e a atribuição exata da Geoapify', () => {
  const { leaflet, mapa } = preparar(COM_GEOAPIFY);
  expect(leaflet.mosaicos.length).toBe(1);
  const [camada] = leaflet.mosaicos;
  expect(camada.url).toBe(URL_GEOAPIFY);
  expect(camada.options.maxZoom).toBe(19);
  expect(camada.options.minZoom).toBe(6);
  expect(leaflet.attributionControl.html).toBe(ATRIBUICOES.geoapify.html);
  expect(mapa.atribuicao).toBe('geoapify');
});

test('os mosaicos usam a Referrer-Policy da página (a chave Geoapify e o OSM precisam do Referer)', () => {
  const { leaflet } = preparar(COM_GEOAPIFY);
  expect('referrerPolicy' in leaflet.mosaicos[0].options).toBe(false);
  expect('crossOrigin' in leaflet.mosaicos[0].options).toBe(false);
});

test('mosaicos OSM (sem chave): a atribuição exata do OSM', () => {
  const { leaflet, mapa } = preparar(SO_OSM);
  expect(leaflet.mosaicos[0].url).toBe(URL_OSM);
  expect(leaflet.attributionControl.html).toBe(ATRIBUICOES.osm.html);
  expect(mapa.atribuicao).toBe('osm');
});

test('uma atribuição desconhecida usa a do OSM: o HTML da atribuição vem sempre das constantes', () => {
  for (const atribuicao of ['pesquisa', '<img src=x onerror=alert(1)>', undefined, 'constructor']) {
    const { leaflet, mapa } = preparar({ ...COM_GEOAPIFY, mosaicos: { url: URL_GEOAPIFY, atribuicao } });
    expect(leaflet.attributionControl.html).toBe(ATRIBUICOES.osm.html);
    expect(mapa.atribuicao).toBe('osm');
  }
});

test('ao 3.º erro de mosaicos sem sucessos muda para os alternativos e para a atribuição do OSM', () => {
  const { leaflet, mapa } = preparar(COM_GEOAPIFY);
  const [principal] = leaflet.mosaicos;
  principal.fire('tileerror');
  principal.fire('tileerror');
  // Com 2 erros ainda não muda.
  expect(leaflet.mosaicos[0]).toBe(principal);
  principal.fire('tileerror');

  // Só uma camada de mosaicos no mapa.
  expect(leaflet.mosaicos.length).toBe(1);
  const [alternativa] = leaflet.mosaicos;
  expect(alternativa).not.toBe(principal);
  expect(alternativa.url).toBe(URL_OSM);
  expect(alternativa.options.maxZoom).toBe(19);
  // A atribuição da Geoapify sai.
  expect(leaflet.attributionControl.html).toBe(ATRIBUICOES.osm.html);
  expect(mapa.atribuicao).toBe('osm');
  expect(principal.listens('tileerror')).toBe(false);
  expect(principal.listens('tileload')).toBe(false);
});

test('com tantos sucessos como erros não muda; com mais erros do que sucessos muda', () => {
  const { leaflet } = preparar(COM_GEOAPIFY);
  const [principal] = leaflet.mosaicos;
  repetir(3, () => principal.fire('tileload'));
  repetir(3, () => principal.fire('tileerror'));
  expect(leaflet.mosaicos[0]).toBe(principal);
  principal.fire('tileerror');
  expect(leaflet.mosaicos[0].url).toBe(URL_OSM);
});

test('muda uma só vez: os erros dos mosaicos alternativos não criam outra camada', () => {
  const { leaflet, mapa } = preparar(COM_GEOAPIFY);
  repetir(3, () => leaflet.mosaicos[0].fire('tileerror'));
  const [alternativa] = leaflet.mosaicos;
  repetir(5, () => alternativa.fire('tileerror'));
  expect(leaflet.mosaicos).toEqual([alternativa]);
  expect(leaflet.mosaicos[0]).toBe(alternativa);
  expect(mapa.atribuicao).toBe('osm');
});

test('se os mosaicos já são os alternativos (sem chave), os erros não mudam nada', () => {
  const { leaflet } = preparar(SO_OSM);
  const [camada] = leaflet.mosaicos;
  repetir(10, () => camada.fire('tileerror'));
  expect(leaflet.mosaicos.length).toBe(1);
  expect(leaflet.mosaicos[0]).toBe(camada);
  expect(leaflet.attributionControl.html).toBe(ATRIBUICOES.osm.html);
});

test('sem URL alternativa, os erros não mudam nada', () => {
  const { leaflet } = preparar({ ...COM_GEOAPIFY, alternativa: undefined });
  const [camada] = leaflet.mosaicos;
  repetir(5, () => camada.fire('tileerror'));
  expect(leaflet.mosaicos.length).toBe(1);
  expect(leaflet.mosaicos[0]).toBe(camada);
  expect(leaflet.attributionControl.html).toBe(ATRIBUICOES.geoapify.html);
});

// --- Pinos e nomes -------------------------------------------------------------------------------

test('um pino por loja (sem agrupamento), na posição da loja e com a classe da fase', () => {
  const { mapa, leaflet } = preparar();
  mapa.mostrarLojas(LOJAS);
  const marcadores = leaflet.marcadores;
  expect(marcadores.length).toBe(3);
  expect(marcadores.map((m) => m.latlng)).toEqual([[38.7108, -9.1369], [38.7135, -9.1458], [38.74, -9.16]]);
  expect(marcadores.map((m) => m.options.icon.options.className)).toEqual([
    'pino pino--cliente',
    'pino pino--perdida',
    'pino pino--potencial',
  ]);
});

test('o pino é um divIcon sem HTML, com 44 px de área de toque centrada na loja', () => {
  const { mapa, leaflet } = preparar();
  mapa.mostrarLojas(LOJAS);
  const { icon } = leaflet.marcadores[0].options;
  expect(icon.tipo).toBe('divIcon');
  // O Leaflet poria o html como HTML.
  expect(icon.options.html).toBeUndefined();
  expect(icon.options.iconSize).toEqual([44, 44]);
  expect(icon.options.iconAnchor).toEqual([22, 22]);
});

test('o pino tem o nome e a fase como título (nome acessível do botão do Leaflet)', () => {
  const { mapa, leaflet } = preparar();
  mapa.mostrarLojas(LOJAS);
  expect(leaflet.marcadores[0].options.title).toBe('Mercearia da Baixa (Cliente)');
  expect(leaflet.marcadores[0].options.keyboard).toBe(true);
  mapa.mostrarLojas([{ ...LOJAS[0], fase: 'xpto' }]);
  expect(leaflet.marcadores[0].options.title).toBe('Mercearia da Baixa');
  expect(leaflet.marcadores[0].options.icon.options.className).toBe('pino');
});

test('o nome fica sempre visível: tooltip permanente à direita, com a classe etiqueta-loja', () => {
  const { mapa, leaflet } = preparar();
  mapa.mostrarLojas(LOJAS);
  for (const marcador of leaflet.marcadores) {
    expect(marcador.etiqueta.opcoes).toEqual({ permanent: true, direction: 'right', className: 'etiqueta-loja' });
  }
  expect(leaflet.marcadores[0].options.icon.options.tooltipAnchor).toEqual([14, 0]);
});

test('a etiqueta recebe um nó DOM com o nome como texto (um nome com HTML não vira elementos)', () => {
  const { mapa, leaflet } = preparar();
  mapa.mostrarLojas([{ ...LOJAS[0], nome: '<b>x</b>' }]);
  const { conteudo } = leaflet.marcadores[0].etiqueta;
  // Nunca uma string (o Leaflet poria-a como HTML).
  expect(typeof conteudo).toBe('object');
  expect(conteudo.tagName).toBe('SPAN');
  expect(conteudo.textContent).toBe('<b>x</b>');
  expect(conteudo.children.length).toBe(0);
  expect(leaflet.marcadores[0].options.title).toBe('<b>x</b> (Cliente)');
});

test('mostrarLojas substitui os pinos anteriores', () => {
  const { mapa, leaflet } = preparar();
  mapa.mostrarLojas(LOJAS);
  mapa.mostrarLojas([LOJAS[1]]);
  expect(leaflet.marcadores.length).toBe(1);
  expect(leaflet.marcadores[0].etiqueta.conteudo.textContent).toBe('Café Fechado');
  mapa.mostrarLojas([]);
  expect(leaflet.marcadores.length).toBe(0);
});

test('lojas sem coordenadas válidas ficam de fora (o resto aparece)', () => {
  const { mapa, leaflet } = preparar();
  mapa.mostrarLojas([
    { ...LOJAS[0], lat: null },
    { ...LOJAS[0], lng: '' },
    { ...LOJAS[0], lat: Number.NaN },
    { ...LOJAS[0], lng: Infinity },
    { ...LOJAS[0], lat: '38.7' },
    null,
    LOJAS[1],
  ]);
  expect(leaflet.marcadores.length).toBe(1);
  expect(leaflet.marcadores[0].etiqueta.conteudo.textContent).toBe('Café Fechado');
});

// --- Escolher uma loja (o cartão da loja) ---------------------------------------------------------

const tecla = (key) => {
  const evento = { key, evitado: false };
  evento.preventDefault = () => {
    evento.evitado = true;
  };
  return evento;
};

test('tocar num pino chama aoEscolherLoja com a loja e o marcador', () => {
  const escolhidas = [];
  const { mapa, leaflet } = preparar(COM_GEOAPIFY, { aoEscolherLoja: (loja, marcador) => escolhidas.push({ loja, marcador }) });
  mapa.mostrarLojas(LOJAS);
  leaflet.marcadores[1].fire('click');
  expect(escolhidas.length).toBe(1);
  expect(escolhidas[0].loja).toBe(LOJAS[1]);
  expect(escolhidas[0].marcador).toBe(leaflet.marcadores[1]);
});

test('Enter ou Espaço num pino com o foco também o escolhem (o pino é um botão para o teclado)', () => {
  const escolhidas = [];
  const { mapa, leaflet } = preparar(COM_GEOAPIFY, { aoEscolherLoja: (loja) => escolhidas.push(loja.id) });
  mapa.mostrarLojas(LOJAS);
  const [primeiro, segundo] = leaflet.marcadores;

  const enter = tecla('Enter');
  primeiro.fire('keydown', { originalEvent: enter });
  const espaco = tecla(' ');
  segundo.fire('keydown', { originalEvent: espaco });
  const outra = tecla('a');
  primeiro.fire('keydown', { originalEvent: outra });
  primeiro.fire('keydown', {});

  expect(escolhidas).toEqual([ID_1, ID_2]);
  expect(enter.evitado).toBe(true);
  // O Espaço não desloca a página.
  expect(espaco.evitado).toBe(true);
  // As outras teclas (setas, +, −) ficam para o Leaflet.
  expect(outra.evitado).toBe(false);
});

test('sem aoEscolherLoja, os pinos não ficam à escuta de toques', () => {
  const { mapa, leaflet } = preparar();
  mapa.mostrarLojas(LOJAS);
  expect(leaflet.marcadores[0].listens('click')).toBe(false);
  expect(leaflet.marcadores[0].listens('keydown')).toBe(false);
});

test('tocar no mapa (fora dos pinos) chama aoTocarNoMapa', () => {
  let toques = 0;
  const { leaflet } = preparar(COM_GEOAPIFY, { aoTocarNoMapa: () => { toques += 1; } });
  leaflet.fire('click');
  expect(toques).toBe(1);
});

test('tocar no mapa passa a aoTocarNoMapa o ponto tocado (o seletor de localização põe lá o pino)', () => {
  const pontos = [];
  const { leaflet } = preparar(COM_GEOAPIFY, { aoTocarNoMapa: (ponto) => pontos.push(ponto) });
  leaflet.fire('click', { latlng: { lat: 38.71, lng: -9.14 } });
  leaflet.fire('click');
  expect(pontos).toEqual([{ lat: 38.71, lng: -9.14 }, null]);
});

test('redimensionar avisa o Leaflet de que a área mudou, sem deslocar o que está no canto de cima', () => {
  const { mapa, leaflet } = preparar();
  mapa.redimensionar();
  expect(leaflet.redimensionamentos).toEqual([{ pan: false }]);
});

test('centrarEm desloca o mapa para a loja ficar ao centro (sem mudar o zoom)', () => {
  const { mapa, leaflet } = preparar();
  mapa.centrarEm(LOJAS[0]);
  expect(leaflet.vistas).toEqual([{ tipo: 'panTo', centro: [38.7108, -9.1369], opcoes: undefined }]);
  mapa.centrarEm({ ...LOJAS[0], lat: null });
  mapa.centrarEm(null);
  // Sem coordenadas válidas não mexe.
  expect(leaflet.vistas.length).toBe(1);
});

test('centrarEm com zoom põe a loja ao centro nesse zoom (o mapa depois de guardar uma loja nova)', () => {
  const { mapa, leaflet } = preparar();
  expect(ZOOM_LOJA).toBe(17);
  mapa.centrarEm(LOJAS[0], ZOOM_LOJA);
  expect(leaflet.vistas).toEqual([{ tipo: 'setView', centro: [38.7108, -9.1369], zoom: 17 }]);
  mapa.centrarEm({ ...LOJAS[0], lng: Number.NaN }, ZOOM_LOJA);
  // Sem coordenadas válidas não mexe.
  expect(leaflet.vistas.length).toBe(1);
});

test('configuracaoValida: só com a URL dos mosaicos (a configuração do mapa pode faltar)', () => {
  expect(configuracaoValida(COM_GEOAPIFY)).toBe(true);
  expect(configuracaoValida(SO_OSM)).toBe(true);
  for (const invalida of [null, undefined, {}, { mosaicos: {} }, { mosaicos: { url: '' } }, { mosaicos: { url: 42 } }]) {
    expect(configuracaoValida(invalida)).toBe(false);
  }
});

test('a mensagem de mapa indisponível é uma só, para o ecrã do mapa e o seletor de localização', () => {
  // No portal os dois importam-na daqui (o original comparava-a com a do ecrã).
  expect(MENSAGEM_SEM_MAPA).toBe('Não foi possível carregar o mapa — recarregue a página.');
});

// --- Vista inicial -------------------------------------------------------------------------------

test('enquadrar com lojas: fitBounds de todas, sem ir além do zoom 16', () => {
  const { mapa, leaflet } = preparar();
  mapa.enquadrar(LOJAS);
  expect(ZOOM_MAXIMO_ENQUADRAR).toBe(16);
  expect(leaflet.vistas.length).toBe(1);
  const [vista] = leaflet.vistas;
  expect(vista.tipo).toBe('fitBounds');
  expect(vista.limites.pontos).toEqual([[38.7108, -9.1369], [38.7135, -9.1458], [38.74, -9.16]]);
  expect(vista.opcoes.maxZoom).toBe(16);
  expect(Array.isArray(vista.opcoes.padding)).toBe(true);
});

test('enquadrar sem lojas (ou sem nenhuma com coordenadas): o centro das definições', () => {
  for (const lojas of [[], [{ ...LOJAS[0], lat: null }]]) {
    const { mapa, leaflet } = preparar();
    mapa.enquadrar(lojas);
    expect(leaflet.vistas).toEqual([{ tipo: 'setView', centro: [38.7223, -9.1393], zoom: ZOOM_SEM_LOJAS }]);
  }
  expect(ZOOM_SEM_LOJAS).toBe(12);
});

test('enquadrar sem lojas e sem centro válido: o ponto da fábrica por defeito', () => {
  for (const centro of [undefined, null, { lat: 'x', lng: -9 }]) {
    const { mapa, leaflet } = preparar({ ...COM_GEOAPIFY, centro });
    mapa.enquadrar([]);
    expect(leaflet.vistas[0].centro).toEqual([CENTRO_PADRAO.lat, CENTRO_PADRAO.lng]);
  }
  expect(CENTRO_PADRAO).toEqual({ lat: 38.7223, lng: -9.1393 });
});

test('destruir remove o mapa do Leaflet', () => {
  const { mapa, leaflet } = preparar();
  mapa.mostrarLojas(LOJAS);
  mapa.destruir();
  expect(leaflet.removido).toBe(true);
  expect(leaflet.camadas.size).toBe(0);
});

// --- A mais no portal ----------------------------------------------------------------------------

test('com o document do browser (jsdom), um nome com HTML fica texto e não cria elementos', () => {
  const { L, registo } = leafletFalso();
  const elemento = document.createElement('div');
  const mapa = criarMapa({ L, documento: document, elemento, configuracao: SO_OSM });
  mapa.mostrarLojas([{ ...LOJAS[0], nome: '<img src=x onerror=alert(1)><b>x</b>' }]);
  const { conteudo } = registo.mapas[0].marcadores[0].etiqueta;
  expect(conteudo).toBeInstanceOf(HTMLSpanElement);
  expect(conteudo.textContent).toBe('<img src=x onerror=alert(1)><b>x</b>');
  expect(conteudo.childElementCount).toBe(0);
  expect(conteudo.querySelector('img, b')).toBeNull();
});

test('sem aoTocarNoMapa, o mapa não fica à escuta de toques (um toque não rebenta no ecrã do mapa)', () => {
  const { leaflet } = preparar();
  expect(leaflet.listens('click')).toBe(false);
});

test('o ponto da fábrica por defeito é o do servidor (backend/crm/dominio/definicoes.py, PADROES)', () => {
  // Falha, e não salta, se o ficheiro não estiver lá (como o fases.test.js).
  expect(fs.existsSync(DEFINICOES_PY)).toBe(true);
  const python = fs.readFileSync(DEFINICOES_PY, 'utf8');
  const lat = [...python.matchAll(/^\s*"fabrica_lat": "(-?[0-9]+\.[0-9]+)",$/gm)];
  const lng = [...python.matchAll(/^\s*"fabrica_lng": "(-?[0-9]+\.[0-9]+)",$/gm)];
  expect(lat).toHaveLength(1);
  expect(lng).toHaveLength(1);
  expect(CENTRO_PADRAO).toEqual({ lat: Number(lat[0][1]), lng: Number(lng[0][1]) });
});

describe('sobre o Leaflet 1.9.4 verdadeiro (jsdom)', () => {
  // O jsdom não carrega imagens nem mede o elemento: chega para ver o DOM que o
  // Leaflet monta com o que o mapa.js lhe passa.
  let elemento;
  let mapa;

  beforeEach(() => {
    elemento = document.createElement('div');
    document.body.appendChild(elemento);
    mapa = null;
  });

  afterEach(() => {
    if (mapa) mapa.destruir();
    elemento.remove();
  });

  const abrir = (opcoes = {}) => {
    mapa = criarMapa({ L: LeafletVerdadeiro, documento: document, elemento, configuracao: SO_OSM, ...opcoes });
    mapa.enquadrar([]);
    return mapa;
  };

  test('a etiqueta do pino é o span com o nome como texto, sem elementos vindos do nome', () => {
    abrir().mostrarLojas([{ ...LOJAS[0], nome: '<b>x</b>' }]);
    const etiquetas = elemento.querySelectorAll('.leaflet-tooltip.etiqueta-loja');
    expect(etiquetas).toHaveLength(1);
    expect(etiquetas[0].textContent).toBe('<b>x</b>');
    expect(etiquetas[0].querySelectorAll('span')).toHaveLength(1);
    expect(etiquetas[0].querySelector('b')).toBeNull();
  });

  test('o ícone é a div da fase, vazia, focável e com o título', () => {
    abrir().mostrarLojas(LOJAS);
    const icones = elemento.querySelectorAll('.leaflet-marker-icon');
    expect(icones).toHaveLength(3);
    const [primeiro] = icones;
    expect(primeiro.classList.contains('pino')).toBe(true);
    expect(primeiro.classList.contains('pino--cliente')).toBe(true);
    expect(primeiro.childElementCount).toBe(0);
    expect(primeiro.textContent).toBe('');
    expect(primeiro.getAttribute('role')).toBe('button');
    expect(primeiro.getAttribute('tabindex')).toBe('0');
    expect(primeiro.title).toBe('Mercearia da Baixa (Cliente)');
  });

  test('a atribuição no canto é só a constante do OSM, sem o prefixo do Leaflet', () => {
    abrir();
    const atribuicao = elemento.querySelector('.leaflet-control-attribution');
    expect(atribuicao.textContent).toBe(ATRIBUICOES.osm.texto);
    const ligacoes = atribuicao.querySelectorAll('a');
    expect(ligacoes).toHaveLength(1);
    expect(ligacoes[0].getAttribute('href')).toBe(ATRIBUICOES.osm.partes[0].url);
    expect(atribuicao.textContent).not.toMatch(/Leaflet/);
  });

  test('um só controlo de zoom, com "Aproximar" e "Afastar" no title e no aria-label (nada em inglês)', () => {
    abrir();
    expect(elemento.querySelectorAll('.leaflet-control-zoom')).toHaveLength(1);
    const mais = elemento.querySelector('.leaflet-control-zoom-in');
    const menos = elemento.querySelector('.leaflet-control-zoom-out');
    expect(mais.getAttribute('title')).toBe('Aproximar');
    expect(mais.getAttribute('aria-label')).toBe('Aproximar');
    expect(menos.getAttribute('title')).toBe('Afastar');
    expect(menos.getAttribute('aria-label')).toBe('Afastar');
    expect(elemento.querySelector('[title^="Zoom"], [aria-label^="Zoom"]')).toBeNull();
  });

  test('Enter no pino escolhe a loja; tocar no mapa dá um ponto', () => {
    const escolhidas = [];
    const pontos = [];
    abrir({ aoEscolherLoja: (loja) => escolhidas.push(loja.id), aoTocarNoMapa: (ponto) => pontos.push(ponto) });
    mapa.mostrarLojas(LOJAS);
    const [primeiro] = elemento.querySelectorAll('.leaflet-marker-icon');
    const enter = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
    primeiro.dispatchEvent(enter);
    expect(escolhidas).toEqual([ID_1]);
    expect(enter.defaultPrevented).toBe(true);

    elemento.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: 0, clientY: 0 }));
    expect(pontos).toHaveLength(1);
    expect(Number.isFinite(pontos[0].lat)).toBe(true);
    expect(Number.isFinite(pontos[0].lng)).toBe(true);
  });

  test('destruir esvazia o elemento e deixa criar outro mapa nele (o StrictMode monta o mapa duas vezes)', () => {
    abrir().mostrarLojas(LOJAS);
    expect(elemento.querySelectorAll('.leaflet-marker-icon')).toHaveLength(3);
    mapa.destruir();
    mapa = null;
    // O Leaflet tira os painéis e os controlos (as classes do contentor ficam).
    expect(elemento.childElementCount).toBe(0);
    // Um mapa novo no mesmo elemento não rebenta ("Map container is already initialized").
    abrir().mostrarLojas(LOJAS);
    expect(elemento.querySelectorAll('.leaflet-marker-icon')).toHaveLength(3);
  });
});
