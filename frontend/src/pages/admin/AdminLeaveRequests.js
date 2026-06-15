import React, { useState, useEffect } from 'react';
import { useOutletContext } from 'react-router-dom';
import { getLeaveRequests, respondLeaveRequest, getEmployees, updateLeaveRequest } from '../../lib/api';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { Textarea } from '../../components/ui/textarea';
import { Card, CardContent } from '../../components/ui/card';
import { ScrollArea } from '../../components/ui/scroll-area';
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../components/ui/table';
import { Calendar, Check, X, Filter, Eye, Pencil, Download } from 'lucide-react';
import { toast } from 'sonner';
import { format, parseISO, differenceInDays } from 'date-fns';
import { downloadCSV } from '../../lib/export';

const leaveTypeLabels = {
  ferias: 'Férias',
  falta: 'Falta',
  doenca: 'Doença',
  folga: 'Folga',
  ausencia: 'Ausência'
};

const statusLabels = {
  pendente: 'Pendente',
  aprovado: 'Aprovado',
  recusado: 'Recusado'
};

const auditActionLabels = {
  criado: 'Pedido criado',
  criado_manual: 'Criado manualmente',
  editado: 'Editado',
  aprovado: 'Aprovado',
  recusado: 'Recusado'
};

const roleLabels = {
  admin: 'Admin',
  gerente: 'Gestor',
  colaborador: 'Colaborador'
};

export default function AdminLeaveRequests() {
  const { selectedCompany } = useOutletContext();
  const [requests, setRequests] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(true);
  const [responseDialogOpen, setResponseDialogOpen] = useState(false);
  const [viewDialogOpen, setViewDialogOpen] = useState(false);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [selectedRequest, setSelectedRequest] = useState(null);
  const [responseAction, setResponseAction] = useState('');
  const [responseText, setResponseText] = useState('');
  const [editFormData, setEditFormData] = useState({
    startDate: '',
    endDate: '',
    observation: ''
  });
  const [filters, setFilters] = useState({
    employee_id: '',
    status: ''
  });
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    fetchData();
  }, [selectedCompany, filters]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const params = {
        company_id: selectedCompany?.id,
        ...filters
      };
      Object.keys(params).forEach(key => !params[key] && delete params[key]);
      
      const [requestsRes, employeesRes] = await Promise.all([
        getLeaveRequests(params),
        getEmployees({ company_id: selectedCompany?.id })
      ]);
      setRequests(requestsRes.data);
      setEmployees(employeesRes.data);
    } catch (error) {
      toast.error('Erro ao carregar dados');
    } finally {
      setLoading(false);
    }
  };

  const handleOpenResponse = (request, action) => {
    setSelectedRequest(request);
    setResponseAction(action);
    setResponseText('');
    setResponseDialogOpen(true);
  };

  const handleOpenEdit = (request) => {
    setSelectedRequest(request);
    setEditFormData({
      startDate: request.start_date,
      endDate: request.end_date,
      observation: request.observation || ''
    });
    setEditDialogOpen(true);
  };

  const handleSubmitEdit = async () => {
    if (!editFormData.startDate || !editFormData.endDate) {
      toast.error('Preencha as datas de início e fim');
      return;
    }
    if (editFormData.startDate > editFormData.endDate) {
      toast.error('Data de início não pode ser posterior à data de fim');
      return;
    }

    setEditing(true);
    try {
      await updateLeaveRequest(selectedRequest.id, {
        startDate: editFormData.startDate,
        endDate: editFormData.endDate,
        observation: editFormData.observation
      });
      toast.success('Pedido atualizado com sucesso');
      setEditDialogOpen(false);
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao atualizar pedido');
    } finally {
      setEditing(false);
    }
  };

  const handleSubmitResponse = async () => {
    setSaving(true);
    try {
      await respondLeaveRequest(selectedRequest.id, responseAction, responseText);
      toast.success(`Pedido ${responseAction === 'aprovado' ? 'aprovado' : 'recusado'} com sucesso`);
      setResponseDialogOpen(false);
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Erro ao responder pedido');
    } finally {
      setSaving(false);
    }
  };

  const clearFilters = () => {
    setFilters({ employee_id: '', status: '' });
  };

  const handleExport = () => {
    if (requests.length === 0) {
      toast.error('Sem pedidos para exportar');
      return;
    }
    const headers = ['Colaborador', 'Tipo', 'Início', 'Fim', 'Dias', 'Estado', 'Observação'];
    const rows = requests.map((r) => [
      r.employee_name,
      leaveTypeLabels[r.leave_type] || r.leave_type,
      format(parseISO(r.start_date), 'dd/MM/yyyy'),
      format(parseISO(r.end_date), 'dd/MM/yyyy'),
      r.counted_days ?? (differenceInDays(parseISO(r.end_date), parseISO(r.start_date)) + 1),
      statusLabels[r.status] || r.status,
      r.observation || '',
    ]);
    const suffix = selectedCompany?.name ? `-${selectedCompany.name}` : '';
    downloadCSV(`ferias${suffix}.csv`, headers, rows);
    toast.success('Pedidos exportados');
  };

  const getDuration = (request) => {
    const days = request?.counted_days ?? (differenceInDays(parseISO(request.end_date), parseISO(request.start_date)) + 1);
    return `${days} dia${days > 1 ? 's' : ''}`;
  };

  const isManagerCreated = (request) => request?.created_by && request.created_by !== 'colaborador';

  return (
    <div className="space-y-6 animate-fade-in" data-testid="admin-leave-requests-page">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl md:text-3xl font-heading font-bold">Férias e Ausências</h1>
          <p className="text-muted-foreground mt-1">
            {selectedCompany ? `Pedidos de ${selectedCompany.name}` : 'Gerir pedidos de férias e ausências'}
          </p>
        </div>
        <Button variant="outline" onClick={handleExport} data-testid="export-leaves-btn">
          <Download className="h-4 w-4 mr-2" />
          Exportar CSV
        </Button>
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-2 mb-4">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <span className="font-medium text-sm">Filtros</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label>Colaborador</Label>
              <Select
                value={filters.employee_id || '__all__'}
                onValueChange={(value) => setFilters({ ...filters, employee_id: value === '__all__' ? '' : value })}
              >
                <SelectTrigger data-testid="filter-employee-select">
                  <SelectValue placeholder="Todos" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">Todos</SelectItem>
                  {employees.map((emp) => (
                    <SelectItem key={emp.id} value={emp.id}>
                      {emp.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Estado</Label>
              <Select
                value={filters.status || '__all__'}
                onValueChange={(value) => setFilters({ ...filters, status: value === '__all__' ? '' : value })}
              >
                <SelectTrigger data-testid="filter-status-select">
                  <SelectValue placeholder="Todos" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">Todos</SelectItem>
                  <SelectItem value="pendente">Pendente</SelectItem>
                  <SelectItem value="aprovado">Aprovado</SelectItem>
                  <SelectItem value="recusado">Recusado</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-end">
              <Button variant="outline" onClick={clearFilters} className="w-full" data-testid="clear-filters-btn">
                Limpar Filtros
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Requests Table */}
      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-32">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
            </div>
          ) : requests.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Calendar className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="font-medium text-lg">Sem pedidos</h3>
              <p className="text-sm text-muted-foreground mt-1">Nenhum pedido de ausência encontrado</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Colaborador</TableHead>
                    <TableHead>Tipo</TableHead>
                    <TableHead className="hidden sm:table-cell">Período</TableHead>
                    <TableHead className="hidden md:table-cell">Duração</TableHead>
                    <TableHead>Estado</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {requests.map((request) => (
                    <TableRow key={request.id} data-testid={`request-row-${request.id}`}>
                      <TableCell className="font-medium">{request.employee_name}</TableCell>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant="outline" data-testid={`leave-type-${request.id}`}>
                            {leaveTypeLabels[request.leave_type]}
                          </Badge>
                          {isManagerCreated(request) && (
                            <Badge variant="secondary" data-testid={`leave-created-by-${request.id}`}>
                              Criado pelo gestor
                            </Badge>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="hidden sm:table-cell">
                        {format(parseISO(request.start_date), 'dd/MM/yyyy')} - {format(parseISO(request.end_date), 'dd/MM/yyyy')}
                      </TableCell>
                      <TableCell className="hidden md:table-cell">
                        {getDuration(request)}
                      </TableCell>
                      <TableCell>
                        <Badge className={`badge-${request.status}`}>
                          {statusLabels[request.status]}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => {
                              setSelectedRequest(request);
                              setViewDialogOpen(true);
                            }}
                            data-testid={`view-request-${request.id}`}
                          >
                            <Eye className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => handleOpenEdit(request)}
                            data-testid={`edit-request-${request.id}`}
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                          {request.status === 'pendente' && (
                            <>
                              <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => handleOpenResponse(request, 'aprovado')}
                                data-testid={`approve-request-${request.id}`}
                              >
                                <Check className="h-4 w-4 text-green-600" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => handleOpenResponse(request, 'recusado')}
                                data-testid={`reject-request-${request.id}`}
                              >
                                <X className="h-4 w-4 text-red-600" />
                              </Button>
                            </>
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

      {/* Response Dialog */}
      <Dialog open={responseDialogOpen} onOpenChange={setResponseDialogOpen}>
        <DialogContent data-testid="response-dialog">
          <DialogHeader>
            <DialogTitle>
              {responseAction === 'aprovado' ? 'Aprovar Pedido' : 'Recusar Pedido'}
            </DialogTitle>
            <DialogDescription>
              {responseAction === 'aprovado' 
                ? `Confirmar aprovação do pedido de ${selectedRequest?.employee_name}`
                : `Recusar o pedido de ${selectedRequest?.employee_name}`}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="p-3 bg-muted rounded-lg space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Tipo:</span>
                <span>{selectedRequest && leaveTypeLabels[selectedRequest.leave_type]}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Período:</span>
                <span>
                  {selectedRequest && format(parseISO(selectedRequest.start_date), 'dd/MM/yyyy')} - {selectedRequest && format(parseISO(selectedRequest.end_date), 'dd/MM/yyyy')}
                </span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Duração:</span>
                <span>{selectedRequest && getDuration(selectedRequest)}</span>
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="response">Resposta (opcional)</Label>
              <Textarea
                id="response"
                value={responseText}
                onChange={(e) => setResponseText(e.target.value)}
                placeholder="Adicione uma nota ou justificação"
                rows={3}
                data-testid="response-text-input"
              />
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setResponseDialogOpen(false)}>
              Cancelar
            </Button>
            <Button 
              onClick={handleSubmitResponse} 
              disabled={saving}
              variant={responseAction === 'aprovado' ? 'default' : 'destructive'}
              data-testid="submit-response-btn"
            >
              {saving ? 'A processar...' : (responseAction === 'aprovado' ? 'Aprovar' : 'Recusar')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Dialog */}
      <Dialog open={editDialogOpen} onOpenChange={setEditDialogOpen}>
        <DialogContent data-testid="edit-request-dialog">
          <DialogHeader>
            <DialogTitle>Editar Pedido</DialogTitle>
            <DialogDescription>
              Ajuste datas ou motivo do pedido selecionado.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="edit-start" data-testid="edit-start-label">Data Início</Label>
                <Input
                  id="edit-start"
                  type="date"
                  value={editFormData.startDate}
                  onChange={(e) => setEditFormData({ ...editFormData, startDate: e.target.value })}
                  data-testid="edit-start-input"
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="edit-end" data-testid="edit-end-label">Data Fim</Label>
                <Input
                  id="edit-end"
                  type="date"
                  value={editFormData.endDate}
                  onChange={(e) => setEditFormData({ ...editFormData, endDate: e.target.value })}
                  data-testid="edit-end-input"
                  required
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-observation" data-testid="edit-observation-label">Motivo/Observação</Label>
              <Textarea
                id="edit-observation"
                value={editFormData.observation}
                onChange={(e) => setEditFormData({ ...editFormData, observation: e.target.value })}
                placeholder="Atualize o motivo ou observação"
                rows={3}
                data-testid="edit-observation-input"
              />
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setEditDialogOpen(false)} data-testid="edit-cancel-btn">
              Cancelar
            </Button>
            <Button onClick={handleSubmitEdit} disabled={editing} data-testid="edit-save-btn">
              {editing ? 'A guardar...' : 'Guardar Alterações'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* View Dialog */}
      <Dialog open={viewDialogOpen} onOpenChange={setViewDialogOpen}>
        <DialogContent data-testid="view-request-dialog">
          <DialogHeader>
            <DialogTitle>Detalhes do Pedido</DialogTitle>
          </DialogHeader>
          {selectedRequest && (
            <div className="space-y-4 py-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-sm text-muted-foreground">Colaborador</p>
                  <p className="font-medium">{selectedRequest.employee_name}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Tipo</p>
                  <p className="font-medium">{leaveTypeLabels[selectedRequest.leave_type]}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Data Início</p>
                  <p className="font-medium">{format(parseISO(selectedRequest.start_date), 'dd/MM/yyyy')}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Data Fim</p>
                  <p className="font-medium">{format(parseISO(selectedRequest.end_date), 'dd/MM/yyyy')}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Duração</p>
                  <p className="font-medium">{getDuration(selectedRequest)}</p>
                </div>
                {selectedRequest?.counted_days !== undefined && (
                  <div>
                    <p className="text-sm text-muted-foreground">Dias contabilizados</p>
                    <p className="font-medium" data-testid="view-request-counted-days">
                      {selectedRequest.counted_days} dia{selectedRequest.counted_days > 1 ? 's' : ''}
                    </p>
                  </div>
                )}
                {selectedRequest?.audit_log?.length > 0 && (
                  <div className="col-span-2">
                    <p className="text-sm text-muted-foreground">Histórico de Alterações</p>
                    <ScrollArea className="max-h-40 mt-2 border rounded-md" data-testid="view-request-audit-log">
                      <div className="space-y-2 p-3">
                        {selectedRequest.audit_log.map((entry, index) => (
                          <div key={`${entry.timestamp}-${index}`} className="text-sm" data-testid={`audit-log-item-${index}`}>
                            <p className="font-medium">
                              {(auditActionLabels[entry.action] || entry.action)} • {entry.actor_name} ({roleLabels[entry.actor_role] || entry.actor_role})
                            </p>
                            <p className="text-xs text-muted-foreground">
                              {format(parseISO(entry.timestamp), 'dd/MM/yyyy HH:mm')}
                            </p>
                          </div>
                        ))}
                      </div>
                    </ScrollArea>
                  </div>
                )}
                <div>
                  <p className="text-sm text-muted-foreground">Estado</p>
                  <Badge className={`badge-${selectedRequest.status}`} data-testid="view-request-status">
                    {statusLabels[selectedRequest.status]}
                  </Badge>
                </div>
                {isManagerCreated(selectedRequest) && (
                  <div>
                    <p className="text-sm text-muted-foreground">Origem</p>
                    <Badge variant="secondary" data-testid="view-request-created-by">
                      Criado pelo gestor
                    </Badge>
                  </div>
                )}
                {selectedRequest?.is_paid !== undefined && (
                  <div>
                    <p className="text-sm text-muted-foreground">Remunerado</p>
                    <p className="font-medium" data-testid="view-request-is-paid">
                      {selectedRequest.is_paid ? 'Sim' : 'Não'}
                    </p>
                  </div>
                )}
              </div>
              {selectedRequest.observation && (
                <div>
                  <p className="text-sm text-muted-foreground">Observação do Colaborador</p>
                  <p className="font-medium">{selectedRequest.observation}</p>
                </div>
              )}
              {selectedRequest.admin_response && (
                <div>
                  <p className="text-sm text-muted-foreground">Resposta da Administração</p>
                  <p className="font-medium">{selectedRequest.admin_response}</p>
                </div>
              )}
              <div>
                <p className="text-sm text-muted-foreground">Data do Pedido</p>
                <p className="font-medium">{format(parseISO(selectedRequest.created_at), 'dd/MM/yyyy HH:mm')}</p>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
