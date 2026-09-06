/**
 * O QUE O BOTÃO «Sincronizar agora» DIZ — corrido de verdade, não lido.
 *
 * A promessa que este ficheiro guarda é uma só: os `assinalados` chegam SEMPRE
 * a quem carregou no botão. São os documentos que a sincronização teve de
 * saltar por avaria e que **não voltam a ser tentados** — a janela do cron só
 * olha para hoje e ontem. Até esta tarefa esse campo não tinha consumidor
 * nenhum: vivia no log da API, onde ninguém olha, e uma FS de 6,85 € que lá
 * caísse desaparecia do Dashboard e do relatório com o cron a parecer saudável.
 */
import { resumoDaSincronizacao } from './faturacao';

const VOLTA_LIMPA = {
  lidos: 12, gravados: 3, ignorados: 8, repetidos: 1,
  motivos: {}, assinalados: [], erros: [], simulado: false,
};

describe('resumoDaSincronizacao', () => {
  test('a volta normal conta o que entrou', () => {
    const r = resumoDaSincronizacao(VOLTA_LIMPA);
    expect(r.tipo).toBe('success');
    expect(r.titulo).toBe('3 faturas novas da app');
    expect(r.descricao).toContain('3 novas · 1 repetida · 8 ignoradas');
  });

  test('sem faturas novas não finge que trouxe alguma', () => {
    expect(resumoDaSincronizacao({ ...VOLTA_LIMPA, gravados: 0 }).titulo)
      .toBe('Sem faturas novas da app');
  });

  test('uma só fatura fala no singular', () => {
    expect(resumoDaSincronizacao({ ...VOLTA_LIMPA, gravados: 1 }).titulo)
      .toBe('1 fatura nova da app');
  });

  test('os assinalados aparecem, um por linha, mesmo com a volta a correr bem', () => {
    const r = resumoDaSincronizacao({
      ...VOLTA_LIMPA,
      assinalados: ['FS 06P2026/447: sem ATCUD',
        'FS 06P2026/448: desapareceu do Vendus'],
    });
    expect(r.tipo).toBe('warning');
    expect(r.titulo).toBe('2 documentos ficaram de fora');
    expect(r.descricao).toContain('FS 06P2026/447: sem ATCUD');
    expect(r.descricao).toContain('FS 06P2026/448: desapareceu do Vendus');
    // A contagem do que ENTROU não se perde por haver um aviso.
    expect(r.descricao).toContain('3 novas');
  });

  test('os assinalados não se somam por cima dos ignorados', () => {
    // No servidor, `_saltar` chama `_contar`: os 2 assinalados são 2 DOS 8
    // ignorados. Escritas como duas contagens soltas, quem lê soma 10 e vai
    // procurar dois documentos que não existem.
    const r = resumoDaSincronizacao({
      ...VOLTA_LIMPA,
      assinalados: ['FS 06P2026/447: sem ATCUD',
        'FS 06P2026/448: desapareceu do Vendus'],
    });
    expect(r.descricao)
      .toContain('8 ignoradas (2 delas ficaram de fora e não voltam)');
  });

  test('um só assinalado fala no singular', () => {
    const r = resumoDaSincronizacao({
      ...VOLTA_LIMPA, assinalados: ['FS 06P2026/447: sem ATCUD'],
    });
    expect(r.descricao)
      .toContain('8 ignoradas (1 dela ficou de fora e não volta)');
  });

  test('sem assinalados a contagem fica limpa', () => {
    expect(resumoDaSincronizacao(VOLTA_LIMPA).descricao)
      .toBe('3 novas · 1 repetida · 8 ignoradas');
  });

  test('um erro manda no tom, mesmo com faturas gravadas', () => {
    const r = resumoDaSincronizacao({
      ...VOLTA_LIMPA,
      erros: ['sem loja escolhida para as vendas da app'],
    });
    expect(r.tipo).toBe('error');
    expect(r.titulo).toBe('A sincronização não chegou ao fim');
    expect(r.descricao).toContain('sem loja escolhida');
  });

  // As ANULADAS: as que já cá estavam e passaram a `A` no Vendus. Não são
  // avaria (não entram nos `assinalados`), mas são dinheiro a SAIR do
  // Dashboard — e o dono anulou-as no painel do Vendus, não aqui.
  test('uma anulação aparece a quem carregou no botão', () => {
    const r = resumoDaSincronizacao({
      ...VOLTA_LIMPA,
      gravados: 0,
      anulados: ['FS 06P2026/446: anulada no Vendus depois de importada'],
    });
    expect(r.titulo).toBe('1 fatura anulada no Vendus');
    expect(r.descricao).toContain('1 anulada');
    expect(r.descricao).toContain('FS 06P2026/446');
  });

  test('uma anulação não se disfarça de avaria', () => {
    const r = resumoDaSincronizacao({
      ...VOLTA_LIMPA,
      anulados: ['FS 06P2026/446: anulada no Vendus depois de importada'],
    });
    // Nem entra no parêntesis dos «que ficaram de fora e não voltam» — ela
    // não ficou de fora, entrou e depois saiu.
    expect(r.descricao).not.toContain('ficou de fora');
    expect(r.descricao).toContain('8 ignoradas · 1 anulada');
    // E com faturas novas o título continua a liderar com elas.
    expect(r.titulo).toBe('3 faturas novas da app');
  });

  test('uma resposta vazia (ou nenhuma) não rebenta o ecrã', () => {
    expect(resumoDaSincronizacao(undefined).tipo).toBe('success');
    expect(resumoDaSincronizacao({}).descricao)
      .toContain('0 novas · 0 repetidas · 0 ignoradas');
  });
});
