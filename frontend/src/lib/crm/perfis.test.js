/**
 * OS PERFIS DO CRM — valores da API e nomes em pt-PT.
 *
 * Porta de tests/js/perfis.test.js do CRM autónomo (etiqueta
 * `referencia-standalone`), com o `node:assert` passado a `expect` e o
 * terceiro perfil do portal (plano T2.21): `admin` "Administrador",
 * `utilizador` "Utilizador" e `motorista` "Motorista" (o motorista só entra
 * no terreno, na F4, mas já pode ser membro).
 *
 * A ordem é a do ecrã dos membros (T2.29), e não a do servidor: o mais comum
 * primeiro, porque o primeiro é o que o "Adicionar" escolhe por omissão (o
 * `PERFIL_INICIAL` do autónomo) — nunca o admin.
 *
 * Os valores têm de ser os do servidor (`backend/crm/dominio/membros.py`,
 * `PERFIS`), lidos do próprio ficheiro: uma cópia não apanhava uma mudança.
 */
import fs from 'fs';
import path from 'path';

import { PERFIS, rotuloPerfil } from './perfis';
import { PERFIS_CRM } from './eu';

// frontend/src/lib/crm → raiz do repositório.
const MEMBROS_PY = path.join(__dirname, '..', '..', '..', '..', 'backend', 'crm', 'dominio', 'membros.py');

test('PERFIS: os três perfis do CRM, o mais comum primeiro', () => {
  expect(PERFIS).toEqual([
    { valor: 'utilizador', rotulo: 'Utilizador' },
    { valor: 'admin', rotulo: 'Administrador' },
    { valor: 'motorista', rotulo: 'Motorista' },
  ]);
  expect(Object.isFrozen(PERFIS)).toBe(true);
  for (const perfil of PERFIS) {
    expect(Object.isFrozen(perfil)).toBe(true);
  }
});

test('o primeiro perfil (o que o ecrã dos membros escolhe por omissão) nunca é o admin', () => {
  expect(PERFIS[0].valor).toBe('utilizador');
});

test('rotuloPerfil: o nome do perfil em pt-PT; um valor desconhecido fica como está', () => {
  expect(rotuloPerfil('admin')).toBe('Administrador');
  expect(rotuloPerfil('utilizador')).toBe('Utilizador');
  expect(rotuloPerfil('motorista')).toBe('Motorista');
  expect(rotuloPerfil('outro')).toBe('outro');
  expect(rotuloPerfil(undefined)).toBe('');
});

test('rotuloPerfil: o que não é texto dá vazio; nomes do Object não são perfis', () => {
  for (const valor of [null, 42, true, {}, ['admin']]) {
    expect(rotuloPerfil(valor)).toBe('');
  }
  expect(rotuloPerfil('constructor')).toBe('constructor');
  expect(rotuloPerfil('Admin')).toBe('Admin');
});

test('os valores são os PERFIS_CRM do eu.js', () => {
  expect(PERFIS.map((p) => p.valor).sort()).toEqual([...PERFIS_CRM].sort());
});

test('os valores são os do servidor (backend/crm/dominio/membros.py, PERFIS), lidos do próprio ficheiro', () => {
  // Falha, e não salta, se o ficheiro não estiver lá (o mesmo cuidado do fases.test.js).
  expect(fs.existsSync(MEMBROS_PY)).toBe(true);
  const python = fs.readFileSync(MEMBROS_PY, 'utf8');

  // O membros.py mantém os PERFIS numa só linha: `PERFIS = ("admin", …)`.
  const linhas = [...python.matchAll(/^PERFIS = \(([^)\n]*)\)$/gm)];
  expect(linhas).toHaveLength(1);
  const valores = [...linhas[0][1].matchAll(/"([^"]*)"/g)].map((m) => m[1]);

  expect(PERFIS.map((p) => p.valor).sort()).toEqual([...valores].sort());
  expect(valores).toHaveLength(PERFIS.length);
});
