/**
 * DEFINIÇÕES › MEMBROS — as regras do separador "Membros", sem DOM.
 *
 * Porta de public/assets/js/componentes/definicoes-utilizadores.js do CRM
 * autónomo (etiqueta `referencia-standalone`), com os casos de
 * tests/js/definicoes-utilizadores.test.js e tests/js/definicoes.test.js que
 * valem para os membros (correção "T2.26 / T2.27 / T2.29 / T2.30 (componentes
 * Sem Jest)"): o ecrã como a ficha da T2.28 — o que o autónomo escrevia no DOM
 * é uma `vista` congelada, entregue ao `aoMudarVista`, e o
 * `pages/crm/DefinicoesMembros.js` só a desenha.
 *
 * Adaptações ao portal (plano T2.29; desenho §3.1):
 *   - no autónomo criavam-se contas (nome, email, palavra-passe temporária);
 *     aqui escolhe-se uma conta do portal que ainda não é membro
 *     (`GET /membros/candidatos`) e o perfil — sem palavras-passe nem
 *     "Ativar/Desativar" (a conta é do portal);
 *   - "Tornar administrador/utilizador" passa a um `Select` com os três perfis
 *     (`PERFIS`, Utilizador por omissão), que grava logo;
 *   - "Desativar" passa a "Retirar", com a mesma confirmação (Cancelar primeiro);
 *   - o admin principal (admin master) vem primeiro, fixo e sem ações; a conta
 *     da própria sessão também não tem ações (como no autónomo); um membro com
 *     a conta apagada mostra "(conta apagada)";
 *   - as mensagens do servidor (409, 404, sem rede) são toasts
 *     (`aoAvisarErro`) e não um parágrafo na linha; os 422 do "Adicionar" ficam
 *     junto aos campos; uma lista que ficou desatualizada (409 `ja_membro`/
 *     `admin_master`, 404) volta a pedir-se;
 *   - ids uuid em texto (o admin principal tem `id: null`).
 */
import { ErroCrm, MENSAGEM_ERRO_INESPERADO, MENSAGEM_SEM_REDE } from './api';
import { PERFIS } from './perfis';
import { criarEstadoRede } from './rede';
import {
  COLUNAS_MEMBROS,
  DESCRICOES_PERFIS,
  PERFIL_INICIAL,
  RESPOSTA_RETIRAR,
  TEXTO_A_ADICIONAR,
  TEXTO_A_CARREGAR_MEMBROS,
  TEXTO_ADICIONAR,
  TEXTO_ADICIONAR_TITULO,
  TEXTO_ADMIN_PRINCIPAL,
  TEXTO_CONTA,
  TEXTO_CONTA_APAGADA,
  TEXTO_DESCRICAO_MEMBROS,
  TEXTO_ESCOLHER_CONTA,
  TEXTO_MEMBRO_ADICIONADO,
  TEXTO_MEMBRO_RETIRADO,
  TEXTO_NOTA_ADMIN_PRINCIPAL,
  TEXTO_NOTA_PROPRIA,
  TEXTO_PERFIL,
  TEXTO_PERFIL_DESCONHECIDO,
  TEXTO_PERFIL_GUARDADO,
  TEXTO_RETIRAR,
  TEXTO_RETIRAR_AVISO,
  TEXTO_SEM_CANDIDATOS,
  TEXTO_SEM_VALOR,
  TITULO_MEMBROS,
  candidatoValido,
  criarMembros,
  membroValido,
  opcoesConta,
  ordenarCandidatos,
  ordenarMembros,
  perguntaRetirar,
  rotuloTipoConta,
} from './membros';

const ID_ANA = '0b6f3c1e-1111-4222-8333-444455556666';
const ID_RUI = '9d8c7b6a-5f4e-4d3c-a2b1-c0d9e8f7a6b5';
const ID_ZE = '3f1c2d4e-5a6b-4c7d-8e9f-0a1b2c3d4e5f';
const ID_APAGADO = '7a8b9c0d-1e2f-4a3b-9c4d-5e6f7a8b9c0d';
const ID_BRUNO_MEMBRO = 'c0ffee00-0000-4000-a000-000000000099';

const ADMIN_PRINCIPAL = Object.freeze({
  id: null, user_id: 'u-bruce', nome: 'Bruce Silva', email: 'geral@exemplo.pt', tipo_conta: 'gestor',
  perfil: 'admin', admin_master: true, conta_existe: true, criado_em: null,
});
const ANA = Object.freeze({
  id: ID_ANA, user_id: 'u-ana', nome: 'Ana Costa', email: 'ana@exemplo.pt', tipo_conta: 'gestor',
  perfil: 'admin', admin_master: false, conta_existe: true, criado_em: '2026-10-01T09:00:00Z',
});
const RUI = Object.freeze({
  id: ID_RUI, user_id: 'u-rui', nome: 'Rui Silva', email: 'rui@exemplo.pt', tipo_conta: 'colaborador',
  perfil: 'utilizador', admin_master: false, conta_existe: true, criado_em: '2026-10-02T09:00:00Z',
});
const ZE = Object.freeze({
  id: ID_ZE, user_id: 'u-ze', nome: 'Zé Lopes', email: 'ze@exemplo.pt', tipo_conta: 'colaborador',
  perfil: 'motorista', admin_master: false, conta_existe: true, criado_em: '2026-10-03T09:00:00Z',
});
const APAGADO = Object.freeze({
  id: ID_APAGADO, user_id: 'u-velho', nome: null, email: null, tipo_conta: null,
  perfil: 'utilizador', admin_master: false, conta_existe: false, criado_em: '2026-09-01T09:00:00Z',
});
const MEMBROS = [ADMIN_PRINCIPAL, ANA, RUI, ZE, APAGADO];

const BRUNO = Object.freeze({ id: 'u-bruno', nome: 'Bruno Dias', email: 'bruno@exemplo.pt', tipo_conta: 'gestor' });
const CARLA = Object.freeze({ id: 'u-carla', nome: 'Carla Reis', email: 'carla@exemplo.pt', tipo_conta: 'colaborador' });
const CANDIDATOS = [BRUNO, CARLA];

// Uma cópia funda, como a que o servidor manda (o jsdom do Jest 27 não tem `structuredClone`).
const copia = (valor) => JSON.parse(JSON.stringify(valor));
const BRUNO_MEMBRO = Object.freeze({
  id: ID_BRUNO_MEMBRO, user_id: 'u-bruno', nome: 'Bruno Dias', email: 'bruno@exemplo.pt', tipo_conta: 'gestor',
  perfil: 'utilizador', admin_master: false, conta_existe: true, criado_em: '2026-10-10T09:00:00Z',
});

// --- Textos --------------------------------------------------------------------------------------

test('os textos exatos do separador', () => {
  expect(TITULO_MEMBROS).toBe('Membros');
  expect(TEXTO_DESCRICAO_MEMBROS).toBe('Quem entra no CRM e com que perfil.');
  expect(TEXTO_A_CARREGAR_MEMBROS).toBe('A carregar os membros…');
  expect(COLUNAS_MEMBROS).toEqual(['Nome', 'Email', 'Tipo de conta', 'Perfil', 'Ações']);
  expect(Object.isFrozen(COLUNAS_MEMBROS)).toBe(true);
  expect(TEXTO_CONTA_APAGADA).toBe('(conta apagada)');
  expect(TEXTO_ADMIN_PRINCIPAL).toBe('Administrador principal');
  expect(TEXTO_NOTA_ADMIN_PRINCIPAL).toBe('É sempre administrador do CRM.');
  expect(TEXTO_NOTA_PROPRIA).toBe('A sua conta: só outro administrador a pode mudar.');
  expect(TEXTO_PERFIL_DESCONHECIDO).toBe('Perfil desconhecido');
  expect(TEXTO_SEM_VALOR).toBe('—');
  expect(TEXTO_ADICIONAR_TITULO).toBe('Adicionar membro');
  expect(TEXTO_CONTA).toBe('Conta do portal');
  expect(TEXTO_PERFIL).toBe('Perfil');
  expect(TEXTO_ESCOLHER_CONTA).toBe('Escolha uma conta');
  expect(TEXTO_SEM_CANDIDATOS).toBe('Todas as contas do portal já são membros do CRM.');
  expect([TEXTO_ADICIONAR, TEXTO_A_ADICIONAR, TEXTO_RETIRAR]).toEqual(['Adicionar', 'A adicionar…', 'Retirar']);
  expect([TEXTO_MEMBRO_ADICIONADO, TEXTO_PERFIL_GUARDADO, TEXTO_MEMBRO_RETIRADO]).toEqual([
    'Membro adicionado', 'Perfil guardado', 'Membro retirado',
  ]);
  expect(TEXTO_RETIRAR_AVISO).toBe('Deixa de ter acesso ao CRM. A conta do portal fica como está.');
});

test('PERFIL_INICIAL é o primeiro dos PERFIS (Utilizador), e cada perfil tem a sua descrição', () => {
  expect(PERFIL_INICIAL).toBe(PERFIS[0].valor);
  expect(PERFIL_INICIAL).toBe('utilizador');
  expect(DESCRICOES_PERFIS).toEqual({
    utilizador: 'Lojas e mapa.',
    admin: 'Tudo, incluindo estas definições.',
    motorista: 'A rota do dia, que ainda não existe — por agora não vê o CRM.',
  });
  expect(Object.keys(DESCRICOES_PERFIS).sort()).toEqual(PERFIS.map((p) => p.valor).sort());
  expect(Object.isFrozen(DESCRICOES_PERFIS)).toBe(true);
});

// --- Funções puras -------------------------------------------------------------------------------

test('ordenarMembros: o admin principal primeiro, as contas apagadas no fim, e por nome como o servidor', () => {
  const lista = [
    { ...APAGADO, id: ID_ZE },
    { ...RUI, id: ID_RUI, nome: 'Zé' },
    { ...RUI, id: ID_ANA, nome: 'élia' },
    ADMIN_PRINCIPAL,
    { ...RUI, id: ID_APAGADO, nome: 'Bruno' },
    { ...RUI, id: ID_BRUNO_MEMBRO, nome: 'bruno' },
    { ...APAGADO, id: ID_ANA },
  ];
  const copiaDaLista = [...lista];
  expect(ordenarMembros(lista).map((m) => [m.id, m.nome])).toEqual([
    [null, 'Bruce Silva'],
    [ID_APAGADO, 'Bruno'],
    [ID_BRUNO_MEMBRO, 'bruno'],
    [ID_ANA, 'élia'],
    [ID_RUI, 'Zé'],
    [ID_ANA, null],
    [ID_ZE, null],
  ]);
  expect(lista).toEqual(copiaDaLista);
});

test('ordenarCandidatos: por nome, sem distinguir maiúsculas nem acentos, e depois pelo id', () => {
  const lista = [{ id: 'u3', nome: 'Zé' }, { id: 'u1', nome: 'élia' }, { id: 'u4', nome: 'bruno' }, { id: 'u2', nome: 'Bruno' }, { id: 'u0', nome: null }];
  expect(ordenarCandidatos(lista).map((c) => c.id)).toEqual(['u0', 'u2', 'u4', 'u1', 'u3']);
  expect(lista[0].id).toBe('u3');
});

test('membroValido: as linhas do GET /membros, com o admin principal (id null) e um perfil desconhecido', () => {
  for (const m of MEMBROS) expect(membroValido(m)).toBe(true);
  expect(membroValido({ ...RUI, perfil: null })).toBe(true);
  expect(membroValido({ ...RUI, perfil: 'gestor_de_frota' })).toBe(true);
  expect(membroValido({ ...ADMIN_PRINCIPAL, user_id: null, nome: null, email: null, conta_existe: false })).toBe(true);
  for (const mau of [
    null, undefined, 'x', [RUI], {},
    { ...RUI, id: 7 }, { ...RUI, id: '' }, { ...RUI, id: 'membro-1' }, { ...RUI, id: null },
    { ...ADMIN_PRINCIPAL, id: ID_ANA }, { ...RUI, admin_master: 'false' }, { ...RUI, admin_master: undefined },
    { ...RUI, conta_existe: 1 }, { ...RUI, nome: 7 }, { ...RUI, email: {} }, { ...RUI, user_id: 3 }, { ...RUI, perfil: 1 },
  ]) {
    expect(membroValido(mau)).toBe(false);
  }
});

test('candidatoValido: um id em texto (não vazio), nome e email em texto ou null', () => {
  for (const c of CANDIDATOS) expect(candidatoValido(c)).toBe(true);
  expect(candidatoValido({ id: 'u-x', nome: null, email: null, tipo_conta: null })).toBe(true);
  // Sem as chaves do nome e do email (uma conta do portal sem eles) também conta.
  expect(candidatoValido({ id: 'u-x' })).toBe(true);
  for (const mau of [null, 'u-x', [], { id: '' }, { id: 5, nome: 'X' }, { nome: 'X' }, { id: 'u', nome: 1 }, { id: 'u', email: [] }]) {
    expect(candidatoValido(mau)).toBe(false);
  }
});

test('rotuloTipoConta: Gestor, Colaborador ou o traço', () => {
  expect(rotuloTipoConta('gestor')).toBe('Gestor');
  expect(rotuloTipoConta('colaborador')).toBe('Colaborador');
  for (const outro of [null, undefined, '', 'admin', 'constructor', '__proto__', 7]) {
    expect(rotuloTipoConta(outro)).toBe('—');
  }
});

test('perguntaRetirar: a pergunta com o nome, o aviso, e Cancelar primeiro (a escolha que não retira)', () => {
  const pergunta = perguntaRetirar(RUI);
  expect(pergunta).toEqual({
    pergunta: 'Retirar Rui Silva do CRM?',
    aviso: 'Deixa de ter acesso ao CRM. A conta do portal fica como está.',
    botoes: [{ texto: 'Cancelar', valor: null, variante: 'normal' }, { texto: 'Sim, retirar', valor: RESPOSTA_RETIRAR, variante: 'perigo' }],
  });
  expect(RESPOSTA_RETIRAR).toBe('retirar');
  expect(Object.isFrozen(pergunta)).toBe(true);
  expect(Object.isFrozen(pergunta.botoes)).toBe(true);
  expect(pergunta.botoes.every(Object.isFrozen)).toBe(true);
  // Sem nome, o email; com a conta apagada, "este membro".
  expect(perguntaRetirar({ ...RUI, nome: null }).pergunta).toBe('Retirar rui@exemplo.pt do CRM?');
  expect(perguntaRetirar(APAGADO).pergunta).toBe('Retirar este membro do CRM?');
  expect(perguntaRetirar({ ...RUI, nome: '<b>x</b>' }).pergunta).toBe('Retirar <b>x</b> do CRM?');
});

test('opcoesConta: o nome (ou o email) e o detalhe com o email e o tipo de conta', () => {
  const opcoes = opcoesConta([BRUNO, { id: 'u-x', nome: null, email: 'x@exemplo.pt', tipo_conta: 'colaborador' }, { id: 'u-y', nome: null, email: null, tipo_conta: null }]);
  expect(opcoes).toEqual([
    { valor: 'u-bruno', nome: 'Bruno Dias', detalhe: 'bruno@exemplo.pt · Gestor' },
    { valor: 'u-x', nome: 'x@exemplo.pt', detalhe: 'Colaborador' },
    { valor: 'u-y', nome: 'u-y', detalhe: '' },
  ]);
  expect(Object.isFrozen(opcoes)).toBe(true);
  expect(opcoes.every(Object.isFrozen)).toBe(true);
  expect(opcoesConta(null)).toEqual([]);
});

// --- O ecrã --------------------------------------------------------------------------------------

// Cada pedido fica pendente até o teste lhe responder (ou o fazer falhar).
function apiFalsa() {
  const pedidos = [];
  const pedir = (nome) => (...argumentos) => new Promise((resolver, rejeitar) => {
    pedidos.push({ nome, argumentos, resolver, rejeitar });
  });
  return {
    pedidos,
    listarMembros: pedir('listarMembros'),
    listarCandidatos: pedir('listarCandidatos'),
    adicionarMembro: pedir('adicionarMembro'),
    mudarPerfilMembro: pedir('mudarPerfilMembro'),
    retirarMembro: pedir('retirarMembro'),
  };
}

const assentar = () => new Promise((r) => {
  setTimeout(r, 0);
});

// Monta o ecrã como a página (DefinicoesMembros): cria e inicia (pede as duas listas e ouve a rede). A sessão
// é a da Ana (admin do CRM, não é o admin principal).
function montar(opcoes = {}) {
  const { iniciar = true, online = true } = opcoes;
  const euId = 'euId' in opcoes ? opcoes.euId : 'u-ana';
  const api = apiFalsa();
  const janela = new EventTarget();
  const navegador = { onLine: online };
  const avisos = [];
  const erros = [];
  const focos = [];
  const vistas = [];
  const ecra = criarMembros({
    api,
    rede: criarEstadoRede(janela, navegador),
    euId,
    aoMudarVista: (vista) => vistas.push(vista),
    aoAvisar: (texto) => avisos.push(texto),
    aoAvisarErro: (texto) => erros.push(texto),
    aoFocar: (alvo) => focos.push(alvo),
  });
  if (iniciar) ecra.iniciar();
  const mudarRede = (ligado) => {
    navegador.onLine = ligado;
    janela.dispatchEvent(new Event(ligado ? 'online' : 'offline'));
  };
  return { api, ecra, avisos, erros, focos, vistas, mudarRede, vista: () => ecra.vista };
}

const pedidos = (m, nome) => m.api.pedidos.filter((p) => p.nome === nome);
const ultimo = (m, nome) => pedidos(m, nome).at(-1);
const resumo = (m) => m.api.pedidos.map((p) => p.nome);

async function responder(m, nome, dados) {
  ultimo(m, nome).resolver(dados);
  await assentar();
}

async function falhar(m, nome, erro) {
  ultimo(m, nome).rejeitar(erro);
  await assentar();
}

async function carregada(opcoes = {}, membros = MEMBROS, candidatos = CANDIDATOS) {
  const m = montar(opcoes);
  await responder(m, 'listarMembros', copia(membros));
  await responder(m, 'listarCandidatos', copia(candidatos));
  return m;
}

const linhaDe = (m, id) => m.vista().linhas.find((l) => l.id === id);
const erroSemRede = () => new ErroCrm({ codigo: 'sem_rede', mensagem: MENSAGEM_SEM_REDE });
const erro409 = (codigo, mensagem) => new ErroCrm({ codigo, mensagem, estado: 409 });
const erro404 = () => new ErroCrm({ codigo: 'nao_encontrado', mensagem: 'Membro não encontrado.', estado: 404 });
const erroValidacao = (campos) => new ErroCrm({ codigo: 'validacao', mensagem: 'Verifique os campos assinalados.', estado: 422, campos });

// --- Carregar ------------------------------------------------------------------------------------

test('criar não pede nada; iniciar pede os membros e os candidatos, um pedido de cada', () => {
  const m = montar({ iniciar: false });
  expect(m.api.pedidos).toEqual([]);
  expect(m.vista().estado).toBe('a_carregar');
  m.ecra.iniciar();
  m.ecra.iniciar();
  expect(resumo(m)).toEqual(['listarMembros', 'listarCandidatos']);
  expect(m.vista().estado).toBe('a_carregar');
  expect(m.vista().linhas).toEqual([]);
  expect(Object.isFrozen(m.vista())).toBe(true);
});

test('com as duas listas: a tabela com nome, email, tipo de conta e perfil, pela ordem', async () => {
  const m = await carregada();
  const vista = m.vista();
  expect(vista.estado).toBe('pronto');
  expect(vista.falha).toBeNull();
  expect(vista.linhas.map((l) => [l.nome, l.email, l.tipoConta, l.rotuloPerfil])).toEqual([
    ['Bruce Silva', 'geral@exemplo.pt', 'Gestor', 'Administrador'],
    ['Ana Costa', 'ana@exemplo.pt', 'Gestor', 'Administrador'],
    ['Rui Silva', 'rui@exemplo.pt', 'Colaborador', 'Utilizador'],
    ['Zé Lopes', 'ze@exemplo.pt', 'Colaborador', 'Motorista'],
    ['(conta apagada)', '—', '—', 'Utilizador'],
  ]);
  expect(vista.linhas.map((l) => l.perfil)).toEqual(['admin', 'admin', 'utilizador', 'motorista', 'utilizador']);
  expect(vista.linhas.map((l) => l.chave)).toEqual(['admin-principal', ID_ANA, ID_RUI, ID_ZE, ID_APAGADO]);
  expect(vista.linhas.map((l) => l.contaApagada)).toEqual([false, false, false, false, true]);
  expect(Object.isFrozen(vista.linhas)).toBe(true);
  expect(vista.linhas.every(Object.isFrozen)).toBe(true);
});

test('o servidor manda por ordem, mas a lista volta a ordenar-se; linhas estragadas ficam de fora', async () => {
  const m = await carregada({}, [ZE, { ...RUI, id: 7 }, APAGADO, ANA, null, ADMIN_PRINCIPAL, RUI], [CARLA, BRUNO]);
  expect(m.vista().linhas.map((l) => l.id)).toEqual([null, ID_ANA, ID_RUI, ID_ZE, ID_APAGADO]);
  expect(m.vista().novo.opcoesConta.map((o) => o.valor)).toEqual(['u-bruno', 'u-carla']);
});

test('o admin principal é fixo, e a própria conta também não tem ações; as outras têm', async () => {
  const m = await carregada();
  const [principal, ana, rui, ze, apagado] = m.vista().linhas;
  expect(principal).toMatchObject({ adminPrincipal: true, propria: false, acoes: false, nota: 'É sempre administrador do CRM.' });
  expect(ana).toMatchObject({ adminPrincipal: false, propria: true, acoes: false, nota: 'A sua conta: só outro administrador a pode mudar.' });
  for (const linha of [rui, ze, apagado]) {
    expect(linha).toMatchObject({ adminPrincipal: false, propria: false, acoes: true, nota: null, ocupada: false });
  }
});

test('o admin principal na sua sessão: a linha dele continua a do admin principal', async () => {
  const m = await carregada({ euId: 'u-bruce' });
  expect(m.vista().linhas[0]).toMatchObject({ adminPrincipal: true, propria: false, nota: TEXTO_NOTA_ADMIN_PRINCIPAL });
  expect(linhaDe(m, ID_ANA)).toMatchObject({ propria: false, acoes: true });
});

test('sem a sessão (euId em falta ou vazio) nenhuma linha é a própria', async () => {
  for (const euId of [null, '', undefined]) {
    const m = await carregada({ euId });
    expect(m.vista().linhas.filter((l) => l.propria)).toEqual([]);
  }
});

test('os nomes acessíveis das ações dizem a ação e a pessoa em pt-PT', async () => {
  const m = await carregada();
  expect(linhaDe(m, ID_RUI)).toMatchObject({ rotuloPerfilAcessivel: 'Perfil de Rui Silva', rotuloRetirarAcessivel: 'Retirar Rui Silva do CRM' });
  expect(linhaDe(m, ID_APAGADO)).toMatchObject({
    rotuloPerfilAcessivel: 'Perfil de este membro', rotuloRetirarAcessivel: 'Retirar este membro do CRM',
  });
});

test('os dados ficam como texto: <b>x</b> chega tal e qual à vista (o React escreve-o como texto)', async () => {
  const m = await carregada({}, [ADMIN_PRINCIPAL, { ...RUI, nome: '<b>x</b>', email: '<i>y</i>@exemplo.pt' }]);
  expect(linhaDe(m, ID_RUI)).toMatchObject({ nome: '<b>x</b>', email: '<i>y</i>@exemplo.pt', rotuloRetirarAcessivel: 'Retirar <b>x</b> do CRM' });
});

test('um perfil desconhecido (null do servidor) mostra "Perfil desconhecido" e pode corrigir-se', async () => {
  const m = await carregada({}, [ADMIN_PRINCIPAL, { ...RUI, perfil: null }]);
  expect(linhaDe(m, ID_RUI)).toMatchObject({ perfil: null, rotuloPerfil: 'Perfil desconhecido', acoes: true });
  m.ecra.mudarPerfil(ID_RUI, 'utilizador');
  await assentar();
  expect(ultimo(m, 'mudarPerfilMembro').argumentos).toEqual([ID_RUI, 'utilizador']);
});

test('o formulário de adicionar: conta por escolher, Utilizador por omissão, as contas que podem entrar', async () => {
  const m = await carregada();
  const { novo } = m.vista();
  expect(novo.userId).toBe('');
  expect(novo.perfil).toBe('utilizador');
  expect(novo.descricaoPerfil).toBe('Lojas e mapa.');
  expect(novo.erros).toEqual({});
  expect(novo.opcoesConta.map((o) => o.valor)).toEqual(['u-bruno', 'u-carla']);
  expect(novo.semCandidatos).toBe(false);
  expect(novo.botao).toEqual({ ativo: true, texto: 'Adicionar' });
  expect(Object.isFrozen(novo)).toBe(true);
  m.ecra.escolherPerfil('motorista');
  expect(m.vista().novo.descricaoPerfil).toBe('A rota do dia, que ainda não existe — por agora não vê o CRM.');
});

test('sem contas por adicionar: a frase, e o botão desativado', async () => {
  const m = await carregada({}, MEMBROS, []);
  expect(m.vista().novo.semCandidatos).toBe(true);
  expect(m.vista().novo.botao).toEqual({ ativo: false, texto: 'Adicionar' });
  m.ecra.adicionar();
  expect(pedidos(m, 'adicionarMembro')).toEqual([]);
});

test('respostas que não são listas contam como listas vazias; candidatos estragados ficam de fora', async () => {
  const m = await carregada({}, { erro: 'x' }, [BRUNO, { id: '' }, 7, CARLA]);
  expect(m.vista().estado).toBe('pronto');
  expect(m.vista().linhas).toEqual([]);
  expect(m.vista().novo.opcoesConta.map((o) => o.valor)).toEqual(['u-bruno', 'u-carla']);
});

test('falha ao carregar os membros: a mensagem e "Tentar novamente" (um toque, um pedido, só do que falhou)', async () => {
  const m = montar();
  await falhar(m, 'listarMembros', erroSemRede());
  expect(m.vista().estado).toBe('falha');
  expect(m.vista().falha).toEqual({ mensagem: MENSAGEM_SEM_REDE, aTentar: true });
  await responder(m, 'listarCandidatos', copia(CANDIDATOS));
  expect(m.vista().falha).toEqual({ mensagem: MENSAGEM_SEM_REDE, aTentar: false });
  m.ecra.tentarDeNovo();
  m.ecra.tentarDeNovo();
  expect(pedidos(m, 'listarMembros')).toHaveLength(2);
  expect(pedidos(m, 'listarCandidatos')).toHaveLength(1);
  expect(m.vista().falha.aTentar).toBe(true);
  await responder(m, 'listarMembros', copia(MEMBROS));
  expect(m.vista().estado).toBe('pronto');
  expect(m.vista().falha).toBeNull();
  m.ecra.tentarDeNovo();
  expect(m.api.pedidos).toHaveLength(3);
});

test('falha ao carregar os candidatos: só eles se pedem outra vez; a mensagem do servidor', async () => {
  const m = montar();
  await responder(m, 'listarMembros', copia(MEMBROS));
  await falhar(m, 'listarCandidatos', new ErroCrm({ codigo: 'sem_permissao', mensagem: 'Sem permissão para esta ação.', estado: 403 }));
  expect(m.vista().estado).toBe('falha');
  expect(m.vista().falha.mensagem).toBe('Sem permissão para esta ação.');
  m.ecra.tentarDeNovo();
  expect(resumo(m)).toEqual(['listarMembros', 'listarCandidatos', 'listarCandidatos']);
  await responder(m, 'listarCandidatos', copia(CANDIDATOS));
  expect(m.vista().estado).toBe('pronto');
});

test('as duas listas falham: a mensagem dos membros primeiro; depois a da que ainda falta', async () => {
  const m = montar();
  await falhar(m, 'listarMembros', erroSemRede());
  await falhar(m, 'listarCandidatos', new ErroCrm({ codigo: 'sem_permissao', mensagem: 'Sem permissão para esta ação.', estado: 403 }));
  expect(m.vista().falha).toEqual({ mensagem: MENSAGEM_SEM_REDE, aTentar: false });
  m.ecra.tentarDeNovo();
  expect(resumo(m)).toEqual(['listarMembros', 'listarCandidatos', 'listarMembros', 'listarCandidatos']);
  await responder(m, 'listarMembros', copia(MEMBROS));
  await falhar(m, 'listarCandidatos', new ErroCrm({ codigo: 'sem_permissao', mensagem: 'Sem permissão para esta ação.', estado: 403 }));
  expect(m.vista().estado).toBe('falha');
  expect(m.vista().falha).toEqual({ mensagem: 'Sem permissão para esta ação.', aTentar: false });
});

test('"Tentar novamente" com a outra lista ainda a caminho não a pede outra vez', async () => {
  const m = montar();
  await falhar(m, 'listarMembros', erroSemRede());
  m.ecra.tentarDeNovo();
  expect(resumo(m)).toEqual(['listarMembros', 'listarCandidatos', 'listarMembros']);
});

test('os candidatos falham e depois chegam, com os membros ainda a caminho: volta a "a carregar", sem a falha antiga', async () => {
  const m = montar();
  await falhar(m, 'listarCandidatos', erroSemRede());
  expect(m.vista()).toMatchObject({ estado: 'falha', falha: { mensagem: MENSAGEM_SEM_REDE, aTentar: true } });
  m.ecra.tentarDeNovo();
  expect(resumo(m)).toEqual(['listarMembros', 'listarCandidatos', 'listarCandidatos']);
  await responder(m, 'listarCandidatos', copia(CANDIDATOS));
  expect(m.vista().estado).toBe('a_carregar');
  expect(m.vista().falha).toBeNull();
  await responder(m, 'listarMembros', copia(MEMBROS));
  expect(m.vista().estado).toBe('pronto');
});

test('iniciar duas vezes ouve a rede uma só vez; ao sair deixa de a ouvir', () => {
  let ouvintes = 0;
  const rede = {
    online: () => true,
    aoMudar: () => {
      ouvintes += 1;
      return () => {
        ouvintes -= 1;
      };
    },
  };
  const ecra = criarMembros({ api: apiFalsa(), rede, euId: 'u-ana' });
  ecra.iniciar();
  ecra.iniciar();
  expect(ouvintes).toBe(1);
  ecra.destruir();
  expect(ouvintes).toBe(0);
});

test('um erro sem mensagem dá a mensagem genérica', async () => {
  const m = montar();
  await falhar(m, 'listarMembros', new Error('x'));
  expect(m.vista().falha.mensagem).toBe(MENSAGEM_ERRO_INESPERADO);
});

test('quando a rede volta, pede outra vez só o que falhou; com tudo carregado não pede nada', async () => {
  const m = montar();
  await falhar(m, 'listarMembros', erroSemRede());
  await responder(m, 'listarCandidatos', copia(CANDIDATOS));
  m.mudarRede(false);
  expect(m.api.pedidos).toHaveLength(2);
  m.mudarRede(true);
  expect(resumo(m)).toEqual(['listarMembros', 'listarCandidatos', 'listarMembros']);
  await responder(m, 'listarMembros', copia(MEMBROS));
  m.mudarRede(false);
  m.mudarRede(true);
  expect(m.api.pedidos).toHaveLength(3);
});

// --- Adicionar -----------------------------------------------------------------------------------

async function adicionar(m, { conta = 'u-bruno', perfil } = {}) {
  m.ecra.escolherConta(conta);
  if (perfil) m.ecra.escolherPerfil(perfil);
  m.ecra.adicionar();
  await assentar();
  return ultimo(m, 'adicionarMembro');
}

test('Adicionar: POST {user_id, perfil}; enquanto espera o botão diz "A adicionar…" (um toque, um pedido)', async () => {
  const m = await carregada();
  const pedido = await adicionar(m, { perfil: 'admin' });
  expect(pedido.argumentos).toEqual([{ user_id: 'u-bruno', perfil: 'admin' }]);
  expect(m.vista().novo.botao).toEqual({ ativo: false, texto: 'A adicionar…' });
  m.ecra.adicionar();
  m.ecra.escolherConta('u-carla');
  m.ecra.escolherPerfil('motorista');
  expect(pedidos(m, 'adicionarMembro')).toHaveLength(1);
  expect(m.vista().novo).toMatchObject({ userId: 'u-bruno', perfil: 'admin' });
});

test('Adicionar com sucesso: a pessoa entra na tabela por ordem e sai das contas; o formulário fica limpo', async () => {
  const m = await carregada();
  await adicionar(m, { perfil: 'motorista' });
  await responder(m, 'adicionarMembro', copia(BRUNO_MEMBRO));
  expect(m.vista().linhas.map((l) => l.nome)).toEqual(['Bruce Silva', 'Ana Costa', 'Bruno Dias', 'Rui Silva', 'Zé Lopes', '(conta apagada)']);
  expect(m.vista().novo.opcoesConta.map((o) => o.valor)).toEqual(['u-carla']);
  expect(m.vista().novo).toMatchObject({ userId: '', perfil: 'utilizador', erros: {}, botao: { ativo: true, texto: 'Adicionar' } });
  expect(m.avisos).toEqual(['Membro adicionado']);
  expect(m.erros).toEqual([]);
  // Sem pedidos a mais: a lista atualiza-se com a resposta.
  expect(resumo(m)).toEqual(['listarMembros', 'listarCandidatos', 'adicionarMembro']);
});

test('Adicionar com dados inválidos (422): o erro do servidor junto a cada campo, e o foco no primeiro', async () => {
  const m = await carregada();
  await adicionar(m, { conta: '' });
  await falhar(m, 'adicionarMembro', erroValidacao({
    user_id: 'Escolha uma conta do portal.', perfil: 'Escolha um perfil: admin, utilizador ou motorista.', outro: 'x',
  }));
  expect(m.vista().novo.erros).toEqual({
    user_id: 'Escolha uma conta do portal.', perfil: 'Escolha um perfil: admin, utilizador ou motorista.',
  });
  expect(m.focos).toEqual(['user_id']);
  expect(m.erros).toEqual([]);
  expect(m.vista().novo.botao).toEqual({ ativo: true, texto: 'Adicionar' });
  // Adicionar outra vez, sem mexer nos campos: os erros saem enquanto o pedido está a caminho.
  m.ecra.adicionar();
  expect(m.vista().novo.erros).toEqual({});
  await falhar(m, 'adicionarMembro', erroValidacao({
    user_id: 'Escolha uma conta do portal.', perfil: 'Escolha um perfil: admin, utilizador ou motorista.',
  }));
  expect(m.focos).toEqual(['user_id', 'user_id']);
  // Escolher a conta tira o erro dela; o do perfil fica até se escolher um perfil.
  m.ecra.escolherConta('u-carla');
  expect(m.vista().novo.erros).toEqual({ perfil: 'Escolha um perfil: admin, utilizador ou motorista.' });
  m.ecra.escolherPerfil('admin');
  expect(m.vista().novo.erros).toEqual({});
  // Só o perfil com erro: o foco vai para o perfil. Um novo pedido limpa os erros anteriores.
  await adicionar(m, { conta: 'u-carla' });
  expect(m.vista().novo.erros).toEqual({});
  await falhar(m, 'adicionarMembro', erroValidacao({ perfil: 'Escolha um perfil: admin, utilizador ou motorista.' }));
  expect(m.focos).toEqual(['user_id', 'user_id', 'perfil']);
});

test('Adicionar com um 422 sem campos conhecidos: a mensagem num aviso de erro', async () => {
  const m = await carregada();
  await adicionar(m);
  await falhar(m, 'adicionarMembro', erroValidacao({ outro: 'x' }));
  expect(m.vista().novo.erros).toEqual({});
  expect(m.erros).toEqual(['Verifique os campos assinalados.']);
  expect(m.focos).toEqual([]);
});

test('Adicionar quem já é membro (409): a mensagem num aviso de erro, e as listas pedem-se outra vez', async () => {
  const m = await carregada();
  await adicionar(m, { perfil: 'admin' });
  await falhar(m, 'adicionarMembro', erro409('ja_membro', 'Esta pessoa já é membro do CRM.'));
  expect(m.erros).toEqual(['Esta pessoa já é membro do CRM.']);
  expect(resumo(m).slice(3)).toEqual(['listarMembros', 'listarCandidatos']);
  await responder(m, 'listarMembros', copia([...MEMBROS, BRUNO_MEMBRO]));
  await responder(m, 'listarCandidatos', copia([CARLA]));
  expect(m.vista().linhas.map((l) => l.id)).toContain(ID_BRUNO_MEMBRO);
  expect(m.vista().novo.opcoesConta.map((o) => o.valor)).toEqual(['u-carla']);
  // A conta escolhida já não está na lista: a escolha sai; o perfil fica.
  expect(m.vista().novo).toMatchObject({ userId: '', perfil: 'admin', botao: { ativo: true, texto: 'Adicionar' } });
});

test('Adicionar o admin principal (409 admin_master) também volta a pedir as listas', async () => {
  const m = await carregada();
  await adicionar(m);
  await falhar(m, 'adicionarMembro', erro409('admin_master', 'O administrador principal já é admin do CRM.'));
  expect(m.erros).toEqual(['O administrador principal já é admin do CRM.']);
  expect(resumo(m).slice(3)).toEqual(['listarMembros', 'listarCandidatos']);
});

test('Adicionar sem rede: o aviso, sem pedir as listas; pode tentar outra vez com a mesma escolha', async () => {
  const m = await carregada();
  await adicionar(m);
  await falhar(m, 'adicionarMembro', erroSemRede());
  expect(m.erros).toEqual([MENSAGEM_SEM_REDE]);
  expect(resumo(m)).toEqual(['listarMembros', 'listarCandidatos', 'adicionarMembro']);
  expect(m.vista().novo).toMatchObject({ userId: 'u-bruno', botao: { ativo: true, texto: 'Adicionar' } });
  m.ecra.adicionar();
  expect(pedidos(m, 'adicionarMembro')).toHaveLength(2);
});

test('Adicionar com uma resposta estragada: o aviso de sucesso, e as listas pedem-se outra vez', async () => {
  const m = await carregada();
  await adicionar(m);
  await responder(m, 'adicionarMembro', { ok: true });
  expect(m.avisos).toEqual(['Membro adicionado']);
  expect(resumo(m).slice(3)).toEqual(['listarMembros', 'listarCandidatos']);
  expect(m.vista().novo.userId).toBe('');
});

test('escolherConta e escolherPerfil: só textos e perfis que existem; antes de as listas chegarem não se adiciona', async () => {
  const m = montar();
  m.ecra.adicionar();
  expect(pedidos(m, 'adicionarMembro')).toEqual([]);
  await responder(m, 'listarMembros', copia(MEMBROS));
  await responder(m, 'listarCandidatos', copia(CANDIDATOS));
  m.ecra.escolherPerfil('Admin');
  m.ecra.escolherPerfil(null);
  m.ecra.escolherConta(7);
  expect(m.vista().novo).toMatchObject({ userId: '', perfil: 'utilizador' });
  const antes = m.vista();
  m.ecra.escolherPerfil('utilizador');
  expect(m.vista()).toBe(antes);
});

// --- Mudar o perfil ------------------------------------------------------------------------------

test('Mudar o perfil: PATCH com o perfil; a linha fica ocupada (um pedido de cada vez) e depois guardada', async () => {
  const m = await carregada();
  m.ecra.mudarPerfil(ID_RUI, 'admin');
  await assentar();
  expect(ultimo(m, 'mudarPerfilMembro').argumentos).toEqual([ID_RUI, 'admin']);
  // Enquanto grava, a linha mostra o perfil escolhido e não aceita outro pedido.
  expect(linhaDe(m, ID_RUI)).toMatchObject({ ocupada: true, perfil: 'admin', rotuloPerfil: 'Administrador' });
  m.ecra.mudarPerfil(ID_RUI, 'motorista');
  m.ecra.pedirRetirar(ID_RUI);
  expect(pedidos(m, 'mudarPerfilMembro')).toHaveLength(1);
  expect(m.vista().pergunta).toBeNull();
  // Outra linha não espera por esta.
  m.ecra.mudarPerfil(ID_ZE, 'utilizador');
  expect(pedidos(m, 'mudarPerfilMembro')).toHaveLength(2);
  pedidos(m, 'mudarPerfilMembro')[0].resolver({ ...copia(RUI), perfil: 'admin' });
  await assentar();
  expect(linhaDe(m, ID_RUI)).toMatchObject({ ocupada: false, perfil: 'admin', rotuloPerfil: 'Administrador' });
  expect(m.avisos).toEqual(['Perfil guardado']);
  expect(linhaDe(m, ID_ZE).ocupada).toBe(true);
});

test('Mudar o perfil não pede nada: o mesmo perfil, um perfil que não existe, o admin principal, a própria conta', async () => {
  const m = await carregada();
  m.ecra.mudarPerfil(ID_RUI, 'utilizador');
  m.ecra.mudarPerfil(ID_RUI, 'Admin');
  m.ecra.mudarPerfil(ID_RUI, '');
  m.ecra.mudarPerfil(null, 'utilizador');
  m.ecra.mudarPerfil(ID_ANA, 'utilizador');
  m.ecra.mudarPerfil('0b6f3c1e-9999-4222-8333-444455556666', 'admin');
  expect(pedidos(m, 'mudarPerfilMembro')).toEqual([]);
});

test('Mudar o perfil e falhar sem rede: o aviso de erro e a linha como estava (sem pedir as listas)', async () => {
  const m = await carregada();
  m.ecra.mudarPerfil(ID_RUI, 'admin');
  await assentar();
  await falhar(m, 'mudarPerfilMembro', erroSemRede());
  expect(m.erros).toEqual([MENSAGEM_SEM_REDE]);
  expect(linhaDe(m, ID_RUI)).toMatchObject({ ocupada: false, perfil: 'utilizador', rotuloPerfil: 'Utilizador' });
  expect(m.avisos).toEqual([]);
  expect(resumo(m)).toEqual(['listarMembros', 'listarCandidatos', 'mudarPerfilMembro']);
});

test('Mudar o perfil de quem já saiu (404) ou do admin principal (409): o aviso e as listas outra vez', async () => {
  const m = await carregada();
  m.ecra.mudarPerfil(ID_RUI, 'admin');
  await assentar();
  await falhar(m, 'mudarPerfilMembro', erro404());
  expect(m.erros).toEqual(['Membro não encontrado.']);
  expect(resumo(m).slice(3)).toEqual(['listarMembros', 'listarCandidatos']);
  await responder(m, 'listarMembros', copia([ADMIN_PRINCIPAL, ANA, ZE]));
  await responder(m, 'listarCandidatos', copia([...CANDIDATOS, { id: 'u-rui', nome: 'Rui Silva', email: 'rui@exemplo.pt', tipo_conta: 'colaborador' }]));
  expect(linhaDe(m, ID_RUI)).toBeUndefined();
  expect(m.vista().novo.opcoesConta.map((o) => o.valor)).toEqual(['u-bruno', 'u-carla', 'u-rui']);

  m.ecra.mudarPerfil(ID_ZE, 'admin');
  await assentar();
  await falhar(m, 'mudarPerfilMembro', erro409('admin_master', 'O administrador principal já é admin do CRM.'));
  expect(m.erros).toEqual(['Membro não encontrado.', 'O administrador principal já é admin do CRM.']);
  expect(pedidos(m, 'listarMembros')).toHaveLength(3);
});

test('Mudar o perfil com uma resposta estragada: fica o perfil pedido, e as listas pedem-se outra vez', async () => {
  const m = await carregada();
  m.ecra.mudarPerfil(ID_RUI, 'motorista');
  await assentar();
  await responder(m, 'mudarPerfilMembro', null);
  expect(linhaDe(m, ID_RUI)).toMatchObject({ ocupada: false, perfil: 'motorista' });
  expect(m.avisos).toEqual(['Perfil guardado']);
  expect(resumo(m).slice(3)).toEqual(['listarMembros', 'listarCandidatos']);
});

// --- Retirar -------------------------------------------------------------------------------------

test('Retirar pede confirmação; Cancelar (ou o Escape) não muda nada', async () => {
  const m = await carregada();
  m.ecra.pedirRetirar(ID_RUI);
  expect(m.vista().pergunta).toEqual(perguntaRetirar(RUI));
  expect(m.vista().pergunta.botoes.map((b) => b.texto)).toEqual(['Cancelar', 'Sim, retirar']);
  m.ecra.responderRetirar(null);
  await assentar();
  expect(m.vista().pergunta).toBeNull();
  expect(pedidos(m, 'retirarMembro')).toEqual([]);
  expect(linhaDe(m, ID_RUI).ocupada).toBe(false);
});

test('Retirar confirmado: DELETE; a pessoa sai da tabela e volta às contas; o aviso e o foco no título', async () => {
  const m = await carregada();
  m.ecra.pedirRetirar(ID_RUI);
  m.ecra.responderRetirar(RESPOSTA_RETIRAR);
  await assentar();
  expect(ultimo(m, 'retirarMembro').argumentos).toEqual([ID_RUI]);
  expect(linhaDe(m, ID_RUI)).toMatchObject({ ocupada: true });
  // Enquanto retira: nem outro pedido nem a mudança de perfil.
  m.ecra.pedirRetirar(ID_RUI);
  m.ecra.mudarPerfil(ID_RUI, 'admin');
  expect(m.vista().pergunta).toBeNull();
  expect(pedidos(m, 'mudarPerfilMembro')).toEqual([]);
  await responder(m, 'retirarMembro', { retirado: true });
  expect(linhaDe(m, ID_RUI)).toBeUndefined();
  expect(m.vista().novo.opcoesConta.map((o) => [o.valor, o.nome, o.detalhe])).toEqual([
    ['u-bruno', 'Bruno Dias', 'bruno@exemplo.pt · Gestor'],
    ['u-carla', 'Carla Reis', 'carla@exemplo.pt · Colaborador'],
    ['u-rui', 'Rui Silva', 'rui@exemplo.pt · Colaborador'],
  ]);
  expect(m.avisos).toEqual(['Membro retirado']);
  expect(m.focos).toEqual(['titulo']);
  expect(resumo(m)).toEqual(['listarMembros', 'listarCandidatos', 'retirarMembro']);
});

test('Retirar: a conta volta às contas no seu lugar pela ordem do nome', async () => {
  // Na sessão do admin principal, a Ana pode ser retirada (não é a própria conta).
  const m = await carregada({ euId: 'u-bruce' });
  m.ecra.pedirRetirar(ID_ANA);
  m.ecra.responderRetirar(RESPOSTA_RETIRAR);
  await assentar();
  await responder(m, 'retirarMembro', { retirado: true });
  expect(m.vista().novo.opcoesConta.map((o) => o.valor)).toEqual(['u-ana', 'u-bruno', 'u-carla']);
});

test('Retirar um membro com a conta apagada: sai da tabela e não volta às contas', async () => {
  const m = await carregada();
  m.ecra.pedirRetirar(ID_APAGADO);
  expect(m.vista().pergunta.pergunta).toBe('Retirar este membro do CRM?');
  m.ecra.responderRetirar(RESPOSTA_RETIRAR);
  await assentar();
  await responder(m, 'retirarMembro', { retirado: true });
  expect(linhaDe(m, ID_APAGADO)).toBeUndefined();
  expect(m.vista().novo.opcoesConta.map((o) => o.valor)).toEqual(['u-bruno', 'u-carla']);
});

test('Retirar e falhar: o aviso de erro e a linha fica; 404 (já tinha saído) pede as listas outra vez', async () => {
  const m = await carregada();
  m.ecra.pedirRetirar(ID_RUI);
  m.ecra.responderRetirar(RESPOSTA_RETIRAR);
  await assentar();
  await falhar(m, 'retirarMembro', erroSemRede());
  expect(m.erros).toEqual([MENSAGEM_SEM_REDE]);
  expect(linhaDe(m, ID_RUI)).toMatchObject({ ocupada: false });
  expect(m.avisos).toEqual([]);
  expect(m.focos).toEqual([]);
  expect(resumo(m)).toEqual(['listarMembros', 'listarCandidatos', 'retirarMembro']);
  m.ecra.pedirRetirar(ID_RUI);
  m.ecra.responderRetirar(RESPOSTA_RETIRAR);
  await assentar();
  await falhar(m, 'retirarMembro', erro404());
  expect(m.erros).toEqual([MENSAGEM_SEM_REDE, 'Membro não encontrado.']);
  expect(resumo(m).slice(4)).toEqual(['listarMembros', 'listarCandidatos']);
});

test('a pergunta do Retirar: só a primeira resposta conta, uma de cada vez, e nunca para o admin principal nem a própria conta', async () => {
  const m = await carregada();
  m.ecra.pedirRetirar(null);
  m.ecra.pedirRetirar(ID_ANA);
  m.ecra.pedirRetirar('0b6f3c1e-9999-4222-8333-444455556666');
  expect(m.vista().pergunta).toBeNull();
  m.ecra.responderRetirar(RESPOSTA_RETIRAR);
  expect(pedidos(m, 'retirarMembro')).toEqual([]);

  m.ecra.pedirRetirar(ID_RUI);
  m.ecra.pedirRetirar(ID_ZE);
  expect(m.vista().pergunta.pergunta).toBe('Retirar Rui Silva do CRM?');
  // Com a pergunta aberta, o perfil não muda (o diálogo tapa o ecrã).
  m.ecra.mudarPerfil(ID_ZE, 'admin');
  expect(pedidos(m, 'mudarPerfilMembro')).toEqual([]);
  m.ecra.responderRetirar(null);
  m.ecra.responderRetirar(RESPOSTA_RETIRAR);
  await assentar();
  expect(pedidos(m, 'retirarMembro')).toEqual([]);
});

// --- Listas pedidas outra vez e sair -------------------------------------------------------------

test('as listas pedidas outra vez: um pedido de cada vez; uma falha deixa as que estavam', async () => {
  const m = await carregada();
  m.ecra.mudarPerfil(ID_RUI, 'admin');
  m.ecra.mudarPerfil(ID_ZE, 'admin');
  await assentar();
  await falhar(m, 'mudarPerfilMembro', erro404());
  pedidos(m, 'mudarPerfilMembro')[0].rejeitar(erro404());
  await assentar();
  expect(pedidos(m, 'listarMembros')).toHaveLength(2);
  await falhar(m, 'listarMembros', erroSemRede());
  await falhar(m, 'listarCandidatos', erroSemRede());
  expect(m.vista().estado).toBe('pronto');
  expect(m.vista().linhas.map((l) => l.id)).toEqual([null, ID_ANA, ID_RUI, ID_ZE, ID_APAGADO]);
  expect(m.erros).toEqual(['Membro não encontrado.', 'Membro não encontrado.']);
});

test('ao sair: a pergunta fecha sem retirar; as respostas, a rede e as escolhas que chegam depois não mexem em nada', async () => {
  const m = await carregada();
  m.ecra.pedirRetirar(ID_RUI);
  m.ecra.destruir();
  expect(m.vista().pergunta).toBeNull();
  const vistasAntes = m.vistas.length;
  m.ecra.responderRetirar(RESPOSTA_RETIRAR);
  m.ecra.mudarPerfil(ID_ZE, 'admin');
  m.ecra.adicionar();
  m.ecra.escolherConta('u-carla');
  m.mudarRede(false);
  m.mudarRede(true);
  await assentar();
  expect(resumo(m)).toEqual(['listarMembros', 'listarCandidatos']);
  expect(m.vistas).toHaveLength(vistasAntes);

  const outra = await carregada();
  await adicionar(outra);
  outra.ecra.mudarPerfil(ID_RUI, 'admin');
  outra.ecra.pedirRetirar(ID_ZE);
  outra.ecra.responderRetirar(RESPOSTA_RETIRAR);
  await assentar();
  outra.ecra.destruir();
  const n = outra.vistas.length;
  await responder(outra, 'adicionarMembro', copia(BRUNO_MEMBRO));
  await responder(outra, 'mudarPerfilMembro', { ...copia(RUI), perfil: 'admin' });
  await responder(outra, 'retirarMembro', { retirado: true });
  expect(outra.vistas).toHaveLength(n);
  expect(outra.avisos).toEqual([]);
  expect(outra.focos).toEqual([]);

  const aCarregar = montar();
  aCarregar.ecra.destruir();
  const vistasAoSair = aCarregar.vistas.length;
  await falhar(aCarregar, 'listarMembros', erroSemRede());
  await responder(aCarregar, 'listarCandidatos', copia(CANDIDATOS));
  expect(aCarregar.vistas).toHaveLength(vistasAoSair);
  expect(aCarregar.vista().estado).toBe('a_carregar');
  aCarregar.ecra.tentarDeNovo();
  expect(aCarregar.api.pedidos).toHaveLength(2);
});
