/**
 * "A MINHA LOCALIZAÇÃO" — as regras do botão (`lib/crm/minhaLocalizacao.js`), sem React.
 *
 * Desenho de 2026-11-06. O GPS é o `gpsFalso` e o mapa é o `criarMapa` verdadeiro sobre o `googleFalso` (G5), para se
 * provar o que chega mesmo à Google: nada corre antes do toque, um só `watchPosition`, `clearWatch` ao parar, a
 * leitura seguinte não mexe no centro do mapa, o recomeço ao voltar a estar visível, os erros e as respostas que
 * chegam tarde.
 *
 * No fim, a regra de privacidade do desenho, lida do próprio código: a posição não sai do telemóvel para o portal.
 * Só as unidades de "A minha localização" tocam nela, e nenhuma fala com o servidor, grava no browser ou deixa
 * registos na consola.
 *
 * O Jest do CRA corre com `resetMocks`: os falsos criam-se dentro de cada teste.
 */
import fs from 'fs';
import path from 'path';

import { OPCOES_SEGUIMENTO } from './gps';
import { ZOOM_MINHA_POSICAO, criarMapa } from './mapa';
import {
  TEXTO_A_PROCURAR, TEXTO_MINHA_LOCALIZACAO, VISTA_INICIAL, criarMinhaLocalizacao,
} from './minhaLocalizacao';
import { documentoFalso } from './testes/domFalso';
import { googleFalso } from './testes/googleFalso';
import { coordenadas, gpsFalso } from './testes/gpsFalso';

const CONFIGURACAO = { google: { chave: 'chave-teste-navegador', map_id: 'map-id-teste' }, centro: { lat: 38.7369, lng: -9.1427 } };
const AQUI = [38.7223, -9.1393, 25];
const ALI = [38.7301, -9.1502, 12];
const ponto = ([lat, lng]) => ({ lat, lng });

// Só o que as regras usam do `document`: o `hidden` e o `visibilitychange`, com os ouvintes contados.
function paginaFalsa() {
  const ouvintes = new Set();
  const pagina = {
    hidden: false,
    get ouvintes() { return ouvintes.size; },
    addEventListener(tipo, fn) {
      expect(tipo).toBe('visibilitychange');
      ouvintes.add(fn);
    },
    removeEventListener(tipo, fn) {
      expect(tipo).toBe('visibilitychange');
      ouvintes.delete(fn);
    },
    mudar(hidden) {
      pagina.hidden = hidden;
      for (const fn of [...ouvintes]) fn();
    },
  };
  return pagina;
}

function novoMapa() {
  const documento = documentoFalso();
  const { google, registo } = googleFalso({ documento });
  const mapa = criarMapa({ google, documento, elemento: documento.createElement('div'), configuracao: CONFIGURACAO });
  return { mapa, registo, mapaGoogle: registo.mapas[0] };
}

function preparar({ gps = gpsFalso(), comMapa = true } = {}) {
  const pagina = paginaFalsa();
  const vistas = [];
  const avisos = [];
  const centros = [];
  const controlo = criarMinhaLocalizacao({
    geolocation: gps,
    documento: pagina,
    aoMudarVista: (vista) => vistas.push(vista),
    aoAvisar: (mensagem) => avisos.push(mensagem),
    aoCentrar: (...argumentos) => centros.push(argumentos),
  });
  const novo = novoMapa();
  if (comMapa) controlo.usarMapa(novo.mapa);
  const estados = () => vistas.map((vista) => vista.estado);
  return { ...novo, gps, pagina, controlo, vistas, avisos, centros, estados };
}

// Ligado: já tocou e a primeira leitura chegou.
function ligado(opcoes) {
  const ambiente = preparar(opcoes);
  ambiente.controlo.tocar();
  ambiente.gps.responder(...AQUI);
  return ambiente;
}

const pontoDaPessoa = (registo) => registo.marcadores[0]?.posicao() ?? null;

// --- Antes do toque ------------------------------------------------------------------------------

test('nada corre antes do toque: nem GPS, nem ouvintes, nem ponto, nem mexidas no mapa', () => {
  const { gps, pagina, registo, mapaGoogle, vistas } = preparar();
  expect(gps.seguimentos).toEqual([]);
  expect(gps.leiturasUnicas).toBe(0);
  expect(pagina.ouvintes).toBe(0);
  expect(registo.marcadores).toEqual([]);
  expect(registo.circulos).toEqual([]);
  expect(mapaGoogle.vistas).toEqual([]);
  expect(vistas).toEqual([]);
});

test('a vista inicial é a do botão desligado', () => {
  expect(VISTA_INICIAL).toEqual({
    estado: 'desligado', ligado: false, aProcurar: false, texto: 'A minha localização', rotulo: 'A minha localização',
  });
  expect(TEXTO_MINHA_LOCALIZACAO).toBe('A minha localização');
});

// --- Ligar ---------------------------------------------------------------------------------------

test('o toque arranca o GPS com um só watchPosition, com as opções do seguimento, e fica a procurar', () => {
  const { gps, controlo, vistas, registo } = preparar();
  controlo.tocar();
  expect(gps.seguimentos).toHaveLength(1);
  expect(gps.seguimentos[0].opcoes).toEqual({ ...OPCOES_SEGUIMENTO });
  expect(gps.leiturasUnicas).toBe(0);
  expect(vistas).toEqual([{
    estado: 'a_procurar', ligado: false, aProcurar: true, texto: TEXTO_A_PROCURAR, rotulo: 'A minha localização: a procurar…',
  }]);
  expect(registo.marcadores).toEqual([]);
});

test('tocar enquanto procura não pede outra vez: continua um só watchPosition', () => {
  const { gps, controlo, vistas } = preparar();
  controlo.tocar();
  controlo.tocar();
  controlo.tocar();
  expect(gps.seguimentos).toHaveLength(1);
  expect(gps.limpezas).toEqual([]);
  expect(vistas).toHaveLength(1);
});

test('a primeira leitura liga, mostra o ponto e o círculo, e centra o mapa uma vez, no zoom da posição', () => {
  const { gps, controlo, estados, registo, mapaGoogle } = preparar();
  controlo.tocar();
  gps.responder(...AQUI);
  expect(estados()).toEqual(['a_procurar', 'ligado']);
  expect(pontoDaPessoa(registo)).toEqual(ponto(AQUI));
  expect(registo.circulos.map((c) => c.getRadius())).toEqual([25]);
  expect(mapaGoogle.vistas).toEqual([
    { tipo: 'setCenter', centro: ponto(AQUI) },
    { tipo: 'setZoom', zoom: ZOOM_MINHA_POSICAO },
  ]);
});

// --- As leituras seguintes -----------------------------------------------------------------------

test('a leitura seguinte só move o ponto: o centro e o zoom do mapa ficam, e o botão não volta a desenhar-se', () => {
  const { gps, registo, mapaGoogle, vistas } = ligado();
  const vistasDoMapa = mapaGoogle.vistas.length;
  const estados = vistas.length;
  gps.responder(...ALI);
  gps.responder(38.74, -9.16, 8);
  expect(pontoDaPessoa(registo)).toEqual({ lat: 38.74, lng: -9.16 });
  expect(registo.marcadores).toHaveLength(1);
  expect(registo.circulos.map((c) => c.getRadius())).toEqual([8]);
  expect(mapaGoogle.vistas).toHaveLength(vistasDoMapa);
  expect(mapaGoogle.getCenter().toJSON()).toEqual(ponto(AQUI));
  expect(vistas).toHaveLength(estados);
  expect(gps.seguimentos).toHaveLength(1);
});

test('o mapa não persegue a pessoa: se ela olhar para outra zona, as leituras não a trazem de volta', () => {
  const { gps, mapaGoogle } = ligado();
  const outraZona = { lat: 41.15, lng: -8.61 };
  mapaGoogle.setCenter(outraZona);
  gps.responder(...ALI);
  expect(mapaGoogle.getCenter().toJSON()).toEqual(outraZona);
});

test('tocar com o ponto ligado volta a centrar na última leitura, sem mudar o zoom e sem outro GPS', () => {
  const { gps, controlo, mapaGoogle, vistas } = ligado();
  gps.responder(...ALI);
  mapaGoogle.setCenter({ lat: 41.15, lng: -8.61 });
  mapaGoogle.setZoom(11);
  const estados = vistas.length;
  controlo.tocar();
  expect(mapaGoogle.vistas.at(-1)).toEqual({ tipo: 'panTo', centro: ponto(ALI) });
  expect(mapaGoogle.getZoom()).toBe(11);
  expect(gps.seguimentos).toHaveLength(1);
  expect(gps.limpezas).toEqual([]);
  expect(vistas).toHaveLength(estados);
  // A leitura depois de voltar a centrar também não mexe no mapa.
  const vistasDoMapa = mapaGoogle.vistas.length;
  gps.responder(...AQUI);
  expect(mapaGoogle.vistas).toHaveLength(vistasDoMapa);
});

test('uma leitura sem precisão mostra só o ponto', () => {
  const { gps, controlo, registo } = preparar();
  controlo.tocar();
  gps.seguimentos[0].sucesso(coordenadas(38.7223, -9.1393, undefined));
  expect(pontoDaPessoa(registo)).toEqual({ lat: 38.7223, lng: -9.1393 });
  expect(registo.circulos).toEqual([]);
});

// --- Coordenadas inválidas -----------------------------------------------------------------------

test('coordenadas inválidas à primeira não ligam nada: continua a procurar, e a boa seguinte conta como a primeira', () => {
  const { gps, controlo, estados, registo, mapaGoogle } = preparar();
  controlo.tocar();
  gps.seguimentos[0].sucesso(coordenadas(Number.NaN, -9.1, 10));
  gps.seguimentos[0].sucesso({});
  expect(estados()).toEqual(['a_procurar']);
  expect(registo.marcadores).toEqual([]);
  expect(mapaGoogle.vistas).toEqual([]);
  gps.responder(...AQUI);
  expect(estados()).toEqual(['a_procurar', 'ligado']);
  expect(mapaGoogle.getCenter().toJSON()).toEqual(ponto(AQUI));
});

test('coordenadas inválidas com o ponto ligado: o ponto fica onde estava', () => {
  const { gps, registo } = ligado();
  gps.seguimentos[0].sucesso(coordenadas(120, -9.1, 10));
  gps.seguimentos[0].sucesso(coordenadas('38.7', -9.1, 10));
  expect(pontoDaPessoa(registo)).toEqual(ponto(AQUI));
});

// --- Os erros ------------------------------------------------------------------------------------

test('autorização recusada à primeira: desliga, para o GPS e explica como autorizar', () => {
  const { gps, pagina, controlo, estados, avisos, registo } = preparar();
  controlo.tocar();
  gps.falhar(1);
  expect(estados()).toEqual(['a_procurar', 'desligado']);
  expect(avisos).toEqual(['Autorize a localização nas definições do browser para ver onde está no mapa']);
  expect(gps.limpezas).toEqual([gps.seguimentos[0].id]);
  expect(pagina.ouvintes).toBe(0);
  expect(registo.marcadores).toEqual([]);
});

test('autorização tirada com o ponto ligado: desliga, tira o ponto e explica (o GPS não vai voltar)', () => {
  const { gps, estados, avisos, registo, pagina } = ligado();
  gps.falhar(1);
  expect(estados().at(-1)).toBe('desligado');
  expect(avisos).toHaveLength(1);
  expect(registo.marcadores).toEqual([]);
  expect(registo.circulos).toEqual([]);
  expect(gps.ativos()).toEqual([]);
  expect(pagina.ouvintes).toBe(0);
});

test.each([
  [2, 'Não foi possível obter a sua localização — tente outra vez'],
  [3, 'A localização demorou demasiado — tente outra vez'],
])('sem posição à primeira (código %i): desliga, para o GPS e pede para tentar de novo', (code, mensagem) => {
  const { gps, controlo, estados, avisos, pagina } = preparar();
  controlo.tocar();
  gps.falhar(code);
  expect(estados()).toEqual(['a_procurar', 'desligado']);
  expect(avisos).toEqual([mensagem]);
  expect(gps.ativos()).toEqual([]);
  expect(pagina.ouvintes).toBe(0);
});

test('browser sem GPS: desliga logo, pede para tentar de novo, e nada fica ligado', () => {
  for (const geolocation of [undefined, null, {}]) {
    const pagina = paginaFalsa();
    const vistas = [];
    const avisos = [];
    const controlo = criarMinhaLocalizacao({
      geolocation, documento: pagina, aoMudarVista: (v) => vistas.push(v.estado), aoAvisar: (m) => avisos.push(m),
    });
    controlo.tocar();
    expect(vistas).toEqual(['a_procurar', 'desligado']);
    expect(avisos).toEqual(['Este browser não permite obter a localização — tente outra vez ou use outro browser']);
    expect(pagina.ouvintes).toBe(0);
  }
});

test('falha sem ponto: tocar outra vez volta a tentar, com um GPS novo, e a primeira leitura centra', () => {
  const { gps, controlo, estados, mapaGoogle } = preparar();
  controlo.tocar();
  gps.falhar(3);
  controlo.tocar();
  expect(gps.seguimentos).toHaveLength(2);
  expect(gps.ativos()).toHaveLength(1);
  gps.responder(...AQUI);
  expect(estados()).toEqual(['a_procurar', 'desligado', 'a_procurar', 'ligado']);
  expect(mapaGoogle.getCenter().toJSON()).toEqual(ponto(AQUI));
});

test.each([[2], [3]])('falha depois de já haver ponto (código %i): sem aviso, o ponto fica e a leitura seguinte atualiza-o', (code) => {
  const { gps, avisos, estados, registo, mapaGoogle } = ligado();
  const vistasDoMapa = mapaGoogle.vistas.length;
  gps.falhar(code);
  gps.falhar(code);
  expect(avisos).toEqual([]);
  expect(estados().at(-1)).toBe('ligado');
  expect(pontoDaPessoa(registo)).toEqual(ponto(AQUI));
  // O GPS continua: não houve outro nem parou.
  expect(gps.seguimentos).toHaveLength(1);
  expect(gps.limpezas).toEqual([]);
  gps.responder(...ALI);
  expect(pontoDaPessoa(registo)).toEqual(ponto(ALI));
  expect(mapaGoogle.vistas).toHaveLength(vistasDoMapa);
});

test('um GPS que falha dentro do próprio watchPosition não deixa um seguimento pendurado', () => {
  const gps = gpsFalso();
  const seguirDeVerdade = gps.watchPosition;
  gps.watchPosition = (sucesso, erro, opcoes) => {
    const id = seguirDeVerdade(sucesso, erro, opcoes);
    erro({ code: 2 });
    return id;
  };
  const { controlo, estados, avisos } = preparar({ gps });
  controlo.tocar();
  expect(estados()).toEqual(['a_procurar', 'desligado']);
  expect(avisos).toHaveLength(1);
  expect(gps.ativos()).toEqual([]);
  expect(gps.limpezas).toEqual([1]);
});

test('o que chega depois da falha, ainda dentro do próprio watchPosition, não volta a ligar nem avisa outra vez', () => {
  const gps = gpsFalso();
  const seguirDeVerdade = gps.watchPosition;
  gps.watchPosition = (sucesso, erro, opcoes) => {
    const id = seguirDeVerdade(sucesso, erro, opcoes);
    erro({ code: 2 });
    sucesso(coordenadas(...AQUI));
    erro({ code: 3 });
    return id;
  };
  const { controlo, estados, avisos, registo } = preparar({ gps });
  controlo.tocar();
  expect(estados()).toEqual(['a_procurar', 'desligado']);
  expect(avisos).toHaveLength(1);
  expect(registo.marcadores).toEqual([]);
});

// --- Voltar a estar visível ----------------------------------------------------------------------

test('com a página escondida o GPS para, e ao voltar a estar visível recomeça: um só seguimento ativo', () => {
  const { gps, pagina } = ligado();
  pagina.mudar(true);
  expect(gps.ativos()).toEqual([]);
  expect(gps.seguimentos).toHaveLength(1);
  pagina.mudar(false);
  expect(gps.seguimentos).toHaveLength(2);
  expect(gps.ativos()).toEqual([gps.seguimentos[1]]);
  expect(gps.limpezas).toEqual([gps.seguimentos[0].id]);
});

test('voltar a estar visível sem o aviso de escondida também recomeça, sem ficarem dois seguimentos', () => {
  const { gps, pagina } = ligado();
  pagina.mudar(false);
  pagina.mudar(false);
  expect(gps.seguimentos).toHaveLength(3);
  expect(gps.ativos()).toEqual([gps.seguimentos[2]]);
});

test('ao recomeçar, o ponto fica e o botão continua ligado; a leitura seguinte só o move, sem mexer no mapa', () => {
  const { gps, pagina, registo, mapaGoogle, vistas } = ligado();
  const vistasDoMapa = mapaGoogle.vistas.length;
  const estados = vistas.length;
  pagina.mudar(true);
  expect(pontoDaPessoa(registo)).toEqual(ponto(AQUI));
  pagina.mudar(false);
  gps.responder(...ALI);
  expect(pontoDaPessoa(registo)).toEqual(ponto(ALI));
  expect(mapaGoogle.vistas).toHaveLength(vistasDoMapa);
  expect(vistas).toHaveLength(estados);
});

test('a resposta atrasada do seguimento de antes de recomeçar não conta', () => {
  const { gps, pagina, registo } = ligado();
  const antigo = gps.seguimentos[0];
  pagina.mudar(true);
  pagina.mudar(false);
  antigo.sucesso(coordenadas(...ALI));
  antigo.erro({ code: 1 });
  expect(pontoDaPessoa(registo)).toEqual(ponto(AQUI));
  expect(gps.ativos()).toHaveLength(1);
});

test('a procurar quando a página se esconde: ao voltar procura de novo, e a primeira leitura centra', () => {
  const { gps, controlo, pagina, estados, mapaGoogle } = preparar();
  controlo.tocar();
  pagina.mudar(true);
  pagina.mudar(false);
  expect(gps.ativos()).toEqual([gps.seguimentos[1]]);
  expect(estados()).toEqual(['a_procurar']);
  gps.responder(...AQUI);
  expect(estados()).toEqual(['a_procurar', 'ligado']);
  expect(mapaGoogle.getCenter().toJSON()).toEqual(ponto(AQUI));
});

test('recusa ao recomeçar: desliga e tira o ponto', () => {
  const { gps, pagina, estados, avisos, registo } = ligado();
  pagina.mudar(true);
  pagina.mudar(false);
  gps.falhar(1);
  expect(estados().at(-1)).toBe('desligado');
  expect(avisos).toHaveLength(1);
  expect(registo.marcadores).toEqual([]);
  expect(gps.ativos()).toEqual([]);
});

test('desligado, voltar a estar visível não liga nada (nunca sozinho)', () => {
  const { gps, controlo, pagina } = preparar();
  pagina.mudar(true);
  pagina.mudar(false);
  expect(gps.seguimentos).toEqual([]);
  controlo.tocar();
  gps.falhar(3);
  pagina.mudar(false);
  expect(gps.seguimentos).toHaveLength(1);
  expect(gps.ativos()).toEqual([]);
});

// --- O mapa que chega tarde ou é recriado --------------------------------------------------------

test('sem mapa ainda: tocar arranca o GPS, e o mapa que chegar recebe o ponto e o centro', () => {
  const { gps, controlo, estados, registo, mapa, mapaGoogle } = preparar({ comMapa: false });
  controlo.tocar();
  gps.responder(...AQUI);
  gps.responder(...ALI);
  expect(estados()).toEqual(['a_procurar', 'ligado']);
  expect(registo.marcadores).toEqual([]);
  controlo.usarMapa(mapa);
  expect(pontoDaPessoa(registo)).toEqual(ponto(ALI));
  expect(mapaGoogle.vistas).toEqual([
    { tipo: 'setCenter', centro: ponto(ALI) },
    { tipo: 'setZoom', zoom: ZOOM_MINHA_POSICAO },
  ]);
});

test('mapa recriado: o ponto volta a desenhar-se no novo, sem centrar outra vez, e o GPS não recomeça', () => {
  const { gps, controlo, mapa, registo } = ligado();
  mapa.destruir();
  controlo.usarMapa(null);
  gps.responder(...ALI); // sem mapa: fica guardada
  const outro = novoMapa();
  controlo.usarMapa(outro.mapa);
  expect(pontoDaPessoa(outro.registo)).toEqual(ponto(ALI));
  expect(outro.registo.circulos).toHaveLength(1);
  expect(outro.mapaGoogle.vistas).toEqual([]);
  expect(registo.marcadores).toEqual([]);
  expect(gps.seguimentos).toHaveLength(1);
  expect(gps.limpezas).toEqual([]);
});

test('trocar de mapa sem o destruir: o ponto sai do antigo', () => {
  const { controlo, registo } = ligado();
  const outro = novoMapa();
  controlo.usarMapa(outro.mapa);
  expect(registo.marcadores).toEqual([]);
  expect(registo.circulos).toEqual([]);
  expect(outro.registo.marcadores).toHaveLength(1);
});

test('voltar a centrar sem mapa fica para quando ele chegar', () => {
  const { controlo, mapa } = ligado();
  mapa.destruir();
  controlo.usarMapa(null);
  controlo.tocar();
  const outro = novoMapa();
  controlo.usarMapa(outro.mapa);
  expect(outro.mapaGoogle.vistas).toEqual([{ tipo: 'panTo', centro: ponto(AQUI) }]);
});

test('aoCentrar: diz à página cada centro feito (a primeira leitura e o toque), e as leituras seguintes não contam', () => {
  const { gps, controlo, mapa, centros } = ligado();
  expect(centros).toEqual([[mapa]]);
  gps.responder(...ALI);
  expect(centros).toHaveLength(1);
  controlo.tocar();
  expect(centros).toEqual([[mapa], [mapa]]);
});

test('aoCentrar: sem mapa não há centro, e o que ficou por fazer avisa com o mapa que chegar', () => {
  const { gps, controlo, centros } = preparar({ comMapa: false });
  controlo.tocar();
  gps.responder(...AQUI);
  expect(centros).toEqual([]);
  const { mapa } = novoMapa();
  controlo.usarMapa(mapa);
  expect(centros).toEqual([[mapa]]);
});

test('aoCentrar: o toque de voltar a centrar guardado sem mapa também avisa, com o mapa que chegar', () => {
  const { controlo, mapa, centros } = ligado();
  mapa.destruir();
  controlo.usarMapa(null);
  controlo.tocar();
  expect(centros).toHaveLength(1);
  const outro = novoMapa();
  controlo.usarMapa(outro.mapa);
  expect(centros).toEqual([[mapa], [outro.mapa]]);
});

test('aoCentrar: o mapa recriado sem centro por fazer não avisa, e a primeira vista dele é da página', () => {
  const { controlo, mapa, centros } = ligado();
  mapa.destruir();
  controlo.usarMapa(novoMapa().mapa);
  expect(centros).toEqual([[mapa]]);
});

test('o mesmo mapa outra vez não desenha nem centra de novo', () => {
  const { controlo, mapa, mapaGoogle } = ligado();
  const vistasDoMapa = mapaGoogle.vistas.length;
  controlo.usarMapa(mapa);
  expect(mapaGoogle.vistas).toHaveLength(vistasDoMapa);
});

// --- Sair do ecrã --------------------------------------------------------------------------------

test('destruir para o GPS (clearWatch uma vez), tira o ponto e o ouvinte da página', () => {
  const { gps, controlo, pagina, registo } = ligado();
  expect(pagina.ouvintes).toBe(1);
  controlo.destruir();
  controlo.destruir();
  expect(gps.limpezas).toEqual([gps.seguimentos[0].id]);
  expect(registo.marcadores).toEqual([]);
  expect(registo.circulos).toEqual([]);
  expect(pagina.ouvintes).toBe(0);
});

test('destruir a meio da procura também para o GPS', () => {
  const { gps, controlo } = preparar();
  controlo.tocar();
  controlo.destruir();
  expect(gps.ativos()).toEqual([]);
});

test('destruir sem nunca ter tocado não mexe em nada', () => {
  const { gps, controlo, mapaGoogle } = preparar();
  controlo.destruir();
  expect(gps.limpezas).toEqual([]);
  expect(mapaGoogle.vistas).toEqual([]);
});

test('as respostas que chegam depois de sair do ecrã não contam: nem ponto, nem aviso, nem vista', () => {
  const { gps, controlo, registo, vistas, avisos } = preparar();
  controlo.tocar();
  const { sucesso, erro } = gps.seguimentos[0];
  controlo.destruir();
  const estados = vistas.length;
  sucesso(coordenadas(...AQUI));
  erro({ code: 1 });
  expect(registo.marcadores).toEqual([]);
  expect(avisos).toEqual([]);
  expect(vistas).toHaveLength(estados);
});

test('depois de destruir, tocar e receber um mapa não fazem nada (a montagem desfeita do StrictMode)', () => {
  const { gps, controlo, pagina, mapa, registo } = preparar();
  controlo.destruir();
  controlo.tocar();
  controlo.usarMapa(mapa);
  expect(gps.seguimentos).toEqual([]);
  expect(pagina.ouvintes).toBe(0);
  expect(registo.marcadores).toEqual([]);
});

test('uma resposta que chega depois de a recusa desligar não volta a ligar', () => {
  const { gps, controlo, estados, registo } = preparar();
  controlo.tocar();
  const { sucesso } = gps.seguimentos[0];
  gps.falhar(1);
  sucesso(coordenadas(...AQUI));
  expect(estados()).toEqual(['a_procurar', 'desligado']);
  expect(registo.marcadores).toEqual([]);
});

// --- A posição não sai do telemóvel --------------------------------------------------------------

const SRC = path.join(__dirname, '..', '..');
const ler = (relativo) => fs.readFileSync(path.join(SRC, relativo), 'utf8');

// As unidades por onde passa a posição, com tudo o que cada uma importa: uma importação nova tem de se ver aqui.
const UNIDADES = {
  'lib/crm/gps.js': [],
  'lib/crm/minhaLocalizacao.js': ['./gps', './mapa'],
  'lib/crm/mapa.js': ['./dom', './fases'],
  'components/crm/BotaoMinhaLocalizacao.js': [
    'react', 'sonner', 'lucide-react', '../ui/button', '../../lib/crm/minhaLocalizacao',
  ],
};

// O que faria a posição sair do telemóvel, ficar gravada ou ficar nos registos. O texto inteiro conta, comentários
// incluídos.
const FUGAS = [
  ['api', /(?:from\s+|import\s*\(\s*|import\s+|require\(\s*)['"][^'"]*\bapi(?:\.js)?['"]/g],
  ['axios', /\baxios\b/g],
  ['fetch', /\bfetch\b/g],
  ['XMLHttpRequest', /\bXMLHttpRequest\b/g],
  ['sendBeacon', /\bsendBeacon\b/g],
  ['WebSocket', /\bWebSocket\b/g],
  ['EventSource', /\bEventSource\b/g],
  ['localStorage', /\blocalStorage\b/g],
  ['sessionStorage', /\bsessionStorage\b/g],
  ['indexedDB', /\bindexedDB\b/g],
  ['cookie', /\bcookie\b/g],
  ['console', /\bconsole\b/g],
];

const fugasEm = (codigo) => FUGAS.filter(([, padrao]) => codigo.search(padrao) !== -1).map(([nome]) => nome);

// Os módulos importados, pela ordem do ficheiro.
const importacoesDe = (codigo) => [...codigo.matchAll(/^import\s[^;]*?from\s+'([^']+)';|^import\s+'([^']+)';/gm)]
  .map((m) => m[1] ?? m[2]);

test.each([
  ["import { obterConfigMapa } from './api';", 'api'],
  ["import api from '../../lib/crm/api';", 'api'],
  ["import { api } from '../../lib/api.js';", 'api'],
  ["const { enviar } = require('./api');", 'api'],
  ["const modulo = await import('./api');", 'api'],
  ["import axios from 'axios';", 'axios'],
  ["await fetch('/api/crm/posicao', { method: 'POST' });", 'fetch'],
  ["window.fetch('/x');", 'fetch'],
  ['const pedido = new XMLHttpRequest();', 'XMLHttpRequest'],
  ["navigator.sendBeacon('/x', dados);", 'sendBeacon'],
  ["new WebSocket('wss://x');", 'WebSocket'],
  ["new EventSource('/x');", 'EventSource'],
  ["localStorage.setItem('crm.posicao', texto);", 'localStorage'],
  ["window.sessionStorage.setItem('crm.posicao', texto);", 'sessionStorage'],
  ["indexedDB.open('crm');", 'indexedDB'],
  ["document.cookie = 'crm=1';", 'cookie'],
  ['console.log(leitura);', 'console'],
  ["window.console.info('leitura', leitura);", 'console'],
])('o detetor de fugas apanha: %s', (amostra, nome) => {
  expect(fugasEm(amostra)).toContain(nome);
});

test('o detetor de fugas deixa passar o código seguro', () => {
  expect(fugasEm("import { seguirPosicao } from './gps';\nconst rapida = 1;\ncontrolo.current?.usarMapa(mapa);")).toEqual([]);
});

test('importacoesDe lê as importações de uma e de várias linhas', () => {
  const amostra = "import a from 'a';\nimport {\n  b,\n  c,\n} from './b';\nimport './crm.css';\nconst d = 1;\n";
  expect(importacoesDe(amostra)).toEqual(['a', './b', './crm.css']);
});

test.each(Object.keys(UNIDADES))('%s não fala com o servidor, não grava nada no browser nem escreve na consola', (relativo) => {
  const codigo = ler(relativo);
  expect(codigo.length).toBeGreaterThan(0);
  expect(fugasEm(codigo)).toEqual([]);
  expect(importacoesDe(codigo)).toEqual(UNIDADES[relativo]);
});

test('o que elas importam também não: nem a api, nem o axios, nem o browser', () => {
  for (const relativo of ['lib/crm/dom.js', 'lib/crm/fases.js']) {
    expect([relativo, fugasEm(ler(relativo))]).toEqual([relativo, []]);
    expect([relativo, importacoesDe(ler(relativo))]).toEqual([relativo, []]);
  }
});

// Os `.js` de código do CRM (sem os testes e os falsos), como no seguranca.test.js.
function codigoDoCrm() {
  const ficheiros = [];
  const visitar = (relativo) => {
    for (const entrada of fs.readdirSync(path.join(SRC, relativo), { withFileTypes: true })) {
      const caminho = `${relativo}/${entrada.name}`;
      if (entrada.isDirectory()) {
        if (entrada.name !== 'testes') visitar(caminho);
      } else if (/\.jsx?$/.test(entrada.name) && !/\.test\.jsx?$/.test(entrada.name)) {
        ficheiros.push(caminho);
      }
    }
  };
  ['lib/crm', 'components/crm', 'pages/crm'].forEach(visitar);
  return ficheiros;
}

test('watchPosition só no gps.js, e o seguirPosicao só nas regras de "A minha localização" (o resultado só vai para o mapa)', () => {
  const ficheiros = codigoDoCrm();
  expect(ficheiros).toContain('lib/crm/gps.js');
  expect(ficheiros).toContain('pages/crm/CrmMapa.js');
  const comPalavra = (palavra) => ficheiros.filter((relativo) => new RegExp(`\\b${palavra}\\b`).test(ler(relativo)));
  expect(comPalavra('watchPosition')).toEqual(['lib/crm/gps.js']);
  expect(comPalavra('seguirPosicao').sort()).toEqual(['lib/crm/gps.js', 'lib/crm/minhaLocalizacao.js']);
});

test('as regras só entregam a posição ao mapa: o aviso, a vista e o aoCentrar nunca a levam', () => {
  const { gps, controlo, mapa, vistas, avisos, centros } = ligado();
  controlo.tocar();
  gps.responder(...ALI);
  gps.falhar(1);
  const dito = JSON.stringify({ vistas, avisos });
  expect(dito).not.toContain('38.7');
  expect(dito).not.toContain('-9.1');
  expect(centros).toEqual([[mapa], [mapa]]); // só o mapa, o mesmo que já tem a posição
  for (const vista of vistas) {
    expect(Object.keys(vista).sort()).toEqual(['aProcurar', 'estado', 'ligado', 'rotulo', 'texto']);
  }
});
