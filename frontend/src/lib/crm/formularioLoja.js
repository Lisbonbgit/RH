// Os campos de uma loja (desenho original §6.2; plano T2.27; a ficha da T2.28
// usa os mesmos, já preenchidos): nome*, fase* (um toque, com a cor do pino),
// região, telefone, pessoa de contacto, morada, código postal, localidade e
// notas. A ficha tem também o horário de receção (até duas janelas, HH:MM) e os
// dias fechada, antes das notas; o registo rápido não os tem.
//
// Porta de public/assets/js/componentes/formulario-loja.js do CRM autónomo,
// sem o DOM: o estado do formulário é um objeto `{valores, preenchida, erros}`
// e cada mudança é uma função pura que devolve o estado novo, ou o mesmo
// objeto quando nada muda (o "não avisa" do autónomo). O
// `components/crm/FormularioLoja.js` só o desenha (correção "componentes Sem
// Jest"):
//  - `valores`: o que está nos campos (a região é um uuid ou null; os textos,
//    tal como escritos: o servidor tira os espaços e trata '' como sem valor);
//  - `preenchida`: o que a app pôs nos campos da morada (a última morada
//    escolhida na pesquisa ou sugerida pelo GPS), para distinguir o que a
//    pessoa escreveu (`camposDaMorada`/`camposSugeridos` de `morada.js`);
//  - `erros`: os erros da API junto a cada campo (`{campo: texto}`).
// Quem valida é o servidor (`validador_loja.py`). Os limites (`maxLength`) são
// os do servidor, para não se escrever mais do que cabe. O nome e o telefone
// são sempre escritos pela pessoa (desenho original §9): nada se copia de
// terceiros, e os campos não aceitam o preenchimento automático do browser
// (que poria os dados de quem está a escrever, e não os da loja).
//
// Adaptação dos ids: a região é um uuid em texto (`eUuid`). O `Select` do
// shadcn não aceita um valor vazio, por isso "Sem região" é `VALOR_SEM_REGIAO`.
import { FASES, FUNIL } from './fases';
import { TEXTO_REGIAO_GUARDADA, regioesValidas } from './filtros';
import { eUuid } from './ids';
import { camposDaMorada, camposSugeridos } from './morada';

export const FASE_INICIAL = 'potencial';
export const ROTULO_FASE = 'Fase';
export const ROTULO_HORARIO = 'Horário de receção';
export const ROTULO_DIAS = 'Dias fechada';
export const TEXTO_SEM_HORARIO = 'Sem horário, a loja recebe a qualquer hora do dia de trabalho.';
export const VALOR_SEM_REGIAO = 'sem';
export const TEXTO_SEM_REGIAO = 'Sem região';

// Os campos que não são a fase, as horas nem os dias. `maxLength` do nome, da morada, da localidade e da
// pessoa de contacto: os do `validador_loja.py` (o formularioLoja.test.js lê-os de lá).
export const CAMPOS = Object.freeze({
  nome: Object.freeze({ rotulo: 'Nome', obrigatorio: true, tipo: 'text', maxLength: 150, autoComplete: 'off' }),
  regiao_id: Object.freeze({ rotulo: 'Região', tag: 'select' }),
  telefone: Object.freeze({ rotulo: 'Telefone', tipo: 'tel', inputMode: 'tel', maxLength: 30, autoComplete: 'off' }),
  pessoa_contacto: Object.freeze({ rotulo: 'Pessoa de contacto', tipo: 'text', maxLength: 100, autoComplete: 'off' }),
  morada: Object.freeze({ rotulo: 'Morada', tipo: 'text', maxLength: 255, autoComplete: 'off' }),
  codigo_postal: Object.freeze({
    rotulo: 'Código postal', tipo: 'text', maxLength: 8, placeholder: '0000-000', autoComplete: 'off',
  }),
  localidade: Object.freeze({ rotulo: 'Localidade', tipo: 'text', maxLength: 100, autoComplete: 'off' }),
  notas: Object.freeze({ rotulo: 'Notas', tag: 'textarea', linhas: 3, autoComplete: 'off' }),
});

// Os campos de texto que se escrevem à mão.
const CAMPOS_TEXTO = Object.freeze(['nome', 'telefone', 'pessoa_contacto', 'morada', 'codigo_postal', 'localidade', 'notas']);

// O horário de receção (dossiê §5.6): duas janelas, cada uma com início e fim.
const JANELAS = Object.freeze([
  Object.freeze({ nome: '1.ª janela', inicio: 'janela1_inicio', fim: 'janela1_fim' }),
  Object.freeze({ nome: '2.ª janela', inicio: 'janela2_inicio', fim: 'janela2_fim' }),
]);
const CAMPOS_HORAS = Object.freeze(JANELAS.flatMap((janela) => [janela.inicio, janela.fim]));

// Os dias fechada (dossiê §5.7), pela ordem da semana (a do servidor).
export const DIAS = Object.freeze([
  ['seg', 'Segunda'], ['ter', 'Terça'], ['qua', 'Quarta'], ['qui', 'Quinta'], ['sex', 'Sexta'], ['sab', 'Sábado'],
  ['dom', 'Domingo'],
].map(([valor, rotulo]) => Object.freeze({ valor, rotulo })));
const VALORES_DIAS = Object.freeze(DIAS.map((dia) => dia.valor));

const temChave = (objeto, chave) => Object.prototype.hasOwnProperty.call(objeto ?? {}, chave);
const textoOuVazio = (valor) => (typeof valor === 'string' ? valor : '');
const diasPorOrdem = (dias) => VALORES_DIAS.filter((dia) => Array.isArray(dias) && dias.includes(dia));

// Os campos que o formulário mostra, pela ordem do ecrã (os erros destes ficam junto a cada um).
export function camposDoFormulario({ ficha = false } = {}) {
  return [
    'nome', 'fase', 'regiao_id', 'telefone', 'pessoa_contacto', 'morada', 'codigo_postal', 'localidade',
    ...(ficha ? [...CAMPOS_HORAS, 'dias_fechada'] : []),
    'notas',
  ];
}

// Os quatro campos das horas: no ecrã lê-se "Início" e "Fim" ao lado do nome da janela; o rótulo completo
// ("Início da 1.ª janela") é o que os leitores de ecrã leem (e o que distingue os quatro campos).
export function camposJanelas() {
  return JANELAS.flatMap((janela) => [['Início', janela.inicio], ['Fim', janela.fim]].map(([parte, campo]) => ({
    campo, janela: janela.nome, parte, rotulo: `${parte} da ${janela.nome}`,
  })));
}

// Uma opção por fase, pela ordem do funil, com a amostra da cor do pino (`crm.css`).
export function opcoesFase() {
  return FUNIL.map((fase) => ({ valor: fase, rotulo: FASES[fase].rotulo, classeCor: `crm-amostra-fase pino--${fase}` }));
}

function valoresVazios({ ficha, regiaoId }) {
  const valores = {
    nome: '',
    fase: FASE_INICIAL,
    regiao_id: eUuid(regiaoId) ? regiaoId : null,
    telefone: '',
    pessoa_contacto: '',
    morada: '',
    codigo_postal: '',
    localidade: '',
    notas: '',
  };
  if (!ficha) return valores;
  for (const campo of CAMPOS_HORAS) valores[campo] = '';
  valores.dias_fechada = [];
  return valores;
}

// O formulário vazio, na fase Potencial; a região dada (ex.: a última usada) se for um uuid.
export function estadoInicial({ ficha = false, regiaoId = null } = {}) {
  return { valores: valoresVazios({ ficha, regiaoId }), preenchida: {}, erros: {} };
}

// Os valores para a API: só as chaves da loja, com a fase e a região só se forem válidas (senão null) e os
// textos como estão ('' fica '': o servidor trata-o como sem valor).
export function valoresDoFormulario(valores, { ficha = false } = {}) {
  const v = valores ?? {};
  const lidos = {
    nome: textoOuVazio(v.nome),
    fase: FUNIL.includes(v.fase) ? v.fase : null,
    regiao_id: eUuid(v.regiao_id) ? v.regiao_id : null,
    telefone: textoOuVazio(v.telefone),
    pessoa_contacto: textoOuVazio(v.pessoa_contacto),
    morada: textoOuVazio(v.morada),
    codigo_postal: textoOuVazio(v.codigo_postal),
    localidade: textoOuVazio(v.localidade),
    notas: textoOuVazio(v.notas),
  };
  if (!ficha) return lidos;
  for (const campo of CAMPOS_HORAS) lidos[campo] = textoOuVazio(v[campo]);
  lidos.dias_fechada = diasPorOrdem(v.dias_fechada);
  return lidos;
}

function semErro(erros, campo) {
  if (!temChave(erros, campo)) return erros;
  const restantes = { ...erros };
  delete restantes[campo];
  return restantes;
}

function valorAceite(campo, valor) {
  if (campo === 'fase') return FUNIL.includes(valor);
  if (campo === 'regiao_id') return valor === null || eUuid(valor);
  return (CAMPOS_TEXTO.includes(campo) || CAMPOS_HORAS.includes(campo)) && typeof valor === 'string';
}

// A pessoa mudou um campo: o valor novo, e o erro desse campo sai. Um campo que este formulário não tem, ou
// um valor que o campo não aceita, não muda nada (os dias mudam-se com `alternarDia`).
export function mudarCampo(estado, campo, valor) {
  if (!temChave(estado.valores, campo) || !valorAceite(campo, valor)) return estado;
  const erros = semErro(estado.erros, campo);
  if (estado.valores[campo] === valor && erros === estado.erros) return estado;
  return { ...estado, valores: { ...estado.valores, [campo]: valor }, erros };
}

// A ficha: marcar ou desmarcar um dia fechada (a lista fica pela ordem da semana; o erro dos dias sai).
export function alternarDia(estado, dia, marcado) {
  const atuais = estado.valores.dias_fechada;
  if (!Array.isArray(atuais) || !VALORES_DIAS.includes(dia) || atuais.includes(dia) === Boolean(marcado)) return estado;
  const dias = VALORES_DIAS.filter((d) => (d === dia ? Boolean(marcado) : atuais.includes(d)));
  return { ...estado, valores: { ...estado.valores, dias_fechada: dias }, erros: semErro(estado.erros, 'dias_fechada') };
}

// Escreve nos campos da morada os valores {campo: texto} que a app escolheu, e lembra-se deles.
function escreverMorada(estado, novos) {
  const nomes = Object.keys(novos);
  if (nomes.length === 0) return estado;
  const erros = nomes.reduce(semErro, estado.erros);
  return { valores: { ...estado.valores, ...novos }, preenchida: { ...estado.preenchida, ...novos }, erros };
}

// A morada escolhida na pesquisa (E6) preenche a morada, o código postal e a localidade (`camposDaMorada`).
// O nome e o telefone nunca vêm de lá: são sempre escritos pela pessoa (desenho original §9).
export function escolherMorada(estado, sugestao) {
  return escreverMorada(estado, camposDaMorada(sugestao, estado.valores, estado.preenchida));
}

// A morada sugerida pelo GPS (E7) só preenche os campos vazios, ou os que a app lá pôs e a pessoa não mudou
// (`camposSugeridos`): o que a pessoa escreveu fica.
export function sugerirMorada(estado, sugestao) {
  return escreverMorada(estado, camposSugeridos(sugestao, estado.valores, estado.preenchida));
}

// A ficha: desfaz o que a app pôs nos campos da morada (a pesquisa ou o GPS) desde a última vez, com os valores
// dados ({campo: texto}), só nos campos que a pessoa não mudou depois. Ex.: cancelar a correção da localização.
export function reporMorada(estado, anteriores) {
  const repostos = {};
  for (const [campo, valor] of Object.entries(estado.preenchida)) {
    const anterior = anteriores?.[campo];
    if (typeof anterior === 'string' && estado.valores[campo] === valor && valor !== anterior) repostos[campo] = anterior;
  }
  const nomes = Object.keys(repostos);
  if (nomes.length === 0) return Object.keys(estado.preenchida).length === 0 ? estado : { ...estado, preenchida: {} };
  return {
    valores: { ...estado.valores, ...repostos },
    preenchida: {},
    erros: nomes.reduce(semErro, estado.erros),
  };
}

// Os erros da API ({campo: texto}): os dos campos que o formulário mostra (`porCampo`), o primeiro deles
// (para o foco; a ordem é a do servidor) e os dos campos que este formulário não tem (`restantes`: ex.: a
// localização, que é do seletor). Mensagens que não são texto não contam.
export function separarErros(erros, { ficha = false } = {}) {
  const campos = camposDoFormulario({ ficha });
  const porCampo = {};
  const restantes = {};
  let primeiro = null;
  if (erros !== null && typeof erros === 'object') {
    for (const [campo, mensagem] of Object.entries(erros)) {
      if (typeof mensagem !== 'string' || campo === '__proto__') continue;
      if (campos.includes(campo)) {
        porCampo[campo] = mensagem;
        if (primeiro === null) primeiro = campo;
      } else {
        restantes[campo] = mensagem;
      }
    }
  }
  return { porCampo, primeiro, restantes };
}

// Mostra os erros dados ({campo: texto}) junto aos campos, com os que já lá estavam.
export function comErros(estado, porCampo) {
  if (Object.keys(porCampo ?? {}).length === 0) return estado;
  return { ...estado, erros: { ...estado.erros, ...porCampo } };
}

export function comErro(estado, campo, texto) {
  return comErros(estado, { [campo]: texto });
}

export function limparErros(estado) {
  return Object.keys(estado.erros).length === 0 ? estado : { ...estado, erros: {} };
}

// --- A região --------------------------------------------------------------------------------------

// As opções do seletor da região ([{valor, texto}]): "Sem região" e as regiões do GET /api/crm/regioes (já
// pela ordem certa; só as que têm um uuid e um nome). `regioes` null = a lista ainda não chegou (ou falhou):
// aí, a região `escolhida` (ex.: a última usada) aparece como "Região guardada", para não se perder.
export function opcoesRegiaoLoja(regioes, escolhida) {
  const opcoes = [{ valor: VALOR_SEM_REGIAO, texto: TEXTO_SEM_REGIAO }];
  if (regioes == null) {
    if (eUuid(escolhida)) opcoes.push({ valor: escolhida, texto: TEXTO_REGIAO_GUARDADA });
  } else {
    for (const regiao of regioesValidas(regioes)) opcoes.push({ valor: regiao.id, texto: regiao.nome });
  }
  return Object.freeze(opcoes.map(Object.freeze));
}

// A região que fica escolhida: a `escolhida`, se existir na lista (ou se a lista ainda não chegou); senão
// nenhuma (null = sem região).
export function regiaoQueFica(regioes, escolhida) {
  if (!eUuid(escolhida)) return null;
  if (regioes == null) return escolhida;
  return regioesValidas(regioes).some((regiao) => regiao.id === escolhida) ? escolhida : null;
}

// As regiões chegaram: fica a escolhida que existe, e o erro da região (a falha de antes) sai.
export function ajustarRegiao(estado, regioes) {
  const regiao = regiaoQueFica(regioes, estado.valores.regiao_id);
  const erros = semErro(estado.erros, 'regiao_id');
  if (regiao === estado.valores.regiao_id && erros === estado.erros) return estado;
  const valores = regiao === estado.valores.regiao_id ? estado.valores : { ...estado.valores, regiao_id: regiao };
  return { ...estado, valores, erros };
}

// O valor do seletor para a região do formulário, e a região do formulário para o valor do seletor.
export const valorSeletorRegiao = (regiaoId) => (eUuid(regiaoId) ? regiaoId : VALOR_SEM_REGIAO);
export const regiaoDoSeletor = (valor) => (eUuid(valor) ? valor : null);

// --- A ficha (T2.28) -------------------------------------------------------------------------------

// O formulário com os dados da loja do GET /api/crm/lojas/{id}; o que a loja não tem (null) fica vazio, uma
// fase desconhecida fica Potencial e uma região que não é um uuid fica sem região. A morada que lá fica é a
// da loja: conta como escrita pela pessoa (o GPS não a substitui).
export function preencherComLoja(loja, { ficha = false } = {}) {
  const valores = valoresVazios({ ficha, regiaoId: loja?.regiao_id });
  for (const campo of CAMPOS_TEXTO) valores[campo] = textoOuVazio(loja?.[campo]);
  valores.fase = FUNIL.includes(loja?.fase) ? loja.fase : FASE_INICIAL;
  if (ficha) {
    for (const campo of CAMPOS_HORAS) valores[campo] = textoOuVazio(loja?.[campo]);
    valores.dias_fechada = diasPorOrdem(loja?.dias_fechada);
  }
  return { valores, preenchida: {}, erros: {} };
}
