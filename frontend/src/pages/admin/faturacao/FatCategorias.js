import React, { useEffect, useState } from 'react';
import {
  getCategorias, criarCategoria, editarCategoria, apagarCategoria,
  detalhesErro,
} from '../../../lib/faturacao';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Badge } from '../../../components/ui/badge';
import { Switch } from '../../../components/ui/switch';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '../../../components/ui/dialog';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '../../../components/ui/alert-dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../../components/ui/table';
import { Tag, Plus, Pencil, Trash2 } from 'lucide-react';
import PageHeader from '../../../components/PageHeader';
import { toast } from 'sonner';

const NOME_MAX = 80;
const emptyForm = { nome: '', ordem: '0', ativa: true };

const estadoBadge = (ativa) => (
  ativa !== false
    ? <Badge variant="outline" className="bg-teal-50 text-teal-700 border-teal-200">Ativa</Badge>
    : <Badge variant="outline" className="bg-slate-100 text-slate-600 border-slate-200">Inativa</Badge>
);

export default function FatCategorias() {
  const [categorias, setCategorias] = useState([]);
  const [loading, setLoading] = useState(true);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [fieldErrors, setFieldErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);

  useEffect(() => { fetchAll(); }, []);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const { data } = await getCategorias();
      setCategorias(data || []);
    } catch (error) {
      toast.error('Erro ao carregar categorias');
    } finally {
      setLoading(false);
    }
  };

  const openNew = () => { setEditing(null); setForm(emptyForm); setFieldErrors({}); setDialogOpen(true); };
  const openEdit = (categoria) => {
    setEditing(categoria);
    setForm({
      nome: categoria.nome || '',
      ordem: String(categoria.ordem ?? 0),
      ativa: categoria.ativa !== false,
    });
    setFieldErrors({});
    setDialogOpen(true);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const nome = form.nome.trim();
    if (!nome) { toast.error('Indique o nome da categoria'); return; }
    if (nome.length > NOME_MAX) { toast.error(`O nome não pode ter mais de ${NOME_MAX} caracteres`); return; }
    const payload = {
      nome,
      ordem: parseInt(form.ordem, 10) || 0,
      ativa: form.ativa,
    };
    setSaving(true);
    setFieldErrors({});
    try {
      if (editing) { await editarCategoria(editing.id, payload); toast.success('Categoria atualizada'); }
      else { await criarCategoria(payload); toast.success('Categoria criada'); }
      setDialogOpen(false);
      fetchAll();
    } catch (error) {
      const status = error.response?.status;
      if (status === 404) {
        toast.error('Esta categoria já não existe. A atualizar a lista...');
        setDialogOpen(false);
        fetchAll();
        return;
      }
      const { campo, mensagem } = detalhesErro(error, 'Erro ao guardar a categoria');
      if (campo) setFieldErrors({ [campo]: mensagem });
      toast.error(mensagem);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    const alvo = deleteTarget;
    setDeleteTarget(null);
    try {
      await apagarCategoria(alvo.id);
      toast.success('Categoria eliminada');
      fetchAll();
    } catch (error) {
      const status = error.response?.status;
      if (status === 409) {
        toast.error(error.response?.data?.detail || 'Esta categoria ainda tem produtos. Mude-os de categoria primeiro.');
      } else if (status === 404) {
        toast.error('Esta categoria já não existe. A atualizar a lista...');
        fetchAll();
      } else {
        toast.error(error.response?.data?.detail || 'Erro ao eliminar a categoria');
      }
    }
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fat-categorias-page">
      <PageHeader
        icon={Tag}
        title="Categorias"
        subtitle="Venda ao Público e Vendas Aplicações — cada produto pertence a uma"
      >
        <Button onClick={openNew} data-testid="add-categoria-btn"><Plus className="h-4 w-4 mr-2" />Nova categoria</Button>
      </PageHeader>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-32"><div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div></div>
          ) : categorias.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Tag className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="font-medium text-lg">Sem categorias</h3>
              <p className="text-sm text-muted-foreground mt-1">Crie a categoria "Venda ao Público" para começar, ou importe do Vendus.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Nome</TableHead>
                    <TableHead>Ordem</TableHead>
                    <TableHead>Estado</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {categorias.map((categoria) => (
                    <TableRow key={categoria.id} data-testid={`categoria-row-${categoria.id}`}>
                      <TableCell className="font-medium">{categoria.nome}</TableCell>
                      <TableCell className="text-muted-foreground">{categoria.ordem ?? 0}</TableCell>
                      <TableCell>{estadoBadge(categoria.ativa)}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-2">
                          <Button variant="ghost" size="icon" onClick={() => openEdit(categoria)} data-testid={`edit-categoria-${categoria.id}`}>
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="icon" onClick={() => setDeleteTarget(categoria)} data-testid={`delete-categoria-${categoria.id}`}>
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
        <DialogContent data-testid="categoria-dialog">
          <DialogHeader>
            <DialogTitle>{editing ? 'Editar categoria' : 'Nova categoria'}</DialogTitle>
            <DialogDescription>Cada produto pertence a uma só categoria, com o seu próprio preço.</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit}>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="categoria-nome">Nome *</Label>
                <Input
                  id="categoria-nome"
                  value={form.nome}
                  onChange={(e) => { setForm({ ...form, nome: e.target.value }); setFieldErrors((prev) => ({ ...prev, nome: undefined })); }}
                  placeholder="Ex: Venda ao Público"
                  required
                  maxLength={NOME_MAX}
                  aria-invalid={!!fieldErrors.nome}
                  data-testid="categoria-nome-input"
                />
                {fieldErrors.nome && <p className="text-xs text-destructive">{fieldErrors.nome}</p>}
              </div>
              <div className="space-y-2">
                <Label htmlFor="categoria-ordem">Ordem</Label>
                <Input
                  id="categoria-ordem"
                  type="number"
                  value={form.ordem}
                  onChange={(e) => setForm({ ...form, ordem: e.target.value })}
                  data-testid="categoria-ordem-input"
                />
                <p className="text-xs text-muted-foreground">Ordem de aparição no POS. Menor primeiro.</p>
              </div>
              <div className="flex items-center gap-2 pt-1">
                <Switch id="categoria-ativa" checked={form.ativa} onCheckedChange={(v) => setForm({ ...form, ativa: v })} data-testid="categoria-ativa-switch" />
                <Label htmlFor="categoria-ativa" className="cursor-pointer">Categoria ativa</Label>
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>Cancelar</Button>
              <Button type="submit" disabled={saving} data-testid="save-categoria-btn">{saving ? 'A guardar...' : 'Guardar'}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Confirmar eliminação */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar categoria</AlertDialogTitle>
            <AlertDialogDescription>
              Tem a certeza que pretende eliminar "{deleteTarget?.nome}"? Esta ação não pode ser desfeita. Só é possível eliminar categorias sem produtos.
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
