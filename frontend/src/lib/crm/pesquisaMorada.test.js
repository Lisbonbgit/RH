/**
 * O CAMPO "PESQUISAR MORADA" — o que o campo mostra e faz, sem DOM.
 *
 * Porta de tests/js/pesquisa-morada.test.js do CRM autónomo (etiqueta
 * `referencia-standalone`), sobre o `criarCampoPesquisaMorada` de
 * `pesquisaMorada.js`, que guarda as regras do componente do autónomo
 * (`componentes/pesquisa-morada.js`) fora do React (plano T2.26; correção
 * "T2.26 / T2.27 / T2.29 / T2.30 (componentes "Sem Jest")"). O
 * `components/crm/PesquisaMorada.js` só desenha a `vista` e passa-lhe o que a
 * pessoa escreve e as teclas.
 *
 * O que no autónomo se via no DOM vê-se aqui na `vista`: o texto do campo, o
 * estado e a sua mensagem, as sugestões, a lista aberta e a sugestão ativa. O
 * `preventDefault` das teclas é o `true` de `tecla()`. Ficam para o componente
 * (verificação no browser) os atributos ARIA, os ids, o "Powered by Geoapify"
 * sempre à vista por baixo e o `mousedown` que não tira o foco do campo.
 *
 * O `node:assert` passou a `expect` e o `mock.timers` a `jest.useFakeTimers()`
 * + `jest.advanceTimersByTime()` (plano §10). A função de pesquisa é falsa e
 * nasce em cada teste (o CRA corre com `resetMocks`): cada pedido fica
 * pendente até o teste o resolver ou rejeitar.
 *
 * A mais: o limite de 200 caracteres é o do servidor (lido do
 * `backend/crm/morada.py`), a `vista` é a mesma que chega ao `aoMudarVista` e
 * não se muda por fora, um texto `null` não pesquisa "null", e uma escolha
 * fora da lista não faz nada.
 */
import fs from 'fs';
import path from 'path';
import {
  criarCampoPesquisaMorada,
  sugestaoValida,
  TEXTO_A_PESQUISAR,
  TEXTO_SEM_RESULTADOS,
  TEXTO_PESQUISAR_MORADA,
  TEXTO_SUGESTOES,
  TEXTO_MAXIMO,
} from './pesquisaMorada';
import { MENSAGEM_MORADA_INDISPONIVEL } from './morada';
import { ErroCrm } from './api';

// frontend/src/lib/crm → raiz do repositório.
const MORADA_PY = path.join(__dirname, '..', '..', '..', '..', 'backend', 'crm', 'morada.py');

const AUGUSTA = { rotulo: 'Rua Augusta, 1100-053 Lisboa, Portugal', morada: 'Rua Augusta', codigo_postal: '1100-053', localidade: 'Lisboa', lat: 38.7104, lng: -9.1377 };
const AUGUSTA_24 = { rotulo: 'Rua Augusta 24, 1100-048 Lisboa, Portugal', morada: 'Rua Augusta 24', codigo_postal: '1100-048', localidade: 'Lisboa', lat: 38.70921, lng: -9.13712 };
const CASCAIS = { rotulo: 'Rua Augusta, 2750 Cascais, Portugal', morada: 'Rua Augusta', codigo_postal: null, localidade: 'Cascais', lat: 38.6979, lng: -9.4215 };

// Deixa correr as promessas pendentes (microtarefas; os temporizadores estão falsificados).
async function esvaziar() {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
}

function preparar({ perto = { lat: 38.7223, lng: -9.1393 } } = {}) {
  const pedidos = [];
  const escolhidas = [];
  const vistas = [];
  const campo = criarCampoPesquisaMorada({
    pesquisar: (texto, ponto) => new Promise((resolver, rejeitar) => {
      pedidos.push({ texto, ponto, resolver, rejeitar });
    }),
    obterPerto: () => perto,
    aoEscolher: (sugestao) => escolhidas.push(sugestao),
    aoMudarVista: (vista) => vistas.push(vista),
  });
  return { campo, pedidos, escolhidas, vistas };
}

const rotulos = (campo) => campo.vista.sugestoes.map((s) => s.rotulo);

// Escreve, espera os 300 ms e responde ao pedido com as sugestões.
async function pesquisarCom(m, texto, sugestoes) {
  m.campo.escrever(texto);
  jest.advanceTimersByTime(300);
  m.pedidos.at(-1).resolver(sugestoes);
  await esvaziar();
}

beforeEach(() => {
  jest.useFakeTimers();
});

afterEach(() => {
  jest.useRealTimers();
});

test('o campo começa vazio, sem lista, sem mensagem e sem sugestão ativa; os textos do campo', () => {
  const { campo } = preparar();
  expect(campo.vista).toEqual({ texto: '', estado: 'vazio', mensagem: '', sugestoes: [], aberta: false, ativa: -1 });
  expect(TEXTO_PESQUISAR_MORADA).toBe('Pesquisar morada');
  expect(TEXTO_SUGESTOES).toBe('Sugestões de morada');
});

test('até 200 caracteres: o limite do servidor (um texto maior daria 422)', () => {
  expect(TEXTO_MAXIMO).toBe(200);
  // Falha, e não salta, se o ficheiro do servidor faltar.
  const servidor = fs.readFileSync(MORADA_PY, 'utf8').match(/^TEXTO_MAXIMO = (\d+)$/m);
  expect(servidor).not.toBeNull();
  expect(Number(servidor[1])).toBe(TEXTO_MAXIMO);
});

test('pesquisa 300 ms depois da última tecla, com o ponto de onde se pesquisa (bias)', () => {
  const { campo, pedidos } = preparar({ perto: { lat: 38.72230000123, lng: -9.1393 } });
  campo.escrever('Rua');
  jest.advanceTimersByTime(200);
  campo.escrever('Rua Aug');
  jest.advanceTimersByTime(299);
  expect(pedidos.length).toBe(0);
  jest.advanceTimersByTime(1);
  expect(pedidos.length).toBe(1);
  expect(pedidos[0].texto).toBe('Rua Aug');
  expect(pedidos[0].ponto).toEqual({ lat: 38.7223, lng: -9.1393 });
  expect(campo.vista.texto).toBe('Rua Aug');
});

test('sem ponto válido, pesquisa sem bias', () => {
  const { campo, pedidos } = preparar({ perto: null });
  campo.escrever('Rua Augusta');
  jest.advanceTimersByTime(300);
  expect(pedidos[0].ponto).toBeNull();
});

test('sem obterPerto, pesquisa sem bias', () => {
  const pedidos = [];
  const campo = criarCampoPesquisaMorada({ pesquisar: (texto, ponto) => { pedidos.push({ texto, ponto }); return new Promise(() => {}); } });
  campo.escrever('Rua Augusta');
  jest.advanceTimersByTime(300);
  expect(pedidos).toEqual([{ texto: 'Rua Augusta', ponto: null }]);
});

test('não pesquisa com menos de 3 caracteres', () => {
  const { campo, pedidos } = preparar();
  campo.escrever('Ru');
  jest.advanceTimersByTime(1000);
  expect(pedidos.length).toBe(0);
  expect(campo.vista.texto).toBe('Ru');
});

test('"A pesquisar…" enquanto espera e depois a lista de sugestões', async () => {
  const m = preparar();
  m.campo.escrever('Rua Augusta');
  jest.advanceTimersByTime(300);
  expect(m.campo.vista.estado).toBe('a_pesquisar');
  expect(m.campo.vista.mensagem).toBe(TEXTO_A_PESQUISAR);
  expect(TEXTO_A_PESQUISAR).toBe('A pesquisar…');
  m.pedidos[0].resolver([AUGUSTA, AUGUSTA_24, CASCAIS]);
  await esvaziar();
  expect(m.campo.vista.estado).toBe('resultados');
  expect(m.campo.vista.mensagem).toBe('');
  expect(m.campo.vista.aberta).toBe(true);
  expect(m.campo.vista.ativa).toBe(-1);
  expect(rotulos(m.campo)).toEqual([AUGUSTA.rotulo, AUGUSTA_24.rotulo, CASCAIS.rotulo]);
});

test('a lista anterior fica enquanto a nova pesquisa decorre (sem saltos no ecrã)', async () => {
  const m = preparar();
  await pesquisarCom(m, 'Rua Augusta', [AUGUSTA, AUGUSTA_24]);
  m.campo.escrever('Rua Augusta 2');
  jest.advanceTimersByTime(300);
  expect(m.campo.vista.estado).toBe('a_pesquisar');
  expect(rotulos(m.campo)).toEqual([AUGUSTA.rotulo, AUGUSTA_24.rotulo]);
  expect(m.campo.vista.aberta).toBe(true);
});

test('as sugestões ficam com o rótulo tal e qual (o React mostra-o como texto)', async () => {
  const m = preparar();
  await pesquisarCom(m, 'Rua <b>x</b>', [{ ...AUGUSTA, rotulo: 'Rua <b>x</b>, Lisboa' }]);
  expect(m.pedidos[0].texto).toBe('Rua <b>x</b>');
  expect(rotulos(m.campo)).toEqual(['Rua <b>x</b>, Lisboa']);
});

test('sugestões sem rótulo ou sem coordenadas ficam de fora', async () => {
  const m = preparar();
  await pesquisarCom(m, 'Rua Augusta', [{ ...AUGUSTA, rotulo: '' }, { ...AUGUSTA, lat: '38.7' }, null, AUGUSTA_24]);
  expect(rotulos(m.campo)).toEqual([AUGUSTA_24.rotulo]);
});

test('sugestaoValida: rótulo com texto e coordenadas finitas', () => {
  expect(sugestaoValida(AUGUSTA)).toBe(true);
  for (const sugestao of [null, undefined, {}, { ...AUGUSTA, rotulo: '' }, { ...AUGUSTA, rotulo: 3 },
    { ...AUGUSTA, lat: '38.7' }, { ...AUGUSTA, lng: Number.NaN }, { ...AUGUSTA, lat: Infinity }]) {
    expect(sugestaoValida(sugestao)).toBe(false);
  }
});

test('sem resultados: diz que não encontrou e fecha a lista', async () => {
  const m = preparar();
  await pesquisarCom(m, 'Rua Augusta', [AUGUSTA]);
  await pesquisarCom(m, 'Rua Inexistente', []);
  expect(m.campo.vista.mensagem).toBe(TEXTO_SEM_RESULTADOS);
  expect(TEXTO_SEM_RESULTADOS).toBe('Nenhuma morada encontrada — escreva de outra forma ou toque no mapa.');
  expect(m.campo.vista.aberta).toBe(false);
  expect(m.campo.vista.sugestoes).toEqual([]);
});

test('falha da pesquisa (503 ou sem rede): a mensagem exata do desenho, sem lista', async () => {
  for (const erro of [
    new ErroCrm({ codigo: 'morada_indisponivel', mensagem: 'do servidor', estado: 503 }),
    new ErroCrm({ codigo: 'sem_rede', mensagem: 'Sem rede', estado: 0 }),
  ]) {
    const m = preparar();
    await pesquisarCom(m, 'Rua Augusta', [AUGUSTA]);
    m.campo.escrever('Rua Augusta 2');
    jest.advanceTimersByTime(300);
    m.pedidos.at(-1).rejeitar(erro);
    await esvaziar();
    expect(m.campo.vista.mensagem).toBe(MENSAGEM_MORADA_INDISPONIVEL);
    expect(m.campo.vista.mensagem).toBe("Pesquisa de morada indisponível — coloque o pino no mapa ou use 'Estou nesta loja'");
    expect(m.campo.vista.estado).toBe('erro');
    expect(m.campo.vista.aberta).toBe(false);
    expect(m.campo.vista.sugestoes).toEqual([]);
  }
});

test('depois de uma falha, escrever outra vez volta a pesquisar e tira a mensagem', async () => {
  const m = preparar();
  m.campo.escrever('falha');
  jest.advanceTimersByTime(300);
  m.pedidos[0].rejeitar(new ErroCrm({ codigo: 'morada_indisponivel', mensagem: 'x', estado: 503 }));
  await esvaziar();
  await pesquisarCom(m, 'Rua Augusta', [AUGUSTA]);
  expect(m.campo.vista.estado).toBe('resultados');
  expect(m.campo.vista.mensagem).toBe('');
  expect(m.campo.vista.sugestoes.length).toBe(1);
});

test('apagar o texto (menos de 3 caracteres) fecha a lista e tira a mensagem', async () => {
  const m = preparar();
  await pesquisarCom(m, 'Rua Augusta', [AUGUSTA]);
  m.campo.escrever('Ru');
  expect(m.campo.vista.aberta).toBe(false);
  expect(m.campo.vista.sugestoes).toEqual([]);
  expect(m.campo.vista.mensagem).toBe('');
  expect(m.campo.vista.estado).toBe('vazio');
});

test('uma resposta antiga não substitui a lista mais recente', async () => {
  const m = preparar();
  m.campo.escrever('Rua Aug');
  jest.advanceTimersByTime(300);
  m.campo.escrever('Rua Augusta 24');
  jest.advanceTimersByTime(300);
  m.pedidos[1].resolver([AUGUSTA_24]);
  await esvaziar();
  m.pedidos[0].resolver([AUGUSTA, CASCAIS]);
  await esvaziar();
  expect(rotulos(m.campo)).toEqual([AUGUSTA_24.rotulo]);
});

test('tocar numa sugestão: escolhe-a, põe o rótulo no campo e fecha a lista', async () => {
  const m = preparar();
  await pesquisarCom(m, 'Rua Augusta', [AUGUSTA, AUGUSTA_24]);
  m.campo.escolher(1);
  expect(m.escolhidas).toEqual([AUGUSTA_24]);
  expect(m.campo.vista.texto).toBe(AUGUSTA_24.rotulo);
  expect(m.campo.vista.aberta).toBe(false);
  expect(m.campo.vista.sugestoes).toEqual([]);
  expect(m.campo.vista.mensagem).toBe('');
  expect(m.campo.vista.estado).toBe('escolhida');
});

test('escolher fora da lista não faz nada', async () => {
  const m = preparar();
  await pesquisarCom(m, 'Rua Augusta', [AUGUSTA]);
  for (const indice of [-1, 1, 5, Number.NaN, '0x', undefined]) m.campo.escolher(indice);
  expect(m.escolhidas).toEqual([]);
  expect(m.campo.vista.aberta).toBe(true);
});

test('escolher cancela a pesquisa que estava agendada', async () => {
  const m = preparar();
  await pesquisarCom(m, 'Rua Augusta', [AUGUSTA]);
  m.campo.escrever('Rua Augusta 2');
  m.campo.escolher(0);
  jest.advanceTimersByTime(1000);
  expect(m.pedidos.length).toBe(1);
});

test('teclado: setas escolhem a sugestão ativa, Enter escolhe, sem submeter', async () => {
  const m = preparar();
  await pesquisarCom(m, 'Rua Augusta', [AUGUSTA, AUGUSTA_24, CASCAIS]);
  expect(m.campo.tecla('ArrowDown')).toBe(true);
  expect(m.campo.vista.ativa).toBe(0);
  m.campo.tecla('ArrowDown');
  expect(m.campo.vista.ativa).toBe(1);
  m.campo.tecla('ArrowDown');
  m.campo.tecla('ArrowDown');
  expect(m.campo.vista.ativa).toBe(0); // volta ao princípio
  expect(m.campo.tecla('ArrowUp')).toBe(true);
  expect(m.campo.vista.ativa).toBe(2); // e ao fim
  expect(m.campo.tecla('Enter')).toBe(true);
  expect(m.escolhidas).toEqual([CASCAIS]);
  expect(m.campo.vista.ativa).toBe(-1);
});

test('uma lista nova começa sem sugestão ativa', async () => {
  const m = preparar();
  await pesquisarCom(m, 'Rua Augusta', [AUGUSTA, AUGUSTA_24, CASCAIS]);
  m.campo.tecla('ArrowUp');
  await pesquisarCom(m, 'Rua Augusta 24', [AUGUSTA_24]);
  expect(m.campo.vista.ativa).toBe(-1);
  m.campo.tecla('Enter');
  expect(m.escolhidas).toEqual([]);
});

test('Enter sem sugestão ativa não escolhe nem submete o formulário à volta', async () => {
  const m = preparar();
  expect(m.campo.tecla('Enter')).toBe(true);
  await pesquisarCom(m, 'Rua Augusta', [AUGUSTA]);
  expect(m.campo.tecla('Enter')).toBe(true);
  expect(m.escolhidas).toEqual([]);
  expect(m.campo.tecla('a')).toBe(false);
});

test('Escape fecha a lista; a seta para baixo volta a abri-la', async () => {
  const m = preparar();
  await pesquisarCom(m, 'Rua Augusta', [AUGUSTA, AUGUSTA_24]);
  m.campo.tecla('ArrowDown');
  expect(m.campo.tecla('Escape')).toBe(true);
  expect(m.campo.vista.aberta).toBe(false);
  expect(m.campo.vista.ativa).toBe(-1);
  expect(m.campo.tecla('Escape')).toBe(false); // com a lista fechada, o Escape é dos outros
  m.campo.tecla('ArrowDown');
  expect(m.campo.vista.aberta).toBe(true);
  expect(m.campo.vista.ativa).toBe(0);
});

test('com a lista fechada, Enter não escolhe a sugestão que estava ativa', async () => {
  const m = preparar();
  await pesquisarCom(m, 'Rua Augusta', [AUGUSTA, AUGUSTA_24]);
  m.campo.tecla('ArrowDown');
  m.campo.fechar();
  expect(m.campo.tecla('Enter')).toBe(true);
  expect(m.escolhidas).toEqual([]);
});

test('as setas sem sugestões não fazem nada', () => {
  const m = preparar();
  expect(m.campo.tecla('ArrowDown')).toBe(false);
  expect(m.campo.tecla('ArrowUp')).toBe(false);
  expect(m.campo.vista.aberta).toBe(false);
  expect(m.campo.vista.ativa).toBe(-1);
});

test('fechar() fecha a lista (ex.: tocaram no mapa)', async () => {
  const m = preparar();
  await pesquisarCom(m, 'Rua Augusta', [AUGUSTA]);
  m.campo.tecla('ArrowDown');
  m.campo.fechar();
  expect(m.campo.vista.aberta).toBe(false);
  expect(m.campo.vista.ativa).toBe(-1);
  expect(m.campo.vista.sugestoes.length).toBe(1); // voltam com a seta para baixo
});

test('cancelar() descarta a pesquisa a decorrer e fecha a lista', async () => {
  const m = preparar();
  await pesquisarCom(m, 'Rua Augusta', [AUGUSTA]);
  m.campo.escrever('Rua Augusta 24');
  jest.advanceTimersByTime(300);
  m.campo.cancelar();
  m.pedidos.at(-1).resolver([AUGUSTA_24]);
  await esvaziar();
  expect(m.campo.vista.aberta).toBe(false);
  expect(m.campo.vista.sugestoes).toEqual([]);
  expect(m.campo.vista.mensagem).toBe('');
  expect(m.campo.vista.estado).toBe('vazio');
});

test('cancelar() descarta a pesquisa agendada', () => {
  const m = preparar();
  m.campo.escrever('Rua Augusta');
  m.campo.cancelar();
  jest.advanceTimersByTime(1000);
  expect(m.pedidos).toEqual([]);
});

// --- A mais ----------------------------------------------------------------------------------------

test('a vista que chega ao aoMudarVista é a do campo, e não se muda por fora', async () => {
  const m = preparar();
  await pesquisarCom(m, 'Rua Augusta', [AUGUSTA]);
  expect(m.vistas.length).toBeGreaterThan(0);
  expect(m.vistas.at(-1)).toBe(m.campo.vista);
  expect(Object.isFrozen(m.campo.vista)).toBe(true);
  expect(Object.isFrozen(m.campo.vista.sugestoes)).toBe(true);
  // Cada mudança traz uma vista nova (o React só desenha outra vez com um objeto novo).
  const antes = m.campo.vista;
  m.campo.tecla('ArrowDown');
  expect(m.campo.vista).not.toBe(antes);
  expect(antes.ativa).toBe(-1);
});

test('um texto null ou undefined fica vazio e não pesquisa "null"', () => {
  const m = preparar();
  for (const texto of [null, undefined]) m.campo.escrever(texto);
  jest.advanceTimersByTime(1000);
  expect(m.pedidos).toEqual([]);
  expect(m.campo.vista.texto).toBe('');
});
