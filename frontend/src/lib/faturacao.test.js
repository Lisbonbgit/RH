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

  test('um erro manda no tom, mesmo com faturas gravadas', () => {
    const r = resumoDaSincronizacao({
      ...VOLTA_LIMPA,
      erros: ['sem loja escolhida para as vendas da app'],
    });
    expect(r.tipo).toBe('error');
    expect(r.titulo).toBe('A sincronização não chegou ao fim');
    expect(r.descricao).toContain('sem loja escolhida');
  });

  test('uma resposta vazia (ou nenhuma) não rebenta o ecrã', () => {
    expect(resumoDaSincronizacao(undefined).tipo).toBe('success');
    expect(resumoDaSincronizacao({}).descricao)
      .toContain('0 novas · 0 repetidas · 0 ignoradas');
  });
});
