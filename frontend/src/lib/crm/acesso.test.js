/**
 * QUEM VÊ O CRM, E ONDE — as regras de visibilidade, corridas e não lidas.
 *
 * Os layouts (`AdminLayout`, `EmployeeLayout`, `CrmLayout`) e a guarda das
 * rotas (`GuardaCrm`) só CHAMAM estas funções: a decisão vive aqui, em funções
 * puras, para se poder provar sem desenhar ecrãs. A interface só esconde; é o
 * servidor que protege (`crm/auth.py` e `test_protecao_rotas.py`).
 *
 * A regra de fundo é fechar na dúvida: um `eu` estragado, uma opção em falta
 * ou uma regra que rebenta escondem o CRM — nunca o mostram por engano, e
 * nunca deitam abaixo o menu do resto do portal.
 */
import {
  BASE_CRM, BASE_CRM_ADMIN, PERFIS_ESCRITORIO, ITENS_MENU_CRM,
  podeAbrirAreaCrm, eAdminCrm, seccaoVisivel, rotaDoCrmNoAdmin, baseCrm, ecraCheioDoCrm, itensMenuCrm,
} from './acesso';

// As respostas do `GET /api/crm/eu`, tal como o backend as manda.
const ADMIN_MASTER = { membro: true, perfil: 'admin', admin_master: true };
const ADMIN = { membro: true, perfil: 'admin', admin_master: false };
const UTILIZADOR = { membro: true, perfil: 'utilizador', admin_master: false };
const MOTORISTA = { membro: true, perfil: 'motorista', admin_master: false };
const NAO_MEMBRO = { membro: false, perfil: null, admin_master: false };

const NO_BROWSER = { nativo: false };
const NA_APP = { nativo: true };

// `eu` que nunca deviam chegar aqui (o `eu.js` normaliza), mas podem.
const EU_ESTRAGADOS = [
  ['nulo', null],
  ['indefinido', undefined],
  ['texto', 'admin'],
  ['lista', [ADMIN]],
  ['objeto vazio', {}],
  ['membro em texto', { membro: 'true', perfil: 'admin', admin_master: false }],
  ['membro 1', { membro: 1, perfil: 'admin', admin_master: false }],
  ['sem membro', { perfil: 'admin' }],
  ['perfil com maiúscula', { membro: true, perfil: 'Admin', admin_master: false }],
  ['perfil com espaços', { membro: true, perfil: ' admin ', admin_master: false }],
  ['perfil desconhecido', { membro: true, perfil: 'gestor', admin_master: false }],
  ['perfil nulo', { membro: true, perfil: null, admin_master: false }],
  ['perfil em lista', { membro: true, perfil: ['admin'], admin_master: false }],
  ['não membro com perfil', { membro: false, perfil: 'admin', admin_master: true }],
];

describe('constantes', () => {
  test('as duas casas do CRM e os perfis de escritório', () => {
    expect(BASE_CRM).toBe('/crm');
    expect(BASE_CRM_ADMIN).toBe('/admin/crm');
    // = `ESCRITORIO = exigir_perfil("admin", "utilizador")` do backend.
    expect(PERFIS_ESCRITORIO).toEqual(['admin', 'utilizador']);
    expect(Object.isFrozen(PERFIS_ESCRITORIO)).toBe(true);
  });

  test('os itens do menu estão congelados (um ecrã não os muda para os outros)', () => {
    expect(Object.isFrozen(ITENS_MENU_CRM)).toBe(true);
    for (const item of ITENS_MENU_CRM) expect(Object.isFrozen(item)).toBe(true);
  });
});

describe('podeAbrirAreaCrm(eu, {nativo})', () => {
  test.each([
    ['admin master', ADMIN_MASTER],
    ['admin', ADMIN],
    ['utilizador', UTILIZADOR],
  ])('membro %s no browser → entra', (_nome, eu) => {
    expect(podeAbrirAreaCrm(eu, NO_BROWSER)).toBe(true);
  });

  test('motorista → não entra (o terreno chega na F4, pela "Rota do dia")', () => {
    expect(podeAbrirAreaCrm(MOTORISTA, NO_BROWSER)).toBe(false);
  });

  test('não membro → não entra', () => {
    expect(podeAbrirAreaCrm(NAO_MEMBRO, NO_BROWSER)).toBe(false);
  });

  test.each(EU_ESTRAGADOS)('eu %s → não entra', (_nome, eu) => {
    expect(podeAbrirAreaCrm(eu, NO_BROWSER)).toBe(false);
  });

  test.each([
    ['admin master', ADMIN_MASTER],
    ['admin', ADMIN],
    ['utilizador', UTILIZADOR],
    ['motorista', MOTORISTA],
  ])('na app nativa → nunca entra, nem o %s', (_nome, eu) => {
    expect(podeAbrirAreaCrm(eu, NA_APP)).toBe(false);
  });

  // Fecha na dúvida: quem se esquecer de dizer onde corre não abre o CRM na
  // app nativa por engano (no browser vê-se logo que falta a opção).
  test.each([
    ['sem opções', undefined],
    ['opções nulas', null],
    ['opções vazias', {}],
    ['nativo indefinido', { nativo: undefined }],
    ['nativo em texto', { nativo: 'false' }],
    ['nativo 0', { nativo: 0 }],
  ])('%s → não entra', (_nome, opcoes) => {
    expect(podeAbrirAreaCrm(ADMIN, opcoes)).toBe(false);
  });
});

describe('eAdminCrm(eu)', () => {
  test('admin e admin master → sim', () => {
    expect(eAdminCrm(ADMIN)).toBe(true);
    expect(eAdminCrm(ADMIN_MASTER)).toBe(true);
  });

  test('utilizador, motorista e não membro → não', () => {
    expect(eAdminCrm(UTILIZADOR)).toBe(false);
    expect(eAdminCrm(MOTORISTA)).toBe(false);
    expect(eAdminCrm(NAO_MEMBRO)).toBe(false);
  });

  test.each(EU_ESTRAGADOS)('eu %s → não', (_nome, eu) => {
    expect(eAdminCrm(eu)).toBe(false);
  });
});

describe('seccaoVisivel(seccao, ctx)', () => {
  test('sem `visivel` → visível (as secções que já existem no AdminLayout)', () => {
    expect(seccaoVisivel({ key: 'rh', label: 'RH' }, { podeVerCrm: false })).toBe(true);
    expect(seccaoVisivel({ key: 'rh', visivel: undefined }, {})).toBe(true);
    expect(seccaoVisivel({ key: 'rh' })).toBe(true);
  });

  test('com função → o resultado, chamada com o ctx', () => {
    const visivel = jest.fn(() => true);
    const ctx = { podeVerCrm: true };
    expect(seccaoVisivel({ key: 'crm', visivel }, ctx)).toBe(true);
    expect(visivel).toHaveBeenCalledTimes(1);
    expect(visivel).toHaveBeenCalledWith(ctx);
  });

  test('a regra da secção CRM: só com podeVerCrm === true', () => {
    const seccao = { key: 'crm', visivel: (ctx) => ctx.podeVerCrm };
    expect(seccaoVisivel(seccao, { podeVerCrm: true })).toBe(true);
    expect(seccaoVisivel(seccao, { podeVerCrm: false })).toBe(false);
    expect(seccaoVisivel(seccao, {})).toBe(false);
  });

  test.each([
    ['false', false], ['1', 1], ['texto', 'sim'], ['objeto', {}], ['nulo', null], ['indefinido', undefined],
  ])('a função devolve %s → escondida (só conta === true)', (_nome, valor) => {
    expect(seccaoVisivel({ key: 'crm', visivel: () => valor }, {})).toBe(false);
  });

  test('`visivel` que não é função: só true mostra', () => {
    expect(seccaoVisivel({ key: 'crm', visivel: true }, {})).toBe(true);
    expect(seccaoVisivel({ key: 'crm', visivel: false }, {})).toBe(false);
    expect(seccaoVisivel({ key: 'crm', visivel: 'sim' }, {})).toBe(false);
    expect(seccaoVisivel({ key: 'crm', visivel: null }, {})).toBe(false);
  });

  // Sem ctx a regra do CRM rebentava (`ctx.podeVerCrm` de undefined). Uma
  // regra que rebenta esconde a secção e não deita abaixo o menu do portal.
  test('uma regra que rebenta → escondida, sem lançar', () => {
    const seccao = { key: 'crm', visivel: (ctx) => ctx.podeVerCrm };
    expect(() => seccaoVisivel(seccao, undefined)).not.toThrow();
    expect(seccaoVisivel(seccao, undefined)).toBe(false);
    expect(seccaoVisivel({ key: 'x', visivel: () => { throw new Error('x'); } }, {})).toBe(false);
  });

  test.each([['nula', null], ['indefinida', undefined], ['texto', 'crm'], ['lista', []]])(
    'secção %s → escondida',
    (_nome, seccao) => {
      expect(seccaoVisivel(seccao, { podeVerCrm: true })).toBe(false);
    },
  );
});

describe('rotaDoCrmNoAdmin(caminho)', () => {
  test.each([
    '/admin/crm',
    '/admin/crm/',
    '/admin/crm/mapa',
    '/admin/crm/lojas/nova',
    '/admin/crm/lojas/x',
    '/admin/crm/definicoes',
  ])('%s → é do CRM', (caminho) => {
    expect(rotaDoCrmNoAdmin(caminho)).toBe(true);
  });

  // O React Router compara caminhos sem distinguir maiúsculas: `/admin/CRM/mapa`
  // abre a página do CRM, por isso o menu tem de a reconhecer também.
  test.each(['/admin/CRM', '/admin/Crm/Mapa', '/ADMIN/CRM/MAPA'])('%s → é do CRM (sem distinguir maiúsculas)', (caminho) => {
    expect(rotaDoCrmNoAdmin(caminho)).toBe(true);
  });

  test.each([
    '/admin/crmx',
    '/admin/crm-velho',
    '/admin/colaboradores',
    '/admin',
    '/admin/',
    '/crm',
    '/crm/mapa',
    '/x/admin/crm',
    '/admin/financeiro/crm',
    '',
  ])('%s → não é', (caminho) => {
    expect(rotaDoCrmNoAdmin(caminho)).toBe(false);
  });

  test.each([[null], [undefined], [42], [['/admin/crm']]])('%p → não é (sem lançar)', (caminho) => {
    expect(rotaDoCrmNoAdmin(caminho)).toBe(false);
  });
});

describe('baseCrm(caminho)', () => {
  test.each([
    ['/admin/crm/lojas/x', '/admin/crm'],
    ['/admin/crm', '/admin/crm'],
    ['/admin/crm/mapa', '/admin/crm'],
    ['/admin/CRM/mapa', '/admin/crm'],
    ['/crm/mapa', '/crm'],
    ['/crm', '/crm'],
    ['/crm/lojas/nova', '/crm'],
  ])('%s → %s', (caminho, base) => {
    expect(baseCrm(caminho)).toBe(base);
  });

  test.each([['/admin/crmx'], ['/colaborador'], [''], [null], [undefined]])('%p → a área própria (/crm)', (caminho) => {
    expect(baseCrm(caminho)).toBe('/crm');
  });
});

describe('ecraCheioDoCrm(caminho)', () => {
  test.each([
    '/crm',
    '/crm/',
    '/crm/mapa',
    '/crm/mapa/',
    '/admin/crm',
    '/admin/crm/',
    '/admin/crm/mapa',
    '/admin/crm/mapa/',
    '/admin/CRM/Mapa',
  ])('%s → o mapa ocupa a área toda', (caminho) => {
    expect(ecraCheioDoCrm(caminho)).toBe(true);
  });

  test.each([
    '/crm/lojas/nova',
    '/admin/crm/lojas/nova',
    '/crm/lojas/x',
    '/admin/crm/lojas/x',
    '/crm/definicoes',
    '/admin/crm/definicoes',
    '/crm/mapa/x',
    '/crm/mapax',
    '/crmx',
    '/admin/crmx/mapa',
    '/x/crm',
    '/x/crm/mapa',
    '/admin',
    '/colaborador',
    '/',
    '',
  ])('%s → área normal, com margens', (caminho) => {
    expect(ecraCheioDoCrm(caminho)).toBe(false);
  });

  test.each([[null], [undefined], [7], [['/crm']]])('%p → área normal (sem lançar)', (caminho) => {
    expect(ecraCheioDoCrm(caminho)).toBe(false);
  });
});

describe('itensMenuCrm(eu, base)', () => {
  const MAPA = { chave: 'mapa', rotulo: 'Mapa', caminho: '/crm/mapa' };
  const NOVA_LOJA = { chave: 'loja-nova', rotulo: 'Nova loja', caminho: '/crm/lojas/nova' };
  const DEFINICOES = { chave: 'definicoes', rotulo: 'Definições', caminho: '/crm/definicoes' };

  test('admin → Mapa, Nova loja e Definições, por esta ordem', () => {
    expect(itensMenuCrm(ADMIN)).toEqual([MAPA, NOVA_LOJA, DEFINICOES]);
    expect(itensMenuCrm(ADMIN_MASTER)).toEqual([MAPA, NOVA_LOJA, DEFINICOES]);
  });

  test('utilizador → Mapa e Nova loja, sem Definições', () => {
    expect(itensMenuCrm(UTILIZADOR)).toEqual([MAPA, NOVA_LOJA]);
  });

  test('motorista e não membro → nada', () => {
    expect(itensMenuCrm(MOTORISTA)).toEqual([]);
    expect(itensMenuCrm(NAO_MEMBRO)).toEqual([]);
  });

  test.each(EU_ESTRAGADOS)('eu %s → nada', (_nome, eu) => {
    expect(itensMenuCrm(eu)).toEqual([]);
  });

  test('dentro da gestão, os caminhos são os de /admin/crm', () => {
    expect(itensMenuCrm(ADMIN, '/admin/crm')).toEqual([
      { chave: 'mapa', rotulo: 'Mapa', caminho: '/admin/crm/mapa' },
      { chave: 'loja-nova', rotulo: 'Nova loja', caminho: '/admin/crm/lojas/nova' },
      { chave: 'definicoes', rotulo: 'Definições', caminho: '/admin/crm/definicoes' },
    ]);
    expect(itensMenuCrm(UTILIZADOR, baseCrm('/admin/crm/lojas/x')).map((i) => i.caminho))
      .toEqual(['/admin/crm/mapa', '/admin/crm/lojas/nova']);
  });

  test('uma base desconhecida dá a área própria (/crm), nunca um caminho inventado', () => {
    expect(itensMenuCrm(UTILIZADOR, '/outro').map((i) => i.caminho)).toEqual(['/crm/mapa', '/crm/lojas/nova']);
    expect(itensMenuCrm(UTILIZADOR, null).map((i) => i.caminho)).toEqual(['/crm/mapa', '/crm/lojas/nova']);
  });

  test('o Mapa abre em ecrã cheio e a Nova loja não', () => {
    const [mapa, novaLoja] = itensMenuCrm(ADMIN);
    expect(ecraCheioDoCrm(mapa.caminho)).toBe(true);
    expect(ecraCheioDoCrm(novaLoja.caminho)).toBe(false);
  });

  test('cada chamada devolve itens novos (mudá-los não muda o menu seguinte)', () => {
    const primeiros = itensMenuCrm(ADMIN);
    primeiros[0].rotulo = 'Estragado';
    primeiros.pop();
    expect(itensMenuCrm(ADMIN)).toEqual([MAPA, NOVA_LOJA, DEFINICOES]);
  });
});
