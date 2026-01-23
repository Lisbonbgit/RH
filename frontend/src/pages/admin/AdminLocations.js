import React, { useState, useEffect } from 'react';
import { useOutletContext } from 'react-router-dom';
import { getLocations, createLocation, updateLocation, deleteLocation, getCompanies } from '../../lib/api';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { Card, CardContent } from '../../components/ui/card';
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../components/ui/table';
import { MapPin, Plus, Pencil, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

export default function AdminLocations() {
  const { selectedCompany } = useOutletContext();
  const [locations, setLocations] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [selectedLocation, setSelectedLocation] = useState(null);
  const [formData, setFormData] = useState({ name: '', company_id: '', address: '' });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchData();
  }, [selectedCompany]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [locationsRes, companiesRes] = await Promise.all([
        getLocations(selectedCompany?.id),
        getCompanies()
      ]);
      setLocations(locationsRes.data);
      setCompanies(companiesRes.data);
    } catch (error) {
      toast.error('Erro ao carregar dados');
    } finally {
      setLoading(false);
    }
  };

  const handleOpenDialog = (location = null) => {
    if (location) {
      setSelectedLocation(location);
      setFormData({ 
        name: location.name, 
        company_id: location.company_id, 
        address: location.address || '' 
      });
    } else {
      setSelectedLocation(null);
      setFormData({ 
        name: '', 
        company_id: selectedCompany?.id || '', 
        address: '' 
      });
    }
    setDialogOpen(true);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!formData.company_id) {
      toast.error('Selecione uma empresa');
      return;
    }
    setSaving(true);
    try {
      if (selectedLocation) {
        await updateLocation(selectedLocation.id, formData);
        toast.success('Local atualizado com sucesso');
      } else {
        await createLocation(formData);
        toast.success('Local criado com sucesso');
      }
      setDialogOpen(false);
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao guardar local');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    try {
      await deleteLocation(selectedLocation.id);
      toast.success('Local eliminado com sucesso');
      setDeleteDialogOpen(false);
      setSelectedLocation(null);
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao eliminar local');
    }
  };

  return (
    <div className="space-y-6 animate-fade-in" data-testid="admin-locations-page">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-heading font-bold">Locais</h1>
          <p className="text-muted-foreground mt-1">
            {selectedCompany ? `Locais de ${selectedCompany.name}` : 'Gerir locais/sedes das empresas'}
          </p>
        </div>
        <Button onClick={() => handleOpenDialog()} data-testid="add-location-btn">
          <Plus className="h-4 w-4 mr-2" />
          Novo Local
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-32">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
            </div>
          ) : locations.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <MapPin className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="font-medium text-lg">Sem locais</h3>
              <p className="text-sm text-muted-foreground mt-1">
                {companies.length === 0 
                  ? 'Crie primeiro uma empresa' 
                  : 'Comece por criar o primeiro local'}
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Nome</TableHead>
                    <TableHead>Empresa</TableHead>
                    <TableHead className="hidden md:table-cell">Morada</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {locations.map((location) => (
                    <TableRow key={location.id} data-testid={`location-row-${location.id}`}>
                      <TableCell className="font-medium">{location.name}</TableCell>
                      <TableCell>{location.company_name}</TableCell>
                      <TableCell className="hidden md:table-cell text-muted-foreground">
                        {location.address || '-'}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-2">
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => handleOpenDialog(location)}
                            data-testid={`edit-location-${location.id}`}
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => {
                              setSelectedLocation(location);
                              setDeleteDialogOpen(true);
                            }}
                            data-testid={`delete-location-${location.id}`}
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
        <DialogContent data-testid="location-dialog">
          <DialogHeader>
            <DialogTitle>{selectedLocation ? 'Editar Local' : 'Novo Local'}</DialogTitle>
            <DialogDescription>
              {selectedLocation ? 'Atualize os dados do local' : 'Preencha os dados para criar um novo local'}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit}>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="company">Empresa *</Label>
                <Select
                  value={formData.company_id}
                  onValueChange={(value) => setFormData({ ...formData, company_id: value })}
                >
                  <SelectTrigger data-testid="location-company-select">
                    <SelectValue placeholder="Selecionar empresa" />
                  </SelectTrigger>
                  <SelectContent>
                    {companies.map((company) => (
                      <SelectItem key={company.id} value={company.id}>
                        {company.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="name">Nome do Local *</Label>
                <Input
                  id="name"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder="Ex: Loja Centro, Escritório Principal"
                  required
                  data-testid="location-name-input"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="address">Morada</Label>
                <Input
                  id="address"
                  value={formData.address}
                  onChange={(e) => setFormData({ ...formData, address: e.target.value })}
                  placeholder="Morada do local"
                  data-testid="location-address-input"
                />
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>
                Cancelar
              </Button>
              <Button type="submit" disabled={saving} data-testid="save-location-btn">
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
            <AlertDialogTitle>Eliminar Local</AlertDialogTitle>
            <AlertDialogDescription>
              Tem a certeza que pretende eliminar o local "{selectedLocation?.name}"? 
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
