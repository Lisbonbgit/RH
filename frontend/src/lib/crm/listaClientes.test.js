/**
 * A LISTA DE CLIENTES — as regras da página "Clientes", sem DOM (desenho de 2026-11-07, §1; a página é o
 * `pages/crm/CrmClientes.js`).
 *
 * O controlador (`criarListaClientes`, no molde do `criarListaRotas`) pede o resumo do `GET /lojas` e separa-o
 * por fase, com pesquisa no browser. Aqui ficam os exemplos da pesquisa do desenho, os números das pastilhas (só
 * as lojas que batem com a pesquisa), o que cada linha mostra, os estados da página, a sessão do browser
 * (`crm.clientes`, à prova de falhas e à parte dos filtros do mapa) e o `veioDaLista`, que decide se a ficha
 * mostra "Voltar à lista".
 */
import fs from 'fs';
import path from 'path';

import { ErroCrm, MENSAGEM_ERRO_INESPERADO, MENSAGEM_SEM_REDE } from './api';
import { CHAVE_FILTROS, carregarFiltros, filtrosPadrao, guardarFiltros } from './filtros';
import {
  CHAVE_CLIENTES,
  FASE_TODAS,
  MARCA_POR_REVELAR,
  ORIGEM_LISTA,
  ROTULO_TODAS,
  TEXTO_A_CARREGAR,
  TEXTO_LIMPAR_PESQUISA,
  TEXTO_NOVA_LOJA,
  TEXTO_PESQUISA,
  TEXTO_SEM_LOJAS,
  TEXTO_SEM_LOJAS_NA_FASE,
  TEXTO_SEM_RESULTADOS,
  TEXTO_VOLTAR_A_LISTA,
  TITULO_CLIENTES,
  caminhoDaLista,
  carregarFiltrosClientes,
  criarListaClientes,
  filtrosClientesPadrao,
  guardarFiltrosClientes,
  linhaDaLoja,
  lojasDaFase,
  lojasDaPesquisa,
  normalizarFiltrosClientes,
  palavrasDaPesquisa,
  pastilhasDeFase,
  semResultados,
  veioDaLista,
} from './listaClientes';
import { criarEstadoRede } from './rede';

const PAGINA = path.join(__dirname, '..', '..', 'pages', 'crm', 'CrmClientes.js');
const FICHA = path.join(__dirname, '..', '..', 'pages', 'crm', 'CrmLoja.js');

const ID_CAFE = '0b6f3c1e-1111-4222-8333-444455556666';
const ID_MERCEARIA = '0b6f3c1e-2222-4222-8333-444455556666';
const ID_QUIOSQUE = '0b6f3c1e-3333-4222-8333-444455556666';
const ID_TASCA = '0b6f3c1e-4444-4222-8333-444455556666';

// O resumo do `GET /lojas` (`CAMPOS_RESUMO` de `backend/crm/formatar.py`), pelo nome.
const resumo = (mudancas) => ({
  id: ID_CAFE,
  nome: 'Loja',
  fase: 'potencial',
  regiao_id: null,
  lat: 38.71,
  lng: -9.13,
  telefone: null,
  pessoa_contacto: null,
  localidade: null,
  consumo_semanal: null,
  marca_atual: null,
  marca_nao_revela: false,
  ultimo_contacto: null,
  ...mudancas,
});

const CAFE = resumo({
  id: ID_CAFE, nome: 'Café Central', fase: 'cliente', localidade: 'Lisboa', pessoa_contacto: 'D. Amélia',
  telefone: '+351 912 345 678', consumo_semanal: '2 baldes grandes', marca_atual: 'Marca Exemplo', ultimo_contacto: '2026-11-05',
});
const MERCEARIA = resumo({
  id: ID_MERCEARIA, nome: 'Mercearia da Baixa', fase: 'cliente', localidade: 'Porto', marca_nao_revela: true,
});
const QUIOSQUE = resumo({ id: ID_QUIOSQUE, nome: 'Quiosque Novo', fase: 'potencial', telefone: '21 000 00 00' });
const TASCA = resumo({ id: ID_TASCA, nome: 'Tasca Antiga', fase: 'perdida', localidade: 'Évora' });
const LOJAS = [CAFE, MERCEARIA, QUIOSQUE, TASCA];

const nomes = (lojas) => lojas.map((loja) => loja.nome);
const pesquisar = (pesquisa, lojas = LOJAS) => nomes(lojasDaPesquisa(lojas, pesquisa));

// --- Os textos -----------------------------------------------------------------------------------

test('os textos do desenho', () => {
  expect(CHAVE_CLIENTES).toBe('crm.clientes');
  expect(ROTULO_TODAS).toBe('Todas');
  expect(TITULO_CLIENTES).toBe('Clientes');
  expect(TEXTO_NOVA_LOJA).toBe('Nova loja');
  expect(TEXTO_LIMPAR_PESQUISA).toBe('Limpar pesquisa');
  expect(TEXTO_SEM_LOJAS_NA_FASE).toBe('Sem lojas nesta fase.');
  expect(TEXTO_VOLTAR_A_LISTA).toBe('Voltar à lista');
  expect(MARCA_POR_REVELAR).toBe('não quer revelar');
  for (const texto of [TEXTO_A_CARREGAR, TEXTO_PESQUISA, TEXTO_SEM_LOJAS, TEXTO_SEM_RESULTADOS]) {
    expect(typeof texto).toBe('string');
    expect(texto).not.toBe('');
  }
});

// --- A pesquisa ----------------------------------------------------------------------------------

describe('lojasDaPesquisa', () => {
  test('sem texto, ou só com espaços, ficam todas (a mesma lista)', () => {
    expect(lojasDaPesquisa(LOJAS, '')).toBe(LOJAS);
    expect(lojasDaPesquisa(LOJAS, '   ')).toBe(LOJAS);
    expect(lojasDaPesquisa(LOJAS, null)).toBe(LOJAS);
  });

  test('ignora maiúsculas e acentos: "cafe" encontra "Café", nos dois sentidos', () => {
    expect(pesquisar('cafe')).toEqual(['Café Central']);
    expect(pesquisar('CAFÉ')).toEqual(['Café Central']);
    expect(pesquisar('evora')).toEqual(['Tasca Antiga']);
    expect(pesquisar('Évora')).toEqual(['Tasca Antiga']);
    expect(pesquisar('amelia')).toEqual(['Café Central']);
  });

  test('um acento escrito em duas partes (NFD) conta como o mesmo', () => {
    expect(pesquisar('café')).toEqual(['Café Central']);
    expect(pesquisar('cafe', [resumo({ nome: 'Café Central' })])).toEqual(['Café Central']);
  });

  test('procura no nome, na pessoa de contacto, no telefone, na localidade e na marca', () => {
    expect(pesquisar('mercearia')).toEqual(['Mercearia da Baixa']);
    expect(pesquisar('amélia')).toEqual(['Café Central']);
    expect(pesquisar('912')).toEqual(['Café Central']);
    expect(pesquisar('porto')).toEqual(['Mercearia da Baixa']);
    expect(pesquisar('exemplo')).toEqual(['Café Central']);
  });

  test('não procura no consumo, na fase nem no id', () => {
    expect(pesquisar('baldes')).toEqual([]);
    expect(pesquisar('potencial')).toEqual([]);
    expect(pesquisar('perdida')).toEqual([]);
    expect(pesquisar('0b6f3c1e')).toEqual([]);
  });

  test('o telefone sem contar os espaços, escritos ou guardados', () => {
    expect(pesquisar('912345678')).toEqual(['Café Central']);
    expect(pesquisar('912 345 678')).toEqual(['Café Central']);
    expect(pesquisar('+351912345678')).toEqual(['Café Central']);
    expect(pesquisar('210000000')).toEqual(['Quiosque Novo']);
    expect(pesquisar('912 345', [resumo({ nome: 'Sem espaços', telefone: '912345678' })])).toEqual(['Sem espaços']);
  });

  test('com várias palavras, cada uma tem de aparecer, em qualquer dos campos', () => {
    expect(pesquisar('café lisboa')).toEqual(['Café Central']);
    expect(pesquisar('lisboa café')).toEqual(['Café Central']);
    expect(pesquisar('café porto')).toEqual([]);
    expect(pesquisar('amélia 912 exemplo lisboa')).toEqual(['Café Central']);
    expect(pesquisar('  café   lisboa  ')).toEqual(['Café Central']);
  });

  test('mesmo que só como parte de uma palavra', () => {
    expect(pesquisar('caf lis')).toEqual(['Café Central']);
    expect(pesquisar('entr')).toEqual(['Café Central']);
  });

  test('a palavra tem de caber num campo: não se junta o fim de um ao início de outro', () => {
    expect(pesquisar('centrald')).toEqual([]);
    expect(pesquisar('centrallisboa')).toEqual([]);
  });

  test('a marca por revelar encontra-se com "não revela", "revelar" e "não quer revelar"', () => {
    for (const pesquisa of ['não revela', 'revelar', 'não quer revelar', 'nao quer', 'NÃO REVELA']) {
      expect([pesquisa, pesquisar(pesquisa)]).toEqual([pesquisa, ['Mercearia da Baixa']]);
    }
  });

  test('"cliente" não traz a marca por revelar, nem a fase Cliente', () => {
    expect(pesquisar('cliente')).toEqual([]);
    expect(pesquisar('o cliente não quer revelar')).toEqual([]);
  });

  test('com a caixa marcada, o que estivesse na marca não conta', () => {
    const lojas = [resumo({ nome: 'Estranha', marca_nao_revela: true, marca_atual: 'Marca Exemplo' })];
    expect(pesquisar('exemplo', lojas)).toEqual([]);
    expect(pesquisar('revelar', lojas)).toEqual(['Estranha']);
  });

  test('uma marca que diz "revelar" encontra-se como outra qualquer', () => {
    expect(pesquisar('revelar', [resumo({ nome: 'A', marca_atual: 'Revelar' })])).toEqual(['A']);
  });

  test('uma loja sem os campos, ou com o que não é texto, conta como vazia e não rebenta', () => {
    const lojas = [{ id: 'x', nome: 7, telefone: 912, localidade: ['Lisboa'], marca_atual: {} }];
    expect(pesquisar('7', lojas)).toEqual([]);
    expect(pesquisar('lisboa', lojas)).toEqual([]);
  });

  test('não muda a lista dada', () => {
    const lojas = [...LOJAS];
    lojasDaPesquisa(lojas, 'café');
    expect(lojas).toEqual(LOJAS);
  });
});

test('palavrasDaPesquisa: sem acentos, em minúsculas e sem os espaços', () => {
  expect(palavrasDaPesquisa('  Café   LISBOA ')).toEqual(['cafe', 'lisboa']);
  expect(palavrasDaPesquisa('a\tb\nc')).toEqual(['a', 'b', 'c']);
  expect(palavrasDaPesquisa('')).toEqual([]);
  expect(palavrasDaPesquisa('   ')).toEqual([]);
  for (const valor of [null, undefined, 7, {}]) expect(palavrasDaPesquisa(valor)).toEqual([]);
});

// --- As pastilhas --------------------------------------------------------------------------------

describe('pastilhasDeFase', () => {
  test('"Todas" e uma por fase, pela ordem do funil, com a cor do pino e o número', () => {
    expect(pastilhasDeFase(LOJAS, FASE_TODAS)).toEqual([
      { valor: 'todas', rotulo: 'Todas', classeCor: null, numero: 4, escolhida: true },
      { valor: 'potencial', rotulo: 'Potencial', classeCor: 'crm-amostra-fase pino--potencial', numero: 1, escolhida: false },
      { valor: 'contactada', rotulo: 'A aguardar amostra', classeCor: 'crm-amostra-fase pino--contactada', numero: 0, escolhida: false },
      { valor: 'amostra', rotulo: 'Amostra recebida', classeCor: 'crm-amostra-fase pino--amostra', numero: 0, escolhida: false },
      { valor: 'fecho', rotulo: 'A aguardar fecho', classeCor: 'crm-amostra-fase pino--fecho', numero: 0, escolhida: false },
      { valor: 'cliente', rotulo: 'Cliente', classeCor: 'crm-amostra-fase pino--cliente', numero: 2, escolhida: false },
      { valor: 'perdida', rotulo: 'Perdida', classeCor: 'crm-amostra-fase pino--perdida', numero: 1, escolhida: false },
    ]);
  });

  test('escolhe-se uma de cada vez', () => {
    const escolhidas = pastilhasDeFase(LOJAS, 'cliente').filter((pastilha) => pastilha.escolhida);
    expect(escolhidas.map((pastilha) => pastilha.valor)).toEqual(['cliente']);
  });

  test('uma fase desconhecida só conta em "Todas"', () => {
    const pastilhas = pastilhasDeFase([resumo({ fase: 'estranha' })], FASE_TODAS);
    expect(pastilhas.map((pastilha) => pastilha.numero)).toEqual([1, 0, 0, 0, 0, 0, 0]);
  });
});

test('lojasDaFase: "Todas" fica com tudo; uma fase, só as dela', () => {
  expect(lojasDaFase(LOJAS, FASE_TODAS)).toBe(LOJAS);
  expect(nomes(lojasDaFase(LOJAS, 'cliente'))).toEqual(['Café Central', 'Mercearia da Baixa']);
  expect(lojasDaFase(LOJAS, 'amostra')).toEqual([]);
});

// --- As linhas -----------------------------------------------------------------------------------

describe('linhaDaLoja', () => {
  test('tudo preenchido: a cor, o nome, a fase em texto e os detalhes, pela ordem do desenho', () => {
    expect(linhaDaLoja(CAFE, '/crm')).toEqual({
      id: ID_CAFE,
      nome: 'Café Central',
      classeCor: 'crm-amostra-fase pino--cliente',
      fase: 'Cliente',
      detalhes: [
        { rotulo: null, texto: 'Lisboa' },
        { rotulo: 'Marca:', texto: 'Marca Exemplo' },
        { rotulo: 'Consumo:', texto: '2 baldes grandes' },
        { rotulo: 'Último contacto:', texto: '5 nov 2026' },
      ],
      caminho: `/crm/lojas/${ID_CAFE}`,
      estado: { origem: 'clientes' },
    });
  });

  test('o que está vazio não aparece, exceto o último contacto', () => {
    expect(linhaDaLoja(QUIOSQUE, '/crm').detalhes).toEqual([{ rotulo: null, texto: 'Ainda sem contactos' }]);
    const soEspacos = resumo({ localidade: '  ', marca_atual: ' ', consumo_semanal: '\t' });
    expect(linhaDaLoja(soEspacos, '/crm').detalhes).toEqual([{ rotulo: null, texto: 'Ainda sem contactos' }]);
  });

  test('com a marca por revelar lê-se "Marca: não revela"', () => {
    expect(linhaDaLoja(MERCEARIA, '/crm').detalhes).toEqual([
      { rotulo: null, texto: 'Porto' },
      { rotulo: 'Marca:', texto: 'não revela' },
      { rotulo: null, texto: 'Ainda sem contactos' },
    ]);
  });

  test('a fase em texto é a do `FASES`; uma fase desconhecida não tem cor e escreve-se como veio', () => {
    expect(linhaDaLoja(resumo({ fase: 'contactada' }), '/crm').fase).toBe('A aguardar amostra');
    expect(linhaDaLoja(resumo({ fase: 'estranha' }), '/crm')).toMatchObject({ classeCor: null, fase: 'estranha' });
    expect(linhaDaLoja(resumo({ fase: null }), '/crm')).toMatchObject({ classeCor: null, fase: '' });
  });

  test('o caminho é o da casa em que se está, com o id num só pedaço', () => {
    expect(linhaDaLoja(CAFE, '/admin/crm').caminho).toBe(`/admin/crm/lojas/${ID_CAFE}`);
    expect(linhaDaLoja(resumo({ id: 'a/b' }), '/crm').caminho).toBe('/crm/lojas/a%2Fb');
  });

  test('os dados ficam como texto: <b>x</b> fica tal e qual', () => {
    expect(linhaDaLoja(resumo({ nome: '<b>x</b>' }), '/crm').nome).toBe('<b>x</b>');
  });
});

test('semResultados: com texto, "Limpar pesquisa"; sem texto, só a frase', () => {
  expect(semResultados('café')).toEqual({ texto: TEXTO_SEM_RESULTADOS, limpar: true });
  expect(semResultados('')).toEqual({ texto: 'Sem lojas nesta fase.', limpar: false });
  expect(semResultados('   ')).toEqual({ texto: 'Sem lojas nesta fase.', limpar: false });
});

// --- A ficha aberta pela lista -------------------------------------------------------------------

describe('veioDaLista', () => {
  test('só com o `state` da lista', () => {
    expect(ORIGEM_LISTA).toBe('clientes');
    expect(veioDaLista({ origem: 'clientes' })).toBe(true);
    expect(veioDaLista(linhaDaLoja(CAFE, '/crm').estado)).toBe(true);
  });

  test('o mapa, a ligação direta, "Sim, abrir X" e o aviso de outro ecrã não mostram "Voltar à lista"', () => {
    for (const estado of [null, undefined, {}, { aviso: 'Loja guardada' }, { origem: 'mapa' }, 'clientes', 1]) {
      expect([estado, veioDaLista(estado)]).toEqual([estado, false]);
    }
  });

  test('caminhoDaLista: a lista da mesma casa', () => {
    expect(caminhoDaLista('/crm')).toBe('/crm/clientes');
    expect(caminhoDaLista('/admin/crm')).toBe('/admin/crm/clientes');
  });
});

// --- A sessão do browser -------------------------------------------------------------------------

function armazenamentoFalso(inicial = {}) {
  const dados = new Map(Object.entries(inicial));
  return {
    dados,
    getItem: (chave) => (dados.has(chave) ? dados.get(chave) : null),
    setItem: (chave, valor) => dados.set(chave, String(valor)),
  };
}

describe('a pesquisa e a fase na sessão', () => {
  test('sem nada guardado: sem pesquisa e todas as fases', () => {
    expect(filtrosClientesPadrao()).toEqual({ pesquisa: '', fase: 'todas' });
    expect(carregarFiltrosClientes(armazenamentoFalso())).toEqual({ pesquisa: '', fase: 'todas' });
  });

  test('guardar e carregar: fica o texto tal como foi escrito e a fase', () => {
    const storage = armazenamentoFalso();
    expect(guardarFiltrosClientes(storage, { pesquisa: ' Café ', fase: 'cliente' })).toBe(true);
    expect(JSON.parse(storage.getItem('crm.clientes'))).toEqual({ pesquisa: ' Café ', fase: 'cliente' });
    expect(carregarFiltrosClientes(storage)).toEqual({ pesquisa: ' Café ', fase: 'cliente' });
  });

  test('normalizar: uma fase que não existe volta a "Todas" e o que não é texto fica vazio', () => {
    expect(normalizarFiltrosClientes({ pesquisa: 'x', fase: 'estranha' })).toEqual({ pesquisa: 'x', fase: 'todas' });
    expect(normalizarFiltrosClientes({ pesquisa: 7, fase: 'todas' })).toEqual({ pesquisa: '', fase: 'todas' });
    expect(normalizarFiltrosClientes({ pesquisa: 'x', extra: 1, fase: 'perdida' })).toEqual({ pesquisa: 'x', fase: 'perdida' });
    for (const dados of [null, undefined, 'x', 3, ['cliente']]) {
      expect(normalizarFiltrosClientes(dados)).toEqual({ pesquisa: '', fase: 'todas' });
    }
  });

  test('um valor estragado no armazenamento volta ao início', () => {
    for (const texto of ['{', 'null', '7', '"x"', '[]']) {
      expect(carregarFiltrosClientes(armazenamentoFalso({ 'crm.clientes': texto }))).toEqual({ pesquisa: '', fase: 'todas' });
    }
  });

  test('à prova de falhas: sem armazenamento, ou se ele lançar, nada rebenta', () => {
    const lanca = {
      getItem() { throw new Error('bloqueado'); },
      setItem() { throw new Error('cheio'); },
    };
    for (const storage of [null, undefined, lanca]) {
      expect(carregarFiltrosClientes(storage)).toEqual({ pesquisa: '', fase: 'todas' });
      expect(guardarFiltrosClientes(storage, { pesquisa: 'x', fase: 'cliente' })).toBe(false);
    }
  });

  test('não se mistura com os filtros do mapa: chaves diferentes, e um não mexe no outro', () => {
    expect(CHAVE_CLIENTES).not.toBe(CHAVE_FILTROS);
    const storage = armazenamentoFalso();
    guardarFiltros(storage, { fases: ['cliente'], regiao: 'sem' });
    guardarFiltrosClientes(storage, { pesquisa: 'café', fase: 'perdida' });
    expect(carregarFiltros(storage)).toEqual({ fases: new Set(['cliente']), regiao: 'sem' });
    expect(carregarFiltrosClientes(storage)).toEqual({ pesquisa: 'café', fase: 'perdida' });
    expect(carregarFiltrosClientes(armazenamentoFalso({ [CHAVE_FILTROS]: '{"fase":"cliente","pesquisa":"x"}' })))
      .toEqual({ pesquisa: '', fase: 'todas' });
    expect(filtrosPadrao().fases.size).toBe(6);
  });
});

// --- O ecrã --------------------------------------------------------------------------------------

function adiada() {
  let resolver;
  let rejeitar;
  const promessa = new Promise((res, rej) => {
    resolver = res;
    rejeitar = rej;
  });
  return { promessa, resolver, rejeitar };
}

const assentar = () => new Promise((r) => {
  setTimeout(r, 0);
});

function montar({
  base = '/crm', storage = armazenamentoFalso(), online = true, comRede = false,
} = {}) {
  const pedidos = [];
  const listarLojas = jest.fn(() => {
    const pedido = adiada();
    pedidos.push(pedido);
    return pedido.promessa;
  });
  const janela = new EventTarget();
  const navegador = { onLine: online };
  const rede = comRede ? criarEstadoRede(janela, navegador) : null;
  const vistas = [];
  const ecra = criarListaClientes({
    api: { listarLojas }, rede, base, storage, aoMudarVista: (vista) => vistas.push(vista),
  });
  const mudarRede = (ligado) => {
    navegador.onLine = ligado;
    janela.dispatchEvent(new Event(ligado ? 'online' : 'offline'));
  };
  return {
    ecra, listarLojas, pedidos, vistas, storage, mudarRede, vista: () => ecra.vista,
  };
}

async function responder(m, lojas = LOJAS) {
  m.pedidos.at(-1).resolver(JSON.parse(JSON.stringify(lojas)));
  await assentar();
}

async function falhar(m, erro) {
  m.pedidos.at(-1).rejeitar(erro);
  await assentar();
}

async function carregada(opcoes, lojas) {
  const m = montar(opcoes);
  m.ecra.iniciar();
  await responder(m, lojas);
  return m;
}

const erroSemRede = () => new ErroCrm({ codigo: 'sem_rede', mensagem: MENSAGEM_SEM_REDE });
const nomesDaVista = (m) => m.vista().linhas.map((linha) => linha.nome);
const numeros = (m) => Object.fromEntries(m.vista().pastilhas.map((pastilha) => [pastilha.valor, pastilha.numero]));

describe('criarListaClientes', () => {
  test('criar não pede nada; iniciar pede uma vez, a carregar', () => {
    const m = montar();
    expect(m.listarLojas).not.toHaveBeenCalled();
    expect(m.vista()).toMatchObject({ estado: 'a_carregar', titulo: 'Clientes', falha: null, linhas: [], pastilhas: [] });
    m.ecra.iniciar();
    m.ecra.iniciar();
    expect(m.listarLojas).toHaveBeenCalledTimes(1);
    expect(m.vista().estado).toBe('a_carregar');
  });

  test('pronto: todas as lojas, pela ordem do GET /lojas, e as pastilhas', async () => {
    const m = await carregada({}, [TASCA, CAFE, MERCEARIA, QUIOSQUE]);
    expect(m.vista().estado).toBe('pronto');
    expect(nomesDaVista(m)).toEqual(['Tasca Antiga', 'Café Central', 'Mercearia da Baixa', 'Quiosque Novo']);
    expect(numeros(m)).toEqual({
      todas: 4, potencial: 1, contactada: 0, amostra: 0, fecho: 0, cliente: 2, perdida: 1,
    });
    expect(m.vista().semResultados).toBe(null);
  });

  test('escolher uma fase: só as dela; os números não mudam', async () => {
    const m = await carregada();
    m.ecra.escolherFase('cliente');
    expect(m.vista().fase).toBe('cliente');
    expect(nomesDaVista(m)).toEqual(['Café Central', 'Mercearia da Baixa']);
    expect(numeros(m).todas).toBe(4);
    expect(m.vista().pastilhas.filter((pastilha) => pastilha.escolhida).map((pastilha) => pastilha.valor)).toEqual(['cliente']);
    m.ecra.escolherFase('todas');
    expect(nomesDaVista(m)).toHaveLength(4);
  });

  test('uma fase que não existe não muda nada', async () => {
    const m = await carregada();
    const antes = m.vista();
    for (const fase of ['estranha', null, undefined, 7, '']) m.ecra.escolherFase(fase);
    expect(m.vista()).toBe(antes);
  });

  test('os números contam só as lojas que batem com a pesquisa, seja qual for a fase escolhida', async () => {
    const m = await carregada();
    m.ecra.escolherFase('perdida');
    m.ecra.mudarPesquisa('lisboa');
    expect(numeros(m)).toEqual({
      todas: 1, potencial: 0, contactada: 0, amostra: 0, fecho: 0, cliente: 1, perdida: 0,
    });
    expect(m.vista().linhas).toEqual([]);
  });

  test('filtra enquanto se escreve, e o campo fica como foi escrito', async () => {
    const m = await carregada();
    m.ecra.mudarPesquisa('Cafe ');
    expect(m.vista().pesquisa).toBe('Cafe ');
    expect(nomesDaVista(m)).toEqual(['Café Central']);
    m.ecra.mudarPesquisa('Cafe Porto');
    expect(nomesDaVista(m)).toEqual([]);
    expect(m.listarLojas).toHaveBeenCalledTimes(1); // no browser, sem outro pedido
  });

  test('sem resultados com texto: "Limpar pesquisa", que só limpa o texto e deixa a fase', async () => {
    const m = await carregada();
    m.ecra.escolherFase('cliente');
    m.ecra.mudarPesquisa('não existe');
    expect(m.vista().semResultados).toEqual({ texto: TEXTO_SEM_RESULTADOS, limpar: true });
    expect(m.vista().pastilhas).toHaveLength(7); // as pastilhas continuam visíveis ("Todas" e as seis fases)
    m.ecra.limparPesquisa();
    expect(m.vista()).toMatchObject({ pesquisa: '', fase: 'cliente', semResultados: null });
    expect(nomesDaVista(m)).toEqual(['Café Central', 'Mercearia da Baixa']);
  });

  test('sem resultados sem texto: só a frase, com as pastilhas visíveis', async () => {
    const m = await carregada();
    m.ecra.escolherFase('amostra');
    expect(m.vista().semResultados).toEqual({ texto: 'Sem lojas nesta fase.', limpar: false });
    expect(m.vista().pastilhas).toHaveLength(7);
    m.ecra.mudarPesquisa('   ');
    expect(m.vista().semResultados).toEqual({ texto: 'Sem lojas nesta fase.', limpar: false });
  });

  test('sem lojas: o estado próprio, com a ligação para "Nova loja" da mesma casa', async () => {
    const m = await carregada({ base: '/admin/crm' }, []);
    expect(m.vista()).toMatchObject({
      estado: 'sem_lojas', novaLoja: '/admin/crm/lojas/nova', linhas: [], pastilhas: [], semResultados: null,
    });
  });

  test('a falha: a mensagem e "Tentar novamente" (um toque, um pedido)', async () => {
    const m = montar();
    m.ecra.iniciar();
    await falhar(m, erroSemRede());
    expect(m.vista()).toMatchObject({ estado: 'falha', falha: { mensagem: MENSAGEM_SEM_REDE, aTentar: false } });
    m.ecra.tentarDeNovo();
    m.ecra.tentarDeNovo();
    expect(m.listarLojas).toHaveBeenCalledTimes(2);
    expect(m.vista().falha.aTentar).toBe(true);
    await responder(m);
    expect(m.vista()).toMatchObject({ estado: 'pronto', falha: null });
  });

  test('um erro sem mensagem, ou uma resposta que não é uma lista: a mensagem genérica', async () => {
    const semMensagem = montar();
    semMensagem.ecra.iniciar();
    await falhar(semMensagem, new Error('rebentou'));
    expect(semMensagem.vista().falha.mensagem).toBe(MENSAGEM_ERRO_INESPERADO);
    const estranha = montar();
    estranha.ecra.iniciar();
    await responder(estranha, { lojas: [] });
    expect(estranha.vista()).toMatchObject({ estado: 'falha', falha: { mensagem: MENSAGEM_ERRO_INESPERADO } });
  });

  test('tentarDeNovo sem falha não pede nada', async () => {
    const m = await carregada();
    m.ecra.tentarDeNovo();
    expect(m.listarLojas).toHaveBeenCalledTimes(1);
  });

  test('uma linha estragada (sem id) não entra', async () => {
    const m = await carregada({}, [CAFE, null, resumo({ id: '' }), resumo({ id: 7 })]);
    expect(nomesDaVista(m)).toEqual(['Café Central']);
  });

  test('a rede que volta pede outra vez a lista que falhou, e não a que chegou', async () => {
    const m = montar({ comRede: true });
    m.ecra.iniciar();
    await falhar(m, erroSemRede());
    m.mudarRede(false);
    expect(m.listarLojas).toHaveBeenCalledTimes(1);
    m.mudarRede(true);
    expect(m.listarLojas).toHaveBeenCalledTimes(2);
    await responder(m);
    m.mudarRede(false);
    m.mudarRede(true);
    expect(m.listarLojas).toHaveBeenCalledTimes(2);
  });

  test('a pesquisa e a fase ficam na sessão, e continuam lá ao voltar da ficha', async () => {
    const m = await carregada();
    m.ecra.mudarPesquisa('café');
    m.ecra.escolherFase('cliente');
    expect(JSON.parse(m.storage.getItem('crm.clientes'))).toEqual({ pesquisa: 'café', fase: 'cliente' });
    m.ecra.destruir();
    const volta = await carregada({ storage: m.storage });
    expect(volta.vista()).toMatchObject({ pesquisa: 'café', fase: 'cliente' });
    expect(nomesDaVista(volta)).toEqual(['Café Central']);
  });

  test('limpar a pesquisa também fica na sessão', async () => {
    const m = await carregada({ storage: armazenamentoFalso({ 'crm.clientes': '{"pesquisa":"café","fase":"cliente"}' }) });
    m.ecra.limparPesquisa();
    expect(JSON.parse(m.storage.getItem('crm.clientes'))).toEqual({ pesquisa: '', fase: 'cliente' });
  });

  test('sem armazenamento a lista funciona na mesma', async () => {
    const m = await carregada({ storage: null });
    m.ecra.mudarPesquisa('café');
    expect(nomesDaVista(m)).toEqual(['Café Central']);
  });

  test('a vista é nova a cada mudança, congelada a fundo, e vai para o aoMudarVista', async () => {
    const m = await carregada();
    const antes = m.vista();
    m.ecra.mudarPesquisa('café');
    expect(m.vista()).not.toBe(antes);
    expect(m.vistas.at(-1)).toBe(m.vista());
    expect(Object.isFrozen(m.vista())).toBe(true);
    expect(Object.isFrozen(m.vista().linhas[0].detalhes[0])).toBe(true);
    expect(Object.isFrozen(m.vista().pastilhas[0])).toBe(true);
  });

  test('a pesquisa só aceita texto', async () => {
    const m = await carregada();
    const antes = m.vista();
    for (const valor of [null, undefined, 7]) m.ecra.mudarPesquisa(valor);
    expect(m.vista()).toBe(antes);
  });

  test('depois de sair, as respostas atrasadas, a rede e os toques já não fazem nada', async () => {
    const m = montar({ comRede: true });
    m.ecra.iniciar();
    const vistas = m.vistas.length;
    m.ecra.destruir();
    await responder(m);
    m.mudarRede(false);
    m.mudarRede(true);
    m.ecra.mudarPesquisa('café');
    m.ecra.escolherFase('cliente');
    m.ecra.limparPesquisa();
    expect(m.vistas).toHaveLength(vistas);
    expect(m.listarLojas).toHaveBeenCalledTimes(1);
    expect(m.storage.getItem('crm.clientes')).toBe(null);
  });
});

// --- A página e a ficha, pelo texto (os componentes não têm Jest) --------------------------------

describe('a página CrmClientes e a ficha', () => {
  const pagina = fs.readFileSync(PAGINA, 'utf8');
  const ficha = fs.readFileSync(FICHA, 'utf8');

  test('a página importa o crm.css: é lazy, e sem ele a cor não aparece a quem abre a lista diretamente', () => {
    expect(pagina).toMatch(/^import '\.\.\/\.\.\/components\/crm\/crm\.css';$/m);
  });

  test('a página guarda no sessionStorage, com a leitura protegida, e não no localStorage', () => {
    expect(pagina).toMatch(/try \{\s+return window\.sessionStorage;\s+\} catch/);
    expect(pagina).not.toContain('localStorage.');
  });

  test('cada linha é um Link com o `state` da linha, e nada vai no endereço', () => {
    expect(pagina).toMatch(/<Link\s+to=\{linha\.caminho\}\s+state=\{linha\.estado\}/);
  });

  test('a página não carrega o mapa: funciona sem o Google', () => {
    expect(pagina).not.toMatch(/MapaLojas|carregadorGoogle|obterConfigMapa/);
  });

  test('"Voltar à lista" é um Link para a lista, e nunca um passo atrás no histórico', () => {
    expect(ficha).toMatch(/vista\.estado === 'ficha' && veioDaLista\(state\)/);
    expect(ficha).toMatch(/<Link to=\{caminhoDaLista\(base\)\}/);
    expect(ficha).not.toMatch(/navigate\(-1\)/);
  });
});
