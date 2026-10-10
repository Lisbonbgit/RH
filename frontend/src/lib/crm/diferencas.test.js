/**
 * AS DIFERENÇAS DA FICHA — o PATCH só leva o que mudou.
 *
 * Porta de tests/js/diferencas.test.js do CRM autónomo (etiqueta
 * `referencia-standalone`), tal e qual, com o `node:assert` passado a
 * `expect`. Regras: a localização é um bloco (lat, lng, origem_coords e
 * precisao_m vão juntos, como exige o `validador_loja.alteracao` do servidor);
 * um campo limpo no formulário (`''`) equivale a `null` e vai como `null`;
 * as listas (`dias_fechada`) são conjuntos.
 *
 * Os três últimos testes são extra: acrescentar um dia fechado (que o
 * autónomo não fixava) e a forma do portal, com ids uuid em texto
 * e as janelas planas da API (`janela1_inicio`…, plano §1 "Janelas").
 */
import { camposAlterados, CAMPOS_LOCALIZACAO } from './diferencas';

const original = {
  id: 7,
  nome: 'Café Central',
  fase: 'potencial',
  regiao_id: 2,
  telefone: null,
  morada: 'Rua Augusta 1',
  lat: 38.7075,
  lng: -9.1364,
  origem_coords: 'gps',
  precisao_m: 12,
  dias_fechada: ['sab', 'dom'],
  atualizado_em: '2026-10-03T09:00:00.123456Z',
};

test('sem alterações devolve objeto vazio', () => {
  expect(camposAlterados(original, { ...original })).toEqual({});
});

test('devolve só as chaves que mudaram, com o valor atual', () => {
  expect(camposAlterados(original, { ...original, nome: 'Café Novo', fase: 'contactada' })).toEqual({
    nome: 'Café Novo',
    fase: 'contactada',
  });
});

test('null passa a valor e valor passa a null', () => {
  expect(camposAlterados(original, { ...original, telefone: '912345678' })).toEqual({ telefone: '912345678' });
  expect(camposAlterados(original, { ...original, regiao_id: null })).toEqual({ regiao_id: null });
});

test('campo vazio do formulário equivale a null', () => {
  expect(camposAlterados(original, { ...original, telefone: '' })).toEqual({});
});

test('limpar um campo do formulário envia null (o "sem valor" da API), não string vazia', () => {
  expect(camposAlterados(original, { ...original, morada: '' })).toEqual({ morada: null });
  expect(camposAlterados(original, { ...original, regiao_id: '' })).toEqual({ regiao_id: null });
});

test('localização: precisão vazia no formulário vai como null no bloco', () => {
  expect(
    camposAlterados(original, { ...original, lat: 38.708, origem_coords: 'pin_manual', precisao_m: '' }),
  ).toEqual({ lat: 38.708, lng: -9.1364, origem_coords: 'pin_manual', precisao_m: null });
});

test('chaves que o formulário não traz são ignoradas', () => {
  const { id, atualizado_em, ...semMeta } = original;
  expect(camposAlterados(original, { ...semMeta, nome: 'X' })).toEqual({ nome: 'X' });
});

test('localização é um bloco: mudar só lat envia lat, lng, origem_coords e precisao_m', () => {
  expect(camposAlterados(original, { ...original, lat: 38.7080 })).toEqual({
    lat: 38.7080,
    lng: -9.1364,
    origem_coords: 'gps',
    precisao_m: 12,
  });
});

test('localização: mudar só a origem também envia o bloco inteiro', () => {
  expect(camposAlterados(original, { ...original, origem_coords: 'pin_manual', precisao_m: null })).toEqual({
    lat: 38.7075,
    lng: -9.1364,
    origem_coords: 'pin_manual',
    precisao_m: null,
  });
});

test('localização: bloco incompleto no atual completa-se com o original', () => {
  const { precisao_m, ...semPrecisao } = original;
  expect(camposAlterados(original, { ...semPrecisao, lng: -9.1370 })).toEqual({
    lat: 38.7075,
    lng: -9.1370,
    origem_coords: 'gps',
    precisao_m: 12,
  });
});

test('CAMPOS_LOCALIZACAO lista o bloco', () => {
  expect(CAMPOS_LOCALIZACAO).toEqual(['lat', 'lng', 'origem_coords', 'precisao_m']);
});

test('dias_fechada compara-se por valor, não por referência', () => {
  expect(camposAlterados(original, { ...original, dias_fechada: ['sab', 'dom'] })).toEqual({});
});

test('dias_fechada é um conjunto: a ordem não conta', () => {
  expect(camposAlterados(original, { ...original, dias_fechada: ['dom', 'sab'] })).toEqual({});
});

test('dias_fechada diferente é enviado', () => {
  expect(camposAlterados(original, { ...original, dias_fechada: ['seg'] })).toEqual({ dias_fechada: ['seg'] });
  expect(camposAlterados(original, { ...original, dias_fechada: [] })).toEqual({ dias_fechada: [] });
});

// --- Extra: o que os testes do autónomo não fixavam ---

test('dias_fechada: acrescentar um dia (ou o primeiro) também é enviado', () => {
  // Sem comparar os tamanhos, uma lista que começa como a original passava por igual.
  expect(camposAlterados(original, { ...original, dias_fechada: ['sab', 'dom', 'seg'] })).toEqual({
    dias_fechada: ['sab', 'dom', 'seg'],
  });
  expect(camposAlterados({ ...original, dias_fechada: [] }, { ...original, dias_fechada: ['seg'] })).toEqual({
    dias_fechada: ['seg'],
  });
});

// --- Extra: a forma do portal ---

test('portal: o regiao_id é um uuid em texto e compara-se tal e qual', () => {
  const lisboa = '3f1c2d4e-5a6b-4c7d-8e9f-0a1b2c3d4e5f';
  const porto = '7a8b9c0d-1e2f-4a3b-9c4d-5e6f7a8b9c0d';
  const loja = { ...original, id: 'b2c3d4e5-f6a7-4b8c-bd9e-0f1a2b3c4d5e', regiao_id: lisboa };
  expect(camposAlterados(loja, { ...loja })).toEqual({});
  expect(camposAlterados(loja, { ...loja, regiao_id: porto })).toEqual({ regiao_id: porto });
  expect(camposAlterados(loja, { ...loja, regiao_id: '' })).toEqual({ regiao_id: null });
  expect(camposAlterados({ ...loja, regiao_id: null }, { ...loja })).toEqual({ regiao_id: lisboa });
});

test('portal: as janelas são planas (janela1_inicio…); limpar uma hora envia null', () => {
  const loja = {
    ...original,
    janela1_inicio: '09:00',
    janela1_fim: '12:00',
    janela2_inicio: null,
    janela2_fim: null,
  };
  expect(camposAlterados(loja, { ...loja, janela2_inicio: '', janela2_fim: '' })).toEqual({});
  expect(camposAlterados(loja, { ...loja, janela1_fim: '13:00' })).toEqual({ janela1_fim: '13:00' });
  expect(camposAlterados(loja, { ...loja, janela1_inicio: '', janela1_fim: '' })).toEqual({
    janela1_inicio: null,
    janela1_fim: null,
  });
  expect(camposAlterados(loja, { ...loja, janela2_inicio: '14:00', janela2_fim: '17:30' })).toEqual({
    janela2_inicio: '14:00',
    janela2_fim: '17:30',
  });
});
