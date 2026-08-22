import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { getFatDashboard } from '../../../lib/faturacao';
import { Card, CardContent } from '../../../components/ui/card';
import { Switch } from '../../../components/ui/switch';
import { Label } from '../../../components/ui/label';
import { Button } from '../../../components/ui/button';
import {
  LayoutDashboard, ShoppingCart, CalendarDays, BarChart3, ArrowUpRight, ArrowDownRight,
  Store, Info, RefreshCw, Rocket, Star, TrendingUp, PackageSearch,
} from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import FatModoDeEmissao from './FatModoDeEmissao';
import { toast } from 'sonner';

// Euro à portuguesa via Intl.NumberFormat('pt-PT', ...): símbolo DEPOIS do
// número, vírgula nos decimais — ex.: 1503.20 -> "1503,20 €" (o pt-PT só
// agrupa milhares a partir de 5 dígitos: 12345.67 -> "12 345,67 €", com
// espaço, não ponto). Não é "€ 1.503,20" como este comentário dizia antes —
// confirmado com Intl.NumberFormat directamente, não de memória. O formato
// é o mesmo em todo o portal (lib/finance.js, MarketingReports.js); não
// mudar aqui isoladamente.
const fmtEUR = (n) => new Intl.NumberFormat('pt-PT', { style: 'currency', currency: 'EUR' }).format(Number(n) || 0);

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

const fmtPct = (n) => {
  const v = Number(n) || 0;
  return `${v >= 0 ? '+' : ''}${v.toLocaleString('pt-PT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
};

// 'YYYY-MM-DD' -> 'dd-mm' (parte a string; sem Date, para nunca tropeçar em fusos).
const ddmm = (iso) => {
  const [, m, d] = String(iso || '').slice(0, 10).split('-');
  return d && m ? `${d}-${m}` : String(iso || '');
};

const MESES_ABREV = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
// 'YYYY-MM' -> 'Ago'
const mesLabel = (m) => {
  const mm = parseInt(String(m || '').slice(5, 7), 10);
  const label = MESES_ABREV[mm - 1] || m;
  return label.charAt(0).toUpperCase() + label.slice(1);
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
const buildArea = (points, { xLeft = 40, xRight = 710, yTop = 30, yBase = 230, yFill = 240 } = {}) => {
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

// Mini gráfico de área (sparkline) para a linha de uma loja — sem eixos nem
// grelha, só a forma da tendência dos últimos 30 dias.
function MiniArea({ pontos, gradId }) {
  const area = useMemo(
    () => buildArea(pontos, { xLeft: 2, xRight: 118, yTop: 4, yBase: 36, yFill: 38 }),
    [pontos]
  );
  if (!area) return null;
  return (
    <svg viewBox="0 0 120 40" className="w-24 h-8 shrink-0" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity="0.35" />
          <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <path d={area.areaPath} fill={`url(#${gradId})`} />
      <path d={area.line} fill="none" stroke="hsl(var(--primary))" strokeWidth="1.5"
        strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

// Mini gráfico de barras (últimos 6 meses) para a linha de uma loja — sem
// eixos nem legendas, só a forma da tendência mensal.
function MiniBars({ pontos }) {
  const b = useMemo(
    () => buildBars(pontos, { xLeft: 0, slot: 16, barW: 11, yTop: 4, yBase: 34, minH: 1.5 }),
    [pontos]
  );
  if (!b) return null;
  return (
    <svg viewBox="0 0 96 40" className="w-24 h-10 shrink-0" xmlns="http://www.w3.org/2000/svg">
      {b.bars.map((bar, i) => (
        <path key={i} d={roundedBarPath(bar.x, bar.y, bar.w, bar.h, 2, bar.neg ? 'bottom' : 'top')}
          fill="hsl(var(--primary))" fillOpacity={bar.neg ? 0.55 : 0.85} />
      ))}
    </svg>
  );
}

// Pastilha da variação — verde quando >=0, vermelha quando negativa; e a
// frase por extenso quando não há período anterior comparável (nunca "0%"
// nem "—" sem explicação).
function VariacaoPill({ variacao }) {
  if (variacao == null) {
    return <span className="text-xs text-muted-foreground">Sem período anterior comparável</span>;
  }
  const up = variacao >= 0;
  return (
    <span className={`inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-xs font-semibold ${
      up ? 'bg-success/10 text-success' : 'bg-destructive/10 text-destructive'}`}>
      {up ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
      {fmtPct(variacao)}
    </span>
  );
}

// Estado vazio compacto para os cartões "Mais Vendidos" / "Mais Rentáveis"
// (sem dados enquanto o POS próprio não guardar linhas de artigo).
function EmptyMini({ icon: Icon }) {
  return (
    <div className="flex flex-col items-center gap-2 py-6 text-center">
      <Icon className="h-9 w-9 text-muted-foreground/50" strokeWidth={1.5} />
      <p className="text-sm text-muted-foreground">Sem informação disponível</p>
    </div>
  );
}

const CARTOES = [
  { key: 'hoje', prefixo: 'Faturação', sufixo: 'Hoje', icon: ShoppingCart },
  { key: 'mensal', prefixo: 'Faturação', sufixo: 'Mensal', icon: CalendarDays },
  { key: 'anual', prefixo: 'Faturação', sufixo: 'Anual', icon: BarChart3 },
];

export default function FatDashboard() {
  const [comIva, setComIva] = useState(true);
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setErro(false);
    try {
      const { data } = await getFatDashboard(comIva);
      setDashboard(data);
    } catch (error) {
      toast.error('Erro ao carregar o dashboard de faturação');
      setErro(true);
    } finally {
      setLoading(false);
    }
  }, [comIva]);

  useEffect(() => { load(); }, [load]);

  // ---------- Gráfico de ÁREA (faturação diária, últimos 30 dias) ----------
  const areaPrincipal = useMemo(() => {
    const pontos = (dashboard?.serie_diaria || []).map((p) => ({ data: p.data, v: Number(p.valor) || 0 }));
    const area = buildArea(pontos);
    if (!area) return null;
    // Sempre 5 linhas de grelha, uniformemente espaçadas na ALTURA do
    // desenho — é textura visual (papel quadriculado), independente dos
    // valores. As ETIQUETAS de valor é que só fazem sentido quando há
    // amplitude real: com a série toda no mesmo valor (tipicamente 0 — sem
    // vendas ainda), mostrar a mesma etiqueta 5 vezes empilhada seria um
    // bug visual, não "mais informação" — mostra-se UMA, junto da linha
    // onde o valor realmente está.
    const gridLines = [0, 0.25, 0.5, 0.75, 1].map((f) => 30 + f * (230 - 30));
    const achatada = area.max === area.min;
    const gridLabels = achatada
      ? [{ y: area.yAt(0), label: fmtEURShort(0) }]
      : [0, 0.25, 0.5, 0.75, 1].map((f) => {
          const valor = area.min + f * (area.max - area.min);
          return { y: area.yAt(valor), label: fmtEURShort(valor) };
        });
    const nLabels = Math.min(6, area.n);
    const seen = new Set();
    const xLabels = [];
    for (let k = 0; k < nLabels; k++) {
      const idx = nLabels === 1 ? 0 : Math.round((k * (area.n - 1)) / (nLabels - 1));
      if (seen.has(idx)) continue;
      seen.add(idx);
      xLabels.push({ x: area.coords[idx].x, label: ddmm(pontos[idx].data) });
    }
    return { ...area, gridLines, gridLabels, xLabels };
  }, [dashboard]);

  // ---------- Gráfico de BARRAS (últimos 6 meses) ----------
  const barras = useMemo(() => {
    const lista = (dashboard?.ultimos_6_meses || []).map((m) => ({ mes: m.mes, v: Number(m.valor) || 0 }));
    const b = buildBars(lista, { xLeft: 42, slot: 58, barW: 32, yTop: 14, yBase: 150, minH: 3 });
    if (!b) return { lista: [] };
    const gridLines = [0, 0.25, 0.5, 0.75, 1].map((f) => b.yTop + f * (b.yBase - b.yTop));
    const achatada = b.max === b.min;
    const gridLabels = achatada
      ? [{ y: b.yAt(0), label: fmtEURShort(0) }]
      : [0, 0.25, 0.5, 0.75, 1].map((f) => {
          const valor = b.min + f * (b.max - b.min);
          return { y: b.yAt(valor), label: fmtEURShort(valor) };
        });
    return { lista: b.bars, gridLines, gridLabels, yBase: b.yBase, width: b.width };
  }, [dashboard]);

  const cartoes = dashboard?.cartoes || {};
  const porLoja = dashboard?.por_loja || [];
  const maisVendidos = dashboard?.mais_vendidos || [];
  const maisRentaveis = dashboard?.mais_rentaveis || [];
  const semVendas = !!dashboard && !dashboard.ha_vendas;

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fat-dashboard-page">
      <PageHeader icon={LayoutDashboard} title="Dashboard" subtitle="Faturação · Gestão">
        <div className="flex items-center gap-2">
          {/* Sinal discreto de que há um pedido novo em curso — sem isto, ao
              mudar o interruptor com o dashboard já carregado, os números
              trocavam sem nenhum aviso de que tinham sido recarregados. */}
          {loading && dashboard && (
            <RefreshCw className="h-3.5 w-3.5 text-muted-foreground animate-spin" data-testid="fat-dashboard-a-actualizar" />
          )}
          <Switch id="fat-vat-toggle" checked={comIva} onCheckedChange={setComIva} data-testid="fat-vat-toggle" />
          <Label htmlFor="fat-vat-toggle" className="text-sm cursor-pointer whitespace-nowrap">Valores c/ IVA</Label>
        </div>
      </PageHeader>

      {/* Em que modo é que as lojas estão a emitir. Fica ANTES dos números:
          uma receita do dia lida por baixo de um POS em modo de testes é uma
          receita que não existe. */}
      <FatModoDeEmissao />

      {loading && !dashboard ? (
        <div className="flex items-center justify-center h-40">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
        </div>
      ) : erro && !dashboard ? (
        <Card>
          <CardContent className="py-12 text-center space-y-3">
            <p className="text-muted-foreground text-sm">Não foi possível carregar o dashboard.</p>
            <Button variant="outline" onClick={load} data-testid="fat-dashboard-retry">
              <RefreshCw className="h-4 w-4 mr-2" />Tentar novamente
            </Button>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* Faixa "ainda sem vendas" — o ecrã continua completo por baixo,
              a zeros, à espera que o POS comece a faturar. */}
          {semVendas && (
            <Card className="border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/30" data-testid="fat-dashboard-sem-vendas">
              <CardContent className="p-4 flex items-start gap-3">
                <div className="h-9 w-9 rounded-full bg-amber-100 dark:bg-amber-900/50 flex items-center justify-center shrink-0">
                  <Info className="h-4 w-4 text-amber-600 dark:text-amber-400" />
                </div>
                <div>
                  <p className="text-sm font-medium text-amber-900 dark:text-amber-200">Ainda não há vendas registadas</p>
                  <p className="text-xs text-amber-800/80 dark:text-amber-300/80 mt-0.5">
                    Os números abaixo acendem sozinhos assim que o Ponto de Venda começar a faturar. A estrutura já está pronta à espera dos dados.
                  </p>
                </div>
              </CardContent>
            </Card>
          )}

          {/* ---------- Cartão largo: 3 métricas + gráfico de área diário ---------- */}
          <Card>
            <CardContent className="p-0">
              <div className="grid grid-cols-1 sm:grid-cols-3 divide-y sm:divide-y-0 sm:divide-x divide-border">
                {CARTOES.map((k) => {
                  const cartao = cartoes[k.key] || {};
                  return (
                    <div key={k.key} className="p-5 sm:p-6 flex items-start gap-4" data-testid={`fat-cartao-${k.key}`}>
                      <div className="h-[72px] w-[72px] rounded-full bg-primary/10 dark:bg-primary/15 flex items-center justify-center shrink-0">
                        <k.icon className="h-8 w-8 text-primary" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm text-muted-foreground">
                          {k.prefixo} <span className="font-bold">{k.sufixo}</span>
                        </p>
                        <p className="text-[28px] sm:text-[30px] font-heading font-bold text-primary leading-tight mt-1">
                          {fmtEUR(cartao.valor)}
                        </p>
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mt-1.5">
                          <VariacaoPill variacao={cartao.variacao} />
                          <span className="text-xs text-muted-foreground">Anterior: {fmtEUR(cartao.valor_comparado)}</span>
                        </div>
                        {/* A frase que diz exactamente o que foi comparado com o
                            quê — é o que este dashboard tem e o do Vendus não
                            tem. Nunca escondida num tooltip. */}
                        {cartao.comparacao && (
                          <p className="text-xs text-muted-foreground mt-2 pt-2 border-t border-border"
                            data-testid={`fat-cartao-${k.key}-comparacao`}>
                            {cartao.comparacao}
                          </p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="border-t border-border p-4 sm:p-5 space-y-3">
                <p className="text-sm font-semibold">
                  Faturação diária <span className="font-normal text-muted-foreground">· últimos 30 dias</span>
                </p>
                {!areaPrincipal ? (
                  <p className="text-center text-muted-foreground py-10 text-sm">Sem dados para mostrar.</p>
                ) : (
                  <div className="overflow-x-auto">
                    <svg viewBox="0 0 720 260" className="w-full min-w-[560px]" xmlns="http://www.w3.org/2000/svg"
                      data-testid="fat-dashboard-area">
                      <defs>
                        <linearGradient id="fatDashboardAreaGrad" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity="0.35" />
                          <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity="0.02" />
                        </linearGradient>
                      </defs>
                      {areaPrincipal.gridLines.map((y, i) => (
                        <line key={i} x1="40" y1={y} x2="710" y2={y} stroke="hsl(var(--border))" strokeWidth="1" />
                      ))}
                      {areaPrincipal.gridLabels.map((g, i) => (
                        <text key={i} x="36" y={g.y + 3.5} textAnchor="end" fontSize="10" fill="hsl(var(--muted-foreground))">
                          {g.label}
                        </text>
                      ))}
                      <path d={areaPrincipal.areaPath} fill="url(#fatDashboardAreaGrad)" />
                      <path d={areaPrincipal.line} fill="none" stroke="hsl(var(--primary))" strokeWidth="2.5"
                        strokeLinejoin="round" strokeLinecap="round" />
                      {areaPrincipal.xLabels.map((l, i) => (
                        <text key={i} x={l.x} y="254" textAnchor="middle" fontSize="10" fill="hsl(var(--muted-foreground))">
                          {l.label}
                        </text>
                      ))}
                    </svg>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          {/* ---------- Mais Vendidos · Mais Rentáveis · Últimos 6 meses ---------- */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-stretch">
            <Card className="flex flex-col">
              <CardContent className="p-4 sm:p-5 flex flex-col flex-1" data-testid="fat-mais-vendidos">
                <div className="flex items-center gap-2">
                  <Rocket className="h-4 w-4 text-primary shrink-0" />
                  <p className="text-sm font-semibold">Mais Vendidos</p>
                  <span className="h-3.5 w-px bg-border" />
                  <span className="text-xs text-muted-foreground">Hoje</span>
                </div>
                <div className="flex-1 flex items-center justify-center">
                  {maisVendidos.length === 0 ? (
                    <EmptyMini icon={PackageSearch} />
                  ) : (
                    <div className="w-full space-y-2 py-2">
                      {maisVendidos.slice(0, 5).map((item, i) => (
                        <div key={item.id || item.nome || i} className="flex items-center justify-between gap-2 text-sm">
                          <span className="truncate">{item.nome || `Artigo ${i + 1}`}</span>
                          <span className="font-semibold text-primary shrink-0">
                            {item.total != null ? fmtEUR(item.total) : item.quantidade ?? ''}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>

            <Card className="flex flex-col">
              <CardContent className="p-4 sm:p-5 flex flex-col flex-1" data-testid="fat-mais-rentaveis">
                <div className="flex items-center gap-2">
                  <Star className="h-4 w-4 text-primary shrink-0" />
                  <p className="text-sm font-semibold">Mais Rentáveis</p>
                  <span className="h-3.5 w-px bg-border" />
                  <span className="text-xs text-muted-foreground">Hoje</span>
                </div>
                <div className="flex-1 flex items-center justify-center">
                  {maisRentaveis.length === 0 ? (
                    <EmptyMini icon={PackageSearch} />
                  ) : (
                    <div className="w-full space-y-2 py-2">
                      {maisRentaveis.slice(0, 5).map((item, i) => (
                        <div key={item.id || item.nome || i} className="flex items-center justify-between gap-2 text-sm">
                          <span className="truncate">{item.nome || `Artigo ${i + 1}`}</span>
                          <span className="font-semibold text-primary shrink-0">
                            {item.total != null ? fmtEUR(item.total) : item.quantidade ?? ''}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>

            <Card className="flex flex-col">
              <CardContent className="p-4 sm:p-5 flex flex-col flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <TrendingUp className="h-4 w-4 text-primary shrink-0" />
                  <p className="text-sm font-semibold">Últimos 6 meses</p>
                </div>
                <div className="flex-1 flex items-center">
                  {barras.lista.length === 0 ? (
                    <EmptyMini icon={BarChart3} />
                  ) : (
                    <div className="overflow-x-auto w-full">
                      <svg viewBox={`0 0 ${barras.width} 190`} className="w-full"
                        style={{ minWidth: Math.max(260, barras.width) }}
                        xmlns="http://www.w3.org/2000/svg" data-testid="fat-dashboard-bars">
                        <defs>
                          <linearGradient id="fatBarsGrad" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity="1" />
                            <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity="0.55" />
                          </linearGradient>
                        </defs>
                        {barras.gridLines.map((y, i) => (
                          <line key={i} x1="38" y1={y} x2={barras.width - 6} y2={y} stroke="hsl(var(--border))" strokeWidth="1" />
                        ))}
                        {barras.gridLabels.map((g, i) => (
                          <text key={i} x="34" y={g.y + 3.5} textAnchor="end" fontSize="9" fill="hsl(var(--muted-foreground))">
                            {g.label}
                          </text>
                        ))}
                        {barras.lista.map((b, i) => (
                          <g key={i}>
                            <path d={roundedBarPath(b.x, b.y, b.w, b.h, 5, b.neg ? 'bottom' : 'top')} fill="url(#fatBarsGrad)" />
                            <text x={b.cx} y={barras.yBase + 15} textAnchor="middle" fontSize="10" fill="hsl(var(--muted-foreground))">
                              {mesLabel(b.mes)}
                            </text>
                          </g>
                        ))}
                      </svg>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>

          {/* ---------- Uma linha por loja ---------- */}
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3 flex-wrap px-1">
              <h2 className="font-heading font-semibold text-base">Por loja</h2>
              {(cartoes.hoje?.comparacao || cartoes.mensal?.comparacao) && (
                <p className="text-xs text-muted-foreground">
                  Hoje e Mensal comparados com os mesmos períodos dos cartões acima.
                </p>
              )}
            </div>

            {porLoja.length === 0 ? (
              <Card>
                <CardContent className="py-8">
                  <p className="text-center text-muted-foreground text-sm">Sem lojas registadas.</p>
                </CardContent>
              </Card>
            ) : (
              porLoja.map((loja) => (
                <Card key={loja.loja_id} data-testid={`fat-loja-row-${loja.loja_id}`}>
                  <CardContent className="p-4 sm:p-5">
                    <div className="flex flex-col lg:flex-row lg:items-center gap-4">
                      <div className="flex items-center gap-2.5 min-w-0 lg:w-52 shrink-0">
                        <div className="h-9 w-9 rounded-lg bg-primary/10 dark:bg-primary/15 flex items-center justify-center shrink-0">
                          <Store className="h-4 w-4 text-primary" />
                        </div>
                        <span className="font-heading font-bold text-sm truncate">{loja.nome}</span>
                      </div>

                      <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-5 sm:gap-0 sm:divide-x sm:divide-border lg:border-l lg:border-border">
                        {/* Hoje */}
                        <div className="flex items-center justify-between gap-3 sm:pr-5 lg:pl-5">
                          <div className="min-w-0">
                            <p className="text-xs text-muted-foreground">Hoje</p>
                            <p className="text-xl font-heading font-bold text-primary leading-tight mt-0.5">
                              {fmtEUR(loja.hoje)}
                            </p>
                            <div className="flex flex-wrap items-center gap-1.5 mt-1">
                              <VariacaoPill variacao={loja.variacao_hoje} />
                              <span className="text-xs text-muted-foreground">Ontem: {fmtEUR(loja.hoje_anterior)}</span>
                            </div>
                          </div>
                          <MiniArea
                            pontos={(loja.serie_diaria || []).map((p) => ({ v: Number(p.valor) || 0 }))}
                            gradId={`fatLojaGradHoje-${loja.loja_id}`}
                          />
                        </div>

                        {/* Mensal */}
                        <div className="flex items-center justify-between gap-3 sm:pl-5">
                          <div className="min-w-0">
                            <p className="text-xs text-muted-foreground">Mensal</p>
                            <p className="text-xl font-heading font-bold text-primary leading-tight mt-0.5">
                              {fmtEUR(loja.mensal)}
                            </p>
                            <div className="flex flex-wrap items-center gap-1.5 mt-1">
                              <VariacaoPill variacao={loja.variacao_mensal} />
                              <span className="text-xs text-muted-foreground">Anterior: {fmtEUR(loja.mensal_anterior)}</span>
                            </div>
                          </div>
                          <MiniBars pontos={(loja.serie_mensal || []).map((p) => ({ v: Number(p.valor) || 0 }))} />
                        </div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))
            )}
          </div>
        </>
      )}
    </div>
  );
}
