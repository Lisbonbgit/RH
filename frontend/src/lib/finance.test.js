import { CATEGORIAS_PADRAO, categoriasDaEmpresa, categoriaLabel } from './finance';

describe('categorias do Financeiro', () => {
  test('a lista por omissão tem as categorias do Excel da diretora financeira', () => {
    const ids = CATEGORIAS_PADRAO.map((c) => c.id);
    expect(ids).toContain('entradas');
    expect(ids).toContain('fornecedor');
    expect(ids).toContain('utilitarios');
    // As duas que só existem no sistema não podem desaparecer, senão as
    // faturas já gravadas com elas ficam órfãs.
    expect(ids).toContain('rendas');
    expect(ids).toContain('outros');
  });

  test('uma empresa sem lista própria usa a lista por omissão', () => {
    expect(categoriasDaEmpresa({ id: 'e1' })).toBe(CATEGORIAS_PADRAO);
    expect(categoriasDaEmpresa({ id: 'e1', categorias: [] })).toBe(CATEGORIAS_PADRAO);
    expect(categoriasDaEmpresa(null)).toBe(CATEGORIAS_PADRAO);
  });

  test('uma empresa com lista própria manda nela', () => {
    const minhas = [{ id: 'gelo', label: 'Gelo' }];
    expect(categoriasDaEmpresa({ id: 'e1', categorias: minhas })).toBe(minhas);
  });

  test('uma categoria desconhecida mostra a chave crua, não desaparece', () => {
    // Uma fatura antiga com "mercadoria" tem de continuar a mostrar alguma
    // coisa no ecrã enquanto a migração não corre.
    expect(categoriaLabel(CATEGORIAS_PADRAO, 'mercadoria')).toBe('mercadoria');
    expect(categoriaLabel(CATEGORIAS_PADRAO, 'fornecedor')).toBe('Fornecedor');
    expect(categoriaLabel(CATEGORIAS_PADRAO, null)).toBe('');
  });
});
