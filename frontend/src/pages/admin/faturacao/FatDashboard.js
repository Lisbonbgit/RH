import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { getFatDashboard } from '../../../lib/faturacao';
import { Card, CardContent } from '../../../components/ui/card';
import { Switch } from '../../../components/ui/switch';
import { Label } from '../../../components/ui/label';
import { Button } from '../../../components/ui/button';
import {
  LayoutDashboard, Clock, CalendarDays, BarChart3, ArrowUpRight, ArrowDownRight,
  Store, Info, RefreshCw,
} from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';

// Euro à portuguesa: "€ 1.503,20" — ponto nos milhares, vírgula nos decimais.
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

const CARTOES = [
  { key: 'hoje', label: 'Faturação Hoje', icon: Clock },
  { key: 'mensal', label: 'Faturação Mensal', icon: CalendarDays },
  { key: 'anual', label: 'Faturação Anual', icon: BarChart3 },
];

const TONS = [
  { bg: 'bg-blue-50 dark:bg-blue-950/40', icon: 'text-blue-600 dark:text-blue-400' },
  { bg: 'bg-teal-50 dark:bg-teal-950/40', icon: 'text-teal-600 dark:text-teal-400' },
  { bg: 'bg-violet-50 dark:bg-violet-950/40', icon: 'text-violet-600 dark:text-violet-400' },
];

// Constrói a linha + a área preenchida de um gráfico a partir de uma lista de
// pontos {v}. Genérico (usado no gráfico principal e nos mini-gráficos por
// loja) — quem chama é que decide as dimensões do desenho.
const buildArea = (points, { xLeft = 40, xRight = 710, yTop = 30, yBase = 230, yFill = 240 } = {}) => {
  const n = points.length;
  if (!n) return null;
  const max = Math.max(1, ...points.map((p) => p.v));
  const xAt = (i) => (n === 1 ? (xLeft + xRight) / 2 : xLeft + (i / (n - 1)) * (xRight - xLeft));
  const yAt = (v) => yBase - (v / max) * (yBase - yTop);
  const coords = points.map((p, i) => ({ ...p, x: xAt(i), y: yAt(p.v) }));
  const line = coords.map((c, i) => `${i === 0 ? 'M' : 'L'} ${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(' ');
  const areaPath =
    `M ${coords[0].x.toFixed(1)} ${yFill} ` +
    coords.map((c) => `L ${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(' ') +
    ` L ${coords[n - 1].x.toFixed(1)} ${yFill} Z`;
  return { n, max, coords, line, areaPath };
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
    const grid = [0, 0.25, 0.5, 0.75, 1].map((f) => ({
      y: 230 - f * (230 - 30), label: fmtEURShort(f * area.max),
    }));
    const nLabels = Math.min(6, area.n);
    const seen = new Set();
    const xLabels = [];
    for (let k = 0; k < nLabels; k++) {
      const idx = nLabels === 1 ? 0 : Math.round((k * (area.n - 1)) / (nLabels - 1));
      if (seen.has(idx)) continue;
      seen.add(idx);
      xLabels.push({ x: area.coords[idx].x, label: ddmm(pontos[idx].data) });
    }
    return { ...area, grid, xLabels };
  }, [dashboard]);

  // ---------- Gráfico de BARRAS (últimos 6 meses) ----------
  const barras = useMemo(() => {
    const lista = (dashboard?.ultimos_6_meses || []).map((m) => ({ mes: m.mes, v: Number(m.valor) || 0 }));
    if (!lista.length) return { lista: [] };
    const SLOT = 70, BAR_W = 42, BASE_Y = 186, TOP_Y = 24;
    const usable = BASE_Y - TOP_Y;
    const max = Math.max(1, ...lista.map((m) => m.v));
    const rects = lista.map((m, i) => {
      const h = m.v > 0 ? Math.max(3, (m.v / max) * usable) : 0;
      const x = i * SLOT + (SLOT - BAR_W) / 2;
      return { ...m, x, w: BAR_W, h, y: BASE_Y - h, cx: i * SLOT + SLOT / 2 };
    });
    return { lista: rects, BASE_Y };
  }, [dashboard]);

  const cartoes = dashboard?.cartoes || {};
  const porLoja = dashboard?.por_loja || [];
  const semVendas = !!dashboard && !dashboard.ha_vendas;

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fat-dashboard-page">
      <PageHeader icon={LayoutDashboard} title="Dashboard" subtitle="Faturação · Gestão">
        <div className="flex items-center gap-2">
          <Switch id="fat-vat-toggle" checked={comIva} onCheckedChange={setComIva} data-testid="fat-vat-toggle" />
          <Label htmlFor="fat-vat-toggle" className="text-sm cursor-pointer whitespace-nowrap">Valores c/ IVA</Label>
        </div>
      </PageHeader>

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
                <Info className="h-5 w-5 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-amber-900 dark:text-amber-200">Ainda não há vendas registadas</p>
                  <p className="text-xs text-amber-800/80 dark:text-amber-300/80 mt-0.5">
                    Os números abaixo acendem sozinhos assim que o Ponto de Venda começar a faturar. A estrutura já está pronta à espera dos dados.
                  </p>
                </div>
              </CardContent>
            </Card>
          )}

          {/* ---------- Cartões: Hoje · Mensal · Anual ---------- */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {CARTOES.map((k, i) => {
              const cartao = cartoes[k.key] || {};
              const variacao = cartao.variacao;
              const up = variacao != null && variacao >= 0;
              const tone = TONS[i];
              return (
                <Card key={k.key} data-testid={`fat-cartao-${k.key}`}>
                  <CardContent className="p-5 space-y-2">
                    <div className="flex items-center gap-3">
                      <div className={`h-10 w-10 rounded-xl ${tone.bg} ${tone.icon} flex items-center justify-center shrink-0`}>
                        <k.icon className="h-5 w-5" />
                      </div>
                      <p className="text-sm text-muted-foreground">{k.label}</p>
                    </div>
                    <p className="text-2xl font-heading font-bold leading-none">{fmtEUR(cartao.valor)}</p>
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                      {variacao == null ? (
                        <span className="text-muted-foreground">Sem período anterior comparável</span>
                      ) : (
                        <span className={`inline-flex items-center gap-0.5 font-semibold ${
                          up ? 'text-emerald-600 dark:text-emerald-400' : 'text-destructive'}`}>
                          {up ? <ArrowUpRight className="h-3.5 w-3.5" /> : <ArrowDownRight className="h-3.5 w-3.5" />}
                          {fmtPct(variacao)}
                        </span>
                      )}
                      <span className="text-muted-foreground">vs {fmtEUR(cartao.valor_comparado)}</span>
                    </div>
                    {/* A frase que diz exatamente o que foi comparado com o quê —
                        é o que este dashboard tem e o do Vendus não tem. */}
                    {cartao.comparacao && (
                      <p className="text-xs text-muted-foreground pt-1.5 mt-1.5 border-t" data-testid={`fat-cartao-${k.key}-comparacao`}>
                        {cartao.comparacao}
                      </p>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>

          {/* ---------- Gráfico de ÁREA (diário, 30 dias) ---------- */}
          <Card>
            <CardContent className="p-4 space-y-3">
              <p className="text-sm font-semibold">Faturação diária (últimos 30 dias)</p>
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
                    {areaPrincipal.grid.map((g, i) => (
                      <g key={i}>
                        <line x1="40" y1={g.y} x2="710" y2={g.y} stroke="hsl(var(--border))" strokeWidth="1" />
                        <text x="36" y={g.y + 3.5} textAnchor="end" fontSize="10" fill="hsl(var(--muted-foreground))">
                          {g.label}
                        </text>
                      </g>
                    ))}
                    <path d={areaPrincipal.areaPath} fill="url(#fatDashboardAreaGrad)" />
                    <path d={areaPrincipal.line} fill="none" stroke="hsl(var(--primary))" strokeWidth="2"
                      strokeLinejoin="round" strokeLinecap="round" />
                    {areaPrincipal.xLabels.map((l, i) => (
                      <text key={i} x={l.x} y="254" textAnchor="middle" fontSize="10" fill="hsl(var(--muted-foreground))">
                        {l.label}
                      </text>
                    ))}
                  </svg>
                </div>
              )}
            </CardContent>
          </Card>

          {/* ---------- Gráfico de BARRAS (6 meses) ---------- */}
          <Card>
            <CardContent className="p-4 space-y-3">
              <p className="text-sm font-semibold">Últimos 6 meses</p>
              {barras.lista.length === 0 ? (
                <p className="text-center text-muted-foreground py-10 text-sm">Sem dados mensais.</p>
              ) : (
                <div className="overflow-x-auto">
                  <svg viewBox="0 0 420 220" className="w-full max-w-xl min-w-[360px]" xmlns="http://www.w3.org/2000/svg"
                    data-testid="fat-dashboard-bars">
                    {barras.lista.map((b, i) => (
                      <g key={i}>
                        {b.h > 0 && (
                          <text x={b.cx} y={b.y - 6} textAnchor="middle" fontSize="9" fill="hsl(var(--muted-foreground))">
                            {fmtEURShort(b.v)}
                          </text>
                        )}
                        <rect x={b.x} y={b.y} width={b.w} height={b.h} rx="6" fill="hsl(var(--primary))" />
                        <text x={b.cx} y={barras.BASE_Y + 18} textAnchor="middle" fontSize="11"
                          fill="hsl(var(--muted-foreground))">
                          {mesLabel(b.mes)}
                        </text>
                      </g>
                    ))}
                  </svg>
                </div>
              )}
            </CardContent>
          </Card>

          {/* ---------- Uma linha por loja ---------- */}
          <Card>
            <CardContent className="p-4 space-y-1">
              <p className="text-sm font-semibold mb-2">Por loja</p>
              {porLoja.length === 0 ? (
                <p className="text-center text-muted-foreground py-8 text-sm">Sem lojas registadas.</p>
              ) : (
                <div className="divide-y">
                  {porLoja.map((loja) => (
                    <div key={loja.loja_id} className="flex flex-wrap items-center justify-between gap-4 py-3"
                      data-testid={`fat-loja-row-${loja.loja_id}`}>
                      <div className="flex items-center gap-2 min-w-0">
                        <Store className="h-4 w-4 text-muted-foreground shrink-0" />
                        <span className="font-medium text-sm truncate">{loja.nome}</span>
                      </div>
                      <div className="flex items-center gap-6 shrink-0">
                        <div className="text-right">
                          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Hoje</p>
                          <p className="text-sm font-semibold">{fmtEUR(loja.hoje)}</p>
                        </div>
                        <div className="text-right">
                          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Mensal</p>
                          <p className="text-sm font-semibold">{fmtEUR(loja.mensal)}</p>
                        </div>
                        <MiniArea
                          pontos={(loja.serie_diaria || []).map((p) => ({ v: Number(p.valor) || 0 }))}
                          gradId={`fatLojaGrad-${loja.loja_id}`}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
