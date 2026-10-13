/**
 * DEFINIÇÕES › REGIÕES — as regras do separador "Regiões", sem DOM.
 *
 * Porta de public/assets/js/componentes/definicoes-regioes.js do CRM autónomo
 * (etiqueta `referencia-standalone`), com os casos de
 * tests/js/definicoes-regioes.test.js (correções "T2.30 (Regiões —
 * subir/descer) e T2.9" e "T2.26 / T2.27 / T2.29 / T2.30 (componentes Sem
 * Jest)"): as funções puras `reordenarRegioes`, `proximaOrdem` e
 * `ordenarRegioes` tal e qual, e o ecrã como os membros da T2.29 — o que o
 * autónomo escrevia no DOM é uma `vista` congelada, entregue ao
 * `aoMudarVista`, e o `pages/crm/DefinicoesRegioes.js` só a desenha.
 *
 * Adaptações ao portal (plano T2.30):
 *   - ids uuid em texto (o desempate da ordem compara-os como texto, como o
 *     `GET /regioes`);
 *   - a mensagem da ordem que não gravou é um aviso de erro (toast,
 *     `aoAvisarErro`), e não um parágrafo por cima da lista; o 404 de outra
 *     pessoa (a região já não existe) também, e a lista volta a pedir-se;
 *   - "Região adicionada", "Nome guardado", "Ordem guardada" e "Região
 *     apagada" são avisos de sucesso (toast, `aoAvisar`);
 *   - enquanto o nome novo grava, o campo e o Cancelar não mexem (no autónomo
 *     o Cancelar fechava a edição a meio do pedido);
 *   - a pergunta do Apagar tem um aviso por baixo ("Só se apagam regiões sem
 *     lojas.").
 */
import { ErroCrm, MENSAGEM_ERRO_INESPERADO, MENSAGEM_SEM_REDE } from './api';
import { criarEstadoRede } from './rede';
import {
  NOME_MAXIMO_REGIAO,
  RESPOSTA_APAGAR_REGIAO,
  TEXTO_A_ADICIONAR,
  TEXTO_A_APAGAR,
  TEXTO_A_CARREGAR_REGIOES,
  TEXTO_A_GUARDAR,
  TEXTO_ADICIONAR,
  TEXTO_APAGAR,
  TEXTO_APAGAR_REGIAO_AVISO,
  TEXTO_CANCELAR,
  TEXTO_DESCER,
  TEXTO_DESCRICAO_REGIOES,
  TEXTO_GUARDAR,
  TEXTO_MUDAR_NOME,
  TEXTO_NOME_GUARDADO,
  TEXTO_NOVA_REGIAO,
  TEXTO_ORDEM_GUARDADA,
  TEXTO_REGIAO_ADICIONADA,
  TEXTO_REGIAO_APAGADA,
  TEXTO_SEM_REGIOES,
  TEXTO_SUBIR,
  TITULO_REGIOES,
  criarRegioes,
  ordenarRegioes,
  perguntaApagarRegiao,
  proximaOrdem,
  regiaoValida,
  reordenarRegioes,
  rotulosRegiao,
} from './regioes';

// Ids uuid4 em texto (os do `str(uuid.uuid4())` do servidor). Os quatro primeiros ordenam-se como os inteiros
// 1, 2, 3, 4 do autónomo.
const ID_LISBOA = '5e1b6c2a-0000-4000-8000-000000000001';
const ID_PORTO = '5e1b6c2a-0000-4000-8000-000000000002';
const ID_SETUBAL = '5e1b6c2a-0000-4000-8000-000000000003';
const ID_FARO = '5e1b6c2a-0000-4000-8000-000000000004';
const ID_OUTRA = 'f0e1d2c3-b4a5-4697-a8b9-cadbecfd0e1f';

const REGIOES = Object.freeze([
  Object.freeze({ id: ID_LISBOA, nome: 'Lisboa', ordem: 0 }),
  Object.freeze({ id: ID_PORTO, nome: 'Porto', ordem: 0 }),
  Object.freeze({ id: ID_SETUBAL, nome: 'Setúbal', ordem: 0 }),
]);

// Uma cópia funda, como a que o servidor manda (o jsdom do Jest 27 não tem `structuredClone`).
const copia = (valor) => JSON.parse(JSON.stringify(valor));

// --- Textos --------------------------------------------------------------------------------------

test('os textos exatos do separador', () => {
  expect(TITULO_REGIOES).toBe('Regiões');
  expect(TEXTO_DESCRICAO_REGIOES).toBe('Os filtros do mapa e o campo Região das lojas mostram-nas por esta ordem.');
  expect(TEXTO_A_CARREGAR_REGIOES).toBe('A carregar as regiões…');
  expect(TEXTO_SEM_REGIOES).toBe('Ainda não há regiões.');
  expect(TEXTO_NOVA_REGIAO).toBe('Nova região');
  expect([TEXTO_ADICIONAR, TEXTO_A_ADICIONAR]).toEqual(['Adicionar', 'A adicionar…']);
  expect([TEXTO_SUBIR, TEXTO_DESCER, TEXTO_MUDAR_NOME, TEXTO_APAGAR, TEXTO_A_APAGAR]).toEqual([
    'Subir', 'Descer', 'Mudar o nome', 'Apagar', 'A apagar…',
  ]);
  expect([TEXTO_GUARDAR, TEXTO_A_GUARDAR, TEXTO_CANCELAR]).toEqual(['Guardar', 'A guardar…', 'Cancelar']);
  expect(TEXTO_APAGAR_REGIAO_AVISO).toBe('Só se apagam regiões sem lojas.');
  expect([TEXTO_REGIAO_ADICIONADA, TEXTO_NOME_GUARDADO, TEXTO_ORDEM_GUARDADA, TEXTO_REGIAO_APAGADA]).toEqual([
    'Região adicionada', 'Nome guardado', 'Ordem guardada', 'Região apagada',
  ]);
  // O tamanho do nome no servidor (`dominio/regioes.py::NOME_MAXIMO`, a coluna do autónomo).
  expect(NOME_MAXIMO_REGIAO).toBe(100);
});

test('rotulosRegiao: o que o leitor de ecrã lê em cada ação, em pt-PT, com o nome tal e qual', () => {
  expect(rotulosRegiao('Porto')).toEqual({
    subir: 'Subir Porto',
    descer: 'Descer Porto',
    mudar: 'Mudar o nome de Porto',
    apagar: 'Apagar Porto',
    novoNome: 'Novo nome de Porto',
  });
  expect(Object.isFrozen(rotulosRegiao('Porto'))).toBe(true);
  expect(rotulosRegiao('<b>x</b>').apagar).toBe('Apagar <b>x</b>');
});

test('perguntaApagarRegiao: a pergunta com o nome, o aviso, e Cancelar primeiro (a escolha que não apaga)', () => {
  const pergunta = perguntaApagarRegiao(REGIOES[1]);
  expect(pergunta).toEqual({
    pergunta: 'Apagar a região Porto?',
    aviso: 'Só se apagam regiões sem lojas.',
    botoes: [
      { texto: 'Cancelar', valor: null, variante: 'normal' },
      { texto: 'Sim, apagar', valor: RESPOSTA_APAGAR_REGIAO, variante: 'perigo' },
    ],
  });
  expect(RESPOSTA_APAGAR_REGIAO).toBe('apagar');
  expect(Object.isFrozen(pergunta)).toBe(true);
  expect(Object.isFrozen(pergunta.botoes)).toBe(true);
  expect(pergunta.botoes.every(Object.isFrozen)).toBe(true);
});

// --- Funções puras (as 4 do autónomo) ------------------------------------------------------------

test('reordenarRegioes: troca com a vizinha e numera a ordem toda (0, 1, 2…); só muda as que mudaram', () => {
  expect(reordenarRegioes(REGIOES, ID_SETUBAL, -1)).toEqual({
    lista: [
      { id: ID_LISBOA, nome: 'Lisboa', ordem: 0 },
      { id: ID_SETUBAL, nome: 'Setúbal', ordem: 1 },
      { id: ID_PORTO, nome: 'Porto', ordem: 2 },
    ],
    alteracoes: [{ id: ID_SETUBAL, ordem: 1 }, { id: ID_PORTO, ordem: 2 }],
  });
  const numeradas = [
    { id: ID_LISBOA, nome: 'A', ordem: 0 }, { id: ID_PORTO, nome: 'B', ordem: 1 }, { id: ID_SETUBAL, nome: 'C', ordem: 2 },
  ];
  expect(reordenarRegioes(numeradas, ID_LISBOA, 1).alteracoes).toEqual([{ id: ID_PORTO, ordem: 0 }, { id: ID_LISBOA, ordem: 1 }]);
  expect(reordenarRegioes(numeradas, ID_LISBOA, 1).lista.map((r) => r.id)).toEqual([ID_PORTO, ID_LISBOA, ID_SETUBAL]);
});

test('reordenarRegioes: a primeira não sobe, a última não desce, e uma que não existe não mexe', () => {
  expect(reordenarRegioes(REGIOES, ID_LISBOA, -1)).toBe(null);
  expect(reordenarRegioes(REGIOES, ID_SETUBAL, 1)).toBe(null);
  expect(reordenarRegioes(REGIOES, ID_OUTRA, 1)).toBe(null);
  expect(REGIOES[0].ordem).toBe(0);
});

test('reordenarRegioes: só sobe (-1) ou desce (1), e nunca altera a lista recebida', () => {
  for (const direcao of [0, 2, -2, '1', null, undefined]) {
    expect(reordenarRegioes(REGIOES, ID_PORTO, direcao)).toBe(null);
  }
  const lista = copia(REGIOES);
  const resultado = reordenarRegioes(lista, ID_PORTO, 1);
  expect(lista).toEqual(copia(REGIOES));
  expect(resultado.lista[2]).not.toBe(lista[1]);
});

test('ordenarRegioes: como o servidor (pela ordem e depois pelo nome, sem distinguir maiúsculas nem acentos)', () => {
  const lista = [
    { id: ID_FARO, nome: 'évora', ordem: 1 },
    { id: ID_PORTO, nome: 'Porto', ordem: 0 },
    { id: ID_SETUBAL, nome: 'Faro', ordem: 1 },
    { id: ID_LISBOA, nome: 'aveiro', ordem: 0 },
  ];
  expect(ordenarRegioes(lista).map((r) => r.id)).toEqual([ID_LISBOA, ID_PORTO, ID_FARO, ID_SETUBAL]);
});

test('ordenarRegioes: o mesmo nome desempata pelo id, como texto; não altera a lista recebida', () => {
  const lista = [
    { id: ID_OUTRA, nome: 'Évora', ordem: 2 },
    { id: ID_PORTO, nome: 'evora', ordem: 2 },
    { id: ID_LISBOA, nome: 'Zona', ordem: -1 },
  ];
  const antes = copia(lista);
  expect(ordenarRegioes(lista).map((r) => r.id)).toEqual([ID_LISBOA, ID_PORTO, ID_OUTRA]);
  expect(lista).toEqual(antes);
  // Os nomes que só diferem nos acentos ou nas maiúsculas são o mesmo nome: decide o id, mesmo que "evora"
  // viesse antes de "Évora" a distinguir acentos.
  const trocados = [
    { id: ID_OUTRA, nome: 'evora', ordem: 2 },
    { id: ID_PORTO, nome: 'Évora', ordem: 2 },
    { id: ID_SETUBAL, nome: 'ÉVORA', ordem: 2 },
  ];
  expect(ordenarRegioes(trocados).map((r) => r.id)).toEqual([ID_PORTO, ID_SETUBAL, ID_OUTRA]);
});

test('proximaOrdem: uma nova região vai para o fim', () => {
  expect(proximaOrdem([])).toBe(0);
  expect(proximaOrdem(REGIOES)).toBe(1);
  expect(proximaOrdem([{ id: ID_LISBOA, nome: 'A', ordem: 7 }, { id: ID_PORTO, nome: 'B', ordem: 2 }])).toBe(8);
  expect(proximaOrdem([{ id: ID_LISBOA, nome: 'A', ordem: -5 }])).toBe(-4);
});

test('regiaoValida: id uuid em texto, nome em texto e ordem inteira', () => {
  for (const r of REGIOES) expect(regiaoValida(r)).toBe(true);
  expect(regiaoValida({ id: ID_OUTRA, nome: '', ordem: -3 })).toBe(true);
  for (const mau of [
    null, undefined, 'x', [], {}, [REGIOES[0]],
    { ...REGIOES[0], id: 1 }, { ...REGIOES[0], id: 'regiao-1' }, { ...REGIOES[0], id: ID_LISBOA.toUpperCase() },
    { ...REGIOES[0], nome: null }, { ...REGIOES[0], nome: 7 },
    { ...REGIOES[0], ordem: '0' }, { ...REGIOES[0], ordem: 1.5 }, { ...REGIOES[0], ordem: null }, { ...REGIOES[0], ordem: 2 ** 53 },
  ]) {
    expect(regiaoValida(mau)).toBe(false);
  }
});

// --- O ecrã --------------------------------------------------------------------------------------

// Cada pedido fica pendente até o teste lhe responder (ou o fazer falhar).
function apiFalsa() {
  const pedidos = [];
  const pedir = (nome) => (...argumentos) => new Promise((resolver, rejeitar) => {
    pedidos.push({ nome, argumentos, resolver, rejeitar });
  });
  return {
    pedidos,
    listarRegioes: pedir('listarRegioes'),
    criarRegiao: pedir('criarRegiao'),
    alterarRegiao: pedir('alterarRegiao'),
    apagarRegiao: pedir('apagarRegiao'),
  };
}

const assentar = () => new Promise((r) => {
  setTimeout(r, 0);
});

// Monta o ecrã como a página (DefinicoesRegioes): cria e inicia (pede a lista e ouve a rede).
function montar({ iniciar = true, online = true } = {}) {
  const api = apiFalsa();
  const janela = new EventTarget();
  const navegador = { onLine: online };
  const avisos = [];
  const erros = [];
  const focos = [];
  const vistas = [];
  const ecra = criarRegioes({
    api,
    rede: criarEstadoRede(janela, navegador),
    aoMudarVista: (vista) => vistas.push(vista),
    aoAvisar: (texto) => avisos.push(texto),
    aoAvisarErro: (texto) => erros.push(texto),
    aoFocar: (alvo) => focos.push(alvo),
  });
  if (iniciar) ecra.iniciar();
  const mudarRede = (ligado) => {
    navegador.onLine = ligado;
    janela.dispatchEvent(new Event(ligado ? 'online' : 'offline'));
  };
  return { api, ecra, avisos, erros, focos, vistas, mudarRede, vista: () => ecra.vista };
}

const pedidos = (m, nome) => m.api.pedidos.filter((p) => p.nome === nome);
const ultimo = (m, nome) => pedidos(m, nome).at(-1);
// 'listarRegioes', 'alterarRegiao <id>', … — o pedido e o id, quando o leva.
const resumo = (m) => m.api.pedidos.map((p) => (
  p.nome === 'listarRegioes' || p.nome === 'criarRegiao' ? p.nome : `${p.nome} ${p.argumentos[0]}`
));

async function responder(m, nome, dados) {
  ultimo(m, nome).resolver(dados);
  await assentar();
}

async function falhar(m, nome, erro) {
  ultimo(m, nome).rejeitar(erro);
  await assentar();
}

async function carregada(lista = REGIOES, opcoes = {}) {
  const m = montar(opcoes);
  await responder(m, 'listarRegioes', copia(lista));
  return m;
}

const nomes = (m) => m.vista().linhas.map((l) => l.nome);
const linhaDe = (m, nome) => m.vista().linhas.find((l) => l.nome === nome);
const erroSemRede = () => new ErroCrm({ codigo: 'sem_rede', mensagem: MENSAGEM_SEM_REDE });
const erroRepetida = () => new ErroCrm({ codigo: 'regiao_repetida', mensagem: 'Já existe uma região com este nome.', estado: 409 });
const erroComLojas = () => new ErroCrm({
  codigo: 'regiao_com_lojas', mensagem: 'Esta região tem lojas — mude-lhe o nome em vez de a apagar.', estado: 409,
});
const erro404 = () => new ErroCrm({ codigo: 'nao_encontrado', mensagem: 'Região não encontrada.', estado: 404 });
const erroValidacao = (campos) => new ErroCrm({ codigo: 'validacao', mensagem: 'Verifique os campos assinalados.', estado: 422, campos });

// --- Carregar ------------------------------------------------------------------------------------

test('criar não pede nada; iniciar pede a lista uma só vez', () => {
  const m = montar({ iniciar: false });
  expect(m.api.pedidos).toEqual([]);
  expect(m.vista()).toEqual({
    estado: 'a_carregar',
    falha: null,
    vazio: false,
    linhas: [],
    nova: { valor: '', erro: null, botao: { ativo: false, texto: 'Adicionar' } },
    pergunta: null,
  });
  expect(Object.isFrozen(m.vista())).toBe(true);
  m.ecra.iniciar();
  m.ecra.iniciar();
  expect(resumo(m)).toEqual(['listarRegioes']);
  expect(m.vista().estado).toBe('a_carregar');
});

test('pede as regiões e mostra-as pela ordem, cada uma com Subir, Descer, Mudar o nome e Apagar', async () => {
  const m = await carregada();
  expect(m.vista().estado).toBe('pronto');
  expect(m.vista().vazio).toBe(false);
  expect(nomes(m)).toEqual(['Lisboa', 'Porto', 'Setúbal']);
  expect(linhaDe(m, 'Porto')).toEqual({
    id: ID_PORTO,
    nome: 'Porto',
    podeSubir: true,
    podeDescer: true,
    ocupada: false,
    rotulos: rotulosRegiao('Porto'),
    edicao: null,
    erro: null,
    apagar: { ativo: true, texto: 'Apagar' },
  });
  expect(linhaDe(m, 'Lisboa').podeSubir).toBe(false); // a primeira não sobe
  expect(linhaDe(m, 'Setúbal').podeDescer).toBe(false); // a última não desce
  expect(linhaDe(m, 'Lisboa').podeDescer).toBe(true);
  expect(m.vista().nova.botao).toEqual({ ativo: true, texto: 'Adicionar' });
  expect(Object.isFrozen(m.vista().linhas)).toBe(true);
  expect(m.vista().linhas.every(Object.isFrozen)).toBe(true);
  expect(Object.isFrozen(linhaDe(m, 'Porto').apagar)).toBe(true);
  expect(Object.isFrozen(m.vista().nova)).toBe(true);
});

test('a lista chega desarrumada ou com linhas estragadas: fica pela ordem do servidor e só com as regiões', async () => {
  const m = await carregada([
    { id: ID_SETUBAL, nome: 'Setúbal', ordem: 2 },
    { id: 'regiao-7', nome: 'Má', ordem: 0 },
    null,
    { id: ID_PORTO, nome: 'Porto', ordem: 1 },
    { id: ID_LISBOA, nome: 'Lisboa', ordem: '0' },
    { id: ID_FARO, nome: 'Faro', ordem: 1 },
  ]);
  expect(nomes(m)).toEqual(['Faro', 'Porto', 'Setúbal']);
});

test('uma resposta que não é uma lista conta como nenhuma região', async () => {
  const m = await carregada({ regioes: REGIOES });
  expect(m.vista().estado).toBe('pronto');
  expect(m.vista().linhas).toEqual([]);
  expect(m.vista().vazio).toBe(true);
});

test('sem regiões: "Ainda não há regiões." e o campo para adicionar', async () => {
  const m = await carregada([]);
  expect(m.vista().vazio).toBe(true);
  expect(m.vista().nova.botao.ativo).toBe(true);
});

test('os nomes ficam texto: <b>x</b> é o nome e entra assim nos rótulos', async () => {
  const m = await carregada([{ id: ID_LISBOA, nome: '<b>x</b>', ordem: 0 }]);
  expect(nomes(m)).toEqual(['<b>x</b>']);
  expect(m.vista().linhas[0].rotulos.apagar).toBe('Apagar <b>x</b>');
});

test('falha ao carregar: a mensagem e "Tentar novamente" (um toque, um pedido); a rede que volta tenta outra vez', async () => {
  const m = montar();
  await falhar(m, 'listarRegioes', erroSemRede());
  expect(m.vista().estado).toBe('falha');
  expect(m.vista().falha).toEqual({ mensagem: MENSAGEM_SEM_REDE, aTentar: false });
  expect(m.vista().nova.botao.ativo).toBe(false);
  m.ecra.tentarDeNovo();
  m.ecra.tentarDeNovo();
  expect(pedidos(m, 'listarRegioes')).toHaveLength(2);
  expect(m.vista().falha).toEqual({ mensagem: MENSAGEM_SEM_REDE, aTentar: true });
  await falhar(m, 'listarRegioes', erroSemRede());
  m.mudarRede(false);
  expect(pedidos(m, 'listarRegioes')).toHaveLength(2);
  m.mudarRede(true);
  expect(pedidos(m, 'listarRegioes')).toHaveLength(3);
  await responder(m, 'listarRegioes', copia(REGIOES));
  expect(m.vista().estado).toBe('pronto');
  expect(m.vista().falha).toBe(null);
  m.mudarRede(true);
  m.ecra.tentarDeNovo();
  expect(pedidos(m, 'listarRegioes')).toHaveLength(3); // com a lista carregada não volta a pedir
});

test('um erro sem mensagem mostra o texto de erro inesperado', async () => {
  const m = montar();
  await falhar(m, 'listarRegioes', new Error('x'));
  expect(m.vista().falha.mensagem).toBe(MENSAGEM_ERRO_INESPERADO);
});

// --- Adicionar -----------------------------------------------------------------------------------

test('Adicionar: {nome, ordem} no fim da lista; a região aparece e o campo fica vazio para a seguinte', async () => {
  const m = await carregada();
  m.ecra.mudarNova('Faro');
  expect(m.vista().nova.valor).toBe('Faro');
  m.ecra.adicionar();
  expect(ultimo(m, 'criarRegiao').argumentos).toEqual([{ nome: 'Faro', ordem: 1 }]);
  expect(m.vista().nova.botao).toEqual({ ativo: false, texto: 'A adicionar…' });
  m.ecra.adicionar();
  expect(pedidos(m, 'criarRegiao')).toHaveLength(1); // um toque, um pedido
  await responder(m, 'criarRegiao', { id: ID_FARO, nome: 'Faro', ordem: 1 });
  expect(nomes(m)).toEqual(['Lisboa', 'Porto', 'Setúbal', 'Faro']);
  expect(m.vista().nova).toEqual({ valor: '', erro: null, botao: { ativo: true, texto: 'Adicionar' } });
  expect(m.focos).toEqual(['nova']); // pronto para a seguinte
  expect(m.avisos).toEqual(['Região adicionada']);
  expect(linhaDe(m, 'Setúbal').podeDescer).toBe(true); // Setúbal deixou de ser a última
  expect(resumo(m)).toEqual(['listarRegioes', 'criarRegiao']);
});

test('Adicionar a primeira: deixa de dizer "Ainda não há regiões."', async () => {
  const m = await carregada([]);
  m.ecra.mudarNova('Lisboa');
  m.ecra.adicionar();
  expect(ultimo(m, 'criarRegiao').argumentos).toEqual([{ nome: 'Lisboa', ordem: 0 }]);
  await responder(m, 'criarRegiao', { id: ID_LISBOA, nome: 'Lisboa', ordem: 0 });
  expect(m.vista().vazio).toBe(false);
  expect(nomes(m)).toEqual(['Lisboa']);
});

test('Adicionar um nome repetido (409) ou vazio (422): a mensagem do servidor junto ao campo, com o foco lá', async () => {
  const m = await carregada();
  m.ecra.mudarNova('lisboa');
  m.ecra.adicionar();
  await falhar(m, 'criarRegiao', erroRepetida());
  expect(m.vista().nova).toEqual({
    valor: 'lisboa', erro: 'Já existe uma região com este nome.', botao: { ativo: true, texto: 'Adicionar' },
  });
  expect(m.focos).toEqual(['nova']);
  expect(m.erros).toEqual([]);
  m.ecra.mudarNova('');
  expect(m.vista().nova.erro).toBe(null); // escrever tira o erro
  m.ecra.adicionar();
  expect(ultimo(m, 'criarRegiao').argumentos).toEqual([{ nome: '', ordem: 1 }]);
  expect(m.vista().nova.erro).toBe(null);
  await falhar(m, 'criarRegiao', erroValidacao({ nome: 'Indique o nome.' }));
  expect(m.vista().nova.erro).toBe('Indique o nome.');
  expect(nomes(m)).toEqual(['Lisboa', 'Porto', 'Setúbal']);
  expect(m.avisos).toEqual([]);
});

test('Adicionar sem rede, ou com o erro da ordem: a mensagem junto ao campo', async () => {
  const m = await carregada();
  m.ecra.mudarNova('Faro');
  m.ecra.adicionar();
  await falhar(m, 'criarRegiao', erroSemRede());
  expect(m.vista().nova.erro).toBe(MENSAGEM_SEM_REDE);
  m.ecra.adicionar();
  expect(m.vista().nova.erro).toBe(null); // o pedido seguinte tira-o
  await falhar(m, 'criarRegiao', erroValidacao({ ordem: 'A ordem tem de ser um número inteiro.' }));
  expect(m.vista().nova.erro).toBe('A ordem tem de ser um número inteiro.');
});

test('Adicionar com uma resposta que não é uma região: a lista vem outra vez do servidor', async () => {
  const m = await carregada();
  m.ecra.mudarNova('Faro');
  m.ecra.adicionar();
  await responder(m, 'criarRegiao', { id: 4, nome: 'Faro', ordem: 1 });
  expect(nomes(m)).toEqual(['Lisboa', 'Porto', 'Setúbal']);
  expect(m.avisos).toEqual(['Região adicionada']);
  expect(pedidos(m, 'listarRegioes')).toHaveLength(2);
  expect(m.vista().linhas.every((l) => l.ocupada)).toBe(true); // a lista a caminho
  await responder(m, 'listarRegioes', [...copia(REGIOES), { id: ID_FARO, nome: 'Faro', ordem: 1 }]);
  expect(nomes(m)).toEqual(['Lisboa', 'Porto', 'Setúbal', 'Faro']);
});

test('Adicionar: uma resposta com o id de uma região que já está na lista não a repete', async () => {
  const m = await carregada();
  m.ecra.mudarNova('Porto');
  m.ecra.adicionar();
  await responder(m, 'criarRegiao', { id: ID_PORTO, nome: 'Porto Novo', ordem: 3 });
  expect(nomes(m)).toEqual(['Lisboa', 'Setúbal', 'Porto Novo']);
});

test('Adicionar antes de a lista chegar não faz nada', () => {
  const m = montar();
  m.ecra.mudarNova('Faro');
  m.ecra.adicionar();
  expect(pedidos(m, 'criarRegiao')).toEqual([]);
});

// --- Subir e descer ------------------------------------------------------------------------------

test('Subir: a lista muda logo e grava a ordem nova, um pedido de cada vez; o foco fica no botão', async () => {
  const m = await carregada();
  m.ecra.subir(ID_SETUBAL);
  expect(nomes(m)).toEqual(['Lisboa', 'Setúbal', 'Porto']);
  expect(m.focos).toEqual([{ id: ID_SETUBAL, alvo: 'subir' }]);
  expect(resumo(m).slice(1)).toEqual([`alterarRegiao ${ID_SETUBAL}`]);
  expect(ultimo(m, 'alterarRegiao').argumentos).toEqual([ID_SETUBAL, { ordem: 1 }]);
  // Enquanto grava, nenhum Subir/Descer mexe (aria-disabled na página: o foco fica no botão tocado).
  expect(m.vista().linhas.every((l) => l.ocupada)).toBe(true);
  m.ecra.descer(ID_LISBOA);
  m.ecra.subir(ID_SETUBAL);
  expect(resumo(m).slice(1)).toEqual([`alterarRegiao ${ID_SETUBAL}`]);
  await responder(m, 'alterarRegiao', { id: ID_SETUBAL, nome: 'Setúbal', ordem: 1 });
  expect(ultimo(m, 'alterarRegiao').argumentos).toEqual([ID_PORTO, { ordem: 2 }]);
  expect(m.avisos).toEqual([]);
  await responder(m, 'alterarRegiao', { id: ID_PORTO, nome: 'Porto', ordem: 2 });
  expect(m.vista().linhas.some((l) => l.ocupada)).toBe(false);
  expect(linhaDe(m, 'Lisboa').podeDescer).toBe(true);
  expect(linhaDe(m, 'Porto').podeDescer).toBe(false); // Porto é agora a última
  expect(m.avisos).toEqual(['Ordem guardada']);
  // A seguinte já parte da ordem numerada: só duas mudam.
  m.ecra.subir(ID_SETUBAL);
  expect(ultimo(m, 'alterarRegiao').argumentos).toEqual([ID_SETUBAL, { ordem: 0 }]);
  await responder(m, 'alterarRegiao', {});
  expect(ultimo(m, 'alterarRegiao').argumentos).toEqual([ID_LISBOA, { ordem: 1 }]);
  await responder(m, 'alterarRegiao', {});
  expect(pedidos(m, 'alterarRegiao')).toHaveLength(4);
  expect(nomes(m)).toEqual(['Setúbal', 'Lisboa', 'Porto']);
});

test('Subir até ao topo: o foco passa para o Descer (o Subir fica desativado); Descer até ao fundo, para o Subir', async () => {
  const m = await carregada();
  m.ecra.subir(ID_PORTO);
  expect(nomes(m)).toEqual(['Porto', 'Lisboa', 'Setúbal']);
  expect(m.focos).toEqual([{ id: ID_PORTO, alvo: 'descer' }]);
  await responder(m, 'alterarRegiao', {});
  await responder(m, 'alterarRegiao', {});
  m.ecra.descer(ID_LISBOA);
  expect(nomes(m)).toEqual(['Porto', 'Setúbal', 'Lisboa']);
  expect(m.focos.at(-1)).toEqual({ id: ID_LISBOA, alvo: 'subir' });
  await responder(m, 'alterarRegiao', {});
  await responder(m, 'alterarRegiao', {});
  m.ecra.descer(ID_PORTO);
  expect(m.focos.at(-1)).toEqual({ id: ID_PORTO, alvo: 'descer' });
});

test('a primeira não sobe, a última não desce, e uma região que não está na lista não mexe', async () => {
  const m = await carregada();
  m.ecra.subir(ID_LISBOA);
  m.ecra.descer(ID_SETUBAL);
  m.ecra.subir(ID_OUTRA);
  expect(pedidos(m, 'alterarRegiao')).toEqual([]);
  expect(m.focos).toEqual([]);
  expect(nomes(m)).toEqual(['Lisboa', 'Porto', 'Setúbal']);
});

test('falha a gravar a ordem: o aviso, e a lista volta a pedir-se ao servidor (para mostrar a ordem que lá ficou)', async () => {
  const m = await carregada();
  m.ecra.descer(ID_LISBOA);
  // Porto passa a 1.ª e já tinha a ordem 0: mudam Lisboa (1) e Setúbal (2), por esta ordem.
  expect(nomes(m)).toEqual(['Porto', 'Lisboa', 'Setúbal']);
  expect(ultimo(m, 'alterarRegiao').argumentos).toEqual([ID_LISBOA, { ordem: 1 }]);
  await falhar(m, 'alterarRegiao', erroSemRede());
  expect(m.erros).toEqual([MENSAGEM_SEM_REDE]);
  expect(pedidos(m, 'alterarRegiao').filter((p) => p.argumentos[0] === ID_SETUBAL)).toEqual([]); // para no primeiro
  expect(pedidos(m, 'listarRegioes')).toHaveLength(2);
  expect(m.vista().linhas.every((l) => l.ocupada)).toBe(true); // até a lista chegar
  m.ecra.descer(ID_LISBOA);
  expect(pedidos(m, 'alterarRegiao')).toHaveLength(1);
  await responder(m, 'listarRegioes', copia(REGIOES));
  expect(nomes(m)).toEqual(['Lisboa', 'Porto', 'Setúbal']);
  expect(m.vista().linhas.some((l) => l.ocupada)).toBe(false); // pode tentar outra vez
  expect(m.avisos).toEqual([]);
  m.ecra.descer(ID_LISBOA);
  expect(pedidos(m, 'alterarRegiao')).toHaveLength(2);
});

test('a ordem recusada (422) mostra a mensagem do campo da ordem', async () => {
  const m = await carregada();
  m.ecra.subir(ID_PORTO);
  await falhar(m, 'alterarRegiao', erroValidacao({ ordem: 'A ordem tem de ser um número inteiro.' }));
  expect(m.erros).toEqual(['A ordem tem de ser um número inteiro.']);
});

test('falha a gravar a ordem e também a pedir a lista: "Tentar novamente" por cima da lista, e a rede que volta pede-a', async () => {
  const m = await carregada();
  m.ecra.descer(ID_LISBOA);
  await falhar(m, 'alterarRegiao', erroSemRede());
  await falhar(m, 'listarRegioes', erroSemRede());
  expect(m.vista().estado).toBe('pronto'); // a lista à vista fica
  expect(m.vista().falha).toEqual({ mensagem: MENSAGEM_SEM_REDE, aTentar: false });
  expect(linhaDe(m, 'Porto').ocupada).toBe(false);
  m.mudarRede(true);
  expect(pedidos(m, 'listarRegioes')).toHaveLength(3);
  await responder(m, 'listarRegioes', copia(REGIOES));
  expect(nomes(m)).toEqual(['Lisboa', 'Porto', 'Setúbal']);
  expect(m.vista().falha).toBe(null);
});

test('"Tentar novamente" com a lista à vista pede-a outra vez (um toque, um pedido)', async () => {
  const m = await carregada();
  m.ecra.descer(ID_LISBOA);
  await falhar(m, 'alterarRegiao', erroSemRede());
  await falhar(m, 'listarRegioes', erroSemRede());
  m.ecra.tentarDeNovo();
  m.ecra.tentarDeNovo();
  expect(pedidos(m, 'listarRegioes')).toHaveLength(3);
});

// --- Mudar o nome --------------------------------------------------------------------------------

test('Mudar o nome: o campo com o nome atual; Guardar envia {nome} e a região fica com o nome novo', async () => {
  const m = await carregada();
  m.ecra.abrirEdicao(ID_PORTO);
  expect(linhaDe(m, 'Porto').edicao).toEqual({ valor: 'Porto', erro: null, aGuardar: false, botao: { ativo: true, texto: 'Guardar' } });
  expect(Object.isFrozen(linhaDe(m, 'Porto').edicao)).toBe(true);
  expect(m.focos).toEqual([{ id: ID_PORTO, alvo: 'nome' }]);
  m.ecra.mudarNome('Grande Porto');
  m.ecra.guardarNome();
  expect(ultimo(m, 'alterarRegiao').argumentos).toEqual([ID_PORTO, { nome: 'Grande Porto' }]);
  expect(linhaDe(m, 'Porto').edicao).toEqual({
    valor: 'Grande Porto', erro: null, aGuardar: true, botao: { ativo: false, texto: 'A guardar…' },
  });
  await responder(m, 'alterarRegiao', { id: ID_PORTO, nome: 'Grande Porto', ordem: 0 });
  expect(nomes(m)).toEqual(['Grande Porto', 'Lisboa', 'Setúbal']); // com a mesma ordem, o nome decide (como no servidor)
  expect(linhaDe(m, 'Grande Porto').edicao).toBe(null);
  expect(linhaDe(m, 'Grande Porto').rotulos.mudar).toBe('Mudar o nome de Grande Porto');
  expect(m.focos.at(-1)).toEqual({ id: ID_PORTO, alvo: 'mudar' });
  expect(m.avisos).toEqual(['Nome guardado']);
});

test('Mudar o nome: só o nome muda (a ordem desta lista pode ser mais recente do que a da resposta)', async () => {
  const m = await carregada();
  m.ecra.abrirEdicao(ID_LISBOA);
  m.ecra.mudarNome('Zona');
  m.ecra.guardarNome();
  await responder(m, 'alterarRegiao', { id: ID_LISBOA, nome: 'Zona', ordem: -1 });
  expect(m.vista().linhas.map((l) => [l.nome, l.podeSubir])).toEqual([['Porto', false], ['Setúbal', true], ['Zona', true]]);
});

test('Mudar o nome: Cancelar volta atrás sem pedir nada; um nome repetido mostra o erro junto ao campo', async () => {
  const m = await carregada();
  m.ecra.abrirEdicao(ID_PORTO);
  m.ecra.cancelarEdicao();
  expect(linhaDe(m, 'Porto').edicao).toBe(null);
  expect(m.focos.at(-1)).toEqual({ id: ID_PORTO, alvo: 'mudar' });
  expect(pedidos(m, 'alterarRegiao')).toEqual([]);

  m.ecra.abrirEdicao(ID_PORTO);
  m.ecra.mudarNome('Lisboa');
  m.ecra.guardarNome();
  await falhar(m, 'alterarRegiao', erroRepetida());
  expect(linhaDe(m, 'Porto').edicao).toEqual({
    valor: 'Lisboa', erro: 'Já existe uma região com este nome.', aGuardar: false, botao: { ativo: true, texto: 'Guardar' },
  }); // continua a editar
  expect(m.focos.at(-1)).toEqual({ id: ID_PORTO, alvo: 'nome' });
  m.ecra.mudarNome('Porto Norte');
  expect(linhaDe(m, 'Porto').edicao.erro).toBe(null);
  m.ecra.guardarNome();
  await falhar(m, 'alterarRegiao', erroValidacao({ nome: 'Indique o nome.' }));
  expect(linhaDe(m, 'Porto').edicao.erro).toBe('Indique o nome.');
  m.ecra.guardarNome();
  await falhar(m, 'alterarRegiao', erroSemRede());
  expect(linhaDe(m, 'Porto').edicao.erro).toBe(MENSAGEM_SEM_REDE);
  expect(m.erros).toEqual([]);
  expect(m.avisos).toEqual([]);
});

test('enquanto o nome grava: um pedido só, e o campo, o Cancelar e as outras edições não mexem', async () => {
  const m = await carregada();
  m.ecra.abrirEdicao(ID_PORTO);
  m.ecra.mudarNome('Grande Porto');
  m.ecra.guardarNome();
  m.ecra.guardarNome();
  m.ecra.mudarNome('Outro');
  m.ecra.cancelarEdicao();
  m.ecra.abrirEdicao(ID_LISBOA);
  expect(pedidos(m, 'alterarRegiao')).toHaveLength(1);
  expect(linhaDe(m, 'Porto').edicao.valor).toBe('Grande Porto');
  expect(linhaDe(m, 'Lisboa').edicao).toBe(null);
  expect(m.focos).toEqual([{ id: ID_PORTO, alvo: 'nome' }]);
});

test('abrir outra edição fecha a primeira; abrir a mesma outra vez não faz nada', async () => {
  const m = await carregada();
  m.ecra.abrirEdicao(ID_PORTO);
  m.ecra.mudarNome('Grande Porto');
  m.ecra.abrirEdicao(ID_PORTO);
  expect(linhaDe(m, 'Porto').edicao.valor).toBe('Grande Porto');
  m.ecra.abrirEdicao(ID_LISBOA);
  expect(linhaDe(m, 'Porto').edicao).toBe(null);
  expect(linhaDe(m, 'Lisboa').edicao.valor).toBe('Lisboa');
  m.ecra.abrirEdicao(ID_OUTRA);
  expect(linhaDe(m, 'Lisboa').edicao).not.toBe(null);
  expect(m.focos).toEqual([{ id: ID_PORTO, alvo: 'nome' }, { id: ID_LISBOA, alvo: 'nome' }]);
});

test('Mudar o nome de uma região que outra pessoa apagou (404): o aviso, a edição fecha e a lista vem outra vez', async () => {
  const m = await carregada();
  m.ecra.abrirEdicao(ID_PORTO);
  m.ecra.guardarNome();
  await falhar(m, 'alterarRegiao', erro404());
  expect(m.erros).toEqual(['Região não encontrada.']);
  expect(linhaDe(m, 'Porto').edicao).toBe(null);
  expect(pedidos(m, 'listarRegioes')).toHaveLength(2);
  await responder(m, 'listarRegioes', copia([REGIOES[0], REGIOES[2]]));
  expect(nomes(m)).toEqual(['Lisboa', 'Setúbal']);
});

test('Mudar o nome com uma resposta sem nome: a edição fecha e a lista vem outra vez do servidor', async () => {
  const m = await carregada();
  m.ecra.abrirEdicao(ID_PORTO);
  m.ecra.mudarNome('Grande Porto');
  m.ecra.guardarNome();
  await responder(m, 'alterarRegiao', { apagada: true });
  expect(linhaDe(m, 'Porto').edicao).toBe(null);
  expect(m.avisos).toEqual(['Nome guardado']);
  expect(pedidos(m, 'listarRegioes')).toHaveLength(2);
});

test('a lista que volta sem a região em edição fecha a edição', async () => {
  const m = await carregada();
  m.ecra.descer(ID_LISBOA);
  await falhar(m, 'alterarRegiao', erroSemRede());
  m.ecra.abrirEdicao(ID_SETUBAL);
  await responder(m, 'listarRegioes', copia(REGIOES.slice(0, 2)));
  expect(m.vista().linhas.every((l) => l.edicao === null)).toBe(true);
  m.ecra.guardarNome();
  expect(pedidos(m, 'alterarRegiao')).toHaveLength(1);
});

// --- Apagar --------------------------------------------------------------------------------------

test('Apagar pede confirmação; Cancelar (ou Escape) não apaga, e só a primeira resposta conta', async () => {
  const m = await carregada();
  m.ecra.pedirApagar(ID_PORTO);
  expect(m.vista().pergunta).toEqual(perguntaApagarRegiao(REGIOES[1]));
  expect(m.vista().pergunta.pergunta).toBe('Apagar a região Porto?');
  m.ecra.pedirApagar(ID_LISBOA); // já há uma pergunta aberta
  expect(m.vista().pergunta.pergunta).toBe('Apagar a região Porto?');
  m.ecra.responderApagar(null);
  m.ecra.responderApagar(RESPOSTA_APAGAR_REGIAO);
  await assentar();
  expect(m.vista().pergunta).toBe(null);
  expect(pedidos(m, 'apagarRegiao')).toEqual([]);
  expect(nomes(m)).toEqual(['Lisboa', 'Porto', 'Setúbal']);
});

test('Apagar só com a resposta "apagar": outra resposta qualquer (ou nenhuma) fecha a pergunta sem apagar', async () => {
  const m = await carregada();
  for (const resposta of [undefined, '', 'cancelar', 'Sim, apagar', true]) {
    m.ecra.pedirApagar(ID_PORTO);
    expect(m.vista().pergunta).not.toBe(null);
    m.ecra.responderApagar(resposta);
    expect(m.vista().pergunta).toBe(null);
  }
  await assentar();
  expect(pedidos(m, 'apagarRegiao')).toEqual([]);
  expect(nomes(m)).toEqual(['Lisboa', 'Porto', 'Setúbal']);
});

test('Apagar confirmado: o pedido, a região sai da lista, o aviso e o foco no título', async () => {
  const m = await carregada();
  m.ecra.pedirApagar(ID_SETUBAL);
  m.ecra.responderApagar(RESPOSTA_APAGAR_REGIAO);
  expect(resumo(m).slice(1)).toEqual([`apagarRegiao ${ID_SETUBAL}`]);
  expect(linhaDe(m, 'Setúbal').apagar).toEqual({ ativo: false, texto: 'A apagar…' });
  m.ecra.pedirApagar(ID_SETUBAL); // já a apagar
  expect(m.vista().pergunta).toBe(null);
  await responder(m, 'apagarRegiao', { apagada: true });
  expect(nomes(m)).toEqual(['Lisboa', 'Porto']);
  expect(linhaDe(m, 'Porto').podeDescer).toBe(false);
  expect(m.avisos).toEqual(['Região apagada']);
  expect(m.focos).toEqual(['titulo']);
});

test('Apagar uma região com lojas (409): a mensagem do servidor nessa região, que fica', async () => {
  const m = await carregada();
  m.ecra.pedirApagar(ID_LISBOA);
  m.ecra.responderApagar(RESPOSTA_APAGAR_REGIAO);
  await falhar(m, 'apagarRegiao', erroComLojas());
  expect(linhaDe(m, 'Lisboa').erro).toBe('Esta região tem lojas — mude-lhe o nome em vez de a apagar.');
  expect(linhaDe(m, 'Lisboa').apagar).toEqual({ ativo: true, texto: 'Apagar' });
  expect(nomes(m)).toEqual(['Lisboa', 'Porto', 'Setúbal']);
  expect(m.erros).toEqual([]);
  expect(m.focos).toEqual([]);
  // Fica até se voltar a perguntar, ou se mudar o nome a essa região.
  m.ecra.subir(ID_PORTO);
  expect(linhaDe(m, 'Lisboa').erro).not.toBe(null);
  m.ecra.pedirApagar(ID_LISBOA);
  expect(linhaDe(m, 'Lisboa').erro).toBe(null);
  m.ecra.responderApagar(RESPOSTA_APAGAR_REGIAO);
  await falhar(m, 'apagarRegiao', erroComLojas());
  m.ecra.abrirEdicao(ID_LISBOA);
  expect(linhaDe(m, 'Lisboa').erro).toBe(null);
});

test('Apagar uma região que outra pessoa já apagou (404): o aviso e a lista outra vez', async () => {
  const m = await carregada();
  m.ecra.pedirApagar(ID_PORTO);
  m.ecra.responderApagar(RESPOSTA_APAGAR_REGIAO);
  await falhar(m, 'apagarRegiao', erro404());
  expect(m.erros).toEqual(['Região não encontrada.']);
  expect(linhaDe(m, 'Porto').erro).toBe(null);
  expect(pedidos(m, 'listarRegioes')).toHaveLength(2);
  await responder(m, 'listarRegioes', copia([REGIOES[0], REGIOES[2]]));
  expect(nomes(m)).toEqual(['Lisboa', 'Setúbal']);
});

test('Apagar uma região de que nada se sabe, ou antes de a lista chegar, não pergunta nada', async () => {
  const m = montar();
  m.ecra.pedirApagar(ID_PORTO);
  expect(m.vista().pergunta).toBe(null);
  await responder(m, 'listarRegioes', copia(REGIOES));
  m.ecra.pedirApagar(ID_OUTRA);
  expect(m.vista().pergunta).toBe(null);
});

test('destruir fecha a pergunta aberta sem apagar; as respostas e a rede que chegam depois são ignoradas', async () => {
  const m = await carregada();
  m.ecra.pedirApagar(ID_LISBOA);
  m.ecra.destruir();
  expect(m.vista().pergunta).toBe(null);
  m.ecra.responderApagar(RESPOSTA_APAGAR_REGIAO);
  await assentar();
  expect(pedidos(m, 'apagarRegiao')).toEqual([]);

  const outra = montar();
  const vistas = outra.vistas.length;
  outra.ecra.destruir();
  await falhar(outra, 'listarRegioes', erroSemRede());
  outra.mudarRede(true);
  expect(pedidos(outra, 'listarRegioes')).toHaveLength(1);
  expect(outra.vistas).toHaveLength(vistas);
  outra.ecra.iniciar();
  expect(pedidos(outra, 'listarRegioes')).toHaveLength(1);
});

test('iniciar duas vezes ouve a rede uma só vez; ao sair deixa de a ouvir', () => {
  let ouvintes = 0;
  const rede = {
    online: () => true,
    aoMudar: () => {
      ouvintes += 1;
      return () => {
        ouvintes -= 1;
      };
    },
  };
  const ecra = criarRegioes({ api: apiFalsa(), rede });
  ecra.iniciar();
  ecra.iniciar();
  expect(ouvintes).toBe(1);
  ecra.destruir();
  expect(ouvintes).toBe(0);
});

test('as respostas da escrita que chegam depois de sair não mexem em nada', async () => {
  const m = await carregada();
  m.ecra.mudarNova('Faro');
  m.ecra.adicionar();
  m.ecra.subir(ID_PORTO);
  m.ecra.destruir();
  const vistas = m.vistas.length;
  await responder(m, 'criarRegiao', { id: ID_FARO, nome: 'Faro', ordem: 1 });
  await responder(m, 'alterarRegiao', {});
  expect(pedidos(m, 'alterarRegiao')).toHaveLength(1);
  expect(m.vistas).toHaveLength(vistas);
  expect(m.avisos).toEqual([]);
  expect(m.focos).toEqual([{ id: ID_PORTO, alvo: 'descer' }]);
});
