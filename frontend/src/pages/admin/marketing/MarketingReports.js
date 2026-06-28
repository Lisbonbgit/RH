import React, { useEffect, useState, useCallback } from 'react';
import { useOutletContext, Link } from 'react-router-dom';
import { getMarketingReports } from '../../../lib/api';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Badge } from '../../../components/ui/badge';
import {
  BarChart3, Megaphone, CalendarClock, Euro, Filter, CalendarDays, Clock,
} from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';
import { format, parseISO } from 'date-fns';

const channelLabels = {
  instagram: 'Instagram', facebook: 'Facebook', tiktok: 'TikTok',
  google: 'Google', website: 'Website', outro: 'Outro',
};
const campStatusLabels = { planeada: 'Planeada', ativa: 'Ativa', terminada: 'Terminada' };
const campTypeLabels = { campanha: 'Campanha', promocao: 'Promoção', evento: 'Evento', cupao: 'Cupão' };

const channelDot = {
  instagram: 'bg-pink-500', facebook: 'bg-blue-600', tiktok: 'bg-slate-800',
  google: 'bg-amber-500', website: 'bg-teal-500', outro: 'bg-slate-400',
};

const fmtMoney = (v) => new Intl.NumberFormat('pt-PT', { style: 'currency', currency: 'EUR' }).format(v || 0);
const fmtDate = (d) => { try { return format(parseISO(d), 'dd/MM'); } catch { return d; } };

function Stat({ icon: Icon, label, value, accent = 'text-primary' }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Icon className={`h-4 w-4 ${accent}`} /> {label}
        </div>
        <p className="text-3xl font-heading font-bold mt-1">{value}</p>
      </CardContent>
    </Card>
  );
}

function Distribution({ title, data, labels = {}, money = false, color = 'bg-primary', empty = 'Sem dados' }) {
  const entries = Object.entries(data || {}).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map(([, v]) => v));
  return (
    <Card>
      <CardContent className="p-4 space-y-3">
        <h3 className="font-heading font-semibold text-sm">{title}</h3>
        {entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">{empty}</p>
        ) : (
          <div className="space-y-2.5">
            {entries.map(([k, v]) => (
              <div key={k}>
                <div className="flex justify-between text-xs mb-1">
                  <span className="capitalize">{labels[k] || k}</span>
                  <span className="font-medium">{money ? fmtMoney(v) : v}</span>
                </div>
                <div className="h-2 rounded-full bg-muted overflow-hidden">
                  <div className={`h-full ${color} rounded-full`} style={{ width: `${(v / max) * 100}%` }} />
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function MarketingReports() {
  const { selectedCompany } = useOutletContext();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({ start_date: '', end_date: '' });

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = { company_id: selectedCompany?.id };
      if (filters.start_date) params.start_date = filters.start_date;
      if (filters.end_date) params.end_date = filters.end_date;
      const res = await getMarketingReports(params);
      setData(res.data);
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao carregar os relatórios');
    } finally {
      setLoading(false);
    }
  }, [selectedCompany, filters]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const c = data?.campaigns;
  const p = data?.posts;
  const hasPeriod = filters.start_date || filters.end_date;

  return (
    <div className="space-y-6 animate-fade-in" data-testid="marketing-reports-page">
      <PageHeader
        icon={BarChart3}
        title="Relatórios de Marketing"
        subtitle={selectedCompany ? `Métricas de ${selectedCompany.name}` : 'Métricas de campanhas e conteúdos do grupo'}
      />

      {/* Filtro de período */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-2 mb-4">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <span className="font-medium text-sm">Período</span>
            <span className="text-xs text-muted-foreground">{hasPeriod ? '' : '(a mostrar tudo)'}</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 items-end">
            <div className="space-y-2">
              <Label>Data início</Label>
              <Input type="date" value={filters.start_date}
                onChange={(e) => setFilters({ ...filters, start_date: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label>Data fim</Label>
              <Input type="date" value={filters.end_date}
                onChange={(e) => setFilters({ ...filters, end_date: e.target.value })} />
            </div>
            {hasPeriod && (
              <Button variant="outline" onClick={() => setFilters({ start_date: '', end_date: '' })}>
                Limpar período
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {loading ? (
        <div className="flex items-center justify-center h-40">
          <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
        </div>
      ) : !data ? null : (
        <>
          {/* KPIs */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <Stat icon={Megaphone} label="Campanhas" value={c.total} />
            <Stat icon={Megaphone} label="Campanhas ativas" value={c.active_now} accent="text-teal-600" />
            <Stat icon={Euro} label="Orçamento total" value={fmtMoney(c.total_budget)} accent="text-amber-600" />
            <Stat icon={CalendarClock} label="Publicações" value={p.total} accent="text-blue-600" />
          </div>

          {/* Resumo de publicações por estado */}
          <div className="grid grid-cols-3 gap-4">
            <Stat icon={CalendarDays} label="Ideias" value={p.ideas} accent="text-slate-500" />
            <Stat icon={CalendarClock} label="Agendadas" value={p.scheduled} accent="text-amber-600" />
            <Stat icon={CalendarDays} label="Publicadas" value={p.published} accent="text-teal-600" />
          </div>

          {/* Distribuições */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Distribution title="Campanhas por estado" data={c.by_status} labels={campStatusLabels} />
            <Distribution title="Campanhas por tipo" data={c.by_type} labels={campTypeLabels} color="bg-teal-500" />
            <Distribution title="Orçamento por canal" data={c.budget_by_channel} money color="bg-amber-500"
              empty="Sem orçamento registado" />
            <Distribution title="Publicações por canal" data={p.by_channel} labels={channelLabels} color="bg-blue-500" />
          </div>

          {/* Próximas publicações agendadas */}
          <Card>
            <CardContent className="p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="font-heading font-semibold text-sm flex items-center gap-2">
                  <CalendarClock className="h-4 w-4 text-primary" /> Próximas publicações
                </h3>
                <Link to="/admin/marketing/calendario" className="text-xs text-primary hover:underline">
                  Ver calendário
                </Link>
              </div>
              {(!p.upcoming || p.upcoming.length === 0) ? (
                <p className="text-sm text-muted-foreground">Nada agendado para os próximos dias.</p>
              ) : (
                <div className="divide-y">
                  {p.upcoming.map((post) => (
                    <div key={post.id} className="flex items-center gap-3 py-2.5">
                      <div className="flex flex-col items-center justify-center rounded-md bg-muted px-2.5 py-1 min-w-[48px]">
                        <span className="text-sm font-bold leading-none">{fmtDate(post.scheduled_date)}</span>
                        {post.scheduled_time && (
                          <span className="text-[10px] text-muted-foreground flex items-center gap-0.5 mt-0.5">
                            <Clock className="h-2.5 w-2.5" /> {post.scheduled_time}
                          </span>
                        )}
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium truncate">{post.title}</p>
                      </div>
                      <Badge variant="outline" className="gap-1.5 shrink-0">
                        <span className={`h-2 w-2 rounded-full ${channelDot[post.channel] || 'bg-slate-400'}`} />
                        {channelLabels[post.channel] || post.channel}
                      </Badge>
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
