import React, { useEffect, useMemo, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { getPosts, createPost, updatePost, deletePost, getCompanies } from '../../../lib/api';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Textarea } from '../../../components/ui/textarea';
import { Badge } from '../../../components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../../components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../../components/ui/select';
import {
  CalendarDays, Plus, Pencil, Trash2, ChevronLeft, ChevronRight, Clock,
  LayoutGrid, List, Lightbulb, CalendarPlus,
} from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';
import {
  format, parseISO, isSameMonth, addMonths, subMonths, startOfMonth, endOfMonth,
  startOfWeek, endOfWeek, eachDayOfInterval, isToday, isWeekend,
} from 'date-fns';
import { pt } from 'date-fns/locale';

const channelInfo = {
  instagram: { label: 'Instagram', className: 'bg-pink-50 text-pink-700 border-pink-200', dot: 'bg-pink-500' },
  facebook: { label: 'Facebook', className: 'bg-blue-50 text-blue-700 border-blue-200', dot: 'bg-blue-600' },
  tiktok: { label: 'TikTok', className: 'bg-slate-100 text-slate-700 border-slate-300', dot: 'bg-slate-800' },
  google: { label: 'Google', className: 'bg-amber-50 text-amber-700 border-amber-200', dot: 'bg-amber-500' },
  website: { label: 'Website', className: 'bg-teal-50 text-teal-700 border-teal-200', dot: 'bg-teal-500' },
  outro: { label: 'Outro', className: 'bg-muted text-muted-foreground border-border', dot: 'bg-slate-400' },
};
const statusInfo = {
  ideia: { label: 'Ideia', className: 'bg-slate-100 text-slate-600 border-slate-200' },
  agendado: { label: 'Agendado', className: 'bg-blue-50 text-blue-700 border-blue-200' },
  publicado: { label: 'Publicado', className: 'bg-teal-50 text-teal-700 border-teal-200' },
};

const weekdays = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'];
const dateKey = (d) => format(d, 'yyyy-MM-dd');
const emptyForm = { title: '', channel: 'instagram', company_id: '', scheduled_date: '', scheduled_time: '', status: 'ideia', content: '' };

export default function MarketingCalendar() {
  const { selectedCompany } = useOutletContext();
  const [posts, setPosts] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refDate, setRefDate] = useState(new Date());
  const [channelFilter, setChannelFilter] = useState('');
  const [view, setView] = useState('calendario'); // calendario | agenda
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [dayDialogDate, setDayDialogDate] = useState(null);

  useEffect(() => {
    getCompanies().then((res) => setCompanies(res.data || [])).catch(() => {});
  }, []);

  useEffect(() => {
    fetchPosts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channelFilter, selectedCompany]);

  const fetchPosts = async () => {
    setLoading(true);
    try {
      const params = {};
      if (channelFilter) params.channel = channelFilter;
      if (selectedCompany?.id) params.company_id = selectedCompany.id;
      const res = await getPosts(params);
      setPosts(res.data || []);
    } catch (error) {
      toast.error('Erro ao carregar publicações');
    } finally {
      setLoading(false);
    }
  };

  // Publicações com data, indexadas por dia (todas) + ideias sem data
  const { postsByDate, undated } = useMemo(() => {
    const map = {};
    const undatedList = [];
    for (const p of posts) {
      if (!p.scheduled_date) { undatedList.push(p); continue; }
      (map[p.scheduled_date] = map[p.scheduled_date] || []).push(p);
    }
    Object.values(map).forEach((arr) => arr.sort((a, b) => (a.scheduled_time || '').localeCompare(b.scheduled_time || '')));
    return { postsByDate: map, undated: undatedList };
  }, [posts]);

  // Agenda do mês (só dias com publicações, ordenados)
  const byDay = useMemo(() => {
    return Object.keys(postsByDate)
      .filter((k) => isSameMonth(parseISO(k), refDate))
      .sort()
      .map((k) => ({ date: k, items: postsByDate[k] }));
  }, [postsByDate, refDate]);

  // Estatísticas do mês visível
  const stats = useMemo(() => {
    const s = { total: 0, ideia: 0, agendado: 0, publicado: 0 };
    for (const p of posts) {
      if (!p.scheduled_date || !isSameMonth(parseISO(p.scheduled_date), refDate)) continue;
      s.total += 1;
      s[p.status] = (s[p.status] || 0) + 1;
    }
    return s;
  }, [posts, refDate]);

  // Grelha do mês (semanas completas, segunda a domingo)
  const gridDays = useMemo(() => {
    const start = startOfWeek(startOfMonth(refDate), { weekStartsOn: 1 });
    const end = endOfWeek(endOfMonth(refDate), { weekStartsOn: 1 });
    return eachDayOfInterval({ start, end });
  }, [refDate]);

  const openNew = (date = '') => {
    setDayDialogDate(null);
    setEditing(null);
    setForm({ ...emptyForm, scheduled_date: date || '', status: date ? 'agendado' : 'ideia' });
    setDialogOpen(true);
  };
  const openEdit = (p) => {
    setDayDialogDate(null);
    setEditing(p);
    setForm({
      title: p.title || '', channel: p.channel || 'instagram', company_id: p.company_id || '',
      scheduled_date: p.scheduled_date || '', scheduled_time: p.scheduled_time || '',
      status: p.status || 'ideia', content: p.content || '',
    });
    setDialogOpen(true);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.title.trim()) { toast.error('Indique o título da publicação'); return; }
    const payload = {
      title: form.title,
      channel: form.channel,
      company_id: form.company_id || null,
      scheduled_date: form.scheduled_date || null,
      scheduled_time: form.scheduled_time || null,
      status: form.status,
      content: form.content || null,
    };
    setSaving(true);
    try {
      if (editing) { await updatePost(editing.id, payload); toast.success('Publicação atualizada'); }
      else { await createPost(payload); toast.success('Publicação criada'); }
      setDialogOpen(false);
      fetchPosts();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao guardar');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (p) => {
    if (!window.confirm(`Eliminar a publicação "${p.title}"?`)) return;
    try { await deletePost(p.id); toast.success('Publicação eliminada'); fetchPosts(); }
    catch (error) { toast.error(error.response?.data?.detail || 'Erro ao eliminar'); }
  };

  const PostCard = ({ p }) => (
    <div className="flex items-start gap-3 p-3 rounded-xl border bg-card hover:shadow-sm transition-shadow" data-testid={`post-${p.id}`}>
      <span className={`mt-1 h-2.5 w-2.5 rounded-full shrink-0 ${(channelInfo[p.channel] || {}).dot || 'bg-slate-400'}`} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          {p.scheduled_time && (
            <span className="text-xs text-muted-foreground flex items-center gap-1 tabular-nums"><Clock className="h-3 w-3" />{p.scheduled_time}</span>
          )}
          <Badge variant="outline" className={(channelInfo[p.channel] || {}).className}>{(channelInfo[p.channel] || {}).label || p.channel}</Badge>
          <Badge variant="outline" className={(statusInfo[p.status] || {}).className}>{(statusInfo[p.status] || {}).label || p.status}</Badge>
        </div>
        <p className="font-medium text-sm mt-1.5">{p.title}</p>
        {p.company_name && <p className="text-xs text-muted-foreground">{p.company_name}</p>}
        {p.content && <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{p.content}</p>}
      </div>
      <div className="flex items-center gap-1 shrink-0">
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => openEdit(p)} data-testid={`edit-post-${p.id}`}><Pencil className="h-4 w-4" /></Button>
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => handleDelete(p)} data-testid={`delete-post-${p.id}`}><Trash2 className="h-4 w-4 text-destructive" /></Button>
      </div>
    </div>
  );

  const StatPill = ({ label, value, className }) => (
    <div className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${className}`}>
      <span className="font-heading font-bold tabular-nums">{value}</span>{label}
    </div>
  );

  return (
    <div className="space-y-5 animate-fade-in" data-testid="marketing-calendar-page">
      <PageHeader icon={CalendarDays} title="Calendário de conteúdos" subtitle="Planeie e agende as publicações nas redes sociais">
        <Select value={channelFilter || '__all__'} onValueChange={(v) => setChannelFilter(v === '__all__' ? '' : v)}>
          <SelectTrigger className="w-40" data-testid="channel-filter"><SelectValue placeholder="Todos os canais" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">Todos os canais</SelectItem>
            {Object.entries(channelInfo).map(([k, c]) => (<SelectItem key={k} value={k}>{c.label}</SelectItem>))}
          </SelectContent>
        </Select>
        <Button onClick={() => openNew()} data-testid="add-post-btn"><Plus className="h-4 w-4 mr-2" />Nova publicação</Button>
      </PageHeader>

      {/* Barra de controlo: navegador de mês + estatísticas + alternância de vista */}
      <Card className="bg-app-grid border-primary/10">
        <CardContent className="p-4 flex flex-col lg:flex-row lg:items-center gap-4">
          <div className="flex items-center gap-3">
            <Button variant="outline" size="icon" onClick={() => setRefDate(subMonths(refDate, 1))} data-testid="prev-month"><ChevronLeft className="h-4 w-4" /></Button>
            <div className="min-w-[180px] text-center">
              <p className="text-lg font-heading font-bold capitalize leading-none text-brand-gradient">{format(refDate, 'MMMM', { locale: pt })}</p>
              <p className="text-xs text-muted-foreground mt-0.5">{format(refDate, 'yyyy')}</p>
            </div>
            <Button variant="outline" size="icon" onClick={() => setRefDate(addMonths(refDate, 1))} data-testid="next-month"><ChevronRight className="h-4 w-4" /></Button>
            <Button variant="ghost" size="sm" className="text-xs" onClick={() => setRefDate(new Date())}>Hoje</Button>
          </div>

          <div className="flex flex-wrap items-center gap-2 lg:ml-2">
            <StatPill label="no mês" value={stats.total} className="bg-primary/10 text-primary" />
            <StatPill label="ideias" value={stats.ideia} className="bg-slate-100 text-slate-600" />
            <StatPill label="agendadas" value={stats.agendado} className="bg-blue-50 text-blue-700" />
            <StatPill label="publicadas" value={stats.publicado} className="bg-teal-50 text-teal-700" />
          </div>

          <div className="lg:ml-auto inline-flex rounded-lg border bg-card p-0.5">
            <button
              onClick={() => setView('calendario')}
              className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${view === 'calendario' ? 'bg-primary text-primary-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
            >
              <LayoutGrid className="h-4 w-4" /> Calendário
            </button>
            <button
              onClick={() => setView('agenda')}
              className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${view === 'agenda' ? 'bg-primary text-primary-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
            >
              <List className="h-4 w-4" /> Agenda
            </button>
          </div>
        </CardContent>
      </Card>

      {loading ? (
        <div className="flex items-center justify-center h-40"><div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div></div>
      ) : view === 'calendario' ? (
        /* ===== VISTA CALENDÁRIO (grelha) ===== */
        <div className="rounded-2xl border shadow-sm overflow-hidden bg-card">
          <div className="overflow-x-auto">
            <div className="min-w-[720px] bg-border">
              {/* cabeçalho dos dias da semana */}
              <div className="grid grid-cols-7 gap-px">
                {weekdays.map((w, i) => (
                  <div key={w} className={`bg-card px-2 py-2.5 text-[11px] font-semibold uppercase tracking-wider ${i >= 5 ? 'text-primary/70' : 'text-muted-foreground'}`}>{w}</div>
                ))}
              </div>
              {/* dias */}
              <div className="grid grid-cols-7 gap-px mt-px">
                {gridDays.map((day) => {
                  const key = dateKey(day);
                  const items = postsByDate[key] || [];
                  const inMonth = isSameMonth(day, refDate);
                  const today = isToday(day);
                  return (
                    <div
                      key={key}
                      onClick={() => setDayDialogDate(key)}
                      className={`group relative min-h-[116px] p-1.5 cursor-pointer transition-colors
                        ${inMonth ? (isWeekend(day) ? 'bg-muted/20' : 'bg-card') : 'bg-muted/40'}
                        hover:bg-primary/[0.04]`}
                    >
                      <div className="flex items-center justify-between">
                        <span className={`text-xs font-semibold h-6 w-6 flex items-center justify-center rounded-full tabular-nums
                          ${today ? 'brand-gradient text-white shadow' : inMonth ? 'text-foreground' : 'text-muted-foreground/50'}`}>
                          {format(day, 'd')}
                        </span>
                        <button
                          onClick={(e) => { e.stopPropagation(); openNew(key); }}
                          className="opacity-0 group-hover:opacity-100 transition h-5 w-5 rounded-md hover:bg-primary/10 text-primary flex items-center justify-center"
                          title="Nova publicação neste dia"
                        >
                          <Plus className="h-3.5 w-3.5" />
                        </button>
                      </div>
                      <div className="mt-1 space-y-1">
                        {items.slice(0, 3).map((p) => (
                          <button
                            key={p.id}
                            onClick={(e) => { e.stopPropagation(); openEdit(p); }}
                            className={`w-full text-left text-[11px] leading-tight rounded-md px-1.5 py-1 border flex items-center gap-1 hover:ring-1 hover:ring-primary/40 transition ${(channelInfo[p.channel] || {}).className || ''}`}
                            title={p.title}
                          >
                            <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${(channelInfo[p.channel] || {}).dot || 'bg-slate-400'}`} />
                            {p.scheduled_time && <span className="tabular-nums opacity-70 shrink-0">{p.scheduled_time}</span>}
                            <span className="truncate font-medium">{p.title}</span>
                          </button>
                        ))}
                        {items.length > 3 && (
                          <button
                            onClick={(e) => { e.stopPropagation(); setDayDialogDate(key); }}
                            className="text-[11px] font-medium text-primary hover:underline pl-1"
                          >
                            +{items.length - 3} mais
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
          {/* legenda de canais */}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-4 py-3 border-t bg-muted/20">
            <span className="text-[11px] uppercase tracking-wide text-muted-foreground font-semibold">Canais</span>
            {Object.entries(channelInfo).map(([k, c]) => (
              <span key={k} className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                <span className={`h-2 w-2 rounded-full ${c.dot}`} /> {c.label}
              </span>
            ))}
          </div>
        </div>
      ) : (
        /* ===== VISTA AGENDA (lista) ===== */
        byDay.length === 0 ? (
          <Card><CardContent className="py-16 flex flex-col items-center text-center text-muted-foreground">
            <CalendarPlus className="h-10 w-10 mb-3 opacity-50" />
            <p>Sem publicações agendadas neste mês.</p>
            <Button variant="outline" size="sm" className="mt-4" onClick={() => openNew()}><Plus className="h-4 w-4 mr-1.5" />Criar publicação</Button>
          </CardContent></Card>
        ) : (
          <div className="space-y-5">
            {byDay.map(({ date, items }) => (
              <div key={date}>
                <div className="flex items-center gap-3 mb-2">
                  <div className="h-11 w-11 rounded-xl brand-gradient text-white flex flex-col items-center justify-center leading-none shadow-sm">
                    <span className="text-[10px] uppercase tracking-wide">{format(parseISO(date), 'EEE', { locale: pt })}</span>
                    <span className="text-base font-bold">{format(parseISO(date), 'd')}</span>
                  </div>
                  <div>
                    <p className="text-sm font-medium capitalize leading-tight">{format(parseISO(date), "EEEE", { locale: pt })}</p>
                    <p className="text-xs text-muted-foreground capitalize">{format(parseISO(date), "d 'de' MMMM", { locale: pt })}</p>
                  </div>
                  <Badge variant="outline" className="ml-auto">{items.length} {items.length === 1 ? 'publicação' : 'publicações'}</Badge>
                </div>
                <div className="space-y-2 pl-1">
                  {items.map((p) => (<PostCard key={p.id} p={p} />))}
                </div>
              </div>
            ))}
          </div>
        )
      )}

      {/* Ideias sem data */}
      {!loading && undated.length > 0 && (
        <Card className="border-dashed">
          <CardContent className="p-4">
            <h3 className="text-sm font-heading font-semibold text-muted-foreground mb-3 flex items-center gap-2">
              <Lightbulb className="h-4 w-4 text-amber-500" /> Ideias (sem data)
              <Badge variant="outline" className="ml-1">{undated.length}</Badge>
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {undated.map((p) => (<PostCard key={p.id} p={p} />))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Diálogo de detalhe do dia */}
      <Dialog open={!!dayDialogDate} onOpenChange={(o) => !o && setDayDialogDate(null)}>
        <DialogContent className="max-h-[90vh] overflow-y-auto" data-testid="day-dialog">
          <DialogHeader>
            <DialogTitle className="capitalize">
              {dayDialogDate && format(parseISO(dayDialogDate), "EEEE, d 'de' MMMM", { locale: pt })}
            </DialogTitle>
            <DialogDescription>
              {dayDialogDate && (postsByDate[dayDialogDate]?.length
                ? `${postsByDate[dayDialogDate].length} publicação(ões) neste dia`
                : 'Sem publicações neste dia')}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            {dayDialogDate && (postsByDate[dayDialogDate] || []).map((p) => (<PostCard key={p.id} p={p} />))}
            {dayDialogDate && !(postsByDate[dayDialogDate] || []).length && (
              <p className="text-sm text-muted-foreground text-center py-4">Ainda nada planeado. Adicione a primeira publicação.</p>
            )}
          </div>
          <DialogFooter>
            <Button onClick={() => openNew(dayDialogDate)} data-testid="day-add-post"><CalendarPlus className="h-4 w-4 mr-2" />Nova publicação neste dia</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Diálogo criar/editar */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto" data-testid="post-dialog">
          <DialogHeader>
            <DialogTitle>{editing ? 'Editar publicação' : 'Nova publicação'}</DialogTitle>
            <DialogDescription>Planeie um conteúdo para as redes sociais.</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit}>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="p-title">Título *</Label>
                <Input id="p-title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Ex: Post do novo sabor de açaí" required data-testid="post-title-input" />
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Canal</Label>
                  <Select value={form.channel} onValueChange={(v) => setForm({ ...form, channel: v })}>
                    <SelectTrigger data-testid="post-channel-select"><SelectValue /></SelectTrigger>
                    <SelectContent>{Object.entries(channelInfo).map(([k, c]) => (<SelectItem key={k} value={k}>{c.label}</SelectItem>))}</SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Estado</Label>
                  <Select value={form.status} onValueChange={(v) => setForm({ ...form, status: v })}>
                    <SelectTrigger data-testid="post-status-select"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="ideia">Ideia</SelectItem>
                      <SelectItem value="agendado">Agendado</SelectItem>
                      <SelectItem value="publicado">Publicado</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="p-date">Data</Label>
                  <Input id="p-date" type="date" value={form.scheduled_date} onChange={(e) => setForm({ ...form, scheduled_date: e.target.value })} data-testid="post-date-input" />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="p-time">Hora</Label>
                  <Input id="p-time" type="time" value={form.scheduled_time} onChange={(e) => setForm({ ...form, scheduled_time: e.target.value })} data-testid="post-time-input" />
                </div>
                <div className="space-y-2">
                  <Label>Empresa</Label>
                  <Select value={form.company_id || '__all__'} onValueChange={(v) => setForm({ ...form, company_id: v === '__all__' ? '' : v })}>
                    <SelectTrigger data-testid="post-company-select"><SelectValue placeholder="Todo o grupo" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__all__">Todo o grupo</SelectItem>
                      {companies.map((co) => (<SelectItem key={co.id} value={co.id}>{co.name}</SelectItem>))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="p-content">Conteúdo / legenda</Label>
                <Textarea id="p-content" value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} rows={3} placeholder="Texto da publicação, hashtags, notas..." data-testid="post-content-input" />
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>Cancelar</Button>
              <Button type="submit" disabled={saving} data-testid="save-post-btn">{saving ? 'A guardar...' : 'Guardar'}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
