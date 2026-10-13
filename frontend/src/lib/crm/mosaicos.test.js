/**
 * QUANDO TROCAR PARA OS MOSAICOS ALTERNATIVOS (OSM).
 *
 * Porta de tests/js/mosaicos.test.js do CRM autónomo (etiqueta
 * `referencia-standalone`), com o `node:assert` passado a `expect`.
 *
 * Com 3 ou mais erros e mais erros do que sucessos, o mapa troca os mosaicos
 * da Geoapify pelos do OSM (com a atribuição do OSM). Troca uma só vez; depois
 * disso os contadores ficam como estavam. O `lib/crm/mapa.js` (T2.23) é quem
 * liga isto aos eventos `tileerror`/`tileload` do Leaflet.
 */
import { criarControloAlternativa } from './mosaicos';

const repetir = (n, fn) => {
  const resultados = [];
  for (let i = 0; i < n; i++) resultados.push(fn());
  return resultados;
};

test('começa sem erros, sem sucessos e sem ter mudado', () => {
  const c = criarControloAlternativa();
  expect(c.erros).toBe(0);
  expect(c.sucessos).toBe(0);
  expect(c.mudou).toBe(false);
});

test('com menos de 3 erros não muda', () => {
  const c = criarControloAlternativa();
  expect(repetir(2, () => c.registarErro())).toEqual([false, false]);
  expect(c.mudou).toBe(false);
  expect(c.erros).toBe(2);
});

test('ao 3.º erro sem sucessos muda para a alternativa', () => {
  const c = criarControloAlternativa();
  expect(repetir(3, () => c.registarErro())).toEqual([false, false, true]);
  expect(c.mudou).toBe(true);
});

test('com tantos sucessos como erros não muda; com mais erros muda', () => {
  const c = criarControloAlternativa();
  repetir(3, () => c.registarSucesso());
  expect(repetir(3, () => c.registarErro())).toEqual([false, false, false]);
  expect(c.mudou).toBe(false);
  expect(c.registarErro()).toBe(true);
  expect(c.mudou).toBe(true);
});

test('sucessos pelo meio contam (e,e,s,s,s,e não muda; o erro seguinte muda)', () => {
  const c = criarControloAlternativa();
  c.registarErro();
  c.registarErro();
  repetir(3, () => c.registarSucesso());
  expect(c.registarErro()).toBe(false);
  expect(c.erros).toBe(3);
  expect(c.sucessos).toBe(3);
  expect(c.registarErro()).toBe(true);
});

test('muitos sucessos exigem mais erros do que sucessos', () => {
  const c = criarControloAlternativa();
  repetir(10, () => c.registarSucesso());
  expect(repetir(10, () => c.registarErro()).every((r) => r === false)).toBe(true);
  expect(c.registarErro()).toBe(true);
});

test('só muda uma vez: depois de mudar, os erros seguintes devolvem false', () => {
  const c = criarControloAlternativa();
  repetir(3, () => c.registarErro());
  expect(c.mudou).toBe(true);
  expect(repetir(5, () => c.registarErro())).toEqual([false, false, false, false, false]);
  c.registarSucesso();
  expect(c.registarErro()).toBe(false);
  expect(c.mudou).toBe(true);
});

test('depois de mudar, os contadores ficam congelados', () => {
  const c = criarControloAlternativa();
  repetir(3, () => c.registarErro());
  c.registarErro();
  c.registarSucesso();
  expect(c.erros).toBe(3);
  expect(c.sucessos).toBe(0);
});

test('erros, sucessos e mudou só se leem (não se podem forçar de fora)', () => {
  const c = criarControloAlternativa();
  repetir(3, () => c.registarErro());
  expect(() => {
    c.mudou = false;
  }).toThrow(TypeError);
  expect(() => {
    c.erros = 0;
  }).toThrow(TypeError);
  expect(() => {
    c.sucessos = 99;
  }).toThrow(TypeError);
  expect(c.mudou).toBe(true);
  expect(c.erros).toBe(3);
  expect(c.sucessos).toBe(0);
  expect(c.registarErro()).toBe(false);
});

test('cada controlo é independente', () => {
  const a = criarControloAlternativa();
  const b = criarControloAlternativa();
  repetir(3, () => a.registarErro());
  expect(a.mudou).toBe(true);
  expect(b.mudou).toBe(false);
  expect(b.erros).toBe(0);
});
