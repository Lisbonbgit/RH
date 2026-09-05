// Chamadas do módulo Plataformas (Painel → Plataformas): o relatório de
// segunda-feira da Uber Eats, da Bolt Food e da Glovo.
//
// Cliente próprio com TECTO DE ESPERA, pela mesma razão escrita no
// `lib/faturacao.js`: não há `axios.defaults.timeout` neste repositório, e um
// pedido pendurado deixa o ecrã no estado inicial — sem erro, sem spinner que
// acabe, e sem nada que diga a quem está a olhar que a resposta nunca chegou.
import axios from 'axios';

import { detalhesErro } from './faturacao';

const API_URL = process.env.REACT_APP_BACKEND_URL + '/api/plataformas';

// 30 s para tudo o que só fala com o Mongo (ler as definições, o relatório do
// ecrã, o histórico) — o mesmo tecto do resto do backoffice.
export const TIMEOUT_BACKOFFICE_MS = 30000;

// 5 minutos para o que vai à CAIXA DE EMAIL. «Recolher agora» liga-se ao IMAP,
// percorre até 400 mensagens de cada caixa e manda cada relatório encontrado à
// IA — uma dessas chamadas pode sozinha demorar dois minutos, e são várias.
// Erra-se por excesso de propósito: desistir a meio não cancela nada do outro
// lado (o que já foi lido fica gravado), só tira o ecrã de cima da operação.
export const TIMEOUT_RECOLHA_MS = 300000;

const api = axios.create({ timeout: TIMEOUT_BACKOFFICE_MS });

// O JWT lido A CADA PEDIDO e não copiado na criação — ver o comentário gémeo
// no `lib/faturacao.js`. Este módulo é importado muito antes do login.
api.interceptors.request.use((config) => {
  const autorizacao = axios.defaults.headers.common.Authorization;
  config.headers = config.headers || {};
  if (autorizacao) config.headers.Authorization = autorizacao;
  return config;
});

export { detalhesErro };

// Quem recebe o email, e se o envio automático está ligado.
export const getDefinicoesPlataformas = () => api.get(`${API_URL}/definicoes`);
export const gravarDefinicoesPlataformas = (dados) =>
  api.put(`${API_URL}/definicoes`, dados);

// O relatório de hoje a partir do que JÁ está guardado. **Não vai à caixa de
// email**: abrir o ecrã não pode custar uma leitura IMAP e uma factura da IA.
export const getRelatorioPlataformas = () => api.get(`${API_URL}/relatorio`);

// As semanas e quinzenas já lidas, das mais recentes para as mais antigas.
export const getHistoricoPlataformas = (limite = 60) =>
  api.get(`${API_URL}/historico`, { params: { limite } });

// Ler a caixa agora, sem enviar email nenhum.
export const recolherPlataformasAgora = () =>
  api.post(`${API_URL}/recolher-agora`, null, { timeout: TIMEOUT_RECOLHA_MS });

// Enviar o email agora. `para` manda-o só para um endereço (o "envia-me isso
// para eu ver"); `recolher` lê a caixa antes, e por isso leva o tecto largo.
export const enviarPlataformasAgora = ({ para, recolher } = {}) =>
  api.post(`${API_URL}/enviar-agora`, { para: para || null, recolher: !!recolher },
    { timeout: recolher ? TIMEOUT_RECOLHA_MS : TIMEOUT_BACKOFFICE_MS });

// --- Como se escrevem estes números no ecrã ---------------------------------

const MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun',
  'jul', 'ago', 'set', 'out', 'nov', 'dez'];

/**
 * `1 234,56 €` — e **um travessão quando o valor não é conhecido**.
 *
 * O `eur()` do `lib/finance.js` faz `Number(n) || 0`, por isso um `null`
 * sai dele como `0,00 €`. É precisamente a mentira que o backend deste
 * módulo se dá ao trabalho de não contar: uma plataforma que não mandou
 * relatório fica com os valores a `null`, e «0,00 €» lê-se como «não
 * vendemos nada» em vez de «não sabemos».
 */
export const euros = (n) => (n === null || n === undefined
  ? '—'
  : (Number(n) || 0).toLocaleString('pt-PT', { style: 'currency', currency: 'EUR' }));

/** `2026-08-24` -> `24 ago`. */
export const diaCurto = (iso) => {
  const texto = String(iso || '');
  if (texto.length < 10) return texto;
  const mes = MESES[Number(texto.slice(5, 7)) - 1];
  if (!mes) return texto;
  return `${Number(texto.slice(8, 10))} ${mes}`;
};

/**
 * `24 a 30 ago`, e `31 ago a 6 set` quando o período atravessa dois meses —
 * «31 a 6 set» lê-se como se fosse tudo em Setembro.
 */
export const intervalo = (inicio, fim) => (
  String(inicio || '').slice(0, 7) === String(fim || '').slice(0, 7)
    ? `${diaCurto(inicio).split(' ')[0]} a ${diaCurto(fim)}`
    : `${diaCurto(inicio)} a ${diaCurto(fim)}`);

/**
 * Quando entra o dinheiro, por extenso. `sabido: false` (o relatório não
 * chegou) nunca diz «pago»: a data é do calendário, mas o valor é
 * desconhecido, e «pago hoje» ao lado de «não recebido» lê-se como se alguma
 * coisa tivesse entrado.
 */
export const quandoPaga = (periodo, sabido = true) => {
  if (!periodo) return '';
  const quando = diaCurto(periodo.pagamento);
  const dias = periodo.dias_para_pagamento;
  if (!sabido) return `Pagamento previsto para ${dias === 0 ? `hoje (${quando})` : quando}`;
  if (dias === 0) return `Pago hoje (${quando})`;
  if (dias < 0) return `Devia ter entrado a ${quando}`;
  return `Entra a ${quando} · ${dias === 1 ? 'falta 1 dia' : `faltam ${dias} dias`}`;
};
