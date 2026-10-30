// O planeador da rota de um dia (desenho original §7; plano F3 T3.31/T3.32), sem DOM. Molde do
// `criarFicha` (T2.28): o controlador pede o que precisa, monta uma `vista` congelada a cada mudança e
// entrega-a ao `aoMudarVista`; o `pages/crm/CrmRota.js` (T3.38) só a desenha.
//
// Esta parte (T3.31) carrega e mostra:
//  - `iniciar()` pede ao mesmo tempo a rota do dia (`obterRota`), a configuração do mapa e as lojas; as
//    sugestões pedem-se depois de a rota chegar, e só numa rota editável com alguma paragem de uma loja
//    (sem nenhuma, o servidor só diria `sem_paragens`: "Adicione a primeira paragem pelo mapa.");
//  - uma data que não é um dia (`eDataValida`), ou que o servidor recusa (422 na `data`, por exemplo a
//    mais de um ano), dá "Dia inválido" sem mais pedidos;
//  - sem a rota não há planeador: a mensagem e "Tentar novamente". A configuração do mapa e as lojas não
//    impedem a rota de se ver: a falha delas fica junto ao mapa (`falhaDoMapa`). O "Tentar novamente"
//    (e a rede que volta) pedem outra vez só o que falhou;
//  - a rota é só de leitura quando o servidor diz que não é editável (`editavel`): um dia passado
//    ("Concluída — só de leitura", ou "Não houve rota neste dia." sem rota) ou com registos do motorista.
//    Aí não há ações, nem sugestões, nem subir/descer, e as definições do dia ficam desligadas;
//  - numa rota virtual (`existe: false`) o servidor recusa o PATCH (404), por isso as definições do dia
//    ficam desligadas com "Adicione a primeira paragem para mudar as definições do dia." e o "Calcular" e
//    o "Guardar" também (correções "T3.31 / T3.39" e "T3.20 / T3.31 / T3.39");
//  - o rótulo das horas (correção "T3.16 / T3.21 / T3.32"): "a recalcular" só com um recálculo pedido
//    (a fila da T3.32); senão "Horas antigas — Recalcular horas", ou "sem horas — ordene à mão" sem a
//    chave do openrouteservice. As horas só valem com `calculo.atual: true`;
//  - o mapa do planeador (`vista.mapa`): as paragens com coordenadas (só as da secção "rota" têm número),
//    os extremos, a linha (a polyline em pares `[lat, lng]`; o `mapa.js` converte-os, T3.33) e as lojas
//    fora da rota, esbatidas. O `vista.mapa`, a linha e as lojas fora da rota guardam a mesma referência
//    enquanto o que mostram não muda (correção "T3.32 / T3.38": o `MapaLojas` não recria os pinos a cada
//    vista nova);
//  - os links de navegação (Google Maps e Waze por paragem, os blocos de 9) só passam pelo `hrefNavegacao`
//    (regra 9; o `seguranca.test.js` recusa-os sem ele); a atribuição do openrouteservice vai sempre, com
//    a frase `TEXTO_ROTA_DE_TERCEIROS` antes (correções do mapa Google, T3.38).
// `recarregar()` volta a ler a rota (o "Recarregar" do conflito) e `destruir()` faz que as respostas que
// chegarem depois já não façam nada.
//
// A segunda parte (T3.32) grava: cada ação grava logo (plano F3 §1 "Gravação"), pela fila da rota
// (`filaRota.js`: um pedido de cada vez, com a versão da última resposta, as alterações seguidas juntas):
//  - otimistas (`aplicarLocalmente` por cima da última rota do servidor, com as alterações ainda por
//    confirmar): retirar, mover/subir/descer, o motivo, o tempo, "Manter", "Pôr na rota", as definições do
//    dia (as horas, as portagens, o início e o fim: "Ponto no mapa" com um toque, ou "Fábrica") e "Guardar
//    rota" (com a pergunta "N paragens não cabem — guardar mesmo assim?"). A resposta do servidor manda; um
//    erro (422, sem rede…) desfaz a visão otimista e mostra a mensagem (`alerta`);
//  - não otimistas: adicionar uma loja ("A adicionar…" até à resposta, das sugestões ou do cartão de uma
//    loja esbatida no mapa), "Calcular melhor ordem" ("A calcular…") e "Recalcular horas";
//  - as horas automáticas: quando a fila esvazia (e quando a rota chega), se faltam horas
//    (`precisaDeHoras`), ~1,5 s sem alterações e depois um só `recalcular` (correção "T3.32": o temporizador
//    é injetado); no máximo um por par (versão, `calculado_em`), para uma resposta com as horas ainda velhas
//    não disparar sem fim contra o limite do openrouteservice (correção "T3.32 / T3.38"). Um cálculo que
//    falha (503, sem rede) mostra a mensagem e deixa `falhou`: nada mais sozinho até à próxima alteração ou
//    ao botão;
//  - os 409 da rota inteira param a fila: `conflito` → a faixa "Alterado por outra pessoa — recarregar" (o
//    "Recarregar" relê a rota e a fila retoma com a versão dela); `rota_em_curso`/`rota_fechada` → só de
//    leitura, com a mensagem do servidor;
//  - as sugestões voltam a pedir-se quando a fila esvazia depois de uma gravação que deu certo (também a de
//    um recálculo: o corredor muda com as horas);
//  - os avisos ("Adicionada", "Retirada", "Rota guardada como planeada") vão para o `aoAvisar`.
//
// A revisão dos ecrãs da F3 (2026-10-30):
//  - F3-UX-1: a hora de chegada de cada paragem só vale com `calculo.atual: true` (plano F3 §4). O servidor não
//    a limpa quando a ordem muda, nem a visão otimista: a linha leva `chegadaAntiga` e o ecrã marca-a;
//  - F3-UX-3: um dia passado sem rota é "Sem rota" (nunca "Concluída") e não mostra as definições por omissão
//    de hoje, que nunca foram as desse dia;
//  - F3-UX-5: uma fechada com "Manter" (na secção "rota", ou na das que não cabem) leva `mantida` (a loja fecha
//    nesse dia) e "Não manter" (`naoManter`) desfaz-o;
//  - F3-UX-6: sem mapa onde tocar (sem a chave Google, o Map ID, ou a Google que falhou; a página diz-o com
//    `mapaDisponivel`), "Ponto no mapa" não abre e a escolha a meio cancela-se (`definicoes.semMapa`).

import { MENSAGEM_ERRO_INESPERADO, MENSAGEM_SEM_REDE } from './api';
import { ATRIBUICOES, TEXTO_ROTA_DE_TERCEIROS } from './atribuicoes';
import { diaDaSemana, eDataValida, rotuloDataLonga } from './datas';
import { hrefNavegacao } from './dom';
import { textoDoErro } from './ecraMapa';
import { FASES } from './fases';
import { CODIGOS_QUE_PARAM, criarFilaRota, enviarPelaApi } from './filaRota';
import { descodificarPolilinha } from './polilinha';
import { mover as moverNaLista } from './reordenar';
import {
  LIMITE_PARAGENS, aplicarLocalmente, avisosDaRota, corpoOrdem, motivoPorFase, perguntaGuardar, precisaDeHoras,
  rotuloEstado, rotuloMotivo, seccoesDaRota, textoAviso, textoDistancia, totaisDaRota,
} from './rota';

export const TEXTO_A_CARREGAR = 'A carregar a rota…';
export const TITULO_DIA_INVALIDO = 'Dia inválido';
// A mensagem do servidor para a `data` (plano F3 §4).
export const MENSAGEM_DATA_INVALIDA = 'Indique o dia no formato AAAA-MM-DD.';

// Porque é que a rota é só de leitura.
export const TEXTO_NAO_HOUVE_ROTA = 'Não houve rota neste dia.';
export const TEXTO_CONCLUIDA_LEITURA = 'Concluída — só de leitura';
// A mensagem do 409 `rota_em_curso` (plano F3 §4).
export const TEXTO_EM_CURSO_LEITURA = 'A rota já tem registos do motorista — no escritório só se pode ver.';
// O estado de um dia sem rota, hoje ou no futuro (a rota nasce com a primeira paragem).
export const TEXTO_AINDA_SEM_PARAGENS = 'Ainda sem paragens';
// O estado de um dia sem rota que já só se pode ver (um dia passado; revisão dos ecrãs, F3-UX-3).
export const TEXTO_SEM_ROTA = 'Sem rota';

// As definições do dia.
export const TEXTO_DEFINICOES_SEM_ROTA = 'Adicione a primeira paragem para mudar as definições do dia.';
export const TEXTO_FABRICA = 'Fábrica';
export const TEXTO_PONTO_NO_MAPA = 'Ponto no mapa';

// O nome de uma paragem cuja loja foi apagada (secção "sem_loja").
export const TEXTO_PARAGEM_SEM_LOJA = 'Loja apagada';

// As ações e porque estão desligadas.
export const MENSAGEM_SEM_CALCULO = 'Cálculo automático indisponível — ordene à mão';
export const TEXTO_CALCULAR = 'Calcular melhor ordem';
export const TEXTO_RECALCULAR = 'Recalcular horas';
export const TEXTO_GUARDAR_ROTA = 'Guardar rota';
// O desenho original §7.1: "Sem paragens: 'Adicione a primeira paragem pelo mapa'".
export const TEXTO_PRIMEIRA_PARAGEM = 'Adicione a primeira paragem pelo mapa.';
export const TEXTO_NADA_A_CALCULAR = 'Não há paragens para calcular.';
export const TEXTO_HORAS_EM_DIA = 'As horas estão em dia.';
export const TEXTO_JA_PLANEADA = 'A rota já está guardada como planeada.';

// O rótulo das horas (correção "T3.16 / T3.21 / T3.32", tal e qual).
export const TEXTO_HORAS_A_RECALCULAR = 'a recalcular';
export const TEXTO_HORAS_ANTIGAS = 'Horas antigas — Recalcular horas';
export const TEXTO_HORAS_ANTIGAS_LEITURA = 'Horas antigas';
export const TEXTO_SEM_HORAS = 'sem horas — ordene à mão';

// As ações em curso e os avisos (T3.32).
export const TEXTO_A_CALCULAR = 'A calcular…';
export const TEXTO_A_RECALCULAR = 'A recalcular…';
export const TEXTO_A_ADICIONAR = 'A adicionar…';
export const TEXTO_ADICIONADA = 'Adicionada';
export const TEXTO_RETIRADA = 'Retirada';
export const TEXTO_GUARDADA = 'Rota guardada como planeada';
// A faixa do 409 `conflito`: a mesma da ficha da loja (`ficha.TEXTO_CONFLITO`) e a mensagem do servidor.
export const TEXTO_CONFLITO = 'Alterado por outra pessoa — recarregar';
export const TEXTO_FALTA_CONFLITO = 'Recarregue a rota para ver o que a outra pessoa mudou.';
// A faixa do "Ponto no mapa" (com "Cancelar": `escolherPonto(null)`).
export const TEXTOS_ESCOLHER_PONTO = Object.freeze({ inicio: 'Toque no mapa no ponto de início', fim: 'Toque no mapa no ponto de fim' });
// A espera sem alterações antes do recálculo automático (correção "T3.32").
export const ESPERA_HORAS_MS = 1500;
// As definições do dia que o `mudarDefinicao` grava (os campos de topo do PATCH).
export const DEFINICOES_DO_DIA = Object.freeze(['hora_saida', 'hora_regresso_limite', 'inicio', 'fim', 'evitar_portagens']);

// As sugestões.
export const TEXTO_SUGESTOES_A_CARREGAR = 'A procurar lojas perto…';
export const TEXTO_SUGESTOES_NENHUMA = 'Não há lojas para sugerir perto desta rota.';
const PREFIXO_NO_CAMINHO = 'no caminho';

// --- Pequenas leituras seguras -------------------------------------------------------------------

const temProprio = (objeto, chave) => Object.prototype.hasOwnProperty.call(objeto, chave);
const eObjeto = (valor) => valor !== null && typeof valor === 'object' && !Array.isArray(valor);
const eNumeroFinito = (valor) => typeof valor === 'number' && Number.isFinite(valor);
const paragensDe = (rota) => (Array.isArray(rota?.paragens) ? rota.paragens : []);
const comCoordenadas = (ponto) => eObjeto(ponto) && eNumeroFinito(ponto.lat) && eNumeroFinito(ponto.lng);
// Uma versão da rota: um inteiro ≥ 1 (a fila só aceita isso, ou null).
const eVersao = (valor) => Number.isInteger(valor) && valor >= 1;
const PONTAS = Object.freeze(['inicio', 'fim']);

function congelarAFundo(valor) {
  if (valor !== null && typeof valor === 'object' && !Object.isFrozen(valor)) {
    Object.values(valor).forEach(congelarAFundo);
    Object.freeze(valor);
  }
  return valor;
}

const SEM_LINHA = Object.freeze([]);
const SEM_AVISOS = Object.freeze([]);

// A mesma resposta enquanto as entradas forem as mesmas (`===`, uma a uma).
function criarMemo() {
  let entradas = null;
  let valor;
  return (novas, calcular) => {
    if (entradas !== null && novas.every((entrada, i) => entrada === entradas[i])) return valor;
    entradas = novas;
    valor = calcular();
    return valor;
  };
}

// --- Funções puras -------------------------------------------------------------------------------

// O rótulo das horas da rota, ou null quando não há nada a dizer (as horas são atuais, ou não há paragens
// na secção "rota"). `aRecalcular`: há um recálculo (ou uma otimização) pedido.
export function textoDasHoras(rota, { aRecalcular = false } = {}) {
  if (rota?.calculo?.atual === true) return null;
  if (seccoesDaRota(rota).rota.length === 0) return null;
  const temCalculo = eObjeto(rota.calculo);
  if (rota.editavel !== true) return temCalculo ? TEXTO_HORAS_ANTIGAS_LEITURA : null;
  if (aRecalcular) return TEXTO_HORAS_A_RECALCULAR;
  if (rota.calculo_disponivel !== true) return TEXTO_SEM_HORAS;
  return temCalculo ? TEXTO_HORAS_ANTIGAS : null;
}

// Porque é que a rota é só de leitura, ou null se for editável.
export function textoLeitura(rota) {
  if (rota?.editavel === true) return null;
  if (rota?.estado_efetivo === 'concluida') return rota.existe === true ? TEXTO_CONCLUIDA_LEITURA : TEXTO_NAO_HOUVE_ROTA;
  return TEXTO_EM_CURSO_LEITURA;
}

const acao = (texto, falta, extra = {}) => ({ texto, ativo: falta === null, falta, ...extra });
// Um botão cujo pedido está a correr: desligado, sem falta a dizer (o texto já diz "A calcular…").
const emCurso = (texto) => ({ texto, ativo: false, falta: null });

// Os botões de uma rota editável: {calcular, recalcular, guardar}, cada um {texto, ativo, falta} (falta: porque
// está desligado, ou null; o guardar leva também a `pergunta`, que o planeador preenche). Com o pedido a correr
// (`aCalcular`: a melhor ordem; `aRecalcular`: as horas), "A calcular…"/"A recalcular…"; senão, pela ordem dos
// motivos: o conflito; sem rede; a rota ainda sem paragens ativas (a virtual também); depois os de cada ação
// (as horas esperam pela melhor ordem que está a correr).
export function acoesDaRota(rota, {
  online = false, conflito = false, aCalcular = false, aRecalcular = false,
} = {}) {
  const { rota: naRota, naoCabem } = seccoesDaRota(rota);
  let geral = null;
  if (conflito === true) geral = TEXTO_FALTA_CONFLITO;
  else if (online !== true) geral = MENSAGEM_SEM_REDE;
  else if (rota?.existe !== true || paragensDe(rota).length === 0) geral = TEXTO_PRIMEIRA_PARAGEM;
  const semChave = rota?.calculo_disponivel === true ? null : MENSAGEM_SEM_CALCULO;

  // O VROOM leva a secção "rota" e as que não cabem (correção "T3.22 / §1"); as horas, só a secção "rota".
  const nadaParaOtimizar = naRota.length + naoCabem.length === 0 ? TEXTO_NADA_A_CALCULAR : null;
  let horas = null;
  if (naRota.length === 0) horas = TEXTO_NADA_A_CALCULAR;
  else if (rota.calculo?.atual === true) horas = TEXTO_HORAS_EM_DIA;
  const planeada = rota?.estado === 'rascunho' ? null : TEXTO_JA_PLANEADA;

  const otimizar = aCalcular === true;
  return {
    calcular: otimizar ? emCurso(TEXTO_A_CALCULAR) : acao(TEXTO_CALCULAR, geral ?? semChave ?? nadaParaOtimizar),
    recalcular: aRecalcular === true
      ? emCurso(TEXTO_A_RECALCULAR)
      : acao(TEXTO_RECALCULAR, (otimizar ? TEXTO_A_CALCULAR : null) ?? geral ?? semChave ?? horas),
    guardar: acao(TEXTO_GUARDAR_ROTA, geral ?? planeada, { pergunta: null }),
  };
}

// A mensagem de uma gravação recusada: num 422, a do primeiro campo (a geral não diz o que está mal); senão a
// do erro.
function mensagemDoErro(erro) {
  if (erro?.codigo === 'validacao' && eObjeto(erro.campos)) {
    const doCampo = Object.values(erro.campos).find((mensagem) => typeof mensagem === 'string' && mensagem !== '');
    if (doCampo !== undefined) return doCampo;
  }
  return textoDoErro(erro);
}

// O título de um grupo: o rótulo da fase (`fases.js`), ou o próprio nome se não for uma fase conhecida.
function tituloDaFase(fase) {
  if (typeof fase !== 'string') return '';
  return temProprio(FASES, fase) ? FASES[fase].rotulo : fase;
}

// Uma loja sugerida no painel: a distância em texto ("1,2 km", "no caminho, 0,8 km").
function sugestaoDe(loja) {
  const distancia = textoDistancia(loja.distancia_m);
  const noCaminho = loja.no_caminho === true;
  let texto = distancia;
  if (noCaminho) texto = distancia === null ? PREFIXO_NO_CAMINHO : `${PREFIXO_NO_CAMINHO}, ${distancia}`;
  return { id: loja.id, nome: loja.nome, fase: loja.fase, lat: loja.lat, lng: loja.lng, distancia: texto, noCaminho };
}

// A resposta do `GET /rotas/{data}/sugestoes` no painel: {estado, grupos, mensagem, tentar, aTentar}, com
// estado 'sem_paragens', 'nenhuma' ou 'lista'. As lojas que já estão na rota (`idsNaRota`, os `loja_id` das
// paragens; uma resposta que chegou depois de a loja entrar) saem, e um grupo sem lojas nem "e mais N" também.
export function vistaDasSugestoes(resposta, idsNaRota) {
  const base = { grupos: [], mensagem: null, tentar: false, aTentar: false };
  if (resposta?.sem_paragens === true) return { ...base, estado: 'sem_paragens', mensagem: TEXTO_PRIMEIRA_PARAGEM };
  const naRota = new Set(Array.isArray(idsNaRota) ? idsNaRota : []);
  const grupos = [];
  for (const grupo of Array.isArray(resposta?.grupos) ? resposta.grupos : []) {
    if (!eObjeto(grupo)) continue;
    const lojas = (Array.isArray(grupo.lojas) ? grupo.lojas : [])
      .filter((loja) => eObjeto(loja) && typeof loja.id === 'string' && !naRota.has(loja.id))
      .map(sugestaoDe);
    const mais = Number.isInteger(grupo.mais) && grupo.mais > 0 ? grupo.mais : 0;
    if (lojas.length === 0 && mais === 0) continue;
    grupos.push({ fase: grupo.fase, titulo: tituloDaFase(grupo.fase), lojas, mais, textoMais: mais > 0 ? `e mais ${mais}` : null });
  }
  if (grupos.length === 0) return { ...base, estado: 'nenhuma', mensagem: TEXTO_SUGESTOES_NENHUMA };
  return { ...base, estado: 'lista', grupos };
}

// Os `loja_id` das paragens ativas da rota.
const idsDasLojasNaRota = (rota) => paragensDe(rota).map((p) => p?.loja_id);

// As lojas do mapa que não estão em nenhuma paragem ativa da rota (as esbatidas), pela ordem da lista e os
// mesmos objetos; null sem as lojas (ainda não chegaram, ou falharam) ou sem a rota.
export function lojasForaDaRota(lojas, rota) {
  if (!Array.isArray(lojas) || !eObjeto(rota)) return null;
  const naRota = new Set(idsDasLojasNaRota(rota));
  return lojas.filter((loja) => !naRota.has(loja?.id));
}

// --- A vista da rota -----------------------------------------------------------------------------

// Uma ponta da rota (início ou fim) com coordenadas: {lat, lng, fabrica}, ou null.
function pontaDe(ponto) {
  return comCoordenadas(ponto) ? { lat: ponto.lat, lng: ponto.lng, fabrica: ponto.fabrica === true } : null;
}

function pontaDasDefinicoes(ponto) {
  const ponta = pontaDe(ponto);
  return ponta === null ? null : { ...ponta, texto: ponta.fabrica ? TEXTO_FABRICA : TEXTO_PONTO_NO_MAPA };
}

// A loja da paragem fecha neste dia da semana (`dia`: 'seg'…'dom', ou null)?
function fechaNoDia(loja, dia) {
  return dia !== null && eObjeto(loja) && Array.isArray(loja.dias_fechada) && loja.dias_fechada.includes(dia);
}

// Uma linha da lista das paragens. Subir e descer só na secção "rota", e só se a rota se puder mudar agora.
// `horasAtuais`: o cálculo da rota é o atual (senão a chegada é antiga: F3-UX-1); `dia`: o dia da semana da rota.
function linhaDe(paragem, { podeSubir = false, podeDescer = false, horasAtuais = false, dia = null } = {}) {
  const { loja } = paragem;
  let nome = TEXTO_PARAGEM_SEM_LOJA;
  if (eObjeto(loja)) nome = typeof loja.nome === 'string' ? loja.nome : '';
  const chegada = typeof paragem.chegada_prevista === 'string' ? paragem.chegada_prevista : null;
  return {
    id: paragem.id,
    numero: Number.isInteger(paragem.numero) ? paragem.numero : null,
    nome,
    fase: eObjeto(loja) && typeof loja.fase === 'string' ? loja.fase : null,
    motivo: paragem.motivo,
    rotuloMotivo: rotuloMotivo(paragem.motivo),
    tempo: paragem.tempo_servico_min,
    chegada,
    espera: Number.isInteger(paragem.espera_min) && paragem.espera_min > 0 ? paragem.espera_min : null,
    chegadaAntiga: chegada !== null && !horasAtuais,
    textoAviso: textoAviso(paragem.aviso),
    // Uma fechada neste dia que só está na rota por "Manter" (F3-UX-5): na secção "rota", ou na das que não cabem
    // (na das fechadas o "Manter" está desligado, por definição).
    mantida: paragem.manter_fechada === true && fechaNoDia(loja, dia),
    google: hrefNavegacao(paragem.links?.google),
    waze: hrefNavegacao(paragem.links?.waze),
    podeSubir,
    podeDescer,
    seccao: paragem.seccao,
  };
}

function seccoesDaVista(rota, podeMover) {
  const grupos = seccoesDaRota(rota);
  const ultima = grupos.rota.length - 1;
  const daRota = { horasAtuais: rota.calculo?.atual === true, dia: diaDaSemana(rota.data) };
  const linha = (p) => linhaDe(p, daRota);
  return {
    rota: grupos.rota.map((p, i) => linhaDe(p, { ...daRota, podeSubir: podeMover && i > 0, podeDescer: podeMover && i < ultima })),
    fechadas: grupos.fechadas.map(linha),
    naoCabem: grupos.naoCabem.map(linha),
    semLoja: grupos.semLoja.map(linha),
  };
}

// Os pinos das paragens: as que têm uma loja com coordenadas, pela ordem da rota (só as da secção "rota"
// têm número).
function paragensDoMapa(rota) {
  return paragensDe(rota)
    .filter((p) => comCoordenadas(p?.loja))
    .map((p) => ({
      id: p.id,
      numero: Number.isInteger(p.numero) ? p.numero : null,
      nome: typeof p.loja.nome === 'string' ? p.loja.nome : '',
      fase: typeof p.loja.fase === 'string' ? p.loja.fase : null,
      lat: p.loja.lat,
      lng: p.loja.lng,
      aviso: textoAviso(p.aviso),
      seccao: p.seccao,
    }));
}

// Os blocos "Abrir paragens X–Y no Google Maps", só com os links que passam no hrefNavegacao.
function blocosDaRota(rota) {
  const lista = Array.isArray(rota.blocos_google) ? rota.blocos_google : [];
  return lista
    .filter(eObjeto)
    .map((bloco) => ({ rotulo: bloco.rotulo, quantas: bloco.quantas, href: hrefNavegacao(bloco.href) }))
    .filter((bloco) => typeof bloco.href === 'string');
}

function limiteDaRota(rota) {
  const limite = Number.isInteger(rota.limite_paragens) && rota.limite_paragens > 0 ? rota.limite_paragens : LIMITE_PARAGENS;
  const ativas = paragensDe(rota).length;
  const cheia = ativas >= limite;
  return { cheia, texto: cheia ? `Uma rota tem no máximo ${limite} paragens.` : `${ativas} de ${limite} paragens` };
}

const ATRIBUICAO_ORS = Object.freeze({ aviso: TEXTO_ROTA_DE_TERCEIROS, texto: ATRIBUICOES.ors.texto, partes: ATRIBUICOES.ors.partes });

// --- Ecrã ----------------------------------------------------------------------------------------

// O temporizador do browser (lido a cada chamada: no Jest, o relógio falso troca-o).
const TEMPORIZADOR_DO_BROWSER = Object.freeze({
  agendar: (funcao, ms) => setTimeout(funcao, ms),
  cancelar: (id) => clearTimeout(id),
});

// O par de um estado da rota para o recálculo automático (correção "T3.32 / T3.38"): a versão e o
// `calculado_em` do cálculo gravado. O recálculo não muda a versão, e o servidor não manda a assinatura.
const parDe = (rota) => JSON.stringify([rota?.versao ?? null, rota?.calculo?.calculado_em ?? null]);

// criarPlaneador({api, rede, data, base, navegar, aoMudarVista, aoAvisar, temporizador})
//   → {vista, iniciar, tentarDeNovo, recarregar, voltarAsRotas, destruir,
//      adicionar, retirar, mover, subir, descer, mudarMotivo, mudarTempo, manter, naoManter, porNaRota,
//      mudarDefinicao, escolherPonto, tocarNoMapa, usarFabrica, escolherLoja, calcularMelhorOrdem, recalcularHoras,
//      guardar, responderGuardar, mapaDisponivel}
//  - api: o cliente do lib/crm/api.js (`obterRota`, `obterConfigMapa`, `listarLojas`, `obterSugestoes` e as
//    escritas `adicionarParagem`, `alterarRota`, `recalcularHoras`, `otimizarRota`, pela fila);
//    data: o `:data` da rota (`AAAA-MM-DD`);
//  - rede: o `criarEstadoRede(window, navigator)`; base: a casa do CRM (`/crm` ou `/admin/crm`);
//  - navegar(caminho, opcoes?): o `navigate` do React Router; aoMudarVista(vista); aoAvisar(texto): os toasts
//    ("Adicionada", "Retirada", "Rota guardada como planeada");
//  - temporizador: {agendar(funcao, ms) → id, cancelar(id)}, a espera das horas automáticas (por omissão o
//    `setTimeout` do browser).
// vista: {estado: 'a_carregar'|'falha'|'rota'|'data_invalida', titulo, somenteLeitura, textoLeitura,
//         rotuloEstado, falha: null | {mensagem, tentar, aTentar}, conflito: null | {mensagem, aRecarregar, erro},
//         semRede, definicoes: null | {hora_saida, hora_regresso_limite, inicio, fim, evitar_portagens, ativas,
//         mensagem, semMapa}, totais, horas: null | {atuais, texto}, avisos, seccoes: null | {rota, fechadas,
//         naoCabem, semLoja} (cada linha com `chegadaAntiga` e `mantida`), sugestoes: null | {estado, grupos (cada loja com `aAdicionar`), mensagem, tentar, aTentar},
//         mapa: {paragens, inicio, fim, linha, linhaAtual, lojasForaDaRota}, configuracao, falhaDoMapa,
//         acoes: null | {calcular, recalcular, guardar (com a `pergunta`)}, calculo: null | {aCalcular, mensagem},
//         blocosGoogle, atribuicaoOrs, limite: null | {cheia, texto}, escolherPonto: null | 'inicio' | 'fim',
//         lojaEscolhida: null | {id, nome, fase, motivo, rotuloMotivo, aAdicionar, ativo}, podeAdicionar,
//         alerta: null | {mensagem}, recarga: {aRecarregar, erro}, caminhoRotas}
//   — nova a cada mudança e congelada a fundo.
// Criar o ecrã não pede nada: `iniciar()` pede e ouve a rede.
export function criarPlaneador({
  api, rede, data, base, navegar, aoMudarVista, aoAvisar, temporizador = TEMPORIZADOR_DO_BROWSER,
}) {
  const dataValida = eDataValida(data);
  const caminhoRotas = `${base}/rotas`;
  let rota = null; // a rota como o servidor a mandou (a do GET, a do último Recarregar ou a da última gravação)
  let falha = null; // a rota não carregou: a mensagem
  let dataRecusada = dataValida ? null : MENSAGEM_DATA_INVALIDA; // "Dia inválido": a mensagem
  let aCarregar = false;
  let configuracao = null;
  let erroConfiguracao = null;
  let aCarregarConfiguracao = false;
  let lojas = null;
  let erroLojas = null;
  let aCarregarLojas = false;
  let sugestoes = null; // a resposta do servidor
  let erroSugestoes = null;
  let aCarregarSugestoes = false;
  let pedidoSugestoes = 0; // só conta a resposta do último pedido
  let aRecarregar = false;
  let erroRecarga = null;
  let iniciado = false;
  let ativo = true;
  let cancelarRede = () => {};

  // As gravações (T3.32).
  let fila = null; // criada com a primeira rota (a versão dela)
  let conflito = false; // um 409 `conflito`: a faixa, até ao Recarregar
  let bloqueio = null; // um 409 `rota_em_curso`/`rota_fechada`: a mensagem (só de leitura até ao Recarregar)
  let alerta = null; // a mensagem da última gravação recusada
  let erroCalculo = null; // a mensagem do último cálculo que falhou
  let falhou = false; // o último cálculo falhou: nada de horas automáticas até à próxima alteração ou ao botão
  let pontaAEscolher = null; // "Ponto no mapa": 'inicio' ou 'fim', à espera do toque
  let lojaEscolhida = null; // o cartão de uma loja esbatida: {id, nome, fase, motivo, rotuloMotivo}
  let perguntarGuardar = false;
  let comMapa = true; // há mapa onde tocar (a página diz quando não: `mapaDisponivel`)
  const aAdicionar = new Set(); // os `loja_id` a adicionar
  const paresTratados = new Set(); // os pares que já tiveram (ou já deram) um recálculo automático
  let esperaHoras = null; // a espera das horas automáticas (o id do temporizador)
  let respostasDaFila = 0; // quantas gravações deram certo (uma leitura que começou antes é mais velha)
  let sugestoesPorPedir = false; // uma gravação deu certo desde o último pedido das sugestões

  const memoLinha = criarMemo();
  const memoLojasFora = criarMemo();
  const memoMapa = criarMemo();

  const online = () => rede?.online() ?? true;

  // --- A vista ---

  // A rota que o ecrã mostra: a do servidor com as alterações ainda por confirmar por cima (a visão
  // otimista) e, depois de um 409 `rota_em_curso`/`rota_fechada`, só de leitura.
  function rotaDaVista() {
    if (rota === null) return null;
    const fabrica = configuracao?.centro ?? null;
    const otimista = fila.alteracoesPorConfirmar.reduce((r, corpo) => aplicarLocalmente(r, corpo, { fabrica }), rota);
    return bloqueio === null ? otimista : { ...otimista, editavel: false };
  }

  function linhaDoMapa(r) {
    const geometria = r?.calculo?.geometria;
    return memoLinha([geometria], () => (typeof geometria === 'string' ? congelarAFundo(descodificarPolilinha(geometria)) : SEM_LINHA));
  }

  function lojasForaDoMapa(r) {
    if (r === null || lojas === null) return null;
    const chave = JSON.stringify([...new Set(idsDasLojasNaRota(r))].sort());
    return memoLojasFora([lojas, chave], () => congelarAFundo(lojasForaDaRota(lojas, r)));
  }

  function mapaDaVista(r) {
    const paragens = r === null ? [] : paragensDoMapa(r);
    const inicio = r === null ? null : pontaDe(r.inicio);
    const fim = r === null ? null : pontaDe(r.fim);
    const linha = linhaDoMapa(r);
    const linhaAtual = r?.calculo?.atual === true;
    const fora = lojasForaDoMapa(r);
    const chave = JSON.stringify([paragens, inicio, fim]);
    return memoMapa([chave, linha, linhaAtual, fora], () => congelarAFundo({
      paragens, inicio, fim, linha, linhaAtual, lojasForaDaRota: fora,
    }));
  }

  // As lojas sugeridas com o "A adicionar…" de cada uma.
  function comAAdicionar(vistaSugestoes) {
    const grupos = vistaSugestoes.grupos.map((grupo) => ({
      ...grupo, lojas: grupo.lojas.map((loja) => ({ ...loja, aAdicionar: aAdicionar.has(loja.id) })),
    }));
    return { ...vistaSugestoes, grupos };
  }

  function sugestoesDaVista(r) {
    if (r === null || r.editavel !== true) return null;
    if (!temLojasNasParagens(r)) return vistaDasSugestoes({ sem_paragens: true }, []);
    if (sugestoes !== null) return comAAdicionar(vistaDasSugestoes(sugestoes, idsDasLojasNaRota(r)));
    if (erroSugestoes !== null) {
      return { estado: 'falha', grupos: [], mensagem: erroSugestoes, tentar: true, aTentar: aCarregarSugestoes };
    }
    return { estado: 'a_carregar', grupos: [], mensagem: TEXTO_SUGESTOES_A_CARREGAR, tentar: false, aTentar: false };
  }

  function falhaDoMapa() {
    const erro = erroConfiguracao ?? erroLojas;
    return erro === null ? null : { mensagem: erro, aTentar: aCarregarConfiguracao || aCarregarLojas };
  }

  // Os botões agora, com o que está na fila.
  function acoesAgora(r) {
    return acoesDaRota(r, {
      online: online(), conflito, aCalcular: fila.tem('otimizar'), aRecalcular: fila.tem('recalcular'),
    });
  }

  // O cartão da loja escolhida no mapa; sai quando a loja entra na rota.
  function lojaEscolhidaDaVista(r, podeAdicionar) {
    if (lojaEscolhida === null || r?.editavel !== true || idsDasLojasNaRota(r).includes(lojaEscolhida.id)) return null;
    const emCursoAqui = aAdicionar.has(lojaEscolhida.id);
    return { ...lojaEscolhida, aAdicionar: emCursoAqui, ativo: podeAdicionar && !emCursoAqui };
  }

  // O estado da rota: o do servidor; sem ele, "Sem rota" num dia que só se pode ver e "Ainda sem paragens" num
  // que ainda se pode planear.
  function estadoDaVista(r, semRotaSoLeitura) {
    if (semRotaSoLeitura) return TEXTO_SEM_ROTA;
    return rotuloEstado(r.estado_efetivo) ?? TEXTO_AINDA_SEM_PARAGENS;
  }

  function montarVista() {
    const r = rotaDaVista();
    let estado = 'a_carregar';
    if (dataRecusada !== null) estado = 'data_invalida';
    else if (r !== null) estado = 'rota';
    else if (falha !== null) estado = 'falha';
    const ligado = online();
    const comRota = estado === 'rota';
    const editavel = comRota && r.editavel === true;
    const podeMudar = editavel && ligado && !conflito;
    const limite = comRota ? limiteDaRota(r) : null;
    const podeAdicionar = podeMudar && !limite.cheia;
    // Um dia passado sem rota (F3-UX-3): nem estado de uma rota que não houve, nem as definições por omissão.
    const semRotaSoLeitura = comRota && !editavel && r.existe !== true;

    let falhaVista = null;
    if (estado === 'data_invalida') falhaVista = { mensagem: dataRecusada, tentar: false, aTentar: false };
    else if (estado === 'falha') falhaVista = { mensagem: falha, tentar: true, aTentar: aCarregar };

    let acoes = null;
    if (editavel) {
      acoes = acoesAgora(r);
      acoes.guardar.pergunta = perguntarGuardar ? perguntaGuardar(r) : null;
    }

    return congelarAFundo({
      estado,
      titulo: dataRecusada === null ? `Rota de ${rotuloDataLonga(data)}` : TITULO_DIA_INVALIDO,
      somenteLeitura: comRota && !editavel,
      textoLeitura: comRota ? (bloqueio ?? textoLeitura(r)) : null,
      rotuloEstado: comRota ? estadoDaVista(r, semRotaSoLeitura) : null,
      falha: falhaVista,
      conflito: conflito ? { mensagem: TEXTO_CONFLITO, aRecarregar, erro: erroRecarga } : null,
      semRede: !ligado,
      definicoes: comRota && !semRotaSoLeitura ? {
        hora_saida: r.hora_saida,
        hora_regresso_limite: r.hora_regresso_limite,
        inicio: pontaDasDefinicoes(r.inicio),
        fim: pontaDasDefinicoes(r.fim),
        evitar_portagens: r.evitar_portagens === true,
        ativas: r.existe === true && podeMudar,
        mensagem: editavel && r.existe !== true ? TEXTO_DEFINICOES_SEM_ROTA : null,
        semMapa: !comMapa,
      } : null,
      totais: comRota ? totaisDaRota(r) : null,
      horas: comRota ? {
        atuais: r.calculo?.atual === true,
        // "a recalcular" só com um recálculo (ou uma otimização) na fila (correção "T3.16 / T3.21 / T3.32").
        texto: textoDasHoras(r, { aRecalcular: fila.tem('recalcular') || fila.tem('otimizar') }),
      } : null,
      avisos: comRota ? avisosDaRota(r) : SEM_AVISOS,
      seccoes: comRota ? seccoesDaVista(r, podeMudar) : null,
      sugestoes: sugestoesDaVista(r),
      mapa: mapaDaVista(r),
      configuracao,
      falhaDoMapa: falhaDoMapa(),
      acoes,
      calculo: editavel ? {
        aCalcular: fila.tem('otimizar'),
        // Sem a chave, só "indisponível" (mesmo que um cálculo de antes tenha falhado com outra mensagem).
        mensagem: r.calculo_disponivel === true ? erroCalculo : MENSAGEM_SEM_CALCULO,
      } : null,
      blocosGoogle: comRota ? blocosDaRota(r) : SEM_AVISOS,
      atribuicaoOrs: comRota ? ATRIBUICAO_ORS : null,
      limite,
      // (A faixa só abre numa rota que já existe: `escolherPonto`.)
      escolherPonto: podeMudar ? pontaAEscolher : null,
      lojaEscolhida: lojaEscolhidaDaVista(r, podeAdicionar),
      podeAdicionar,
      alerta: alerta === null ? null : { mensagem: alerta },
      recarga: { aRecarregar, erro: erroRecarga },
      caminhoRotas,
    });
  }

  let vista = montarVista();

  function atualizar() {
    vista = montarVista();
    aoMudarVista?.(vista);
  }

  // --- Os pedidos ---

  // Uma paragem de uma loja que existe: só aí há sugestões a pedir (o `sem_paragens` do servidor).
  function temLojasNasParagens(lida) {
    return paragensDe(lida).some((p) => eObjeto(p?.loja));
  }

  // O 422 do servidor na `data` (por exemplo, a mais de um ano): o dia não serve, tentar outra vez não ajuda.
  function mensagemDaData(erro) {
    const mensagem = erro?.codigo === 'validacao' ? erro.campos?.data : null;
    return typeof mensagem === 'string' && mensagem !== '' ? mensagem : null;
  }

  // As sugestões da rota em vigor; só a resposta do último pedido conta. Sem nada a pedir (só de leitura, sem
  // paragens de lojas), as que havia e o pedido em curso deixam de contar.
  async function pedirSugestoes() {
    pedidoSugestoes += 1;
    const meu = pedidoSugestoes;
    if (rota.editavel !== true || !temLojasNasParagens(rota)) {
      sugestoes = null;
      erroSugestoes = null;
      aCarregarSugestoes = false;
      return;
    }
    aCarregarSugestoes = true;
    let resposta;
    try {
      resposta = await api.obterSugestoes(data);
    } catch (erro) {
      if (!ativo || meu !== pedidoSugestoes) return;
      aCarregarSugestoes = false;
      erroSugestoes = textoDoErro(erro);
      atualizar();
      return;
    }
    if (!ativo || meu !== pedidoSugestoes) return;
    aCarregarSugestoes = false;
    sugestoes = resposta;
    erroSugestoes = null;
    atualizar();
  }

  // --- As horas automáticas ---

  // Pode pedir as horas sozinho agora? A fila vazia e a andar, com rede, a rota a precisar delas (com a
  // chave, editável, com paragens na secção "rota", as horas velhas e sem um cálculo falhado) e um par novo.
  function horasAutomaticas() {
    return ativo && rota !== null && fila.vazia && !fila.parada && online()
      && precisaDeHoras(rota, { falhou }) && !paresTratados.has(parDe(rota));
  }

  // (Cancelar uma espera que já disparou, ou nenhuma, não faz nada.)
  function cancelarEspera() {
    temporizador.cancelar(esperaHoras);
    esperaHoras = null;
  }

  // ~1,5 s sem alterações e depois um só recálculo (correção "T3.32"): cada ação cancela a espera e cada
  // vez que a fila esvazia ela recomeça.
  function agendarHoras() {
    cancelarEspera();
    if (!horasAutomaticas()) return;
    esperaHoras = temporizador.agendar(() => {
      if (!horasAutomaticas()) return;
      paresTratados.add(parDe(rota));
      calcular('recalcular');
      atualizar();
    }, ESPERA_HORAS_MS);
  }

  // --- As gravações ---

  // Um 409 da rota inteira parou a fila (os pedidos à espera foram recusados com ele). Não há espera das
  // horas a cancelar: o pedido que parou saiu de uma ação (que a cancelou) ou da própria espera.
  function parar(erro) {
    pontaAEscolher = null;
    lojaEscolhida = null;
    perguntarGuardar = false;
    aAdicionar.clear();
    if (erro.codigo === 'conflito') conflito = true;
    else bloqueio = textoDoErro(erro);
  }

  // Quando a fila esvazia (e continua a andar): a espera das horas e, se alguma gravação deu certo, as
  // sugestões outra vez.
  function depoisDoPedido() {
    if (fila.vazia && !fila.parada) {
      agendarHoras();
      if (sugestoesPorPedir) {
        sugestoesPorPedir = false;
        pedirSugestoes();
      }
    }
    atualizar();
  }

  // Segue a promessa de um pedido da fila: a rota da resposta (a visão otimista assenta nela), ou o erro.
  // Todas as promessas da fila têm aqui o seu `catch`: numa paragem são todas recusadas com o mesmo erro.
  function seguir(promessa, { aoGravar, aoFalhar }) {
    promessa.then(
      (lida) => {
        if (!ativo) return;
        if (eObjeto(lida)) rota = lida;
        respostasDaFila += 1;
        sugestoesPorPedir = true;
        aoGravar?.(lida);
        depoisDoPedido();
      },
      (erro) => {
        if (!ativo) return;
        if (CODIGOS_QUE_PARAM.includes(erro?.codigo)) parar(erro);
        else aoFalhar(erro);
        depoisDoPedido();
      },
    );
  }

  const mostrarAlerta = (erro) => {
    alerta = mensagemDoErro(erro);
  };

  // Uma ação de quem planeia: a espera das horas recomeça depois dela, a mensagem anterior sai e as horas
  // automáticas voltam a poder tentar.
  function antesDeGravar() {
    cancelarEspera();
    alerta = null;
    falhou = false;
  }

  // Um PATCH pela fila (otimista: a vista mostra-o já).
  function alterar(corpo, aoGravar) {
    antesDeGravar();
    seguir(fila.alterar(corpo), { aoGravar, aoFalhar: mostrarAlerta });
    atualizar();
  }

  // O recalcular (as horas) ou o otimizar (a melhor ordem e as horas). A falha fica junto ao cálculo.
  function calcular(tipo) {
    erroCalculo = null;
    seguir(tipo === 'otimizar' ? fila.otimizar() : fila.recalcular(), {
      aoGravar: (lida) => {
        paresTratados.add(parDe(lida));
      },
      aoFalhar: (erro) => {
        erroCalculo = textoDoErro(erro);
        falhou = true;
      },
    });
  }

  // A rota (otimista) se agora se pode gravar nela: editável, com rede e sem conflito; senão null.
  function rotaParaGravar() {
    const r = rotaDaVista();
    return ativo && r !== null && r.editavel === true && online() && !conflito ? r : null;
  }

  // …e com as definições do dia: a rota já existe (o PATCH de uma rota virtual dá 404; correção
  // "T3.20 / T3.31 / T3.39").
  function rotaComDefinicoes() {
    const r = rotaParaGravar();
    return r !== null && r.existe === true ? r : null;
  }

  const temParagem = (r, id) => paragensDe(r).some((p) => p.id === id);
  const idsDaSeccaoRota = (r) => seccoesDaRota(r).rota.map((p) => p.id);

  // A secção "rota" com a paragem `de` na posição `para` (o `mover` do reordenar.js: fora da lista não mexe,
  // para lá das pontas encosta); sem nada a mudar, nada a gravar.
  function moverParagem(r, de, para) {
    const ids = idsDaSeccaoRota(r);
    const novos = moverNaLista(ids, de, para);
    if (novos.every((id, i) => id === ids[i])) return;
    alterar(corpoOrdem(r, novos));
  }

  // Subir (−1) ou descer (+1) uma posição; nas pontas, ou fora da secção "rota", o `moverParagem` não muda nada.
  function deslocar(id, passo) {
    const r = rotaParaGravar();
    if (r === null) return;
    const i = idsDaSeccaoRota(r).indexOf(id);
    moverParagem(r, i, i + passo);
  }

  function alterarParagem(id, campos) {
    const r = rotaParaGravar();
    if (r === null || !temParagem(r, id)) return;
    alterar({ paragens: { [id]: campos } });
  }

  function mudarDefinicao(chave, valor) {
    if (!DEFINICOES_DO_DIA.includes(chave) || valor === undefined) return;
    const r = rotaComDefinicoes();
    if (r === null) return;
    // As horas e as portagens com o valor que já têm: nada a gravar (o início e o fim são objetos: vão sempre).
    if (r[chave] === valor) return;
    alterar({ [chave]: valor });
  }

  function enviarGuardar() {
    alterar({ estado: 'planeada' }, () => aoAvisar?.(TEXTO_GUARDADA));
  }

  // A rota que chegou (do GET ou do Recarregar), e as sugestões dela. A fila nasce com a primeira; depois
  // retoma com a versão da rota lida, só vazia (parada também está vazia): com uma gravação a correr, a
  // versão é a da resposta dela.
  function aplicarRota(lida) {
    rota = lida;
    falha = null;
    const versao = eVersao(lida.versao) ? lida.versao : null;
    if (fila === null) fila = criarFilaRota({ enviar: enviarPelaApi(api, data), versao });
    else if (fila.vazia) fila.retomar(versao);
    pedirSugestoes();
    agendarHoras();
    atualizar();
  }

  // Os três pedidos do início. Quem chama decide quando (o `iniciar` uma vez, o `repetirFalhas` só o que
  // falhou e não está em curso).
  async function carregarRota() {
    aCarregar = true;
    let lida;
    try {
      lida = await api.obterRota(data);
    } catch (erro) {
      aCarregar = false;
      if (!ativo) return;
      const daData = mensagemDaData(erro);
      if (daData !== null) dataRecusada = daData;
      else falha = textoDoErro(erro);
      atualizar();
      return;
    }
    aCarregar = false;
    if (!ativo) return;
    if (!eObjeto(lida)) {
      falha = MENSAGEM_ERRO_INESPERADO;
      atualizar();
      return;
    }
    aplicarRota(lida);
  }

  async function carregarConfiguracao() {
    aCarregarConfiguracao = true;
    let lida;
    try {
      lida = await api.obterConfigMapa();
    } catch (erro) {
      aCarregarConfiguracao = false;
      if (!ativo) return;
      erroConfiguracao = textoDoErro(erro);
      atualizar();
      return;
    }
    aCarregarConfiguracao = false;
    if (!ativo) return;
    configuracao = congelarAFundo(lida ?? {});
    erroConfiguracao = null;
    atualizar();
  }

  async function carregarLojas() {
    aCarregarLojas = true;
    let lida;
    try {
      lida = await api.listarLojas();
    } catch (erro) {
      aCarregarLojas = false;
      if (!ativo) return;
      erroLojas = textoDoErro(erro);
      atualizar();
      return;
    }
    aCarregarLojas = false;
    if (!ativo) return;
    lojas = Array.isArray(lida) ? lida : [];
    erroLojas = null;
    atualizar();
  }

  // Volta a pedir só o que falhou (o "Tentar novamente" e a rede que volta); um toque, um pedido. Depois do
  // `iniciar`, o que não chegou e não está a ser pedido falhou.
  function repetirFalhas() {
    if (!ativo || !iniciado || dataRecusada !== null) return;
    let pediu = false;
    if (rota === null && !aCarregar) {
      carregarRota();
      pediu = true;
    }
    if (configuracao === null && !aCarregarConfiguracao) {
      carregarConfiguracao();
      pediu = true;
    }
    if (lojas === null && !aCarregarLojas) {
      carregarLojas();
      pediu = true;
    }
    if (rota !== null && erroSugestoes !== null && !aCarregarSugestoes) {
      pedirSugestoes();
      pediu = true;
    }
    if (pediu) atualizar();
  }

  // Volta a ler a rota (o "Recarregar" do conflito e do só de leitura): a que se tinha fica até chegar a nova.
  // Se uma gravação deu certo entretanto, a leitura é mais velha do que ela e não conta.
  async function recarregar() {
    if (!ativo || rota === null || aRecarregar) return;
    aRecarregar = true;
    erroRecarga = null;
    const marca = respostasDaFila;
    atualizar();
    let lida;
    try {
      lida = await api.obterRota(data);
    } catch (erro) {
      if (!ativo) return;
      aRecarregar = false;
      erroRecarga = textoDoErro(erro);
      atualizar();
      return;
    }
    if (!ativo) return;
    aRecarregar = false;
    if (!eObjeto(lida)) {
      erroRecarga = MENSAGEM_ERRO_INESPERADO;
      atualizar();
      return;
    }
    if (respostasDaFila !== marca) {
      atualizar();
      return;
    }
    conflito = false;
    bloqueio = null;
    alerta = null;
    erroCalculo = null;
    falhou = false;
    aplicarRota(lida);
  }

  return {
    get vista() {
      return vista;
    },
    iniciar() {
      if (!ativo || iniciado || dataRecusada !== null) return;
      iniciado = true;
      // Sem rede as ações desligam-se; quando volta, as horas automáticas voltam a esperar e o que falhou
      // pede-se outra vez. O `destruir` cancela-o.
      cancelarRede = rede?.aoMudar((ligado) => {
        atualizar();
        if (!ligado) return;
        agendarHoras();
        repetirFalhas();
      }) ?? (() => {});
      carregarRota();
      carregarConfiguracao();
      carregarLojas();
      atualizar();
    },
    // "Tentar novamente": a rota, a configuração do mapa, as lojas ou as sugestões que falharam.
    tentarDeNovo: repetirFalhas,
    recarregar,
    // "Dia inválido" → as Rotas da mesma casa.
    voltarAsRotas() {
      navegar?.(caminhoRotas);
    },
    destruir() {
      if (!ativo) return;
      ativo = false;
      cancelarRede();
      cancelarEspera();
    },

    // --- As ações (T3.32) ---

    // Uma loja à rota (das sugestões ou do cartão do mapa), com o motivo escolhido ou, sem ele, o da fase
    // (o servidor escolhe). Não é otimista: "A adicionar…" até à resposta.
    adicionar(lojaId, motivo) {
      if (typeof lojaId !== 'string' || lojaId === '' || aAdicionar.has(lojaId)) return;
      const r = rotaParaGravar();
      if (r === null || limiteDaRota(r).cheia || idsDasLojasNaRota(r).includes(lojaId)) return;
      antesDeGravar();
      aAdicionar.add(lojaId);
      seguir(fila.adicionar({ loja_id: lojaId, motivo }), {
        aoGravar: () => {
          aAdicionar.delete(lojaId);
          if (lojaEscolhida?.id === lojaId) lojaEscolhida = null;
          aoAvisar?.(TEXTO_ADICIONADA);
        },
        aoFalhar: (erro) => {
          aAdicionar.delete(lojaId);
          mostrarAlerta(erro);
        },
      });
      atualizar();
    },
    retirar(id) {
      const r = rotaParaGravar();
      if (r === null || !temParagem(r, id)) return;
      alterar({ retirar: [id] }, () => aoAvisar?.(TEXTO_RETIRADA));
    },
    // Arrastar na secção "rota": da posição `de` para a `para` (as posições da secção, a contar de 0).
    mover(de, para) {
      const r = rotaParaGravar();
      if (r !== null) moverParagem(r, de, para);
    },
    subir(id) {
      deslocar(id, -1);
    },
    descer(id) {
      deslocar(id, 1);
    },
    mudarMotivo(id, motivo) {
      alterarParagem(id, { motivo });
    },
    // O tempo de serviço em minutos; o texto de um campo só com algarismos vai como inteiro.
    mudarTempo(id, minutos) {
      const texto = typeof minutos === 'string' ? minutos.trim() : null;
      alterarParagem(id, { tempo_servico_min: texto !== null && /^\d+$/.test(texto) ? Number(texto) : minutos });
    },
    // "Manter" uma paragem fechada neste dia: entra no cálculo.
    manter(id) {
      alterarParagem(id, { manter_fechada: true });
    },
    // "Não manter" uma fechada mantida: volta às fechadas, fora do cálculo (F3-UX-5).
    naoManter(id) {
      alterarParagem(id, { manter_fechada: false });
    },
    // "Pôr na rota" uma que não cabe no horário.
    porNaRota(id) {
      alterarParagem(id, { nao_cabe: false });
    },
    mudarDefinicao,
    // "Ponto no mapa": a faixa "Toque no mapa no ponto de início/fim" (`null`: "Cancelar").
    escolherPonto(ponta) {
      if (ponta === null) {
        pontaAEscolher = null;
        atualizar();
        return;
      }
      if (!PONTAS.includes(ponta) || !comMapa || rotaComDefinicoes() === null) return;
      pontaAEscolher = ponta;
      lojaEscolhida = null;
      atualizar();
    },
    // Um toque no mapa (fora dos pinos): o ponto escolhido, ou fecha o cartão da loja.
    tocarNoMapa(ponto) {
      if (pontaAEscolher === null) {
        lojaEscolhida = null;
        atualizar();
        return;
      }
      if (!comCoordenadas(ponto) || rotaComDefinicoes() === null) return;
      const ponta = pontaAEscolher;
      pontaAEscolher = null;
      alterar({ [ponta]: { lat: ponto.lat, lng: ponto.lng } });
    },
    // "Fábrica" no início ou no fim.
    usarFabrica(ponta) {
      if (!PONTAS.includes(ponta)) return;
      const r = rotaComDefinicoes();
      if (r === null) return;
      if (pontaAEscolher === ponta) pontaAEscolher = null;
      if (r[ponta]?.fabrica === true) {
        atualizar();
        return;
      }
      alterar({ [ponta]: null });
    },
    // Um toque numa loja esbatida: o cartão pequeno "Adicionar à rota", com o motivo da fase (`null` fecha-o).
    escolherLoja(loja) {
      if (loja === null) {
        lojaEscolhida = null;
        atualizar();
        return;
      }
      if (!eObjeto(loja) || typeof loja.id !== 'string' || loja.id === '') return;
      const r = rotaDaVista();
      if (r?.editavel !== true || conflito || idsDasLojasNaRota(r).includes(loja.id)) return;
      const fase = temProprio(FASES, loja.fase) ? loja.fase : null;
      const motivo = motivoPorFase(fase);
      lojaEscolhida = { id: loja.id, nome: typeof loja.nome === 'string' ? loja.nome : '', fase, motivo, rotuloMotivo: rotuloMotivo(motivo) };
      pontaAEscolher = null;
      atualizar();
    },
    calcularMelhorOrdem() {
      const r = rotaParaGravar();
      if (r === null || !acoesAgora(r).calcular.ativo) return;
      antesDeGravar();
      calcular('otimizar');
      atualizar();
    },
    // O botão "Recalcular horas": logo, sem esperar.
    recalcularHoras() {
      const r = rotaParaGravar();
      if (r === null || !acoesAgora(r).recalcular.ativo) return;
      antesDeGravar();
      calcular('recalcular');
      atualizar();
    },
    // "Guardar rota": rascunho → planeada; com paragens que não cabem, primeiro a pergunta.
    guardar() {
      const r = rotaParaGravar();
      if (r === null || !acoesAgora(r).guardar.ativo) return;
      if (perguntaGuardar(r) === null) {
        enviarGuardar();
        return;
      }
      perguntarGuardar = true;
      atualizar();
    },
    // A página diz se há mapa onde tocar (só o `true` é "sim"). Sem ele, "Ponto no mapa" não abre e a escolha
    // que estava a meio cancela-se (F3-UX-6).
    mapaDisponivel(sim) {
      const agora = sim === true;
      if (!ativo || agora === comMapa) return;
      comMapa = agora;
      if (!comMapa) pontaAEscolher = null;
      atualizar();
    },
    // A resposta à pergunta do "Guardar rota" (o "sim" só grava se ainda se puder).
    responderGuardar(sim) {
      if (!perguntarGuardar) return;
      perguntarGuardar = false;
      const r = sim === true ? rotaParaGravar() : null;
      if (r !== null && acoesAgora(r).guardar.ativo) {
        enviarGuardar();
        return;
      }
      atualizar();
    },
  };
}
