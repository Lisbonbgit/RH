import React, { useMemo, useRef, useState } from 'react';

// **Os gráficos da faturação, num sítio só.**
//
// Viviam dentro do `FatDashboard.js`. O dono viu a curva do painel e pediu-a
// nos Relatórios: «quero este mesmo tipo nas páginas de relatórios». Copiá-la
// para lá era garantir que um dia as duas discordavam — e a conta que
// converte a posição do rato para o `viewBox` é precisamente onde não se pode
// divergir (já apanhou três defeitos).
//
// **Não vive em `components/`, e isso é deliberado.** O arnês dos testes de
// ecrã substitui tudo o que esteja lá por marcas mudas
// (`test_a_faixa_do_modo_no_ecra`, o ramo `@/components/`), e um gráfico
// substituído por uma `div` deixava de ser medível — que é exactamente o
// defeito que a escolha do artigo do Vendus foi a produção a ter.


// Versão curta para os eixos dos gráficos (ex.: €1,2k).
const fmtEURShort = (n) => {
  const v = Number(n) || 0;
  const abs = Math.abs(v);
  if (abs >= 1000) {
    const k = v / 1000;
    return `€${k.toLocaleString('pt-PT', { maximumFractionDigits: Math.abs(k) >= 10 ? 0 : 1 })}k`;
  }
  return `€${Math.round(v)}`;
};

// Converte uma lista de pontos {x,y} numa curva suave — interpolação cúbica
// de Hermite MONÓTONA (o mesmo método do d3.curveMonotoneX), não um
// Catmull-Rom genérico: a variante monótona tem a garantia (restrição de
// Fritsch-Carlson, mais abaixo) de nunca ultrapassar o valor dos pontos
// vizinhos — ou seja, a curva nunca "salta" para fora da caixa [min,max]
// que os próprios dados definem, mesmo com um pico isolado a seguir a uma
// sequência de zeros. É essa garantia que evita "curva fora do desenho".
// Com 0 ou 1 pontos devolve só o "M" (nada para desenhar); com 2, uma recta
// (não há curvatura possível com dois pontos só).
const smoothPath = (coords) => {
  const n = coords.length;
  const f = (v) => v.toFixed(1);
  if (n === 0) return '';
  if (n === 1) return `M ${f(coords[0].x)} ${f(coords[0].y)}`;
  if (n === 2) return `M ${f(coords[0].x)} ${f(coords[0].y)} L ${f(coords[1].x)} ${f(coords[1].y)}`;

  const slopes = [];
  for (let i = 0; i < n - 1; i++) {
    const h = coords[i + 1].x - coords[i].x;
    slopes.push(h === 0 ? 0 : (coords[i + 1].y - coords[i].y) / h);
  }
  const m = new Array(n);
  m[0] = slopes[0];
  m[n - 1] = slopes[n - 2];
  for (let i = 1; i < n - 1; i++) {
    // Sinais opostos (ou um deles zero) -> um extremo local; a tangente
    // fica plana aí, senão a curva "vergaria" para lá do ponto.
    m[i] = slopes[i - 1] * slopes[i] <= 0 ? 0 : (slopes[i - 1] + slopes[i]) / 2;
  }
  // Restrição de Fritsch-Carlson: encolhe as tangentes para a curva nunca
  // ultrapassar (overshoot) os pontos vizinhos — a parte que faz esta curva
  // ser "monótona" e não um Catmull-Rom qualquer.
  for (let i = 0; i < n - 1; i++) {
    if (slopes[i] === 0) {
      m[i] = 0; m[i + 1] = 0;
      continue;
    }
    const a = m[i] / slopes[i];
    const b = m[i + 1] / slopes[i];
    const h = Math.hypot(a, b);
    if (h > 3) {
      const t = 3 / h;
      m[i] = t * a * slopes[i];
      m[i + 1] = t * b * slopes[i];
    }
  }
  let d = `M ${f(coords[0].x)} ${f(coords[0].y)} `;
  for (let i = 0; i < n - 1; i++) {
    const h = coords[i + 1].x - coords[i].x;
    const cp1x = coords[i].x + h / 3;
    const cp1y = coords[i].y + (m[i] * h) / 3;
    const cp2x = coords[i + 1].x - h / 3;
    const cp2y = coords[i + 1].y - (m[i + 1] * h) / 3;
    d += `C ${f(cp1x)} ${f(cp1y)} ${f(cp2x)} ${f(cp2y)} ${f(coords[i + 1].x)} ${f(coords[i + 1].y)} `;
  }
  return d.trim();
};

// Constrói a curva suave + a área preenchida de um gráfico a partir de uma
// lista de pontos {v}. Genérico (usado no gráfico principal e nos mini-
// -gráficos por loja) — quem chama é que decide as dimensões do desenho.
//
// As notas de crédito são cidadãs de primeira classe neste módulo — um dia
// de saldo negativo é um valor real, não uma excepção. Por isso a escala usa
// SEMPRE mínimo e máximo dos próprios dados (nunca só 0..max): um único dia
// negativo, ou uma série inteira negativa, tem de continuar dentro do
// viewBox, com a linha de base (0€) visível lá dentro — nunca a fugir por
// cima ou por baixo do desenho.
// **As medidas do gráfico grande, num sítio só.**
//
// O dono pôs o painel do Vendus ao lado do nosso: «tem todos os dias do mês.
// fica menor, não fica tão grande como o nosso». As duas coisas saem da mesma
// causa — a PROPORÇÃO do desenho.
//
// Um `viewBox` de 720×260 é quase 3:1. Esticado para a largura do ecrã
// (~1400 px), a altura vai atrás: 505 px de gráfico. O do Vendus é quase
// 6,5:1 e por isso fica baixo.
//
// A largura maior resolve as duas de uma vez: 1400 unidades de desenho
// mostradas em ~1400 px fazem a letra de tamanho 10 sair a 10 px (e não a 19,
// como saía), e nesse tamanho cabem as trinta datas que antes se atropelavam
// — daí só se mostrarem seis.
const AREA = {
  largura: 1400,
  altura: 250,
  xLeft: 46,
  xRight: 1392,
  yTop: 16,
  yBase: 206,
  yFill: 216,
  yLabels: 232,
};

const buildArea = (points, {
  xLeft = AREA.xLeft, xRight = AREA.xRight, yTop = AREA.yTop,
  yBase = AREA.yBase, yFill = AREA.yFill,
} = {}) => {
  const n = points.length;
  if (!n) return null;
  const valores = points.map((p) => p.v);
  // Math.min/max(..., 0) garante que a linha de base (0€) está sempre dentro
  // do intervalo [min, max], mesmo quando todos os valores são positivos
  // (min fica 0, como antes) ou todos negativos (max fica 0).
  const max = Math.max(...valores, 0);
  const min = Math.min(...valores, 0);
  const amplitude = max - min || 1; // evita divisão por zero numa série toda a 0
  const xAt = (i) => (n === 1 ? (xLeft + xRight) / 2 : xLeft + (i / (n - 1)) * (xRight - xLeft));
  const yAt = (v) => yBase - ((v - min) / amplitude) * (yBase - yTop);
  const coords = points.map((p, i) => ({ ...p, x: xAt(i), y: yAt(p.v) }));
  // A área fecha um pouco ABAIXO da linha de base (0€), não do fundo fixo do
  // desenho — preserva o mesmo "sangramento" decorrativo de antes (quando o
  // 0 estava sempre em yBase) também quando a linha de base agora fica a
  // meio do gráfico (série com valores negativos).
  const yFechoArea = yAt(0) + (yFill - yBase);
  const line = smoothPath(coords);
  // A área reaproveita a MESMA curva da linha (nunca reconstrói o traçado à
  // parte) — senão o preenchimento "foge" da linha nos troços mais
  // inclinados. Só troca o arranque (desce até à base) e o fecho.
  const corpoCurva = line.replace(/^M\s+\S+\s+\S+\s*/, '');
  const areaPath =
    `M ${coords[0].x.toFixed(1)} ${yFechoArea.toFixed(1)} ` +
    `L ${coords[0].x.toFixed(1)} ${coords[0].y.toFixed(1)} ` +
    corpoCurva +
    `L ${coords[n - 1].x.toFixed(1)} ${yFechoArea.toFixed(1)} Z`;
  return { n, max, min, yAt, coords, line, areaPath };
};

// Caminho SVG de uma barra com cantos arredondados só de UM lado — o lado
// "de fora" (mais longe da linha de base/0€). 'top' para uma barra positiva
// (cresce para cima), 'bottom' para uma negativa (cresce para baixo, ex.: um
// mês com mais notas de crédito que vendas). Aproxima o arco com uma curva
// quadrática (Q) — suficiente para um raio pequeno como este, sem precisar
// do comando de arco elíptico completo.
const roundedBarPath = (x, y, w, h, r, lado) => {
  const rad = Math.max(0, Math.min(r, w / 2, h));
  if (lado === 'bottom') {
    return `M ${x} ${y} L ${x + w} ${y} L ${x + w} ${y + h - rad} `
      + `Q ${x + w} ${y + h} ${x + w - rad} ${y + h} L ${x + rad} ${y + h} `
      + `Q ${x} ${y + h} ${x} ${y + h - rad} Z`;
  }
  return `M ${x} ${y + h} L ${x} ${y + rad} Q ${x} ${y} ${x + rad} ${y} `
    + `L ${x + w - rad} ${y} Q ${x + w} ${y} ${x + w} ${y + rad} L ${x + w} ${y + h} Z`;
};

// Constrói as barras (posição + altura) de um gráfico de barras a partir de
// pontos {v} — usado no gráfico "Últimos 6 meses" e nos mini-gráficos por
// loja. Mesma filosofia defensiva do buildArea: a escala usa sempre o
// mínimo e o máximo dos PRÓPRIOS dados (nunca só 0..max, para um mês
// negativo — mais notas de crédito que vendas — nunca desaparecer), e mesmo
// um valor exactamente a 0 desenha uma barra mínima em vez de sumir — o
// ecrã tem de ficar completo a zeros, não vazio.
const buildBars = (points, { xLeft = 0, slot = 58, barW = 34, yTop = 10, yBase = 150, minH = 3 } = {}) => {
  const n = points.length;
  if (!n) return null;
  const valores = points.map((p) => p.v);
  const max = Math.max(...valores, 0);
  const min = Math.min(...valores, 0);
  const amplitude = max - min || 1;
  const usable = yBase - yTop;
  const yAt = (v) => yBase - ((v - min) / amplitude) * usable;
  const zeroY = yAt(0);
  const bars = points.map((p, i) => {
    const x = xLeft + i * slot + (slot - barW) / 2;
    const alturaReal = Math.abs(yAt(p.v) - zeroY);
    const h = Math.max(minH, alturaReal);
    const neg = p.v < 0;
    const y = neg ? zeroY : zeroY - h;
    return { ...p, x, y, w: barW, h, neg, cx: xLeft + i * slot + slot / 2 };
  });
  return { n, bars, max, min, yAt, zeroY, yTop, yBase, width: xLeft + n * slot };
};

// --- O toque: a linha de mira e o balão --------------------------------------
//
// O dono mostrou os gráficos do Vendus: o cursor sobre a curva e um balão a
// dizer o dia e o valor. Os desenhos já cá estavam; o que faltava era isto —
// sem o toque, um pico a meio de trinta dias não tem data nenhuma, lê-se a
// olho contra o eixo e não se lê.
//
// UMA peça para os três gráficos (a curva grande, as barras, e os
// mini-gráficos de cada loja): três cópias disto divergiam à terceira
// correcção, e a conta das coordenadas é precisamente onde não se pode
// divergir.

// O índice do ponto MAIS PERTO do rato. O SVG desenha-se num `viewBox` fixo
// e é mostrado com a largura que o cartão tiver — esta função é a ponte
// entre as duas escalas, e é o único sítio onde essa conversão existe.
//
// «Mais perto» e não «por cima»: ninguém acerta com o rato num ponto de 2 px,
// muito menos no rato de um PC de balcão. O leitor aponta para uma zona e o
// gráfico decide qual é o dia.
const indiceMaisPerto = (evento, svg, coords, larguraViewBox) => {
  if (!svg || !coords || coords.length === 0) return null;
  const caixa = svg.getBoundingClientRect();
  // Sem largura não há conversão possível (o elemento ainda não foi medido, ou
  // está escondido) — devolver 0 aqui punha o balão a apontar sempre para o
  // primeiro dia, com ar de estar certo.
  if (!caixa.width) return null;
  const x = ((evento.clientX - caixa.left) / caixa.width) * larguraViewBox;
  let melhor = 0;
  for (let i = 1; i < coords.length; i += 1) {
    if (Math.abs(coords[i].x - x) < Math.abs(coords[melhor].x - x)) melhor = i;
  }
  return melhor;
};

// O balão. O VALOR manda (é o que se veio cá ler) e a etiqueta vem a seguir,
// em tom secundário — ao contrário de uma legenda, onde é o nome que manda.
//
// Encostado à borda o balão sairia do cartão. Em vez de o virar ao contrário
// (que o faz saltar de lado a meio do movimento, e o salto lê-se como avaria),
// limita-se o centro dele a ficar entre 12% e 88%: acompanha o rato até onde
// pode e espera lá.
function BalaoDoGrafico({ xPct, yPct, etiqueta, valor, testid, compacto = false }) {
  const centro = Math.min(0.88, Math.max(0.12, xPct));
  // Encostado ao TOPO não há para onde o empurrar — passa para baixo do ponto.
  // Ao contrário do lado (onde virar faria o balão saltar durante o movimento),
  // aqui a troca é estável: um ponto alto está alto e fica alto. Sem isto, o
  // balão da barra mais alta sai do cartão e vai tapar o título do gráfico —
  // visto a olho, não deduzido.
  const porBaixo = yPct < 0.28;
  return (
    <div
      data-testid={testid}
      data-por-baixo={porBaixo ? 'sim' : 'nao'}
      className={`pointer-events-none absolute z-20 -translate-x-1/2 ${
        porBaixo ? '' : '-translate-y-full'}`}
      style={{
        left: `${centro * 100}%`,
        top: `calc(${yPct * 100}% ${porBaixo ? '+' : '-'} 10px)`,
      }}
    >
      <div className={`rounded-lg border border-border bg-popover shadow-lg whitespace-nowrap ${
        compacto ? 'px-2 py-1' : 'px-2.5 py-1.5'}`}>
        <div className="flex items-center gap-1.5">
          {/* Um traço, não um quadrado: à densidade de um balão, um quadrado
              cheio é tinta com peso de dados a fazer trabalho de etiqueta. */}
          <span className="h-0.5 w-3 rounded-full bg-primary shrink-0" />
          <span className={`font-semibold tabular-nums text-popover-foreground ${
            compacto ? 'text-xs' : 'text-sm'}`}>{valor}</span>
        </div>
        <p className={`text-muted-foreground mt-0.5 ${compacto ? 'text-[10px]' : 'text-[11px]'}`}>
          {etiqueta}
        </p>
      </div>
    </div>
  );
}


// --- O gráfico de ÁREA, inteiro ----------------------------------------------
//
// `pontos`: `[{ rotulo, v }]` — o rótulo é o que se lê no eixo e no balão, o
// `v` é o dinheiro. Quem chama traduz o que tem (uma data, uma loja) para
// isto; este componente não sabe o que é um dia nem um produto.

export const eixoDeValores = (area) => {
  // Sempre 5 linhas de grelha, uniformemente espaçadas na ALTURA do desenho —
  // é textura visual (papel quadriculado), independente dos valores. As
  // ETIQUETAS é que só fazem sentido com amplitude real: com a série toda no
  // mesmo valor (tipicamente 0), a mesma etiqueta cinco vezes empilhada é um
  // defeito visual, não "mais informação".
  const linhas = [0, 0.25, 0.5, 0.75, 1].map(
    (f) => AREA.yTop + f * (AREA.yBase - AREA.yTop));
  const achatada = area.max === area.min;
  const etiquetas = achatada
    ? [{ y: area.yAt(0), label: fmtEURShort(0) }]
    : [0, 0.25, 0.5, 0.75, 1].map((f) => {
        const valor = area.min + f * (area.max - area.min);
        return { y: area.yAt(valor), label: fmtEURShort(valor) };
      });
  return { linhas, etiquetas };
};

export const eixoDeRotulos = (area, pontos, larguraDoRotulo = 30) => {
  // TODOS os rótulos que caibam. Se não couberem, SALTA — um eixo com menos
  // datas é melhor do que um eixo ilegível.
  const porPonto = (AREA.xRight - AREA.xLeft) / Math.max(1, area.n - 1);
  const saltar = Math.max(1, Math.ceil(larguraDoRotulo / porPonto));
  const rotulos = [];
  for (let i = 0; i < area.n; i += saltar) {
    // A ANCORAGEM, e não só a posição: a última fica encostada à borda do
    // `viewBox`, e centrada nesse x metade dela cai fora — lia-se "26-0".
    const x = area.coords[i].x;
    const ancora = x > AREA.largura - 20 ? 'end' : (x < 20 ? 'start' : 'middle');
    rotulos.push({ x, ancora, label: pontos[i].rotulo });
  }
  return rotulos;
};

let sequenciaDeGradientes = 0;

export function GraficoDeArea({ pontos, ariaLabel, testid = 'grafico-area', larguraDoRotulo = 30 }) {
  const svg = useRef(null);
  const [ponto, setPonto] = useState(null);
  // Um id de gradiente POR gráfico: dois gráficos na mesma página com o mesmo
  // id `url(#...)` fazem o segundo apontar para as definições do primeiro, e
  // basta o primeiro desmontar-se para o segundo perder o preenchimento.
  const gradId = useMemo(() => `gradArea${++sequenciaDeGradientes}`, []);

  const area = useMemo(() => {
    const a = buildArea(pontos || []);
    if (!a) return null;
    return { ...a, eixoY: eixoDeValores(a), rotulos: eixoDeRotulos(a, pontos, larguraDoRotulo) };
  }, [pontos, larguraDoRotulo]);

  if (!area) {
    return (
      <p className="text-center text-muted-foreground py-10 text-sm" data-testid={`${testid}-vazio`}>
        Sem dados para mostrar.
      </p>
    );
  }

  const escolhido = ponto != null ? area.coords[ponto] : null;

  return (
    <div className="overflow-x-auto">
      {/* A moldura é o alvo do rato, e não o SVG: um SVG só recebe o rato onde
          tem tinta pintada, e o leitor aponta para o espaço em branco por cima
          da curva tantas vezes como para a curva. A largura mínima vive AQUI e
          não no desenho — as duas têm de ter a MESMA caixa, porque é dela que
          saem as percentagens onde o balão assenta. */}
      <div
        className="relative min-w-[900px] outline-none"
        data-testid={`${testid}-moldura`}
        tabIndex={0}
        role="img"
        aria-label={ariaLabel}
        onPointerMove={(e) => setPonto(indiceMaisPerto(e, svg.current, area.coords, AREA.largura))}
        onPointerLeave={() => setPonto(null)}
        onFocus={() => setPonto((i) => (i == null ? 0 : i))}
        onBlur={() => setPonto(null)}
        /* O teclado. Trinta pontos eram trinta paragens de tabulação — uma
           armadilha, não uma ajuda. Uma paragem só, e as setas andam. */
        onKeyDown={(e) => {
          if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
          e.preventDefault();
          const passo = e.key === 'ArrowRight' ? 1 : -1;
          setPonto((i) => Math.min(area.coords.length - 1,
            Math.max(0, (i == null ? 0 : i) + passo)));
        }}
      >
        <svg viewBox={`0 0 ${AREA.largura} ${AREA.altura}`} className="w-full"
          xmlns="http://www.w3.org/2000/svg" ref={svg} data-testid={testid}>
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity="0.35" />
              <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity="0.02" />
            </linearGradient>
          </defs>
          {area.eixoY.linhas.map((y, i) => (
            <line key={i} x1={AREA.xLeft} y1={y} x2={AREA.xRight} y2={y}
              stroke="hsl(var(--border))" strokeWidth="1" />
          ))}
          {area.eixoY.etiquetas.map((g, i) => (
            <text key={i} x={AREA.xLeft - 6} y={g.y + 3.5} textAnchor="end" fontSize="10"
              fill="hsl(var(--muted-foreground))">{g.label}</text>
          ))}
          <path d={area.areaPath} fill={`url(#${gradId})`} />
          <path d={area.line} fill="none" stroke="hsl(var(--primary))" strokeWidth="2.5"
            strokeLinejoin="round" strokeLinecap="round" />
          {/* A mira e o ponto vêm DEPOIS da curva de propósito: no SVG quem vem
              a seguir fica por cima, e uma mira por baixo do preenchimento não
              se via. */}
          {escolhido && (
            <g data-testid={`${testid}-linha`}>
              <line x1={escolhido.x} y1={AREA.yTop} x2={escolhido.x} y2={AREA.yBase}
                stroke="hsl(var(--primary))" strokeWidth="1" strokeOpacity="0.45"
                strokeDasharray="3 3" />
              {/* Anel da cor do fundo à volta do ponto: sem ele, o ponto
                  some-se dentro da própria curva. */}
              <circle cx={escolhido.x} cy={escolhido.y} r="5" fill="hsl(var(--primary))"
                stroke="hsl(var(--card))" strokeWidth="2" />
            </g>
          )}
          {area.rotulos.map((l, i) => (
            <text key={i} x={l.x} y={AREA.yLabels} textAnchor={l.ancora} fontSize="10"
              fill="hsl(var(--muted-foreground))">{l.label}</text>
          ))}
        </svg>
        {escolhido && (
          <BalaoDoGrafico
            testid={`${testid}-balao`}
            xPct={escolhido.x / AREA.largura}
            yPct={escolhido.y / AREA.altura}
            valor={new Intl.NumberFormat('pt-PT', {
              style: 'currency', currency: 'EUR' }).format(escolhido.v)}
            etiqueta={escolhido.rotulo}
          />
        )}
      </div>
    </div>
  );
}


// --- O gráfico de BARRAS ------------------------------------------------------
//
// Para o que NÃO é uma linha do tempo contínua: as horas do dia, os dias da
// semana, os meses. Uma curva entre «Segunda» e «Terça» desenha uma subida
// que não existe — não há nada entre os dois — e é por isso que estes três
// são barras e os outros são área.
//
// Mesma caixa, mesma grelha, mesmo balão do gráfico de área: são irmãos, e o
// dono passa de um para o outro no mesmo ecrã.

export function GraficoDeBarras({ pontos, ariaLabel, testid = 'grafico-barras' }) {
  const [tocada, setTocada] = useState(null);

  const dados = useMemo(() => {
    const lista = pontos || [];
    if (!lista.length) return null;
    // O espaço reparte-se pelas barras que houver: sete dias da semana ou
    // vinte e quatro horas têm de caber na MESMA caixa, senão os dois ecrãs
    // não parecem o mesmo produto.
    const util = AREA.xRight - AREA.xLeft;
    const slot = util / lista.length;
    // Tecto de 64: com sete barras, uma barra de 190 de largo lia-se como um
    // bloco de cor e não como uma medida.
    const barW = Math.max(4, Math.min(slot * 0.62, 64));
    const b = buildBars(lista, {
      xLeft: AREA.xLeft, slot, barW,
      yTop: AREA.yTop, yBase: AREA.yBase, minH: 2,
    });
    return { ...b, eixoY: eixoDeValores(b) };
  }, [pontos]);

  if (!dados) {
    return (
      <p className="text-center text-muted-foreground py-10 text-sm" data-testid={`${testid}-vazio`}>
        Sem dados para mostrar.
      </p>
    );
  }

  const escolhida = tocada != null ? dados.bars[tocada] : null;

  return (
    <div className="overflow-x-auto">
      <div className="relative min-w-[900px]" data-testid={`${testid}-moldura`}>
        <svg viewBox={`0 0 ${AREA.largura} ${AREA.altura}`} className="w-full"
          xmlns="http://www.w3.org/2000/svg" role="img" aria-label={ariaLabel}
          data-testid={testid}>
          {dados.eixoY.linhas.map((y, i) => (
            <line key={i} x1={AREA.xLeft} y1={y} x2={AREA.xRight} y2={y}
              stroke="hsl(var(--border))" strokeWidth="1" />
          ))}
          {dados.eixoY.etiquetas.map((g, i) => (
            <text key={i} x={AREA.xLeft - 6} y={g.y + 3.5} textAnchor="end" fontSize="10"
              fill="hsl(var(--muted-foreground))">{g.label}</text>
          ))}
          {dados.bars.map((b, i) => (
            <g key={i}>
              <path d={roundedBarPath(b.x, b.y, b.w, b.h, 5, b.neg ? 'bottom' : 'top')}
                fill="hsl(var(--primary))"
                fillOpacity={tocada == null || tocada === i ? 0.9 : 0.35} />
              {/* O alvo do dedo é a COLUNA inteira e não a barra: uma barra de
                  três píxeis (um dia fraco) era impossível de apontar, e é
                  justamente essa que se quer perguntar «quanto foi?». */}
              <rect
                x={b.cx - dados.bars[0].w / 2 - 6} y={AREA.yTop}
                width={b.w + 12} height={AREA.yBase - AREA.yTop}
                fill="transparent" tabIndex={0}
                data-testid={`${testid}-toque-${i}`}
                onPointerOver={() => setTocada(i)}
                onPointerOut={() => setTocada(null)}
                onFocus={() => setTocada(i)}
                onBlur={() => setTocada(null)}
              />
            </g>
          ))}
          {dados.bars.map((b, i) => (
            <text key={i} x={b.cx} y={AREA.yLabels} textAnchor="middle" fontSize="10"
              fill="hsl(var(--muted-foreground))">{b.rotulo}</text>
          ))}
        </svg>
        {escolhida && (
          <BalaoDoGrafico
            testid={`${testid}-balao`}
            xPct={escolhida.cx / AREA.largura}
            yPct={escolhida.y / AREA.altura}
            valor={new Intl.NumberFormat('pt-PT', {
              style: 'currency', currency: 'EUR' }).format(escolhida.v)}
            etiqueta={escolhida.rotulo}
          />
        )}
      </div>
    </div>
  );
}

export { AREA, smoothPath, buildArea, roundedBarPath, buildBars, indiceMaisPerto, BalaoDoGrafico, fmtEURShort };
