// O seletor da localização de uma loja (desenho original §6.2; plano T2.26),
// sem DOM: as regras do componente do CRM autónomo
// (public/assets/js/componentes/seletor-localizacao.js) fora do React, para
// terem testes (correção "T2.26 / T2.27 / T2.29 / T2.30 (componentes "Sem
// Jest")", na parte do seletor da T2.24a). O
// `components/crm/SeletorLocalizacao.js` só desenha a `vista` e liga os botões;
// a nova loja (T2.27), a ficha (T2.28, "Corrigir localização") e a fábrica
// (T2.30, sem GPS) usam esse componente.
//
// Um mapa onde se toca para pôr o pino, que se arrasta até ao sítio exato e se
// confirma com "Confirmar localização":
//  - com a `api` (a do `lib/crm/api.js`), a pesquisa de morada por cima do
//    mapa (`pesquisaMorada.js`): escolher uma sugestão põe lá o pino (origem
//    geocoder), solto, aproxima o mapa (zoom 18) e entrega a sugestão ao ecrã
//    (`aoEscolherMorada`), para preencher a morada, o código postal e a
//    localidade (`camposDaMorada`);
//  - com a `geolocation` (navigator.geolocation), "Estou nesta loja" (dossiê
//    §5.4). O GPS só se pede quando se toca no botão (nunca seguimento
//    contínuo); enquanto espera, o botão diz "A obter a localização…" e não
//    volta a pedir. A posição põe lá o pino (origem gps), solto, com um círculo
//    do tamanho da precisão, e o mapa enquadra o círculo. Com a precisão pior
//    que 50 m: "Localização imprecisa — ajuste o pino", e só se confirma depois
//    de arrastar (fica pin_manual). Se o pino mudar de sítio por outra via
//    (toque no mapa, arrasto, morada escolhida) antes de o GPS responder, a
//    posição (ou o erro) que chega depois é ignorada;
//  - com a `api`, a geocodificação inversa do ponto do GPS (GET
//    /api/crm/morada/inversa) mostra "Morada sugerida: … · Powered by Geoapify"
//    e entrega-a ao ecrã (`aoSugerirMorada`, que só preenche os campos vazios:
//    `camposSugeridos`). Se o pino for posto noutro sítio, a morada sugerida
//    sai (e a que chegar tarde é ignorada).
//
// Estados: 'vazio' (sem pino) → 'por_confirmar' (pino solto, arrastável) →
// 'confirmado' (pino fixo; "Alterar localização" solta-o outra vez). Só a
// localização confirmada conta para guardar. A origem das coordenadas segue o
// `localizacao.js`: um pino arrastado passa a pin_manual.
//
// O mapa é o do `mapa.js` (os mesmos mosaicos, a mesma atribuição e a troca
// para o OSM). O Leaflet e o documento são recebidos por parâmetro. O pino não
// leva HTML: é um `divIcon` só com a classe, e a gota desenha-se no CSS
// (`.pino-seletor`, em `components/crm/crm.css`). O seletor não põe texto
// nenhum no Leaflet.

import { ATRIBUICOES } from './atribuicoes';
import { criarMapa, configuracaoValida, MENSAGEM_SEM_MAPA } from './mapa';
import { podeConfirmar, localizacaoFinal } from './localizacao';
import {
  MENSAGEM_LOCALIZACAO_IMPRECISA, obterPosicao, traduzirErroGps, limitesDoCirculo,
} from './gps';
import { pontoDeBias, MENSAGEM_MORADA_SUGERIDA_INDISPONIVEL } from './morada';
import { criarCampoPesquisaMorada } from './pesquisaMorada';

export const TEXTO_TOCAR_NO_MAPA = 'Toque no mapa no sítio da loja.';
export const TEXTO_ARRASTAR = 'Arraste o pino para o sítio exato e confirme.';
export const TEXTO_CONFIRMADA = 'Localização confirmada.';
export const TEXTO_CONFIRMAR = 'Confirmar localização';
export const TEXTO_ALTERAR = 'Alterar localização';

// O zoom ao escolher uma morada: chega para se ver a rua e arrastar o pino até à porta da loja.
export const ZOOM_MORADA = 18;

export const TEXTO_ESTOU_NESTA_LOJA = 'Estou nesta loja';
export const TEXTO_A_OBTER_LOCALIZACAO = 'A obter a localização…';
export const TEXTO_A_PROCURAR_MORADA = 'A procurar a morada…';
const TEXTO_MORADA_SUGERIDA = 'Morada sugerida: ';
const SEPARADOR_ATRIBUICAO = ' · ';
// Depois do GPS, o mapa enquadra o círculo da precisão, mas nunca mais perto do que ao escolher uma morada.
export const ZOOM_GPS = ZOOM_MORADA;
const MARGEM_GPS = [24, 24];
// O círculo da precisão: o roxo do CRM (o mesmo da gota do pino, conferido pelo css.test.js), transparente;
// os toques passam para o mapa.
export const ESTILO_CIRCULO = Object.freeze({
  className: 'circulo-precisao',
  interactive: false,
  color: '#6b2fa3',
  weight: 2,
  opacity: 0.8,
  fillColor: '#6b2fa3',
  fillOpacity: 0.12,
});

// 44 px de área de toque; a ponta da gota (CSS) fica no ponto da loja.
const TAMANHO_PINO = 44;
const PONTA_PINO = [22, 38];

const numero = (valor) => typeof valor === 'number' && Number.isFinite(valor);

// Os textos de uma loja: o título, a dica antes de haver pino, o nome da área do mapa e o do pino (estes dois
// para os leitores de ecrã). Outro sítio (o ponto da fábrica, T2.30) passa os seus.
export const TEXTOS_LOJA = Object.freeze({
  titulo: 'Localização',
  tocar: TEXTO_TOCAR_NO_MAPA,
  mapa: 'Mapa para pôr o pino da loja',
  pino: 'Pino da loja',
});

export const textosSeletor = (textos = {}) => Object.freeze({ ...TEXTOS_LOJA, ...textos });

const parte = (texto, url = null) => Object.freeze({ texto, url });

// "Morada sugerida: <rótulo> · Powered by Geoapify": o rótulo é uma parte de texto e a atribuição sai só das
// constantes de atribuicoes.js (com a ligação), como no autónomo. O componente desenha cada parte como texto
// ou, com `url`, como uma ligação.
export const partesMoradaSugerida = (rotulo) => Object.freeze([
  parte(TEXTO_MORADA_SUGERIDA),
  parte(String(rotulo)),
  parte(SEPARADOR_ATRIBUICAO),
  ...ATRIBUICOES.pesquisa.partes.map((p) => parte(p.texto, p.url)),
]);

const MORADA_A_PROCURAR = Object.freeze({ tipo: null, partes: Object.freeze([parte(TEXTO_A_PROCURAR_MORADA)]) });
const MORADA_INDISPONIVEL = Object.freeze({
  tipo: 'erro',
  partes: Object.freeze([parte(MENSAGEM_MORADA_SUGERIDA_INDISPONIVEL)]),
});

// criarSeletor({L, documento, configuracao, textos?, api?, geolocation?, aoMudar?, aoEscolherMorada?,
//               aoSugerirMorada?, aoMudarVista?, aoFocar?})
//   → {vista, localizacao, mapa, pesquisa, iniciar, colocar, confirmar, alterar, estouNestaLoja, desconfirmar,
//      mostrarErro, limparErro, focar, redimensionar, destruir}
//  - configuracao: a do GET /api/crm/config (pode ser null ou inválida: o seletor diz que não há mapa);
//  - textos: {titulo?, tocar?, mapa?, pino?} (ver TEXTOS_LOJA);
//  - api: {pesquisarMorada, moradaInversa} do lib/crm/api.js; com ela, a pesquisa de morada e a morada
//    sugerida depois do GPS;
//  - geolocation: o navigator.geolocation do browser; com ele, "Estou nesta loja";
//  - aoMudar(localizacao): a localização confirmada mudou — {lat, lng, origem_coords, precisao_m}, ou null
//    quando deixa de haver (o pino voltou a soltar-se);
//  - aoEscolherMorada(sugestao): escolheram uma morada na pesquisa ({rotulo, morada, codigo_postal,
//    localidade, lat, lng}) e o pino já lá está;
//  - aoSugerirMorada(sugestao): a morada do ponto do GPS (a mesma forma), para os campos vazios;
//  - aoMudarVista(vista): a vista mudou (a mesma de `vista`);
//  - aoFocar('confirmar' | 'alterar'): o foco deve ir para esse botão (o que se carregou desaparece, ou o
//    passo seguinte é confirmar).
// vista: {estado, dica, aviso: 'imprecisa'|null, erro: texto|null, semMapa, confirmarAtivo,
//         gps: null | {texto, ocupado, mensagem: null | {texto, tipo: 'erro'}},
//         moradaSugerida: null | {tipo: null|'erro', partes: [{texto, url}]},
//         pesquisa: null | a vista do campo (pesquisaMorada.js)}
// Cada mudança traz um objeto novo, congelado. Sem mapa, a pesquisa e o GPS não aparecem (null).
export function criarSeletor({
  L, documento, configuracao, textos, api, geolocation, aoMudar, aoEscolherMorada, aoSugerirMorada, aoMudarVista,
  aoFocar,
}) {
  const rotulos = textosSeletor(textos);
  const temGps = typeof geolocation?.getCurrentPosition === 'function';
  const temInversa = typeof api?.moradaInversa === 'function';
  let criado = null; // o mapa de mapa.js
  let indisponivel = false;
  let marcador = null;
  let posicao = null; // {lat, lng, origem, precisao_m}: onde está o pino e de onde veio
  let arrastado = false;
  let confirmada = null;
  let estado = 'vazio';
  let erro = null;
  // Muda sempre que o pino muda de sítio: a posição do GPS que chega depois de outra mudança é ignorada.
  let versaoPino = 0;
  let aObterGps = false;
  let mensagemGps = null;
  let circulo = null; // o círculo da precisão do último GPS
  let moradaSugerida = null;
  // Cada morada sugerida pedida (e cada mudança do pino) muda a sequência: só conta a resposta mais recente.
  let pedidoMorada = 0;
  let vista = null;

  // A pesquisa de morada (com a api). As funções que chama (colocar, atualizar) são declarações: já existem.
  const pesquisa = typeof api?.pesquisarMorada === 'function'
    ? criarCampoPesquisaMorada({
      pesquisar: (texto, perto) => api.pesquisarMorada({ texto, ...(perto ?? {}) }),
      // As sugestões mais perto do sítio que o mapa mostra vêm primeiro.
      obterPerto() {
        try {
          return criado?.mapa.getCenter() ?? null;
        } catch {
          return null; // o Leaflet ainda sem vista
        }
      },
      aoEscolher(sugestao) {
        if (!colocar({ lat: sugestao.lat, lng: sugestao.lng, origem: 'geocoder' }, { zoom: ZOOM_MORADA })) return;
        aoEscolherMorada?.(sugestao);
        // O passo seguinte é arrastar e confirmar; no telemóvel, o teclado fecha e o mapa fica à vista.
        aoFocar?.('confirmar');
      },
      aoMudarVista: () => atualizar(),
    })
    : null;

  const confirmavel = () => posicao !== null
    && podeConfirmar({ origem: posicao.origem, precisao_m: posicao.precisao_m, arrastado });

  function montarVista() {
    const imprecisa = estado !== 'confirmado' && posicao !== null && !confirmavel();
    let dica;
    if (estado === 'confirmado') dica = TEXTO_CONFIRMADA;
    else if (posicao === null) dica = rotulos.tocar;
    else dica = imprecisa ? MENSAGEM_LOCALIZACAO_IMPRECISA : TEXTO_ARRASTAR;
    return Object.freeze({
      estado,
      dica,
      aviso: imprecisa ? 'imprecisa' : null,
      erro,
      semMapa: indisponivel,
      confirmarAtivo: estado !== 'confirmado' && !indisponivel && confirmavel(),
      // Sem mapa não há onde pôr o pino do GPS nem o da morada escolhida.
      gps: temGps && !indisponivel
        ? Object.freeze({
          texto: aObterGps ? TEXTO_A_OBTER_LOCALIZACAO : TEXTO_ESTOU_NESTA_LOJA,
          // aria-disabled (não disabled): o foco fica no botão enquanto o GPS responde.
          ocupado: aObterGps || !criado,
          mensagem: mensagemGps,
        })
        : null,
      moradaSugerida,
      pesquisa: pesquisa && !indisponivel ? pesquisa.vista : null,
    });
  }

  function atualizar() {
    vista = montarVista();
    aoMudarVista?.(vista);
  }

  // O pino foi para outro sítio: o círculo, a mensagem do GPS e a morada sugerida do ponto anterior saem.
  function esquecerGps() {
    circulo?.remove();
    circulo = null;
    pedidoMorada += 1;
    mensagemGps = null;
    moradaSugerida = null;
  }

  function definirConfirmada(valor) {
    if (valor === confirmada) return;
    confirmada = valor;
    aoMudar?.(confirmada);
  }

  // O pino solta-se (arrastável) e a localização deixa de estar confirmada.
  function soltar() {
    estado = 'por_confirmar';
    marcador?.dragging?.enable();
    atualizar();
    definirConfirmada(null);
  }

  function criarPino(latlng) {
    const novo = L.marker(latlng, {
      icon: L.divIcon({ className: 'pino-seletor', iconSize: [TAMANHO_PINO, TAMANHO_PINO], iconAnchor: PONTA_PINO }),
      draggable: true,
      autoPan: true,
      keyboard: true,
      title: rotulos.pino,
      zIndexOffset: 1000,
    });
    novo.on('dragend', () => {
      const { lat, lng } = novo.getLatLng();
      posicao = { ...posicao, lat, lng };
      arrastado = true;
      // O círculo e a morada sugerida ficam (ajustar o pino é o passo seguinte ao GPS); um GPS a caminho não.
      versaoPino += 1;
      atualizar();
    });
    // O arrasto do Leaflet (marker.dragging) só existe depois de o pino entrar no mapa.
    return novo.addTo(criado.mapa);
  }

  // Põe o pino na posição {lat, lng, origem, precisao_m?} (origem: 'pin_manual' | 'geocoder' | 'gps'), solto e
  // por confirmar. Com {zoom}, o mapa aproxima-se do pino. false se não há mapa ou a posição não é válida.
  function colocar(nova, { zoom } = {}) {
    if (!criado || !numero(nova?.lat) || !numero(nova?.lng)) return false;
    versaoPino += 1;
    esquecerGps();
    posicao = {
      lat: nova.lat,
      lng: nova.lng,
      origem: typeof nova.origem === 'string' ? nova.origem : 'pin_manual',
      precisao_m: numero(nova.precisao_m) ? nova.precisao_m : null,
    };
    arrastado = false;
    const latlng = [posicao.lat, posicao.lng];
    if (marcador) marcador.setLatLng(latlng);
    else marcador = criarPino(latlng);
    if (numero(zoom)) criado.mapa.setView(latlng, zoom);
    erro = null;
    soltar();
    return true;
  }

  // A morada do ponto do GPS (geocodificação inversa), só como sugestão.
  async function sugerirMorada(ponto) {
    if (!temInversa) return;
    pedidoMorada += 1;
    const minha = pedidoMorada;
    moradaSugerida = MORADA_A_PROCURAR;
    atualizar();
    let sugestao;
    try {
      // Sempre com o ponto do pontoDeBias (6 casas): o servidor recusa números com expoente.
      sugestao = await api.moradaInversa(pontoDeBias(ponto));
    } catch (falha) {
      if (minha !== pedidoMorada) return;
      // Fora de Portugal (422) não há morada a sugerir; o erro da localização aparece ao guardar.
      moradaSugerida = falha?.codigo === 'validacao' ? null : MORADA_INDISPONIVEL;
      atualizar();
      return;
    }
    if (minha !== pedidoMorada) return;
    if (typeof sugestao?.rotulo !== 'string' || sugestao.rotulo === '') {
      moradaSugerida = null;
      atualizar();
      return;
    }
    moradaSugerida = Object.freeze({ tipo: null, partes: partesMoradaSugerida(sugestao.rotulo) });
    atualizar();
    aoSugerirMorada?.(sugestao);
  }

  // O pino no ponto do GPS, com o círculo da precisão (se o browser a deu), e o mapa a mostrar o círculo.
  function colocarDoGps({ lat, lng, precisao_m }) {
    if (!colocar({ lat, lng, origem: 'gps', precisao_m })) return;
    const centro = [lat, lng];
    if (numero(precisao_m) && precisao_m > 0 && typeof L.circle === 'function') {
      circulo = L.circle(centro, { ...ESTILO_CIRCULO, radius: precisao_m }).addTo(criado.mapa);
    }
    const limites = limitesDoCirculo({ lat, lng }, precisao_m);
    if (limites) criado.mapa.fitBounds(limites, { maxZoom: ZOOM_GPS, padding: MARGEM_GPS });
    else criado.mapa.setView(centro, ZOOM_GPS);
    sugerirMorada({ lat, lng });
  }

  // "Estou nesta loja": um toque, um pedido ao GPS (só aqui, nunca ao montar).
  async function estouNestaLoja() {
    if (!temGps || aObterGps || !criado) return;
    aObterGps = true;
    const versao = versaoPino;
    mensagemGps = null;
    atualizar();
    let nova = null;
    let falha = null;
    try {
      nova = await obterPosicao(geolocation);
    } catch (e) {
      falha = e;
    }
    if (!criado) return; // saiu do ecrã
    aObterGps = false;
    atualizar();
    // A pessoa pôs o pino noutro sítio enquanto esperava: fica o que ela fez.
    if (versao !== versaoPino) return;
    if (falha) {
      mensagemGps = Object.freeze({
        texto: typeof falha.mensagem === 'string' ? falha.mensagem : traduzirErroGps(null).mensagem,
        tipo: 'erro',
      });
      atualizar();
      return;
    }
    colocarDoGps(nova);
  }

  function semMapa() {
    indisponivel = true;
    // Sem mapa não há onde pôr o pino da morada escolhida nem o do GPS.
    pesquisa?.cancelar();
    erro = MENSAGEM_SEM_MAPA;
    atualizar();
  }

  vista = montarVista();

  return {
    get vista() {
      return vista;
    },
    // A localização confirmada, como a API a recebe; null até confirmar.
    get localizacao() {
      return confirmada;
    },
    // O mapa de mapa.js ({mapa, …}; null antes de iniciar ou depois de destruir).
    get mapa() {
      return criado;
    },
    // O campo da pesquisa de morada (pesquisaMorada.js), ou null sem a api.
    get pesquisa() {
      return pesquisa;
    },
    // Cria o mapa no elemento (já na página: o Leaflet mede a área). false se não foi possível.
    // Com {inicial: {lat, lng, origem, precisao_m?}} (a ficha a corrigir a localização que a loja já tem, ou o
    // ponto da fábrica), o pino começa solto nesse sítio, à escala da rua; sem ela, o mapa mostra o centro das
    // definições.
    iniciar(elemento, { inicial } = {}) {
      if (criado) return true;
      if (indisponivel) return false;
      if (typeof L?.map !== 'function' || !configuracaoValida(configuracao)) {
        semMapa();
        return false;
      }
      try {
        criado = criarMapa({
          L,
          documento,
          elemento,
          configuracao,
          aoTocarNoMapa(ponto) {
            pesquisa?.fechar();
            if (ponto && estado !== 'confirmado') colocar({ ...ponto, origem: 'pin_manual' });
          },
        });
      } catch {
        criado = null;
        semMapa();
        return false;
      }
      if (!inicial || !colocar(inicial, { zoom: ZOOM_MORADA })) criado.enquadrar([]);
      atualizar();
      return true;
    },
    colocar,
    // "Confirmar localização": fixa o pino; o foco passa para "Alterar localização".
    confirmar() {
      if (estado === 'confirmado' || indisponivel || !confirmavel()) return;
      estado = 'confirmado';
      marcador?.dragging?.disable();
      atualizar();
      aoFocar?.('alterar');
      definirConfirmada(localizacaoFinal(posicao, arrastado));
    },
    // "Alterar localização": solta o pino outra vez; o foco volta a "Confirmar localização".
    alterar() {
      if (estado !== 'confirmado') return;
      soltar();
      aoFocar?.('confirmar');
    },
    estouNestaLoja,
    // A API recusou a localização (ex.: "Fora de Portugal"): o pino volta a soltar-se para a corrigir.
    desconfirmar() {
      if (estado === 'confirmado') soltar();
    },
    mostrarErro(texto) {
      erro = String(texto);
      atualizar();
    },
    // A mensagem do mapa que não carregou fica (sem mapa não há o que corrigir).
    limparErro() {
      if (erro === null || indisponivel) return;
      erro = null;
      atualizar();
    },
    // O foco no botão que se vê (ex.: ao lado do erro que a API devolveu).
    focar() {
      aoFocar?.(estado === 'confirmado' ? 'alterar' : 'confirmar');
    },
    // Depois de a área do mapa mudar de tamanho.
    redimensionar() {
      criado?.redimensionar();
    },
    destruir() {
      pesquisa?.cancelar();
      // O mapa sai com o pino e o círculo; o GPS e a morada sugerida que chegarem depois são ignorados.
      pedidoMorada += 1;
      criado?.destruir();
      criado = null;
      marcador = null;
      circulo = null;
    },
  };
}
