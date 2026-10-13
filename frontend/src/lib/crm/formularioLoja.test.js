/**
 * O FORMULÁRIO DA LOJA — os campos, os valores, a região, a morada e os erros.
 *
 * Porta de public/assets/js/componentes/formulario-loja.js do CRM autónomo
 * (etiqueta `referencia-standalone`), com os casos de
 * tests/js/formulario-loja.test.js. No autónomo o componente guardava o estado
 * no DOM; aqui o estado é um objeto `{valores, preenchida, erros}` e cada
 * mudança é uma função pura que devolve o estado novo (o mesmo objeto quando
 * nada muda: é o "não avisa" do autónomo). O `components/crm/FormularioLoja.js`
 * só desenha este estado (correção "componentes Sem Jest").
 *
 * Adaptações ao portal (plano T2.27):
 *   - a região é um uuid em texto (`eUuid`), e não um inteiro positivo; o
 *     seletor da região (o `Select` do shadcn não aceita um valor vazio) usa
 *     `VALOR_SEM_REGIAO` ('sem') para "Sem região";
 *   - enquanto as regiões não chegam, a região guardada aparece como "Região
 *     guardada" (no autónomo era o ecrã que o fazia, com `definirRegioes`);
 *   - os limites dos campos de texto são os do servidor, lidos do
 *     `backend/crm/dominio/validador_loja.py`.
 * O horário de receção e os dias fechada são só da ficha (`{ficha: true}`,
 * T2.28); o registo rápido (T2.27) não os tem.
 */
import fs from 'fs';
import path from 'path';

import {
  CAMPOS,
  DIAS,
  FASE_INICIAL,
  ROTULO_DIAS,
  ROTULO_FASE,
  ROTULO_HORARIO,
  TEXTO_SEM_HORARIO,
  TEXTO_SEM_REGIAO,
  VALOR_SEM_REGIAO,
  ajustarRegiao,
  alternarDia,
  camposDoFormulario,
  camposJanelas,
  comErro,
  comErros,
  escolherMorada,
  estadoInicial,
  limparErros,
  mudarCampo,
  opcoesFase,
  opcoesRegiaoLoja,
  preencherComLoja,
  regiaoDoSeletor,
  regiaoQueFica,
  reporMorada,
  separarErros,
  sugerirMorada,
  valorSeletorRegiao,
  valoresDoFormulario,
} from './formularioLoja';
import { TEXTO_REGIAO_GUARDADA } from './filtros';

// frontend/src/lib/crm → raiz do repositório.
const VALIDADOR_PY = path.join(
  __dirname, '..', '..', '..', '..', 'backend', 'crm', 'dominio', 'validador_loja.py',
);

const LISBOA = '3f1c2d4e-5a6b-4c7d-8e9f-0a1b2c3d4e5f';
const PORTO = '7a8b9c0d-1e2f-4a3b-9c4d-5e6f7a8b9c0d';
const SETUBAL = 'c0ffee00-0000-4000-a000-000000000099';

const escrever = (estado, campo, valor) => mudarCampo(estado, campo, valor);

// --- Os campos ---------------------------------------------------------------------------------------

test('os campos do registo rápido (plano E5), com rótulo, pela ordem do formulário', () => {
  expect(camposDoFormulario()).toEqual([
    'nome', 'fase', 'regiao_id', 'telefone', 'pessoa_contacto', 'morada', 'codigo_postal', 'localidade', 'notas',
  ]);
  const rotulos = camposDoFormulario().filter((c) => c !== 'fase').map((c) => CAMPOS[c].rotulo);
  expect(rotulos).toEqual(['Nome', 'Região', 'Telefone', 'Pessoa de contacto', 'Morada', 'Código postal', 'Localidade', 'Notas']);
  expect(ROTULO_FASE).toBe('Fase');
  expect(CAMPOS.nome.obrigatorio).toBe(true);
  for (const campo of ['regiao_id', 'telefone', 'pessoa_contacto', 'morada', 'codigo_postal', 'localidade', 'notas']) {
    expect([campo, CAMPOS[campo].obrigatorio === true]).toEqual([campo, false]);
  }
  expect(CAMPOS.notas.tag).toBe('textarea');
  expect(CAMPOS.notas.linhas).toBe(3);
  expect(CAMPOS.regiao_id.tag).toBe('select');
  expect(Object.isFrozen(CAMPOS)).toBe(true);
  expect(Object.values(CAMPOS).every(Object.isFrozen)).toBe(true);
});

test('atributos dos campos: limites da BD, teclado do telefone e sem preenchimento automático com dados da pessoa', () => {
  expect(CAMPOS.nome.maxLength).toBe(150);
  expect(CAMPOS.telefone.tipo).toBe('tel');
  expect(CAMPOS.telefone.inputMode).toBe('tel');
  expect(CAMPOS.telefone.maxLength).toBe(30);
  expect(CAMPOS.pessoa_contacto.maxLength).toBe(100);
  expect(CAMPOS.morada.maxLength).toBe(255);
  expect(CAMPOS.codigo_postal.maxLength).toBe(8);
  expect(CAMPOS.codigo_postal.placeholder).toBe('0000-000');
  expect(CAMPOS.localidade.maxLength).toBe(100);
  // São os dados da loja, não os de quem escreve: o browser não os preenche sozinho.
  for (const campo of ['nome', 'telefone', 'pessoa_contacto', 'morada', 'codigo_postal', 'localidade', 'notas']) {
    expect([campo, CAMPOS[campo].autoComplete]).toEqual([campo, 'off']);
  }
  for (const campo of ['nome', 'pessoa_contacto', 'morada', 'codigo_postal', 'localidade']) {
    expect([campo, CAMPOS[campo].tipo]).toEqual([campo, 'text']);
  }
});

test('os limites do nome, da morada, da localidade e da pessoa de contacto são os do servidor (validador_loja.py)', () => {
  // Falha, e não salta, se o ficheiro não estiver lá (o mesmo cuidado do ids.test.js).
  expect(fs.existsSync(VALIDADOR_PY)).toBe(true);
  const python = fs.readFileSync(VALIDADOR_PY, 'utf8');
  const nome = [...python.matchAll(/^NOME_MAXIMO = (\d+)$/gm)];
  expect(nome).toHaveLength(1);
  expect(CAMPOS.nome.maxLength).toBe(Number(nome[0][1]));
  for (const campo of ['morada', 'localidade', 'pessoa_contacto']) {
    const linhas = [...python.matchAll(new RegExp(`^\\s+"${campo}": \\("[^"]+", (\\d+)\\),$`, 'gm'))];
    expect([campo, linhas.length]).toEqual([campo, 1]);
    expect([campo, CAMPOS[campo].maxLength]).toEqual([campo, Number(linhas[0][1])]);
  }
});

test('a fase escolhe-se com um toque: uma opção por fase, pela ordem do funil, com a cor do pino; começa em Potencial', () => {
  expect(opcoesFase()).toEqual([
    { valor: 'potencial', rotulo: 'Potencial', classeCor: 'crm-amostra-fase pino--potencial' },
    { valor: 'contactada', rotulo: 'A aguardar amostra', classeCor: 'crm-amostra-fase pino--contactada' },
    { valor: 'amostra', rotulo: 'Amostra recebida', classeCor: 'crm-amostra-fase pino--amostra' },
    { valor: 'cliente', rotulo: 'Cliente', classeCor: 'crm-amostra-fase pino--cliente' },
    { valor: 'perdida', rotulo: 'Perdida', classeCor: 'crm-amostra-fase pino--perdida' },
  ]);
  expect(FASE_INICIAL).toBe('potencial');
  expect(estadoInicial().valores.fase).toBe('potencial');
});

// --- O estado e os valores ---------------------------------------------------------------------------

test('estadoInicial: tudo vazio, fase Potencial, sem região (ou a região dada, se for um uuid)', () => {
  expect(estadoInicial()).toEqual({
    valores: {
      nome: '', fase: 'potencial', regiao_id: null, telefone: '', pessoa_contacto: '', morada: '', codigo_postal: '',
      localidade: '', notas: '',
    },
    preenchida: {},
    erros: {},
  });
  expect(estadoInicial({ regiaoId: LISBOA }).valores.regiao_id).toBe(LISBOA);
  for (const regiaoId of [7, '7', '', LISBOA.toUpperCase(), undefined, null]) {
    expect([regiaoId, estadoInicial({ regiaoId }).valores.regiao_id]).toEqual([regiaoId, null]);
  }
});

test('valores: o que está no formulário, com a região como uuid (ou null) e a fase escolhida', () => {
  let estado = estadoInicial();
  estado = escrever(estado, 'nome', '  Mercearia da Baixa ');
  estado = escrever(estado, 'fase', 'cliente');
  estado = escrever(estado, 'regiao_id', LISBOA);
  estado = escrever(estado, 'telefone', '+351 912 345 678');
  estado = escrever(estado, 'notas', 'Fecha à hora de almoço');
  expect(valoresDoFormulario(estado.valores)).toEqual({
    nome: '  Mercearia da Baixa ',
    fase: 'cliente',
    regiao_id: LISBOA,
    telefone: '+351 912 345 678',
    pessoa_contacto: '',
    morada: '',
    codigo_postal: '',
    localidade: '',
    notas: 'Fecha à hora de almoço',
  });
  expect(valoresDoFormulario(escrever(estado, 'regiao_id', null).valores).regiao_id).toBe(null);
});

test('valores: só as chaves da API; o que não é texto fica vazio, uma fase ou região que não existe fica null', () => {
  const estranhos = {
    nome: 7, fase: 'desconhecida', regiao_id: 3, telefone: null, pessoa_contacto: undefined, morada: ['x'],
    codigo_postal: '1100-048', localidade: 'Lisboa', notas: '', extra: 'não vai', lat: 38.7,
  };
  expect(valoresDoFormulario(estranhos)).toEqual({
    nome: '', fase: null, regiao_id: null, telefone: '', pessoa_contacto: '', morada: '', codigo_postal: '1100-048',
    localidade: 'Lisboa', notas: '',
  });
  expect(valoresDoFormulario(undefined)).toEqual(valoresDoFormulario({ fase: null }));
});

test('mudarCampo: muda só esse campo e tira só o erro dele; nada mudado devolve o mesmo estado', () => {
  const inicial = comErros(estadoInicial(), { nome: 'Indique o nome.', telefone: 'Telefone inválido.' });
  const estado = escrever(inicial, 'nome', 'Mercearia');
  expect(estado).not.toBe(inicial);
  expect(estado.valores.nome).toBe('Mercearia');
  expect(estado.erros).toEqual({ telefone: 'Telefone inválido.' });
  expect(inicial.valores.nome).toBe(''); // o estado anterior não muda
  expect(inicial.erros).toEqual({ nome: 'Indique o nome.', telefone: 'Telefone inválido.' });
  expect(escrever(estado, 'nome', 'Mercearia')).toBe(estado);
  // O mesmo valor num campo com erro tira o erro (a pessoa mexeu-lhe).
  expect(escrever(estado, 'telefone', '').erros).toEqual({});
});

test('mudarCampo: um campo que o formulário não tem, ou os dias (que têm alternarDia), não mudam nada', () => {
  const estado = estadoInicial();
  for (const campo of ['lat', 'origem_coords', 'confirmar_duplicado', '__proto__', 'janela1_inicio', 'dias_fechada', 'constructor']) {
    expect([campo, mudarCampo(estado, campo, 'x')]).toEqual([campo, estado]);
  }
  expect(Object.prototype).not.toHaveProperty('x');
});

test('mudarCampo na fase: só uma fase do funil', () => {
  const estado = estadoInicial();
  expect(mudarCampo(estado, 'fase', 'amostra').valores.fase).toBe('amostra');
  expect(mudarCampo(estado, 'fase', 'desconhecida')).toBe(estado);
  expect(mudarCampo(estado, 'fase', null)).toBe(estado);
});

test('mudarCampo na região: um uuid ou null (sem região); o resto não muda nada', () => {
  const estado = estadoInicial();
  expect(mudarCampo(estado, 'regiao_id', LISBOA).valores.regiao_id).toBe(LISBOA);
  expect(mudarCampo(mudarCampo(estado, 'regiao_id', LISBOA), 'regiao_id', null).valores.regiao_id).toBe(null);
  for (const valor of [7, '7', '', LISBOA.toUpperCase(), 'sem']) {
    expect([valor, mudarCampo(estado, 'regiao_id', valor)]).toEqual([valor, estado]);
  }
});

test('mudarCampo nos textos: só texto', () => {
  const estado = estadoInicial();
  expect(mudarCampo(estado, 'telefone', 912345678)).toBe(estado);
  expect(mudarCampo(estado, 'telefone', null)).toBe(estado);
});

// --- A região ----------------------------------------------------------------------------------------

test('opcoesRegiaoLoja: "Sem região" e as regiões pela ordem da API', () => {
  const regioes = [{ id: PORTO, nome: 'Porto', ordem: 0 }, { id: LISBOA, nome: 'Lisboa', ordem: 1 }];
  expect(opcoesRegiaoLoja(regioes, LISBOA)).toEqual([
    { valor: 'sem', texto: 'Sem região' },
    { valor: PORTO, texto: 'Porto' },
    { valor: LISBOA, texto: 'Lisboa' },
  ]);
  expect(VALOR_SEM_REGIAO).toBe('sem');
  expect(TEXTO_SEM_REGIAO).toBe('Sem região');
  expect(opcoesRegiaoLoja([], null)).toEqual([{ valor: 'sem', texto: 'Sem região' }]);
});

test('opcoesRegiaoLoja: antes de as regiões chegarem (ou se falharam), a escolhida fica como "Região guardada"', () => {
  expect(opcoesRegiaoLoja(null, LISBOA)).toEqual([
    { valor: 'sem', texto: 'Sem região' },
    { valor: LISBOA, texto: 'Região guardada' },
  ]);
  expect(TEXTO_REGIAO_GUARDADA).toBe('Região guardada');
  expect(opcoesRegiaoLoja(undefined, null)).toEqual([{ valor: 'sem', texto: 'Sem região' }]);
  expect(opcoesRegiaoLoja(null, 7)).toEqual([{ valor: 'sem', texto: 'Sem região' }]);
});

test('opcoesRegiaoLoja ignora entradas inválidas e deixa os nomes como texto', () => {
  const lista = [{ id: LISBOA, nome: '<b>Lisboa</b>' }, { id: '2', nome: 'X' }, { id: 7, nome: 'Y' }, null, { id: PORTO }];
  expect(opcoesRegiaoLoja(lista, null)).toEqual([
    { valor: 'sem', texto: 'Sem região' },
    { valor: LISBOA, texto: '<b>Lisboa</b>' },
  ]);
  expect(opcoesRegiaoLoja({ id: LISBOA, nome: 'Lisboa' }, null)).toEqual([{ valor: 'sem', texto: 'Sem região' }]);
});

test('regiaoQueFica: a escolhida, se existir; uma que já não existe fica sem região', () => {
  const regioes = [{ id: PORTO, nome: 'Porto', ordem: 0 }, { id: LISBOA, nome: 'Lisboa', ordem: 1 }];
  expect(regiaoQueFica(regioes, LISBOA)).toBe(LISBOA);
  expect(regiaoQueFica(regioes, SETUBAL)).toBe(null);
  expect(regiaoQueFica(regioes, null)).toBe(null);
  expect(regiaoQueFica([{ id: LISBOA }], LISBOA)).toBe(null); // uma região sem nome não conta
  // Antes de as regiões chegarem (ou se falharam), a escolhida fica.
  expect(regiaoQueFica(null, LISBOA)).toBe(LISBOA);
  expect(regiaoQueFica(null, 7)).toBe(null);
});

test('ajustarRegiao: quando as regiões chegam, fica a escolhida que existe e sai o erro da região', () => {
  const regioes = [{ id: LISBOA, nome: 'Lisboa', ordem: 0 }];
  const comFalha = comErro(estadoInicial({ regiaoId: LISBOA }), 'regiao_id', 'Sem rede — verifique a ligação e tente novamente.');
  const ajustado = ajustarRegiao(comFalha, regioes);
  expect(ajustado.valores.regiao_id).toBe(LISBOA);
  expect(ajustado.erros).toEqual({});
  expect(ajustarRegiao(estadoInicial({ regiaoId: SETUBAL }), regioes).valores.regiao_id).toBe(null);
  const semNada = estadoInicial({ regiaoId: LISBOA });
  expect(ajustarRegiao(semNada, regioes)).toBe(semNada);
});

test('o seletor da região: o valor de cada região, e "sem" para sem região', () => {
  expect(valorSeletorRegiao(LISBOA)).toBe(LISBOA);
  expect(valorSeletorRegiao(null)).toBe('sem');
  expect(valorSeletorRegiao(7)).toBe('sem');
  expect(regiaoDoSeletor(LISBOA)).toBe(LISBOA);
  expect(regiaoDoSeletor('sem')).toBe(null);
  expect(regiaoDoSeletor('')).toBe(null);
  expect(regiaoDoSeletor(undefined)).toBe(null);
});

// --- Os erros ----------------------------------------------------------------------------------------

test('separarErros: cada erro do seu campo; o primeiro campo (para o foco) e os erros sem campo no formulário', () => {
  const resultado = separarErros({
    nome: 'Indique o nome.',
    telefone: 'O telefone tem de ter 9 a 15 algarismos (aceita + e espaços).',
    lat: 'Fora de Portugal',
    janela1_inicio: 'Hora inválida.',
  });
  expect(resultado).toEqual({
    porCampo: { nome: 'Indique o nome.', telefone: 'O telefone tem de ter 9 a 15 algarismos (aceita + e espaços).' },
    primeiro: 'nome',
    restantes: { lat: 'Fora de Portugal', janela1_inicio: 'Hora inválida.' },
  });
});

test('separarErros: o primeiro é o primeiro que o servidor manda; mensagens que não são texto não contam', () => {
  expect(separarErros({ telefone: 'x', codigo_postal: 'y' }).primeiro).toBe('telefone');
  expect(separarErros({ nome: null, notas: 7, morada: 'z' })).toEqual({ porCampo: { morada: 'z' }, primeiro: 'morada', restantes: {} });
  expect(separarErros(undefined)).toEqual({ porCampo: {}, primeiro: null, restantes: {} });
  expect(separarErros({ lat: 'Fora de Portugal' })).toEqual({ porCampo: {}, primeiro: null, restantes: { lat: 'Fora de Portugal' } });
  expect(separarErros({ ['__proto__']: 'x', toString: 'y' })).toEqual({
    porCampo: {}, primeiro: null, restantes: { toString: 'y' },
  });
});

test('separarErros na fase e na região', () => {
  expect(separarErros({ fase: 'A fase não é válida.', regiao_id: 'A região não existe.' })).toEqual({
    porCampo: { fase: 'A fase não é válida.', regiao_id: 'A região não existe.' },
    primeiro: 'fase',
    restantes: {},
  });
});

test('comErros junta os erros; comErro mostra um; limparErros tira todos', () => {
  const estado = comErros(estadoInicial(), { nome: 'Indique o nome.', telefone: 'Telefone inválido.' });
  expect(estado.erros).toEqual({ nome: 'Indique o nome.', telefone: 'Telefone inválido.' });
  const mais = comErro(estado, 'regiao_id', 'Sem rede — verifique a ligação e tente novamente.');
  expect(mais.erros).toEqual({
    nome: 'Indique o nome.', telefone: 'Telefone inválido.', regiao_id: 'Sem rede — verifique a ligação e tente novamente.',
  });
  expect(limparErros(mais).erros).toEqual({});
  expect(limparErros(mais).valores).toBe(mais.valores);
  const limpo = estadoInicial();
  expect(limparErros(limpo)).toBe(limpo);
  expect(comErros(limpo, {})).toBe(limpo);
});

// --- Morada escolhida na pesquisa (E6) ---------------------------------------------------------------

const AUGUSTA_24 = { rotulo: 'Rua Augusta 24, 1100-048 Lisboa, Portugal', morada: 'Rua Augusta 24', codigo_postal: '1100-048', localidade: 'Lisboa', lat: 38.70921, lng: -9.13712 };
const CASCAIS = { rotulo: 'Rua Augusta, 2750 Cascais, Portugal', morada: 'Rua Augusta', codigo_postal: null, localidade: 'Cascais', lat: 38.6979, lng: -9.4215 };

test('escolherMorada: a morada, o código postal e a localidade da sugestão; o resto fica', () => {
  let estado = escrever(estadoInicial(), 'nome', 'Mercearia');
  estado = escrever(estado, 'morada', 'Rua do Ouro');
  const novo = escolherMorada(estado, AUGUSTA_24);
  expect(novo).not.toBe(estado);
  expect(novo.valores.morada).toBe('Rua Augusta 24');
  expect(novo.valores.codigo_postal).toBe('1100-048');
  expect(novo.valores.localidade).toBe('Lisboa');
  expect(novo.valores.nome).toBe('Mercearia'); // o nome é sempre escrito pela pessoa (spec §9)
  expect(novo.valores.telefone).toBe('');
  expect(novo.preenchida).toEqual({ morada: 'Rua Augusta 24', codigo_postal: '1100-048', localidade: 'Lisboa' });
});

test('escolherMorada: outra sugestão sem código postal esvazia o da anterior, mas não o que a pessoa escreveu', () => {
  let estado = escolherMorada(estadoInicial(), AUGUSTA_24);
  estado = escolherMorada(estado, CASCAIS);
  expect(estado.valores.codigo_postal).toBe(''); // não fica o código postal de Lisboa com a rua de Cascais
  expect(estado.valores.localidade).toBe('Cascais');
  estado = escrever(estado, 'codigo_postal', '2750-001');
  estado = escolherMorada(estado, { ...CASCAIS, morada: 'Rua Augusta 3' });
  expect(estado.valores.codigo_postal).toBe('2750-001');
  expect(estado.valores.morada).toBe('Rua Augusta 3');
});

test('escolherMorada tira os erros dos campos que preenche', () => {
  const estado = comErros(estadoInicial(), { codigo_postal: 'Código postal inválido.', telefone: 'Telefone inválido.' });
  expect(escolherMorada(estado, AUGUSTA_24).erros).toEqual({ telefone: 'Telefone inválido.' });
});

test('escolherMorada sem nada a mudar devolve o mesmo estado', () => {
  const estado = estadoInicial();
  expect(escolherMorada(estado, { rotulo: 'Lisboa', morada: null, codigo_postal: null, localidade: null, lat: 38.7, lng: -9.1 })).toBe(estado);
  expect(escolherMorada(estado, null)).toBe(estado);
});

// --- Morada sugerida pelo GPS (E7) -------------------------------------------------------------------

const PRACA = { rotulo: 'Praça do Comércio, 1100-148 Lisboa, Portugal', morada: 'Praça do Comércio', codigo_postal: '1100-148', localidade: 'Lisboa', lat: 38.70749, lng: -9.13648 };

test('sugerirMorada: preenche só os campos de morada vazios; o que a pessoa escreveu fica', () => {
  let estado = escrever(estadoInicial(), 'nome', 'Mercearia');
  estado = escrever(estado, 'morada', 'Rua do Ouro 3');
  const novo = sugerirMorada(estado, PRACA);
  expect(novo.valores.morada).toBe('Rua do Ouro 3');
  expect(novo.valores.codigo_postal).toBe('1100-148');
  expect(novo.valores.localidade).toBe('Lisboa');
  expect(novo.valores.nome).toBe('Mercearia'); // o nome é sempre escrito pela pessoa (spec §9)
  expect(novo.preenchida).toEqual({ codigo_postal: '1100-148', localidade: 'Lisboa' });
});

test('sugerirMorada: uma segunda sugestão substitui a primeira onde a pessoa não mexeu', () => {
  let estado = sugerirMorada(estadoInicial(), PRACA);
  estado = escrever(estado, 'localidade', 'Baixa');
  estado = sugerirMorada(estado, { ...PRACA, morada: 'Rua Augusta 24', codigo_postal: null });
  expect(estado.valores.morada).toBe('Rua Augusta 24');
  expect(estado.valores.codigo_postal).toBe(''); // não fica o código postal do primeiro ponto
  expect(estado.valores.localidade).toBe('Baixa');
});

test('sugerirMorada e depois a pesquisa: a morada escolhida sem código postal esvazia o que o GPS lá pôs', () => {
  let estado = sugerirMorada(estadoInicial(), PRACA);
  estado = escolherMorada(estado, CASCAIS);
  expect(estado.valores.codigo_postal).toBe('');
  expect(estado.valores.localidade).toBe('Cascais');
});

test('sugerirMorada tira os erros dos campos que preenche; sem nada a mudar devolve o mesmo estado', () => {
  let estado = comErros(estadoInicial(), { codigo_postal: 'Código postal inválido.' });
  estado = sugerirMorada(estado, PRACA);
  expect(estado.erros).toEqual({});
  const vazia = { rotulo: 'Lisboa', morada: null, codigo_postal: null, localidade: null, lat: 38.7, lng: -9.1 };
  const esvaziado = sugerirMorada(estado, vazia);
  expect(esvaziado).not.toBe(estado); // esvaziou os campos que a sugestão anterior lá pôs
  expect(sugerirMorada(esvaziado, vazia)).toBe(esvaziado);
});

// --- A ficha (E8): horário de receção, dias fechada e preencher com a loja ---------------------------

const LOJA = {
  id: '0b6f3c1e-1111-4222-8333-444455556666',
  nome: 'Mercearia da Baixa',
  fase: 'amostra',
  regiao_id: PORTO,
  morada: 'Rua Augusta 24',
  codigo_postal: '1100-048',
  localidade: 'Lisboa',
  lat: 38.70921,
  lng: -9.13712,
  origem_coords: 'pin_manual',
  precisao_m: null,
  telefone: '+351 912 345 678',
  pessoa_contacto: null,
  notas: 'Fecha à hora de almoço',
  janela1_inicio: '10:00',
  janela1_fim: '13:00',
  janela2_inicio: '15:00',
  janela2_fim: '19:00',
  dias_fechada: ['sab', 'dom'],
  atualizado_em: '2026-10-03T09:00:00.123456Z',
};

const CAMPOS_HORAS = ['janela1_inicio', 'janela1_fim', 'janela2_inicio', 'janela2_fim'];

test('sem `ficha` (registo rápido, E5) não há horário de receção nem dias fechada (§9)', () => {
  expect(camposDoFormulario()).not.toContain('janela1_inicio');
  expect(camposDoFormulario()).not.toContain('dias_fechada');
  expect(Object.keys(estadoInicial().valores)).not.toContain('janela1_inicio');
  expect(Object.keys(valoresDoFormulario(estadoInicial().valores))).not.toContain('dias_fechada');
  expect(separarErros({ janela1_fim: 'x', dias_fechada: 'y' }).restantes).toEqual({ janela1_fim: 'x', dias_fechada: 'y' });
});

test('ficha: o horário de receção (2 janelas, horas HH:MM) e os dias fechada, antes das notas', () => {
  expect(camposDoFormulario({ ficha: true })).toEqual([
    'nome', 'fase', 'regiao_id', 'telefone', 'pessoa_contacto', 'morada', 'codigo_postal', 'localidade',
    ...CAMPOS_HORAS, 'dias_fechada', 'notas',
  ]);
  expect([ROTULO_HORARIO, ROTULO_DIAS]).toEqual(['Horário de receção', 'Dias fechada']);
  expect(camposJanelas()).toEqual([
    { campo: 'janela1_inicio', janela: '1.ª janela', parte: 'Início', rotulo: 'Início da 1.ª janela' },
    { campo: 'janela1_fim', janela: '1.ª janela', parte: 'Fim', rotulo: 'Fim da 1.ª janela' },
    { campo: 'janela2_inicio', janela: '2.ª janela', parte: 'Início', rotulo: 'Início da 2.ª janela' },
    { campo: 'janela2_fim', janela: '2.ª janela', parte: 'Fim', rotulo: 'Fim da 2.ª janela' },
  ]);
  expect(TEXTO_SEM_HORARIO).toBe('Sem horário, a loja recebe a qualquer hora do dia de trabalho.');
  expect(DIAS).toEqual([
    { valor: 'seg', rotulo: 'Segunda' }, { valor: 'ter', rotulo: 'Terça' }, { valor: 'qua', rotulo: 'Quarta' },
    { valor: 'qui', rotulo: 'Quinta' }, { valor: 'sex', rotulo: 'Sexta' }, { valor: 'sab', rotulo: 'Sábado' },
    { valor: 'dom', rotulo: 'Domingo' },
  ]);
});

test('ficha: os valores trazem as quatro horas e os dias fechada pela ordem da semana', () => {
  let estado = estadoInicial({ ficha: true });
  expect(estado.valores).toMatchObject({ janela1_inicio: '', janela1_fim: '', janela2_inicio: '', janela2_fim: '', dias_fechada: [] });
  estado = escrever(estado, 'janela1_inicio', '10:00');
  estado = escrever(estado, 'janela1_fim', '13:00');
  estado = alternarDia(estado, 'dom', true);
  estado = alternarDia(estado, 'seg', true);
  expect(estado.valores.dias_fechada).toEqual(['seg', 'dom']); // pela ordem da semana, não pela dos toques
  const valores = valoresDoFormulario(estado.valores, { ficha: true });
  expect(valores.janela1_inicio).toBe('10:00');
  expect(valores.janela1_fim).toBe('13:00');
  expect(valores.janela2_inicio).toBe('');
  expect(valores.janela2_fim).toBe('');
  expect(valores.dias_fechada).toEqual(['seg', 'dom']);
  expect(valoresDoFormulario(alternarDia(estado, 'seg', false).valores, { ficha: true }).dias_fechada).toEqual(['dom']);
});

test('alternarDia: só dias da semana; marcar outra vez (ou desmarcar um que não está) devolve o mesmo estado', () => {
  const estado = alternarDia(estadoInicial({ ficha: true }), 'sab', true);
  expect(alternarDia(estado, 'sab', true)).toBe(estado);
  expect(alternarDia(estado, 'ter', false)).toBe(estado);
  expect(alternarDia(estado, 'feriado', true)).toBe(estado);
  expect(alternarDia(estadoInicial(), 'sab', true)).toEqual(estadoInicial()); // sem ficha não há dias
});

test('ficha: os erros da API nas horas e nos dias ficam em cada campo; mexer nos dias tira o erro deles', () => {
  const { porCampo, primeiro, restantes } = separarErros({
    janela1_fim: 'O fim tem de ser depois do início.',
    janela2_inicio: 'A janela 2 tem de começar depois do fim da janela 1.',
    dias_fechada: 'Há dias repetidos.',
    lat: 'Fora de Portugal',
  }, { ficha: true });
  expect(primeiro).toBe('janela1_fim');
  expect(restantes).toEqual({ lat: 'Fora de Portugal' });
  expect(porCampo).toEqual({
    janela1_fim: 'O fim tem de ser depois do início.',
    janela2_inicio: 'A janela 2 tem de começar depois do fim da janela 1.',
    dias_fechada: 'Há dias repetidos.',
  });
  const estado = comErros(estadoInicial({ ficha: true }), porCampo);
  expect(alternarDia(estado, 'ter', true).erros).toEqual({
    janela1_fim: 'O fim tem de ser depois do início.',
    janela2_inicio: 'A janela 2 tem de começar depois do fim da janela 1.',
  });
});

test('preencherComLoja: os campos ficam com os da loja (null fica vazio), a fase, a região e os dias marcados', () => {
  const estado = preencherComLoja(LOJA, { ficha: true });
  expect(estado).toEqual({
    valores: {
      nome: 'Mercearia da Baixa',
      fase: 'amostra',
      regiao_id: PORTO,
      telefone: '+351 912 345 678',
      pessoa_contacto: '',
      morada: 'Rua Augusta 24',
      codigo_postal: '1100-048',
      localidade: 'Lisboa',
      notas: 'Fecha à hora de almoço',
      janela1_inicio: '10:00',
      janela1_fim: '13:00',
      janela2_inicio: '15:00',
      janela2_fim: '19:00',
      dias_fechada: ['sab', 'dom'],
    },
    preenchida: {},
    erros: {},
  });
  expect(estado.valores.dias_fechada).not.toBe(LOJA.dias_fechada); // uma cópia: a loja carregada não muda
});

test('preencherComLoja: o que a loja não tem (ou não é válido) fica vazio, Potencial e sem região', () => {
  const estado = preencherComLoja({
    ...LOJA, fase: 'desconhecida', regiao_id: 3, janela2_inicio: null, janela2_fim: null, dias_fechada: ['sab', 'x', 'seg'], notas: null,
  }, { ficha: true });
  expect(estado.valores.fase).toBe('potencial');
  expect(estado.valores.regiao_id).toBe(null);
  expect(estado.valores.janela2_inicio).toBe('');
  expect(estado.valores.janela2_fim).toBe('');
  expect(estado.valores.dias_fechada).toEqual(['seg', 'sab']);
  expect(estado.valores.notas).toBe('');
  expect(preencherComLoja(null)).toEqual(estadoInicial());
  expect(Object.keys(preencherComLoja(LOJA).valores)).not.toContain('janela1_inicio');
});

test('preencherComLoja mostra os dados só como texto (o React escreve-os como texto)', () => {
  expect(preencherComLoja({ ...LOJA, nome: '<b>x</b>' }).valores.nome).toBe('<b>x</b>');
});

test('preencherComLoja: a morada da loja conta como escrita pela pessoa (o GPS não a substitui)', () => {
  const estado = sugerirMorada(preencherComLoja({ ...LOJA, codigo_postal: null }, { ficha: true }), PRACA);
  expect(estado.valores.morada).toBe('Rua Augusta 24');
  expect(estado.valores.codigo_postal).toBe('1100-148'); // só o campo vazio
});

test('reporMorada: volta a pôr os valores dados nos campos que a app mudou e a pessoa não', () => {
  let estado = preencherComLoja({ ...LOJA, morada: 'Rua do Ouro 3', codigo_postal: '1100-060' }, { ficha: true });
  const antes = { morada: 'Rua do Ouro 3', codigo_postal: '1100-060', localidade: 'Lisboa' };
  estado = escolherMorada(estado, AUGUSTA_24);
  estado = escolherMorada(estado, CASCAIS);
  expect(estado.valores.codigo_postal).toBe(''); // a segunda sugestão esvaziou o da primeira
  estado = escrever(estado, 'localidade', 'Estoril');
  const reposto = reporMorada(estado, antes);
  expect(reposto.valores.morada).toBe('Rua do Ouro 3');
  expect(reposto.valores.codigo_postal).toBe('1100-060'); // o que a pesquisa esvaziou também volta
  expect(reposto.valores.localidade).toBe('Estoril'); // o que a pessoa escreveu fica
  expect(reposto.preenchida).toEqual({});
  const outraVez = reporMorada(reposto, antes);
  expect(outraVez.valores).toBe(reposto.valores); // sem nada a repor, os valores ficam os mesmos
});

test('reporMorada tira os erros dos campos que repõe', () => {
  let estado = escolherMorada(estadoInicial(), AUGUSTA_24);
  estado = comErros(estado, { morada: 'A morada tem no máximo 255 caracteres.', telefone: 'Telefone inválido.' });
  const reposto = reporMorada(estado, { morada: 'Rua do Ouro 3', codigo_postal: '', localidade: '' });
  expect(reposto.valores.morada).toBe('Rua do Ouro 3');
  expect(reposto.erros).toEqual({ telefone: 'Telefone inválido.' });
});
