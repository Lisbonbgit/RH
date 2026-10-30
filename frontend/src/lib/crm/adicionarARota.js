// "Adicionar à rota" a partir do cartão de uma loja no mapa (desenho original §6.3: "Adicionar à rota
// (escolhe o dia)"; plano F3 T3.34, o diálogo da T3.40), sem DOM. Molde do `criarFabrica` (T2.30): uma
// `vista` congelada a cada mudança, entregue ao `aoMudarVista`; o `components/crm/DialogoAdicionarARota.js`
// só a desenha.
//
//  - `iniciar()` pede a lista das rotas (`listarRotas()` sem intervalo: o servidor usa hoje − 14 e
//    hoje + 60). O "hoje" é sempre o do servidor (o fuso do browser pode não ser o de Lisboa).
//  - O dia proposto (`diaPorOmissao`) é a primeira rota que o escritório ainda pode mudar a partir de hoje
//    (`rascunho` ou `planeada`; as do passado já vêm `concluida`), senão hoje. Os atalhos são essas rotas,
//    no máximo 5, com o dia e as paragens ativas ("Hoje · 5 paragens", "ter 13/10 · 8 paragens"). O campo
//    da data tem o `min` (hoje) e o `max` (hoje + 365, o horizonte do servidor); um dia passado escrito à
//    mão não se recusa aqui: o servidor dá o 409 `rota_fechada`, com a mensagem dele.
//  - O motivo vem pré-escolhido pela fase da loja (`motivoPorFase`, o mesmo do servidor) e pode mudar-se.
//  - "Adicionar" grava com `adicionarParagem(data, {loja_id, motivo})`, **sem** a versão: o cartão não a
//    conhece, e o servidor lê, verifica e tenta até 3 vezes (plano F3 §1 "Adicionar sem versão"). Um
//    pedido de cada vez: "A adicionar…" e os campos desligados até à resposta. Sem rede não se adiciona
//    (desenho original §6.2).
//  - Com sucesso, o aviso "Adicionada à rota de ter 13/10 (9 paragens)." com a ação "Abrir rota" (um toast,
//    `aoAvisar(texto, {acao, href, abrir})`). Quando a rota tinha horas calculadas e ficaram velhas, o aviso
//    acaba com "Abra a rota para recalcular as horas." (correção "T3.16 / T3.21 / T3.32", a parte da T3.40:
//    pelo cartão ninguém recalcula; o planeador recalcula sozinho quando a rota abre).
//  - Os erros mostram a mensagem do servidor (`ja_na_rota`, `rota_cheia`, `rota_fechada`, `rota_em_curso`,
//    `conflito`, a loja apagada, `sem_rede`…) no `alerta`; o 422 do dia e o do motivo ficam junto do campo.
// Os dados ficam como texto: o React escreve-os como texto.
import { MENSAGEM_ERRO_INESPERADO, MENSAGEM_SEM_REDE } from './api';
import { eDataValida, rotuloDia, somarDias } from './datas';
import { textoDoErro } from './ecraMapa';
import { MOTIVOS, motivoPorFase, rotuloMotivo } from './rota';

export const TITULO_ADICIONAR_A_ROTA = 'Adicionar à rota';
export const TEXTO_A_CARREGAR_DIAS = 'A carregar as rotas…';
export const TEXTO_DIA = 'Dia';
export const TEXTO_MOTIVO = 'Motivo';
export const TEXTO_ADICIONAR = 'Adicionar';
export const TEXTO_A_ADICIONAR = 'A adicionar…';
export const TEXTO_ABRIR_ROTA = 'Abrir rota';
export const TEXTO_FALTA_DIA = 'Escolha o dia.';
export const TEXTO_RECALCULAR_NA_ROTA = 'Abra a rota para recalcular as horas.';
// O diálogo do cartão (T3.40): o grupo dos atalhos, a ajuda do campo da data, "Cancelar" e "Tentar novamente".
export const TEXTO_DIAS_COM_ROTA = 'Dias com rota';
export const TEXTO_AJUDA_DIA = 'Num dia ainda sem rota, a rota começa com esta loja.';
export const TEXTO_CANCELAR = 'Cancelar';
export const TEXTO_TENTAR_DE_NOVO = 'Tentar novamente';

// No máximo 5 atalhos de dias (plano F3 T3.34).
export const ATALHOS_MAXIMO = 5;
// O último dia que o servidor aceita é hoje + 365 (`dominio.datas.MAXIMO_DIAS_FUTURO`; o teste lê-o).
export const MAXIMO_DIAS_FUTURO = 365;
// Os estados que o escritório ainda pode mudar (`dominio.rotas.ESTADOS_EDITAVEIS`; o teste lê-os).
export const ESTADOS_EDITAVEIS = Object.freeze(['rascunho', 'planeada']);

const OPCOES_MOTIVO = Object.freeze(MOTIVOS.map((valor) => Object.freeze({ valor, texto: rotuloMotivo(valor) })));

const eObjeto = (valor) => valor !== null && typeof valor === 'object' && !Array.isArray(valor);
const textoComConteudo = (valor) => typeof valor === 'string' && valor !== '';
const eContagem = (valor) => Number.isInteger(valor) && valor >= 0;

// --- Funções puras -------------------------------------------------------------------------------

// "sem paragens", "1 paragem", "9 paragens"; o que não é uma contagem dá null.
export function textoParagens(n) {
  if (!eContagem(n)) return null;
  if (n === 0) return 'sem paragens';
  return n === 1 ? '1 paragem' : `${n} paragens`;
}

// As linhas do `GET /rotas` que ainda se podem mudar, de hoje em diante, pela data e uma por dia.
function rotasEditaveis({ hoje, rotas } = {}) {
  if (!eDataValida(hoje) || !Array.isArray(rotas)) return [];
  const porDia = new Map();
  for (const rota of rotas) {
    if (!eObjeto(rota) || !eDataValida(rota.data) || rota.data < hoje) continue;
    if (!ESTADOS_EDITAVEIS.includes(rota.estado_efetivo) || porDia.has(rota.data)) continue;
    porDia.set(rota.data, rota);
  }
  return [...porDia.values()].sort((a, b) => (a.data < b.data ? -1 : 1));
}

// O dia proposto: a primeira rota que ainda se pode mudar a partir de hoje, senão hoje (null sem um hoje
// válido).
export function diaPorOmissao({ hoje, rotas } = {}) {
  if (!eDataValida(hoje)) return null;
  return rotasEditaveis({ hoje, rotas })[0]?.data ?? hoje;
}

// [{data, texto: 'ter 13/10 · 8 paragens', escolhido}], no máximo `ATALHOS_MAXIMO`.
export function atalhosDosDias({ hoje, rotas } = {}, escolhida = null) {
  return rotasEditaveis({ hoje, rotas }).slice(0, ATALHOS_MAXIMO).map((rota) => {
    const dia = rotuloDia(rota.data, hoje);
    const paragens = textoParagens(rota.paragens);
    return { data: rota.data, texto: paragens === null ? dia : `${dia} · ${paragens}`, escolhido: rota.data === escolhida };
  });
}

// O dia a meio de uma frase: "hoje", "amanhã", "ter 13/10" (o dia em AAAA-MM-DD sem um hoje válido).
function diaNaFrase(data, hoje) {
  const rotulo = rotuloDia(data, hoje);
  if (rotulo === 'Hoje' || rotulo === 'Amanhã') return rotulo.toLowerCase();
  return rotulo ?? data;
}

// As horas da rota ficaram velhas e há quem as recalcule (o planeador, com a chave do openrouteservice).
const horasPorRecalcular = (rota) => eObjeto(rota) && rota.calculo_disponivel === true && eObjeto(rota.calculo)
  && rota.calculo.atual !== true;

// "Adicionada à rota de ter 13/10 (9 paragens)." (+ "Abra a rota para recalcular as horas."), a partir da
// Rota que o servidor devolveu (as paragens são só as ativas). O hoje da resposta ganha ao da lista.
export function textoAdicionada(rota, { data, hoje } = {}) {
  const diaHoje = eDataValida(rota?.hoje) ? rota.hoje : hoje;
  const paragens = Array.isArray(rota?.paragens) ? textoParagens(rota.paragens.length) : null;
  const frase = `Adicionada à rota de ${diaNaFrase(data, diaHoje)}${paragens === null ? '' : ` (${paragens})`}.`;
  return horasPorRecalcular(rota) ? `${frase} ${TEXTO_RECALCULAR_NA_ROTA}` : frase;
}

// O botão "Adicionar": {ativo, texto, falta} (falta: porque não se pode, ou null).
export function estadoAdicionar({ aAdicionar, online, dataValida }) {
  if (aAdicionar) return { ativo: false, texto: TEXTO_A_ADICIONAR, falta: null };
  const desativado = (falta) => ({ ativo: false, texto: TEXTO_ADICIONAR, falta });
  if (!online) return desativado(MENSAGEM_SEM_REDE);
  if (!dataValida) return desativado(TEXTO_FALTA_DIA);
  return { ativo: true, texto: TEXTO_ADICIONAR, falta: null };
}

// O diálogo pode fechar-se ("Cancelar", o Escape, um toque fora)? Não enquanto a paragem se grava: o pedido já
// saiu, e fechar escondia o resultado (o aviso ou o erro).
export const podeFechar = (vista) => vista?.camposDesativados !== true;

// --- Ecrã ----------------------------------------------------------------------------------------

// criarAdicionarARota({api, loja, rede, base, navegar, aoMudarVista, aoAvisar, aoFocar})
//   → {vista, iniciar, tentarDeNovo, escolherDia, mudarMotivo, adicionar, destruir}
//  - api: {listarRotas, adicionarParagem} do lib/crm/api.js; loja: {id, nome, fase} (a do cartão; sem id é
//    um engano no código: TypeError); rede: o `criarEstadoRede(window, navigator)`;
//  - base: a casa do CRM (`/crm` ou `/admin/crm`); navegar(caminho): o `navigate` do React Router;
//  - aoAvisar(texto, {acao: 'Abrir rota', href, abrir}): o toast do sucesso (o `abrir()` navega para a
//    rota desse dia, também depois de o diálogo fechar); aoFocar(alvo): 'data' ou 'motivo', com o 422.
// vista: {estado: 'a_carregar'|'falha'|'pronto', titulo, loja: {id, nome}, falha: null | {mensagem, aTentar},
//         atalhos: [{data, texto, escolhido}], data, min, max, erroData, motivo, opcoesMotivo: [{valor, texto}],
//         erroMotivo, camposDesativados, alerta, semRede, adicionar: {ativo, texto, falta}}
//   — nova a cada mudança e congelada a fundo.
// Criar não pede nada: `iniciar()` pede a lista e ouve a rede; `destruir()` (o diálogo fechou) faz que as
// respostas que chegarem depois e a rede já não façam nada. O diálogo não deve fechar enquanto
// `camposDesativados` (a paragem a ser gravada).
export function criarAdicionarARota({
  api, loja, rede, base, navegar, aoMudarVista, aoAvisar, aoFocar,
}) {
  if (!textoComConteudo(loja?.id)) throw new TypeError('criarAdicionarARota: falta a loja (com o id).');
  const lojaVista = Object.freeze({ id: loja.id, nome: typeof loja.nome === 'string' ? loja.nome : '' });

  let hoje = null; // o do servidor (null até a lista chegar)
  let rotas = []; // as linhas do `GET /rotas`
  let falha = null; // a mensagem, se a lista não carregou
  let aCarregar = false;
  let data = null;
  let motivo = motivoPorFase(loja.fase);
  let erroData = null;
  let erroMotivo = null;
  let alerta = null;
  let aAdicionar = false;
  let iniciado = false;
  let ativo = true;
  let cancelarRede = () => {};

  const online = () => rede?.online() ?? true;
  const pronto = () => hoje !== null;

  function estadoAtual() {
    if (!pronto()) return { ativo: false, texto: TEXTO_ADICIONAR, falta: null };
    return estadoAdicionar({ aAdicionar, online: online(), dataValida: eDataValida(data) });
  }

  function montarVista() {
    let estado = 'a_carregar';
    if (pronto()) estado = 'pronto';
    else if (falha !== null) estado = 'falha';
    return Object.freeze({
      estado,
      titulo: TITULO_ADICIONAR_A_ROTA,
      loja: lojaVista,
      falha: estado === 'falha' ? Object.freeze({ mensagem: falha, aTentar: aCarregar }) : null,
      atalhos: Object.freeze(atalhosDosDias({ hoje, rotas }, data).map((atalho) => Object.freeze(atalho))),
      data,
      min: hoje,
      // Sem o hoje do servidor, o `somarDias` dá null.
      max: somarDias(hoje, MAXIMO_DIAS_FUTURO),
      erroData,
      motivo,
      opcoesMotivo: OPCOES_MOTIVO,
      erroMotivo,
      camposDesativados: aAdicionar,
      alerta,
      semRede: !online(),
      adicionar: Object.freeze(estadoAtual()),
    });
  }

  let vista = montarVista();

  function atualizar() {
    vista = montarVista();
    aoMudarVista?.(vista);
  }

  // --- Carregar ---

  async function carregar() {
    if (!ativo || aCarregar || pronto()) return;
    aCarregar = true;
    atualizar();
    let lista;
    try {
      lista = await api.listarRotas();
    } catch (erro) {
      aCarregar = false;
      if (!ativo) return;
      falha = textoDoErro(erro);
      atualizar();
      return;
    }
    aCarregar = false;
    if (!ativo) return;
    if (eDataValida(lista?.hoje)) {
      hoje = lista.hoje;
      rotas = Array.isArray(lista.rotas) ? lista.rotas : [];
      data = diaPorOmissao({ hoje, rotas });
    } else {
      falha = MENSAGEM_ERRO_INESPERADO;
    }
    atualizar();
  }

  // --- Adicionar ---

  function mostrarErro(erro) {
    if (erro?.codigo === 'validacao') {
      const campos = eObjeto(erro.campos) ? erro.campos : {};
      const doDia = textoComConteudo(campos.data) ? campos.data : null;
      const doMotivo = textoComConteudo(campos.motivo) ? campos.motivo : null;
      if (doDia !== null || doMotivo !== null) {
        erroData = doDia;
        erroMotivo = doMotivo;
        atualizar();
        aoFocar?.(doDia !== null ? 'data' : 'motivo');
        return;
      }
      // O de outro campo (a loja): a mensagem dele.
      alerta = Object.values(campos).find(textoComConteudo) ?? textoDoErro(erro);
      atualizar();
      return;
    }
    alerta = textoDoErro(erro);
    atualizar();
  }

  // A linha da lista desse dia passa a ser a da rota que voltou (a contagem nova; um dia novo ganha o atalho).
  function guardarNaLista(dia, rota) {
    if (!eObjeto(rota) || !Array.isArray(rota.paragens)) return;
    const linha = { data: dia, estado_efetivo: rota.estado_efetivo, paragens: rota.paragens.length };
    rotas = [...rotas.filter((r) => r?.data !== dia), linha];
  }

  async function adicionar() {
    if (!ativo || !estadoAtual().ativo) return;
    const dia = data;
    aAdicionar = true;
    alerta = null;
    erroData = null;
    erroMotivo = null;
    atualizar();
    let rota;
    try {
      rota = await api.adicionarParagem(dia, { loja_id: loja.id, motivo });
    } catch (erro) {
      aAdicionar = false;
      if (!ativo) return;
      mostrarErro(erro);
      return;
    }
    aAdicionar = false;
    if (!ativo) return;
    guardarNaLista(dia, rota);
    atualizar();
    const caminho = `${base}/rotas/${dia}`;
    aoAvisar?.(textoAdicionada(rota, { data: dia, hoje }), Object.freeze({
      acao: TEXTO_ABRIR_ROTA,
      href: caminho,
      abrir: () => navegar?.(caminho),
    }));
  }

  return {
    get vista() {
      return vista;
    },
    iniciar() {
      if (!ativo || iniciado) return;
      iniciado = true;
      cancelarRede = rede?.aoMudar((ligado) => {
        // Sem rede o "Adicionar" desliga-se; quando volta, a lista que falhou pede-se outra vez.
        atualizar();
        if (ligado) carregar();
      }) ?? (() => {});
      carregar();
    },
    // "Tentar novamente" (a lista não carregou); um toque, um pedido.
    tentarDeNovo() {
      if (falha !== null) carregar();
    },
    // Um atalho ou o campo da data (o valor do `<input type="date">`, '' quando está vazio).
    escolherDia(valor) {
      if (!ativo || !pronto() || aAdicionar || typeof valor !== 'string') return;
      data = valor;
      erroData = null;
      alerta = null;
      atualizar();
    },
    mudarMotivo(valor) {
      if (!ativo || aAdicionar || !MOTIVOS.includes(valor)) return;
      motivo = valor;
      erroMotivo = null;
      atualizar();
    },
    adicionar,
    destruir() {
      ativo = false;
      cancelarRede();
    },
  };
}
