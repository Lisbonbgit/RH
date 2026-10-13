// Definições › Regiões (desenho original §6.7; plano T2.30), sem DOM: as
// regiões que filtram as lojas no mapa. Porta de
// public/assets/js/componentes/definicoes-regioes.js do CRM autónomo; como os
// membros da T2.29, o que o autónomo escrevia no DOM é uma `vista` congelada,
// entregue ao `aoMudarVista`, e o `pages/crm/DefinicoesRegioes.js` só a
// desenha (correções "T2.30 (Regiões — subir/descer) e T2.9" e "T2.26 / T2.27
// / T2.29 / T2.30 (componentes Sem Jest)").
//
// As regiões chegam do GET /api/crm/regioes pela ordem, depois pelo nome (sem
// maiúsculas nem acentos) e pelo id; os filtros do mapa e o campo Região das
// lojas mostram-nas por essa ordem.
//  - Adicionar envia {nome, ordem: proximaOrdem(lista)}: a região nova vai para
//    o fim (o POST sem ordem gravava 0).
//  - Subir e Descer trocam a região com a vizinha: a lista muda logo e a ordem
//    nova grava-se toda (0, 1, 2…), um PATCH {ordem} de cada vez, só das que
//    mudaram (`reordenarRegioes`). Enquanto grava (ou a lista se pede outra
//    vez), os outros Subir/Descer não fazem nada (a página usa aria-disabled,
//    para o foco ficar no botão tocado). Se um PATCH falhar, para aí, avisa e
//    a lista volta a pedir-se ao servidor.
//  - Mudar o nome abre o campo com o nome atual; um nome repetido (409
//    `regiao_repetida`) ou vazio (422) mostra a mensagem do servidor junto ao
//    campo. Enquanto grava, o campo e o Cancelar não mexem.
//  - Apagar pede confirmação (Cancelar primeiro, a escolha que não apaga); uma
//    região com lojas (409 `regiao_com_lojas`) não se apaga: a mensagem do
//    servidor fica nessa região.
//  - Uma região que outra pessoa apagou entretanto (404) dá um aviso de erro e
//    a lista volta a pedir-se.
//  - Os avisos de sucesso ("Região adicionada", "Nome guardado", "Ordem
//    guardada", "Região apagada") e os de erro sem sítio próprio são toasts
//    (`aoAvisar` / `aoAvisarErro`), como nos membros.
// Os nomes ficam como texto: o React escreve-os como texto.
import { textoDoErro } from './ecraMapa';
import { eUuid } from './ids';

export const TITULO_REGIOES = 'Regiões';
export const TEXTO_DESCRICAO_REGIOES = 'Os filtros do mapa e o campo Região das lojas mostram-nas por esta ordem.';
export const TEXTO_A_CARREGAR_REGIOES = 'A carregar as regiões…';
export const TEXTO_SEM_REGIOES = 'Ainda não há regiões.';
export const TEXTO_NOVA_REGIAO = 'Nova região';
export const TEXTO_ADICIONAR = 'Adicionar';
export const TEXTO_A_ADICIONAR = 'A adicionar…';
export const TEXTO_SUBIR = 'Subir';
export const TEXTO_DESCER = 'Descer';
export const TEXTO_MUDAR_NOME = 'Mudar o nome';
export const TEXTO_APAGAR = 'Apagar';
export const TEXTO_A_APAGAR = 'A apagar…';
export const TEXTO_GUARDAR = 'Guardar';
export const TEXTO_A_GUARDAR = 'A guardar…';
export const TEXTO_CANCELAR = 'Cancelar';
export const TEXTO_APAGAR_REGIAO_AVISO = 'Só se apagam regiões sem lojas.';
export const TEXTO_REGIAO_ADICIONADA = 'Região adicionada';
export const TEXTO_NOME_GUARDADO = 'Nome guardado';
export const TEXTO_ORDEM_GUARDADA = 'Ordem guardada';
export const TEXTO_REGIAO_APAGADA = 'Região apagada';
export const RESPOSTA_APAGAR_REGIAO = 'apagar';

// O tamanho do nome no servidor (`backend/crm/dominio/regioes.py::NOME_MAXIMO`, a coluna do autónomo).
export const NOME_MAXIMO_REGIAO = 100;

const SEM_LINHAS = Object.freeze([]);

// --- Funções puras -------------------------------------------------------------------------------

// Uma região do GET /api/crm/regioes: {id (uuid em texto), nome (texto), ordem (inteiro)}.
export function regiaoValida(regiao) {
  return regiao !== null && typeof regiao === 'object' && eUuid(regiao.id) && typeof regiao.nome === 'string'
    && Number.isSafeInteger(regiao.ordem);
}

// Como o servidor (`ordem`, `chave_comparacao(nome)`, `id`): sem distinguir maiúsculas nem acentos, e o id
// (texto) desempata.
const colador = new Intl.Collator('pt', { sensitivity: 'base' });

function compararIds(a, b) {
  if (a === b) return 0;
  return a < b ? -1 : 1;
}

export function ordenarRegioes(lista) {
  return [...lista].sort((a, b) => a.ordem - b.ordem || colador.compare(a.nome, b.nome) || compararIds(a.id, b.id));
}

// Troca a região `id` com a vizinha (direcao -1 sobe, 1 desce) e numera a lista toda (0, 1, 2…).
// → {lista (nova, com as ordens novas), alteracoes: [{id, ordem}] (só as que mudaram, pela ordem nova)}, ou null
// se não se pode mexer (a primeira não sobe, a última não desce, ou a região não está na lista).
export function reordenarRegioes(lista, id, direcao) {
  const de = lista.findIndex((regiao) => regiao.id === id);
  const para = de + direcao;
  if (de === -1 || (direcao !== -1 && direcao !== 1) || para < 0 || para >= lista.length) return null;
  const nova = lista.map((regiao) => ({ ...regiao }));
  [nova[de], nova[para]] = [nova[para], nova[de]];
  const alteracoes = [];
  nova.forEach((regiao, posicao) => {
    if (regiao.ordem === posicao) return;
    regiao.ordem = posicao;
    alteracoes.push({ id: regiao.id, ordem: posicao });
  });
  return { lista: nova, alteracoes };
}

// A ordem de uma região nova: depois da última.
export function proximaOrdem(lista) {
  return lista.length === 0 ? 0 : Math.max(...lista.map((regiao) => regiao.ordem)) + 1;
}

// O que o leitor de ecrã lê em cada ação de uma região (o texto do botão não diz qual é a região).
export function rotulosRegiao(nome) {
  return Object.freeze({
    subir: `${TEXTO_SUBIR} ${nome}`,
    descer: `${TEXTO_DESCER} ${nome}`,
    mudar: `${TEXTO_MUDAR_NOME} de ${nome}`,
    apagar: `${TEXTO_APAGAR} ${nome}`,
    novoNome: `Novo nome de ${nome}`,
  });
}

// A pergunta do Apagar: a primeira escolha é a que não apaga (o foco vai para ela).
export function perguntaApagarRegiao(regiao) {
  return Object.freeze({
    pergunta: `Apagar a região ${regiao.nome}?`,
    aviso: TEXTO_APAGAR_REGIAO_AVISO,
    botoes: Object.freeze([
      Object.freeze({ texto: TEXTO_CANCELAR, valor: null, variante: 'normal' }),
      Object.freeze({ texto: 'Sim, apagar', valor: RESPOSTA_APAGAR_REGIAO, variante: 'perigo' }),
    ]),
  });
}

const listaDeRegioes = (resposta) => ordenarRegioes((Array.isArray(resposta) ? resposta : []).filter(regiaoValida));

// A mensagem de um erro para um campo: a do campo no 422 (`nome` ou `ordem`), ou a do erro.
function mensagemDoCampo(erro, campos) {
  const doCampo = campos.map((campo) => erro?.campos?.[campo]).find((texto) => typeof texto === 'string' && texto !== '');
  return doCampo ?? textoDoErro(erro);
}

// --- Ecrã ----------------------------------------------------------------------------------------

// criarRegioes({api, rede, aoMudarVista, aoAvisar, aoAvisarErro, aoFocar})
//   → {vista, iniciar, tentarDeNovo, mudarNova, adicionar, subir, descer, abrirEdicao, mudarNome, guardarNome,
//      cancelarEdicao, pedirApagar, responderApagar, destruir}
//  - api: {listarRegioes, criarRegiao, alterarRegiao, apagarRegiao} do lib/crm/api.js; rede: o
//    `criarEstadoRede(window, navigator)`;
//  - aoAvisar(texto) / aoAvisarErro(texto): os toasts; aoFocar(alvo): 'titulo' (depois de apagar), 'nova' (o
//    campo "Nova região") ou {id, alvo: 'subir' | 'descer' | 'mudar' | 'nome'} (um botão ou o campo de uma
//    região: ao mudar uma região de sítio, a página perde o foco do botão tocado).
// vista: {estado: 'a_carregar'|'falha'|'pronto', falha: null | {mensagem, aTentar}, vazio,
//         linhas: [{id, nome, podeSubir, podeDescer, ocupada, rotulos, edicao: null | {valor, erro, aGuardar,
//                   botao: {ativo, texto}}, erro, apagar: {ativo, texto}}],
//         nova: {valor, erro, botao: {ativo, texto}}, pergunta: null | {pergunta, aviso, botoes}}
//   — nova a cada mudança e congelada. Com a lista à vista, uma falha ao pedi-la outra vez fica em `falha`
//   (com "Tentar novamente") por cima da lista, e `estado` continua 'pronto'.
// Criar não pede nada: `iniciar()` pede a lista e ouve a rede; `destruir()` (o ecrã saiu) faz que as respostas
// que chegarem depois, a rede e as respostas à pergunta já não façam nada.
export function criarRegioes({
  api, rede, aoMudarVista, aoAvisar, aoAvisarErro, aoFocar,
}) {
  let regioes = [];
  let carregada = false;
  let falha = null; // a mensagem, se o último pedido da lista falhou
  let aCarregar = false;
  let aMover = false;
  let nova = { valor: '', erro: null };
  let aAdicionar = false;
  let edicao = null; // {id, valor, erro, aGuardar}: o nome que se está a mudar (uma região de cada vez)
  const aApagar = new Set(); // ids das regiões a apagar
  const errosApagar = new Map(); // id → a mensagem do servidor (ex.: a região tem lojas)
  let pergunta = null; // a região da pergunta "Apagar a região X?", enquanto está aberta
  let iniciado = false;
  let ativo = true;
  let cancelarRede = () => {};

  const regiaoCom = (id) => regioes.find((regiao) => regiao.id === id) ?? null;

  function vistaEdicao(regiao) {
    if (edicao === null || edicao.id !== regiao.id) return null;
    return Object.freeze({
      valor: edicao.valor,
      erro: edicao.erro,
      aGuardar: edicao.aGuardar,
      botao: Object.freeze({ ativo: !edicao.aGuardar, texto: edicao.aGuardar ? TEXTO_A_GUARDAR : TEXTO_GUARDAR }),
    });
  }

  function vistaLinha(regiao, posicao) {
    const aApagarEsta = aApagar.has(regiao.id);
    return Object.freeze({
      id: regiao.id,
      nome: regiao.nome,
      podeSubir: posicao > 0,
      podeDescer: posicao < regioes.length - 1,
      ocupada: aMover || aCarregar,
      rotulos: rotulosRegiao(regiao.nome),
      edicao: vistaEdicao(regiao),
      erro: errosApagar.get(regiao.id) ?? null,
      apagar: Object.freeze({ ativo: !aApagarEsta, texto: aApagarEsta ? TEXTO_A_APAGAR : TEXTO_APAGAR }),
    });
  }

  function montarVista() {
    let estado = 'a_carregar';
    if (carregada) estado = 'pronto';
    else if (falha !== null) estado = 'falha';
    return Object.freeze({
      estado,
      falha: falha === null ? null : Object.freeze({ mensagem: falha, aTentar: aCarregar }),
      vazio: carregada && regioes.length === 0,
      linhas: carregada ? Object.freeze(regioes.map(vistaLinha)) : SEM_LINHAS,
      nova: Object.freeze({
        valor: nova.valor,
        erro: nova.erro,
        botao: Object.freeze({
          ativo: carregada && !aAdicionar,
          texto: aAdicionar ? TEXTO_A_ADICIONAR : TEXTO_ADICIONAR,
        }),
      }),
      pergunta: pergunta === null ? null : perguntaApagarRegiao(pergunta),
    });
  }

  let vista = montarVista();

  function atualizar() {
    vista = montarVista();
    aoMudarVista?.(vista);
  }

  // --- Carregar ---

  async function carregar() {
    if (!ativo || aCarregar) return;
    aCarregar = true;
    atualizar();
    let resposta;
    try {
      resposta = await api.listarRegioes();
    } catch (erro) {
      aCarregar = false;
      if (!ativo) return;
      falha = textoDoErro(erro);
      atualizar();
      return;
    }
    aCarregar = false;
    if (!ativo) return;
    regioes = listaDeRegioes(resposta);
    carregada = true;
    falha = null;
    // O que era de regiões que já não estão na lista sai com elas.
    if (edicao !== null && regiaoCom(edicao.id) === null) edicao = null;
    for (const id of [...errosApagar.keys()]) {
      if (regiaoCom(id) === null) errosApagar.delete(id);
    }
    atualizar();
  }

  // --- Adicionar ---

  async function adicionar() {
    if (!ativo || !carregada || aAdicionar) return;
    const corpo = { nome: nova.valor, ordem: proximaOrdem(regioes) };
    aAdicionar = true;
    nova = { ...nova, erro: null };
    atualizar();
    let criada;
    try {
      criada = await api.criarRegiao(corpo);
    } catch (erro) {
      aAdicionar = false;
      if (!ativo) return;
      nova = { ...nova, erro: mensagemDoCampo(erro, ['nome', 'ordem']) };
      atualizar();
      aoFocar?.('nova');
      return;
    }
    aAdicionar = false;
    if (!ativo) return;
    const valida = regiaoValida(criada);
    if (valida) regioes = ordenarRegioes([...regioes.filter((regiao) => regiao.id !== criada.id), criada]);
    // Pronto para a seguinte.
    nova = { valor: '', erro: null };
    atualizar();
    aoAvisar?.(TEXTO_REGIAO_ADICIONADA);
    aoFocar?.('nova');
    // O servidor gravou, mas a resposta não é uma região: a lista vem do servidor.
    if (!valida) carregar();
  }

  // --- Subir e descer ---

  async function mover(id, direcao) {
    if (!ativo || !carregada || aMover || aCarregar) return;
    const resultado = reordenarRegioes(regioes, id, direcao);
    if (!resultado) return;
    aMover = true;
    regioes = resultado.lista;
    atualizar();
    // O foco fica no botão tocado; no topo (ou no fundo) ele fica desativado e o foco passa para o outro.
    const posicao = regioes.findIndex((regiao) => regiao.id === id);
    const naPonta = direcao === -1 ? posicao === 0 : posicao === regioes.length - 1;
    const tocado = direcao === -1 ? 'subir' : 'descer';
    const outro = direcao === -1 ? 'descer' : 'subir';
    aoFocar?.({ id, alvo: naPonta ? outro : tocado });

    for (const alteracao of resultado.alteracoes) {
      try {
        await api.alterarRegiao(alteracao.id, { ordem: alteracao.ordem });
      } catch (erro) {
        aMover = false;
        if (!ativo) return;
        aoAvisarErro?.(mensagemDoCampo(erro, ['ordem']));
        // A ordem no servidor ficou a meio: mostra-se a que lá está.
        carregar();
        return;
      }
      if (!ativo) return;
    }
    aMover = false;
    atualizar();
    if (resultado.alteracoes.length > 0) aoAvisar?.(TEXTO_ORDEM_GUARDADA);
  }

  // --- Mudar o nome ---

  async function guardarNome() {
    if (!ativo || edicao === null || edicao.aGuardar) return;
    const { id } = edicao;
    const corpo = { nome: edicao.valor };
    edicao = { ...edicao, erro: null, aGuardar: true };
    atualizar();
    let alterada;
    try {
      alterada = await api.alterarRegiao(id, corpo);
    } catch (erro) {
      if (!ativo) return;
      if (erro?.codigo === 'nao_encontrado') {
        // Outra pessoa apagou-a entretanto: a lista vem outra vez (e a região sai dela).
        edicao = null;
        atualizar();
        aoAvisarErro?.(textoDoErro(erro));
        carregar();
        return;
      }
      if (edicao?.id === id) edicao = { ...edicao, aGuardar: false, erro: mensagemDoCampo(erro, ['nome']) };
      atualizar();
      aoFocar?.({ id, alvo: 'nome' });
      return;
    }
    if (!ativo) return;
    const valida = typeof alterada?.nome === 'string';
    if (valida) {
      // Só o nome: a ordem desta lista pode já ser mais recente do que a da resposta.
      regioes = ordenarRegioes(regioes.map((regiao) => (regiao.id === id ? { ...regiao, nome: alterada.nome } : regiao)));
    }
    if (edicao?.id === id) edicao = null;
    atualizar();
    aoAvisar?.(TEXTO_NOME_GUARDADO);
    aoFocar?.({ id, alvo: 'mudar' });
    if (!valida) carregar();
  }

  // --- Apagar ---

  async function apagar(regiao) {
    const { id } = regiao;
    aApagar.add(id);
    atualizar();
    try {
      await api.apagarRegiao(id);
    } catch (erro) {
      aApagar.delete(id);
      if (!ativo) return;
      if (erro?.codigo === 'nao_encontrado') {
        atualizar();
        aoAvisarErro?.(textoDoErro(erro));
        carregar();
        return;
      }
      errosApagar.set(id, textoDoErro(erro));
      atualizar();
      return;
    }
    aApagar.delete(id);
    if (!ativo) return;
    regioes = regioes.filter((r) => r.id !== id);
    errosApagar.delete(id);
    if (edicao?.id === id) edicao = null;
    atualizar();
    aoAvisar?.(TEXTO_REGIAO_APAGADA);
    // A região saiu (e o botão com ela): o foco fica no título da secção.
    aoFocar?.('titulo');
  }

  return {
    get vista() {
      return vista;
    },
    iniciar() {
      if (!ativo || iniciado) return;
      iniciado = true;
      // A rede voltou: ainda sem lista, ou a última vez que se pediu falhou (a lista à vista pode não ser a do
      // servidor).
      cancelarRede = rede?.aoMudar((ligado) => {
        if (ativo && ligado && (!carregada || falha !== null)) carregar();
      }) ?? (() => {});
      carregar();
    },
    // "Tentar novamente" (a lista não carregou); um toque, um pedido.
    tentarDeNovo() {
      if (falha !== null) carregar();
    },
    mudarNova(valor) {
      if (!ativo || typeof valor !== 'string') return;
      nova = { valor, erro: null };
      atualizar();
    },
    adicionar,
    subir: (id) => mover(id, -1),
    descer: (id) => mover(id, 1),
    abrirEdicao(id) {
      if (!ativo || !carregada || edicao?.aGuardar || edicao?.id === id) return;
      const regiao = regiaoCom(id);
      if (regiao === null) return;
      edicao = { id, valor: regiao.nome, erro: null, aGuardar: false };
      errosApagar.delete(id);
      atualizar();
      aoFocar?.({ id, alvo: 'nome' });
    },
    mudarNome(valor) {
      if (!ativo || edicao === null || edicao.aGuardar || typeof valor !== 'string') return;
      edicao = { ...edicao, valor, erro: null };
      atualizar();
    },
    guardarNome,
    cancelarEdicao() {
      if (!ativo || edicao === null || edicao.aGuardar) return;
      const { id } = edicao;
      edicao = null;
      atualizar();
      aoFocar?.({ id, alvo: 'mudar' });
    },
    pedirApagar(id) {
      if (!ativo || pergunta !== null || aApagar.has(id)) return;
      const regiao = regiaoCom(id);
      if (regiao === null) return;
      errosApagar.delete(id);
      pergunta = regiao;
      atualizar();
    },
    // A resposta à pergunta do Apagar ('apagar' ou null); só a primeira conta.
    responderApagar(valor) {
      if (!ativo || pergunta === null) return;
      const regiao = pergunta;
      pergunta = null;
      atualizar();
      if (valor === RESPOSTA_APAGAR_REGIAO) apagar(regiao);
    },
    destruir() {
      if (!ativo) return;
      ativo = false;
      cancelarRede();
      pergunta = null;
      vista = montarVista();
    },
  };
}
