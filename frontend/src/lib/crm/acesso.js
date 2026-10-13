// Quem vê o CRM, e onde. Funções puras: os layouts (`AdminLayout`,
// `EmployeeLayout`, `CrmLayout`) e a guarda das rotas (`GuardaCrm`) só as
// chamam, com o `eu` de `useEstadoCrm()` (`GET /api/crm/eu`, já normalizado
// pelo `eu.js`).
//
// **A interface só esconde; é o servidor que protege** (`crm/auth.py`, com o
// teste `test_protecao_rotas.py`). Por isso aqui fecha-se na dúvida: um `eu`
// estragado, uma opção em falta ou uma regra que rebenta escondem o CRM — e
// nunca deitam abaixo o menu do resto do portal.

// As duas casas das mesmas páginas: a área própria e a secção da gestão.
export const BASE_CRM = '/crm';
export const BASE_CRM_ADMIN = '/admin/crm';

// Quem entra nas páginas de escritório do CRM (`ESCRITORIO =
// exigir_perfil("admin", "utilizador")` no backend). O `motorista` não entra
// na F1–F2: o terreno chega na F4, pela "Rota do dia".
export const PERFIS_ESCRITORIO = Object.freeze(['admin', 'utilizador']);

// O menu do CRM, pela ordem em que aparece. `caminho` é relativo à casa
// (`BASE_CRM` ou `BASE_CRM_ADMIN`) e bate com as rotas filhas de `rotasCrm.js`.
export const ITENS_MENU_CRM = Object.freeze([
  Object.freeze({ chave: 'mapa', rotulo: 'Mapa', caminho: 'mapa', soAdmin: false }),
  Object.freeze({ chave: 'loja-nova', rotulo: 'Nova loja', caminho: 'lojas/nova', soAdmin: false }),
  Object.freeze({ chave: 'definicoes', rotulo: 'Definições', caminho: 'definicoes', soAdmin: true }),
]);

const eObjetoSimples = (x) => x !== null && typeof x === 'object' && !Array.isArray(x);

// O perfil que o `eu` declara, se for membro (ainda por comparar com uma lista
// exata); null para quem não é membro ou para um `eu` estragado.
const perfilDeMembro = (eu) => (eObjetoSimples(eu) && eu.membro === true ? eu.perfil : null);

const eDeEscritorio = (eu) => PERFIS_ESCRITORIO.includes(perfilDeMembro(eu));

/**
 * Pode abrir a área do CRM (`/crm/*` e `/admin/crm/*`): membro `admin` ou
 * `utilizador`, no browser. Nas apps nativas (`Capacitor.isNativePlatform()`)
 * o CRM fica escondido na v1 — e só `nativo: false` conta como browser, para
 * que esquecer a opção nunca abra o CRM na app por engano.
 */
export function podeAbrirAreaCrm(eu, opcoes) {
  if (!eObjetoSimples(opcoes) || opcoes.nativo !== false) return false;
  return eDeEscritorio(eu);
}

/** Admin do CRM (o admin master incluído): vê as Definições. */
export function eAdminCrm(eu) {
  return perfilDeMembro(eu) === 'admin';
}

// O aviso da guarda quando o `GET /api/crm/eu` não respondeu.
export const MENSAGEM_ACESSO_FALHOU =
  'Não foi possível confirmar o acesso ao CRM. Verifique a ligação e tente de novo.';

/**
 * O que a guarda da área do CRM (`GuardaCrm`) faz com o estado de
 * `useEstadoCrm()` (`{carregando, eu, falhou}`): `'esperar'` (indicador),
 * `'entrar'`, `'falhou'` (aviso com "Tentar de novo") ou `'recambiar'` (para
 * o início do portal).
 *
 * **Uma falha não é um "não"** (desenho §4: se o `/eu` falhar, o CRM fica
 * escondido; só quem não é membro é recambiado): com o pedido sem resposta, um
 * membro no browser fica onde está, com o aviso, em vez de ser deitado fora do
 * CRM (revisão da F0/F1). Na app nativa o CRM está sempre escondido, por isso
 * aí — ou sem dizer onde corre — recambia.
 */
export function decisaoGuardaCrm(estado, opcoes) {
  if (!eObjetoSimples(estado)) return 'recambiar';
  if (estado.carregando === true) return 'esperar';
  if (podeAbrirAreaCrm(estado.eu, opcoes)) return 'entrar';
  if (estado.falhou === true && eObjetoSimples(opcoes) && opcoes.nativo === false) return 'falhou';
  return 'recambiar';
}

/**
 * O mesmo para as páginas só do admin do CRM (`SoAdminCrm`, as Definições):
 * `'recambiar'` aqui é voltar ao mapa da mesma casa. Fica sempre dentro da
 * `GuardaCrm`, que já tratou da app nativa.
 */
export function decisaoSoAdminCrm(estado) {
  if (!eObjetoSimples(estado)) return 'recambiar';
  if (estado.carregando === true) return 'esperar';
  if (eAdminCrm(estado.eu)) return 'entrar';
  if (estado.falhou === true) return 'falhou';
  return 'recambiar';
}

/**
 * Se uma secção do menu de gestão aparece. As secções que já existem não têm
 * `visivel` e aparecem sempre; com uma função, só o resultado `=== true`
 * mostra. Uma regra que rebenta esconde a secção sem lançar: o menu do portal
 * inteiro desenha-se com isto.
 */
export function seccaoVisivel(seccao, ctx) {
  if (!eObjetoSimples(seccao)) return false;
  const { visivel } = seccao;
  if (visivel === undefined) return true;
  if (typeof visivel !== 'function') return visivel === true;
  try {
    return visivel(ctx) === true;
  } catch {
    return false;
  }
}

// O React Router compara os caminhos sem distinguir maiúsculas e aceita
// barras no fim: `/admin/CRM/mapa/` abre a mesma página que `/admin/crm/mapa`.
// As regras seguem-no, para o menu acender o que o router mostra.
const ROTA_CRM_NO_ADMIN = /^\/admin\/crm(?:\/|$)/i;
const ECRA_CHEIO = /^(?:\/admin)?\/crm(?:\/mapa)?\/*$/i;

/**
 * O caminho é da secção CRM da gestão (`/admin/crm` e o que está por baixo).
 * O `match` do RH no `AdminLayout` exclui-o: o RH é o apanha-tudo do `/admin`.
 */
export function rotaDoCrmNoAdmin(caminho) {
  return typeof caminho === 'string' && ROTA_CRM_NO_ADMIN.test(caminho);
}

/** A casa do CRM em que o caminho está: `/admin/crm` na gestão, senão `/crm`. */
export function baseCrm(caminho) {
  return rotaDoCrmNoAdmin(caminho) ? BASE_CRM_ADMIN : BASE_CRM;
}

/**
 * O mapa ocupa a área toda (sem margens): `/crm`, `/crm/mapa`, `/admin/crm` e
 * `/admin/crm/mapa`. Decide-se pela rota, não pela secção: a Nova loja e as
 * Definições ficam com as margens de sempre.
 */
export function ecraCheioDoCrm(caminho) {
  return typeof caminho === 'string' && ECRA_CHEIO.test(caminho);
}

/**
 * O menu do CRM para este `eu`: Mapa e Nova loja para os perfis de escritório,
 * Definições só para o admin; nada para o motorista ou quem não é membro.
 * `base` é `BASE_CRM` (por omissão) ou `BASE_CRM_ADMIN`; outra coisa dá a área
 * própria, nunca um caminho inventado. Cada chamada devolve objetos novos.
 */
export function itensMenuCrm(eu, base = BASE_CRM) {
  if (!eDeEscritorio(eu)) return [];
  const casa = base === BASE_CRM_ADMIN ? BASE_CRM_ADMIN : BASE_CRM;
  const admin = eAdminCrm(eu);
  return ITENS_MENU_CRM
    .filter((item) => !item.soAdmin || admin)
    .map(({ chave, rotulo, caminho }) => ({ chave, rotulo, caminho: `${casa}/${caminho}` }));
}
