// O seletor da localização de uma loja (desenho original §6.2; plano T2.26),
// sem DOM: as regras do componente do CRM autónomo
// (public/assets/js/componentes/seletor-localizacao.js) fora do React, para
// terem testes (correção "T2.26 / T2.27 / T2.29 / T2.30 (componentes "Sem
// Jest")", na parte do seletor da T2.24a). O
// `components/crm/SeletorLocalizacao.js` só desenha a `vista` e liga os botões;
// a nova loja (T2.27), a ficha (T2.28, "Corrigir localização") e a fábrica
// (T2.30, sem GPS) usam esse componente. Sobre o Google Maps desde a G10 do
// plano do mapa Google (adenda §6.1 e §6.2).
//
// Um mapa da Google (o do `mapa.js`) onde se toca para pôr o pino, que se
// arrasta até ao sítio exato e se confirma com "Confirmar localização":
//  - o pino é um marcador avançado da Google com `gmpDraggable`: arrasta-se
//    enquanto está por confirmar e fica fixo depois de confirmado. O conteúdo
//    é a `div.pino-seletor` vazia, feita com o `el()` (a gota desenha-se no
//    `components/crm/crm.css`): nunca HTML nem texto;
//  - a regra do arrasto (adenda §2.1, decisão 2): um pino vindo da Google (o
//    negócio tocado no mapa ou a morada escolhida na pesquisa: a origem
//    `google`, que só existe aqui) só se confirma depois de a pessoa o arrastar
//    até à porta da loja, e vai como `pin_manual` com o `google_place_id` ao
//    lado (`localizacao.js`). Arrastar mantém o identificador do lugar; um
//    toque à mão no mapa, o GPS ou outro sítio sem identificador limpam-no.
//    Assim nenhuma coordenada da Google se grava tal e qual;
//  - com a `geolocation` (navigator.geolocation), "Estou nesta loja" (dossiê
//    §5.4). O GPS só se pede quando se toca no botão (nunca seguimento
//    contínuo); enquanto espera, o botão diz "A obter a localização…" e não
//    volta a pedir. A posição põe lá o pino (origem gps), solto, com um círculo
//    da Google do tamanho da precisão (os toques passam para o mapa), e o mapa
//    enquadra o círculo sem passar do zoom 18. Com a precisão pior que 50 m:
//    "Localização imprecisa — ajuste o pino", e só se confirma depois de
//    arrastar (fica pin_manual). Se o pino mudar de sítio por outra via (toque
//    no mapa, arrasto) antes de o GPS responder, a posição (ou o erro) que
//    chega depois é ignorada;
//  - com a `api`, a geocodificação inversa do ponto do GPS (GET
//    /api/crm/morada/inversa) mostra "Morada sugerida: … · Powered by Geoapify"
//    e entrega-a ao ecrã (`aoSugerirMorada`, que só preenche os campos vazios:
//    `camposSugeridos`). Só o GPS a pede (nunca para um ponto da Google). Se o
//    pino for posto noutro sítio, a morada sugerida sai (e a que chegar tarde é
//    ignorada);
//  - o negócio selecionado (G11; adenda §1.2 e §6.3): tocar no ícone de um
//    negócio do mapa abre o balão da própria Google (o código nunca o trava) e
//    o painel "Negócio selecionado" (`criarNegocioSelecionado` do
//    `lugarGoogle.js`, aqui dentro): o pino ainda não se move. Só quando a
//    pessoa toca em "Pôr o pino neste negócio" (ou a nova loja chega do mapa
//    com um negócio) se pede à Google a posição do lugar, e só ela; o pino vai
//    para lá com a origem `google` (a regra do arrasto). Se a Google falhar, o
//    pino vai para o ponto tocado (a reserva), com a mesma regra, e o painel
//    diz porquê. O nome e a morada do negócio nunca se pedem: escrevem-se à mão;
//  - a pesquisa da Google (G11): o elemento de pesquisa da própria Google
//    (`criarPesquisaLugar`), que o ecrã põe junto ao mapa (fora da caixa dele);
//    prefere a zona à vista (`limitesDoMapa`). Escolher uma morada põe lá o pino (origem
//    `google`, com o identificador do lugar), mostra "Morada sugerida: <a
//    morada da Google>" e entrega-a ao ecrã (`aoEscolherMorada`, para os campos
//    da morada). Nunca se pede a inversa da Geoapify para um ponto da Google;
//  - as escolhas que se cruzam (revisão do mapa Google, MAPA-G-4 / G-ENG-2):
//    um toque à mão, um arrasto, "Estou nesta loja", "Pôr o pino neste
//    negócio" e uma sugestão da pesquisa são escolhas do sítio do pino; o que
//    chegar depois de uma escolha mais recente (a posição do GPS, a de um
//    negócio, o lugar da pesquisa, ou a falha de um deles) é ignorado, e um
//    painel "A posicionar o pino…" cujo pedido deixou de contar fecha. Outro
//    negócio tocado ou o painel fechado também tiram a validade à posição de
//    um negócio a caminho;
//  - a Google que recusa a chave depois de o mapa abrir (o `gm_authFailure`,
//    que o componente ouve do carregador) → `mapaFalhou()`: fica como se a
//    Google não tivesse carregado (MENSAGEM_SEM_MAPA; sem pino, pesquisa,
//    painel nem GPS), e nada do que estava a caminho conta (MAPA-G-1).
//
// Estados: 'vazio' (sem pino) → 'por_confirmar' (pino solto, arrastável) →
// 'confirmado' (pino fixo; "Alterar localização" solta-o outra vez). Só a
// localização confirmada conta para guardar. A origem das coordenadas segue o
// `localizacao.js`: um pino arrastado passa a pin_manual.
//
// A Google e o documento são recebidos por parâmetro: o componente passa o
// `window.google` depois de carregar as bibliotecas do mapa e dos pinos; os
// testes passam os falsos de `testes/`. As posições da Google leem-se sempre
// pelo `pontoDe` do `mapa.js` (ora `LatLng`, ora literal).

import { ATRIBUICOES } from './atribuicoes';
import { el } from './dom';
import {
  criarMapa, configuracaoValida, pontoDe, limitarZoomDepoisDeEnquadrar, MENSAGEM_SEM_MAPA,
  MENSAGEM_MAPA_NAO_CONFIGURADO,
} from './mapa';
import { podeConfirmar, localizacaoFinal } from './localizacao';
import {
  MENSAGEM_LOCALIZACAO_IMPRECISA, obterPosicao, traduzirErroGps, limitesDoCirculo,
} from './gps';
import { pontoDeBias, MENSAGEM_MORADA_SUGERIDA_INDISPONIVEL } from './morada';
import {
  criarNegocioSelecionado, criarPesquisaLugar, posicaoDoLugar, TEXTO_ESCREVA_O_NOME, TEXTO_LUGAR_INDISPONIVEL,
} from './lugarGoogle';

export const TEXTO_TOCAR_NO_MAPA = 'Toque no mapa no sítio da loja.';
export const TEXTO_ARRASTAR = 'Arraste o pino para o sítio exato e confirme.';
// Um pino vindo da Google só se confirma depois de arrastado (a regra do arrasto).
export const TEXTO_ARRASTAR_LUGAR = 'Arraste o pino até à porta da loja para confirmar';
export const TEXTO_CONFIRMADA = 'Localização confirmada.';
export const TEXTO_CONFIRMAR = 'Confirmar localização';
export const TEXTO_ALTERAR = 'Alterar localização';

// O zoom ao pôr o pino numa morada ou num lugar: chega para se ver a rua e arrastar o pino até à porta da loja.
export const ZOOM_MORADA = 18;

export const TEXTO_ESTOU_NESTA_LOJA = 'Estou nesta loja';
export const TEXTO_A_OBTER_LOCALIZACAO = 'A obter a localização…';
export const TEXTO_A_PROCURAR_MORADA = 'A procurar a morada…';
const TEXTO_MORADA_SUGERIDA = 'Morada sugerida: ';
const SEPARADOR_ATRIBUICAO = ' · ';
// Depois do GPS, o mapa enquadra o círculo da precisão, mas nunca mais perto do que ao escolher uma morada.
export const ZOOM_GPS = ZOOM_MORADA;
// Folga (px) à volta do círculo da precisão no enquadramento.
export const MARGEM_GPS = 24;
// O círculo da precisão (google.maps.Circle): o roxo do CRM (o mesmo da gota do pino, conferido pelo
// css.test.js), transparente; não recebe toques (passam para o mapa).
export const ESTILO_CIRCULO = Object.freeze({
  strokeColor: '#6b2fa3',
  strokeOpacity: 0.8,
  strokeWeight: 2,
  fillColor: '#6b2fa3',
  fillOpacity: 0.12,
  clickable: false,
});

// O pino fica por cima de tudo o que o mapa desenhe.
const INDICE_PINO = 1000;

const numero = (valor) => typeof valor === 'number' && Number.isFinite(valor);
// Um identificador de lugar da Google só conta se for um texto com algo além de espaços (o formato não é documentado).
const idDeLugar = (valor) => typeof valor === 'string' && valor.trim() !== '';

// A Google com o que o seletor usa: o mapa (biblioteca `maps`) e o marcador avançado (biblioteca `marker`).
const temGoogle = (google) => typeof google?.maps?.Map === 'function'
  && typeof google.maps.marker?.AdvancedMarkerElement === 'function';

// O servidor não tem a chave do navegador ou o Map ID: o GET /api/crm/config trouxe `google: null`.
const naoConfigurado = (configuracao) => configuracao !== null && typeof configuracao === 'object'
  && configuracao.google === null;

// Os textos de uma loja: o título, a dica antes de haver pino, o nome da área do mapa e o do pino (estes dois
// para os leitores de ecrã), a dica da regra do arrasto, a mensagem de quando a Google não dá a posição de um
// lugar (o painel do negócio e a pesquisa) e a dica do painel do negócio (null: sem dica). Outro sítio (o ponto
// da fábrica, T2.30) passa os seus (revisão do mapa Google, MAPA-G-2: a fábrica não é uma loja nem tem nome).
export const TEXTOS_LOJA = Object.freeze({
  titulo: 'Localização',
  tocar: TEXTO_TOCAR_NO_MAPA,
  mapa: 'Mapa para pôr o pino da loja',
  pino: 'Pino da loja',
  arrastarLugar: TEXTO_ARRASTAR_LUGAR,
  lugarIndisponivel: TEXTO_LUGAR_INDISPONIVEL,
  dicaNegocio: TEXTO_ESCREVA_O_NOME,
});

export const textosSeletor = (textos = {}) => Object.freeze({ ...TEXTOS_LOJA, ...textos });

const parte = (texto, url = null) => Object.freeze({ texto, url });

// "Morada sugerida: <rótulo> · Powered by Geoapify" (a morada do ponto do GPS): o rótulo é uma parte de texto
// e a atribuição sai só das constantes de atribuicoes.js (com a ligação), como no autónomo. Com
// {fonte: 'google'} (a morada escolhida na pesquisa da Google), só "Morada sugerida: <rótulo>": a atribuição é
// a do próprio mapa da Google, ao lado. O componente desenha cada parte como texto ou, com `url`, como uma
// ligação.
export const partesMoradaSugerida = (rotulo, { fonte } = {}) => Object.freeze([
  parte(TEXTO_MORADA_SUGERIDA),
  parte(String(rotulo)),
  ...(fonte === 'google' ? [] : [
    parte(SEPARADOR_ATRIBUICAO),
    ...ATRIBUICOES.geoapify.partes.map((p) => parte(p.texto, p.url)),
  ]),
]);

const MORADA_A_PROCURAR = Object.freeze({ tipo: null, partes: Object.freeze([parte(TEXTO_A_PROCURAR_MORADA)]) });
const MORADA_INDISPONIVEL = Object.freeze({
  tipo: 'erro',
  partes: Object.freeze([parte(MENSAGEM_MORADA_SUGERIDA_INDISPONIVEL)]),
});

// criarSeletor({google, documento, configuracao, textos?, api?, geolocation?, aoMudar?, aoEscolherMorada?,
//               aoSugerirMorada?, aoMudarVista?, aoFocar?})
//   → {vista, localizacao, mapa, iniciar, colocar, confirmar, alterar, estouNestaLoja, desconfirmar,
//      mostrarErro, limparErro, focar, redimensionar, escolherNegocio, usarNegocio, fecharNegocio,
//      limitesDoMapa, mapaFalhou, destruir}
//  - google: o `window.google` com as bibliotecas `maps` e `marker` já carregadas (sem elas, o seletor diz
//    que não há mapa) e, para a pesquisa e o negócio selecionado, a `places` (sem ela, não há pesquisa);
//  - configuracao: a do GET /api/crm/config, {google: {chave, map_id} | null, centro} (pode ser null ou
//    inválida: o seletor diz que não há mapa; com `google: null`, que o mapa não está configurado);
//  - textos: {titulo?, tocar?, mapa?, pino?, arrastarLugar?, lugarIndisponivel?, dicaNegocio?} (ver TEXTOS_LOJA;
//    a `dicaNegocio` é do componente, que a põe no painel do negócio);
//  - api: {moradaInversa} do lib/crm/api.js; com ela, a morada sugerida depois do GPS;
//  - geolocation: o navigator.geolocation do browser; com ele, "Estou nesta loja";
//  - aoMudar(localizacao): a localização confirmada mudou — {lat, lng, origem_coords, precisao_m,
//    google_place_id}, ou null quando deixa de haver (o pino voltou a soltar-se);
//  - aoEscolherMorada(morada): escolheram uma morada na pesquisa da Google e o pino já lá está —
//    {rotulo, morada, codigo_postal, localidade, lat, lng} (a forma da morada sugerida, para os campos);
//  - aoSugerirMorada(sugestao): a morada do ponto do GPS ({rotulo, morada, codigo_postal, localidade, lat,
//    lng}), para os campos vazios;
//  - aoMudarVista(vista): a vista mudou (a mesma de `vista`);
//  - aoFocar('confirmar' | 'alterar'): o foco deve ir para esse botão (o que se carregou desaparece, ou o
//    passo seguinte é confirmar).
// vista: {estado, dica, aviso: 'imprecisa'|'arrastar'|null, erro: texto|null, semMapa, confirmarAtivo,
//         gps: null | {texto, ocupado, mensagem: null | {texto, tipo: 'erro'}},
//         moradaSugerida: null | {tipo: null|'erro', partes: [{texto, url}]},
//         pesquisa: {ativa, elemento} (o elemento de pesquisa da Google, que o ecrã põe na página; null e
//                   inativa sem mapa ou sem a biblioteca `places`),
//         negocio: a vista do painel do negócio selecionado ({placeId, reserva, estado, mensagem}, do
//                  `criarNegocioSelecionado`: nenhum dado da Google)}
// Cada mudança traz um objeto novo, congelado. Sem mapa, o GPS não aparece (null). Depois de `destruir`,
// nada muda nem avisa.
// Com a chave recusada pela Google (ex.: RefererNotAllowedMapError), tirar um pino ou um círculo do mapa lança
// dentro da biblioteca; isso nunca pode derrubar a página do CRM (visto em produção a 2026-10-22).
function tirarDoMapa(acao) {
  try {
    acao();
  } catch {
    // O mapa já não existe para a Google: não há nada para tirar.
  }
}

export function criarSeletor({
  google, documento, configuracao, textos, api, geolocation, aoMudar, aoEscolherMorada, aoSugerirMorada,
  aoMudarVista, aoFocar,
}) {
  const rotulos = textosSeletor(textos);
  const temGps = typeof geolocation?.getCurrentPosition === 'function';
  const temInversa = typeof api?.moradaInversa === 'function';
  let criado = null; // o mapa de mapa.js
  let indisponivel = false;
  let destruido = false;
  let marcador = null;
  // {lat, lng, origem, precisao_m, google_place_id}: onde está o pino, de onde veio e de que lugar da Google.
  let posicao = null;
  let arrastado = false;
  let confirmada = null;
  let estado = 'vazio';
  let erro = null;
  // Muda sempre que o pino muda de sítio e sempre que começa outra escolha do sítio dele (o GPS, a pesquisa, um
  // negócio): a posição do GPS e o lugar da pesquisa que chegam depois de outra mudança são ignorados.
  let versaoPino = 0;
  let aObterGps = false;
  let mensagemGps = null;
  let circulo = null; // o círculo da precisão do último GPS
  let moradaSugerida = null;
  // Cada morada sugerida pedida (e cada mudança do pino) muda a sequência: só conta a resposta mais recente.
  let pedidoMorada = 0;
  let pesquisa = null; // a pesquisa da Google ({elemento, destruir}), criada com o mapa
  // Cada escolha de negócio, cada fecho do painel e cada mudança do pino mudam a sequência: a posição de um
  // negócio que chegue depois já não conta.
  let pedidoNegocio = 0;
  let posicionando = null; // {placeId, promessa}: o usarNegocio a decorrer
  let vista = null;
  // O painel do negócio selecionado; avisa o seletor, que junta a vista dele à sua.
  const painel = criarNegocioSelecionado({ aoMudarVista: () => atualizar() });

  const confirmavel = () => posicao !== null
    && podeConfirmar({ origem: posicao.origem, precisao_m: posicao.precisao_m, arrastado });

  function montarVista() {
    // Falta arrastar: um pino da Google ou um GPS impreciso ainda por arrastar.
    const faltaArrastar = estado !== 'confirmado' && posicao !== null && !confirmavel();
    let dica = TEXTO_ARRASTAR;
    let aviso = null;
    if (estado === 'confirmado') dica = TEXTO_CONFIRMADA;
    else if (posicao === null) dica = rotulos.tocar;
    else if (faltaArrastar && posicao.origem === 'google') {
      dica = rotulos.arrastarLugar;
      aviso = 'arrastar';
    } else if (faltaArrastar) {
      dica = MENSAGEM_LOCALIZACAO_IMPRECISA;
      aviso = 'imprecisa';
    }
    return Object.freeze({
      estado,
      dica,
      aviso,
      erro,
      semMapa: indisponivel,
      confirmarAtivo: estado !== 'confirmado' && !indisponivel && confirmavel(),
      // Sem mapa não há onde pôr o pino do GPS.
      gps: temGps && !indisponivel
        ? Object.freeze({
          texto: aObterGps ? TEXTO_A_OBTER_LOCALIZACAO : TEXTO_ESTOU_NESTA_LOJA,
          // aria-disabled (não disabled): o foco fica no botão enquanto o GPS responde.
          ocupado: aObterGps || !criado,
          mensagem: mensagemGps,
        })
        : null,
      moradaSugerida,
      // A pesquisa nasce com o mapa (iniciar) e sai com ele (destruir).
      pesquisa: Object.freeze({ ativa: Boolean(pesquisa?.elemento), elemento: pesquisa?.elemento ?? null }),
      negocio: painel.vista,
    });
  }

  function atualizar() {
    if (destruido) return;
    vista = montarVista();
    aoMudarVista?.(vista);
  }

  // O pino foi para outro sítio: o círculo, a mensagem do GPS e a morada sugerida do ponto anterior saem.
  function esquecerGps() {
    tirarDoMapa(() => circulo?.setMap(null));
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

  // Começou outra escolha do sítio do pino (um arrasto, o GPS, a pesquisa): o que estiver a caminho de uma
  // escolha anterior já não conta — a posição do GPS e o lugar da pesquisa (`versaoPino`) e a de um negócio
  // (`pedidoNegocio`, e o painel que estava "A posicionar o pino…" fecha). Devolve a versão desta escolha.
  function novaEscolha() {
    versaoPino += 1;
    pedidoNegocio += 1;
    if (painel.vista.estado === 'a_posicionar') painel.fechar();
    return versaoPino;
  }

  // O pino solta-se (arrastável) e a localização deixa de estar confirmada.
  function soltar() {
    estado = 'por_confirmar';
    if (marcador) marcador.gmpDraggable = true;
    atualizar();
    definirConfirmada(null);
  }

  function criarPino(ponto) {
    const novo = new google.maps.marker.AdvancedMarkerElement({
      map: criado.mapa,
      position: ponto,
      content: el(documento, 'div', { classe: 'pino-seletor' }),
      gmpDraggable: true,
      title: rotulos.pino,
      zIndex: INDICE_PINO,
    });
    // A Google move o pino; a posição nova lê-se do próprio marcador (LatLng ou literal).
    novo.addListener('dragend', () => {
      const arrastadoPara = pontoDe(novo.position);
      if (arrastadoPara === null) return;
      posicao = { ...posicao, lat: arrastadoPara.lat, lng: arrastadoPara.lng };
      arrastado = true;
      // O círculo e a morada sugerida ficam (ajustar o pino é o passo seguinte ao GPS); um GPS, uma posição de
      // negócio ou um lugar da pesquisa a caminho não (o arrasto da pessoa é a escolha mais recente).
      novaEscolha();
      atualizar();
    });
    return novo;
  }

  // Põe o pino na posição {lat, lng, origem, precisao_m?, google_place_id?} (origem: 'pin_manual' | 'gps' |
  // 'geocoder' | 'google'), solto e por confirmar; o `google_place_id` é o dessa posição (sem ele, null: o de um
  // pino anterior nunca passa para o novo). Com {zoom}, o mapa mostra o pino nesse zoom. false se não há mapa
  // ou a posição não é válida. Não mexe no painel do negócio (o `colocar` público fecha-o).
  function porPino(nova, { zoom } = {}) {
    if (!criado || !numero(nova?.lat) || !numero(nova?.lng)) return false;
    versaoPino += 1;
    pedidoNegocio += 1;
    esquecerGps();
    posicao = {
      lat: nova.lat,
      lng: nova.lng,
      origem: typeof nova.origem === 'string' ? nova.origem : 'pin_manual',
      precisao_m: numero(nova.precisao_m) ? nova.precisao_m : null,
      // O localizacao.js só o envia se for um texto não vazio (senão vai null).
      google_place_id: nova.google_place_id,
    };
    arrastado = false;
    const ponto = { lat: posicao.lat, lng: posicao.lng };
    if (marcador) marcador.position = ponto;
    else marcador = criarPino(ponto);
    if (numero(zoom)) criado.centrarEm(ponto, zoom);
    erro = null;
    soltar();
    return true;
  }

  // O pino noutro sítio por outra via (um toque à mão, o GPS, a pesquisa, o ecrã): o painel do negócio fecha
  // (e uma posição do negócio a caminho já não conta).
  function colocar(nova, opcoes) {
    if (!porPino(nova, opcoes)) return false;
    painel.fechar();
    return true;
  }

  // --- O negócio selecionado ---

  // Tocaram num negócio do mapa (o balão da Google abre sozinho): o painel abre, o pino fica onde está.
  function escolherNegocio(placeId, { reserva } = {}) {
    if (!criado || !idDeLugar(placeId)) return;
    pedidoNegocio += 1;
    painel.abrir(placeId, { reserva });
  }

  // "Pôr o pino neste negócio" (ou a nova loja que chega do mapa com um negócio): pede à Google só a posição
  // do lugar e põe lá o pino (origem google, por arrastar); se a Google falhar, põe-no na reserva (o ponto
  // tocado), com a mesma regra, e o painel diz porquê; sem reserva, só a mensagem. Devolve uma promessa que
  // nunca rejeita: true se o pino foi para a posição do lugar. Dois toques seguidos na ação fazem um só pedido.
  function usarNegocio(placeId = painel.vista.placeId, { reserva = painel.vista.reserva } = {}) {
    if (!criado || !idDeLugar(placeId)) return Promise.resolve(false);
    // O painel só fica "a posicionar" enquanto o pedido dele é o que vale (qualquer outra escolha muda-o).
    if (painel.vista.estado === 'a_posicionar' && posicionando?.placeId === placeId) return posicionando.promessa;
    // Outra escolha: o GPS e o lugar da pesquisa a caminho deixam de contar.
    versaoPino += 1;
    pedidoNegocio += 1;
    const meu = pedidoNegocio;
    painel.abrir(placeId, { reserva });
    painel.aPosicionar();
    const promessa = posicaoDoLugar(google, placeId).then(
      (lugar) => {
        if (meu !== pedidoNegocio) return false;
        // O colocar fecha o painel.
        colocar({ lat: lugar.lat, lng: lugar.lng, origem: 'google', google_place_id: placeId }, { zoom: ZOOM_MORADA });
        return true;
      },
      () => {
        if (meu !== pedidoNegocio) return false;
        const ponto = painel.vista.reserva;
        if (ponto) porPino({ ...ponto, origem: 'google', google_place_id: placeId }, { zoom: ZOOM_MORADA });
        painel.falhou(rotulos.lugarIndisponivel);
        return false;
      },
    );
    posicionando = { placeId, promessa };
    return promessa;
  }

  // "Fechar": o painel fecha e o pino fica (uma posição a caminho já não conta).
  function fecharNegocio() {
    pedidoNegocio += 1;
    painel.fechar();
  }

  // --- A pesquisa da Google ---

  // Os limites do mapa à vista (as sugestões da pesquisa preferem esta zona), ou null sem mapa (ou antes de a
  // Google os ter).
  function limitesDoMapa() {
    return criado?.mapa.getBounds() ?? null;
  }

  // Escolheram uma morada na pesquisa: o pino vai para lá (origem google, com o identificador do lugar), a
  // morada da Google aparece como sugerida e o ecrã recebe-a (sem nunca pedir a inversa da Geoapify).
  // A morada chega do `lugarDaPesquisa` ({rotulo, morada, codigo_postal, localidade}, cada um texto ou null) e
  // passa ao ecrã campo a campo: nada mais do lugar sai daqui.
  function aoEscolherNaPesquisa({ id, lat, lng, morada: daGoogle }) {
    if (!colocar({ lat, lng, origem: 'google', google_place_id: id }, { zoom: ZOOM_MORADA })) return;
    if (daGoogle.rotulo) {
      moradaSugerida = Object.freeze({ tipo: null, partes: partesMoradaSugerida(daGoogle.rotulo, { fonte: 'google' }) });
      atualizar();
    }
    aoEscolherMorada?.({
      rotulo: daGoogle.rotulo,
      morada: daGoogle.morada,
      codigo_postal: daGoogle.codigo_postal,
      localidade: daGoogle.localidade,
      lat,
      lng,
    });
  }

  // A Google não deu o lugar escolhido (ou não conseguiu sugerir): o pino fica e o erro diz porquê.
  function aoFalharNaPesquisa() {
    erro = rotulos.lugarIndisponivel;
    atualizar();
  }

  // Escolheram uma sugestão (o lugar ainda vem a caminho): é outra escolha, e a resposta só vale se o pino não
  // tiver mudado entretanto (um toque à mão, um arrasto, o GPS, um negócio).
  function aoComecarNaPesquisa() {
    const versao = novaEscolha();
    return () => versao === versaoPino;
  }

  function criarPesquisa() {
    try {
      return criarPesquisaLugar({
        google,
        documento,
        aoEscolher: aoEscolherNaPesquisa,
        aoFalhar: aoFalharNaPesquisa,
        obterLimites: limitesDoMapa,
        aoComecar: aoComecarNaPesquisa,
      });
    } catch {
      return null; // a Google recusou o elemento: o mapa fica, sem pesquisa
    }
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
    const centro = { lat, lng };
    if (numero(precisao_m) && precisao_m > 0) {
      circulo = new google.maps.Circle({ ...ESTILO_CIRCULO, center: centro, radius: precisao_m, map: criado.mapa });
    }
    const limites = limitesDoCirculo(centro, precisao_m);
    if (limites) {
      const [[sul, oeste], [norte, este]] = limites;
      criado.mapa.fitBounds(new google.maps.LatLngBounds({ lat: sul, lng: oeste }, { lat: norte, lng: este }), MARGEM_GPS);
      // O fitBounds da Google não tem zoom máximo: um círculo pequeno não leva o mapa além do zoom 18.
      limitarZoomDepoisDeEnquadrar(google, criado.mapa, ZOOM_GPS);
    } else {
      criado.centrarEm(centro, ZOOM_GPS);
    }
    sugerirMorada(centro);
  }

  // "Estou nesta loja": um toque, um pedido ao GPS (só aqui, nunca ao montar).
  async function estouNestaLoja() {
    if (!temGps || aObterGps || !criado) return;
    aObterGps = true;
    // Outra escolha: uma posição de negócio ou um lugar da pesquisa a caminho deixam de contar.
    const versao = novaEscolha();
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

  function semMapa(mensagem) {
    indisponivel = true;
    erro = mensagem;
    atualizar();
  }

  // A Google recusou a chave (o `gm_authFailure`, com o mapa já criado ou antes disso): o pino, o círculo, a
  // pesquisa, o painel e o mapa saem, o que estava a caminho deixa de contar, a localização confirmada deixa
  // de existir e o seletor fica sem mapa, com a mensagem de quando a Google não carrega.
  function mapaFalhou() {
    if (destruido || indisponivel) return;
    versaoPino += 1;
    pedidoNegocio += 1;
    pedidoMorada += 1;
    pesquisa?.destruir();
    pesquisa = null;
    if (marcador) tirarDoMapa(() => { marcador.map = null; });
    marcador = null;
    tirarDoMapa(() => circulo?.setMap(null));
    circulo = null;
    criado?.destruir();
    criado = null;
    posicao = null;
    arrastado = false;
    estado = 'vazio';
    aObterGps = false;
    mensagemGps = null;
    moradaSugerida = null;
    painel.fechar();
    semMapa(MENSAGEM_SEM_MAPA);
    definirConfirmada(null);
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
    // Cria o mapa no elemento (já na página). false se não foi possível.
    // Com {inicial: {lat, lng, origem, precisao_m?, google_place_id?}} (a ficha a corrigir a localização que a
    // loja já tem, ou o ponto da fábrica), o pino começa solto nesse sítio, à escala da rua; sem ela, o mapa
    // mostra o centro das definições.
    iniciar(elemento, { inicial } = {}) {
      if (destruido) return false;
      if (criado) return true;
      if (indisponivel) return false;
      if (naoConfigurado(configuracao)) {
        semMapa(MENSAGEM_MAPA_NAO_CONFIGURADO);
        return false;
      }
      if (!temGoogle(google) || !configuracaoValida(configuracao)) {
        semMapa(MENSAGEM_SEM_MAPA);
        return false;
      }
      try {
        criado = criarMapa({
          google,
          documento,
          elemento,
          configuracao,
          // Um toque à mão põe o pino sem lugar da Google (o de antes sai) e fecha o painel do negócio.
          aoTocarNoMapa(ponto) {
            if (ponto && estado !== 'confirmado') colocar({ ...ponto, origem: 'pin_manual' });
          },
          // Um toque no ícone de um negócio: o painel abre (com o ponto tocado como reserva); confirmado, o pino
          // fica fixo e o painel não abre (o balão da Google abre na mesma).
          aoTocarNumLugar({ placeId, lat, lng }) {
            if (estado !== 'confirmado') escolherNegocio(placeId, { reserva: { lat, lng } });
          },
        });
      } catch {
        criado = null;
        semMapa(MENSAGEM_SEM_MAPA);
        return false;
      }
      pesquisa = criarPesquisa();
      if (inicial) colocar(inicial, { zoom: ZOOM_MORADA });
      atualizar();
      return true;
    },
    colocar,
    // "Confirmar localização": fixa o pino (deixa de se arrastar); o foco passa para "Alterar localização".
    confirmar() {
      if (destruido || estado === 'confirmado' || indisponivel || !confirmavel()) return;
      estado = 'confirmado';
      if (marcador) marcador.gmpDraggable = false;
      atualizar();
      aoFocar?.('alterar');
      definirConfirmada(localizacaoFinal(posicao, arrastado));
    },
    // "Alterar localização": solta o pino outra vez; o foco volta a "Confirmar localização".
    alterar() {
      if (destruido || estado !== 'confirmado') return;
      soltar();
      aoFocar?.('confirmar');
    },
    estouNestaLoja,
    // A API recusou a localização (ex.: "Fora de Portugal"): o pino volta a soltar-se para a corrigir.
    desconfirmar() {
      if (!destruido && estado === 'confirmado') soltar();
    },
    mostrarErro(texto) {
      if (destruido) return;
      erro = String(texto);
      atualizar();
    },
    // A mensagem do mapa que não carregou fica (sem mapa não há o que corrigir).
    limparErro() {
      if (destruido || erro === null || indisponivel) return;
      erro = null;
      atualizar();
    },
    // O foco no botão que se vê (ex.: ao lado do erro que a API devolveu).
    focar() {
      if (destruido) return;
      aoFocar?.(estado === 'confirmado' ? 'alterar' : 'confirmar');
    },
    // Depois de a área do mapa mudar de tamanho.
    redimensionar() {
      criado?.redimensionar();
    },
    escolherNegocio,
    usarNegocio,
    fecharNegocio,
    limitesDoMapa,
    mapaFalhou,
    // O pino e o círculo saem do mapa, a pesquisa sai da página e o mapa é destruído; o GPS, a morada
    // sugerida, a posição de um negócio e a escolha da pesquisa que chegarem depois são ignorados, e nada mais
    // muda nem avisa. Uma segunda chamada já não encontra nada para tirar.
    destruir() {
      destruido = true;
      pedidoMorada += 1;
      pedidoNegocio += 1;
      pesquisa?.destruir();
      if (marcador) tirarDoMapa(() => { marcador.map = null; });
      tirarDoMapa(() => circulo?.setMap(null));
      criado?.destruir();
      criado = null;
      marcador = null;
      circulo = null;
    },
  };
}
