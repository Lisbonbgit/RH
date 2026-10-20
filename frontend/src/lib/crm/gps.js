// GPS de "Estou nesta loja": só se pede quando a pessoa toca no botão, uma
// vez, e nunca há seguimento contínuo (desenho §4.4; dossiê §5.4). Funções
// puras: o objeto `geolocation` (navigator.geolocation) é passado por
// parâmetro. Porta de public/assets/js/gps.js do CRM autónomo.
//
// LIMITE_PRECISAO_M e MENSAGEM_LOCALIZACAO_IMPRECISA têm de ser os de
// backend/crm/dominio/geo.py (LIMITE_PRECISAO_M e MENSAGEM_GPS), verificado
// pelo backend/tests/crm/test_consistencia_frontend.py: manter cada um numa
// só linha `export const <nome> = <valor>;`.

export const LIMITE_PRECISAO_M = 50;

export const OPCOES_GPS = Object.freeze({ enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });

export const MENSAGEM_PERMISSAO_NEGADA = "Autorize a localização no browser para usar 'Estou nesta loja'";
// Mostrada quando a precisão é pior que 50 m (igual à mensagem 422 do servidor).
export const MENSAGEM_LOCALIZACAO_IMPRECISA = 'Localização imprecisa — ajuste o pino';
const MENSAGEM_POSICAO_INDISPONIVEL = 'Não foi possível obter a localização — coloque o pino no mapa';
const MENSAGEM_TEMPO_ESGOTADO = 'A localização demorou demasiado — tente outra vez ou coloque o pino no mapa';
const MENSAGEM_SEM_GPS = 'Este browser não permite obter a localização — coloque o pino no mapa';

// Códigos de GeolocationPositionError.
const ERROS = {
  1: { codigo: 'permissao_negada', mensagem: MENSAGEM_PERMISSAO_NEGADA },
  2: { codigo: 'posicao_indisponivel', mensagem: MENSAGEM_POSICAO_INDISPONIVEL },
  3: { codigo: 'tempo_esgotado', mensagem: MENSAGEM_TEMPO_ESGOTADO },
};

// 'ok' quando a precisão (em metros) é <= 50; 'imprecisa' acima disso ou se for inválida.
export function avaliarPrecisao(precisaoM) {
  if (typeof precisaoM !== 'number' || !Number.isFinite(precisaoM) || precisaoM < 0) return 'imprecisa';
  return precisaoM <= LIMITE_PRECISAO_M ? 'ok' : 'imprecisa';
}

export function traduzirErroGps(erro) {
  const code = erro?.code;
  // Só propriedades próprias: um `code` como 'constructor' não pode apanhar as herdadas. O autónomo usa
  // Object.hasOwn, que falta nos Safari anteriores ao 15.4 (o CRA não junta polyfills): aí o erro
  // rebentava dentro da resposta do browser e a promessa do obterPosicao nunca acabava.
  const conhecido = Object.prototype.hasOwnProperty.call(ERROS, String(code));
  return { ...(conhecido ? ERROS[code] : ERROS[2]) };
}

function erroGps({ codigo, mensagem }) {
  return Object.assign(new Error(mensagem), { codigo, mensagem });
}

// Resolve com {lat, lng, precisao_m} (precisão arredondada ao metro, como o servidor guarda;
// null se o browser não a der). Rejeita com um Error que tem {codigo, mensagem} em pt-PT.
export function obterPosicao(geolocation) {
  return new Promise((resolver, rejeitar) => {
    if (!geolocation || typeof geolocation.getCurrentPosition !== 'function') {
      rejeitar(erroGps({ codigo: 'sem_gps', mensagem: MENSAGEM_SEM_GPS }));
      return;
    }
    try {
      geolocation.getCurrentPosition(
        (posicao) => {
          const { latitude, longitude, accuracy } = posicao.coords;
          const precisao_m = Number.isFinite(accuracy) ? Math.round(accuracy) : null;
          resolver({ lat: latitude, lng: longitude, precisao_m });
        },
        (erro) => rejeitar(erroGps(traduzirErroGps(erro))),
        { ...OPCOES_GPS },
      );
    } catch {
      rejeitar(erroGps(traduzirErroGps(null)));
    }
  });
}

// --- O círculo da precisão no mapa (E7) ----------------------------------------------------------

// Metros por grau de latitude: 40 075 017 m de perímetro (a esfera de raio 6 378 137 m que a Google também usa).
const METROS_POR_GRAU = 40075017 / 360;

// O retângulo [[sul, oeste], [norte, este]] que contém o círculo com centro {lat, lng} e raio em metros. O
// seletor junta os dois cantos num LatLngBounds da Google para o mapa enquadrar o círculo (fitBounds, com o
// zoom limitado à parte); o falso dos testes calcula com ele os limites do círculo. null sem centro ou sem raio
// positivo.
export function limitesDoCirculo(centro, raioM) {
  const lat = centro?.lat;
  const lng = centro?.lng;
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  if (typeof raioM !== 'number' || !Number.isFinite(raioM) || raioM <= 0) return null;
  const graosLat = raioM / METROS_POR_GRAU;
  const graosLng = graosLat / Math.cos((lat * Math.PI) / 180);
  return [[lat - graosLat, lng - graosLng], [lat + graosLat, lng + graosLng]];
}
