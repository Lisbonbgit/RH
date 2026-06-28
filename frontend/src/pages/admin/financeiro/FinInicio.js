import React, { useState, useEffect } from 'react';
import {
  getFinCompanies, createFinCompany, updateFinCompany, deleteFinCompany,
  getFinUnits, createFinUnit, updateFinUnit, deleteFinUnit,
} from '../../../lib/api';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Badge } from '../../../components/ui/badge';
import { Card, CardContent } from '../../../components/ui/card';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '../../../components/ui/dialog';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '../../../components/ui/alert-dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../../components/ui/table';
import { Wallet, Building2, Store, Users, Plus, Pencil, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import PageHeader from '../../../components/PageHeader';

const ROLE_LABEL = { owner: 'Dono', partner: 'Sócio', accountant: 'Contabilista' };
const canEditCompany = (role) => role === 'owner';
const canEditUnits = (role) => role === 'owner' || role === 'partner';

export default function FinInicio() {
  const [companies, setCompanies] = useState([]);
  const [units, setUnits] = useState([]);
  const [loading, setLoading] = useState(true);

  // Dialog empresa
  const [companyDialog, setCompanyDialog] = useState(false);
  const [selectedCompany, setSelectedCompany] = useState(null);
  const [companyForm, setCompanyForm] = useState({ name: '', nif: '' });
  const [savingCompany, setSavingCompany] = useState(false);
  const [deleteCompanyOpen, setDeleteCompanyOpen] = useState(false);

  // Dialog unidades
  const [unitsDialog, setUnitsDialog] = useState(false);
  const [unitsCompany, setUnitsCompany] = useState(null);
  const [unitForm, setUnitForm] = useState({ name: '', type: '', sort: 0 });
  const [editingUnit, setEditingUnit] = useState(null);
  const [savingUnit, setSavingUnit] = useState(false);
  const [unitToDelete, setUnitToDelete] = useState(null);

  useEffect(() => { fetchAll(); }, []);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [c, u] = await Promise.all([getFinCompanies(), getFinUnits()]);
      setCompanies(c.data);
      setUnits(u.data);
    } catch (error) {
      toast.error('Erro ao carregar dados financeiros');
    } finally {
      setLoading(false);
    }
  };

  const unitsOf = (companyId) => units.filter((u) => u.company_id === companyId);

  // ---- Empresa ----
  const openCompanyDialog = (company = null) => {
    if (company) {
      setSelectedCompany(company);
      setCompanyForm({ name: company.name, nif: company.nif || '' });
    } else {
      setSelectedCompany(null);
      setCompanyForm({ name: '', nif: '' });
    }
    setCompanyDialog(true);
  };

  const submitCompany = async (e) => {
    e.preventDefault();
    setSavingCompany(true);
    try {
      if (selectedCompany) {
        await updateFinCompany(selectedCompany.id, companyForm);
        toast.success('Empresa atualizada');
      } else {
        await createFinCompany(companyForm);
        toast.success('Empresa criada');
      }
      setCompanyDialog(false);
      fetchAll();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao guardar empresa');
    } finally {
      setSavingCompany(false);
    }
  };

  const handleDeleteCompany = async () => {
    try {
      await deleteFinCompany(selectedCompany.id);
      toast.success('Empresa eliminada');
      setDeleteCompanyOpen(false);
      setSelectedCompany(null);
      fetchAll();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao eliminar empresa');
    }
  };

  // ---- Unidades ----
  const openUnitsDialog = (company) => {
    setUnitsCompany(company);
    setEditingUnit(null);
    setUnitForm({ name: '', type: '', sort: 0 });
    setUnitsDialog(true);
  };

  const startEditUnit = (unit) => {
    setEditingUnit(unit);
    setUnitForm({ name: unit.name, type: unit.type || '', sort: unit.sort || 0 });
  };

  const resetUnitForm = () => {
    setEditingUnit(null);
    setUnitForm({ name: '', type: '', sort: 0 });
  };

  const submitUnit = async (e) => {
    e.preventDefault();
    if (!unitsCompany) return;
    setSavingUnit(true);
    try {
      const payload = {
        company_id: unitsCompany.id,
        name: unitForm.name,
        type: unitForm.type || null,
        sort: Number(unitForm.sort) || 0,
      };
      if (editingUnit) {
        await updateFinUnit(editingUnit.id, payload);
        toast.success('Unidade atualizada');
      } else {
        await createFinUnit(payload);
        toast.success('Unidade criada');
      }
      resetUnitForm();
      const u = await getFinUnits();
      setUnits(u.data);
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao guardar unidade');
    } finally {
      setSavingUnit(false);
    }
  };

  const handleDeleteUnit = async () => {
    try {
      await deleteFinUnit(unitToDelete.id);
      toast.success('Unidade eliminada');
      setUnitToDelete(null);
      const u = await getFinUnits();
      setUnits(u.data);
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao eliminar unidade');
    }
  };

  const stats = [
    { label: 'Empresas', value: companies.length, icon: Building2 },
    { label: 'Unidades / Lojas', value: units.length, icon: Store },
    { label: 'Como dono', value: companies.filter((c) => c.role === 'owner').length, icon: Users },
  ];

  return (
    <div className="space-y-6 animate-fade-in" data-testid="fin-inicio-page">
      <PageHeader icon={Wallet} title="Financeiro" subtitle="Empresas, unidades e visão geral do módulo">
        <Button onClick={() => openCompanyDialog()} data-testid="fin-add-company-btn">
          <Plus className="h-4 w-4 mr-2" />
          Nova Empresa
        </Button>
      </PageHeader>

      {/* Resumo */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {stats.map((s) => (
          <Card key={s.label}>
            <CardContent className="flex items-center gap-4 p-5">
              <div className="h-11 w-11 rounded-xl brand-gradient text-white flex items-center justify-center shrink-0">
                <s.icon className="h-5 w-5" />
              </div>
              <div>
                <p className="text-2xl font-heading font-bold leading-none">{s.value}</p>
                <p className="text-sm text-muted-foreground mt-1">{s.label}</p>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Empresas */}
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
              <p className="text-sm text-muted-foreground mt-1">Comece por criar a primeira empresa do Financeiro</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Empresa</TableHead>
                    <TableHead className="hidden sm:table-cell">NIF</TableHead>
                    <TableHead>Unidades</TableHead>
                    <TableHead>Papel</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {companies.map((company) => (
                    <TableRow key={company.id} data-testid={`fin-company-row-${company.id}`}>
                      <TableCell className="font-medium">{company.name}</TableCell>
                      <TableCell className="hidden sm:table-cell text-muted-foreground">
                        {company.nif || '-'}
                      </TableCell>
                      <TableCell>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => openUnitsDialog(company)}
                          data-testid={`fin-units-btn-${company.id}`}
                        >
                          <Store className="h-4 w-4 mr-2" />
                          {unitsOf(company.id).length} · Gerir
                        </Button>
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary">{ROLE_LABEL[company.role] || company.role}</Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        {canEditCompany(company.role) ? (
                          <div className="flex items-center justify-end gap-2">
                            <Button variant="ghost" size="icon" onClick={() => openCompanyDialog(company)}
                              data-testid={`fin-edit-company-${company.id}`}>
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button variant="ghost" size="icon"
                              onClick={() => { setSelectedCompany(company); setDeleteCompanyOpen(true); }}
                              data-testid={`fin-delete-company-${company.id}`}>
                              <Trash2 className="h-4 w-4 text-destructive" />
                            </Button>
                          </div>
                        ) : (
                          <span className="text-xs text-muted-foreground">Só leitura</span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Dialog criar/editar empresa */}
      <Dialog open={companyDialog} onOpenChange={setCompanyDialog}>
        <DialogContent data-testid="fin-company-dialog">
          <DialogHeader>
            <DialogTitle>{selectedCompany ? 'Editar Empresa' : 'Nova Empresa'}</DialogTitle>
            <DialogDescription>
              {selectedCompany ? 'Atualize os dados da empresa' : 'Crie uma empresa do Financeiro (fica como dono)'}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={submitCompany}>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="fin-company-name">Nome da Empresa *</Label>
                <Input id="fin-company-name" value={companyForm.name}
                  onChange={(e) => setCompanyForm({ ...companyForm, name: e.target.value })}
                  placeholder="Ex: Fordaimon Foods" required data-testid="fin-company-name-input" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="fin-company-nif">NIF</Label>
                <Input id="fin-company-nif" value={companyForm.nif}
                  onChange={(e) => setCompanyForm({ ...companyForm, nif: e.target.value })}
                  placeholder="Ex: 517542510" inputMode="numeric" data-testid="fin-company-nif-input" />
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setCompanyDialog(false)}>Cancelar</Button>
              <Button type="submit" disabled={savingCompany} data-testid="fin-save-company-btn">
                {savingCompany ? 'A guardar...' : 'Guardar'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Dialog gerir unidades */}
      <Dialog open={unitsDialog} onOpenChange={setUnitsDialog}>
        <DialogContent data-testid="fin-units-dialog">
          <DialogHeader>
            <DialogTitle>Unidades · {unitsCompany?.name}</DialogTitle>
            <DialogDescription>Lojas e unidades desta empresa</DialogDescription>
          </DialogHeader>

          <div className="space-y-2 max-h-64 overflow-y-auto">
            {unitsCompany && unitsOf(unitsCompany.id).length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">Sem unidades. Adicione a primeira abaixo.</p>
            ) : (
              unitsCompany && unitsOf(unitsCompany.id).map((u) => (
                <div key={u.id} className="flex items-center justify-between rounded-lg border p-3" data-testid={`fin-unit-row-${u.id}`}>
                  <div>
                    <p className="font-medium text-sm">{u.name}</p>
                    {u.type && <p className="text-xs text-muted-foreground">{u.type}</p>}
                  </div>
                  {unitsCompany && canEditUnits(unitsCompany.role) && (
                    <div className="flex items-center gap-1">
                      <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => startEditUnit(u)}
                        data-testid={`fin-edit-unit-${u.id}`}>
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setUnitToDelete(u)}
                        data-testid={`fin-delete-unit-${u.id}`}>
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>

          {unitsCompany && canEditUnits(unitsCompany.role) && (
            <form onSubmit={submitUnit} className="border-t pt-4 space-y-3">
              <p className="text-sm font-medium">{editingUnit ? 'Editar unidade' : 'Nova unidade'}</p>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="sm:col-span-2 space-y-1">
                  <Label htmlFor="fin-unit-name" className="text-xs">Nome *</Label>
                  <Input id="fin-unit-name" value={unitForm.name}
                    onChange={(e) => setUnitForm({ ...unitForm, name: e.target.value })}
                    placeholder="Ex: Loja Belém" required data-testid="fin-unit-name-input" />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="fin-unit-type" className="text-xs">Tipo</Label>
                  <Input id="fin-unit-type" value={unitForm.type}
                    onChange={(e) => setUnitForm({ ...unitForm, type: e.target.value })}
                    placeholder="Loja / Sede" data-testid="fin-unit-type-input" />
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Button type="submit" size="sm" disabled={savingUnit} data-testid="fin-save-unit-btn">
                  {savingUnit ? 'A guardar...' : editingUnit ? 'Atualizar' : 'Adicionar'}
                </Button>
                {editingUnit && (
                  <Button type="button" size="sm" variant="ghost" onClick={resetUnitForm}>Cancelar edição</Button>
                )}
              </div>
            </form>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setUnitsDialog(false)}>Fechar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Confirmar eliminar empresa */}
      <AlertDialog open={deleteCompanyOpen} onOpenChange={setDeleteCompanyOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar Empresa</AlertDialogTitle>
            <AlertDialogDescription>
              Tem a certeza que pretende eliminar "{selectedCompany?.name}"? As unidades e acessos desta empresa
              também serão removidos. Esta ação não pode ser revertida.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleDeleteCompany} className="bg-destructive text-destructive-foreground"
              data-testid="fin-confirm-delete-company-btn">
              Eliminar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Confirmar eliminar unidade */}
      <AlertDialog open={!!unitToDelete} onOpenChange={(o) => !o && setUnitToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar Unidade</AlertDialogTitle>
            <AlertDialogDescription>
              Eliminar a unidade "{unitToDelete?.name}"? Esta ação não pode ser revertida.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleDeleteUnit} className="bg-destructive text-destructive-foreground"
              data-testid="fin-confirm-delete-unit-btn">
              Eliminar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
