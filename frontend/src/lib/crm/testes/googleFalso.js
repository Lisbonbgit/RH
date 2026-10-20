// Google Maps falso para testar o mapa no Jest (a Maps JavaScript API
// verdadeira não corre no jsdom: pede a rede, mede o elemento e desenha em
// canvas). Só testes; fica fora do varrimento do seguranca.test.js, que exclui
// a pasta `testes/`. Substitui o falso da biblioteca do mapa antigo (plano do
// mapa Google, G5; adenda §6.5).
//
// Imita só o que `lib/crm/mapa.js`, `seletor.js`, `lugarGoogle.js` e, na F3b,
// o `mostrarRota` usam, com o comportamento da Google que importa para os
// testes:
//  - um `Map` enche a `div` com DOM seu (aqui um filho `.gm-style-falso`) e
//    nunca o tira: é o `destruir` do mapa.js que esvazia o elemento, e um
//    segundo `new Map` no mesmo elemento (StrictMode) empilhava outro;
//  - num `click` do mapa com `placeId` (tocaram num ícone de negócio), se
//    nenhum ouvinte chamar `evento.stop()`, a Google abre o seu balão do lugar:
//    o falso conta-o em `registo.baloesDaGoogle` (o código do CRM nunca chama
//    `stop()`); com `clickableIcons: false` a Google não emite `placeId` nenhum,
//    por isso o falso tira-o do evento antes dos ouvintes;
//  - `position` de um marcador e `location` de um lugar chegam ora como `LatLng`
//    (com `lat()`/`lng()` em função) ora como literal `{lat, lng}`: o falso
//    alterna de propósito, para o código ter de tratar os dois (`pontoDe` do
//    mapa.js, `pontoDoLugar` do lugarGoogle.js); `posicao()` e `getCenter()`
//    são as formas fixas para os testes;
//  - onde a Google só aceita um `LatLng` ou um literal (`center`, `setCenter`,
//    `panTo`, `position`, `LatLngBounds.extend`, o `path` de uma linha), o falso
//    também só aceita isso e rebenta com um par `[lat, lng]`, para o
//    falso não deixar passar o que a Google recusa;
//  - `gmp-click` só existe com `gmpClickable: true` e o arrasto só com
//    `gmpDraggable: true` (`tocar()` e `arrastarPara()` rebentam sem eles, como
//    o marcador falso do mapa antigo fazia);
//  - `Place.fetchFields` só preenche os campos pedidos (e cada campo a mais
//    muda o que a Google cobra): o falso regista-os em `registo.camposPedidos` e
//    copia só esses do lugar que o teste pôs em `registo.lugares[id]` — as
//    chaves a mais com sentinelas só aparecem se o código as pedir;
//  - `InfoWindow` nunca se cria no CRM (o balão é o da própria Google): o
//    construtor conta em `registo.infoWindowsNossas`, que os testes exigem a 0;
//  - os ouvintes contam-se (`ouvintes(tipo)`) e as limpezas também
//    (`limpezas`), para provar que um `idle` único não fica pendurado e que o
//    `destruir` tira tudo.
//
// `googleFalso({documento})` → `{google, registo}`; `registo` tem `mapas` (todos
// os criados), `marcadores`/`circulos`/`linhas` (os que estão num mapa neste
// momento), `pesquisas`, `camposPedidos`, `lugares` (a pôr pelo teste),
// `bibliotecas` (os nomes pedidos ao `importLibrary`), `baloesDaGoogle` e
// `infoWindowsNossas`. O Jest do CRA corre com `resetMocks`: criar o falso
// dentro de cada teste.

import { limitesDoCirculo } from '../gps';

const numero = (valor) => typeof valor === 'number' && Number.isFinite(valor);

// Um LatLng como o da Google: lat()/lng() em função; toJSON() dá o literal.
export class LatLngFalso {
  constructor(lat, lng) {
    this.latitude = lat;
    this.longitude = lng;
  }

  lat() { return this.latitude; }

  lng() { return this.longitude; }

  equals(outro) {
    const ponto = pontoLiteral(outro);
    return ponto !== null && ponto.lat === this.latitude && ponto.lng === this.longitude;
  }

  toJSON() { return { lat: this.latitude, lng: this.longitude }; }

  toString() { return `(${this.latitude}, ${this.longitude})`; }
}

// {lat, lng} numérico a partir de um literal ou de um LatLng (funções); o resto (um par [lat, lng]
// incluído) dá null, como a Google, que só aceita estas duas formas.
export function pontoLiteral(valor) {
  if (valor === null || typeof valor !== 'object' || Array.isArray(valor)) return null;
  const lat = typeof valor.lat === 'function' ? valor.lat() : valor.lat;
  const lng = typeof valor.lng === 'function' ? valor.lng() : valor.lng;
  return numero(lat) && numero(lng) ? { lat, lng } : null;
}

function exigirPonto(valor, onde) {
  const ponto = pontoLiteral(valor);
  if (ponto === null) throw new TypeError(`${onde}: não é um LatLng nem um literal {lat, lng}`);
  return ponto;
}

// Os limites (google.maps.LatLngBounds): extend, cantos, centro e `pontos` (os que entraram, pela ordem).
export class LatLngBoundsFalsos {
  constructor(sudoeste, nordeste) {
    this.pontos = [];
    if (sudoeste !== null && typeof sudoeste === 'object' && 'south' in sudoeste) {
      // O literal {south, west, north, east}.
      this.extend({ lat: sudoeste.south, lng: sudoeste.west });
      this.extend({ lat: sudoeste.north, lng: sudoeste.east });
      return;
    }
    if (sudoeste !== undefined) this.extend(sudoeste);
    if (nordeste !== undefined) this.extend(nordeste);
  }

  extend(ponto) {
    this.pontos.push(exigirPonto(ponto, 'LatLngBounds.extend'));
    return this;
  }

  isEmpty() { return this.pontos.length === 0; }

  getSouthWest() {
    if (this.isEmpty()) return null;
    return new LatLngFalso(Math.min(...this.pontos.map((p) => p.lat)), Math.min(...this.pontos.map((p) => p.lng)));
  }

  getNorthEast() {
    if (this.isEmpty()) return null;
    return new LatLngFalso(Math.max(...this.pontos.map((p) => p.lat)), Math.max(...this.pontos.map((p) => p.lng)));
  }

  getCenter() {
    if (this.isEmpty()) return null;
    const so = this.getSouthWest();
    const ne = this.getNorthEast();
    return new LatLngFalso((so.lat() + ne.lat()) / 2, (so.lng() + ne.lng()) / 2);
  }

  contains(valor) {
    const ponto = pontoLiteral(valor);
    if (ponto === null || this.isEmpty()) return false;
    const so = this.getSouthWest();
    const ne = this.getNorthEast();
    return ponto.lat >= so.lat() && ponto.lat <= ne.lat() && ponto.lng >= so.lng() && ponto.lng <= ne.lng();
  }

  toJSON() {
    if (this.isEmpty()) return { south: 1, west: 180, north: -1, east: -180 };
    const so = this.getSouthWest();
    const ne = this.getNorthEast();
    return { south: so.lat(), west: so.lng(), north: ne.lat(), east: ne.lng() };
  }
}

// Ora um LatLng ora um literal, para o código ter de tratar os dois.
function alternador() {
  let vez = 0;
  return ({ lat, lng }) => {
    vez += 1;
    return vez % 2 === 1 ? new LatLngFalso(lat, lng) : { lat, lng };
  };
}

// Os ouvintes de um objeto da Google (mapa, marcador): addListener → {remove}; o `fire` é para os testes
// (e para o google.maps.event.trigger). Os ouvintes chamam-se com `this` = o objeto, como a Google.
class OuvintesFalsos {
  constructor() {
    this.registados = [];
    this.disparos = [];
    this.limpezas = 0;
  }

  addListener(tipo, fn) { return this.registar(tipo, fn, false); }

  registar(tipo, fn, umaVez) {
    if (typeof fn !== 'function') throw new TypeError(`addListener('${tipo}'): o ouvinte não é uma função`);
    const ouvinte = { tipo, fn, umaVez };
    this.registados.push(ouvinte);
    return {
      remove: () => {
        this.registados = this.registados.filter((o) => o !== ouvinte);
      },
    };
  }

  // Quantos ouvintes ativos deste tipo (os de uma vez só contam até dispararem).
  ouvintes(tipo) { return this.registados.filter((o) => o.tipo === tipo).length; }

  fire(tipo, ...args) {
    this.disparos.push({ tipo, args });
    const lista = this.registados.filter((o) => o.tipo === tipo);
    this.registados = this.registados.filter((o) => !(o.tipo === tipo && o.umaVez));
    for (const { fn } of lista) fn.apply(this, args);
  }

  limparOuvintes() {
    this.registados = [];
    this.limpezas += 1;
  }
}

const COLLISION_BEHAVIOR = Object.freeze({
  REQUIRED: 'REQUIRED',
  OPTIONAL_AND_HIDES_LOWER_PRIORITY: 'OPTIONAL_AND_HIDES_LOWER_PRIORITY',
  REQUIRED_AND_HIDES_OPTIONAL: 'REQUIRED_AND_HIDES_OPTIONAL',
});

// Meia largura (em graus) dos limites que `getBounds()` devolve à volta do centro (≈ 1 km).
const MEIA_VISTA_GRAUS = 0.01;

// O toque no mapa, como o MapMouseEvent/IconMouseEvent da Google: `latLng` com funções, `placeId` só quando
// tocaram num ícone de negócio, e `stop()` (que o código do CRM nunca chama: o balão da Google deve abrir).
export function eventoDeToque({ lat, lng, placeId } = {}) {
  const evento = {
    latLng: { lat: () => lat, lng: () => lng },
    parado: false,
    stop: () => {
      evento.parado = true;
    },
  };
  if (placeId !== undefined) evento.placeId = placeId;
  return evento;
}

// O `documento` por omissão é o do jsdom (o do Jest); os testes com o DOM falso passam o `documentoFalso()`.
const documentoDoJest = () => (typeof document === 'undefined' ? undefined : document);

export function googleFalso({ documento = documentoDoJest() } = {}) {
  const registo = {
    mapas: [],
    marcadores: [],
    circulos: [],
    linhas: [],
    pesquisas: [],
    camposPedidos: [],
    lugares: {},
    bibliotecas: [],
    baloesDaGoogle: 0,
    infoWindowsNossas: 0,
  };
  const alternarLugar = alternador();

  // Põe ou tira um objeto de uma das listas do registo conforme entra ou sai de um mapa.
  function porNoMapa(lista, objeto, mapa) {
    if (mapa !== null && mapa !== undefined && !(mapa instanceof MapaFalso)) {
      throw new TypeError('map: não é um google.maps.Map');
    }
    const indice = lista.indexOf(objeto);
    if (mapa && indice === -1) lista.push(objeto);
    if (!mapa && indice !== -1) lista.splice(indice, 1);
    return mapa ?? null;
  }

  class MapaFalso extends OuvintesFalsos {
    constructor(elemento, opcoes = {}) {
      super();
      if (elemento === null || typeof elemento !== 'object') throw new TypeError('Map: o elemento não existe');
      this.elemento = elemento;
      this.options = { ...opcoes };
      this.vistas = [];
      this.centro = opcoes.center === undefined ? null : exigirPonto(opcoes.center, 'Map center');
      this.zoom = numero(opcoes.zoom) ? opcoes.zoom : undefined;
      // A Google enche a div com o DOM dela e nunca o tira.
      this.vista = documento.createElement('div');
      this.vista.setAttribute('class', 'gm-style-falso');
      elemento.appendChild(this.vista);
      registo.mapas.push(this);
    }

    getDiv() { return this.elemento; }

    setOptions(opcoes = {}) {
      Object.assign(this.options, opcoes);
      if (opcoes.center !== undefined) this.setCenter(opcoes.center);
      if (opcoes.zoom !== undefined) this.setZoom(opcoes.zoom);
    }

    // Só um LatLngBounds (ou o literal {south, west, north, east}), como a Google; a margem fica registada.
    fitBounds(limites, margem) {
      const caixa = limites instanceof LatLngBoundsFalsos ? limites : new LatLngBoundsFalsos(limites);
      if (caixa.isEmpty()) throw new TypeError('fitBounds: não é um LatLngBounds');
      this.vistas.push({ tipo: 'fitBounds', limites: caixa, margem });
      this.centro = pontoLiteral(caixa.getCenter());
    }

    setCenter(centro) {
      this.centro = exigirPonto(centro, 'setCenter');
      this.vistas.push({ tipo: 'setCenter', centro: { ...this.centro } });
    }

    panTo(centro) {
      this.centro = exigirPonto(centro, 'panTo');
      this.vistas.push({ tipo: 'panTo', centro: { ...this.centro } });
    }

    setZoom(zoom) {
      if (!numero(zoom)) throw new TypeError('setZoom: não é um número');
      this.zoom = zoom;
      this.vistas.push({ tipo: 'setZoom', zoom });
    }

    getZoom() { return this.zoom; }

    // Como a Google: um LatLng (funções); undefined antes de haver centro.
    getCenter() {
      return this.centro ? new LatLngFalso(this.centro.lat, this.centro.lng) : undefined;
    }

    // Uma caixa de ≈ 1 km à volta do centro; undefined antes de haver centro, como a Google antes do primeiro desenho.
    getBounds() {
      if (!this.centro) return undefined;
      const { lat, lng } = this.centro;
      return new LatLngBoundsFalsos(
        { lat: lat - MEIA_VISTA_GRAUS, lng: lng - MEIA_VISTA_GRAUS },
        { lat: lat + MEIA_VISTA_GRAUS, lng: lng + MEIA_VISTA_GRAUS },
      );
    }

    // O comportamento da Google num toque num ícone de negócio (ver o cabeçalho).
    fire(tipo, ...args) {
      const evento = args[0];
      const comPlaceId = tipo === 'click' && evento !== null && typeof evento === 'object' && 'placeId' in evento;
      if (comPlaceId && this.options.clickableIcons === false) delete evento.placeId;
      super.fire(tipo, ...args);
      if (comPlaceId && evento.placeId && !evento.parado) registo.baloesDaGoogle += 1;
    }

    // Para os testes
    get marcadores() { return registo.marcadores.filter((m) => m.map === this); }

    get circulos() { return registo.circulos.filter((c) => c.getMap() === this); }

    get linhas() { return registo.linhas.filter((l) => l.getMap() === this); }
  }

  // google.maps.marker.AdvancedMarkerElement: propriedades em vez de get/set; o `content` entra no DOM do mapa
  // quando o marcador tem `map` e sai com `map = null`; `element` é o nó do conteúdo (com `focus()` e
  // `isConnected`, para o ecrã devolver o foco ao pino).
  class MarcadorFalso extends OuvintesFalsos {
    constructor(opcoes = {}) {
      super();
      this.options = { ...opcoes };
      this.content = opcoes.content ?? null;
      this.title = opcoes.title ?? '';
      this.gmpDraggable = opcoes.gmpDraggable ?? false;
      this.gmpClickable = opcoes.gmpClickable ?? false;
      this.collisionBehavior = opcoes.collisionBehavior;
      this.zIndex = opcoes.zIndex;
      this.leiturasDaPosicao = 0;
      this.pontoAtual = null;
      this.mapaAtual = null;
      this.position = opcoes.position ?? null;
      this.map = opcoes.map ?? null;
    }

    get map() { return this.mapaAtual; }

    set map(mapa) {
      this.mapaAtual = porNoMapa(registo.marcadores, this, mapa);
      if (this.content === null || typeof this.content !== 'object') return;
      if (this.mapaAtual) this.mapaAtual.vista.appendChild(this.content);
      else this.content.remove?.();
    }

    // Ora um LatLng ora um literal (ver o cabeçalho); null sem posição.
    get position() {
      if (this.pontoAtual === null) return null;
      this.leiturasDaPosicao += 1;
      const { lat, lng } = this.pontoAtual;
      return this.leiturasDaPosicao % 2 === 1 ? new LatLngFalso(lat, lng) : { lat, lng };
    }

    set position(valor) {
      this.pontoAtual = valor === null || valor === undefined ? null : exigirPonto(valor, 'AdvancedMarkerElement.position');
    }

    // Para os testes: sempre {lat, lng} (ou null).
    posicao() { return this.pontoAtual ? { ...this.pontoAtual } : null; }

    get element() { return this.content; }

    // Para os testes: a pessoa toca no pino (ou Enter/Espaço com o foco nele). A Google só emite gmp-click
    // com gmpClickable: true.
    tocar() {
      if (this.gmpClickable !== true) throw new Error('o pino não recebe toques (gmpClickable)');
      this.fire('gmp-click', { type: 'gmp-click' });
    }

    // Para os testes: a pessoa arrasta o pino até ao ponto (só com gmpDraggable: true, como na Google).
    arrastarPara(lat, lng) {
      if (this.gmpDraggable !== true) throw new Error('o pino não se pode arrastar');
      const antes = this.pontoAtual ?? { lat, lng };
      this.fire('dragstart', { latLng: new LatLngFalso(antes.lat, antes.lng) });
      this.pontoAtual = exigirPonto({ lat, lng }, 'arrastarPara');
      this.fire('drag', { latLng: new LatLngFalso(lat, lng) });
      this.fire('dragend', { latLng: new LatLngFalso(lat, lng) });
    }
  }

  class CirculoFalso {
    constructor(opcoes = {}) {
      this.options = { ...opcoes };
      this.centro = opcoes.center === undefined || opcoes.center === null ? null : exigirPonto(opcoes.center, 'Circle center');
      this.raio = opcoes.radius;
      this.mapaAtual = null;
      this.setMap(opcoes.map ?? null);
    }

    setMap(mapa) { this.mapaAtual = porNoMapa(registo.circulos, this, mapa); }

    getMap() { return this.mapaAtual; }

    getCenter() { return this.centro ? new LatLngFalso(this.centro.lat, this.centro.lng) : null; }

    setCenter(centro) { this.centro = exigirPonto(centro, 'Circle.setCenter'); }

    getRadius() { return this.raio; }

    setRadius(raio) { this.raio = raio; }

    setOptions(opcoes = {}) {
      Object.assign(this.options, opcoes);
      if (opcoes.center !== undefined) this.setCenter(opcoes.center);
      if (opcoes.radius !== undefined) this.setRadius(opcoes.radius);
      if (opcoes.map !== undefined) this.setMap(opcoes.map);
    }

    // Os limites do círculo, pela mesma conta do gps.js (null sem centro ou sem raio válido).
    getBounds() {
      const limites = limitesDoCirculo(this.centro, this.raio);
      if (!limites) return null;
      const [[sul, oeste], [norte, este]] = limites;
      return new LatLngBoundsFalsos({ lat: sul, lng: oeste }, { lat: norte, lng: este });
    }
  }

  // google.maps.Polyline: o caminho guarda-se como literais {lat, lng}; getPath() devolve uma cópia (a Google
  // devolve um MVCArray de LatLng; aqui chega uma lista, que é o que os testes comparam).
  class PolilinhaFalsa {
    constructor(opcoes = {}) {
      this.options = { ...opcoes };
      this.mapaAtual = null;
      this.setPath(opcoes.path ?? []);
      this.setMap(opcoes.map ?? null);
    }

    setMap(mapa) { this.mapaAtual = porNoMapa(registo.linhas, this, mapa); }

    getMap() { return this.mapaAtual; }

    setPath(caminho) {
      if (!Array.isArray(caminho)) throw new TypeError('Polyline.path: não é uma lista');
      this.caminho = caminho.map((ponto) => exigirPonto(ponto, 'Polyline.path'));
    }

    getPath() { return this.caminho.map((ponto) => ({ ...ponto })); }

    setOptions(opcoes = {}) {
      Object.assign(this.options, opcoes);
      if (opcoes.path !== undefined) this.setPath(opcoes.path);
      if (opcoes.map !== undefined) this.setMap(opcoes.map);
    }
  }

  // Um balão nosso: nunca se cria no CRM (o balão do negócio é o da própria Google).
  class InfoWindowFalsa {
    constructor(opcoes = {}) {
      this.options = { ...opcoes };
      registo.infoWindowsNossas += 1;
    }

    open() {}

    close() {}
  }

  // google.maps.places.Place: só o `id` à partida; fetchFields({fields}) regista os campos pedidos e copia só
  // esses de registo.lugares[id] ({lat, lng, formattedAddress?, addressComponents?, …}); sem lugar, ou com
  // `falha: true`, rejeita como a Google quando o lugar não existe.
  class LugarFalso {
    constructor({ id, requestedLanguage, requestedRegion } = {}) {
      if (typeof id !== 'string' || id === '') throw new TypeError('Place: o id tem de ser um texto');
      this.id = id;
      this.requestedLanguage = requestedLanguage ?? null;
      this.requestedRegion = requestedRegion ?? null;
    }

    async fetchFields(pedido) {
      const campos = pedido?.fields;
      if (!Array.isArray(campos)) throw new TypeError('fetchFields: faltam os fields ({ fields: [...] })');
      registo.camposPedidos.push({ id: this.id, fields: [...campos] });
      const lugar = registo.lugares[this.id];
      if (!lugar || lugar.falha === true) throw new Error('NOT_FOUND');
      for (const campo of campos) {
        if (campo === 'id') continue;
        if (campo === 'location') {
          this.location = numero(lugar.lat) && numero(lugar.lng) ? alternarLugar({ lat: lugar.lat, lng: lugar.lng }) : null;
        } else {
          // Um campo pedido que o lugar não tem fica null, como na Google.
          this[campo] = campo in lugar ? lugar[campo] : null;
        }
      }
      return { place: this };
    }
  }

  // google.maps.places.PlaceAutocompleteElement: um elemento do documento (a Google dá um elemento à medida
  // com shadow DOM) com `escolher(id)` (a pessoa escolheu uma sugestão → 'gmp-select' com
  // `placePrediction.toPlace()`) e `falhar()` ('gmp-error'), para os testes.
  function PesquisaFalsa(opcoes = {}) {
    const elemento = documento.createElement('div');
    elemento.setAttribute('class', 'gmp-place-autocomplete-falso');
    elemento.opcoes = { ...opcoes };
    elemento.includedRegionCodes = opcoes.includedRegionCodes ?? null;
    elemento.locationBias = opcoes.locationBias ?? null;
    elemento.requestedRegion = opcoes.requestedRegion ?? null;
    elemento.escolher = (id) => {
      const evento = new Event('gmp-select');
      evento.placePrediction = { placeId: id, toPlace: () => new LugarFalso({ id }) };
      elemento.dispatchEvent(evento);
    };
    elemento.falhar = (mensagem = 'A pesquisa da Google falhou.') => {
      const evento = new Event('gmp-error');
      evento.error = new Error(mensagem);
      elemento.dispatchEvent(evento);
    };
    registo.pesquisas.push(elemento);
    return elemento;
  }

  const eventos = {
    addListener: (instancia, tipo, fn) => instancia.addListener(tipo, fn),
    addListenerOnce: (instancia, tipo, fn) => instancia.registar(tipo, fn, true),
    removeListener: (ouvinte) => ouvinte?.remove(),
    trigger: (instancia, tipo, ...args) => instancia.fire(tipo, ...args),
    clearInstanceListeners: (instancia) => instancia.limparOuvintes(),
  };

  const maps = {
    Map: MapaFalso,
    LatLng: LatLngFalso,
    LatLngBounds: LatLngBoundsFalsos,
    Circle: CirculoFalso,
    Polyline: PolilinhaFalsa,
    InfoWindow: InfoWindowFalsa,
    CollisionBehavior: COLLISION_BEHAVIOR,
    event: eventos,
    marker: { AdvancedMarkerElement: MarcadorFalso },
    places: { Place: LugarFalso, PlaceAutocompleteElement: PesquisaFalsa },
    // O carregador (carregadorGoogle.js) vê isto como "já carregado" e só delega.
    importLibrary: async (nome) => {
      registo.bibliotecas.push(nome);
      return maps;
    },
  };

  return { google: { maps }, registo };
}
