// Definições › Membros (desenho §3.1; plano T2.29), sem DOM: quem entra no
// CRM e com que perfil. Porta de
// public/assets/js/componentes/definicoes-utilizadores.js do CRM autónomo,
// adaptada aos membros do portal; como a ficha da T2.28, o que o autónomo
// escrevia no DOM é uma `vista` congelada, entregue ao `aoMudarVista`, e o
// `pages/crm/DefinicoesMembros.js` só a desenha (correção "T2.26 / T2.27 /
// T2.29 / T2.30 (componentes Sem Jest)").
//
//  - A tabela: nome, email, tipo de conta (gestor/colaborador, da conta do
//    portal) e perfil. O admin principal (o admin master do portal, `id:
//    null`) vem primeiro, fixo e sem ações: é sempre admin do CRM. A conta da
//    própria sessão também não tem ações, como no autónomo (o admin não se
//    tira o acesso a si próprio por engano). Um membro com a conta apagada
//    mostra "(conta apagada)" e pode retirar-se.
//  - O perfil muda num `Select` e grava logo (PATCH {perfil}); a linha fica
//    ocupada até à resposta (um pedido de cada vez por linha), com o perfil
//    escolhido à vista. "Perfil guardado" é um aviso (toast).
//  - Retirar pede confirmação ("Retirar X do CRM?", com Cancelar primeiro, a
//    escolha que não retira); retirado, a conta volta à lista das que podem
//    entrar e o foco vai para o título (o botão em que se tocou desaparece).
//  - Adicionar: escolher uma conta do portal que ainda não é membro (`GET
//    /membros/candidatos`) e o perfil (Utilizador por omissão, `PERFIS[0]`).
//    Os erros de campo (422) ficam junto aos campos, com o foco no primeiro.
//  - As mensagens do servidor (409, 404, sem rede) são avisos de erro (toast;
//    nota da T2.28), e não um parágrafo na linha como no autónomo. Quando a
//    lista ficou desatualizada (409 `ja_membro`/`admin_master`, 404: outro
//    admin mudou-a entretanto), as duas listas pedem-se outra vez.
//  - Sem as listas não há tabela: a mensagem e "Tentar novamente" (só do que
//    falhou); quando a rede volta, o que falhou pede-se outra vez.
//
// Os dados (nomes, emails) ficam como texto: o React escreve-os como texto.
import { textoDoErro } from './ecraMapa';
import { eUuid } from './ids';
import { PERFIS, rotuloPerfil } from './perfis';

export const TITULO_MEMBROS = 'Membros';
export const TEXTO_DESCRICAO_MEMBROS = 'Quem entra no CRM e com que perfil.';
export const TEXTO_A_CARREGAR_MEMBROS = 'A carregar os membros…';
export const COLUNAS_MEMBROS = Object.freeze(['Nome', 'Email', 'Tipo de conta', 'Perfil', 'Ações']);
export const TEXTO_CONTA_APAGADA = '(conta apagada)';
export const TEXTO_ADMIN_PRINCIPAL = 'Administrador principal';
export const TEXTO_NOTA_ADMIN_PRINCIPAL = 'É sempre administrador do CRM.';
export const TEXTO_NOTA_PROPRIA = 'A sua conta: só outro administrador a pode mudar.';
export const TEXTO_PERFIL_DESCONHECIDO = 'Perfil desconhecido';
export const TEXTO_SEM_VALOR = '—';
export const TEXTO_ADICIONAR_TITULO = 'Adicionar membro';
export const TEXTO_CONTA = 'Conta do portal';
export const TEXTO_PERFIL = 'Perfil';
export const TEXTO_ESCOLHER_CONTA = 'Escolha uma conta';
export const TEXTO_SEM_CANDIDATOS = 'Todas as contas do portal já são membros do CRM.';
export const TEXTO_ADICIONAR = 'Adicionar';
export const TEXTO_A_ADICIONAR = 'A adicionar…';
export const TEXTO_RETIRAR = 'Retirar';
export const TEXTO_MEMBRO_ADICIONADO = 'Membro adicionado';
export const TEXTO_PERFIL_GUARDADO = 'Perfil guardado';
export const TEXTO_MEMBRO_RETIRADO = 'Membro retirado';
export const TEXTO_RETIRAR_AVISO = 'Deixa de ter acesso ao CRM. A conta do portal fica como está.';
export const RESPOSTA_RETIRAR = 'retirar';

// O perfil que o "Adicionar" escolhe por omissão: o primeiro dos PERFIS (o mais comum), nunca o admin.
export const PERFIL_INICIAL = PERFIS[0].valor;

// O que cada perfil dá na F2 (desenho §3.1), por baixo da escolha do perfil. O motorista só entra no terreno
// (F4): até lá não vê o CRM (`acesso.js`).
export const DESCRICOES_PERFIS = Object.freeze({
  utilizador: 'Lojas e mapa.',
  admin: 'Tudo, incluindo estas definições.',
  motorista: 'A rota do dia, que ainda não existe — por agora não vê o CRM.',
});

const TIPOS_CONTA = Object.freeze({ gestor: 'Gestor', colaborador: 'Colaborador' });

// Os erros que querem dizer que a lista à vista já não é a do servidor (outro admin mudou-a).
const LISTA_DESATUALIZADA = new Set(['ja_membro', 'admin_master', 'nao_encontrado']);

// Os campos do "Adicionar", pela ordem do formulário (o foco vai para o primeiro com erro).
const CAMPOS_NOVO = Object.freeze(['user_id', 'perfil']);

const SEM_LINHAS = Object.freeze([]);

// --- Funções puras -------------------------------------------------------------------------------

const textoOuNulo = (valor) => valor == null || typeof valor === 'string';
// Uma lista nunca passa: não tem `conta_existe` booleano nem `id` em texto.
const eObjeto = (valor) => valor !== null && typeof valor === 'object';
const ePerfil = (valor) => PERFIS.some((p) => p.valor === valor);
const textoComConteudo = (valor) => typeof valor === 'string' && valor !== '';

// Uma linha do GET /api/crm/membros: o admin principal (`admin_master: true`, `id: null`) ou um membro (uuid).
// Um perfil desconhecido (null, ou de uma versão mais nova do servidor) conta: a linha fica para o corrigir.
export function membroValido(m) {
  if (!eObjeto(m) || typeof m.conta_existe !== 'boolean') return false;
  if (!textoOuNulo(m.nome) || !textoOuNulo(m.email) || !textoOuNulo(m.user_id) || !textoOuNulo(m.perfil)) return false;
  if (m.admin_master === true) return m.id === null;
  return m.admin_master === false && eUuid(m.id);
}

// Uma conta do GET /api/crm/membros/candidatos: o id da conta do portal (o `user_id` do POST) em texto.
export function candidatoValido(c) {
  return eObjeto(c) && textoComConteudo(c.id) && textoOuNulo(c.nome) && textoOuNulo(c.email);
}

// Como o servidor (`chave_comparacao` e depois o id): sem distinguir maiúsculas nem acentos.
const colador = new Intl.Collator('pt', { sensitivity: 'base' });
const nomeParaOrdem = (item) => (typeof item?.nome === 'string' ? item.nome : '');

function compararIds(a, b) {
  const x = String(a ?? '');
  const y = String(b ?? '');
  if (x === y) return 0;
  return x < y ? -1 : 1;
}

const porNome = (a, b) => colador.compare(nomeParaOrdem(a), nomeParaOrdem(b)) || compararIds(a.id, b.id);

// O admin principal primeiro, os membros com a conta apagada no fim, e por nome. Não altera a lista recebida.
export function ordenarMembros(lista) {
  return [...lista].sort((a, b) => (
    Number(b.admin_master === true) - Number(a.admin_master === true)
    || Number(a.conta_existe === false) - Number(b.conta_existe === false)
    || porNome(a, b)
  ));
}

export function ordenarCandidatos(lista) {
  return [...lista].sort(porNome);
}

// 'gestor' → 'Gestor', 'colaborador' → 'Colaborador'; o resto → '—'.
export function rotuloTipoConta(tipo) {
  return typeof tipo === 'string' && Object.prototype.hasOwnProperty.call(TIPOS_CONTA, tipo) ? TIPOS_CONTA[tipo] : TEXTO_SEM_VALOR;
}

// Como a pessoa aparece numa frase: o nome, o email, ou "este membro" (com a conta apagada não há nenhum).
function nomeNaFrase(m) {
  if (m.conta_existe && textoComConteudo(m.nome)) return m.nome;
  if (m.conta_existe && textoComConteudo(m.email)) return m.email;
  return 'este membro';
}

// Como a pessoa aparece na coluna do nome.
function nomeNaTabela(m) {
  if (!m.conta_existe) return TEXTO_CONTA_APAGADA;
  if (textoComConteudo(m.nome)) return m.nome;
  return textoComConteudo(m.email) ? m.email : TEXTO_SEM_VALOR;
}

// A pergunta do Retirar: a primeira escolha é a que não retira (o foco vai para ela).
export function perguntaRetirar(m) {
  return Object.freeze({
    pergunta: `Retirar ${nomeNaFrase(m)} do CRM?`,
    aviso: TEXTO_RETIRAR_AVISO,
    botoes: Object.freeze([
      Object.freeze({ texto: 'Cancelar', valor: null, variante: 'normal' }),
      Object.freeze({ texto: 'Sim, retirar', valor: RESPOSTA_RETIRAR, variante: 'perigo' }),
    ]),
  });
}

// As contas que podem entrar, para o `Select` do "Adicionar": [{valor (o id da conta), nome, detalhe}].
export function opcoesConta(candidatos) {
  if (!Array.isArray(candidatos)) return SEM_LINHAS;
  return Object.freeze(candidatos.map((c) => {
    const nome = [c.nome, c.email, c.id].find(textoComConteudo);
    const tipo = rotuloTipoConta(c.tipo_conta);
    const detalhe = [textoComConteudo(c.nome) ? c.email : null, tipo === TEXTO_SEM_VALOR ? null : tipo].filter(textoComConteudo);
    return Object.freeze({ valor: c.id, nome, detalhe: detalhe.join(' · ') });
  }));
}

const listaDeMembros = (resposta) => ordenarMembros((Array.isArray(resposta) ? resposta : []).filter(membroValido));
const listaDeCandidatos = (resposta) => ordenarCandidatos((Array.isArray(resposta) ? resposta : []).filter(candidatoValido));

// Os erros de campo do 422 do POST /membros que o formulário mostra: só `user_id` e `perfil`, em texto.
function errosDoNovo(campos) {
  const erros = {};
  for (const campo of CAMPOS_NOVO) {
    if (typeof campos?.[campo] === 'string' && campos[campo] !== '') erros[campo] = campos[campo];
  }
  return erros;
}

const semCampo = (erros, campo) => {
  const { [campo]: _fora, ...resto } = erros;
  return resto;
};

// --- Ecrã ----------------------------------------------------------------------------------------

// criarMembros({api, rede, euId, aoMudarVista, aoAvisar, aoAvisarErro, aoFocar})
//   → {vista, iniciar, tentarDeNovo, escolherConta, escolherPerfil, adicionar, mudarPerfil, pedirRetirar,
//      responderRetirar, destruir}
//  - api: {listarMembros, listarCandidatos, adicionarMembro, mudarPerfilMembro, retirarMembro} do
//    lib/crm/api.js; rede: o `criarEstadoRede(window, navigator)`;
//  - euId: o id da conta da sessão (`useAuth().user.id`): a linha dele não tem ações;
//  - aoAvisar(texto): "Membro adicionado" / "Perfil guardado" / "Membro retirado" (toast); aoAvisarErro(texto):
//    a mensagem do servidor (toast de erro); aoFocar(alvo): 'user_id' ou 'perfil' (o campo do 422), ou
//    'titulo' (depois de retirar).
// vista: {estado: 'a_carregar'|'falha'|'pronto', falha: null | {mensagem, aTentar},
//         linhas: [{chave, id, nome, contaApagada, email, tipoConta, perfil, rotuloPerfil, adminPrincipal,
//                   propria, acoes, ocupada, nota, rotuloPerfilAcessivel, rotuloRetirarAcessivel}],
//         novo: {userId, perfil, descricaoPerfil, erros, opcoesConta, semCandidatos, botao: {ativo, texto}},
//         pergunta: null | {pergunta, aviso, botoes}}
//   — nova a cada mudança e congelada.
// Criar não pede nada: `iniciar()` pede as duas listas e ouve a rede; `destruir()` (o ecrã saiu) faz que as
// respostas que chegarem depois, a rede e as respostas à pergunta já não façam nada.
export function criarMembros({
  api, rede, euId, aoMudarVista, aoAvisar, aoAvisarErro, aoFocar,
}) {
  let membros = null; // o GET /membros, quando chegar (ordenado)
  let candidatos = null; // o GET /membros/candidatos, quando chegar (ordenado)
  let falhaMembros = null; // a mensagem, se o pedido falhou
  let falhaCandidatos = null;
  let aCarregarMembros = false;
  let aCarregarCandidatos = false;
  let aRecarregar = false;
  let novo = { user_id: '', perfil: PERFIL_INICIAL };
  let errosNovo = {};
  let aAdicionar = false;
  const ocupadas = new Map(); // id do membro → o perfil pedido (ou null, a retirar)
  let aRetirar = null; // o membro da pergunta "Retirar …?", enquanto está aberta
  let iniciado = false;
  let ativo = true;
  let cancelarRede = () => {};

  const sessao = textoComConteudo(euId) ? euId : null;
  const propria = (m) => !m.admin_master && sessao !== null && m.user_id === sessao;
  // O membro (não o admin principal) com este id que aceita ações agora: nem a própria conta, nem ocupado.
  const membroLivre = (id) => {
    const m = membros?.find((x) => !x.admin_master && x.id === id);
    return m && !propria(m) && !ocupadas.has(id) ? m : null;
  };

  function estadoAtual() {
    if (membros !== null && candidatos !== null) return 'pronto';
    if (falhaMembros !== null || falhaCandidatos !== null) return 'falha';
    return 'a_carregar';
  }

  function vistaLinha(m) {
    const ocupada = !m.admin_master && ocupadas.has(m.id);
    const pedido = ocupada ? ocupadas.get(m.id) : null;
    const perfil = typeof pedido === 'string' ? pedido : (m.perfil ?? null);
    const daSessao = propria(m);
    let nota = null;
    if (m.admin_master) nota = TEXTO_NOTA_ADMIN_PRINCIPAL;
    else if (daSessao) nota = TEXTO_NOTA_PROPRIA;
    const frase = nomeNaFrase(m);
    return Object.freeze({
      chave: m.admin_master ? 'admin-principal' : m.id,
      id: m.id,
      nome: nomeNaTabela(m),
      contaApagada: !m.conta_existe,
      email: m.conta_existe && textoComConteudo(m.email) ? m.email : TEXTO_SEM_VALOR,
      tipoConta: rotuloTipoConta(m.tipo_conta),
      perfil,
      rotuloPerfil: perfil === null ? TEXTO_PERFIL_DESCONHECIDO : rotuloPerfil(perfil),
      adminPrincipal: m.admin_master,
      propria: daSessao,
      acoes: !m.admin_master && !daSessao,
      ocupada,
      nota,
      rotuloPerfilAcessivel: `Perfil de ${frase}`,
      rotuloRetirarAcessivel: `Retirar ${frase} do CRM`,
    });
  }

  function montarVista() {
    const estado = estadoAtual();
    return Object.freeze({
      estado,
      falha: estado === 'falha' ? Object.freeze({
        mensagem: falhaMembros ?? falhaCandidatos,
        aTentar: aCarregarMembros || aCarregarCandidatos,
      }) : null,
      linhas: membros === null ? SEM_LINHAS : Object.freeze(membros.map(vistaLinha)),
      novo: Object.freeze({
        userId: novo.user_id,
        perfil: novo.perfil,
        descricaoPerfil: DESCRICOES_PERFIS[novo.perfil] ?? '',
        erros: Object.freeze({ ...errosNovo }),
        opcoesConta: opcoesConta(candidatos ?? []),
        semCandidatos: candidatos !== null && candidatos.length === 0,
        botao: Object.freeze({
          ativo: estado === 'pronto' && !aAdicionar && candidatos.length > 0,
          texto: aAdicionar ? TEXTO_A_ADICIONAR : TEXTO_ADICIONAR,
        }),
      }),
      pergunta: aRetirar === null ? null : perguntaRetirar(aRetirar),
    });
  }

  let vista = montarVista();

  function atualizar() {
    vista = montarVista();
    aoMudarVista?.(vista);
  }

  // --- Carregar ---

  async function carregarMembros() {
    aCarregarMembros = true;
    atualizar();
    let resposta;
    try {
      resposta = await api.listarMembros();
    } catch (erro) {
      aCarregarMembros = false;
      if (!ativo) return;
      falhaMembros = textoDoErro(erro);
      atualizar();
      return;
    }
    aCarregarMembros = false;
    if (!ativo) return;
    membros = listaDeMembros(resposta);
    falhaMembros = null;
    atualizar();
  }

  async function carregarCandidatos() {
    aCarregarCandidatos = true;
    atualizar();
    let resposta;
    try {
      resposta = await api.listarCandidatos();
    } catch (erro) {
      aCarregarCandidatos = false;
      if (!ativo) return;
      falhaCandidatos = textoDoErro(erro);
      atualizar();
      return;
    }
    aCarregarCandidatos = false;
    if (!ativo) return;
    candidatos = listaDeCandidatos(resposta);
    falhaCandidatos = null;
    atualizar();
  }

  // Pede o que ainda não chegou (e não está a caminho): no início, no "Tentar novamente" e quando a rede volta.
  function carregar() {
    if (!ativo) return;
    if (membros === null && !aCarregarMembros) carregarMembros();
    if (candidatos === null && !aCarregarCandidatos) carregarCandidatos();
  }

  // As duas listas outra vez, sem esconder a tabela: outro admin mudou-as entretanto. Uma falha deixa as que
  // estavam (o aviso do erro que levou aqui já foi dado).
  async function recarregarListas() {
    if (!ativo || aRecarregar) return;
    aRecarregar = true;
    const [respostaMembros, respostaCandidatos] = await Promise.allSettled([api.listarMembros(), api.listarCandidatos()]);
    aRecarregar = false;
    if (!ativo) return;
    if (respostaMembros.status === 'fulfilled') membros = listaDeMembros(respostaMembros.value);
    if (respostaCandidatos.status === 'fulfilled') {
      candidatos = listaDeCandidatos(respostaCandidatos.value);
      // A conta escolhida já não pode entrar (outro admin juntou-a): a escolha sai.
      if (!candidatos.some((c) => c.id === novo.user_id)) novo = { ...novo, user_id: '' };
    }
    atualizar();
  }

  function avisarErro(erro) {
    aoAvisarErro?.(textoDoErro(erro));
    if (LISTA_DESATUALIZADA.has(erro?.codigo)) recarregarListas();
  }

  // --- Adicionar ---

  async function adicionar() {
    if (!ativo || aAdicionar || !vista.novo.botao.ativo) return;
    const corpo = { user_id: novo.user_id, perfil: novo.perfil };
    aAdicionar = true;
    errosNovo = {};
    atualizar();

    let criado;
    try {
      criado = await api.adicionarMembro(corpo);
    } catch (erro) {
      if (!ativo) return;
      aAdicionar = false;
      const erros = erro?.codigo === 'validacao' ? errosDoNovo(erro.campos) : {};
      const primeiro = CAMPOS_NOVO.find((campo) => campo in erros);
      if (primeiro) {
        errosNovo = erros;
        atualizar();
        aoFocar?.(primeiro);
        return;
      }
      atualizar();
      avisarErro(erro);
      return;
    }
    if (!ativo) return;
    aAdicionar = false;
    const valido = membroValido(criado) && !criado.admin_master;
    if (valido) {
      membros = ordenarMembros([...membros.filter((m) => m.id !== criado.id), criado]);
      candidatos = candidatos.filter((c) => c.id !== corpo.user_id && c.id !== criado.user_id);
    }
    novo = { user_id: '', perfil: PERFIL_INICIAL };
    atualizar();
    aoAvisar?.(TEXTO_MEMBRO_ADICIONADO);
    // O servidor gravou, mas a resposta não é uma linha: a lista vem do servidor.
    if (!valido) recarregarListas();
  }

  // --- Mudar o perfil ---

  async function mudarPerfil(id, perfil) {
    if (!ativo || aRetirar !== null || !ePerfil(perfil)) return;
    const m = membroLivre(id);
    if (!m || m.perfil === perfil) return;
    ocupadas.set(id, perfil);
    atualizar();

    let resposta;
    try {
      resposta = await api.mudarPerfilMembro(id, perfil);
    } catch (erro) {
      if (!ativo) return;
      ocupadas.delete(id);
      atualizar();
      avisarErro(erro);
      return;
    }
    if (!ativo) return;
    ocupadas.delete(id);
    const valida = membroValido(resposta) && resposta.id === id;
    membros = membros.map((x) => {
      if (x.admin_master || x.id !== id) return x;
      return valida ? resposta : { ...x, perfil };
    });
    atualizar();
    aoAvisar?.(TEXTO_PERFIL_GUARDADO);
    if (!valida) recarregarListas();
  }

  // --- Retirar ---

  async function retirar(m) {
    ocupadas.set(m.id, null);
    atualizar();
    try {
      await api.retirarMembro(m.id);
    } catch (erro) {
      if (!ativo) return;
      ocupadas.delete(m.id);
      atualizar();
      avisarErro(erro);
      return;
    }
    if (!ativo) return;
    ocupadas.delete(m.id);
    membros = membros.filter((x) => x.admin_master || x.id !== m.id);
    // A conta volta às que podem entrar (uma conta apagada não).
    if (m.conta_existe && textoComConteudo(m.user_id) && !candidatos.some((c) => c.id === m.user_id)) {
      candidatos = ordenarCandidatos([
        ...candidatos,
        { id: m.user_id, nome: m.nome ?? null, email: m.email ?? null, tipo_conta: m.tipo_conta ?? null },
      ]);
    }
    atualizar();
    aoAvisar?.(TEXTO_MEMBRO_RETIRADO);
    aoFocar?.('titulo');
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
    // "Tentar novamente" (uma das listas não carregou); um toque, um pedido.
    tentarDeNovo() {
      if (estadoAtual() === 'falha') carregar();
    },
    escolherConta(valor) {
      if (!ativo || aAdicionar || typeof valor !== 'string') return;
      if (valor === novo.user_id && !('user_id' in errosNovo)) return;
      novo = { ...novo, user_id: valor };
      errosNovo = semCampo(errosNovo, 'user_id');
      atualizar();
    },
    escolherPerfil(valor) {
      if (!ativo || aAdicionar || !ePerfil(valor)) return;
      if (valor === novo.perfil && !('perfil' in errosNovo)) return;
      novo = { ...novo, perfil: valor };
      errosNovo = semCampo(errosNovo, 'perfil');
      atualizar();
    },
    adicionar,
    mudarPerfil,
    pedirRetirar(id) {
      if (!ativo || aRetirar !== null) return;
      const m = membroLivre(id);
      if (!m) return;
      aRetirar = m;
      atualizar();
    },
    // A resposta à pergunta do Retirar ('retirar' ou null); só a primeira conta.
    responderRetirar(valor) {
      if (!ativo || aRetirar === null) return;
      const m = aRetirar;
      aRetirar = null;
      atualizar();
      if (valor === RESPOSTA_RETIRAR) retirar(m);
    },
    destruir() {
      if (!ativo) return;
      ativo = false;
      cancelarRede();
      aRetirar = null;
      vista = montarVista();
    },
  };
}
