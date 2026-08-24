/**
 * AS DECISÕES DOS BOTÕES DE IMPRIMIR — corridas de verdade, não lidas.
 *
 * A regra da casa: um guarda que procure o TEXTO de uma frase num ficheiro
 * fica verde com a condição desligada por trás dela. Já aconteceu duas vezes
 * neste módulo. Por isso estas funções vivem em `lib/pos.js`, fora do JSX, e
 * este ficheiro EXECUTA-AS.
 *
 * **O que isto NÃO prova:** que o botão do ecrã está mesmo ligado a esta
 * decisão. Isso vê-se com o POS aberto num browser, contra um servidor a
 * sério — e num Mac sem Mongo não há servidor a sério. Está dito no relatório.
 */
import {
  razaoDeNaoImprimir,
  razaoDeNaoImprimirPedido,
  MSG_PEDIDO_SEM_LINHAS,
  avisoDaFilaDeImpressao,
  haFalhadosPorVer,
  MSG_IMPRESSAO_SEM_PROGRAMA,
  MSG_IMPRESSAO_POR_SABER,
  MSG_IMPRESSAO_A_ENVIAR,
} from './pos';

const COM_PROGRAMA = { ha_programa: true, por_sair: 0, falhados: 0 };

describe('razaoDeNaoImprimir', () => {
  test('com programa a ouvir, o botão funciona', () => {
    expect(razaoDeNaoImprimir({ estado: COM_PROGRAMA })).toBeNull();
  });

  test('SEM programa a ouvir, o botão desliga e diz porquê', () => {
    // É a razão de existir de tudo isto: uma loja onde ninguém instalou o
    // programa não pode ter um botão que parece funcionar. O toque entrava na
    // fila, caducava meia hora depois, e a operadora dava o cliente por
    // servido sem papel nenhum ter existido.
    expect(razaoDeNaoImprimir({ estado: { ...COM_PROGRAMA, ha_programa: false } }))
      .toBe(MSG_IMPRESSAO_SEM_PROGRAMA);
  });

  test('enquanto NÃO SE SABE, desliga na mesma', () => {
    // Entre abrir o ecrã e a primeira resposta há um vão de um segundo. Um
    // botão que funcionasse nesse vão numa loja sem programa é exactamente o
    // engano que isto existe para não deixar acontecer.
    expect(razaoDeNaoImprimir({ estado: null })).toBe(MSG_IMPRESSAO_POR_SABER);
    expect(razaoDeNaoImprimir({})).toBe(MSG_IMPRESSAO_POR_SABER);
    expect(razaoDeNaoImprimir()).toBe(MSG_IMPRESSAO_POR_SABER);
  });

  test('a meio do envio, não deixa carregar outra vez', () => {
    expect(razaoDeNaoImprimir({ estado: COM_PROGRAMA, aImprimir: true }))
      .toBe(MSG_IMPRESSAO_A_ENVIAR);
  });

  test('«a enviar» vence «não há programa» — é o que está a acontecer agora', () => {
    expect(razaoDeNaoImprimir({
      estado: { ...COM_PROGRAMA, ha_programa: false }, aImprimir: true,
    })).toBe(MSG_IMPRESSAO_A_ENVIAR);
  });
});

describe('razaoDeNaoImprimirPedido', () => {
  // A ficha da COZINHA tem uma razão a mais do que os outros papéis: uma
  // conta ainda sem nada picado mandava para a fila o cabeçalho e mais nada
  // («PEDIDO COZINHA / #AZIA 10:05 / ===='), com o ecrã a dizer que tinha
  // imprimido. Basta tocar no botão antes de picar o primeiro copo.
  test('uma conta VAZIA desliga o botão e diz porquê', () => {
    expect(razaoDeNaoImprimirPedido({
      venda: { id: 'venda-1', linhas: [] }, estado: COM_PROGRAMA,
    })).toBe(MSG_PEDIDO_SEM_LINHAS);
  });

  test('com um copo picado, o botão funciona', () => {
    expect(razaoDeNaoImprimirPedido({
      venda: { id: 'venda-1', linhas: [{ produto_nome: 'Açaí' }] },
      estado: COM_PROGRAMA,
    })).toBeNull();
  });

  test('SEM programa a ouvir vence a conta vazia — é o problema maior', () => {
    // Não vale a pena dizer «pique alguma coisa» a quem não tem impressora
    // nenhuma a ouvir.
    expect(razaoDeNaoImprimirPedido({
      venda: { id: 'venda-1', linhas: [] },
      estado: { ...COM_PROGRAMA, ha_programa: false },
    })).toBe(MSG_IMPRESSAO_SEM_PROGRAMA);
  });

  test('sem venda nenhuma, continua a valer o guarda de sempre', () => {
    // O botão já está desligado por `!venda` no ecrã; aqui o que importa é
    // não inventar a frase da conta vazia quando não há conta.
    expect(razaoDeNaoImprimirPedido({ estado: COM_PROGRAMA })).toBeNull();
  });
});

describe('avisoDaFilaDeImpressao', () => {
  test('sem nada por sair nem falhado, não inventa aviso nenhum', () => {
    expect(avisoDaFilaDeImpressao(COM_PROGRAMA)).toBeNull();
    expect(avisoDaFilaDeImpressao(null)).toBeNull();
  });

  test('o que a fila DESISTIU de imprimir é dito', () => {
    // Uma fila que desiste em silêncio é pior do que uma fila que insiste: o
    // servidor desiste ao fim de algumas tentativas, e sem esta frase isso
    // era um segredo entre o servidor e o log.
    const um = avisoDaFilaDeImpressao({ ...COM_PROGRAMA, falhados: 1 });
    expect(um).toMatch(/não chegou a sair/);
    expect(um).toMatch(/Faturação/);
    expect(avisoDaFilaDeImpressao({ ...COM_PROGRAMA, falhados: 3 })).toMatch(/^3 papéis/);
  });

  test('o que está por sair também', () => {
    expect(avisoDaFilaDeImpressao({ ...COM_PROGRAMA, por_sair: 1 }))
      .toMatch(/um papel à espera/);
    expect(avisoDaFilaDeImpressao({ ...COM_PROGRAMA, por_sair: 4 }))
      .toMatch(/4 papéis à espera/);
  });

  test('o FALHADO vence o que está por sair', () => {
    // "Há 2 papéis à espera" ao lado de um que já não vai sair lê-se como
    // paciência; o que a operadora precisa de saber é que um se perdeu.
    expect(avisoDaFilaDeImpressao({ ...COM_PROGRAMA, por_sair: 2, falhados: 1 }))
      .toMatch(/não chegou a sair/);
  });
});

describe('haFalhadosPorVer', () => {
  test('só há o que dar por visto quando há papéis falhados', () => {
    // É esta condição que decide se o botão «Já vi» aparece. Sem ele, o aviso
    // ficava no ecrã sete dias — até o TTL do Mongo apagar o trabalho — e um
    // aviso que não se desliga é um aviso que se aprende a ignorar.
    expect(haFalhadosPorVer({ ...COM_PROGRAMA, falhados: 1 })).toBe(true);
    expect(haFalhadosPorVer({ ...COM_PROGRAMA, falhados: 3 })).toBe(true);
    expect(haFalhadosPorVer(COM_PROGRAMA)).toBe(false);
    expect(haFalhadosPorVer({ ...COM_PROGRAMA, por_sair: 2 })).toBe(false);
    expect(haFalhadosPorVer(null)).toBe(false);
    expect(haFalhadosPorVer(undefined)).toBe(false);
  });
});
