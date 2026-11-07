// O GPS do CRM. Funções puras: o objeto `geolocation` (navigator.geolocation)
// é passado por parâmetro.
//  - "Estou nesta loja" (`obterPosicao`): só se pede quando a pessoa toca no
//    botão, uma vez, sem seguir a pessoa (desenho §4.4; dossiê §5.4). Porta de
//    public/assets/js/gps.js do CRM autónomo.
//  - "A minha localização" (`seguirPosicao`): o único seguimento contínuo, só
//    a pedido da pessoa, e a posição só vai para o mapa, nunca para o servidor
//    (desenho de 2026-11-06; dossiê §5.4). As regras estão em
//    `minhaLocalizacao.js`.
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

function traduzirErro(tabela, erro) {
  const code = erro?.code;
  // Só propriedades próprias: um `code` como 'constructor' não pode apanhar as herdadas. O autónomo usa
  // Object.hasOwn, que falta nos Safari anteriores ao 15.4 (o CRA não junta polyfills): aí o erro
  // rebentava dentro da resposta do browser e a promessa do obterPosicao nunca acabava.
  const conhecido = Object.prototype.hasOwnProperty.call(tabela, String(code));
  return { ...(conhecido ? tabela[code] : tabela[2]) };
}

export function traduzirErroGps(erro) {
  return traduzirErro(ERROS, erro);
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

// --- O seguimento de "A minha localização" -------------------------------------------------------

// Opções próprias, porque aqui não se guarda nada e o que conta é o ponto aparecer depressa: uma leitura de há
// 5 s serve, e a primeira pode demorar 20 s (um GPS a frio, sem a pessoa parada à porta de uma loja). O `timeout`
// vale para cada leitura: num telemóvel parado alguns browsers voltam a dar "tempo esgotado" com o seguimento vivo.
export const OPCOES_SEGUIMENTO = Object.freeze({ enableHighAccuracy: true, timeout: 20000, maximumAge: 5000 });

// As mensagens de "Estou nesta loja" falam do pino e desse botão: aqui não há pino para ajustar.
const ERROS_SEGUIMENTO = {
  1: { codigo: 'permissao_negada', mensagem: 'Autorize a localização nas definições do browser para ver onde está no mapa' },
  2: { codigo: 'posicao_indisponivel', mensagem: 'Não foi possível obter a sua localização — tente outra vez' },
  3: { codigo: 'tempo_esgotado', mensagem: 'A localização demorou demasiado — tente outra vez' },
};
const SEM_GPS_NO_SEGUIMENTO = {
  codigo: 'sem_gps',
  mensagem: 'Este browser não permite obter a localização — tente outra vez ou use outro browser',
};

const coordenada = (valor, limite) => Number.isFinite(valor) && Math.abs(valor) <= limite;

// {lat, lng, precisao_m}, como o obterPosicao; null com coordenadas que não servem (a leitura ignora-se).
function leituraDe(posicao) {
  const { latitude, longitude, accuracy } = posicao?.coords ?? {};
  if (!coordenada(latitude, 90) || !coordenada(longitude, 180)) return null;
  const precisao_m = Number.isFinite(accuracy) && accuracy >= 0 ? Math.round(accuracy) : null;
  return { lat: latitude, lng: longitude, precisao_m };
}

// Segue a posição até se chamar a função devolvida (que para o GPS, uma vez, e faz o que ainda chegar não contar).
//  - aoMudar({lat, lng, precisao_m}): uma leitura boa; as que não servem não chegam;
//  - aoFalhar({codigo, mensagem}): o browser falhou (em pt-PT, com os códigos do obterPosicao). O browser continua a
//    seguir depois de um "tempo esgotado": é quem chama que decide se para. Sem GPS, ou se o browser lançar um erro,
//    chega logo aqui, antes de esta função voltar.
export function seguirPosicao(geolocation, { aoMudar, aoFalhar }) {
  if (!geolocation || typeof geolocation.watchPosition !== 'function') {
    aoFalhar({ ...SEM_GPS_NO_SEGUIMENTO });
    return () => {};
  }
  let parado = false;
  let id;
  try {
    id = geolocation.watchPosition(
      (posicao) => {
        const leitura = parado ? null : leituraDe(posicao);
        if (leitura !== null) aoMudar(leitura);
      },
      (erro) => {
        if (!parado) aoFalhar(traduzirErro(ERROS_SEGUIMENTO, erro));
      },
      { ...OPCOES_SEGUIMENTO },
    );
  } catch {
    aoFalhar(traduzirErro(ERROS_SEGUIMENTO, null));
    return () => {};
  }
  return () => {
    if (parado) return;
    parado = true;
    try {
      geolocation.clearWatch(id);
    } catch {
      // Sair do ecrã nunca pode rebentar por causa do GPS; o que ainda chegar já não conta.
    }
  };
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
