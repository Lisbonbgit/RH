// Reordenar as paragens da rota (F3 / T3.28): arrastar a pega com o rato ou o dedo, e o teclado.
// Módulo puro, sem DOM nem relógio, e sem bibliotecas (plano F3 §0 regra 6 e §1 "Arrastar"). A
// `ListaParagens` (T3.36) mede as linhas, lê as teclas, desenha e anuncia numa região `aria-live`; as
// decisões estão aqui, porque o jsdom do Jest não faz layout (§10).
//
// - `mover(lista, de, para)`: a lista nova com o elemento `de` na posição `para`, encostada às pontas.
//   O planeador (T3.32) faz `corpoOrdem(rota, mover(idsDaSeccaoRota, de, para))` (rota.js).
// - Arrastar com o ponteiro (Pointer Events, `touch-action: none` na pega):
//   - `deveIniciarArrasto(dx, dy)`: o arrasto só começa depois de 4 px, para um toque não mover nada;
//   - `indiceDestino(y, caixas, de)`: com as caixas das linhas medidas **no início** do arrasto (antes
//     de qualquer `translateY`) e o `y` da linha arrastada (o meio dela, ou o ponteiro) nas mesmas
//     coordenadas, o destino é o número de linhas, sem a arrastada, com o meio acima de `y`;
//   - `desvioDaLinha(i, de, para)`: −1, 0 ou 1 alturas da linha arrastada, para as outras abrirem lugar;
//   - `deslocamentoAutomatico(y, caixa)`: os px a deslocar o contentor em cada passo, perto das pontas.
// - Teclado: `teclaNaLista(estado, {tecla, indice, total, nome, repetida})` → `{estado, acao, anuncio,
//   tratada}`. O `estado` é `null` (nada pegado) ou `{de, para, nome}`; a `acao` só existe ao largar
//   noutro sítio (`{tipo: 'largar', de, para}`); o `anuncio` vai para a região `aria-live`; com
//   `tratada`, a lista chama o `preventDefault` (o Espaço não desloca a página nem carrega no botão). A
//   `tecla` é o `key` do evento (' ', 'Enter', 'ArrowUp', 'ArrowDown', 'Escape', 'Tab'); a `repetida`,
//   o `repeat` (carregar sem largar não pega e larga sem fim). Com a paragem pegada valem o `de` e o
//   nome guardados (a linha com o foco pode ser outra), e o `total` de cada tecla (a lista pode ter
//   mudado). `cancelarMovimento(estado)` é a perda do foco.

export const LIMIAR_ARRASTO_PX = 4;

// A faixa de cada ponta do contentor onde a lista se desloca sozinha, e o passo máximo (px por passo).
export const ZONA_DESLOCAR_PX = 48;
export const PASSO_DESLOCAR_PX = 12;

export const INSTRUCOES_ARRASTAR =
  'Para reordenar: Espaço ou Enter para pegar, setas para mover, Espaço para largar, Escape para cancelar. Também pode arrastar a pega com o rato ou o dedo.';

const TECLA_ESPACO = ' ';
const TECLA_ENTER = 'Enter';
const TECLA_CIMA = 'ArrowUp';
const TECLA_BAIXO = 'ArrowDown';
const TECLA_ESCAPE = 'Escape';
const TECLA_TAB = 'Tab';

const PEGAR_E_LARGAR = Object.freeze([TECLA_ESPACO, TECLA_ENTER]);
const PASSO_DA_SETA = Object.freeze({ [TECLA_CIMA]: -1, [TECLA_BAIXO]: 1 });
const DA_LISTA = Object.freeze([TECLA_ESPACO, TECLA_ENTER, TECLA_CIMA, TECLA_BAIXO, TECLA_ESCAPE]);

const finito = (valor) => Number.isFinite(valor);
const indiceValido = (indice, total) => Number.isInteger(indice) && indice >= 0 && indice < total;
const encostar = (valor, minimo, maximo) => Math.min(Math.max(valor, minimo), maximo);

export function mover(lista, de, para) {
  if (!Array.isArray(lista)) return [];
  const nova = [...lista];
  if (!indiceValido(de, nova.length) || !Number.isInteger(para)) return nova;
  const [elemento] = nova.splice(de, 1);
  nova.splice(encostar(para, 0, nova.length), 0, elemento);
  return nova;
}

export function indiceDestino(y, caixas, de) {
  if (!finito(y) || !Array.isArray(caixas) || !indiceValido(de, caixas.length)) return de;
  let destino = 0;
  caixas.forEach((caixa, i) => {
    if (i !== de && finito(caixa?.top) && finito(caixa?.bottom) && (caixa.top + caixa.bottom) / 2 < y) destino += 1;
  });
  return destino;
}

export function deveIniciarArrasto(dx, dy) {
  return finito(dx) && finito(dy) && Math.hypot(dx, dy) >= LIMIAR_ARRASTO_PX;
}

export function desvioDaLinha(indice, de, para) {
  if (![indice, de, para].every(Number.isInteger)) return 0;
  if (de < para && indice > de && indice <= para) return -1;
  if (de > para && indice >= para && indice < de) return 1;
  return 0;
}

export function deslocamentoAutomatico(y, caixa) {
  if (!finito(y) || !finito(caixa?.top) || !finito(caixa?.bottom) || caixa.bottom <= caixa.top) return 0;
  // Numa lista baixa, cada zona fica com metade da altura: o meio nunca desloca.
  const zona = Math.min(ZONA_DESLOCAR_PX, (caixa.bottom - caixa.top) / 2);
  const passo = (distancia) => Math.ceil((PASSO_DESLOCAR_PX * (zona - Math.max(distancia, 0))) / zona);
  if (y - caixa.top < zona) return -passo(y - caixa.top);
  if (caixa.bottom - y < zona) return passo(caixa.bottom - y);
  return 0;
}

// --- Teclado -------------------------------------------------------------------------------------

const resposta = (estado, acao, anuncio, tratada) => Object.freeze({ estado, acao, anuncio, tratada });
const NADA = resposta(null, null, null, false);

const pegada = (estado) =>
  estado !== null &&
  typeof estado === 'object' &&
  Number.isInteger(estado.de) &&
  estado.de >= 0 &&
  Number.isInteger(estado.para) &&
  estado.para >= 0;

const nomeDaParagem = (nome) => (typeof nome === 'string' ? nome.trim() : '');
const nomeOuNumero = (estado) => nomeDaParagem(estado.nome) || `Paragem ${estado.de + 1}`;

const novoEstado = (de, para, nome) => Object.freeze({ de, para, nome });

function cancelado(estado, tratada) {
  return resposta(null, null, `Movimento cancelado. ${nomeOuNumero(estado)} voltou à posição ${estado.de + 1}.`, tratada);
}

function pegar({ indice, total, nome }) {
  if (!Number.isInteger(total) || !indiceValido(indice, total)) return NADA;
  const estado = novoEstado(indice, indice, nomeDaParagem(nome));
  const quem = estado.nome ? `Paragem ${indice + 1}, ${estado.nome}` : `Paragem ${indice + 1}`;
  return resposta(
    estado,
    null,
    `${quem}, pegada. Posição ${indice + 1} de ${total}. Use as setas para mover, Espaço para largar ou Escape para cancelar.`,
    true,
  );
}

export function teclaNaLista(estado, evento) {
  const { tecla, total, repetida } = evento ?? {};
  if (!pegada(estado)) {
    if (!PEGAR_E_LARGAR.includes(tecla)) return NADA;
    return repetida === true ? resposta(null, null, null, true) : pegar(evento);
  }
  if (!DA_LISTA.includes(tecla) && tecla !== TECLA_TAB) return resposta(estado, null, null, false);
  if (PEGAR_E_LARGAR.includes(tecla) && repetida === true) return resposta(estado, null, null, true);
  // A lista mudou por baixo da paragem pegada: a posição de onde saiu já não quer dizer nada.
  if (!Number.isInteger(total) || estado.de >= total) {
    return resposta(null, null, 'Movimento cancelado.', tecla !== TECLA_TAB);
  }
  if (tecla === TECLA_ESCAPE) return cancelado(estado, true);
  if (tecla === TECLA_TAB) return cancelado(estado, false);
  if (tecla === TECLA_CIMA || tecla === TECLA_BAIXO) {
    const movida = encostar(Math.min(estado.para, total - 1) + PASSO_DA_SETA[tecla], 0, total - 1);
    return resposta(novoEstado(estado.de, movida, estado.nome), null, `Posição ${movida + 1} de ${total}.`, true);
  }
  // Espaço ou Enter: larga.
  const para = Math.min(estado.para, total - 1);
  const acao = para === estado.de ? null : Object.freeze({ tipo: 'largar', de: estado.de, para });
  return resposta(null, acao, `${nomeOuNumero(estado)} largada na posição ${para + 1} de ${total}.`, true);
}

export function cancelarMovimento(estado) {
  return pegada(estado) ? cancelado(estado, false) : NADA;
}
