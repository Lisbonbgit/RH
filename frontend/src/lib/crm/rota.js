// A rota de um dia no frontend (F3 / T3.27): os motivos, as secções, os avisos, os totais e a visão
// otimista das alterações. Módulo puro, sem DOM nem rede; o planeador (T3.31/T3.32) usa-o para montar
// a `vista`.
//
// A rota vem do servidor já arrumada (`GET /rotas/{data}` e as respostas das escritas; plano F3 §4): as
// paragens ativas por `ordem`, cada uma com a `seccao` ("rota", "fechada", "nao_cabe", "sem_loja"), o
// `numero` (1..k só na secção "rota"), o `aviso` e os `links` de navegação; o `calculo` com o `atual`
// (as horas guardadas só valem com `atual: true`); os `blocos_google`.
//
// - `seccoesDaRota`, `avisosDaRota`, `totaisDaRota`, `precisaDeHoras` e `perguntaGuardar` só leem o
//   que o servidor mandou.
// - `aplicarLocalmente(rota, corpo)` é a visão otimista de um `PATCH /rotas/{data}`: aplica a ordem,
//   retirar, o motivo, o tempo, os sinais ("Manter", "Pôr na rota"), as definições do dia e o estado,
//   e refaz as secções, os números e os avisos com as regras do servidor (`dominio.rotas.seccoes`,
//   `aviso`, `nova_ordem` e o `_alteracoes` do `crm/rotas.py`). O que o servidor recusaria (422) não
//   muda nada: a resposta dele desfaz a visão de qualquer forma. As horas deixam de ser atuais quando
//   muda o que as decide (a entrada do `horarios.entrada_calculo`: as horas do dia, o início, o fim, as
//   portagens e as paragens da secção "rota" pela ordem, com o tempo de serviço), e sem nenhuma paragem
//   na secção "rota" o cálculo e as horas limpam-se, como no servidor (correções "T3.20 / T3.27" e
//   "F3-MAT-2"). O que só o servidor monta fica vazio até à resposta, em vez de ficar errado: os
//   `blocos_google` quando muda a secção "rota" ou as portagens, e os `links` de cada paragem quando
//   mudam as portagens. O tempo padrão de um motivo novo também vem só na resposta (o planeador não
//   tem as definições).
// - `corpoOrdem(rota, idsRota)` é o corpo de um arrastar na secção "rota".
//
// MOTIVOS, MOTIVO_POR_FASE e LIMITE_PARAGENS são os de backend/crm/dominio/rotas.py, verificados nos
// dois sentidos (backend/tests/crm/test_consistencia_frontend.py lê este ficheiro; o rota.test.js lê o
// rotas.py): manter cada um numa só linha.

import { diaDaSemana } from './datas';

export const MOTIVOS = Object.freeze(['entrega', 'amostra', 'acompanhamento', 'angariacao']);

// A pré-escolha do motivo ao adicionar à rota (desenho original §4.3), pela ordem das fases (`fases.ORDEM`).
export const MOTIVO_POR_FASE = Object.freeze({ perdida: 'angariacao', potencial: 'angariacao', contactada: 'amostra', amostra: 'acompanhamento', cliente: 'acompanhamento' });

// O Directions aceita 50 coordenadas: 48 paragens mais o início e o fim.
export const LIMITE_PARAGENS = 48;

export const ROTULOS_MOTIVO = Object.freeze({
  entrega: 'Entrega',
  amostra: 'Amostra',
  acompanhamento: 'Acompanhamento',
  angariacao: 'Angariação',
});

// Os `ESTADOS` do servidor, pela mesma ordem (a F3 só grava os dois primeiros).
export const ROTULOS_ESTADO = Object.freeze({
  rascunho: 'Rascunho',
  planeada: 'Planeada',
  em_curso: 'Em curso',
  concluida: 'Concluída',
});

// Os `AVISOS` do servidor menos o "nenhum", pela mesma ordem.
export const TEXTOS_AVISO = Object.freeze({
  fechada_neste_dia: '⚠️ Fechada neste dia',
  nao_cabe: '⚠️ Não cabe no horário',
  fora_de_horario: '⚠️ Fora do horário de receção',
});

// Sem fase conhecida, a loja ainda está por angariar.
const MOTIVO_SEM_FASE = 'angariacao';

// A secção da API → o grupo do `seccoesDaRota`.
const GRUPO_DA_SECCAO = Object.freeze({ rota: 'rota', fechada: 'fechadas', nao_cabe: 'naoCabem', sem_loja: 'semLoja' });

// Os campos de topo das definições do dia que o PATCH muda tal e qual.
const CAMPOS_HORA = Object.freeze(['hora_saida', 'hora_regresso_limite']);
const PONTAS = Object.freeze(['inicio', 'fim']);
const OUTRA_PONTA = Object.freeze({ inicio: 'fim', fim: 'inicio' });

// As regras do validador do servidor (`janelas.hora` e `validador_rota`): "HH:MM" e de 1 a 240 minutos.
const FORMATO_HORA = /^([01][0-9]|2[0-3]):[0-5][0-9]$/;
const TEMPO_MINIMO = 1;
const TEMPO_MAXIMO = 240;

// As horas de uma paragem sem cálculo (o `SEM_HORAS` do `crm/rotas.py`).
const SEM_HORAS = Object.freeze({ chegada_prevista: null, espera_min: null, fora_de_horario: false });

// --- Pequenas leituras seguras -------------------------------------------------------------------

const temProprio = (objeto, chave) => Object.prototype.hasOwnProperty.call(objeto, chave);
const eObjeto = (valor) => valor !== null && typeof valor === 'object' && !Array.isArray(valor);
const eNumeroFinito = (valor) => typeof valor === 'number' && Number.isFinite(valor);

// O valor de `mapa[chave]` só se for uma chave própria (nunca o `constructor` nem o `__proto__`), ou null.
function proprio(mapa, chave) {
  return typeof chave === 'string' && temProprio(mapa, chave) ? mapa[chave] : null;
}

const paragensDe = (rota) => (Array.isArray(rota?.paragens) ? rota.paragens : []);

// Os ids de uma lista, sem os que não são texto nem os repetidos.
function idsDe(lista) {
  return Array.isArray(lista) ? [...new Set(lista.filter((id) => typeof id === 'string'))] : [];
}

const plural = (n, singular, varios) => (n === 1 ? singular : varios);

// O corpo tal como vai no pedido (o axios manda-o em JSON): sem o que o JSON deixa cair (as chaves
// herdadas, os valores `undefined`, as funções). A visão otimista nunca mostra o que o servidor não recebe.
function comoVaiNoPedido(corpo) {
  if (!eObjeto(corpo)) return {};
  const lido = JSON.parse(JSON.stringify(corpo));
  return eObjeto(lido) ? lido : {};
}

// --- Textos --------------------------------------------------------------------------------------

// O motivo pré-escolhido para uma loja nesta fase; uma fase desconhecida (ou que nem é texto) dá
// "angariacao", como o `motivo_por_fase` do servidor.
export function motivoPorFase(fase) {
  return proprio(MOTIVO_POR_FASE, fase) ?? MOTIVO_SEM_FASE;
}

export const rotuloMotivo = (motivo) => proprio(ROTULOS_MOTIVO, motivo);
export const rotuloEstado = (estado) => proprio(ROTULOS_ESTADO, estado);
// O texto do aviso de uma paragem, ou null (também no "nenhum").
export const textoAviso = (aviso) => proprio(TEXTOS_AVISO, aviso);

// "123,5 km" (sempre em quilómetros, com uma casa decimal e vírgula), ou null.
export function textoDistancia(metros) {
  if (!eNumeroFinito(metros) || metros < 0) return null;
  const decimas = Math.round(metros / 100);
  return `${Math.floor(decimas / 10)},${decimas % 10} km`;
}

// "5 h 21 min", "45 min" ou "2 h" (arredondado ao minuto), ou null.
export function textoDuracao(segundos) {
  if (!eNumeroFinito(segundos) || segundos < 0) return null;
  const minutos = Math.round(segundos / 60);
  const horas = Math.floor(minutos / 60);
  const resto = minutos % 60;
  if (horas === 0) return `${resto} min`;
  return resto === 0 ? `${horas} h` : `${horas} h ${resto} min`;
}

// --- O que o servidor mandou ---------------------------------------------------------------------

// `{rota, fechadas, naoCabem, semLoja}`: as paragens de cada secção, pela ordem da rota (os mesmos
// objetos). Uma secção desconhecida não entra em nenhum grupo.
export function seccoesDaRota(rota) {
  const grupos = { rota: [], fechadas: [], naoCabem: [], semLoja: [] };
  for (const paragem of paragensDe(rota)) {
    const grupo = proprio(GRUPO_DA_SECCAO, paragem?.seccao);
    if (grupo !== null) grupos[grupo].push(paragem);
  }
  return grupos;
}

// Os totais do último cálculo, para o resumo: `{distancia, duracao, regresso, regressoTarde, atual}`,
// ou null sem cálculo. Com `atual: false` o ecrã mostra-os esbatidos.
export function totaisDaRota(rota) {
  const calculo = rota?.calculo;
  if (!eObjeto(calculo)) return null;
  return {
    distancia: textoDistancia(calculo.distancia_m),
    duracao: textoDuracao(calculo.duracao_s),
    regresso: calculo.regresso_previsto ?? null,
    regressoTarde: calculo.depois_do_limite === true,
    atual: calculo.atual === true,
  };
}

// Os avisos da rota inteira, por esta ordem: o regresso depois do limite (só com as horas atuais), as
// fechadas neste dia e as que não cabem no horário.
export function avisosDaRota(rota) {
  const avisos = [];
  const calculo = rota?.calculo;
  if (eObjeto(calculo) && calculo.atual === true && calculo.depois_do_limite === true) {
    const limite = rota.hora_regresso_limite;
    // A partir das 24:00 o servidor não dá a hora (`regresso_previsto: null`), só o aviso.
    avisos.push(
      calculo.regresso_previsto == null
        ? `Regresso previsto depois da meia-noite — depois do limite (${limite}).`
        : `Regresso previsto às ${calculo.regresso_previsto} — depois do limite (${limite}).`,
    );
  }
  const { fechadas, naoCabem } = seccoesDaRota(rota);
  if (fechadas.length > 0) {
    avisos.push(
      plural(
        fechadas.length,
        '1 paragem fechada neste dia fica fora do cálculo até escolher "Manter".',
        `${fechadas.length} paragens fechadas neste dia ficam fora do cálculo até escolher "Manter".`,
      ),
    );
  }
  if (naoCabem.length > 0) {
    avisos.push(plural(naoCabem.length, '1 paragem não cabe no horário.', `${naoCabem.length} paragens não cabem no horário.`));
  }
  return avisos;
}

// O planeador pede as horas sozinho? Há chave do openrouteservice, a rota é editável, tem paragens na
// secção "rota", as horas não são atuais e o último recálculo não falhou.
export function precisaDeHoras(rota, { falhou = false } = {}) {
  return (
    rota?.calculo_disponivel === true &&
    rota.editavel === true &&
    seccoesDaRota(rota).rota.length >= 1 &&
    rota.calculo?.atual !== true &&
    !falhou
  );
}

// A pergunta do "Guardar rota" quando há paragens que não cabem, ou null.
export function perguntaGuardar(rota) {
  const n = seccoesDaRota(rota).naoCabem.length;
  if (n === 0) return null;
  return plural(n, '1 paragem não cabe — guardar mesmo assim?', `${n} paragens não cabem — guardar mesmo assim?`);
}

// O corpo de um arrastar na secção "rota": `{ordem}` com os `idsRota` (só os da secção "rota", sem
// repetidos; as da secção em falta a seguir, pela ordem delas), depois as que não cabem e as fechadas,
// cada grupo pela sua ordem. As de uma loja apagada ficam de fora: o servidor põe-nas no fim.
export function corpoOrdem(rota, idsRota) {
  const { rota: naRota, naoCabem, fechadas } = seccoesDaRota(rota);
  const daRota = new Set(naRota.map((p) => p.id));
  const ordem = idsDe(idsRota).filter((id) => daRota.has(id));
  const vistos = new Set(ordem);
  for (const paragem of [...naRota, ...naoCabem, ...fechadas]) {
    if (!vistos.has(paragem.id)) {
      vistos.add(paragem.id);
      ordem.push(paragem.id);
    }
  }
  return { ordem };
}

// --- A visão otimista ----------------------------------------------------------------------------

// A secção de uma paragem pela regra do servidor (`dominio.rotas.seccoes`): sem loja → fechada neste
// dia e sem "Manter" → não cabe → rota.
function seccaoDe(paragem, dia) {
  const loja = paragem.loja;
  if (loja == null) return 'sem_loja';
  const diasFechada = Array.isArray(loja.dias_fechada) ? loja.dias_fechada : [];
  if (dia !== null && diasFechada.includes(dia) && !paragem.manter_fechada) return 'fechada';
  if (paragem.nao_cabe) return 'nao_cabe';
  return 'rota';
}

// O aviso pela secção (`dominio.rotas.aviso`): o fora de horário só na secção "rota" e com as horas atuais.
function avisoDe(paragem, seccao, calculoAtual) {
  if (seccao === 'fechada') return 'fechada_neste_dia';
  if (seccao === 'nao_cabe') return 'nao_cabe';
  if (seccao === 'rota' && calculoAtual && paragem.fora_de_horario) return 'fora_de_horario';
  return 'nenhum';
}

// As alterações válidas de uma paragem (o que o validador do servidor aceitaria), já aplicadas.
function comAlteracoes(paragem, alteracoes) {
  if (!eObjeto(alteracoes)) return paragem;
  const nova = { ...paragem };
  if (MOTIVOS.includes(alteracoes.motivo)) nova.motivo = alteracoes.motivo;
  const tempo = alteracoes.tempo_servico_min;
  if (Number.isInteger(tempo) && tempo >= TEMPO_MINIMO && tempo <= TEMPO_MAXIMO) nova.tempo_servico_min = tempo;
  if (typeof alteracoes.manter_fechada === 'boolean') nova.manter_fechada = alteracoes.manter_fechada;
  // "Só se pode pôr de volta na rota."
  if (alteracoes.nao_cabe === false) nova.nao_cabe = false;
  return nova;
}

// A ordem nova (`dominio.rotas.nova_ordem`, leniente): as pedidas primeiro, as outras pela ordem delas.
function pelaOrdem(paragens, ids) {
  const porId = new Map(paragens.map((p) => [p.id, p]));
  const pedidas = idsDe(ids).filter((id) => porId.has(id));
  const vistas = new Set(pedidas);
  return [...pedidas.map((id) => porId.get(id)), ...paragens.filter((p) => !vistas.has(p.id))];
}

// O início ou o fim depois do PATCH: um ponto `{lat, lng}`, ou `null` (a fábrica). Sem saber onde é a
// fábrica (nem pelas `opcoes`, nem por uma das pontas que já é a fábrica), fica como estava até à
// resposta. Outra coisa (que o servidor recusaria) não muda nada.
function pontaDepois(rota, ponta, valor, fabrica) {
  const atual = rota[ponta];
  if (valor === null) {
    const conhecida = [fabrica, atual?.fabrica === true ? atual : null, rota[OUTRA_PONTA[ponta]]?.fabrica === true ? rota[OUTRA_PONTA[ponta]] : null].find(
      (ponto) => eObjeto(ponto) && eNumeroFinito(ponto.lat) && eNumeroFinito(ponto.lng),
    );
    return conhecida === undefined ? atual : { lat: conhecida.lat, lng: conhecida.lng, fabrica: true };
  }
  if (eObjeto(valor) && eNumeroFinito(valor.lat) && eNumeroFinito(valor.lng)) return { lat: valor.lat, lng: valor.lng, fabrica: false };
  return atual;
}

// As paragens com a secção pela regra (`[{paragem, seccao}]`).
const arrumar = (paragens, dia) => paragens.map((paragem) => ({ paragem, seccao: seccaoDe(paragem, dia) }));
const incluidasDe = (arrumadas) => arrumadas.filter(({ seccao }) => seccao === 'rota').map(({ paragem }) => paragem);
const coordenadas = (ponto) => [ponto?.lat ?? null, ponto?.lng ?? null];

// O que decide as horas (a entrada do `horarios.entrada_calculo`, sem o que aqui não muda: as
// coordenadas e as janelas das lojas).
function entradaDasHoras(rota, incluidas) {
  return JSON.stringify([
    rota.hora_saida,
    rota.hora_regresso_limite,
    coordenadas(rota.inicio),
    coordenadas(rota.fim),
    rota.evitar_portagens,
    incluidas.map((p) => [p.id, p.tempo_servico_min]),
  ]);
}

// O que decide os blocos do Google: a secção "rota" pela ordem e as portagens.
const entradaDosBlocos = (rota, incluidas) => JSON.stringify([rota.evitar_portagens, incluidas.map((p) => p.id)]);

// A rota como fica depois do `corpo` de um PATCH (a visão otimista), lido como vai no pedido. Devolve
// uma rota nova e não mexe na que recebe. `opcoes.fabrica` (`{lat, lng}`, o centro do `GET /config`) diz onde fica a fábrica,
// para um `inicio`/`fim` a `null`.
export function aplicarLocalmente(rota, corpo, { fabrica = null } = {}) {
  const pedido = comoVaiNoPedido(corpo);
  const nova = { ...rota };

  for (const campo of CAMPOS_HORA) {
    if (temProprio(pedido, campo) && typeof pedido[campo] === 'string' && FORMATO_HORA.test(pedido[campo])) nova[campo] = pedido[campo];
  }
  if (typeof pedido.evitar_portagens === 'boolean') nova.evitar_portagens = pedido.evitar_portagens;
  for (const ponta of PONTAS) {
    if (temProprio(pedido, ponta)) nova[ponta] = pontaDepois(rota, ponta, pedido[ponta], fabrica);
  }
  if (pedido.estado === 'planeada') {
    nova.estado = 'planeada';
    nova.estado_efetivo = 'planeada';
  }

  // Retirar, as alterações de cada paragem e a ordem (os retirados saem da ordem).
  const retirar = new Set(idsDe(pedido.retirar));
  const alteracoes = eObjeto(pedido.paragens) ? pedido.paragens : {};
  let paragens = paragensDe(rota)
    .filter((p) => !retirar.has(p.id))
    .map((p) => comAlteracoes(p, proprio(alteracoes, p.id)));
  if (temProprio(pedido, 'ordem') || retirar.size > 0) paragens = pelaOrdem(paragens, pedido.ordem);

  // As secções, antes e depois, pela mesma regra.
  const dia = diaDaSemana(rota.data);
  const antes = incluidasDe(arrumar(paragensDe(rota), dia));
  const arrumadas = arrumar(paragens, dia);
  const depois = incluidasDe(arrumadas);

  const semIncluidas = depois.length === 0;
  if (semIncluidas || !eObjeto(rota.calculo)) {
    nova.calculo = null;
  } else {
    const atual = rota.calculo.atual === true && entradaDasHoras(rota, antes) === entradaDasHoras(nova, depois);
    nova.calculo = atual === rota.calculo.atual ? rota.calculo : { ...rota.calculo, atual };
  }
  if (entradaDosBlocos(rota, antes) !== entradaDosBlocos(nova, depois)) nova.blocos_google = [];
  const semLinks = nova.evitar_portagens !== rota.evitar_portagens;

  let numero = 0;
  nova.paragens = arrumadas.map(({ paragem, seccao }, ordem) => {
    if (seccao === 'rota') numero += 1;
    const horas = semIncluidas ? SEM_HORAS : {};
    const p = { ...paragem, ...horas, seccao, ordem, numero: seccao === 'rota' ? numero : null };
    p.aviso = avisoDe(p, seccao, nova.calculo?.atual === true);
    if (semLinks) p.links = null;
    return p;
  });
  return nova;
}
