import React, { useState, useEffect } from 'react';
import { useOutletContext } from 'react-router-dom';
import { getCompanies, createCompany, updateCompany, deleteCompany } from '../../lib/api';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { Textarea } from '../../components/ui/textarea';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../components/ui/dialog';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '../../components/ui/alert-dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../components/ui/table';
import { Building2, Plus, Pencil, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { format, parseISO } from 'date-fns';

export default function AdminCompanies() {
  const { refreshCompanies } = useOutletContext();
  const [companies, setCompanies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [selectedCompany, setSelectedCompany] = useState(null);
  const [formData, setFormData] = useState({ name: '', description: '' });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchCompanies();
  }, []);

  const fetchCompanies = async () => {
    setLoading(true);
    try {
      const response = await getCompanies();
      setCompanies(response.data);
    } catch (error) {
      toast.error('Erro ao carregar empresas');
    } finally {
      setLoading(false);
    }
  };

  const handleOpenDialog = (company = null) => {
    if (company) {
      setSelectedCompany(company);
      setFormData({ name: company.name, description: company.description || '' });
    } else {
      setSelectedCompany(null);
      setFormData({ name: '', description: '' });
    }
    setDialogOpen(true);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      if (selectedCompany) {
        await updateCompany(selectedCompany.id, formData);
        toast.success('Empresa atualizada com sucesso');
      } else {
        await createCompany(formData);
        toast.success('Empresa criada com sucesso');
      }
      setDialogOpen(false);
      fetchCompanies();
      refreshCompanies();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao guardar empresa');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    try {
      await deleteCompany(selectedCompany.id);
      toast.success('Empresa eliminada com sucesso');
      setDeleteDialogOpen(false);
      setSelectedCompany(null);
      fetchCompanies();
      refreshCompanies();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao eliminar empresa');
    }
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="admin-companies-page">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-heading font-bold">Empresas</h1>
          <p className="text-muted-foreground mt-1">Gerir empresas do grupo</p>
        </div>
        <Button onClick={() => handleOpenDialog()} data-testid="add-company-btn">
          <Plus className="h-4 w-4 mr-2" />
          Nova Empresa
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-32">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
            </div>
          ) : companies.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Building2 className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="font-medium text-lg">Sem empresas</h3>
              <p className="text-sm text-muted-foreground mt-1">Comece por criar a primeira empresa</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Nome</TableHead>
                    <TableHead className="hidden md:table-cell">Descrição</TableHead>
                    <TableHead className="hidden sm:table-cell">Data de Criação</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {companies.map((company) => (
                    <TableRow key={company.id} data-testid={`company-row-${company.id}`}>
                      <TableCell className="font-medium">{company.name}</TableCell>
                      <TableCell className="hidden md:table-cell text-muted-foreground">
                        {company.description || '-'}
                      </TableCell>
                      <TableCell className="hidden sm:table-cell text-muted-foreground">
                        {format(parseISO(company.created_at), 'dd/MM/yyyy')}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-2">
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => handleOpenDialog(company)}
                            data-testid={`edit-company-${company.id}`}
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => {
                              setSelectedCompany(company);
                              setDeleteDialogOpen(true);
                            }}
                            data-testid={`delete-company-${company.id}`}
                          >
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

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent data-testid="company-dialog">
          <DialogHeader>
            <DialogTitle>{selectedCompany ? 'Editar Empresa' : 'Nova Empresa'}</DialogTitle>
            <DialogDescription>
              {selectedCompany ? 'Atualize os dados da empresa' : 'Preencha os dados para criar uma nova empresa'}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit}>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="name">Nome da Empresa *</Label>
                <Input
                  id="name"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder="Ex: Empresa ABC"
                  required
                  data-testid="company-name-input"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="description">Descrição</Label>
                <Textarea
                  id="description"
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  placeholder="Descrição opcional da empresa"
                  rows={3}
                  data-testid="company-description-input"
                />
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>
                Cancelar
              </Button>
              <Button type="submit" disabled={saving} data-testid="save-company-btn">
                {saving ? 'A guardar...' : 'Guardar'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar Empresa</AlertDialogTitle>
            <AlertDialogDescription>
              Tem a certeza que pretende eliminar a empresa "{selectedCompany?.name}"? 
              Esta ação não pode ser revertida.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} className="bg-destructive text-destructive-foreground" data-testid="confirm-delete-btn">
              Eliminar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
