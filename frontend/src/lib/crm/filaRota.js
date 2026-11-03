// A fila das gravações da rota de um dia (F3 / T3.30): um pedido de cada vez, as alterações juntas e a
// versão em vigor. Módulo puro, sem DOM nem rede: o `enviar` é injetado (o planeador usa o
// `enviarPelaApi`, sobre o `api.js` da T3.29).
//
// Cada ação do planeador grava logo (plano F3 §1 "Gravação") e leva a `versao` da rota: o servidor dá 409
// `conflito` se outra pessoa gravou entretanto. Duas gravações ao mesmo tempo dariam conflito uma à outra,
// por isso:
//   - só há **um pedido em curso**; os outros esperam pela ordem em que foram pedidos;
//   - cada pedido sai com a **versão da última resposta** (lida quando sai, não quando foi pedido);
//   - os `alterar` à espera **seguidos** juntam-se num só PATCH (`juntarAlteracoes`): menos pedidos e
//     nenhum conflito consigo próprio. Um `adicionar`, um `otimizar` ou um `recalcular` pelo meio separa-os
//     (a alteração seguinte pode ser da loja que vai ser adicionada);
//   - `adicionar` e `otimizar` nunca se juntam; os `recalcular` à espera ficam um só, **no fim** da fila
//     (as horas saem depois de tudo o que está à espera; plano F3 §9, R7: o limite de pedidos do ORS);
//   - um 409 da rota inteira (`CODIGOS_QUE_PARAM`) recusa o pedido em curso e todos os pendentes com esse
//     erro, e a fila fica **parada** até `retomar(versao)` (o "Recarregar" do planeador); enquanto está
//     parada, cada pedido novo é recusado logo com o mesmo erro;
//   - outro erro (422, 503, sem rede, os 409 de uma paragem: `ja_na_rota`, `rota_cheia`) recusa só esse
//     pedido, e os seguintes continuam com a versão que estava em vigor.
//
// Os getters (`vazia`, `ocupada`, `parada`, `erro`, `versao`, `alteracoesPorConfirmar`) e o `tem(tipo)`
// já mostram o estado seguinte quando corre a continuação de um pedido: a fila trata a resposta (a versão
// nova e o pedido seguinte a sair) antes de resolver as promessas de quem pediu.

export const TIPOS_DE_PEDIDO = Object.freeze(['alterar', 'adicionar', 'recalcular', 'otimizar']);

// Os 409 da rota inteira (plano F3 §4): outra pessoa gravou, o motorista já começou, o dia já passou.
// Os 409 de uma paragem (`ja_na_rota`, `rota_cheia`) não param a fila.
export const CODIGOS_QUE_PARAM = Object.freeze(['conflito', 'rota_em_curso', 'rota_fechada']);

// --- Pequenas leituras seguras -------------------------------------------------------------------

const temProprio = (objeto, chave) => Object.prototype.hasOwnProperty.call(objeto, chave);
const eObjeto = (valor) => valor !== null && typeof valor === 'object' && !Array.isArray(valor);

// O corpo tal como vai no pedido (em JSON): uma cópia sem o que o JSON deixa cair (as chaves herdadas,
// os valores `undefined`, as funções). Um corpo que não é um objeto conta como vazio.
function comoVaiNoPedido(corpo) {
  if (!eObjeto(corpo)) return {};
  const lido = JSON.parse(JSON.stringify(corpo));
  return eObjeto(lido) ? lido : {};
}

function congelarAFundo(valor) {
  if (valor !== null && typeof valor === 'object' && !Object.isFrozen(valor)) {
    Object.values(valor).forEach(congelarAFundo);
    Object.freeze(valor);
  }
  return valor;
}

// Uma versão da rota: um inteiro ≥ 1, ou `null` (a rota virtual, que ainda não existe).
const eVersao = (valor) => Number.isInteger(valor) && valor >= 1;

function versaoOuErro(valor, onde) {
  if (valor === null || eVersao(valor)) return valor;
  throw new TypeError(`${onde}: a versão da rota é um inteiro ≥ 1 ou null.`);
}

// --- Juntar alterações ---------------------------------------------------------------------------

// As alterações de uma paragem, uma depois da outra: a última vence campo a campo. Um motivo novo sem
// tempo deita fora o tempo que estava à espera: pedido a pedido, o servidor punha o padrão do motivo
// novo por cima dele (`crm/rotas.py`). Umas alterações que não são um objeto vencem inteiras (o
// servidor recusa-as com 422).
function juntarCampos(antes, depois) {
  if (!eObjeto(antes) || !eObjeto(depois)) return depois;
  const juntos = { ...antes, ...depois };
  if (temProprio(depois, 'motivo') && !temProprio(depois, 'tempo_servico_min')) delete juntos.tempo_servico_min;
  return juntos;
}

function juntarParagens(antes, depois) {
  if (!eObjeto(antes) || !eObjeto(depois)) return depois;
  const juntas = { ...antes };
  for (const [id, campos] of Object.entries(depois)) {
    juntas[id] = temProprio(antes, id) ? juntarCampos(antes[id], campos) : campos;
  }
  return juntas;
}

// A união das listas, sem repetidos e pela ordem em que chegaram; o que não é uma lista conta como vazio.
function uniao(...listas) {
  const ids = [];
  for (const lista of listas) {
    if (!Array.isArray(lista)) continue;
    for (const id of lista) if (!ids.includes(id)) ids.push(id);
  }
  return ids;
}

/**
 * Dois corpos do `PATCH /rotas/{data}` num só, como se o servidor recebesse `a` e depois `b`:
 *   - as definições do dia (`hora_saida`, `hora_regresso_limite`, `inicio`, `fim`, `evitar_portagens`),
 *     a `ordem`, o `estado` e qualquer outra chave: a última vence;
 *   - as `paragens` juntam-se por id e por campo (`juntarCampos`);
 *   - `retirar` é a união, e o retirar ganha: esses ids saem da `ordem` e das `paragens`, venham antes ou
 *     depois (correção "T3.4 / T3.20"; o servidor recusava uma paragem retirada e alterada no mesmo PATCH);
 *   - a `versao` nunca passa: é a fila que põe a que está em vigor quando o pedido sai.
 * Lê os dois como vão no pedido e devolve um corpo novo, sem mexer nos que recebe.
 */
export function juntarAlteracoes(a, b) {
  const antes = comoVaiNoPedido(a);
  const depois = comoVaiNoPedido(b);
  const junta = { ...antes, ...depois };
  delete junta.versao;

  if (temProprio(antes, 'paragens') && temProprio(depois, 'paragens')) {
    junta.paragens = juntarParagens(antes.paragens, depois.paragens);
  }
  if (temProprio(antes, 'retirar') || temProprio(depois, 'retirar')) {
    junta.retirar = uniao(antes.retirar, depois.retirar);
    const retirados = new Set(junta.retirar);
    if (Array.isArray(junta.ordem)) junta.ordem = junta.ordem.filter((id) => !retirados.has(id));
    if (eObjeto(junta.paragens)) {
      for (const id of retirados) delete junta.paragens[id];
    }
  }
  return junta;
}

// --- O enviar sobre a API ------------------------------------------------------------------------

/**
 * O `enviar` da fila sobre o cliente do CRM (`api.js`, T3.29), para o dia `data`:
 *   - `alterar` → `alterarRota(data, {...corpo, versao})`;
 *   - `adicionar` → `adicionarParagem(data, {loja_id, motivo, versao})` (`versao: null` numa rota virtual);
 *   - `recalcular` → `recalcularHoras(data, versao)`; `otimizar` → `otimizarRota(data, versao)`.
 * Um tipo desconhecido dá uma promessa recusada com `TypeError`, sem chamar a API.
 */
export function enviarPelaApi(api, data) {
  return ({ tipo, corpo, versao }) => {
    if (tipo === 'alterar') return api.alterarRota(data, { ...corpo, versao });
    if (tipo === 'adicionar') return api.adicionarParagem(data, { loja_id: corpo?.loja_id, motivo: corpo?.motivo, versao });
    if (tipo === 'recalcular') return api.recalcularHoras(data, versao);
    if (tipo === 'otimizar') return api.otimizarRota(data, versao);
    return Promise.reject(new TypeError(`enviarPelaApi: pedido desconhecido (${String(tipo)}).`));
  };
}

// --- A fila --------------------------------------------------------------------------------------

/**
 * `criarFilaRota({enviar, versao})`: a fila das gravações de uma rota.
 *   - `enviar({tipo, corpo, versao})` → a promessa da Rota que o servidor devolveu (ou a própria Rota);
 *     o pedido que recebe está congelado. `corpo`: no `alterar`, as alterações juntas; no `adicionar`,
 *     `{loja_id, motivo}`; no `recalcular` e no `otimizar`, `null`.
 *   - `versao`: a da rota lida (`null` numa rota virtual; em falta também é `null`).
 * Devolve, congelado: `alterar(corpo)`, `adicionar({loja_id, motivo})`, `recalcular()` e `otimizar()`
 * (cada um → a promessa da Rota do pedido onde foi parar; os `alterar` juntos e os `recalcular` juntos
 * recebem a mesma), `retomar(versao)`, `tem(tipo)` e os getters.
 */
export function criarFilaRota({ enviar, versao = null } = {}) {
  if (typeof enviar !== 'function') throw new TypeError('criarFilaRota: falta o enviar.');
  let versaoAtual = versaoOuErro(versao, 'criarFilaRota');
  let emCurso = null;
  const pendentes = [];
  let erroQueParou = null;

  function avancar() {
    if (emCurso !== null || pendentes.length === 0) return;
    const pedido = pendentes.shift();
    emCurso = pedido;
    let resposta;
    try {
      resposta = Promise.resolve(enviar(Object.freeze({ tipo: pedido.tipo, corpo: pedido.corpo, versao: versaoAtual })));
    } catch (erro) {
      resposta = Promise.reject(erro);
    }
    resposta.then(
      (rota) => respondeu(pedido, rota),
      (erro) => falhou(pedido, erro),
    );
  }

  function respondeu(pedido, rota) {
    emCurso = null;
    if (eVersao(rota?.versao)) versaoAtual = rota.versao;
    avancar();
    pedido.esperas.forEach(({ resolver }) => resolver(rota));
  }

  function falhou(pedido, erro) {
    emCurso = null;
    if (CODIGOS_QUE_PARAM.includes(erro?.codigo)) {
      erroQueParou = erro;
      const recusados = [pedido, ...pendentes.splice(0)];
      recusados.forEach(({ esperas }) => esperas.forEach(({ rejeitar }) => rejeitar(erro)));
      return;
    }
    avancar();
    pedido.esperas.forEach(({ rejeitar }) => rejeitar(erro));
  }

  // Põe o pedido na fila (ou junta-o a um que já lá está) e devolve a promessa da resposta.
  function pedir(tipo, corpo) {
    if (erroQueParou !== null) return Promise.reject(erroQueParou);
    return new Promise((resolver, rejeitar) => {
      const espera = { resolver, rejeitar };
      const ultimo = pendentes[pendentes.length - 1];
      const recalculo = tipo === 'recalcular' ? pendentes.findIndex((p) => p.tipo === 'recalcular') : -1;
      if (tipo === 'alterar' && ultimo?.tipo === 'alterar') {
        ultimo.corpo = congelarAFundo(juntarAlteracoes(ultimo.corpo, corpo));
        ultimo.esperas.push(espera);
      } else if (recalculo >= 0) {
        const [juntado] = pendentes.splice(recalculo, 1);
        juntado.esperas.push(espera);
        pendentes.push(juntado);
      } else {
        pendentes.push({ tipo, corpo: congelarAFundo(corpo), esperas: [espera] });
      }
      avancar();
    });
  }

  // O corpo de um `adicionar`, como vai no pedido e sem a versão (é a fila que a põe).
  function corpoAdicionar(corpo) {
    const lido = comoVaiNoPedido(corpo);
    delete lido.versao;
    return lido;
  }

  const todos = () => (emCurso === null ? [...pendentes] : [emCurso, ...pendentes]);

  return Object.freeze({
    alterar: (corpo) => pedir('alterar', juntarAlteracoes({}, corpo)),
    adicionar: (corpo) => pedir('adicionar', corpoAdicionar(corpo)),
    recalcular: () => pedir('recalcular', null),
    otimizar: () => pedir('otimizar', null),

    // A fila volta a andar com a versão da rota relida (um inteiro ≥ 1 ou null; senão, TypeError e nada
    // muda). Parada, a fila já não tem nada à espera: o pedido seguinte sai logo.
    retomar(nova) {
      versaoAtual = versaoOuErro(nova, 'retomar');
      erroQueParou = null;
    },

    // Há um pedido deste tipo em curso ou à espera?
    tem: (tipo) => todos().some((pedido) => pedido.tipo === tipo),

    get vazia() {
      return emCurso === null && pendentes.length === 0;
    },
    get ocupada() {
      return emCurso !== null;
    },
    get parada() {
      return erroQueParou !== null;
    },
    // O erro que parou a fila, ou null.
    get erro() {
      return erroQueParou;
    },
    get versao() {
      return versaoAtual;
    },
    // Os corpos dos `alterar` em curso e à espera, pela ordem (congelados): a visão otimista do planeador
    // aplica-os por cima da última rota do servidor (`rota.aplicarLocalmente`). Um pedido recusado sai daqui.
    get alteracoesPorConfirmar() {
      return Object.freeze(todos().filter((pedido) => pedido.tipo === 'alterar').map((pedido) => pedido.corpo));
    },
  });
}
