/**
 * O MAPA DAS LOJAS sobre o Google Maps — pinos por fase com o nome sempre
 * visível, escolher uma loja, tocar no mapa ou num negócio, enquadrar,
 * centrar e destruir.
 *
 * Reescrito na G6 do plano do mapa Google sobre o `googleFalso` (G5) e o
 * `domFalso`: ficam os testes dos pinos, dos nomes, de escolher, de tocar, de
 * enquadrar, de centrar, de destruir e do centro padrão, adaptados; saem os das
 * imagens do mapa antigo, da atribuição e da troca para o mapa alternativo (a
 * atribuição é a da própria Google) e os da biblioteca antiga a correr no
 * jsdom; entram os novos: as opções
 * exatas do `Map`, a configuração `{google: {chave, map_id}}`, o toque num
 * negócio (o balão é o da Google: o código nunca chama `stop()` nem cria um
 * balão seu), o limite do zoom depois de enquadrar num `idle` único, o
 * `focar()`, o `__crmMapa` (regra 16) e o `pontoDe`.
 *
 * Na F3 (T3.33, com as correções do mapa Google do plano da F3) entra a rota do planeador: o `mostrarRota`
 * com os pinos numerados das paragens (o número em texto no `content` do `el()`), os extremos ("Início",
 * "Fim" ou um só "Início e fim: fábrica"), a linha (`google.maps.Polyline` com as opções exatas, a cheia e a
 * tracejada das horas velhas) e o `enquadrarRota`.
 *
 * O Jest do CRA corre com `resetMocks`: o falso cria-se dentro de cada teste.
 */
import fs from 'fs';
import path from 'path';

import {
  criarMapa, configuracaoValida, pontoDe, limitarZoomDepoisDeEnquadrar,
  ZOOM_MINIMO, ZOOM_MAXIMO, ZOOM_SEM_LOJAS, ZOOM_MAXIMO_ENQUADRAR, ZOOM_LOJA, CENTRO_PADRAO, MARGEM_ENQUADRAR,
  MENSAGEM_SEM_MAPA, MENSAGEM_MAPA_NAO_CONFIGURADO,
  ZINDEX_PARAGEM, ZINDEX_EXTREMO, TEXTO_INICIO, TEXTO_FIM, TEXTO_INICIO_E_FIM, TEXTO_INICIO_E_FIM_FABRICA,
  COR_LINHA_ROTA,
} from './mapa';
import { FASES } from './fases';
import { TEXTOS_AVISO } from './rota';
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

test('o objeto do mapa tem só a interface dos ecrãs (sem a atribuição nem as imagens do mapa antigo)', () => {
  const { mapa } = preparar();
  expect(Object.keys(mapa).sort()).toEqual(
    ['centrarEm', 'destruir', 'enquadrar', 'enquadrarRota', 'focar', 'mapa', 'mostrarLojas', 'mostrarRota', 'redimensionar'],
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
    // A forma antiga do GET /config (antes da G2: as imagens do mapa da Geoapify e a alternativa). A chave
    // escreve-se por partes para o inventário do §5 do plano (G19) só apanhar código que ainda a use.
    {
      [['mosai', 'cos'].join('')]: { url: 'http://x/{z}/{x}/{y}.png', atribuicao: 'geoapify' },
      alternativa: { url: 'http://y' },
      centro: CENTRO,
    },
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
  // A posição vai como literal {lat, lng} (nunca como um par [lat, lng]).
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

test('destruir não rebenta quando a Google recusou a chave e tirar um pino do mapa lança erro', () => {
  // Visto em produção (2026-10-22): com RefererNotAllowedMapError, `marcador.map = null` lança
  // "Cannot read properties of undefined (reading 'getRootNode')" e a página inteira do CRM fechava.
  const { mapa, registo, mapaGoogle, elemento } = preparar(CONFIGURACAO, ouvintesDeToque());
  mapa.mostrarLojas(LOJAS);
  for (const marcador of registo.marcadores) {
    Object.defineProperty(marcador, 'map', {
      configurable: true,
      get: () => mapaGoogle,
      set: () => { throw new TypeError("Cannot read properties of undefined (reading 'getRootNode')"); },
    });
  }
  expect(() => mapa.destruir()).not.toThrow();
  expect(mapaGoogle.limpezas).toBe(1);
  expect('__crmMapa' in elemento).toBe(false);
  expect(elemento.childNodes.length).toBe(0);
});

test('mostrarLojas não rebenta quando tirar os pinos antigos lança erro (mapa recusado pela Google)', () => {
  const { mapa, registo, mapaGoogle } = preparar(CONFIGURACAO, ouvintesDeToque());
  mapa.mostrarLojas(LOJAS);
  for (const marcador of registo.marcadores) {
    Object.defineProperty(marcador, 'map', {
      configurable: true,
      get: () => mapaGoogle,
      set: () => { throw new TypeError('mapa recusado'); },
    });
  }
  expect(() => mapa.mostrarLojas(LOJAS)).not.toThrow();
});

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

// --- A rota do planeador (F3, T3.33) --------------------------------------------------------------

const PARAGEM_1 = '1f0e2d3c-4b5a-4968-8776-655443322110';
const PARAGEM_2 = '2a1b0c9d-8e7f-4a6b-9c5d-4e3f2a1b0c9d';
const PARAGEM_3 = '3b2c1d0e-9f8a-4b7c-8d6e-5f4a3b2c1d0e';
const FABRICA = { lat: 38.7369, lng: -9.1427, fabrica: true };

// O `vista.mapa` do planeador (lib/crm/planeador.js, T3.31): os pinos pela ordem da rota (só os da secção
// "rota" têm número; a fechada neste dia vem com `numero: null`), o aviso já em texto, as pontas com o
// `fabrica` e a linha em pares [lat, lng] (o descodificarPolilinha da T3.26).
function rotaDoPlaneador(mudancas = {}) {
  return {
    paragens: [
      { id: PARAGEM_1, numero: 1, nome: 'Café X', fase: 'cliente', lat: 38.7108, lng: -9.1369, aviso: null, seccao: 'rota' },
      {
        id: PARAGEM_2, numero: 2, nome: 'Mercearia da Sé', fase: 'potencial', lat: 38.7135, lng: -9.1458,
        aviso: TEXTOS_AVISO.fora_de_horario, seccao: 'rota',
      },
      {
        id: PARAGEM_3, numero: null, nome: 'Quiosque Fechado', fase: 'contactada', lat: 38.74, lng: -9.16,
        aviso: TEXTOS_AVISO.fechada_neste_dia, seccao: 'fechada',
      },
    ],
    inicio: { ...FABRICA },
    fim: { ...FABRICA },
    linha: [[38.7369, -9.1427], [38.7108, -9.1369], [38.7135, -9.1458], [38.7369, -9.1427]],
    linhaAtual: true,
    lojasForaDaRota: [],
    ...mudancas,
  };
}

// O `className` (o DOM falso e o jsdom têm-no os dois).
const temClasse = (classe) => (marcador) => conteudoDe(marcador).className.split(/\s+/).includes(classe);
const pinosDasParagens = (registo) => registo.marcadores.filter(temClasse('pino-paragem'));
const pinosDosExtremos = (registo) => registo.marcadores.filter(temClasse('pino-extremo'));
const filhosDe = (marcador) => Array.from(conteudoDe(marcador).children);

const OPCOES_LINHA_ATUAL = {
  strokeColor: '#6b2fa3', strokeWeight: 4, strokeOpacity: 0.9, clickable: false,
};
const OPCOES_LINHA_ANTIGA = {
  strokeColor: '#6b2fa3',
  strokeWeight: 4,
  strokeOpacity: 0,
  icons: [{ icon: { path: 'M 0,-1 0,1', strokeOpacity: 0.6, scale: 3 }, offset: '0', repeat: '14px' }],
  clickable: false,
};
const CAMINHO = [
  { lat: 38.7369, lng: -9.1427 },
  { lat: 38.7108, lng: -9.1369 },
  { lat: 38.7135, lng: -9.1458 },
  { lat: 38.7369, lng: -9.1427 },
];

test('os textos, as cores e as camadas da rota', () => {
  expect(TEXTO_INICIO).toBe('Início');
  expect(TEXTO_FIM).toBe('Fim');
  expect(TEXTO_INICIO_E_FIM).toBe('Início e fim');
  expect(TEXTO_INICIO_E_FIM_FABRICA).toBe('Início e fim: fábrica');
  // O roxo da linha é o do cliente (o da marca).
  expect(COR_LINHA_ROTA).toBe('#6b2fa3');
  expect(COR_LINHA_ROTA).toBe(FASES.cliente.cor);
  // Por cima dos pinos das lojas (sem zIndex: a Google ordena-os pela altura no ecrã, até ao MAX_ZINDEX de
  // 1000000 dos marcadores antigos); as paragens por cima dos extremos.
  expect(ZINDEX_EXTREMO).toBeGreaterThan(1000000);
  expect(ZINDEX_PARAGEM).toBeGreaterThan(ZINDEX_EXTREMO);
  expect(Number.isInteger(ZINDEX_PARAGEM) && Number.isInteger(ZINDEX_EXTREMO)).toBe(true);
});

test('mostrarRota: um pino por paragem com coordenadas, pela ordem da rota, e o dos extremos no fim', () => {
  const { mapa, registo, mapaGoogle } = preparar();
  mapa.mostrarRota(rotaDoPlaneador());
  expect(registo.marcadores.length).toBe(4);
  expect(registo.marcadores.every((m) => m.map === mapaGoogle)).toBe(true);
  expect(registo.marcadores.map((m) => m.posicao())).toEqual([
    { lat: 38.7108, lng: -9.1369 },
    { lat: 38.7135, lng: -9.1458 },
    { lat: 38.74, lng: -9.16 },
    { lat: 38.7369, lng: -9.1427 },
  ]);
  expect(pinosDasParagens(registo)).toEqual(registo.marcadores.slice(0, 3));
  expect(pinosDosExtremos(registo)).toEqual(registo.marcadores.slice(3));
  // A posição vai como literal {lat, lng}, só com as coordenadas (sem o resto da paragem nem o `fabrica`).
  expect(registo.marcadores[0].options.position).toStrictEqual({ lat: 38.7108, lng: -9.1369 });
  expect(registo.marcadores[3].options.position).toStrictEqual({ lat: 38.7369, lng: -9.1427 });
});

test('o pino de uma paragem: "N. Nome" como título, recebe toques, nunca se esconde e fica por cima das lojas', () => {
  const { google, mapa, registo } = preparar();
  mapa.mostrarLojas(LOJAS);
  mapa.mostrarRota(rotaDoPlaneador());
  const [primeira] = pinosDasParagens(registo);
  expect(primeira.title).toBe('1. Café X');
  expect(primeira.gmpClickable).toBe(true);
  expect(primeira.gmpDraggable).toBe(false);
  expect(primeira.collisionBehavior).toBe(google.maps.CollisionBehavior.REQUIRED);
  expect(primeira.zIndex).toBe(ZINDEX_PARAGEM);
  expect(Object.keys(primeira.options).sort()).toEqual(
    ['collisionBehavior', 'content', 'gmpClickable', 'map', 'position', 'title', 'zIndex'],
  );
  // Os pinos das lojas continuam sem zIndex (por baixo).
  expect(registo.marcadores.filter(temClasse('pino')).map((m) => m.zIndex)).toEqual([undefined, undefined, undefined]);
});

test('o título leva o aviso, e uma paragem sem número (fechada, não cabe) só o nome', () => {
  const { mapa, registo } = preparar();
  mapa.mostrarRota(rotaDoPlaneador());
  expect(pinosDasParagens(registo).map((m) => m.title)).toEqual([
    '1. Café X',
    '2. Mercearia da Sé — ⚠️ Fora do horário de receção',
    'Quiosque Fechado — ⚠️ Fechada neste dia',
  ]);
});

test('o conteúdo do pino: a div da paragem na cor da fase, o número em texto e a etiqueta com o nome', () => {
  const { mapa, registo } = preparar();
  mapa.mostrarRota(rotaDoPlaneador());
  const [primeira, segunda, terceira] = pinosDasParagens(registo);

  expect(conteudoDe(primeira).tagName).toBe('DIV');
  expect(conteudoDe(primeira).className).toBe('pino-paragem pino--cliente');
  expect(filhosDe(primeira).map((no) => no.tagName)).toEqual(['SPAN', 'SPAN']);
  expect(filhosDe(primeira).map((no) => no.className)).toEqual(['pino-paragem__numero', 'etiqueta-loja']);
  expect(filhosDe(primeira).map((no) => no.textContent)).toEqual(['1', 'Café X']);
  // O número é um nó de texto (nada de elementos lá dentro).
  expect(filhosDe(primeira)[0].children.length).toBe(0);

  // Com aviso: a classe do aviso.
  expect(conteudoDe(segunda).className).toBe('pino-paragem pino--potencial pino-paragem--aviso');
  expect(filhosDe(segunda).map((no) => no.textContent)).toEqual(['2', 'Mercearia da Sé']);

  // Sem número (fechada neste dia): sem o número no conteúdo, só a etiqueta.
  expect(conteudoDe(terceira).className).toBe('pino-paragem pino--contactada pino-paragem--aviso pino-paragem--sem-numero');
  expect(filhosDe(terceira).map((no) => [no.className, no.textContent])).toEqual([['etiqueta-loja', 'Quiosque Fechado']]);
});

test('os pinos da rota nunca têm a classe "pino" (a das lojas, esbatida no planeador)', () => {
  const { mapa, registo } = preparar();
  mapa.mostrarRota(rotaDoPlaneador());
  expect(registo.marcadores.length).toBe(4);
  expect(registo.marcadores.some(temClasse('pino'))).toBe(false);
});

test('uma fase desconhecida (ou sem fase): só "pino-paragem", sem classe de fase', () => {
  const { mapa, registo } = preparar();
  const base = rotaDoPlaneador().paragens[0];
  mapa.mostrarRota(rotaDoPlaneador({ paragens: [{ ...base, fase: 'xpto' }, { ...base, fase: null }, { ...base, fase: 'constructor' }] }));
  expect(pinosDasParagens(registo).map((m) => conteudoDe(m).className)).toEqual(['pino-paragem', 'pino-paragem', 'pino-paragem']);
});

test('um número que não é inteiro conta como sem número; um aviso vazio não é aviso', () => {
  const { mapa, registo } = preparar();
  const base = rotaDoPlaneador().paragens[0];
  mapa.mostrarRota(rotaDoPlaneador({
    paragens: [
      { ...base, numero: '3' },
      { ...base, numero: 2.5 },
      { ...base, numero: 7, aviso: '' },
      { ...base, numero: 8, aviso: undefined },
      { ...base, numero: 9, aviso: '   ' },
    ],
  }));
  const pinos = pinosDasParagens(registo);
  expect(pinos.map((m) => m.title)).toEqual(['Café X', 'Café X', '7. Café X', '8. Café X', '9. Café X']);
  expect(pinos.map((m) => conteudoDe(m).className)).toEqual([
    'pino-paragem pino--cliente pino-paragem--sem-numero',
    'pino-paragem pino--cliente pino-paragem--sem-numero',
    'pino-paragem pino--cliente',
    'pino-paragem pino--cliente',
    'pino-paragem pino--cliente',
  ]);
  expect(pinos.map((m) => filhosDe(m).length)).toEqual([1, 1, 2, 2, 2]);
});

test('o nome (e o aviso) de uma paragem com HTML fica texto na etiqueta e no título (DOM falso)', () => {
  const { mapa, registo } = preparar();
  const base = rotaDoPlaneador().paragens[0];
  mapa.mostrarRota(rotaDoPlaneador({ paragens: [{ ...base, nome: '<b>x</b>', aviso: '<i>a</i>' }] }));
  const [pino] = pinosDasParagens(registo);
  const [numeroNo, etiqueta] = filhosDe(pino);
  expect(numeroNo.textContent).toBe('1');
  expect(etiqueta.textContent).toBe('<b>x</b>');
  expect(etiqueta.children.length).toBe(0);
  expect(pino.title).toBe('1. <b>x</b> — <i>a</i>');
});

test('com o document do browser (jsdom), o número e o nome são texto: nenhum <b> nem <img> no mapa', () => {
  const { mapa, registo, elemento } = preparar(CONFIGURACAO, {}, { jsdom: true });
  const base = rotaDoPlaneador().paragens[0];
  mapa.mostrarRota(rotaDoPlaneador({ paragens: [{ ...base, nome: '<img src=x onerror=alert(1)><b>x</b>' }] }));
  const conteudo = conteudoDe(pinosDasParagens(registo)[0]);
  expect(conteudo).toBeInstanceOf(HTMLDivElement);
  expect(conteudo.querySelector('.pino-paragem__numero').textContent).toBe('1');
  expect(conteudo.querySelector('.etiqueta-loja').textContent).toBe('<img src=x onerror=alert(1)><b>x</b>');
  expect(conteudo.querySelector('b')).toBeNull();
  expect(conteudo.querySelector('img')).toBeNull();
  // Os pinos estão no DOM do mapa (o falso põe lá o conteúdo dos marcadores que têm map).
  expect(elemento.querySelectorAll('.pino-paragem')).toHaveLength(1);
  expect(elemento.querySelectorAll('.pino-extremo')).toHaveLength(1);
  expect(elemento.querySelector('b')).toBeNull();
});

test('um nome que não é texto: a etiqueta e o título ficam sem ele (sem "null" nem "undefined")', () => {
  const { mapa, registo } = preparar();
  const base = rotaDoPlaneador().paragens[0];
  mapa.mostrarRota(rotaDoPlaneador({
    paragens: [{ ...base, nome: null }, { ...base, nome: undefined, numero: null }, { ...base, nome: 42, numero: 5 }],
  }));
  const pinos = pinosDasParagens(registo);
  expect(pinos.map((m) => m.title)).toEqual(['1. ', '', '5. ']);
  expect(pinos.map((m) => filhosDe(m).slice(-1)[0].textContent)).toEqual(['', '', '']);
});

test('tocar num pino de paragem (gmp-click, rato ou Enter/Espaço com o foco) escolhe a paragem', () => {
  const escolhidas = [];
  const { mapa, registo } = preparar();
  const rota = rotaDoPlaneador();
  mapa.mostrarRota(rota, { aoEscolherParagem: (paragem, marcador) => escolhidas.push({ paragem, marcador }) });
  const pinos = pinosDasParagens(registo);
  pinos[2].tocar();
  pinos[0].tocar();
  expect(escolhidas.map((e) => e.paragem)).toEqual([rota.paragens[2], rota.paragens[0]]);
  // A própria paragem do planeador (a mesma referência) e o marcador dela.
  expect(escolhidas[0].paragem).toBe(rota.paragens[2]);
  expect(escolhidas[0].marcador).toBe(pinos[2]);
  expect(escolhidas[1].marcador).toBe(pinos[0]);
  expect(registo.infoWindowsNossas).toBe(0);
});

test('sem aoEscolherParagem (ou sem opções), os pinos das paragens não ficam à escuta de toques', () => {
  for (const opcoes of [undefined, null, {}, { aoEscolherParagem: 'x' }]) {
    const { mapa, registo } = preparar();
    mapa.mostrarRota(rotaDoPlaneador(), opcoes);
    const pinos = pinosDasParagens(registo);
    expect(pinos.length).toBe(3);
    expect(pinos.map((m) => m.ouvintes('gmp-click'))).toEqual([0, 0, 0]);
    pinos[0].tocar();
  }
});

test('tocar num pino de paragem não chega ao mapa nem ao cartão das lojas', () => {
  const lojas = [];
  const toques = ouvintesDeToque();
  const { mapa, registo } = preparar(CONFIGURACAO, { ...toques, aoEscolherLoja: (loja) => lojas.push(loja) });
  const paragens = [];
  mapa.mostrarRota(rotaDoPlaneador(), { aoEscolherParagem: (paragem) => paragens.push(paragem.id) });
  pinosDasParagens(registo)[1].tocar();
  expect(paragens).toEqual([PARAGEM_2]);
  expect(lojas).toEqual([]);
  expect(toques.pontos).toEqual([]);
});

test('paragens sem coordenadas válidas (ou que não são objetos) ficam de fora', () => {
  const { mapa, registo } = preparar();
  const base = rotaDoPlaneador().paragens[0];
  mapa.mostrarRota(rotaDoPlaneador({
    paragens: [
      { ...base, lat: null },
      { ...base, lng: '' },
      { ...base, lat: Number.NaN },
      { ...base, lng: Infinity },
      { ...base, lat: '38.7' },
      null,
      'x',
      { ...base, numero: 4, nome: 'Fica' },
    ],
  }));
  expect(pinosDasParagens(registo).map((m) => m.title)).toEqual(['4. Fica']);
});

test('paragens que não são uma lista: nenhum pino de paragem (os extremos aparecem na mesma)', () => {
  for (const paragens of [undefined, null, {}, 'x']) {
    const { mapa, registo } = preparar();
    mapa.mostrarRota(rotaDoPlaneador({ paragens }));
    expect(pinosDasParagens(registo)).toEqual([]);
    expect(pinosDosExtremos(registo).length).toBe(1);
  }
});

// --- Os extremos ---

test('início e fim no mesmo ponto da fábrica: um só pino "Início e fim: fábrica"', () => {
  const { google, mapa, registo } = preparar();
  mapa.mostrarRota(rotaDoPlaneador());
  const extremos = pinosDosExtremos(registo);
  expect(extremos.length).toBe(1);
  const [extremo] = extremos;
  expect(extremo.title).toBe('Início e fim: fábrica');
  expect(extremo.posicao()).toStrictEqual({ lat: 38.7369, lng: -9.1427 });
  expect(conteudoDe(extremo).className).toBe('pino-extremo');
  expect(filhosDe(extremo).map((no) => [no.tagName, no.className, no.textContent])).toEqual([
    ['SPAN', 'pino-extremo__marca', ''],
    ['SPAN', 'etiqueta-loja', 'Início e fim: fábrica'],
  ]);
  // Não se escolhe (não recebe toques), nunca se esconde e fica por cima das lojas, por baixo das paragens.
  expect(extremo.gmpClickable).toBe(false);
  expect(extremo.collisionBehavior).toBe(google.maps.CollisionBehavior.REQUIRED);
  expect(extremo.zIndex).toBe(ZINDEX_EXTREMO);
  expect(Object.keys(extremo.options).sort()).toEqual(['collisionBehavior', 'content', 'map', 'position', 'title', 'zIndex']);
});

test('início e fim no mesmo ponto que não é a fábrica (ou só um deles é): "Início e fim"', () => {
  const ponto = { lat: 38.75, lng: -9.2 };
  for (const [inicio, fim] of [
    [{ ...ponto, fabrica: false }, { ...ponto, fabrica: false }],
    [{ ...ponto, fabrica: true }, { ...ponto, fabrica: false }],
    [{ ...ponto, fabrica: false }, { ...ponto, fabrica: true }],
    [{ ...ponto }, { ...ponto, fabrica: true }],
    [{ ...ponto, fabrica: 'sim' }, { ...ponto, fabrica: true }],
  ]) {
    const { mapa, registo } = preparar();
    mapa.mostrarRota(rotaDoPlaneador({ inicio, fim }));
    expect(pinosDosExtremos(registo).map((m) => m.title)).toEqual(['Início e fim']);
    expect(pinosDosExtremos(registo)[0].posicao()).toStrictEqual(ponto);
  }
});

test('início e fim em pontos diferentes: o pino "Início" e o pino "Fim", por esta ordem', () => {
  const { mapa, registo } = preparar();
  mapa.mostrarRota(rotaDoPlaneador({ fim: { lat: 38.7, lng: -9.3, fabrica: false } }));
  const extremos = pinosDosExtremos(registo);
  expect(extremos.map((m) => m.title)).toEqual(['Início', 'Fim']);
  expect(extremos.map((m) => m.posicao())).toEqual([{ lat: 38.7369, lng: -9.1427 }, { lat: 38.7, lng: -9.3 }]);
  expect(extremos.map((m) => filhosDe(m)[1].textContent)).toEqual(['Início', 'Fim']);
  // Só a latitude ou só a longitude diferentes também são pontos diferentes.
  for (const fim of [{ lat: 38.7369, lng: -9.3 }, { lat: 38.7, lng: -9.1427 }]) {
    const outro = preparar();
    outro.mapa.mostrarRota(rotaDoPlaneador({ fim }));
    expect(pinosDosExtremos(outro.registo).map((m) => m.title)).toEqual(['Início', 'Fim']);
  }
});

test('um extremo sem coordenadas não tem pino; o outro aparece sozinho com o seu nome', () => {
  for (const sem of [null, undefined, {}, { lat: 38.7 }, { lat: '38.7', lng: -9.1 }, { lat: Number.NaN, lng: -9.1 }]) {
    const a = preparar();
    a.mapa.mostrarRota(rotaDoPlaneador({ fim: sem }));
    expect(pinosDosExtremos(a.registo).map((m) => m.title)).toEqual(['Início']);
    const b = preparar();
    b.mapa.mostrarRota(rotaDoPlaneador({ inicio: sem }));
    expect(pinosDosExtremos(b.registo).map((m) => m.title)).toEqual(['Fim']);
  }
  const c = preparar();
  c.mapa.mostrarRota(rotaDoPlaneador({ inicio: null, fim: null }));
  expect(pinosDosExtremos(c.registo)).toEqual([]);
  expect(pinosDasParagens(c.registo).length).toBe(3);
});

// --- A linha ---

test('a linha das horas atuais: uma Polyline cheia, com as opções exatas e o caminho em literais {lat, lng}', () => {
  const { mapa, registo, mapaGoogle } = preparar();
  mapa.mostrarRota(rotaDoPlaneador());
  expect(registo.linhas.length).toBe(1);
  const [linha] = registo.linhas;
  expect(linha.getMap()).toBe(mapaGoogle);
  expect(linha.options).toStrictEqual({ path: CAMINHO, ...OPCOES_LINHA_ATUAL, map: mapaGoogle });
  expect(linha.getPath()).toStrictEqual(CAMINHO);
});

test('a linha das horas velhas (linhaAtual que não é true): tracejada, com o traço só nos ícones', () => {
  for (const linhaAtual of [false, undefined, null, 'true', 1]) {
    const { mapa, registo, mapaGoogle } = preparar();
    mapa.mostrarRota(rotaDoPlaneador({ linhaAtual }));
    expect(registo.linhas.length).toBe(1);
    expect(registo.linhas[0].options).toStrictEqual({ path: CAMINHO, ...OPCOES_LINHA_ANTIGA, map: mapaGoogle });
  }
});

test('a linha só com 2 pontos ou mais; sem linha, vazia ou estragada não há linha (os pinos aparecem)', () => {
  for (const linha of [[], [[38.7, -9.1]], undefined, null, 'x', {}, [[38.7, -9.1], [38.71]], [[38.7, -9.1], null],
    [[38.7, -9.1], ['38.71', -9.12]], [[38.7, -9.1], [38.71, Number.NaN]], [[38.7, -9.1], { lat: 38.71, lng: -9.12 }],
    [[38.7, -9.1], [38.71, -9.12, 0]],
    // Um par estragado deita fora a linha toda (não se salta: a linha passava a cortar caminho).
    [[38.7, -9.1], [38.71, -9.12], [38.72]], [[38.7, -9.1], null, [38.71, -9.12]]]) {
    const { mapa, registo } = preparar();
    mapa.mostrarRota(rotaDoPlaneador({ linha }));
    expect(registo.linhas).toEqual([]);
    expect(registo.marcadores.length).toBe(4);
  }
  const { mapa, registo } = preparar();
  mapa.mostrarRota(rotaDoPlaneador({ linha: [[38.7, -9.1], [38.71, -9.12]] }));
  expect(registo.linhas[0].getPath()).toStrictEqual([{ lat: 38.7, lng: -9.1 }, { lat: 38.71, lng: -9.12 }]);
});

test('a linha da vista congelada do planeador lê-se sem a mudar', () => {
  const { mapa, registo } = preparar();
  const linha = Object.freeze(CAMINHO.map(({ lat, lng }) => Object.freeze([lat, lng])));
  mapa.mostrarRota(Object.freeze(rotaDoPlaneador({ linha })));
  expect(registo.linhas[0].getPath()).toStrictEqual(CAMINHO);
  expect(linha[0]).toEqual([38.7369, -9.1427]);
});

// --- Substituir, limpar e as lojas ---

test('uma rota nova substitui a anterior: os pinos e a linha antigos saem do mapa', () => {
  const { mapa, registo } = preparar();
  mapa.mostrarRota(rotaDoPlaneador());
  const pinosAntigos = [...registo.marcadores];
  const [linhaAntiga] = registo.linhas;
  const base = rotaDoPlaneador().paragens[0];
  mapa.mostrarRota(rotaDoPlaneador({ paragens: [{ ...base, nome: 'Nova' }], linha: [[38.7, -9.1], [38.71, -9.12]], linhaAtual: false }));
  expect(pinosAntigos.every((m) => m.map === null)).toBe(true);
  expect(linhaAntiga.getMap()).toBeNull();
  expect(registo.marcadores.length).toBe(2);
  expect(pinosDasParagens(registo).map((m) => m.title)).toEqual(['1. Nova']);
  expect(registo.linhas.length).toBe(1);
  expect(registo.linhas[0]).not.toBe(linhaAntiga);
  expect(registo.linhas[0].options.strokeOpacity).toBe(0);
});

test('uma rota sem linha tira a linha anterior; mostrarRota(null) tira tudo da rota', () => {
  const { mapa, registo } = preparar();
  mapa.mostrarRota(rotaDoPlaneador());
  mapa.mostrarRota(rotaDoPlaneador({ linha: [] }));
  expect(registo.linhas).toEqual([]);
  expect(registo.marcadores.length).toBe(4);
  for (const vazia of [null, undefined, 'x']) {
    mapa.mostrarRota(rotaDoPlaneador());
    mapa.mostrarRota(vazia);
    expect(registo.marcadores).toEqual([]);
    expect(registo.linhas).toEqual([]);
  }
});

test('as lojas e a rota são grupos à parte: mostrar uma não tira a outra', () => {
  const { mapa, registo } = preparar();
  mapa.mostrarLojas(LOJAS);
  mapa.mostrarRota(rotaDoPlaneador());
  expect(registo.marcadores.length).toBe(7);
  mapa.mostrarLojas([LOJAS[0]]);
  expect(pinosDasParagens(registo).length).toBe(3);
  expect(pinosDosExtremos(registo).length).toBe(1);
  expect(registo.linhas.length).toBe(1);
  mapa.mostrarRota(null);
  expect(registo.marcadores.filter(temClasse('pino')).length).toBe(1);
  mapa.mostrarLojas([]);
  mapa.mostrarRota(rotaDoPlaneador());
  expect(registo.marcadores.length).toBe(4);
});

test('mostrarRota não rebenta quando tirar a rota anterior lança erro (mapa recusado pela Google)', () => {
  const { mapa, registo, mapaGoogle } = preparar();
  mapa.mostrarRota(rotaDoPlaneador());
  for (const marcador of registo.marcadores) {
    Object.defineProperty(marcador, 'map', {
      configurable: true,
      get: () => mapaGoogle,
      set: () => { throw new TypeError('mapa recusado'); },
    });
  }
  registo.linhas[0].setMap = () => { throw new TypeError('mapa recusado'); };
  expect(() => mapa.mostrarRota(rotaDoPlaneador())).not.toThrow();
  expect(() => mapa.mostrarRota(null)).not.toThrow();
});

// --- Enquadrar a rota ---

test('enquadrarRota: fitBounds das paragens e dos extremos, com a margem de 40 px e o limite do zoom 16', () => {
  const { google, mapa, mapaGoogle } = preparar();
  mapa.mostrarRota(rotaDoPlaneador({ fim: { lat: 38.7, lng: -9.3, fabrica: false } }));
  mapa.enquadrarRota();
  expect(mapaGoogle.vistas.length).toBe(1);
  const [vista] = mapaGoogle.vistas;
  expect(vista.tipo).toBe('fitBounds');
  expect(vista.limites).toBeInstanceOf(google.maps.LatLngBounds);
  expect(vista.limites.pontos).toStrictEqual([
    { lat: 38.7108, lng: -9.1369 },
    { lat: 38.7135, lng: -9.1458 },
    { lat: 38.74, lng: -9.16 },
    { lat: 38.7369, lng: -9.1427 },
    { lat: 38.7, lng: -9.3 },
  ]);
  expect(vista.margem).toBe(MARGEM_ENQUADRAR);
  expect(mapaGoogle.ouvintes('idle')).toBe(1);
  mapaGoogle.setZoom(18);
  mapaGoogle.fire('idle');
  expect(mapaGoogle.getZoom()).toBe(ZOOM_MAXIMO_ENQUADRAR);
});

test('enquadrarRota com os extremos iguais: o ponto da fábrica entra uma vez; sem paragens, só os extremos', () => {
  const { mapa, mapaGoogle } = preparar();
  mapa.mostrarRota(rotaDoPlaneador());
  mapa.enquadrarRota();
  expect(mapaGoogle.vistas[0].limites.pontos.slice(-1)).toStrictEqual([{ lat: 38.7369, lng: -9.1427 }]);
  expect(mapaGoogle.vistas[0].limites.pontos.length).toBe(4);
  mapa.mostrarRota(rotaDoPlaneador({ paragens: [] }));
  mapa.enquadrarRota();
  expect(mapaGoogle.vistas[1].limites.pontos).toStrictEqual([{ lat: 38.7369, lng: -9.1427 }]);
});

test('enquadrarRota não conta as lojas fora da rota nem a linha', () => {
  const { mapa, mapaGoogle } = preparar();
  mapa.mostrarLojas(LOJAS);
  mapa.mostrarRota(rotaDoPlaneador({ paragens: [], linha: [[39, -8], [37, -10]] }));
  mapa.enquadrarRota();
  expect(mapaGoogle.vistas[0].limites.pontos).toStrictEqual([{ lat: 38.7369, lng: -9.1427 }]);
});

test('enquadrarRota sem rota (ou sem nenhum ponto): o centro das definições no zoom 12', () => {
  const casos = [
    (mapa) => mapa,
    (mapa) => mapa.mostrarRota(null),
    (mapa) => mapa.mostrarRota(rotaDoPlaneador({ paragens: [], inicio: null, fim: null })),
    (mapa) => {
      mapa.mostrarRota(rotaDoPlaneador());
      mapa.mostrarRota(null);
    },
  ];
  for (const preparo of casos) {
    const { mapa, mapaGoogle } = preparar();
    preparo(mapa);
    mapa.enquadrarRota();
    expect(mapaGoogle.vistas).toStrictEqual([
      { tipo: 'setCenter', centro: CENTRO },
      { tipo: 'setZoom', zoom: ZOOM_SEM_LOJAS },
    ]);
    expect(mapaGoogle.ouvintes('idle')).toBe(0);
  }
});

test('enquadrarRota usa a última rota mostrada', () => {
  const { mapa, mapaGoogle } = preparar();
  mapa.mostrarRota(rotaDoPlaneador());
  const base = rotaDoPlaneador().paragens[0];
  mapa.mostrarRota(rotaDoPlaneador({ paragens: [{ ...base, lat: 38.8, lng: -9.0 }], inicio: null }));
  mapa.enquadrarRota();
  expect(mapaGoogle.vistas[0].limites.pontos).toStrictEqual([{ lat: 38.8, lng: -9.0 }, { lat: 38.7369, lng: -9.1427 }]);
});

// --- Destruir com a rota ---

test('destruir tira os pinos e a linha da rota; depois disso, mostrarRota e enquadrarRota não fazem nada', () => {
  const { mapa, registo, mapaGoogle } = preparar();
  mapa.mostrarLojas(LOJAS);
  mapa.mostrarRota(rotaDoPlaneador());
  const marcadores = [...registo.marcadores];
  const [linha] = registo.linhas;
  mapa.destruir();
  expect(marcadores.every((m) => m.map === null)).toBe(true);
  expect(linha.getMap()).toBeNull();
  expect(registo.marcadores).toEqual([]);
  expect(registo.linhas).toEqual([]);

  mapa.mostrarRota(rotaDoPlaneador());
  mapa.enquadrarRota();
  expect(registo.marcadores).toEqual([]);
  expect(registo.linhas).toEqual([]);
  expect(mapaGoogle.vistas).toEqual([]);
});

test('destruir não rebenta quando tirar a linha ou os pinos da rota lança erro (mapa recusado pela Google)', () => {
  const { mapa, registo, mapaGoogle, elemento } = preparar();
  mapa.mostrarRota(rotaDoPlaneador());
  for (const marcador of registo.marcadores) {
    Object.defineProperty(marcador, 'map', {
      configurable: true,
      get: () => mapaGoogle,
      set: () => { throw new TypeError("Cannot read properties of undefined (reading 'getRootNode')"); },
    });
  }
  registo.linhas[0].setMap = () => { throw new TypeError('mapa recusado'); };
  expect(() => mapa.destruir()).not.toThrow();
  expect(mapaGoogle.limpezas).toBe(1);
  expect(elemento.childNodes.length).toBe(0);
});

// --- pontoDe: o LatLng da Google ou um literal ----------------------------------------------------

test('pontoDe aceita um literal numérico ou um LatLng (lat() e lng() em função) e devolve só {lat, lng}', () => {
  const { google } = googleFalso({ documento: documentoFalso() });
  expect(pontoDe({ lat: 38.7, lng: -9.1 })).toStrictEqual({ lat: 38.7, lng: -9.1 });
  expect(pontoDe({ lat: 38.7, lng: -9.1, extra: 'x' })).toStrictEqual({ lat: 38.7, lng: -9.1 });
  expect(pontoDe(new google.maps.LatLng(38.7, -9.1))).toStrictEqual({ lat: 38.7, lng: -9.1 });
  expect(pontoDe(eventoDeToque({ lat: 38.71, lng: -9.14 }).latLng)).toStrictEqual({ lat: 38.71, lng: -9.14 });
});

test('pontoDe devolve null para o resto (um par [lat, lng] incluído)', () => {
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
