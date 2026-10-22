/**
 * "ADICIONAR À ROTA" — as regras do diálogo do cartão do mapa, sem DOM (plano F3 T3.34; o diálogo é da T3.40).
 *
 * O cartão de uma loja no mapa tem "Adicionar à rota" (desenho original §6.3: "escolhe o dia"). O
 * controlador (`criarAdicionarARota`, no molde do `criarFabrica`) pede a lista das rotas (`listarRotas()`,
 * sem intervalo: o servidor usa hoje − 14 e hoje + 60), propõe o dia (a primeira rota que ainda se pode
 * mudar a partir de hoje, senão hoje), mostra até 5 atalhos ("Hoje · 5 paragens", "ter 13/10 · 8
 * paragens"), o campo da data (`min` = o hoje do servidor) e o motivo pré-escolhido pela fase
 * (`motivoPorFase`), e grava com `adicionarParagem(data, {loja_id, motivo})`, **sem** a versão (o servidor
 * lê, verifica e tenta até 3 vezes). Com sucesso, o aviso "Adicionada à rota de ter 13/10 (9 paragens)."
 * com a ação "Abrir rota"; quando a rota tinha horas calculadas, também "Abra a rota para recalcular as
 * horas." (correção "T3.16 / T3.21 / T3.32", a parte da T3.40). Os erros (`ja_na_rota`, `rota_cheia`,
 * `rota_fechada`, `sem_rede`…) mostram a mensagem do servidor; um pedido de cada vez.
 */
import fs from 'fs';
import path from 'path';

import {
  ATALHOS_MAXIMO,
  ESTADOS_EDITAVEIS,
  MAXIMO_DIAS_FUTURO,
  TEXTO_ABRIR_ROTA,
  TEXTO_ADICIONAR,
  TEXTO_A_ADICIONAR,
  TEXTO_A_CARREGAR_DIAS,
  TEXTO_DIA,
  TEXTO_FALTA_DIA,
  TEXTO_MOTIVO,
  TEXTO_RECALCULAR_NA_ROTA,
  TITULO_ADICIONAR_A_ROTA,
  atalhosDosDias,
  criarAdicionarARota,
  diaPorOmissao,
  estadoAdicionar,
  textoAdicionada,
  textoParagens,
} from './adicionarARota';
import { ErroCrm, MENSAGEM_ERRO_INESPERADO, MENSAGEM_SEM_REDE } from './api';
import { criarEstadoRede } from './rede';

// frontend/src/lib/crm → raiz do repositório.
const RAIZ = path.join(__dirname, '..', '..', '..', '..');
const DATAS_PY = path.join(RAIZ, 'backend', 'crm', 'dominio', 'datas.py');
const ROTAS_PY = path.join(RAIZ, 'backend', 'crm', 'dominio', 'rotas.py');

// 2026-10-11 é um domingo: o 12 é "Amanhã" e o 13 "ter 13/10".
const HOJE = '2026-10-11';
const LOJA = Object.freeze({ id: 'loja-1', nome: 'Café Central', fase: 'contactada' });

const copia = (valor) => JSON.parse(JSON.stringify(valor));
const resumo = (data, estadoEfetivo, paragens, estado = estadoEfetivo) => ({
  id: `rota-${data}`, data, estado, estado_efetivo: estadoEfetivo, paragens,
});

// O `GET /rotas` (plano F3 §4): por `data`.
const LISTA = Object.freeze({
  hoje: HOJE,
  de: '2026-09-27',
  ate: '2026-12-10',
  rotas: [
    resumo('2026-10-09', 'concluida', 7, 'planeada'),
    resumo('2026-10-13', 'rascunho', 8),
    resumo('2026-10-15', 'planeada', 1),
  ],
});

function paragens(n) {
  return Array.from({ length: n }, (_, i) => ({ id: `p${i}`, loja_id: `l${i}`, seccao: 'rota', numero: i + 1 }));
}

// A Rota que o `POST /rotas/{data}/paragens` devolve (201).
function rotaAdicionada(extra = {}) {
  return {
    id: 'rota-2026-10-13',
    data: '2026-10-13',
    existe: true,
    estado: 'rascunho',
    estado_efetivo: 'rascunho',
    editavel: true,
    versao: 5,
    hoje: HOJE,
    calculo_disponivel: true,
    calculo: null,
    paragens: paragens(9),
    ...extra,
  };
}

function congeladaAFundo(valor) {
  if (valor === null || typeof valor !== 'object') return true;
  if (!Object.isFrozen(valor)) return false;
  return Object.values(valor).every(congeladaAFundo);
}

// --- Textos e constantes ---------------------------------------------------------------------------

test('os textos exatos do diálogo', () => {
  expect(TITULO_ADICIONAR_A_ROTA).toBe('Adicionar à rota');
  expect(TEXTO_A_CARREGAR_DIAS).toBe('A carregar as rotas…');
  expect(TEXTO_DIA).toBe('Dia');
  expect(TEXTO_MOTIVO).toBe('Motivo');
  expect(TEXTO_ADICIONAR).toBe('Adicionar');
  expect(TEXTO_A_ADICIONAR).toBe('A adicionar…');
  expect(TEXTO_ABRIR_ROTA).toBe('Abrir rota');
  expect(TEXTO_FALTA_DIA).toBe('Escolha o dia.');
  expect(TEXTO_RECALCULAR_NA_ROTA).toBe('Abra a rota para recalcular as horas.');
  expect(ATALHOS_MAXIMO).toBe(5);
  expect([...ESTADOS_EDITAVEIS]).toEqual(['rascunho', 'planeada']);
  expect(Object.isFrozen(ESTADOS_EDITAVEIS)).toBe(true);
});

describe('igual ao servidor, lido dos próprios ficheiros', () => {
  // Falha, e não salta, se o ficheiro não estiver lá.
  const ler = (ficheiro) => {
    expect(fs.existsSync(ficheiro)).toBe(true);
    return fs.readFileSync(ficheiro, 'utf8');
  };

  test('MAXIMO_DIAS_FUTURO é o do backend/crm/dominio/datas.py', () => {
    const linhas = [...ler(DATAS_PY).matchAll(/^MAXIMO_DIAS_FUTURO = ([0-9]+)$/gm)];
    expect(linhas).toHaveLength(1);
    expect(MAXIMO_DIAS_FUTURO).toBe(Number(linhas[0][1]));
    expect(MAXIMO_DIAS_FUTURO).toBe(365);
  });

  test('ESTADOS_EDITAVEIS são os do backend/crm/dominio/rotas.py, pela mesma ordem', () => {
    const linhas = [...ler(ROTAS_PY).matchAll(/^ESTADOS_EDITAVEIS = \(([^)\n]*)\)$/gm)];
    expect(linhas).toHaveLength(1);
    expect([...ESTADOS_EDITAVEIS]).toEqual([...linhas[0][1].matchAll(/"([^"]*)"/g)].map((m) => m[1]));
  });
});

// --- Funções puras ---------------------------------------------------------------------------------

test('textoParagens: "sem paragens", "1 paragem", "9 paragens"; o que não é uma contagem dá null', () => {
  expect(textoParagens(0)).toBe('sem paragens');
  expect(textoParagens(1)).toBe('1 paragem');
  expect(textoParagens(2)).toBe('2 paragens');
  expect(textoParagens(48)).toBe('48 paragens');
  for (const valor of [-1, 1.5, NaN, Infinity, '3', null, undefined, true]) expect(textoParagens(valor)).toBeNull();
});

describe('diaPorOmissao({hoje, rotas})', () => {
  test('a primeira rota que ainda se pode mudar a partir de hoje', () => {
    expect(diaPorOmissao(copia(LISTA))).toBe('2026-10-13');
  });

  test('pela data, venha a lista por que ordem vier', () => {
    const rotas = [resumo('2026-10-20', 'rascunho', 2), resumo('2026-10-14', 'planeada', 3), resumo('2026-10-16', 'rascunho', 1)];
    expect(diaPorOmissao({ hoje: HOJE, rotas })).toBe('2026-10-14');
  });

  test('a rota de hoje conta (também sem paragens ativas)', () => {
    expect(diaPorOmissao({ hoje: HOJE, rotas: [resumo(HOJE, 'rascunho', 0), resumo('2026-10-12', 'rascunho', 4)] })).toBe(HOJE);
  });

  test('ficam de fora as do passado, as em curso, as concluídas e as linhas estragadas', () => {
    const rotas = [
      resumo('2026-10-10', 'rascunho', 3), // antes de hoje (o servidor diria "concluida")
      resumo('2026-10-12', 'em_curso', 4),
      resumo('2026-10-13', 'concluida', 2, 'planeada'),
      { ...resumo('2026-10-14', 'rascunho', 1), data: '2026-02-30' },
      { ...resumo('2026-10-14', 'rascunho', 1), data: null },
      { ...resumo('2026-10-14', 'rascunho', 1), data: '2026-10-12 ' },
      null,
      'rota',
      { ...resumo('2026-10-16', 'Rascunho', 1) },
      resumo('2026-10-18', 'planeada', 6),
    ];
    expect(diaPorOmissao({ hoje: HOJE, rotas })).toBe('2026-10-18');
  });

  test('sem nenhuma que sirva, hoje', () => {
    expect(diaPorOmissao({ hoje: HOJE, rotas: [] })).toBe(HOJE);
    expect(diaPorOmissao({ hoje: HOJE, rotas: [resumo('2026-10-01', 'concluida', 3)] })).toBe(HOJE);
    expect(diaPorOmissao({ hoje: HOJE, rotas: null })).toBe(HOJE);
    expect(diaPorOmissao({ hoje: HOJE })).toBe(HOJE);
  });

  test('sem um hoje válido não há dia', () => {
    for (const hoje of [undefined, null, '', '2026-13-01', '11/10/2026']) {
      expect(diaPorOmissao({ hoje, rotas: copia(LISTA.rotas) })).toBeNull();
    }
    expect(diaPorOmissao(undefined)).toBeNull();
  });
});

describe('atalhosDosDias({hoje, rotas}, escolhida)', () => {
  test('as rotas que se podem mudar, a partir de hoje, com o dia e as paragens', () => {
    const rotas = [resumo(HOJE, 'rascunho', 5), resumo('2026-10-12', 'planeada', 1), resumo('2026-10-13', 'rascunho', 8)];
    expect(atalhosDosDias({ hoje: HOJE, rotas }, '2026-10-13')).toEqual([
      { data: HOJE, texto: 'Hoje · 5 paragens', escolhido: false },
      { data: '2026-10-12', texto: 'Amanhã · 1 paragem', escolhido: false },
      { data: '2026-10-13', texto: 'ter 13/10 · 8 paragens', escolhido: true },
    ]);
  });

  test('no máximo 5, os mais próximos; o dia repetido conta uma vez', () => {
    const rotas = ['2026-10-30', '2026-10-12', '2026-10-14', '2026-10-13', '2026-10-17', '2026-10-16', '2026-10-15']
      .map((data, i) => resumo(data, 'rascunho', i));
    rotas.push(resumo('2026-10-12', 'planeada', 40));
    const atalhos = atalhosDosDias({ hoje: HOJE, rotas }, null);
    expect(atalhos.map((a) => a.data)).toEqual(['2026-10-12', '2026-10-13', '2026-10-14', '2026-10-15', '2026-10-16']);
    expect(atalhos[0].texto).toBe('Amanhã · 1 paragem');
    expect(atalhos.every((a) => a.escolhido === false)).toBe(true);
  });

  test('uma rota sem paragens ativas diz "sem paragens"; uma contagem estragada fica só com o dia', () => {
    const rotas = [resumo('2026-10-13', 'rascunho', 0), resumo('2026-10-14', 'rascunho', null), resumo('2026-10-15', 'rascunho', '3')];
    expect(atalhosDosDias({ hoje: HOJE, rotas }, null).map((a) => a.texto)).toEqual([
      'ter 13/10 · sem paragens', 'qua 14/10', 'qui 15/10',
    ]);
  });

  test('sem rotas, ou sem um hoje válido, não há atalhos', () => {
    expect(atalhosDosDias({ hoje: HOJE, rotas: [] }, HOJE)).toEqual([]);
    expect(atalhosDosDias({ hoje: HOJE, rotas: 'x' }, HOJE)).toEqual([]);
    expect(atalhosDosDias({ hoje: null, rotas: copia(LISTA.rotas) }, HOJE)).toEqual([]);
  });
});

describe('textoAdicionada(rota, {data, hoje})', () => {
  test('o dia e as paragens ativas da rota que voltou', () => {
    expect(textoAdicionada(rotaAdicionada(), { data: '2026-10-13', hoje: HOJE })).toBe('Adicionada à rota de ter 13/10 (9 paragens).');
    expect(textoAdicionada(rotaAdicionada({ paragens: paragens(1) }), { data: '2026-10-13', hoje: HOJE }))
      .toBe('Adicionada à rota de ter 13/10 (1 paragem).');
  });

  test('hoje e amanhã em minúsculas, a meio da frase', () => {
    expect(textoAdicionada(rotaAdicionada({ data: HOJE }), { data: HOJE, hoje: HOJE })).toBe('Adicionada à rota de hoje (9 paragens).');
    expect(textoAdicionada(rotaAdicionada({ data: '2026-10-12' }), { data: '2026-10-12', hoje: HOJE }))
      .toBe('Adicionada à rota de amanhã (9 paragens).');
  });

  test('o hoje da resposta ganha ao da lista (a meia-noite pode ter passado)', () => {
    expect(textoAdicionada(rotaAdicionada({ hoje: '2026-10-12' }), { data: '2026-10-13', hoje: HOJE }))
      .toBe('Adicionada à rota de amanhã (9 paragens).');
    // Um hoje estragado na resposta não conta.
    expect(textoAdicionada(rotaAdicionada({ hoje: 'ontem' }), { data: '2026-10-13', hoje: HOJE }))
      .toBe('Adicionada à rota de ter 13/10 (9 paragens).');
  });

  test('com horas calculadas que ficaram velhas: "Abra a rota para recalcular as horas." (correção "T3.16 / T3.21 / T3.32")', () => {
    const velha = rotaAdicionada({ calculo: { atual: false, distancia_m: 1200, duracao_s: 900 } });
    expect(textoAdicionada(velha, { data: '2026-10-13', hoje: HOJE }))
      .toBe('Adicionada à rota de ter 13/10 (9 paragens). Abra a rota para recalcular as horas.');
    // Um cálculo sem o `atual` também não é atual.
    expect(textoAdicionada(rotaAdicionada({ calculo: { distancia_m: 1200 } }), { data: '2026-10-13', hoje: HOJE }))
      .toBe('Adicionada à rota de ter 13/10 (9 paragens). Abra a rota para recalcular as horas.');
  });

  test('sem esse aviso: sem cálculo, com as horas ainda atuais, ou sem a chave do openrouteservice', () => {
    const casos = [
      rotaAdicionada({ calculo: null }),
      rotaAdicionada({ calculo: { atual: true } }),
      rotaAdicionada({ calculo: { atual: false }, calculo_disponivel: false }),
      rotaAdicionada({ calculo: { atual: false }, calculo_disponivel: 'true' }),
      rotaAdicionada({ calculo: 'velho' }),
      rotaAdicionada({ calculo: [{ atual: false }] }),
    ];
    for (const rota of casos) {
      expect(textoAdicionada(rota, { data: '2026-10-13', hoje: HOJE })).toBe('Adicionada à rota de ter 13/10 (9 paragens).');
    }
  });

  test('uma resposta sem paragens legíveis fica sem a contagem', () => {
    expect(textoAdicionada(null, { data: '2026-10-13', hoje: HOJE })).toBe('Adicionada à rota de ter 13/10.');
    expect(textoAdicionada(rotaAdicionada({ paragens: null }), { data: '2026-10-13', hoje: HOJE })).toBe('Adicionada à rota de ter 13/10.');
    expect(textoAdicionada(rotaAdicionada({ paragens: 'xyz' }), { data: '2026-10-13', hoje: HOJE })).toBe('Adicionada à rota de ter 13/10.');
    // Sem nenhum hoje válido, o dia em AAAA-MM-DD.
    expect(textoAdicionada(rotaAdicionada({ hoje: null }), { data: '2026-10-13', hoje: null })).toBe('Adicionada à rota de 2026-10-13 (9 paragens).');
  });
});

test('estadoAdicionar: a adicionar → sem rede → sem dia → pronto', () => {
  expect(estadoAdicionar({ aAdicionar: true, online: false, dataValida: false })).toEqual({ ativo: false, texto: 'A adicionar…', falta: null });
  expect(estadoAdicionar({ aAdicionar: false, online: false, dataValida: false })).toEqual({ ativo: false, texto: 'Adicionar', falta: MENSAGEM_SEM_REDE });
  expect(estadoAdicionar({ aAdicionar: false, online: true, dataValida: false })).toEqual({ ativo: false, texto: 'Adicionar', falta: 'Escolha o dia.' });
  expect(estadoAdicionar({ aAdicionar: false, online: true, dataValida: true })).toEqual({ ativo: true, texto: 'Adicionar', falta: null });
});

// --- O ecrã -----------------------------------------------------------------------------------------

function apiFalsa() {
  const pedidos = [];
  const pedir = (nome) => (...argumentos) => new Promise((resolver, rejeitar) => {
    pedidos.push({ nome, argumentos, resolver, rejeitar });
  });
  return { pedidos, listarRotas: pedir('listarRotas'), adicionarParagem: pedir('adicionarParagem') };
}

const assentar = () => new Promise((r) => {
  setTimeout(r, 0);
});

// Monta o diálogo como a página (T3.40): cria e inicia (pede a lista e ouve a rede).
function montar({ loja = LOJA, base = '/crm', iniciar = true, online = true } = {}) {
  const api = apiFalsa();
  const janela = new EventTarget();
  const navegador = { onLine: online };
  const avisos = [];
  const focos = [];
  const vistas = [];
  const navegacoes = [];
  const ecra = criarAdicionarARota({
    api,
    loja,
    rede: criarEstadoRede(janela, navegador),
    base,
    navegar: (caminho, opcoes) => navegacoes.push([caminho, opcoes]),
    aoMudarVista: (vista) => vistas.push(vista),
    aoAvisar: (texto, opcoes) => avisos.push([texto, opcoes]),
    aoFocar: (alvo) => focos.push(alvo),
  });
  if (iniciar) ecra.iniciar();
  const mudarRede = (ligado) => {
    navegador.onLine = ligado;
    janela.dispatchEvent(new Event(ligado ? 'online' : 'offline'));
  };
  return { api, ecra, avisos, focos, vistas, navegacoes, mudarRede, vista: () => ecra.vista };
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

async function carregado(opcoes = {}, lista = LISTA) {
  const m = montar(opcoes);
  await responder(m, 'listarRotas', copia(lista));
  return m;
}

const erro = (codigo, mensagem, extra = {}) => new ErroCrm({ codigo, mensagem, estado: 409, ...extra });
const erroValidacao = (campos) => new ErroCrm({ codigo: 'validacao', mensagem: 'Verifique os campos assinalados.', estado: 422, campos });
const PRONTO = { ativo: true, texto: 'Adicionar', falta: null };

test('sem uma loja com id não há diálogo (um engano no código)', () => {
  for (const loja of [undefined, null, {}, { id: '' }, { id: 7 }, 'loja-1']) {
    expect(() => criarAdicionarARota({ api: apiFalsa(), loja, base: '/crm' })).toThrow(TypeError);
  }
});

test('sem o objeto da rede conta como ligado', async () => {
  const api = apiFalsa();
  const ecra = criarAdicionarARota({ api, loja: LOJA, base: '/crm' });
  ecra.iniciar();
  api.pedidos[0].resolver(copia(LISTA));
  await assentar();
  expect(ecra.vista.semRede).toBe(false);
  expect(ecra.vista.adicionar).toEqual(PRONTO);
});

test('criar não pede nada; iniciar pede a lista das rotas sem intervalo (uma vez)', () => {
  const m = montar({ iniciar: false });
  expect(m.api.pedidos).toEqual([]);
  // "Tentar novamente" só depois de uma falha.
  m.ecra.tentarDeNovo();
  expect(m.api.pedidos).toEqual([]);
  m.ecra.iniciar();
  m.ecra.iniciar();
  expect(m.api.pedidos.map((p) => [p.nome, p.argumentos])).toEqual([['listarRotas', []]]);
});

test('iniciar outra vez (também depois de uma falha) não pede nem ouve a rede de novo', async () => {
  const ouvidos = [];
  const api = apiFalsa();
  const ecra = criarAdicionarARota({
    api, loja: LOJA, base: '/crm', rede: { online: () => true, aoMudar: (f) => { ouvidos.push(f); return () => {}; } },
  });
  ecra.iniciar();
  api.pedidos[0].rejeitar(erro('sem_rede', MENSAGEM_SEM_REDE));
  await assentar();
  ecra.iniciar();
  expect(api.pedidos).toHaveLength(1);
  expect(ouvidos).toHaveLength(1);
});

test('a carregar: o título e a loja, o resto vazio, congelado; cada mudança vai para o aoMudarVista', () => {
  const m = montar();
  const vista = m.vista();
  expect(Object.keys(vista)).toEqual([
    'estado', 'titulo', 'loja', 'falha', 'atalhos', 'data', 'min', 'max', 'erroData', 'motivo', 'opcoesMotivo',
    'erroMotivo', 'camposDesativados', 'alerta', 'semRede', 'adicionar',
  ]);
  expect(vista).toEqual({
    estado: 'a_carregar',
    titulo: 'Adicionar à rota',
    loja: { id: 'loja-1', nome: 'Café Central' },
    falha: null,
    atalhos: [],
    data: null,
    min: null,
    max: null,
    erroData: null,
    motivo: 'amostra',
    opcoesMotivo: [
      { valor: 'entrega', texto: 'Entrega' },
      { valor: 'amostra', texto: 'Amostra' },
      { valor: 'acompanhamento', texto: 'Acompanhamento' },
      { valor: 'angariacao', texto: 'Angariação' },
    ],
    erroMotivo: null,
    camposDesativados: false,
    alerta: null,
    semRede: false,
    adicionar: { ativo: false, texto: 'Adicionar', falta: null },
  });
  expect(congeladaAFundo(vista)).toBe(true);
  // O iniciar mostrou a vista a carregar (o pedido saiu).
  expect(m.vistas.at(-1)).toBe(vista);
});

test('com a lista: o dia proposto, o mínimo (hoje) e o máximo (hoje + 365), os atalhos e "Adicionar"', async () => {
  const m = await carregado();
  const vista = m.vista();
  expect(vista.estado).toBe('pronto');
  expect(vista.data).toBe('2026-10-13');
  expect(vista.min).toBe(HOJE);
  expect(vista.max).toBe('2027-10-11');
  expect(vista.atalhos).toEqual([
    { data: '2026-10-13', texto: 'ter 13/10 · 8 paragens', escolhido: true },
    { data: '2026-10-15', texto: 'qui 15/10 · 1 paragem', escolhido: false },
  ]);
  expect(vista.adicionar).toEqual(PRONTO);
  expect(vista.falha).toBeNull();
  expect(congeladaAFundo(vista)).toBe(true);
  expect(m.vistas.at(-1)).toBe(vista);
});

test('sem rotas a partir de hoje, o dia proposto é hoje e não há atalhos', async () => {
  const m = await carregado({}, { ...LISTA, rotas: [resumo('2026-10-09', 'concluida', 7)] });
  expect(m.vista().data).toBe(HOJE);
  expect(m.vista().atalhos).toEqual([]);
  expect(m.vista().adicionar).toEqual(PRONTO);
});

test('o motivo pré-escolhido pela fase da loja (motivoPorFase)', () => {
  const casos = [
    ['potencial', 'angariacao'], ['perdida', 'angariacao'], ['contactada', 'amostra'], ['amostra', 'acompanhamento'],
    ['cliente', 'acompanhamento'], ['desconhecida', 'angariacao'], [undefined, 'angariacao'],
  ];
  for (const [fase, motivo] of casos) {
    const m = montar({ loja: { id: 'x', nome: 'X', fase }, iniciar: false });
    expect(m.vista().motivo).toBe(motivo);
  }
  // Uma loja sem nome em texto fica com o nome vazio.
  expect(montar({ loja: { id: 'x', fase: 'cliente' }, iniciar: false }).vista().loja).toEqual({ id: 'x', nome: '' });
});

test('a lista falha: a mensagem e "Tentar novamente" (um toque, um pedido)', async () => {
  const m = montar();
  await falhar(m, 'listarRotas', erro('sem_rede', MENSAGEM_SEM_REDE, { estado: 0 }));
  expect(m.vista().estado).toBe('falha');
  expect(m.vista().falha).toEqual({ mensagem: MENSAGEM_SEM_REDE, aTentar: false });
  expect(congeladaAFundo(m.vista())).toBe(true);
  expect(m.vista().adicionar.ativo).toBe(false);
  m.ecra.tentarDeNovo();
  m.ecra.tentarDeNovo();
  expect(pedidos(m, 'listarRotas')).toHaveLength(2);
  expect(m.vista().falha).toEqual({ mensagem: MENSAGEM_SEM_REDE, aTentar: true });
  await responder(m, 'listarRotas', copia(LISTA));
  expect(m.vista().estado).toBe('pronto');
  expect(m.vista().falha).toBeNull();
  // Depois de carregada, "Tentar novamente" não pede nada.
  m.ecra.tentarDeNovo();
  expect(pedidos(m, 'listarRotas')).toHaveLength(2);
});

test('um erro sem mensagem, ou uma resposta sem o hoje do servidor, dá o erro inesperado', async () => {
  const m = montar();
  await falhar(m, 'listarRotas', new Error());
  expect(m.vista().falha.mensagem).toBe(MENSAGEM_ERRO_INESPERADO);
  for (const resposta of [null, [], { rotas: [] }, { hoje: 'hoje', rotas: [] }]) {
    const outro = montar();
    await responder(outro, 'listarRotas', resposta);
    expect(outro.vista().estado).toBe('falha');
    expect(outro.vista().falha.mensagem).toBe(MENSAGEM_ERRO_INESPERADO);
  }
  // Uma lista de rotas que não é lista conta como vazia.
  const semLista = montar();
  await responder(semLista, 'listarRotas', { hoje: HOJE, rotas: 'x' });
  expect(semLista.vista().estado).toBe('pronto');
  expect(semLista.vista().data).toBe(HOJE);
  semLista.ecra.adicionar();
  await responder(semLista, 'adicionarParagem', rotaAdicionada({ data: HOJE, paragens: paragens(1) }));
  expect(semLista.vista().atalhos).toEqual([{ data: HOJE, texto: 'Hoje · 1 paragem', escolhido: true }]);
});

test('a rede que volta pede outra vez a lista que falhou (e só essa)', async () => {
  const m = montar();
  await falhar(m, 'listarRotas', erro('sem_rede', MENSAGEM_SEM_REDE));
  m.mudarRede(false);
  expect(pedidos(m, 'listarRotas')).toHaveLength(1);
  m.mudarRede(true);
  expect(pedidos(m, 'listarRotas')).toHaveLength(2);
  await responder(m, 'listarRotas', copia(LISTA));
  m.mudarRede(true);
  expect(pedidos(m, 'listarRotas')).toHaveLength(2);
});

test('sem rede: semRede e "Adicionar" desligado com a mensagem; quando volta, liga-se', async () => {
  const m = await carregado();
  m.mudarRede(false);
  expect(m.vista().semRede).toBe(true);
  expect(m.vista().adicionar).toEqual({ ativo: false, texto: 'Adicionar', falta: MENSAGEM_SEM_REDE });
  m.ecra.adicionar();
  expect(pedidos(m, 'adicionarParagem')).toEqual([]);
  m.mudarRede(true);
  expect(m.vista().semRede).toBe(false);
  expect(m.vista().adicionar).toEqual(PRONTO);
});

test('escolher o dia (um atalho ou o campo da data) marca o atalho e limpa os erros', async () => {
  const m = await carregado();
  m.ecra.escolherDia('2026-10-15');
  expect(m.vista().data).toBe('2026-10-15');
  expect(m.vista().atalhos.map((a) => a.escolhido)).toEqual([false, true]);
  m.ecra.escolherDia('2026-11-02');
  expect(m.vista().data).toBe('2026-11-02');
  expect(m.vista().atalhos.map((a) => a.escolhido)).toEqual([false, false]);
  // Um erro do dia e um alerta saem quando se escolhe outro dia.
  m.ecra.adicionar();
  await falhar(m, 'adicionarParagem', erroValidacao({ data: 'Escolha um dia até um ano a partir de hoje.' }));
  expect(m.vista().erroData).toBe('Escolha um dia até um ano a partir de hoje.');
  m.ecra.escolherDia('2026-10-13');
  expect(m.vista().erroData).toBeNull();
  m.ecra.adicionar();
  await falhar(m, 'adicionarParagem', erro('ja_na_rota', 'Esta loja já está na rota deste dia.'));
  expect(m.vista().alerta).toBe('Esta loja já está na rota deste dia.');
  // O motivo não muda o que o servidor disse do dia: o alerta fica.
  m.ecra.mudarMotivo('entrega');
  expect(m.vista().alerta).toBe('Esta loja já está na rota deste dia.');
  m.ecra.escolherDia('2026-10-15');
  expect(m.vista().alerta).toBeNull();
});

test('um dia vazio ou mal escrito desliga "Adicionar" ("Escolha o dia."); o que não é texto não conta', async () => {
  const m = await carregado();
  m.ecra.escolherDia('');
  expect(m.vista().data).toBe('');
  expect(m.vista().adicionar).toEqual({ ativo: false, texto: 'Adicionar', falta: 'Escolha o dia.' });
  m.ecra.adicionar();
  expect(pedidos(m, 'adicionarParagem')).toEqual([]);
  m.ecra.escolherDia('2026-02-30');
  expect(m.vista().adicionar.falta).toBe('Escolha o dia.');
  const antes = m.vista();
  m.ecra.escolherDia(undefined);
  m.ecra.escolherDia(20261013);
  expect(m.vista()).toBe(antes);
  // Um dia passado não se recusa aqui: o `min` do campo e o 409 `rota_fechada` do servidor (T3.40).
  m.ecra.escolherDia('2026-10-01');
  expect(m.vista().adicionar).toEqual(PRONTO);
});

test('antes de a lista chegar não se escolhe dia nem motivo, nem se adiciona', () => {
  const m = montar();
  const antes = m.vista();
  m.ecra.escolherDia('2026-10-13');
  m.ecra.adicionar();
  expect(m.vista()).toBe(antes);
  expect(pedidos(m, 'adicionarParagem')).toEqual([]);
  // O motivo pode mudar-se já (o campo aparece com o diálogo).
  m.ecra.mudarMotivo('entrega');
  expect(m.vista().motivo).toBe('entrega');
});

test('mudar o motivo: só um dos quatro', async () => {
  const m = await carregado();
  m.ecra.mudarMotivo('entrega');
  expect(m.vista().motivo).toBe('entrega');
  const antes = m.vista();
  for (const valor of ['Entrega', 'visita', '', null, undefined, 'constructor']) m.ecra.mudarMotivo(valor);
  expect(m.vista()).toBe(antes);
});

test('adicionar: POST das paragens com a loja e o motivo, sem a versão', async () => {
  const m = await carregado();
  m.ecra.mudarMotivo('acompanhamento');
  m.ecra.adicionar();
  const [pedido] = pedidos(m, 'adicionarParagem');
  expect(pedido.argumentos).toEqual(['2026-10-13', { loja_id: 'loja-1', motivo: 'acompanhamento' }]);
  expect(Object.keys(pedido.argumentos[1])).toEqual(['loja_id', 'motivo']);
});

test('um pedido de cada vez: "A adicionar…" e os campos desligados até à resposta', async () => {
  const m = await carregado();
  m.ecra.adicionar();
  expect(m.vista().adicionar).toEqual({ ativo: false, texto: 'A adicionar…', falta: null });
  expect(m.vista().camposDesativados).toBe(true);
  m.ecra.adicionar();
  m.ecra.escolherDia('2026-10-15');
  m.ecra.mudarMotivo('entrega');
  expect(pedidos(m, 'adicionarParagem')).toHaveLength(1);
  expect(m.vista().data).toBe('2026-10-13');
  expect(m.vista().motivo).toBe('amostra');
  await responder(m, 'adicionarParagem', rotaAdicionada());
  expect(m.vista().camposDesativados).toBe(false);
  expect(m.vista().adicionar).toEqual(PRONTO);
});

test('com sucesso: o aviso com o dia e as paragens, e "Abrir rota" para a rota desse dia', async () => {
  const m = await carregado();
  m.ecra.adicionar();
  await responder(m, 'adicionarParagem', rotaAdicionada());
  expect(m.avisos).toHaveLength(1);
  const [texto, opcoes] = m.avisos[0];
  expect(texto).toBe('Adicionada à rota de ter 13/10 (9 paragens).');
  expect(Object.keys(opcoes)).toEqual(['acao', 'href', 'abrir']);
  expect(opcoes.acao).toBe('Abrir rota');
  expect(opcoes.href).toBe('/crm/rotas/2026-10-13');
  expect(Object.isFrozen(opcoes)).toBe(true);
  expect(m.navegacoes).toEqual([]);
  opcoes.abrir();
  expect(m.navegacoes).toEqual([['/crm/rotas/2026-10-13', undefined]]);
  // A contagem do atalho é a da resposta.
  expect(m.vista().atalhos[0]).toEqual({ data: '2026-10-13', texto: 'ter 13/10 · 9 paragens', escolhido: true });
  expect(m.vista().alerta).toBeNull();
});

test('na casa do admin, a rota abre-se em /admin/crm', async () => {
  const m = await carregado({ base: '/admin/crm' });
  m.ecra.adicionar();
  await responder(m, 'adicionarParagem', rotaAdicionada());
  expect(m.avisos[0][1].href).toBe('/admin/crm/rotas/2026-10-13');
  m.avisos[0][1].abrir();
  expect(m.navegacoes).toEqual([['/admin/crm/rotas/2026-10-13', undefined]]);
});

test('"Abrir rota" funciona mesmo depois de o diálogo fechar (o toast fica)', async () => {
  const m = await carregado();
  m.ecra.adicionar();
  await responder(m, 'adicionarParagem', rotaAdicionada());
  m.ecra.destruir();
  m.avisos[0][1].abrir();
  expect(m.navegacoes).toEqual([['/crm/rotas/2026-10-13', undefined]]);
});

test('um dia novo (a rota nasceu com esta paragem) passa a ter o seu atalho', async () => {
  const m = await carregado();
  m.ecra.escolherDia('2026-10-14');
  m.ecra.adicionar();
  await responder(m, 'adicionarParagem', rotaAdicionada({ id: 'nova', data: '2026-10-14', paragens: paragens(1) }));
  expect(m.avisos[0][0]).toBe('Adicionada à rota de qua 14/10 (1 paragem).');
  expect(m.vista().atalhos).toEqual([
    { data: '2026-10-13', texto: 'ter 13/10 · 8 paragens', escolhido: false },
    { data: '2026-10-14', texto: 'qua 14/10 · 1 paragem', escolhido: true },
    { data: '2026-10-15', texto: 'qui 15/10 · 1 paragem', escolhido: false },
  ]);
});

test('uma resposta que não é uma rota: o aviso sem a contagem e os atalhos como estavam', async () => {
  const m = await carregado();
  const atalhos = m.vista().atalhos;
  m.ecra.adicionar();
  await responder(m, 'adicionarParagem', null);
  expect(m.avisos[0][0]).toBe('Adicionada à rota de ter 13/10.');
  expect(m.vista().atalhos).toEqual(atalhos);
});

test('com as horas da rota a ficarem velhas, o aviso manda abrir a rota (correção "T3.16 / T3.21 / T3.32")', async () => {
  const m = await carregado();
  m.ecra.adicionar();
  await responder(m, 'adicionarParagem', rotaAdicionada({ calculo: { atual: false, distancia_m: 9000 } }));
  expect(m.avisos[0][0]).toBe('Adicionada à rota de ter 13/10 (9 paragens). Abra a rota para recalcular as horas.');
});

test.each([
  ['ja_na_rota', 'Esta loja já está na rota deste dia.'],
  ['rota_cheia', 'Uma rota tem no máximo 48 paragens.'],
  ['rota_fechada', 'Este dia já passou — a rota só se pode ver.'],
  ['rota_em_curso', 'A rota já tem registos do motorista — no escritório só se pode ver.'],
  ['conflito', 'Alguém alterou esta rota ao mesmo tempo — tente novamente.'],
  ['nao_encontrado', 'Loja não encontrada.'],
  ['sem_rede', MENSAGEM_SEM_REDE],
])('o erro %s mostra a mensagem do servidor, sem aviso, e pode-se tentar outra vez', async (codigo, mensagem) => {
  const m = await carregado();
  m.ecra.adicionar();
  await falhar(m, 'adicionarParagem', erro(codigo, mensagem));
  expect(m.vista().alerta).toBe(mensagem);
  expect(m.vista().erroData).toBeNull();
  expect(m.avisos).toEqual([]);
  expect(m.vista().adicionar).toEqual(PRONTO);
  expect(m.vista().camposDesativados).toBe(false);
  m.ecra.adicionar();
  expect(pedidos(m, 'adicionarParagem')).toHaveLength(2);
  // O alerta sai quando se tenta outra vez.
  expect(m.vista().alerta).toBeNull();
});

test('um erro sem mensagem dá o erro inesperado', async () => {
  const m = await carregado();
  m.ecra.adicionar();
  await falhar(m, 'adicionarParagem', new TypeError('x'));
  expect(m.vista().alerta).toBe(MENSAGEM_ERRO_INESPERADO);
});

test('o 422 do dia fica junto do campo da data, com o foco lá', async () => {
  const m = await carregado();
  m.ecra.adicionar();
  await falhar(m, 'adicionarParagem', erroValidacao({ data: 'Escolha um dia até um ano a partir de hoje.' }));
  expect(m.vista().erroData).toBe('Escolha um dia até um ano a partir de hoje.');
  expect(m.vista().alerta).toBeNull();
  expect(m.focos).toEqual(['data']);
});

test('o 422 do motivo fica junto do motivo, com o foco lá; o do dia ganha o foco', async () => {
  const m = await carregado();
  m.ecra.adicionar();
  await falhar(m, 'adicionarParagem', erroValidacao({ motivo: 'Escolha um motivo: entrega, amostra, acompanhamento ou angariação.' }));
  expect(m.vista().erroMotivo).toBe('Escolha um motivo: entrega, amostra, acompanhamento ou angariação.');
  expect(m.focos).toEqual(['motivo']);
  // Mudar o motivo limpa o erro dele.
  m.ecra.mudarMotivo('entrega');
  expect(m.vista().erroMotivo).toBeNull();
  m.ecra.adicionar();
  await falhar(m, 'adicionarParagem', erroValidacao({ motivo: 'Motivo errado.', data: 'Dia errado.' }));
  expect([m.vista().erroData, m.vista().erroMotivo]).toEqual(['Dia errado.', 'Motivo errado.']);
  expect(m.focos).toEqual(['motivo', 'data']);
  // Tentar de novo limpa os dois.
  m.ecra.adicionar();
  expect([m.vista().erroData, m.vista().erroMotivo]).toEqual([null, null]);
});

test('o 422 de outro campo (a loja) vai para o alerta com a mensagem do campo; sem campos, a geral', async () => {
  const m = await carregado();
  m.ecra.adicionar();
  await falhar(m, 'adicionarParagem', erroValidacao({ loja_id: 'Escolha uma loja.' }));
  expect(m.vista().alerta).toBe('Escolha uma loja.');
  expect(m.focos).toEqual([]);
  m.ecra.adicionar();
  await falhar(m, 'adicionarParagem', erroValidacao({}));
  expect(m.vista().alerta).toBe('Verifique os campos assinalados.');
  m.ecra.adicionar();
  await falhar(m, 'adicionarParagem', erroValidacao({ data: '', motivo: 7 }));
  expect(m.vista().alerta).toBe('Verifique os campos assinalados.');
  expect([m.vista().erroData, m.vista().erroMotivo]).toEqual([null, null]);
  m.ecra.adicionar();
  await falhar(m, 'adicionarParagem', erroValidacao({ data: 7, motivo: '' }));
  expect(m.vista().alerta).toBe('Verifique os campos assinalados.');
  expect([m.vista().erroData, m.vista().erroMotivo]).toEqual([null, null]);
  m.ecra.adicionar();
  await falhar(m, 'adicionarParagem', new ErroCrm({ codigo: 'validacao', mensagem: 'Verifique os campos assinalados.', estado: 422, campos: null }));
  expect(m.vista().alerta).toBe('Verifique os campos assinalados.');
});

describe('destruir(): o diálogo fechou', () => {
  test('a lista que chega (ou falha) depois não muda nada', async () => {
    for (const acabar of [(m) => responder(m, 'listarRotas', copia(LISTA)), (m) => falhar(m, 'listarRotas', erro('sem_rede', 'x'))]) {
      const m = montar();
      const vista = m.vista();
      const vistas = m.vistas.length;
      m.ecra.destruir();
      await acabar(m);
      expect(m.vista()).toEqual(vista);
      expect(m.vistas).toHaveLength(vistas);
    }
  });

  test('a paragem que chega (ou falha) depois não avisa nem muda a vista', async () => {
    for (const acabar of [
      (m) => responder(m, 'adicionarParagem', rotaAdicionada()),
      (m) => falhar(m, 'adicionarParagem', erro('ja_na_rota', 'x')),
    ]) {
      const m = await carregado();
      m.ecra.adicionar();
      const vistas = m.vistas.length;
      m.ecra.destruir();
      await acabar(m);
      expect(m.avisos).toEqual([]);
      expect(m.focos).toEqual([]);
      expect(m.vistas).toHaveLength(vistas);
    }
  });

  test('a rede deixa de se ouvir; nada mais se pede nem se escolhe', async () => {
    const m = montar();
    await falhar(m, 'listarRotas', erro('sem_rede', 'x'));
    m.ecra.destruir();
    const vistasAntes = m.vistas.length;
    m.mudarRede(false);
    m.mudarRede(true);
    m.ecra.tentarDeNovo();
    m.ecra.iniciar();
    expect(pedidos(m, 'listarRotas')).toHaveLength(1);
    expect(m.vistas).toHaveLength(vistasAntes);
    const outro = await carregado();
    outro.ecra.destruir();
    const vistas = outro.vistas.length;
    outro.ecra.escolherDia('2026-10-15');
    outro.ecra.mudarMotivo('entrega');
    outro.ecra.adicionar();
    expect(pedidos(outro, 'adicionarParagem')).toEqual([]);
    expect(outro.vistas).toHaveLength(vistas);
  });

  test('iniciar depois de destruir não pede nada nem ouve a rede', () => {
    const m = montar({ iniciar: false });
    m.ecra.destruir();
    m.ecra.iniciar();
    m.mudarRede(false);
    expect(m.api.pedidos).toEqual([]);
    expect(m.vistas).toEqual([]);
  });

  test('o ouvinte da rede cancela-se', () => {
    const cancelados = [];
    const rede = { online: () => true, aoMudar: () => () => cancelados.push('cancelado') };
    const ecra = criarAdicionarARota({ api: apiFalsa(), loja: LOJA, rede, base: '/crm' });
    ecra.iniciar();
    expect(cancelados).toEqual([]);
    ecra.destruir();
    expect(cancelados).toEqual(['cancelado']);
  });
});
