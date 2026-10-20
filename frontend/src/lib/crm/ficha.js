// O ecrã "Ficha da loja" (desenho original §6.3; plano T2.28), sem DOM. Porta
// de public/assets/js/ecras/loja.js do CRM autónomo: as funções puras tal e
// qual, e o ecrã como a nova loja da T2.27 — o que o autónomo escrevia no DOM é
// uma `vista` congelada, entregue ao `aoMudarVista`, e o
// `pages/crm/CrmLoja.js` só a desenha (correção "T2.28 (Ficha da loja — fase
// num toque)").
//
//  - O formulário é o da nova loja (`formularioLoja.js`), já preenchido com o
//    GET /api/crm/lojas/{id}, mais o Instagram e o site (2026-10-13), o
//    horário de receção (2 janelas) e os dias fechada.
//  - A fase muda com um toque: escolher uma pastilha grava logo só a fase
//    (PATCH {fase, atualizado_em}), sem Guardar, e avisa "Fase guardada". O
//    resto da ficha fica como está (o que se mudou noutros campos, antes ou
//    durante o pedido, continua por guardar). Um pedido de cada vez: um toque
//    durante o pedido grava-se a seguir, com a versão nova, e fica a última
//    fase escolhida (com um só aviso, o dela). Sem rede (ou se falhar) a fase
//    escolhida fica por guardar e grava-se com o Guardar; com o conflito não se
//    grava por cima da outra pessoa; voltar à fase guardada não grava nada.
//  - Guardar envia só o que mudou (`diferencas.js`: a localização vai em
//    bloco) + o `atualizado_em` da loja em vigor (a do GET, a do último PATCH
//    da fase ou do Guardar). Fica desativado sem alterações, sem nome, com a
//    correção da localização por confirmar, com o conflito e sem rede.
//    Enquanto grava, os campos ficam desativados (a resposta volta a
//    preenchê-los: o que se escrevesse perdia-se). Com sucesso, a ficha fica
//    com a loja devolvida e avisa "Alterações guardadas".
//  - 409 conflito (outra pessoa alterou a loja entretanto) → a faixa "Alterado
//    por outra pessoa — recarregar", com o foco no Recarregar (pede a loja
//    outra vez; o que se tinha mudado perde-se, para não apagar o da outra).
//  - "Corrigir localização" abre o seletor (com a pesquisa de morada e "Estou
//    nesta loja") com o pino no sítio guardado, solto. "Cancelar correção"
//    fecha-o e desfaz a morada que a pesquisa ou o GPS lá puseram. Um 409
//    duplicado mostra o diálogo da nova loja ("Já existe X aqui — é a
//    mesma?"); um 422 da localização volta a soltar o pino, com o erro junto ao
//    mapa.
//  - Apagar pede confirmação ("Apagar esta loja? Use só para enganos — …") e,
//    apagada, volta ao mapa da mesma casa com o aviso "Loja apagada" no
//    `state` (o mapa mostra-o num toast). Uma loja com histórico não se apaga
//    (409 `loja_com_historico`): fica a mensagem do servidor.
//  - Sem a loja não há ficha: a mensagem e "Tentar novamente" (ou, se não
//    existe, "Voltar ao mapa"). Quando a rede volta, o que falhou (a loja, as
//    regiões) pede-se outra vez.
//
// Adaptações ao portal: ids uuid em texto; as chamadas do `lib/crm/api.js`
// (sempre com o id da rota) e os erros `ErroCrm`; os avisos de sucesso são
// toasts do sonner (`aoAvisar`); a região da loja que não está na lista das
// regiões fica escolhida como "Região guardada" (no autónomo passava a "Sem
// região" e guardar tirava a loja da região).
import { camposAlterados } from './diferencas';
import { RESPOSTA_ABRIR, RESPOSTA_OUTRA, dialogoDuplicado } from './dialogo';
import { PARAMETRO_LOJA, textoDoErro } from './ecraMapa';
import { FUNIL } from './fases';
import { TEXTO_REGIAO_GUARDADA } from './filtros';
import { eUuid } from './ids';
import {
  alternarDia as alternarDiaNoFormulario,
  comErro,
  comErros,
  escolherMorada as escolherMoradaNoFormulario,
  estadoInicial,
  limparErros,
  mudarCampo as mudarCampoNoFormulario,
  opcoesRegiaoLoja,
  preencherComLoja,
  reporMorada,
  sugerirMorada as sugerirMoradaNoFormulario,
  valorSeletorRegiao,
  valoresDoFormulario,
} from './formularioLoja';
import {
  TEXTO_A_GUARDAR, TEXTO_GUARDAR, TEXTO_GUARDAR_SEM_REDE, caminhoDaFicha, respostaAoErro,
} from './lojaNova';
import { CAMPOS_MORADA } from './morada';

export const TITULO_FICHA = 'Ficha da loja';
export const TEXTO_A_CARREGAR = 'A carregar a ficha…';
export const TEXTO_CONFLITO = 'Alterado por outra pessoa — recarregar';
export const TEXTO_RECARREGAR = 'Recarregar';
export const TEXTO_FASE_GUARDADA = 'Fase guardada';
export const TEXTO_ALTERACOES_GUARDADAS = 'Alterações guardadas';
export const TEXTO_LOJA_APAGADA = 'Loja apagada';
export const TEXTO_CORRIGIR = 'Corrigir localização';
export const TEXTO_CANCELAR_CORRECAO = 'Cancelar correção';
export const TEXTO_APAGAR_LOJA = 'Apagar loja';
export const TEXTO_A_APAGAR = 'A apagar…';
export const TEXTO_APAGAR_PERGUNTA = 'Apagar esta loja?';
export const TEXTO_APAGAR_AVISO = 'Use só para enganos — se a loja não está interessada, mude a fase para Perdida.';
export const TEXTO_APAGAR = `${TEXTO_APAGAR_PERGUNTA} ${TEXTO_APAGAR_AVISO}`;
export const RESPOSTA_APAGAR = 'apagar';

// Os motivos do Guardar desativado (o `falta`), pela ordem em que contam.
export const TEXTO_FALTA_CONFLITO = 'Recarregue a ficha para ver o que a outra pessoa mudou.';
export const TEXTO_FALTA_NOME = 'Para guardar, escreva o nome.';
export const TEXTO_FALTA_CORRECAO = 'Para guardar, confirme a localização no mapa ou cancele a correção.';
export const TEXTO_FALTA_ALTERACOES = 'Sem alterações por guardar.';

// A pergunta do Apagar: a primeira escolha é a que não apaga (o foco vai para ela).
export const PERGUNTA_APAGAR = Object.freeze({
  pergunta: TEXTO_APAGAR_PERGUNTA,
  aviso: TEXTO_APAGAR_AVISO,
  botoes: Object.freeze([
    Object.freeze({ texto: 'Cancelar', valor: null, variante: 'normal' }),
    Object.freeze({ texto: 'Sim, apagar', valor: RESPOSTA_APAGAR, variante: 'perigo' }),
  ]),
});

// --- Funções puras -------------------------------------------------------------------------------

// O botão Guardar da ficha: {ativo, texto, falta} (falta: porque não se pode guardar, ou null).
export function estadoGuardarFicha({ nome, alterada, aCorrigir, conflito, online, aGuardar }) {
  if (aGuardar) return { ativo: false, texto: TEXTO_A_GUARDAR, falta: null };
  if (!online) return { ativo: false, texto: TEXTO_GUARDAR_SEM_REDE, falta: null };
  const desativado = (falta) => ({ ativo: false, texto: TEXTO_GUARDAR, falta });
  if (conflito) return desativado(TEXTO_FALTA_CONFLITO);
  if (typeof nome !== 'string' || nome.trim() === '') return desativado(TEXTO_FALTA_NOME);
  if (aCorrigir) return desativado(TEXTO_FALTA_CORRECAO);
  if (!alterada) return desativado(TEXTO_FALTA_ALTERACOES);
  return { ativo: true, texto: TEXTO_GUARDAR, falta: null };
}

// O corpo do PATCH /api/crm/lojas/{id}: só os campos que mudaram e o atualizado_em da loja carregada
// (bloqueio otimista: se outra pessoa a alterou entretanto, o servidor responde 409 conflito).
export function corpoAlteracao(original, atual, { confirmarDuplicado = false } = {}) {
  const corpo = { ...camposAlterados(original, atual), atualizado_em: original.atualizado_em };
  if (confirmarDuplicado) corpo.confirmar_duplicado = true;
  return corpo;
}

// De onde vem o pino guardado (origem_coords), em palavras.
export function textoLocalizacao(loja) {
  if (loja?.origem_coords === 'gps') {
    return Number.isFinite(loja.precisao_m)
      ? `Pino do GPS, no local (precisão de ${loja.precisao_m} m).`
      : 'Pino do GPS, no local.';
  }
  if (loja?.origem_coords === 'geocoder') return 'Pino da morada escolhida na pesquisa.';
  // O pino de um lugar da Google é sempre arrastado pela pessoa (mapa Google, plano G9): fica pin_manual + id.
  const doGoogle = typeof loja?.google_place_id === 'string' && loja.google_place_id.trim() !== '';
  if (loja?.origem_coords === 'pin_manual' && doGoogle) return 'Pino posto à mão a partir de um lugar da Google.';
  return 'Pino posto à mão no mapa.';
}

// As opções da região na ficha: as da nova loja (`opcoesRegiaoLoja`) e, se a região da loja não estiver na
// lista (ou a lista ainda não chegou), essa região como "Região guardada", para não se perder ao guardar.
export function opcoesRegiaoFicha(regioes, regiaoDaLoja) {
  if (regioes == null) return opcoesRegiaoLoja(null, regiaoDaLoja);
  const opcoes = opcoesRegiaoLoja(regioes, null);
  if (!eUuid(regiaoDaLoja) || opcoes.some((opcao) => opcao.valor === regiaoDaLoja)) return opcoes;
  return Object.freeze([...opcoes, Object.freeze({ valor: regiaoDaLoja, texto: TEXTO_REGIAO_GUARDADA })]);
}

// Depois de apagar: o mapa da mesma casa, com o aviso no `state` (o mapa mostra-o num toast).
export function destinoDepoisDeApagar(base) {
  return { caminho: `${base}/mapa`, estado: { aviso: TEXTO_LOJA_APAGADA } };
}

// "Ver no mapa": o mapa da mesma casa centrado na loja.
export function caminhoNoMapa(base, id) {
  return `${base}/mapa?${PARAMETRO_LOJA}=${encodeURIComponent(id)}`;
}

// --- Ecrã ----------------------------------------------------------------------------------------

// criarFicha({api, rede, base, id, navegar, seletor, aoMudarVista, aoFocar, aoAvisar})
//   → {vista, iniciar, tentarDeNovo, mudarCampo, guardarFase, alternarDia, escolherMorada, sugerirMorada,
//      abrirCorrecao, cancelarCorrecao, mudarLocalizacao, guardar, recarregar, responderDuplicado, pedirApagar,
//      responderApagar, destruir}
//  - api: {obterLoja, listarRegioes, alterarLoja, apagarLoja} do lib/crm/api.js; id: o `:lojaId` da rota;
//  - rede: o `criarEstadoRede(window, navigator)`; base: a casa do CRM (`/crm` ou `/admin/crm`);
//  - navegar(caminho, opcoes?): o `navigate` do React Router;
//  - seletor: {limparErro, desconfirmar, mostrarErro, focar} do SeletorLocalizacao da correção (pela ref);
//  - aoMudarVista(vista); aoFocar(alvo): o foco deve ir para 'recarregar', 'corrigir' ou o campo do
//    formulário com erro; aoAvisar(texto): "Fase guardada" / "Alterações guardadas" (um toast).
// vista: {estado: 'a_carregar'|'falha'|'ficha', titulo, falha: null | {mensagem, tentar, aTentar, voltar},
//         valores, erros, opcoesRegiao, valorRegiao, resumoLocalizacao,
//         correcao: null | {chave, inicial: {lat, lng, origem, precisao_m}}, camposDesativados,
//         guardar: {ativo, texto, falta}, alerta, conflito: null | {erro, aRecarregar},
//         duplicado: null | {loja, mensagem, botoes}, apagar: {texto, ativo, erro, pergunta}}
//   — nova a cada mudança e congelada. `correcao.chave` muda a cada abertura (a `key` do seletor: o
//   `inicial` só se lê ao criá-lo).
// Criar o ecrã não pede nada: `iniciar()` pede a loja e as regiões e ouve a rede; `destruir()` (o ecrã saiu)
// faz que as respostas que chegarem depois, a rede e as respostas aos diálogos já não façam nada.
export function criarFicha({
  api, rede, base, id, navegar, seletor, aoMudarVista, aoFocar, aoAvisar,
}) {
  let original = null; // a loja como o servidor a tem (a do GET, ou a devolvida pelo último PATCH)
  let formulario = estadoInicial({ ficha: true });
  let regioes = null; // o GET /api/crm/regioes, quando chegar
  let falha = null; // {mensagem, naoExiste}: a loja não carregou
  let aCarregar = false;
  let aCarregarRegioes = false;
  let aGuardar = false; // o Guardar (os campos ficam desativados até à resposta)
  let aGuardarFase = false; // o toque na fase (os outros campos continuam editáveis)
  let aApagar = false; // depois de apagar fica true: não há segundo pedido até o ecrã mudar
  let aRecarregar = false;
  let conflito = false;
  let erroRecarregar = null;
  let alerta = null;
  let erroApagar = null;
  let perguntarApagar = false;
  let duplicada = null; // a loja do diálogo do duplicado, enquanto está aberto
  // A correção da localização em curso: {chave, localizacao (a confirmada, ou null), moradaAntes}.
  let correcao = null;
  let chaveCorrecao = 0;
  let iniciado = false;
  let ativo = true;
  let cancelarRede = () => {};

  const online = () => rede?.online() ?? true;

  // O que está na ficha agora, para comparar com a loja guardada.
  function atual() {
    const valores = valoresDoFormulario(formulario.valores, { ficha: true });
    return correcao?.localizacao ? { ...valores, ...correcao.localizacao } : valores;
  }

  function estadoAtual() {
    const agora = atual();
    return estadoGuardarFicha({
      nome: agora.nome,
      alterada: original !== null && Object.keys(camposAlterados(original, agora)).length > 0,
      aCorrigir: correcao !== null && correcao.localizacao === null,
      conflito,
      online: online(),
      aGuardar: aGuardar || aGuardarFase,
    });
  }

  function vistaDaCorrecao() {
    if (correcao === null || original === null) return null;
    return Object.freeze({
      chave: correcao.chave,
      inicial: Object.freeze({
        lat: original.lat, lng: original.lng, origem: original.origem_coords, precisao_m: original.precisao_m,
      }),
    });
  }

  function montarVista() {
    let estado = 'a_carregar';
    if (original !== null) estado = 'ficha';
    else if (falha !== null) estado = 'falha';
    const valores = { ...formulario.valores };
    if (Array.isArray(valores.dias_fechada)) valores.dias_fechada = Object.freeze([...valores.dias_fechada]);
    return Object.freeze({
      estado,
      titulo: typeof original?.nome === 'string' && original.nome !== '' ? original.nome : TITULO_FICHA,
      falha: falha === null || original !== null ? null : Object.freeze({
        mensagem: falha.mensagem, tentar: !falha.naoExiste, aTentar: aCarregar, voltar: falha.naoExiste,
      }),
      valores: Object.freeze(valores),
      erros: Object.freeze({ ...formulario.erros }),
      opcoesRegiao: opcoesRegiaoFicha(regioes, original?.regiao_id ?? null),
      valorRegiao: valorSeletorRegiao(formulario.valores.regiao_id),
      resumoLocalizacao: original === null ? null : textoLocalizacao(original),
      correcao: vistaDaCorrecao(),
      camposDesativados: aGuardar,
      guardar: Object.freeze(estadoAtual()),
      alerta,
      conflito: conflito ? Object.freeze({ erro: erroRecarregar, aRecarregar }) : null,
      duplicado: duplicada === null ? null : Object.freeze({ loja: duplicada, ...dialogoDuplicado(duplicada) }),
      apagar: Object.freeze({
        texto: aApagar ? TEXTO_A_APAGAR : TEXTO_APAGAR_LOJA,
        ativo: original !== null && !aApagar,
        erro: erroApagar,
        pergunta: perguntarApagar ? PERGUNTA_APAGAR : null,
      }),
    });
  }

  let vista = montarVista();

  function atualizar() {
    vista = montarVista();
    aoMudarVista?.(vista);
  }

  function mudarFormulario(novo) {
    if (!ativo || novo === formulario) return;
    formulario = novo;
    atualizar();
  }

  function limparMensagens() {
    alerta = null;
    formulario = limparErros(formulario);
    if (correcao !== null) seletor?.limparErro?.();
  }

  // Fecha a correção. Com `repor`, desfaz a morada que a pesquisa ou o GPS puseram durante a correção.
  function fecharCorrecao({ repor = false } = {}) {
    if (correcao === null) return;
    const { moradaAntes } = correcao;
    correcao = null;
    if (repor) formulario = reporMorada(formulario, moradaAntes);
  }

  // A ficha com esta loja (a do GET, a do Recarregar ou a devolvida pelo PATCH do Guardar).
  function aplicarLoja(loja) {
    original = loja;
    falha = null;
    conflito = false;
    erroRecarregar = null;
    fecharCorrecao();
    // A falha das regiões (se ainda não chegaram) fica junto ao campo: preencher apaga os erros, e um erro do
    // servidor não traz o 'online' que as volta a pedir (no autónomo, preencher não mexia nos erros).
    const erroRegioes = regioes === null ? formulario.erros.regiao_id : undefined;
    formulario = preencherComLoja(loja, { ficha: true });
    if (erroRegioes) formulario = comErro(formulario, 'regiao_id', erroRegioes);
    atualizar();
  }

  // Sem a loja não há ficha: a mensagem e "Tentar novamente" (ou, se não existe, "Voltar ao mapa").
  function mostrarFalha(erro) {
    fecharCorrecao();
    original = null;
    conflito = false;
    erroRecarregar = null;
    duplicada = null;
    perguntarApagar = false;
    falha = { mensagem: textoDoErro(erro), naoExiste: erro?.codigo === 'nao_encontrado' };
    atualizar();
  }

  async function carregar() {
    if (!ativo || aCarregar || original !== null) return;
    aCarregar = true;
    atualizar();
    let loja;
    try {
      loja = await api.obterLoja(id);
    } catch (erro) {
      aCarregar = false;
      // Saiu do ecrã (também com a sessão terminada): nada a mostrar.
      if (ativo) mostrarFalha(erro);
      return;
    }
    aCarregar = false;
    if (ativo) aplicarLoja(loja);
  }

  async function carregarRegioes() {
    if (!ativo || aCarregarRegioes || regioes !== null) return;
    aCarregarRegioes = true;
    let lista;
    try {
      lista = await api.listarRegioes();
    } catch (erro) {
      aCarregarRegioes = false;
      if (ativo) mudarFormulario(comErro(formulario, 'regiao_id', textoDoErro(erro)));
      return;
    }
    aCarregarRegioes = false;
    if (!ativo) return;
    regioes = Array.isArray(lista) ? lista : [];
    // Fica a região que está escolhida (a da loja, ou a que a pessoa já escolheu); o erro de antes sai.
    formulario = mudarCampoNoFormulario(formulario, 'regiao_id', formulario.valores.regiao_id);
    atualizar();
  }

  function tratarErro(erro) {
    if (erro?.codigo === 'conflito') {
      conflito = true;
      atualizar();
      aoFocar?.('recarregar');
      return;
    }
    const resposta = respostaAoErro(erro, { ficha: true, comSeletor: correcao !== null });
    if (resposta.tipo === 'duplicado') {
      duplicada = resposta.loja;
      atualizar();
      return;
    }
    alerta = resposta.alerta;
    if (resposta.tipo !== 'validacao') {
      atualizar();
      return;
    }
    formulario = comErros(formulario, resposta.erros);
    atualizar();
    if (resposta.localizacao !== null) {
      // O pino volta a soltar-se para a pessoa o pôr noutro sítio e confirmar outra vez.
      seletor?.desconfirmar?.();
      seletor?.mostrarErro?.(resposta.localizacao);
      seletor?.focar?.();
    } else if (resposta.primeiro !== null) {
      aoFocar?.(resposta.primeiro);
    }
  }

  async function guardar({ confirmarDuplicado = false } = {}) {
    if (!ativo || original === null || !estadoAtual().ativo) return;
    const corpo = corpoAlteracao(original, atual(), { confirmarDuplicado });
    aGuardar = true;
    limparMensagens();
    atualizar();

    let loja;
    try {
      loja = await api.alterarLoja(id, corpo);
    } catch (erro) {
      if (!ativo) return;
      aGuardar = false;
      tratarErro(erro);
      return;
    }
    if (!ativo) return;
    aGuardar = false;
    aplicarLoja(loja);
    aoAvisar?.(TEXTO_ALTERACOES_GUARDADAS);
  }

  // A fase num toque: só a fase e a versão em vigor, um pedido de cada vez.
  async function guardarFase() {
    if (!ativo || original === null || aGuardar || aGuardarFase || conflito || !online()) return;
    const { fase } = formulario.valores;
    if (!FUNIL.includes(fase) || fase === original.fase) return;
    aGuardarFase = true;
    alerta = null;
    atualizar();

    let loja;
    try {
      loja = await api.alterarLoja(id, { fase, atualizado_em: original.atualizado_em });
    } catch (erro) {
      if (!ativo) return;
      aGuardarFase = false;
      // O conflito e o 422 como no Guardar; os outros erros (ex.: sem rede) junto à fase, onde se tocou.
      if (erro?.codigo === 'conflito' || erro?.codigo === 'validacao') tratarErro(erro);
      else mudarFormulario(comErro(formulario, 'fase', textoDoErro(erro)));
      return;
    }
    if (!ativo) return;
    aGuardarFase = false;
    // A loja como o servidor a tem agora (fase e atualizado_em novos). Os campos não se tocam: o que a pessoa
    // mudou neles continua por guardar.
    original = loja;
    atualizar();
    // Escolheu outra fase enquanto esta gravava: grava-se agora, com a versão nova (o aviso é o dessa).
    if (formulario.valores.fase !== original.fase) guardarFase();
    else aoAvisar?.(TEXTO_FASE_GUARDADA);
  }

  async function recarregar() {
    if (!ativo || !conflito || aRecarregar) return;
    aRecarregar = true;
    erroRecarregar = null;
    atualizar();
    let loja;
    try {
      loja = await api.obterLoja(id);
    } catch (erro) {
      if (!ativo) return;
      aRecarregar = false;
      if (erro?.codigo === 'nao_encontrado') {
        mostrarFalha(erro);
        return;
      }
      erroRecarregar = textoDoErro(erro);
      atualizar();
      return;
    }
    if (!ativo) return;
    aRecarregar = false;
    limparMensagens();
    aplicarLoja(loja);
  }

  async function apagar() {
    aApagar = true;
    erroApagar = null;
    atualizar();
    try {
      await api.apagarLoja(id);
    } catch (erro) {
      if (!ativo) return;
      aApagar = false;
      erroApagar = textoDoErro(erro);
      atualizar();
      return;
    }
    if (!ativo) return;
    const destino = destinoDepoisDeApagar(base);
    navegar?.(destino.caminho, { state: destino.estado });
  }

  return {
    get vista() {
      return vista;
    },
    iniciar() {
      if (!ativo || iniciado) return;
      iniciado = true;
      // Sem rede, Guardar fica desativado; quando a rede volta, o que falhou (a loja, as regiões) pede-se
      // outra vez.
      cancelarRede = rede?.aoMudar((ligado) => {
        if (!ativo) return;
        atualizar();
        if (!ligado) return;
        if (original === null && falha !== null && !falha.naoExiste) carregar();
        carregarRegioes();
      }) ?? (() => {});
      carregar();
      carregarRegioes();
    },
    // "Tentar novamente" (a loja não carregou); um toque, um pedido.
    tentarDeNovo() {
      if (falha !== null && !falha.naoExiste) carregar();
    },
    mudarCampo(campo, valor) {
      if (aGuardar) return; // os campos estão desativados enquanto grava
      mudarFormulario(mudarCampoNoFormulario(formulario, campo, valor));
    },
    // A pastilha da fase (depois do `mudarCampo('fase', …)`): grava logo.
    guardarFase,
    alternarDia(dia, marcado) {
      if (aGuardar) return;
      mudarFormulario(alternarDiaNoFormulario(formulario, dia, marcado));
    },
    // A morada escolhida na pesquisa do seletor, e a sugerida pelo GPS (só com a correção aberta).
    escolherMorada(sugestao) {
      if (correcao !== null) mudarFormulario(escolherMoradaNoFormulario(formulario, sugestao));
    },
    sugerirMorada(sugestao) {
      if (correcao !== null) mudarFormulario(sugerirMoradaNoFormulario(formulario, sugestao));
    },
    abrirCorrecao() {
      if (!ativo || correcao !== null || original === null || aGuardar) return;
      chaveCorrecao += 1;
      const moradaAntes = Object.fromEntries(CAMPOS_MORADA.map((campo) => [campo, formulario.valores[campo]]));
      correcao = { chave: chaveCorrecao, localizacao: null, moradaAntes };
      atualizar();
    },
    cancelarCorrecao() {
      if (!ativo || correcao === null) return;
      fecharCorrecao({ repor: true });
      atualizar();
      aoFocar?.('corrigir');
    },
    // A localização confirmada no seletor ({lat, lng, origem_coords, precisao_m}), ou null.
    mudarLocalizacao(nova) {
      const valor = nova ?? null;
      if (!ativo || correcao === null || valor === correcao.localizacao) return;
      correcao = { ...correcao, localizacao: valor };
      atualizar();
    },
    guardar,
    recarregar,
    // A resposta ao diálogo do duplicado ('abrir', 'outra' ou null); só a primeira conta.
    responderDuplicado(valor) {
      if (!ativo || duplicada === null) return;
      const loja = duplicada;
      duplicada = null;
      atualizar();
      if (valor === RESPOSTA_ABRIR) navegar?.(caminhoDaFicha(base, loja.id));
      else if (valor === RESPOSTA_OUTRA) guardar({ confirmarDuplicado: true });
    },
    pedirApagar() {
      if (!ativo || original === null || aApagar || perguntarApagar || duplicada !== null) return;
      perguntarApagar = true;
      atualizar();
    },
    // A resposta à pergunta do Apagar ('apagar' ou null); só a primeira conta.
    responderApagar(valor) {
      if (!ativo || !perguntarApagar) return;
      perguntarApagar = false;
      atualizar();
      if (valor === RESPOSTA_APAGAR) apagar();
    },
    destruir() {
      if (!ativo) return;
      ativo = false;
      cancelarRede();
      duplicada = null;
      perguntarApagar = false;
      vista = montarVista();
    },
  };
}
