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
 */
import fs from 'fs';
import path from 'path';
import { FASES, ORDEM } from './fases';

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
