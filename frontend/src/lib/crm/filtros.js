// Filtros do mapa: fases (por omissão todas, incluindo perdida — desenho
// original §4.1/§6.1) e região ('todas' | 'sem' | uuid). O armazenamento
// (o localStorage) é recebido por parâmetro.
//
// Porta de public/assets/js/filtros.js do CRM autónomo, com a adaptação dos
// ids (plano T2.21): a região é um uuid em texto (ids.js), e não um inteiro
// positivo; o id numérico do autónomo volta a 'todas'. A chave passa de
// `phc.filtros` a `crm.filtros`.
//
// No fim, as regras puras do componente dos filtros do autónomo
// (componentes/filtros-mapa.js): as opções da região, a região guardada que
// já não existe e os "filtros ativos". O FiltrosMapa (T2.25) só as chama.

import { ORDEM } from './fases';
import { eUuid } from './ids';

export const CHAVE_FILTROS = 'crm.filtros';

// Uma região guardada, enquanto a lista de regiões não chega.
export const TEXTO_REGIAO_GUARDADA = 'Região guardada';

export function filtrosPadrao() {
  return { fases: new Set(ORDEM), regiao: 'todas' };
}

function normalizarRegiao(regiao) {
  if (regiao === 'todas' || regiao === 'sem') return regiao;
  if (eUuid(regiao)) return regiao;
  return 'todas';
}

function normalizarFases(fases) {
  if (!(fases instanceof Set) && !Array.isArray(fases)) return new Set(ORDEM);
  const lista = [...fases];
  if (lista.length === 0) return new Set();
  const validas = ORDEM.filter((f) => lista.includes(f));
  return new Set(validas.length > 0 ? validas : ORDEM);
}

const ehObjeto = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

export function normalizarFiltros(dados) {
  if (!ehObjeto(dados)) return filtrosPadrao();
  return { fases: normalizarFases(dados.fases), regiao: normalizarRegiao(dados.regiao) };
}

// Usa a mesma normalização de guardar/carregar, para o mapa mostrar o mesmo
// antes e depois de recarregar (e nunca lançar erro com filtros inválidos).
// O regiao_id da loja compara-se tal e qual; uma loja com um regiao_id órfão
// (região apagada entretanto) só aparece em 'todas'.
export function aplicarFiltros(lojas, filtros) {
  const { fases, regiao } = normalizarFiltros(filtros ?? {});
  return lojas.filter((loja) => {
    if (!fases.has(loja.fase)) return false;
    if (regiao === 'todas') return true;
    if (regiao === 'sem') return loja.regiao_id == null;
    return loja.regiao_id === regiao;
  });
}

export function carregarFiltros(storage) {
  try {
    const texto = storage.getItem(CHAVE_FILTROS);
    if (texto == null) return filtrosPadrao();
    return normalizarFiltros(JSON.parse(texto));
  } catch {
    return filtrosPadrao();
  }
}

export function guardarFiltros(storage, filtros) {
  try {
    const f = normalizarFiltros(filtros);
    storage.setItem(CHAVE_FILTROS, JSON.stringify({ fases: [...f.fases], regiao: f.regiao }));
    return true;
  } catch {
    return false;
  }
}

export function textoNumeroLojas(n) {
  return n === 1 ? '1 loja' : `${n} lojas`;
}

// --- Regras do componente dos filtros (filtros-mapa.js do autónomo) ---

const regiaoValida = (regiao) => eUuid(regiao?.id) && typeof regiao.nome === 'string';

// As regiões do GET /api/crm/regioes (já pela ordem certa) com um uuid e um
// nome em texto; o que não for lista dá []. O nome fica como está: o React
// escreve-o como texto.
export function regioesValidas(lista) {
  return Array.isArray(lista) ? lista.filter(regiaoValida) : [];
}

// As opções do seletor da região: [{valor, texto}]. `regioes` null ou
// undefined = a lista ainda não chegou; aí, uma região guardada aparece como
// "Região guardada", para o seletor não a perder.
export function opcoesRegiao(filtros, regioes) {
  const { regiao } = normalizarFiltros(filtros ?? {});
  const opcoes = [
    { valor: 'todas', texto: 'Todas' },
    { valor: 'sem', texto: 'Sem região' },
  ];
  if (regioes == null) {
    if (eUuid(regiao)) opcoes.push({ valor: regiao, texto: TEXTO_REGIAO_GUARDADA });
    return opcoes;
  }
  for (const r of regioesValidas(regioes)) opcoes.push({ valor: r.id, texto: r.nome });
  return opcoes;
}

// Quando a lista das regiões chega: uma região guardada que já não existe
// (foi apagada) volta a 'todas'. `mudou` diz ao ecrã que os filtros mudaram e
// têm de se guardar. Chamar só com a lista que chegou (com uma falha do
// pedido, não chamar: a região guardada fica).
export function ajustarARegioes(filtros, regioes) {
  const normalizados = normalizarFiltros(filtros ?? {});
  const apagada = eUuid(normalizados.regiao)
    && !regioesValidas(regioes).some((r) => r.id === normalizados.regiao);
  if (!apagada) return { filtros: normalizados, mudou: false };
  return { filtros: { fases: normalizados.fases, regiao: 'todas' }, mudou: true };
}

// Com filtros ativos o mapa não mostra todas as lojas (o botão "Filtros" fica marcado).
export function filtrosAtivos(filtros) {
  const { fases, regiao } = normalizarFiltros(filtros ?? {});
  return fases.size !== ORDEM.length || regiao !== 'todas';
}
