// As datas das rotas no frontend (F3 / T3.26): o dia `AAAA-MM-DD`, em hora de Lisboa.
//
// Uma rota por dia (`crm_rotas.data`). O dia vem no caminho (`/crm/rotas/2026-10-12`) e o "hoje" vem
// sempre do servidor (`rota.hoje`; `GET /rotas` → `hoje`, de `relogio.hoje()`): o frontend nunca lê o
// relógio do browser para decidir o dia, porque o fuso do browser pode não ser o de Lisboa. Aqui só
// se valida, se soma e se escreve o dia.
//
// - `eDataValida` é a regra do `ler_data` de backend/crm/dominio/datas.py: exatamente `AAAA-MM-DD`,
//   só algarismos ASCII, um dia que exista (do ano 1 ao 9999, como o `date` do Python). Sem a flag
//   `m`, o `$` do JavaScript só aceita o fim do texto (um "\n" final fica de fora).
// - As contas fazem-se ao meio-dia UTC, com as leituras UTC do `Date`: a mudança de hora nunca mexe
//   num dia de calendário, seja qual for o fuso do browser. O `setUTCFullYear` (e não o `Date.UTC`)
//   guarda os anos abaixo de 100, que o `Date.UTC` passava a 19xx.
// - Os nomes escrevem-se com listas fixas, sem `Intl` nem `toLocale…`: o texto não depende da língua
//   nem do fuso do browser.

// Os nomes dos `dias_fechada` da loja, de segunda a domingo: os `campos_loja.DIAS` do servidor
// (verificado pelo datas.test.js, que lê esse ficheiro).
export const DIAS_SEMANA = Object.freeze(['seg', 'ter', 'qua', 'qui', 'sex', 'sab', 'dom']);

// Os nomes que se escrevem no ecrã, pela mesma ordem (o sábado leva o acento, a chave não).
const DIAS_CURTOS = Object.freeze(['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom']);
const DIAS_LONGOS = Object.freeze([
  'segunda-feira',
  'terça-feira',
  'quarta-feira',
  'quinta-feira',
  'sexta-feira',
  'sábado',
  'domingo',
]);
const MESES = Object.freeze([
  'janeiro',
  'fevereiro',
  'março',
  'abril',
  'maio',
  'junho',
  'julho',
  'agosto',
  'setembro',
  'outubro',
  'novembro',
  'dezembro',
]);
const MESES_CURTOS = Object.freeze(['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']);

const FORMATO = /^([0-9]{4})-([0-9]{2})-([0-9]{2})$/;
const ANO_MINIMO = 1;
const ANO_MAXIMO = 9999;

const doisAlgarismos = (n) => String(n).padStart(2, '0');

// O `Date` ao meio-dia UTC desse dia, ou null.
function meioDiaUtc(ano, mes, dia) {
  const instante = new Date(0);
  instante.setUTCFullYear(ano, mes - 1, dia);
  instante.setUTCHours(12, 0, 0, 0);
  return Number.isNaN(instante.getTime()) ? null : instante;
}

// {ano, mes, dia} de um `AAAA-MM-DD` válido, ou null.
function partes(data) {
  if (typeof data !== 'string') return null;
  const m = FORMATO.exec(data);
  if (m === null) return null;
  const [ano, mes, dia] = [Number(m[1]), Number(m[2]), Number(m[3])];
  if (ano < ANO_MINIMO || mes < 1 || mes > 12 || dia < 1) return null;
  const instante = meioDiaUtc(ano, mes, dia);
  // O 31 de abril passava a 1 de maio: o dia tem de ficar o mesmo.
  if (instante === null || instante.getUTCMonth() !== mes - 1 || instante.getUTCDate() !== dia) return null;
  return { ano, mes, dia, instante };
}

function texto(instante) {
  const ano = instante.getUTCFullYear();
  if (ano < ANO_MINIMO || ano > ANO_MAXIMO) return null;
  return `${String(ano).padStart(4, '0')}-${doisAlgarismos(instante.getUTCMonth() + 1)}-${doisAlgarismos(instante.getUTCDate())}`;
}

// 0 = segunda … 6 = domingo (o `getUTCDay` conta do domingo).
const indiceDoDia = (instante) => (instante.getUTCDay() + 6) % 7;

export function eDataValida(data) {
  return partes(data) !== null;
}

// O dia `n` dias de calendário depois (ou antes, com `n` negativo), ou null se a data não for válida,
// se `n` não for um inteiro ou se o resultado sair dos anos 1 a 9999.
export function somarDias(data, n) {
  const lida = partes(data);
  if (lida === null || !Number.isInteger(n)) return null;
  const instante = new Date(lida.instante.getTime());
  instante.setUTCDate(instante.getUTCDate() + n);
  if (Number.isNaN(instante.getTime())) return null;
  return texto(instante);
}

// "seg" … "dom" (os nomes dos `dias_fechada`), ou null.
export function diaDaSemana(data) {
  const lida = partes(data);
  return lida === null ? null : DIAS_SEMANA[indiceDoDia(lida.instante)];
}

// "Hoje", "Amanhã" ou "seg 19/10" (o dia e o mês com dois algarismos), ou null se uma das datas não
// for válida. `hoje` é o do servidor.
export function rotuloDia(data, hoje) {
  const lida = partes(data);
  if (lida === null || !eDataValida(hoje)) return null;
  if (data === hoje) return 'Hoje';
  if (data === somarDias(hoje, 1)) return 'Amanhã';
  return `${DIAS_CURTOS[indiceDoDia(lida.instante)]} ${doisAlgarismos(lida.dia)}/${doisAlgarismos(lida.mes)}`;
}

// "segunda-feira, 12 de outubro" (o dia sem zero à esquerda), ou null.
export function rotuloDataLonga(data) {
  const lida = partes(data);
  if (lida === null) return null;
  return `${DIAS_LONGOS[indiceDoDia(lida.instante)]}, ${lida.dia} de ${MESES[lida.mes - 1]}`;
}

// "5 nov 2026" (o dia sem zero à esquerda), ou null: a data do último contacto no cartão do mapa, na lista de
// clientes e em cada contacto da ficha.
export function rotuloDataCurta(data) {
  const lida = partes(data);
  if (lida === null) return null;
  return `${lida.dia} ${MESES_CURTOS[lida.mes - 1]} ${lida.ano}`;
}
