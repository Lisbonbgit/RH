// As decisões do ecrã do mapa (`pages/crm/CrmMapa.js`), fora do React para
// terem testes. Porta das regras de public/assets/js/ecras/mapa.js do CRM
// autónomo (plano T2.25):
//  - a primeira vista: as lojas que os filtros deixam ver; se os filtros as
//    escondem todas, as lojas todas (nunca um mapa vazio); sem lojas, ou se o
//    pedido falhou, o centro das definições (o `enquadrar([])` do mapa.js); e
//    uma segunda falha já não mexe na vista;
//  - a loja do endereço (`?loja=<id>`), ao nível da rua (`ZOOM_LOJA`), mesmo
//    que os filtros a escondam. Procura-se na lista das lojas, sem outro pedido
//    (no autónomo vinha com o ecrã de onde se saía);
//  - o aviso de quem manda voltar ao mapa (ex.: "Loja guardada", no `state` da
//    navegação), com "— os filtros escondem-na do mapa." quando é o caso. O
//    aviso é um texto fixo: o nome da loja nunca entra nele;
//  - a linha de contacto do cartão da loja (`components/crm/CartaoLoja.js`):
//    a pessoa de contacto e o telefone em texto, tal como foram escritos. O
//    botão Ligar do desenho original saiu em 2026-10-13, a pedido do Bruce. A
//    loja do cartão é a do resumo do `GET /lojas` (a que o pino tem), por isso
//    o resumo traz os dois campos (`CAMPOS_RESUMO` em `backend/crm/formatar.py`;
//    o `ecraMapa.test.js` confere-o).

import { MENSAGEM_ERRO_INESPERADO } from './api';
import { aplicarFiltros } from './filtros';
import { ZOOM_LOJA } from './mapa';

// A loja a centrar no mapa: `…/mapa?loja=<id>`.
export const PARAMETRO_LOJA = 'loja';

// A loja nova não aparece no mapa porque os filtros guardados a escondem.
export const TEXTO_ESCONDIDA_PELOS_FILTROS = 'os filtros escondem-na do mapa.';

// Entre a pessoa de contacto e o telefone, na linha "Contacto:" do cartão.
export const SEPARADOR_CONTACTO = ' · ';

const numero = (valor) => typeof valor === 'number' && Number.isFinite(valor);
const temCoordenadas = (loja) => numero(loja?.lat) && numero(loja?.lng);
const texto = (valor) => (typeof valor === 'string' ? valor.trim() : '');

// O contacto do cartão: "pessoa · telefone", só a parte que existe, ou null
// sem nenhuma das duas (a linha não se mostra). É texto: o React escapa-o e
// não se monta nenhuma ligação (o telefone aparece tal como foi escrito).
export function contactoDaLoja(loja) {
  const partes = [texto(loja?.pessoa_contacto), texto(loja?.telefone)].filter((parte) => parte !== '');
  return partes.length > 0 ? partes.join(SEPARADOR_CONTACTO) : null;
}

// A mensagem de um erro do cliente (`ErroCrm`); sem ela, o texto de erro inesperado.
export function textoDoErro(erro) {
  return typeof erro?.mensagem === 'string' && erro.mensagem !== '' ? erro.mensagem : MENSAGEM_ERRO_INESPERADO;
}

// A loja da lista com este id (comparado tal e qual) e com coordenadas, ou null.
export function lojaComId(lojas, id) {
  if (!Array.isArray(lojas) || typeof id !== 'string' || id === '') return null;
  const loja = lojas.find((l) => l?.id === id);
  return temCoordenadas(loja) ? loja : null;
}

// A vista quando o pedido das lojas termina:
//  - lojas: a lista que chegou, ou null se o pedido falhou;
//  - idLoja: o `?loja=<id>` do endereço (ou null);
//  - jaTemVista: o mapa já tem uma vista (de uma falha anterior).
// → {tipo: 'centrar', loja, zoom} | {tipo: 'enquadrar', lojas} | null (não mexer).
export function vistaAoCarregar({ lojas, filtros, idLoja = null, jaTemVista = false }) {
  if (!Array.isArray(lojas)) return jaTemVista ? null : { tipo: 'enquadrar', lojas: [] };
  const alvo = lojaComId(lojas, idLoja);
  if (alvo) return { tipo: 'centrar', loja: alvo, zoom: ZOOM_LOJA };
  const visiveis = aplicarFiltros(lojas, filtros);
  return { tipo: 'enquadrar', lojas: visiveis.length > 0 ? visiveis : lojas };
}

// O aviso que outro ecrã deixou ao navegar para o mapa (`state: {aviso}`), ou null.
export function lerAviso(estado) {
  return typeof estado?.aviso === 'string' && estado.aviso !== '' ? estado.aviso : null;
}

// O texto do aviso: o próprio aviso, com o porquê quando os filtros escondem a loja.
export function textoAviso(aviso, loja, filtros) {
  if (typeof aviso !== 'string' || aviso === '') return null;
  const escondida = temCoordenadas(loja) && aplicarFiltros([loja], filtros).length === 0;
  return escondida ? `${aviso} — ${TEXTO_ESCONDIDA_PELOS_FILTROS}` : aviso;
}
