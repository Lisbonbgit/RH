import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { useOutletContext } from 'react-router-dom';
import { getFinSalesDashboard, syncFinSales, createFinSale, getFinUnits } from '../../../lib/api';
import { eur, todayISO } from '../../../lib/finance';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Switch } from '../../../components/ui/switch';
import { Textarea } from '../../../components/ui/textarea';
import { Card, CardContent } from '../../../components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../components/ui/select';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '../../../components/ui/dialog';
import {
  ShoppingCart, CalendarDays, BarChart3, TrendingUp, RefreshCw, ArrowUpRight, ArrowDownRight, Plus,
} from 'lucide-react';
import { toast } from 'sonner';
import PageHeader from '../../../components/PageHeader';

const UNIT_NONE = '__none__'; // "Comum" (sem loja) no Dialog de novo lançamento

// Euro curto para os eixos dos gráficos (ex.: €1,2k). Datas/valores tratados como números simples.
const eurShort = (n) => {
  const v = Number(n) || 0;
  const abs = Math.abs(v);
  if (abs >= 1000) {
    const k = v / 1000;
    return `€${k.toLocaleString('pt-PT', { maximumFractionDigits: Math.abs(k) >= 10 ? 0 : 1 })}k`;
  }
  return `€${Math.round(v)}`;
};

// 'YYYY-MM-DD' -> 'dd-mm' (parte a string; sem Date para evitar fusos).
const ddmm = (iso) => {
  const [, m, d] = String(iso || '').slice(0, 10).split('-');
  return d && m ? `${d}-${m}` : String(iso || '');
};

// Capitaliza a 1ª letra (labels dos meses vêm minúsculos: "fev").
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

// Variação percentual formatada, com sinal e 2 casas. Devolve null quando não há base.
const fmtVar = (n) => `${n >= 0 ? '+' : ''}${n.toLocaleString('pt-PT', {
  minimumFractionDigits: 2, maximumFractionDigits: 2,
})}%`;

const emptyForm = () => ({ date: todayISO(), amount: '', vat_rate: '', unit_id: UNIT_NONE, note: '' });

export default function FinVendas() {
  // Empresa/loja vêm do SELETOR GLOBAL do topo (sem seletores próprios nesta página).
  const { selectedCompany, selectedUnit } = useOutletContext();
  const companyId = selectedCompany ? selectedCompany.id : 'all';
  const unitId = selectedUnit ? selectedUnit.id : undefined;

  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(false);
  const [withVat, setWithVat] = useState(true); // "Valores c/ IVA" — LIGADO por defeito
  const [syncing, setSyncing] = useState(false);

  // Dialog "Novo lançamento"
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState(emptyForm());
  const [saving, setSaving] = useState(false);
  const [units, setUnits] = useState([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { company_id: companyId };
      if (unitId) params.unit_id = unitId;
      const r = await getFinSalesDashboard(params);
      setDashboard(r.data || null);
    } catch (e) {
      toast.error('Erro ao carregar o dashboard de vendas');
      setDashboard(null);
    } finally {
      setLoading(false);
    }
  }, [companyId, unitId]);

  // Recarrega quando empresa/loja mudam.
  useEffect(() => { load(); }, [load]);

  // Escolhe o valor c/ ou s/ IVA de um objeto {c, s}.
  const pick = useCallback((o) => (o ? Number(withVat ? o.c : o.s) || 0 : 0), [withVat]);

  // ---------- Gráfico de ÁREA (faturação diária, 30 pontos) ----------
  const area = useMemo(() => {
    const pts = (dashboard?.diario || []).map((p) => ({ date: p.date, v: pick(p) }));
    const n = pts.length;
    if (!n) return { n: 0 };
    const X_LEFT = 40, X_RIGHT = 710, Y_TOP = 30, Y_BASE = 230, Y_FILL = 240;
    const max = Math.max(1, ...pts.map((p) => p.v));
    const xAt = (i) => (n === 1 ? (X_LEFT + X_RIGHT) / 2 : X_LEFT + (i / (n - 1)) * (X_RIGHT - X_LEFT));
    const yAt = (v) => Y_BASE - (v / max) * (Y_BASE - Y_TOP);
    const coords = pts.map((p, i) => ({ x: xAt(i), y: yAt(p.v), ...p }));
    const line = coords.map((c, i) => `${i === 0 ? 'M' : 'L'} ${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(' ');
    const areaPath =
      `M ${coords[0].x.toFixed(1)} ${Y_FILL} ` +
      coords.map((c) => `L ${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(' ') +
      ` L ${coords[n - 1].x.toFixed(1)} ${Y_FILL} Z`;
    // Grelha horizontal + labels do eixo Y.
    const grid = [0, 0.25, 0.5, 0.75, 1].map((f) => ({ y: Y_BASE - f * (Y_BASE - Y_TOP), label: eurShort(f * max) }));
    // ~6 datas espaçadas no eixo X.
    const nLabels = Math.min(6, n);
    const seen = new Set();
    const xLabels = [];
    for (let k = 0; k < nLabels; k++) {
      const idx = nLabels === 1 ? 0 : Math.round((k * (n - 1)) / (nLabels - 1));
      if (seen.has(idx)) continue;
      seen.add(idx);
      xLabels.push({ x: xAt(idx), label: ddmm(pts[idx].date) });
    }
    return { n, max, line, areaPath, grid, xLabels, Y_BASE };
  }, [dashboard, pick]);

  // ---------- Gráfico de BARRAS (últimos 6 meses) ----------
  const bars = useMemo(() => {
    const list = (dashboard?.meses6 || []).map((m) => ({ label: m.label, v: pick(m) }));
    if (!list.length) return { list: [] };
    const SLOT = 70, BAR_W = 42, BASE_Y = 186, TOP_Y = 24;
    const usable = BASE_Y - TOP_Y;
    const max = Math.max(1, ...list.map((m) => m.v));
    const rects = list.map((m, i) => {
      const h = m.v > 0 ? Math.max(3, (m.v / max) * usable) : 0;
      const x = i * SLOT + (SLOT - BAR_W) / 2;
      return { ...m, x, w: BAR_W, h, y: BASE_Y - h, cx: i * SLOT + SLOT / 2 };
    });
    return { list: rects, BASE_Y };
  }, [dashboard, pick]);

  // ---------- Sync (por empresa) ----------
  const doSync = async () => {
    setSyncing(true);
    try {
      const res = await syncFinSales(companyId);
      const engine = res.data?.engine === 'moloni' ? 'Moloni' : 'Vendus';
      const written = res.data?.written ?? 0;
      const errors = res.data?.errors || [];
      if (errors.length) {
        toast.warning(`${engine}: ${written} dias sincronizados · ${errors.length} avisos`, { description: errors[0] });
      } else {
        toast.success(`${engine} sincronizado: ${written} dias de vendas`);
      }
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Erro ao sincronizar');
    } finally {
      setSyncing(false);
    }
  };

  // ---------- Dialog: novo lançamento ----------
  const openNew = async () => {
    setForm(emptyForm());
    setDialogOpen(true);
    try {
      const r = await getFinUnits(companyId);
      setUnits(r.data || []);
    } catch (e) {
      setUnits([]);
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await createFinSale({
        company_id: companyId,
        date: form.date || null,
        amount: form.amount === '' ? null : Number(form.amount),
        vat_rate: form.vat_rate === '' ? null : Number(form.vat_rate),
        unit_id: form.unit_id === UNIT_NONE ? null : form.unit_id,
        note: form.note || null,
      });
      toast.success('Venda lançada');
      setDialogOpen(false);
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Erro ao guardar');
    } finally {
      setSaving(false);
    }
  };

  // Uma empresa específica está selecionada? (sync + novo lançamento são por empresa)
  const hasCompany = !!selectedCompany;

  // ---------- KPIs ----------
  const KPIS = [
    { key: 'hoje', label: 'Faturação Hoje', icon: ShoppingCart, prevLabel: 'Ontem' },
    { key: 'mensal', label: 'Faturação Mensal', icon: CalendarDays, prevLabel: 'Anterior' },
    { key: 'anual', label: 'Faturação Anual', icon: BarChart3, prevLabel: 'Anterior' },
  ];

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fin-vendas-page">
      <PageHeader icon={TrendingUp} title="Vendas" subtitle="Faturação por dia, mês e ano">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <Switch id="fin-vat-toggle" checked={withVat} onCheckedChange={setWithVat} data-testid="fin-vat-toggle" />
            <Label htmlFor="fin-vat-toggle" className="text-sm cursor-pointer whitespace-nowrap">Valores c/ IVA</Label>
          </div>
          {hasCompany && (
            <Button variant="outline" onClick={doSync} disabled={syncing}
              title="Sincronizar vendas (Vendus/Moloni)" data-testid="fin-sync-btn">
              <RefreshCw className={`h-4 w-4 mr-2 ${syncing ? 'animate-spin' : ''}`} />
              {syncing ? 'A sincronizar...' : 'Atualizar'}
            </Button>
          )}
          {hasCompany && (
            <Button onClick={openNew} data-testid="fin-new-sale-btn">
              <Plus className="h-4 w-4 mr-2" />Novo lançamento
            </Button>
          )}
        </div>
      </PageHeader>

      {loading && !dashboard ? (
        <div className="flex justify-center h-40 items-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
        </div>
      ) : !dashboard ? (
        <Card><CardContent className="py-12 text-center text-muted-foreground">
          Sem dados de vendas para mostrar. Escolhe uma empresa no topo e usa <b>Atualizar</b> para sincronizar.
        </CardContent></Card>
      ) : (
        <>
          {/* ---------- KPIs ---------- */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {KPIS.map((k) => {
              const block = dashboard[k.key] || {};
              const cur = pick(block.valor);
              const prev = pick(block.anterior);
              const hasPrev = prev !== 0;
              const diff = hasPrev ? ((cur - prev) / prev) * 100 : null;
              const up = diff != null && diff >= 0;
              return (
                <Card key={k.key} data-testid={`fin-kpi-${k.key}`}>
                  <CardContent className="p-5 space-y-3">
                    <div className="flex items-center gap-3">
                      <div className="h-10 w-10 rounded-xl brand-gradient text-white flex items-center justify-center shrink-0">
                        <k.icon className="h-5 w-5" />
                      </div>
                      <p className="text-sm text-muted-foreground">{k.label}</p>
                    </div>
                    <p className="text-2xl font-heading font-bold leading-none">{eur(cur)}</p>
                    <div className="flex items-center gap-2 text-xs">
                      {diff == null ? (
                        <span className="text-muted-foreground">—</span>
                      ) : (
                        <span className={`inline-flex items-center gap-0.5 font-semibold ${
                          up ? 'text-emerald-600 dark:text-emerald-400' : 'text-destructive'}`}>
                          {up ? <ArrowUpRight className="h-3.5 w-3.5" /> : <ArrowDownRight className="h-3.5 w-3.5" />}
                          {fmtVar(diff)}
                        </span>
                      )}
                      <span className="text-muted-foreground">{k.prevLabel}: {eur(prev)}</span>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>

          {/* ---------- Gráfico de ÁREA (diário, 30 dias) ---------- */}
          <Card>
            <CardContent className="p-4 space-y-3">
              <p className="text-sm font-semibold">Faturação diária (últimos 30 dias)</p>
              {area.n === 0 ? (
                <p className="text-center text-muted-foreground py-10 text-sm">Sem vendas neste período.</p>
              ) : (
                <div className="overflow-x-auto">
                  <svg viewBox="0 0 720 260" className="w-full min-w-[560px]" xmlns="http://www.w3.org/2000/svg"
                    data-testid="fin-sales-area">
                    <defs>
                      <linearGradient id="finVendasAreaGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity="0.35" />
                        <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity="0.02" />
                      </linearGradient>
                    </defs>
                    {/* Grelha + labels do eixo Y */}
                    {area.grid.map((g, i) => (
                      <g key={i}>
                        <line x1="40" y1={g.y} x2="710" y2={g.y} stroke="hsl(var(--border))" strokeWidth="1" />
                        <text x="36" y={g.y + 3.5} textAnchor="end" fontSize="10" fill="hsl(var(--muted-foreground))">
                          {g.label}
                        </text>
                      </g>
                    ))}
                    {/* Área + linha */}
                    <path d={area.areaPath} fill="url(#finVendasAreaGrad)" />
                    <path d={area.line} fill="none" stroke="hsl(var(--primary))" strokeWidth="2"
                      strokeLinejoin="round" strokeLinecap="round" />
                    {/* Labels do eixo X */}
                    {area.xLabels.map((l, i) => (
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
              {bars.list.length === 0 ? (
                <p className="text-center text-muted-foreground py-10 text-sm">Sem dados mensais.</p>
              ) : (
                <div className="overflow-x-auto">
                  <svg viewBox="0 0 420 220" className="w-full max-w-xl min-w-[360px]" xmlns="http://www.w3.org/2000/svg"
                    data-testid="fin-sales-bars">
                    {bars.list.map((b, i) => (
                      <g key={i}>
                        {b.h > 0 && (
                          <text x={b.cx} y={b.y - 6} textAnchor="middle" fontSize="9" fill="hsl(var(--muted-foreground))">
                            {eurShort(b.v)}
                          </text>
                        )}
                        <rect x={b.x} y={b.y} width={b.w} height={b.h} rx="6" fill="hsl(var(--primary))" />
                        <text x={b.cx} y={bars.BASE_Y + 18} textAnchor="middle" fontSize="11"
                          fill="hsl(var(--muted-foreground))">
                          {cap(b.label)}
                        </text>
                      </g>
                    ))}
                  </svg>
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}

      {/* ---------- Dialog: novo lançamento manual ---------- */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-md" data-testid="fin-sale-dialog">
          <DialogHeader>
            <DialogTitle>Novo lançamento</DialogTitle>
            <DialogDescription>Lançamento manual de faturação de um dia.</DialogDescription>
          </DialogHeader>
          <form onSubmit={submit} className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label className="text-xs">Data *</Label>
                <Input type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })}
                  required data-testid="fin-s-date" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Valor *</Label>
                <Input type="number" step="0.01" value={form.amount}
                  onChange={(e) => setForm({ ...form, amount: e.target.value })} required data-testid="fin-s-amount" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">IVA %</Label>
                <Input type="number" step="0.01" value={form.vat_rate}
                  onChange={(e) => setForm({ ...form, vat_rate: e.target.value })} placeholder="13" data-testid="fin-s-vat" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Loja</Label>
                <Select value={form.unit_id} onValueChange={(v) => setForm({ ...form, unit_id: v })}>
                  <SelectTrigger data-testid="fin-s-unit"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value={UNIT_NONE}>Comum</SelectItem>
                    {units.map((u) => <SelectItem key={u.id} value={u.id}>{u.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1 col-span-2">
                <Label className="text-xs">Nota</Label>
                <Textarea rows={2} value={form.note}
                  onChange={(e) => setForm({ ...form, note: e.target.value })} data-testid="fin-s-note" />
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>Cancelar</Button>
              <Button type="submit" disabled={saving} data-testid="fin-save-sale-btn">
                {saving ? 'A guardar...' : 'Guardar'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
