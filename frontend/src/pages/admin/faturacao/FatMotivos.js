import React, { useEffect, useState } from 'react';
import {
  getMotivos, criarMotivo, editarMotivo, predefinirMotivo, apagarMotivo,
  detalhesErro,
} from '../../../lib/faturacao';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Label } from '../../../components/ui/label';
import { Badge } from '../../../components/ui/badge';
import { Textarea } from '../../../components/ui/textarea';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '../../../components/ui/dialog';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '../../../components/ui/alert-dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../../components/ui/table';
import { FileMinus, Plus, Pencil, Trash2, Star } from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';

const TEXTO_MAX = 200;
const emptyForm = { texto: '' };

export default function FatMotivos() {
  const [motivos, setMotivos] = useState([]);
  const [loading, setLoading] = useState(true);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [settingDefaultId, setSettingDefaultId] = useState(null);

  useEffect(() => { fetchAll(); }, []);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const { data } = await getMotivos();
      setMotivos(data || []);
    } catch (error) {
      toast.error('Erro ao carregar motivos de nota de crédito');
    } finally {
      setLoading(false);
    }
  };

  const openNew = () => { setEditing(null); setForm(emptyForm); setDialogOpen(true); };
  const openEdit = (motivo) => { setEditing(motivo); setForm({ texto: motivo.texto || '' }); setDialogOpen(true); };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const texto = form.texto.trim();
    if (!texto) { toast.error('Indique o texto do motivo'); return; }
    if (texto.length > TEXTO_MAX) { toast.error(`O texto não pode ter mais de ${TEXTO_MAX} caracteres`); return; }
    setSaving(true);
    try {
      if (editing) { await editarMotivo(editing.id, { texto }); toast.success('Motivo atualizado'); }
      else { await criarMotivo({ texto }); toast.success('Motivo criado'); }
      setDialogOpen(false);
      fetchAll();
    } catch (error) {
      const status = error.response?.status;
      if (status === 404) {
        toast.error('Este motivo já não existe. A atualizar a lista...');
        setDialogOpen(false);
        fetchAll();
        return;
      }
      const { mensagem } = detalhesErro(error, 'Erro ao guardar o motivo');
      toast.error(mensagem);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    const alvo = deleteTarget;
    setDeleteTarget(null);
    try {
      await apagarMotivo(alvo.id);
      toast.success('Motivo eliminado');
      fetchAll();
    } catch (error) {
      const status = error.response?.status;
      if (status === 404) {
        toast.error('Este motivo já não existe. A atualizar a lista...');
        fetchAll();
      } else {
        const { mensagem } = detalhesErro(error, 'Erro ao eliminar o motivo');
        toast.error(mensagem);
      }
    }
  };

  const handlePredefinir = async (motivo) => {
    if (motivo.predefinido) return;
    setSettingDefaultId(motivo.id);
    try {
      await predefinirMotivo(motivo.id);
      toast.success('Motivo predefinido atualizado');
      fetchAll();
    } catch (error) {
      const status = error.response?.status;
      if (status === 404) {
        toast.error('Este motivo já não existe. A atualizar a lista...');
        fetchAll();
      } else {
        const { mensagem } = detalhesErro(error, 'Erro ao predefinir o motivo');
        toast.error(mensagem);
      }
    } finally {
      setSettingDefaultId(null);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fat-motivos-page">
      <PageHeader icon={FileMinus} title="Motivos de NC" subtitle="Motivos de nota de crédito disponíveis na faturação">
        <Button onClick={openNew} data-testid="add-motivo-btn"><Plus className="h-4 w-4 mr-2" />Novo motivo</Button>
      </PageHeader>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-32"><div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div></div>
          ) : motivos.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <FileMinus className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="font-medium text-lg">Sem motivos</h3>
              <p className="text-sm text-muted-foreground mt-1">Crie o primeiro motivo de nota de crédito.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Motivo</TableHead>
                    <TableHead>Predefinido</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {motivos.map((motivo) => (
                    <TableRow key={motivo.id} data-testid={`motivo-row-${motivo.id}`}>
                      <TableCell className="font-medium max-w-md">{motivo.texto}</TableCell>
                      <TableCell>
                        {motivo.predefinido ? (
                          <Badge variant="outline" className="bg-amber-50 text-amber-700 border-amber-200 gap-1">
                            <Star className="h-3 w-3 fill-amber-500 text-amber-500" />Predefinido
                          </Badge>
                        ) : (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 text-muted-foreground"
                            disabled={settingDefaultId === motivo.id}
                            onClick={() => handlePredefinir(motivo)}
                            data-testid={`set-default-motivo-${motivo.id}`}
                          >
                            <Star className="h-3.5 w-3.5 mr-1.5" />
                            {settingDefaultId === motivo.id ? 'A atualizar...' : 'Marcar como predefinido'}
                          </Button>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-2">
                          <Button variant="ghost" size="icon" onClick={() => openEdit(motivo)} data-testid={`edit-motivo-${motivo.id}`}>
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="icon" onClick={() => setDeleteTarget(motivo)} data-testid={`delete-motivo-${motivo.id}`}>
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

      {/* Dialog criar/editar */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent data-testid="motivo-dialog">
          <DialogHeader>
            <DialogTitle>{editing ? 'Editar motivo' : 'Novo motivo'}</DialogTitle>
            <DialogDescription>Este texto vai para as observações do documento fiscal emitido no Vendus.</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit}>
            <div className="space-y-2 py-4">
              <Label htmlFor="motivo-texto">Texto *</Label>
              <Textarea
                id="motivo-texto"
                value={form.texto}
                onChange={(e) => setForm({ texto: e.target.value.slice(0, TEXTO_MAX) })}
                placeholder="Ex: Cliente enganou-se no NIF"
                maxLength={TEXTO_MAX}
                rows={3}
                required
                data-testid="motivo-texto-input"
              />
              <p className="text-xs text-muted-foreground text-right">{form.texto.length}/{TEXTO_MAX}</p>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>Cancelar</Button>
              <Button type="submit" disabled={saving} data-testid="save-motivo-btn">{saving ? 'A guardar...' : 'Guardar'}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Confirmar eliminação */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar motivo</AlertDialogTitle>
            <AlertDialogDescription>
              Tem a certeza que pretende eliminar "{deleteTarget?.texto}"? Esta ação não pode ser desfeita.
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
