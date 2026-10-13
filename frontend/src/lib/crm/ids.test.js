/**
 * OS IDS DO PORTAL — uuid4 em texto.
 *
 * Sem equivalente no CRM autónomo, onde os ids eram inteiros positivos. No
 * portal, regiões, lojas e membros têm um `id` gravado com
 * `str(uuid.uuid4())` (plano §1, "Identificadores"), e o servidor só aceita
 * esse formato num `regiao_id` (`backend/crm/dominio/validador_loja.py`,
 * `_UUID4`). O `eUuid` é a mesma regra no frontend: os filtros do mapa (T2.21)
 * e as regras dos ecrãs da T2.24a (`carregarUltimaRegiao`, `lojaDuplicada`)
 * usam-no onde o autónomo pedia um inteiro positivo.
 *
 * O último teste lê o padrão do próprio `validador_loja.py`: uma cópia dentro
 * do teste não apanhava uma mudança do servidor.
 */
import fs from 'fs';
import path from 'path';

import { PADRAO_UUID4, eUuid } from './ids';

// frontend/src/lib/crm → raiz do repositório.
const VALIDADOR_PY = path.join(
  __dirname, '..', '..', '..', '..', 'backend', 'crm', 'dominio', 'validador_loja.py',
);

// Três `str(uuid.uuid4())` a sério e um de cada variante (8, 9, a, b).
const VALIDOS = [
  '3f1c2d4e-5a6b-4c7d-8e9f-0a1b2c3d4e5f',
  '7a8b9c0d-1e2f-4a3b-9c4d-5e6f7a8b9c0d',
  'c0ffee00-0000-4000-a000-000000000099',
  'b2c3d4e5-f6a7-4b8c-bd9e-0f1a2b3c4d5e',
];

test('aceita o uuid4 em texto que o servidor grava (minúsculas, versão 4, variante 8, 9, a ou b)', () => {
  for (const id of VALIDOS) {
    expect(eUuid(id)).toBe(true);
  }
});

test('recusa o que o servidor recusa: maiúsculas, espaços, outra versão ou variante, outro formato', () => {
  const [id] = VALIDOS;
  const invalidos = [
    id.toUpperCase(),
    '3F1c2d4e-5a6b-4c7d-8e9f-0a1b2c3d4e5f',
    ` ${id}`,
    `${id} `,
    `${id}\n`,
    `\n${id}`,
    id.replace(/-/g, ''),
    `{${id}}`,
    `urn:uuid:${id}`,
    '3f1c2d4e-5a6b-1c7d-8e9f-0a1b2c3d4e5f', // versão 1
    '3f1c2d4e-5a6b-5c7d-8e9f-0a1b2c3d4e5f', // versão 5
    '3f1c2d4e-5a6b-4c7d-7e9f-0a1b2c3d4e5f', // variante 7
    '3f1c2d4e-5a6b-4c7d-ce9f-0a1b2c3d4e5f', // variante c
    '3f1c2d4e-5a6b-4c7d-8e9f-0a1b2c3d4e5', // curto
    '3f1c2d4e-5a6b-4c7d-8e9f-0a1b2c3d4e5f0', // comprido
    '3f1c2d4g-5a6b-4c7d-8e9f-0a1b2c3d4e5f', // g não é hexadecimal
    '3f1c2d4e_5a6b_4c7d_8e9f_0a1b2c3d4e5f',
    '00000000-0000-0000-0000-000000000000',
    '',
    '1',
    '7',
  ];
  for (const valor of invalidos) {
    expect([valor, eUuid(valor)]).toEqual([valor, false]);
  }
});

test('só texto conta: números (os ids do autónomo), objetos e listas não são uuid', () => {
  const [id] = VALIDOS;
  // eslint-disable-next-line no-new-wrappers -- um String embrulhado também tem de ser recusado
  const embrulhado = new String(id);
  for (const valor of [1, 7, 0, -1, 1.5, NaN, Infinity, true, false, null, undefined, {}, [], [id], { id }, embrulhado]) {
    expect(eUuid(valor)).toBe(false);
  }
});

test('PADRAO_UUID4 é o padrão do servidor (validador_loja.py, _UUID4), lido do próprio ficheiro', () => {
  // Falha, e não salta, se o ficheiro não estiver lá (o mesmo cuidado do
  // fases.test.js e do backend/tests/faturacao/test_caminhos_do_pos.py).
  expect(fs.existsSync(VALIDADOR_PY)).toBe(true);
  const python = fs.readFileSync(VALIDADOR_PY, 'utf8');

  // Uma só linha `_UUID4 = re.compile(r"…")`, usada com `fullmatch`.
  const linhas = [...python.matchAll(/^_UUID4 = re\.compile\(r"([^"\n]*)"\)$/gm)];
  expect(linhas).toHaveLength(1);
  expect(PADRAO_UUID4).toBe(linhas[0][1]);
  expect(python).toMatch(/_UUID4\.fullmatch\(/);
});
