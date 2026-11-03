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
 *     mesmo); a mensagem do último cálculo só quando não repete um motivo;
 *   - (T3.39) as definições do dia (`definicoesDoPainel`): as duas horas, o início e o fim ("Fábrica" ou
 *     "Ponto no mapa", e qual está à espera do toque), "Evitar portagens" e o resumo de uma linha;
 *   - a faixa do "Ponto no mapa" (`faixaDoPonto`): "Toque no mapa no ponto de início/fim", com "Cancelar";
 *   - as sugestões (`sugestoesDoPainel`): os grupos, cada loja com a distância e o botão "Adicionar" ("A
 *     adicionar…" com o pedido a correr; desligado quando a rota não aceita mais);
 *   - o cartão pequeno de uma loja esbatida tocada no mapa (`cartaoDaLoja`): o nome, a fase, o motivo e
 *     "Adicionar à rota".
 */
import { MENSAGEM_SEM_REDE } from './api';
import {
  MENSAGEM_SEM_CALCULO,
  TEXTOS_ESCOLHER_PONTO,
  TEXTO_A_ADICIONAR,
  TEXTO_A_CALCULAR,
  TEXTO_CALCULAR,
  TEXTO_DEFINICOES_SEM_ROTA,
  TEXTO_FABRICA,
  TEXTO_GUARDAR_ROTA,
  TEXTO_HORAS_EM_DIA,
  TEXTO_PONTO_NO_MAPA,
  TEXTO_PRIMEIRA_PARAGEM,
  TEXTO_RECALCULAR,
  TEXTO_SUGESTOES_A_CARREGAR,
  TEXTO_SUGESTOES_NENHUMA,
  acoesDaRota,
  vistaDasSugestoes,
} from './planeador';
import {
  ROTULOS_HORAS,
  ROTULOS_PONTAS,
  ROTULOS_TOTAIS,
  TEXTO_ADICIONAR,
  TEXTO_ADICIONAR_A_ROTA,
  TEXTO_EVITAR_PORTAGENS,
  TEXTO_FECHADA_MANTIDA,
  TEXTO_FECHAR,
  TEXTO_NOTA_PORTAGENS,
  TEXTO_SEM_MAPA_PONTO,
  TITULO_DEFINICOES,
  TITULO_SUGESTOES,
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
  cartaoDaLoja,
  definicoesDoPainel,
  enquadramentoDoMapa,
  textoDaChegada,
  faixaDoPonto,
  seccoesDoPainel,
  sugestoesDoPainel,
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

// --- As definições do dia (T3.39) ----------------------------------------------------------------

test('os textos das definições do dia, das sugestões e do cartão', () => {
  expect(TITULO_DEFINICOES).toBe('Definições do dia');
  expect(ROTULOS_HORAS).toEqual({ hora_saida: 'Hora de saída', hora_regresso_limite: 'Hora limite de regresso' });
  expect(Object.isFrozen(ROTULOS_HORAS)).toBe(true);
  expect(ROTULOS_PONTAS).toEqual({ inicio: 'Início', fim: 'Fim' });
  expect(Object.isFrozen(ROTULOS_PONTAS)).toBe(true);
  expect(TEXTO_EVITAR_PORTAGENS).toBe('Evitar portagens');
  // O desenho original §7.2: a otimização não evita portagens; as horas (e a linha) vêm do Directions, que sim.
  expect(TEXTO_NOTA_PORTAGENS).toBe('A melhor ordem escolhe-se com portagens; as horas e a linha evitam-nas.');
  expect(TITULO_SUGESTOES).toBe('Sugestões perto da rota');
  expect(TEXTO_ADICIONAR).toBe('Adicionar');
  expect(TEXTO_ADICIONAR_A_ROTA).toBe('Adicionar à rota');
  expect(TEXTO_FECHAR).toBe('Fechar');
});

describe('definicoesDoPainel', () => {
  const FABRICA = Object.freeze({ lat: 38.75, lng: -9.2, fabrica: true, texto: 'Fábrica' });
  const PONTO = Object.freeze({ lat: 39.1, lng: -8.5, fabrica: false, texto: 'Ponto no mapa' });
  const definicoes = (extra = {}) => ({
    hora_saida: '08:00',
    hora_regresso_limite: '19:00',
    inicio: FABRICA,
    fim: FABRICA,
    evitar_portagens: false,
    ativas: true,
    mensagem: null,
    ...extra,
  });

  test('as horas, as pontas, as portagens e o resumo de uma rota com início e fim na fábrica', () => {
    expect(definicoesDoPainel(definicoes(), null)).toEqual({
      resumo: 'Saída 08:00 · Regresso até 19:00 · Início e fim: Fábrica',
      horas: [
        { chave: 'hora_saida', rotulo: 'Hora de saída', valor: '08:00' },
        { chave: 'hora_regresso_limite', rotulo: 'Hora limite de regresso', valor: '19:00' },
      ],
      pontas: [
        { chave: 'inicio', rotulo: 'Início', texto: 'Fábrica', fabrica: true, noMapa: false, aEscolher: false },
        { chave: 'fim', rotulo: 'Fim', texto: 'Fábrica', fabrica: true, noMapa: false, aEscolher: false },
      ],
      evitarPortagens: false,
      ativas: true,
      mensagem: null,
      pontoNoMapa: { ativo: true, falta: null },
    });
  });

  test('um ponto no mapa e pontas diferentes: cada uma no resumo; "Sem portagens" no fim', () => {
    const painel = definicoesDoPainel(definicoes({ fim: PONTO, evitar_portagens: true }), null);
    expect(painel.resumo).toBe('Saída 08:00 · Regresso até 19:00 · Início: Fábrica · Fim: Ponto no mapa · Sem portagens');
    expect(painel.pontas[1]).toEqual({ chave: 'fim', rotulo: 'Fim', texto: 'Ponto no mapa', fabrica: false, noMapa: true, aEscolher: false });
    expect(painel.evitarPortagens).toBe(true);
  });

  test('os dois num ponto no mapa (o mesmo texto) juntam-se no resumo', () => {
    const painel = definicoesDoPainel(definicoes({ inicio: PONTO, fim: PONTO }), null);
    expect(painel.resumo).toBe('Saída 08:00 · Regresso até 19:00 · Início e fim: Ponto no mapa');
  });

  test('a ponta à espera do toque no mapa (a faixa da vista) é a que está a escolher', () => {
    const inicio = definicoesDoPainel(definicoes(), 'inicio');
    expect(inicio.pontas.map((p) => [p.chave, p.aEscolher])).toEqual([['inicio', true], ['fim', false]]);
    const fim = definicoesDoPainel(definicoes(), 'fim');
    expect(fim.pontas.map((p) => [p.chave, p.aEscolher])).toEqual([['inicio', false], ['fim', true]]);
    expect(definicoesDoPainel(definicoes(), 'outra').pontas.map((p) => p.aEscolher)).toEqual([false, false]);
    expect(definicoesDoPainel(definicoes()).pontas.map((p) => p.aEscolher)).toEqual([false, false]);
  });

  test('desligadas numa rota virtual, com a mensagem do planeador', () => {
    const painel = definicoesDoPainel(definicoes({ ativas: false, mensagem: TEXTO_DEFINICOES_SEM_ROTA }), null);
    expect(painel.ativas).toBe(false);
    expect(painel.mensagem).toBe('Adicione a primeira paragem para mudar as definições do dia.');
  });

  test('só um ativas e um evitar_portagens verdadeiros contam; uma mensagem vazia ou que não é texto não conta', () => {
    const painel = definicoesDoPainel(definicoes({ ativas: 'sim', evitar_portagens: 1, mensagem: '' }), null);
    expect([painel.ativas, painel.evitarPortagens, painel.mensagem]).toEqual([false, false, null]);
    expect(definicoesDoPainel(definicoes({ mensagem: 42 }), null).mensagem).toBeNull();
  });

  test('uma hora que não é texto fica vazia no campo e fora do resumo', () => {
    const painel = definicoesDoPainel(definicoes({ hora_saida: null, hora_regresso_limite: 1900 }), null);
    expect(painel.horas.map((h) => h.valor)).toEqual(['', '']);
    expect(painel.resumo).toBe('Início e fim: Fábrica');
    const soSaida = definicoesDoPainel(definicoes({ hora_regresso_limite: '' }), null);
    expect(soSaida.resumo).toBe('Saída 08:00 · Início e fim: Fábrica');
  });

  test('uma ponta estragada (null na vista) não tem texto nem botão carregado, e fica fora do resumo', () => {
    const painel = definicoesDoPainel(definicoes({ fim: null }), null);
    expect(painel.pontas[1]).toEqual({ chave: 'fim', rotulo: 'Fim', texto: null, fabrica: false, noMapa: false, aEscolher: false });
    expect(painel.resumo).toBe('Saída 08:00 · Regresso até 19:00 · Início: Fábrica');
    const semNenhuma = definicoesDoPainel(definicoes({ inicio: null, fim: null }), null);
    expect(semNenhuma.resumo).toBe('Saída 08:00 · Regresso até 19:00');
  });

  test('o texto da ponta é o dos botões, pelo sinal da fábrica (o texto da vista não conta)', () => {
    const painel = definicoesDoPainel(definicoes({ inicio: { ...FABRICA, texto: 'outro' }, fim: { ...PONTO, texto: 7 } }), null);
    expect(painel.pontas.map((p) => p.texto)).toEqual([TEXTO_FABRICA, TEXTO_PONTO_NO_MAPA]);
    // Só o `fabrica: true` é a fábrica.
    const estranha = definicoesDoPainel(definicoes({ inicio: { lat: 1, lng: 2, fabrica: 'sim' } }), null);
    expect(estranha.pontas[0]).toEqual({ chave: 'inicio', rotulo: 'Início', texto: 'Ponto no mapa', fabrica: false, noMapa: true, aEscolher: false });
  });

  test('sem definições (a carregar, falha, dia inválido), null', () => {
    expect(definicoesDoPainel(null, null)).toBeNull();
    expect(definicoesDoPainel(undefined, 'inicio')).toBeNull();
    expect(definicoesDoPainel('definicoes', null)).toBeNull();
  });

  test('vem congelado', () => {
    const painel = definicoesDoPainel(definicoes(), 'inicio');
    expect(Object.isFrozen(painel)).toBe(true);
    expect(Object.isFrozen(painel.horas)).toBe(true);
    expect(Object.isFrozen(painel.horas[0])).toBe(true);
    expect(Object.isFrozen(painel.pontas)).toBe(true);
    expect(Object.isFrozen(painel.pontas[1])).toBe(true);
    expect(Object.isFrozen(painel.pontoNoMapa)).toBe(true);
  });

  // Revisão dos ecrãs da F3, F3-UX-6: sem mapa onde tocar, "Ponto no mapa" desliga-se e diz porquê.
  test('F3-UX-6: sem mapa (`semMapa`), "Ponto no mapa" desligado com "Sem mapa — use a fábrica."', () => {
    expect(TEXTO_SEM_MAPA_PONTO).toBe('Sem mapa — use a fábrica.');
    expect(definicoesDoPainel(definicoes({ semMapa: true }), null).pontoNoMapa).toEqual({ ativo: false, falta: 'Sem mapa — use a fábrica.' });
    expect(definicoesDoPainel(definicoes({ semMapa: false }), null).pontoNoMapa).toEqual({ ativo: true, falta: null });
    // Só o `true` é "sem mapa".
    expect(definicoesDoPainel(definicoes({ semMapa: 'sim' }), null).pontoNoMapa).toEqual({ ativo: true, falta: null });
    // Com as definições desligadas (a rota virtual, sem rede) o porquê é o geral: a falta do mapa não se repete.
    expect(definicoesDoPainel(definicoes({ ativas: false, semMapa: true }), null).pontoNoMapa).toEqual({ ativo: false, falta: null });
    expect(definicoesDoPainel(definicoes({ ativas: false }), null).pontoNoMapa).toEqual({ ativo: false, falta: null });
    // O resto não muda: as horas, a fábrica e as portagens continuam ligadas.
    expect(definicoesDoPainel(definicoes({ semMapa: true }), null).ativas).toBe(true);
  });
});

describe('faixaDoPonto', () => {
  test('"Toque no mapa no ponto de início/fim" (os textos do planeador), com a ponta', () => {
    expect(faixaDoPonto('inicio')).toEqual({ ponta: 'inicio', texto: 'Toque no mapa no ponto de início' });
    expect(faixaDoPonto('fim')).toEqual({ ponta: 'fim', texto: 'Toque no mapa no ponto de fim' });
    expect(faixaDoPonto('fim').texto).toBe(TEXTOS_ESCOLHER_PONTO.fim);
  });

  test('sem nada a escolher (ou uma ponta que não existe), sem faixa', () => {
    expect(faixaDoPonto(null)).toBeNull();
    expect(faixaDoPonto(undefined)).toBeNull();
    expect(faixaDoPonto('meio')).toBeNull();
    expect(faixaDoPonto('toString')).toBeNull();
  });

  test('vem congelada', () => {
    expect(Object.isFrozen(faixaDoPonto('inicio'))).toBe(true);
  });
});

// --- As sugestões (T3.39) ------------------------------------------------------------------------

describe('sugestoesDoPainel', () => {
  const loja = (id, extra = {}) => ({
    id, nome: `Loja ${id}`, fase: 'contactada', lat: 38.7, lng: -9.1, distancia: '1,2 km', noCaminho: false, aAdicionar: false, ...extra,
  });
  const lista = (extra = {}) => ({
    estado: 'lista',
    grupos: [
      { fase: 'contactada', titulo: 'A aguardar amostra', lojas: [loja('a'), loja('b', { distancia: 'no caminho, 0,8 km', noCaminho: true })], mais: 0, textoMais: null },
      { fase: 'potencial', titulo: 'Potencial', lojas: [loja('c', { fase: 'potencial' })], mais: 3, textoMais: 'e mais 3' },
    ],
    mensagem: null,
    tentar: false,
    aTentar: false,
    ...extra,
  });

  test('os grupos pela ordem da vista, cada loja com a distância e o botão "Adicionar" ligado', () => {
    expect(sugestoesDoPainel(lista(), true)).toEqual({
      titulo: 'Sugestões perto da rota',
      estado: 'lista',
      mensagem: null,
      tentar: false,
      aTentar: false,
      grupos: [
        {
          fase: 'contactada',
          titulo: 'A aguardar amostra',
          textoMais: null,
          lojas: [
            { id: 'a', nome: 'Loja a', distancia: '1,2 km', noCaminho: false, botao: { texto: 'Adicionar', ativo: true, rotulo: 'Adicionar: Loja a' } },
            { id: 'b', nome: 'Loja b', distancia: 'no caminho, 0,8 km', noCaminho: true, botao: { texto: 'Adicionar', ativo: true, rotulo: 'Adicionar: Loja b' } },
          ],
        },
        {
          fase: 'potencial',
          titulo: 'Potencial',
          textoMais: 'e mais 3',
          lojas: [{ id: 'c', nome: 'Loja c', distancia: '1,2 km', noCaminho: false, botao: { texto: 'Adicionar', ativo: true, rotulo: 'Adicionar: Loja c' } }],
        },
      ],
    });
  });

  test('a loja a adicionar: "A adicionar…" e desligada (as outras continuam)', () => {
    const vista = lista();
    vista.grupos[0].lojas[1].aAdicionar = true;
    const [grupo] = sugestoesDoPainel(vista, true).grupos;
    expect(grupo.lojas.map((l) => l.botao)).toEqual([
      { texto: 'Adicionar', ativo: true, rotulo: 'Adicionar: Loja a' },
      { texto: 'A adicionar…', ativo: false, rotulo: 'A adicionar…: Loja b' },
    ]);
    expect(TEXTO_A_ADICIONAR).toBe('A adicionar…');
  });

  test('sem poder adicionar (a rota cheia, sem rede, o conflito), todos desligados', () => {
    const painel = sugestoesDoPainel(lista(), false);
    expect(painel.grupos.flatMap((g) => g.lojas.map((l) => l.botao.ativo))).toEqual([false, false, false]);
    expect(sugestoesDoPainel(lista(), 'sim').grupos[0].lojas[0].botao.ativo).toBe(false);
    expect(sugestoesDoPainel(lista()).grupos[0].lojas[0].botao.ativo).toBe(false);
  });

  test('só um aAdicionar e um noCaminho verdadeiros contam', () => {
    const vista = lista();
    vista.grupos[0].lojas[0] = loja('a', { aAdicionar: 'sim', noCaminho: 1 });
    const [primeira] = sugestoesDoPainel(vista, true).grupos[0].lojas;
    expect([primeira.botao.texto, primeira.botao.ativo, primeira.noCaminho]).toEqual(['Adicionar', true, false]);
  });

  test('a carregar, sem paragens, nenhuma e a falha: a mensagem da vista, sem grupos', () => {
    const aCarregar = { estado: 'a_carregar', grupos: [], mensagem: TEXTO_SUGESTOES_A_CARREGAR, tentar: false, aTentar: false };
    expect(sugestoesDoPainel(aCarregar, true)).toEqual({
      titulo: 'Sugestões perto da rota', estado: 'a_carregar', mensagem: 'A procurar lojas perto…', tentar: false, aTentar: false, grupos: [],
    });
    const falha = sugestoesDoPainel({ estado: 'falha', grupos: [], mensagem: 'Sem rede.', tentar: true, aTentar: true }, true);
    expect([falha.estado, falha.mensagem, falha.tentar, falha.aTentar]).toEqual(['falha', 'Sem rede.', true, true]);
    const tentarEstranho = sugestoesDoPainel({ estado: 'falha', grupos: [], mensagem: 'x', tentar: 'sim', aTentar: 1 }, true);
    expect([tentarEstranho.tentar, tentarEstranho.aTentar]).toEqual([false, false]);
  });

  test('com a vista do planeador (vistaDasSugestoes): sem paragens, nenhuma e a lista', () => {
    expect(sugestoesDoPainel(vistaDasSugestoes({ sem_paragens: true }, []), true).mensagem).toBe(TEXTO_PRIMEIRA_PARAGEM);
    expect(sugestoesDoPainel(vistaDasSugestoes({ sem_paragens: false, grupos: [] }, []), true).mensagem).toBe(TEXTO_SUGESTOES_NENHUMA);
    const resposta = {
      sem_paragens: false,
      no_caminho: true,
      grupos: [{ fase: 'potencial', lojas: [{ id: 'x', nome: 'Café X', fase: 'potencial', lat: 1, lng: 2, distancia_m: 800, no_caminho: true }], mais: 0 }],
    };
    const vista = vistaDasSugestoes(resposta, []);
    // O planeador junta o `aAdicionar` de cada loja.
    vista.grupos[0].lojas[0].aAdicionar = false;
    const painel = sugestoesDoPainel(vista, true);
    expect(painel.grupos).toEqual([{
      fase: 'potencial',
      titulo: 'Potencial',
      textoMais: null,
      lojas: [{ id: 'x', nome: 'Café X', distancia: 'no caminho, 0,8 km', noCaminho: true, botao: { texto: 'Adicionar', ativo: true, rotulo: 'Adicionar: Café X' } }],
    }]);
  });

  test('o que não é um grupo ou uma loja fica de fora; um nome ou uma distância que não são texto ficam vazios', () => {
    const vista = lista({ grupos: [null, 'grupo', { fase: 'potencial', titulo: 'Potencial', lojas: [null, 7, loja('d', { nome: 3, distancia: 5 })], textoMais: '' }, { fase: 'x', titulo: 'X', lojas: 'nada' }] });
    const painel = sugestoesDoPainel(vista, true);
    expect(painel.grupos).toEqual([
      {
        fase: 'potencial',
        titulo: 'Potencial',
        textoMais: null,
        lojas: [{ id: 'd', nome: '', distancia: null, noCaminho: false, botao: { texto: 'Adicionar', ativo: true, rotulo: 'Adicionar' } }],
      },
      { fase: 'x', titulo: 'X', textoMais: null, lojas: [] },
    ]);
    expect(sugestoesDoPainel(lista({ grupos: 'nada', mensagem: '' }), true)).toMatchObject({ grupos: [], mensagem: null });
  });

  test('sem sugestões (só de leitura, a carregar a rota), null', () => {
    expect(sugestoesDoPainel(null, true)).toBeNull();
    expect(sugestoesDoPainel(undefined, true)).toBeNull();
    expect(sugestoesDoPainel('lista', true)).toBeNull();
  });

  test('vem congelado', () => {
    const painel = sugestoesDoPainel(lista(), true);
    expect(Object.isFrozen(painel)).toBe(true);
    expect(Object.isFrozen(painel.grupos)).toBe(true);
    expect(Object.isFrozen(painel.grupos[0])).toBe(true);
    expect(Object.isFrozen(painel.grupos[0].lojas)).toBe(true);
    expect(Object.isFrozen(painel.grupos[0].lojas[0].botao)).toBe(true);
  });
});

// --- O cartão de uma loja esbatida (T3.39) -------------------------------------------------------

describe('cartaoDaLoja', () => {
  const escolhida = (extra = {}) => ({
    id: 'loja-z', nome: 'Café Z', fase: 'contactada', motivo: 'amostra', rotuloMotivo: 'Amostra', aAdicionar: false, ativo: true, ...extra,
  });

  test('o nome, a fase, o motivo (o da fase, já escolhido pelo planeador) e "Adicionar à rota" ligado', () => {
    expect(cartaoDaLoja(escolhida())).toEqual({
      id: 'loja-z',
      nome: 'Café Z',
      fase: 'contactada',
      rotuloFase: 'A aguardar amostra',
      motivo: 'amostra',
      textoMotivo: 'Motivo: Amostra',
      botao: { texto: 'Adicionar à rota', ativo: true },
    });
  });

  test('a adicionar: "A adicionar…" e desligado; sem poder adicionar, desligado', () => {
    expect(cartaoDaLoja(escolhida({ aAdicionar: true, ativo: false })).botao).toEqual({ texto: 'A adicionar…', ativo: false });
    expect(cartaoDaLoja(escolhida({ ativo: false })).botao).toEqual({ texto: 'Adicionar à rota', ativo: false });
    expect(cartaoDaLoja(escolhida({ ativo: 'sim' })).botao.ativo).toBe(false);
    expect(cartaoDaLoja(escolhida({ aAdicionar: 1 })).botao.texto).toBe('Adicionar à rota');
  });

  test('uma fase desconhecida fica sem rótulo; um nome ou um motivo que não são texto ficam vazios', () => {
    const cartao = cartaoDaLoja(escolhida({ fase: 'toString', nome: null, rotuloMotivo: null, motivo: 7 }));
    expect(cartao).toEqual({
      id: 'loja-z', nome: '', fase: null, rotuloFase: null, motivo: null, textoMotivo: null, botao: { texto: 'Adicionar à rota', ativo: true },
    });
    expect(cartaoDaLoja(escolhida({ fase: null })).rotuloFase).toBeNull();
    expect(cartaoDaLoja(escolhida({ rotuloMotivo: '' })).textoMotivo).toBeNull();
  });

  test('sem loja escolhida (ou sem id), sem cartão', () => {
    expect(cartaoDaLoja(null)).toBeNull();
    expect(cartaoDaLoja(undefined)).toBeNull();
    expect(cartaoDaLoja('loja')).toBeNull();
    expect(cartaoDaLoja(escolhida({ id: '' }))).toBeNull();
    expect(cartaoDaLoja(escolhida({ id: 7 }))).toBeNull();
  });

  test('vem congelado', () => {
    const cartao = cartaoDaLoja(escolhida());
    expect(Object.isFrozen(cartao)).toBe(true);
    expect(Object.isFrozen(cartao.botao)).toBe(true);
  });
});

// --- Revisão dos ecrãs da F3 (2026-10-30) ----------------------------------------------------------

describe('textoDaChegada (F3-UX-1)', () => {
  const linha = (extra = {}) => ({ chegada: '10:35', espera: null, chegadaAntiga: false, ...extra });

  test('a chegada e a espera, só com o que existe', () => {
    expect(textoDaChegada(linha())).toBe('Chegada 10:35');
    expect(textoDaChegada(linha({ espera: 5 }))).toBe('Chegada 10:35 (espera 5 min)');
  });

  test('com as horas velhas: "(antiga)" e sem a espera (também velha)', () => {
    expect(textoDaChegada(linha({ chegadaAntiga: true }))).toBe('Chegada 10:35 (antiga)');
    expect(textoDaChegada(linha({ espera: 5, chegadaAntiga: true }))).toBe('Chegada 10:35 (antiga)');
    // Só o `true` é antiga.
    expect(textoDaChegada(linha({ espera: 5, chegadaAntiga: 'sim' }))).toBe('Chegada 10:35 (espera 5 min)');
  });

  test('sem chegada (ou que não é texto), null', () => {
    expect(textoDaChegada(linha({ chegada: null }))).toBeNull();
    expect(textoDaChegada(linha({ chegada: '', chegadaAntiga: true }))).toBeNull();
    expect(textoDaChegada(linha({ chegada: 935 }))).toBeNull();
    expect(textoDaChegada(null)).toBeNull();
  });
});

test('F3-UX-5: o texto de uma fechada mantida', () => {
  expect(TEXTO_FECHADA_MANTIDA).toBe('⚠️ Fechada neste dia — mantida');
});

describe('enquadramentoDoMapa (F3-UX-2)', () => {
  const FABRICA = Object.freeze({ lat: 38.75, lng: -9.2, fabrica: true });
  const PARAGEM = Object.freeze({ id: 'A', numero: 1, lat: 38.7, lng: -9.1 });
  const LOJAS = Object.freeze([
    { id: 'x', nome: 'X', lat: 38.8, lng: -9.3 },
    { id: 'y', nome: 'Y', lat: 41.1, lng: -8.6 },
    { id: 'z', nome: 'Sem sítio', lat: null, lng: null },
  ]);
  const mapa = (extra = {}) => ({ paragens: [], inicio: FABRICA, fim: FABRICA, lojasForaDaRota: LOJAS, ...extra });

  test('com paragens, a rota (o `enquadrarRota`), uma vez', () => {
    expect(enquadramentoDoMapa(mapa({ paragens: [PARAGEM] }), null)).toEqual({ enquadrar: 'rota', estado: 'feito' });
    expect(enquadramentoDoMapa(mapa({ paragens: [PARAGEM] }), 'feito')).toEqual({ enquadrar: null, estado: 'feito' });
    // As lojas ainda por chegar não contam: a rota tem paragens.
    expect(enquadramentoDoMapa(mapa({ paragens: [PARAGEM], lojasForaDaRota: null }))).toEqual({ enquadrar: 'rota', estado: 'feito' });
  });

  test('sem paragens: as lojas fora da rota (com coordenadas) e as pontas — não só a fábrica, que dava o zoom da rua', () => {
    expect(enquadramentoDoMapa(mapa(), null)).toEqual({
      enquadrar: [{ lat: 38.8, lng: -9.3 }, { lat: 41.1, lng: -8.6 }, { lat: 38.75, lng: -9.2 }, { lat: 38.75, lng: -9.2 }],
      estado: 'feito',
    });
    // Um início num ponto do mapa e o fim estragado.
    const outro = enquadramentoDoMapa(mapa({ inicio: { lat: 39, lng: -9, fabrica: false }, fim: null }), null);
    expect(outro.enquadrar).toEqual([{ lat: 38.8, lng: -9.3 }, { lat: 41.1, lng: -8.6 }, { lat: 39, lng: -9 }]);
    expect(enquadramentoDoMapa(mapa(), 'feito')).toEqual({ enquadrar: null, estado: 'feito' });
  });

  test('sem paragens e sem as lojas ainda: o centro (`[]`, o zoom 12 do mapa.js) e, quando chegam, elas, uma vez', () => {
    const primeiro = enquadramentoDoMapa(mapa({ lojasForaDaRota: null }), null);
    expect(primeiro).toEqual({ enquadrar: [], estado: 'sem_lojas' });
    // Ainda sem elas: nada mais.
    expect(enquadramentoDoMapa(mapa({ lojasForaDaRota: null }), 'sem_lojas')).toEqual({ enquadrar: null, estado: 'sem_lojas' });
    // Chegam.
    expect(enquadramentoDoMapa(mapa(), 'sem_lojas')).toEqual({
      enquadrar: [{ lat: 38.8, lng: -9.3 }, { lat: 41.1, lng: -8.6 }, { lat: 38.75, lng: -9.2 }, { lat: 38.75, lng: -9.2 }],
      estado: 'feito',
    });
    // Chegam vazias (ou só sem coordenadas): o centro já está, nada mais.
    expect(enquadramentoDoMapa(mapa({ lojasForaDaRota: [] }), 'sem_lojas')).toEqual({ enquadrar: null, estado: 'feito' });
    // Entretanto entrou uma paragem: quem planeia já mexeu, o mapa fica.
    expect(enquadramentoDoMapa(mapa({ paragens: [PARAGEM] }), 'sem_lojas')).toEqual({ enquadrar: null, estado: 'feito' });
  });

  test('sem paragens e nenhuma loja com coordenadas: o centro, e acabou', () => {
    expect(enquadramentoDoMapa(mapa({ lojasForaDaRota: [] }), null)).toEqual({ enquadrar: [], estado: 'feito' });
    expect(enquadramentoDoMapa(mapa({ lojasForaDaRota: [LOJAS[2]] }), null)).toEqual({ enquadrar: [], estado: 'feito' });
  });

  test('um mapa da vista estragado não rebenta: o centro, à espera das lojas', () => {
    expect(enquadramentoDoMapa(null, null)).toEqual({ enquadrar: [], estado: 'sem_lojas' });
    expect(enquadramentoDoMapa({ paragens: 'x', lojasForaDaRota: 'y' })).toEqual({ enquadrar: [], estado: 'sem_lojas' });
  });

  test('vem congelado', () => {
    const resultado = enquadramentoDoMapa(mapa(), null);
    expect(Object.isFrozen(resultado)).toBe(true);
    expect(Object.isFrozen(resultado.enquadrar)).toBe(true);
    expect(Object.isFrozen(resultado.enquadrar[0])).toBe(true);
  });
});
