/**
 * O BOTÃO "A MINHA LOCALIZAÇÃO" — a ligação das regras ao ciclo de vida do React.
 *
 * As regras têm os testes delas (`lib/crm/minhaLocalizacao.test.js`). Aqui o componente corre no React de verdade
 * (`createRoot`, no jsdom), com o `StrictMode` que o `index.js` usa, para provar o que só a montagem mostra: nada corre
 * ao montar, desmontar para o GPS e tira o ponto, o mapa pode chegar tarde ou ser recriado, e o aspeto do botão.
 *
 * O Jest do CRA corre com `resetMocks`: os falsos criam-se dentro de cada teste.
 */
import fs from 'fs';
import path from 'path';

import React, { StrictMode, act } from 'react';
import { createRoot } from 'react-dom/client';
import { toast } from 'sonner';

import BotaoMinhaLocalizacao from './BotaoMinhaLocalizacao';
import { gpsFalso } from '../../lib/crm/testes/gpsFalso';

jest.mock('sonner', () => ({ toast: { error: jest.fn() } }));
// O atalho `@/` é do webpack (craco.config.js): o Jest do CRA não o conhece, e o botão do portal usa-o.
jest.mock('@/lib/utils', () => ({ cn: (...classes) => classes.filter(Boolean).join(' ') }), { virtual: true });

const AQUI = [38.7223, -9.1393, 25];

// O mapa do `criarMapa` nos dois métodos que o botão usa.
function mapaFalso() {
  return { mostrarMinhaPosicao: jest.fn(), centrarEm: jest.fn() };
}

let raiz;
let contentor;

function desenhar(mapa, { estrito = true } = {}) {
  const botao = <BotaoMinhaLocalizacao mapa={mapa} />;
  act(() => raiz.render(estrito ? <StrictMode>{botao}</StrictMode> : botao));
}

const botao = () => contentor.querySelector('button');
const tocar = () => act(() => botao().click());

function usarGps(gps) {
  Object.defineProperty(window.navigator, 'geolocation', { value: gps, configurable: true });
  return gps;
}

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  contentor = document.createElement('div');
  document.body.appendChild(contentor);
  raiz = createRoot(contentor);
});

afterEach(() => {
  act(() => raiz.unmount());
  contentor.remove();
  delete window.navigator.geolocation;
});

test('montar (com o StrictMode a montar duas vezes) não pede o GPS nem desenha nada', () => {
  const gps = usarGps(gpsFalso());
  const mapa = mapaFalso();
  desenhar(mapa);
  expect(gps.seguimentos).toEqual([]);
  expect(gps.leiturasUnicas).toBe(0);
  expect(mapa.mostrarMinhaPosicao).not.toHaveBeenCalled();
  expect(mapa.centrarEm).not.toHaveBeenCalled();
});

test('no StrictMode, um toque é um só watchPosition: as regras da montagem desfeita não ficam vivas', () => {
  const gps = usarGps(gpsFalso());
  desenhar(mapaFalso());
  tocar();
  expect(gps.seguimentos).toHaveLength(1);
});

test('desmontar para o GPS com o clearWatch, tira o ponto, e o que chegar depois não conta', () => {
  const gps = usarGps(gpsFalso());
  const mapa = mapaFalso();
  desenhar(mapa);
  tocar();
  act(() => gps.responder(...AQUI));
  const { sucesso } = gps.seguimentos[0];
  expect(gps.ativos()).toHaveLength(1);
  act(() => raiz.render(null));
  expect(gps.limpezas).toEqual([gps.seguimentos[0].id]);
  expect(gps.ativos()).toEqual([]);
  expect(mapa.mostrarMinhaPosicao).toHaveBeenLastCalledWith(null);
  const chamadas = mapa.mostrarMinhaPosicao.mock.calls.length;
  sucesso({ coords: { latitude: 38.73, longitude: -9.15, accuracy: 5 } });
  expect(mapa.mostrarMinhaPosicao).toHaveBeenCalledTimes(chamadas);
});

test('o mapa ainda não está pronto: o botão funciona, e o ponto e o centro chegam com o mapa', () => {
  const gps = usarGps(gpsFalso());
  desenhar(null);
  tocar();
  act(() => gps.responder(...AQUI));
  expect(botao().getAttribute('aria-pressed')).toBe('true');
  const mapa = mapaFalso();
  desenhar(mapa);
  expect(mapa.mostrarMinhaPosicao).toHaveBeenCalledWith({ lat: AQUI[0], lng: AQUI[1], precisao_m: 25 });
  expect(mapa.centrarEm).toHaveBeenCalledTimes(1);
});

test('o mapa recriado recebe o ponto sem centrar outra vez, e o GPS continua o mesmo', () => {
  const gps = usarGps(gpsFalso());
  const antigo = mapaFalso();
  desenhar(antigo);
  tocar();
  act(() => gps.responder(...AQUI));
  desenhar(null);
  const novo = mapaFalso();
  desenhar(novo);
  expect(novo.mostrarMinhaPosicao).toHaveBeenCalledTimes(1);
  expect(novo.centrarEm).not.toHaveBeenCalled();
  expect(gps.seguimentos).toHaveLength(1);
  expect(gps.limpezas).toEqual([]);
});

test('desligado: ícone, texto só em sm+, aria-label e aria-pressed a false, à altura dos outros botões da barra', () => {
  usarGps(gpsFalso());
  desenhar(mapaFalso());
  expect(botao().getAttribute('type')).toBe('button');
  expect(botao().getAttribute('aria-label')).toBe('A minha localização');
  expect(botao().getAttribute('aria-pressed')).toBe('false');
  expect(botao().hasAttribute('aria-disabled')).toBe(false);
  expect(botao().className).toMatch(/(?:^|\s)h-11(?:\s|$)/);
  expect(botao().querySelector('svg').getAttribute('aria-hidden')).toBe('true');
  const texto = botao().querySelector('span');
  expect(texto.textContent).toBe('A minha localização');
  expect(texto.className).toBe('hidden sm:inline');
});

test('a procurar: o estado vê-se (o ícone a rodar, em qualquer largura) e o botão fica com aria-disabled, sem perder o foco', () => {
  usarGps(gpsFalso());
  desenhar(mapaFalso());
  botao().focus();
  tocar();
  expect(botao().getAttribute('data-estado')).toBe('a_procurar');
  expect(botao().getAttribute('aria-disabled')).toBe('true');
  expect(botao().getAttribute('aria-label')).toBe('A minha localização: a procurar…');
  expect(botao().getAttribute('aria-pressed')).toBe('false');
  expect(botao().disabled).toBe(false);
  expect(document.activeElement).toBe(botao());
  expect(botao().querySelector('svg').getAttribute('class')).toMatch(/animate-spin/);
  expect(botao().querySelector('span').textContent).toBe('A procurar…');
});

test('ligado: aria-pressed a true, e o toque seguinte volta a centrar', () => {
  const gps = usarGps(gpsFalso());
  const mapa = mapaFalso();
  desenhar(mapa);
  tocar();
  act(() => gps.responder(...AQUI));
  expect(botao().getAttribute('aria-pressed')).toBe('true');
  expect(botao().hasAttribute('aria-disabled')).toBe(false);
  expect(botao().querySelector('svg').getAttribute('class')).not.toMatch(/animate-spin/);
  tocar();
  expect(mapa.centrarEm).toHaveBeenCalledTimes(2);
  expect(gps.seguimentos).toHaveLength(1);
});

test('um erro aparece no toast de erro, e o botão volta a desligado', () => {
  const gps = usarGps(gpsFalso());
  desenhar(mapaFalso());
  tocar();
  act(() => gps.falhar(1));
  expect(toast.error).toHaveBeenCalledTimes(1);
  expect(toast.error).toHaveBeenCalledWith('Autorize a localização nas definições do browser para ver onde está no mapa');
  expect(botao().getAttribute('data-estado')).toBe('desligado');
  expect(botao().getAttribute('aria-pressed')).toBe('false');
});

test('um browser sem GPS avisa ao tocar, sem rebentar', () => {
  desenhar(mapaFalso());
  tocar();
  expect(toast.error).toHaveBeenCalledTimes(1);
  expect(botao().getAttribute('data-estado')).toBe('desligado');
});

test('voltar a estar visível recomeça o seguimento; desmontar tira esse ouvinte', () => {
  const gps = usarGps(gpsFalso());
  desenhar(mapaFalso());
  tocar();
  act(() => gps.responder(...AQUI));
  act(() => {
    document.dispatchEvent(new Event('visibilitychange'));
  });
  expect(gps.seguimentos).toHaveLength(2);
  expect(gps.ativos()).toHaveLength(1);
  act(() => raiz.render(null));
  act(() => {
    document.dispatchEvent(new Event('visibilitychange'));
  });
  expect(gps.seguimentos).toHaveLength(2);
  expect(gps.ativos()).toEqual([]);
});

// --- Nas duas páginas ----------------------------------------------------------------------------

const fonte = (relativo) => fs.readFileSync(path.join(__dirname, '../..', relativo), 'utf8');

test.each(['pages/crm/CrmMapa.js', 'pages/crm/CrmRota.js'])('%s põe o botão na barra de cima, com o mapa da página', (relativo) => {
  const codigo = fonte(relativo);
  // Dentro da .crm-mapa__barra, sem nenhum elemento a fechar a barra pelo meio (`</div>`).
  expect(codigo).toMatch(/className="crm-mapa__barra">(?:(?!<\/div>)[\s\S])*<BotaoMinhaLocalizacao mapa=\{mapa\} \/>/);
  // A barra vem depois do mapa e dentro da vista dele.
  expect(codigo.indexOf('crm-mapa__vista')).toBeLessThan(codigo.indexOf('<MapaLojas'));
  expect(codigo.indexOf('<MapaLojas')).toBeLessThan(codigo.indexOf('className="crm-mapa__barra"'));
});

test('a barra só devolve os toques aos filhos diretos: o botão é um só elemento', () => {
  usarGps(gpsFalso());
  desenhar(mapaFalso());
  expect(Array.from(contentor.children)).toEqual([botao()]);
});
