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
// Com o mapa da Google (plano do mapa Google, G15; adenda §1.1 e §6.3):
//  - o negócio tocado no mapa (o ícone dele): só o identificador do lugar e o
//    ponto tocado, nada mais (`negocioDoToque`). Os dados do negócio estão no
//    balão da própria Google; o painel "Negócio selecionado" não os mostra;
//  - "Adicionar como loja" leva à Nova loja com o negócio no `state` da
//    navegação (`destinoNovaLojaDoNegocio`). O mapa não pede nada à Google: a
//    posição do lugar pede-se na Nova loja, quando o seletor está pronto;
//  - sem mapa, a mensagem distingue o servidor sem a chave Google ("Mapa não
//    configurado…") do mapa que não carregou (`configuracaoDoMapa`,
//    `mensagemSemMapa`).

import { MENSAGEM_ERRO_INESPERADO } from './api';
import { aplicarFiltros } from './filtros';
import { MENSAGEM_MAPA_NAO_CONFIGURADO, MENSAGEM_SEM_MAPA, ZOOM_LOJA, configuracaoValida } from './mapa';

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

// --- O mapa da Google ---------------------------------------------------------------------------------

const eObjeto = (valor) => valor !== null && typeof valor === 'object' && !Array.isArray(valor);
// Um identificador de lugar só serve se for um texto não vazio (a Google não documenta o formato).
const eIdDeLugar = (valor) => typeof valor === 'string' && valor.trim() !== '';

// {id, lat, lng} só com estas chaves (uma cópia), ou null se o id não for texto não vazio ou o ponto não
// tiver dois números finitos.
function negocioValido(id, lat, lng) {
  return eIdDeLugar(id) && numero(lat) && numero(lng) ? { id, lat, lng } : null;
}

// O negócio de um toque no ícone dele (o `aoTocarNumLugar({placeId, lat, lng})` do mapa) → {id, lat, lng},
// ou null (sem identificador em texto, sem ponto, ou o que não for um toque). Nunca rebenta.
export function negocioDoToque(toque) {
  if (!eObjeto(toque)) return null;
  return negocioValido(toque.placeId, toque.lat, toque.lng);
}

// "Adicionar como loja": a Nova loja (`<base>/lojas/nova`) com o negócio no `state` da navegação,
// {negocio: {id, lat, lng}} e nada mais. Sem um negócio válido, a Nova loja abre vazia (estado null).
export function destinoNovaLojaDoNegocio(base, negocio) {
  const valido = eObjeto(negocio) ? negocioValido(negocio.id, negocio.lat, negocio.lng) : null;
  return { caminho: `${base}/lojas/nova`, estado: valido === null ? null : { negocio: valido } };
}

// A configuração do GET /api/crm/config (null enquanto não chega, ou se o pedido falhou):
//  - 'a_chegar': ainda não há configuração;
//  - 'nao_configurado': o servidor não tem a chave do navegador ou o Map ID (google: null);
//  - 'ok': a chave e o Map ID em texto (o mapa pode carregar);
//  - 'invalida': qualquer outra forma (o mapa não carrega).
export function configuracaoDoMapa(configuracao) {
  if (configuracao === null || configuracao === undefined) return 'a_chegar';
  if (configuracao.google === null) return 'nao_configurado';
  return configuracaoValida(configuracao) ? 'ok' : 'invalida';
}

// A mensagem no lugar do mapa: "Mapa não configurado…" sem a chave no servidor; "Não foi possível carregar
// o mapa…" com uma configuração inválida ou se a Google falhou (`falhou`); null com o mapa (ou à espera).
export function mensagemSemMapa({ estado, falhou = false } = {}) {
  if (estado === 'nao_configurado') return MENSAGEM_MAPA_NAO_CONFIGURADO;
  if (estado === 'invalida' || falhou) return MENSAGEM_SEM_MAPA;
  return null;
}
