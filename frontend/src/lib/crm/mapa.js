// O mapa das lojas sobre o Leaflet 1.9.4 (desenho original §6.1 e §9; dossiê
// §7). Porta de public/assets/js/mapa.js do CRM autónomo. O Leaflet (L) e o
// documento são recebidos por parâmetro: o `MapaLojas` (T2.25) passa o
// `import * as L from 'leaflet'` e o `document`; os testes passam os falsos de
// `testes/`.
//
//  - Zoom do 6 ao 19. A atribuição fica sempre visível no canto, sem o prefixo
//    do Leaflet (o Leaflet é creditado na licença e na política de privacidade).
//  - Os mosaicos vêm do GET /api/crm/config. Se falharem (mosaicos.js), o mapa
//    muda sozinho para os alternativos (OpenStreetMap) e para a atribuição do
//    OSM. A atribuição é sempre uma das constantes de atribuicoes.js (o Leaflet
//    põe-na como HTML): nunca vem de dados.
//  - Cada loja é um pino com a cor da fase e o nome sempre visível ao lado, em
//    qualquer zoom, sem agrupamento. O nome entra numa etiqueta (tooltip) como
//    nó DOM com textContent; o ícone não leva HTML (a bola desenha-se no CSS).
//  - Este é o único ficheiro do CRM onde o Leaflet recebe conteúdo e atribuição
//    (o seguranca.test.js recusa-os noutros sítios).
//  - Os mosaicos não mudam a Referrer-Policy: a chave da Geoapify está restrita
//    por Referer.
//  - Tocar num pino (ou Enter/Espaço com o foco nele) escolhe a loja: o ecrã
//    abre o cartão da loja. As etiquetas não recebem toques (CSS do Leaflet),
//    para não taparem os pinos vizinhos quando os nomes se sobrepõem.

import { el } from './dom';
import { ATRIBUICOES } from './atribuicoes';
import { FASES, ORDEM, classePino } from './fases';
import { criarControloAlternativa } from './mosaicos';

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

// 44 px de área de toque, com o centro na loja; a bola do pino desenha-se no CSS (.pino::before).
const TAMANHO_PINO = 44;
// A etiqueta começa logo à direita da bola.
const DISTANCIA_ETIQUETA = 14;
// Folga à volta das lojas no enquadramento (as etiquetas ficam à direita dos pinos).
const MARGEM_ENQUADRAR = [40, 40];
// As teclas que "carregam" no pino (tem role="button" e tabindex, mas não é um <button>).
const TECLAS_ESCOLHER = new Set(['Enter', ' ']);

export const MENSAGEM_SEM_MAPA = 'Não foi possível carregar o mapa — recarregue a página.';

// A configuração do GET /api/crm/config serve para criar o mapa (pode faltar,
// se o pedido falhou).
export const configuracaoValida = (configuracao) =>
  typeof configuracao?.mosaicos?.url === 'string' && configuracao.mosaicos.url !== '';

const numero = (valor) => typeof valor === 'number' && Number.isFinite(valor);
const temCoordenadas = (loja) => numero(loja?.lat) && numero(loja?.lng);
const chaveAtribuicao = (valor) => (valor === 'geoapify' ? 'geoapify' : 'osm');
const urlValida = (url) => typeof url === 'string' && url !== '';

function tituloPino(loja) {
  const fase = ORDEM.includes(loja.fase) ? FASES[loja.fase].rotulo : null;
  return fase ? `${loja.nome} (${fase})` : String(loja.nome);
}

// criarMapa({L, documento, elemento, configuracao, aoEscolherLoja?, aoTocarNoMapa?})
//   → {mapa, atribuicao, mostrarLojas, enquadrar, redimensionar, centrarEm, destruir}
//  - configuracao: a do GET /api/crm/config, {mosaicos:{url, atribuicao}, alternativa:{url}, centro:{lat, lng}};
//  - o elemento já deve estar na página (o Leaflet mede-o ao mostrar a primeira vista);
//  - aoEscolherLoja(loja, marcador): tocaram no pino da loja; aoTocarNoMapa({lat, lng}): tocaram no mapa, fora
//    dos pinos, nesse ponto (os toques num pino não chegam ao mapa: no Leaflet, os marcadores não os deixam subir).
export function criarMapa({ L, documento, elemento, configuracao, aoEscolherLoja, aoTocarNoMapa }) {
  const mapa = L.map(elemento, { minZoom: ZOOM_MINIMO, maxZoom: ZOOM_MAXIMO, attributionControl: false });
  L.control.attribution({ prefix: false }).addTo(mapa);
  if (typeof aoTocarNoMapa === 'function') {
    mapa.on('click', (evento) => {
      const ponto = evento?.latlng;
      aoTocarNoMapa(ponto ? { lat: ponto.lat, lng: ponto.lng } : null);
    });
  }

  const principal = configuracao.mosaicos.url;
  const alternativa = configuracao.alternativa?.url;
  let atribuicao = chaveAtribuicao(configuracao.mosaicos.atribuicao);

  const novaCamada = (url, chave) => L.tileLayer(url, {
    attribution: ATRIBUICOES[chave].html,
    minZoom: ZOOM_MINIMO,
    maxZoom: ZOOM_MAXIMO,
  });

  const camada = novaCamada(principal, atribuicao);
  if (urlValida(alternativa) && alternativa !== principal) {
    const controlo = criarControloAlternativa();
    const aoCarregar = () => controlo.registarSucesso();
    const aoFalhar = () => {
      if (!controlo.registarErro()) return;
      // Só os ouvintes deste ficheiro: o controlo de atribuição tem um na camada para esquecer o texto dela.
      camada.off('tileload', aoCarregar).off('tileerror', aoFalhar);
      novaCamada(alternativa, 'osm').addTo(mapa);
      camada.remove();
      atribuicao = 'osm';
    };
    camada.on('tileload', aoCarregar).on('tileerror', aoFalhar);
  }
  camada.addTo(mapa);

  const pinos = L.layerGroup().addTo(mapa);

  function pino(loja) {
    const marcador = L.marker([loja.lat, loja.lng], {
      icon: L.divIcon({
        className: classePino(loja.fase),
        iconSize: [TAMANHO_PINO, TAMANHO_PINO],
        iconAnchor: [TAMANHO_PINO / 2, TAMANHO_PINO / 2],
        tooltipAnchor: [DISTANCIA_ETIQUETA, 0],
      }),
      keyboard: true,
      title: tituloPino(loja),
    });
    marcador.bindTooltip(el(documento, 'span', { texto: loja.nome }), {
      permanent: true,
      direction: 'right',
      className: 'etiqueta-loja',
    });
    if (typeof aoEscolherLoja === 'function') {
      marcador.on('click', () => aoEscolherLoja(loja, marcador));
      marcador.on('keydown', (evento) => {
        const tecla = evento.originalEvent;
        if (!TECLAS_ESCOLHER.has(tecla?.key)) return;
        tecla.preventDefault?.();
        aoEscolherLoja(loja, marcador);
      });
    }
    return marcador;
  }

  return {
    mapa,
    get atribuicao() {
      return atribuicao;
    },
    // Mostra estas lojas (e só estas): {id, nome, fase, lat, lng, …} do GET /api/crm/lojas.
    mostrarLojas(lojas) {
      pinos.clearLayers();
      for (const loja of lojas) {
        if (temCoordenadas(loja)) pinos.addLayer(pino(loja));
      }
    },
    // A vista inicial: todas as lojas à vista; sem lojas, o centro das definições (o ponto da fábrica).
    enquadrar(lojas) {
      const pontos = lojas.filter(temCoordenadas).map((loja) => [loja.lat, loja.lng]);
      if (pontos.length > 0) {
        mapa.fitBounds(L.latLngBounds(pontos), { padding: MARGEM_ENQUADRAR, maxZoom: ZOOM_MAXIMO_ENQUADRAR });
        return;
      }
      const centro = temCoordenadas(configuracao.centro) ? configuracao.centro : CENTRO_PADRAO;
      mapa.setView([centro.lat, centro.lng], ZOOM_SEM_LOJAS);
    },
    // Depois de a área do mapa mudar de tamanho (ex.: o cartão da loja abre por baixo). O que está no canto
    // de cima fica onde está; sem isto o Leaflet continuava a contar com o tamanho antigo.
    redimensionar() {
      mapa.invalidateSize({ pan: false });
    },
    // Põe a loja ao centro. Sem zoom, desloca-se até ela sem mudar o zoom (os botões de zoom aproximam à volta
    // do centro); com zoom, mostra-a logo nesse zoom.
    centrarEm(loja, zoom) {
      if (!temCoordenadas(loja)) return;
      if (numero(zoom)) mapa.setView([loja.lat, loja.lng], zoom);
      else mapa.panTo([loja.lat, loja.lng]);
    },
    // No cleanup do useEffect (o StrictMode monta duas vezes em desenvolvimento).
    destruir() {
      mapa.remove();
    },
  };
}
