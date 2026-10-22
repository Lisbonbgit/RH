// A linha da rota no frontend (F3 / T3.26): a polyline codificada ("Encoded Polyline Algorithm Format"
// da Google) que o Directions do openrouteservice devolve, com 5 casas decimais. O servidor guarda-a
// tal como vem (`calculo.geometria`) e manda-a na API; aqui desfaz-se em pares `[lat, lng]`, que o
// `mapa.js` converte para os literais `{lat, lng}` da linha do mapa (o `Polyline` da Google; correções
// do mapa Google no plano da F3, T3.26 e T3.33). Este módulo não fala com a Google.
//
// É a regra do `descodificar` de backend/crm/dominio/polilinha.py: cada ponto é a diferença para o
// anterior, em inteiros (graus × 10^precisão), com o sinal no bit mais baixo e cortada em blocos de 5
// bits, do mais baixo para o mais alto, com o 0x20 em todos menos no último; a cada bloco soma-se 63
// ("?" … "~").
//
// Com uma diferença de propósito: o Python levanta erros, o ecrã nunca rebenta. Um texto estragado
// (um carácter fora de "?".."~", um valor cortado a meio, uma latitude sem longitude, um valor com
// mais de 10 blocos, um ponto fora de ±90/±180), o que não é texto ou uma precisão fora de 0..10 dão
// `[]`: não há linha. As contas são somas e produtos, nunca os operadores de bits do JavaScript (que
// cortam a 32 bits); 10 blocos são 50 bits, que um double guarda sem perder nenhum.

const PRECISAO = 5;
const PRECISAO_MAXIMA = 10;
const DESVIO = 63;
const BLOCO = 32; // 5 bits
const CONTINUA = 32; // o 0x20
const MAXIMO_BLOCOS = 10;
const LATITUDE_MAXIMA = 90;
const LONGITUDE_MAXIMA = 180;

// Os inteiros com sinal da polyline, ou null se o texto estiver estragado.
function valores(texto) {
  const lidos = [];
  let valor = 0;
  let peso = 1;
  let blocos = 0;
  for (let i = 0; i < texto.length; i += 1) {
    const bloco = texto.charCodeAt(i) - DESVIO;
    if (bloco < 0 || bloco >= 2 * BLOCO) return null;
    blocos += 1;
    if (blocos > MAXIMO_BLOCOS) return null;
    valor += (bloco % BLOCO) * peso;
    peso *= BLOCO;
    if (bloco >= CONTINUA) continue;
    // O bit mais baixo é o sinal: 2k → k, 2k + 1 → −(k + 1) (o `~` do algoritmo).
    lidos.push(valor % 2 === 1 ? -(valor + 1) / 2 : valor / 2);
    valor = 0;
    peso = 1;
    blocos = 0;
  }
  if (blocos !== 0 || lidos.length % 2 !== 0) return null;
  return lidos;
}

// A polyline → `[[lat, lng], …]` em graus, numa lista nova; `''` dá `[]` e um texto estragado também.
export function descodificarPolilinha(texto, precisao = PRECISAO) {
  if (typeof texto !== 'string') return [];
  if (!Number.isInteger(precisao) || precisao < 0 || precisao > PRECISAO_MAXIMA) return [];
  const lidos = valores(texto);
  if (lidos === null) return [];
  const escala = 10 ** precisao;
  const pontos = [];
  let lat = 0;
  let lng = 0;
  for (let i = 0; i < lidos.length; i += 2) {
    lat += lidos[i];
    lng += lidos[i + 1];
    const ponto = [lat / escala, lng / escala];
    if (Math.abs(ponto[0]) > LATITUDE_MAXIMA || Math.abs(ponto[1]) > LONGITUDE_MAXIMA) return [];
    pontos.push(ponto);
  }
  return pontos;
}
