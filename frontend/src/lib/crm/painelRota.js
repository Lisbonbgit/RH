// O painel do planeador da rota (plano F3 T3.38), sem DOM: o que a página `pages/crm/CrmRota.js` e o
// `components/crm/ResumoRota.js` desenham a partir da `vista` do planeador (`lib/crm/planeador.js`).
//  - `seccoesDoPainel(vista.seccoes)`: as listas das paragens, pela ordem "Rota" (a única que se arrasta),
//    "⚠️ Fechadas neste dia" (com "Manter"), "⚠️ Não cabem no horário" (com "Pôr na rota") e "Lojas
//    apagadas" (só "Retirar"); só as que têm paragens;
//  - `totaisDoResumo(vista.totais)`: a distância, a condução e o regresso previsto (com o aviso quando passa
//    do limite), `antigos` quando as horas não são as atuais (o ecrã esbate-os);
//  - `botoesDoResumo(vista.acoes, vista.calculo)`: "Calcular melhor ordem", "Recalcular horas" e "Guardar
//    rota", cada um desligado com o motivo; os motivos iguais escrevem-se uma vez (sem rede, os três dizem o
//    mesmo) e cada botão aponta para o seu (`motivo`, a posição em `motivos`: o `aria-describedby`). A
//    mensagem do último cálculo que falhou só aparece se não repetir um motivo (sem a chave do
//    openrouteservice é a mesma do "Calcular").
// Tudo sai congelado. Os textos são da página; os da rota (estado, avisos, horas) vêm já na `vista`.

export const TITULO_PAINEL = 'Painel da rota';
export const TITULO_RESUMO = 'Resumo da rota';
export const TITULO_BLOCOS_GOOGLE = 'Navegação no Google Maps';
// O bloco próprio da atribuição do openrouteservice, no fim do painel (nunca sobre o mapa).
export const TITULO_ATRIBUICAO_ORS = 'Cálculo das rotas';
export const TEXTO_ROTAS = 'Rotas';
export const TEXTO_VOLTAR_AS_ROTAS = 'Voltar às Rotas';
export const TEXTO_TENTAR_DE_NOVO = 'Tentar novamente';
export const TEXTO_RECARREGAR = 'Recarregar';
export const TEXTO_A_RECARREGAR = 'A recarregar…';
// A pergunta do "Guardar rota" com paragens que não cabem (`vista.acoes.guardar.pergunta`).
export const TEXTO_GUARDAR_MESMO_ASSIM = 'Guardar mesmo assim';
// O que acontece às que não cabem (§1 "Não cabem": no fim da lista e sem hora).
export const TEXTO_GUARDAR_NAO_CABEM = 'As que não cabem ficam no fim da rota, sem hora prevista.';
export const TEXTO_CANCELAR = 'Cancelar';

export const TITULOS_SECCOES = Object.freeze({
  rota: 'Rota',
  fechadas: '⚠️ Fechadas neste dia',
  naoCabem: '⚠️ Não cabem no horário',
  semLoja: 'Lojas apagadas',
});

export const ROTULOS_TOTAIS = Object.freeze({ distancia: 'Distância', duracao: 'Condução', regresso: 'Regresso previsto' });

const ORDEM_SECCOES = Object.freeze(['rota', 'fechadas', 'naoCabem', 'semLoja']);
const ORDEM_TOTAIS = Object.freeze(['distancia', 'duracao', 'regresso']);
const ORDEM_BOTOES = Object.freeze(['calcular', 'recalcular', 'guardar']);

const eObjeto = (valor) => valor !== null && typeof valor === 'object' && !Array.isArray(valor);
const eTexto = (valor) => typeof valor === 'string' && valor !== '';

function congelarAFundo(valor) {
  if (valor !== null && typeof valor === 'object') {
    Object.values(valor).forEach(congelarAFundo);
    Object.freeze(valor);
  }
  return valor;
}

// As listas das paragens do painel: [{chave, titulo, linhas, arrastavel, comManter, comPorNaRota}]. As
// `linhas` são as da vista (a mesma lista); as de cada linha não se congelam aqui (já vêm congeladas).
export function seccoesDoPainel(seccoes) {
  const lista = ORDEM_SECCOES
    .filter((chave) => Array.isArray(seccoes?.[chave]) && seccoes[chave].length > 0)
    .map((chave) => Object.freeze({
      chave,
      titulo: TITULOS_SECCOES[chave],
      linhas: seccoes[chave],
      arrastavel: chave === 'rota',
      comManter: chave === 'fechadas',
      comPorNaRota: chave === 'naoCabem',
    }));
  return Object.freeze(lista);
}

// Os totais do último cálculo (`vista.totais`, o `totaisDaRota`): {itens: [{chave, rotulo, valor, aviso}],
// antigos}, ou null sem nada para mostrar.
export function totaisDoResumo(totais) {
  const itens = ORDEM_TOTAIS
    .filter((chave) => eTexto(totais?.[chave]))
    .map((chave) => ({
      chave,
      rotulo: ROTULOS_TOTAIS[chave],
      valor: totais[chave],
      aviso: chave === 'regresso' && totais.regressoTarde === true,
    }));
  if (itens.length === 0) return null;
  return congelarAFundo({ itens, antigos: totais.atual !== true });
}

// Os botões das ações (`vista.acoes`, o `acoesDaRota`) e a mensagem do último cálculo (`vista.calculo`):
// {botoes: [{chave, texto, ativo, motivo}], motivos: [texto], mensagem}, ou null sem ações (só de leitura).
export function botoesDoResumo(acoes, calculo) {
  if (!eObjeto(acoes)) return null;
  const motivos = [];
  const botoes = ORDEM_BOTOES
    .filter((chave) => eObjeto(acoes[chave]))
    .map((chave) => {
      const { texto, ativo, falta } = acoes[chave];
      const ligado = ativo === true;
      let motivo = null;
      if (!ligado && eTexto(falta)) {
        if (!motivos.includes(falta)) motivos.push(falta);
        motivo = motivos.indexOf(falta);
      }
      return { chave, texto, ativo: ligado, motivo };
    });
  const mensagem = eTexto(calculo?.mensagem) && !motivos.includes(calculo.mensagem) ? calculo.mensagem : null;
  return congelarAFundo({ botoes, motivos, mensagem });
}
