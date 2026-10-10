/**
 * O CSS DO MAPA (`components/crm/crm.css`) — as regras que só se veem no
 * browser, conferidas aqui pelo texto.
 *
 * Correção "T2.23 (porta do mapa.test.js e seguranca.test.js) / T2.25": escrito
 * antes do `crm.css`, lê-o com `path.join(__dirname, …)` (o `import.meta` do
 * autónomo não funciona no Jest do CRA). Porta do teste do app.css do
 * `tests/js/mapa.test.js` (as cores dos pinos) e dos três testes de CSS do
 * `tests/js/ecra-mapa.test.js` do CRM autónomo (etiqueta
 * `referencia-standalone`): sem juntas entre os mosaicos, o nome inteiro na
 * etiqueta e o mapa que encolhe com o cartão aberto. As classes são as do
 * portal (`.crm-mapa` em vez de `.mapa`).
 *
 * A mais: a bola do pino usa as variáveis das classes das fases (as cores
 * estão num só sítio), a etiqueta tem cores fixas (o mapa é claro também no
 * tema escuro do portal), não há regras soltas de `.etiqueta-loja` (pintavam
 * duas caixas: nota da T2.23) e as amostras de cor dos filtros e do cartão
 * usam as mesmas classes dos pinos.
 *
 * T2.26: o pino do seletor da localização (a gota do `.pino-seletor`, da cor
 * do círculo da precisão, e roxo-escuro depois de confirmar) e a altura
 * própria do mapa do seletor.
 */
import fs from 'fs';
import path from 'path';
import { FASES, ORDEM } from './fases';
import { ESTILO_CIRCULO } from './seletor';

const CAMINHO = path.join(__dirname, '../../components/crm/crm.css');
// Sem comentários: uma regra comentada não conta.
const CSS = fs.readFileSync(CAMINHO, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');

const escapar = (texto) => texto.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// O corpo da primeira regra com exatamente este seletor (no início de uma linha), ou null.
function regra(seletor) {
  const encontrada = CSS.match(new RegExp(`(?:^|\\n)[ \\t]*${escapar(seletor)}\\s*\\{([^}]*)\\}`));
  return encontrada ? encontrada[1] : null;
}

// Todos os seletores do ficheiro (o texto antes de cada "{", partido nas vírgulas).
const seletores = () =>
  [...CSS.matchAll(/([^{}]+)\{/g)].flatMap((m) => m[1].split(',').map((s) => s.trim())).filter(Boolean);

test('cada fase tem a cor exata no pino (e o contorno da potencial)', () => {
  for (const fase of ORDEM) {
    const bloco = regra(`.pino--${fase}`);
    expect(bloco).not.toBeNull();
    expect(bloco).toMatch(new RegExp(`--cor-pino:\\s*${escapar(FASES[fase].cor)};`));
    if (FASES[fase].contorno !== null) {
      expect(bloco).toMatch(new RegExp(`--contorno-pino:\\s*${escapar(FASES[fase].contorno)};`));
    } else {
      expect(bloco).not.toMatch(/--contorno-pino/);
    }
  }
});

test('só há classes de pino para as fases que existem', () => {
  const fases = new Set(seletores().flatMap((s) => [...s.matchAll(/\.pino--([a-z0-9_-]+)/g)].map((m) => m[1])));
  expect([...fases].sort()).toEqual([...ORDEM].sort());
});

test('a bola do pino desenha-se com as variáveis das classes das fases', () => {
  const pino = regra('.pino');
  expect(pino).not.toBeNull();
  expect(pino).toMatch(/--cor-pino:\s*#cfcfcf;/);
  expect(pino).toMatch(/--contorno-pino:\s*#fff;/);
  const bola = regra('.pino::before');
  expect(bola).not.toBeNull();
  expect(bola).toMatch(/background:\s*var\(--cor-pino\);/);
  expect(bola).toMatch(/border:\s*3px solid var\(--contorno-pino\);/);
});

test('os mosaicos do mapa não mostram juntas brancas entre si (Chrome em ecrãs de alta resolução)', () => {
  // Defeito conhecido do Leaflet no Chromium com escalas fracionárias: aparecem linhas finas entre
  // os mosaicos. mix-blend-mode: plus-lighter faz os bordos semitransparentes somarem-se e tapa-as.
  const mosaico = regra('.crm-mapa img.leaflet-tile');
  expect(mosaico).not.toBeNull();
  expect(mosaico).toMatch(/mix-blend-mode:\s*plus-lighter;/);
  // Sem isolar o contentor dos mosaicos, a mistura soma também o fundo cinzento do mapa (#ddd)
  // e as juntas ficam brancas em vez de desaparecerem (visto no portal a 2026-10-11).
  const contentor = regra('.crm-mapa .leaflet-tile-container');
  expect(contentor).not.toBeNull();
  expect(contentor).toMatch(/isolation:\s*isolate;/);
});

test('a etiqueta da loja mostra o nome inteiro (sem reticências): os nomes compridos passam a outra linha', () => {
  const etiqueta = regra('.leaflet-tooltip.etiqueta-loja');
  expect(etiqueta).not.toBeNull();
  expect(etiqueta).not.toMatch(/text-overflow/);
  expect(etiqueta).not.toMatch(/overflow:\s*hidden/);
  expect(etiqueta).toMatch(/white-space:\s*normal;/); // o tooltip do Leaflet é nowrap
  expect(etiqueta).toMatch(/width:\s*max-content;/); // sem isto, o nome partia-se em cada palavra
  expect(etiqueta).toMatch(/max-width:\s*16rem;/);
});

test('a etiqueta tem cores fixas (o mapa é claro também no tema escuro) e não tem a seta do tooltip', () => {
  const etiqueta = regra('.leaflet-tooltip.etiqueta-loja');
  const fundo = etiqueta.match(/(?:^|;|\s)background:\s*([^;]+);/);
  const cor = etiqueta.match(/(?:^|;|\s)color:\s*([^;]+);/);
  expect(fundo).not.toBeNull();
  expect(cor).not.toBeNull();
  for (const valor of [fundo[1], cor[1]]) {
    expect(valor).not.toMatch(/var\(|currentcolor|inherit/i);
  }
  expect(regra('.leaflet-tooltip.etiqueta-loja::before')).toMatch(/display:\s*none;/);
});

test('o nome só se pinta no tooltip do Leaflet (uma regra solta de .etiqueta-loja pintava duas caixas)', () => {
  const soltos = seletores().filter((s) => /\.etiqueta-loja/.test(s) && !/\.leaflet-tooltip\.etiqueta-loja/.test(s));
  expect(soltos).toEqual([]);
});

test('o mapa tem altura explícita: ocupa a área toda e pode encolher com o cartão da loja aberto', () => {
  // O Leaflet precisa de uma área com tamanho: o mapa enche a vista (absoluto, de canto a canto).
  const mapa = regra('.crm-mapa');
  expect(mapa).not.toBeNull();
  expect(mapa).toMatch(/position:\s*absolute;/);
  expect(mapa).toMatch(/inset:\s*0;/);
  expect(mapa).toMatch(/isolation:\s*isolate;/); // os painéis do Leaflet (até 1000) ficam por baixo do menu
  // A vista ocupa o que sobra; com o cartão aberto encolhe até 8rem, para Ligar e Ver ficha caberem no
  // ecrã (telemóvel deitado incluído).
  const vista = regra('.crm-mapa__vista');
  expect(vista).not.toBeNull();
  expect(vista).toMatch(/position:\s*relative;/);
  expect(vista).toMatch(/flex:\s*1 1 0(?:%|px)?;/);
  const altura = vista.match(/min-height:\s*([\d.]+)rem;/);
  expect(altura).not.toBeNull();
  expect(Number(altura[1])).toBeLessThanOrEqual(8);
});

test('as amostras de cor (filtros e cartão) usam as classes dos pinos, com o mesmo cinzento por omissão', () => {
  const amostra = regra('.crm-amostra-fase');
  expect(amostra).not.toBeNull();
  expect(amostra).toMatch(/background:\s*var\(--cor-pino,\s*#cfcfcf\);/);
  expect(amostra).toMatch(/border:\s*2px solid var\(--contorno-pino,/);
});

// --- O seletor da localização (T2.26) --------------------------------------------------------------
// Porta das regras do .pino-seletor do app.css do autónomo: o pino do seletor é um L.divIcon sem HTML
// (seletor.js), e a gota desenha-se toda aqui.

test('o pino do seletor é uma gota roxa (a cor do círculo da precisão) cuja ponta fica no sítio da loja', () => {
  const area = regra('.pino-seletor');
  expect(area).not.toBeNull();
  expect(area).toMatch(/background:\s*transparent;/);
  const gota = regra('.pino-seletor::before');
  expect(gota).not.toBeNull();
  expect(gota).toMatch(new RegExp(`background:\\s*${escapar(ESTILO_CIRCULO.color)};`));
  expect(gota).toMatch(/border:\s*3px solid #fff;/);
  expect(gota).toMatch(/border-radius:\s*50% 50% 50% 0;/);
  expect(gota).toMatch(/transform:\s*rotate\(-45deg\);/);
  expect(gota).toMatch(/width:\s*28px;/);
  expect(gota).toMatch(/height:\s*28px;/);
  const ponto = regra('.pino-seletor::after');
  expect(ponto).not.toBeNull();
  expect(ponto).toMatch(/background:\s*#fff;/);
  expect(ponto).toMatch(/border-radius:\s*50%;/);
  // As duas partes da gota são do CSS (o ícone não leva HTML).
  for (const bloco of [gota, ponto]) {
    expect(bloco).toMatch(/content:\s*"";/);
    expect(bloco).toMatch(/position:\s*absolute;/);
  }
});

test('confirmada a localização, a gota fica roxo-escuro', () => {
  const confirmado = regra('.crm-seletor[data-estado="confirmado"] .pino-seletor::before');
  expect(confirmado).not.toBeNull();
  expect(confirmado).toMatch(/background:\s*#4f1f7d;/);
});

test('o mapa do seletor tem altura própria (o .crm-mapa é absoluto dentro dela)', () => {
  const vista = regra('.crm-seletor__vista');
  expect(vista).not.toBeNull();
  expect(vista).toMatch(/position:\s*relative;/);
  expect(vista).toMatch(/height:\s*clamp\(16rem,\s*50vh,\s*28rem\);/);
  expect(vista).toMatch(/overflow:\s*hidden;/);
});

// A especificidade [ids, classes/atributos/pseudo-classes, elementos] de um seletor simples (sem :is/:where).
function especificidade(seletor) {
  const semPseudoElementos = seletor.replace(/::?(before|after)\b/g, '');
  const ids = (semPseudoElementos.match(/#[\w-]+/g) ?? []).length;
  const classes = (semPseudoElementos.match(/\.[\w-]+|\[[^\]]*\]|:[\w-]+/g) ?? []).length;
  const elementos = semPseudoElementos
    .split(/[\s>+~]+/)
    .map((parte) => parte.replace(/[.#[:].*$/, ''))
    .filter((nome) => nome !== '' && nome !== '*').length;
  return [ids, classes, elementos];
}

const ganha = (a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2];

test('os botões de zoom têm 44 px mesmo com o leaflet.css a seguir no build (ganham ao .leaflet-touch .leaflet-bar a)', () => {
  // O Leaflet põe a classe leaflet-touch em todos os browsers com PointerEvent (o Chrome do computador também), e
  // o leaflet.css dá 30 px a `.leaflet-touch .leaflet-bar a`. No build (e no `craco start`) o crm.css vem ANTES do
  // leaflet.css (o cartão e o formulário importam-no primeiro): com a mesma especificidade, ganhava o do Leaflet
  // (30 px, visto no browser na T2.32). A regra dos 44 px tem de ganhar pela especificidade, não pela ordem.
  const leaflet = fs.readFileSync(require.resolve('leaflet/dist/leaflet.css'), 'utf8');
  expect(leaflet).toMatch(/\.leaflet-touch \.leaflet-bar a \{\s*width: 30px;/);
  const doLeaflet = especificidade('.leaflet-touch .leaflet-bar a');
  const nossas = [...CSS.matchAll(/([^{}]+)\{([^}]*)\}/g)]
    .filter(([, , corpo]) => /(^|[\s;])width:\s*44px;/.test(corpo) && /(^|[\s;])height:\s*44px;/.test(corpo)
      && /line-height:\s*44px;/.test(corpo))
    .flatMap(([, seletores]) => seletores.split(',').map((s) => s.trim()))
    .filter((s) => s.endsWith('.leaflet-bar a'));
  expect(nossas.length).toBeGreaterThan(0);
  for (const seletor of nossas) {
    expect(seletor.startsWith('.crm-mapa')).toBe(true);
    expect(ganha(especificidade(seletor), doLeaflet)).toBeGreaterThan(0);
  }
});

test('a especificidade conta como o browser', () => {
  expect(especificidade('.leaflet-touch .leaflet-bar a')).toEqual([0, 2, 1]);
  expect(especificidade('.crm-mapa.leaflet-container .leaflet-bar a')).toEqual([0, 3, 1]);
  expect(especificidade('.leaflet-tooltip.etiqueta-loja::before')).toEqual([0, 2, 0]);
  expect(especificidade('.crm-seletor[data-estado="confirmado"] .pino-seletor::before')).toEqual([0, 3, 0]);
  expect(especificidade('.crm-mapa img.leaflet-tile')).toEqual([0, 2, 1]);
  expect(ganha([0, 3, 1], [0, 2, 1])).toBeGreaterThan(0);
  expect(ganha([0, 2, 1], [0, 2, 1])).toBe(0);
});
