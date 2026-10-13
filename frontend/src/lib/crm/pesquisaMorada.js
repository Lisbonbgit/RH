// O campo "Pesquisar morada" do seletor da localização (desenho original §6.2;
// plano T2.26), sem DOM: as regras do componente do CRM autónomo
// (public/assets/js/componentes/pesquisa-morada.js) fora do React, para terem
// testes. O `components/crm/PesquisaMorada.js` só desenha a `vista` e passa-lhe
// o que a pessoa escreve (`escrever`), as teclas (`tecla`) e a sugestão em que
// tocou (`escolher`).
//
//  - Autocompletar só de Portugal (o servidor pede à Geoapify, GET
//    /api/crm/morada/pesquisa), 300 ms depois da última tecla, com 3 ou mais
//    caracteres; uma resposta antiga nunca substitui uma mais recente
//    (`criarPesquisaMorada` de `morada.js`). O ponto de onde se pesquisa (o
//    centro do mapa) só ordena as sugestões.
//  - "Powered by Geoapify" fica sempre à vista por baixo do campo (desenho
//    original §9): é do componente, com as `partes` de `atribuicoes.js`.
//  - A lista fica por baixo do campo, no fluxo da página: não tapa o mapa nem
//    a atribuição dos mosaicos. Enquanto chega a lista nova, fica a anterior.
//  - Falha (503 ou sem rede): "Pesquisa de morada indisponível — coloque o pino
//    no mapa ou use 'Estou nesta loja'". O resto do ecrã continua a funcionar,
//    e escrever outra vez volta a tentar.
//  - Teclado (combobox): setas para a sugestão ativa, Enter escolhe, Escape
//    fecha. O Enter nunca submete um formulário à volta (`tecla` devolve `true`
//    quando o componente tem de fazer `preventDefault`).
// As sugestões ficam com o rótulo tal e qual: o React mostra-o como texto.

import { criarPesquisaMorada, pontoDeBias } from './morada';

export const TEXTO_PESQUISAR_MORADA = 'Pesquisar morada';
export const TEXTO_SUGESTOES = 'Sugestões de morada';
export const TEXTO_A_PESQUISAR = 'A pesquisar…';
export const TEXTO_SEM_RESULTADOS = 'Nenhuma morada encontrada — escreva de outra forma ou toque no mapa.';

// O limite do servidor (TEXTO_MAXIMO de backend/crm/morada.py): um texto maior daria 422.
export const TEXTO_MAXIMO = 200;

// Uma sugestão que se pode mostrar e escolher: com rótulo e coordenadas.
export const sugestaoValida = (sugestao) => typeof sugestao?.rotulo === 'string' && sugestao.rotulo !== ''
  && Number.isFinite(sugestao.lat) && Number.isFinite(sugestao.lng);

const congelar = (vista) => Object.freeze({ ...vista, sugestoes: Object.freeze([...vista.sugestoes]) });

// criarCampoPesquisaMorada({pesquisar, obterPerto?, aoEscolher?, aoMudarVista?})
//   → {vista, escrever, tecla, escolher, fechar, cancelar}
//  - pesquisar(texto, perto): Promise com a lista [{rotulo, morada, codigo_postal, localidade, lat, lng}]
//    (GET /api/crm/morada/pesquisa); perto = {lat, lng} (6 casas, do `pontoDeBias`) ou null;
//  - obterPerto(): o ponto de onde se pesquisa (ex.: o centro do mapa), ou null;
//  - aoEscolher(sugestao): a pessoa escolheu uma sugestão;
//  - aoMudarVista(vista): a vista mudou (a mesma de `vista`).
// vista: {texto, estado: 'vazio'|'a_pesquisar'|'resultados'|'erro'|'escolhida', mensagem, sugestoes, aberta,
//         ativa (o índice da sugestão ativa, -1 sem nenhuma)}. Cada mudança traz um objeto novo, congelado.
export function criarCampoPesquisaMorada({ pesquisar, obterPerto, aoEscolher, aoMudarVista }) {
  let vista = congelar({ texto: '', estado: 'vazio', mensagem: '', sugestoes: [], aberta: false, ativa: -1 });

  function mudar(alteracoes) {
    const nova = { ...vista, ...alteracoes };
    // Lista fechada, nenhuma sugestão ativa (as setas voltam a começar do princípio).
    if (!nova.aberta) nova.ativa = -1;
    vista = congelar(nova);
    aoMudarVista?.(vista);
  }

  // Uma lista nova começa sem sugestão ativa; aberta só se tiver sugestões.
  const comSugestoes = (sugestoes) => ({ sugestoes, aberta: sugestoes.length > 0, ativa: -1 });

  function aoMudarEstado(novo) {
    if (novo.estado === 'a_pesquisar') {
      // A lista anterior fica até chegar a nova (sem saltos no ecrã).
      mudar({ estado: 'a_pesquisar', mensagem: TEXTO_A_PESQUISAR });
    } else if (novo.estado === 'resultados') {
      const sugestoes = novo.sugestoes.filter(sugestaoValida);
      mudar({ ...comSugestoes(sugestoes), estado: 'resultados', mensagem: sugestoes.length > 0 ? '' : TEXTO_SEM_RESULTADOS });
    } else {
      // 'vazio' (menos de 3 caracteres) ou 'erro' (com a mensagem do desenho).
      mudar({ ...comSugestoes([]), estado: novo.estado, mensagem: novo.estado === 'erro' ? novo.mensagem : '' });
    }
  }

  const pesquisa = criarPesquisaMorada({ api: pesquisar, aoMudarEstado });

  function escolher(indice) {
    if (!Number.isInteger(indice) || indice < 0 || indice >= vista.sugestoes.length) return;
    const sugestao = vista.sugestoes[indice];
    pesquisa.cancelar();
    mudar({ ...comSugestoes([]), texto: sugestao.rotulo, estado: 'escolhida', mensagem: '' });
    aoEscolher?.(sugestao);
  }

  return {
    get vista() {
      return vista;
    },
    // A pessoa escreveu no campo (o valor todo).
    escrever(valor) {
      const texto = String(valor ?? '');
      mudar({ texto });
      pesquisa.escrever(texto, pontoDeBias(obterPerto?.()));
    },
    // Uma tecla no campo. true: o componente faz preventDefault (a tecla foi do campo).
    tecla(tecla) {
      const total = vista.sugestoes.length;
      if (tecla === 'ArrowDown' || tecla === 'ArrowUp') {
        if (total === 0) return false;
        const { ativa } = vista;
        const seguinte = tecla === 'ArrowDown' ? (ativa + 1) % total : (ativa <= 0 ? total - 1 : ativa - 1);
        // Com a lista fechada, a seta volta a abri-la (as sugestões continuam lá).
        mudar({ aberta: true, ativa: seguinte });
        return true;
      }
      if (tecla === 'Enter') {
        // Sem isto, o Enter submeteria o formulário onde o campo estiver (ex.: a ficha).
        if (vista.aberta && vista.ativa >= 0) escolher(vista.ativa);
        return true;
      }
      if (tecla === 'Escape' && vista.aberta) {
        mudar({ aberta: false });
        return true;
      }
      return false;
    },
    escolher,
    // Fecha a lista (ex.: tocaram no mapa); as sugestões voltam com a seta para baixo.
    fechar() {
      if (vista.aberta) mudar({ aberta: false });
    },
    // Descarta a pesquisa agendada e a que está a decorrer, e tira a lista e a mensagem.
    cancelar() {
      pesquisa.cancelar();
      mudar({ ...comSugestoes([]), estado: 'vazio', mensagem: '' });
    },
  };
}
