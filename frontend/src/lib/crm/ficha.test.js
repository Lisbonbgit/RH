/**
 * FICHA DA LOJA — as regras do ecrã "Ficha da loja", sem DOM.
 *
 * Porta de public/assets/js/ecras/loja.js do CRM autónomo (etiqueta
 * `referencia-standalone`), com os casos de tests/js/loja.test.js (correção
 * "T2.28 (Ficha da loja — fase num toque)"):
 *   - as funções puras (`estadoGuardarFicha`, `corpoAlteracao`,
 *     `textoLocalizacao`), tal e qual;
 *   - o ecrã sem o DOM (`criarFicha`), como a nova loja da T2.27: o que o
 *     autónomo escrevia no DOM é uma `vista` congelada, entregue ao
 *     `aoMudarVista`, e o `pages/crm/CrmLoja.js` só a desenha. Ficam aqui os
 *     casos do ecrã que não precisam de DOM nem de Leaflet (o seletor tem os
 *     seus no `seletor.test.js`, o formulário no `formularioLoja.test.js`):
 *     carregar, Guardar, a fase num toque (um pedido de cada vez, a versão em
 *     vigor, a fase por guardar sem rede), o conflito e o Recarregar, a
 *     correção da localização com o duplicado, e Apagar.
 *
 * Adaptações ao portal (plano T2.28):
 *   - ids uuid em texto; as chamadas são as do `lib/crm/api.js` (`obterLoja`,
 *     `listarRegioes`, `alterarLoja`, `apagarLoja`, sempre com o id da rota) e
 *     os erros são `ErroCrm`;
 *   - "Fase guardada" e "Alterações guardadas" são avisos (`aoAvisar`, um
 *     toast do sonner na página), e não o parágrafo que ficava até à mudança
 *     seguinte; dois toques seguidos na fase dão um só aviso, o da última;
 *   - apagada, a loja leva ao mapa da mesma casa com `state: {aviso: 'Loja
 *     apagada'}` (o toast é do mapa, nota da T2.25); "Sim, abrir X" abre
 *     `<casa>/lojas/<id>`;
 *   - a região da loja que não está na lista das regiões fica escolhida como
 *     "Região guardada" (no autónomo passava a "Sem região" e guardar tirava a
 *     loja da região).
 */
import { ErroCrm, MENSAGEM_ERRO_INESPERADO, MENSAGEM_SEM_REDE } from './api';
import { criarEstadoRede } from './rede';
import {
  PERGUNTA_APAGAR,
  RESPOSTA_APAGAR,
  TEXTO_A_APAGAR,
  TEXTO_A_CARREGAR,
  TEXTO_ALTERACOES_GUARDADAS,
  TEXTO_APAGAR,
  TEXTO_APAGAR_AVISO,
  TEXTO_APAGAR_LOJA,
  TEXTO_APAGAR_PERGUNTA,
  TEXTO_CONFLITO,
  TEXTO_FALTA_ALTERACOES,
  TEXTO_FALTA_CONFLITO,
  TEXTO_FALTA_CORRECAO,
  TEXTO_FALTA_NOME,
  TEXTO_FASE_GUARDADA,
  TEXTO_LOJA_APAGADA,
  TITULO_FICHA,
  caminhoNoMapa,
  corpoAlteracao,
  criarFicha,
  destinoDepoisDeApagar,
  estadoGuardarFicha,
  opcoesRegiaoFicha,
  textoLocalizacao,
} from './ficha';

const LISBOA = '3f1c2d4e-5a6b-4c7d-8e9f-0a1b2c3d4e5f';
const PORTO = '7a8b9c0d-1e2f-4a3b-9c4d-5e6f7a8b9c0d';
const SETUBAL = 'c0ffee00-0000-4000-a000-000000000099';
const ID = '0b6f3c1e-1111-4222-8333-444455556666';
const CAFE_CENTRAL = '9d8c7b6a-5f4e-4d3c-a2b1-c0d9e8f7a6b5';

const REGIOES = [{ id: LISBOA, nome: 'Lisboa', ordem: 0 }, { id: PORTO, nome: 'Porto', ordem: 1 }];

const LOJA = Object.freeze({
  id: ID,
  nome: 'Mercearia da Baixa',
  fase: 'amostra',
  fase_desde: '2026-10-01T09:00:00Z',
  regiao_id: PORTO,
  morada: 'Rua Augusta 24',
  codigo_postal: '1100-048',
  localidade: 'Lisboa',
  lat: 38.70921,
  lng: -9.13712,
  origem_coords: 'gps',
  precisao_m: 12,
  telefone: '+351 912 345 678',
  pessoa_contacto: null,
  notas: null,
  janela1_inicio: '10:00',
  janela1_fim: '13:00',
  janela2_inicio: null,
  janela2_fim: null,
  dias_fechada: ['dom'],
  visita_pendente_motivo: null,
  visita_pendente_desde: null,
  ultima_interacao_em: null,
  ultima_visita_ou_entrega_em: null,
  criado_por: 'seed-local',
  criado_em: '2026-10-01T09:00:00Z',
  atualizado_em: '2026-10-03T09:00:00.123456Z',
});
const VERSAO_NOVA = '2026-10-03T10:00:00.000001Z';
// Uma cópia funda, como a que o servidor manda (o jsdom do Jest 27 não tem `structuredClone`).
const copia = (loja = LOJA, mudancas = {}) => ({ ...JSON.parse(JSON.stringify(loja)), ...mudancas });

// --- Funções puras -------------------------------------------------------------------------------

test('estadoGuardarFicha: só com alterações; nome, correção por confirmar, conflito e sem rede impedem', () => {
  const base = { nome: 'Mercearia', alterada: true, aCorrigir: false, conflito: false, online: true, aGuardar: false };
  expect(estadoGuardarFicha(base)).toEqual({ ativo: true, texto: 'Guardar', falta: null });
  expect(estadoGuardarFicha({ ...base, alterada: false })).toEqual({ ativo: false, texto: 'Guardar', falta: 'Sem alterações por guardar.' });
  expect(estadoGuardarFicha({ ...base, nome: '  ' })).toEqual({ ativo: false, texto: 'Guardar', falta: 'Para guardar, escreva o nome.' });
  expect(estadoGuardarFicha({ ...base, aCorrigir: true })).toEqual({
    ativo: false, texto: 'Guardar', falta: 'Para guardar, confirme a localização no mapa ou cancele a correção.',
  });
  expect(estadoGuardarFicha({ ...base, conflito: true })).toEqual({
    ativo: false, texto: 'Guardar', falta: 'Recarregue a ficha para ver o que a outra pessoa mudou.',
  });
  expect(estadoGuardarFicha({ ...base, online: false })).toEqual({ ativo: false, texto: 'Guardar — sem rede', falta: null });
  expect(estadoGuardarFicha({ ...base, aGuardar: true, online: false })).toEqual({ ativo: false, texto: 'A guardar…', falta: null });
  // A ordem dos motivos: o conflito, depois o nome, a correção e, por fim, as alterações.
  expect(estadoGuardarFicha({ ...base, conflito: true, nome: '', aCorrigir: true, alterada: false }).falta).toBe(TEXTO_FALTA_CONFLITO);
  expect(estadoGuardarFicha({ ...base, nome: '', aCorrigir: true, alterada: false }).falta).toBe(TEXTO_FALTA_NOME);
  expect(estadoGuardarFicha({ ...base, aCorrigir: true, alterada: false }).falta).toBe(TEXTO_FALTA_CORRECAO);
  expect(estadoGuardarFicha({ ...base, nome: 7 }).falta).toBe(TEXTO_FALTA_NOME);
  // Os textos exatos dos motivos (correção da T2.28).
  expect([TEXTO_FALTA_ALTERACOES, TEXTO_FALTA_NOME, TEXTO_FALTA_CORRECAO, TEXTO_FALTA_CONFLITO]).toEqual([
    'Sem alterações por guardar.',
    'Para guardar, escreva o nome.',
    'Para guardar, confirme a localização no mapa ou cancele a correção.',
    'Recarregue a ficha para ver o que a outra pessoa mudou.',
  ]);
});

test('corpoAlteracao: só os campos alterados + o atualizado_em da loja carregada; confirmar_duplicado só quando confirmado', () => {
  const atual = { nome: 'Mercearia da Baixa', fase: 'cliente', telefone: '+351 912 345 678', notas: '' };
  expect(corpoAlteracao(LOJA, atual)).toStrictEqual({ fase: 'cliente', atualizado_em: LOJA.atualizado_em });
  expect(corpoAlteracao(LOJA, atual, { confirmarDuplicado: true })).toStrictEqual({
    fase: 'cliente', atualizado_em: LOJA.atualizado_em, confirmar_duplicado: true,
  });
  // A localização vai em bloco.
  expect(corpoAlteracao(LOJA, { lat: 38.7095, lng: -9.1372, origem_coords: 'pin_manual', precisao_m: null })).toStrictEqual({
    lat: 38.7095, lng: -9.1372, origem_coords: 'pin_manual', precisao_m: null, atualizado_em: LOJA.atualizado_em,
  });
  // Sem alterações, só a versão (o servidor aceita-o e avança a versão: o ecrã não o envia).
  expect(corpoAlteracao(LOJA, { nome: LOJA.nome })).toStrictEqual({ atualizado_em: LOJA.atualizado_em });
});

test('textoLocalizacao: de onde vem o pino guardado', () => {
  expect(textoLocalizacao({ origem_coords: 'gps', precisao_m: 12 })).toBe('Pino do GPS, no local (precisão de 12 m).');
  expect(textoLocalizacao({ origem_coords: 'gps', precisao_m: null })).toBe('Pino do GPS, no local.');
  expect(textoLocalizacao({ origem_coords: 'geocoder', precisao_m: null })).toBe('Pino da morada escolhida na pesquisa.');
  expect(textoLocalizacao({ origem_coords: 'pin_manual', precisao_m: null })).toBe('Pino posto à mão no mapa.');
  expect(textoLocalizacao(null)).toBe('Pino posto à mão no mapa.');
});

test('opcoesRegiaoFicha: "Sem região" e as regiões; a da loja fica como "Região guardada" enquanto não estiver na lista', () => {
  expect(opcoesRegiaoFicha(null, PORTO)).toEqual([{ valor: 'sem', texto: 'Sem região' }, { valor: PORTO, texto: 'Região guardada' }]);
  expect(opcoesRegiaoFicha(null, null)).toEqual([{ valor: 'sem', texto: 'Sem região' }]);
  expect(opcoesRegiaoFicha(REGIOES, PORTO)).toEqual([
    { valor: 'sem', texto: 'Sem região' }, { valor: LISBOA, texto: 'Lisboa' }, { valor: PORTO, texto: 'Porto' },
  ]);
  // A região da loja que não veio na lista (ex.: criada depois de a lista chegar) não se perde.
  expect(opcoesRegiaoFicha(REGIOES, SETUBAL)).toEqual([
    { valor: 'sem', texto: 'Sem região' }, { valor: LISBOA, texto: 'Lisboa' }, { valor: PORTO, texto: 'Porto' },
    { valor: SETUBAL, texto: 'Região guardada' },
  ]);
  expect(opcoesRegiaoFicha([], 7)).toEqual([{ valor: 'sem', texto: 'Sem região' }]);
  const opcoes = opcoesRegiaoFicha(REGIOES, SETUBAL);
  expect(Object.isFrozen(opcoes)).toBe(true);
  expect(opcoes.every(Object.isFrozen)).toBe(true);
});

test('textos exatos da ficha', () => {
  expect(TITULO_FICHA).toBe('Ficha da loja');
  expect(TEXTO_A_CARREGAR).toBe('A carregar a ficha…');
  expect(TEXTO_CONFLITO).toBe('Alterado por outra pessoa — recarregar');
  expect(TEXTO_FASE_GUARDADA).toBe('Fase guardada');
  expect(TEXTO_ALTERACOES_GUARDADAS).toBe('Alterações guardadas');
  expect(TEXTO_LOJA_APAGADA).toBe('Loja apagada');
  expect(TEXTO_APAGAR).toBe('Apagar esta loja? Use só para enganos — se a loja não está interessada, mude a fase para Perdida.');
  expect(TEXTO_APAGAR).toBe(`${TEXTO_APAGAR_PERGUNTA} ${TEXTO_APAGAR_AVISO}`);
  expect([TEXTO_APAGAR_LOJA, TEXTO_A_APAGAR]).toEqual(['Apagar loja', 'A apagar…']);
  expect(PERGUNTA_APAGAR).toEqual({
    pergunta: 'Apagar esta loja?',
    aviso: 'Use só para enganos — se a loja não está interessada, mude a fase para Perdida.',
    botoes: [{ texto: 'Cancelar', valor: null, variante: 'normal' }, { texto: 'Sim, apagar', valor: RESPOSTA_APAGAR, variante: 'perigo' }],
  });
  expect(Object.isFrozen(PERGUNTA_APAGAR)).toBe(true);
  expect(Object.isFrozen(PERGUNTA_APAGAR.botoes)).toBe(true);
  expect(PERGUNTA_APAGAR.botoes.every(Object.isFrozen)).toBe(true);
});

test('destinoDepoisDeApagar e caminhoNoMapa: o mapa da mesma casa', () => {
  expect(destinoDepoisDeApagar('/crm')).toEqual({ caminho: '/crm/mapa', estado: { aviso: 'Loja apagada' } });
  expect(destinoDepoisDeApagar('/admin/crm').caminho).toBe('/admin/crm/mapa');
  expect(caminhoNoMapa('/crm', ID)).toBe(`/crm/mapa?loja=${ID}`);
  expect(caminhoNoMapa('/admin/crm', 'a b&c/d')).toBe('/admin/crm/mapa?loja=a%20b%26c%2Fd');
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
    obterLoja: pedir('obterLoja'),
    listarRegioes: pedir('listarRegioes'),
    alterarLoja: pedir('alterarLoja'),
    apagarLoja: pedir('apagarLoja'),
  };
}

const assentar = () => new Promise((r) => {
  setTimeout(r, 0);
});

// Monta o ecrã como a página (CrmLoja): cria e inicia (pede a loja e as regiões, e ouve a rede).
function montar({ online = true, base = '/crm', id = ID, iniciar = true } = {}) {
  const api = apiFalsa();
  const janela = new EventTarget();
  const navegador = { onLine: online };
  const navegacoes = [];
  const focos = [];
  const avisos = [];
  const vistas = [];
  const seletor = [];
  let ecra = null;
  ecra = criarFicha({
    api,
    rede: criarEstadoRede(janela, navegador),
    base,
    id,
    navegar: (caminho, opcoes) => navegacoes.push({ caminho, opcoes }),
    // O seletor da correção (SeletorLocalizacao pela ref): o desconfirmar avisa que a localização saiu, como o
    // verdadeiro (aoMudar(null)).
    seletor: {
      limparErro: () => seletor.push(['limparErro']),
      desconfirmar: () => {
        seletor.push(['desconfirmar']);
        ecra.mudarLocalizacao(null);
      },
      mostrarErro: (texto) => seletor.push(['mostrarErro', texto]),
      focar: () => seletor.push(['focar']),
    },
    aoMudarVista: (vista) => vistas.push(vista),
    aoFocar: (alvo) => focos.push(alvo),
    aoAvisar: (texto) => avisos.push(texto),
  });
  if (iniciar) ecra.iniciar();
  const mudarRede = (ligado) => {
    navegador.onLine = ligado;
    janela.dispatchEvent(new Event(ligado ? 'online' : 'offline'));
  };
  return { api, ecra, navegacoes, focos, avisos, vistas, seletor, mudarRede, vista: () => ecra.vista };
}

const pedidos = (m, nome) => m.api.pedidos.filter((p) => p.nome === nome);
const ultimo = (m, nome) => pedidos(m, nome).at(-1);

async function responder(m, nome, dados) {
  ultimo(m, nome).resolver(dados);
  await assentar();
}

async function falhar(m, nome, erro) {
  ultimo(m, nome).rejeitar(erro);
  await assentar();
}

// O ecrã com a loja e as regiões carregadas.
async function carregada(opcoes = {}, loja = LOJA) {
  const m = montar(opcoes);
  await responder(m, 'obterLoja', copia(loja));
  await responder(m, 'listarRegioes', REGIOES);
  return m;
}

async function guardar(m, opcoes) {
  m.ecra.guardar(opcoes);
  await assentar();
  return ultimo(m, 'alterarLoja');
}

// Tocar numa pastilha da fase: o formulário muda a fase (aoMudar) e pede para a gravar (aoMudarFase).
async function tocarNaFase(m, fase) {
  m.ecra.mudarCampo('fase', fase);
  m.ecra.guardarFase();
  await assentar();
}

const corpo = (pedido) => pedido.argumentos[1];
const erroSemRede = () => new ErroCrm({ codigo: 'sem_rede', mensagem: MENSAGEM_SEM_REDE });
const erroConflito = () => new ErroCrm({ codigo: 'conflito', mensagem: 'Alterado por outra pessoa — recarregar', estado: 409 });
const erroDuplicado = (lojas = [{ id: CAFE_CENTRAL, nome: 'Café Central', distancia_m: 18 }]) => new ErroCrm({
  codigo: 'duplicado', mensagem: `Já existe ${lojas[0]?.nome} aqui — é a mesma?`, estado: 409, extra: { lojas },
});
const erroValidacao = (campos) => new ErroCrm({ codigo: 'validacao', mensagem: 'Verifique os campos assinalados.', estado: 422, campos });

const PINO_NOVO = Object.freeze({ lat: 38.7095, lng: -9.1374, origem_coords: 'pin_manual', precisao_m: null });

// --- Carregar ------------------------------------------------------------------------------------

test('pede a loja (com o id da rota) e as regiões; até a loja chegar mostra "A carregar a ficha…"', () => {
  const m = montar();
  expect(m.api.pedidos.map((p) => [p.nome, ...p.argumentos])).toEqual([['obterLoja', ID], ['listarRegioes']]);
  expect(m.vista().estado).toBe('a_carregar');
  expect(m.vista().titulo).toBe('Ficha da loja');
  expect(m.vista().falha).toBe(null);
  expect(m.vista().correcao).toBe(null); // o mapa só aparece ao corrigir a localização
  expect(m.vista().guardar.ativo).toBe(false);
});

test('criar o ecrã não pede nada; iniciar pede a loja e as regiões uma vez', () => {
  const m = montar({ iniciar: false });
  expect(m.api.pedidos).toEqual([]);
  m.ecra.iniciar();
  m.ecra.iniciar();
  expect(pedidos(m, 'obterLoja')).toHaveLength(1);
  expect(pedidos(m, 'listarRegioes')).toHaveLength(1);
});

test('a ficha: o nome no título e o formulário igual ao da criação, já preenchido, com horário e dias fechada', async () => {
  const m = await carregada();
  const vista = m.vista();
  expect(vista.estado).toBe('ficha');
  expect(vista.titulo).toBe('Mercearia da Baixa');
  expect(vista.valores).toEqual({
    nome: 'Mercearia da Baixa',
    fase: 'amostra',
    regiao_id: PORTO,
    telefone: '+351 912 345 678',
    pessoa_contacto: '',
    morada: 'Rua Augusta 24',
    codigo_postal: '1100-048',
    localidade: 'Lisboa',
    notas: '',
    janela1_inicio: '10:00',
    janela1_fim: '13:00',
    janela2_inicio: '',
    janela2_fim: '',
    dias_fechada: ['dom'],
  });
  expect(vista.valorRegiao).toBe(PORTO);
  expect(vista.resumoLocalizacao).toBe('Pino do GPS, no local (precisão de 12 m).');
  expect(vista.guardar).toEqual({ ativo: false, texto: 'Guardar', falta: 'Sem alterações por guardar.' });
  expect(vista.camposDesativados).toBe(false);
  expect(vista.conflito).toBe(null);
  expect(vista.alerta).toBe(null);
  expect(vista.apagar).toEqual({ texto: 'Apagar loja', ativo: true, erro: null, pergunta: null });
});

test('os dados da loja entram como texto: <b>x</b> fica tal e qual', async () => {
  const m = await carregada({}, copia(LOJA, { nome: '<b>x</b>', notas: '<img src=x onerror=alert(1)>' }));
  expect(m.vista().titulo).toBe('<b>x</b>');
  expect(m.vista().valores.notas).toBe('<img src=x onerror=alert(1)>');
});

test('até as regiões chegarem, a região da loja fica escolhida ("Região guardada") e não se perde', async () => {
  const m = montar();
  await responder(m, 'obterLoja', copia());
  expect(m.vista().valorRegiao).toBe(PORTO);
  expect(m.vista().opcoesRegiao.find((o) => o.valor === PORTO).texto).toBe('Região guardada');
  expect(m.vista().guardar.ativo).toBe(false); // a região não conta como alterada
  await responder(m, 'listarRegioes', REGIOES);
  expect(m.vista().valorRegiao).toBe(PORTO);
  expect(m.vista().opcoesRegiao.find((o) => o.valor === PORTO).texto).toBe('Porto');
});

test('as regiões que chegam primeiro ficam à espera da loja', async () => {
  const m = montar();
  await responder(m, 'listarRegioes', REGIOES);
  await responder(m, 'obterLoja', copia());
  expect(m.vista().valorRegiao).toBe(PORTO);
  expect(m.vista().opcoesRegiao).toHaveLength(3);
});

test('uma loja numa região que não veio na lista: fica escolhida e não conta como alterada', async () => {
  const m = await carregada({}, copia(LOJA, { regiao_id: SETUBAL }));
  expect(m.vista().valorRegiao).toBe(SETUBAL);
  expect(m.vista().opcoesRegiao.at(-1)).toEqual({ valor: SETUBAL, texto: 'Região guardada' });
  expect(m.vista().guardar.falta).toBe('Sem alterações por guardar.');
  m.ecra.mudarCampo('telefone', '912 000 000');
  expect(corpo(await guardar(m))).toStrictEqual({ telefone: '912 000 000', atualizado_em: LOJA.atualizado_em });
});

test('as regiões falham: o erro junto ao campo, a região da loja fica, e pedem-se outra vez quando a rede volta', async () => {
  const m = montar();
  await responder(m, 'obterLoja', copia());
  await falhar(m, 'listarRegioes', erroSemRede());
  expect(m.vista().erros).toEqual({ regiao_id: MENSAGEM_SEM_REDE });
  expect(m.vista().valorRegiao).toBe(PORTO);
  m.mudarRede(false);
  m.mudarRede(true);
  expect(pedidos(m, 'listarRegioes')).toHaveLength(2);
  await responder(m, 'listarRegioes', REGIOES);
  expect(m.vista().erros).toEqual({});
  expect(m.vista().valorRegiao).toBe(PORTO);
  m.mudarRede(false);
  m.mudarRede(true);
  expect(pedidos(m, 'listarRegioes')).toHaveLength(2); // com as regiões carregadas não volta a pedir
});

test('as regiões falham antes de a loja chegar: o erro continua junto à região depois de a loja chegar', async () => {
  // Revisão da F2 ("ficha-erro-regioes-apagado"): um 500 não traz o 'online', por isso este erro é o único aviso.
  const m = montar();
  await falhar(m, 'listarRegioes', new ErroCrm({ codigo: 'erro_interno', mensagem: MENSAGEM_ERRO_INESPERADO, estado: 500 }));
  expect(m.vista().erros).toEqual({ regiao_id: MENSAGEM_ERRO_INESPERADO });
  await responder(m, 'obterLoja', copia());
  expect(m.vista().estado).toBe('ficha');
  expect(m.vista().erros).toEqual({ regiao_id: MENSAGEM_ERRO_INESPERADO });
  expect(m.vista().valorRegiao).toBe(PORTO);
  // Quando as regiões chegarem (a rede volta), o erro sai.
  m.mudarRede(false);
  m.mudarRede(true);
  await responder(m, 'listarRegioes', REGIOES);
  expect(m.vista().erros).toEqual({});
});

test('uma resposta das regiões que não é uma lista conta como nenhuma região (e não se volta a pedir)', async () => {
  const m = montar();
  await responder(m, 'obterLoja', copia());
  await responder(m, 'listarRegioes', null);
  expect(m.vista().opcoesRegiao).toEqual([{ valor: 'sem', texto: 'Sem região' }, { valor: PORTO, texto: 'Região guardada' }]);
  expect(m.vista().valorRegiao).toBe(PORTO);
  m.mudarRede(false);
  m.mudarRede(true);
  expect(pedidos(m, 'listarRegioes')).toHaveLength(1);
});

test('loja que não existe (404): "Loja não encontrada." e a ligação para o mapa, sem "Tentar novamente"', async () => {
  const m = montar();
  await falhar(m, 'obterLoja', new ErroCrm({ codigo: 'nao_encontrado', mensagem: 'Loja não encontrada.', estado: 404 }));
  expect(m.vista().estado).toBe('falha');
  expect(m.vista().falha).toEqual({ mensagem: 'Loja não encontrada.', tentar: false, aTentar: false, voltar: true });
  expect(m.vista().titulo).toBe('Ficha da loja');
  m.mudarRede(false);
  m.mudarRede(true);
  m.ecra.tentarDeNovo();
  expect(pedidos(m, 'obterLoja')).toHaveLength(1); // não existe: não se pede outra vez
});

test('sem rede ao abrir: a mensagem e "Tentar novamente" (um toque, um pedido); também quando a rede volta', async () => {
  const m = montar();
  await falhar(m, 'obterLoja', erroSemRede());
  expect(m.vista().falha).toEqual({ mensagem: MENSAGEM_SEM_REDE, tentar: true, aTentar: false, voltar: false });
  m.ecra.tentarDeNovo();
  m.ecra.tentarDeNovo();
  expect(pedidos(m, 'obterLoja')).toHaveLength(2);
  expect(m.vista().falha.aTentar).toBe(true); // o botão fica desativado enquanto pede
  await falhar(m, 'obterLoja', erroSemRede());
  expect(m.vista().falha.aTentar).toBe(false);
  m.mudarRede(true);
  expect(pedidos(m, 'obterLoja')).toHaveLength(3);
  await responder(m, 'obterLoja', copia());
  expect(m.vista().estado).toBe('ficha');
  expect(m.vista().titulo).toBe('Mercearia da Baixa');
  expect(m.vista().falha).toBe(null);
  m.mudarRede(true);
  m.ecra.tentarDeNovo();
  expect(pedidos(m, 'obterLoja')).toHaveLength(3); // com a ficha carregada não volta a pedir
});

test('um erro inesperado ao abrir (ou sem mensagem): a mensagem genérica, com "Tentar novamente"', async () => {
  const m = montar();
  await falhar(m, 'obterLoja', new Error('rebentou'));
  expect(m.vista().falha).toEqual({ mensagem: MENSAGEM_ERRO_INESPERADO, tentar: true, aTentar: false, voltar: false });
});

test('a vista é nova a cada mudança, congelada, e vai para o aoMudarVista', async () => {
  const m = await carregada();
  const antes = m.vista();
  m.ecra.mudarCampo('telefone', '9');
  expect(m.vista()).not.toBe(antes);
  expect(m.vistas.at(-1)).toBe(m.vista());
  for (const parte of ['valores', 'erros', 'opcoesRegiao', 'guardar', 'apagar']) {
    expect([parte, Object.isFrozen(m.vista()[parte])]).toEqual([parte, true]);
  }
  expect(Object.isFrozen(m.vista())).toBe(true);
  expect(Object.isFrozen(m.vista().valores.dias_fechada)).toBe(true);
  // Nada mudado: não há vista nova.
  const vistas = m.vistas.length;
  m.ecra.mudarCampo('telefone', '9');
  m.ecra.mudarCampo('lat', 38.7);
  m.ecra.alternarDia('dom', true);
  m.ecra.mudarLocalizacao(PINO_NOVO); // sem a correção aberta não há localização nova
  expect(m.vistas).toHaveLength(vistas);
});

test('a resposta que chega depois de sair do ecrã não faz nada', async () => {
  const m = montar();
  const vistas = m.vistas.length;
  m.ecra.destruir();
  await responder(m, 'obterLoja', copia());
  await responder(m, 'listarRegioes', REGIOES);
  expect(m.vista().titulo).toBe('Ficha da loja');
  expect(m.vistas).toHaveLength(vistas);
});

test('destruir deixa de ouvir a rede (o ouvinte sai); criar não ouve nada', () => {
  const ouvintes = new Set();
  const rede = {
    online: () => true,
    aoMudar(ouvinte) {
      ouvintes.add(ouvinte);
      return () => ouvintes.delete(ouvinte);
    },
  };
  const ecra = criarFicha({ api: apiFalsa(), rede, base: '/crm', id: ID });
  expect(ouvintes.size).toBe(0);
  ecra.iniciar();
  ecra.iniciar();
  expect(ouvintes.size).toBe(1);
  ecra.destruir();
  expect(ouvintes.size).toBe(0);
});

// --- Guardar -------------------------------------------------------------------------------------

test('Guardar envia só os campos alterados + atualizado_em, com o id da rota', async () => {
  const m = await carregada();
  m.ecra.mudarCampo('telefone', '912 000 000');
  expect(m.vista().guardar).toEqual({ ativo: true, texto: 'Guardar', falta: null });
  const pedido = await guardar(m);
  expect(pedido.argumentos[0]).toBe(ID);
  expect(corpo(pedido)).toStrictEqual({ telefone: '912 000 000', atualizado_em: LOJA.atualizado_em });
  expect(m.vista().guardar).toEqual({ ativo: false, texto: 'A guardar…', falta: null });
  m.ecra.guardar();
  m.ecra.guardar({ confirmarDuplicado: true });
  await assentar();
  expect(pedidos(m, 'alterarLoja')).toHaveLength(1); // um toque, um pedido
});

test('sem alterações (ou antes de a loja chegar), Guardar não envia nada', async () => {
  const antes = montar();
  antes.ecra.mudarCampo('nome', 'X');
  antes.ecra.guardar();
  await assentar();
  expect(pedidos(antes, 'alterarLoja')).toHaveLength(0);
  const m = await carregada();
  m.ecra.guardar();
  await assentar();
  expect(pedidos(m, 'alterarLoja')).toHaveLength(0);
});

test('voltar a pôr o valor original: deixa de haver alterações', async () => {
  const m = await carregada();
  m.ecra.mudarCampo('telefone', '912 000 000');
  expect(m.vista().guardar.ativo).toBe(true);
  m.ecra.mudarCampo('telefone', '+351 912 345 678');
  expect(m.vista().guardar).toEqual({ ativo: false, texto: 'Guardar', falta: 'Sem alterações por guardar.' });
});

test('horário e dias: limpar um campo envia null; os dias vão como lista', async () => {
  const m = await carregada();
  m.ecra.mudarCampo('janela2_inicio', '15:00');
  m.ecra.mudarCampo('janela2_fim', '19:00');
  m.ecra.alternarDia('dom', false);
  m.ecra.alternarDia('sab', true);
  m.ecra.mudarCampo('morada', '');
  expect(corpo(await guardar(m))).toStrictEqual({
    morada: null,
    janela2_inicio: '15:00',
    janela2_fim: '19:00',
    dias_fechada: ['sab'],
    atualizado_em: LOJA.atualizado_em,
  });
});

test('os dias marcados pela ordem da semana; desmarcar e voltar a marcar não é alteração', async () => {
  const m = await carregada();
  m.ecra.alternarDia('seg', true);
  expect(m.vista().valores.dias_fechada).toEqual(['seg', 'dom']);
  m.ecra.alternarDia('seg', false);
  expect(m.vista().guardar.falta).toBe('Sem alterações por guardar.');
});

test('nome vazio: Guardar desativado com o que falta', async () => {
  const m = await carregada();
  m.ecra.mudarCampo('nome', ' ');
  expect(m.vista().guardar).toEqual({ ativo: false, texto: 'Guardar', falta: 'Para guardar, escreva o nome.' });
});

test('sucesso: a ficha fica com a loja devolvida (atualizado_em novo) e o aviso "Alterações guardadas"', async () => {
  const m = await carregada();
  m.ecra.mudarCampo('nome', '  Mercearia Nova ');
  const pedido = await guardar(m);
  expect(m.avisos).toEqual([]);
  pedido.resolver(copia(LOJA, { nome: 'Mercearia Nova', atualizado_em: VERSAO_NOVA }));
  await assentar();
  expect(m.vista().titulo).toBe('Mercearia Nova');
  expect(m.vista().valores.nome).toBe('Mercearia Nova'); // o valor que o servidor guardou
  expect(m.avisos).toEqual(['Alterações guardadas']);
  expect(m.vista().guardar).toEqual({ ativo: false, texto: 'Guardar', falta: 'Sem alterações por guardar.' });

  m.ecra.mudarCampo('telefone', '912 000 000');
  expect(corpo(await guardar(m))).toStrictEqual({ telefone: '912 000 000', atualizado_em: VERSAO_NOVA }); // a versão nova
  expect(m.navegacoes).toEqual([]); // fica na ficha
});

test('enquanto grava, os campos não se editam: o que se escrevesse perdia-se quando a resposta chegasse', async () => {
  const m = await carregada();
  m.ecra.mudarCampo('telefone', '912 000 000');
  expect(m.vista().camposDesativados).toBe(false);
  await guardar(m);
  expect(m.vista().camposDesativados).toBe(true);
  // Mesmo que um campo mude (não devia: estão desativados), não conta.
  m.ecra.mudarCampo('notas', 'perdida');
  m.ecra.alternarDia('seg', true);
  m.ecra.abrirCorrecao();
  expect(m.vista().valores.notas).toBe('');
  expect(m.vista().valores.dias_fechada).toEqual(['dom']);
  expect(m.vista().correcao).toBe(null);
  await responder(m, 'alterarLoja', copia(LOJA, { telefone: '912 000 000', atualizado_em: VERSAO_NOVA }));
  expect(m.vista().camposDesativados).toBe(false);
});

test('se gravar falhar, os campos voltam a editar-se e o que se escreveu fica', async () => {
  const m = await carregada();
  m.ecra.mudarCampo('telefone', '912 000 000');
  await guardar(m);
  await falhar(m, 'alterarLoja', erroSemRede());
  expect(m.vista().camposDesativados).toBe(false);
  expect(m.vista().valores.telefone).toBe('912 000 000');
});

test('sem rede: Guardar desativado com "sem rede", e volta quando a rede voltar', async () => {
  const m = await carregada();
  m.ecra.mudarCampo('telefone', '912 000 000');
  m.mudarRede(false);
  expect(m.vista().guardar).toEqual({ ativo: false, texto: 'Guardar — sem rede', falta: null });
  m.ecra.guardar();
  await assentar();
  expect(pedidos(m, 'alterarLoja')).toHaveLength(0);
  m.mudarRede(true);
  expect(m.vista().guardar.ativo).toBe(true);
});

test('a abrir sem rede: Guardar já começa com "sem rede"', () => {
  expect(montar({ online: false }).vista().guardar.texto).toBe('Guardar — sem rede');
});

test('409 conflito: a faixa "Alterado por outra pessoa — recarregar", o foco no Recarregar, Guardar desativado', async () => {
  const m = await carregada();
  m.ecra.mudarCampo('telefone', '912 000 000');
  await guardar(m);
  await falhar(m, 'alterarLoja', erroConflito());
  expect(m.vista().conflito).toEqual({ erro: null, aRecarregar: false });
  expect(m.focos).toEqual(['recarregar']);
  expect(m.vista().guardar).toEqual({ ativo: false, texto: 'Guardar', falta: 'Recarregue a ficha para ver o que a outra pessoa mudou.' });
  expect(m.vista().alerta).toBe(null); // a mensagem é a da faixa
  expect(m.vista().valores.telefone).toBe('912 000 000'); // o que se escreveu fica até recarregar
});

test('Recarregar: pede a loja outra vez e a ficha fica com a versão da outra pessoa', async () => {
  const m = await carregada();
  m.ecra.mudarCampo('telefone', '912 000 000');
  await guardar(m);
  await falhar(m, 'alterarLoja', erroConflito());
  m.ecra.recarregar();
  m.ecra.recarregar();
  expect(pedidos(m, 'obterLoja')).toHaveLength(2); // um toque, um pedido
  expect(ultimo(m, 'obterLoja').argumentos).toEqual([ID]);
  expect(m.vista().conflito).toEqual({ erro: null, aRecarregar: true });
  await responder(m, 'obterLoja', copia(LOJA, { fase: 'contactada', telefone: '913 000 000', atualizado_em: VERSAO_NOVA }));
  expect(m.vista().conflito).toBe(null);
  expect(m.vista().valores.fase).toBe('contactada');
  expect(m.vista().valores.telefone).toBe('913 000 000');
  m.ecra.mudarCampo('telefone', '914 000 000');
  expect(corpo(await guardar(m))).toStrictEqual({ telefone: '914 000 000', atualizado_em: VERSAO_NOVA });
});

test('Recarregar sem rede: o erro na faixa, que fica, e pode tentar outra vez', async () => {
  const m = await carregada();
  m.ecra.mudarCampo('telefone', '912 000 000');
  await guardar(m);
  await falhar(m, 'alterarLoja', erroConflito());
  m.ecra.recarregar();
  await falhar(m, 'obterLoja', erroSemRede());
  expect(m.vista().conflito).toEqual({ erro: MENSAGEM_SEM_REDE, aRecarregar: false });
  m.ecra.recarregar();
  expect(pedidos(m, 'obterLoja')).toHaveLength(3);
  expect(m.vista().conflito).toEqual({ erro: null, aRecarregar: true });
});

test('Recarregar uma loja que entretanto foi apagada: "Loja não encontrada." e a ligação para o mapa', async () => {
  const m = await carregada();
  m.ecra.mudarCampo('telefone', '912 000 000');
  await guardar(m);
  await falhar(m, 'alterarLoja', erroConflito());
  m.ecra.recarregar();
  await falhar(m, 'obterLoja', new ErroCrm({ codigo: 'nao_encontrado', mensagem: 'Loja não encontrada.', estado: 404 }));
  expect(m.vista().estado).toBe('falha');
  expect(m.vista().falha).toEqual({ mensagem: 'Loja não encontrada.', tentar: false, aTentar: false, voltar: true });
  expect(m.vista().titulo).toBe('Ficha da loja');
});

test('Recarregar sem conflito não faz nada (o botão só existe na faixa)', async () => {
  const m = await carregada();
  m.ecra.recarregar();
  expect(pedidos(m, 'obterLoja')).toHaveLength(1);
});

test('422: os erros junto aos campos (incluindo as horas), a mensagem do servidor e o foco no primeiro', async () => {
  const m = await carregada();
  m.ecra.mudarCampo('janela1_fim', '09:00');
  await guardar(m);
  await falhar(m, 'alterarLoja', erroValidacao({ janela1_fim: 'O fim tem de ser depois do início.' }));
  expect(m.vista().erros).toEqual({ janela1_fim: 'O fim tem de ser depois do início.' });
  expect(m.focos).toEqual(['janela1_fim']);
  expect(m.vista().alerta).toBe('Verifique os campos assinalados.');
  expect(m.vista().guardar.ativo).toBe(true); // pode corrigir e guardar outra vez
  m.ecra.mudarCampo('janela1_fim', '14:00');
  expect(m.vista().erros).toEqual({});
});

test('422 dos dias e de um campo que a ficha não tem: os dias junto a eles, o outro na mensagem de cima', async () => {
  const m = await carregada();
  m.ecra.alternarDia('seg', true);
  await guardar(m);
  await falhar(m, 'alterarLoja', erroValidacao({ dias_fechada: 'Há dias repetidos.', visita: 'Campo desconhecido.' }));
  expect(m.vista().erros).toEqual({ dias_fechada: 'Há dias repetidos.' });
  expect(m.vista().alerta).toBe('Verifique os campos assinalados. Campo desconhecido.');
  expect(m.focos).toEqual(['dias_fechada']);
});

test('outro erro (ex.: sem rede a meio): a mensagem junto ao Guardar, e pode guardar outra vez', async () => {
  const m = await carregada();
  m.ecra.mudarCampo('telefone', '912 000 000');
  await guardar(m);
  await falhar(m, 'alterarLoja', erroSemRede());
  expect(m.vista().alerta).toBe(MENSAGEM_SEM_REDE);
  expect(m.vista().guardar.ativo).toBe(true);
});

test('uma segunda tentativa limpa as mensagens da anterior', async () => {
  const m = await carregada();
  m.ecra.mudarCampo('telefone', '1');
  await guardar(m);
  await falhar(m, 'alterarLoja', erroValidacao({ telefone: 'Telefone inválido.' }));
  m.ecra.mudarCampo('notas', 'x');
  await guardar(m);
  expect(m.vista().alerta).toBe(null);
  expect(m.vista().erros).toEqual({});
});

// --- A fase (um toque, spec §4.1 e §6.3; correção da T2.28) --------------------------------------

test('a fase muda com um toque: grava logo só a fase + atualizado_em, sem Guardar, e avisa "Fase guardada"', async () => {
  const m = await carregada();
  await tocarNaFase(m, 'cliente');
  const pedido = ultimo(m, 'alterarLoja');
  expect(pedido.argumentos).toEqual([ID, { fase: 'cliente', atualizado_em: LOJA.atualizado_em }]);
  expect(m.vista().guardar.texto).toBe('A guardar…');
  await responder(m, 'alterarLoja', copia(LOJA, { fase: 'cliente', atualizado_em: VERSAO_NOVA }));
  expect(m.avisos).toEqual(['Fase guardada']);
  expect(m.vista().valores.fase).toBe('cliente');
  expect(m.vista().guardar).toEqual({ ativo: false, texto: 'Guardar', falta: 'Sem alterações por guardar.' });

  await tocarNaFase(m, 'perdida');
  expect(corpo(ultimo(m, 'alterarLoja'))).toStrictEqual({ fase: 'perdida', atualizado_em: VERSAO_NOVA }); // a versão nova
  expect(m.navegacoes).toEqual([]); // fica na ficha
});

test('a fase grava-se sozinha: o que se escreveu noutros campos (antes e durante) fica por guardar', async () => {
  const m = await carregada();
  m.ecra.mudarCampo('notas', 'Encomendou 10 caixas');
  await tocarNaFase(m, 'cliente');
  expect(corpo(ultimo(m, 'alterarLoja'))).toStrictEqual({ fase: 'cliente', atualizado_em: LOJA.atualizado_em }); // só a fase
  expect(m.vista().camposDesativados).toBe(false); // gravar a fase não bloqueia os outros campos
  m.ecra.mudarCampo('telefone', '913 000 000');
  await responder(m, 'alterarLoja', copia(LOJA, { fase: 'cliente', atualizado_em: VERSAO_NOVA }));
  expect(m.vista().valores.notas).toBe('Encomendou 10 caixas');
  expect(m.vista().valores.telefone).toBe('913 000 000');
  expect(m.vista().guardar.ativo).toBe(true); // as outras alterações continuam por guardar
  expect(corpo(await guardar(m))).toStrictEqual({ telefone: '913 000 000', notas: 'Encomendou 10 caixas', atualizado_em: VERSAO_NOVA });
});

test('dois toques seguidos na fase: um pedido de cada vez, e fica a última (com a versão nova)', async () => {
  const m = await carregada();
  await tocarNaFase(m, 'cliente');
  await tocarNaFase(m, 'perdida');
  expect(pedidos(m, 'alterarLoja')).toHaveLength(1);
  await responder(m, 'alterarLoja', copia(LOJA, { fase: 'cliente', atualizado_em: VERSAO_NOVA }));
  expect(pedidos(m, 'alterarLoja')).toHaveLength(2);
  expect(corpo(ultimo(m, 'alterarLoja'))).toStrictEqual({ fase: 'perdida', atualizado_em: VERSAO_NOVA });
  expect(m.vista().valores.fase).toBe('perdida');
  expect(m.avisos).toEqual([]); // o aviso é o da última
  await responder(m, 'alterarLoja', copia(LOJA, { fase: 'perdida', atualizado_em: '2026-10-03T10:00:05.000001Z' }));
  expect(pedidos(m, 'alterarLoja')).toHaveLength(2);
  expect(m.avisos).toEqual(['Fase guardada']);
  expect(m.vista().guardar.ativo).toBe(false);
});

test('três toques, o último de volta à fase que ficou gravada: não há segundo pedido', async () => {
  const m = await carregada();
  await tocarNaFase(m, 'cliente');
  await tocarNaFase(m, 'perdida');
  await tocarNaFase(m, 'cliente');
  await responder(m, 'alterarLoja', copia(LOJA, { fase: 'cliente', atualizado_em: VERSAO_NOVA }));
  expect(pedidos(m, 'alterarLoja')).toHaveLength(1);
  expect(m.avisos).toEqual(['Fase guardada']);
});

test('a fase que não se gravou (ex.: sem rede a meio): o erro junto à fase; fica escolhida e Guardar tenta outra vez', async () => {
  const m = await carregada();
  await tocarNaFase(m, 'cliente');
  await falhar(m, 'alterarLoja', erroSemRede());
  expect(m.vista().erros).toEqual({ fase: MENSAGEM_SEM_REDE });
  expect(m.vista().valores.fase).toBe('cliente');
  expect(m.vista().alerta).toBe(null);
  expect(m.avisos).toEqual([]);
  expect(m.vista().guardar.ativo).toBe(true);
  expect(corpo(await guardar(m))).toStrictEqual({ fase: 'cliente', atualizado_em: LOJA.atualizado_em });
});

test('a fase com 409 conflito: a faixa, como no Guardar; com o conflito não grava por cima da outra pessoa', async () => {
  const m = await carregada();
  await tocarNaFase(m, 'cliente');
  await falhar(m, 'alterarLoja', erroConflito());
  expect(m.vista().conflito).toEqual({ erro: null, aRecarregar: false });
  expect(m.focos).toEqual(['recarregar']);
  expect(m.vista().guardar.ativo).toBe(false);
  await tocarNaFase(m, 'perdida');
  expect(pedidos(m, 'alterarLoja')).toHaveLength(1);
});

test('a fase com 422: o erro junto à fase e a mensagem do servidor, como no Guardar', async () => {
  const m = await carregada();
  await tocarNaFase(m, 'cliente');
  await falhar(m, 'alterarLoja', erroValidacao({ fase: 'Fase desconhecida.' }));
  expect(m.vista().erros).toEqual({ fase: 'Fase desconhecida.' });
  expect(m.vista().alerta).toBe('Verifique os campos assinalados.');
  expect(m.focos).toEqual(['fase']);
});

test('sem rede, a fase escolhida fica por guardar: Guardar quando a rede voltar', async () => {
  const m = await carregada({ online: false });
  await tocarNaFase(m, 'cliente');
  expect(pedidos(m, 'alterarLoja')).toHaveLength(0);
  expect(m.vista().guardar.texto).toBe('Guardar — sem rede');
  m.mudarRede(true);
  expect(m.vista().guardar.ativo).toBe(true);
  expect(pedidos(m, 'alterarLoja')).toHaveLength(0); // a rede a voltar não grava sozinha
  expect(corpo(await guardar(m))).toStrictEqual({ fase: 'cliente', atualizado_em: LOJA.atualizado_em });
});

test('voltar a escolher a fase guardada não grava nada', async () => {
  const m = await carregada();
  await tocarNaFase(m, 'amostra');
  expect(pedidos(m, 'alterarLoja')).toHaveLength(0);
});

test('a fase não grava enquanto o Guardar grava, nem o Guardar enquanto a fase grava', async () => {
  const m = await carregada();
  m.ecra.mudarCampo('telefone', '912 000 000');
  await guardar(m);
  m.ecra.guardarFase(); // a fase está desativada (os campos todos); mesmo assim, nada
  await assentar();
  expect(pedidos(m, 'alterarLoja')).toHaveLength(1);
  await responder(m, 'alterarLoja', copia(LOJA, { telefone: '912 000 000', atualizado_em: VERSAO_NOVA }));
  await tocarNaFase(m, 'cliente');
  m.ecra.mudarCampo('notas', 'x');
  m.ecra.guardar();
  await assentar();
  expect(pedidos(m, 'alterarLoja')).toHaveLength(2);
  expect(corpo(ultimo(m, 'alterarLoja'))).toStrictEqual({ fase: 'cliente', atualizado_em: VERSAO_NOVA });
});

test('a fase escolhida sem rede vai no Guardar; enquanto ele grava, a fase não grava à parte', async () => {
  const m = await carregada({ online: false });
  await tocarNaFase(m, 'cliente');
  m.mudarRede(true);
  m.ecra.mudarCampo('telefone', '912 000 000');
  const pedido = await guardar(m);
  expect(corpo(pedido)).toStrictEqual({ fase: 'cliente', telefone: '912 000 000', atualizado_em: LOJA.atualizado_em });
  m.ecra.guardarFase();
  await assentar();
  expect(pedidos(m, 'alterarLoja')).toHaveLength(1);
});

test('a gravação da fase limpa a mensagem de um erro anterior', async () => {
  const m = await carregada();
  m.ecra.mudarCampo('telefone', '912 000 000');
  await guardar(m);
  await falhar(m, 'alterarLoja', erroSemRede());
  expect(m.vista().alerta).toBe(MENSAGEM_SEM_REDE);
  await tocarNaFase(m, 'cliente');
  expect(m.vista().alerta).toBe(null);
});

// --- Corrigir localização ------------------------------------------------------------------------

test('"Corrigir localização" abre o seletor com o pino no sítio guardado; Guardar espera pela confirmação', async () => {
  const m = await carregada();
  m.ecra.abrirCorrecao();
  expect(m.vista().correcao).toEqual({
    chave: 1, inicial: { lat: LOJA.lat, lng: LOJA.lng, origem: 'gps', precisao_m: 12 },
  });
  expect(Object.isFrozen(m.vista().correcao)).toBe(true);
  expect(Object.isFrozen(m.vista().correcao.inicial)).toBe(true);
  expect(m.vista().guardar).toEqual({
    ativo: false, texto: 'Guardar', falta: 'Para guardar, confirme a localização no mapa ou cancele a correção.',
  });
  m.ecra.abrirCorrecao(); // já aberta: a mesma
  expect(m.vista().correcao.chave).toBe(1);
});

test('"Corrigir localização" antes de a loja chegar não abre nada', () => {
  const m = montar();
  m.ecra.abrirCorrecao();
  expect(m.vista().correcao).toBe(null);
});

test('arrastar o pino e confirmar: Guardar envia o bloco da localização (pin_manual), e o seletor fecha', async () => {
  const m = await carregada();
  m.ecra.abrirCorrecao();
  m.ecra.mudarLocalizacao(PINO_NOVO);
  expect(m.vista().guardar.ativo).toBe(true);
  const pedido = await guardar(m);
  expect(corpo(pedido)).toStrictEqual({ ...PINO_NOVO, atualizado_em: LOJA.atualizado_em });
  pedido.resolver(copia(LOJA, { ...PINO_NOVO, atualizado_em: VERSAO_NOVA }));
  await assentar();
  expect(m.vista().correcao).toBe(null);
  expect(m.vista().resumoLocalizacao).toBe('Pino posto à mão no mapa.');
  expect(m.avisos).toEqual(['Alterações guardadas']);
});

test('confirmar sem mexer no pino: não há alterações', async () => {
  const m = await carregada();
  m.ecra.abrirCorrecao();
  m.ecra.mudarLocalizacao({ lat: LOJA.lat, lng: LOJA.lng, origem_coords: 'gps', precisao_m: 12 });
  expect(m.vista().guardar).toEqual({ ativo: false, texto: 'Guardar', falta: 'Sem alterações por guardar.' });
});

test('"Alterar localização" no seletor (aoMudar(null)): Guardar volta a esperar pela confirmação', async () => {
  const m = await carregada();
  m.ecra.abrirCorrecao();
  m.ecra.mudarLocalizacao(PINO_NOVO);
  m.ecra.mudarLocalizacao(null);
  expect(m.vista().guardar.falta).toBe('Para guardar, confirme a localização no mapa ou cancele a correção.');
});

test('"Cancelar correção": fecha o seletor, a localização volta à guardada e o foco vai para "Corrigir localização"', async () => {
  const m = await carregada();
  m.ecra.abrirCorrecao();
  m.ecra.mudarLocalizacao(PINO_NOVO);
  expect(m.vista().guardar.ativo).toBe(true);
  m.ecra.cancelarCorrecao();
  expect(m.vista().correcao).toBe(null);
  expect(m.focos).toEqual(['corrigir']);
  expect(m.vista().guardar).toEqual({ ativo: false, texto: 'Guardar', falta: 'Sem alterações por guardar.' });
  // Uma localização que o seletor (já a sair) ainda mande, já não conta.
  m.ecra.mudarLocalizacao(PINO_NOVO);
  expect(m.vista().guardar.ativo).toBe(false);
  // Abrir outra vez é outro seletor (outra chave), do sítio guardado.
  m.ecra.abrirCorrecao();
  expect(m.vista().correcao.chave).toBe(2);
});

test('a morada escolhida na pesquisa durante a correção preenche os campos e sai ao cancelar', async () => {
  const m = await carregada();
  m.ecra.abrirCorrecao();
  const sugestao = { rotulo: 'Rua do Ouro 3, 1100-060 Lisboa, Portugal', morada: 'Rua do Ouro 3', codigo_postal: '1100-060', localidade: 'Lisboa', lat: 38.7101, lng: -9.138 };
  m.ecra.escolherMorada(sugestao);
  expect(m.vista().valores).toMatchObject({ morada: 'Rua do Ouro 3', codigo_postal: '1100-060', localidade: 'Lisboa' });
  m.ecra.cancelarCorrecao();
  expect(m.vista().valores).toMatchObject({ morada: 'Rua Augusta 24', codigo_postal: '1100-048', localidade: 'Lisboa' });
  expect(m.vista().guardar.ativo).toBe(false);
});

test('a morada sugerida pelo GPS só preenche o que está vazio; cancelar desfaz isso e não o que a pessoa escreveu', async () => {
  const m = await carregada({}, copia(LOJA, { codigo_postal: null }));
  m.ecra.abrirCorrecao();
  m.ecra.sugerirMorada({ rotulo: 'Praça do Comércio', morada: 'Praça do Comércio', codigo_postal: '1100-148', localidade: 'Lisboa', lat: 38.7075, lng: -9.1364 });
  expect(m.vista().valores).toMatchObject({ morada: 'Rua Augusta 24', codigo_postal: '1100-148' });
  m.ecra.mudarCampo('localidade', 'Baixa');
  m.ecra.cancelarCorrecao();
  expect(m.vista().valores).toMatchObject({ morada: 'Rua Augusta 24', codigo_postal: '', localidade: 'Baixa' });
  expect(m.vista().guardar.ativo).toBe(true); // a localidade que a pessoa escreveu continua por guardar
});

test('sem a correção aberta, a morada da pesquisa ou do GPS que chegue tarde não mexe nos campos', async () => {
  const m = await carregada({}, copia(LOJA, { codigo_postal: null }));
  const vistas = m.vistas.length;
  m.ecra.escolherMorada({ rotulo: 'X', morada: 'Rua X', codigo_postal: '1000-000', localidade: 'X', lat: 38.7, lng: -9.1 });
  m.ecra.sugerirMorada({ rotulo: 'X', morada: 'Rua X', codigo_postal: '1000-000', localidade: 'X', lat: 38.7, lng: -9.1 });
  expect(m.vista().valores).toMatchObject({ morada: 'Rua Augusta 24', codigo_postal: '', localidade: 'Lisboa' });
  expect(m.vistas).toHaveLength(vistas);
});

test('409 duplicado ao mudar a localização: o diálogo; "Não, é outra loja" volta a enviar com confirmar_duplicado', async () => {
  const m = await carregada();
  m.ecra.abrirCorrecao();
  m.ecra.mudarLocalizacao(PINO_NOVO);
  const primeiro = await guardar(m);
  await falhar(m, 'alterarLoja', erroDuplicado());
  const { duplicado } = m.vista();
  expect(duplicado.loja).toEqual({ id: CAFE_CENTRAL, nome: 'Café Central', distancia_m: 18 });
  expect(duplicado.mensagem.map((p) => p.texto).join('')).toBe('Já existe Café Central aqui — é a mesma?');
  expect(duplicado.botoes.map((b) => b.texto)).toEqual(['Sim, abrir Café Central', 'Não, é outra loja', 'Cancelar']);
  m.ecra.responderDuplicado('outra');
  await assentar();
  const segundo = ultimo(m, 'alterarLoja');
  expect(segundo).not.toBe(primeiro);
  expect(corpo(segundo)).toStrictEqual({ ...corpo(primeiro), confirmar_duplicado: true });
  expect(corpo(primeiro)).not.toHaveProperty('confirmar_duplicado');
  expect(m.vista().duplicado).toBe(null);
});

test('409 duplicado → "Sim, abrir X" abre a ficha dessa loja, na mesma casa, sem gravar', async () => {
  const m = await carregada({ base: '/admin/crm' });
  m.ecra.abrirCorrecao();
  m.ecra.mudarLocalizacao(PINO_NOVO);
  await guardar(m);
  await falhar(m, 'alterarLoja', erroDuplicado());
  m.ecra.responderDuplicado('abrir');
  await assentar();
  expect(m.navegacoes).toEqual([{ caminho: `/admin/crm/lojas/${CAFE_CENTRAL}`, opcoes: undefined }]);
  expect(pedidos(m, 'alterarLoja')).toHaveLength(1);
});

test('409 duplicado → Cancelar fecha o diálogo, não envia nada e deixa guardar outra vez; só a primeira resposta conta', async () => {
  const m = await carregada();
  m.ecra.responderDuplicado('outra'); // sem diálogo: nada
  m.ecra.abrirCorrecao();
  m.ecra.mudarLocalizacao(PINO_NOVO);
  await guardar(m);
  await falhar(m, 'alterarLoja', erroDuplicado());
  m.ecra.responderDuplicado(null);
  m.ecra.responderDuplicado('outra');
  await assentar();
  expect(m.vista().duplicado).toBe(null);
  expect(pedidos(m, 'alterarLoja')).toHaveLength(1);
  expect(m.vista().guardar.ativo).toBe(true);
});

test('422 na localização (ex.: fora de Portugal): o erro no seletor e o pino volta a soltar-se', async () => {
  const m = await carregada();
  m.ecra.abrirCorrecao();
  m.ecra.mudarLocalizacao(PINO_NOVO);
  await guardar(m);
  expect(m.seletor).toEqual([['limparErro']]);
  m.seletor.length = 0;
  await falhar(m, 'alterarLoja', erroValidacao({ lat: 'Fora de Portugal continental.' }));
  expect(m.seletor).toEqual([['desconfirmar'], ['mostrarErro', 'Fora de Portugal continental.'], ['focar']]);
  expect(m.focos).toEqual([]);
  expect(m.vista().guardar.ativo).toBe(false); // falta confirmar a localização outra vez
  expect(m.vista().alerta).toBe('Verifique os campos assinalados.');
});

test('422 na localização sem a correção aberta (não devia acontecer): a mensagem vai no alerta', async () => {
  const m = await carregada();
  m.ecra.mudarCampo('telefone', '912 000 000');
  await guardar(m);
  await falhar(m, 'alterarLoja', erroValidacao({ lat: 'Fora de Portugal continental.', notas: 'Notas a mais.' }));
  expect(m.vista().alerta).toBe('Verifique os campos assinalados. Fora de Portugal continental.');
  expect(m.vista().erros).toEqual({ notas: 'Notas a mais.' });
  expect(m.seletor.filter(([nome]) => nome !== 'limparErro')).toEqual([]);
});

// --- Apagar --------------------------------------------------------------------------------------

test('Apagar pede confirmação com o texto do plano; Cancelar não apaga', async () => {
  const m = await carregada();
  m.ecra.pedirApagar();
  expect(m.vista().apagar.pergunta).toBe(PERGUNTA_APAGAR);
  m.ecra.pedirApagar(); // já está a perguntar
  m.ecra.responderApagar(null);
  await assentar();
  expect(m.vista().apagar.pergunta).toBe(null);
  expect(pedidos(m, 'apagarLoja')).toHaveLength(0);
  m.ecra.responderApagar(RESPOSTA_APAGAR); // sem pergunta: nada
  await assentar();
  expect(pedidos(m, 'apagarLoja')).toHaveLength(0);
});

test('Apagar confirmado: DELETE (com o id da rota) e volta ao mapa com "Loja apagada"', async () => {
  const m = await carregada();
  m.ecra.pedirApagar();
  m.ecra.responderApagar('apagar');
  await assentar();
  expect(pedidos(m, 'apagarLoja').map((p) => p.argumentos)).toEqual([[ID]]);
  expect(m.vista().apagar).toEqual({ texto: 'A apagar…', ativo: false, erro: null, pergunta: null });
  m.ecra.pedirApagar(); // a apagar: nada
  expect(m.vista().apagar.pergunta).toBe(null);
  await responder(m, 'apagarLoja', { apagada: true });
  expect(m.navegacoes).toEqual([{ caminho: '/crm/mapa', opcoes: { state: { aviso: 'Loja apagada' } } }]);
  expect(m.vista().apagar.ativo).toBe(false); // até o ecrã mudar, não há segundo pedido
});

test('Apagar na casa do admin volta ao mapa do /admin/crm', async () => {
  const m = await carregada({ base: '/admin/crm' });
  m.ecra.pedirApagar();
  m.ecra.responderApagar('apagar');
  await assentar();
  await responder(m, 'apagarLoja', { apagada: true });
  expect(m.navegacoes[0].caminho).toBe('/admin/crm/mapa');
});

test('Apagar uma loja com histórico (409): a mensagem do servidor e a loja fica', async () => {
  const m = await carregada();
  m.ecra.pedirApagar();
  m.ecra.responderApagar('apagar');
  await assentar();
  await falhar(m, 'apagarLoja', new ErroCrm({
    codigo: 'loja_com_historico', mensagem: 'Esta loja tem histórico — mude a fase para perdida em vez de a apagar.', estado: 409,
  }));
  expect(m.vista().apagar).toEqual({
    texto: 'Apagar loja', ativo: true, erro: 'Esta loja tem histórico — mude a fase para perdida em vez de a apagar.', pergunta: null,
  });
  expect(m.navegacoes).toEqual([]);
  // Uma nova tentativa tira a mensagem anterior.
  m.ecra.pedirApagar();
  m.ecra.responderApagar('apagar');
  expect(m.vista().apagar.erro).toBe(null);
});

test('Apagar não abre por cima do diálogo do duplicado, nem antes de a loja chegar', async () => {
  const antes = montar();
  antes.ecra.pedirApagar();
  expect(antes.vista().apagar).toEqual({ texto: 'Apagar loja', ativo: false, erro: null, pergunta: null });
  const m = await carregada();
  m.ecra.abrirCorrecao();
  m.ecra.mudarLocalizacao(PINO_NOVO);
  await guardar(m);
  await falhar(m, 'alterarLoja', erroDuplicado());
  m.ecra.pedirApagar();
  expect(m.vista().apagar.pergunta).toBe(null);
});

test('sair do ecrã com um diálogo aberto fecha-o e já não faz nada', async () => {
  const m = await carregada();
  m.ecra.pedirApagar();
  m.ecra.destruir();
  expect(m.ecra.vista.apagar.pergunta).toBe(null);
  m.ecra.responderApagar('apagar');
  await assentar();
  expect(pedidos(m, 'apagarLoja')).toHaveLength(0);

  const outro = await carregada();
  outro.ecra.abrirCorrecao();
  outro.ecra.mudarLocalizacao(PINO_NOVO);
  await guardar(outro);
  await falhar(outro, 'alterarLoja', erroDuplicado());
  outro.ecra.destruir();
  expect(outro.ecra.vista.duplicado).toBe(null);
  outro.ecra.responderDuplicado('outra');
  outro.ecra.responderDuplicado('abrir');
  await assentar();
  expect(pedidos(outro, 'alterarLoja')).toHaveLength(1);
  expect(outro.navegacoes).toEqual([]);
});

// --- Depois de sair do ecrã ----------------------------------------------------------------------

test('depois de sair do ecrã: as respostas que chegam tarde (gravar, fase, apagar) não fazem nada', async () => {
  const m = await carregada();
  m.ecra.mudarCampo('telefone', '912 000 000');
  const pedido = await guardar(m);
  const vistas = m.vistas.length;
  m.ecra.destruir();
  pedido.resolver(copia(LOJA, { atualizado_em: VERSAO_NOVA }));
  await assentar();
  expect(m.vistas).toHaveLength(vistas);
  expect(m.avisos).toEqual([]);

  const fase = await carregada();
  await tocarNaFase(fase, 'cliente');
  fase.ecra.destruir();
  await falhar(fase, 'alterarLoja', erroConflito());
  expect(fase.focos).toEqual([]);

  const apagar = await carregada();
  apagar.ecra.pedirApagar();
  apagar.ecra.responderApagar('apagar');
  await assentar();
  apagar.ecra.destruir();
  await responder(apagar, 'apagarLoja', { apagada: true });
  expect(apagar.navegacoes).toEqual([]);
});

test('depois de sair do ecrã: mudar a rede ou os campos já não mexe no ecrã', async () => {
  const m = montar();
  await falhar(m, 'obterLoja', erroSemRede());
  m.ecra.destruir();
  const vistas = m.vistas.length;
  m.mudarRede(false);
  m.mudarRede(true);
  m.ecra.mudarCampo('nome', 'X');
  m.ecra.tentarDeNovo();
  m.ecra.iniciar();
  await assentar();
  expect(pedidos(m, 'obterLoja')).toHaveLength(1);
  expect(m.vistas).toHaveLength(vistas);
});
