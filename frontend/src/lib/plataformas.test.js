/**
 * COMO O ECRÃ DAS PLATAFORMAS ESCREVE OS NÚMEROS — corrido, não lido.
 *
 * A promessa é a mesma que o backend deste módulo se dá ao trabalho de
 * cumprir: **um valor que não chegou nunca aparece como zero**. O `eur()` do
 * `lib/finance.js` faz `Number(n) || 0` e transforma um `null` em «0,00 €» —
 * e «0,00 €» na linha da Bolt Food lê-se como «não vendemos nada» em vez de
 * «o relatório ainda não chegou».
 */
import { eur } from './finance';
import { diaCurto, euros, intervalo, quandoPaga } from './plataformas';

describe('euros', () => {
  test('um valor por saber é um travessão, nunca zero', () => {
    // É por isto que este ficheiro existe: o formatador da casa mente aqui.
    expect(eur(null)).toContain('0,00');
    expect(euros(null)).toBe('—');
    expect(euros(undefined)).toBe('—');
  });

  test('um zero a sério continua a ser zero', () => {
    // Uma semana em que a plataforma diz mesmo «zero» não pode virar «—»:
    // são coisas diferentes, e a diferença é o que este ecrã existe para dizer.
    expect(euros(0)).toContain('0,00');
  });

  test('um valor normal sai em euros portugueses', () => {
    // Sem os espaços: o separador de milhares depende dos dados de ICU do
    // ambiente (o Node dos testes não os tem completos e escreve «1234,56 €», o
    // browser escreve «1 234,56 €»). O que aqui interessa é a vírgula decimal
    // e o símbolo — um ponto decimal seria o descuido a apanhar.
    expect(euros(1234.56).replace(/[\s\xa0\u202f]/g, '')).toBe('1234,56€');
  });
});

describe('diaCurto', () => {
  test('a data ISO vira dia e mês', () => {
    expect(diaCurto('2026-08-24')).toBe('24 ago');
    expect(diaCurto('2026-01-01')).toBe('1 jan');
    expect(diaCurto('2026-12-31')).toBe('31 dez');
  });

  test('o que não é data volta como veio, sem rebentar', () => {
    expect(diaCurto(null)).toBe('');
    expect(diaCurto('')).toBe('');
    expect(diaCurto('2026-13-99')).toBe('2026-13-99');
  });
});

describe('intervalo', () => {
  test('dentro do mesmo mês o mês escreve-se uma vez', () => {
    expect(intervalo('2026-08-24', '2026-08-30')).toBe('24 a 30 ago');
  });

  test('entre dois meses escrevem-se os dois', () => {
    // «31 a 6 set» lê-se como se a semana fosse toda em Setembro.
    expect(intervalo('2026-08-31', '2026-09-06')).toBe('31 ago a 6 set');
  });
});

describe('quandoPaga', () => {
  const hoje = { pagamento: '2026-08-31', dias_para_pagamento: 0 };

  test('na segunda, a Uber e a Bolt já foram pagas', () => {
    expect(quandoPaga(hoje)).toBe('Pago hoje (31 ago)');
  });

  test('sem relatório NÃO se diz «pago» — só a data prevista', () => {
    // A data é do calendário; o valor é desconhecido. «Pago hoje» ao lado de
    // «relatório não recebido» lê-se como se alguma coisa tivesse entrado.
    expect(quandoPaga(hoje, false)).toBe('Pagamento previsto para hoje (31 ago)');
  });

  test('a contagem de dias fala no singular quando é um só', () => {
    expect(quandoPaga({ pagamento: '2026-09-01', dias_para_pagamento: 1 }))
      .toBe('Entra a 1 set · falta 1 dia');
    expect(quandoPaga({ pagamento: '2026-09-05', dias_para_pagamento: 5 }))
      .toBe('Entra a 5 set · faltam 5 dias');
  });

  test('uma data já passada assinala-se em vez de dizer «faltam -3 dias»', () => {
    expect(quandoPaga({ pagamento: '2026-08-28', dias_para_pagamento: -3 }))
      .toBe('Devia ter entrado a 28 ago');
  });

  test('sem período não rebenta', () => {
    expect(quandoPaga(null)).toBe('');
  });
});
