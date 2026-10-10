/**
 * O ESTADO DE MEMBRO DA SESSÃO — `GET /api/crm/eu` uma vez por token.
 *
 * O `AdminLayout`, o `EmployeeLayout`, o `CrmLayout` e a guarda das rotas
 * querem todos saber o mesmo: "esta sessão é membro do CRM, e com que perfil?".
 * A resposta guarda-se por token numa cache única da app (`useEstadoCrm`), e
 * estas regras provam-se aqui, sem React:
 *   - o mesmo token → um só pedido (também com dois componentes ao mesmo tempo);
 *   - outro token → pedido novo; a resposta atrasada do token antigo não fica
 *     como a do novo;
 *   - sem token → `EU_NINGUEM`, sem pedido;
 *   - uma falha → `EU_NINGUEM` (o CRM fica escondido) e o pedido seguinte volta
 *     a tentar: um "não" de uma falha não se guarda para a sessão inteira (é
 *     por isso que o backend responde 500 e nunca `membro: false` quando a
 *     base falha — `test_eu.py`);
 *   - e o estado que um componente mostra diz `falhou: true` depois de uma
 *     falha, para a guarda não a confundir com um "não é membro" (revisão da
 *     F0/F1: a guarda recambiava um membro com a rede em baixo).
 *
 * Os `jest.fn` nascem DENTRO de cada teste (o Jest do CRA usa `resetMocks`).
 */
import {
  EU_NINGUEM, PERFIS_CRM, ESTADO_A_CARREGAR, ESTADO_FALHOU, normalizarEu, criarCacheEu, estadoEu,
} from './eu';

const ADMIN_MASTER = { membro: true, perfil: 'admin', admin_master: true };
const UTILIZADOR = { membro: true, perfil: 'utilizador', admin_master: false };
const MOTORISTA = { membro: true, perfil: 'motorista', admin_master: false };
const NAO_MEMBRO = { membro: false, perfil: null, admin_master: false };

// Uma promessa que o teste resolve ou rejeita quando quer.
function adiado() {
  let resolver;
  let rejeitar;
  const promessa = new Promise((ok, falha) => {
    resolver = ok;
    rejeitar = falha;
  });
  return { promessa, resolver, rejeitar };
}

// Deixa correr as continuações pendentes (`.then`) das promessas já resolvidas.
const assentar = () => new Promise((ok) => setTimeout(ok, 0));

describe('constantes', () => {
  test('EU_NINGUEM é a resposta do /eu a quem não é membro, congelada', () => {
    expect(EU_NINGUEM).toEqual({ membro: false, perfil: null, admin_master: false });
    expect(Object.isFrozen(EU_NINGUEM)).toBe(true);
  });

  test('os perfis são os do backend (`crm/dominio/membros.py::PERFIS`), pela mesma ordem', () => {
    expect(PERFIS_CRM).toEqual(['admin', 'utilizador', 'motorista']);
    expect(Object.isFrozen(PERFIS_CRM)).toBe(true);
  });

  test('ESTADO_A_CARREGAR: a carregar e, entretanto, ninguém (ainda não falhou)', () => {
    expect(ESTADO_A_CARREGAR).toEqual({ carregando: true, eu: EU_NINGUEM, falhou: false });
    expect(Object.isFrozen(ESTADO_A_CARREGAR)).toBe(true);
  });

  test('ESTADO_FALHOU: já não carrega, ninguém (CRM escondido) e falhou', () => {
    expect(ESTADO_FALHOU).toEqual({ carregando: false, eu: EU_NINGUEM, falhou: true });
    expect(Object.isFrozen(ESTADO_FALHOU)).toBe(true);
  });
});

describe('normalizarEu(dados)', () => {
  test.each([
    ['admin master', ADMIN_MASTER],
    ['admin', { membro: true, perfil: 'admin', admin_master: false }],
    ['utilizador', UTILIZADOR],
    ['motorista', MOTORISTA],
  ])('%s → igual, congelado', (_nome, dados) => {
    const eu = normalizarEu(dados);
    expect(eu).toEqual(dados);
    expect(eu).not.toBe(dados);
    expect(Object.isFrozen(eu)).toBe(true);
  });

  test('não membro → EU_NINGUEM', () => {
    expect(normalizarEu(NAO_MEMBRO)).toBe(EU_NINGUEM);
  });

  test('só as três chaves passam (o resto da resposta fica de fora)', () => {
    expect(normalizarEu({ ...UTILIZADOR, nome: 'Bea', token: 'x' })).toEqual(UTILIZADOR);
  });

  // Um perfil fora da lista é tratado como no backend (`estado_crm`): não é
  // membro. Fica `perfil: null` e, com ele, `membro: false`.
  test.each([
    ['com maiúscula', 'Admin'],
    ['com espaços', ' admin '],
    ['desconhecido', 'gestor'],
    ['vazio', ''],
    ['nulo', null],
    ['número', 1],
    ['lista', ['admin']],
  ])('perfil %s → null (EU_NINGUEM)', (_nome, perfil) => {
    const eu = normalizarEu({ membro: true, perfil, admin_master: false });
    expect(eu.perfil).toBeNull();
    expect(eu).toBe(EU_NINGUEM);
  });

  test.each([
    ['texto "true"', 'true'],
    ['1', 1],
    ['objeto', {}],
    ['em falta', undefined],
  ])('membro %s → não é membro (só true conta)', (_nome, membro) => {
    expect(normalizarEu({ membro, perfil: 'admin', admin_master: false })).toBe(EU_NINGUEM);
  });

  test('admin_master só com true, e só num admin', () => {
    expect(normalizarEu({ membro: true, perfil: 'admin', admin_master: 'true' }))
      .toEqual({ membro: true, perfil: 'admin', admin_master: false });
    expect(normalizarEu({ membro: true, perfil: 'admin' }))
      .toEqual({ membro: true, perfil: 'admin', admin_master: false });
    expect(normalizarEu({ membro: true, perfil: 'utilizador', admin_master: true })).toEqual(UTILIZADOR);
    expect(normalizarEu({ membro: false, perfil: null, admin_master: true })).toBe(EU_NINGUEM);
  });

  test.each([['nulo', null], ['indefinido', undefined], ['texto', '<html>'], ['lista', [ADMIN_MASTER]], ['número', 42]])(
    '%s → EU_NINGUEM',
    (_nome, dados) => {
      expect(normalizarEu(dados)).toBe(EU_NINGUEM);
    },
  );
});

describe('criarCacheEu(obter) — o mesmo token, um só pedido', () => {
  test('o pedido leva o token e a resposta sai normalizada', async () => {
    const obter = jest.fn(async () => ({ ...UTILIZADOR, extra: 1 }));
    const cache = criarCacheEu(obter);
    const eu = await cache.obter('tok-a');
    expect(eu).toEqual(UTILIZADOR);
    expect(Object.isFrozen(eu)).toBe(true);
    expect(obter).toHaveBeenCalledTimes(1);
    expect(obter).toHaveBeenCalledWith('tok-a');
  });

  test('o mesmo token outra vez → a mesma resposta, sem pedido novo', async () => {
    const obter = jest.fn(async () => ADMIN_MASTER);
    const cache = criarCacheEu(obter);
    const primeiro = await cache.obter('tok-a');
    const segundo = await cache.obter('tok-a');
    const terceiro = await cache.obter('tok-a');
    expect(obter).toHaveBeenCalledTimes(1);
    expect(segundo).toBe(primeiro);
    expect(terceiro).toBe(primeiro);
  });

  test('dois componentes ao mesmo tempo (pedido ainda a correr) → um só pedido', async () => {
    const pedido = adiado();
    const obter = jest.fn(() => pedido.promessa);
    const cache = criarCacheEu(obter);
    const p1 = cache.obter('tok-a');
    const p2 = cache.obter('tok-a');
    expect(obter).toHaveBeenCalledTimes(1);
    pedido.resolver(UTILIZADOR);
    const [r1, r2] = await Promise.all([p1, p2]);
    expect(r1).toEqual(UTILIZADOR);
    expect(r2).toBe(r1);
    expect(obter).toHaveBeenCalledTimes(1);
  });

  test('um "não é membro" também se guarda para o token (não volta a perguntar)', async () => {
    const obter = jest.fn(async () => NAO_MEMBRO);
    const cache = criarCacheEu(obter);
    expect(await cache.obter('tok-a')).toBe(EU_NINGUEM);
    expect(await cache.obter('tok-a')).toBe(EU_NINGUEM);
    expect(obter).toHaveBeenCalledTimes(1);
    expect(cache.memorizado('tok-a')).toBe(EU_NINGUEM);
  });
});

describe('criarCacheEu(obter) — outro token, pedido novo', () => {
  test('outro token → pedido novo; voltar ao primeiro → pede outra vez (guarda só o token atual)', async () => {
    const obter = jest.fn(async (token) => (token === 'tok-a' ? ADMIN_MASTER : UTILIZADOR));
    const cache = criarCacheEu(obter);
    expect(await cache.obter('tok-a')).toEqual(ADMIN_MASTER);
    expect(await cache.obter('tok-b')).toEqual(UTILIZADOR);
    expect(obter).toHaveBeenCalledTimes(2);
    expect(obter).toHaveBeenNthCalledWith(2, 'tok-b');
    expect(cache.memorizado('tok-a')).toBeUndefined();
    expect(await cache.obter('tok-a')).toEqual(ADMIN_MASTER);
    expect(obter).toHaveBeenCalledTimes(3);
  });

  test('a resposta atrasada do token antigo não fica como a do novo', async () => {
    const pedidoA = adiado();
    const pedidoB = adiado();
    const obter = jest.fn((token) => (token === 'tok-a' ? pedidoA.promessa : pedidoB.promessa));
    const cache = criarCacheEu(obter);
    const pA = cache.obter('tok-a');
    const pB = cache.obter('tok-b');
    pedidoA.resolver(ADMIN_MASTER);
    // Quem perguntou pelo token antigo recebe a resposta dele…
    expect(await pA).toEqual(ADMIN_MASTER);
    // …mas a cache não a guarda: nem para o novo, nem para o antigo.
    expect(cache.memorizado('tok-b')).toBeUndefined();
    expect(cache.memorizado('tok-a')).toBeUndefined();
    // O pedido do novo continua a ser o único para ele.
    const pB2 = cache.obter('tok-b');
    expect(obter).toHaveBeenCalledTimes(2);
    pedidoB.resolver(UTILIZADOR);
    expect(await pB).toEqual(UTILIZADOR);
    expect(await pB2).toEqual(UTILIZADOR);
    expect(cache.memorizado('tok-b')).toEqual(UTILIZADOR);
  });

  test('a falha atrasada do token antigo não estraga o pedido do novo', async () => {
    const pedidoA = adiado();
    const pedidoB = adiado();
    const obter = jest.fn((token) => (token === 'tok-a' ? pedidoA.promessa : pedidoB.promessa));
    const cache = criarCacheEu(obter);
    const pA = cache.obter('tok-a');
    const pB = cache.obter('tok-b');
    pedidoA.rejeitar(new Error('rede'));
    expect(await pA).toBe(EU_NINGUEM);
    cache.obter('tok-b');
    expect(obter).toHaveBeenCalledTimes(2);
    pedidoB.resolver(MOTORISTA);
    expect(await pB).toEqual(MOTORISTA);
    expect(cache.memorizado('tok-b')).toEqual(MOTORISTA);
  });
});

describe('criarCacheEu(obter) — sem token', () => {
  test.each([['nulo', null], ['indefinido', undefined], ['vazio', ''], ['número', 123], ['objeto', {}]])(
    'token %s → EU_NINGUEM sem pedido',
    async (_nome, token) => {
      const obter = jest.fn(async () => ADMIN_MASTER);
      const cache = criarCacheEu(obter);
      expect(await cache.obter(token)).toBe(EU_NINGUEM);
      expect(cache.memorizado(token)).toBe(EU_NINGUEM);
      expect(obter).not.toHaveBeenCalled();
    },
  );

  test('terminar a sessão esquece a resposta: o mesmo token depois pede outra vez', async () => {
    const obter = jest.fn(async () => ADMIN_MASTER);
    const cache = criarCacheEu(obter);
    await cache.obter('tok-a');
    expect(cache.memorizado('tok-a')).toEqual(ADMIN_MASTER);
    expect(await cache.obter(null)).toBe(EU_NINGUEM);
    expect(cache.memorizado('tok-a')).toBeUndefined();
    await cache.obter('tok-a');
    expect(obter).toHaveBeenCalledTimes(2);
  });

  test('a resposta que chega depois de terminar a sessão não fica guardada', async () => {
    const pedido = adiado();
    const obter = jest.fn(() => pedido.promessa);
    const cache = criarCacheEu(obter);
    const p = cache.obter('tok-a');
    await cache.obter(null);
    pedido.resolver(ADMIN_MASTER);
    await p;
    expect(cache.memorizado('tok-a')).toBeUndefined();
  });
});

describe('criarCacheEu(obter) — falhas', () => {
  test('pedido rejeitado → EU_NINGUEM (nunca rejeita) e o seguinte volta a tentar', async () => {
    const obter = jest.fn()
      .mockRejectedValueOnce(new Error('Sem rede'))
      .mockResolvedValueOnce(UTILIZADOR);
    const cache = criarCacheEu(obter);
    expect(await cache.obter('tok-a')).toBe(EU_NINGUEM);
    expect(cache.memorizado('tok-a')).toBeUndefined();
    expect(await cache.obter('tok-a')).toEqual(UTILIZADOR);
    expect(obter).toHaveBeenCalledTimes(2);
    expect(cache.memorizado('tok-a')).toEqual(UTILIZADOR);
    // Depois do sucesso, guardado: não pede mais.
    await cache.obter('tok-a');
    expect(obter).toHaveBeenCalledTimes(2);
  });

  test('obter que lança logo (sem promessa) → EU_NINGUEM e o seguinte volta a tentar', async () => {
    const obter = jest.fn()
      .mockImplementationOnce(() => { throw new Error('engano'); })
      .mockImplementationOnce(async () => ADMIN_MASTER);
    const cache = criarCacheEu(obter);
    expect(await cache.obter('tok-a')).toBe(EU_NINGUEM);
    expect(await cache.obter('tok-a')).toEqual(ADMIN_MASTER);
    expect(obter).toHaveBeenCalledTimes(2);
  });

  // Uma resposta 200 sem a forma do /eu (o index.html de um proxy, um corpo
  // vazio) não é um "não é membro": é uma falha, e não se guarda.
  test.each([
    ['nula', null],
    ['texto (HTML)', '<!doctype html>'],
    ['lista', [ADMIN_MASTER]],
    ['objeto sem membro', { perfil: 'admin' }],
    ['membro em texto', { membro: 'true', perfil: 'admin', admin_master: false }],
  ])('resposta %s → falha: EU_NINGUEM, não guardada, volta a tentar', async (_nome, resposta) => {
    const obter = jest.fn()
      .mockResolvedValueOnce(resposta)
      .mockResolvedValueOnce(UTILIZADOR);
    const cache = criarCacheEu(obter);
    expect(await cache.obter('tok-a')).toBe(EU_NINGUEM);
    expect(cache.memorizado('tok-a')).toBeUndefined();
    expect(await cache.obter('tok-a')).toEqual(UTILIZADOR);
    expect(obter).toHaveBeenCalledTimes(2);
  });

  test('dois à espera de um pedido que falha → os dois recebem EU_NINGUEM, um só pedido', async () => {
    const pedido = adiado();
    const obter = jest.fn(() => pedido.promessa);
    const cache = criarCacheEu(obter);
    const p1 = cache.obter('tok-a');
    const p2 = cache.obter('tok-a');
    pedido.rejeitar(new Error('500'));
    expect(await p1).toBe(EU_NINGUEM);
    expect(await p2).toBe(EU_NINGUEM);
    expect(obter).toHaveBeenCalledTimes(1);
  });
});

describe('criarCacheEu(obter) — memorizado e avisos', () => {
  test('memorizado: nada antes da resposta, a resposta depois (a mesma referência)', async () => {
    const pedido = adiado();
    const cache = criarCacheEu(jest.fn(() => pedido.promessa));
    expect(cache.memorizado('tok-a')).toBeUndefined();
    const p = cache.obter('tok-a');
    expect(cache.memorizado('tok-a')).toBeUndefined();
    pedido.resolver(ADMIN_MASTER);
    const eu = await p;
    expect(cache.memorizado('tok-a')).toBe(eu);
    expect(cache.memorizado('tok-a')).toBe(cache.memorizado('tok-a'));
  });

  test('avisa quem subscreveu quando a resposta fica guardada, e deixa de avisar ao sair', async () => {
    const respostas = { 'tok-a': UTILIZADOR, 'tok-b': MOTORISTA };
    const cache = criarCacheEu(jest.fn(async (token) => respostas[token]));
    const ouvinte = jest.fn();
    const outro = jest.fn();
    const sair = cache.subscrever(ouvinte);
    cache.subscrever(outro);

    await cache.obter('tok-a');
    expect(ouvinte).toHaveBeenCalledTimes(1);
    expect(outro).toHaveBeenCalledTimes(1);

    sair();
    await cache.obter('tok-b');
    expect(ouvinte).toHaveBeenCalledTimes(1);
    expect(outro).toHaveBeenCalledTimes(2);
  });

  test('a resposta atrasada de um token antigo não avisa ninguém', async () => {
    const pedidoA = adiado();
    const pedidoB = adiado();
    const cache = criarCacheEu(jest.fn((token) => (token === 'tok-a' ? pedidoA.promessa : pedidoB.promessa)));
    const ouvinte = jest.fn();
    cache.subscrever(ouvinte);
    const pA = cache.obter('tok-a');
    cache.obter('tok-b');
    pedidoA.resolver(ADMIN_MASTER);
    await pA;
    expect(ouvinte).not.toHaveBeenCalled();
    pedidoB.resolver(UTILIZADOR);
    await assentar();
    expect(ouvinte).toHaveBeenCalledTimes(1);
  });

  test('o aviso chega com o valor já guardado (lido dentro do ouvinte)', async () => {
    const cache = criarCacheEu(jest.fn(async () => MOTORISTA));
    const vistos = [];
    cache.subscrever(() => vistos.push(cache.memorizado('tok-a')));
    await cache.obter('tok-a');
    await assentar();
    expect(vistos).toContainEqual(MOTORISTA);
  });

  test('uma falha não avisa ninguém (nada mudou no que está guardado)', async () => {
    const pedido = adiado();
    const cache = criarCacheEu(jest.fn(() => pedido.promessa));
    const p = cache.obter('tok-a');
    const ouvinte = jest.fn();
    cache.subscrever(ouvinte);
    pedido.rejeitar(new Error('x'));
    await p;
    expect(ouvinte).not.toHaveBeenCalled();
  });
});

describe('estadoEu(memorizado, jaRespondeu)', () => {
  test('com resposta guardada → não carrega, mostra-a e não falhou', () => {
    const eu = normalizarEu(UTILIZADOR);
    expect(estadoEu(eu, false)).toEqual({ carregando: false, eu, falhou: false });
    expect(estadoEu(eu, true)).toEqual({ carregando: false, eu, falhou: false });
    expect(estadoEu(eu, true).eu).toBe(eu);
    // Um "não é membro" de verdade (resposta do servidor) não é uma falha.
    expect(estadoEu(EU_NINGUEM, false)).toEqual({ carregando: false, eu: EU_NINGUEM, falhou: false });
    expect(estadoEu(EU_NINGUEM, true)).toEqual({ carregando: false, eu: EU_NINGUEM, falhou: false });
  });

  test('sem resposta e sem pedido terminado → a carregar (a guarda espera, não recambia)', () => {
    expect(estadoEu(undefined, false)).toBe(ESTADO_A_CARREGAR);
  });

  test('sem resposta mas o pedido já terminou → falhou: CRM escondido, mas dito (a guarda não recambia)', () => {
    expect(estadoEu(undefined, true)).toBe(ESTADO_FALHOU);
    expect(estadoEu(undefined, true).falhou).toBe(true);
    expect(estadoEu(undefined, true).eu).toBe(EU_NINGUEM);
  });
});
