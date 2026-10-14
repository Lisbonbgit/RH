// Cliente da API do CRM (`/api/crm/*`). Molde do `lib/faturacao.js`: cliente
// axios próprio com tecto de espera e o JWT do portal lido a cada pedido.
//
// **Todo o erro sai daqui com a mesma forma**: `ErroCrm` com `{codigo,
// mensagem, campos, extra, estado}` — a do `ErroApi` do CRM autónomo. O backend
// fala de três maneiras e os ecrãs não têm de as conhecer:
//   - erros do CRM: `detail` objeto `{codigo, mensagem, campos?, …extra}`;
//   - erros herdados da sessão do portal (`faturacao.auth` / `HTTPBearer`):
//     `detail` texto («Sessão terminada», «Not authenticated», …);
//   - 422 do Pydantic: `detail` lista `[{loc, msg, …}]` (em inglês; não devia
//     acontecer no CRM, que valida no domínio, mas nunca pode chegar ao toast
//     como array).
// Sem resposta do servidor (rede em baixo, tecto de espera) → `sem_rede`.
import axios, { AxiosHeaders } from 'axios';

export const MENSAGEM_SEM_REDE = 'Sem rede — verifique a ligação e tente novamente.';
export const MENSAGEM_ERRO_INESPERADO = 'Erro inesperado — tente novamente.';
// A mensagem geral do 422 `validacao` do backend (`crm/erros.py::validacao`).
export const MENSAGEM_VALIDACAO = 'Verifique os campos assinalados.';
// Os textos do `HTTPBearer` são em inglês e dizem «não há sessão», não «não
// tem permissão». Mostra-se o texto do backend para a mesma situação.
export const MENSAGEM_SEM_SESSAO = 'Sessão terminada';

// «Not authenticated»: pedido sem cabeçalho (403 no FastAPI 0.110; 401 nos
// mais novos). «Invalid authentication credentials»: cabeçalho sem «Bearer».
const TEXTOS_SEM_SESSAO = new Set(['Not authenticated', 'Invalid authentication credentials']);

export class ErroCrm extends Error {
  constructor({ codigo, mensagem, campos = {}, estado = 0, extra = {} }, opcoes) {
    super(mensagem, opcoes);
    this.name = 'ErroCrm';
    this.codigo = codigo;
    this.mensagem = mensagem;
    this.campos = campos;
    this.estado = estado;
    this.extra = extra;
  }
}

const eObjetoSimples = (x) => x !== null && typeof x === 'object' && !Array.isArray(x);
const eTextoComConteudo = (x) => typeof x === 'string' && x.trim() !== '';

// 422 do Pydantic: o campo é o fim da `loc` e a mensagem a `msg` (sem o
// «Value error, » que o Pydantic põe à frente dos erros dos validadores).
// Um campo por chave — fica a primeira mensagem, como no domínio.
function camposDoPydantic(lista) {
  const campos = {};
  for (const item of lista) {
    if (!eObjetoSimples(item) || !Array.isArray(item.loc) || item.loc.length === 0) continue;
    if (!eTextoComConteudo(item.msg)) continue;
    const campo = String(item.loc[item.loc.length - 1]);
    if (campo in campos) continue;
    campos[campo] = item.msg.replace(/^Value error,\s*/i, '');
  }
  return campos;
}

/**
 * Normaliza qualquer erro de um pedido ao CRM num `ErroCrm`.
 *
 * Um erro que não veio do axios (um engano no código) dá `erro_interno` e não
 * `sem_rede`: «verifique a ligação» mandava a pessoa ver o Wi-Fi por causa de
 * um erro de programação. Um `ErroCrm` volta igual.
 */
export function erroCrm(e) {
  if (e instanceof ErroCrm) return e;
  const causa = { cause: e };
  if (!axios.isAxiosError(e)) {
    return new ErroCrm({ codigo: 'erro_interno', mensagem: MENSAGEM_ERRO_INESPERADO, estado: 0 }, causa);
  }
  if (!e.response) {
    return new ErroCrm({ codigo: 'sem_rede', mensagem: MENSAGEM_SEM_REDE, estado: 0 }, causa);
  }

  const estado = e.response.status;
  const dados = e.response.data;
  const detail = eObjetoSimples(dados) ? dados.detail : undefined;

  if (eObjetoSimples(detail) && eTextoComConteudo(detail.codigo)) {
    const { codigo, mensagem, campos, ...extra } = detail;
    return new ErroCrm({
      codigo,
      mensagem: eTextoComConteudo(mensagem) ? mensagem : MENSAGEM_ERRO_INESPERADO,
      campos: eObjetoSimples(campos) ? campos : {},
      estado,
      extra,
    }, causa);
  }

  if (estado === 422 && Array.isArray(detail)) {
    return new ErroCrm({
      codigo: 'validacao', mensagem: MENSAGEM_VALIDACAO, campos: camposDoPydantic(detail), estado,
    }, causa);
  }

  if (TEXTOS_SEM_SESSAO.has(detail)) {
    return new ErroCrm({ codigo: 'nao_autenticado', mensagem: MENSAGEM_SEM_SESSAO, estado }, causa);
  }
  if (estado === 401) {
    return new ErroCrm({
      codigo: 'nao_autenticado',
      mensagem: eTextoComConteudo(detail) ? detail : MENSAGEM_ERRO_INESPERADO,
      estado,
    }, causa);
  }
  if (estado === 403 && eTextoComConteudo(detail)) {
    return new ErroCrm({ codigo: 'sem_permissao', mensagem: detail, estado }, causa);
  }

  // O resto: HTML de um proxy, o «Not Found» do FastAPI, um objeto sem código.
  return new ErroCrm({ codigo: 'erro_interno', mensagem: MENSAGEM_ERRO_INESPERADO, estado }, causa);
}

// --- O cliente HTTP -----------------------------------------------------------

// 30 s: o mesmo tecto do backoffice no `lib/faturacao.js`. Quase tudo o que o
// CRM faz só fala com o Mongo; a morada (F2) passa pela Geoapify no servidor,
// que desiste aos 5 s (`servicos/geoapify.py`) e responde 503. Sem `timeout`,
// o axios espera para sempre.
export const TIMEOUT_CRM_MS = 30000;
export const URL_BASE_CRM = `${process.env.REACT_APP_BACKEND_URL}/api/crm`;

// **O JWT lido A CADA PEDIDO**, de onde o `AuthContext` o põe (e de onde o
// `logout` o tira). O `axios.create` copia os `defaults` do axios global no
// instante em que corre: uma instância criada com a sessão aberta ficava com
// esse token para sempre. Por isso, sem token no axios global, o pedido sai
// sem `Authorization` — nunca com um token de uma sessão já terminada.
export function comAutorizacaoAtual(config) {
  const autorizacao = axios.defaults.headers.common.Authorization;
  const cabecalhos = AxiosHeaders.from(config.headers || {});
  if (autorizacao) cabecalhos.set('Authorization', autorizacao);
  else cabecalhos.delete('Authorization');
  config.headers = cabecalhos;
  return config;
}

export function criarInstanciaCrm() {
  const instancia = axios.create({ baseURL: URL_BASE_CRM, timeout: TIMEOUT_CRM_MS });
  instancia.interceptors.request.use(comAutorizacaoAtual);
  return instancia;
}

export const instanciaCrm = criarInstanciaCrm();

// Um id vai num só pedaço do caminho, codificado (`/` → `%2F`). Os pedaços «.»
// e «..» o browser resolve antes de enviar (`/lojas/..` → a raiz do CRM,
// `/lojas/.` → a lista), e codificar os pontos não chega (o URL do browser lê
// `%2e` como ponto); vazio dava `/lojas/`, que o FastAPI manda para a lista.
// Esses nunca saem: os ids vêm do servidor ou da rota, por isso é um engano
// no código (`erro_interno`, como os outros).
const PEDACOS_PROIBIDOS = new Set(['', '.', '..']);

function caminhoComId(recurso, id) {
  const pedaco = String(id);
  if (PEDACOS_PROIBIDOS.has(pedaco)) {
    throw new ErroCrm({ codigo: 'erro_interno', mensagem: MENSAGEM_ERRO_INESPERADO, estado: 0 });
  }
  return `${recurso}/${encodeURIComponent(pedaco)}`;
}

// Os parâmetros da query sem os `null`/`undefined` (nunca o texto "null"); o
// zero fica. É o `comParametros` do CRM autónomo.
function semNulos(parametros) {
  const limpos = {};
  for (const [nome, valor] of Object.entries(parametros)) {
    if (valor !== null && valor !== undefined) limpos[nome] = valor;
  }
  return limpos;
}

/**
 * As chamadas do CRM sobre um `pedir(config)` que devolve a resposta do axios
 * (`{data}`). Cada função devolve só os `data`; um erro sai como `ErroCrm`.
 * Os testes passam um `pedir` falso; por omissão é a instância do CRM.
 *
 * As funções com id são `async`: um id recusado pelo `caminhoComId` rejeita a
 * promessa, como qualquer outro erro, em vez de lançar fora dela.
 */
export function criarClienteCrm({ pedir = (config) => instanciaCrm.request(config) } = {}) {
  async function chamar(config) {
    let resposta;
    try {
      resposta = await pedir(config);
    } catch (e) {
      throw erroCrm(e);
    }
    return resposta.data;
  }

  return {
    // `{membro, perfil, admin_master}` da sessão atual (nunca 403).
    obterEu: () => chamar({ method: 'GET', url: '/eu' }),
    // Só admin do CRM.
    listarMembros: () => chamar({ method: 'GET', url: '/membros' }),
    listarCandidatos: () => chamar({ method: 'GET', url: '/membros/candidatos' }),
    // Só o `user_id` e o `perfil` vão no corpo: o resto é estado do ecrã.
    adicionarMembro: ({ user_id, perfil }) =>
      chamar({ method: 'POST', url: '/membros', data: { user_id, perfil } }),
    mudarPerfilMembro: async (membroId, perfil) =>
      chamar({ method: 'PATCH', url: caminhoComId('/membros', membroId), data: { perfil } }),
    retirarMembro: async (membroId) => chamar({ method: 'DELETE', url: caminhoComId('/membros', membroId) }),

    // --- F2 -------------------------------------------------------------------
    // Os corpos vão tal como o ecrã os montou, nas regras puras (corpoLojaNova,
    // corpoFabrica, camposAlterados + `atualizado_em`); o servidor valida-os.

    // Regiões: `[{id, nome, ordem}]` por ordem. Criar `{nome, ordem?}` → a
    // região; alterar `{nome?, ordem?}` → a região; apagar → `{apagada: true}`
    // (409 `regiao_com_lojas`). Só o listar é para o escritório; o resto, admin.
    listarRegioes: () => chamar({ method: 'GET', url: '/regioes' }),
    criarRegiao: (corpo) => chamar({ method: 'POST', url: '/regioes', data: corpo }),
    alterarRegiao: async (regiaoId, corpo) =>
      chamar({ method: 'PATCH', url: caminhoComId('/regioes', regiaoId), data: corpo }),
    apagarRegiao: async (regiaoId) => chamar({ method: 'DELETE', url: caminhoComId('/regioes', regiaoId) }),

    // Lojas: a lista é o resumo `[{id, nome, fase, regiao_id, lat, lng,
    // telefone, pessoa_contacto}]` (`CAMPOS_RESUMO` de `backend/crm/formatar.py`;
    // a pessoa entrou em 2026-10-13 para a linha de contacto do cartão do
    // mapa); obter, criar e alterar devolvem a loja completa (com o
    // `atualizado_em` novo). Um 409 `duplicado` traz `extra.lojas` (`[{id,
    // nome, distancia_m}]`) e reenvia-se com `confirmar_duplicado: true`; o 409
    // `conflito` só traz código e mensagem. Apagar → `{apagada: true}` (409
    // `loja_com_historico`).
    listarLojas: () => chamar({ method: 'GET', url: '/lojas' }),
    obterLoja: async (lojaId) => chamar({ method: 'GET', url: caminhoComId('/lojas', lojaId) }),
    criarLoja: (corpo) => chamar({ method: 'POST', url: '/lojas', data: corpo }),
    alterarLoja: async (lojaId, corpo) =>
      chamar({ method: 'PATCH', url: caminhoComId('/lojas', lojaId), data: corpo }),
    apagarLoja: async (lojaId) => chamar({ method: 'DELETE', url: caminhoComId('/lojas', lojaId) }),

    // Só admin: `{fabrica_morada, fabrica_lat, fabrica_lng}` (números); o PATCH
    // devolve os valores em vigor, e o 422 traz `campos` por chave.
    obterDefinicoes: () => chamar({ method: 'GET', url: '/definicoes' }),
    alterarDefinicoes: (corpo) => chamar({ method: 'PATCH', url: '/definicoes', data: corpo }),

    // `{mosaicos: {url, atribuicao}, alternativa: {url}, centro: {lat, lng}}`.
    obterConfigMapa: () => chamar({ method: 'GET', url: '/config' }),

    // Morada (Geoapify pelo servidor). A pesquisa → até 5 `{rotulo, morada,
    // codigo_postal, localidade, lat, lng}`; o ponto (`pontoDeBias`) só ordena
    // as sugestões. No seletor: `api: (texto, extra) => pesquisarMorada({
    // texto, ...(extra ?? {}) })`. A inversa → a sugestão ou `null` (422 fora
    // de Portugal continental). Sem chave ou com a Geoapify em baixo, 503
    // `morada_indisponivel`; sem rede, `sem_rede` (como todas).
    pesquisarMorada: (pedido) => chamar({
      method: 'GET',
      url: '/morada/pesquisa',
      params: semNulos({ texto: pedido?.texto, lat: pedido?.lat, lng: pedido?.lng }),
    }),
    moradaInversa: (ponto) => chamar({
      method: 'GET', url: '/morada/inversa', params: semNulos({ lat: ponto?.lat, lng: ponto?.lng }),
    }),
  };
}

export const clienteCrm = criarClienteCrm();

export const {
  obterEu, listarMembros, listarCandidatos, adicionarMembro, mudarPerfilMembro, retirarMembro,
  listarRegioes, criarRegiao, alterarRegiao, apagarRegiao,
  listarLojas, obterLoja, criarLoja, alterarLoja, apagarLoja,
  obterDefinicoes, alterarDefinicoes, obterConfigMapa, pesquisarMorada, moradaInversa,
} = clienteCrm;
