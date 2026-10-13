/**
 * O SELETOR DA LOCALIZAÇÃO — pino no mapa, pesquisa de morada e "Estou nesta
 * loja", sem DOM.
 *
 * Porta de tests/js/seletor-localizacao.test.js do CRM autónomo (etiqueta
 * `referencia-standalone`), sobre o `criarSeletor` de `seletor.js`, que guarda
 * as regras do componente do autónomo (`componentes/seletor-localizacao.js`)
 * fora do React (plano T2.26; correção "T2.26 / T2.27 / T2.29 / T2.30
 * (componentes "Sem Jest")", na parte do seletor da T2.24a). O
 * `components/crm/SeletorLocalizacao.js` só desenha a `vista` e liga os
 * botões.
 *
 * O Leaflet é o falso de `testes/leafletFalso.js` (o mesmo do autónomo), e no
 * fim alguns casos correm sobre o Leaflet 1.9.4 verdadeiro no jsdom (como o
 * `mapa.test.js`). O que no autónomo se via no DOM vê-se aqui na `vista`: a
 * dica, o aviso, o erro, o Confirmar ativo, o botão e a mensagem do GPS, a
 * morada sugerida (em partes: texto e ligação) e a pesquisa. O foco que o
 * autónomo mudava (Confirmar ↔ Alterar) chega ao componente pelo `aoFocar`.
 * Ficam para o componente (verificação no browser) o título, os nomes da área
 * e do pino para os leitores de ecrã, o `aria-describedby` do erro, o
 * `aria-live` das mensagens e a ordem dos blocos.
 *
 * Adaptações ao portal: a `api` é a do `lib/crm/api.js`
 * (`pesquisarMorada({texto, lat, lng})` e `moradaInversa({lat, lng})`, com os
 * caminhos `/api/crm/morada/…`), e o elemento do mapa entra no `iniciar`. O
 * `mock.timers` passou a `jest.useFakeTimers()` (plano §10). Os falsos nascem
 * em cada teste (o CRA corre com `resetMocks`).
 *
 * A mais: a `vista` é a mesma que chega ao `aoMudarVista`, nova a cada mudança
 * e congelada; nada chega depois de destruir; `redimensionar`; os textos por
 * omissão e os da fábrica; e o pino no Leaflet verdadeiro (a div vazia da
 * gota, arrastável até confirmar).
 */
import * as LeafletVerdadeiro from 'leaflet';
import {
  criarSeletor,
  textosSeletor,
  partesMoradaSugerida,
  TEXTOS_LOJA,
  TEXTO_TOCAR_NO_MAPA,
  TEXTO_ARRASTAR,
  TEXTO_CONFIRMADA,
  TEXTO_CONFIRMAR,
  TEXTO_ALTERAR,
  TEXTO_ESTOU_NESTA_LOJA,
  TEXTO_A_OBTER_LOCALIZACAO,
  TEXTO_A_PROCURAR_MORADA,
  ZOOM_MORADA,
  ZOOM_GPS,
} from './seletor';
import { MENSAGEM_SEM_MAPA, ZOOM_SEM_LOJAS } from './mapa';
import {
  MENSAGEM_LOCALIZACAO_IMPRECISA, MENSAGEM_PERMISSAO_NEGADA, OPCOES_GPS, limitesDoCirculo,
} from './gps';
import { MENSAGEM_MORADA_INDISPONIVEL, MENSAGEM_MORADA_SUGERIDA_INDISPONIVEL } from './morada';
import { ATRIBUICOES } from './atribuicoes';
import { leafletFalso } from './testes/leafletFalso';
import { documentoFalso } from './testes/domFalso';

const CONFIGURACAO = {
  mosaicos: { url: 'http://127.0.0.1:8099/mosaicos/{z}/{x}/{y}.png?apiKey=chave-teste-mosaicos', atribuicao: 'geoapify' },
  alternativa: { url: 'http://127.0.0.1:8099/osm/{z}/{x}/{y}.png' },
  centro: { lat: 38.7223, lng: -9.1393 },
};

// Cria o seletor como um ecrã: a área do mapa já está na página quando se inicia (o Leaflet mede-a).
function preparar({ configuracao = CONFIGURACAO, semLeaflet = false, iniciar = true, textos } = {}) {
  const { L, registo } = leafletFalso();
  const documento = documentoFalso();
  const elemento = documento.createElement('div');
  documento.body.appendChild(elemento);
  const mudancas = [];
  const focos = [];
  const vistas = [];
  const seletor = criarSeletor({
    L: semLeaflet ? undefined : L,
    documento,
    configuracao,
    textos,
    aoMudar: (localizacao) => mudancas.push(localizacao),
    aoFocar: (alvo) => focos.push(alvo),
    aoMudarVista: (vista) => vistas.push(vista),
  });
  const iniciado = iniciar ? seletor.iniciar(elemento) : null;
  return {
    documento, elemento, registo, seletor, mudancas, focos, vistas, iniciado, leaflet: () => registo.mapas[0],
  };
}

const tocar = (leaflet, lat, lng) => leaflet.fire('click', { latlng: { lat, lng } });
const pino = (leaflet) => {
  expect(leaflet.marcadores.length).toBe(1); // um só pino
  return leaflet.marcadores[0];
};
const texto = (partes) => partes.map((p) => p.texto).join('');
const moradaSugerida = (seletor) => (seletor.vista.moradaSugerida ? texto(seletor.vista.moradaSugerida.partes) : '');

test('antes de iniciar: a dica para tocar no mapa, "Confirmar localização" desativado e sem mapa', () => {
  const { seletor, registo } = preparar({ iniciar: false });
  expect(seletor.vista.dica).toBe(TEXTO_TOCAR_NO_MAPA);
  expect(TEXTO_TOCAR_NO_MAPA).toBe('Toque no mapa no sítio da loja.');
  expect(seletor.vista.estado).toBe('vazio');
  expect(seletor.vista.confirmarAtivo).toBe(false);
  expect(seletor.vista.aviso).toBeNull();
  expect(seletor.vista.erro).toBeNull();
  expect(seletor.vista.semMapa).toBe(false);
  expect(seletor.localizacao).toBeNull();
  expect(seletor.mapa).toBeNull();
  expect(registo.mapas.length).toBe(0); // o mapa só se cria em iniciar(), com a área já na página
});

test('os textos dos botões e os da loja (título, dica, área do mapa e pino)', () => {
  expect(TEXTO_CONFIRMAR).toBe('Confirmar localização');
  expect(TEXTO_ALTERAR).toBe('Alterar localização');
  expect(TEXTOS_LOJA).toEqual({
    titulo: 'Localização', tocar: TEXTO_TOCAR_NO_MAPA, mapa: 'Mapa para pôr o pino da loja', pino: 'Pino da loja',
  });
  expect(textosSeletor()).toEqual(TEXTOS_LOJA);
  expect(textosSeletor({})).toEqual(TEXTOS_LOJA);
  expect(Object.isFrozen(TEXTOS_LOJA)).toBe(true);
});

test('com `textos` (o ponto da fábrica): o título, a dica, o nome do mapa e o do pino são os dados', () => {
  const textos = { titulo: 'Ponto da fábrica', tocar: 'Toque no mapa no sítio da fábrica.', mapa: 'Mapa da fábrica', pino: 'Pino da fábrica' };
  expect(textosSeletor(textos)).toEqual(textos);
  expect(textosSeletor({ titulo: 'Ponto da fábrica' })).toEqual({ ...TEXTOS_LOJA, titulo: 'Ponto da fábrica' });
  const { seletor, leaflet, elemento } = preparar({ iniciar: false, textos });
  expect(seletor.vista.dica).toBe('Toque no mapa no sítio da fábrica.');
  seletor.iniciar(elemento, { inicial: { lat: 38.7223, lng: -9.1393, origem: 'pin_manual' } });
  expect(pino(leaflet()).options.title).toBe('Pino da fábrica');
  expect(seletor.vista.dica).toBe(TEXTO_ARRASTAR);
});

test('sem `textos`: os da loja (o título do pino incluído)', () => {
  const { leaflet } = preparar();
  tocar(leaflet(), 38.71, -9.14);
  expect(pino(leaflet()).options.title).toBe('Pino da loja');
});

test('iniciar cria o mapa no elemento, com a atribuição da sessão, no centro das definições (zoom 12)', () => {
  const { seletor, iniciado, leaflet, elemento } = preparar();
  expect(iniciado).toBe(true);
  expect(leaflet().elemento).toBe(elemento);
  expect(leaflet().attributionControl.html).toBe(ATRIBUICOES.geoapify.html);
  expect(leaflet().vistas).toEqual([{ tipo: 'setView', centro: [38.7223, -9.1393], zoom: ZOOM_SEM_LOJAS }]);
  expect(seletor.mapa.mapa).toBe(leaflet()); // o mapa fica disponível (o círculo da precisão)
  expect(seletor.iniciar(elemento)).toBe(true); // já iniciado
});

test('iniciar duas vezes não cria um segundo mapa', () => {
  const { seletor, registo, elemento } = preparar();
  seletor.iniciar(elemento);
  expect(registo.mapas.length).toBe(1);
});

// A ficha (T2.28) corrige a localização a partir da que a loja já tem.
const GUARDADA = { lat: 38.70921, lng: -9.13712, origem: 'gps', precisao_m: 12 };

test('iniciar com a localização inicial (ficha): o pino solto nesse sítio, à escala da rua, numa só vista', () => {
  const { seletor, leaflet, mudancas, elemento } = preparar({ iniciar: false });
  expect(seletor.iniciar(elemento, { inicial: GUARDADA })).toBe(true);
  // Sem passar pelo centro das definições (não se pedem os mosaicos de duas vistas).
  expect(leaflet().vistas).toEqual([{ tipo: 'setView', centro: [38.70921, -9.13712], zoom: ZOOM_MORADA }]);
  expect(pino(leaflet()).getLatLng()).toEqual({ lat: 38.70921, lng: -9.13712 });
  expect(pino(leaflet()).dragging.enabled()).toBe(true);
  expect(seletor.vista.estado).toBe('por_confirmar');
  expect(seletor.vista.dica).toBe(TEXTO_ARRASTAR);
  expect(seletor.localizacao).toBeNull();
  expect(mudancas).toEqual([]);
  expect(leaflet().circulos.length).toBe(0); // o círculo é só de uma leitura nova do GPS
});

test('iniciar com a localização inicial e confirmar sem mexer: a mesma localização, com a mesma origem', () => {
  const { seletor, elemento } = preparar({ iniciar: false });
  seletor.iniciar(elemento, { inicial: GUARDADA });
  seletor.confirmar();
  expect(seletor.localizacao).toEqual({ lat: 38.70921, lng: -9.13712, origem_coords: 'gps', precisao_m: 12 });
});

test('iniciar com a localização inicial e arrastar: passa a pin_manual', () => {
  const { seletor, leaflet, elemento } = preparar({ iniciar: false });
  seletor.iniciar(elemento, { inicial: { lat: 38.70921, lng: -9.13712, origem: 'geocoder' } });
  pino(leaflet()).arrastarPara(38.7093, -9.1372);
  seletor.confirmar();
  expect(seletor.localizacao).toEqual({ lat: 38.7093, lng: -9.1372, origem_coords: 'pin_manual', precisao_m: null });
});

test('iniciar com uma localização inicial inválida: o centro das definições, sem pino', () => {
  const { seletor, leaflet, elemento } = preparar({ iniciar: false });
  expect(seletor.iniciar(elemento, { inicial: { lat: null, lng: -9.1 } })).toBe(true);
  expect(leaflet().vistas).toEqual([{ tipo: 'setView', centro: [38.7223, -9.1393], zoom: ZOOM_SEM_LOJAS }]);
  expect(leaflet().marcadores.length).toBe(0);
});

test('sem Leaflet ou sem configuração do mapa: mostra a mensagem e não deixa confirmar', () => {
  for (const opcoes of [{ semLeaflet: true }, { configuracao: null }, { configuracao: { mosaicos: { url: '' } } }]) {
    const { seletor, iniciado, registo, elemento } = preparar(opcoes);
    expect(iniciado).toBe(false);
    expect(registo.mapas.length).toBe(0);
    expect(seletor.vista.semMapa).toBe(true);
    expect(seletor.vista.erro).toBe(MENSAGEM_SEM_MAPA);
    expect(seletor.vista.confirmarAtivo).toBe(false);
    expect(seletor.colocar({ lat: 38.71, lng: -9.14, origem: 'geocoder' })).toBe(false);
    expect(seletor.iniciar(elemento)).toBe(false); // sem mapa uma vez, sem mapa sempre
  }
});

test('se o Leaflet rebentar uma vez, o seletor fica sem mapa (não tenta outra vez)', () => {
  const { L: falso } = leafletFalso();
  let tentativas = 0;
  const L = {
    ...falso,
    map: (...args) => {
      tentativas += 1;
      if (tentativas === 1) throw new Error('sem tamanho');
      return falso.map(...args);
    },
  };
  const documento = documentoFalso();
  const seletor = criarSeletor({ L, documento, configuracao: CONFIGURACAO });
  const elemento = documento.createElement('div');
  expect(seletor.iniciar(elemento)).toBe(false);
  expect(seletor.iniciar(elemento)).toBe(false);
  expect(tentativas).toBe(1);
  expect(seletor.mapa).toBeNull();
  expect(seletor.vista.semMapa).toBe(true);
});

test('sem mapa, limparErro não tira a mensagem do mapa (o ecrã limpa os erros ao guardar)', () => {
  const { seletor } = preparar({ configuracao: null });
  seletor.limparErro();
  expect(seletor.vista.erro).toBe(MENSAGEM_SEM_MAPA);
});

test('se o Leaflet rebentar ao criar o mapa: a mesma mensagem', () => {
  const documento = documentoFalso();
  const L = { map: () => { throw new Error('sem tamanho'); } };
  const seletor = criarSeletor({ L, documento, configuracao: CONFIGURACAO });
  expect(seletor.iniciar(documento.createElement('div'))).toBe(false);
  expect(seletor.vista.erro).toBe(MENSAGEM_SEM_MAPA);
  expect(seletor.vista.semMapa).toBe(true);
});

test('tocar no mapa põe lá um pino arrastável (44 px, ponta no sítio) e deixa confirmar', () => {
  const { seletor, leaflet, mudancas } = preparar();
  tocar(leaflet(), 38.7101, -9.1402);
  const marcador = pino(leaflet());
  expect(marcador.getLatLng()).toEqual({ lat: 38.7101, lng: -9.1402 });
  expect(marcador.dragging.enabled()).toBe(true);
  const icone = marcador.options.icon.options;
  expect(icone.className).toBe('pino-seletor');
  expect(icone.iconSize).toEqual([44, 44]);
  expect(icone.iconAnchor).toEqual([22, 38]);
  expect(icone.html).toBeUndefined(); // o ícone não leva HTML
  expect(marcador.options.title).toBe('Pino da loja');
  expect(marcador.options.draggable).toBe(true);
  expect(marcador.options.keyboard).toBe(true);
  expect(marcador.options.autoPan).toBe(true);
  expect(marcador.options.zIndexOffset).toBe(1000);
  expect(seletor.vista.dica).toBe(TEXTO_ARRASTAR);
  expect(TEXTO_ARRASTAR).toBe('Arraste o pino para o sítio exato e confirme.');
  expect(seletor.vista.confirmarAtivo).toBe(true);
  expect(seletor.vista.estado).toBe('por_confirmar');
  expect(seletor.localizacao).toBeNull(); // só conta depois de confirmar
  expect(mudancas).toEqual([]);
  expect(leaflet().vistas.length).toBe(1); // o mapa não salta para o pino
});

test('tocar outra vez muda o mesmo pino de sítio', () => {
  const { leaflet } = preparar();
  tocar(leaflet(), 38.71, -9.14);
  const primeiro = pino(leaflet());
  tocar(leaflet(), 38.72, -9.15);
  expect(pino(leaflet())).toBe(primeiro);
  expect(primeiro.getLatLng()).toEqual({ lat: 38.72, lng: -9.15 });
});

test('um toque no mapa sem ponto não faz nada', () => {
  const { leaflet, seletor } = preparar();
  leaflet().fire('click');
  expect(leaflet().marcadores.length).toBe(0);
  expect(seletor.vista.confirmarAtivo).toBe(false);
});

test('Confirmar: fixa o pino, avisa com a localização (pin_manual) e o foco passa a "Alterar localização"', () => {
  const { seletor, leaflet, mudancas, focos } = preparar();
  tocar(leaflet(), 38.7101, -9.1402);
  seletor.confirmar();
  const localizacao = { lat: 38.7101, lng: -9.1402, origem_coords: 'pin_manual', precisao_m: null };
  expect(seletor.localizacao).toEqual(localizacao);
  expect(mudancas).toEqual([localizacao]);
  expect(pino(leaflet()).dragging.enabled()).toBe(false); // confirmado, o pino já não se arrasta
  expect(seletor.vista.dica).toBe(TEXTO_CONFIRMADA);
  expect(TEXTO_CONFIRMADA).toBe('Localização confirmada.');
  expect(seletor.vista.estado).toBe('confirmado');
  // O foco não se perde com o botão que desaparece.
  expect(focos).toEqual(['alterar']);
});

test('Confirmar outra vez, ou sem pino, não faz nada', () => {
  const { seletor, leaflet, mudancas, focos } = preparar();
  seletor.confirmar();
  expect(seletor.vista.estado).toBe('vazio');
  tocar(leaflet(), 38.71, -9.14);
  seletor.confirmar();
  seletor.confirmar();
  expect(mudancas.length).toBe(1);
  expect(focos).toEqual(['alterar']);
});

test('confirmado, um toque no mapa não mexe no pino', () => {
  const { seletor, leaflet, mudancas } = preparar();
  tocar(leaflet(), 38.71, -9.14);
  seletor.confirmar();
  tocar(leaflet(), 38.75, -9.2);
  expect(pino(leaflet()).getLatLng()).toEqual({ lat: 38.71, lng: -9.14 });
  expect(mudancas.length).toBe(1);
});

test('"Alterar localização" volta a soltar o pino e avisa que já não há localização confirmada', () => {
  const { seletor, leaflet, mudancas, focos } = preparar();
  tocar(leaflet(), 38.71, -9.14);
  seletor.confirmar();
  seletor.alterar();
  expect(seletor.localizacao).toBeNull();
  expect(mudancas.at(-1)).toBeNull();
  expect(pino(leaflet()).dragging.enabled()).toBe(true);
  expect(seletor.vista.estado).toBe('por_confirmar');
  expect(focos).toEqual(['alterar', 'confirmar']);
  expect(seletor.vista.dica).toBe(TEXTO_ARRASTAR);
  seletor.alterar(); // por confirmar, não faz nada
  expect(focos).toEqual(['alterar', 'confirmar']);
  expect(mudancas.length).toBe(2);
});

test('arrastar o pino: confirma o sítio para onde foi arrastado', () => {
  const { seletor, leaflet } = preparar();
  tocar(leaflet(), 38.71, -9.14);
  pino(leaflet()).arrastarPara(38.7112, -9.1388);
  seletor.confirmar();
  expect(seletor.localizacao).toEqual({ lat: 38.7112, lng: -9.1388, origem_coords: 'pin_manual', precisao_m: null });
});

test('colocar (pesquisa de morada): pino da sugestão, aproxima no zoom pedido e a origem é geocoder', () => {
  const { seletor, leaflet } = preparar();
  expect(seletor.colocar({ lat: 38.7098, lng: -9.1365, origem: 'geocoder' }, { zoom: 18 })).toBe(true);
  expect(leaflet().vistas.at(-1)).toEqual({ tipo: 'setView', centro: [38.7098, -9.1365], zoom: 18 });
  expect(pino(leaflet()).dragging.enabled()).toBe(true);
  seletor.confirmar();
  expect(seletor.localizacao).toEqual({ lat: 38.7098, lng: -9.1365, origem_coords: 'geocoder', precisao_m: null });
});

test('colocar e depois arrastar: a origem passa a pin_manual', () => {
  const { seletor, leaflet } = preparar();
  seletor.colocar({ lat: 38.7098, lng: -9.1365, origem: 'geocoder' });
  pino(leaflet()).arrastarPara(38.7099, -9.1366);
  seletor.confirmar();
  expect(seletor.localizacao).toEqual({ lat: 38.7099, lng: -9.1366, origem_coords: 'pin_manual', precisao_m: null });
});

test('colocar sem origem: pin_manual', () => {
  const { seletor } = preparar();
  seletor.colocar({ lat: 38.7098, lng: -9.1365 });
  seletor.confirmar();
  expect(seletor.localizacao.origem_coords).toBe('pin_manual');
});

test('GPS com boa precisão: confirma sem arrastar, com origem gps e a precisão', () => {
  const { seletor } = preparar();
  seletor.colocar({ lat: 38.7105, lng: -9.1366, origem: 'gps', precisao_m: 20 });
  expect(seletor.vista.confirmarAtivo).toBe(true);
  seletor.confirmar();
  expect(seletor.localizacao).toEqual({ lat: 38.7105, lng: -9.1366, origem_coords: 'gps', precisao_m: 20 });
});

test('GPS impreciso (> 50 m): "Localização imprecisa — ajuste o pino" e só confirma depois de arrastar', () => {
  const { seletor, leaflet } = preparar();
  seletor.colocar({ lat: 38.7105, lng: -9.1366, origem: 'gps', precisao_m: 120 });
  expect(seletor.vista.dica).toBe(MENSAGEM_LOCALIZACAO_IMPRECISA);
  expect(seletor.vista.aviso).toBe('imprecisa');
  expect(seletor.vista.confirmarAtivo).toBe(false);
  seletor.confirmar();
  expect(seletor.localizacao).toBeNull();
  pino(leaflet()).arrastarPara(38.7106, -9.1367);
  expect(seletor.vista.confirmarAtivo).toBe(true);
  expect(seletor.vista.dica).toBe(TEXTO_ARRASTAR);
  expect(seletor.vista.aviso).toBeNull();
  seletor.confirmar();
  expect(seletor.localizacao).toEqual({ lat: 38.7106, lng: -9.1367, origem_coords: 'pin_manual', precisao_m: null });
});

test('colocar depois de confirmar: volta a pedir confirmação', () => {
  const { seletor, leaflet, mudancas } = preparar();
  tocar(leaflet(), 38.71, -9.14);
  seletor.confirmar();
  seletor.colocar({ lat: 38.7098, lng: -9.1365, origem: 'geocoder' });
  expect(seletor.localizacao).toBeNull();
  expect(mudancas.at(-1)).toBeNull();
  expect(pino(leaflet()).dragging.enabled()).toBe(true);
  expect(pino(leaflet()).getLatLng()).toEqual({ lat: 38.7098, lng: -9.1365 });
  expect(seletor.vista.estado).toBe('por_confirmar');
});

test('colocar sem coordenadas válidas não faz nada', () => {
  const { seletor, leaflet } = preparar();
  for (const posicao of [null, {}, { lat: '38.7', lng: -9.1 }, { lat: Number.NaN, lng: -9.1 }]) {
    expect(seletor.colocar(posicao)).toBe(false);
  }
  expect(leaflet().marcadores.length).toBe(0);
});

test('mostrarErro (ex.: 422 "Fora de Portugal") aparece junto ao mapa; colocar outro pino limpa-o', () => {
  const { seletor, leaflet } = preparar();
  tocar(leaflet(), 38.71, -9.14);
  seletor.mostrarErro('Fora de Portugal');
  expect(seletor.vista.erro).toBe('Fora de Portugal');
  tocar(leaflet(), 38.72, -9.15);
  expect(seletor.vista.erro).toBeNull();
  seletor.mostrarErro('Fora de Portugal');
  seletor.limparErro();
  expect(seletor.vista.erro).toBeNull();
});

test('desconfirmar (a API recusou a localização): volta a soltar o pino', () => {
  const { seletor, leaflet, mudancas } = preparar();
  tocar(leaflet(), 38.71, -9.14);
  seletor.confirmar();
  seletor.desconfirmar();
  expect(seletor.localizacao).toBeNull();
  expect(mudancas).toEqual([{ lat: 38.71, lng: -9.14, origem_coords: 'pin_manual', precisao_m: null }, null]);
  expect(pino(leaflet()).dragging.enabled()).toBe(true);
  seletor.desconfirmar();
  expect(mudancas.length).toBe(2); // sem localização confirmada não volta a avisar
});

test('desconfirmar sem localização confirmada não faz nada (nem sem pino)', () => {
  const { seletor, leaflet, mudancas } = preparar();
  seletor.desconfirmar();
  expect(seletor.vista.estado).toBe('vazio');
  tocar(leaflet(), 38.71, -9.14);
  pino(leaflet()).dragging.disable();
  seletor.desconfirmar();
  expect(pino(leaflet()).dragging.enabled()).toBe(false);
  expect(mudancas).toEqual([]);
});

test('focar põe o foco no botão de confirmar (ao lado do erro); confirmado, no de alterar', () => {
  const { seletor, leaflet, focos } = preparar();
  tocar(leaflet(), 38.71, -9.14);
  seletor.focar();
  expect(focos).toEqual(['confirmar']);
  seletor.confirmar();
  seletor.focar();
  expect(focos).toEqual(['confirmar', 'alterar', 'alterar']);
});

test('destruir remove o mapa do Leaflet', () => {
  const { seletor, leaflet } = preparar();
  seletor.destruir();
  expect(leaflet().removido).toBe(true);
  expect(seletor.mapa).toBeNull();
  seletor.destruir();
  expect(seletor.colocar({ lat: 38.71, lng: -9.14, origem: 'geocoder' })).toBe(false);
});

// --- Pesquisa de morada --------------------------------------------------------------------------

const AUGUSTA_24 = { rotulo: 'Rua Augusta 24, 1100-048 Lisboa, Portugal', morada: 'Rua Augusta 24', codigo_postal: '1100-048', localidade: 'Lisboa', lat: 38.70921, lng: -9.13712 };

async function esvaziar() {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
}

// A api do portal (lib/crm/api.js) falsa: cada pedido fica pendente até o teste lhe responder.
function apiFalsa() {
  const pedidos = [];
  const pendente = (caminho) => (parametros) => new Promise((resolver, rejeitar) => {
    pedidos.push({ caminho, parametros, resolver, rejeitar });
  });
  return { pedidos, api: { pesquisarMorada: pendente('pesquisa'), moradaInversa: pendente('inversa') } };
}

describe('pesquisa de morada', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  // O seletor com a api (a pesquisa de morada aparece).
  function prepararComPesquisa({ semLeaflet = false, iniciar = true } = {}) {
    const { L, registo } = leafletFalso();
    const documento = documentoFalso();
    const elemento = documento.createElement('div');
    const { pedidos, api } = apiFalsa();
    const escolhidas = [];
    const mudancas = [];
    const focos = [];
    const seletor = criarSeletor({
      L: semLeaflet ? undefined : L,
      documento,
      configuracao: CONFIGURACAO,
      api,
      aoMudar: (localizacao) => mudancas.push(localizacao),
      aoEscolherMorada: (sugestao) => escolhidas.push(sugestao),
      aoFocar: (alvo) => focos.push(alvo),
    });
    if (iniciar) seletor.iniciar(elemento);
    const escrever = (valor) => {
      seletor.pesquisa.escrever(valor);
      jest.advanceTimersByTime(300);
    };
    return {
      seletor, pedidos, escolhidas, mudancas, focos, escrever, elemento, leaflet: () => registo.mapas[0],
    };
  }

  test('sem api, o seletor não tem pesquisa de morada', () => {
    const { seletor } = preparar();
    expect(seletor.pesquisa).toBeNull();
    expect(seletor.vista.pesquisa).toBeNull();
  });

  test('com api: o campo "Pesquisar morada" (a vista dele vem na do seletor)', () => {
    const m = prepararComPesquisa();
    expect(m.seletor.pesquisa).not.toBeNull();
    expect(m.seletor.vista.pesquisa).toBe(m.seletor.pesquisa.vista);
    m.seletor.pesquisa.escrever('Ru');
    expect(m.seletor.vista.pesquisa.texto).toBe('Ru'); // cada mudança do campo chega à vista do seletor
  });

  test('pesquisa no GET /api/crm/morada/pesquisa com o centro do mapa como bias', () => {
    const m = prepararComPesquisa();
    m.escrever('Rua Augusta');
    expect(m.pedidos.length).toBe(1);
    expect(m.pedidos[0].caminho).toBe('pesquisa');
    expect(m.pedidos[0].parametros).toStrictEqual({ texto: 'Rua Augusta', lat: 38.7223, lng: -9.1393 });
  });

  test('escolher uma sugestão: pino arrastável na sugestão, zoom 18, avisa o ecrã e o foco vai para Confirmar', async () => {
    const m = prepararComPesquisa();
    m.escrever('Rua Augusta 24');
    m.pedidos[0].resolver([AUGUSTA_24]);
    await esvaziar();
    m.seletor.pesquisa.escolher(0);
    expect(ZOOM_MORADA).toBe(18);
    expect(m.leaflet().vistas.at(-1)).toEqual({ tipo: 'setView', centro: [38.70921, -9.13712], zoom: 18 });
    const marcador = pino(m.leaflet());
    expect(marcador.getLatLng()).toEqual({ lat: 38.70921, lng: -9.13712 });
    expect(marcador.dragging.enabled()).toBe(true);
    expect(m.escolhidas).toEqual([AUGUSTA_24]);
    expect(m.seletor.localizacao).toBeNull(); // ainda por confirmar
    expect(m.seletor.vista.dica).toBe(TEXTO_ARRASTAR);
    expect(m.focos).toEqual(['confirmar']);
    m.seletor.confirmar();
    expect(m.seletor.localizacao).toEqual({ lat: 38.70921, lng: -9.13712, origem_coords: 'geocoder', precisao_m: null });
  });

  test('escolher uma sugestão e arrastar o pino: a origem passa a pin_manual', async () => {
    const m = prepararComPesquisa();
    m.escrever('Rua Augusta 24');
    m.pedidos[0].resolver([AUGUSTA_24]);
    await esvaziar();
    m.seletor.pesquisa.escolher(0);
    pino(m.leaflet()).arrastarPara(38.7093, -9.1372);
    m.seletor.confirmar();
    expect(m.seletor.localizacao).toEqual({ lat: 38.7093, lng: -9.1372, origem_coords: 'pin_manual', precisao_m: null });
  });

  test('escolher uma sugestão com a localização já confirmada: o pino muda e volta a pedir confirmação', async () => {
    const m = prepararComPesquisa();
    tocar(m.leaflet(), 38.71, -9.14);
    m.seletor.confirmar();
    m.escrever('Rua Augusta 24');
    m.pedidos[0].resolver([AUGUSTA_24]);
    await esvaziar();
    m.seletor.pesquisa.escolher(0);
    expect(pino(m.leaflet()).getLatLng()).toEqual({ lat: 38.70921, lng: -9.13712 });
    expect(m.seletor.localizacao).toBeNull();
    expect(m.mudancas.at(-1)).toBeNull();
  });

  test('tocar no mapa fecha a lista de sugestões', async () => {
    const m = prepararComPesquisa();
    m.escrever('Rua Augusta');
    m.pedidos[0].resolver([AUGUSTA_24]);
    await esvaziar();
    expect(m.seletor.vista.pesquisa.aberta).toBe(true);
    tocar(m.leaflet(), 38.71, -9.14);
    expect(m.seletor.vista.pesquisa.aberta).toBe(false);
    expect(m.escolhidas).toEqual([]); // tocar no mapa não escolhe a morada
  });

  test('falha da pesquisa: a mensagem do desenho e o pino continua a pôr-se no mapa', async () => {
    const m = prepararComPesquisa();
    m.escrever('falha');
    m.pedidos[0].rejeitar({ codigo: 'morada_indisponivel', mensagem: 'x' });
    await esvaziar();
    expect(m.seletor.vista.pesquisa.mensagem).toBe(MENSAGEM_MORADA_INDISPONIVEL);
    expect(m.seletor.vista.pesquisa.mensagem)
      .toBe("Pesquisa de morada indisponível — coloque o pino no mapa ou use 'Estou nesta loja'");
    tocar(m.leaflet(), 38.71, -9.14);
    m.seletor.confirmar();
    expect(m.seletor.localizacao.origem_coords).toBe('pin_manual');
  });

  test('sem mapa, a pesquisa de morada não aparece (não teria onde pôr o pino)', () => {
    const m = prepararComPesquisa({ semLeaflet: true });
    expect(m.seletor.vista.pesquisa).toBeNull();
    expect(m.seletor.vista.erro).toBe(MENSAGEM_SEM_MAPA);
  });

  test('sem mapa, a pesquisa que estava agendada é descartada', () => {
    const m = prepararComPesquisa({ semLeaflet: true, iniciar: false });
    m.seletor.pesquisa.escrever('Rua Augusta');
    m.seletor.iniciar(m.elemento);
    jest.advanceTimersByTime(1000);
    expect(m.pedidos.length).toBe(0);
  });

  test('antes de haver mapa, a pesquisa vai sem bias', () => {
    const m = prepararComPesquisa({ iniciar: false });
    m.escrever('Rua Augusta');
    expect(m.pedidos[0].parametros).toStrictEqual({ texto: 'Rua Augusta' });
  });

  test('antes de haver mapa, escolher uma sugestão não faz nada', async () => {
    const m = prepararComPesquisa({ iniciar: false });
    m.escrever('Rua Augusta 24');
    m.pedidos[0].resolver([AUGUSTA_24]);
    await esvaziar();
    m.seletor.pesquisa.escolher(0);
    expect(m.escolhidas).toEqual([]);
    expect(m.focos).toEqual([]);
  });

  test('destruir descarta a pesquisa que estava agendada', () => {
    const m = prepararComPesquisa();
    m.seletor.pesquisa.escrever('Rua Augusta');
    m.seletor.destruir();
    jest.advanceTimersByTime(1000);
    expect(m.pedidos.length).toBe(0);
  });
});

// --- "Estou nesta loja" --------------------------------------------------------------------------

// Geolocalização falsa (navigator.geolocation): cada pedido fica pendente até o teste lhe responder.
function geoFalso() {
  const pedidos = [];
  return {
    pedidos,
    getCurrentPosition(sucesso, falha, opcoes) {
      pedidos.push({ sucesso, falha, opcoes });
    },
  };
}

const PRACA = { rotulo: 'Praça do Comércio, 1100-148 Lisboa, Portugal', morada: 'Praça do Comércio', codigo_postal: '1100-148', localidade: 'Lisboa', lat: 38.70749, lng: -9.13648 };

// O seletor com o GPS (e, por omissão, com a api, para a morada sugerida).
function prepararComGps({ comApi = true, semLeaflet = false, iniciar = true } = {}) {
  const { L, registo } = leafletFalso();
  const documento = documentoFalso();
  const elemento = documento.createElement('div');
  const geo = geoFalso();
  const { pedidos, api } = apiFalsa();
  const sugeridas = [];
  const mudancas = [];
  const vistas = [];
  const seletor = criarSeletor({
    L: semLeaflet ? undefined : L,
    documento,
    configuracao: CONFIGURACAO,
    api: comApi ? api : undefined,
    geolocation: geo,
    aoMudar: (localizacao) => mudancas.push(localizacao),
    aoSugerirMorada: (sugestao) => sugeridas.push(sugestao),
    aoMudarVista: (vista) => vistas.push(vista),
  });
  if (iniciar) seletor.iniciar(elemento);
  return {
    seletor, geo, pedidos, sugeridas, mudancas, vistas, elemento, leaflet: () => registo.mapas[0],
  };
}

const inversas = (m) => m.pedidos.filter((p) => p.caminho === 'inversa');

// Toca em "Estou nesta loja" e o browser responde com a posição.
async function gps(m, latitude, longitude, accuracy) {
  m.seletor.estouNestaLoja();
  m.geo.pedidos.at(-1).sucesso({ coords: { latitude, longitude, accuracy } });
  await esvaziar();
}

test('sem geolocalização no browser, não há "Estou nesta loja"', () => {
  const { seletor } = preparar();
  expect(seletor.vista.gps).toBeNull();
});

test('"Estou nesta loja": o GPS só se pede quando se toca', () => {
  const m = prepararComGps();
  expect(TEXTO_ESTOU_NESTA_LOJA).toBe('Estou nesta loja');
  expect(m.seletor.vista.gps).toEqual({ texto: 'Estou nesta loja', ocupado: false, mensagem: null });
  expect(m.geo.pedidos.length).toBe(0); // criar o seletor e o mapa não pede o GPS
  expect(m.seletor.vista.moradaSugerida).toBeNull();
});

test('um geolocation sem getCurrentPosition conta como sem GPS', () => {
  const { L } = leafletFalso();
  const seletor = criarSeletor({ L, documento: documentoFalso(), configuracao: CONFIGURACAO, geolocation: {} });
  expect(seletor.vista.gps).toBeNull();
});

test('antes de haver mapa, "Estou nesta loja" não pede o GPS (não teria onde pôr o pino)', async () => {
  const m = prepararComGps({ iniciar: false });
  expect(m.seletor.vista.gps.ocupado).toBe(true);
  await m.seletor.estouNestaLoja();
  expect(m.geo.pedidos.length).toBe(0);
  m.seletor.iniciar(m.elemento);
  expect(m.seletor.vista.gps.ocupado).toBe(false);
});

test('sem mapa, "Estou nesta loja" não aparece', () => {
  const m = prepararComGps({ semLeaflet: true });
  expect(m.seletor.vista.gps).toBeNull();
});

test('tocar: pede o GPS uma vez (alta precisão, 15 s, sem cache) e espera com "A obter a localização…"', () => {
  const m = prepararComGps();
  m.seletor.estouNestaLoja();
  expect(m.geo.pedidos.length).toBe(1);
  expect(m.geo.pedidos[0].opcoes).toEqual(OPCOES_GPS);
  expect(TEXTO_A_OBTER_LOCALIZACAO).toBe('A obter a localização…');
  // aria-disabled no botão (não `disabled`: o foco não se perde).
  expect(m.seletor.vista.gps).toEqual({ texto: 'A obter a localização…', ocupado: true, mensagem: null });
  m.seletor.estouNestaLoja();
  expect(m.geo.pedidos.length).toBe(1); // um toque, um pedido
});

test('boa precisão: pino arrastável no ponto, círculo com o raio da precisão e o mapa enquadra o círculo', async () => {
  const m = prepararComGps();
  await gps(m, 38.7075, -9.1364, 20);
  const marcador = pino(m.leaflet());
  expect(marcador.getLatLng()).toEqual({ lat: 38.7075, lng: -9.1364 });
  expect(marcador.dragging.enabled()).toBe(true);
  expect(m.leaflet().circulos.length).toBe(1);
  const [circulo] = m.leaflet().circulos;
  expect(circulo.getLatLng()).toEqual({ lat: 38.7075, lng: -9.1364 });
  expect(circulo.getRadius()).toBe(20);
  expect(circulo.options.className).toBe('circulo-precisao');
  expect(circulo.options.interactive).toBe(false); // um toque no círculo chega ao mapa
  expect(circulo.options.color).toBe('#6b2fa3');
  expect(circulo.options.fillColor).toBe('#6b2fa3');
  expect(ZOOM_GPS).toBe(18);
  const vista = m.leaflet().vistas.at(-1);
  expect(vista.tipo).toBe('fitBounds');
  expect(vista.limites).toEqual(limitesDoCirculo({ lat: 38.7075, lng: -9.1364 }, 20));
  expect(vista.opcoes.maxZoom).toBe(ZOOM_GPS);
  expect(m.seletor.vista.gps).toEqual({ texto: 'Estou nesta loja', ocupado: false, mensagem: null });
  expect(m.seletor.vista.dica).toBe(TEXTO_ARRASTAR);
  expect(m.seletor.vista.aviso).toBeNull();
  expect(m.seletor.localizacao).toBeNull(); // ainda por confirmar
  expect(m.seletor.vista.confirmarAtivo).toBe(true);
  m.seletor.confirmar();
  expect(m.seletor.localizacao).toEqual({ lat: 38.7075, lng: -9.1364, origem_coords: 'gps', precisao_m: 20 });
});

test('a precisão vai arredondada ao metro (como o servidor a guarda)', async () => {
  const m = prepararComGps();
  await gps(m, 38.7075, -9.1364, 12.6);
  expect(m.leaflet().circulos[0].getRadius()).toBe(13);
  m.seletor.confirmar();
  expect(m.seletor.localizacao.precisao_m).toBe(13);
});

test('GPS impreciso (> 50 m): "Localização imprecisa — ajuste o pino" e Confirmar só depois de arrastar (pin_manual)', async () => {
  const m = prepararComGps();
  await gps(m, 38.7075, -9.1364, 120);
  expect(m.seletor.vista.dica).toBe(MENSAGEM_LOCALIZACAO_IMPRECISA);
  expect(m.seletor.vista.aviso).toBe('imprecisa');
  expect(m.seletor.vista.confirmarAtivo).toBe(false);
  expect(m.leaflet().circulos[0].getRadius()).toBe(120);
  pino(m.leaflet()).arrastarPara(38.7077, -9.1361);
  expect(m.seletor.vista.confirmarAtivo).toBe(true);
  expect(m.seletor.vista.aviso).toBeNull();
  expect(m.leaflet().circulos.length).toBe(1); // o círculo fica, para se ver a zona onde o GPS está
  m.seletor.confirmar();
  expect(m.seletor.localizacao).toEqual({ lat: 38.7077, lng: -9.1361, origem_coords: 'pin_manual', precisao_m: null });
});

test('o browser sem a precisão: sem círculo, aproxima no ponto (zoom 18) e conta como imprecisa', async () => {
  const m = prepararComGps();
  await gps(m, 38.7075, -9.1364, undefined);
  expect(m.leaflet().circulos.length).toBe(0);
  expect(m.leaflet().vistas.at(-1)).toEqual({ tipo: 'setView', centro: [38.7075, -9.1364], zoom: ZOOM_GPS });
  expect(m.seletor.vista.confirmarAtivo).toBe(false);
  expect(m.seletor.vista.dica).toBe(MENSAGEM_LOCALIZACAO_IMPRECISA);
});

test('permissão negada: a mensagem pt junto ao botão, sem pino, e o botão volta', async () => {
  const m = prepararComGps();
  m.seletor.estouNestaLoja();
  m.geo.pedidos[0].falha({ code: 1, message: 'User denied Geolocation' });
  await esvaziar();
  expect(m.seletor.vista.gps.mensagem).toEqual({ texto: MENSAGEM_PERMISSAO_NEGADA, tipo: 'erro' });
  expect(m.seletor.vista.gps.mensagem.texto).toBe("Autorize a localização no browser para usar 'Estou nesta loja'");
  expect(m.leaflet().marcadores.length).toBe(0);
  expect(m.seletor.vista.gps.texto).toBe('Estou nesta loja');
  expect(m.seletor.vista.gps.ocupado).toBe(false);
  expect(inversas(m).length).toBe(0);
  tocar(m.leaflet(), 38.71, -9.14);
  expect(m.seletor.vista.gps.mensagem).toBeNull(); // pôr o pino à mão tira a mensagem
});

test('tempo esgotado: a mensagem pt e pode tentar outra vez', async () => {
  const m = prepararComGps();
  m.seletor.estouNestaLoja();
  m.geo.pedidos[0].falha({ code: 3 });
  await esvaziar();
  expect(m.seletor.vista.gps.mensagem.texto).toBe('A localização demorou demasiado — tente outra vez ou coloque o pino no mapa');
  // Tocar outra vez tira logo a mensagem anterior (enquanto espera, só "A obter a localização…").
  m.seletor.estouNestaLoja();
  expect(m.seletor.vista.gps).toEqual({ texto: TEXTO_A_OBTER_LOCALIZACAO, ocupado: true, mensagem: null });
  m.geo.pedidos[1].falha({ code: 3 });
  await esvaziar();
  await gps(m, 38.7075, -9.1364, 20);
  expect(m.geo.pedidos.length).toBe(3);
  expect(m.seletor.vista.gps.mensagem).toBeNull();
  expect(pino(m.leaflet()).getLatLng().lat).toBe(38.7075);
});

test('tocar no mapa ou escolher outro sítio depois do GPS: sai o círculo e a morada sugerida', async () => {
  const m = prepararComGps();
  await gps(m, 38.7075, -9.1364, 20);
  inversas(m)[0].resolver(PRACA);
  await esvaziar();
  expect(moradaSugerida(m.seletor)).not.toBe('');
  tocar(m.leaflet(), 38.72, -9.15);
  expect(m.leaflet().circulos.length).toBe(0);
  expect(m.seletor.vista.moradaSugerida).toBeNull();
  m.seletor.confirmar();
  expect(m.seletor.localizacao.origem_coords).toBe('pin_manual');
});

test('"Estou nesta loja" outra vez: um só círculo, no ponto novo', async () => {
  const m = prepararComGps();
  await gps(m, 38.7075, -9.1364, 40);
  await gps(m, 38.7080, -9.1370, 15);
  expect(m.leaflet().circulos.length).toBe(1);
  expect(m.leaflet().circulos[0].getRadius()).toBe(15);
  expect(pino(m.leaflet()).getLatLng()).toEqual({ lat: 38.708, lng: -9.137 });
});

test('pôr o pino à mão enquanto o GPS responde: a posição que chega depois é ignorada', async () => {
  const m = prepararComGps();
  m.seletor.estouNestaLoja();
  tocar(m.leaflet(), 38.72, -9.15);
  m.geo.pedidos[0].sucesso({ coords: { latitude: 38.7075, longitude: -9.1364, accuracy: 10 } });
  await esvaziar();
  expect(pino(m.leaflet()).getLatLng()).toEqual({ lat: 38.72, lng: -9.15 });
  expect(m.leaflet().circulos.length).toBe(0);
  expect(inversas(m).length).toBe(0);
  expect(m.seletor.vista.gps).toEqual({ texto: 'Estou nesta loja', ocupado: false, mensagem: null });
});

test('arrastar o pino enquanto o GPS responde: fica o que a pessoa fez (também com um erro do GPS)', async () => {
  for (const responder of [
    (pedido) => pedido.sucesso({ coords: { latitude: 38.7075, longitude: -9.1364, accuracy: 10 } }),
    (pedido) => pedido.falha({ code: 2 }),
  ]) {
    const m = prepararComGps();
    tocar(m.leaflet(), 38.72, -9.15);
    m.seletor.estouNestaLoja();
    pino(m.leaflet()).arrastarPara(38.7201, -9.1501);
    responder(m.geo.pedidos[0]);
    await esvaziar();
    expect(pino(m.leaflet()).getLatLng()).toEqual({ lat: 38.7201, lng: -9.1501 });
    expect(m.seletor.vista.gps.mensagem).toBeNull();
    expect(m.seletor.vista.gps.ocupado).toBe(false);
  }
});

test('com a localização já confirmada, o GPS muda o pino e volta a pedir confirmação', async () => {
  const m = prepararComGps();
  tocar(m.leaflet(), 38.72, -9.15);
  m.seletor.confirmar();
  await gps(m, 38.7075, -9.1364, 20);
  expect(m.seletor.localizacao).toBeNull();
  expect(m.mudancas.at(-1)).toBeNull();
  expect(pino(m.leaflet()).getLatLng()).toEqual({ lat: 38.7075, lng: -9.1364 });
  expect(m.seletor.vista.estado).toBe('por_confirmar');
});

test('destruir enquanto espera pelo GPS: o que chega depois não faz nada', async () => {
  for (const responder of [
    (pedido) => pedido.sucesso({ coords: { latitude: 38.7075, longitude: -9.1364, accuracy: 10 } }),
    (pedido) => pedido.falha({ code: 1 }),
  ]) {
    const m = prepararComGps();
    m.seletor.estouNestaLoja();
    m.seletor.destruir();
    const vistas = m.vistas.length;
    responder(m.geo.pedidos[0]);
    await esvaziar();
    expect(m.leaflet().removido).toBe(true);
    expect(m.leaflet().marcadores.length).toBe(0);
    expect(inversas(m).length).toBe(0);
    expect(m.seletor.vista.gps.mensagem).toBeNull();
    expect(m.vistas.length).toBe(vistas); // nada chega ao ecrã que já saiu
  }
});

// --- Morada sugerida (geocodificação inversa do ponto do GPS) -------------------------------------

test('depois do GPS: GET /api/crm/morada/inversa com o ponto (6 casas decimais) e "A procurar a morada…"', async () => {
  const m = prepararComGps();
  await gps(m, 38.70750000123, -9.13640000456, 12);
  expect(inversas(m).length).toBe(1);
  expect(inversas(m)[0].parametros).toStrictEqual({ lat: 38.7075, lng: -9.1364 });
  expect(TEXTO_A_PROCURAR_MORADA).toBe('A procurar a morada…');
  expect(moradaSugerida(m.seletor)).toBe('A procurar a morada…');
  expect(m.seletor.vista.moradaSugerida.tipo).toBeNull();
});

test('morada sugerida: "Morada sugerida: … · Powered by Geoapify" (com a ligação) e o ecrã recebe-a', async () => {
  const m = prepararComGps();
  await gps(m, 38.7075, -9.1364, 12);
  inversas(m)[0].resolver(PRACA);
  await esvaziar();
  expect(moradaSugerida(m.seletor)).toBe('Morada sugerida: Praça do Comércio, 1100-148 Lisboa, Portugal · Powered by Geoapify');
  const ligacoes = m.seletor.vista.moradaSugerida.partes.filter((p) => p.url !== null);
  expect(ligacoes).toEqual([{ texto: ATRIBUICOES.pesquisa.texto, url: ATRIBUICOES.pesquisa.partes[0].url }]);
  expect(m.seletor.vista.moradaSugerida.tipo).toBeNull();
  expect(m.sugeridas).toEqual([PRACA]);
  expect(m.seletor.localizacao).toBeNull(); // a morada não confirma a localização
  pino(m.leaflet()).arrastarPara(38.7076, -9.1365);
  expect(moradaSugerida(m.seletor)).not.toBe(''); // arrastar o pino não a tira
});

test('partesMoradaSugerida: o rótulo entra como uma parte de texto, sem ligação, e a atribuição só das constantes', () => {
  const partes = partesMoradaSugerida('<b>x</b>');
  expect(texto(partes)).toBe('Morada sugerida: <b>x</b> · Powered by Geoapify');
  expect(partes[1]).toEqual({ texto: '<b>x</b>', url: null });
  expect(partes.slice(3)).toEqual(ATRIBUICOES.pesquisa.partes.map((p) => ({ texto: p.texto, url: p.url })));
});

test('a morada sugerida entra como texto: <b>x</b> fica tal e qual', async () => {
  const m = prepararComGps();
  await gps(m, 38.7075, -9.1364, 12);
  inversas(m)[0].resolver({ ...PRACA, rotulo: '<b>x</b>' });
  await esvaziar();
  expect(moradaSugerida(m.seletor)).toBe('Morada sugerida: <b>x</b> · Powered by Geoapify');
});

test('sem morada para o ponto (null ou sem rótulo): não mostra nada nem preenche', async () => {
  for (const resposta of [null, {}, { ...PRACA, rotulo: '' }]) {
    const m = prepararComGps();
    await gps(m, 38.7075, -9.1364, 12);
    inversas(m)[0].resolver(resposta);
    await esvaziar();
    expect(m.seletor.vista.moradaSugerida).toBeNull();
    expect(m.sugeridas).toEqual([]);
  }
});

test('morada sugerida indisponível (503 ou sem rede): a mensagem, e o pino confirma-se na mesma', async () => {
  for (const codigo of ['morada_indisponivel', 'sem_rede', 'erro_interno']) {
    const m = prepararComGps();
    await gps(m, 38.7075, -9.1364, 12);
    inversas(m)[0].rejeitar({ codigo, mensagem: 'x' });
    await esvaziar();
    expect(moradaSugerida(m.seletor)).toBe(MENSAGEM_MORADA_SUGERIDA_INDISPONIVEL);
    expect(m.seletor.vista.moradaSugerida.tipo).toBe('erro');
    expect(m.sugeridas).toEqual([]);
    m.seletor.confirmar();
    expect(m.seletor.localizacao.origem_coords).toBe('gps');
  }
});

test('ponto fora de Portugal (422): sem morada sugerida (o erro aparece ao guardar)', async () => {
  const m = prepararComGps();
  await gps(m, 38.7075, -9.1364, 12);
  inversas(m)[0].rejeitar({ codigo: 'validacao', mensagem: 'Fora de Portugal', campos: { lat: 'Fora de Portugal' } });
  await esvaziar();
  expect(m.seletor.vista.moradaSugerida).toBeNull();
});

test('a morada sugerida que chega depois de o pino mudar de sítio é ignorada', async () => {
  const m = prepararComGps();
  await gps(m, 38.7075, -9.1364, 12);
  tocar(m.leaflet(), 38.72, -9.15);
  inversas(m)[0].resolver(PRACA);
  await esvaziar();
  expect(m.sugeridas).toEqual([]);
  expect(m.seletor.vista.moradaSugerida).toBeNull();

  await gps(m, 38.7075, -9.1364, 12);
  await gps(m, 38.7080, -9.1370, 12);
  inversas(m)[1].resolver(PRACA);
  await esvaziar();
  expect(m.sugeridas).toEqual([]); // a do primeiro ponto chegou tarde
  inversas(m)[2].resolver({ ...PRACA, rotulo: 'Rua Augusta 24, 1100-048 Lisboa, Portugal' });
  await esvaziar();
  expect(m.sugeridas.length).toBe(1);
  expect(moradaSugerida(m.seletor)).toBe('Morada sugerida: Rua Augusta 24, 1100-048 Lisboa, Portugal · Powered by Geoapify');
});

test('um erro tardio da morada sugerida também é ignorado', async () => {
  const m = prepararComGps();
  await gps(m, 38.7075, -9.1364, 12);
  tocar(m.leaflet(), 38.72, -9.15);
  inversas(m)[0].rejeitar({ codigo: 'morada_indisponivel', mensagem: 'x' });
  await esvaziar();
  expect(m.seletor.vista.moradaSugerida).toBeNull();
});

test('destruir com a morada a caminho: a resposta não faz nada', async () => {
  const m = prepararComGps();
  await gps(m, 38.7075, -9.1364, 12);
  m.seletor.destruir();
  const vistas = m.vistas.length;
  inversas(m)[0].resolver(PRACA);
  await esvaziar();
  expect(m.sugeridas).toEqual([]);
  expect(m.vistas.length).toBe(vistas);
});

test('sem api: o GPS põe o pino sem pedir a morada', async () => {
  const m = prepararComGps({ comApi: false });
  await gps(m, 38.7075, -9.1364, 12);
  expect(m.leaflet().marcadores.length).toBe(1);
  expect(m.seletor.vista.moradaSugerida).toBeNull();
});

// --- A mais: a vista, redimensionar ---------------------------------------------------------------

test('a vista que chega ao aoMudarVista é a do seletor, nova a cada mudança e congelada', () => {
  const { seletor, leaflet, vistas } = preparar();
  const antes = seletor.vista;
  tocar(leaflet(), 38.71, -9.14);
  expect(vistas.at(-1)).toBe(seletor.vista);
  expect(seletor.vista).not.toBe(antes);
  expect(antes.estado).toBe('vazio');
  expect(Object.isFrozen(seletor.vista)).toBe(true);
  seletor.confirmar();
  expect(vistas.at(-1).estado).toBe('confirmado');
});

test('redimensionar: o Leaflet volta a medir a área sem deslocar o mapa (antes de iniciar, nada)', () => {
  const { seletor, leaflet, registo, elemento } = preparar({ iniciar: false });
  expect(() => seletor.redimensionar()).not.toThrow();
  expect(registo.mapas.length).toBe(0);
  seletor.iniciar(elemento);
  seletor.redimensionar();
  expect(leaflet().redimensionamentos).toEqual([{ pan: false }]);
  seletor.destruir();
  expect(() => seletor.redimensionar()).not.toThrow();
  expect(leaflet().redimensionamentos.length).toBe(1);
});

// --- Sobre o Leaflet 1.9.4 verdadeiro (jsdom) ------------------------------------------------------

describe('sobre o Leaflet 1.9.4 verdadeiro (jsdom)', () => {
  // O jsdom não carrega imagens nem mede o elemento: chega para ver o DOM que o Leaflet monta com o
  // que o seletor lhe passa.
  let elemento;
  let seletor;

  beforeEach(() => {
    elemento = document.createElement('div');
    document.body.appendChild(elemento);
    seletor = criarSeletor({ L: LeafletVerdadeiro, documento: document, configuracao: CONFIGURACAO });
    seletor.iniciar(elemento);
  });

  afterEach(() => {
    seletor.destruir();
    elemento.remove();
  });

  test('tocar no mapa põe o pino: a div da gota, vazia, arrastável, com o título; confirmado, deixa de se arrastar', () => {
    elemento.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: 0, clientY: 0 }));
    const icones = elemento.querySelectorAll('.leaflet-marker-icon');
    expect(icones).toHaveLength(1);
    const [icone] = icones;
    expect(icone.classList.contains('pino-seletor')).toBe(true);
    expect(icone.childElementCount).toBe(0);
    expect(icone.textContent).toBe('');
    expect(icone.title).toBe('Pino da loja');
    expect(icone.classList.contains('leaflet-marker-draggable')).toBe(true);
    expect(seletor.vista.estado).toBe('por_confirmar');
    seletor.confirmar();
    expect(icone.classList.contains('leaflet-marker-draggable')).toBe(false);
    seletor.alterar();
    expect(icone.classList.contains('leaflet-marker-draggable')).toBe(true);
  });

  test('a atribuição no canto é a constante da configuração', () => {
    const atribuicao = elemento.querySelector('.leaflet-control-attribution');
    expect(atribuicao.textContent).toBe(ATRIBUICOES.geoapify.texto);
  });

  test('os botões de zoom do seletor (Nova loja, Corrigir localização, Fábrica) estão em pt-PT', () => {
    expect(elemento.querySelectorAll('.leaflet-control-zoom')).toHaveLength(1);
    expect(elemento.querySelector('.leaflet-control-zoom-in').getAttribute('aria-label')).toBe('Aproximar');
    expect(elemento.querySelector('.leaflet-control-zoom-out').getAttribute('aria-label')).toBe('Afastar');
  });
});
