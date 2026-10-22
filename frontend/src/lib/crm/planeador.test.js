/**
 * O PLANEADOR DE ROTA SEM DOM (1/2) — carregar, a vista, a leitura só e as sugestões (F3 / T3.31).
 *
 * Molde do `criarFicha` (T2.28): o controlador pede o que precisa, monta uma `vista` congelada a cada
 * mudança e entrega-a ao `aoMudarVista`; o `pages/crm/CrmRota.js` (T3.38) só a desenha. Ficam aqui:
 *   - o `iniciar()`: a rota (`obterRota`), a configuração do mapa e as lojas ao mesmo tempo, e as
 *     sugestões só depois de a rota chegar;
 *   - a vista do plano (T3.31), com as correções que tocam nesta tarefa:
 *       "T3.31 / T3.39" e "T3.20 / T3.31 / T3.39" — numa rota virtual (`existe: false`) as definições do
 *       dia ficam desligadas com "Adicione a primeira paragem para mudar as definições do dia." e o
 *       "Calcular" e o "Guardar" também;
 *       "T3.16 / T3.21 / T3.32" — o rótulo das horas: "a recalcular" só com um recálculo pedido;
 *       senão "Horas antigas — Recalcular horas", ou "sem horas — ordene à mão" sem a chave;
 *       "T3.32 / T3.38" — a `vista.mapa.lojasForaDaRota` (e o próprio `vista.mapa`) mantém a mesma
 *       referência enquanto as lojas e os ids na rota não mudam;
 *   - a leitura só (dia passado, em curso, "Não houve rota neste dia."), a data inválida, a falha com
 *     "Tentar novamente", o sem rede, o `recarregar()` e o `destruir()`.
 *
 * O PLANEADOR (2/2) — as ações, as horas automáticas, calcular, guardar e os conflitos (F3 / T3.32), no fim
 * do ficheiro, com as correções que tocam nesta tarefa:
 *   "T3.32" — depois de a fila esvaziar, ~1,5 s sem alterações antes do recálculo automático (o temporizador
 *     injetado; também com o relógio falso do Jest): várias alterações seguidas dão um só recálculo;
 *   "T3.32 / T3.38" — no máximo um recálculo automático por par (versão, `calculado_em`): uma resposta 200
 *     que ainda traga as horas velhas não volta a disparar;
 *   "T3.16 / T3.21 / T3.32" — "a recalcular" só com um recálculo (ou uma otimização) na fila;
 *   "T3.20 / T3.31 / T3.39" — numa rota virtual, mudar as definições do dia não chama a API.
 */
import { ErroCrm, MENSAGEM_ERRO_INESPERADO, MENSAGEM_SEM_REDE } from './api';
import { ATRIBUICOES, TEXTO_ROTA_DE_TERCEIROS } from './atribuicoes';
import { TEXTO_CONFLITO as TEXTO_CONFLITO_DA_FICHA } from './ficha';
import { descodificarPolilinha } from './polilinha';
import { criarEstadoRede } from './rede';
import {
  DEFINICOES_DO_DIA,
  ESPERA_HORAS_MS,
  TEXTOS_ESCOLHER_PONTO,
  TEXTO_ADICIONADA,
  TEXTO_A_ADICIONAR,
  TEXTO_A_CALCULAR,
  TEXTO_A_RECALCULAR,
  TEXTO_CONFLITO,
  TEXTO_FALTA_CONFLITO,
  TEXTO_GUARDADA,
  TEXTO_RETIRADA,
  MENSAGEM_DATA_INVALIDA,
  MENSAGEM_SEM_CALCULO,
  TEXTO_AINDA_SEM_PARAGENS,
  TEXTO_A_CARREGAR,
  TEXTO_CALCULAR,
  TEXTO_CONCLUIDA_LEITURA,
  TEXTO_DEFINICOES_SEM_ROTA,
  TEXTO_EM_CURSO_LEITURA,
  TEXTO_FABRICA,
  TEXTO_GUARDAR_ROTA,
  TEXTO_HORAS_ANTIGAS,
  TEXTO_HORAS_ANTIGAS_LEITURA,
  TEXTO_HORAS_A_RECALCULAR,
  TEXTO_HORAS_EM_DIA,
  TEXTO_JA_PLANEADA,
  TEXTO_NADA_A_CALCULAR,
  TEXTO_NAO_HOUVE_ROTA,
  TEXTO_PARAGEM_SEM_LOJA,
  TEXTO_PONTO_NO_MAPA,
  TEXTO_PRIMEIRA_PARAGEM,
  TEXTO_RECALCULAR,
  TEXTO_SEM_HORAS,
  TEXTO_SUGESTOES_A_CARREGAR,
  TEXTO_SUGESTOES_NENHUMA,
  TITULO_DIA_INVALIDO,
  acoesDaRota,
  criarPlaneador,
  lojasForaDaRota,
  textoDasHoras,
  textoLeitura,
  vistaDasSugestoes,
} from './planeador';

// --- Uma rota da API (plano F3 §4) ----------------------------------------------------------------

// 2026-10-12 é uma segunda-feira ('seg'); o "hoje" do servidor é o sábado antes.
const DIA = '2026-10-12';
const HOJE = '2026-10-10';
const FABRICA = Object.freeze({ lat: 38.75, lng: -9.2 });
const GEOMETRIA = '_p~iF~ps|U_ulLnnqC';

function lojaDaParagem(nome, ordem, extra = {}) {
  return {
    nome,
    fase: 'contactada',
    lat: 38.7 + ordem / 100,
    lng: -9.1 - ordem / 100,
    telefone: '',
    janela1_inicio: null,
    janela1_fim: null,
    janela2_inicio: null,
    janela2_fim: null,
    dias_fechada: [],
    ...extra,
  };
}

const linksDe = (id) => ({
  google: `https://www.google.com/maps/dir/?api=1&destination=${id}`,
  waze: `https://waze.com/ul?ll=${id}&navigate=yes`,
});

function paragem(id, ordem, { seccao = 'rota', numero = null, aviso = 'nenhum', semLoja = false, ...extra } = {}) {
  return {
    id,
    loja_id: `loja-${id}`,
    numero,
    seccao,
    ordem,
    motivo: 'amostra',
    tempo_servico_min: 10,
    manter_fechada: false,
    nao_cabe: false,
    chegada_prevista: seccao === 'rota' ? `09:${String(ordem).padStart(2, '0')}` : null,
    espera_min: seccao === 'rota' ? 0 : null,
    fora_de_horario: false,
    aviso,
    estado: 'pendente',
    resultado: null,
    links: semLoja ? null : linksDe(id),
    loja: semLoja ? null : lojaDaParagem(`Loja ${id}`, ordem),
    ...extra,
  };
}

// A, C e E na rota (1, 2 e 3; E fora do horário e com espera), B fechada à segunda, D não cabe e F de
// uma loja apagada.
function rotaDoServidor(extra = {}) {
  return {
    id: 'rota-1',
    data: DIA,
    existe: true,
    estado: 'rascunho',
    estado_efetivo: 'rascunho',
    editavel: true,
    versao: 3,
    hoje: HOJE,
    hora_saida: '08:00',
    hora_regresso_limite: '19:00',
    evitar_portagens: false,
    inicio: { ...FABRICA, fabrica: true },
    fim: { ...FABRICA, fabrica: true },
    limite_paragens: 48,
    calculo_disponivel: true,
    calculo: {
      atual: true,
      distancia_m: 123456,
      duracao_s: 19260,
      regresso_previsto: '19:40',
      depois_do_limite: true,
      geometria: GEOMETRIA,
      calculado_em: '2026-10-10T07:00:00.000000+00:00',
    },
    paragens: [
      paragem('A', 0, { numero: 1 }),
      paragem('B', 1, { seccao: 'fechada', aviso: 'fechada_neste_dia', loja: lojaDaParagem('Loja B', 1, { dias_fechada: ['seg'] }) }),
      paragem('C', 2, { numero: 2 }),
      paragem('D', 3, { seccao: 'nao_cabe', aviso: 'nao_cabe', nao_cabe: true }),
      paragem('E', 4, { numero: 3, aviso: 'fora_de_horario', fora_de_horario: true, espera_min: 12 }),
      paragem('F', 5, { seccao: 'sem_loja', semLoja: true }),
    ],
    blocos_google: [
      { de: 1, ate: 3, quantas: 3, rotulo: 'Abrir paragens 1–3 no Google Maps', href: 'https://www.google.com/maps/dir/?api=1&destination=E' },
    ],
    ...extra,
  };
}

// A rota virtual de um dia sem rota (hoje ou futuro): `existe: false`, os valores por omissão.
function rotaVirtual(extra = {}) {
  return rotaDoServidor({
    id: null, existe: false, estado: null, estado_efetivo: null, versao: null, calculo: null, paragens: [], blocos_google: [], ...extra,
  });
}

// O resumo do GET /lojas: as lojas das paragens A a E, e duas fora da rota (a F foi apagada).
const loja = (id, extra = {}) => ({
  id, nome: `Loja ${id}`, fase: 'potencial', regiao_id: null, lat: 38.8, lng: -9.3, telefone: null, pessoa_contacto: null, ...extra,
});
const LOJAS = ['loja-A', 'loja-B', 'loja-C', 'loja-D', 'loja-E', 'loja-X', 'loja-Y'].map((id) => loja(id));
const CONFIG = { google: { chave: 'chave-falsa', map_id: 'mapa-falso' }, centro: { ...FABRICA } };

const sugestao = (id, nome, fase, distancia_m, no_caminho = false) => ({
  id, nome, fase, lat: 38.71, lng: -9.11, distancia_m, no_caminho,
});
// As sugestões do servidor: a contactada X a 1,2 km, a potencial Y no caminho a 0,8 km (mais 3 que não
// vêm), e a A, já na rota (uma resposta que chegou depois de a A entrar).
function sugestoesDoServidor() {
  return {
    sem_paragens: false,
    no_caminho: true,
    grupos: [
      { fase: 'contactada', lojas: [sugestao('loja-X', 'Café X', 'contactada', 1234), sugestao('loja-A', 'Loja A', 'contactada', 10)], mais: 0 },
      { fase: 'potencial', lojas: [sugestao('loja-Y', 'Frutaria Y', 'potencial', 800, true)], mais: 3 },
    ],
  };
}

// Uma cópia funda, como a que o servidor manda.
const copia = (valor) => JSON.parse(JSON.stringify(valor));

// --- O ecrã --------------------------------------------------------------------------------------

// Cada pedido fica pendente até o teste lhe responder (ou o fazer falhar).
function apiFalsa() {
  const pedidos = [];
  const pedir = (nome) => (...argumentos) => new Promise((resolver, rejeitar) => {
    pedidos.push({ nome, argumentos, resolver, rejeitar });
  });
  return {
    pedidos,
    obterRota: pedir('obterRota'),
    obterConfigMapa: pedir('obterConfigMapa'),
    listarLojas: pedir('listarLojas'),
    obterSugestoes: pedir('obterSugestoes'),
    // As escritas (T3.32), pela fila (`enviarPelaApi`).
    adicionarParagem: pedir('adicionarParagem'),
    alterarRota: pedir('alterarRota'),
    recalcularHoras: pedir('recalcularHoras'),
    otimizarRota: pedir('otimizarRota'),
  };
}

// Com o relógio falso do Jest, o `setTimeout` também é falso: as respostas assentam só pelas microtarefas.
let comRelogioFalso = false;
const microtarefas = async () => {
  for (let i = 0; i < 50; i += 1) await Promise.resolve();
};
const assentar = () => (comRelogioFalso ? microtarefas() : new Promise((r) => {
  setTimeout(r, 0);
}));

// Um temporizador à mão (o `temporizador` injetado no planeador): guarda o que se agendou, e o teste diz
// quando dispara.
function temporizadorFalso() {
  let proximo = 1;
  const agendados = new Map();
  return {
    agendar: (funcao, ms) => {
      const id = proximo;
      proximo += 1;
      agendados.set(id, { funcao, ms });
      return id;
    },
    cancelar: (id) => {
      agendados.delete(id);
    },
    // Os milissegundos de cada espera ainda por disparar.
    get esperas() {
      return [...agendados.values()].map((a) => a.ms);
    },
    disparar() {
      const lista = [...agendados.values()];
      agendados.clear();
      lista.forEach((a) => a.funcao());
    },
  };
}

// Monta o ecrã como a página (CrmRota): cria e inicia. A `data` em falta é o DIA (um `undefined` explícito
// fica `undefined`: o `:data` da rota que não veio). O `temporizador` em falta é o falso, à mão; um
// `undefined` explícito deixa o do planeador (o do browser: o relógio falso do Jest).
function montar(opcoes = {}) {
  const { online = true, base = '/crm', iniciar = true } = opcoes;
  const data = 'data' in opcoes ? opcoes.data : DIA;
  const relogio = 'temporizador' in opcoes ? opcoes.temporizador : temporizadorFalso();
  const api = apiFalsa();
  const janela = new EventTarget();
  const navegador = { onLine: online };
  const navegacoes = [];
  const avisos = [];
  const vistas = [];
  const planeador = criarPlaneador({
    api,
    rede: criarEstadoRede(janela, navegador),
    data,
    base,
    navegar: (caminho, opcoes) => navegacoes.push({ caminho, opcoes }),
    aoMudarVista: (vista) => vistas.push(vista),
    aoAvisar: (texto, opcoes) => avisos.push({ texto, opcoes }),
    temporizador: relogio,
  });
  if (iniciar) planeador.iniciar();
  const mudarRede = (ligado) => {
    navegador.onLine = ligado;
    janela.dispatchEvent(new Event(ligado ? 'online' : 'offline'));
  };
  return { api, planeador, navegacoes, avisos, vistas, mudarRede, relogio, vista: () => planeador.vista };
}

const pedidos = (m, nome) => m.api.pedidos.filter((p) => p.nome === nome);
const nomes = (m) => m.api.pedidos.map((p) => p.nome);
const ultimo = (m, nome) => pedidos(m, nome).at(-1);

async function responder(m, nome, dados) {
  ultimo(m, nome).resolver(dados);
  await assentar();
}

async function falhar(m, nome, erro) {
  ultimo(m, nome).rejeitar(erro);
  await assentar();
}

// O planeador com a rota, a configuração e as lojas carregadas (as sugestões ficam pedidas, sem resposta).
async function carregado({ rota = rotaDoServidor(), lojas = LOJAS, config = CONFIG, ...opcoes } = {}) {
  const m = montar(opcoes);
  await responder(m, 'obterConfigMapa', copia(config));
  await responder(m, 'listarLojas', copia(lojas));
  await responder(m, 'obterRota', copia(rota));
  return m;
}

// …e com as sugestões também.
async function comSugestoes(opcoes = {}, resposta = sugestoesDoServidor()) {
  const m = await carregado(opcoes);
  await responder(m, 'obterSugestoes', copia(resposta));
  return m;
}

const erroSemRede = () => new ErroCrm({ codigo: 'sem_rede', mensagem: MENSAGEM_SEM_REDE });
const erroServidor = (mensagem = 'O servidor falhou.') => new ErroCrm({ codigo: 'erro_interno', mensagem, estado: 500 });

const CHAVES_DA_VISTA = [
  'estado', 'titulo', 'somenteLeitura', 'textoLeitura', 'rotuloEstado', 'falha', 'conflito', 'semRede',
  'definicoes', 'totais', 'horas', 'avisos', 'seccoes', 'sugestoes', 'mapa', 'configuracao', 'falhaDoMapa',
  'acoes', 'calculo', 'blocosGoogle', 'atribuicaoOrs', 'limite', 'escolherPonto', 'lojaEscolhida', 'podeAdicionar',
  'alerta', 'recarga', 'caminhoRotas',
];

// --- Os textos -----------------------------------------------------------------------------------

test('os textos do planeador', () => {
  expect({
    TEXTO_A_CARREGAR,
    TITULO_DIA_INVALIDO,
    MENSAGEM_DATA_INVALIDA,
    TEXTO_NAO_HOUVE_ROTA,
    TEXTO_CONCLUIDA_LEITURA,
    TEXTO_EM_CURSO_LEITURA,
    TEXTO_AINDA_SEM_PARAGENS,
    TEXTO_DEFINICOES_SEM_ROTA,
    TEXTO_FABRICA,
    TEXTO_PONTO_NO_MAPA,
    TEXTO_PARAGEM_SEM_LOJA,
    MENSAGEM_SEM_CALCULO,
    TEXTO_CALCULAR,
    TEXTO_RECALCULAR,
    TEXTO_GUARDAR_ROTA,
    TEXTO_PRIMEIRA_PARAGEM,
    TEXTO_NADA_A_CALCULAR,
    TEXTO_HORAS_EM_DIA,
    TEXTO_JA_PLANEADA,
    TEXTO_HORAS_A_RECALCULAR,
    TEXTO_HORAS_ANTIGAS,
    TEXTO_HORAS_ANTIGAS_LEITURA,
    TEXTO_SEM_HORAS,
    TEXTO_SUGESTOES_A_CARREGAR,
    TEXTO_SUGESTOES_NENHUMA,
  }).toEqual({
    TEXTO_A_CARREGAR: 'A carregar a rota…',
    TITULO_DIA_INVALIDO: 'Dia inválido',
    // A mensagem do servidor para a `data` (plano F3 §4).
    MENSAGEM_DATA_INVALIDA: 'Indique o dia no formato AAAA-MM-DD.',
    TEXTO_NAO_HOUVE_ROTA: 'Não houve rota neste dia.',
    TEXTO_CONCLUIDA_LEITURA: 'Concluída — só de leitura',
    // A mensagem do 409 `rota_em_curso` (plano F3 §4).
    TEXTO_EM_CURSO_LEITURA: 'A rota já tem registos do motorista — no escritório só se pode ver.',
    TEXTO_AINDA_SEM_PARAGENS: 'Ainda sem paragens',
    TEXTO_DEFINICOES_SEM_ROTA: 'Adicione a primeira paragem para mudar as definições do dia.',
    TEXTO_FABRICA: 'Fábrica',
    TEXTO_PONTO_NO_MAPA: 'Ponto no mapa',
    TEXTO_PARAGEM_SEM_LOJA: 'Loja apagada',
    MENSAGEM_SEM_CALCULO: 'Cálculo automático indisponível — ordene à mão',
    TEXTO_CALCULAR: 'Calcular melhor ordem',
    TEXTO_RECALCULAR: 'Recalcular horas',
    TEXTO_GUARDAR_ROTA: 'Guardar rota',
    // O desenho original §7.1: "Sem paragens: 'Adicione a primeira paragem pelo mapa'".
    TEXTO_PRIMEIRA_PARAGEM: 'Adicione a primeira paragem pelo mapa.',
    TEXTO_NADA_A_CALCULAR: 'Não há paragens para calcular.',
    TEXTO_HORAS_EM_DIA: 'As horas estão em dia.',
    TEXTO_JA_PLANEADA: 'A rota já está guardada como planeada.',
    // A correção "T3.16 / T3.21 / T3.32", tal e qual.
    TEXTO_HORAS_A_RECALCULAR: 'a recalcular',
    TEXTO_HORAS_ANTIGAS: 'Horas antigas — Recalcular horas',
    TEXTO_HORAS_ANTIGAS_LEITURA: 'Horas antigas',
    TEXTO_SEM_HORAS: 'sem horas — ordene à mão',
    TEXTO_SUGESTOES_A_CARREGAR: 'A procurar lojas perto…',
    TEXTO_SUGESTOES_NENHUMA: 'Não há lojas para sugerir perto desta rota.',
  });
});

// --- Funções puras -------------------------------------------------------------------------------

describe('textoDasHoras: o rótulo das horas (correção "T3.16 / T3.21 / T3.32")', () => {
  const velhas = (extra = {}) => rotaDoServidor({ calculo: { ...rotaDoServidor().calculo, atual: false }, ...extra });

  test('as horas atuais não levam rótulo, nem uma rota sem paragens na secção "rota"', () => {
    expect(textoDasHoras(rotaDoServidor())).toBeNull();
    expect(textoDasHoras(rotaDoServidor(), { aRecalcular: true })).toBeNull();
    const soFechada = velhas({ paragens: [rotaDoServidor().paragens[1]] });
    expect(textoDasHoras(soFechada)).toBeNull();
    expect(textoDasHoras(soFechada, { aRecalcular: true })).toBeNull();
    expect(textoDasHoras(velhas({ paragens: [] }))).toBeNull();
  });

  test('"a recalcular" só com um recálculo pedido; senão "Horas antigas — Recalcular horas"', () => {
    expect(textoDasHoras(velhas(), { aRecalcular: true })).toBe('a recalcular');
    expect(textoDasHoras(velhas())).toBe('Horas antigas — Recalcular horas');
    expect(textoDasHoras(velhas(), {})).toBe('Horas antigas — Recalcular horas');
    // Sem cálculo nenhum (ainda não se calculou): nada a dizer até ao recálculo.
    expect(textoDasHoras(rotaDoServidor({ calculo: null }))).toBeNull();
    expect(textoDasHoras(rotaDoServidor({ calculo: null }), { aRecalcular: true })).toBe('a recalcular');
  });

  test('sem a chave do openrouteservice: "sem horas — ordene à mão", com ou sem horas antigas', () => {
    expect(textoDasHoras(velhas({ calculo_disponivel: false }))).toBe('sem horas — ordene à mão');
    expect(textoDasHoras(rotaDoServidor({ calculo_disponivel: false, calculo: null }))).toBe('sem horas — ordene à mão');
    // O `true` do JSON e nada mais.
    expect(textoDasHoras(velhas({ calculo_disponivel: 'sim' }))).toBe('sem horas — ordene à mão');
    // As horas atuais continuam sem rótulo.
    expect(textoDasHoras(rotaDoServidor({ calculo_disponivel: false }))).toBeNull();
  });

  test('só de leitura: "Horas antigas" sem o botão, e nada sem cálculo', () => {
    expect(textoDasHoras(velhas({ editavel: false }))).toBe('Horas antigas');
    expect(textoDasHoras(velhas({ editavel: false, calculo_disponivel: false }), { aRecalcular: true })).toBe('Horas antigas');
    expect(textoDasHoras(rotaDoServidor({ editavel: false, calculo: null }))).toBeNull();
    expect(textoDasHoras(rotaDoServidor({ editavel: false }))).toBeNull();
    // Editável quer dizer `true`, nada mais.
    expect(textoDasHoras(velhas({ editavel: 1 }))).toBe('Horas antigas');
  });

  test('não rebenta com o que não é uma rota', () => {
    expect(textoDasHoras(null)).toBeNull();
    expect(textoDasHoras(undefined)).toBeNull();
    expect(textoDasHoras({})).toBeNull();
  });
});

describe('textoLeitura: porque é que a rota é só de leitura', () => {
  test('editável → null', () => {
    expect(textoLeitura(rotaDoServidor())).toBeNull();
    expect(textoLeitura(rotaVirtual())).toBeNull();
  });

  test('um dia passado: "Concluída — só de leitura", ou "Não houve rota neste dia." sem rota', () => {
    expect(textoLeitura(rotaDoServidor({ editavel: false, estado_efetivo: 'concluida' }))).toBe('Concluída — só de leitura');
    expect(textoLeitura(rotaVirtual({ editavel: false, estado_efetivo: 'concluida' }))).toBe('Não houve rota neste dia.');
  });

  test('hoje ou no futuro, com registos do motorista: a mensagem do rota_em_curso', () => {
    expect(textoLeitura(rotaDoServidor({ editavel: false, estado: 'em_curso', estado_efetivo: 'em_curso' }))).toBe(TEXTO_EM_CURSO_LEITURA);
    expect(textoLeitura(rotaDoServidor({ editavel: false }))).toBe(TEXTO_EM_CURSO_LEITURA);
  });

  test('editável quer dizer `true`', () => {
    expect(textoLeitura(rotaDoServidor({ editavel: 'true' }))).toBe(TEXTO_EM_CURSO_LEITURA);
    expect(textoLeitura(null)).toBe(TEXTO_EM_CURSO_LEITURA);
  });
});

describe('acoesDaRota: Calcular melhor ordem, Recalcular horas e Guardar rota', () => {
  const desligada = (texto, falta, extra = {}) => ({ texto, ativo: false, falta, ...extra });
  const ligada = (texto, extra = {}) => ({ texto, ativo: true, falta: null, ...extra });

  test('a rota do exemplo: calcular e guardar; as horas já estão em dia', () => {
    expect(acoesDaRota(rotaDoServidor(), { online: true })).toEqual({
      calcular: ligada('Calcular melhor ordem'),
      recalcular: desligada('Recalcular horas', 'As horas estão em dia.'),
      guardar: ligada('Guardar rota', { pergunta: null }),
    });
  });

  test('com horas antigas (ou sem cálculo) recalcula-se', () => {
    const velhas = rotaDoServidor({ calculo: { ...rotaDoServidor().calculo, atual: false } });
    expect(acoesDaRota(velhas, { online: true }).recalcular).toEqual(ligada('Recalcular horas'));
    expect(acoesDaRota(rotaDoServidor({ calculo: null }), { online: true }).recalcular).toEqual(ligada('Recalcular horas'));
  });

  test('sem rede: tudo desligado com a mensagem do sem rede, antes de qualquer outro motivo', () => {
    for (const rota of [rotaDoServidor(), rotaVirtual(), rotaDoServidor({ calculo_disponivel: false, estado: 'planeada' })]) {
      const acoes = acoesDaRota(rota, { online: false });
      expect(acoes.calcular).toEqual(desligada('Calcular melhor ordem', MENSAGEM_SEM_REDE));
      expect(acoes.recalcular).toEqual(desligada('Recalcular horas', MENSAGEM_SEM_REDE));
      expect(acoes.guardar).toEqual(desligada('Guardar rota', MENSAGEM_SEM_REDE, { pergunta: null }));
    }
    // Sem o argumento, conta como sem rede (nunca se liga uma ação por engano).
    expect(acoesDaRota(rotaDoServidor()).calcular.falta).toBe(MENSAGEM_SEM_REDE);
  });

  test('a rota virtual (correção "T3.31 / T3.39") e uma rota sem paragens ativas: "Adicione a primeira paragem pelo mapa."', () => {
    for (const rota of [rotaVirtual(), rotaDoServidor({ paragens: [] }), rotaVirtual({ paragens: rotaDoServidor().paragens })]) {
      const acoes = acoesDaRota(rota, { online: true });
      expect(acoes.calcular).toEqual(desligada('Calcular melhor ordem', 'Adicione a primeira paragem pelo mapa.'));
      expect(acoes.recalcular).toEqual(desligada('Recalcular horas', 'Adicione a primeira paragem pelo mapa.'));
      expect(acoes.guardar).toEqual(desligada('Guardar rota', 'Adicione a primeira paragem pelo mapa.', { pergunta: null }));
    }
  });

  test('sem a chave do openrouteservice: o cálculo desligado com "Cálculo automático indisponível — ordene à mão"; guardar não depende dela', () => {
    const acoes = acoesDaRota(rotaDoServidor({ calculo_disponivel: false, calculo: null }), { online: true });
    expect(acoes.calcular).toEqual(desligada('Calcular melhor ordem', MENSAGEM_SEM_CALCULO));
    expect(acoes.recalcular).toEqual(desligada('Recalcular horas', MENSAGEM_SEM_CALCULO));
    expect(acoes.guardar).toEqual(ligada('Guardar rota', { pergunta: null }));
    // Só o `true` do JSON quer dizer que há chave.
    for (const valor of [undefined, null, 'true', 1]) {
      expect(acoesDaRota(rotaDoServidor({ calculo_disponivel: valor, calculo: null }), { online: true }).recalcular.falta).toBe(MENSAGEM_SEM_CALCULO);
    }
  });

  test('o que se calcula: o VROOM leva a secção "rota" e as que não cabem; as horas só a secção "rota"', () => {
    const [, fechada, , naoCabe, , semLoja] = rotaDoServidor().paragens;
    const soNaoCabe = acoesDaRota(rotaDoServidor({ calculo: null, paragens: [naoCabe, fechada] }), { online: true });
    expect(soNaoCabe.calcular).toEqual(ligada('Calcular melhor ordem'));
    expect(soNaoCabe.recalcular).toEqual(desligada('Recalcular horas', 'Não há paragens para calcular.'));
    const nada = acoesDaRota(rotaDoServidor({ calculo: null, paragens: [fechada, semLoja] }), { online: true });
    expect(nada.calcular).toEqual(desligada('Calcular melhor ordem', 'Não há paragens para calcular.'));
    expect(nada.recalcular).toEqual(desligada('Recalcular horas', 'Não há paragens para calcular.'));
    expect(nada.guardar).toEqual(ligada('Guardar rota', { pergunta: null }));
  });

  test('guardar passa um rascunho a planeada: uma rota já planeada não tem nada a guardar', () => {
    expect(acoesDaRota(rotaDoServidor({ estado: 'planeada', estado_efetivo: 'planeada' }), { online: true }).guardar).toEqual(
      desligada('Guardar rota', 'A rota já está guardada como planeada.', { pergunta: null }),
    );
  });
});

describe('vistaDasSugestoes: a resposta do servidor no painel', () => {
  test('os grupos com o título da fase, a distância em texto ("no caminho, …") e o "e mais N"', () => {
    expect(vistaDasSugestoes(sugestoesDoServidor(), [])).toEqual({
      estado: 'lista',
      grupos: [
        {
          fase: 'contactada',
          titulo: 'A aguardar amostra',
          lojas: [
            { id: 'loja-X', nome: 'Café X', fase: 'contactada', lat: 38.71, lng: -9.11, distancia: '1,2 km', noCaminho: false },
            { id: 'loja-A', nome: 'Loja A', fase: 'contactada', lat: 38.71, lng: -9.11, distancia: '0,0 km', noCaminho: false },
          ],
          mais: 0,
          textoMais: null,
        },
        {
          fase: 'potencial',
          titulo: 'Potencial',
          lojas: [{ id: 'loja-Y', nome: 'Frutaria Y', fase: 'potencial', lat: 38.71, lng: -9.11, distancia: 'no caminho, 0,8 km', noCaminho: true }],
          mais: 3,
          textoMais: 'e mais 3',
        },
      ],
      mensagem: null,
      tentar: false,
      aTentar: false,
    });
  });

  test('as lojas que já estão na rota saem (uma resposta que chegou atrasada), e um grupo vazio também', () => {
    const vista = vistaDasSugestoes(sugestoesDoServidor(), ['loja-A', 'loja-Y']);
    expect(vista.grupos.map((g) => g.fase)).toEqual(['contactada', 'potencial']);
    expect(vista.grupos[0].lojas.map((l) => l.id)).toEqual(['loja-X']);
    // A potencial ficou sem lojas mas ainda há mais 3: o grupo fica, com o "e mais 3".
    expect(vista.grupos[1].lojas).toEqual([]);
    expect(vista.grupos[1].textoMais).toBe('e mais 3');
    const semMais = sugestoesDoServidor();
    semMais.grupos[1].mais = 0;
    expect(vistaDasSugestoes(semMais, ['loja-Y']).grupos.map((g) => g.fase)).toEqual(['contactada']);
  });

  test('sem nada para sugerir: "Não há lojas para sugerir perto desta rota."', () => {
    const vazia = { sem_paragens: false, no_caminho: false, grupos: [{ fase: 'contactada', lojas: [], mais: 0 }, { fase: 'potencial', lojas: [], mais: 0 }] };
    const esperada = { estado: 'nenhuma', grupos: [], mensagem: 'Não há lojas para sugerir perto desta rota.', tentar: false, aTentar: false };
    expect(vistaDasSugestoes(vazia, [])).toEqual(esperada);
    expect(vistaDasSugestoes(sugestoesDoServidor(), ['loja-X', 'loja-A', 'loja-Y']).estado).toBe('lista');
    const soMais = sugestoesDoServidor();
    soMais.grupos[1].mais = 0;
    expect(vistaDasSugestoes(soMais, ['loja-X', 'loja-A', 'loja-Y'])).toEqual(esperada);
  });

  test('o servidor diz que não há paragens: "Adicione a primeira paragem pelo mapa."', () => {
    expect(vistaDasSugestoes({ sem_paragens: true, no_caminho: false, grupos: [] }, [])).toEqual({
      estado: 'sem_paragens', grupos: [], mensagem: 'Adicione a primeira paragem pelo mapa.', tentar: false, aTentar: false,
    });
  });

  test('não rebenta com uma resposta estranha: grupos e lojas que não servem não contam', () => {
    expect(vistaDasSugestoes(null, []).estado).toBe('nenhuma');
    expect(vistaDasSugestoes({ grupos: 'x' }, []).estado).toBe('nenhuma');
    const estranha = {
      sem_paragens: false,
      grupos: [null, 'x', { fase: 'contactada', lojas: [null, { nome: 'sem id' }, sugestao('loja-X', 'Café X', 'contactada', -5)], mais: -2 }, { fase: 'outra', lojas: 'x', mais: 1.5 }],
    };
    expect(vistaDasSugestoes(sugestoesDoServidor(), 5).grupos[0].lojas.map((l) => l.id)).toEqual(['loja-X', 'loja-A']);
    expect(vistaDasSugestoes(estranha, null)).toEqual({
      estado: 'lista',
      grupos: [{
        fase: 'contactada',
        titulo: 'A aguardar amostra',
        lojas: [{ id: 'loja-X', nome: 'Café X', fase: 'contactada', lat: 38.71, lng: -9.11, distancia: null, noCaminho: false }],
        mais: 0,
        textoMais: null,
      }],
      mensagem: null,
      tentar: false,
      aTentar: false,
    });
    // Uma fase que não é das conhecidas fica com o próprio nome; uma distância estragada "no caminho" fica só "no caminho".
    const outra = { grupos: [{ fase: 'outra', lojas: [sugestao('loja-Z', 'Z', 'outra', 'x', true)], mais: 0 }] };
    expect(vistaDasSugestoes(outra, []).grupos[0]).toMatchObject({ titulo: 'outra', lojas: [{ distancia: 'no caminho', noCaminho: true }] });
    // O `constructor` não é uma fase.
    const proto = { grupos: [{ fase: 'constructor', lojas: [sugestao('loja-Z', 'Z', 'x', 100)], mais: 0 }] };
    expect(vistaDasSugestoes(proto, []).grupos[0].titulo).toBe('constructor');
  });
});

describe('lojasForaDaRota: as lojas esbatidas no mapa do planeador', () => {
  test('as lojas sem nenhuma paragem ativa na rota, pela ordem da lista e os mesmos objetos', () => {
    const fora = lojasForaDaRota(LOJAS, rotaDoServidor());
    expect(fora.map((l) => l.id)).toEqual(['loja-X', 'loja-Y']);
    expect(fora[0]).toBe(LOJAS[5]);
    expect(lojasForaDaRota(LOJAS, rotaVirtual())).toEqual(LOJAS);
    expect(lojasForaDaRota(LOJAS, rotaVirtual())).not.toBe(LOJAS);
  });

  test('sem as lojas (ainda não chegaram ou falharam) ou sem a rota → null', () => {
    expect(lojasForaDaRota(null, rotaDoServidor())).toBeNull();
    expect(lojasForaDaRota(undefined, rotaDoServidor())).toBeNull();
    expect(lojasForaDaRota(LOJAS, null)).toBeNull();
  });
});

// --- Carregar ------------------------------------------------------------------------------------

test('criar não pede nada; iniciar pede a rota, a configuração e as lojas ao mesmo tempo, e as sugestões só depois da rota', async () => {
  const m = montar({ iniciar: false });
  expect(m.api.pedidos).toEqual([]);
  expect(m.vista().estado).toBe('a_carregar');
  m.planeador.iniciar();
  expect(nomes(m)).toEqual(['obterRota', 'obterConfigMapa', 'listarLojas']);
  expect(ultimo(m, 'obterRota').argumentos).toEqual([DIA]);
  expect(ultimo(m, 'obterConfigMapa').argumentos).toEqual([]);
  expect(ultimo(m, 'listarLojas').argumentos).toEqual([]);
  // Iniciar outra vez não pede nada de novo, nem ouve a rede duas vezes.
  m.planeador.iniciar();
  expect(m.api.pedidos).toHaveLength(3);
  const vistas = m.vistas.length;
  m.mudarRede(false);
  expect(m.vistas).toHaveLength(vistas + 1);
  m.mudarRede(true);

  await responder(m, 'obterConfigMapa', copia(CONFIG));
  await responder(m, 'listarLojas', copia(LOJAS));
  expect(pedidos(m, 'obterSugestoes')).toEqual([]);
  await responder(m, 'obterRota', copia(rotaDoServidor()));
  expect(nomes(m)).toEqual(['obterRota', 'obterConfigMapa', 'listarLojas', 'obterSugestoes']);
  expect(ultimo(m, 'obterSugestoes').argumentos).toEqual([DIA]);
});

test('a carregar: o título do dia e o resto vazio, congelado; cada mudança vai para o aoMudarVista', async () => {
  const m = montar();
  const vista = m.vista();
  expect(Object.keys(vista)).toEqual(CHAVES_DA_VISTA);
  expect(vista).toEqual({
    estado: 'a_carregar',
    titulo: 'Rota de segunda-feira, 12 de outubro',
    somenteLeitura: false,
    textoLeitura: null,
    rotuloEstado: null,
    falha: null,
    conflito: null,
    semRede: false,
    definicoes: null,
    totais: null,
    horas: null,
    avisos: [],
    seccoes: null,
    sugestoes: null,
    mapa: { paragens: [], inicio: null, fim: null, linha: [], linhaAtual: false, lojasForaDaRota: null },
    configuracao: null,
    falhaDoMapa: null,
    acoes: null,
    calculo: null,
    blocosGoogle: [],
    atribuicaoOrs: null,
    limite: null,
    escolherPonto: null,
    lojaEscolhida: null,
    podeAdicionar: false,
    alerta: null,
    recarga: { aRecarregar: false, erro: null },
    caminhoRotas: '/crm/rotas',
  });
  expect(Object.isFrozen(vista)).toBe(true);
  expect(Object.isFrozen(vista.mapa)).toBe(true);
  expect(Object.isFrozen(vista.mapa.paragens)).toBe(true);
  expect(Object.isFrozen(vista.avisos)).toBe(true);
  expect(Object.isFrozen(vista.recarga)).toBe(true);
  expect(m.vistas.at(-1)).toBe(vista);

  await responder(m, 'obterConfigMapa', copia(CONFIG));
  expect(m.vistas.at(-1)).toBe(m.vista());
  expect(m.vista()).not.toBe(vista);
  expect(m.vista().estado).toBe('a_carregar');
  expect(m.vista().configuracao).toEqual(CONFIG);
});

test('a rota chega: o estado, as definições do dia, os totais, as horas, os avisos, o limite, os blocos e a atribuição', async () => {
  const m = await carregado();
  const vista = m.vista();
  expect(Object.keys(vista)).toEqual(CHAVES_DA_VISTA);
  expect(vista).toMatchObject({
    estado: 'rota',
    titulo: 'Rota de segunda-feira, 12 de outubro',
    somenteLeitura: false,
    textoLeitura: null,
    rotuloEstado: 'Rascunho',
    falha: null,
    conflito: null,
    semRede: false,
    escolherPonto: null,
    lojaEscolhida: null,
    caminhoRotas: '/crm/rotas',
  });
  expect(vista.definicoes).toEqual({
    hora_saida: '08:00',
    hora_regresso_limite: '19:00',
    inicio: { lat: 38.75, lng: -9.2, fabrica: true, texto: 'Fábrica' },
    fim: { lat: 38.75, lng: -9.2, fabrica: true, texto: 'Fábrica' },
    evitar_portagens: false,
    ativas: true,
    mensagem: null,
  });
  expect(vista.totais).toEqual({ distancia: '123,5 km', duracao: '5 h 21 min', regresso: '19:40', regressoTarde: true, atual: true });
  expect(vista.horas).toEqual({ atuais: true, texto: null });
  expect(vista.avisos).toEqual([
    'Regresso previsto às 19:40 — depois do limite (19:00).',
    '1 paragem fechada neste dia fica fora do cálculo até escolher "Manter".',
    '1 paragem não cabe no horário.',
  ]);
  expect(vista.limite).toEqual({ cheia: false, texto: '6 de 48 paragens' });
  expect(vista.blocosGoogle).toEqual([
    { rotulo: 'Abrir paragens 1–3 no Google Maps', quantas: 3, href: 'https://www.google.com/maps/dir/?api=1&destination=E' },
  ]);
  expect(vista.atribuicaoOrs).toEqual({
    aviso: TEXTO_ROTA_DE_TERCEIROS,
    texto: 'Developed by VROOM · Hosted by HeiGIT · Routing by openrouteservice · Data from OpenStreetMap',
    partes: ATRIBUICOES.ors.partes,
  });
  expect(vista.acoes).toEqual({
    calcular: { texto: 'Calcular melhor ordem', ativo: true, falta: null },
    recalcular: { texto: 'Recalcular horas', ativo: false, falta: 'As horas estão em dia.' },
    guardar: { texto: 'Guardar rota', ativo: true, falta: null, pergunta: null },
  });
  expect(vista.calculo).toEqual({ aCalcular: false, mensagem: null });
  expect(vista.configuracao).toEqual(CONFIG);
  expect(vista.falhaDoMapa).toBeNull();
  expect(vista.recarga).toEqual({ aRecarregar: false, erro: null });
});

test('as linhas de cada secção: número, nome, motivo, tempo, chegada, espera, aviso, links e subir/descer', async () => {
  const m = await carregado();
  const { seccoes } = m.vista();
  const { google, waze } = linksDe('A');
  expect(seccoes.rota).toEqual([
    {
      id: 'A', numero: 1, nome: 'Loja A', fase: 'contactada', motivo: 'amostra', rotuloMotivo: 'Amostra', tempo: 10,
      chegada: '09:00', espera: null, textoAviso: null, google, waze, podeSubir: false, podeDescer: true, seccao: 'rota',
    },
    {
      id: 'C', numero: 2, nome: 'Loja C', fase: 'contactada', motivo: 'amostra', rotuloMotivo: 'Amostra', tempo: 10,
      chegada: '09:02', espera: null, textoAviso: null, google: linksDe('C').google, waze: linksDe('C').waze,
      podeSubir: true, podeDescer: true, seccao: 'rota',
    },
    {
      id: 'E', numero: 3, nome: 'Loja E', fase: 'contactada', motivo: 'amostra', rotuloMotivo: 'Amostra', tempo: 10,
      chegada: '09:04', espera: 12, textoAviso: '⚠️ Fora do horário de receção', google: linksDe('E').google, waze: linksDe('E').waze,
      podeSubir: true, podeDescer: false, seccao: 'rota',
    },
  ]);
  expect(seccoes.fechadas).toEqual([{
    id: 'B', numero: null, nome: 'Loja B', fase: 'contactada', motivo: 'amostra', rotuloMotivo: 'Amostra', tempo: 10,
    chegada: null, espera: null, textoAviso: '⚠️ Fechada neste dia', google: linksDe('B').google, waze: linksDe('B').waze,
    podeSubir: false, podeDescer: false, seccao: 'fechada',
  }]);
  expect(seccoes.naoCabem.map((l) => [l.id, l.numero, l.textoAviso, l.podeSubir, l.podeDescer])).toEqual([['D', null, '⚠️ Não cabe no horário', false, false]]);
  expect(seccoes.semLoja).toEqual([{
    id: 'F', numero: null, nome: 'Loja apagada', fase: null, motivo: 'amostra', rotuloMotivo: 'Amostra', tempo: 10,
    chegada: null, espera: null, textoAviso: null, google: null, waze: null, podeSubir: false, podeDescer: false, seccao: 'sem_loja',
  }]);
  expect(Object.keys(seccoes)).toEqual(['rota', 'fechadas', 'naoCabem', 'semLoja']);
});

test('uma só paragem na secção "rota" não sobe nem desce; o motivo e o tempo seguem a paragem', async () => {
  const rota = rotaDoServidor({ paragens: [paragem('A', 0, { numero: 1, motivo: 'angariacao', tempo_servico_min: 25, espera_min: null })] });
  const m = await carregado({ rota });
  expect(m.vista().seccoes.rota[0]).toMatchObject({ podeSubir: false, podeDescer: false, motivo: 'angariacao', rotuloMotivo: 'Angariação', tempo: 25, espera: null });
  // Uma chegada em falta (ou que não é texto) fica null.
  const semChegada = paragem('A', 0, { numero: 1 });
  delete semChegada.chegada_prevista;
  const n = await carregado({ rota: rotaDoServidor({ paragens: [semChegada, paragem('C', 1, { numero: 2, chegada_prevista: 900 })] }) });
  expect(n.vista().seccoes.rota.map((l) => l.chegada)).toEqual([null, null]);
});

test('os links de navegação só passam pelo hrefNavegacao: o que não for um link do Google Maps ou do Waze fica de fora', async () => {
  // eslint-disable-next-line no-script-url -- é o ataque que o hrefNavegacao tem de recusar
  const estragada = paragem('A', 0, { numero: 1, links: { google: 'javascript:alert(1)', waze: 'http://waze.com/ul?ll=1' } });
  const rota = rotaDoServidor({
    paragens: [estragada],
    blocos_google: [
      { de: 1, ate: 1, quantas: 1, rotulo: 'Abrir paragem 1 no Google Maps', href: 'https://exemplo.invalid/maps' },
      { de: 1, ate: 1, quantas: 1, rotulo: 'Bom', href: 'https://www.google.com/maps/dir/?api=1&destination=1' },
    ],
  });
  const m = await carregado({ rota });
  expect(m.vista().seccoes.rota[0]).toMatchObject({ google: null, waze: null });
  expect(m.vista().blocosGoogle).toEqual([{ rotulo: 'Bom', quantas: 1, href: 'https://www.google.com/maps/dir/?api=1&destination=1' }]);
  // Os blocos que não vêm numa lista não rebentam.
  const semBlocos = await carregado({ rota: rotaDoServidor({ blocos_google: null }) });
  expect(semBlocos.vista().blocosGoogle).toEqual([]);
});

test('a vista é congelada a fundo', async () => {
  const m = await comSugestoes();
  const v = m.vista();
  for (const parte of [
    v, v.definicoes, v.definicoes.inicio, v.totais, v.horas, v.avisos, v.seccoes, v.seccoes.rota, v.seccoes.rota[0],
    v.sugestoes, v.sugestoes.grupos, v.sugestoes.grupos[0], v.sugestoes.grupos[0].lojas, v.sugestoes.grupos[0].lojas[0],
    v.mapa, v.mapa.paragens, v.mapa.paragens[0], v.mapa.inicio, v.mapa.linha, v.mapa.linha[0], v.mapa.lojasForaDaRota,
    v.mapa.lojasForaDaRota[0], v.configuracao, v.configuracao.google, v.acoes, v.acoes.calcular, v.calculo, v.blocosGoogle,
    v.blocosGoogle[0], v.atribuicaoOrs, v.limite, v.recarga,
  ]) {
    expect(Object.isFrozen(parte)).toBe(true);
  }
});

test('outras definições do dia: um ponto próprio, as portagens e as horas da rota', async () => {
  const rota = rotaDoServidor({
    hora_saida: '07:30', hora_regresso_limite: '18:00', evitar_portagens: true, inicio: { lat: 38.6, lng: -9.0, fabrica: false },
  });
  const m = await carregado({ rota });
  expect(m.vista().definicoes).toMatchObject({
    hora_saida: '07:30',
    hora_regresso_limite: '18:00',
    evitar_portagens: true,
    inicio: { lat: 38.6, lng: -9.0, fabrica: false, texto: 'Ponto no mapa' },
    fim: { lat: 38.75, lng: -9.2, fabrica: true, texto: 'Fábrica' },
  });
  // Uma ponta estragada fica null; as portagens só com o `true` do JSON.
  const estranha = await carregado({ rota: rotaDoServidor({ inicio: null, fim: { lat: 'x', lng: 1 }, evitar_portagens: 'sim' }) });
  expect(estranha.vista().definicoes).toMatchObject({ inicio: null, fim: null, evitar_portagens: false });
  expect(estranha.vista().mapa).toMatchObject({ inicio: null, fim: null });
});

// --- O mapa --------------------------------------------------------------------------------------

test('o mapa: as paragens com coordenadas (o número, o nome, a fase e o aviso), os extremos e a linha', async () => {
  const m = await carregado();
  const { mapa } = m.vista();
  const ponto = (id, ordem, numero, seccao, aviso = null) => ({
    id, numero, nome: `Loja ${id}`, fase: 'contactada', lat: 38.7 + ordem / 100, lng: -9.1 - ordem / 100, aviso, seccao,
  });
  expect(mapa.paragens).toEqual([
    ponto('A', 0, 1, 'rota'),
    ponto('B', 1, null, 'fechada', '⚠️ Fechada neste dia'),
    ponto('C', 2, 2, 'rota'),
    ponto('D', 3, null, 'nao_cabe', '⚠️ Não cabe no horário'),
    ponto('E', 4, 3, 'rota', '⚠️ Fora do horário de receção'),
  ]);
  expect(mapa.inicio).toEqual({ lat: 38.75, lng: -9.2, fabrica: true });
  expect(mapa.fim).toEqual({ lat: 38.75, lng: -9.2, fabrica: true });
  expect(mapa.linha).toEqual(descodificarPolilinha(GEOMETRIA));
  expect(mapa.linha).toEqual([[38.5, -120.2], [40.7, -120.95]]);
  expect(mapa.linhaAtual).toBe(true);
  expect(mapa.lojasForaDaRota.map((l) => l.id)).toEqual(['loja-X', 'loja-Y']);
  expect(Object.keys(mapa)).toEqual(['paragens', 'inicio', 'fim', 'linha', 'linhaAtual', 'lojasForaDaRota']);
});

test('o mapa: a linha antiga, sem cálculo, sem coordenadas e antes das lojas', async () => {
  const velha = await carregado({ rota: rotaDoServidor({ calculo: { ...rotaDoServidor().calculo, atual: false } }) });
  expect(velha.vista().mapa).toMatchObject({ linha: [[38.5, -120.2], [40.7, -120.95]], linhaAtual: false });
  const semCalculo = await carregado({ rota: rotaDoServidor({ calculo: null }) });
  expect(semCalculo.vista().mapa).toMatchObject({ linha: [], linhaAtual: false });
  const estragada = await carregado({ rota: rotaDoServidor({ calculo: { ...rotaDoServidor().calculo, geometria: 'estragada!' } }) });
  expect(estragada.vista().mapa.linha).toEqual([]);
  // Uma loja da paragem sem coordenadas não tem pino.
  const semPonto = paragem('A', 0, { numero: 1, loja: lojaDaParagem('Loja A', 0, { lat: null }) });
  const semCoordenadas = await carregado({ rota: rotaDoServidor({ paragens: [semPonto] }) });
  expect(semCoordenadas.vista().mapa.paragens).toEqual([]);

  // Antes de a rota chegar não há lojas "fora da rota"; antes das lojas também não.
  const m = montar();
  await responder(m, 'listarLojas', copia(LOJAS));
  expect(m.vista().mapa.lojasForaDaRota).toBeNull();
  const n = montar();
  await responder(n, 'obterRota', copia(rotaDoServidor()));
  expect(n.vista().mapa.lojasForaDaRota).toBeNull();
  await responder(n, 'listarLojas', copia(LOJAS));
  expect(n.vista().mapa.lojasForaDaRota.map((l) => l.id)).toEqual(['loja-X', 'loja-Y']);
});

test('a mesma referência do mapa e das lojas fora da rota enquanto nada muda (correção "T3.32 / T3.38")', async () => {
  const m = await carregado();
  const antes = m.vista();
  await responder(m, 'obterSugestoes', copia(sugestoesDoServidor()));
  const depois = m.vista();
  expect(depois).not.toBe(antes);
  expect(depois.mapa).toBe(antes.mapa);
  expect(depois.mapa.lojasForaDaRota).toBe(antes.mapa.lojasForaDaRota);
  expect(depois.mapa.linha).toBe(antes.mapa.linha);

  // Recarregar a mesma rota (outro objeto, o mesmo conteúdo): tudo igual.
  m.planeador.recarregar();
  await responder(m, 'obterRota', copia(rotaDoServidor()));
  expect(m.vista().mapa).toBe(antes.mapa);

  // Uma hora de chegada nova (o mapa não a mostra): o mapa fica.
  const outraHora = rotaDoServidor();
  outraHora.paragens[0].chegada_prevista = '10:00';
  m.planeador.recarregar();
  await responder(m, 'obterRota', copia(outraHora));
  expect(m.vista().seccoes.rota[0].chegada).toBe('10:00');
  expect(m.vista().mapa).toBe(antes.mapa);

  // A X entrou na rota: as lojas fora da rota mudam; a linha (a mesma geometria) fica.
  const comX = rotaDoServidor();
  comX.paragens.push({ ...paragem('X', 6, { numero: 4 }), loja_id: 'loja-X' });
  m.planeador.recarregar();
  await responder(m, 'obterRota', copia(comX));
  const comXVista = m.vista();
  expect(comXVista.mapa).not.toBe(antes.mapa);
  expect(comXVista.mapa.lojasForaDaRota).not.toBe(antes.mapa.lojasForaDaRota);
  expect(comXVista.mapa.lojasForaDaRota.map((l) => l.id)).toEqual(['loja-Y']);
  expect(comXVista.mapa.linha).toBe(antes.mapa.linha);

  // Outra ordem das mesmas lojas: as lojas fora da rota ficam; os pinos mudam.
  const outraOrdem = copia(comX);
  outraOrdem.paragens.reverse();
  m.planeador.recarregar();
  await responder(m, 'obterRota', outraOrdem);
  expect(m.vista().mapa).not.toBe(comXVista.mapa);
  expect(m.vista().mapa.lojasForaDaRota).toBe(comXVista.mapa.lojasForaDaRota);

  // Só as horas ficaram antigas (a mesma geometria): o mapa muda, a linha fica.
  const antigas = copia(outraOrdem);
  antigas.calculo.atual = false;
  m.planeador.recarregar();
  await responder(m, 'obterRota', copia(antigas));
  expect(m.vista().mapa).not.toBe(comXVista.mapa);
  expect(m.vista().mapa).toMatchObject({ linhaAtual: false });
  expect(m.vista().mapa.linha).toBe(antes.mapa.linha);

  // A Y entra numa paragem sem pino (a loja sem coordenadas): os pinos ficam, as lojas fora da rota não.
  const comY = copia(outraOrdem);
  comY.paragens.push({ ...paragem('Y', 7, { numero: 5, loja: lojaDaParagem('Loja Y', 7, { lat: null }) }), loja_id: 'loja-Y' });
  m.planeador.recarregar();
  await responder(m, 'obterRota', copia(comY));
  expect(m.vista().mapa.paragens).toEqual(comXVista.mapa.paragens.slice().reverse());
  expect(m.vista().mapa.lojasForaDaRota).toEqual([]);
  const semY = m.vista().mapa;
  m.planeador.recarregar();
  await responder(m, 'obterRota', copia(outraOrdem));
  expect(m.vista().mapa).not.toBe(semY);
  expect(m.vista().mapa.paragens).toEqual(semY.paragens);
  expect(m.vista().mapa.lojasForaDaRota.map((l) => l.id)).toEqual(['loja-Y']);

  // Cada mudança, uma de cada vez (por cima da anterior): outro início, outro fim, outra geometria (com as
  // horas atuais) e as horas antigas (com a mesma geometria). O mapa muda sempre.
  let estado = copia(outraOrdem);
  for (const mudar of [
    (r) => { r.inicio = { lat: 38.6, lng: -9.0, fabrica: false }; },
    (r) => { r.fim = { lat: 38.6, lng: -9.0, fabrica: false }; },
    (r) => { r.calculo.geometria = '_p~iF~ps|U'; },
    (r) => { r.calculo.atual = false; },
  ]) {
    const anterior = m.vista().mapa;
    estado = copia(estado);
    mudar(estado);
    m.planeador.recarregar();
    await responder(m, 'obterRota', copia(estado));
    expect(m.vista().mapa).not.toBe(anterior);
  }
  expect(m.vista().mapa).toMatchObject({
    inicio: { lat: 38.6, lng: -9.0, fabrica: false }, fim: { lat: 38.6, lng: -9.0, fabrica: false }, linha: [[38.5, -120.2]], linhaAtual: false,
  });
});

test('a lista das lojas é a mesma referência até chegar outra', async () => {
  const m = await carregado({ rota: rotaVirtual() });
  const fora = m.vista().mapa.lojasForaDaRota;
  expect(fora.map((l) => l.id)).toEqual(LOJAS.map((l) => l.id));
  m.planeador.recarregar();
  await responder(m, 'obterRota', copia(rotaVirtual()));
  expect(m.vista().mapa.lojasForaDaRota).toBe(fora);
});

// --- As sugestões --------------------------------------------------------------------------------

test('as sugestões: a carregar, depois a lista sem as lojas que já estão na rota', async () => {
  const m = await carregado();
  expect(m.vista().sugestoes).toEqual({
    estado: 'a_carregar', grupos: [], mensagem: 'A procurar lojas perto…', tentar: false, aTentar: false,
  });
  await responder(m, 'obterSugestoes', copia(sugestoesDoServidor()));
  const { sugestoes } = m.vista();
  expect(sugestoes.estado).toBe('lista');
  expect(sugestoes.grupos.map((g) => [g.fase, g.lojas.map((l) => l.id), g.textoMais])).toEqual([
    ['contactada', ['loja-X'], null],
    ['potencial', ['loja-Y'], 'e mais 3'],
  ]);
  expect(sugestoes.grupos[1].lojas[0].distancia).toBe('no caminho, 0,8 km');
});

test('as sugestões: o servidor sem nada, ou a dizer que não há paragens', async () => {
  const m = await comSugestoes({}, { sem_paragens: false, no_caminho: false, grupos: [] });
  expect(m.vista().sugestoes).toMatchObject({ estado: 'nenhuma', mensagem: 'Não há lojas para sugerir perto desta rota.' });
  const n = await comSugestoes({}, { sem_paragens: true, no_caminho: false, grupos: [] });
  expect(n.vista().sugestoes).toMatchObject({ estado: 'sem_paragens', mensagem: 'Adicione a primeira paragem pelo mapa.' });
});

test('as sugestões numa rota sem paragens com loja: "Adicione a primeira paragem pelo mapa.", sem pedir nada', async () => {
  for (const rota of [rotaVirtual(), rotaDoServidor({ paragens: [] }), rotaDoServidor({ paragens: [paragem('F', 0, { seccao: 'sem_loja', semLoja: true })] })]) {
    const m = await carregado({ rota });
    expect(pedidos(m, 'obterSugestoes')).toEqual([]);
    expect(m.vista().sugestoes).toEqual({
      estado: 'sem_paragens', grupos: [], mensagem: 'Adicione a primeira paragem pelo mapa.', tentar: false, aTentar: false,
    });
  }
});

test('as sugestões falham: a mensagem e "Tentar novamente", que só volta a pedir as sugestões', async () => {
  const m = await carregado();
  await falhar(m, 'obterSugestoes', erroServidor('As sugestões falharam.'));
  expect(m.vista().estado).toBe('rota');
  expect(m.vista().sugestoes).toEqual({
    estado: 'falha', grupos: [], mensagem: 'As sugestões falharam.', tentar: true, aTentar: false,
  });
  const antes = m.api.pedidos.length;
  m.planeador.tentarDeNovo();
  expect(nomes(m).slice(antes)).toEqual(['obterSugestoes']);
  expect(m.vista().sugestoes).toMatchObject({ estado: 'falha', tentar: true, aTentar: true });
  // Um toque, um pedido.
  m.planeador.tentarDeNovo();
  expect(m.api.pedidos).toHaveLength(antes + 1);
  await responder(m, 'obterSugestoes', copia(sugestoesDoServidor()));
  expect(m.vista().sugestoes.estado).toBe('lista');
  // Já sem falhas: tentar de novo não pede nada.
  m.planeador.tentarDeNovo();
  expect(m.api.pedidos).toHaveLength(antes + 1);
});

test('as sugestões: um erro inesperado tem a mensagem geral', async () => {
  const m = await carregado();
  await falhar(m, 'obterSugestoes', new TypeError('x'));
  expect(m.vista().sugestoes.mensagem).toBe(MENSAGEM_ERRO_INESPERADO);
});

test('as sugestões: só conta a resposta do último pedido; a lista antiga fica até chegar a nova', async () => {
  const m = await comSugestoes();
  m.planeador.recarregar();
  await responder(m, 'obterRota', copia(rotaDoServidor()));
  expect(pedidos(m, 'obterSugestoes')).toHaveLength(2);
  // Enquanto a nova não chega, fica a lista que já se tinha.
  expect(m.vista().sugestoes.estado).toBe('lista');
  m.planeador.recarregar();
  await responder(m, 'obterRota', copia(rotaDoServidor()));
  const [, segundo, terceiro] = pedidos(m, 'obterSugestoes');
  // A segunda (já velha) chega depois: não conta, nem a falhar.
  segundo.resolver({ sem_paragens: false, no_caminho: false, grupos: [] });
  await assentar();
  expect(m.vista().sugestoes.estado).toBe('lista');
  segundo.rejeitar(erroServidor());
  await assentar();
  expect(m.vista().sugestoes.estado).toBe('lista');
  terceiro.resolver({ sem_paragens: false, no_caminho: false, grupos: [] });
  await assentar();
  expect(m.vista().sugestoes.estado).toBe('nenhuma');
});

test('as sugestões: uma falha de um pedido velho não conta (o "Tentar novamente" não pede outra vez)', async () => {
  const m = await carregado();
  await falhar(m, 'obterSugestoes', erroServidor());
  m.planeador.recarregar();
  await responder(m, 'obterRota', copia(rotaDoServidor()));
  m.planeador.recarregar();
  await responder(m, 'obterRota', copia(rotaDoServidor()));
  const [, segundo] = pedidos(m, 'obterSugestoes');
  expect(pedidos(m, 'obterSugestoes')).toHaveLength(3);
  segundo.rejeitar(erroServidor());
  await assentar();
  // O terceiro ainda está em curso: tentar de novo não pede outro.
  expect(m.vista().sugestoes).toMatchObject({ estado: 'falha', aTentar: true });
  m.planeador.tentarDeNovo();
  expect(pedidos(m, 'obterSugestoes')).toHaveLength(3);
});

test('as sugestões: uma falha depois de uma lista mantém a lista', async () => {
  const m = await comSugestoes();
  m.planeador.recarregar();
  await responder(m, 'obterRota', copia(rotaDoServidor()));
  await falhar(m, 'obterSugestoes', erroServidor());
  expect(m.vista().sugestoes.estado).toBe('lista');
});

test('as sugestões: a rota recarregada sem paragens deita fora as que havia e o pedido em curso', async () => {
  const m = await comSugestoes();
  m.planeador.recarregar();
  await responder(m, 'obterRota', copia(rotaDoServidor()));
  const emCurso = ultimo(m, 'obterSugestoes');
  m.planeador.recarregar();
  await responder(m, 'obterRota', copia(rotaDoServidor({ paragens: [] })));
  expect(m.vista().sugestoes.estado).toBe('sem_paragens');
  emCurso.resolver(copia(sugestoesDoServidor()));
  await assentar();
  expect(m.vista().sugestoes.estado).toBe('sem_paragens');
  // Volta a ter paragens: a carregar (a lista antiga já não conta).
  m.planeador.recarregar();
  await responder(m, 'obterRota', copia(rotaDoServidor()));
  expect(m.vista().sugestoes.estado).toBe('a_carregar');
});

// --- A rota virtual -------------------------------------------------------------------------------

test('a rota virtual de um dia sem rota: as definições do dia desligadas, sem calcular nem guardar (correções "T3.31 / T3.39" e "T3.20 / T3.31 / T3.39")', async () => {
  const m = await carregado({ rota: rotaVirtual() });
  const v = m.vista();
  expect(v).toMatchObject({ estado: 'rota', somenteLeitura: false, textoLeitura: null, rotuloEstado: 'Ainda sem paragens' });
  expect(v.definicoes).toEqual({
    hora_saida: '08:00',
    hora_regresso_limite: '19:00',
    inicio: { lat: 38.75, lng: -9.2, fabrica: true, texto: 'Fábrica' },
    fim: { lat: 38.75, lng: -9.2, fabrica: true, texto: 'Fábrica' },
    evitar_portagens: false,
    ativas: false,
    mensagem: 'Adicione a primeira paragem para mudar as definições do dia.',
  });
  expect(v.acoes.calcular).toEqual({ texto: 'Calcular melhor ordem', ativo: false, falta: 'Adicione a primeira paragem pelo mapa.' });
  expect(v.acoes.guardar).toMatchObject({ ativo: false, falta: 'Adicione a primeira paragem pelo mapa.' });
  expect(v.acoes.recalcular).toMatchObject({ ativo: false });
  expect(v.totais).toBeNull();
  expect(v.horas).toEqual({ atuais: false, texto: null });
  expect(v.avisos).toEqual([]);
  expect(v.seccoes).toEqual({ rota: [], fechadas: [], naoCabem: [], semLoja: [] });
  expect(v.limite).toEqual({ cheia: false, texto: '0 de 48 paragens' });
  expect(v.blocosGoogle).toEqual([]);
  expect(v.mapa).toMatchObject({ paragens: [], linha: [], linhaAtual: false });
  expect(v.atribuicaoOrs).not.toBeNull();
});

test('a rota existente fica com as definições ligadas mesmo sem paragens ativas', async () => {
  const m = await carregado({ rota: rotaDoServidor({ paragens: [] }) });
  expect(m.vista().definicoes).toMatchObject({ ativas: true, mensagem: null });
  expect(m.vista().rotuloEstado).toBe('Rascunho');
});

test('o limite das 48 paragens: com 48 ativas a rota está cheia', async () => {
  const cheias = Array.from({ length: 48 }, (_, i) => paragem(`P${i}`, i, { numero: i + 1 }));
  const m = await carregado({ rota: rotaDoServidor({ paragens: cheias }) });
  expect(m.vista().limite).toEqual({ cheia: true, texto: 'Uma rota tem no máximo 48 paragens.' });
  const quase = await carregado({ rota: rotaDoServidor({ paragens: cheias.slice(1) }) });
  expect(quase.vista().limite).toEqual({ cheia: false, texto: '47 de 48 paragens' });
  // O limite vem do servidor; sem ele, o do rota.js.
  const outro = await carregado({ rota: rotaDoServidor({ paragens: cheias.slice(0, 3), limite_paragens: 3 }) });
  expect(outro.vista().limite).toEqual({ cheia: true, texto: 'Uma rota tem no máximo 3 paragens.' });
  const semLimite = await carregado({ rota: rotaDoServidor({ limite_paragens: null }) });
  expect(semLimite.vista().limite.texto).toBe('6 de 48 paragens');
});

test('sem a chave do openrouteservice: o cálculo desligado e "sem horas — ordene à mão"', async () => {
  const m = await carregado({ rota: rotaDoServidor({ calculo_disponivel: false, calculo: null }) });
  expect(m.vista().calculo).toEqual({ aCalcular: false, mensagem: 'Cálculo automático indisponível — ordene à mão' });
  expect(m.vista().acoes.calcular.falta).toBe('Cálculo automático indisponível — ordene à mão');
  expect(m.vista().horas).toEqual({ atuais: false, texto: 'sem horas — ordene à mão' });
  const velhas = await carregado({ rota: rotaDoServidor({ calculo: { ...rotaDoServidor().calculo, atual: false } }) });
  expect(velhas.vista().horas).toEqual({ atuais: false, texto: 'Horas antigas — Recalcular horas' });
  expect(velhas.vista().totais.atual).toBe(false);
  // Com horas antigas, o regresso tarde já não é aviso (rota.js).
  expect(velhas.vista().avisos).toHaveLength(2);
});

// --- Leitura só ----------------------------------------------------------------------------------

test('leitura só: um dia passado com rota — "Concluída — só de leitura", sem ações nem sugestões', async () => {
  const rota = rotaDoServidor({ estado: 'planeada', estado_efetivo: 'concluida', editavel: false, calculo: { ...rotaDoServidor().calculo, atual: false } });
  const m = await carregado({ rota });
  const v = m.vista();
  expect(v).toMatchObject({
    estado: 'rota', somenteLeitura: true, textoLeitura: 'Concluída — só de leitura', rotuloEstado: 'Concluída',
    acoes: null, calculo: null, sugestoes: null,
  });
  expect(pedidos(m, 'obterSugestoes')).toEqual([]);
  expect(v.definicoes).toMatchObject({ ativas: false, mensagem: null });
  for (const linha of [...v.seccoes.rota, ...v.seccoes.fechadas, ...v.seccoes.naoCabem]) {
    expect([linha.podeSubir, linha.podeDescer]).toEqual([false, false]);
  }
  expect(v.horas).toEqual({ atuais: false, texto: 'Horas antigas' });
  // Os links, os blocos, os totais e o mapa continuam: servem para ver.
  expect(v.seccoes.rota[0].google).toBe(linksDe('A').google);
  expect(v.blocosGoogle).toHaveLength(1);
  expect(v.totais).not.toBeNull();
  expect(v.mapa.paragens).toHaveLength(5);
  expect(v.atribuicaoOrs).not.toBeNull();
});

test('leitura só: um dia passado sem rota — "Não houve rota neste dia."', async () => {
  const m = await carregado({ rota: rotaVirtual({ estado_efetivo: 'concluida', editavel: false }) });
  expect(m.vista()).toMatchObject({
    somenteLeitura: true, textoLeitura: 'Não houve rota neste dia.', rotuloEstado: 'Concluída', acoes: null, sugestoes: null,
  });
  expect(m.vista().definicoes).toMatchObject({ ativas: false, mensagem: null });
});

test('leitura só: a rota com registos do motorista (hoje ou no futuro)', async () => {
  const feita = rotaDoServidor({ estado: 'planeada', estado_efetivo: 'planeada', editavel: false });
  feita.paragens[0].estado = 'feita';
  const m = await carregado({ rota: feita });
  expect(m.vista()).toMatchObject({
    somenteLeitura: true,
    textoLeitura: 'A rota já tem registos do motorista — no escritório só se pode ver.',
    rotuloEstado: 'Planeada',
    acoes: null,
    sugestoes: null,
  });
  const emCurso = await carregado({ rota: rotaDoServidor({ estado: 'em_curso', estado_efetivo: 'em_curso', editavel: false }) });
  expect(emCurso.vista().rotuloEstado).toBe('Em curso');
  // Editável é o `true` do JSON e nada mais.
  const texto = await carregado({ rota: rotaDoServidor({ editavel: 'true' }) });
  expect(texto.vista()).toMatchObject({ somenteLeitura: true, acoes: null, calculo: null, sugestoes: null });
  expect(texto.vista().seccoes.rota[1]).toMatchObject({ podeSubir: false, podeDescer: false });
});

// --- Dia inválido, falhas e sem rede -------------------------------------------------------------

test.each([['2026-02-30'], ['abc'], [''], ['2026-1-1'], [undefined], [null], ['2026-10-12\n']])(
  'a data %p não é um dia: "Dia inválido", sem pedir nada',
  (data) => {
    const m = montar({ data });
    expect(m.api.pedidos).toEqual([]);
    expect(m.vista()).toMatchObject({
      estado: 'data_invalida',
      titulo: 'Dia inválido',
      falha: { mensagem: 'Indique o dia no formato AAAA-MM-DD.', tentar: false, aTentar: false },
      caminhoRotas: '/crm/rotas',
    });
    m.planeador.tentarDeNovo();
    m.planeador.recarregar();
    m.mudarRede(false);
    m.mudarRede(true);
    expect(m.api.pedidos).toEqual([]);
  },
);

test('o servidor recusa o dia (422 na data): "Dia inválido" com a mensagem dele, e tentar de novo não pede nada', async () => {
  const m = montar();
  const mensagem = 'Escolha um dia até um ano a partir de hoje.';
  await falhar(m, 'obterRota', new ErroCrm({ codigo: 'validacao', mensagem: 'Verifique os campos assinalados.', estado: 422, campos: { data: mensagem } }));
  expect(m.vista()).toMatchObject({ estado: 'data_invalida', titulo: 'Dia inválido', falha: { mensagem, tentar: false, aTentar: false } });
  const antes = m.api.pedidos.length;
  m.planeador.tentarDeNovo();
  m.mudarRede(true);
  expect(m.api.pedidos).toHaveLength(antes);
  // Um 422 sem a data é uma falha como as outras.
  const n = montar();
  await falhar(n, 'obterRota', new ErroCrm({ codigo: 'validacao', mensagem: 'Verifique os campos assinalados.', estado: 422, campos: { outra: 'x' } }));
  expect(n.vista()).toMatchObject({ estado: 'falha', falha: { mensagem: 'Verifique os campos assinalados.', tentar: true } });
  const o = montar();
  await falhar(o, 'obterRota', new ErroCrm({ codigo: 'validacao', mensagem: 'Verifique.', estado: 422, campos: { data: '' } }));
  expect(o.vista().estado).toBe('falha');
  // Só o 422 da validação: outro erro com um campo `data` é uma falha.
  const p = montar();
  await falhar(p, 'obterRota', new ErroCrm({ codigo: 'conflito', mensagem: 'Outro.', estado: 409, campos: { data: 'x' } }));
  expect(p.vista()).toMatchObject({ estado: 'falha', falha: { mensagem: 'Outro.' } });
});

test('com o dia recusado, a configuração e as lojas que falharam não se voltam a pedir', async () => {
  const m = montar();
  await falhar(m, 'obterConfigMapa', erroSemRede());
  await falhar(m, 'listarLojas', erroSemRede());
  await falhar(m, 'obterRota', new ErroCrm({ codigo: 'validacao', mensagem: 'Verifique.', estado: 422, campos: { data: 'Escolha um dia até um ano a partir de hoje.' } }));
  m.planeador.tentarDeNovo();
  m.mudarRede(true);
  expect(m.api.pedidos).toHaveLength(3);
});

test('a rota não carrega: a mensagem e "Tentar novamente", que só volta a pedir a rota', async () => {
  const m = montar();
  await responder(m, 'obterConfigMapa', copia(CONFIG));
  await responder(m, 'listarLojas', copia(LOJAS));
  await falhar(m, 'obterRota', erroSemRede());
  expect(m.vista()).toMatchObject({
    estado: 'falha',
    falha: { mensagem: MENSAGEM_SEM_REDE, tentar: true, aTentar: false },
    definicoes: null,
    seccoes: null,
    acoes: null,
    atribuicaoOrs: null,
  });
  expect(pedidos(m, 'obterSugestoes')).toEqual([]);
  m.planeador.tentarDeNovo();
  expect(nomes(m)).toEqual(['obterRota', 'obterConfigMapa', 'listarLojas', 'obterRota']);
  expect(m.vista()).toMatchObject({ estado: 'falha', falha: { aTentar: true } });
  m.planeador.tentarDeNovo();
  expect(pedidos(m, 'obterRota')).toHaveLength(2);
  await responder(m, 'obterRota', copia(rotaDoServidor()));
  expect(m.vista()).toMatchObject({ estado: 'rota', falha: null });
  expect(pedidos(m, 'obterSugestoes')).toHaveLength(1);
  // Com a rota, tentar de novo não volta a pedi-la.
  m.planeador.tentarDeNovo();
  expect(pedidos(m, 'obterRota')).toHaveLength(2);
});

test('a rota falha outra vez: a falha nova, e um erro inesperado com a mensagem geral', async () => {
  const m = montar();
  await falhar(m, 'obterRota', erroSemRede());
  m.planeador.tentarDeNovo();
  await falhar(m, 'obterRota', new TypeError('engano'));
  expect(m.vista().falha).toEqual({ mensagem: MENSAGEM_ERRO_INESPERADO, tentar: true, aTentar: false });
});

test('uma resposta da rota que não é um objeto é uma falha', async () => {
  for (const resposta of [null, 'x', [rotaDoServidor()]]) {
    const m = montar();
    await responder(m, 'obterRota', resposta);
    expect(m.vista()).toMatchObject({ estado: 'falha', falha: { mensagem: MENSAGEM_ERRO_INESPERADO, tentar: true } });
  }
});

test('a configuração do mapa ou as lojas não carregam: a rota mostra-se, e "Tentar novamente" pede só o que falhou', async () => {
  const m = montar();
  await falhar(m, 'obterConfigMapa', erroServidor('A configuração falhou.'));
  await responder(m, 'listarLojas', copia(LOJAS));
  await responder(m, 'obterRota', copia(rotaDoServidor()));
  expect(m.vista()).toMatchObject({ estado: 'rota', configuracao: null, falhaDoMapa: { mensagem: 'A configuração falhou.', aTentar: false } });
  const antes = m.api.pedidos.length;
  m.planeador.tentarDeNovo();
  expect(nomes(m).slice(antes)).toEqual(['obterConfigMapa']);
  expect(m.vista().falhaDoMapa).toEqual({ mensagem: 'A configuração falhou.', aTentar: true });
  m.planeador.tentarDeNovo();
  expect(m.api.pedidos).toHaveLength(antes + 1);
  await responder(m, 'obterConfigMapa', copia(CONFIG));
  expect(m.vista()).toMatchObject({ falhaDoMapa: null, configuracao: CONFIG });

  const n = montar();
  await responder(n, 'obterConfigMapa', null);
  await falhar(n, 'listarLojas', erroServidor('As lojas falharam.'));
  await responder(n, 'obterRota', copia(rotaDoServidor()));
  // Uma configuração vazia (null) conta como {}: o mapa diz "não configurado" pela regra do ecraMapa.
  expect(n.vista().configuracao).toEqual({});
  expect(n.vista()).toMatchObject({ falhaDoMapa: { mensagem: 'As lojas falharam.', aTentar: false } });
  expect(n.vista().mapa.lojasForaDaRota).toBeNull();
  const antesN = n.api.pedidos.length;
  n.planeador.tentarDeNovo();
  expect(nomes(n).slice(antesN)).toEqual(['listarLojas']);
  n.planeador.tentarDeNovo();
  expect(n.api.pedidos).toHaveLength(antesN + 1);
  expect(n.vista().falhaDoMapa).toMatchObject({ aTentar: true });
  await responder(n, 'listarLojas', 'não é uma lista');
  expect(n.vista().falhaDoMapa).toBeNull();
  expect(n.vista().mapa.lojasForaDaRota).toEqual([]);
});

test('as duas falham: a mensagem da configuração primeiro; tentar de novo pede as duas', async () => {
  const m = montar();
  await falhar(m, 'listarLojas', erroServidor('As lojas falharam.'));
  await falhar(m, 'obterConfigMapa', erroServidor('A configuração falhou.'));
  expect(m.vista().falhaDoMapa).toEqual({ mensagem: 'A configuração falhou.', aTentar: false });
  m.planeador.tentarDeNovo();
  expect(nomes(m).slice(3)).toEqual(['obterConfigMapa', 'listarLojas']);
  await responder(m, 'obterConfigMapa', copia(CONFIG));
  expect(m.vista().falhaDoMapa).toEqual({ mensagem: 'As lojas falharam.', aTentar: true });
});

test('sem rede: semRede, as ações e as definições do dia desligadas, sem subir nem descer', async () => {
  const m = await carregado({ online: false });
  const v = m.vista();
  expect(v.semRede).toBe(true);
  expect(v.acoes.calcular).toEqual({ texto: 'Calcular melhor ordem', ativo: false, falta: MENSAGEM_SEM_REDE });
  expect(v.acoes.guardar).toMatchObject({ ativo: false, falta: MENSAGEM_SEM_REDE });
  expect(v.definicoes).toMatchObject({ ativas: false, mensagem: null });
  expect(v.seccoes.rota.map((l) => [l.podeSubir, l.podeDescer])).toEqual([[false, false], [false, false], [false, false]]);
  // Os pedidos saem na mesma: o navigator.onLine só é fiável no "sem rede", e o pedido dirá.
  expect(nomes(m)).toEqual(['obterRota', 'obterConfigMapa', 'listarLojas', 'obterSugestoes']);
});

test('a rede cai e volta: a vista muda, e o que falhou pede-se outra vez', async () => {
  const m = montar();
  await falhar(m, 'obterRota', erroSemRede());
  await falhar(m, 'obterConfigMapa', erroSemRede());
  await responder(m, 'listarLojas', copia(LOJAS));
  const vistas = m.vistas.length;
  m.mudarRede(false);
  expect(m.vistas).toHaveLength(vistas + 1);
  expect(m.vista().semRede).toBe(true);
  expect(m.api.pedidos).toHaveLength(3);
  m.mudarRede(true);
  expect(m.vista().semRede).toBe(false);
  expect(nomes(m).slice(3)).toEqual(['obterRota', 'obterConfigMapa']);
  await responder(m, 'obterRota', copia(rotaDoServidor()));
  await falhar(m, 'obterSugestoes', erroSemRede());
  m.mudarRede(true);
  expect(nomes(m).slice(-1)).toEqual(['obterSugestoes']);
  // Cair a rede não pede nada.
  const total = m.api.pedidos.length;
  m.mudarRede(false);
  expect(m.api.pedidos).toHaveLength(total);
});

test('tentar de novo antes de iniciar não pede nada', () => {
  const m = montar({ iniciar: false });
  m.planeador.tentarDeNovo();
  expect(m.api.pedidos).toEqual([]);
});

test('sem a rede (o objeto), conta como ligado', async () => {
  const api = apiFalsa();
  const planeador = criarPlaneador({ api, data: DIA, base: '/crm' });
  planeador.iniciar();
  expect(planeador.vista.semRede).toBe(false);
  expect(api.pedidos.map((p) => p.nome)).toEqual(['obterRota', 'obterConfigMapa', 'listarLojas']);
});

// --- Recarregar, voltar e destruir ---------------------------------------------------------------

test('recarregar: volta a pedir a rota (um pedido de cada vez), mostra a nova e volta a pedir as sugestões', async () => {
  const m = await comSugestoes();
  const antes = m.api.pedidos.length;
  m.planeador.recarregar();
  expect(nomes(m).slice(antes)).toEqual(['obterRota']);
  expect(m.vista().recarga).toEqual({ aRecarregar: true, erro: null });
  m.planeador.recarregar();
  expect(m.api.pedidos).toHaveLength(antes + 1);
  await responder(m, 'obterRota', copia(rotaDoServidor({ estado: 'planeada', estado_efetivo: 'planeada' })));
  expect(m.vista().rotuloEstado).toBe('Planeada');
  expect(m.vista().recarga).toEqual({ aRecarregar: false, erro: null });
  expect(nomes(m).slice(antes)).toEqual(['obterRota', 'obterSugestoes']);
});

test('recarregar falha: a rota que se tinha fica, com o erro; o seguinte limpa-o', async () => {
  const m = await carregado();
  m.planeador.recarregar();
  await falhar(m, 'obterRota', erroSemRede());
  expect(m.vista()).toMatchObject({ estado: 'rota', rotuloEstado: 'Rascunho', recarga: { aRecarregar: false, erro: MENSAGEM_SEM_REDE } });
  m.planeador.recarregar();
  expect(m.vista().recarga).toEqual({ aRecarregar: true, erro: null });
  await responder(m, 'obterRota', 'estragada');
  expect(m.vista().recarga).toEqual({ aRecarregar: false, erro: MENSAGEM_ERRO_INESPERADO });
  expect(m.vista().rotuloEstado).toBe('Rascunho');
});

test('recarregar uma rota que passou a só de leitura: sem sugestões nem ações', async () => {
  const m = await comSugestoes();
  m.planeador.recarregar();
  await responder(m, 'obterRota', copia(rotaDoServidor({ editavel: false })));
  expect(m.vista()).toMatchObject({ somenteLeitura: true, sugestoes: null, acoes: null });
  expect(pedidos(m, 'obterSugestoes')).toHaveLength(1);
});

test('recarregar antes de haver rota não faz nada', async () => {
  const m = montar();
  m.planeador.recarregar();
  expect(pedidos(m, 'obterRota')).toHaveLength(1);
  await falhar(m, 'obterRota', erroSemRede());
  m.planeador.recarregar();
  expect(pedidos(m, 'obterRota')).toHaveLength(1);
});

test('voltarAsRotas: a página das rotas da mesma casa', async () => {
  const m = montar({ base: '/admin/crm', data: 'abc' });
  expect(m.vista().caminhoRotas).toBe('/admin/crm/rotas');
  m.planeador.voltarAsRotas();
  expect(m.navegacoes).toEqual([{ caminho: '/admin/crm/rotas', opcoes: undefined }]);
});

test('destruir: as respostas e a rede que chegarem depois não fazem nada', async () => {
  const m = montar();
  await responder(m, 'obterConfigMapa', copia(CONFIG));
  const vista = m.vista();
  const vistas = m.vistas.length;
  m.planeador.destruir();
  await responder(m, 'obterRota', copia(rotaDoServidor()));
  await responder(m, 'listarLojas', copia(LOJAS));
  m.mudarRede(false);
  m.mudarRede(true);
  m.planeador.tentarDeNovo();
  m.planeador.recarregar();
  m.planeador.iniciar();
  expect(m.vista()).toBe(vista);
  expect(m.vistas).toHaveLength(vistas);
  expect(m.api.pedidos).toHaveLength(3);
  expect(pedidos(m, 'obterSugestoes')).toEqual([]);
  // Destruir duas vezes não rebenta.
  m.planeador.destruir();
});

test('destruir: nenhuma resposta conta depois, a dar certo ou a falhar', async () => {
  const certo = montar();
  certo.planeador.destruir();
  const vistaCerta = certo.vista();
  await responder(certo, 'obterConfigMapa', copia(CONFIG));
  await responder(certo, 'listarLojas', copia(LOJAS));
  await responder(certo, 'obterRota', copia(rotaDoServidor()));
  expect(certo.vista()).toBe(vistaCerta);
  expect(certo.vistas).toHaveLength(1);
  expect(pedidos(certo, 'obterSugestoes')).toEqual([]);

  const errado = montar();
  errado.planeador.destruir();
  await falhar(errado, 'obterConfigMapa', erroSemRede());
  await falhar(errado, 'listarLojas', erroSemRede());
  await falhar(errado, 'obterRota', erroSemRede());
  expect(errado.vistas).toHaveLength(1);

  const sugerido = await carregado();
  const vistas = sugerido.vistas.length;
  sugerido.planeador.destruir();
  await responder(sugerido, 'obterSugestoes', copia(sugestoesDoServidor()));
  expect(sugerido.vistas).toHaveLength(vistas);
  expect(sugerido.vista().sugestoes.estado).toBe('a_carregar');
});

test('destruir antes de iniciar: iniciar já não pede nada', () => {
  const m = montar({ iniciar: false });
  m.planeador.destruir();
  m.planeador.iniciar();
  expect(m.api.pedidos).toEqual([]);
  expect(m.vistas).toEqual([]);
});

test('destruir com as falhas e as sugestões em curso: nada muda depois', async () => {
  const m = await carregado();
  const vistas = m.vistas.length;
  m.planeador.destruir();
  await falhar(m, 'obterSugestoes', erroServidor());
  m.planeador.recarregar();
  expect(m.vistas).toHaveLength(vistas);

  const n = montar();
  await falhar(n, 'obterRota', erroSemRede());
  await falhar(n, 'obterConfigMapa', erroSemRede());
  await falhar(n, 'listarLojas', erroSemRede());
  const vistasN = n.vistas.length;
  n.planeador.destruir();
  n.planeador.tentarDeNovo();
  n.mudarRede(true);
  expect(n.api.pedidos).toHaveLength(3);
  expect(n.vistas).toHaveLength(vistasN);

  const o = await carregado();
  o.planeador.recarregar();
  o.planeador.destruir();
  const vistasO = o.vistas.length;
  await responder(o, 'obterRota', copia(rotaDoServidor({ estado: 'planeada', estado_efetivo: 'planeada' })));
  expect(o.vistas).toHaveLength(vistasO);
  expect(o.vista().rotuloEstado).toBe('Rascunho');
  expect(pedidos(o, 'obterSugestoes')).toHaveLength(1);
});

// =================================================================================================
// T3.32 — as ações, as horas automáticas, calcular, guardar e os conflitos
// =================================================================================================

// A rota do exemplo com as horas velhas (o cálculo já não é o da rota gravada).
const CALCULO = rotaDoServidor().calculo;
const comHorasVelhas = (extra = {}) => rotaDoServidor({ calculo: { ...CALCULO, atual: false }, ...extra });
// A resposta de uma escrita: a rota do servidor com esta versão.
const resposta = (versao, extra = {}) => copia(rotaDoServidor({ versao, ...extra }));
const respostaVelha = (versao, extra = {}) => copia(comHorasVelhas({ versao, ...extra }));
// O exemplo sem a D (a que não cabe): o "Guardar rota" não pergunta nada.
const semNaoCabe = (extra = {}) => rotaDoServidor({ paragens: rotaDoServidor().paragens.filter((p) => p.id !== 'D'), ...extra });

const erroDe = (codigo, mensagem, estado = 409, extra = {}) => new ErroCrm({ codigo, mensagem, estado, ...extra });
const erroConflito = () => erroDe('conflito', 'Alterado por outra pessoa — recarregar');
const erroEmCurso = () => erroDe('rota_em_curso', TEXTO_EM_CURSO_LEITURA);
const erroFechada = () => erroDe('rota_fechada', 'Este dia já passou — a rota só se pode ver.');
const MENSAGEM_LIMITE = 'Cálculo automático indisponível por agora (limite de pedidos) — espere um minuto ou ordene à mão';
const erroCalculo = (tipo = 'limite', mensagem = MENSAGEM_LIMITE) => erroDe('calculo_indisponivel', mensagem, 503, { extra: { tipo } });
const erroValidacao = (campos) => erroDe('validacao', 'Verifique os campos assinalados.', 422, { campos });

const idsDaRota = (m) => m.vista().seccoes.rota.map((l) => l.id);
const numerosDaRota = (m) => m.vista().seccoes.rota.map((l) => [l.id, l.numero]);
const escritas = (m) => m.api.pedidos.filter((p) => ['adicionarParagem', 'alterarRota', 'recalcularHoras', 'otimizarRota'].includes(p.nome));
const corpo = (m, n = -1) => pedidos(m, 'alterarRota').at(n).argumentos;

test('os textos das ações (T3.32)', () => {
  expect({
    TEXTO_A_CALCULAR, TEXTO_A_RECALCULAR, TEXTO_A_ADICIONAR, TEXTO_ADICIONADA, TEXTO_RETIRADA, TEXTO_GUARDADA,
    TEXTO_CONFLITO, TEXTO_FALTA_CONFLITO, TEXTOS_ESCOLHER_PONTO, ESPERA_HORAS_MS, DEFINICOES_DO_DIA,
  }).toEqual({
    TEXTO_A_CALCULAR: 'A calcular…',
    TEXTO_A_RECALCULAR: 'A recalcular…',
    TEXTO_A_ADICIONAR: 'A adicionar…',
    // Os avisos do plano (T3.32), tal e qual.
    TEXTO_ADICIONADA: 'Adicionada',
    TEXTO_RETIRADA: 'Retirada',
    TEXTO_GUARDADA: 'Rota guardada como planeada',
    TEXTO_CONFLITO: 'Alterado por outra pessoa — recarregar',
    TEXTO_FALTA_CONFLITO: 'Recarregue a rota para ver o que a outra pessoa mudou.',
    TEXTOS_ESCOLHER_PONTO: { inicio: 'Toque no mapa no ponto de início', fim: 'Toque no mapa no ponto de fim' },
    // A correção "T3.32": ~1,5 s sem alterações antes do recálculo automático.
    ESPERA_HORAS_MS: 1500,
    DEFINICOES_DO_DIA: ['hora_saida', 'hora_regresso_limite', 'inicio', 'fim', 'evitar_portagens'],
  });
  // A faixa do conflito é a da ficha da loja (e a mensagem do 409 do servidor).
  expect(TEXTO_CONFLITO).toBe(TEXTO_CONFLITO_DA_FICHA);
  expect(Object.isFrozen(TEXTOS_ESCOLHER_PONTO)).toBe(true);
  expect(Object.isFrozen(DEFINICOES_DO_DIA)).toBe(true);
});

describe('acoesDaRota: o conflito e os cálculos em curso (T3.32)', () => {
  test('o conflito desliga tudo com "Recarregue a rota…", antes do sem rede', () => {
    const falta = 'Recarregue a rota para ver o que a outra pessoa mudou.';
    for (const online of [true, false]) {
      const acoes = acoesDaRota(rotaDoServidor(), { online, conflito: true });
      expect([acoes.calcular, acoes.recalcular, acoes.guardar].map((a) => [a.ativo, a.falta])).toEqual([[false, falta], [false, falta], [false, falta]]);
    }
    // O conflito é o `true` e nada mais.
    expect(acoesDaRota(rotaDoServidor(), { online: true, conflito: 1 }).calcular.ativo).toBe(true);
  });

  test('a calcular a melhor ordem: "A calcular…" desligado sem falta, e as horas esperam por ele', () => {
    const acoes = acoesDaRota(comHorasVelhas(), { online: true, aCalcular: true });
    expect(acoes.calcular).toEqual({ texto: 'A calcular…', ativo: false, falta: null });
    expect(acoes.recalcular).toEqual({ texto: 'Recalcular horas', ativo: false, falta: 'A calcular…' });
    expect(acoes.guardar).toEqual({ texto: 'Guardar rota', ativo: true, falta: null, pergunta: null });
    // Em curso ganha a qualquer outro motivo (sem rede, horas em dia).
    expect(acoesDaRota(rotaDoServidor(), { online: false, aCalcular: true }).calcular).toEqual({ texto: 'A calcular…', ativo: false, falta: null });
    expect(acoesDaRota(rotaDoServidor(), { online: true, aCalcular: true }).recalcular.falta).toBe('A calcular…');
  });

  test('a recalcular as horas: "A recalcular…" desligado sem falta; calcular continua', () => {
    const acoes = acoesDaRota(comHorasVelhas(), { online: true, aRecalcular: true });
    expect(acoes.recalcular).toEqual({ texto: 'A recalcular…', ativo: false, falta: null });
    expect(acoes.calcular).toEqual({ texto: 'Calcular melhor ordem', ativo: true, falta: null });
    expect(acoesDaRota(comHorasVelhas(), { online: false, aRecalcular: true }).recalcular).toEqual({ texto: 'A recalcular…', ativo: false, falta: null });
    // Os dois em curso.
    const ambos = acoesDaRota(comHorasVelhas(), { online: true, aRecalcular: true, aCalcular: true });
    expect([ambos.calcular.texto, ambos.recalcular.texto]).toEqual(['A calcular…', 'A recalcular…']);
    // O `true` e nada mais.
    expect(acoesDaRota(comHorasVelhas(), { online: true, aRecalcular: 'sim', aCalcular: 1 })).toMatchObject({
      calcular: { texto: 'Calcular melhor ordem', ativo: true }, recalcular: { texto: 'Recalcular horas', ativo: true },
    });
  });
});

// --- Arrastar, subir e descer (otimistas) ---------------------------------------------------------

test('mover: a ordem nova vai logo (otimista) e grava-se com a versão em vigor; a resposta manda', async () => {
  const m = await comSugestoes();
  m.planeador.mover(0, 2);
  expect(corpo(m)).toEqual([DIA, { ordem: ['C', 'E', 'A', 'D', 'B'], versao: 3 }]);
  // Logo, antes da resposta: os números, os pinos e as horas (já velhas).
  expect(numerosDaRota(m)).toEqual([['C', 1], ['E', 2], ['A', 3]]);
  expect(m.vista().mapa.paragens.filter((p) => p.numero !== null).map((p) => [p.id, p.numero])).toEqual([['C', 1], ['E', 2], ['A', 3]]);
  expect(m.vista().horas).toEqual({ atuais: false, texto: 'Horas antigas — Recalcular horas' });
  expect(m.vista().seccoes.rota.map((l) => [l.podeSubir, l.podeDescer])).toEqual([[false, true], [true, true], [true, false]]);
  // A resposta do servidor substitui a visão otimista.
  await responder(m, 'alterarRota', resposta(4, { estado: 'planeada', estado_efetivo: 'planeada' }));
  expect(m.vista().rotuloEstado).toBe('Planeada');
  expect(idsDaRota(m)).toEqual(['A', 'C', 'E']);
  // A seguinte sai com a versão nova.
  m.planeador.mover(2, 0);
  expect(corpo(m)).toEqual([DIA, { ordem: ['E', 'A', 'C', 'D', 'B'], versao: 4 }]);
  expect(m.avisos).toEqual([]);
});

test('mover: para o mesmo sítio, fora da lista ou sem índices não grava nada', async () => {
  const m = await carregado();
  m.planeador.mover(1, 1);
  m.planeador.mover(5, 0);
  m.planeador.mover(-1, 0);
  m.planeador.mover(0, 'x');
  m.planeador.mover();
  expect(escritas(m)).toEqual([]);
  // Para lá da ponta encosta à ponta (o `mover` do reordenar.js).
  m.planeador.mover(0, 99);
  expect(corpo(m)[1].ordem).toEqual(['C', 'E', 'A', 'D', 'B']);
});

test('subir e descer: uma posição na secção "rota"; nas pontas, ou fora dela, nada', async () => {
  const m = await carregado();
  m.planeador.subir('A');
  m.planeador.descer('E');
  m.planeador.subir('B');
  m.planeador.descer('D');
  m.planeador.subir('Z');
  expect(escritas(m)).toEqual([]);
  m.planeador.subir('C');
  expect(corpo(m)).toEqual([DIA, { ordem: ['C', 'A', 'E', 'D', 'B'], versao: 3 }]);
  expect(idsDaRota(m)).toEqual(['C', 'A', 'E']);
  await responder(m, 'alterarRota', resposta(4));
  // A resposta manda: a rota do servidor é A, C, E.
  m.planeador.descer('C');
  expect(corpo(m)).toEqual([DIA, { ordem: ['A', 'E', 'C', 'D', 'B'], versao: 4 }]);
});

test('um pedido de cada vez: as alterações seguidas juntam-se e saem com a versão da última resposta', async () => {
  const m = await carregado();
  m.planeador.mover(0, 2);
  m.planeador.retirar('C');
  m.planeador.mudarMotivo('A', 'entrega');
  expect(pedidos(m, 'alterarRota')).toHaveLength(1);
  // A visão otimista já tem as três.
  expect(numerosDaRota(m)).toEqual([['E', 1], ['A', 2]]);
  expect(m.vista().seccoes.rota[1].rotuloMotivo).toBe('Entrega');
  await responder(m, 'alterarRota', resposta(4));
  expect(corpo(m)).toEqual([DIA, { retirar: ['C'], paragens: { A: { motivo: 'entrega' } }, versao: 4 }]);
  expect(pedidos(m, 'alterarRota')).toHaveLength(2);
  // Enquanto a segunda não chega, ela continua por cima da primeira resposta.
  expect(idsDaRota(m)).toEqual(['A', 'E']);
  await responder(m, 'alterarRota', resposta(5));
  expect(m.avisos.map((a) => a.texto)).toEqual(['Retirada']);
  expect(idsDaRota(m)).toEqual(['A', 'C', 'E']);
});

// --- Retirar e as alterações de cada paragem ------------------------------------------------------

test('retirar: sai logo da lista e do mapa, e "Retirada" quando o servidor confirma', async () => {
  const m = await carregado();
  m.planeador.retirar('C');
  expect(corpo(m)).toEqual([DIA, { retirar: ['C'], versao: 3 }]);
  expect(numerosDaRota(m)).toEqual([['A', 1], ['E', 2]]);
  expect(m.vista().mapa.paragens.map((p) => p.id)).toEqual(['A', 'B', 'D', 'E']);
  expect(m.vista().mapa.lojasForaDaRota.map((l) => l.id)).toEqual(['loja-C', 'loja-X', 'loja-Y']);
  expect(m.vista().limite).toEqual({ cheia: false, texto: '5 de 48 paragens' });
  expect(m.avisos).toEqual([]);
  await responder(m, 'alterarRota', resposta(4, { paragens: rotaDoServidor().paragens.filter((p) => p.id !== 'C') }));
  expect(m.avisos).toEqual([{ texto: 'Retirada', opcoes: undefined }]);
  // Também as outras secções (a fechada e a da loja apagada); um id que não está na rota, nada.
  m.planeador.retirar('F');
  expect(corpo(m)).toEqual([DIA, { retirar: ['F'], versao: 4 }]);
  await responder(m, 'alterarRota', resposta(5, { paragens: rotaDoServidor().paragens.filter((p) => !['C', 'F'].includes(p.id)) }));
  m.planeador.retirar('C');
  m.planeador.retirar();
  expect(pedidos(m, 'alterarRota')).toHaveLength(2);
});

test('o motivo, o tempo, "Manter" e "Pôr na rota": uma paragem de cada vez, otimistas', async () => {
  const m = await carregado();
  m.planeador.mudarMotivo('A', 'acompanhamento');
  expect(corpo(m)).toEqual([DIA, { paragens: { A: { motivo: 'acompanhamento' } }, versao: 3 }]);
  expect(m.vista().seccoes.rota[0]).toMatchObject({ motivo: 'acompanhamento', rotuloMotivo: 'Acompanhamento' });
  await responder(m, 'alterarRota', resposta(4));

  // O tempo em texto (o campo do formulário) vai como inteiro; o resto vai como veio (o servidor diz o 422).
  m.planeador.mudarTempo('C', '25');
  expect(corpo(m)).toEqual([DIA, { paragens: { C: { tempo_servico_min: 25 } }, versao: 4 }]);
  expect(m.vista().seccoes.rota[1].tempo).toBe(25);
  await responder(m, 'alterarRota', resposta(5));
  m.planeador.mudarTempo('C', 30);
  expect(corpo(m)[1]).toEqual({ paragens: { C: { tempo_servico_min: 30 } }, versao: 5 });
  await responder(m, 'alterarRota', resposta(6));
  m.planeador.mudarTempo('C', '2,5');
  expect(corpo(m)[1]).toEqual({ paragens: { C: { tempo_servico_min: '2,5' } }, versao: 6 });
  await responder(m, 'alterarRota', resposta(7));

  // "Manter" a fechada neste dia: entra logo na secção "rota".
  m.planeador.manter('B');
  expect(corpo(m)[1]).toEqual({ paragens: { B: { manter_fechada: true } }, versao: 7 });
  expect(idsDaRota(m)).toEqual(['A', 'B', 'C', 'E']);
  await responder(m, 'alterarRota', resposta(8));
  // "Pôr na rota" a que não cabe.
  m.planeador.porNaRota('D');
  expect(corpo(m)[1]).toEqual({ paragens: { D: { nao_cabe: false } }, versao: 8 });
  expect(idsDaRota(m)).toEqual(['A', 'C', 'D', 'E']);
  await responder(m, 'alterarRota', resposta(9));

  // Uma paragem que não está na rota: nada.
  for (const acao of ['mudarMotivo', 'mudarTempo', 'manter', 'porNaRota']) m.planeador[acao]('Z', 'entrega');
  expect(pedidos(m, 'alterarRota')).toHaveLength(6);
  expect(m.avisos).toEqual([]);
});

// --- As definições do dia ---------------------------------------------------------------------------

test('mudarDefinicao: as horas e as portagens; o mesmo valor ou outra chave não gravam nada', async () => {
  const m = await carregado();
  m.planeador.mudarDefinicao('hora_saida', '08:00');
  m.planeador.mudarDefinicao('evitar_portagens', false);
  m.planeador.mudarDefinicao('cor', 'roxo');
  m.planeador.mudarDefinicao('hora_saida', undefined);
  m.planeador.mudarDefinicao('versao', 9);
  expect(escritas(m)).toEqual([]);
  m.planeador.mudarDefinicao('hora_saida', '07:30');
  expect(corpo(m)).toEqual([DIA, { hora_saida: '07:30', versao: 3 }]);
  expect(m.vista().definicoes.hora_saida).toBe('07:30');
  m.planeador.mudarDefinicao('evitar_portagens', true);
  m.planeador.mudarDefinicao('hora_regresso_limite', '18:30');
  await responder(m, 'alterarRota', resposta(4, { hora_saida: '07:30' }));
  expect(corpo(m)).toEqual([DIA, { evitar_portagens: true, hora_regresso_limite: '18:30', versao: 4 }]);
  expect(m.vista().definicoes).toMatchObject({ hora_saida: '07:30', evitar_portagens: true, hora_regresso_limite: '18:30' });
});

test('o início e o fim: "Ponto no mapa" com a faixa e o toque, "Fábrica" e "Cancelar"', async () => {
  const m = await carregado();
  m.planeador.escolherPonto('meio');
  expect(m.vista().escolherPonto).toBeNull();
  m.planeador.escolherPonto('inicio');
  expect(m.vista().escolherPonto).toBe('inicio');
  // Um toque sem coordenadas não serve; continua à espera.
  m.planeador.tocarNoMapa({ lat: 'x', lng: -9 });
  m.planeador.tocarNoMapa(null);
  expect(escritas(m)).toEqual([]);
  expect(m.vista().escolherPonto).toBe('inicio');
  m.planeador.tocarNoMapa({ lat: 38.6, lng: -9.0, outra: 'coisa' });
  expect(corpo(m)).toEqual([DIA, { inicio: { lat: 38.6, lng: -9.0 }, versao: 3 }]);
  expect(m.vista().escolherPonto).toBeNull();
  expect(m.vista().definicoes.inicio).toEqual({ lat: 38.6, lng: -9.0, fabrica: false, texto: 'Ponto no mapa' });
  expect(m.vista().mapa.inicio).toEqual({ lat: 38.6, lng: -9.0, fabrica: false });
  await responder(m, 'alterarRota', resposta(4, { inicio: { lat: 38.6, lng: -9.0, fabrica: false } }));

  // Outro toque, já sem a faixa: nada.
  m.planeador.tocarNoMapa({ lat: 38.5, lng: -9.1 });
  expect(pedidos(m, 'alterarRota')).toHaveLength(1);

  // "Fábrica" volta à fábrica (o centro do GET /config), e fecha a faixa dessa ponta.
  m.planeador.escolherPonto('inicio');
  m.planeador.usarFabrica('inicio');
  expect(m.vista().escolherPonto).toBeNull();
  expect(corpo(m)).toEqual([DIA, { inicio: null, versao: 4 }]);
  expect(m.vista().definicoes.inicio).toEqual({ lat: 38.75, lng: -9.2, fabrica: true, texto: 'Fábrica' });
  await responder(m, 'alterarRota', resposta(5));
  // O fim já é a fábrica: nada a gravar (e a faixa do fim fecha-se na mesma).
  m.planeador.escolherPonto('fim');
  expect(m.vista().escolherPonto).toBe('fim');
  m.planeador.usarFabrica('fim');
  expect(m.vista().escolherPonto).toBeNull();
  m.planeador.usarFabrica('meio');
  expect(pedidos(m, 'alterarRota')).toHaveLength(2);
  // A faixa de uma ponta não fecha com a fábrica da outra; "Cancelar" fecha-a.
  m.planeador.escolherPonto('fim');
  m.planeador.usarFabrica('inicio');
  expect(m.vista().escolherPonto).toBe('fim');
  m.planeador.escolherPonto(null);
  expect(m.vista().escolherPonto).toBeNull();
  // O fim num ponto do mapa.
  m.planeador.escolherPonto('fim');
  m.planeador.tocarNoMapa({ lat: 38.9, lng: -9.3 });
  expect(corpo(m)[1]).toEqual({ fim: { lat: 38.9, lng: -9.3 }, versao: 5 });
});

test('numa rota virtual, as definições do dia não chamam a API (correção "T3.20 / T3.31 / T3.39")', async () => {
  const m = await carregado({ rota: rotaVirtual() });
  m.planeador.mudarDefinicao('hora_saida', '07:30');
  m.planeador.mudarDefinicao('evitar_portagens', true);
  m.planeador.escolherPonto('inicio');
  expect(m.vista().escolherPonto).toBeNull();
  m.planeador.tocarNoMapa({ lat: 38.6, lng: -9.0 });
  m.planeador.usarFabrica('fim');
  m.planeador.mudarDefinicao('inicio', { lat: 38.6, lng: -9.0 });
  expect(escritas(m)).toEqual([]);
  expect(m.vista().definicoes).toMatchObject({ hora_saida: '08:00', evitar_portagens: false, ativas: false });
});

// --- Adicionar (não é otimista) ---------------------------------------------------------------------

test('adicionar: "A adicionar…" sem mudar a lista, e "Adicionada" com a rota do servidor', async () => {
  const m = await comSugestoes();
  expect(m.vista().podeAdicionar).toBe(true);
  expect(m.vista().sugestoes.grupos[0].lojas[0]).toMatchObject({ id: 'loja-X', aAdicionar: false });
  m.planeador.adicionar('loja-X');
  expect(ultimo(m, 'adicionarParagem').argumentos).toEqual([DIA, { loja_id: 'loja-X', versao: 3 }]);
  expect(m.vista().sugestoes.grupos[0].lojas[0]).toMatchObject({ id: 'loja-X', aAdicionar: true });
  expect(m.vista().sugestoes.grupos[1].lojas[0]).toMatchObject({ id: 'loja-Y', aAdicionar: false });
  // Não é otimista: a lista, o mapa e o limite ficam até à resposta.
  expect(idsDaRota(m)).toEqual(['A', 'C', 'E']);
  expect(m.vista().limite.texto).toBe('6 de 48 paragens');
  expect(m.vista().mapa.lojasForaDaRota.map((l) => l.id)).toEqual(['loja-X', 'loja-Y']);
  // A mesma loja outra vez enquanto se adiciona: nada.
  m.planeador.adicionar('loja-X');
  expect(pedidos(m, 'adicionarParagem')).toHaveLength(1);
  expect(pedidos(m, 'obterSugestoes')).toHaveLength(1);

  const comX = [...rotaDoServidor().paragens, paragem('X', 6, { numero: 4 })];
  await responder(m, 'adicionarParagem', resposta(4, { paragens: comX }));
  expect(m.avisos).toEqual([{ texto: 'Adicionada', opcoes: undefined }]);
  expect(idsDaRota(m)).toEqual(['A', 'C', 'E', 'X']);
  expect(m.vista().limite.texto).toBe('7 de 48 paragens');
  expect(m.vista().mapa.lojasForaDaRota.map((l) => l.id)).toEqual(['loja-Y']);
  // A lista antiga sem a X (já está na rota), e as sugestões pedem-se outra vez.
  expect(m.vista().sugestoes.grupos.map((g) => g.lojas.map((l) => l.id))).toEqual([['loja-Y']]);
  expect(pedidos(m, 'obterSugestoes')).toHaveLength(2);

  // Com o motivo escolhido; uma loja que já está na rota (ou sem id) não vai.
  m.planeador.adicionar('loja-Y', 'entrega');
  expect(ultimo(m, 'adicionarParagem').argumentos).toEqual([DIA, { loja_id: 'loja-Y', motivo: 'entrega', versao: 4 }]);
  await responder(m, 'adicionarParagem', resposta(5, { paragens: [...comX, paragem('Y', 7, { numero: 5 })] }));
  // Com a fila parada, para ver que nem entram na fila.
  m.planeador.adicionar('loja-A');
  m.planeador.adicionar('');
  m.planeador.adicionar();
  m.planeador.adicionar(7);
  expect(pedidos(m, 'adicionarParagem')).toHaveLength(2);
});

test('adicionar falha: a mensagem do servidor e o botão volta (ja_na_rota, rota_cheia, sem rede)', async () => {
  const m = await comSugestoes();
  m.planeador.adicionar('loja-X');
  await falhar(m, 'adicionarParagem', erroDe('ja_na_rota', 'Esta loja já está na rota deste dia.'));
  expect(m.vista().alerta).toEqual({ mensagem: 'Esta loja já está na rota deste dia.' });
  expect(m.vista().sugestoes.grupos[0].lojas[0].aAdicionar).toBe(false);
  expect(m.avisos).toEqual([]);
  // Não pára a fila: a seguinte sai com a mesma versão, e limpa a mensagem.
  m.planeador.adicionar('loja-Y');
  expect(m.vista().alerta).toBeNull();
  expect(ultimo(m, 'adicionarParagem').argumentos).toEqual([DIA, { loja_id: 'loja-Y', versao: 3 }]);
  await falhar(m, 'adicionarParagem', erroDe('rota_cheia', 'Uma rota tem no máximo 48 paragens.'));
  expect(m.vista().alerta).toEqual({ mensagem: 'Uma rota tem no máximo 48 paragens.' });
  m.planeador.adicionar('loja-X');
  await falhar(m, 'adicionarParagem', erroSemRede());
  expect(m.vista().alerta).toEqual({ mensagem: MENSAGEM_SEM_REDE });
  // Nada mudou: as sugestões não se voltam a pedir.
  expect(pedidos(m, 'obterSugestoes')).toHaveLength(1);
});

test('adicionar numa rota virtual: sai com `versao: null` e a rota nasce (versão 1)', async () => {
  const m = await carregado({ rota: rotaVirtual() });
  expect(m.vista().sugestoes.estado).toBe('sem_paragens');
  m.planeador.escolherPonto('inicio');
  m.planeador.adicionar('loja-X', 'amostra');
  expect(ultimo(m, 'adicionarParagem').argumentos).toEqual([DIA, { loja_id: 'loja-X', motivo: 'amostra', versao: null }]);
  await responder(m, 'adicionarParagem', resposta(1, { paragens: [paragem('X', 0, { numero: 1 })], calculo: null, blocos_google: [] }));
  expect(m.vista().definicoes.ativas).toBe(true);
  expect(m.vista().escolherPonto).toBeNull();
  expect(pedidos(m, 'obterSugestoes')).toHaveLength(1);
  m.planeador.mudarDefinicao('hora_saida', '07:30');
  expect(corpo(m)).toEqual([DIA, { hora_saida: '07:30', versao: 1 }]);
});

test('com a rota cheia (48) não se adiciona', async () => {
  const cheias = Array.from({ length: 48 }, (_, i) => paragem(`P${i}`, i, { numero: i + 1 }));
  const m = await carregado({ rota: rotaDoServidor({ paragens: cheias }) });
  expect(m.vista().podeAdicionar).toBe(false);
  m.planeador.adicionar('loja-X');
  m.planeador.escolherLoja(LOJAS[5]);
  expect(m.vista().lojaEscolhida).toMatchObject({ id: 'loja-X', ativo: false });
  expect(escritas(m)).toEqual([]);
});

// --- Um toque numa loja esbatida (o cartão pequeno) ------------------------------------------------

test('escolherLoja: o cartão "Adicionar à rota" com o motivo da fase; fecha ao adicionar, ao tocar no mapa ou com null', async () => {
  const m = await carregado();
  m.planeador.escolherLoja(LOJAS[5]);
  expect(m.vista().lojaEscolhida).toEqual({
    id: 'loja-X', nome: 'Loja loja-X', fase: 'potencial', motivo: 'angariacao', rotuloMotivo: 'Angariação', aAdicionar: false, ativo: true,
  });
  m.planeador.adicionar('loja-X', 'angariacao');
  expect(m.vista().lojaEscolhida).toMatchObject({ aAdicionar: true, ativo: false });
  await responder(m, 'adicionarParagem', resposta(4, { paragens: [...rotaDoServidor().paragens, paragem('X', 6, { numero: 4 })] }));
  expect(m.vista().lojaEscolhida).toBeNull();

  // Outra loja; a contactada pré-escolhe "Amostra".
  m.planeador.escolherLoja({ id: 'loja-Y', nome: 'Café Y', fase: 'contactada' });
  expect(m.vista().lojaEscolhida).toMatchObject({ id: 'loja-Y', nome: 'Café Y', motivo: 'amostra', rotuloMotivo: 'Amostra' });
  m.planeador.tocarNoMapa({ lat: 38.7, lng: -9.1 });
  expect(m.vista().lojaEscolhida).toBeNull();
  expect(pedidos(m, 'alterarRota')).toEqual([]);
  m.planeador.escolherLoja({ id: 'loja-Y', nome: 'Café Y', fase: 'contactada' });
  m.planeador.escolherLoja(null);
  expect(m.vista().lojaEscolhida).toBeNull();
  // Escolher um ponto fecha o cartão.
  m.planeador.escolherLoja({ id: 'loja-Y', nome: 'Café Y', fase: 'contactada' });
  m.planeador.escolherPonto('inicio');
  expect(m.vista().lojaEscolhida).toBeNull();
  m.planeador.escolherPonto(null);

  // Escolher uma loja fecha a faixa do ponto; uma loja da rota não troca o cartão aberto.
  m.planeador.escolherPonto('inicio');
  m.planeador.escolherLoja({ id: 'loja-Y', nome: 'Café Y', fase: 'contactada' });
  expect(m.vista().escolherPonto).toBeNull();
  m.planeador.escolherLoja(LOJAS[0]);
  expect(m.vista().lojaEscolhida).toMatchObject({ id: 'loja-Y' });
  m.planeador.escolherLoja(null);

  // Uma loja que já está na rota, ou que não é uma loja: nada. Sem nome nem fase conhecida: "Angariação".
  m.planeador.escolherLoja(LOJAS[0]);
  m.planeador.escolherLoja({ nome: 'Sem id' });
  m.planeador.escolherLoja({ id: '' });
  m.planeador.escolherLoja('loja-Y');
  expect(m.vista().lojaEscolhida).toBeNull();
  m.planeador.escolherLoja({ id: 'loja-Z', nome: 3, fase: 'outra' });
  expect(m.vista().lojaEscolhida).toMatchObject({ id: 'loja-Z', nome: '', fase: null, motivo: 'angariacao' });
});

test('escolherLoja: sem rede o cartão mostra-se desligado; só de leitura não há cartão', async () => {
  const m = await carregado({ online: false });
  m.planeador.escolherLoja(LOJAS[5]);
  expect(m.vista().lojaEscolhida).toMatchObject({ id: 'loja-X', ativo: false });
  expect(m.vista().podeAdicionar).toBe(false);
  const n = await carregado({ rota: rotaDoServidor({ editavel: false }) });
  n.planeador.escolherLoja(LOJAS[5]);
  expect(n.vista().lojaEscolhida).toBeNull();
});

// --- Calcular melhor ordem e Recalcular horas -------------------------------------------------------

test('calcularMelhorOrdem: "A calcular…" até à resposta, que traz a ordem e as horas', async () => {
  const m = await comSugestoes({ rota: comHorasVelhas() });
  m.relogio.disparar();
  await responder(m, 'recalcularHoras', resposta(3));
  m.planeador.calcularMelhorOrdem();
  expect(ultimo(m, 'otimizarRota').argumentos).toEqual([DIA, 3]);
  expect(m.vista().calculo).toEqual({ aCalcular: true, mensagem: null });
  expect(m.vista().acoes.calcular).toEqual({ texto: 'A calcular…', ativo: false, falta: null });
  expect(m.vista().acoes.recalcular).toMatchObject({ ativo: false, falta: 'A calcular…' });
  // Um segundo toque não pede outra.
  m.planeador.calcularMelhorOrdem();
  expect(pedidos(m, 'otimizarRota')).toHaveLength(1);
  const sugestoesAntes = pedidos(m, 'obterSugestoes').length;
  await responder(m, 'otimizarRota', resposta(4, { estado: 'planeada', estado_efetivo: 'planeada' }));
  expect(m.vista().calculo).toEqual({ aCalcular: false, mensagem: null });
  expect(m.vista().rotuloEstado).toBe('Planeada');
  expect(pedidos(m, 'obterSugestoes')).toHaveLength(sugestoesAntes + 1);
  expect(m.avisos).toEqual([]);
});

test('calcularMelhorOrdem com as horas velhas: "a recalcular" enquanto corre', async () => {
  const m = await carregado({ rota: comHorasVelhas() });
  m.planeador.calcularMelhorOrdem();
  expect(m.vista().horas).toEqual({ atuais: false, texto: 'a recalcular' });
  // A espera do recálculo automático cancela-se: a otimização já traz as horas.
  expect(m.relogio.esperas).toEqual([]);
  await responder(m, 'otimizarRota', resposta(4));
  expect(m.vista().horas).toEqual({ atuais: true, texto: null });
  expect(m.relogio.esperas).toEqual([]);
});

test('calcularMelhorOrdem falha (503): a mensagem do servidor, nada muda e não recalcula sozinho', async () => {
  const m = await carregado({ rota: comHorasVelhas() });
  m.planeador.calcularMelhorOrdem();
  await falhar(m, 'otimizarRota', erroCalculo('ponto_sem_estrada', 'A paragem 2 não fica perto de uma estrada — corrija a localização da loja'));
  expect(m.vista().calculo).toEqual({ aCalcular: false, mensagem: 'A paragem 2 não fica perto de uma estrada — corrija a localização da loja' });
  expect(m.vista().horas.texto).toBe('Horas antigas — Recalcular horas');
  expect(idsDaRota(m)).toEqual(['A', 'C', 'E']);
  expect(m.relogio.esperas).toEqual([]);
  expect(m.vista().alerta).toBeNull();
  // Tentar outra vez (o botão) limpa a mensagem.
  m.planeador.calcularMelhorOrdem();
  expect(m.vista().calculo).toEqual({ aCalcular: true, mensagem: null });
});

test('calcularMelhorOrdem e recalcularHoras desligados não pedem nada (sem chave, horas em dia, sem paragens)', async () => {
  const semChave = await carregado({ rota: comHorasVelhas({ calculo_disponivel: false }) });
  semChave.planeador.calcularMelhorOrdem();
  semChave.planeador.recalcularHoras();
  expect(escritas(semChave)).toEqual([]);
  expect(semChave.vista().acoes.calcular.falta).toBe('Cálculo automático indisponível — ordene à mão');
  const emDia = await carregado();
  emDia.planeador.recalcularHoras();
  expect(escritas(emDia)).toEqual([]);
  const virtual = await carregado({ rota: rotaVirtual() });
  virtual.planeador.calcularMelhorOrdem();
  virtual.planeador.recalcularHoras();
  virtual.planeador.guardar();
  expect(escritas(virtual)).toEqual([]);
});

test('recalcularHoras (o botão): logo, sem esperar, e "A recalcular…"', async () => {
  const m = await carregado({ rota: comHorasVelhas() });
  expect(m.relogio.esperas).toEqual([1500]);
  m.planeador.recalcularHoras();
  expect(m.relogio.esperas).toEqual([]);
  expect(ultimo(m, 'recalcularHoras').argumentos).toEqual([DIA, 3]);
  expect(m.vista().acoes.recalcular).toEqual({ texto: 'A recalcular…', ativo: false, falta: null });
  expect(m.vista().horas).toEqual({ atuais: false, texto: 'a recalcular' });
  m.planeador.recalcularHoras();
  expect(pedidos(m, 'recalcularHoras')).toHaveLength(1);
  await responder(m, 'recalcularHoras', resposta(3, { calculo: { ...CALCULO, calculado_em: '2026-10-10T08:00:00.000000+00:00' } }));
  expect(m.vista().horas).toEqual({ atuais: true, texto: null });
  expect(m.vista().acoes.recalcular).toMatchObject({ ativo: false, falta: 'As horas estão em dia.' });
});

// --- Guardar rota -----------------------------------------------------------------------------------

test('guardar: passa a planeada (otimista) e "Rota guardada como planeada"', async () => {
  const m = await carregado({ rota: semNaoCabe() });
  m.planeador.guardar();
  expect(corpo(m)).toEqual([DIA, { estado: 'planeada', versao: 3 }]);
  expect(m.vista().rotuloEstado).toBe('Planeada');
  expect(m.vista().acoes.guardar).toMatchObject({ ativo: false, falta: 'A rota já está guardada como planeada.' });
  m.planeador.guardar();
  expect(pedidos(m, 'alterarRota')).toHaveLength(1);
  await responder(m, 'alterarRota', copia(semNaoCabe({ versao: 4, estado: 'planeada', estado_efetivo: 'planeada' })));
  expect(m.avisos).toEqual([{ texto: 'Rota guardada como planeada', opcoes: undefined }]);
  m.planeador.guardar();
  m.planeador.responderGuardar(true);
  expect(pedidos(m, 'alterarRota')).toHaveLength(1);
});

test('guardar com paragens que não cabem: a pergunta, e só grava com o "sim"', async () => {
  const m = await carregado();
  m.planeador.responderGuardar(true);
  expect(escritas(m)).toEqual([]);
  m.planeador.guardar();
  expect(escritas(m)).toEqual([]);
  expect(m.vista().acoes.guardar).toEqual({ texto: 'Guardar rota', ativo: true, falta: null, pergunta: '1 paragem não cabe — guardar mesmo assim?' });
  m.planeador.responderGuardar(false);
  expect(m.vista().acoes.guardar.pergunta).toBeNull();
  expect(escritas(m)).toEqual([]);
  m.planeador.guardar();
  m.planeador.responderGuardar(true);
  expect(m.vista().acoes.guardar.pergunta).toBeNull();
  expect(corpo(m)).toEqual([DIA, { estado: 'planeada', versao: 3 }]);
  // Responder outra vez já não grava.
  m.planeador.responderGuardar(true);
  expect(pedidos(m, 'alterarRota')).toHaveLength(1);
});

test('guardar: a pergunta aberta e a rede cai — o "sim" já não grava', async () => {
  const m = await carregado();
  m.planeador.guardar();
  m.mudarRede(false);
  m.planeador.responderGuardar(true);
  expect(escritas(m)).toEqual([]);
  expect(m.vista().acoes.guardar.pergunta).toBeNull();
});

// --- Os erros das alterações --------------------------------------------------------------------------

test('um 422 desfaz o otimista e mostra a mensagem do campo; a ação seguinte limpa-a', async () => {
  const m = await carregado();
  m.planeador.mudarDefinicao('hora_regresso_limite', '07:00');
  expect(m.vista().definicoes.hora_regresso_limite).toBe('07:00');
  await falhar(m, 'alterarRota', erroValidacao({ hora_regresso_limite: 'A hora limite de regresso tem de ser depois da hora de saída.' }));
  expect(m.vista().definicoes.hora_regresso_limite).toBe('19:00');
  expect(m.vista().alerta).toEqual({ mensagem: 'A hora limite de regresso tem de ser depois da hora de saída.' });
  expect(Object.isFrozen(m.vista().alerta)).toBe(true);
  // Não pára a fila: a seguinte sai com a mesma versão.
  m.planeador.retirar('C');
  expect(m.vista().alerta).toBeNull();
  expect(corpo(m)).toEqual([DIA, { retirar: ['C'], versao: 3 }]);
  // Sem campos (ou campos vazios), a mensagem geral do 422.
  await falhar(m, 'alterarRota', erroValidacao({ hora_saida: '' }));
  expect(m.vista().alerta).toEqual({ mensagem: 'Verifique os campos assinalados.' });
  expect(idsDaRota(m)).toEqual(['A', 'C', 'E']);
  m.planeador.retirar('C');
  await falhar(m, 'alterarRota', new ErroCrm({ codigo: 'validacao', mensagem: 'Verifique os campos assinalados.', estado: 422, campos: null }));
  expect(m.vista().alerta).toEqual({ mensagem: 'Verifique os campos assinalados.' });
  // Um erro sem mensagem: a geral.
  m.planeador.retirar('C');
  await falhar(m, 'alterarRota', new TypeError('x'));
  expect(m.vista().alerta).toEqual({ mensagem: MENSAGEM_ERRO_INESPERADO });
  expect(m.avisos).toEqual([]);
});

test('sem rede (o pedido falha): a paragem volta e a mensagem do sem rede', async () => {
  const m = await carregado();
  m.planeador.retirar('C');
  expect(idsDaRota(m)).toEqual(['A', 'E']);
  await falhar(m, 'alterarRota', erroSemRede());
  expect(idsDaRota(m)).toEqual(['A', 'C', 'E']);
  expect(m.vista().alerta).toEqual({ mensagem: MENSAGEM_SEM_REDE });
  expect(m.avisos).toEqual([]);
});

test('sem rede (o browser diz): as ações não pedem nada', async () => {
  const m = await carregado({ online: false });
  m.planeador.mover(0, 2);
  m.planeador.subir('C');
  m.planeador.retirar('C');
  m.planeador.mudarMotivo('A', 'entrega');
  m.planeador.manter('B');
  m.planeador.mudarDefinicao('hora_saida', '07:30');
  m.planeador.escolherPonto('inicio');
  m.planeador.tocarNoMapa({ lat: 38.6, lng: -9 });
  m.planeador.usarFabrica('inicio');
  m.planeador.adicionar('loja-X');
  m.planeador.calcularMelhorOrdem();
  m.planeador.recalcularHoras();
  m.planeador.guardar();
  expect(escritas(m)).toEqual([]);
  expect(m.vista().escolherPonto).toBeNull();
  // A rede volta: a faixa do ponto só abre agora.
  m.mudarRede(true);
  m.planeador.escolherPonto('inicio');
  expect(m.vista().escolherPonto).toBe('inicio');
  m.mudarRede(false);
  expect(m.vista().escolherPonto).toBeNull();
});

test('só de leitura: as ações não pedem nada', async () => {
  const m = await carregado({ rota: rotaDoServidor({ editavel: false, estado_efetivo: 'concluida', calculo: { ...CALCULO, atual: false } }) });
  m.planeador.mover(0, 2);
  m.planeador.retirar('C');
  m.planeador.mudarTempo('A', 20);
  m.planeador.porNaRota('D');
  m.planeador.mudarDefinicao('hora_saida', '07:30');
  m.planeador.adicionar('loja-X');
  m.planeador.calcularMelhorOrdem();
  m.planeador.recalcularHoras();
  m.planeador.guardar();
  expect(escritas(m)).toEqual([]);
  expect(m.relogio.esperas).toEqual([]);
});

// --- Os conflitos -----------------------------------------------------------------------------------

test('409 conflito: a faixa "Alterado por outra pessoa — recarregar", tudo desligado, e o otimista desfeito', async () => {
  const m = await comSugestoes();
  m.planeador.mover(0, 2);
  m.planeador.retirar('C');
  m.planeador.escolherPonto('inicio');
  m.planeador.guardar();
  m.planeador.escolherLoja(LOJAS[5]);
  expect(m.vista().acoes.guardar.pergunta).not.toBeNull();
  await falhar(m, 'alterarRota', erroConflito());
  const v = m.vista();
  expect(v.conflito).toEqual({ mensagem: 'Alterado por outra pessoa — recarregar', aRecarregar: false, erro: null });
  expect(Object.isFrozen(v.conflito)).toBe(true);
  // A rota do servidor, sem nenhuma das duas alterações (a que estava à espera também foi recusada).
  expect(idsDaRota(m)).toEqual(['A', 'C', 'E']);
  expect(pedidos(m, 'alterarRota')).toHaveLength(1);
  expect(v.alerta).toBeNull();
  expect(v.somenteLeitura).toBe(false);
  expect(v.acoes.calcular).toEqual({ texto: 'Calcular melhor ordem', ativo: false, falta: 'Recarregue a rota para ver o que a outra pessoa mudou.' });
  expect(v.acoes.guardar).toMatchObject({ ativo: false, falta: 'Recarregue a rota para ver o que a outra pessoa mudou.' });
  expect(v.definicoes.ativas).toBe(false);
  expect(v.podeAdicionar).toBe(false);
  expect(v.lojaEscolhida).toBeNull();
  expect(v.seccoes.rota.map((l) => [l.podeSubir, l.podeDescer])).toEqual([[false, false], [false, false], [false, false]]);
  expect(m.avisos).toEqual([]);
  // Nada grava enquanto não se recarrega.
  m.planeador.retirar('A');
  m.planeador.adicionar('loja-X');
  m.planeador.mudarDefinicao('hora_saida', '07:30');
  m.planeador.calcularMelhorOrdem();
  m.planeador.guardar();
  m.planeador.escolherLoja(LOJAS[5]);
  expect(m.vista().lojaEscolhida).toBeNull();
  expect(escritas(m)).toHaveLength(1);
  expect(m.relogio.esperas).toEqual([]);

  // "Recarregar": a rota de novo, e a fila volta a andar com a versão dela.
  m.planeador.recarregar();
  expect(m.vista().conflito).toEqual({ mensagem: 'Alterado por outra pessoa — recarregar', aRecarregar: true, erro: null });
  await responder(m, 'obterRota', resposta(7, { hora_saida: '09:00' }));
  expect(m.vista().conflito).toBeNull();
  expect(m.vista().definicoes).toMatchObject({ hora_saida: '09:00', ativas: true });
  // A faixa do ponto, a pergunta do "Guardar" e o cartão da loja não voltam.
  expect(m.vista()).toMatchObject({ escolherPonto: null, lojaEscolhida: null });
  expect(m.vista().acoes.guardar.pergunta).toBeNull();
  m.planeador.retirar('A');
  expect(corpo(m)).toEqual([DIA, { retirar: ['A'], versao: 7 }]);
});

test('409 conflito: o "Recarregar" que falha mostra o erro na faixa e a faixa fica', async () => {
  const m = await carregado();
  m.planeador.retirar('C');
  await falhar(m, 'alterarRota', erroConflito());
  m.planeador.recarregar();
  await falhar(m, 'obterRota', erroSemRede());
  expect(m.vista().conflito).toEqual({ mensagem: 'Alterado por outra pessoa — recarregar', aRecarregar: false, erro: MENSAGEM_SEM_REDE });
  m.planeador.retirar('A');
  expect(pedidos(m, 'alterarRota')).toHaveLength(1);
});

test('409 conflito noutros pedidos: o adicionar, o recalcular e o otimizar também param', async () => {
  for (const [acao, nome] of [['adicionar', 'adicionarParagem'], ['calcularMelhorOrdem', 'otimizarRota']]) {
    const m = await comSugestoes({ rota: comHorasVelhas() });
    m.planeador[acao]('loja-X');
    await falhar(m, nome, erroConflito());
    expect(m.vista().conflito).not.toBeNull();
    expect(m.vista().calculo.mensagem).toBeNull();
    expect(m.vista().alerta).toBeNull();
    const sugeridas = m.vista().sugestoes.grupos.flatMap((g) => g.lojas);
    expect(sugeridas.map((l) => [l.id, l.aAdicionar])).toEqual([['loja-X', false], ['loja-Y', false]]);
  }
  const m = await carregado({ rota: comHorasVelhas() });
  m.relogio.disparar();
  await falhar(m, 'recalcularHoras', erroConflito());
  expect(m.vista().conflito).not.toBeNull();
  expect(m.vista().calculo.mensagem).toBeNull();
});

test('409 rota_em_curso: só de leitura, com a mensagem do servidor', async () => {
  const m = await comSugestoes();
  m.planeador.mover(0, 2);
  m.planeador.escolherPonto('inicio');
  m.planeador.guardar();
  await falhar(m, 'alterarRota', erroEmCurso());
  const v = m.vista();
  expect(v).toMatchObject({
    estado: 'rota', somenteLeitura: true, textoLeitura: TEXTO_EM_CURSO_LEITURA, conflito: null, alerta: null,
    acoes: null, calculo: null, sugestoes: null, escolherPonto: null, lojaEscolhida: null, podeAdicionar: false,
  });
  expect(v.definicoes).toMatchObject({ ativas: false, mensagem: null });
  expect(idsDaRota(m)).toEqual(['A', 'C', 'E']);
  expect(v.seccoes.rota.every((l) => !l.podeSubir && !l.podeDescer)).toBe(true);
  m.planeador.retirar('C');
  m.planeador.adicionar('loja-X');
  m.planeador.escolherLoja(LOJAS[5]);
  expect(escritas(m)).toHaveLength(1);
  expect(m.vista().lojaEscolhida).toBeNull();
  // O "Recarregar" traz a rota como o servidor a vê (só de leitura, com os registos).
  m.planeador.recarregar();
  await responder(m, 'obterRota', resposta(3, { editavel: false, estado: 'em_curso', estado_efetivo: 'em_curso' }));
  expect(m.vista()).toMatchObject({ somenteLeitura: true, textoLeitura: TEXTO_EM_CURSO_LEITURA, rotuloEstado: 'Em curso' });
});

test('409 rota_fechada: só de leitura com "Este dia já passou…"; recarregar mostra a concluída', async () => {
  const m = await carregado({ rota: comHorasVelhas() });
  m.planeador.retirar('C');
  await falhar(m, 'alterarRota', erroFechada());
  expect(m.vista()).toMatchObject({ somenteLeitura: true, textoLeitura: 'Este dia já passou — a rota só se pode ver.', acoes: null });
  expect(m.vista().horas).toEqual({ atuais: false, texto: 'Horas antigas' });
  expect(m.relogio.esperas).toEqual([]);
  m.planeador.recarregar();
  await responder(m, 'obterRota', resposta(3, { editavel: false, estado_efetivo: 'concluida' }));
  expect(m.vista()).toMatchObject({ somenteLeitura: true, textoLeitura: 'Concluída — só de leitura' });
  // Se o servidor a voltar a dar como editável, volta a ser.
  m.planeador.recarregar();
  await responder(m, 'obterRota', resposta(3));
  expect(m.vista()).toMatchObject({ somenteLeitura: false, textoLeitura: null });
  m.planeador.retirar('C');
  expect(pedidos(m, 'alterarRota')).toHaveLength(2);
});

test('recarregar enquanto uma gravação responde: a leitura (mais velha) não conta', async () => {
  const m = await carregado();
  m.planeador.mudarDefinicao('hora_saida', '07:30');
  m.planeador.recarregar();
  await responder(m, 'alterarRota', resposta(4, { hora_saida: '07:30' }));
  await responder(m, 'obterRota', resposta(3));
  expect(m.vista().definicoes.hora_saida).toBe('07:30');
  expect(m.vista().recarga).toEqual({ aRecarregar: false, erro: null });
  m.planeador.mudarDefinicao('evitar_portagens', true);
  expect(corpo(m)).toEqual([DIA, { evitar_portagens: true, versao: 4 }]);
});

test('recarregar com uma gravação em curso: a rota lida fica, mas a versão é a da gravação', async () => {
  const m = await carregado();
  m.planeador.mudarDefinicao('hora_saida', '07:30');
  m.planeador.recarregar();
  await responder(m, 'obterRota', resposta(3, { estado: 'planeada', estado_efetivo: 'planeada' }));
  // A alteração continua por cima da rota lida.
  expect(m.vista()).toMatchObject({ rotuloEstado: 'Planeada', definicoes: { hora_saida: '07:30' } });
  m.planeador.mudarDefinicao('evitar_portagens', true);
  await responder(m, 'alterarRota', resposta(4, { hora_saida: '07:30' }));
  expect(corpo(m)).toEqual([DIA, { evitar_portagens: true, versao: 4 }]);
});

// --- As horas automáticas (o temporizador à mão) ------------------------------------------------------

test('horas automáticas: com as horas velhas, ~1,5 s depois de a rota chegar, uma só vez', async () => {
  const m = await comSugestoes({ rota: comHorasVelhas() });
  expect(m.relogio.esperas).toEqual([1500]);
  expect(pedidos(m, 'recalcularHoras')).toEqual([]);
  m.relogio.disparar();
  expect(ultimo(m, 'recalcularHoras').argumentos).toEqual([DIA, 3]);
  expect(m.vista().horas).toEqual({ atuais: false, texto: 'a recalcular' });
  expect(m.vista().acoes.recalcular).toEqual({ texto: 'A recalcular…', ativo: false, falta: null });
  await responder(m, 'recalcularHoras', resposta(3, { calculo: { ...CALCULO, calculado_em: '2026-10-10T08:00:00.000000+00:00' } }));
  expect(m.vista().horas).toEqual({ atuais: true, texto: null });
  expect(m.relogio.esperas).toEqual([]);
  // Depois do recálculo as sugestões pedem-se outra vez (o corredor muda com as horas).
  expect(pedidos(m, 'obterSugestoes')).toHaveLength(2);
  expect(pedidos(m, 'recalcularHoras')).toHaveLength(1);
  expect(m.avisos).toEqual([]);
});

test('horas automáticas: nunca com as horas em dia, sem a chave, só de leitura ou sem paragens na rota', async () => {
  for (const rota of [
    rotaDoServidor(),
    comHorasVelhas({ calculo_disponivel: false }),
    rotaDoServidor({ calculo: null, calculo_disponivel: false }),
    comHorasVelhas({ editavel: false }),
    comHorasVelhas({ paragens: [rotaDoServidor().paragens[1]] }),
    rotaVirtual(),
  ]) {
    const m = await carregado({ rota });
    expect(m.relogio.esperas).toEqual([]);
  }
  // Sem cálculo nenhum, mas com a chave e paragens: calcula.
  const semCalculo = await carregado({ rota: rotaDoServidor({ calculo: null }) });
  expect(semCalculo.relogio.esperas).toEqual([1500]);
});

test('horas automáticas depois de uma alteração: a espera só começa quando a fila esvazia, e cada ação a cancela', async () => {
  const m = await carregado();
  m.planeador.mover(0, 2);
  expect(m.relogio.esperas).toEqual([]);
  m.planeador.retirar('A');
  await responder(m, 'alterarRota', respostaVelha(4));
  // Ainda falta a segunda.
  expect(m.relogio.esperas).toEqual([]);
  await responder(m, 'alterarRota', respostaVelha(5));
  expect(m.relogio.esperas).toEqual([1500]);
  // Uma ação nova cancela a espera; a resposta dela arma outra.
  m.planeador.mudarMotivo('A', 'entrega');
  expect(m.relogio.esperas).toEqual([]);
  await responder(m, 'alterarRota', respostaVelha(6));
  expect(m.relogio.esperas).toEqual([1500]);
  m.relogio.disparar();
  expect(pedidos(m, 'recalcularHoras').map((p) => p.argumentos)).toEqual([[DIA, 6]]);
});

test('horas automáticas: com a fila ocupada não se arma a espera (o adicionar, a rede que volta, a rota relida)', async () => {
  const m = await carregado({ rota: comHorasVelhas() });
  expect(m.relogio.esperas).toEqual([1500]);
  m.planeador.adicionar('loja-X');
  expect(m.relogio.esperas).toEqual([]);
  m.mudarRede(true);
  expect(m.relogio.esperas).toEqual([]);
  m.planeador.recarregar();
  await responder(m, 'obterRota', respostaVelha(3));
  expect(m.relogio.esperas).toEqual([]);
  expect(pedidos(m, 'recalcularHoras')).toEqual([]);
  await responder(m, 'adicionarParagem', respostaVelha(4, { paragens: [...rotaDoServidor().paragens, paragem('X', 6, { numero: 4 })] }));
  expect(m.relogio.esperas).toEqual([1500]);
});

test('horas automáticas falham (503): a mensagem, `falhou`, e não tentam sozinhas até à próxima alteração ou ao botão', async () => {
  const m = await carregado({ rota: comHorasVelhas() });
  m.relogio.disparar();
  await falhar(m, 'recalcularHoras', erroCalculo());
  expect(m.vista().calculo).toEqual({ aCalcular: false, mensagem: MENSAGEM_LIMITE });
  expect(m.vista().horas).toEqual({ atuais: false, texto: 'Horas antigas — Recalcular horas' });
  expect(m.vista().alerta).toBeNull();
  expect(m.relogio.esperas).toEqual([]);
  // A rede a cair e a voltar não volta a tentar.
  m.mudarRede(false);
  m.mudarRede(true);
  expect(m.relogio.esperas).toEqual([]);
  // Uma alteração volta a ligar o automático.
  m.planeador.mudarMotivo('A', 'entrega');
  await responder(m, 'alterarRota', respostaVelha(4));
  expect(m.relogio.esperas).toEqual([1500]);
  m.relogio.disparar();
  expect(m.vista().calculo.mensagem).toBeNull();
  await falhar(m, 'recalcularHoras', erroCalculo('indisponivel', 'Cálculo automático indisponível — ordene à mão'));
  expect(m.vista().calculo.mensagem).toBe('Cálculo automático indisponível — ordene à mão');
  // O botão também.
  m.planeador.recalcularHoras();
  expect(pedidos(m, 'recalcularHoras')).toHaveLength(3);
  await responder(m, 'recalcularHoras', resposta(4));
  expect(m.vista().calculo.mensagem).toBeNull();
});

test('horas automáticas sem rede (o pedido falha, ou o cálculo passou do tecto): também `falhou`', async () => {
  const m = await carregado({ rota: comHorasVelhas() });
  m.relogio.disparar();
  await falhar(m, 'recalcularHoras', erroSemRede());
  expect(m.vista().calculo.mensagem).toBe(MENSAGEM_SEM_REDE);
  m.mudarRede(true);
  expect(m.relogio.esperas).toEqual([]);
});

test('horas automáticas: no máximo uma por par (versão, calculado_em) — uma resposta que ainda traz horas velhas não volta a disparar (correção "T3.32 / T3.38")', async () => {
  const m = await carregado({ rota: comHorasVelhas() });
  m.relogio.disparar();
  // A fábrica mudou entre a leitura e a escrita: o servidor gravou as horas e elas já são velhas.
  await responder(m, 'recalcularHoras', respostaVelha(3, { calculo: { ...CALCULO, atual: false, calculado_em: '2026-10-10T09:00:00.000000+00:00' } }));
  expect(m.relogio.esperas).toEqual([]);
  m.mudarRede(true);
  expect(m.relogio.esperas).toEqual([]);
  // A mesma rota relida (o mesmo par): também não.
  m.planeador.recarregar();
  await responder(m, 'obterRota', respostaVelha(3, { calculo: { ...CALCULO, atual: false, calculado_em: '2026-10-10T09:00:00.000000+00:00' } }));
  expect(m.relogio.esperas).toEqual([]);
  // A rota do início (o par que já se pediu): também não.
  m.planeador.recarregar();
  await responder(m, 'obterRota', respostaVelha(3));
  expect(m.relogio.esperas).toEqual([]);
  // Uma versão nova é outro par.
  m.planeador.mudarMotivo('A', 'entrega');
  await responder(m, 'alterarRota', respostaVelha(4));
  expect(m.relogio.esperas).toEqual([1500]);
  m.relogio.disparar();
  expect(pedidos(m, 'recalcularHoras').map((p) => p.argumentos)).toEqual([[DIA, 3], [DIA, 4]]);
});

test('horas automáticas: o par da resposta de um recálculo pelo botão também conta', async () => {
  const m = await carregado({ rota: comHorasVelhas() });
  m.planeador.recalcularHoras();
  await responder(m, 'recalcularHoras', respostaVelha(3, { calculo: { ...CALCULO, atual: false, calculado_em: '2026-10-10T09:00:00.000000+00:00' } }));
  expect(m.relogio.esperas).toEqual([]);
});

test('horas automáticas: sem rede quando a espera acaba não pede; quando a rede volta, espera outra vez', async () => {
  const m = await carregado({ rota: comHorasVelhas() });
  m.mudarRede(false);
  m.relogio.disparar();
  expect(pedidos(m, 'recalcularHoras')).toEqual([]);
  expect(m.relogio.esperas).toEqual([]);
  m.mudarRede(true);
  expect(m.relogio.esperas).toEqual([1500]);
  m.relogio.disparar();
  expect(pedidos(m, 'recalcularHoras')).toHaveLength(1);
});

test('horas automáticas: recarregar depois de uma falha volta a ligar o automático para uma rota nova', async () => {
  const m = await carregado({ rota: comHorasVelhas() });
  m.relogio.disparar();
  await falhar(m, 'recalcularHoras', erroCalculo());
  m.planeador.recarregar();
  await responder(m, 'obterRota', respostaVelha(5));
  expect(m.relogio.esperas).toEqual([1500]);
  expect(m.vista().calculo.mensagem).toBeNull();
});

test('horas automáticas: um recálculo sem resposta válida não muda a rota', async () => {
  const m = await carregado({ rota: comHorasVelhas() });
  m.relogio.disparar();
  await responder(m, 'recalcularHoras', 'estragada');
  expect(m.vista().horas.atuais).toBe(false);
  expect(m.vista()).toMatchObject({ estado: 'rota', rotuloEstado: 'Rascunho', somenteLeitura: false });
});

// --- As sugestões depois das gravações ---------------------------------------------------------------

test('as sugestões pedem-se outra vez só quando a fila esvazia, e só se alguma gravação deu certo', async () => {
  const m = await comSugestoes();
  m.planeador.mover(0, 2);
  m.planeador.adicionar('loja-X');
  expect(pedidos(m, 'obterSugestoes')).toHaveLength(1);
  await responder(m, 'alterarRota', resposta(4));
  expect(pedidos(m, 'obterSugestoes')).toHaveLength(1);
  await falhar(m, 'adicionarParagem', erroDe('ja_na_rota', 'Esta loja já está na rota deste dia.'));
  expect(pedidos(m, 'obterSugestoes')).toHaveLength(2);
  // Uma gravação que falha sozinha: nada mudou.
  m.planeador.retirar('C');
  await falhar(m, 'alterarRota', erroSemRede());
  expect(pedidos(m, 'obterSugestoes')).toHaveLength(2);
  // Retirar a última loja: "Adicione a primeira paragem pelo mapa.", sem pedir.
  m.planeador.retirar('A');
  await responder(m, 'alterarRota', resposta(5, { paragens: [] }));
  expect(m.vista().sugestoes.estado).toBe('sem_paragens');
  expect(pedidos(m, 'obterSugestoes')).toHaveLength(2);
});

// --- Destruir ----------------------------------------------------------------------------------------

test('destruir: as respostas das gravações já não mudam nada, e a espera das horas cancela-se', async () => {
  const armada = await carregado({ rota: comHorasVelhas() });
  expect(armada.relogio.esperas).toEqual([1500]);
  armada.planeador.destruir();
  expect(armada.relogio.esperas).toEqual([]);
  armada.mudarRede(true);
  expect(armada.relogio.esperas).toEqual([]);

  const m = await carregado({ rota: comHorasVelhas() });
  m.planeador.retirar('C');
  m.planeador.destruir();
  const vistas = m.vistas.length;
  await responder(m, 'alterarRota', respostaVelha(4));
  expect(m.vistas).toHaveLength(vistas);
  expect(m.avisos).toEqual([]);
  expect(m.relogio.esperas).toEqual([]);
  m.planeador.retirar('A');
  m.planeador.adicionar('loja-X');
  expect(escritas(m)).toHaveLength(1);

  const n = await carregado();
  n.planeador.retirar('C');
  n.planeador.destruir();
  await falhar(n, 'alterarRota', erroConflito());
  expect(n.vista().conflito).toBeNull();
  // A espera armada antes de destruir não pede nada se disparar.
  const o = await carregado({ rota: comHorasVelhas() });
  const disparar = o.relogio.disparar.bind(o.relogio);
  o.relogio.cancelar = () => {};
  o.planeador.destruir();
  disparar();
  expect(pedidos(o, 'recalcularHoras')).toEqual([]);
});

// --- Com o relógio falso do Jest (o temporizador do browser, por omissão) ------------------------------

describe('o temporizador do browser, com o relógio falso do Jest (correção "T3.32")', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    comRelogioFalso = true;
  });
  afterEach(() => {
    comRelogioFalso = false;
    jest.useRealTimers();
  });

  test('várias alterações seguidas dão um só recálculo, ~1,5 s depois da última resposta', async () => {
    const m = await carregado({ temporizador: undefined });
    m.planeador.mover(0, 2);
    await responder(m, 'alterarRota', respostaVelha(4));
    jest.advanceTimersByTime(1000);
    m.planeador.subir('C');
    await responder(m, 'alterarRota', respostaVelha(5));
    jest.advanceTimersByTime(1000);
    m.planeador.mudarMotivo('A', 'entrega');
    await responder(m, 'alterarRota', respostaVelha(6));
    jest.advanceTimersByTime(1499);
    expect(pedidos(m, 'recalcularHoras')).toEqual([]);
    jest.advanceTimersByTime(1);
    expect(pedidos(m, 'recalcularHoras').map((p) => p.argumentos)).toEqual([[DIA, 6]]);
    jest.advanceTimersByTime(60000);
    expect(pedidos(m, 'recalcularHoras')).toHaveLength(1);
  });

  test('destruir cancela a espera', async () => {
    const m = await carregado({ rota: comHorasVelhas(), temporizador: undefined });
    expect(jest.getTimerCount()).toBe(1);
    m.planeador.destruir();
    expect(jest.getTimerCount()).toBe(0);
    jest.advanceTimersByTime(5000);
    expect(pedidos(m, 'recalcularHoras')).toEqual([]);
  });
});

// --- Os cantos -----------------------------------------------------------------------------------------

test('as ações antes de a rota chegar (ou com o dia inválido) não pedem nada nem rebentam', async () => {
  for (const m of [montar(), montar({ data: 'abc' })]) {
    m.planeador.adicionar('loja-X');
    m.planeador.retirar('A');
    m.planeador.mover(0, 1);
    m.planeador.subir('A');
    m.planeador.descer('A');
    m.planeador.mudarMotivo('A', 'entrega');
    m.planeador.mudarDefinicao('hora_saida', '07:30');
    m.planeador.escolherPonto('inicio');
    m.planeador.tocarNoMapa({ lat: 38.6, lng: -9 });
    m.planeador.usarFabrica('inicio');
    m.planeador.escolherLoja(LOJAS[5]);
    m.planeador.calcularMelhorOrdem();
    m.planeador.recalcularHoras();
    m.planeador.guardar();
    m.planeador.responderGuardar(true);
    m.mudarRede(true);
    expect(escritas(m)).toEqual([]);
    expect(m.vista()).toMatchObject({ escolherPonto: null, lojaEscolhida: null, podeAdicionar: false, alerta: null });
  }
});

test('uma rota com uma versão que não serve: a primeira gravação sai com `versao: null` (o servidor diz)', async () => {
  const m = await carregado({ rota: rotaDoServidor({ versao: 'x' }) });
  m.planeador.retirar('C');
  expect(corpo(m)).toEqual([DIA, { retirar: ['C'], versao: null }]);
  const n = await carregado({ rota: rotaDoServidor({ versao: 0 }) });
  n.planeador.retirar('C');
  expect(corpo(n)[1].versao).toBeNull();
});

test('o tempo em texto com espaços à volta também vai como inteiro', async () => {
  const m = await carregado();
  m.planeador.mudarTempo('A', ' 25 ');
  expect(corpo(m)[1]).toEqual({ paragens: { A: { tempo_servico_min: 25 } }, versao: 3 });
});

test('adicionar, retirar e voltar a adicionar a mesma loja (o cartão não volta)', async () => {
  const m = await carregado();
  m.planeador.escolherLoja(LOJAS[5]);
  m.planeador.adicionar('loja-X');
  const comX = [...rotaDoServidor().paragens, paragem('X', 6, { numero: 4 })];
  await responder(m, 'adicionarParagem', resposta(4, { paragens: comX }));
  m.planeador.retirar('X');
  await responder(m, 'alterarRota', resposta(5));
  expect(m.vista().lojaEscolhida).toBeNull();
  m.planeador.adicionar('loja-X');
  expect(pedidos(m, 'adicionarParagem').map((p) => p.argumentos)).toEqual([
    [DIA, { loja_id: 'loja-X', versao: 3 }],
    [DIA, { loja_id: 'loja-X', versao: 5 }],
  ]);
  expect(m.avisos.map((a) => a.texto)).toEqual(['Adicionada', 'Retirada']);
});

test('o cartão da loja sai quando a rota relida já a tem, ou passou a só de leitura', async () => {
  const m = await carregado();
  m.planeador.escolherLoja(LOJAS[5]);
  m.planeador.recarregar();
  await responder(m, 'obterRota', resposta(4, { paragens: [...rotaDoServidor().paragens, paragem('X', 6, { numero: 4 })] }));
  expect(m.vista().lojaEscolhida).toBeNull();
  const n = await carregado();
  n.planeador.escolherLoja(LOJAS[5]);
  n.planeador.recarregar();
  await responder(n, 'obterRota', resposta(3, { editavel: false }));
  expect(n.vista().lojaEscolhida).toBeNull();
});

test('recarregar limpa a mensagem da gravação recusada', async () => {
  const m = await carregado();
  m.planeador.retirar('C');
  await falhar(m, 'alterarRota', erroSemRede());
  expect(m.vista().alerta).not.toBeNull();
  m.planeador.recarregar();
  await responder(m, 'obterRota', resposta(3));
  expect(m.vista().alerta).toBeNull();
});

test('depois de um conflito: a rede que volta não arma as horas, e uma gravação que deu certo antes não pede sugestões', async () => {
  const m = await comSugestoes({ rota: comHorasVelhas() });
  m.planeador.mover(0, 2);
  m.planeador.adicionar('loja-X');
  await responder(m, 'alterarRota', respostaVelha(4));
  await falhar(m, 'adicionarParagem', erroConflito());
  expect(m.vista().conflito).not.toBeNull();
  expect(pedidos(m, 'obterSugestoes')).toHaveLength(1);
  expect(m.relogio.esperas).toEqual([]);
  m.mudarRede(false);
  m.mudarRede(true);
  expect(m.relogio.esperas).toEqual([]);
  expect(escritas(m)).toHaveLength(2);
});

test('a rede que volta com a espera armada não arma outra (uma só espera)', async () => {
  const m = await carregado({ rota: comHorasVelhas() });
  m.mudarRede(true);
  m.mudarRede(true);
  expect(m.relogio.esperas).toEqual([1500]);
});

test('horas automáticas: outra pessoa recalculou (a mesma versão, outro calculado_em) — é um par novo', async () => {
  const m = await carregado({ rota: comHorasVelhas() });
  m.relogio.disparar();
  await falhar(m, 'recalcularHoras', erroCalculo());
  m.planeador.recarregar();
  await responder(m, 'obterRota', respostaVelha(3, { calculo: { ...CALCULO, atual: false, calculado_em: '2026-10-10T10:00:00.000000+00:00' } }));
  expect(m.relogio.esperas).toEqual([1500]);
});

test('recarregar com uma gravação em curso: a versão da fila fica a dela, mesmo sem versão na resposta', async () => {
  const m = await carregado();
  m.planeador.mudarDefinicao('hora_saida', '07:30');
  m.planeador.recarregar();
  await responder(m, 'obterRota', resposta(6));
  m.planeador.mudarDefinicao('evitar_portagens', true);
  await responder(m, 'alterarRota', 'estragada');
  expect(corpo(m)).toEqual([DIA, { evitar_portagens: true, versao: 3 }]);
});

test('"Fábrica" com as duas pontas num ponto do mapa: a fábrica é o centro do GET /config', async () => {
  const pontos = { inicio: { lat: 38.6, lng: -9.0, fabrica: false }, fim: { lat: 38.9, lng: -9.3, fabrica: false } };
  const m = await carregado({ rota: rotaDoServidor(pontos), config: { ...CONFIG, centro: { lat: 38.71, lng: -9.14 } } });
  m.planeador.usarFabrica('fim');
  expect(corpo(m)).toEqual([DIA, { fim: null, versao: 3 }]);
  expect(m.vista().definicoes.fim).toEqual({ lat: 38.71, lng: -9.14, fabrica: true, texto: 'Fábrica' });
  expect(m.vista().definicoes.inicio).toEqual({ lat: 38.6, lng: -9.0, fabrica: false, texto: 'Ponto no mapa' });
});

test('adicionar outra loja (das sugestões) não fecha o cartão que está aberto', async () => {
  const m = await carregado();
  m.planeador.escolherLoja(LOJAS[6]);
  m.planeador.adicionar('loja-X');
  await responder(m, 'adicionarParagem', resposta(4, { paragens: [...rotaDoServidor().paragens, paragem('X', 6, { numero: 4 })] }));
  expect(m.vista().lojaEscolhida).toMatchObject({ id: 'loja-Y', aAdicionar: false, ativo: true });
});

test('só de leitura, o toque numa loja não guarda o cartão para quando a rota voltar a ser editável', async () => {
  const m = await carregado({ rota: rotaDoServidor({ editavel: false }) });
  m.planeador.escolherLoja(LOJAS[5]);
  m.planeador.recarregar();
  await responder(m, 'obterRota', resposta(3));
  expect(m.vista().lojaEscolhida).toBeNull();
});

test('a faixa do ponto aberta e a rede cai: o toque não grava; a rede volta e a faixa também', async () => {
  const m = await carregado();
  m.planeador.escolherPonto('inicio');
  m.mudarRede(false);
  expect(m.vista().escolherPonto).toBeNull();
  m.planeador.tocarNoMapa({ lat: 38.6, lng: -9.0 });
  expect(escritas(m)).toEqual([]);
  m.mudarRede(true);
  expect(m.vista().escolherPonto).toBe('inicio');
  m.planeador.tocarNoMapa({ lat: 38.6, lng: -9.0 });
  expect(corpo(m)).toEqual([DIA, { inicio: { lat: 38.6, lng: -9.0 }, versao: 3 }]);
});

test('o conflito fecha a faixa do ponto, e enquanto dura não se abre outra (nem depois de recarregar)', async () => {
  const m = await carregado();
  m.planeador.escolherPonto('inicio');
  m.planeador.retirar('C');
  await falhar(m, 'alterarRota', erroConflito());
  m.planeador.escolherPonto('fim');
  m.planeador.recarregar();
  await responder(m, 'obterRota', resposta(4));
  expect(m.vista().escolherPonto).toBeNull();
});

test('numa rota virtual, "Fábrica" não grava mesmo que o servidor mande uma ponta num ponto do mapa', async () => {
  const m = await carregado({ rota: rotaVirtual({ fim: { lat: 38.9, lng: -9.3, fabrica: false } }) });
  m.planeador.usarFabrica('fim');
  expect(escritas(m)).toEqual([]);
});

test('a mensagem do cálculo: a falha com a chave; sem a chave (a rota nova já não a tem), "indisponível"', async () => {
  const m = await carregado({ rota: comHorasVelhas() });
  m.relogio.disparar();
  await falhar(m, 'recalcularHoras', erroCalculo());
  expect(m.vista().calculo.mensagem).toBe(MENSAGEM_LIMITE);
  m.planeador.mudarMotivo('A', 'entrega');
  await responder(m, 'alterarRota', respostaVelha(4, { calculo_disponivel: false }));
  expect(m.vista().calculo).toEqual({ aCalcular: false, mensagem: 'Cálculo automático indisponível — ordene à mão' });
});

test('a rede a mudar antes de a rota chegar não rebenta (nem no ouvinte)', async () => {
  const erros = jest.spyOn(console, 'error').mockImplementation(() => {});
  try {
    const m = montar();
    m.mudarRede(false);
    m.mudarRede(true);
    await falhar(m, 'obterRota', erroSemRede());
    m.mudarRede(true);
    expect(erros).not.toHaveBeenCalled();
    expect(m.relogio.esperas).toEqual([]);
  } finally {
    erros.mockRestore();
  }
});
