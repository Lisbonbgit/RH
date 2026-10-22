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
 * As ações, as horas automáticas e os conflitos são da T3.32.
 */
import { ErroCrm, MENSAGEM_ERRO_INESPERADO, MENSAGEM_SEM_REDE } from './api';
import { ATRIBUICOES, TEXTO_ROTA_DE_TERCEIROS } from './atribuicoes';
import { descodificarPolilinha } from './polilinha';
import { criarEstadoRede } from './rede';
import {
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
  };
}

const assentar = () => new Promise((r) => {
  setTimeout(r, 0);
});

// Monta o ecrã como a página (CrmRota): cria e inicia. A `data` em falta é o DIA (um `undefined` explícito
// fica `undefined`: o `:data` da rota que não veio).
function montar(opcoes = {}) {
  const { online = true, base = '/crm', iniciar = true } = opcoes;
  const data = 'data' in opcoes ? opcoes.data : DIA;
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
  });
  if (iniciar) planeador.iniciar();
  const mudarRede = (ligado) => {
    navegador.onLine = ligado;
    janela.dispatchEvent(new Event(ligado ? 'online' : 'offline'));
  };
  return { api, planeador, navegacoes, avisos, vistas, mudarRede, vista: () => planeador.vista };
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
  'acoes', 'calculo', 'blocosGoogle', 'atribuicaoOrs', 'limite', 'escolherPonto', 'lojaEscolhida', 'recarga',
  'caminhoRotas',
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
