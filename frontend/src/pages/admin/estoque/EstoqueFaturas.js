import React, { useState, useEffect, useCallback } from 'react';
import { useOutletContext } from 'react-router-dom';
import { getFinEstoqueInvoices, getFinInvoicePdf } from '../../../lib/api';
import { eur, fmtDate, todayISO, kpiTone } from '../../../lib/finance';
import { Button } from '../../../components/ui/button';
import { Badge } from '../../../components/ui/badge';
import { Card, CardContent } from '../../../components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../components/ui/select';
import { Boxes, ClipboardCheck, Receipt, User, Store, FileText } from 'lucide-react';
import { toast } from 'sonner';
import PageHeader from '../../../components/PageHeader';
import MonthPicker from '../../../components/MonthPicker';

const COMPANY_ALL = 'all';
const ALL = '__all__';

// Estado da fatura -> rótulo + cor do selo.
const STATUS = {
  pending: { label: 'A confirmar', cls: 'bg-amber-500 hover:bg-amber-500' },
  approved: { label: 'Aprovada', cls: 'bg-emerald-600 hover:bg-emerald-600' },
  rejected: { label: 'Rejeitada', cls: 'bg-destructive hover:bg-destructive' },
};

export default function EstoqueFaturas() {
  // Empresa vem do seletor global do topo (a secção Estoque usa as empresas do
  // Financeiro, como as páginas do Financeiro).
  const { selectedCompany } = useOutletContext();
  const companyId = selectedCompany ? selectedCompany.id : COMPANY_ALL;

  const [month, setMonth] = useState(() => todayISO().slice(0, 7));
  const [colaborador, setColaborador] = useState(ALL);
  const [loja, setLoja] = useState(ALL);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(null);

  const companyName = (id) => (selectedCompany && selectedCompany.id === id ? selectedCompany.name : '');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await getFinEstoqueInvoices({
        company_id: companyId,
        month,
        origin_user: colaborador === ALL ? undefined : colaborador,
        origin_store: loja === ALL ? undefined : loja,
      });
      setData(r.data);
    } catch (e) {
      toast.error('Erro ao carregar as faturas do Estoque');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [companyId, month, colaborador, loja]);

  useEffect(() => { load(); }, [load]);
  // Ao trocar de empresa, os filtros de colaborador/loja podem já não existir.
  useEffect(() => { setColaborador(ALL); setLoja(ALL); }, [companyId]);

  const openPdf = async (inv) => {
    setPdfBusy(inv.id);
    try {
      const res = await getFinInvoicePdf(inv.id);
      const url = URL.createObjectURL(res.data);
      window.open(url, '_blank');
    } catch (e) {
      toast.error('Esta fatura não tem PDF guardado.');
    } finally {
      setPdfBusy(null);
    }
  };

  const t = data?.totais || { n: 0, valor: 0, por_confirmar: 0 };
  const invoices = data?.invoices || [];

  return (
    <div className="space-y-6 animate-fade-in" data-testid="estoque-faturas-page">
      <PageHeader icon={Boxes} title="Estoque · Faturas"
        subtitle="Faturas inseridas pelos colaboradores na app do Estoque">
        <div className="flex flex-wrap items-center gap-2">
          {data?.colaboradores?.length > 0 && (
            <Select value={colaborador} onValueChange={setColaborador}>
              <SelectTrigger className="w-44" data-testid="estoque-colab-filter">
                <SelectValue placeholder="Colaborador" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>Todos os colaboradores</SelectItem>
                {data.colaboradores.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
              </SelectContent>
            </Select>
          )}
          {data?.lojas?.length > 0 && (
            <Select value={loja} onValueChange={setLoja}>
              <SelectTrigger className="w-40" data-testid="estoque-loja-filter">
                <SelectValue placeholder="Loja" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>Todas as lojas</SelectItem>
                {data.lojas.map((l) => <SelectItem key={l} value={l}>{l}</SelectItem>)}
              </SelectContent>
            </Select>
          )}
          <MonthPicker value={month} onChange={(v) => setMonth(v || todayISO().slice(0, 7))}
            className="w-44" testid="estoque-month" />
        </div>
      </PageHeader>

      {/* KPIs */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {[
          { label: 'Faturas no período', value: t.n, icon: Receipt },
          { label: 'Valor total', value: eur(t.valor), icon: Boxes },
          { label: 'Por confirmar', value: t.por_confirmar, icon: ClipboardCheck },
        ].map((k, i) => {
          const tone = kpiTone(i);
          return (
            <Card key={k.label}>
              <CardContent className="flex items-center gap-3 p-5">
                <div className={`h-10 w-10 rounded-xl ${tone.bg} ${tone.icon} flex items-center justify-center shrink-0`}>
                  <k.icon className="h-5 w-5" />
                </div>
                <div className="min-w-0">
                  <p className="text-xl font-heading font-bold leading-none">{k.value}</p>
                  <p className="text-xs text-muted-foreground mt-1">{k.label}</p>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Lista */}
      <Card>
        <CardContent className="p-0">
          {loading && !data ? (
            <p className="text-center text-muted-foreground py-12 text-sm">A carregar…</p>
          ) : invoices.length === 0 ? (
            <p className="text-center text-muted-foreground py-12 text-sm">
              Sem faturas do Estoque neste período. Os colaboradores inserem-nas pela app do Estoque.
            </p>
          ) : (
            <div className="divide-y">
              {invoices.map((inv) => {
                const st = STATUS[inv.approval_status] || { label: inv.approval_status || '—', cls: 'bg-muted text-foreground' };
                return (
                  <div key={inv.id} className="p-4 flex flex-wrap items-start gap-3" data-testid={`estoque-inv-${inv.id}`}>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="font-semibold break-words">{inv.supplier || '(sem fornecedor)'}</p>
                        <Badge className={st.cls}>{st.label}</Badge>
                        {inv.paid && <Badge variant="outline" className="border-emerald-500/60 text-emerald-700">Paga</Badge>}
                        {companyId === COMPANY_ALL && companyName(inv.company_id) && (
                          <span className="text-xs text-muted-foreground">{companyName(inv.company_id)}</span>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {inv.invoice_number ? `nº ${inv.invoice_number} · ` : ''}
                        {inv.issue_date ? `emissão ${fmtDate(inv.issue_date)} · ` : ''}
                        inserida {fmtDate(inv.created_at)}
                      </p>
                      <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground flex-wrap">
                        <span className="inline-flex items-center gap-1">
                          <User className="h-3.5 w-3.5" /><b className="text-foreground">{inv.origin_user || '—'}</b>
                        </span>
                        {inv.origin_store && (
                          <span className="inline-flex items-center gap-1">
                            <Store className="h-3.5 w-3.5" /><b className="text-foreground">{inv.origin_store}</b>
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      <p className="text-lg font-heading font-bold tabular-nums">{eur(inv.amount)}</p>
                      {inv.has_pdf && (
                        <Button size="sm" variant="ghost" onClick={() => openPdf(inv)} disabled={pdfBusy === inv.id}
                          data-testid={`estoque-pdf-${inv.id}`}>
                          <FileText className="h-4 w-4 mr-1" />PDF
                        </Button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground text-center">
        Para confirmar ou rejeitar as faturas por confirmar, usa a zona “A confirmar” em <b>Financeiro · Pagamentos</b>.
      </p>
    </div>
  );
}
