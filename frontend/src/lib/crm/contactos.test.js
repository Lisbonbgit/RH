/**
 * OS CONTACTOS DE UMA LOJA — as regras da secção da ficha, sem DOM (desenho de 2026-11-07, §3; a secção é o
 * `components/crm/ContactosLoja.js`).
 *
 * Blocos numerados, do mais recente para o mais antigo, com a numeração só do servidor. O controlador
 * (`criarContactos`, no molde do `criarAdicionarARota`) fica separado do `criarFicha`. O que aqui fica preso:
 *   - "Adicionar contacto" só com um `hoje` do servidor, e um só bloco de cada vez;
 *   - ao abrir o bloco pede-se outra vez a lista: Guardar espera pela resposta, que atualiza o máximo e, com a data por
 *     mexer, a data; se falhar fica o último `hoje`;
 *   - o resumo vazio e a data fora desativam Guardar, com o motivo no `falta`; sem rede, "Guardar — sem rede";
 *   - nada do que se escreveu se perde num erro, e o `client_uuid` só se repete no reenvio exato;
 *   - o foco, os avisos e a pergunta do Apagar.
 * As listas do servidor leem-se de `backend/crm/dominio/contactos.py`: uma cópia aqui não apanhava uma mudança dele.
 */
import fs from 'fs';
import path from 'path';

import { MENSAGEM_ERRO_INESPERADO, MENSAGEM_SEM_REDE } from './api';
import {
  ALVO_ADICIONAR,
  ALVO_GUARDAR,
  DATA_MINIMA,
  OPCOES_TIPO,
  PERGUNTA_APAGAR,
  RESPOSTA_APAGAR,
  RESUMO_MAXIMO,
  TEXTO_ADICIONAR_CONTACTO,
  TEXTO_A_CARREGAR_CONTACTOS,
  TEXTO_CONTACTO_APAGADO,
  TEXTO_CONTACTO_GUARDADO,
  TEXTO_CORRIGIR_CONTACTO,
  TEXTO_EXEMPLO_RESUMO,
  TEXTO_FALTA_ALTERACOES,
  TEXTO_FALTA_DATA,
  TEXTO_FALTA_RESUMO,
  TEXTO_NOVO_CONTACTO,
  TEXTO_SEM_CONTACTOS,
  TIPOS_CONTACTO,
  TIPO_POR_OMISSAO,
  alvoApagar,
  alvoCorrigir,
  blocoAtualizado,
  blocoDeCorrecao,
  blocoNovo,
  camposDoBloco,
  clientUuidDoEnvio,
  corpoCorrecao,
  criarContactos,
  dataAceite,
  estadoGuardarContacto,
  focoAoFechar,
  linhaDoContacto,
  mudarBloco,
  rotuloNumero,
  rotuloTipo,
} from './contactos';
import { eUuid, novoUuid4 } from './ids';
import { TEXTO_A_GUARDAR, TEXTO_GUARDAR, TEXTO_GUARDAR_SEM_REDE } from './lojaNova';

const RAIZ = path.join(__dirname, '..', '..', '..', '..');
const DOMINIO_PY = path.join(RAIZ, 'backend', 'crm', 'dominio', 'contactos.py');
const SRC = path.join(__dirname, '..', '..');
const COMPONENTE = path.join(SRC, 'components', 'crm', 'ContactosLoja.js');
const PAGINA = path.join(SRC, 'pages', 'crm', 'CrmLoja.js');
const FICHA = path.join(__dirname, 'ficha.js');
const MODULO = path.join(__dirname, 'contactos.js');

const LOJA = '0b6f3c1e-1111-4222-8333-444455556666';
const HOJE = '2026-11-07';
const ONTEM = '2026-11-06';
const UUID_A = '3f1c2d4e-5a6b-4c7d-8e9f-0a1b2c3d4e5f';
const UUID_B = '7a8b9c0d-1e2f-4a3b-9c4d-5e6f7a8b9c0d';
const UUID_C = 'c0ffee00-0000-4000-a000-000000000099';
const C1 = 'aaaaaaaa-0000-4000-8000-000000000001';
const C2 = 'aaaaaaaa-0000-4000-8000-000000000002';

const CONTACTO_MEU = Object.freeze({
  id: C2,
  numero: 2,
  tipo: 'chamada',
  data: '2026-11-05',
  resumo: 'Falámos da amostra.',
  autor: 'Ana Exemplo',
  pode_alterar: true,
  corrigido: true,
});
const CONTACTO_DE_OUTRO = Object.freeze({
  id: C1,
  numero: 1,
  tipo: 'visita',
  data: '2026-10-30',
  resumo: 'Primeira visita.',
  autor: 'Conta removida',
  pode_alterar: false,
  corrigido: false,
});
const RESPOSTA = Object.freeze({ hoje: HOJE, contactos: [CONTACTO_MEU, CONTACTO_DE_OUTRO] });
const SEM_CONTACTOS = Object.freeze({ hoje: HOJE, contactos: [] });

const erroCom = (codigo, mensagem, extra = {}) => ({ codigo, mensagem, ...extra });
const SEM_REDE = erroCom('sem_rede', MENSAGEM_SEM_REDE);

// Uma promessa que o teste resolve ou rejeita quando quiser.
function pendente() {
  let resolver;
  let rejeitar;
  const promessa = new Promise((res, rej) => {
    resolver = res;
    rejeitar = rej;
  });
  return { promessa, resolver, rejeitar };
}

const esperar = async () => {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
};

function redeFalsa(online = true) {
  const ouvintes = new Set();
  return {
    estado: online,
    online() {
      return this.estado;
    },
    aoMudar(ouvinte) {
      ouvintes.add(ouvinte);
      return () => ouvintes.delete(ouvinte);
    },
    mudar(ligado) {
      this.estado = ligado;
      [...ouvintes].forEach((ouvinte) => ouvinte(ligado));
    },
    ouvintes,
  };
}

// Um ecrã com a API falsa: cada chamada à lista responde `lista` e as escritas respondem `RESPOSTA`.
function montar({
  lista = RESPOSTA, api = {}, uuids = [UUID_A, UUID_B, UUID_C], rede = null,
} = {}) {
  const fila = [...uuids];
  const registo = { vistas: [], focos: [], avisos: [] };
  const apiFalsa = {
    listarContactos: jest.fn(async () => lista),
    criarContacto: jest.fn(async () => RESPOSTA),
    alterarContacto: jest.fn(async () => RESPOSTA),
    apagarContacto: jest.fn(async () => RESPOSTA),
    ...api,
  };
  const ecra = criarContactos({
    api: apiFalsa,
    rede,
    lojaId: LOJA,
    novoUuid: jest.fn(() => fila.shift()),
    aoMudarVista: (vista) => registo.vistas.push(vista),
    aoFocar: (alvo) => registo.focos.push(alvo),
    aoAvisar: (texto) => registo.avisos.push(texto),
  });
  return { ecra, api: apiFalsa, ...registo };
}

// Um ecrã já com a lista carregada.
async function pronto(opcoes) {
  const montado = montar(opcoes);
  montado.ecra.iniciar();
  await esperar();
  return montado;
}

// Um ecrã com um bloco de contacto novo aberto, com a lista do abrir já respondida e o resumo escrito.
async function comBlocoNovo(opcoes, resumo = 'Falámos.') {
  const montado = await pronto(opcoes);
  montado.ecra.abrirNovo();
  await esperar();
  if (resumo !== null) montado.ecra.mudarCampo('resumo', resumo);
  return montado;
}

// --- Os dois lados e os textos -------------------------------------------------------------------

describe('os valores são os do servidor', () => {
  const dominio = fs.readFileSync(DOMINIO_PY, 'utf8');

  test('os tipos, numa só linha, pela ordem do servidor', () => {
    const lidos = /^TIPOS_CONTACTO = \(([^)\n]*)\)$/m.exec(dominio);
    expect(lidos).not.toBeNull();
    expect(TIPOS_CONTACTO).toEqual([...lidos[1].matchAll(/"([a-z_]+)"/g)].map(([, tipo]) => tipo));
    expect(fs.readFileSync(MODULO, 'utf8')).toMatch(
      /^export const TIPOS_CONTACTO = Object\.freeze\(\['visita', 'chamada', 'mensagem'\]\);$/m,
    );
  });

  test('a data mais antiga e o tamanho do resumo', () => {
    const data = /^DATA_MINIMA = date\((\d+), (\d+), (\d+)\)$/m.exec(dominio);
    expect(data).not.toBeNull();
    expect(DATA_MINIMA).toBe(`${data[1]}-${data[2].padStart(2, '0')}-${data[3].padStart(2, '0')}`);
    expect(RESUMO_MAXIMO).toBe(Number(/^RESUMO_MAXIMO = (\d+)$/m.exec(dominio)[1]));
  });
});

test('os textos que o desenho fixa', () => {
  expect(TEXTO_A_CARREGAR_CONTACTOS).toBe('A carregar os contactos…');
  expect(TEXTO_ADICIONAR_CONTACTO).toBe('Adicionar contacto');
  expect(TEXTO_EXEMPLO_RESUMO).toBe('O que foi falado e o próximo passo.');
  expect(TEXTO_SEM_CONTACTOS).toBe('Ainda sem contactos. Adicione o primeiro.');
  expect(TEXTO_CONTACTO_GUARDADO).toBe('Contacto guardado');
  expect(TEXTO_CONTACTO_APAGADO).toBe('Contacto apagado');
  expect(PERGUNTA_APAGAR.pergunta).toBe('Apagar este contacto?');
  expect(TIPO_POR_OMISSAO).toBe('visita');
  expect(OPCOES_TIPO.map(({ rotulo }) => rotulo)).toEqual(['Visita', 'Chamada', 'Mensagem']);
});

test('a primeira escolha do Apagar é a que não apaga', () => {
  expect(PERGUNTA_APAGAR.botoes[0].valor).toBeNull();
  expect(PERGUNTA_APAGAR.botoes[1].valor).toBe(RESPOSTA_APAGAR);
});

// --- Funções puras -------------------------------------------------------------------------------

describe('o que cada contacto mostra', () => {
  test('o número, a data, o tipo, o resumo, quem o escreveu e o "corrigido"', () => {
    expect(linhaDoContacto(CONTACTO_MEU)).toEqual({
      id: C2,
      titulo: '2.º contacto',
      data: '5 nov 2026',
      tipo: 'Chamada',
      resumo: 'Falámos da amostra.',
      autor: 'Ana Exemplo',
      corrigido: true,
      podeAlterar: true,
    });
  });

  test('só `true` conta no "corrigido" e no `pode_alterar`', () => {
    const linha = linhaDoContacto({ ...CONTACTO_MEU, corrigido: 'sim', pode_alterar: 1 });
    expect(linha.corrigido).toBe(false);
    expect(linha.podeAlterar).toBe(false);
  });

  test('uma data ou um tipo inesperados escrevem-se como vieram, e o resumo em falta fica vazio', () => {
    const linha = linhaDoContacto({ ...CONTACTO_MEU, data: 'x', tipo: 'amostra', resumo: null, autor: null });
    expect(linha).toMatchObject({
      data: 'x', tipo: 'amostra', resumo: '', autor: '',
    });
  });

  test('rotuloNumero e rotuloTipo', () => {
    expect(rotuloNumero(3)).toBe('3.º contacto');
    expect(rotuloNumero(12)).toBe('12.º contacto');
    expect(TIPOS_CONTACTO.map(rotuloTipo)).toEqual(['Visita', 'Chamada', 'Mensagem']);
    expect(rotuloTipo(undefined)).toBe('');
  });
});

describe('dataAceite', () => {
  test.each([
    [HOJE, true],
    [ONTEM, true],
    ['2000-01-01', true],
    ['1999-12-31', false],
    ['2026-11-08', false],
    ['2026-02-30', false],
    ['', false],
    [null, false],
  ])('%j → %j', (data, esperado) => {
    expect(dataAceite(data, HOJE)).toBe(esperado);
  });

  test('sem um hoje válido nada se aceita', () => {
    expect(dataAceite(ONTEM, null)).toBe(false);
  });
});

describe('o bloco', () => {
  const novo = () => blocoNovo({ hoje: HOJE, clientUuid: UUID_A });
  const aCorrigir = () => blocoDeCorrecao(CONTACTO_MEU);

  test('um contacto novo abre com hoje, Visita, o resumo vazio e o `client_uuid` dele', () => {
    expect(novo()).toMatchObject({
      modo: 'novo',
      origem: ALVO_ADICIONAR,
      data: HOJE,
      tipo: 'visita',
      resumo: '',
      clientUuid: UUID_A,
      ultimoEnvio: null,
      aAtualizar: true,
    });
  });

  test('"Corrigir" abre com o que o contacto tem e volta ao botão dele', () => {
    expect(aCorrigir()).toMatchObject({
      modo: 'corrigir',
      origem: alvoCorrigir(C2),
      contactoId: C2,
      data: '2026-11-05',
      tipo: 'chamada',
      resumo: 'Falámos da amostra.',
    });
  });

  test('mudar um campo tira o erro dele e a mensagem, e deixa os outros erros', () => {
    const comErros = {
      ...novo(), erros: { data: 'x', resumo: 'y' }, alerta: 'z',
    };
    const mudado = mudarBloco(comErros, 'resumo', 'Texto');
    expect(mudado).toMatchObject({ resumo: 'Texto', erros: { data: 'x' }, alerta: null });
    expect(mudado.erros).not.toHaveProperty('resumo');
  });

  test('só mexer na data conta como "mexeu na data"', () => {
    expect(mudarBloco(novo(), 'resumo', 'x').dataMexida).toBe(false);
    expect(mudarBloco(novo(), 'tipo', 'chamada').dataMexida).toBe(false);
    expect(mudarBloco(novo(), 'data', ONTEM).dataMexida).toBe(true);
    expect(mudarBloco(mudarBloco(novo(), 'data', ONTEM), 'tipo', 'chamada').dataMexida).toBe(true);
  });

  test('o que não serve ou não muda devolve o mesmo bloco', () => {
    const bloco = novo();
    expect(mudarBloco(bloco, 'tipo', 'amostra')).toBe(bloco);
    expect(mudarBloco(bloco, 'tipo', 'visita')).toBe(bloco);
    expect(mudarBloco(bloco, 'resumo', null)).toBe(bloco);
    expect(mudarBloco(bloco, 'clientUuid', UUID_B)).toBe(bloco);
  });

  test('a resposta ao abrir põe a data de hoje só num contacto novo com a data por mexer', () => {
    const NOVO_HOJE = '2026-11-08';
    expect(blocoAtualizado(novo(), NOVO_HOJE)).toMatchObject({ data: NOVO_HOJE, aAtualizar: false });
    const mexida = mudarBloco(novo(), 'data', ONTEM);
    expect(blocoAtualizado(mexida, NOVO_HOJE)).toMatchObject({ data: ONTEM, aAtualizar: false });
    expect(blocoAtualizado(aCorrigir(), NOVO_HOJE)).toMatchObject({ data: '2026-11-05', aAtualizar: false });
  });

  test('os campos vão com o resumo aparado', () => {
    expect(camposDoBloco({ ...novo(), resumo: '  Falámos.\n' })).toEqual({ data: HOJE, tipo: 'visita', resumo: 'Falámos.' });
  });

  test('o corpo do PATCH leva só o que mudou', () => {
    expect(corpoCorrecao(aCorrigir())).toEqual({});
    expect(corpoCorrecao(mudarBloco(aCorrigir(), 'tipo', 'mensagem'))).toEqual({ tipo: 'mensagem' });
    expect(corpoCorrecao(mudarBloco(aCorrigir(), 'data', ONTEM))).toEqual({ data: ONTEM });
    expect(corpoCorrecao(mudarBloco(aCorrigir(), 'resumo', 'Novo.'))).toEqual({ resumo: 'Novo.' });
    // Espaços nas pontas não são uma mudança: o servidor apara.
    expect(corpoCorrecao(mudarBloco(aCorrigir(), 'resumo', ' Falámos da amostra. '))).toEqual({});
  });
});

describe('clientUuidDoEnvio', () => {
  const campos = { data: HOJE, tipo: 'visita', resumo: 'Falámos.' };
  const novoUuid = () => UUID_B;

  test('o primeiro envio usa o do bloco', () => {
    expect(clientUuidDoEnvio({ clientUuid: UUID_A, ultimoEnvio: null }, campos, novoUuid)).toBe(UUID_A);
  });

  test('o reenvio exato usa o mesmo', () => {
    expect(clientUuidDoEnvio({ clientUuid: UUID_A, ultimoEnvio: { ...campos } }, campos, novoUuid)).toBe(UUID_A);
  });

  test.each([
    ['o tipo', { tipo: 'chamada' }],
    ['a data', { data: ONTEM }],
    ['o resumo', { resumo: 'Outra coisa.' }],
  ])('com %s diferente, vai um novo', (_nome, mudanca) => {
    const bloco = { clientUuid: UUID_A, ultimoEnvio: { ...campos } };
    expect(clientUuidDoEnvio(bloco, { ...campos, ...mudanca }, novoUuid)).toBe(UUID_B);
  });
});

describe('estadoGuardarContacto', () => {
  const base = {
    aGuardar: false, online: true, aAtualizar: false, resumo: 'Falámos.', data: HOJE, hoje: HOJE, alterado: true,
  };

  test('tudo certo: ativo', () => {
    expect(estadoGuardarContacto(base)).toEqual({ ativo: true, texto: TEXTO_GUARDAR, falta: null });
  });

  test('a gravar: "A guardar…", desativado', () => {
    expect(estadoGuardarContacto({ ...base, aGuardar: true })).toEqual({ ativo: false, texto: TEXTO_A_GUARDAR, falta: null });
  });

  test('sem rede: "Guardar — sem rede", como na ficha', () => {
    expect(TEXTO_GUARDAR_SEM_REDE).toBe('Guardar — sem rede');
    expect(estadoGuardarContacto({ ...base, online: false })).toEqual({
      ativo: false, texto: TEXTO_GUARDAR_SEM_REDE, falta: null,
    });
  });

  test.each([[''], ['   \n'], [null]])('com o resumo %j, desativado e com o motivo', (resumo) => {
    expect(estadoGuardarContacto({ ...base, resumo })).toEqual({ ativo: false, texto: TEXTO_GUARDAR, falta: TEXTO_FALTA_RESUMO });
  });

  test.each([[''], ['2026-11-08'], ['1999-12-31']])('com a data %j, desativado e com o motivo', (data) => {
    expect(estadoGuardarContacto({ ...base, data })).toEqual({ ativo: false, texto: TEXTO_GUARDAR, falta: TEXTO_FALTA_DATA });
  });

  test('à espera da lista pedida ao abrir: desativado, sem motivo à vista', () => {
    expect(estadoGuardarContacto({ ...base, aAtualizar: true })).toEqual({ ativo: false, texto: TEXTO_GUARDAR, falta: null });
  });

  test('o resumo vazio conta antes da espera: o motivo aparece logo ao abrir', () => {
    expect(estadoGuardarContacto({ ...base, aAtualizar: true, resumo: '' }).falta).toBe(TEXTO_FALTA_RESUMO);
  });

  test('a corrigir sem nada mudado: desativado e com o motivo', () => {
    expect(estadoGuardarContacto({ ...base, alterado: false })).toEqual({
      ativo: false, texto: TEXTO_GUARDAR, falta: TEXTO_FALTA_ALTERACOES,
    });
  });
});

describe('focoAoFechar', () => {
  test('volta ao botão que o abriu', () => {
    expect(focoAoFechar(alvoCorrigir(C2), [CONTACTO_MEU])).toBe(alvoCorrigir(C2));
    expect(focoAoFechar(ALVO_ADICIONAR, [CONTACTO_MEU])).toBe(ALVO_ADICIONAR);
  });

  test('sem esse botão, "Adicionar contacto": o contacto saiu da lista ou já não se pode alterar', () => {
    expect(focoAoFechar(alvoCorrigir(C2), [CONTACTO_DE_OUTRO])).toBe(ALVO_ADICIONAR);
    expect(focoAoFechar(alvoCorrigir(C1), [CONTACTO_DE_OUTRO])).toBe(ALVO_ADICIONAR);
  });
});

// --- Ecrã ----------------------------------------------------------------------------------------

describe('criarContactos — carregar', () => {
  test('sem a loja é um engano no código', () => {
    expect(() => criarContactos({})).toThrow(TypeError);
  });

  test('criar não pede nada e já tem vista: "a carregar", com "Adicionar contacto" desativado', () => {
    const { ecra, api } = montar();
    expect(api.listarContactos).not.toHaveBeenCalled();
    expect(ecra.vista).toMatchObject({
      estado: 'a_carregar', falha: null, semContactos: false, adicionar: { ativo: false }, bloco: null,
    });
    expect(ecra.vista.linhas).toEqual([]);
  });

  test('a lista chega: o mais recente em cima, como veio, e "Adicionar contacto" ativo', async () => {
    const { ecra, api } = await pronto();
    expect(api.listarContactos.mock.calls).toEqual([[LOJA]]);
    expect(ecra.vista).toMatchObject({ estado: 'pronto', adicionar: { ativo: true }, semContactos: false, acoesAtivas: true });
    expect(ecra.vista.linhas.map(({ titulo }) => titulo)).toEqual(['2.º contacto', '1.º contacto']);
  });

  test('a vista é congelada a fundo', async () => {
    const { ecra } = await comBlocoNovo();
    expect(Object.isFrozen(ecra.vista)).toBe(true);
    expect(Object.isFrozen(ecra.vista.linhas)).toBe(true);
    expect(Object.isFrozen(ecra.vista.linhas[0])).toBe(true);
    expect(Object.isFrozen(ecra.vista.adicionar)).toBe(true);
    expect(Object.isFrozen(ecra.vista.bloco)).toBe(true);
    expect(Object.isFrozen(ecra.vista.bloco.erros)).toBe(true);
    expect(Object.isFrozen(ecra.vista.bloco.guardar)).toBe(true);
  });

  test('sem contactos: `semContactos`, e dá para adicionar', async () => {
    const { ecra } = await pronto({ lista: SEM_CONTACTOS });
    expect(ecra.vista).toMatchObject({ semContactos: true, adicionar: { ativo: true } });
  });

  test('linhas sem id ou sem número ficam de fora', async () => {
    const lista = { hoje: HOJE, contactos: [CONTACTO_MEU, null, { id: C1 }, { numero: 1 }] };
    const { ecra } = await pronto({ lista });
    expect(ecra.vista.linhas.map(({ id }) => id)).toEqual([C2]);
  });

  test('uma falha só mostra o erro nesta secção, com "Tentar novamente", e "Adicionar contacto" fica desativado', async () => {
    const { ecra } = await pronto({ api: { listarContactos: jest.fn(async () => { throw SEM_REDE; }) } });
    expect(ecra.vista).toMatchObject({
      estado: 'falha', falha: { mensagem: MENSAGEM_SEM_REDE, aTentar: false }, adicionar: { ativo: false },
    });
  });

  test('uma resposta sem `hoje` válido conta como falha', async () => {
    const { ecra } = await pronto({ lista: { hoje: 'ontem', contactos: [] } });
    expect(ecra.vista).toMatchObject({ estado: 'falha', falha: { mensagem: MENSAGEM_ERRO_INESPERADO } });
  });

  test('"Tentar novamente" pede outra vez; dois toques, um pedido', async () => {
    const pedido = pendente();
    const listarContactos = jest.fn()
      .mockRejectedValueOnce(SEM_REDE)
      .mockReturnValueOnce(pedido.promessa);
    const { ecra } = await pronto({ api: { listarContactos } });
    ecra.tentarDeNovo();
    ecra.tentarDeNovo();
    expect(listarContactos).toHaveBeenCalledTimes(2);
    expect(ecra.vista.falha.aTentar).toBe(true);
    pedido.resolver(RESPOSTA);
    await esperar();
    expect(ecra.vista).toMatchObject({ estado: 'pronto', falha: null });
  });

  test('"Tentar novamente" sem falha não faz nada', async () => {
    const { ecra, api } = await pronto();
    ecra.tentarDeNovo();
    expect(api.listarContactos).toHaveBeenCalledTimes(1);
  });

  test('a rede que volta pede a lista que falhou', async () => {
    const rede = redeFalsa(false);
    const listarContactos = jest.fn().mockRejectedValueOnce(SEM_REDE).mockResolvedValue(RESPOSTA);
    const { ecra } = await pronto({ rede, api: { listarContactos } });
    expect(ecra.vista.estado).toBe('falha');
    rede.mudar(true);
    await esperar();
    expect(listarContactos).toHaveBeenCalledTimes(2);
    expect(ecra.vista.estado).toBe('pronto');
  });

  test('a rede que volta não pede nada sem falha', async () => {
    const rede = redeFalsa(true);
    const { api } = await pronto({ rede });
    rede.mudar(false);
    rede.mudar(true);
    await esperar();
    expect(api.listarContactos).toHaveBeenCalledTimes(1);
  });

  test('`iniciar` duas vezes pede uma', async () => {
    const { ecra, api } = montar();
    ecra.iniciar();
    ecra.iniciar();
    await esperar();
    expect(api.listarContactos).toHaveBeenCalledTimes(1);
  });

  test('depois de `destruir`, as respostas e a rede não mexem em nada', async () => {
    const rede = redeFalsa();
    const pedido = pendente();
    const { ecra, vistas } = montar({ rede, api: { listarContactos: jest.fn(() => pedido.promessa) } });
    ecra.iniciar();
    ecra.destruir();
    const contagem = vistas.length;
    pedido.resolver(RESPOSTA);
    await esperar();
    rede.mudar(false);
    expect(vistas).toHaveLength(contagem);
    expect(rede.ouvintes.size).toBe(0);
  });
});

describe('criarContactos — abrir o bloco', () => {
  test('"Adicionar contacto" abre com o último hoje, Visita, e vai para o resumo', async () => {
    const { ecra, focos } = await pronto();
    ecra.abrirNovo();
    expect(ecra.vista.bloco).toMatchObject({
      modo: 'novo',
      titulo: TEXTO_NOVO_CONTACTO,
      data: HOJE,
      min: DATA_MINIMA,
      max: HOJE,
      tipo: 'visita',
      resumo: '',
      camposDesativados: false,
    });
    expect(ecra.vista.bloco.opcoesTipo).toBe(OPCOES_TIPO);
    expect(focos).toEqual(['resumo']);
  });

  test('um bloco de cada vez: "Adicionar contacto", os "Corrigir" e os "Apagar" ficam desativados', async () => {
    const { ecra, api } = await pronto();
    ecra.abrirNovo();
    expect(ecra.vista).toMatchObject({ adicionar: { ativo: false }, acoesAtivas: false });
    ecra.abrirNovo();
    ecra.abrirCorrecao(C2);
    ecra.pedirApagar(C2);
    expect(ecra.vista.bloco.modo).toBe('novo');
    expect(ecra.vista.apagar).toBeNull();
    expect(api.listarContactos).toHaveBeenCalledTimes(2);
  });

  test('sem hoje do servidor não abre', () => {
    const { ecra, api } = montar();
    ecra.abrirNovo();
    expect(ecra.vista.bloco).toBeNull();
    expect(api.listarContactos).not.toHaveBeenCalled();
  });

  test('ao abrir pede-se outra vez a lista, e Guardar fica desativado até à resposta', async () => {
    const pedido = pendente();
    const listarContactos = jest.fn().mockResolvedValueOnce(RESPOSTA).mockReturnValueOnce(pedido.promessa);
    const { ecra } = await pronto({ api: { listarContactos } });
    ecra.abrirNovo();
    ecra.mudarCampo('resumo', 'Falámos.');
    expect(listarContactos).toHaveBeenCalledTimes(2);
    expect(ecra.vista.bloco.guardar).toEqual({ ativo: false, texto: TEXTO_GUARDAR, falta: null });
    pedido.resolver(RESPOSTA);
    await esperar();
    expect(ecra.vista.bloco.guardar.ativo).toBe(true);
  });

  test('a resposta atualiza o máximo e, com a data por mexer, a data, e a lista', async () => {
    const AMANHA = '2026-11-08';
    const pedido = pendente();
    const listarContactos = jest.fn().mockResolvedValueOnce(RESPOSTA).mockReturnValueOnce(pedido.promessa);
    const { ecra } = await pronto({ api: { listarContactos } });
    ecra.abrirNovo();
    expect(ecra.vista.bloco).toMatchObject({ data: HOJE, max: HOJE });
    pedido.resolver({ hoje: AMANHA, contactos: [CONTACTO_DE_OUTRO] });
    await esperar();
    expect(ecra.vista.bloco).toMatchObject({ data: AMANHA, max: AMANHA });
    expect(ecra.vista.linhas.map(({ id }) => id)).toEqual([C1]);
  });

  test('a data mexida fica, e o máximo atualiza-se na mesma', async () => {
    const AMANHA = '2026-11-08';
    const pedido = pendente();
    const listarContactos = jest.fn().mockResolvedValueOnce(RESPOSTA).mockReturnValueOnce(pedido.promessa);
    const { ecra } = await pronto({ api: { listarContactos } });
    ecra.abrirNovo();
    ecra.mudarCampo('data', ONTEM);
    pedido.resolver({ hoje: AMANHA, contactos: [] });
    await esperar();
    expect(ecra.vista.bloco).toMatchObject({ data: ONTEM, max: AMANHA });
  });

  test.each([
    ['falhar', () => Promise.reject(SEM_REDE)],
    ['vier sem a forma certa', () => Promise.resolve({ hoje: null })],
  ])('se o pedido %s, fica o último hoje e Guardar volta a ativo', async (_nome, responder) => {
    const listarContactos = jest.fn().mockResolvedValueOnce(RESPOSTA).mockImplementationOnce(responder);
    const { ecra } = await pronto({ api: { listarContactos } });
    ecra.abrirNovo();
    ecra.mudarCampo('resumo', 'Falámos.');
    await esperar();
    expect(ecra.vista.bloco).toMatchObject({ data: HOJE, max: HOJE, guardar: { ativo: true } });
    expect(ecra.vista.linhas).toHaveLength(2);
  });

  test('fechar e voltar a abrir: só a resposta do último pedido conta', async () => {
    const primeiro = pendente();
    const segundo = pendente();
    const listarContactos = jest.fn()
      .mockResolvedValueOnce(RESPOSTA)
      .mockReturnValueOnce(primeiro.promessa)
      .mockReturnValueOnce(segundo.promessa);
    const { ecra } = await pronto({ api: { listarContactos } });
    ecra.abrirNovo();
    ecra.cancelar();
    ecra.abrirNovo();
    ecra.mudarCampo('resumo', 'Falámos.');
    primeiro.resolver({ hoje: '2026-11-08', contactos: [] });
    await esperar();
    expect(ecra.vista.linhas).toHaveLength(2);
    expect(ecra.vista.bloco).toMatchObject({ data: HOJE, guardar: { ativo: false } });
    segundo.resolver(RESPOSTA);
    await esperar();
    expect(ecra.vista.bloco.guardar.ativo).toBe(true);
  });

  test('uma lista pedida antes de apagar não desfaz o que a escrita devolveu', async () => {
    const lenta = pendente();
    const listarContactos = jest.fn().mockResolvedValueOnce(RESPOSTA).mockReturnValueOnce(lenta.promessa);
    const apagarContacto = jest.fn(async () => ({ hoje: HOJE, contactos: [CONTACTO_DE_OUTRO] }));
    const { ecra } = await pronto({ api: { listarContactos, apagarContacto } });
    ecra.abrirNovo();
    ecra.cancelar();
    ecra.pedirApagar(C2);
    ecra.responderApagar(RESPOSTA_APAGAR);
    await esperar();
    lenta.resolver(RESPOSTA);
    await esperar();
    expect(ecra.vista.linhas.map(({ id }) => id)).toEqual([C1]);
  });

  test('"Corrigir" abre com o contacto, vai para o resumo e pede a lista; a resposta não lhe muda a data', async () => {
    const AMANHA = '2026-11-08';
    const listarContactos = jest.fn()
      .mockResolvedValueOnce(RESPOSTA)
      .mockResolvedValueOnce({ hoje: AMANHA, contactos: RESPOSTA.contactos });
    const { ecra, focos } = await pronto({ api: { listarContactos } });
    ecra.abrirCorrecao(C2);
    expect(ecra.vista.bloco).toMatchObject({
      modo: 'corrigir', titulo: 'Corrigir o 2.º contacto', data: '2026-11-05', tipo: 'chamada', resumo: 'Falámos da amostra.',
    });
    expect(focos).toEqual(['resumo']);
    await esperar();
    expect(listarContactos).toHaveBeenCalledTimes(2);
    expect(ecra.vista.bloco).toMatchObject({ data: '2026-11-05', max: AMANHA });
  });

  test('o título segue o número que o servidor deu', async () => {
    const listarContactos = jest.fn()
      .mockResolvedValueOnce(RESPOSTA)
      .mockResolvedValueOnce({ hoje: HOJE, contactos: [{ ...CONTACTO_MEU, numero: 3 }] });
    const { ecra } = await pronto({ api: { listarContactos } });
    ecra.abrirCorrecao(C2);
    expect(ecra.vista.bloco.titulo).toBe('Corrigir o 2.º contacto');
    await esperar();
    expect(ecra.vista.bloco.titulo).toBe('Corrigir o 3.º contacto');
  });

  test('o contacto sai da lista com o bloco aberto: o bloco fica, com o que se escreveu', async () => {
    const listarContactos = jest.fn()
      .mockResolvedValueOnce(RESPOSTA)
      .mockResolvedValueOnce({ hoje: HOJE, contactos: [] });
    const { ecra } = await pronto({ api: { listarContactos } });
    ecra.abrirCorrecao(C2);
    ecra.mudarCampo('resumo', 'O que escrevi.');
    await esperar();
    expect(ecra.vista.bloco).toMatchObject({ titulo: TEXTO_CORRIGIR_CONTACTO, resumo: 'O que escrevi.' });
  });

  test('um contacto de outra pessoa ou que não existe não abre', async () => {
    const { ecra, api } = await pronto();
    ecra.abrirCorrecao(C1);
    ecra.abrirCorrecao('nao-existe');
    expect(ecra.vista.bloco).toBeNull();
    expect(api.listarContactos).toHaveBeenCalledTimes(1);
  });

  test('cancelar fecha e volta ao botão que o abriu', async () => {
    const { ecra, focos } = await comBlocoNovo();
    ecra.cancelar();
    expect(ecra.vista.bloco).toBeNull();
    expect(ecra.vista).toMatchObject({ adicionar: { ativo: true }, acoesAtivas: true });
    expect(focos).toEqual(['resumo', ALVO_ADICIONAR]);
  });

  test('cancelar uma correção volta ao "Corrigir" dela', async () => {
    const { ecra, focos } = await pronto();
    ecra.abrirCorrecao(C2);
    await esperar();
    ecra.cancelar();
    expect(focos).toEqual(['resumo', alvoCorrigir(C2)]);
  });

  test('cancelar com o contacto fora da lista vai para "Adicionar contacto"', async () => {
    const listarContactos = jest.fn()
      .mockResolvedValueOnce(RESPOSTA)
      .mockResolvedValueOnce({ hoje: HOJE, contactos: [CONTACTO_DE_OUTRO] });
    const { ecra, focos } = await pronto({ api: { listarContactos } });
    ecra.abrirCorrecao(C2);
    await esperar();
    ecra.cancelar();
    expect(focos).toEqual(['resumo', ALVO_ADICIONAR]);
  });
});

describe('criarContactos — Guardar', () => {
  test('com o resumo vazio fica desativado, com o motivo, e guardar não envia', async () => {
    const { ecra, api } = await comBlocoNovo({}, null);
    expect(ecra.vista.bloco.guardar).toEqual({ ativo: false, texto: TEXTO_GUARDAR, falta: TEXTO_FALTA_RESUMO });
    await ecra.guardar();
    expect(api.criarContacto).not.toHaveBeenCalled();
  });

  test('a data futura escrita à mão fica desativada, com o motivo', async () => {
    const { ecra, api } = await comBlocoNovo();
    ecra.mudarCampo('data', '2026-11-08');
    expect(ecra.vista.bloco.guardar).toEqual({ ativo: false, texto: TEXTO_GUARDAR, falta: TEXTO_FALTA_DATA });
    await ecra.guardar();
    expect(api.criarContacto).not.toHaveBeenCalled();
  });

  test('sem rede, "Guardar — sem rede"; a rede que volta ativa-o', async () => {
    const rede = redeFalsa(true);
    const { ecra } = await comBlocoNovo({ rede });
    rede.mudar(false);
    expect(ecra.vista.bloco.guardar).toEqual({ ativo: false, texto: TEXTO_GUARDAR_SEM_REDE, falta: null });
    rede.mudar(true);
    expect(ecra.vista.bloco.guardar).toEqual({ ativo: true, texto: TEXTO_GUARDAR, falta: null });
  });

  test('guardar envia o tipo, a data, o resumo aparado e o `client_uuid` do bloco', async () => {
    const { ecra, api } = await comBlocoNovo({}, '  Falámos.  ');
    ecra.mudarCampo('tipo', 'mensagem');
    ecra.mudarCampo('data', ONTEM);
    await ecra.guardar();
    expect(api.criarContacto.mock.calls).toEqual([[LOJA, {
      data: ONTEM, tipo: 'mensagem', resumo: 'Falámos.', client_uuid: UUID_A,
    }]]);
  });

  test('o `client_uuid` que o ecrã manda é um uuid4 que o servidor aceita', async () => {
    const criarContacto = jest.fn(async () => RESPOSTA);
    const registo = [];
    const ecra = criarContactos({
      api: { listarContactos: async () => RESPOSTA, criarContacto },
      lojaId: LOJA,
      novoUuid: novoUuid4,
      aoFocar: (alvo) => registo.push(alvo),
    });
    ecra.iniciar();
    await esperar();
    ecra.abrirNovo();
    await esperar();
    ecra.mudarCampo('resumo', 'Falámos.');
    await ecra.guardar();
    expect(eUuid(criarContacto.mock.calls[0][1].client_uuid)).toBe(true);
  });

  test('com sucesso: a lista da resposta, o bloco fecha, o aviso e o foco no botão que o abriu', async () => {
    const criarContacto = jest.fn(async () => ({ hoje: HOJE, contactos: [{ ...CONTACTO_MEU, numero: 3 }, CONTACTO_DE_OUTRO] }));
    const { ecra, avisos, focos } = await comBlocoNovo({ api: { criarContacto } });
    await ecra.guardar();
    expect(ecra.vista.bloco).toBeNull();
    expect(ecra.vista.linhas[0].titulo).toBe('3.º contacto');
    expect(avisos).toEqual([TEXTO_CONTACTO_GUARDADO]);
    expect(focos).toEqual(['resumo', ALVO_ADICIONAR]);
  });

  test('enquanto grava: "A guardar…", campos e cancelar parados, um pedido só', async () => {
    const pedido = pendente();
    const criarContacto = jest.fn(() => pedido.promessa);
    const { ecra } = await comBlocoNovo({ api: { criarContacto } });
    ecra.guardar();
    expect(ecra.vista.bloco).toMatchObject({
      camposDesativados: true, guardar: { ativo: false, texto: TEXTO_A_GUARDAR },
    });
    ecra.guardar();
    ecra.mudarCampo('resumo', 'Outra coisa.');
    ecra.cancelar();
    expect(criarContacto).toHaveBeenCalledTimes(1);
    expect(ecra.vista.bloco.resumo).toBe('Falámos.');
    pedido.resolver(RESPOSTA);
    await esperar();
    expect(ecra.vista.bloco).toBeNull();
  });

  test('"Corrigir" envia só o que mudou, volta ao botão dele e não leva `client_uuid`', async () => {
    const { ecra, api, focos, avisos } = await pronto();
    ecra.abrirCorrecao(C2);
    await esperar();
    ecra.mudarCampo('resumo', 'Falámos da amostra e do preço.');
    await ecra.guardar();
    expect(api.alterarContacto.mock.calls).toEqual([[LOJA, C2, { resumo: 'Falámos da amostra e do preço.' }]]);
    expect(api.criarContacto).not.toHaveBeenCalled();
    expect(ecra.vista.bloco).toBeNull();
    expect(avisos).toEqual([TEXTO_CONTACTO_GUARDADO]);
    expect(focos).toEqual(['resumo', alvoCorrigir(C2)]);
  });

  test('"Corrigir" sem nada mudado fica desativado, com o motivo', async () => {
    const { ecra, api } = await pronto();
    ecra.abrirCorrecao(C2);
    await esperar();
    expect(ecra.vista.bloco.guardar).toEqual({ ativo: false, texto: TEXTO_GUARDAR, falta: TEXTO_FALTA_ALTERACOES });
    await ecra.guardar();
    expect(api.alterarContacto).not.toHaveBeenCalled();
  });

  test('corrigido e já sem poder alterar: o foco vai para "Adicionar contacto"', async () => {
    const alterarContacto = jest.fn(async () => ({ hoje: HOJE, contactos: [{ ...CONTACTO_MEU, pode_alterar: false }] }));
    const { ecra, focos } = await pronto({ api: { alterarContacto } });
    ecra.abrirCorrecao(C2);
    await esperar();
    ecra.mudarCampo('tipo', 'visita');
    await ecra.guardar();
    expect(focos).toEqual(['resumo', ALVO_ADICIONAR]);
  });
});

describe('criarContactos — nada do que se escreveu se perde num erro', () => {
  const FALHA = erroCom('erro_interno', MENSAGEM_ERRO_INESPERADO);

  test('o bloco fica aberto com o texto e a mensagem, e o foco em Guardar', async () => {
    const criarContacto = jest.fn(async () => { throw FALHA; });
    const { ecra, focos, avisos } = await comBlocoNovo({ api: { criarContacto } });
    await ecra.guardar();
    expect(ecra.vista.bloco).toMatchObject({
      resumo: 'Falámos.', alerta: MENSAGEM_ERRO_INESPERADO, camposDesativados: false, guardar: { ativo: true, texto: TEXTO_GUARDAR },
    });
    expect(avisos).toEqual([]);
    expect(focos).toEqual(['resumo', ALVO_GUARDAR]);
  });

  test('a falha com a rede em baixo: o foco vai para o resumo, porque Guardar fica desativado', async () => {
    const rede = redeFalsa(true);
    const criarContacto = jest.fn(async () => {
      rede.estado = false;
      throw SEM_REDE;
    });
    const { ecra, focos } = await comBlocoNovo({ rede, api: { criarContacto } });
    await ecra.guardar();
    expect(ecra.vista.bloco).toMatchObject({
      alerta: MENSAGEM_SEM_REDE, guardar: { ativo: false, texto: TEXTO_GUARDAR_SEM_REDE },
    });
    expect(focos).toEqual(['resumo', 'resumo']);
  });

  test('o reenvio exato usa o mesmo `client_uuid`', async () => {
    const criarContacto = jest.fn().mockRejectedValueOnce(FALHA).mockResolvedValueOnce(RESPOSTA);
    const { ecra } = await comBlocoNovo({ api: { criarContacto } });
    await ecra.guardar();
    await ecra.guardar();
    const [primeiro, segundo] = criarContacto.mock.calls.map(([, corpo]) => corpo);
    expect(primeiro.client_uuid).toBe(UUID_A);
    expect(segundo).toEqual(primeiro);
  });

  test.each([
    ['o tipo', 'tipo', 'chamada'],
    ['a data', 'data', ONTEM],
    ['o resumo', 'resumo', 'Falámos da amostra.'],
  ])('mudar %s depois de uma falha gera um `client_uuid` novo', async (_nome, campo, valor) => {
    const criarContacto = jest.fn().mockRejectedValueOnce(FALHA).mockResolvedValueOnce(RESPOSTA);
    const { ecra } = await comBlocoNovo({ api: { criarContacto } });
    await ecra.guardar();
    ecra.mudarCampo(campo, valor);
    await ecra.guardar();
    const [primeiro, segundo] = criarContacto.mock.calls.map(([, corpo]) => corpo);
    expect(primeiro.client_uuid).toBe(UUID_A);
    expect(segundo.client_uuid).toBe(UUID_B);
    expect(segundo[campo]).toBe(valor);
  });

  test('o `client_uuid` novo é o que fica: outra falha com o mesmo texto repete-o', async () => {
    const criarContacto = jest.fn()
      .mockRejectedValueOnce(FALHA)
      .mockRejectedValueOnce(FALHA)
      .mockResolvedValueOnce(RESPOSTA);
    const { ecra } = await comBlocoNovo({ api: { criarContacto } });
    await ecra.guardar();
    ecra.mudarCampo('resumo', 'Outra coisa.');
    await ecra.guardar();
    await ecra.guardar();
    expect(criarContacto.mock.calls.map(([, corpo]) => corpo.client_uuid)).toEqual([UUID_A, UUID_B, UUID_B]);
  });

  test('mudar e voltar ao que falhou é o reenvio exato: fica o mesmo', async () => {
    const criarContacto = jest.fn().mockRejectedValueOnce(FALHA).mockResolvedValueOnce(RESPOSTA);
    const { ecra } = await comBlocoNovo({ api: { criarContacto } });
    await ecra.guardar();
    ecra.mudarCampo('tipo', 'chamada');
    ecra.mudarCampo('tipo', 'visita');
    await ecra.guardar();
    expect(criarContacto.mock.calls.map(([, corpo]) => corpo.client_uuid)).toEqual([UUID_A, UUID_A]);
  });

  test('cada bloco aberto tem o seu `client_uuid`', async () => {
    const { ecra, api } = await comBlocoNovo();
    await ecra.guardar();
    ecra.abrirNovo();
    await esperar();
    ecra.mudarCampo('resumo', 'Falámos.');
    await ecra.guardar();
    expect(api.criarContacto.mock.calls.map(([, corpo]) => corpo.client_uuid)).toEqual([UUID_A, UUID_B]);
  });

  test('mudar um campo depois da falha tira a mensagem', async () => {
    const criarContacto = jest.fn(async () => { throw FALHA; });
    const { ecra } = await comBlocoNovo({ api: { criarContacto } });
    await ecra.guardar();
    ecra.mudarCampo('resumo', 'Outra coisa.');
    expect(ecra.vista.bloco.alerta).toBeNull();
  });

  test('o 422 fica junto ao campo, com o foco no primeiro que tiver erro', async () => {
    const criarContacto = jest.fn(async () => {
      throw erroCom('validacao', 'Verifique os campos assinalados.', {
        campos: { resumo: 'O resumo tem no máximo 5000 caracteres.', data: 'Escolha um dia entre 1 de janeiro de 2000 e hoje.' },
      });
    });
    const { ecra, focos } = await comBlocoNovo({ api: { criarContacto } });
    await ecra.guardar();
    expect(ecra.vista.bloco.erros).toEqual({
      data: 'Escolha um dia entre 1 de janeiro de 2000 e hoje.', resumo: 'O resumo tem no máximo 5000 caracteres.',
    });
    expect(ecra.vista.bloco).toMatchObject({ alerta: null, resumo: 'Falámos.' });
    expect(focos).toEqual(['resumo', 'data']);
  });

  test('o 422 de um campo que não está no bloco (o `client_uuid`) é a mensagem do bloco', async () => {
    const criarContacto = jest.fn(async () => {
      throw erroCom('validacao', 'Verifique os campos assinalados.', { campos: { client_uuid: 'Este identificador já foi usado noutra loja.' } });
    });
    const { ecra } = await comBlocoNovo({ api: { criarContacto } });
    await ecra.guardar();
    expect(ecra.vista.bloco.alerta).toBe('Este identificador já foi usado noutra loja.');
  });

  test('"Corrigir" que falha: o bloco fica com o texto e a mensagem do servidor', async () => {
    const alterarContacto = jest.fn(async () => { throw erroCom('nao_encontrado', 'Contacto não encontrado.'); });
    const { ecra } = await pronto({ api: { alterarContacto } });
    ecra.abrirCorrecao(C2);
    await esperar();
    ecra.mudarCampo('resumo', 'O que escrevi.');
    await ecra.guardar();
    expect(ecra.vista.bloco).toMatchObject({ resumo: 'O que escrevi.', alerta: 'Contacto não encontrado.' });
  });

  test('a resposta depois de `destruir` não mexe em nada', async () => {
    const pedido = pendente();
    const { ecra, vistas, avisos, focos } = await comBlocoNovo({ api: { criarContacto: jest.fn(() => pedido.promessa) } });
    ecra.guardar();
    ecra.destruir();
    const contagem = vistas.length;
    const focosAntes = focos.length;
    pedido.resolver(RESPOSTA);
    await esperar();
    expect(vistas).toHaveLength(contagem);
    expect(avisos).toEqual([]);
    expect(focos).toHaveLength(focosAntes);
  });
});

describe('criarContactos — Apagar', () => {
  test('pergunta, com o contacto na descrição', async () => {
    const { ecra, api } = await pronto();
    ecra.pedirApagar(C2);
    expect(ecra.vista.apagar).toMatchObject({
      id: C2,
      descricao: '2.º contacto · 5 nov 2026 · Chamada',
      pergunta: PERGUNTA_APAGAR.pergunta,
      botoes: PERGUNTA_APAGAR.botoes,
    });
    expect(api.apagarContacto).not.toHaveBeenCalled();
  });

  test('um contacto de outra pessoa não pergunta', async () => {
    const { ecra } = await pronto();
    ecra.pedirApagar(C1);
    expect(ecra.vista.apagar).toBeNull();
  });

  test('a escolha que não apaga fecha a pergunta e não pede nada', async () => {
    const { ecra, api, focos } = await pronto();
    ecra.pedirApagar(C2);
    ecra.responderApagar(null);
    expect(ecra.vista.apagar).toBeNull();
    expect(api.apagarContacto).not.toHaveBeenCalled();
    expect(focos).toEqual([]);
  });

  test('"Sim, apagar": a lista da resposta, o aviso e o foco em "Adicionar contacto"', async () => {
    const apagarContacto = jest.fn(async () => ({ hoje: HOJE, contactos: [CONTACTO_DE_OUTRO] }));
    const { ecra, avisos, focos } = await pronto({ api: { apagarContacto } });
    ecra.pedirApagar(C2);
    ecra.responderApagar(RESPOSTA_APAGAR);
    await esperar();
    expect(apagarContacto.mock.calls).toEqual([[LOJA, C2]]);
    expect(ecra.vista.linhas.map(({ id }) => id)).toEqual([C1]);
    expect(avisos).toEqual([TEXTO_CONTACTO_APAGADO]);
    expect(focos).toEqual([ALVO_ADICIONAR]);
    expect(ecra.vista).toMatchObject({ adicionar: { ativo: true }, acoesAtivas: true, alerta: null });
  });

  test('enquanto apaga, tudo fica parado; só a primeira resposta à pergunta conta', async () => {
    const pedido = pendente();
    const apagarContacto = jest.fn(() => pedido.promessa);
    const { ecra } = await pronto({ api: { apagarContacto } });
    ecra.pedirApagar(C2);
    ecra.responderApagar(RESPOSTA_APAGAR);
    ecra.responderApagar(RESPOSTA_APAGAR);
    expect(apagarContacto).toHaveBeenCalledTimes(1);
    expect(ecra.vista).toMatchObject({ adicionar: { ativo: false }, acoesAtivas: false });
    ecra.abrirNovo();
    ecra.abrirCorrecao(C2);
    ecra.pedirApagar(C2);
    expect(ecra.vista.bloco).toBeNull();
    expect(ecra.vista.apagar).toBeNull();
    pedido.resolver(SEM_CONTACTOS);
    await esperar();
    expect(ecra.vista.semContactos).toBe(true);
  });

  test('uma falha mostra a mensagem, o contacto fica e o foco volta ao "Apagar" dele', async () => {
    const apagarContacto = jest.fn(async () => { throw erroCom('sem_permissao', 'Não tem permissão.'); });
    const { ecra, avisos, focos } = await pronto({ api: { apagarContacto } });
    ecra.pedirApagar(C2);
    ecra.responderApagar(RESPOSTA_APAGAR);
    await esperar();
    expect(ecra.vista).toMatchObject({ alerta: 'Não tem permissão.', acoesAtivas: true });
    expect(ecra.vista.linhas).toHaveLength(2);
    expect(avisos).toEqual([]);
    expect(focos).toEqual([alvoApagar(C2)]);
  });

  test('a mensagem da falha sai com a pergunta seguinte ou ao abrir um bloco', async () => {
    const apagarContacto = jest.fn(async () => { throw SEM_REDE; });
    const { ecra } = await pronto({ api: { apagarContacto } });
    ecra.pedirApagar(C2);
    ecra.responderApagar(RESPOSTA_APAGAR);
    await esperar();
    ecra.pedirApagar(C2);
    expect(ecra.vista.alerta).toBeNull();
    ecra.responderApagar(RESPOSTA_APAGAR);
    await esperar();
    expect(ecra.vista.alerta).toBe(MENSAGEM_SEM_REDE);
    ecra.abrirNovo();
    expect(ecra.vista.alerta).toBeNull();
  });

  test('a lista muda com a pergunta aberta: a pergunta fica, sem descrição', async () => {
    const lenta = pendente();
    const listarContactos = jest.fn().mockResolvedValueOnce(RESPOSTA).mockReturnValueOnce(lenta.promessa);
    const { ecra } = await pronto({ api: { listarContactos } });
    ecra.abrirNovo();
    ecra.cancelar();
    ecra.pedirApagar(C2);
    lenta.resolver({ hoje: HOJE, contactos: [CONTACTO_DE_OUTRO] });
    await esperar();
    expect(ecra.vista.apagar).toMatchObject({ id: C2, descricao: '' });
  });
});

// --- O que se lê no código -----------------------------------------------------------------------

describe('a secção na ficha', () => {
  const pagina = fs.readFileSync(PAGINA, 'utf8');
  const componente = fs.readFileSync(COMPONENTE, 'utf8');

  test('fica entre os dados da loja e a zona de apagar, fora do formulário', () => {
    const fimDoFormulario = pagina.indexOf('</form>');
    const seccao = pagina.indexOf('<ContactosLoja lojaId={id} />');
    const apagar = pagina.indexOf('data-testid="crm-ficha-apagar"');
    expect(fimDoFormulario).toBeGreaterThan(-1);
    expect(seccao).toBeGreaterThan(fimDoFormulario);
    expect(apagar).toBeGreaterThan(seccao);
  });

  test('o `criarFicha` não sabe dos contactos, e os contactos não dependem dele', () => {
    expect(fs.readFileSync(FICHA, 'utf8')).not.toMatch(/from '\.\/contactos'|listarContactos|criarContacto/);
    expect(fs.readFileSync(MODULO, 'utf8')).not.toMatch(/from '\.\/ficha'/);
    expect(pagina).not.toMatch(/listarContactos|criarContacto/);
  });

  test('o `novoUuid4` entra por parâmetro, e o módulo não lê o relógio nem o crypto do browser', () => {
    const modulo = fs.readFileSync(MODULO, 'utf8');
    expect(componente).toMatch(/novoUuid: novoUuid4,/);
    expect(modulo).not.toMatch(/new Date|Date\.now|crypto\./);
  });

  test('o bloco é um formulário sem a validação do browser, com o máximo do hoje do servidor', () => {
    expect(componente).toMatch(/<form\s+noValidate/);
    expect(componente).toMatch(/max=\{bloco\.max \?\? undefined\}/);
    expect(componente).toMatch(/placeholder=\{TEXTO_EXEMPLO_RESUMO\}/);
  });

  test('o motivo de Guardar fica num aria-live que está sempre na página', () => {
    expect(componente).toMatch(/<p aria-live="polite"[^>]*>\s*\{guardar\.falta \?\? ''\}/);
  });

  test('o foco da pergunta vai para a primeira escolha, a que não apaga', () => {
    expect(componente).toMatch(/ref=\{i === 0 \? primeiraEscolhaApagar : undefined\}/);
    expect(componente).toMatch(/onOpenAutoFocus=[\s\S]*?primeiraEscolhaApagar\.current\?\.focus\(\)/);
  });

  test('um botão que já não exista dá lugar a "Adicionar contacto"', () => {
    expect(componente).toMatch(/\(nos\.current\[alvo\] \?\? nos\.current\[ALVO_ADICIONAR\]\)\?\.focus\(\)/);
  });
});
