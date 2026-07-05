import React, { useState, useEffect, useMemo } from 'react';
import {
  getFinCompanies, getFinInvoices, getFinSupplierRules,
  upsertFinSupplierRule, deleteFinSupplierRule,
} from '../../../lib/api';
import { eur, supplierKeyOf, normSup } from '../../../lib/finance';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Badge } from '../../../components/ui/badge';
import { Card, CardContent } from '../../../components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../components/ui/select';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '../../../components/ui/dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../../components/ui/table';
import { Truck, Search, Plus, Pencil, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import PageHeader from '../../../components/PageHeader';

const LS_KEY = 'fin_selected_company';
const COMPANY_ALL = 'all';

export default function FinFornecedores() {
  const [companies, setCompanies] = useState([]);
  const [companyId, setCompanyId] = useState(localStorage.getItem(LS_KEY) || '');
  const [invoices, setInvoices] = useState([]);
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');

  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => { loadCompanies(); }, []);
  useEffect(() => { if (companyId) { localStorage.setItem(LS_KEY, companyId); loadData(); } }, [companyId]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadCompanies = async () => {
    try {
      const c = await getFinCompanies();
      setCompanies(c.data);
      // Válido: "Todas as empresas" ou uma empresa existente que não a "Por classificar".
      const valid = companyId === COMPANY_ALL ||
        c.data.some((x) => x.id === companyId && normSup(x.name) !== 'por classificar');
      if (c.data.length && !valid) setCompanyId(COMPANY_ALL);
      else if (companyId) loadData();
    } catch (e) { toast.error('Erro ao carregar empresas'); }
  };

  const loadData = async () => {
    setLoading(true);
    try {
      const [inv, r] = await Promise.all([getFinInvoices(companyId), getFinSupplierRules()]);
      setInvoices(inv.data);
      setRules(r.data);
    } catch (e) { toast.error('Erro ao carregar fornecedores'); }
    finally { setLoading(false); }
  };

  const rulesByKey = useMemo(() => {
    const m = {};
    rules.forEach((r) => { m[r.supplier_key] = r; });
    return m;
  }, [rules]);

  // Fornecedores distintos a partir das faturas + regras existentes.
  const suppliers = useMemo(() => {
    const map = {};
    invoices.forEach((i) => {
      const key = supplierKeyOf(i.nif, i.supplier);
      const m = map[key] || { key, name: i.supplier || '(sem nome)', nif: i.nif || '', count: 0, total: 0 };
      m.count += 1;
      m.total += Number(i.amount) || 0;
      if (!m.nif && i.nif) m.nif = i.nif;
      map[key] = m;
    });
    // incluir regras sem faturas neste período
    rules.forEach((r) => {
      if (!map[r.supplier_key]) {
        map[r.supplier_key] = { key: r.supplier_key, name: r.supplier_name || r.supplier_key, nif: '', count: 0, total: 0 };
      }
    });
    const q = search.trim().toLowerCase();
    return Object.values(map)
      .filter((s) => !q || s.name.toLowerCase().includes(q) || String(s.nif).includes(q))
      .sort((a, b) => b.total - a.total);
  }, [invoices, rules, search]);

  const openRule = (sup) => {
    const rule = rulesByKey[sup.key] || {};
    setForm({
      manual: false,
      supplier_name: sup.name === '(sem nome)' ? '' : sup.name,
      nif: sup.nif || '',
      pay_term_days: rule.pay_term_days ?? '',
      direct_debit: !!rule.direct_debit,
      auto_paid: !!rule.auto_paid,
      recurring: !!rule.recurring,
      existing_key: sup.key,
    });
    setDialogOpen(true);
  };

  const openManual = () => {
    setForm({ manual: true, supplier_name: '', nif: '', pay_term_days: '', direct_debit: false, auto_paid: false, recurring: false });
    setDialogOpen(true);
  };

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const supplier_key = supplierKeyOf(form.nif, form.supplier_name);
      await upsertFinSupplierRule({
        supplier_key,
        supplier_name: form.supplier_name || null,
        pay_term_days: form.pay_term_days === '' ? null : Number(form.pay_term_days),
        direct_debit: form.direct_debit,
        auto_paid: form.auto_paid,
        recurring: form.recurring,
      });
      toast.success('Regra guardada');
      setDialogOpen(false);
      loadData();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Erro ao guardar regra');
    } finally { setSaving(false); }
  };

  const removeRule = async (sup) => {
    try { await deleteFinSupplierRule(sup.key); toast.success('Regra removida'); loadData(); }
    catch (e) { toast.error('Erro ao remover regra'); }
  };

  const ruleBadges = (key) => {
    const r = rulesByKey[key];
    if (!r) return <span className="text-xs text-muted-foreground">Sem regra</span>;
    return (
      <div className="flex flex-wrap gap-1">
        {r.pay_term_days != null && <Badge variant="secondary">{r.pay_term_days} dias</Badge>}
        {r.direct_debit ? <Badge variant="secondary">Débito direto</Badge> : null}
        {r.auto_paid ? <Badge variant="secondary">Pago no ato</Badge> : null}
        {r.recurring ? <Badge className="bg-emerald-600 hover:bg-emerald-600">Recorrente</Badge> : null}
      </div>
    );
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fin-fornecedores-page">
      <PageHeader icon={Truck} title="Fornecedores" subtitle="Fichas e regras por fornecedor (partilhadas pela equipa)">
        <div className="flex flex-wrap items-center gap-2">
          {companies.length > 0 && (
            <Select value={companyId} onValueChange={setCompanyId}>
              <SelectTrigger className="w-48"><SelectValue placeholder="Empresa" /></SelectTrigger>
              <SelectContent>
                <SelectItem value={COMPANY_ALL}>Todas as empresas</SelectItem>
                {companies
                  .filter((c) => normSup(c.name) !== 'por classificar')
                  .map((c) => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}
              </SelectContent>
            </Select>
          )}
          <Button onClick={openManual} data-testid="fin-new-rule-btn">
            <Plus className="h-4 w-4 mr-2" />Nova regra
          </Button>
        </div>
      </PageHeader>

      <Card>
        <CardContent className="p-4 space-y-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input className="pl-9" placeholder="Pesquisar por nome ou NIF..."
              value={search} onChange={(e) => setSearch(e.target.value)} data-testid="fin-supplier-search" />
          </div>
          {loading ? (
            <div className="flex justify-center h-24 items-center">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary" />
            </div>
          ) : suppliers.length === 0 ? (
            <p className="text-center text-muted-foreground py-10">Sem fornecedores. Lança faturas ou cria uma regra.</p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Fornecedor</TableHead>
                    <TableHead className="hidden sm:table-cell">NIF</TableHead>
                    <TableHead className="hidden md:table-cell text-right">Faturas</TableHead>
                    <TableHead>Regra</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {suppliers.map((s) => (
                    <TableRow key={s.key} data-testid={`fin-supplier-row-${s.key}`}>
                      <TableCell className="font-medium">{s.name}</TableCell>
                      <TableCell className="hidden sm:table-cell text-muted-foreground">{s.nif || '-'}</TableCell>
                      <TableCell className="hidden md:table-cell text-right text-muted-foreground">
                        {s.count} · {eur(s.total)}
                      </TableCell>
                      <TableCell>{ruleBadges(s.key)}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button variant="ghost" size="icon" className="h-8 w-8" title="Editar regra"
                            onClick={() => openRule(s)} data-testid={`fin-edit-rule-${s.key}`}>
                            <Pencil className="h-4 w-4" />
                          </Button>
                          {rulesByKey[s.key] && (
                            <Button variant="ghost" size="icon" className="h-8 w-8" title="Remover regra"
                              onClick={() => removeRule(s)} data-testid={`fin-delete-rule-${s.key}`}>
                              <Trash2 className="h-4 w-4 text-destructive" />
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Modal de regra */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent data-testid="fin-rule-dialog">
          <DialogHeader>
            <DialogTitle>Regra de fornecedor</DialogTitle>
            <DialogDescription>Aplica-se a todas as empresas da equipa.</DialogDescription>
          </DialogHeader>
          {form && (
            <form onSubmit={submit} className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1 col-span-2">
                  <Label className="text-xs">Fornecedor *</Label>
                  <Input value={form.supplier_name} onChange={(e) => setForm({ ...form, supplier_name: e.target.value })}
                    required disabled={!form.manual} data-testid="fin-rule-name" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">NIF</Label>
                  <Input value={form.nif} onChange={(e) => setForm({ ...form, nif: e.target.value })}
                    inputMode="numeric" disabled={!form.manual} data-testid="fin-rule-nif" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Prazo de pagamento (dias)</Label>
                  <Input type="number" min="0" value={form.pay_term_days}
                    onChange={(e) => setForm({ ...form, pay_term_days: e.target.value })}
                    placeholder="—" data-testid="fin-rule-term" />
                </div>
              </div>
              <div className="space-y-2">
                {[
                  { k: 'direct_debit', label: 'Débito direto', hint: 'Sai da lista "a pagar à mão"' },
                  { k: 'auto_paid', label: 'Pago no ato', hint: 'Fatura entra já paga (lojas físicas)' },
                  { k: 'recurring', label: 'Fornecedor recorrente', hint: 'Faturas por email entram já aprovadas' },
                ].map((opt) => (
                  <label key={opt.k} className="flex items-start gap-2 text-sm cursor-pointer">
                    <input type="checkbox" className="mt-1" checked={!!form[opt.k]}
                      onChange={(e) => setForm({ ...form, [opt.k]: e.target.checked })}
                      data-testid={`fin-rule-${opt.k}`} />
                    <span>
                      <span className="font-medium">{opt.label}</span>
                      <span className="block text-xs text-muted-foreground">{opt.hint}</span>
                    </span>
                  </label>
                ))}
              </div>
              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>Cancelar</Button>
                <Button type="submit" disabled={saving} data-testid="fin-save-rule-btn">
                  {saving ? 'A guardar...' : 'Guardar regra'}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
