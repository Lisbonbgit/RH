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
 * Geoapify; entram os da regra do arrasto (um pino vindo da Google só se
 * confirma depois de arrastado, e vai como `pin_manual` com o
 * `google_place_id`), os do `AdvancedMarkerElement` (`gmpDraggable` ligado e
 * desligado), os do `google.maps.Circle` e os da configuração
 * `{google: {chave, map_id}}`. A G11 junta os do negócio selecionado (um
 * negócio tocado no mapa pequeno abre o painel; "Pôr o pino neste negócio"
 * pede à Google só a posição) e os da pesquisa da Google (a morada escolhida
 * põe o pino e preenche os campos, sem nunca pedir a inversa da Geoapify),
 * com o `registo.camposPedidos` do Google falso e um lugar com sentinelas
 * (dados de negócio que nunca podem chegar à vista, ao ecrã nem à API).
 *
 * O que no autónomo se via no DOM vê-se aqui na `vista`: a dica, o aviso, o
 * erro, o Confirmar ativo, o botão e a mensagem do GPS e a morada sugerida (em
 * partes: texto e ligação). O foco que o autónomo mudava (Confirmar ↔ Alterar)
 * chega ao componente pelo `aoFocar`. Em todos os testes, cada localização
 * confirmada que chega ao `aoMudar` é conferida no fim (chaves exatas e nunca
 * `origem_coords: 'google'`).
 *
 * A revisão do mapa Google junta os de `mapaFalhou` (a Google recusou a chave
 * depois de o mapa abrir), os textos da fábrica na regra do arrasto e no lugar
 * indisponível, e os das escolhas que se cruzam (um arrasto, a pesquisa, o GPS
 * e um negócio: conta sempre a escolha mais recente).
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
import { TEXTO_A_POSICIONAR, TEXTO_ESCREVA_O_NOME, TEXTO_LUGAR_INDISPONIVEL } from './lugarGoogle';
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
  const escolhidas = [];
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
    aoEscolherMorada: (morada) => escolhidas.push(morada),
    aoFocar: (alvo) => focos.push(alvo),
    aoMudarVista: (vista) => vistas.push(vista),
  });
  const iniciado = iniciar ? seletor.iniciar(elemento, inicial === undefined ? undefined : { inicial }) : null;
  return {
    documento, elemento, google, registo, seletor, mudancas, focos, vistas, sugeridas, escolhidas, geo, pedidos,
    iniciado,
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

// Deixa correr os pedidos à Google (o Google falso responde de forma assíncrona).
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

// Um negócio tocado no mapa pequeno: o identificador, o ponto do toque (a reserva) e a posição da Google.
const NEGOCIO = 'ChIJ-teste-negocio';
const TOQUE = Object.freeze({ lat: 38.71012, lng: -9.14021 });
const POSICAO_NEGOCIO = Object.freeze({ lat: 38.71034, lng: -9.14047 });

// Uma morada escolhida na pesquisa da Google (os componentes como a Google os dá).
const PESQUISADO = 'EiJ-teste-rua-augusta';
const POSICAO_AUGUSTA = Object.freeze({ lat: 38.71021, lng: -9.13695 });
const ROTULO_AUGUSTA = 'R. Augusta 24, 1100-048 Lisboa, Portugal';
const COMPONENTES_AUGUSTA = Object.freeze([
  { types: ['street_number'], longText: '24', shortText: '24' },
  { types: ['route'], longText: 'Rua Augusta', shortText: 'R. Augusta' },
  { types: ['locality', 'political'], longText: 'Lisboa', shortText: 'Lisboa' },
  { types: ['country', 'political'], longText: 'Portugal', shortText: 'PT' },
  { types: ['postal_code'], longText: '1100-048', shortText: '1100-048' },
]);
// O que o ecrã recebe ao escolher essa morada (aoEscolherMorada): a morada da Google e o ponto.
const MORADA_AUGUSTA = Object.freeze({
  rotulo: ROTULO_AUGUSTA,
  morada: 'Rua Augusta 24',
  codigo_postal: '1100-048',
  localidade: 'Lisboa',
  ...POSICAO_AUGUSTA,
});

// Dados de negócio que a Google tem e que o seletor nunca pede nem mostra (os valores são sentinelas).
const SENTINELAS = Object.freeze({
  displayName: 'CANÁRIO-NOME',
  nationalPhoneNumber: 'CANÁRIO-TELEFONE',
  websiteUri: 'CANÁRIO-SITE',
});

// Os lugares que a Google falsa conhece: o negócio (com a morada dele, que só viria se fosse pedida) e a
// morada da pesquisa, os dois com as sentinelas.
function lugares(registo) {
  registo.lugares[NEGOCIO] = { ...POSICAO_NEGOCIO, formattedAddress: 'CANÁRIO-MORADA-DO-NEGÓCIO', ...SENTINELAS };
  registo.lugares[PESQUISADO] = {
    ...POSICAO_AUGUSTA, formattedAddress: ROTULO_AUGUSTA, addressComponents: COMPONENTES_AUGUSTA, ...SENTINELAS,
  };
}

// A vista leva o elemento de pesquisa da Google (um nó do documento, com ciclos): no texto conta só se existe.
const emTexto = (valor) => JSON.stringify(valor, (chave, v) => (chave === 'elemento' ? v !== null : v)) ?? '';
const semSentinelas = (valor) => !emTexto(valor).includes('CANÁRIO');

const posicoesDosPinos = (mapa) => mapa.marcadores.map((marcador) => marcador.posicao());
const pesquisa = (m) => m.seletor.vista.pesquisa.elemento;

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

test('a vista tem exatamente estas chaves (com a pesquisa da Google e o painel do negócio, congelados)', () => {
  const { seletor, registo } = preparar({ gps: true });
  expect(Object.keys(seletor.vista)).toEqual([
    'estado', 'dica', 'aviso', 'erro', 'semMapa', 'confirmarAtivo', 'gps', 'moradaSugerida', 'pesquisa', 'negocio',
  ]);
  expect(Object.keys(seletor.vista.pesquisa)).toEqual(['ativa', 'elemento']);
  expect(seletor.vista.pesquisa.ativa).toBe(true);
  expect(seletor.vista.pesquisa.elemento).toBe(registo.pesquisas[0]);
  expect(Object.isFrozen(seletor.vista.pesquisa)).toBe(true);
  expect(seletor.vista.negocio).toEqual({ placeId: null, reserva: null, estado: 'fechado', mensagem: null });
  expect(Object.isFrozen(seletor.vista.negocio)).toBe(true);
  expect(seletor.pesquisa).toBeUndefined(); // o campo da pesquisa da Geoapify saiu
});

test('os textos dos botões e os da loja (título, dica, área do mapa e pino)', () => {
  expect(TEXTO_CONFIRMAR).toBe('Confirmar localização');
  expect(TEXTO_ALTERAR).toBe('Alterar localização');
  expect(TEXTOS_LOJA).toEqual({
    titulo: 'Localização',
    tocar: TEXTO_TOCAR_NO_MAPA,
    mapa: 'Mapa para pôr o pino da loja',
    pino: 'Pino da loja',
    // Revisão do mapa Google (MAPA-G-2): a dica da regra do arrasto, o lugar indisponível e a dica do painel do
    // negócio também se trocam (o ponto da fábrica passa os seus).
    arrastarLugar: TEXTO_ARRASTAR_LUGAR,
    lugarIndisponivel: TEXTO_LUGAR_INDISPONIVEL,
    dicaNegocio: TEXTO_ESCREVA_O_NOME,
  });
  expect(textosSeletor()).toEqual(TEXTOS_LOJA);
  expect(textosSeletor({})).toEqual(TEXTOS_LOJA);
  expect(Object.isFrozen(TEXTOS_LOJA)).toBe(true);
});

test('com `textos` (o ponto da fábrica): o título, a dica, o nome do mapa e o do pino são os dados', () => {
  const textos = { titulo: 'Ponto da fábrica', tocar: 'Toque no mapa no sítio da fábrica.', mapa: 'Mapa da fábrica', pino: 'Pino da fábrica' };
  expect(textosSeletor(textos)).toEqual({ ...TEXTOS_LOJA, ...textos });
  expect(textosSeletor({ titulo: 'Ponto da fábrica' })).toEqual({ ...TEXTOS_LOJA, titulo: 'Ponto da fábrica' });
  const { seletor, mapa, elemento } = preparar({ iniciar: false, textos });
  expect(seletor.vista.dica).toBe('Toque no mapa no sítio da fábrica.');
  seletor.iniciar(elemento, { inicial: { lat: 38.7223, lng: -9.1393, origem: 'pin_manual' } });
  expect(pino(mapa()).title).toBe('Pino da fábrica');
  expect(seletor.vista.dica).toBe(TEXTO_ARRASTAR);
});

test('com `textos` (o ponto da fábrica): a dica da regra do arrasto e o lugar indisponível (painel e pesquisa) são os dados', async () => {
  const textos = {
    tocar: 'Toque no mapa no sítio da fábrica.',
    arrastarLugar: 'Arraste o pino até ao sítio exato da fábrica para confirmar',
    lugarIndisponivel: 'Não foi possível obter a posição deste lugar — toque no mapa no sítio da fábrica.',
    dicaNegocio: null,
  };
  expect(textosSeletor(textos)).toEqual({ ...TEXTOS_LOJA, ...textos });
  const m = preparar({ textos });
  lugares(m.registo);
  // Um negócio: o pino da Google pede o arrasto com o texto dado.
  m.seletor.escolherNegocio(NEGOCIO, { reserva: TOQUE });
  await m.seletor.usarNegocio();
  expect(m.seletor.vista.dica).toBe(textos.arrastarLugar);
  expect(m.seletor.vista.aviso).toBe('arrastar');
  // A Google sem a posição de outro negócio: o painel diz porquê, com o texto dado (o pino vai para a reserva).
  m.seletor.escolherNegocio('ChIJ-inexistente', { reserva: TOQUE });
  await m.seletor.usarNegocio();
  expect(m.seletor.vista.negocio.mensagem).toBe(textos.lugarIndisponivel);
  expect(m.seletor.vista.dica).toBe(textos.arrastarLugar);
  // A pesquisa sem o lugar, ou o gmp-error: o erro do seletor também.
  pesquisa(m).escolher('EiJ-inexistente');
  await esperar();
  expect(m.seletor.vista.erro).toBe(textos.lugarIndisponivel);
  tocar(m.mapa(), 38.71, -9.14);
  pesquisa(m).falhar();
  expect(m.seletor.vista.erro).toBe(textos.lugarIndisponivel);
  expect(emTexto(m.vistas)).not.toMatch(/loja/i);
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

// Revisão do mapa Google (MAPA-G-1 / G-ENG-1): com um referrer que a chave não autoriza (a app instalada, um
// domínio a mais) ou uma chave recusada, o script da Google carrega na mesma e o mapa cria-se; a Google só
// avisa depois (`gm_authFailure`), e o componente chama `mapaFalhou`. Fica como se a Google não tivesse
// carregado: "Não foi possível carregar o mapa — recarregue a página." e sem pino, pesquisa, painel nem GPS.
test('mapaFalhou (a Google recusou a chave com o mapa aberto): a mensagem de sempre e nada do mapa fica', () => {
  const m = preparar({ gps: true });
  lugares(m.registo);
  const contentor = m.documento.createElement('div');
  contentor.appendChild(pesquisa(m));
  tocar(m.mapa(), 38.71, -9.14);
  m.seletor.escolherNegocio(NEGOCIO, { reserva: TOQUE });
  expect(m.seletor.vista.negocio.estado).toBe('aberto');
  const vistas = m.vistas.length;
  m.seletor.mapaFalhou();
  expect(m.vistas.length).toBeGreaterThan(vistas);
  expect(m.vistas.at(-1)).toBe(m.seletor.vista);
  const { vista } = m.seletor;
  expect(vista.semMapa).toBe(true);
  expect(vista.erro).toBe(MENSAGEM_SEM_MAPA);
  expect(vista.estado).toBe('vazio');
  expect(vista.dica).toBe(TEXTO_TOCAR_NO_MAPA);
  expect(vista.aviso).toBeNull();
  expect(vista.confirmarAtivo).toBe(false);
  expect(vista.gps).toBeNull();
  expect(vista.moradaSugerida).toBeNull();
  expect(vista.pesquisa).toEqual({ ativa: false, elemento: null });
  expect(vista.negocio.estado).toBe('fechado');
  // A pesquisa saiu de onde o ecrã a pôs; o pino e o mapa (com o DOM da Google) também.
  expect(contentor.childNodes.length).toBe(0);
  expect(m.registo.marcadores.length).toBe(0);
  expect(m.seletor.mapa).toBeNull();
  expect(m.elemento.childNodes.length).toBe(0);
  expect(m.mapa().limpezas).toBeGreaterThan(0);
  expect(m.seletor.limitesDoMapa()).toBeNull();
  expect(Object.isFrozen(vista)).toBe(true);
});

test('mapaFalhou com a localização confirmada: deixa de haver localização (aoMudar(null)) e nada mais se faz', async () => {
  const m = preparar({ gps: true });
  lugares(m.registo);
  await gps(m, 38.7101, -9.1402, 12);
  m.seletor.confirmar();
  expect(m.seletor.localizacao).not.toBeNull();
  m.seletor.mapaFalhou();
  expect(m.seletor.localizacao).toBeNull();
  expect(m.mudancas.at(-1)).toBeNull();
  expect(m.registo.circulos.length).toBe(0);
  expect(m.seletor.vista.estado).toBe('vazio');
  m.seletor.confirmar();
  m.seletor.alterar();
  m.seletor.desconfirmar();
  m.seletor.estouNestaLoja();
  expect(m.geo.pedidos.length).toBe(1);
  expect(m.seletor.localizacao).toBeNull();
  expect(m.seletor.colocar({ lat: 38.7, lng: -9.15, origem: 'pin_manual' })).toBe(false);
  m.seletor.escolherNegocio(NEGOCIO, { reserva: TOQUE });
  await expect(m.seletor.usarNegocio(NEGOCIO, { reserva: TOQUE })).resolves.toBe(false);
  expect(m.registo.camposPedidos).toEqual([]);
  expect(m.seletor.vista.negocio.estado).toBe('fechado');
  expect(m.seletor.iniciar(m.elemento)).toBe(false);
  expect(m.registo.mapas.length).toBe(1);
  expect(m.registo.marcadores.length).toBe(0);
  // A mensagem do mapa fica (o ecrã limpa os erros ao guardar).
  m.seletor.limparErro();
  expect(m.seletor.vista.erro).toBe(MENSAGEM_SEM_MAPA);
});

test('mapaFalhou com o GPS, a morada sugerida, a posição de um negócio ou uma escolha da pesquisa a caminho: o que chega depois não faz nada', async () => {
  const casos = {
    'o GPS': async (m) => {
      m.seletor.estouNestaLoja();
      return async () => {
        m.geo.pedidos.at(-1).sucesso({ coords: { latitude: 38.7101, longitude: -9.1402, accuracy: 12 } });
        await esvaziar();
      };
    },
    'a morada sugerida do GPS': async (m) => {
      await gps(m, 38.7101, -9.1402, 12);
      return async () => {
        inversas(m).at(-1).resolver({ rotulo: 'Rua Augusta 24, Lisboa', morada: 'Rua Augusta 24' });
        await esvaziar();
      };
    },
    'a posição de um negócio': async (m) => {
      const soltar = atrasar(m.google, NEGOCIO);
      m.seletor.escolherNegocio(NEGOCIO, { reserva: TOQUE });
      const promessa = m.seletor.usarNegocio();
      return async () => {
        soltar();
        await expect(promessa).resolves.toBe(false);
      };
    },
    'uma escolha da pesquisa': async (m) => {
      const soltar = atrasar(m.google, PESQUISADO);
      pesquisa(m).escolher(PESQUISADO);
      return async () => {
        soltar();
        await esperar();
      };
    },
  };
  for (const [caso, comecar] of Object.entries(casos)) {
    const m = preparar({ gps: true });
    lugares(m.registo);
    const chegar = await comecar(m);
    m.seletor.mapaFalhou();
    const { vista } = m.seletor;
    const vistas = m.vistas.length;
    const sugeridas = m.sugeridas.length;
    await chegar();
    expect([caso, m.seletor.vista === vista, m.vistas.length]).toEqual([caso, true, vistas]);
    expect([caso, m.registo.marcadores.length, m.registo.circulos.length]).toEqual([caso, 0, 0]);
    expect([caso, m.escolhidas, m.sugeridas.length]).toEqual([caso, [], sugeridas]);
  }
});

test('mapaFalhou antes de iniciar fica sem mapa; sem mapa (não configurado), outra vez ou depois de destruir, nada muda', () => {
  const antes = preparar({ iniciar: false, gps: true });
  antes.seletor.mapaFalhou();
  expect(antes.seletor.vista.semMapa).toBe(true);
  expect(antes.seletor.vista.erro).toBe(MENSAGEM_SEM_MAPA);
  expect(antes.seletor.vista.gps).toBeNull();
  expect(antes.seletor.iniciar(antes.elemento)).toBe(false);
  expect(antes.registo.mapas.length).toBe(0);
  // O servidor sem a chave: fica "Mapa não configurado".
  const naoConfigurado = preparar({ configuracao: { google: null, centro: CENTRO } });
  const vistasSemChave = naoConfigurado.vistas.length;
  naoConfigurado.seletor.mapaFalhou();
  expect(naoConfigurado.seletor.vista.erro).toBe(MENSAGEM_MAPA_NAO_CONFIGURADO);
  expect(naoConfigurado.vistas.length).toBe(vistasSemChave);
  // Duas vezes: a segunda não muda nem avisa nada.
  const duas = preparar();
  duas.seletor.mapaFalhou();
  const vistas = duas.vistas.length;
  const { vista } = duas.seletor;
  duas.seletor.mapaFalhou();
  expect(duas.vistas.length).toBe(vistas);
  expect(duas.seletor.vista).toBe(vista);
  // Depois de destruir.
  const fora = preparar();
  fora.seletor.destruir();
  const vistasFora = fora.vistas.length;
  fora.seletor.mapaFalhou();
  expect(fora.vistas.length).toBe(vistasFora);
  expect(fora.seletor.vista.semMapa).toBe(false);
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

test('tocar num negócio do mapa: abre o painel com o ponto tocado; o pino não se move, o balão é o da Google e nada se pede', () => {
  for (const comPino of [false, true]) {
    const { seletor, mapa, registo } = preparar();
    if (comPino) tocar(mapa(), 38.7, -9.15);
    const evento = eventoDeToque({ ...TOQUE, placeId: NEGOCIO });
    mapa().fire('click', evento);
    expect(seletor.vista.negocio).toEqual({ placeId: NEGOCIO, reserva: TOQUE, estado: 'aberto', mensagem: null });
    expect(mapa().marcadores.map((m) => m.posicao())).toEqual(comPino ? [{ lat: 38.7, lng: -9.15 }] : []);
    expect(seletor.vista.estado).toBe(comPino ? 'por_confirmar' : 'vazio');
    expect(evento.parado).toBe(false);
    expect(registo.baloesDaGoogle).toBe(1);
    expect(registo.infoWindowsNossas).toBe(0);
    expect(registo.camposPedidos).toEqual([]);
  }
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

test('destruir não rebenta quando a Google recusou a chave e tirar o pino ou o círculo lança erro', async () => {
  // Visto em produção (2026-10-22): com RefererNotAllowedMapError, tirar um pino do mapa lança dentro da Google.
  const m = preparar({ gps: true });
  await gps(m, 38.7075, -9.1364, 20);
  const [circulo] = m.mapa().circulos;
  const marcador = pino(m.mapa());
  Object.defineProperty(marcador, 'map', { configurable: true, get: () => m.mapa(), set: () => { throw new TypeError('recusado'); } });
  circulo.setMap = () => { throw new TypeError('recusado'); };
  expect(() => m.seletor.destruir()).not.toThrow();
  expect(m.elemento.childNodes.length).toBe(0);
  expect(m.seletor.mapa).toBeNull();
});

test('depois de destruir nada muda nem avisa (iniciar, colocar, confirmar, alterar, GPS, erros, foco, negócio)', async () => {
  const m = preparar({ gps: true });
  lugares(m.registo);
  tocar(m.mapa(), 38.71, -9.14);
  m.seletor.confirmar();
  m.seletor.destruir();
  const vista = m.seletor.vista;
  const vistas = m.vistas.length;
  expect(m.seletor.iniciar(m.elemento)).toBe(false);
  expect(m.seletor.colocar({ lat: 38.72, lng: -9.15, origem: 'pin_manual' })).toBe(false);
  m.seletor.escolherNegocio(NEGOCIO, { reserva: TOQUE });
  await expect(m.seletor.usarNegocio(NEGOCIO, { reserva: TOQUE })).resolves.toBe(false);
  m.seletor.fecharNegocio();
  expect(m.registo.camposPedidos).toEqual([]);
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

// --- O negócio selecionado: um negócio tocado no mapa pequeno (G11) ---------------------------------

test('escolherNegocio(placeId, {reserva}) abre o painel; outro negócio substitui-o; um id que não seja texto não abre nada', () => {
  const { seletor, registo } = preparar();
  seletor.escolherNegocio(NEGOCIO, { reserva: TOQUE });
  expect(seletor.vista.negocio).toEqual({ placeId: NEGOCIO, reserva: TOQUE, estado: 'aberto', mensagem: null });
  seletor.escolherNegocio('ChIJ-outro', { reserva: { lat: 38.72, lng: -9.13 } });
  expect(seletor.vista.negocio).toEqual({
    placeId: 'ChIJ-outro', reserva: { lat: 38.72, lng: -9.13 }, estado: 'aberto', mensagem: null,
  });
  for (const id of [undefined, null, '', '   ', 42, { id: NEGOCIO }]) {
    seletor.fecharNegocio();
    seletor.escolherNegocio(id, { reserva: TOQUE });
    expect(seletor.vista.negocio.estado).toBe('fechado');
  }
  expect(registo.camposPedidos).toEqual([]);
  expect(registo.marcadores.length).toBe(0);
});

test('com a localização confirmada, tocar num negócio não abre o painel nem mexe no pino (o balão da Google abre)', () => {
  const { seletor, mapa, registo } = preparar();
  tocar(mapa(), 38.7, -9.15);
  seletor.confirmar();
  mapa().fire('click', eventoDeToque({ ...TOQUE, placeId: NEGOCIO }));
  expect(seletor.vista.negocio.estado).toBe('fechado');
  expect(seletor.vista.estado).toBe('confirmado');
  expect(posicoesDosPinos(mapa())).toEqual([{ lat: 38.7, lng: -9.15 }]);
  expect(registo.baloesDaGoogle).toBe(1);
});

test('fecharNegocio fecha o painel e deixa o pino onde estava', () => {
  const { seletor, mapa } = preparar();
  tocar(mapa(), 38.7, -9.15);
  mapa().fire('click', eventoDeToque({ ...TOQUE, placeId: NEGOCIO }));
  seletor.fecharNegocio();
  expect(seletor.vista.negocio).toEqual({ placeId: null, reserva: null, estado: 'fechado', mensagem: null });
  expect(posicoesDosPinos(mapa())).toEqual([{ lat: 38.7, lng: -9.15 }]);
  expect(seletor.vista.confirmarAtivo).toBe(true);
});

test('um toque à mão no mapa fecha o painel e põe o pino nesse ponto, sem lugar da Google', () => {
  const { seletor, mapa } = preparar();
  mapa().fire('click', eventoDeToque({ ...TOQUE, placeId: NEGOCIO }));
  tocar(mapa(), 38.7, -9.15);
  expect(seletor.vista.negocio.estado).toBe('fechado');
  seletor.confirmar();
  expect(seletor.localizacao).toEqual({
    lat: 38.7, lng: -9.15, origem_coords: 'pin_manual', precisao_m: null, google_place_id: null,
  });
});

test('usarNegocio (a ação do painel): "A posicionar o pino…", só a location, e o pino solto no negócio; o painel fecha', async () => {
  const m = preparar();
  lugares(m.registo);
  m.mapa().fire('click', eventoDeToque({ ...TOQUE, placeId: NEGOCIO }));
  const promessa = m.seletor.usarNegocio();
  expect(m.seletor.vista.negocio).toEqual({
    placeId: NEGOCIO, reserva: TOQUE, estado: 'a_posicionar', mensagem: TEXTO_A_POSICIONAR,
  });
  expect(m.mapa().marcadores.length).toBe(0); // ainda não: a posição vem da Google
  await expect(promessa).resolves.toBe(true);
  expect(m.registo.camposPedidos).toEqual([{ id: NEGOCIO, fields: ['location'] }]);
  expect(posicoesDosPinos(m.mapa())).toEqual([POSICAO_NEGOCIO]);
  expect(pino(m.mapa()).gmpDraggable).toBe(true);
  expect(m.mapa().centro).toEqual(POSICAO_NEGOCIO);
  expect(m.mapa().zoom).toBe(ZOOM_MORADA);
  expect(m.seletor.vista.negocio).toEqual({ placeId: null, reserva: null, estado: 'fechado', mensagem: null });
  // A regra do arrasto: um pino da Google só se confirma depois de arrastado até à porta.
  expect(m.seletor.vista.estado).toBe('por_confirmar');
  expect(m.seletor.vista.dica).toBe(TEXTO_ARRASTAR_LUGAR);
  expect(m.seletor.vista.aviso).toBe('arrastar');
  expect(m.seletor.vista.confirmarAtivo).toBe(false);
  m.seletor.confirmar();
  expect(m.seletor.localizacao).toBeNull();
  // A morada de um negócio não se preenche (nem a inversa da Geoapify) e nenhum balão é nosso.
  expect(m.seletor.vista.moradaSugerida).toBeNull();
  expect(m.escolhidas).toEqual([]);
  expect(m.sugeridas).toEqual([]);
  expect(inversas(m).length).toBe(0);
  expect(m.registo.baloesDaGoogle).toBe(1);
  expect(m.registo.infoWindowsNossas).toBe(0);
});

test('o pino de um negócio, arrastado até à porta: confirma como pin_manual com o google_place_id do negócio', async () => {
  const m = preparar();
  lugares(m.registo);
  m.seletor.escolherNegocio(NEGOCIO, { reserva: TOQUE });
  await m.seletor.usarNegocio();
  pino(m.mapa()).arrastarPara(38.71036, -9.14049);
  expect(m.seletor.vista.confirmarAtivo).toBe(true);
  m.seletor.confirmar();
  expect(m.seletor.localizacao).toEqual({
    lat: 38.71036, lng: -9.14049, origem_coords: 'pin_manual', precisao_m: null, google_place_id: NEGOCIO,
  });
  expect(m.mudancas).toEqual([m.seletor.localizacao]);
});

test('usarNegocio ao chegar do mapa (nova loja): com o painel fechado, abre-o a posicionar e põe o pino', async () => {
  const m = preparar();
  lugares(m.registo);
  const promessa = m.seletor.usarNegocio(NEGOCIO, { reserva: TOQUE });
  expect(m.seletor.vista.negocio).toEqual({
    placeId: NEGOCIO, reserva: TOQUE, estado: 'a_posicionar', mensagem: TEXTO_A_POSICIONAR,
  });
  await expect(promessa).resolves.toBe(true);
  expect(posicoesDosPinos(m.mapa())).toEqual([POSICAO_NEGOCIO]);
  expect(m.seletor.vista.negocio.estado).toBe('fechado');
  expect(m.seletor.vista.dica).toBe(TEXTO_ARRASTAR_LUGAR);
  expect(m.registo.camposPedidos).toEqual([{ id: NEGOCIO, fields: ['location'] }]);
});

test('usarNegocio: a Google falha com reserva → o pino no ponto tocado (google, o mesmo id, por arrastar) e o painel diz porquê', async () => {
  // O lugar não existe (NOT_FOUND), a Google falha, ou o lugar vem sem posição.
  for (const lugar of [undefined, { ...POSICAO_NEGOCIO, falha: true }, { lat: null, lng: null }]) {
    const m = preparar();
    if (lugar) m.registo.lugares[NEGOCIO] = lugar;
    m.seletor.escolherNegocio(NEGOCIO, { reserva: TOQUE });
    await expect(m.seletor.usarNegocio()).resolves.toBe(false);
    expect(m.registo.camposPedidos).toEqual([{ id: NEGOCIO, fields: ['location'] }]);
    expect(posicoesDosPinos(m.mapa())).toEqual([TOQUE]);
    expect(m.mapa().zoom).toBe(ZOOM_MORADA);
    expect(m.seletor.vista.negocio).toEqual({
      placeId: NEGOCIO, reserva: TOQUE, estado: 'erro', mensagem: TEXTO_LUGAR_INDISPONIVEL,
    });
    expect(m.seletor.vista.confirmarAtivo).toBe(false);
    expect(m.seletor.vista.dica).toBe(TEXTO_ARRASTAR_LUGAR);
    m.seletor.confirmar();
    expect(m.seletor.localizacao).toBeNull();
    pino(m.mapa()).arrastarPara(38.71015, -9.14025);
    m.seletor.confirmar();
    expect(m.seletor.localizacao).toEqual({
      lat: 38.71015, lng: -9.14025, origem_coords: 'pin_manual', precisao_m: null, google_place_id: NEGOCIO,
    });
  }
});

test('usarNegocio: a Google falha sem reserva → só a mensagem (o pino fica); tocar outra vez na ação volta a pedir', async () => {
  const m = preparar();
  tocar(m.mapa(), 38.7, -9.15);
  // Um toque num negócio sem ponto legível: o painel abre sem reserva.
  m.seletor.escolherNegocio(NEGOCIO, { reserva: { lat: null, lng: null } });
  await expect(m.seletor.usarNegocio()).resolves.toBe(false);
  expect(m.seletor.vista.negocio).toEqual({
    placeId: NEGOCIO, reserva: null, estado: 'erro', mensagem: TEXTO_LUGAR_INDISPONIVEL,
  });
  expect(posicoesDosPinos(m.mapa())).toEqual([{ lat: 38.7, lng: -9.15 }]);
  expect(m.seletor.vista.dica).toBe(TEXTO_ARRASTAR);
  expect(m.seletor.vista.confirmarAtivo).toBe(true);
  // Do erro volta-se a posicionar: agora a Google responde.
  lugares(m.registo);
  const promessa = m.seletor.usarNegocio();
  expect(m.seletor.vista.negocio.estado).toBe('a_posicionar');
  await expect(promessa).resolves.toBe(true);
  expect(posicoesDosPinos(m.mapa())).toEqual([POSICAO_NEGOCIO]);
  expect(m.registo.camposPedidos.length).toBe(2);
  // Sem pino nenhum antes e sem reserva: continua sem pino.
  const sem = preparar();
  await expect(sem.seletor.usarNegocio(NEGOCIO)).resolves.toBe(false);
  expect(sem.mapa().marcadores.length).toBe(0);
  expect(sem.seletor.vista.negocio.estado).toBe('erro');
});

test('um usarNegocio tardio é ignorado: outro negócio, um toque à mão, o painel fechado ou o pino noutro sítio entretanto', async () => {
  const casos = {
    'outro negócio tocado': (m) => m.mapa().fire('click', eventoDeToque({ lat: 38.72, lng: -9.13, placeId: 'ChIJ-outro' })),
    'um toque à mão': (m) => tocar(m.mapa(), 38.7, -9.15),
    'o painel fechado': (m) => m.seletor.fecharNegocio(),
    'outro sítio (colocar)': (m) => m.seletor.colocar({ lat: 38.7, lng: -9.15, origem: 'geocoder' }),
  };
  for (const [caso, entretanto] of Object.entries(casos)) {
    // Tanto a resposta boa como a falha (que poria o pino na reserva) chegam tarde.
    for (const conhecido of [true, false]) {
      const m = preparar();
      if (conhecido) lugares(m.registo);
      const soltar = atrasar(m.google, NEGOCIO);
      m.seletor.escolherNegocio(NEGOCIO, { reserva: TOQUE });
      const promessa = m.seletor.usarNegocio();
      entretanto(m);
      const pinos = posicoesDosPinos(m.mapa());
      const { negocio } = m.seletor.vista;
      soltar();
      await expect(promessa).resolves.toBe(false);
      expect([caso, posicoesDosPinos(m.mapa())]).toEqual([caso, pinos]);
      expect([caso, m.seletor.vista.negocio]).toEqual([caso, negocio]);
    }
  }
});

// Revisão do mapa Google (MAPA-G-4 / G-ENG-2): arrastar o pino, escolher na pesquisa, "Estou nesta loja" ou
// "Pôr o pino neste negócio" são escolhas novas — o que chegar depois de uma escolha anterior (a posição de um
// negócio, o lugar da pesquisa, a posição do GPS) já não tira o pino do sítio da escolha mais recente.
test('arrastar o pino enquanto a posição do negócio chega: fica o arrasto, o painel fecha e a resposta é ignorada', async () => {
  const INICIAL = { lat: 38.70921, lng: -9.13712, origem: 'pin_manual' };
  const ARRASTADO = { lat: 38.70925, lng: -9.13716 };
  for (const conhecido of [true, false]) {
    const m = preparar({ inicial: INICIAL });
    if (conhecido) lugares(m.registo);
    const soltar = atrasar(m.google, NEGOCIO);
    m.seletor.escolherNegocio(NEGOCIO, { reserva: TOQUE });
    const promessa = m.seletor.usarNegocio();
    expect(m.seletor.vista.negocio.estado).toBe('a_posicionar');
    pino(m.mapa()).arrastarPara(ARRASTADO.lat, ARRASTADO.lng);
    // O painel não fica preso em "A posicionar o pino…".
    expect(m.seletor.vista.negocio.estado).toBe('fechado');
    soltar();
    await expect(promessa).resolves.toBe(false);
    expect([conhecido, posicoesDosPinos(m.mapa())]).toEqual([conhecido, [ARRASTADO]]);
    expect(m.seletor.vista.negocio.estado).toBe('fechado');
    expect(m.seletor.vista.confirmarAtivo).toBe(true);
    m.seletor.confirmar();
    expect(m.seletor.localizacao).toEqual({ ...ARRASTADO, origem_coords: 'pin_manual', precisao_m: null, google_place_id: null });
  }
  // Depois do arrasto, a ação volta a pedir (não fica presa no pedido ignorado).
  const m = preparar({ inicial: INICIAL });
  lugares(m.registo);
  const soltar = atrasar(m.google, NEGOCIO);
  m.seletor.escolherNegocio(NEGOCIO, { reserva: TOQUE });
  const ignorada = m.seletor.usarNegocio();
  pino(m.mapa()).arrastarPara(ARRASTADO.lat, ARRASTADO.lng);
  m.seletor.escolherNegocio(NEGOCIO, { reserva: TOQUE });
  const outra = m.seletor.usarNegocio();
  expect(outra).not.toBe(ignorada);
  soltar();
  await expect(ignorada).resolves.toBe(false);
  await expect(outra).resolves.toBe(true);
  expect(posicoesDosPinos(m.mapa())).toEqual([POSICAO_NEGOCIO]);
});

test('arrastar o pino com o painel do negócio só aberto (sem pedido a caminho): o painel fica, com a ação', () => {
  const m = preparar({ inicial: { lat: 38.70921, lng: -9.13712, origem: 'pin_manual' } });
  m.seletor.escolherNegocio(NEGOCIO, { reserva: TOQUE });
  pino(m.mapa()).arrastarPara(38.70925, -9.13716);
  expect(m.seletor.vista.negocio).toEqual({ placeId: NEGOCIO, reserva: TOQUE, estado: 'aberto', mensagem: null });
});

test('uma morada da pesquisa que chega depois de outra escolha é ignorada: um toque à mão, um arrasto, o GPS, um negócio', async () => {
  const casos = {
    'um toque à mão': async (m) => tocar(m.mapa(), 38.7003, -9.1503),
    'um arrasto': async (m) => pino(m.mapa()).arrastarPara(38.7001, -9.1501),
    'o GPS': async (m) => gps(m, 38.7002, -9.1502, 10),
    'um negócio': async (m) => {
      m.seletor.escolherNegocio(NEGOCIO, { reserva: TOQUE });
      await m.seletor.usarNegocio();
    },
  };
  for (const [caso, entretanto] of Object.entries(casos)) {
    // Também uma falha da Google que chegue tarde não mostra o erro sobre a escolha mais recente.
    for (const conhecido of [true, false]) {
      const m = preparar({ gps: true, comApi: false });
      lugares(m.registo);
      if (!conhecido) delete m.registo.lugares[PESQUISADO];
      tocar(m.mapa(), 38.7, -9.15);
      const soltar = atrasar(m.google, PESQUISADO);
      pesquisa(m).escolher(PESQUISADO);
      await entretanto(m);
      const pinos = posicoesDosPinos(m.mapa());
      const { vista } = m.seletor;
      soltar();
      await esperar();
      expect([caso, conhecido, posicoesDosPinos(m.mapa())]).toEqual([caso, conhecido, pinos]);
      expect([caso, conhecido, m.seletor.vista === vista]).toEqual([caso, conhecido, true]);
      expect([caso, conhecido, m.escolhidas]).toEqual([caso, conhecido, []]);
    }
  }
});

test('escolher na pesquisa enquanto chegam a posição de um negócio ou o GPS: conta a pesquisa (a escolha mais recente)', async () => {
  // A posição do negócio a caminho: o painel fecha logo e a posição que chegue depois é ignorada.
  const n = preparar();
  lugares(n.registo);
  const soltarNegocio = atrasar(n.google, NEGOCIO);
  n.seletor.escolherNegocio(NEGOCIO, { reserva: TOQUE });
  const promessa = n.seletor.usarNegocio();
  pesquisa(n).escolher(PESQUISADO);
  expect(n.seletor.vista.negocio.estado).toBe('fechado');
  await esperar();
  expect(posicoesDosPinos(n.mapa())).toEqual([POSICAO_AUGUSTA]);
  soltarNegocio();
  await expect(promessa).resolves.toBe(false);
  expect(posicoesDosPinos(n.mapa())).toEqual([POSICAO_AUGUSTA]);
  expect(n.escolhidas).toEqual([MORADA_AUGUSTA]);
  // O GPS a responder: a posição que chegue depois da escolha (antes da morada da Google) é ignorada.
  const g = preparar({ gps: true, comApi: false });
  lugares(g.registo);
  const soltarPesquisa = atrasar(g.google, PESQUISADO);
  g.seletor.estouNestaLoja();
  pesquisa(g).escolher(PESQUISADO);
  g.geo.pedidos.at(-1).sucesso({ coords: { latitude: 38.75, longitude: -9.2, accuracy: 10 } });
  await esvaziar();
  expect(g.mapa().marcadores.length).toBe(0);
  expect(g.seletor.vista.gps.texto).toBe(TEXTO_ESTOU_NESTA_LOJA);
  soltarPesquisa();
  await esperar();
  expect(posicoesDosPinos(g.mapa())).toEqual([POSICAO_AUGUSTA]);
  expect(g.mapa().circulos.length).toBe(0);
  expect(g.escolhidas).toEqual([MORADA_AUGUSTA]);
});

test('"Estou nesta loja" enquanto chega a posição de um negócio, e um negócio enquanto o GPS responde: conta a escolha mais recente', async () => {
  const a = preparar({ gps: true, comApi: false });
  lugares(a.registo);
  const soltar = atrasar(a.google, NEGOCIO);
  a.seletor.escolherNegocio(NEGOCIO, { reserva: TOQUE });
  const promessa = a.seletor.usarNegocio();
  a.seletor.estouNestaLoja();
  expect(a.seletor.vista.negocio.estado).toBe('fechado');
  soltar();
  await expect(promessa).resolves.toBe(false);
  expect(a.mapa().marcadores.length).toBe(0);
  a.geo.pedidos.at(-1).sucesso({ coords: { latitude: 38.75, longitude: -9.2, accuracy: 10 } });
  await esvaziar();
  expect(posicoesDosPinos(a.mapa())).toEqual([{ lat: 38.75, lng: -9.2 }]);

  const b = preparar({ gps: true, comApi: false });
  lugares(b.registo);
  b.seletor.estouNestaLoja();
  b.seletor.escolherNegocio(NEGOCIO, { reserva: TOQUE });
  await expect(b.seletor.usarNegocio()).resolves.toBe(true);
  b.geo.pedidos.at(-1).sucesso({ coords: { latitude: 38.75, longitude: -9.2, accuracy: 10 } });
  await esvaziar();
  expect(posicoesDosPinos(b.mapa())).toEqual([POSICAO_NEGOCIO]);
  expect(b.mapa().circulos.length).toBe(0);
  expect(b.seletor.vista.gps.texto).toBe(TEXTO_ESTOU_NESTA_LOJA);
  expect(b.seletor.vista.gps.ocupado).toBe(false);
});

test('"Pôr o pino neste negócio" é a escolha mais recente: o GPS ou a pesquisa que respondam antes da posição do negócio são ignorados', async () => {
  // Cada caso começa a sua escolha e devolve como ela responde (a pesquisa responde sozinha: o lugar não se atrasa).
  const comecos = {
    'o GPS': (m) => {
      m.seletor.estouNestaLoja();
      return () => m.geo.pedidos.at(-1).sucesso({ coords: { latitude: 38.75, longitude: -9.2, accuracy: 10 } });
    },
    'a pesquisa': (m) => {
      pesquisa(m).escolher(PESQUISADO);
      return () => {};
    },
  };
  for (const [caso, comecar] of Object.entries(comecos)) {
    const m = preparar({ gps: true, comApi: false });
    lugares(m.registo);
    const soltar = atrasar(m.google, NEGOCIO);
    const responder = comecar(m);
    m.seletor.escolherNegocio(NEGOCIO, { reserva: TOQUE });
    const promessa = m.seletor.usarNegocio();
    // O GPS ou o lugar da pesquisa chegam primeiro: já não contam.
    responder();
    await esperar();
    expect([caso, m.mapa().marcadores.length, m.seletor.vista.negocio.estado]).toEqual([caso, 0, 'a_posicionar']);
    expect([caso, m.escolhidas]).toEqual([caso, []]);
    soltar();
    await expect(promessa).resolves.toBe(true);
    expect([caso, posicoesDosPinos(m.mapa())]).toEqual([caso, [POSICAO_NEGOCIO]]);
    expect([caso, m.mapa().circulos.length, m.seletor.vista.moradaSugerida]).toEqual([caso, 0, null]);
  }
});

test('dois toques seguidos na ação do painel: um só pedido à Google', async () => {
  const m = preparar();
  lugares(m.registo);
  m.seletor.escolherNegocio(NEGOCIO, { reserva: TOQUE });
  const primeira = m.seletor.usarNegocio();
  const segunda = m.seletor.usarNegocio();
  expect(segunda).toBe(primeira);
  await primeira;
  expect(m.registo.camposPedidos).toEqual([{ id: NEGOCIO, fields: ['location'] }]);
  // Depois de posto, o painel fechou: sem negócio, nada se pede.
  await expect(m.seletor.usarNegocio()).resolves.toBe(false);
  expect(m.registo.camposPedidos.length).toBe(1);
});

test('usarNegocio com um identificador que não seja texto não vazio: nada se pede nem muda', async () => {
  const m = preparar();
  for (const id of [undefined, null, '', '   ', 42, { id: NEGOCIO }]) {
    await expect(m.seletor.usarNegocio(id, { reserva: TOQUE })).resolves.toBe(false);
  }
  expect(m.seletor.vista.negocio.estado).toBe('fechado');
  expect(m.registo.camposPedidos).toEqual([]);
  expect(m.mapa().marcadores.length).toBe(0);
});

test('um id que não seja texto (escolherNegocio ou usarNegocio) não estraga o pedido de outro negócio a caminho', async () => {
  const m = preparar();
  lugares(m.registo);
  const soltar = atrasar(m.google, NEGOCIO);
  m.seletor.escolherNegocio(NEGOCIO, { reserva: TOQUE });
  const promessa = m.seletor.usarNegocio();
  for (const id of [null, '', '   ', 42, { id: 'ChIJ-outro' }]) {
    m.seletor.escolherNegocio(id, { reserva: { lat: 38.72, lng: -9.13 } });
    await expect(m.seletor.usarNegocio(id, { reserva: TOQUE })).resolves.toBe(false);
  }
  expect(m.seletor.vista.negocio.estado).toBe('a_posicionar');
  soltar();
  await expect(promessa).resolves.toBe(true);
  expect(posicoesDosPinos(m.mapa())).toEqual([POSICAO_NEGOCIO]);
  expect(m.registo.camposPedidos).toEqual([{ id: NEGOCIO, fields: ['location'] }]);
});

test('sem mapa (antes de iniciar, ou sem Google): o painel não abre e nada se pede à Google', async () => {
  for (const opcoes of [{ iniciar: false }, { configuracao: null }, { configuracao: { google: null, centro: CENTRO } }]) {
    const { seletor, registo } = preparar(opcoes);
    lugares(registo);
    seletor.escolherNegocio(NEGOCIO, { reserva: TOQUE });
    await expect(seletor.usarNegocio(NEGOCIO, { reserva: TOQUE })).resolves.toBe(false);
    expect(seletor.vista.negocio.estado).toBe('fechado');
    expect(registo.camposPedidos).toEqual([]);
    expect(registo.marcadores.length).toBe(0);
  }
});

test('destruir com a posição do negócio a caminho: a resposta não põe o pino nem muda nada', async () => {
  for (const conhecido of [true, false]) {
    const m = preparar();
    if (conhecido) lugares(m.registo);
    const soltar = atrasar(m.google, NEGOCIO);
    m.seletor.escolherNegocio(NEGOCIO, { reserva: TOQUE });
    const promessa = m.seletor.usarNegocio();
    m.seletor.destruir();
    const vista = m.seletor.vista;
    const vistas = m.vistas.length;
    soltar();
    await expect(promessa).resolves.toBe(false);
    expect(m.seletor.vista).toBe(vista);
    expect(m.vistas.length).toBe(vistas);
    expect(m.registo.marcadores.length).toBe(0);
  }
});

test('nenhum dado do negócio (nem a morada da Google dele) chega à vista, ao ecrã ou à localização confirmada', async () => {
  const m = preparar({ gps: true });
  lugares(m.registo);
  m.mapa().fire('click', eventoDeToque({ ...TOQUE, placeId: NEGOCIO }));
  await m.seletor.usarNegocio();
  pino(m.mapa()).arrastarPara(38.71036, -9.14049);
  m.seletor.confirmar();
  // E a pesquisa: só a morada (as sentinelas do lugar pesquisado também não).
  m.seletor.alterar();
  pesquisa(m).escolher(PESQUISADO);
  await esperar();
  pino(m.mapa()).arrastarPara(38.71023, -9.13697);
  m.seletor.confirmar();
  expect(m.vistas.length).toBeGreaterThan(5);
  for (const vista of m.vistas) expect(semSentinelas(vista)).toBe(true);
  expect(semSentinelas(m.mudancas)).toBe(true);
  expect(semSentinelas(m.escolhidas)).toBe(true);
  expect(m.mudancas.filter(Boolean).map((l) => l.google_place_id)).toEqual([NEGOCIO, PESQUISADO]);
  for (const { fields } of m.registo.camposPedidos) {
    for (const campo of fields) expect(['id', 'location', 'formattedAddress', 'addressComponents']).toContain(campo);
  }
});

// --- A pesquisa da Google (G11) ---------------------------------------------------------------------

test('iniciar cria a pesquisa da Google, só com lugares de Portugal, e a vista mostra-a ({ativa, elemento})', () => {
  const { seletor, registo, elemento } = preparar({ iniciar: false });
  expect(seletor.vista.pesquisa).toEqual({ ativa: false, elemento: null });
  expect(registo.pesquisas.length).toBe(0); // a pesquisa nasce com o mapa
  seletor.iniciar(elemento);
  expect(registo.pesquisas.length).toBe(1);
  const [criada] = registo.pesquisas;
  expect(seletor.vista.pesquisa.ativa).toBe(true);
  expect(seletor.vista.pesquisa.elemento).toBe(criada);
  expect(criada.opcoes).toEqual({ includedRegionCodes: ['pt'] });
  seletor.iniciar(elemento); // já iniciado: a mesma
  expect(registo.pesquisas.length).toBe(1);
});

test('sem mapa, sem a biblioteca places, ou se a Google rebentar ao criar a pesquisa: não há pesquisa (o mapa fica)', () => {
  const semMapa = preparar({ configuracao: null });
  expect(semMapa.seletor.vista.pesquisa).toEqual({ ativa: false, elemento: null });
  expect(semMapa.registo.pesquisas.length).toBe(0);
  const casos = [
    (google) => ({ maps: { ...google.maps, places: undefined } }),
    (google) => ({
      maps: {
        ...google.maps,
        places: {
          ...google.maps.places,
          PlaceAutocompleteElement: function PesquisaQueRebenta() {
            throw new Error('a Google recusou a pesquisa');
          },
        },
      },
    }),
  ];
  for (const ajustarGoogle of casos) {
    const { seletor, mapa, iniciado } = preparar({ ajustarGoogle });
    expect(iniciado).toBe(true);
    expect(seletor.vista.semMapa).toBe(false);
    expect(seletor.vista.pesquisa).toEqual({ ativa: false, elemento: null });
    tocar(mapa(), 38.71, -9.14);
    expect(seletor.vista.confirmarAtivo).toBe(true);
  }
});

test('escolher uma sugestão: o pino solto na morada (google, o id, zoom da rua), "Morada sugerida: …" e o ecrã recebe a morada', async () => {
  const m = preparar({ gps: true });
  lugares(m.registo);
  pesquisa(m).escolher(PESQUISADO);
  await esperar();
  expect(m.registo.camposPedidos).toEqual([
    { id: PESQUISADO, fields: ['location', 'formattedAddress', 'addressComponents'] },
  ]);
  expect(posicoesDosPinos(m.mapa())).toEqual([POSICAO_AUGUSTA]);
  expect(m.mapa().centro).toEqual(POSICAO_AUGUSTA);
  expect(m.mapa().zoom).toBe(ZOOM_MORADA);
  // A morada da Google, sem a atribuição da Geoapify (o mapa à volta é o da Google).
  expect(moradaSugerida(m.seletor)).toBe(`Morada sugerida: ${ROTULO_AUGUSTA}`);
  expect(m.seletor.vista.moradaSugerida.tipo).toBeNull();
  expect(m.seletor.vista.moradaSugerida.partes.every((p) => p.url === null)).toBe(true);
  expect(m.escolhidas).toEqual([MORADA_AUGUSTA]);
  expect(Object.keys(m.escolhidas[0])).toEqual(['rotulo', 'morada', 'codigo_postal', 'localidade', 'lat', 'lng']);
  // Nunca a inversa da Geoapify para um ponto da Google (nem a morada sugerida do GPS).
  expect(inversas(m).length).toBe(0);
  expect(m.sugeridas).toEqual([]);
  // A regra do arrasto.
  expect(m.seletor.vista.estado).toBe('por_confirmar');
  expect(m.seletor.vista.dica).toBe(TEXTO_ARRASTAR_LUGAR);
  expect(m.seletor.vista.aviso).toBe('arrastar');
  expect(m.seletor.vista.confirmarAtivo).toBe(false);
  m.seletor.confirmar();
  expect(m.seletor.localizacao).toBeNull();
});

test('a morada escolhida, arrastada até à porta: confirma como pin_manual com o google_place_id; a morada sugerida fica', async () => {
  const m = preparar();
  lugares(m.registo);
  pesquisa(m).escolher(PESQUISADO);
  await esperar();
  pino(m.mapa()).arrastarPara(38.71023, -9.13697);
  expect(moradaSugerida(m.seletor)).toBe(`Morada sugerida: ${ROTULO_AUGUSTA}`);
  expect(m.seletor.vista.confirmarAtivo).toBe(true);
  m.seletor.confirmar();
  expect(m.seletor.localizacao).toEqual({
    lat: 38.71023, lng: -9.13697, origem_coords: 'pin_manual', precisao_m: null, google_place_id: PESQUISADO,
  });
  // Um toque à mão depois: a morada sugerida e o id saem.
  m.seletor.alterar();
  tocar(m.mapa(), 38.7, -9.15);
  expect(m.seletor.vista.moradaSugerida).toBeNull();
  m.seletor.confirmar();
  expect(m.seletor.localizacao.google_place_id).toBeNull();
});

test('escolher uma sugestão com a localização confirmada ou com o painel do negócio aberto: o pino vai para a morada', async () => {
  const m = preparar();
  lugares(m.registo);
  tocar(m.mapa(), 38.7, -9.15);
  m.seletor.confirmar();
  pesquisa(m).escolher(PESQUISADO);
  await esperar();
  expect(m.seletor.vista.estado).toBe('por_confirmar');
  expect(m.seletor.localizacao).toBeNull();
  expect(posicoesDosPinos(m.mapa())).toEqual([POSICAO_AUGUSTA]);
  m.seletor.escolherNegocio(NEGOCIO, { reserva: TOQUE });
  pesquisa(m).escolher(PESQUISADO);
  await esperar();
  expect(m.seletor.vista.negocio.estado).toBe('fechado');
  expect(m.escolhidas.length).toBe(2);
});

test('uma sugestão sem morada por extenso: o pino na mesma, sem morada sugerida, e o ecrã recebe o que houver', async () => {
  const m = preparar();
  m.registo.lugares['EiJ-so-o-ponto'] = { lat: 38.7, lng: -9.15 };
  pesquisa(m).escolher('EiJ-so-o-ponto');
  await esperar();
  expect(posicoesDosPinos(m.mapa())).toEqual([{ lat: 38.7, lng: -9.15 }]);
  expect(m.seletor.vista.moradaSugerida).toBeNull();
  expect(m.escolhidas).toEqual([{ rotulo: null, morada: null, codigo_postal: null, localidade: null, lat: 38.7, lng: -9.15 }]);
});

test('a pesquisa falha (a Google não dá o lugar, ou o gmp-error): o erro do seletor diz porquê e o pino fica', async () => {
  for (const falhar of [(el) => el.escolher('EiJ-inexistente'), (el) => el.falhar()]) {
    const m = preparar();
    lugares(m.registo);
    tocar(m.mapa(), 38.7, -9.15);
    falhar(pesquisa(m));
    await esperar();
    expect(m.seletor.vista.erro).toBe(TEXTO_LUGAR_INDISPONIVEL);
    expect(posicoesDosPinos(m.mapa())).toEqual([{ lat: 38.7, lng: -9.15 }]);
    expect(m.seletor.vista.confirmarAtivo).toBe(true);
    expect(m.seletor.vista.moradaSugerida).toBeNull();
    expect(m.escolhidas).toEqual([]);
    // Pôr o pino noutro sítio limpa o erro.
    tocar(m.mapa(), 38.71, -9.14);
    expect(m.seletor.vista.erro).toBeNull();
  }
});

test('limitesDoMapa: os limites que o mapa mostra (getBounds), ou null sem mapa; a pesquisa usa-os ao focar', () => {
  const m = preparar({ iniciar: false });
  expect(m.seletor.limitesDoMapa()).toBeNull();
  m.seletor.iniciar(m.elemento);
  expect(m.seletor.limitesDoMapa().toJSON()).toEqual(m.mapa().getBounds().toJSON());
  const elemento = pesquisa(m);
  elemento.dispatchEvent(new Event('focus'));
  expect(elemento.locationBias.toJSON()).toEqual(m.mapa().getBounds().toJSON());
  // O mapa mudou de sítio: ao focar outra vez, os limites novos.
  m.seletor.colocar({ lat: 38.8, lng: -9.3, origem: 'pin_manual' }, { zoom: ZOOM_MORADA });
  elemento.dispatchEvent(new Event('focus'));
  expect(elemento.locationBias.contains({ lat: 38.8, lng: -9.3 })).toBe(true);
  // A Google ainda sem limites (antes do primeiro desenho): null.
  m.mapa().getBounds = () => undefined;
  expect(m.seletor.limitesDoMapa()).toBeNull();
  m.seletor.destruir();
  expect(m.seletor.limitesDoMapa()).toBeNull();
});

test('destruir tira a pesquisa (o elemento sai de onde o ecrã o pôs); uma escolha a caminho ou depois não faz nada', async () => {
  const m = preparar();
  lugares(m.registo);
  const elemento = pesquisa(m);
  const contentor = m.documento.createElement('div');
  contentor.appendChild(elemento);
  const soltar = atrasar(m.google, PESQUISADO);
  elemento.escolher(PESQUISADO);
  m.seletor.destruir();
  expect(contentor.childNodes.length).toBe(0);
  const vistas = m.vistas.length;
  soltar();
  await esperar();
  elemento.escolher(PESQUISADO);
  elemento.falhar();
  await esperar();
  expect(m.registo.camposPedidos.length).toBe(1); // só a escolha de antes de destruir
  expect(m.vistas.length).toBe(vistas);
  expect(m.escolhidas).toEqual([]);
  expect(m.registo.marcadores.length).toBe(0);
});

test('partesMoradaSugerida com a fonte google: só "Morada sugerida: <rótulo>"; sem fonte, com a atribuição da Geoapify', () => {
  const google = partesMoradaSugerida('<b>x</b>', { fonte: 'google' });
  expect(google).toEqual([{ texto: 'Morada sugerida: ', url: null }, { texto: '<b>x</b>', url: null }]);
  expect(Object.isFrozen(google)).toBe(true);
  expect(google.every((p) => Object.isFrozen(p))).toBe(true);
  expect(texto(partesMoradaSugerida('Rua X'))).toBe('Morada sugerida: Rua X · Powered by Geoapify');
  expect(texto(partesMoradaSugerida('Rua X', { fonte: 'geoapify' }))).toBe('Morada sugerida: Rua X · Powered by Geoapify');
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
