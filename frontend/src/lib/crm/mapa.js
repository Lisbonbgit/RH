// O mapa das lojas sobre o Google Maps (Maps JavaScript API, só peças GA;
// adenda do mapa Google §6.1, plano G6). A Google (`google`) e o documento são
// recebidos por parâmetro: o `MapaLojas` passa o `window.google` depois do
// `importar` do `carregadorGoogle.js`; os testes passam os falsos de `testes/`.
//
//  - Um só `google.maps.Map` no elemento, com o Map ID da configuração (sem
//    ele os marcadores avançados não aparecem), zoom do 6 ao 19 e só os botões
//    de zoom da Google (os títulos já vêm em português). A atribuição e o
//    logótipo são os da própria Google: nunca se escondem nem se tapam.
//  - Cada loja é um `AdvancedMarkerElement` com a cor da fase e o nome sempre
//    visível ao lado, em qualquer zoom, sem agrupamento e sem se esconder por
//    colisão. O conteúdo do pino é um nó DOM montado com o `el()` (o nome entra
//    por textContent): nunca HTML vindo de dados. Este ficheiro e o
//    `seletor.js` são os únicos onde um marcador recebe conteúdo.
//  - Tocar num pino (ou Enter/Espaço com o foco nele: a Google emite o mesmo
//    `gmp-click`) escolhe a loja; o ecrã abre o cartão da loja.
//  - Tocar no ícone de um negócio da Google abre o balão do lugar da própria
//    Google: o código nunca o trava (não se chama `stop()` no evento) e nunca
//    cria um balão seu; o ecrã recebe só o identificador do lugar e o ponto
//    tocado (`aoTocarNumLugar`). Com `negociosClicaveis: false` (o planeador)
//    a Google não emite o lugar e tudo é toque no mapa.
//  - As posições da Google chegam ora como `LatLng` (lat()/lng() em função) ora
//    como literal {lat, lng}: lê-las sempre pelo `pontoDe`.
//  - O elemento guarda o Map em `__crmMapa`, só para a verificação no browser
//    (regra 16 do plano): nenhum código do CRM o lê.

import { el } from './dom';
import { FASES, ORDEM, classePino } from './fases';

export const ZOOM_MINIMO = 6;
export const ZOOM_MAXIMO = 19;
// Sem lojas, o mapa mostra a zona da fábrica.
export const ZOOM_SEM_LOJAS = 12;
// Com uma loja só (ou muito juntas), o enquadramento não vai até ao zoom máximo.
export const ZOOM_MAXIMO_ENQUADRAR = 16;
// Ao voltar ao mapa depois de guardar uma loja nova: ao nível da rua, com os nomes à volta.
export const ZOOM_LOJA = 17;
// O ponto da fábrica por defeito (os PADROES de backend/crm/dominio/definicoes.py),
// se a configuração não trouxer o centro.
export const CENTRO_PADRAO = Object.freeze({ lat: 38.7223, lng: -9.1393 });
// Folga (px) à volta das lojas no enquadramento (as etiquetas ficam à direita dos pinos).
export const MARGEM_ENQUADRAR = 40;

// A Google não carregou (rede, quota, referrer) ou não criou o mapa.
export const MENSAGEM_SEM_MAPA = 'Não foi possível carregar o mapa — recarregue a página.';
// O servidor não tem a chave do navegador ou o Map ID (o GET /api/crm/config trouxe google: null).
export const MENSAGEM_MAPA_NAO_CONFIGURADO = 'Mapa não configurado — peça ao administrador para configurar a chave Google.';

const textoPreenchido = (valor) => typeof valor === 'string' && valor.trim() !== '';

// A configuração do GET /api/crm/config serve para criar o mapa: {google: {chave, map_id}, centro}, com a
// chave do navegador e o Map ID em texto. Pode faltar (o pedido falhou) ou vir com google: null.
export const configuracaoValida = (configuracao) =>
  textoPreenchido(configuracao?.google?.chave) && textoPreenchido(configuracao?.google?.map_id);

const numero = (valor) => typeof valor === 'number' && Number.isFinite(valor);
const temCoordenadas = (loja) => numero(loja?.lat) && numero(loja?.lng);
const pontoDaLoja = (loja) => ({ lat: loja.lat, lng: loja.lng });

// {lat, lng} numérico a partir de um literal ou de um LatLng da Google (lat() e lng() em função); o resto
// (um par [lat, lng] incluído) → null.
export function pontoDe(valor) {
  if (valor === null || typeof valor !== 'object') return null;
  const funcoes = typeof valor.lat === 'function' && typeof valor.lng === 'function';
  const lat = funcoes ? valor.lat() : valor.lat;
  const lng = funcoes ? valor.lng() : valor.lng;
  return numero(lat) && numero(lng) ? { lat, lng } : null;
}

// O limite do zoom que espera pelo próximo `idle` de cada mapa (um só por mapa).
const limitesPendentes = new WeakMap();

function cancelarLimiteDoZoom(mapa) {
  const ouvinte = limitesPendentes.get(mapa);
  if (!ouvinte) return;
  limitesPendentes.delete(mapa);
  ouvinte.remove();
}

// O fitBounds da Google não aceita um zoom máximo: limita-se no primeiro `idle` depois de enquadrar. O
// ouvinte guarda-se (um só por mapa): a chamada seguinte, um zoom pedido pelo código e o `destruir` tiram-no,
// para um `idle` tardio não desfazer o zoom que a pessoa (ou o ecrã) escolheu entretanto. Devolve o ouvinte
// (o MapsEventListener da Google). Também a usa o seletor (o círculo do GPS).
export function limitarZoomDepoisDeEnquadrar(google, mapa, maximo) {
  cancelarLimiteDoZoom(mapa);
  const ouvinte = google.maps.event.addListenerOnce(mapa, 'idle', () => {
    if (limitesPendentes.get(mapa) === ouvinte) limitesPendentes.delete(mapa);
    const zoom = mapa.getZoom();
    if (numero(zoom) && zoom > maximo) mapa.setZoom(maximo);
  });
  limitesPendentes.set(mapa, ouvinte);
  return ouvinte;
}

function tituloPino(loja) {
  const fase = ORDEM.includes(loja.fase) ? FASES[loja.fase].rotulo : null;
  return fase ? `${loja.nome} (${fase})` : String(loja.nome);
}

// criarMapa({google, documento, elemento, configuracao, negociosClicaveis = true, aoEscolherLoja?,
//            aoTocarNoMapa?, aoTocarNumLugar?})
//   → {mapa, mostrarLojas, enquadrar, redimensionar, centrarEm, focar, destruir}
//  - configuracao: a do GET /api/crm/config, {google: {chave, map_id}, centro: {lat, lng}} (ver configuracaoValida);
//  - aoEscolherLoja(loja, marcador): tocaram no pino da loja;
//  - aoTocarNoMapa({lat, lng} | null): tocaram no mapa, fora dos pinos e dos negócios, nesse ponto (os toques
//    num pino não chegam ao mapa);
//  - aoTocarNumLugar({placeId, lat, lng}): tocaram no ícone de um negócio (o balão da Google abre na mesma);
//    lat/lng são o ponto tocado, só como reserva. Sem ele, o toque num negócio chega a aoTocarNoMapa.
export function criarMapa({
  google, documento, elemento, configuracao, negociosClicaveis = true, aoEscolherLoja, aoTocarNoMapa, aoTocarNumLugar,
}) {
  const centro = temCoordenadas(configuracao.centro) ? pontoDaLoja(configuracao.centro) : { ...CENTRO_PADRAO };
  const clicaveis = Boolean(negociosClicaveis);
  const mapa = new google.maps.Map(elemento, {
    mapId: configuracao.google.map_id,
    center: centro,
    zoom: ZOOM_SEM_LOJAS,
    minZoom: ZOOM_MINIMO,
    maxZoom: ZOOM_MAXIMO,
    clickableIcons: clicaveis,
    disableDefaultUI: true,
    zoomControl: true,
    gestureHandling: 'greedy',
    mapTypeId: 'roadmap',
  });
  // A div do mapa não é focável por si: o ecrã devolve-lhe o foco ao fechar o cartão (focar()).
  elemento.tabIndex = -1;
  elemento.__crmMapa = mapa;

  const tocarNoMapa = typeof aoTocarNoMapa === 'function' ? aoTocarNoMapa : null;
  const tocarNumLugar = typeof aoTocarNumLugar === 'function' ? aoTocarNumLugar : null;
  if (tocarNoMapa || tocarNumLugar) {
    // Nunca evento.stop(): num negócio, o balão da Google abre como em qualquer site.
    mapa.addListener('click', (evento) => {
      const ponto = pontoDe(evento?.latLng);
      const placeId = clicaveis && textoPreenchido(evento?.placeId) ? evento.placeId : null;
      if (placeId && tocarNumLugar) {
        tocarNumLugar({ placeId, lat: ponto ? ponto.lat : null, lng: ponto ? ponto.lng : null });
        return;
      }
      tocarNoMapa?.(ponto);
    });
  }

  let marcadores = [];
  let destruido = false;

  function pino(loja) {
    const marcador = new google.maps.marker.AdvancedMarkerElement({
      map: mapa,
      position: pontoDaLoja(loja),
      content: el(documento, 'div', {
        classe: classePino(loja.fase),
        filhos: [
          el(documento, 'span', { classe: 'pino__bola' }),
          el(documento, 'span', { classe: 'etiqueta-loja', texto: loja.nome }),
        ],
      }),
      title: tituloPino(loja),
      gmpClickable: true,
      collisionBehavior: google.maps.CollisionBehavior.REQUIRED,
    });
    if (typeof aoEscolherLoja === 'function') {
      marcador.addListener('gmp-click', () => aoEscolherLoja(loja, marcador));
    }
    return marcador;
  }

  // Com a chave recusada pela Google (ex.: RefererNotAllowedMapError), `marcador.map = null` lança dentro da
  // biblioteca; tirar os pinos nunca pode derrubar a página do CRM (visto em produção a 2026-10-22).
  function tirarPinos() {
    for (const marcador of marcadores) {
      try {
        marcador.map = null;
      } catch {
        // O mapa já não existe para a Google: não há pino para tirar.
      }
    }
    marcadores = [];
  }

  return {
    mapa,
    // Mostra estas lojas (e só estas): {id, nome, fase, lat, lng, …} do GET /api/crm/lojas.
    mostrarLojas(lojas) {
      if (destruido) return;
      tirarPinos();
      marcadores = lojas.filter(temCoordenadas).map(pino);
    },
    // A vista inicial: todas as lojas à vista (sem passar do zoom 16); sem lojas, o centro das definições
    // (o ponto da fábrica).
    enquadrar(lojas) {
      if (destruido) return;
      const pontos = lojas.filter(temCoordenadas).map(pontoDaLoja);
      if (pontos.length > 0) {
        const limites = new google.maps.LatLngBounds();
        for (const ponto of pontos) limites.extend(ponto);
        mapa.fitBounds(limites, MARGEM_ENQUADRAR);
        limitarZoomDepoisDeEnquadrar(google, mapa, ZOOM_MAXIMO_ENQUADRAR);
        return;
      }
      cancelarLimiteDoZoom(mapa);
      mapa.setCenter({ ...centro });
      mapa.setZoom(ZOOM_SEM_LOJAS);
    },
    // Depois de a área do mapa mudar de tamanho (ex.: o cartão da loja abre ao lado). A Google mede-se sozinha
    // nas versões atuais; o aviso fica pela interface e é inofensivo.
    redimensionar() {
      if (destruido) return;
      google.maps.event.trigger(mapa, 'resize');
    },
    // Põe a loja ao centro. Sem zoom, desloca-se até ela sem mudar o zoom; com zoom, mostra-a logo nesse zoom
    // (e um limite do enquadramento ainda à espera já não conta).
    centrarEm(loja, zoom) {
      if (destruido || !temCoordenadas(loja)) return;
      if (numero(zoom)) {
        cancelarLimiteDoZoom(mapa);
        mapa.setCenter(pontoDaLoja(loja));
        mapa.setZoom(zoom);
      } else {
        mapa.panTo(pontoDaLoja(loja));
      }
    },
    // O foco no mapa (ao fechar o cartão de uma loja cujo pino já não existe).
    focar() {
      if (destruido) return;
      elemento.focus();
    },
    // No cleanup do useEffect (o StrictMode monta duas vezes em desenvolvimento): a Google nunca tira o DOM
    // que pôs no elemento, por isso esvazia-se aqui, para um mapa novo no mesmo elemento não ficar por cima.
    // Uma segunda chamada não faz nada (não mexe num mapa novo do mesmo elemento).
    destruir() {
      if (destruido) return;
      destruido = true;
      cancelarLimiteDoZoom(mapa);
      tirarPinos();
      google.maps.event.clearInstanceListeners(mapa);
      if (elemento.__crmMapa === mapa) delete elemento.__crmMapa;
      elemento.replaceChildren();
    },
  };
}
