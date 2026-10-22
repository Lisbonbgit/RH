// O painel do planeador da rota (plano F3 T3.38), sem DOM: o que a página `pages/crm/CrmRota.js` e o
// `components/crm/ResumoRota.js` desenham a partir da `vista` do planeador (`lib/crm/planeador.js`).
//  - `seccoesDoPainel(vista.seccoes)`: as listas das paragens, pela ordem "Rota" (a única que se arrasta),
//    "⚠️ Fechadas neste dia" (com "Manter"), "⚠️ Não cabem no horário" (com "Pôr na rota") e "Lojas
//    apagadas" (só "Retirar"); só as que têm paragens;
//  - `totaisDoResumo(vista.totais)`: a distância, a condução e o regresso previsto (com o aviso quando passa
//    do limite), `antigos` quando as horas não são as atuais (o ecrã esbate-os);
//  - `botoesDoResumo(vista.acoes, vista.calculo)`: "Calcular melhor ordem", "Recalcular horas" e "Guardar
//    rota", cada um desligado com o motivo; os motivos iguais escrevem-se uma vez (sem rede, os três dizem o
//    mesmo) e cada botão aponta para o seu (`motivo`, a posição em `motivos`: o `aria-describedby`). A
//    mensagem do último cálculo que falhou só aparece se não repetir um motivo (sem a chave do
//    openrouteservice é a mesma do "Calcular").
// E, para a T3.39 (`components/crm/DefinicoesDoDia.js`, `components/crm/SugestoesRota.js`):
//  - `definicoesDoPainel(vista.definicoes, vista.escolherPonto)`: as duas horas, o início e o fim ("Fábrica"
//    ou "Ponto no mapa", e qual está à espera do toque no mapa), "Evitar portagens", se se podem mudar (numa
//    rota virtual não: a mensagem do planeador) e o resumo de uma linha ("Saída 08:00 · Regresso até 19:00 ·
//    Início e fim: Fábrica");
//  - `faixaDoPonto(vista.escolherPonto)`: a faixa "Toque no mapa no ponto de início/fim", com "Cancelar";
//  - `sugestoesDoPainel(vista.sugestoes, vista.podeAdicionar)`: os grupos da vista, cada loja com a distância
//    e o botão "Adicionar" ("A adicionar…" com o pedido a correr; desligado quando a rota não aceita mais);
//  - `cartaoDaLoja(vista.lojaEscolhida)`: o cartão pequeno de uma loja esbatida tocada no mapa (o nome, a
//    fase, o motivo que o planeador escolheu pela fase e "Adicionar à rota").
// Tudo sai congelado. Os textos são da página; os da rota (estado, avisos, horas) vêm já na `vista`.

import { FASES } from './fases';
import {
  TEXTOS_ESCOLHER_PONTO, TEXTO_A_ADICIONAR, TEXTO_FABRICA, TEXTO_PONTO_NO_MAPA,
} from './planeador';

export const TITULO_PAINEL = 'Painel da rota';
export const TITULO_RESUMO = 'Resumo da rota';
export const TITULO_BLOCOS_GOOGLE = 'Navegação no Google Maps';
// O bloco próprio da atribuição do openrouteservice, no fim do painel (nunca sobre o mapa).
export const TITULO_ATRIBUICAO_ORS = 'Cálculo das rotas';
export const TEXTO_ROTAS = 'Rotas';
export const TEXTO_VOLTAR_AS_ROTAS = 'Voltar às Rotas';
export const TEXTO_TENTAR_DE_NOVO = 'Tentar novamente';
export const TEXTO_RECARREGAR = 'Recarregar';
export const TEXTO_A_RECARREGAR = 'A recarregar…';
// A pergunta do "Guardar rota" com paragens que não cabem (`vista.acoes.guardar.pergunta`).
export const TEXTO_GUARDAR_MESMO_ASSIM = 'Guardar mesmo assim';
// O que acontece às que não cabem (§1 "Não cabem": no fim da lista e sem hora).
export const TEXTO_GUARDAR_NAO_CABEM = 'As que não cabem ficam no fim da rota, sem hora prevista.';
export const TEXTO_CANCELAR = 'Cancelar';

// As definições do dia (T3.39).
export const TITULO_DEFINICOES = 'Definições do dia';
export const ROTULOS_HORAS = Object.freeze({ hora_saida: 'Hora de saída', hora_regresso_limite: 'Hora limite de regresso' });
export const ROTULOS_PONTAS = Object.freeze({ inicio: 'Início', fim: 'Fim' });
export const TEXTO_EVITAR_PORTAGENS = 'Evitar portagens';
// O desenho original §7.2: a otimização (o VROOM) não evita portagens; as horas e a linha vêm do Directions,
// que as evita.
export const TEXTO_NOTA_PORTAGENS = 'A melhor ordem escolhe-se com portagens; as horas e a linha evitam-nas.';

// As sugestões e o cartão de uma loja esbatida (T3.39).
export const TITULO_SUGESTOES = 'Sugestões perto da rota';
export const TEXTO_ADICIONAR = 'Adicionar';
export const TEXTO_ADICIONAR_A_ROTA = 'Adicionar à rota';
export const TEXTO_FECHAR = 'Fechar';

export const TITULOS_SECCOES = Object.freeze({
  rota: 'Rota',
  fechadas: '⚠️ Fechadas neste dia',
  naoCabem: '⚠️ Não cabem no horário',
  semLoja: 'Lojas apagadas',
});

export const ROTULOS_TOTAIS = Object.freeze({ distancia: 'Distância', duracao: 'Condução', regresso: 'Regresso previsto' });

const ORDEM_SECCOES = Object.freeze(['rota', 'fechadas', 'naoCabem', 'semLoja']);
const ORDEM_TOTAIS = Object.freeze(['distancia', 'duracao', 'regresso']);
const ORDEM_BOTOES = Object.freeze(['calcular', 'recalcular', 'guardar']);
const ORDEM_HORAS = Object.freeze(['hora_saida', 'hora_regresso_limite']);
const ORDEM_PONTAS = Object.freeze(['inicio', 'fim']);

const eObjeto = (valor) => valor !== null && typeof valor === 'object' && !Array.isArray(valor);
const eTexto = (valor) => typeof valor === 'string' && valor !== '';
const temProprio = (objeto, chave) => Object.prototype.hasOwnProperty.call(objeto, chave);
const textoOuVazio = (valor) => (typeof valor === 'string' ? valor : '');

function congelarAFundo(valor) {
  if (valor !== null && typeof valor === 'object') {
    Object.values(valor).forEach(congelarAFundo);
    Object.freeze(valor);
  }
  return valor;
}

// As listas das paragens do painel: [{chave, titulo, linhas, arrastavel, comManter, comPorNaRota}]. As
// `linhas` são as da vista (a mesma lista); as de cada linha não se congelam aqui (já vêm congeladas).
export function seccoesDoPainel(seccoes) {
  const lista = ORDEM_SECCOES
    .filter((chave) => Array.isArray(seccoes?.[chave]) && seccoes[chave].length > 0)
    .map((chave) => Object.freeze({
      chave,
      titulo: TITULOS_SECCOES[chave],
      linhas: seccoes[chave],
      arrastavel: chave === 'rota',
      comManter: chave === 'fechadas',
      comPorNaRota: chave === 'naoCabem',
    }));
  return Object.freeze(lista);
}

// Os totais do último cálculo (`vista.totais`, o `totaisDaRota`): {itens: [{chave, rotulo, valor, aviso}],
// antigos}, ou null sem nada para mostrar.
export function totaisDoResumo(totais) {
  const itens = ORDEM_TOTAIS
    .filter((chave) => eTexto(totais?.[chave]))
    .map((chave) => ({
      chave,
      rotulo: ROTULOS_TOTAIS[chave],
      valor: totais[chave],
      aviso: chave === 'regresso' && totais.regressoTarde === true,
    }));
  if (itens.length === 0) return null;
  return congelarAFundo({ itens, antigos: totais.atual !== true });
}

// Os botões das ações (`vista.acoes`, o `acoesDaRota`) e a mensagem do último cálculo (`vista.calculo`):
// {botoes: [{chave, texto, ativo, motivo}], motivos: [texto], mensagem}, ou null sem ações (só de leitura).
export function botoesDoResumo(acoes, calculo) {
  if (!eObjeto(acoes)) return null;
  const motivos = [];
  const botoes = ORDEM_BOTOES
    .filter((chave) => eObjeto(acoes[chave]))
    .map((chave) => {
      const { texto, ativo, falta } = acoes[chave];
      const ligado = ativo === true;
      let motivo = null;
      if (!ligado && eTexto(falta)) {
        if (!motivos.includes(falta)) motivos.push(falta);
        motivo = motivos.indexOf(falta);
      }
      return { chave, texto, ativo: ligado, motivo };
    });
  const mensagem = eTexto(calculo?.mensagem) && !motivos.includes(calculo.mensagem) ? calculo.mensagem : null;
  return congelarAFundo({ botoes, motivos, mensagem });
}

// --- As definições do dia (T3.39) ----------------------------------------------------------------

// Uma ponta (início ou fim) da `vista.definicoes`: {lat, lng, fabrica, …} ou null (estragada). O texto é o dos
// botões: "Fábrica" (só com `fabrica: true`) ou "Ponto no mapa".
function pontaDoPainel(chave, ponta, escolherPonto) {
  const comPonta = eObjeto(ponta);
  const fabrica = comPonta && ponta.fabrica === true;
  let texto = null;
  if (comPonta) texto = fabrica ? TEXTO_FABRICA : TEXTO_PONTO_NO_MAPA;
  return {
    chave,
    rotulo: ROTULOS_PONTAS[chave],
    texto,
    fabrica,
    noMapa: comPonta && !fabrica,
    aEscolher: escolherPonto === chave,
  };
}

// "Saída 08:00 · Regresso até 19:00 · Início e fim: Fábrica · Sem portagens", só com o que existe.
function resumoDasDefinicoes(horas, pontas, evitarPortagens) {
  const [saida, regresso] = horas;
  const [inicio, fim] = pontas;
  const partes = [];
  if (saida.valor !== '') partes.push(`Saída ${saida.valor}`);
  if (regresso.valor !== '') partes.push(`Regresso até ${regresso.valor}`);
  if (inicio.texto !== null && inicio.texto === fim.texto) {
    partes.push(`${inicio.rotulo} e ${fim.rotulo.toLowerCase()}: ${inicio.texto}`);
  } else {
    for (const ponta of pontas) if (ponta.texto !== null) partes.push(`${ponta.rotulo}: ${ponta.texto}`);
  }
  if (evitarPortagens) partes.push('Sem portagens');
  return partes.join(' · ');
}

// As definições do dia no painel: {resumo, horas: [{chave, rotulo, valor}], pontas: [{chave, rotulo, texto,
// fabrica, noMapa, aEscolher}], evitarPortagens, ativas, mensagem}, ou null sem definições (sem a rota).
// `escolherPonto` é o da vista: a ponta que está à espera do toque no mapa.
export function definicoesDoPainel(definicoes, escolherPonto) {
  if (!eObjeto(definicoes)) return null;
  const horas = ORDEM_HORAS.map((chave) => ({ chave, rotulo: ROTULOS_HORAS[chave], valor: textoOuVazio(definicoes[chave]) }));
  const pontas = ORDEM_PONTAS.map((chave) => pontaDoPainel(chave, definicoes[chave], escolherPonto));
  const evitarPortagens = definicoes.evitar_portagens === true;
  return congelarAFundo({
    resumo: resumoDasDefinicoes(horas, pontas, evitarPortagens),
    horas,
    pontas,
    evitarPortagens,
    ativas: definicoes.ativas === true,
    mensagem: eTexto(definicoes.mensagem) ? definicoes.mensagem : null,
  });
}

// A faixa do "Ponto no mapa": {ponta, texto} ("Toque no mapa no ponto de início"), ou null.
export function faixaDoPonto(escolherPonto) {
  if (!temProprio(TEXTOS_ESCOLHER_PONTO, escolherPonto)) return null;
  return Object.freeze({ ponta: escolherPonto, texto: TEXTOS_ESCOLHER_PONTO[escolherPonto] });
}

// --- As sugestões e o cartão (T3.39) -------------------------------------------------------------

function lojaSugerida(loja, podeAdicionar) {
  const nome = textoOuVazio(loja.nome);
  const aAdicionar = loja.aAdicionar === true;
  const texto = aAdicionar ? TEXTO_A_ADICIONAR : TEXTO_ADICIONAR;
  return {
    id: loja.id,
    nome,
    distancia: eTexto(loja.distancia) ? loja.distancia : null,
    noCaminho: loja.noCaminho === true,
    botao: { texto, ativo: podeAdicionar && !aAdicionar, rotulo: nome === '' ? texto : `${texto}: ${nome}` },
  };
}

// As sugestões no painel (`vista.sugestoes` com o `vista.podeAdicionar`): {titulo, estado, mensagem, tentar,
// aTentar, grupos: [{fase, titulo, textoMais, lojas: [{id, nome, distancia, noCaminho, botao: {texto, ativo,
// rotulo}}]}]}, ou null sem sugestões (só de leitura).
export function sugestoesDoPainel(sugestoes, podeAdicionar) {
  if (!eObjeto(sugestoes)) return null;
  const pode = podeAdicionar === true;
  const grupos = (Array.isArray(sugestoes.grupos) ? sugestoes.grupos : [])
    .filter(eObjeto)
    .map((grupo) => ({
      fase: grupo.fase,
      titulo: grupo.titulo,
      textoMais: eTexto(grupo.textoMais) ? grupo.textoMais : null,
      lojas: (Array.isArray(grupo.lojas) ? grupo.lojas : []).filter(eObjeto).map((loja) => lojaSugerida(loja, pode)),
    }));
  return congelarAFundo({
    titulo: TITULO_SUGESTOES,
    estado: sugestoes.estado,
    mensagem: eTexto(sugestoes.mensagem) ? sugestoes.mensagem : null,
    tentar: sugestoes.tentar === true,
    aTentar: sugestoes.aTentar === true,
    grupos,
  });
}

// O cartão pequeno da loja esbatida tocada no mapa (`vista.lojaEscolhida`): {id, nome, fase, rotuloFase,
// motivo, textoMotivo ("Motivo: Amostra"), botao: {texto, ativo}}, ou null.
export function cartaoDaLoja(loja) {
  if (!eTexto(loja?.id)) return null;
  const fase = temProprio(FASES, loja.fase) ? loja.fase : null;
  return congelarAFundo({
    id: loja.id,
    nome: textoOuVazio(loja.nome),
    fase,
    rotuloFase: fase === null ? null : FASES[fase].rotulo,
    motivo: eTexto(loja.motivo) ? loja.motivo : null,
    textoMotivo: eTexto(loja.rotuloMotivo) ? `Motivo: ${loja.rotuloMotivo}` : null,
    botao: { texto: loja.aAdicionar === true ? TEXTO_A_ADICIONAR : TEXTO_ADICIONAR_A_ROTA, ativo: loja.ativo === true },
  });
}
