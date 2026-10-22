/**
 * O PAINEL DO PLANEADOR — o que a página `pages/crm/CrmRota.js` (plano F3 T3.38) e o
 * `components/crm/ResumoRota.js` desenham a partir da `vista` do planeador, sem DOM:
 *   - as secções do painel (`seccoesDoPainel`): "Rota" (a única arrastável), "⚠️ Fechadas neste dia" (com
 *     "Manter"), "⚠️ Não cabem no horário" (com "Pôr na rota") e "Lojas apagadas", por esta ordem e só as
 *     que têm paragens;
 *   - os totais do resumo (`totaisDoResumo`): a distância, a condução e o regresso previsto (com o aviso
 *     quando passa do limite), esbatidos quando as horas não são as atuais;
 *   - os botões das ações (`botoesDoResumo`): "Calcular melhor ordem", "Recalcular horas" e "Guardar rota",
 *     cada um desligado com o motivo, e os motivos iguais escritos uma só vez (sem rede, os três dizem o
 *     mesmo); a mensagem do último cálculo só quando não repete um motivo.
 */
import { MENSAGEM_SEM_REDE } from './api';
import {
  MENSAGEM_SEM_CALCULO,
  TEXTO_A_CALCULAR,
  TEXTO_CALCULAR,
  TEXTO_GUARDAR_ROTA,
  TEXTO_HORAS_EM_DIA,
  TEXTO_PRIMEIRA_PARAGEM,
  TEXTO_RECALCULAR,
  acoesDaRota,
} from './planeador';
import {
  ROTULOS_TOTAIS,
  TEXTO_A_RECARREGAR,
  TEXTO_CANCELAR,
  TEXTO_GUARDAR_MESMO_ASSIM,
  TEXTO_GUARDAR_NAO_CABEM,
  TEXTO_RECARREGAR,
  TEXTO_ROTAS,
  TEXTO_TENTAR_DE_NOVO,
  TEXTO_VOLTAR_AS_ROTAS,
  TITULO_ATRIBUICAO_ORS,
  TITULO_BLOCOS_GOOGLE,
  TITULO_PAINEL,
  TITULO_RESUMO,
  TITULOS_SECCOES,
  botoesDoResumo,
  seccoesDoPainel,
  totaisDoResumo,
} from './painelRota';

const linha = (id) => ({ id, numero: null, nome: `Loja ${id}` });

// --- Os textos -----------------------------------------------------------------------------------

test('os textos do painel', () => {
  expect(TITULO_PAINEL).toBe('Painel da rota');
  expect(TITULO_RESUMO).toBe('Resumo da rota');
  expect(TITULO_BLOCOS_GOOGLE).toBe('Navegação no Google Maps');
  expect(TITULO_ATRIBUICAO_ORS).toBe('Cálculo das rotas');
  expect(TEXTO_ROTAS).toBe('Rotas');
  expect(TEXTO_VOLTAR_AS_ROTAS).toBe('Voltar às Rotas');
  expect(TEXTO_TENTAR_DE_NOVO).toBe('Tentar novamente');
  expect(TEXTO_RECARREGAR).toBe('Recarregar');
  expect(TEXTO_A_RECARREGAR).toBe('A recarregar…');
  expect(TEXTO_GUARDAR_MESMO_ASSIM).toBe('Guardar mesmo assim');
  expect(TEXTO_GUARDAR_NAO_CABEM).toBe('As que não cabem ficam no fim da rota, sem hora prevista.');
  expect(TEXTO_CANCELAR).toBe('Cancelar');
});

test('os títulos das secções (o plano: "Rota", "⚠️ Fechadas neste dia" e "⚠️ Não cabem no horário")', () => {
  expect(TITULOS_SECCOES).toEqual({
    rota: 'Rota',
    fechadas: '⚠️ Fechadas neste dia',
    naoCabem: '⚠️ Não cabem no horário',
    semLoja: 'Lojas apagadas',
  });
  expect(Object.isFrozen(TITULOS_SECCOES)).toBe(true);
});

test('os rótulos dos totais', () => {
  expect(ROTULOS_TOTAIS).toEqual({ distancia: 'Distância', duracao: 'Condução', regresso: 'Regresso previsto' });
  expect(Object.isFrozen(ROTULOS_TOTAIS)).toBe(true);
});

// --- As secções ----------------------------------------------------------------------------------

describe('seccoesDoPainel', () => {
  test('as quatro secções por esta ordem, cada uma com o título e o que se pode fazer nela', () => {
    const seccoes = {
      semLoja: [linha('f')],
      naoCabem: [linha('d')],
      fechadas: [linha('b')],
      rota: [linha('a'), linha('c')],
    };
    expect(seccoesDoPainel(seccoes)).toEqual([
      { chave: 'rota', titulo: 'Rota', linhas: seccoes.rota, arrastavel: true, comManter: false, comPorNaRota: false },
      { chave: 'fechadas', titulo: '⚠️ Fechadas neste dia', linhas: seccoes.fechadas, arrastavel: false, comManter: true, comPorNaRota: false },
      { chave: 'naoCabem', titulo: '⚠️ Não cabem no horário', linhas: seccoes.naoCabem, arrastavel: false, comManter: false, comPorNaRota: true },
      { chave: 'semLoja', titulo: 'Lojas apagadas', linhas: seccoes.semLoja, arrastavel: false, comManter: false, comPorNaRota: false },
    ]);
  });

  test('as linhas são as da vista (a mesma lista: a ListaParagens não vê uma lista nova sem razão)', () => {
    const seccoes = { rota: [linha('a')], fechadas: [linha('b')], naoCabem: [], semLoja: [] };
    const [rota, fechadas] = seccoesDoPainel(seccoes);
    expect(rota.linhas).toBe(seccoes.rota);
    expect(fechadas.linhas).toBe(seccoes.fechadas);
  });

  test('só as secções com paragens (uma rota sem paragens não tem nenhuma)', () => {
    expect(seccoesDoPainel({ rota: [], fechadas: [linha('b')], naoCabem: [], semLoja: [] }).map((s) => s.chave)).toEqual(['fechadas']);
    expect(seccoesDoPainel({ rota: [linha('a')], fechadas: [], naoCabem: [linha('d')], semLoja: [] }).map((s) => s.chave)).toEqual(['rota', 'naoCabem']);
    expect(seccoesDoPainel({ rota: [], fechadas: [], naoCabem: [], semLoja: [linha('f')] }).map((s) => s.chave)).toEqual(['semLoja']);
    expect(seccoesDoPainel({ rota: [], fechadas: [], naoCabem: [], semLoja: [] })).toEqual([]);
  });

  test('uma secção em falta ou que não é uma lista fica de fora; sem secções (a carregar, falha), nenhuma', () => {
    expect(seccoesDoPainel({ rota: [linha('a')] }).map((s) => s.chave)).toEqual(['rota']);
    expect(seccoesDoPainel({ rota: 'a', fechadas: { 0: linha('b') }, naoCabem: null, semLoja: [linha('f')] }).map((s) => s.chave)).toEqual(['semLoja']);
    expect(seccoesDoPainel(null)).toEqual([]);
    expect(seccoesDoPainel(undefined)).toEqual([]);
    expect(seccoesDoPainel('rota')).toEqual([]);
    expect(seccoesDoPainel([[linha('a')]])).toEqual([]);
  });

  test('uma chave que não é uma secção não entra', () => {
    expect(seccoesDoPainel({ rota: [linha('a')], outra: [linha('x')] }).map((s) => s.chave)).toEqual(['rota']);
  });

  test('a lista e cada secção vêm congeladas', () => {
    const lista = seccoesDoPainel({ rota: [linha('a')], fechadas: [], naoCabem: [], semLoja: [] });
    expect(Object.isFrozen(lista)).toBe(true);
    expect(Object.isFrozen(lista[0])).toBe(true);
  });
});

// --- Os totais -----------------------------------------------------------------------------------

describe('totaisDoResumo', () => {
  const TOTAIS = Object.freeze({ distancia: '12,3 km', duracao: '45 min', regresso: '18:40', regressoTarde: false, atual: true });

  test('a distância, a condução e o regresso previsto, com as horas atuais', () => {
    expect(totaisDoResumo(TOTAIS)).toEqual({
      itens: [
        { chave: 'distancia', rotulo: 'Distância', valor: '12,3 km', aviso: false },
        { chave: 'duracao', rotulo: 'Condução', valor: '45 min', aviso: false },
        { chave: 'regresso', rotulo: 'Regresso previsto', valor: '18:40', aviso: false },
      ],
      antigos: false,
    });
  });

  test('o regresso depois do limite leva o aviso (só ele)', () => {
    const { itens } = totaisDoResumo({ ...TOTAIS, regressoTarde: true });
    expect(itens.map((i) => i.aviso)).toEqual([false, false, true]);
  });

  test('só um regressoTarde verdadeiro avisa', () => {
    for (const regressoTarde of [1, 'true', null, undefined]) {
      expect(totaisDoResumo({ ...TOTAIS, regressoTarde }).itens[2].aviso).toBe(false);
    }
  });

  test('com as horas que não são as atuais (ou sem o sinal), os totais ficam antigos', () => {
    expect(totaisDoResumo({ ...TOTAIS, atual: false }).antigos).toBe(true);
    expect(totaisDoResumo({ ...TOTAIS, atual: 'true' }).antigos).toBe(true);
    const { atual, ...semSinal } = TOTAIS;
    expect(totaisDoResumo(semSinal).antigos).toBe(true);
  });

  test('o que falta (ou não é texto) fica de fora; sem nada, nenhum total', () => {
    expect(totaisDoResumo({ ...TOTAIS, duracao: null }).itens.map((i) => i.chave)).toEqual(['distancia', 'regresso']);
    expect(totaisDoResumo({ ...TOTAIS, distancia: null, regresso: null }).itens.map((i) => i.chave)).toEqual(['duracao']);
    expect(totaisDoResumo({ ...TOTAIS, distancia: '', regresso: 1840 }).itens.map((i) => i.chave)).toEqual(['duracao']);
    expect(totaisDoResumo({ ...TOTAIS, distancia: null, duracao: null, regresso: null })).toBeNull();
  });

  test('sem totais (sem cálculo, ou estragados), null', () => {
    expect(totaisDoResumo(null)).toBeNull();
    expect(totaisDoResumo(undefined)).toBeNull();
    expect(totaisDoResumo('12 km')).toBeNull();
    expect(totaisDoResumo([TOTAIS])).toBeNull();
  });

  test('vem congelado', () => {
    const totais = totaisDoResumo(TOTAIS);
    expect(Object.isFrozen(totais)).toBe(true);
    expect(Object.isFrozen(totais.itens)).toBe(true);
    expect(Object.isFrozen(totais.itens[0])).toBe(true);
  });
});

// --- Os botões das ações -------------------------------------------------------------------------

describe('botoesDoResumo', () => {
  const ativo = (texto) => ({ texto, ativo: true, falta: null });
  const desligado = (texto, falta) => ({ texto, ativo: false, falta });
  const ACOES_ATIVAS = Object.freeze({
    calcular: ativo(TEXTO_CALCULAR),
    recalcular: ativo(TEXTO_RECALCULAR),
    guardar: { ...ativo(TEXTO_GUARDAR_ROTA), pergunta: null },
  });

  test('os três botões por esta ordem, ligados e sem motivos', () => {
    expect(botoesDoResumo(ACOES_ATIVAS, { aCalcular: false, mensagem: null })).toEqual({
      botoes: [
        { chave: 'calcular', texto: 'Calcular melhor ordem', ativo: true, motivo: null },
        { chave: 'recalcular', texto: 'Recalcular horas', ativo: true, motivo: null },
        { chave: 'guardar', texto: 'Guardar rota', ativo: true, motivo: null },
      ],
      motivos: [],
      mensagem: null,
    });
  });

  test('os motivos iguais escrevem-se uma vez: sem rede, os três apontam para o mesmo', () => {
    const acoes = {
      calcular: desligado(TEXTO_CALCULAR, MENSAGEM_SEM_REDE),
      recalcular: desligado(TEXTO_RECALCULAR, MENSAGEM_SEM_REDE),
      guardar: desligado(TEXTO_GUARDAR_ROTA, MENSAGEM_SEM_REDE),
    };
    const { botoes, motivos } = botoesDoResumo(acoes, null);
    expect(motivos).toEqual([MENSAGEM_SEM_REDE]);
    expect(botoes.map((b) => [b.ativo, b.motivo])).toEqual([[false, 0], [false, 0], [false, 0]]);
  });

  test('cada motivo diferente tem o seu lugar, pela ordem dos botões', () => {
    const acoes = {
      calcular: desligado(TEXTO_CALCULAR, MENSAGEM_SEM_CALCULO),
      recalcular: desligado(TEXTO_RECALCULAR, TEXTO_HORAS_EM_DIA),
      guardar: desligado(TEXTO_GUARDAR_ROTA, MENSAGEM_SEM_CALCULO),
    };
    const { botoes, motivos } = botoesDoResumo(acoes, null);
    expect(motivos).toEqual([MENSAGEM_SEM_CALCULO, TEXTO_HORAS_EM_DIA]);
    expect(botoes.map((b) => b.motivo)).toEqual([0, 1, 0]);
  });

  test('um botão com o pedido a correr ("A calcular…") está desligado sem motivo', () => {
    const acoes = { ...ACOES_ATIVAS, calcular: { texto: TEXTO_A_CALCULAR, ativo: false, falta: null } };
    const { botoes, motivos } = botoesDoResumo(acoes, null);
    expect(botoes[0]).toEqual({ chave: 'calcular', texto: 'A calcular…', ativo: false, motivo: null });
    expect(motivos).toEqual([]);
  });

  test('um botão ligado não tem motivo, mesmo que traga uma falta; uma falta vazia ou que não é texto não conta', () => {
    const acoes = {
      calcular: { texto: TEXTO_CALCULAR, ativo: true, falta: 'não devia vir' },
      recalcular: desligado(TEXTO_RECALCULAR, ''),
      guardar: desligado(TEXTO_GUARDAR_ROTA, 42),
    };
    const { botoes, motivos } = botoesDoResumo(acoes, null);
    expect(botoes.map((b) => [b.ativo, b.motivo])).toEqual([[true, null], [false, null], [false, null]]);
    expect(motivos).toEqual([]);
  });

  test('só um ativo verdadeiro liga o botão', () => {
    const acoes = { ...ACOES_ATIVAS, guardar: { texto: TEXTO_GUARDAR_ROTA, ativo: 'sim', falta: null } };
    expect(botoesDoResumo(acoes, null).botoes[2].ativo).toBe(false);
  });

  test('a mensagem do último cálculo aparece quando não repete um motivo', () => {
    const limite = 'Cálculo automático indisponível por agora (limite de pedidos) — espere um minuto ou ordene à mão';
    expect(botoesDoResumo(ACOES_ATIVAS, { aCalcular: false, mensagem: limite }).mensagem).toBe(limite);
    const semChave = {
      calcular: desligado(TEXTO_CALCULAR, MENSAGEM_SEM_CALCULO),
      recalcular: desligado(TEXTO_RECALCULAR, MENSAGEM_SEM_CALCULO),
      guardar: ativo(TEXTO_GUARDAR_ROTA),
    };
    expect(botoesDoResumo(semChave, { aCalcular: false, mensagem: MENSAGEM_SEM_CALCULO }).mensagem).toBeNull();
    expect(botoesDoResumo(ACOES_ATIVAS, { aCalcular: false, mensagem: '' }).mensagem).toBeNull();
    expect(botoesDoResumo(ACOES_ATIVAS, { aCalcular: false, mensagem: 503 }).mensagem).toBeNull();
    expect(botoesDoResumo(ACOES_ATIVAS, undefined).mensagem).toBeNull();
  });

  test('com as ações do planeador: sem chave, o "indisponível" uma só vez e o "Guardar" ligado', () => {
    const rota = {
      existe: true,
      estado: 'rascunho',
      editavel: true,
      calculo_disponivel: false,
      calculo: null,
      paragens: [{ id: 'p1', seccao: 'rota' }],
    };
    const acoes = acoesDaRota(rota, { online: true });
    const resumo = botoesDoResumo(acoes, { aCalcular: false, mensagem: MENSAGEM_SEM_CALCULO });
    expect(resumo.motivos).toEqual([MENSAGEM_SEM_CALCULO]);
    expect(resumo.botoes.map((b) => [b.chave, b.ativo, b.motivo])).toEqual([
      ['calcular', false, 0],
      ['recalcular', false, 0],
      ['guardar', true, null],
    ]);
    expect(resumo.mensagem).toBeNull();
  });

  test('com as ações do planeador numa rota sem paragens: "Adicione a primeira paragem pelo mapa." uma só vez', () => {
    const rota = { existe: false, estado: null, editavel: true, calculo_disponivel: true, calculo: null, paragens: [] };
    const resumo = botoesDoResumo(acoesDaRota(rota, { online: true }), { aCalcular: false, mensagem: null });
    expect(resumo.motivos).toEqual([TEXTO_PRIMEIRA_PARAGEM]);
    expect(resumo.botoes.map((b) => b.motivo)).toEqual([0, 0, 0]);
  });

  test('um botão em falta (ou que não é um objeto) não aparece', () => {
    const { calcular, recalcular } = ACOES_ATIVAS;
    expect(botoesDoResumo({ calcular, recalcular }, null).botoes.map((b) => b.chave)).toEqual(['calcular', 'recalcular']);
    expect(botoesDoResumo({ calcular: 'x', recalcular, guardar: null }, null).botoes.map((b) => b.chave)).toEqual(['recalcular']);
  });

  test('sem ações (só de leitura, a carregar, falha), null', () => {
    expect(botoesDoResumo(null, null)).toBeNull();
    expect(botoesDoResumo(undefined, { mensagem: 'x' })).toBeNull();
    expect(botoesDoResumo('acoes', null)).toBeNull();
  });

  test('vem congelado', () => {
    const resumo = botoesDoResumo(ACOES_ATIVAS, null);
    expect(Object.isFrozen(resumo)).toBe(true);
    expect(Object.isFrozen(resumo.botoes)).toBe(true);
    expect(Object.isFrozen(resumo.botoes[0])).toBe(true);
    expect(Object.isFrozen(resumo.motivos)).toBe(true);
  });
});
