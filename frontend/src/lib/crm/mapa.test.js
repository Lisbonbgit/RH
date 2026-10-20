/**
 * O MAPA DAS LOJAS sobre o Google Maps — pinos por fase com o nome sempre
 * visível, escolher uma loja, tocar no mapa ou num negócio, enquadrar,
 * centrar e destruir.
 *
 * Reescrito na G6 do plano do mapa Google sobre o `googleFalso` (G5) e o
 * `domFalso`: ficam os testes dos pinos, dos nomes, de escolher, de tocar, de
 * enquadrar, de centrar, de destruir e do centro padrão, adaptados; saem os dos
 * mosaicos, da atribuição e da troca para o OSM (a atribuição é a da própria
 * Google) e os do Leaflet verdadeiro no jsdom; entram os novos: as opções
 * exatas do `Map`, a configuração `{google: {chave, map_id}}`, o toque num
 * negócio (o balão é o da Google: o código nunca chama `stop()` nem cria um
 * balão seu), o limite do zoom depois de enquadrar num `idle` único, o
 * `focar()`, o `__crmMapa` (regra 16) e o `pontoDe`.
 *
 * O Jest do CRA corre com `resetMocks`: o falso cria-se dentro de cada teste.
 */
import fs from 'fs';
import path from 'path';

import {
  criarMapa, configuracaoValida, pontoDe, limitarZoomDepoisDeEnquadrar,
  ZOOM_MINIMO, ZOOM_MAXIMO, ZOOM_SEM_LOJAS, ZOOM_MAXIMO_ENQUADRAR, ZOOM_LOJA, CENTRO_PADRAO, MARGEM_ENQUADRAR,
  MENSAGEM_SEM_MAPA, MENSAGEM_MAPA_NAO_CONFIGURADO,
} from './mapa';
import { googleFalso, eventoDeToque } from './testes/googleFalso';
import { documentoFalso } from './testes/domFalso';

// frontend/src/lib/crm → raiz do repositório.
const DEFINICOES_PY = path.join(__dirname, '..', '..', '..', '..', 'backend', 'crm', 'dominio', 'definicoes.py');

// O centro das definições (diferente do CENTRO_PADRAO, para se ver de onde vem).
const CENTRO = { lat: 38.7369, lng: -9.1427 };
const CONFIGURACAO = { google: { chave: 'chave-teste-navegador', map_id: 'map-id-teste' }, centro: CENTRO };

const REGIAO = 'c3d4e5f6-a7b8-4c9d-a0e1-f2a3b4c5d6e7';
const ID_1 = '0b6c3f9e-8f1a-4c2d-9e3b-1a2b3c4d5e6f';
const ID_2 = '5d2e7a10-3b4c-4d5e-8f60-718293a4b5c6';
const ID_3 = 'a1b2c3d4-e5f6-4a7b-b8c9-d0e1f2a3b4c5';

const LOJAS = [
  { id: ID_1, nome: 'Mercearia da Baixa', fase: 'cliente', regiao_id: REGIAO, lat: 38.7108, lng: -9.1369, telefone: null },
  { id: ID_2, nome: 'Café Fechado', fase: 'perdida', regiao_id: REGIAO, lat: 38.7135, lng: -9.1458, telefone: null },
  { id: ID_3, nome: 'Quiosque Novo', fase: 'potencial', regiao_id: null, lat: 38.7400, lng: -9.1600, telefone: null },
];

const PLACE_ID = 'ChIJ-teste-negocio';

// Por omissão, o DOM falso (rebenta com qualquer via de HTML em texto); com {jsdom: true}, o `document` do
// Jest com o elemento na página.
function preparar(configuracao = CONFIGURACAO, opcoes = {}, { jsdom = false } = {}) {
  const documento = jsdom ? document : documentoFalso();
  const { google, registo } = googleFalso({ documento });
  const elemento = documento.createElement('div');
  if (jsdom) document.body.appendChild(elemento);
  const mapa = criarMapa({ google, documento, elemento, configuracao, ...opcoes });
  return { google, registo, documento, elemento, mapa, mapaGoogle: registo.mapas[0] };
}

afterEach(() => {
  document.body.replaceChildren();
});

const conteudoDe = (marcador) => marcador.content;
const etiquetaDe = (marcador) => Array.from(conteudoDe(marcador).children)[1];

// --- O mapa e a configuração ---------------------------------------------------------------------

test('cria um só Map no elemento, com as opções exatas (Map ID, centro, zoom 6–19, só o zoom da Google)', () => {
  const { registo, elemento, mapa, mapaGoogle } = preparar();
  expect(registo.mapas.length).toBe(1);
  expect(mapaGoogle.getDiv()).toBe(elemento);
  expect(mapaGoogle.options).toStrictEqual({
    mapId: 'map-id-teste',
    center: { lat: 38.7369, lng: -9.1427 },
    zoom: 12,
    minZoom: 6,
    maxZoom: 19,
    clickableIcons: true,
    disableDefaultUI: true,
    zoomControl: true,
    gestureHandling: 'greedy',
    mapTypeId: 'roadmap',
  });
  expect(ZOOM_MINIMO).toBe(6);
  expect(ZOOM_MAXIMO).toBe(19);
  expect(ZOOM_SEM_LOJAS).toBe(12);
  // O Map da Google fica disponível para os ecrãs (o seletor da G10 enquadra o círculo do GPS nele).
  expect(mapa.mapa).toBe(mapaGoogle);
});

test('o objeto do mapa tem só a interface dos ecrãs (sem a atribuição nem os mosaicos do Leaflet)', () => {
  const { mapa } = preparar();
  expect(Object.keys(mapa).sort()).toEqual(
    ['centrarEm', 'destruir', 'enquadrar', 'focar', 'mapa', 'mostrarLojas', 'redimensionar'],
  );
});

test('o centro inicial é o das definições, só com lat e lng; sem centro válido, o ponto da fábrica por defeito', () => {
  const { mapaGoogle } = preparar({ ...CONFIGURACAO, centro: { ...CENTRO, extra: 'x' } });
  expect(mapaGoogle.options.center).toStrictEqual(CENTRO);
  for (const centro of [undefined, null, { lat: 'x', lng: -9 }, { lat: 38.7 }, [38.7, -9.1]]) {
    const outro = preparar({ ...CONFIGURACAO, centro }).mapaGoogle;
    expect(outro.options.center).toStrictEqual({ lat: CENTRO_PADRAO.lat, lng: CENTRO_PADRAO.lng });
  }
});

test('negociosClicaveis: false (o planeador) desliga os ícones de negócio da Google', () => {
  expect(preparar(CONFIGURACAO, { negociosClicaveis: false }).mapaGoogle.options.clickableIcons).toBe(false);
  expect(preparar(CONFIGURACAO, { negociosClicaveis: true }).mapaGoogle.options.clickableIcons).toBe(true);
});

test('o elemento fica focável por código (tabIndex -1) e focar() põe lá o foco', () => {
  const { elemento, mapa, documento } = preparar();
  expect(elemento.tabIndex).toBe(-1);
  expect(documento.activeElement).not.toBe(elemento);
  mapa.focar();
  expect(documento.activeElement).toBe(elemento);
});

test('focar() com o document do browser (jsdom): o mapa fica com o foco', () => {
  const { elemento, mapa } = preparar(CONFIGURACAO, {}, { jsdom: true });
  expect(elemento.tabIndex).toBe(-1);
  mapa.focar();
  expect(document.activeElement).toBe(elemento);
});

test('o elemento guarda o Map em __crmMapa (só para a verificação no browser da G21)', () => {
  const { elemento, mapaGoogle } = preparar();
  expect(elemento.__crmMapa).toBe(mapaGoogle);
});

test('configuracaoValida: só com a chave do navegador e o Map ID em texto não vazio', () => {
  expect(configuracaoValida(CONFIGURACAO)).toBe(true);
  expect(configuracaoValida({ google: { chave: 'k', map_id: 'm' } })).toBe(true);
  for (const invalida of [
    null,
    undefined,
    {},
    { google: null },
    { google: {} },
    { google: { chave: '' } },
    { google: { chave: '', map_id: 'm' } },
    { google: { chave: 'k' } },
    { google: { chave: 'k', map_id: '' } },
    { google: { chave: '   ', map_id: 'm' } },
    { google: { chave: 'k', map_id: ' ' } },
    { google: { chave: 42, map_id: 'm' } },
    { google: { chave: 'k', map_id: 42 } },
    // A forma antiga do GET /config (Leaflet + Geoapify).
    { mosaicos: { url: 'http://x/{z}/{x}/{y}.png', atribuicao: 'geoapify' }, alternativa: { url: 'http://y' }, centro: CENTRO },
  ]) {
    expect(configuracaoValida(invalida)).toBe(false);
  }
});

test('as mensagens sem mapa: a de sempre (a Google não carregou) e a nova (sem chave no servidor)', () => {
  expect(MENSAGEM_SEM_MAPA).toBe('Não foi possível carregar o mapa — recarregue a página.');
  expect(MENSAGEM_MAPA_NAO_CONFIGURADO).toBe('Mapa não configurado — peça ao administrador para configurar a chave Google.');
});

// --- Pinos e nomes -------------------------------------------------------------------------------

test('um AdvancedMarkerElement por loja (sem agrupamento), no mapa e na posição da loja', () => {
  const { mapa, registo, mapaGoogle } = preparar();
  mapa.mostrarLojas(LOJAS);
  const { marcadores } = registo;
  expect(marcadores.length).toBe(3);
  expect(marcadores.every((m) => m.map === mapaGoogle)).toBe(true);
  expect(marcadores.map((m) => m.posicao())).toEqual([
    { lat: 38.7108, lng: -9.1369 },
    { lat: 38.7135, lng: -9.1458 },
    { lat: 38.74, lng: -9.16 },
  ]);
  // A posição vai como literal {lat, lng} (nunca o par [lat, lng] do Leaflet).
  expect(marcadores[0].options.position).toStrictEqual({ lat: 38.7108, lng: -9.1369 });
});

test('o pino: "Nome (Fase)" como título, recebe toques, nunca se esconde por colisão e não se arrasta', () => {
  const { google, mapa, registo } = preparar();
  mapa.mostrarLojas(LOJAS);
  const [marcador] = registo.marcadores;
  expect(marcador.title).toBe('Mercearia da Baixa (Cliente)');
  expect(marcador.gmpClickable).toBe(true);
  expect(marcador.collisionBehavior).toBe(google.maps.CollisionBehavior.REQUIRED);
  expect(marcador.gmpDraggable).toBe(false);
  // As opções exatas: nada de arrasto, zIndex ou outras.
  expect(Object.keys(marcador.options).sort()).toEqual(
    ['collisionBehavior', 'content', 'gmpClickable', 'map', 'position', 'title'],
  );
});

test('uma fase desconhecida: o título é só o nome e a classe só "pino"', () => {
  const { mapa, registo } = preparar();
  mapa.mostrarLojas([{ ...LOJAS[0], fase: 'xpto' }]);
  const [marcador] = registo.marcadores;
  expect(marcador.title).toBe('Mercearia da Baixa');
  expect(conteudoDe(marcador).className).toBe('pino');
});

test('o conteúdo do pino é a div da fase com a bola e a etiqueta com o nome (sempre visível)', () => {
  const { mapa, registo } = preparar();
  mapa.mostrarLojas(LOJAS);
  expect(registo.marcadores.map((m) => conteudoDe(m).className)).toEqual([
    'pino pino--cliente',
    'pino pino--perdida',
    'pino pino--potencial',
  ]);
  const conteudo = conteudoDe(registo.marcadores[0]);
  expect(conteudo.tagName).toBe('DIV');
  const filhos = Array.from(conteudo.children);
  expect(filhos.map((no) => no.tagName)).toEqual(['SPAN', 'SPAN']);
  expect(filhos.map((no) => no.className)).toEqual(['pino__bola', 'etiqueta-loja']);
  expect(filhos[0].textContent).toBe('');
  expect(filhos[1].textContent).toBe('Mercearia da Baixa');
});

test('um nome com HTML fica texto na etiqueta e no título (DOM falso: nenhuma via de HTML)', () => {
  const { mapa, registo } = preparar();
  mapa.mostrarLojas([{ ...LOJAS[0], nome: '<b>x</b>' }]);
  const [marcador] = registo.marcadores;
  const etiqueta = etiquetaDe(marcador);
  expect(etiqueta.textContent).toBe('<b>x</b>');
  expect(etiqueta.children.length).toBe(0);
  expect(marcador.title).toBe('<b>x</b> (Cliente)');
});

test('com o document do browser (jsdom), um nome com HTML não cria elementos', () => {
  const { mapa, registo, elemento } = preparar(CONFIGURACAO, {}, { jsdom: true });
  mapa.mostrarLojas([{ ...LOJAS[0], nome: '<img src=x onerror=alert(1)><b>x</b>' }]);
  const conteudo = conteudoDe(registo.marcadores[0]);
  expect(conteudo).toBeInstanceOf(HTMLDivElement);
  expect(conteudo.querySelector('.etiqueta-loja').textContent).toBe('<img src=x onerror=alert(1)><b>x</b>');
  expect(conteudo.querySelector('img, b')).toBeNull();
  // O pino está no DOM do mapa (o falso põe lá o conteúdo dos marcadores que têm map).
  expect(elemento.querySelectorAll('.pino')).toHaveLength(1);
  expect(elemento.querySelector('b')).toBeNull();
});

test('mostrarLojas substitui os pinos anteriores (map = null nos antigos)', () => {
  const { mapa, registo } = preparar();
  mapa.mostrarLojas(LOJAS);
  const antigos = [...registo.marcadores];
  mapa.mostrarLojas([LOJAS[1]]);
  expect(antigos.every((m) => m.map === null)).toBe(true);
  expect(registo.marcadores.length).toBe(1);
  expect(etiquetaDe(registo.marcadores[0]).textContent).toBe('Café Fechado');
  mapa.mostrarLojas([]);
  expect(registo.marcadores.length).toBe(0);
});

test('lojas sem coordenadas válidas ficam de fora (o resto aparece)', () => {
  const { mapa, registo } = preparar();
  mapa.mostrarLojas([
    { ...LOJAS[0], lat: null },
    { ...LOJAS[0], lng: '' },
    { ...LOJAS[0], lat: Number.NaN },
    { ...LOJAS[0], lng: Infinity },
    { ...LOJAS[0], lat: '38.7' },
    null,
    LOJAS[1],
  ]);
  expect(registo.marcadores.length).toBe(1);
  expect(etiquetaDe(registo.marcadores[0]).textContent).toBe('Café Fechado');
});

// --- Escolher uma loja (o cartão da loja) ---------------------------------------------------------

test('tocar num pino (gmp-click, rato ou teclado) chama aoEscolherLoja com a loja e o marcador', () => {
  const escolhidas = [];
  const { mapa, registo } = preparar(CONFIGURACAO, { aoEscolherLoja: (loja, marcador) => escolhidas.push({ loja, marcador }) });
  mapa.mostrarLojas(LOJAS);
  registo.marcadores[1].tocar();
  expect(escolhidas.length).toBe(1);
  expect(escolhidas[0].loja).toBe(LOJAS[1]);
  expect(escolhidas[0].marcador).toBe(registo.marcadores[1]);
  expect(registo.infoWindowsNossas).toBe(0);
});

test('sem aoEscolherLoja, os pinos não ficam à escuta de toques', () => {
  const { mapa, registo } = preparar();
  mapa.mostrarLojas(LOJAS);
  expect(registo.marcadores[0].ouvintes('gmp-click')).toBe(0);
  // Tocar não rebenta nem faz nada.
  registo.marcadores[0].tocar();
});

// --- Tocar no mapa ou num negócio ----------------------------------------------------------------

function ouvintesDeToque() {
  const pontos = [];
  const lugares = [];
  return {
    pontos,
    lugares,
    aoTocarNoMapa: (ponto) => pontos.push(ponto),
    aoTocarNumLugar: (lugar) => lugares.push(lugar),
  };
}

test('tocar no mapa (fora dos negócios) passa a aoTocarNoMapa o ponto tocado', () => {
  const toques = ouvintesDeToque();
  const { mapaGoogle, registo } = preparar(CONFIGURACAO, toques);
  mapaGoogle.fire('click', eventoDeToque({ lat: 38.71, lng: -9.14 }));
  // O latLng da Google pode chegar como literal.
  mapaGoogle.fire('click', { latLng: { lat: 38.72, lng: -9.15 } });
  mapaGoogle.fire('click', {});
  expect(toques.pontos).toStrictEqual([{ lat: 38.71, lng: -9.14 }, { lat: 38.72, lng: -9.15 }, null]);
  expect(toques.lugares).toEqual([]);
  expect(registo.baloesDaGoogle).toBe(0);
  expect(registo.infoWindowsNossas).toBe(0);
});

test('tocar num negócio: o balão da Google abre (sem stop), aoTocarNumLugar recebe o lugar e o mapa não', () => {
  const toques = ouvintesDeToque();
  const { mapaGoogle, registo } = preparar(CONFIGURACAO, toques);
  const evento = eventoDeToque({ lat: 38.711, lng: -9.137, placeId: PLACE_ID });
  mapaGoogle.fire('click', evento);
  expect(evento.parado).toBe(false);
  expect(registo.baloesDaGoogle).toBe(1);
  expect(toques.lugares).toStrictEqual([{ placeId: PLACE_ID, lat: 38.711, lng: -9.137 }]);
  expect(toques.pontos).toEqual([]);
  expect(registo.infoWindowsNossas).toBe(0);
});

test('tocar num negócio sem aoTocarNumLugar: aoTocarNoMapa recebe o ponto e o balão da Google abre na mesma', () => {
  const pontos = [];
  const { mapaGoogle, registo } = preparar(CONFIGURACAO, { aoTocarNoMapa: (ponto) => pontos.push(ponto) });
  const evento = eventoDeToque({ lat: 38.711, lng: -9.137, placeId: PLACE_ID });
  mapaGoogle.fire('click', evento);
  expect(pontos).toStrictEqual([{ lat: 38.711, lng: -9.137 }]);
  expect(evento.parado).toBe(false);
  expect(registo.baloesDaGoogle).toBe(1);
  expect(registo.infoWindowsNossas).toBe(0);
});

test('só com aoTocarNumLugar: um toque fora dos negócios não chama nada', () => {
  const lugares = [];
  const { mapaGoogle } = preparar(CONFIGURACAO, { aoTocarNumLugar: (lugar) => lugares.push(lugar) });
  mapaGoogle.fire('click', eventoDeToque({ lat: 38.71, lng: -9.14 }));
  expect(lugares).toEqual([]);
  mapaGoogle.fire('click', eventoDeToque({ lat: 38.71, lng: -9.14, placeId: PLACE_ID }));
  expect(lugares).toStrictEqual([{ placeId: PLACE_ID, lat: 38.71, lng: -9.14 }]);
});

test('um negócio sem latLng chega a aoTocarNumLugar com lat e lng a null', () => {
  const toques = ouvintesDeToque();
  const { mapaGoogle } = preparar(CONFIGURACAO, toques);
  mapaGoogle.fire('click', { placeId: PLACE_ID, stop() {} });
  expect(toques.lugares).toStrictEqual([{ placeId: PLACE_ID, lat: null, lng: null }]);
});

test('negociosClicaveis: false — um toque num negócio chega como toque no mapa e não abre balão', () => {
  const toques = ouvintesDeToque();
  const { mapaGoogle, registo } = preparar(CONFIGURACAO, { ...toques, negociosClicaveis: false });
  mapaGoogle.fire('click', eventoDeToque({ lat: 38.711, lng: -9.137, placeId: PLACE_ID }));
  expect(toques.pontos).toStrictEqual([{ lat: 38.711, lng: -9.137 }]);
  expect(toques.lugares).toEqual([]);
  expect(registo.baloesDaGoogle).toBe(0);
  expect(registo.infoWindowsNossas).toBe(0);
});

test('um placeId que não é texto não vazio conta como toque no mapa', () => {
  for (const placeId of ['', 42, null, { id: 'x' }]) {
    const toques = ouvintesDeToque();
    const { mapaGoogle } = preparar(CONFIGURACAO, toques);
    mapaGoogle.fire('click', eventoDeToque({ lat: 38.71, lng: -9.14, placeId }));
    expect(toques.lugares).toEqual([]);
    expect(toques.pontos).toStrictEqual([{ lat: 38.71, lng: -9.14 }]);
  }
});

test('sem aoTocarNoMapa nem aoTocarNumLugar, o mapa não fica à escuta de toques (o balão da Google abre na mesma)', () => {
  const { mapaGoogle, registo } = preparar();
  expect(mapaGoogle.ouvintes('click')).toBe(0);
  mapaGoogle.fire('click', eventoDeToque({ lat: 38.71, lng: -9.14, placeId: PLACE_ID }));
  expect(registo.baloesDaGoogle).toBe(1);
  expect(registo.infoWindowsNossas).toBe(0);
});

// --- Redimensionar e centrar ---------------------------------------------------------------------

test('redimensionar avisa a Google de que a área mudou (resize)', () => {
  const { mapa, mapaGoogle } = preparar();
  mapa.redimensionar();
  expect(mapaGoogle.disparos.map((d) => d.tipo)).toEqual(['resize']);
  expect(mapaGoogle.vistas).toEqual([]);
});

test('centrarEm desloca o mapa para a loja ficar ao centro (sem mudar o zoom)', () => {
  const { mapa, mapaGoogle } = preparar();
  mapa.centrarEm(LOJAS[0]);
  expect(mapaGoogle.vistas).toStrictEqual([{ tipo: 'panTo', centro: { lat: 38.7108, lng: -9.1369 } }]);
  mapa.centrarEm({ ...LOJAS[0], lat: null });
  mapa.centrarEm(null);
  // Sem coordenadas válidas não mexe.
  expect(mapaGoogle.vistas.length).toBe(1);
});

test('centrarEm com zoom põe a loja ao centro nesse zoom (o mapa depois de guardar uma loja nova)', () => {
  const { mapa, mapaGoogle } = preparar();
  expect(ZOOM_LOJA).toBe(17);
  mapa.centrarEm(LOJAS[0], ZOOM_LOJA);
  expect(mapaGoogle.vistas).toStrictEqual([
    { tipo: 'setCenter', centro: { lat: 38.7108, lng: -9.1369 } },
    { tipo: 'setZoom', zoom: 17 },
  ]);
  expect(mapaGoogle.getZoom()).toBe(17);
  mapa.centrarEm({ ...LOJAS[0], lng: Number.NaN }, ZOOM_LOJA);
  // Sem coordenadas válidas não mexe.
  expect(mapaGoogle.vistas.length).toBe(2);
});

// --- Vista inicial: enquadrar e o limite do zoom --------------------------------------------------

test('enquadrar com lojas: fitBounds com um LatLngBounds de todas e a margem de 40 px', () => {
  const { google, mapa, mapaGoogle } = preparar();
  mapa.enquadrar(LOJAS);
  expect(MARGEM_ENQUADRAR).toBe(40);
  expect(mapaGoogle.vistas.length).toBe(1);
  const [vista] = mapaGoogle.vistas;
  expect(vista.tipo).toBe('fitBounds');
  expect(vista.limites).toBeInstanceOf(google.maps.LatLngBounds);
  expect(vista.limites.pontos).toStrictEqual([
    { lat: 38.7108, lng: -9.1369 },
    { lat: 38.7135, lng: -9.1458 },
    { lat: 38.74, lng: -9.16 },
  ]);
  for (const loja of LOJAS) expect(vista.limites.contains({ lat: loja.lat, lng: loja.lng })).toBe(true);
  expect(vista.margem).toBe(40);
});

test('depois de enquadrar, o primeiro idle baixa um zoom acima de 16 para 16 (uma só vez)', () => {
  const { mapa, mapaGoogle } = preparar();
  expect(ZOOM_MAXIMO_ENQUADRAR).toBe(16);
  mapa.enquadrar([LOJAS[0]]);
  expect(mapaGoogle.ouvintes('idle')).toBe(1);
  // A Google enquadrou uma loja só no zoom 18.
  mapaGoogle.setZoom(18);
  mapaGoogle.fire('idle');
  expect(mapaGoogle.getZoom()).toBe(16);
  expect(mapaGoogle.ouvintes('idle')).toBe(0);
  // A pessoa aproxima depois: o idle seguinte já não mexe.
  mapaGoogle.setZoom(19);
  mapaGoogle.fire('idle');
  expect(mapaGoogle.getZoom()).toBe(19);
});

test('depois de enquadrar, um zoom de 15 fica como está', () => {
  const { mapa, mapaGoogle } = preparar();
  mapa.enquadrar(LOJAS);
  mapaGoogle.setZoom(15);
  const vistas = mapaGoogle.vistas.length;
  mapaGoogle.fire('idle');
  expect(mapaGoogle.getZoom()).toBe(15);
  expect(mapaGoogle.vistas.length).toBe(vistas);
});

test('dois enquadrar seguidos sem idle pelo meio: um só ouvinte de idle ativo', () => {
  const { mapa, mapaGoogle } = preparar();
  mapa.enquadrar(LOJAS);
  mapa.enquadrar([LOJAS[1]]);
  expect(mapaGoogle.ouvintes('idle')).toBe(1);
  mapaGoogle.setZoom(18);
  mapaGoogle.fire('idle');
  expect(mapaGoogle.getZoom()).toBe(16);
  expect(mapaGoogle.vistas.filter((v) => v.tipo === 'setZoom').map((v) => v.zoom)).toEqual([18, 16]);
});

test('um idle tardio não desfaz o zoom de centrarEm nem o do enquadrar sem lojas', () => {
  const { mapa, mapaGoogle } = preparar();
  mapa.enquadrar(LOJAS);
  mapa.centrarEm(LOJAS[0], ZOOM_LOJA);
  expect(mapaGoogle.ouvintes('idle')).toBe(0);
  mapaGoogle.fire('idle');
  expect(mapaGoogle.getZoom()).toBe(17);

  mapa.enquadrar(LOJAS);
  mapa.enquadrar([]);
  expect(mapaGoogle.ouvintes('idle')).toBe(0);
});

test('centrarEm sem zoom (deslocar) não tira o limite que o enquadrar armou', () => {
  const { mapa, mapaGoogle } = preparar();
  mapa.enquadrar([LOJAS[0]]);
  mapa.centrarEm(LOJAS[1]);
  expect(mapaGoogle.ouvintes('idle')).toBe(1);
});

test('enquadrar sem lojas (ou sem nenhuma com coordenadas): o centro das definições no zoom 12', () => {
  for (const lojas of [[], [{ ...LOJAS[0], lat: null }]]) {
    const { mapa, mapaGoogle } = preparar();
    mapa.enquadrar(lojas);
    expect(mapaGoogle.vistas).toStrictEqual([
      { tipo: 'setCenter', centro: CENTRO },
      { tipo: 'setZoom', zoom: ZOOM_SEM_LOJAS },
    ]);
    expect(mapaGoogle.ouvintes('idle')).toBe(0);
  }
});

test('enquadrar sem lojas e sem centro válido: o ponto da fábrica por defeito', () => {
  for (const centro of [undefined, null, { lat: 'x', lng: -9 }]) {
    const { mapa, mapaGoogle } = preparar({ ...CONFIGURACAO, centro });
    mapa.enquadrar([]);
    expect(mapaGoogle.vistas[0]).toStrictEqual({ tipo: 'setCenter', centro: { lat: 38.7223, lng: -9.1393 } });
  }
  expect(CENTRO_PADRAO).toEqual({ lat: 38.7223, lng: -9.1393 });
});

test('limitarZoomDepoisDeEnquadrar: devolve o ouvinte; um só por mapa; o idle limita e o ouvinte sai', () => {
  const documento = documentoFalso();
  const { google } = googleFalso({ documento });
  const a = new google.maps.Map(documento.createElement('div'), { center: CENTRO, zoom: 19 });
  const b = new google.maps.Map(documento.createElement('div'), { center: CENTRO, zoom: 19 });

  const primeiro = limitarZoomDepoisDeEnquadrar(google, a, 18);
  expect(typeof primeiro.remove).toBe('function');
  limitarZoomDepoisDeEnquadrar(google, a, 17);
  limitarZoomDepoisDeEnquadrar(google, b, 18);
  expect(a.ouvintes('idle')).toBe(1);
  expect(b.ouvintes('idle')).toBe(1);

  a.fire('idle');
  expect(a.getZoom()).toBe(17);
  expect(a.ouvintes('idle')).toBe(0);
  b.fire('idle');
  expect(b.getZoom()).toBe(18);

  // Depois de disparar, pode armar-se outra vez; o ouvinte velho já não tira o novo.
  limitarZoomDepoisDeEnquadrar(google, a, 15);
  primeiro.remove();
  expect(a.ouvintes('idle')).toBe(1);
  a.fire('idle');
  expect(a.getZoom()).toBe(15);
});

// --- Destruir ------------------------------------------------------------------------------------

test('destruir: pinos fora do mapa, ouvintes limpos, __crmMapa apagado e o elemento vazio', () => {
  const toques = ouvintesDeToque();
  const { mapa, registo, mapaGoogle, elemento } = preparar(CONFIGURACAO, { ...toques, aoEscolherLoja: () => {} });
  mapa.mostrarLojas(LOJAS);
  mapa.enquadrar(LOJAS);
  const marcadores = [...registo.marcadores];
  expect(elemento.childNodes.length).toBe(1);

  mapa.destruir();
  expect(marcadores.every((m) => m.map === null)).toBe(true);
  expect(registo.marcadores.length).toBe(0);
  expect(mapaGoogle.limpezas).toBe(1);
  expect(mapaGoogle.ouvintes('click')).toBe(0);
  expect(mapaGoogle.ouvintes('idle')).toBe(0);
  expect('__crmMapa' in elemento).toBe(false);
  // Incluindo o DOM que a Google pôs no elemento.
  expect(elemento.childNodes.length).toBe(0);
});

test('destruir tira o ouvinte do idle que ficou à espera (não depende só da limpeza da Google)', () => {
  const { google, mapa, mapaGoogle } = preparar();
  const original = google.maps.event.addListenerOnce;
  const removidos = [];
  google.maps.event.addListenerOnce = (instancia, tipo, fn) => {
    const ouvinte = original(instancia, tipo, fn);
    return {
      remove: () => {
        removidos.push(tipo);
        ouvinte.remove();
      },
    };
  };
  mapa.enquadrar(LOJAS);
  expect(mapaGoogle.ouvintes('idle')).toBe(1);
  mapa.destruir();
  expect(removidos).toEqual(['idle']);
  expect(mapaGoogle.ouvintes('idle')).toBe(0);
});

test('um segundo criarMapa no mesmo elemento funciona (o StrictMode monta o mapa duas vezes)', () => {
  const { google, registo, elemento, mapa } = preparar(CONFIGURACAO, {}, { jsdom: true });
  mapa.mostrarLojas(LOJAS);
  expect(elemento.querySelectorAll('.pino')).toHaveLength(3);
  mapa.destruir();
  expect(elemento.childElementCount).toBe(0);

  const outro = criarMapa({ google, documento: document, elemento, configuracao: CONFIGURACAO });
  outro.mostrarLojas(LOJAS);
  expect(registo.mapas.length).toBe(2);
  expect(elemento.childElementCount).toBe(1);
  expect(elemento.__crmMapa).toBe(registo.mapas[1]);
  expect(elemento.querySelectorAll('.pino')).toHaveLength(3);
});

test('destruir duas vezes não mexe no mapa novo do mesmo elemento; depois de destruir, nada mexe', () => {
  const { google, registo, elemento, mapa, documento, mapaGoogle } = preparar();
  mapa.destruir();
  const outro = criarMapa({ google, documento, elemento, configuracao: CONFIGURACAO });
  outro.mostrarLojas(LOJAS);
  mapa.destruir();
  expect(elemento.childNodes.length).toBe(1);
  expect(elemento.__crmMapa).toBe(registo.mapas[1]);
  expect(registo.marcadores.length).toBe(3);
  expect(mapaGoogle.limpezas).toBe(1);

  mapa.mostrarLojas(LOJAS);
  mapa.enquadrar(LOJAS);
  mapa.centrarEm(LOJAS[0], ZOOM_LOJA);
  expect(registo.marcadores.length).toBe(3);
  expect(mapaGoogle.vistas).toEqual([]);
  expect(mapaGoogle.ouvintes('idle')).toBe(0);
});

// --- pontoDe: o LatLng da Google ou um literal ----------------------------------------------------

test('pontoDe aceita um literal numérico ou um LatLng (lat() e lng() em função) e devolve só {lat, lng}', () => {
  const { google } = googleFalso({ documento: documentoFalso() });
  expect(pontoDe({ lat: 38.7, lng: -9.1 })).toStrictEqual({ lat: 38.7, lng: -9.1 });
  expect(pontoDe({ lat: 38.7, lng: -9.1, extra: 'x' })).toStrictEqual({ lat: 38.7, lng: -9.1 });
  expect(pontoDe(new google.maps.LatLng(38.7, -9.1))).toStrictEqual({ lat: 38.7, lng: -9.1 });
  expect(pontoDe(eventoDeToque({ lat: 38.71, lng: -9.14 }).latLng)).toStrictEqual({ lat: 38.71, lng: -9.14 });
});

test('pontoDe devolve null para o resto (o par do Leaflet incluído)', () => {
  for (const valor of [
    null,
    undefined,
    '38.7,-9.1',
    38.7,
    [38.7, -9.1],
    {},
    { lat: 38.7 },
    { lat: '38.7', lng: -9.1 },
    { lat: Number.NaN, lng: -9.1 },
    { lat: 38.7, lng: Infinity },
    { lat: () => '38.7', lng: () => -9.1 },
    { lat: () => 38.7, lng: -9.1 },
    { lat: () => Number.NaN, lng: () => -9.1 },
  ]) {
    expect(pontoDe(valor)).toBeNull();
  }
});

// --- O centro padrão é o do servidor -------------------------------------------------------------

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
