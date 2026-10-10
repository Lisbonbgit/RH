/**
 * A PESQUISA DE MORADA — espera entre teclas, respostas fora de ordem e os
 * campos que a sugestão escolhida (ou a morada sugerida pelo GPS) preenche.
 *
 * Porta de tests/js/morada.test.js do CRM autónomo (etiqueta
 * `referencia-standalone`), com o `node:assert` passado a `expect` e o
 * `mock.timers` do `node:test` passado a `jest.useFakeTimers()` +
 * `jest.advanceTimersByTime()` (plano §10). A api é falsa e criada em cada
 * teste (o CRA corre com `resetMocks`): cada pedido fica pendente até o teste
 * o resolver ou rejeitar.
 *
 * As duas mensagens têm de ser as do 503 do servidor
 * (`backend/crm/morada.py`, `PESQUISA_INDISPONIVEL` e `INVERSA_INDISPONIVEL`),
 * vigiadas pelo `backend/tests/crm/test_consistencia_frontend.py`.
 *
 * Os três últimos testes são extra: um texto `null`/`undefined` não pesquisa
 * "null", o `pontoDeBias` guarda a 6.ª casa e aceita os limites do servidor,
 * e os erros do `api.js` do portal (`ErroCrm`) dão o estado certo.
 */
import {
  criarPesquisaMorada,
  camposDaMorada,
  camposSugeridos,
  pontoDeBias,
  CAMPOS_MORADA,
  MENSAGEM_MORADA_INDISPONIVEL,
  MENSAGEM_MORADA_SUGERIDA_INDISPONIVEL,
} from './morada';
import { ErroCrm, MENSAGEM_SEM_REDE } from './api';

const MENSAGEM = "Pesquisa de morada indisponível — coloque o pino no mapa ou use 'Estou nesta loja'";

// Api falsa: cada chamada fica pendente até o teste a resolver ou rejeitar.
function criarApiFalsa() {
  const chamadas = [];
  function api(texto, extra) {
    let resolver;
    let rejeitar;
    const promessa = new Promise((res, rej) => {
      resolver = res;
      rejeitar = rej;
    });
    chamadas.push({ texto, extra, resolver, rejeitar });
    return promessa;
  }
  return { api, chamadas };
}

// Deixa correr as promessas pendentes (microtarefas).
async function esvaziar() {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
}

let falsa;
let estados;
let pesquisa;

beforeEach(() => {
  jest.useFakeTimers();
  falsa = criarApiFalsa();
  estados = [];
  pesquisa = criarPesquisaMorada({ api: falsa.api, aoMudarEstado: (e) => estados.push(e) });
});

afterEach(() => {
  jest.useRealTimers();
});

const ultimo = () => estados[estados.length - 1];

test('a mensagem de falha é a do plano', () => {
  expect(MENSAGEM_MORADA_INDISPONIVEL).toBe(MENSAGEM);
});

test('espera 300 ms depois da última tecla antes de pesquisar', () => {
  pesquisa.escrever('Rua');
  jest.advanceTimersByTime(299);
  expect(falsa.chamadas.length).toBe(0);
  pesquisa.escrever('Rua A');
  jest.advanceTimersByTime(299);
  expect(falsa.chamadas.length).toBe(0);
  jest.advanceTimersByTime(1);
  expect(falsa.chamadas.length).toBe(1);
  expect(falsa.chamadas[0].texto).toBe('Rua A');
});

test('passa o extra (bias) à api', () => {
  pesquisa.escrever('Rua Augusta', { lat: 38.7, lng: -9.1 });
  jest.advanceTimersByTime(300);
  expect(falsa.chamadas[0].extra).toEqual({ lat: 38.7, lng: -9.1 });
});

test('não pesquisa com menos de 3 caracteres (sem contar espaços nas pontas)', () => {
  pesquisa.escrever('Ru');
  jest.advanceTimersByTime(1000);
  pesquisa.escrever('  Ru  ');
  jest.advanceTimersByTime(1000);
  expect(falsa.chamadas.length).toBe(0);
  expect(ultimo()).toEqual({ estado: 'vazio', sugestoes: [] });
});

test('envia o texto sem espaços nas pontas', () => {
  pesquisa.escrever('  Rua  ');
  jest.advanceTimersByTime(300);
  expect(falsa.chamadas[0].texto).toBe('Rua');
});

test('apagar para menos de 3 caracteres cancela a pesquisa agendada', () => {
  pesquisa.escrever('Rua');
  jest.advanceTimersByTime(100);
  pesquisa.escrever('Ru');
  jest.advanceTimersByTime(1000);
  expect(falsa.chamadas.length).toBe(0);
});

test('mostra a_pesquisar e depois os resultados', async () => {
  pesquisa.escrever('Rua Augusta');
  jest.advanceTimersByTime(300);
  expect(ultimo()).toEqual({ estado: 'a_pesquisar', texto: 'Rua Augusta' });
  const sugestoes = [{ rotulo: 'Rua Augusta, Lisboa', lat: 38.71, lng: -9.137 }];
  falsa.chamadas[0].resolver(sugestoes);
  await esvaziar();
  expect(ultimo()).toEqual({ estado: 'resultados', texto: 'Rua Augusta', sugestoes });
});

test('uma resposta antiga não substitui uma mais recente', async () => {
  pesquisa.escrever('Rua Aug');
  jest.advanceTimersByTime(300);
  pesquisa.escrever('Rua Augusta');
  jest.advanceTimersByTime(300);
  expect(falsa.chamadas.length).toBe(2);

  const novas = [{ rotulo: 'Rua Augusta, Lisboa' }];
  falsa.chamadas[1].resolver(novas);
  await esvaziar();
  falsa.chamadas[0].resolver([{ rotulo: 'Rua Augusto Gil' }]);
  await esvaziar();

  expect(ultimo()).toEqual({ estado: 'resultados', texto: 'Rua Augusta', sugestoes: novas });
  expect(estados.filter((e) => e.estado === 'resultados').length).toBe(1);
});

test('um erro antigo também não substitui resultados mais recentes', async () => {
  pesquisa.escrever('Rua Aug');
  jest.advanceTimersByTime(300);
  pesquisa.escrever('Rua Augusta');
  jest.advanceTimersByTime(300);
  falsa.chamadas[1].resolver([]);
  await esvaziar();
  falsa.chamadas[0].rejeitar({ codigo: 'morada_indisponivel', mensagem: 'x' });
  await esvaziar();
  expect(ultimo().estado).toBe('resultados');
});

test('resposta que chega depois de apagar o texto é ignorada', async () => {
  pesquisa.escrever('Rua');
  jest.advanceTimersByTime(300);
  pesquisa.escrever('');
  falsa.chamadas[0].resolver([{ rotulo: 'Rua X' }]);
  await esvaziar();
  expect(ultimo()).toEqual({ estado: 'vazio', sugestoes: [] });
});

test('cancelar descarta a pesquisa agendada e a que está a decorrer', async () => {
  pesquisa.escrever('Rua');
  jest.advanceTimersByTime(300);
  pesquisa.escrever('Rua A');
  pesquisa.cancelar();
  jest.advanceTimersByTime(1000);
  expect(falsa.chamadas.length).toBe(1);
  falsa.chamadas[0].resolver([{ rotulo: 'Rua X' }]);
  await esvaziar();
  expect(ultimo().estado).not.toBe('resultados');
});

test('erro morada_indisponivel resulta no estado de erro com a mensagem exata', async () => {
  pesquisa.escrever('falha');
  jest.advanceTimersByTime(300);
  falsa.chamadas[0].rejeitar({ codigo: 'morada_indisponivel', mensagem: 'do servidor' });
  await esvaziar();
  expect(ultimo()).toEqual({ estado: 'erro', codigo: 'morada_indisponivel', mensagem: MENSAGEM });
});

test('erro sem_rede resulta no estado de erro com a mensagem exata', async () => {
  pesquisa.escrever('Rua Augusta');
  jest.advanceTimersByTime(300);
  falsa.chamadas[0].rejeitar({ codigo: 'sem_rede', mensagem: 'Sem rede' });
  await esvaziar();
  expect(ultimo()).toEqual({ estado: 'erro', codigo: 'sem_rede', mensagem: MENSAGEM });
});

test('outro erro qualquer também mostra a falha da pesquisa', async () => {
  pesquisa.escrever('Rua Augusta');
  jest.advanceTimersByTime(300);
  falsa.chamadas[0].rejeitar(new TypeError('rebentou'));
  await esvaziar();
  expect(ultimo()).toEqual({ estado: 'erro', codigo: 'morada_indisponivel', mensagem: MENSAGEM });
});

test('api que lança logo também resulta no estado de erro', async () => {
  const p = criarPesquisaMorada({
    api: () => {
      throw new Error('síncrono');
    },
    aoMudarEstado: (e) => estados.push(e),
  });
  p.escrever('Rua Augusta');
  jest.advanceTimersByTime(300);
  await esvaziar();
  expect(ultimo()).toEqual({ estado: 'erro', codigo: 'morada_indisponivel', mensagem: MENSAGEM });
});

test('atrasoMs e minimo são configuráveis', () => {
  const p = criarPesquisaMorada({ api: falsa.api, aoMudarEstado: () => {}, atrasoMs: 50, minimo: 5 });
  p.escrever('Rua');
  jest.advanceTimersByTime(1000);
  expect(falsa.chamadas.length).toBe(0);
  p.escrever('Rua A');
  jest.advanceTimersByTime(50);
  expect(falsa.chamadas.length).toBe(1);
});

test('cancelar sozinho descarta a resposta e o erro de um pedido a decorrer', async () => {
  pesquisa.escrever('Rua Augusta');
  jest.advanceTimersByTime(300);
  pesquisa.escrever('Rua Augusto Gil');
  jest.advanceTimersByTime(300);
  expect(falsa.chamadas.length).toBe(2);
  pesquisa.cancelar();
  const antes = estados.length;
  falsa.chamadas[1].resolver([{ rotulo: 'Rua Augusto Gil' }]);
  falsa.chamadas[0].rejeitar({ codigo: 'sem_rede' });
  await esvaziar();
  expect(estados.length).toBe(antes);
});

test('resposta que não é lista dá resultados vazios', async () => {
  pesquisa.escrever('Rua Augusta');
  jest.advanceTimersByTime(300);
  falsa.chamadas[0].resolver(null);
  await esvaziar();
  expect(ultimo()).toEqual({ estado: 'resultados', texto: 'Rua Augusta', sugestoes: [] });
});

// --- Campos da loja preenchidos pela sugestão escolhida (E6) ------------------------------------

const AUGUSTA = {
  rotulo: 'Rua Augusta 24, 1100-048 Lisboa, Portugal',
  morada: 'Rua Augusta 24',
  codigo_postal: '1100-048',
  localidade: 'Lisboa',
  lat: 38.70921,
  lng: -9.13712,
};
const VAZIOS = { morada: '', codigo_postal: '', localidade: '' };

test('CAMPOS_MORADA: morada, código postal e localidade', () => {
  expect([...CAMPOS_MORADA]).toEqual(['morada', 'codigo_postal', 'localidade']);
});

test('camposDaMorada: a sugestão preenche a morada, o código postal e a localidade', () => {
  expect(camposDaMorada(AUGUSTA, VAZIOS, {})).toEqual({
    morada: 'Rua Augusta 24',
    codigo_postal: '1100-048',
    localidade: 'Lisboa',
  });
});

test('camposDaMorada: a sugestão substitui o que lá estava', () => {
  const atuais = { morada: 'Rua do Ouro', codigo_postal: '1100-060', localidade: 'Lisbo' };
  expect(camposDaMorada(AUGUSTA, atuais, {})).toEqual({
    morada: 'Rua Augusta 24',
    codigo_postal: '1100-048',
    localidade: 'Lisboa',
  });
});

test('camposDaMorada: o que a sugestão não tem fica como a pessoa o escreveu', () => {
  const semCodigo = { ...AUGUSTA, codigo_postal: null, morada: null };
  const atuais = { morada: 'Rua Augusta, loja 3', codigo_postal: '1100-048', localidade: '' };
  expect(camposDaMorada(semCodigo, atuais, {})).toEqual({ localidade: 'Lisboa' });
});

test('camposDaMorada: o que a sugestão anterior lá pôs, e a pessoa não mudou, esvazia-se', () => {
  const cascais = {
    rotulo: 'Rua Augusta, 2750 Cascais, Portugal',
    morada: 'Rua Augusta',
    codigo_postal: null,
    localidade: 'Cascais',
    lat: 38.6979,
    lng: -9.4215,
  };
  const anteriores = { morada: 'Rua Augusta 24', codigo_postal: '1100-048', localidade: 'Lisboa' };
  expect(camposDaMorada(cascais, anteriores, anteriores)).toEqual({
    morada: 'Rua Augusta',
    codigo_postal: '',
    localidade: 'Cascais',
  });
  const mudado = { ...anteriores, codigo_postal: '2750-001' };
  expect(camposDaMorada(cascais, mudado, anteriores)).toEqual({ morada: 'Rua Augusta', localidade: 'Cascais' });
});

test('camposDaMorada: valores que não são texto, ou só espaços, contam como em falta', () => {
  const estranha = { rotulo: 'x', morada: 7, codigo_postal: '   ', localidade: undefined, lat: 38.7, lng: -9.1 };
  expect(camposDaMorada(estranha, VAZIOS, {})).toEqual({});
  expect(camposDaMorada({ ...AUGUSTA, localidade: '  Lisboa ' }, VAZIOS).localidade).toBe('Lisboa');
  expect(camposDaMorada(null, VAZIOS, {})).toEqual({});
});

test('pontoDeBias: o ponto com até 6 casas decimais; sem ponto válido, null', () => {
  expect(pontoDeBias({ lat: 38.72230000123, lng: -9.13930000456 })).toEqual({ lat: 38.7223, lng: -9.1393 });
  expect(pontoDeBias({ lat: 38.7, lng: -9.1, alt: 3 })).toEqual({ lat: 38.7, lng: -9.1 });
  const invalidos = [
    null,
    undefined,
    {},
    { lat: '38.7', lng: -9.1 },
    { lat: Number.NaN, lng: -9.1 },
    { lat: 38.7, lng: Infinity },
    { lat: 91, lng: 0 },
    { lat: 0, lng: -181 },
  ];
  for (const invalido of invalidos) {
    expect(pontoDeBias(invalido)).toBeNull();
  }
});

test('pontoDeBias: nunca escreve o número com expoente (o servidor ignoraria o bias)', () => {
  const ponto = pontoDeBias({ lat: 0.0000001, lng: -0.0000001 });
  expect(String(ponto.lat)).toBe('0');
  expect(String(ponto.lng)).toBe('0');
});

// --- Morada sugerida pela geocodificação inversa do GPS (E7) --------------------------------------

const PRACA = {
  rotulo: 'Praça do Comércio, 1100-148 Lisboa, Portugal',
  morada: 'Praça do Comércio',
  codigo_postal: '1100-148',
  localidade: 'Lisboa',
  lat: 38.70749,
  lng: -9.13648,
};

test('MENSAGEM_MORADA_SUGERIDA_INDISPONIVEL é a do servidor (crm/morada.py, INVERSA_INDISPONIVEL)', () => {
  expect(MENSAGEM_MORADA_SUGERIDA_INDISPONIVEL).toBe('Morada sugerida indisponível — escreva a morada à mão.');
});

test('camposSugeridos: preenche só os campos vazios', () => {
  expect(camposSugeridos(PRACA, VAZIOS, {})).toEqual({
    morada: 'Praça do Comércio',
    codigo_postal: '1100-148',
    localidade: 'Lisboa',
  });
  // O que a pessoa escreveu fica.
  const atuais = { morada: 'Rua do Ouro 3', codigo_postal: '  ', localidade: 'Lisbo' };
  expect(camposSugeridos(PRACA, atuais, {})).toEqual({ codigo_postal: '1100-148' });
});

test('camposSugeridos: o que a app lá pôs antes (e a pessoa não mudou) pode ser substituído', () => {
  const anteriores = { morada: 'Rua Augusta 24', codigo_postal: '1100-048', localidade: 'Lisboa' };
  expect(camposSugeridos(PRACA, anteriores, anteriores)).toEqual({
    morada: 'Praça do Comércio',
    codigo_postal: '1100-148',
    localidade: 'Lisboa',
  });
  const mudado = { ...anteriores, morada: 'Rua Augusta 24, loja 2' };
  expect(camposSugeridos(PRACA, mudado, anteriores)).toEqual({ codigo_postal: '1100-148', localidade: 'Lisboa' });
});

test('camposSugeridos: sem o valor na sugestão, só se esvazia o que a app lá pôs', () => {
  const semCodigo = { ...PRACA, codigo_postal: null };
  const anteriores = { morada: 'Rua Augusta 24', codigo_postal: '1100-048', localidade: 'Lisboa' };
  expect(camposSugeridos(semCodigo, anteriores, anteriores)).toEqual({
    morada: 'Praça do Comércio',
    codigo_postal: '',
    localidade: 'Lisboa',
  });
  const escrito = { morada: '', codigo_postal: '1100-001', localidade: '' };
  expect(camposSugeridos(semCodigo, escrito, {})).toEqual({ morada: 'Praça do Comércio', localidade: 'Lisboa' });
});

test('camposSugeridos: valores que não são texto, ou só espaços, contam como em falta', () => {
  const estranha = { rotulo: 'x', morada: 7, codigo_postal: '   ', localidade: undefined, lat: 38.7, lng: -9.1 };
  expect(camposSugeridos(estranha, VAZIOS, {})).toEqual({});
  expect(camposSugeridos({ ...PRACA, localidade: '  Lisboa ' }, VAZIOS).localidade).toBe('Lisboa');
  expect(camposSugeridos(null, VAZIOS, {})).toEqual({});
  // Campos em falta contam como vazios.
  expect(camposSugeridos(PRACA, {}, undefined)).toEqual({
    morada: 'Praça do Comércio',
    codigo_postal: '1100-148',
    localidade: 'Lisboa',
  });
});

// --- Extra (portal) ------------------------------------------------------------------------------

test('um texto null ou undefined fica vazio (não pesquisa "null")', () => {
  for (const texto of [null, undefined]) {
    pesquisa.escrever(texto);
    jest.advanceTimersByTime(1000);
    expect(ultimo()).toEqual({ estado: 'vazio', sugestoes: [] });
  }
  expect(falsa.chamadas.length).toBe(0);
});

test('pontoDeBias: guarda a 6.ª casa e aceita os limites do servidor (|lat| ≤ 90, |lng| ≤ 180)', () => {
  expect(pontoDeBias({ lat: 38.7223451, lng: -9.1393449 })).toEqual({ lat: 38.722345, lng: -9.139345 });
  // crm/morada.py: o bias serve com qualquer ponto do mundo dentro destes limites (T2.15).
  expect(pontoDeBias({ lat: 90, lng: 180 })).toEqual({ lat: 90, lng: 180 });
  expect(pontoDeBias({ lat: -90, lng: -180 })).toEqual({ lat: -90, lng: -180 });
});

test('os erros do api.js do portal (ErroCrm) dão o estado certo', async () => {
  const casos = [
    [new ErroCrm({ codigo: 'sem_rede', mensagem: MENSAGEM_SEM_REDE, estado: 0 }), 'sem_rede'],
    [new ErroCrm({ codigo: 'morada_indisponivel', mensagem: MENSAGEM, estado: 503 }), 'morada_indisponivel'],
    [new ErroCrm({ codigo: 'validacao', mensagem: 'Verifique os campos assinalados.', estado: 422 }), 'morada_indisponivel'],
  ];
  for (const [erro, codigo] of casos) {
    pesquisa.escrever('Rua Augusta');
    jest.advanceTimersByTime(300);
    falsa.chamadas[falsa.chamadas.length - 1].rejeitar(erro);
    await esvaziar();
    expect(ultimo()).toEqual({ estado: 'erro', codigo, mensagem: MENSAGEM });
  }
});
