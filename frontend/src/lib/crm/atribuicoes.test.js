/**
 * AS ATRIBUIÇÕES QUE O CRM ESCREVE (desenho original §9; dossiê §8).
 *
 * Desde o mapa Google (G8 do plano `2026-10-14-crm-mapa-google.md`), a
 * atribuição do mapa é a da própria Google: desenha-a a API, por cima do
 * mapa, e o CRM nunca a esconde, nunca a tapa e não a repete aqui. Saíram por
 * isso a do OpenStreetMap (`osm`), a da pesquisa de moradas da Geoapify
 * (`pesquisa`) e o `html` do mapa antigo. Ficam:
 *   - a Geoapify, de onde vem a morada sugerida de um ponto do GPS ("Powered
 *     by Geoapify", com a ligação);
 *   - o openrouteservice (`ors`, F3 / T3.26), que calcula a ordem e as horas
 *     da rota: "Developed by VROOM · Hosted by HeiGIT · Routing by
 *     openrouteservice · Data from OpenStreetMap", sempre visível no
 *     planeador, num bloco próprio do painel (nunca sobre o mapa nem junto da
 *     atribuição da Google), com a frase `TEXTO_ROTA_DE_TERCEIROS` antes da
 *     linha da rota (Termos Específicos EEA da Google, §A.4.3; correções do
 *     mapa Google no plano da F3).
 *
 * Os ecrãs montam cada parte como texto, ou, com `url`, como uma ligação: não
 * há HTML nenhum.
 */
import { ATRIBUICOES, TEXTO_ROTA_DE_TERCEIROS } from './atribuicoes';

const ORS = 'Developed by VROOM · Hosted by HeiGIT · Routing by openrouteservice · Data from OpenStreetMap';

// A única ligação http: a que o plano da F3 fixa para o VROOM (T3.26).
const LIGACOES_HTTP = ['http://vroom-project.org/'];

test('as atribuições são a da Geoapify e a do openrouteservice (a do mapa é a da Google)', () => {
  expect(Object.keys(ATRIBUICOES)).toEqual(['geoapify', 'ors']);
});

test('"Powered by Geoapify" com a ligação para a Geoapify, numa só parte', () => {
  expect(ATRIBUICOES.geoapify.texto).toBe('Powered by Geoapify');
  expect(ATRIBUICOES.geoapify.partes).toEqual([{ texto: 'Powered by Geoapify', url: 'https://www.geoapify.com/' }]);
});

test('o texto exato do openrouteservice, com os pontos médios', () => {
  expect(ATRIBUICOES.ors.texto).toBe(ORS);
  expect(ATRIBUICOES.ors.texto).toBe(
    'Developed by VROOM · Hosted by HeiGIT · Routing by openrouteservice · Data from OpenStreetMap',
  );
});

test('o openrouteservice: VROOM, HeiGIT, openrouteservice e OpenStreetMap ligados, o resto em texto', () => {
  expect(ATRIBUICOES.ors.partes).toEqual([
    { texto: 'Developed by ', url: null },
    { texto: 'VROOM', url: 'http://vroom-project.org/' },
    { texto: ' · Hosted by ', url: null },
    { texto: 'HeiGIT', url: 'https://heigit.org/' },
    { texto: ' · Routing by ', url: null },
    { texto: 'openrouteservice', url: 'https://openrouteservice.org/' },
    { texto: ' · Data from ', url: null },
    { texto: 'OpenStreetMap', url: 'https://www.openstreetmap.org/copyright' },
  ]);
});

test('a frase da rota de terceiros, ao lado da atribuição do openrouteservice', () => {
  expect(TEXTO_ROTA_DE_TERCEIROS).toBe('Routing provided by openrouteservice');
  expect(typeof TEXTO_ROTA_DE_TERCEIROS).toBe('string');
});

test('nenhuma entrada tem html: só o texto e as partes', () => {
  for (const atribuicao of Object.values(ATRIBUICOES)) {
    expect(Object.keys(atribuicao)).toEqual(['texto', 'partes']);
    expect('html' in atribuicao).toBe(false);
  }
});

test('as partes juntam-se no texto exato e cada uma é só texto e ligação', () => {
  for (const atribuicao of Object.values(ATRIBUICOES)) {
    expect(atribuicao.partes.map((p) => p.texto).join('')).toBe(atribuicao.texto);
    for (const parte of atribuicao.partes) {
      expect(Object.keys(parte)).toEqual(['texto', 'url']);
      expect(typeof parte.texto).toBe('string');
      expect(parte.texto).not.toMatch(/[<>&]/);
      // Sem ligação (`null`), uma ligação https, ou a ligação http que o plano fixa para o VROOM.
      expect(parte.url === null || /^https:\/\/[^\s<>"']+$/.test(parte.url) || LIGACOES_HTTP.includes(parte.url)).toBe(true);
    }
  }
});

test('as atribuições não podem ser alteradas', () => {
  expect(Object.isFrozen(ATRIBUICOES)).toBe(true);
  for (const atribuicao of Object.values(ATRIBUICOES)) {
    expect(Object.isFrozen(atribuicao)).toBe(true);
    expect(Object.isFrozen(atribuicao.partes)).toBe(true);
    expect(atribuicao.partes.every((p) => Object.isFrozen(p))).toBe(true);
  }
});
