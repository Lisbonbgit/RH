import React, { useState, useEffect, useCallback } from 'react';
import { useOutletContext } from 'react-router-dom';
import {
  getFinReportIva, getFinReportDre, getFinReportTesouraria, getFinReportExport,
} from '../../../lib/api';
import { eur, kpiTone } from '../../../lib/finance';
import { Button } from '../../../components/ui/button';
import { Card, CardContent } from '../../../components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../../../components/ui/tabs';
import { Badge } from '../../../components/ui/badge';
import {
  BarChart3, Percent, Landmark, Download, AlertTriangle, TrendingUp, Receipt, FileSpreadsheet,
} from 'lucide-react';
import { toast } from 'sonner';
import PageHeader from '../../../components/PageHeader';
import MonthPicker from '../../../components/MonthPicker';

const COMPANY_ALL = 'all';
const thisMonth = () => new Date().toISOString().slice(0, 7);
const MESES = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'];

// Intervalo (start,end) de um mês (ano, mês 1-12).
const mesRange = (yy, mm) => ({
  start: `${yy}-${String(mm).padStart(2, '0')}-01`,
  end: `${yy}-${String(mm).padStart(2, '0')}-${String(new Date(yy, mm, 0).getDate()).padStart(2, '0')}`,
});
// Trimestre que contém o mês 'YYYY-MM': {label, ano, q(0-3), meses:[1-12,...]}.
const trimestreDe = (ym) => {
  const [yy, mm] = ym.split('-').map(Number);
  const q = Math.floor((mm - 1) / 3);
  const meses = [q * 3 + 1, q * 3 + 2, q * 3 + 3];
  return { ano: yy, q, meses, label: `T${q + 1} ${yy} · ${MESES[meses[0] - 1].slice(0, 3)}–${MESES[meses[2] - 1].slice(0, 3)}` };
};

const CAT_LABEL = {
  mercadoria: 'Mercadoria', rendas: 'Rendas', energia_agua: 'Água/Energia',
  salarios: 'Salários', servicos: 'Serviços', impostos: 'Impostos',
  outros: 'Outros', sem_categoria: 'Sem categoria',
};
const taxaLabel = (k) => (k === 'sem_taxa' ? 'Sem taxa' : `${k}%`);

// Cartão de KPI (mesmo visual das outras páginas do Financeiro).
// `tone` controla a cor do VALOR (bom/mau); `colorIdx` escolhe a cor do badge do ícone (paleta RH).
function Kpi({ label, value, icon: Icon, tone, colorIdx = 0 }) {
  const toneCls = tone === 'bad' ? 'text-destructive' : tone === 'good' ? 'text-emerald-600 dark:text-emerald-400' : '';
  const badge = kpiTone(colorIdx);
  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-4">
        <div className={`h-10 w-10 rounded-xl ${badge.bg} ${badge.icon} flex items-center justify-center shrink-0`}>
          <Icon className="h-5 w-5" />
        </div>
        <div className="min-w-0">
          <p className={`text-lg font-heading font-bold leading-none truncate ${toneCls}`}>{value}</p>
          <p className="text-xs text-muted-foreground mt-1">{label}</p>
        </div>
      </CardContent>
    </Card>
  );
}

function Spinner() {
  return (
    <div className="flex justify-center h-24 items-center">
      <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary" />
    </div>
  );
}

// Linha "taxa → valor" para as decomposições de IVA.
function TaxaRows({ por_taxa }) {
  const entries = Object.entries(por_taxa || {}).filter(([, v]) => Math.abs(Number(v) || 0) > 0.005);
  if (!entries.length) return <p className="text-xs text-muted-foreground">Sem valores.</p>;
  return (
    <div className="space-y-1">
      {entries.map(([k, v]) => (
        <div key={k} className="flex items-center justify-between text-sm">
          <span className="text-muted-foreground">{taxaLabel(k)}</span>
          <span className="font-medium tabular-nums">{eur(v)}</span>
        </div>
      ))}
    </div>
  );
}

export default function FinRelatorios() {
  const { selectedCompany } = useOutletContext();
  const [companyId, setCompanyId] = useState('');
  const [month, setMonth] = useState(thisMonth());
  const [weeks] = useState(8);

  const [iva, setIva] = useState(null);
  const [dre, setDre] = useState(null);
  const [tes, setTes] = useState(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState('');
  // IVA por trimestre (regime trimestral): agrega os 3 meses do trimestre do mês selecionado.
  const [ivaTri, setIvaTri] = useState(false);
  const [tri, setTri] = useState(null);
  const [triLoading, setTriLoading] = useState(false);

  useEffect(() => {
    setCompanyId(selectedCompany ? selectedCompany.id : COMPANY_ALL);
  }, [selectedCompany]);

  // Mês YYYY-MM -> intervalo start/end.
  const [y, m] = month.split('-').map(Number);
  const start = `${month}-01`;
  const end = y && m ? `${month}-${String(new Date(y, m, 0).getDate()).padStart(2, '0')}` : `${month}-28`;

  const load = useCallback(async () => {
    if (!companyId) return;
    setLoading(true);
    try {
      const [ri, rd, rt] = await Promise.all([
        getFinReportIva({ company_id: companyId, start, end }),
        getFinReportDre({ company_id: companyId, start, end }),
        getFinReportTesouraria({ company_id: companyId, weeks }),
      ]);
      setIva(ri.data); setDre(rd.data); setTes(rt.data);
    } catch (e) {
      toast.error('Erro ao carregar os relatórios');
      setIva(null); setDre(null); setTes(null);
    } finally {
      setLoading(false);
    }
  }, [companyId, start, end, weeks]);

  useEffect(() => { load(); }, [load]);

  // Carrega o trimestre (3 meses) quando o modo trimestral está ligado.
  const loadTri = useCallback(async () => {
    if (!companyId) return;
    const t = trimestreDe(month);
    setTriLoading(true);
    try {
      const res = await Promise.all(t.meses.map((mm) => {
        const r = mesRange(t.ano, mm);
        return getFinReportIva({ company_id: companyId, start: r.start, end: r.end });
      }));
      const meses = res.map((r, i) => ({
        nome: MESES[t.meses[i] - 1],
        liquidado: r.data.liquidado?.total || 0,
        dedutivel: r.data.dedutivel?.total || 0,
        saldo: r.data.saldo || 0,
      }));
      const liquidado = meses.reduce((s, x) => s + x.liquidado, 0);
      const dedutivel = meses.reduce((s, x) => s + x.dedutivel, 0);
      const saldo = +(liquidado - dedutivel).toFixed(2);
      setTri({ label: t.label, meses, liquidado: +liquidado.toFixed(2), dedutivel: +dedutivel.toFixed(2),
        saldo, a_pagar: Math.max(0, saldo), a_recuperar: Math.max(0, -saldo) });
    } catch (e) {
      toast.error('Erro ao carregar o trimestre');
      setTri(null);
    } finally {
      setTriLoading(false);
    }
  }, [companyId, month]);

  useEffect(() => { if (ivaTri) loadTri(); }, [ivaTri, loadTri]);

  const doExport = async (kind) => {
    setExporting(kind);
    try {
      const res = await getFinReportExport({ company_id: companyId, start, end, kind });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement('a');
      a.href = url;
      a.download = kind === 'invoices' ? `faturas_${start}_a_${end}.csv` : `vendas_${start}_a_${end}.csv`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
      toast.success('Ficheiro gerado');
    } catch (e) {
      toast.error('Erro ao exportar');
    } finally {
      setExporting('');
    }
  };

  const despesas = dre?.despesas?.por_categoria || {};
  const despEntries = Object.entries(despesas).sort((a, b) => b[1] - a[1]);

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fin-relatorios-page">
      <PageHeader icon={BarChart3} title="Relatórios" subtitle="Apuramento de IVA, resultados, exportação e tesouraria">
        <MonthPicker value={month} onChange={setMonth} className="w-44" testid="fin-rel-month" />
      </PageHeader>

      <Tabs defaultValue="iva">
        <TabsList className="grid grid-cols-2 sm:grid-cols-4 h-auto">
          <TabsTrigger value="iva" className="px-2 truncate">IVA</TabsTrigger>
          <TabsTrigger value="dre" className="px-2 truncate">Resultados</TabsTrigger>
          <TabsTrigger value="export" className="px-2 truncate">Exportação</TabsTrigger>
          <TabsTrigger value="tesouraria" className="px-2 truncate">Tesouraria</TabsTrigger>
        </TabsList>

        {/* ---------- IVA ---------- */}
        <TabsContent value="iva" className="space-y-4 mt-4">
          {/* Interruptor Mês / Trimestre (regime trimestral). */}
          <div className="inline-flex rounded-lg border p-0.5 text-sm">
            <button type="button" onClick={() => setIvaTri(false)}
              className={`px-3 py-1 rounded-md transition-colors ${!ivaTri ? 'bg-primary text-primary-foreground' : 'text-muted-foreground'}`}
              data-testid="fin-iva-mes">Mês</button>
            <button type="button" onClick={() => setIvaTri(true)}
              className={`px-3 py-1 rounded-md transition-colors ${ivaTri ? 'bg-primary text-primary-foreground' : 'text-muted-foreground'}`}
              data-testid="fin-iva-trimestre">Trimestre</button>
          </div>

          {!ivaTri ? (
            loading ? <Spinner /> : !iva ? null : (
              <>
                <div className="grid gap-4 md:grid-cols-3">
                  <Kpi label="IVA liquidado (vendas)" value={eur(iva.liquidado?.total)} icon={TrendingUp} colorIdx={0} />
                  <Kpi label="IVA dedutível (compras)" value={eur(iva.dedutivel?.total)} icon={Receipt} colorIdx={1} />
                  {iva.a_pagar > 0
                    ? <Kpi label="A pagar ao Estado" value={eur(iva.a_pagar)} icon={Landmark} tone="bad" colorIdx={2} />
                    : <Kpi label="A recuperar" value={eur(iva.a_recuperar)} icon={Landmark} tone="good" colorIdx={2} />}
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                  <Card><CardContent className="p-4 space-y-2">
                    <p className="text-sm font-semibold">Liquidado por taxa</p>
                    <TaxaRows por_taxa={iva.liquidado?.por_taxa} />
                  </CardContent></Card>
                  <Card><CardContent className="p-4 space-y-2">
                    <p className="text-sm font-semibold">Dedutível por taxa</p>
                    <TaxaRows por_taxa={iva.dedutivel?.por_taxa} />
                  </CardContent></Card>
                </div>
                <p className="text-xs text-muted-foreground">
                  IVA liquidado (vendas) − dedutível (compras) no período. Valor indicativo — confirma sempre com o teu contabilista.
                </p>
              </>
            )
          ) : (
            triLoading ? <Spinner /> : !tri ? null : (
              <>
                <p className="text-sm font-semibold">{tri.label}</p>
                <div className="grid gap-4 md:grid-cols-3">
                  <Kpi label="IVA liquidado (trimestre)" value={eur(tri.liquidado)} icon={TrendingUp} colorIdx={0} />
                  <Kpi label="IVA dedutível (trimestre)" value={eur(tri.dedutivel)} icon={Receipt} colorIdx={1} />
                  {tri.a_pagar > 0
                    ? <Kpi label="A pagar ao Estado" value={eur(tri.a_pagar)} icon={Landmark} tone="bad" colorIdx={2} />
                    : <Kpi label="A recuperar" value={eur(tri.a_recuperar)} icon={Landmark} tone="good" colorIdx={2} />}
                </div>
                <Card><CardContent className="p-4 space-y-2">
                  <p className="text-sm font-semibold">Detalhe por mês</p>
                  <div className="space-y-1">
                    <div className="flex items-center justify-between text-xs text-muted-foreground uppercase tracking-wide">
                      <span className="w-24">Mês</span>
                      <span className="flex-1 text-right">Liquidado</span>
                      <span className="flex-1 text-right">Dedutível</span>
                      <span className="flex-1 text-right">Saldo</span>
                    </div>
                    {tri.meses.map((mm) => (
                      <div key={mm.nome} className="flex items-center justify-between text-sm py-1 border-b last:border-0">
                        <span className="w-24 text-muted-foreground">{mm.nome}</span>
                        <span className="flex-1 text-right tabular-nums">{eur(mm.liquidado)}</span>
                        <span className="flex-1 text-right tabular-nums">{eur(mm.dedutivel)}</span>
                        <span className={`flex-1 text-right tabular-nums font-medium ${mm.saldo > 0 ? 'text-destructive' : ''}`}>{eur(mm.saldo)}</span>
                      </div>
                    ))}
                    <div className="flex items-center justify-between text-sm pt-1 font-bold font-heading">
                      <span className="w-24">Total</span>
                      <span className="flex-1 text-right tabular-nums">{eur(tri.liquidado)}</span>
                      <span className="flex-1 text-right tabular-nums">{eur(tri.dedutivel)}</span>
                      <span className={`flex-1 text-right tabular-nums ${tri.saldo > 0 ? 'text-destructive' : 'text-emerald-600 dark:text-emerald-400'}`}>{eur(tri.saldo)}</span>
                    </div>
                  </div>
                </CardContent></Card>
                <p className="text-xs text-muted-foreground">
                  Trimestre do mês selecionado no topo. IVA liquidado − dedutível dos 3 meses. Valor indicativo — confirma com o teu contabilista.
                </p>
              </>
            )
          )}
        </TabsContent>

        {/* ---------- DRE ---------- */}
        <TabsContent value="dre" className="space-y-4 mt-4">
          {loading ? <Spinner /> : !dre ? null : (
            <>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <Kpi label="Vendas líquidas" value={eur(dre.vendas_liquidas)} icon={TrendingUp} colorIdx={0} />
                <Kpi label="CMV (custo)" value={eur(dre.cmv)} icon={Receipt} colorIdx={1} />
                <Kpi label="Margem bruta" value={eur(dre.margem_bruta)} icon={Percent} colorIdx={2} />
                <Kpi label="Resultado" value={eur(dre.resultado)} icon={BarChart3}
                  tone={dre.resultado >= 0 ? 'good' : 'bad'} colorIdx={3} />
              </div>
              <Card><CardContent className="p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-semibold">Demonstração de resultados</p>
                  <Badge variant="secondary">Food cost {(Number(dre.food_cost_pct) || 0).toLocaleString('pt-PT', { maximumFractionDigits: 1 })}%</Badge>
                </div>
                <div className="space-y-1 text-sm">
                  <Row label="Vendas líquidas" value={eur(dre.vendas_liquidas)} />
                  <Row label="− CMV" value={eur(-Math.abs(dre.cmv || 0))} />
                  <Row label="= Margem bruta" value={eur(dre.margem_bruta)} bold />
                  <div className="pt-2 mt-1 border-t space-y-1">
                    <p className="text-xs text-muted-foreground uppercase tracking-wide">Despesas</p>
                    {despEntries.length === 0
                      ? <p className="text-xs text-muted-foreground">Sem despesas classificadas no período.</p>
                      : despEntries.map(([cat, val]) => (
                        <Row key={cat} label={CAT_LABEL[cat] || cat} value={eur(-Math.abs(val))} muted />
                      ))}
                    <Row label="− Total despesas" value={eur(-Math.abs(dre.despesas?.total || 0))} />
                  </div>
                  <div className="pt-2 mt-1 border-t">
                    <Row label="= Resultado" value={eur(dre.resultado)} bold
                      tone={dre.resultado >= 0 ? 'good' : 'bad'} />
                  </div>
                </div>
              </CardContent></Card>
              <p className="text-xs text-muted-foreground">
                Classifica as faturas por categoria (no separador Pagamentos) para as despesas aparecerem detalhadas aqui.
              </p>
            </>
          )}
        </TabsContent>

        {/* ---------- Exportação ---------- */}
        <TabsContent value="export" className="space-y-4 mt-4">
          <Card><CardContent className="p-5 space-y-4">
            <div className="flex items-start gap-3">
              <div className="h-10 w-10 rounded-xl brand-gradient text-white flex items-center justify-center shrink-0">
                <FileSpreadsheet className="h-5 w-5" />
              </div>
              <div>
                <p className="font-semibold">Exportar para o contabilista</p>
                <p className="text-sm text-muted-foreground">
                  Faturas e vendas do período <b>{start}</b> a <b>{end}</b> em CSV (abre no Excel).
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => doExport('invoices')} disabled={!!exporting}
                data-testid="fin-rel-export-invoices">
                <Download className="h-4 w-4 mr-2" />
                {exporting === 'invoices' ? 'A gerar...' : 'Exportar faturas'}
              </Button>
              <Button variant="outline" onClick={() => doExport('sales')} disabled={!!exporting}
                data-testid="fin-rel-export-sales">
                <Download className="h-4 w-4 mr-2" />
                {exporting === 'sales' ? 'A gerar...' : 'Exportar vendas'}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Colunas com base, IVA, taxa e total — prontas para o contabilista não reintroduzir tudo à mão.
            </p>
          </CardContent></Card>
        </TabsContent>

        {/* ---------- Tesouraria ---------- */}
        <TabsContent value="tesouraria" className="space-y-4 mt-4">
          {loading ? <Spinner /> : !tes ? null : (
            <>
              <div className="grid gap-4 sm:grid-cols-2">
                <Kpi label="Saldo atual em banco" value={eur(tes.saldo_atual)} icon={Landmark} colorIdx={0} />
                {tes.em_atraso > 0
                  ? <Kpi label="Em atraso (por pagar)" value={eur(tes.em_atraso)} icon={AlertTriangle} tone="bad" colorIdx={1} />
                  : <Kpi label="Em atraso" value={eur(0)} icon={AlertTriangle} colorIdx={1} />}
              </div>
              <Card><CardContent className="p-4 space-y-2">
                <p className="text-sm font-semibold">Próximas {tes.semanas?.length || 0} semanas</p>
                <div className="space-y-1">
                  {(tes.semanas || []).map((s) => (
                    <div key={s.inicio} className="flex items-center justify-between gap-3 text-sm py-1 border-b last:border-0">
                      <span className="text-muted-foreground w-28 shrink-0">{s.label}</span>
                      <span className="tabular-nums text-right flex-1">−{eur(s.saidas)}</span>
                      <span className={`tabular-nums text-right w-28 font-medium inline-flex items-center justify-end gap-1 ${s.negativo ? 'text-destructive' : ''}`}>
                        {s.negativo && <AlertTriangle className="h-3.5 w-3.5" />}{eur(s.saldo_previsto)}
                      </span>
                    </div>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground pt-1">
                  Projeção só das saídas conhecidas (faturas por pagar). Não inclui vendas futuras.
                </p>
              </CardContent></Card>
            </>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

// Linha de uma demonstração (label à esquerda, valor à direita).
function Row({ label, value, bold, muted, tone }) {
  const toneCls = tone === 'bad' ? 'text-destructive' : tone === 'good' ? 'text-emerald-600 dark:text-emerald-400' : '';
  return (
    <div className="flex items-center justify-between">
      <span className={muted ? 'text-muted-foreground pl-3' : ''}>{label}</span>
      <span className={`tabular-nums ${bold ? 'font-bold font-heading' : ''} ${toneCls}`}>{value}</span>
    </div>
  );
}
