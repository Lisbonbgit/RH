/**
 * DEFINIÇÕES › FÁBRICA — as regras do separador "Fábrica", sem DOM.
 *
 * Porta de public/assets/js/componentes/definicoes-fabrica.js do CRM autónomo
 * (etiqueta `referencia-standalone`), com os casos de
 * tests/js/definicoes-fabrica.test.js (correção "T2.26 / T2.27 / T2.29 /
 * T2.30 (componentes Sem Jest)", a parte da fábrica da T2.24a):
 *   - as funções puras `corpoFabrica`, `estadoGuardarFabrica` e `textoPonto`,
 *     tal e qual (o ponto só muda se mudar nas 6 casas, com lat e lng juntas);
 *   - o ecrã sem o DOM (`criarFabrica`), como a ficha da T2.28: o que o
 *     autónomo escrevia no DOM é uma `vista` congelada, entregue ao
 *     `aoMudarVista`, e o `pages/crm/DefinicoesFabrica.js` só a desenha. O
 *     seletor do ponto é o `SeletorLocalizacao` (sem GPS), que o ecrã só toca
 *     pela `ref` (`limparErro`, `desconfirmar`, `mostrarErro`, `focar`): os
 *     casos do mapa (o pino solto no ponto, à escala da rua, o título e a
 *     pesquisa) são do `seletor.test.js` e da verificação no browser.
 *
 * Adaptações ao portal (plano T2.30):
 *   - "Dados da fábrica guardados." é um aviso (toast, `aoAvisar`), e não o
 *     parágrafo que ficava até à mudança seguinte;
 *   - sem `aoMudarCentro`: no portal cada página do mapa pede o `/config` ao
 *     abrir, e o centro novo vem de lá;
 *   - um erro do ponto com a mudança fechada leva o foco para "Mudar o ponto
 *     no mapa" (ao lado do erro).
 */
import { ErroCrm, MENSAGEM_ERRO_INESPERADO, MENSAGEM_SEM_REDE } from './api';
import { criarEstadoRede } from './rede';
import { textosSeletor } from './seletor';
import {
  MORADA_MAXIMO_FABRICA,
  TEXTOS_SELETOR_FABRICA,
  TEXTO_A_CARREGAR_FABRICA,
  TEXTO_A_GUARDAR,
  TEXTO_AJUDA_PONTO,
  TEXTO_CANCELAR_MUDANCA,
  TEXTO_DESCRICAO_FABRICA,
  TEXTO_FABRICA_GUARDADA,
  TEXTO_GUARDAR,
  TEXTO_MORADA_FABRICA,
  TEXTO_MUDAR_PONTO,
  TEXTO_PONTO_NO_MAPA,
  TITULO_FABRICA,
  corpoFabrica,
  criarFabrica,
  estadoGuardarFabrica,
  textoPonto,
} from './fabrica';

const DEFINICOES = Object.freeze({ fabrica_morada: 'Rua da Fábrica 1, Lisboa', fabrica_lat: 38.7223, fabrica_lng: -9.1393 });
const copia = (valor) => JSON.parse(JSON.stringify(valor));

// --- Textos --------------------------------------------------------------------------------------

test('os textos exatos do separador e do seletor do ponto', () => {
  expect(TITULO_FABRICA).toBe('Fábrica');
  expect(TEXTO_DESCRICAO_FABRICA).toBe('A morada e o ponto da fábrica no mapa.');
  expect(TEXTO_A_CARREGAR_FABRICA).toBe('A carregar os dados da fábrica…');
  expect(TEXTO_FABRICA_GUARDADA).toBe('Dados da fábrica guardados.');
  expect(TEXTO_MORADA_FABRICA).toBe('Morada da fábrica');
  expect(TEXTO_PONTO_NO_MAPA).toBe('Ponto no mapa');
  expect(TEXTO_AJUDA_PONTO).toBe('O mapa abre aqui enquanto não houver lojas.');
  expect(TEXTO_MUDAR_PONTO).toBe('Mudar o ponto no mapa');
  expect(TEXTO_CANCELAR_MUDANCA).toBe('Cancelar a mudança do ponto');
  expect([TEXTO_GUARDAR, TEXTO_A_GUARDAR]).toEqual(['Guardar', 'A guardar…']);
  // O tamanho da morada no servidor (`dominio/definicoes.py::MORADA_MAXIMO`).
  expect(MORADA_MAXIMO_FABRICA).toBe(255);
  expect(TEXTOS_SELETOR_FABRICA).toEqual({
    titulo: 'Ponto da fábrica no mapa',
    tocar: 'Toque no mapa no sítio da fábrica.',
    mapa: 'Mapa para pôr o pino da fábrica',
    pino: 'Pino da fábrica',
    // Revisão do mapa Google (MAPA-G-2): a regra do arrasto, o lugar indisponível e o painel do negócio
    // também falam da fábrica; o painel não tem a dica do nome (a fábrica não tem nome a escrever).
    arrastarLugar: 'Arraste o pino até ao sítio exato da fábrica para confirmar',
    lugarIndisponivel: 'Não foi possível obter a posição deste lugar — toque no mapa no sítio da fábrica.',
    dicaNegocio: null,
  });
  expect(Object.isFrozen(TEXTOS_SELETOR_FABRICA)).toBe(true);
  // Os textos do seletor da loja trocados todos pelos da fábrica: nenhum fala da loja.
  expect(textosSeletor(TEXTOS_SELETOR_FABRICA)).toEqual(TEXTOS_SELETOR_FABRICA);
  const daLoja = Object.values(textosSeletor(TEXTOS_SELETOR_FABRICA)).filter((texto) => /loja/i.test(texto ?? ''));
  expect(daLoja).toEqual([]);
});

// --- Funções puras (as 3 do autónomo) ------------------------------------------------------------

test('corpoFabrica: só o que mudou; o ponto vai inteiro (latitude e longitude), com 6 casas', () => {
  expect(corpoFabrica(DEFINICOES, { morada: DEFINICOES.fabrica_morada, ponto: null })).toStrictEqual({});
  expect(corpoFabrica(DEFINICOES, { morada: ' Rua da Fábrica 1, Lisboa  ', ponto: null })).toStrictEqual({}); // espaços nas pontas não contam
  expect(corpoFabrica(DEFINICOES, { morada: 'Rua Nova 2', ponto: null })).toStrictEqual({ fabrica_morada: 'Rua Nova 2' });
  expect(corpoFabrica(DEFINICOES, { morada: '', ponto: null })).toStrictEqual({ fabrica_morada: '' });
  expect(corpoFabrica(DEFINICOES, { morada: DEFINICOES.fabrica_morada, ponto: { lat: 38.71234567, lng: -9.13456789 } }))
    .toStrictEqual({ fabrica_lat: 38.712346, fabrica_lng: -9.134568 });
  // O mesmo ponto com as 6 casas com que se guarda.
  expect(corpoFabrica(DEFINICOES, { morada: DEFINICOES.fabrica_morada, ponto: { lat: 38.72230004, lng: -9.1393 } })).toStrictEqual({});
  expect(corpoFabrica(DEFINICOES, { morada: 'Rua Nova 2', ponto: { lat: 38.7, lng: -9.1393 } }))
    .toStrictEqual({ fabrica_morada: 'Rua Nova 2', fabrica_lat: 38.7, fabrica_lng: -9.1393 });
});

test('corpoFabrica: só a longitude mudou também leva a latitude; um ponto sem números não conta', () => {
  expect(corpoFabrica(DEFINICOES, { morada: DEFINICOES.fabrica_morada, ponto: { lat: 38.7223, lng: -9.2 } }))
    .toStrictEqual({ fabrica_lat: 38.7223, fabrica_lng: -9.2 });
  for (const ponto of [{ lat: 38.7 }, { lat: NaN, lng: -9.2 }, { lat: 38.7, lng: Infinity }, { lat: '38.7', lng: -9.2 }, undefined]) {
    expect(corpoFabrica(DEFINICOES, { morada: DEFINICOES.fabrica_morada, ponto })).toStrictEqual({});
  }
  // Uma morada que não é texto conta como vazia; a morada guardada em falta também.
  expect(corpoFabrica(DEFINICOES, { morada: null, ponto: null })).toStrictEqual({ fabrica_morada: '' });
  expect(corpoFabrica({ ...DEFINICOES, fabrica_morada: undefined }, { morada: '  ', ponto: null })).toStrictEqual({});
});

test('corpoFabrica: de um ponto vindo da Google só contam a latitude e a longitude (nunca o google_place_id nem a origem; plano G17)', () => {
  const doNegocio = {
    lat: 38.71234567, lng: -9.13456789, origem_coords: 'pin_manual', precisao_m: 7, google_place_id: 'ChIJ-negocio-teste',
  };
  const corpo = corpoFabrica(DEFINICOES, { morada: DEFINICOES.fabrica_morada, ponto: doNegocio });
  expect(corpo).toStrictEqual({ fabrica_lat: 38.712346, fabrica_lng: -9.134568 });
  expect(Object.keys(corpo)).toEqual(['fabrica_lat', 'fabrica_lng']);
  // O id sozinho (o ponto no mesmo sítio) não é uma alteração.
  expect(corpoFabrica(DEFINICOES, {
    morada: DEFINICOES.fabrica_morada,
    ponto: { lat: 38.7223, lng: -9.1393, origem_coords: 'pin_manual', precisao_m: null, google_place_id: 'ChIJ-outro' },
  })).toStrictEqual({});
});

test('estadoGuardarFabrica: o botão Guardar e porque não se pode guardar', () => {
  expect(estadoGuardarFabrica({ alterada: true, aCorrigir: false, aGuardar: false })).toEqual({ ativo: true, texto: 'Guardar', falta: null });
  expect(estadoGuardarFabrica({ alterada: false, aCorrigir: false, aGuardar: false }))
    .toEqual({ ativo: false, texto: 'Guardar', falta: 'Sem alterações por guardar.' });
  expect(estadoGuardarFabrica({ alterada: true, aCorrigir: true, aGuardar: false }))
    .toEqual({ ativo: false, texto: 'Guardar', falta: 'Para guardar, confirme o ponto no mapa ou cancele a mudança.' });
  expect(estadoGuardarFabrica({ alterada: true, aCorrigir: false, aGuardar: true })).toEqual({ ativo: false, texto: 'A guardar…', falta: null });
  expect(estadoGuardarFabrica({ alterada: false, aCorrigir: true, aGuardar: true })).toEqual({ ativo: false, texto: 'A guardar…', falta: null });
});

test('textoPonto: as coordenadas com as 6 casas com que se guardam', () => {
  expect(textoPonto(DEFINICOES)).toBe('Latitude 38.722300 · longitude -9.139300');
  expect(textoPonto({ fabrica_lat: 41.15, fabrica_lng: -8.6100004 })).toBe('Latitude 41.150000 · longitude -8.610000');
});

// --- O ecrã --------------------------------------------------------------------------------------

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

// Monta o ecrã como a página (DefinicoesFabrica): cria e inicia (pede as definições e ouve a rede).
function montar({ iniciar = true } = {}) {
  const api = apiFalsa();
  const janela = new EventTarget();
  const navegador = { onLine: true };
  const avisos = [];
  const focos = [];
  const vistas = [];
  const seletor = [];
  let ecra = null;
  ecra = criarFabrica({
    api,
    rede: criarEstadoRede(janela, navegador),
    // O seletor do ponto (SeletorLocalizacao pela ref): o desconfirmar avisa que o ponto saiu, como o
    // verdadeiro (aoMudar(null)).
    seletor: {
      limparErro: () => seletor.push(['limparErro']),
      desconfirmar: () => {
        seletor.push(['desconfirmar']);
        ecra.mudarPonto(null);
      },
      mostrarErro: (texto) => seletor.push(['mostrarErro', texto]),
      focar: () => seletor.push(['focar']),
    },
    aoMudarVista: (vista) => vistas.push(vista),
    aoAvisar: (texto) => avisos.push(texto),
    aoFocar: (alvo) => focos.push(alvo),
  });
  if (iniciar) ecra.iniciar();
  const mudarRede = (ligado) => {
    navegador.onLine = ligado;
    janela.dispatchEvent(new Event(ligado ? 'online' : 'offline'));
  };
  return { api, ecra, avisos, focos, vistas, seletor, mudarRede, vista: () => ecra.vista };
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

async function carregada(definicoes = DEFINICOES) {
  const m = montar();
  await responder(m, 'obterDefinicoes', copia(definicoes));
  return m;
}

const erroSemRede = () => new ErroCrm({ codigo: 'sem_rede', mensagem: MENSAGEM_SEM_REDE });
const erroValidacao = (campos) => new ErroCrm({ codigo: 'validacao', mensagem: 'Verifique os campos assinalados.', estado: 422, campos });
const SEM_ALTERACOES = { ativo: false, texto: 'Guardar', falta: 'Sem alterações por guardar.' };
const A_CONFIRMAR = { ativo: false, texto: 'Guardar', falta: 'Para guardar, confirme o ponto no mapa ou cancele a mudança.' };
const PRONTO = { ativo: true, texto: 'Guardar', falta: null };
// O bloco que o seletor entrega ao confirmar (o `localizacaoFinal` de um pino arrastado).
const PINO = Object.freeze({ lat: 38.71234567, lng: -9.13456789, origem_coords: 'pin_manual', precisao_m: null });

// --- Carregar ------------------------------------------------------------------------------------

test('criar não pede nada; iniciar pede as definições uma só vez', () => {
  const m = montar({ iniciar: false });
  expect(m.api.pedidos).toEqual([]);
  expect(m.vista()).toEqual({
    estado: 'a_carregar',
    falha: null,
    morada: '',
    erroMorada: null,
    resumoPonto: null,
    erroPonto: null,
    correcao: null,
    camposDesativados: false,
    alerta: null,
    guardar: SEM_ALTERACOES,
  });
  expect(Object.isFrozen(m.vista())).toBe(true);
  m.ecra.mudarMorada('Rua Nova'); // ainda sem formulário
  expect(m.vista().morada).toBe('');
  m.ecra.iniciar();
  m.ecra.iniciar();
  expect(m.api.pedidos.map((p) => p.nome)).toEqual(['obterDefinicoes']);
});

test('pede as definições e mostra a morada e o ponto; sem alterações, Guardar fica desativado', async () => {
  const m = await carregada();
  expect(m.vista()).toEqual({
    estado: 'pronto',
    falha: null,
    morada: 'Rua da Fábrica 1, Lisboa',
    erroMorada: null,
    resumoPonto: 'Latitude 38.722300 · longitude -9.139300',
    erroPonto: null,
    correcao: null, // o mapa só se abre para mudar o ponto
    camposDesativados: false,
    alerta: null,
    guardar: SEM_ALTERACOES,
  });
  expect(Object.isFrozen(m.vista().guardar)).toBe(true);
});

test('os dados ficam texto: uma morada <b>x</b> é a morada', async () => {
  const m = await carregada({ ...DEFINICOES, fabrica_morada: '<b>x</b>' });
  expect(m.vista().morada).toBe('<b>x</b>');
});

test('falha ao carregar: a mensagem e "Tentar novamente" (um toque, um pedido); a rede que volta tenta outra vez', async () => {
  const m = montar();
  await falhar(m, 'obterDefinicoes', erroSemRede());
  expect(m.vista().estado).toBe('falha');
  expect(m.vista().falha).toEqual({ mensagem: MENSAGEM_SEM_REDE, aTentar: false });
  m.ecra.tentarDeNovo();
  m.ecra.tentarDeNovo();
  expect(pedidos(m, 'obterDefinicoes')).toHaveLength(2);
  expect(m.vista().falha.aTentar).toBe(true);
  await falhar(m, 'obterDefinicoes', erroSemRede());
  m.mudarRede(false);
  expect(pedidos(m, 'obterDefinicoes')).toHaveLength(2);
  m.mudarRede(true);
  expect(pedidos(m, 'obterDefinicoes')).toHaveLength(3);
  await responder(m, 'obterDefinicoes', copia(DEFINICOES));
  expect(m.vista().estado).toBe('pronto');
  expect(m.vista().falha).toBe(null);
  m.mudarRede(true);
  m.ecra.tentarDeNovo();
  expect(pedidos(m, 'obterDefinicoes')).toHaveLength(3); // carregadas, não volta a pedir
});

test('uma resposta estragada conta como falha: o texto de erro inesperado e "Tentar novamente"', async () => {
  for (const estragada of [null, [], { ...DEFINICOES, fabrica_lat: '38.7' }, { ...DEFINICOES, fabrica_morada: null }, { ...DEFINICOES, fabrica_lng: NaN }]) {
    const m = montar();
    await responder(m, 'obterDefinicoes', estragada);
    expect(m.vista().estado).toBe('falha');
    expect(m.vista().falha).toEqual({ mensagem: MENSAGEM_ERRO_INESPERADO, aTentar: false });
    m.ecra.tentarDeNovo();
    expect(pedidos(m, 'obterDefinicoes')).toHaveLength(2);
  }
});

// --- A morada ------------------------------------------------------------------------------------

test('mudar a morada e Guardar: só a morada; depois fica a do servidor e o aviso "Dados da fábrica guardados."', async () => {
  const m = await carregada();
  m.ecra.mudarMorada('Rua Nova 2, Lisboa');
  expect(m.vista().morada).toBe('Rua Nova 2, Lisboa');
  expect(m.vista().guardar).toEqual(PRONTO);
  m.ecra.guardar();
  expect(ultimo(m, 'alterarDefinicoes').argumentos).toEqual([{ fabrica_morada: 'Rua Nova 2, Lisboa' }]);
  expect(m.vista().guardar).toEqual({ ativo: false, texto: 'A guardar…', falta: null });
  m.ecra.guardar();
  expect(pedidos(m, 'alterarDefinicoes')).toHaveLength(1); // um toque, um pedido
  expect(m.avisos).toEqual([]);
  await responder(m, 'alterarDefinicoes', { ...DEFINICOES, fabrica_morada: 'Rua Nova 2, Lisboa (servidor)' });
  expect(m.avisos).toEqual(['Dados da fábrica guardados.']);
  expect(m.vista().morada).toBe('Rua Nova 2, Lisboa (servidor)');
  expect(m.vista().guardar).toEqual(SEM_ALTERACOES);
  m.ecra.mudarMorada('Rua Nova 3');
  expect(m.vista().guardar).toEqual(PRONTO);
});

test('Guardar sem alterações não pede nada', async () => {
  const m = await carregada();
  m.ecra.mudarMorada('  Rua da Fábrica 1, Lisboa ');
  m.ecra.guardar();
  expect(pedidos(m, 'alterarDefinicoes')).toEqual([]);
});

test('enquanto grava, a morada e o ponto não se mexem (a resposta repõe-nos); voltam quando a resposta chega', async () => {
  const m = await carregada();
  m.ecra.mudarMorada('Rua Nova 2');
  m.ecra.guardar();
  expect(m.vista().camposDesativados).toBe(true);
  m.ecra.mudarMorada('Outra');
  m.ecra.abrirCorrecao();
  expect(m.vista().morada).toBe('Rua Nova 2');
  expect(m.vista().correcao).toBe(null);
  await responder(m, 'alterarDefinicoes', { ...DEFINICOES, fabrica_morada: 'Rua Nova 2' });
  expect(m.vista().camposDesativados).toBe(false);
  m.ecra.abrirCorrecao();
  expect(m.vista().correcao).not.toBe(null);
});

test('se gravar falhar, a morada volta a editar-se, com o que se escreveu', async () => {
  const m = await carregada();
  m.ecra.mudarMorada('Rua Nova 2');
  m.ecra.guardar();
  await falhar(m, 'alterarDefinicoes', erroSemRede());
  expect(m.vista().camposDesativados).toBe(false);
  expect(m.vista().morada).toBe('Rua Nova 2');
  expect(m.avisos).toEqual([]);
});

test('uma morada inválida (422): o erro do servidor junto ao campo, com o foco lá; escrever tira-o', async () => {
  const m = await carregada();
  m.ecra.mudarMorada('x'.repeat(10));
  m.ecra.guardar();
  await falhar(m, 'alterarDefinicoes', erroValidacao({ fabrica_morada: 'A morada tem no máximo 255 caracteres.' }));
  expect(m.vista().erroMorada).toBe('A morada tem no máximo 255 caracteres.');
  expect(m.focos).toEqual(['morada']);
  expect(m.vista().guardar).toEqual(PRONTO);
  expect(m.vista().alerta).toBe(null);
  m.ecra.guardar();
  expect(m.vista().erroMorada).toBe(null); // o pedido seguinte tira-o
  await falhar(m, 'alterarDefinicoes', erroValidacao({ fabrica_morada: 'A morada tem no máximo 255 caracteres.' }));
  m.ecra.mudarMorada('Rua');
  expect(m.vista().erroMorada).toBe(null);
});

test('Guardar sem rede: a mensagem por cima do botão, e pode tentar outra vez (o pedido seguinte tira-a)', async () => {
  const m = await carregada();
  m.ecra.mudarMorada('Rua Nova 2');
  m.ecra.guardar();
  await falhar(m, 'alterarDefinicoes', erroSemRede());
  expect(m.vista().alerta).toBe(MENSAGEM_SEM_REDE);
  expect(m.vista().guardar).toEqual(PRONTO);
  m.ecra.guardar();
  expect(m.vista().alerta).toBe(null);
  await falhar(m, 'alterarDefinicoes', new Error('x'));
  expect(m.vista().alerta).toBe(MENSAGEM_ERRO_INESPERADO);
});

test('um 422 sem campos conhecidos vai para a mensagem por cima do botão', async () => {
  const m = await carregada();
  m.ecra.mudarMorada('Rua Nova 2');
  m.ecra.guardar();
  await falhar(m, 'alterarDefinicoes', erroValidacao({ fabrica_cor: 'Esta definição não existe.' }));
  expect(m.vista().alerta).toBe('Verifique os campos assinalados.');
  expect(m.focos).toEqual([]);
});

test('uma resposta do Guardar que não são as definições: fica o que se tinha, e o aviso na mesma', async () => {
  const m = await carregada();
  m.ecra.mudarMorada('Rua Nova 2');
  m.ecra.guardar();
  await responder(m, 'alterarDefinicoes', { ok: true });
  expect(m.avisos).toEqual(['Dados da fábrica guardados.']);
  expect(m.vista().morada).toBe('Rua Nova 2');
  expect(m.vista().resumoPonto).toBe('Latitude 38.722300 · longitude -9.139300');
  expect(m.vista().guardar).toEqual(PRONTO);
});

// --- O ponto no mapa -----------------------------------------------------------------------------

test('"Mudar o ponto no mapa": o seletor com o pino solto no ponto da fábrica; Guardar espera pela confirmação', async () => {
  const m = await carregada();
  m.ecra.abrirCorrecao();
  expect(m.vista().correcao).toEqual({ chave: 1, inicial: { lat: 38.7223, lng: -9.1393, origem: 'pin_manual' } });
  expect(Object.isFrozen(m.vista().correcao)).toBe(true);
  expect(Object.isFrozen(m.vista().correcao.inicial)).toBe(true);
  expect(m.vista().guardar).toEqual(A_CONFIRMAR);
  m.ecra.abrirCorrecao(); // já aberto: o mesmo
  expect(m.vista().correcao.chave).toBe(1);
});

test('"Mudar o ponto no mapa" antes de as definições chegarem não abre nada', () => {
  const m = montar();
  m.ecra.abrirCorrecao();
  expect(m.vista().correcao).toBe(null);
});

test('arrastar o pino e confirmar: Guardar envia a latitude e a longitude; depois o seletor fecha', async () => {
  const m = await carregada();
  m.ecra.abrirCorrecao();
  m.ecra.mudarPonto(PINO);
  expect(m.vista().guardar).toEqual(PRONTO);
  m.ecra.guardar();
  expect(ultimo(m, 'alterarDefinicoes').argumentos).toEqual([{ fabrica_lat: 38.712346, fabrica_lng: -9.134568 }]);
  expect(m.seletor).toEqual([['limparErro']]);
  m.ecra.cancelarCorrecao(); // enquanto grava, não se cancela nem se escolhe outra morada
  m.ecra.escolherMorada({ rotulo: 'Rua do Ouro 3' });
  expect(m.vista().correcao).not.toBe(null);
  expect(m.vista().morada).toBe('Rua da Fábrica 1, Lisboa');
  await responder(m, 'alterarDefinicoes', { ...DEFINICOES, fabrica_lat: 38.712346, fabrica_lng: -9.134568 });
  expect(m.vista().correcao).toBe(null);
  expect(m.vista().resumoPonto).toBe('Latitude 38.712346 · longitude -9.134568');
  expect(m.avisos).toEqual(['Dados da fábrica guardados.']);
  expect(m.vista().guardar).toEqual(SEM_ALTERACOES);
  // A mudança seguinte é outro seletor (outra chave), já no ponto novo.
  m.ecra.abrirCorrecao();
  expect(m.vista().correcao).toEqual({ chave: 2, inicial: { lat: 38.712346, lng: -9.134568, origem: 'pin_manual' } });
});

test('o ponto de um negócio ou da pesquisa da Google (arrastado: pin_manual + google_place_id): Guardar só manda a latitude e a longitude (plano G17)', async () => {
  const m = await carregada();
  m.ecra.abrirCorrecao();
  // A fábrica abre sem GPS e sem lugar da Google: só o ponto e a origem pin_manual.
  expect(m.vista().correcao.inicial).toStrictEqual({ lat: 38.7223, lng: -9.1393, origem: 'pin_manual' });
  expect(m.vista().correcao.inicial).not.toHaveProperty('google_place_id');
  m.ecra.mudarPonto({ ...PINO, google_place_id: 'ChIJ-negocio-teste' });
  expect(m.vista().guardar).toEqual(PRONTO);
  m.ecra.guardar();
  expect(ultimo(m, 'alterarDefinicoes').argumentos).toStrictEqual([{ fabrica_lat: 38.712346, fabrica_lng: -9.134568 }]);
  // Nada do lugar chega à vista (nem o id).
  expect(JSON.stringify(m.vistas)).not.toContain('ChIJ');
  await responder(m, 'alterarDefinicoes', { ...DEFINICOES, fabrica_lat: 38.712346, fabrica_lng: -9.134568 });
  expect(m.vista().correcao).toBe(null);
  expect(m.vista().resumoPonto).toBe('Latitude 38.712346 · longitude -9.134568');
});

test('a morada da pesquisa da Google sem rótulo (a Google sem a morada formatada) não mexe na morada da fábrica (plano G17)', async () => {
  const m = await carregada();
  m.ecra.abrirCorrecao();
  const daGoogle = { morada: 'Rua do Ouro 3', codigo_postal: '1100-060', localidade: 'Lisboa', lat: 38.7101, lng: -9.138 };
  m.ecra.escolherMorada({ rotulo: null, ...daGoogle });
  expect(m.vista().morada).toBe('Rua da Fábrica 1, Lisboa');
  expect(m.vista().guardar).toEqual(A_CONFIRMAR);
  m.ecra.escolherMorada({ rotulo: 'Rua do Ouro 3, 1100-060 Lisboa, Portugal', ...daGoogle });
  expect(m.vista().morada).toBe('Rua do Ouro 3, 1100-060 Lisboa, Portugal');
});

test('confirmar o ponto sem o mexer não é uma alteração; "Alterar localização" volta a esperar pela confirmação', async () => {
  const m = await carregada();
  m.ecra.abrirCorrecao();
  m.ecra.mudarPonto({ lat: 38.7223, lng: -9.1393, origem_coords: 'pin_manual', precisao_m: null });
  expect(m.vista().guardar).toEqual(SEM_ALTERACOES);
  m.ecra.mudarPonto(PINO);
  expect(m.vista().guardar).toEqual(PRONTO);
  m.ecra.mudarPonto(null);
  expect(m.vista().guardar).toEqual(A_CONFIRMAR);
});

test('o ponto fora de Portugal (422): o erro no mapa e o pino volta a soltar-se', async () => {
  const m = await carregada();
  m.ecra.abrirCorrecao();
  m.ecra.mudarPonto({ lat: 40.4168, lng: -3.7038, origem_coords: 'pin_manual', precisao_m: null });
  m.ecra.guardar();
  m.seletor.length = 0;
  await falhar(m, 'alterarDefinicoes', erroValidacao({
    fabrica_lat: 'Fora de Portugal continental.', fabrica_lng: 'Fora de Portugal continental.',
  }));
  expect(m.seletor).toEqual([['desconfirmar'], ['mostrarErro', 'Fora de Portugal continental.'], ['focar']]);
  expect(m.vista().guardar).toEqual(A_CONFIRMAR);
  expect(m.vista().erroPonto).toBe(null);
  expect(m.focos).toEqual([]);
});

test('só a longitude com erro também vai para o mapa', async () => {
  const m = await carregada();
  m.ecra.abrirCorrecao();
  m.ecra.mudarPonto(PINO);
  m.ecra.guardar();
  m.seletor.length = 0;
  await falhar(m, 'alterarDefinicoes', erroValidacao({ fabrica_lng: 'A longitude tem de ser um número.' }));
  expect(m.seletor).toEqual([['desconfirmar'], ['mostrarErro', 'A longitude tem de ser um número.'], ['focar']]);
});

test('o ponto e a morada com erro: os dois erros, e o foco na morada', async () => {
  const m = await carregada();
  m.ecra.mudarMorada('x');
  m.ecra.abrirCorrecao();
  m.ecra.mudarPonto(PINO);
  m.ecra.guardar();
  m.seletor.length = 0;
  await falhar(m, 'alterarDefinicoes', erroValidacao({
    fabrica_morada: 'A morada tem no máximo 255 caracteres.', fabrica_lat: 'Fora de Portugal continental.',
  }));
  expect(m.seletor).toEqual([['desconfirmar'], ['mostrarErro', 'Fora de Portugal continental.']]);
  expect(m.vista().erroMorada).toBe('A morada tem no máximo 255 caracteres.');
  expect(m.focos).toEqual(['morada']);
});

test('um erro do ponto com a mudança fechada fica junto a "Mudar o ponto no mapa", com o foco lá', async () => {
  const m = await carregada();
  m.ecra.mudarMorada('Rua Nova 2');
  m.ecra.guardar();
  await falhar(m, 'alterarDefinicoes', erroValidacao({ fabrica_lat: 'Indique também a latitude.' }));
  expect(m.vista().erroPonto).toBe('Indique também a latitude.');
  expect(m.focos).toEqual(['mudar']);
  expect(m.seletor).toEqual([]);
  // Abrir a mudança do ponto tira-o (o ponto vai ser outro); guardar também.
  m.ecra.abrirCorrecao();
  expect(m.vista().erroPonto).toBe(null);
  m.ecra.cancelarCorrecao();
  m.ecra.guardar();
  await falhar(m, 'alterarDefinicoes', erroValidacao({ fabrica_lat: 'Indique também a latitude.' }));
  m.ecra.guardar();
  expect(m.vista().erroPonto).toBe(null);
});

test('escolher uma morada na pesquisa escreve-a na morada; cancelar desfaz isso e devolve o foco ao botão', async () => {
  const m = await carregada();
  m.ecra.abrirCorrecao();
  const sugestao = { rotulo: 'Rua do Ouro 3, 1100-060 Lisboa, Portugal', morada: 'Rua do Ouro 3', codigo_postal: '1100-060', localidade: 'Lisboa', lat: 38.7101, lng: -9.138 };
  m.ecra.escolherMorada(sugestao);
  expect(m.vista().morada).toBe('Rua do Ouro 3, 1100-060 Lisboa, Portugal');
  m.ecra.cancelarCorrecao();
  expect(m.vista().correcao).toBe(null);
  expect(m.vista().morada).toBe('Rua da Fábrica 1, Lisboa');
  expect(m.vista().guardar).toEqual(SEM_ALTERACOES);
  expect(m.focos).toEqual(['mudar']);
});

test('escolher uma morada tira o erro da morada; sem a mudança aberta, ou sem rótulo, não faz nada', async () => {
  const m = await carregada();
  m.ecra.escolherMorada({ rotulo: 'Rua do Ouro 3' });
  expect(m.vista().morada).toBe('Rua da Fábrica 1, Lisboa');
  m.ecra.mudarMorada('x');
  m.ecra.guardar();
  await falhar(m, 'alterarDefinicoes', erroValidacao({ fabrica_morada: 'A morada tem no máximo 255 caracteres.' }));
  m.ecra.abrirCorrecao();
  for (const sugestao of [null, {}, { rotulo: '' }, { rotulo: 7 }]) m.ecra.escolherMorada(sugestao);
  expect(m.vista().morada).toBe('x');
  m.ecra.escolherMorada({ rotulo: 'Rua do Ouro 3' });
  expect(m.vista().erroMorada).toBe(null);
});

test('cancelar não desfaz a morada que a pessoa escreveu depois da pesquisa', async () => {
  const m = await carregada();
  m.ecra.abrirCorrecao();
  m.ecra.escolherMorada({ rotulo: 'Rua do Ouro 3' });
  m.ecra.mudarMorada('Escrita à mão');
  m.ecra.cancelarCorrecao();
  expect(m.vista().morada).toBe('Escrita à mão');
  expect(m.vista().guardar).toEqual(PRONTO);
});

test('cancelar sem ter escolhido morada deixa a morada como está', async () => {
  const m = await carregada();
  m.ecra.abrirCorrecao();
  m.ecra.mudarMorada('Escrita à mão');
  m.ecra.cancelarCorrecao();
  expect(m.vista().morada).toBe('Escrita à mão');
  m.ecra.cancelarCorrecao(); // já fechada
  expect(m.focos).toEqual(['mudar']);
});

test('um ponto que o seletor mande com a mudança fechada já não conta', async () => {
  const m = await carregada();
  m.ecra.mudarPonto(PINO);
  expect(m.vista().guardar).toEqual(SEM_ALTERACOES);
  m.ecra.abrirCorrecao();
  m.ecra.cancelarCorrecao();
  m.ecra.mudarPonto(PINO);
  expect(m.vista().guardar).toEqual(SEM_ALTERACOES);
});

test('as respostas que chegam depois de sair do ecrã são ignoradas; a rede também', async () => {
  const m = await carregada();
  m.ecra.mudarMorada('Rua Nova 2');
  m.ecra.guardar();
  m.ecra.destruir();
  const vistas = m.vistas.length;
  await responder(m, 'alterarDefinicoes', { ...DEFINICOES, fabrica_morada: 'Rua Nova 2' });
  expect(m.avisos).toEqual([]);
  expect(m.vistas).toHaveLength(vistas);

  const outra = montar();
  outra.ecra.destruir();
  await falhar(outra, 'obterDefinicoes', erroSemRede());
  outra.mudarRede(true);
  outra.ecra.iniciar();
  outra.ecra.tentarDeNovo();
  expect(pedidos(outra, 'obterDefinicoes')).toHaveLength(1);
  expect(outra.vista().estado).toBe('a_carregar');
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
  const ecra = criarFabrica({ api: apiFalsa(), rede });
  ecra.iniciar();
  ecra.iniciar();
  expect(ouvintes).toBe(1);
  ecra.destruir();
  expect(ouvintes).toBe(0);
});
