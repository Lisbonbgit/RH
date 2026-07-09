import React, { useState, useEffect } from 'react';
import {
  getFinCompanies, getFinGlobalDashboard, getCompanies, linkFinCompanyRh,
  syncNowVendus, syncNowMoloni, syncNowIngest,
} from '../../../lib/api';
import { eur, normSup } from '../../../lib/finance';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Card, CardContent } from '../../../components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../components/ui/select';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '../../../components/ui/dialog';
import {
  LayoutDashboard, TrendingUp, CircleDollarSign, Check, AlertTriangle, Landmark,
  Users, CalendarOff, Megaphone, Link2, Gauge, RefreshCw, Store, Factory, Mail,
} from 'lucide-react';
import { toast } from 'sonner';
import PageHeader from '../../../components/PageHeader';

const LS_KEY = 'fin_selected_company';
const COMPANY_ALL = 'all';
const currentMonth = () => new Date().toISOString().slice(0, 7);

// Cartão de KPI (mesmo visual do Resumo em FinPagamentos).
function KpiCard({ label, value, icon: Icon }) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-5">
        <div className="h-10 w-10 rounded-xl brand-gradient text-white flex items-center justify-center shrink-0">
          <Icon className="h-5 w-5" />
        </div>
        <div className="min-w-0">
          <p className="text-xl font-heading font-bold leading-none truncate">{value}</p>
          <p className="text-xs text-muted-foreground mt-1">{label}</p>
        </div>
      </CardContent>
    </Card>
  );
}

// Formata número/nulo para apresentação (— quando não disponível).
const num = (n) => (n == null ? '—' : Number(n).toLocaleString('pt-PT'));

export default function PainelGlobal() {
  const [companies, setCompanies] = useState([]);
  const [companyId, setCompanyId] = useState(localStorage.getItem(LS_KEY) || '');
  const [month, setMonth] = useState(currentMonth());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  // Dialog "Ligar ao RH"
  const [linkOpen, setLinkOpen] = useState(false);
  const [rhCompanies, setRhCompanies] = useState([]);
  const [rhChoice, setRhChoice] = useState('');
  const [linking, setLinking] = useState(false);

  // Botões "Atualizar agora" (qual sistema está a sincronizar, ou null)
  const [syncBusy, setSyncBusy] = useState(null);

  useEffect(() => { loadCompanies(); }, []);
  useEffect(() => {
    if (companyId) { localStorage.setItem(LS_KEY, companyId); loadDashboard(); }
    else { setData(null); }
  }, [companyId, month]); // eslint-disable-line react-hooks/exhaustive-deps

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

  const loadDashboard = async () => {
    setLoading(true);
    try {
      const res = await getFinGlobalDashboard({ company_id: companyId, month });
      setData(res.data);
    } catch (e) {
      toast.error('Erro ao carregar o painel');
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  const fin = data?.financeiro || {};
  const rh = data?.rh || {};
  const mkt = data?.marketing || {};
  const cruzados = data?.cruzados || {};

  // ---------- Dialog "Ligar ao RH" ----------
  const openLink = async () => {
    try {
      const res = await getCompanies();
      const list = res.data || [];
      setRhCompanies(list);
      // Sugestão automática: nome do Financeiro ~ nome do RH (minúsculas, sem acentos).
      const finName = normSup(data?.company?.name);
      const match = finName
        ? list.find((c) => normSup(c.name) === finName)
          || list.find((c) => finName && normSup(c.name).includes(finName))
          || list.find((c) => finName && finName.includes(normSup(c.name)))
        : null;
      setRhChoice(match?.id || (list[0]?.id ?? ''));
      setLinkOpen(true);
    } catch (e) {
      toast.error('Erro ao carregar empresas do RH');
    }
  };

  const confirmLink = async () => {
    if (!rhChoice) { toast.error('Escolhe uma empresa do RH'); return; }
    setLinking(true);
    try {
      await linkFinCompanyRh(companyId, rhChoice);
      toast.success('Empresa ligada ao RH');
      setLinkOpen(false);
      loadDashboard();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erro ao ligar ao RH');
    } finally {
      setLinking(false);
    }
  };

  const hasReceita = cruzados.receita_por_colaborador != null;

  // ---------- Botões "Atualizar agora" (um por sistema) ----------
  const SYNCS = {
    vendus: { fn: syncNowVendus, nome: 'Vendus (lojas)' },
    moloni: { fn: syncNowMoloni, nome: 'Moloni (fábrica)' },
    ingest: { fn: syncNowIngest, nome: 'Faturas do email' },
  };
  const runSync = async (kind) => {
    setSyncBusy(kind);
    try {
      const res = await SYNCS[kind].fn();
      const d = res.data || {};
      let resumo;
      if (kind === 'ingest') {
        resumo = `${d.invoices_created ?? 0} faturas novas · ${d.attachments_seen ?? 0} anexos lidos`;
      } else {
        resumo = `${d.written ?? 0} dias de vendas atualizados`;
      }
      const errors = d.errors || [];
      if (errors.length) {
        toast.warning(`${SYNCS[kind].nome}: ${resumo} · ${errors.length} avisos`, { description: String(errors[0]) });
      } else {
        toast.success(`${SYNCS[kind].nome}: ${resumo}`);
      }
      loadDashboard();
    } catch (e) {
      toast.error(e.response?.data?.detail || `Erro ao atualizar ${SYNCS[kind].nome}`);
    } finally {
      setSyncBusy(null);
    }
  };

  const SyncBtn = ({ kind, icon: Icon, label }) => (
    <Button variant="outline" size="sm" disabled={syncBusy !== null}
      onClick={() => runSync(kind)} data-testid={`sync-now-${kind}`}>
      {syncBusy === kind
        ? <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
        : <Icon className="h-4 w-4 mr-2" />}
      {syncBusy === kind ? 'A atualizar...' : label}
    </Button>
  );

  return (
    <div className="space-y-6 animate-fade-in" data-testid="painel-global-page">
      <PageHeader icon={LayoutDashboard} title="Painel Global" subtitle="Visão cruzada dos setores">
        <div className="flex flex-wrap items-center gap-2">
          {companies.length > 0 && (
            <Select value={companyId} onValueChange={setCompanyId}>
              <SelectTrigger className="w-48" data-testid="painel-company-picker">
                <SelectValue placeholder="Empresa" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={COMPANY_ALL}>Todas as empresas</SelectItem>
                {companies
                  .filter((c) => normSup(c.name) !== 'por classificar')
                  .map((c) => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}
              </SelectContent>
            </Select>
          )}
          <Input
            type="month"
            className="w-40"
            value={month}
            onChange={(e) => setMonth(e.target.value || currentMonth())}
            data-testid="painel-month-picker"
          />
        </div>
      </PageHeader>

      {/* Atualização instantânea — um botão por sistema de faturação. */}
      {companies.length > 0 && (
        <Card>
          <CardContent className="p-3 flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mr-1">
              Atualizar agora
            </span>
            <SyncBtn kind="vendus" icon={Store} label="Vendus (lojas)" />
            <SyncBtn kind="moloni" icon={Factory} label="Moloni (fábrica)" />
            <SyncBtn kind="ingest" icon={Mail} label="Faturas do email" />
            <span className="text-[11px] text-muted-foreground ml-auto hidden sm:inline">
              Automático: vendas a cada hora · faturas às 07:00
            </span>
          </CardContent>
        </Card>
      )}

      {companies.length === 0 ? (
        <Card><CardContent className="py-12 text-center text-muted-foreground">
          Ainda não tens empresas. Cria uma no separador <b>Financeiro › Início</b> primeiro.
        </CardContent></Card>
      ) : loading ? (
        <div className="flex justify-center h-40 items-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
        </div>
      ) : !data ? (
        <Card><CardContent className="py-12 text-center text-muted-foreground">
          Sem dados para o período selecionado.
        </CardContent></Card>
      ) : (
        <div className="space-y-8">
          {/* ---------- KPI cruzado em destaque ---------- */}
          {hasReceita && (
            <Card className="border-primary/30">
              <CardContent className="flex items-center gap-4 p-6">
                <div className="h-14 w-14 rounded-2xl brand-gradient text-white flex items-center justify-center shrink-0">
                  <Gauge className="h-7 w-7" />
                </div>
                <div>
                  <p className="text-3xl font-heading font-bold leading-none" data-testid="painel-receita-colaborador">
                    {eur(cruzados.receita_por_colaborador)}
                  </p>
                  <p className="text-sm text-muted-foreground mt-1">Receita por colaborador (mês)</p>
                </div>
              </CardContent>
            </Card>
          )}

          {/* ---------- FINANCEIRO ---------- */}
          <section className="space-y-3">
            <h2 className="text-sm font-heading font-bold uppercase tracking-wide text-muted-foreground">Financeiro</h2>
            <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
              <KpiCard label="Vendas do mês" value={eur(fin.vendas_mes)} icon={TrendingUp} />
              <KpiCard label="A pagar" value={eur(fin.a_pagar)} icon={CircleDollarSign} />
              <KpiCard label="Pago" value={eur(fin.pago)} icon={Check} />
              <KpiCard label="Vencidas" value={num(fin.vencidas)} icon={AlertTriangle} />
              <KpiCard label="Saldo banco" value={eur(fin.saldo_banco)} icon={Landmark} />
            </div>
          </section>

          {/* ---------- RH ---------- */}
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-heading font-bold uppercase tracking-wide text-muted-foreground">RH</h2>
              {rh.linked === false && (
                <Button variant="ghost" size="sm" className="h-7 px-2 text-xs text-muted-foreground"
                  onClick={openLink} data-testid="painel-link-rh-btn">
                  <Link2 className="h-3 w-3 mr-1" />Ligar ao RH
                </Button>
              )}
            </div>
            {rh.linked && (
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                <KpiCard label="Colaboradores" value={num(rh.colaboradores)} icon={Users} />
                <KpiCard label="Ausências pendentes" value={num(rh.ausencias_pendentes)} icon={CalendarOff} />
              </div>
            )}
            {/* Quem está a trabalhar agora, agrupado por loja */}
            <Card>
              <CardContent className="p-5 space-y-3" data-testid="painel-a-trabalhar">
                <div className="flex items-center gap-2">
                  <div className="h-8 w-8 rounded-lg brand-gradient text-white flex items-center justify-center shrink-0">
                    <Users className="h-4 w-4" />
                  </div>
                  <p className="font-medium text-sm">
                    A trabalhar agora
                    <span className="text-muted-foreground font-normal"> · {(rh.a_trabalhar || []).length} pessoa{(rh.a_trabalhar || []).length === 1 ? '' : 's'}</span>
                  </p>
                </div>
                {(rh.a_trabalhar || []).length === 0 ? (
                  <p className="text-sm text-muted-foreground">Ninguém com entrada registada neste momento.</p>
                ) : (
                  Object.entries(
                    (rh.a_trabalhar || []).reduce((acc, p) => {
                      (acc[p.loja] = acc[p.loja] || []).push(p);
                      return acc;
                    }, {})
                  ).map(([loja, pessoas]) => (
                    <div key={loja} className="space-y-1.5">
                      <p className="text-xs font-semibold text-muted-foreground">{loja}</p>
                      <div className="flex flex-wrap gap-1.5">
                        {pessoas.map((p) => (
                          <span key={p.nome + loja}
                            className="inline-flex items-center gap-1.5 rounded-full border bg-muted/50 px-2.5 py-1 text-xs">
                            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 shrink-0" />
                            <span className="font-medium">{p.nome}</span>
                            {p.desde && <span className="text-muted-foreground">desde {p.desde}</span>}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))
                )}
              </CardContent>
            </Card>
          </section>

          {/* ---------- MARKETING ---------- */}
          <section className="space-y-3">
            <h2 className="text-sm font-heading font-bold uppercase tracking-wide text-muted-foreground">Marketing</h2>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              <KpiCard label="Campanhas ativas" value={num(mkt.campanhas_ativas)} icon={Megaphone} />
            </div>
          </section>
        </div>
      )}

      {/* ---------- Dialog "Ligar ao RH" ---------- */}
      <Dialog open={linkOpen} onOpenChange={setLinkOpen}>
        <DialogContent data-testid="painel-link-rh-dialog">
          <DialogHeader>
            <DialogTitle>Ligar ao RH</DialogTitle>
            <DialogDescription>
              Escolhe a empresa do RH que corresponde a <b>{data?.company?.name}</b>.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            <Label className="text-xs">Empresa do RH</Label>
            {rhCompanies.length === 0 ? (
              <p className="text-sm text-muted-foreground">Não há empresas no RH para ligar.</p>
            ) : (
              <Select value={rhChoice} onValueChange={setRhChoice}>
                <SelectTrigger data-testid="painel-rh-company-select"><SelectValue placeholder="Empresa do RH" /></SelectTrigger>
                <SelectContent>
                  {rhCompanies.map((c) => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}
                </SelectContent>
              </Select>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setLinkOpen(false)}>Cancelar</Button>
            <Button
              type="button"
              onClick={confirmLink}
              disabled={linking || rhCompanies.length === 0}
              data-testid="painel-confirm-link-rh"
            >
              {linking ? 'A ligar...' : 'Ligar'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
