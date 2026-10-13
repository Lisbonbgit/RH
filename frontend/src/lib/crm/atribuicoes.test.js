/**
 * AS ATRIBUIÇÕES OBRIGATÓRIAS DO MAPA E DA PESQUISA DE MORADA.
 *
 * Porta de tests/js/atribuicoes.test.js do CRM autónomo (etiqueta
 * `referencia-standalone`), com o `node:assert` passado a `expect`.
 *
 * O texto visível tem de ser exatamente o destes testes (desenho original §9;
 * dossiê §8). O `html` só existe para o controlo de atribuição do Leaflet
 * (`lib/crm/mapa.js`) e sai apenas das constantes do módulo, nunca de dados.
 * Os ecrãs React usam as `partes` (texto e ligação), sem HTML.
 */
import { ATRIBUICOES } from './atribuicoes';

const LIGACOES_PERMITIDAS = new Set([
  'https://www.geoapify.com/',
  'https://openmaptiles.org/',
  'https://www.openstreetmap.org/copyright',
]);

const semEtiquetas = (html) => html.replace(/<[^>]*>/g, '');
const hrefs = (html) => [...html.matchAll(/href="([^"]*)"/g)].map((m) => m[1]);

test('textos exatos das três atribuições', () => {
  expect(ATRIBUICOES.geoapify.texto).toBe(
    'Powered by Geoapify | © OpenMapTiles © OpenStreetMap contributors',
  );
  expect(ATRIBUICOES.osm.texto).toBe('© OpenStreetMap contributors');
  expect(ATRIBUICOES.pesquisa.texto).toBe('Powered by Geoapify');
  expect(Object.keys(ATRIBUICOES)).toEqual(['geoapify', 'osm', 'pesquisa']);
});

test('o HTML sem etiquetas é exatamente o texto (sem entidades)', () => {
  for (const a of Object.values(ATRIBUICOES)) {
    expect(semEtiquetas(a.html)).toBe(a.texto);
    expect(a.html.includes('&')).toBe(false);
  }
});

test('o HTML só tem ligações para os sítios dos créditos', () => {
  expect(hrefs(ATRIBUICOES.geoapify.html)).toEqual([
    'https://www.geoapify.com/',
    'https://openmaptiles.org/',
    'https://www.openstreetmap.org/copyright',
  ]);
  expect(hrefs(ATRIBUICOES.osm.html)).toEqual(['https://www.openstreetmap.org/copyright']);
  expect(hrefs(ATRIBUICOES.pesquisa.html)).toEqual(['https://www.geoapify.com/']);
});

test('as ligações abrem noutra janela com rel="noopener"', () => {
  for (const a of Object.values(ATRIBUICOES)) {
    const ancoras = a.html.match(/<a\b[^>]*>/g) ?? [];
    expect(ancoras.length).toBeGreaterThan(0);
    for (const ancora of ancoras) {
      expect(ancora).toMatch(/\btarget="_blank"/);
      expect(ancora).toMatch(/\brel="noopener"/);
    }
    const etiquetas = a.html.match(/<\/?([a-z]+)/g).map((t) => t.replace(/[</]/g, ''));
    expect(etiquetas.every((t) => t === 'a')).toBe(true);
  }
});

test('as partes (para montar com createElement) juntam-se no texto exato', () => {
  for (const a of Object.values(ATRIBUICOES)) {
    expect(a.partes.map((p) => p.texto).join('')).toBe(a.texto);
    for (const p of a.partes) {
      if (p.url !== null) {
        expect(LIGACOES_PERMITIDAS.has(p.url)).toBe(true);
      }
    }
  }
});

test('as atribuições não podem ser alteradas', () => {
  expect(Object.isFrozen(ATRIBUICOES)).toBe(true);
  for (const a of Object.values(ATRIBUICOES)) {
    expect(Object.isFrozen(a)).toBe(true);
    expect(Object.isFrozen(a.partes)).toBe(true);
    expect(a.partes.every((p) => Object.isFrozen(p))).toBe(true);
  }
});
