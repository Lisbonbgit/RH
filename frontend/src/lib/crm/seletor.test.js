/**
 * O SELETOR DA LOCALIZAÇÃO sobre o Google Maps — pino arrastável, círculo da
 * precisão, "Estou nesta loja" e a regra do arrasto, sem DOM.
 *
 * Porta de tests/js/seletor-localizacao.test.js do CRM autónomo (etiqueta
 * `referencia-standalone`), sobre o `criarSeletor` de `seletor.js`, que guarda
 * as regras do componente do autónomo fora do React (plano T2.26). Reescrito
 * na G10 do plano do mapa Google sobre o `googleFalso` (G5) e o `domFalso`:
 * ficam, adaptados, os dos estados, da dica, do aviso, do erro, do Confirmar,
 * do GPS (com o `getCurrentPosition` falso), do círculo, da morada sugerida
 * pela inversa do GPS, do foco, da vista nova e congelada, de nada depois de
 * destruir, do `redimensionar`, dos textos e dos da fábrica; saem os da
 * biblioteca do mapa antigo a correr no jsdom e os da pesquisa de morada da
 * Geoapify (a G11 traz os da pesquisa e do negócio da Google); entram os da
 * regra do arrasto (um pino vindo da Google só se confirma depois de
 * arrastado, e vai como `pin_manual` com o `google_place_id`), os do
 * `AdvancedMarkerElement` (`gmpDraggable` ligado e desligado), os do
 * `google.maps.Circle` e os da configuração `{google: {chave, map_id}}`.
 *
 * O que no autónomo se via no DOM vê-se aqui na `vista`: a dica, o aviso, o
 * erro, o Confirmar ativo, o botão e a mensagem do GPS e a morada sugerida (em
 * partes: texto e ligação). O foco que o autónomo mudava (Confirmar ↔ Alterar)
 * chega ao componente pelo `aoFocar`. Em todos os testes, cada localização
 * confirmada que chega ao `aoMudar` é conferida no fim (chaves exatas e nunca
 * `origem_coords: 'google'`).
 *
 * O Jest do CRA corre com `resetMocks`: os falsos nascem em cada teste.
 */
import fs from 'fs';
import path from 'path';

import {
  criarSeletor,
  textosSeletor,
  partesMoradaSugerida,
  TEXTOS_LOJA,
  TEXTO_TOCAR_NO_MAPA,
  TEXTO_ARRASTAR,
  TEXTO_ARRASTAR_LUGAR,
  TEXTO_CONFIRMADA,
  TEXTO_CONFIRMAR,
  TEXTO_ALTERAR,
  TEXTO_ESTOU_NESTA_LOJA,
  TEXTO_A_OBTER_LOCALIZACAO,
  TEXTO_A_PROCURAR_MORADA,
  ZOOM_MORADA,
  ZOOM_GPS,
  MARGEM_GPS,
  ESTILO_CIRCULO,
} from './seletor';
import { MENSAGEM_SEM_MAPA, MENSAGEM_MAPA_NAO_CONFIGURADO, ZOOM_SEM_LOJAS } from './mapa';
import {
  MENSAGEM_LOCALIZACAO_IMPRECISA, MENSAGEM_PERMISSAO_NEGADA, OPCOES_GPS, limitesDoCirculo,
} from './gps';
import { MENSAGEM_MORADA_SUGERIDA_INDISPONIVEL } from './morada';
import { ATRIBUICOES } from './atribuicoes';
import { googleFalso, eventoDeToque } from './testes/googleFalso';
import { documentoFalso } from './testes/domFalso';

const CENTRO = { lat: 38.7223, lng: -9.1393 };
const CONFIGURACAO = { google: { chave: 'chave-teste-navegador', map_id: 'map-id-teste' }, centro: CENTRO };

// Um identificador de lugar da Google (o negócio tocado no mapa ou a morada escolhida na pesquisa).
const LUGAR = 'ChIJ-teste-lugar';

// O bloco da localização que a API recebe (localizacao.js): sempre estas chaves, por esta ordem.
const CHAVES_LOCALIZACAO = ['lat', 'lng', 'origem_coords', 'precisao_m', 'google_place_id'];

// Todas as localizações confirmadas que chegaram ao aoMudar neste teste (conferidas no afterEach).
let confirmadas = [];

function conferirConfirmadas() {
  const lista = confirmadas.filter((localizacao) => localizacao !== null);
  confirmadas = [];
  for (const localizacao of lista) {
    expect(Object.keys(localizacao)).toEqual(CHAVES_LOCALIZACAO);
    expect(['pin_manual', 'gps', 'geocoder']).toContain(localizacao.origem_coords);
    expect(localizacao.origem_coords).not.toBe('google');
  }
}

afterEach(() => {
  conferirConfirmadas();
  document.body.replaceChildren();
});

async function esvaziar() {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
}

// A api do portal (lib/crm/api.js) falsa: cada pedido fica pendente até o teste lhe responder.
function apiFalsa() {
  const pedidos = [];
  const pendente = (caminho) => (parametros) => new Promise((resolver, rejeitar) => {
    pedidos.push({ caminho, parametros, resolver, rejeitar });
  });
  return { pedidos, api: { moradaInversa: pendente('inversa') } };
}

// Geolocalização falsa (navigator.geolocation): cada pedido fica pendente até o teste lhe responder.
function geoFalso() {
  const pedidos = [];
  return {
    pedidos,
    getCurrentPosition(sucesso, falha, opcoes) {
      pedidos.push({ sucesso, falha, opcoes });
    },
  };
}

// Cria o seletor como um ecrã: a área do mapa já está na página quando se inicia.
//  - ajustarGoogle(google): o que se passa no lugar da Google falsa (sem Google: () => undefined);
//  - gps: true (a geolocalização falsa), um objeto (passado tal e qual) ou false (sem GPS);
//  - comApi: a api falsa (a morada sugerida do GPS).
function preparar({
  configuracao = CONFIGURACAO, ajustarGoogle = (google) => google, iniciar = true, inicial, textos, gps = false,
  comApi = true, documento = documentoFalso(),
} = {}) {
  const { google, registo } = googleFalso({ documento });
  const elemento = documento.createElement('div');
  documento.body.appendChild(elemento);
  const geo = gps === true ? geoFalso() : gps || undefined;
  const { pedidos, api } = apiFalsa();
  const mudancas = [];
  const focos = [];
  const vistas = [];
  const sugeridas = [];
  const seletor = criarSeletor({
    google: ajustarGoogle(google),
    documento,
    configuracao,
    textos,
    api: comApi ? api : undefined,
    geolocation: geo,
    aoMudar: (localizacao) => {
      mudancas.push(localizacao);
      confirmadas.push(localizacao);
    },
    aoSugerirMorada: (sugestao) => sugeridas.push(sugestao),
    aoFocar: (alvo) => focos.push(alvo),
    aoMudarVista: (vista) => vistas.push(vista),
  });
  const iniciado = iniciar ? seletor.iniciar(elemento, inicial === undefined ? undefined : { inicial }) : null;
  return {
    documento, elemento, google, registo, seletor, mudancas, focos, vistas, sugeridas, geo, pedidos, iniciado,
    mapa: () => registo.mapas[0],
  };
}

const tocar = (mapa, lat, lng) => mapa.fire('click', eventoDeToque({ lat, lng }));
const pino = (mapa) => {
  expect(mapa.marcadores.length).toBe(1); // um só pino
  return mapa.marcadores[0];
};
const texto = (partes) => partes.map((p) => p.texto).join('');
const moradaSugerida = (seletor) => (seletor.vista.moradaSugerida ? texto(seletor.vista.moradaSugerida.partes) : '');
const inversas = (m) => m.pedidos.filter((p) => p.caminho === 'inversa');

// Toca em "Estou nesta loja" e o browser responde com a posição.
async function gps(m, latitude, longitude, accuracy) {
  m.seletor.estouNestaLoja();
  m.geo.pedidos.at(-1).sucesso({ coords: { latitude, longitude, accuracy } });
  await esvaziar();
}

// --- Antes de iniciar; os textos ------------------------------------------------------------------

test('antes de iniciar: a dica para tocar no mapa, "Confirmar localização" desativado e sem mapa', () => {
  const { seletor, registo } = preparar({ iniciar: false });
  expect(seletor.vista.dica).toBe(TEXTO_TOCAR_NO_MAPA);
  expect(TEXTO_TOCAR_NO_MAPA).toBe('Toque no mapa no sítio da loja.');
  expect(seletor.vista.estado).toBe('vazio');
  expect(seletor.vista.confirmarAtivo).toBe(false);
  expect(seletor.vista.aviso).toBeNull();
  expect(seletor.vista.erro).toBeNull();
  expect(seletor.vista.semMapa).toBe(false);
  expect(seletor.localizacao).toBeNull();
  expect(seletor.mapa).toBeNull();
  expect(registo.mapas.length).toBe(0); // o mapa só se cria em iniciar(), com a área já na página
});

test('a vista tem exatamente estas chaves (a pesquisa da Google entra na G11: até lá, null)', () => {
  const { seletor } = preparar({ gps: true });
  expect(Object.keys(seletor.vista)).toEqual([
    'estado', 'dica', 'aviso', 'erro', 'semMapa', 'confirmarAtivo', 'gps', 'moradaSugerida', 'pesquisa',
  ]);
  expect(seletor.vista.pesquisa).toBeNull();
  expect(seletor.pesquisa).toBeUndefined(); // o campo da pesquisa da Geoapify saiu
});

test('os textos dos botões e os da loja (título, dica, área do mapa e pino)', () => {
  expect(TEXTO_CONFIRMAR).toBe('Confirmar localização');
  expect(TEXTO_ALTERAR).toBe('Alterar localização');
  expect(TEXTOS_LOJA).toEqual({
    titulo: 'Localização', tocar: TEXTO_TOCAR_NO_MAPA, mapa: 'Mapa para pôr o pino da loja', pino: 'Pino da loja',
  });
  expect(textosSeletor()).toEqual(TEXTOS_LOJA);
  expect(textosSeletor({})).toEqual(TEXTOS_LOJA);
  expect(Object.isFrozen(TEXTOS_LOJA)).toBe(true);
});

test('com `textos` (o ponto da fábrica): o título, a dica, o nome do mapa e o do pino são os dados', () => {
  const textos = { titulo: 'Ponto da fábrica', tocar: 'Toque no mapa no sítio da fábrica.', mapa: 'Mapa da fábrica', pino: 'Pino da fábrica' };
  expect(textosSeletor(textos)).toEqual(textos);
  expect(textosSeletor({ titulo: 'Ponto da fábrica' })).toEqual({ ...TEXTOS_LOJA, titulo: 'Ponto da fábrica' });
  const { seletor, mapa, elemento } = preparar({ iniciar: false, textos });
  expect(seletor.vista.dica).toBe('Toque no mapa no sítio da fábrica.');
  seletor.iniciar(elemento, { inicial: { lat: 38.7223, lng: -9.1393, origem: 'pin_manual' } });
  expect(pino(mapa()).title).toBe('Pino da fábrica');
  expect(seletor.vista.dica).toBe(TEXTO_ARRASTAR);
});

test('sem `textos`: os da loja (o título do pino incluído)', () => {
  const { mapa } = preparar();
  tocar(mapa(), 38.71, -9.14);
  expect(pino(mapa()).title).toBe('Pino da loja');
});

// --- Iniciar: o mapa, a configuração e a localização inicial ----------------------------------------

test('iniciar cria um só mapa da Google no elemento, no centro das definições (zoom 12), sem mexer na vista', () => {
  const { seletor, iniciado, mapa, registo, elemento } = preparar();
  expect(iniciado).toBe(true);
  expect(registo.mapas.length).toBe(1);
  expect(mapa().getDiv()).toBe(elemento);
  expect(mapa().options.mapId).toBe('map-id-teste');
  expect(mapa().options.center).toEqual(CENTRO);
  expect(mapa().options.zoom).toBe(ZOOM_SEM_LOJAS);
  // Os ícones dos negócios ficam clicáveis: o balão da Google abre (e a G11 usa o toque).
  expect(mapa().options.clickableIcons).toBe(true);
  expect(mapa().vistas).toEqual([]); // o mapa já nasce no centro e no zoom certos
  expect(seletor.mapa.mapa).toBe(mapa()); // o mapa de mapa.js fica disponível
  expect(seletor.iniciar(elemento)).toBe(true); // já iniciado
  expect(registo.mapas.length).toBe(1);
});

// A ficha (T2.28) corrige a localização a partir da que a loja já tem.
const GUARDADA = { lat: 38.70921, lng: -9.13712, origem: 'gps', precisao_m: 12 };

test('iniciar com a localização inicial (ficha): o pino solto nesse sítio, à escala da rua', () => {
  const { seletor, mapa, mudancas } = preparar({ inicial: GUARDADA });
  expect(mapa().vistas).toEqual([
    { tipo: 'setCenter', centro: { lat: 38.70921, lng: -9.13712 } },
    { tipo: 'setZoom', zoom: ZOOM_MORADA },
  ]);
  expect(pino(mapa()).posicao()).toEqual({ lat: 38.70921, lng: -9.13712 });
  expect(pino(mapa()).gmpDraggable).toBe(true);
  expect(seletor.vista.estado).toBe('por_confirmar');
  expect(seletor.vista.dica).toBe(TEXTO_ARRASTAR);
  expect(seletor.localizacao).toBeNull();
  expect(mudancas).toEqual([]);
  expect(mapa().circulos.length).toBe(0); // o círculo é só de uma leitura nova do GPS
});

test('iniciar com a localização inicial e confirmar sem mexer: a mesma localização, com a mesma origem', () => {
  const { seletor } = preparar({ inicial: GUARDADA });
  seletor.confirmar();
  expect(seletor.localizacao).toEqual({
    lat: 38.70921, lng: -9.13712, origem_coords: 'gps', precisao_m: 12, google_place_id: null,
  });
});

test('iniciar com a localização inicial e arrastar: passa a pin_manual', () => {
  const { seletor, mapa } = preparar({ inicial: { lat: 38.70921, lng: -9.13712, origem: 'geocoder' } });
  pino(mapa()).arrastarPara(38.7093, -9.1372);
  seletor.confirmar();
  expect(seletor.localizacao).toEqual({
    lat: 38.7093, lng: -9.1372, origem_coords: 'pin_manual', precisao_m: null, google_place_id: null,
  });
});

test('a correção na ficha de um pino posto a partir de um lugar da Google: confirma sem arrastar e leva o id', () => {
  const inicial = { lat: 38.70921, lng: -9.13712, origem: 'pin_manual', google_place_id: LUGAR };
  const { seletor, mapa } = preparar({ inicial });
  expect(seletor.vista.confirmarAtivo).toBe(true);
  expect(seletor.vista.dica).toBe(TEXTO_ARRASTAR);
  expect(seletor.vista.aviso).toBeNull();
  seletor.confirmar();
  expect(seletor.localizacao).toEqual({
    lat: 38.70921, lng: -9.13712, origem_coords: 'pin_manual', precisao_m: null, google_place_id: LUGAR,
  });
  // Arrastar mantém o id; tocar no mapa à mão limpa-o.
  seletor.alterar();
  pino(mapa()).arrastarPara(38.7093, -9.1372);
  seletor.confirmar();
  expect(seletor.localizacao.google_place_id).toBe(LUGAR);
  seletor.alterar();
  tocar(mapa(), 38.711, -9.141);
  seletor.confirmar();
  expect(seletor.localizacao).toEqual({
    lat: 38.711, lng: -9.141, origem_coords: 'pin_manual', precisao_m: null, google_place_id: null,
  });
});

test('iniciar com uma localização inicial inválida: o centro das definições, sem pino', () => {
  const { seletor, mapa, elemento } = preparar({ iniciar: false });
  expect(seletor.iniciar(elemento, { inicial: { lat: null, lng: -9.1 } })).toBe(true);
  expect(mapa().vistas).toEqual([]);
  expect(mapa().options.center).toEqual(CENTRO);
  expect(mapa().marcadores.length).toBe(0);
});

test('sem a Google (ou sem as bibliotecas do mapa e dos pinos) ou com uma configuração inválida: "Não foi possível carregar o mapa"', () => {
  const casos = [
    { ajustarGoogle: () => undefined },
    { ajustarGoogle: () => null },
    { ajustarGoogle: () => ({}) },
    { ajustarGoogle: (google) => ({ maps: { ...google.maps, Map: undefined } }) },
    { ajustarGoogle: (google) => ({ maps: { ...google.maps, marker: undefined } }) },
    { configuracao: null },
    { configuracao: { centro: CENTRO } },
    { configuracao: { google: { chave: '', map_id: 'map-id-teste' }, centro: CENTRO } },
    { configuracao: { google: { chave: 'chave-teste-navegador' }, centro: CENTRO } },
  ];
  for (const opcoes of casos) {
    const { seletor, iniciado, registo, elemento } = preparar({ ...opcoes, gps: true });
    expect(iniciado).toBe(false);
    expect(registo.mapas.length).toBe(0);
    expect(seletor.vista.semMapa).toBe(true);
    expect(seletor.vista.erro).toBe(MENSAGEM_SEM_MAPA);
    expect(seletor.vista.confirmarAtivo).toBe(false);
    expect(seletor.vista.gps).toBeNull(); // sem mapa não há onde pôr o pino do GPS
    expect(seletor.colocar({ lat: 38.71, lng: -9.14, origem: 'pin_manual' })).toBe(false);
    expect(seletor.iniciar(elemento)).toBe(false); // sem mapa uma vez, sem mapa sempre
  }
});

test('o servidor sem a chave da Google (google: null): "Mapa não configurado", com ou sem a Google carregada', () => {
  for (const ajustarGoogle of [(google) => google, () => undefined]) {
    const { seletor, iniciado, registo } = preparar({ configuracao: { google: null, centro: CENTRO }, ajustarGoogle });
    expect(iniciado).toBe(false);
    expect(registo.mapas.length).toBe(0);
    expect(seletor.vista.semMapa).toBe(true);
    expect(seletor.vista.erro).toBe(MENSAGEM_MAPA_NAO_CONFIGURADO);
    expect(seletor.vista.confirmarAtivo).toBe(false);
  }
});

test('se a Google rebentar uma vez ao criar o mapa, o seletor fica sem mapa (não tenta outra vez)', () => {
  let tentativas = 0;
  const { seletor, elemento } = preparar({
    iniciar: false,
    ajustarGoogle: (google) => ({
      maps: {
        ...google.maps,
        Map: function MapaQueRebenta(...args) {
          tentativas += 1;
          if (tentativas === 1) throw new Error('sem tamanho');
          return new google.maps.Map(...args);
        },
      },
    }),
  });
  expect(seletor.iniciar(elemento)).toBe(false);
  expect(seletor.iniciar(elemento)).toBe(false);
  expect(tentativas).toBe(1);
  expect(seletor.mapa).toBeNull();
  expect(seletor.vista.semMapa).toBe(true);
  expect(seletor.vista.erro).toBe(MENSAGEM_SEM_MAPA);
});

test('sem mapa, limparErro não tira a mensagem do mapa (o ecrã limpa os erros ao guardar)', () => {
  const { seletor } = preparar({ configuracao: null });
  seletor.limparErro();
  expect(seletor.vista.erro).toBe(MENSAGEM_SEM_MAPA);
});

// --- O pino: tocar, arrastar, confirmar, alterar --------------------------------------------------

test('tocar no mapa põe lá um pino avançado arrastável (a gota vazia do el(), título, por cima) e deixa confirmar', () => {
  const { seletor, mapa, mudancas, documento, registo } = preparar();
  tocar(mapa(), 38.7101, -9.1402);
  const marcador = pino(mapa());
  expect(Object.keys(marcador.options).sort()).toEqual(['content', 'gmpDraggable', 'map', 'position', 'title', 'zIndex']);
  expect(marcador.options.map).toBe(mapa());
  expect(marcador.options.position).toStrictEqual({ lat: 38.7101, lng: -9.1402 });
  expect(marcador.options.gmpDraggable).toBe(true);
  expect(marcador.options.title).toBe('Pino da loja');
  expect(marcador.options.zIndex).toBe(1000);
  // O conteúdo é a div da gota, sem filhos nem texto (a gota desenha-se no crm.css), feita com o documento dado.
  const gota = marcador.content;
  expect(gota.tagName).toBe('DIV');
  expect(gota.className).toBe('pino-seletor');
  expect(gota.childNodes.length).toBe(0);
  expect(gota.textContent).toBe('');
  expect(gota.ownerDocument).toBe(documento);
  expect(marcador.posicao()).toEqual({ lat: 38.7101, lng: -9.1402 });
  expect(seletor.vista.dica).toBe(TEXTO_ARRASTAR);
  expect(TEXTO_ARRASTAR).toBe('Arraste o pino para o sítio exato e confirme.');
  expect(seletor.vista.confirmarAtivo).toBe(true);
  expect(seletor.vista.estado).toBe('por_confirmar');
  expect(seletor.localizacao).toBeNull(); // só conta depois de confirmar
  expect(mudancas).toEqual([]);
  expect(mapa().vistas.length).toBe(0); // o mapa não salta para o pino
  expect(registo.infoWindowsNossas).toBe(0);
});

test('com o document do jsdom: o pino é a div .pino-seletor vazia, dentro do mapa', () => {
  const { mapa, elemento } = preparar({ documento: document });
  tocar(mapa(), 38.7101, -9.1402);
  const gota = pino(mapa()).content;
  expect(gota).toBeInstanceOf(HTMLDivElement);
  expect(gota.className).toBe('pino-seletor');
  expect(gota.childElementCount).toBe(0);
  expect(gota.textContent).toBe('');
  expect(elemento.contains(gota)).toBe(true);
});

test('tocar outra vez muda o mesmo pino de sítio', () => {
  const { mapa, registo } = preparar();
  tocar(mapa(), 38.71, -9.14);
  const primeiro = pino(mapa());
  tocar(mapa(), 38.72, -9.15);
  expect(pino(mapa())).toBe(primeiro);
  expect(registo.marcadores.length).toBe(1);
  expect(primeiro.posicao()).toEqual({ lat: 38.72, lng: -9.15 });
});

test('um toque no mapa sem ponto não faz nada', () => {
  const { mapa, seletor } = preparar();
  mapa().fire('click', {});
  mapa().fire('click');
  expect(mapa().marcadores.length).toBe(0);
  expect(seletor.vista.confirmarAtivo).toBe(false);
});

test('tocar num negócio do mapa: o balão é o da Google (sem stop(), nenhum balão nosso) e nada se pede à Google', () => {
  const { mapa, registo } = preparar();
  const evento = eventoDeToque({ lat: 38.7101, lng: -9.1402, placeId: 'ChIJ-negocio' });
  mapa().fire('click', evento);
  expect(evento.parado).toBe(false);
  expect(registo.baloesDaGoogle).toBe(1);
  expect(registo.infoWindowsNossas).toBe(0);
  expect(registo.camposPedidos).toEqual([]);
});

test('Confirmar: fixa o pino (deixa de se arrastar), avisa com a localização (pin_manual) e o foco passa a "Alterar"', () => {
  const { seletor, mapa, mudancas, focos } = preparar();
  tocar(mapa(), 38.7101, -9.1402);
  seletor.confirmar();
  const localizacao = { lat: 38.7101, lng: -9.1402, origem_coords: 'pin_manual', precisao_m: null, google_place_id: null };
  expect(seletor.localizacao).toEqual(localizacao);
  expect(mudancas).toEqual([localizacao]);
  expect(mudancas[0]).toBe(seletor.localizacao);
  expect(pino(mapa()).gmpDraggable).toBe(false); // confirmado, o pino já não se arrasta
  expect(() => pino(mapa()).arrastarPara(38.72, -9.15)).toThrow('o pino não se pode arrastar');
  expect(seletor.vista.dica).toBe(TEXTO_CONFIRMADA);
  expect(TEXTO_CONFIRMADA).toBe('Localização confirmada.');
  expect(seletor.vista.estado).toBe('confirmado');
  expect(seletor.vista.confirmarAtivo).toBe(false);
  // O foco não se perde com o botão que desaparece.
  expect(focos).toEqual(['alterar']);
});

test('Confirmar outra vez, ou sem pino, não faz nada', () => {
  const { seletor, mapa, mudancas, focos } = preparar();
  seletor.confirmar();
  expect(seletor.vista.estado).toBe('vazio');
  tocar(mapa(), 38.71, -9.14);
  seletor.confirmar();
  seletor.confirmar();
  expect(mudancas.length).toBe(1);
  expect(focos).toEqual(['alterar']);
});

test('confirmado, um toque no mapa não mexe no pino', () => {
  const { seletor, mapa, mudancas } = preparar();
  tocar(mapa(), 38.71, -9.14);
  seletor.confirmar();
  tocar(mapa(), 38.75, -9.2);
  expect(pino(mapa()).posicao()).toEqual({ lat: 38.71, lng: -9.14 });
  expect(mudancas.length).toBe(1);
});

test('"Alterar localização" volta a soltar o pino (arrastável) e avisa que já não há localização confirmada', () => {
  const { seletor, mapa, mudancas, focos } = preparar();
  tocar(mapa(), 38.71, -9.14);
  seletor.confirmar();
  seletor.alterar();
  expect(seletor.localizacao).toBeNull();
  expect(mudancas.at(-1)).toBeNull();
  expect(pino(mapa()).gmpDraggable).toBe(true);
  expect(seletor.vista.estado).toBe('por_confirmar');
  expect(focos).toEqual(['alterar', 'confirmar']);
  expect(seletor.vista.dica).toBe(TEXTO_ARRASTAR);
  seletor.alterar(); // por confirmar, não faz nada
  expect(focos).toEqual(['alterar', 'confirmar']);
  expect(mudancas.length).toBe(2);
});

test('arrastar o pino: confirma o sítio para onde foi arrastado (lido do LatLng ou do literal da Google)', () => {
  const { seletor, mapa } = preparar();
  tocar(mapa(), 38.71, -9.14);
  // O falso dá a posição ora como LatLng ora como literal: dois arrastos seguidos passam pelas duas formas.
  pino(mapa()).arrastarPara(38.7111, -9.1387);
  pino(mapa()).arrastarPara(38.7112, -9.1388);
  seletor.confirmar();
  expect(seletor.localizacao).toEqual({
    lat: 38.7112, lng: -9.1388, origem_coords: 'pin_manual', precisao_m: null, google_place_id: null,
  });
  seletor.alterar();
  pino(mapa()).arrastarPara(38.7113, -9.1389);
  seletor.confirmar();
  expect(seletor.localizacao).toMatchObject({ lat: 38.7113, lng: -9.1389 });
});

test('um fim de arrasto sem posição legível no pino não muda nada (o pino fica onde estava)', () => {
  const { seletor, mapa, vistas } = preparar();
  seletor.colocar({ lat: 38.7098, lng: -9.1365, origem: 'google', google_place_id: LUGAR });
  const antes = vistas.length;
  const marcador = pino(mapa());
  marcador.position = null;
  marcador.fire('dragend', {});
  expect(vistas.length).toBe(antes);
  expect(seletor.vista.confirmarAtivo).toBe(false); // continua por arrastar
  marcador.arrastarPara(38.70985, -9.13655);
  seletor.confirmar();
  expect(seletor.localizacao).toMatchObject({ lat: 38.70985, lng: -9.13655, google_place_id: LUGAR });
});

test('colocar com zoom (uma origem guardada, geocoder): pino solto, o mapa aproxima-se e a origem fica', () => {
  const { seletor, mapa } = preparar();
  expect(seletor.colocar({ lat: 38.7098, lng: -9.1365, origem: 'geocoder' }, { zoom: 18 })).toBe(true);
  expect(mapa().vistas).toEqual([
    { tipo: 'setCenter', centro: { lat: 38.7098, lng: -9.1365 } },
    { tipo: 'setZoom', zoom: 18 },
  ]);
  expect(pino(mapa()).gmpDraggable).toBe(true);
  seletor.confirmar();
  expect(seletor.localizacao).toEqual({
    lat: 38.7098, lng: -9.1365, origem_coords: 'geocoder', precisao_m: null, google_place_id: null,
  });
});

test('colocar e depois arrastar: a origem passa a pin_manual', () => {
  const { seletor, mapa } = preparar();
  seletor.colocar({ lat: 38.7098, lng: -9.1365, origem: 'geocoder' });
  pino(mapa()).arrastarPara(38.7099, -9.1366);
  seletor.confirmar();
  expect(seletor.localizacao).toEqual({
    lat: 38.7099, lng: -9.1366, origem_coords: 'pin_manual', precisao_m: null, google_place_id: null,
  });
});

test('colocar sem origem: pin_manual', () => {
  const { seletor } = preparar();
  seletor.colocar({ lat: 38.7098, lng: -9.1365 });
  seletor.confirmar();
  expect(seletor.localizacao.origem_coords).toBe('pin_manual');
});

test('GPS com boa precisão: confirma sem arrastar, com origem gps e a precisão', () => {
  const { seletor } = preparar();
  seletor.colocar({ lat: 38.7105, lng: -9.1366, origem: 'gps', precisao_m: 20 });
  expect(seletor.vista.confirmarAtivo).toBe(true);
  seletor.confirmar();
  expect(seletor.localizacao).toEqual({
    lat: 38.7105, lng: -9.1366, origem_coords: 'gps', precisao_m: 20, google_place_id: null,
  });
});

test('GPS impreciso (> 50 m): "Localização imprecisa — ajuste o pino" e só confirma depois de arrastar', () => {
  const { seletor, mapa } = preparar();
  seletor.colocar({ lat: 38.7105, lng: -9.1366, origem: 'gps', precisao_m: 120 });
  expect(seletor.vista.dica).toBe(MENSAGEM_LOCALIZACAO_IMPRECISA);
  expect(seletor.vista.aviso).toBe('imprecisa');
  expect(seletor.vista.confirmarAtivo).toBe(false);
  seletor.confirmar();
  expect(seletor.localizacao).toBeNull();
  pino(mapa()).arrastarPara(38.7106, -9.1367);
  expect(seletor.vista.confirmarAtivo).toBe(true);
  expect(seletor.vista.dica).toBe(TEXTO_ARRASTAR);
  expect(seletor.vista.aviso).toBeNull();
  seletor.confirmar();
  expect(seletor.localizacao).toEqual({
    lat: 38.7106, lng: -9.1367, origem_coords: 'pin_manual', precisao_m: null, google_place_id: null,
  });
});

test('colocar depois de confirmar: volta a pedir confirmação', () => {
  const { seletor, mapa, mudancas } = preparar();
  tocar(mapa(), 38.71, -9.14);
  seletor.confirmar();
  seletor.colocar({ lat: 38.7098, lng: -9.1365, origem: 'geocoder' });
  expect(seletor.localizacao).toBeNull();
  expect(mudancas.at(-1)).toBeNull();
  expect(pino(mapa()).gmpDraggable).toBe(true);
  expect(pino(mapa()).posicao()).toEqual({ lat: 38.7098, lng: -9.1365 });
  expect(seletor.vista.estado).toBe('por_confirmar');
});

test('colocar sem coordenadas válidas não faz nada', () => {
  const { seletor, mapa } = preparar();
  for (const posicao of [null, {}, { lat: '38.7', lng: -9.1 }, { lat: Number.NaN, lng: -9.1 }]) {
    expect(seletor.colocar(posicao)).toBe(false);
  }
  expect(mapa().marcadores.length).toBe(0);
});

// --- A regra do arrasto: um pino vindo da Google ----------------------------------------------------

test('o texto da regra do arrasto, numa só linha do seletor.js', () => {
  expect(TEXTO_ARRASTAR_LUGAR).toBe('Arraste o pino até à porta da loja para confirmar');
  const fonte = fs.readFileSync(path.join(__dirname, 'seletor.js'), 'utf8');
  expect(fonte).toContain("\nexport const TEXTO_ARRASTAR_LUGAR = 'Arraste o pino até à porta da loja para confirmar';\n");
});

test('um pino da Google: Confirmar desligado, "Arraste o pino até à porta…", e Confirmar não faz nada', () => {
  const { seletor, mapa, mudancas, focos } = preparar();
  expect(seletor.colocar({ lat: 38.7098, lng: -9.1365, origem: 'google', google_place_id: LUGAR }, { zoom: ZOOM_MORADA })).toBe(true);
  expect(seletor.vista.estado).toBe('por_confirmar');
  expect(seletor.vista.confirmarAtivo).toBe(false);
  expect(seletor.vista.dica).toBe(TEXTO_ARRASTAR_LUGAR);
  expect(seletor.vista.aviso).toBe('arrastar');
  expect(pino(mapa()).gmpDraggable).toBe(true);
  seletor.confirmar();
  expect(seletor.vista.estado).toBe('por_confirmar');
  expect(seletor.localizacao).toBeNull();
  expect(mudancas).toEqual([]);
  expect(focos).toEqual([]);
  expect(pino(mapa()).gmpDraggable).toBe(true);
});

test('um pino da Google arrastado: Confirmar liga-se e confirma como pin_manual, com o google_place_id', () => {
  const { seletor, mapa, mudancas } = preparar();
  seletor.colocar({ lat: 38.7098, lng: -9.1365, origem: 'google', google_place_id: LUGAR }, { zoom: ZOOM_MORADA });
  pino(mapa()).arrastarPara(38.70985, -9.13655);
  expect(seletor.vista.confirmarAtivo).toBe(true);
  expect(seletor.vista.dica).toBe(TEXTO_ARRASTAR);
  expect(seletor.vista.aviso).toBeNull();
  seletor.confirmar();
  const localizacao = {
    lat: 38.70985, lng: -9.13655, origem_coords: 'pin_manual', precisao_m: null, google_place_id: LUGAR,
  };
  expect(seletor.localizacao).toEqual(localizacao);
  expect(mudancas).toEqual([localizacao]);
  // A API recusou (ex.: duplicado): volta a soltar-se e confirma-se outra vez sem novo arrasto.
  seletor.desconfirmar();
  expect(seletor.vista.confirmarAtivo).toBe(true);
  seletor.confirmar();
  expect(seletor.localizacao).toEqual(localizacao);
});

test('um pino da Google e depois um toque à mão no mapa: o google_place_id sai (arrastado ou não)', () => {
  for (const arrastar of [false, true]) {
    const { seletor, mapa } = preparar();
    seletor.colocar({ lat: 38.7098, lng: -9.1365, origem: 'google', google_place_id: LUGAR });
    if (arrastar) pino(mapa()).arrastarPara(38.70985, -9.13655);
    tocar(mapa(), 38.7101, -9.1402);
    expect(seletor.vista.dica).toBe(TEXTO_ARRASTAR);
    expect(seletor.vista.confirmarAtivo).toBe(true); // o pino à mão confirma-se sem arrastar
    seletor.confirmar();
    expect(seletor.localizacao).toEqual({
      lat: 38.7101, lng: -9.1402, origem_coords: 'pin_manual', precisao_m: null, google_place_id: null,
    });
  }
});

test('um pino da Google e depois outro sítio (colocar sem id): o id anterior não passa para o novo pino', () => {
  const { seletor, mapa } = preparar();
  seletor.colocar({ lat: 38.7098, lng: -9.1365, origem: 'google', google_place_id: LUGAR });
  pino(mapa()).arrastarPara(38.70985, -9.13655);
  seletor.colocar({ lat: 38.7105, lng: -9.1366, origem: 'gps', precisao_m: 20 });
  seletor.confirmar();
  expect(seletor.localizacao.google_place_id).toBeNull();
  expect(seletor.localizacao.origem_coords).toBe('gps');
});

test('um pino da Google sem identificador em texto: continua a exigir o arrasto e vai com google_place_id null', () => {
  for (const id of [undefined, null, '', '   ', 42, { id: LUGAR }]) {
    const { seletor, mapa } = preparar();
    seletor.colocar({ lat: 38.7098, lng: -9.1365, origem: 'google', google_place_id: id });
    expect(seletor.vista.confirmarAtivo).toBe(false);
    pino(mapa()).arrastarPara(38.70985, -9.13655);
    seletor.confirmar();
    expect(seletor.localizacao.google_place_id).toBeNull();
    expect(seletor.localizacao.origem_coords).toBe('pin_manual');
  }
});

test('a localização inicial com a origem google (passageira) também só se confirma depois de arrastar', () => {
  const { seletor, mapa } = preparar({ inicial: { lat: 38.7098, lng: -9.1365, origem: 'google', google_place_id: LUGAR } });
  expect(seletor.vista.aviso).toBe('arrastar');
  seletor.confirmar();
  expect(seletor.localizacao).toBeNull();
  pino(mapa()).arrastarPara(38.70985, -9.13655);
  seletor.confirmar();
  expect(seletor.localizacao).toEqual({
    lat: 38.70985, lng: -9.13655, origem_coords: 'pin_manual', precisao_m: null, google_place_id: LUGAR,
  });
});

// --- Erros, desconfirmar e foco ---------------------------------------------------------------------

test('mostrarErro (ex.: 422 "Fora de Portugal") aparece junto ao mapa; colocar outro pino limpa-o', () => {
  const { seletor, mapa } = preparar();
  tocar(mapa(), 38.71, -9.14);
  seletor.mostrarErro('Fora de Portugal');
  expect(seletor.vista.erro).toBe('Fora de Portugal');
  tocar(mapa(), 38.72, -9.15);
  expect(seletor.vista.erro).toBeNull();
  seletor.mostrarErro('Fora de Portugal');
  seletor.limparErro();
  expect(seletor.vista.erro).toBeNull();
});

test('desconfirmar (a API recusou a localização): volta a soltar o pino', () => {
  const { seletor, mapa, mudancas } = preparar();
  tocar(mapa(), 38.71, -9.14);
  seletor.confirmar();
  seletor.desconfirmar();
  expect(seletor.localizacao).toBeNull();
  expect(mudancas).toEqual([
    { lat: 38.71, lng: -9.14, origem_coords: 'pin_manual', precisao_m: null, google_place_id: null },
    null,
  ]);
  expect(pino(mapa()).gmpDraggable).toBe(true);
  seletor.desconfirmar();
  expect(mudancas.length).toBe(2); // sem localização confirmada não volta a avisar
});

test('desconfirmar sem localização confirmada não faz nada (nem sem pino)', () => {
  const { seletor, mapa, mudancas, vistas } = preparar();
  seletor.desconfirmar();
  expect(seletor.vista.estado).toBe('vazio');
  tocar(mapa(), 38.71, -9.14);
  const antes = vistas.length;
  pino(mapa()).gmpDraggable = false;
  seletor.desconfirmar();
  expect(pino(mapa()).gmpDraggable).toBe(false);
  expect(vistas.length).toBe(antes);
  expect(mudancas).toEqual([]);
});

test('focar põe o foco no botão de confirmar (ao lado do erro); confirmado, no de alterar', () => {
  const { seletor, mapa, focos } = preparar();
  tocar(mapa(), 38.71, -9.14);
  seletor.focar();
  expect(focos).toEqual(['confirmar']);
  seletor.confirmar();
  seletor.focar();
  expect(focos).toEqual(['confirmar', 'alterar', 'alterar']);
});

// --- Destruir ---------------------------------------------------------------------------------------

test('destruir tira o pino e o círculo do mapa e destrói o mapa (ouvintes e o DOM da Google)', async () => {
  const m = preparar({ gps: true });
  await gps(m, 38.7075, -9.1364, 20);
  const [circulo] = m.mapa().circulos;
  const marcador = pino(m.mapa());
  m.seletor.destruir();
  expect(marcador.map).toBeNull();
  expect(circulo.getMap()).toBeNull();
  expect(m.registo.marcadores.length).toBe(0);
  expect(m.registo.circulos.length).toBe(0);
  expect(m.mapa().limpezas).toBe(1); // o destruir do mapa.js (clearInstanceListeners)
  expect(m.elemento.childNodes.length).toBe(0);
  expect(m.seletor.mapa).toBeNull();
  expect(() => m.seletor.destruir()).not.toThrow();
  expect(m.mapa().limpezas).toBe(1);
});

test('depois de destruir nada muda nem avisa (iniciar, colocar, confirmar, alterar, GPS, erros, foco)', async () => {
  const m = preparar({ gps: true });
  tocar(m.mapa(), 38.71, -9.14);
  m.seletor.confirmar();
  m.seletor.destruir();
  const vista = m.seletor.vista;
  const vistas = m.vistas.length;
  expect(m.seletor.iniciar(m.elemento)).toBe(false);
  expect(m.seletor.colocar({ lat: 38.72, lng: -9.15, origem: 'pin_manual' })).toBe(false);
  m.seletor.alterar();
  m.seletor.desconfirmar();
  m.seletor.confirmar();
  m.seletor.mostrarErro('Fora de Portugal');
  m.seletor.limparErro();
  m.seletor.focar();
  m.seletor.redimensionar();
  await m.seletor.estouNestaLoja();
  expect(m.geo.pedidos.length).toBe(0);
  expect(m.seletor.vista).toBe(vista);
  expect(m.vistas.length).toBe(vistas);
  expect(m.mudancas.length).toBe(1);
  expect(m.focos).toEqual(['alterar']);
  expect(m.registo.mapas.length).toBe(1);
  expect(m.registo.marcadores.length).toBe(0);
});

test('um arrasto que chegue depois de destruir (o pino já fora do mapa) não muda nem avisa nada', () => {
  const { seletor, mapa, vistas, mudancas } = preparar();
  tocar(mapa(), 38.71, -9.14);
  const marcador = pino(mapa());
  seletor.destruir();
  const vista = seletor.vista;
  const antes = vistas.length;
  marcador.arrastarPara(38.72, -9.15);
  expect(seletor.vista).toBe(vista);
  expect(vistas.length).toBe(antes);
  seletor.confirmar();
  expect(mudancas).toEqual([]);
});

// --- "Estou nesta loja" -----------------------------------------------------------------------------

const PRACA = { rotulo: 'Praça do Comércio, 1100-148 Lisboa, Portugal', morada: 'Praça do Comércio', codigo_postal: '1100-148', localidade: 'Lisboa', lat: 38.70749, lng: -9.13648 };

test('sem geolocalização no browser, não há "Estou nesta loja"', () => {
  const { seletor } = preparar();
  expect(seletor.vista.gps).toBeNull();
});

test('"Estou nesta loja": o GPS só se pede quando se toca', () => {
  const m = preparar({ gps: true });
  expect(TEXTO_ESTOU_NESTA_LOJA).toBe('Estou nesta loja');
  expect(m.seletor.vista.gps).toEqual({ texto: 'Estou nesta loja', ocupado: false, mensagem: null });
  expect(m.geo.pedidos.length).toBe(0); // criar o seletor e o mapa não pede o GPS
  expect(m.seletor.vista.moradaSugerida).toBeNull();
});

test('um geolocation sem getCurrentPosition conta como sem GPS', () => {
  const { seletor } = preparar({ gps: {} });
  expect(seletor.vista.gps).toBeNull();
});

test('antes de haver mapa, "Estou nesta loja" não pede o GPS (não teria onde pôr o pino)', async () => {
  const m = preparar({ gps: true, iniciar: false });
  expect(m.seletor.vista.gps.ocupado).toBe(true);
  await m.seletor.estouNestaLoja();
  expect(m.geo.pedidos.length).toBe(0);
  m.seletor.iniciar(m.elemento);
  expect(m.seletor.vista.gps.ocupado).toBe(false);
});

test('tocar: pede o GPS uma vez (alta precisão, 15 s, sem cache) e espera com "A obter a localização…"', () => {
  const m = preparar({ gps: true });
  m.seletor.estouNestaLoja();
  expect(m.geo.pedidos.length).toBe(1);
  expect(m.geo.pedidos[0].opcoes).toEqual(OPCOES_GPS);
  expect(TEXTO_A_OBTER_LOCALIZACAO).toBe('A obter a localização…');
  // aria-disabled no botão (não `disabled`: o foco não se perde).
  expect(m.seletor.vista.gps).toEqual({ texto: 'A obter a localização…', ocupado: true, mensagem: null });
  m.seletor.estouNestaLoja();
  expect(m.geo.pedidos.length).toBe(1); // um toque, um pedido
});

test('o círculo da precisão: o roxo do CRM, transparente, e os toques passam para o mapa', () => {
  expect(ESTILO_CIRCULO).toStrictEqual({
    strokeColor: '#6b2fa3',
    strokeOpacity: 0.8,
    strokeWeight: 2,
    fillColor: '#6b2fa3',
    fillOpacity: 0.12,
    clickable: false,
  });
  expect(Object.isFrozen(ESTILO_CIRCULO)).toBe(true);
  expect(MARGEM_GPS).toBe(24);
  expect(ZOOM_GPS).toBe(18);
});

test('boa precisão: pino arrastável no ponto, um Circle com o raio da precisão e o mapa enquadra o círculo', async () => {
  const m = preparar({ gps: true });
  await gps(m, 38.7075, -9.1364, 20);
  const marcador = pino(m.mapa());
  expect(marcador.posicao()).toEqual({ lat: 38.7075, lng: -9.1364 });
  expect(marcador.gmpDraggable).toBe(true);
  expect(m.mapa().circulos.length).toBe(1);
  const [circulo] = m.mapa().circulos;
  expect(circulo.options).toStrictEqual({
    ...ESTILO_CIRCULO, center: { lat: 38.7075, lng: -9.1364 }, radius: 20, map: m.mapa(),
  });
  // O enquadramento: os cantos dos limitesDoCirculo num LatLngBounds, com a margem do GPS.
  const [[sul, oeste], [norte, este]] = limitesDoCirculo({ lat: 38.7075, lng: -9.1364 }, 20);
  const vista = m.mapa().vistas.at(-1);
  expect(vista.tipo).toBe('fitBounds');
  expect(vista.limites).toBeInstanceOf(m.google.maps.LatLngBounds);
  expect(vista.limites.pontos).toEqual([{ lat: sul, lng: oeste }, { lat: norte, lng: este }]);
  expect(vista.margem).toBe(MARGEM_GPS);
  expect(m.seletor.vista.gps).toEqual({ texto: 'Estou nesta loja', ocupado: false, mensagem: null });
  expect(m.seletor.vista.dica).toBe(TEXTO_ARRASTAR);
  expect(m.seletor.vista.aviso).toBeNull();
  expect(m.seletor.localizacao).toBeNull(); // ainda por confirmar
  expect(m.seletor.vista.confirmarAtivo).toBe(true);
  m.seletor.confirmar();
  expect(m.seletor.localizacao).toEqual({
    lat: 38.7075, lng: -9.1364, origem_coords: 'gps', precisao_m: 20, google_place_id: null,
  });
});

test('depois de enquadrar o círculo, o zoom não passa do 18 (no primeiro idle, um só ouvinte)', async () => {
  const m = preparar({ gps: true });
  await gps(m, 38.7075, -9.1364, 3);
  expect(m.mapa().ouvintes('idle')).toBe(1);
  await gps(m, 38.7076, -9.1365, 3);
  expect(m.mapa().ouvintes('idle')).toBe(1); // o anterior saiu
  m.mapa().setZoom(19);
  m.mapa().fire('idle');
  expect(m.mapa().getZoom()).toBe(ZOOM_GPS);
  expect(m.mapa().ouvintes('idle')).toBe(0);
  // Um círculo grande deixa o zoom que a Google escolheu.
  await gps(m, 38.7075, -9.1364, 40);
  m.mapa().setZoom(16);
  m.mapa().fire('idle');
  expect(m.mapa().getZoom()).toBe(16);
});

test('a precisão vai arredondada ao metro (como o servidor a guarda)', async () => {
  const m = preparar({ gps: true });
  await gps(m, 38.7075, -9.1364, 12.6);
  expect(m.mapa().circulos[0].getRadius()).toBe(13);
  m.seletor.confirmar();
  expect(m.seletor.localizacao.precisao_m).toBe(13);
});

test('GPS impreciso (> 50 m): "Localização imprecisa — ajuste o pino" e Confirmar só depois de arrastar (pin_manual)', async () => {
  const m = preparar({ gps: true });
  await gps(m, 38.7075, -9.1364, 120);
  expect(m.seletor.vista.dica).toBe(MENSAGEM_LOCALIZACAO_IMPRECISA);
  expect(m.seletor.vista.aviso).toBe('imprecisa');
  expect(m.seletor.vista.confirmarAtivo).toBe(false);
  expect(m.mapa().circulos[0].getRadius()).toBe(120);
  pino(m.mapa()).arrastarPara(38.7077, -9.1361);
  expect(m.seletor.vista.confirmarAtivo).toBe(true);
  expect(m.seletor.vista.aviso).toBeNull();
  expect(m.mapa().circulos.length).toBe(1); // o círculo fica, para se ver a zona onde o GPS está
  m.seletor.confirmar();
  expect(m.seletor.localizacao).toEqual({
    lat: 38.7077, lng: -9.1361, origem_coords: 'pin_manual', precisao_m: null, google_place_id: null,
  });
});

test('o browser sem a precisão: sem círculo, aproxima no ponto (zoom 18) e conta como imprecisa', async () => {
  const m = preparar({ gps: true });
  await gps(m, 38.7075, -9.1364, undefined);
  expect(m.mapa().circulos.length).toBe(0);
  expect(m.mapa().vistas.slice(-2)).toEqual([
    { tipo: 'setCenter', centro: { lat: 38.7075, lng: -9.1364 } },
    { tipo: 'setZoom', zoom: ZOOM_GPS },
  ]);
  expect(m.mapa().ouvintes('idle')).toBe(0);
  expect(m.seletor.vista.confirmarAtivo).toBe(false);
  expect(m.seletor.vista.dica).toBe(MENSAGEM_LOCALIZACAO_IMPRECISA);
});

test('permissão negada: a mensagem pt junto ao botão, sem pino, e o botão volta', async () => {
  const m = preparar({ gps: true });
  m.seletor.estouNestaLoja();
  m.geo.pedidos[0].falha({ code: 1, message: 'User denied Geolocation' });
  await esvaziar();
  expect(m.seletor.vista.gps.mensagem).toEqual({ texto: MENSAGEM_PERMISSAO_NEGADA, tipo: 'erro' });
  expect(m.seletor.vista.gps.mensagem.texto).toBe("Autorize a localização no browser para usar 'Estou nesta loja'");
  expect(m.mapa().marcadores.length).toBe(0);
  expect(m.seletor.vista.gps.texto).toBe('Estou nesta loja');
  expect(m.seletor.vista.gps.ocupado).toBe(false);
  expect(inversas(m).length).toBe(0);
  tocar(m.mapa(), 38.71, -9.14);
  expect(m.seletor.vista.gps.mensagem).toBeNull(); // pôr o pino à mão tira a mensagem
});

test('tempo esgotado: a mensagem pt e pode tentar outra vez', async () => {
  const m = preparar({ gps: true });
  m.seletor.estouNestaLoja();
  m.geo.pedidos[0].falha({ code: 3 });
  await esvaziar();
  expect(m.seletor.vista.gps.mensagem.texto).toBe('A localização demorou demasiado — tente outra vez ou coloque o pino no mapa');
  // Tocar outra vez tira logo a mensagem anterior (enquanto espera, só "A obter a localização…").
  m.seletor.estouNestaLoja();
  expect(m.seletor.vista.gps).toEqual({ texto: TEXTO_A_OBTER_LOCALIZACAO, ocupado: true, mensagem: null });
  m.geo.pedidos[1].falha({ code: 3 });
  await esvaziar();
  await gps(m, 38.7075, -9.1364, 20);
  expect(m.geo.pedidos.length).toBe(3);
  expect(m.seletor.vista.gps.mensagem).toBeNull();
  expect(pino(m.mapa()).posicao().lat).toBe(38.7075);
});

test('tocar no mapa ou escolher outro sítio depois do GPS: sai o círculo e a morada sugerida', async () => {
  const m = preparar({ gps: true });
  await gps(m, 38.7075, -9.1364, 20);
  inversas(m)[0].resolver(PRACA);
  await esvaziar();
  expect(moradaSugerida(m.seletor)).not.toBe('');
  const [circulo] = m.mapa().circulos;
  tocar(m.mapa(), 38.72, -9.15);
  expect(m.mapa().circulos.length).toBe(0);
  expect(circulo.getMap()).toBeNull();
  expect(m.seletor.vista.moradaSugerida).toBeNull();
  m.seletor.confirmar();
  expect(m.seletor.localizacao.origem_coords).toBe('pin_manual');
});

test('"Estou nesta loja" outra vez: um só círculo, no ponto novo', async () => {
  const m = preparar({ gps: true });
  await gps(m, 38.7075, -9.1364, 40);
  await gps(m, 38.7080, -9.1370, 15);
  expect(m.mapa().circulos.length).toBe(1);
  expect(m.mapa().circulos[0].getRadius()).toBe(15);
  expect(m.mapa().circulos[0].getCenter().toJSON()).toEqual({ lat: 38.708, lng: -9.137 });
  expect(pino(m.mapa()).posicao()).toEqual({ lat: 38.708, lng: -9.137 });
});

test('pôr o pino à mão enquanto o GPS responde: a posição que chega depois é ignorada', async () => {
  const m = preparar({ gps: true });
  m.seletor.estouNestaLoja();
  tocar(m.mapa(), 38.72, -9.15);
  m.geo.pedidos[0].sucesso({ coords: { latitude: 38.7075, longitude: -9.1364, accuracy: 10 } });
  await esvaziar();
  expect(pino(m.mapa()).posicao()).toEqual({ lat: 38.72, lng: -9.15 });
  expect(m.mapa().circulos.length).toBe(0);
  expect(inversas(m).length).toBe(0);
  expect(m.seletor.vista.gps).toEqual({ texto: 'Estou nesta loja', ocupado: false, mensagem: null });
});

test('arrastar o pino enquanto o GPS responde: fica o que a pessoa fez (também com um erro do GPS)', async () => {
  for (const responder of [
    (pedido) => pedido.sucesso({ coords: { latitude: 38.7075, longitude: -9.1364, accuracy: 10 } }),
    (pedido) => pedido.falha({ code: 2 }),
  ]) {
    const m = preparar({ gps: true });
    tocar(m.mapa(), 38.72, -9.15);
    m.seletor.estouNestaLoja();
    pino(m.mapa()).arrastarPara(38.7201, -9.1501);
    responder(m.geo.pedidos[0]);
    await esvaziar();
    expect(pino(m.mapa()).posicao()).toEqual({ lat: 38.7201, lng: -9.1501 });
    expect(m.mapa().circulos.length).toBe(0);
    expect(m.seletor.vista.gps.mensagem).toBeNull();
    expect(m.seletor.vista.gps.ocupado).toBe(false);
  }
});

test('com a localização já confirmada, o GPS muda o pino e volta a pedir confirmação', async () => {
  const m = preparar({ gps: true });
  tocar(m.mapa(), 38.72, -9.15);
  m.seletor.confirmar();
  await gps(m, 38.7075, -9.1364, 20);
  expect(m.seletor.localizacao).toBeNull();
  expect(m.mudancas.at(-1)).toBeNull();
  expect(pino(m.mapa()).posicao()).toEqual({ lat: 38.7075, lng: -9.1364 });
  expect(pino(m.mapa()).gmpDraggable).toBe(true);
  expect(m.seletor.vista.estado).toBe('por_confirmar');
});

test('um pino da Google e depois "Estou nesta loja": o pino do GPS não leva o google_place_id', async () => {
  const m = preparar({ gps: true });
  m.seletor.colocar({ lat: 38.7098, lng: -9.1365, origem: 'google', google_place_id: LUGAR });
  await gps(m, 38.7075, -9.1364, 20);
  expect(m.seletor.vista.confirmarAtivo).toBe(true);
  m.seletor.confirmar();
  expect(m.seletor.localizacao).toEqual({
    lat: 38.7075, lng: -9.1364, origem_coords: 'gps', precisao_m: 20, google_place_id: null,
  });
});

test('destruir enquanto espera pelo GPS: o que chega depois não faz nada', async () => {
  for (const responder of [
    (pedido) => pedido.sucesso({ coords: { latitude: 38.7075, longitude: -9.1364, accuracy: 10 } }),
    (pedido) => pedido.falha({ code: 1 }),
  ]) {
    const m = preparar({ gps: true });
    m.seletor.estouNestaLoja();
    m.seletor.destruir();
    const vistas = m.vistas.length;
    responder(m.geo.pedidos[0]);
    await esvaziar();
    expect(m.registo.marcadores.length).toBe(0);
    expect(m.registo.circulos.length).toBe(0);
    expect(inversas(m).length).toBe(0);
    expect(m.seletor.vista.gps.mensagem).toBeNull();
    expect(m.vistas.length).toBe(vistas); // nada chega ao ecrã que já saiu
  }
});

// --- Morada sugerida (geocodificação inversa do ponto do GPS, pela Geoapify) ------------------------

test('depois do GPS: GET /api/crm/morada/inversa com o ponto (6 casas decimais) e "A procurar a morada…"', async () => {
  const m = preparar({ gps: true });
  await gps(m, 38.70750000123, -9.13640000456, 12);
  expect(inversas(m).length).toBe(1);
  expect(inversas(m)[0].parametros).toStrictEqual({ lat: 38.7075, lng: -9.1364 });
  expect(TEXTO_A_PROCURAR_MORADA).toBe('A procurar a morada…');
  expect(moradaSugerida(m.seletor)).toBe('A procurar a morada…');
  expect(m.seletor.vista.moradaSugerida.tipo).toBeNull();
});

test('só o GPS pede a morada inversa (nem o toque, nem o arrasto, nem um pino da Google)', async () => {
  const m = preparar({ gps: true });
  tocar(m.mapa(), 38.71, -9.14);
  pino(m.mapa()).arrastarPara(38.711, -9.141);
  m.seletor.colocar({ lat: 38.7098, lng: -9.1365, origem: 'google', google_place_id: LUGAR });
  pino(m.mapa()).arrastarPara(38.70985, -9.13655);
  await esvaziar();
  expect(inversas(m).length).toBe(0);
  expect(m.seletor.vista.moradaSugerida).toBeNull();
});

test('morada sugerida: "Morada sugerida: … · Powered by Geoapify" (com a ligação) e o ecrã recebe-a', async () => {
  const m = preparar({ gps: true });
  await gps(m, 38.7075, -9.1364, 12);
  inversas(m)[0].resolver(PRACA);
  await esvaziar();
  expect(moradaSugerida(m.seletor)).toBe('Morada sugerida: Praça do Comércio, 1100-148 Lisboa, Portugal · Powered by Geoapify');
  const ligacoes = m.seletor.vista.moradaSugerida.partes.filter((p) => p.url !== null);
  expect(ligacoes).toEqual([{ texto: 'Powered by Geoapify', url: 'https://www.geoapify.com/' }]);
  expect(ligacoes).toEqual(ATRIBUICOES.geoapify.partes.map((p) => ({ texto: p.texto, url: p.url })));
  expect(m.seletor.vista.moradaSugerida.tipo).toBeNull();
  expect(m.sugeridas).toEqual([PRACA]);
  expect(m.seletor.localizacao).toBeNull(); // a morada não confirma a localização
  pino(m.mapa()).arrastarPara(38.7076, -9.1365);
  expect(moradaSugerida(m.seletor)).not.toBe(''); // arrastar o pino não a tira
});

test('partesMoradaSugerida: o rótulo entra como uma parte de texto, sem ligação, e a atribuição só das constantes', () => {
  const partes = partesMoradaSugerida('<b>x</b>');
  expect(texto(partes)).toBe('Morada sugerida: <b>x</b> · Powered by Geoapify');
  expect(partes[1]).toEqual({ texto: '<b>x</b>', url: null });
  expect(partes.slice(3)).toEqual(ATRIBUICOES.geoapify.partes.map((p) => ({ texto: p.texto, url: p.url })));
  expect(Object.isFrozen(partes)).toBe(true);
  expect(partes.every((p) => Object.isFrozen(p))).toBe(true);
});

test('a morada sugerida entra como texto: <b>x</b> fica tal e qual', async () => {
  const m = preparar({ gps: true });
  await gps(m, 38.7075, -9.1364, 12);
  inversas(m)[0].resolver({ ...PRACA, rotulo: '<b>x</b>' });
  await esvaziar();
  expect(moradaSugerida(m.seletor)).toBe('Morada sugerida: <b>x</b> · Powered by Geoapify');
});

test('sem morada para o ponto (null ou sem rótulo): não mostra nada nem preenche', async () => {
  for (const resposta of [null, {}, { ...PRACA, rotulo: '' }]) {
    const m = preparar({ gps: true });
    await gps(m, 38.7075, -9.1364, 12);
    inversas(m)[0].resolver(resposta);
    await esvaziar();
    expect(m.seletor.vista.moradaSugerida).toBeNull();
    expect(m.sugeridas).toEqual([]);
  }
});

test('morada sugerida indisponível (503 ou sem rede): a mensagem, e o pino confirma-se na mesma', async () => {
  for (const codigo of ['morada_indisponivel', 'sem_rede', 'erro_interno']) {
    const m = preparar({ gps: true });
    await gps(m, 38.7075, -9.1364, 12);
    inversas(m)[0].rejeitar({ codigo, mensagem: 'x' });
    await esvaziar();
    expect(moradaSugerida(m.seletor)).toBe(MENSAGEM_MORADA_SUGERIDA_INDISPONIVEL);
    expect(m.seletor.vista.moradaSugerida.tipo).toBe('erro');
    expect(m.sugeridas).toEqual([]);
    m.seletor.confirmar();
    expect(m.seletor.localizacao.origem_coords).toBe('gps');
  }
});

test('ponto fora de Portugal (422): sem morada sugerida (o erro aparece ao guardar)', async () => {
  const m = preparar({ gps: true });
  await gps(m, 38.7075, -9.1364, 12);
  inversas(m)[0].rejeitar({ codigo: 'validacao', mensagem: 'Fora de Portugal', campos: { lat: 'Fora de Portugal' } });
  await esvaziar();
  expect(m.seletor.vista.moradaSugerida).toBeNull();
});

test('a morada sugerida que chega depois de o pino mudar de sítio é ignorada', async () => {
  const m = preparar({ gps: true });
  await gps(m, 38.7075, -9.1364, 12);
  tocar(m.mapa(), 38.72, -9.15);
  inversas(m)[0].resolver(PRACA);
  await esvaziar();
  expect(m.sugeridas).toEqual([]);
  expect(m.seletor.vista.moradaSugerida).toBeNull();

  await gps(m, 38.7075, -9.1364, 12);
  await gps(m, 38.7080, -9.1370, 12);
  inversas(m)[1].resolver(PRACA);
  await esvaziar();
  expect(m.sugeridas).toEqual([]); // a do primeiro ponto chegou tarde
  inversas(m)[2].resolver({ ...PRACA, rotulo: 'Rua Augusta 24, 1100-048 Lisboa, Portugal' });
  await esvaziar();
  expect(m.sugeridas.length).toBe(1);
  expect(moradaSugerida(m.seletor)).toBe('Morada sugerida: Rua Augusta 24, 1100-048 Lisboa, Portugal · Powered by Geoapify');
});

test('um erro tardio da morada sugerida também é ignorado', async () => {
  const m = preparar({ gps: true });
  await gps(m, 38.7075, -9.1364, 12);
  tocar(m.mapa(), 38.72, -9.15);
  inversas(m)[0].rejeitar({ codigo: 'morada_indisponivel', mensagem: 'x' });
  await esvaziar();
  expect(m.seletor.vista.moradaSugerida).toBeNull();
});

test('destruir com a morada a caminho: a resposta não faz nada', async () => {
  const m = preparar({ gps: true });
  await gps(m, 38.7075, -9.1364, 12);
  m.seletor.destruir();
  const vistas = m.vistas.length;
  inversas(m)[0].resolver(PRACA);
  await esvaziar();
  expect(m.sugeridas).toEqual([]);
  expect(m.vistas.length).toBe(vistas);
});

test('sem api: o GPS põe o pino sem pedir a morada', async () => {
  const m = preparar({ gps: true, comApi: false });
  await gps(m, 38.7075, -9.1364, 12);
  expect(m.mapa().marcadores.length).toBe(1);
  expect(m.seletor.vista.moradaSugerida).toBeNull();
});

// --- A mais: a vista, redimensionar -----------------------------------------------------------------

test('a vista que chega ao aoMudarVista é a do seletor, nova a cada mudança e congelada', () => {
  const { seletor, mapa, vistas } = preparar();
  const antes = seletor.vista;
  tocar(mapa(), 38.71, -9.14);
  expect(vistas.at(-1)).toBe(seletor.vista);
  expect(seletor.vista).not.toBe(antes);
  expect(antes.estado).toBe('vazio');
  expect(Object.isFrozen(seletor.vista)).toBe(true);
  seletor.confirmar();
  expect(vistas.at(-1).estado).toBe('confirmado');
});

test('redimensionar: avisa o mapa da Google (resize); antes de iniciar e depois de destruir, nada', () => {
  const { seletor, mapa, registo, elemento } = preparar({ iniciar: false });
  expect(() => seletor.redimensionar()).not.toThrow();
  expect(registo.mapas.length).toBe(0);
  seletor.iniciar(elemento);
  seletor.redimensionar();
  const redimensionamentos = () => mapa().disparos.filter((d) => d.tipo === 'resize').length;
  expect(redimensionamentos()).toBe(1);
  seletor.destruir();
  expect(() => seletor.redimensionar()).not.toThrow();
  expect(redimensionamentos()).toBe(1);
});
