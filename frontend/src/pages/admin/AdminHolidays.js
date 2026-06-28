import React, { useEffect, useState } from 'react';
import { getHolidays, createHoliday, updateHoliday, deleteHoliday, getCompanies, getLocations } from '../../lib/api';
import { Card, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { Badge } from '../../components/ui/badge';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '../../components/ui/dialog';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '../../components/ui/alert-dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '../../components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../components/ui/table';
import { CalendarOff, Plus, Pencil, Trash2, Building2, MapPin, Users } from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import { toast } from 'sonner';

const months = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'];
const emptyForm = { name: '', day: '1', month: '1', scope: 'group', company_id: '', location_id: '' };

export default function AdminHolidays() {
  const [holidays, setHolidays] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);

  useEffect(() => { fetchAll(); }, []);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [h, c, l] = await Promise.all([getHolidays(), getCompanies(), getLocations()]);
      setHolidays(h.data || []);
      setCompanies(c.data || []);
      setLocations(l.data || []);
    } catch (error) {
      toast.error('Erro ao carregar feriados');
    } finally {
      setLoading(false);
    }
  };

  const openNew = () => { setEditing(null); setForm(emptyForm); setDialogOpen(true); };
  const openEdit = (h) => {
    setEditing(h);
    setForm({
      name: h.name,
      day: String(h.day),
      month: String(h.month),
      scope: h.location_id ? 'location' : h.company_id ? 'company' : 'group',
      company_id: h.company_id || '',
      location_id: h.location_id || '',
    });
    setDialogOpen(true);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) { toast.error('Indique o nome do feriado'); return; }
    if (form.scope === 'company' && !form.company_id) { toast.error('Escolha a empresa'); return; }
    if (form.scope === 'location' && !form.location_id) { toast.error('Escolha a loja'); return; }
    const payload = {
      name: form.name.trim(),
      day: parseInt(form.day, 10),
      month: parseInt(form.month, 10),
      company_id: form.scope === 'company' ? form.company_id : null,
      location_id: form.scope === 'location' ? form.location_id : null,
    };
    setSaving(true);
    try {
      if (editing) { await updateHoliday(editing.id, payload); toast.success('Feriado atualizado'); }
      else { await createHoliday(payload); toast.success('Feriado criado'); }
      setDialogOpen(false);
      fetchAll();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao guardar');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    try {
      await deleteHoliday(deleteTarget.id);
      toast.success('Feriado eliminado');
      setDeleteTarget(null);
      fetchAll();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao eliminar');
    }
  };

  const scopeBadge = (h) => {
    if (h.location_id) return <Badge variant="outline" className="bg-teal-50 text-teal-700 border-teal-200 gap-1"><MapPin className="h-3 w-3" />{h.location_name || 'Loja'}</Badge>;
    if (h.company_id) return <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200 gap-1"><Building2 className="h-3 w-3" />{h.company_name || 'Empresa'}</Badge>;
    return <Badge variant="outline" className="bg-slate-100 text-slate-600 border-slate-200 gap-1"><Users className="h-3 w-3" />Todo o grupo</Badge>;
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="admin-holidays-page">
      <PageHeader icon={CalendarOff} title="Feriados" subtitle="Feriados municipais e personalizados (além dos nacionais)">
        <Button onClick={openNew} data-testid="add-holiday-btn"><Plus className="h-4 w-4 mr-2" />Novo feriado</Button>
      </PageHeader>

      <Card className="bg-app-grid border-primary/10">
        <CardContent className="p-4 text-sm text-muted-foreground">
          Os <strong>feriados nacionais de Portugal</strong> já são considerados automaticamente e não contam como dias de férias.
          Aqui adiciona os <strong>municipais</strong> (ex.: Santo António, São João) ou outros, que <strong>recorrem todos os anos</strong> na mesma data.
          Pode aplicá-los a todo o grupo, a uma empresa ou só a uma loja.
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-32"><div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div></div>
          ) : holidays.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <CalendarOff className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="font-medium text-lg">Sem feriados personalizados</h3>
              <p className="text-sm text-muted-foreground mt-1">Adicione o primeiro feriado municipal.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Data</TableHead>
                    <TableHead>Feriado</TableHead>
                    <TableHead>Âmbito</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {holidays.map((h) => (
                    <TableRow key={h.id} data-testid={`holiday-row-${h.id}`}>
                      <TableCell className="font-medium tabular-nums whitespace-nowrap">
                        {String(h.day).padStart(2, '0')} {months[h.month - 1]}
                      </TableCell>
                      <TableCell>{h.name}</TableCell>
                      <TableCell>{scopeBadge(h)}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-2">
                          <Button variant="ghost" size="icon" onClick={() => openEdit(h)} data-testid={`edit-holiday-${h.id}`}><Pencil className="h-4 w-4" /></Button>
                          <Button variant="ghost" size="icon" onClick={() => setDeleteTarget(h)} data-testid={`delete-holiday-${h.id}`}><Trash2 className="h-4 w-4 text-destructive" /></Button>
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

      {/* Dialog criar/editar */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent data-testid="holiday-dialog">
          <DialogHeader>
            <DialogTitle>{editing ? 'Editar feriado' : 'Novo feriado'}</DialogTitle>
            <DialogDescription>Recorre todos os anos na data indicada.</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit}>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="h-name">Nome *</Label>
                <Input id="h-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Ex: Santo António" required data-testid="holiday-name-input" />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Dia</Label>
                  <Select value={form.day} onValueChange={(v) => setForm({ ...form, day: v })}>
                    <SelectTrigger data-testid="holiday-day-select"><SelectValue /></SelectTrigger>
                    <SelectContent className="max-h-60">
                      {Array.from({ length: 31 }, (_, i) => i + 1).map((d) => (<SelectItem key={d} value={String(d)}>{d}</SelectItem>))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Mês</Label>
                  <Select value={form.month} onValueChange={(v) => setForm({ ...form, month: v })}>
                    <SelectTrigger data-testid="holiday-month-select"><SelectValue /></SelectTrigger>
                    <SelectContent className="max-h-60">
                      {months.map((m, i) => (<SelectItem key={m} value={String(i + 1)}>{m}</SelectItem>))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="space-y-2">
                <Label>Aplica-se a</Label>
                <Select value={form.scope} onValueChange={(v) => setForm({ ...form, scope: v })}>
                  <SelectTrigger data-testid="holiday-scope-select"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="group">Todo o grupo</SelectItem>
                    <SelectItem value="company">Uma empresa</SelectItem>
                    <SelectItem value="location">Uma loja</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {form.scope === 'company' && (
                <div className="space-y-2">
                  <Label>Empresa</Label>
                  <Select value={form.company_id} onValueChange={(v) => setForm({ ...form, company_id: v })}>
                    <SelectTrigger data-testid="holiday-company-select"><SelectValue placeholder="Selecionar empresa" /></SelectTrigger>
                    <SelectContent>
                      {companies.map((c) => (<SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>))}
                    </SelectContent>
                  </Select>
                </div>
              )}
              {form.scope === 'location' && (
                <div className="space-y-2">
                  <Label>Loja</Label>
                  <Select value={form.location_id} onValueChange={(v) => setForm({ ...form, location_id: v })}>
                    <SelectTrigger data-testid="holiday-location-select"><SelectValue placeholder="Selecionar loja" /></SelectTrigger>
                    <SelectContent>
                      {locations.map((l) => (<SelectItem key={l.id} value={l.id}>{l.name}{l.company_name ? ` — ${l.company_name}` : ''}</SelectItem>))}
                    </SelectContent>
                  </Select>
                </div>
              )}
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>Cancelar</Button>
              <Button type="submit" disabled={saving} data-testid="save-holiday-btn">{saving ? 'A guardar...' : 'Guardar'}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Confirmar eliminação */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar feriado</AlertDialogTitle>
            <AlertDialogDescription>
              Tem a certeza que pretende eliminar "{deleteTarget?.name}"?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} className="bg-destructive text-destructive-foreground">Eliminar</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
