/**
 * O GPS DE "ESTOU NESTA LOJA" — só se pede quando a pessoa toca no botão.
 *
 * Porta de tests/js/gps.test.js do CRM autónomo (etiqueta
 * `referencia-standalone`), com o `node:assert` passado a `expect`: o limite
 * de 50 m, as opções `{enableHighAccuracy: true, timeout: 15000,
 * maximumAge: 0}`, as mensagens em pt-PT e o retângulo do círculo da
 * precisão. O `geolocation` é falso e entra por parâmetro.
 *
 * `LIMITE_PRECISAO_M` e `MENSAGEM_LOCALIZACAO_IMPRECISA` têm de ser os do
 * servidor (`backend/crm/dominio/geo.py`, `LIMITE_PRECISAO_M` e
 * `MENSAGEM_GPS`): quem o vigia é o
 * `backend/tests/crm/test_consistencia_frontend.py`, que lê este `gps.js`
 * (plano T2.22).
 *
 * Os quatro últimos testes são extra: nunca há seguimento contínuo (desenho
 * §4.4: guarda-se só o ponto da loja), um `geolocation` sem
 * `getCurrentPosition` também é "sem GPS", o `traduzirErroGps` devolve sempre
 * uma cópia, e as opções passadas ao browser são uma cópia das congeladas.
 */
import {
  LIMITE_PRECISAO_M,
  OPCOES_GPS,
  avaliarPrecisao,
  obterPosicao,
  traduzirErroGps,
  limitesDoCirculo,
  MENSAGEM_PERMISSAO_NEGADA,
  MENSAGEM_LOCALIZACAO_IMPRECISA,
} from './gps';

const POSICAO_INDISPONIVEL = {
  codigo: 'posicao_indisponivel',
  mensagem: 'Não foi possível obter a localização — coloque o pino no mapa',
};

function geoQueResponde(posicao) {
  const chamadas = [];
  return {
    chamadas,
    getCurrentPosition(sucesso, _erro, opcoes) {
      chamadas.push(opcoes);
      sucesso(posicao);
    },
  };
}

// O erro com que a promessa rejeita; se resolver, o teste falha.
function rejeicao(promessa) {
  return promessa.then(
    (valor) => {
      throw new Error(`devia ter rejeitado, resolveu com ${JSON.stringify(valor)}`);
    },
    (erro) => erro,
  );
}

// Só o código e a mensagem, para comparar com toEqual (formas exatas, dossiê §2.1).
const codigoEMensagem = (erro) => ({ codigo: erro.codigo, mensagem: erro.mensagem });

function geoQueFalha(code) {
  return {
    getCurrentPosition(_sucesso, erro) {
      erro({ code, message: 'erro do browser', PERMISSION_DENIED: 1, POSITION_UNAVAILABLE: 2, TIMEOUT: 3 });
    },
  };
}

test('LIMITE_PRECISAO_M é 50', () => {
  expect(LIMITE_PRECISAO_M).toBe(50);
});

test('avaliarPrecisao: 50 é ok, 51 é imprecisa', () => {
  expect(avaliarPrecisao(50)).toBe('ok');
  expect(avaliarPrecisao(0)).toBe('ok');
  expect(avaliarPrecisao(51)).toBe('imprecisa');
  expect(avaliarPrecisao(50.4)).toBe('imprecisa');
});

test('avaliarPrecisao: valor em falta ou inválido é imprecisa', () => {
  expect(avaliarPrecisao(null)).toBe('imprecisa');
  expect(avaliarPrecisao(undefined)).toBe('imprecisa');
  expect(avaliarPrecisao(Number.NaN)).toBe('imprecisa');
  expect(avaliarPrecisao(-1)).toBe('imprecisa');
});

test('obterPosicao usa alta precisão, 15 s de tempo limite e sem cache', async () => {
  const geo = geoQueResponde({ coords: { latitude: 38.7075, longitude: -9.1364, accuracy: 12 } });
  await obterPosicao(geo);
  expect(geo.chamadas).toEqual([{ enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }]);
  expect(OPCOES_GPS).toEqual({ enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
});

test('obterPosicao devolve lat, lng e precisão arredondada', async () => {
  const geo = geoQueResponde({ coords: { latitude: 38.7075, longitude: -9.1364, accuracy: 12.6 } });
  expect(await obterPosicao(geo)).toEqual({ lat: 38.7075, lng: -9.1364, precisao_m: 13 });
});

test('obterPosicao: permissão negada rejeita com a mensagem pt', async () => {
  const mensagem = "Autorize a localização no browser para usar 'Estou nesta loja'";
  const erro = await rejeicao(obterPosicao(geoQueFalha(1)));
  expect(erro).toBeInstanceOf(Error);
  expect(codigoEMensagem(erro)).toEqual({ codigo: 'permissao_negada', mensagem });
  expect(erro.message).toBe(erro.mensagem);
  expect(MENSAGEM_PERMISSAO_NEGADA).toBe(mensagem);
});

test('obterPosicao: posição indisponível e tempo esgotado têm mensagens pt', async () => {
  expect(codigoEMensagem(await rejeicao(obterPosicao(geoQueFalha(2))))).toEqual(POSICAO_INDISPONIVEL);
  expect(codigoEMensagem(await rejeicao(obterPosicao(geoQueFalha(3))))).toEqual({
    codigo: 'tempo_esgotado',
    mensagem: 'A localização demorou demasiado — tente outra vez ou coloque o pino no mapa',
  });
});

test('obterPosicao: sem geolocalização no browser rejeita sem rebentar', async () => {
  expect(codigoEMensagem(await rejeicao(obterPosicao(undefined)))).toEqual({
    codigo: 'sem_gps',
    mensagem: 'Este browser não permite obter a localização — coloque o pino no mapa',
  });
});

test('traduzirErroGps: código desconhecido cai em posição indisponível', () => {
  expect(traduzirErroGps({ code: 99 })).toEqual(POSICAO_INDISPONIVEL);
  expect(traduzirErroGps(undefined)).toEqual(POSICAO_INDISPONIVEL);
});

test('MENSAGEM_LOCALIZACAO_IMPRECISA é o texto exato do plano', () => {
  expect(MENSAGEM_LOCALIZACAO_IMPRECISA).toBe('Localização imprecisa — ajuste o pino');
});

test('traduzirErroGps: nomes herdados de Object não são códigos de erro', () => {
  for (const code of ['constructor', '__proto__', 'toString']) {
    expect(traduzirErroGps({ code })).toEqual(POSICAO_INDISPONIVEL);
  }
});

test('obterPosicao: getCurrentPosition que lança rejeita com codigo e mensagem pt', async () => {
  const geo = {
    getCurrentPosition() {
      throw new TypeError('Illegal invocation');
    },
  };
  expect(codigoEMensagem(await rejeicao(obterPosicao(geo)))).toEqual(POSICAO_INDISPONIVEL);
});

test('obterPosicao: precisão em falta ou inválida fica null (nunca NaN)', async () => {
  for (const accuracy of [undefined, null, Number.NaN]) {
    const geo = geoQueResponde({ coords: { latitude: 38.7075, longitude: -9.1364, accuracy } });
    const posicao = await obterPosicao(geo);
    expect(posicao).toEqual({ lat: 38.7075, lng: -9.1364, precisao_m: null });
    expect(avaliarPrecisao(posicao.precisao_m)).toBe('imprecisa');
  }
});

// --- O círculo da precisão no mapa (E7) ----------------------------------------------------------

// Distância em metros entre dois pontos (haversine), para medir os limites sem depender da fórmula.
function metros([lat1, lng1], [lat2, lng2]) {
  const r = 6371008.8;
  const rad = (g) => (g * Math.PI) / 180;
  const a = Math.sin(rad(lat2 - lat1) / 2) ** 2 + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(rad(lng2 - lng1) / 2) ** 2;
  return 2 * r * Math.asin(Math.sqrt(a));
}

test('limitesDoCirculo: o retângulo [[sul, oeste], [norte, este]] que contém o círculo da precisão', () => {
  const centro = { lat: 38.7075, lng: -9.1364 };
  const [[sul, oeste], [norte, este]] = limitesDoCirculo(centro, 120);
  expect(sul).toBeLessThan(centro.lat);
  expect(centro.lat).toBeLessThan(norte);
  expect(oeste).toBeLessThan(centro.lng);
  expect(centro.lng).toBeLessThan(este);
  // De sul a norte, o diâmetro.
  expect(Math.abs(metros([sul, centro.lng], [norte, centro.lng]) - 240)).toBeLessThan(1);
  // De oeste a este, o diâmetro (na latitude da loja).
  expect(Math.abs(metros([centro.lat, oeste], [centro.lat, este]) - 240)).toBeLessThan(1);
  expect(Math.abs((sul + norte) / 2 - centro.lat)).toBeLessThan(1e-9);
  expect(Math.abs((oeste + este) / 2 - centro.lng)).toBeLessThan(1e-9);
});

test('limitesDoCirculo: sem centro ou sem raio positivo, null', () => {
  const centro = { lat: 38.7075, lng: -9.1364 };
  for (const raio of [null, undefined, 0, -5, Number.NaN, Infinity, '50']) {
    expect(limitesDoCirculo(centro, raio)).toBeNull();
  }
  for (const invalido of [null, undefined, {}, { lat: '38.7', lng: -9.1 }, { lat: 38.7, lng: Number.NaN }]) {
    expect(limitesDoCirculo(invalido, 50)).toBeNull();
  }
});

// --- Extra (portal) ------------------------------------------------------------------------------

test('obterPosicao pede a posição uma só vez e nunca segue a pessoa (sem watchPosition)', async () => {
  const pedidos = [];
  const seguimentos = [];
  const geo = {
    getCurrentPosition(sucesso, _erro, opcoes) {
      pedidos.push(opcoes);
      sucesso({ coords: { latitude: 38.7075, longitude: -9.1364, accuracy: 8 } });
    },
    watchPosition(...argumentos) {
      seguimentos.push(argumentos);
      return 1;
    },
  };
  expect(await obterPosicao(geo)).toEqual({ lat: 38.7075, lng: -9.1364, precisao_m: 8 });
  expect(pedidos).toHaveLength(1);
  expect(seguimentos).toHaveLength(0);
});

test('obterPosicao: um geolocation sem getCurrentPosition também é "sem GPS"', async () => {
  for (const geo of [{}, { getCurrentPosition: 'não é função' }, null]) {
    expect(codigoEMensagem(await rejeicao(obterPosicao(geo)))).toEqual({
      codigo: 'sem_gps',
      mensagem: 'Este browser não permite obter a localização — coloque o pino no mapa',
    });
  }
});

test('traduzirErroGps devolve uma cópia: mudar o resultado não muda o seguinte', () => {
  const primeiro = traduzirErroGps({ code: 1 });
  primeiro.mensagem = 'outra';
  primeiro.codigo = 'outro';
  expect(traduzirErroGps({ code: 1 })).toEqual({
    codigo: 'permissao_negada',
    mensagem: MENSAGEM_PERMISSAO_NEGADA,
  });
});

test('OPCOES_GPS está congelado e o browser recebe uma cópia', async () => {
  expect(Object.isFrozen(OPCOES_GPS)).toBe(true);
  const geo = geoQueResponde({ coords: { latitude: 38.7075, longitude: -9.1364, accuracy: 12 } });
  await obterPosicao(geo);
  expect(geo.chamadas[0]).not.toBe(OPCOES_GPS);
  expect(Object.isFrozen(geo.chamadas[0])).toBe(false);
});
