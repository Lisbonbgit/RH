import React, { useState, useEffect, useMemo } from 'react';
import { useOutletContext } from 'react-router-dom';
import {
  getFinCompanies, getFinUnits, getFinSales,
  createFinSale, updateFinSale, deleteFinSale, syncFinSales,
} from '../../../lib/api';
import { eur, fmtDate, todayISO, normSup } from '../../../lib/finance';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Badge } from '../../../components/ui/badge';
import { Textarea } from '../../../components/ui/textarea';
import { Card, CardContent } from '../../../components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../components/ui/select';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '../../../components/ui/dialog';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '../../../components/ui/alert-dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../../components/ui/table';
import {
  TrendingUp, Plus, RefreshCw, Pencil, Trash2, Percent, Wallet, PiggyBank, BarChart3,
} from 'lucide-react';
import { toast } from 'sonner';
import PageHeader from '../../../components/PageHeader';

const LS_KEY = 'fin_selected_company';
const COMPANY_ALL = 'all';
const UNIT_NONE = '__none__';   // valor para "Comum" no Dialog (sem loja)
const UNIT_ALL = '__all__';     // valor para "Todas" no filtro

// Mês atual no formato YYYY-MM
const thisMonth = () => todayISO().slice(0, 7);

// Percentagem amigável (0 quando o denominador é 0).
const pct = (num, den) => (den > 0 ? (num / den) * 100 : 0);
const fmtPct = (n) => `${(Number(n) || 0).toLocaleString('pt-PT', { maximumFractionDigits: 1 })}%`;

const emptyForm = () => ({
  date: todayISO(), unit_id: UNIT_NONE, amount: '', vat_rate: '', note: '',
});

export default function FinVendas() {
  const { selectedCompany } = useOutletContext();
  const [companies, setCompanies] = useState([]);
  const [companyId, setCompanyId] = useState('');
  const [units, setUnits] = useState([]);
  const [unitId, setUnitId] = useState(UNIT_ALL);
  const [month, setMonth] = useState(thisMonth());
  const [sales, setSales] = useState([]);
  const [loading, setLoading] = useState(false);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm());
  const [saving, setSaving] = useState(false);
  const [toDelete, setToDelete] = useState(null);
  const [syncing, setSyncing] = useState(false);

  const company = companies.find((c) => c.id === companyId) || null;
  const canEdit = company && (company.role === 'owner' || company.role === 'partner');

  useEffect(() => { loadCompanies(); }, []);
  useEffect(() => {
    if (companyId) {
      localStorage.setItem(LS_KEY, companyId);
      setUnitId(UNIT_ALL);
      loadUnits();
    }
  }, [companyId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (companyId) loadSales();
  }, [companyId, unitId, month]); // eslint-disable-line react-hooks/exhaustive-deps
  // Empresa ativa vem do seletor global do topo (secção Financeiro).
  useEffect(() => {
    setCompanyId(selectedCompany ? selectedCompany.id : COMPANY_ALL);
  }, [selectedCompany]);

  const loadCompanies = async () => {
    try {
      const c = await getFinCompanies();
      setCompanies(c.data);
      // Válido: "Todas as empresas" ou uma empresa existente que não a "Por classificar".
      const valid = companyId === COMPANY_ALL ||
        c.data.some((x) => x.id === companyId && normSup(x.name) !== 'por classificar');
      if (c.data.length && !valid) setCompanyId(COMPANY_ALL);
    } catch (e) {
      toast.error('Erro ao carregar empresas');
    }
  };

  const loadUnits = async () => {
    try {
      const r = await getFinUnits(companyId === COMPANY_ALL ? undefined : companyId);
      setUnits(r.data || []);
    } catch (e) {
      setUnits([]);
    }
  };

  const loadSales = async () => {
    setLoading(true);
    try {
      const params = { company_id: companyId };
      if (month) params.month = month;
      if (unitId !== UNIT_ALL) params.unit_id = unitId;
      const r = await getFinSales(params);
      setSales(r.data || []);
    } catch (e) {
      toast.error('Erro ao carregar vendas');
      setSales([]);
    } finally {
      setLoading(false);
    }
  };

  const companyUnits = companyId === COMPANY_ALL ? units : units.filter((u) => u.company_id === companyId);
  const unitName = (id) => companyUnits.find((u) => u.id === id)?.name || 'Comum';
  const companyName = (id) => companies.find((c) => c.id === id)?.name || '';

  // ---------- KPIs ----------
  const kpis = useMemo(() => {
    let amount = 0, net = 0, cost = 0;
    sales.forEach((s) => {
      amount += Number(s.amount) || 0;
      net += Number(s.amount_net) || 0;
      cost += Number(s.amount_cost) || 0;
    });
    const margin = net - cost;
    return {
      amount, net, cost, margin,
      foodCost: pct(cost, net),   // CMV / vendas líquidas
      marginPct: pct(margin, net),
    };
  }, [sales]);

  // ---------- Gráfico diário (vendas por dia do mês) ----------
  const chart = useMemo(() => {
    // Nº de dias do mês selecionado (fallback: 31).
    let days = 31;
    if (month) {
      const [y, m] = month.split('-').map(Number);
      if (y && m) days = new Date(y, m, 0).getDate();
    }
    const totals = new Array(days).fill(0);
    sales.forEach((s) => {
      const d = String(s.date || '').slice(0, 10);
      if (month && !d.startsWith(month)) return;
      const day = Number(d.slice(8, 10));
      if (day >= 1 && day <= days) totals[day - 1] += Number(s.amount) || 0;
    });
    const max = totals.reduce((m, v) => Math.max(m, v), 0);
    return { days, totals, max };
  }, [sales, month]);

  // ---------- Tabela por loja + dia ----------
  const rows = useMemo(() => {
    const map = {};
    sales.forEach((s) => {
      const day = String(s.date || '').slice(0, 10);
      const key = `${day}|${s.unit_id || ''}`;
      const r = map[key] || {
        key, date: day, unit_id: s.unit_id || null, company_id: s.company_id || null,
        amount: 0, net: 0, cost: 0, manualId: null, manualCount: 0, total: 0,
      };
      r.amount += Number(s.amount) || 0;
      r.net += Number(s.amount_net) || 0;
      r.cost += Number(s.amount_cost) || 0;
      r.total += 1;
      if (s.source === 'manual') { r.manualCount += 1; r.manualId = s.id; }
      map[key] = r;
    });
    return Object.values(map)
      .map((r) => ({ ...r, margin: r.net - r.cost }))
      .sort((a, b) =>
        String(b.date).localeCompare(String(a.date)) ||
        unitName(a.unit_id).localeCompare(unitName(b.unit_id)));
  }, [sales]); // eslint-disable-line react-hooks/exhaustive-deps

  // Mapa rápido id->venda manual (para editar/eliminar pela linha agregada de 1 só lançamento).
  const manualById = useMemo(() => {
    const m = {};
    sales.forEach((s) => { if (s.source === 'manual') m[s.id] = s; });
    return m;
  }, [sales]);

  // ---------- Dialog ----------
  const openNew = () => {
    setEditing(null);
    setForm(emptyForm());
    setDialogOpen(true);
  };
  const openEdit = (sale) => {
    setEditing(sale);
    setForm({
      date: sale.date || todayISO(),
      unit_id: sale.unit_id || UNIT_NONE,
      amount: sale.amount ?? '',
      vat_rate: sale.vat_rate ?? '',
      note: sale.note || '',
    });
    setDialogOpen(true);
  };

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = {
        company_id: companyId,
        date: form.date || null,
        unit_id: form.unit_id === UNIT_NONE ? null : form.unit_id,
        amount: form.amount === '' ? null : Number(form.amount),
        vat_rate: form.vat_rate === '' ? null : Number(form.vat_rate),
        note: form.note || null,
      };
      if (editing) {
        await updateFinSale(editing.id, payload);
        toast.success('Venda atualizada');
      } else {
        await createFinSale(payload);
        toast.success('Venda lançada');
      }
      setDialogOpen(false);
      loadSales();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Erro ao guardar');
    } finally {
      setSaving(false);
    }
  };

  const doDelete = async () => {
    try {
      await deleteFinSale(toDelete.id);
      toast.success('Venda eliminada');
      setToDelete(null);
      loadSales();
    } catch (e) {
      toast.error('Erro ao eliminar');
    }
  };

  // Sync rápido (sem CMV — o custo é preenchido pelo cron noturno). O backend
  // escolhe o motor pela empresa: Vendus (lojas) ou Moloni (Purple House).
  const doSync = async () => {
    setSyncing(true);
    try {
      const res = await syncFinSales(companyId);
      const engine = res.data?.engine === 'moloni' ? 'Moloni' : 'Vendus';
      const written = res.data?.written ?? 0;
      const errors = res.data?.errors || [];
      if (errors.length) {
        toast.warning(`${engine}: ${written} dias sincronizados · ${errors.length} avisos`, {
          description: errors[0],
        });
      } else {
        toast.success(`${engine} sincronizado: ${written} dias de vendas`);
      }
      loadSales();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Erro ao sincronizar');
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fin-vendas-page">
      <PageHeader icon={TrendingUp} title="Vendas" subtitle="Receita por loja, food cost e margem">
        <div className="flex items-center gap-2 flex-wrap">
          <Select value={unitId} onValueChange={setUnitId}>
            <SelectTrigger className="w-40" data-testid="fin-unit-picker">
              <SelectValue placeholder="Loja" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={UNIT_ALL}>Todas as lojas</SelectItem>
              {companyUnits.map((u) => <SelectItem key={u.id} value={u.id}>{u.name}</SelectItem>)}
            </SelectContent>
          </Select>
          <Input type="month" value={month} onChange={(e) => setMonth(e.target.value)}
            className="w-36" data-testid="fin-month-picker" />
          {canEdit && (
            <Button variant="outline" onClick={doSync} disabled={syncing}
              title="Sincronizar vendas (Vendus/Moloni, últimos 3 dias)" data-testid="fin-sync-btn">
              <RefreshCw className={`h-4 w-4 mr-2 ${syncing ? 'animate-spin' : ''}`} />
              {syncing ? 'A sincronizar...' : 'Sincronizar'}
            </Button>
          )}
          {canEdit && (
            <Button onClick={openNew} data-testid="fin-new-sale-btn">
              <Plus className="h-4 w-4 mr-2" />Nova venda
            </Button>
          )}
        </div>
      </PageHeader>

      {companies.length === 0 ? (
        <Card><CardContent className="py-12 text-center text-muted-foreground">
          Ainda não tens empresas. Cria uma no separador <b>Início</b> primeiro.
        </CardContent></Card>
      ) : (
        <>
          {/* ---------- KPIs ---------- */}
          <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
            {[
              { label: 'Vendas', value: eur(kpis.amount), icon: TrendingUp },
              { label: 'Vendas líq.', value: eur(kpis.net), icon: Wallet },
              { label: 'CMV', value: eur(kpis.cost), icon: PiggyBank },
              { label: 'Food cost', value: fmtPct(kpis.foodCost), icon: Percent },
              { label: 'Margem bruta', value: eur(kpis.margin), icon: BarChart3 },
              { label: 'Margem %', value: fmtPct(kpis.marginPct), icon: Percent },
            ].map((k) => (
              <Card key={k.label}>
                <CardContent className="flex items-center gap-3 p-4">
                  <div className="h-10 w-10 rounded-xl brand-gradient text-white flex items-center justify-center shrink-0">
                    <k.icon className="h-5 w-5" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-lg font-heading font-bold leading-none truncate">{k.value}</p>
                    <p className="text-xs text-muted-foreground mt-1">{k.label}</p>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* ---------- Gráfico de barras diário ---------- */}
          <Card>
            <CardContent className="p-4 space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold">Vendas por dia</p>
                <p className="text-xs text-muted-foreground">Máx. diário: {eur(chart.max)}</p>
              </div>
              {chart.max === 0 ? (
                <p className="text-center text-muted-foreground py-8 text-sm">Sem vendas neste período.</p>
              ) : (
                <div className="overflow-x-auto">
                  <div className="flex items-end gap-1 h-40 min-w-[480px]" data-testid="fin-sales-chart">
                    {chart.totals.map((v, i) => {
                      const h = chart.max > 0 ? Math.round((v / chart.max) * 100) : 0;
                      return (
                        <div key={i} className="flex-1 flex flex-col items-center justify-end h-full group">
                          <div className="w-full rounded-t brand-gradient transition-all"
                            style={{ height: `${Math.max(v > 0 ? 4 : 0, h)}%` }}
                            title={`Dia ${i + 1}: ${eur(v)}`} />
                          <span className="mt-1 text-[9px] text-muted-foreground tabular-nums">{i + 1}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {/* ---------- Tabela por loja + dia ---------- */}
          <Card>
            <CardContent className="p-4">
              {loading ? (
                <div className="flex justify-center h-24 items-center">
                  <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary" />
                </div>
              ) : rows.length === 0 ? (
                <p className="text-center text-muted-foreground py-10">Sem vendas neste período.</p>
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Data</TableHead>
                        <TableHead>Loja</TableHead>
                        <TableHead className="text-right">Vendas</TableHead>
                        <TableHead className="text-right hidden md:table-cell">Líq.</TableHead>
                        <TableHead className="text-right hidden md:table-cell">CMV</TableHead>
                        <TableHead className="text-right">Margem</TableHead>
                        <TableHead className="text-right">Ações</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {rows.map((r) => {
                        // Linha editável apenas quando agrega exatamente 1 lançamento manual.
                        const editableSale = (r.manualCount === 1 && r.total === 1)
                          ? manualById[r.manualId] : null;
                        return (
                          <TableRow key={r.key} data-testid={`fin-sale-row-${r.key}`}>
                            <TableCell className="whitespace-nowrap">{fmtDate(r.date)}</TableCell>
                            <TableCell className="font-medium">
                              {unitName(r.unit_id)}
                              {companyId === COMPANY_ALL && companyName(r.company_id) && (
                                <span className="ml-2 text-xs text-muted-foreground font-normal">{companyName(r.company_id)}</span>
                              )}
                              {r.manualCount > 0 && <Badge variant="outline" className="ml-2">manual</Badge>}
                            </TableCell>
                            <TableCell className="text-right whitespace-nowrap">{eur(r.amount)}</TableCell>
                            <TableCell className="text-right whitespace-nowrap hidden md:table-cell">{eur(r.net)}</TableCell>
                            <TableCell className="text-right whitespace-nowrap hidden md:table-cell">{eur(r.cost)}</TableCell>
                            <TableCell className="text-right whitespace-nowrap">{eur(r.margin)}</TableCell>
                            <TableCell className="text-right">
                              <div className="flex items-center justify-end gap-1">
                                {canEdit && editableSale && (
                                  <>
                                    <Button variant="ghost" size="icon" className="h-8 w-8" title="Editar"
                                      onClick={() => openEdit(editableSale)} data-testid={`fin-edit-sale-${editableSale.id}`}>
                                      <Pencil className="h-4 w-4" />
                                    </Button>
                                    <Button variant="ghost" size="icon" className="h-8 w-8" title="Eliminar"
                                      onClick={() => setToDelete(editableSale)} data-testid={`fin-delete-sale-${editableSale.id}`}>
                                      <Trash2 className="h-4 w-4 text-destructive" />
                                    </Button>
                                  </>
                                )}
                              </div>
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}

      {/* ---------- Dialog criar/editar venda manual ---------- */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-md" data-testid="fin-sale-dialog">
          <DialogHeader>
            <DialogTitle>{editing ? 'Editar venda' : 'Nova venda'}</DialogTitle>
            <DialogDescription>Lançamento manual de receita de um dia.</DialogDescription>
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
                  onChange={(e) => setForm({ ...form, amount: e.target.value })}
                  required data-testid="fin-s-amount" />
              </div>
              <div className="space-y-1 col-span-2">
                <Label className="text-xs">Loja</Label>
                <Select value={form.unit_id} onValueChange={(v) => setForm({ ...form, unit_id: v })}>
                  <SelectTrigger data-testid="fin-s-unit"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value={UNIT_NONE}>Comum</SelectItem>
                    {companyUnits.map((u) => <SelectItem key={u.id} value={u.id}>{u.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">IVA %</Label>
                <Input type="number" step="0.01" value={form.vat_rate}
                  onChange={(e) => setForm({ ...form, vat_rate: e.target.value })}
                  placeholder="13" data-testid="fin-s-vat" />
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

      {/* ---------- Confirmar eliminar ---------- */}
      <AlertDialog open={!!toDelete} onOpenChange={(o) => !o && setToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar venda</AlertDialogTitle>
            <AlertDialogDescription>
              Eliminar a venda de {fmtDate(toDelete?.date)} ({eur(toDelete?.amount)})?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={doDelete} className="bg-destructive text-destructive-foreground"
              data-testid="fin-confirm-delete-sale">
              Eliminar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
