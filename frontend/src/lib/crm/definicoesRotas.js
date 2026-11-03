// Definições › Rotas (plano F3 T3.34; a página é a `pages/crm/DefinicoesRotas.js` da T3.41), sem DOM: as 6
// definições das rotas do `GET`/`PATCH /api/crm/definicoes` (só o admin; plano F3 §1 "Definições do CRM"):
//  - "Hora de saída" e "Hora limite de regresso" ("HH:MM", hora de Lisboa): as horas com que nasce cada
//    rota nova (o servidor copia-as para a rota quando ela nasce; um dia sem rota mostra-as logo);
//  - "Tempo de serviço (min)" de cada motivo (inteiros de 1 a 240): o tempo com que entra cada paragem
//    nova, e o de uma paragem cujo motivo muda sem se dizer o tempo.
// Molde do `criarFabrica` (T2.30): uma `vista` congelada a cada mudança, entregue ao `aoMudarVista`.
//  - Guardar envia só o que mudou (`corpoDefinicoesRotas`): as horas em texto, aparadas; os minutos como
//    inteiros quando são só algarismos (o resto vai como está e o servidor diz porquê). As chaves da
//    fábrica nunca vão: são do separador "Fábrica".
//  - Quem valida é o servidor: o 422 fica junto de cada campo, com o foco no primeiro; a coerência das horas
//    ("A hora de regresso tem de ser depois da hora de saída.") vem no regresso. Mudar um campo tira só o
//    erro dele. "Definições das rotas guardadas." é um aviso (toast, `aoAvisar`).
//  - Sem as definições não há formulário: a mensagem e "Tentar novamente"; quando a rede volta, pedem-se
//    outra vez.
// As chaves e os limites são os do servidor (`dominio/definicoes.py` e `dominio/validador_rota.py`; o teste
// lê-os). Os dados ficam como texto: o React escreve-os como texto.
import { MENSAGEM_ERRO_INESPERADO } from './api';
import { textoDoErro } from './ecraMapa';
import { MOTIVOS, rotuloMotivo } from './rota';

export const TITULO_ROTAS = 'Rotas';
export const TEXTO_DESCRICAO_ROTAS = 'As horas de cada rota nova e o tempo de serviço de cada paragem nova, por motivo. '
  + 'O que já está planeado não muda.';
export const TEXTO_A_CARREGAR_ROTAS = 'A carregar as definições das rotas…';
export const TEXTO_ROTAS_GUARDADAS = 'Definições das rotas guardadas.';
export const TEXTO_TEMPO_SERVICO = 'Tempo de serviço (min)';
export const TEXTO_GUARDAR = 'Guardar';
export const TEXTO_A_GUARDAR = 'A guardar…';
const TEXTO_FALTA_ALTERACOES = 'Sem alterações por guardar.';

// O tempo de serviço de uma paragem (`dominio/validador_rota.py::TEMPO_SERVICO_MINIMO/MAXIMO`).
export const TEMPO_SERVICO_MINIMO = 1;
export const TEMPO_SERVICO_MAXIMO = 240;
// A ajuda do grupo dos tempos (a página da T3.41): o formulário é `noValidate`, os limites ficam escritos.
export const TEXTO_AJUDA_TEMPO_SERVICO = `Minutos em cada paragem nova, de ${TEMPO_SERVICO_MINIMO} a ${TEMPO_SERVICO_MAXIMO}.`;

// As `HORAS` e os `MINUTOS` de `dominio/definicoes.py`, pela mesma ordem (um tempo por motivo).
export const CHAVES_HORAS = Object.freeze(['rota_hora_saida', 'rota_hora_regresso']);
export const CHAVES_MINUTOS = Object.freeze(MOTIVOS.map((motivo) => `servico_${motivo}_min`));

// Os 6 campos, pela ordem do ecrã. `tipo` é o do `<input>`; os tempos vão juntos, sob o `grupo`.
const ROTULOS_HORAS = Object.freeze({ rota_hora_saida: 'Hora de saída', rota_hora_regresso: 'Hora limite de regresso' });
export const CAMPOS_ROTAS = Object.freeze([
  ...CHAVES_HORAS.map((chave) => Object.freeze({
    chave, rotulo: ROTULOS_HORAS[chave], tipo: 'time', grupo: null, min: null, max: null,
  })),
  ...MOTIVOS.map((motivo, i) => Object.freeze({
    chave: CHAVES_MINUTOS[i],
    rotulo: rotuloMotivo(motivo),
    tipo: 'number',
    grupo: TEXTO_TEMPO_SERVICO,
    min: TEMPO_SERVICO_MINIMO,
    max: TEMPO_SERVICO_MAXIMO,
  })),
]);
const CHAVES = Object.freeze(CAMPOS_ROTAS.map((campo) => campo.chave));

const textoComConteudo = (valor) => typeof valor === 'string' && valor !== '';
const eObjeto = (valor) => valor !== null && typeof valor === 'object' && !Array.isArray(valor);
const SO_ALGARISMOS = /^[0-9]+$/;

// As 6 das rotas, como o servidor as manda: as horas em texto e os minutos inteiros.
const definicoesValidas = (d) => eObjeto(d)
  && CHAVES_HORAS.every((chave) => typeof d[chave] === 'string')
  && CHAVES_MINUTOS.every((chave) => Number.isInteger(d[chave]));

// O valor de um campo como vai no pedido: o texto aparado; nos minutos, um texto só de algarismos passa a
// inteiro. O resto vai como está (o servidor recusa-o com a mensagem dele).
function valorDoPedido(chave, valor) {
  const texto = typeof valor === 'string' ? valor.trim() : valor;
  if (CHAVES_MINUTOS.includes(chave) && typeof texto === 'string' && SO_ALGARISMOS.test(texto)) return Number(texto);
  return texto;
}

// Os valores dos campos (texto) a partir das definições do servidor.
const valoresDe = (definicoes) => Object.fromEntries(CHAVES.map((chave) => [chave, String(definicoes[chave])]));

// --- Funções puras -------------------------------------------------------------------------------

// O corpo do PATCH /api/crm/definicoes: só as definições das rotas que mudaram, pela ordem dos campos. Um
// campo em falta (ou `undefined`) não é uma alteração.
export function corpoDefinicoesRotas(original, valores) {
  const corpo = {};
  for (const chave of CHAVES) {
    if (valores[chave] === undefined) continue;
    const valor = valorDoPedido(chave, valores[chave]);
    if (valor !== original[chave]) corpo[chave] = valor;
  }
  return corpo;
}

// O botão Guardar: {ativo, texto, falta} (falta: porque não se pode guardar, ou null).
export function estadoGuardarRotas({ alterada, aGuardar }) {
  if (aGuardar) return { ativo: false, texto: TEXTO_A_GUARDAR, falta: null };
  if (!alterada) return { ativo: false, texto: TEXTO_GUARDAR, falta: TEXTO_FALTA_ALTERACOES };
  return { ativo: true, texto: TEXTO_GUARDAR, falta: null };
}

// --- Ecrã ----------------------------------------------------------------------------------------

// criarDefinicoesRotas({api, rede, aoMudarVista, aoAvisar, aoFocar})
//   → {vista, iniciar, tentarDeNovo, mudarCampo, guardar, destruir}
//  - api: {obterDefinicoes, alterarDefinicoes} do lib/crm/api.js; rede: o `criarEstadoRede(window, navigator)`;
//  - aoAvisar(texto): "Definições das rotas guardadas." (um toast); aoFocar(chave): o primeiro campo com o
//    erro do 422, pela ordem do ecrã.
// vista: {estado: 'a_carregar'|'falha'|'pronto', falha: null | {mensagem, aTentar},
//         campos: [{chave, rotulo, tipo, grupo, min, max, valor, erro}], camposDesativados, alerta,
//         guardar: {ativo, texto, falta}}
//   — nova a cada mudança e congelada a fundo.
// Criar não pede nada: `iniciar()` pede as definições e ouve a rede; `destruir()` (o separador saiu) faz que
// as respostas que chegarem depois e a rede já não façam nada.
export function criarDefinicoesRotas({
  api, rede, aoMudarVista, aoAvisar, aoFocar,
}) {
  let original = null; // as definições como o servidor as tem
  let valores = null; // o que está nos campos (texto)
  let erros = {}; // {chave: texto} do 422
  let falha = null;
  let aCarregar = false;
  let aGuardar = false;
  let alerta = null;
  let iniciado = false;
  let ativo = true;
  let cancelarRede = () => {};

  const alterada = () => original !== null && Object.keys(corpoDefinicoesRotas(original, valores)).length > 0;
  const estadoAtual = () => estadoGuardarRotas({ alterada: alterada(), aGuardar });

  function montarVista() {
    let estado = 'a_carregar';
    if (original !== null) estado = 'pronto';
    else if (falha !== null) estado = 'falha';
    const campos = original === null ? [] : CAMPOS_ROTAS.map((campo) => Object.freeze({
      ...campo, valor: valores[campo.chave], erro: erros[campo.chave] ?? null,
    }));
    return Object.freeze({
      estado,
      falha: estado === 'falha' ? Object.freeze({ mensagem: falha, aTentar: aCarregar }) : null,
      campos: Object.freeze(campos),
      camposDesativados: aGuardar,
      alerta,
      guardar: Object.freeze(estadoAtual()),
    });
  }

  let vista = montarVista();

  function atualizar() {
    vista = montarVista();
    aoMudarVista?.(vista);
  }

  function aplicar(definicoes) {
    original = definicoes;
    valores = valoresDe(definicoes);
  }

  // --- Carregar ---

  async function carregar() {
    if (!ativo || aCarregar || original !== null) return;
    aCarregar = true;
    atualizar();
    let definicoes;
    try {
      definicoes = await api.obterDefinicoes();
    } catch (erro) {
      aCarregar = false;
      if (!ativo) return;
      falha = textoDoErro(erro);
      atualizar();
      return;
    }
    aCarregar = false;
    if (!ativo) return;
    if (definicoesValidas(definicoes)) aplicar(definicoes);
    else falha = MENSAGEM_ERRO_INESPERADO;
    atualizar();
  }

  // --- Guardar ---

  function mostrarErro(erro) {
    if (erro?.codigo === 'validacao' && eObjeto(erro.campos)) {
      const dosCampos = Object.fromEntries(
        CHAVES.filter((chave) => textoComConteudo(erro.campos[chave])).map((chave) => [chave, erro.campos[chave]]),
      );
      const primeira = Object.keys(dosCampos)[0];
      if (primeira !== undefined) {
        erros = dosCampos;
        atualizar();
        aoFocar?.(primeira);
        return;
      }
    }
    alerta = textoDoErro(erro);
    atualizar();
  }

  async function guardar() {
    if (!ativo || original === null || !estadoAtual().ativo) return;
    const corpo = corpoDefinicoesRotas(original, valores);
    aGuardar = true;
    alerta = null;
    erros = {};
    atualizar();
    let definicoes;
    try {
      definicoes = await api.alterarDefinicoes(corpo);
    } catch (erro) {
      if (!ativo) return;
      aGuardar = false;
      mostrarErro(erro);
      return;
    }
    if (!ativo) return;
    aGuardar = false;
    // Uma resposta que não são as definições: fica o que se tinha (Guardar volta a poder-se usar).
    if (definicoesValidas(definicoes)) aplicar(definicoes);
    atualizar();
    aoAvisar?.(TEXTO_ROTAS_GUARDADAS);
  }

  return {
    get vista() {
      return vista;
    },
    iniciar() {
      if (!ativo || iniciado) return;
      iniciado = true;
      cancelarRede = rede?.aoMudar((ligado) => {
        if (ligado) carregar();
      }) ?? (() => {});
      carregar();
    },
    // "Tentar novamente" (as definições não carregaram); um toque, um pedido.
    tentarDeNovo() {
      if (falha !== null) carregar();
    },
    // O texto de um dos 6 campos, tal e qual escrito.
    mudarCampo(chave, valor) {
      if (!ativo || original === null || aGuardar || !CHAVES.includes(chave) || typeof valor !== 'string') return;
      valores = { ...valores, [chave]: valor };
      const { [chave]: _tirado, ...outros } = erros;
      erros = outros;
      atualizar();
    },
    guardar,
    destruir() {
      ativo = false;
      cancelarRede();
    },
  };
}
