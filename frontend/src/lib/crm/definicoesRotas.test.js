/**
 * DEFINIÇÕES › ROTAS — as regras do separador "Rotas", sem DOM (plano F3 T3.34; a página é da T3.41).
 *
 * As 6 definições das rotas do `GET`/`PATCH /api/crm/definicoes` (só o admin; plano F3 §1 "Definições do
 * CRM"): a hora de saída e a hora limite de regresso de cada rota nova ("HH:MM") e o tempo de serviço de
 * cada motivo (minutos inteiros de 1 a 240). O controlador (`criarDefinicoesRotas`, no molde do
 * `criarFabrica`) mostra os 6 campos, grava só o que mudou (`corpoDefinicoesRotas`, os minutos como
 * inteiros), avisa "Definições das rotas guardadas." e põe o 422 junto de cada campo (também a coerência
 * das horas, que o servidor põe no regresso). As chaves da fábrica nunca vão: são do separador "Fábrica".
 */
import fs from 'fs';
import path from 'path';

import { ErroCrm, MENSAGEM_ERRO_INESPERADO, MENSAGEM_SEM_REDE } from './api';
import {
  CAMPOS_ROTAS,
  CHAVES_HORAS,
  CHAVES_MINUTOS,
  TEMPO_SERVICO_MAXIMO,
  TEMPO_SERVICO_MINIMO,
  TEXTO_A_CARREGAR_ROTAS,
  TEXTO_A_GUARDAR,
  TEXTO_AJUDA_TEMPO_SERVICO,
  TEXTO_DESCRICAO_ROTAS,
  TEXTO_GUARDAR,
  TEXTO_ROTAS_GUARDADAS,
  TEXTO_TEMPO_SERVICO,
  TITULO_ROTAS,
  corpoDefinicoesRotas,
  criarDefinicoesRotas,
  estadoGuardarRotas,
} from './definicoesRotas';
import { TEXTO_A_GUARDAR as A_GUARDAR_FABRICA, TEXTO_GUARDAR as GUARDAR_FABRICA } from './fabrica';
import { criarEstadoRede } from './rede';
import { MOTIVOS } from './rota';

// frontend/src/lib/crm → raiz do repositório.
const RAIZ = path.join(__dirname, '..', '..', '..', '..');
const DEFINICOES_PY = path.join(RAIZ, 'backend', 'crm', 'dominio', 'definicoes.py');
const VALIDADOR_ROTA_PY = path.join(RAIZ, 'backend', 'crm', 'dominio', 'validador_rota.py');

// O `GET /definicoes` (as 9 chaves; os minutos como inteiros).
const DEFINICOES = Object.freeze({
  fabrica_morada: 'Rua da Fábrica 1, Lisboa',
  fabrica_lat: 38.7223,
  fabrica_lng: -9.1393,
  rota_hora_saida: '08:00',
  rota_hora_regresso: '19:00',
  servico_entrega_min: 10,
  servico_amostra_min: 10,
  servico_acompanhamento_min: 15,
  servico_angariacao_min: 15,
});
// Os valores dos campos, como o ecrã os escreve (texto).
const VALORES = Object.freeze({
  rota_hora_saida: '08:00',
  rota_hora_regresso: '19:00',
  servico_entrega_min: '10',
  servico_amostra_min: '10',
  servico_acompanhamento_min: '15',
  servico_angariacao_min: '15',
});

const copia = (valor) => JSON.parse(JSON.stringify(valor));

function congeladaAFundo(valor) {
  if (valor === null || typeof valor !== 'object') return true;
  if (!Object.isFrozen(valor)) return false;
  return Object.values(valor).every(congeladaAFundo);
}

// --- Textos e campos -------------------------------------------------------------------------------

test('os textos exatos do separador', () => {
  expect(TITULO_ROTAS).toBe('Rotas');
  expect(TEXTO_DESCRICAO_ROTAS).toBe(
    'As horas de cada rota nova e o tempo de serviço de cada paragem nova, por motivo. O que já está planeado não muda.',
  );
  expect(TEXTO_A_CARREGAR_ROTAS).toBe('A carregar as definições das rotas…');
  expect(TEXTO_ROTAS_GUARDADAS).toBe('Definições das rotas guardadas.');
  expect(TEXTO_TEMPO_SERVICO).toBe('Tempo de serviço (min)');
  // A ajuda do grupo dos tempos (T3.41): os limites são os do servidor.
  expect(TEXTO_AJUDA_TEMPO_SERVICO).toBe('Minutos em cada paragem nova, de 1 a 240.');
  // Os mesmos do botão da fábrica.
  expect([TEXTO_GUARDAR, TEXTO_A_GUARDAR]).toEqual(['Guardar', 'A guardar…']);
  expect([TEXTO_GUARDAR, TEXTO_A_GUARDAR]).toEqual([GUARDAR_FABRICA, A_GUARDAR_FABRICA]);
});

test('os 6 campos, pela ordem do ecrã: as duas horas e o tempo de serviço de cada motivo', () => {
  expect(CAMPOS_ROTAS).toEqual([
    { chave: 'rota_hora_saida', rotulo: 'Hora de saída', tipo: 'time', grupo: null, min: null, max: null },
    { chave: 'rota_hora_regresso', rotulo: 'Hora limite de regresso', tipo: 'time', grupo: null, min: null, max: null },
    { chave: 'servico_entrega_min', rotulo: 'Entrega', tipo: 'number', grupo: 'Tempo de serviço (min)', min: 1, max: 240 },
    { chave: 'servico_amostra_min', rotulo: 'Amostra', tipo: 'number', grupo: 'Tempo de serviço (min)', min: 1, max: 240 },
    { chave: 'servico_acompanhamento_min', rotulo: 'Acompanhamento', tipo: 'number', grupo: 'Tempo de serviço (min)', min: 1, max: 240 },
    { chave: 'servico_angariacao_min', rotulo: 'Angariação', tipo: 'number', grupo: 'Tempo de serviço (min)', min: 1, max: 240 },
  ]);
  expect(congeladaAFundo(CAMPOS_ROTAS)).toBe(true);
  expect([...CHAVES_HORAS]).toEqual(['rota_hora_saida', 'rota_hora_regresso']);
  // Um tempo por motivo, pela ordem dos MOTIVOS.
  expect([...CHAVES_MINUTOS]).toEqual(MOTIVOS.map((motivo) => `servico_${motivo}_min`));
  expect(Object.isFrozen(CHAVES_HORAS) && Object.isFrozen(CHAVES_MINUTOS)).toBe(true);
  expect([TEMPO_SERVICO_MINIMO, TEMPO_SERVICO_MAXIMO]).toEqual([1, 240]);
});

describe('igual ao servidor, lido dos próprios ficheiros', () => {
  // Falha, e não salta, se o ficheiro não estiver lá.
  const ler = (ficheiro) => {
    expect(fs.existsSync(ficheiro)).toBe(true);
    return fs.readFileSync(ficheiro, 'utf8');
  };
  const tuplo = (texto, nome) => {
    const linhas = [...texto.matchAll(new RegExp(`^${nome} = \\(([^)\\n]*)\\)$`, 'gm'))];
    expect(linhas).toHaveLength(1);
    return [...linhas[0][1].matchAll(/"([^"]*)"/g)].map((m) => m[1]);
  };
  const inteiro = (texto, nome) => {
    const linhas = [...texto.matchAll(new RegExp(`^${nome} = ([0-9]+)$`, 'gm'))];
    expect(linhas).toHaveLength(1);
    return Number(linhas[0][1]);
  };

  test('as chaves das horas e dos minutos são as HORAS e os MINUTOS do dominio/definicoes.py, pela mesma ordem', () => {
    const texto = ler(DEFINICOES_PY);
    expect([...CHAVES_HORAS]).toEqual(tuplo(texto, 'HORAS'));
    expect([...CHAVES_MINUTOS]).toEqual(tuplo(texto, 'MINUTOS'));
  });

  test('os limites do tempo de serviço são os do dominio/validador_rota.py', () => {
    const texto = ler(VALIDADOR_ROTA_PY);
    expect(TEMPO_SERVICO_MINIMO).toBe(inteiro(texto, 'TEMPO_SERVICO_MINIMO'));
    expect(TEMPO_SERVICO_MAXIMO).toBe(inteiro(texto, 'TEMPO_SERVICO_MAXIMO'));
  });
});

// --- Funções puras ---------------------------------------------------------------------------------

describe('corpoDefinicoesRotas(original, valores): só o que mudou', () => {
  test('sem alterações, nada', () => {
    expect(corpoDefinicoesRotas(DEFINICOES, VALORES)).toStrictEqual({});
    // Espaços nas pontas e zeros à esquerda não são alterações.
    expect(corpoDefinicoesRotas(DEFINICOES, { ...VALORES, rota_hora_saida: ' 08:00 ', servico_entrega_min: ' 010 ' })).toStrictEqual({});
  });

  test('as horas em texto, aparadas', () => {
    expect(corpoDefinicoesRotas(DEFINICOES, { ...VALORES, rota_hora_saida: '07:30' })).toStrictEqual({ rota_hora_saida: '07:30' });
    expect(corpoDefinicoesRotas(DEFINICOES, { ...VALORES, rota_hora_regresso: ' 18:45 ' })).toStrictEqual({ rota_hora_regresso: '18:45' });
    // Vazia ou mal escrita vai como está: o servidor diz porquê (422 junto do campo).
    expect(corpoDefinicoesRotas(DEFINICOES, { ...VALORES, rota_hora_saida: '' })).toStrictEqual({ rota_hora_saida: '' });
    expect(corpoDefinicoesRotas(DEFINICOES, { ...VALORES, rota_hora_saida: '7h30' })).toStrictEqual({ rota_hora_saida: '7h30' });
    // Só algarismos numa hora não passa a número (só os minutos passam).
    expect(corpoDefinicoesRotas(DEFINICOES, { ...VALORES, rota_hora_saida: '0730' })).toStrictEqual({ rota_hora_saida: '0730' });
  });

  test('os minutos como inteiros', () => {
    expect(corpoDefinicoesRotas(DEFINICOES, { ...VALORES, servico_entrega_min: '12' })).toStrictEqual({ servico_entrega_min: 12 });
    expect(corpoDefinicoesRotas(DEFINICOES, { ...VALORES, servico_angariacao_min: ' 0020 ' })).toStrictEqual({ servico_angariacao_min: 20 });
    expect(corpoDefinicoesRotas(DEFINICOES, { ...VALORES, servico_amostra_min: 25 })).toStrictEqual({ servico_amostra_min: 25 });
    // Fora dos limites também vai (o servidor recusa com a mensagem dele).
    expect(corpoDefinicoesRotas(DEFINICOES, { ...VALORES, servico_amostra_min: '0' })).toStrictEqual({ servico_amostra_min: 0 });
    expect(corpoDefinicoesRotas(DEFINICOES, { ...VALORES, servico_amostra_min: '241' })).toStrictEqual({ servico_amostra_min: 241 });
  });

  test('um tempo que não é um inteiro escrito com algarismos vai como está (o 422 diz porquê)', () => {
    for (const valor of ['', 'abc', '1.5', '1e2', '-5', '+5', '1 5', '١٥']) {
      expect(corpoDefinicoesRotas(DEFINICOES, { ...VALORES, servico_entrega_min: valor })).toStrictEqual({ servico_entrega_min: valor.trim() });
    }
    expect(corpoDefinicoesRotas(DEFINICOES, { ...VALORES, servico_entrega_min: 12.5 })).toStrictEqual({ servico_entrega_min: 12.5 });
    expect(corpoDefinicoesRotas(DEFINICOES, { ...VALORES, servico_entrega_min: null })).toStrictEqual({ servico_entrega_min: null });
    // Só um texto passa a número (uma lista com algarismos não).
    expect(corpoDefinicoesRotas(DEFINICOES, { ...VALORES, servico_entrega_min: ['12'] })).toStrictEqual({ servico_entrega_min: ['12'] });
  });

  test('várias alterações, pela ordem dos campos; as chaves da fábrica e as desconhecidas nunca vão', () => {
    const corpo = corpoDefinicoesRotas(DEFINICOES, {
      servico_angariacao_min: '20',
      fabrica_morada: 'Outra',
      rota_hora_regresso: '18:00',
      fabrica_lat: 39,
      servico_entrega_min: '5',
      outra: 'x',
      rota_hora_saida: '07:00',
    });
    expect(corpo).toStrictEqual({ rota_hora_saida: '07:00', rota_hora_regresso: '18:00', servico_entrega_min: 5, servico_angariacao_min: 20 });
    expect(Object.keys(corpo)).toEqual(['rota_hora_saida', 'rota_hora_regresso', 'servico_entrega_min', 'servico_angariacao_min']);
  });

  test('um campo em falta (ou undefined) não é uma alteração; nada do que recebe muda', () => {
    expect(corpoDefinicoesRotas(DEFINICOES, {})).toStrictEqual({});
    expect(corpoDefinicoesRotas(DEFINICOES, { rota_hora_saida: undefined, servico_entrega_min: undefined })).toStrictEqual({});
    const original = copia(DEFINICOES);
    const valores = { ...VALORES, rota_hora_saida: ' 07:00 ' };
    const antes = [copia(original), copia(valores)];
    corpoDefinicoesRotas(original, valores);
    expect([original, valores]).toEqual(antes);
  });
});

test('estadoGuardarRotas: a guardar → sem alterações → pronto', () => {
  expect(estadoGuardarRotas({ alterada: true, aGuardar: true })).toEqual({ ativo: false, texto: 'A guardar…', falta: null });
  expect(estadoGuardarRotas({ alterada: false, aGuardar: false })).toEqual({ ativo: false, texto: 'Guardar', falta: 'Sem alterações por guardar.' });
  expect(estadoGuardarRotas({ alterada: true, aGuardar: false })).toEqual({ ativo: true, texto: 'Guardar', falta: null });
});

// --- O ecrã -----------------------------------------------------------------------------------------

function apiFalsa() {
  const pedidos = [];
  const pedir = (nome) => (...argumentos) => new Promise((resolver, rejeitar) => {
    pedidos.push({ nome, argumentos, resolver, rejeitar });
  });
  return { pedidos, obterDefinicoes: pedir('obterDefinicoes'), alterarDefinicoes: pedir('alterarDefinicoes') };
}

const assentar = () => new Promise((r) => {
  setTimeout(r, 0);
});

// Monta o separador como a página (T3.41): cria e inicia (pede as definições e ouve a rede).
function montar({ iniciar = true } = {}) {
  const api = apiFalsa();
  const janela = new EventTarget();
  const navegador = { onLine: true };
  const avisos = [];
  const focos = [];
  const vistas = [];
  const ecra = criarDefinicoesRotas({
    api,
    rede: criarEstadoRede(janela, navegador),
    aoMudarVista: (vista) => vistas.push(vista),
    aoAvisar: (texto) => avisos.push(texto),
    aoFocar: (alvo) => focos.push(alvo),
  });
  if (iniciar) ecra.iniciar();
  const mudarRede = (ligado) => {
    navegador.onLine = ligado;
    janela.dispatchEvent(new Event(ligado ? 'online' : 'offline'));
  };
  return { api, ecra, avisos, focos, vistas, mudarRede, vista: () => ecra.vista };
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

async function carregadas(definicoes = DEFINICOES) {
  const m = montar();
  await responder(m, 'obterDefinicoes', copia(definicoes));
  return m;
}

const erroSemRede = () => new ErroCrm({ codigo: 'sem_rede', mensagem: MENSAGEM_SEM_REDE });
const erroValidacao = (campos) => new ErroCrm({ codigo: 'validacao', mensagem: 'Verifique os campos assinalados.', estado: 422, campos });
const SEM_ALTERACOES = { ativo: false, texto: 'Guardar', falta: 'Sem alterações por guardar.' };
const PRONTO = { ativo: true, texto: 'Guardar', falta: null };
const valoresDa = (m) => Object.fromEntries(m.vista().campos.map((c) => [c.chave, c.valor]));
const errosDa = (m) => Object.fromEntries(m.vista().campos.map((c) => [c.chave, c.erro]));
const SEM_ERROS = Object.freeze(Object.fromEntries(Object.keys(VALORES).map((chave) => [chave, null])));

test('criar não pede nada; iniciar pede as definições (uma vez)', () => {
  const m = montar({ iniciar: false });
  expect(m.api.pedidos).toEqual([]);
  // "Tentar novamente" só depois de uma falha.
  m.ecra.tentarDeNovo();
  expect(m.api.pedidos).toEqual([]);
  m.ecra.iniciar();
  m.ecra.iniciar();
  expect(m.api.pedidos.map((p) => [p.nome, p.argumentos])).toEqual([['obterDefinicoes', []]]);
});

test('iniciar outra vez (também depois de uma falha) não pede nem ouve a rede de novo', async () => {
  const ouvidos = [];
  const api = apiFalsa();
  const ecra = criarDefinicoesRotas({ api, rede: { online: () => true, aoMudar: (f) => { ouvidos.push(f); return () => {}; } } });
  ecra.iniciar();
  api.pedidos[0].rejeitar(erroSemRede());
  await assentar();
  ecra.iniciar();
  expect(api.pedidos).toHaveLength(1);
  expect(ouvidos).toHaveLength(1);
});

test('a carregar: sem campos, congelada; cada mudança vai para o aoMudarVista', () => {
  const m = montar();
  const vista = m.vista();
  expect(Object.keys(vista)).toEqual(['estado', 'falha', 'campos', 'camposDesativados', 'alerta', 'guardar']);
  expect(vista).toEqual({
    estado: 'a_carregar', falha: null, campos: [], camposDesativados: false, alerta: null, guardar: SEM_ALTERACOES,
  });
  expect(congeladaAFundo(vista)).toBe(true);
  expect(m.vistas.at(-1)).toBe(vista);
});

test('com as definições: os 6 campos com os valores em texto (os minutos também) e Guardar desligado', async () => {
  const m = await carregadas();
  const vista = m.vista();
  expect(vista.estado).toBe('pronto');
  expect(vista.campos).toEqual(CAMPOS_ROTAS.map((campo) => ({ ...campo, valor: VALORES[campo.chave], erro: null })));
  expect(Object.keys(vista.campos[0])).toEqual(['chave', 'rotulo', 'tipo', 'grupo', 'min', 'max', 'valor', 'erro']);
  expect(vista.guardar).toEqual(SEM_ALTERACOES);
  expect(congeladaAFundo(vista)).toBe(true);
  expect(m.vistas.at(-1)).toBe(vista);
});

test('as definições não carregam: a mensagem e "Tentar novamente" (um toque, um pedido)', async () => {
  const m = montar();
  await falhar(m, 'obterDefinicoes', erroSemRede());
  expect(m.vista().estado).toBe('falha');
  expect(m.vista().falha).toEqual({ mensagem: MENSAGEM_SEM_REDE, aTentar: false });
  expect(m.vista().campos).toEqual([]);
  m.ecra.tentarDeNovo();
  m.ecra.tentarDeNovo();
  expect(pedidos(m, 'obterDefinicoes')).toHaveLength(2);
  expect(m.vista().falha.aTentar).toBe(true);
  await responder(m, 'obterDefinicoes', copia(DEFINICOES));
  expect(m.vista().estado).toBe('pronto');
  m.ecra.tentarDeNovo();
  expect(pedidos(m, 'obterDefinicoes')).toHaveLength(2);
});

test('o 403 de quem não é admin mostra a mensagem do servidor', async () => {
  const m = montar();
  await falhar(m, 'obterDefinicoes', new ErroCrm({ codigo: 'sem_permissao', mensagem: 'Só o administrador do CRM.', estado: 403 }));
  expect(m.vista().falha.mensagem).toBe('Só o administrador do CRM.');
});

test('uma resposta sem as 6 definições das rotas certas dá o erro inesperado', async () => {
  const estragadas = [
    null,
    [],
    { fabrica_morada: '', fabrica_lat: 38.7, fabrica_lng: -9.1 },
    { ...DEFINICOES, rota_hora_saida: 8 },
    { ...DEFINICOES, rota_hora_regresso: null },
    { ...DEFINICOES, servico_entrega_min: '10' },
    { ...DEFINICOES, servico_angariacao_min: 15.5 },
    { ...DEFINICOES, servico_amostra_min: undefined },
  ];
  for (const resposta of estragadas) {
    const m = montar();
    await responder(m, 'obterDefinicoes', resposta);
    expect(m.vista().estado).toBe('falha');
    expect(m.vista().falha.mensagem).toBe(MENSAGEM_ERRO_INESPERADO);
  }
});

test('a rede que volta pede outra vez as definições que falharam (e só essas)', async () => {
  const m = montar();
  await falhar(m, 'obterDefinicoes', erroSemRede());
  m.mudarRede(false);
  expect(pedidos(m, 'obterDefinicoes')).toHaveLength(1);
  m.mudarRede(true);
  expect(pedidos(m, 'obterDefinicoes')).toHaveLength(2);
  await responder(m, 'obterDefinicoes', copia(DEFINICOES));
  m.mudarRede(true);
  expect(pedidos(m, 'obterDefinicoes')).toHaveLength(2);
});

test('mudar um campo: o valor tal e qual escrito, o erro dele sai e Guardar liga-se', async () => {
  const m = await carregadas();
  m.ecra.mudarCampo('rota_hora_saida', '07:30');
  expect(valoresDa(m)).toEqual({ ...VALORES, rota_hora_saida: '07:30' });
  expect(m.vista().guardar).toEqual(PRONTO);
  m.ecra.mudarCampo('servico_amostra_min', '012');
  expect(valoresDa(m).servico_amostra_min).toBe('012');
  // Voltar ao valor guardado desliga Guardar outra vez.
  m.ecra.mudarCampo('rota_hora_saida', '08:00');
  m.ecra.mudarCampo('servico_amostra_min', '10');
  expect(m.vista().guardar).toEqual(SEM_ALTERACOES);
});

test('mudar um campo que não existe, um da fábrica ou com um valor que não é texto não muda nada', async () => {
  const m = await carregadas();
  const antes = m.vista();
  m.ecra.mudarCampo('fabrica_morada', 'Outra');
  m.ecra.mudarCampo('outra', 'x');
  m.ecra.mudarCampo('constructor', 'x');
  m.ecra.mudarCampo('rota_hora_saida', 7);
  m.ecra.mudarCampo('servico_entrega_min', undefined);
  expect(m.vista()).toBe(antes);
});

test('antes de carregar não se muda nem se guarda', () => {
  const m = montar();
  const antes = m.vista();
  m.ecra.mudarCampo('rota_hora_saida', '07:30');
  m.ecra.guardar();
  expect(m.vista()).toBe(antes);
  expect(pedidos(m, 'alterarDefinicoes')).toEqual([]);
});

test('Guardar envia só o que mudou (os minutos como inteiros) e avisa', async () => {
  const m = await carregadas();
  m.ecra.mudarCampo('rota_hora_saida', '07:30');
  m.ecra.mudarCampo('servico_entrega_min', ' 12 ');
  m.ecra.guardar();
  const [pedido] = pedidos(m, 'alterarDefinicoes');
  expect(pedido.argumentos).toEqual([{ rota_hora_saida: '07:30', servico_entrega_min: 12 }]);
  // Enquanto grava: "A guardar…", os campos desligados, um pedido de cada vez.
  expect(m.vista().guardar).toEqual({ ativo: false, texto: 'A guardar…', falta: null });
  expect(m.vista().camposDesativados).toBe(true);
  m.ecra.guardar();
  m.ecra.mudarCampo('rota_hora_regresso', '18:00');
  expect(pedidos(m, 'alterarDefinicoes')).toHaveLength(1);
  expect(valoresDa(m).rota_hora_regresso).toBe('19:00');
  expect(m.avisos).toEqual([]);
  await responder(m, 'alterarDefinicoes', { ...copia(DEFINICOES), rota_hora_saida: '07:30', servico_entrega_min: 12 });
  // Os campos passam a ser o que o servidor tem.
  expect(valoresDa(m)).toEqual({ ...VALORES, rota_hora_saida: '07:30', servico_entrega_min: '12' });
  expect(m.vista().guardar).toEqual(SEM_ALTERACOES);
  expect(m.vista().camposDesativados).toBe(false);
  expect(m.avisos).toEqual(['Definições das rotas guardadas.']);
});

test('sem alterações, Guardar não pede nada', async () => {
  const m = await carregadas();
  m.ecra.guardar();
  expect(pedidos(m, 'alterarDefinicoes')).toEqual([]);
});

test('a resposta que não são as definições deixa os campos como estavam (Guardar volta a poder-se usar)', async () => {
  const m = await carregadas();
  m.ecra.mudarCampo('servico_amostra_min', '20');
  m.ecra.guardar();
  await responder(m, 'alterarDefinicoes', null);
  expect(valoresDa(m).servico_amostra_min).toBe('20');
  expect(m.vista().guardar).toEqual(PRONTO);
  expect(m.avisos).toEqual(['Definições das rotas guardadas.']);
});

test('o 422 fica junto de cada campo (a coerência das horas no regresso), com o foco no primeiro', async () => {
  const m = await carregadas();
  m.ecra.mudarCampo('rota_hora_regresso', '07:00');
  m.ecra.mudarCampo('servico_acompanhamento_min', '300');
  m.ecra.guardar();
  await falhar(m, 'alterarDefinicoes', erroValidacao({
    servico_acompanhamento_min: 'O tempo de serviço é um número inteiro de minutos, de 1 a 240.',
    rota_hora_regresso: 'A hora de regresso tem de ser depois da hora de saída.',
  }));
  expect(errosDa(m)).toEqual({
    ...SEM_ERROS,
    rota_hora_regresso: 'A hora de regresso tem de ser depois da hora de saída.',
    servico_acompanhamento_min: 'O tempo de serviço é um número inteiro de minutos, de 1 a 240.',
  });
  expect(m.focos).toEqual(['rota_hora_regresso']);
  expect(m.vista().alerta).toBeNull();
  // O que se escreveu fica, para corrigir.
  expect(valoresDa(m)).toEqual({ ...VALORES, rota_hora_regresso: '07:00', servico_acompanhamento_min: '300' });
  expect(m.vista().guardar).toEqual(PRONTO);
  expect(m.avisos).toEqual([]);
  // Mudar um campo tira só o erro dele.
  m.ecra.mudarCampo('servico_acompanhamento_min', '30');
  expect(errosDa(m)).toEqual({ ...SEM_ERROS, rota_hora_regresso: 'A hora de regresso tem de ser depois da hora de saída.' });
  // Guardar outra vez limpa os erros.
  m.ecra.guardar();
  expect(errosDa(m)).toEqual(SEM_ERROS);
});

test('o 422 sem nenhum dos 6 campos (ou sem campos) vai para o alerta; o alerta sai ao guardar outra vez', async () => {
  const m = await carregadas();
  m.ecra.mudarCampo('rota_hora_saida', '07:00');
  m.ecra.guardar();
  await falhar(m, 'alterarDefinicoes', erroValidacao({ fabrica_lat: 'A latitude tem de ser um número.' }));
  expect(m.vista().alerta).toBe('Verifique os campos assinalados.');
  expect(errosDa(m)).toEqual(SEM_ERROS);
  expect(m.focos).toEqual([]);
  m.ecra.guardar();
  expect(m.vista().alerta).toBeNull();
  await falhar(m, 'alterarDefinicoes', erroValidacao({ rota_hora_saida: '' }));
  expect(m.vista().alerta).toBe('Verifique os campos assinalados.');
  m.ecra.guardar();
  await falhar(m, 'alterarDefinicoes', new ErroCrm({ codigo: 'validacao', mensagem: 'Verifique os campos assinalados.', estado: 422, campos: null }));
  expect(m.vista().alerta).toBe('Verifique os campos assinalados.');
});

test('outro erro (sem rede, inesperado) vai para o alerta, sem aviso', async () => {
  const m = await carregadas();
  m.ecra.mudarCampo('rota_hora_saida', '07:00');
  m.ecra.guardar();
  await falhar(m, 'alterarDefinicoes', erroSemRede());
  expect(m.vista().alerta).toBe(MENSAGEM_SEM_REDE);
  expect(m.vista().guardar).toEqual(PRONTO);
  m.ecra.guardar();
  await falhar(m, 'alterarDefinicoes', new Error());
  expect(m.vista().alerta).toBe(MENSAGEM_ERRO_INESPERADO);
  expect(m.avisos).toEqual([]);
});

describe('destruir(): o separador saiu', () => {
  test('as definições que chegam (ou falham) depois não mudam nada', async () => {
    for (const acabar of [(m) => responder(m, 'obterDefinicoes', copia(DEFINICOES)), (m) => falhar(m, 'obterDefinicoes', erroSemRede())]) {
      const m = montar();
      const vista = m.vista();
      const vistas = m.vistas.length;
      m.ecra.destruir();
      await acabar(m);
      expect(m.vista()).toEqual(vista);
      expect(m.vistas).toHaveLength(vistas);
    }
  });

  test('a gravação que chega (ou falha) depois não avisa nem muda a vista', async () => {
    for (const acabar of [
      (m) => responder(m, 'alterarDefinicoes', copia(DEFINICOES)),
      (m) => falhar(m, 'alterarDefinicoes', erroValidacao({ rota_hora_saida: 'x' })),
    ]) {
      const m = await carregadas();
      m.ecra.mudarCampo('rota_hora_saida', '07:00');
      m.ecra.guardar();
      const vistas = m.vistas.length;
      m.ecra.destruir();
      await acabar(m);
      expect(m.avisos).toEqual([]);
      expect(m.focos).toEqual([]);
      expect(m.vistas).toHaveLength(vistas);
    }
  });

  test('a rede deixa de se ouvir; nada mais se pede nem se muda', async () => {
    const m = montar();
    await falhar(m, 'obterDefinicoes', erroSemRede());
    m.ecra.destruir();
    m.mudarRede(true);
    m.ecra.tentarDeNovo();
    m.ecra.iniciar();
    expect(pedidos(m, 'obterDefinicoes')).toHaveLength(1);
    const outro = await carregadas();
    outro.ecra.mudarCampo('servico_amostra_min', '20');
    outro.ecra.destruir();
    const vistas = outro.vistas.length;
    outro.ecra.mudarCampo('rota_hora_saida', '07:00');
    outro.ecra.guardar();
    expect(pedidos(outro, 'alterarDefinicoes')).toEqual([]);
    expect(outro.vistas).toHaveLength(vistas);
  });

  test('iniciar depois de destruir não pede nada nem ouve a rede', () => {
    const ouvidos = [];
    const api = apiFalsa();
    const ecra = criarDefinicoesRotas({ api, rede: { online: () => true, aoMudar: (f) => { ouvidos.push(f); return () => {}; } } });
    ecra.destruir();
    ecra.iniciar();
    expect(api.pedidos).toEqual([]);
    expect(ouvidos).toEqual([]);
  });

  test('o ouvinte da rede cancela-se', () => {
    const cancelados = [];
    const rede = { online: () => true, aoMudar: () => () => cancelados.push('cancelado') };
    const ecra = criarDefinicoesRotas({ api: apiFalsa(), rede });
    ecra.iniciar();
    expect(cancelados).toEqual([]);
    ecra.destruir();
    expect(cancelados).toEqual(['cancelado']);
  });
});
