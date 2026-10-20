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
 *
 * As chamadas da F2 (T2.24): regiões, lojas, definições, configuração do mapa
 * e morada (só a inversa, para o GPS: a pesquisa de moradas da Geoapify saiu
 * na G11 do plano do mapa Google, que a substitui pelo elemento de pesquisa da
 * própria Google). Os `params` da morada comparam-se com `toStrictEqual`: o
 * `toEqual` ignora as chaves com `undefined` e deixava passar um
 * `lat: undefined`.
 */
import axios, { AxiosError, AxiosHeaders } from 'axios';
import {
  ErroCrm, erroCrm, criarClienteCrm, criarInstanciaCrm, instanciaCrm,
  obterEu, listarMembros, listarCandidatos, adicionarMembro, mudarPerfilMembro, retirarMembro,
  listarRegioes, criarRegiao, alterarRegiao, apagarRegiao,
  listarLojas, obterLoja, criarLoja, alterarLoja, apagarLoja,
  obterDefinicoes, alterarDefinicoes, obterConfigMapa, moradaInversa,
  MENSAGEM_SEM_REDE, MENSAGEM_ERRO_INESPERADO, MENSAGEM_VALIDACAO, MENSAGEM_SEM_SESSAO,
  TIMEOUT_CRM_MS, URL_BASE_CRM,
} from './api';
import * as moduloApi from './api';
import { pontoDeBias } from './morada';

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

describe('criarClienteCrm — chamadas da F2 com pedir falso', () => {
  // Ids como os do servidor (uuid4 em texto).
  const REGIAO_ID = '5e2a9d14-7c3b-4e8f-a1d6-3f9b2c8e7a05';
  const LOJA_ID = '0b6f3c2e-8d4a-4f1b-9c7e-2a5d8e1f3b4c';
  const VERSAO = '2026-10-10T09:00:00.123456Z';

  // Um pedir falso que responde, por ordem, com cada um dos `dados`.
  const pedirQueResponde = (...dados) => {
    const fila = [...dados];
    return jest.fn(async () => ({ data: fila.shift(), status: 200 }));
  };
  const pedirQueFalha = (erro) => jest.fn(async () => { throw erro; });
  // O que se tira de cada pedido, numa lista do próprio teste: o `mock.calls`
  // nasce noutro «realm» e um `.map` sobre ele dá um Array que o
  // `toStrictEqual` recusa ("serializes to the same string").
  const pedidos = (pedir, tirar) => Array.from(pedir.mock.calls, ([config]) => tirar(config));

  test('regiões: listar (GET), criar (POST), alterar (PATCH) e apagar (DELETE), e devolvem os dados', async () => {
    const lista = [{ id: REGIAO_ID, nome: 'Lisboa', ordem: 0 }];
    const criada = { id: REGIAO_ID, nome: 'Setúbal', ordem: 1 };
    const alterada = { id: REGIAO_ID, nome: 'Setúbal', ordem: 2 };
    const apagada = { apagada: true };
    const pedir = pedirQueResponde(lista, criada, alterada, apagada);
    const cliente = criarClienteCrm({ pedir });
    const corpoNova = { nome: 'Setúbal', ordem: 1 };
    const corpoAlterar = { ordem: 2 };

    await expect(cliente.listarRegioes()).resolves.toBe(lista);
    await expect(cliente.criarRegiao(corpoNova)).resolves.toBe(criada);
    await expect(cliente.alterarRegiao(REGIAO_ID, corpoAlterar)).resolves.toBe(alterada);
    await expect(cliente.apagarRegiao(REGIAO_ID)).resolves.toBe(apagada);

    expect(pedir.mock.calls).toEqual([
      [{ method: 'GET', url: '/regioes' }],
      [{ method: 'POST', url: '/regioes', data: { nome: 'Setúbal', ordem: 1 } }],
      [{ method: 'PATCH', url: `/regioes/${REGIAO_ID}`, data: { ordem: 2 } }],
      [{ method: 'DELETE', url: `/regioes/${REGIAO_ID}` }],
    ]);
    // O corpo vai tal como o ecrã o montou (o servidor ignora as outras chaves).
    expect(pedir.mock.calls[1][0].data).toBe(corpoNova);
    expect(pedir.mock.calls[2][0].data).toBe(corpoAlterar);
  });

  test('lojas: listar, obter, criar, alterar e apagar, e devolvem os dados', async () => {
    const lista = [{ id: LOJA_ID, nome: 'Café Central', fase: 'potencial', regiao_id: null, lat: 38.7, lng: -9.1, telefone: '' }];
    const loja = { id: LOJA_ID, nome: 'Café Central', atualizado_em: VERSAO };
    const criada = { ...loja };
    const alterada = { ...loja, telefone: '912345678' };
    const apagada = { apagada: true };
    const pedir = pedirQueResponde(lista, loja, criada, alterada, apagada);
    const cliente = criarClienteCrm({ pedir });
    // Os corpos montam-se nas regras puras (corpoLojaNova, camposAlterados):
    // aqui vão tal e qual, incluindo o `confirmar_duplicado` e a versão.
    const corpoNova = { nome: 'Café Central', fase: 'potencial', lat: 38.7, lng: -9.1, confirmar_duplicado: true };
    const corpoAlterar = { telefone: '912345678', atualizado_em: VERSAO };

    await expect(cliente.listarLojas()).resolves.toBe(lista);
    await expect(cliente.obterLoja(LOJA_ID)).resolves.toBe(loja);
    await expect(cliente.criarLoja(corpoNova)).resolves.toBe(criada);
    await expect(cliente.alterarLoja(LOJA_ID, corpoAlterar)).resolves.toBe(alterada);
    await expect(cliente.apagarLoja(LOJA_ID)).resolves.toBe(apagada);

    expect(pedir.mock.calls).toEqual([
      [{ method: 'GET', url: '/lojas' }],
      [{ method: 'GET', url: `/lojas/${LOJA_ID}` }],
      [{ method: 'POST', url: '/lojas', data: corpoNova }],
      [{ method: 'PATCH', url: `/lojas/${LOJA_ID}`, data: corpoAlterar }],
      [{ method: 'DELETE', url: `/lojas/${LOJA_ID}` }],
    ]);
    expect(pedir.mock.calls[2][0].data).toBe(corpoNova);
    expect(pedir.mock.calls[3][0].data).toBe(corpoAlterar);
  });

  test('definições da fábrica (GET e PATCH) e configuração do mapa (GET /config)', async () => {
    const definicoes = { fabrica_morada: 'Rua A', fabrica_lat: 38.7, fabrica_lng: -9.1 };
    const alteradas = { ...definicoes, fabrica_morada: 'Rua B' };
    const config = { google: { chave: 'chave-teste-navegador', map_id: 'map-id-teste' }, centro: { lat: 38.7, lng: -9.1 } };
    const pedir = pedirQueResponde(definicoes, alteradas, config);
    const cliente = criarClienteCrm({ pedir });
    const corpo = { fabrica_morada: 'Rua B' };

    await expect(cliente.obterDefinicoes()).resolves.toBe(definicoes);
    await expect(cliente.alterarDefinicoes(corpo)).resolves.toBe(alteradas);
    await expect(cliente.obterConfigMapa()).resolves.toBe(config);

    expect(pedir.mock.calls).toEqual([
      [{ method: 'GET', url: '/definicoes' }],
      [{ method: 'PATCH', url: '/definicoes', data: { fabrica_morada: 'Rua B' } }],
      [{ method: 'GET', url: '/config' }],
    ]);
    expect(pedir.mock.calls[1][0].data).toBe(corpo);
  });

  test('a pesquisa de moradas da Geoapify saiu do cliente e do módulo (a da Google vive no seletor); fica a inversa', () => {
    const cliente = criarClienteCrm({ pedir: jest.fn() });
    // Nenhuma chamada de pesquisa, no cliente nem nas exportações soltas do módulo.
    const pesquisas = (nomes) => nomes.filter((nome) => /pesquis/i.test(nome));
    expect(pesquisas(Object.keys(cliente))).toEqual([]);
    expect(pesquisas(Object.keys(moduloApi))).toEqual([]);
    expect(typeof cliente.moradaInversa).toBe('function');
    expect(typeof moduloApi.moradaInversa).toBe('function');
  });

  test('moradaInversa faz GET /morada/inversa com lat e lng; sem ponto (pontoDeBias nulo) vai sem parâmetros', async () => {
    const sugestao = { rotulo: 'Praça do Comércio, Lisboa', morada: 'Praça do Comércio', codigo_postal: '1100-148', localidade: 'Lisboa', lat: 38.7075, lng: -9.1365 };
    const pedir = pedirQueResponde(sugestao, null, null, null);
    const cliente = criarClienteCrm({ pedir });

    await expect(cliente.moradaInversa({ lat: 38.7075, lng: -9.1365, precisao_m: 12 })).resolves.toBe(sugestao);
    // A inversa responde `null` quando não há morada para o ponto.
    await expect(cliente.moradaInversa(pontoDeBias(null))).resolves.toBeNull();
    await expect(cliente.moradaInversa(undefined)).resolves.toBeNull();
    await expect(cliente.moradaInversa({ lat: 0, lng: null })).resolves.toBeNull();

    expect(pedidos(pedir, (c) => [c.method, c.url, c.params, c.data])).toStrictEqual([
      ['GET', '/morada/inversa', { lat: 38.7075, lng: -9.1365 }, undefined],
      ['GET', '/morada/inversa', {}, undefined],
      ['GET', '/morada/inversa', {}, undefined],
      ['GET', '/morada/inversa', { lat: 0 }, undefined],
    ]);
  });

  test('os ids das lojas e das regiões vão codificados num só pedaço do caminho', async () => {
    const pedir = pedirQueResponde({}, {}, {}, {}, {});
    const cliente = criarClienteCrm({ pedir });
    await cliente.obterLoja('a/b?c#d');
    await cliente.alterarLoja('../x', { atualizado_em: VERSAO });
    await cliente.apagarLoja('a b');
    await cliente.alterarRegiao('a/b', { ordem: 1 });
    await cliente.apagarRegiao('?x=1');
    expect(pedir.mock.calls.map(([c]) => c.url)).toEqual([
      '/lojas/a%2Fb%3Fc%23d', '/lojas/..%2Fx', '/lojas/a%20b', '/regioes/a%2Fb', '/regioes/%3Fx%3D1',
    ]);
  });

  test('um id «.», «..» ou vazio nunca sai: o browser resolvia-o para outra rota (a lista, ou a raiz do CRM)', async () => {
    const pedir = pedirQueResponde({});
    const cliente = criarClienteCrm({ pedir });
    const chamadas = (id) => [
      () => cliente.obterLoja(id),
      () => cliente.alterarLoja(id, { atualizado_em: VERSAO }),
      () => cliente.apagarLoja(id),
      () => cliente.alterarRegiao(id, { nome: 'X' }),
      () => cliente.apagarRegiao(id),
      () => cliente.mudarPerfilMembro(id, 'admin'),
      () => cliente.retirarMembro(id),
    ];
    for (const id of ['.', '..', '']) {
      for (const chamada of chamadas(id)) {
        // Rejeita (nunca lança fora da promessa): o ecrã trata-o como os outros erros.
        const e = await rejeicao(chamada());
        expect(e).toBeInstanceOf(ErroCrm);
        expect(forma(e)).toEqual(esperado('erro_interno', MENSAGEM_ERRO_INESPERADO, 0));
      }
    }
    expect(pedir).not.toHaveBeenCalled();
  });

  test('409 duplicado ao criar ou ao alterar uma loja chega com as lojas em extra', async () => {
    const lojas = [{ id: LOJA_ID, nome: 'Café Central', distancia_m: 12 }];
    const duplicado = () => comResposta(409, {
      detail: { codigo: 'duplicado', mensagem: 'Já existe Café Central aqui — é a mesma?', lojas },
    });
    const cliente = criarClienteCrm({ pedir: jest.fn(async () => { throw duplicado(); }) });

    for (const chamada of [
      () => cliente.criarLoja({ nome: 'Café Novo', lat: 38.7, lng: -9.1 }),
      () => cliente.alterarLoja(LOJA_ID, { lat: 38.7, lng: -9.1, atualizado_em: VERSAO }),
    ]) {
      const e = await rejeicao(chamada());
      expect(e).toBeInstanceOf(ErroCrm);
      expect(forma(e)).toEqual(esperado('duplicado', 'Já existe Café Central aqui — é a mesma?', 409, { extra: { lojas } }));
    }
  });

  test('409 conflito ao alterar uma loja só traz código e mensagem; 422 traz os campos', async () => {
    const pedir = jest.fn()
      .mockRejectedValueOnce(comResposta(409, { detail: { codigo: 'conflito', mensagem: 'Alterado por outra pessoa — recarregar' } }))
      .mockRejectedValueOnce(comResposta(422, {
        detail: { codigo: 'validacao', mensagem: MENSAGEM_VALIDACAO, campos: { fabrica_x: 'Esta definição não existe.' } },
      }));
    const cliente = criarClienteCrm({ pedir });

    const conflito = await rejeicao(cliente.alterarLoja(LOJA_ID, { fase: 'cliente', atualizado_em: VERSAO }));
    expect(forma(conflito)).toEqual(esperado('conflito', 'Alterado por outra pessoa — recarregar', 409));

    const validacao = await rejeicao(cliente.alterarDefinicoes({ fabrica_x: 1 }));
    expect(forma(validacao)).toEqual(esperado('validacao', MENSAGEM_VALIDACAO, 422, {
      campos: { fabrica_x: 'Esta definição não existe.' },
    }));
  });

  test('503 da morada inversa chega como morada_indisponivel, com a mensagem do servidor', async () => {
    const inversa = 'Morada sugerida indisponível — escreva a morada à mão.';
    const pedir = jest.fn()
      .mockRejectedValueOnce(comResposta(503, { detail: { codigo: 'morada_indisponivel', mensagem: inversa } }));
    const cliente = criarClienteCrm({ pedir });

    expect(forma(await rejeicao(cliente.moradaInversa({ lat: 38.7, lng: -9.1 }))))
      .toEqual(esperado('morada_indisponivel', inversa, 503));
  });

  test('sem rede, todas as chamadas da F2 rejeitam com sem_rede', async () => {
    const cliente = criarClienteCrm({ pedir: pedirQueFalha(semResposta()) });
    for (const chamada of [
      () => cliente.listarRegioes(), () => cliente.criarRegiao({ nome: 'X' }),
      () => cliente.alterarRegiao(REGIAO_ID, { nome: 'Y' }), () => cliente.apagarRegiao(REGIAO_ID),
      () => cliente.listarLojas(), () => cliente.obterLoja(LOJA_ID), () => cliente.criarLoja({ nome: 'X' }),
      () => cliente.alterarLoja(LOJA_ID, { atualizado_em: VERSAO }), () => cliente.apagarLoja(LOJA_ID),
      () => cliente.obterDefinicoes(), () => cliente.alterarDefinicoes({ fabrica_morada: 'X' }),
      () => cliente.obterConfigMapa(),
      () => cliente.moradaInversa({ lat: 38.7, lng: -9.1 }),
    ]) {
      const e = await rejeicao(chamada());
      expect(e).toBeInstanceOf(ErroCrm);
      expect(forma(e)).toEqual(esperado('sem_rede', MENSAGEM_SEM_REDE, 0));
    }
  });
});

describe('o URL do backend vem de REACT_APP_BACKEND_URL', () => {
  // No Jest a variável não existe (o CRA não carrega o `.env.local` com
  // NODE_ENV=test): comparar o URL_BASE_CRM com a mesma expressão dava
  // 'undefined/api/crm' dos dois lados, e um nome de variável errado no
  // api.js passava (revisão da F0/F1, F2). Aqui fixa-se o valor ANTES de
  // carregar o módulo, num registo de módulos à parte.
  const ORIGINAL = process.env.REACT_APP_BACKEND_URL;

  afterEach(() => {
    if (ORIGINAL === undefined) delete process.env.REACT_APP_BACKEND_URL;
    else process.env.REACT_APP_BACKEND_URL = ORIGINAL;
  });

  const carregarCom = (valor) => {
    process.env.REACT_APP_BACKEND_URL = valor;
    let modulo;
    jest.isolateModules(() => {
      modulo = require('./api');
    });
    return modulo;
  };

  test('absoluto (app nativa, ambiente local): <backend>/api/crm', () => {
    const { URL_BASE_CRM: url, criarInstanciaCrm: criar, instanciaCrm: instancia } = carregarCom('https://backend.exemplo');
    expect(url).toBe('https://backend.exemplo/api/crm');
    expect(criar().defaults.baseURL).toBe('https://backend.exemplo/api/crm');
    expect(instancia.defaults.baseURL).toBe('https://backend.exemplo/api/crm');
  });

  test('vazio (o build do Docker, no mesmo domínio): /api/crm relativo', () => {
    const { URL_BASE_CRM: url, instanciaCrm: instancia } = carregarCom('');
    expect(url).toBe('/api/crm');
    expect(instancia.defaults.baseURL).toBe('/api/crm');
  });

  test('o pedido do /eu sai para <backend>/api/crm/eu', async () => {
    const { obterEu: obter, instanciaCrm: instancia } = carregarCom('https://backend.exemplo');
    const adaptador = jest.fn(async (config) => ({
      data: { membro: false, perfil: null, admin_master: false }, status: 200, statusText: 'OK', headers: {}, config, request: {},
    }));
    instancia.defaults.adapter = adaptador;
    await obter();
    expect(axios.getUri(adaptador.mock.calls[0][0])).toBe('https://backend.exemplo/api/crm/eu');
  });
});

describe('a instância axios do CRM', () => {
  // Um adaptador falso: responde sem rede e guarda o pedido que o axios montou.
  const adaptadorQueResponde = (data) => jest.fn(async (config) => ({
    data, status: 200, statusText: 'OK', headers: {}, config, request: {},
  }));
  const autorizacaoDe = (config) => AxiosHeaders.from(config.headers).get('Authorization');

  test('aponta para /api/crm do backend do portal, com tecto de 30 s', () => {
    // O valor do URL prova-se em «o URL do backend vem de REACT_APP_BACKEND_URL»
    // (abaixo): aqui só se garante que as instâncias usam o URL_BASE_CRM.
    expect(URL_BASE_CRM).toMatch(/\/api\/crm$/);
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

  test('as funções da F2 do módulo saem pela instância do CRM: método, caminho e corpo', async () => {
    const adaptador = adaptadorQueResponde({});
    instanciaCrm.defaults.adapter = adaptador;
    const regiao = '5e2a9d14-7c3b-4e8f-a1d6-3f9b2c8e7a05';
    const loja = '0b6f3c2e-8d4a-4f1b-9c7e-2a5d8e1f3b4c';
    await listarRegioes();
    await criarRegiao({ nome: 'Setúbal', ordem: 1 });
    await alterarRegiao(regiao, { nome: 'Setúbal' });
    await apagarRegiao(regiao);
    await listarLojas();
    await obterLoja(loja);
    await criarLoja({ nome: 'Café', lat: 38.7, lng: -9.1, confirmar_duplicado: true });
    await alterarLoja(loja, { fase: 'cliente', atualizado_em: '2026-10-10T09:00:00.123456Z' });
    await apagarLoja(loja);
    await obterDefinicoes();
    await alterarDefinicoes({ fabrica_lat: 38.7, fabrica_lng: -9.1 });
    await obterConfigMapa();
    await moradaInversa({ lat: 38.7, lng: -9.1 });

    expect(adaptador.mock.calls.map(([c]) => `${c.method.toUpperCase()} ${axios.getUri(c)}`)).toEqual([
      `GET ${URL_BASE_CRM}/regioes`,
      `POST ${URL_BASE_CRM}/regioes`,
      `PATCH ${URL_BASE_CRM}/regioes/${regiao}`,
      `DELETE ${URL_BASE_CRM}/regioes/${regiao}`,
      `GET ${URL_BASE_CRM}/lojas`,
      `GET ${URL_BASE_CRM}/lojas/${loja}`,
      `POST ${URL_BASE_CRM}/lojas`,
      `PATCH ${URL_BASE_CRM}/lojas/${loja}`,
      `DELETE ${URL_BASE_CRM}/lojas/${loja}`,
      `GET ${URL_BASE_CRM}/definicoes`,
      `PATCH ${URL_BASE_CRM}/definicoes`,
      `GET ${URL_BASE_CRM}/config`,
      `GET ${URL_BASE_CRM}/morada/inversa?lat=38.7&lng=-9.1`,
    ]);
    const corpo = (i) => JSON.parse(adaptador.mock.calls[i][0].data);
    expect(corpo(1)).toEqual({ nome: 'Setúbal', ordem: 1 });
    expect(corpo(2)).toEqual({ nome: 'Setúbal' });
    expect(corpo(6)).toEqual({ nome: 'Café', lat: 38.7, lng: -9.1, confirmar_duplicado: true });
    expect(corpo(7)).toEqual({ fase: 'cliente', atualizado_em: '2026-10-10T09:00:00.123456Z' });
    expect(corpo(10)).toEqual({ fabrica_lat: 38.7, fabrica_lng: -9.1 });
    // Os GET e os DELETE não levam corpo.
    for (const i of [0, 3, 4, 5, 8, 9, 11, 12]) expect(adaptador.mock.calls[i][0].data).toBeUndefined();
  });

  test('a query da morada inversa chega ao servidor com os números por extenso, sem nulos', async () => {
    const adaptador = adaptadorQueResponde(null);
    instanciaCrm.defaults.adapter = adaptador;
    await moradaInversa(pontoDeBias({ lat: 38.7077514, lng: -9.1365923 }));
    await moradaInversa({ lat: null, lng: undefined });
    await moradaInversa({ lat: 0, lng: 0 });

    // A query lê-se como o servidor a lê (o `parse_qsl` do Starlette).
    const lida = (i) => {
      const [caminho, query] = axios.getUri(adaptador.mock.calls[i][0]).split('?');
      return [caminho, [...new URLSearchParams(query ?? '').entries()]];
    };
    expect(lida(0)).toEqual([`${URL_BASE_CRM}/morada/inversa`, [['lat', '38.707751'], ['lng', '-9.136592']]]);
    expect(lida(1)).toEqual([`${URL_BASE_CRM}/morada/inversa`, []]);
    expect(lida(2)).toEqual([`${URL_BASE_CRM}/morada/inversa`, [['lat', '0'], ['lng', '0']]]);
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
