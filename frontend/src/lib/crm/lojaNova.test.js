/**
 * NOVA LOJA — as regras do ecrã "Adicionar loja", sem DOM.
 *
 * Porta de public/assets/js/ecras/loja-nova.js do CRM autónomo (etiqueta
 * `referencia-standalone`), com os casos de tests/js/loja-nova.test.js:
 *   - as funções puras (`estadoGuardar`, `corpoLojaNova`,
 *     `carregarUltimaRegiao`, `guardarUltimaRegiao`), tal e qual;
 *   - o ecrã sem o DOM (`criarLojaNova`), como o seletor da T2.26: o que o
 *     autónomo escrevia no DOM é uma `vista` congelada, entregue ao
 *     `aoMudarVista`, e o `pages/crm/CrmLojaNova.js` só a desenha. Ficam aqui
 *     os casos do ecrã que não precisam de DOM nem de Leaflet (o seletor tem os
 *     seus no `seletor.test.js`): Guardar, as regiões, os erros, o duplicado,
 *     a rede e o fim do ecrã.
 *
 * Adaptações ao portal (plano T2.27):
 *   - a última região guarda-se em `crm.ultimaRegiao` (era `phc.ultimaRegiao`)
 *     e é um uuid em texto (`eUuid`), e não um inteiro positivo;
 *   - as chamadas são as do `lib/crm/api.js` (`listarRegioes`, `criarLoja`) e
 *     os erros são `ErroCrm`;
 *   - depois de gravar, o mapa abre em `<casa>/mapa?loja=<id>` com
 *     `state: {aviso: 'Loja guardada'}` (nota da T2.25): o toast é do mapa;
 *     "Sim, abrir X" abre `<casa>/lojas/<id>`;
 *   - o diálogo tem três botões ('Sim, abrir X', 'Não, é outra loja' e
 *     'Cancelar'), como no autónomo (correção "componentes Sem Jest").
 */
import { ErroCrm, MENSAGEM_ERRO_INESPERADO, MENSAGEM_SEM_REDE } from './api';
import { criarEstadoRede } from './rede';
import {
  CHAVE_ULTIMA_REGIAO,
  TEXTO_A_GUARDAR,
  TEXTO_GUARDAR,
  TEXTO_GUARDAR_SEM_REDE,
  TEXTO_LOJA_GUARDADA,
  caminhoDaFicha,
  carregarUltimaRegiao,
  corpoLojaNova,
  criarLojaNova,
  destinoDepoisDeGuardar,
  estadoGuardar,
  guardarUltimaRegiao,
  respostaAoErro,
} from './lojaNova';

const LISBOA = '3f1c2d4e-5a6b-4c7d-8e9f-0a1b2c3d4e5f';
const PORTO = '7a8b9c0d-1e2f-4a3b-9c4d-5e6f7a8b9c0d';
const SETUBAL = 'c0ffee00-0000-4000-a000-000000000099';
const MERCEARIA_DA_BAIXA = '0b6f3c1e-1111-4222-8333-444455556666';
const NOVA = '0b6f3c1e-9999-4222-8333-444455556666';

const REGIOES = [{ id: LISBOA, nome: 'Lisboa', ordem: 0 }, { id: PORTO, nome: 'Porto', ordem: 1 }];
const PINO = { lat: 38.7101, lng: -9.1402, origem_coords: 'pin_manual', precisao_m: null };
const LOJA_GRAVADA = { id: NOVA, nome: 'Mercearia Nova', fase: 'potencial', regiao_id: PORTO, lat: 38.7101, lng: -9.1402, telefone: null };

function criarArmazenamento(inicial = {}) {
  const dados = new Map(Object.entries(inicial));
  return {
    dados,
    getItem: (k) => (dados.has(k) ? dados.get(k) : null),
    setItem: (k, v) => {
      dados.set(k, String(v));
    },
    removeItem: (k) => {
      dados.delete(k);
    },
  };
}

// --- Funções puras -------------------------------------------------------------------------------

test('estadoGuardar: só com nome e localização confirmada; sem rede, desativado com "sem rede"', () => {
  const localizacao = { lat: 38.71, lng: -9.14, origem_coords: 'pin_manual', precisao_m: null };
  expect(estadoGuardar({ nome: 'Mercearia', localizacao, online: true, aGuardar: false })).toEqual({ ativo: true, texto: 'Guardar', falta: null });
  expect(estadoGuardar({ nome: '', localizacao: null, online: true, aGuardar: false })).toEqual({
    ativo: false, texto: 'Guardar', falta: 'Para guardar, escreva o nome e confirme a localização.',
  });
  expect(estadoGuardar({ nome: '   ', localizacao, online: true, aGuardar: false })).toEqual({
    ativo: false, texto: 'Guardar', falta: 'Para guardar, escreva o nome.',
  });
  expect(estadoGuardar({ nome: 'Mercearia', localizacao: null, online: true, aGuardar: false })).toEqual({
    ativo: false, texto: 'Guardar', falta: 'Para guardar, confirme a localização no mapa.',
  });
  expect(estadoGuardar({ nome: 'Mercearia', localizacao, online: false, aGuardar: false })).toEqual({
    ativo: false, texto: 'Guardar — sem rede', falta: null,
  });
  expect(estadoGuardar({ nome: '', localizacao: null, online: false, aGuardar: false }).texto).toBe('Guardar — sem rede');
  expect(estadoGuardar({ nome: 'Mercearia', localizacao, online: true, aGuardar: true })).toEqual({
    ativo: false, texto: 'A guardar…', falta: null,
  });
  expect(estadoGuardar({ nome: 7, localizacao, online: true, aGuardar: false }).ativo).toBe(false);
  // Os textos do botão, para a página (o ícone do "A guardar…").
  expect([TEXTO_GUARDAR, TEXTO_A_GUARDAR, TEXTO_GUARDAR_SEM_REDE]).toEqual(['Guardar', 'A guardar…', 'Guardar — sem rede']);
  expect(estadoGuardar({ nome: 'Mercearia', localizacao: undefined, online: true, aGuardar: false }).ativo).toBe(false);
});

test('corpoLojaNova: os campos do formulário e a localização; confirmar_duplicado só quando confirmado', () => {
  const valores = { nome: 'Mercearia', fase: 'potencial', regiao_id: null, telefone: '', pessoa_contacto: '', morada: '', codigo_postal: '', localidade: '', notas: '' };
  const localizacao = { lat: 38.71, lng: -9.14, origem_coords: 'gps', precisao_m: 20 };
  expect(corpoLojaNova(valores, localizacao)).toStrictEqual({ ...valores, ...localizacao });
  expect(corpoLojaNova(valores, localizacao, { confirmarDuplicado: true })).toStrictEqual({ ...valores, ...localizacao, confirmar_duplicado: true });
  expect(corpoLojaNova(valores, localizacao, { confirmarDuplicado: false })).not.toHaveProperty('confirmar_duplicado');
  expect(valores).not.toHaveProperty('lat');
});

test('carregarUltimaRegiao: o uuid guardado em crm.ultimaRegiao; o resto (ou um armazenamento que falha) dá null', () => {
  expect(CHAVE_ULTIMA_REGIAO).toBe('crm.ultimaRegiao');
  expect(carregarUltimaRegiao(criarArmazenamento({ 'crm.ultimaRegiao': LISBOA }))).toBe(LISBOA);
  for (const valor of ['3', '0', '-1', 'abc', '', ` ${LISBOA}`, LISBOA.toUpperCase(), `${LISBOA}\n`, 'null']) {
    expect([valor, carregarUltimaRegiao(criarArmazenamento({ 'crm.ultimaRegiao': valor }))]).toEqual([valor, null]);
  }
  expect(carregarUltimaRegiao(criarArmazenamento())).toBe(null);
  expect(carregarUltimaRegiao(criarArmazenamento({ 'phc.ultimaRegiao': LISBOA }))).toBe(null);
  expect(carregarUltimaRegiao({ getItem: () => { throw new Error('bloqueado'); } })).toBe(null);
  expect(carregarUltimaRegiao(null)).toBe(null);
});

test('guardarUltimaRegiao: guarda o uuid; sem região, esquece a anterior; nunca lança', () => {
  const storage = criarArmazenamento({ 'crm.ultimaRegiao': LISBOA });
  expect(guardarUltimaRegiao(storage, PORTO)).toBe(true);
  expect(storage.dados.get('crm.ultimaRegiao')).toBe(PORTO);
  expect(guardarUltimaRegiao(storage, null)).toBe(true);
  expect(storage.dados.has('crm.ultimaRegiao')).toBe(false);
  storage.dados.set('crm.ultimaRegiao', LISBOA);
  expect(guardarUltimaRegiao(storage, 2)).toBe(true);
  expect(storage.dados.has('crm.ultimaRegiao')).toBe(false); // um id do autónomo não é uma região do portal
  expect(guardarUltimaRegiao({ setItem: () => { throw new Error('cheio'); }, removeItem: () => {} }, PORTO)).toBe(false);
  expect(guardarUltimaRegiao(null, PORTO)).toBe(false);
});

test('respostaAoErro: o 409 duplicado com a lista abre o diálogo da loja mais perto', () => {
  const perto = { id: MERCEARIA_DA_BAIXA, nome: 'Mercearia da Baixa', distancia_m: 12 };
  const erro = new ErroCrm({ codigo: 'duplicado', mensagem: 'Já existe Mercearia da Baixa aqui — é a mesma?', estado: 409, extra: { lojas: [perto] } });
  expect(respostaAoErro(erro)).toEqual({ tipo: 'duplicado', loja: perto });
  // Sem a lista (ou sem uma loja válida nela): a mensagem do servidor, como um erro.
  for (const extra of [{}, { lojas: [] }, { lojas: [{ id: 7, nome: 'X' }] }]) {
    const semLista = new ErroCrm({ codigo: 'duplicado', mensagem: 'Já existe outra loja aqui.', estado: 409, extra });
    expect(respostaAoErro(semLista)).toEqual({ tipo: 'erro', alerta: 'Já existe outra loja aqui.' });
  }
});

test('respostaAoErro: o 422 separa os erros dos campos, o da localização e os que o formulário não tem', () => {
  const erro = new ErroCrm({
    codigo: 'validacao',
    mensagem: 'Verifique os campos assinalados.',
    estado: 422,
    campos: {
      nome: 'Indique o nome.', lat: 'Fora de Portugal', lng: 'Fora de Portugal', telefone: 'Telefone inválido.',
      janela1_inicio: 'Hora inválida.', dias_fechada: 'Há dias repetidos.',
    },
  });
  expect(respostaAoErro(erro)).toEqual({
    tipo: 'validacao',
    alerta: 'Verifique os campos assinalados. Hora inválida. Há dias repetidos.',
    erros: { nome: 'Indique o nome.', telefone: 'Telefone inválido.' },
    primeiro: 'nome',
    localizacao: 'Fora de Portugal',
  });
  const soLocalizacao = new ErroCrm({ codigo: 'validacao', mensagem: 'Verifique os campos assinalados.', estado: 422, campos: { origem_coords: 'Indique a origem das coordenadas.' } });
  expect(respostaAoErro(soLocalizacao)).toEqual({
    tipo: 'validacao', alerta: 'Verifique os campos assinalados.', erros: {}, primeiro: null, localizacao: 'Indique a origem das coordenadas.',
  });
  // A precisão do GPS também é da localização (a precisão vai com o resto do bloco).
  const precisao = new ErroCrm({ codigo: 'validacao', mensagem: 'Verifique os campos assinalados.', estado: 422, campos: { precisao_m: 'Localização imprecisa — ajuste o pino' } });
  expect(respostaAoErro(precisao).localizacao).toBe('Localização imprecisa — ajuste o pino');
});

test('respostaAoErro sem o seletor à vista (a ficha sem a correção aberta): o erro da localização vai no alerta', () => {
  const erro = new ErroCrm({
    codigo: 'validacao',
    mensagem: 'Verifique os campos assinalados.',
    estado: 422,
    campos: { lat: 'Fora de Portugal', notas: 'Notas a mais.', visita: 'Campo desconhecido.' },
  });
  // Como o `mostrarValidacao` do autónomo: a mensagem do servidor, a da localização e as dos outros campos.
  expect(respostaAoErro(erro, { ficha: true, comSeletor: false })).toEqual({
    tipo: 'validacao',
    alerta: 'Verifique os campos assinalados. Fora de Portugal Campo desconhecido.',
    erros: { notas: 'Notas a mais.' },
    primeiro: 'notas',
    localizacao: null,
  });
  expect(respostaAoErro(erro, { ficha: true }).localizacao).toBe('Fora de Portugal'); // por omissão, com o seletor
  expect(respostaAoErro(erro, { ficha: true, comSeletor: true }).alerta).toBe('Verifique os campos assinalados. Campo desconhecido.');
});

test('respostaAoErro: o resto mostra a mensagem do erro (ou a de erro inesperado)', () => {
  expect(respostaAoErro(new ErroCrm({ codigo: 'sem_rede', mensagem: MENSAGEM_SEM_REDE }))).toEqual({ tipo: 'erro', alerta: MENSAGEM_SEM_REDE });
  expect(respostaAoErro(new ErroCrm({ codigo: 'erro_interno', mensagem: '', estado: 500 }))).toEqual({ tipo: 'erro', alerta: MENSAGEM_ERRO_INESPERADO });
  expect(respostaAoErro(new Error('rebentou'))).toEqual({ tipo: 'erro', alerta: MENSAGEM_ERRO_INESPERADO });
  expect(respostaAoErro(undefined)).toEqual({ tipo: 'erro', alerta: MENSAGEM_ERRO_INESPERADO });
});

test('destinoDepoisDeGuardar: o mapa da mesma casa centrado na loja nova, com o aviso "Loja guardada"', () => {
  expect(TEXTO_LOJA_GUARDADA).toBe('Loja guardada');
  expect(destinoDepoisDeGuardar('/crm', LOJA_GRAVADA)).toEqual({
    caminho: `/crm/mapa?loja=${NOVA}`, estado: { aviso: 'Loja guardada' },
  });
  expect(destinoDepoisDeGuardar('/admin/crm', LOJA_GRAVADA).caminho).toBe(`/admin/crm/mapa?loja=${NOVA}`);
  expect(destinoDepoisDeGuardar('/crm', { id: 'a b&c/d' }).caminho).toBe('/crm/mapa?loja=a%20b%26c%2Fd');
  // Sem um id na resposta (não devia acontecer), o mapa na mesma, com o aviso.
  expect(destinoDepoisDeGuardar('/crm', {})).toEqual({ caminho: '/crm/mapa', estado: { aviso: 'Loja guardada' } });
  expect(destinoDepoisDeGuardar('/crm', null).caminho).toBe('/crm/mapa');
});

test('caminhoDaFicha: a ficha da loja na mesma casa, com o id num só pedaço do caminho', () => {
  expect(caminhoDaFicha('/crm', MERCEARIA_DA_BAIXA)).toBe(`/crm/lojas/${MERCEARIA_DA_BAIXA}`);
  expect(caminhoDaFicha('/admin/crm', MERCEARIA_DA_BAIXA)).toBe(`/admin/crm/lojas/${MERCEARIA_DA_BAIXA}`);
  expect(caminhoDaFicha('/crm', '../x')).toBe('/crm/lojas/..%2Fx');
});

// --- O ecrã --------------------------------------------------------------------------------------

// Cada pedido fica pendente até o teste lhe responder (ou o fazer falhar).
function apiFalsa() {
  const pedidos = [];
  const pedir = (nome) => (corpo) => new Promise((resolver, rejeitar) => {
    pedidos.push({ nome, corpo, resolver, rejeitar });
  });
  return { pedidos, listarRegioes: pedir('listarRegioes'), criarLoja: pedir('criarLoja') };
}

const assentar = () => new Promise((r) => {
  setTimeout(r, 0);
});

// Monta o ecrã como a página (CrmLojaNova): cria, inicia (pede as regiões e ouve a rede).
function montar({ online = true, storage = criarArmazenamento(), base = '/crm', iniciar = true } = {}) {
  const api = apiFalsa();
  const janela = new EventTarget();
  const navegador = { onLine: online };
  const navegacoes = [];
  const focos = [];
  const vistas = [];
  const seletor = [];
  let ecra = null;
  ecra = criarLojaNova({
    api,
    storage,
    rede: criarEstadoRede(janela, navegador),
    base,
    navegar: (caminho, opcoes) => navegacoes.push({ caminho, opcoes }),
    // O seletor da localização (SeletorLocalizacao pela ref): o desconfirmar avisa que a localização saiu,
    // como o verdadeiro (aoMudar(null)).
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
    aoFocar: (campo) => focos.push(campo),
  });
  if (iniciar) ecra.iniciar();
  const mudarRede = (ligado) => {
    navegador.onLine = ligado;
    janela.dispatchEvent(new Event(ligado ? 'online' : 'offline'));
  };
  return { api, ecra, storage, navegacoes, focos, vistas, seletor, mudarRede, vista: () => ecra.vista };
}

const pedidos = (m, nome) => m.api.pedidos.filter((p) => p.nome === nome);
const responderRegioes = async (m, regioes = REGIOES) => {
  pedidos(m, 'listarRegioes')[0].resolver(regioes);
  await assentar();
};

// O ecrã com as regiões carregadas, o pino confirmado e o nome escrito: pronto a guardar.
async function pronto(opcoes) {
  const m = montar(opcoes);
  await responderRegioes(m);
  m.ecra.mudarLocalizacao(PINO);
  m.ecra.mudarCampo('nome', 'Mercearia Nova');
  return m;
}

async function guardar(m) {
  m.ecra.guardar();
  await assentar();
  return pedidos(m, 'criarLoja').at(-1);
}

const erroDuplicado = (lojas = [{ id: MERCEARIA_DA_BAIXA, nome: 'Mercearia da Baixa', distancia_m: 12 }]) => new ErroCrm({
  codigo: 'duplicado',
  mensagem: `Já existe ${lojas[0]?.nome} aqui — é a mesma?`,
  estado: 409,
  extra: { lojas },
});

const erroValidacao = (campos) => new ErroCrm({ codigo: 'validacao', mensagem: 'Verifique os campos assinalados.', estado: 422, campos });

test('ao abrir: Guardar desativado com o que falta, fase Potencial, sem alerta nem diálogo', () => {
  const { vista } = montar();
  expect(vista().guardar).toEqual({ ativo: false, texto: 'Guardar', falta: 'Para guardar, escreva o nome e confirme a localização.' });
  expect(vista().valores.fase).toBe('potencial');
  expect(vista().alerta).toBe(null);
  expect(vista().duplicado).toBe(null);
  expect(vista().erros).toEqual({});
  expect(vista().valorRegiao).toBe('sem');
  expect(vista().opcoesRegiao).toEqual([{ valor: 'sem', texto: 'Sem região' }]);
});

test('criar o ecrã não pede nada; iniciar pede as regiões uma vez', () => {
  const m = montar({ iniciar: false });
  expect(m.api.pedidos).toEqual([]);
  m.ecra.iniciar();
  m.ecra.iniciar();
  expect(pedidos(m, 'listarRegioes')).toHaveLength(1);
});

test('iniciar outra vez não ouve a rede duas vezes: uma mudança da rede, uma vista nova', () => {
  const m = montar();
  m.ecra.iniciar();
  const vistas = m.vistas.length;
  m.mudarRede(false);
  expect(m.vistas).toHaveLength(vistas + 1);
});

test('a vista é nova a cada mudança, congelada, e vai para o aoMudarVista', () => {
  const m = montar();
  const antes = m.vista();
  m.ecra.mudarCampo('nome', 'M');
  expect(m.vista()).not.toBe(antes);
  expect(m.vistas.at(-1)).toBe(m.vista());
  expect(Object.isFrozen(m.vista())).toBe(true);
  expect(Object.isFrozen(m.vista().guardar)).toBe(true);
  expect(Object.isFrozen(m.vista().valores)).toBe(true);
  expect(Object.isFrozen(m.vista().erros)).toBe(true);
  expect(Object.isFrozen(m.vista().opcoesRegiao)).toBe(true);
  // Nada mudado: não há vista nova.
  const vistas = m.vistas.length;
  m.ecra.mudarCampo('nome', 'M');
  m.ecra.mudarCampo('lat', 38.7);
  expect(m.vistas).toHaveLength(vistas);
});

test('Guardar só fica ativo com o nome escrito e a localização confirmada', () => {
  const m = montar();
  m.ecra.mudarCampo('nome', 'Mercearia Nova');
  expect(m.vista().guardar.ativo).toBe(false);
  expect(m.vista().guardar.falta).toBe('Para guardar, confirme a localização no mapa.');
  m.ecra.mudarLocalizacao(PINO);
  expect(m.vista().guardar).toEqual({ ativo: true, texto: 'Guardar', falta: null });
  m.ecra.mudarCampo('nome', '   ');
  expect(m.vista().guardar.ativo).toBe(false);
  expect(m.vista().guardar.falta).toBe('Para guardar, escreva o nome.');
  m.ecra.mudarCampo('nome', 'Mercearia Nova');
  m.ecra.mudarLocalizacao(null);
  expect(m.vista().guardar.ativo).toBe(false); // a localização voltou a estar por confirmar
});

test('regiões: "Sem região" e as da API; pré-escolhe a última usada (crm.ultimaRegiao)', async () => {
  const m = montar({ storage: criarArmazenamento({ 'crm.ultimaRegiao': PORTO }) });
  expect(pedidos(m, 'listarRegioes')).toHaveLength(1);
  await responderRegioes(m);
  expect(m.vista().opcoesRegiao.map((o) => o.texto)).toEqual(['Sem região', 'Lisboa', 'Porto']);
  expect(m.vista().valorRegiao).toBe(PORTO);
  expect(m.vista().valores.regiao_id).toBe(PORTO);
});

test('regiões: a última usada que já não existe fica "Sem região"', async () => {
  const m = montar({ storage: criarArmazenamento({ 'crm.ultimaRegiao': SETUBAL }) });
  await responderRegioes(m);
  expect(m.vista().valorRegiao).toBe('sem');
  expect(m.vista().valores.regiao_id).toBe(null);
});

test('regiões que não carregam: a última usada fica escolhida ("Região guardada"), vai no POST e não se esquece', async () => {
  const m = montar({ storage: criarArmazenamento({ 'crm.ultimaRegiao': PORTO }) });
  expect(m.vista().valorRegiao).toBe(PORTO); // enquanto as regiões não chegam
  expect(m.vista().opcoesRegiao.find((o) => o.valor === PORTO).texto).toBe('Região guardada');
  pedidos(m, 'listarRegioes')[0].rejeitar(new ErroCrm({ codigo: 'erro_interno', mensagem: 'Erro inesperado — tente novamente.', estado: 500 }));
  await assentar();
  expect(m.vista().valorRegiao).toBe(PORTO);
  m.ecra.mudarLocalizacao(PINO);
  m.ecra.mudarCampo('nome', 'Mercearia Nova');
  const pedido = await guardar(m);
  expect(pedido.corpo.regiao_id).toBe(PORTO);
  pedido.resolver(LOJA_GRAVADA);
  await assentar();
  expect(m.storage.dados.get('crm.ultimaRegiao')).toBe(PORTO);
});

test('enquanto as regiões não chegam, a guardada fica na lista, mesmo depois de escolher "Sem região"', () => {
  const m = montar({ storage: criarArmazenamento({ 'crm.ultimaRegiao': PORTO }) });
  m.ecra.mudarCampo('regiao_id', null);
  expect(m.vista().valorRegiao).toBe('sem');
  expect(m.vista().opcoesRegiao).toEqual([{ valor: 'sem', texto: 'Sem região' }, { valor: PORTO, texto: 'Região guardada' }]);
  m.ecra.mudarCampo('regiao_id', PORTO);
  expect(m.vista().valorRegiao).toBe(PORTO);
});

test('regiões que chegam depois: fica a região que está escolhida (a guardada, ou a que a pessoa já mudou)', async () => {
  const guardada = montar({ storage: criarArmazenamento({ 'crm.ultimaRegiao': PORTO }) });
  await responderRegioes(guardada);
  expect(guardada.vista().valorRegiao).toBe(PORTO);
  expect(guardada.vista().opcoesRegiao.find((o) => o.valor === PORTO).texto).toBe('Porto');

  const mudada = montar({ storage: criarArmazenamento({ 'crm.ultimaRegiao': PORTO }) });
  mudada.ecra.mudarCampo('regiao_id', null);
  await responderRegioes(mudada);
  expect(mudada.vista().valorRegiao).toBe('sem'); // a pessoa escolheu "Sem região" antes de as regiões chegarem
});

test('regiões que não carregam: o erro junto à região, e tenta outra vez quando a rede volta', async () => {
  const m = montar();
  pedidos(m, 'listarRegioes')[0].rejeitar(new ErroCrm({ codigo: 'sem_rede', mensagem: MENSAGEM_SEM_REDE }));
  await assentar();
  expect(m.vista().erros).toEqual({ regiao_id: MENSAGEM_SEM_REDE });
  m.mudarRede(false);
  m.mudarRede(true);
  await assentar();
  expect(pedidos(m, 'listarRegioes')).toHaveLength(2);
  pedidos(m, 'listarRegioes')[1].resolver(REGIOES);
  await assentar();
  expect(m.vista().erros).toEqual({});
  expect(m.vista().opcoesRegiao).toHaveLength(3);
  m.mudarRede(false);
  m.mudarRede(true);
  await assentar();
  expect(pedidos(m, 'listarRegioes')).toHaveLength(2); // com as regiões carregadas não volta a pedir
});

test('regiões a caminho: a rede a voltar não faz outro pedido', async () => {
  const m = montar();
  m.mudarRede(false);
  m.mudarRede(true);
  await assentar();
  expect(pedidos(m, 'listarRegioes')).toHaveLength(1);
});

test('mudar a região tira o erro dela', async () => {
  const m = montar();
  pedidos(m, 'listarRegioes')[0].rejeitar(new ErroCrm({ codigo: 'sem_rede', mensagem: MENSAGEM_SEM_REDE }));
  await assentar();
  m.ecra.mudarCampo('regiao_id', null);
  expect(m.vista().erros).toEqual({});
});

test('guardar: criarLoja com os campos e a localização confirmada (pin_manual)', async () => {
  const m = await pronto();
  m.ecra.mudarCampo('regiao_id', PORTO);
  m.ecra.mudarCampo('fase', 'cliente');
  m.ecra.mudarCampo('telefone', '912 345 678');
  const pedido = await guardar(m);
  expect(pedido.corpo).toStrictEqual({
    nome: 'Mercearia Nova',
    fase: 'cliente',
    regiao_id: PORTO,
    telefone: '912 345 678',
    pessoa_contacto: '',
    morada: '',
    codigo_postal: '',
    localidade: '',
    notas: '',
    lat: 38.7101,
    lng: -9.1402,
    origem_coords: 'pin_manual',
    precisao_m: null,
  });
  expect(m.vista().guardar).toEqual({ ativo: false, texto: 'A guardar…', falta: null });
});

test('um toque, um pedido: Guardar outra vez enquanto guarda não envia nada', async () => {
  const m = await pronto();
  await guardar(m);
  m.ecra.guardar();
  m.ecra.guardar({ confirmarDuplicado: true });
  await assentar();
  expect(pedidos(m, 'criarLoja')).toHaveLength(1);
});

test('Enter no formulário sem nome ou sem pino não envia nada', async () => {
  const m = montar();
  await responderRegioes(m);
  m.ecra.guardar();
  m.ecra.mudarCampo('nome', 'Mercearia');
  m.ecra.guardar();
  await assentar();
  expect(pedidos(m, 'criarLoja')).toHaveLength(0);
});

test('sucesso: guarda a região usada e volta ao mapa centrado na loja nova, com "Loja guardada"', async () => {
  const m = await pronto();
  m.ecra.mudarCampo('regiao_id', PORTO);
  const pedido = await guardar(m);
  pedido.resolver(LOJA_GRAVADA);
  await assentar();
  expect(m.storage.dados.get('crm.ultimaRegiao')).toBe(PORTO);
  expect(m.navegacoes).toEqual([{ caminho: `/crm/mapa?loja=${NOVA}`, opcoes: { state: { aviso: 'Loja guardada' } } }]);
  expect(m.vista().guardar.ativo).toBe(false); // até o ecrã mudar, não há segundo envio
  m.ecra.guardar();
  await assentar();
  expect(pedidos(m, 'criarLoja')).toHaveLength(1);
});

test('sucesso na casa do admin: volta ao mapa do /admin/crm', async () => {
  const m = await pronto({ base: '/admin/crm' });
  (await guardar(m)).resolver(LOJA_GRAVADA);
  await assentar();
  expect(m.navegacoes[0].caminho).toBe(`/admin/crm/mapa?loja=${NOVA}`);
});

test('sucesso sem região: esquece a última usada (da próxima vez começa em "Sem região")', async () => {
  const m = await pronto({ storage: criarArmazenamento({ 'crm.ultimaRegiao': LISBOA }) });
  m.ecra.mudarCampo('regiao_id', null);
  const pedido = await guardar(m);
  pedido.resolver({ ...LOJA_GRAVADA, regiao_id: null });
  await assentar();
  expect(m.storage.dados.has('crm.ultimaRegiao')).toBe(false);
});

test('422: os erros junto aos campos, a mensagem do servidor por cima, e o foco no primeiro campo', async () => {
  const m = await pronto();
  const pedido = await guardar(m);
  pedido.rejeitar(erroValidacao({
    telefone: 'O telefone tem de ter 9 a 15 algarismos (aceita + e espaços).', codigo_postal: 'O código postal tem de ter o formato 0000-000.',
  }));
  await assentar();
  expect(m.vista().alerta).toBe('Verifique os campos assinalados.');
  expect(m.vista().erros).toEqual({
    telefone: 'O telefone tem de ter 9 a 15 algarismos (aceita + e espaços).', codigo_postal: 'O código postal tem de ter o formato 0000-000.',
  });
  expect(m.focos).toEqual(['telefone']);
  expect(m.vista().guardar).toEqual({ ativo: true, texto: 'Guardar', falta: null }); // pode corrigir e guardar outra vez
  // Escrever no campo com erro tira o erro dele.
  m.ecra.mudarCampo('telefone', '912345678');
  expect(m.vista().erros).toEqual({ codigo_postal: 'O código postal tem de ter o formato 0000-000.' });
});

test('422 na localização (ex.: "Fora de Portugal"): o erro no seletor e o pino volta a soltar-se', async () => {
  const m = await pronto();
  const pedido = await guardar(m);
  m.seletor.length = 0;
  pedido.rejeitar(erroValidacao({ lat: 'Fora de Portugal', lng: 'Fora de Portugal' }));
  await assentar();
  expect(m.seletor).toEqual([['desconfirmar'], ['mostrarErro', 'Fora de Portugal'], ['focar']]);
  expect(m.focos).toEqual([]); // o foco vai para o seletor (Confirmar localização)
  expect(m.vista().guardar.ativo).toBe(false); // falta confirmar a localização outra vez
  expect(m.vista().alerta).toBe('Verifique os campos assinalados.');
});

test('422 num campo que o formulário não tem: a mensagem dele junta-se à de cima', async () => {
  const m = await pronto();
  (await guardar(m)).rejeitar(erroValidacao({ janela1_inicio: 'Hora inválida.' }));
  await assentar();
  expect(m.vista().alerta).toBe('Verifique os campos assinalados. Hora inválida.');
  expect(m.focos).toEqual([]);
});

test('uma segunda tentativa limpa os erros da anterior (também o do seletor)', async () => {
  const m = await pronto();
  (await guardar(m)).rejeitar(erroValidacao({ notas: 'As notas são demasiado compridas.' }));
  await assentar();
  m.seletor.length = 0;
  await guardar(m);
  expect(m.vista().alerta).toBe(null);
  expect(m.vista().erros).toEqual({});
  expect(m.seletor).toEqual([['limparErro']]);
});

test('409 duplicado: "Já existe X aqui — é a mesma?" com "Sim, abrir X", "Não, é outra loja" e Cancelar', async () => {
  const m = await pronto();
  (await guardar(m)).rejeitar(erroDuplicado());
  await assentar();
  const { duplicado } = m.vista();
  expect(duplicado.loja).toEqual({ id: MERCEARIA_DA_BAIXA, nome: 'Mercearia da Baixa', distancia_m: 12 });
  expect(duplicado.mensagem.map((p) => p.texto).join('')).toBe('Já existe Mercearia da Baixa aqui — é a mesma?');
  expect(duplicado.mensagem.filter((p) => p.forte).map((p) => p.texto)).toEqual(['Mercearia da Baixa']);
  expect(duplicado.botoes.map((b) => b.texto)).toEqual(['Sim, abrir Mercearia da Baixa', 'Não, é outra loja', 'Cancelar']);
  expect(m.vista().alerta).toBe(null); // a pergunta está no diálogo
  expect(m.vista().guardar).toEqual({ ativo: true, texto: 'Guardar', falta: null });
});

test('duplicado → "Sim, abrir X" abre a ficha dessa loja e não grava', async () => {
  const m = await pronto();
  (await guardar(m)).rejeitar(erroDuplicado());
  await assentar();
  m.ecra.responder('abrir');
  await assentar();
  expect(m.navegacoes).toEqual([{ caminho: `/crm/lojas/${MERCEARIA_DA_BAIXA}`, opcoes: undefined }]);
  expect(pedidos(m, 'criarLoja')).toHaveLength(1);
  expect(m.vista().duplicado).toBe(null);
});

test('duplicado → "Não, é outra loja" volta a enviar com confirmar_duplicado e grava', async () => {
  const m = await pronto();
  const primeiro = await guardar(m);
  primeiro.rejeitar(erroDuplicado());
  await assentar();
  m.ecra.responder('outra');
  await assentar();
  const enviados = pedidos(m, 'criarLoja');
  expect(enviados).toHaveLength(2);
  expect(enviados[1].corpo).toStrictEqual({ ...primeiro.corpo, confirmar_duplicado: true });
  expect(primeiro.corpo).not.toHaveProperty('confirmar_duplicado');
  expect(m.vista().duplicado).toBe(null);
  expect(m.vista().guardar.texto).toBe('A guardar…');
  enviados[1].resolver(LOJA_GRAVADA);
  await assentar();
  expect(m.navegacoes).toEqual([{ caminho: `/crm/mapa?loja=${NOVA}`, opcoes: { state: { aviso: 'Loja guardada' } } }]);
});

test('duplicado → Cancelar (ou Escape) fecha o diálogo, não envia nada e deixa guardar outra vez', async () => {
  const m = await pronto();
  (await guardar(m)).rejeitar(erroDuplicado());
  await assentar();
  m.ecra.responder(null);
  await assentar();
  expect(m.vista().duplicado).toBe(null);
  expect(pedidos(m, 'criarLoja')).toHaveLength(1);
  expect(m.navegacoes).toEqual([]);
  expect(m.vista().guardar.ativo).toBe(true);
});

test('duplicado: só conta a primeira resposta, e responder sem diálogo não faz nada', async () => {
  const m = await pronto();
  m.ecra.responder('outra');
  await assentar();
  expect(pedidos(m, 'criarLoja')).toHaveLength(0);
  (await guardar(m)).rejeitar(erroDuplicado());
  await assentar();
  m.ecra.responder('abrir');
  m.ecra.responder('outra');
  await assentar();
  expect(pedidos(m, 'criarLoja')).toHaveLength(1);
  expect(m.navegacoes).toHaveLength(1);
});

test('duplicado de uma loja chamada <b>x</b>: o nome fica em texto', async () => {
  const m = await pronto();
  (await guardar(m)).rejeitar(erroDuplicado([{ id: MERCEARIA_DA_BAIXA, nome: '<b>x</b>', distancia_m: 3 }]));
  await assentar();
  const { duplicado } = m.vista();
  expect(duplicado.mensagem.map((p) => p.texto).join('')).toBe('Já existe <b>x</b> aqui — é a mesma?');
  expect(duplicado.botoes[0].texto).toBe('Sim, abrir <b>x</b>');
});

test('duplicado sem a lista de lojas: mostra a mensagem do servidor como um erro', async () => {
  const m = await pronto();
  (await guardar(m)).rejeitar(new ErroCrm({ codigo: 'duplicado', mensagem: 'Já existe outra loja aqui.', estado: 409, extra: {} }));
  await assentar();
  expect(m.vista().duplicado).toBe(null);
  expect(m.vista().alerta).toBe('Já existe outra loja aqui.');
});

test('sem rede: Guardar desativado com "sem rede"; volta quando a rede volta', async () => {
  const m = await pronto();
  m.mudarRede(false);
  expect(m.vista().guardar).toEqual({ ativo: false, texto: 'Guardar — sem rede', falta: null });
  m.ecra.guardar();
  await assentar();
  expect(pedidos(m, 'criarLoja')).toHaveLength(0);
  m.mudarRede(true);
  expect(m.vista().guardar).toEqual({ ativo: true, texto: 'Guardar', falta: null });
});

test('a abrir sem rede: Guardar já começa com "sem rede"', () => {
  expect(montar({ online: false }).vista().guardar.texto).toBe('Guardar — sem rede');
});

test('o pedido falha por falta de rede: a mensagem de sem rede e pode tentar outra vez', async () => {
  const m = await pronto();
  (await guardar(m)).rejeitar(new ErroCrm({ codigo: 'sem_rede', mensagem: MENSAGEM_SEM_REDE }));
  await assentar();
  expect(m.vista().alerta).toBe(MENSAGEM_SEM_REDE);
  expect(m.vista().guardar.ativo).toBe(true);
});

test('outro erro do servidor: a mensagem dele por cima do formulário', async () => {
  const m = await pronto();
  (await guardar(m)).rejeitar(new ErroCrm({ codigo: 'erro_interno', mensagem: 'Erro inesperado — tente novamente.', estado: 500 }));
  await assentar();
  expect(m.vista().alerta).toBe('Erro inesperado — tente novamente.');
});

test('depois de sair do ecrã: as respostas que chegam tarde não fazem nada', async () => {
  const m = await pronto();
  const pedido = await guardar(m);
  const vistas = m.vistas.length;
  m.ecra.destruir();
  pedido.resolver(LOJA_GRAVADA);
  await assentar();
  expect(m.navegacoes).toEqual([]);
  expect(m.storage.dados.has('crm.ultimaRegiao')).toBe(false);
  expect(m.vistas).toHaveLength(vistas);
});

test('depois de sair do ecrã: um erro que chega tarde, ou as regiões, também não', async () => {
  const m = montar();
  m.ecra.mudarLocalizacao(PINO);
  m.ecra.mudarCampo('nome', 'Mercearia Nova');
  const pedido = await guardar(m);
  const vistas = m.vistas.length;
  m.ecra.destruir();
  pedido.rejeitar(erroValidacao({ lat: 'Fora de Portugal' }));
  pedidos(m, 'listarRegioes')[0].resolver(REGIOES);
  await assentar();
  expect(m.vistas).toHaveLength(vistas);
  expect(m.seletor.filter(([nome]) => nome !== 'limparErro')).toEqual([]);
  expect(m.focos).toEqual([]);
});

test('depois de sair do ecrã com o diálogo aberto: o diálogo fecha e já não envia nada', async () => {
  const m = await pronto();
  (await guardar(m)).rejeitar(erroDuplicado());
  await assentar();
  m.ecra.destruir();
  expect(m.ecra.vista.duplicado).toBe(null);
  m.ecra.responder('outra');
  m.ecra.responder('abrir');
  await assentar();
  expect(pedidos(m, 'criarLoja')).toHaveLength(1);
  expect(m.navegacoes).toEqual([]);
});

test('destruir deixa de ouvir a rede (o ouvinte sai)', () => {
  const ouvintes = new Set();
  const rede = {
    online: () => true,
    aoMudar(ouvinte) {
      ouvintes.add(ouvinte);
      return () => ouvintes.delete(ouvinte);
    },
  };
  const ecra = criarLojaNova({ api: apiFalsa(), storage: criarArmazenamento(), rede, base: '/crm' });
  expect(ouvintes.size).toBe(0); // criar não ouve nada
  ecra.iniciar();
  expect(ouvintes.size).toBe(1);
  ecra.destruir();
  expect(ouvintes.size).toBe(0);
});

test('depois de sair do ecrã: mudar a rede ou os campos já não mexe no ecrã', async () => {
  const m = montar();
  pedidos(m, 'listarRegioes')[0].rejeitar(new ErroCrm({ codigo: 'sem_rede', mensagem: MENSAGEM_SEM_REDE }));
  await assentar();
  m.ecra.destruir();
  const vistas = m.vistas.length;
  m.mudarRede(false);
  m.mudarRede(true);
  m.ecra.mudarCampo('nome', 'X');
  m.ecra.mudarLocalizacao(PINO);
  m.ecra.iniciar();
  await assentar();
  expect(pedidos(m, 'listarRegioes')).toHaveLength(1);
  expect(m.vistas).toHaveLength(vistas); // o ouvinte da rede foi cancelado
});

// --- Pesquisa de morada (E6) e "Estou nesta loja" (E7): a morada nos campos ------------------------

const AUGUSTA_24 = { rotulo: 'Rua Augusta 24, 1100-048 Lisboa, Portugal', morada: 'Rua Augusta 24', codigo_postal: '1100-048', localidade: 'Lisboa', lat: 38.70921, lng: -9.13712 };
const PRACA = { rotulo: 'Praça do Comércio, 1100-148 Lisboa, Portugal', morada: 'Praça do Comércio', codigo_postal: '1100-148', localidade: 'Lisboa', lat: 38.70749, lng: -9.13648 };

test('escolher uma morada: preenche a morada, o código postal e a localidade; o nome fica por escrever', async () => {
  const m = montar();
  await responderRegioes(m);
  m.ecra.mudarCampo('morada', 'escrita à mão');
  m.ecra.escolherMorada(AUGUSTA_24);
  expect(m.vista().valores).toMatchObject({ morada: 'Rua Augusta 24', codigo_postal: '1100-048', localidade: 'Lisboa', nome: '' });
  expect(m.vista().guardar.ativo).toBe(false); // a localização ainda não está confirmada
  expect(m.vista().guardar.falta).toBe('Para guardar, escreva o nome e confirme a localização.');
});

test('morada escolhida, pino confirmado e nome: guarda com origem geocoder e a morada da sugestão', async () => {
  const m = montar();
  await responderRegioes(m);
  m.ecra.escolherMorada(AUGUSTA_24);
  m.ecra.mudarLocalizacao({ lat: 38.70921, lng: -9.13712, origem_coords: 'geocoder', precisao_m: null });
  m.ecra.mudarCampo('nome', 'Mercearia Augusta');
  const pedido = await guardar(m);
  expect(pedido.corpo).toStrictEqual({
    nome: 'Mercearia Augusta',
    fase: 'potencial',
    regiao_id: null,
    telefone: '',
    pessoa_contacto: '',
    morada: 'Rua Augusta 24',
    codigo_postal: '1100-048',
    localidade: 'Lisboa',
    notas: '',
    lat: 38.70921,
    lng: -9.13712,
    origem_coords: 'geocoder',
    precisao_m: null,
  });
});

test('GPS: a morada sugerida preenche só os campos vazios e guarda com origem gps', async () => {
  const m = montar();
  await responderRegioes(m);
  m.ecra.mudarCampo('morada', 'Rua do Ouro 3, loja');
  m.ecra.sugerirMorada(PRACA);
  expect(m.vista().valores).toMatchObject({ morada: 'Rua do Ouro 3, loja', codigo_postal: '1100-148', localidade: 'Lisboa', nome: '' });
  m.ecra.mudarLocalizacao({ lat: 38.7075, lng: -9.1364, origem_coords: 'gps', precisao_m: 12 });
  m.ecra.mudarCampo('nome', 'Mercearia do Comércio');
  const pedido = await guardar(m);
  expect(pedido.corpo).toStrictEqual({
    nome: 'Mercearia do Comércio',
    fase: 'potencial',
    regiao_id: null,
    telefone: '',
    pessoa_contacto: '',
    morada: 'Rua do Ouro 3, loja',
    codigo_postal: '1100-148',
    localidade: 'Lisboa',
    notas: '',
    lat: 38.7075,
    lng: -9.1364,
    origem_coords: 'gps',
    precisao_m: 12,
  });
});

test('a morada que a app pôs tira os erros desses campos', async () => {
  const m = await pronto();
  (await guardar(m)).rejeitar(erroValidacao({ codigo_postal: 'O código postal tem de ter o formato 0000-000.', telefone: 'Telefone inválido.' }));
  await assentar();
  m.ecra.escolherMorada(AUGUSTA_24);
  expect(m.vista().erros).toEqual({ telefone: 'Telefone inválido.' });
});
