// "A minha localização" nos mapas do CRM (desenho de 2026-11-06; dossiê §5.4), sem React: as regras do botão fora
// do componente, para terem testes. O `components/crm/BotaoMinhaLocalizacao.js` só desenha a `vista` e liga isto ao
// ciclo de vida. O GPS (`geolocation`) e o documento entram por parâmetro.
//
// Três estados: 'desligado' → 'a_procurar' (o toque) → 'ligado' (a primeira leitura).
//  - Nada corre antes do toque: nem GPS nem ouvintes. A escolha não fica lembrada: cada visita ao mapa começa
//    desligada.
//  - Um só seguimento de cada vez. Um toque enquanto procura não faz nada.
//  - A primeira leitura mostra o ponto e centra o mapa, uma vez (`ZOOM_MINHA_POSICAO`). As seguintes só movem o
//    ponto: o mapa não persegue a pessoa, que pode olhar para outras zonas. Tocar com o ponto ligado volta a
//    centrar, sem mudar o zoom que a pessoa escolheu.
//  - Os erros: a autorização recusada desliga, tira o ponto e diz como autorizar (também se a pessoa a tirar a meio:
//    o GPS não volta e um ponto parado enganava). Sem posição à primeira, desliga e pede para tentar de novo. Outra
//    falha depois de já haver ponto não diz nada: o ponto fica onde estava e a leitura seguinte atualiza-o (o browser
//    pode dar "tempo esgotado" a cada 20 s com o telemóvel parado).
//  - Com a página escondida (o ecrã bloqueado, outra aplicação) o GPS para; ao voltar a estar visível, recomeça
//    sozinho, porque alguns telemóveis param o seguimento e não o retomam. O ponto fica e a primeira leitura depois
//    disso conta como as seguintes: não mexe no mapa.
//  - O mapa pode ainda não estar pronto ou ser recriado (`usarMapa`): a posição guarda-se aqui e desenha-se no mapa
//    que chegar; o centro que ficou por fazer faz-se aí. A página dá a primeira vista a esse mapa logo a seguir (os
//    efeitos dos filhos correm primeiro) ou só quando as lojas chegam: `aoCentrar` avisa-a, para não desfazer o centro.
//  - `destruir()` para o GPS e tira o ponto; o que chegar depois não conta.
//
// A posição não sai do telemóvel para o portal: vai só para o mapa. Este ficheiro e o componente nunca falam com o
// servidor nem gravam nada no browser (o minhaLocalizacao.test.js lê-os para o provar).
import { seguirPosicao } from './gps';
import { ZOOM_MINHA_POSICAO } from './mapa';

export const TEXTO_MINHA_LOCALIZACAO = 'A minha localização';
export const TEXTO_A_PROCURAR = 'A procurar…';

const vista = (estado, texto, rotulo) => Object.freeze({
  estado,
  ligado: estado === 'ligado',
  aProcurar: estado === 'a_procurar',
  texto,
  rotulo,
});

const VISTAS = Object.freeze({
  desligado: vista('desligado', TEXTO_MINHA_LOCALIZACAO, TEXTO_MINHA_LOCALIZACAO),
  a_procurar: vista('a_procurar', TEXTO_A_PROCURAR, `${TEXTO_MINHA_LOCALIZACAO}: a procurar…`),
  ligado: vista('ligado', TEXTO_MINHA_LOCALIZACAO, TEXTO_MINHA_LOCALIZACAO),
});

export const VISTA_INICIAL = VISTAS.desligado;

// criarMinhaLocalizacao({geolocation, documento, aoMudarVista?, aoAvisar?, aoCentrar?}) → {tocar, usarMapa, destruir}
//  - geolocation: o navigator.geolocation do browser (sem ele, o toque avisa e fica desligado);
//  - documento: o `document` (o `hidden` e o `visibilitychange`);
//  - aoMudarVista(vista): {estado, ligado, aProcurar, texto, rotulo}, só quando o estado muda (as leituras não voltam
//    a desenhar o botão);
//  - aoAvisar(mensagem): um erro para mostrar à pessoa, já em texto;
//  - aoCentrar(mapa): o mapa que acabou de ser centrado na pessoa (o mapa, nunca a posição).
export function criarMinhaLocalizacao({ geolocation, documento, aoMudarVista, aoAvisar, aoCentrar }) {
  let estado = 'desligado';
  let mapa = null; // o do `criarMapa`, quando está pronto
  let posicao = null; // a última leitura boa
  let porCentrar = null; // 'primeira' (com zoom), 'toque' (sem zoom) ou null
  let pararGps = null;
  let seguimento = 0; // só conta o que responde ao seguimento em curso
  let destruido = false;

  function mudarEstado(novo) {
    if (novo === estado) return;
    estado = novo;
    if (!destruido) aoMudarVista?.(VISTAS[novo]);
  }

  function desenhar() {
    if (mapa === null || posicao === null) return;
    mapa.mostrarMinhaPosicao(posicao);
    if (porCentrar === null) return;
    mapa.centrarEm(posicao, porCentrar === 'primeira' ? ZOOM_MINHA_POSICAO : undefined);
    porCentrar = null;
    aoCentrar?.(mapa);
  }

  function tirarPonto() {
    if (posicao !== null) mapa?.mostrarMinhaPosicao(null);
  }

  function pararSeguimento() {
    seguimento += 1;
    const parar = pararGps;
    pararGps = null;
    parar?.();
  }

  function seguir() {
    pararSeguimento();
    const meu = seguimento;
    const parar = seguirPosicao(geolocation, {
      aoMudar(leitura) {
        if (meu !== seguimento) return;
        posicao = leitura;
        mudarEstado('ligado');
        desenhar();
      },
      aoFalhar(falha) {
        if (meu !== seguimento) return;
        if (falha.codigo !== 'permissao_negada' && posicao !== null) return;
        desligar();
        aoAvisar?.(falha.mensagem);
      },
    });
    // Sem GPS, a falha chega antes de haver com que parar: um seguimento que já não conta não fica pendurado.
    if (meu === seguimento) pararGps = parar;
    else parar();
  }

  function aoMudarVisibilidade() {
    pararSeguimento();
    if (!documento.hidden) seguir();
  }

  function desligar() {
    documento.removeEventListener('visibilitychange', aoMudarVisibilidade);
    pararSeguimento();
    tirarPonto();
    posicao = null;
    porCentrar = null;
    mudarEstado('desligado');
  }

  return {
    // O toque no botão: liga, ou, com o ponto ligado, volta a centrar.
    tocar() {
      if (destruido || estado === 'a_procurar') return;
      if (estado === 'ligado') {
        porCentrar = porCentrar ?? 'toque';
        desenhar();
        return;
      }
      porCentrar = 'primeira';
      mudarEstado('a_procurar');
      documento.addEventListener('visibilitychange', aoMudarVisibilidade);
      seguir();
    },
    // O mapa em que se desenha: o do `criarMapa`, ou null enquanto não há.
    usarMapa(novo) {
      if (destruido || novo === mapa) return;
      tirarPonto();
      mapa = novo ?? null;
      desenhar();
    },
    // Ao sair do ecrã. Uma segunda chamada não faz nada.
    destruir() {
      if (destruido) return;
      destruido = true;
      desligar();
      mapa = null;
    },
  };
}
