// A página "Clientes" (desenho de 2026-11-07, §1), sem DOM: todas as lojas, de todas as fases, separadas pela
// fase e com pesquisa. Molde do `criarListaRotas`: uma `vista` congelada a cada mudança, entregue ao
// `aoMudarVista`; o `pages/crm/CrmClientes.js` só a desenha. Não usa o mapa: funciona sem o Google.
//
//  - `iniciar()` pede o resumo do `GET /lojas`, que já vem pelo nome. A falha mostra a mensagem e "Tentar
//    novamente"; a rede que volta pede outra vez a lista que falhou.
//  - **Pastilhas:** "Todas" e uma por fase, pela ordem do funil, com a cor do pino e o número de lojas. Uma de
//    cada vez. Os números contam só as lojas que batem com a pesquisa em curso, para se ver onde estão os
//    resultados.
//  - **Pesquisa:** filtra enquanto se escreve, aqui no browser, sem contar maiúsculas nem acentos. Procura no
//    nome, na pessoa de contacto, no telefone (sem contar os espaços), na localidade e na marca. Com várias
//    palavras, cada uma tem de aparecer, em qualquer dos campos, mesmo que só como parte de uma palavra. Numa
//    loja com a marca por revelar, o texto da marca é "não quer revelar", e nunca o rótulo da caixa da ficha:
//    "cliente" não a traz.
//  - **Cada linha:** a cor, o nome, a fase em texto (a cor nunca é a única pista) e os detalhes. O que estiver
//    vazio não aparece, exceto o último contacto.
//  - **Abrir a ficha:** cada linha é um `Link` com `state: {origem: 'clientes'}`, sem nada no endereço, e o
//    `veioDaLista` decide se a ficha mostra "Voltar à lista". A ficha aberta de outro sítio não traz esse
//    `state`.
//  - A pesquisa e a fase ficam na sessão do browser (`sessionStorage`, chave `crm.clientes`), para continuarem
//    lá ao voltar da ficha. Não se misturam com os filtros do mapa (`crm.filtros`). O armazenamento pode faltar
//    ou lançar: a página funciona na mesma, só não se lembra.
//
// Os dados ficam como texto: o React escreve-os como texto.
import { MENSAGEM_ERRO_INESPERADO } from './api';
import { linhaUltimoContacto, textoDoErro } from './ecraMapa';
import { FASES, FUNIL } from './fases';
import { opcoesFase } from './formularioLoja';
import { caminhoDaFicha } from './lojaNova';

export const CHAVE_CLIENTES = 'crm.clientes';
export const FASE_TODAS = 'todas';
export const ROTULO_TODAS = 'Todas';

export const TITULO_CLIENTES = 'Clientes';
export const TEXTO_A_CARREGAR = 'A carregar as lojas…';
export const TEXTO_PESQUISA = 'Pesquisar por nome, pessoa, telefone, localidade ou marca';
export const TEXTO_SEM_LOJAS = 'Ainda não há lojas.';
export const TEXTO_NOVA_LOJA = 'Nova loja';
export const TEXTO_SEM_RESULTADOS = 'Nenhuma loja encontrada.';
export const TEXTO_LIMPAR_PESQUISA = 'Limpar pesquisa';
export const TEXTO_SEM_LOJAS_NA_FASE = 'Sem lojas nesta fase.';
export const TEXTO_VOLTAR_A_LISTA = 'Voltar à lista';

export const ROTULO_MARCA = 'Marca:';
export const ROTULO_CONSUMO = 'Consumo:';
export const TEXTO_MARCA_NAO_REVELA = 'não revela';
// O texto pesquisável da marca de quem não a quer revelar.
export const MARCA_POR_REVELAR = 'não quer revelar';

// De onde a ficha foi aberta (`state` da navegação).
export const ORIGEM_LISTA = 'clientes';

const eObjeto = (valor) => valor !== null && typeof valor === 'object' && !Array.isArray(valor);
const aparado = (valor) => (typeof valor === 'string' ? valor.trim() : '');

function congelarAFundo(valor) {
  if (valor !== null && typeof valor === 'object') {
    Object.values(valor).forEach(congelarAFundo);
    Object.freeze(valor);
  }
  return valor;
}

// --- A ficha aberta pela lista -------------------------------------------------------------------

export const caminhoDaLista = (base) => `${base}/clientes`;

// O `state` da ficha diz que ela foi aberta pela lista: mostra "Voltar à lista".
export function veioDaLista(estado) {
  return estado?.origem === ORIGEM_LISTA;
}

// --- A pesquisa e a fase na sessão do browser ----------------------------------------------------

export function filtrosClientesPadrao() {
  return { pesquisa: '', fase: FASE_TODAS };
}

// Uma fase que não existe volta a "Todas"; a pesquisa fica tal como foi escrita.
export function normalizarFiltrosClientes(dados) {
  if (!eObjeto(dados)) return filtrosClientesPadrao();
  return {
    pesquisa: typeof dados.pesquisa === 'string' ? dados.pesquisa : '',
    fase: FUNIL.includes(dados.fase) ? dados.fase : FASE_TODAS,
  };
}

export function carregarFiltrosClientes(storage) {
  try {
    const texto = storage.getItem(CHAVE_CLIENTES);
    if (texto == null) return filtrosClientesPadrao();
    return normalizarFiltrosClientes(JSON.parse(texto));
  } catch {
    return filtrosClientesPadrao();
  }
}

export function guardarFiltrosClientes(storage, filtros) {
  try {
    storage.setItem(CHAVE_CLIENTES, JSON.stringify(normalizarFiltrosClientes(filtros)));
    return true;
  } catch {
    return false;
  }
}

// --- A pesquisa ----------------------------------------------------------------------------------

// Sem acentos e em minúsculas; o que não é texto conta como vazio.
function paraComparar(valor) {
  return typeof valor === 'string' ? valor.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase() : '';
}

// As palavras da pesquisa, já prontas para comparar; só espaços não é pesquisa nenhuma.
export function palavrasDaPesquisa(pesquisa) {
  return paraComparar(pesquisa).split(/\s+/).filter((palavra) => palavra !== '');
}

function camposPesquisaveis(loja) {
  const telefone = typeof loja.telefone === 'string' ? loja.telefone.replace(/\s/g, '') : '';
  const marca = loja.marca_nao_revela === true ? MARCA_POR_REVELAR : loja.marca_atual;
  return [loja.nome, loja.pessoa_contacto, telefone, loja.localidade, marca].map(paraComparar);
}

// Cada palavra tem de aparecer em algum dos campos, cada uma no seu; sem palavras, todas as lojas batem.
export function lojasDaPesquisa(lojas, pesquisa) {
  const palavras = palavrasDaPesquisa(pesquisa);
  if (palavras.length === 0) return lojas;
  return lojas.filter((loja) => {
    const campos = camposPesquisaveis(loja);
    return palavras.every((palavra) => campos.some((campo) => campo.includes(palavra)));
  });
}

// --- As pastilhas e as linhas --------------------------------------------------------------------

// "Todas" e uma por fase, pela ordem do funil: {valor, rotulo, classeCor, numero, escolhida}. `lojas`: as que
// batem com a pesquisa. Uma loja de uma fase desconhecida só conta em "Todas".
export function pastilhasDeFase(lojas, faseEscolhida) {
  return [
    { valor: FASE_TODAS, rotulo: ROTULO_TODAS, classeCor: null, numero: lojas.length, escolhida: faseEscolhida === FASE_TODAS },
    ...opcoesFase().map((opcao) => ({
      ...opcao,
      numero: lojas.filter((loja) => loja.fase === opcao.valor).length,
      escolhida: faseEscolhida === opcao.valor,
    })),
  ];
}

export function lojasDaFase(lojas, fase) {
  return fase === FASE_TODAS ? lojas : lojas.filter((loja) => loja.fase === fase);
}

// A marca de uma linha ("não revela", o texto dela, ou nada).
function marcaDaLinha(loja) {
  return loja.marca_nao_revela === true ? TEXTO_MARCA_NAO_REVELA : aparado(loja.marca_atual);
}

// Os detalhes de uma linha, pela ordem do ecrã, cada um {rotulo, texto}.
function detalhesDaLinha(loja) {
  const detalhes = [
    { rotulo: null, texto: aparado(loja.localidade) },
    { rotulo: ROTULO_MARCA, texto: marcaDaLinha(loja) },
    { rotulo: ROTULO_CONSUMO, texto: aparado(loja.consumo_semanal) },
  ];
  return [...detalhes.filter((detalhe) => detalhe.texto !== ''), linhaUltimoContacto(loja)];
}

// Uma linha da lista: {id, nome, classeCor, fase, detalhes, caminho, estado}. `classeCor` é null numa fase
// desconhecida, que se escreve tal como veio. `estado` é o `state` do `Link` para a ficha.
export function linhaDaLoja(loja, base) {
  const conhecida = FUNIL.includes(loja.fase);
  return {
    id: loja.id,
    nome: aparado(loja.nome),
    classeCor: conhecida ? `crm-amostra-fase pino--${loja.fase}` : null,
    fase: conhecida ? FASES[loja.fase].rotulo : String(loja.fase ?? ''),
    detalhes: detalhesDaLinha(loja),
    caminho: caminhoDaFicha(base, loja.id),
    estado: { origem: ORIGEM_LISTA },
  };
}

// Sem linhas para mostrar: {texto, limpar}. Com texto na pesquisa, "Limpar pesquisa" (que deixa a fase); sem
// texto, só a frase, porque as pastilhas continuam visíveis.
export function semResultados(pesquisa) {
  return palavrasDaPesquisa(pesquisa).length > 0
    ? { texto: TEXTO_SEM_RESULTADOS, limpar: true }
    : { texto: TEXTO_SEM_LOJAS_NA_FASE, limpar: false };
}

// --- Ecrã ----------------------------------------------------------------------------------------

// criarListaClientes({api, rede, base, storage, aoMudarVista})
//   → {vista, iniciar, tentarDeNovo, mudarPesquisa, limparPesquisa, escolherFase, destruir}
//  - api: {listarLojas} do lib/crm/api.js; rede: o `criarEstadoRede(window, navigator)` (sem ele, não se ouve a
//    rede); base: a casa do CRM (`/crm` ou `/admin/crm`); storage: o `sessionStorage` (pode faltar ou lançar).
// vista: {estado: 'a_carregar'|'falha'|'sem_lojas'|'pronto', titulo, falha: null | {mensagem, aTentar},
//         novaLoja, pesquisa, fase, pastilhas: [pastilha], linhas: [linha], semResultados: null | {texto, limpar}}
//   — nova a cada mudança e congelada a fundo; as pastilhas e as linhas só com lojas.
// Criar não pede nada: `iniciar()` pede a lista e ouve a rede; `destruir()` (a página saiu) faz que as respostas
// que chegarem depois e a rede já não façam nada.
export function criarListaClientes({
  api, rede, base, storage, aoMudarVista,
}) {
  let lojas = null; // o `GET /lojas`, só com as que têm id
  let falha = null; // a mensagem, se a lista não carregou
  let aCarregar = false;
  let filtros = carregarFiltrosClientes(storage);
  let iniciado = false;
  let ativo = true;
  let cancelarRede = () => {};

  function montarVista() {
    let estado = 'a_carregar';
    if (lojas !== null) estado = lojas.length === 0 ? 'sem_lojas' : 'pronto';
    else if (falha !== null) estado = 'falha';
    const pronto = estado === 'pronto';
    const encontradas = pronto ? lojasDaPesquisa(lojas, filtros.pesquisa) : [];
    const linhas = lojasDaFase(encontradas, filtros.fase).map((loja) => linhaDaLoja(loja, base));
    return congelarAFundo({
      estado,
      titulo: TITULO_CLIENTES,
      falha: estado === 'falha' ? { mensagem: falha, aTentar: aCarregar } : null,
      novaLoja: `${base}/lojas/nova`,
      pesquisa: filtros.pesquisa,
      fase: filtros.fase,
      pastilhas: pronto ? pastilhasDeFase(encontradas, filtros.fase) : [],
      linhas,
      semResultados: pronto && linhas.length === 0 ? semResultados(filtros.pesquisa) : null,
    });
  }

  let vista = montarVista();

  function atualizar() {
    vista = montarVista();
    aoMudarVista?.(vista);
  }

  function mudarFiltros(novos) {
    if (!ativo) return;
    filtros = { ...filtros, ...novos };
    guardarFiltrosClientes(storage, filtros);
    atualizar();
  }

  async function carregar() {
    if (!ativo || aCarregar || lojas !== null) return;
    aCarregar = true;
    atualizar();
    let resposta;
    try {
      resposta = await api.listarLojas();
    } catch (erro) {
      aCarregar = false;
      if (!ativo) return;
      falha = textoDoErro(erro);
      atualizar();
      return;
    }
    aCarregar = false;
    if (!ativo) return;
    if (Array.isArray(resposta)) lojas = resposta.filter((loja) => typeof loja?.id === 'string' && loja.id !== '');
    else falha = MENSAGEM_ERRO_INESPERADO;
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
    // O valor do campo da pesquisa, tal como está escrito.
    mudarPesquisa(pesquisa) {
      if (typeof pesquisa === 'string') mudarFiltros({ pesquisa });
    },
    // Só limpa o texto: a fase fica.
    limparPesquisa() {
      mudarFiltros({ pesquisa: '' });
    },
    escolherFase(fase) {
      if (fase === FASE_TODAS || FUNIL.includes(fase)) mudarFiltros({ fase });
    },
    destruir() {
      ativo = false;
      cancelarRede();
    },
  };
}
