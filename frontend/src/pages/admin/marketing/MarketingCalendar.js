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
import { CalendarDays, Plus, Pencil, Trash2, ChevronLeft, ChevronRight, Clock } from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';
import { format, parseISO, isSameMonth, addMonths, subMonths } from 'date-fns';
import { pt } from 'date-fns/locale';

const channelInfo = {
  instagram: { label: 'Instagram', className: 'bg-pink-50 text-pink-700 border-pink-200' },
  facebook: { label: 'Facebook', className: 'bg-blue-50 text-blue-700 border-blue-200' },
  tiktok: { label: 'TikTok', className: 'bg-slate-100 text-slate-700 border-slate-200' },
  google: { label: 'Google', className: 'bg-amber-50 text-amber-700 border-amber-200' },
  website: { label: 'Website', className: 'bg-teal-50 text-teal-700 border-teal-200' },
  outro: { label: 'Outro', className: 'bg-muted text-muted-foreground border-border' },
};
const statusInfo = {
  ideia: { label: 'Ideia', className: 'bg-slate-100 text-slate-600 border-slate-200' },
  agendado: { label: 'Agendado', className: 'bg-blue-50 text-blue-700 border-blue-200' },
  publicado: { label: 'Publicado', className: 'bg-teal-50 text-teal-700 border-teal-200' },
};

const emptyForm = { title: '', channel: 'instagram', company_id: '', scheduled_date: '', scheduled_time: '', status: 'ideia', content: '' };

export default function MarketingCalendar() {
  const { selectedCompany } = useOutletContext();
  const [posts, setPosts] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refDate, setRefDate] = useState(new Date());
  const [channelFilter, setChannelFilter] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);

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

  // Publicações do mês selecionado, agrupadas por dia + as "ideias sem data"
  const { byDay, undated } = useMemo(() => {
    const map = {};
    const undatedList = [];
    for (const p of posts) {
      if (!p.scheduled_date) {
        undatedList.push(p);
        continue;
      }
      let d;
      try { d = parseISO(p.scheduled_date); } catch { continue; }
      if (!isSameMonth(d, refDate)) continue;
      const key = p.scheduled_date;
      if (!map[key]) map[key] = [];
      map[key].push(p);
    }
    const sortedKeys = Object.keys(map).sort();
    sortedKeys.forEach((k) => map[k].sort((a, b) => (a.scheduled_time || '').localeCompare(b.scheduled_time || '')));
    return { byDay: sortedKeys.map((k) => ({ date: k, items: map[k] })), undated: undatedList };
  }, [posts, refDate]);

  const openNew = () => { setEditing(null); setForm(emptyForm); setDialogOpen(true); };
  const openEdit = (p) => {
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
    <div className="flex items-start gap-3 p-3 rounded-xl border bg-card" data-testid={`post-${p.id}`}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          {p.scheduled_time && (
            <span className="text-xs text-muted-foreground flex items-center gap-1"><Clock className="h-3 w-3" />{p.scheduled_time}</span>
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

  return (
    <div className="space-y-6 animate-fade-in" data-testid="marketing-calendar-page">
      <PageHeader icon={CalendarDays} title="Calendário de conteúdos" subtitle="Planear e agendar publicações nas redes sociais">
        <Select value={channelFilter || '__all__'} onValueChange={(v) => setChannelFilter(v === '__all__' ? '' : v)}>
          <SelectTrigger className="w-40" data-testid="channel-filter"><SelectValue placeholder="Todos os canais" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">Todos os canais</SelectItem>
            {Object.entries(channelInfo).map(([k, c]) => (<SelectItem key={k} value={k}>{c.label}</SelectItem>))}
          </SelectContent>
        </Select>
        <Button onClick={openNew} data-testid="add-post-btn"><Plus className="h-4 w-4 mr-2" />Nova publicação</Button>
      </PageHeader>

      {/* Navegação de mês */}
      <div className="flex items-center justify-center gap-2">
        <Button variant="outline" size="icon" onClick={() => setRefDate(subMonths(refDate, 1))} data-testid="prev-month"><ChevronLeft className="h-4 w-4" /></Button>
        <span className="min-w-[160px] text-center font-medium capitalize">{format(refDate, "MMMM 'de' yyyy", { locale: pt })}</span>
        <Button variant="outline" size="icon" onClick={() => setRefDate(addMonths(refDate, 1))} data-testid="next-month"><ChevronRight className="h-4 w-4" /></Button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-32"><div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div></div>
      ) : (
        <>
          {/* Agenda do mês */}
          {byDay.length === 0 ? (
            <Card><CardContent className="py-12 text-center text-muted-foreground">Sem publicações agendadas neste mês.</CardContent></Card>
          ) : (
            <div className="space-y-4">
              {byDay.map(({ date, items }) => (
                <div key={date}>
                  <div className="flex items-center gap-2 mb-2">
                    <div className="h-9 w-9 rounded-lg brand-gradient text-white flex flex-col items-center justify-center leading-none">
                      <span className="text-[10px] uppercase">{format(parseISO(date), 'EEE', { locale: pt })}</span>
                      <span className="text-sm font-bold">{format(parseISO(date), 'd')}</span>
                    </div>
                    <span className="text-sm font-medium capitalize">{format(parseISO(date), "EEEE, d 'de' MMMM", { locale: pt })}</span>
                  </div>
                  <div className="space-y-2 pl-1">
                    {items.map((p) => (<PostCard key={p.id} p={p} />))}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Ideias sem data */}
          {undated.length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-2 flex items-center gap-2">💡 Ideias (sem data)</h3>
              <div className="space-y-2">
                {undated.map((p) => (<PostCard key={p.id} p={p} />))}
              </div>
            </div>
          )}
        </>
      )}

      {/* Diálogo */}
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
