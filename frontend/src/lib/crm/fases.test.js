/**
 * AS FASES DA LOJA — nomes, rótulos e cores exatas dos pinos.
 *
 * Porta de tests/js/fases.test.js do CRM autónomo (etiqueta
 * `referencia-standalone`), com o `node:assert` passado a `expect`.
 *
 * A `ORDEM` é a das regras automáticas e tem de ser a do servidor
 * (`backend/crm/dominio/fases.py`): os pinos, os filtros e o formulário usam a
 * daqui, e a API só aceita a de lá. Os dois lados vigiam-se um ao outro:
 *   - `backend/tests/crm/test_consistencia_frontend.py` lê este `fases.js`;
 *   - o último teste daqui lê o `fases.py` (uma lista copiada para dentro do
 *     teste não apanhava uma mudança do servidor).
 */
import fs from 'fs';
import path from 'path';

import { FASES, ORDEM, FUNIL, classePino } from './fases';

// frontend/src/lib/crm → raiz do repositório.
const FASES_PY = path.join(__dirname, '..', '..', '..', '..', 'backend', 'crm', 'dominio', 'fases.py');

test('ORDEM tem as 5 fases pela ordem das regras automáticas', () => {
  expect([...ORDEM]).toEqual(['perdida', 'potencial', 'contactada', 'amostra', 'cliente']);
});

test('FASES tem exatamente as 5 fases, pela mesma ordem de ORDEM', () => {
  expect(Object.keys(FASES)).toEqual([...ORDEM]);
  for (const id of ORDEM) {
    expect(FASES[id].id).toBe(id);
  }
});

test('cada fase tem o rótulo em pt-PT', () => {
  const rotulos = Object.fromEntries(ORDEM.map((id) => [id, FASES[id].rotulo]));
  expect(rotulos).toEqual({
    perdida: 'Perdida',
    potencial: 'Potencial',
    contactada: 'Contactada',
    amostra: 'Amostra',
    cliente: 'Cliente',
  });
});

test('cada fase tem a cor exata do pino (potencial com contorno #888)', () => {
  const cores = Object.fromEntries(
    ORDEM.map((id) => [id, { cor: FASES[id].cor, contorno: FASES[id].contorno }]),
  );
  expect(cores).toEqual({
    potencial: { cor: '#cfcfcf', contorno: '#888' },
    contactada: { cor: '#f4c20d', contorno: null },
    amostra: { cor: '#f08a24', contorno: null },
    cliente: { cor: '#6b2fa3', contorno: null },
    perdida: { cor: '#1a1a1a', contorno: null },
  });
});

test('FASES e ORDEM não podem ser alterados', () => {
  expect(Object.isFrozen(ORDEM)).toBe(true);
  expect(Object.isFrozen(FASES)).toBe(true);
  for (const id of ORDEM) {
    expect(Object.isFrozen(FASES[id])).toBe(true);
  }
});

test('classePino devolve a classe da fase só para fases conhecidas', () => {
  expect(classePino('cliente')).toBe('pino pino--cliente');
  expect(classePino('perdida')).toBe('pino pino--perdida');
  expect(classePino('xpto')).toBe('pino');
  expect(classePino('cliente extra')).toBe('pino');
  expect(classePino('constructor')).toBe('pino');
  expect(classePino(undefined)).toBe('pino');
  expect(classePino(null)).toBe('pino');
});

test('FUNIL tem as mesmas 5 fases pela ordem do funil (spec §4.1), para os filtros e o formulário', () => {
  expect([...FUNIL]).toEqual(['potencial', 'contactada', 'amostra', 'cliente', 'perdida']);
  expect([...FUNIL].sort()).toEqual([...ORDEM].sort());
  expect(Object.isFrozen(FUNIL)).toBe(true);
});

test('ORDEM é a mesma do servidor (backend/crm/dominio/fases.py), lida do próprio ficheiro', () => {
  // Falha, e não salta, se o ficheiro não estiver lá: um guarda que se desliga
  // sozinho passava a verde para sempre (o mesmo cuidado do
  // backend/tests/faturacao/test_caminhos_do_pos.py).
  expect(fs.existsSync(FASES_PY)).toBe(true);
  const python = fs.readFileSync(FASES_PY, 'utf8');

  // O fases.py mantém a ORDEM numa só linha: `ORDEM = ("perdida", …)`.
  const linhas = [...python.matchAll(/^ORDEM = \(([^)\n]*)\)$/gm)];
  expect(linhas).toHaveLength(1);
  const nomes = [...linhas[0][1].matchAll(/"([^"]*)"/g)].map((m) => m[1]);

  expect([...ORDEM]).toEqual(nomes);
});
