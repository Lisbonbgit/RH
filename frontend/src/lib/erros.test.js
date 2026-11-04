/**
 * @jest-environment node
 */
// O ERRO DE UM PEDIDO CHEGA AO ECRÃ COMO TEXTO — corrido, não lido.
//
// O caso que o pediu: um colaborador escreveu «carlos@gmailcom» no login. O
// <input type="email"> aceita-o, o EmailStr do servidor não: 422 com o `detail`
// em LISTA, o sonner desenhou a lista como filho React e o portal ficou branco.
//
// Três peças: a frase (`mensagemDoErro`), o interceptor do axios por omissão
// (`detalheEmTexto`, registado no AuthContext — que aqui se importa a sério) e a
// prova de que as instâncias do `axios.create` não o herdam (tratam o 422 à sua
// maneira: lib/faturacao.js, lib/pos.js, lib/crm/api.js).
import axios, { AxiosError } from 'axios';
import { detalheEmTexto, fraseDaValidacao, mensagemDoErro, MENSAGEM_EMAIL_INVALIDO } from './erros';
import { mensagemDoErro as mensagemDoColaborador } from './colaboradores';
import '../contexts/AuthContext';

const erro = (status, detail) => ({ response: { status, data: { detail } } });

// Tal como o FastAPI os manda.
const LISTA_EMAIL = [{
  type: 'value_error', loc: ['body', 'email'], input: 'carlos@gmailcom',
  msg: 'value is not a valid email address: The part after the @-sign is not valid. It should have a period.',
  ctx: { reason: 'The part after the @-sign is not valid. It should have a period.' },
}];
const LISTA_SENHA = [{
  type: 'value_error', loc: ['body', 'new_password'], input: 'curta',
  msg: 'Value error, A palavra-passe deve ter pelo menos 8 caracteres',
}];

describe('mensagemDoErro — sempre texto', () => {
  test('um 422 no email dá a frase em português', () => {
    expect(mensagemDoErro(erro(422, LISTA_EMAIL), 'Erro ao iniciar sessão')).toBe(MENSAGEM_EMAIL_INVALIDO);
    expect(MENSAGEM_EMAIL_INVALIDO).toBe('Email inválido. Verifique como está escrito.');
  });
  test('um 422 noutro campo dá a mensagem do validador, sem o «Value error,»', () => {
    expect(mensagemDoErro(erro(422, LISTA_SENHA), 'x')).toBe('A palavra-passe deve ter pelo menos 8 caracteres');
  });
  test('o texto do servidor vai tal e qual', () => {
    expect(mensagemDoErro(erro(401, 'Email ou palavra-passe incorretos'), 'x')).toBe('Email ou palavra-passe incorretos');
  });
  test('sem resposta, a mensagem por omissão', () => {
    expect(mensagemDoErro(new Error('Network Error'), 'Erro ao iniciar sessão')).toBe('Erro ao iniciar sessão');
    expect(mensagemDoErro(undefined, 'Erro ao iniciar sessão')).toBe('Erro ao iniciar sessão');
    expect(typeof mensagemDoErro(new Error('x'))).toBe('string');
  });
  test('um detalhe estranho nunca sai cru: a mensagem por omissão', () => {
    for (const detalhe of [{ estranho: true }, [], [null], ['texto'], [{ loc: 'body', msg: { a: 1 } }], 42, '']) {
      expect(mensagemDoErro(erro(422, detalhe), 'Por omissão')).toBe('Por omissão');
    }
  });
  test('fraseDaValidacao: null quando não se sabe ler', () => {
    expect(fraseDaValidacao(undefined)).toBeNull();
    expect(fraseDaValidacao('texto')).toBeNull();
    expect(fraseDaValidacao([{ loc: ['body', 'code'], msg: '' }])).toBeNull();
  });
});

describe('detalheEmTexto — o interceptor do axios por omissão', () => {
  test('a lista passa a texto e fica guardada em `detalhes`; a promessa continua rejeitada', async () => {
    const e = erro(422, LISTA_EMAIL);
    await expect(detalheEmTexto(e)).rejects.toBe(e);
    expect(e.response.data.detail).toBe(MENSAGEM_EMAIL_INVALIDO);
    expect(e.response.data.detalhes).toBe(LISTA_EMAIL);
  });
  test('uma lista sem frase legível fica sem `detail` (cada ecrã usa a sua)', async () => {
    const e = erro(422, []);
    await expect(detalheEmTexto(e)).rejects.toBe(e);
    expect(e.response.data.detail).toBeUndefined();
    expect(e.response.data.detalhes).toEqual([]);
  });
  test('o detail em texto, ou em objeto, fica intacto', async () => {
    const texto = erro(400, 'Código inválido');
    await expect(detalheEmTexto(texto)).rejects.toBe(texto);
    expect(texto.response.data).toEqual({ detail: 'Código inválido' });
    // O 404 do extrato (FinExtrato) traz um objeto com que o ecrã trabalha.
    const objeto = erro(404, { code: 'conta_desconhecida', holder: 'X' });
    await expect(detalheEmTexto(objeto)).rejects.toBe(objeto);
    expect(objeto.response.data).toEqual({ detail: { code: 'conta_desconhecida', holder: 'X' } });
  });
  test('sem resposta (rede em baixo, tecto de espera) fica intacto', async () => {
    const semRede = new AxiosError('Network Error', 'ERR_NETWORK', {}, {});
    await expect(detalheEmTexto(semRede)).rejects.toBe(semRede);
    expect(semRede.response).toBeUndefined();
    const blob = { response: { status: 500, data: 'texto' } };
    await expect(detalheEmTexto(blob)).rejects.toBe(blob);
    expect(blob.response.data).toBe('texto');
  });
  test('o «Editar Colaborador» continua a dizer «Email inválido» com o interceptor ativo', async () => {
    const e = erro(422, LISTA_EMAIL);
    await detalheEmTexto(e).catch(() => {});
    expect(mensagemDoColaborador(e)).toBe(MENSAGEM_EMAIL_INVALIDO);
    const senha = erro(422, LISTA_SENHA);
    await detalheEmTexto(senha).catch(() => {});
    expect(mensagemDoColaborador(senha)).toBe('A palavra-passe deve ter pelo menos 8 caracteres');
  });
});

describe('registado no axios por omissão, e só nele', () => {
  // Um adaptador que responde 422 como o servidor: o axios rejeita com a resposta.
  const responde422 = (detail) => (config) => Promise.reject(new AxiosError(
    'Request failed with status code 422', 'ERR_BAD_REQUEST', config, {},
    { status: 422, statusText: 'Unprocessable Entity', data: { detail }, headers: {}, config },
  ));

  test('um 422 do axios por omissão chega ao ecrã já em texto', async () => {
    const recusado = await axios.post('/api/auth/login', { email: 'carlos@gmailcom', password: 'x' },
      { adapter: responde422(LISTA_EMAIL) }).catch((e) => e);
    expect(recusado).toBeInstanceOf(AxiosError);
    expect(recusado.response.data.detail).toBe(MENSAGEM_EMAIL_INVALIDO);
    expect(recusado.response.data.detalhes).toEqual(LISTA_EMAIL);
  });
  test('uma instância do axios.create não o herda: o detail fica em lista', async () => {
    const recusado = await axios.create().post('/api/x', {}, { adapter: responde422(LISTA_EMAIL) }).catch((e) => e);
    expect(recusado.response.data.detail).toEqual(LISTA_EMAIL);
    expect(recusado.response.data).not.toHaveProperty('detalhes');
  });
  test('uma resposta boa passa sem mexer', async () => {
    const adapter = (config) => Promise.resolve({ status: 200, statusText: 'OK', data: { detail: ['a'] }, headers: {}, config });
    const { data } = await axios.get('/api/x', { adapter });
    expect(data).toEqual({ detail: ['a'] });
  });
});
