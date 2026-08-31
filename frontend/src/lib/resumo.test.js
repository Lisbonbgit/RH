/**
 * AS DECISÕES DO ECRÃ RESUMO — corridas de verdade, não lidas.
 *
 * A promessa que este ficheiro guarda é uma só: quando um bloco não tem dados,
 * o cartão NÃO produz números. `eur(null)` devolve «0,00 €», e um «0,00 €» num
 * telemóvel lê-se como «a empresa não vendeu nada», não como «não tens acesso».
 *
 * O que isto NÃO prova: que o JSX desenha só `linhas`. Isso vê-se com a app
 * aberta contra o servidor a sério.
 */
import { eur } from './finance';
import {
  pede, estadoDoBloco, rotaDeAterragem,
  cartaoVendas, cartaoFinanceiro, cartaoRh, cartaoEstoque,
  OK, SEM_ACESSO, INDISPONIVEL, MSG_SEM_ACESSO, MSG_INDISPONIVEL, MSG_SEM_LOJAS,
} from './resumo';

const negado = { ok: false, status: 403 };
const rebentou = { ok: false, status: 500 };

describe('estadoDoBloco', () => {
  test('403 é falta de acesso, não avaria', () => {
    expect(estadoDoBloco(negado)).toBe(SEM_ACESSO);
  });
  test('qualquer outra falha é avaria', () => {
    expect(estadoDoBloco(rebentou)).toBe(INDISPONIVEL);
    expect(estadoDoBloco({ ok: false, status: null })).toBe(INDISPONIVEL);
  });
  test('com dados, está ok', () => {
    expect(estadoDoBloco({ ok: true, data: {} })).toBe(OK);
  });
});

describe('pede', () => {
  test('embrulha a resposta', async () => {
    expect(await pede(async () => ({ data: { a: 1 } }))).toEqual({ ok: true, data: { a: 1 } });
  });
  test('apanha o 403 do axios sem deixar rebentar o ecrã', async () => {
    const erro = Object.assign(new Error('nope'), { response: { status: 403 } });
    expect(await pede(async () => { throw erro; })).toEqual({ ok: false, status: 403 });
  });
  test('um erro sem resposta (rede em baixo) não tem estado', async () => {
    expect(await pede(async () => { throw new Error('offline'); })).toEqual({ ok: false, status: null });
  });
});

describe('cartões sem acesso', () => {
  // A razão de existir de tudo isto.
  test.each([
    ['vendas', cartaoVendas], ['financeiro', cartaoFinanceiro],
    ['rh', cartaoRh], ['estoque', cartaoEstoque],
  ])('%s com 403 diz «Sem acesso» e NÃO traz linhas', (_nome, cartao) => {
    const c = cartao(negado);
    expect(c.estado).toBe(SEM_ACESSO);
    expect(c.mensagem).toBe(MSG_SEM_ACESSO);
    expect(c.linhas).toEqual([]);
  });

  test.each([
    ['vendas', cartaoVendas], ['financeiro', cartaoFinanceiro],
    ['rh', cartaoRh], ['estoque', cartaoEstoque],
  ])('%s avariado diz «Indisponível» e NÃO traz linhas', (_nome, cartao) => {
    const c = cartao(rebentou);
    expect(c.estado).toBe(INDISPONIVEL);
    expect(c.mensagem).toBe(MSG_INDISPONIVEL);
    expect(c.linhas).toEqual([]);
  });
});

describe('cartaoFinanceiro', () => {
  const resposta = { ok: true, data: { financeiro: {
    a_pagar: 1234.5, vencidas: 2, pago: 800, saldo_banco: 5000,
  } } };

  test('mostra os quatro números em euros', () => {
    const c = cartaoFinanceiro(resposta);
    expect(c.estado).toBe(OK);
    expect(c.linhas.map((l) => l.rotulo)).toEqual(['A pagar', 'Vencidas', 'Pago no mês', 'Saldo do banco']);
    // Comparar com `eur` e nunca com um literal: em pt-PT o separador de
    // milhares é um espaço INSEPARÁVEL (U+00A0). Um literal escrito à mão com
    // um espaço normal nunca casa — e um `expect(...).not` sobre ele fica
    // verde por engano, que é a pior espécie de teste.
    expect(c.linhas[0].valor).toBe(eur(1234.5));
  });

  test('faturas vencidas acendem o alerta; zero vencidas não', () => {
    expect(cartaoFinanceiro(resposta).linhas[1].alerta).toBe(true);
    const zero = { ok: true, data: { financeiro: { ...resposta.data.financeiro, vencidas: 0 } } };
    expect(cartaoFinanceiro(zero).linhas[1].alerta).toBe(false);
  });

  test('um campo em falta some do cartão — não vira «0,00 €»', () => {
    const semSaldo = { ok: true, data: { financeiro: { a_pagar: 10, vencidas: 0, pago: 5 } } };
    const rotulos = cartaoFinanceiro(semSaldo).linhas.map((l) => l.rotulo);
    expect(rotulos).not.toContain('Saldo do banco');
    expect(cartaoFinanceiro(semSaldo).linhas.some((l) => l.valor === eur(0))).toBe(false);
  });

  // Uma string vazia não é zero: `Number('')` é 0 e é finito, e era por aí
  // que um campo em falta chegado do servidor como '' (em vez de null) se
  // transformava num «0,00 €» com ar de dado real.
  test.each([
    ['string vazia', ''],
    ['só espaços', '   '],
    ['null', null],
    ['undefined', undefined],
    ['NaN', NaN],
    ['true', true],
    ['array vazio', []],
  ])('a_pagar = %s não é um número real — a linha «A pagar» some', (_nome, valor) => {
    const r = { ok: true, data: { financeiro: { a_pagar: valor, vencidas: 0, pago: 0, saldo_banco: 0 } } };
    expect(cartaoFinanceiro(r).linhas.map((l) => l.rotulo)).not.toContain('A pagar');
  });

  test.each([
    ['zero verdadeiro', 0],
    ['string numérica', '12'],
  ])('a_pagar = %s é um número real — a linha «A pagar» fica', (_nome, valor) => {
    const r = { ok: true, data: { financeiro: { a_pagar: valor, vencidas: 0, pago: 0, saldo_banco: 0 } } };
    expect(cartaoFinanceiro(r).linhas.map((l) => l.rotulo)).toContain('A pagar');
  });
});

describe('cartaoVendas', () => {
  const resposta = { ok: true, data: { ha_vendas: true, cartoes: {
    hoje: { valor: 300, valor_comparado: 200, variacao: 50 },
    mensal: { valor: 9000, valor_comparado: 8000, variacao: 12.5 },
  } } };

  test('traz hoje e o mês, cada um com a sua variação', () => {
    const c = cartaoVendas(resposta);
    expect(c.linhas.map((l) => l.rotulo)).toEqual(['Hoje', 'Mês atual']);
    expect(c.linhas[0].variacao).toBe(50);
  });

  test('sem variação comparável, não inventa uma seta', () => {
    const sem = { ok: true, data: { ha_vendas: true, cartoes: {
      hoje: { valor: 300, valor_comparado: 0, variacao: null },
    } } };
    expect(cartaoVendas(sem).linhas[0].variacao).toBeNull();
  });

  test('um negócio que nunca vendeu diz isso, em vez de mostrar zeros', () => {
    const nunca = { ok: true, data: { ha_vendas: false, cartoes: {} } };
    const c = cartaoVendas(nunca);
    expect(c.linhas).toEqual([]);
    expect(c.mensagem).toBe('Ainda não há vendas');
  });

  test('«hoje» sem valor some — não produz a linha «Hoje»', () => {
    const semHoje = { ok: true, data: { ha_vendas: true, cartoes: {
      hoje: { valor: null, valor_comparado: 200, variacao: null },
      mensal: { valor: 9000, valor_comparado: 8000, variacao: 12.5 },
    } } };
    const c = cartaoVendas(semHoje);
    expect(c.linhas.map((l) => l.rotulo)).toEqual(['Mês atual']);
  });
});

describe('cartaoRh', () => {
  // O RH vem de /dashboard/admin, que é guardado por PAPEL
  // (admin_manager_required). Não vem do painel do Financeiro, que é guardado
  // por PERTENÇA à empresa. É essa separação que faz o RH sobreviver a um 403
  // no Financeiro — o caso de um administrador que não é membro de empresa
  // nenhuma lá dentro.
  test('lê os quatro números do painel de RH', () => {
    const r = { ok: true, data: {
      total_employees: 12, working_now: 2, on_leave_today: 1, pending_requests: 3,
    } };
    const c = cartaoRh(r);
    expect(c.linhas.map((l) => [l.rotulo, l.valor])).toEqual([
      ['Colaboradores', '12'], ['Ao serviço agora', '2'],
      ['De férias hoje', '1'], ['Ausências por aprovar', '3'],
    ]);
    expect(c.linhas[3].alerta).toBe(true);
  });

  test('um ZERO verdadeiro desenha-se; só o que falta é que desaparece', () => {
    const c = cartaoRh({ ok: true, data: {
      total_employees: 12, working_now: 0, on_leave_today: 0, pending_requests: 0,
    } });
    expect(c.linhas[1].valor).toBe('0');
    expect(c.linhas[3].alerta).toBe(false);
    // `total_employees` em falta é outra coisa: some.
    const semTotal = cartaoRh({ ok: true, data: { working_now: 0 } });
    expect(semTotal.linhas.map((l) => l.rotulo)).toEqual(['Ao serviço agora']);
  });
});

describe('cartaoEstoque', () => {
  test('soma o que falta e nomeia só as lojas com falta', () => {
    const r = { ok: true, data: [
      { unidade_id: '1', nome: 'Belém', abaixo_minimo: 4 },
      { unidade_id: '2', nome: 'Oeiras', abaixo_minimo: 0 },
    ] };
    const c = cartaoEstoque(r);
    expect(c.linhas[0]).toMatchObject({ rotulo: 'Artigos abaixo do mínimo', valor: '4', alerta: true });
    expect(c.linhas.slice(1).map((l) => l.rotulo)).toEqual(['Belém']);
  });

  test('com tudo em ordem, diz que está tudo em ordem', () => {
    const r = { ok: true, data: [{ unidade_id: '1', nome: 'Belém', abaixo_minimo: 0 }] };
    const c = cartaoEstoque(r);
    expect(c.linhas[0].alerta).toBe(false);
    expect(c.linhas).toHaveLength(1);
  });

  // Um 200 sem lojas nenhuma não pode desenhar «0»: isso lê-se como «está
  // tudo em ordem» quando pode ser «não veio nada».
  test('res.data que não é array é avaria — sem linhas, sem «0» a fingir de dado', () => {
    const c = cartaoEstoque({ ok: true, data: null });
    expect(c.estado).toBe(OK);
    expect(c.linhas).toEqual([]);
    expect(c.mensagem).toBe(MSG_INDISPONIVEL);
  });

  test('array vazio é «sem lojas configuradas», não «zero em falta»', () => {
    const c = cartaoEstoque({ ok: true, data: [] });
    expect(c.estado).toBe(OK);
    expect(c.linhas).toEqual([]);
    expect(c.mensagem).toBe(MSG_SEM_LOJAS);
  });
});

describe('rotaDeAterragem', () => {
  test('na APP, um gestor aterra no Resumo', () => {
    expect(rotaDeAterragem({ nativo: true, papel: 'admin' })).toBe('/admin/resumo');
  });
  test('no browser, um gestor aterra onde sempre aterrou', () => {
    expect(rotaDeAterragem({ nativo: false, papel: 'admin' })).toBe('/admin');
  });
  test('um colaborador vai para o lado dele, app ou não', () => {
    expect(rotaDeAterragem({ nativo: true, papel: 'colaborador' })).toBe('/colaborador');
    expect(rotaDeAterragem({ nativo: false, papel: 'colaborador' })).toBe('/colaborador');
  });

  // Os outros dois papéis de gestão — um erro de transcrição em
  // PAPEIS_DE_GESTAO não pode passar despercebido só por só testarmos 'admin'.
  test.each(['gerente', 'contabilista'])(
    'na APP, um %s (também de gestão) aterra no Resumo',
    (papel) => {
      expect(rotaDeAterragem({ nativo: true, papel })).toBe('/admin/resumo');
    },
  );
});
