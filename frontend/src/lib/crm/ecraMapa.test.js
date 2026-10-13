/**
 * O ECRÃ DO MAPA — as decisões puras da página (`pages/crm/CrmMapa.js`).
 *
 * Porta das regras de public/assets/js/ecras/mapa.js do CRM autónomo
 * (etiqueta `referencia-standalone`), com os casos de tests/js/ecra-mapa.test.js
 * que não precisam de DOM nem de Leaflet: a primeira vista (enquadrar as lojas
 * que se veem, todas se os filtros as escondem todas, o centro sem lojas ou
 * com erro, e não voltar a mexer depois de uma falha), a loja a centrar ao
 * nível da rua e o aviso "Loja guardada — os filtros escondem-na do mapa.".
 *
 * Adaptações ao portal (plano T2.25):
 *   - a loja a centrar vem do endereço (`?loja=<id>`) e procura-se na lista das
 *     lojas, sem outro pedido (nota da T2.24); no autónomo vinha com o ecrã
 *     de onde se saía (`contexto.chegada.loja`). Uma loja que não está na lista
 *     não centra nada: a vista enquadra as lojas, como sempre;
 *   - o aviso vem do `state` da navegação (`{aviso: 'Loja guardada'}`) e
 *     mostra-se num toast; a loja do aviso é a do `?loja=`;
 *   - os ids são uuid em texto;
 *   - o cartão mostra o contacto em texto (`contactoDaLoja`: pessoa · telefone,
 *     só o que existe) em vez do botão Ligar, que saiu em 2026-10-13 a pedido
 *     do Bruce.
 */
import fs from 'fs';
import path from 'path';
import { MENSAGEM_ERRO_INESPERADO } from './api';
import { ZOOM_LOJA } from './mapa';
import { filtrosPadrao } from './filtros';
import {
  PARAMETRO_LOJA,
  SEPARADOR_CONTACTO,
  TEXTO_ESCONDIDA_PELOS_FILTROS,
  contactoDaLoja,
  lerAviso,
  lojaComId,
  textoAviso,
  textoDoErro,
  vistaAoCarregar,
} from './ecraMapa';

const LISBOA = '3f1c2d4e-5a6b-4c7d-8e9f-0a1b2c3d4e5f';
const MERCEARIA = '0b6f3c1e-1111-4222-8333-444455556666';
const CAFE = '0b6f3c1e-2222-4222-8333-444455556666';
const QUIOSQUE = '0b6f3c1e-3333-4222-8333-444455556666';

// As três lojas do ecra-mapa.test.js: cliente e perdida em Lisboa, potencial sem região — com a forma
// do resumo do `GET /lojas` (`CAMPOS_RESUMO` de `backend/crm/formatar.py`; o teste abaixo lê-a de lá).
const TRES_LOJAS = [
  {
    id: MERCEARIA, nome: 'Mercearia da Baixa', fase: 'cliente', regiao_id: LISBOA, lat: 38.7108, lng: -9.1369,
    telefone: '+351 912 345 678', pessoa_contacto: 'D. Amélia',
  },
  {
    id: CAFE, nome: 'Café Fechado', fase: 'perdida', regiao_id: LISBOA, lat: 38.7135, lng: -9.1458,
    telefone: null, pessoa_contacto: null,
  },
  {
    id: QUIOSQUE, nome: 'Quiosque Novo', fase: 'potencial', regiao_id: null, lat: 38.74, lng: -9.16,
    telefone: null, pessoa_contacto: null,
  },
];

// frontend/src/lib/crm → raiz do repositório (como o `formularioLoja.test.js`).
const FORMATAR_PY = path.join(__dirname, '..', '..', '..', '..', 'backend', 'crm', 'formatar.py');

const SO_CLIENTES = { fases: ['cliente'], regiao: 'todas' };
const SEM_FASES = { fases: [], regiao: 'todas' };

describe('textos', () => {
  test('o texto do aviso quando os filtros escondem a loja, e o parâmetro do endereço', () => {
    expect(TEXTO_ESCONDIDA_PELOS_FILTROS).toBe('os filtros escondem-na do mapa.');
    expect(PARAMETRO_LOJA).toBe('loja');
  });

  test('o erro mostra a sua mensagem; sem mensagem (ou vazia), o texto de erro inesperado', () => {
    expect(textoDoErro({ codigo: 'sem_rede', mensagem: 'Sem rede — verifique a ligação e tente novamente.' }))
      .toBe('Sem rede — verifique a ligação e tente novamente.');
    for (const erro of [{}, { mensagem: '' }, { mensagem: 3 }, null, undefined, new Error()]) {
      expect(textoDoErro(erro)).toBe(MENSAGEM_ERRO_INESPERADO);
    }
  });
});

describe('lojaComId (o ?loja=<id>)', () => {
  test('devolve a loja da lista com esse id (o próprio objeto)', () => {
    expect(lojaComId(TRES_LOJAS, QUIOSQUE)).toBe(TRES_LOJAS[2]);
  });

  test('sem essa loja na lista, ou sem id, devolve null', () => {
    expect(lojaComId(TRES_LOJAS, '0b6f3c1e-9999-4222-8333-444455556666')).toBeNull();
    for (const id of [null, undefined, '', 1, {}]) expect(lojaComId(TRES_LOJAS, id)).toBeNull();
  });

  test('o id compara-se tal e qual (sem maiúsculas nem espaços à volta)', () => {
    expect(lojaComId(TRES_LOJAS, QUIOSQUE.toUpperCase())).toBeNull();
    expect(lojaComId(TRES_LOJAS, ` ${QUIOSQUE}`)).toBeNull();
  });

  test('uma loja sem coordenadas válidas não serve para centrar o mapa', () => {
    const semCoordenadas = [{ ...TRES_LOJAS[0], lat: null }, { ...TRES_LOJAS[1], lng: '-9.1' }, { ...TRES_LOJAS[2], lat: NaN }];
    for (const loja of semCoordenadas) expect(lojaComId(semCoordenadas, loja.id)).toBeNull();
  });

  test('sem lista (ainda não chegou, ou falhou) devolve null', () => {
    for (const lojas of [null, undefined, {}]) expect(lojaComId(lojas, MERCEARIA)).toBeNull();
  });
});

describe('vistaAoCarregar (a vista quando o pedido das lojas termina)', () => {
  test('sem loja no endereço: enquadra as lojas todas (com os filtros por omissão, vêem-se todas)', () => {
    expect(vistaAoCarregar({ lojas: TRES_LOJAS, filtros: filtrosPadrao() }))
      .toEqual({ tipo: 'enquadrar', lojas: TRES_LOJAS });
  });

  test('filtros: a vista inicial enquadra as lojas que se veem (as dos filtros guardados)', () => {
    expect(vistaAoCarregar({ lojas: TRES_LOJAS, filtros: SO_CLIENTES }))
      .toEqual({ tipo: 'enquadrar', lojas: [TRES_LOJAS[0]] });
  });

  test('filtros: se os filtros guardados escondem todas, a vista enquadra na mesma todas as lojas', () => {
    expect(vistaAoCarregar({ lojas: TRES_LOJAS, filtros: SEM_FASES }))
      .toEqual({ tipo: 'enquadrar', lojas: TRES_LOJAS });
  });

  test('filtros inválidos contam como os de omissão (todas as lojas)', () => {
    for (const filtros of [null, undefined, 'x', { fases: 'cliente', regiao: 7 }]) {
      expect(vistaAoCarregar({ lojas: TRES_LOJAS, filtros })).toEqual({ tipo: 'enquadrar', lojas: TRES_LOJAS });
    }
  });

  test('sem lojas: enquadra uma lista vazia (o mapa mostra o centro das definições)', () => {
    expect(vistaAoCarregar({ lojas: [], filtros: filtrosPadrao() })).toEqual({ tipo: 'enquadrar', lojas: [] });
  });

  test('erro ao carregar as lojas: mostra o centro (enquadrar sem lojas)', () => {
    expect(vistaAoCarregar({ lojas: null, filtros: filtrosPadrao(), jaTemVista: false }))
      .toEqual({ tipo: 'enquadrar', lojas: [] });
  });

  test('erro outra vez ao tentar de novo (o mapa já tem vista): não mexe', () => {
    expect(vistaAoCarregar({ lojas: null, filtros: filtrosPadrao(), jaTemVista: true })).toBeNull();
    expect(vistaAoCarregar({ lojas: null, filtros: filtrosPadrao(), idLoja: QUIOSQUE, jaTemVista: true })).toBeNull();
  });

  test('as lojas chegam ao tentar de novo, depois de uma falha: enquadra-as (a vista do centro era provisória)', () => {
    expect(vistaAoCarregar({ lojas: TRES_LOJAS, filtros: filtrosPadrao(), jaTemVista: true }))
      .toEqual({ tipo: 'enquadrar', lojas: TRES_LOJAS });
  });

  test('loja no endereço: o mapa abre centrado nela, ao nível da rua (zoom 17)', () => {
    expect(ZOOM_LOJA).toBe(17);
    expect(vistaAoCarregar({ lojas: TRES_LOJAS, filtros: filtrosPadrao(), idLoja: QUIOSQUE }))
      .toEqual({ tipo: 'centrar', loja: TRES_LOJAS[2], zoom: ZOOM_LOJA });
  });

  test('loja no endereço escondida pelos filtros: centra na mesma onde ela está', () => {
    expect(vistaAoCarregar({ lojas: TRES_LOJAS, filtros: SO_CLIENTES, idLoja: QUIOSQUE }))
      .toEqual({ tipo: 'centrar', loja: TRES_LOJAS[2], zoom: ZOOM_LOJA });
  });

  test('loja no endereço que não está na lista (ou sem coordenadas): enquadra as lojas como sempre', () => {
    expect(vistaAoCarregar({ lojas: TRES_LOJAS, filtros: filtrosPadrao(), idLoja: '0b6f3c1e-9999-4222-8333-444455556666' }))
      .toEqual({ tipo: 'enquadrar', lojas: TRES_LOJAS });
    const semCoordenadas = [TRES_LOJAS[0], { ...TRES_LOJAS[2], lat: null }];
    expect(vistaAoCarregar({ lojas: semCoordenadas, filtros: filtrosPadrao(), idLoja: QUIOSQUE }))
      .toEqual({ tipo: 'enquadrar', lojas: semCoordenadas });
  });

  test('loja no endereço e as lojas não carregam: mostra o centro (sem a lista não se sabe onde ela está)', () => {
    expect(vistaAoCarregar({ lojas: null, filtros: filtrosPadrao(), idLoja: QUIOSQUE, jaTemVista: false }))
      .toEqual({ tipo: 'enquadrar', lojas: [] });
  });

  test('a loja do endereço chega ao tentar de novo, depois de uma falha: centra nela', () => {
    expect(vistaAoCarregar({ lojas: TRES_LOJAS, filtros: filtrosPadrao(), idLoja: MERCEARIA, jaTemVista: true }))
      .toEqual({ tipo: 'centrar', loja: TRES_LOJAS[0], zoom: ZOOM_LOJA });
  });

  test('não altera a lista nem os filtros recebidos', () => {
    const lojas = TRES_LOJAS.map((l) => ({ ...l }));
    const filtros = { fases: new Set(['cliente']), regiao: 'todas' };
    vistaAoCarregar({ lojas, filtros, idLoja: CAFE });
    expect(lojas).toEqual(TRES_LOJAS);
    expect([...filtros.fases]).toEqual(['cliente']);
  });
});

describe('contactoDaLoja (a linha "Contacto:" do cartão, em vez do botão Ligar)', () => {
  test('o separador entre a pessoa e o telefone', () => {
    expect(SEPARADOR_CONTACTO).toBe(' · ');
  });

  test('pessoa e telefone: "pessoa · telefone", tal como foram escritos', () => {
    expect(contactoDaLoja(TRES_LOJAS[0])).toBe('D. Amélia · +351 912 345 678');
    expect(contactoDaLoja({ pessoa_contacto: 'Sr. Rui', telefone: '912 345 678' })).toBe('Sr. Rui · 912 345 678');
  });

  test('o resumo do GET /lojas (a loja que o pino dá ao cartão) traz a pessoa e o telefone (formatar.py)', () => {
    // Revisão das alterações do dono (2026-10-13): o cartão recebe a loja da lista do mapa, não a ficha.
    // Falha, e não salta, se o ficheiro não estiver lá.
    expect(fs.existsSync(FORMATAR_PY)).toBe(true);
    const python = fs.readFileSync(FORMATAR_PY, 'utf8');
    const linhas = [...python.matchAll(/^CAMPOS_RESUMO = \((.*)\)$/gm)];
    expect(linhas).toHaveLength(1);
    const campos = linhas[0][1].split(',').map((campo) => campo.trim().replace(/^"|"$/g, '')).filter(Boolean);
    expect(campos).toEqual(expect.arrayContaining(['id', 'nome', 'fase', 'regiao_id', 'lat', 'lng']));
    expect(campos).toEqual(expect.arrayContaining(['pessoa_contacto', 'telefone']));
    // O fixture tem a forma do resumo: nem mais nem menos chaves.
    for (const loja of TRES_LOJAS) expect(Object.keys(loja).sort()).toEqual([...campos].sort());
  });

  test('só a pessoa, ou só o telefone: mostra o que há, sem separador', () => {
    expect(contactoDaLoja({ ...TRES_LOJAS[0], pessoa_contacto: null })).toBe('+351 912 345 678');
    expect(contactoDaLoja({ ...TRES_LOJAS[0], pessoa_contacto: '' })).toBe('+351 912 345 678');
    expect(contactoDaLoja({ pessoa_contacto: 'D. Amélia' })).toBe('D. Amélia');
    expect(contactoDaLoja({ pessoa_contacto: 'D. Amélia', telefone: null })).toBe('D. Amélia');
    expect(contactoDaLoja({ pessoa_contacto: 'D. Amélia', telefone: '' })).toBe('D. Amélia');
  });

  test('sem pessoa nem telefone (ou só espaços): null — o cartão não mostra a linha', () => {
    expect(contactoDaLoja(TRES_LOJAS[1])).toBeNull();
    expect(contactoDaLoja({ pessoa_contacto: '', telefone: '' })).toBeNull();
    expect(contactoDaLoja({ pessoa_contacto: '   ', telefone: ' ' })).toBeNull();
    expect(contactoDaLoja({})).toBeNull();
    for (const loja of [null, undefined, 'x', 3]) expect(contactoDaLoja(loja)).toBeNull();
  });

  test('os espaços à volta saem; o que não é texto conta como vazio', () => {
    expect(contactoDaLoja({ pessoa_contacto: '  D. Amélia ', telefone: ' 912 345 678  ' })).toBe('D. Amélia · 912 345 678');
    expect(contactoDaLoja({ pessoa_contacto: 7, telefone: ['912345678'] })).toBeNull();
    expect(contactoDaLoja({ pessoa_contacto: { nome: 'x' }, telefone: '912 345 678' })).toBe('912 345 678');
  });

  test('o telefone não precisa de ser marcável (ao contrário do antigo Ligar): aparece como texto', () => {
    expect(contactoDaLoja({ telefone: '1234' })).toBe('1234');
    expect(contactoDaLoja({ telefone: 'sem telefone' })).toBe('sem telefone');
  });

  test('não altera a loja recebida', () => {
    const loja = { ...TRES_LOJAS[0], pessoa_contacto: ' D. Amélia ' };
    const copia = { ...loja };
    contactoDaLoja(loja);
    expect(loja).toEqual(copia);
  });
});

describe('o aviso ao voltar ao mapa (ex.: "Loja guardada")', () => {
  test('lerAviso: o aviso do state da navegação; tudo o resto é null', () => {
    expect(lerAviso({ aviso: 'Loja guardada' })).toBe('Loja guardada');
    for (const estado of [null, undefined, {}, 'Loja guardada', { aviso: '' }, { aviso: 3 }, { aviso: null }]) {
      expect(lerAviso(estado)).toBeNull();
    }
  });

  test('sem aviso não há texto', () => {
    expect(textoAviso(null, TRES_LOJAS[0], filtrosPadrao())).toBeNull();
    expect(textoAviso('', TRES_LOJAS[0], filtrosPadrao())).toBeNull();
  });

  test('a loja aparece no mapa: só o aviso', () => {
    expect(textoAviso('Loja guardada', TRES_LOJAS[2], filtrosPadrao())).toBe('Loja guardada');
  });

  test('loja escondida pelos filtros guardados: o aviso diz porquê', () => {
    expect(textoAviso('Loja guardada', TRES_LOJAS[2], SO_CLIENTES)).toBe('Loja guardada — os filtros escondem-na do mapa.');
    expect(textoAviso('Loja guardada', TRES_LOJAS[2], { fases: ['potencial'], regiao: LISBOA }))
      .toBe('Loja guardada — os filtros escondem-na do mapa.');
  });

  test('sem a loja (não está na lista, ou a lista não chegou) ou sem coordenadas válidas: só o aviso', () => {
    expect(textoAviso('Loja guardada', null, SO_CLIENTES)).toBe('Loja guardada');
    expect(textoAviso('Loja guardada', { id: QUIOSQUE, lat: null }, SO_CLIENTES)).toBe('Loja guardada');
  });

  test('o nome da loja não entra no aviso (o aviso é um texto fixo)', () => {
    const loja = { ...TRES_LOJAS[2], nome: '<b>x</b>' };
    expect(textoAviso('Loja guardada', loja, filtrosPadrao())).toBe('Loja guardada');
    expect(textoAviso('Loja guardada', loja, SO_CLIENTES)).not.toMatch(/<b>|x<\/b>/);
  });
});
