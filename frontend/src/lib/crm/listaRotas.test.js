/**
 * A PÁGINA "ROTAS" — as regras da lista e da escolha do dia, sem DOM (plano F3 T3.37; a página é o
 * `pages/crm/CrmRotas.js`).
 *
 * O controlador (`criarListaRotas`, no molde do `criarAdicionarARota`) pede a lista das rotas
 * (`listarRotas()`, sem intervalo: o servidor usa hoje − 14 e hoje + 60) e divide-a em "Próximas" (de
 * hoje em diante, a mais perto primeiro) e "Anteriores" (a mais recente primeiro), cada linha com o dia
 * (`rotuloDia`), o estado (`ROTULOS_ESTADO`, pelo `estado_efetivo`) e as paragens ativas, por exemplo
 * "seg 12/10 · Planeada · 9 paragens", ligada ao planeador desse dia. O campo da data com "Abrir" leva a
 * qualquer dia (também do passado, só de leitura; até hoje + 365, o horizonte do servidor) e "Hoje" à
 * rota de hoje. O "hoje" é sempre o do servidor. A falha mostra a mensagem e "Tentar novamente".
 */
import fs from 'fs';
import path from 'path';

import { TEXTO_FALTA_DIA } from './adicionarARota';
import { ErroCrm, MENSAGEM_ERRO_INESPERADO, MENSAGEM_SEM_REDE } from './api';
import {
  MENSAGEM_HORIZONTE,
  TEXTO_ABRIR,
  TEXTO_HOJE,
  TEXTO_SEM_ANTERIORES,
  TEXTO_SEM_PROXIMAS,
  TITULO_ANTERIORES,
  TITULO_PROXIMAS,
  TITULO_ROTAS,
  criarListaRotas,
  estadoAbrir,
  linhaDaRota,
  listasDasRotas,
  notaDoIntervalo,
  textoSemAnteriores,
  textoSemProximas,
} from './listaRotas';
import { criarEstadoRede } from './rede';

// frontend/src/lib/crm → raiz do repositório.
const RAIZ = path.join(__dirname, '..', '..', '..', '..');
const VALIDADOR_PY = path.join(RAIZ, 'backend', 'crm', 'dominio', 'validador_rota.py');

// 2026-10-10 é um sábado: o 11 é "Amanhã" e o 12 "seg 12/10". O servidor manda hoje − 14 e hoje + 60.
const HOJE = '2026-10-10';
const DE = '2026-09-26';
const ATE = '2026-12-09';

const resumo = (data, estadoEfetivo, paragens, estado = estadoEfetivo) => ({
  id: `rota-${data}`, data, estado, estado_efetivo: estadoEfetivo, paragens,
});

// O `GET /rotas` (plano F3 §4): por `data`.
const LISTA = Object.freeze({
  hoje: HOJE,
  de: DE,
  ate: ATE,
  rotas: [
    resumo('2026-09-30', 'concluida', 4, 'rascunho'),
    resumo('2026-10-08', 'concluida', 7, 'planeada'),
    resumo('2026-10-10', 'rascunho', 5),
    resumo('2026-10-12', 'planeada', 9),
    resumo('2026-10-20', 'rascunho', 1),
  ],
});

const copia = (valor) => JSON.parse(JSON.stringify(valor));

function congeladaAFundo(valor) {
  if (valor === null || typeof valor !== 'object') return true;
  if (!Object.isFrozen(valor)) return false;
  return Object.values(valor).every(congeladaAFundo);
}

// Uma promessa controlada à mão.
function adiada() {
  let resolver;
  let rejeitar;
  const promessa = new Promise((res, rej) => {
    resolver = res;
    rejeitar = rej;
  });
  return { promessa, resolver, rejeitar };
}

const esperar = () => new Promise((res) => {
  setTimeout(res, 0);
});

// Uma rede falsa (o `criarEstadoRede` verdadeiro sobre uma janela e um navigator falsos).
function redeFalsa(online = true) {
  const ouvintes = {};
  const janela = { addEventListener: (nome, fn) => { ouvintes[nome] = fn; } };
  const navegador = { onLine: online };
  const rede = criarEstadoRede(janela, navegador);
  return {
    rede,
    cair() {
      navegador.onLine = false;
      ouvintes.offline();
    },
    voltar() {
      navegador.onLine = true;
      ouvintes.online();
    },
  };
}

function montar({ base = '/crm', rede = null } = {}) {
  const pedidos = [];
  const listarRotas = jest.fn(() => {
    const pedido = adiada();
    pedidos.push(pedido);
    return pedido.promessa;
  });
  const navegar = jest.fn();
  const vistas = [];
  const aoMudarVista = jest.fn((vista) => vistas.push(vista));
  const lista = criarListaRotas({
    api: { listarRotas }, rede, base, navegar, aoMudarVista,
  });
  return {
    lista, listarRotas, navegar, aoMudarVista, vistas, pedidos,
  };
}

// Inicia e responde ao primeiro pedido com a lista dada (sem ela, a LISTA; um `undefined` dado conta).
async function pronto(opcoes = {}, ...dada) {
  const resposta = dada.length > 0 ? dada[0] : copia(LISTA);
  const m = montar(opcoes);
  m.lista.iniciar();
  m.pedidos[0].resolver(resposta);
  await esperar();
  return m;
}

// --- Constantes ----------------------------------------------------------------------------------

describe('textos', () => {
  test('os textos da página', () => {
    expect(TITULO_ROTAS).toBe('Rotas');
    expect(TEXTO_ABRIR).toBe('Abrir');
    expect(TEXTO_HOJE).toBe('Hoje');
    expect(TITULO_PROXIMAS).toBe('Próximas');
    expect(TITULO_ANTERIORES).toBe('Anteriores');
    expect(TEXTO_SEM_PROXIMAS).toBe('Não há rotas marcadas.');
    expect(TEXTO_SEM_ANTERIORES).toBe('Não houve rotas.');
  });

  test('a mensagem do horizonte é a do servidor (validador_rota.MENSAGEM_HORIZONTE)', () => {
    const texto = fs.readFileSync(VALIDADOR_PY, 'utf8');
    const m = /^MENSAGEM_HORIZONTE = "([^"]+)"$/m.exec(texto);
    expect(m).not.toBeNull();
    expect(MENSAGEM_HORIZONTE).toBe(m[1]);
    expect(MENSAGEM_HORIZONTE).toBe('Escolha um dia até um ano a partir de hoje.');
  });

  test('o intervalo da lista é o do servidor por omissão: hoje − 14 e hoje + 60 (os textos do teste)', () => {
    const texto = fs.readFileSync(VALIDADOR_PY, 'utf8');
    expect(texto).toMatch(/^INTERVALO_DIAS_ANTES = 14$/m);
    expect(texto).toMatch(/^INTERVALO_DIAS_DEPOIS = 60$/m);
  });

  test('o módulo nunca lê o relógio nem a língua do browser (o "hoje" é o do servidor)', () => {
    const texto = fs.readFileSync(path.join(__dirname, 'listaRotas.js'), 'utf8');
    for (const proibido of [/\bDate\b/, /\bIntl\b/, /toLocale/, /\bperformance\b/, /setTimeout|setInterval/]) {
      expect(texto).not.toMatch(proibido);
    }
  });
});

// --- linhaDaRota ---------------------------------------------------------------------------------

describe('linhaDaRota', () => {
  const linha = (rota, base = '/crm') => linhaDaRota(rota, { hoje: HOJE, base });

  test('o exemplo do plano: "seg 12/10 · Planeada · 9 paragens", ligada ao planeador desse dia', () => {
    expect(linha(resumo('2026-10-12', 'planeada', 9))).toEqual({
      data: '2026-10-12',
      caminho: '/crm/rotas/2026-10-12',
      dia: 'seg 12/10',
      estado: 'Planeada',
      paragens: '9 paragens',
      texto: 'seg 12/10 · Planeada · 9 paragens',
      eHoje: false,
    });
  });

  test('hoje e amanhã pelo nome, com o hoje do servidor', () => {
    expect(linha(resumo('2026-10-10', 'rascunho', 5))).toMatchObject({
      dia: 'Hoje', texto: 'Hoje · Rascunho · 5 paragens', eHoje: true,
    });
    expect(linha(resumo('2026-10-11', 'em_curso', 3))).toMatchObject({
      dia: 'Amanhã', texto: 'Amanhã · Em curso · 3 paragens', eHoje: false,
    });
  });

  test('o estado é o efetivo: uma rota planeada de um dia que passou é "Concluída"', () => {
    expect(linha(resumo('2026-10-08', 'concluida', 7, 'planeada'))).toMatchObject({
      dia: 'qui 08/10', estado: 'Concluída', texto: 'qui 08/10 · Concluída · 7 paragens',
    });
  });

  test('as paragens no singular, no plural e sem nenhuma', () => {
    expect(linha(resumo('2026-10-12', 'rascunho', 1)).texto).toBe('seg 12/10 · Rascunho · 1 paragem');
    expect(linha(resumo('2026-10-12', 'rascunho', 0)).texto).toBe('seg 12/10 · Rascunho · sem paragens');
    expect(linha(resumo('2026-10-12', 'rascunho', 48)).paragens).toBe('48 paragens');
  });

  test('um estado desconhecido ou uma contagem estragada ficam de fora do texto', () => {
    for (const estado of ['inventado', null, undefined, 'constructor', '__proto__', 7]) {
      const l = linha(resumo('2026-10-12', estado, 9));
      expect(l.estado).toBeNull();
      expect(l.texto).toBe('seg 12/10 · 9 paragens');
    }
    for (const paragens of [-1, 1.5, '3', null, undefined, Number.NaN, Infinity, true]) {
      const l = linha(resumo('2026-10-12', 'planeada', paragens));
      expect(l.paragens).toBeNull();
      expect(l.texto).toBe('seg 12/10 · Planeada');
    }
    expect(linha(resumo('2026-10-12', 'x', 'y')).texto).toBe('seg 12/10');
  });

  test('o caminho é o da casa do CRM em que se está', () => {
    expect(linha(resumo('2026-10-12', 'planeada', 9), '/admin/crm').caminho).toBe('/admin/crm/rotas/2026-10-12');
  });

  test('uma linha estragada, um dia que não existe ou um hoje inválido dão null', () => {
    for (const estragada of [null, undefined, 'rota', 3, [], [resumo('2026-10-12', 'planeada', 9)]]) {
      expect(linha(estragada)).toBeNull();
    }
    for (const data of ['2026-02-30', '2026-10-12\n', '12/10/2026', '', null, undefined, 20261012]) {
      expect(linha(resumo(data, 'planeada', 9))).toBeNull();
    }
    expect(linhaDaRota(resumo('2026-10-12', 'planeada', 9), { hoje: '2026-02-30', base: '/crm' })).toBeNull();
    expect(linhaDaRota(resumo('2026-10-12', 'planeada', 9), { hoje: null, base: '/crm' })).toBeNull();
    expect(linhaDaRota(resumo('2026-10-12', 'planeada', 9))).toBeNull();
  });
});

// --- listasDasRotas ------------------------------------------------------------------------------

describe('listasDasRotas', () => {
  const datas = (linhas) => linhas.map((l) => l.data);

  test('"Próximas" de hoje em diante (a mais perto primeiro) e "Anteriores" (a mais recente primeiro)', () => {
    const { proximas, anteriores } = listasDasRotas(LISTA, '/crm');
    expect(datas(proximas)).toEqual(['2026-10-10', '2026-10-12', '2026-10-20']);
    expect(datas(anteriores)).toEqual(['2026-10-08', '2026-09-30']);
    expect(proximas[0]).toEqual(linhaDaRota(LISTA.rotas[2], { hoje: HOJE, base: '/crm' }));
    expect(anteriores[1].texto).toBe('qua 30/09 · Concluída · 4 paragens');
  });

  test('venha a lista por que ordem vier, e uma só linha por dia (a primeira)', () => {
    const rotas = [
      resumo('2026-10-20', 'rascunho', 1),
      resumo('2026-09-30', 'concluida', 4),
      resumo('2026-10-12', 'planeada', 9),
      resumo('2026-10-08', 'concluida', 7),
      resumo('2026-10-12', 'rascunho', 2),
      resumo('2026-10-10', 'rascunho', 5),
    ];
    const { proximas, anteriores } = listasDasRotas({ hoje: HOJE, rotas }, '/crm');
    expect(datas(proximas)).toEqual(['2026-10-10', '2026-10-12', '2026-10-20']);
    expect(proximas[1].texto).toBe('seg 12/10 · Planeada · 9 paragens');
    expect(datas(anteriores)).toEqual(['2026-10-08', '2026-09-30']);
  });

  test('as linhas estragadas saem; sem lista ou sem um hoje válido, as duas ficam vazias', () => {
    const rotas = [null, 'x', resumo('2026-02-30', 'planeada', 3), resumo('2026-10-12', 'planeada', 9), []];
    expect(datas(listasDasRotas({ hoje: HOJE, rotas }, '/crm').proximas)).toEqual(['2026-10-12']);
    for (const lista of [{ hoje: HOJE, rotas: null }, { hoje: HOJE, rotas: {} }, { hoje: HOJE }, null, undefined,
      { hoje: '2026-13-01', rotas: LISTA.rotas }, { rotas: LISTA.rotas }]) {
      expect(listasDasRotas(lista, '/crm')).toEqual({ proximas: [], anteriores: [] });
    }
  });
});

// --- Textos das listas vazias e do intervalo -----------------------------------------------------

describe('textos das listas vazias e do intervalo', () => {
  test('sem próximas: até ao último dia da lista; sem anteriores: desde o primeiro', () => {
    expect(textoSemProximas(ATE, HOJE)).toBe('Não há rotas até qua 09/12.');
    expect(textoSemAnteriores(DE, HOJE)).toBe('Não houve rotas desde sáb 26/09.');
  });

  test('hoje e amanhã a meio da frase em minúsculas', () => {
    expect(textoSemProximas('2026-10-11', HOJE)).toBe('Não há rotas até amanhã.');
    expect(textoSemProximas(HOJE, HOJE)).toBe('Não há rotas até hoje.');
    expect(textoSemAnteriores(HOJE, HOJE)).toBe('Não houve rotas desde hoje.');
  });

  test('sem dias válidos, os textos gerais', () => {
    for (const [dia, hoje] of [[null, HOJE], ['2026-02-30', HOJE], [ATE, null], [ATE, '2026-02-30'], [undefined, undefined]]) {
      expect(textoSemProximas(dia, hoje)).toBe(TEXTO_SEM_PROXIMAS);
      expect(textoSemAnteriores(dia, hoje)).toBe(TEXTO_SEM_ANTERIORES);
    }
  });

  test('a nota do intervalo mostrado, ou null', () => {
    expect(notaDoIntervalo(LISTA)).toBe('Rotas de sáb 26/09 a qua 09/12. Para outro dia, escolha-o acima.');
    expect(notaDoIntervalo({ hoje: HOJE, de: HOJE, ate: '2026-10-11' }))
      .toBe('Rotas de hoje a amanhã. Para outro dia, escolha-o acima.');
    for (const lista of [{ ...LISTA, de: null }, { ...LISTA, ate: '2026-12-32' }, { ...LISTA, hoje: 'ontem' }, null, undefined]) {
      expect(notaDoIntervalo(lista)).toBeNull();
    }
  });
});

// --- estadoAbrir ---------------------------------------------------------------------------------

describe('estadoAbrir', () => {
  const ativo = { ativo: true, texto: TEXTO_ABRIR, falta: null };
  const semDia = { ativo: false, texto: TEXTO_ABRIR, falta: TEXTO_FALTA_DIA };

  test('um dia que existe abre, também do passado (só de leitura) e até hoje + 365', () => {
    expect(TEXTO_FALTA_DIA).toBe('Escolha o dia.');
    for (const data of [HOJE, '2026-10-12', '2025-01-01', '2026-09-26', '2027-10-10']) {
      expect(estadoAbrir({ data, hoje: HOJE })).toEqual(ativo);
    }
  });

  test('depois de hoje + 365, a mensagem do servidor', () => {
    expect(estadoAbrir({ data: '2027-10-11', hoje: HOJE }))
      .toEqual({ ativo: false, texto: TEXTO_ABRIR, falta: MENSAGEM_HORIZONTE });
    expect(estadoAbrir({ data: '9999-12-31', hoje: HOJE }).falta).toBe(MENSAGEM_HORIZONTE);
  });

  test('sem o hoje do servidor ainda, um dia que existe abre (o planeador diz o resto)', () => {
    expect(estadoAbrir({ data: '2030-01-01', hoje: null })).toEqual(ativo);
    expect(estadoAbrir({ data: '2030-01-01' })).toEqual(ativo);
  });

  test('um dia vazio, mal escrito ou que não existe: "Escolha o dia."', () => {
    for (const data of ['', '2026-02-30', '10/10/2026', '2026-10-1', ' 2026-10-10', null, undefined, 20261010]) {
      expect(estadoAbrir({ data, hoje: HOJE })).toEqual(semDia);
    }
    expect(estadoAbrir()).toEqual(semDia);
  });
});

// --- criarListaRotas -----------------------------------------------------------------------------

describe('criarListaRotas: carregar', () => {
  test('criar não pede nada; a primeira vista é a de "a carregar", congelada a fundo', () => {
    const { lista, listarRotas, aoMudarVista } = montar();
    expect(listarRotas).not.toHaveBeenCalled();
    expect(aoMudarVista).not.toHaveBeenCalled();
    expect(lista.vista).toEqual({
      estado: 'a_carregar',
      titulo: TITULO_ROTAS,
      falha: null,
      data: '',
      max: null,
      abrir: { ativo: false, texto: TEXTO_ABRIR, falta: TEXTO_FALTA_DIA },
      hoje: { ativo: false, texto: TEXTO_HOJE, caminho: null },
      proximas: null,
      anteriores: null,
      nota: null,
    });
    expect(congeladaAFundo(lista.vista)).toBe(true);
  });

  test('iniciar pede a lista sem intervalo, uma só vez', () => {
    const { lista, listarRotas } = montar();
    lista.iniciar();
    lista.iniciar();
    expect(listarRotas).toHaveBeenCalledTimes(1);
    expect(listarRotas.mock.calls[0]).toEqual([]);
    expect(lista.vista.estado).toBe('a_carregar');
  });

  test('com a lista: as duas listas, o dia de hoje no campo, o máximo e "Hoje"', async () => {
    const { lista, aoMudarVista, vistas } = await pronto();
    const { vista } = lista;
    expect(vista.estado).toBe('pronto');
    expect(vista.falha).toBeNull();
    expect(vista.data).toBe(HOJE);
    expect(vista.max).toBe('2027-10-10');
    expect(vista.abrir).toEqual({ ativo: true, texto: TEXTO_ABRIR, falta: null });
    expect(vista.hoje).toEqual({ ativo: true, texto: TEXTO_HOJE, caminho: '/crm/rotas/2026-10-10' });
    expect(vista.proximas).toEqual({
      titulo: TITULO_PROXIMAS, linhas: listasDasRotas(LISTA, '/crm').proximas, vazia: null,
    });
    expect(vista.anteriores).toEqual({
      titulo: TITULO_ANTERIORES, linhas: listasDasRotas(LISTA, '/crm').anteriores, vazia: null,
    });
    expect(vista.nota).toBe(notaDoIntervalo(LISTA));
    expect(congeladaAFundo(vista)).toBe(true);
    expect(aoMudarVista).toHaveBeenLastCalledWith(vista);
    // Uma vista nova a cada mudança: "a carregar" e a lista.
    expect(vistas.map((v) => v.estado)).toEqual(['a_carregar', 'pronto']);
    expect(vistas[0]).not.toBe(vistas[1]);
  });

  test('na casa do admin, os caminhos são os do /admin/crm', async () => {
    const { lista } = await pronto({ base: '/admin/crm' });
    expect(lista.vista.hoje.caminho).toBe('/admin/crm/rotas/2026-10-10');
    expect(lista.vista.proximas.linhas[1].caminho).toBe('/admin/crm/rotas/2026-10-12');
  });

  test('sem rotas: as duas listas vazias com o texto do intervalo', async () => {
    const { lista } = await pronto({}, { hoje: HOJE, de: DE, ate: ATE, rotas: [] });
    expect(lista.vista.proximas).toEqual({ titulo: TITULO_PROXIMAS, linhas: [], vazia: 'Não há rotas até qua 09/12.' });
    expect(lista.vista.anteriores)
      .toEqual({ titulo: TITULO_ANTERIORES, linhas: [], vazia: 'Não houve rotas desde sáb 26/09.' });
  });

  test('só uma das listas vazia', async () => {
    const soAnteriores = await pronto({}, { ...copia(LISTA), rotas: [resumo('2026-10-08', 'concluida', 7)] });
    expect(soAnteriores.lista.vista.proximas.vazia).toBe('Não há rotas até qua 09/12.');
    expect(soAnteriores.lista.vista.anteriores.vazia).toBeNull();
    const soProximas = await pronto({}, { ...copia(LISTA), rotas: [resumo('2026-10-10', 'rascunho', 0)] });
    expect(soProximas.lista.vista.proximas.vazia).toBeNull();
    expect(soProximas.lista.vista.anteriores.vazia).toBe('Não houve rotas desde sáb 26/09.');
  });

  test('as rotas que não vêm numa lista contam como nenhuma; sem de/ate, os textos gerais e sem nota', async () => {
    const { lista } = await pronto({}, { hoje: HOJE, rotas: 'nada' });
    expect(lista.vista.estado).toBe('pronto');
    expect(lista.vista.proximas.vazia).toBe(TEXTO_SEM_PROXIMAS);
    expect(lista.vista.anteriores.vazia).toBe(TEXTO_SEM_ANTERIORES);
    expect(lista.vista.nota).toBeNull();
  });

  test('uma resposta sem um hoje válido é o erro inesperado', async () => {
    for (const resposta of [null, undefined, 'x', {}, { ...copia(LISTA), hoje: '2026-02-30' }, { ...copia(LISTA), hoje: 20261010 }]) {
      const { lista } = await pronto({}, resposta);
      expect(lista.vista.estado).toBe('falha');
      expect(lista.vista.falha).toEqual({ mensagem: MENSAGEM_ERRO_INESPERADO, aTentar: false });
      expect(lista.vista.hoje).toEqual({ ativo: false, texto: TEXTO_HOJE, caminho: null });
      expect(lista.vista.max).toBeNull();
    }
  });
});

describe('criarListaRotas: falha e "Tentar novamente"', () => {
  async function falhada(...dado) {
    const erro = dado.length > 0 ? dado[0] : new ErroCrm({ codigo: 'sem_rede', mensagem: MENSAGEM_SEM_REDE });
    const m = montar();
    m.lista.iniciar();
    m.pedidos[0].rejeitar(erro);
    await esperar();
    return m;
  }

  test('a falha mostra a mensagem do erro, sem listas nem "Hoje"', async () => {
    const { lista } = await falhada();
    expect(lista.vista.estado).toBe('falha');
    expect(lista.vista.falha).toEqual({ mensagem: MENSAGEM_SEM_REDE, aTentar: false });
    expect(lista.vista.proximas).toBeNull();
    expect(lista.vista.anteriores).toBeNull();
    expect(lista.vista.nota).toBeNull();
    expect(lista.vista.hoje.ativo).toBe(false);
    expect(congeladaAFundo(lista.vista)).toBe(true);
  });

  test('um erro sem mensagem dá o erro inesperado', async () => {
    for (const erro of [new Error(''), undefined, 'x', { mensagem: '' }]) {
      const { lista } = await falhada(erro);
      expect(lista.vista.falha.mensagem).toBe(MENSAGEM_ERRO_INESPERADO);
    }
  });

  test('"Tentar novamente" pede outra vez (um toque, um pedido) e mostra a lista', async () => {
    const { lista, listarRotas, pedidos } = await falhada();
    lista.tentarDeNovo();
    lista.tentarDeNovo();
    expect(listarRotas).toHaveBeenCalledTimes(2);
    expect(listarRotas.mock.calls[1]).toEqual([]);
    expect(lista.vista.estado).toBe('falha');
    expect(lista.vista.falha).toEqual({ mensagem: MENSAGEM_SEM_REDE, aTentar: true });
    pedidos[1].resolver(copia(LISTA));
    await esperar();
    expect(lista.vista.estado).toBe('pronto');
    expect(lista.vista.falha).toBeNull();
    lista.tentarDeNovo();
    expect(listarRotas).toHaveBeenCalledTimes(2);
  });

  test('"Tentar novamente" que falha outra vez mostra a mensagem nova', async () => {
    const { lista, pedidos } = await falhada();
    lista.tentarDeNovo();
    pedidos[1].rejeitar(new ErroCrm({ codigo: 'erro_interno', mensagem: 'Outra coisa.' }));
    await esperar();
    expect(lista.vista.falha).toEqual({ mensagem: 'Outra coisa.', aTentar: false });
  });

  test('sem falha, "Tentar novamente" não pede nada (nem a carregar, nem com a lista)', async () => {
    const { lista, listarRotas } = montar();
    lista.tentarDeNovo();
    expect(listarRotas).not.toHaveBeenCalled();
    lista.iniciar();
    lista.tentarDeNovo();
    expect(listarRotas).toHaveBeenCalledTimes(1);
  });

  test('iniciar outra vez depois de uma falha não pede (só o "Tentar novamente")', async () => {
    const { lista, listarRotas } = await falhada();
    lista.iniciar();
    expect(listarRotas).toHaveBeenCalledTimes(1);
    expect(lista.vista.falha.aTentar).toBe(false);
  });

  test('antes de iniciar, "Tentar novamente" não pede nada', () => {
    const { lista, listarRotas } = montar();
    lista.tentarDeNovo();
    expect(listarRotas).not.toHaveBeenCalled();
  });
});

describe('criarListaRotas: o dia, "Abrir" e "Hoje"', () => {
  test('mudar o dia e abrir navega para o planeador desse dia', async () => {
    const { lista, navegar } = await pronto();
    lista.mudarDia('2026-10-12');
    expect(lista.vista.data).toBe('2026-10-12');
    lista.abrir();
    expect(navegar).toHaveBeenCalledTimes(1);
    expect(navegar).toHaveBeenCalledWith('/crm/rotas/2026-10-12');
  });

  test('com o dia de hoje no campo, abrir leva a hoje; na casa do admin, ao /admin/crm', async () => {
    const { lista, navegar } = await pronto({ base: '/admin/crm' });
    lista.abrir();
    expect(navegar).toHaveBeenCalledWith('/admin/crm/rotas/2026-10-10');
  });

  test('um dia do passado também abre (só de leitura)', async () => {
    const { lista, navegar } = await pronto();
    lista.mudarDia('2025-03-01');
    lista.abrir();
    expect(navegar).toHaveBeenCalledWith('/crm/rotas/2025-03-01');
  });

  test('um dia vazio, que não existe ou depois do horizonte não abre e diz porquê', async () => {
    const { lista, navegar } = await pronto();
    lista.mudarDia('');
    expect(lista.vista.abrir).toEqual({ ativo: false, texto: TEXTO_ABRIR, falta: TEXTO_FALTA_DIA });
    lista.abrir();
    lista.mudarDia('2026-02-30');
    lista.abrir();
    lista.mudarDia('2027-10-11');
    expect(lista.vista.abrir.falta).toBe(MENSAGEM_HORIZONTE);
    lista.abrir();
    expect(navegar).not.toHaveBeenCalled();
    lista.mudarDia('2027-10-10');
    lista.abrir();
    expect(navegar).toHaveBeenCalledWith('/crm/rotas/2027-10-10');
  });

  test('o que não é texto não muda o dia', async () => {
    const { lista, aoMudarVista } = await pronto();
    const chamadas = aoMudarVista.mock.calls.length;
    for (const valor of [null, undefined, 20261012, {}, ['2026-10-12']]) lista.mudarDia(valor);
    expect(lista.vista.data).toBe(HOJE);
    expect(aoMudarVista).toHaveBeenCalledTimes(chamadas);
  });

  test('o dia escrito antes de a lista chegar fica (também vazio); senão, entra o de hoje', async () => {
    const escrito = montar();
    escrito.lista.iniciar();
    escrito.lista.mudarDia('2026-11-02');
    escrito.pedidos[0].resolver(copia(LISTA));
    await esperar();
    expect(escrito.lista.vista.data).toBe('2026-11-02');

    const apagado = montar();
    apagado.lista.iniciar();
    apagado.lista.mudarDia('2026-11-02');
    apagado.lista.mudarDia('');
    apagado.pedidos[0].resolver(copia(LISTA));
    await esperar();
    expect(apagado.lista.vista.data).toBe('');
  });

  test('antes de a lista chegar, um dia que existe abre; "Hoje" não tem para onde ir', () => {
    const { lista, navegar } = montar();
    lista.iniciar();
    expect(lista.vista.hoje).toEqual({ ativo: false, texto: TEXTO_HOJE, caminho: null });
    lista.mudarDia('2026-10-12');
    expect(lista.vista.abrir.ativo).toBe(true);
    lista.abrir();
    expect(navegar).toHaveBeenCalledWith('/crm/rotas/2026-10-12');
  });

  test('"Hoje" leva à rota de hoje do servidor, seja qual for o dia no campo', async () => {
    const { lista, navegar } = await pronto();
    lista.mudarDia('2026-10-12');
    expect(lista.vista.hoje).toEqual({ ativo: true, texto: TEXTO_HOJE, caminho: '/crm/rotas/2026-10-10' });
    expect(navegar).not.toHaveBeenCalled();
  });

  test('com a lista falhada, "Hoje" não leva a lado nenhum e o campo continua a abrir', async () => {
    const m = montar();
    m.lista.iniciar();
    m.pedidos[0].rejeitar(new ErroCrm({ codigo: 'sem_rede', mensagem: MENSAGEM_SEM_REDE }));
    await esperar();
    expect(m.lista.vista.hoje.caminho).toBeNull();
    m.lista.mudarDia('2026-10-12');
    m.lista.abrir();
    expect(m.navegar).toHaveBeenCalledWith('/crm/rotas/2026-10-12');
  });

  test('sem o `navegar`, abrir não rebenta', async () => {
    const lista = criarListaRotas({ api: { listarRotas: () => Promise.resolve(copia(LISTA)) }, base: '/crm' });
    lista.iniciar();
    await esperar();
    expect(lista.vista.abrir.ativo).toBe(true);
    expect(() => lista.abrir()).not.toThrow();
  });
});

describe('criarListaRotas: a rede', () => {
  test('a rede que volta pede outra vez a lista que falhou (uma vez)', async () => {
    const r = redeFalsa();
    const m = montar({ rede: r.rede });
    m.lista.iniciar();
    m.pedidos[0].rejeitar(new ErroCrm({ codigo: 'sem_rede', mensagem: MENSAGEM_SEM_REDE }));
    await esperar();
    r.cair();
    expect(m.listarRotas).toHaveBeenCalledTimes(1);
    r.voltar();
    r.voltar();
    expect(m.listarRotas).toHaveBeenCalledTimes(2);
    m.pedidos[1].resolver(copia(LISTA));
    await esperar();
    expect(m.lista.vista.estado).toBe('pronto');
    r.voltar();
    expect(m.listarRotas).toHaveBeenCalledTimes(2);
  });

  test('com a lista a carregar ou já carregada, a rede não pede nada', async () => {
    const r = redeFalsa();
    const m = montar({ rede: r.rede });
    m.lista.iniciar();
    r.cair();
    r.voltar();
    expect(m.listarRotas).toHaveBeenCalledTimes(1);
  });

  test('antes de iniciar não se ouve a rede; destruir cancela o ouvinte', async () => {
    const r = redeFalsa();
    const m = montar({ rede: r.rede });
    r.cair();
    r.voltar();
    expect(m.listarRotas).not.toHaveBeenCalled();
    m.lista.iniciar();
    m.pedidos[0].rejeitar(new ErroCrm({ codigo: 'sem_rede', mensagem: MENSAGEM_SEM_REDE }));
    await esperar();
    m.lista.destruir();
    r.voltar();
    expect(m.listarRotas).toHaveBeenCalledTimes(1);
  });
});

describe('criarListaRotas: destruir', () => {
  // Uma rede que conta os ouvintes e os cancelamentos.
  function redeQueConta() {
    const cancelar = jest.fn();
    return { rede: { online: () => true, aoMudar: jest.fn(() => cancelar) }, cancelar };
  }

  test('destruir cancela o ouvinte da rede (uma vez registado, uma vez cancelado)', () => {
    const { rede, cancelar } = redeQueConta();
    const { lista } = montar({ rede });
    lista.iniciar();
    lista.iniciar();
    expect(rede.aoMudar).toHaveBeenCalledTimes(1);
    expect(cancelar).not.toHaveBeenCalled();
    lista.destruir();
    expect(cancelar).toHaveBeenCalledTimes(1);
  });

  test('iniciar depois de destruir não ouve a rede', () => {
    const { rede } = redeQueConta();
    const { lista } = montar({ rede });
    lista.destruir();
    lista.iniciar();
    expect(rede.aoMudar).not.toHaveBeenCalled();
  });


  test('as respostas que chegam depois de destruir não mudam nada (a dar certo e a falhar)', async () => {
    for (const responder of [(p) => p.resolver(copia(LISTA)), (p) => p.rejeitar(new ErroCrm({ codigo: 'x', mensagem: 'm' }))]) {
      const m = montar();
      m.lista.iniciar();
      const antes = m.lista.vista;
      const chamadas = m.aoMudarVista.mock.calls.length;
      m.lista.destruir();
      responder(m.pedidos[0]);
      await esperar();
      expect(m.lista.vista).toBe(antes);
      expect(m.aoMudarVista).toHaveBeenCalledTimes(chamadas);
    }
  });

  test('depois de destruir, nada pede, muda ou navega', async () => {
    const m = await pronto();
    m.lista.destruir();
    const antes = m.lista.vista;
    m.lista.mudarDia('2026-10-12');
    m.lista.abrir();
    m.lista.tentarDeNovo();
    expect(m.lista.vista).toBe(antes);
    expect(m.navegar).not.toHaveBeenCalled();

    const novo = montar();
    novo.lista.destruir();
    novo.lista.iniciar();
    expect(novo.listarRotas).not.toHaveBeenCalled();
  });

  test('destruir depois de uma falha: "Tentar novamente" e a rede já não pedem', async () => {
    const r = redeFalsa();
    const m = montar({ rede: r.rede });
    m.lista.iniciar();
    m.pedidos[0].rejeitar(new ErroCrm({ codigo: 'sem_rede', mensagem: MENSAGEM_SEM_REDE }));
    await esperar();
    expect(m.lista.vista.estado).toBe('falha');
    m.lista.destruir();
    m.lista.tentarDeNovo();
    r.voltar();
    expect(m.listarRotas).toHaveBeenCalledTimes(1);
  });

  test('a falha depois de destruir não deixa "Tentar novamente" pedir', async () => {
    const m = montar();
    m.lista.iniciar();
    m.lista.destruir();
    m.pedidos[0].rejeitar(new ErroCrm({ codigo: 'sem_rede', mensagem: MENSAGEM_SEM_REDE }));
    await esperar();
    m.lista.tentarDeNovo();
    expect(m.listarRotas).toHaveBeenCalledTimes(1);
  });
});
