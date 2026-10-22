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
// `recarregar()` volta a ler a rota (o "Recarregar" do conflito, T3.32) e `destruir()` faz que as respostas
// que chegarem depois já não façam nada. As ações, as horas automáticas e os conflitos são da T3.32.

import { MENSAGEM_ERRO_INESPERADO, MENSAGEM_SEM_REDE } from './api';
import { ATRIBUICOES, TEXTO_ROTA_DE_TERCEIROS } from './atribuicoes';
import { eDataValida, rotuloDataLonga } from './datas';
import { hrefNavegacao } from './dom';
import { textoDoErro } from './ecraMapa';
import { FASES } from './fases';
import { descodificarPolilinha } from './polilinha';
import {
  LIMITE_PARAGENS, avisosDaRota, rotuloEstado, rotuloMotivo, seccoesDaRota, textoAviso, textoDistancia, totaisDaRota,
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

// Os botões de uma rota editável: {calcular, recalcular, guardar}, cada um {texto, ativo, falta} (falta: porque
// está desligado, ou null; o guardar leva também a `pergunta`, da T3.32). Pela ordem dos motivos: sem rede;
// a rota ainda sem paragens ativas (a virtual também); depois os de cada ação.
export function acoesDaRota(rota, { online = false } = {}) {
  const { rota: naRota, naoCabem } = seccoesDaRota(rota);
  let geral = null;
  if (online !== true) geral = MENSAGEM_SEM_REDE;
  else if (rota?.existe !== true || paragensDe(rota).length === 0) geral = TEXTO_PRIMEIRA_PARAGEM;
  const semChave = rota?.calculo_disponivel === true ? null : MENSAGEM_SEM_CALCULO;

  // O VROOM leva a secção "rota" e as que não cabem (correção "T3.22 / §1"); as horas, só a secção "rota".
  const nadaParaOtimizar = naRota.length + naoCabem.length === 0 ? TEXTO_NADA_A_CALCULAR : null;
  let horas = null;
  if (naRota.length === 0) horas = TEXTO_NADA_A_CALCULAR;
  else if (rota.calculo?.atual === true) horas = TEXTO_HORAS_EM_DIA;
  const planeada = rota?.estado === 'rascunho' ? null : TEXTO_JA_PLANEADA;

  return {
    calcular: acao(TEXTO_CALCULAR, geral ?? semChave ?? nadaParaOtimizar),
    recalcular: acao(TEXTO_RECALCULAR, geral ?? semChave ?? horas),
    guardar: acao(TEXTO_GUARDAR_ROTA, geral ?? planeada, { pergunta: null }),
  };
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

// Uma linha da lista das paragens. Subir e descer só na secção "rota", e só se a rota se puder mudar agora.
function linhaDe(paragem, { podeSubir = false, podeDescer = false } = {}) {
  const { loja } = paragem;
  let nome = TEXTO_PARAGEM_SEM_LOJA;
  if (eObjeto(loja)) nome = typeof loja.nome === 'string' ? loja.nome : '';
  return {
    id: paragem.id,
    numero: Number.isInteger(paragem.numero) ? paragem.numero : null,
    nome,
    fase: eObjeto(loja) && typeof loja.fase === 'string' ? loja.fase : null,
    motivo: paragem.motivo,
    rotuloMotivo: rotuloMotivo(paragem.motivo),
    tempo: paragem.tempo_servico_min,
    chegada: typeof paragem.chegada_prevista === 'string' ? paragem.chegada_prevista : null,
    espera: Number.isInteger(paragem.espera_min) && paragem.espera_min > 0 ? paragem.espera_min : null,
    textoAviso: textoAviso(paragem.aviso),
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
  return {
    rota: grupos.rota.map((p, i) => linhaDe(p, { podeSubir: podeMover && i > 0, podeDescer: podeMover && i < ultima })),
    fechadas: grupos.fechadas.map((p) => linhaDe(p)),
    naoCabem: grupos.naoCabem.map((p) => linhaDe(p)),
    semLoja: grupos.semLoja.map((p) => linhaDe(p)),
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

// criarPlaneador({api, rede, data, base, navegar, aoMudarVista, aoAvisar})
//   → {vista, iniciar, tentarDeNovo, recarregar, voltarAsRotas, destruir}
//  - api: {obterRota, obterConfigMapa, listarLojas, obterSugestoes} do lib/crm/api.js (a T3.32 junta as
//    escritas); data: o `:data` da rota (`AAAA-MM-DD`);
//  - rede: o `criarEstadoRede(window, navigator)`; base: a casa do CRM (`/crm` ou `/admin/crm`);
//  - navegar(caminho, opcoes?): o `navigate` do React Router; aoMudarVista(vista); aoAvisar(texto, opcoes?):
//    os toasts das ações (T3.32).
// vista: {estado: 'a_carregar'|'falha'|'rota'|'data_invalida', titulo, somenteLeitura, textoLeitura,
//         rotuloEstado, falha: null | {mensagem, tentar, aTentar}, conflito (T3.32), semRede,
//         definicoes: null | {hora_saida, hora_regresso_limite, inicio, fim, evitar_portagens, ativas, mensagem},
//         totais, horas: null | {atuais, texto}, avisos, seccoes: null | {rota, fechadas, naoCabem, semLoja},
//         sugestoes: null | {estado, grupos, mensagem, tentar, aTentar},
//         mapa: {paragens, inicio, fim, linha, linhaAtual, lojasForaDaRota}, configuracao, falhaDoMapa,
//         acoes: null | {calcular, recalcular, guardar}, calculo: null | {aCalcular, mensagem}, blocosGoogle,
//         atribuicaoOrs, limite: null | {cheia, texto}, escolherPonto, lojaEscolhida (T3.32),
//         recarga: {aRecarregar, erro}, caminhoRotas}
//   — nova a cada mudança e congelada a fundo.
// Criar o ecrã não pede nada: `iniciar()` pede e ouve a rede.
export function criarPlaneador({ api, rede, data, base, navegar, aoMudarVista, aoAvisar }) {
  const dataValida = eDataValida(data);
  const caminhoRotas = `${base}/rotas`;
  let rota = null; // a rota como o servidor a mandou (a do GET, ou a do último Recarregar)
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

  const memoLinha = criarMemo();
  const memoLojasFora = criarMemo();
  const memoMapa = criarMemo();

  const online = () => rede?.online() ?? true;

  // --- A vista ---

  function linhaDoMapa() {
    const geometria = rota?.calculo?.geometria;
    return memoLinha([geometria], () => (typeof geometria === 'string' ? congelarAFundo(descodificarPolilinha(geometria)) : SEM_LINHA));
  }

  function lojasForaDoMapa() {
    if (rota === null || lojas === null) return null;
    const chave = JSON.stringify([...new Set(idsDasLojasNaRota(rota))].sort());
    return memoLojasFora([lojas, chave], () => congelarAFundo(lojasForaDaRota(lojas, rota)));
  }

  function mapaDaVista() {
    const paragens = rota === null ? [] : paragensDoMapa(rota);
    const inicio = rota === null ? null : pontaDe(rota.inicio);
    const fim = rota === null ? null : pontaDe(rota.fim);
    const linha = linhaDoMapa();
    const linhaAtual = rota?.calculo?.atual === true;
    const fora = lojasForaDoMapa();
    const chave = JSON.stringify([paragens, inicio, fim]);
    return memoMapa([chave, linha, linhaAtual, fora], () => congelarAFundo({
      paragens, inicio, fim, linha, linhaAtual, lojasForaDaRota: fora,
    }));
  }

  function sugestoesDaVista() {
    if (rota === null || rota.editavel !== true) return null;
    if (!temLojasNasParagens(rota)) return vistaDasSugestoes({ sem_paragens: true }, []);
    if (sugestoes !== null) return vistaDasSugestoes(sugestoes, idsDasLojasNaRota(rota));
    if (erroSugestoes !== null) {
      return { estado: 'falha', grupos: [], mensagem: erroSugestoes, tentar: true, aTentar: aCarregarSugestoes };
    }
    return { estado: 'a_carregar', grupos: [], mensagem: TEXTO_SUGESTOES_A_CARREGAR, tentar: false, aTentar: false };
  }

  function falhaDoMapa() {
    const erro = erroConfiguracao ?? erroLojas;
    return erro === null ? null : { mensagem: erro, aTentar: aCarregarConfiguracao || aCarregarLojas };
  }

  function montarVista() {
    let estado = 'a_carregar';
    if (dataRecusada !== null) estado = 'data_invalida';
    else if (rota !== null) estado = 'rota';
    else if (falha !== null) estado = 'falha';
    const ligado = online();
    const comRota = estado === 'rota';
    const editavel = comRota && rota.editavel === true;
    const podeMudar = editavel && ligado;

    let falhaVista = null;
    if (estado === 'data_invalida') falhaVista = { mensagem: dataRecusada, tentar: false, aTentar: false };
    else if (estado === 'falha') falhaVista = { mensagem: falha, tentar: true, aTentar: aCarregar };

    return congelarAFundo({
      estado,
      titulo: dataRecusada === null ? `Rota de ${rotuloDataLonga(data)}` : TITULO_DIA_INVALIDO,
      somenteLeitura: comRota && !editavel,
      textoLeitura: comRota ? textoLeitura(rota) : null,
      rotuloEstado: comRota ? (rotuloEstado(rota.estado_efetivo) ?? TEXTO_AINDA_SEM_PARAGENS) : null,
      falha: falhaVista,
      conflito: null,
      semRede: !ligado,
      definicoes: comRota ? {
        hora_saida: rota.hora_saida,
        hora_regresso_limite: rota.hora_regresso_limite,
        inicio: pontaDasDefinicoes(rota.inicio),
        fim: pontaDasDefinicoes(rota.fim),
        evitar_portagens: rota.evitar_portagens === true,
        ativas: rota.existe === true && podeMudar,
        mensagem: editavel && rota.existe !== true ? TEXTO_DEFINICOES_SEM_ROTA : null,
      } : null,
      totais: comRota ? totaisDaRota(rota) : null,
      horas: comRota ? { atuais: rota.calculo?.atual === true, texto: textoDasHoras(rota) } : null,
      avisos: comRota ? avisosDaRota(rota) : SEM_AVISOS,
      seccoes: comRota ? seccoesDaVista(rota, podeMudar) : null,
      sugestoes: comRota ? sugestoesDaVista() : null,
      mapa: mapaDaVista(),
      configuracao,
      falhaDoMapa: falhaDoMapa(),
      acoes: editavel ? acoesDaRota(rota, { online: ligado }) : null,
      calculo: editavel ? { aCalcular: false, mensagem: rota.calculo_disponivel === true ? null : MENSAGEM_SEM_CALCULO } : null,
      blocosGoogle: comRota ? blocosDaRota(rota) : SEM_AVISOS,
      atribuicaoOrs: comRota ? ATRIBUICAO_ORS : null,
      limite: comRota ? limiteDaRota(rota) : null,
      escolherPonto: null,
      lojaEscolhida: null,
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

  // A rota que chegou (do GET ou do Recarregar), e as sugestões dela.
  function aplicarRota(lida) {
    rota = lida;
    falha = null;
    pedirSugestoes();
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

  async function recarregar() {
    if (!ativo || rota === null || aRecarregar) return;
    aRecarregar = true;
    erroRecarga = null;
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
    aplicarRota(lida);
  }

  return {
    get vista() {
      return vista;
    },
    iniciar() {
      if (!ativo || iniciado || dataRecusada !== null) return;
      iniciado = true;
      // Sem rede as ações desligam-se; quando volta, o que falhou pede-se outra vez. O `destruir` cancela-o.
      cancelarRede = rede?.aoMudar((ligado) => {
        atualizar();
        if (ligado) repetirFalhas();
      }) ?? (() => {});
      carregarRota();
      carregarConfiguracao();
      carregarLojas();
      atualizar();
    },
    // "Tentar novamente": a rota, a configuração do mapa, as lojas ou as sugestões que falharam.
    tentarDeNovo: repetirFalhas,
    // Volta a ler a rota (o "Recarregar"); a que se tinha fica até chegar a nova.
    recarregar,
    // "Dia inválido" → as Rotas da mesma casa.
    voltarAsRotas() {
      navegar?.(caminhoRotas);
    },
    destruir() {
      if (!ativo) return;
      ativo = false;
      cancelarRede();
    },
  };
}
