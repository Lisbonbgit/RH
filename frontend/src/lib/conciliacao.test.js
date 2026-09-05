import {
  descricaoDoMovimento, resumoPorCategoria,
  percentagensSobreEntradas, plataformasDasEntradas,
} from './conciliacao';

const CATS = [
  { id: 'entradas', label: 'Entradas' },
  { id: 'fornecedor', label: 'Fornecedor' },
  { id: 'supermercado', label: 'Supermercado' },
  { id: 'salarios', label: 'Salários' },
];

describe('descrição do movimento', () => {
  test('o que a diretora financeira escreveu ganha ao texto do banco', () => {
    expect(descricaoDoMovimento({ title: 'MAKRO', description: 'COMPRA 4512 MAKRO CASH' })).toBe('MAKRO');
  });
  test('sem reescrita, fica o texto do banco', () => {
    expect(descricaoDoMovimento({ description: 'COMPRA 4512' })).toBe('COMPRA 4512');
  });
  test('sem nada, não fica em branco', () => {
    expect(descricaoDoMovimento({})).toBe('(sem descrição)');
  });
});

describe('resumo por categoria', () => {
  const MOVS = [
    { category: 'entradas', amount: 3633.0 },
    { category: 'entradas', amount: 2460.92 },
    { category: 'fornecedor', amount: -2268.91 },
    { category: 'supermercado', amount: -65.8 },
  ];

  test('soma por categoria e guarda o SINAL', () => {
    const linhas = resumoPorCategoria(MOVS, CATS);
    const porId = Object.fromEntries(linhas.map((l) => [l.id, l.total]));
    expect(porId.entradas).toBeCloseTo(6093.92, 2);
    expect(porId.fornecedor).toBeCloseTo(-2268.91, 2);
  });

  test('uma categoria sem movimentos aparece a zero, como no Excel', () => {
    const linhas = resumoPorCategoria(MOVS, CATS);
    expect(linhas.find((l) => l.id === 'salarios').total).toBe(0);
  });

  test('a ordem é a da lista da empresa', () => {
    expect(resumoPorCategoria(MOVS, CATS).slice(0, 4).map((l) => l.id))
      .toEqual(['entradas', 'fornecedor', 'supermercado', 'salarios']);
  });

  test('o que está por classificar não desaparece nem se cala', () => {
    const linhas = resumoPorCategoria([{ amount: -10 }], CATS);
    const sem = linhas.find((l) => l.id === 'sem_categoria');
    expect(sem.total).toBe(-10);
    expect(sem.label).toBe('Sem categoria');
  });

  test('uma categoria legada fora da lista aparece com a chave crua', () => {
    const linhas = resumoPorCategoria([{ category: 'mercadoria', amount: -5 }], CATS);
    expect(linhas.find((l) => l.id === 'mercadoria').total).toBe(-5);
  });
});

describe('percentagens sobre as entradas', () => {
  test('cada categoria a dividir pelas entradas, em valor absoluto', () => {
    const linhas = resumoPorCategoria([
      { category: 'entradas', amount: 7630.69 },
      { category: 'supermercado', amount: -135.84 },
    ], CATS);
    const pcts = percentagensSobreEntradas(linhas);
    expect(pcts.find((p) => p.id === 'supermercado').pct).toBeCloseTo(1.78, 2);
  });

  test('as entradas não aparecem a dividir-se por si próprias', () => {
    const linhas = resumoPorCategoria([{ category: 'entradas', amount: 100 }], CATS);
    expect(percentagensSobreEntradas(linhas).find((p) => p.id === 'entradas')).toBeUndefined();
  });

  test('sem entradas, a percentagem é desconhecida — não é zero', () => {
    const linhas = resumoPorCategoria([{ category: 'supermercado', amount: -50 }], CATS);
    expect(percentagensSobreEntradas(linhas).find((p) => p.id === 'supermercado').pct).toBeNull();
  });
});

describe('plataformas', () => {
  test('agrupa as entradas pela descrição e ordena pela maior', () => {
    const plats = plataformasDasEntradas([
      { category: 'entradas', title: 'Glovo', amount: 3633.0 },
      { category: 'entradas', title: 'Fecho TPA Teya', amount: 2460.92 },
      { category: 'entradas', title: 'Glovo', amount: 100.0 },
      { category: 'fornecedor', title: 'Glovo', amount: -50.0 },
    ]);
    expect(plats).toEqual([
      { nome: 'Glovo', total: 3733.0 },
      { nome: 'Fecho TPA Teya', total: 2460.92 },
    ]);
  });
});
