// Definições › Fábrica (desenho original §6.7; plano T2.30), sem DOM: a morada
// da fábrica e o ponto no mapa (GET e PATCH /api/crm/definicoes, só o admin).
// O ponto é o centro do mapa enquanto não há lojas (o `centro` do GET
// /api/crm/config), e o início das rotas na F3. Porta de
// public/assets/js/componentes/definicoes-fabrica.js do CRM autónomo (a parte
// da fábrica da T2.24a); como a ficha da T2.28, o que o autónomo escrevia no
// DOM é uma `vista` congelada, entregue ao `aoMudarVista`, e o
// `pages/crm/DefinicoesFabrica.js` só a desenha (correção "T2.26 / T2.27 /
// T2.29 / T2.30 (componentes Sem Jest)").
//
//  - "Mudar o ponto no mapa" abre o seletor das lojas (`SeletorLocalizacao`,
//    sobre o mapa Google), com o pino solto no ponto atual e a pesquisa da
//    Google, mas sem o GPS ("Estou nesta loja" é para as lojas). Escolher uma
//    morada na pesquisa põe lá o pino e escreve a morada da Google na morada
//    da fábrica (sem a morada formatada, não escreve nada); "Cancelar a
//    mudança do ponto" desfaz as duas coisas (não a morada que a pessoa
//    escreveu depois). Um pino vindo da Google (a pesquisa, ou um negócio
//    tocado no mapa) só se confirma depois de arrastado (a regra do arrasto,
//    no seletor), e da localização confirmada só contam a latitude e a
//    longitude: a fábrica nunca guarda o `google_place_id` nem a origem
//    (plano do mapa Google, G17).
//  - Guardar envia só o que mudou: a morada, e o ponto inteiro (latitude e
//    longitude, com as 6 casas com que se guardam; o servidor recusa uma sem a
//    outra). Um ponto fora de Portugal continental (422) mostra o erro no mapa
//    e solta o pino outra vez. Enquanto grava, a morada e o ponto ficam
//    desativados (a resposta volta a preenchê-los). "Dados da fábrica
//    guardados." é um aviso (toast, `aoAvisar`).
//  - Sem as definições não há formulário: a mensagem e "Tentar novamente";
//    quando a rede volta, pedem-se outra vez.
// O autónomo avisava o mapa da app do centro novo (`aoMudarCentro`); no portal
// cada página do mapa pede o `/config` ao abrir, e o centro novo vem de lá.
// Os dados ficam como texto: o React escreve-os como texto.
import { MENSAGEM_ERRO_INESPERADO } from './api';
import { textoDoErro } from './ecraMapa';

export const TITULO_FABRICA = 'Fábrica';
export const TEXTO_DESCRICAO_FABRICA = 'A morada e o ponto da fábrica no mapa.';
export const TEXTO_A_CARREGAR_FABRICA = 'A carregar os dados da fábrica…';
export const TEXTO_FABRICA_GUARDADA = 'Dados da fábrica guardados.';
export const TEXTO_MORADA_FABRICA = 'Morada da fábrica';
export const TEXTO_PONTO_NO_MAPA = 'Ponto no mapa';
export const TEXTO_AJUDA_PONTO = 'O mapa abre aqui enquanto não houver lojas.';
export const TEXTO_MUDAR_PONTO = 'Mudar o ponto no mapa';
export const TEXTO_CANCELAR_MUDANCA = 'Cancelar a mudança do ponto';
export const TEXTO_GUARDAR = 'Guardar';
export const TEXTO_A_GUARDAR = 'A guardar…';
const TEXTO_FALTA_CONFIRMAR = 'Para guardar, confirme o ponto no mapa ou cancele a mudança.';
const TEXTO_FALTA_ALTERACOES = 'Sem alterações por guardar.';

// O tamanho da morada no servidor (`backend/crm/dominio/definicoes.py::MORADA_MAXIMO`).
export const MORADA_MAXIMO_FABRICA = 255;

// Os textos do seletor do ponto (os `textos` do `SeletorLocalizacao`, no lugar dos da loja): todos, para nenhum
// falar da loja (revisão do mapa Google, MAPA-G-2). O painel do negócio não tem a dica do nome: a fábrica não
// tem nome a escrever (adenda §1.2: aqui a pesquisa e o negócio servem só para pôr o pino).
export const TEXTOS_SELETOR_FABRICA = Object.freeze({
  titulo: 'Ponto da fábrica no mapa',
  tocar: 'Toque no mapa no sítio da fábrica.',
  mapa: 'Mapa para pôr o pino da fábrica',
  pino: 'Pino da fábrica',
  arrastarLugar: 'Arraste o pino até ao sítio exato da fábrica para confirmar',
  lugarIndisponivel: 'Não foi possível obter a posição deste lugar — toque no mapa no sítio da fábrica.',
  dicaNegocio: null,
});

const CAMPOS_PONTO = Object.freeze(['fabrica_lat', 'fabrica_lng']);

const numero = (valor) => typeof valor === 'number' && Number.isFinite(valor);
const textoComConteudo = (valor) => typeof valor === 'string' && valor !== '';

// As 6 casas decimais com que as coordenadas se guardam (o "%.6f" de `dominio/definicoes.py`).
const seisCasas = (valor) => Number(valor.toFixed(6));

const definicoesValidas = (d) => typeof d?.fabrica_morada === 'string' && numero(d.fabrica_lat) && numero(d.fabrica_lng);

// --- Funções puras -------------------------------------------------------------------------------

// O corpo do PATCH /api/crm/definicoes: só o que mudou. A morada sem espaços nas pontas; o ponto inteiro (o
// servidor recusa a latitude sem a longitude), e só se mudar nas 6 casas com que se guarda. Do ponto só se leem
// a latitude e a longitude (a origem e o `google_place_id` do seletor nunca vão).
export function corpoFabrica(original, { morada, ponto }) {
  const corpo = {};
  const texto = typeof morada === 'string' ? morada.trim() : '';
  if (texto !== (original.fabrica_morada ?? '').trim()) corpo.fabrica_morada = texto;
  if (numero(ponto?.lat) && numero(ponto?.lng)) {
    const lat = seisCasas(ponto.lat);
    const lng = seisCasas(ponto.lng);
    if (lat !== seisCasas(original.fabrica_lat) || lng !== seisCasas(original.fabrica_lng)) {
      corpo.fabrica_lat = lat;
      corpo.fabrica_lng = lng;
    }
  }
  return corpo;
}

// O botão Guardar: {ativo, texto, falta} (falta: porque não se pode guardar, ou null).
export function estadoGuardarFabrica({ alterada, aCorrigir, aGuardar }) {
  if (aGuardar) return { ativo: false, texto: TEXTO_A_GUARDAR, falta: null };
  const desativado = (falta) => ({ ativo: false, texto: TEXTO_GUARDAR, falta });
  if (aCorrigir) return desativado(TEXTO_FALTA_CONFIRMAR);
  if (!alterada) return desativado(TEXTO_FALTA_ALTERACOES);
  return { ativo: true, texto: TEXTO_GUARDAR, falta: null };
}

// 'Latitude 38.722300 · longitude -9.139300'
export function textoPonto(definicoes) {
  return `Latitude ${definicoes.fabrica_lat.toFixed(6)} · longitude ${definicoes.fabrica_lng.toFixed(6)}`;
}

// --- Ecrã ----------------------------------------------------------------------------------------

// criarFabrica({api, rede, seletor, aoMudarVista, aoAvisar, aoFocar})
//   → {vista, iniciar, tentarDeNovo, mudarMorada, abrirCorrecao, cancelarCorrecao, mudarPonto, escolherMorada,
//      guardar, destruir}
//  - api: {obterDefinicoes, alterarDefinicoes} do lib/crm/api.js; rede: o `criarEstadoRede(window, navigator)`;
//  - seletor: {limparErro, desconfirmar, mostrarErro, focar} do SeletorLocalizacao do ponto (pela ref);
//  - aoAvisar(texto): "Dados da fábrica guardados." (um toast); aoFocar(alvo): 'morada' (o campo, com o erro
//    do 422) ou 'mudar' (o botão "Mudar o ponto no mapa", ao cancelar ou com o erro do ponto).
// vista: {estado: 'a_carregar'|'falha'|'pronto', falha: null | {mensagem, aTentar}, morada, erroMorada,
//         resumoPonto, erroPonto, correcao: null | {chave, inicial: {lat, lng, origem: 'pin_manual'}},
//         camposDesativados, alerta, guardar: {ativo, texto, falta}}
//   — nova a cada mudança e congelada. `correcao.chave` muda a cada abertura (a `key` do seletor: o `inicial`
//   só se lê ao criá-lo).
// Criar não pede nada: `iniciar()` pede as definições e ouve a rede; `destruir()` (o ecrã saiu) faz que as
// respostas que chegarem depois e a rede já não façam nada.
export function criarFabrica({
  api, rede, seletor, aoMudarVista, aoAvisar, aoFocar,
}) {
  let original = null; // as definições como o servidor as tem
  let falha = null; // a mensagem, se não carregaram
  let aCarregar = false;
  let aGuardar = false;
  let morada = '';
  let erroMorada = null;
  let erroPonto = null;
  let alerta = null;
  // A mudança do ponto em curso: {chave, ponto (o confirmado, ou null), moradaAntes, moradaPosta}.
  let correcao = null;
  let chaveCorrecao = 0;
  let iniciado = false;
  let ativo = true;
  let cancelarRede = () => {};

  const corpoAtual = () => corpoFabrica(original, { morada, ponto: correcao?.ponto ?? null });

  function estadoAtual() {
    return estadoGuardarFabrica({
      alterada: original !== null && Object.keys(corpoAtual()).length > 0,
      aCorrigir: correcao !== null && correcao.ponto === null,
      aGuardar,
    });
  }

  function vistaDaCorrecao() {
    if (correcao === null || original === null) return null;
    return Object.freeze({
      chave: correcao.chave,
      inicial: Object.freeze({ lat: original.fabrica_lat, lng: original.fabrica_lng, origem: 'pin_manual' }),
    });
  }

  function montarVista() {
    let estado = 'a_carregar';
    if (original !== null) estado = 'pronto';
    else if (falha !== null) estado = 'falha';
    return Object.freeze({
      estado,
      falha: estado === 'falha' ? Object.freeze({ mensagem: falha, aTentar: aCarregar }) : null,
      morada,
      erroMorada,
      resumoPonto: original === null ? null : textoPonto(original),
      erroPonto,
      correcao: vistaDaCorrecao(),
      camposDesativados: aGuardar,
      alerta,
      guardar: Object.freeze(estadoAtual()),
    });
  }

  let vista = montarVista();

  function atualizar() {
    vista = montarVista();
    aoMudarVista?.(vista);
  }

  // Fecha a mudança do ponto (o seletor sai da página). Com `repor`, a morada que a pesquisa lá escreveu
  // volta à de antes (se a pessoa não a mudou depois).
  function fecharCorrecao({ repor = false } = {}) {
    if (correcao === null) return;
    const { moradaAntes, moradaPosta } = correcao;
    correcao = null;
    if (repor && moradaPosta !== null && morada === moradaPosta) morada = moradaAntes;
  }

  function aplicar(definicoes) {
    original = definicoes;
    falha = null;
    fecharCorrecao();
    morada = definicoes.fabrica_morada;
  }

  // --- Carregar ---

  async function carregar() {
    if (!ativo || aCarregar || original !== null) return;
    aCarregar = true;
    atualizar();
    let definicoes;
    try {
      definicoes = await api.obterDefinicoes();
    } catch (erro) {
      aCarregar = false;
      if (!ativo) return;
      falha = textoDoErro(erro);
      atualizar();
      return;
    }
    aCarregar = false;
    if (!ativo) return;
    if (definicoesValidas(definicoes)) aplicar(definicoes);
    else falha = MENSAGEM_ERRO_INESPERADO;
    atualizar();
  }

  // --- Guardar ---

  function limparMensagens() {
    alerta = null;
    erroMorada = null;
    erroPonto = null;
    if (correcao !== null) seletor?.limparErro?.();
  }

  function mostrarErro(erro) {
    if (erro?.codigo === 'validacao') {
      const daMorada = erro.campos?.fabrica_morada;
      const doPonto = CAMPOS_PONTO.map((campo) => erro.campos?.[campo]).find(textoComConteudo);
      if (textoComConteudo(doPonto)) {
        if (correcao !== null) {
          // O pino volta a soltar-se para a pessoa o pôr noutro sítio e confirmar outra vez.
          seletor?.desconfirmar?.();
          seletor?.mostrarErro?.(doPonto);
        } else {
          erroPonto = doPonto;
        }
      }
      if (textoComConteudo(daMorada)) erroMorada = daMorada;
      if (textoComConteudo(daMorada) || textoComConteudo(doPonto)) {
        atualizar();
        if (textoComConteudo(daMorada)) aoFocar?.('morada');
        else if (correcao !== null) seletor?.focar?.();
        else aoFocar?.('mudar');
        return;
      }
    }
    alerta = textoDoErro(erro);
    atualizar();
  }

  async function guardar() {
    if (!ativo || original === null || !estadoAtual().ativo) return;
    const corpo = corpoAtual();
    aGuardar = true;
    limparMensagens();
    atualizar();
    let definicoes;
    try {
      definicoes = await api.alterarDefinicoes(corpo);
    } catch (erro) {
      if (!ativo) return;
      aGuardar = false;
      mostrarErro(erro);
      return;
    }
    if (!ativo) return;
    aGuardar = false;
    // Uma resposta que não são as definições: fica o que se tinha (Guardar volta a poder-se usar).
    if (definicoesValidas(definicoes)) aplicar(definicoes);
    atualizar();
    aoAvisar?.(TEXTO_FABRICA_GUARDADA);
  }

  return {
    get vista() {
      return vista;
    },
    iniciar() {
      if (!ativo || iniciado) return;
      iniciado = true;
      cancelarRede = rede?.aoMudar((ligado) => {
        if (ativo && ligado) carregar();
      }) ?? (() => {});
      carregar();
    },
    // "Tentar novamente" (as definições não carregaram); um toque, um pedido.
    tentarDeNovo() {
      if (falha !== null) carregar();
    },
    mudarMorada(valor) {
      if (!ativo || original === null || aGuardar || typeof valor !== 'string') return;
      morada = valor;
      erroMorada = null;
      atualizar();
    },
    // "Mudar o ponto no mapa": o seletor abre com o pino solto no ponto atual.
    abrirCorrecao() {
      if (!ativo || correcao !== null || original === null || aGuardar) return;
      chaveCorrecao += 1;
      correcao = { chave: chaveCorrecao, ponto: null, moradaAntes: morada, moradaPosta: null };
      erroPonto = null;
      atualizar();
    },
    // "Cancelar a mudança do ponto": o foco volta a "Mudar o ponto no mapa".
    cancelarCorrecao() {
      if (!ativo || correcao === null || aGuardar) return;
      fecharCorrecao({ repor: true });
      atualizar();
      aoFocar?.('mudar');
    },
    // O ponto confirmado no seletor ({lat, lng, origem_coords, precisao_m, google_place_id}), ou null. Para o
    // corpo só contam a latitude e a longitude (`corpoFabrica`).
    mudarPonto(valor) {
      const ponto = valor ?? null;
      if (!ativo || correcao === null || ponto === correcao.ponto) return;
      correcao = { ...correcao, ponto };
      atualizar();
    },
    // A morada escolhida na pesquisa da Google do seletor (o pino já lá está): o rótulo (a morada formatada)
    // vai para a morada da fábrica; sem ele, nada muda.
    escolherMorada(sugestao) {
      if (!ativo || correcao === null || aGuardar || !textoComConteudo(sugestao?.rotulo)) return;
      morada = sugestao.rotulo;
      erroMorada = null;
      correcao = { ...correcao, moradaPosta: sugestao.rotulo };
      atualizar();
    },
    guardar,
    destruir() {
      if (!ativo) return;
      ativo = false;
      cancelarRede();
      vista = montarVista();
    },
  };
}
