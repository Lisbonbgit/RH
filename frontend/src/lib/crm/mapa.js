// O mapa das lojas sobre o Google Maps (Maps JavaScript API, só peças GA;
// adenda do mapa Google §6.1, plano G6). A Google (`google`) e o documento são
// recebidos por parâmetro: o `MapaLojas` passa o `window.google` depois do
// `importar` do `carregadorGoogle.js`; os testes passam os falsos de `testes/`.
//
//  - Um só `google.maps.Map` no elemento, com o Map ID da configuração (sem
//    ele os marcadores avançados não aparecem), zoom do 6 ao 19 e só os botões
//    de zoom da Google (os títulos já vêm em português). A atribuição e o
//    logótipo são os da própria Google: nunca se escondem nem se tapam.
//  - Cada loja é um `AdvancedMarkerElement` com a cor da fase e o nome sempre
//    visível ao lado, em qualquer zoom, sem agrupamento e sem se esconder por
//    colisão. O conteúdo do pino é um nó DOM montado com o `el()` (o nome entra
//    por textContent): nunca HTML vindo de dados. Este ficheiro e o
//    `seletor.js` são os únicos onde um marcador recebe conteúdo.
//  - Tocar num pino (ou Enter/Espaço com o foco nele: a Google emite o mesmo
//    `gmp-click`) escolhe a loja; o ecrã abre o cartão da loja.
//  - Tocar no ícone de um negócio da Google abre o balão do lugar da própria
//    Google: o código nunca o trava (não se chama `stop()` no evento) e nunca
//    cria um balão seu; o ecrã recebe só o identificador do lugar e o ponto
//    tocado (`aoTocarNumLugar`). Com `negociosClicaveis: false` (o planeador)
//    a Google não emite o lugar e tudo é toque no mapa.
//  - As posições da Google chegam ora como `LatLng` (lat()/lng() em função) ora
//    como literal {lat, lng}: lê-las sempre pelo `pontoDe`.
//  - O elemento guarda o Map em `__crmMapa`, só para a verificação no browser
//    (regra 16 do plano): nenhum código do CRM o lê.
//  - A rota do planeador (F3, T3.33; correções do mapa Google do plano da F3)
//    é um grupo à parte, por cima das lojas: um pino numerado por paragem (o
//    número e o nome entram por textContent no `content` do `el()`), os
//    extremos (um só "Início e fim: fábrica" quando calham no mesmo ponto) e a
//    linha do openrouteservice (`google.maps.Polyline`, cheia com as horas em
//    dia, tracejada com as horas velhas). A geometria vem do servidor, nunca
//    da Google. As lojas e a rota mostram-se e tiram-se cada uma por si.
//  - A posição da própria pessoa ("A minha localização", desenho de
//    2026-11-06) é outro grupo: um ponto azul por cima de tudo, com o círculo
//    da precisão (`google.maps.Circle`). Não recebem toques (as lojas por baixo
//    continuam a tocar-se) e vivem só no mapa: a regra de quando aparecem está
//    em `minhaLocalizacao.js`.

import { el } from './dom';
import { FASES, ORDEM, classePino } from './fases';

export const ZOOM_MINIMO = 6;
export const ZOOM_MAXIMO = 19;
// Sem lojas, o mapa mostra a zona da fábrica.
export const ZOOM_SEM_LOJAS = 12;
// Com uma loja só (ou muito juntas), o enquadramento não vai até ao zoom máximo.
export const ZOOM_MAXIMO_ENQUADRAR = 16;
// Ao voltar ao mapa depois de guardar uma loja nova: ao nível da rua, com os nomes à volta.
export const ZOOM_LOJA = 17;
// Ao ligar "A minha localização": perto o bastante para se verem as ruas e as lojas à volta da pessoa.
export const ZOOM_MINHA_POSICAO = 16;
// O ponto da fábrica por defeito (os PADROES de backend/crm/dominio/definicoes.py),
// se a configuração não trouxer o centro.
export const CENTRO_PADRAO = Object.freeze({ lat: 38.7223, lng: -9.1393 });
// Folga (px) à volta das lojas (ou da rota) no enquadramento (as etiquetas ficam à direita dos pinos).
export const MARGEM_ENQUADRAR = 40;

// A Google não carregou (rede, quota, referrer) ou não criou o mapa.
export const MENSAGEM_SEM_MAPA = 'Não foi possível carregar o mapa — recarregue a página.';
// O servidor não tem a chave do navegador ou o Map ID (o GET /api/crm/config trouxe google: null).
export const MENSAGEM_MAPA_NAO_CONFIGURADO = 'Mapa não configurado — peça ao administrador para configurar a chave Google.';

// A rota do planeador por cima dos pinos das lojas, que não têm zIndex: a Google ordena-os pela altura no ecrã
// e, nos marcadores antigos dela, o maior zIndex que atribuía sozinha era o MAX_ZINDEX (1000000). As paragens
// ficam por cima dos extremos.
export const ZINDEX_EXTREMO = 1000001;
export const ZINDEX_PARAGEM = 1000002;
// O ponto da pessoa fica por cima das lojas e da rota.
export const ZINDEX_MINHA_POSICAO = 1000003;
// Os nomes dos pinos dos extremos (o título e a etiqueta).
export const TEXTO_INICIO = 'Início';
export const TEXTO_FIM = 'Fim';
export const TEXTO_INICIO_E_FIM = 'Início e fim';
export const TEXTO_INICIO_E_FIM_FABRICA = 'Início e fim: fábrica';
// A linha da rota: o roxo da marca (o do cliente, em fases.js), sem CSS (a Google desenha-a ela própria).
export const COR_LINHA_ROTA = '#6b2fa3';
// As opções da linha (objetos novos a cada vez: a Google fica com eles). Com as horas em dia, cheia; com as
// horas velhas (o cálculo já não serve), o traço só nos ícones: um traço curto repetido a cada 14 px, a
// tracejada. Nunca recebe toques (um toque nela é um toque no mapa).
function opcoesDaLinha(atual) {
  if (atual) return { strokeColor: COR_LINHA_ROTA, strokeWeight: 4, strokeOpacity: 0.9, clickable: false };
  return {
    strokeColor: COR_LINHA_ROTA,
    strokeWeight: 4,
    strokeOpacity: 0,
    icons: [{ icon: { path: 'M 0,-1 0,1', strokeOpacity: 0.6, scale: 3 }, offset: '0', repeat: '14px' }],
    clickable: false,
  };
}

// O ponto da pessoa e o círculo da precisão: o azul de "estou aqui" dos mapas, para não se confundir com o roxo das
// lojas nem com o da rota (o crm.css pinta o ponto com a mesma cor; o círculo desenha-o a Google, sem CSS). Cores
// fixas, como os pinos: o mapa é claro também no tema escuro. O círculo nunca recebe toques.
export const TEXTO_MINHA_POSICAO = 'A sua posição';
export const COR_MINHA_POSICAO = '#1a73e8';
export const ESTILO_PRECISAO = Object.freeze({
  strokeColor: COR_MINHA_POSICAO,
  strokeOpacity: 0.4,
  strokeWeight: 1,
  fillColor: COR_MINHA_POSICAO,
  fillOpacity: 0.15,
  clickable: false,
});

const textoPreenchido = (valor) => typeof valor === 'string' && valor.trim() !== '';

// A configuração do GET /api/crm/config serve para criar o mapa: {google: {chave, map_id}, centro}, com a
// chave do navegador e o Map ID em texto. Pode faltar (o pedido falhou) ou vir com google: null.
export const configuracaoValida = (configuracao) =>
  textoPreenchido(configuracao?.google?.chave) && textoPreenchido(configuracao?.google?.map_id);

const numero = (valor) => typeof valor === 'number' && Number.isFinite(valor);
const temCoordenadas = (loja) => numero(loja?.lat) && numero(loja?.lng);
const pontoDaLoja = (loja) => ({ lat: loja.lat, lng: loja.lng });

// {lat, lng} numérico a partir de um literal ou de um LatLng da Google (lat() e lng() em função); o resto
// (um par [lat, lng] incluído) → null.
export function pontoDe(valor) {
  if (valor === null || typeof valor !== 'object') return null;
  const funcoes = typeof valor.lat === 'function' && typeof valor.lng === 'function';
  const lat = funcoes ? valor.lat() : valor.lat;
  const lng = funcoes ? valor.lng() : valor.lng;
  return numero(lat) && numero(lng) ? { lat, lng } : null;
}

// O limite do zoom que espera pelo próximo `idle` de cada mapa (um só por mapa).
const limitesPendentes = new WeakMap();

function cancelarLimiteDoZoom(mapa) {
  const ouvinte = limitesPendentes.get(mapa);
  if (!ouvinte) return;
  limitesPendentes.delete(mapa);
  ouvinte.remove();
}

// O fitBounds da Google não aceita um zoom máximo: limita-se no primeiro `idle` depois de enquadrar. O
// ouvinte guarda-se (um só por mapa): a chamada seguinte, um zoom pedido pelo código e o `destruir` tiram-no,
// para um `idle` tardio não desfazer o zoom que a pessoa (ou o ecrã) escolheu entretanto. Devolve o ouvinte
// (o MapsEventListener da Google). Também a usa o seletor (o círculo do GPS).
export function limitarZoomDepoisDeEnquadrar(google, mapa, maximo) {
  cancelarLimiteDoZoom(mapa);
  const ouvinte = google.maps.event.addListenerOnce(mapa, 'idle', () => {
    if (limitesPendentes.get(mapa) === ouvinte) limitesPendentes.delete(mapa);
    const zoom = mapa.getZoom();
    if (numero(zoom) && zoom > maximo) mapa.setZoom(maximo);
  });
  limitesPendentes.set(mapa, ouvinte);
  return ouvinte;
}

function tituloPino(loja) {
  const fase = ORDEM.includes(loja.fase) ? FASES[loja.fase].rotulo : null;
  return fase ? `${loja.nome} (${fase})` : String(loja.nome);
}

// --- A rota do planeador ---

const texto = (valor) => (typeof valor === 'string' ? valor : '');

// A linha do planeador chega em pares [lat, lng] (o `descodificarPolilinha`); a Google quer literais {lat, lng}.
// Um par estragado deita fora a linha toda, como o descodificador faz a um texto estragado.
function caminhoDaLinha(linha) {
  if (!Array.isArray(linha)) return [];
  const caminho = [];
  for (const par of linha) {
    if (!Array.isArray(par) || par.length !== 2 || !numero(par[0]) || !numero(par[1])) return [];
    caminho.push({ lat: par[0], lng: par[1] });
  }
  return caminho;
}

// "3. Café X", com o aviso (já em texto) a seguir; uma paragem sem número (fechada, não cabe) só com o nome.
function tituloParagem(paragem) {
  const nome = texto(paragem.nome);
  const base = Number.isInteger(paragem.numero) ? `${paragem.numero}. ${nome}` : nome;
  return textoPreenchido(paragem.aviso) ? `${base} — ${paragem.aviso}` : base;
}

// Os pinos dos extremos: um só quando o início e o fim calham no mesmo ponto ("Início e fim: fábrica" se os
// dois são a fábrica); senão "Início" e "Fim", e só os que têm coordenadas.
function extremosDaRota(inicio, fim) {
  const a = temCoordenadas(inicio) ? inicio : null;
  const b = temCoordenadas(fim) ? fim : null;
  if (a && b && a.lat === b.lat && a.lng === b.lng) {
    const fabrica = a.fabrica === true && b.fabrica === true;
    return [{ ponto: pontoDaLoja(a), nome: fabrica ? TEXTO_INICIO_E_FIM_FABRICA : TEXTO_INICIO_E_FIM }];
  }
  return [
    a && { ponto: pontoDaLoja(a), nome: TEXTO_INICIO },
    b && { ponto: pontoDaLoja(b), nome: TEXTO_FIM },
  ].filter(Boolean);
}

// criarMapa({google, documento, elemento, configuracao, negociosClicaveis = true, aoEscolherLoja?,
//            aoTocarNoMapa?, aoTocarNumLugar?})
//   → {mapa, mostrarLojas, enquadrar, mostrarRota, enquadrarRota, redimensionar, centrarEm, mostrarMinhaPosicao,
//      focar, destruir}
//  - configuracao: a do GET /api/crm/config, {google: {chave, map_id}, centro: {lat, lng}} (ver configuracaoValida);
//  - aoEscolherLoja(loja, marcador): tocaram no pino da loja;
//  - aoTocarNoMapa({lat, lng} | null): tocaram no mapa, fora dos pinos e dos negócios, nesse ponto (os toques
//    num pino não chegam ao mapa);
//  - aoTocarNumLugar({placeId, lat, lng}): tocaram no ícone de um negócio (o balão da Google abre na mesma);
//    lat/lng são o ponto tocado, só como reserva. Sem ele, o toque num negócio chega a aoTocarNoMapa.
export function criarMapa({
  google, documento, elemento, configuracao, negociosClicaveis = true, aoEscolherLoja, aoTocarNoMapa, aoTocarNumLugar,
}) {
  const centro = temCoordenadas(configuracao.centro) ? pontoDaLoja(configuracao.centro) : { ...CENTRO_PADRAO };
  const clicaveis = Boolean(negociosClicaveis);
  const mapa = new google.maps.Map(elemento, {
    mapId: configuracao.google.map_id,
    center: centro,
    zoom: ZOOM_SEM_LOJAS,
    minZoom: ZOOM_MINIMO,
    maxZoom: ZOOM_MAXIMO,
    clickableIcons: clicaveis,
    disableDefaultUI: true,
    zoomControl: true,
    gestureHandling: 'greedy',
    mapTypeId: 'roadmap',
  });
  // A div do mapa não é focável por si: o ecrã devolve-lhe o foco ao fechar o cartão (focar()).
  elemento.tabIndex = -1;
  elemento.__crmMapa = mapa;

  const tocarNoMapa = typeof aoTocarNoMapa === 'function' ? aoTocarNoMapa : null;
  const tocarNumLugar = typeof aoTocarNumLugar === 'function' ? aoTocarNumLugar : null;
  if (tocarNoMapa || tocarNumLugar) {
    // Nunca evento.stop(): num negócio, o balão da Google abre como em qualquer site.
    mapa.addListener('click', (evento) => {
      const ponto = pontoDe(evento?.latLng);
      const placeId = clicaveis && textoPreenchido(evento?.placeId) ? evento.placeId : null;
      if (placeId && tocarNumLugar) {
        tocarNumLugar({ placeId, lat: ponto ? ponto.lat : null, lng: ponto ? ponto.lng : null });
        return;
      }
      tocarNoMapa?.(ponto);
    });
  }

  let marcadores = [];
  // A rota (mostrarRota): os pinos das paragens e dos extremos, a linha e os pontos para o enquadrarRota.
  let pinosDaRota = [];
  let linhaDaRota = null;
  let pontosDaRota = [];
  // A posição da pessoa (mostrarMinhaPosicao): o ponto e o círculo da precisão.
  let pontoDaPessoa = null;
  let circuloDaPessoa = null;
  let destruido = false;

  function pino(loja) {
    const marcador = new google.maps.marker.AdvancedMarkerElement({
      map: mapa,
      position: pontoDaLoja(loja),
      content: el(documento, 'div', {
        classe: classePino(loja.fase),
        filhos: [
          el(documento, 'span', { classe: 'pino__bola' }),
          el(documento, 'span', { classe: 'etiqueta-loja', texto: loja.nome }),
        ],
      }),
      title: tituloPino(loja),
      gmpClickable: true,
      collisionBehavior: google.maps.CollisionBehavior.REQUIRED,
    });
    if (typeof aoEscolherLoja === 'function') {
      marcador.addListener('gmp-click', () => aoEscolherLoja(loja, marcador));
    }
    return marcador;
  }

  // Uma paragem da rota: {id, numero, nome, fase, lat, lng, aviso, …} do `vista.mapa.paragens` (planeador.js).
  // O número só nas da secção "rota"; o aviso já vem em texto.
  function pinoParagem(paragem, aoEscolherParagem) {
    const comNumero = Number.isInteger(paragem.numero);
    const marcador = new google.maps.marker.AdvancedMarkerElement({
      map: mapa,
      position: pontoDaLoja(paragem),
      content: el(documento, 'div', {
        classe: [
          'pino-paragem',
          ORDEM.includes(paragem.fase) && `pino--${paragem.fase}`,
          textoPreenchido(paragem.aviso) && 'pino-paragem--aviso',
          !comNumero && 'pino-paragem--sem-numero',
        ],
        filhos: [
          comNumero && el(documento, 'span', { classe: 'pino-paragem__numero', texto: String(paragem.numero) }),
          el(documento, 'span', { classe: 'etiqueta-loja', texto: texto(paragem.nome) }),
        ],
      }),
      title: tituloParagem(paragem),
      gmpClickable: true,
      collisionBehavior: google.maps.CollisionBehavior.REQUIRED,
      zIndex: ZINDEX_PARAGEM,
    });
    if (typeof aoEscolherParagem === 'function') {
      marcador.addListener('gmp-click', () => aoEscolherParagem(paragem, marcador));
    }
    return marcador;
  }

  // O início, o fim, ou os dois num só pino. Não se escolhe: não recebe toques.
  function pinoExtremo({ ponto, nome }) {
    return new google.maps.marker.AdvancedMarkerElement({
      map: mapa,
      position: ponto,
      content: el(documento, 'div', {
        classe: 'pino-extremo',
        filhos: [
          el(documento, 'span', { classe: 'pino-extremo__marca' }),
          el(documento, 'span', { classe: 'etiqueta-loja', texto: nome }),
        ],
      }),
      title: nome,
      collisionBehavior: google.maps.CollisionBehavior.REQUIRED,
      zIndex: ZINDEX_EXTREMO,
    });
  }

  // Com a chave recusada pela Google (ex.: RefererNotAllowedMapError), `marcador.map = null` lança dentro da
  // biblioteca; tirar os pinos (e a linha) nunca pode derrubar a página do CRM (visto em produção a 2026-10-22).
  function tirarDoMapa(lista) {
    for (const marcador of lista) {
      try {
        marcador.map = null;
      } catch {
        // O mapa já não existe para a Google: não há pino para tirar.
      }
    }
  }

  function tirarPinos() {
    tirarDoMapa(marcadores);
    marcadores = [];
  }

  function tirarRota() {
    tirarDoMapa(pinosDaRota);
    try {
      linhaDaRota?.setMap(null);
    } catch {
      // Idem: o mapa já não existe para a Google.
    }
    pinosDaRota = [];
    linhaDaRota = null;
    pontosDaRota = [];
  }

  // Não é clicável e o crm.css tira-lhe os toques: um toque no ponto chega ao pino ou ao mapa que estão por baixo.
  function pontoMinhaPosicao(ponto) {
    return new google.maps.marker.AdvancedMarkerElement({
      map: mapa,
      position: ponto,
      content: el(documento, 'div', { classe: 'ponto-minha-posicao' }),
      title: TEXTO_MINHA_POSICAO,
      collisionBehavior: google.maps.CollisionBehavior.REQUIRED,
      zIndex: ZINDEX_MINHA_POSICAO,
    });
  }

  function tirarCirculoDaPessoa() {
    try {
      circuloDaPessoa?.setMap(null);
    } catch {
      // Idem: o mapa já não existe para a Google.
    }
    circuloDaPessoa = null;
  }

  function tirarMinhaPosicao() {
    if (pontoDaPessoa) tirarDoMapa([pontoDaPessoa]);
    pontoDaPessoa = null;
    tirarCirculoDaPessoa();
  }

  // Todos os pontos à vista (sem passar do zoom 16); sem nenhum, o centro das definições (o ponto da fábrica).
  function enquadrarPontos(pontos) {
    if (pontos.length > 0) {
      const limites = new google.maps.LatLngBounds();
      for (const ponto of pontos) limites.extend(ponto);
      mapa.fitBounds(limites, MARGEM_ENQUADRAR);
      limitarZoomDepoisDeEnquadrar(google, mapa, ZOOM_MAXIMO_ENQUADRAR);
      return;
    }
    cancelarLimiteDoZoom(mapa);
    mapa.setCenter({ ...centro });
    mapa.setZoom(ZOOM_SEM_LOJAS);
  }

  return {
    mapa,
    // Mostra estas lojas (e só estas): {id, nome, fase, lat, lng, …} do GET /api/crm/lojas.
    mostrarLojas(lojas) {
      if (destruido) return;
      tirarPinos();
      marcadores = lojas.filter(temCoordenadas).map(pino);
    },
    // A vista inicial: todas as lojas à vista (sem passar do zoom 16); sem lojas, o centro das definições
    // (o ponto da fábrica).
    enquadrar(lojas) {
      if (destruido) return;
      enquadrarPontos(lojas.filter(temCoordenadas).map(pontoDaLoja));
    },
    // Mostra esta rota (e só esta) por cima das lojas: o `vista.mapa` do planeador, {paragens, inicio, fim,
    // linha, linhaAtual, …} (as pontas {lat, lng, fabrica} ou null; a linha em pares [lat, lng]). A linha só
    // com 2 pontos ou mais; `null` tira a rota. aoEscolherParagem(paragem, marcador): tocaram no pino da
    // paragem (ou Enter/Espaço com o foco nele).
    mostrarRota(rota, opcoes) {
      if (destruido) return;
      tirarRota();
      if (rota === null || typeof rota !== 'object') return;
      const caminho = caminhoDaLinha(rota.linha);
      if (caminho.length >= 2) {
        linhaDaRota = new google.maps.Polyline({ path: caminho, ...opcoesDaLinha(rota.linhaAtual === true), map: mapa });
      }
      const paragens = Array.isArray(rota.paragens) ? rota.paragens.filter(temCoordenadas) : [];
      const extremos = extremosDaRota(rota.inicio, rota.fim);
      pinosDaRota = [
        ...paragens.map((paragem) => pinoParagem(paragem, opcoes?.aoEscolherParagem)),
        ...extremos.map(pinoExtremo),
      ];
      pontosDaRota = [...paragens.map(pontoDaLoja), ...extremos.map((extremo) => extremo.ponto)];
    },
    // A rota à vista: as paragens e os extremos da última rota mostrada (sem passar do zoom 16); sem nenhum
    // ponto, o centro das definições.
    enquadrarRota() {
      if (destruido) return;
      enquadrarPontos(pontosDaRota);
    },
    // Depois de a área do mapa mudar de tamanho (ex.: o cartão da loja abre ao lado). A Google mede-se sozinha
    // nas versões atuais; o aviso fica pela interface e é inofensivo.
    redimensionar() {
      if (destruido) return;
      google.maps.event.trigger(mapa, 'resize');
    },
    // Põe a loja ao centro. Sem zoom, desloca-se até ela sem mudar o zoom; com zoom, mostra-a logo nesse zoom
    // (e um limite do enquadramento ainda à espera já não conta).
    centrarEm(loja, zoom) {
      if (destruido || !temCoordenadas(loja)) return;
      if (numero(zoom)) {
        cancelarLimiteDoZoom(mapa);
        mapa.setCenter(pontoDaLoja(loja));
        mapa.setZoom(zoom);
      } else {
        mapa.panTo(pontoDaLoja(loja));
      }
    },
    // A posição da pessoa, {lat, lng, precisao_m}: o ponto e o círculo criam-se uma vez e depois só se movem, sem
    // tocar na vista do mapa. Sem precisão (ou com 0 m), só o ponto; `null` tira os dois; uma posição sem
    // coordenadas válidas não muda nada.
    mostrarMinhaPosicao(posicao) {
      if (destruido) return;
      if (posicao === null) {
        tirarMinhaPosicao();
        return;
      }
      if (!temCoordenadas(posicao)) return;
      const ponto = pontoDaLoja(posicao);
      if (pontoDaPessoa) pontoDaPessoa.position = ponto;
      else pontoDaPessoa = pontoMinhaPosicao(ponto);
      const raio = posicao.precisao_m;
      if (!numero(raio) || raio <= 0) {
        tirarCirculoDaPessoa();
      } else if (circuloDaPessoa) {
        circuloDaPessoa.setCenter(ponto);
        circuloDaPessoa.setRadius(raio);
      } else {
        circuloDaPessoa = new google.maps.Circle({ ...ESTILO_PRECISAO, center: ponto, radius: raio, map: mapa });
      }
    },
    // O foco no mapa (ao fechar o cartão de uma loja cujo pino já não existe).
    focar() {
      if (destruido) return;
      elemento.focus();
    },
    // No cleanup do useEffect (o StrictMode monta duas vezes em desenvolvimento): a Google nunca tira o DOM
    // que pôs no elemento, por isso esvazia-se aqui, para um mapa novo no mesmo elemento não ficar por cima.
    // Uma segunda chamada não faz nada (não mexe num mapa novo do mesmo elemento).
    destruir() {
      if (destruido) return;
      destruido = true;
      cancelarLimiteDoZoom(mapa);
      tirarPinos();
      tirarRota();
      tirarMinhaPosicao();
      google.maps.event.clearInstanceListeners(mapa);
      if (elemento.__crmMapa === mapa) delete elemento.__crmMapa;
      elemento.replaceChildren();
    },
  };
}
