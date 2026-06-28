import React, { useState, useEffect } from 'react';
import { useOutletContext } from 'react-router-dom';
import { getLocations, createLocation, updateLocation, deleteLocation, getCompanies, findPlace } from '../../lib/api';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { Card, CardContent } from '../../components/ui/card';
import { Badge } from '../../components/ui/badge';
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
import { MapPin, Plus, Pencil, Trash2, LocateFixed, Loader2, Star, Search } from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import { toast } from 'sonner';

const emptyForm = { name: '', company_id: '', address: '', latitude: '', longitude: '', geofence_radius: '', google_place_id: '' };

export default function AdminLocations() {
  const { selectedCompany } = useOutletContext();
  const [locations, setLocations] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [selectedLocation, setSelectedLocation] = useState(null);
  const [formData, setFormData] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [locating, setLocating] = useState(false);
  const [placeQuery, setPlaceQuery] = useState('');
  const [placeResults, setPlaceResults] = useState(null);
  const [searchingPlace, setSearchingPlace] = useState(false);

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
        address: location.address || '',
        latitude: location.latitude ?? '',
        longitude: location.longitude ?? '',
        geofence_radius: location.geofence_radius ?? '',
        google_place_id: location.google_place_id || '',
      });
    } else {
      setSelectedLocation(null);
      setFormData({ ...emptyForm, company_id: selectedCompany?.id || '' });
    }
    setPlaceQuery('');
    setPlaceResults(null);
    setDialogOpen(true);
  };

  const handleSearchPlace = async () => {
    const q = placeQuery.trim() || formData.name + ' ' + (formData.address || '');
    if (!q.trim()) {
      toast.error('Escreva o nome/morada da loja para procurar');
      return;
    }
    setSearchingPlace(true);
    setPlaceResults(null);
    try {
      const res = await findPlace(q.trim());
      setPlaceResults(res.data.candidates || []);
      if (!res.data.candidates?.length) toast.info('Nenhum local encontrado na Google');
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao procurar na Google');
    } finally {
      setSearchingPlace(false);
    }
  };

  const handleGetCurrentLocation = () => {
    if (!('geolocation' in navigator)) {
      toast.error('O navegador não suporta geolocalização');
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setFormData((prev) => ({
          ...prev,
          latitude: pos.coords.latitude.toFixed(6),
          longitude: pos.coords.longitude.toFixed(6),
        }));
        setLocating(false);
        toast.success('Localização apanhada! Confirme o raio e guarde.');
      },
      () => {
        setLocating(false);
        toast.error('Não foi possível obter a localização (permissão negada?)');
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
    );
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!formData.company_id) {
      toast.error('Selecione uma empresa');
      return;
    }
    const payload = {
      name: formData.name,
      company_id: formData.company_id,
      address: formData.address || null,
      latitude: formData.latitude === '' ? null : parseFloat(formData.latitude),
      longitude: formData.longitude === '' ? null : parseFloat(formData.longitude),
      geofence_radius: formData.geofence_radius === '' ? null : parseInt(formData.geofence_radius, 10),
      google_place_id: formData.google_place_id.trim() || null,
    };
    setSaving(true);
    try {
      if (selectedLocation) {
        await updateLocation(selectedLocation.id, payload);
        toast.success('Local atualizado com sucesso');
      } else {
        await createLocation(payload);
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
      <PageHeader
        icon={MapPin}
        title="Locais"
        subtitle={selectedCompany ? `Locais de ${selectedCompany.name}` : 'Gerir locais/sedes das empresas'}
      >
        <Button onClick={() => handleOpenDialog()} data-testid="add-location-btn">
          <Plus className="h-4 w-4 mr-2" />
          Novo Local
        </Button>
      </PageHeader>

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
                    <TableHead className="hidden sm:table-cell">Cerca</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {locations.map((location) => (
                    <TableRow key={location.id} data-testid={`location-row-${location.id}`}>
                      <TableCell className="font-medium">
                        <span className="inline-flex items-center gap-1.5">
                          {location.name}
                          {location.google_place_id && (
                            <Star className="h-3.5 w-3.5 fill-amber-400 text-amber-400" title="Ligada ao Google (avaliações)" />
                          )}
                        </span>
                      </TableCell>
                      <TableCell>{location.company_name}</TableCell>
                      <TableCell className="hidden md:table-cell text-muted-foreground">
                        {location.address || '-'}
                      </TableCell>
                      <TableCell className="hidden sm:table-cell">
                        {location.geofence_radius && location.latitude != null ? (
                          <Badge variant="outline" className="text-green-600 border-green-300 gap-1">
                            <MapPin className="h-3 w-3" /> {location.geofence_radius} m
                          </Badge>
                        ) : (
                          <span className="text-xs text-muted-foreground">Desligada</span>
                        )}
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
        <DialogContent data-testid="location-dialog" className="max-h-[90vh] overflow-y-auto">
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

              {/* Cerca geográfica */}
              <div className="rounded-lg border p-3 space-y-3 bg-muted/30">
                <div className="flex items-center gap-2">
                  <MapPin className="h-4 w-4 text-primary" />
                  <span className="font-medium text-sm">Cerca geográfica (opcional)</span>
                </div>
                <p className="text-xs text-muted-foreground">
                  Defina a posição do local e um raio para só permitir o registo de ponto perto dele.
                  Deixe o raio vazio para não restringir (só regista a localização).
                  <br />
                  💡 Estando no próprio local, use o botão abaixo para apanhar a posição.
                </p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handleGetCurrentLocation}
                  disabled={locating}
                  data-testid="get-location-btn"
                >
                  {locating ? (
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  ) : (
                    <LocateFixed className="h-4 w-4 mr-2" />
                  )}
                  Apanhar a minha localização atual
                </Button>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <Label htmlFor="latitude" className="text-xs">Latitude</Label>
                    <Input
                      id="latitude"
                      value={formData.latitude}
                      onChange={(e) => setFormData({ ...formData, latitude: e.target.value })}
                      placeholder="38.7223"
                      data-testid="location-latitude-input"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="longitude" className="text-xs">Longitude</Label>
                    <Input
                      id="longitude"
                      value={formData.longitude}
                      onChange={(e) => setFormData({ ...formData, longitude: e.target.value })}
                      placeholder="-9.1393"
                      data-testid="location-longitude-input"
                    />
                  </div>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="radius" className="text-xs">Raio permitido (metros)</Label>
                  <Input
                    id="radius"
                    type="number"
                    min="10"
                    value={formData.geofence_radius}
                    onChange={(e) => setFormData({ ...formData, geofence_radius: e.target.value })}
                    placeholder="Ex: 200 (vazio = sem restrição)"
                    data-testid="location-radius-input"
                  />
                </div>
                {formData.latitude !== '' && formData.longitude !== '' && (
                  <a
                    href={`https://www.google.com/maps?q=${formData.latitude},${formData.longitude}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                  >
                    <MapPin className="h-3 w-3" /> Ver esta posição no mapa
                  </a>
                )}
              </div>

              {/* Avaliações Google */}
              <div className="rounded-lg border p-3 space-y-3 bg-muted/30">
                <div className="flex items-center gap-2">
                  <Star className="h-4 w-4 text-amber-500" />
                  <span className="font-medium text-sm">Avaliações Google (opcional)</span>
                </div>
                <p className="text-xs text-muted-foreground">
                  Associe esta loja ao seu local no Google para mostrar as avaliações
                  em <strong>Marketing → Avaliações</strong>. Procure pelo nome e clique em "Usar".
                </p>
                <div className="flex gap-2">
                  <Input
                    value={placeQuery}
                    onChange={(e) => setPlaceQuery(e.target.value)}
                    placeholder={`Procurar na Google (ex: ${formData.name || 'nome da loja'})`}
                    onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleSearchPlace(); } }}
                    data-testid="place-search-input"
                  />
                  <Button type="button" variant="outline" size="sm" onClick={handleSearchPlace} disabled={searchingPlace}>
                    {searchingPlace ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                  </Button>
                </div>
                {placeResults && placeResults.length > 0 && (
                  <div className="space-y-2">
                    {placeResults.map((c) => (
                      <div key={c.place_id} className="flex items-center justify-between gap-2 rounded-md border bg-card p-2">
                        <div className="min-w-0">
                          <p className="text-sm font-medium truncate">{c.name}</p>
                          <p className="text-xs text-muted-foreground truncate">{c.address}</p>
                          {c.rating != null && (
                            <span className="inline-flex items-center gap-1 text-xs text-amber-600">
                              <Star className="h-3 w-3 fill-amber-500 text-amber-500" /> {c.rating} ({c.total})
                            </span>
                          )}
                        </div>
                        <Button
                          type="button"
                          size="sm"
                          variant={formData.google_place_id === c.place_id ? 'default' : 'outline'}
                          onClick={() => {
                            setFormData({ ...formData, google_place_id: c.place_id });
                            setPlaceResults(null);
                            toast.success('Loja associada à Google');
                          }}
                        >
                          {formData.google_place_id === c.place_id ? 'Selecionada' : 'Usar'}
                        </Button>
                      </div>
                    ))}
                  </div>
                )}
                <div className="space-y-1">
                  <Label htmlFor="place_id" className="text-xs">Google Place ID</Label>
                  <Input
                    id="place_id"
                    value={formData.google_place_id}
                    onChange={(e) => setFormData({ ...formData, google_place_id: e.target.value })}
                    placeholder="Ex: ChIJ... (preenchido pela procura ou colado à mão)"
                    data-testid="location-placeid-input"
                  />
                </div>
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
