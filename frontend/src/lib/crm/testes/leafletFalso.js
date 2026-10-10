// Leaflet falso para testar o mapa no Jest (o Leaflet verdadeiro mede o
// elemento e carrega imagens, o que o jsdom não faz). Só testes; fica fora do
// varrimento do seguranca.test.js, que exclui a pasta `testes/`.
//
// Porta de tests/js/apoio/leaflet-falso.js do CRM autónomo (etiqueta
// `referencia-standalone`), tal e qual, com os comentários adaptados ao portal.
//
// Imita só o que o `lib/crm/mapa.js` usa, com o comportamento do Leaflet 1.9.4
// que importa para os testes:
//  - as camadas emitem eventos (on/once/off/fire) e o mapa emite 'add'/'remove'
//    nelas e 'layeradd';
//  - o controlo de atribuição junta as atribuições das camadas que estão no mapa
//    e esquece a de uma camada quando ela sai (com um `once('remove')` na própria
//    camada, como o Leaflet: um `off()` sem argumentos nessa camada deixava a
//    atribuição antiga para sempre);
//  - um grupo de camadas põe e tira os filhos do mapa com ele;
//  - o arrasto de um marcador (marker.dragging) só existe com o marcador no
//    mapa, como no Leaflet: é criado ao entrar (ligado se a opção draggable o
//    pedir) e apagado ao sair (ligado, a opção draggable fica true);
//  - um círculo (L.circle) guarda o centro e o raio em metros (options.radius),
//    como no Leaflet.
// Regista os mapas criados em `registo.mapas`.

class EventosFalsos {
  constructor() {
    this.ouvintes = new Map();
  }

  on(tipo, fn) {
    if (!this.ouvintes.has(tipo)) this.ouvintes.set(tipo, []);
    this.ouvintes.get(tipo).push({ fn, umaVez: false });
    return this;
  }

  once(tipo, fn) {
    if (!this.ouvintes.has(tipo)) this.ouvintes.set(tipo, []);
    this.ouvintes.get(tipo).push({ fn, umaVez: true });
    return this;
  }

  off(tipo, fn) {
    if (tipo === undefined) {
      this.ouvintes.clear();
    } else if (fn === undefined) {
      this.ouvintes.delete(tipo);
    } else if (this.ouvintes.has(tipo)) {
      this.ouvintes.set(tipo, this.ouvintes.get(tipo).filter((o) => o.fn !== fn));
    }
    return this;
  }

  fire(tipo, dados = {}) {
    const lista = this.ouvintes.get(tipo) ?? [];
    this.ouvintes.set(tipo, lista.filter((o) => !o.umaVez));
    for (const { fn } of lista) fn.call(this, { type: tipo, target: this, ...dados });
    return this;
  }

  listens(tipo) {
    return (this.ouvintes.get(tipo)?.length ?? 0) > 0;
  }
}

class CamadaFalsa extends EventosFalsos {
  constructor(opcoes = {}) {
    super();
    this.options = opcoes;
    this.mapa = null;
  }

  addTo(alvo) {
    alvo.addLayer(this);
    return this;
  }

  remove() {
    this.mapa?.removeLayer(this);
    return this;
  }

  getAttribution() {
    return this.options.attribution;
  }
}

export class MosaicosFalsos extends CamadaFalsa {
  constructor(url, opcoes) {
    super(opcoes);
    this.url = url;
  }
}

class ArrastoFalso {
  constructor(ligado) {
    this.ligado = ligado;
  }

  enable() {
    this.ligado = true;
    return this;
  }

  disable() {
    this.ligado = false;
    return this;
  }

  enabled() {
    return this.ligado;
  }
}

export class MarcadorFalso extends CamadaFalsa {
  constructor(latlng, opcoes) {
    super(opcoes);
    this.latlng = latlng;
    this.etiqueta = null;
  }

  aoEntrar() {
    this.dragging = new ArrastoFalso(this.options.draggable === true);
  }

  aoSair() {
    if (this.dragging.enabled()) this.options.draggable = true;
    delete this.dragging;
  }

  setLatLng(latlng) {
    this.latlng = latlng;
    this.fire('move');
    return this;
  }

  // Para os testes: a pessoa arrasta o pino até ao ponto (só se o arrasto estiver ligado).
  arrastarPara(lat, lng) {
    if (!this.dragging?.enabled()) throw new Error('o pino não se pode arrastar');
    this.fire('dragstart');
    this.latlng = { lat, lng };
    this.fire('drag');
    this.fire('dragend');
  }

  bindTooltip(conteudo, opcoes) {
    this.etiqueta = { conteudo, opcoes };
    return this;
  }

  // Como no Leaflet: sempre {lat, lng}, mesmo que o marcador tenha sido criado com [lat, lng].
  getLatLng() {
    const [lat, lng] = Array.isArray(this.latlng) ? this.latlng : [this.latlng.lat, this.latlng.lng];
    return { lat, lng };
  }

  // O elemento do ícone (no Leaflet, só existe com o marcador no mapa). Os testes podem pôr um.
  getElement() {
    return this.elemento ?? null;
  }
}

export class CirculoFalso extends CamadaFalsa {
  constructor(latlng, opcoes = {}) {
    super(opcoes);
    this.latlng = latlng;
  }

  getLatLng() {
    const [lat, lng] = Array.isArray(this.latlng) ? this.latlng : [this.latlng.lat, this.latlng.lng];
    return { lat, lng };
  }

  getRadius() {
    return this.options.radius;
  }
}

class GrupoFalso extends CamadaFalsa {
  constructor() {
    super();
    this.filhos = new Set();
  }

  addLayer(camada) {
    this.filhos.add(camada);
    this.mapa?.addLayer(camada);
    return this;
  }

  clearLayers() {
    for (const camada of this.filhos) this.mapa?.removeLayer(camada);
    this.filhos.clear();
    return this;
  }

  getLayers() {
    return [...this.filhos];
  }

  aoEntrar(mapa) {
    for (const camada of this.filhos) mapa.addLayer(camada);
  }

  aoSair(mapa) {
    for (const camada of this.filhos) mapa.removeLayer(camada);
  }
}

class AtribuicaoFalsa {
  constructor(opcoes = {}) {
    this.options = opcoes;
    this.contagem = new Map();
  }

  addTo(mapa) {
    mapa.controlos.push(this);
    mapa.attributionControl = this;
    for (const camada of mapa.camadas) this.acrescentar(camada);
    mapa.on('layeradd', (evento) => this.acrescentar(evento.layer));
    return this;
  }

  acrescentar(camada) {
    const texto = camada.getAttribution?.();
    if (!texto) return;
    this.contagem.set(texto, (this.contagem.get(texto) ?? 0) + 1);
    camada.once('remove', () => this.contagem.set(texto, this.contagem.get(texto) - 1));
  }

  // O que o Leaflet põe no controlo: o prefixo (se houver) e as atribuições separadas por ", ".
  get html() {
    const textos = [...this.contagem].filter(([, n]) => n > 0).map(([texto]) => texto);
    const partes = [];
    if (this.options.prefix) partes.push(this.options.prefix);
    if (textos.length > 0) partes.push(textos.join(', '));
    return partes.join(' | ');
  }
}

export class MapaFalso extends EventosFalsos {
  constructor(elemento, opcoes = {}) {
    super();
    this.elemento = elemento;
    this.options = opcoes;
    this.camadas = new Set();
    this.controlos = [];
    this.vistas = [];
    this.redimensionamentos = [];
    this.removido = false;
    this.attributionControl = undefined;
  }

  addLayer(camada) {
    if (this.camadas.has(camada)) return this;
    this.camadas.add(camada);
    camada.mapa = this;
    camada.aoEntrar?.(this);
    camada.fire('add');
    this.fire('layeradd', { layer: camada });
    return this;
  }

  removeLayer(camada) {
    if (!this.camadas.has(camada)) return this;
    this.camadas.delete(camada);
    camada.aoSair?.(this);
    camada.mapa = null;
    camada.fire('remove');
    this.fire('layerremove', { layer: camada });
    return this;
  }

  hasLayer(camada) {
    return this.camadas.has(camada);
  }

  setView(centro, zoom) {
    this.vistas.push({ tipo: 'setView', centro, zoom });
    this.zoom = zoom;
    return this;
  }

  getZoom() {
    return this.zoom;
  }

  // O centro da última vista posta com setView, como {lat, lng} (o Leaflet lança um erro antes de haver vista).
  getCenter() {
    const vista = this.vistas.findLast((v) => v.tipo === 'setView' || v.tipo === 'panTo');
    if (!vista) throw new Error('Set map center and zoom first.');
    const [lat, lng] = Array.isArray(vista.centro) ? vista.centro : [vista.centro.lat, vista.centro.lng];
    return { lat, lng };
  }

  fitBounds(limites, opcoes) {
    this.vistas.push({ tipo: 'fitBounds', limites, opcoes });
    return this;
  }

  panTo(centro, opcoes) {
    this.vistas.push({ tipo: 'panTo', centro, opcoes });
    return this;
  }

  invalidateSize(opcoes) {
    this.redimensionamentos.push(opcoes);
    return this;
  }

  remove() {
    for (const camada of [...this.camadas]) this.removeLayer(camada);
    this.removido = true;
    return this;
  }

  // Para os testes
  get mosaicos() {
    return [...this.camadas].filter((c) => c instanceof MosaicosFalsos);
  }

  get marcadores() {
    return [...this.camadas].filter((c) => c instanceof MarcadorFalso);
  }

  get circulos() {
    return [...this.camadas].filter((c) => c instanceof CirculoFalso);
  }
}

export function leafletFalso() {
  const registo = { mapas: [] };
  const L = {
    map(elemento, opcoes) {
      const mapa = new MapaFalso(elemento, opcoes);
      registo.mapas.push(mapa);
      return mapa;
    },
    control: { attribution: (opcoes) => new AtribuicaoFalsa(opcoes) },
    tileLayer: (url, opcoes) => new MosaicosFalsos(url, opcoes),
    layerGroup: () => new GrupoFalso(),
    marker: (latlng, opcoes) => new MarcadorFalso(latlng, opcoes),
    circle: (latlng, opcoes) => new CirculoFalso(latlng, opcoes),
    divIcon: (opcoes) => ({ tipo: 'divIcon', options: opcoes }),
    latLngBounds: (pontos) => ({ tipo: 'latLngBounds', pontos }),
  };
  return { L, registo };
}
