import React, { useState, useEffect } from 'react';
import { useOutletContext } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { getEmployees, createEmployee, updateEmployee, deleteEmployee, getCompanies, getLocations, createAdminLeave } from '../../lib/api';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { Textarea } from '../../components/ui/textarea';
import { Checkbox } from '../../components/ui/checkbox';
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
import { Users, Plus, Pencil, Trash2, Eye, Search, Calendar } from 'lucide-react';
import { toast } from 'sonner';
import { format, parseISO } from 'date-fns';

const contractTypes = [
  { value: 'efetivo', label: 'Efetivo' },
  { value: 'termo_certo', label: 'Termo Certo' },
  { value: 'termo_incerto', label: 'Termo Incerto' },
  { value: 'temporario', label: 'Temporário' },
  { value: 'estagio', label: 'Estágio' },
];

export default function AdminEmployees() {
  const { selectedCompany } = useOutletContext();
  const { user } = useAuth();
  const isManager = user?.role === 'gerente';
  const [employees, setEmployees] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [viewDialogOpen, setViewDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [selectedEmployee, setSelectedEmployee] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [formData, setFormData] = useState({
    name: '',
    email: '',
    password: '',
    company_id: '',
    location_id: '',
    position: '',
    contract_type: '',
    start_date: '',
    vacation_days: 22,
    observations: '',
    geofence_exempt: false
  });
  const [leaveDialogOpen, setLeaveDialogOpen] = useState(false);
  const [leaveSaving, setLeaveSaving] = useState(false);
  const [leaveFormData, setLeaveFormData] = useState({
    type: 'ferias',
    startDate: '',
    endDate: '',
    reason: '',
    isPaid: true
  });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchData();
  }, [selectedCompany]);

  useEffect(() => {
    if (formData.company_id) {
      fetchLocations(formData.company_id);
    }
  }, [formData.company_id]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [employeesRes, companiesRes] = await Promise.all([
        getEmployees({ company_id: selectedCompany?.id }),
        getCompanies()
      ]);
      setEmployees(employeesRes.data);
      setCompanies(companiesRes.data);
    } catch (error) {
      toast.error('Erro ao carregar dados');
    } finally {
      setLoading(false);
    }
  };

  const fetchLocations = async (companyId) => {
    try {
      const response = await getLocations(companyId);
      setLocations(response.data);
    } catch (error) {
      console.error('Error fetching locations:', error);
    }
  };

  const handleOpenDialog = (employee = null) => {
    if (employee) {
      setSelectedEmployee(employee);
      setFormData({
        name: employee.name,
        email: employee.email,
        password: '',
        company_id: employee.company_id,
        location_id: employee.location_id,
        position: employee.position,
        contract_type: employee.contract_type,
        start_date: employee.start_date,
        vacation_days: employee.vacation_days,
        observations: employee.observations || '',
        geofence_exempt: employee.geofence_exempt === true
      });
      fetchLocations(employee.company_id);
    } else {
      setSelectedEmployee(null);
      setFormData({
        name: '',
        email: '',
        password: '',
        company_id: selectedCompany?.id || '',
        location_id: '',
        position: '',
        contract_type: '',
        start_date: '',
        vacation_days: 22,
        observations: '',
        geofence_exempt: false
      });
      if (selectedCompany?.id) {
        fetchLocations(selectedCompany.id);
      }
    }
    setDialogOpen(true);
  };

  const handleOpenLeaveDialog = (employee) => {
    setSelectedEmployee(employee);
    setLeaveFormData({
      type: 'ferias',
      startDate: '',
      endDate: '',
      reason: '',
      isPaid: true
    });
    setViewDialogOpen(false);
    setLeaveDialogOpen(true);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!formData.company_id) {
      toast.error('Selecione a empresa');
      return;
    }
    setSaving(true);
    try {
      if (selectedEmployee) {
        const updateData = { ...formData };
        delete updateData.password;
        delete updateData.email;
        await updateEmployee(selectedEmployee.id, updateData);
        toast.success('Colaborador atualizado com sucesso');
      } else {
        if (!formData.password) {
          toast.error('Palavra-passe é obrigatória');
          setSaving(false);
          return;
        }
        await createEmployee(formData);
        toast.success('Colaborador criado com sucesso');
      }
      setDialogOpen(false);
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao guardar colaborador');
    } finally {
      setSaving(false);
    }
  };

  const handleSubmitLeave = async (e) => {
    e.preventDefault();
    if (!leaveFormData.startDate || !leaveFormData.endDate) {
      toast.error('Preencha as datas de início e fim');
      return;
    }
    if (leaveFormData.startDate > leaveFormData.endDate) {
      toast.error('Data de início não pode ser posterior à data de fim');
      return;
    }
    if (!selectedEmployee?.id) {
      toast.error('Colaborador não encontrado');
      return;
    }

    setLeaveSaving(true);
    try {
      await createAdminLeave({
        userId: selectedEmployee.id,
        type: leaveFormData.type,
        startDate: leaveFormData.startDate,
        endDate: leaveFormData.endDate,
        reason: leaveFormData.reason,
        isPaid: leaveFormData.isPaid
      });
      toast.success('Férias/Ausência criada com sucesso');
      setLeaveDialogOpen(false);
      setLeaveFormData({
        type: 'ferias',
        startDate: '',
        endDate: '',
        reason: '',
        isPaid: true
      });
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao criar férias/ausência');
    } finally {
      setLeaveSaving(false);
    }
  };

  const handleDelete = async () => {
    try {
      await deleteEmployee(selectedEmployee.id);
      toast.success('Colaborador eliminado com sucesso');
      setDeleteDialogOpen(false);
      setSelectedEmployee(null);
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao eliminar colaborador');
    }
  };

  const filteredEmployees = employees.filter(emp =>
    emp.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    emp.email.toLowerCase().includes(searchTerm.toLowerCase()) ||
    emp.position.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="space-y-6 animate-fade-in" data-testid="admin-employees-page">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-heading font-bold">Colaboradores</h1>
          <p className="text-muted-foreground mt-1">
            {selectedCompany ? `Colaboradores de ${selectedCompany.name}` : 'Gerir colaboradores'}
          </p>
        </div>
        {!isManager && (
          <Button onClick={() => handleOpenDialog()} data-testid="add-employee-btn">
            <Plus className="h-4 w-4 mr-2" />
            Novo Colaborador
          </Button>
        )}
      </div>

      {/* Search */}
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Pesquisar colaboradores..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="pl-10"
          data-testid="search-employees-input"
        />
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-32">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
            </div>
          ) : filteredEmployees.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Users className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="font-medium text-lg">Sem colaboradores</h3>
              <p className="text-sm text-muted-foreground mt-1">
                {companies.length === 0 
                  ? 'Crie primeiro uma empresa e um local' 
                  : 'Comece por adicionar colaboradores'}
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Nome</TableHead>
                    <TableHead className="hidden sm:table-cell">Cargo</TableHead>
                    <TableHead className="hidden md:table-cell">Empresa</TableHead>
                    <TableHead className="hidden lg:table-cell">Local</TableHead>
                    <TableHead className="hidden xl:table-cell">Contrato</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredEmployees.map((employee) => (
                    <TableRow key={employee.id} data-testid={`employee-row-${employee.id}`}>
                      <TableCell>
                        <div>
                          <p className="font-medium">{employee.name}</p>
                          <p className="text-xs text-muted-foreground">{employee.email}</p>
                        </div>
                      </TableCell>
                      <TableCell className="hidden sm:table-cell">{employee.position}</TableCell>
                      <TableCell className="hidden md:table-cell">{employee.company_name}</TableCell>
                      <TableCell className="hidden lg:table-cell">{employee.location_name}</TableCell>
                      <TableCell className="hidden xl:table-cell">
                        <Badge variant="secondary">
                          {contractTypes.find(c => c.value === employee.contract_type)?.label || employee.contract_type}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => {
                              setSelectedEmployee(employee);
                              setViewDialogOpen(true);
                            }}
                            data-testid={`view-employee-${employee.id}`}
                          >
                            <Eye className="h-4 w-4" />
                          </Button>
                          {!isManager && (
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleOpenDialog(employee)}
                              data-testid={`edit-employee-${employee.id}`}
                            >
                              <Pencil className="h-4 w-4" />
                            </Button>
                          )}
                          {!isManager && (
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => {
                                setSelectedEmployee(employee);
                                setDeleteDialogOpen(true);
                              }}
                              data-testid={`delete-employee-${employee.id}`}
                            >
                              <Trash2 className="h-4 w-4 text-destructive" />
                            </Button>
                          )}
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
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto" data-testid="employee-dialog">
          <DialogHeader>
            <DialogTitle>{selectedEmployee ? 'Editar Colaborador' : 'Novo Colaborador'}</DialogTitle>
            <DialogDescription>
              {selectedEmployee ? 'Atualize os dados do colaborador' : 'Preencha os dados para criar um novo colaborador'}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit}>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="name">Nome Completo *</Label>
                <Input
                  id="name"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder="Nome do colaborador"
                  required
                  data-testid="employee-name-input"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="email">Email *</Label>
                <Input
                  id="email"
                  type="email"
                  value={formData.email}
                  onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                  placeholder="email@exemplo.com"
                  required
                  disabled={!!selectedEmployee}
                  data-testid="employee-email-input"
                />
              </div>
              {!selectedEmployee && (
                <div className="space-y-2">
                  <Label htmlFor="password">Palavra-passe *</Label>
                  <Input
                    id="password"
                    type="password"
                    value={formData.password}
                    onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                    placeholder="Palavra-passe inicial"
                    required
                    data-testid="employee-password-input"
                  />
                </div>
              )}
              <div className="space-y-2">
                <Label htmlFor="company">Empresa *</Label>
                <Select
                  value={formData.company_id}
                  onValueChange={(value) => {
                    setFormData({ ...formData, company_id: value, location_id: '' });
                    fetchLocations(value);
                  }}
                >
                  <SelectTrigger data-testid="employee-company-select">
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
                <Label htmlFor="location">Local (opcional)</Label>
                <Select
                  value={formData.location_id || '__none__'}
                  onValueChange={(value) => setFormData({ ...formData, location_id: value === '__none__' ? '' : value })}
                  disabled={!formData.company_id}
                >
                  <SelectTrigger data-testid="employee-location-select">
                    <SelectValue placeholder="Selecionar local" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">Sem local (trabalha em vários / remoto)</SelectItem>
                    {locations.map((location) => (
                      <SelectItem key={location.id} value={location.id}>
                        {location.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="position">Cargo *</Label>
                <Input
                  id="position"
                  value={formData.position}
                  onChange={(e) => setFormData({ ...formData, position: e.target.value })}
                  placeholder="Ex: Assistente Administrativo"
                  required
                  data-testid="employee-position-input"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="contract_type">Tipo de Contrato *</Label>
                <Select
                  value={formData.contract_type}
                  onValueChange={(value) => setFormData({ ...formData, contract_type: value })}
                >
                  <SelectTrigger data-testid="employee-contract-select">
                    <SelectValue placeholder="Selecionar tipo" />
                  </SelectTrigger>
                  <SelectContent>
                    {contractTypes.map((type) => (
                      <SelectItem key={type.value} value={type.value}>
                        {type.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="start_date">Data de Entrada *</Label>
                <Input
                  id="start_date"
                  type="date"
                  value={formData.start_date}
                  onChange={(e) => setFormData({ ...formData, start_date: e.target.value })}
                  required
                  data-testid="employee-start-date-input"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="vacation_days">Dias de Férias</Label>
                <Input
                  id="vacation_days"
                  type="number"
                  min="0"
                  value={formData.vacation_days}
                  onChange={(e) => setFormData({ ...formData, vacation_days: parseInt(e.target.value) || 0 })}
                  data-testid="employee-vacation-days-input"
                />
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label htmlFor="observations">Observações</Label>
                <Textarea
                  id="observations"
                  value={formData.observations}
                  onChange={(e) => setFormData({ ...formData, observations: e.target.value })}
                  placeholder="Observações adicionais"
                  rows={3}
                  data-testid="employee-observations-input"
                />
              </div>
              <div className="md:col-span-2 rounded-lg border p-3 bg-muted/30">
                <label className="flex items-start gap-2 text-sm cursor-pointer">
                  <Checkbox
                    checked={formData.geofence_exempt === true}
                    onCheckedChange={(checked) => setFormData({ ...formData, geofence_exempt: checked === true })}
                    data-testid="employee-geofence-exempt-checkbox"
                    className="mt-0.5"
                  />
                  <span>
                    <span className="font-medium">Trabalha em vários locais (isento de cerca geográfica)</span>
                    <br />
                    <span className="text-xs text-muted-foreground">
                      Se ativado, este colaborador pode registar ponto de qualquer lugar — a cerca
                      geográfica do local não é aplicada (a localização continua a ser registada).
                    </span>
                  </span>
                </label>
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>
                Cancelar
              </Button>
              <Button type="submit" disabled={saving} data-testid="save-employee-btn">
                {saving ? 'A guardar...' : 'Guardar'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* View Dialog */}
      <Dialog open={viewDialogOpen} onOpenChange={setViewDialogOpen}>
        <DialogContent className="max-w-lg" data-testid="view-employee-dialog">
          <DialogHeader>
            <DialogTitle>Detalhes do Colaborador</DialogTitle>
          </DialogHeader>
          {selectedEmployee && (
            <div className="space-y-4 py-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-sm text-muted-foreground">Nome</p>
                  <p className="font-medium">{selectedEmployee.name}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Email</p>
                  <p className="font-medium">{selectedEmployee.email}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Empresa</p>
                  <p className="font-medium">{selectedEmployee.company_name}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Local</p>
                  <p className="font-medium">{selectedEmployee.location_name}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Cargo</p>
                  <p className="font-medium">{selectedEmployee.position}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Tipo de Contrato</p>
                  <p className="font-medium">
                    {contractTypes.find(c => c.value === selectedEmployee.contract_type)?.label || selectedEmployee.contract_type}
                  </p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Data de Entrada</p>
                  <p className="font-medium">{format(parseISO(selectedEmployee.start_date), 'dd/MM/yyyy')}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Dias de Férias</p>
                  <p className="font-medium">{selectedEmployee.vacation_days} dias</p>
                </div>
              </div>
              {selectedEmployee.observations && (
                <div>
                  <p className="text-sm text-muted-foreground">Observações</p>
                  <p className="font-medium">{selectedEmployee.observations}</p>
                </div>
              )}
              <div className="pt-2">
                <Button
                  type="button"
                  onClick={() => handleOpenLeaveDialog(selectedEmployee)}
                  data-testid="add-admin-leave-btn"
                >
                  <Calendar className="h-4 w-4 mr-2" />
                  Adicionar Férias / Ausência
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Admin Leave Dialog */}
      <Dialog open={leaveDialogOpen} onOpenChange={setLeaveDialogOpen}>
        <DialogContent className="max-w-lg" data-testid="admin-leave-dialog">
          <DialogHeader>
            <DialogTitle>Adicionar Férias / Ausência</DialogTitle>
            <DialogDescription>
              {selectedEmployee ? `Registar férias ou ausência para ${selectedEmployee.name}` : 'Registar férias ou ausência'}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmitLeave}>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label data-testid="admin-leave-type-label">Tipo</Label>
                <Select
                  value={leaveFormData.type}
                  onValueChange={(value) => setLeaveFormData({ ...leaveFormData, type: value })}
                >
                  <SelectTrigger data-testid="admin-leave-type-select">
                    <SelectValue placeholder="Selecionar tipo" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ferias">Férias</SelectItem>
                    <SelectItem value="ausencia">Ausência</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="leave-start" data-testid="admin-leave-start-label">Data Início</Label>
                  <Input
                    id="leave-start"
                    type="date"
                    value={leaveFormData.startDate}
                    onChange={(e) => setLeaveFormData({ ...leaveFormData, startDate: e.target.value })}
                    required
                    data-testid="admin-leave-start-input"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="leave-end" data-testid="admin-leave-end-label">Data Fim</Label>
                  <Input
                    id="leave-end"
                    type="date"
                    value={leaveFormData.endDate}
                    onChange={(e) => setLeaveFormData({ ...leaveFormData, endDate: e.target.value })}
                    required
                    data-testid="admin-leave-end-input"
                  />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="leave-reason" data-testid="admin-leave-reason-label">Motivo (opcional)</Label>
                <Textarea
                  id="leave-reason"
                  value={leaveFormData.reason}
                  onChange={(e) => setLeaveFormData({ ...leaveFormData, reason: e.target.value })}
                  placeholder="Motivo da ausência ou férias"
                  rows={3}
                  data-testid="admin-leave-reason-input"
                />
              </div>
              <div className="flex items-center gap-2" data-testid="admin-leave-paid-field">
                <Checkbox
                  id="leave-paid"
                  checked={leaveFormData.isPaid}
                  onCheckedChange={(checked) => setLeaveFormData({ ...leaveFormData, isPaid: checked === true })}
                  data-testid="admin-leave-paid-checkbox"
                />
                <Label htmlFor="leave-paid" className="cursor-pointer" data-testid="admin-leave-paid-label">Remunerado</Label>
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setLeaveDialogOpen(false)} data-testid="admin-leave-cancel-btn">
                Cancelar
              </Button>
              <Button type="submit" disabled={leaveSaving} data-testid="admin-leave-save-btn">
                {leaveSaving ? 'A guardar...' : 'Guardar'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar Colaborador</AlertDialogTitle>
            <AlertDialogDescription>
              Tem a certeza que pretende eliminar o colaborador "{selectedEmployee?.name}"? 
              Todos os dados associados (ponto, férias, documentos) serão eliminados. Esta ação não pode ser revertida.
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
