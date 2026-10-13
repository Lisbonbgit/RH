// Atribuições obrigatórias (desenho original §9; dossiê §8). Porta de
// public/assets/js/atribuicoes.js do CRM autónomo.
//
// O texto visível tem de ser exatamente o de `texto`. O `html` é só para o
// controlo de atribuição do Leaflet (`lib/crm/mapa.js`) e é montado apenas a
// partir das constantes deste ficheiro (nunca de dados). Nos ecrãs React (ex.:
// "Powered by Geoapify" por baixo da pesquisa de morada), usar `partes`, com o
// texto como filho de um elemento e a `url` no `href` — nunca o `html`.

const GEOAPIFY = 'https://www.geoapify.com/';
const OPENMAPTILES = 'https://openmaptiles.org/';
const OSM = 'https://www.openstreetmap.org/copyright';

const parte = (texto, url = null) => Object.freeze({ texto, url });

const ancora = (p) =>
  p.url === null ? p.texto : `<a href="${p.url}" target="_blank" rel="noopener">${p.texto}</a>`;

function criar(partes) {
  return Object.freeze({
    texto: partes.map((p) => p.texto).join(''),
    html: partes.map(ancora).join(''),
    partes: Object.freeze(partes),
  });
}

export const ATRIBUICOES = Object.freeze({
  geoapify: criar([
    parte('Powered by Geoapify', GEOAPIFY),
    parte(' | '),
    parte('© OpenMapTiles', OPENMAPTILES),
    parte(' '),
    parte('© OpenStreetMap contributors', OSM),
  ]),
  osm: criar([parte('© OpenStreetMap contributors', OSM)]),
  pesquisa: criar([parte('Powered by Geoapify', GEOAPIFY)]),
});
