import React, { useState, useEffect, useMemo } from 'react';
import { useOutletContext } from 'react-router-dom';
import {
  getFinCompanies, getFinUnits, getFinInvoices, getFinInvoice, getFinInvoicePdf,
  getFinSupplierRules, createFinInvoice, updateFinInvoice,
  toggleFinInvoicePaid, setFinInvoiceUnit, deleteFinInvoice, cancelFinInvoiceSeries,
  getFinMovements, linkFinMovement, unlinkFinMovement,
  approveFinInvoice, rejectFinInvoice,
} from '../../../lib/api';
import { eur, fmtDate, todayISO, effectiveDue, supplierKeyOf, kpiTone } from '../../../lib/finance';
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
  Receipt, Plus, Search, Check, Pencil, Trash2, CircleDollarSign,
  Clock, AlertTriangle, Wallet, ChevronLeft, ChevronRight,
  FileText, Link2, Unlink, X, ClipboardCheck,
} from 'lucide-react';
import { toast } from 'sonner';
import PageHeader from '../../../components/PageHeader';

const COMPANY_ALL = 'all';
const RECURRENCE = [
  { value: 'none', label: 'Não recorrente' },
  { value: 'weekly', label: 'Semanal' },
  { value: 'monthly', label: 'Mensal' },
  { value: 'quarterly', label: 'Trimestral' },
  { value: 'yearly', label: 'Anual' },
];
const UNIT_NONE = '__none__';
// Categorias de despesa (usadas no relatório DRE, que agrupa por categoria).
const CATEGORIAS = [
  { value: 'mercadoria', label: 'Mercadoria' },
  { value: 'rendas', label: 'Rendas' },
  { value: 'energia_agua', label: 'Água/Energia' },
  { value: 'salarios', label: 'Salários' },
  { value: 'servicos', label: 'Serviços' },
  { value: 'impostos', label: 'Impostos' },
  { value: 'outros', label: 'Outros' },
];
const categoriaLabel = (v) => CATEGORIAS.find((c) => c.value === v)?.label || '';

const emptyForm = () => ({
  kind: 'invoice', supplier: '', nif: '', invoice_number: '',
  issue_date: todayISO(), due_date: '', amount: '', vat_rate: '',
  description: '', unit_id: UNIT_NONE, category: '', recurrence: 'none', paid: false, paid_date: '',
});

// Origem da fatura em linguagem humana (ficha de detalhe).
const SOURCE_LABEL = { email: 'Email (automática)', manual: 'Manual', recurrence: 'Recorrente' };

// Campo da grelha de dados na ficha de detalhe.
function DetailField({ label, value }) {
  return (
    <div className="min-w-0">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm font-medium break-words">{value || '—'}</p>
    </div>
  );
}

export default function FinPagamentos() {
  const { selectedCompany } = useOutletContext();
  const [companies, setCompanies] = useState([]);
  const [companyId, setCompanyId] = useState('');
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

  // Ficha de detalhe da fatura (abre ao clicar na linha)
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(false);
  // Sub-dialog: ligar a movimento do extrato
  const [linkOpen, setLinkOpen] = useState(false);
  const [linkMovs, setLinkMovs] = useState([]);
  const [linkLoading, setLinkLoading] = useState(false);
  const [linkSearch, setLinkSearch] = useState('');

  // Zona "A confirmar": aprovar/rejeitar faturas pendentes (ex.: entradas do Estoque)
  const [pendingBusyId, setPendingBusyId] = useState(null); // fatura em processamento (aprovar/rejeitar/PDF)
  const [rejecting, setRejecting] = useState(null);         // fatura a rejeitar (abre diálogo)
  const [rejectNote, setRejectNote] = useState('');

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
    if (companyId) { loadData(); }
  }, [companyId]); // eslint-disable-line react-hooks/exhaustive-deps
  // A empresa ativa vem do seletor global do topo (secção Financeiro).
  useEffect(() => {
    setCompanyId(selectedCompany ? selectedCompany.id : COMPANY_ALL);
  }, [selectedCompany]);

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
      category: inv.category || '',
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
        category: form.category || null,
        recurrence: editing ? 'none' : form.recurrence, // recorrência só ao criar
        paid: !!form.paid,
        paid_date: form.paid_date || null,
      };
      if (editing) {
        await updateFinInvoice(editing.id, payload);
        toast.success('Fatura atualizada');
      } else {
        // Aviso de possível duplicado (não bloqueia): mesma empresa e mesmo
        // fornecedor, com o mesmo nº de fatura OU o mesmo valor+data de emissão.
        // Evita pagar a mesma fatura duas vezes por lançamento repetido.
        const myKey = supplierKeyOf(form.nif, form.supplier);
        const dup = invoices.find((i) => {
          if (i.company_id !== companyId || i.approval_status === 'rejected') return false;
          if (supplierKeyOf(i.nif, i.supplier) !== myKey) return false;
          const mesmoNum = form.invoice_number && i.invoice_number &&
            String(i.invoice_number).trim().toLowerCase() === form.invoice_number.trim().toLowerCase();
          const mesmoValorData = amount != null && Number(i.amount) === amount &&
            i.issue_date && i.issue_date === form.issue_date;
          return mesmoNum || mesmoValorData;
        });
        if (dup) {
          const qual = dup.invoice_number ? `nº ${dup.invoice_number}` : `${eur(dup.amount)} de ${fmtDate(dup.issue_date)}`;
          const avanca = window.confirm(
            `Já existe uma fatura de "${dup.supplier || 'este fornecedor'}" (${qual}). ` +
            `Criar mesmo assim?\n\nSe for a mesma fatura, cancela para não pagar duas vezes.`
          );
          if (!avanca) { setSaving(false); return; }
        }
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

  const doTogglePaid = async (inv) => {
    try {
      await toggleFinInvoicePaid(inv.id, !inv.paid, !inv.paid ? todayISO() : null);
      loadData();
      if (detail && detail.id === inv.id) refreshDetail(inv.id); // ficha aberta acompanha
    } catch (e) { toast.error('Erro ao atualizar pagamento'); }
  };

  // ---------- Ficha de detalhe ----------
  // Abre já com os dados da linha; em paralelo vai buscar a fatura completa
  // (traz linked_movement — o movimento do extrato ligado, ou null).
  const openDetail = (inv) => {
    setDetail({ ...inv, linked_movement: null });
    setDetailLoading(true);
    refreshDetail(inv.id);
  };
  const refreshDetail = async (id) => {
    try {
      const r = await getFinInvoice(id);
      setDetail(r.data);
    } catch (e) {
      // mantém os dados da linha — a ficha continua utilizável
    } finally {
      setDetailLoading(false);
    }
  };
  const closeDetail = () => { setDetail(null); setLinkOpen(false); setLinkSearch(''); };

  const viewPdf = async () => {
    if (!detail) return;
    setPdfBusy(true);
    try {
      const res = await getFinInvoicePdf(detail.id);
      const url = URL.createObjectURL(res.data);
      window.open(url, '_blank');
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (err) {
      // responseType blob → o detail do erro vem num Blob; ler como texto
      let msg = 'Erro ao abrir o PDF';
      try {
        const txt = await err.response?.data?.text?.();
        if (txt) msg = JSON.parse(txt)?.detail || msg;
      } catch (_) { /* mantém a mensagem genérica */ }
      toast.error(msg);
    } finally {
      setPdfBusy(false);
    }
  };

  // ---------- Zona "A confirmar" (faturas pendentes) ----------
  // Abre o PDF de uma fatura pendente diretamente da linha (mesmo mecanismo do viewPdf).
  const viewPendingPdf = async (inv) => {
    setPendingBusyId(inv.id);
    try {
      const res = await getFinInvoicePdf(inv.id);
      const url = URL.createObjectURL(res.data);
      window.open(url, '_blank');
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (err) {
      let msg = 'Erro ao abrir o PDF';
      try {
        const txt = await err.response?.data?.text?.();
        if (txt) msg = JSON.parse(txt)?.detail || msg;
      } catch (_) { /* mantém a mensagem genérica */ }
      toast.error(msg);
    } finally {
      setPendingBusyId(null);
    }
  };
  const doApproveInvoice = async (inv) => {
    setPendingBusyId(inv.id);
    try {
      await approveFinInvoice(inv.id);
      toast.success('Fatura confirmada');
      loadData();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erro ao confirmar');
    } finally {
      setPendingBusyId(null);
    }
  };
  const doRejectInvoice = async () => {
    if (!rejecting) return;
    setPendingBusyId(rejecting.id);
    try {
      await rejectFinInvoice(rejecting.id, rejectNote.trim() || null);
      toast.success('Fatura rejeitada');
      setRejecting(null);
      setRejectNote('');
      loadData();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erro ao rejeitar');
    } finally {
      setPendingBusyId(null);
    }
  };

  const doUnlinkMov = async () => {
    const mov = detail?.linked_movement;
    if (!mov) return;
    try {
      await unlinkFinMovement(mov.id);
      toast.success('Movimento desligado — a fatura volta a "por pagar"');
      refreshDetail(detail.id);
      loadData();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erro ao desligar');
    }
  };

  // Sub-dialog: carrega os movimentos da MESMA empresa da fatura ao abrir.
  const openLinkMov = async () => {
    if (!detail) return;
    setLinkSearch('');
    setLinkOpen(true);
    setLinkLoading(true);
    try {
      const r = await getFinMovements({ company_id: detail.company_id });
      setLinkMovs(r.data || []);
    } catch (e) {
      toast.error('Erro ao carregar movimentos');
      setLinkMovs([]);
    } finally {
      setLinkLoading(false);
    }
  };
  const doLinkMov = async (mov) => {
    if (!detail) return;
    try {
      await linkFinMovement(mov.id, detail.id);
      toast.success('Fatura ligada e marcada como paga');
      setLinkOpen(false);
      setLinkSearch('');
      refreshDetail(detail.id);
      loadData();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erro ao ligar movimento');
    }
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
  // Faturas pendentes de confirmação (respeitam o filtro de empresa já aplicado no loadData).
  const pending = useMemo(
    () => invoices.filter((i) => i.approval_status === 'pending'),
    [invoices]
  );
  const active = invoices.filter((i) => i.approval_status !== 'rejected');
  const kpis = useMemo(() => {
    const today = todayISO();
    let aPagar = 0, pago = 0, porPagar = 0, vencidas = 0;
    active.forEach((i) => {
      const val = Number(i.amount) || 0;
      if (i.paid) pago += val;
      else {
        aPagar += val;
        porPagar += 1;
        const due = effectiveDue(i, ruleFor(i));
        if (due && due < today) vencidas += 1;
      }
    });
    return { aPagar, pago, porPagar, vencidas };
  }, [active]); // eslint-disable-line react-hooks/exhaustive-deps

  // Candidatos do sub-dialog "Ligar a movimento": saídas (amount < 0) sem fatura,
  // com pesquisa por descrição/valor/data; os de valor igual ao da fatura vêm primeiro.
  const linkCandidates = useMemo(() => {
    if (!detail) return [];
    const alvo = Math.abs(Number(detail.amount) || 0).toFixed(2);
    const q = linkSearch.trim().toLowerCase();
    let list = linkMovs.filter((m) => (Number(m.amount) || 0) < 0 && !m.invoice_id);
    if (q) {
      list = list.filter((m) =>
        [m.description, m.amount, m.date_lancamento]
          .filter(Boolean).some((f) => String(f).toLowerCase().includes(q))
      );
    }
    return list
      .map((m) => ({ ...m, _match: Math.abs(Number(m.amount) || 0).toFixed(2) === alvo }))
      .sort((a, b) =>
        (b._match - a._match) ||
        String(b.date_lancamento || '').localeCompare(String(a.date_lancamento || '')))
      .slice(0, 50);
  }, [detail, linkMovs, linkSearch]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return invoices;
    return invoices.filter((i) =>
      [i.invoice_number, i.supplier, i.nif, i.issue_date, i.description]
        .filter(Boolean).some((f) => String(f).toLowerCase().includes(q))
    );
  }, [invoices, search]);

  // ---------- Semana (Resumo): limites de pagamento por dia ----------
  // Segunda→domingo, com as faturas POR PAGAR cujo vencimento efetivo (regra
  // do fornecedor incluída; débito direto excluído) cai em cada dia.
  // weekOffset: 0 = semana atual; -1 anterior; +1 seguinte.
  const [weekOffset, setWeekOffset] = useState(0);
  const semana = useMemo(() => {
    const localISO = (d) =>
      `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    const hoje = new Date();
    const hojeISO = localISO(hoje);
    const seg = new Date(hoje);
    seg.setDate(hoje.getDate() - ((hoje.getDay() + 6) % 7)); // segunda-feira
    seg.setDate(seg.getDate() + weekOffset * 7); // navegação entre semanas
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
    const atrasadas = porPagar.filter((i) => i._due < hojeISO); // globais, independentes da semana visível
    const meses = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
    const dom = new Date(seg);
    dom.setDate(seg.getDate() + 6);
    const label = weekOffset === 0
      ? 'Esta semana'
      : seg.getMonth() === dom.getMonth()
        ? `${seg.getDate()}–${dom.getDate()} ${meses[dom.getMonth()]}`
        : `${seg.getDate()} ${meses[seg.getMonth()]}–${dom.getDate()} ${meses[dom.getMonth()]}`;
    return {
      dias, hojeISO, label,
      atrasadas: atrasadas.length,
      atrasadasTotal: atrasadas.reduce((s, i) => s + (Number(i.amount) || 0), 0),
      totalSemana: dias.reduce((s, d) => s + d.total, 0),
    };
  }, [active, weekOffset]); // eslint-disable-line react-hooks/exhaustive-deps

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

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fin-pagamentos-page">
      <PageHeader icon={Receipt} title="Pagamentos" subtitle="Faturas de fornecedor, agenda e conta corrente">
        <div className="flex flex-wrap items-center gap-2">
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

      {/* ---------- A CONFIRMAR (faturas pendentes, ex.: entradas do Estoque) ---------- */}
      {pending.length > 0 && (
        <Card className="border-amber-500/50 bg-amber-50/40 dark:bg-amber-950/10" data-testid="fin-a-confirmar">
          <CardContent className="p-4 space-y-3">
            <div className="flex items-center gap-3">
              <div className="h-10 w-10 rounded-xl bg-amber-500 text-white flex items-center justify-center shrink-0">
                <ClipboardCheck className="h-5 w-5" />
              </div>
              <div>
                <p className="text-lg font-heading font-bold leading-none">A confirmar ({pending.length})</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Faturas inseridas pela app do Estoque, à espera de aprovação.
                </p>
              </div>
            </div>
            <div className="space-y-2">
              {pending.map((inv) => (
                <div key={inv.id} className="rounded-xl border bg-background p-3 space-y-2"
                  data-testid={`fin-pending-${inv.id}`}>
                  <div className="flex items-start justify-between gap-3 flex-wrap">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="font-semibold break-words">{inv.supplier || '(sem fornecedor)'}</p>
                        {inv.source === 'estoque' && (
                          <Badge variant="outline" className="border-amber-500/60 text-amber-700">Estoque</Badge>
                        )}
                        {companyId === COMPANY_ALL && companyName(inv.company_id) && (
                          <span className="text-xs text-muted-foreground">{companyName(inv.company_id)}</span>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {inv.invoice_number ? `Fatura ${inv.invoice_number} · ` : ''}
                        Emissão {fmtDate(inv.issue_date)}
                        {inv.due_date ? ` · Vence ${fmtDate(inv.due_date)}` : ''}
                      </p>
                    </div>
                    <p className="text-xl font-heading font-bold tabular-nums shrink-0">{eur(inv.amount)}</p>
                  </div>

                  {/* Campos extraídos pela IA */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-3 gap-y-1 text-sm">
                    <DetailField label="NIF" value={inv.nif} />
                    <DetailField label="Líquido" value={inv.amount_net != null ? eur(inv.amount_net) : null} />
                    <DetailField label="IVA"
                      value={inv.vat_amount != null
                        ? `${eur(inv.vat_amount)}${inv.vat_rate != null ? ` (${inv.vat_rate}%)` : ''}`
                        : null} />
                    <DetailField label="Unidade / Loja" value={unitName(inv.unit_id)} />
                  </div>
                  {inv.description && (
                    <p className="text-sm text-muted-foreground break-words">{inv.description}</p>
                  )}

                  {/* Origem: quem inseriu + loja (para custos por loja) */}
                  <p className="text-xs text-muted-foreground">
                    Inserida por <b className="text-foreground">{inv.origin_user || '—'}</b>
                    {inv.origin_store ? <> · <b className="text-foreground">{inv.origin_store}</b></> : ''}
                  </p>

                  {/* Ações */}
                  <div className="flex items-center gap-2 flex-wrap pt-1">
                    {inv.pdf_path && (
                      <Button variant="outline" size="sm" onClick={() => viewPendingPdf(inv)}
                        disabled={pendingBusyId === inv.id} data-testid={`fin-pending-pdf-${inv.id}`}>
                        <FileText className="h-4 w-4 mr-2" />Ver PDF
                      </Button>
                    )}
                    {canEdit && (
                      <>
                        <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700 text-white"
                          onClick={() => doApproveInvoice(inv)} disabled={pendingBusyId === inv.id}
                          data-testid={`fin-approve-${inv.id}`}>
                          <Check className="h-4 w-4 mr-2" />Confirmar
                        </Button>
                        <Button size="sm" variant="outline" className="text-destructive hover:text-destructive"
                          onClick={() => { setRejecting(inv); setRejectNote(''); }} disabled={pendingBusyId === inv.id}
                          data-testid={`fin-reject-${inv.id}`}>
                          <X className="h-4 w-4 mr-2" />Rejeitar
                        </Button>
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

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
                { label: 'Por pagar', value: kpis.porPagar, icon: Clock },
                { label: 'Vencidas', value: kpis.vencidas, icon: AlertTriangle },
              ].map((k, i) => {
                const tone = kpiTone(i);
                return (
                <Card key={k.label}>
                  <CardContent className="flex items-center gap-3 p-5">
                    <div className={`h-10 w-10 rounded-xl ${tone.bg} ${tone.icon} flex items-center justify-center shrink-0`}>
                      <k.icon className="h-5 w-5" />
                    </div>
                    <div>
                      <p className="text-xl font-heading font-bold leading-none">{k.value}</p>
                      <p className="text-xs text-muted-foreground mt-1">{k.label}</p>
                    </div>
                  </CardContent>
                </Card>
                );
              })}
            </div>

            {/* ---------- Esta semana: limites de pagamento por dia ---------- */}
            <Card>
              <CardContent className="p-4 space-y-3" data-testid="fin-semana-pagamentos">
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <div className="flex items-center gap-1.5">
                    <Button variant="outline" size="icon" className="h-8 w-8" title="Semana anterior"
                      data-testid="fin-semana-prev" onClick={() => setWeekOffset((o) => o - 1)}>
                      <ChevronLeft className="h-4 w-4" />
                    </Button>
                    {weekOffset === 0 ? (
                      <p className="text-lg md:text-xl font-heading font-bold px-1">{semana.label}</p>
                    ) : (
                      <button type="button" title="Voltar a esta semana" onClick={() => setWeekOffset(0)}
                        className="text-lg md:text-xl font-heading font-bold px-1 hover:text-primary transition-colors">
                        {semana.label}
                      </button>
                    )}
                    <Button variant="outline" size="icon" className="h-8 w-8" title="Semana seguinte"
                      data-testid="fin-semana-next" onClick={() => setWeekOffset((o) => o + 1)}>
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                  <div className="flex items-center gap-3 text-sm">
                    {semana.atrasadas > 0 && (
                      <span className="inline-flex items-center gap-1 text-destructive font-medium">
                        <AlertTriangle className="h-4 w-4" />
                        {semana.atrasadas} em atraso · {eur(semana.atrasadasTotal)}
                      </span>
                    )}
                    <span className="text-muted-foreground">
                      Semana: <b className="text-foreground">{eur(semana.totalSemana)}</b>
                    </span>
                  </div>
                </div>
                <div className="overflow-x-auto">
                  <div className="grid grid-cols-7 gap-1.5 min-w-[700px]">
                    {semana.dias.map((d) => (
                      <div key={d.iso}
                        className={`rounded-xl border p-2.5 flex flex-col gap-1.5 min-h-[132px] ${
                          d.hoje ? 'border-primary ring-1 ring-primary/40 bg-primary/5'
                          : d.passado ? 'opacity-60' : ''
                        }`}>
                        <div className="flex items-center justify-between">
                          <span className={`text-xs uppercase font-semibold tracking-wide ${d.hoje ? 'text-primary' : 'text-muted-foreground'}`}>
                            {d.nome}
                          </span>
                          {d.hoje ? (
                            <span className="h-9 w-9 rounded-full brand-gradient text-white flex items-center justify-center text-2xl font-heading font-bold">
                              {d.num}
                            </span>
                          ) : (
                            <span className="text-2xl font-heading font-bold">{d.num}</span>
                          )}
                        </div>
                        {d.faturas.length === 0 ? (
                          <span className="text-sm text-muted-foreground/50 m-auto">—</span>
                        ) : (
                          <>
                            <span className={`text-base md:text-lg font-heading font-bold tabular-nums ${d.passado ? 'text-destructive' : ''}`}>
                              {eur(d.total)}
                            </span>
                            <div className="space-y-0.5">
                              {d.faturas.slice(0, 2).map((f) => (
                                <div key={f.id} title={`${f.supplier || ''} · ${eur(f.amount)}`}
                                  className="truncate rounded-md bg-muted px-2 py-1 text-sm leading-snug">
                                  <span className="font-bold text-foreground">{f.supplier || '(s/ fornecedor)'}</span>
                                  <span className="text-muted-foreground font-medium"> {eur(f.amount)}</span>
                                </div>
                              ))}
                              {d.faturas.length > 2 && (
                                <span className="text-xs text-muted-foreground">+{d.faturas.length - 2} mais</span>
                              )}
                            </div>
                          </>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
                <p className="text-xs text-muted-foreground">
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
                          <TableRow key={inv.id} data-testid={`fin-invoice-row-${inv.id}`}
                            className="cursor-pointer hover:bg-muted/50" onClick={() => openDetail(inv)}>
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
                            <TableCell className="hidden lg:table-cell" onClick={(e) => e.stopPropagation()}>
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
                                {inv.approval_status === 'rejected' && (
                                  <Badge variant="destructive">Rejeitada</Badge>
                                )}
                                {inv.paid
                                  ? <Badge variant="secondary" className="text-emerald-700">Paga</Badge>
                                  : <Badge variant="outline">Por pagar</Badge>}
                              </div>
                            </TableCell>
                            <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
                              <div className="flex items-center justify-end gap-1">
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
              <div className="space-y-1 col-span-2">
                <Label className="text-xs">Categoria</Label>
                <Select value={form.category || UNIT_NONE}
                  onValueChange={(v) => setForm({ ...form, category: v === UNIT_NONE ? '' : v })}>
                  <SelectTrigger data-testid="fin-f-category"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value={UNIT_NONE}>Sem categoria</SelectItem>
                    {CATEGORIAS.map((c) => <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>)}
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

      {/* ---------- Ficha de detalhe da fatura ---------- */}
      <Dialog open={!!detail} onOpenChange={(o) => { if (!o) closeDetail(); }}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto" data-testid="fin-invoice-detail">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 flex-wrap">
              {detail?.supplier || '(sem fornecedor)'}
              {detail?.kind === 'payment' && <Badge variant="outline">Pagamento</Badge>}
              {detail?.recurrence && detail.recurrence !== 'none' && <Badge variant="outline">Recorrente</Badge>}
              {detail?.approval_status === 'rejected' && <Badge variant="destructive">Rejeitada</Badge>}
            </DialogTitle>
            <DialogDescription>
              {detail?.invoice_number ? `Fatura ${detail.invoice_number}` : 'Detalhe do lançamento'}
            </DialogDescription>
          </DialogHeader>
          {detail && (
            <div className="space-y-4">
              {/* Valor + estado em destaque */}
              <div className="flex items-center justify-between gap-3 rounded-xl border p-4">
                <div>
                  <p className="text-2xl font-heading font-bold leading-none">{eur(detail.amount)}</p>
                  <p className="text-xs text-muted-foreground mt-1">Valor c/ IVA</p>
                </div>
                {detail.paid ? (
                  <Badge className="bg-emerald-600 hover:bg-emerald-600 text-sm px-3 py-1" data-testid="fin-detail-paid-badge">
                    Paga{detail.paid_date ? ` · ${fmtDate(detail.paid_date)}` : ''}
                  </Badge>
                ) : (
                  <Badge variant="outline" className="text-sm px-3 py-1" data-testid="fin-detail-paid-badge">Por pagar</Badge>
                )}
              </div>

              {/* Grelha de dados */}
              <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-3">
                <DetailField label="Fornecedor" value={detail.supplier} />
                <DetailField label="NIF" value={detail.nif} />
                <DetailField label="Nº fatura" value={detail.invoice_number} />
                <DetailField label="Emissão" value={fmtDate(detail.issue_date)} />
                <DetailField label="Vencimento" value={fmtDate(detail.due_date)} />
                <DetailField label="Valor c/ IVA" value={eur(detail.amount)} />
                <DetailField label="Líquido" value={detail.amount_net != null ? eur(detail.amount_net) : null} />
                <DetailField label="IVA"
                  value={detail.vat_amount != null
                    ? `${eur(detail.vat_amount)}${detail.vat_rate != null ? ` (${detail.vat_rate}%)` : ''}`
                    : null} />
                <DetailField label="Unidade / Loja" value={unitName(detail.unit_id)} />
                <DetailField label="Categoria" value={categoriaLabel(detail.category)} />
                <DetailField label="Empresa" value={companyName(detail.company_id)} />
                <DetailField label="Origem" value={SOURCE_LABEL[detail.source] || detail.source} />
              </div>
              {detail.description && (
                <div>
                  <p className="text-xs text-muted-foreground">Descrição</p>
                  <p className="text-sm whitespace-pre-wrap break-words">{detail.description}</p>
                </div>
              )}

              {/* Movimento do extrato */}
              <div className="rounded-xl border p-3 space-y-2" data-testid="fin-detail-movement">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                  Movimento do extrato
                </p>
                {detailLoading ? (
                  <p className="text-sm text-muted-foreground">A carregar...</p>
                ) : detail.linked_movement ? (
                  <>
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium truncate">
                          {detail.linked_movement.description || '(sem descrição)'}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {fmtDate(detail.linked_movement.date_lancamento)} · {eur(detail.linked_movement.amount)}
                        </p>
                      </div>
                      {canEdit && (
                        <Button variant="ghost" size="sm" className="shrink-0"
                          onClick={doUnlinkMov} data-testid="fin-detail-unlink">
                          <Unlink className="h-4 w-4 mr-1" />Desligar
                        </Button>
                      )}
                    </div>
                    {canEdit && (
                      <p className="text-[11px] text-muted-foreground">
                        Desligar volta a marcar a fatura como "por pagar".
                      </p>
                    )}
                  </>
                ) : canEdit ? (
                  <Button variant="outline" size="sm" onClick={openLinkMov} data-testid="fin-detail-link">
                    <Link2 className="h-4 w-4 mr-2" />Ligar a movimento do extrato
                  </Button>
                ) : (
                  <p className="text-sm text-muted-foreground">Sem movimento ligado.</p>
                )}
              </div>

              {/* Ações */}
              <DialogFooter className="flex-col sm:flex-row sm:flex-wrap gap-2 sm:justify-start">
                {detail.pdf_path && (
                  <Button variant="outline" size="sm" onClick={viewPdf} disabled={pdfBusy}
                    data-testid="fin-detail-pdf">
                    <FileText className="h-4 w-4 mr-2" />{pdfBusy ? 'A abrir...' : 'Ver PDF'}
                  </Button>
                )}
                {canEdit && (
                  <>
                    <Button variant="outline" size="sm" onClick={() => doTogglePaid(detail)}
                      data-testid="fin-detail-toggle-paid">
                      <CircleDollarSign className={`h-4 w-4 mr-2 ${detail.paid ? 'text-muted-foreground' : 'text-emerald-600'}`} />
                      {detail.paid ? 'Marcar por pagar' : 'Marcar paga'}
                    </Button>
                    <Button variant="outline" size="sm"
                      onClick={() => { const inv = detail; closeDetail(); openEdit(inv); }}
                      data-testid="fin-detail-edit">
                      <Pencil className="h-4 w-4 mr-2" />Editar dados
                    </Button>
                    <Button variant="outline" size="sm"
                      className="text-destructive hover:text-destructive"
                      onClick={() => { const inv = detail; closeDetail(); setToDelete(inv); }}
                      data-testid="fin-detail-delete">
                      <Trash2 className="h-4 w-4 mr-2" />Eliminar
                    </Button>
                  </>
                )}
              </DialogFooter>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* ---------- Sub-dialog: ligar a movimento do extrato ---------- */}
      <Dialog open={linkOpen} onOpenChange={(o) => { if (!o) { setLinkOpen(false); setLinkSearch(''); } }}>
        <DialogContent className="max-w-lg" data-testid="fin-detail-link-dialog">
          <DialogHeader>
            <DialogTitle>Ligar a movimento do extrato</DialogTitle>
            <DialogDescription>
              Saídas sem fatura{detail ? ` de ${companyName(detail.company_id) || 'todas as empresas'} · fatura de ${eur(detail.amount)}` : ''}.
              Ligar marca a fatura como paga.
            </DialogDescription>
          </DialogHeader>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input className="pl-9" placeholder="Pesquisar por descrição, valor, data..."
              value={linkSearch} onChange={(e) => setLinkSearch(e.target.value)}
              data-testid="fin-detail-link-search" />
          </div>
          <div className="max-h-72 overflow-y-auto space-y-1">
            {linkLoading ? (
              <div className="flex justify-center h-20 items-center">
                <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary" />
              </div>
            ) : linkCandidates.length === 0 ? (
              <p className="text-center text-muted-foreground py-6 text-sm">
                Sem movimentos de saída por ligar nesta empresa.
              </p>
            ) : (
              linkCandidates.map((m) => (
                <button key={m.id} type="button"
                  className={`w-full flex items-center justify-between gap-3 rounded-md border p-2 text-left hover:bg-accent ${
                    m._match ? 'border-emerald-500/60 bg-emerald-500/5' : ''}`}
                  onClick={() => doLinkMov(m)}
                  data-testid={`fin-detail-link-option-${m.id}`}>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">{m.description || '(sem descrição)'}</p>
                    <p className="text-xs text-muted-foreground">{fmtDate(m.date_lancamento)}</p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {m._match && (
                      <Badge variant="outline" className="text-[10px] border-emerald-500/60 text-emerald-600">
                        valor igual
                      </Badge>
                    )}
                    <span className="text-sm font-medium text-destructive">{eur(m.amount)}</span>
                  </div>
                </button>
              ))
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* ---------- Rejeitar fatura pendente ---------- */}
      <Dialog open={!!rejecting}
        onOpenChange={(o) => { if (!o) { setRejecting(null); setRejectNote(''); } }}>
        <DialogContent className="max-w-md" data-testid="fin-reject-dialog">
          <DialogHeader>
            <DialogTitle>Rejeitar fatura</DialogTitle>
            <DialogDescription>
              {rejecting ? `${rejecting.supplier || 'Fornecedor'} · ${eur(rejecting.amount)}` : ''}
              {rejecting?.origin_user ? ` · inserida por ${rejecting.origin_user}` : ''}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1">
            <Label className="text-xs">Motivo (opcional)</Label>
            <Textarea rows={3} value={rejectNote} onChange={(e) => setRejectNote(e.target.value)}
              placeholder="Ex.: valor errado, fatura duplicada, loja errada..."
              data-testid="fin-reject-note" />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline"
              onClick={() => { setRejecting(null); setRejectNote(''); }}>Cancelar</Button>
            <Button type="button"
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={doRejectInvoice} disabled={pendingBusyId === rejecting?.id}
              data-testid="fin-confirm-reject">
              Rejeitar
            </Button>
          </DialogFooter>
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
