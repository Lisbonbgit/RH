/**
 * A FILA DAS GRAVAÇÕES DA ROTA — um pedido de cada vez, alterações juntas e a versão em vigor (F3 / T3.30).
 *
 * Cada ação do planeador grava logo (plano F3 §1 "Gravação") e leva a `versao` em vigor: o servidor dá 409
 * `conflito` se outra pessoa gravou entretanto. Por isso as gravações saem uma de cada vez, pela ordem, e
 * cada uma com a versão da última resposta (nunca a do momento em que a ação foi pedida).
 *   - `juntarAlteracoes(a, b)`: dois corpos do `PATCH /rotas/{data}` num só, como se fossem um depois do
 *     outro — as definições do dia, a `ordem` e o `estado`, a última vence; as `paragens` juntam-se por id
 *     e campo; `retirar` é a união e o retirar ganha (sai da `ordem` e das `paragens`, correção
 *     "T3.4 / T3.20"); a `versao` nunca passa (é a fila que a põe).
 *   - `criarFilaRota({enviar, versao})`: um só pedido em curso; os `alterar` pendentes seguidos juntam-se
 *     num; `adicionar` e `otimizar` nunca se juntam; os `recalcular` pendentes ficam um, no fim; um 409
 *     `conflito`/`rota_em_curso`/`rota_fechada` recusa o pedido em curso e todos os pendentes e a fila
 *     fica parada até `retomar(versao)`; outro erro recusa só esse pedido.
 *   - `enviarPelaApi(api, data)`: o `enviar` do planeador sobre o `api.js` da T3.29.
 *
 * Os `jest.fn` nascem DENTRO de cada teste (o Jest do CRA usa `resetMocks`); as respostas do servidor são
 * promessas controladas pelo teste.
 */
import fs from 'fs';
import path from 'path';

import { criarClienteCrm, ErroCrm, TIMEOUT_CALCULO_MS } from './api';
import {
  CODIGOS_QUE_PARAM,
  TIPOS_DE_PEDIDO,
  criarFilaRota,
  enviarPelaApi,
  juntarAlteracoes,
} from './filaRota';

const FILA_ROTA_JS = path.join(__dirname, 'filaRota.js');

const A = '0b6f5a52-1c1e-4d43-9b8e-3f2f7f6c0a01';
const B = '1c7a6b63-2d2f-4e54-8c9f-4a3a8a7d1b02';
const C = '2d8b7c74-3e3a-4f65-9daa-5b4b9b8e2c03';
const D = '3e9c8d85-4f4b-4a76-8ebb-6c5cac9f3d04';
const LOJA = '4fad9e96-5a5c-4b87-9fcc-7d6dbdaa4e05';

const PONTO = Object.freeze({ lat: 38.72, lng: -9.14 });
const OUTRO_PONTO = Object.freeze({ lat: 38.6, lng: -9.2 });

function congelarAFundo(valor) {
  if (valor && typeof valor === 'object' && !Object.isFrozen(valor)) {
    Object.values(valor).forEach(congelarAFundo);
    Object.freeze(valor);
  }
  return valor;
}

function estaCongeladoAFundo(valor) {
  if (!valor || typeof valor !== 'object') return true;
  return Object.isFrozen(valor) && Object.values(valor).every(estaCongeladoAFundo);
}

// Uma promessa que o teste resolve ou rejeita quando quer.
function adiado() {
  let resolver;
  let rejeitar;
  const promessa = new Promise((ok, falha) => {
    resolver = ok;
    rejeitar = falha;
  });
  return { promessa, resolver, rejeitar };
}

// Deixa correr as continuações pendentes (`.then`) das promessas já resolvidas.
const assentar = () => new Promise((ok) => setTimeout(ok, 0));

// Um `enviar` cujas respostas o teste controla: `chamadas[i]` tem o pedido e o `resolver`/`rejeitar`.
function servidorControlado() {
  const chamadas = [];
  const enviar = jest.fn((pedido) => {
    const resposta = adiado();
    chamadas.push({ pedido, ...resposta });
    return resposta.promessa;
  });
  return { enviar, chamadas };
}

// O estado de uma promessa, sem esperar por ela: 'pendente', 'resolvida' ou 'rejeitada'.
function seguir(promessa) {
  const estado = { como: 'pendente', valor: undefined };
  promessa.then(
    (valor) => {
      estado.como = 'resolvida';
      estado.valor = valor;
    },
    (erro) => {
      estado.como = 'rejeitada';
      estado.valor = erro;
    },
  );
  return estado;
}

const rota = (versao, extra = {}) => ({ id: 'r1', data: '2026-10-12', versao, ...extra });
const erro409 = (codigo) => new ErroCrm({ codigo, mensagem: `mensagem de ${codigo}`, estado: 409 });

// --- Constantes ----------------------------------------------------------------------------------

describe('constantes', () => {
  test('os quatro pedidos da fila, congelados', () => {
    expect(TIPOS_DE_PEDIDO).toEqual(['alterar', 'adicionar', 'recalcular', 'otimizar']);
    expect(Object.isFrozen(TIPOS_DE_PEDIDO)).toBe(true);
  });

  test('os códigos que param a fila são os 409 da rota inteira (não os de uma paragem), congelados', () => {
    expect(CODIGOS_QUE_PARAM).toEqual(['conflito', 'rota_em_curso', 'rota_fechada']);
    expect(Object.isFrozen(CODIGOS_QUE_PARAM)).toBe(true);
  });
});

// --- juntarAlteracoes ----------------------------------------------------------------------------

describe('juntarAlteracoes(a, b): as definições do dia e o estado, a última vence', () => {
  test.each([
    ['hora_saida', '08:00', '09:30'],
    ['hora_regresso_limite', '19:00', '18:00'],
    ['inicio', PONTO, null],
    ['inicio', null, OUTRO_PONTO],
    ['inicio', PONTO, OUTRO_PONTO],
    ['fim', PONTO, null],
    ['fim', null, PONTO],
    ['evitar_portagens', true, false],
    ['evitar_portagens', false, true],
    ['estado', 'planeada', 'planeada'],
  ])('%s: %p e depois %p → o segundo', (chave, primeiro, segundo) => {
    expect(juntarAlteracoes({ [chave]: primeiro }, { [chave]: segundo })).toStrictEqual({ [chave]: segundo });
  });

  test('o que só vem num dos lados fica (o null da fábrica também)', () => {
    expect(
      juntarAlteracoes(
        { hora_saida: '09:00', inicio: null, estado: 'planeada' },
        { fim: PONTO, evitar_portagens: false, hora_regresso_limite: '18:30' },
      ),
    ).toStrictEqual({
      hora_saida: '09:00',
      inicio: null,
      estado: 'planeada',
      fim: { lat: 38.72, lng: -9.14 },
      evitar_portagens: false,
      hora_regresso_limite: '18:30',
    });
    expect(juntarAlteracoes({ fim: null }, {})).toStrictEqual({ fim: null });
    expect(juntarAlteracoes({}, { inicio: null })).toStrictEqual({ inicio: null });
  });

  test('uma chave que o servidor não conhece segue a mesma regra (ele ignora-a)', () => {
    expect(juntarAlteracoes({ outra: 1 }, { outra: 2 })).toStrictEqual({ outra: 2 });
    expect(juntarAlteracoes({ outra: 1 }, {})).toStrictEqual({ outra: 1 });
  });
});

describe('juntarAlteracoes(a, b): a ordem, a última vence', () => {
  test('a ordem nova substitui a anterior (não se juntam as duas listas)', () => {
    expect(juntarAlteracoes({ ordem: [A, B, C] }, { ordem: [C, A] })).toStrictEqual({ ordem: [C, A] });
  });

  test('a ordem só de um dos lados fica', () => {
    expect(juntarAlteracoes({ ordem: [B, A] }, { hora_saida: '09:00' })).toStrictEqual({ ordem: [B, A], hora_saida: '09:00' });
    expect(juntarAlteracoes({ hora_saida: '09:00' }, { ordem: [B, A] })).toStrictEqual({ hora_saida: '09:00', ordem: [B, A] });
  });

  test('uma ordem vazia também vence', () => {
    expect(juntarAlteracoes({ ordem: [A, B] }, { ordem: [] })).toStrictEqual({ ordem: [] });
  });
});

describe('juntarAlteracoes(a, b): as paragens juntam-se por id e por campo', () => {
  test('ids diferentes ficam todos; no mesmo id, os campos dos dois', () => {
    expect(
      juntarAlteracoes(
        { paragens: { [A]: { motivo: 'amostra' }, [B]: { manter_fechada: true } } },
        { paragens: { [A]: { manter_fechada: true }, [C]: { nao_cabe: false } } },
      ),
    ).toStrictEqual({
      paragens: {
        [A]: { motivo: 'amostra', manter_fechada: true },
        [B]: { manter_fechada: true },
        [C]: { nao_cabe: false },
      },
    });
  });

  test.each([
    ['tempo_servico_min', 20, 35],
    ['manter_fechada', true, false],
    ['motivo', 'amostra', 'entrega'],
  ])('o mesmo campo da mesma paragem: a última vence (%s)', (campo, primeiro, segundo) => {
    expect(juntarAlteracoes({ paragens: { [A]: { [campo]: primeiro } } }, { paragens: { [A]: { [campo]: segundo } } })).toStrictEqual({
      paragens: { [A]: { [campo]: segundo } },
    });
  });

  test('as paragens só de um dos lados ficam', () => {
    expect(juntarAlteracoes({ paragens: { [A]: { motivo: 'amostra' } } }, { ordem: [A] })).toStrictEqual({
      paragens: { [A]: { motivo: 'amostra' } },
      ordem: [A],
    });
    expect(juntarAlteracoes({ ordem: [A] }, { paragens: { [A]: { motivo: 'amostra' } } })).toStrictEqual({
      ordem: [A],
      paragens: { [A]: { motivo: 'amostra' } },
    });
  });

  test('um motivo novo sem tempo deita fora o tempo pendente: o servidor põe o padrão do motivo novo, como pedido a pedido', () => {
    expect(
      juntarAlteracoes({ paragens: { [A]: { tempo_servico_min: 20, manter_fechada: true } } }, { paragens: { [A]: { motivo: 'entrega' } } }),
    ).toStrictEqual({ paragens: { [A]: { manter_fechada: true, motivo: 'entrega' } } });
  });

  test('um motivo novo com tempo leva esse tempo', () => {
    expect(
      juntarAlteracoes({ paragens: { [A]: { tempo_servico_min: 20 } } }, { paragens: { [A]: { motivo: 'entrega', tempo_servico_min: 12 } } }),
    ).toStrictEqual({ paragens: { [A]: { tempo_servico_min: 12, motivo: 'entrega' } } });
  });

  test('outra alteração depois de um motivo com tempo não mexe nesse tempo', () => {
    expect(
      juntarAlteracoes({ paragens: { [A]: { motivo: 'entrega', tempo_servico_min: 12 } } }, { paragens: { [A]: { manter_fechada: true } } }),
    ).toStrictEqual({ paragens: { [A]: { motivo: 'entrega', tempo_servico_min: 12, manter_fechada: true } } });
  });

  test('um tempo depois de um motivo fica com os dois (o tempo explícito ganha no servidor)', () => {
    expect(
      juntarAlteracoes({ paragens: { [A]: { motivo: 'entrega' } } }, { paragens: { [A]: { tempo_servico_min: 25 } } }),
    ).toStrictEqual({ paragens: { [A]: { motivo: 'entrega', tempo_servico_min: 25 } } });
  });

  test('o motivo novo só mexe no tempo da sua paragem', () => {
    expect(
      juntarAlteracoes(
        { paragens: { [A]: { tempo_servico_min: 20 }, [B]: { tempo_servico_min: 30 } } },
        { paragens: { [A]: { motivo: 'entrega' } } },
      ),
    ).toStrictEqual({ paragens: { [A]: { motivo: 'entrega' }, [B]: { tempo_servico_min: 30 } } });
  });

  test('alterações de uma paragem que não são um objeto: as últimas vencem inteiras (o servidor recusa-as com 422)', () => {
    expect(juntarAlteracoes({ paragens: { [A]: { motivo: 'amostra' } } }, { paragens: { [A]: 'x' } })).toStrictEqual({
      paragens: { [A]: 'x' },
    });
    expect(juntarAlteracoes({ paragens: { [A]: ['x'] } }, { paragens: { [A]: { motivo: 'amostra' } } })).toStrictEqual({
      paragens: { [A]: { motivo: 'amostra' } },
    });
  });

  test('umas paragens que não são um objeto: as últimas vencem inteiras', () => {
    expect(juntarAlteracoes({ paragens: { [A]: { motivo: 'amostra' } } }, { paragens: [A] })).toStrictEqual({ paragens: [A] });
    expect(juntarAlteracoes({ paragens: 'x' }, { paragens: { [A]: { motivo: 'amostra' } } })).toStrictEqual({
      paragens: { [A]: { motivo: 'amostra' } },
    });
  });
});

describe('juntarAlteracoes(a, b): retirar é a união, e o retirar ganha', () => {
  test('a união sem repetidos, pela ordem em que chegaram', () => {
    expect(juntarAlteracoes({ retirar: [A, B] }, { retirar: [C, A] })).toStrictEqual({ retirar: [A, B, C] });
  });

  test('retirar só de um dos lados fica', () => {
    expect(juntarAlteracoes({ retirar: [A] }, { hora_saida: '09:00' })).toStrictEqual({ retirar: [A], hora_saida: '09:00' });
    expect(juntarAlteracoes({ hora_saida: '09:00' }, { retirar: [A] })).toStrictEqual({ hora_saida: '09:00', retirar: [A] });
  });

  test('os repetidos de um só lado também saem', () => {
    expect(juntarAlteracoes({}, { retirar: [A, A, B] })).toStrictEqual({ retirar: [A, B] });
  });

  test('o retirado sai da ordem e das paragens que vieram antes', () => {
    expect(
      juntarAlteracoes({ ordem: [A, B, C], paragens: { [B]: { motivo: 'amostra' }, [C]: { manter_fechada: true } } }, { retirar: [B] }),
    ).toStrictEqual({ ordem: [A, C], paragens: { [C]: { manter_fechada: true } }, retirar: [B] });
  });

  test('o retirado também sai da ordem e das paragens que vieram depois (o servidor recusava a paragem com 422)', () => {
    expect(
      juntarAlteracoes({ retirar: [B] }, { ordem: [C, B, A], paragens: { [B]: { motivo: 'amostra' }, [A]: { tempo_servico_min: 30 } } }),
    ).toStrictEqual({ retirar: [B], ordem: [C, A], paragens: { [A]: { tempo_servico_min: 30 } } });
  });

  test('num só corpo, o retirado também sai da ordem e das paragens', () => {
    expect(juntarAlteracoes({}, { ordem: [A, B], paragens: { [A]: { motivo: 'entrega' } }, retirar: [A] })).toStrictEqual({
      ordem: [B],
      paragens: {},
      retirar: [A],
    });
  });

  test('uma ordem e umas paragens que ficam vazias continuam no corpo (vazias)', () => {
    expect(juntarAlteracoes({ ordem: [A], paragens: { [A]: { motivo: 'amostra' } } }, { retirar: [A] })).toStrictEqual({
      ordem: [],
      paragens: {},
      retirar: [A],
    });
  });

  test('sem retirar, a ordem e as paragens ficam como estão', () => {
    expect(juntarAlteracoes({ ordem: [A, B] }, { paragens: { [A]: { motivo: 'amostra' } } })).toStrictEqual({
      ordem: [A, B],
      paragens: { [A]: { motivo: 'amostra' } },
    });
  });

  test('um retirar que não é uma lista conta como vazio', () => {
    expect(juntarAlteracoes({ retirar: A, ordem: [A, B] }, { retirar: [C] })).toStrictEqual({ retirar: [C], ordem: [A, B] });
    expect(juntarAlteracoes({ retirar: [A] }, { retirar: { [B]: true } })).toStrictEqual({ retirar: [A] });
  });

  test('uma ordem ou umas paragens que não são uma lista ou um objeto não rebentam', () => {
    expect(juntarAlteracoes({ ordem: 'x' }, { retirar: [A] })).toStrictEqual({ ordem: 'x', retirar: [A] });
    expect(juntarAlteracoes({ paragens: null }, { retirar: [A] })).toStrictEqual({ paragens: null, retirar: [A] });
    expect(juntarAlteracoes({ paragens: [A] }, { retirar: [A] })).toStrictEqual({ paragens: [A], retirar: [A] });
  });
});

describe('juntarAlteracoes(a, b): o corpo como vai no pedido', () => {
  test('a versão nunca passa: é a fila que põe a que está em vigor', () => {
    expect(juntarAlteracoes({ versao: 3, hora_saida: '09:00' }, { versao: 4 })).toStrictEqual({ hora_saida: '09:00' });
    expect(juntarAlteracoes({}, { versao: 4, ordem: [A] })).toStrictEqual({ ordem: [A] });
  });

  test('não mexe nos corpos que recebe e devolve estruturas novas', () => {
    const a = congelarAFundo({ ordem: [A, B], paragens: { [A]: { motivo: 'amostra' } }, inicio: { lat: 38.7, lng: -9.1 } });
    const b = congelarAFundo({ paragens: { [B]: { manter_fechada: true } }, fim: { lat: 38.6, lng: -9.2 }, retirar: [C] });
    const junta = juntarAlteracoes(a, b);
    expect(junta.ordem).not.toBe(a.ordem);
    expect(junta.paragens).not.toBe(a.paragens);
    expect(junta.paragens[A]).not.toBe(a.paragens[A]);
    expect(junta.paragens[B]).not.toBe(b.paragens[B]);
    expect(junta.inicio).not.toBe(a.inicio);
    expect(junta.fim).not.toBe(b.fim);
    expect(junta.retirar).not.toBe(b.retirar);
    junta.ordem.push(D);
    junta.paragens[A].motivo = 'entrega';
    expect(a).toStrictEqual({ ordem: [A, B], paragens: { [A]: { motivo: 'amostra' } }, inicio: { lat: 38.7, lng: -9.1 } });
  });

  test('só com um corpo, as paragens e a ordem também são cópias', () => {
    const b = congelarAFundo({ ordem: [A], paragens: { [A]: { motivo: 'amostra' } } });
    const junta = juntarAlteracoes({}, b);
    expect(junta).toStrictEqual(b);
    expect(junta.ordem).not.toBe(b.ordem);
    expect(junta.paragens).not.toBe(b.paragens);
    expect(junta.paragens[A]).not.toBe(b.paragens[A]);
  });

  test('um undefined não apaga o valor anterior (não vai no pedido)', () => {
    expect(juntarAlteracoes({ inicio: PONTO, hora_saida: '09:00' }, { inicio: undefined, hora_saida: undefined })).toStrictEqual({
      inicio: { lat: 38.72, lng: -9.14 },
      hora_saida: '09:00',
    });
    expect(juntarAlteracoes({ paragens: { [A]: { motivo: 'amostra' } } }, { paragens: { [A]: { motivo: undefined } } })).toStrictEqual({
      paragens: { [A]: { motivo: 'amostra' } },
    });
  });

  test('um motivo undefined não deita fora o tempo pendente', () => {
    expect(
      juntarAlteracoes({ paragens: { [A]: { tempo_servico_min: 20 } } }, { paragens: { [A]: { motivo: undefined } } }),
    ).toStrictEqual({ paragens: { [A]: { tempo_servico_min: 20 } } });
  });

  test('as chaves herdadas não contam', () => {
    const herdado = Object.create({ hora_saida: '10:00', retirar: [A] });
    herdado.fim = null;
    expect(juntarAlteracoes({ hora_saida: '09:00', ordem: [A] }, herdado)).toStrictEqual({ hora_saida: '09:00', ordem: [A], fim: null });
  });

  test.each([
    ['null', null],
    ['undefined', undefined],
    ['um texto', 'hora_saida'],
    ['um número', 3],
    ['uma lista', [{ hora_saida: '09:00' }]],
  ])('um corpo que não é um objeto (%s) conta como vazio', (_caso, nada) => {
    expect(juntarAlteracoes(nada, { hora_saida: '09:00' })).toStrictEqual({ hora_saida: '09:00' });
    expect(juntarAlteracoes({ hora_saida: '09:00' }, nada)).toStrictEqual({ hora_saida: '09:00' });
    expect(juntarAlteracoes(nada, nada)).toStrictEqual({});
  });

  test('uma função também conta como vazio (não vai no pedido)', () => {
    expect(juntarAlteracoes(() => ({ hora_saida: '10:00' }), { hora_saida: '09:00' })).toStrictEqual({ hora_saida: '09:00' });
    expect(juntarAlteracoes({ hora_saida: '09:00' }, () => ({ hora_saida: '10:00' }))).toStrictEqual({ hora_saida: '09:00' });
  });

  test('um objeto cujo JSON não é um objeto também conta como vazio', () => {
    expect(juntarAlteracoes({ toJSON: () => 'hora_saida' }, { hora_saida: '09:00' })).toStrictEqual({ hora_saida: '09:00' });
    expect(juntarAlteracoes({ hora_saida: '09:00' }, { toJSON: () => ['x'] })).toStrictEqual({ hora_saida: '09:00' });
  });

  test('sem nada de um lado nem do outro, nenhuma chave aparece', () => {
    expect(juntarAlteracoes({}, {})).toStrictEqual({});
    expect(Object.keys(juntarAlteracoes({ hora_saida: '09:00' }, { fim: null }))).toEqual(['hora_saida', 'fim']);
  });
});

describe('juntarAlteracoes: juntar muitas é o mesmo que juntar duas a duas, por qualquer agrupamento', () => {
  const CORPOS = [
    { ordem: [A, B, C] },
    { retirar: [B] },
    { paragens: { [A]: { tempo_servico_min: 20 } } },
    { paragens: { [A]: { motivo: 'entrega' } }, hora_saida: '09:00' },
    { ordem: [C, B, A], inicio: PONTO },
    { paragens: { [C]: { manter_fechada: true }, [A]: { tempo_servico_min: 40 } } },
    { inicio: null, estado: 'planeada' },
    { retirar: [D], paragens: { [D]: { motivo: 'amostra' } } },
  ];

  test('pela esquerda e pela direita dá o mesmo', () => {
    const pelaEsquerda = CORPOS.reduce((junta, corpo) => juntarAlteracoes(junta, corpo), {});
    const pelaDireita = CORPOS.reduceRight((junta, corpo) => juntarAlteracoes(corpo, junta), {});
    expect(pelaDireita).toEqual(pelaEsquerda);
    expect(pelaEsquerda).toStrictEqual({
      ordem: [C, A],
      retirar: [B, D],
      paragens: { [A]: { motivo: 'entrega', tempo_servico_min: 40 }, [C]: { manter_fechada: true } },
      hora_saida: '09:00',
      inicio: null,
      estado: 'planeada',
    });
  });

  test.each([1, 2, 3, 4, 5, 6, 7])('partindo a lista no %i, juntar as duas metades dá o mesmo', (corte) => {
    const juntar = (lista) => lista.reduce((junta, corpo) => juntarAlteracoes(junta, corpo), {});
    expect(juntarAlteracoes(juntar(CORPOS.slice(0, corte)), juntar(CORPOS.slice(corte)))).toEqual(juntar(CORPOS));
  });
});

// --- criarFilaRota: a construção e os getters ----------------------------------------------------

describe('criarFilaRota: a construção', () => {
  test.each([
    ['sem opções', undefined],
    ['sem enviar', {}],
    ['enviar que não é uma função', { enviar: 'alterarRota' }],
  ])('%s → TypeError', (_caso, opcoes) => {
    expect(() => criarFilaRota(opcoes)).toThrow(TypeError);
  });

  test.each([0, -1, 1.5, '3', true, NaN, Infinity, {}, [3]])('uma versão inicial %p → TypeError', (versao) => {
    expect(() => criarFilaRota({ enviar: jest.fn(), versao })).toThrow(TypeError);
  });

  test('a versão inicial: um inteiro ≥ 1, null (a rota virtual) ou em falta (= null)', () => {
    expect(criarFilaRota({ enviar: jest.fn(), versao: 1 }).versao).toBe(1);
    expect(criarFilaRota({ enviar: jest.fn(), versao: 42 }).versao).toBe(42);
    expect(criarFilaRota({ enviar: jest.fn(), versao: null }).versao).toBeNull();
    expect(criarFilaRota({ enviar: jest.fn() }).versao).toBeNull();
  });

  test('a fila acabada de criar está vazia, desocupada e a andar, e não chama o enviar', () => {
    const enviar = jest.fn();
    const fila = criarFilaRota({ enviar, versao: 3 });
    expect(fila.vazia).toBe(true);
    expect(fila.ocupada).toBe(false);
    expect(fila.parada).toBe(false);
    expect(fila.erro).toBeNull();
    expect(fila.versao).toBe(3);
    expect(fila.alteracoesPorConfirmar).toEqual([]);
    expect(TIPOS_DE_PEDIDO.map((tipo) => fila.tem(tipo))).toEqual([false, false, false, false]);
    expect(enviar).not.toHaveBeenCalled();
  });

  test('vazia, ocupada, parada, erro, versao e alteracoesPorConfirmar são getters, e a fila está congelada', () => {
    const fila = criarFilaRota({ enviar: jest.fn(), versao: 3 });
    for (const nome of ['vazia', 'ocupada', 'parada', 'erro', 'versao', 'alteracoesPorConfirmar']) {
      const descritor = Object.getOwnPropertyDescriptor(fila, nome);
      expect(typeof descritor.get).toBe('function');
      expect(descritor.set).toBeUndefined();
    }
    expect(Object.isFrozen(fila)).toBe(true);
  });
});

// --- criarFilaRota: um pedido de cada vez --------------------------------------------------------

describe('criarFilaRota: um só pedido em curso, pela ordem', () => {
  test('o primeiro pedido sai logo, com a versão em vigor, e a fila fica ocupada', () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.alterar({ hora_saida: '09:00' });
    expect(enviar).toHaveBeenCalledTimes(1);
    expect(chamadas[0].pedido).toStrictEqual({ tipo: 'alterar', corpo: { hora_saida: '09:00' }, versao: 3 });
    expect(Object.isFrozen(chamadas[0].pedido)).toBe(true);
    expect(fila.ocupada).toBe(true);
    expect(fila.vazia).toBe(false);
  });

  test('enquanto há um em curso, os outros esperam; cada um sai quando o anterior responde', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    const primeiro = seguir(fila.alterar({ hora_saida: '09:00' }));
    const segundo = seguir(fila.adicionar({ loja_id: LOJA, motivo: 'amostra' }));
    const terceiro = seguir(fila.otimizar());
    expect(enviar).toHaveBeenCalledTimes(1);

    chamadas[0].resolver(rota(4));
    await assentar();
    expect(primeiro).toEqual({ como: 'resolvida', valor: rota(4) });
    expect(segundo.como).toBe('pendente');
    expect(enviar).toHaveBeenCalledTimes(2);
    expect(chamadas[1].pedido).toStrictEqual({ tipo: 'adicionar', corpo: { loja_id: LOJA, motivo: 'amostra' }, versao: 4 });

    chamadas[1].resolver(rota(5));
    await assentar();
    expect(segundo).toEqual({ como: 'resolvida', valor: rota(5) });
    expect(enviar).toHaveBeenCalledTimes(3);
    expect(chamadas[2].pedido).toStrictEqual({ tipo: 'otimizar', corpo: null, versao: 5 });

    chamadas[2].resolver(rota(6));
    await assentar();
    expect(terceiro).toEqual({ como: 'resolvida', valor: rota(6) });
    expect(enviar).toHaveBeenCalledTimes(3);
    expect(fila.vazia).toBe(true);
    expect(fila.ocupada).toBe(false);
  });

  test('a promessa de cada pedido resolve com a resposta desse pedido (a mesma, sem cópia)', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    const promessa = fila.recalcular();
    const resposta = rota(3, { calculo: { atual: true } });
    chamadas[0].resolver(resposta);
    await expect(promessa).resolves.toBe(resposta);
  });

  test('na continuação de um pedido, a fila já mostra o estado seguinte (a versão nova e o pedido seguinte em curso)', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    const vistos = [];
    fila.alterar({ hora_saida: '09:00' }).then(() => vistos.push(['1.º', fila.versao, fila.ocupada, fila.vazia]));
    fila.alterar({ hora_saida: '09:00' });
    fila.recalcular().then(() => vistos.push(['3.º', fila.versao, fila.ocupada, fila.vazia]));
    chamadas[0].resolver(rota(4));
    await assentar();
    chamadas[1].resolver(rota(5));
    await assentar();
    chamadas[2].resolver(rota(5));
    await assentar();
    expect(vistos).toEqual([
      ['1.º', 4, true, false],
      ['3.º', 5, false, true],
    ]);
  });

  test('tem(tipo): o pedido em curso e os pendentes contam; um tipo desconhecido não', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.adicionar({ loja_id: LOJA });
    fila.recalcular();
    expect(fila.tem('adicionar')).toBe(true);
    expect(fila.tem('recalcular')).toBe(true);
    expect(fila.tem('alterar')).toBe(false);
    expect(fila.tem('otimizar')).toBe(false);
    expect(fila.tem('apagar')).toBe(false);
    expect(fila.tem(undefined)).toBe(false);

    chamadas[0].resolver(rota(4));
    await assentar();
    expect(fila.tem('adicionar')).toBe(false);
    expect(fila.tem('recalcular')).toBe(true);

    chamadas[1].resolver(rota(4));
    await assentar();
    expect(fila.tem('recalcular')).toBe(false);
  });

  test('vazia: sem nada em curso nem pendente; ocupada: com um pedido em curso', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.alterar({ hora_saida: '09:00' });
    fila.alterar({ hora_saida: '10:00' });
    expect([fila.vazia, fila.ocupada]).toEqual([false, true]);
    chamadas[0].resolver(rota(4));
    await assentar();
    expect([fila.vazia, fila.ocupada]).toEqual([false, true]);
    chamadas[1].resolver(rota(5));
    await assentar();
    expect([fila.vazia, fila.ocupada]).toEqual([true, false]);
  });
});

// --- criarFilaRota: o que se junta e o que não se junta ------------------------------------------

describe('criarFilaRota: os alterar pendentes juntam-se num', () => {
  test('dois alterar à espera saem num só PATCH, e as duas promessas resolvem com a mesma resposta', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.adicionar({ loja_id: LOJA });
    const segundo = fila.alterar({ ordem: [A, B, C], paragens: { [A]: { motivo: 'amostra' } } });
    const terceiro = fila.alterar({ retirar: [B], hora_saida: '09:00' });
    const quarto = fila.alterar({ paragens: { [C]: { manter_fechada: true } } });

    chamadas[0].resolver(rota(4));
    await assentar();
    expect(enviar).toHaveBeenCalledTimes(2);
    expect(chamadas[1].pedido).toStrictEqual({
      tipo: 'alterar',
      corpo: {
        ordem: [A, C],
        paragens: { [A]: { motivo: 'amostra' }, [C]: { manter_fechada: true } },
        retirar: [B],
        hora_saida: '09:00',
      },
      versao: 4,
    });

    const resposta = rota(5);
    chamadas[1].resolver(resposta);
    await expect(segundo).resolves.toBe(resposta);
    await expect(terceiro).resolves.toBe(resposta);
    await expect(quarto).resolves.toBe(resposta);
    expect(enviar).toHaveBeenCalledTimes(2);
    expect(fila.vazia).toBe(true);
  });

  test('um alterar nunca se junta ao que já está em curso (já saiu)', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.alterar({ hora_saida: '09:00' });
    fila.alterar({ hora_regresso_limite: '18:00' });
    expect(chamadas[0].pedido.corpo).toStrictEqual({ hora_saida: '09:00' });
    chamadas[0].resolver(rota(4));
    await assentar();
    expect(chamadas[1].pedido.corpo).toStrictEqual({ hora_regresso_limite: '18:00' });
  });

  test('só se juntam alterar seguidos: um adicionar pelo meio fica entre os dois (a alteração seguinte pode ser da loja nova)', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.recalcular();
    fila.alterar({ retirar: [A] });
    fila.adicionar({ loja_id: LOJA, motivo: 'entrega' });
    fila.alterar({ paragens: { [D]: { tempo_servico_min: 30 } } });
    for (let i = 0; i < 4; i += 1) {
      chamadas[i].resolver(rota(4 + i));
      await assentar();
    }
    expect(chamadas.map(({ pedido }) => [pedido.tipo, pedido.corpo, pedido.versao])).toEqual([
      ['recalcular', null, 3],
      ['alterar', { retirar: [A] }, 4],
      ['adicionar', { loja_id: LOJA, motivo: 'entrega' }, 5],
      ['alterar', { paragens: { [D]: { tempo_servico_min: 30 } } }, 6],
    ]);
  });

  test('um otimizar ou um recalcular pelo meio também separa os alterar', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.adicionar({ loja_id: LOJA });
    fila.alterar({ hora_saida: '09:00' });
    fila.otimizar();
    fila.alterar({ hora_saida: '10:00' });
    fila.recalcular();
    fila.alterar({ hora_saida: '11:00' });
    for (let i = 0; i < 6; i += 1) {
      chamadas[i].resolver(rota(4 + i));
      await assentar();
    }
    expect(chamadas.map(({ pedido }) => pedido.tipo)).toEqual(['adicionar', 'alterar', 'otimizar', 'alterar', 'recalcular', 'alterar']);
    expect(chamadas.map(({ pedido }) => pedido.corpo?.hora_saida ?? null)).toEqual([null, '09:00', null, '10:00', null, '11:00']);
  });
});

describe('criarFilaRota: adicionar e otimizar nunca se juntam; os recalcular pendentes ficam um', () => {
  test('dois adicionar à espera saem cada um com a sua loja', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.alterar({ hora_saida: '09:00' });
    fila.adicionar({ loja_id: LOJA, motivo: 'entrega' });
    fila.adicionar({ loja_id: D });
    for (let i = 0; i < 3; i += 1) {
      chamadas[i].resolver(rota(4 + i));
      await assentar();
    }
    expect(chamadas.slice(1).map(({ pedido }) => pedido)).toStrictEqual([
      { tipo: 'adicionar', corpo: { loja_id: LOJA, motivo: 'entrega' }, versao: 4 },
      { tipo: 'adicionar', corpo: { loja_id: D }, versao: 5 },
    ]);
  });

  test('dois otimizar à espera saem os dois', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.alterar({ hora_saida: '09:00' });
    fila.otimizar();
    fila.otimizar();
    for (let i = 0; i < 3; i += 1) {
      chamadas[i].resolver(rota(4 + i));
      await assentar();
    }
    expect(chamadas.map(({ pedido }) => [pedido.tipo, pedido.versao])).toEqual([
      ['alterar', 3],
      ['otimizar', 4],
      ['otimizar', 5],
    ]);
  });

  test('vários recalcular à espera saem num só, e todas as promessas resolvem com essa resposta', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.alterar({ hora_saida: '09:00' });
    const promessas = [fila.recalcular(), fila.recalcular(), fila.recalcular()];
    chamadas[0].resolver(rota(4));
    await assentar();
    expect(enviar).toHaveBeenCalledTimes(2);
    expect(chamadas[1].pedido).toStrictEqual({ tipo: 'recalcular', corpo: null, versao: 4 });
    const resposta = rota(4, { calculo: { atual: true } });
    chamadas[1].resolver(resposta);
    for (const promessa of promessas) {
      await expect(promessa).resolves.toBe(resposta);
    }
    expect(enviar).toHaveBeenCalledTimes(2);
  });

  test('o recalcular que fica é o do fim: as horas saem depois de tudo o que está à espera', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.adicionar({ loja_id: LOJA });
    const primeiro = seguir(fila.recalcular());
    fila.alterar({ ordem: [B, A] });
    fila.adicionar({ loja_id: D });
    const segundo = seguir(fila.recalcular());
    for (let i = 0; i < 4; i += 1) {
      chamadas[i].resolver(rota(4 + i));
      await assentar();
    }
    expect(chamadas.map(({ pedido }) => pedido.tipo)).toEqual(['adicionar', 'alterar', 'adicionar', 'recalcular']);
    expect(primeiro).toEqual({ como: 'resolvida', valor: rota(7) });
    expect(segundo).toEqual({ como: 'resolvida', valor: rota(7) });
    expect(enviar).toHaveBeenCalledTimes(4);
  });

  test('um recalcular depois de outro já em curso fica à espera (as horas podem ter mudado entretanto)', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.recalcular();
    fila.recalcular();
    chamadas[0].resolver(rota(3));
    await assentar();
    expect(enviar).toHaveBeenCalledTimes(2);
    expect(chamadas[1].pedido.tipo).toBe('recalcular');
  });

  test('um alterar depois de um recalcular à espera não salta por cima dele (só se junta a um alterar seguido)', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.adicionar({ loja_id: LOJA });
    fila.alterar({ hora_saida: '09:00' });
    fila.recalcular();
    fila.recalcular();
    fila.alterar({ hora_saida: '10:00' });
    for (let i = 0; i < 4; i += 1) {
      chamadas[i].resolver(rota(4 + i));
      await assentar();
    }
    expect(chamadas.map(({ pedido }) => [pedido.tipo, pedido.corpo])).toEqual([
      ['adicionar', { loja_id: LOJA }],
      ['alterar', { hora_saida: '09:00' }],
      ['recalcular', null],
      ['alterar', { hora_saida: '10:00' }],
    ]);
  });
});

// --- criarFilaRota: os corpos ---------------------------------------------------------------------

describe('criarFilaRota: os corpos que saem', () => {
  test('o alterar sai com o corpo como vai no pedido, copiado e congelado: mudar o objeto depois não muda nada', () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    const corpo = { ordem: [A, B], paragens: { [A]: { motivo: 'amostra' } }, inicio: { lat: 38.7, lng: -9.1 }, fim: undefined };
    fila.alterar(corpo);
    corpo.ordem.push(C);
    corpo.paragens[A].motivo = 'entrega';
    corpo.inicio.lat = 0;
    const enviado = chamadas[0].pedido.corpo;
    expect(enviado).toStrictEqual({ ordem: [A, B], paragens: { [A]: { motivo: 'amostra' } }, inicio: { lat: 38.7, lng: -9.1 } });
    expect(estaCongeladoAFundo(enviado)).toBe(true);
  });

  test('o alterar sai já arrumado: o retirado sai da ordem e das paragens do mesmo corpo', () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.alterar({ ordem: [A, B], paragens: { [B]: { motivo: 'entrega' } }, retirar: [B] });
    expect(chamadas[0].pedido.corpo).toStrictEqual({ ordem: [A], paragens: {}, retirar: [B] });
  });

  test('a versão de um corpo nunca sai: vai a da fila (alterar e adicionar)', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.alterar({ versao: 99, hora_saida: '09:00' });
    fila.adicionar({ loja_id: LOJA, versao: 99 });
    chamadas[0].resolver(rota(4));
    await assentar();
    expect(chamadas[0].pedido).toStrictEqual({ tipo: 'alterar', corpo: { hora_saida: '09:00' }, versao: 3 });
    expect(chamadas[1].pedido).toStrictEqual({ tipo: 'adicionar', corpo: { loja_id: LOJA }, versao: 4 });
  });

  test('o adicionar sai com uma cópia congelada do corpo, sem os undefined', () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: null });
    const corpo = { loja_id: LOJA, motivo: undefined };
    fila.adicionar(corpo);
    corpo.loja_id = D;
    expect(chamadas[0].pedido).toStrictEqual({ tipo: 'adicionar', corpo: { loja_id: LOJA }, versao: null });
    expect(estaCongeladoAFundo(chamadas[0].pedido)).toBe(true);
  });

  test.each([
    ['nada', undefined],
    ['null', null],
    ['um texto', LOJA],
  ])('um adicionar ou um alterar com %s sai com um corpo vazio (o servidor responde 422 ou 200 sem mudar)', async (_caso, nada) => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.adicionar(nada);
    fila.alterar(nada);
    chamadas[0].resolver(rota(3));
    await assentar();
    expect(chamadas[0].pedido.corpo).toStrictEqual({});
    expect(chamadas[1].pedido.corpo).toStrictEqual({});
  });

  test('o recalcular e o otimizar saem sem corpo (só a versão)', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.recalcular({ versao: 99 });
    fila.otimizar({ versao: 99 });
    chamadas[0].resolver(rota(3));
    await assentar();
    expect(chamadas.map(({ pedido }) => pedido)).toStrictEqual([
      { tipo: 'recalcular', corpo: null, versao: 3 },
      { tipo: 'otimizar', corpo: null, versao: 3 },
    ]);
  });
});

describe('criarFilaRota: alteracoesPorConfirmar (para a visão otimista do planeador)', () => {
  test('os corpos dos alterar em curso e à espera, pela ordem; os outros pedidos não', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.alterar({ ordem: [B, A] });
    fila.adicionar({ loja_id: LOJA });
    fila.alterar({ hora_saida: '09:00' });
    fila.alterar({ retirar: [A] });
    fila.recalcular();
    expect(fila.alteracoesPorConfirmar).toStrictEqual([{ ordem: [B, A] }, { hora_saida: '09:00', retirar: [A] }]);
    expect(estaCongeladoAFundo(fila.alteracoesPorConfirmar)).toBe(true);

    chamadas[0].resolver(rota(4));
    await assentar();
    expect(fila.alteracoesPorConfirmar).toStrictEqual([{ hora_saida: '09:00', retirar: [A] }]);
    chamadas[1].resolver(rota(5));
    await assentar();
    expect(fila.alteracoesPorConfirmar).toStrictEqual([{ hora_saida: '09:00', retirar: [A] }]);
    chamadas[2].resolver(rota(6));
    await assentar();
    expect(fila.alteracoesPorConfirmar).toStrictEqual([]);
  });

  test('um alterar recusado sai da lista (a visão otimista desfaz-se)', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.alterar({ paragens: { [A]: { tempo_servico_min: 999 } } }).catch(() => {});
    expect(fila.alteracoesPorConfirmar).toStrictEqual([{ paragens: { [A]: { tempo_servico_min: 999 } } }]);
    chamadas[0].rejeitar(new ErroCrm({ codigo: 'validacao', mensagem: 'Verifique os campos assinalados.', estado: 422 }));
    await assentar();
    expect(fila.alteracoesPorConfirmar).toStrictEqual([]);
  });
});

// --- criarFilaRota: a versão em vigor -------------------------------------------------------------

describe('criarFilaRota: cada pedido sai com a versão da última resposta', () => {
  test('a versão do pedido é a do momento em que sai, não a do momento em que foi pedido', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.alterar({ hora_saida: '09:00' });
    fila.adicionar({ loja_id: LOJA });
    fila.otimizar();
    fila.recalcular();
    expect(fila.versao).toBe(3);
    chamadas[0].resolver(rota(4));
    await assentar();
    expect(fila.versao).toBe(4);
    chamadas[1].resolver(rota(5));
    await assentar();
    chamadas[2].resolver(rota(6));
    await assentar();
    chamadas[3].resolver(rota(6));
    await assentar();
    expect(chamadas.map(({ pedido }) => pedido.versao)).toEqual([3, 4, 5, 6]);
    expect(fila.versao).toBe(6);
  });

  test('uma rota virtual (versão null): o primeiro pedido sai com null e o seguinte com a versão da rota criada', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: null });
    fila.adicionar({ loja_id: LOJA });
    fila.alterar({ hora_saida: '09:00' });
    expect(chamadas[0].pedido.versao).toBeNull();
    chamadas[0].resolver(rota(1));
    await assentar();
    expect(chamadas[1].pedido.versao).toBe(1);
    expect(fila.versao).toBe(1);
  });

  test('a versão da resposta vale mesmo que seja mais baixa (o servidor é que sabe)', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 8 });
    fila.recalcular();
    chamadas[0].resolver(rota(2));
    await assentar();
    expect(fila.versao).toBe(2);
  });

  test.each([
    ['sem versão', { id: 'r1' }],
    ['versão null', rota(null)],
    ['versão 0', rota(0)],
    ['versão em texto', rota('5')],
    ['versão decimal', rota(4.5)],
    ['versão verdadeira', rota(true)],
    ['nada', undefined],
    ['null', null],
    ['um texto', 'ok'],
  ])('uma resposta %s não muda a versão em vigor', async (_caso, resposta) => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    const promessa = fila.alterar({ hora_saida: '09:00' });
    fila.recalcular();
    chamadas[0].resolver(resposta);
    await expect(promessa).resolves.toBe(resposta);
    expect(fila.versao).toBe(3);
    expect(chamadas[1].pedido.versao).toBe(3);
  });

  test('um enviar que devolve logo a rota (sem promessa) também conta', async () => {
    const enviar = jest.fn(() => rota(9));
    const fila = criarFilaRota({ enviar, versao: 3 });
    await expect(fila.alterar({ hora_saida: '09:00' })).resolves.toEqual(rota(9));
    expect(fila.versao).toBe(9);
    expect(fila.vazia).toBe(true);
  });
});

// --- criarFilaRota: os erros ----------------------------------------------------------------------

describe('criarFilaRota: um 409 da rota inteira para a fila', () => {
  test.each(['conflito', 'rota_em_curso', 'rota_fechada'])(
    '%s: recusa o pedido em curso e todos os pendentes com o mesmo erro, sem enviar mais nada',
    async (codigo) => {
      const { enviar, chamadas } = servidorControlado();
      const fila = criarFilaRota({ enviar, versao: 3 });
      const promessas = [
        fila.alterar({ hora_saida: '09:00' }),
        fila.alterar({ ordem: [A] }),
        fila.alterar({ retirar: [B] }),
        fila.adicionar({ loja_id: LOJA }),
        fila.recalcular(),
        fila.otimizar(),
      ].map(seguir);
      const erro = erro409(codigo);
      chamadas[0].rejeitar(erro);
      await assentar();
      expect(promessas.map((p) => p.como)).toEqual(Array(6).fill('rejeitada'));
      for (const p of promessas) expect(p.valor).toBe(erro);
      expect(enviar).toHaveBeenCalledTimes(1);
      expect(fila.parada).toBe(true);
      expect(fila.erro).toBe(erro);
      expect(fila.vazia).toBe(true);
      expect(fila.ocupada).toBe(false);
      expect(fila.versao).toBe(3);
      expect(fila.alteracoesPorConfirmar).toEqual([]);
      expect(TIPOS_DE_PEDIDO.map((tipo) => fila.tem(tipo))).toEqual([false, false, false, false]);
    },
  );

  test('parada, cada pedido novo é recusado logo com o mesmo erro e nada sai', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.alterar({ hora_saida: '09:00' }).catch(() => {});
    const erro = erro409('conflito');
    chamadas[0].rejeitar(erro);
    await assentar();
    for (const pedir of [() => fila.alterar({ hora_saida: '10:00' }), () => fila.adicionar({ loja_id: LOJA }), () => fila.recalcular(), () => fila.otimizar()]) {
      await expect(pedir()).rejects.toBe(erro);
    }
    expect(enviar).toHaveBeenCalledTimes(1);
    expect(fila.vazia).toBe(true);
    expect(fila.alteracoesPorConfirmar).toEqual([]);
  });

  test('retomar(versao): a fila volta a andar com a versão da rota relida', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.alterar({ hora_saida: '09:00' }).catch(() => {});
    chamadas[0].rejeitar(erro409('conflito'));
    await assentar();
    fila.retomar(7);
    expect(fila.parada).toBe(false);
    expect(fila.erro).toBeNull();
    expect(fila.versao).toBe(7);
    expect(enviar).toHaveBeenCalledTimes(1);
    const promessa = fila.alterar({ hora_saida: '10:00' });
    expect(chamadas[1].pedido).toStrictEqual({ tipo: 'alterar', corpo: { hora_saida: '10:00' }, versao: 7 });
    chamadas[1].resolver(rota(8));
    await expect(promessa).resolves.toEqual(rota(8));
    expect(fila.versao).toBe(8);
  });

  test('retomar(null) também serve (a rota relida pode ser virtual)', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.recalcular().catch(() => {});
    chamadas[0].rejeitar(erro409('rota_fechada'));
    await assentar();
    fila.retomar(null);
    expect(fila.versao).toBeNull();
    expect(fila.parada).toBe(false);
  });

  test.each([undefined, 0, -2, 2.5, '7', false, NaN])('retomar(%p) → TypeError, e a fila continua parada', async (versao) => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.recalcular().catch(() => {});
    const erro = erro409('conflito');
    chamadas[0].rejeitar(erro);
    await assentar();
    expect(() => fila.retomar(versao)).toThrow(TypeError);
    expect(fila.parada).toBe(true);
    expect(fila.erro).toBe(erro);
    expect(fila.versao).toBe(3);
  });

  test('retomar sem estar parada só muda a versão em vigor', () => {
    const { enviar } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.retomar(5);
    expect(fila.versao).toBe(5);
    expect(fila.parada).toBe(false);
    expect(enviar).not.toHaveBeenCalled();
  });

  test('um 409 que não é da rota inteira (ja_na_rota, rota_cheia) não para a fila', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    const primeiro = seguir(fila.adicionar({ loja_id: LOJA }));
    const segundo = seguir(fila.adicionar({ loja_id: D }));
    fila.alterar({ hora_saida: '09:00' });
    chamadas[0].rejeitar(erro409('ja_na_rota'));
    await assentar();
    chamadas[1].rejeitar(erro409('rota_cheia'));
    await assentar();
    expect([primeiro.como, segundo.como]).toEqual(['rejeitada', 'rejeitada']);
    expect(fila.parada).toBe(false);
    expect(enviar).toHaveBeenCalledTimes(3);
    expect(chamadas[2].pedido).toStrictEqual({ tipo: 'alterar', corpo: { hora_saida: '09:00' }, versao: 3 });
  });

  test('o código decide, não o estado HTTP: um código desconhecido com 409 não para', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.alterar({ hora_saida: '09:00' }).catch(() => {});
    chamadas[0].rejeitar(erro409('outro_conflito'));
    await assentar();
    expect(fila.parada).toBe(false);
  });
});

describe('criarFilaRota: outro erro recusa só esse pedido, e os seguintes continuam', () => {
  test.each([
    ['422 validacao', () => new ErroCrm({ codigo: 'validacao', mensagem: 'Verifique os campos assinalados.', estado: 422, campos: { x: 'y' } })],
    ['503 calculo_indisponivel', () => new ErroCrm({ codigo: 'calculo_indisponivel', mensagem: 'Cálculo automático indisponível — ordene à mão', estado: 503, extra: { tipo: 'limite' } })],
    ['sem_rede', () => new ErroCrm({ codigo: 'sem_rede', mensagem: 'Sem rede — verifique a ligação e tente novamente.', estado: 0 })],
    ['404 nao_encontrado', () => new ErroCrm({ codigo: 'nao_encontrado', mensagem: 'Ainda não há rota para este dia.', estado: 404 })],
    ['erro_interno', () => new ErroCrm({ codigo: 'erro_interno', mensagem: 'Erro inesperado — tente novamente.', estado: 0 })],
    ['um Error sem código', () => new TypeError('enganei-me')],
    ['um texto', () => 'conflito'],
    ['nada', () => undefined],
    ['um objeto com o código num sítio errado', () => ({ detail: { codigo: 'conflito' } })],
  ])('%s', async (_caso, criarErro) => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    const primeiro = seguir(fila.alterar({ hora_saida: '09:00' }));
    const segundo = seguir(fila.recalcular());
    const erro = criarErro();
    chamadas[0].rejeitar(erro);
    await assentar();
    expect(primeiro).toEqual({ como: 'rejeitada', valor: erro });
    expect(segundo.como).toBe('pendente');
    expect(fila.parada).toBe(false);
    expect(fila.erro).toBeNull();
    expect(fila.versao).toBe(3);
    expect(enviar).toHaveBeenCalledTimes(2);
    expect(chamadas[1].pedido).toStrictEqual({ tipo: 'recalcular', corpo: null, versao: 3 });
    chamadas[1].resolver(rota(3));
    await assentar();
    expect(segundo).toEqual({ como: 'resolvida', valor: rota(3) });
    expect(fila.vazia).toBe(true);
  });

  test('os alterar juntos são recusados juntos, e o pedido seguinte sai', async () => {
    const { enviar, chamadas } = servidorControlado();
    const fila = criarFilaRota({ enviar, versao: 3 });
    fila.adicionar({ loja_id: LOJA });
    const juntos = [fila.alterar({ hora_saida: '09:00' }), fila.alterar({ ordem: [A] })].map(seguir);
    fila.otimizar();
    chamadas[0].resolver(rota(4));
    await assentar();
    const erro = new ErroCrm({ codigo: 'validacao', mensagem: 'Verifique os campos assinalados.', estado: 422 });
    chamadas[1].rejeitar(erro);
    await assentar();
    expect(juntos).toEqual([
      { como: 'rejeitada', valor: erro },
      { como: 'rejeitada', valor: erro },
    ]);
    expect(chamadas[2].pedido).toStrictEqual({ tipo: 'otimizar', corpo: null, versao: 4 });
  });

  test('um enviar que rebenta logo dá uma promessa recusada (nunca lança) e a fila continua', async () => {
    const erro = new Error('rebentou');
    const enviar = jest.fn().mockImplementationOnce(() => {
      throw erro;
    }).mockImplementationOnce(() => Promise.resolve(rota(4)));
    const fila = criarFilaRota({ enviar, versao: 3 });
    let promessa;
    expect(() => {
      promessa = fila.alterar({ hora_saida: '09:00' });
    }).not.toThrow();
    const segundo = fila.recalcular();
    await expect(promessa).rejects.toBe(erro);
    await expect(segundo).resolves.toEqual(rota(4));
    expect(enviar).toHaveBeenCalledTimes(2);
    expect(fila.versao).toBe(4);
    expect(fila.vazia).toBe(true);
  });

  test('um enviar que rebenta logo com um 409 da rota inteira também para a fila', async () => {
    const erro = erro409('rota_em_curso');
    const enviar = jest.fn(() => {
      throw erro;
    });
    const fila = criarFilaRota({ enviar, versao: 3 });
    const primeiro = fila.alterar({ hora_saida: '09:00' });
    const segundo = fila.recalcular();
    await expect(primeiro).rejects.toBe(erro);
    await expect(segundo).rejects.toBe(erro);
    expect(enviar).toHaveBeenCalledTimes(1);
    expect(fila.parada).toBe(true);
  });
});

// --- enviarPelaApi --------------------------------------------------------------------------------

describe('enviarPelaApi(api, data): o enviar do planeador sobre o api.js', () => {
  function apiFalsa() {
    return {
      alterarRota: jest.fn(() => Promise.resolve('alterada')),
      adicionarParagem: jest.fn(() => Promise.resolve('adicionada')),
      recalcularHoras: jest.fn(() => Promise.resolve('recalculada')),
      otimizarRota: jest.fn(() => Promise.resolve('otimizada')),
    };
  }

  test('alterar → alterarRota(data, {...corpo, versao})', async () => {
    const api = apiFalsa();
    const enviar = enviarPelaApi(api, '2026-10-12');
    await expect(enviar({ tipo: 'alterar', corpo: { ordem: [A], hora_saida: '09:00' }, versao: 4 })).resolves.toBe('alterada');
    expect(api.alterarRota).toHaveBeenCalledWith('2026-10-12', { ordem: [A], hora_saida: '09:00', versao: 4 });
    expect(api.alterarRota.mock.calls[0]).toHaveLength(2);
  });

  test('a versão da fila ganha a uma que venha no corpo', async () => {
    const api = apiFalsa();
    await enviarPelaApi(api, '2026-10-12')({ tipo: 'alterar', corpo: { versao: 99 }, versao: 4 });
    expect(api.alterarRota).toHaveBeenCalledWith('2026-10-12', { versao: 4 });
  });

  test('adicionar → adicionarParagem(data, {loja_id, motivo, versao}), também com a versão null', async () => {
    const api = apiFalsa();
    const enviar = enviarPelaApi(api, '2026-10-12');
    await expect(enviar({ tipo: 'adicionar', corpo: { loja_id: LOJA, motivo: 'entrega', outra: 1 }, versao: null })).resolves.toBe('adicionada');
    expect(api.adicionarParagem).toHaveBeenCalledWith('2026-10-12', { loja_id: LOJA, motivo: 'entrega', versao: null });
    await enviar({ tipo: 'adicionar', corpo: { loja_id: LOJA }, versao: 5 });
    expect(api.adicionarParagem).toHaveBeenLastCalledWith('2026-10-12', { loja_id: LOJA, motivo: undefined, versao: 5 });
  });

  test('recalcular → recalcularHoras(data, versao); otimizar → otimizarRota(data, versao)', async () => {
    const api = apiFalsa();
    const enviar = enviarPelaApi(api, '2026-10-12');
    await expect(enviar({ tipo: 'recalcular', corpo: null, versao: 6 })).resolves.toBe('recalculada');
    await expect(enviar({ tipo: 'otimizar', corpo: null, versao: 7 })).resolves.toBe('otimizada');
    expect(api.recalcularHoras).toHaveBeenCalledWith('2026-10-12', 6);
    expect(api.otimizarRota).toHaveBeenCalledWith('2026-10-12', 7);
    expect(api.alterarRota).not.toHaveBeenCalled();
    expect(api.adicionarParagem).not.toHaveBeenCalled();
  });

  test('cada tipo chama só a sua função', async () => {
    const api = apiFalsa();
    const enviar = enviarPelaApi(api, '2026-10-12');
    await enviar({ tipo: 'alterar', corpo: {}, versao: 1 });
    expect([api.alterarRota, api.adicionarParagem, api.recalcularHoras, api.otimizarRota].map((f) => f.mock.calls.length)).toEqual([1, 0, 0, 0]);
  });

  test.each(['apagar', undefined, 'constructor'])('um tipo desconhecido (%p) → promessa recusada com TypeError, sem chamar a API', async (tipo) => {
    const api = apiFalsa();
    await expect(enviarPelaApi(api, '2026-10-12')({ tipo, corpo: null, versao: 1 })).rejects.toThrow(TypeError);
    for (const funcao of Object.values(api)) expect(funcao).not.toHaveBeenCalled();
  });

  test('a fila sobre o cliente verdadeiro do api.js: os pedidos HTTP que saem', async () => {
    const pedidos = [];
    let versao = 3;
    const pedir = jest.fn((config) => {
      pedidos.push(config);
      versao += config.url.endsWith('/recalcular') ? 0 : 1;
      return Promise.resolve({ data: rota(versao) });
    });
    const fila = criarFilaRota({ enviar: enviarPelaApi(criarClienteCrm({ pedir }), '2026-10-12'), versao: 3 });
    fila.adicionar({ loja_id: LOJA });
    fila.alterar({ ordem: [A, B] });
    fila.alterar({ retirar: [B] });
    fila.recalcular();
    await fila.otimizar();
    expect(pedidos).toStrictEqual([
      { method: 'POST', url: '/rotas/2026-10-12/paragens', data: { loja_id: LOJA, versao: 3 } },
      { method: 'PATCH', url: '/rotas/2026-10-12', data: { ordem: [A], retirar: [B], versao: 4 } },
      { method: 'POST', url: '/rotas/2026-10-12/recalcular', data: { versao: 5 }, timeout: TIMEOUT_CALCULO_MS },
      { method: 'POST', url: '/rotas/2026-10-12/otimizar', data: { versao: 5 }, timeout: TIMEOUT_CALCULO_MS },
    ]);
    expect(fila.versao).toBe(6);
  });

  test('um 409 conflito do servidor (pelo erroCrm do api.js) para a fila', async () => {
    const pedir = jest.fn(() =>
      Promise.reject(
        Object.assign(new Error('Request failed with status code 409'), {
          isAxiosError: true,
          response: { status: 409, data: { detail: { codigo: 'conflito', mensagem: 'Alguém alterou entretanto.' } } },
        }),
      ),
    );
    const fila = criarFilaRota({ enviar: enviarPelaApi(criarClienteCrm({ pedir }), '2026-10-12'), versao: 3 });
    const primeiro = fila.alterar({ hora_saida: '09:00' });
    const segundo = fila.recalcular();
    await expect(primeiro).rejects.toMatchObject({ codigo: 'conflito', estado: 409 });
    await expect(segundo).rejects.toMatchObject({ codigo: 'conflito' });
    expect(pedir).toHaveBeenCalledTimes(1);
    expect(fila.parada).toBe(true);
  });
});

// --- O módulo -------------------------------------------------------------------------------------

test('o filaRota.js é puro: sem imports, sem DOM, sem relógio nem temporizadores', () => {
  const texto = fs.readFileSync(FILA_ROTA_JS, 'utf8');
  expect(texto).not.toMatch(/^\s*import\b/m);
  expect(texto).not.toMatch(/\brequire\(/);
  expect(texto).not.toMatch(
    /\b(document|window|navigator|globalThis|setTimeout|setInterval|queueMicrotask|requestAnimationFrame|Date|performance|addEventListener|fetch|axios)\b/,
  );
});
