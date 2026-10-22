// Atribuições que o CRM escreve (desenho original §9; dossiê §8). Porta de
// public/assets/js/atribuicoes.js do CRM autónomo.
//
// A atribuição do mapa é a da própria Google: desenha-a a API do Google Maps,
// por cima do mapa, e o CRM nunca a esconde nem a tapa (nada nosso dentro do
// `.crm-mapa`; cartões e painéis vivem fora dele) e não a repete aqui. Ficam
// a da Geoapify, de onde vem a morada sugerida de um ponto do GPS ("Morada
// sugerida: … · Powered by Geoapify"), e a do openrouteservice (F3 / T3.26),
// que calcula a ordem e as horas da rota: sempre visível no planeador, num
// bloco próprio do painel (nunca sobre o mapa nem junto da atribuição da
// Google), com a frase `TEXTO_ROTA_DE_TERCEIROS` antes da linha da rota
// (Termos Específicos EEA da Google, §A.4.3; correções do mapa Google no plano
// da F3).
//
// O texto visível tem de ser exatamente o de `texto`. Os ecrãs usam as
// `partes`: cada uma é um texto, ou, com `url`, uma ligação com esse texto —
// nunca HTML.

const GEOAPIFY = 'https://www.geoapify.com/';
// As ligações da atribuição do openrouteservice (a do VROOM é http, como o
// plano da F3 a fixa).
const VROOM = 'http://vroom-project.org/';
const HEIGIT = 'https://heigit.org/';
const OPENROUTESERVICE = 'https://openrouteservice.org/';
const OPENSTREETMAP = 'https://www.openstreetmap.org/copyright';

const parte = (texto, url = null) => Object.freeze({ texto, url });

function criar(partes) {
  return Object.freeze({
    texto: partes.map((p) => p.texto).join(''),
    partes: Object.freeze(partes),
  });
}

export const ATRIBUICOES = Object.freeze({
  geoapify: criar([parte('Powered by Geoapify', GEOAPIFY)]),
  // "Developed by VROOM · Hosted by HeiGIT · Routing by openrouteservice · Data from OpenStreetMap".
  ors: criar([
    parte('Developed by '),
    parte('VROOM', VROOM),
    parte(' · Hosted by '),
    parte('HeiGIT', HEIGIT),
    parte(' · Routing by '),
    parte('openrouteservice', OPENROUTESERVICE),
    parte(' · Data from '),
    parte('OpenStreetMap', OPENSTREETMAP),
  ]),
});

// A frase que vai antes da linha da rota (e no resumo da rota): a linha é de
// um terceiro, não da Google.
export const TEXTO_ROTA_DE_TERCEIROS = 'Routing provided by openrouteservice';
