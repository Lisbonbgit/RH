/**
 * AS ATRIBUIÇÕES QUE O CRM ESCREVE (desenho original §9; dossiê §8).
 *
 * Desde o mapa Google (G8 do plano `2026-10-14-crm-mapa-google.md`), a
 * atribuição do mapa é a da própria Google: desenha-a a API, por cima do
 * mapa, e o CRM nunca a esconde, nunca a tapa e não a repete aqui. Saíram por
 * isso a do OpenStreetMap (`osm`), a da pesquisa de moradas da Geoapify
 * (`pesquisa`) e o `html` do mapa antigo. Fica só a Geoapify, de onde
 * vem a morada sugerida de um ponto do GPS ("Powered by Geoapify", com a
 * ligação); a F3 junta-lhe a do openrouteservice (`ors`).
 *
 * Os ecrãs montam cada parte como texto, ou, com `url`, como uma ligação: não
 * há HTML nenhum.
 */
import { ATRIBUICOES } from './atribuicoes';

test('só fica a atribuição da Geoapify (a do mapa é a da Google)', () => {
  // A F3 (planear rota) junta aqui `ors`.
  expect(Object.keys(ATRIBUICOES)).toEqual(['geoapify']);
});

test('"Powered by Geoapify" com a ligação para a Geoapify, numa só parte', () => {
  expect(ATRIBUICOES.geoapify.texto).toBe('Powered by Geoapify');
  expect(ATRIBUICOES.geoapify.partes).toEqual([{ texto: 'Powered by Geoapify', url: 'https://www.geoapify.com/' }]);
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
      // Sem ligação (`null`) ou uma ligação https.
      expect(parte.url === null || /^https:\/\/[^\s<>"']+$/.test(parte.url)).toBe(true);
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
