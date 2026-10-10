/**
 * O CLIENTE DA API DO CRM — corrido, não lido.
 *
 * A promessa que este ficheiro guarda: **todo o erro que sai do cliente do CRM
 * tem a mesma forma** — `ErroCrm` com `{codigo, mensagem, campos, extra,
 * estado}` —, venha ele de um erro do CRM (`detail` objeto), da sessão do
 * portal (`detail` texto), de um 422 do Pydantic (`detail` lista) ou de não
 * haver resposta nenhuma. Os ecrãs decidem pelo `codigo` e mostram a
 * `mensagem`, que é sempre texto pt-PT (nunca o inglês do FastAPI, nunca um
 * array que o toast tentasse desenhar).
 *
 * Os `jest.fn` nascem DENTRO de cada teste: o Jest do CRA corre com
 * `resetMocks: true`, que apaga antes de cada teste a implementação dos que
 * fossem criados ao nível do módulo.
 *
 * As formas comparam-se com `toEqual` sobre `forma(e)`, e não com
 * `toMatchObject`: neste, `campos: {}` aceita QUALQUER valor (até `null` ou
 * uma lista), porque um objeto vazio é subconjunto de tudo.
 */
import axios, { AxiosError, AxiosHeaders } from 'axios';
import {
  ErroCrm, erroCrm, criarClienteCrm, criarInstanciaCrm, instanciaCrm,
  obterEu, listarMembros, listarCandidatos, adicionarMembro, mudarPerfilMembro, retirarMembro,
  MENSAGEM_SEM_REDE, MENSAGEM_ERRO_INESPERADO, MENSAGEM_VALIDACAO, MENSAGEM_SEM_SESSAO,
  TIMEOUT_CRM_MS, URL_BASE_CRM,
} from './api';

// Um erro do axios COM resposta do servidor, tal como o axios o entrega.
const comResposta = (estado, data) => new AxiosError(
  `Request failed with status code ${estado}`,
  estado >= 500 ? 'ERR_BAD_RESPONSE' : 'ERR_BAD_REQUEST',
  {}, {}, { status: estado, statusText: '', data, headers: {}, config: {} },
);

// Um erro do axios SEM resposta: rede em baixo ou tecto de espera esgotado.
const semResposta = (codigo = 'ERR_NETWORK', mensagem = 'Network Error') =>
  new AxiosError(mensagem, codigo, {}, {});

// A forma pública de um ErroCrm, e a forma esperada com os vazios por omissão.
const forma = (e) => ({
  codigo: e.codigo, mensagem: e.mensagem, campos: e.campos, extra: e.extra, estado: e.estado,
});
const esperado = (codigo, mensagem, estado, { campos = {}, extra = {} } = {}) => ({
  codigo, mensagem, campos, extra, estado,
});

// O erro com que uma promessa rejeitou (e falha se ela não rejeitar).
const rejeicao = async (promessa) => {
  try {
    await promessa;
  } catch (e) {
    return e;
  }
  throw new Error('a promessa não rejeitou');
};

const AUTORIZACAO_ORIGINAL = axios.defaults.headers.common.Authorization;
const ADAPTADOR_ORIGINAL = instanciaCrm.defaults.adapter;

afterEach(() => {
  if (AUTORIZACAO_ORIGINAL === undefined) delete axios.defaults.headers.common.Authorization;
  else axios.defaults.headers.common.Authorization = AUTORIZACAO_ORIGINAL;
  instanciaCrm.defaults.adapter = ADAPTADOR_ORIGINAL;
});

describe('mensagens', () => {
  test('os textos são os do CRM autónomo e do backend, letra a letra', () => {
    expect(MENSAGEM_SEM_REDE).toBe('Sem rede — verifique a ligação e tente novamente.');
    expect(MENSAGEM_ERRO_INESPERADO).toBe('Erro inesperado — tente novamente.');
    expect(MENSAGEM_VALIDACAO).toBe('Verifique os campos assinalados.');
    // O mesmo texto do 401 do backend (`faturacao.auth`) para a conta apagada.
    expect(MENSAGEM_SEM_SESSAO).toBe('Sessão terminada');
  });
});

describe('ErroCrm', () => {
  test('é um Error, com a mensagem como message e valores por omissão vazios', () => {
    const e = new ErroCrm({ codigo: 'conflito', mensagem: 'Alterado por outra pessoa — recarregar' });
    expect(e).toBeInstanceOf(Error);
    expect(e.name).toBe('ErroCrm');
    expect(e.message).toBe('Alterado por outra pessoa — recarregar');
    expect(forma(e)).toEqual(esperado('conflito', 'Alterado por outra pessoa — recarregar', 0));
  });
});

describe('erroCrm — sem resposta do servidor', () => {
  test('sem rede → sem_rede, estado 0, com o erro original guardado', () => {
    const original = semResposta();
    const e = erroCrm(original);
    expect(e).toBeInstanceOf(ErroCrm);
    expect(forma(e)).toEqual(esperado('sem_rede', MENSAGEM_SEM_REDE, 0));
    expect(e.message).toBe(MENSAGEM_SEM_REDE);
    expect(e.cause).toBe(original);
  });

  test('o tecto de espera esgotado também é sem_rede', () => {
    expect(forma(erroCrm(semResposta('ECONNABORTED', 'timeout of 30000ms exceeded'))))
      .toEqual(esperado('sem_rede', MENSAGEM_SEM_REDE, 0));
    expect(forma(erroCrm(semResposta('ETIMEDOUT', 'timeout exceeded'))))
      .toEqual(esperado('sem_rede', MENSAGEM_SEM_REDE, 0));
  });

  test('um engano no código (erro que não veio do axios) não se disfarça de «sem rede»', () => {
    // «Sem rede — verifique a ligação» mandava a pessoa ver o Wi-Fi por causa
    // de um erro de programação.
    for (const e of [new TypeError('x is not a function'), new Error('x'), undefined, null, 'texto']) {
      expect(forma(erroCrm(e))).toEqual(esperado('erro_interno', MENSAGEM_ERRO_INESPERADO, 0));
    }
  });
});

describe('erroCrm — erros do CRM (detail objeto)', () => {
  test('409 duplicado: código, mensagem, campos vazios e as lojas em extra', () => {
    const lojas = [{ id: '7d1c…', nome: 'Café Central', distancia_m: 12 }];
    const e = erroCrm(comResposta(409, { detail: {
      codigo: 'duplicado', mensagem: 'Já existe Café Central aqui — é a mesma?', lojas,
    } }));
    expect(e).toBeInstanceOf(ErroCrm);
    expect(forma(e)).toEqual(esperado('duplicado', 'Já existe Café Central aqui — é a mesma?', 409, { extra: { lojas } }));
  });

  test('422 validacao: os campos chegam tal como o domínio os escreveu', () => {
    const campos = { user_id: 'Escolha uma conta do portal.', perfil: 'Escolha um perfil: admin, utilizador ou motorista.' };
    const e = erroCrm(comResposta(422, { detail: { codigo: 'validacao', mensagem: MENSAGEM_VALIDACAO, campos } }));
    expect(forma(e)).toEqual(esperado('validacao', MENSAGEM_VALIDACAO, 422, { campos }));
  });

  test('um 403 do CRM em objeto ganha à regra do texto', () => {
    expect(forma(erroCrm(comResposta(403, { detail: { codigo: 'sem_acesso_crm', mensagem: 'Sem acesso ao CRM.' } }))))
      .toEqual(esperado('sem_acesso_crm', 'Sem acesso ao CRM.', 403));
    expect(forma(erroCrm(comResposta(403, { detail: { codigo: 'sem_permissao', mensagem: 'Sem permissão para esta ação.' } }))))
      .toEqual(esperado('sem_permissao', 'Sem permissão para esta ação.', 403));
  });

  test('400 json_invalido, 404 nao_encontrado e 409 ja_membro passam como vêm', () => {
    expect(forma(erroCrm(comResposta(400, { detail: { codigo: 'json_invalido', mensagem: 'O pedido não é JSON válido.' } }))))
      .toEqual(esperado('json_invalido', 'O pedido não é JSON válido.', 400));
    expect(forma(erroCrm(comResposta(404, { detail: { codigo: 'nao_encontrado', mensagem: 'Membro não encontrado.' } }))))
      .toEqual(esperado('nao_encontrado', 'Membro não encontrado.', 404));
    expect(forma(erroCrm(comResposta(409, { detail: { codigo: 'ja_membro', mensagem: 'Esta pessoa já é membro do CRM.' } }))))
      .toEqual(esperado('ja_membro', 'Esta pessoa já é membro do CRM.', 409));
  });

  test('campos que não são um objeto simples passam a {}', () => {
    for (const campos of [[], ['x'], null, 'nome', 3]) {
      const e = erroCrm(comResposta(422, { detail: { codigo: 'validacao', mensagem: MENSAGEM_VALIDACAO, campos } }));
      expect(forma(e)).toEqual(esperado('validacao', MENSAGEM_VALIDACAO, 422));
    }
  });

  test('sem mensagem de texto, a mensagem é a genérica (nunca vazia, nunca um objeto)', () => {
    for (const mensagem of [undefined, '', '   ', null, 7, { a: 1 }]) {
      const e = erroCrm(comResposta(409, { detail: { codigo: 'conflito', mensagem } }));
      expect(forma(e)).toEqual(esperado('conflito', MENSAGEM_ERRO_INESPERADO, 409));
    }
  });

  test('um objeto sem código de texto é um erro inesperado (e no 401 continua a ser falta de sessão)', () => {
    for (const detail of [{}, { mensagem: 'x' }, { codigo: 3, mensagem: 'x' }, { codigo: '', mensagem: 'x' }]) {
      expect(forma(erroCrm(comResposta(409, { detail }))))
        .toEqual(esperado('erro_interno', MENSAGEM_ERRO_INESPERADO, 409));
      expect(forma(erroCrm(comResposta(401, { detail }))))
        .toEqual(esperado('nao_autenticado', MENSAGEM_ERRO_INESPERADO, 401));
    }
  });
});

describe('erroCrm — erros herdados da sessão do portal (detail texto)', () => {
  test('401 → nao_autenticado com o texto do servidor', () => {
    expect(forma(erroCrm(comResposta(401, { detail: 'Sessão terminada' }))))
      .toEqual(esperado('nao_autenticado', 'Sessão terminada', 401));
    expect(forma(erroCrm(comResposta(401, { detail: 'Sessão inválida ou expirada' }))))
      .toEqual(esperado('nao_autenticado', 'Sessão inválida ou expirada', 401));
  });

  test('403 «Not authenticated» (sem cabeçalho) é falta de sessão, não falta de permissão', () => {
    // Correções obrigatórias, linha «§10 armadilhas Jest / T1.10».
    expect(forma(erroCrm(comResposta(403, { detail: 'Not authenticated' }))))
      .toEqual(esperado('nao_autenticado', MENSAGEM_SEM_SESSAO, 403));
  });

  test('os outros textos do HTTPBearer também são falta de sessão, e nunca aparecem em inglês', () => {
    // «Invalid authentication credentials»: cabeçalho sem «Bearer». Um FastAPI
    // mais novo responde «Not authenticated» com 401 em vez de 403.
    expect(forma(erroCrm(comResposta(403, { detail: 'Invalid authentication credentials' }))))
      .toEqual(esperado('nao_autenticado', MENSAGEM_SEM_SESSAO, 403));
    expect(forma(erroCrm(comResposta(401, { detail: 'Not authenticated' }))))
      .toEqual(esperado('nao_autenticado', MENSAGEM_SEM_SESSAO, 401));
  });

  test('outro 403 em texto → sem_permissao com o texto do servidor', () => {
    expect(forma(erroCrm(comResposta(403, { detail: 'Sem permissão para esta área' }))))
      .toEqual(esperado('sem_permissao', 'Sem permissão para esta área', 403));
  });

  test('401 sem texto útil continua a ser nao_autenticado, com a mensagem genérica', () => {
    for (const data of [undefined, null, '', '<html>401</html>', { detail: '' }, { detail: '  ' }, { outra: 1 }]) {
      expect(forma(erroCrm(comResposta(401, data))))
        .toEqual(esperado('nao_autenticado', MENSAGEM_ERRO_INESPERADO, 401));
    }
  });

  test('403 sem texto útil é um erro inesperado', () => {
    expect(forma(erroCrm(comResposta(403, { detail: '' }))))
      .toEqual(esperado('erro_interno', MENSAGEM_ERRO_INESPERADO, 403));
  });
});

describe('erroCrm — 422 do Pydantic (detail lista)', () => {
  test('o campo vem do fim da loc e a mensagem da msg', () => {
    const e = erroCrm(comResposta(422, { detail: [
      { type: 'missing', loc: ['query', 'texto'], msg: 'Field required', input: null },
    ] }));
    expect(e).toBeInstanceOf(ErroCrm);
    expect(forma(e)).toEqual(esperado('validacao', MENSAGEM_VALIDACAO, 422, { campos: { texto: 'Field required' } }));
  });

  test('tira o «Value error, »; um campo por chave (fica o primeiro); ignora entradas estragadas', () => {
    const e = erroCrm(comResposta(422, { detail: [
      { loc: ['body', 'nome'], msg: 'Value error, Indique o nome.' },
      { loc: ['body', 'nome'], msg: 'segunda mensagem do mesmo campo' },
      { loc: ['body', 'janelas', 0, 'inicio'], msg: 'Hora inválida' },
      { loc: 'nome', msg: 'loc que não é lista' },
      { loc: [], msg: 'loc vazia' },
      { loc: ['body', 'lat'] },
      { loc: ['body', 'lng'], msg: '' },
      null,
      'texto solto',
    ] }));
    expect(forma(e)).toEqual(esperado('validacao', MENSAGEM_VALIDACAO, 422, {
      campos: { nome: 'Indique o nome.', inicio: 'Hora inválida' },
    }));
  });

  test('uma lista vazia continua a ser validacao, com campos vazios', () => {
    expect(forma(erroCrm(comResposta(422, { detail: [] }))))
      .toEqual(esperado('validacao', MENSAGEM_VALIDACAO, 422));
  });
});

describe('erroCrm — o resto', () => {
  test('500 sem JSON, 502 do proxy e o «Not Found» do FastAPI → erro_interno com a mensagem genérica', () => {
    expect(forma(erroCrm(comResposta(500, 'Internal Server Error'))))
      .toEqual(esperado('erro_interno', MENSAGEM_ERRO_INESPERADO, 500));
    expect(forma(erroCrm(comResposta(502, '<html><body>502 Bad Gateway</body></html>'))))
      .toEqual(esperado('erro_interno', MENSAGEM_ERRO_INESPERADO, 502));
    // Texto em inglês do FastAPI fora do 401/403: nunca vai para o ecrã.
    expect(forma(erroCrm(comResposta(404, { detail: 'Not Found' }))))
      .toEqual(esperado('erro_interno', MENSAGEM_ERRO_INESPERADO, 404));
    expect(forma(erroCrm(comResposta(405, { detail: 'Method Not Allowed' }))))
      .toEqual(esperado('erro_interno', MENSAGEM_ERRO_INESPERADO, 405));
  });

  test('uma lista fora do 422 e um texto no 422 também são erro_interno', () => {
    expect(forma(erroCrm(comResposta(400, { detail: [{ loc: ['body', 'x'], msg: 'm' }] }))))
      .toEqual(esperado('erro_interno', MENSAGEM_ERRO_INESPERADO, 400));
    expect(forma(erroCrm(comResposta(422, { detail: 'Unprocessable Entity' }))))
      .toEqual(esperado('erro_interno', MENSAGEM_ERRO_INESPERADO, 422));
  });

  test('um erro já normalizado volta igual (pode passar duas vezes pelo erroCrm)', () => {
    const uma = erroCrm(comResposta(409, { detail: { codigo: 'conflito', mensagem: 'Alterado por outra pessoa — recarregar' } }));
    expect(erroCrm(uma)).toBe(uma);
  });
});

describe('criarClienteCrm — chamadas da F1 com pedir falso', () => {
  test('obterEu faz GET /eu e devolve os dados', async () => {
    const eu = { membro: true, perfil: 'admin', admin_master: true };
    const pedir = jest.fn(async () => ({ data: eu, status: 200 }));
    const cliente = criarClienteCrm({ pedir });
    await expect(cliente.obterEu()).resolves.toBe(eu);
    expect(pedir).toHaveBeenCalledTimes(1);
    expect(pedir).toHaveBeenCalledWith({ method: 'GET', url: '/eu' });
  });

  test('listarMembros e listarCandidatos fazem GET e devolvem as listas', async () => {
    const membros = [{ id: null, admin_master: true }];
    const candidatos = [{ id: 'u-2', nome: 'Bea' }];
    const pedir = jest.fn(async ({ url }) => ({ data: url === '/membros' ? membros : candidatos }));
    const cliente = criarClienteCrm({ pedir });
    await expect(cliente.listarMembros()).resolves.toBe(membros);
    await expect(cliente.listarCandidatos()).resolves.toBe(candidatos);
    expect(pedir.mock.calls).toEqual([
      [{ method: 'GET', url: '/membros' }],
      [{ method: 'GET', url: '/membros/candidatos' }],
    ]);
  });

  test('adicionarMembro faz POST /membros só com user_id e perfil', async () => {
    const criado = { id: 'm-1', user_id: 'u-2', perfil: 'utilizador' };
    const pedir = jest.fn(async () => ({ data: criado, status: 201 }));
    const cliente = criarClienteCrm({ pedir });
    // O `nome` é estado do ecrã: não vai para o servidor.
    await expect(cliente.adicionarMembro({ user_id: 'u-2', perfil: 'utilizador', nome: 'Bea' }))
      .resolves.toBe(criado);
    expect(pedir).toHaveBeenCalledWith({ method: 'POST', url: '/membros', data: { user_id: 'u-2', perfil: 'utilizador' } });
  });

  test('mudarPerfilMembro faz PATCH /membros/{id} com o perfil; retirarMembro faz DELETE', async () => {
    const pedir = jest.fn(async ({ method }) => ({ data: method === 'DELETE' ? { retirado: true } : { id: 'm-1', perfil: 'admin' } }));
    const cliente = criarClienteCrm({ pedir });
    await expect(cliente.mudarPerfilMembro('m-1', 'admin')).resolves.toEqual({ id: 'm-1', perfil: 'admin' });
    await expect(cliente.retirarMembro('m-1')).resolves.toEqual({ retirado: true });
    expect(pedir.mock.calls).toEqual([
      [{ method: 'PATCH', url: '/membros/m-1', data: { perfil: 'admin' } }],
      [{ method: 'DELETE', url: '/membros/m-1' }],
    ]);
  });

  test('o id do membro vai codificado no caminho (nunca abre outra rota)', async () => {
    const pedir = jest.fn(async () => ({ data: {} }));
    const cliente = criarClienteCrm({ pedir });
    await cliente.mudarPerfilMembro('a/b?c#d', 'admin');
    await cliente.retirarMembro('../x');
    expect(pedir.mock.calls.map(([c]) => c.url)).toEqual(['/membros/a%2Fb%3Fc%23d', '/membros/..%2Fx']);
  });

  test('um erro do servidor é relançado já normalizado', async () => {
    const pedir = jest.fn(async () => {
      throw comResposta(409, { detail: { codigo: 'ja_membro', mensagem: 'Esta pessoa já é membro do CRM.' } });
    });
    const cliente = criarClienteCrm({ pedir });
    const e = await rejeicao(cliente.adicionarMembro({ user_id: 'u-2', perfil: 'admin' }));
    expect(e).toBeInstanceOf(ErroCrm);
    expect(forma(e)).toEqual(esperado('ja_membro', 'Esta pessoa já é membro do CRM.', 409));
  });

  test('sem rede, todas as chamadas rejeitam com sem_rede', async () => {
    const pedir = jest.fn(async () => { throw semResposta(); });
    const cliente = criarClienteCrm({ pedir });
    for (const chamada of [
      () => cliente.obterEu(), () => cliente.listarMembros(), () => cliente.listarCandidatos(),
      () => cliente.adicionarMembro({ user_id: 'u', perfil: 'admin' }),
      () => cliente.mudarPerfilMembro('m', 'admin'), () => cliente.retirarMembro('m'),
    ]) {
      const e = await rejeicao(chamada());
      expect(e).toBeInstanceOf(ErroCrm);
      expect(forma(e)).toEqual(esperado('sem_rede', MENSAGEM_SEM_REDE, 0));
    }
  });
});

describe('a instância axios do CRM', () => {
  // Um adaptador falso: responde sem rede e guarda o pedido que o axios montou.
  const adaptadorQueResponde = (data) => jest.fn(async (config) => ({
    data, status: 200, statusText: 'OK', headers: {}, config, request: {},
  }));
  const autorizacaoDe = (config) => AxiosHeaders.from(config.headers).get('Authorization');

  test('aponta para /api/crm do backend do portal, com tecto de 30 s', () => {
    expect(URL_BASE_CRM).toBe(`${process.env.REACT_APP_BACKEND_URL}/api/crm`);
    expect(TIMEOUT_CRM_MS).toBe(30000);
    const instancia = criarInstanciaCrm();
    expect(instancia.defaults.baseURL).toBe(URL_BASE_CRM);
    expect(instancia.defaults.timeout).toBe(TIMEOUT_CRM_MS);
    expect(instanciaCrm.defaults.baseURL).toBe(URL_BASE_CRM);
    expect(instanciaCrm.defaults.timeout).toBe(TIMEOUT_CRM_MS);
  });

  test('o token é lido a cada pedido, não copiado na criação', async () => {
    delete axios.defaults.headers.common.Authorization;
    const instancia = criarInstanciaCrm();
    const adaptador = adaptadorQueResponde({});
    axios.defaults.headers.common.Authorization = 'Bearer token-a';
    await instancia.request({ url: '/eu', adapter: adaptador });
    axios.defaults.headers.common.Authorization = 'Bearer token-b';
    await instancia.request({ url: '/eu', adapter: adaptador });
    expect(adaptador.mock.calls.map(([c]) => autorizacaoDe(c))).toEqual(['Bearer token-a', 'Bearer token-b']);
  });

  test('depois de terminar a sessão não segue token nenhum — nem o que havia quando a instância nasceu', async () => {
    // O `axios.create` copia os `defaults` do axios global no instante em que
    // corre: uma instância criada com sessão aberta ficava com esse token.
    axios.defaults.headers.common.Authorization = 'Bearer velho';
    const instancia = criarInstanciaCrm();
    delete axios.defaults.headers.common.Authorization;
    const adaptador = adaptadorQueResponde({});
    await instancia.request({ url: '/eu', adapter: adaptador });
    expect(autorizacaoDe(adaptador.mock.calls[0][0])).toBeUndefined();
  });

  test('as funções do módulo saem pela instância do CRM, com o token em vigor', async () => {
    axios.defaults.headers.common.Authorization = 'Bearer do-portal';
    const eu = { membro: false, perfil: null, admin_master: false };
    const adaptador = adaptadorQueResponde(eu);
    instanciaCrm.defaults.adapter = adaptador;
    await expect(obterEu()).resolves.toEqual(eu);
    const [config] = adaptador.mock.calls[0];
    expect(config.method).toBe('get');
    expect(axios.getUri(config)).toBe(`${URL_BASE_CRM}/eu`);
    expect(autorizacaoDe(config)).toBe('Bearer do-portal');
  });

  test('cada função do módulo chama o método e o caminho certos', async () => {
    const adaptador = adaptadorQueResponde({});
    instanciaCrm.defaults.adapter = adaptador;
    await listarMembros();
    await listarCandidatos();
    await adicionarMembro({ user_id: 'u-2', perfil: 'utilizador' });
    await mudarPerfilMembro('m-1', 'admin');
    await retirarMembro('m-1');
    expect(adaptador.mock.calls.map(([c]) => `${c.method.toUpperCase()} ${axios.getUri(c)}`)).toEqual([
      `GET ${URL_BASE_CRM}/membros`,
      `GET ${URL_BASE_CRM}/membros/candidatos`,
      `POST ${URL_BASE_CRM}/membros`,
      `PATCH ${URL_BASE_CRM}/membros/m-1`,
      `DELETE ${URL_BASE_CRM}/membros/m-1`,
    ]);
    expect(JSON.parse(adaptador.mock.calls[2][0].data)).toEqual({ user_id: 'u-2', perfil: 'utilizador' });
    expect(JSON.parse(adaptador.mock.calls[3][0].data)).toEqual({ perfil: 'admin' });
  });

  test('um erro do axios a sério chega normalizado às funções do módulo', async () => {
    const respostaDeErro = (config, estado, data) => new AxiosError(
      `Request failed with status code ${estado}`, 'ERR_BAD_REQUEST', config, {},
      { status: estado, statusText: '', headers: {}, config, data },
    );

    instanciaCrm.defaults.adapter = jest.fn(async (config) => {
      throw respostaDeErro(config, 403, { detail: { codigo: 'sem_acesso_crm', mensagem: 'Sem acesso ao CRM.' } });
    });
    const semAcesso = await rejeicao(listarMembros());
    expect(semAcesso.name).toBe('ErroCrm');
    expect(forma(semAcesso)).toEqual(esperado('sem_acesso_crm', 'Sem acesso ao CRM.', 403));

    instanciaCrm.defaults.adapter = jest.fn(async (config) => {
      throw respostaDeErro(config, 403, { detail: 'Not authenticated' });
    });
    expect(forma(await rejeicao(obterEu()))).toEqual(esperado('nao_autenticado', MENSAGEM_SEM_SESSAO, 403));

    instanciaCrm.defaults.adapter = jest.fn(async (config) => {
      throw new AxiosError('Network Error', 'ERR_NETWORK', config, {});
    });
    expect(forma(await rejeicao(obterEu()))).toEqual(esperado('sem_rede', MENSAGEM_SEM_REDE, 0));
  });
});
