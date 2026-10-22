// A página "Rotas" (plano F3 T3.37; desenho original §7.1, "Escolher o dia … Se já existir rota, abre-a"),
// sem DOM. Molde do `criarAdicionarARota` (T3.34): uma `vista` congelada a cada mudança, entregue ao
// `aoMudarVista`; o `pages/crm/CrmRotas.js` só a desenha.
//
//  - `iniciar()` pede a lista das rotas (`listarRotas()` sem intervalo: o servidor usa hoje − 14 e
//    hoje + 60). O "hoje" é sempre o do servidor (o fuso do browser pode não ser o de Lisboa).
//  - As linhas dividem-se em "Próximas" (de hoje em diante, a mais perto primeiro) e "Anteriores" (a mais
//    recente primeiro), uma por dia: o dia (`rotuloDia`), o estado efetivo (`rotuloEstado`: uma rota de
//    um dia que passou é "Concluída") e as paragens ativas — "seg 12/10 · Planeada · 9 paragens" —, cada
//    uma ligada ao planeador desse dia.
//  - O campo da data e "Abrir" levam a qualquer dia que exista: também do passado (o planeador mostra-o só
//    de leitura) e até hoje + 365, o horizonte do servidor (depois dele, a mensagem do servidor). O campo
//    começa com o dia de hoje quando a lista chega, se a pessoa ainda não escreveu nada.
//  - "Hoje" leva à rota de hoje (`vista.hoje.caminho`, só com o hoje do servidor). As linhas e "Hoje" são
//    ligações (`<Link to>`); só o "Abrir" do campo navega pelo `navegar`.
//  - A falha mostra a mensagem (`textoDoErro`) e "Tentar novamente"; a rede que volta pede outra vez a
//    lista que falhou.
// Os dados ficam como texto: o React escreve-os como texto. Os caminhos são do portal (`<casa>/rotas/<dia>`,
// com o dia já validado pelo `eDataValida`), não links de fora.
import { MENSAGEM_ERRO_INESPERADO } from './api';
import { MAXIMO_DIAS_FUTURO, TEXTO_FALTA_DIA, textoParagens } from './adicionarARota';
import { eDataValida, rotuloDia, somarDias } from './datas';
import { textoDoErro } from './ecraMapa';
import { rotuloEstado } from './rota';

export const TITULO_ROTAS = 'Rotas';
export const TEXTO_ABRIR = 'Abrir';
export const TEXTO_HOJE = 'Hoje';
export const TITULO_PROXIMAS = 'Próximas';
export const TITULO_ANTERIORES = 'Anteriores';
export const TEXTO_SEM_PROXIMAS = 'Não há rotas marcadas.';
export const TEXTO_SEM_ANTERIORES = 'Não houve rotas.';
// A do servidor depois do horizonte (`validador_rota.MENSAGEM_HORIZONTE`; o teste lê-a).
export const MENSAGEM_HORIZONTE = 'Escolha um dia até um ano a partir de hoje.';

const SEPARADOR = ' · ';

function congelarAFundo(valor) {
  if (valor !== null && typeof valor === 'object') {
    Object.values(valor).forEach(congelarAFundo);
    Object.freeze(valor);
  }
  return valor;
}

const caminhoDoDia = (base, data) => `${base}/rotas/${data}`;

// --- Funções puras -------------------------------------------------------------------------------

// A linha de uma rota do `GET /rotas`: {data, caminho, dia, estado, paragens, texto, eHoje}, ou null (uma
// linha estragada, um dia que não existe, ou sem um hoje válido). O estado e as paragens que não se sabem
// ler ficam de fora do texto.
export function linhaDaRota(rota, { hoje, base } = {}) {
  if (!eDataValida(rota?.data) || !eDataValida(hoje)) return null;
  const dia = rotuloDia(rota.data, hoje);
  const estado = rotuloEstado(rota.estado_efetivo);
  const paragens = textoParagens(rota.paragens);
  return {
    data: rota.data,
    caminho: caminhoDoDia(base, rota.data),
    dia,
    estado,
    paragens,
    texto: [dia, estado, paragens].filter((parte) => parte !== null).join(SEPARADOR),
    eHoje: rota.data === hoje,
  };
}

// {proximas, anteriores}: as linhas de hoje em diante pela data, e as de antes de hoje da mais recente para
// a mais antiga; uma por dia (a primeira que vier), sem as estragadas.
export function listasDasRotas(lista, base) {
  const hoje = lista?.hoje;
  const rotas = Array.isArray(lista?.rotas) ? lista.rotas : [];
  const porDia = new Map();
  for (const rota of rotas) {
    const linha = linhaDaRota(rota, { hoje, base });
    if (linha !== null && !porDia.has(linha.data)) porDia.set(linha.data, linha);
  }
  const linhas = [...porDia.values()].sort((a, b) => (a.data < b.data ? -1 : 1));
  return {
    proximas: linhas.filter((linha) => linha.data >= hoje),
    anteriores: linhas.filter((linha) => linha.data < hoje).reverse(),
  };
}

// O dia a meio de uma frase: "hoje", "amanhã", "qua 09/12"; null sem dias válidos.
function diaNaFrase(data, hoje) {
  const rotulo = rotuloDia(data, hoje);
  if (rotulo === 'Hoje' || rotulo === 'Amanhã') return rotulo.toLowerCase();
  return rotulo;
}

// "Não há rotas até qua 09/12." (o fim da lista), senão o texto geral.
export function textoSemProximas(ate, hoje) {
  const dia = diaNaFrase(ate, hoje);
  return dia === null ? TEXTO_SEM_PROXIMAS : `Não há rotas até ${dia}.`;
}

// "Não houve rotas desde sáb 26/09." (o início da lista), senão o texto geral.
export function textoSemAnteriores(de, hoje) {
  const dia = diaNaFrase(de, hoje);
  return dia === null ? TEXTO_SEM_ANTERIORES : `Não houve rotas desde ${dia}.`;
}

// "Rotas de sáb 26/09 a qua 09/12. Para outro dia, escolha-o acima.", ou null.
export function notaDoIntervalo(lista) {
  const de = diaNaFrase(lista?.de, lista?.hoje);
  const ate = diaNaFrase(lista?.ate, lista?.hoje);
  if (de === null || ate === null) return null;
  return `Rotas de ${de} a ${ate}. Para outro dia, escolha-o acima.`;
}

// O botão "Abrir": {ativo, texto, falta}. Um dia que existe abre (também do passado); com o hoje do
// servidor, só até hoje + 365.
export function estadoAbrir({ data, hoje } = {}) {
  const desativado = (falta) => ({ ativo: false, texto: TEXTO_ABRIR, falta });
  if (!eDataValida(data)) return desativado(TEXTO_FALTA_DIA);
  const limite = somarDias(hoje, MAXIMO_DIAS_FUTURO); // null sem o hoje do servidor
  if (limite !== null && data > limite) return desativado(MENSAGEM_HORIZONTE);
  return { ativo: true, texto: TEXTO_ABRIR, falta: null };
}

// --- Ecrã ----------------------------------------------------------------------------------------

// criarListaRotas({api, rede, base, navegar, aoMudarVista})
//   → {vista, iniciar, tentarDeNovo, mudarDia, abrir, destruir}
//  - api: {listarRotas} do lib/crm/api.js; rede: o `criarEstadoRede(window, navigator)` (sem ele, não se
//    ouve a rede);
//  - base: a casa do CRM (`/crm` ou `/admin/crm`); navegar(caminho): o `navigate` do React Router.
// vista: {estado: 'a_carregar'|'falha'|'pronto', titulo, falha: null | {mensagem, aTentar}, data, max,
//         abrir: {ativo, texto, falta}, hoje: {ativo, texto, caminho},
//         proximas: null | {titulo, linhas: [linha], vazia}, anteriores: (igual), nota}
//   — nova a cada mudança e congelada a fundo; as listas e a nota só com a lista carregada.
// Criar não pede nada: `iniciar()` pede a lista e ouve a rede; `destruir()` (a página saiu) faz que as
// respostas que chegarem depois e a rede já não façam nada.
export function criarListaRotas({
  api, rede, base, navegar, aoMudarVista,
}) {
  let lista = null; // a resposta do `GET /rotas` (só com um hoje válido)
  let falha = null; // a mensagem, se a lista não carregou
  let aCarregar = false;
  let data = '';
  let dataMexida = false; // a pessoa já escreveu no campo (o dia de hoje não o substitui)
  let iniciado = false;
  let ativo = true;
  let cancelarRede = () => {};

  const hoje = () => (lista === null ? null : lista.hoje);

  function grupo(titulo, linhas, vazia) {
    return { titulo, linhas, vazia: linhas.length === 0 ? vazia : null };
  }

  function montarVista() {
    let estado = 'a_carregar';
    if (lista !== null) estado = 'pronto';
    else if (falha !== null) estado = 'falha';
    const listas = lista === null ? null : listasDasRotas(lista, base);
    const diaHoje = hoje();
    return congelarAFundo({
      estado,
      titulo: TITULO_ROTAS,
      falha: estado === 'falha' ? { mensagem: falha, aTentar: aCarregar } : null,
      data,
      // Sem o hoje do servidor, o `somarDias` dá null.
      max: somarDias(diaHoje, MAXIMO_DIAS_FUTURO),
      abrir: estadoAbrir({ data, hoje: diaHoje }),
      hoje: {
        ativo: diaHoje !== null,
        texto: TEXTO_HOJE,
        caminho: diaHoje === null ? null : caminhoDoDia(base, diaHoje),
      },
      proximas: listas === null ? null
        : grupo(TITULO_PROXIMAS, listas.proximas, textoSemProximas(lista.ate, diaHoje)),
      anteriores: listas === null ? null
        : grupo(TITULO_ANTERIORES, listas.anteriores, textoSemAnteriores(lista.de, diaHoje)),
      nota: notaDoIntervalo(lista),
    });
  }

  let vista = montarVista();

  function atualizar() {
    vista = montarVista();
    aoMudarVista?.(vista);
  }

  async function carregar() {
    if (!ativo || aCarregar || lista !== null) return;
    aCarregar = true;
    atualizar();
    let resposta;
    try {
      resposta = await api.listarRotas();
    } catch (erro) {
      aCarregar = false;
      if (!ativo) return;
      falha = textoDoErro(erro);
      atualizar();
      return;
    }
    aCarregar = false;
    if (!ativo) return;
    if (eDataValida(resposta?.hoje)) {
      lista = resposta;
      if (!dataMexida) data = resposta.hoje;
    } else {
      falha = MENSAGEM_ERRO_INESPERADO;
    }
    atualizar();
  }

  return {
    get vista() {
      return vista;
    },
    iniciar() {
      if (!ativo || iniciado) return;
      iniciado = true;
      cancelarRede = rede?.aoMudar((ligado) => {
        // Quando a rede volta, a lista que falhou pede-se outra vez (o `carregar` não pede a que já chegou nem a
        // que está a chegar).
        if (ligado) carregar();
      }) ?? (() => {});
      carregar();
    },
    // "Tentar novamente" (a lista não carregou); um toque, um pedido.
    tentarDeNovo() {
      if (falha !== null) carregar();
    },
    // O valor do `<input type="date">` ('' quando está vazio).
    mudarDia(valor) {
      if (!ativo || typeof valor !== 'string') return;
      data = valor;
      dataMexida = true;
      atualizar();
    },
    abrir() {
      if (!ativo || !estadoAbrir({ data, hoje: hoje() }).ativo) return;
      navegar?.(caminhoDoDia(base, data));
    },
    destruir() {
      ativo = false;
      cancelarRede();
    },
  };
}
