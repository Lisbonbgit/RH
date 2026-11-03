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
import fs from 'fs';
import path from 'path';
import {
  BASE_CRM, BASE_CRM_ADMIN, PERFIS_ESCRITORIO, ITENS_MENU_CRM, MENSAGEM_ACESSO_FALHOU,
  podeAbrirAreaCrm, eAdminCrm, seccaoVisivel, rotaDoCrmNoAdmin, baseCrm, ecraCheioDoCrm, itensMenuCrm,
  decisaoGuardaCrm, decisaoSoAdminCrm,
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

  // F3 / T3.35: as Rotas entram depois do Mapa, para os perfis de escritório (como no backend, as rotas
  // `/api/crm/rotas…` são do `ESCRITORIO`).
  test('o menu: Mapa, Rotas, Nova loja e Definições, por esta ordem', () => {
    expect(ITENS_MENU_CRM).toEqual([
      { chave: 'mapa', rotulo: 'Mapa', caminho: 'mapa', soAdmin: false },
      { chave: 'rotas', rotulo: 'Rotas', caminho: 'rotas', soAdmin: false },
      { chave: 'loja-nova', rotulo: 'Nova loja', caminho: 'lojas/nova', soAdmin: false },
      { chave: 'definicoes', rotulo: 'Definições', caminho: 'definicoes', soAdmin: true },
    ]);
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

// O estado de `useEstadoCrm()` (`estadoEu` do `eu.js`): a carregar, com
// resposta, ou falhou (o pedido terminou sem resposta — rede em baixo, 502 de
// um reinício, um 200 que não é do `/eu`).
const A_CARREGAR = { carregando: true, eu: NAO_MEMBRO, falhou: false };
const FALHOU = { carregando: false, eu: NAO_MEMBRO, falhou: true };
const respondeu = (eu) => ({ carregando: false, eu, falhou: false });

// Estados que nunca deviam chegar à guarda (o hook dá sempre a forma certa).
const ESTADOS_ESTRAGADOS = [
  ['nulo', null],
  ['indefinido', undefined],
  ['texto', 'entrar'],
  ['lista', [respondeu(ADMIN)]],
  ['objeto vazio', {}],
  ['falhou em texto', { carregando: false, eu: NAO_MEMBRO, falhou: 'true' }],
];

describe('decisaoGuardaCrm(estado, {nativo}) — a guarda da área do CRM', () => {
  test('a mensagem de quando não se consegue confirmar o acesso', () => {
    expect(MENSAGEM_ACESSO_FALHOU).toBe('Não foi possível confirmar o acesso ao CRM. Verifique a ligação e tente de novo.');
  });

  test('a carregar → espera (nunca recambia a meio de um pedido)', () => {
    expect(decisaoGuardaCrm(A_CARREGAR, NO_BROWSER)).toBe('esperar');
    expect(decisaoGuardaCrm({ ...A_CARREGAR, eu: ADMIN }, NO_BROWSER)).toBe('esperar');
    expect(decisaoGuardaCrm(A_CARREGAR, NA_APP)).toBe('esperar');
  });

  test.each([
    ['admin master', ADMIN_MASTER],
    ['admin', ADMIN],
    ['utilizador', UTILIZADOR],
  ])('membro %s no browser → entra', (_nome, eu) => {
    expect(decisaoGuardaCrm(respondeu(eu), NO_BROWSER)).toBe('entrar');
  });

  test.each([
    ['não membro', NAO_MEMBRO],
    ['motorista', MOTORISTA],
  ])('%s (resposta do servidor) → recambia para o início', (_nome, eu) => {
    expect(decisaoGuardaCrm(respondeu(eu), NO_BROWSER)).toBe('recambiar');
  });

  // Revisão da F0/F1: com o `/eu` sem resposta (4G fraco, reinício do
  // backend), a guarda recambiava um membro para fora do CRM. Uma falha não
  // é um "não": mostra o aviso com "Tentar de novo".
  test('o pedido falhou, no browser → mostra a falha, NUNCA recambia', () => {
    expect(decisaoGuardaCrm(FALHOU, NO_BROWSER)).toBe('falhou');
  });

  test.each([
    ['na app nativa', NA_APP],
    ['sem opções', undefined],
    ['nativo em texto', { nativo: 'false' }],
  ])('o pedido falhou %s → recambia (o CRM fica escondido)', (_nome, opcoes) => {
    expect(decisaoGuardaCrm(FALHOU, opcoes)).toBe('recambiar');
  });

  test('na app nativa nunca entra, nem o admin', () => {
    expect(decisaoGuardaCrm(respondeu(ADMIN), NA_APP)).toBe('recambiar');
  });

  test.each(ESTADOS_ESTRAGADOS)('estado %s → recambia (fecha na dúvida)', (_nome, estado) => {
    expect(decisaoGuardaCrm(estado, NO_BROWSER)).toBe('recambiar');
  });
});

describe('decisaoSoAdminCrm(estado) — as Definições', () => {
  test('a carregar → espera', () => {
    expect(decisaoSoAdminCrm(A_CARREGAR)).toBe('esperar');
    expect(decisaoSoAdminCrm({ ...A_CARREGAR, eu: ADMIN })).toBe('esperar');
  });

  test.each([
    ['admin master', ADMIN_MASTER],
    ['admin', ADMIN],
  ])('%s → entra', (_nome, eu) => {
    expect(decisaoSoAdminCrm(respondeu(eu))).toBe('entrar');
  });

  test.each([
    ['utilizador', UTILIZADOR],
    ['motorista', MOTORISTA],
    ['não membro', NAO_MEMBRO],
  ])('%s → recambia para o mapa', (_nome, eu) => {
    expect(decisaoSoAdminCrm(respondeu(eu))).toBe('recambiar');
  });

  test('o pedido falhou → mostra a falha, nunca recambia', () => {
    expect(decisaoSoAdminCrm(FALHOU)).toBe('falhou');
  });

  test.each(ESTADOS_ESTRAGADOS)('estado %s → recambia para o mapa', (_nome, estado) => {
    expect(decisaoSoAdminCrm(estado)).toBe('recambiar');
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
    '/admin/crm/rotas',
    '/admin/crm/rotas/2026-10-12',
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
    ['/admin/crm/rotas/2026-10-12', '/admin/crm'],
    ['/crm/rotas/2026-10-12', '/crm'],
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

  // F3 / T3.35: o planeador de um dia (`rotas/:data`) é mapa e painel, também na área toda — só com um dia
  // que existe (o `eDataValida` do `datas.js`, a mesma regra com que o planeador decide "Dia inválido").
  test.each([
    '/crm/rotas/2026-10-12',
    '/crm/rotas/2026-10-12/',
    '/crm/rotas/2026-10-12//',
    '/admin/crm/rotas/2026-10-12',
    '/admin/crm/rotas/2026-10-12/',
    '/ADMIN/CRM/ROTAS/2026-10-12',
    '/Crm/Rotas/2026-10-12',
    '/crm/rotas/2028-02-29',
    '/crm/rotas/2026-12-31',
  ])('%s → o planeador ocupa a área toda', (caminho) => {
    expect(ecraCheioDoCrm(caminho)).toBe(true);
  });

  test.each([
    '/crm/rotas',
    '/crm/rotas/',
    '/admin/crm/rotas',
    '/admin/crm/rotas/',
    '/crm/rotas/abc',
    '/admin/crm/rotas/abc',
    '/crm/rotas/2026-10-12/x',
    '/crm/rotas/2026-10-12x',
    '/crm/rotas/x2026-10-12',
    '/crm/rotas/2026-1-12',
    '/crm/rotas/2026-10-123',
    '/crm/rotas/20261012',
    '/crm/rotas/2026-02-30',
    '/crm/rotas/2027-02-29',
    '/crm/rotas/2026-13-01',
    '/crm/rotas/2026-00-10',
    '/crm/rotas/2026-10-00',
    '/crm/rotas/２０２６-10-12',
    '/crm/rotas2026-10-12',
    '/crm/rotasx/2026-10-12',
    '/crm/rota/2026-10-12',
    '/crm/mapa/2026-10-12',
    '/crm/2026-10-12',
    '/x/crm/rotas/2026-10-12',
    '/admin/crmx/rotas/2026-10-12',
    '/admin/x/crm/rotas/2026-10-12',
  ])('%s → área normal, com margens (a lista das Rotas ou "Dia inválido")', (caminho) => {
    expect(ecraCheioDoCrm(caminho)).toBe(false);
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
  const ROTAS = { chave: 'rotas', rotulo: 'Rotas', caminho: '/crm/rotas' };
  const NOVA_LOJA = { chave: 'loja-nova', rotulo: 'Nova loja', caminho: '/crm/lojas/nova' };
  const DEFINICOES = { chave: 'definicoes', rotulo: 'Definições', caminho: '/crm/definicoes' };

  test('admin → Mapa, Rotas, Nova loja e Definições, por esta ordem', () => {
    expect(itensMenuCrm(ADMIN)).toEqual([MAPA, ROTAS, NOVA_LOJA, DEFINICOES]);
    expect(itensMenuCrm(ADMIN_MASTER)).toEqual([MAPA, ROTAS, NOVA_LOJA, DEFINICOES]);
  });

  test('utilizador → Mapa, Rotas e Nova loja, sem Definições', () => {
    expect(itensMenuCrm(UTILIZADOR)).toEqual([MAPA, ROTAS, NOVA_LOJA]);
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
      { chave: 'rotas', rotulo: 'Rotas', caminho: '/admin/crm/rotas' },
      { chave: 'loja-nova', rotulo: 'Nova loja', caminho: '/admin/crm/lojas/nova' },
      { chave: 'definicoes', rotulo: 'Definições', caminho: '/admin/crm/definicoes' },
    ]);
    expect(itensMenuCrm(UTILIZADOR, baseCrm('/admin/crm/lojas/x')).map((i) => i.caminho))
      .toEqual(['/admin/crm/mapa', '/admin/crm/rotas', '/admin/crm/lojas/nova']);
  });

  test('uma base desconhecida dá a área própria (/crm), nunca um caminho inventado', () => {
    expect(itensMenuCrm(UTILIZADOR, '/outro').map((i) => i.caminho)).toEqual(['/crm/mapa', '/crm/rotas', '/crm/lojas/nova']);
    expect(itensMenuCrm(UTILIZADOR, null).map((i) => i.caminho)).toEqual(['/crm/mapa', '/crm/rotas', '/crm/lojas/nova']);
  });

  test('o Mapa abre em ecrã cheio; as Rotas (a lista), a Nova loja e as Definições não', () => {
    const [mapa, rotas, novaLoja, definicoes] = itensMenuCrm(ADMIN);
    expect(ecraCheioDoCrm(mapa.caminho)).toBe(true);
    expect(ecraCheioDoCrm(rotas.caminho)).toBe(false);
    expect(ecraCheioDoCrm(novaLoja.caminho)).toBe(false);
    expect(ecraCheioDoCrm(definicoes.caminho)).toBe(false);
  });

  test('o planeador de um dia, a partir do item Rotas, abre em ecrã cheio nas duas casas', () => {
    for (const base of [BASE_CRM, BASE_CRM_ADMIN]) {
      const rotas = itensMenuCrm(UTILIZADOR, base).find((item) => item.chave === 'rotas');
      expect(ecraCheioDoCrm(`${rotas.caminho}/2026-10-12`)).toBe(true);
      expect(ecraCheioDoCrm(`${rotas.caminho}/abc`)).toBe(false);
    }
  });

  test('cada chamada devolve itens novos (mudá-los não muda o menu seguinte)', () => {
    const primeiros = itensMenuCrm(ADMIN);
    primeiros[0].rotulo = 'Estragado';
    primeiros.pop();
    expect(itensMenuCrm(ADMIN)).toEqual([MAPA, ROTAS, NOVA_LOJA, DEFINICOES]);
  });
});

// --- Os ficheiros que desenham o menu e as rotas batem com o ITENS_MENU_CRM ---------------------
//
// Os componentes não têm Jest (§1 da F1–F2), mas o que liga o menu às páginas é texto que se lê: um
// caminho do menu sem rota abria o mapa (`*`), uma chave sem ícone desenhava o item sem ele, e uma página
// preguiçosa que não existe só rebentava ao abri-la.
const SRC = path.join(__dirname, '..', '..');
const lerFonte = (relativo) => fs.readFileSync(path.join(SRC, relativo), 'utf8');
const ROTAS_CRM = 'pages/crm/rotasCrm.js';
const DESENHAM_O_MENU = ['components/layouts/CrmLayout.js', 'components/crm/seccaoCrm.js'];

// As chaves do `const ICONES = { … };` de um ficheiro, pela ordem, com o nome do ícone de cada uma.
function iconesDe(texto) {
  const bloco = /\bconst ICONES = \{([^}]*)\};/.exec(texto);
  if (bloco === null) return null;
  return [...bloco[1].matchAll(/(?:'([^']+)'|([A-Za-z_$][\w$]*))\s*:\s*([A-Za-z_$][\w$]*)/g)].map(
    ([, entreAspas, solta, icone]) => [entreAspas ?? solta, icone],
  );
}

// O `element` de cada `<Route path="…">` do `filhosCrm()`: {caminho: 'pagina(nome, Componente)' ou outro}.
function rotasDe(texto) {
  return Object.fromEntries(
    [...texto.matchAll(/<Route\s+path="([^"]+)"\s+element=\{(.*?)\}\s*\/>/g)].map(([, caminho, elemento]) => [caminho, elemento]),
  );
}

describe('o menu e as rotas das páginas (rotasCrm.js, CrmLayout.js e seccaoCrm.js)', () => {
  test('cada caminho do menu tem a sua rota no rotasCrm.js', () => {
    const rotas = rotasDe(lerFonte(ROTAS_CRM));
    for (const { caminho } of ITENS_MENU_CRM) expect(Object.keys(rotas)).toContain(caminho);
  });

  test('as Rotas abrem a lista (CrmRotas) e rotas/:data o planeador (CrmRota), cada uma com o seu limite', () => {
    const rotas = rotasDe(lerFonte(ROTAS_CRM));
    expect(rotas.rotas).toBe("pagina('rotas', CrmRotas)");
    expect(rotas['rotas/:data']).toBe("pagina('rota', CrmRota)");
  });

  test('cada página preguiçosa do rotasCrm.js existe (o React.lazy só a pede ao abrir)', () => {
    const paginas = [...lerFonte(ROTAS_CRM).matchAll(/const (\w+) = lazy\(\(\) => import\('\.\/(\w+)'\)\);/g)];
    expect(paginas.map(([, nome]) => nome)).toEqual(['CrmMapa', 'CrmLojaNova', 'CrmLoja', 'CrmDefinicoes', 'CrmRotas', 'CrmRota']);
    for (const [, nome, ficheiro] of paginas) {
      expect(ficheiro).toBe(nome);
      expect(fs.existsSync(path.join(SRC, 'pages', 'crm', `${ficheiro}.js`))).toBe(true);
    }
  });

  test.each(DESENHAM_O_MENU)('o %s dá um ícone a cada item, e às Rotas o Route do lucide', (relativo) => {
    const texto = lerFonte(relativo);
    const icones = iconesDe(texto);
    expect(icones).not.toBeNull();
    expect(icones.map(([chave]) => chave)).toEqual(ITENS_MENU_CRM.map((item) => item.chave));
    expect(Object.fromEntries(icones).rotas).toBe('IconeRota');
    // Nunca `Route` solto: confundia-se com o `Route` do React Router.
    expect(texto).toMatch(/^\s*Route as IconeRota,/m);
    expect(texto).not.toMatch(/^\s*Route,\s*$/m);
  });

  test('o CrmLayout e o seccaoCrm usam os mesmos ícones', () => {
    const [layout, seccao] = DESENHAM_O_MENU.map((relativo) => iconesDe(lerFonte(relativo)));
    expect(seccao).toEqual(layout);
  });
});
