import React, { useEffect, useState } from 'react';
import { getCampaigns, createCampaign, updateCampaign, deleteCampaign, getCompanies } from '../../../lib/api';
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../../components/ui/table';
import { Megaphone, Plus, Pencil, Trash2, Filter } from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';
import { format, parseISO } from 'date-fns';

const typeLabels = { campanha: 'Campanha', promocao: 'Promoção', evento: 'Evento', cupao: 'Cupão' };
const statusInfo = {
  planeada: { label: 'Planeada', className: 'bg-amber-50 text-amber-700 border-amber-200' },
  ativa: { label: 'Ativa', className: 'bg-teal-50 text-teal-700 border-teal-200' },
  terminada: { label: 'Terminada', className: 'bg-slate-100 text-slate-600 border-slate-200' },
};

const emptyForm = {
  name: '', type: 'campanha', company_id: '', start_date: '', end_date: '',
  status: 'planeada', channel: '', budget: '', description: '', result: '',
};

const fmtDate = (d) => {
  if (!d) return '—';
  try { return format(parseISO(d), 'dd/MM/yyyy'); } catch { return d; }
};

export default function MarketingCampaigns() {
  const [campaigns, setCampaigns] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getCompanies().then((res) => setCompanies(res.data || [])).catch(() => {});
  }, []);

  useEffect(() => {
    fetchCampaigns();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter]);

  const fetchCampaigns = async () => {
    setLoading(true);
    try {
      const params = {};
      if (statusFilter) params.status = statusFilter;
      const res = await getCampaigns(params);
      setCampaigns(res.data || []);
    } catch (error) {
      toast.error('Erro ao carregar campanhas');
    } finally {
      setLoading(false);
    }
  };

  const openNew = () => {
    setEditing(null);
    setForm(emptyForm);
    setDialogOpen(true);
  };

  const openEdit = (c) => {
    setEditing(c);
    setForm({
      name: c.name || '', type: c.type || 'campanha', company_id: c.company_id || '',
      start_date: c.start_date || '', end_date: c.end_date || '', status: c.status || 'planeada',
      channel: c.channel || '', budget: c.budget ?? '', description: c.description || '', result: c.result || '',
    });
    setDialogOpen(true);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) { toast.error('Indique o nome da campanha'); return; }
    if (form.start_date && form.end_date && form.start_date > form.end_date) {
      toast.error('A data de início não pode ser depois da data de fim');
      return;
    }
    const payload = {
      name: form.name,
      type: form.type,
      company_id: form.company_id || null,
      start_date: form.start_date || null,
      end_date: form.end_date || null,
      status: form.status,
      channel: form.channel || null,
      budget: form.budget === '' ? null : parseFloat(form.budget),
      description: form.description || null,
      result: form.result || null,
    };
    setSaving(true);
    try {
      if (editing) {
        await updateCampaign(editing.id, payload);
        toast.success('Campanha atualizada');
      } else {
        await createCampaign(payload);
        toast.success('Campanha criada');
      }
      setDialogOpen(false);
      fetchCampaigns();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao guardar');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (c) => {
    if (!window.confirm(`Eliminar a campanha "${c.name}"?`)) return;
    try {
      await deleteCampaign(c.id);
      toast.success('Campanha eliminada');
      fetchCampaigns();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao eliminar');
    }
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="marketing-campaigns-page">
      <PageHeader icon={Megaphone} title="Campanhas e promoções" subtitle="Gerir campanhas, promoções e cupões do grupo">
        <Button onClick={openNew} data-testid="add-campaign-btn">
          <Plus className="h-4 w-4 mr-2" />
          Nova campanha
        </Button>
      </PageHeader>

      {/* Filtro */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-3">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <span className="text-sm font-medium">Estado</span>
            <Select value={statusFilter || '__all__'} onValueChange={(v) => setStatusFilter(v === '__all__' ? '' : v)}>
              <SelectTrigger className="w-48" data-testid="campaign-status-filter">
                <SelectValue placeholder="Todos" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">Todos</SelectItem>
                <SelectItem value="planeada">Planeada</SelectItem>
                <SelectItem value="ativa">Ativa</SelectItem>
                <SelectItem value="terminada">Terminada</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {/* Lista */}
      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-32">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
            </div>
          ) : campaigns.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Megaphone className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="font-medium text-lg">Sem campanhas</h3>
              <p className="text-sm text-muted-foreground mt-1">Crie a primeira campanha ou promoção</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Campanha</TableHead>
                    <TableHead className="hidden sm:table-cell">Tipo</TableHead>
                    <TableHead className="hidden md:table-cell">Empresa</TableHead>
                    <TableHead className="hidden lg:table-cell">Período</TableHead>
                    <TableHead>Estado</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {campaigns.map((c) => (
                    <TableRow key={c.id} data-testid={`campaign-row-${c.id}`}>
                      <TableCell>
                        <p className="font-medium">{c.name}</p>
                        {c.channel && <p className="text-xs text-muted-foreground">{c.channel}</p>}
                      </TableCell>
                      <TableCell className="hidden sm:table-cell">
                        <Badge variant="outline">{typeLabels[c.type] || c.type}</Badge>
                      </TableCell>
                      <TableCell className="hidden md:table-cell text-sm">{c.company_name || 'Todo o grupo'}</TableCell>
                      <TableCell className="hidden lg:table-cell text-sm text-muted-foreground">
                        {c.start_date || c.end_date ? `${fmtDate(c.start_date)} – ${fmtDate(c.end_date)}` : '—'}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className={(statusInfo[c.status] || {}).className}>
                          {(statusInfo[c.status] || {}).label || c.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button variant="ghost" size="icon" onClick={() => openEdit(c)} data-testid={`edit-campaign-${c.id}`}>
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="icon" onClick={() => handleDelete(c)} data-testid={`delete-campaign-${c.id}`}>
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
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

      {/* Diálogo criar/editar */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto" data-testid="campaign-dialog">
          <DialogHeader>
            <DialogTitle>{editing ? 'Editar campanha' : 'Nova campanha'}</DialogTitle>
            <DialogDescription>Detalhes da campanha, promoção ou cupão.</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit}>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="c-name">Nome *</Label>
                <Input id="c-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Ex: Promoção de Verão" required data-testid="campaign-name-input" />
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Tipo</Label>
                  <Select value={form.type} onValueChange={(v) => setForm({ ...form, type: v })}>
                    <SelectTrigger data-testid="campaign-type-select"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {Object.entries(typeLabels).map(([k, l]) => (<SelectItem key={k} value={k}>{l}</SelectItem>))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Estado</Label>
                  <Select value={form.status} onValueChange={(v) => setForm({ ...form, status: v })}>
                    <SelectTrigger data-testid="campaign-status-select"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="planeada">Planeada</SelectItem>
                      <SelectItem value="ativa">Ativa</SelectItem>
                      <SelectItem value="terminada">Terminada</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Empresa</Label>
                  <Select value={form.company_id || '__all__'} onValueChange={(v) => setForm({ ...form, company_id: v === '__all__' ? '' : v })}>
                    <SelectTrigger data-testid="campaign-company-select"><SelectValue placeholder="Todo o grupo" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__all__">Todo o grupo</SelectItem>
                      {companies.map((co) => (<SelectItem key={co.id} value={co.id}>{co.name}</SelectItem>))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="c-channel">Canal</Label>
                  <Input id="c-channel" value={form.channel} onChange={(e) => setForm({ ...form, channel: e.target.value })} placeholder="Ex: Instagram, Loja..." data-testid="campaign-channel-input" />
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="c-start">Início</Label>
                  <Input id="c-start" type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} data-testid="campaign-start-input" />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="c-end">Fim</Label>
                  <Input id="c-end" type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} data-testid="campaign-end-input" />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="c-budget">Orçamento (€)</Label>
                  <Input id="c-budget" type="number" min="0" step="0.01" value={form.budget} onChange={(e) => setForm({ ...form, budget: e.target.value })} placeholder="0" data-testid="campaign-budget-input" />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="c-desc">Descrição / objetivo</Label>
                <Textarea id="c-desc" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} rows={2} placeholder="O que é a campanha e qual o objetivo" data-testid="campaign-desc-input" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="c-result">Resultado / notas</Label>
                <Textarea id="c-result" value={form.result} onChange={(e) => setForm({ ...form, result: e.target.value })} rows={2} placeholder="Resultados obtidos (opcional)" data-testid="campaign-result-input" />
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>Cancelar</Button>
              <Button type="submit" disabled={saving} data-testid="save-campaign-btn">{saving ? 'A guardar...' : 'Guardar'}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
