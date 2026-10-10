// O ecrã "Nova loja" (desenho original §6.2; plano T2.27), sem DOM. Porta de
// public/assets/js/ecras/loja-nova.js do CRM autónomo: as funções puras tal e
// qual, e o ecrã como o seletor da T2.26 — o que o autónomo escrevia no DOM é
// uma `vista` congelada, entregue ao `aoMudarVista`, e o
// `pages/crm/CrmLojaNova.js` só a desenha (correção "componentes Sem Jest").
//
//  - Primeiro a localização (o `SeletorLocalizacao`: pino, pesquisa de morada
//    ou "Estou nesta loja"), depois os dados (`formularioLoja.js`): nome*,
//    fase* (Potencial por omissão), região, telefone, pessoa de contacto,
//    morada, código postal, localidade e notas. O horário de receção e os dias
//    fechada ficam para a ficha (T2.28).
//  - Guardar só fica ativo com o nome e a localização confirmada. Adicionar uma
//    loja exige rede: sem rede, o botão fica desativado com "sem rede" e volta
//    quando a rede voltar (`rede.js`).
//  - 422 → os erros junto aos campos (os da localização, junto ao mapa, e o
//    pino volta a soltar-se) e a mensagem do servidor por cima.
//  - 409 duplicado → "Já existe X aqui — é a mesma?" (`dialogo.js`): "Sim, abrir
//    X" abre a ficha dessa loja; "Não, é outra loja" volta a enviar com
//    `confirmar_duplicado`; "Cancelar" (ou o Escape) não faz nada.
//  - Região: pré-escolhida com a última usada (`crm.ultimaRegiao`). Até as
//    regiões chegarem (ou se não chegarem) fica escolhida como "Região
//    guardada", para não se gravar a loja sem região nem se esquecer a última.
//    Se falharem, o erro fica junto à região e voltam a pedir-se quando a rede
//    voltar.
//  - Sucesso → guarda a região usada (sem região, esquece a anterior) e volta
//    ao mapa da mesma casa centrado na loja nova, com o aviso "Loja guardada"
//    no `state` (o mapa mostra-o num toast; nota da T2.25).
//
// Adaptações ao portal: a última região é um uuid em texto, guardado em
// `crm.ultimaRegiao` (era `phc.ultimaRegiao`); as chamadas são as do
// `lib/crm/api.js` e os erros `ErroCrm`; os caminhos são os do React Router.
import { CAMPOS_LOCALIZACAO } from './diferencas';
import { RESPOSTA_ABRIR, RESPOSTA_OUTRA, dialogoDuplicado, lojaDuplicada } from './dialogo';
import { PARAMETRO_LOJA, textoDoErro } from './ecraMapa';
import { eUuid } from './ids';
import {
  ajustarRegiao,
  comErro,
  comErros,
  escolherMorada as escolherMoradaNoFormulario,
  estadoInicial,
  limparErros,
  mudarCampo as mudarCampoNoFormulario,
  opcoesRegiaoLoja,
  separarErros,
  sugerirMorada as sugerirMoradaNoFormulario,
  valorSeletorRegiao,
  valoresDoFormulario,
} from './formularioLoja';

export const CHAVE_ULTIMA_REGIAO = 'crm.ultimaRegiao';
export const TEXTO_LOJA_GUARDADA = 'Loja guardada';
export const TEXTO_GUARDAR = 'Guardar';
export const TEXTO_A_GUARDAR = 'A guardar…';
export const TEXTO_GUARDAR_SEM_REDE = 'Guardar — sem rede';

// --- Funções puras -------------------------------------------------------------------------------

// O botão Guardar: {ativo, texto, falta} (falta: o que ainda é preciso para guardar, ou null).
export function estadoGuardar({ nome, localizacao, online, aGuardar }) {
  if (aGuardar) return { ativo: false, texto: TEXTO_A_GUARDAR, falta: null };
  if (!online) return { ativo: false, texto: TEXTO_GUARDAR_SEM_REDE, falta: null };
  const temNome = typeof nome === 'string' && nome.trim() !== '';
  const temLocalizacao = localizacao !== null && localizacao !== undefined;
  if (temNome && temLocalizacao) return { ativo: true, texto: TEXTO_GUARDAR, falta: null };
  let falta = 'Para guardar, confirme a localização no mapa.';
  if (!temNome) falta = temLocalizacao ? 'Para guardar, escreva o nome.' : 'Para guardar, escreva o nome e confirme a localização.';
  return { ativo: false, texto: TEXTO_GUARDAR, falta };
}

// O corpo do POST /api/crm/lojas: os campos do formulário e a localização confirmada.
export function corpoLojaNova(valores, localizacao, { confirmarDuplicado = false } = {}) {
  const corpo = { ...valores, ...localizacao };
  if (confirmarDuplicado) corpo.confirmar_duplicado = true;
  return corpo;
}

// A região da última loja guardada (um uuid), ou null. O armazenamento pode faltar ou lançar.
export function carregarUltimaRegiao(storage) {
  try {
    const texto = storage.getItem(CHAVE_ULTIMA_REGIAO);
    return eUuid(texto) ? texto : null;
  } catch {
    return null;
  }
}

// Guarda a região usada; sem região, esquece a anterior (a próxima loja começa em "Sem região").
export function guardarUltimaRegiao(storage, regiaoId) {
  try {
    if (eUuid(regiaoId)) storage.setItem(CHAVE_ULTIMA_REGIAO, regiaoId);
    else storage.removeItem(CHAVE_ULTIMA_REGIAO);
    return true;
  } catch {
    return false;
  }
}

// O que mostrar com o erro de um POST (ou PATCH) da loja:
//  - {tipo: 'duplicado', loja}: o 409 com a loja mais perto, para o diálogo;
//  - {tipo: 'validacao', alerta, erros, primeiro, localizacao}: o 422 — os erros dos campos do formulário
//    (`primeiro` para o foco), o da localização (para o seletor) e, no alerta, a mensagem do servidor com os
//    dos campos que o formulário não tem;
//  - {tipo: 'erro', alerta}: o resto (também um duplicado sem a lista), com a mensagem do erro.
export function respostaAoErro(erro, { ficha = false } = {}) {
  const duplicada = erro?.codigo === 'duplicado' ? lojaDuplicada(erro.extra?.lojas) : null;
  if (duplicada) return { tipo: 'duplicado', loja: duplicada };
  if (erro?.codigo !== 'validacao') return { tipo: 'erro', alerta: textoDoErro(erro) };
  const { porCampo, primeiro, restantes } = separarErros(erro.campos, { ficha });
  const localizacao = CAMPOS_LOCALIZACAO.map((campo) => restantes[campo]).find((texto) => typeof texto === 'string') ?? null;
  const outros = Object.entries(restantes).filter(([campo]) => !CAMPOS_LOCALIZACAO.includes(campo)).map(([, texto]) => texto);
  return { tipo: 'validacao', alerta: [textoDoErro(erro), ...outros].join(' '), erros: porCampo, primeiro, localizacao };
}

// Depois de gravar: o mapa da mesma casa centrado na loja nova (`?loja=<id>`), com o aviso no `state`.
export function destinoDepoisDeGuardar(base, loja) {
  const id = loja?.id;
  const caminho = typeof id === 'string' && id !== '' ? `${base}/mapa?${PARAMETRO_LOJA}=${encodeURIComponent(id)}` : `${base}/mapa`;
  return { caminho, estado: { aviso: TEXTO_LOJA_GUARDADA } };
}

// A ficha de uma loja na mesma casa (o id num só pedaço do caminho).
export function caminhoDaFicha(base, id) {
  return `${base}/lojas/${encodeURIComponent(id)}`;
}

// --- Ecrã ----------------------------------------------------------------------------------------

// criarLojaNova({api, storage, rede, base, navegar, seletor, aoMudarVista, aoFocar})
//   → {vista, iniciar, mudarCampo, escolherMorada, sugerirMorada, mudarLocalizacao, guardar, responder, destruir}
//  - api: {listarRegioes, criarLoja} do lib/crm/api.js;
//  - storage: o localStorage (pode faltar ou lançar); rede: o `criarEstadoRede(window, navigator)`;
//  - base: a casa do CRM (`/crm` ou `/admin/crm`); navegar(caminho, opcoes?): o `navigate` do React Router;
//  - seletor: {limparErro, desconfirmar, mostrarErro, focar} do SeletorLocalizacao (pela ref);
//  - aoMudarVista(vista); aoFocar(campo): o foco deve ir para esse campo do formulário.
// vista: {valores, erros, opcoesRegiao, valorRegiao, guardar: {ativo, texto, falta}, alerta,
//         duplicado: null | {loja, mensagem, botoes}} — nova a cada mudança e congelada.
// Criar o ecrã não pede nada: `iniciar()` pede as regiões e ouve a rede; `destruir()` (o ecrã saiu) faz que
// as respostas que chegarem depois, a rede e as respostas ao diálogo já não façam nada.
export function criarLojaNova({ api, storage, rede, base, navegar, seletor, aoMudarVista, aoFocar }) {
  const regiaoGuardada = carregarUltimaRegiao(storage);
  let formulario = estadoInicial({ regiaoId: regiaoGuardada });
  let localizacao = null; // a confirmada no seletor
  let regioes = null; // null até chegarem
  let aCarregarRegioes = false;
  let aGuardar = false; // depois de gravar fica true: não há segundo envio até o ecrã mudar
  let alerta = null;
  let duplicada = null; // a loja do diálogo do duplicado, enquanto está aberto
  let iniciado = false;
  let ativo = true;
  let cancelarRede = () => {};

  const online = () => rede?.online() ?? true;

  function montarVista() {
    return Object.freeze({
      valores: Object.freeze({ ...formulario.valores }),
      erros: Object.freeze({ ...formulario.erros }),
      // Enquanto as regiões não chegam, a guardada fica na lista (mesmo que a pessoa escolha "Sem região").
      opcoesRegiao: opcoesRegiaoLoja(regioes, regioes === null ? regiaoGuardada : null),
      valorRegiao: valorSeletorRegiao(formulario.valores.regiao_id),
      guardar: Object.freeze(estadoGuardar({ nome: formulario.valores.nome, localizacao, online: online(), aGuardar })),
      alerta,
      duplicado: duplicada === null ? null : Object.freeze({ loja: duplicada, ...dialogoDuplicado(duplicada) }),
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
    // Fica a que está escolhida: a última usada, ou a que a pessoa já escolheu entretanto.
    formulario = ajustarRegiao(formulario, regioes);
    atualizar();
  }

  function tratarErro(erro) {
    const resposta = respostaAoErro(erro);
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
    if (!ativo) return;
    const estado = estadoGuardar({ nome: formulario.valores.nome, localizacao, online: online(), aGuardar });
    if (!estado.ativo) return;
    aGuardar = true;
    alerta = null;
    formulario = limparErros(formulario);
    seletor?.limparErro?.();
    atualizar();

    const valores = valoresDoFormulario(formulario.valores);
    let loja;
    try {
      loja = await api.criarLoja(corpoLojaNova(valores, localizacao, { confirmarDuplicado }));
    } catch (erro) {
      // Saiu do ecrã (também com a sessão terminada): nada a mostrar.
      if (!ativo) return;
      aGuardar = false;
      tratarErro(erro);
      return;
    }
    if (!ativo) return;
    guardarUltimaRegiao(storage, valores.regiao_id);
    const destino = destinoDepoisDeGuardar(base, loja);
    navegar?.(destino.caminho, { state: destino.estado });
  }

  return {
    get vista() {
      return vista;
    },
    iniciar() {
      if (!ativo || iniciado) return;
      iniciado = true;
      // Sem rede, Guardar fica desativado; quando a rede volta, as regiões que falharam pedem-se outra vez.
      cancelarRede = rede?.aoMudar((ligado) => {
        if (!ativo) return;
        atualizar();
        if (ligado) carregarRegioes();
      }) ?? (() => {});
      carregarRegioes();
    },
    mudarCampo(campo, valor) {
      mudarFormulario(mudarCampoNoFormulario(formulario, campo, valor));
    },
    // A morada escolhida na pesquisa do seletor, e a sugerida pelo GPS.
    escolherMorada(sugestao) {
      mudarFormulario(escolherMoradaNoFormulario(formulario, sugestao));
    },
    sugerirMorada(sugestao) {
      mudarFormulario(sugerirMoradaNoFormulario(formulario, sugestao));
    },
    // A localização confirmada no seletor ({lat, lng, origem_coords, precisao_m}), ou null.
    mudarLocalizacao(nova) {
      const valor = nova ?? null;
      if (!ativo || valor === localizacao) return;
      localizacao = valor;
      atualizar();
    },
    guardar,
    // A resposta ao diálogo do duplicado ('abrir', 'outra' ou null); só a primeira conta.
    responder(valor) {
      if (!ativo || duplicada === null) return;
      const loja = duplicada;
      duplicada = null;
      atualizar();
      if (valor === RESPOSTA_ABRIR) navegar?.(caminhoDaFicha(base, loja.id));
      else if (valor === RESPOSTA_OUTRA) guardar({ confirmarDuplicado: true });
    },
    destruir() {
      if (!ativo) return;
      ativo = false;
      cancelarRede();
      duplicada = null;
      vista = montarVista();
    },
  };
}
