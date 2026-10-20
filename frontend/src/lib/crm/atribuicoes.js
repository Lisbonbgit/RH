// Atribuições que o CRM escreve (desenho original §9; dossiê §8). Porta de
// public/assets/js/atribuicoes.js do CRM autónomo.
//
// A atribuição do mapa é a da própria Google: desenha-a a API do Google Maps,
// por cima do mapa, e o CRM nunca a esconde nem a tapa (nada nosso dentro do
// `.crm-mapa`; cartões e painéis vivem fora dele) e não a repete aqui. Fica só
// a da Geoapify, de onde vem a morada sugerida de um ponto do GPS ("Morada
// sugerida: … · Powered by Geoapify"); a F3 junta a do openrouteservice.
//
// O texto visível tem de ser exatamente o de `texto`. Os ecrãs usam as
// `partes`: cada uma é um texto, ou, com `url`, uma ligação com esse texto —
// nunca HTML.

const GEOAPIFY = 'https://www.geoapify.com/';

const parte = (texto, url = null) => Object.freeze({ texto, url });

function criar(partes) {
  return Object.freeze({
    texto: partes.map((p) => p.texto).join(''),
    partes: Object.freeze(partes),
  });
}

export const ATRIBUICOES = Object.freeze({
  geoapify: criar([parte('Powered by Geoapify', GEOAPIFY)]),
});
