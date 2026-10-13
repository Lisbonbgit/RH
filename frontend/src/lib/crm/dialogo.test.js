/**
 * O DIÁLOGO DO DUPLICADO — "Já existe X aqui — é a mesma?" (as regras puras).
 *
 * Porta de public/assets/js/componentes/dialogo.js do CRM autónomo (etiqueta
 * `referencia-standalone`), com os casos de tests/js/dialogo.test.js que não
 * precisam de DOM: a loja da lista do 409 (`lojaDuplicada`), a mensagem com o
 * nome em negrito, os três botões ('Sim, abrir X', 'Não, é outra loja' e
 * 'Cancelar', correção "componentes Sem Jest") e "só conta a primeira
 * escolha". O `<dialog>` do autónomo passa a ser o `AlertDialog` do shadcn
 * (`components/crm/DialogoDuplicado.js`), que só desenha isto.
 *
 * Adaptação dos ids (plano T2.24a): a loja do 409 tem um uuid em texto
 * (`eUuid`), e não um inteiro positivo.
 */
import {
  RESPOSTA_ABRIR,
  RESPOSTA_OUTRA,
  TEXTO_CANCELAR,
  TEXTO_OUTRA_LOJA,
  criarEscolhaUnica,
  dialogoDuplicado,
  lojaDuplicada,
} from './dialogo';

const MERCEARIA = '0b6f3c1e-1111-4222-8333-444455556666';
const OUTRA = '0b6f3c1e-2222-4222-8333-444455556666';

test('lojaDuplicada: a primeira da lista do 409 (a mais perto), só com um uuid e um nome', () => {
  const perto = { id: MERCEARIA, nome: 'Mercearia da Baixa', distancia_m: 12 };
  expect(lojaDuplicada([perto, { id: OUTRA, nome: 'Outra', distancia_m: 40 }])).toBe(perto);
  const invalidas = [
    undefined, null, {}, [], 'x', [{ id: 7, nome: 'X' }], [{ id: '7', nome: 'X' }], [{ id: MERCEARIA }],
    [{ id: MERCEARIA, nome: 7 }], [{ id: MERCEARIA.toUpperCase(), nome: 'X' }], [null], [{ nome: 'X' }],
    // Só a primeira conta (é a mais perto): uma inválida à frente não deixa escolher a seguinte.
    [{ id: 0, nome: 'X' }, perto],
  ];
  for (const invalida of invalidas) {
    expect([invalida, lojaDuplicada(invalida)]).toEqual([invalida, null]);
  }
});

test('dialogoDuplicado: "Já existe X aqui — é a mesma?", com o nome em negrito', () => {
  const { mensagem } = dialogoDuplicado({ id: MERCEARIA, nome: 'Mercearia da Baixa', distancia_m: 12 });
  expect(mensagem).toEqual([
    { texto: 'Já existe ', forte: false },
    { texto: 'Mercearia da Baixa', forte: true },
    { texto: ' aqui — é a mesma?', forte: false },
  ]);
  expect(mensagem.map((p) => p.texto).join('')).toBe('Já existe Mercearia da Baixa aqui — é a mesma?');
});

test('dialogoDuplicado: "Sim, abrir X", "Não, é outra loja" e Cancelar, por esta ordem', () => {
  const { botoes } = dialogoDuplicado({ id: MERCEARIA, nome: 'Mercearia da Baixa', distancia_m: 12 });
  expect(botoes).toEqual([
    { texto: 'Sim, abrir Mercearia da Baixa', valor: 'abrir', variante: 'principal' },
    { texto: 'Não, é outra loja', valor: 'outra', variante: 'normal' },
    { texto: 'Cancelar', valor: null, variante: 'discreto' },
  ]);
  expect([RESPOSTA_ABRIR, RESPOSTA_OUTRA, TEXTO_OUTRA_LOJA, TEXTO_CANCELAR])
    .toEqual(['abrir', 'outra', 'Não, é outra loja', 'Cancelar']);
});

test('dialogoDuplicado: uma loja chamada <b>x</b> fica em texto (o React escreve-o como texto)', () => {
  const { mensagem, botoes } = dialogoDuplicado({ id: MERCEARIA, nome: '<b>x</b>', distancia_m: 1 });
  expect(mensagem[1]).toEqual({ texto: '<b>x</b>', forte: true });
  expect(botoes[0].texto).toBe('Sim, abrir <b>x</b>');
});

test('dialogoDuplicado: a mensagem e os botões não se mudam por engano', () => {
  const dialogo = dialogoDuplicado({ id: MERCEARIA, nome: 'X', distancia_m: 1 });
  expect(Object.isFrozen(dialogo)).toBe(true);
  expect(Object.isFrozen(dialogo.mensagem)).toBe(true);
  expect(dialogo.mensagem.every(Object.isFrozen)).toBe(true);
  expect(Object.isFrozen(dialogo.botoes)).toBe(true);
  expect(dialogo.botoes.every(Object.isFrozen)).toBe(true);
});

test('criarEscolhaUnica: dois toques seguidos, só conta a primeira escolha', () => {
  const escolhas = [];
  const escolha = criarEscolhaUnica((valor) => escolhas.push(valor));
  expect(escolha.escolhida).toBe(false);
  expect(escolha.escolher('abrir')).toBe(true);
  expect(escolha.escolher('outra')).toBe(false);
  expect(escolha.escolher(null)).toBe(false);
  expect(escolhas).toEqual(['abrir']);
  expect(escolha.escolhida).toBe(true);
});

test('criarEscolhaUnica: fechar sem escolha (Cancelar ou Escape) conta como a escolha null', () => {
  const escolhas = [];
  const escolha = criarEscolhaUnica((valor) => escolhas.push(valor));
  escolha.escolher(null);
  escolha.escolher('outra');
  expect(escolhas).toEqual([null]);
});

test('criarEscolhaUnica: sem função, escolher não rebenta', () => {
  const escolha = criarEscolhaUnica();
  expect(escolha.escolher('abrir')).toBe(true);
  expect(escolha.escolher('outra')).toBe(false);
});
