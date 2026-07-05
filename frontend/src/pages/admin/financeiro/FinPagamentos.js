import React, { useState, useEffect, useMemo } from 'react';
import {
  getFinCompanies, getFinUnits, getFinInvoices, getFinSupplierRules,
  createFinInvoice, updateFinInvoice, approveFinInvoice, rejectFinInvoice,
  toggleFinInvoicePaid, setFinInvoiceUnit, deleteFinInvoice, cancelFinInvoiceSeries,
} from '../../../lib/api';
import { eur, fmtDate, todayISO, effectiveDue, supplierKeyOf } from '../../../lib/finance';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Badge } from '../../../components/ui/badge';
import { Textarea } from '../../../components/ui/textarea';
import { Card, CardContent } from '../../../components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../../../components/ui/tabs';
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
  Receipt, Plus, Search, Check, X, Pencil, Trash2, CircleDollarSign,
  Clock, AlertTriangle, Wallet,
} from 'lucide-react';
import { toast } from 'sonner';
import PageHeader from '../../../components/PageHeader';

const LS_KEY = 'fin_selected_company';
const COMPANY_ALL = 'all';
const RECURRENCE = [
  { value: 'none', label: 'Não recorrente' },
  { value: 'weekly', label: 'Semanal' },
  { value: 'monthly', label: 'Mensal' },
  { value: 'quarterly', label: 'Trimestral' },
  { value: 'yearly', label: 'Anual' },
];
const UNIT_NONE = '__none__';

const emptyForm = () => ({
  kind: 'invoice', supplier: '', nif: '', invoice_number: '',
  issue_date: todayISO(), due_date: '', amount: '', vat_rate: '',
  description: '', unit_id: UNIT_NONE, recurrence: 'none', paid: false, paid_date: '',
});

export default function FinPagamentos() {
  const [companies, setCompanies] = useState([]);
  const [companyId, setCompanyId] = useState(localStorage.getItem(LS_KEY) || '');
  const [units, setUnits] = useState([]);
  const [invoices, setInvoices] = useState([]);
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm());
  const [saving, setSaving] = useState(false);

  const [toDelete, setToDelete] = useState(null);
  const [agendaView, setAgendaView] = useState('week');

  const company = companies.find((c) => c.id === companyId) || null;
  const canEdit = company && (company.role === 'owner' || company.role === 'partner');
  const companyUnits = companyId === COMPANY_ALL ? units : units.filter((u) => u.company_id === companyId);
  const companyName = (id) => companies.find((c) => c.id === id)?.name || '';

  const rulesByKey = useMemo(() => {
    const m = {};
    rules.forEach((r) => { m[r.supplier_key] = r; });
    return m;
  }, [rules]);
  const ruleFor = (inv) => rulesByKey[supplierKeyOf(inv.nif, inv.supplier)] || null;

  useEffect(() => { loadCompanies(); }, []);
  useEffect(() => {
    if (companyId) { localStorage.setItem(LS_KEY, companyId); loadData(); }
  }, [companyId]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadCompanies = async () => {
    try {
      const [c, r] = await Promise.all([getFinCompanies(), getFinSupplierRules()]);
      setCompanies(c.data);
      setRules(r.data);
      // Válido: "Todas as empresas" ou qualquer empresa existente (incluindo a "Por classificar",
      // que aqui continua visível para tratar as faturas órfãs do email).
      const valid = companyId === COMPANY_ALL || c.data.some((x) => x.id === companyId);
      if (c.data.length && !valid) setCompanyId(COMPANY_ALL);
    } catch (e) {
      toast.error('Erro ao carregar empresas');
    }
  };

  const loadData = async () => {
    setLoading(true);
    try {
      const [inv, u, r] = await Promise.all([
        getFinInvoices(companyId),
        getFinUnits(companyId === COMPANY_ALL ? undefined : companyId),
        getFinSupplierRules(),
      ]);
      setInvoices(inv.data);
      setUnits(u.data);
      setRules(r.data);
    } catch (e) {
      toast.error('Erro ao carregar faturas');
    } finally {
      setLoading(false);
    }
  };

  const unitName = (id) => companyUnits.find((u) => u.id === id)?.name || 'Comum';

  // ---------- Dialog fatura ----------
  const openNew = (kind = 'invoice') => {
    setEditing(null);
    setForm({ ...emptyForm(), kind });
    setDialogOpen(true);
  };
  const openEdit = (inv) => {
    setEditing(inv);
    setForm({
      kind: inv.kind || 'invoice',
      supplier: inv.supplier || '', nif: inv.nif || '', invoice_number: inv.invoice_number || '',
      issue_date: inv.issue_date || '', due_date: inv.due_date || '',
      amount: inv.amount ?? '', vat_rate: inv.vat_rate ?? '',
      description: inv.description || '',
      unit_id: inv.unit_id || UNIT_NONE,
      recurrence: inv.recurrence || 'none',
      paid: !!inv.paid, paid_date: inv.paid_date || '',
    });
    setDialogOpen(true);
  };

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const amount = form.amount === '' ? null : Number(form.amount);
      const rate = form.vat_rate === '' ? null : Number(form.vat_rate);
      let amount_net = null, vat_amount = null;
      if (amount != null && rate != null && rate >= 0) {
        amount_net = +(amount / (1 + rate / 100)).toFixed(2);
        vat_amount = +(amount - amount_net).toFixed(2);
      }
      const payload = {
        company_id: companyId,
        kind: form.kind,
        supplier: form.supplier || null,
        nif: form.nif || null,
        invoice_number: form.invoice_number || null,
        issue_date: form.issue_date || null,
        due_date: form.due_date || null,
        amount, amount_net, vat_amount, vat_rate: rate,
        description: form.description || null,
        unit_id: form.unit_id === UNIT_NONE ? null : form.unit_id,
        recurrence: editing ? 'none' : form.recurrence, // recorrência só ao criar
        paid: !!form.paid,
        paid_date: form.paid_date || null,
      };
      if (editing) {
        await updateFinInvoice(editing.id, payload);
        toast.success('Fatura atualizada');
      } else {
        await createFinInvoice(payload);
        toast.success(form.recurrence !== 'none' ? 'Série recorrente criada' : 'Lançamento criado');
      }
      setDialogOpen(false);
      loadData();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Erro ao guardar');
    } finally {
      setSaving(false);
    }
  };

  const doApprove = async (inv) => { try { await approveFinInvoice(inv.id); toast.success('Aprovada'); loadData(); } catch (e) { toast.error('Erro ao aprovar'); } };
  const doReject = async (inv) => { try { await rejectFinInvoice(inv.id); toast.success('Rejeitada'); loadData(); } catch (e) { toast.error('Erro ao rejeitar'); } };
  const doTogglePaid = async (inv) => {
    try {
      await toggleFinInvoicePaid(inv.id, !inv.paid, !inv.paid ? todayISO() : null);
      loadData();
    } catch (e) { toast.error('Erro ao atualizar pagamento'); }
  };
  const doSetUnit = async (inv, unitId) => {
    try { await setFinInvoiceUnit(inv.id, unitId === UNIT_NONE ? null : unitId); loadData(); }
    catch (e) { toast.error(e.response?.data?.detail || 'Erro ao definir unidade'); }
  };
  const doDelete = async () => {
    try {
      await deleteFinInvoice(toDelete.id);
      toast.success('Eliminada');
      setToDelete(null);
      loadData();
    } catch (e) { toast.error('Erro ao eliminar'); }
  };
  const doCancelSeries = async (inv) => {
    try {
      const res = await cancelFinInvoiceSeries(inv.id);
      toast.success(`Série cancelada (${res.data.cancelled} por pagar)`);
      setToDelete(null);
      loadData();
    } catch (e) { toast.error('Erro ao cancelar série'); }
  };

  // ---------- Derivados ----------
  const active = invoices.filter((i) => i.approval_status !== 'rejected');
  const kpis = useMemo(() => {
    const today = todayISO();
    let aPagar = 0, pago = 0, pendentes = 0, vencidas = 0;
    active.forEach((i) => {
      const val = Number(i.amount) || 0;
      if (i.paid) pago += val; else aPagar += val;
      if (i.approval_status === 'pending') pendentes += 1;
      if (!i.paid) {
        const due = effectiveDue(i, ruleFor(i));
        if (due && due < today) vencidas += 1;
      }
    });
    return { aPagar, pago, pendentes, vencidas };
  }, [active]); // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return invoices;
    return invoices.filter((i) =>
      [i.invoice_number, i.supplier, i.nif, i.issue_date, i.description]
        .filter(Boolean).some((f) => String(f).toLowerCase().includes(q))
    );
  }, [invoices, search]);

  // ---------- Semana atual (Resumo): limites de pagamento por dia ----------
  // Segunda→domingo, com as faturas POR PAGAR cujo vencimento efetivo (regra
  // do fornecedor incluída; débito direto excluído) cai em cada dia.
  const semana = useMemo(() => {
    const localISO = (d) =>
      `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    const hoje = new Date();
    const hojeISO = localISO(hoje);
    const seg = new Date(hoje);
    seg.setDate(hoje.getDate() - ((hoje.getDay() + 6) % 7)); // segunda-feira
    const nomes = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom'];
    const porPagar = active
      .filter((i) => !i.paid && !ruleFor(i)?.direct_debit)
      .map((i) => ({ ...i, _due: effectiveDue(i, ruleFor(i)) }))
      .filter((i) => i._due);
    const dias = [];
    for (let k = 0; k < 7; k++) {
      const d = new Date(seg);
      d.setDate(seg.getDate() + k);
      const iso = localISO(d);
      const doDia = porPagar.filter((i) => i._due === iso);
      dias.push({
        iso, nome: nomes[k], num: d.getDate(),
        hoje: iso === hojeISO, passado: iso < hojeISO,
        faturas: doDia,
        total: doDia.reduce((s, i) => s + (Number(i.amount) || 0), 0),
      });
    }
    const atrasadas = porPagar.filter((i) => i._due < hojeISO);
    return {
      dias, hojeISO,
      atrasadas: atrasadas.length,
      atrasadasTotal: atrasadas.reduce((s, i) => s + (Number(i.amount) || 0), 0),
      totalSemana: dias.reduce((s, d) => s + d.total, 0),
    };
  }, [active]); // eslint-disable-line react-hooks/exhaustive-deps

  const agenda = useMemo(() => {
    const today = todayISO();
    const list = active
      .filter((i) => !i.paid)
      .map((i) => ({ ...i, _due: effectiveDue(i, ruleFor(i)), _dd: !!ruleFor(i)?.direct_debit }))
      .filter((i) => !i._dd && i._due); // débito direto sai da lista a pagar à mão
    const inWindow = (due) => {
      if (due < today) return true; // vencidas entram sempre
      if (agendaView === 'day') return due === today;
      if (agendaView === 'week') {
        const w = new Date(); w.setDate(w.getDate() + 7);
        return due <= w.toISOString().slice(0, 10);
      }
      return due.slice(0, 7) === today.slice(0, 7); // month
    };
    const sel = list.filter((i) => inWindow(i._due)).sort((a, b) => a._due.localeCompare(b._due));
    const groups = {};
    sel.forEach((i) => { (groups[i._due] = groups[i._due] || []).push(i); });
    const total = sel.reduce((s, i) => s + (Number(i.amount) || 0), 0);
    return { groups, total, count: sel.length };
  }, [active, agendaView]); // eslint-disable-line react-hooks/exhaustive-deps

  const contaCorrente = useMemo(() => {
    const map = {};
    active.forEach((i) => {
      const key = i.supplier || '(sem fornecedor)';
      const m = map[key] || { supplier: key, faturado: 0, pago: 0 };
      const val = Number(i.amount) || 0;
      if (i.kind !== 'payment') m.faturado += val;
      if (i.paid || i.kind === 'payment') m.pago += val;
      map[key] = m;
    });
    return Object.values(map)
      .map((m) => ({ ...m, saldo: m.faturado - m.pago }))
      .sort((a, b) => b.saldo - a.saldo);
  }, [active]);

  const approvalBadge = (s) => {
    if (s === 'approved') return <Badge className="bg-emerald-600 hover:bg-emerald-600">Aprovada</Badge>;
    if (s === 'rejected') return <Badge variant="destructive">Rejeitada</Badge>;
    return <Badge className="bg-amber-500 hover:bg-amber-500">Pendente</Badge>;
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fin-pagamentos-page">
      <PageHeader icon={Receipt} title="Pagamentos" subtitle="Faturas de fornecedor, agenda e conta corrente">
        <div className="flex flex-wrap items-center gap-2">
          {companies.length > 0 && (
            <Select value={companyId} onValueChange={setCompanyId}>
              <SelectTrigger className="w-48" data-testid="fin-company-picker">
                <SelectValue placeholder="Empresa" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={COMPANY_ALL}>Todas as empresas</SelectItem>
                {companies.map((c) => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}
              </SelectContent>
            </Select>
          )}
          {canEdit && (
            <>
              <Button variant="outline" onClick={() => openNew('payment')} data-testid="fin-new-payment-btn">
                <Wallet className="h-4 w-4 mr-2" />Pagamento
              </Button>
              <Button onClick={() => openNew('invoice')} data-testid="fin-new-invoice-btn">
                <Plus className="h-4 w-4 mr-2" />Fatura
              </Button>
            </>
          )}
        </div>
      </PageHeader>

      {companies.length === 0 ? (
        <Card><CardContent className="py-12 text-center text-muted-foreground">
          Ainda não tens empresas. Cria uma no separador <b>Início</b> primeiro.
        </CardContent></Card>
      ) : (
        <Tabs defaultValue="resumo" className="space-y-4">
          <TabsList>
            <TabsTrigger value="resumo" data-testid="tab-resumo">Resumo</TabsTrigger>
            <TabsTrigger value="faturas" data-testid="tab-faturas">Faturas</TabsTrigger>
            <TabsTrigger value="agenda" data-testid="tab-agenda">Agenda</TabsTrigger>
            <TabsTrigger value="conta" data-testid="tab-conta">Conta Corrente</TabsTrigger>
          </TabsList>

          {/* ---------- RESUMO ---------- */}
          <TabsContent value="resumo" className="space-y-4">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              {[
                { label: 'A pagar', value: eur(kpis.aPagar), icon: CircleDollarSign },
                { label: 'Pago', value: eur(kpis.pago), icon: Check },
                { label: 'Pendentes', value: kpis.pendentes, icon: Clock },
                { label: 'Vencidas', value: kpis.vencidas, icon: AlertTriangle },
              ].map((k) => (
                <Card key={k.label}>
                  <CardContent className="flex items-center gap-3 p-5">
                    <div className="h-10 w-10 rounded-xl brand-gradient text-white flex items-center justify-center shrink-0">
                      <k.icon className="h-5 w-5" />
                    </div>
                    <div>
                      <p className="text-xl font-heading font-bold leading-none">{k.value}</p>
                      <p className="text-xs text-muted-foreground mt-1">{k.label}</p>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>

            {/* ---------- Esta semana: limites de pagamento por dia ---------- */}
            <Card>
              <CardContent className="p-4 space-y-3" data-testid="fin-semana-pagamentos">
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <p className="text-sm font-semibold">Esta semana · limites de pagamento</p>
                  <div className="flex items-center gap-3 text-xs">
                    {semana.atrasadas > 0 && (
                      <span className="inline-flex items-center gap-1 text-destructive font-medium">
                        <AlertTriangle className="h-3.5 w-3.5" />
                        {semana.atrasadas} em atraso · {eur(semana.atrasadasTotal)}
                      </span>
                    )}
                    <span className="text-muted-foreground">
                      Semana: <b className="text-foreground">{eur(semana.totalSemana)}</b>
                    </span>
                  </div>
                </div>
                <div className="overflow-x-auto">
                  <div className="grid grid-cols-7 gap-1.5 min-w-[640px]">
                    {semana.dias.map((d) => (
                      <div key={d.iso}
                        className={`rounded-xl border p-2 flex flex-col gap-1.5 min-h-[108px] ${
                          d.hoje ? 'border-primary ring-1 ring-primary/40 bg-primary/5'
                          : d.passado ? 'opacity-60' : ''
                        }`}>
                        <div className="flex items-baseline justify-between">
                          <span className={`text-[10px] uppercase font-semibold ${d.hoje ? 'text-primary' : 'text-muted-foreground'}`}>
                            {d.nome}
                          </span>
                          <span className={`text-sm font-heading font-bold ${d.hoje ? 'text-primary' : ''}`}>{d.num}</span>
                        </div>
                        {d.faturas.length === 0 ? (
                          <span className="text-[11px] text-muted-foreground/60 m-auto">—</span>
                        ) : (
                          <>
                            <span className={`text-[11px] font-semibold ${d.passado ? 'text-destructive' : ''}`}>
                              {eur(d.total)}
                            </span>
                            <div className="space-y-0.5">
                              {d.faturas.slice(0, 3).map((f) => (
                                <div key={f.id} title={`${f.supplier || ''} · ${eur(f.amount)}`}
                                  className="truncate rounded bg-muted/60 px-1.5 py-0.5 text-[10px] leading-tight">
                                  <span className="font-medium">{f.supplier || '(s/ fornecedor)'}</span>
                                  <span className="text-muted-foreground"> {eur(f.amount)}</span>
                                </div>
                              ))}
                              {d.faturas.length > 3 && (
                                <span className="text-[10px] text-muted-foreground">+{d.faturas.length - 3} mais</span>
                              )}
                            </div>
                          </>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
                <p className="text-[11px] text-muted-foreground">
                  Vencimento efetivo (regras de fornecedor aplicadas); débitos diretos não aparecem. Detalhe completo na <b>Agenda</b>.
                </p>
              </CardContent>
            </Card>
          </TabsContent>

          {/* ---------- FATURAS ---------- */}
          <TabsContent value="faturas">
            <Card>
              <CardContent className="p-4 space-y-4">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input className="pl-9" placeholder="Pesquisar por nº, fornecedor, NIF, data..."
                    value={search} onChange={(e) => setSearch(e.target.value)} data-testid="fin-invoice-search" />
                </div>
                {loading ? (
                  <div className="flex justify-center h-24 items-center">
                    <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary" />
                  </div>
                ) : filtered.length === 0 ? (
                  <p className="text-center text-muted-foreground py-10">Sem faturas.</p>
                ) : (
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Emissão</TableHead>
                          <TableHead>Fornecedor</TableHead>
                          <TableHead className="hidden md:table-cell">Nº</TableHead>
                          <TableHead className="text-right">Valor</TableHead>
                          <TableHead className="hidden lg:table-cell">Unidade</TableHead>
                          <TableHead>Estado</TableHead>
                          <TableHead className="text-right">Ações</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {filtered.map((inv) => (
                          <TableRow key={inv.id} data-testid={`fin-invoice-row-${inv.id}`}>
                            <TableCell className="whitespace-nowrap">{fmtDate(inv.issue_date)}</TableCell>
                            <TableCell className="font-medium">
                              {inv.supplier || '-'}
                              {inv.kind === 'payment' && <Badge variant="outline" className="ml-2">Pagamento</Badge>}
                              {inv.recurrence && inv.recurrence !== 'none' && <Badge variant="outline" className="ml-2">Recorrente</Badge>}
                              {companyId === COMPANY_ALL && companyName(inv.company_id) && (
                                <p className="text-xs text-muted-foreground font-normal">{companyName(inv.company_id)}</p>
                              )}
                            </TableCell>
                            <TableCell className="hidden md:table-cell text-muted-foreground">{inv.invoice_number || '-'}</TableCell>
                            <TableCell className="text-right whitespace-nowrap">{eur(inv.amount)}</TableCell>
                            <TableCell className="hidden lg:table-cell">
                              {canEdit ? (
                                <Select value={inv.unit_id || UNIT_NONE} onValueChange={(v) => doSetUnit(inv, v)}>
                                  <SelectTrigger className="h-8 w-32 text-xs"><SelectValue /></SelectTrigger>
                                  <SelectContent>
                                    <SelectItem value={UNIT_NONE}>Comum</SelectItem>
                                    {companyUnits.map((u) => <SelectItem key={u.id} value={u.id}>{u.name}</SelectItem>)}
                                  </SelectContent>
                                </Select>
                              ) : unitName(inv.unit_id)}
                            </TableCell>
                            <TableCell>
                              <div className="flex flex-col gap-1 items-start">
                                {approvalBadge(inv.approval_status)}
                                {inv.paid
                                  ? <Badge variant="secondary" className="text-emerald-700">Paga</Badge>
                                  : <Badge variant="outline">Por pagar</Badge>}
                              </div>
                            </TableCell>
                            <TableCell className="text-right">
                              <div className="flex items-center justify-end gap-1">
                                {canEdit && inv.approval_status === 'pending' && (
                                  <>
                                    <Button variant="ghost" size="icon" className="h-8 w-8" title="Aprovar"
                                      onClick={() => doApprove(inv)} data-testid={`fin-approve-${inv.id}`}>
                                      <Check className="h-4 w-4 text-emerald-600" />
                                    </Button>
                                    <Button variant="ghost" size="icon" className="h-8 w-8" title="Rejeitar"
                                      onClick={() => doReject(inv)} data-testid={`fin-reject-${inv.id}`}>
                                      <X className="h-4 w-4 text-destructive" />
                                    </Button>
                                  </>
                                )}
                                {canEdit && (
                                  <Button variant="ghost" size="icon" className="h-8 w-8" title={inv.paid ? 'Marcar por pagar' : 'Marcar paga'}
                                    onClick={() => doTogglePaid(inv)} data-testid={`fin-toggle-paid-${inv.id}`}>
                                    <CircleDollarSign className={`h-4 w-4 ${inv.paid ? 'text-muted-foreground' : 'text-emerald-600'}`} />
                                  </Button>
                                )}
                                {canEdit && (
                                  <Button variant="ghost" size="icon" className="h-8 w-8" title="Editar"
                                    onClick={() => openEdit(inv)} data-testid={`fin-edit-${inv.id}`}>
                                    <Pencil className="h-4 w-4" />
                                  </Button>
                                )}
                                {canEdit && (
                                  <Button variant="ghost" size="icon" className="h-8 w-8" title="Eliminar"
                                    onClick={() => setToDelete(inv)} data-testid={`fin-delete-${inv.id}`}>
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
          </TabsContent>

          {/* ---------- AGENDA ---------- */}
          <TabsContent value="agenda">
            <Card>
              <CardContent className="p-4 space-y-4">
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <Tabs value={agendaView} onValueChange={setAgendaView}>
                    <TabsList>
                      <TabsTrigger value="day">Dia</TabsTrigger>
                      <TabsTrigger value="week">Semana</TabsTrigger>
                      <TabsTrigger value="month">Mês</TabsTrigger>
                    </TabsList>
                  </Tabs>
                  <div className="text-sm text-muted-foreground">
                    {agenda.count} a pagar · <b className="text-foreground">{eur(agenda.total)}</b>
                  </div>
                </div>
                {Object.keys(agenda.groups).length === 0 ? (
                  <p className="text-center text-muted-foreground py-10">Nada a pagar neste período. 🎉</p>
                ) : (
                  Object.entries(agenda.groups).map(([due, items]) => (
                    <div key={due} className="space-y-1">
                      <div className="flex items-center gap-2 text-sm font-semibold">
                        <span>{fmtDate(due)}</span>
                        {due < todayISO() && <Badge variant="destructive" className="text-[10px]">Vencido</Badge>}
                      </div>
                      {items.map((i) => (
                        <div key={i.id} className="flex items-center justify-between rounded-lg border p-3">
                          <div>
                            <p className="text-sm font-medium">{i.supplier || '-'}</p>
                            <p className="text-xs text-muted-foreground">{i.invoice_number || ''} · {unitName(i.unit_id)}</p>
                          </div>
                          <div className="flex items-center gap-3">
                            <span className="font-medium">{eur(i.amount)}</span>
                            {canEdit && (
                              <Button size="sm" variant="outline" onClick={() => doTogglePaid(i)}>Pagar</Button>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  ))
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* ---------- CONTA CORRENTE ---------- */}
          <TabsContent value="conta">
            <Card>
              <CardContent className="p-0">
                {contaCorrente.length === 0 ? (
                  <p className="text-center text-muted-foreground py-10">Sem movimentos.</p>
                ) : (
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Fornecedor</TableHead>
                          <TableHead className="text-right">Faturado</TableHead>
                          <TableHead className="text-right">Pago</TableHead>
                          <TableHead className="text-right">Saldo</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {contaCorrente.map((m) => (
                          <TableRow key={m.supplier}>
                            <TableCell className="font-medium">{m.supplier}</TableCell>
                            <TableCell className="text-right">{eur(m.faturado)}</TableCell>
                            <TableCell className="text-right">{eur(m.pago)}</TableCell>
                            <TableCell className={`text-right font-medium ${m.saldo > 0 ? 'text-destructive' : ''}`}>{eur(m.saldo)}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      )}

      {/* ---------- Dialog criar/editar ---------- */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto" data-testid="fin-invoice-dialog">
          <DialogHeader>
            <DialogTitle>
              {editing ? 'Editar lançamento' : form.kind === 'payment' ? 'Novo pagamento' : 'Nova fatura'}
            </DialogTitle>
            <DialogDescription>
              {form.kind === 'payment' ? 'Pagamento avulso (entra já aprovado).' : 'Fatura de fornecedor.'}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={submit} className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1 col-span-2">
                <Label className="text-xs">Fornecedor *</Label>
                <Input value={form.supplier} onChange={(e) => setForm({ ...form, supplier: e.target.value })}
                  required data-testid="fin-f-supplier" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">NIF</Label>
                <Input value={form.nif} onChange={(e) => setForm({ ...form, nif: e.target.value })} inputMode="numeric" data-testid="fin-f-nif" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Nº fatura</Label>
                <Input value={form.invoice_number} onChange={(e) => setForm({ ...form, invoice_number: e.target.value })} data-testid="fin-f-number" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Emissão</Label>
                <Input type="date" value={form.issue_date} onChange={(e) => setForm({ ...form, issue_date: e.target.value })} data-testid="fin-f-issue" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Vencimento</Label>
                <Input type="date" value={form.due_date} onChange={(e) => setForm({ ...form, due_date: e.target.value })} data-testid="fin-f-due" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Valor (c/IVA) *</Label>
                <Input type="number" step="0.01" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} required data-testid="fin-f-amount" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">IVA %</Label>
                <Input type="number" step="0.01" value={form.vat_rate} onChange={(e) => setForm({ ...form, vat_rate: e.target.value })} placeholder="23" data-testid="fin-f-vat" />
              </div>
              <div className="space-y-1 col-span-2">
                <Label className="text-xs">Unidade / Loja</Label>
                <Select value={form.unit_id} onValueChange={(v) => setForm({ ...form, unit_id: v })}>
                  <SelectTrigger data-testid="fin-f-unit"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value={UNIT_NONE}>Comum</SelectItem>
                    {companyUnits.map((u) => <SelectItem key={u.id} value={u.id}>{u.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              {!editing && (
                <div className="space-y-1 col-span-2">
                  <Label className="text-xs">Recorrência</Label>
                  <Select value={form.recurrence} onValueChange={(v) => setForm({ ...form, recurrence: v })}>
                    <SelectTrigger data-testid="fin-f-recurrence"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {RECURRENCE.map((r) => <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              )}
              <div className="space-y-1 col-span-2">
                <Label className="text-xs">Descrição</Label>
                <Textarea rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} data-testid="fin-f-desc" />
              </div>
              <label className="col-span-2 flex items-center gap-2 text-sm cursor-pointer">
                <input type="checkbox" checked={form.paid}
                  onChange={(e) => setForm({ ...form, paid: e.target.checked, paid_date: e.target.checked ? (form.paid_date || todayISO()) : '' })}
                  data-testid="fin-f-paid" />
                Já pago
              </label>
              {form.paid && (
                <div className="space-y-1 col-span-2">
                  <Label className="text-xs">Data de pagamento</Label>
                  <Input type="date" value={form.paid_date} onChange={(e) => setForm({ ...form, paid_date: e.target.value })} />
                </div>
              )}
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>Cancelar</Button>
              <Button type="submit" disabled={saving} data-testid="fin-save-invoice-btn">
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
            <AlertDialogTitle>Eliminar lançamento</AlertDialogTitle>
            <AlertDialogDescription>
              Eliminar a fatura de "{toDelete?.supplier}" ({eur(toDelete?.amount)})?
              {toDelete?.recur_group && ' Esta fatura faz parte de uma série recorrente.'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className="flex-col sm:flex-row gap-2">
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            {toDelete?.recur_group && (
              <Button variant="outline" onClick={() => doCancelSeries(toDelete)}>
                Cancelar série (futuras por pagar)
              </Button>
            )}
            <AlertDialogAction onClick={doDelete} className="bg-destructive text-destructive-foreground"
              data-testid="fin-confirm-delete-invoice">
              Eliminar só esta
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
